"""P0 INIT-ARCH-FIX (18.10.2026) — архитектурные доработки наблюдателя инициативы.

Источник: `plans/features/p0-save-init-ux/source-p0-followup-2026-10-18.md` §1
(пп. 1.2 CATCHUP, 1.3 CONTEXT, 1.4 SIGNALS, 1.5 SMALL, 1.6 BACKFILL) +
gap-check `plans/features/p0-save-init-ux/evidence/init-arch-gap.md` §2.1–2.5.

Свидетели (RED → GREEN по каждому пункту):

* **BACKFILL** (1.6): импорт старой истории (`import_key` задан) не
  наблюдается — ни `observed`/`pending`, ни окна оценки, ни поводов; живые
  сообщения продолжают работать, архив не разрушается.
* **CONTEXT** (1.3): окно оценки адаптивное — база 10, рост по накоплению до
  явного капа 200 (10/60/300 сообщений → окно 10/60/200); жёстких «14» нет.
* **CATCHUP** (1.2): при большом разрыве watermark пропущенный интервал
  сжимается bounded-дайджестом (ОДИН LLM-стрим, ≤200 реплик-выборки,
  bounded-подсчёт «сколько пропущено»); недоступность LLM → fail-open к
  актуальному окну (без дайджеста, как раньше).
* **SIGNALS** (1.4): reply-связи размечены в промпте окна; `addressee_user_id`
  и `rationale` вердикта не теряются — едут в контекст повода к Writer/L1.
* **SMALL** (1.5): новый чат 5–20 сообщений на заводском профиле `normal`
  доходит до полноценного повода: порог не требует больше истории, чем у чата
  есть (но не ниже floor 4); устоявшийся чат ждёт порог профиля как раньше.

TEST-LIFECYCLE: REGRESSION owner=P0-INIT-ARCH/§1 (initiative arch gaps)
TEST-LIFECYCLE: CONTRACT owner=P0-INIT-ARCH/§1.3 (adaptive eval window)
"""
from __future__ import annotations

import json
import time

import pytest

from services import chat_params
from services import hot_config
from services import mca_events
from services import initiative_observer as obs
from services.database import DatabaseService

CHAT = -2026
BOT_ID = 999
YEAR = 365 * 24 * 3600
IMPORT_EPOCH = 1700000000          # «многолетняя» дата импорта (2023-11)


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat=None):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


def _caches(by_chat=None, hot=None):
    hot_config.set_config_cache(_FakeHot(hot or {}))
    chat_params.set_chat_params_cache(_FakeChatParams(by_chat or {}))


def _reset_caches():
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


class _FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text)))

        class _Msg:
            message_id = 8000 + len(self.sent)

        return _Msg()


class _FakeWriter:
    def __init__(self, action="reply", text="Реплика инициативы."):
        self.action = action
        self.text = text
        self.rows: list = []
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        from services.direct_l1 import L1Plan
        self.rows.append(dict(intent_row or {}))
        return L1Plan(action=self.action, confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        self.rows.append(dict(intent_row or {}))
        return self.text


class _FakeLLM:
    def __init__(self, verdicts=()):
        self.verdicts = list(verdicts)
        self.calls = 0
        self.prompts: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append([dict(m) for m in messages])
        if self.verdicts:
            return self.verdicts.pop(0)
        return json.dumps({"opportunity": False})


class _FailFirstLLM(_FakeLLM):
    """Первый LLM-вызов (дайджест) падает → fail-open к актуальному окну."""

    async def generate(self, messages, **kwargs):
        if self.calls == 0:
            self.calls += 1
            self.prompts.append([dict(m) for m in messages])
            raise RuntimeError("digest llm down")
        return await super().generate(messages, **kwargs)


def _verdict(**kw) -> str:
    base = {"opportunity": True, "kind": "development", "action": "say",
            "horizon": "now", "addressee_user_id": None,
            "topic_key": "tema", "goal": "участники обсуждают поездку",
            "rationale": "есть что добавить"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


async def _db(tmp_path, name) -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, *, chat_id=CHAT, user_id=42, text="реплика", ts=None,
               media_type="text", is_forward=0, reply_to_id=None,
               import_key=None) -> int:
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id, "
        "import_key) VALUES (?, ?, ?, ?, ?, ?, 'u', ?, NULL, ?)",
        (user_id, chat_id, text, reply_to_id, ts, media_type, is_forward,
         import_key))
    await db.db.commit()
    return cursor.lastrowid


