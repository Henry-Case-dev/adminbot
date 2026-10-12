"""ASAP 8 F6 — Initiative v2: producers → decision → L2 Writer → SendRecheck
→ send (architecture.md §6; current_task §13.1–§13.3, §18D, §22 I1–I9).

Покрытие:
  * I1  — реальное событие (вопрос без ответа бота) создаёт durable intent;
  * I2  — обычный шум (без '?', команды, URL) намерений не создаёт; дедуп
          по содержанию, кап pending на чат;
  * I3  — due intent доходит до решения (L1-модель, SILENT → defer+backoff);
  * I4  — REPLY генерирует prepared_text СУЩЕСТВУЮЩИМ Direct L2 Writer и
          может отправиться (chunks/ledger/mark_attempt, funnel-события);
  * I5  — SILENT ничего не отправляет;
  * I6  — свежий recheck (§18D): отвечено тем временем → A15 close; прямое
          обращение → defer; смена контекста → ровно одна переоценка,
          повторная смена → defer (без циклов); закрытое → нет отправки;
  * I7  — нет вечного candidate_ready: writer-failure → bounded attempts →
          терминальное закрытие (writer_failed/abandoned);
  * I8  — Status различает heartbeat alive vs producers=0 (state_label);
  * I9  — лимиты измеряются funnel (producers/decisions/writer/sent 24ч).

TEST-LIFECYCLE: CONTRACT owner=ASAP8/F6
"""
import time

import pytest

from services import mca_events, mca_gates
from services import mca_intents as mi
from services import direct_chat_service as dcs
from services.database import DatabaseService
from services.direct_l1 import (FUTURE_INTENT_GOAL_MAX, FutureIntent,
                                L1Plan)

CHAT = -100777
BOT_ID = 4242


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture(autouse=True)
def _no_exploration_draw(monkeypatch):
    """Детерминизм: mca-10b exploration-draw случайно выбирает форму вместо
    intent-кандидата (легитимный прод-путь), что делает счётчики
    решение/генерация недетерминированными. В этих тестах exploration OFF —
    проверяется ровно intent-путь F6 (10b покрыт своими тестами)."""
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
    """Duck-typed DirectChatService для writer-пути F6 (ровно два метода
    контракта §13.2: plan_initiative_decision / generate_initiative_reply)."""

    def __init__(self, action="reply", text="Ну что, продолжим?"):
        self.action = action
        self.text = text
        self.plan_calls = 0
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        self.plan_calls += 1
        return L1Plan(action=self.action, confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


async def _db(tmp_path, name="f6.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


def _situation(**kw) -> mi.InitiativeSituation:
    base = dict(trigger_kind="intent_due", chat_id=CHAT)
    base.update(kw)
    return mi.InitiativeSituation(**base)


def _candidate(intent_id: str = ""):
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT, intent_id=intent_id,
        reason_code="default")


async def _make_intent(db, *, goal="когда стрим?", created_delta=7200):
    now = int(time.time())
    return await mi.get_service(db).create_intent(
        CHAT, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:test",), goal=goal, source_refs=("msg:11",),
        not_before=now - created_delta,
        expires_at=now + 3 * 86400, activation_condition="time_due",
        created_at=now - created_delta)


async def _intent_row(db, intent_id):
    return await mi.get_service(db).store.get_intent(intent_id)


async def _flushed_events(db, event_name: str) -> list[dict]:
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT event_name, outcome, reason_code, stage, status FROM "
        "mca_events WHERE chat_id = ? AND event_name = ? ORDER BY ts",
        (CHAT, event_name))
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ═══ I1/I2: producers ════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_i1_unanswered_question_creates_durable_intent(tmp_path):
    db = await _db(tmp_path, "f6_i1.db")
    intent_id, created = await dcs._f6_maybe_create_unanswered_question(
        db, CHAT, "когда стрим?", 1001)
    assert created is True and intent_id
    row = await _intent_row(db, intent_id)
    assert row["kind"] == "follow_up"
    assert row["origin"] == "unanswered_question"
    assert row["status"] == "pending"
    assert row["activation_condition"] == "time_due"
    assert row["not_before"] > int(time.time())      # due не мгновенно
    assert row["expires_at"] is not None
    assert "стрим" in (row["goal"] or "")
    events = await _flushed_events(db, "intent_created")
    assert events and events[-1]["stage"] == "unanswered_question"


