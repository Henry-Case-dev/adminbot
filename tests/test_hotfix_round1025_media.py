"""ASAP-хотфикс round1025 (T-2461…T-2466, T-2468/T-2469) — медиа/транскрибация.

Проверяем:
  * эффективный лимит размера ЗАВИСИТ от режима Bot API (T-2464/ADR-1025-6 D2):
    local (--local) → конфиг (дефолт 50, до 2000); cloud-fallback → 20 МБ;
  * ранний честный гейт размера ДО скачивания — 25 МБ отклоняется в облаке
    и проходит в локальном режиме (T-2464/T-2465);
  * фраза «файл слишком большой» несёт ФАКТИЧЕСКИЙ лимит, без `{limit}` (T-2468);
  * сбой fetch логирует ТЕКСТ причины (T-2466), таймаут → отдельная фраза
    «провайдер не ответил» (T-2468), секреты в лог не попадают (R17/T-2469);
  * docker-compose включает локальный режим (T-2461/T-2462).
"""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import youtube as youtube_mod
from services import media_download
from services.smartmodule_phrases import (
    VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
    video_too_big_phrase,
)

CHAT_ID = -1001234567890
USER_ID = 111
MB = 1024 * 1024


@pytest.fixture
def yv_cleanup():
    yield
    youtube_mod._service = None
    youtube_mod._media_transcriber = None
    youtube_mod._media_db = None
    youtube_mod._media_memory = None
    youtube_mod._media_bot_id = None
    youtube_mod._cooldown._last.clear()


def _media(**kw):
    return MagicMock(**kw)


def _make_media_msg(text, video):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = 11
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = USER_ID
    msg.from_user.username = "vasya"
    msg.from_user.first_name = "Вася"
    msg.from_user.last_name = None
    msg.reply_to_message = None
    msg.forward_origin = None
    msg.video = video
    msg.document = None
    msg.voice = None
    msg.video_note = None
    return msg


def _make_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.set_message_reaction = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


def _setup():
    svc = MagicMock()
    svc.summarize_transcript = AsyncMock(return_value="выжимка")
    svc.summarize_cascade = AsyncMock(return_value="url-выжимка")
    youtube_mod.setup_youtube(svc)
    transcriber = MagicMock()
    transcriber.transcribe_voice = AsyncMock(return_value="текст расшифровки")
    youtube_mod.setup_youtube_video_media(transcriber, MagicMock(), None,
                                          MagicMock(), bot_id=999)
    return svc, transcriber


def _patch_fetch(monkeypatch, side_effect):
    mock = AsyncMock(side_effect=side_effect)
    monkeypatch.setattr(youtube_mod, "fetch_media_to_tmp", mock)
    return mock


