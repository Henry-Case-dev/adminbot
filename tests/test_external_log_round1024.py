"""Раунд 10.24 (F2, ADR-1024-1) — единый R17-safe лог внешних API/пайплайнов.

Покрытие T-2202: (a) маскирование секретов и лимит длины; (b) egress-сканер
лог-записей не находит запрещённых токенов; (c) сбой каждой подсистемы
(image/cron/extractor/graph) оставляет запись с причиной; (d/f) уровни и
«никогда не бросает/без сети»; (g) kill-switch убирает тело/URL.

Тесты не ходят в сеть: `httpx`/`_http_request` подменяются заглушками.
"""
from __future__ import annotations

import logging
import re

import pytest
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import services.log_ring as log_ring
from config.settings import Settings
from services import anticliche_worker as aw
from services import bot_persona
from services import dream_worker as dw
from services import external_log as el
from services import image_generation as ig
from services import summary_memory as sm
from services.dream_worker import DreamWorker


# ── заглушки ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, text="", json_data=None, headers=None,
                 content=b""):
        self.status_code = status
        self.text = text
        self._json = json_data
        self.headers = headers or {}
        self.content = content

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


def _find(caplog, needle: str) -> list[str]:
    return [m for m in _messages(caplog) if needle in m]


# ── (a) helper: маскирование и усечение ─────────────────────────────────────

class TestHelperMasking:
    def test_safe_text_masks_secret_tokens(self):
        text = ("Authorization: Bearer abcdefghijklmnop "
                "sk-ZZZZZZ999999 gsk_XYZ789000 or-QQQQQQ1234")
        out = el.safe_text(text)
        assert "abcdefghijklmnop" not in out
        assert "sk-ZZZZZZ999999" not in out
        assert "gsk_XYZ789000" not in out
        assert "or-QQQQQQ1234" not in out
        assert el.REDACTED in out

    def test_safe_text_masks_uri_creds(self):
        out = el.safe_text("https://user:secretpw@host/path")
        assert "secretpw" not in out
        assert "://***@host/path" in out

    def test_safe_text_truncates_to_limit(self, monkeypatch):
        monkeypatch.setattr(Settings, "EXTERNAL_API_LOG_BODY_CHARS", 20)
        out = el.safe_text("x" * 100)
        assert len(out) <= 20

    def test_safe_text_idempotent(self, monkeypatch):
        monkeypatch.setattr(Settings, "EXTERNAL_API_LOG_BODY_CHARS", 1024)
        once = el.safe_text("Bearer abcdefghijklmnop")
        assert el.safe_text(once) == once

    def test_redact_url_drops_query_and_userinfo(self):
        assert el.redact_url(
            "https://u:p@host/v1?key=sk-ZZZZZZ999&model=flux"
        ) == "https://host/v1"

    def test_redact_url_keep_query_masks_secret_params(self):
        out = el.redact_url("https://host/v1?key=abc&model=flux",
                            keep_query=True)
        assert "key=***" in out
        assert "model=flux" in out
        assert "abc" not in out

    def test_redact_url_ipv6_keeps_brackets(self):
        out = el.redact_url("https://[::1]:8443/path?x=1")
        assert out == "https://[::1]:8443/path"


# R1024F2-03: литеральный секрет каталога (spec §6a). Значение секрета —
# синтетическое, реальные ключи не цитируются (R18). `Settings` — frozen
# dataclass, поэтому подменяем settings-подобный объект в `_collect_secrets`.
class TestLiteralCatalogSecret:
    @pytest.fixture
    def reset_secret_cache(self):
        log_ring._SECRETS = None
        yield
        log_ring._SECRETS = None

    def _patch_catalog_secret(self, monkeypatch, secret):
        import types

        monkeypatch.setattr("config.settings.settings",
                            types.SimpleNamespace(IMAGE_API_KEY=secret))
        log_ring._SECRETS = None      # сбросить кэш → перечитать каталог

    def test_literal_catalog_secret_masked(self, monkeypatch,
                                           reset_secret_cache):
        secret = "SENTINEL-CATALOG-SECRET-9f3a11"
        self._patch_catalog_secret(monkeypatch, secret)
        out = el.safe_text(f"provider_key={secret} trailing")
        assert secret not in out
        assert el.REDACTED in out

    def test_literal_catalog_secret_masked_in_body(self, monkeypatch,
                                                    reset_secret_cache, caplog):
        secret = "SENTINEL-CATALOG-SECRET-9f3a11"
        self._patch_catalog_secret(monkeypatch, secret)
        with caplog.at_level(logging.INFO):
            el.log_external_api(
                logging.getLogger("t"), provider="p", status=400,
                reason="bad_request", body=f'{{"key":"{secret}"}}')
        assert secret not in "\n".join(_messages(caplog))