@pytest.mark.asyncio
async def test_i2_ordinary_noise_creates_none(tmp_path):
    db = await _db(tmp_path, "f6_i2.db")
    for text in ("привет", "/help?", "глянь https://x.ru?q=1",
                 "ахахаха", ""):
        intent_id, created = await dcs._f6_maybe_create_unanswered_question(
            db, CHAT, text, 1002)
        assert created is False and intent_id is None, text
    rows = await mi.get_service(db).store.list_active(CHAT)
    assert rows == []


@pytest.mark.asyncio
async def test_same_question_dedup_merges_not_spams(tmp_path):
    db = await _db(tmp_path, "f6_dedup.db")
    first_id, created1 = await dcs._f6_maybe_create_unanswered_question(
        db, CHAT, "когда стрим?", 11)
    second_id, created2 = await dcs._f6_maybe_create_unanswered_question(
        db, CHAT, "когда стрим?", 22)
    assert created1 is True and created2 is False
    assert first_id == second_id
    assert await mi.get_service(db).store.count_active(CHAT) == 1


@pytest.mark.asyncio
async def test_pending_cap_skips_new_intents(tmp_path, monkeypatch):
    db = await _db(tmp_path, "f6_cap.db")
    monkeypatch.setattr(mca_gates, "intent_candidates_max", lambda: 1)
    ok_id, ok = await dcs._f6_maybe_create_unanswered_question(
        db, CHAT, "когда стрим?", 11)
    assert ok is True
    skipped_id, created = await dcs._f6_maybe_create_unanswered_question(
        db, CHAT, "а во сколько начинается?", 12)
    assert created is False and skipped_id is None
    assert await mi.get_service(db).store.count_active(CHAT) == 1


@pytest.mark.asyncio
async def test_producers_inert_when_intents_disabled(tmp_path, monkeypatch):
    db = await _db(tmp_path, "f6_off.db")
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
    intent_id, created = await dcs._f6_maybe_create_unanswered_question(
        db, CHAT, "когда стрим?", 11)
    assert created is False and intent_id is None


# ═══ L1 future-intent (allowlist; intent пишет сервис) ═══════════════════════

def test_future_intent_parser_allowlist():
    plan_result = _parse_future(
        '{"action": "reply", "confidence": 0.8, "future_intent": '
        '{"kind": "follow_up", "goal": "завтра скину трек"}}')
    assert plan_result is not None
    kind, goal = plan_result
    assert (kind, goal) == ("follow_up", "завтра скину трек")
    # невалидный kind / пустая цель / не-dict → поле None, план валиден
    for raw in ('{"action": "reply", "future_intent": {"kind": "spam", '
                '"goal": "x"}}',
                '{"action": "reply", "future_intent": {"kind": "follow_up", '
                '"goal": ""}}',
                '{"action": "reply", "future_intent": "давай позже"}'):
        assert _parse_future(raw) is None, raw
    assert FUTURE_INTENT_GOAL_MAX == 200


def _parse_future(raw: str):
    from services.direct_l1 import parse_l1_plan
    plan = parse_l1_plan(raw)
    if plan is None or plan.future_intent is None:
        return None
    return plan.future_intent.kind, plan.future_intent.goal


@pytest.mark.asyncio
async def test_future_intent_producer_creates_explicit_request(tmp_path):
    db = await _db(tmp_path, "f6_future.db")
    fi = FutureIntent(kind="open_dispute", goal="обсудим правила отдельно")
    intent_id, created = await dcs._f6_create_future_intent(db, CHAT, fi, 33)
    assert created is True and intent_id
    row = await _intent_row(db, intent_id)
    assert row["origin"] == "explicit_request"
    assert row["kind"] == "open_dispute"
    # повтор того же обещания — дедуп-слияние (LLM в DB не пишет; сервис
    # не создаёт дублей)
    _, created2 = await dcs._f6_create_future_intent(db, CHAT, fi, 44)
    assert created2 is False


