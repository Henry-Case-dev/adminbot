"""Раунд 10.16 (F1, T-1630/T-1631) — download-контракт + probe-фоллбэк.

Покрытие spec §6: tool `download_media` без `"direct"`, `_normalize_quality`
(None/auto/best/direct→max, 1080p→1080, мусор→invalid_quality без сети),
ветвление direct/YouTube/cobalt в `download()`, классы probe-причин (R17),
env-preflight presence, Fast-Track bounded fallback. Без сети — моки
yt-dlp/cobalt/httpx.
"""
import json
import logging
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from handlers import video_download as vd
from handlers import youtube as yt
from services import hot_config as hot
from services.smartmodule_throttling import CooldownTracker
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from tools import video_downloader as vdm
from tools.video_download_phrases import (
    VD_SERVICE_DOWN_PHRASES,
    VD_UNAVAILABLE_PHRASES,
)
from tools.video_downloader import (
    CobaltServiceDownError,
    DownloadBusyError,
    DownloadError,
    DownloadTooBigError,
    DownloadUnavailableError,
    VideoDownloader,
    is_direct_media_url,
)

CHAT_ID = -1001234567890
USER_ID = 10
_YT = "https://youtu.be/ABCDEFGHIJK"
_TIKTOK = "https://www.tiktok.com/@user/video/1234567890"
_MP4 = "https://cdn.example.com/secret-clip-777.mp4"


# ── фейки ────────────────────────────────────────────────────────────────


class _FakeBot:
    def __init__(self):
        self.sent_video = []
        self.sent_document = []
        self.send_message = AsyncMock(
            return_value=SimpleNamespace(message_id=42))
        self.edit_message_text = AsyncMock()
        self.delete_message = AsyncMock()

    async def send_video(self, chat_id, file, **kwargs):
        self.sent_video.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)

    async def send_document(self, chat_id, file, **kwargs):
        self.sent_document.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)


def _msg(text, message_id=100, user_id=USER_ID):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = SimpleNamespace(id=CHAT_ID)
    msg.from_user = SimpleNamespace(id=user_id)
    msg.reply = AsyncMock(return_value=SimpleNamespace(message_id=999))
    msg.video = None
    msg.document = None
    msg.reply_to_message = None
    return msg


def _deps(**kwargs) -> ToolDeps:
    kwargs.setdefault("search", MagicMock())
    kwargs.setdefault("memory", MagicMock())
    return ToolDeps(**kwargs)


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(CHAT_ID, "свободная форма", **kwargs)


def _gate(monkeypatch, enabled):
    real_get = hot.get
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: enabled
        if key == "flags.download_enabled" else real_get(key, default))


# ── 1. tool download_media: platform/direct, без "direct" ────────────────


class TestToolDownload:
    @pytest.mark.asyncio
    async def test_platform_url_passes_auto_no_direct(self, monkeypatch,
                                                      tmp_path):
        _gate(monkeypatch, True)
        path = tmp_path / "yt.mp4"
        path.write_bytes(b"data")
        downloader = MagicMock()
        downloader.download = AsyncMock(return_value=path)
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _YT},
                                    _ctx(bot=_FakeBot()))
        assert json.loads(out)["status"] == "success"
        downloader.download.assert_awaited_once_with(_YT)

    @pytest.mark.asyncio
    async def test_direct_mp4_still_works(self, monkeypatch, tmp_path):
        _gate(monkeypatch, True)
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"data")
        downloader = MagicMock()
        downloader.download = AsyncMock(return_value=path)
        bot = _FakeBot()
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _MP4},
                                    _ctx(bot=bot))
        assert json.loads(out)["status"] == "success"
        downloader.download.assert_awaited_once_with(_MP4)
        assert len(bot.sent_video) == 1

    @pytest.mark.asyncio
    async def test_failure_logs_reason_not_url(self, monkeypatch, caplog):
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.download = AsyncMock(
            side_effect=DownloadError("failed " + _MP4,
                                      reason="invalid_quality"))
        router = ToolRouter(_deps(downloader=downloader))
        with caplog.at_level(logging.WARNING):
            out = await router.dispatch("download_media", {"url": _MP4},
                                        _ctx(bot=_FakeBot()))
        assert json.loads(out)["status"] == "error"
        assert "reason=invalid_quality" in caplog.text
        assert "secret-clip" not in caplog.text
        assert "cdn.example.com" not in caplog.text


# ── 2. _normalize_quality ────────────────────────────────────────────────