class TestEffectiveLimitModeRound1025:
    def test_unset_env_is_cloud(self, monkeypatch):
        # Паритет с образом: не задано/пусто → облако (20 МБ). Ветка достижима
        # (мёртвых ветвей нет) — это и есть fallback ADR-1025-6 D3.
        monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)
        assert youtube_mod.telegram_local_mode_enabled() is False
        assert youtube_mod.video_bot_api_mode() == "cloud"

    def test_any_nonempty_env_is_local(self, monkeypatch):
        # Паритет с образом (append_flag_from_env): ЛЮБОЕ непустое = local,
        # включая "0"/"off" — поэтому откат делается УДАЛЕНИЕМ env, не "0".
        for value in ("1", "true", "0", "off", "yes"):
            monkeypatch.setenv("TELEGRAM_LOCAL", value)
            assert youtube_mod.telegram_local_mode_enabled() is True
            assert youtube_mod.video_bot_api_mode() == "local"

    def test_cloud_limit_is_20(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)
        assert youtube_mod.effective_video_max_size_mb() == 20

    def test_local_limit_uses_configured(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_LOCAL", "1")
        from config.settings import settings
        from services import hot_config as hot
        configured = int(hot.get("limits.video_transcribe_max_size_mb",
                                 settings.VIDEO_TRANSCRIBE_MAX_SIZE_MB))
        assert youtube_mod.effective_video_max_size_mb() == min(configured, 2000)

    def test_too_big_phrase_has_no_placeholder_actual_limit(self):
        phrase = youtube_mod._too_big_phrase(20)
        assert "{limit}" not in phrase
        assert "20" in phrase
        # ссылочная ветка (yt-dlp) — настроенный лимит, тоже без заглушки
        other = youtube_mod._too_big_phrase(
            youtube_mod._configured_video_max_size_mb())
        assert "{limit}" not in other


class TestSizeGateByModeRound1025:
    @pytest.mark.asyncio
    async def test_cloud_rejects_25mb_before_fetch(self, monkeypatch, yv_cleanup,
                                                   caplog):
        monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)   # облачный fallback
        _setup()
        fetch = _patch_fetch(monkeypatch, RuntimeError("must-not-run"))
        big = _media(file_id="f", file_size=25 * MB, duration=10)
        bot = _make_bot()
        with caplog.at_level(logging.INFO, logger="handlers.youtube"):
            await youtube_mod.youtube_handler(
                _make_media_msg("Бот, транскрипт", big), bot=bot)
        assert fetch.await_count == 0                 # гейт сработал раньше fetch
        sent = bot.send_message.await_args.args[1]
        assert "{limit}" not in sent and "20" in sent
        assert "limit_mb=20" in caplog.text
        assert "mode=cloud" in caplog.text

    @pytest.mark.asyncio
    async def test_local_allows_25mb_to_fetch(self, monkeypatch, yv_cleanup):
        monkeypatch.setenv("TELEGRAM_LOCAL", "1")
        _setup()
        fetch = _patch_fetch(monkeypatch, RuntimeError("stop-after-gate"))
        big = _media(file_id="f", file_size=25 * MB, duration=10)
        bot = _make_bot()
        await youtube_mod.youtube_handler(
            _make_media_msg("Бот, транскрипт", big), bot=bot)
        assert fetch.await_count == 1                 # 25 МБ прошли локальный гейт


