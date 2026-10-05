"""MCA-09 `mca-09-intents-initiative` — focused-тесты блока D (T-5035…T-5037).

Покрытие:
  * `SendRecheck` (D4/T-5035): порядок проверок (включённость → адресат/
    родитель → состояние намерения → новые ответы → разрешения инструмента);
    посторонняя ветка не отменяет; ровно ОДНА повторная оценка → defer;
    логи `stale_context`/`already_answered`/`intent_closed`;
  * T-5036: без цепочек (собственные сообщения без нового события/результата);
    chunks = одна логическая отправка (recheck один раз, не дублируется);
  * A16-fixture: тема закрыта, пока бот готовил ответ → проверка перед
    отправкой, отправки нет, бесконечного пересмотра нет.
"""
import pytest

from services import mca_gates
from services import mca_intents as mi
from services.direct_chat_service import (ACTION_REPLY, ACTION_SILENT,
                                          CoordinatorDecision)

CHAT = -100500
NOW = 1_800_000_000


def _decision(**kw) -> CoordinatorDecision:
    base = dict(intent="chat", addressee="unknown", memory_need=False,
                tool_calls=(), evaluation="none", action=ACTION_REPLY,
                trigger_kind="intent_due")
    base.update(kw)
    return CoordinatorDecision(**base)


def _recheck() -> mi.SendRecheck:
    return mi.SendRecheck()


# ═══ T-5035: SendRecheck ═════════════════════════════════════════════════════

def test_applies_only_to_recheck_decisions():
    assert _recheck().applies(_decision(trigger_kind="")) is False
    assert _recheck().applies(_decision(trigger_kind="intent_due")) is True
    assert _recheck().applies(
        _decision(trigger_kind="", recheck_conditions=("new_replies",))) is True


def test_check_order_and_reasons():
    r = _recheck()
    # 1) выключенность (чатовые/фичевые гейты) — отмена с точной причиной
    out = r.check(mi.RecheckContext(enabled=False))
    assert out.proceed is False and out.reason_code == "disabled"
    # 2) адресат/родитель изменились → stale_context
    assert r.check(mi.RecheckContext(addressee_ok=False)).reason_code == \
        "stale_context"
    assert r.check(mi.RecheckContext(parent_changed=True)).reason_code == \
        "stale_context"
    # 3) состояние намерения: терминальное → intent_closed (не реактивируется)
    out = r.check(mi.RecheckContext(
        intent_row={"status": "fulfilled", "merged_into_id": None}))
    assert out.proceed is False and out.reason_code == "intent_closed"
    out = r.check(mi.RecheckContext(
        intent_row={"status": "pending", "merged_into_id": "intent:x"}))
    assert out.reason_code == "intent_closed"
    # 4) новые ответы в релевантной ветке → already_answered + A15-закрытие
    out = r.check(mi.RecheckContext(already_answered=True))
    assert out.proceed is False and out.reason_code == "already_answered"
    assert out.close_intent == "fulfilled"
    out = r.check(mi.RecheckContext(same_branch_replies=True))
    assert out.reason_code == "already_answered"
    # 5) разрешения инструмента: denied → без слепого повтора
    out = r.check(mi.RecheckContext(tool_permission_denied=True))
    assert out.proceed is False and out.reason_code == "disabled"
    # посторонняя ветка: в контексте её нет → готовый ответ НЕ отменяется
    assert r.check(mi.RecheckContext()).proceed is True


def test_semantic_change_one_reevaluation_then_defer():
    r = _recheck()
    changed = mi.RecheckContext(context_version="ctx-v2",
                                evaluated_context_version="ctx-v1",
                                recheck_attempts=0)
    out = r.check(changed)
    assert out.proceed is False and out.recheck_again is True
    assert out.reason_code == "stale_context" and out.defer is False
    # ровно одна повторная оценка: повторная смена → defer (не бесконечно)
    changed2 = mi.RecheckContext(context_version="ctx-v3",
                                 evaluated_context_version="ctx-v1",
                                 recheck_attempts=1)
    out = r.check(changed2)
    assert out.proceed is False and out.defer is True
    assert out.reason_code == "recheck_deferred"
    # без смены условий — proceed
    assert r.check(mi.RecheckContext(
        context_version="ctx-v1",
        evaluated_context_version="ctx-v1")).proceed is True


def test_k4_off_subset():
    """K4 OFF → новый recheck-слой не выполняется (документ. подмножество)."""
    old = mca_gates.send_recheck_enabled
    try:
        mca_gates.send_recheck_enabled = lambda: False
        out = _recheck().check(mi.RecheckContext(enabled=False))
        assert out.proceed is True and out.reason_code == ""
    finally:
        mca_gates.send_recheck_enabled = old


def test_apply_recheck_cancels_and_defers():
    decision = _decision()
    assert mi.apply_recheck(decision, mi.RecheckOutcome(True, "")) is True
    assert decision.action == ACTION_REPLY
    decision2 = _decision()
    assert mi.apply_recheck(
        decision2, mi.RecheckOutcome(False, "already_answered",
                                     close_intent="fulfilled")) is False
    assert decision2.action == ACTION_SILENT
    assert decision2.reason_codes == ("already_answered",)
    decision3 = _decision()
    assert mi.apply_recheck(
        decision3, mi.RecheckOutcome(False, "recheck_deferred", defer=True),
        now=NOW) is False
    assert decision3.action == ACTION_SILENT
    assert decision3.next_check_at == NOW + \
        mca_gates.intent_defer_backoff_seconds()


