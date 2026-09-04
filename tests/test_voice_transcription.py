"""Tests for Epic 67 — VoiceTranscriber (T-530/T-531/T-532, Section 71).

Паттерн Стратегия (fallback Groq→OpenRouter, TranscriptionUnavailable/
EmptyTranscript), хендлер 0i (лимит длительности, пулы фраз, HTML-формат
D268, cleanup temp в finally, F.audio/F.document не триггерят),
MediaMessage-обёртка для GraphRAG и UPDATE smart_messages_text.
"""
import asyncio
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import voice_transcription as vt
from services import media_download as md
from SmartModule.phrases import (
    VT_ALL_FAILED_PHRASES,
    VT_SILENCE_PHRASES,
    VT_TOO_LONG_PHRASES,
)
from SmartModule.service import (
    EmptyTranscript,
    TranscriptionUnavailable,
    VoiceTranscriber,
)
from SmartModule.transcriber.base import BaseTranscriber

CHAT_ID = -1001234567890
USER_ID = 111


# ── Фейки стратегий ─────────────────────────────────────────────────

class FakeTranscriber:
    name = "fake"
    timeout = 5.0

    def __init__(self, result="", error=None):
        self._result = result
        self._error = error
        self.calls = []

    @property
    def available(self):
        return True

    async def transcribe(self, file_path):
        self.calls.append(file_path)
        if self._error is not None:
            raise self._error
        return self._result


class UnavailableTranscriber(FakeTranscriber):
    @property
    def available(self):
        return False


# ── Хендлер-окружение ───────────────────────────────────────────────

def _make_msg(**kwargs):
    msg = MagicMock()
    msg.text = None
    msg.caption = None
    msg.forward_origin = None          # conftest.make_message convention
    msg.media_group_id = None
    msg.message_id = kwargs.pop("message_id", 12345)
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = kwargs.pop("user_id", USER_ID)
    msg.from_user.username = "vasya"
    msg.from_user.first_name = "Вася"
    msg.from_user.last_name = None
    msg.reply = AsyncMock()
    msg.voice = None
    msg.video_note = None
    for k, v in kwargs.items():
        setattr(msg, k, v)
    return msg


def _make_bot():
    bot = AsyncMock()
    bot.get_file = AsyncMock()      # хендлер НЕ должен звать напрямую (T-543)
    bot.download = AsyncMock()
    return bot


@pytest.fixture
def vt_env(tmp_path):
    """DI: чистое окружение хендлера + восстановление глобалов после теста."""
    old = (vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id)
    service = VoiceTranscriber(strategies=(FakeTranscriber("заглушка"),))
    db = MagicMock()
    db.update_smart_message_text = AsyncMock(return_value=1)
    aliases = MagicMock()
    aliases.resolve = MagicMock(side_effect=lambda uid, nickname=None, username=None:
                                nickname or "Анонимус")
    memory = MagicMock()
    memory.memorize_facts = AsyncMock()
    vt.setup_voice_transcription(service, db, aliases, memory, bot_id=999)
    yield service, db, aliases, memory
    vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id = old


@pytest.fixture
def tmp_file_path(tmp_path, monkeypatch):
    """mkstemp → tmp_path с записью созданного пути (для cleanup-тестов)."""
    created = []

    def _mkstemp(prefix="vt_", suffix=""):
        path = os.path.join(str(tmp_path), f"{prefix}x{suffix}")
        with open(path, "wb") as fh:
            fh.write(b"oggdata")
        created.append(path)
        return os.open(path, os.O_RDONLY), path

    monkeypatch.setattr(vt.tempfile, "mkstemp", _mkstemp)
    return created


# ── 1. Паттерн Стратегия / контроллер ────────────────────────────────

