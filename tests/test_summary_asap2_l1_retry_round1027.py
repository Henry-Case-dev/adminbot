"""ASAP-2 round1027 (T-3947) — correction retry ПОСЛЕ deterministic repair.

Переработка uncommitted partial (same-prompt retry): §15:2508–2520 —
порядок строго ``call → parse → repair → validate → correction-повтор``.
Вторая попытка = system + исходный user + correction-блок с текстом
причины («Do not invent message ids» / «верни строго валидный JSON…»),
ровно ОДНА; kill-switch'и hot-first
(``flags.summary_hybrid_l1_retry_enabled`` /
``flags.summary_hybrid_l1_repair_enabled``; env-слой — ClassVar'ы).
`message_in_multiple_threads` в §95-v2 НЕ существует: пересечение тредов —
валидная many-to-many структура (тест-инверсия ниже).
"""
from __future__ import annotations

import json

import pytest

from config.settings import Settings, settings
from services import hot_config
from services.llm_client import LLMError, LLMTimeoutError
from services.summary_l1_contract import (
    REASON_INVALID_JSON,
    REASON_L1_USELESS_AFTER_REPAIR,
    REASON_LLM_ERROR,
    REASON_LLM_TIMEOUT,
    REASON_TOO_MANY_FACTS,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OK,
)
from services.summary_l1_clusterizer import (
    _correction_block,
    run_l1,
)
from tests.test_summary_l1_clusterizer import _rows3, _thread, _valid_json


class QueueLLM:
    """Мок LLM с очередью ответов (порядок = последовательность попыток)."""

    def __init__(self, responses, error=None):
        self.responses = list(responses)
        self.error = error
        self.calls = []
        self._chat_model = "global-model"
        self._base_url = "https://global.example/v1"

    async def generate(self, messages, **kwargs):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _ok_json():
    return _valid_json([_thread(ids=(101,),
                                facts=[{"text": "факт",
                                        "evidence_message_ids": [101]}])])


def _two_threads_overlap_json():
    """Сообщение 101 в двух темах + 102 только во второй — в v2 ПОЛНОСТЬЮ
    ВАЛИДНО (many-to-many; бывшая причина message_in_multiple_threads
    удалена из контракта)."""
    return _valid_json([
        _thread(ids=(101,), facts=[{"text": "факт А",
                                    "evidence_message_ids": [101]}],
                thread_id="thread_001"),
        _thread(topic="вторая", ids=(101, 102),
                facts=[{"text": "факт Б", "evidence_message_ids": [102]}],
                thread_id="thread_002"),
    ])


def _unknown_id_json(unknown=999):
    """Один выдуманный id (только в message_ids): 1 occurrence из 2 distinct
    referenced = 0.5 → НЕ useless (§17 тест 5: «repair → pipeline
    продолжается»); >0.5 было бы useless (формула Q3)."""
    return _valid_json([_thread(
        ids=(101, unknown),
        facts=[{"text": "факт", "evidence_message_ids": [101]}])])


# ── 1. invalid_json → РОВНО ОДНА correction-повторная попытка → ok ────────

@pytest.mark.asyncio
async def test_correction_retry_after_invalid_json(caplog):
    llm = QueueLLM(["не json вовсе", _ok_json()])
    with caplog.at_level("INFO"):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="cid-c1")
    assert result.status == STATUS_OK
    assert result.usable
    assert len(llm.calls) == 2
    assert "L1_CORRECTION_RETRY" in caplog.text
    assert "reason=invalid_json" in caplog.text
    assert "attempts=2" in caplog.text
    # Первая попытка — чистый вход; вторая — system + ТОТ ЖЕ user +
    # correction-блок (same-prompt `continue` из partial ЗАПРЕЩЁН §15).
    first_user = llm.calls[0][1]["content"]
    second_user = llm.calls[1][1]["content"]
    assert second_user.startswith(first_user)
    assert second_user != first_user
    assert llm.calls[1][0]["content"] == llm.calls[0][0]["content"]
    assert "ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: invalid_json" in second_user
    assert "schema_version: 2" in second_user
    assert "Верни исправленный JSON." in second_user


# ── 2. ИНВЕРСИЯ partial: message_in_multiple_threads больше НЕТ — валидно ──

@pytest.mark.asyncio
async def test_overlapping_threads_valid_without_retry(caplog):
    llm = QueueLLM([_two_threads_overlap_json()])
    with caplog.at_level("INFO"):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="cid-c2")
    assert result.status == STATUS_OK
    assert result.usable
    assert result.threads_count == 2
    assert len(llm.calls) == 1                      # retry не срабатывает
    assert "L1_CORRECTION_RETRY" not in caplog.text
    assert "message_in_multiple_threads" not in caplog.text
    # Repair наблюдает пересечение информационно (v2 — не ошибка).
    assert "overlapping_topic_memberships=1" in caplog.text


