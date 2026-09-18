"""Раунд 10.23 (F5, ADR-1023-5) — инструмент `generate_image`, провайдер
изображений (POST/GET), бюджет, секрет, egress, идемпотентный сид.

Тесты не ходят в сеть: ``image_generation._http_request`` подменяется
детерминированной заглушкой; ключ провайдера нигде не печатается.
"""
from __future__ import annotations

import json
import re
import subprocess
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import image_generation as ig
from services import worker_budget
from services.config_migrations import migrate_image_provider_defaults
from services.param_catalog import get, get_by_pg_key
from services.telegram_send import SEND_ALLOWLIST
from services.tool_router import ToolContext, ToolRouter
from services.tool_schemas import (
    IMAGE_GENERATION_TOOL_NAME,
    TOOL_CALLING_TOOLS,
    active_tools,
)

_FIRST_EIGHT = [
    "query_chat_memory", "dig_into_lore", "execute_web_search",
    "summarize_video", "download_media", "get_bot_health",
    "get_recent_history", "compile_lore_story",
]


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"",
                 headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


def _patch_budget(monkeypatch, ok=True):
    monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=ok))


# ── Схема и гейт инструмента ────────────────────────────────────────────────

class TestToolSchema:
    def test_generate_image_is_ninth(self):
        names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        assert names == _FIRST_EIGHT + ["generate_image"]
        assert IMAGE_GENERATION_TOOL_NAME == "generate_image"

    def test_schema_strict(self):
        tool = TOOL_CALLING_TOOLS[-1]
        fn = tool["function"]
        assert fn["name"] == "generate_image"
        assert fn["description"].strip()
        assert not any("\u0400" <= ch <= "\u04FF" for ch in fn["description"])
        params = fn["parameters"]
        assert params["required"] == ["prompt"]
        assert params["additionalProperties"] is False
        assert params["properties"]["prompt"]["type"] == "string"
        json.dumps(tool)

    def test_active_tools_gate(self):
        assert [t["function"]["name"] for t in active_tools()] == _FIRST_EIGHT
        assert [t["function"]["name"]
                for t in active_tools(image_generation_enabled=True)] == \
            _FIRST_EIGHT + ["generate_image"]

    def test_factcheck_tools_unchanged(self):
        from services.tool_schemas import factcheck_tools
        names = [t["function"]["name"] for t in factcheck_tools()]
        assert "generate_image" not in names


# ── Ключевики ───────────────────────────────────────────────────────────────

class TestKeywords:
    @pytest.mark.parametrize("text", [
        "Бот, нарисуй кота в шляпе",
        "бот нарисуй закат",
        "Бот, создай изображение дракона",
        "Бот, создай картинку моря",
        "Бот, создай мем про понедельник",
        "Бот, создай арт в стиле киберпанк",
        "Бот, сгенерируй пейзаж",
    ])
    def test_matches(self, text):
        assert ig.is_image_keyword(text) is True

    @pytest.mark.parametrize("text", [
        "привет бот, как дела",
        "нарисуй кота",              # без обращения к боту
        "Бот, расскажи анекдот",
        "Бот, создай таблицу",
        "",
    ])
    def test_not_matches(self, text):
        assert ig.is_image_keyword(text) is False

    def test_extract_prompt(self):
        assert ig.extract_prompt("Бот, нарисуй кота в шляпе") == "кота в шляпе"
        assert ig.extract_prompt("Бот, создай мем про работу") == "про работу"


# ── Флаг модуля ─────────────────────────────────────────────────────────────

