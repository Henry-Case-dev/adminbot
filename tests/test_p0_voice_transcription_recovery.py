"""P0 VOICE-TRANSCRIPTION-RECOVERY-01 (18.11.2026).

Проверяет наблюдаемый контракт фикса:
  * A — один транспорт voice/video_note: local 400 «wrong file_id or the file
    is temporarily unavailable» НЕ выдаётся за invalid_file_id (файл мог не
    записаться на диск), одна попытка local → typed ошибка → облачный
    fallback при разрешённом MEDIA_DOWNLOAD_CLOUD_FALLBACK; постоянный
    invalid_file_id терминален;
  * B — отказ скачивания даёт терминальный failed с безопасной причиной
    `download_<stage>_<class>`, НЕ pending; прежний успешный текст и
    revision сохраняются; ответа в Telegram нет;
  * C — протухший pending в `_derive_status` становится unavailable с
    причиной и не блокирует честный статус; поздний ready выигрывает гонку;
  * D — фактический режим Bot API определяется сессией/инфраструктурным
    TELEGRAM_LOCAL, mismatch виден явно; hot-флаг модуля endpoint не меняет;
  * Replay сохранённых voice/video_note без Update: тот же транспорт → STT →
    durable source-ref; без reply/send, идемпотентно (revision не растёт,
    память не дублируется), Writer видит текст.

TEST-LIFECYCLE: CONTRACT owner=VOICE-TRANSCRIPTION-RECOVERY-01 (A/B/C/D/replay);
TEST-LIFECYCLE: REGRESSION owner=VMQ-V (source-ref/version), R17 (ids в логах).
"""
import asyncio
import logging
import os
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from handlers import voice_transcription as vt
from services import local_bot_api
from services import media_download as md
from services import voice_transcripts as vts
from services.database import DatabaseService
from SmartModule.service import EmptyTranscript, TranscriptionUnavailable

CHAT = -100777000111
USER = 111
BOT_ID = 8802473181


# ─────────────────────────── общие двойники ────────────────────────────────

class _Session:
    def __init__(self, is_local: bool):
        self.api = types.SimpleNamespace(is_local=is_local)


class _Bot:
    """Двойник бота: фактическая сессия, запись в destination, никаких reply."""

    def __init__(self, *, local: bool = False, data: bytes = b"audio-bytes",
                 file_path: str = "voice/file.ogg"):
        self.session = _Session(local)
        self.id = BOT_ID
        self.token = f"{BOT_ID}:recovery-secret"
        self.data = data
        self.file_path = file_path
        self.get_file_calls = 0
        self.download_file_calls = 0
        self.get_file_exc: BaseException | None = None
        self.sent_messages: list = []

    async def get_file(self, file_id):
        self.get_file_calls += 1
        if self.get_file_exc is not None:
            raise self.get_file_exc
        return types.SimpleNamespace(file_path=self.file_path)

    async def download_file(self, file_path, destination=None, timeout=30):
        self.download_file_calls += 1
        if isinstance(destination, str):
            Path(destination).write_bytes(self.data)
        else:
            destination.write(self.data)

    async def send_chat_action(self, *args, **kwargs):
        return None

    async def send_message(self, *args, **kwargs):
        self.sent_messages.append((args, kwargs))


class _BadRequest(Exception):
    """Постоянный Telegram 400 (текст как у локального сервера 18.11.2026)."""


class _Stt:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple] = []

    async def transcribe_voice(self, file_path, audio_format):
        self.calls.append((str(file_path), audio_format))
        result = self.results.pop(0) if self.results else "текст"
        if isinstance(result, BaseException):
            raise result
        return result


def _msg(*, message_id=700, voice=True, duration=10, file_id="f1"):
    msg = MagicMock()
    msg.text = None
    msg.caption = None
    msg.forward_origin = None
    msg.message_id = message_id
    msg.chat = types.SimpleNamespace(id=CHAT)
    msg.from_user = types.SimpleNamespace(
        id=USER, username="vasya", first_name="Вася", last_name=None)
    msg.reply = AsyncMock()
    msg.voice = (MagicMock(duration=duration, file_id=file_id)
                 if voice else None)
    msg.video_note = None
    return msg


