"""MCA-09 `mca-09-intents-initiative` — focused-тесты блока E (T-5038…T-5040).

Покрытие:
  * единый вход инициативы `handle_initiative` (без входящего сообщения):
    тот же CoordinatorDecision, единственный транспорт `telegram_send.send_text`,
    silent/candidate_ready/cancelled/sent — честные статусы;
  * T-5038: NostalgiaWorker делегирует кандидата в единый Decision/транспорт
    (K1/K3 ON), legacy direct-send при OFF; второго send-path нет (grep);
  * T-5039: M-MCA07-2/§11.2 — поля единственного EvidenceBundle из оценки
    намерений (chosen_intent/recent_actions/ambiguities/unknown/contradictions);
  * T-5040: процесс `intent.initiative` v1 в реестре (стадии/события/widget-ID/
    enabled_gate), §16.3-снимок «Намерения и инициатива» (disabled/not_run/
    restricted), R17-safe.
"""
import inspect

import pytest

from services import mca_events, mca_gates
from services import mca_intents as mi
from services.database import DatabaseService
from services.direct_chat_service import (TRIGGER_INITIATIVE,
                                          direct_output_kind,
                                          handle_initiative)

CHAT = -100500
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


class _FakeBot:
    def __init__(self):
        self.id = 42
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

        class _Msg:
            message_id = 1000 + len(self.sent)

        return _Msg()


async def _db(tmp_path, name="mca09_e.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


def _situation(**kw) -> mi.InitiativeSituation:
    base = dict(trigger_kind="intent_due", chat_id=CHAT)
    base.update(kw)
    return mi.InitiativeSituation(**base)


def _candidate(intent_id="", prepared_ref=None):
    return mi.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=CHAT, intent_id=intent_id,
        prepared_text_ref=prepared_ref)


# ═══ T-5038: единый вход инициативы ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_handle_initiative_disabled_without_gates(monkeypatch):
    bot = _FakeBot()
    monkeypatch.setattr(mca_gates, "intent_decision_enabled", lambda: False)
    result = await handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], prepared_text="текст")
    assert result["status"] == "disabled"
    assert bot.sent == []


@pytest.mark.asyncio
async def test_handle_initiative_silent_no_send(monkeypatch):
    sent: list = []

    def _boom(*a, **k):
        sent.append((a, k))
        raise AssertionError("silent не должен доходить до отправки")

    monkeypatch.setattr("services.telegram_send.send_text", _boom)
    bot = _FakeBot()
    result = await handle_initiative(
        bot=bot, chat_id=CHAT, situation=_situation(sensitive_moment=True),
        candidates=[_candidate()], prepared_text="текст")
    assert result["status"] == "silent"
    assert bot.sent == [] and sent == []


@pytest.mark.asyncio
async def test_handle_initiative_candidate_ready_without_text(monkeypatch):
    sent: list = []

    def _boom(*a, **k):
        sent.append((a, k))
        raise AssertionError("без подготовленного текста отправки нет")

    monkeypatch.setattr("services.telegram_send.send_text", _boom)
    result = await handle_initiative(
        bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate()], prepared_text=None)
    assert result["status"] == "candidate_ready"
    assert result["delivery_kind"] == mi.DELIVERY_TEXT
    assert sent == []


