"""ASAP 8 F9 — YouTube proxy classification + health (ТЗ §16, §24 Y1–Y5,
architecture §9, §28.20/§28.21).

Покрытие:
  * Y1 — 407/«Proxy Authentication Required» => failure_class
    proxy_auth_failed, ОДНА попытка каскада (никаких exponential retries),
    РОВНО ОДИН WARN на запрос; 407 на ОДНОМ движке останавливает каскад
    даже при transient-фейле второго (регресс retry storm 1/2/4/8с);
  * Y2 — 429 остаётся transient с backoff (1,2,4,8);
  * Y3 — timeout retries bounded (4 ретрая = 5 попыток);
  * Y4 — ЕДИНЫЙ effective proxy profile: yt-dlp opts и transcript-api
    proxy_config строятся из одного резолвера (resident-поля и URL — оба
    пути); health-эндпоинт: auth OK/FAIL + оба пути + last_check;
  * Y5 — секреты прокси (user:pass/host) не появляются в логах/UI/API.

yt-dlp / YouTubeTranscriptApi / urllib — мокаются (реальная сеть НЕ ходит);
asyncio.sleep ЗАМОКАН. API — TestClient + ConfigCache-стаб (прецедент
test_webapp_api.py).

TEST-LIFECYCLE: CONTRACT owner=asap8/F9 (Y1-Y5)
"""
import asyncio
import json
import logging
import time
import types
import urllib.error

import pytest
from fastapi.testclient import TestClient

from services import youtube_transcript_engine as engine_mod
from services.youtube_transcript_engine import (
    YouTubeTranscriptEngine,
    YouTubeTranscriptUnavailableException,
    effective_proxy_profile,
    mask_proxy_endpoint,
    proxy_health_snapshot,
)


# ── Фейк-классы исключений (имена = реальные; библиотеки не импортируются) ──

class HTTPError(Exception):
    def __init__(self, message=None, status=None, response=None):
        self.status = status
        self.response = response
        super().__init__(
            message if message is not None else f"HTTP Error {status}")


class ProxyError(Exception):
    pass


class TransportError(Exception):
    pass


class DownloadError(Exception):
    pass


class TooManyRequests(Exception):
    pass


class TimeoutError_(TimeoutError):
    pass


def _wrap_cause(inner):
    outer = YouTubeTranscriptUnavailableException("list failed")
    outer.__cause__ = inner
    return outer


# ── Y1: классификация 407 / 403 / 429 / timeout / reset / proxy ─────────────

class TestF9FailureClass:
    """Матрица F9 (architecture §9): специфичный парс ДО generic-классов."""

    @pytest.mark.parametrize("exc", [
        HTTPError(status=407),
        HTTPError("HTTP Error 407: Proxy Authentication Required", status=None),
        DownloadError("ERROR: Unable to download webpage: HTTP Error 407"),
        ProxyError("Cannot connect to proxy.: 407 Proxy Authentication Required"),
        TransportError("407 Proxy Authentication Required"),
        # обёртка transcript-api: классификация по __cause__
        _wrap_cause(DownloadError("HTTP Error 407")),
    ])
    def test_407_is_proxy_auth_failed_permanent(self, exc):
        assert YouTubeTranscriptEngine._failure_class(exc) == "proxy_auth_failed"
        assert YouTubeTranscriptEngine._is_transient(exc) is False
        assert YouTubeTranscriptEngine._is_proxy_auth_failed(exc) is True

    def test_403_forbidden_no_retry(self):
        """F9: 403 => forbidden — БЕЗ exponential retry (смена контракта)."""
        exc = HTTPError(status=403)
        assert YouTubeTranscriptEngine._failure_class(exc) == "forbidden"
        assert YouTubeTranscriptEngine._is_transient(exc) is False

    def test_429_rate_limited_transient(self):
        """Y2: 429 остаётся transient (backoff как раньше)."""
        assert YouTubeTranscriptEngine._failure_class(
            HTTPError(status=429)) == "rate_limited"
        assert YouTubeTranscriptEngine._is_transient(HTTPError(status=429)) is True
        assert YouTubeTranscriptEngine._is_transient(
            DownloadError("ERROR: Unable to download webpage: HTTP Error 429")) is True

    def test_5xx_server_error_transient(self):
        for status in (500, 502, 503, 504):
            exc = HTTPError(status=status)
            assert YouTubeTranscriptEngine._failure_class(exc) == "server_error"
            assert YouTubeTranscriptEngine._is_transient(exc) is True

    @pytest.mark.parametrize("exc,expected", [
        (TimeoutError_("request timed out"), "timeout"),
        (RuntimeError("Connection reset by peer"), "reset"),
        (RuntimeError("[Errno 104] Connection reset"), "reset"),
        (ProxyError("Cannot connect to proxy.: Connection refused"),
         "proxy_unavailable"),
        (TransportError("proxy unavailable"), "proxy_unavailable"),
    ])
    def test_transient_bounded_classes(self, exc, expected):
        """Y3-смежное: timeout/reset/proxy-unavailable — transient bounded."""
        assert YouTubeTranscriptEngine._failure_class(exc) == expected
        assert YouTubeTranscriptEngine._is_transient(exc) is True

    def test_unknown_failure_permanent_default(self):
        assert YouTubeTranscriptEngine._failure_class(
            RuntimeError("mystery")) == "permanent"
        assert YouTubeTranscriptEngine._is_transient(RuntimeError("mystery")) is False