def _query(text="что в голосовых?", message_id=10000):
    return types.SimpleNamespace(
        message_id=message_id, text=text, quote=None,
        reply_to_message=None, caption=None,
        from_user=types.SimpleNamespace(id=USER))


@pytest_asyncio.fixture
async def db():
    service = DatabaseService(":memory:")
    await service.initialize()
    try:
        yield service
    finally:
        await service.close()


@pytest_asyncio.fixture
async def wire(db, monkeypatch):
    """DI хендлера: fake STT + реальная БД + fake memory; env cloud-off."""
    old = (vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id)
    service = _Stt("голос")
    aliases = MagicMock()
    aliases.resolve = MagicMock(side_effect=lambda uid, nickname=None,
                                username=None: nickname or "Вася")
    memory = MagicMock()
    memory.memorize_facts = AsyncMock()
    vt.setup_voice_transcription(service, db, aliases, memory, bot_id=BOT_ID)
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "0")
    monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)
    yield service, memory
    vt._service, vt._db, vt._aliases, vt._memory, vt._bot_id = old


@pytest.fixture
def tmp_track(monkeypatch, tmp_path):
    created = []

    def _mkstemp(prefix="vt_", suffix=""):
        path = os.path.join(str(tmp_path), f"{prefix}{len(created)}{suffix}")
        with open(path, "wb") as fh:
            fh.write(b"")
        created.append(path)
        return os.open(path, os.O_RDONLY), path

    monkeypatch.setattr(vt.tempfile, "mkstemp", _mkstemp)
    return created


async def _seed_voice(db, *, message_id, ts=None, media_type="voice",
                      text=None, status=None, reason="",
                      updated_at=None):
    await db.save_smart_message(
        user_id=USER, chat_id=CHAT, text=text, reply_to_id=None,
        timestamp=int(ts if ts is not None else time.time()),
        media_type=media_type, author_name="Вася", message_id=message_id)
    if status is not None:
        await db.set_smart_message_transcript(
            CHAT, message_id, status=status, text=text, reason=reason)
    if updated_at is not None:
        await db.db.execute(
            "UPDATE smart_messages SET transcript_updated_at = ? "
            "WHERE chat_id = ? AND tg_message_id = ?",
            (int(updated_at), CHAT, int(message_id)))
        await db.db.commit()


async def _row(db, message_id):
    return await db.get_smart_message_by_tg_id(CHAT, message_id)


# ─────────────── B. Отказ скачивания: терминальный статус ──────────────────

@pytest.mark.asyncio
async def test_handler_download_failure_terminal_no_pending_no_reply(
        wire, db, tmp_track, monkeypatch):
    """Локальный 400 + облако off → failed с классом, без pending/ответа."""
    await _seed_voice(db, message_id=700)
    statuses: list[str] = []
    real = db.set_smart_message_transcript

    async def _record(*args, **kwargs):
        statuses.append(str(kwargs.get("status")))
        return await real(*args, **kwargs)

    monkeypatch.setattr(db, "set_smart_message_transcript", _record)
    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: wrong file_id or the file is temporarily unavailable")
    msg = _msg(message_id=700)

    result = await vt.voice_transcription_handler(msg, bot=bot)

    assert result is vt.UNHANDLED
    msg.reply.assert_not_called()
    assert bot.get_file_calls == 1                     # без тройного повтора
    assert statuses == ["failed"]                     # pending не выставлялся
    row = await _row(db, 700)
    assert row["transcript_status"] == "failed"
    assert row["transcript_reason"] == "download_get_file_local_read_failed"
    assert row["transcript_revision"] == 0
    assert "заглушка" not in str(row["text"] or "")
    assert len(tmp_track) == 1
    assert not os.path.exists(tmp_track[0])            # temp убран


