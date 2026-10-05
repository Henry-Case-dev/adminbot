"""MCA-09 `mca-09-intents-initiative` — focused-тесты блока C (T-5029…T-5034).

Покрытие:
  * AMEND `CoordinatorDecision`: аддитивные поля §13.3, enum не сломан,
    `defer` — не значение enum, инварианты A7 сохранены;
  * silent-семантика: silent не проходит Вербализатор и ничего не отправляет;
    tool-result может завершиться silent (A17), без слепого повтора;
  * уместность/приоритеты: молчание не поднимает «желание», таймера «раз в
    10 минут» нет, direct-путь не подавляется, дедуп только того же события;
  * mca-10a: random_metadata (F-2: PolicyChoice.source → actual_source) +
    ОДНА probability-проверка на ситуацию, истинность не рандомизируется;
  * mca-11: ToolResult-статусы, tool→silent, без второго учёта;
  * OFF (K1/K3) и дефолты env-лимитов.
"""
import inspect

import pytest

from config.settings import settings
from services import mca_gates
from services import mca_intents as mi
from services.database import DatabaseService
from services.direct_chat_service import (ACTION_REPLY, ACTION_SILENT,
                                          ACTION_TOOL, COORDINATOR_ACTIONS,
                                          REASON_DEFAULT, REASON_QUESTION,
                                          CoordinatorDecision,
                                          DecisionCandidate, DecisionContext,
                                          DecisionToggles,
                                          _decision_pre_action)
from services.mca_random_source import DrawResult, ExplorationPolicy

CHAT = -100500
NOW = 1_800_000_000


def _cand(cid="c1", *, action=ACTION_REPLY, reason="default", source="intent",
          priority=0, admissible=True, intent_id=None, codes=()):
    return DecisionCandidate(
        candidate_id=cid, action=action, reason_code=reason, source=source,
        priority=priority, admissible=admissible, intent_id=intent_id,
        reason_codes=codes)


def _decision(action=ACTION_REPLY, **kw) -> CoordinatorDecision:
    base = dict(intent="chat", addressee="unknown", memory_need=False,
                tool_calls=(), evaluation="none", action=action)
    base.update(kw)
    return CoordinatorDecision(**base)


def _situation(**kw) -> mi.InitiativeSituation:
    base = dict(trigger_kind="intent_due", chat_id=CHAT)
    base.update(kw)
    return mi.InitiativeSituation(**base)


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


# ═══ T-5029: аддитивный контракт ════════════════════════════════════════════

def test_additive_fields_defaults_enum_not_broken():
    d = _decision()
    assert d.trigger_kind == "" and d.intent_id is None
    assert d.reply_target is None and d.candidate_actions == ()
    assert d.selected_candidate is None and d.reason_codes == ()
    assert d.source_refs == () and d.context_version is None
    assert d.recheck_conditions == () and d.next_check_at is None
    assert d.random_metadata is None and d.tool_outcome is None
    assert COORDINATOR_ACTIONS == ("reply", "react", "silent", "tool")
    # `defer` не значение enum; незнакомое → существующая нормализация reply
    assert _decision(action="defer").action == ACTION_REPLY
    assert _decision(action="yell").action == ACTION_REPLY
    # A7-инварианты сохранены
    d2 = _decision(style="silent", reaction="🗿", reason_code="made_up")
    assert d2.style == "" and d2.reaction is None
    assert d2.reason_code == REASON_DEFAULT
    assert not hasattr(d2, "to_json")      # wire-`action` не вводится


def test_decision_candidate_normalization():
    c = DecisionCandidate(candidate_id="", action="defer", reason_code="bogus",
                          source="made_up", communicative_intent="bogus",
                          source_refs=("ok:1", "плохой ref"),
                          prepared_text_ref="a" * 200, random_meta={"hack": 1})
    assert c.candidate_id.startswith("candidate:")
    assert c.action == ACTION_REPLY
    assert c.reason_code == REASON_DEFAULT
    assert c.source == "intent"
    assert c.communicative_intent is None
    assert c.source_refs == ("ok:1",)
    assert c.prepared_text_ref is None
    assert c.random_meta is None
    assert c.id == c.candidate_id           # duck-typing mca-10a