class TestServiceStrategy:
    @pytest.mark.asyncio
    async def test_groq_fails_fallback_to_openrouter(self):
        """T-530: Groq упал (исключение) → OpenRouter вызван, результат возвращён."""
        groq = FakeTranscriber(error=RuntimeError("502"))
        openrouter = FakeTranscriber(result="привет мир")
        service = VoiceTranscriber(strategies=(groq, openrouter))
        text = await service.transcribe_voice("/tmp/fake.ogg", "ogg")
        assert text == "привет мир"
        assert len(groq.calls) == 1
        assert len(openrouter.calls) == 1

    @pytest.mark.asyncio
    async def test_groq_timeout_fallback_to_openrouter(self):
        """Groq таймаут → управление сразу переходит к OpenRouter."""
        groq = FakeTranscriber(error=asyncio.TimeoutError())
        openrouter = FakeTranscriber(result="фолбэк")
        service = VoiceTranscriber(strategies=(groq, openrouter))
        assert await service.transcribe_voice("/tmp/fake.ogg", "ogg") == "фолбэк"

    @pytest.mark.asyncio
    async def test_both_fail_raises_unavailable(self):
        groq = FakeTranscriber(error=RuntimeError("down"))
        openrouter = FakeTranscriber(error=RuntimeError("down too"))
        service = VoiceTranscriber(strategies=(groq, openrouter))
        with pytest.raises(TranscriptionUnavailable):
            await service.transcribe_voice("/tmp/fake.ogg", "ogg")

    @pytest.mark.asyncio
    async def test_empty_results_raise_empty_transcript(self):
        service = VoiceTranscriber(
            strategies=(FakeTranscriber(result="   "),
                        FakeTranscriber(result="")))
        with pytest.raises(EmptyTranscript):
            await service.transcribe_voice("/tmp/fake.ogg", "ogg")

    @pytest.mark.asyncio
    async def test_unavailable_strategy_skipped_no_retry(self):
        """Стратегия без ключа пропускается; ретраев нет — один вызов на каждого."""
        groq = FakeTranscriber(error=RuntimeError("x"))
        openrouter = FakeTranscriber(result="ок")
        service = VoiceTranscriber(
            strategies=(UnavailableTranscriber(), groq, openrouter))
        assert await service.transcribe_voice("/tmp/fake.ogg", "ogg") == "ок"
        assert len(groq.calls) == 1 and len(openrouter.calls) == 1

    def test_default_strategies_order_groq_then_openrouter(self):
        from SmartModule.service import GroqTranscriber, OpenRouterTranscriber  # noqa: F401
        from SmartModule.transcriber import GroqTranscriber as G, OpenRouterTranscriber as O
        service = VoiceTranscriber()
        assert isinstance(service._strategies[0], G)
        assert isinstance(service._strategies[1], O)

    def test_openrouter_audio_format_mapping(self):
        """Epic 67 (решение @Reviewer): OpenRouter НЕ поддерживает format='mp4'
        (доки: wav/mp3/flac/m4a/ogg/webm/aac) → video_note (.mp4) маппится
        в 'm4a' (MIME audio/mp4); voice (.ogg) остаётся 'ogg'."""
        from SmartModule.transcriber.openrouter_transcriber import (
            OpenRouterTranscriber,
        )
        f = OpenRouterTranscriber._audio_format
        assert f("/tmp/vt_x.mp4") == "m4a"
        assert f("/tmp/vt_x.ogg") == "ogg"
        assert f("/tmp/vt_x") == "ogg"

    # ── Epic 79.5 (D295): rate limiting + очередь ───────────────────────

    @pytest.mark.asyncio
    async def test_concurrent_requests_serialized(self):
        """Epic 79.5: max_concurrency=1 → запросы выполняются строго
        последовательно (semaphore), а не параллельно."""
        import time as _time

        calls = []

        class SlowTranscriber(BaseTranscriber):
            name = "slow"
            timeout = 5.0

            @property
            def available(self):
                return True

            async def transcribe(self, file_path: str) -> str:
                calls.append(_time.monotonic())
                await asyncio.sleep(0.5)  # имитация LLM-запроса
                return "ok"

        service = VoiceTranscriber(
            strategies=(SlowTranscriber(),), max_concurrency=1)
        # 3 одновременных запроса
        results = await asyncio.gather(*[
            service.transcribe_voice("/tmp/fake", "ogg") for _ in range(3)
        ])
        assert all(r == "ok" for r in results)
        assert len(calls) == 3
        # Интервалы между началом вызовов должны быть >= 0.5s (сериализованы)
        intervals = [calls[i + 1] - calls[i] for i in range(len(calls) - 1)]
        for iv in intervals:
            assert iv >= 0.45  # небольшая темерь для flakiness


# ── 2. Хендлер: пулы фраз и фильтры ─────────────────────────────────

