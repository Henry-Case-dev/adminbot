"""Раунд 10.24 (F12, ADR-1024-4) — универсальный payload обложек + probe.

Покрытие (T-2280…T-2285):
  * (a) тело POST строго ``{prompt, model, n:1}`` — без ``size``/``quality``/
    ``response_format`` (модели ``gptimage``/``ideogram``/``flux`` — любой
    OpenAI-совместимый провайдер);
  * (b) ``flux``/``gptimage`` генерируют одинаково универсальным путём;
  * (c) ответ ``data[0].url`` скачивается, ``data[0].b64_json`` декодируется;
  * (d) стиль приоритетнее visual (режется visual); лог ``style_present``;
  * (e) ``probe()`` — успех/ошибка, ``body_excerpt`` безопасен (R17);
  * (f) причина отказа провайдера реально логируется, а не только
    «image unavailable» (F2/ADR-1024-1);
  * (g) kill-switch ``SUMMARY_COVER_MODEL_COMPAT_ENABLED=False`` → прежнее
    тело (byte-identical).

Сеть не используется: ``_http_request`` подменяется заглушкой; ключ нигде
не печатается (R17).
"""
from __future__ import annotations

import base64
import json
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock

from config.settings import Settings
from services import image_generation as ig
from services import summary_generator as sg
from services.summary_generator import (
    SummaryGenerator,
    compose_cover_image_prompt,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"",
                 text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


def _patch_cfg(monkeypatch, *, model="flux", api_key="", get_mode=False):
    """hot.get: прозрачный резолв (default); ключ/модель — по параметрам."""
    def fake_get(key, default=None):
        if key == ig.KEY_API_KEY:
            return api_key
        if key == ig.KEY_MODEL:
            return model
        if key == ig.KEY_GET_MODE:
            return get_mode
        return default

    monkeypatch.setattr(ig.hot, "get", fake_get)


# ── (a)/(g) payload ─────────────────────────────────────────────────────────

class TestUniversalPayload:
    def test_build_body_minimal(self, monkeypatch):
        monkeypatch.setattr(Settings, "SUMMARY_COVER_MODEL_COMPAT_ENABLED", True)
        body = ig._build_post_body("a cat", "gptimage")
        assert body == {"prompt": "a cat", "model": "gptimage", "n": 1}

    def test_build_body_kill_switch_legacy(self, monkeypatch):
        monkeypatch.setattr(Settings, "SUMMARY_COVER_MODEL_COMPAT_ENABLED", False)
        body = ig._build_post_body("a cat", "flux")
        assert body["size"] == ig._IMAGE_SIZE
        assert body["response_format"] == "url"
        assert body["n"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", ["gptimage", "ideogram", "flux"])
    async def test_post_has_no_incompatible_fields(self, monkeypatch, model):
        captured = {}

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            if method == "POST":
                captured["body"] = json_body
                return FakeResponse(200, {"data": [
                    {"url": "https://cdn.example/a.jpg"}]})
            return FakeResponse(200, content=b"bytes")

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        _patch_cfg(monkeypatch, model=model)
        res = await ig.generate("обложка саммари", chat_id=1)
        assert res.ok
        body = captured["body"]
        assert body == {"prompt": "обложка саммари", "model": model, "n": 1}
        for bad in ("size", "quality", "response_format"):
            assert bad not in body

    @pytest.mark.asyncio
    async def test_kill_switch_off_sends_legacy_body(self, monkeypatch):
        """(g) OFF → прежнее тело (откат), byte-identical."""
        monkeypatch.setattr(Settings, "SUMMARY_COVER_MODEL_COMPAT_ENABLED", False)
        captured = {}

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            if method == "POST":
                captured["body"] = json_body
                return FakeResponse(200, {"data": [
                    {"url": "https://cdn.example/a.jpg"}]})
            return FakeResponse(200, content=b"bytes")

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        _patch_cfg(monkeypatch, model="flux")
        await ig.generate("кот", chat_id=1)
        assert captured["body"]["size"] == ig._IMAGE_SIZE
        assert captured["body"]["response_format"] == "url"


# ── (b)/(c) обе формы ответа ────────────────────────────────────────────────

class TestResponseForms:
    @pytest.mark.asyncio
    async def test_url_downloaded(self, monkeypatch):
        calls = []

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            calls.append(method)
            if method == "POST":
                return FakeResponse(200, {"data": [
                    {"url": "https://cdn.example/a.jpg"}]})
            return FakeResponse(200, content=b"\xff\xd8jpeg")

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        _patch_cfg(monkeypatch)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok and res.content == b"\xff\xd8jpeg"
        assert calls == ["POST", "GET"]

    @pytest.mark.asyncio
    async def test_b64_json_decoded(self, monkeypatch):
        payload = base64.b64encode(b"img-bytes").decode()

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            assert method == "POST"          # download не нужен
            return FakeResponse(200, {"data": [{"b64_json": payload}]})

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        _patch_cfg(monkeypatch)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok and res.content == b"img-bytes"

    @pytest.mark.asyncio
    async def test_no_image_reason(self, monkeypatch):
        async def fake(*a, **kw):
            return FakeResponse(200, {"data": [{}]})

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        _patch_cfg(monkeypatch)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok is False and res.reason == "no_url"


# ── (e) probe ───────────────────────────────────────────────────────────────

class TestProbe:
    @pytest.mark.asyncio
    async def test_probe_ok(self, monkeypatch):
        calls = []

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            calls.append(json_body)
            return FakeResponse(200, {"data": [{"b64_json": "aGk="}]},
                                text="")

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_cfg(monkeypatch, model="gptimage")
        result = await ig.probe()
        assert result.ok is True
        assert result.status_code == 200
        assert result.reason == "ok"
        assert result.model == "gptimage"
        assert result.mode == "post"
        # Тело — универсальное (никаких size/response_format).
        assert calls[0] == {"prompt": ig.PROBE_PROMPT, "model": "gptimage",
                            "n": 1}

    @pytest.mark.asyncio
    async def test_probe_error_is_safe(self, monkeypatch):
        """400 → ok=false + сырой усечённый body_excerpt; ключ не утекает."""
        secret = "sk-SUPER-SECRET-1234567890"

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            return FakeResponse(
                400, None,
                text=json.dumps({"error": f"unknown field size; key {secret}"}))

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_cfg(monkeypatch, model="gptimage", api_key=secret)
        result = await ig.probe()
        assert result.ok is False
        assert result.status_code == 400
        assert result.reason == "bad_request"
        assert "unknown field size" in result.body_excerpt
        assert secret not in result.body_excerpt      # R17
        assert result.as_dict()["reason"] == "bad_request"

    @pytest.mark.asyncio
    async def test_probe_does_not_consume_budget(self, monkeypatch):
        async def fake(*a, **kw):
            return FakeResponse(200, {"data": [{"url": "http://x/a.jpg"}]})

        def _boom(*a, **kw):
            raise AssertionError("probe не должен расходовать бюджет")

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", _boom)
        _patch_cfg(monkeypatch)
        result = await ig.probe()
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_probe_unreachable(self, monkeypatch):
        import httpx

        async def fake(*a, **kw):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_cfg(monkeypatch)
        result = await ig.probe()
        assert result.ok is False
        assert result.reason == "unreachable"
        assert result.status_code is None


# ── (d) стиль ───────────────────────────────────────────────────────────────

class TestStyleCompose:
    def test_style_present_then_visual(self):
        out = compose_cover_image_prompt("photoreal, PERMsoc", "a cat")
        assert out == "photoreal, PERMsoc a cat"

    def test_visual_trimmed_not_style(self):
        style = "s" * 400
        out = compose_cover_image_prompt(style, "v" * 900)
        assert out.startswith(style + " ")
        assert len(out) == int(
            getattr(Settings, "SUMMARY_COVER_PROMPT_MAX_CHARS", 1000))

    def test_style_capped_at_own_limit(self):
        cap = int(getattr(Settings, "SUMMARY_COVER_STYLE_MAX_CHARS", 500))
        out = compose_cover_image_prompt("s" * 2000, "v")
        # стиль обрезан своим капом, visual добавлен целиком
        assert out.startswith("s" * cap + " ")

    def test_empty_style(self):
        assert compose_cover_image_prompt("", "a cat") == "a cat"
        assert compose_cover_image_prompt(None, "a cat") == "a cat"


class TestStyleLogged:
    @pytest.mark.asyncio
    async def test_deliver_rich_logs_style_present_and_reason(
            self, monkeypatch, caplog):
        """(d)+(f): лог доказывает подмешивание стиля и показывает причину."""
        gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                               MagicMock(), concurrency_pool=MagicMock())
        style = "photoreal, PERMsoc"
        monkeypatch.setattr(sg.hot, "get",
                            lambda key, default=None: style)
        monkeypatch.setattr(
            sg, "generate_image_verbose",
            AsyncMock(return_value=(None, "bad_request")))
        monkeypatch.setattr(SummaryGenerator, "_plain_fallback",
                            AsyncMock())

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._deliver_rich(-100, "текст", "a lone cat",
                                    correlation_id="X")

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "style_present=True" in joined
        assert f"style_len={len(style)}" in joined
        # стиль реально подмешан в финальный промпт (visual идёт после стиля)
        assert "visual_len=10" in joined
        # (f) реальная причина отказа провайдера, а не только «unavailable».
        assert "bad_request" in joined
        assert "image unavailable (bad_request)" in joined
        SummaryGenerator._plain_fallback.assert_awaited_once()
