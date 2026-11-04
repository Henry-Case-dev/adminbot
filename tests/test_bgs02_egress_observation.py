"""BGS-02 — контракт: Evidence Egress Guard только наблюдает.

BEHAVIOR-GATES-SIMPLIFICATION-01 (owner input 2026-11-05, §3 BGS-02,
§8 матрица пересечений, §9 приёмка):

* неподтверждённое высокорисковое утверждение больше НЕ вырезается из готового
  ответа и не вызывает повторной генерации/второго поиска;
* отсутствие подтверждения = неопределённость: код + место уходят в событие
  ``EVIDENCE_EGRESS_CHECK``, а доставляется ровно текст L2;
* claim, который раньше «исчезал», теперь доставляется целиком;
* проверка claim↔evidence сохранена (наблюдение по РЕАЛЬНО доставленной
  выдержке, «прочитал» ≠ подтверждено);
* ответ вне целевого фактчека не получает ложный знак «проверено»;
* техническая санитаризация машинных маркеров (<thought>, ``fact:ID``) и
  запреты RBAC/SSRF/рубильника остаются в силе.

TEST-LIFECYCLE: CONTRACT owner=BGS-02.
"""
import asyncio

import pytest

from services import direct_chat_service as dcs
from services import evidence_policy as ep
from services import outgoing_guard as og


def _run(coro):
    return asyncio.run(coro)


def _factual() -> "ep.EvidenceDecision":
    return ep.EvidenceDecision(required=True,
                               evidence_class="externally_factual")


# ════════════════════════════════════════════════════════════════════════════
# 1. §3 п.1/п.2: раньше удалялось — теперь доставляется с честным состоянием
# ════════════════════════════════════════════════════════════════════════════

def test_previously_dropped_claim_is_now_delivered_byte_identical():
    """«Модель X не существует» без источника доставляется целиком.

    Раньше: lookup → reroll → детерминированное удаление этого предложения.
    Теперь ни одна буква ответа не меняется, а факт наблюдения виден в
    статистике события."""
    answer = "Модели GeForce RTX 9090 не существует. Ну и ладно."
    delivered, stats = _run(dcs._run_evidence_egress_guard(
        answer=answer, decision=_factual(), evidence_text=""))
    assert delivered == answer
    assert stats["observed"] == 1
    assert stats["code"] == ep.GUARD_OBSERVED_UNVERIFIED
    assert stats["reason_code"] == ep.REASON_EVIDENCE_CLAIM_OBSERVED
    # Место указывает на спорное предложение, а не на весь ответ.
    assert answer[stats["char_start"]:stats["char_end"]] \
        == "Модели GeForce RTX 9090 не существует."
    assert stats["sentence_index"] == 0


def test_drop_branch_and_rewrite_helper_do_not_exist():
    """Эквивалентного postprocess/rewrite с тем же эффектом не осталось.

    Ветка ``GUARD_DROP_CLAIM``, функция ``drop_claim_sentence`` и повторный
    Writer-guard'а (``_evidence_rewrite``) удалены целиком: их нельзя вызвать
    ни напрямую, ни через DI-параметры."""
    import inspect

    for gone in ("GUARD_DROP_CLAIM", "GUARD_HINT_RETRY", "GUARD_ONE_LOOKUP",
                 "drop_claim_sentence", "EgressVerdict"):
        assert not hasattr(ep, gone), gone
    assert ep.GUARD_ACTIONS == (ep.GUARD_NONE, ep.GUARD_OBSERVED_UNVERIFIED)
    params = inspect.signature(dcs._run_evidence_egress_guard).parameters
    assert "lookup" not in params and "rewrite" not in params
    assert "drop_allowed" not in params
    for gone in ("_evidence_lookup", "_evidence_rewrite"):
        assert not hasattr(dcs.DirectChatService, gone), gone
    assert not hasattr(dcs, "EVIDENCE_EGRESS_HINT")


# ════════════════════════════════════════════════════════════════════════════
# 2. Проверка claim↔evidence сохранена (и не ослаблена)
# ════════════════════════════════════════════════════════════════════════════

def test_claim_evidence_check_still_works_on_delivered_sources():
    """«Прочитал документацию» без доставленной выдержки — наблюдение;
    с реальной выдержкой — тишина (source_fetched ≠ verified)."""
    answer = "Я прочитал документацию: там 16 ГБ видеопамяти."
    unsupported, stats = _run(dcs._run_evidence_egress_guard(
        answer=answer, decision=_factual(), evidence_text=""))
    assert stats["observed"] == 1 and unsupported == answer

    supported, stats2 = _run(dcs._run_evidence_egress_guard(
        answer=answer, decision=_factual(),
        evidence_text="Спецификация: видеопамяти 16 ГБ, шина 256 бит."))
    assert stats2["observed"] == 0 and supported == answer


