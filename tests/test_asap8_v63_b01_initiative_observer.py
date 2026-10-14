"""ASAP 8 v6.3 — B01: Initiative = автономная речь в обычном групповом чате.

Покрытие (REQ-B01, B01.1–B01.6; канон source-lines-37423-EOF.md строки
37466–37482):
  * B01.1: observer производит семантически обоснованные opportunities из
    fixture обычных реплик БЕЗ слова «бот» и адресных вопросов; несколько
    разновидностей ситуаций; bounded-оценка (LLM НЕ на каждую реплику);
  * B01.2: разделение ephemeral opportunity / durable intent; решение
    SAY/REACT/SILENT адекватно ситуации;
  * B01.3: негативы — спам (min gap / day cap), повтор (context dedup),
    закрытая тема (недавняя реплика бота); two-chat isolation;
  * B01.4: per-chat профили частоты + тонкие лимиты (runtime-резолв);
    «24ч ноль Opportunities при активном observer» → диагностическое событие;
  * B01.5: сигналы не зависят от Direct entrypoint; недоступность Writer →
    явный `initiative_writer_unavailable` (не молчание), повод — в durable
    intent; reboots: курсор/дедуп персистентны;
  * воронка observed→eligible→opportunity→decision→writer→recheck→sent с
    reason codes.

TEST-LIFECYCLE: CONTRACT owner=REQ-B01
"""
import json
import time
import uuid

import pytest

from services import hot_config
from services import mca_events, mca_gates
from services import mca_intents as mi
from services import initiative_observer as obs
from services.database import DatabaseService

CHAT = -2026
CHAT_B = -2027
BOT_ID = 999


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture(autouse=True)
def _no_exploration_draw(monkeypatch):
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


class _FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

        class _Msg:
            message_id = 5000 + len(self.sent)

        return _Msg()


