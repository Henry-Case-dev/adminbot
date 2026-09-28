"""ASAP-2 round1027 (T-3956, §18) — observability: лог одного прогона
читается как pipeline, новые события/поля, R17-safe (без raw/secret).

Проверяет аддитивность: существующие имена событий НЕ переименованы; новые
события (L1_PARSE/L1_REPAIR/L1_CORRECTION_RETRY/L1_FALLBACK_PACKAGE/
LEGACY_FALLBACK/LEGACY_CHUNKS_CAPPED/L2_OVER_SOFT_CEILING) присутствуют;
поля §18 (messages_before/after, serialized_chars/tokens, response_mode/
targets, chars, topics/messages, attempts, fallback=) — на своих местах.
"""
from __future__ import annotations

import json
import logging

import pytest

from services.summary_l1_clusterizer import run_l1
from services.summary_l2_writer import run_l2
from tests.test_summary_asap2_failsoft_round1027 import (
    CHAT, FakeMemory, _HYBRID_FLAG, _L2_JSON, _fixed_rid, _gen, _lines,
    _patch_chat_limit, _run_gen,
)
from tests.test_summary_l1_clusterizer import _rows3, _thread, _valid_json
from tests.test_summary_l2_writer import _doc, _package, _SlotStub


class QueueLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_t3956_l1_pipeline_events_and_fields(caplog):
    """L1_START → L1_PARSE → L1_REPAIR → L1_COMPLETE(attempts) в порядке §18."""
    secret = "СЕКРЕТНЫЙ_СЫРОЙ_ТЕКСТ_В_ОТВЕТЕ_НЕ_ПИШЕМ"
    payload = _valid_json([_thread(
        "тема", (101, 999),
        [{"text": secret, "evidence_message_ids": [101]}])])
    llm = QueueLLM([payload])
    with caplog.at_level(logging.INFO):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="run-obs1")
    assert result.status == "ok"
    idx = {}
    for name in ("L1_START", "L1_PARSE", "L1_REPAIR", "L1_COMPLETE"):
        lines = _lines(caplog, name)
        assert lines, name
        idx[name] = lines[0]
    assert "attempt=1" in idx["L1_PARSE"] and "parse_status=ok" in idx["L1_PARSE"]
    assert "raw_chars=" in idx["L1_PARSE"]
    for field in ("overlapping_topic_memberships=", "unknown_ids_removed=1",
                  "facts_removed=", "topics_removed=",
                  "evidence_membership_added=",
                  "unassigned_conflicts_resolved=", "useless=0",
                  "useless_reason=-"):
        assert field in idx["L1_REPAIR"], field
    assert "attempts=1" in idx["L1_COMPLETE"]
    # R17: сырой текст факта в лог НЕ попадает (только числа/коды).
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_t3956_correction_retry_event_codes_only(caplog):
    """L1_CORRECTION_RETRY: reason-код и attempt; списки unknown-id в ЛОГ
    не пишутся (R17) — они только в correction-промпте."""
    payload_bad = _valid_json([_thread(
        "тема", (998, 999, 997, 101),
        [{"text": "факт",
          "evidence_message_ids": [998, 999, 997, 101]}])])
    llm = QueueLLM([payload_bad, _valid_json([_thread(
        ids=(101,), facts=[{"text": "ф", "evidence_message_ids": [101]}])])])
    with caplog.at_level(logging.INFO):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="run-obs2")
    assert result.status == "ok"
    retry = _lines(caplog, "L1_CORRECTION_RETRY")
    assert retry and "attempt=1/2" in retry[0]
    assert "reason=l1_useless_after_repair" in retry[0]
    assert "998" not in caplog.text and "999" not in caplog.text
    complete = _lines(caplog, "L1_COMPLETE")
    assert complete and "attempts=2" in complete[0]