# ── (d/f) helper: уровни и «никогда не бросает» ─────────────────────────────

class TestHelperRobustness:
    def test_never_raises_on_garbage(self):
        class _Boom:
            def __str__(self):
                raise RuntimeError("boom")

        assert el.safe_text(None) == ""
        assert el.safe_text(_Boom()) == ""
        assert el.redact_url(None) == ""
        # logger=None и битый вход не бросают
        el.log_external_api(None, provider="p", body="b")
        el.trace_step(None, component="c", step="s", status="ok")
        el.log_dropped(None, component="c", reason="r")

    def test_levels(self, caplog):
        logger = logging.getLogger("test.extlog.levels")
        with caplog.at_level(logging.DEBUG):
            el.log_external_api(logger, provider="p", status=200)
            el.trace_step(logger, component="c", step="s", status="ok")
            el.trace_step(logger, component="c", step="s", status="skip")
            el.trace_step(logger, component="c", step="s", status="empty")
            el.trace_step(logger, component="c", step="s", status="duplicate")
            el.trace_step(logger, component="c", step="s", status="bogus")
            el.trace_step(logger, component="c", step="s", status="error")
            el.trace_step(logger, component="c", step="s", status="dropped")
            el.log_dropped(logger, component="c", reason="r", count=2)
        levels = [r.levelno for r in caplog.records]
        assert levels[0] == logging.INFO
        assert levels[1:5] == [logging.INFO] * 4
        assert levels[5] == logging.WARNING
        assert levels[6] == logging.ERROR
        assert levels[7] == logging.ERROR
        assert levels[8] == logging.ERROR

    def test_log_dropped_counts(self, caplog):
        with caplog.at_level(logging.ERROR):
            el.log_dropped(logging.getLogger("t"), component="graph",
                           reason="batch_kept", count=3, chat_id=7)
        msg = _find(caplog, "event=dropped_metric")[0]
        assert "count=3" in msg and "chat_id=7" in msg


class TestOptionalEventKey:
    """Раунд 10.24 F1 (ADR-1024-6 D4): опциональный `event` в хелперах.

    Default (`event=None`) остаётся байт-в-байт (F2); явный event печатается
    как согласованный ключ алерта (`event=graph_extract_*`)."""

    def test_default_events_unchanged(self, caplog):
        with caplog.at_level(logging.INFO):
            el.trace_step(logging.getLogger("t"), component="c", step="s",
                          status="ok")
            el.log_dropped(logging.getLogger("t"), component="c", reason="r")
        assert _find(caplog, "event=pipeline_step")
        assert _find(caplog, "event=dropped_metric")

    def test_custom_event_key_emitted(self, caplog):
        with caplog.at_level(logging.INFO):
            el.trace_step(logging.getLogger("t"), component="graph",
                          step="extract", status="partial",
                          reason="graph_extract_partial",
                          event="graph_extract_partial")
            el.trace_step(logging.getLogger("t"), component="graph",
                          step="extract", status="error",
                          reason="graph_extract_failed",
                          event="graph_extract_failed")
            el.log_dropped(logging.getLogger("t"), component="graph",
                           reason="graph_extract_dropped",
                           event="graph_extract_dropped")
        assert "event=graph_extract_partial" in caplog.text
        assert "event=graph_extract_failed" in caplog.text
        assert "event=graph_extract_dropped" in caplog.text
        # прежние ключи НЕ печатаются при явном event
        assert "event=pipeline_step" not in caplog.text
        assert "event=dropped_metric" not in caplog.text


