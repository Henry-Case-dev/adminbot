"""Tests for Epic 66 — Cobalt Downloader (T-524/T-526/T-527, Section 70).

Триггер-парсинг, извлечение ссылок, уникальные разрешения, busy-лок,
кулдаун с remaining_time, мок Cobalt (aiohttp), удаление клавиатуры
(TelegramBadRequest → продолжение), cleanup файла в finally.
"""
import asyncio
import re
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
                 text=None, content=None):
        self._payload = payload
        self.status = status
        self._chunks = chunks
        self._text = text
        self._content_override = content

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
