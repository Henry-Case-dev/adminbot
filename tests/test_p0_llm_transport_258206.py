# -*- coding: utf-8 -*-
"""P0 SMART transport slice (2.58.206) — LLM transport hot-apply contract.

Покрывает ARCH_DECISION (S1/S2/S4/S5/S6, AC-01..AC-06, AC-09):

  * дефолты 180с (один HTTP-ответ) / 360с (предел одной основной попытки)
    и их семантика «не дедлайн исследования»;
  * идемпотентная PG-миграция: нет ключа → новый дефолт; старый дефолт →
    обновление; кастом → preserve; PG down → skip;
  * PG-значение не перебивается env-дефолтом;
  * hot-apply модели/адреса/таймаута/бюджета/ретраев/фоллбэка на СЛЕДУЮЩЕМ
    вызове без пересоздания LLMClient/httpx-клиента;
  * in-flight `_post` держит снимок политики (mid-flight смена настроек не
    меняет текущую попытку);
  * фоллбэк использует СВОЙ таймаут, а не primary 180с;
  * эмбеддинги ограничены техническим потолком 60с;
  * `cause_class="budget"` для бюджетных таймаутов, `read_timeouts` /
    `budget_exhausted` в `llm_stats()`;
  * R17-safe поля логов `LLM timeout` / `LLM request OK` (провайдер-хост,
    модель, канал, модуль, шаг, попытки, elapsed, effective-лимиты, источники,
    request_chars/tools_count/streaming/finish_reason; без промптов/ключей).

RED на базе `bca18c1e`: дефолты 30/60, нет миграции, нет hot-apply модели/
политики, нет per-request окна, нет cause_class/метрик, advanced-блок UI.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

import services.llm_client as lc
from config.settings import Settings, settings
from services import hot_config as hot
from services.config_migrations import (
    LLM_GUARD_MIGRATIONS,
    migrate_llm_guard_defaults,
)
from services.llm_client import LLMClient, LLMTimeoutError, llm_stats


class _Cache:
    """Мини-ConfigCache: sync get, async set, pg_available-флаг."""

    def __init__(self, data=None, pg_available=True):
        self.data = dict(data or {})
        self.pg_available = pg_available

    def get(self, key, default=None):
        return self.data.get(key, default)

    async def set(self, key, value, category=None):
        self.data[key] = value


@pytest.fixture
def hot_cache(monkeypatch):
    """Подменяет глобальный ConfigCache; восстанавливает прежний."""
    old = hot.get_config_cache()
    cache = _Cache()
    hot.set_config_cache(cache)
    try:
        yield cache
    finally:
        hot.set_config_cache(old)


def _make_client(handler, monkeypatch, *, fallback=False, **kwargs):
    """LLMClient на httpx.MockTransport; перехватывает per-request окна."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    params = dict(
        base_url="https://primary.example/v1",
        api_key="test-key",
        chat_model="model-init",
        embed_model="embed-init",
        fallback_base_url="",
        fallback_model="",
        fallback_api_key="",
    )
    if fallback:
        params.update(
            fallback_base_url="https://fallback.example/v1",
            fallback_model="fallback-model",
            fallback_api_key="fb-key",
        )
    params.update(kwargs)
    client = LLMClient(**params)
    client.backoff_base = 0        # тест-хук: без реальных пауз
    return client


def _ok_handler(calls, *, finish_reason="stop", usage=None):
    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"},
                             "finish_reason": finish_reason}],
                "usage": usage or {"prompt_tokens": 1, "completion_tokens": 1},
            },
            request=request,
        )
    return handler


def _read_timeout(request):
    return (request.extensions.get("timeout") or {}).get("read")


class _StubHttp:
    """httpx-клиент-заглушка с единственным методом post."""

    def __init__(self, post):
        self.post = post