def test_transformation_class_is_out_of_scope():
    """Пересказ поданного текста и историю не перепроверяем вебом."""
    decision = ep.EvidenceDecision(required=False,
                                   evidence_class="transformation")
    answer = "Новая цена будет 700$."
    observation = ep.guard_egress(answer=answer, decision=decision,
                                  evidence_text="")
    assert observation.action == ep.GUARD_NONE
    assert observation.note == "not_externally_factual"
    delivered, stats = _run(dcs._run_evidence_egress_guard(
        answer=answer, decision=decision, evidence_text=""))
    assert delivered == answer and stats["observed"] == 0


# ════════════════════════════════════════════════════════════════════════════
# 3. Событие: код + место, без текста (R17)
# ════════════════════════════════════════════════════════════════════════════

def test_observation_event_carries_code_and_location_only(monkeypatch):
    """``EVIDENCE_EGRESS_CHECK``: observed/code/location, без самого текста."""
    seen: list = []
    orig_agentic = dcs.emit_agentic_event
    orig_mca = dcs._mca_events.emit_mca_event

    def spy_agentic(name, **fields):
        seen.append((name, fields))
        return orig_agentic(name, **fields)

    def spy_mca(event_name, *, outcome, **fields):
        seen.append((event_name, dict(fields, outcome=outcome)))
        return orig_mca(event_name, outcome=outcome, **fields)

    monkeypatch.setattr(dcs, "emit_agentic_event", spy_agentic)
    monkeypatch.setattr(dcs._mca_events, "emit_mca_event", spy_mca)

    answer = "Кстати, новая цена будет 700$."
    svc = object.__new__(dcs.DirectChatService)
    _delivered, stats = _run(dcs._run_evidence_egress_guard(
        answer=answer, decision=_factual(), evidence_text=""))
    svc._emit_evidence_egress_event(42, "run-bgs02", stats)

    agentic = [f for n, f in seen if n == dcs._EVIDENCE_EVENT_EGRESS]
    mca = [f for n, f in seen if n == "evidence_egress_check"]
    assert len(agentic) == 1 and len(mca) == 1
    event = agentic[0]
    assert event["observed"] == 1
    assert event["code"] == ep.GUARD_OBSERVED_UNVERIFIED
    assert event["char_start"] == 0 and event["char_end"] == len(answer)
    assert answer not in str(event)                  # полного текста нет
    assert "dropped_claim" not in event
    usage = mca[0]["usage_json"]
    assert usage["observed"] == 1
    assert usage["code"] == ep.GUARD_OBSERVED_UNVERIFIED
    assert usage["char_start"] == 0
    assert answer not in str(usage)
    assert mca[0]["reason_code"] == ep.REASON_EVIDENCE_CLAIM_OBSERVED


# ════════════════════════════════════════════════════════════════════════════
# 4. Продовый путь Direct: ни reroll, ни потери текста
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_direct_handle_delivers_claim_and_makes_no_reroll(monkeypatch):
    """``handle()``: ровно один Writer-вызов, ответ с claim доставлен целиком.

    Это тот самый путь, где раньше стоял повтор и удаление предложения."""
    from tests.test_asap7_direct_l1 import _drive, _FakeLLM, _plan_json

    l2_text = "Вышла версия 1.5 этого ядра, честно."
    calls: list[dict] = []

    async def _writer(self, chat_id, query, *, temperature=None,
                      correlation_id=None, **kw):
        calls.append({"speech": kw.get("speech")})
        return (l2_text, "reply")

    async def _preflight(self, chat_id, correlation_id, **kwargs):
        return ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")

    svc, _react, bot, msg, user = _drive(
        monkeypatch, "бот, какая версия вышла?",
        llm=_FakeLLM(l1=_plan_json(response_act="answer"), l2=l2_text))
    monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _writer)
    monkeypatch.setattr(dcs.DirectChatService, "_evidence_preflight",
                        _preflight)
    events: list = []
    orig_event = dcs.emit_agentic_event

    def _spy(name, **fields):
        events.append((name, fields))
        return orig_event(name, **fields)

    monkeypatch.setattr(dcs, "emit_agentic_event", _spy)
    await svc.handle(bot, msg, user)

    assert len(calls) == 1, calls                  # reroll'а нет
    # Наблюдение реально доехало до телеметрии этого хода.
    checks = [f for n, f in events if n == dcs._EVIDENCE_EVENT_EGRESS]
    assert len(checks) == 1, events
    assert checks[0]["observed"] == 1, checks
    assert checks[0]["code"] == ep.GUARD_OBSERVED_UNVERIFIED, checks
    delivered = svc._send_direct_answer.await_args.args[2]
    assert delivered == l2_text                     # текст байт-в-байт