@pytest.mark.asyncio
async def test_handler_download_failure_keeps_previous_text(
        wire, db, tmp_track):
    """Отказ скачивания при повторе не стирает уже полученный текст."""
    await _seed_voice(db, message_id=701, status="ready",
                      text="прежняя удачная расшифровка")
    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: wrong file_id or the file is temporarily unavailable")
    msg = _msg(message_id=701)

    result = await vt.voice_transcription_handler(msg, bot=bot)

    assert result is vt.UNHANDLED
    msg.reply.assert_not_called()
    row = await _row(db, 701)
    assert row["text"] == "прежняя удачная расшифровка"
    assert row["transcript_status"] == "failed"
    assert row["transcript_revision"] == 1


@pytest.mark.asyncio
async def test_handler_local_400_cloud_200_recovers(
        wire, db, tmp_track, monkeypatch):
    """Прод-сценарий 18.11.2026: local 400 → cloud 200 → ready + один ответ."""
    await _seed_voice(db, message_id=702)
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    calls = []

    async def _cloud(token, file_id, rel_path, *, timeout, max_bytes):
        calls.append({"file_id": file_id, "rel": rel_path})
        return b"cloud-voice-bytes"

    monkeypatch.setattr(md, "_default_cloud_fetch", _cloud)
    wire[0].results = ["привет из облака"]
    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: wrong file_id or the file is temporarily unavailable")
    msg = _msg(message_id=702)

    result = await vt.voice_transcription_handler(msg, bot=bot)

    assert result is vt.UNHANDLED
    assert bot.get_file_calls == 1
    assert calls and calls[0]["file_id"] == "f1"
    msg.reply.assert_called_once()
    assert "привет из облака" in msg.reply.call_args.args[0]
    row = await _row(db, 702)
    assert row["transcript_status"] == "ready"
    assert row["text"] == "привет из облака"
    assert row["transcript_revision"] == 1


# ─────────────── C. Протухший pending и гонка завершения ───────────────────

@pytest.mark.asyncio
async def test_stale_pending_becomes_unavailable_with_reason(wire, db):
    now = int(time.time())
    await _seed_voice(db, message_id=710, ts=now - 7200, status="pending",
                      updated_at=now - 7200)
    bundle = await vts.resolve_voice_bundle(
        db, chat_id=CHAT, message=_query(), query="что в голосовых?")
    item = bundle.items[0]
    assert item.status == vts.TRANSCRIPT_UNAVAILABLE
    assert item.reason == "stale_pending"
    assert item.in_flight is False
    block = vts.render_voice_block(bundle)
    assert "ещё идёт" not in block
    assert "не завершилось" in block


@pytest.mark.asyncio
async def test_fresh_pending_stays_pending(wire, db):
    await _seed_voice(db, message_id=711, status="pending")
    bundle = await vts.resolve_voice_bundle(
        db, chat_id=CHAT, message=_query(), query="что в голосовых?")
    assert bundle.items[0].status == vts.TRANSCRIPT_PENDING
    assert bundle.items[0].in_flight is True


@pytest.mark.asyncio
async def test_late_ready_wins_stale_snapshot(wire, db):
    now = int(time.time())
    await _seed_voice(db, message_id=712, ts=now - 7200, status="pending",
                      updated_at=now - 7200)
    bundle = await vts.resolve_voice_bundle(
        db, chat_id=CHAT, message=_query(), query="что в голосовых?")
    assert bundle.items[0].status == vts.TRANSCRIPT_UNAVAILABLE
    # Гонка: операция завершилась после снимка.
    await db.set_smart_message_transcript(
        CHAT, 712, status="ready", text="поздняя речь")
    fresh = await vts.refresh_voice_bundle(db, bundle)
    assert fresh.items[0].status == vts.TRANSCRIPT_READY
    assert fresh.items[0].text == "поздняя речь"


# ─────────────────────── D. Режим Bot API / диагностика ────────────────────

def test_bot_api_mode_mismatch_is_explicit(monkeypatch, caplog):
    monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)
    local_bot = _Bot(local=True)
    snap = local_bot_api.bot_api_mode(local_bot)
    assert snap == {"mode": "local", "session": True, "infra": False,
                    "mismatch": True, "reason": "session_vs_infra"}
    with caplog.at_level(logging.WARNING):
        local_bot_api.log_bot_api_mode(local_bot)
    assert any("mode mismatch" in r.getMessage() for r in caplog.records)

    monkeypatch.setenv("TELEGRAM_LOCAL", "1")
    cloud_bot = _Bot(local=False)
    assert local_bot_api.bot_api_mode(cloud_bot)["mismatch"] is True
    assert local_bot_api.bot_api_mode(local_bot)["mismatch"] is False


