"""Tests for Epic 66 — Cobalt Downloader (T-524/T-526/T-527, Section 70).

Триггер-парсинг, извлечение ссылок, уникальные разрешения, busy-лок,
кулдаун с remaining_time, мок Cobalt (aiohttp), удаление клавиатуры
(TelegramBadRequest → продолжение), cleanup файла в finally.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import video_download as vd
from tools.video_download_phrases import (
    VD_BUSY_PHRASES,
    VD_COOLDOWN_PHRASES,
    VD_ERROR_PHRASES,
    VD_NO_LINK_PHRASES,
)
from tools.video_downloader import (
    DownloadError,
    ProbeResult,
    VideoDownloader,
    unique_qualities,
)

CHAT_ID = -1001234567890
USER_ID = 111
URL = "https://example.com/watch?v=1"
URL2 = "https://youtu.be/dQw4w9WgXcQ"


def _make_msg(text=None, message_id=100, user_id=USER_ID, **kwargs):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.forward_origin = None          # conftest.make_message convention
    msg.media_group_id = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply = AsyncMock(return_value=MagicMock(message_id=999))
    for k, v in kwargs.items():
        setattr(msg, k, v)
    return msg


def _make_cb(data, message=None):
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = USER_ID
    if message is None:
        message = MagicMock()
        message.chat.id = CHAT_ID
        message.delete = AsyncMock()
    cb.message = message
    return cb


@pytest.fixture
def vd_env(tmp_path, monkeypatch):
    """DI: свежий VideoDownloader + чистый pending/cooldown на каждый тест."""
    old_dl, old_cd = vd._downloader, vd._cooldown
    dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "downloads"))
    vd._downloader = dl
    vd._cooldown = type(vd._cooldown)(1800.0)   # in-memory CooldownTracker(30m)
    vd._PENDING.clear()
    yield dl
    vd._downloader, vd._cooldown = old_dl, old_cd
    vd._PENDING.clear()


def _probe(title="тестовое видео", qualities=("1080p", "720p", "360p")):
    return ProbeResult(title=title, qualities=qualities)


# ── 1. Триггер-парсинг ──────────────────────────────────────────────

class TestTrigger:
    @pytest.mark.asyncio
    async def test_all_trigger_words(self, vd_env, monkeypatch):
        monkeypatch.setattr(vd._downloader, "probe",
                            AsyncMock(return_value=_probe()))
        for word in ("скачай", "загрузи", "стяни", "спизди", "скачать"):
            msg = _make_msg(f"{word} {URL}")
            result = await vd.video_download_handler(msg, bot=AsyncMock())
            assert result is None                       # consume (не UNHANDLED)

    @pytest.mark.asyncio
    async def test_case_insensitive_and_leading_ws(self, monkeypatch):
        assert vd._TRIGGER_RE.match("  СКАЧАЙ " + URL)
        assert vd._TRIGGER_RE.match("Спизди " + URL)

    @pytest.mark.asyncio
    async def test_trigger_mid_sentence_not_a_trigger(self, vd_env):
        from aiogram.dispatcher.event.bases import UNHANDLED
        msg = _make_msg(f"ну ты даешь {URL} вообще")
        result = await vd.video_download_handler(msg, bot=AsyncMock())
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    def test_download_word_without_boundary_no_match(self):
        """«скачайка»/«загрузим» — word-boundary отсекает."""
        assert not vd._TRIGGER_RE.match("скачайка")
        assert not vd._TRIGGER_RE.match("загрузим файл")


# ── 2. Извлечение ссылок ────────────────────────────────────────────

class TestUrlExtraction:
    def test_zero_links(self):
        assert vd._extract_urls(_make_msg("скачай что-нибудь")) == []

    def test_one_link_from_text(self):
        assert vd._extract_urls(_make_msg(f"скачай {URL}")) == [URL]

    def test_caption_link(self):
        assert vd._extract_urls(
            _make_msg("скачай", caption=f"глянь {URL2}")) == [URL2]

    def test_multiple_links_dedup_order(self):
        urls = vd._extract_urls(_make_msg(f"скачай {URL} и {URL2} и {URL}"))
        assert urls == [URL, URL2]

    def test_reply_message_link(self):
        target = _make_msg(f"вот: {URL}", message_id=77)
        msg = _make_msg("скачай это", reply_to_message=target)
        assert vd._extract_urls(msg) == [URL]

    def test_reply_without_text_is_safe(self):
        """MagicMock-реплай без строкового text не роняет извлечение."""
        target = MagicMock(spec=[])             # нет атрибутов вообще
        msg = _make_msg("скачай", reply_to_message=target)
        assert vd._extract_urls(msg) == []


class TestNoLinkPhrase:
    @pytest.mark.asyncio
    async def test_trigger_without_link_replies_no_link(self, vd_env):
        msg = _make_msg("скачай что-нибудь")
        await vd.video_download_handler(msg, bot=AsyncMock())
        sent = msg.reply.call_args[0][0]
        assert sent in VD_NO_LINK_PHRASES


# ── 3. Уникальные разрешения из formats ────────────────────────────

class TestUniqueQualities:
    def test_dedup_desc_audio_filtered(self):
        formats = [
            {"vcodec": "avc1.640028", "height": 720},
            {"vcodec": "avc1.640028", "height": 1080},
            {"vcodec": "none", "height": 1080},     # аудио — фильтруем
            {"vcodec": "vp9", "height": 360},
            {"vcodec": "vp9"},                      # без height
            {"format_note": "storyboard", "vcodec": "none", "height": 1080},
        ]
        assert unique_qualities(formats) == ("1080p", "720p", "360p")

    def test_intersect_with_allowed_heights(self):
        formats = [{"vcodec": "h264", "height": h} for h in (144, 240, 360, 480)]
        assert unique_qualities(formats) == ("480p", "360p")

    def test_fallback_when_no_heights(self):
        assert unique_qualities([]) == ("1080p", "720p", "360p")
        assert unique_qualities(None) == ("1080p", "720p", "360p")


# ── 4. Busy-лок → BUSY фраза БЕЗ ожидания ──────────────────────────

class TestBusyLock:
    @pytest.mark.asyncio
    async def test_busy_lock_answers_busy_phrase_immediately(
            self, vd_env, monkeypatch):
        await vd_env._lock.acquire()                # чужое скачивание «идёт»
        try:
            vd._PENDING[(CHAT_ID, USER_ID)] = {
                "urls": [URL], "probes": [_probe()], "selected": 0,
                "trigger_message_id": 100,
                "expires": time.monotonic() + 60,
            }

            async def _fail(*args, **kwargs):
                raise AssertionError("download must not be called when busy")

            monkeypatch.setattr(vd._downloader, "download",
                                AsyncMock(side_effect=_fail))
            cb = _make_cb("vd:720")
            await vd.cb_pick_quality(cb, bot=AsyncMock())
            kwargs = cb.answer.call_args
            assert kwargs.kwargs.get("show_alert") is True
            assert kwargs.args[0] in VD_BUSY_PHRASES
        finally:
            vd_env._lock.release()

    @pytest.mark.asyncio
    async def test_service_busy_property(self, vd_env):
        assert vd_env.busy is False
        await vd_env._lock.acquire()
        try:
            assert vd_env.busy is True
        finally:
            vd_env._lock.release()
        assert vd_env.busy is False


# ── 5. Кулдаун → фраза с remaining_time ─────────────────────────────

class TestCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_phrase_contains_remaining_time(self, vd_env):
        vd._cooldown._last[(CHAT_ID, USER_ID)] = time.monotonic() - 10.0
        msg = _make_msg(f"скачай {URL}")
        await vd.video_download_handler(msg, bot=AsyncMock())
        sent = msg.reply.call_args[0][0]
        assert any(p.split("{")[0] in sent for p in VD_COOLDOWN_PHRASES), sent
        assert "{" not in sent                      # плейсхолдер подставлен
        assert "мин" in sent                        # человеческий формат

    @pytest.mark.asyncio
    async def test_cooldown_expires_allows_next_request(self, vd_env, monkeypatch):
        vd._cooldown._last[(CHAT_ID, USER_ID)] = (
            time.monotonic() - 1900.0)              # 30м кулдаун истёк
        monkeypatch.setattr(vd._downloader, "probe",
                            AsyncMock(return_value=_probe()))
        msg = _make_msg(f"скачай {URL}")
        await vd.video_download_handler(msg, bot=AsyncMock())
        msg.reply.assert_not_called()               # кулдауна нет → фразы нет


# ── 6. Мок Cobalt (aiohttp): успех + ошибка ─────────────────────────

class FakeCobaltResponse:
    def __init__(self, payload=None, status=200, chunks=(b"vid", b"eo")):
        self._payload = payload
        self.status = status
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, content_type=None):
        return self._payload

    class _Content:
        def __init__(self, chunks):
            self._chunks = chunks

        async def iter_chunked(self, size):
            for chunk in self._chunks:
                yield chunk

    @property
    def content(self):
        return self._Content(self._chunks)


class FakeCobaltSession:
    behavior = {"post_payload": None, "post_response": None}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, json=None):
        FakeCobaltSession.behavior["post_payload"] = json
        resp = FakeCobaltSession.behavior["post_response"] or FakeCobaltResponse(
            payload={"status": "tunnel", "url": "http://tunnel/file.mp4"})
        return resp

    def get(self, url):
        return FakeCobaltResponse(status=200, chunks=(b"fake", b"video"))


class TestCobaltMocked:
    @pytest.mark.asyncio
    async def test_download_success_via_cobalt(self, vd_env, tmp_path,
                                               monkeypatch):
        monkeypatch.setattr(
            "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
        FakeCobaltSession.behavior["post_payload"] = None
        FakeCobaltSession.behavior["post_response"] = FakeCobaltResponse(
            payload={"status": "tunnel",
                     "url": "http://tunnel/video.mp4",
                     "filename": "cool video.mp4"})
        path = await vd_env.download(URL, "720p")
        payload = FakeCobaltSession.behavior["post_payload"]
        assert payload == {"url": URL, "videoQuality": "720p",
                           "downloadMode": "auto"}
        assert path.exists() and path.read_bytes() == b"fakevideo"
        path.unlink()

    @pytest.mark.asyncio
    async def test_cobalt_error_json_maps_to_error_phrases(
            self, vd_env, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
        FakeCobaltSession.behavior["post_response"] = FakeCobaltResponse(
            payload={"error": {"code": "bad.url"}})
        with pytest.raises(DownloadError):
            await vd_env.download(URL, "720p")

        # хендлер маппит DownloadError → пул ERROR реплаем на триггер
        vd._PENDING[(CHAT_ID, USER_ID)] = {
            "urls": [URL], "probes": [_probe()], "selected": 0,
            "trigger_message_id": 100,
            "expires": time.monotonic() + 60,
        }

        class _BrokenDownloader:
            busy = False

            async def download(self, url, quality):
                raise DownloadError("cobalt error")

        old = vd._downloader
        vd._downloader = _BrokenDownloader()
        try:
            bot = AsyncMock()
            cb = _make_cb("vd:720")
            await vd.cb_pick_quality(cb, bot=bot)
            kwargs = bot.send_message.call_args
            assert kwargs.args[1] in VD_ERROR_PHRASES
            assert kwargs.kwargs["reply_to_message_id"] == 100
        finally:
            vd._downloader = old


# ── 7. Выбор качества: удаление клавиатуры ──────────────────────────

def _seed_pending():
    vd._PENDING[(CHAT_ID, USER_ID)] = {
        "urls": [URL], "probes": [_probe()], "selected": 0,
        "trigger_message_id": 100,
        "expires": time.monotonic() + 600,
    }


class TestKeyboardDelete:
    @pytest.mark.asyncio
    async def test_delete_success_then_video_sent_as_reply(self, vd_env,
                                                           tmp_path):
        f = tmp_path / "out.mp4"
        f.write_bytes(b"x" * 32)
        dl_mock = AsyncMock(return_value=f)
        monkey_target = vd._downloader
        monkey_target.download = dl_mock
        _seed_pending()
        bot = AsyncMock()
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        cb.message.delete.assert_awaited_once()
        send_kwargs = bot.send_video.call_args.kwargs
        assert send_kwargs["supports_streaming"] is True
        assert send_kwargs["reply_to_message_id"] == 100
        assert not f.exists()                       # cleanup в finally

    @pytest.mark.asyncio
    async def test_telegram_bad_request_reply_rights_but_download_continues(
            self, vd_env, tmp_path):
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods.base import TelegramMethod

        f = tmp_path / "out2.mp4"
        f.write_bytes(b"y" * 32)
        vd._downloader.download = AsyncMock(return_value=f)
        _seed_pending()
        kb_msg = MagicMock()
        kb_msg.chat.id = CHAT_ID
        kb_msg.delete = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(
                spec=TelegramMethod), message="message to delete not found"))
        bot = AsyncMock()
        cb = _make_cb("vd:360", message=kb_msg)
        await vd.cb_pick_quality(cb, bot=bot)
        kb_msg.delete.assert_awaited_once()
        # RIGHTS_ERROR реплай ушёл на триггер...
        rights_sent = [
            c for c in bot.send_message.call_args_list
            if c.kwargs.get("reply_to_message_id") == 100
        ]
        assert len(rights_sent) == 1
        # ...и скачивание ПРОДОЛЖИЛОСЬ: видео отправлено
        assert bot.send_video.await_count == 1
        assert vd._downloader.download.await_count == 1
        assert not f.exists()


# ── 8. Cleanup файла в finally при ошибке отправки ──────────────────

class TestCleanupFinally:
    @pytest.mark.asyncio
    async def test_file_deleted_even_if_send_fails(self, vd_env, tmp_path):
        f = tmp_path / "boom.mp4"
        f.write_bytes(b"z" * 16)
        vd._downloader.download = AsyncMock(return_value=f)
        _seed_pending()
        bot = AsyncMock()
        bot.send_chat_action = AsyncMock()
        bot.send_video = AsyncMock(side_effect=RuntimeError("network gone"))
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        assert not f.exists(), "файл обязан удаляться даже при ошибке отправки"
        # и юзер получил ERROR-фразу
        assert any(
            c.args[1] in VD_ERROR_PHRASES
            for c in bot.send_message.call_args_list)


# ── 9. Multi-link flow: выбор видео → выбор качества ────────────────

class TestMultiLinkFlow:
    @pytest.mark.asyncio
    async def test_multi_links_pick_video_then_quality_menu(self, vd_env,
                                                            monkeypatch):
        probes = {
            URL: _probe(title="Первое видео про котов"),
            URL2: _probe(title="Второе видео"),
        }

        async def fake_probe(url):
            return probes[url]

        monkeypatch.setattr(vd._downloader, "probe", fake_probe)
        msg = _make_msg(f"скачай {URL} и {URL2}")
        bot = AsyncMock()
        bot.edit_message_text = AsyncMock()
        await vd.video_download_handler(msg, bot=bot)
        markup = bot.edit_message_text.call_args.kwargs["reply_markup"]
        texts = [btn.text for row in markup.inline_keyboard for btn in row]
        assert texts == ["Первое видео про котов", "Второе видео"]
        datas = [btn.callback_data for row in markup.inline_keyboard
                 for btn in row]
        assert datas == ["vdv:0", "vdv:1"]

        # выбор первого видео → меню качества
        cb = _make_cb("vdv:0")
        await vd.cb_pick_video(cb, bot=AsyncMock())
        entry = vd._PENDING[(CHAT_ID, USER_ID)]
        assert entry["selected"] == 0

    @pytest.mark.asyncio
    async def test_stale_callback_answered_expired(self, vd_env):
        cb = _make_cb("vdv:5")
        await vd.cb_pick_video(cb, bot=AsyncMock())
        cb.answer.assert_awaited_with("эта менюха протухла")


# ── Epic 72 (74.A/D270): probe прокидывает единый yt-dlp конфиг ──────

class TestProbeOpts:
    """probe использует build_ytdlp_base_opts() (прокси/cookies) — фикс прод-бага
    «Sign in to confirm you're not a bot»; сеть не трогаем — мок YoutubeDL."""

    class _FakeYDL:
        last_opts = None

        def __init__(self, opts):
            type(self).last_opts = opts

        def extract_info(self, url, download=False):
            return {"title": "t",
                    "formats": [{"vcodec": "h264", "height": 720}]}

    def _patch_ytdlp(self, monkeypatch):
        import sys
        import types
        fake = types.SimpleNamespace(YoutubeDL=self._FakeYDL)
        monkeypatch.setitem(sys.modules, "yt_dlp", fake)

    @pytest.mark.asyncio
    async def test_probe_base_opts_passed(self, tmp_path, monkeypatch):
        """Epic 72: opts = build_ytdlp_base_opts() + quiet/noplaylist."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts",
                            lambda: {"proxy": "http://u:p@h:10808",
                                     "cookiefile": "/c.txt"})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        result = await dl.probe(URL)
        assert isinstance(result, ProbeResult)
        opts = self._FakeYDL.last_opts
        assert opts["proxy"] == "http://u:p@h:10808"
        assert opts["cookiefile"] == "/c.txt"
        assert opts["quiet"] is True
        assert opts["noplaylist"] is True

    @pytest.mark.asyncio
    async def test_probe_without_settings_no_proxy_keys(
            self, tmp_path, monkeypatch):
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        await dl.probe(URL)
        assert "proxy" not in self._FakeYDL.last_opts
        assert "cookiefile" not in self._FakeYDL.last_opts

    @pytest.mark.asyncio
    async def test_probe_proxy_set_logs_fact_only(
            self, tmp_path, monkeypatch, caplog):
        """74.A.2/R17: логируется только факт proxy=set, НЕ значение."""
        import logging
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        secret = "http://user:supersecret@host:10808"
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts",
                            lambda: {"proxy": secret})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with caplog.at_level(logging.INFO, logger="tools.video_downloader"):
            await dl.probe(URL)
        assert any("proxy=set" in r.message for r in caplog.records)
        assert all(secret not in r.getMessage() for r in caplog.records)