@pytest.mark.asyncio
async def test_t3956_l2_start_fields_and_chars(monkeypatch, caplog):
    """L2_START += response_mode/target_chars/target_paragraphs;
    L2_COMPLETE += chars; §18-алиасы не переименованы (L2_RESULT≡L2_COMPLETE)."""
    from services import hot_config
    real = hot_config.get
    monkeypatch.setattr(hot_config, "get", lambda k, d=None: (
        "casual" if k == "limits.summary_hybrid_response_mode" else real(k, d)))
    llm = QueueLLM([json.dumps(_doc(paragraphs=[
        {"text": "Абзац.", "emphasis": None}]), ensure_ascii=False)])
    with caplog.at_level(logging.INFO):
        await run_l2(llm, _package(), slot=_SlotStub(),
                     correlation_id="run-obs3", chat_id=None)
    start = _lines(caplog, "L2_START")
    assert start and "response_mode=casual" in start[0]
    assert "target_chars=4000" in start[0] and "target_paragraphs=5" in start[0]
    assert "paragraphs_hint=5" in start[0]      # pin-совместимость сохранена
    complete = _lines(caplog, "L2_COMPLETE")
    assert complete and "chars=" in complete[0]
    assert "trimmed=" not in complete[0]        # T-3936: метка удалена


@pytest.mark.asyncio
async def test_t3956_fact_package_topics_messages(monkeypatch, caplog):
    """FACT_PACKAGE_COMPLETE += topics=/messages= (контракт (k))."""
    _fixed_rid(monkeypatch)
    _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
    from unittest.mock import AsyncMock, MagicMock
    from services.summary_l1_contract import invalid_result

    async def dead_l1(**kwargs):
        return invalid_result("l1_useless_after_repair")

    monkeypatch.setattr("services.summary_l1_clusterizer.run_l1", dead_l1)
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=_L2_JSON)
    gen = _gen(_fake_memory(), llm)
    with caplog.at_level(logging.INFO):
        await _run_gen(gen)
    fb = _lines(caplog, "L1_FALLBACK_PACKAGE")
    assert fb and "reason=l1_useless_after_repair" in fb[0]
    assert "fragments=" in fb[0] and "chronology=" in fb[0] and "run_id=" \
        in fb[0]
    complete = _lines(caplog, "SUMMARY_COMPLETE")
    assert complete and "fallback=none" in complete[0]


def _fake_memory():
    from tests.test_summary_publish_integration_round1026 import _rows
    return FakeMemory(rows=_rows())


def test_t3956_existing_event_names_not_renamed():
    """Инвариант (k) + ASAP-2.1 (T-3986, раздел 4 spec): пины S7/S8 не
    сломаны — имена существующих событий на месте в коде (grep-уровень).
    FILTER_COMPLETE/RESTORE_* УДАЛЕНЫ вместе с S1/S2 (замещены
    SOURCE_WINDOW/L1_CONTEXT_PACK); новые имена на месте."""
    import pathlib
    files = ["services/summary_l1_clusterizer.py", "services/summary_l2_writer.py",
             "services/summary_fact_package.py", "services/summary_run_log.py",
             "services/summary_generator.py"]
    blob = "".join(pathlib.Path(f).read_text(encoding="utf-8")
                   for f in files)
    for name in ("L1_START", "L1_COMPLETE", "L1_ERROR", "L2_START",
                 "L2_COMPLETE", "L2_SKIPPED", "FACT_PACKAGE_START",
                 "FACT_PACKAGE_COMPLETE", "SUMMARY_START",
                 "SUMMARY_COMPLETE", "SUMMARY_FAILED",
                 # ASAP-2.1: новые события §36:
                 "SOURCE_WINDOW", "L1_CONTEXT_PACK"):
        assert name in blob, name
    # Удалённые события S1/S2 не реинкарнировались (строки-эмиттеры нет):
    assert 'event=FILTER_START' not in blob
    assert 'event=FILTER_COMPLETE' not in blob
    assert 'event=RESTORE_START' not in blob
    assert 'event=RESTORE_COMPLETE' not in blob
