"""P0 HOTFIX (18.10.2026) — инициатива: реальные блокеры автономных сообщений.

Источник: `plans/features/p0-save-init-ux/source-p0-hotfix-2026-10-18.md` §1
(«Инициатива — автономные сообщения не появляются») + read-only диагностика
прода 18.10.2026 (см. `plans/features/p0-save-init-ux/evidence/initiatives/`).

Свидетели (RED → GREEN), по одному на подтверждённый блокер:

1. **Курсор в многолетней истории** — наблюдение обязано идти по АКТУАЛЬНОЙ
   переписке (прод: cursor=155734 при max(id)=2350637; 200 строк / 300 с
   ≈ 38 суток догоняния). История не уничтожается, по древним обсуждениям
   инициатива не генерируется.
2. **Одно обращение к боту выбрасывало всё окно** (`direct_address_seen`) —
   прямые обращения и самостоятельные возможности разделены: смешанное окно
   доходит до оценки, а окно из одних обращений по-прежнему молчит.
   Словоформы «ботаник/ботва/робот» больше не считаются обращением.
3. **Cooldown считался от ЛЮБОГО вывода бота** — антифлуд (после любого
   вывода) и cooldown инициативы (после инициативных) разделены: обычный
   Direct не блокирует автономную инициативу на `min_gap_seconds`.
4. **Эфемерный повод терял свой контекст** — наблюдатель передаёт повод
   (goal/kind/origin/created_at) в существующий единый вход, поэтому L1/L2
   Writer видят реальную цель, а SendRecheck реально проверяет «прямой запрос
   пришёл, пока готовился текст» (прод: opportunity → decision reply →
   l1_silent «цель не указана» → отправок нет).

TEST-LIFECYCLE: REGRESSION owner=P0-INIT-FIX/§1 (initiative blockers)
"""
from __future__ import annotations

import json
import time

import pytest

from services import chat_params
from services import direct_chat_service as dcs
from services import hot_config
from services import mca_events
from services import initiative_observer as obs
from services.database import DatabaseService

CHAT = -2026
BOT_ID = 999
YEAR = 365 * 24 * 3600


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
            message_id = 7000 + len(self.sent)

        return _Msg()


class _FakeWriter:
    """Существующий Direct-контур: L1-решение → L2-текст (записывает входящую
    строку намерения — именно её терял observer-путь)."""

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
               media_type="text", is_forward=0) -> int:
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, ?, 'u', ?, NULL)",
        (user_id, chat_id, text, ts, media_type, is_forward))
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


@pytest.fixture(autouse=True)
def _clean():
    mca_events.reset_pending()
    _reset_caches()
    yield
    mca_events.reset_pending()
    _reset_caches()


# ═══ 1. Курсор: наблюдение актуальной переписки ═════════════════════════════

