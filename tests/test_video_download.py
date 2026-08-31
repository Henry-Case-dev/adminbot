"""Tests for Epic 66 — Cobalt Downloader (T-524/T-526/T-527, Section 70).

Триггер-парсинг, извлечение ссылок, уникальные разрешения, busy-лок,
кулдаун с remaining_time, мок Cobalt (aiohttp), удаление клавиатуры
(TelegramBadRequest → продолжение), cleanup файла в finally.
"""
import asyncio
import logging
import re
import time
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from handlers import video_download as vd
from tools.video_download_phrases import (
    VD_BUSY_PHRASES,
    VD_COOLDOWN_PHRASES,
    VD_ERROR_PHRASES,
    VD_NO_LINK_PHRASES,
    VD_RIGHTS_ERROR_PHRASES,
    VD_TOO_BIG_PHRASES,
)
from tools.video_downloader import (
    CobaltServiceDownError,
    DownloadError,
    DownloadTooBigError,
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


# ── 5b. Epic 73 (75.2–75.3/D279): touch только после успешного probe ──

class TestTouchAfterProbe:
    @pytest.mark.asyncio
    async def test_failed_probe_no_touch_and_retry_passes_gate(
            self, vd_env, monkeypatch):
        calls = []

        async def flaky(url):
            calls.append(url)
            if len(calls) == 1:
                raise DownloadError("yt-dlp boom")
            return _probe()

        monkeypatch.setattr(vd._downloader, "probe", flaky)
        msg1 = _make_msg(f"скачай {URL}", message_id=101)
        await vd.video_download_handler(msg1, bot=AsyncMock())
        assert msg1.reply.call_args[0][0] in VD_ERROR_PHRASES
        assert (CHAT_ID, USER_ID) not in vd._cooldown._last   # touch не звался

        # немедленный ретрай проходит кулдаун-гейт без ожидания
        msg2 = _make_msg(f"скачай {URL}", message_id=102)
        bot2 = AsyncMock()
        await vd.video_download_handler(msg2, bot=bot2)
        msg2.reply.assert_not_called()
        assert len(calls) == 2                       # дошли до probe повторно
        assert bot2.send_message.await_count == 1    # меню качества ушло

    @pytest.mark.asyncio
    async def test_success_probe_touches_exactly_once(self, vd_env,
                                                      monkeypatch):
        touched = []
        real_touch = vd.cooldown_touch

        async def spy(tracker, chat_id, user_id):
            touched.append((chat_id, user_id))
            await real_touch(tracker, chat_id, user_id)

        monkeypatch.setattr(vd, "cooldown_touch", spy)
        probe_mock = AsyncMock(return_value=_probe())
        monkeypatch.setattr(vd._downloader, "probe", probe_mock)

        msg1 = _make_msg(f"скачай {URL}", message_id=101)
        await vd.video_download_handler(msg1, bot=AsyncMock())
        assert touched == [(CHAT_ID, USER_ID)]       # ровно один touch
        assert (CHAT_ID, USER_ID) in vd._cooldown._last

        # мгновенный повторный триггер → кулдаун активен, probe не дёргается
        msg2 = _make_msg(f"скачай {URL}", message_id=102)
        await vd.video_download_handler(msg2, bot=AsyncMock())
        sent = msg2.reply.call_args[0][0]
        assert any(p.split("{")[0] in sent for p in VD_COOLDOWN_PHRASES)
        assert probe_mock.await_count == 1

    @pytest.mark.asyncio
    async def test_busy_callback_does_not_touch(self, vd_env):
        vd._PENDING[(CHAT_ID, USER_ID)] = {
            "urls": [URL], "probes": [_probe()], "selected": 0,
            "trigger_message_id": 100,
            "expires": time.monotonic() + 60,
        }
        await vd_env._lock.acquire()                 # чужое скачивание «идёт»
        try:
            cb = _make_cb("vd:720")
            await vd.cb_pick_quality(cb, bot=AsyncMock())
            assert cb.answer.call_args.kwargs.get("show_alert") is True
            assert (CHAT_ID, USER_ID) not in vd._cooldown._last
        finally:
            vd_env._lock.release()

    @pytest.mark.asyncio
    async def test_multi_link_partial_success_touches(self, vd_env,
                                                      monkeypatch):
        """Частично битые ссылки ≠ провал probe-фазы: меню построено → touch."""

        async def fake_probe(url):
            if url == URL2:
                raise DownloadError("bad link")
            return _probe(title="Живое видео")

        monkeypatch.setattr(vd._downloader, "probe", fake_probe)
        bot = AsyncMock()
        await vd.video_download_handler(
            _make_msg(f"скачай {URL} и {URL2}"), bot=bot)
        assert bot.edit_message_text.await_count == 1
        assert (CHAT_ID, USER_ID) in vd._cooldown._last      # touch прозван

    @pytest.mark.asyncio
    async def test_multi_link_all_failed_no_touch(self, vd_env, monkeypatch):
        async def fake_probe(url):
            raise DownloadError("all dead")

        monkeypatch.setattr(vd._downloader, "probe", fake_probe)
        bot = AsyncMock()
        await vd.video_download_handler(
            _make_msg(f"скачай {URL} и {URL2}"), bot=bot)
        assert (CHAT_ID, USER_ID) not in vd._cooldown._last  # БЕЗ touch

    @pytest.mark.asyncio
    async def test_remaining_time_counts_from_new_touch(self, vd_env,
                                                        monkeypatch):
        state = {"fail": True}

        async def flaky(url):
            if state["fail"]:
                raise DownloadError("boom")
            return _probe()

        monkeypatch.setattr(vd._downloader, "probe", flaky)
        # T-619: кулдаун перечитывается из конфига (hot.get) — значения
        # подменяем консистентно с трекером (30m).
        import types
        monkeypatch.setattr(
            vd, "settings",
            types.SimpleNamespace(DOWNLOAD_COOLDOWN=1800.0))
        t_first = time.monotonic()
        await vd.video_download_handler(
            _make_msg(f"скачай {URL}", message_id=101), bot=AsyncMock())
        await asyncio.sleep(0.25)                    # пауза между попытками
        state["fail"] = False
        await vd.video_download_handler(
            _make_msg(f"скачай {URL}", message_id=102), bot=AsyncMock())

        # touch проставлен в момент УСПЕШНОГО probe, не первого триггера
        touch_ts = vd._cooldown._last[(CHAT_ID, USER_ID)]
        assert touch_ts - t_first >= 0.24

        # фраза кулдауна отсчитывает remaining от нового touch (~полные 30м)
        msg3 = _make_msg(f"скачай {URL}", message_id=103)
        await vd.video_download_handler(msg3, bot=AsyncMock())
        sent = msg3.reply.call_args[0][0]
        minutes = int(re.search(r"(\d+) мин", sent).group(1))
        assert minutes in (29, 30)


# ── 6. Мок Cobalt (aiohttp): успех + ошибка ─────────────────────────

class FakeCobaltResponse:
    def __init__(self, payload=None, status=200, chunks=(b"vid", b"eo"),
                 text=None, content=None, headers=None):
        self._payload = payload
        self.status = status
        self._chunks = chunks
        self._text = text
        self._content_override = content
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        if self._text is not None:
            return self._text
        import json as _json
        return _json.dumps(self._payload) if self._payload is not None else ""

    class _Content:
        def __init__(self, chunks, text=None):
            self._chunks = chunks
            self._text = text

        async def iter_chunked(self, size):
            for chunk in self._chunks:
                yield chunk

        async def read(self, n=-1):
            # Epic 74: прод-код читает тело ошибки через content.read(лимит).
            if self._text is not None:
                data = self._text.encode("utf-8")
            else:
                data = b"".join(self._chunks)
            return data if n < 0 else data[:n]

    @property
    def content(self):
        if self._content_override is not None:
            return self._content_override
        return self._Content(self._chunks, self._text)


class FakeCobaltSession:
    behavior = {"post_payload": None, "post_response": None}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        FakeCobaltSession.behavior["post_called"] = True
        FakeCobaltSession.behavior["post_payload"] = json
        FakeCobaltSession.behavior["post_headers"] = headers
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
        FakeCobaltSession.behavior["post_headers"] = None
        FakeCobaltSession.behavior["post_response"] = FakeCobaltResponse(
            payload={"status": "tunnel",
                     "url": "http://tunnel/video.mp4",
                     "filename": "cool video.mp4"})
        path = await vd_env.download(URL, "720p")
        payload = FakeCobaltSession.behavior["post_payload"]
        assert payload == {"url": URL, "videoQuality": "720",
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

            async def download(self, url, quality, progress_cb=None):
                raise DownloadError("cobalt error")

        old = vd._downloader
        vd._downloader = _BrokenDownloader()
        try:
            bot = AsyncMock()
            cb = _make_cb("vd:720")
            await vd.cb_pick_quality(cb, bot=bot)
            # F1: fail применён через прогресс-сообщение (мок-бот стартует
            # бар с message_id=1) → ERROR-фраза в правке, НЕ в реплае
            err_edits = [c.args[2] for c in
                         bot.edit_message_text.call_args_list]
            assert any(t in VD_ERROR_PHRASES for t in err_edits)
            assert bot.edit_message_text.call_args.args[0] == CHAT_ID
        finally:
            vd._downloader = old


# ── 6b. Epic 74 (D280–D282): нормализация качества, Accept, тело 400 ─

@pytest.mark.asyncio
async def test_epic74_payload_quality_normalized(vd_env, monkeypatch):
    """D280: «1080p»/«1080»/1080 → videoQuality == «1080» в payload."""
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    FakeCobaltSession.behavior["post_response"] = None
    for q in ("1080p", "1080", 1080):
        FakeCobaltSession.behavior["post_called"] = False
        await vd_env.download(URL, q)
        payload = FakeCobaltSession.behavior["post_payload"]
        assert payload["videoQuality"] == "1080", q


@pytest.mark.asyncio
async def test_epic74_accept_header_sent(vd_env, monkeypatch):
    """D281: POST уходит с Accept: application/json."""
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    FakeCobaltSession.behavior["post_response"] = None
    await vd_env.download(URL, "720p")
    assert FakeCobaltSession.behavior["post_headers"] == {
        "Accept": "application/json"}


@pytest.mark.asyncio
async def test_epic74_http400_json_body_error_code_in_message(
        vd_env, monkeypatch, caplog):
    """D282: 400 + JSON-тело → error.code в тексте DownloadError."""
    import logging
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    FakeCobaltSession.behavior["post_response"] = FakeCobaltResponse(
        status=400,
        text='{"error":{"code":"error.api.quality.unavailable"}}')
    with caplog.at_level(logging.ERROR,
                         logger="tools.video_downloader"):
        with pytest.raises(DownloadError) as exc_info:
            await vd_env.download(URL, "1080")
    msg = str(exc_info.value)
    assert "cobalt http 400" in msg
    assert "error.api.quality.unavailable" in msg
    assert any("error.api.quality.unavailable" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_epic74_http400_non_json_body_raw_truncated_to_500(
        vd_env, monkeypatch):
    """D282: 400 + не-JSON тело → сырой текст в ошибке, обрезан до 500."""
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    raw = "x" * 900
    FakeCobaltSession.behavior["post_response"] = FakeCobaltResponse(
        status=400, text=raw)
    with pytest.raises(DownloadError) as exc_info:
        await vd_env.download(URL, "1080")
    msg = str(exc_info.value)
    assert "cobalt http 400" in msg
    assert "x" * 500 in msg                 # первые 500 символов включены
    assert "x" * 501 not in msg             # длиннее 500 — НЕ просочилось


@pytest.mark.asyncio
async def test_epic74_garbage_quality_fails_without_network(
        vd_env, monkeypatch):
    """D280: мусорное качество → DownloadError БЕЗ похода в сеть."""
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    FakeCobaltSession.behavior["post_called"] = False
    with pytest.raises(DownloadError, match="invalid quality"):
        await vd_env.download(URL, "abc")
    assert FakeCobaltSession.behavior["post_called"] is False


@pytest.mark.asyncio
async def test_epic74_max_quality_passes_through(vd_env, monkeypatch):
    """D280: «max» проходит как есть (без нормализации к числу)."""
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    FakeCobaltSession.behavior["post_response"] = None
    await vd_env.download(URL, "max")
    payload = FakeCobaltSession.behavior["post_payload"]
    assert payload["videoQuality"] == "max"


@pytest.mark.asyncio
async def test_epic74_http400_body_read_is_bounded(
        vd_env, monkeypatch, caplog):
    """D282 (ревью): тело ошибки читается через content.read с лимитом —
    гигантское тело НЕ читается целиком (resp.text() без потолка = OOM-риск),
    в сообщении только первые 500 символов."""
    import logging
    import tools.video_downloader as vdm
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    raw = "y" * (vdm._ERROR_BODY_MAX_BYTES * 100)   # 100 KB при лимите 1 KB
    FakeCobaltSession.behavior["post_response"] = FakeCobaltResponse(
        status=413, text=raw)
    with caplog.at_level(logging.ERROR,
                         logger="tools.video_downloader"):
        with pytest.raises(DownloadError) as exc_info:
            await vd_env.download(URL, "1080")
    msg = str(exc_info.value)
    assert "cobalt http 413" in msg
    assert len([c for c in msg if c == "y"]) <= 500   # не 100K «y»
    assert any("cobalt http 413" in r.getMessage()
               for r in caplog.records)


class _BrokenContent:
    async def read(self, n=-1):
        raise ConnectionResetError("reset while reading error body")


@pytest.mark.asyncio
async def test_epic74_http_error_body_unreadable_bare_status_fallback(
        vd_env, monkeypatch):
    """D282 (ревью): обрыв соединения при чтении тела ошибки → DownloadError
    со статусом БЕЗ тела, исключение не маскируется transport-ошибкой."""
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", FakeCobaltSession)
    resp = FakeCobaltResponse(status=502, content=_BrokenContent())
    FakeCobaltSession.behavior["post_response"] = resp
    with pytest.raises(DownloadError, match=r"^cobalt http 502$"):
        await vd_env.download(URL, "1080")


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
        # RIGHTS_ERROR реплай ушёл на триггер (прогресс-бар — тоже reply,
        # поэтому фильтр по фразе, а не по reply_to_message_id)
        rights_sent = [
            c for c in bot.send_message.call_args_list
            if c.kwargs.get("reply_to_message_id") == 100
            and c.args[1] in VD_RIGHTS_ERROR_PHRASES
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

        class _Bot:
            """send_message отдаёт реальный message_id → прогресс-бар
            применён; send_video падает → ошибка показана ЧЕРЕЗ бар."""
            def __init__(self):
                self.send_chat_action = AsyncMock()
                self.send_video = AsyncMock(side_effect=RuntimeError(
                    "network gone"))
                self.send_message = AsyncMock(return_value=MagicMock(
                    message_id=42))
                self.edit_message_text = AsyncMock()
                self.delete_message = AsyncMock()

        bot = _Bot()
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        assert not f.exists(), "файл обязан удаляться даже при ошибке отправки"
        # F1: fail применён (репортер жив) → отдельный _safe_error_reply НЕ шлётся
        err_edits = [c.args[2] for c in bot.edit_message_text.call_args_list]
        assert any(t in VD_ERROR_PHRASES for t in err_edits)
        sent = [c.args[1] for c in bot.send_message.call_args_list]
        assert sent == ["⏳ Скачивание…"]
        assert bot.delete_message.await_count == 0   # сообщение с ошибкой живёт

    @pytest.mark.asyncio
    async def test_start_broken_falls_back_to_error_reply(self, vd_env):
        """F1: старт прогресс-бара сломан (send_message падает) →
        reporter.fail() == False → _safe_error_reply доставляет ошибку."""
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import TelegramMethod
        from services import progress_reporter as pr
        pr._active.clear()
        vd._downloader.download = AsyncMock(
            side_effect=DownloadError("boom"))

        class _Bot:
            def __init__(self):
                self.send_chat_action = AsyncMock()
                self.send_video = AsyncMock()
                self.send_message = AsyncMock(side_effect=TelegramBadRequest(
                    method=MagicMock(spec=TelegramMethod),
                    message="not enough rights"))
                self.edit_message_text = AsyncMock()
                self.delete_message = AsyncMock()

        _seed_pending()
        bot = _Bot()
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        assert pr.get_active(CHAT_ID) is None
        # ошибка доставлена обычным реплаем (прогресс-сообщения нет)
        sent = [c.args[1] for c in bot.send_message.call_args_list]
        assert any(t in VD_ERROR_PHRASES for t in sent)


# ── 84.23 (D303): прогресс-бар в хендлере ───────────────────────────

class TestProgressBarHandler:
    """cb_pick_quality/direct: репортер создан → fail/close → реестр чист."""

    class _MockBot:
        def __init__(self):
            self.send_chat_action = AsyncMock()
            self.send_video = AsyncMock()
            self.send_message = AsyncMock(return_value=MagicMock(
                message_id=42))
            self.edit_message_text = AsyncMock()
            self.delete_message = AsyncMock()

    @pytest.mark.asyncio
    async def test_quality_callback_reporter_success_lifecycle(
            self, vd_env, tmp_path):
        """Успех: «⏳ Скачивание…» отправлено, файл отправлен, прогресс-
        сообщение УДАЛЕНО, реестр очищен."""
        from services import progress_reporter as pr
        pr._active.clear()
        f = tmp_path / "ok.mp4"
        f.write_bytes(b"x")
        vd._downloader.download = AsyncMock(return_value=f)
        _seed_pending()
        bot = self._MockBot()
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        assert pr.get_active(CHAT_ID) is None
        assert bot.send_message.call_args.args[1] == "⏳ Скачивание…"
        assert bot.send_video.await_count == 1
        assert bot.delete_message.await_count == 1
        assert bot.delete_message.call_args.args[0] == CHAT_ID
        assert not f.exists()            # cleanup в finally

    @pytest.mark.asyncio
    async def test_quality_callback_error_calls_fail(self, vd_env, tmp_path):
        """Ошибка: репортер.fail с текстом ошибки (правка), сообщение с
        ошибкой НЕ удаляется, реестр очищен."""
        from services import progress_reporter as pr
        pr._active.clear()
        vd._downloader.download = AsyncMock(
            side_effect=DownloadError("boom"))
        _seed_pending()
        bot = self._MockBot()
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        assert pr.get_active(CHAT_ID) is None
        edit_texts = [c.args[2] for c in bot.edit_message_text.call_args_list]
        assert any(t in VD_ERROR_PHRASES for t in edit_texts)
        assert bot.delete_message.await_count == 0

    @pytest.mark.asyncio
    async def test_quality_callback_too_big_fails_reporter(self, vd_env):
        """TooBig: fail с TOO_BIG-фразой, реестр очищен."""
        from services import progress_reporter as pr
        pr._active.clear()
        vd._downloader.download = AsyncMock(
            side_effect=DownloadTooBigError("too big"))
        _seed_pending()
        bot = self._MockBot()
        cb = _make_cb("vd:720")
        await vd.cb_pick_quality(cb, bot=bot)
        assert pr.get_active(CHAT_ID) is None
        edit_texts = [c.args[2] for c in bot.edit_message_text.call_args_list]
        assert any(t in VD_TOO_BIG_PHRASES for t in edit_texts)


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

# ── Epic 75 (Section 77 / D283–D284): retry-once + диагностика empty body ──

TUNNEL_URL = ("https://gv.example/videoplayback"
              "?id=abcdef1234567890&sig=TOPSECRETSIGNATURE")

EMPTY_HEADERS = {"Content-Length": "1048576",
                 "Estimated-Content-Length": "1048576",
                 "Content-Type": "video/mp4"}


class _StreamResponse:
    def __init__(self, status=200, chunks=(), headers=None):
        self.status = status
        self._chunks = chunks
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    class _Content:
        def __init__(self, chunks):
            self._chunks = chunks

        async def iter_chunked(self, size):
            for chunk in self._chunks:
                yield chunk

    @property
    def content(self):
        return self._Content(self._chunks)


class _StreamSession:
    """Fake aiohttp.ClientSession для GET tunnel: очередь ответов/ошибок."""
    queue = []
    urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url):
        type(self).urls.append(url)
        item = type(self).queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def stream_env(vd_env, monkeypatch):
    """Downloader с существующим download_dir + патч ClientSession/sleep."""
    vd_env._download_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "tools.video_downloader.aiohttp.ClientSession", _StreamSession)
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr("tools.video_downloader.asyncio.sleep", fake_sleep)
    _StreamSession.queue = []
    _StreamSession.urls = []
    vd_env.sleeps = sleeps
    return vd_env


class TestEmptyBodyRetry:
    @pytest.mark.asyncio
    async def test_retry_once_recovers(self, stream_env):
        """77.2 #1: попытка 1 empty → попытка 2 успешна: файл скачан,
        ровно 2 GET того же URL, ровно 1 сон 4с."""
        _StreamSession.queue = [
            _StreamResponse(chunks=(), headers=EMPTY_HEADERS),
            _StreamResponse(chunks=(b"fake", b"video")),
        ]
        path = await stream_env._stream_to_file(TUNNEL_URL, "retry vid.mp4")
        assert path.exists()
        assert path.name == "retry vid.mp4"
        assert path.read_bytes() == b"fakevideo"
        assert len(_StreamSession.urls) == 2
        assert all(u == TUNNEL_URL for u in _StreamSession.urls)
        assert stream_env.sleeps == [4.0]

    @pytest.mark.asyncio
    async def test_both_attempts_empty_error_after_retry_tmp_removed(
            self, stream_env):
        """77.2 #2: обе попытки empty → DownloadError "(after retry)",
        ровно 1 ретрай (2 GET), tmp-файл удалён."""
        _StreamSession.queue = [
            _StreamResponse(chunks=(), headers=EMPTY_HEADERS),
            _StreamResponse(chunks=(), headers=EMPTY_HEADERS),
        ]
        with pytest.raises(DownloadError,
                           match=r"empty body from tunnel \(after retry\)"):
            await stream_env._stream_to_file(TUNNEL_URL, None)
        assert len(_StreamSession.urls) == 2
        assert stream_env.sleeps == [4.0]
        assert list(stream_env._download_dir.glob("vd_*.mp4")) == []

    @pytest.mark.asyncio
    async def test_http_4xx_no_retry(self, stream_env):
        """77.2 #3: статус >=400 на первой попытке → мгновенный
        DownloadError("tunnel http …") БЕЗ ретрая и без сна."""
        _StreamSession.queue = [_StreamResponse(status=403)]
        with pytest.raises(DownloadError, match=r"^tunnel http 403$"):
            await stream_env._stream_to_file(TUNNEL_URL, None)
        assert len(_StreamSession.urls) == 1
        assert stream_env.sleeps == []

    @pytest.mark.asyncio
    async def test_diagnostics_logged_no_full_url_no_secret(
            self, stream_env, caplog):
        """77.2 #4 (D284): WARNING содержит attempt/http_status/CL/ECL/
        content-type/bytes_written=0/gv_id (8 симв.); полный URL и подпись
        в логах ОТСУТСТВУЮТ; полный gv id тоже не логируется."""
        _StreamSession.queue = [
            _StreamResponse(chunks=(), headers=EMPTY_HEADERS),
            _StreamResponse(chunks=(), headers=EMPTY_HEADERS),
        ]
        with caplog.at_level(logging.WARNING,
                             logger="tools.video_downloader"):
            with pytest.raises(DownloadError):
                await stream_env._stream_to_file(TUNNEL_URL, None)
        texts = [r.getMessage() for r in caplog.records
                 if "tunnel empty body" in r.getMessage()]
        assert len(texts) == 2                      # перед ретраем и после фейла
        assert any("attempt=1" in t for t in texts)
        assert any("attempt=2" in t for t in texts)
        joined = "\n".join(texts)
        for fragment in ("http_status=200",
                         "content_length=1048576",
                         "estimated_content_length=1048576",
                         "content_type=video/mp4",
                         "bytes_written=0",
                         "gv_id=abcdef12"):
            assert fragment in joined, fragment
        assert TUNNEL_URL not in joined             # полный URL не в логах
        assert "TOPSECRETSIGNATURE" not in joined   # подпись не утекла
        assert "abcdef1234567890" not in joined     # только первые 8 символов

    @pytest.mark.asyncio
    async def test_connector_error_unchanged_no_retry(self, stream_env):
        """77.2 #5: сетевые ошибки без изменений — прежний класс/текст,
        без ретрая (1 GET), без сна."""
        key = MagicMock()
        os_error = OSError("no route to host")
        _StreamSession.queue = [aiohttp.ClientConnectorError(key, os_error)]
        with pytest.raises(CobaltServiceDownError,
                           match="tunnel unreachable"):
            await stream_env._stream_to_file(TUNNEL_URL, None)
        assert len(_StreamSession.urls) == 1
        assert stream_env.sleeps == []

    @pytest.mark.asyncio
    async def test_timeout_error_unchanged_no_retry(self, stream_env):
        _StreamSession.queue = [asyncio.TimeoutError()]
        with pytest.raises(DownloadError, match=r"^stream timeout$"):
            await stream_env._stream_to_file(TUNNEL_URL, None)
        assert len(_StreamSession.urls) == 1
        assert stream_env.sleeps == []

    @pytest.mark.asyncio
    async def test_generic_client_error_unchanged_no_retry(self, stream_env):
        _StreamSession.queue = [aiohttp.ClientPayloadError("chunk gone")]
        with pytest.raises(DownloadError, match="stream transport error"):
            await stream_env._stream_to_file(TUNNEL_URL, None)
        assert len(_StreamSession.urls) == 1
        assert stream_env.sleeps == []

    @pytest.mark.asyncio
    async def test_success_first_attempt_no_retry_no_warning(
            self, stream_env, caplog):
        """Нормальный стрим с первого раза — без ретрая и без WARNING."""
        _StreamSession.queue = [_StreamResponse(chunks=(b"data",))]
        with caplog.at_level(logging.WARNING,
                             logger="tools.video_downloader"):
            path = await stream_env._stream_to_file(TUNNEL_URL, "ok vid.mp4")
        assert path.read_bytes() == b"data"
        assert len(_StreamSession.urls) == 1
        assert stream_env.sleeps == []
        assert not [r for r in caplog.records
                    if "tunnel empty body" in r.getMessage()]


# ── Прод-хотфикс 30.08.2026: yt-dlp merge «Invalid data found…» ─────────────

class TestYtdlpDownloadHotfix:
    """Ретрай с резервным player_client, URL/фаза в ошибке, диск-чек,
    ffmpeg-чек при старте."""

    class _FakeYDL:
        last_opts = None
        calls = []
        result = None
        exc = None
        fail_first = False

        def __init__(self, opts):
            type(self).last_opts = opts
            type(self).calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            if type(self).fail_first and len(type(self).calls) == 1:
                raise type(self).exc
            if type(self).exc is not None and not type(self).fail_first:
                raise type(self).exc
            if type(self).result is not None:
                return type(self).result
            return {"title": "t", "requested_downloads": [
                {"filepath": "/tmp/x.mp4"}]}

    def _patch_ytdlp(self, monkeypatch):
        import sys
        import types
        fake = types.SimpleNamespace(YoutubeDL=self._FakeYDL)
        monkeypatch.setitem(sys.modules, "yt_dlp", fake)

    @pytest.mark.asyncio
    async def test_retry_with_android_player_client(
            self, tmp_path, monkeypatch, caplog):
        """Первый вызов падает (не-postprocess, напр. 403) → перебор
        клиентов: второй с player_client=android → успех."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = RuntimeError("HTTP Error 403: Forbidden")
        self._FakeYDL.fail_first = True
        self._FakeYDL.result = None
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with caplog.at_level(logging.WARNING):
            path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ",
                                           "720p")
        assert path.name == "x.mp4"     # успешный повтор (фейк-файлpath)
        assert len(self._FakeYDL.calls) == 2
        retry_opts = self._FakeYDL.calls[1]
        assert retry_opts["extractor_args"] == {
            "youtube": {"player_client": ["android"]}}
        assert any("retry with player_client" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_retry_keeps_pot_from_base_opts(
            self, tmp_path, monkeypatch):
        """B2: retry-опции МЕРЖАТ extractor_args с базовыми — pot_provider/
        pot_token_background из build_ytdlp_base_opts сохраняются, добавляется
        player_client ретрая (без полной замены)."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = RuntimeError("HTTP Error 403: Forbidden")
        self._FakeYDL.fail_first = True
        self._FakeYDL.result = None

        def _base_with_pot():
            return {"extractor_args": {
                "youtube": {"pot_provider": ["bgutil:http"],
                            "pot_token_background": ["false"]}}}
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", _base_with_pot)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert len(self._FakeYDL.calls) == 2
        retry_opts = self._FakeYDL.calls[1]
        assert retry_opts["extractor_args"]["youtube"] == {
            "pot_provider": ["bgutil:http"],
            "pot_token_background": ["false"],
            "player_client": ["android"]}

    @pytest.mark.asyncio
    async def test_attempt_budget_includes_merge_fallback(
            self, tmp_path, monkeypatch):
        """B3: первый fail (постпроцессинг) + merge-фолбек + ретрай-клиенты —
        суммарно НЕ более _MAX_YTDLP_ATTEMPTS реальных загрузок (3)."""
        from tools import video_downloader as vdm

        class _FakeAlwaysFail:
            calls = []

            def __init__(self, opts):
                type(self).calls.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=False):
                raise RuntimeError(
                    "ERROR: Postprocessing: Error opening input files: "
                    "Invalid data found when processing input")

        fake = _FakeAlwaysFail
        fake.calls = []
        import sys
        import types
        monkeypatch.setitem(
            sys.modules, "yt_dlp",
            types.SimpleNamespace(YoutubeDL=fake))
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadError):
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        # 1-я попытка + merge-фолбек + 1 ретрай-клиент = 3, не 4
        assert len(fake.calls) == 3
        assert "merge_output_format" not in fake.calls[1]
        assert fake.calls[1]["format"] == "b[ext=mp4]/b/best"
        assert fake.calls[2]["extractor_args"]["youtube"] == {
            "player_client": ["android"]}

    @pytest.mark.asyncio
    async def test_merge_fallback_on_postprocess_error(
            self, tmp_path, monkeypatch, caplog):
        """Постпроцессинг-ошибка → merge-фолбек: повтор БЕЗ merge, формат
        'b[ext=mp4]/b/best', один файл → успех."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = RuntimeError(
            "ERROR: Postprocessing: Error opening input files: "
            "Invalid data found when processing input")
        self._FakeYDL.fail_first = True    # первая попытка падает
        self._FakeYDL.result = None
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with caplog.at_level(logging.WARNING):
            path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ",
                                           "720p")
        assert path.name == "x.mp4"
        assert len(self._FakeYDL.calls) == 2
        fallback_opts = self._FakeYDL.calls[1]
        assert "merge_output_format" not in fallback_opts   # merge-фолбек
        assert fallback_opts["format"] == "b[ext=mp4]/b/best"
        assert any("merge-фолбек" in r.getMessage() or
                   "merge-fallback" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_age_restrict_raises_unavailable(
            self, tmp_path, monkeypatch):
        """Детект недоступности: age_limit > 0 → DownloadUnavailableError."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = None
        self._FakeYDL.fail_first = False
        self._FakeYDL.result = {"title": "t", "age_limit": 18,
                                "requested_downloads": [
                                    {"filepath": "/tmp/x.mp4"}]}
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadUnavailableError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert "возрастное ограничение" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_progress_cb_called_from_hook(self, tmp_path, monkeypatch):
        """84.23 (D303): fake-yt-dlp дергает progress_hooks → progress_cb
        получил raw dict (status/downloaded/total/eta/title)."""
        from tools import video_downloader as vdm
        captured = []

        class _FakeYDL_Hook:
            last_hook = None

            def __init__(self, opts):
                type(self).last_hook = opts["progress_hooks"][0]

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=True):
                type(self).last_hook({
                    "status": "downloading",
                    "downloaded_bytes": 1024,
                    "total_bytes": 2048,
                    "speed": 512,
                    "eta": 3,
                    "info_dict": {"title": "t"}})
                type(self).last_hook({"status": "finished"})
                return {"title": "t", "requested_downloads": [
                    {"filepath": "/tmp/x.mp4"}]}

        import sys
        import types
        monkeypatch.setitem(
            sys.modules, "yt_dlp",
            types.SimpleNamespace(YoutubeDL=_FakeYDL_Hook))
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p",
                                progress_cb=captured.append)
        assert [c["status"] for c in captured] == ["downloading", "finished"]
        assert captured[0]["downloaded_bytes"] == 1024
        assert captured[0]["total_bytes"] == 2048
        assert captured[0]["eta"] == 3
        assert captured[0]["info_dict"]["title"] == "t"

    @pytest.mark.asyncio
    async def test_direct_progress_cb_synthetic(self, tmp_path, monkeypatch):
        """84.23: download_direct вызывает progress_cb с синтетическим
        dict (bytes из стрима + total из Content-Length)."""
        from tools import video_downloader as vdm
        captured = []

        class _Resp:
            status_code = 200
            headers = {"content-length": "6"}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def aiter_bytes(self, n):
                async def _gen():
                    yield b"aaa"
                    yield b"bbb"
                return _gen()

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None):
                return _Resp()

        monkeypatch.setattr(vdm.httpx, "AsyncClient", _Client)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        await dl.download_direct("https://2ch.su/a.mp4",
                                 progress_cb=captured.append)
        assert [c["status"] for c in captured] == \
            ["downloading", "downloading"]
        assert captured[-1]["downloaded_bytes"] == 6
        assert captured[-1]["total_bytes"] == 6

    @pytest.mark.asyncio
    async def test_innocent_sign_in_phrase_in_description_ok(
            self, tmp_path, monkeypatch):
        """M1: «how to sign in to our site» в описании — НЕ недоступность
        (ложно-положительный детект устранён): скачивание проходит."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = None
        self._FakeYDL.fail_first = False
        self._FakeYDL.result = {
            "title": "t",
            "description": "learn how to sign in to our site",
            "requested_downloads": [{"filepath": "/tmp/x.mp4"}]}
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ",
                                       "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_full_sign_in_phrase_raises_unavailable(
            self, tmp_path, monkeypatch):
        """M1: ПОЛНАЯ фраза бот-проверки в описании/availability →
        DownloadUnavailableError (детект по полной фразе работает)."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = None
        self._FakeYDL.fail_first = False
        self._FakeYDL.result = {
            "title": "t",
            "description": "please sign in to confirm you're not a bot",
            "requested_downloads": [{"filepath": "/tmp/x.mp4"}]}
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadUnavailableError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert "вход в аккаунт" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_merge_fallback_success_cleans_intermediates(
            self, tmp_path, monkeypatch):
        """M2: успешный merge-фолбек (wX4OiGISNlY-сценарий) — промежуточные
        vd_*.f137.mp4 / vd_*.f140.m4a удалены, итоговый файл цел."""
        from tools import video_downloader as vdm
        from pathlib import Path
        written = []

        class _FakeYDL_M2:
            calls = []

            def __init__(self, opts):
                type(self).calls.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=False):
                opts = type(self).calls[-1]
                if len(type(self).calls) == 1:
                    # 1-я попытка (с merge): промежуточные уже записаны,
                    # потом падение на постпроцессинге (merge ffmpeg).
                    prefix = Path(opts["outtmpl"]).stem
                    base = Path(opts["outtmpl"].replace("%(ext)s", "mp4"))
                    for suffix in (".f137.mp4", ".f140.m4a"):
                        p = base.parent / f"{prefix}{suffix}"
                        p.write_bytes(b"x")
                        written.append(p)
                    raise RuntimeError(
                        "ERROR: Postprocessing: Error opening input files: "
                        "Invalid data found when processing input")
                # merge-фолбек: итоговый файл (без merge) записан.
                final = Path(opts["outtmpl"].replace("%(ext)s", "mp4"))
                final.write_bytes(b"final")
                return {"title": "t", "requested_downloads": [
                    {"filepath": str(final)}]}

        _FakeYDL_M2.calls = []
        import sys
        import types
        monkeypatch.setitem(
            sys.modules, "yt_dlp",
            types.SimpleNamespace(YoutubeDL=_FakeYDL_M2))
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ",
                                       "720p")
        assert path.read_bytes() == b"final"
        for p in written:
            assert not p.exists(), f"промежуточный файл остался: {p}"
        assert path.exists()

    def test_pot_options_from_env(self, monkeypatch):
        """POT-провайдер из env: YTDLP_POT_PROVIDER=bgutil:http →
        build_ytdlp_base_opts несёт extractor_args youtube pot_provider."""
        import config.settings as settings_mod
        monkeypatch.setenv("YTDLP_POT_PROVIDER", "bgutil:http")
        opts = settings_mod.build_ytdlp_base_opts()
        assert opts["extractor_args"] == {
            "youtube": {"pot_provider": ["bgutil:http"],
                        "pot_token_background": ["false"]}}

    def test_pot_absent_by_default(self, monkeypatch):
        """Без настройки — POT-ключей НЕТ."""
        import config.settings as settings_mod
        monkeypatch.delenv("YTDLP_POT_PROVIDER", raising=False)
        opts = settings_mod.build_ytdlp_base_opts()
        assert "extractor_args" not in opts

    @pytest.mark.asyncio
    async def test_failure_includes_url_and_phase(
            self, tmp_path, monkeypatch, caplog):
        """Ошибка yt-dlp оборачивается с url и фазой (диагностика)."""
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = RuntimeError("boom postprocess")
        self._FakeYDL.fail_first = False     # оба вызова (и ретрай) падают
        self._FakeYDL.result = None
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        msg = str(excinfo.value)
        assert "https://youtu.be/dQw4w9WgXcQ" in msg
        assert "phase=" in msg

    @pytest.mark.asyncio
    async def test_low_disk_warns(self, tmp_path, monkeypatch, caplog):
        """Диск-чек: free < 500 МБ → WARNING с URL (не блокирует)."""
        import shutil
        from tools import video_downloader as vdm
        self._patch_ytdlp(monkeypatch)
        self._FakeYDL.calls = []
        self._FakeYDL.exc = None
        self._FakeYDL.fail_first = False
        self._FakeYDL.result = None
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})

        class _Usage:
            free = 100 * 1024 * 1024

        monkeypatch.setattr(vdm.shutil, "disk_usage", lambda p: _Usage())
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with caplog.at_level(logging.WARNING):
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert any("low disk" in r.getMessage() and "youtu.be" in r.getMessage()
                   for r in caplog.records)

    def test_ffmpeg_missing_warns_on_setup(self, monkeypatch, caplog):
        """ffmpeg отсутствует в PATH → WARNING при setup_video_download."""
        import shutil
        from handlers import video_download as vd_mod
        monkeypatch.setattr(shutil, "which", lambda name: None)
        with caplog.at_level(logging.WARNING):
            vd_mod.setup_video_download(None)
        assert any("ffmpeg НЕ найден" in r.getMessage()
                   for r in caplog.records)