# ── A. Дефолты 180/360 + семантика ─────────────────────────────────────────
class TestDefaults:
    def test_settings_defaults_are_180_360(self):
        assert Settings.LLM_TIMEOUT == 180.0
        assert Settings.LLM_TOTAL_BUDGET == 360.0

    def test_semantics_not_research_deadline_in_catalog(self):
        from services import param_catalog as pc
        timeout_desc = pc.REGISTRY["LLM_TIMEOUT"].description.lower()
        budget_desc = pc.REGISTRY["LLM_TOTAL_BUDGET"].description.lower()
        retries_desc = pc.REGISTRY["LLM_MAX_RETRIES"].description.lower()
        assert "не дедлайн исследования" in timeout_desc
        assert "не дедлайн исследования" in budget_desc
        for desc in (timeout_desc, budget_desc, retries_desc):
            assert "без перезапуска" in desc
            assert "не управляет" in desc and "summary" in desc
            assert "супервизор" in desc

    def test_readme_and_env_example_show_180_360(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        readme = (root / "README.md").read_text(encoding="utf-8")
        env = (root / ".env.example").read_text(encoding="utf-8")
        assert "| `LLM_TIMEOUT` | `180.0` |" in readme
        assert "| `LLM_TOTAL_BUDGET` | `360.0` |" in readme
        assert "LLM_TIMEOUT=180.0" in env
        assert "# LLM_TOTAL_BUDGET=360.0" in env


# ── B. Идемпотентная миграция PG ────────────────────────────────────────────
class TestMigration:
    @pytest.mark.asyncio
    async def test_missing_rows_seed_new_defaults(self, caplog):
        cache = _Cache({})
        with caplog.at_level(logging.INFO):
            report = await migrate_llm_guard_defaults(cache)
        assert cache.data["models.llm_timeout"] == 180.0
        assert cache.data["models.llm_total_budget"] == 360.0
        assert report == {"models.llm_timeout": "seeded",
                          "models.llm_total_budget": "seeded"}
        assert "llm_guard_migration" in caplog.text

    @pytest.mark.asyncio
    async def test_old_defaults_are_updated(self):
        cache = _Cache({"models.llm_timeout": "30",           # PG может str
                        "models.llm_total_budget": 60.0})
        report = await migrate_llm_guard_defaults(cache)
        assert cache.data["models.llm_timeout"] == 180.0
        assert cache.data["models.llm_total_budget"] == 360.0
        assert report == {"models.llm_timeout": "updated",
                          "models.llm_total_budget": "updated"}

    @pytest.mark.asyncio
    async def test_custom_values_preserved(self, caplog):
        cache = _Cache({"models.llm_timeout": 45.0,
                        "models.llm_total_budget": 600.0})
        with caplog.at_level(logging.INFO):
            report = await migrate_llm_guard_defaults(cache)
        assert cache.data == {"models.llm_timeout": 45.0,
                              "models.llm_total_budget": 600.0}
        assert report == {}
        # INFO-режим (CONFIG_MIGRATION_INFO_LOGGING_ENABLED) → CUSTOM_PRESERVED;
        # OFF — прежний WARNING (grep-паритет). Оба варианта — «не трогаем».
        assert ("CONFIG_MIGRATION_CUSTOM_PRESERVED" in caplog.text
                or "кастом владельца — НЕ трогаем" in caplog.text)

    @pytest.mark.asyncio
    async def test_already_new_defaults_noop(self):
        cache = _Cache({"models.llm_timeout": 180,
                        "models.llm_total_budget": "360"})
        report = await migrate_llm_guard_defaults(cache)
        assert report == {}

    @pytest.mark.asyncio
    async def test_pg_down_skips(self):
        cache = _Cache({"models.llm_timeout": 30.0}, pg_available=False)
        report = await migrate_llm_guard_defaults(cache)
        assert report == {}
        assert cache.data == {"models.llm_timeout": 30.0}

    @pytest.mark.asyncio
    async def test_none_cache_skips(self):
        assert await migrate_llm_guard_defaults(None) == {}

    def test_bot_calls_migration_before_startup(self):
        """Миграция — в main() ДО on_startup(), который создаёт LLMClient."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        source = (root / "bot.py").read_text(encoding="utf-8")
        migration_at = source.index(
            "await migrate_llm_guard_defaults(cache)")
        startup_at = source.index("memory = await on_startup()")
        assert migration_at < startup_at

    def test_migration_contract_values(self):
        assert LLM_GUARD_MIGRATIONS == {"models.llm_timeout": (30.0, 180.0),
                                       "models.llm_total_budget": (60.0, 360.0)}


# ── C. PG перебивает env-дефолт; hot-apply на следующем вызове ──────────────
class TestHotApply:
    @pytest.mark.asyncio
    async def test_pg_value_beats_env_default(self, hot_cache, monkeypatch):
        # env/settings-дефолт 30/60 не должен перебить сохранённый PG.
        monkeypatch.setattr(type(settings), "LLM_TIMEOUT", 30.0)
        monkeypatch.setattr(type(settings), "LLM_TOTAL_BUDGET", 60.0)
        hot_cache.data.update({"models.llm_timeout": 180.0,
                               "models.llm_total_budget": 360.0})
        calls = []
        client = _make_client(_ok_handler(calls), monkeypatch, timeout=30.0)
        assert client._timeout == 180.0
        assert client._budget == 360.0
        await client.generate([{"role": "user", "content": "hi"}])
        assert _read_timeout(calls[0]) == 180.0

    @pytest.mark.asyncio
    async def test_model_url_timeout_budget_apply_without_restart(
            self, hot_cache, monkeypatch):
        calls = []
        client = _make_client(_ok_handler(calls), monkeypatch)
        hot_cache.data.update({
            "models.llm_model_name": "model-hot-1",
            "models.llm_base_url": "https://hot-one.example/v1",
            "models.llm_timeout": 5.0,
            "models.llm_total_budget": 9.0,
        })
        first = await client.generate_with_metadata(
            [{"role": "user", "content": "hi"}], module="direct_chat",
            step="reply")
        assert first.model == "model-hot-1"
        assert str(calls[0].url) == "https://hot-one.example/v1/chat/completions"
        assert _read_timeout(calls[0]) == 5.0
        client_id = id(client._client)

        # Меняем настройки — СЛЕДУЮЩИЙ вызов уже с новыми значениями.
        hot_cache.data.update({
            "models.llm_model_name": "model-hot-2",
            "models.llm_base_url": "https://hot-two.example/v1",
            "models.llm_timeout": 7.0,
            "models.llm_total_budget": 11.0,
        })
        second = await client.generate_with_metadata(
            [{"role": "user", "content": "hi"}])
        assert second.model == "model-hot-2"
        assert str(calls[1].url) == "https://hot-two.example/v1/chat/completions"
        assert _read_timeout(calls[1]) == 7.0
        # Кэшированный httpx-клиент НЕ пересоздан (ключ не менялся).
        assert id(client._client) == client_id
        assert client._timeout == 7.0
        assert client._budget == 11.0

    @pytest.mark.asyncio
    async def test_explicit_constructor_model_base_survive_hot_config(
            self, hot_cache, monkeypatch):
        """F1 regression: явный constructor-level model/base (Speech Try,
        per-call каналы) не затирается hot-конфигом на первом вызове.

        Раньше ``_policy_chat_model``/``_policy_base_url`` инициализировались
        рабочим kwarg'ом, поэтому hot-значение всегда считалось «изменённым»
        и молча подменяло явный выбор. Теперь хранится конфиг-снимок: hot
        применяется только при реальной смене настроек.
        """
        calls = []
        hot_cache.data.update({
            "models.llm_model_name": "config-model",
            "models.llm_base_url": "https://config.example/v1",
        })
        client = _make_client(
            _ok_handler(calls), monkeypatch,
            base_url="https://custom.example/v1", chat_model="custom-model")
        first = await client.generate_with_metadata(
            [{"role": "user", "content": "hi"}], module="speech_ui",
            step="try_lab")
        assert first.model == "custom-model"
        assert str(calls[0].url) == "https://custom.example/v1/chat/completions"
        assert client._chat_model == "custom-model"
        assert client._base_url == "https://custom.example/v1"
        client_id = id(client._client)

        # Реальное изменение hot-конфига — СЛЕДУЮЩИЙ вызов уже с новым
        # значением (и httpx-клиент не пересоздан: менялся не ключ).
        hot_cache.data.update({
            "models.llm_model_name": "config-model-2",
            "models.llm_base_url": "https://config-two.example/v1",
        })
        second = await client.generate_with_metadata(
            [{"role": "user", "content": "hi"}])
        assert second.model == "config-model-2"
        assert str(calls[1].url) == \
            "https://config-two.example/v1/chat/completions"
        assert client._chat_model == "config-model-2"
        assert client._base_url == "https://config-two.example/v1"
        assert id(client._client) == client_id

    @pytest.mark.asyncio
    async def test_inflight_model_snapshot_survives_hot_change(
            self, hot_cache, monkeypatch):
        """F1: in-flight запрос держит снимок модели/адреса, собранный на
        входе вызова; смена hot-конфига посреди запроса его не меняет."""
        entered = asyncio.Event()
        release = asyncio.Event()
        seen = []

        async def post(url, **kwargs):  # noqa: ARG001
            seen.append((kwargs["json"]["model"], url))
            entered.set()
            await release.wait()
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"},
                                   "finish_reason": "stop"}]},
                request=httpx.Request("POST", url))

        hot_cache.data.update({"models.llm_model_name": "config-a",
                               "models.llm_base_url": "https://a.example/v1"})
        client = _make_client(_ok_handler([]), monkeypatch,
                              base_url="https://a.example/v1",
                              chat_model="config-a")
        client._get_client = lambda key=None: _StubHttp(post)  # noqa: ARG005

        task = asyncio.create_task(client.generate(
            [{"role": "user", "content": "hi"}]))
        await asyncio.wait_for(entered.wait(), timeout=5)
        hot_cache.data.update({"models.llm_model_name": "config-b",
                               "models.llm_base_url": "https://b.example/v1"})
        release.set()
        await asyncio.wait_for(task, timeout=5)
        # Текущий запрос — со снимком config-a (модель и адрес).
        assert seen == [("config-a", "https://a.example/v1/chat/completions")]
        assert client._chat_model == "config-a"

        # Следующий вызов подхватывает config-b.
        entered.clear()
        await client.generate([{"role": "user", "content": "hi"}])
        assert seen[-1] == ("config-b", "https://b.example/v1/chat/completions")
        assert client._chat_model == "config-b"

    @pytest.mark.asyncio
    async def test_retries_and_fallback_policy_apply_hot(
            self, hot_cache, monkeypatch):
        calls = []

        def handler(request):
            calls.append(request)
            if "fallback.example" in str(request.url):
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "fb"}}]},
                    request=request)
            return httpx.Response(500, json={"error": "x"}, request=request)

        client = _make_client(handler, monkeypatch, fallback=True)
        hot_cache.data.update({
            "models.llm_max_retries": 0,
            "models.llm_fallback_timeout_seconds": 12.0,
            "models.llm_fallback_max_retries": 1,
        })
        await client.generate([{"role": "user", "content": "hi"}])
        assert client._max_retries == 0
        assert client._fallback_timeout == 12.0
        assert client._fallback_max_retries == 1
        # max_retries=0 → одна primary-попытка; fallback — со своим окном 12с.
        primary = [r for r in calls if "primary.example" in str(r.url)]
        fallback = [r for r in calls if "fallback.example" in str(r.url)]
        assert len(primary) == 1
        assert all(_read_timeout(r) == 12.0 for r in fallback)

    @pytest.mark.asyncio
    async def test_manual_attribute_override_survives_refresh(
            self, hot_cache, monkeypatch):
        # Тест-хук/ручное переопределение не затирается, пока конфиг не менялся.
        calls = []
        hot_cache.data.update({"models.llm_timeout": 180.0})
        client = _make_client(_ok_handler(calls), monkeypatch, timeout=180.0)
        client._timeout = 0.05
        await client.generate([{"role": "user", "content": "hi"}])
        assert client._timeout == 0.05
        assert _read_timeout(calls[0]) == 0.05

    @pytest.mark.asyncio
    async def test_inflight_post_keeps_policy_snapshot(
            self, hot_cache, monkeypatch):
        entered = asyncio.Event()
        release = asyncio.Event()
        seen_timeouts = []

        async def post(url, **kwargs):
            seen_timeouts.append(kwargs["timeout"].read)
            entered.set()
            await release.wait()
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"},
                                   "finish_reason": "stop"}]},
                request=httpx.Request("POST", url))

        hot_cache.data.update({"models.llm_timeout": 6.0,
                               "models.llm_total_budget": 8.0})
        client = _make_client(_ok_handler([]), monkeypatch)
        client._get_client = lambda key=None: _StubHttp(post)  # noqa: ARG005

        task = asyncio.create_task(client.generate(
            [{"role": "user", "content": "hi"}]))
        await asyncio.wait_for(entered.wait(), timeout=5)
        # Смена настроек ПОСРЕДИ in-flight запроса.
        hot_cache.data.update({"models.llm_timeout": 9.0,
                               "models.llm_total_budget": 10.0})
        release.set()
        await asyncio.wait_for(task, timeout=5)
        # Текущая попытка — со снимком 6с, а не 9с.
        assert seen_timeouts == [6.0]
        assert client._timeout == 6.0

        # Следующий вызов подхватывает 9с.
        entered.clear()
        await client.generate([{"role": "user", "content": "hi"}])
        assert seen_timeouts[-1] == 9.0
        assert client._timeout == 9.0


# ── D. Таймауты: primary / fallback / embed ────────────────────────────────
class TestTimeouts:
    @pytest.mark.asyncio
    async def test_primary_uses_policy_timeout_per_request(
            self, hot_cache, monkeypatch):
        hot_cache.data.update({"models.llm_timeout": 180.0})
        calls = []
        client = _make_client(_ok_handler(calls), monkeypatch)
        await client.generate([{"role": "user", "content": "hi"}])
        assert _read_timeout(calls[0]) == 180.0

    @pytest.mark.asyncio
    async def test_fallback_uses_own_timeout_not_primary(
            self, hot_cache, monkeypatch):
        hot_cache.data.update({"models.llm_timeout": 180.0,
                               "models.llm_fallback_timeout_seconds": 60.0})
        calls = []

        def handler(request):
            calls.append(request)
            if "fallback.example" in str(request.url):
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "fb"}}]},
                    request=request)
            return httpx.Response(500, json={"error": "x"}, request=request)

        client = _make_client(handler, monkeypatch, fallback=True)
        await client.generate([{"role": "user", "content": "hi"}])
        primary = [r for r in calls if "primary.example" in str(r.url)]
        fallback = [r for r in calls if "fallback.example" in str(r.url)]
        assert primary and fallback
        assert all(_read_timeout(r) == 180.0 for r in primary)
        assert all(_read_timeout(r) == 60.0 for r in fallback)
        assert client._fallback_timeout == 60.0

    @pytest.mark.asyncio
    async def test_explicit_supervised_timeout_is_preserved(
            self, hot_cache, monkeypatch):
        hot_cache.data.update({"models.llm_timeout": 180.0})
        calls = []
        client = _make_client(_ok_handler(calls), monkeypatch, fallback=True)
        await client._post_fallback({"model": "x"}, timeout=0.7)
        assert _read_timeout(calls[0]) == 0.7
        await client._post("/chat/completions", {"model": "x"},
                           budget=1.0, timeout=0.9)
        assert _read_timeout(calls[1]) == 0.9

    @pytest.mark.asyncio
    async def test_embed_has_technical_cap_60(self, hot_cache, monkeypatch):
        hot_cache.data.update({"models.llm_timeout": 180.0})
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                200, json={"data": [{"embedding": [0.1, 0.2]}]},
                request=request)

        client = _make_client(handler, monkeypatch)
        await client.embed(["text"])
        assert _read_timeout(calls[0]) == 60.0

    @pytest.mark.asyncio
    async def test_embed_cap_keeps_smaller_config_timeout(
            self, hot_cache, monkeypatch):
        hot_cache.data.update({"models.llm_timeout": 5.0})
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                200, json={"data": [{"embedding": [0.1]}]}, request=request)

        client = _make_client(handler, monkeypatch)
        await client.embed(["text"])
        assert _read_timeout(calls[0]) == 5.0


# ── E. Причины/метрики/логи ─────────────────────────────────────────────────
class TestObservability:
    @pytest.mark.asyncio
    async def test_budget_timeout_cause_class_and_metric(
            self, hot_cache, monkeypatch, caplog):
        async def slow_post(url, **kwargs):  # noqa: ARG001
            await asyncio.sleep(0.3)
            return httpx.Response(200, json={},
                                  request=httpx.Request("POST", url))

        client = _make_client(_ok_handler([]), monkeypatch)
        client._get_client = lambda key=None: _StubHttp(slow_post)  # noqa: ARG
        before = llm_stats()["budget_exhausted"]
        with caplog.at_level(logging.ERROR, logger=lc.__name__):
            with pytest.raises(LLMTimeoutError) as raised:
                await client._post("/chat/completions", {"model": "m"},
                                   budget=0.05, max_retries=0,
                                   module="direct_chat", step="reply")
        assert raised.value.cause_class == "budget"
        assert llm_stats()["budget_exhausted"] == before + 1
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason=total_budget_exceeded" in logged
        assert "cause_class=budget" in logged
        assert "effective_budget=" in logged
        assert "timeout_source=" in logged

    @pytest.mark.asyncio
    async def test_read_timeout_metric_and_log_fields(self, monkeypatch,
                                                      caplog):
        def handler(request):
            raise httpx.ReadTimeout("read timed out", request=request)

        client = _make_client(handler, monkeypatch)
        before_read = llm_stats()["read_timeouts"]
        before_timeouts = llm_stats()["timeouts"]
        with caplog.at_level(logging.ERROR, logger=lc.__name__):
            with pytest.raises(LLMTimeoutError) as raised:
                await client._post("/chat/completions", {"model": "m"},
                                   max_retries=0, module="checkup",
                                   step="tool")
        assert raised.value.cause_class == "ReadTimeout"
        assert llm_stats()["read_timeouts"] == before_read + 1
        assert llm_stats()["timeouts"] == before_timeouts + 1
        logged = "\n".join(r.getMessage() for r in caplog.records)
        for marker in (
            "reason=ReadTimeout", "provider=primary.example", "model=m",
            "channel=chat", "module=checkup", "step=tool", "attempt=1/1",
            "elapsed_ms=", "effective_timeout=", "effective_budget=",
            "timeout_source=settings", "budget_source=settings",
            "request_chars=", "tools_count=0", "streaming=False",
        ):
            assert marker in logged, marker
        assert "test-key" not in logged

    @pytest.mark.asyncio
    async def test_request_ok_log_fields(self, hot_cache, monkeypatch, caplog):
        hot_cache.data.update({"models.llm_timeout": 180.0,
                               "models.llm_total_budget": 360.0})
        calls = []
        client = _make_client(_ok_handler(calls), monkeypatch)
        payload = {"model": "model-hot", "messages": [
            {"role": "user", "content": "secret-prompt"}], "tools": [
                {"type": "function", "function": {"name": "x"}}]}
        with caplog.at_level(logging.INFO, logger=lc.__name__):
            await client._post("/chat/completions", payload,
                               module="direct_chat", step="reply")
        logged = "\n".join(r.getMessage() for r in caplog.records
                           if "LLM request OK" in r.getMessage())
        for marker in (
            "provider=primary.example", "model=model-hot", "channel=chat",
            "module=direct_chat", "step=reply", "attempt=1/3",
            "elapsed_ms=", "effective_timeout=180.0",
            "effective_budget=360.0", "timeout_source=pg",
            "budget_source=pg", "request_chars=", "tools_count=1",
            "streaming=False", "finish_reason=stop",
        ):
            assert marker in logged, marker
        assert "secret-prompt" not in logged
        assert "test-key" not in logged

    @pytest.mark.asyncio
    async def test_budget_exhausted_branch_metric(self, hot_cache, monkeypatch,
                                                  caplog):
        """Попытка не стартует (время бюджета исчерпано) → budget_exhausted."""
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={"e": 1}, request=request)

        client = _make_client(handler, monkeypatch)
        client.backoff_base = 0          # сон 0, но время «прошло»
        ticks = iter([0.0, 2.0, 4.0, 8.0, 16.0])

        from types import SimpleNamespace
        before = llm_stats()["budget_exhausted"]
        # Патчим ТОЛЬКО модульный `time` llm_client: event loop/таймауты
        # asyncio не затронуты; проверяем именно ветку «попытка не стартует».
        monkeypatch.setattr(lc, "time",
                            SimpleNamespace(monotonic=lambda: next(ticks)))
        with caplog.at_level(logging.ERROR, logger=lc.__name__):
            with pytest.raises(LLMTimeoutError) as raised:
                await client._post("/chat/completions", {"model": "m"},
                                   budget=1.0, max_retries=3)
        assert raised.value.cause_class == "budget"
        assert llm_stats()["budget_exhausted"] == before + 1
        assert "budget_exhausted" in "\n".join(
            r.getMessage() for r in caplog.records)

    def test_stats_shape_includes_new_counters(self):
        stats = llm_stats()
        assert {"requests", "timeouts", "fallbacks", "budget_exhausted",
                "read_timeouts", "timeout_share"} <= set(stats)
        assert isinstance(stats["budget_exhausted"], int)
        assert isinstance(stats["read_timeouts"], int)


# ── F. Статический контракт админки (Playwright — tools/ui_p0_llm_guard_e2e) ─
class TestAdminContract:
    def test_llm_guard_is_visible_policy_group(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        js = (root / "web" / "app.js").read_text(encoding="utf-8")
        policy_at = js.index("id: 'prov_policy'")
        text_at = js.index("id: 'prov_text'")
        assert policy_at < text_at
        assert "title: 'Время ответа и защита'" in js
        guard_at = js.index("id: 'llm_guard'")
        guard = js[guard_at:js.index("id: 'search_keys'")]
        assert "zone: 'advanced'" not in guard
        assert "label: 'Таймаут одного запроса, сек'" in guard
        assert "label: 'Повторов при сбое'" in guard
        assert "label: 'Предел одной основной попытки, сек'" in guard
        assert "без перезапуска" in guard
        assert "не ограничивает всё исследование" in guard

    def test_advanced_still_for_backoff_cb_technical(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        js = (root / "web" / "app.js").read_text(encoding="utf-8")
        # advanced-зона сохранена для технических блоков; backoff/CB остаются
        # generic-параметрами каталога (LLM_RETRY_*/LLM_CB_*), не в guard-блоке.
        assert "id: 'search_keys'" in js and "zone: 'advanced'" in js
        assert "id: 'media_share'" in js
        guard_at = js.index("id: 'llm_guard'")
        guard = js[guard_at:js.index("id: 'search_keys'")]
        assert "llm_retry_backoff" not in guard.lower()
        assert "llm_cb_" not in guard.lower()

    def test_transport_policy_reads_only_declared_keys(self):
        """Нет adaptive per-model/provider: политика читает ровно объявленные
        ключи транспорта, без перцентилей/истории латентности (до p95)."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        source = (root / "services" / "llm_client.py").read_text(
            encoding="utf-8")
        start = source.index("def _refresh_transport_policy")
        end = source.index("def _effective_timeout", start)
        block = source[start:end]
        keys = set(re.findall(r'hot\.get\(\s*"([^"]+)"', block))
        assert keys == {
            "models.llm_timeout",
            "models.llm_total_budget",
            "models.llm_max_retries",
            "models.llm_retry_backoff_base",
            "models.llm_retry_backoff_cap",
            "models.llm_retry_jitter_max",
            "models.llm_fallback_timeout_seconds",
            "models.llm_fallback_max_retries",
        }
        assert "latency" not in block.lower()
        assert "percentile" not in block.lower()