class TestHandlerPools:
    @pytest.mark.asyncio
    async def test_duration_limit_replies_too_long(self, vt_env, tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=601, file_id="f1"))
        result = await vt.voice_transcription_handler(msg, bot=_make_bot())
        assert result is vt.UNHANDLED
        replied = msg.reply.call_args.args[0]
        assert replied in VT_TOO_LONG_PHRASES
        assert len(tmp_file_path) == 0            # файл НЕ качали
        vt._db.update_smart_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_failed_replies_api_fail_pool(self, vt_env, tmp_file_path):
        vt._service = VoiceTranscriber(strategies=(
            FakeTranscriber(error=RuntimeError("a")),
            FakeTranscriber(error=RuntimeError("b")),
        ))
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        result = await vt.voice_transcription_handler(msg, bot=_make_bot())
        assert result is vt.UNHANDLED
        replied = msg.reply.call_args.args[0]
        assert replied in VT_ALL_FAILED_PHRASES

    @pytest.mark.asyncio
    async def test_empty_transcript_replies_silence_pool(self, vt_env, tmp_file_path):
        vt._service = VoiceTranscriber(strategies=(
            FakeTranscriber(result=""),
            FakeTranscriber(result="  "),
        ))
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        result = await vt.voice_transcription_handler(msg, bot=_make_bot())
        assert result is vt.UNHANDLED
        replied = msg.reply.call_args.args[0]
        assert replied in VT_SILENCE_PHRASES

    @pytest.mark.asyncio
    async def test_audio_and_document_do_not_trigger(self, vt_env):
        from aiogram.dispatcher.event.bases import UNHANDLED
        for media in ("audio", "document"):
            msg = _make_msg(**{media: MagicMock()})
            bot = _make_bot()
            result = await vt.voice_transcription_handler(msg, bot=bot)
            assert result is UNHANDLED
            msg.reply.assert_not_called()
            bot.get_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_own_voice_skipped(self, vt_env):
        msg = _make_msg(user_id=999, voice=MagicMock(duration=10, file_id="f1"))
        bot = _make_bot()
        await vt.voice_transcription_handler(msg, bot=bot)
        msg.reply.assert_not_called()
        bot.get_file.assert_not_called()


# ── 3. Формат вывода (D268) ─────────────────────────────────────────

