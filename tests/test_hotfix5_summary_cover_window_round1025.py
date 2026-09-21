"""Хотфикс-5 (round10.25) — окно/ретраи генерации обложки, наблюдаемость,
отдельный бюджет изображений и int-chat_id в планировщике.

Падают на старом коде:
  * окно попытки было 90 c без ретраев → таймаут провайдера терял обложку;
  * `image unavailable` логировался на INFO без класса причины/провайдера;
  * `image_calls` реюзал `limits.worker_daily_llm_calls_*` (обложка конкурировала
    с LLM-лимитом чата);
  * `summary_scheduler._tick` передавал `chat_id` из PG как есть (строкой) →
    per-chat override «Стиля обложки» не резолвился.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config.settings import Settings, settings
from services import image_generation as ig
from services import summary_generator as sg
from services import worker_budget
from services.summary_generator import SummaryGenerator
from services.summary_scheduler import SummarySchedulerService

pytestmark = pytest.mark.system2


class _Rec:
    def __init__(self):
        self.rich = []
        self.plain = []


def _patch_rich(monkeypatch, rec):
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
    monkeypatch.setattr(sg, "build_cover_media",
                        lambda path, **kw: {"stub_path": path})

    async def _send(bot, chat_id, text, *, media=None, cover_id=None, **kw):
        rec.rich.append({"media": media, "cover_id": cover_id, "text": text})

    monkeypatch.setattr(sg, "send_rich_message", _send)

    async def _plain(self, chat_id, text):
        rec.plain.append(text)

    monkeypatch.setattr(SummaryGenerator, "_plain_fallback", _plain)
    monkeypatch.setattr(SummaryGenerator, "_resolve_cover_style_text",
                        AsyncMock(return_value="owner style"))


def _make_gen():
    return SummaryGenerator(MagicMock(), MagicMock(), MagicMock(), MagicMock(),
                            concurrency_pool=MagicMock())


# ── A. Окно/ретраи (a/b) ─────────────────────────────────────────────────

class TestCoverRetryWindow:
    @pytest.mark.asyncio
    async def test_timeout_first_attempt_then_success_rich(
            self, monkeypatch, caplog):
        """(а) таймаут первой попытки → вторая успешна → rich+обложка."""
        rec = _Rec()
        _patch_rich(monkeypatch, rec)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        monkeypatch.setattr(
            Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS", 0.0)
        calls = {"n": 0}
        seen = {}

        async def fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                timeout=None, consume_budget=True,
                                retry=True):
            calls["n"] += 1
            seen.setdefault("retry", retry)
            if calls["n"] == 1:
                return ig.GenerationResult(ok=False, reason="timeout")
            return ig.GenerationResult(ok=True, content=b"\xff\xd8jpeg")

        monkeypatch.setattr(ig, "generate", fake_generate)

        with caplog.at_level(logging.WARNING, logger=ig.__name__):
            await _make_gen()._deliver_rich(-100, "текст", "a lone cat")

        assert calls["n"] == 2                    # ровно 2 попытки
        assert seen["retry"] is False             # внутренний HTTP-ретрай off
        assert len(rec.rich) == 1                 # rich доставлен
        assert rec.plain == []                    # текст не ушёл plain
        assert rec.rich[0]["media"]
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "attempt=1/2" in joined
        assert "reason_class=timeout" in joined

    @pytest.mark.asyncio
    async def test_exhausted_attempts_plain_with_warning(
            self, monkeypatch, caplog):
        """(б) исчерпание попыток → plain + WARNING с классом причины."""
        rec = _Rec()
        _patch_rich(monkeypatch, rec)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        monkeypatch.setattr(
            Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS", 0.0)
        calls = {"n": 0}

        async def fake_generate(prompt, **kw):
            calls["n"] += 1
            return ig.GenerationResult(ok=False, reason="timeout")

        monkeypatch.setattr(ig, "generate", fake_generate)

        with caplog.at_level(logging.WARNING):
            await _make_gen()._deliver_rich(-100, "текст", "a lone cat")

        assert calls["n"] == 2
        assert rec.rich == []                     # обложки нет
        assert rec.plain and "текст" in rec.plain[0]   # текст не потерян
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason_class=timeout" in joined
        assert "attempt=1/2" in joined and "attempt=2/2" in joined
        assert "image unavailable" in joined

    @pytest.mark.asyncio
    async def test_deterministic_failure_single_attempt(
            self, monkeypatch, caplog):
        """(1) детерминированный отказ (unauthorized) → ровно 1 попытка."""
        rec = _Rec()
        _patch_rich(monkeypatch, rec)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        monkeypatch.setattr(
            Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS", 0.0)
        calls = {"n": 0}

        async def fake_generate(prompt, **kw):
            calls["n"] += 1
            return ig.GenerationResult(ok=False, reason="unauthorized")

        monkeypatch.setattr(ig, "generate", fake_generate)

        with caplog.at_level(logging.WARNING):
            await _make_gen()._deliver_rich(-100, "текст", "a lone cat")

        assert calls["n"] == 1                    # без повторов
        assert rec.rich == [] and rec.plain
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "attempt=1/2" in joined
        assert "reason_class=http_401" in joined
        assert "attempt=2/2" not in joined

    @pytest.mark.asyncio
    async def test_http_reason_class_in_warning(self, monkeypatch, caplog):
        rec = _Rec()
        _patch_rich(monkeypatch, rec)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        monkeypatch.setattr(
            Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS", 0.0)

        async def fake_generate(prompt, **kw):
            return ig.GenerationResult(ok=False, reason="unauthorized")

        monkeypatch.setattr(ig, "generate", fake_generate)

        with caplog.at_level(logging.WARNING):
            await _make_gen()._deliver_rich(-100, "текст", "a lone cat")

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason_class=http_401" in joined
        assert "provider=" in joined

    @pytest.mark.asyncio
    async def test_budget_short_circuits_without_http(self, monkeypatch):
        """reason=budget → сразу plain, без сетевых попыток."""
        rec = _Rec()
        _patch_rich(monkeypatch, rec)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=False))
        calls = {"n": 0}

        async def fake_generate(prompt, **kw):
            calls["n"] += 1
            return ig.GenerationResult(ok=True, content=b"x")

        monkeypatch.setattr(ig, "generate", fake_generate)

        await _make_gen()._deliver_rich(-100, "текст", "a lone cat")
        assert calls["n"] == 0
        assert rec.rich == [] and rec.plain


class TestReasonClassTaxonomy:
    def test_mapping(self):
        assert ig.reason_class("timeout") == "timeout"
        assert ig.reason_class("network") == "network"
        assert ig.reason_class("budget") == "budget"
        assert ig.reason_class("bad_json") == "bad_json"
        assert ig.reason_class("bad_b64") == "bad_json"
        assert ig.reason_class("bad_request") == "http_400"
        assert ig.reason_class("unauthorized") == "http_401"
        assert ig.reason_class("http_500") == "http_500"
        assert ig.reason_class("download_rate_limited") == "http_429"
        # item 4: явные классы вместо безликого `error`/ложного `bad_json`
        assert ig.reason_class("no_url") == "bad_response"
        assert ig.reason_class("no_image") == "bad_response"
        assert ig.reason_class("empty") == "empty"
        assert ig.reason_class("empty_prompt") == "empty"
        assert ig.reason_class("too_large") == "too_large"
        assert ig.reason_class("temp_write_failed") == "local"
        assert ig.reason_class("weird") == "error"

    def test_transient_predicate(self):
        """(1) транзиентные повторяемы; детерминированные — нет."""
        for transient in ("timeout", "network", "unreachable",
                          "rate_limited", "bad_gateway", "unavailable",
                          "http_504", "download_unavailable"):
            assert ig.is_transient_reason(transient) is True, transient
        for deterministic in ("unauthorized", "bad_request", "forbidden",
                              "payment_required", "bad_json", "too_large",
                              "budget", "empty", "error"):
            assert ig.is_transient_reason(deterministic) is False, \
                deterministic


class TestGenerateTimeoutClass:
    @pytest.mark.asyncio
    async def test_timeout_maps_to_timeout_reason(self, monkeypatch):
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))

        async def boom(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            raise httpx.ReadTimeout("slow provider")

        monkeypatch.setattr(ig, "_http_request", boom)
        res = await ig.generate("кот", chat_id=1)
        assert res.ok is False and res.reason == "timeout"

    @pytest.mark.asyncio
    async def test_attempt_timeout_is_forwarded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        seen = {}

        async def fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                timeout=None, consume_budget=True,
                                retry=True):
            seen["timeout"] = timeout
            return ig.GenerationResult(ok=True, content=b"\xff")

        monkeypatch.setattr(ig, "generate", fake_generate)
        monkeypatch.setattr(
            Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS", 0.0)
        path, reason = await ig.generate_image_verbose("кот", chat_id=1)
        try:
            assert reason == "ok" and path
            assert seen["timeout"] == 180.0
        finally:
            if path:
                import os
                os.remove(path)

    @pytest.mark.asyncio
    async def test_attempt_bounded_by_window_deadline(self, monkeypatch):
        """Review iter1 (item 1): «одна попытка ≤ окно» — реальный дедлайн
        покрывает POST+скачивание; суммарно ≤ attempts×окно + backoff.

        Старо (без `wait_for`) две «зависшие» попытки шли бы ~10 c."""
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        monkeypatch.setattr(Settings, "IMAGE_ATTEMPT_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_MAX_ATTEMPTS", 2)
        monkeypatch.setattr(
            Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS", 0.0)
        calls = {"n": 0}

        async def never_returns(prompt, **kw):
            calls["n"] += 1
            await asyncio.sleep(5.0)          # «зависший» провайдер
            return ig.GenerationResult(ok=True, content=b"x")

        monkeypatch.setattr(ig, "generate", never_returns)
        started = time.monotonic()
        path, reason = await ig.generate_image_verbose("кот", chat_id=1)
        elapsed = time.monotonic() - started

        assert path is None and reason == "timeout"
        assert calls["n"] == 2                # обе попытки стартовали
        assert elapsed < 0.2 * 2 + 0.5        # дедлайн каждой попытки сработал


# ── B. Бюджет изображений (c) ────────────────────────────────────────────

class _FakeConn:
    def __init__(self):
        self.rows = {}

    async def fetchrow(self, sql, *args):
        key = (args[1], args[2])
        self.rows[key] = self.rows.get(key, 0) + int(args[3])
        return {"used": self.rows[key]}


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


class _FakePg:
    def __init__(self):
        self.conn = _FakeConn()
        self.pool = _FakePool(self.conn)


class TestImageBudgetIsolation:
    @pytest.mark.asyncio
    async def test_image_limit_is_separate_from_llm(self, monkeypatch):
        monkeypatch.setattr(Settings, "WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 5)
        monkeypatch.setattr(Settings, "WORKER_DAILY_IMAGE_CALLS_GLOBAL", 9)
        assert await worker_budget._metric_limit(
            "chat:-100", worker_budget.METRIC_IMAGE_CALLS) == 5
        assert await worker_budget._metric_limit(
            "global", worker_budget.METRIC_IMAGE_CALLS) == 9
        # llm_calls — прежний каталоговый контур (settings-инстанс, не env-only)
        assert await worker_budget._metric_limit(
            "chat:-100", worker_budget.METRIC_CALLS) == \
            settings.WORKER_DAILY_LLM_CALLS_PER_CHAT

    @pytest.mark.asyncio
    async def test_image_consume_allowed_when_llm_exhausted(
            self, monkeypatch):
        """LLM-лимит чата исчерпан (`0` = запрет), но image-ветка отдельная."""
        monkeypatch.setattr(Settings, "WORKER_DAILY_LLM_CALLS_PER_CHAT", 0)
        monkeypatch.setattr(Settings, "WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 3)
        resolve = AsyncMock(return_value=0)
        monkeypatch.setattr(worker_budget, "_resolve_limit", resolve)
        pg = _FakePg()
        allowed = await worker_budget.consume(
            pg, "chat:-100", worker_budget.METRIC_IMAGE_CALLS, 1)
        assert allowed is True
        resolve.assert_not_awaited()             # каталоговый LLM-лимит не трогаем

    @pytest.mark.asyncio
    async def test_global_image_limit_blocks(self, monkeypatch):
        """(2) global-лимит `image_calls` РЕАЛЬНО enforced (не декор)."""
        monkeypatch.setattr(Settings, "WORKER_DAILY_IMAGE_CALLS_GLOBAL", 2)
        monkeypatch.setattr(Settings, "WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 5)
        pg = _FakePg()
        assert await worker_budget.consume(
            pg, "global", worker_budget.METRIC_IMAGE_CALLS, 1) is True
        assert await worker_budget.consume(
            pg, "global", worker_budget.METRIC_IMAGE_CALLS, 1) is True
        assert await worker_budget.consume(
            pg, "global", worker_budget.METRIC_IMAGE_CALLS, 1) is False

    @pytest.mark.asyncio
    async def test_consume_budget_spends_global_and_per_chat(self, monkeypatch):
        """(2) `_consume_budget` списывает ОБА контура; при отказе global
        per-chat не тратится."""
        seen = []

        async def fake_consume(pg, scope, metric, amount=1):
            seen.append(scope)
            return scope != "global"            # global исчерпан → False

        monkeypatch.setattr(worker_budget, "consume", fake_consume)
        assert await ig._consume_budget(7) is False
        assert seen == ["global"]               # до per-chat не дошли

        seen.clear()

        async def fake_consume_ok(pg, scope, metric, amount=1):
            seen.append(scope)
            return True

        monkeypatch.setattr(worker_budget, "consume", fake_consume_ok)
        assert await ig._consume_budget(7) is True
        assert seen == ["global", "chat:7"]


# ── C. Планировщик: int chat_id (d) ──────────────────────────────────────

class TestSchedulerChatIdType:
    @pytest.mark.asyncio
    async def test_string_chat_id_cast_to_int(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=["-100", -200])
        service = SummarySchedulerService(generator, db)
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=None)
        with patch("services.summary_scheduler.settings", mod):
            await service._tick()
        calls = [c.args[0] for c in generator.generate_and_send.await_args_list]
        assert calls == [-100, -200]
        assert all(isinstance(c, int) for c in calls)

    @pytest.mark.asyncio
    async def test_invalid_and_null_skipped(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(
            return_value=["abc", None, "", -100])
        service = SummarySchedulerService(generator, db)
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=None)
        with patch("services.summary_scheduler.settings", mod):
            await service._tick()
        generator.generate_and_send.assert_awaited_once_with(-100)

    @pytest.mark.asyncio
    async def test_int_chat_id_resolves_per_chat_style(self, monkeypatch):
        """int chat_id — ключ per-chat override «Стиля обложки» (T-2509)."""
        from services import chat_params
        resolved = {}

        async def fake_get(chat_id, key, default=None):
            resolved["chat_id"] = chat_id
            return "OWNER STYLE"

        monkeypatch.setattr(chat_params, "get_chat_param", fake_get)
        generator = MagicMock()

        async def _send(chat_id, manual=False, focus=None):
            gen = _make_gen()
            resolved["style"] = await gen._resolve_cover_style_text(chat_id)

        generator.generate_and_send = AsyncMock(side_effect=_send)
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=["-100"])
        service = SummarySchedulerService(generator, db)
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=None)
        with patch("services.summary_scheduler.settings", mod):
            await service._tick()

        assert isinstance(resolved["chat_id"], int)
        assert resolved["chat_id"] == -100
        assert resolved["style"] == "OWNER STYLE"


# ── D. Дефолты (e) ───────────────────────────────────────────────────────

class TestDefaults:
    def test_env_only_defaults(self):
        s = Settings()
        assert s.IMAGE_ATTEMPT_TIMEOUT_SECONDS == 180.0
        assert s.IMAGE_GENERATION_MAX_ATTEMPTS == 2
        assert s.IMAGE_GENERATION_RETRY_BACKOFF_SECONDS == 2.0
        assert s.WORKER_DAILY_IMAGE_CALLS_PER_CHAT == 60
        assert s.WORKER_DAILY_IMAGE_CALLS_GLOBAL == 200
        # прежние таймауты изображений не тронуты
        assert s.IMAGE_REQUEST_TIMEOUT_SECONDS == 90.0

    def test_resolvers(self, monkeypatch):
        assert ig._image_attempt_timeout() == 180.0
        assert ig._image_max_attempts() == 2
        assert ig._image_retry_backoff() == 2.0
        # нижние клампы (item 3)
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_MAX_ATTEMPTS", 0)
        assert ig._image_max_attempts() == 1
        monkeypatch.setattr(Settings, "IMAGE_ATTEMPT_TIMEOUT_SECONDS", 0.0)
        assert ig._image_attempt_timeout() == 180.0
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS",
                            -5.0)
        assert ig._image_retry_backoff() == 0.0
        # верхние клампы (item 3)
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_MAX_ATTEMPTS", 99)
        assert ig._image_max_attempts() == 5
        monkeypatch.setattr(Settings, "IMAGE_ATTEMPT_TIMEOUT_SECONDS", 9999.0)
        assert ig._image_attempt_timeout() == 600.0
        monkeypatch.setattr(Settings, "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS",
                            9999.0)
        assert ig._image_retry_backoff() == 30.0

    def test_new_keys_not_in_param_catalog(self):
        """Δ каталога = 0: новые env-only ключи отсутствуют в param_catalog."""
        from services import param_catalog
        for key in ("IMAGE_ATTEMPT_TIMEOUT_SECONDS",
                    "IMAGE_GENERATION_MAX_ATTEMPTS",
                    "IMAGE_GENERATION_RETRY_BACKOFF_SECONDS",
                    "WORKER_DAILY_IMAGE_CALLS_PER_CHAT",
                    "WORKER_DAILY_IMAGE_CALLS_GLOBAL"):
            assert param_catalog.get(key) is None
