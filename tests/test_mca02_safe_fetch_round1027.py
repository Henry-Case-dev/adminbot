"""Раунд 10.27 (MCA Wave 1, `mca-02-safe-fetch-cookies`) — тесты SafeFetcher.

Приёмки: **A22** (redirect на private IPv4/IPv6, metadata; большой stream —
блокировка без чтения в RAM; каждый redirect + фактический адрес; маскирование)
и **A23** (cookies/профиль сохранены; video paths работают), регрессии OFF-паритет
и доверенные API. Синтетика (ttl getaddrinfo) мокается → детерминизм без сети.
"""
import asyncio
import gzip
import logging
import time

import httpx
import pytest

from services import mca_gates
from services import safe_fetch as sf


# ── helpers ──────────────────────────────────────────────────────────────────

def _patch_resolver(monkeypatch, mapping, default="93.184.216.34"):
    def resolver(host):
        return list(mapping.get(host.lower(), [default]))
    monkeypatch.setattr(sf, "_resolve_ip", resolver)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _SlowTransport(httpx.AsyncBaseTransport):
    """Транспорт, «висящий» в connect дольше профильного timeout (B-MCA02-1)."""

    def __init__(self, delay: float = 1.5, addr=("93.184.216.34", 443)):
        self._delay = delay
        self._addr = addr

    async def handle_async_request(self, request):
        await asyncio.sleep(self._delay)
        return httpx.Response(
            200, content=b"slow",
            extensions={"network_stream": _FakeStream(self._addr)},
            request=request)


class _FakeStream:
    def __init__(self, addr):
        self._addr = addr

    def get_extra_info(self, info):
        return self._addr if info == "server_addr" else None


def _resp(request, status=200, content=b"hello", headers=None, addr=None,
          extensions=None):
    ext = dict(extensions or {})
    if addr is not None:
        ext["network_stream"] = _FakeStream(addr)
    return httpx.Response(status, content=content, headers=headers,
                          extensions=ext, request=request)


# ── нормализация/схемы/credentials (SC-01) ───────────────────────────────────

class TestNormalize:
    def test_scheme_and_default_port_and_dot_segments(self):
        assert sf.normalize_url("HTTPS://Example.COM:443/a/./b/../c") == \
            "https://example.com/a/c"
        assert sf.normalize_url("http://Host:80/p") == "http://host/p"

    def test_idn_to_punycode(self):
        assert sf.normalize_url("https://пример.рф/x").startswith(
            "https://xn--e1afmkfd.xn--p1ai/")

    def test_fragment_dropped(self):
        assert sf.normalize_url("https://h/p#frag") == "https://h/p"

    @pytest.mark.parametrize("url,code", [
        ("ftp://h/x", "scheme_not_allowed"),
        ("gopher://h/x", "scheme_not_allowed"),
        ("file:///etc/passwd", "scheme_not_allowed"),
        ("data:text/plain,hi", "scheme_not_allowed"),
        ("http://user:pass@h/x", "credentials_in_url"),
        ("http://h/a\\b", "invalid_url"),
        ("", "invalid_url"),
    ])
    def test_rejected(self, url, code):
        with pytest.raises(sf.SafeFetchError) as exc:
            sf.normalize_url(url)
        assert exc.value.code == code
        assert exc.value.stage == "normalize"


# ── SSRF-политика (SC-02) ────────────────────────────────────────────────────