# ── (g) kill-switch ─────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_off_hides_url_and_body(self, monkeypatch, caplog):
        monkeypatch.setattr(Settings, "EXTERNAL_API_LOGGING_ENABLED", False)
        with caplog.at_level(logging.INFO):
            el.log_external_api(
                logging.getLogger("t"), provider="pollinations", method="POST",
                url="https://host/v1?key=k", body="BODY-SENTINEL",
                status=400, reason="bad_request")
        msg = _find(caplog, "event=ext_api")[0]
        assert "status=400" in msg and "reason=bad_request" in msg
        assert "BODY-SENTINEL" not in msg
        assert "https://host/v1" not in msg

    def test_on_prints_url_body(self, monkeypatch, caplog):
        monkeypatch.setattr(Settings, "EXTERNAL_API_LOGGING_ENABLED", True)
        monkeypatch.setattr(Settings, "EXTERNAL_API_LOG_URL_QUERY", False)
        with caplog.at_level(logging.INFO):
            el.log_external_api(
                logging.getLogger("t"), provider="pollinations", method="POST",
                url="https://host/v1/images/generations?key=sk-ZZZZZZ999",
                body='{"error": "bad model"}', status=400,
                reason="bad_request")
        msg = _find(caplog, "event=ext_api")[0]
        assert "url=https://host/v1/images/generations" in msg
        assert "?key" not in msg
        assert "bad model" in msg


# ── (b) egress: тело с секретом не утекает ──────────────────────────────────

class TestEgressMasking:
    def test_body_secret_not_in_log(self, caplog):
        token = "sk-EGRESSZZZ999888777666"
        with caplog.at_level(logging.INFO):
            el.log_external_api(
                logging.getLogger("t"), provider="p", method="POST",
                status=401, reason="unauthorized",
                body='{"error":"invalid key: %s", "auth":"Bearer abcdefghijklmnop"}' % token)
        joined = "\n".join(_messages(caplog))
        assert token not in joined
        assert "abcdefghijklmnop" not in joined


# ── (c/e) image-провайдер ───────────────────────────────────────────────────

class TestImageFailureLogging:
    def _gen(self, monkeypatch, resp, *, get_mode=False):
        async def fake(method, url, *, json_body=None, headers=None, timeout=90.0):
            return resp

        monkeypatch.setattr(ig, "_http_request", fake)
        monkeypatch.setattr(ig, "_consume_budget", AsyncMock(return_value=True))
        monkeypatch.setattr(
            ig.hot, "get",
            lambda key, default=None: get_mode if key == ig.KEY_GET_MODE
            else default)
        return ig.generate("кот", chat_id=1)

    @pytest.mark.asyncio
    async def test_post_error_logs_status_body_reason(self, monkeypatch, caplog):
        resp = _Resp(400, text='{"error":"unsupported response_format"}',
                     headers={})
        with caplog.at_level(logging.INFO):
            result = await self._gen(monkeypatch, resp)
        assert result.ok is False and result.reason == "bad_request"
        ext = _find(caplog, "event=ext_api")
        assert any("status=400" in m and "reason=bad_request" in m
                   and "unsupported response_format" in m for m in ext)
        assert any(r.levelno == logging.ERROR for r in caplog.records
                   if "event=ext_api" in r.getMessage())

    @pytest.mark.asyncio
    async def test_get_url_does_not_leak_prompt(self, monkeypatch, caplog):
        resp = _Resp(500, text="upstream down", headers={})
        with caplog.at_level(logging.INFO):
            await self._gen(monkeypatch, resp, get_mode=True)
        assert not any("кот" in m for m in _messages(caplog))

    @pytest.mark.asyncio
    async def test_get_retry_does_not_leak_prompt(self, monkeypatch, caplog):
        """R1024F2-01: ретрай GET не пишет промпт из path в лог."""
        prompt = "кот-секрет-промпт"
        responses = [
            _Resp(429, text="rate limited", headers={"Retry-After": "0"}),
            _Resp(200, content=b"img-bytes", headers={}),
        ]
        calls: list[str] = []

        async def fake(method, url, *, json_body=None, headers=None,
                       timeout=90.0):
            calls.append(url)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        monkeypatch.setattr(ig, "_http_request", fake)
        with caplog.at_level(logging.INFO):
            content = await ig._generate_get(
                "https://image.pollinations.ai", "flux", prompt, 5.0, 1000)
        assert content == b"img-bytes"
        joined = "\n".join(_messages(caplog))
        assert prompt not in joined
        assert quote(prompt, safe="") not in joined
        retry = [m for m in _messages(caplog) if "reason=retry" in m]
        assert retry
        assert "url=https://image.pollinations.ai/image" in retry[0]
        # R1024F2-05: провайдер распознан, а не деградировал до "image".
        assert "provider=image.pollinations.ai" in retry[0]

    def test_provider_from_scheme_less_host(self):
        assert ig._provider_from_url(
            "image.pollinations.ai") == "image.pollinations.ai"
        assert ig._provider_from_url(
            "https://image.pollinations.ai/v1") == "image.pollinations.ai"