# ── Каскад: фейки движков (прецедент test_youtube_transcript_engine) ────────

def _flaky_fetcher(outcomes):
    counter = {"n": 0}

    def fn(video_id):
        counter["n"] += 1
        item = outcomes[min(counter["n"] - 1, len(outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return fn, counter


class _PatchedCascade:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.sleep_calls = []

    def patch(self, ytdlp_outcomes, api_outcomes):
        engine = YouTubeTranscriptEngine()
        ytdlp_fn, self.ytdlp_calls = _flaky_fetcher(ytdlp_outcomes)
        api_fn, self.api_calls = _flaky_fetcher(api_outcomes)
        self.monkeypatch.setattr(engine, "_fetch_ytdlp", ytdlp_fn)
        self.monkeypatch.setattr(engine, "_fetch_segments", api_fn)

        async def _no_sleep(delay):
            self.sleep_calls.append(delay)

        self.monkeypatch.setattr(engine_mod.asyncio, "sleep", _no_sleep)
        return engine


@pytest.mark.asyncio
class TestF9Cascade407:
    """Y1 (§28.20/§28.21): 407 — одна попытка, reason proxy_auth_failed,
    никаких exponential retries, WARN ровно 1/request."""

    async def test_both_engines_407_one_attempt(self, monkeypatch, caplog):
        cascade = _PatchedCascade(monkeypatch)
        exc407 = DownloadError("ERROR: failed: HTTP Error 407")
        engine = cascade.patch([exc407], [ProxyError("407 Proxy Auth Required")])
        on_retry_calls = []

        async def on_retry(attempt, max_attempts):
            on_retry_calls.append((attempt, max_attempts))

        with caplog.at_level(logging.WARNING):
            with pytest.raises(YouTubeTranscriptUnavailableException) as ei:
                await engine.fetch_transcript("video-1", 4000, on_retry=on_retry)
        assert cascade.ytdlp_calls["n"] == 1          # одна попытка
        assert cascade.api_calls["n"] == 1
        assert cascade.sleep_calls == []              # никаких backoff-пауз
        assert on_retry_calls == []                   # ретраев не было
        assert ei.value.reason == "proxy_auth_failed"
        warns = [r for r in caplog.records
                 if "proxy auth failed (407)" in r.message
                 and r.levelno == logging.WARNING]
        assert len(warns) == 1                        # РОВНО ОДИН WARN на запрос

    async def test_407_on_one_engine_stops_despite_transient_other(self,
                                                                   monkeypatch):
        """Регресс retry storm: yt-dlp 407 + transcript-api 429 (transient) —
        прежде OR-правило давало 5 попыток; теперь перманент с 1 попытки."""
        cascade = _PatchedCascade(monkeypatch)
        engine = cascade.patch(
            [DownloadError("HTTP Error 407")],
            [TooManyRequests("too many")],
        )
        with pytest.raises(YouTubeTranscriptUnavailableException) as ei:
            await engine.fetch_transcript("video-1", 4000)
        assert cascade.ytdlp_calls["n"] == 1
        assert cascade.api_calls["n"] == 1
        assert cascade.sleep_calls == []
        assert ei.value.reason == "proxy_auth_failed"

    async def test_407_secrets_never_logged(self, monkeypatch, caplog):
        """Y5-фрагмент: WARN/исключение не содержат user:pass прокси."""
        cascade = _PatchedCascade(monkeypatch)
        engine = cascade.patch(
            [DownloadError("HTTP Error 407")],
            [ProxyError("407 Proxy Auth Required")],
        )
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(YouTubeTranscriptUnavailableException):
                await engine.fetch_transcript("video-1", 4000)
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert "secretpass" not in blob
        assert "proxyuser" not in blob


@pytest.mark.asyncio
class TestF9Cascade429Timeout:
    """Y2/Y3: 429 и timeout остаются transient bounded."""

    async def test_429_retries_with_backoff_then_raises(self, monkeypatch):
        """Y2: 429 → backoff (1,2,4,8), 5 попыток (как прежде, D151/D152)."""
        cascade = _PatchedCascade(monkeypatch)
        engine = cascade.patch(
            [HTTPError(status=429)],
            [TooManyRequests("too many")],
        )
        with pytest.raises(YouTubeTranscriptUnavailableException,
                           match="both engines failed after 5 attempt"):
            await engine.fetch_transcript("video-1", 4000)
        assert cascade.ytdlp_calls["n"] == 5
        assert cascade.api_calls["n"] == 5
        assert cascade.sleep_calls == [1.0, 2.0, 4.0, 8.0]

    async def test_429_recovers_on_second_attempt(self, monkeypatch):
        cascade = _PatchedCascade(monkeypatch)
        engine = cascade.patch(
            [HTTPError(status=429), [{"text": "ok", "start": 0.0, "duration": 1.0}]],
            [TooManyRequests("too many")],
        )
        result = await engine.fetch_transcript("video-1", 4000)
        assert "ok" in result
        assert cascade.sleep_calls == [1.0]

    async def test_timeout_retries_bounded_4(self, monkeypatch):
        """Y3: timeout → bounded 4 ретрая = 5 попыток, backoff 1/2/4/8."""
        cascade = _PatchedCascade(monkeypatch)
        engine = cascade.patch(
            [TimeoutError_("request timed out")],
            [RuntimeError("request timed out")],
        )
        with pytest.raises(YouTubeTranscriptUnavailableException,
                           match="both engines failed after 5 attempt"):
            await engine.fetch_transcript("video-1", 4000)
        assert cascade.ytdlp_calls["n"] == 5
        assert cascade.api_calls["n"] == 5
        assert cascade.sleep_calls == [1.0, 2.0, 4.0, 8.0]


# ── Y4: единый effective proxy profile ──────────────────────────────────────

def _mock_settings(monkeypatch, proxy="", username="", password="",
                   domain="", port="", credentialed=True):
    monkeypatch.setattr(
        engine_mod, "settings",
        types.SimpleNamespace(
            YOUTUBE_TRANSCRIPT_PROXY_URL=proxy,
            YOUTUBE_COOKIES_FILE="",
            YOUTUBE_TRANSCRIPT_PROXY_USERNAME=username,
            YOUTUBE_TRANSCRIPT_PROXY_PASSWORD=password,
            YOUTUBE_TRANSCRIPT_PROXY_DOMAIN=domain,
            YOUTUBE_TRANSCRIPT_PROXY_PORT=port,
            YOUTUBE_CREDENTIALED_LEVEL_ENABLED=credentialed,
        ),
    )
    # hot_config в юнит-тестах недоступен (_cache None → default)
    monkeypatch.setattr(engine_mod.hot, "get", lambda key, default=None: default)
    # build_ytdlp_base_opts уважает credentialed-гейт (как реальный хелпер)
    monkeypatch.setattr(
        engine_mod, "build_ytdlp_base_opts",
        lambda: {} if not credentialed else {**({"proxy": proxy} if proxy else {})})


class _FakeGenericProxyConfig:
    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeGenericProxyConfig.last_kwargs = kwargs
        self.http_url = kwargs.get("http_url")
        self.https_url = kwargs.get("https_url")


class _FakeYDL:
    last_opts = None

    def __init__(self, opts):
        _FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        raise RuntimeError("no network in test")


class _CapturingApi:
    last_proxy_config = None

    def __init__(self, proxy_config=None):
        _CapturingApi.last_proxy_config = proxy_config

    def list(self, video_id):
        raise RuntimeError("no network in test")


class TestF9UnifiedProfile:
    """Y4: yt-dlp и transcript-api получают ОДИН effective proxy profile."""

    @pytest.fixture(autouse=True)
    def _fakes(self, monkeypatch):
        _FakeYDL.last_opts = None
        _CapturingApi.last_proxy_config = None
        _FakeGenericProxyConfig.last_kwargs = None
        monkeypatch.setattr(engine_mod, "GenericProxyConfig",
                            _FakeGenericProxyConfig)
        monkeypatch.setattr(engine_mod, "yt_dlp",
                            types.SimpleNamespace(YoutubeDL=_FakeYDL))
        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _CapturingApi)
        from services import safe_fetch
        monkeypatch.setattr(safe_fetch, "egress_proxy_url", lambda: None)
        self._monkeypatch = monkeypatch

    def test_webshare_fields_same_profile_both_paths(self, monkeypatch):
        """Y4: resident-поля → ОДИН URL (с auth) в opts И proxy_config."""
        _mock_settings(monkeypatch, username="proxyuser", password="secretpass",
                       domain="proxy.example.com", port="8080")
        engine = YouTubeTranscriptEngine()
        ytdlp_proxy = engine._ytdlp_opts()["proxy"]
        api_cfg = engine._transcript_proxy_config()
        expected = "http://proxyuser:secretpass@proxy.example.com:8080"
        assert ytdlp_proxy == expected
        assert api_cfg.http_url == expected == api_cfg.https_url

    def test_url_only_same_profile_both_paths(self, monkeypatch):
        """Y4: URL-прокси → оба пути получают один и тот же effective proxy
        (до F9 transcript-api URL НЕ получал — рассинхрон)."""
        url = "http://proxyuser:secretpass@127.0.0.1:10808"
        _mock_settings(monkeypatch, proxy=url)
        engine = YouTubeTranscriptEngine()
        assert engine._ytdlp_opts()["proxy"] == url
        api_cfg = engine._transcript_proxy_config()
        assert api_cfg.http_url == url
        assert api_cfg.https_url == url

    def test_credentialed_off_no_proxy_both_paths(self, monkeypatch):
        _mock_settings(monkeypatch, proxy="http://pr:8080",
                       domain="proxy.example.com", port="8080",
                       credentialed=False)
        engine = YouTubeTranscriptEngine()
        assert "proxy" not in engine._ytdlp_opts()
        assert engine._transcript_proxy_config() is None

    def test_empty_settings_no_proxy_both_paths(self, monkeypatch):
        _mock_settings(monkeypatch)
        engine = YouTubeTranscriptEngine()
        assert "proxy" not in engine._ytdlp_opts()
        assert engine._transcript_proxy_config() is None
        profile = effective_proxy_profile()
        assert profile["configured"] is False
        assert profile["endpoint_masked"] is None

    def test_profile_endpoint_masked_and_auth_flag(self, monkeypatch):
        """Y4/Y5: профиль отдаёт только замаскированный endpoint."""
        _mock_settings(monkeypatch, username="proxyuser", password="secretpass",
                       domain="proxy.example.com", port="8080")
        profile = effective_proxy_profile()
        assert profile["configured"] is True
        assert profile["source"] == "webshare"
        assert profile["auth_configured"] is True
        assert profile["endpoint_masked"] == "pr\u2026om:8080"
        # Y5: UI-ориентируемые поля не несут секретов (proxy_url — внутреннее
        # поле движка, в health/UI/API не попадает — см. test_full_run_paths).
        assert "secretpass" not in profile["endpoint_masked"]
        assert "proxy.example.com" not in profile["endpoint_masked"]


def test_mask_proxy_endpoint_shapes():
    assert mask_proxy_endpoint("http://user:p@host.example.com:9090") == \
        "ho\u2026om:9090"
    assert mask_proxy_endpoint("http://short:80") == "s\u2026:80"
    assert mask_proxy_endpoint("http://10.0.0.5") == "10\u2026.5"
    assert mask_proxy_endpoint("") is None
    assert mask_proxy_endpoint(None) is None
    assert mask_proxy_endpoint("not a url at all") is None


# ── F9: proxy health unit (auth probe + шаги + snapshot) ────────────────────

class TestProxyAuthProbe:
    def _probe_with(self, monkeypatch, behavior):
        class _Resp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Opener:
            def __init__(self, handlers):
                self.handlers = handlers

            def open(self, req, timeout=None):
                return behavior(req, timeout)

        monkeypatch.setattr(engine_mod.urllib.request, "build_opener",
                            lambda handlers=None: _Opener(handlers))
        return engine_mod._proxy_auth_probe("http://u:p@pr:8080")

    def test_407_http_error_fail(self, monkeypatch):
        def behavior(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 407,
                                         "Proxy Authentication Required",
                                         None, None)
        result = self._probe_with(monkeypatch, behavior)
        assert result == {"status": "fail", "http_status": 407,
                          "reason": "proxy_auth_failed"}

    def test_target_403_means_proxy_auth_ok(self, monkeypatch):
        """4xx от ЦЕЛИ (не от прокси) — туннель и auth OK."""

        def behavior(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden",
                                         None, None)

        result = self._probe_with(monkeypatch, behavior)
        assert result == {"status": "ok", "http_status": 403, "reason": None}

    def test_urlopen_ok(self, monkeypatch):
        class _Resp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def behavior(req, timeout):
            return _Resp()

        result = self._probe_with(monkeypatch, behavior)
        assert result == {"status": "ok", "http_status": 204, "reason": None}

    def test_proxy_error_with_407_marker_fail(self, monkeypatch):
        def behavior(req, timeout):
            raise urllib.error.URLError(
                "Cannot connect to proxy.: 407 Proxy Authentication Required")

        result = self._probe_with(monkeypatch, behavior)
        assert result["status"] == "fail"
        assert result["reason"] == "proxy_auth_failed"

    def test_unreachable(self, monkeypatch):
        def behavior(req, timeout):
            raise urllib.error.URLError("Connection refused")

        result = self._probe_with(monkeypatch, behavior)
        assert result == {"status": "unreachable", "http_status": None,
                          "reason": "proxy_unreachable"}


class TestProxyHealthCheck:
    @pytest.fixture(autouse=True)
    def _reset_snapshot(self):
        engine_mod._PROXY_HEALTH_LAST = None
        yield
        engine_mod._PROXY_HEALTH_LAST = None

    def test_no_proxy_all_skipped(self, monkeypatch):
        _mock_settings(monkeypatch)
        result = engine_mod.run_proxy_health_check()
        assert result["configured"] is False
        for step in ("auth", "ytdlp_path", "transcript_api_path"):
            assert result[step]["status"] == "skipped"
            assert result[step]["reason"] == "no_proxy"
        assert result["checked_at"]
        assert isinstance(result["took_ms"], int)
        assert proxy_health_snapshot() is result

    def test_full_run_paths_and_codes(self, monkeypatch):
        """Y4: auth FAIL + классифицированные фейлы обоих путей; last_check."""
        _mock_settings(monkeypatch, proxy="http://proxyuser:secretpass@pr:8080")
        monkeypatch.setattr(
            engine_mod, "_proxy_auth_probe",
            lambda url: {"status": "fail", "http_status": 407,
                         "reason": "proxy_auth_failed"})

        def _fake_ytdlp(self, video_id):
            raise DownloadError("HTTP Error 407")

        def _fake_api_cfg(self):
            return object()

        monkeypatch.setattr(YouTubeTranscriptEngine, "_fetch_ytdlp", _fake_ytdlp)
        monkeypatch.setattr(YouTubeTranscriptEngine, "_transcript_proxy_config",
                            _fake_api_cfg)

        class _Api:
            def __init__(self, proxy_config=None):
                pass

            def list(self, video_id):
                raise TooManyRequests("429")

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        result = engine_mod.run_proxy_health_check()
        assert result["configured"] is True
        assert result["endpoint"] == "p\u2026:8080"
        assert result["auth"] == {"status": "fail", "http_status": 407,
                                  "reason": "proxy_auth_failed"}
        assert result["ytdlp_path"]["status"] == "fail"
        assert result["ytdlp_path"]["code"] == "proxy_auth_failed"
        assert result["transcript_api_path"]["code"] == "rate_limited"
        assert proxy_health_snapshot() is result
        blob = json.dumps(result)
        assert "secretpass" not in blob
        assert "HTTP Error" not in blob          # только коды, не тексты

    def test_singleflight_in_progress(self, monkeypatch):
        _mock_settings(monkeypatch)
        engine_mod._PROXY_HEALTH_LAST = {"checked_at": "2026-10-13T00:00:00+00:00"}
        acquired = engine_mod._PROXY_HEALTH_LOCK.acquire(blocking=False)
        assert acquired is True                  # имитация идущей пробы
        try:
            result = engine_mod.run_proxy_health_check_locked()
        finally:
            engine_mod._PROXY_HEALTH_LOCK.release()
        assert result["in_progress"] is True
        assert result["checked_at"] == "2026-10-13T00:00:00+00:00"


# ── Y4/Y5: API /api/youtube/proxy/health + /api/youtube/proxy/test ──────────

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079


def _make_init_data(user_id: int) -> str:
    import hashlib
    import hmac
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": _make_init_data(user_id)}


class _FakeConn:
    def __init__(self, role_rows, admin_rows=()):
        self._role_rows = role_rows
        self._admin_rows = admin_rows

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx

    async def fetch(self, sql, *args):
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


@pytest.fixture
def yt_client(monkeypatch):
    from services.config_cache import ConfigCache
    from web.api import deps as deps_mod
    from web.api import routes as routes_mod
    from web.app import create_app

    routes_mod.reset_youtube_proxy_test_rate_limit()
    engine_mod._PROXY_HEALTH_LAST = None
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn(role_rows=[
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False},
        {"role_name": "moderator", "permissions": {"sections": ["limits"]},
         "is_custom": False},
        {"role_name": "user", "permissions": {}, "is_custom": False},
    ], admin_rows=[
        {"telegram_id": ADMIN_ID, "role_name": "admin", "added_by": None,
         "created_at": "2026-08-30T00:00:00+00:00"},
        {"telegram_id": MODERATOR_ID, "role_name": "moderator",
         "added_by": ADMIN_ID, "created_at": "2026-08-30T00:00:01+00:00"},
    ])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        yield test_client
    routes_mod.reset_youtube_proxy_test_rate_limit()
    engine_mod._PROXY_HEALTH_LAST = None


class TestYoutubeProxyApi:
    def test_health_never_run(self, yt_client):
        resp = yt_client.get("/api/youtube/proxy/health", headers=_hdr())
        assert resp.status_code == 200
        assert resp.json() == {"status": "never_run"}

    def test_health_returns_snapshot_without_rerun(self, yt_client):
        engine_mod._PROXY_HEALTH_LAST = {
            "configured": True, "endpoint": "p\u2026r:8080",
            "auth": {"status": "fail"}, "checked_at_ts": 1000,
        }
        resp = yt_client.get("/api/youtube/proxy/health", headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["endpoint"] == "p\u2026r:8080"

    def test_health_fail_closed_for_moderator(self, yt_client):
        """global-admin fail-closed: moderator → 403, снимок не утекает."""
        engine_mod._PROXY_HEALTH_LAST = {"configured": True, "secret": "x"}
        resp = yt_client.get("/api/youtube/proxy/health",
                             headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_test_fail_closed_for_moderator(self, yt_client):
        resp = yt_client.post("/api/youtube/proxy/test",
                              headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_test_runs_and_masks_secrets(self, yt_client, monkeypatch):
        """Y4/Y5: живая проба → 200 с шагами; секретов в ответе нет."""
        def _fake_locked(**kwargs):
            return {
                "configured": True, "source": "url",
                "endpoint": "p\u2026r:8080", "auth_configured": True,
                "auth": {"status": "fail", "http_status": 407,
                         "reason": "proxy_auth_failed"},
                "ytdlp_path": {"status": "fail", "code": "proxy_auth_failed"},
                "transcript_api_path": {"status": "fail",
                                        "code": "proxy_auth_failed"},
                "checked_at": "2026-10-13T00:00:00+00:00",
                "checked_at_ts": 1000, "took_ms": 5,
            }

        monkeypatch.setattr(engine_mod, "run_proxy_health_check_locked",
                            _fake_locked)
        resp = yt_client.post("/api/youtube/proxy/test", headers=_hdr())
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth"]["reason"] == "proxy_auth_failed"
        assert data["ytdlp_path"]["code"] == "proxy_auth_failed"
        assert "secretpass" not in json.dumps(data)

    def test_test_rate_limited(self, yt_client, monkeypatch):
        def _fake_locked(**kwargs):
            return {"configured": False}

        monkeypatch.setattr(engine_mod, "run_proxy_health_check_locked",
                            _fake_locked)
        first = yt_client.post("/api/youtube/proxy/test", headers=_hdr())
        assert first.status_code == 200
        second = yt_client.post("/api/youtube/proxy/test", headers=_hdr())
        assert second.status_code == 429