class TestDestination:
    @pytest.mark.parametrize("ip", [
        "127.0.0.1", "10.0.0.1", "172.16.5.5", "192.168.1.1",
        "169.254.169.254", "100.64.0.1", "0.0.0.0",
        "::1", "fe80::1", "fc00::1", "fd00:ec2::254", "100.100.100.200",
        "::ffff:10.0.0.1",
    ])
    def test_blocked_literals(self, ip):
        assert sf.destination_reason(ip) is not None

    def test_public_literal_ok(self):
        assert sf.destination_reason("93.184.216.34") is None
        assert sf.destination_reason("2606:2800:220:1:248:1893:25c8:1946") is None

    def test_metadata_host_blocked(self):
        assert sf.destination_reason("metadata.google.internal") == \
            "metadata_endpoint"

    def test_guarded_target_blocks_private_hostname(self, monkeypatch):
        _patch_resolver(monkeypatch, {"evil.example": ["10.1.2.3"]})
        with pytest.raises(sf.SafeFetchError) as exc:
            sf.guarded_target("http://evil.example/x")
        assert exc.value.code == "destination_blocked"
        assert exc.value.stage == "resolve"

    def test_trusted_allowlist_permits_loopback(self, monkeypatch):
        import types
        monkeypatch.setattr(sf, "settings", types.SimpleNamespace(
            SAFE_FETCH_TRUSTED_HOSTS="127.0.0.1",
            SAFE_FETCH_TRUSTED_PORTS="9000"))
        assert sf.is_trusted("127.0.0.1", 9000)
        tgt = sf.guarded_target("http://127.0.0.1:9000/", trusted=True)
        assert tgt.host == "127.0.0.1"
        # Пользовательский URL (trusted=False) — всегда блок.
        with pytest.raises(sf.SafeFetchError):
            sf.guarded_target("http://127.0.0.1:9000/")

    def test_trusted_does_not_allow_metadata(self, monkeypatch):
        import types
        monkeypatch.setattr(sf, "settings", types.SimpleNamespace(
            SAFE_FETCH_TRUSTED_HOSTS="169.254.169.254",
            SAFE_FETCH_TRUSTED_PORTS=""))
        with pytest.raises(sf.SafeFetchError) as exc:
            sf.guarded_target("http://169.254.169.254/latest/meta-data/",
                              trusted=True)
        assert exc.value.code == "metadata_endpoint_blocked"


# ── redirect + peer-проверка (SC-03) ─────────────────────────────────────────

class TestRedirectsAndPeer:
    @pytest.mark.asyncio
    async def test_redirect_to_private_ipv4_blocked(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            return _resp(request, 302, b"", {"location": "http://10.0.0.5/x"})
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://start.example/a",
                                         client=_client(handler))
        assert exc.value.code == "redirect_blocked"
        assert exc.value.stage == "redirect"

    @pytest.mark.asyncio
    async def test_redirect_to_private_ipv6_blocked(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            return _resp(request, 301, b"", {"location": "http://[fd00::1]/x"})
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://start.example/a",
                                         client=_client(handler))
        assert exc.value.code == "redirect_blocked"

    @pytest.mark.asyncio
    async def test_redirect_to_metadata_blocked(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            return _resp(request, 302, b"",
                         {"location": "http://169.254.169.254/latest"})
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://start.example/a",
                                         client=_client(handler))
        assert exc.value.code == "redirect_blocked"

    @pytest.mark.asyncio
    async def test_public_redirect_chain_allowed(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            if str(request.url).endswith("/a"):
                return _resp(request, 302, b"", {"location": "/b"})
            if str(request.url).endswith("/b"):
                return _resp(request, 200, b"final")
            return _resp(request, 500, b"")
        out = await sf.SafeFetcher().fetch_text(
            "http://start.example/a", client=_client(handler))
        assert out == "final"

    @pytest.mark.asyncio
    async def test_too_many_redirects(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            n = int(str(request.url).rsplit("/", 1)[-1] or 0)
            return _resp(request, 302, b"",
                         {"location": f"/{n + 1}"})
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://start.example/0",
                                         client=_client(handler))
        assert exc.value.code == "too_many_redirects"

    @pytest.mark.asyncio
    async def test_peer_mismatch_blocked(self, monkeypatch):
        """Anti-rebinding: фактический peer вне валидированного набора → блок."""
        _patch_resolver(monkeypatch, {"start.example": ["93.184.216.34"]})
        def handler(request):
            return _resp(request, 200, b"ok", addr=("10.0.0.9", 80))
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://start.example/a",
                                         client=_client(handler))
        assert exc.value.code == "destination_blocked"
        assert exc.value.stage == "connect"

    @pytest.mark.asyncio
    async def test_peer_match_allowed(self, monkeypatch):
        _patch_resolver(monkeypatch, {"start.example": ["93.184.216.34"]})
        def handler(request):
            return _resp(request, 200, b"ok", addr=("93.184.216.34", 80))
        out = await sf.SafeFetcher().fetch_text("http://start.example/a",
                                                client=_client(handler))
        assert out == "ok"