@pytest.mark.asyncio
async def test_handle_initiative_sent_single_transport_chunks(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, created = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question",
            goal="Спросить про собеседование", source_refs=("msg:1",),
            not_before=NOW - 1, activation_condition="time_due",
            created_at=NOW - 10)
        assert created
        bot = _FakeBot()
        long_text = ("напоминание " * 700).strip()      # > 4096 символов
        result = await handle_initiative(
            bot=bot, chat_id=CHAT, situation=_situation(),
            candidates=[_candidate(intent_id=intent_id)],
            prepared_text=long_text, db=db)
        assert result["status"] == "sent"
        assert result["chunks"] >= 2
        assert len(bot.sent) == result["chunks"]        # единственный транспорт
        assert all(chat == CHAT for chat, _ in bot.sent)
        # попытка зафиксирована (attempts=1 → deferred на новое событие)
        row = await svc.store.get_intent(intent_id)
        assert row["attempts"] == 1 and row["status"] == "deferred"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_candidate_ready_defers_intent_backoff(tmp_path, monkeypatch):
    """Reviewer F-2: candidate_ready (нет prepared_text) НЕ должен оставлять
    intent due — иначе heartbeat переизбирает его каждые 300 с бесконечно.
    Bounded fix: defer с backoff `MCA_INTENT_DEFER_BACKOFF_SECONDS`;
    фактических попыток нет (attempts не растут); MAX_ATTEMPTS/гигиена
    уважаются."""
    db = await _db(tmp_path)
    try:
        # явный now уважается; только внутренний `_now()` фиксируется на NOW
        monkeypatch.setattr(
            mi, "_now", lambda ts=None: int(ts) if ts is not None else NOW)
        svc = mi.get_service(db)
        intent_id, created = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question",
            goal="Спросить про собеседование", source_refs=("msg:1",),
            created_at=NOW - 100)
        assert created
        assert await svc.defer(intent_id, next_check_at=NOW - 10,
                               activation_condition="new_reply", now=NOW - 10)
        result = await handle_initiative(
            bot=_FakeBot(), chat_id=CHAT, situation=_situation(),
            candidates=[_candidate(intent_id=intent_id)],
            prepared_text=None, db=db)
        assert result["status"] == "candidate_ready"
        row = await svc.store.get_intent(intent_id)
        # серверное планирование: deferred + backoff, attempts НЕ выросли
        assert row["status"] == "deferred"
        assert row["attempts"] == 0
        backoff = mca_gates.intent_defer_backoff_seconds()
        assert row["next_check_at"] == NOW + backoff
        assert row["activation_condition"] == "new_reply"   # условие сохранено
        # нет переизбрания через 300 с; следующий due — по backoff
        assert await svc.due_candidates(now=NOW + 301) == []
        due_later = await svc.due_candidates(now=NOW + backoff + 1)
        assert [c.intent_id for c in due_later] == [intent_id]
        # MAX_ATTEMPTS: 3 фактические попытки → abandoned (не due, не вечный цикл)
        for i in range(3):
            await svc.mark_attempt(intent_id, now=NOW + backoff + 2 + i)
        assert (await svc.store.get_intent(intent_id))["status"] == "abandoned"
        assert await svc.due_candidates(now=NOW + 10 * backoff) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_handle_initiative_cancelled_by_recheck(tmp_path):
    """A16-связка: человек уже сообщил результат → проверка отменяет отправку."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, _ = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question",
            goal="Спросить про собеседование", source_refs=("msg:1",),
            created_at=NOW - 10)
        # до отправки намерение закрыто человеком
        await svc.close(intent_id, status="fulfilled",
                        reason_code="already_answered", now=NOW)
        bot = _FakeBot()
        result = await handle_initiative(
            bot=bot, chat_id=CHAT, situation=_situation(),
            candidates=[_candidate(intent_id=intent_id)],
            prepared_text="напоминание", db=db)
        assert result["status"] == "cancelled"
        assert result["reason_code"] == "intent_closed"
        assert bot.sent == []
    finally:
        await db.close()


def test_initiative_output_kind_and_single_send_path():
    assert direct_output_kind(TRIGGER_INITIATIVE) == "initiative_reply"
    assert direct_output_kind("free_will") == "autonomous_reply"
    assert direct_output_kind("reply_to_bot") == "direct_reply"
    # единый вход: отправка — только через telegram_send.send_text; второго
    # send-path (прямой bot.send_message) в функции нет
    src = inspect.getsource(handle_initiative)
    assert "send_text" in src
    assert "bot.send_message" not in src


# ═══ T-5038: делегирование NostalgiaWorker ══════════════════════════════════

def test_nostalgia_delegation_gate_and_legacy_parity(monkeypatch):
    from services import nostalgia_worker as nw
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_decision_enabled", lambda: True)
    assert nw._intent_delegation_enabled() is True
    monkeypatch.setattr(mca_gates, "intent_decision_enabled", lambda: False)
    assert nw._intent_delegation_enabled() is False
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
    monkeypatch.setattr(mca_gates, "intent_decision_enabled", lambda: True)
    assert nw._intent_delegation_enabled() is False
    # legacy-ветка сохранена: при OFF отправка — существующий direct-send
    src = inspect.getsource(nw.NostalgiaWorker._candidate_llm_send)
    assert "if _intent_delegation_enabled():" in src
    assert "await self.bot.send_message(chat_id, text)" in src


@pytest.mark.asyncio
async def test_nostalgia_delegate_initiative_sent(tmp_path):
    from services import nostalgia_worker as nw
    db = await _db(tmp_path)
    try:
        worker = nw.NostalgiaWorker(db=db, bot=_FakeBot())
        result = await worker._delegate_initiative(
            CHAT, "кстати, год назад…", {"kind": "year_back", "fact_id": 7})
        assert result["status"] == "sent"
        assert worker.bot.sent and worker.bot.sent[0][0] == CHAT
        # source/trigger делегирования — nostalgia/ nostalgia_due
        assert result["delivery_kind"] == mi.DELIVERY_TEXT
    finally:
        await db.close()


# ═══ T-5039: границы mca-07 (единственный bundle) ═══════════════════════════

def test_bundle_signals_single_bundle():
    from services.mca_retrieval_context import EvidenceBundle
    bundle = EvidenceBundle(trigger="direct", context_version="ctx-1")
    updated = mi.apply_intent_bundle_signals(
        bundle, intent_row={"intent_id": "intent:1",
                            "linked_action_id": "action:9"},
        recent_actions=("reply:sent",), ambiguities=("topic_ref",),
        unknown=("addressee",), contradictions=())
    assert updated.chosen_intent == "intent:1"
    assert updated.recent_actions == ("reply:sent", "action:9")
    assert updated.ambiguities == ("topic_ref",)
    assert updated.unknown == ("addressee",)
    assert updated.contradictions == ()
    # исходный bundle не мутирован (frozen; второго bundle не создаётся)
    assert bundle.chosen_intent is None and bundle.recent_actions == ()
    # границы: модуль не строит второй bundle/retrieval-движок
    src = inspect.getsource(mi)
    assert "EvidenceBundle(" not in src
    assert "def retrieve" not in src


# ═══ T-5040: реестр процессов + §16.3-снимок ════════════════════════════════

@pytest.mark.asyncio
async def test_lifecycle_events_pass_mca13_contract(tmp_path):
    """D9/T-5040: жизненные события реально проходят `build_event` (валидный
    outcome) — не отбрасываются молча."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, _ = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question", goal="g",
            source_refs=("msg:1",), created_at=NOW)
        await svc.close(intent_id, status="fulfilled", now=NOW + 1)
        ab, _ = await svc.create_intent(
            CHAT, "topic_interest", "unfinished_topic", goal="t",
            source_refs=("msg:2",), topic_refs=("t:2",), created_at=NOW)
        await svc.close(ab, status="abandoned", now=NOW + 1)
        names = {ev.get("event_name") for ev in mca_events._pending}
        assert {"intent_created", "intent_fulfilled",
                "intent_abandoned"} <= names
        for ev in mca_events._pending:
            if str(ev.get("event_name") or "").startswith("intent_"):
                assert ev.get("outcome") in mca_events.ALL_OUTCOMES
                assert ev.get("component") == "intents"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_events_r17_no_raw_text(tmp_path):
    """R17: события/логи контура не несут сырой текст/секреты — только
    ID/коды/enum/числа/refs."""
    db = await _db(tmp_path)
    try:
        secret = "sk-abcdef1234567890"
        svc = mi.get_service(db)
        intent_id, _ = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question",
            goal=f"Позвонить завтра {secret}", source_refs=("msg:1",),
            created_at=NOW)
        await svc.close(intent_id, status="fulfilled", now=NOW + 1)
        blob = repr(list(mca_events._pending))
        assert secret not in blob and "Позвонить" not in blob
        for ev in mca_events._pending:
            assert "goal" not in ev and "text" not in ev
    finally:
        await db.close()