# ── 3. Unknown id: сначала repair (первенство), retry — только если вред ───

@pytest.mark.asyncio
async def test_single_unknown_id_repaired_no_retry(caplog):
    """§17 тест 5 / failure-case 1: один выдуманный id (1/2 ссылок = 0.5,
    граница НЕ превышена) → repair удалил → прогон ОДНОЙ попыткой."""
    llm = QueueLLM([_unknown_id_json()])
    with caplog.at_level("INFO"):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="cid-c3")
    assert result.status == STATUS_OK
    assert result.usable
    assert len(llm.calls) == 1
    assert "L1_REPAIR" in caplog.text
    assert "unknown_ids_removed=1" in caplog.text
    assert "L1_CORRECTION_RETRY" not in caplog.text


@pytest.mark.asyncio
async def test_unknown_id_correction_lists_ids_in_prompt_only(caplog):
    """Repair OFF (kill-switch) → unknown_message_id fatal → correction
    retry; списки id уходят ТОЛЬКО в промпт, в лог — код/числа (R17)."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: (
                            False if key == "flags.summary_hybrid_l1_repair_enabled"
                            else default))
    try:
        llm = QueueLLM([_unknown_id_json(), _ok_json()])
        with caplog.at_level("INFO"):
            result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                                  correlation_id="cid-c3b")
    finally:
        monkeypatch.undo()
    assert result.status == STATUS_OK
    assert len(llm.calls) == 2
    assert "L1_REPAIR" not in caplog.text           # kill-switch respected
    second_user = llm.calls[1][1]["content"]
    assert "999" in second_user                     # id — в промпт
    assert "Do not invent message ids" in second_user
    assert "Используй ТОЛЬКО message_id из входных данных" in second_user
    assert "999" not in caplog.text                 # …но НЕ в лог


# ── 4. «useless после repair» — новая причина correction-ретрая ───────────

@pytest.mark.asyncio
async def test_useless_after_repair_then_correction(caplog):
    """Модель сыпет выдуманными id (>50% ссылок) → useless
    (mass_unknown_ids) → РОВНО одна исправляющая попытка → вторая чистая —
    ok, attempts=2."""
    bad = _valid_json([_thread(
        ids=(901, 902, 101),
        facts=[{"text": "факт", "evidence_message_ids": [901, 902, 101]}])])
    llm = QueueLLM([bad, _ok_json()])
    with caplog.at_level("INFO"):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="cid-c4")
    assert result.status == STATUS_OK
    assert len(llm.calls) == 2
    assert "useless=1" in caplog.text
    assert "useless_reason=mass_unknown_ids" in caplog.text
    assert "reason=l1_useless_after_repair" in caplog.text
    second_user = llm.calls[1][1]["content"]
    assert "ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: l1_useless_after_repair" in second_user
    assert "mass_unknown_ids" in second_user


@pytest.mark.asyncio
async def test_useless_both_attempts_final_reason(caplog):
    """Обе попытки useless → итоговый invalid с reason ВТОРОЙ попытки →
    вызывающий контур уходит в LEVEL-2 (не здесь (unit-срез) — контракт (i))."""
    bad = _valid_json([_thread(
        ids=(901, 902, 903, 101),
        facts=[{"text": "факт",
                "evidence_message_ids": [901, 902, 903, 101]}])])
    llm = QueueLLM([bad, bad])
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c5")
    assert result.status == STATUS_INVALID
    assert result.invalid_reason == REASON_L1_USELESS_AFTER_REPAIR
    assert result.payload is None and not result.usable
    assert len(llm.calls) == 2                      # ровно одна поправка


# ── 5. Пустой ответ — retryable (empty_response в наборе post-repair) ──────

@pytest.mark.asyncio
async def test_empty_response_correction_retry():
    llm = QueueLLM(["   ", _ok_json()])
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c6")
    assert result.status == STATUS_OK
    assert len(llm.calls) == 2


# ── 6. Ровно ОДНА повторная попытка (не лавина; §21-антипаттерн) ───────────

@pytest.mark.asyncio
async def test_exactly_one_correction_no_cascade():
    llm = QueueLLM(["мусор", "мусор", _ok_json()])
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c7")
    assert len(llm.calls) == 2                      # третья НЕ запрашивается
    assert result.status == STATUS_INVALID


# ── 7. too_many_* — single-shot (переполнение контракта → LEVEL-2) ─────────

@pytest.mark.asyncio
async def test_no_retry_on_too_many_facts():
    threads = [_thread(topic=f"тема {i}", ids=(101,), thread_id=f"thread_{i:03d}",
                       facts=[{"text": f"факт {j}",
                               "evidence_message_ids": [101]}
                              for j in range(31)])
               for i in range(2)]
    payload = json.dumps({"schema_version": 2, "threads": threads,
                          "unassigned_message_ids": []}, ensure_ascii=False)
    llm = QueueLLM([payload, _ok_json()])
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c8")
    assert result.status == STATUS_INVALID
    assert result.invalid_reason == REASON_TOO_MANY_FACTS
    assert len(llm.calls) == 1                      # ретрая нет


# ── 8. Kill-switch retry OFF → прежний single-shot байт-в-байт ─────────────

@pytest.mark.asyncio
async def test_retry_kill_switch_off_single_call():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: (
                            False if key == "flags.summary_hybrid_l1_retry_enabled"
                            else default))
    try:
        llm = QueueLLM(["не json", _ok_json()])
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="cid-c9")
    finally:
        monkeypatch.undo()
    assert result.status == STATUS_INVALID
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_kill_switches_off_via_env_classvar(monkeypatch):
    """Env-слой тумблеров (по умолчанию ON); OFF- env ClassVar тоже гасится
    (off = hot не задан → env)."""
    monkeypatch.setattr(Settings, "SUMMARY_L1_RETRY_ENABLED", False)
    llm = QueueLLM(["не json", _ok_json()])
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c10")
    assert result.status == STATUS_INVALID
    assert len(llm.calls) == 1
    assert getattr(settings, "SUMMARY_L1_REPAIR_ENABLED") is True


# ── 9. Транспорт — без correction-ретрая (как в partial) ───────────────────

@pytest.mark.asyncio
async def test_no_retry_on_llm_error():
    llm = QueueLLM([_ok_json()], error=LLMError("boom"))
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c11")
    assert result.status == STATUS_ERROR
    assert result.invalid_reason == REASON_LLM_ERROR
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_no_retry_on_llm_timeout():
    llm = QueueLLM([_ok_json()], error=LLMTimeoutError("timeout"))
    result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                          correlation_id="cid-c12")
    assert result.status == STATUS_ERROR
    assert result.invalid_reason == REASON_LLM_TIMEOUT
    assert len(llm.calls) == 1


# ── 10. Валидный ответ с первой попытки — attempts=1, correction нет ───────

@pytest.mark.asyncio
async def test_first_attempt_ok_no_correction(caplog):
    llm = QueueLLM([_ok_json()])
    with caplog.at_level("INFO"):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="cid-c13")
    assert result.status == STATUS_OK
    assert len(llm.calls) == 1
    assert "L1_CORRECTION_RETRY" not in caplog.text
    assert "attempts=1" in caplog.text


# ── 11. Формы correction-блока по классам (текст контракта (c)) ────────────

def test_correction_block_text_by_class():
    block_json = _correction_block(REASON_INVALID_JSON, unknown_ids=[])
    assert "ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: invalid_json" in block_json
    assert "schema_version: 2" in block_json
    assert "Верни исправленный JSON." in block_json
    block_ids = _correction_block("unknown_message_id",
                                  unknown_ids=[7, 8, 9])
    assert "[7, 8, 9]" in block_ids
    assert "Используй ТОЛЬКО message_id из входных данных" in block_ids
    assert "Не выдумывай идентификаторы" in block_ids
    assert "Do not invent message ids" in block_ids
    block_useless = _correction_block(
        REASON_L1_USELESS_AFTER_REPAIR, unknown_ids=[],
        useless_reason="no_facts")
    assert "после ремонта не осталось пригодных тем/фактов" in block_useless
    assert "no_facts" in block_useless
    # cap ≤20 id
    many = list(range(1, 41))
    assert _correction_block("unknown_message_id",
                             unknown_ids=many[:20]).count(",") >= 19


# ── 12. Retryable-набор = пост-repair список контракта (c) ─────────────────

def test_retryable_set_matches_contract_c():
    from services.summary_l1_clusterizer import _RETRYABLE_REASONS
    assert _RETRYABLE_REASONS == frozenset({
        "invalid_json", "empty_response", "bad_type", "unknown_field",
        "bad_schema_version", "invalid_thread_id", "invalid_topic",
        "invalid_fact", "l1_useless_after_repair", "unknown_message_id",
    })
    # НЕ retryable: транспорт, переполнение контракта, наши баги.
    for gone in ("llm_error", "llm_timeout", "too_many_threads",
                 "too_many_facts", "too_many_facts_total",
                 "id_space_mismatch", "internal_error",
                 "message_in_multiple_threads"):
        assert gone not in _RETRYABLE_REASONS
