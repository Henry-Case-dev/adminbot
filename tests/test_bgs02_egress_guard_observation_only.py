"""BGS-02 шаг 1: egress guard — НАБЛЮДЕНИЕ, а не пострицензура.

Фокусный контракт `services/evidence_policy.py` (минимальная проверка шага):

1. claim, который раньше вырезался (`GUARD_DROP_CLAIM` / `drop_claim_sentence`),
   доставляется БАЙТ-В-БАЙТ: guard отдаёт наблюдение (код + место), текст
   ответа не меняется ни в guard'е, ни на реальном шве доставки
   (`direct_chat_service._run_evidence_egress_guard`).
2. у наблюдения есть машинный код причины и место в готовом тексте
   (`sentence_index` / `char_start` / `char_end`) — его можно залогировать.
3. «drop»-поверхность (константа действия, helper удаления, fail-closed)
   не вернулась.

Мутация (проверено вручную): возврат удаления claim'а на шве доставки
(`answer.replace(observation.sentence, "")`) делает
`test_real_choke_point_delivers_answer_unchanged` КРАСНЫМ; после отката
мутации файл снова зелёный.

TEST-LIFECYCLE: CONTRACT owner=BGS-02 (evidence egress guard observation-only)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from services import direct_chat_service as dcs
from services import evidence_policy as ep

#: Ответ с ОДНИМ существенным внешним claim'ом (цена) без выдержки-подтверждения.
#: Именно такое предложение старый guard удалял из доставленного текста.
ANSWER = "Привет, я на месте. Теперь цена будет 700$."
UNSUPPORTED_CLAIM = "Теперь цена будет 700$."


@pytest.fixture(autouse=True)
def _clean():
    ep.POLICY_ENABLED_OVERRIDE = None
    ep.EGRESS_ENABLED_OVERRIDE = None
    yield
    ep.POLICY_ENABLED_OVERRIDE = None
    ep.EGRESS_ENABLED_OVERRIDE = None


def _decision(required: bool = False) -> ep.EvidenceDecision:
    return ep.EvidenceDecision(required=required,
                              evidence_class="externally_factual")


def test_unsupported_claim_is_observed_and_text_byte_identical():
    """Ранее удалявшийся claim: наблюдение есть, текст не тронут ни на байт."""
    decision = _decision()
    observation = ep.guard_egress(answer=ANSWER, decision=decision,
                                  evidence_text="")

    # 1) Наблюдение, а не приказ изменить текст.
    assert observation.action == ep.GUARD_OBSERVED_UNVERIFIED, observation
    assert observation.reason_code == ep.REASON_EVIDENCE_CLAIM_OBSERVED
    assert observation.observed is True
    assert observation.sentence == UNSUPPORTED_CLAIM

    # 2) Место реально указывает в исходный текст (0-based срез = тот же claim).
    assert ANSWER[observation.char_start:observation.char_end] \
        == observation.sentence
    assert observation.location["sentence_index"] >= 0

    # 3) Поля события логируются как есть (enum/числа, без правок текста).
    payload = json.loads(json.dumps(observation.event_fields()))
    assert payload["observed"] == 1
    assert payload["code"] == ep.GUARD_OBSERVED_UNVERIFIED
    assert payload["reason_code"] == ep.REASON_EVIDENCE_CLAIM_OBSERVED

    # 4) В наблюдении нет «исправленного» текста: единственный текст — срез
    #    исходного ответа.
    assert observation.sentence in ANSWER


def test_no_drop_surface_remains():
    """«drop»-API и fail-closed удалены: остались только none/observed."""
    assert not hasattr(ep, "GUARD_DROP_CLAIM")
    assert not hasattr(ep, "drop_claim_sentence")
    assert ep.GUARD_ACTIONS == (ep.GUARD_NONE, ep.GUARD_OBSERVED_UNVERIFIED)
    assert not any("drop" in str(action) for action in ep.GUARD_ACTIONS)


def test_real_choke_point_delivers_answer_unchanged():
    """Реальный шов доставки: (answer, stats) — тот же текст + наблюдение."""
    ep.EGRESS_ENABLED_OVERRIDE = True
    decision = _decision()
    delivered, stats = asyncio.run(dcs._run_evidence_egress_guard(
        answer=ANSWER, decision=decision, evidence_text=""))

    assert delivered == ANSWER
    assert delivered.encode("utf-8") == ANSWER.encode("utf-8")
    assert stats["observed"] == 1
    assert stats["code"] == ep.GUARD_OBSERVED_UNVERIFIED
    assert stats["reason_code"] == ep.REASON_EVIDENCE_CLAIM_OBSERVED
    assert delivered[stats["char_start"]:stats["char_end"]] \
        == UNSUPPORTED_CLAIM


def test_no_observation_when_claim_is_supported():
    """Подтверждённый claim не порождает наблюдений (нет ложных срабатываний)."""
    decision = _decision()
    observation = ep.guard_egress(
        answer=ANSWER, decision=decision,
        evidence_text="Прайс: теперь цена будет 700$ за подписку.")
    assert observation.action == ep.GUARD_NONE
    assert observation.observed is False