class TestNormalizeQuality:
    @pytest.mark.parametrize("value", [None, "", "auto", "best", "max",
                                       "direct", "DIRECT", " Auto "])
    def test_auto_variants_to_max(self, value):
        assert VideoDownloader._normalize_quality(value) == "max"

    @pytest.mark.parametrize("value,expected",
                             [("1080p", "1080"), ("1080", "1080"),
                              (1080, "1080"), ("720P", "720"), ("360", "360")])
    def test_height_variants(self, value, expected):
        assert VideoDownloader._normalize_quality(value) == expected

    @pytest.mark.parametrize("value", ["p", "abc", "10x80", "p1080p2"])
    def test_garbage_invalid_quality_without_network(self, value):
        """Мусор → DownloadError(reason=invalid_quality) до похода в сеть."""
        with pytest.raises(DownloadError) as exc:
            VideoDownloader._normalize_quality(value)
        assert exc.value.reason == "invalid_quality"

    def test_cobalt_garbage_never_calls_network(self, tmp_path):
        """_request_tunnel с мусором → DownloadError до aiohttp (мок не нужен)."""
        import asyncio

        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadError) as exc:
            asyncio.run(dl._request_tunnel("https://x/a", "junk"))
        assert exc.value.reason == "invalid_quality"


# ── 3. download(): ветвление direct/YouTube/cobalt ───────────────────────


class TestDownloadRouting:
    def _dl(self, tmp_path):
        return VideoDownloader("http://localhost:9000/", str(tmp_path))

    def _no_yt(self, monkeypatch):
        real = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: False
            if key == "flags.ytdlp_for_youtube" else real(key, default))

    def _yes_yt(self, monkeypatch):
        real = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: True
            if key == "flags.ytdlp_for_youtube" else real(key, default))

    @pytest.mark.asyncio
    async def test_direct_url_ignores_quality(self, tmp_path, monkeypatch):
        dl = self._dl(tmp_path)
        out = tmp_path / "d.mp4"
        out.write_bytes(b"x")
        called = {}

        async def fake_direct(url, progress_cb=None):
            called["url"] = url
            return out

        monkeypatch.setattr(dl, "download_direct", fake_direct)
        monkeypatch.setattr(dl, "download_ytdlp", AsyncMock(
            side_effect=AssertionError("ytdlp не должен вызываться")))
        result = await dl.download(_MP4 + "?t=1", "1080")
        assert result == out and called["url"].startswith(_MP4)

    @pytest.mark.asyncio
    async def test_youtube_auto_quality_max(self, tmp_path, monkeypatch):
        self._yes_yt(monkeypatch)
        dl = self._dl(tmp_path)
        out = tmp_path / "yt.mp4"
        out.write_bytes(b"x")
        seen = {}

        async def fake_ytdlp(url, quality, progress_cb=None):
            seen["quality"] = quality
            return out

        monkeypatch.setattr(dl, "download_ytdlp", fake_ytdlp)
        assert await dl.download(_YT, None) == out
        assert seen["quality"] == "max"

    @pytest.mark.asyncio
    async def test_youtube_legacy_direct_alias_is_max(self, tmp_path,
                                                      monkeypatch):
        """Регресс-защита: legacy «direct» больше не роняет платформу."""
        self._yes_yt(monkeypatch)
        dl = self._dl(tmp_path)
        out = tmp_path / "yt2.mp4"
        out.write_bytes(b"x")
        seen = {}

        async def fake_ytdlp(url, quality, progress_cb=None):
            seen["quality"] = quality
            return out

        monkeypatch.setattr(dl, "download_ytdlp", fake_ytdlp)
        assert await dl.download(_YT, "direct") == out
        assert seen["quality"] == "max"

    @pytest.mark.asyncio
    async def test_platform_uses_cobalt_max(self, tmp_path, monkeypatch):
        self._no_yt(monkeypatch)
        dl = self._dl(tmp_path)
        out = tmp_path / "tt.mp4"
        out.write_bytes(b"x")
        seen = {}

        async def fake_tunnel(url, quality):
            seen["quality"] = quality
            return "http://tunnel/x", None

        async def fake_stream(tunnel, filename):
            return out

        monkeypatch.setattr(dl, "_request_tunnel", fake_tunnel)
        monkeypatch.setattr(dl, "_stream_to_file", fake_stream)
        assert await dl.download(_TIKTOK, None) == out
        assert seen["quality"] == "max"

    @pytest.mark.asyncio
    async def test_youtube_height_quality(self, tmp_path, monkeypatch):
        self._yes_yt(monkeypatch)
        dl = self._dl(tmp_path)
        out = tmp_path / "yt3.mp4"
        out.write_bytes(b"x")
        seen = {}

        async def fake_ytdlp(url, quality, progress_cb=None):
            seen["quality"] = quality
            return out

        monkeypatch.setattr(dl, "download_ytdlp", fake_ytdlp)
        await dl.download(_YT, "1080p")
        assert seen["quality"] == "1080"

    @pytest.mark.asyncio
    async def test_unknown_quality_no_network(self, tmp_path, monkeypatch):
        self._no_yt(monkeypatch)
        dl = self._dl(tmp_path)
        monkeypatch.setattr(dl, "_request_tunnel", AsyncMock(
            side_effect=AssertionError("сеть не должна трогаться")))
        with pytest.raises(DownloadError) as exc:
            await dl.download(_TIKTOK, "мусор")
        assert exc.value.reason == "invalid_quality"


