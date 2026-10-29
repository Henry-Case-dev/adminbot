# -*- coding: utf-8 -*-
"""EVOL-013 — общее качество статусов и телеметрии (не-embedding часть).

Контракт (ТЗ EVOL-013, строки 163-165 plans/current_task.md + revalidation):
  * повторяющиеся WARN по одной установленной проблеме дедуплицируются
    (повтор в окне — INFO со счётчиком; повторяемые ошибки НЕ скрываются);
  * восстановление не прячется: после успеха следующая проблема — снова WARN;
  * причина различает класс исключения: NameError (детерминированная ошибка
    кода) НЕ маскируется под transport/timeout; timeout — отдельный код;
  * type-name-only логи получают ограниченное R17-safe сообщение.
"""
from __future__ import annotations

import asyncio
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
from services.mca_vision import validate_image_bytes  # noqa: E402

CHAT = -1002013


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


class _ContentTransport:
    def __init__(self, content: str, repeat: int = 10**9):
        self.content = content
        self.repeat = repeat
        self.calls = 0

    async def __call__(self, url, *, payload=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls > self.repeat:
            self.content = json.dumps({"ocr_blocks": []})
        return 200, {"choices": [{"message": {"content": self.content}}],
                     "usage": {}}


class _ExcTransport:
    def __init__(self, exc: BaseException):
        self.exc = exc

    async def __call__(self, url, *, payload=None, headers=None, timeout=None):
        raise self.exc


@pytest.fixture()
def vision_env(monkeypatch):
    monkeypatch.setattr(mca_vision, "resolve_effective_state", _state_ok)
    monkeypatch.setattr(mca_vision, "route_config_problem", lambda route: "")
    monkeypatch.setattr(mca_vision, "api_key_for", lambda route: "test-key")
    yield


@pytest.fixture()
def events(monkeypatch):
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


# ═════════ 1. Дедуп повторных WARN + re-notify после восстановления ═════════

@pytest.mark.asyncio
async def test_repeat_same_error_warn_suppressed(vision_env, events):
    img = validate_image_bytes(_png())
    bad = _ContentTransport("мусор вместо json")

    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=bad)
    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=bad)
    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=bad)

    evs = _adapt_events(events)
    assert [e["level"] for e in evs] == ["WARN", "INFO", "INFO"]
    assert "repeats" not in evs[0]["error_json"]
    assert evs[1]["error_json"]["repeats"] == 1
    assert evs[2]["error_json"]["repeats"] == 2
    # исходы не меняются — ошибка по-прежнему видна как failed
    assert all(e["outcome"] == "failed" and e["reason_code"] == "parse_error"
               for e in evs)


@pytest.mark.asyncio
async def test_recovery_renotifies_and_new_distinct_error_warns(
        vision_env, events):
    img = validate_image_bytes(_png())
    bad = _ContentTransport("мусор вместо json")
    good = _ContentTransport(json.dumps({"ocr_blocks": []}))

    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=bad)
    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=bad)
    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=good)
    await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=bad)

    evs = _adapt_events(events)
    assert [e["level"] for e in evs] == ["WARN", "INFO", "INFO", "WARN"]
    assert evs[2]["outcome"] == "success"      # восстановление видимо
    assert "repeats" not in evs[3]["error_json"]  # re-notify, а не подавление


@pytest.mark.asyncio
async def test_new_distinct_error_not_suppressed_by_old(vision_env, events):
    img = validate_image_bytes(_png())
    await mca_vision.analyze_adaptive(
        img, chat_id=CHAT, transport=_ContentTransport("мусор вместо json"))
    import httpx
    from services.mca_vision import VisionError
    with pytest.raises(VisionError):
        await mca_vision.analyze_adaptive(
            img, chat_id=CHAT,
            transport=_ExcTransport(httpx.ConnectError("refused")))
    evs = _adapt_events(events)
    assert evs[0]["level"] == "WARN"
    assert evs[1]["level"] == "WARN"           # новая отличная проблема
    assert evs[1]["reason_code"] == "vision_unavailable"


# ═════════ 2. Честная классификация: NameError ≠ transport ≠ timeout ════════