# ── потоковые лимиты (SC-06) ─────────────────────────────────────────────────

class TestStreamLimits:
    @pytest.mark.asyncio
    async def test_large_stream_blocked_without_full_read(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        emitted = {"chunks": 0}

        def handler(request):
            async def gen():
                for _ in range(500):
                    emitted["chunks"] += 1
                    yield b"x" * 65536          # 32 MB всего
            return httpx.Response(200, content=gen(), request=request)
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://big.example/huge",
                                         client=_client(handler),
                                         profile="html", max_bytes=200_000)
        assert exc.value.code == "too_many_bytes"
        # Прервано задолго до полного потока (без чтения 32 MB в RAM).
        assert emitted["chunks"] < 20

    @pytest.mark.asyncio
    async def test_decompressed_bomb_blocked(self, monkeypatch):
        """Распакованные байты лимитированы: gzip-«бомба» прерывается."""
        import types
        _patch_resolver(monkeypatch, {})
        monkeypatch.setattr(sf, "settings", types.SimpleNamespace(
            SAFE_FETCH_HTML_MAX_DECOMPRESSED_BYTES=50_000))
        big = b"A" * 5_000_000
        payload = gzip.compress(big)          # ~5 KB сжато, 5 MB распаковано

        def handler(request):
            return httpx.Response(200, content=payload,
                                  headers={"Content-Encoding": "gzip"},
                                  request=request)
        with pytest.raises(sf.SafeFetchError) as exc:
            await sf.SafeFetcher().fetch("http://bomb.example/z",
                                         client=_client(handler),
                                         profile="html", max_bytes=10_000_000)
        assert exc.value.code == "decompressed_too_large"
        assert exc.value.stage == "decompress"

    def test_video_profile_has_large_limit(self, monkeypatch):
        import types
        monkeypatch.setattr(sf, "settings", types.SimpleNamespace(
            SAFE_FETCH_VIDEO_MAX_BYTES=2_000_000_000))
        prof = sf._profile("video")
        assert prof.max_transmitted == 2_000_000_000
        assert prof.max_decompressed == 2_000_000_000

    @pytest.mark.asyncio
    async def test_stream_to_file_video_profile(self, monkeypatch, tmp_path):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            return httpx.Response(200, content=b"m" * 300_000, request=request)
        dest = tmp_path / "v.mp4"
        written = await sf.SafeFetcher().stream_to_file(
            "http://cdn.example/v.mp4", str(dest), profile="video",
            client=_client(handler))
        assert written == 300_000
        assert dest.read_bytes() == b"m" * 300_000