async def _payload(db) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY COALESCE(finished_at, updated_at) DESC, rowid DESC LIMIT 1",
        (obs.OBSERVE_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads((row["payload"] if row else "{}") or "{}")


def _entry(payload, chat_id=CHAT) -> dict:
    return dict((payload.get("chats") or {}).get(str(chat_id)) or {})


def _limits(**kw) -> dict:
    base = {"initiative.frequency_profile": "active",
            "initiative.eval_min_messages": 4,
            "initiative.eval_min_interval_seconds": 0,
            "initiative.min_gap_seconds": 0,
            "initiative.max_replies_per_day": 10,
            "initiative.eval_llm_budget_per_day": 10}
    base.update(kw)
    return base


def _window_lines(prompt: str) -> list:
    block = str(prompt or "")
    try:
        block = block.split("<Fresh_Chat_Window>", 1)[1]
        block = block.split("</Fresh_Chat_Window>", 1)[0]
    except IndexError:
        return []
    return [ln for ln in block.strip().splitlines() if ln.strip()]


@pytest.fixture(autouse=True)
def _clean():
    # Гигиена сессии pytest: `mca_random_source` — модульный singleton,
    # связываемый с БД первого теста, дошедшего до `handle_initiative`
    # (цепочка повода делает probability-draw). Без сброса он держит
    # ЗАКРЫТУЮ БД этого файла, и draw следующих файлов сессии падает
    # (`no active connection`) → инициатива откладывается `random_fallback`.
    from services import mca_random_source
    mca_random_source.reset_service()
    mca_events.reset_pending()
    _reset_caches()
    yield
    mca_random_source.reset_service()
    mca_events.reset_pending()
    _reset_caches()


# ═══ 1. BACKFILL: импорт старой истории не наблюдается ═══════════════════════

@pytest.mark.asyncio
async def test_imported_history_is_invisible_for_observer(tmp_path):
    """RED до фикса: импортированные годы назад реплики наблюдались как
    «новые» (новые id, старые ts) — провоцировали реакции на древние события."""
    db = await _db(tmp_path, "ia_import.db")
    _caches({CHAT: _limits()})
    bot, writer = _FakeBot(), _FakeWriter()
    llm = _FakeLLM([_verdict(goal="древнее событие")])
    try:
        for i in range(300):
            await _msg(db, text="старый импорт %d" % i,
                       ts=IMPORT_EPOCH + i, import_key="k:imp:%d" % i)
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload = await _payload(db)
        counters = payload["counters"]
        # Импорт не наблюдался: ни строк, ни накопления, ни LLM, ни поводов.
        assert counters["observed"] == 0, counters
        assert counters["evals"] == 0, counters
        assert counters["opportunities"] == 0, counters
        assert llm.calls == 0
        assert int(_entry(payload).get("pending") or 0) == 0
        # Живые новые сообщения работают как раньше.
        live_ids = []
        for i in range(6):
            live_ids.append(await _msg(db, text="живой разговор %d" % i,
                                       ts=int(time.time()) - 60 + i))
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload2 = await _payload(db)
        assert payload2["counters"]["observed"] >= 6
        assert llm.calls == 1, payload2["counters"]["eval_skips"]
        prompt = llm.prompts[-1][1]["content"]
        assert "живой разговор 5" in prompt
        assert "старый импорт 5" not in prompt
        # Архив не разрушен (ничего не удаляем — только не наблюдаем).
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages WHERE chat_id = ?",
            (CHAT,))
        assert int((await cursor.fetchone())["c"]) == 306
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_live_readers_ignore_imported_rows(tmp_path):
    """Платформенная конвенция «живое = import_key IS NULL»: темп, живые
    сообщения за окно и отставание курсора не раздуваются импортом."""
    db = await _db(tmp_path, "ia_readers.db")
    now = int(time.time())
    try:
        for i in range(5):
            await _msg(db, text="импорт-свежий %d" % i, ts=now - 100 + i,
                       import_key="k:recent:%d" % i)
        live_max = 0
        for i in range(3):
            live_max = await _msg(db, text="живое %d" % i, ts=now - 50 + i)
        live = await obs.live_messages(db, CHAT, now=now)
        assert live == 3
        rate = await obs.recent_message_rate(db, CHAT, now=now)
        assert abs(rate * obs.RATE_WINDOW_SECONDS - 3) < 1e-6
        lag = await obs._cursor_lag(db, {}, {"last_seen_msg_id": live_max - 1})
        assert lag == 1, "импорт не должен раздувать отставание курсора"
    finally:
        await db.close()