def test_candidate_actions_normalization(monkeypatch):
    monkeypatch.setattr(mca_gates, "intent_candidates_max", lambda: 2)
    c1, c2, c3 = _cand("c1"), _cand("c2"), _cand("c3")
    d = _decision(
        candidate_actions=(c1, c2, c3, "мусор"), selected_candidate="c3",
        reason_codes=("wrong_moment", "made_up", "wrong_moment"),
        recheck_conditions=("new_replies", "made_up"),
        source_refs=("msg:1", "плохой ref"), next_check_at=-5,
        random_metadata={"policy_version": "mca10a-v1", "hack": "x",
                         "draw_ids": ["d1"], "probability": 2.5,
                         "deferred": 1, "actual_source": "pseudorandom"},
        tool_outcome="made_up", trigger_kind="made_up",
        context_version="v" * 300)
    assert len(d.candidate_actions) == 2
    assert d.selected_candidate is None
    assert d.reason_codes == ("wrong_moment",)
    assert d.recheck_conditions == ("new_replies",)
    assert d.source_refs == ("msg:1",)
    assert d.next_check_at == 0
    assert d.tool_outcome is None
    assert d.trigger_kind == ""
    assert len(d.context_version) == 120
    assert d.random_metadata == {"policy_version": "mca10a-v1",
                                 "draw_ids": ["d1"], "probability": 1.0,
                                 "deferred": True,
                                 "actual_source": "pseudorandom"}


def test_selected_candidate_must_be_in_set():
    d = _decision(candidate_actions=(_cand("c1"),),
                  selected_candidate="c1")
    assert d.selected_candidate == "c1"
    d2 = _decision(candidate_actions=(_cand("c1"),),
                   selected_candidate="other")
    assert d2.selected_candidate is None


# ═══ T-5030: silent-семантика (A17) ═════════════════════════════════════════

def _forbid_verb_and_send(monkeypatch):
    calls: list = []

    def _boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("silent не должен доходить до отправки/вербализатора")

    monkeypatch.setattr("services.telegram_send.send_text", _boom)
    monkeypatch.setattr("services.negative_constraints.verbalize_validated",
                        _boom)
    return calls


def test_a17_silent_no_verbalizer_no_send(monkeypatch):
    calls = _forbid_verb_and_send(monkeypatch)
    d = mi.decide_initiative(
        situation=_situation(direct_pending=True), candidates=[_cand()])
    assert d.action == ACTION_SILENT
    assert mi.initiative_delivery_kind(d) == mi.DELIVERY_SILENT
    assert d.reason_codes == ("direct_update_dedup_hit",)
    # tool-result может завершиться silent — тоже без отправки
    tool = _decision(action=ACTION_TOOL, reason_code="tool_result")
    finished = mi.finish_tool_decision(tool, tool_outcome="delivery_unknown")
    assert finished.action == ACTION_SILENT
    assert mi.initiative_delivery_kind(finished) == mi.DELIVERY_SILENT
    assert "insufficient_evidence" in finished.reason_codes
    mi.note_decision(finished, chat_id=CHAT)   # событие, не отправка
    assert calls == []


def test_tool_outcome_matrix():
    from services.tool_result import STATUSES
    assert len(STATUSES) == 7
    base = _decision(action=ACTION_TOOL, reason_code="tool_result")
    assert mi.finish_tool_decision(base, tool_outcome="ok").action == \
        ACTION_TOOL
    empty = mi.finish_tool_decision(
        _decision(action=ACTION_TOOL, reason_code="tool_result"),
        tool_outcome="empty")
    assert empty.action == ACTION_SILENT
    assert empty.tool_outcome == "empty"
    assert "no_new_contribution" in empty.reason_codes
    for outcome in ("error", "timeout", "cancelled", "denied",
                    "delivery_unknown"):
        row = mi.finish_tool_decision(
            _decision(action=ACTION_TOOL, reason_code="tool_result"),
            tool_outcome=outcome)
        assert row.action == ACTION_SILENT, outcome
        assert row.tool_outcome == outcome
        assert "insufficient_evidence" in row.reason_codes
    # explicit/question/force — никогда silent (A7 §43)
    forced = mi.finish_tool_decision(
        _decision(action=ACTION_TOOL, reason_code="tool_result"),
        tool_outcome="error", forced=True)
    assert forced.action == ACTION_TOOL
    # unknown ≠ ok: незнакомый статус не публикуем
    unknown = mi.finish_tool_decision(
        _decision(action=ACTION_TOOL, reason_code="tool_result"),
        tool_outcome="made_up")
    assert unknown.action == ACTION_SILENT
    assert unknown.tool_outcome is None
    # None — решение не меняется
    assert mi.finish_tool_decision(
        _decision(action=ACTION_TOOL), tool_outcome=None).action == ACTION_TOOL