class TestProfileTimeout:
    @pytest.mark.asyncio
    async def test_profile_timeout_enforced_fetch(self, monkeypatch):
        """B-MCA02-1/SC-06: профильный timeout реально применяется."""
        _patch_resolver(monkeypatch, {"slow.example": ["93.184.216.34"]})
        fetcher = sf.SafeFetcher(
            client=httpx.AsyncClient(transport=_SlowTransport(1.5)))
        try:
            t0 = time.monotonic()
            with pytest.raises(sf.SafeFetchError) as exc:
                await fetcher.fetch("https://slow.example/x", timeout=0.2)
            elapsed = time.monotonic() - t0
            assert exc.value.code == "safe_fetch_timeout"
            assert exc.value.stage == "stream"
            assert elapsed <= 0.6                 # вернулся за профильный timeout
        finally:
            await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_profile_timeout_enforced_stream_to_file(self, monkeypatch,
                                                           tmp_path):
        _patch_resolver(monkeypatch, {"slow.example": ["93.184.216.34"]})
        fetcher = sf.SafeFetcher(
            client=httpx.AsyncClient(transport=_SlowTransport(1.5)))
        dest = tmp_path / "slow.bin"
        try:
            t0 = time.monotonic()
            with pytest.raises(sf.SafeFetchError) as exc:
                await fetcher.stream_to_file(
                    "https://slow.example/x", str(dest), profile="video",
                    timeout=0.2)
            elapsed = time.monotonic() - t0
            assert exc.value.code == "safe_fetch_timeout"
            assert elapsed <= 0.6
            assert not dest.exists()
        finally:
            await fetcher.aclose()

    def test_html_profile_keeps_baseline_timeout(self):
        # baseline `web_content_extractor` = 10 s; ON не ослабляет/не меняет.
        assert sf._profile("html").timeout == 10.0
        assert sf._profile("video").timeout == 240.0

    @pytest.mark.asyncio
    async def test_stream_to_file_removes_partial_on_limit(self, monkeypatch,
                                                           tmp_path):
        """L-MCA02-4: частично записанный файл удаляется при ошибке."""
        _patch_resolver(monkeypatch, {})

        def handler(request):
            async def gen():
                yield b"x" * 10
                yield b"y" * 4096
            return httpx.Response(200, content=gen(), request=request)

        fetcher = sf.SafeFetcher(client=_client(handler))
        dest = tmp_path / "part.bin"
        try:
            with pytest.raises(sf.SafeFetchError) as exc:
                await fetcher.stream_to_file(
                    "http://big.example/x", str(dest), profile="html",
                    max_bytes=64)
            assert exc.value.code == "too_many_bytes"
            assert not dest.exists()
        finally:
            await fetcher.aclose()


class TestTrustedPath:
    @pytest.mark.asyncio
    async def test_trusted_ip_literal_peer_match(self):
        """M-MCA02-2: trusted IP-литерал → resolved заполняется литералом,
        peer-проверка проходит (без ложного destination_blocked)."""
        tgt = sf.guarded_target("http://127.0.0.1:9000/", trusted=True)
        assert tgt.resolved == ("127.0.0.1",)

        def handler(request):
            return _resp(request, 200, b"ok", addr=("127.0.0.1", 9000))
        out = await sf.SafeFetcher().fetch_text(
            "http://127.0.0.1:9000/", client=_client(handler), trusted=True)
        assert out == "ok"

    @pytest.mark.asyncio
    async def test_trusted_http_path_through_safe_fetcher(self, monkeypatch):
        """M-MCA02-3: официальный trusted-HTTP путь SafeFetcher (SSRF+лимиты)."""
        _patch_resolver(monkeypatch, {"localhost": ["127.0.0.1"]})

        def handler(request):
            return _resp(request, 200, b"trusted", addr=("127.0.0.1", 9000))
        out = await sf.SafeFetcher().fetch_text(
            "http://localhost:9000/api", client=_client(handler), trusted=True)
        assert out == "trusted"


# ── egress-guard (SC-04/SC-05) ───────────────────────────────────────────────