# ═══ I3–I7: consumer (decision → writer → recheck → send) ════════════════════

@pytest.mark.asyncio
async def test_i3_due_intent_reaches_l1_decision_silent(tmp_path):
    db = await _db(tmp_path, "f6_i3.db")
    intent_id, _ = await _make_intent(db)
    writer = _FakeWriter(action="silent")
    result = await dcs.handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "silent"
    assert writer.plan_calls == 1
    row = await _intent_row(db, intent_id)
    # серверное планирование: не re-decide каждые 300 с
    assert row["status"] == "deferred"
    assert (row["next_check_at"] or 0) > int(time.time())


@pytest.mark.asyncio
async def test_i4_reply_generates_via_existing_writer_and_sends(
        tmp_path, monkeypatch):
    db = await _db(tmp_path, "f6_i4.db")
    intent_id, _ = await _make_intent(db)
    sent: list = []

    async def _fake_send(bot, chat_id, text):
        sent.append((chat_id, text))

        class _Msg:
            message_id = 7001

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    bot = _FakeBot()
    writer = _FakeWriter(text="Ну что, по поводу стрима — в 19:00.")
    result = await dcs.handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db,
        correlation_id="corr-f6-i4", writer_service=writer)
    assert result["status"] == "sent"
    assert result.get("generated") is True
    assert writer.plan_calls == 1 and writer.generate_calls == 1
    assert len(sent) == 1 and sent[0][0] == CHAT
    # ledger: доставленный output инициативы — СО СВОИМ kind (не `other`)
    outputs = await db.list_recent_bot_outputs(CHAT, limit=5)
    assert outputs and outputs[0]["output_kind"] == "initiative_reply"
    # intent: фактическая попытка учтена, дальше — только по новому событию
    row = await _intent_row(db, intent_id)
    assert row["attempts"] == 1
    assert row["status"] == "deferred"
    assert row["activation_condition"] == "new_reply"
    # funnel-события: генерация → recheck → отправка
    assert await _flushed_events(db, "initiative_writer_generated")
    assert await _flushed_events(db, "initiative_recheck_passed")
    assert await _flushed_events(db, "initiative_sent")


@pytest.mark.asyncio
async def test_i5_silent_sends_nothing(tmp_path, monkeypatch):
    db = await _db(tmp_path, "f6_i5.db")
    intent_id, _ = await _make_intent(db)
    sent: list = []

    async def _boom(*a, **k):
        sent.append((a, k))
        raise AssertionError("SILENT не должен отправлять")

    monkeypatch.setattr("services.telegram_send.send_text", _boom)
    bot = _FakeBot()
    writer = _FakeWriter(action="silent")
    result = await dcs.handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "silent"
    assert bot.sent == [] and sent == []


@pytest.mark.asyncio
async def test_i6_answered_while_preparing_suppresses(tmp_path):
    db = await _db(tmp_path, "f6_i6a.db")
    intent_id, _ = await _make_intent(db)
    # «человек получил ответ»: бот доставил текст после создания намерения
    await db.record_bot_output(
        chat_id=CHAT, bot_user_id=BOT_ID, tg_message_id=8001,
        output_kind="direct_reply", content_text="держи ответ",
        sent_at=int(time.time()), delivery_status="delivered")
    bot = _FakeBot()
    writer = _FakeWriter()
    result = await dcs.handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "already_answered"
    assert bot.sent == [] and writer.plan_calls == 0
    row = await _intent_row(db, intent_id)
    assert row["status"] == "fulfilled"      # A15-закрытие без вопроса


@pytest.mark.asyncio
async def test_i6_direct_request_arrives_initiative_does_not_race(tmp_path):
    db = await _db(tmp_path, "f6_i6b.db")
    intent_id, _ = await _make_intent(db)
    # прямое обращение к боту появилось ПОСЛЕ создания намерения
    await db.save_smart_message(7, CHAT, "бот, а ты как считаешь?", None,
                                int(time.time()), "text", "Дима",
                                message_id=9001)
    bot = _FakeBot()
    writer = _FakeWriter()
    result = await dcs.handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "direct_pending"
    assert bot.sent == [] and writer.plan_calls == 0
    row = await _intent_row(db, intent_id)
    # инициатива отложена (не отменена навсегда) и не потратила попытку
    assert row["status"] == "deferred"
    assert int(row["attempts"] or 0) == 0