def test_registry_process_intent_initiative():
    from services.mca_process_registry import (_GATE_RESOLVERS, get_process,
                                               runtime_status)
    process = get_process("intent.initiative")
    assert process is not None and process.version == "1"
    assert process.stages == ("trigger", "candidate", "decide", "recheck",
                              "deliver", "close")
    assert process.trigger_kind == "event"
    assert process.schedule == "heartbeat 300s + события"
    assert process.state_source == ("mca_intents", "mca_events", "task_jobs")
    assert process.recovery_ops == ("intent_rescan", "deferred_resume")
    assert process.widget_id == "Намерения и инициатива"
    assert process.enabled_gate == "MCA_INTENTS_ENABLED"
    assert process.stages_to_events == {
        "trigger": "intent_created", "decide": "initiative_decided",
        "recheck": "recheck_deferred", "close": "intent_fulfilled"}
    assert process.instrumentation == ("trigger", "decide", "recheck",
                                       "close")
    assert _GATE_RESOLVERS["MCA_INTENTS_ENABLED"] == "intents_enabled"
    # OFF → disabled; события без прогонов → not_run (честно)
    from config.settings import settings
    old = getattr(type(settings), "MCA_INTENTS_ENABLED", True)
    try:
        setattr(type(settings), "MCA_INTENTS_ENABLED", False)
        assert runtime_status(process) == "disabled"
    finally:
        setattr(type(settings), "MCA_INTENTS_ENABLED", old)


@pytest.mark.asyncio
async def test_intent_status_snapshot(tmp_path, monkeypatch):
    from services.status_service import StatusService
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr("services.lore_runtime.get_lore_db", lambda: db)
        svc = mi.get_service(db)
        await svc.create_intent(CHAT, "follow_up", "unanswered_question",
                                goal="Спросить про собеседование",
                                source_refs=("msg:1",), created_at=NOW)
        status = StatusService()
        snap = await status.intent_snapshot(chat_id=CHAT,
                                            chat_scope_allowed=True)
        assert snap["enabled"] is True and snap["state"] == "ok"
        assert snap["active"] == 1
        assert snap["top"][0]["kind"] == "follow_up"
        assert snap["top"][0]["goal"] == "Спросить про собеседование"
        assert snap["top"][0]["status"] == "pending"
        # без разрешённого чата данные не раскрываются
        restricted = await status.intent_snapshot(chat_id=None)
        assert restricted["state"] == "restricted" and restricted["top"] == []
        # K1 OFF → honest disabled
        monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
        off = await status.intent_snapshot(chat_id=CHAT,
                                           chat_scope_allowed=True)
        assert off["enabled"] is False and off["state"] == "disabled"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_intent_status_snapshot_not_run(tmp_path, monkeypatch):
    from services.status_service import StatusService
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr("services.lore_runtime.get_lore_db", lambda: db)
        snap = await StatusService().intent_snapshot(
            chat_id=CHAT, chat_scope_allowed=True)
        assert snap["state"] == "not_run" and snap["active"] == 0
    finally:
        await db.close()