# ── G. Реальный потребитель F1: POST /api/speech/try ───────────────────────
class TestSpeechTryConsumer:
    @pytest.mark.asyncio
    async def test_explicit_try_model_reaches_provider(self, hot_cache,
                                                      monkeypatch):
        """F1: явный ``TryRequest.chat_model`` («Попробовать» в речи) идёт в
        payload провайдера, даже когда глобальная hot-модель другая.

        Регресс: раньше hot-apply на входе ``generate`` молча подменял
        constructor-level модель на ``models.llm_model_name``.

        Примечание: ``_generate_variants`` содержит ПРЕДСУЩЕСТВУЮЩИЙ баг вне
        скоупа слайса — ``from config import settings`` даёт модуль
        ``config.settings`` (пустой ``config/__init__.py``), а не инстанс, и
        ``settings.LLM_BASE_URL`` падает в ``client_unavailable``. Тест
        подставляет инстанс в пакет, чтобы проверить именно транспортный шов
        выбора модели; сам баг зафиксирован отдельно и здесь не чинится.
        """
        import config as config_pkg
        from config.settings import settings as settings_instance

        calls = []
        transport = httpx.MockTransport(_ok_handler(calls))
        original = httpx.AsyncClient

        def factory(**kw):
            return original(transport=transport, **kw)

        monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
        monkeypatch.setattr(config_pkg, "settings", settings_instance,
                            raising=False)
        hot_cache.data.update({
            "models.llm_model_name": "global-hot-model",
            "models.llm_base_url": "https://hot.example/v1",
            "keys.llm_api_key": "test-key",
        })
        from web.api.speech import TryRequest, _generate_variants

        body = TryRequest(text="привет", generate=True,
                          chat_model="owner-picked-model")
        out = await _generate_variants(
            {"system_masked": "system prompt"}, None, body, None)
        assert out["ok"] is True
        assert len(calls) == 1
        payload = json.loads(calls[0].content)
        assert payload["model"] == "owner-picked-model"
        assert str(calls[0].url) == "https://hot.example/v1/chat/completions"