class TestOutputFormat:
    @pytest.mark.asyncio
    async def test_success_reply_html_escaped(self, vt_env, tmp_file_path):
        vt._service = VoiceTranscriber(
            strategies=(FakeTranscriber(result="<b> & привет"),))
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        bot = _make_bot()
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED              # observer-стиль
        args, kwargs = msg.reply.call_args
        assert args[0] == "<b>Вася</b> 🗣: <i>&lt;b&gt; &amp; привет</i>"
        assert kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_reply_is_on_the_voice_message(self, vt_env, tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        msg.reply.assert_called_once()             # reply() = строго на голосовое


# ── 4. Инъекция в память (D267, двойная) ────────────────────────────

class TestMemoryInjection:
    @pytest.mark.asyncio
    async def test_update_smart_message_text_called(self, vt_env, tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        vt._db.update_smart_message_text.assert_awaited_once_with(
            CHAT_ID, msg.message_id, "заглушка")

    @pytest.mark.asyncio
    async def test_memorize_facts_wrapped_media_message_voice(self, vt_env,
                                                              tmp_file_path):
        import re
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        await asyncio.sleep(0)                     # дать fire_and_forget стартовать
        args, kwargs = vt._memory.memorize_facts.call_args
        raw_text, source_type = args[1], kwargs["source_type"]
        assert source_type == "voice_transcript"
        m = re.fullmatch(
            r'<MediaMessage type="voice" sender="([^"]*)" '
            r'timestamp="([^"]*)">([^<]*)</MediaMessage>', raw_text)
        assert m, raw_text
        assert m.group(1) == "Вася"
        assert m.group(3) == "заглушка"
        # ISO8601 UTC timestamp
        from datetime import datetime
        datetime.fromisoformat(m.group(2))

    @pytest.mark.asyncio
    async def test_memorize_facts_video_note_type(self, vt_env, tmp_file_path):
        msg = _make_msg(video_note=MagicMock(duration=10, file_id="f2"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        await asyncio.sleep(0)
        args, kwargs = vt._memory.memorize_facts.call_args
        assert 'type="video_note"' in args[1]

    def test_wrap_media_fact_format(self):
        tag = vt.wrap_media_fact("voice", "Слава", "текст")
        assert tag.startswith('<MediaMessage type="voice" sender="Слава" ')
        assert tag.endswith(">текст</MediaMessage>")


# ── 5. Cleanup temp в finally ────────────────────────────────────────

class TestTempCleanup:
    @pytest.mark.asyncio
    async def test_temp_removed_even_on_error(self, vt_env, tmp_file_path):
        """Ошибка скачивания → UNHANDLED без реплая, temp удалён в finally."""
        bot = _make_bot()
        bot.download.side_effect = RuntimeError("download boom")
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        assert len(tmp_file_path) == 1
        assert not os.path.exists(tmp_file_path[0])   # файл удалён при ошибке
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_temp_suffix_by_media_type(self, vt_env, tmp_file_path):
        msg = _make_msg(video_note=MagicMock(duration=10, file_id="f2"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        assert tmp_file_path[0].endswith(".mp4")


# ── 5b. Паттерн скачивания Bot.download (хотфикс v2.46.1, T-543) ────

class TestBotDownloadPattern:
    @pytest.mark.asyncio
    async def test_download_called_with_file_id_and_destination(
            self, vt_env, tmp_file_path):
        """T-543: bot.download(media.file_id, destination=path), destination —
        созданный mkstemp-путь."""
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        bot = _make_bot()
        await vt.voice_transcription_handler(msg, bot=bot)
        bot.download.assert_awaited_once()
        args, kwargs = bot.download.await_args
        assert args[0] == "f1"
        assert kwargs["destination"] == tmp_file_path[0]

    def test_handler_source_has_no_legacy_call(self):
        """Регрессия v2.46.1 (+ Epic 78 T-579) и Bugfix 04.09.2026 (Часть 1,
        T-669): в исходнике хендлера нет download_to_drive; скачивание — через
        общий хелпер services/media_download (fetch_media_to_tmp; get_file
        легитимен ТОЛЬКО внутри него)."""
        import inspect
        src = inspect.getsource(vt)
        assert "download_to_drive" not in src
        assert "download_to_drive" not in inspect.getsource(md)
        assert "_fetch_media_to_tmp" in src
        assert "services.media_download" in src
        assert "def fetch_media_to_tmp" in inspect.getsource(md)
        assert "bot.download(" in inspect.getsource(md)

    @pytest.mark.asyncio
    async def test_no_direct_get_file_at_runtime(self, vt_env, tmp_file_path):
        """Хендлер использует bot.download → get_file НЕ вызывается напрямую."""
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        bot = _make_bot()
        await vt.voice_transcription_handler(msg, bot=bot)
        bot.get_file.assert_not_called()
        bot.download.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_temp_cleaned_up_when_bot_download_raises(
            self, vt_env, tmp_file_path):
        """Ошибка bot.download → UNHANDLED без реплая, temp удалён в finally."""
        bot = _make_bot()
        bot.download.side_effect = RuntimeError("download boom")
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        assert len(tmp_file_path) == 1
        assert not os.path.exists(tmp_file_path[0])
        msg.reply.assert_not_called()


# ── 5c. Epic 78 (T-579, Section 79/D292): резолв host-пути ──────────

class TestEpic78LocalApiResolve:
    """Локальный режим (DOWNLOAD_ENABLED=True = гейт D262) + относительный
    file_path → копирование из TELEGRAM_API_FILES_DIR/<bot_id>:<token>/;
    файла нет / абсолютный path / облако → фолбэк bot.download; токен НЕ
    в логах (R17); cleanup tmp сохранён."""

    BOT_ID = 4242

    @staticmethod
    def _cfg(**overrides):
        """Копия frozen-Settings с переопределениями (прецедент
        tests/test_typing_manager.py::_cfg)."""
        import dataclasses
        from config.settings import settings as real_settings
        return dataclasses.replace(real_settings, **overrides)

    @pytest.fixture
    def local_mode(self, tmp_path, monkeypatch):
        files_dir = tmp_path / "tgapi"
        cfg = self._cfg(
            DOWNLOAD_ENABLED=True,
            TELEGRAM_API_FILES_DIR=str(files_dir))
        # Bugfix 04.09.2026 (Часть 1): хелпер скачивания теперь в
        # services.media_download — патчим settings ОБОИХ модулей.
        monkeypatch.setattr(vt, "settings", cfg)
        monkeypatch.setattr(md, "settings", cfg)
        return files_dir

    @pytest.fixture
    def vsrc(self, local_mode, monkeypatch):
        """Виртуальный файл(ы) внутри '<dir>/<bot_id>:<token>/'. На Windows
        ':' в имени каталога запрещён, поэтому FS-слой подменяется ТОЧЕЧНО
        (только пути под TELEGRAM_API_FILES_DIR): Path.exists и
        shutil.copyfile хелпера (services.media_download)."""
        files = {}                       # str(abs_path) -> bytes
        copied = {}                      # str(abs_src) -> str(dst)
        root = str(local_mode)
        real_exists = Path.exists

        def fake_exists(pself):
            s = str(pself)
            if s.startswith(root):
                return s in files
            return real_exists(pself)

        def fake_copyfile(src, dst):
            assert str(src) in files, str(src)
            copied[str(src)] = str(dst)
            with open(dst, "wb") as fh:
                fh.write(files[str(src)])

        monkeypatch.setattr(Path, "exists", fake_exists)
        monkeypatch.setattr(md.shutil, "copyfile", fake_copyfile)
        return files, copied

    def _src_path(self, files_dir, rel):
        # Epic 78 hotfix: имя каталога строит сам хендлер (_local_files_subdir):
        # токен уже может содержать '<bot_id>:' — задвоение недопустимо.
        token = str(vt.settings.API_TOKEN)
        prefix = f"{self.BOT_ID}:"
        dirname = token if token.startswith(prefix) else prefix + token
        return str(files_dir / dirname / rel)

    def _local_bot(self):
        bot = _make_bot()
        bot.id = self.BOT_ID
        return bot

    @staticmethod
    def _tg_file(file_path):
        tg = MagicMock()
        tg.file_path = file_path
        return tg

    @pytest.mark.asyncio
    async def test_local_relative_existing_file_copied_no_download(
            self, vt_env, tmp_file_path, vsrc, local_mode):
        """Кейс 1: файл на диске → скопирован в tmp, bot.download НЕ зван."""
        files, copied = vsrc
        src_key = self._src_path(local_mode, "video_notes/file_0.mp4")
        files[src_key] = b"circldata"
        msg = _make_msg(video_note=MagicMock(duration=10, file_id="f2"))
        bot = self._local_bot()
        bot.get_file.return_value = self._tg_file("video_notes/file_0.mp4")
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        # tmp удалён в finally ПОСЛЕ успешной расшифровки — содержимое
        # проверяем через запись fake-копирования
        assert copied == {src_key: tmp_file_path[0]}
        bot.download.assert_not_awaited()
        assert "заглушка" in msg.reply.call_args.args[0]

    @pytest.mark.asyncio
    async def test_missing_file_falls_back_to_download(
            self, vt_env, tmp_file_path, local_mode, caplog):
        """Кейс 2: файла нет → WARNING без токена + bot.download как раньше."""
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        bot = self._local_bot()
        bot.get_file.return_value = self._tg_file("music/file_1.ogg")
        with caplog.at_level(logging.WARNING,
                             logger="handlers.voice_transcription"):
            result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        bot.download.assert_awaited_once_with(
            "f1", destination=tmp_file_path[0])
        assert any("local api file missing" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_cloud_mode_straight_download_no_get_file(
            self, vt_env, tmp_file_path, monkeypatch):
        """Кейс 3: DOWNLOAD_ENABLED=False → сразу bot.download, get_file и
        резолв диска не выполняются."""
        cfg = self._cfg(DOWNLOAD_ENABLED=False)
        monkeypatch.setattr(vt, "settings", cfg)
        monkeypatch.setattr(md, "settings", cfg)
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        bot = _make_bot()
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        bot.get_file.assert_not_awaited()
        bot.download.assert_awaited_once_with(
            "f1", destination=tmp_file_path[0])

    @pytest.mark.asyncio
    async def test_absolute_file_path_skips_host_resolve(
            self, vt_env, tmp_file_path, local_mode):
        """Кейс 4: абсолютный file_path → без host-resolve, ветка bot.download."""
        abs_path = "/var/lib/telegram-bot-api/data/file_2.mp4"
        msg = _make_msg(video_note=MagicMock(duration=10, file_id="f3"))
        bot = self._local_bot()
        bot.get_file.return_value = self._tg_file(abs_path)
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        bot.download.assert_awaited_once_with(
            "f3", destination=tmp_file_path[0])
        # ничего не скопировано с диска (root даже не создавался)
        assert not local_mode.exists()

    @pytest.mark.asyncio
    async def test_token_never_logged_any_branch(
            self, vt_env, tmp_file_path, local_mode, caplog, monkeypatch,
            vsrc):
        """Кейс 5: токен и '<bot_id>:<token>' отсутствуют во всех логах
        (существующий файл / файл missing / копирование упало / облако)."""
        token = vt.settings.API_TOKEN
        prefix = f"{self.BOT_ID}:"
        secret = token if token.startswith(prefix) else prefix + token
        files, copied = vsrc
        key_ok = self._src_path(local_mode, "music/ok.ogg")
        files[key_ok] = b"x"

        # ВАЖНО: sync-функция — хелпер зовёт её через asyncio.to_thread;
        # async-функция здесь создала бы невзведённую корутину (RuntimeWarning)
        # и ветка «копирование упало» не выполнялась бы вовсе.
        def _boom_copy(src, dst):
            raise OSError(f"boom {src}")

        bot = self._local_bot()

        with caplog.at_level(logging.DEBUG,
                             logger="handlers.voice_transcription"):
            # A: существующий файл (копирование ок)
            m1 = _make_msg(voice=MagicMock(duration=10, file_id="a"))
            bot.get_file.return_value = self._tg_file("music/ok.ogg")
            await vt.voice_transcription_handler(m1, bot=bot)
            # B: файл отсутствует → WARNING fallback
            m2 = _make_msg(voice=MagicMock(duration=10, file_id="b"))
            bot.get_file.return_value = self._tg_file("music/gone.ogg")
            await vt.voice_transcription_handler(m2, bot=bot)
            # C: копирование упало → fallback download (тоже падает)
            bot.download.side_effect = RuntimeError("dl boom")
            prev_copyfile = md.shutil.copyfile
            md.shutil.copyfile = _boom_copy
            try:
                m3 = _make_msg(voice=MagicMock(duration=10, file_id="c"))
                bot.get_file.return_value = self._tg_file("music/ok.ogg")
                await vt.voice_transcription_handler(m3, bot=bot)
            finally:
                md.shutil.copyfile = prev_copyfile
            bot.download.side_effect = None
            # D: get_file упал → fallback download
            bot.get_file.side_effect = RuntimeError("api boom")
            m4 = _make_msg(voice=MagicMock(duration=10, file_id="d"))
            await vt.voice_transcription_handler(m4, bot=bot)
            bot.get_file.side_effect = None
            # E: облачный режим
            cfg_cloud = self._cfg(DOWNLOAD_ENABLED=False)
            monkeypatch.setattr(vt, "settings", cfg_cloud)
            monkeypatch.setattr(md, "settings", cfg_cloud)
            m5 = _make_msg(voice=MagicMock(duration=10, file_id="e"))
            await vt.voice_transcription_handler(m5, bot=_make_bot())

        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert token not in blob
        assert secret not in blob
        assert key_ok not in blob
        # ветка C реально выполнена: OSError с ПОЛНЫМ путём (в сообщении
        # исключения есть '<bot_id>:<token>') залогирован только как src.name
        assert any("host copy failed" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_both_media_types_suffix_preserved(
            self, vt_env, tmp_file_path, vsrc, local_mode):
        """Кейс 6: voice (.ogg) и video_note (.mp4) — суффикс/формат Epic 67
        не меняются, обе ветки проходят."""
        files, copied = vsrc
        cases = [
            ("voice", MagicMock(duration=10, file_id="v1"),
             "music/file_5.ogg", ".ogg"),
            ("video_note", MagicMock(duration=10, file_id="v2"),
             "video_notes/file_6.mp4", ".mp4"),
        ]
        for attr, media, file_path, suffix in cases:
            src_key = self._src_path(local_mode, file_path)
            files[src_key] = b"media-bytes"
            msg = _make_msg(**{attr: media})
            bot = self._local_bot()
            bot.get_file.return_value = self._tg_file(file_path)
            result = await vt.voice_transcription_handler(msg, bot=bot)
            assert result is vt.UNHANDLED
            assert copied[src_key] == tmp_file_path[-1]
            assert tmp_file_path[-1].endswith(suffix)
            bot.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cleanup_on_helper_exception(
            self, vt_env, tmp_file_path, vsrc, local_mode, monkeypatch):
        """Кейс 7: исключение хелпера (копирование упало) → fallback
        bot.download тоже падает → tmp удалён существующим finally,
        UNHANDLED без реплая."""
        files, copied = vsrc
        files[self._src_path(local_mode, "music/file_7.ogg")] = b"y"

        def _boom_copy(src, dst):
            raise OSError("copy failed")

        monkeypatch.setattr(md.shutil, "copyfile", _boom_copy)
        bot = self._local_bot()
        bot.download.side_effect = RuntimeError("download boom")
        bot.get_file.return_value = self._tg_file("music/file_7.ogg")
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f7"))
        result = await vt.voice_transcription_handler(msg, bot=bot)
        assert result is vt.UNHANDLED
        assert copied == {}                       # копирование не "успело"
        assert len(tmp_file_path) == 1
        assert not os.path.exists(tmp_file_path[0])
        msg.reply.assert_not_called()


# ── 6. БД: update_smart_message_text ────────────────────────────────

class TestDatabaseMethod:
    @pytest.mark.asyncio
    async def test_updates_text_and_reports_missing_row(self, tmp_path):
        from services.database import DatabaseService
        d = DatabaseService(":memory:")
        await d.initialize()
        try:
            row_id = await d.save_smart_message(
                user_id=1, chat_id=CHAT_ID, text=None, reply_to_id=None,
                timestamp=1000, media_type="voice", author_name="вася",
                message_id=777)
            updated = await d.update_smart_message_text(CHAT_ID, 777, "транскрипт")
            assert updated == 1
            cursor = await d.db.execute(
                "SELECT text FROM smart_messages WHERE id = ?", (row_id,))
            assert (await cursor.fetchone())["text"] == "транскрипт"
            # нет записи → no-op
            assert await d.update_smart_message_text(CHAT_ID, 88888, "x") == 0
        finally:
            await d.close()


# ── 7. summary_xml микро-правка (D267) ──────────────────────────────

class TestXmlBodyNoSuffix:
    def test_transcribed_voice_text_without_placeholder(self):
        from services.summary_xml import XmlGroundingBuilder
        row = {"id": 1, "user_id": 1, "timestamp": 1700000000,
               "author_name": "вася", "text": "привет",
               "reply_to_id": None, "media_type": "voice",
               "is_forward": False, "forward_source": ""}
        xml = XmlGroundingBuilder()._build_body("привет", "voice")
        assert xml == "привет"                     # без суффикса [голосовое]

    def test_untranscribed_voice_keeps_placeholder(self):
        from services.summary_xml import XmlGroundingBuilder
        assert XmlGroundingBuilder()._build_body(None, "voice") == "[голосовое]"

    def test_video_note_maps_to_video_type(self):
        from services.summary_xml import XmlGroundingBuilder
        assert XmlGroundingBuilder()._build_body("кружок", "video") == "кружок"


# ── 8. origin допущен в _FACT_ORIGINS ───────────────────────────────

def test_voice_transcript_in_fact_origins():
    from services.summary_memory import _FACT_ORIGINS
    assert "voice_transcript" in _FACT_ORIGINS


# ── Epic 72 (74.B/D272): автор форварда в транскрипции ───────────────

from aiogram.types import (
    Chat,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    User,
)


def _origin_user(user_id=555, first_name="Олег", username="oleg_src"):
    return MessageOriginUser(
        type="user", date=1234567890,
        sender_user=User(id=user_id, is_bot=False, first_name=first_name,
                         username=username))


def _origin_hidden(name="Скрытый Гость"):
    return MessageOriginHiddenUser(
        type="hidden_user", date=1234567890, sender_user_name=name)


def _origin_channel(title="Канал X", username="channelx"):
    return MessageOriginChannel(
        type="channel", date=1234567890,
        chat=Chat(id=-100999, type="channel", title=title, username=username),
        message_id=42)


def _origin_chat(title="Группа Y", username="groupy"):
    return MessageOriginChat(
        type="chat", date=1234567890,
        sender_chat=Chat(id=-100888, type="group", title=title,
                         username=username))


@pytest.fixture
def summary_aliases(monkeypatch):
    """_extract_forward_source читает глобальную handlers.summary._aliases."""
    from handlers import summary as summary_mod
    resolver = MagicMock()
    resolver.resolve = MagicMock(
        side_effect=lambda uid, nickname=None, username=None:
            nickname or "Анонимус")
    monkeypatch.setattr(summary_mod, "_aliases", resolver)
    return resolver


class TestResolveTranscriptAuthor:
    """Epic 72 (74.B.1/D272): каскад переиспользован из handlers/summary."""

    def test_forward_from_user_resolves_via_alias_cascade(self, summary_aliases):
        msg = _make_msg()
        msg.forward_origin = _origin_user(first_name="Олег")
        assert vt._resolve_transcript_author(msg) == "Олег"
        summary_aliases.resolve.assert_called_once()

    def test_forward_hidden_user_uses_sender_user_name(self, summary_aliases):
        msg = _make_msg()
        msg.forward_origin = _origin_hidden("Скрытый Гость")
        assert vt._resolve_transcript_author(msg) == "Скрытый Гость"

    def test_forward_channel_uses_title_and_username(self, summary_aliases):
        msg = _make_msg()
        msg.forward_origin = _origin_channel("Канал X", "channelx")
        assert vt._resolve_transcript_author(msg) == "Канал X @channelx"

    def test_forward_chat_uses_title(self, summary_aliases):
        msg = _make_msg()
        msg.forward_origin = _origin_chat("Группа Y", "groupy")
        assert vt._resolve_transcript_author(msg) == "Группа Y @groupy"

    def test_exotic_origin_falls_back_to_unknown(self, summary_aliases):
        """Origin есть, извлечение вернуло None → локальная константа."""
        msg = _make_msg()
        msg.forward_origin = object()          # не MessageOrigin*
        assert vt._resolve_transcript_author(msg) == "Неизвестный"
        assert vt._VT_UNKNOWN_AUTHOR == "Неизвестный"

    def test_origin_user_without_sender_unknown(self, summary_aliases):
        msg = _make_msg()
        msg.forward_origin = MessageOriginUser.model_construct(
            type="user", date=1234567890, sender_user=None)
        assert vt._resolve_transcript_author(msg) == "Неизвестный"

    def test_no_origin_keeps_old_from_user_cascade(self, vt_env):
        """Не-форвард → прежний каскад от from_user (D268-поведение)."""
        msg = _make_msg()
        assert msg.forward_origin is None
        assert vt._resolve_transcript_author(msg) == "Вася"


class TestForwardOutputFormat:
    @pytest.mark.asyncio
    async def test_forward_reply_has_forwarder_label(self, vt_env,
                                                     tmp_file_path,
                                                     summary_aliases):
        """D272: <b>{автор}</b> (переслал {пересыльщик}) 🗣: <i>{text}</i>."""
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        msg.forward_origin = _origin_hidden("Скрытый Гость")
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        args, kwargs = msg.reply.call_args
        assert args[0] == ("<b>Скрытый Гость</b> (переслал Вася) "
                           "🗣: <i>заглушка</i>")
        assert kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_non_forward_format_byte_identical(self, vt_env,
                                                     tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        args, _ = msg.reply.call_args
        assert args[0] == "<b>Вася</b> 🗣: <i>заглушка</i>"

    @pytest.mark.asyncio
    async def test_forward_source_name_html_escaped(self, vt_env,
                                                    tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        msg.forward_origin = _origin_hidden("<b>&Хакер")
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        args, _ = msg.reply.call_args
        assert "&lt;b&gt;&amp;Хакер" in args[0]
        assert "<b>&Хакер" not in args[0]

    @pytest.mark.asyncio
    async def test_forward_channel_label(self, vt_env, tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        msg.forward_origin = _origin_channel()
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        args, _ = msg.reply.call_args
        assert args[0].startswith("<b>Канал X @channelx</b> (переслал Вася)")


class TestWrapMediaFactForward:
    """Epic 72 (74.B.3/D273): атрибуты forwarded/forward_from в факте."""

    def test_forward_attributes_added_and_escaped(self):
        tag = vt.wrap_media_fact("voice", "Слава", "текст",
                                 forward_source='A<b>&"C')
        assert 'forwarded="true"' in tag
        assert 'forward_from="A&lt;b&gt;&amp;&quot;C"' in tag
        # атрибуты внутри открывающего тега, до текста
        assert tag.index('forward_from=') < tag.index(">текст<")

    def test_default_no_forward_attributes(self):
        tag = vt.wrap_media_fact("voice", "Слава", "текст")
        assert "forwarded" not in tag
        assert "forward_from" not in tag

    @pytest.mark.asyncio
    async def test_memorize_facts_carries_forward_attrs(self, vt_env,
                                                        tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        msg.forward_origin = _origin_hidden("Скрытый Гость")
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        await asyncio.sleep(0)
        args, _ = vt._memory.memorize_facts.call_args
        assert 'forwarded="true"' in args[1]
        assert 'forward_from="Скрытый Гость"' in args[1]

    @pytest.mark.asyncio
    async def test_memorize_facts_plain_voice_no_attrs(self, vt_env,
                                                       tmp_file_path):
        msg = _make_msg(voice=MagicMock(duration=10, file_id="f1"))
        await vt.voice_transcription_handler(msg, bot=_make_bot())
        await asyncio.sleep(0)
        args, _ = vt._memory.memorize_facts.call_args
        assert "forwarded" not in args[1]


# ── Epic 72 (74.C/D274): детектор «reply на расшифровку» ─────────────

class TestIsReplyToTranscription:
    def _target(self, text="Вася 🗣: привет", user_id=999,
                reply_to_message=None):
        t = MagicMock()
        t.text = text
        t.from_user = MagicMock()
        t.from_user.id = user_id
        t.reply_to_message = reply_to_message
        t.voice = None
        t.video_note = None
        return t

    def _msg(self, target):
        m = _make_msg(text="спасибо")
        m.reply_to_message = target
        return m

    @pytest.mark.asyncio
    async def test_true_by_anchor(self, vt_env):
        assert vt.is_reply_to_transcription(self._msg(self._target()))

    @pytest.mark.asyncio
    async def test_true_for_forward_format_anchor(self, vt_env):
        t = self._target("Вася (переслал Коля) 🗣: привет")
        assert vt.is_reply_to_transcription(self._msg(t))

    @pytest.mark.asyncio
    async def test_false_for_foreign_user_target(self, vt_env):
        t = self._target(user_id=111)
        assert not vt.is_reply_to_transcription(self._msg(t))

    @pytest.mark.asyncio
    async def test_false_for_regular_bot_answer(self, vt_env):
        t = self._target("держи ответ, брат")
        assert not vt.is_reply_to_transcription(self._msg(t))

    @pytest.mark.asyncio
    async def test_structural_fallback_voice(self, vt_env):
        orig = MagicMock()
        orig.voice = MagicMock()
        orig.video_note = None
        t = self._target(text="", reply_to_message=orig)
        assert vt.is_reply_to_transcription(self._msg(t))

    @pytest.mark.asyncio
    async def test_structural_fallback_video_note(self, vt_env):
        orig = MagicMock()
        orig.voice = None
        orig.video_note = MagicMock()
        t = self._target(text="", reply_to_message=orig)
        assert vt.is_reply_to_transcription(self._msg(t))

    @pytest.mark.asyncio
    async def test_structural_fallback_requires_voice_chain(self, vt_env):
        orig = MagicMock()
        orig.voice = None
        orig.video_note = None
        t = self._target(text="", reply_to_message=orig)
        assert not vt.is_reply_to_transcription(self._msg(t))

    @pytest.mark.asyncio
    async def test_false_without_reply(self, vt_env):
        assert not vt.is_reply_to_transcription(_make_msg(text="привет"))
