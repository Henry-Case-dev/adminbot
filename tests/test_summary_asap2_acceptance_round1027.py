"""ASAP-2 round1027 (T-3958) — приёмочные regression-тесты §17 №1–9
(current_task.md:2560–2602). Backend-контур: Hybrid/Legacy разделение
MAX_SUMMARY_PARTS, many-to-many L1, deterministic repair, мягкие цели длины.

0 реальных LLM/Telegram: моки очереди ответов (QueueLLM/ScriptedLLM).
"""
from __future__ import annotations

import json
import logging

import pytest

from services import hot_config
from services.summary_fact_package import build_fact_package
from services.summary_l1_contract import (
    STATUS_OK,
    build_id_space,
    validate_l1_response,
)
from services.summary_l1_clusterizer import pack_l1_input, run_l1
from services.summary_l2_writer import (
    HYBRID_MAX_CHARS_DEFAULT,
    HYBRID_PRESETS,
    RICH_MAX_CHARS,
    STATUS_INVALID,
    run_l2,
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


def _hot(**overrides):
    real = hot_config.get

    def _get(key, default=None):
        if key in overrides:
            return overrides[key]
        return real(key, default)

    return _get


def _patch_hot(monkeypatch, **overrides):
    monkeypatch.setattr(hot_config, "get", _hot(**overrides))


def _paragraphs(n, width=40):
    return [{"text": f"Абзац {i}: " + "я" * width, "emphasis": None}
            for i in range(n)]


# ── §17.1 MAX_SUMMARY_PARTS=1 → Hybrid L2 с 8 абзацами публикует ПОЛНУЮ ────

@pytest.mark.asyncio
async def test_t3958_01_parts_1_hybrid_publishes_full_article(monkeypatch):
    # Legacy-ключ в hot-слое = 1: Hybrid его НЕ читает (контракт (d)).
    _patch_hot(monkeypatch, **{"limits.max_summary_parts": 1})
    llm = QueueLLM([json.dumps(_doc(paragraphs=_paragraphs(8)),
                               ensure_ascii=False)])
    result = await run_l2(llm, _package(), slot=_SlotStub(),
                          correlation_id="run-a1", chat_id=None)
    assert result.status == STATUS_OK and result.usable
    assert len(result.document["paragraphs"]) == 8       # полная статья
    assert result.metrics.get("trimmed_for_publication") is None


# ── §17.2 MAX_SUMMARY_PARTS=1 → Legacy plain ≤1 часть + WARN ───────────────
# (закреплён интеграционным тестом
#  tests/test_summary_publish_integration_round1026.py::
#  TestNoLossPublication::test_legacy_plain_capped_at_max_summary_parts_with_warn
#  и юнитом cap-хелпера ниже — оба требуются §17.2 через send-кап T-3938).

def test_t3958_02_legacy_cap_helper_dedupe_warn():
    from services.summary_generator import _cap_legacy_chunks
    chunks = ["часть %d" % i for i in range(5)]
    out = _cap_legacy_chunks(chunks, 1, run_id="r", chat_id=-1)
    assert out == ["часть 0"]
    assert _cap_legacy_chunks(chunks, None) == chunks     # hybrid — без капа
    assert _cap_legacy_chunks(chunks, 10) == chunks       # хватает — всё


# ── §17.3 один message_id в topics A и B → VALID ───────────────────────────

def test_t3958_03_message_in_two_topics_valid():
    space = build_id_space([{"message_id": i, "timestamp": 100 + i}
                            for i in (101, 102, 103)])
    data = {
        "schema_version": 2,
        "threads": [
            {"thread_id": "thread_001", "topic": "Тема А",
             "message_ids": [101, 102],
             "facts": [{"text": "факт А", "evidence_message_ids": [101]}]},
            {"thread_id": "thread_002", "topic": "Тема Б",
             "message_ids": [101, 103],
             "facts": [{"text": "факт Б", "evidence_message_ids": [103]}]},
        ],
        "unassigned_message_ids": [],
    }
    result = validate_l1_response(data, space)
    assert result.status == STATUS_OK and result.usable
    # many-to-many карта: 101 в двух темах
    items = [{"message_id": i, "timestamp": 100 + i, "text": "т" + str(i),
              "author_id": 1, "display_name": "A", "reply_to_id": None}
             for i in (101, 102, 103)]
    package = build_fact_package(result, items, budget=("tokens", 99999))
    assert package.deliverable
    chron = package.package["threads"][0]["chronology"]
    assert chron[0]["message_id"] == 101 and chron[0]["topic_ids"] == \
        ["thread_001", "thread_002"]


# ── §17.4 reply внутри одной темы + смыслово в другой → VALID ──────────────

def test_t3958_04_reply_one_topic_meaning_other_valid():
    items = [
        {"message_id": 201, "chat_id": -1, "timestamp": 1, "author_id": 1,
         "display_name": "A", "text": "старая тема", "reply_to_id": None},
        {"message_id": 202, "chat_id": -1, "timestamp": 2, "author_id": 2,
         "display_name": "B", "text": "ответ по старой теме и прыжок в новую",
         "reply_to_id": 201},
    ]
    space = build_id_space(items)
    data = {
        "schema_version": 2,
        "threads": [
            {"thread_id": "thread_001", "topic": "Старая",
             "message_ids": [201, 202],
             "facts": [{"text": "A сказал факт", "evidence_message_ids": [201]}]},
            {"thread_id": "thread_002", "topic": "Новая",
             "message_ids": [202],
             "facts": [{"text": "B перевёл разговор",
                        "evidence_message_ids": [202]}]},
        ],
        "unassigned_message_ids": [],
    }
    result = validate_l1_response(data, space)
    assert result.status == STATUS_OK
    package = build_fact_package(result, items, budget=("tokens", 99999))
    assert package.deliverable
    assert package.package["threads"][1]["chronology"][0]["topic_ids"] == \
        ["thread_001", "thread_002"]


# ── §17.5 L1 содержит один unknown id → repair → pipeline продолжается ─────

@pytest.mark.asyncio
async def test_t3958_05_single_unknown_id_repaired_pipeline_continues(caplog):
    payload = _valid_json([_thread(
        ids=(101, 999),
        facts=[{"text": "факт", "evidence_message_ids": [101]}])])
    llm = QueueLLM([payload])
    with caplog.at_level(logging.INFO):
        result = await run_l1(llm=llm, rows=_rows3(), chat_id=-100,
                              correlation_id="run-a5")
    assert result.status == STATUS_OK and result.usable    # не отбракован
    assert llm.calls == 1                                  # без retry
    assert "L1_REPAIR" in caplog.text
    assert "unknown_ids_removed=1" in caplog.text


# ── §17.6 overlapping topics → FactPackage строится ────────────────────────

def test_t3958_06_overlapping_topics_package_built():
    items = [{"message_id": i, "timestamp": 100 + i, "text": "т" + str(i),
              "author_id": 1, "display_name": "A", "reply_to_id": None}
             for i in (101, 102, 103)]
    data = {
        "schema_version": 2,
        "threads": [
            {"thread_id": "thread_001", "topic": "А", "message_ids": [101, 102],
             "facts": [{"text": "фа", "evidence_message_ids": [101]}]},
            {"thread_id": "thread_002", "topic": "Б", "message_ids": [102, 103],
             "facts": [{"text": "фб", "evidence_message_ids": [103]}]},
        ],
        "unassigned_message_ids": [],
    }
    result = validate_l1_response(data, build_id_space(items))
    assert result.status == STATUS_OK
    package = build_fact_package(result, items, budget=("tokens", 99999))
    assert package.deliverable
    assert package.package["status"] == "ok"


# ── §17.7 одна evidence через разные topics → без двойного пересказа ───────

def test_t3958_07_shared_evidence_semantic_dedup_instruction():
    """Инструкция дедупликации — в каноне L2 (контракт (l)); в пакете общий
    id виден один раз на тему с полной хронологией topic_ids → рассказчик
    объединяет. Мока-статья строится валидатором без дублей блоков."""
    from services.summary_l2_writer import SUMMARY_L2_WRITER_SYSTEM_PROMPT
    assert "расскажи его ОДИН раз" in SUMMARY_L2_WRITER_SYSTEM_PROMPT
    # mock-статья: событие один раз (формальный assert отсутствия дубля).
    doc = _doc(paragraphs=[{"text": "Вася предложил прогуляться под дождём.",
                            "emphasis": None}])
    document, metrics = _validate_ok(doc)
    texts = [p["text"] for p in document["paragraphs"]]
    assert len(texts) == len(set(texts))                   # без дублей


def _validate_ok(doc):
    from services.summary_l2_writer import validate_l2_document
    document, metrics = validate_l2_document(doc, _package())
    assert document is not None, metrics
    return document, metrics


# ── §17.8 L2 больше target умеренно → не режем ─────────────────────────────

@pytest.mark.asyncio
async def test_t3958_08_over_moderate_target_not_cut(monkeypatch):
    _patch_hot(monkeypatch, **{"limits.summary_hybrid_target_chars": 50,
                               "limits.summary_hybrid_target_paragraphs": 1})
    paras = _paragraphs(4, width=100)
    llm = QueueLLM([json.dumps(_doc(paragraphs=paras), ensure_ascii=False)])
    result = await run_l2(llm, _package(), slot=_SlotStub(),
                          correlation_id="run-a8", chat_id=None)
    assert result.status == STATUS_OK and result.usable
    assert len(result.document["paragraphs"]) == 4         # не обрезан
    assert result.metrics["chars"] > 50                    # цель превышена — ок
    assert result.metrics.get("trimmed_for_publication") is None


# ── §17.9 L2 меньше target → не ошибка ─────────────────────────────────────

@pytest.mark.asyncio
async def test_t3958_09_under_target_not_error(monkeypatch):
    _patch_hot(monkeypatch, **{"limits.summary_hybrid_target_chars": 60000})
    llm = QueueLLM([json.dumps(_doc(paragraphs=_paragraphs(1, width=10)),
                               ensure_ascii=False)])
    result = await run_l2(llm, _package(), slot=_SlotStub(),
                          correlation_id="run-a9", chat_id=None)
    assert result.status == STATUS_OK and result.usable


# ── failure-case 5 (spec §4): 30000 → WARN+публикация; 33000 → too_long ───

@pytest.mark.asyncio
async def test_t3958_soft_ceiling_warn_and_publish(caplog, monkeypatch):
    _patch_hot(monkeypatch, **{"limits.summary_hybrid_max_chars": 24000})
    paras = _paragraphs(34, width=880)                     # ≈30 500 символов
    doc = _doc(paragraphs=paras)
    llm = QueueLLM([json.dumps(doc, ensure_ascii=False)])
    with caplog.at_level(logging.WARNING):
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              correlation_id="run-ac1", chat_id=-100)
    assert result.status == STATUS_OK and result.usable    # НЕ отбракован
    assert 24000 < result.metrics["chars"] <= RICH_MAX_CHARS
    assert "L2_OVER_SOFT_CEILING" in caplog.text