# ═══ 2. CONTEXT: адаптивное окно оценки (10 / 50–200+) ═══════════════════════

def test_adaptive_window_resolver_has_base_and_explicit_cap():
    assert obs.EVAL_WINDOW_BASE_MESSAGES == 10
    assert obs.EVAL_WINDOW_MAX_MESSAGES == 200
    cases = [(0, 10), (3, 10), (10, 10), (14, 14), (60, 60), (199, 199),
             (300, 200), (5000, 200)]
    for backlog, expected in cases:
        assert obs.resolve_window_messages(backlog) == expected, backlog


@pytest.mark.parametrize("size,expected", [(10, 10), (60, 60), (300, 200)])
@pytest.mark.asyncio
async def test_eval_window_is_adaptive_by_volume(tmp_path, size, expected):
    """RED до фикса: окно всегда 14, объёмное обсуждение обрезалось."""
    db = await _db(tmp_path, "ia_window_%d.db" % size)
    _caches({CHAT: _limits()})
    llm = _FakeLLM()
    base = int(time.time()) - 3600
    try:
        for i in range(size):
            await _msg(db, text="поток беседы %d" % i, ts=base + i)
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=llm) == "completed"
        assert llm.calls == 1
        lines = _window_lines(llm.prompts[-1][1]["content"])
        assert len(lines) == expected, (size, len(lines))
        # Самая свежая реплика — в окне всегда.
        assert "поток беседы %d" % (size - 1) in llm.prompts[-1][1]["content"]
    finally:
        await db.close()


# ═══ 3. CATCHUP: bounded-дайджест пропущенного интервала ═════════════════════