# ═══ T-5031: уместность/приоритеты ══════════════════════════════════════════

def test_appropriateness_silence_reasons():
    cand = _cand()
    dedup = mi.decide_initiative(situation=_situation(same_event_pending=True),
                                 candidates=[cand])
    assert dedup.action == ACTION_SILENT
    assert dedup.reason_codes == ("direct_update_dedup_hit",)
    sensitive = mi.decide_initiative(situation=_situation(sensitive_moment=True),
                                     candidates=[cand])
    assert sensitive.reason_codes == ("wrong_moment",)
    closed_topic = mi.decide_initiative(situation=_situation(topic_open=False),
                                        candidates=[cand])
    assert closed_topic.reason_codes == ("wrong_moment",)
    recent = mi.decide_initiative(situation=_situation(bot_replied_recently=True),
                                  candidates=[cand])
    assert recent.action == ACTION_SILENT
    assert recent.reason_code == "recent_reply"
    # необходимость ответа перевешивает «недавно отвечали»
    needed = mi.decide_initiative(
        situation=_situation(bot_replied_recently=True, reply_needed=True),
        candidates=[cand])
    assert needed.action == ACTION_REPLY
    empty = mi.decide_initiative(situation=_situation(), candidates=[])
    assert empty.action == ACTION_SILENT
    assert empty.reason_codes == ("no_eligible_alternative",)
    stale = mi.decide_initiative(situation=_situation(),
                                 candidates=[_cand(codes=("no_new_contribution",))])
    assert stale.action == ACTION_SILENT
    # приоритет: выбран кандидат с большим priority
    best = mi.decide_initiative(
        situation=_situation(),
        candidates=[_cand("a", priority=1), _cand("b", priority=5)])
    assert best.selected_candidate == "b"


def test_intent_closed_candidate_dropped():
    cand = _cand(intent_id="intent:1")
    closed = mi.decide_initiative(situation=_situation(open_intent_ids=()),
                                  candidates=[cand])
    assert closed.action == ACTION_SILENT
    assert closed.reason_codes == ("no_eligible_alternative",)
    opened = mi.decide_initiative(
        situation=_situation(open_intent_ids=("intent:1",)),
        candidates=[cand])
    assert opened.action == ACTION_REPLY
    unknown = mi.decide_initiative(situation=_situation(), candidates=[cand])
    assert unknown.action == ACTION_REPLY


def test_silence_does_not_raise_desire_no_timer():
    """Молчание — чистый исход: повтор даёт тот же результат; таймера «раз в
    10 минут обязательно говорить» в слое решения нет."""
    situation = _situation(sensitive_moment=True)
    first = mi.decide_initiative(situation=situation, candidates=[_cand()])
    second = mi.decide_initiative(situation=situation, candidates=[_cand()])
    assert (first.action, first.reason_codes, first.next_check_at) == \
        (second.action, second.reason_codes, second.next_check_at)
    src = inspect.getsource(mi.decide_initiative)
    assert "write_transaction" not in src and "mark_attempt" not in src
    assert "sleep" not in src and "600" not in src


def test_direct_path_not_suppressed():
    """Квота/инициатива не подавляют прямой ответ: direct-путь A7 отвечает
    explicit/question независимо от слоя инициативы."""
    for message_class in ("explicit_request", "question"):
        action, _, _, _ = _decision_pre_action(
            message_class=message_class, context=DecisionContext(),
            toggles=DecisionToggles(), target_message_id=1)
        assert action == ACTION_REPLY, message_class
    assert _decision_pre_action(
        message_class="question", context=DecisionContext(),
        toggles=DecisionToggles(), target_message_id=1)[1] == REASON_QUESTION
    # при этом инициатива в той же ситуации молчит (дедуп того же события)
    assert mi.decide_initiative(
        situation=_situation(direct_pending=True),
        candidates=[_cand()]).action == ACTION_SILENT