class TestFetchDiagnosticsRound1025:
    @pytest.mark.asyncio
    async def test_fetch_timeout_uses_provider_timeout_phrase(self, monkeypatch,
                                                              yv_cleanup, caplog):
        monkeypatch.setenv("TELEGRAM_LOCAL", "1")
        _setup()
        _patch_fetch(monkeypatch,
                     asyncio.TimeoutError("bearer supersecrettoken12345"))
        small = _media(file_id="f", file_size=1000, duration=10)
        bot = _make_bot()
        with caplog.at_level(logging.WARNING, logger="handlers.youtube"):
            await youtube_mod.youtube_handler(
                _make_media_msg("Бот, транскрипт", small), bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES
        assert "TimeoutError" in caplog.text          # причина (класс) в логе
        assert "supersecrettoken12345" not in caplog.text   # R17: секрет скрыт

    @pytest.mark.asyncio
    async def test_fetch_failure_logs_reason_text(self, monkeypatch, yv_cleanup,
                                                  caplog):
        monkeypatch.setenv("TELEGRAM_LOCAL", "1")
        _setup()
        _patch_fetch(monkeypatch, RuntimeError("boom-detail-42"))
        small = _media(file_id="f", file_size=1000, duration=10)
        bot = _make_bot()
        with caplog.at_level(logging.WARNING, logger="handlers.youtube"):
            await youtube_mod.youtube_handler(
                _make_media_msg("Бот, транскрипт", small), bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_UNAVAILABLE_PHRASES
        assert "RuntimeError" in caplog.text          # класс
        assert "boom-detail-42" in caplog.text        # ТЕКСТ причины (T-2466)


class TestSafeExcTextRound1025:
    def test_empty_str_uses_repr(self):
        import httpx
        text = youtube_mod._safe_exc_text(httpx.ReadTimeout(""))
        assert text
        assert "ReadTimeout" in text

    def test_masks_bearer_secret(self):
        text = youtube_mod._safe_exc_text(
            RuntimeError("failed bearer supersecrettoken12345"))
        assert "supersecrettoken12345" not in text
        assert "***" in text

    def test_single_line(self):
        text = youtube_mod._safe_exc_text(RuntimeError("a\nb\r\nc"))
        assert "\n" not in text and "\r" not in text


class TestComposeLocalModeRound1025:
    def test_compose_reads_single_env_switch(self):
        text = Path("docker-compose.yml").read_text(encoding="utf-8")
        # ЕДИНЫЙ рубильник из общего .env (тот же читает хостовый процесс).
        assert 'TELEGRAM_LOCAL: "${TELEGRAM_LOCAL:-}"' in text
        assert "telegram-bot-api" in text
        # документированная процедура откатa: убрать env, НЕ ставить "0".
        assert "ОТКАТ" in text
        assert '"0"' in text and "непустое" in text

    def test_adr_documents_rollback_and_mode(self):
        adr = (Path(__file__).resolve().parents[1]
               / "plans/archive/hotfix-media-tma-round1025"
               / "adr-1025-6-bot-api-local-mode.md").read_text(encoding="utf-8")
        assert "TELEGRAM_LOCAL" in adr
        assert "убрать/закомментировать" in adr          # процедура откатa
        assert "пути host" in adr or "host ≠ container" in adr  # уточнение D263


class TestNoLimitPlaceholderLeakRound1025:
    def test_renderer_never_leaks_placeholder(self):
        for limit in (20, 50, 2000):
            phrase = video_too_big_phrase(limit)
            assert "{limit}" not in phrase
            assert str(limit) in phrase

    @pytest.mark.asyncio
    async def test_user_facing_reply_has_no_placeholder(self, monkeypatch,
                                                        yv_cleanup):
        monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)
        _setup()
        _patch_fetch(monkeypatch, RuntimeError("no"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(
            _make_media_msg("Бот, транскрипт",
                            _media(file_id="f", file_size=25 * MB, duration=10)),
            bot=bot)
        assert "{limit}" not in bot.send_message.await_args.args[1]


class TestLocalFilePathRound1025:
    """`local_file_path` (правка ревью Medium): абсолютный путь локального
    Bot API принимается ТОЛЬКО внутри TELEGRAM_API_FILES_DIR, иначе None."""

    def _bot(self, bot_id=999):
        bot = MagicMock()
        bot.id = bot_id
        return bot

    def _patch_root(self, monkeypatch, root):
        # config.settings — frozen dataclass → подменяем объект в модуле.
        monkeypatch.setattr(
            media_download, "settings",
            SimpleNamespace(TELEGRAM_API_FILES_DIR=str(root),
                            API_TOKEN="123456:secret"),
            raising=False)

    def test_relative_inside_root(self, tmp_path, monkeypatch):
        self._patch_root(monkeypatch, tmp_path)
        src = media_download.local_file_path(self._bot(), "videos/file_0.mp4")
        assert src is not None
        assert str(tmp_path) in str(src)

    def test_absolute_inside_root_accepted(self, tmp_path, monkeypatch):
        root = tmp_path / "files"
        self._patch_root(monkeypatch, root)
        inside = root / "7843:token" / "videos" / "file_0.mp4"
        src = media_download.local_file_path(self._bot(), str(inside))
        assert src == inside

    def test_absolute_outside_root_rejected(self, tmp_path, monkeypatch):
        self._patch_root(monkeypatch, tmp_path / "root")
        outside = tmp_path / "other" / "file_0.mp4"
        assert media_download.local_file_path(self._bot(), str(outside)) is None

    def test_relative_escape_rejected(self, tmp_path, monkeypatch):
        self._patch_root(monkeypatch, tmp_path)
        assert media_download.local_file_path(
            self._bot(), "../../escape.mp4") is None

    def test_junk_and_none_rejected(self, tmp_path, monkeypatch):
        self._patch_root(monkeypatch, tmp_path)
        assert media_download.local_file_path(self._bot(), "") is None
        assert media_download.local_file_path(self._bot(), None) is None