# ── 4. probe-классификация (R17 reason) ──────────────────────────────────


def _patch_ytdlp(monkeypatch, exc=None, sleep=0.0):
    import asyncio
    import sys
    import types

    class _YDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download=False):
            if sleep:
                import time
                time.sleep(sleep)
            if exc is not None:
                raise exc
            return {"title": "t", "formats": []}

    monkeypatch.setitem(sys.modules, "yt_dlp",
                        types.SimpleNamespace(YoutubeDL=_YDL))


class TestProbeClassification:
    @pytest.mark.asyncio
    async def test_timeout_reason(self, tmp_path, monkeypatch):
        _patch_ytdlp(monkeypatch, exc=RuntimeError("x"), sleep=0.05)
        monkeypatch.setattr(vdm, "_PROBE_TIMEOUT_SECONDS", 0.01)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadError) as exc:
            await dl.probe(_YT)
        assert exc.value.reason == "probe_timeout"

    @pytest.mark.asyncio
    async def test_bot_check_reason(self, tmp_path, monkeypatch):
        _patch_ytdlp(monkeypatch, exc=RuntimeError(
            "Sign in to confirm you're not a bot"))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadUnavailableError) as exc:
            await dl.probe(_YT)
        assert exc.value.reason == "probe_bot_check"

    @pytest.mark.asyncio
    async def test_generic_reason(self, tmp_path, monkeypatch):
        _patch_ytdlp(monkeypatch, exc=RuntimeError("unexpected boom"))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadError) as exc:
            await dl.probe(_YT)
        assert exc.value.reason == "probe_failed"


# ── 5. reason-атрибуты классов ───────────────────────────────────────────


class TestReasonAttributes:
    def test_subclass_defaults(self):
        assert DownloadBusyError("x").reason == "busy"
        assert DownloadTooBigError("x").reason == "direct_too_big"
        assert CobaltServiceDownError("x").reason == "cobalt_down"
        assert DownloadUnavailableError("x").reason == "ytdlp_unavailable"
        assert DownloadError("x").reason == "unknown"

    def test_explicit_reason_wins(self):
        assert DownloadError("x", reason="ytdlp_drm").reason == "ytdlp_drm"


# ── 6. env-preflight presence (R17: без значений) ────────────────────────


class TestEnvPreflight:
    def test_summary_presence_without_values(self, monkeypatch):
        # Ревью-итер.1 (Low): POT — из единого хелпера settings, не os.getenv.
        monkeypatch.setattr(vdm, "settings", SimpleNamespace(
            YOUTUBE_COOKIES_FILE="/etc/secret-cookies.txt",
            YOUTUBE_TRANSCRIPT_PROXY_URL="",
            COBALT_API_URL="http://cobalt:9000/"))
        monkeypatch.setattr(vdm, "get_ytdlp_pot_provider",
                            lambda: "bgutil:http")
        summary = vdm.download_env_summary()
        assert "cookies=set" in summary
        assert "proxy=absent" in summary
        assert "pot=set" in summary
        assert "cobalt=set" in summary
        assert "secret-cookies" not in summary
        assert "bgutil" not in summary

    def test_log_once_flag(self, monkeypatch, caplog):
        monkeypatch.setattr(vdm, "_ENV_LOGGED", False)
        monkeypatch.setattr(vdm, "settings", SimpleNamespace(
            YOUTUBE_COOKIES_FILE="", YOUTUBE_TRANSCRIPT_PROXY_URL="",
            COBALT_API_URL=""))
        monkeypatch.setattr(vdm, "get_ytdlp_pot_provider", lambda: "")
        with caplog.at_level(logging.WARNING):
            vdm.log_download_env_once()
            vdm.log_download_env_once()
        assert caplog.text.count("[videodl] env |") == 1