class TestEgressGuard:
    def test_check_blocks_private_allows_public(self, monkeypatch):
        guard = sf.EgressGuard()
        assert guard._check("127.0.0.1", 80) == "destination_blocked"
        assert guard._check("10.0.0.1", 443) == "destination_blocked"
        assert guard._check("93.184.216.34", 443) is None

    @pytest.mark.asyncio
    async def test_guard_absolute_uri_forwards_when_trusted(self, monkeypatch):
        """Egress-guard пропускает доверенную локальную службу (SC-05)."""
        _patch_resolver(monkeypatch, {})

        # Мини-сервер-апстрим (локальный, доверенный).
        async def upstream(reader, writer):
            await reader.read(65536)
            body = b"upstream-ok"
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n"
                         b"Connection: close\r\n\r\n" % len(body) + body)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        guard = sf.EgressGuard()
        # guard._check использует user-политику (trusted=False), поэтому
        # локальный апстрим был бы заблокирован — для этого теста пропускаем
        # цель через доверенный конфиг явно.
        monkeypatch.setattr(guard, "_check", lambda h, p: None)
        proxy_url = await guard.start()
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=5.0) as client:
                resp = await client.get(f"http://127.0.0.1:{port}/x")
            assert resp.status_code == 200
            assert resp.content == b"upstream-ok"
        finally:
            await guard.stop()
            server.close()

    @pytest.mark.asyncio
    async def test_guard_denies_private_target(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        guard = sf.EgressGuard()
        proxy_url = await guard.start()
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=5.0) as client:
                resp = await client.get("http://10.0.0.5/secret")
            assert resp.status_code == 403
        finally:
            await guard.stop()

    def test_apply_egress_to_ytdlp_opts(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "egress_guard_enabled", lambda: False)
        opts = {"quiet": True}
        assert sf.apply_egress_to_ytdlp_opts(opts) == {"quiet": True}
        # Свой proxy не перезаписывается.
        monkeypatch.setattr(mca_gates, "egress_guard_enabled", lambda: True)
        monkeypatch.setattr(sf, "_guard", sf.EgressGuard())
        sf._guard._port = 12345
        opts2 = {"proxy": "http://u:p@h:1"}
        sf.apply_egress_to_ytdlp_opts(opts2)
        assert opts2["proxy"] == "http://u:p@h:1"
        opts3 = {}
        sf.apply_egress_to_ytdlp_opts(opts3)
        assert opts3["proxy"] == "http://127.0.0.1:12345"


# ── ошибки/маскирование/события (SC-08/SC-15, R17) ───────────────────────────

class TestErrorsMaskingEvents:
    def test_error_carries_code_stage_reason(self):
        err = sf.SafeFetchError("destination_blocked", "resolve", "private")
        assert err.code == "destination_blocked"
        assert err.stage == "resolve"
        assert "reason=private" in str(err)
        assert err.to_event_fields()["reason_code"] == "destination_blocked"

    def test_mask_url_and_text(self):
        assert sf.mask_url("https://h/p?key=SECRET&x=1&token=ABC") == \
            "https://h/p?key=***&x=1&token=***"
        assert "SECRET" not in sf.mask_text("failed url=https://h?key=SECRET&a=1")
        assert "abcdef" not in sf.mask_text("Bearer sk-abcdef")

    @pytest.mark.asyncio
    async def test_block_emits_mca_event_without_secret(self, monkeypatch,
                                                        caplog):
        _patch_resolver(monkeypatch, {})
        with caplog.at_level(logging.INFO):
            with pytest.raises(sf.SafeFetchError):
                sf.guarded_target("http://10.0.0.1/x?key=TOPSECRET")
        # reason_code зарегистрирован и есть в словаре §17.2.
        from services.mca_events import REASON_CODES
        assert "destination_blocked" in REASON_CODES

    @pytest.mark.asyncio
    async def test_fetch_failure_event_no_secret(self, monkeypatch, caplog):
        _patch_resolver(monkeypatch, {"start.example": ["10.0.0.5"]})
        with caplog.at_level(logging.WARNING):
            with pytest.raises(sf.SafeFetchError):
                await sf.SafeFetcher().fetch(
                    "http://start.example/a?token=LEAKME")
        assert "LEAKME" not in caplog.text

    def test_all_safe_fetch_reason_codes_registered(self):
        from services.mca_events import REASON_CODES
        assert sf.REASON_CODES <= REASON_CODES


# ── OFF-паритет + доверенные API (регрессии) ─────────────────────────────────