# ── (c) анти-клише крон ─────────────────────────────────────────────────────

class TestAnticlicheFailureLogging:
    @pytest.mark.asyncio
    async def test_refresh_fetch_error_has_phase(self, monkeypatch, caplog):
        monkeypatch.setattr(aw.anticliche_cache, "enabled", lambda: True)
        monkeypatch.setattr(aw.anticliche_cache, "mark_status", AsyncMock())
        worker = aw.AntiClicheWorker(
            llm=None, pg=object(),
            fetch=AsyncMock(side_effect=RuntimeError("boom")))
        with caplog.at_level(logging.INFO):
            result = await worker.refresh()
        assert result["status"] == "fetch_error"
        trace = _find(caplog, "event=pipeline_step")
        assert any("component=anticliche" in m and "step=fetch" in m
                   and "reason=fetch_error" in m for m in trace)
        assert any(r.levelno == logging.ERROR for r in caplog.records
                   if "step=fetch" in r.getMessage())

    @pytest.mark.asyncio
    async def test_refresh_parse_error_phase(self, monkeypatch, caplog):
        monkeypatch.setattr(aw.anticliche_cache, "enabled", lambda: True)
        monkeypatch.setattr(aw.anticliche_cache, "mark_status", AsyncMock())
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        llm = MagicMock()
        llm.generate_worker = AsyncMock(return_value="не json вообще")
        worker = aw.AntiClicheWorker(
            llm=llm, pg=object(), fetch=AsyncMock(return_value="text"))
        with caplog.at_level(logging.INFO):
            result = await worker.refresh()
        assert result["status"] == "parse_error"
        trace = _find(caplog, "event=pipeline_step")
        assert any("step=parse" in m and "reason=parse_error" in m
                   for m in trace)

    @pytest.mark.asyncio
    async def test_tick_logs_summary_with_next_run(self, monkeypatch, caplog):
        worker = aw.AntiClicheWorker(llm=None, pg=object())
        worker.refresh = AsyncMock(return_value={
            "status": "ok", "count": 2, "version": 1, "source": "wikipedia"})
        with caplog.at_level(logging.INFO):
            await worker.tick()
        trace = _find(caplog, "event=pipeline_step")
        assert any("step=refresh" in m and "status=ok" in m
                   and "count=2" in m and "next_run_time=" in m for m in trace)

    @pytest.mark.asyncio
    async def test_fetch_source_logs_status_body(self, monkeypatch, caplog):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                return _Resp(500, text='{"error":"upstream"}')

        monkeypatch.setattr(aw.httpx, "AsyncClient",
                            lambda **kw: _Client())
        with caplog.at_level(logging.INFO):
            with pytest.raises(Exception):
                await aw.fetch_source("https://wiki.example/w/api.php?x=1")
        ext = _find(caplog, "event=ext_api")
        assert any("status=500" in m and "upstream" in m for m in ext)

    @pytest.mark.asyncio
    async def test_fetch_source_2xx_not_error(self, monkeypatch, caplog):
        """R1024F2-07: успешные 200/204 не пишут ERROR-строку."""
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                return _Resp(204, text="")

        monkeypatch.setattr(aw.httpx, "AsyncClient", lambda **kw: _Client())
        with caplog.at_level(logging.INFO):
            out = await aw.fetch_source("https://wiki.example/w/api.php?x=1")
        assert out == ""
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
        assert not _find(caplog, "event=ext_api")


# ── (c) Экстрактор/Сон ──────────────────────────────────────────────────────

class _EmptyDb:
    async def get_dream_candidates(self, *a, **kw):
        return []

    async def list_recent_beliefs(self, *a, **kw):
        return []