# ── 7. Fast-Track bounded probe-fallback ─────────────────────────────────


class TestFastTrackFallback:
    def _setup(self, monkeypatch, tmp_path, download_side_effect=None,
               download_return=None):
        # R10.15-4: хендлер гейтит master-флаг (в тест-env дефолт False) —
        # прямые вызовы хендлера требуют включённого флага (как боевой .env).
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.busy = False
        downloader.probe = AsyncMock(
            side_effect=DownloadError("probe boom", reason="probe_failed"))
        downloader.download = AsyncMock(
            side_effect=download_side_effect, return_value=download_return)
        monkeypatch.setattr(vd, "_downloader", downloader)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(1800.0))
        return downloader

    @pytest.mark.asyncio
    async def test_probe_fail_fallback_success_no_menu(self, monkeypatch,
                                                       tmp_path):
        out = tmp_path / "fb.mp4"
        out.write_bytes(b"x")
        downloader = self._setup(monkeypatch, tmp_path, download_return=out)
        bot = _FakeBot()
        result = await vd.video_download_handler(
            _msg(f"Бот, скачай {_TIKTOK}"), bot)
        assert result is None
        downloader.download.assert_awaited_once_with(
            _TIKTOK, None, progress_cb=ANY)
        assert len(bot.sent_video) == 1
        # меню качества НЕ слалось (нет сообщений с inline-клавиатурой)
        for call in bot.send_message.call_args_list:
            assert "reply_markup" not in call.kwargs
        assert (CHAT_ID, USER_ID) in vd._cooldown._last  # успех → touch

    @pytest.mark.asyncio
    async def test_probe_fail_fallback_fail_no_cooldown(self, monkeypatch,
                                                        tmp_path):
        self._setup(monkeypatch, tmp_path, download_side_effect=DownloadError(
            "cobalt down", reason="cobalt_down"))
        bot = _FakeBot()
        await vd.video_download_handler(_msg(f"Бот, скачай {_TIKTOK}"), bot)
        # probe-fail (и провал fallback) кулдаун НЕ жгут
        assert (CHAT_ID, USER_ID) not in vd._cooldown._last
        # классифицированная фраза service-down, а не «битая ссылка»
        texts = [c.args[2] for c in bot.edit_message_text.call_args_list]
        assert any(t in VD_SERVICE_DOWN_PHRASES for t in texts)

    @pytest.mark.asyncio
    async def test_probe_bot_check_phrase_available(self, monkeypatch,
                                                    tmp_path):
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.busy = False
        downloader.probe = AsyncMock(side_effect=DownloadUnavailableError(
            "bot", reason="probe_bot_check"))
        downloader.download = AsyncMock(
            side_effect=DownloadError("nope", reason="probe_bot_check"))
        monkeypatch.setattr(vd, "_downloader", downloader)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(1800.0))
        bot = _FakeBot()
        await vd.video_download_handler(_msg(f"Бот, скачай {_YT}"), bot)
        texts = [c.args[2] for c in bot.edit_message_text.call_args_list]
        assert any(t in VD_UNAVAILABLE_PHRASES for t in texts)

    @pytest.mark.asyncio
    async def test_probe_fail_logs_reason_without_url(self, monkeypatch,
                                                      caplog):
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.busy = False
        downloader.probe = AsyncMock(side_effect=DownloadError(
            f"probe failed {_YT}", reason="probe_failed"))
        downloader.download = AsyncMock(
            side_effect=DownloadError("boom", reason="cobalt_down"))
        monkeypatch.setattr(vd, "_downloader", downloader)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(1800.0))
        with caplog.at_level(logging.WARNING):
            await vd.video_download_handler(_msg(f"Бот, скачай {_YT}"),
                                            _FakeBot())
        assert "reason=probe_failed" in caplog.text
        assert "youtu.be" not in caplog.text


# ── 8. is_direct_media_url: платформа vs direct ──────────────────────────


class TestDirectDetection:
    def test_platform_never_direct(self):
        assert not is_direct_media_url(_TIKTOK + "/file.mp4")
        assert not is_direct_media_url(_YT + ".mp4")

    def test_plain_direct(self):
        assert is_direct_media_url(_MP4 + "?token=1")


# ── 9. R17: секреты/URL/str(exc)/тело не попадают в логи (ревью-итер.1) ──