@pytest.mark.asyncio
async def test_i6_context_change_reevaluates_exactly_once(tmp_path,
                                                          monkeypatch):
    db = await _db(tmp_path, "f6_i6c.db")
    intent_id, _ = await _make_intent(db)
    quiet = {"new_human": 0, "last_human_id": None, "direct_pending": False,
             "same_branch_replies": False, "bot_outputs": 0,
             "last_output_id": None, "bot_after": 0}
    changed = dict(quiet, new_human=2, last_human_id="42")
    facts_sequence = [quiet, changed, changed]

    async def _facts(_db, _chat, _created):
        if facts_sequence:
            return facts_sequence.pop(0)
        return changed

    monkeypatch.setattr(dcs, "_f6_chat_facts", _facts)
    sent: list = []

    async def _fake_send(bot, chat_id, text):
        sent.append(text)

        class _Msg:
            message_id = 7100

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    writer = _FakeWriter(text="ответ на свежем контексте")
    result = await dcs.handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "sent"
    # ровно одна переоценка: решение+генерация дважды, отправка один раз
    assert writer.plan_calls == 2 and writer.generate_calls == 2
    assert len(sent) == 1
    row = await _intent_row(db, intent_id)
    assert row["status"] == "deferred"


@pytest.mark.asyncio
async def test_i6_context_changed_twice_defers_not_loops(tmp_path,
                                                         monkeypatch):
    db = await _db(tmp_path, "f6_i6d.db")
    intent_id, _ = await _make_intent(db)
    quiet = {"new_human": 0, "last_human_id": None, "direct_pending": False,
             "same_branch_replies": False, "bot_outputs": 0,
             "last_output_id": None, "bot_after": 0}
    calls = {"n": 0}

    async def _facts(_db, _chat, _created):
        calls["n"] += 1
        return dict(quiet, new_human=calls["n"])

    monkeypatch.setattr(dcs, "_f6_chat_facts", _facts)
    writer = _FakeWriter(text="текст")
    result = await dcs.handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "cancelled"
    # вторая смена условий → defer (бесконечных переоценок нет)
    assert result["reason_code"] == "recheck_deferred"
    row = await _intent_row(db, intent_id)
    assert row["status"] == "deferred"


@pytest.mark.asyncio
async def test_i6_closed_intent_never_sends(tmp_path):
    db = await _db(tmp_path, "f6_i6e.db")
    intent_id, _ = await _make_intent(db)
    await mi.get_service(db).close(intent_id, status="abandoned",
                                   reason_code="test")
    bot = _FakeBot()
    writer = _FakeWriter()
    result = await dcs.handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db, writer_service=writer)
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "intent_closed"
    assert bot.sent == [] and writer.plan_calls == 0


@pytest.mark.asyncio
async def test_i7_writer_failure_is_bounded_not_endless_candidate_ready(
        tmp_path):
    db = await _db(tmp_path, "f6_i7.db")
    intent_id, _ = await _make_intent(db)
    writer = _FakeWriter(text="")          # генерация всегда пуста
    bot = _FakeBot()
    statuses = []
    for _ in range(5):
        result = await dcs.handle_initiative(
            bot=bot, chat_id=CHAT, situation=_situation(),
            candidates=[_candidate(intent_id)], db=db,
            writer_service=writer)
        statuses.append(result["status"])
        row = await _intent_row(db, intent_id)
        if row["status"] in ("fulfilled", "abandoned", "expired"):
            break
    # ни одного candidate_ready; исход ограничен (cap MCA_INTENT_MAX_ATTEMPTS)
    assert "candidate_ready" not in statuses
    assert statuses and all(s == "writer_failed" for s in statuses)
    row = await _intent_row(db, intent_id)
    assert row["status"] == "abandoned"
    assert int(row["attempts"] or 0) >= int(mca_gates.intent_max_attempts())
    assert bot.sent == []
    close = await _flushed_events(db, "intent_abandoned")
    assert close and close[-1]["reason_code"] == "writer_failed"