def test_session_bool_is_required_for_mode(monkeypatch):
    """MagicMock/строка не считаются режимом: берётся инфраструктурный env."""
    monkeypatch.delenv("TELEGRAM_LOCAL", raising=False)
    assert local_bot_api.session_local_mode(MagicMock()) is None
    assert local_bot_api.bot_api_mode(MagicMock())["mode"] == "cloud"
    monkeypatch.setenv("TELEGRAM_LOCAL", "1")
    assert local_bot_api.bot_api_mode(MagicMock())["mode"] == "local"


# ───────────────────── Replay сохранённых без Update ───────────────────────

@pytest.mark.asyncio
async def test_replay_ready_idempotent_no_reply(wire, db):
    await _seed_voice(db, message_id=235)
    service, memory = wire
    service.results = ["речь первого голосового",
                       "речь первого голосового"]
    bot = _Bot(local=False, data=b"voice-bytes")

    first = await vt.replay_saved_media(
        bot, chat_id=CHAT, message_id=235, file_id="AgAD-first-full-id",
        media_type="voice", service=service, db=db, memory=memory)
    await asyncio.sleep(0.02)

    assert first["status"] == "ready"
    assert first["source_ref"] == "tg:235"
    assert first["revision"] == 1
    assert first["chars"] > 0
    assert first["asr"] == "ok"
    assert first["persisted"] is True
    assert first["file_id_prefix"] == "AgAD-f"       # только префикс
    row = await _row(db, 235)
    assert row["text"] == "речь первого голосового"
    assert row["transcript_status"] == "ready"
    assert row["transcript_revision"] == 1
    assert memory.memorize_facts.await_count == 1
    assert bot.sent_messages == []

    # Повторный replay: та же версия, без второго факта и без новой строки.
    second = await vt.replay_saved_media(
        bot, chat_id=CHAT, message_id=235, file_id="AgAD-first-full-id",
        media_type="voice", service=service, db=db, memory=memory)
    await asyncio.sleep(0.02)
    assert second["status"] == "ready"
    assert second["revision"] == 1
    assert memory.memorize_facts.await_count == 1
    row = await _row(db, 235)
    assert row["text"] == "речь первого голосового"
    assert row["transcript_revision"] == 1
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
        (CHAT,))
    assert (await cursor.fetchone())["n"] == 1
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_replay_download_failure_terminal_preserves_text(wire, db):
    await _seed_voice(db, message_id=236, status="ready",
                      text="прежний успешный текст")
    service, memory = wire
    service.results = ["не должно вызываться"]
    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: wrong file_id or the file is temporarily unavailable")
    statuses: list[str] = []
    real = db.set_smart_message_transcript

    async def _record(*args, **kwargs):
        statuses.append(str(kwargs.get("status")))
        return await real(*args, **kwargs)

    db.set_smart_message_transcript = _record
    report = await vt.replay_saved_media(
        bot, chat_id=CHAT, message_id=236, file_id="AgAD-broken",
        media_type="voice", service=service, db=db, memory=memory)

    assert report["status"] == "failed"
    assert report["reason"] == "download_get_file_local_read_failed"
    assert report["stage"] == md.STAGE_GET_FILE
    assert report["persisted"] is True
    assert statuses == ["failed"]                  # pending не выставлялся
    row = await _row(db, 236)
    assert row["text"] == "прежний успешный текст"
    assert row["transcript_status"] == "failed"
    assert row["transcript_revision"] == 1
    assert memory.memorize_facts.await_count == 0
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_replay_two_voices_and_video_note_sequence(wire, db):
    """2 voice + 1 video_note последовательно; Writer видит все три."""
    now = int(time.time())
    await _seed_voice(db, message_id=235, ts=now - 60)
    await _seed_voice(db, message_id=1222542, ts=now - 50)
    # Сохранённый кружок застрял в pending (как 12 строк инцидента).
    await _seed_voice(db, message_id=9001, ts=now - 40, media_type="video",
                      status="pending", updated_at=now - 7200)
    service, memory = wire
    service.results = ["первое голосовое", "второе голосовое",
                       "речь кружочка",
                       "первое голосовое", "второе голосовое",
                       "речь кружочка"]
    bot = _Bot(local=False, data=b"media-bytes")
    items = [
        (235, "AgAD-235", "voice"),
        (1222542, "AgAD-1222542", "voice"),
        (9001, "AgAD-9001", "video_note"),
    ]
    for message_id, file_id, kind in items:
        report = await vt.replay_saved_media(
            bot, chat_id=CHAT, message_id=message_id, file_id=file_id,
            media_type=kind, service=service, db=db, memory=memory)
        assert report["status"] == "ready", report
        assert report["revision"] == 1
    await asyncio.sleep(0.05)

    assert len(service.calls) == 3
    assert [c[1] for c in service.calls] == ["ogg", "ogg", "mp4"]
    assert memory.memorize_facts.await_count == 3
    assert bot.sent_messages == []

    bundle = await vts.resolve_voice_bundle(
        db, chat_id=CHAT, message=_query("что в голосовых?",
                                         message_id=2_000_000),
        query="что в голосовых?")
    assert bundle.summary_status() == vts.TRANSCRIPT_READY
    assert bundle.refs == ("tg:235", "tg:1222542", "tg:9001")
    block = vts.render_voice_block(bundle)
    for text in ("первое голосовое", "второе голосовое", "речь кружочка"):
        assert text in block

    # Повторная последовательность не создаёт дублей/новых версий.
    for message_id, file_id, kind in items:
        report = await vt.replay_saved_media(
            bot, chat_id=CHAT, message_id=message_id, file_id=file_id,
            media_type=kind, service=service, db=db, memory=memory)
        assert report["status"] == "ready"
        assert report["revision"] == 1
    await asyncio.sleep(0.02)
    assert memory.memorize_facts.await_count == 3
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
        (CHAT,))
    assert (await cursor.fetchone())["n"] == 3