_SECRET_URL = ("https://cdn.example.com/secret-token-abc.mp4"
               "?key=TOPSECRETSIGNATURE")


def _direct_client(statuses):
    """Fake httpx.AsyncClient: последовательность статусов, затем 200+тело."""
    class _Resp:
        def __init__(self, status):
            self.status_code = status
            self.headers = {"content-length": "3"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def aiter_bytes(self, n):
            async def _gen():
                yield b"abc"
            return _gen()

    class _Client:
        calls = 0

        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, headers=None):
            idx = min(type(self).calls, len(statuses) - 1)
            type(self).calls += 1
            return _Resp(statuses[idx])

    _Client.calls = 0
    return _Client


class _FakeHttpResp:
    def __init__(self, status, read):
        self.status = status
        self.content = SimpleNamespace(read=read)


class TestNoSecretsLogging:
    @pytest.mark.asyncio
    async def test_no_secrets_logging(self, tmp_path, monkeypatch, caplog):
        """R17 (ревью-итер.1, High): прямой стрим и cobalt-http логируются
        без URL/query-токенов/тела ответа."""
        monkeypatch.setattr(vdm.httpx, "AsyncClient",
                            _direct_client([200]))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with caplog.at_level(logging.INFO, logger="tools.video_downloader"):
            await dl.download_direct(_SECRET_URL)
        assert "direct downloaded" in caplog.text
        assert "bytes=3" in caplog.text
        for leak in ("secret-token-abc", "cdn.example.com",
                     "TOPSECRETSIGNATURE", _SECRET_URL):
            assert leak not in caplog.text, leak

    @pytest.mark.asyncio
    async def test_direct_403_retry_logs_no_url(self, tmp_path, monkeypatch,
                                                caplog):
        monkeypatch.setattr(vdm.httpx, "AsyncClient",
                            _direct_client([403, 403]))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with caplog.at_level(logging.WARNING, logger="tools.video_downloader"):
            with pytest.raises(DownloadError):
                await dl.download_direct(_SECRET_URL)
        assert "direct 403" in caplog.text
        assert "cdn.example.com" not in caplog.text
        assert "TOPSECRETSIGNATURE" not in caplog.text

    @pytest.mark.asyncio
    async def test_raise_sites_do_not_embed_url(self, tmp_path, monkeypatch):
        """S10.16-1 (Info-1, defense-in-depth): тексты DownloadError/
        DownloadTooBigError/DownloadUnavailableError НЕ содержат URL/токенов —
        иначе будущий `logger.*(..., exc)`/`exc_info` вернёт утечку."""
        # direct HTTP 4xx
        monkeypatch.setattr(vdm.httpx, "AsyncClient",
                            _direct_client([500]))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadError) as exc:
            await dl.download_direct(_SECRET_URL)
        assert "cdn.example.com" not in str(exc.value)
        assert "TOPSECRETSIGNATURE" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_direct_too_big_text_has_no_url(self, tmp_path, monkeypatch):
        """S10.16-1: DownloadTooBigError прямого стрима — без URL в тексте."""
        monkeypatch.setattr(vdm, "_DIRECT_MAX_BYTES", 2)
        monkeypatch.setattr(vdm.httpx, "AsyncClient",
                            _direct_client([200]))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadTooBigError) as exc:
            await dl.download_direct(_SECRET_URL)
        assert exc.value.reason == "direct_too_big"
        assert "cdn.example.com" not in str(exc.value)
        assert "TOPSECRETSIGNATURE" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_http_error_body_not_logged(self, caplog):
        body = ('{"error":{"code":"x"},"msg":"' + _SECRET_URL + '"}')

        async def _read(n):
            return body.encode()

        with caplog.at_level(logging.ERROR, logger="tools.video_downloader"):
            err = await VideoDownloader._http_error(
                _FakeHttpResp(403, _read))
        assert err.reason == "tunnel_http"
        assert "cobalt http 403" in caplog.text
        assert "code=x" in caplog.text
        assert "body_chars=" in caplog.text
        for leak in ("cdn.example.com", "TOPSECRETSIGNATURE", _SECRET_URL):
            assert leak not in caplog.text, leak

    @pytest.mark.asyncio
    async def test_http_error_unreadable_body_no_exc_text(self, caplog):
        async def _read(n):
            raise RuntimeError("boom " + _SECRET_URL)

        with caplog.at_level(logging.ERROR, logger="tools.video_downloader"):
            err = await VideoDownloader._http_error(
                _FakeHttpResp(502, _read))
        assert err.reason == "tunnel_http"
        assert "RuntimeError" in caplog.text
        assert "cdn.example.com" not in caplog.text
        assert "TOPSECRETSIGNATURE" not in caplog.text

    @pytest.mark.asyncio
    async def test_stream_too_big_reason_and_no_url(self, tmp_path, monkeypatch):
        """Medium: единый корректный reason для too-big в стриме."""
        monkeypatch.setattr(vdm, "VD_MAX_BYTES", 4)

        class _Content:
            def iter_chunked(self, n):
                async def _gen():
                    yield b"12345"
                return _gen()

        class _Resp:
            status = 200
            headers = {}

            def __init__(self):
                self.content = _Content()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Session:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def get(self, url):
                return _Resp()

        monkeypatch.setattr(vdm.aiohttp, "ClientSession", _Session)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadTooBigError) as exc:
            await dl._stream_attempt("https://tunnel/secret?token=TOP",
                                     tmp_path / "x.mp4")
        assert exc.value.reason == "stream_too_big"