# ═══ I8/I9: Status funnel ════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_i8_status_distinguishes_heartbeat_vs_producers(tmp_path):
    from services import memory_maintenance as mm
    db = await _db(tmp_path, "f6_i8.db")
    mm._heartbeat_last_tick["ts"] = int(time.time())
    mm._heartbeat_last_tick["due"] = 0
    snap = await _status_snapshot(db)
    label_empty = snap["module"]["state_label"]
    assert "producers" in label_empty
    assert snap["module"]["heartbeat"]["enabled"] is True
    assert snap["module"]["funnel"]["heartbeat_last_tick"]
    # после producer-события статус уже НЕ «producers=0»
    await dcs._f6_maybe_create_unanswered_question(db, CHAT,
                                                   "когда стрим?", 11)
    await mca_events.flush_events(db)
    snap2 = await _status_snapshot(db)
    funnel = snap2["module"]["funnel"]
    assert funnel["producers_24h"].get("unanswered_question") == 1
    assert funnel["intents_created_24h"] == 1
    assert "producers" not in snap2["module"]["state_label"]


@pytest.mark.asyncio
async def test_i8_heartbeat_not_run_label_is_honest(tmp_path, monkeypatch):
    """REV-F6 F2: до первого тика (heartbeat_last_tick=None) метка НЕ вправе
    утверждать «Heartbeat работает» — честное «ещё не запускался»."""
    from services import memory_maintenance as mm
    db = await _db(tmp_path, "f6_i8b.db")
    mm._heartbeat_last_tick["ts"] = None
    mm._heartbeat_last_tick["due"] = 0
    snap = await _status_snapshot(db)
    funnel = snap["module"]["funnel"]
    assert funnel["heartbeat_last_tick"] is None
    assert funnel["intents_created_24h"] == 0
    label = snap["module"]["state_label"]
    assert "работает" not in label
    assert "ещё не запускался" in label
    assert snap["module"]["top_block_reason"] == "heartbeat_not_run"


@pytest.mark.asyncio
async def test_i9_funnel_measures_decisions_writer_sent(tmp_path,
                                                        monkeypatch):
    db = await _db(tmp_path, "f6_i9.db")
    intent_id, _ = await _make_intent(db)
    sent: list = []

    async def _fake_send(bot, chat_id, text):
        sent.append(text)

        class _Msg:
            message_id = 7200

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)
    result = await dcs.handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db,
        writer_service=_FakeWriter())
    assert result["status"] == "sent"
    await mca_events.flush_events(db)
    snap = await _status_snapshot(db)
    funnel = snap["module"]["funnel"]
    assert funnel["decisions_24h"] >= 1
    assert funnel["writer_generated_24h"] >= 1
    assert funnel["recheck_passed_24h"] >= 1
    assert funnel["sent_24h"] >= 1
    outputs = await db.list_recent_bot_outputs(
        CHAT, limit=5, kinds=("initiative_reply",))
    assert len(outputs) == 1


# ═══ wrapper-уровень: полный ход Direct → producer (REV-F6 F1) ══════════════

def _turn_service(db, llm):
    """Реальный DirectChatService поверх реальной БД (producer пишет intent)."""
    from tests.test_direct_chat import FakeMemory, _make_service
    return _make_service(memory=FakeMemory(), db=db, llm=llm)