# ═══ T-5032: mca-10a — одна проверка на ситуацию, без второго draw ══════════

class _FakeSource:
    def __init__(self, *, value=0.1, index=0):
        self.value = value
        self.index = index
        self.prob_calls = 0
        self.index_calls = 0

    async def draw_probability(self, *, chat_id=None, purpose="",
                               policy_version=None, probability=None):
        self.prob_calls += 1
        return DrawResult(value=self.value, source="pseudorandom",
                          selected_source="quantum",
                          draw_id=f"p{self.prob_calls}",
                          policy_version=policy_version)

    async def draw_index(self, n, *, chat_id=None, purpose="",
                         policy_version=None, candidates=None,
                         probability=None):
        self.index_calls += 1
        return DrawResult(index=self.index, source="pseudorandom",
                          selected_source="quantum",
                          draw_id=f"i{self.index_calls}",
                          policy_version=policy_version)


@pytest.mark.asyncio
async def test_single_probability_check_and_metadata_f2():
    fake = _FakeSource(value=0.1)
    policy = ExplorationPolicy(source=fake)
    primary, alternative = _cand("primary"), _cand("alt")
    choice = await policy.choose(primary, [alternative], probability=0.5,
                                 chat_id=CHAT, purpose="less_studied_periods")
    assert fake.prob_calls == 1               # одна probability-проверка
    assert fake.index_calls == 1              # один draw альтернативы
    assert choice.explored is True
    meta = mi.build_random_metadata(choice, requested_source="quantum")
    # read-only копия: второй проверки/draw нет
    assert fake.prob_calls == 1 and fake.index_calls == 1
    assert meta["policy_version"] and meta["draw_ids"]
    assert meta["actual_source"] == "pseudorandom"     # F-2 (green)
    assert meta["requested_source"] == "quantum"
    assert meta["probability"] == 0.5 and meta["deferred"] is False
    assert set(meta) <= {"policy_version", "requested_source",
                         "actual_source", "draw_ids", "probability",
                         "fallback_reason", "deferred"}
    # решение с уже выполненной проверкой: альтернатива выигрывает, draw нет
    decision = mi.decide_initiative(situation=_situation(),
                                    candidates=[primary, alternative],
                                    random_choice=choice,
                                    requested_source="quantum")
    assert fake.prob_calls == 1 and fake.index_calls == 1
    assert decision.selected_candidate == "alt"
    assert decision.random_metadata["actual_source"] == "pseudorandom"


@pytest.mark.asyncio
async def test_ineligible_measurement_not_randomized():
    fake = _FakeSource(value=0.1)
    policy = ExplorationPolicy(source=fake)
    primary, alternative = _cand("primary"), _cand("alt")
    choice = await policy.choose(primary, [alternative], probability=0.5,
                                 chat_id=CHAT, purpose="less_studied_periods",
                                 measurement="truth")
    assert fake.prob_calls == 0 and fake.index_calls == 0
    assert choice.selected is primary and choice.explored is False
    assert choice.reason == "no_eligible_alternative"


@pytest.mark.asyncio
async def test_random_fallback_defers_optional_initiative():
    class _DeferredSource(_FakeSource):
        async def draw_probability(self, *, chat_id=None, purpose="",
                                   policy_version=None, probability=None):
            self.prob_calls += 1
            return DrawResult(value=None, deferred=True,
                              reason="provider_unavailable",
                              source="pseudorandom",
                              selected_source="quantum",
                              policy_version=policy_version)

    fake = _DeferredSource()
    policy = ExplorationPolicy(source=fake)
    primary, alternative = _cand("primary"), _cand("alt")
    choice = await policy.choose(primary, [alternative], probability=0.5,
                                 chat_id=CHAT, purpose="less_studied_periods")
    assert choice.deferred is True
    decision = mi.decide_initiative(situation=_situation(),
                                    candidates=[primary, alternative],
                                    random_choice=choice)
    assert decision.action == ACTION_SILENT
    assert decision.reason_codes == ("random_fallback",)
    assert decision.next_check_at is not None      # bounded backoff
    # direct-путь не затрагивается fallback'ом инициативы
    action, _, _, _ = _decision_pre_action(
        message_class="question", context=DecisionContext(),
        toggles=DecisionToggles(), target_message_id=1)
    assert action == ACTION_REPLY


