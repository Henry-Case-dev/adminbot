# -*- coding: utf-8 -*-
"""EVOL-011 — `vision_adapt failed` с пустой причиной: честная телеметрия.

Контракт (ТЗ EVOL-011, строки 143-149 plans/current_task.md + revalidation):
  * HTTP 200 + не-JSON payload → outcome=failed с reason_code=parse_error
    в событии (пустой error больше не теряет причину);
  * пустой content — ОТДЕЛЬНАЯ причина (empty_content), не «не JSON»;
  * timeout / provider-http / прочие технические отказы различимы по
    существующему словарю кодов, без выдумывания причин;
  * готовые исходы (ready/no_text) остаются success/INFO (контракт не менял);
  * отмена — outcome=cancelled (ожидаемый промежуточный исход);
  * поведение распознавания (статусы/фолбэк/pending→ready) не меняется —
    тесты правят только наблюдаемость.

TEST-LIFECYCLE: CONTRACT owner=EVOL-011
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import mca_events                    # noqa: E402
from services import mca_vision                    # noqa: E402
from services.mca_vision import (VisionAnalysis,   # noqa: E402
                                 VisionError, parse_analysis_payload,
                                 validate_image_bytes)

CHAT = -1002011


# ── Фикстуры без PIL: минимальный валидный PNG (сниффер читает IHDR) ────────

def _png(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


async def _state_ok(chat_id=None):
    return SimpleNamespace(effective_enabled=True, capability="ok",
                           reason="vision_ok", visible_reason="ok")


class _StaticTransport:
    """Всегда HTTP 200 с заданным content в choices[0].message.content."""

    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    async def __call__(self, url, *, payload=None, headers=None, timeout=None):
        self.calls += 1
        body = {"choices": [{"message": {"content": self.content}}],
                "usage": {}}
        return 200, body


class _FailingTransport:
    """Поднять исключение / отдать HTTP-статус (по сценарию теста)."""

    def __init__(self, exc: BaseException | None = None, status: int = 0):
        self.exc = exc
        self.status = status
        self.calls = 0

    async def __call__(self, url, *, payload=None, headers=None, timeout=None):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.status, {"error": {"message": "no"}}


@pytest.fixture()
def vision_env(monkeypatch):
    monkeypatch.setattr(mca_vision, "resolve_effective_state", _state_ok)
    monkeypatch.setattr(mca_vision, "route_config_problem", lambda route: "")
    monkeypatch.setattr(mca_vision, "api_key_for", lambda route: "test-key")
    yield


@pytest.fixture()
def events(monkeypatch):
    """Перехват emit_mca_event + чистое состояние дедупа WARN."""
    mca_vision._adapt_warn_state.clear()
    seen: list[dict] = []

    def _sink(name, **fields):
        seen.append({"event": name, **fields})
        return None

    monkeypatch.setattr(mca_events, "emit_mca_event", _sink)
    yield seen
    mca_vision._adapt_warn_state.clear()


def _adapt_events(seen: list[dict]) -> list[dict]:
    return [e for e in seen if e["event"] == "vision_adapt"]


# ═════════ 1. Парсер: non-JSON vs empty_content vs готовые статусы ══════════

def test_parser_non_json_is_failed_parse_error():
    out = parse_analysis_payload("это вообще не json {")
    assert out.status == "failed"
    assert out.error_reason == "parse_error"


def test_parser_empty_content_is_distinct_reason():
    out = parse_analysis_payload("")
    assert out.status == "failed"
    assert out.error_reason == "empty_content"
    assert parse_analysis_payload("   \n ").error_reason == "empty_content"


def test_parser_success_statuses_unchanged():
    ok = parse_analysis_payload(json.dumps(
        {"ocr_blocks": [{"text": "текст"}], "visual_description": "desc"}))
    assert ok.status == "ready" and ok.error_reason == ""
    no_text = parse_analysis_payload(json.dumps({"ocr_blocks": []}))
    assert no_text.status == "no_text" and no_text.error_reason == ""


def test_empty_content_in_reason_code_whitelist():
    """Код обязан проходить реальный контракт событий (иначе whitelist его
    молча выбрасывает — повтор дефекта «reason_code потерян»)."""
    assert "empty_content" in mca_events.REASON_CODES
    assert "parse_error" in mca_events.REASON_CODES
    for code in ("empty_content", "parse_error", "timeout"):
        ev = mca_events.build_event("vision_adapt", outcome="failed",
                                    level="WARN", reason_code=code)
        assert ev is not None and ev["reason_code"] == code


# ═════════ 2. Событие vision_adapt: reason_code присутствует ════════════════

@pytest.mark.asyncio
async def test_parse_error_payload_emits_failed_with_reason_code(
        vision_env, events):
    img = validate_image_bytes(_png())
    t = _StaticTransport("модель ответила prose вместо JSON")
    out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
    assert out.status == "failed" and out.error_reason == "parse_error"
    evs = _adapt_events(events)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["outcome"] == "failed"
    assert ev["level"] == "WARN"
    assert ev["reason_code"] == "parse_error"
    ej = ev["error_json"]
    assert ej["error"] == ""          # исключения не было — честно
    assert ej["strategy"] and "reason" in ej and "calls" in ej


@pytest.mark.asyncio
async def test_empty_content_vs_non_json_vs_timeout_distinct(
        vision_env, events):
    img = validate_image_bytes(_png())

    await mca_vision.analyze_adaptive(
        img, chat_id=CHAT, transport=_StaticTransport(""))
    await mca_vision.analyze_adaptive(
        img, chat_id=CHAT, transport=_StaticTransport("не json"))
    import httpx
    with pytest.raises(VisionError):
        await mca_vision.analyze_adaptive(
            img, chat_id=CHAT,
            transport=_FailingTransport(exc=httpx.ReadTimeout("slow")))

    evs = _adapt_events(events)
    codes = [e.get("reason_code") for e in evs]
    assert codes[0] == "empty_content"
    assert codes[1] == "parse_error"
    assert codes[2] == "vision_unavailable"     # транспортный таймаут → код
    details = [e["error_json"].get("detail", "") for e in evs]
    assert "timeout" in details[2]              # …с честным классом причины
    assert len(set(c for c in codes if c)) == 3  # все три различимы


@pytest.mark.asyncio
async def test_budget_timeout_reason_code_timeout(vision_env, events):
    """Исчерпание бюджета адаптивного контура → reason_code=timeout."""

    class _Slow(_StaticTransport):
        async def __call__(self, url, **kw):
            await asyncio.sleep(1.0)
            return 200, {}

    img = validate_image_bytes(_png())
    with pytest.raises(asyncio.TimeoutError):
        await mca_vision.analyze_adaptive(img, chat_id=CHAT,
                                          transport=_Slow(""),
                                          budget_seconds=0.05)
    evs = _adapt_events(events)
    assert len(evs) == 1
    assert evs[0]["outcome"] == "failed"
    assert evs[0]["reason_code"] == "timeout"


@pytest.mark.asyncio
async def test_provider_http_error_distinct(vision_env, events):
    img = validate_image_bytes(_png())
    with pytest.raises(VisionError) as ei:
        await mca_vision.analyze_adaptive(
            img, chat_id=CHAT, transport=_FailingTransport(status=401))
    assert ei.value.reason == "vision_unavailable"
    evs = _adapt_events(events)
    assert evs[0]["outcome"] == "failed"
    assert evs[0]["reason_code"] == "vision_unavailable"
    assert "http_401" in evs[0]["error_json"].get("detail", "")


@pytest.mark.asyncio
async def test_success_paths_unchanged(vision_env, events):
    img = validate_image_bytes(_png())
    good = json.dumps({"ocr_blocks": [{"text": "строка"}],
                       "visual_description": "описание"}, ensure_ascii=False)
    out = await mca_vision.analyze_adaptive(
        img, chat_id=CHAT, transport=_StaticTransport(good))
    assert out.status == "ready"
    evs = _adapt_events(events)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["outcome"] == "success"
    assert ev["level"] == "INFO"
    assert not ev.get("reason_code")
    assert "repeats" not in ev["error_json"]


@pytest.mark.asyncio
async def test_no_text_is_success(vision_env, events):
    img = validate_image_bytes(_png())
    out = await mca_vision.analyze_adaptive(
        img, chat_id=CHAT,
        transport=_StaticTransport(json.dumps({"ocr_blocks": []})))
    assert out.status == "no_text"
    evs = _adapt_events(events)
    assert evs[0]["outcome"] == "success" and evs[0]["level"] == "INFO"


@pytest.mark.asyncio
async def test_cancelled_is_not_failed(vision_env, events):
    img = validate_image_bytes(_png())
    with pytest.raises(asyncio.CancelledError):
        await mca_vision.analyze_adaptive(
            img, chat_id=CHAT,
            transport=_FailingTransport(exc=asyncio.CancelledError()))
    evs = _adapt_events(events)
    assert len(evs) == 1
    assert evs[0]["outcome"] == "cancelled"
    assert evs[0]["level"] == "INFO"


@pytest.mark.asyncio
async def test_no_second_pipeline_no_extra_calls(vision_env, events):
    """Анализатор — один; событие ровно на вызов (без дублей телеметрии)."""
    img = validate_image_bytes(_png())
    t = _StaticTransport(json.dumps({"ocr_blocks": []}))
    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
    assert t.calls == 1
    assert len(_adapt_events(events)) == 1


# ═════════ 3. Классификация исключений (EVOL-013, общая точка) ══════════════

def test_classify_vision_error_uses_existing_reason():
    code, cls = mca_vision._classify_adapt_error(
        VisionError("vision_rate_limited", "http_429"))
    assert (code, cls) == ("vision_rate_limited", "VisionError")


def test_classify_timeout_and_unknown_distinct():
    code, cls = mca_vision._classify_adapt_error(asyncio.TimeoutError())
    assert (code, cls) == ("timeout", "TimeoutError")
    code2, cls2 = mca_vision._classify_adapt_error(NameError("x"))
    assert code2 == "" and cls2 == "NameError"   # выдуманный код не ставится


def test_safe_exc_text_bounded_single_line():
    text = mca_vision._safe_exc_text(ValueError("a\nb " * 100))
    assert "\n" not in text
    assert text.startswith("ValueError: ")
    assert len(text) <= 320
