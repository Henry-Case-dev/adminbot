"""Раунд 10.24 (F19, ADR-1024-20) — инструмент `transcribe_video` + команда
«транскрипт» (принудительный повтор ГС/кружка) + канон R9 = 10.

Покрытие spec §6:
(a) различимые EN-определения `summarize_video` (выжимка) vs `transcribe_video`
    (сырой текст); `additionalProperties:false`, `required` без `url`, `source`;
(b) «транскрипт» реплаем на voice/video_note → STT вызван заново, ответ
    курсивом `<b>…</b> 🗣: <i>…</i>` реплаем на целевое, temp удалён,
    идемпотентность `memorize_facts`;
(c) YouTube-URL + «транскрипт» → курсивный сырой транскрипт (без саммаризации);
(d) канон = 10, `transcribe_video` в конец, первые 9 байт-в-байт;
(e) dispatch: YouTube-субтитры raw / direct download+STT / native video+voice;
(g) ошибки — строки, не исключения (нет источника / нет STT / voice не выжимка);
(h) флаг `MEDIA_TRANSCRIBE_TOOL_ENABLED` OFF → нет в `active_tools` + нейтральный
    ответ по ГС; схема/канон 10 безусловны;
(i) R17 — в логах нет URL/file_id (только source/kind/out_chars).
(f) без команды — авто-путь 0i не изменился (force=False → memorize как прежде).

Без сети: фейки bot/downloader/STT/DB.
"""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from handlers import voice_transcription as vt
from handlers import youtube as yt
from services import native_media
from services.smartmodule_phrases import COMMAND_NO_TARGET_PHRASES
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import (
    TOOL_CALLING_TOOLS,
    TOOL_SUMMARIZE_VIDEO,
    TOOL_TRANSCRIBE_VIDEO,
    active_tools,
)

CHAT_ID = -1001234567890
USER_ID = 111
YT_URL = "https://youtu.be/dQw4w9WgXcQ"
DIRECT_URL = "https://cdn.example.com/clip.mp4"

_FIRST_NINE = [
    "query_chat_memory", "dig_into_lore", "execute_web_search",
    "summarize_video", "download_media", "get_bot_health",
    "get_recent_history", "compile_lore_story", "generate_image"]


# ── фейки / окружение ────────────────────────────────────────────────────


def _make_msg(text=None, caption=None, message_id=11, user_id=USER_ID,
              video=None, document=None, voice=None, video_note=None,
              reply_to_message=None, forward_origin=None):
    m = MagicMock()
    m.text = text
    m.caption = caption
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    m.from_user.first_name = "Вася"
    m.from_user.last_name = None
    m.reply_to_message = reply_to_message
    m.forward_origin = forward_origin
    m.video = video
    m.document = document
    m.voice = voice
    m.video_note = video_note
    m.reply = AsyncMock(return_value=SimpleNamespace(message_id=999))
    return m


def _voice_msg(message_id=77, file_id="voicefid01", duration=5,
               user_id=USER_ID, caption=None):
    return _make_msg(message_id=message_id, user_id=user_id, caption=caption,
                     voice=SimpleNamespace(file_id=file_id, duration=duration))