class TestDreamTraceLogging:
    @pytest.mark.asyncio
    async def test_traits_empty_reason(self, monkeypatch, caplog):
        monkeypatch.setattr(bot_persona, "record_trait_status",
                            AsyncMock())
        worker = DreamWorker(_EmptyDb())
        with caplog.at_level(logging.INFO):
            stats = await worker._run_persona_traits_once(123)
        assert stats["status"] == "empty"
        trace = _find(caplog, "event=pipeline_step")
        assert any("component=dream" in m and "step=traits" in m
                   and "status=empty" in m and "reason=no_self_facts" in m
                   and "chat_id=123" in m for m in trace)

    @pytest.mark.asyncio
    async def test_deep_disabled_reason(self, monkeypatch, caplog):
        async def fake_resolve(key, *, chat_id, default):
            return False

        monkeypatch.setattr(dw, "resolve_setting_cached", fake_resolve)
        worker = DreamWorker(_EmptyDb())
        with caplog.at_level(logging.INFO):
            result = await worker._run_deep_once(55)
        assert result["status"] == "disabled"
        trace = _find(caplog, "event=pipeline_step")
        assert any("step=deep" in m and "reason=disabled" in m
                   and "chat_id=55" in m for m in trace)


class TestGraphTraceLogging:
    @pytest.mark.asyncio
    async def test_no_captions_reason(self, caplog):
        mem = sm.MemoryManager(db=MagicMock(), llm=MagicMock())
        with caplog.at_level(logging.INFO):
            await mem._extract_and_save_graph(9, [{"author_name": "a",
                                                   "text": ""}])
        trace = _find(caplog, "event=pipeline_step")
        assert any("component=graph" in m and "reason=no_captions" in m
                   and "chat_id=9" in m for m in trace)


# ── (b) сквозной egress-скан по всем подсистемам (spec §6c) ──────────────────

class TestEgressEndToEnd:
    """R1024F2-02: прогон сбоев image/cron/dream/graph → единый R17/R18-скан
    собранных лог-записей: ни одного запрещённого токена."""

    _SECRET_RE = re.compile(
        r"(?i)(authorization\s*:\s*bearer\s+\S+"
        r"|bearer\s+[A-Za-z0-9._\-]{12,}"
        r"|\b(?:sk|gsk|or|tvly)[-_][A-Za-z0-9_\-]{6,}"
        r"|://[^/\s:@]+:[^/\s@]+@)")

    @pytest.mark.asyncio
    async def test_scan_failure_scenarios(self, monkeypatch, caplog):
        with caplog.at_level(logging.INFO):
            # 1) image POST 400 — секреты в теле ответа
            async def post_fake(method, url, *, json_body=None, headers=None,
                                timeout=90.0):
                return _Resp(
                    400,
                    text='{"error":"bad model",'
                         '"auth":"Bearer abcdefghijklmnop",'
                         '"key":"sk-EGRESSZZZ999888777666"}')

            monkeypatch.setattr(ig, "_http_request", post_fake)
            with pytest.raises(ig.ImageGenerationError):
                await ig._generate_post("https://gen.pollinations.ai/v1",
                                        "flux", "кот", "", 5.0, 1000)

            # 2) image GET 429 → ретрай (промпт в path не должен утечь)
            seq = [
                _Resp(429, text="rate limited",
                      headers={"Retry-After": "0"}),
                _Resp(200, content=b"img", headers={}),
            ]
            calls: list[str] = []

            async def get_fake(method, url, *, json_body=None, headers=None,
                               timeout=90.0):
                calls.append(url)
                return seq[min(len(calls) - 1, len(seq) - 1)]

            monkeypatch.setattr(ig, "_http_request", get_fake)
            await ig._generate_get("https://image.pollinations.ai", "flux",
                                   "кот-промпт-123", 5.0, 1000)

            # 3) cron fetch 500 — секреты в теле источника
            class _Client:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                async def get(self, *a, **kw):
                    return _Resp(
                        500,
                        text='{"e":"Bearer abcdefghijklmnop",'
                             '"k":"gsk_XYZ789000000"}')

            monkeypatch.setattr(aw.httpx, "AsyncClient",
                                lambda **kw: _Client())
            with pytest.raises(Exception):
                await aw.fetch_source("https://wiki.example/w/api.php?x=1")

            # 4) dream traits empty
            monkeypatch.setattr(bot_persona, "record_trait_status",
                                AsyncMock())
            await DreamWorker(_EmptyDb())._run_persona_traits_once(7)

            # 5) graph no captions
            mem = sm.MemoryManager(db=MagicMock(), llm=MagicMock())
            await mem._extract_and_save_graph(
                9, [{"author_name": "a", "text": ""}])

        joined = "\n".join(_messages(caplog))
        match = self._SECRET_RE.search(joined)
        assert match is None, f"секрет в логах: {match.group(0)!r}"
        assert "reason=retry" in joined and "event=pipeline_step" in joined