@pytest.mark.asyncio
async def test_large_watermark_gap_is_digested_not_sequentially_evaluated(
        tmp_path):
    """RED до фикса: при разрыве watermark «середина» пропускалась молча —
    оценка шла только по актуальному окну без смыслового сжатия."""
    db = await _db(tmp_path, "ia_digest.db")
    _caches({CHAT: _limits()})
    bot, writer = _FakeBot(), _FakeWriter()
    now = int(time.time())
    try:
        # Первое наблюдение: watermark двигается вперёд (база для разрыва).
        for i in range(10):
            await _msg(db, text="первое окно %d" % i, ts=now - 3000 + i)
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=_FakeLLM()) == "completed"
        entry = _entry(await _payload(db))
        assert int(entry.get("last_eval_msg_id") or 0) > 0
        # Пропущено 1000 реплик (условно «сотни/тысячи сообщений»).
        for i in range(1000):
            if i == 5:
                text = "РАННЯЯ-ЧАСТЬ-РАЗРЫВА-ЗА-КАПОМ"
            elif i == 796:
                text = "МАРКЕР-СЕРЕДИНЫ интервала"
            else:
                text = "лавина сообщений #%d" % i
            await _msg(db, text=text, ts=now - 1000 + i)
        llm = _FakeLLM([
            "участники обсуждали лавину сообщений и планы",   # дайджест
            _verdict(goal="лавина сообщений"),                # оценка
        ])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        # РОВНО два стрима: один дешёвый дайджест + одна оценка окна —
        # тысячи пропущенных реплик НЕ оцениваются последовательно.
        assert llm.calls == 2, llm.calls
        digest_prompt = llm.prompts[0][1]["content"]
        eval_prompt = llm.prompts[1][1]["content"]
        # Дайджест видит bounded-выборку пропущенного (последние ≤200 реплик).
        assert "МАРКЕР-СЕРЕДИНЫ интервала" in digest_prompt
        assert "первое окно 5" not in digest_prompt
        # Самое начало разрыва за капом выборки — не в дайджесте.
        assert "РАННЯЯ-ЧАСТЬ-РАЗРЫВА-ЗА-КАПОМ" not in digest_prompt
        # Оценка получает сжатие пропущенного как bounded-блок.
        assert "<Skipped_Chat_Digest>" in eval_prompt
        assert "участники обсуждали лавину сообщений" in eval_prompt
        assert "Пропущено" in eval_prompt  # статистика пропущенного (bound)
        # Актуальное окно — свежие 200 реплик (кап), не тысячи.
        assert len(_window_lines(eval_prompt)) == 200
        # Watermark догнал живой чат: тысячи окон не жуются.
        payload = await _payload(db)
        entry2 = _entry(payload)
        assert int(entry2.get("last_eval_msg_id") or 0) >= 1000
        assert payload["counters"]["evals"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_small_gap_needs_no_digest(tmp_path):
    """Малый разрыв (окно покрывает всё) — лишнего LLM-стрима нет."""
    db = await _db(tmp_path, "ia_gap_small.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    try:
        for i in range(10):
            await _msg(db, text="первое окно %d" % i, ts=now - 900 + i)
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=_FakeLLM()) == "completed"
        for i in range(30):
            await _msg(db, text="продолжение %d" % i, ts=now - 300 + i)
        llm = _FakeLLM()
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=llm) == "completed"
        assert llm.calls == 1, llm.calls
        assert "<Skipped_Chat_Digest>" not in llm.prompts[-1][1]["content"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_digest_failure_is_fail_open_to_actual_window(tmp_path):
    """Недоступность LLM на дайджесте → оценка идёт по актуальному окну."""
    db = await _db(tmp_path, "ia_digest_fail.db")
    _caches({CHAT: _limits()})
    bot, writer = _FakeBot(), _FakeWriter()
    now = int(time.time())
    try:
        for i in range(10):
            await _msg(db, text="первое окно %d" % i, ts=now - 3000 + i)
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=_FakeLLM()) == "completed"
        for i in range(1000):
            await _msg(db, text="лавина сообщений #%d" % i,
                       ts=now - 1000 + i)
        llm = _FailFirstLLM([_verdict(goal="лавина")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        assert llm.calls == 2, llm.calls
        assert "<Skipped_Chat_Digest>" not in llm.prompts[-1][1]["content"]
        payload = await _payload(db)
        assert payload["counters"]["evals"] == 2
        assert payload["counters"]["opportunities"] == 1
    finally:
        await db.close()


# ═══ 4. SIGNALS: reply-связи и адресат/обоснование не теряются ══════════════

@pytest.mark.asyncio
async def test_reply_links_and_addressee_reach_prompt_and_context(tmp_path):
    """RED до фикса: `reply_to_id` не доходил до промпта, `addressee_user_id`
    и `rationale` вердикта выбрасывались молча."""
    db = await _db(tmp_path, "ia_signals.db")
    _caches({CHAT: _limits()})
    bot, writer = _FakeBot(), _FakeWriter()
    now = int(time.time())
    try:
        a = await _msg(db, user_id=42, text="обсуждаем маршрут поездки",
                       ts=now - 300)
        b = await _msg(db, user_id=7, text="а какой бюджет",
                       ts=now - 290, reply_to_id=a)
        await _msg(db, user_id=42, text="давай в горы всё-таки",
                   ts=now - 280, reply_to_id=b)
        await _msg(db, user_id=7, text="я тоже за горы", ts=now - 270)
        await _msg(db, user_id=42, text="тогда решаем сегодня", ts=now - 260)
        await _msg(db, user_id=7, text="предлагаю июнь", ts=now - 250)
        llm = _FakeLLM([_verdict(
            goal="выбрать маршрут поездки", addressee_user_id=42,
            rationale="участники обсуждают маршрут и бюджет")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        prompt = llm.prompts[-1][1]["content"]
        # Reply-связи размечены: id реплики и ссылка «ответ на».
        assert "[msg:%d]" % a in prompt
        assert "(ответ на msg:%d)" % a in prompt
        assert "(ответ на msg:%d)" % b in prompt
        # Адресат и обоснование не теряются — доезжают до контекста повода.
        assert writer.rows, "Writer не вызывался"
        row = writer.rows[0]
        assert row.get("addressee_user_id") == 42
        assert row.get("rationale") == "участники обсуждают маршрут и бюджет"
        payload = await _payload(db)
        assert payload["counters"]["sent"] == 1
    finally:
        await db.close()


def test_opportunity_row_parity_without_new_signals():
    """Без адресата/обоснования строка-контекст не меняется (паритет)."""
    row = obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="цель", fallback="development",
        rows=[])
    assert "addressee_user_id" not in row
    assert "rationale" not in row
    row2 = obs.build_opportunity_row(
        CHAT, kind="topic_interest", goal="цель", fallback="development",
        rows=[], addressee_user_id=42, rationale="обоснование")
    assert row2["addressee_user_id"] == 42
    assert row2["rationale"] == "обоснование"


# ═══ 5. SMALL: маленький/новый чат не требует большой истории ════════════════

@pytest.mark.parametrize("size", [6, 12, 20])
@pytest.mark.asyncio
async def test_new_small_chat_normal_profile_reaches_full_opportunity(
        tmp_path, size):
    """RED до фикса (size=6): «5–7 сообщений → ждать порога 8» не давало
    новому чату ни одного шанса, хотя повод уже полноценный."""
    db = await _db(tmp_path, "ia_small_%d.db" % size)
    # Заводской профиль: только он и задан — остальное дефолты каталога.
    _caches({CHAT: {"initiative.frequency_profile": "normal"}})
    bot, writer = _FakeBot(), _FakeWriter()
    now = int(time.time())
    try:
        for i in range(size):
            await _msg(db, text="первый разговор в новом чате %d" % i,
                       ts=now - 300 + i)
        llm = _FakeLLM([_verdict(goal="новый чат начал обсуждать планы")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload = await _payload(db)
        counters = payload["counters"]
        assert counters["evals"] == 1, counters["eval_skips"]
        assert llm.calls == 1
        assert counters.get("eval_skips", {}).get("not_enough_messages", 0) \
            == 0, counters["eval_skips"]
        assert counters["sent"] == 1
        assert writer.rows and writer.rows[0].get("goal") == \
            "новый чат начал обсуждать планы"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_established_chat_still_waits_for_profile_threshold(tmp_path):
    """Паритет качества: у чата с историей порог профиля остаётся каноном."""
    db = await _db(tmp_path, "ia_established.db")
    _caches({CHAT: {"initiative.frequency_profile": "normal"}})
    now = int(time.time())
    try:
        for i in range(20):
            await _msg(db, text="историческая беседа %d" % i,
                       ts=now - 600 + i)
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=_FakeLLM()) == "completed"
        for i in range(3):
            await _msg(db, text="редкое продолжение %d" % i, ts=now - 60 + i)
        llm2 = _FakeLLM()
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=llm2) == "completed"
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get(
            "not_enough_messages", 0) >= 1
        assert llm2.calls == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_required_messages_never_below_quality_floor(tmp_path):
    """Чат из 3 реплик не оценивается: floor 4 сохраняет качество оценки."""
    db = await _db(tmp_path, "ia_floor.db")
    _caches({CHAT: {"initiative.frequency_profile": "normal"}})
    now = int(time.time())
    try:
        for i in range(3):
            await _msg(db, text="совсем новый чат %d" % i, ts=now - 120 + i)
        llm = _FakeLLM()
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=llm) == "completed"
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get(
            "not_enough_messages", 0) >= 1
        assert llm.calls == 0
        need = await obs.required_messages_for_chat(db, CHAT, 8)
        assert need == obs.MIN_EVAL_MESSAGES_FLOOR
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_block_state_pending_gate_uses_same_threshold(tmp_path):
    """Панель «что мешает» показывает ТОТ ЖЕ порог, что боевой путь."""
    db = await _db(tmp_path, "ia_gate.db")
    _caches({CHAT: {"initiative.frequency_profile": "normal"}})
    now = int(time.time())
    try:
        for i in range(3):
            await _msg(db, text="маленький чат %d" % i, ts=now - 120 + i)
        gates = await obs.chat_block_state(db, CHAT)
        pending = [i for i in gates["items"] if i["gate"] == "pending"]
        assert pending and pending[0]["limit"] == obs.MIN_EVAL_MESSAGES_FLOOR
        # Чат с историей — порог профиля (8), как раньше.
        for i in range(17):
            await _msg(db, text="история %d" % i, ts=now - 100 + i)
        gates2 = await obs.chat_block_state(db, CHAT)
        pending2 = [i for i in gates2["items"] if i["gate"] == "pending"]
        assert pending2 and pending2[0]["limit"] == 8
    finally:
        await db.close()