# ── Прод-фикс 30.08.2026 (диагностика DevOps): протокол-фильтр, sign-in,
#    direct-медиа, нативное TG-видео ─────────────────────────────────────────

class TestSelectorProtocolFilter:
    """1b: селекторы предпочитают прямые CDN-ссылки битым HLS (wX4OiGISNlY)."""

    def test_selector_has_protocol_https(self):
        from tools.video_downloader import VideoDownloader
        dl = VideoDownloader("http://localhost:9000/", "d")
        # первый приоритет обоих селекторов содержит [protocol^=https]
        for quality, expect in (("max", "bv[ext=mp4][protocol^=https]+ba"),
                                ("720",
                                 "bv[ext=mp4][height<=720][protocol^=https]+ba")):
            sel = dl._format_selector(quality)
            assert sel.startswith(expect), sel


class TestSignInError:
    """1c: бот-проверка → понятная ошибка DownloadUnavailableError."""

    class _SignInYDL:
        calls = []

        def __init__(self, opts):
            type(self).calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError(
                "ERROR: unable to download video data: HTTP Error 403: "
                "Sign in to confirm you're not a bot")

    @pytest.mark.asyncio
    async def test_sign_in_raises_unavailable(self, tmp_path, monkeypatch):
        import sys
        import types
        from tools import video_downloader as vdm
        fake = types.SimpleNamespace(YoutubeDL=self._SignInYDL)
        monkeypatch.setitem(sys.modules, "yt_dlp", fake)
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadUnavailableError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert "бот-проверка" in str(excinfo.value)