@pytest.mark.asyncio
async def test_nameerror_not_masked_as_transport_or_timeout(
        vision_env, events):
    img = validate_image_bytes(_png())
    with pytest.raises(NameError):
        await mca_vision.analyze_adaptive(
            img, chat_id=CHAT, transport=_ExcTransport(NameError("boom")))
    evs = _adapt_events(events)
    assert evs[0]["outcome"] == "failed"
    # выдуманный код не ставится: детерминированная ошибка кода остаётся
    # честным «класс + сообщение», без fake vision_unavailable/timeout
    assert not evs[0].get("reason_code")
    assert evs[0]["error_json"]["error"] == "NameError"
    assert "NameError: boom" in evs[0]["error_json"]["detail"]


@pytest.mark.asyncio
async def test_timeout_distinct_from_nameerror(vision_env, events):
    """Бюджетный таймаут (wait_for) — отдельный код `timeout`, не «неизвестный
    transport» и не «не JSON»; транспортный таймаут провайдера даёт свой
    честный `vision_unavailable`+detail (см. test_evol011)."""

    class _Slow(_ExcTransport):
        async def __call__(self, url, **kwargs):
            await asyncio.sleep(1.0)
            raise AssertionError("не должен дождаться")

    img = validate_image_bytes(_png())
    with pytest.raises(asyncio.TimeoutError):
        await mca_vision.analyze_adaptive(
            img, chat_id=CHAT, transport=_Slow(None), budget_seconds=0.05)
    evs = _adapt_events(events)
    assert evs[0]["outcome"] == "failed"
    assert evs[0]["reason_code"] == "timeout"


# ═════════ 3. Type-name-only логи: класс + R17-safe сообщение ═══════════════

@pytest.mark.asyncio
async def test_vision_task_failure_log_includes_message(caplog):
    async def _boom():
        raise NameError("bg oops")

    task = asyncio.ensure_future(_boom())
    with pytest.raises(NameError):
        await task
    mca_vision.VisionMediaWorker._log_task_failure(
        task, "[vision] test task failed")
    warnings = [r for r in caplog.records
                if "test task failed" in r.getMessage()]
    assert warnings, "сбой фоновой задачи должен попадать в WARN"
    line = warnings[-1].getMessage()
    assert "NameError" in line and "bg oops" in line


def test_exc_brief_helpers_bounded_and_single_line():
    from services.direct_chat_service import _exc_brief as dcs_brief
    from services.direct_execution import _exc_brief as exec_brief
    for brief in (dcs_brief, exec_brief):
        text = brief(ValueError("x\ny " * 200))
        assert "\n" not in text and text.startswith("ValueError: ")
        assert len(text) <= 220
        assert brief(ValueError("")) == "ValueError"


# ═════════ 4. llm_client: транспортная причина — machine-readable ═══════════

def test_llm_error_cause_class_default_empty():
    from services.llm_client import LLMError, LLMTransportError
    assert LLMError("x").cause_class == ""
    err = LLMTransportError("LLM transport error", cause_class="ConnectError")
    assert err.cause_class == "ConnectError"


@pytest.mark.asyncio
async def test_llm_transport_error_carries_cause_class(monkeypatch):
    import httpx
    from services.llm_client import LLMClient, LLMTimeoutError, \
        LLMTransportError

    client = LLMClient("http://127.0.0.1:9", "key", "chat-model",
                       "embed-model")
    client.backoff_base = 0
    client._max_retries = 0
    monkeypatch.setattr(client, "_get_client", lambda *a, **kw: SimpleNamespace(
        post=_raise(httpx.ConnectError("boom"))))
    with pytest.raises(LLMTransportError) as ei:
        await client._post("/chat/completions", {"model": "chat-model"})
    assert ei.value.cause_class == "ConnectError"

    monkeypatch.setattr(client, "_get_client",
                        lambda *a, **kw: SimpleNamespace(
                            post=_raise(httpx.ReadTimeout("t"))))
    with pytest.raises(LLMTimeoutError) as ti:
        await client._post("/chat/completions", {"model": "chat-model"})
    assert ti.value.cause_class == "ReadTimeout"


def _raise(exc):
    async def _post(url, **kwargs):
        raise exc
    return _post