@pytest.mark.asyncio
async def test_stale_cursor_is_anchored_to_live_conversation(tmp_path):
    """RED до P0-фикса: курсор ползёт по многолетней истории.

    Прод-факты: cursor=155734 vs max(id)=2350637 → наблюдатель не видел
    живой чат (38 суток догоняния), а «наблюдённые» счётчики наполнялись
    древними репликами.
    """
    db = await _db(tmp_path, "p0_anchor.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    try:
        # Многолетний backlog (общее число строк ≫ одного прохода).
        for i in range(1200):
            await _msg(db, text="древняя болтовня %d" % i,
                       ts=now - 3 * YEAR + i)
        backlog_max = 0
        cursor = await db.db.execute("SELECT MAX(id) AS mx FROM smart_messages")
        backlog_max = int((await cursor.fetchone())["mx"])
        # Живой чат прямо сейчас.
        for i in range(6):
            await _msg(db, text="живой разговор сегодня %d" % i,
                       ts=now - 60 + i)
        bot, writer, llm = _FakeBot(), _FakeWriter(), _FakeLLM()
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload = await _payload(db)
        target = int(payload[obs.CURSOR_KEY])
        assert target > backlog_max, (
            "курсор остался в истории: %s (живой хвост начинается после %s)"
            % (target, backlog_max))
        assert float(payload["counters"].get("scan_anchored") or 0) >= 1
        # Наблюдаются ЖИВЫЕ реплики, а не древние.
        assert payload["counters"]["observed"] < 300
        # История не уничтожена.
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages")
        assert int((await cursor.fetchone())["c"]) == 1206
        # И живой контекст дошёл до оценщика.
        assert llm.calls == 1
        assert "живой разговор сегодня 5" in llm.prompts[0][1]["content"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_live_cursor_is_not_rewound(tmp_path):
    """Подтяжка курсора — только ВПЕРЁД: назад наблюдение не откатывается."""
    db = await _db(tmp_path, "p0_anchor_fwd.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    try:
        for i in range(6):
            await _msg(db, text="живая реплика %d" % i, ts=now - 30 + i)
        for i in range(6):
            await _msg(db, text="ещё живые %d" % i, ts=now - 10 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=_FakeLLM())
        first = int((await _payload(db))[obs.CURSOR_KEY])
        for i in range(6):
            await _msg(db, text="новое окно %d" % i, ts=now + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=_FakeLLM())
        second = int((await _payload(db))[obs.CURSOR_KEY])
        assert second > first
    finally:
        await db.close()


# ═══ 2. Прямые обращения vs самостоятельные возможности ═════════════════════

def test_bot_call_detection_ignores_words_containing_bot():
    """«ботаник/ботва/робот» — НЕ обращение к боту (ложные срабатывания
    прежнего `\\bбот\\w*` глушили окно в русском чате)."""
    assert obs.addressed_to_bot("бот, что скажешь?")
    assert obs.addressed_to_bot("напиши боту про поездку")
    assert obs.addressed_to_bot("ботик, привет")
    assert not obs.addressed_to_bot("он ботаник, но прикольный")
    assert not obs.addressed_to_bot("ботва на огороде выросла")
    assert not obs.addressed_to_bot("робот-пылесос сломался")
    assert obs.addressed_to_bot("эй @permsoc_bot помоги",
                                bot_username="PERMsoc_bot")


@pytest.mark.asyncio
async def test_mixed_window_with_bot_mention_is_still_evaluated(tmp_path):
    """RED до P0-фикса: одно «бот …» в окне выбрасывало ВСЁ окно."""
    db = await _db(tmp_path, "p0_mixed.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    llm = _FakeLLM()
    try:
        for i in range(6):
            await _msg(db, user_id=42 + i % 2,
                       text="обсуждаем поездку, вариант %d" % i, ts=now - 90 + i)
        await _msg(db, user_id=7, text="бот, а ты что думаешь?",
                   ts=now - 80)
        for i in range(6):
            await _msg(db, user_id=42 + i % 2,
                       text="давай в горы всё-таки %d" % i, ts=now - 60 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert llm.calls == 1, payload["counters"]["eval_skips"]
        assert payload["counters"]["eval_skips"].get("direct_address_seen") \
            in (None, 0)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_window_with_only_bot_addresses_still_silent(tmp_path):
    """Защита сохранена: окно из одних обращений к боту не оценивается."""
    db = await _db(tmp_path, "p0_pure_direct.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    llm = _FakeLLM()
    try:
        for i in range(6):
            await _msg(db, text="бот, ответь на вопрос %d" % i, ts=now - 60 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("direct_address_seen") >= 1
        assert llm.calls == 0
    finally:
        await db.close()


# ═══ 3. Антифлуд ≠ cooldown инициативы ══════════════════════════════════════

@pytest.mark.asyncio
async def test_direct_reply_does_not_block_initiative(tmp_path):
    """RED до P0-фикса: обычный Direct сбрасывал паузу инициативы."""
    db = await _db(tmp_path, "p0_gap_direct.db")
    _caches({CHAT: _limits(**{"initiative.min_gap_seconds": 7200})})
    now = int(time.time())
    llm = _FakeLLM()
    try:
        await db.record_bot_output(chat_id=CHAT, bot_user_id=BOT_ID,
                                   output_kind="direct_reply",
                                   content_text="ответ в чат",
                                   sent_at=now - 600)
        for i in range(6):
            await _msg(db, text="живой разговор %d" % i, ts=now - 120 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert llm.calls == 1, payload["counters"]["eval_skips"]
        assert payload["counters"]["eval_skips"].get("min_gap") in (None, 0)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_initiative_cooldown_still_blocks_after_initiative(tmp_path):
    """Cooldown инициативы жив: пауза считается от инициативных реплик."""
    db = await _db(tmp_path, "p0_gap_init.db")
    _caches({CHAT: _limits(**{"initiative.min_gap_seconds": 7200})})
    now = int(time.time())
    llm = _FakeLLM()
    try:
        await db.record_bot_output(chat_id=CHAT, bot_user_id=BOT_ID,
                                   output_kind="initiative_reply",
                                   content_text="инициатива",
                                   sent_at=now - 600)
        for i in range(6):
            await _msg(db, text="живой разговор %d" % i, ts=now - 120 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("min_gap") >= 1
        assert llm.calls == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_anti_flood_blocks_right_after_any_output(tmp_path):
    """Антифлуд жив: сразу после ЛЮБОГО вывода бота инициатива не говорит."""
    db = await _db(tmp_path, "p0_antiflood.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    llm = _FakeLLM()
    try:
        await db.record_bot_output(chat_id=CHAT, bot_user_id=BOT_ID,
                                   output_kind="rich_message",
                                   content_text="сводка",
                                   sent_at=now - 30)
        for i in range(6):
            await _msg(db, text="живой разговор %d" % i, ts=now - 20 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("anti_flood") >= 1
        assert llm.calls == 0
    finally:
        await db.close()


# ═══ 4. Цепочка наблюдателя до отправки: повод + Writer + recheck ══════════

@pytest.mark.asyncio
async def test_opportunity_carries_context_into_writer_and_sends(tmp_path):
    """RED до P0-фикса: L1/L2 получали пустую строку намерения.

    Прод-факты 18.10.2026: opportunity (useful_info/development, action=say)
    → decision action=reply → `l1_silent` (в событии — «default») → ни одной
    отправки, writer-события нет. Повод терялся между наблюдателем и Writer.
    """
    db = await _db(tmp_path, "p0_chain.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    bot, writer = _FakeBot(), _FakeWriter()
    llm = _FakeLLM([_verdict(goal="участники выбирают маршрут поездки")])
    try:
        for i in range(6):
            await _msg(db, user_id=42 + i % 2,
                       text="куда едем в отпуск, вариант %d" % i,
                       ts=now - 90 + i)
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload = await _payload(db)
        # Цепочка дошла до отправки (fake-транспорт, не боевой чат).
        assert payload["counters"]["sent"] == 1
        assert bot.sent and bot.sent[0][0] == CHAT
        # Writer видел РЕАЛЬНЫЙ повод, а не пустую строку.
        assert writer.rows, "L1/L2 не вызывались с контекстом повода"
        row = writer.rows[0]
        assert row.get("goal") == "участники выбирают маршрут поездки"
        assert row.get("origin") == "observer_opportunity"
        assert int(row.get("created_at") or 0) > 0
        # Отправка отражена инициативным kind в ledger (cooldown инициативы).
        cursor = await db.db.execute(
            "SELECT output_kind FROM mca_bot_outputs WHERE chat_id = ? "
            "ORDER BY output_id DESC LIMIT 1", (CHAT,))
        assert (await cursor.fetchone())["output_kind"] == "initiative_reply"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_pending_direct_request_stops_observer_initiative(tmp_path,
                                                               monkeypatch):
    """Recheck перед отправкой РАБОТАЕТ для observer-повода (RED до фикса:
    пустой контекст → проверка молча пропускалась и инициатива уходила).

    Прямое обращение к боту, пришедшее пока готовился текст, отменяет
    отправку (`direct_pending`) — инициатива не соревнуется с Direct.
    """
    db = await _db(tmp_path, "p0_recheck.db")
    _caches({CHAT: _limits()})
    now = int(time.time())
    bot, writer = _FakeBot(), _FakeWriter()
    seen: list = []

    async def _fresh(db_, chat_id, intent_row, **kw):
        seen.append(dict(intent_row or {}))
        return dcs._mca_intents.RecheckContext(
            enabled=True, intent_row=dict(intent_row or {}),
            direct_request_pending=True, context_version="fresh-1",
            evaluated_context_version=str(kw.get(
                "evaluated_context_version") or "") or None,
            recheck_attempts=int(kw.get("recheck_attempts") or 0))

    monkeypatch.setattr(dcs, "build_fresh_recheck_context", _fresh)
    llm = _FakeLLM([_verdict()])
    try:
        for i in range(6):
            await _msg(db, text="разговор про маршрут %d" % i, ts=now - 60 + i)
        await obs.observe_tick(db, bot=bot, writer_service=writer, llm=llm)
        payload = await _payload(db)
        assert seen, "свежий recheck не выполнялся (пустой контекст)"
        assert payload["counters"]["sent"] == 0
        assert bot.sent == []
    finally:
        await db.close()
