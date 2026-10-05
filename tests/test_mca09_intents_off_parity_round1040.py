"""MCA-09 `mca-09-intents-initiative` — T-5041: OFF-паритет всех kill-switch.

K1 `MCA_INTENTS_ENABLED` OFF = бит-в-бит 2.58.59 (ни записей/чтений v29, ни
heartbeat, ни кандидатов/событий; nostalgia legacy); K2/K3/K4 OFF —
документированные подмножества. Дефолты ON, 0 env-оверрайдов; Δ каталога=0.
"""
import pytest

from config.settings import settings
from services import mca_events, mca_gates
from services import mca_intents as mi
from services.database import DatabaseService

CHAT = -100500
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


class _SqlRecorder:
    def __init__(self, inner):
        self._inner = inner
        self.statements: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def execute(self, sql, *args, **kwargs):
        self.statements.append(str(sql))
        return await self._inner.execute(sql, *args, **kwargs)


class _DbProxy:
    def __init__(self, inner):
        self._inner = inner
        self.db = _SqlRecorder(inner.db)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _db(tmp_path, name="mca09_off.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


def test_kill_switch_registry_defaults_on():
    for key in ("MCA_INTENTS_ENABLED", "MCA_INTENT_HEARTBEAT_ENABLED",
                "MCA_INTENT_DECISION_ENABLED", "MCA_SEND_RECHECK_ENABLED"):
        assert mca_gates.KILL_SWITCHES[key][0] is True
    assert settings.MCA_INTENTS_ENABLED is True
    assert settings.MCA_INTENT_HEARTBEAT_ENABLED is True
    assert settings.MCA_INTENT_DECISION_ENABLED is True
    assert settings.MCA_SEND_RECHECK_ENABLED is True
    assert mca_gates.intents_enabled() is True
    assert mca_gates.intent_heartbeat_enabled() is True
    assert mca_gates.intent_decision_enabled() is True
    assert mca_gates.send_recheck_enabled() is True
    # env-only лимиты — дефолты (каталог не менялся: Δ=0)
    assert mca_gates.intent_heartbeat_batch_max() == 20
    assert mca_gates.intent_max_attempts() == 3
    assert mca_gates.intent_candidates_max() == 8
    assert mca_gates.intent_retention_days() == 180
    assert mca_gates.intent_defer_backoff_seconds() == 1800


@pytest.mark.asyncio
async def test_k1_off_bit_parity(tmp_path, monkeypatch):
    """K1 OFF: контур инертен — 0 чтений/записей v29, событий/кандидатов нет;
    производные подгейты инертны; nostalgia — legacy."""
    monkeypatch.setattr(type(settings), "MCA_INTENTS_ENABLED", False)
    assert mca_gates.intents_enabled() is False
    assert mca_gates.intent_heartbeat_enabled() is False
    assert mca_gates.intent_decision_enabled() is False
    assert mca_gates.send_recheck_enabled() is False
    from services import nostalgia_worker as nw
    assert nw._intent_delegation_enabled() is False
    from services.direct_chat_service import handle_initiative
    db = await _db(tmp_path)
    try:
        proxy = _DbProxy(db)
        svc = mi.get_service(proxy)
        assert (await svc.create_intent(
            CHAT, "follow_up", "unanswered_question", goal="g",
            source_refs=("msg:1",)))[0] is None
        assert await svc.due_candidates(now=NOW) == []
        assert (await svc.heartbeat_tick(now=NOW))["enabled"] is False
        assert mi.candidate_from_trigger(trigger_kind="new_message",
                                         chat_id=CHAT) is None
        assert proxy.db.statements == []          # v29 не читается вовсе
        result = await handle_initiative(
            bot=None, chat_id=CHAT,
            situation=mi.InitiativeSituation(trigger_kind="intent_due",
                                             chat_id=CHAT),
            candidates=[])
        assert result["status"] == "disabled"
        assert await mi.heartbeat_tick(db, now=NOW) == {
            "status": "disabled", "due": 0, "candidates": 0, "chats": 0}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_k2_off_subset(tmp_path, monkeypatch):
    """K2 OFF: due-тика нет; создание/закрытие намерений возможно."""
    monkeypatch.setattr(type(settings), "MCA_INTENT_HEARTBEAT_ENABLED", False)
    assert mca_gates.intents_enabled() is True
    assert mca_gates.intent_heartbeat_enabled() is False
    assert mca_gates.intent_decision_enabled() is True
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        assert await svc.due_candidates(now=NOW) == []
        intent_id, created = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question", goal="g",
            source_refs=("msg:1",))
        assert created
        assert await svc.close(intent_id, status="fulfilled") is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_k3_off_subset(tmp_path, monkeypatch):
    """K3 OFF: инициативные решения не выполняются; durable-контур жив."""
    monkeypatch.setattr(type(settings), "MCA_INTENT_DECISION_ENABLED", False)
    assert mca_gates.intent_decision_enabled() is False
    assert mca_gates.intent_heartbeat_enabled() is True
    from services.direct_chat_service import handle_initiative
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, created = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question", goal="g",
            source_refs=("msg:1",), not_before=NOW - 1,
            activation_condition="time_due", created_at=NOW - 5)
        assert created
        result = await handle_initiative(
            bot=None, chat_id=CHAT,
            situation=mi.InitiativeSituation(trigger_kind="intent_due",
                                             chat_id=CHAT),
            candidates=[mi.candidate_from_trigger(
                trigger_kind="intent_due", chat_id=CHAT,
                intent_id=intent_id)],
            prepared_text="текст")
        assert result["status"] == "disabled"
    finally:
        await db.close()


def test_k4_off_subset(monkeypatch):
    """K4 OFF: новый recheck-слой не выполняется (существующие гейты)."""
    monkeypatch.setattr(type(settings), "MCA_SEND_RECHECK_ENABLED", False)
    assert mca_gates.send_recheck_enabled() is False
    from services.direct_chat_service import CoordinatorDecision
    outcome = mi.SendRecheck().check(mi.RecheckContext(
        already_answered=True, enabled=False))
    assert outcome.proceed is True and outcome.reason_code == ""
    assert mi.plan_logical_send(
        CoordinatorDecision(intent="chat", addressee="unknown",
                            memory_need=False, tool_calls=(),
                            evaluation="none", action="reply",
                            trigger_kind="intent_due"),
        recheck=mi.SendRecheck(), context=mi.RecheckContext(
            already_answered=True),
        text="x").outcome.proceed is True


def test_no_env_overrides_and_catalog_untouched():
    """0 env-оверрайдов (дефолты ON) + Δ каталога = 0: имена kill-switch не
    попадают в param_catalog (env-only)."""
    from services.param_catalog import REGISTRY
    for key in ("MCA_INTENTS_ENABLED", "MCA_INTENT_HEARTBEAT_ENABLED",
                "MCA_INTENT_DECISION_ENABLED", "MCA_SEND_RECHECK_ENABLED",
                "MCA_INTENT_HEARTBEAT_BATCH_MAX", "MCA_INTENT_MAX_ATTEMPTS",
                "MCA_INTENT_CANDIDATES_MAX", "MCA_INTENT_RETENTION_DAYS",
                "MCA_INTENT_DEFER_BACKOFF_SECONDS"):
        assert key not in REGISTRY