def test_explored_alternative_must_be_admissible():
    primary, alt = _cand("primary"), _cand("alt", admissible=False)

    class _Choice:
        explored = True
        deferred = False
        selected = alt
        policy_version = "mca10a-v1"
        source = "quantum"
        draw_ids = ["d1"]
        probability = 0.5
        fallback_reason = None

    decision = mi.decide_initiative(situation=_situation(),
                                    candidates=[primary, alt],
                                    random_choice=_Choice())
    assert decision.selected_candidate == "primary"


# ═══ T-5033: mca-11 — без второго учёта/слепого повтора ═════════════════════

def test_no_second_accounting_static():
    src = inspect.getsource(mi)
    for forbidden in ("mca_money_limits", "usage_events", "cost_usd",
                      "record_usage"):
        assert forbidden not in src, forbidden
    tool = _decision(action=ACTION_TOOL, reason_code="tool_result")
    mi.finish_tool_decision(tool, tool_outcome="error")
    assert not hasattr(tool, "usage") and not hasattr(tool, "cost_usd")


def test_no_blind_repeat_on_delivery_unknown():
    decision = _decision(action=ACTION_TOOL, reason_code="tool_result")
    finished = mi.finish_tool_decision(decision, tool_outcome="delivery_unknown")
    assert finished.action == ACTION_SILENT
    assert mi.initiative_delivery_kind(finished) == mi.DELIVERY_SILENT
    assert finished.next_check_at is None      # повтор не заказан
    src = inspect.getsource(mi.finish_tool_decision)
    assert "retry" not in src.lower()


# ═══ OFF (K1/K3) и дефолты лимитов ══════════════════════════════════════════

def test_k3_resolver_respects_master(monkeypatch):
    monkeypatch.setattr(type(settings), "MCA_INTENTS_ENABLED", True)
    monkeypatch.setattr(type(settings), "MCA_INTENT_DECISION_ENABLED", True)
    assert mca_gates.intent_decision_enabled() is True
    monkeypatch.setattr(type(settings), "MCA_INTENT_DECISION_ENABLED", False)
    assert mca_gates.intent_decision_enabled() is False
    monkeypatch.setattr(type(settings), "MCA_INTENTS_ENABLED", False)
    monkeypatch.setattr(type(settings), "MCA_INTENT_DECISION_ENABLED", True)
    assert mca_gates.intent_decision_enabled() is False   # K1 master
    assert mca_gates.intent_heartbeat_enabled() is False
    assert mca_gates.send_recheck_enabled() is False


def test_k3_off_decision_disabled(monkeypatch):
    monkeypatch.setattr(mca_gates, "intent_decision_enabled", lambda: False)
    decision = mi.decide_initiative(situation=_situation(),
                                    candidates=[_cand()])
    assert decision.action == ACTION_SILENT
    assert decision.reason_code == "disabled"
    assert decision.reason_codes == ("disabled",)
    assert decision.next_check_at is None


@pytest.mark.asyncio
async def test_k1_off_no_v29_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
    db = DatabaseService(str(tmp_path / "mca09_c.db"))
    await db.initialize()
    try:
        proxy = _DbProxy(db)
        stats = await mi.heartbeat_tick(proxy, now=NOW)
        assert stats["status"] == "disabled"
        assert proxy.db.statements == []      # v29 не читается вовсе
        assert mi.candidate_from_trigger(trigger_kind="new_message",
                                         chat_id=CHAT) is None
    finally:
        await db.close()


def test_k4_resolver_default_on():
    assert mca_gates.send_recheck_enabled() is True
    assert mca_gates.KILL_SWITCHES["MCA_SEND_RECHECK_ENABLED"][0] is True
    assert mca_gates.intent_candidates_max() == 8
    assert mca_gates.intent_heartbeat_batch_max() == 20
    assert mca_gates.intent_max_attempts() == 3
    assert mca_gates.intent_retention_days() == 180
    assert mca_gates.intent_defer_backoff_seconds() == 1800