def _bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=500))
    bot.set_message_reaction = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Сброс DI youtube/voice_transcription + бот-префикс «бот»."""
    old = (yt._service, yt._media_transcriber, yt._media_db, yt._media_memory,
           yt._media_bot_id, yt._media_downloader,
           vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id)
    yt._cooldown._last.clear()
    monkeypatch.setattr(
        "services.command_prefix.command_prefix_tokens", lambda: ("бот",))

    async def _fake_fetch(bot, media, path):
        Path(path).write_bytes(b"audiodata")

    monkeypatch.setattr(vt, "_fetch_media_to_tmp", _fake_fetch)
    yield
    (yt._service, yt._media_transcriber, yt._media_db, yt._media_memory,
     yt._media_bot_id, yt._media_downloader,
     vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id) = old
    yt._cooldown._last.clear()


def _setup_voice(transcribe_result="привет мир", transcribe_error=None,
                 row=None):
    """Fake STT/DB/memory для voice_transcription (0i)."""
    svc = MagicMock()
    if transcribe_error is not None:
        svc.transcribe_voice = AsyncMock(side_effect=transcribe_error)
    else:
        svc.transcribe_voice = AsyncMock(return_value=transcribe_result)
    db = MagicMock()
    db.update_smart_message_text = AsyncMock(return_value=1)
    db.get_smart_message_by_tg_id = AsyncMock(return_value=row)
    memory = MagicMock()
    memory.memorize_facts = AsyncMock()
    aliases = MagicMock()
    aliases.resolve = MagicMock(
        side_effect=lambda uid, nickname=None, username=None:
        nickname or "Вася")
    vt._service = svc
    vt._db = db
    vt._memory = memory
    vt._aliases = aliases
    vt._bot_id = 999
    vt.set_media_aliases(aliases)
    return svc, db, memory


# ── (a) различимые определения инструментов ──────────────────────────────


class TestDefinitions:
    def test_summary_vs_transcript_distinguishable(self):
        summary = TOOL_SUMMARIZE_VIDEO["function"]["description"]
        transcribe = TOOL_TRANSCRIBE_VIDEO["function"]["description"]
        assert "SUMMARY" in summary
        assert "not the raw transcript" in summary
        assert "RAW verbatim" in transcribe
        assert "do NOT summarize" in transcribe
        assert "transcript" in transcribe.lower()
        # EN-описания (без кириллицы).
        for desc in (summary, transcribe):
            assert not any("\u0400" <= ch <= "\u04FF" for ch in desc)

    def test_transcribe_schema_shape(self):
        params = TOOL_TRANSCRIBE_VIDEO["function"]["parameters"]
        assert TOOL_TRANSCRIBE_VIDEO["function"]["name"] == "transcribe_video"
        assert params["required"] == []
        assert params["additionalProperties"] is False
        assert params["properties"]["url"]["type"] == "string"
        assert params["properties"]["source"]["enum"] == ["link", "reply"]

    def test_summarize_has_no_mode(self):
        params = TOOL_SUMMARIZE_VIDEO["function"]["parameters"]
        assert "mode" not in params["properties"]
        assert params["required"] == []
        assert params["properties"]["source"]["enum"] == ["link", "reply"]


# ── (d) канон = 10 ───────────────────────────────────────────────────────


class TestCanon:
    def test_ten_tools_transcribe_last(self):
        names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        assert len(names) == 10
        assert names[:9] == _FIRST_NINE
        assert names[-1] == "transcribe_video"
        assert TOOL_CALLING_TOOLS[-1] is TOOL_TRANSCRIBE_VIDEO

    def test_counter_comment_actualized(self):
        import services.tool_schemas as ts
        assert "R9 = **10**" in (ts.__doc__ or "")


# ── (h) флаг гейтит LLM-список, но не схему/канон ────────────────────────


class TestFlag:
    def test_flag_off_removes_from_active_tools(self, monkeypatch):
        monkeypatch.setattr(type(settings),
                            "MEDIA_TRANSCRIBE_TOOL_ENABLED", False)
        names = [t["function"]["name"]
                 for t in active_tools(True, image_generation_enabled=True)]
        assert "transcribe_video" not in names
        assert len(names) == 9                  # 8 базовых + generate_image
        assert len(TOOL_CALLING_TOOLS) == 10    # схема/канон безусловны

    def test_flag_on_includes(self, monkeypatch):
        monkeypatch.setattr(type(settings),
                            "MEDIA_TRANSCRIBE_TOOL_ENABLED", True)
        names = [t["function"]["name"]
                 for t in active_tools(True, image_generation_enabled=True)]
        assert names[-1] == "transcribe_video"


# ── (b)/(h) команда «транскрипт» по ГС/кружку ────────────────────────────


class TestVoiceCommand:
    @pytest.mark.asyncio
    async def test_force_repeat_voice_italic(self, clean_env):
        svc, db, memory = _setup_voice(row={"text": "[голосовое]"})
        yt.setup_youtube(MagicMock())
        bot = _bot()
        voice = _voice_msg()
        command = _make_msg(text="Бот, транскрипт", message_id=100,
                            reply_to_message=voice)

        result = await yt.youtube_handler(command, bot=bot)
        assert result is None                      # consumed (не UNHANDLED)
        svc.transcribe_voice.assert_awaited_once()
        voice.reply.assert_awaited_once()
        args, kwargs = voice.reply.call_args
        assert "🗣:" in args[0]
        assert "<i>привет мир</i>" in args[0]
        assert kwargs.get("parse_mode") == "HTML"
        await asyncio.sleep(0)                     # fire_and_forget
        memory.memorize_facts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_repeat_idempotent_memorize(self, clean_env):
        """Повтор по уже расшифрованной строке не дублирует GraphRAG-факт."""
        svc, db, memory = _setup_voice(row={"text": "привет мир"})
        yt.setup_youtube(MagicMock())
        bot = _bot()
        voice = _voice_msg()
        command = _make_msg(text="Бот, транскрипт", message_id=100,
                            reply_to_message=voice)

        await yt.youtube_handler(command, bot=bot)
        await asyncio.sleep(0)
        svc.transcribe_voice.assert_awaited_once()   # STT заново (свежий)
        memory.memorize_facts.assert_not_awaited()   # но факт не дублируется
        db.update_smart_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_repeat_video_note(self, clean_env):
        svc, db, memory = _setup_voice(row={"text": "[кружок]"})
        yt.setup_youtube(MagicMock())
        bot = _bot()
        note = _make_msg(message_id=78,
                         video_note=SimpleNamespace(file_id="n1", duration=3))
        command = _make_msg(text="Бот, транскрипт", message_id=101,
                            reply_to_message=note)

        await yt.youtube_handler(command, bot=bot)
        assert svc.transcribe_voice.await_args.args[1] == "mp4"
        assert note.reply.await_count == 1

    @pytest.mark.asyncio
    async def test_flag_off_neutral_answer(self, clean_env, monkeypatch):
        svc, db, memory = _setup_voice()
        yt.setup_youtube(MagicMock())
        monkeypatch.setattr(type(settings),
                            "MEDIA_TRANSCRIBE_TOOL_ENABLED", False)
        bot = _bot()
        voice = _voice_msg()
        command = _make_msg(text="Бот, транскрипт", message_id=100,
                            reply_to_message=voice)

        await yt.youtube_handler(command, bot=bot)
        svc.transcribe_voice.assert_not_awaited()
        sent = [c.args[1] for c in bot.send_message.await_args_list
                if len(c.args) > 1]
        assert any(str(text) in COMMAND_NO_TARGET_PHRASES for text in sent)

    @pytest.mark.asyncio
    async def test_caption_row_is_not_a_transcript(self, clean_env):
        """Medium-фикс: подпись медиа в text ≠ расшифровка → memorize вызван."""
        caption = "подпись к голосовому"
        svc, db, memory = _setup_voice(row={"text": caption})
        yt.setup_youtube(MagicMock())
        bot = _bot()
        voice = _voice_msg(caption=caption)
        command = _make_msg(text="Бот, транскрипт", message_id=100,
                            reply_to_message=voice)

        await yt.youtube_handler(command, bot=bot)
        await asyncio.sleep(0)
        memory.memorize_facts.assert_awaited_once()
        db.update_smart_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caption_video_note_placeholder_still_memorizes(self,
                                                                  clean_env):
        """`video_note` мапится observer'ом на `video` → плейсхолдер «[видео]»
        (не «[кружок]»); первый форс-повтор обязан вызвать memorize."""
        svc, db, memory = _setup_voice(row={"text": "[видео]"})
        yt.setup_youtube(MagicMock())
        bot = _bot()
        note = _make_msg(message_id=78,
                         video_note=SimpleNamespace(file_id="n1", duration=3))
        command = _make_msg(text="Бот, транскрипт", message_id=101,
                            reply_to_message=note)

        await yt.youtube_handler(command, bot=bot)
        await asyncio.sleep(0)
        memory.memorize_facts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caption_repeat_after_transcript_skips_memorize(self,
                                                                  clean_env):
        """Повтор после реальной расшифровки (≠ подписи) → memorize не дублит."""
        caption = "подпись к голосовому"
        svc, db, memory = _setup_voice(row={"text": "полный текст расшифровки"})
        yt.setup_youtube(MagicMock())
        bot = _bot()
        voice = _voice_msg(caption=caption)
        command = _make_msg(text="Бот, транскрипт", message_id=100,
                            reply_to_message=voice)

        await yt.youtube_handler(command, bot=bot)
        await asyncio.sleep(0)
        memory.memorize_facts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_path_still_memorizes_without_force(self, clean_env):
        """(f) Авто-путь 0i (force=False) не изменился: memorize как прежде."""
        svc, db, memory = _setup_voice(row={"text": "старый текст"})
        bot = _bot()
        voice = _voice_msg()
        ok = await vt.transcribe_media_message(
            voice, bot, reply_to_id=voice.message_id, force=False)
        assert ok is True
        await asyncio.sleep(0)
        memory.memorize_facts.assert_awaited_once()


class TestTargetSelection:
    @pytest.mark.asyncio
    async def test_own_voice_priority_over_reply(self, clean_env):
        """Единый хелпер: и классификация, и исполнение берут «своё > реплай»."""
        svc, db, memory = _setup_voice()
        yt.setup_youtube(MagicMock())
        bot = _bot()
        reply_voice = _voice_msg(message_id=70)
        own = _make_msg(message_id=71, caption="Бот, транскрипт",
                        voice=SimpleNamespace(file_id="own1", duration=4),
                        reply_to_message=reply_voice)

        await yt.youtube_handler(own, bot=bot)
        own.reply.assert_awaited_once()            # транскрибировано своё
        reply_voice.reply.assert_not_awaited()
        assert svc.transcribe_voice.await_args.args[1] == "ogg"

    @pytest.mark.asyncio
    async def test_reply_target_id_uses_send_message(self, clean_env):
        """Low-фикс: внешний reply_to_id покрыт — bot.send_message + reply."""
        svc, db, memory = _setup_voice(row={"text": "[голосовое]"})
        bot = _bot()
        voice = _voice_msg(message_id=77)

        ok = await vt.transcribe_media_message(
            voice, bot, reply_to_id=555, force=False)
        assert ok is True
        voice.reply.assert_not_awaited()
        args, kwargs = bot.send_message.await_args
        assert kwargs.get("reply_to_message_id") == 555
        assert kwargs.get("parse_mode") == "HTML"
        assert "<i>привет мир</i>" in args[1]


# ── (c) YouTube-URL + «транскрипт» → курсивный сырой транскрипт ──────────


class TestYoutubeCommand:
    @pytest.mark.asyncio
    async def test_youtube_transcript_italic_raw(self, clean_env):
        svc = MagicMock()
        svc.engine.fetch_transcript = AsyncMock(
            return_value="сырой транскрипт субтитров")
        svc.summarize_cascade = AsyncMock(return_value="ВЫЖИМКА")
        yt.setup_youtube(svc)
        yt.setup_youtube_video_media(MagicMock(), None, None, None, bot_id=999)
        bot = _bot()
        msg = _make_msg(text=f"Бот, транскрипт {YT_URL}", message_id=5)

        await yt.youtube_handler(msg, bot=bot)
        sent = [str(c.args[1]) for c in bot.send_message.await_args_list
                if len(c.args) > 1]
        assert any("<i>сырой транскрипт субтитров</i>" in text for text in sent)
        svc.summarize_cascade.assert_not_awaited()


# ── (e) dispatch путей `transcribe_video` ────────────────────────────────


class TestDispatch:
    @pytest.mark.asyncio
    async def test_youtube_link_uses_subtitles(self):
        video = MagicMock()
        video.engine.fetch_transcript = AsyncMock(return_value="субтитры raw")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     video=video))
        out = await router.dispatch("transcribe_video", {"url": YT_URL},
                                    ToolContext(CHAT_ID, "q"))
        assert out == "субтитры raw"
        video.engine.fetch_transcript.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_direct_link_download_stt(self, tmp_path):
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"x")
        dl = MagicMock()
        dl.download = AsyncMock(return_value=path)
        tr = MagicMock()
        tr.transcribe_voice = AsyncMock(return_value="дословный текст")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     downloader=dl, transcriber=tr))
        out = await router.dispatch("transcribe_video", {"url": DIRECT_URL},
                                    ToolContext(CHAT_ID, "q"))
        assert out == "дословный текст"
        tr.transcribe_voice.assert_awaited_once()
        assert not path.exists()                 # temp удалён в finally

    @pytest.mark.asyncio
    async def test_native_video_stt(self, tmp_path, monkeypatch):
        path = tmp_path / "n.mp4"
        path.write_bytes(b"x")
        monkeypatch.setattr(native_media, "download_to_tmp",
                            AsyncMock(return_value=path))
        tr = MagicMock()
        tr.transcribe_voice = AsyncMock(return_value="нативный raw")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     transcriber=tr))
        native = native_media.NativeMedia(
            source=MagicMock(), media=SimpleNamespace(file_id="fid"),
            kind="video")
        ctx = ToolContext(CHAT_ID, "q", bot=MagicMock(), native_media=native)
        out = await router.dispatch("transcribe_video", {"source": "reply"}, ctx)
        assert out == "нативный raw"
        assert tr.transcribe_voice.await_args.args[1] == "mp4"

    @pytest.mark.asyncio
    async def test_native_voice_stt_ogg(self, tmp_path, monkeypatch):
        path = tmp_path / "n.ogg"
        path.write_bytes(b"x")
        monkeypatch.setattr(native_media, "download_to_tmp",
                            AsyncMock(return_value=path))
        tr = MagicMock()
        tr.transcribe_voice = AsyncMock(return_value="голосовой raw")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     transcriber=tr))
        native = native_media.NativeMedia(
            source=MagicMock(), media=SimpleNamespace(file_id="fid"),
            kind="voice")
        ctx = ToolContext(CHAT_ID, "q", bot=MagicMock(), native_media=native)
        out = await router.dispatch("transcribe_video", {}, ctx)
        assert out == "голосовой raw"
        assert tr.transcribe_voice.await_args.args[1] == "ogg"


# ── (g) ошибки — строки, не исключения ───────────────────────────────────


class TestErrors:
    @pytest.mark.asyncio
    async def test_no_source_string(self):
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        out = await router.dispatch("transcribe_video", {},
                                    ToolContext(CHAT_ID, "q"))
        assert out.startswith("ОШИБКА transcribe_video")
        assert "нет источника" in out

    @pytest.mark.asyncio
    async def test_transcriber_unavailable_string(self, tmp_path, monkeypatch):
        path = tmp_path / "n.mp4"
        path.write_bytes(b"x")
        monkeypatch.setattr(native_media, "download_to_tmp",
                            AsyncMock(return_value=path))
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        native = native_media.NativeMedia(
            source=MagicMock(), media=SimpleNamespace(file_id="fid"),
            kind="video")
        ctx = ToolContext(CHAT_ID, "q", bot=MagicMock(), native_media=native)
        out = await router.dispatch("transcribe_video", {}, ctx)
        assert out == "ОШИБКА transcribe_video: RuntimeError"

    @pytest.mark.asyncio
    async def test_summarize_rejects_voice(self):
        video = MagicMock()
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     video=video))
        native = native_media.NativeMedia(
            source=MagicMock(), media=SimpleNamespace(file_id="fid"),
            kind="voice")
        ctx = ToolContext(CHAT_ID, "q", native_media=native)
        out = await router.dispatch("summarize_video", {"source": "reply"}, ctx)
        assert out.startswith("ОШИБКА summarize_video")


# ── (i) R17 — логи без URL/file_id ───────────────────────────────────────


class TestR17:
    @pytest.mark.asyncio
    async def test_link_logs_no_url(self, tmp_path, caplog):
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"x")
        dl = MagicMock()
        dl.download = AsyncMock(return_value=path)
        tr = MagicMock()
        tr.transcribe_voice = AsyncMock(return_value="text")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     downloader=dl, transcriber=tr))
        secret = "https://example.com/PRIVATE_TOKEN_42.mp4"
        with caplog.at_level(logging.DEBUG, logger="services.tool_router"):
            await router.dispatch("transcribe_video", {"url": secret},
                                  ToolContext(CHAT_ID, "q"))
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert secret not in blob
        assert "PRIVATE_TOKEN_42" not in blob
        assert "source=link" in blob and "out_chars" in blob

    @pytest.mark.asyncio
    async def test_native_logs_no_file_id(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / "n.mp4"
        path.write_bytes(b"x")
        monkeypatch.setattr(native_media, "download_to_tmp",
                            AsyncMock(return_value=path))
        tr = MagicMock()
        tr.transcribe_voice = AsyncMock(return_value="text")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     transcriber=tr))
        native = native_media.NativeMedia(
            source=MagicMock(), media=SimpleNamespace(file_id="SECRETFID777"),
            kind="video")
        ctx = ToolContext(CHAT_ID, "q", bot=MagicMock(), native_media=native)
        with caplog.at_level(logging.DEBUG, logger="services.tool_router"):
            await router.dispatch("transcribe_video", {}, ctx)
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert "SECRETFID777" not in blob
        assert "kind=video" in blob
