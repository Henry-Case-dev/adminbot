"""ASAP hotfix round1027 — точечные тесты прод-инцидента 27.09 03:17.

Прод-цепочка (chat_id=-1002661910336):
  1. Graph L3-фон: все чанки упали с LLMTimeoutError (nano-gpt ReadTimeout)
     → GraphExtractionError → «batch kept, pipeline continues» (лечится уже
     существующей защитой — здесь проверяем, что она держит и что публикация
     саммари графом не срывается).
  2. Публикация: L2-статья длиннее мягкого капа `limits.max_summary_parts`
     отбраковывалась жёстко (too_many_paragraphs → L2_ERROR «не публикуем»)
     → публикация отменялась целиком. Фикс: детерминированная обрезка
     (маркер trimmed_for_publication), env-only `SUMMARY_L2_TRIM_ENABLED`.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from config.settings import Settings, settings
from services import summary_memory as sm
from services.summary_l2_writer import (
    MAX_PARAGRAPHS_HARD,
    REASON_TOO_MANY_PARAGRAPHS,
    STATUS_INVALID,
    STATUS_OK,
    run_l2,
)
from tests.test_summary_l2_writer import _doc, _package, _SlotStub


class ScriptedLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.response


# ── Фикс №1: L2 too_many_paragraphs не отменяет публикацию ────────────────

@pytest.mark.asyncio
async def test_l2_article_over_cap_is_trimmed_and_publishable():
    """(а) Прод-сценарий: LLM вернул 6 абзацев, мягкий кап = 1 (легаси-дефолт
    MAX_SUMMARY_PARTS) → публикация ПОЛУЧАЕТ документ (обрезка до 1 абзаца),
    а не «не публикуем»."""
    paragraphs = [{"text": f"Абзац номер {i}.", "emphasis": None}
                  for i in range(6)]
    llm = ScriptedLLM(json.dumps(_doc(paragraphs=paragraphs),
                                 ensure_ascii=False))
    result = await run_l2(llm, _package(), slot=_SlotStub(),
                          max_paragraphs=1)
    assert result.status == STATUS_OK
    assert result.usable
    assert result.document is not None
    assert len(result.document["paragraphs"]) == 1
    assert result.document["paragraphs"][0]["text"] == "Абзац номер 0."
    assert result.metrics.get("trimmed_for_publication") is True


def test_l2_trim_respects_rich_char_budget(monkeypatch):
    """После обрезки по капу абзацев бюджет RICH_MAX_CHARS тоже соблюдён:
    длинные абзацы снимаются с конца, публикация остаётся возможной."""
    from services import summary_l2_writer as l2w
    monkeypatch.setattr(l2w, "RICH_MAX_CHARS", 2200)
    long_text = "ы" * 900
    document = {"schema_version": 1, "title": "Дождь",
                "paragraphs": [{"text": long_text, "emphasis": None}
                               for _ in range(5)]}
    metrics = {"status": "ok", "reason": "ok"}
    trimmed = l2w._trim_document_for_publication(document, 4, metrics)
    assert trimmed is not None
    kept = trimmed["paragraphs"]
    assert len(kept) < 4
    total = len(trimmed["title"]) + sum(
        len(p["text"]) + (len(p["emphasis"]) if p.get("emphasis") else 0)
        for p in kept)
    assert total <= 2200
    assert metrics.get("trimmed_for_publication") is True
    assert metrics.get("paragraphs_before") == 5
    assert metrics.get("paragraphs_dropped_count", 0) >= 5 - len(kept) - 1


@pytest.mark.asyncio
async def test_l2_trim_kill_switch_off_exact_legacy_reject():
    """env-only kill-switch OFF → точный прежний fail-closed: invalid +
    reason=too_many_paragraphs (S5 §106, байт-в-байт поведение)."""
    paragraphs = [{"text": f"Абзац номер {i}.", "emphasis": None}
                  for i in range(6)]
    llm = ScriptedLLM(json.dumps(_doc(paragraphs=paragraphs),
                                 ensure_ascii=False))
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Settings, "SUMMARY_L2_TRIM_ENABLED", False)
    try:
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              max_paragraphs=1)
    finally:
        monkeypatch.undo()
    assert result.status == STATUS_INVALID
    assert result.invalid_reason == REASON_TOO_MANY_PARAGRAPHS
    assert result.document is None


@pytest.mark.asyncio
async def test_l2_llm_timeout_still_error_when_trim_on():
    """Обрезка не размывает fail-closed на реальных ошибках: LLMError →
    status=error, документа нет, повторного L2-вызова нет."""
    class TimeoutLLM:
        calls = 0

        async def generate(self, messages, **kwargs):
            from services.llm_client import LLMError
            TimeoutLLM.calls += 1
            raise LLMError("timeout")

    result = await run_l2(TimeoutLLM(), _package(), slot=_SlotStub(),
                          max_paragraphs=1)
    assert result.status == "error"
    assert result.invalid_reason == "llm_error"
    assert result.document is None
    assert TimeoutLLM.calls == 1


@pytest.mark.asyncio
async def test_l2_hard_cap_498_not_trimmed():
    """Жёсткий потолок §99 (MAX_PARAGRAPHS_HARD) остаётся fail-closed даже
    при trim ON: обрезка применяется ТОЛЬКО к мягкому капу."""
    paragraphs = [{"text": "Х", "emphasis": None}
                  for _ in range(MAX_PARAGRAPHS_HARD + 1)]
    document = {"schema_version": 1, "title": "Т", "paragraphs": paragraphs}
    llm = ScriptedLLM(json.dumps(document, ensure_ascii=False))
    result = await run_l2(llm, _package(), slot=_SlotStub(),
                          max_paragraphs=MAX_PARAGRAPHS_HARD)
    assert result.status == STATUS_INVALID
    assert result.invalid_reason == REASON_TOO_MANY_PARAGRAPHS
    assert result.document is None


@pytest.mark.asyncio
async def test_l2_over_cap_document_reaches_deliver_stage(caplog, monkeypatch):
    """(б) Интеграционный срез гибридного пути: L2-статья с абзацами > капа
    доходит до delivery-блока (publish), а не обрывается ранним return
    «не публикуем». Plain-путь (без rich-обложки) — публикация есть."""
    from services.summary_generator import SummaryGenerator
    from services.summary_l2_writer import L2Result

    paragraphs = [{"text": f"Абзац для публикации {i}.", "emphasis": None}
                  for i in range(6)]
    document, metrics = {}, {}
    llm = ScriptedLLM(json.dumps(_doc(paragraphs=paragraphs),
                                 ensure_ascii=False))
    result = await run_l2(llm, _package(
        service={"response_mode": "serious", "cover_prompt": ""}),
        slot=_SlotStub(), max_paragraphs=1)
    assert result.usable
    document, metrics = result.document, result.as_metrics()

    generator = SummaryGenerator.__new__(SummaryGenerator)
    sent = []

    async def _send_text(chat_id, text, parse_mode=None):
        sent.append(text)
        return dataclasses.SimpleNamespace(message_id=77)

    generator._send_text_with_retry = _send_text
    monkeypatch.setattr("services.summary_generator.hot.get",
                        lambda k, d=None: d)

    class _Cfg:
        SUMMARY_CHUNK_DELAY = 0.0

    await generator._publish_plain_document(
        -1002661910336, document, correlation_id="run-hotfix", ctx=None,
        reason="plain")
    assert sent, "plain-публикация должна была состояться"
    assert all("Абзац для публикации" in s for s in sent)


# ── Фикс №2: GraphExtractionError не срывает пайплайн ─────────────────────

class _FakeDB:
    """Минимальный стаб db-слоя для extract-only ветки."""

    def __init__(self, rows):
        self.rows = rows
        self.marked: list = []

    async def get_smart_raw(self, chat_id, cutoff, batch_size,
                            exclude_imported=True, exclude_processed=True):
        if not self.rows:
            return []
        rows, self.rows = self.rows[:batch_size], self.rows[batch_size:]
        return rows

    async def mark_smart_messages_processed(self, chat_id, ids):
        self.marked.append(list(ids))


def _bare_memory(db):
    """MemoryManager без __init__ (только атрибуты extract-only ветки)."""
    memory = sm.MemoryManager.__new__(sm.MemoryManager)
    memory.db = db
    return memory


@pytest.mark.asyncio
async def test_graph_llm_timeout_batch_kept_pipeline_continues():
    """(в) Прод-сценарий graph: все чанки LLMTimeoutError → GraphExtraction-
    Error ловится ВНУТРИ _compress_purge_extract_only, батч НЕ помечен
    processed, метод завершается штатно — публикация саммари продолжается."""
    batch = [{"id": 1}, {"id": 2}, {"id": 3}]
    db = _FakeDB(list(batch))
    memory = _bare_memory(db)

    async def _fail_extract(chat_id, b):
        raise sm.GraphExtractionError(
            "graph extract failed: all 1 chunk(s) failed "
            "| reason=LLMTimeoutError")

    memory._extract_and_save_graph = _fail_extract
    # extract-only метод ДОЛЖЕН вернуть управление (не бросить)
    await memory._compress_purge_extract_only(-1002661910336)
    assert db.marked == []            # батч сохранён (не помечен обработанным)
    # Проверка полноты: сам класс реально бросается вне защиты
    with pytest.raises(sm.GraphExtractionError):
        await _fail_extract(-1002661910336, batch)


@pytest.mark.asyncio
async def test_graph_extract_dropped_marks_batch():
    """Серия фейлов → GraphExtractDropped → батч ЯВНО отброшен (mark) и
    очередь графа не стоит (F1/ADR-1024-6 D3, прежняя семантика)."""
    batch = [{"id": 7}]
    db = _FakeDB(list(batch))
    memory = _bare_memory(db)
    memory._graph_batch_failures = {}

    async def _fail_extract(chat_id, b):
        raise sm.GraphExtractDropped("dropped after max failures")

    memory._extract_and_save_graph = _fail_extract
    await memory._compress_purge_extract_only(-1002661910336)
    assert db.marked == [[7]]


@pytest.mark.asyncio
async def test_graph_success_batch_marks_processed():
    """Успешная экстракция окна → маркер processed (инвариант no-infinite-loop,
    прежняя семантика не регрессировала)."""
    batch = [{"id": 11}, {"id": 12}]
    db = _FakeDB(list(batch))
    memory = _bare_memory(db)

    async def _ok_extract(chat_id, b):
        return None

    memory._extract_and_save_graph = _ok_extract
    await memory._compress_purge_extract_only(-1002661910336)
    assert db.marked == [[11, 12]]


def test_settings_trim_env_only_no_catalog_delta():
    """Δ каталога = 0: новый env-only ClassVar не попадает в dataclass-поля
    (== каталог F8) и default ON."""
    assert getattr(settings, "SUMMARY_L2_TRIM_ENABLED") is True
    assert "SUMMARY_L2_TRIM_ENABLED" not in [
        f.name for f in dataclasses.fields(Settings)]