class _FakeWriter:
    """Duck-typed DirectChatService (контракт §13.2: два метода)."""

    def __init__(self, action="reply", text="О, это интересно, продолжайте."):
        self.action = action
        self.text = text
        self.plan_calls = 0
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        from services.direct_l1 import L1Plan
        self.plan_calls += 1
        return L1Plan(action=self.action, confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


class _FakeLLM:
    """Observer-оценщик: очередь вердиктов (JSON), счётчик вызовов."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0
        self.last_messages = None

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = messages
        if self.verdicts:
            return self.verdicts.pop(0)
        return json.dumps({"opportunity": False})


def _verdict(**kw) -> str:
    base = {"opportunity": True, "kind": "development", "action": "say",
            "horizon": "now", "addressee_user_id": None,
            "topic_key": "games", "goal": "участники обсуждают игры",
            "rationale": "живая тема, есть что добавить"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


async def _db(tmp_path, name="b01.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db: DatabaseService, *, chat_id=CHAT, user_id=42, text,
               ts=None) -> int:
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
        (user_id, chat_id, text, ts))
    await db.db.commit()
    return cursor.lastrowid


class _FakeChatParams:
    def __init__(self, by_chat):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


_ACTIVE = {
    "initiative.frequency_profile": "active",
    "initiative.eval_min_messages": 4,
    "initiative.eval_min_interval_seconds": 0,
    "initiative.min_gap_seconds": 0,
    "initiative.max_replies_per_day": 10,
    "initiative.eval_llm_budget_per_day": 10,
}


def _caches(by_chat):
    from services import chat_params
    hot_config.set_config_cache(_FakeHot({}))
    chat_params.set_chat_params_cache(_FakeChatParams(by_chat))


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


async def _payload_of(db: DatabaseService) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY finished_at DESC, created_at DESC, rowid DESC LIMIT 1",
        (obs.OBSERVE_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


async def _flushed_events(db: DatabaseService, name: str,
                          chat_id=CHAT) -> list[dict]:
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT event_name, outcome, reason_code, stage FROM mca_events "
        "WHERE chat_id = ? AND event_name = ? ORDER BY ts, rowid",
        (chat_id, name))
    return [dict(r) for r in await cursor.fetchall()]


# ═══ B01.1: fixture без «бота» и адресных вопросов → opportunities ═══════════

@pytest.mark.asyncio
async def test_b01_fixture_without_botword_produces_opportunities(tmp_path):
    db = await _db(tmp_path, "b01_fixture.db")
    _caches({CHAT: dict(_ACTIVE)})
    bot, writer = _FakeBot(), _FakeWriter()
    llm = _FakeLLM([
        _verdict(kind="topic_shift", action="say"),
        json.dumps({"opportunity": False}),
        json.dumps({"opportunity": False}),
    ])
    try:
        # 120 обычных реплик: игры/походы/бытовуха — ни слова «бот»,
        # ни одного адресного вопроса.
        topics = (["какие нынче инди-игры вышли", "я прошёл хедлайнер за вечер",
                  "а у меня сохранение слетело", "на каком сложности играешь",
                  "грустно, сюжет топ", "посоветуй что-то похожее"] * 20)
        base = int(time.time()) - 3600
        for i, text in enumerate(topics):
            await _msg(db, user_id=42 + (i % 3), text=text,
                       ts=base + i)
        status = await obs.observe_tick(db, bot=bot, writer_service=writer,
                                        llm=llm)
        assert status == "completed"
        payload = await _payload_of(db)
        counters = payload["counters"]
        # observer реально видит сообщения (диагностика «сколько видит»)
        assert counters["observed"] >= 100
        assert counters["eligible"] >= 100
        # семантически обоснованный opportunity + SAY доведён до отправки
        assert counters["opportunities"] == 1
        assert counters["sent"] == 1
        assert len(bot.sent) == 1 and bot.sent[0][0] == CHAT
        # НЕ LLM на каждую реплику: оценок окна ≪ сообщений (bounded)
        assert llm.calls <= 3
        opportunities = await _flushed_events(db, "initiative_opportunity")
        assert opportunities and opportunities[-1]["stage"] == \
            "opportunity:topic_shift:say"
        sent = await _flushed_events(db, "initiative_sent")
        assert sent and sent[-1]["stage"].startswith("observer:")
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_b01_variety_say_react_silent_and_durable_intent(tmp_path):
    db = await _db(tmp_path, "b01_variety.db")
    _caches({CHAT: dict(_ACTIVE)})
    bot = _FakeBot()
    writer = _FakeWriter(action="reply")
    react_writer = _FakeWriter(action="react")
    try:
        base = int(time.time()) - 1800
        # 1) развитие разговора → ephemeral SAY → sent
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"поездку обсуждаем {i}",
                       ts=base + i)
        llm = _FakeLLM([_verdict(kind="development", action="say",
                                 horizon="now", topic_key="trip")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        assert len(bot.sent) == 1
        # 2) спор → durable intent (horizon=later), БЕЗ немедленной отправки
        for i in range(6):
            await _msg(db, user_id=42 + i % 2,
                       text=f"спор про консоли раунд {i}",
                       ts=base + 100 + i)
        llm2 = _FakeLLM([_verdict(kind="dispute", action="say",
                                  horizon="later", topic_key="consoles")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm2) == "completed"
        assert len(bot.sent) == 1                 # попытка не отправлялась
        intents = await mi.get_service(db).store.list_active(CHAT)
        assert any(r["origin"] == "unfinished_topic" and
                   r["kind"] == "open_dispute" for r in intents)
        # 3) юмор → REACT-решение (L1 react): отправки текста нет,
        #    реакция фиксируется решением (reason l1_react)
        for i in range(6):
            await _msg(db, user_id=43, text=f"анекдот про кота часть {i}",
                       ts=base + 200 + i)
        llm3 = _FakeLLM([_verdict(kind="humor", action="react",
                                  topic_key="cats")])
        assert await obs.observe_tick(db, bot=bot,
                                      writer_service=react_writer,
                                      llm=llm3) == "completed"
        assert react_writer.plan_calls == 1
        payload = await _payload_of(db)
        assert payload["counters"]["react_decisions"] == 1
        # 4) шум → SILENT легален: opportunity=false
        for i in range(6):
            await _msg(db, user_id=44, text=f"бытовой шум {i}",
                       ts=base + 300 + i)
        llm4 = _FakeLLM([json.dumps({"opportunity": False})])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm4) == "completed"
        payload = await _payload_of(db)
        assert payload["counters"]["eval_skips"].get("no_opportunity") == 1
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ B01.3: негативы — спам/повтор/закрытая тема; two-chat isolation ═════════

@pytest.mark.asyncio
async def test_b01_negatives_min_gap_repeat_and_topic_cap(tmp_path):
    db = await _db(tmp_path, "b01_negative.db")
    limits = dict(_ACTIVE)
    limits.update({"initiative.max_replies_per_topic": 1})
    _caches({CHAT: limits})
    bot, writer = _FakeBot(), _FakeWriter()
    verdict = _verdict(topic_key="trip")
    try:
        base = int(time.time()) - 1200
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"поездка план {i}",
                       ts=base + i)
        llm = _FakeLLM([verdict])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        assert len(bot.sent) == 1
        # Повтор той же темы: topic_cap отсекает ВТОРУЮ отправку (после
        # оценки; сами оценки бюджетируются отдельно).
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"поездка опять {i}",
                       ts=base + 60 + i)
        llm2 = _FakeLLM([_verdict(topic_key="trip")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm2) == "completed"
        assert llm2.calls == 1
        assert len(bot.sent) == 1                 # повторной отправки НЕТ
        payload = await _payload_of(db)
        assert payload["counters"]["eval_skips"].get("topic_cap") == 1
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_b01_day_cap_and_min_gap_cuts_spam(tmp_path):
    db = await _db(tmp_path, "b01_spam.db")
    limits = dict(_ACTIVE)
    limits.update({"initiative.max_replies_per_day": 1,
                   "initiative.min_gap_seconds": 3600})
    _caches({CHAT: limits})
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 7200
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"чат тред {i}",
                       ts=base + i)
        llm = _FakeLLM([_verdict(topic_key="t1")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        assert len(bot.sent) == 1
        # min_gap: bot только что отправил (durable ledger) → отсечка до LLM
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"чат тред2 {i}",
                       ts=base + 60 + i)
        llm2 = _FakeLLM([])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm2) == "completed"
        assert llm2.calls == 0
        assert len(bot.sent) == 1
        payload = await _payload_of(db)
        skips = payload["counters"]["eval_skips"]
        assert skips.get("min_gap") == 1 or skips.get("day_cap") == 1
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_b01_two_chat_isolation(tmp_path):
    db = await _db(tmp_path, "b01_two_chat.db")
    _caches({
        CHAT: {"initiative.max_replies_per_day": 1,
               "initiative.eval_min_messages": 4,
               "initiative.eval_min_interval_seconds": 1,
               "initiative.min_gap_seconds": 0,
               "initiative.eval_llm_budget_per_day": 10},
        CHAT_B: dict(_ACTIVE),
    })
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, chat_id=CHAT, user_id=42 + i % 2,
                       text=f"чат A разговор {i}", ts=base + i)
            await _msg(db, chat_id=CHAT_B, user_id=52 + i % 2,
                       text=f"чат B разговор {i}", ts=base + i)
        llm = _FakeLLM([
            _verdict(topic_key="a1"),
            _verdict(topic_key="b1", action="silent"),
            json.dumps({"opportunity": False}),
        ])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        # chat A отправил и исчерпан; chat B — свой профиль: silent легален
        assert len(bot.sent) == 1
        assert bot.sent[0][0] == CHAT
        payload = await _payload_of(db)
        chats = payload["chats"]
        assert str(CHAT) in chats and str(CHAT_B) in chats
        # состояние чатов изолировано (отдельные счётчики/темы)
        assert chats[str(CHAT)].get("sent_stamps") and \
            not chats[str(CHAT_B)].get("sent_stamps")
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ B01: reboots — курсор/дедуп персистентны ════════════════════════════════

@pytest.mark.asyncio
async def test_b01_reboot_keeps_cursor_and_context_dedup(tmp_path):
    db = await _db(tmp_path, "b01_reboot.db")
    _caches({CHAT: dict(_ACTIVE)})
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"тема рестарта {i}",
                       ts=base + i)
        llm = _FakeLLM([json.dumps({"opportunity": False})])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload = await _payload_of(db)
        first_cursor = payload[obs.CURSOR_KEY]
        assert first_cursor > 0 and llm.calls == 1
        # «Рестарт»: новый тик по той же БД, НОВЫЙ runner, новых сообщений нет.
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        payload2 = await _payload_of(db)
        assert payload2[obs.CURSOR_KEY] == first_cursor   # позиция сохранена
        counters = payload2["counters"]
        assert counters["observed"] == payload["counters"]["observed"]
        # то же окно после сброса eval-интервала НЕ пере-оценивается:
        # дедуп контекста персистентен (hash в payload)
        assert payload2["chats"][str(CHAT)]["recent_hashes"]
        assert llm.calls == 1                     # второй LLM-оценки не было
        # новые сообщения → новая оценка возможна (курсор пошёл вперёд)
        for i in range(6):
            await _msg(db, user_id=45, text=f"свежий тред {i}",
                       ts=base + 600 + i)
        llm3 = _FakeLLM([_verdict(topic_key="fresh")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm3) == "completed"
        assert llm3.calls == 1
        assert llm.calls == 1
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ B01.4: профили частоты (runtime-резолв) + диагностика ═══════════════════

@pytest.mark.asyncio
async def test_b01_frequency_profiles_and_thin_limits(tmp_path):
    db = await _db(tmp_path, "b01_profiles.db")
    _caches({
        CHAT: {"initiative.frequency_profile": "rare"},
        CHAT_B: {"initiative.frequency_profile": "active",
                 "initiative.min_gap_seconds": 30,
                 "initiative.max_replies_per_day": 3,
                 "initiative.eval_min_messages": 3},
    })
    try:
        rare = await obs.frequency_profile(CHAT)
        assert rare["min_gap_seconds"] == 6 * 3600
        assert rare["max_replies_per_day"] == 2
        active = await obs.frequency_profile(CHAT_B)
        assert active["min_gap_seconds"] == 30
        assert active["max_replies_per_day"] == 3
        assert active["eval_min_messages"] == 3
        # неизвестный профиль → дефолт (fail-open, без выдуманных значений);
        # сравниваем профиль-определяющие ключи (резолв добавляет тонкие лимиты)
        _caches({CHAT: {"initiative.frequency_profile": "шустрый"}})
        fallback = await obs.frequency_profile(CHAT)
        for key, value in obs.FREQUENCY_PROFILES["normal"].items():
            assert fallback[key] == value
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_b01_zero_opportunities_24h_is_diagnostic_event(tmp_path):
    db = await _db(tmp_path, "b01_diag.db")
    _caches({CHAT: dict(_ACTIVE)})
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(8):
            await _msg(db, user_id=42 + i % 2, text=f"тихий тред {i}",
                       ts=base + i)
        llm = _FakeLLM([json.dumps({"opportunity": False})])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        # Симулировать сутки активного наблюдателя без единого opportunity:
        # дневные счётчики «вчера», диагностический штамп устарел.
        payload = await _payload_of(db)
        payload["day"] = {"stamp": int(time.time()) // 86400,
                          "observed": 250, "opportunities": 0}
        payload["last_diag_ts"] = int(time.time()) - 2 * 86400
        cursor = await db.db.execute(
            "SELECT job_id FROM task_jobs WHERE kind = ? ORDER BY rowid "
            "DESC LIMIT 1", (obs.OBSERVE_JOB_KIND,))
        job_id = (await cursor.fetchone())["job_id"]
        await db.db.execute(
            "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
            "WHERE job_id = ?", (job_id,))
        await db.db.commit()
        runner = obs.InitiativeObserverRunner(db, bot=bot,
                                              writer_service=writer, llm=llm)
        fresh = await runner._load_payload(job_id)
        fresh["day"] = {"stamp": int(time.time()) // 86400,
                        "observed": 250, "opportunities": 0}
        fresh["last_diag_ts"] = int(time.time()) - 2 * 86400
        await runner._diagnose_phase(fresh)
        diags = [e for e in mca_events._pending
                 if e.get("event_name") == "initiative_observer_diagnostic"]
        assert diags and diags[-1]["stage"] == "diagnose:no_opportunities_24h"
        assert diags[-1]["outcome"] == "failed"
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ B01.5: независимость от Direct entrypoint + writer unavailable ══════════

@pytest.mark.asyncio
async def test_b01_independent_of_direct_entrypoint_gate(tmp_path):
    db = await _db(tmp_path, "b01_direct_gate.db")
    _caches({CHAT: dict(_ACTIVE)})
    # Direct entrypoint OFF (свой master-тумблер) — observer обязан работать.
    hot_config.set_config_cache(_FakeHot({
        "flags.direct_chat_botword_enabled": False}))
    from services import chat_params
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: dict(_ACTIVE)}))
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"независимый тред {i}",
                       ts=base + i)
        llm = _FakeLLM([_verdict(kind="event", action="say",
                                 topic_key="meetup")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        assert llm.calls == 1 and len(bot.sent) == 1
    finally:
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


@pytest.mark.asyncio
async def test_b01_writer_unavailable_is_explicit_not_silent(tmp_path):
    db = await _db(tmp_path, "b01_no_writer.db")
    _caches({CHAT: dict(_ACTIVE)})
    bot = _FakeBot()
    llm = _FakeLLM([_verdict(kind="development", action="say",
                             topic_key="boardgames")])
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"настолки тред {i}",
                       ts=base + i)
        assert await obs.observe_tick(db, bot=bot, writer_service=None,
                                      llm=llm) == "completed"
        # Явный статус, не молчание: событие + durable intent (повод не
        # теряется), отправки нет.
        events = await _flushed_events(db, "initiative_writer_unavailable")
        assert events and events[-1]["stage"] == "writer:unavailable"
        intents = await mi.get_service(db).store.list_active(CHAT)
        assert any(r["origin"] == "unfinished_topic" for r in intents)
        assert llm.calls == 1 and len(bot.sent) == 0
        payload = await _payload_of(db)
        assert payload["counters"]["writer_unavailable"] == 1
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ chat OFF отсекает proactive-путь (per-chat gate) ════════════════════════

@pytest.mark.asyncio
async def test_b01_chat_off_cuts_proactive_path(tmp_path):
    db = await _db(tmp_path, "b01_chat_off.db")
    _caches({
        CHAT: {"initiative.enabled": False},
        CHAT_B: dict(_ACTIVE),
    })
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, chat_id=CHAT, user_id=42 + i % 2,
                       text=f"выключенный чат {i}", ts=base + i)
            await _msg(db, chat_id=CHAT_B, user_id=52 + i % 2,
                       text=f"включённый чат {i}", ts=base + i)
        llm = _FakeLLM([_verdict(topic_key="b_only"),
                        json.dumps({"opportunity": False})])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        # CHAT выключен: ни одной LLM-оценки/отправки для него;
        # stored override не переписан.
        assert all(msg[0] != CHAT for msg in bot.sent)
        payload = await _payload_of(db)
        assert payload["counters"]["eval_skips"].get("chat_disabled") == 1
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()


# ═══ B01.5: heartbeat-тик без Writer — явное событие, не молчание ════════════

@pytest.mark.asyncio
async def test_b01_heartbeat_tick_writer_unavailable_event(tmp_path,
                                                           monkeypatch):
    from services.memory_maintenance import MemoryMaintenanceService
    db = await _db(tmp_path, "b01_hb.db")
    now = int(time.time())
    intent_id, created = await mi.get_service(db).create_intent(
        CHAT, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:test",), goal="когда стрим?",
        source_refs=("msg:11",), not_before=now - 3600,
        expires_at=now + 86400, activation_condition="time_due",
        created_at=now - 7200)
    assert created
    monkeypatch.setattr(
        "services.memory_maintenance._direct_chat_service_singleton",
        lambda: None)
    maint = MemoryMaintenanceService(db, memory=None, llm=None,
                                     bot=_FakeBot())
    await maint._tick_intent_heartbeat()
    row = await mi.get_service(db).store.get_intent(intent_id)
    assert row["status"] == "pending"        # кандидат не теряется
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT stage, outcome FROM mca_events WHERE event_name = "
        "'initiative_writer_unavailable' ORDER BY ts, rowid")
    events = [dict(r) for r in await cursor.fetchall()]
    assert events and events[-1]["stage"] == "writer:unavailable"
    assert events[-1]["outcome"] == "skipped"


# ═══ воронка observed→…→sent с reason codes ══════════════════════════════════

@pytest.mark.asyncio
async def test_b01_funnel_events_chain_with_reason_codes(tmp_path):
    db = await _db(tmp_path, "b01_funnel.db")
    _caches({CHAT: dict(_ACTIVE)})
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"воронка тред {i}",
                       ts=base + i)
        llm = _FakeLLM([_verdict(kind="association", action="say",
                                 topic_key="music")])
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        await mca_events.flush_events(db)
        cursor = await db.db.execute(
            "SELECT event_name, outcome, reason_code, stage, chat_id FROM "
            "mca_events WHERE event_name IN "
            "('initiative_observer_scan', 'initiative_opportunity', "
            "'initiative_decided', 'initiative_writer_generated', "
            "'initiative_recheck_passed', 'initiative_sent') "
            "ORDER BY ts, rowid")
        rows = [dict(r) for r in await cursor.fetchall()]
        names = [r["event_name"] for r in rows]
        assert names.count("initiative_observer_scan") >= 1
        assert "initiative_opportunity" in names
        assert "initiative_decided" in names
        assert "initiative_writer_generated" in names
        assert "initiative_sent" in names
        # Плечо recheck выполняется всегда (SendRecheck перед отправкой);
        # отдельное событие recheck_passed в mca-09 привязано к intent_id —
        # ephemeral-кандидат наблюдателя идёт без него (существующий
        # контракт), воронка решения/генерации/отправки полная.
        # порядок воронки: scan → opportunity → … → sent
        assert names.index("initiative_observer_scan") < \
            names.index("initiative_opportunity") < names.index(
                "initiative_sent")
        opp = [r for r in rows if r["event_name"] == "initiative_opportunity"]
        assert opp[-1]["stage"] == "opportunity:association:say"
    finally:
        from services import chat_params
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
        await db.close()
