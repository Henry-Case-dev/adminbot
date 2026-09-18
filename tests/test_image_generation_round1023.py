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

    @pytest.mark.asyncio
    async def test_dispatch_mapping(self, monkeypatch):
        """review iter1 Finding 7: реальный маппинг `"generate_image"` в
        `dispatch()` (а не прямой вызов метода)."""
        monkeypatch.setattr(ig, "resolve_module_enabled", AsyncMock(
            return_value=True))
        monkeypatch.setattr(ig, "generate_and_send", AsyncMock(
            return_value=ig.GenerationResult(ok=True, content=b"x")))
        router = ToolRouter(types.SimpleNamespace())
        ctx = ToolContext(1, "Бот, нарисуй кота", bot=MagicMock())
        out = await router.dispatch("generate_image", {"prompt": "кот"}, ctx)
        assert json.loads(out)["status"] == "success"


# ── Пре-гейт и прямой чат ───────────────────────────────────────────────────

class TestPreGateIntegration:
    @pytest.mark.asyncio
    async def test_pre_gate_calls_service(self, monkeypatch):
        from services.direct_chat_service import DirectChatService
        monkeypatch.setattr(ig, "resolve_module_enabled", AsyncMock(
            return_value=True))
        called = {}

        async def fake_handle(ctx, query):
            called["query"] = query
            return '<image_result status="ok">x</image_result>'

        monkeypatch.setattr(ig, "maybe_handle_keyword", fake_handle)
        block = await DirectChatService._image_pre_gate_block(
            types.SimpleNamespace(), 1, "Бот, нарисуй кота", MagicMock(),
            types.SimpleNamespace(message_id=7), None)
        assert block.startswith("<image_result")
        assert called["query"] == "Бот, нарисуй кота"

    @pytest.mark.asyncio
    async def test_pre_gate_module_off(self, monkeypatch):
        from services.direct_chat_service import DirectChatService
        monkeypatch.setattr(ig, "resolve_module_enabled", AsyncMock(
            return_value=False))
        monkeypatch.setattr(ig, "maybe_handle_keyword", AsyncMock())
        block = await DirectChatService._image_pre_gate_block(
            types.SimpleNamespace(), 1, "Бот, нарисуй кота", MagicMock(),
            types.SimpleNamespace(message_id=7), None)
        assert block == ""
        ig.maybe_handle_keyword.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pre_gate_no_keyword(self, monkeypatch):
        from services.direct_chat_service import DirectChatService
        monkeypatch.setattr(ig, "resolve_module_enabled", AsyncMock(
            return_value=True))
        monkeypatch.setattr(ig, "maybe_handle_keyword", AsyncMock())
        block = await DirectChatService._image_pre_gate_block(
            types.SimpleNamespace(), 1, "Бот, расскажи анекдот", MagicMock(),
            types.SimpleNamespace(message_id=7), None)
        assert block == ""
        ig.maybe_handle_keyword.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_direct_chat_image_off_eight_tools(self, monkeypatch):
        """review iter1 Finding 7: OFF-ветка модуля в прямом чате → 8 тулов."""
        from tests.test_direct_chat import (
            _bot as dc_bot,
            _make_service,
            _message as dc_message,
            _user as dc_user,
        )
        monkeypatch.setattr("services.image_generation."
                            "resolve_module_enabled",
                            AsyncMock(return_value=False))
        captured = {}

        async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                       temperature, chat_id=None, **kwargs):
            captured["tools"] = tools
            return "ответ"

        monkeypatch.setattr("services.direct_chat_service.chat_with_tools",
                            fake_chat_with_tools)
        service = _make_service(tool_router=MagicMock())
        bot = dc_bot()
        user = dc_user()
        await service.handle(bot, dc_message(text="привет", message_id=1,
                                             user=user), user)
        names = [t["function"]["name"] for t in captured["tools"]]
        assert len(names) == 8
        assert "generate_image" not in names

    @pytest.mark.asyncio
    async def test_direct_chat_pre_gate_disables_tool(self, monkeypatch):
        """review iter1 Finding 3: на ход пре-гейта инструмент исключён —
        один путь генерации, без двойного платного вызова."""
        from tests.test_direct_chat import (
            _bot as dc_bot,
            _make_service,
            _message as dc_message,
            _user as dc_user,
        )
        monkeypatch.setattr("services.image_generation."
                            "resolve_module_enabled",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(
            "services.image_generation.maybe_handle_keyword",
            AsyncMock(return_value='<image_result status="ok">ok</image_result>'))
        captured = {}

        async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                       temperature, chat_id=None, **kwargs):
            captured["tools"] = tools
            captured["payload"] = payload
            return "ответ"

        monkeypatch.setattr("services.direct_chat_service.chat_with_tools",
                            fake_chat_with_tools)
        service = _make_service(tool_router=MagicMock())
        bot = dc_bot()
        user = dc_user()
        await service.handle(bot, dc_message(text="Бот, нарисуй кота",
                                             message_id=2, user=user), user)
        names = [t["function"]["name"] for t in captured["tools"]]
        assert "generate_image" not in names
        # Блок пре-гейта инжектится в user-content Stage-1.
        assert any("<image_result" in str(m.get("content", ""))
                   for m in captured["payload"] if isinstance(m, dict))


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
    async def test_get_url_is_anonymous(self, monkeypatch):
        """review iter1 Finding 1: GET-режим строго анонимный — ключ НЕ в URL."""
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
            else ("SENTINELKEYVALUE12345" if key == ig.KEY_API_KEY
                  else default))
        res = await ig.generate("кот в шляпе", chat_id=1)
        assert res.ok
        method, url = urls[0]
        assert method == "GET"
        assert "/image/" in url and "/v1/image/" not in url
        assert "model=flux" in url
        # Ключ не попадает в query GET-режима вовсе.
        assert "SENTINELKEYVALUE12345" not in url
        assert "key=" not in url
        assert res.content == b"img-bytes"

    @pytest.mark.asyncio
    async def test_get_key_not_in_logs(self, monkeypatch, caplog):
        """review iter1 Finding 1: при GET-вызове с заданным ключом ключ не
        встречается ни в одном лог-сообщении (httpx INFO заглушён, фильтры)."""
        import logging

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            # Эмулируем то, что httpx-INFO писал бы полный URL.
            logging.getLogger("httpx").info(
                'HTTP Request: %s %s "HTTP/1.1 200 OK"', method, url)
            return FakeResponse(200, content=b"img")

        monkeypatch.setattr(ig, "_http_request", fake)
        _patch_budget(monkeypatch)
        sentinel = "SENTINELKEYVALUE12345"
        monkeypatch.setattr(
            ig.hot, "get",
            lambda key, default=None: True if key == ig.KEY_GET_MODE
            else (sentinel if key == ig.KEY_API_KEY else default))
        with caplog.at_level(logging.INFO):
            await ig.generate("кот", chat_id=1)
        for record in caplog.records:
            assert sentinel not in record.getMessage()

    def test_secret_mask_filter_masks_keyed_url(self):
        """Defense-in-depth: фильтр для консольного обработчика маскирует
        ключ в URL (закрывает путь stdout → journald)."""
        import logging

        from services.log_ring import SecretMaskFilter
        record = logging.LogRecord(
            "httpx", logging.INFO, __file__, 1,
            'HTTP Request: GET http://x/image/cat?key=sk_ABCDEFGHIJKLMNOP',
            (), None)
        assert SecretMaskFilter().filter(record) is True
        assert "sk_ABCDEFGHIJKLMNOP" not in record.getMessage()

    def test_host_from_base(self):
        assert ig._host_from_base("https://gen.pollinations.ai/v1") == \
            "https://gen.pollinations.ai"

    @pytest.mark.asyncio
    async def test_send_photo_gets_bytes_not_url(self, monkeypatch):
        from aiogram.types import BufferedInputFile
        monkeypatch.setattr(ig, "generate", AsyncMock(return_value=(
            ig.GenerationResult(ok=True, content=b"payload"))))
        captured = {}

        async def fake_send(bot, chat_id, photo, **kwargs):
            captured["photo"] = photo
            captured["chat_id"] = chat_id
            captured["kwargs"] = kwargs

        monkeypatch.setattr("services.telegram_send.send_photo", fake_send)
        res = await ig.generate_and_send(MagicMock(), 5, "кот",
                                         reply_to_message_id=42)
        assert res.ok
        # Наружу уходят именно БАЙТЫ (BufferedInputFile), а не URL провайдера.
        assert isinstance(captured["photo"], BufferedInputFile)
        assert captured["photo"].data == b"payload"
        assert captured["photo"].filename
        assert captured["kwargs"].get("reply_to_message_id") == 42
        assert "key=" not in str(captured)


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

    @pytest.mark.asyncio
    async def test_day_summary_reports_image_calls(self):
        """review iter1 Finding 8: расход на картинки виден в сводке бюджета."""
        summary = await worker_budget.get_day_summary(pg=None)
        assert "image_calls" in summary["global"]


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
        # review iter1 Finding 2: `plans/` НЕ исключаем — трекаемые
        # MEMORY.md/backlog.md/спеки тоже под сканом (untracked current_task.md
        # и так не попадает: скан идёт по `git ls-files`).
        root = Path(__file__).resolve().parents[1]
        skip = (".git", ".venv", "__pycache__", "migrate_history")
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