@pytest.mark.asyncio
async def test_direct_handle_unverified_claim_not_labelled_verified(
        monkeypatch):
    """Ответ вне целевого фактчека не получает ложный знак «проверено».

    L2 получает честную пометку «не утверждай, что проверил» вместо вырезания
    мысли, а доставленный текст не приобретает ни метки верификации, ни
    ссылки: единственное изменение — диагностическое событие."""
    from tests.test_asap7_direct_l1 import _drive, _FakeLLM, _plan_json

    l2_text = "Сборка 1.2.3 падает на старте, проверено лично."
    blocks: list[str] = []

    async def _writer(self, chat_id, query, *, temperature=None,
                      correlation_id=None, **kw):
        blocks.extend(str(b) for b in (kw.get("user_blocks") or []))
        return (l2_text, "reply")

    async def _preflight(self, chat_id, correlation_id, **kwargs):
        return ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual",
                                   required_unmet=True,
                                   failure_code=ep.EvidenceFailureCode.
                                   SEARCH_PROVIDER_DOWN)

    svc, _react, bot, msg, user = _drive(
        monkeypatch, "бот, что за сборка?",
        llm=_FakeLLM(l1=_plan_json(response_act="answer"), l2=l2_text))
    monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _writer)
    monkeypatch.setattr(dcs.DirectChatService, "_evidence_preflight",
                        _preflight)
    await svc.handle(bot, msg, user)

    delivered = svc._send_direct_answer.await_args.args[2]
    assert delivered == l2_text
    note = " ".join(blocks)
    # Честное состояние едет ДО генерации, а не пост-правкой текста.
    assert "не утверждай, что проверил" in note
    assert "выдержек нет" in note
    # Ни метки «проверено», ни выдуманной ссылки в доставленном тексте нет.
    assert "https://" not in delivered
    assert "источник:" not in delivered.lower()


# ════════════════════════════════════════════════════════════════════════════
# 5. Техническая санитаризация и технические гейты — без изменений
# ════════════════════════════════════════════════════════════════════════════

def test_machine_markers_are_still_stripped_while_claim_survives():
    """``<thought>``/``fact:ID`` вычищает технический sanitizer, а смысл — нет."""
    raw = ("Ответ: <thought>внутренний черновик</thought> fact:123 "
           "Модели GeForce RTX 9090 не существует.")
    delivered, stats = _run(dcs._run_evidence_egress_guard(
        answer=raw, decision=_factual(), evidence_text=""))
    assert delivered == raw                    # guard ничего не вырезал
    assert stats["observed"] == 1
    clean = og.sanitize_outgoing(delivered)
    assert "<thought>" not in clean and "внутренний черновик" not in clean
    assert "fact:123" not in clean
    assert "не существует" in clean            # содержательная фраза цела


def test_rbac_and_ssrf_still_block_with_their_own_reasons():
    """RBAC/SSRF/квота/рубильник не обходятся наблюдением — коды на месте."""
    from tests.test_evol_evidence_routing import _ok_ctx

    assert ep.allowed("web_search", _ok_ctx(rbac_ok=False)) == \
        (False, ep.BLOCK_RBAC)
    assert ep.allowed("fetch_url", _ok_ctx(ssrf_ok={"fetch_url": False})) == \
        (False, ep.BLOCK_SSRF)
    assert ep.allowed("web_search", _ok_ctx(quota_ok={"web_search": False})) \
        == (False, ep.BLOCK_QUOTA)
    assert ep.allowed(
        "web_search",
        _ok_ctx(network_allowed={"web_search": False, "fetch_url": True})) == \
        (False, ep.BLOCK_EXTERNAL_DISABLED)
    assert ep.is_external_forbidden("без интернета, просто скажи") is True


def test_env_switch_mca_egress_guard_is_untouched():
    """Другой механизм (loopback/media egress) не относится к BGS-02."""
    from services import mca_gates

    assert hasattr(mca_gates, "egress_guard_enabled")
    assert mca_gates.egress_guard_enabled is not \
        ep.egress_guard_enabled