# ── 10. _normalize_quality: диапазон высот (ревью-итер.1, Low) ───────────


class TestQualityRange:
    @pytest.mark.parametrize("bad", ["-5", "0", "1", "100", "5000", "-1080"])
    def test_out_of_range_invalid_quality(self, bad):
        with pytest.raises(DownloadError) as exc:
            VideoDownloader._normalize_quality(bad)
        assert exc.value.reason == "invalid_quality"

    @pytest.mark.parametrize("ok,expected", [("144", "144"), ("360", "360"),
                                             ("4320", "4320")])
    def test_in_range_ok(self, ok, expected):
        assert VideoDownloader._normalize_quality(ok) == expected


# ── 11. S10.16-1: R17 на youtube-пути пересказа ссылки ───────────────────


class TestYoutubePathNoSecretsLogging:
    """До фикса `_download_or_phrase` (handlers/youtube.py) логировал сам
    `str(exc)`, а тексты DownloadError/DownloadTooBigError несли `url={url}`
    (signed/CDN с query-токеном). Здесь покрываем ИМЕННО этот путь."""

    def _patch_downloader(self, monkeypatch, exc):
        class _FakeDL:
            busy = False

            async def download(self, url, quality):
                raise exc(url)

        monkeypatch.setattr(yt, "_media_downloader", _FakeDL())
        monkeypatch.setattr(yt, "_reply", AsyncMock())

    @pytest.mark.asyncio
    async def test_download_error_logs_no_url(self, monkeypatch, caplog):
        secret = ("https://cdn.example.com/v?token=TOPSECRETSIGNATURE"
                  "&sig=abc")
        # Намеренно «грязный» текст исключения (имитация legacy raise-сайта):
        # хендлер обязан логировать только класс + reason, не str(exc).
        exc = lambda url: DownloadError(f"yt-dlp failed | url={url}",
                                        reason="ytdlp_failed")
        self._patch_downloader(monkeypatch, exc)
        with caplog.at_level(logging.WARNING, logger="handlers.youtube"):
            result = await yt._download_or_phrase(
                AsyncMock(), CHAT_ID, secret, 1)
        assert result is None
        text = "\n".join(r.getMessage() for r in caplog.records
                         if r.name == "handlers.youtube")
        assert "error=DownloadError" in text
        assert "reason=ytdlp_failed" in text
        for leak in ("TOPSECRETSIGNATURE", "cdn.example.com", "sig=abc",
                     secret):
            assert leak not in text, leak
        assert "url=" not in text

    @pytest.mark.asyncio
    async def test_too_big_error_logs_no_url(self, monkeypatch, caplog):
        secret = "https://cdn.example.com/v?token=TOPSECRETSIGNATURE"
        exc = lambda url: DownloadTooBigError(
            f"file exceeds 5 bytes | url={url}", reason="ytdlp_too_big")
        self._patch_downloader(monkeypatch, exc)
        with caplog.at_level(logging.WARNING, logger="handlers.youtube"):
            result = await yt._download_or_phrase(
                AsyncMock(), CHAT_ID, secret, 1)
        assert result is None
        text = "\n".join(r.getMessage() for r in caplog.records
                         if r.name == "handlers.youtube")
        assert "error=DownloadTooBigError" in text
        assert "reason=ytdlp_too_big" in text
        for leak in ("TOPSECRETSIGNATURE", "cdn.example.com", secret):
            assert leak not in text, leak
        assert "url=" not in text