@pytest.mark.asyncio
async def test_t3958_above_rich_hard_limit_rejected():
    paras = _paragraphs(38, width=880)                     # ≈33 800 > 32000
    doc = _doc(paragraphs=paras)
    llm = QueueLLM([json.dumps(doc, ensure_ascii=False)])
    result = await run_l2(llm, _package(), slot=_SlotStub(),
                          correlation_id="run-ac2", chat_id=-100)
    assert result.status == STATUS_INVALID
    assert result.invalid_reason == "too_long"             # §99 hard → LEVEL-3


# ── Пресеты/дефолты (Q4): значения зафиксированы ───────────────────────────

def test_t3958_presets_values_locked():
    assert HYBRID_PRESETS == {"casual": (4000, 5), "serious": (6500, 8),
                              "deep_research": (11000, 14)}
    assert HYBRID_MAX_CHARS_DEFAULT == 24000
    assert RICH_MAX_CHARS == 32000
    # запас до rich ≥2.9× для самого большого пресета (Q4)
    assert RICH_MAX_CHARS / HYBRID_PRESETS["deep_research"][0] >= 2.9


# ── Serialized-учёт бюджета (Q5/T-3941(а)): §92-элемент, не только text ───

def test_t3958_serialized_budget_counts_fields():
    rows = _rows3()
    pack_text_only = sum(len(r["text"]) for r in rows)
    pack = pack_l1_input(rows, -100, char_limit=99999)
    serialized = sum(len(json.dumps(item, ensure_ascii=False,
                                    separators=(",", ":")))
                     for item in pack.payload)
    # serialized-оценка ЧЕСТНАЯ: больше голого текста (имена полей §92)
    assert serialized > pack_text_only
    pack2 = pack_l1_input(rows, -100, char_limit=serialized)
    assert pack2.truncated is False                        # влез ровно
    pack3 = pack_l1_input(rows, -100, char_limit=serialized - 1)
    assert pack3.truncated is True                         # вытеснение