# ═══ T-5036: chunks = одна логическая отправка, без цепочек ═════════════════

def test_chunk_text_pure_and_bounded():
    assert mi.chunk_text("") == ()
    short = "короткий текст"
    assert mi.chunk_text(short) == (short,)
    long = ("слово " * 2000).strip()          # > 4096 символов
    chunks = mi.chunk_text(long)
    assert len(chunks) >= 2
    assert all(len(c) <= mi.CHUNK_LIMIT for c in chunks)
    assert "".join(c.replace(" ", "") for c in chunks) == \
        long.replace(" ", "")
    # разбиение не выполняет проверок (чистая функция)
    import inspect
    src = inspect.getsource(mi.chunk_text)
    assert "check" not in src and "emit" not in src


def test_plan_logical_send_recheck_once_for_all_chunks():
    calls: list = []

    class _SpyRecheck(mi.SendRecheck):
        def check(self, context):
            calls.append(1)
            return mi.RecheckOutcome(True, "")

    decision = _decision()
    plan = mi.plan_logical_send(
        decision, recheck=_SpyRecheck(),
        context=mi.RecheckContext(), text="x" * 9000)
    assert len(calls) == 1                     # ровно одна проверка
    assert len(plan.chunks) == 3               # 9000/4096 → 3 chunk'а
    assert plan.outcome.proceed is True


def test_plan_logical_send_cancelled_no_chunks():
    decision = _decision()
    plan = mi.plan_logical_send(
        decision, recheck=_recheck(),
        context=mi.RecheckContext(already_answered=True), text="x" * 9000)
    assert plan.outcome.proceed is False
    assert plan.chunks == ()
    # silent-решение — тоже без chunks (silent ничего не отправляет)
    silent = _decision(action=ACTION_SILENT, trigger_kind="")
    plan2 = mi.plan_logical_send(silent, recheck=_recheck(),
                                 context=mi.RecheckContext(), text="x" * 9000)
    assert plan2.chunks == () and plan2.outcome.proceed is False


def test_chain_allowed_no_self_message_chains():
    # событие-триггеры допустимы по определению
    for kind in ("new_message", "direct_address", "significant_event",
                 "search_completed", "nostalgia_due"):
        assert mi.chain_allowed(trigger_kind=kind) is True
    # intent_due: первая проверка допустима; после попытки — только новое
    # человеческое событие/реальный результат (после отправки follow-up)
    assert mi.chain_allowed(trigger_kind="intent_due",
                            intent_row={"attempts": 0}) is True
    assert mi.chain_allowed(trigger_kind="intent_due",
                            intent_row={"attempts": 1}) is False
    assert mi.chain_allowed(trigger_kind="intent_due",
                            intent_row={"attempts": 1},
                            new_human_event=True) is True
    assert mi.chain_allowed(trigger_kind="intent_due",
                            intent_row={"attempts": 2},
                            new_result=True) is True


# ═══ A16-fixture ═════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a16_topic_closed_while_preparing(tmp_path, monkeypatch):
    """A16: тема меняется/закрывается, пока бот готовил ответ → проверка перед
    отправкой; отправки нет; намерение закрыто без вопроса."""
    from services import mca_events
    from services.database import DatabaseService

    sent: list = []

    def _boom(*a, **k):
        sent.append((a, k))
        raise AssertionError("отправка не должна состояться")

    monkeypatch.setattr("services.telegram_send.send_text", _boom)
    mca_events.reset_pending()
    db = DatabaseService(str(tmp_path / "mca09_d.db"))
    await db.initialize()
    try:
        svc = mi.get_service(db)
        intent_id, created = await svc.create_intent(
            CHAT, "follow_up", "unanswered_question",
            goal="Спросить про собеседование", source_refs=("msg:1",),
            not_before=NOW - 1, activation_condition="time_due",
            created_at=NOW - 10)
        assert created
        row = await svc.store.get_intent(intent_id)
        # решение «ответить» уже готово; перед отправкой — проверка
        decision = mi.decide_initiative(
            situation=mi.InitiativeSituation(trigger_kind="intent_due",
                                             chat_id=CHAT),
            candidates=[mi.InitiativeCandidate(
                trigger_kind="intent_due", chat_id=CHAT,
                intent_id=intent_id).to_decision_candidate()])
        assert decision.action == ACTION_REPLY
        # человек уже сообщил результат (новая реплика в релевантной ветке)
        outcome = mi.SendRecheck().check(mi.RecheckContext(
            intent_row=row, already_answered=True, context_version="v2",
            evaluated_context_version="v1"))
        assert outcome.proceed is False
        assert outcome.reason_code == "already_answered"
        assert mi.apply_recheck(decision, outcome) is False
        assert decision.action == ACTION_SILENT
        # A15-закрытие без повторного вопроса
        assert outcome.close_intent == "fulfilled"
        await svc.close(intent_id, status="fulfilled",
                        reason_code="already_answered", now=NOW)
        assert (await svc.store.get_intent(intent_id))["status"] == "fulfilled"
        # повторной отправки/вопроса нет; новый due-скан ничего не породит
        assert await svc.due_candidates(now=NOW + 3600) == []
        assert sent == []
        # бесконечного пересмотра нет: вторая смена условий → defer
        outcome2 = mi.SendRecheck().check(mi.RecheckContext(
            intent_row=row, context_version="v3",
            evaluated_context_version="v1", recheck_attempts=1))
        assert outcome2.defer is True
        assert outcome2.reason_code == "recheck_deferred"
    finally:
        await db.close()
        mca_events.reset_pending()