class TestModuleFlag:
    @pytest.mark.asyncio
    async def test_env_off(self, monkeypatch):
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_ENABLED", False)
        assert await ig.resolve_module_enabled(None) is False

    @pytest.mark.asyncio
    async def test_catalog_off(self, monkeypatch):
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_ENABLED", True)
        monkeypatch.setattr(
            ig.hot, "get",
            lambda key, default=None: False if key == ig.KEY_MODULE_ENABLED
            else default)
        assert await ig.resolve_module_enabled(None) is False

    @pytest.mark.asyncio
    async def test_tool_dispatch_disabled(self, monkeypatch):
        monkeypatch.setattr(ig, "resolve_module_enabled", AsyncMock(
            return_value=False))
        router = ToolRouter(types.SimpleNamespace())
        ctx = ToolContext(1, "Бот, нарисуй кота", bot=MagicMock())
        out = await router._generate_image({"prompt": "кот"}, ctx)
        assert json.loads(out)["status"] == "error"

    def test_registered_in_dispatch(self):
        router = ToolRouter(types.SimpleNamespace())
        assert callable(getattr(router, "_generate_image"))


# ── POST-режим ──────────────────────────────────────────────────────────────

class TestPostMode:
    @pytest.mark.asyncio
    async def test_post_hard_url_format(self, monkeypatch):
        calls = []

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            calls.append((method, url, json_body, headers))
            if method == "POST":
                return FakeResponse(200, {"data": [
                    {"url": "https://cdn.example/a.jpg"}]})
            return FakeResponse(200, content=b"\xff\xd8jpeg-bytes")

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_budget(monkeypatch)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok and res.content == b"\xff\xd8jpeg-bytes"
        method, url, body, _headers = calls[0]
        assert method == "POST"
        assert url.endswith("/images/generations")
        assert body["response_format"] == "url"
        assert body["model"] == "flux"
        assert body["size"] == ig._IMAGE_SIZE
        assert body["n"] == 1

    @pytest.mark.asyncio
    async def test_post_b64_fallback(self, monkeypatch):
        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            if method == "POST":
                import base64
                return FakeResponse(200, {"data": [
                    {"b64_json": base64.b64encode(b"img").decode()}]})
            raise AssertionError("download не должен вызываться")

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_budget(monkeypatch)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok and res.content == b"img"


# ── GET-режим ───────────────────────────────────────────────────────────────

class TestGetMode:
    @pytest.mark.asyncio
    async def test_get_url_and_no_key_leak(self, monkeypatch):
        urls = []

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            urls.append((method, url))
            return FakeResponse(200, content=b"img-bytes")

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_budget(monkeypatch)
        monkeypatch.setattr(
            ig.hot, "get",
            lambda key, default=None: True if key == ig.KEY_GET_MODE
            else ("top-secret-value" if key == ig.KEY_API_KEY else default))
        res = await ig.generate("кот в шляпе", chat_id=1)
        assert res.ok
        method, url = urls[0]
        assert method == "GET"
        assert "/image/" in url and "/v1/image/" not in url
        assert "model=flux" in url
        assert "top-secret-value" in url          # GET-режим допускает ?key
        # URL не уходит наружу в результате/логах — только байты.
        assert res.content == b"img-bytes"

    def test_host_from_base(self):
        assert ig._host_from_base("https://gen.pollinations.ai/v1") == \
            "https://gen.pollinations.ai"

    @pytest.mark.asyncio
    async def test_send_photo_gets_bytes_not_url(self, monkeypatch):
        monkeypatch.setattr(ig, "generate", AsyncMock(return_value=(
            ig.GenerationResult(ok=True, content=b"payload"))))
        captured = {}

        async def fake_send(bot, chat_id, photo, **kwargs):
            captured["photo"] = photo
            captured["kwargs"] = kwargs

        monkeypatch.setattr("services.telegram_send.send_photo", fake_send)
        res = await ig.generate_and_send(MagicMock(), 5, "кот",
                                         reply_to_message_id=42)
        assert res.ok
        assert captured["photo"].data == b"payload"
        assert "top-secret" not in str(captured["kwargs"])


# ── Бюджет ──────────────────────────────────────────────────────────────────