@pytest.mark.asyncio
async def test_replay_missing_source_writes_nothing(wire, db):
    service, memory = wire
    bot = _Bot(local=False)
    report = await vt.replay_saved_media(
        bot, chat_id=CHAT, message_id=999999, file_id="AgAD",
        media_type="voice", service=service, db=db, memory=memory)
    assert report["status"] == "unavailable"
    assert report["reason"] == "source_missing"
    assert report["persisted"] is False
    assert bot.get_file_calls == 0
    assert memory.memorize_facts.await_count == 0
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
        (CHAT,))
    assert (await cursor.fetchone())["n"] == 0


@pytest.mark.asyncio
async def test_replay_stt_failure_terminal(wire, db):
    await _seed_voice(db, message_id=237)
    service, memory = wire
    service.results = [TranscriptionUnavailable("all failed")]
    bot = _Bot(local=False, data=b"voice-bytes")
    report = await vt.replay_saved_media(
        bot, chat_id=CHAT, message_id=237, file_id="AgAD-237",
        service=service, db=db, memory=memory)
    assert report["status"] == "failed"
    assert report["reason"] == "stt_failed"
    row = await _row(db, 237)
    assert row["transcript_status"] == "failed"
    assert memory.memorize_facts.await_count == 0
    assert bot.sent_messages == []


@pytest.mark.asyncio
async def test_replay_empty_transcript_honest(wire, db):
    await _seed_voice(db, message_id=238)
    service, memory = wire
    service.results = [EmptyTranscript("empty")]
    bot = _Bot(local=False, data=b"voice-bytes")
    report = await vt.replay_saved_media(
        bot, chat_id=CHAT, message_id=238, file_id="AgAD-238",
        service=service, db=db, memory=memory)
    assert report["status"] == "unavailable"
    assert report["reason"] == "empty_transcript"
    row = await _row(db, 238)
    assert row["transcript_status"] == "unavailable"
    assert bot.sent_messages == []
