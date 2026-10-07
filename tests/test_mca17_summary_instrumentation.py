"""MCA-17 (W1-C1, группа «Сводки и память») — инструментирование mca_events.

Покрытие:
  * summary.window: `SUMMARY_WINDOW_BUILD` start + терминальный outcome
    (success / skipped(parse_error|no_new_contribution) / failed(
    model_unavailable)) на `_build_running_summary`;
  * facts.extract: `FACTS_EXTRACT` start + терминал (success со счётчиками /
    skipped: disabled/validation_failed/parse_error/no_new_contribution /
    failed: model_unavailable) на `memorize_facts`;
  * embeddings.index: `EMBED_API_FAILED` — терминал после исчерпания
    ретраев (legacy-цикл) и hard-fail контрол-плейна (serviceability —
    НЕ эмитится, штатный paused-флоу); `EMBED_API_DEFERRED` — notable WARN
    batch breaker'а (факты сохранены text-only);
  * summary.publish: `SUMMARY_PUBLISH` start + терминал (rich / plain-
    фолбэк → fallback_engaged / идемпотентный skip / failed) на
    `_publish_rich_document`;
  * fail-open: `MCA_EVENT_CONTRACT_ENABLED=false` → нет событий, основной
    путь не меняется.

R17: события несут только id/числа/коды/счётчики (без текстов сообщений).
Сеть/провайдеры не вызываются. summary.hybrid НЕ инструментируется заново —
SUMMARY_* стадии уже эмитятся через pipeline_events (см. отчёт W1-C1).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
from services import mca_events as me
from services.database import DatabaseService
from services.llm_client import LLMError
from services.summary_memory import (
    FACT_EXTRACT_PROMPT,
    MemoryManager,
    _FACT_RETRY_SYSTEM_PROMPT,
)

pytestmark = pytest.mark.asyncio

CHAT_ID = -100777


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mca_gates_on(monkeypatch):
    """Контракт/буфер ON, буфер чистый; restore после теста."""
    import services.mca_gates as gates
    monkeypatch.setattr(gates, "event_contract_enabled", lambda: True,
                        raising=False)
    monkeypatch.setattr(gates, "telemetry_store_enabled", lambda: True,
                        raising=False)
    me.reset_pending()
    yield
    me.reset_pending()


@pytest.fixture(autouse=True)
def _reset_memorize_state():
    import services.summary_memory as sm
    sm._memorize_warn_state.clear()
    sm._memorize_lost_totals.clear()
    yield
    sm._memorize_warn_state.clear()
    sm._memorize_lost_totals.clear()


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _events(name: str) -> list[dict]:
    return [dict(e) for e in me._pending if e.get("event_name") == name]


def _start_logged(caplog, name: str) -> bool:
    """start не буферизуется (контракт: буфер — только терминальные);
    start виден в структурном логе `services.mca_events`."""
    return any(
        name in r.getMessage() and "outcome=start" in r.getMessage()
        for r in caplog.records if r.name == "services.mca_events")


def _usage(ev: dict) -> dict:
    raw = ev.get("usage_json")
    return json.loads(raw) if raw else {}


# ── summary.window (`SUMMARY_WINDOW_BUILD`) ─────────────────────────────────


class WindowLLM:
    def __init__(self, summary="свежий конспект", error: Exception | None = None):
        self.summary = summary
        self.error = error

    async def generate(self, messages):
        if self.error is not None:
            raise self.error
        return self.summary

    async def embed(self, texts):        # окно embed не делает
        raise AssertionError("window build must not embed")


def _rows(n=400):
    import time as _t
    now = int(_t.time())
    return [{"timestamp": now - 3600 + i, "text": f"сообщение {i}",
             "author_name": "вася"} for i in range(n)]


async def test_window_success_start_and_terminal(db, caplog):
    """SC: успешная сборка → start (лог) + success (буфер, после UPSERT)."""
    import logging
    memory = MemoryManager(db, WindowLLM("конспект окна"))
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        await memory._build_running_summary(CHAT_ID, _rows())
    assert _start_logged(caplog, "SUMMARY_WINDOW_BUILD")
    evs = _events("SUMMARY_WINDOW_BUILD")
    assert [e["outcome"] for e in evs] == ["success"]
    assert evs[0]["chat_id"] == str(CHAT_ID)   # _ID_FIELDS → строка (R17)
    assert evs[0]["component"] == "summary"
    assert "reason_code" not in evs[0]


async def test_window_llm_error_failed_model_unavailable(db, caplog):
    """SC: LLMError → failed/model_unavailable; исключение пробрасывается
    (fire_and_forget-контракт не меняется)."""
    import logging
    memory = MemoryManager(db, WindowLLM(error=LLMError("503 модель")))
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        with pytest.raises(LLMError):
            await memory._build_running_summary(CHAT_ID, _rows())
    assert _start_logged(caplog, "SUMMARY_WINDOW_BUILD")
    evs = _events("SUMMARY_WINDOW_BUILD")
    assert [e["outcome"] for e in evs] == ["failed"]
    assert evs[0]["reason_code"] == "model_unavailable"
    assert evs[0]["level"] == "WARN"


async def test_window_no_head_skipped(db):
    """SC: всё окно — дословный хвост (head пуст) → skipped/no_new_contribution."""
    memory = MemoryManager(db, WindowLLM("не должен вызываться"))
    # len(rows) ≤ tail (default 30) → head пуст
    await memory._build_running_summary(CHAT_ID, _rows(5))
    evs = _events("SUMMARY_WINDOW_BUILD")
    assert [e["outcome"] for e in evs] == ["skipped"]
    assert evs[0]["reason_code"] == "no_new_contribution"


async def test_window_fail_open_no_events(db, monkeypatch):
    """SC: контракт OFF → 0 событий, сборка работает (fail-open)."""
    import services.mca_gates as gates
    monkeypatch.setattr(gates, "event_contract_enabled", lambda: False,
                        raising=False)
    memory = MemoryManager(db, WindowLLM("конспект"))
    await memory._build_running_summary(CHAT_ID, _rows())
    assert _events("SUMMARY_WINDOW_BUILD") == []
    stored = await db.get_running_summary(CHAT_ID, 0)
    assert stored is not None


# ── facts.extract (`FACTS_EXTRACT`) ─────────────────────────────────────────


class FactsLLM:
    """Канон-JSON на FACT_EXTRACT_PROMPT/ретрай-промпт; опциональная ошибка."""

    def __init__(self, response="[]", error: Exception | None = None):
        self.response = response
        self.error = error
        self.generate_calls = 0

    async def generate(self, messages):
        self.generate_calls += 1
        if self.error is not None:
            raise self.error
        assert messages[0]["content"] in (FACT_EXTRACT_PROMPT,
                                          _FACT_RETRY_SYSTEM_PROMPT)
        return self.response

    async def embed(self, texts):
        raise AssertionError("network embed must not be called")


def _facts_json(count=2):
    return json.dumps([
        {"subject": f"s{i}", "predicate": "p", "object": f"o{i}"}
        for i in range(count)], ensure_ascii=False)


async def test_facts_success_start_and_terminal(db, caplog):
    """SC: факты сохранены → start (лог) + success (буфер, счётчик saved)."""
    import logging
    memory = MemoryManager(db, FactsLLM(_facts_json(2)))
    memory._vec_available = False
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        await memory.memorize_facts(CHAT_ID, "вася любит кофе", "chat_history")
    assert _start_logged(caplog, "FACTS_EXTRACT")
    evs = _events("FACTS_EXTRACT")
    assert [e["outcome"] for e in evs] == ["success"]
    assert _usage(evs[0])["saved"] == 2
    assert evs[0]["component"] == "facts"


async def test_facts_gate_disabled_skipped(db, monkeypatch):
    """SC: GRAPH_RAG_ENABLED OFF → одиночное skipped/disabled (без start)."""
    import services.summary_memory as sm
    llm = FactsLLM(_facts_json())
    memory = MemoryManager(db, llm)
    memory._vec_available = False
    mod = replace(settings, GRAPH_RAG_ENABLED=False)
    with patch.object(sm, "settings", mod):
        await memory.memorize_facts(CHAT_ID, "текст", "search_fact")
    evs = _events("FACTS_EXTRACT")
    assert [e["outcome"] for e in evs] == ["skipped"]
    assert evs[0]["reason_code"] == "disabled"
    assert llm.generate_calls == 0


async def test_facts_unknown_source_skipped_validation(db):
    """SC: неизвестный source_type → skipped/validation_failed (без start)."""
    memory = MemoryManager(db, FactsLLM(_facts_json()))
    memory._vec_available = False
    await memory.memorize_facts(CHAT_ID, "текст", "banana_source")
    evs = _events("FACTS_EXTRACT")
    assert [e["outcome"] for e in evs] == ["skipped"]
    assert evs[0]["reason_code"] == "validation_failed"


async def test_facts_parse_error_skipped(db):
    """SC: не-JSON ответ (и ретрай тоже) → skipped/parse_error."""
    memory = MemoryManager(db, FactsLLM("совсем не JSON {"))
    memory._vec_available = False
    await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    evs = _events("FACTS_EXTRACT")
    assert [e["outcome"] for e in evs] == ["skipped"]
    assert evs[0]["reason_code"] == "parse_error"


async def test_facts_empty_valid_skipped(db):
    """SC: валидный [] → skipped/no_new_contribution."""
    memory = MemoryManager(db, FactsLLM("[]"))
    memory._vec_available = False
    await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    evs = _events("FACTS_EXTRACT")
    assert [e["outcome"] for e in evs] == ["skipped"]
    assert evs[0]["reason_code"] == "no_new_contribution"


async def test_facts_llm_down_failed_model_unavailable(db, monkeypatch, caplog):
    """SC: модель недоступна (extract+retry LLMError) → честный failed/
    model_unavailable, не parse_error."""
    import logging
    import services.summary_memory as sm
    mod = replace(settings, GRAPH_MEMORIZE_MAX_BATCH_RETRIES=0,
                  GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF=0.0)
    memory = MemoryManager(db, FactsLLM(error=LLMError("timeout")))
    memory._vec_available = False
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        with patch.object(sm, "settings", mod):
            await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    assert _start_logged(caplog, "FACTS_EXTRACT")
    evs = _events("FACTS_EXTRACT")
    assert [e["outcome"] for e in evs] == ["failed"]
    assert evs[0]["reason_code"] == "model_unavailable"
    assert evs[0]["level"] == "WARN"


# ── embeddings.index (`EMBED_API_FAILED` / `EMBED_API_DEFERRED`) ────────────


class EmbedFailLLM:
    async def generate(self, messages):
        raise AssertionError("not used")

    async def embed(self, texts):
        raise LLMError("все ключи исчерпаны")


def _memory_no_db():
    import services.summary_memory as sm
    mm = MemoryManager(None, EmbedFailLLM())
    mm._vec_dim = 8
    return mm


def _patch_control_plane(monkeypatch, value: bool) -> None:
    """EMBED_CONTROL_PLANE_ENABLED — ClassVar на Settings: патч класса
    (инстанс-тень для этого поля не создаётся)."""
    monkeypatch.setattr(type(settings), "EMBED_CONTROL_PLANE_ENABLED", value,
                        raising=False)


async def test_embed_api_legacy_terminal_failure(db, monkeypatch):
    """SC: legacy-цикл, все попытки исчерпаны → EMBED_API_FAILED/failed
    (attempt=3, reason provider_unavailable), исключение пробрасывается."""
    import services.summary_memory as sm
    _patch_control_plane(monkeypatch, False)
    monkeypatch.setattr(sm, "_EMBED_RETRY_BACKOFF", 0.0, raising=False)
    mm = _memory_no_db()
    with pytest.raises(LLMError):
        await mm._embed_api(["a", "b"])
    evs = _events("EMBED_API_FAILED")
    assert len(evs) == 1
    ev = evs[0]
    assert ev["outcome"] == "failed"
    assert ev["level"] == "ERROR"
    assert ev["attempt"] == sm._EMBED_RETRY_ATTEMPTS
    assert ev["reason_code"] == "provider_unavailable"
    assert ev["component"] == "embeddings"


async def test_embed_api_control_plane_hard_fail_emits(db, monkeypatch):
    """SC: контрол-плейн ON, hard-fail (не serviceability) → событие + re-raise."""
    import services.embedding_control_plane as ecp
    _patch_control_plane(monkeypatch, True)
    monkeypatch.setattr(ecp, "control_plane_enabled", lambda: True,
                        raising=False)

    async def hard_fail(llm, texts, *, priority=None):
        raise LLMError("adapter down")

    monkeypatch.setattr(ecp, "execute_embed", hard_fail)
    mm = _memory_no_db()
    with pytest.raises(LLMError):
        await mm._embed_api(["a"])
    evs = _events("EMBED_API_FAILED")
    assert len(evs) == 1
    assert evs[0]["outcome"] == "failed"
    assert evs[0]["reason_code"] == "provider_unavailable"


async def test_embed_api_control_plane_serviceability_silent(db, monkeypatch):
    """SC: CoolingDown — штатный paused-флоу контрол-плейна → БЕЗ per-call
    события (не спамим), исключение пробрасывается как раньше."""
    import services.embedding_control_plane as ecp
    _patch_control_plane(monkeypatch, True)
    monkeypatch.setattr(ecp, "control_plane_enabled", lambda: True,
                        raising=False)

    async def cooling(llm, texts, *, priority=None):
        raise ecp.EmbeddingGroupCoolingDown(
            group_id="g1", next_allowed_at=int(0))

    monkeypatch.setattr(ecp, "execute_embed", cooling)
    mm = _memory_no_db()
    with pytest.raises(ecp.EmbeddingGroupCoolingDown):
        await mm._embed_api(["a"])
    assert _events("EMBED_API_FAILED") == []


async def test_embed_deferred_batch_breaker(db, monkeypatch):
    """SC: batch breaker (cooldown на первом факте) → факты text-only +
    ровно одно notable EMBED_API_DEFERRED/embed_deferred на batch."""
    import services.embedding_control_plane as ecp
    import services.summary_memory as sm
    sm._memorize_warn_state.clear()
    llm = FactsLLM(_facts_json(3))
    memory = MemoryManager(db, llm)
    memory._vec_available = True
    memory._vec_int8 = False

    calls = {"n": 0}

    async def cooling_embed(texts, *, priority=None):
        calls["n"] += 1
        raise ecp.EmbeddingGroupCoolingDown(
            group_id="g1", next_allowed_at=int(0))

    monkeypatch.setattr(memory, "_embed", cooling_embed)
    await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    evs = _events("EMBED_API_DEFERRED")
    assert len(evs) == 1
    assert evs[0]["outcome"] == "skipped"
    assert evs[0]["reason_code"] == "embed_deferred"
    assert _usage(evs[0])["facts_text_only"] == 3
    assert calls["n"] == 1                      # ≤1 embed-попытка на batch


# ── summary.publish (`SUMMARY_PUBLISH`) ─────────────────────────────────────

PUB_CHAT = -100123
DOC = {"schema_version": 1, "title": "Событие",
       "paragraphs": [{"text": "Первый абзац.", "emphasis": None},
                      {"text": "Второй абзац.", "emphasis": None}]}


class _PublishRec:
    def __init__(self):
        self.rich = []
        self.plain = []

    def install(self, monkeypatch, tmp_path, *, base_ok=True, rich_ok=True):
        from services import summary_generator as sg
        base = tmp_path / "base.jpg"
        base.write_bytes(b"BASE")

        async def _gen(prompt, *, chat_id=None, correlation_id=None):
            return (str(base), "ok") if base_ok else (None, "no_key")

        async def _rich(bot, chat_id, text, *, media=None, cover_id=None,
                        content_format="auto", **kw):
            if not rich_ok:
                raise RuntimeError("sendRichMessage down")
            self.rich.append({"text": text, "media": media})
            return MagicMock(message_id=555)

        async def _text(bot, chat_id, text, **kw):
            self.plain.append(text)
            return MagicMock(message_id=101)

        monkeypatch.setattr(sg, "generate_image_verbose", _gen)
        monkeypatch.setattr(sg, "build_cover_media",
                            lambda path, **kw: {"path": path})
        monkeypatch.setattr(sg, "send_rich_message", _rich)
        monkeypatch.setattr(sg, "send_text", _text)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)


def _pub_gen(monkeypatch):
    from services.summary_generator import SummaryGenerator
    gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    gen._resolve_cover_style_text = AsyncMock(return_value="style")
    gen._maybe_apply_cover_style = AsyncMock(return_value=None)
    return gen


async def test_publish_rich_success(monkeypatch, tmp_path, caplog):
    """SC: rich доставлен → start (лог) + success (буфер: status=rich,
    message_id)."""
    import logging
    _PublishRec().install(monkeypatch, tmp_path)
    gen = _pub_gen(monkeypatch)
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        published = await gen._publish_rich_document(PUB_CHAT, DOC, "a lone cat")
    assert published is True
    assert _start_logged(caplog, "SUMMARY_PUBLISH")
    evs = _events("SUMMARY_PUBLISH")
    assert [e["outcome"] for e in evs] == ["success"]
    assert evs[0]["status"] == "rich"
    assert evs[0]["message_id"] == "555"      # _ID_FIELDS → строка (R17)
    assert "reason_code" not in evs[0]


async def test_publish_cover_unavailable_fallback_engaged(monkeypatch, tmp_path):
    """SC: обложка недоступна → degraded-фолбэк доставил сводку →
    success + fallback_engaged (fallback_reason в usage_json)."""
    _PublishRec().install(monkeypatch, tmp_path, base_ok=False)
    gen = _pub_gen(monkeypatch)
    published = await gen._publish_rich_document(PUB_CHAT, DOC, "a lone cat")
    assert published is True
    evs = _events("SUMMARY_PUBLISH")
    assert [e["outcome"] for e in evs] == ["success"]
    assert evs[0]["reason_code"] == "fallback_engaged"
    assert _usage(evs[0])["fallback_reason"] == "cover_unavailable"
    assert evs[0]["status"] == "degraded"


async def test_publish_rich_error_plain_fallback(monkeypatch, tmp_path):
    """SC: rich-канал упал → plain доставил → success + fallback_engaged
    (status=plain)."""
    _PublishRec().install(monkeypatch, tmp_path, rich_ok=False)
    gen = _pub_gen(monkeypatch)
    published = await gen._publish_rich_document(PUB_CHAT, DOC, "a lone cat")
    assert published is True
    evs = _events("SUMMARY_PUBLISH")
    assert [e["outcome"] for e in evs] == ["success"]
    assert evs[0]["reason_code"] == "fallback_engaged"
    assert evs[0]["status"] == "plain"
    assert _usage(evs[0])["fallback_reason"] == "rich_error"


async def test_publish_gate_skip_idempotent(monkeypatch, tmp_path):
    """SC: publication gate skip (уже опубликовано) → skipped/
    action_idempotent_replay."""
    _PublishRec().install(monkeypatch, tmp_path)
    gen = _pub_gen(monkeypatch)
    gen._publication_gate = AsyncMock(return_value="skip")
    published = await gen._publish_rich_document(PUB_CHAT, DOC, "a lone cat")
    assert published is True
    evs = _events("SUMMARY_PUBLISH")
    assert [e["outcome"] for e in evs] == ["skipped"]
    assert evs[0]["reason_code"] == "action_idempotent_replay"


async def test_publish_fail_open_no_events(monkeypatch, tmp_path):
    """SC: контракт OFF → публикация работает, 0 событий (fail-open)."""
    import services.mca_gates as gates
    monkeypatch.setattr(gates, "event_contract_enabled", lambda: False,
                        raising=False)
    _PublishRec().install(monkeypatch, tmp_path)
    gen = _pub_gen(monkeypatch)
    published = await gen._publish_rich_document(PUB_CHAT, DOC, "a lone cat")
    assert published is True
    assert _events("SUMMARY_PUBLISH") == []