class TestDrmDetect:
    """Прод-баг 01.09.2026: ложный «защищено DRM» — аудио-форматы YouTube
    с DRC (Dynamic Range Compression: format_note 'low, DRC', format_id
    '139-drc') НЕ являются DRM. Рецепт (ресерч): DRM только по форматам —
    has_drm is True / licenseInfos / 'drm'|'Premium' в format_note; title/
    description/availability НЕ сканируются; unavailable только когда
    DRM-форматы есть, а свободных нет."""

    def _run(self, tmp_path, monkeypatch, info: dict):
        """Запуск download_ytdlp с fake-yt-dlp, возвращающим info."""
        import sys
        import types
        from tools import video_downloader as vdm

        class _FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=True):
                return info

        monkeypatch.setitem(
            sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_FakeYDL))
        monkeypatch.setattr(vdm, "build_ytdlp_base_opts", lambda: {})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        return dl

    def _info(self, formats, **kw):
        base = {"title": "t", "requested_downloads": [
            {"filepath": "/tmp/x.mp4"}]}
        base["formats"] = formats
        base.update(kw)
        return base

    @pytest.mark.asyncio
    async def test_shorts_drc_audio_not_drm(self, tmp_path, monkeypatch):
        """Воспроизведение бага: Shorts-подобный info с 'low, DRC'/
        'medium, DRC' аудио (format_id *-drc) + свободные форматы →
        НЕ unavailable, скачивается."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "137", "ext": "mp4", "format_note": "DASH video"},
            {"format_id": "139-drc", "ext": "m4a", "format_note": "low, DRC"},
            {"format_id": "140-drc", "ext": "m4a", "format_note": "medium, DRC"},
            {"format_id": "249-drc", "ext": "webm", "format_note": "low, DRC"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_drc_only_audio_still_free_video_ok(self, tmp_path,
                                                      monkeypatch):
        """Даже если ВСЕ аудио-форматы DRC — есть свободное видео →
        скачивание идёт (правило «свободных нет»)."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "137", "ext": "mp4", "format_note": "DASH video"},
            {"format_id": "139-drc", "ext": "m4a", "format_note": "low, DRC"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_all_audio_drc_only_not_unavailable(self, tmp_path,
                                                      monkeypatch):
        """Ревью-фикс 3: audio-only видео, ВСЕ форматы *-drc (format_id и
        format_note 'DRC') → drm=0, свободные = все → НЕ unavailable
        ('drc' полностью убран из DRM-маркеров)."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "139-drc", "ext": "m4a", "format_note": "low, DRC"},
            {"format_id": "140-drc", "ext": "m4a", "format_note": "medium, DRC"},
            {"format_id": "249-drc", "ext": "webm", "format_note": "low, DRC"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_has_drm_true_raises_unavailable(self, tmp_path,
                                                   monkeypatch):
        """Канон: формат с has_drm=True и без свободных → DRM."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "drc", "has_drm": True, "ext": "mp4"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        with pytest.raises(vdm.DownloadUnavailableError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert "защищено DRM" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_license_infos_no_free_formats_raises(self, tmp_path,
                                                        monkeypatch):
        """licenseInfos на видео-уровне + НЕТ форматов вовсе → DRM
        (как youtube.py: 'This video is DRM protected')."""
        from tools import video_downloader as vdm
        info = self._info([], licenseInfos=[{"name": "widevine"}])
        dl = self._run(tmp_path, monkeypatch, info)
        with pytest.raises(vdm.DownloadUnavailableError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert "защищено DRM" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_format_license_infos_and_free_formats_ok(self, tmp_path,
                                                            monkeypatch):
        """Формат с licenseInfos + свободные форматы → НЕ unavailable."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "137", "ext": "mp4",
             "licenseInfos": [{"name": "widevine"}]},
            {"format_id": "136", "ext": "mp4"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_description_with_drm_word_not_blocking(self, tmp_path,
                                                          monkeypatch):
        """Слово 'DRM' в описании/availability → НЕ unavailable
        (title/description/availability не сканируются)."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "137", "ext": "mp4", "format_note": "DASH video"},
        ], description="watch this DRM free video!", availability="public")
        dl = self._run(tmp_path, monkeypatch, info)
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_has_drm_maybe_not_blocking(self, tmp_path, monkeypatch):
        """has_drm='maybe' (потенциальный DRM, yt-dlp проверит сам через
        check-formats) → НЕ unavailable."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "616", "ext": "mp4", "has_drm": "maybe",
             "format_note": "DASH video"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        path = await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert path.name == "x.mp4"

    @pytest.mark.asyncio
    async def test_premium_note_all_formats_raises(self, tmp_path,
                                                   monkeypatch):
        """Все форматы с 'Premium'/'DRM' в format_note, свободных нет →
        unavailable."""
        from tools import video_downloader as vdm
        info = self._info([
            {"format_id": "616", "ext": "mp4", "format_note": "Premium"},
            {"format_id": "617", "ext": "mp4", "format_note": "DRM, HDR"},
        ])
        dl = self._run(tmp_path, monkeypatch, info)
        with pytest.raises(vdm.DownloadUnavailableError) as excinfo:
            await dl.download_ytdlp("https://youtu.be/dQw4w9WgXcQ", "720p")
        assert "защищено DRM" in str(excinfo.value)


class TestDirectMedia:
    """2: прямые медиа-ссылки — детект и стрим-даунлоад."""

    def test_direct_media_detection(self):
        from tools.video_downloader import is_direct_media_url
        assert is_direct_media_url("https://x/a.mp4")
        assert is_direct_media_url("https://x/a.mp4?token=123")
        assert is_direct_media_url("https://x/a.webm#frag")
        assert is_direct_media_url("https://x/a.MOV")
        assert not is_direct_media_url("https://x/a.mp4/other")
        assert not is_direct_media_url("https://x/watch?v=1")
        assert not is_direct_media_url("https://x/a.txt")

    @pytest.mark.asyncio
    async def test_direct_download_success(self, tmp_path, monkeypatch):
        from tools import video_downloader as vdm
        chunks = [b"data1", b"data2"]

        class _Resp:
            """Объект-«ответ»: status_code + aiter_bytes + async-CM (его
            возвращает client.stream в download_direct)."""
            status_code = 200

            def __init__(self, status, chunks):
                self.status_code = status
                self._chunks = chunks

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def aiter_bytes(self, n):
                async def _gen():
                    for c in self._chunks:
                        yield c
                return _gen()

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        calls = {"n": 0}

        def _stream(self, method, url, headers=None):   # sync: async-with CM
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(403, [])
            return _Resp(200, chunks)

        _Client.stream = _stream
        monkeypatch.setattr(vdm.httpx, "AsyncClient", _Client)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        path = await dl.download_direct("https://2ch.su/a.mp4?t=1")
        assert path.read_bytes() == b"data1data2"
        assert calls["n"] == 2        # 403 → referer-retry → успех

    @pytest.mark.asyncio
    async def test_direct_download_all_403_fails(self, tmp_path, monkeypatch):
        from tools import video_downloader as vdm

        class _Resp:
            status_code = 403

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def aiter_bytes(self, n):
                async def _gen():
                    if False:
                        yield b""
                return _gen()

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None):
                return _Resp()

        monkeypatch.setattr(vdm.httpx, "AsyncClient", _Client)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadError):
            await dl.download_direct("https://2ch.su/a.mp4")

    @pytest.mark.asyncio
    async def test_direct_download_interrupt_removes_partial_file(
            self, tmp_path, monkeypatch):
        """B1: обрыв стрима (httpx.HTTPError) в середине загрузки →
        частично записанный файл НЕ остаётся на диске."""
        from tools import video_downloader as vdm

        class _Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def aiter_bytes(self, n):
                async def _gen():
                    yield b"partial-data"
                    raise vdm.httpx.HTTPError("connection reset by peer")
                return _gen()

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None):
                return _Resp()

        monkeypatch.setattr(vdm.httpx, "AsyncClient", _Client)
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path / "d"))
        with pytest.raises(vdm.DownloadError):
            await dl.download_direct("https://2ch.su/a.mp4")
        leftovers = list((tmp_path / "d").glob("vd_*"))
        assert leftovers == [], f"частичный файл остался: {leftovers}"

    @pytest.mark.asyncio
    async def test_direct_handler_unlinks_file_after_send(
            self, vd_env, tmp_path, monkeypatch):
        """B1: direct-ветка хендлера — файл существует на диске во время
        отправки и УДАЛЯЕТСЯ в finally после неё (прецедент
        cb_pick_quality)."""
        from tools import video_downloader as vdm

        class _Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def aiter_bytes(self, n):
                async def _gen():
                    yield b"hello"
                    yield b"-direct"
                return _gen()

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None):
                return _Resp()

        monkeypatch.setattr(vdm.httpx, "AsyncClient", _Client)

        class _Bot:
            def __init__(self):
                self.send_video = AsyncMock()

        bot = _Bot()
        msg = _make_msg("скачай https://2ch.su/a.mp4?t=1",
                        chat_type="private")
        await vd.video_download_handler(msg, bot=bot)
        assert bot.send_video.await_count == 1
        leftovers = list((tmp_path / "downloads").glob("vd_*"))
        assert leftovers == [], f"файл не удалён: {leftovers}"
        # 84.23: direct-ветка тоже регистрирует репортер и чистит реестр
        from services import progress_reporter as pr
        assert pr.get_active(CHAT_ID) is None


class TestNativeMedia:
    """3: «скачай <видео-сообщение>» — bot.get_file → temp → send_video."""

    @pytest.mark.asyncio
    async def test_native_video_flow(self, tmp_path, monkeypatch):
        from io import BytesIO
        from types import SimpleNamespace

        from handlers import video_download as vd_mod
        from tools import video_downloader as vdm

        vd_mod._downloader = vdm.VideoDownloader("http://localhost:9000/",
                                                 str(tmp_path))
        file_info = SimpleNamespace(file_path="video/file.mp4")

        class _Bot:
            def __init__(self):
                self.get_file = AsyncMock(return_value=file_info)
                self.download_file = AsyncMock(return_value=BytesIO(b"DATA"))
                self.send_video = AsyncMock()
                self.send_message = AsyncMock()

        bot = _Bot()
        msg = _make_msg("скачай", chat_type="private")
        msg.video = SimpleNamespace(file_id="fid123")
        await vd_mod.video_download_handler(msg, bot=bot)
        assert bot.get_file.await_count == 1
        assert bot.send_video.await_count == 1
        vd_mod._downloader = None