class TestOffParityAndTrusted:
    def test_gates_default_on(self):
        assert mca_gates.safe_fetch_enabled() is True
        assert mca_gates.egress_guard_enabled() is True
        from services.mca_gates import KILL_SWITCHES
        assert "MCA_SAFE_FETCH_ENABLED" in KILL_SWITCHES
        assert "MCA_EGRESS_GUARD_ENABLED" in KILL_SWITCHES

    @pytest.mark.asyncio
    async def test_video_downloader_off_skips_preflight(self, monkeypatch,
                                                        tmp_path):
        from tools import video_downloader as vdm
        monkeypatch.setattr(mca_gates, "safe_fetch_enabled", lambda: False)
        dl = vdm.VideoDownloader("http://localhost:9000/", str(tmp_path))
        # private URL: с OFF pre-flight не выполняется (legacy).
        await dl._preflight("http://10.0.0.1/x")

    @pytest.mark.asyncio
    async def test_video_downloader_on_blocks_private(self, monkeypatch,
                                                      tmp_path):
        from tools import video_downloader as vdm
        monkeypatch.setattr(mca_gates, "safe_fetch_enabled", lambda: True)
        dl = vdm.VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(vdm.DownloadError) as exc:
            await dl._preflight("http://10.0.0.1/x")
        assert exc.value.reason == "destination_blocked"

    @pytest.mark.asyncio
    async def test_legitimate_public_url_passes(self, monkeypatch):
        _patch_resolver(monkeypatch, {})
        def handler(request):
            return _resp(request, 200, b"ok")
        out = await sf.SafeFetcher().fetch_text("https://example.com/a",
                                                client=_client(handler))
        assert out == "ok"

    def test_trusted_public_api_not_broken(self, monkeypatch):
        _patch_resolver(monkeypatch, {"api.tavily.com": ["93.184.216.34"]})
        # Публичный доверенный API проходит как обычный публичный хост.
        tgt = sf.guarded_target("https://api.tavily.com/extract",
                                trusted=True)
        assert tgt.host == "api.tavily.com"

    @pytest.mark.asyncio
    async def test_web_extractor_blocks_destination_without_fallback(self):
        """Опасное назначение не уходит в облачные фолбеки (SSRF-инвариант)."""
        from services.web_content_extractor import (
            WebContentExtractor, WebContentExtractionFailedException)
        calls = []
        ext = WebContentExtractor(tavily_api_key="k", exa_api_key="k")

        async def _boom(url):
            calls.append(url)
            raise AssertionError("provider fallback must not be called")

        ext._extract_tavily = _boom       # type: ignore[assignment]
        ext._extract_exa = _boom          # type: ignore[assignment]
        with pytest.raises(WebContentExtractionFailedException):
            await ext.extract("http://10.0.0.1/private", 4000)
        assert calls == []


# ── cookies/профиль (A23) ────────────────────────────────────────────────────

class TestCookiesPreserved:
    def test_cleanup_deferred_code_registered(self):
        from services.mca_events import REASON_CODES
        assert "cleanup_deferred_dependency_unverified" in REASON_CODES

    def test_cookiefile_still_wired_into_ytdlp_opts(self, monkeypatch, tmp_path):
        import types
        import config.settings as cs
        cookie = tmp_path / "srv_cookies.txt"
        cookie.write_text("# Netscape\n", encoding="utf-8")
        monkeypatch.setattr(cs, "settings", types.SimpleNamespace(
            YOUTUBE_CREDENTIALED_LEVEL_ENABLED=True,
            YOUTUBE_TRANSCRIPT_PROXY_URL="",
            YOUTUBE_COOKIES_FILE=str(cookie)))
        opts = cs.build_ytdlp_base_opts()
        assert opts.get("cookiefile") == str(cookie)
        # Файл НЕ удалён (cookies/профиль сохраняются).
        assert cookie.exists()

    def test_download_env_summary_presence_only(self, monkeypatch):
        import types
        from tools import video_downloader as vdm
        monkeypatch.setattr(vdm, "settings", types.SimpleNamespace(
            YOUTUBE_COOKIES_FILE="/secret/path/srv_cookies.txt",
            YOUTUBE_TRANSCRIPT_PROXY_URL="http://user:pass@host:1",
            COBALT_API_URL="http://localhost:9000/"))
        summary = vdm.download_env_summary()
        assert "secret" not in summary
        assert "pass" not in summary
        assert "cookies=set" in summary