class TestBudget:
    @pytest.mark.asyncio
    async def test_consume_uses_image_metric(self, monkeypatch):
        consume = AsyncMock(return_value=True)
        monkeypatch.setattr(worker_budget, "consume", consume)
        ok = await ig._consume_budget(7)
        assert ok is True
        assert consume.await_args.kwargs["metric"] == \
            worker_budget.METRIC_IMAGE_CALLS
        assert consume.await_args.kwargs["scope"] == "chat:7"

    @pytest.mark.asyncio
    async def test_budget_exhausted_no_http(self, monkeypatch):
        _patch_budget(monkeypatch, ok=False)
        called = []

        async def fake(*a, **kw):
            called.append(1)
            return FakeResponse(200)

        monkeypatch.setattr(ig, "_http_request", fake)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok is False and res.reason == "budget"
        assert called == []

    @pytest.mark.asyncio
    async def test_budget_fail_open_on_error(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("pg down")

        monkeypatch.setattr(worker_budget, "consume", boom)
        assert await ig._consume_budget(7) is True

    @pytest.mark.asyncio
    async def test_metric_limit_reuses_per_chat_calls(self, monkeypatch):
        captured = []

        async def fake_resolve(key, *, chat_id, default):
            captured.append(key)
            return 5

        monkeypatch.setattr(worker_budget, "_resolve_limit", fake_resolve)
        await worker_budget._metric_limit("chat:3",
                                          worker_budget.METRIC_IMAGE_CALLS)
        assert captured == [worker_budget.LIMIT_CALLS_PER_CHAT]


# ── Ошибки/ретраи/размер ────────────────────────────────────────────────────

class TestErrors:
    @pytest.mark.asyncio
    async def test_retry_once_on_429(self, monkeypatch):
        seq = [FakeResponse(429, headers={"Retry-After": "0"}),
               FakeResponse(200)]
        monkeypatch.setattr(ig, "_http_request",
                            AsyncMock(side_effect=seq))
        resp = await ig._request_with_retry("POST", "http://x", timeout=1)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_retry_on_401(self, monkeypatch):
        calls = []

        async def fake(*a, **kw):
            calls.append(1)
            return FakeResponse(401)

        monkeypatch.setattr(ig, "_http_request", fake)
        resp = await ig._request_with_retry("POST", "http://x", timeout=1)
        assert resp.status_code == 401
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_http_error_reason(self, monkeypatch):
        monkeypatch.setattr(ig, "_http_request",
                            AsyncMock(return_value=FakeResponse(401)))
        _patch_budget(monkeypatch)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok is False and res.reason == "unauthorized"

    @pytest.mark.asyncio
    async def test_too_large(self, monkeypatch):
        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            if method == "POST":
                return FakeResponse(200, {"data": [{"url": "http://img"}]})
            return FakeResponse(200, content=b"x" * 100)

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_budget(monkeypatch)
        monkeypatch.setattr(Settings, "IMAGE_MAX_BYTES", 10)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok is False and res.reason == "too_large"

    @pytest.mark.asyncio
    async def test_empty_prompt(self):
        res = await ig.generate("   ", chat_id=1)
        assert res.ok is False and res.reason == "empty_prompt"

    @pytest.mark.asyncio
    async def test_keyword_fallback_block(self, monkeypatch):
        monkeypatch.setattr(ig, "generate_and_send", AsyncMock(return_value=(
            ig.GenerationResult(ok=False, reason="unauthorized"))))
        ctx = ToolContext(1, "Бот, нарисуй кота", bot=MagicMock())
        block = await ig.maybe_handle_keyword(ctx, "Бот, нарисуй кота")
        assert 'status="error"' in block
        assert ig.IMAGE_GENERATION_FALLBACK_PHRASE in block

    @pytest.mark.asyncio
    async def test_keyword_ok_block(self, monkeypatch):
        monkeypatch.setattr(ig, "generate_and_send", AsyncMock(return_value=(
            ig.GenerationResult(ok=True, content=b"x"))))
        ctx = ToolContext(1, "Бот, нарисуй кота", bot=MagicMock())
        block = await ig.maybe_handle_keyword(ctx, "Бот, нарисуй кота")
        assert 'status="ok"' in block


# ── Каталог/сид/секрет/egress ───────────────────────────────────────────────

class TestCatalog:
    def test_groups_and_keys(self):
        assert get("IMAGE_BASE_URL").group == "models_images"
        assert get("IMAGE_MODEL").group == "models_images"
        assert get("IMAGE_GET_MODE").group == "models_images"
        assert get("IMAGE_API_KEY").group == "keys_images"
        assert get("IMAGE_GENERATION_MODULE_ENABLED").group == \
            "flags_module_images"
        assert get_by_pg_key("models.image_base_url") is not None
        assert get_by_pg_key("keys.image_api_key").secret is True
        assert get("IMAGE_API_KEY").pg_key == "keys.image_api_key"

    def test_defaults(self):
        s = Settings()
        assert s.IMAGE_BASE_URL == "https://gen.pollinations.ai/v1"
        assert s.IMAGE_MODEL == "flux"
        assert s.IMAGE_GET_MODE is False
        assert s.IMAGE_API_KEY == ""
        assert s.IMAGE_GENERATION_MODULE_ENABLED is True
        assert Settings.IMAGE_GENERATION_ENABLED is True


class _FakeCache:
    def __init__(self, values=None):
        self.pg_available = True
        self.values = dict(values or {})
        self.set_calls = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.values[key] = value
        self.set_calls.append((key, value, category))


class TestSeedMigration:
    @pytest.mark.asyncio
    async def test_idempotent_and_secret_untouched(self):
        cache = _FakeCache()
        first = await migrate_image_provider_defaults(cache)
        assert set(first) == {
            "models.image_base_url", "models.image_model",
            "models.image_get_mode"}
        assert "keys.image_api_key" not in cache.values
        second = await migrate_image_provider_defaults(cache)
        assert second == {}

    @pytest.mark.asyncio
    async def test_custom_not_overwritten(self):
        cache = _FakeCache({"models.image_model": "my-model"})
        report = await migrate_image_provider_defaults(cache)
        assert "models.image_model" not in report
        assert cache.values["models.image_model"] == "my-model"

    @pytest.mark.asyncio
    async def test_pg_down_skip(self):
        cache = _FakeCache()
        cache.pg_available = False
        assert await migrate_image_provider_defaults(cache) == {}


class TestSecretAndEgress:
    _KEY_RE = re.compile("sk" + "_" + "[A-Za-z0-9]{20,}")

    def _tracked_text_files(self, root: Path):
        try:
            out = subprocess.run(["git", "ls-files"], cwd=root,
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                for rel in out.stdout.splitlines():
                    yield root / rel
                return
        except Exception:
            pass
        for base in ("services", "config", "web", "handlers", "tools",
                     "tests", "scripts"):
            for path in (root / base).rglob("*"):
                if path.is_file():
                    yield path

    def test_no_plaintext_image_key_in_repo(self):
        root = Path(__file__).resolve().parents[1]
        skip = (".git", ".venv", "__pycache__", "migrate_history", "plans")
        for path in self._tracked_text_files(root):
            posix = path.as_posix()
            if any(part in posix for part in skip):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeError):
                continue
            assert not self._KEY_RE.search(text), \
                f"plaintext-ключ найден: {posix}"

    def test_image_generation_allowlisted(self):
        reason = SEND_ALLOWLIST.get("services/image_generation.py")
        assert reason and reason.strip()


class TestEgressWrapper:
    @pytest.mark.asyncio
    async def test_send_photo_wrapper(self):
        from services.telegram_send import send_photo
        bot = MagicMock()
        bot.send_photo = AsyncMock(return_value="sent")
        await send_photo(bot, 1, "photo", reply_to_message_id=5)
        assert bot.send_photo.await_args.args[0] == 1
        assert bot.send_photo.await_args.kwargs["reply_to_message_id"] == 5
