"""ASAP hotfix round1027 (2.58.32) + переписка тестов по ASAP-2 §16.

История: прод-цепочка (chat_id=-1002661910336) 27.09 — L2-статья, валидная
по §98/§99, отбраковывалась по мягкому капу ``limits.max_summary_parts`` →
публикации не было. Hotfix 2.58.32 добавил trim-обрезку — ВЛАДЕЛЕЦ ASAP-2 §16
потребовал ЕЁ УДАЛИТЬ («paragraphs[:cap] — удалить; тесты, утверждающие, что
такой trim правильный, тоже переписать»).

ASAP-2 (spec контракт (e)/(d)) — новая связка инвариантов:
  * ``limits.max_summary_parts`` — строго Legacy (число Telegram-частей);
    Hybrid его НЕ читает: статья с любым числом абзацев ≤498 публикуется
    ПОЛНОЙ (§17 тест 1);
  * превышение/недобор мягкой цели Hybrid — НЕ ошибка и НЕ обрезка
    (§17 тесты 8–9; WARN-полоса только логируется);
  * жёсткие тех-лимиты §99 (title≤200, абзац≤900, ≤498 блоков, rich≤32000)
    остаются fail-closed — это НЕ trim;
  * trim-костыль (`_trim_document_for_publication`,
    ``SUMMARY_L2_TRIM_ENABLED``) удалён полностью.
Граф-сценарии (ниже) сохранены без изменений (ASAP-2 §19 verification-only,
T-3957).
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from config.settings import settings
from services import summary_memory as sm
from services.summary_l2_writer import (
    MAX_PARAGRAPHS_HARD,
    REASON_TOO_MANY_PARAGRAPHS,
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


# ── Инвариант №1 (замена trim-сценариев 2.58.32): Hybrid не режет и не
#    бракует статью по мягким целям; MAX_SUMMARY_PARTS Hybrid не касается ──

@pytest.mark.asyncio
async def test_l2_article_above_legacy_parts_publishes_complete():
    """§17 тест 1 / инверсия (а): Hybrid-статья из 6 абзацев публикуется
    ПОЛНОЙ: `limits.max_summary_parts` из Hybrid-кода выведен полностью
    (контракт (d)) — резолвера абзацев больше не существует, а Settings —
    frozen dataclass (instance-поля Hybrid-резолверов не читают legacy-ключ)."""
    from services import summary_l2_writer as l2w
    assert not hasattr(l2w, "resolve_l2_max_paragraphs")
    assert not hasattr(l2w, "MAX_PARAGRAPHS_DEFAULT")
    paragraphs = [{"text": f"Абзац номер {i}.", "emphasis": None}
                  for i in range(6)]
    llm = ScriptedLLM(json.dumps(_doc(paragraphs=paragraphs),
                                 ensure_ascii=False))
    result = await run_l2(llm, _package(), slot=_SlotStub())
    assert result.status == STATUS_OK
    assert result.usable
    assert result.document is not None
    assert len(result.document["paragraphs"]) == 6      # полная, без обрезки
    assert result.metrics.get("trimmed_for_publication") is None
    assert "trimmed" not in result.as_metrics()


def test_trim_costume_fully_removed():
    """§16:2536–2545 — trim-костыль УДАЛЁН, а не «оставлен выключенным»:
    функций, маркеров и env-ключа не существует."""
    from services import summary_l2_writer as l2w
    assert not hasattr(l2w, "_trim_document_for_publication")
    assert not hasattr(l2w, "REASON_TRIMMED_FOR_PUBLICATION")
    assert not hasattr(l2w.settings, "SUMMARY_L2_TRIM_ENABLED")
    assert "SUMMARY_L2_TRIM_ENABLED" not in dir(type(l2w.settings))


@pytest.mark.asyncio
async def test_l2_llm_timeout_still_error():
    """Отбраковка реальной ошибки не размывается: LLMError → status=error,
    документа нет, повторного L2-вызова нет (L2-retry не вводится — ADR D3)."""
    class TimeoutLLM:
        calls = 0

        async def generate(self, messages, **kwargs):
            from services.llm_client import LLMError
            TimeoutLLM.calls += 1
            raise LLMError("timeout")

    result = await run_l2(TimeoutLLM(), _package(), slot=_SlotStub())
    assert result.status == "error"
    assert result.invalid_reason == "llm_error"
    assert result.document is None
    assert TimeoutLLM.calls == 1


@pytest.mark.asyncio
async def test_l2_hard_cap_498_still_fail_closed():
    """Жёсткий технический потолок §99 (MAX_PARAGRAPHS_HARD=498) — fail-closed
    и после демонтажа trim (это Telegram blocks limit, не «мягкий кап»)."""
    paragraphs = [{"text": "Х", "emphasis": None}
                  for _ in range(MAX_PARAGRAPHS_HARD + 1)]
    document = {"schema_version": 1, "title": "Т", "paragraphs": paragraphs}
    llm = ScriptedLLM(json.dumps(document, ensure_ascii=False))
    result = await run_l2(llm, _package(), slot=_SlotStub())
    assert result.status != STATUS_OK
    assert result.invalid_reason == REASON_TOO_MANY_PARAGRAPHS
    assert result.document is None


@pytest.mark.asyncio
async def test_l2_full_document_reaches_deliver_stage(caplog, monkeypatch):
    """(б→инверсия) Интеграционный срез: L2-статья с абзацами «больше старой
    легаси-parts» доходит до delivery и публикуется ПОЛНОСТЬЮ — все абзацы
    уходят в plain-чанки, ничего не отброшено."""
    from services.summary_generator import SummaryGenerator

    paragraphs = [{"text": f"Абзац для публикации {i}.", "emphasis": None}
                  for i in range(6)]
    llm = ScriptedLLM(json.dumps(_doc(paragraphs=paragraphs),
                                 ensure_ascii=False))
    result = await run_l2(llm, _package(
        service={"response_mode": "serious", "cover_prompt": ""}),
        slot=_SlotStub())
    assert result.usable
    document = result.document

    generator = SummaryGenerator.__new__(SummaryGenerator)
    sent = []

    async def _send_text(chat_id, text, parse_mode=None):
        sent.append(text)
        return SimpleNamespace(message_id=77)

    generator._send_text_with_retry = _send_text
    monkeypatch.setattr("services.summary_generator.hot.get",
                        lambda k, d=None: d)

    published = await generator._publish_plain_document(
        -1002661910336, document, correlation_id="run-hotfix", ctx=None,
        reason="plain")
    assert published is True
    assert sent, "plain-публикация должна была состояться"
    joined = "".join(sent)
    for i in range(6):
        assert f"Абзац для публикации {i}." in joined  # полнота текста


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