@pytest.mark.asyncio
async def test_wrapper_error_phrase_reply_is_not_unanswered_question(
        tmp_path):
    """REV-F6 F1: ход с '?', где бот ОТПРАВИЛ error-фразу (LLM упал) —
    это НЕ «вопрос без ответа»: intent не создаётся (иначе каждый вопрос
    при лежащем LLM порождал durable follow_up → defer → writer_failed)."""
    from services.llm_client import LLMError
    from tests.test_direct_chat import FakeLLM, _bot, _message, _user
    db = await _db(tmp_path, "f6_wrap_err.db")
    llm = FakeLLM(error=LLMError("upstream down"))
    service = _turn_service(db, llm)
    bot = _bot()
    await service.handle(bot, _message(text="когда стрим?", message_id=404,
                                       chat_id=CHAT), _user())
    # error-фраза отправлена (текстовый reply в ходе ЕСТЬ)
    assert bot.send_message.await_count >= 1
    assert await mi.get_service(db).store.count_active(CHAT) == 0
    events = await _flushed_events(db, "intent_created")
    assert events == []


@pytest.mark.asyncio
async def test_wrapper_silent_turn_with_question_creates_intent(tmp_path):
    """REV-F6 F1 (позитив wrapper-уровня): ход с '?' и БЕЗ текстового reply
    (модель жива, ответила пустым → 🗿-молчание) → durable follow_up."""
    from tests.test_direct_chat import FakeLLM, _bot, _message, _user
    db = await _db(tmp_path, "f6_wrap_ok.db")
    llm = FakeLLM(text="")                 # пустой ответ → молчание/🗿
    service = _turn_service(db, llm)
    bot = _bot()
    await service.handle(bot, _message(text="когда стрим?", message_id=405,
                                       chat_id=CHAT), _user())
    # реакция — не текстовый reply: send_message не вызван
    assert bot.send_message.await_count == 0
    rows = await mi.get_service(db).store.list_active(CHAT)
    assert len(rows) == 1
    assert rows[0]["origin"] == "unanswered_question"
    assert "стрим" in (rows[0]["goal"] or "")


# ═══ heartbeat-путь (memory_maintenance) ═════════════════════════════════════

@pytest.mark.asyncio
async def test_heartbeat_generates_and_sends_with_writer_service(
        tmp_path, monkeypatch):
    from services.memory_maintenance import MemoryMaintenanceService
    db = await _db(tmp_path, "f6_hb.db")
    intent_id, _ = await _make_intent(db)
    sent: list = []

    async def _fake_send(bot, chat_id, text):
        sent.append(text)

        class _Msg:
            message_id = 7300

        return _Msg()

    monkeypatch.setattr("services.telegram_send.send_text", _fake_send)

    async def _allow_budget(*a, **k):
        return True

    monkeypatch.setattr("services.worker_budget.consume", _allow_budget)
    maint = MemoryMaintenanceService(db, memory=None, llm=None,
                                     bot=_FakeBot())
    monkeypatch.setattr(
        "services.memory_maintenance._direct_chat_service_singleton",
        lambda: _FakeWriter(text="инициативная реплика"))
    await maint._tick_intent_heartbeat()
    assert sent == ["инициативная реплика"]
    row = await _intent_row(db, intent_id)
    assert row["attempts"] == 1
    assert row["status"] == "deferred"


@pytest.mark.asyncio
async def test_heartbeat_without_direct_service_skips_decisions(
        tmp_path, monkeypatch):
    from services.memory_maintenance import MemoryMaintenanceService
    db = await _db(tmp_path, "f6_hb2.db")
    intent_id, _ = await _make_intent(db)
    monkeypatch.setattr(
        "services.memory_maintenance._direct_chat_service_singleton",
        lambda: None)
    maint = MemoryMaintenanceService(db, memory=None, llm=None,
                                     bot=_FakeBot())
    await maint._tick_intent_heartbeat()
    # без writer-сервиса решение не принимается, но intent не теряется
    row = await _intent_row(db, intent_id)
    assert row["status"] == "pending"
    assert int(row["attempts"] or 0) == 0


# ═══ хелперы ═════════════════════════════════════════════════════════════════

async def _status_snapshot(db):
    """intent_snapshot с подменённым lore_runtime.get_lore_db (единая БД)."""
    from services import lore_runtime
    from services.status_service import StatusService
    original = lore_runtime.get_lore_db
    lore_runtime.get_lore_db = lambda: db
    try:
        return await StatusService().intent_snapshot(chat_id=CHAT,
                                                     chat_scope_allowed=True)
    finally:
        lore_runtime.get_lore_db = original
