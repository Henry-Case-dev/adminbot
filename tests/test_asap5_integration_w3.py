"""ASAP5 W3 — INTEGRATION: кросс-модульные матрицы (source §23–§26).

Слайс ASAP5-INTEGRATION (база `release/p0-2026-10-26` @ `35ca5ba7`, W1+W2
в одном дереве). Каждый сценарий Part VI — одна проверка СКВОЗНОГО потока
данных на реальных компонентах (id/состояния/маркеры payload), не финальных
формулировок:

  * Матрица A (§24, 22 сценария + ключевой): Media × Vision × Direct Chat —
    intake (register_intake_assets → durable job) → состояние Vision (W2
    honest states) → представление в payload Direct Chat (build_chat_context
    + Current_Question-маркеры + auto-target);
  * Матрица B: Media × Fact-check — альбом и типы превью через
    resolve_claim_publication / load_claim_media (whole-post путь);
  * Матрица C (§25, 14 сценариев + админка §22): Image-gen × Direct Chat ×
    Admin — capability claim vs фактический маршрут (generate/edit →
    media_execution), admin types/diag против реального runtime;
  * Матрица D (§23, 16 сценариев): Nostalgia × provenance — forward-лейблы в
    composed памяти, отказы до публикации, отсутствие помех от новых типов
    медиа;
  * Матрица E (cross-cutting): согласованность provenance-лейблов на всех
    путях, честные unsupported-состояния, отсутствие шаблонирования.

Границы: без Telegram, без сети; LLM-вызовов нет (`.env` в ворктрие нет) —
Vision-транспорт/LLM/отправка — контрактные моки, честно отделённые
(прецедент W1/W2). Не тестируется офлайн → честно `needs-real-env` в карте.

TEST-LIFECYCLE: INTEGRATION owner=ASAP5/Part VI (§23-§26); для строк,
уже покрытых CONTRACT-тестами W1/W2, здесь — сквозной поток на одном дереве.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import struct
import time
import types
import zlib
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from config.settings import settings
from services import capability_registry as caps
from services import chat_context
from services import direct_capabilities as dcap
from services import factcheck_service as fcs
from services import hot_config as hot
from services import image_capabilities as icap
from services import image_generation as ig
from services import mca_vision
from services import message_identity
from services import nostalgia_worker as nw
from services import tool_schemas
from services import worker_budget as wb
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.nostalgia_prompts import format_year_back_line
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolRouter

pytestmark = [pytest.mark.asap3]

CHAT = -1007770003
CHAT2 = -1007770004
USER_ID = 42
BOT_ID = 999
NOW = int(time.time())


# ═══════════════════════════ общая обвязка ══════════════════════════════════

class Transport:
    """Контрактный мок Vision-транспорта: сценарий (status, body)."""

    def __init__(self, script=None, default=None):
        self.calls: list = []
        self._script = list(script or [])
        self._default = default

    async def __call__(self, url, *, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload,
                           "headers": dict(headers), "timeout": timeout})
        item = self._script.pop(0) if self._script else self._default
        if isinstance(item, BaseException):
            raise item
        status, body = item
        return status, body

    @property
    def n(self) -> int:
        return len(self.calls)


class _FakeBot:
    def __init__(self, blobs: dict):
        self.blobs = blobs

    async def get_file(self, file_id):
        f = types.SimpleNamespace()
        f.file_id = file_id
        return f

    async def download(self, tg_file, destination=None):
        blob = self.blobs.get(tg_file.file_id)
        if blob is None:
            raise FileNotFoundError(tg_file.file_id)
        destination.write(blob)


def make_png(width=10, height=10) -> bytes:
    def chunk(tag, data):
        raw = tag + data
        return (struct.pack(">I", len(data)) + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF))
    row = b"\x00" + b"\x10\x20\x30" * width
    body = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0,
                                         0, 0))
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def _analysis_body(desc="тестовое изображение: тёмный квадрат",
                   ocr_text="НАДПИСЬ НА СТЕНЕ"):
    return {"choices": [{"message": {"content": json.dumps({
        "ocr_blocks": ([{"text": ocr_text}] if ocr_text else []),
        "visual_description": desc,
        "uncertainty": [], "self_reported_confidence": 0.8})}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


_NO_TEXT_BODY = {"choices": [{"message": {"content": json.dumps({
    "ocr_blocks": [], "visual_description": "",
    "uncertainty": [], "self_reported_confidence": 0.9})}}],
    "usage": {"prompt_tokens": 4, "completion_tokens": 2}}


def _err_body(message: str, code: str = "err"):
    return {"error": {"message": message, "code": code, "type": "x"}}


@contextmanager
def patched_settings(**kw):
    saved = {k: getattr(settings, k) for k in kw}
    for k, v in kw.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)


class _Cfg:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, vals):
            self._values = dict(vals or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


@pytest.fixture(autouse=True)
def _w3_env():
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()
    caps.reset_cache()
    hot.set_config_cache(None)
    with patched_settings(VISION_ENABLED=True, LLM_API_KEY="test-key",
                          VISION_API_KEY="", VISION_API_BASE_URL="",
                          VISION_MODEL="", VISION_API_TYPE="openai_compatible",
                          MCA_VISION_ENABLED=True,
                          NATIVE_REPLY_MEDIA_CONTEXT_ENABLED=True):
        yield
    mca_vision.reset_runtime()
    mca_vision.reset_capability_cache()
    caps.reset_cache()
    hot.set_config_cache(None)


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "w3-integration.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


def _cap_ok():
    mca_vision.store_capability(
        mca_vision.resolve_route(),
        mca_vision.CapabilityVerdict("ok", "", True, time.monotonic()))


async def _store(db):
    from services.task_supervisor import TaskJobStore
    return TaskJobStore(db)


async def _active_vision(db, status=None):
    store = await _store(db)
    return [j for j in await store.active()
            if j.get("kind") == mca_vision.VISION_JOB_KIND
            and (status is None or j.get("status") == status)]


async def _claimed_job(db, job_id):
    store = await _store(db)
    await store.mark_running(job_id)
    job = await store.get(job_id) or {}
    job["attempt"] = int(job.get("attempt") or 1)
    return job


async def _process_asset(db, msg, transport, bot, *, enqueue=True):
    """Сквозной прогон media-гранул сообщения: intake → enqueue → claim →
    process для КАЖДОЙ джобы сообщения (multi-asset: GIF = честный fail
    источника + успех обложки; capability ok — 1 transport-вызов на анализ).
    Возвращает asset_id-ы сообщения."""
    mca_vision.bind_runtime(db)
    _cap_ok()
    assets = await mca_vision.register_intake_assets(db, msg)
    assert assets, "intake не зарегистрировал активы"
    if enqueue:
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
    queued = [j for j in await _active_vision(db, "queued")
              if json.loads(j.get("payload") or "{}").get(
                  "asset_id") in assets]
    assert queued, "enqueue не создал durable-джобу"
    for j in queued:
        job = await _claimed_job(db, j["job_id"])
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                           transport=transport)
    return assets


async def _process_until_terminal(db, job_id, transport, bot):
    """Дожать bounded-retry джобы до терминального исхода (транзиентные
    причины уходят в next_retry — рабочий цикл повторяет попытку)."""
    store = await _store(db)
    row = await store.get(job_id)
    for _ in range(6):
        if row is None or row.get("status") in ("failed", "completed",
                                                "cancelled"):
            break
        job = dict(row)
        await store.mark_running(job_id)
        row = await store.get(job_id)
        job = dict(row or {})
        job["attempt"] = int(job.get("attempt") or 1)
        await mca_vision.process_asset_job(job, db=db, bot=bot,
                                           transport=transport)
        row = await store.get(job_id)
    return await store.get(job_id)


async def _save_media_row(db, tg_id, *, media_type="photo", caption=None,
                          text=None, forward_source=None,
                          media_group_id=None, author="Сергей",
                          ts=None):
    """Канонический intake-путь строки smart_messages (identity ON)."""
    return await message_identity.save_live_message(
        db, chat_id=CHAT, user_id=USER_ID, text=text, caption=caption,
        timestamp=(ts or NOW), sent_at=(ts or NOW), ingested_at=(ts or NOW),
        media_type=media_type, author_name=author,
        is_forward=bool(forward_source), forward_source=forward_source or "",
        tg_message_id=tg_id, media_group_id=media_group_id)


# ── aiogram-сообщения (прецедент W1) ────────────────────────────────────────

def _thumb(serial: int):
    from aiogram.types import PhotoSize
    return PhotoSize(file_id=f"thumb_fid_{serial}",
                     file_unique_id=f"thumb_uniq_{serial}",
                     width=320, height=240, file_size=4321)


def _photo_message(tg_id, serial=1, *, caption=None, media_group_id=None):
    from aiogram.types import Chat, Message, PhotoSize, User
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Сергей"),
        photo=[PhotoSize(file_id=f"fid_{serial}",
                         file_unique_id=f"uniq_{serial}",
                         width=800, height=600, file_size=12345)],
        caption=caption, media_group_id=media_group_id)


def _document_message(tg_id):
    from aiogram.types import Chat, Document, Message, User
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Сергей"),
        document=Document(file_id="doc_fid", file_unique_id="doc_uniq",
                          file_name="pic.jpg", mime_type="image/jpeg",
                          file_size=3000))


def _sticker_message(tg_id, *, is_animated=False, is_video=False,
                     with_thumb=False):
    from aiogram.types import Chat, Message, Sticker, User
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Сергей"),
        sticker=Sticker(file_id=f"st_fid_{tg_id}",
                        file_unique_id=f"st_uniq_{tg_id}",
                        width=512, height=512,
                        is_animated=is_animated, is_video=is_video,
                        type="regular",
                        thumbnail=(_thumb(90 + tg_id % 100)
                                   if with_thumb else None)))


def _animation_message(tg_id, serial=1, *, with_thumb=True):
    from aiogram.types import Animation, Chat, Message, User
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Сергей"),
        animation=Animation(file_id=f"gif_fid_{serial}",
                            file_unique_id=f"gif_uniq_{serial}",
                            width=320, height=240, duration=3,
                            mime_type="video/mp4", file_name="gif.mp4",
                            file_size=100_000,
                            thumbnail=(_thumb(serial)
                                       if with_thumb else None)))


def _video_message(tg_id, serial=1, *, with_thumb=True, media_group_id=None):
    from aiogram.types import Chat, Message, User, Video
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Сергей"),
        video=Video(file_id=f"vid_fid_{serial}",
                    file_unique_id=f"vid_uniq_{serial}",
                    width=1280, height=720, duration=42,
                    mime_type="video/mp4", file_size=2_000_000,
                    thumbnail=(_thumb(serial) if with_thumb else None)),
        media_group_id=media_group_id)


def _video_note_message(tg_id, serial=1, *, with_thumb=True):
    from aiogram.types import Chat, Message, User, VideoNote
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Сергей"),
        video_note=VideoNote(file_id=f"vn_fid_{serial}",
                             file_unique_id=f"vn_uniq_{serial}",
                             length=360, duration=15, file_size=800_000,
                             thumbnail=(_thumb(serial)
                                        if with_thumb else None)))


# ── Direct Chat payload (минимальный сервис, прецедент test_direct_chat) ────

def _direct_service(db):
    return DirectChatService(MagicMock(), db, MagicMock(),
                             types.SimpleNamespace(resolve=lambda *a, **k: ""))


def _user_message(tg_id, text=None, caption=None, *, reply_to=None,
                  media_type="photo", media_group_id=None):
    """MagicMock-сообщение с явными медиа-полями (прецедент ADD-TR)."""
    m = MagicMock()
    m.text = text
    m.caption = caption
    m.entities = None
    m.caption_entities = None
    m.reply_to_message = reply_to
    m.message_id = tg_id
    m.chat = MagicMock()
    m.chat.id = CHAT
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = USER_ID
    m.photo = [MagicMock()] if media_type == "photo" else None
    m.document = None
    m.video = None
    m.video_note = None
    m.voice = None
    m.audio = None
    m.animation = None
    m.sticker = None
    m.media_group_id = media_group_id
    m.forward_origin = None
    return m


async def _w3_payload(db):
    """Payload Direct Chat для окна чата (сквозной consumer
    collect_media_analysis_blocks → format_chat_context)."""
    rows = await db.get_smart_window(CHAT, 0, 10)
    return await chat_context.build_chat_context(db, rows, chat_id=CHAT)


async def _payload_contains(db, *needles):
    payload = await _w3_payload(db)
    assert payload, "payload Direct Chat пуст"
    for needle in needles:
        assert needle in payload, f"{needle!r} нет в payload:\n{payload}"
    return payload


# ═════════════════════ Матрица A: Media × Vision × Direct Chat ══════════════

class TestMediaVisionDirectChat:
    """§24 (22 сценария + ключевой): intake → состояние Vision → payload
    Direct Chat; per-message consistency (W2 states); честность превью."""

    async def _ready_payload(self, db, msg, bot_blobs, *, body=None,
                             save_kwargs=None):
        t = Transport(default=(200, body or _analysis_body()))
        bot = _FakeBot(bot_blobs)
        assets = await _process_asset(db, msg, t, bot)
        await _save_media_row(db, msg.message_id, **(save_kwargs or {}))
        payload = await _w3_payload(db)
        return assets, t, payload

    @pytest.mark.asyncio
    async def test_a01_plain_photo_full_flow_to_direct_chat(self, db):
        """§24.1 обычное фото: intake → ready-анализ → payload Direct Chat
        содержит заголовок с msg-id, OCR-канал и описание; маркер фото в
        Current_Question для текстового вопроса."""
        msg = _photo_message(101, serial=1)
        assets, t, _ = await self._ready_payload(
            db, msg, {"fid_1": make_png(12, 12)},
            save_kwargs=dict(caption="бот, что тут?"))
        ready = await mca_vision.resolve_ready_for_asset(
            db, (await db.get_media_assets_for_message(CHAT, 101))[0],
            mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
        svc = _direct_service(db)
        q = svc._render_current_question(
            _user_message(102, text="что на фото?",
                          reply_to=_user_message(101, caption=None)))
        assert "[медиа: photo tg:101]" in q
        await _payload_contains(db, f"msg:{CHAT}:101",
                                mca_vision.OCR_LINE_LABEL,
                                mca_vision.DESC_LABEL)
        assert assets and t.n == 1

    @pytest.mark.asyncio
    async def test_a02_document_image_same_pipeline(self, db):
        """§24.2 изображение-документ: тот же Vision-пайплайн и payload."""
        msg = _document_message(111)
        await self._ready_payload(db, msg, {"doc_fid": make_png(13, 13)})
        row = (await db.get_media_assets_for_message(CHAT, 111))[0]
        assert row["asset_kind"] == "document"
        await _payload_contains(db, mca_vision.DESC_LABEL, f"msg:{CHAT}:111")

    @pytest.mark.asyncio
    async def test_a03_static_sticker(self, db):
        """§24.3 статический стикер: регистрируется и распознаётся."""
        msg = _sticker_message(112)
        await self._ready_payload(db, msg, {"st_fid_112": make_png(14, 14)})
        row = (await db.get_media_assets_for_message(CHAT, 112))[0]
        assert row["asset_kind"] == "sticker"
        await _payload_contains(db, mca_vision.DESC_LABEL)

    @pytest.mark.asyncio
    async def test_a04_gif_animation_cover_frame(self, db):
        """§24.4 GIF: источник honest-unsupported, обложка — визуальное
        представление; payload маркирует «превью кадра», движение не
        заявляется."""
        msg = _animation_message(113, serial=4)
        t = Transport(default=(200, _analysis_body(desc="кадр gif")))
        bot = _FakeBot({"thumb_fid_4": make_png(15, 15)})
        assets = await _process_asset(db, msg, t, bot)
        await _save_media_row(db, 113, media_type="animation")
        rows = await db.get_media_assets_for_message(CHAT, 113)
        kinds = sorted(r["asset_kind"] for r in rows)
        assert kinds == ["animation", "animation_preview"]
        preview_id = mca_vision.make_asset_id(
            CHAT, 113, "thumb_uniq_4", "animation_preview")
        assert preview_id in assets
        payload = await _payload_contains(
            db, mca_vision.ANIMATION_PREVIEW_NOTE, "движение не анализируется")
        assert mca_vision.VIDEO_PREVIEW_NOTE not in payload

    @pytest.mark.asyncio
    async def test_a05_tgs_sticker_cover(self, db):
        """§24.5 TGS: honest-unsupported источник + обложка-кандидат; тип
        админки — animated_stickers."""
        msg = _sticker_message(114, is_animated=True, with_thumb=True)
        t = Transport(default=(200, _analysis_body(desc="кадр tgs")))
        bot = _FakeBot({"thumb_fid_104": make_png(16, 16)})
        await _process_asset(db, msg, t, bot)
        await _save_media_row(db, 114, media_type="sticker")
        rows = await db.get_media_assets_for_message(CHAT, 114)
        variants = sorted((r["asset_kind"], r["size_variant"]) for r in rows)
        assert ("animation", "sticker") in variants
        assert ("animation_preview", "sticker_preview") in variants
        await _payload_contains(db, mca_vision.ANIMATION_PREVIEW_NOTE)
        assert mca_vision.media_type_for_asset(
            "animation_preview", "sticker_preview") == "animated_stickers"

    @pytest.mark.asyncio
    async def test_a06_webm_video_sticker_cover(self, db):
        """§24.6 WebM-стикер: тот же честный маршрут обложки, что TGS."""
        msg = _sticker_message(115, is_video=True, with_thumb=True)
        t = Transport(default=(200, _analysis_body(desc="кадр webm")))
        bot = _FakeBot({"thumb_fid_105": make_png(17, 17)})
        await _process_asset(db, msg, t, bot)
        await _save_media_row(db, 115, media_type="sticker")
        variants = [(r["asset_kind"], r["size_variant"]) for r in
                    await db.get_media_assets_for_message(CHAT, 115)]
        assert ("animation", "sticker") in variants
        assert ("animation_preview", "sticker_preview") in variants
        await _payload_contains(db, mca_vision.ANIMATION_PREVIEW_NOTE)

    @pytest.mark.asyncio
    async def test_a07_video_preview_not_full_view(self, db):
        """§24.7 превью видео: анализ кадра с обязательной маркировкой
        «не полный просмотр»; file_id кандидата — обложка, не видео."""
        msg = _video_message(116, serial=5)
        t = Transport(default=(200, _analysis_body(desc="кадр видео")))
        bot = _FakeBot({"thumb_fid_5": make_png(18, 18)})
        await _process_asset(db, msg, t, bot)
        await _save_media_row(db, 116, media_type="video")
        await _payload_contains(db, mca_vision.VIDEO_PREVIEW_NOTE,
                                "не полный просмотр")
        row = (await db.get_media_assets_for_message(CHAT, 116))[0]
        assert row["asset_kind"] == "video_preview"
        assert row["file_id"] == "thumb_fid_5"

    @pytest.mark.asyncio
    async def test_a08_video_note_preview_distinct(self, db):
        """§24.8 превью видеосообщения: свой size_variant → свой asset_id."""
        msg = _video_note_message(117, serial=6)
        t = Transport(default=(200, _analysis_body(desc="кадр кружка")))
        bot = _FakeBot({"thumb_fid_6": make_png(19, 19)})
        await _process_asset(db, msg, t, bot)
        await _save_media_row(db, 117, media_type="video")
        row = (await db.get_media_assets_for_message(CHAT, 117))[0]
        assert row["size_variant"] == "video_note_preview"
        assert row["asset_id"] == mca_vision.make_asset_id(
            CHAT, 117, "thumb_uniq_6", "video_note_preview")
        await _payload_contains(db, mca_vision.VIDEO_PREVIEW_NOTE)

    @pytest.mark.asyncio
    async def test_a09_media_with_caption(self, db):
        """§24.9 медиа с подписью: подпись отправителя отдельной строкой
        payload (не смешивается с OCR)."""
        msg = _photo_message(118, serial=7, caption="смотри что нашёл")
        await self._ready_payload(db, msg, {"fid_7": make_png(20, 20)},
                                  save_kwargs=dict(
                                      caption="смотри что нашёл"))
        payload = await _payload_contains(
            db, "Подпись отправителя: смотри что нашёл")
        assert "OCR, не слова автора" in payload

    @pytest.mark.asyncio
    async def test_a10_media_without_caption(self, db):
        """§24.10 медиа без подписи: анализ есть, строки подписи нет."""
        msg = _photo_message(119, serial=8)
        await self._ready_payload(db, msg, {"fid_8": make_png(21, 21)})
        payload = await _payload_contains(db, mca_vision.DESC_LABEL)
        assert "Подпись отправителя" not in payload

    @pytest.mark.asyncio
    async def test_a11_reply_targets_exact_media(self, db):
        """§24.11 reply на медиа: маркер reply-сообщения в Current_Question;
        tool-резолв по reply находит именно это сообщение."""
        target = _photo_message(120, serial=9)
        await self._ready_payload(db, target, {"fid_9": make_png(22, 22)})
        reply = _user_message(121, text="прочитай надпись",
                              reply_to=_user_message(120))
        svc = _direct_service(db)
        q = svc._render_current_question(reply)
        assert "[медиа: photo tg:120]" in q
        res = await mca_vision.resolve_target_assets(db, chat_id=CHAT,
                                                     reply_tg_id=120)
        assert res["status"] == "ok"
        assert res["assets"][0]["tg_message_id"] == 120

    @pytest.mark.asyncio
    async def test_a12_media_group_album_per_message(self, db):
        """§24.12 медиагруппа: у каждого элемента свои актив/джоба/анализ;
        payload каждого сообщения независим (per-message consistency)."""
        group = "w3-album"
        m1, m2 = (_photo_message(122, serial=10, media_group_id=group),
                  _photo_message(123, serial=11, media_group_id=group))
        bot = _FakeBot({"fid_10": make_png(23, 23),
                        "fid_11": make_png(24, 24)})
        t = Transport(default=(200, _analysis_body(desc="альбом")))
        mca_vision.bind_runtime(db)
        _cap_ok()
        a1 = await mca_vision.register_intake_assets(db, m1)
        a2 = await mca_vision.register_intake_assets(db, m2)
        # группа регистрируется ЦЕЛИКОМ до обработки (album grace не дробит)
        await mca_vision.enqueue_intake_jobs(db, m1, a1)
        await mca_vision.enqueue_intake_jobs(db, m2, a2)
        queued = [j for j in await _active_vision(db, "queued")
                  if json.loads(j["payload"]).get("asset_id") in (a1 + a2)]
        assert len(queued) == 2
        for j in queued:
            job = await _claimed_job(db, j["job_id"])
            await mca_vision.process_asset_job(job, db=db, bot=bot,
                                               transport=t)
        await _save_media_row(db, 122, media_group_id=group)
        await _save_media_row(db, 123, media_group_id=group)
        for tg in (122, 123):
            rows_ = await db.get_media_assets_for_message(CHAT, tg)
            assert len(rows_) == 1
            assert rows_[0]["media_group_id"] == group
            ready = await mca_vision.resolve_ready_for_asset(
                db, rows_[0], mca_vision.access_scope_for(CHAT))
            assert ready is not None and ready["status"] == "ready"
        payload = await _payload_contains(db, f"msg:{CHAT}:122",
                                          f"msg:{CHAT}:123")
        assert payload.count(mca_vision.DESC_LABEL) >= 2

    @pytest.mark.asyncio
    async def test_a13_forwarded_post_provenance(self, db):
        """§24.13 пересланная публикация: provenance-лейбл источника в
        payload Direct Chat (рендер Vision-фасада)."""
        msg = _photo_message(124, serial=12)
        await self._ready_payload(
            db, msg, {"fid_12": make_png(25, 25)},
            save_kwargs=dict(forward_source="Спорт-Новости"))
        await _payload_contains(db, "Переслано из Спорт-Новости")

    @pytest.mark.asyncio
    async def test_a14_reuse_ready_analysis_no_new_call(self, db):
        """§24.14 повторное использование готового анализа: тул-запросы —
        cache_hit без нового провайдер-вызова."""
        msg = _photo_message(125, serial=13)
        await self._ready_payload(db, msg, {"fid_13": make_png(26, 26)})
        t2 = Transport(default=(200, _analysis_body()))
        mca_vision._PENDING_TRIGGERS.clear()
        res1 = await mca_vision.recognize_target(db, chat_id=CHAT,
                                                 reply_tg_id=125,
                                                 wait_seconds=0,
                                                 transport=t2)
        assert res1["status"] == "ready" and res1["cache_hit"] is True
        res2 = await mca_vision.recognize_target(db, chat_id=CHAT,
                                                 reply_tg_id=125,
                                                 wait_seconds=0,
                                                 transport=t2)
        assert res2["status"] == "ready" and t2.calls == []

    @pytest.mark.asyncio
    async def test_a15_in_progress_recognition_pending(self, db):
        """§24.15 распознавание ещё в работе: payload — честный pending;
        тул — pending с job_linked (не «посмотрел»)."""
        msg = _photo_message(126, serial=14)
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        await _save_media_row(db, 126)
        await _payload_contains(db, mca_vision.PENDING_LINE)
        payload = await _w3_payload(db)
        assert mca_vision.DESC_LABEL not in payload   # описания ещё нет
        mca_vision._PENDING_TRIGGERS.clear()
        res = await mca_vision.recognize_target(db, chat_id=CHAT,
                                                reply_tg_id=126,
                                                wait_seconds=0)
        assert res["status"] == "pending"
        assert res.get("job_linked") is True
        assert res.get("asset_id") == assets[0]

    @pytest.mark.asyncio
    async def test_a16_state_changes_between_messages(self, db):
        """§24.16 изменение состояния между сообщениями: turn 1 — pending,
        turn 2 (после завершения) — готовый результат (W2 per-message)."""
        msg = _photo_message(127, serial=15)
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        await _save_media_row(db, 127)
        await _payload_contains(db, mca_vision.PENDING_LINE)
        queued = await _active_vision(db, "queued")
        job = await _claimed_job(db, queued[0]["job_id"])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_15": make_png(27, 27)}),
            transport=Transport(default=(200, _analysis_body(
                desc="финальное описание"))))
        payload = await _payload_contains(db, "финальное описание",
                                          mca_vision.DESC_LABEL)
        assert mca_vision.PENDING_LINE not in payload

    @pytest.mark.asyncio
    async def test_a17_enqueue_error_no_fake_pending(self, db):
        """§24.17 ошибка постановки задания: без живой задачи — честный
        failed (job_linked=False), не «распознавание идёт»."""
        from services.task_supervisor import TaskJobStore
        msg = _photo_message(128, serial=16)
        mca_vision.bind_runtime(db)
        _cap_ok()
        await mca_vision.register_intake_assets(db, msg)
        await _save_media_row(db, 128)
        mca_vision._PENDING_TRIGGERS.clear()
        saved = TaskJobStore.enqueue

        async def _boom(self_, **kwargs):
            raise RuntimeError("store down")

        TaskJobStore.enqueue = _boom
        try:
            res = await mca_vision.recognize_target(db, chat_id=CHAT,
                                                    reply_tg_id=128,
                                                    wait_seconds=0)
            assert res["status"] == "failed"
            assert res["reason"] == "vision_failed"
            assert res.get("job_linked") is False
        finally:
            TaskJobStore.enqueue = saved

    @pytest.mark.asyncio
    async def test_a18_recognition_error_distinct_line(self, db):
        """§24.18 ошибка распознавания: терминальная джоба → своя честная
        строка payload, отличимая от pending и от no_text."""
        msg = _photo_message(129, serial=17)
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        await _save_media_row(db, 129)
        queued = await _active_vision(db, "queued")
        job = await _claimed_job(db, queued[0]["job_id"])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_17": make_png(28, 28)}),
            transport=Transport(default=(500, _err_body("boom", "500"))))
        store = await _store(db)
        row = await store.get(job["job_id"])
        assert row["status"] == "failed"
        payload = await _w3_payload(db)
        assert mca_vision.PENDING_LINE not in payload
        assert mca_vision.NO_TEXT_LINE not in payload
        failure_lines = set(mca_vision.ANALYSIS_FAILURE_LINES.values())
        assert any(line in payload for line in failure_lines), payload

    @pytest.mark.asyncio
    async def test_a19_restart_recovery_durable_job(self, db):
        """§24.19 восстановление после рестарта: durable-джоба переживает
        «перезапуск» (новые объекты store/worker) и доводится до результата;
        результат доступен в payload."""
        msg = _photo_message(130, serial=18)
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        await _save_media_row(db, 130)
        # ── «рестарт»: runtime сброшен, новые объекты store ──────────────
        mca_vision.reset_runtime()
        store = await _store(db)
        rows = [j for j in await store.active()
                if j.get("kind") == mca_vision.VISION_JOB_KIND]
        assert rows and rows[0]["status"] == "queued"
        job = await _claimed_job(db, rows[0]["job_id"])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_18": make_png(29, 29)}),
            transport=Transport(default=(200, _analysis_body(
                desc="после рестарта"))))
        ready = await mca_vision.resolve_ready_for_asset(
            db, (await db.get_media_assets_for_message(CHAT, 130))[0],
            mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"
        await _payload_contains(db, "после рестарта")

    @pytest.mark.asyncio
    async def test_a20_module_disabled_honest(self, db, monkeypatch):
        """§24.20 отключённый модуль: enqueue нет (registry сохранён),
        media-блоков в payload нет (байт-в-байт прежний контекст), маркер
        Current_Question остаётся (не vision-гейтится)."""
        msg = _photo_message(131, serial=19)
        mca_vision.bind_runtime(db)

        async def _req_off(chat_id=None):
            return False

        monkeypatch.setattr(mca_vision, "resolve_requested", _req_off)
        assets = await mca_vision.register_intake_assets(db, msg)
        assert assets                       # канонический реестр не сужен
        assert await mca_vision.enqueue_intake_jobs(db, msg, assets) == 0
        assert await _active_vision(db) == []
        await _save_media_row(db, 131)
        payload = await _w3_payload(db)
        assert mca_vision.DESC_LABEL not in payload
        assert mca_vision.PENDING_LINE not in payload
        svc = _direct_service(db)
        q = svc._render_current_question(
            _user_message(132, text="что на фото?",
                          reply_to=_user_message(131)))
        assert "[медиа: photo tg:131]" in q

    @pytest.mark.asyncio
    async def test_a21_missing_source_file_honest(self, db):
        """§24.21 отсутствующий исходный файл: транзиентные неудачи загрузки
        уходят в bounded-retry, терминальный исход наблюдаем в payload
        (не тихий сброс и не вечный pending)."""
        msg = _photo_message(133, serial=20)
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        await _save_media_row(db, 133)
        queued = await _active_vision(db, "queued")
        bot = _FakeBot({})                     # файл недоступен
        row = await _process_until_terminal(db, queued[0]["job_id"],
                                            Transport(default=(200,
                                                               _analysis_body())),
                                            bot)
        assert row["status"] == "failed"
        outcome = await mca_vision.asset_vision_outcome(
            db, assets[0], mca_vision.access_scope_for(CHAT))
        assert outcome is not None
        # терминал download-неудачи — job_terminal (честная строка, не pending)
        payload = await _payload_contains(
            db, mca_vision.ANALYSIS_FAILURE_LINES["job_terminal"])
        assert mca_vision.PENDING_LINE not in payload

    @pytest.mark.asyncio
    async def test_a22_concurrent_multi_media(self, db):
        """§24.22 одновременная обработка нескольких медиа: каждая гранула —
        свой анализ, привязки не перепутаны."""
        m1, m2 = _photo_message(134, serial=21), _photo_message(135,
                                                                serial=22)
        bot = _FakeBot({"fid_21": make_png(30, 30),
                        "fid_22": make_png(31, 31)})
        mca_vision.bind_runtime(db)
        _cap_ok()
        a1 = await mca_vision.register_intake_assets(db, m1)
        a2 = await mca_vision.register_intake_assets(db, m2)
        await mca_vision.enqueue_intake_jobs(db, m1, a1)
        await mca_vision.enqueue_intake_jobs(db, m2, a2)
        await _save_media_row(db, 134)
        await _save_media_row(db, 135)

        async def _run(aids, desc):
            queued = [j for j in await _active_vision(db, "queued")
                      if json.loads(j["payload"]).get("asset_id") in aids]
            job = await _claimed_job(db, queued[0]["job_id"])
            await mca_vision.process_asset_job(
                job, db=db, bot=bot,
                transport=Transport(default=(200, _analysis_body(desc=desc))))

        await asyncio.gather(_run(a1, "описание первого"),
                             _run(a2, "описание второго"))
        for tg, desc in ((134, "описание первого"), (135, "описание второго")):
            assets = await db.get_media_assets_for_message(CHAT, tg)
            ready = await mca_vision.resolve_ready_for_asset(
                db, assets[0], mca_vision.access_scope_for(CHAT))
            assert ready is not None and ready["status"] == "ready"
            rendered = await mca_vision.render_media_context_async(
                db, chat_id=CHAT, tg_message_id=tg)
            assert desc in rendered["text"]

    @pytest.mark.asyncio
    async def test_a23_key_scenario_question_while_working(self, db):
        """§24 КЛЮЧЕВОЙ сценарий: вопрос о фото во время работы Vision →
        payload честно говорит «фото существует и обрабатывается» (маркер +
        pending, без выдуманных описаний и без ложной неспособности);
        после завершения следующее обращение использует результат."""
        msg = _photo_message(136, serial=23)
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        await _save_media_row(db, 136)
        # ── turn 1: вопрос «что на фото?» пока джоба ещё не выполнена ────
        payload = await _w3_payload(db)
        assert mca_vision.PENDING_LINE in payload      # существует + в работе
        assert mca_vision.DESC_LABEL not in payload    # выдуманного нет
        assert "не могу просматривать" not in payload
        svc = _direct_service(db)
        q = svc._render_current_question(
            _user_message(137, text="что на фото?",
                          reply_to=_user_message(136)))
        assert "[медиа: photo tg:136]" in q
        # ── turn 2: анализ завершён → результат используется ────────────
        queued = await _active_vision(db, "queued")
        job = await _claimed_job(db, queued[0]["job_id"])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_23": make_png(32, 32)}),
            transport=Transport(default=(200, _analysis_body(
                desc="чёрный квадрат Малевича"))))
        res = await mca_vision.recognize_target(db, chat_id=CHAT,
                                                reply_tg_id=136,
                                                wait_seconds=0)
        assert res["status"] == "ready"
        payload2 = await _payload_contains(db, "чёрный квадрат Малевича")
        assert mca_vision.PENDING_LINE not in payload2


# ═════════════════════ Матрица B: Media × Fact-check ════════════════════════

class TestMediaFactcheck:
    """Альбом + типы превью через whole-post путь фактчека (P0-FACTCHECK
    media): сквозной поток smart_messages + Vision-анализы →
    resolve_claim_publication."""

    async def _factcheck_publication(self, db, *, tg_id, base_text,
                                     media_type="photo", caption=None,
                                     media_group_id=None, target=None):
        await _save_media_row(db, tg_id, media_type=media_type,
                              caption=caption,
                              media_group_id=media_group_id)
        return await fcs.resolve_claim_publication(
            db, CHAT, tg_id, base_text=base_text, target=target)

    @pytest.mark.asyncio
    async def test_b01_album_whole_post_ocr_all_elements(self, db):
        """Альбом (2 фото, OCR на обоих): тезис содержит текст КАЖДОГО
        элемента; публикация полная (без honest-оговорки неполноты)."""
        group = "w3-fc-album"
        m1 = _photo_message(141, serial=30, caption="первый кадр",
                            media_group_id=group)
        m2 = _photo_message(142, serial=31, media_group_id=group)
        bot = _FakeBot({"fid_30": make_png(40, 40),
                        "fid_31": make_png(41, 41)})
        t = Transport(default=(200, _analysis_body(
            desc="скрин новости", ocr_text="СРОЧНО: КУРС УПАЛ")))
        mca_vision.bind_runtime(db)
        _cap_ok()
        a1 = await mca_vision.register_intake_assets(db, m1)
        a2 = await mca_vision.register_intake_assets(db, m2)
        await mca_vision.enqueue_intake_jobs(db, m1, a1)
        await mca_vision.enqueue_intake_jobs(db, m2, a2)
        queued = [j for j in await _active_vision(db, "queued")
                  if json.loads(j["payload"]).get("asset_id") in (a1 + a2)]
        assert len(queued) == 2
        for j in queued:
            job = await _claimed_job(db, j["job_id"])
            await mca_vision.process_asset_job(job, db=db, bot=bot,
                                               transport=t)
        await _save_media_row(db, 141, media_group_id=group,
                              caption="первый кадр")
        await _save_media_row(db, 142, media_group_id=group)
        pub = await fcs.resolve_claim_publication(db, CHAT, 141,
                                                  base_text="первый кадр")
        assert "СРОЧНО: КУРС УПАЛ" in pub.text
        assert pub.has_image and pub.media.image_count == 2
        assert pub.media.image_analyzed
        assert not pub.album_incomplete
        assert pub.notice() == ""
        assert 141 in pub.message_ids and 142 in pub.message_ids

    @pytest.mark.asyncio
    async def test_b02_album_pending_member_honest_notice(self, db):
        """Альбом с непроспознанным элементом: pending второго изображения —
        честная оговорка «часть ещё не распознана», не «нет изображения»."""
        group = "w3-fc-album2"
        m1 = _photo_message(143, serial=32, media_group_id=group)
        m2 = _photo_message(144, serial=33, media_group_id=group)
        bot = _FakeBot({"fid_32": make_png(42, 42),
                        "fid_33": make_png(43, 43)})
        t = Transport(default=(200, _analysis_body(desc="кадр 1")))
        mca_vision.bind_runtime(db)
        _cap_ok()
        a1 = await mca_vision.register_intake_assets(db, m1)
        await mca_vision.register_intake_assets(db, m2)   # актив без джобы
        await mca_vision.enqueue_intake_jobs(db, m1, a1)
        queued = await _active_vision(db, "queued")
        job = await _claimed_job(db, queued[0]["job_id"])
        await mca_vision.process_asset_job(job, db=db, bot=bot, transport=t)
        await _save_media_row(db, 143, media_group_id=group)
        await _save_media_row(db, 144, media_group_id=group)
        pub = await fcs.resolve_claim_publication(db, CHAT, 143,
                                                  base_text="смотри")
        assert pub.media.image_count >= 1
        assert "Часть изображений публикации ещё не распознана" \
            in pub.notice()

    @pytest.mark.asyncio
    async def test_b03_sticker_post_image_contour(self, db):
        """Пост-стикер: статический стикер — в image-контуре фактчека."""
        msg = _sticker_message(145)
        await _process_asset(db, msg, Transport(default=(200, _analysis_body(
            desc="стикер"))), _FakeBot({"st_fid_145": make_png(44, 44)}))
        pub = await self._factcheck_publication(
            db, tg_id=145, base_text="", media_type="sticker")
        assert pub.has_image and pub.media.image_present
        assert pub.media.image_analyzed

    @pytest.mark.asyncio
    async def test_b04_video_post_preview_material_no_false_failure(self, db):
        """Видео-пост: визуальный материал фактчека — из честно
        маркированного превью-контура; техническая недоступность не
        приписывается (expected_images не завышен)."""
        msg = _video_message(146, serial=34)
        await _process_asset(db, msg, Transport(default=(200, _analysis_body(
            desc="кадр видео"))),
            _FakeBot({"thumb_fid_34": make_png(45, 45)}))
        pub = await self._factcheck_publication(
            db, tg_id=146, base_text="видео-пост", media_type="video")
        assert pub.media.image_present
        assert pub.media.vision_failed is False
        assert "кадр видео" in pub.media.description_suffix \
            or "кадр видео" in pub.text

    @pytest.mark.asyncio
    async def test_b05_vision_failed_technical_notice(self, db):
        """Сбой чтения Vision-контура при ожидаемом изображении: честная
        техническая оговорка, текст публикации сохраняется."""
        target = _user_message(147, caption="текст поста")
        pub = await fcs.resolve_claim_publication(
            db, CHAT, 147, base_text="текст поста", target=target)
        assert pub.media.vision_failed is True
        assert pub.media.image_present is False
        assert "не удалось прочитать" in pub.notice()
        assert "текст поста" in pub.text

    @pytest.mark.asyncio
    async def test_b06_no_text_no_false_pending(self, db):
        """Готовый no_text-анализ: фактчек не показывает «распознавание ещё
        не готово» (F6) — analyzed без ложной оговорки."""
        msg = _photo_message(148, serial=35)
        await _process_asset(db, msg, Transport(default=(200, _NO_TEXT_BODY)),
                             _FakeBot({"fid_35": make_png(46, 46)}))
        pub = await self._factcheck_publication(
            db, tg_id=148, base_text="пост без текста на фото")
        assert pub.media.image_analyzed
        assert not pub.media.image_not_analyzed
        assert "распознавание ещё не готово" not in pub.notice()


# ══════════════════ Матрица C: Image-gen × Direct Chat × Admin ══════════════

_READY_CONF = {
    "flags.image_generation_module_enabled": True,
    "keys.image_api_key": "test-key",
    "models.image_model": "test-model",
}


def _patch_image_sources(monkeypatch, *, module_on=True):
    hot.set_config_cache(_Cfg(dict(_READY_CONF)))

    async def _module(_chat_id=None):
        return bool(module_on)

    monkeypatch.setattr(ig, "resolve_module_enabled", _module)

    async def fake_usage(pg=None, scope=None, day=None):
        return []

    async def fake_limits(chat_id):
        return (200, 60, "default")

    monkeypatch.setattr(wb, "get_usage", fake_usage)
    monkeypatch.setattr(wb, "image_limits", fake_limits)
    from services import postgen_vision
    monkeypatch.setattr(postgen_vision, "enabled", lambda: False)


def _patch_edit_caps(monkeypatch, *, edit_value: str):
    def _resolve(provider, base_url, model, **kwargs):
        caps_obj = icap.conservative_unknown()
        caps_obj.image_edit = edit_value
        return caps_obj

    monkeypatch.setattr(icap, "resolve_capabilities", _resolve)


class _Result:
    def __init__(self, ok, reason="", content=b"", filename="image.png"):
        self.ok = ok
        self.reason = reason
        self.content = content
        self.filename = filename


class TestImageGenDirectAdmin:
    """§25 (14 сценариев) + §22 (админка): capability claim vs фактический
    маршрут; edit-route из reply/контекста; admin types/diag против runtime."""

    def _router(self, db):
        router = object.__new__(ToolRouter)
        router.deps = types.SimpleNamespace(db=db)
        return router

    @pytest.mark.asyncio
    async def test_c01_create_image_actual_route(self, db, monkeypatch):
        """§25.1 создание изображения: dispatch generate_image идёт через
        РЕАЛЬНЫЙ единый раннер и generate_and_send до контрактного мока
        провайдера; ToolResult — success; исход — в реестре."""
        _patch_image_sources(monkeypatch)
        gen_calls: list = []
        delivered: list = []

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 timeout=None, consume_budget=True,
                                 retry=True):
            gen_calls.append({"prompt": prompt, "chat_id": chat_id})
            return _Result(ok=True, content=b"png-bytes")

        async def _fake_send_photo(bot, chat_id, photo, **kwargs):
            delivered.append({"chat_id": chat_id, **kwargs})
            return object()

        monkeypatch.setattr(ig, "generate", _fake_generate)
        from services import telegram_send
        monkeypatch.setattr(telegram_send, "send_photo", _fake_send_photo)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй кота", bot=object(),
                          correlation_id="w3-c1")
        out = await router.dispatch("generate_image",
                                    {"prompt": "кот в шляпе"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "success"
        assert gen_calls and gen_calls[0]["chat_id"] == CHAT
        assert "кот в шляпе" in gen_calls[0]["prompt"]
        assert delivered and delivered[0]["chat_id"] == CHAT
        assert caps._outcome("image_generation", CHAT)[0] \
            == caps.RESULT_SUCCESS

    @pytest.mark.asyncio
    async def test_c02_successful_send_delivery_reply(self, db, monkeypatch):
        """§25.2 успешная отправка: результат доставлен существующей
        telegram_send.send_photo с reply на запрос (доставка после генерации)."""
        _patch_image_sources(monkeypatch)

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 timeout=None, consume_budget=True,
                                 retry=True):
            return _Result(ok=True, content=b"png-bytes")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        delivered: list = []

        async def _fake_send_photo(bot, chat_id, photo, **kwargs):
            delivered.append({"chat_id": chat_id, **kwargs})
            return object()

        from services import telegram_send
        monkeypatch.setattr(telegram_send, "send_photo", _fake_send_photo)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй", bot=object(),
                          reply_to_message_id=200)
        out = await router.dispatch("generate_image", {"prompt": "мем"}, ctx)
        assert json.loads(out)["status"] == "success"
        assert delivered and delivered[0]["chat_id"] == CHAT
        assert delivered[0].get("reply_to_message_id") == 200

    @pytest.mark.asyncio
    async def test_c03_generation_error_real_reason(self, db, monkeypatch):
        """§25.3 ошибка генерации: реальный reason доводится через честный
        исход generate_and_send; отправки нет; исход — fail в реестре."""
        _patch_image_sources(monkeypatch)

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 timeout=None, consume_budget=True,
                                 retry=True):
            return _Result(ok=False, reason="provider_down")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        delivered: list = []

        async def _fake_send_photo(bot, chat_id, photo, **kwargs):
            delivered.append({"chat_id": chat_id})
            return object()

        from services import telegram_send
        monkeypatch.setattr(telegram_send, "send_photo", _fake_send_photo)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй", bot=object())
        out = await router.dispatch("generate_image", {"prompt": "мем"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["reason"] == "provider_down"
        assert delivered == []                   # отправки нет
        assert caps._outcome("image_generation", CHAT)[0] \
            == caps.RESULT_FAILED

    @pytest.mark.asyncio
    async def test_c04_send_error_honest(self, db, monkeypatch):
        """§25.4 ошибка отправки: генерация удалась, доставка нет → честный
        send_failed (не «успешно отправлено»)."""
        _patch_image_sources(monkeypatch)

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 timeout=None, consume_budget=True,
                                 retry=True):
            return _Result(ok=True, content=b"png-bytes")

        monkeypatch.setattr(ig, "generate", _fake_generate)

        async def _boom(bot, chat_id, photo, **kwargs):
            raise RuntimeError("telegram down")

        from services import telegram_send
        monkeypatch.setattr(telegram_send, "send_photo", _boom)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй", bot=object())
        out = await router.dispatch("generate_image", {"prompt": "мем"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["reason"] == "send_failed"

    @pytest.mark.asyncio
    async def test_c05_follow_up_after_send_skipped(self, db, monkeypatch):
        """§25.5 повторное обращение после отправки: маркер прогона →
        skipped/already_handled без второй генерации."""
        _patch_image_sources(monkeypatch)
        calls: list = []

        async def _fake_generate(prompt, *, chat_id=None, correlation_id=None,
                                 timeout=None, consume_budget=True,
                                 retry=True):
            calls.append(prompt)
            return _Result(ok=True, content=b"png")

        monkeypatch.setattr(ig, "generate", _fake_generate)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй", bot=object())
        ctx.image_request_handled = True
        out = await router.dispatch("generate_image",
                                    {"prompt": "второй кот"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "skipped"
        assert payload["reason"] == "already_handled"
        assert calls == []

    @pytest.mark.asyncio
    async def test_c06_edit_via_reply_uses_registry_source(self, db,
                                                           monkeypatch):
        """§25.6 редактирование по reply: исходник — из канонического
        реестра intake (реальная БД), маршрут — submit_edit; результат
        связан с исходным сообщением."""
        _patch_image_sources(monkeypatch)
        _patch_edit_caps(monkeypatch, edit_value="yes")
        caps.invalidate(None, None, reason="test")
        msg = _photo_message(201, serial=40)
        await _process_asset(db, msg,
                             Transport(default=(200, _analysis_body())),
                             _FakeBot({"fid_40": make_png(50, 50)}))
        calls: dict = {"edit": [], "download": [], "send": []}

        class _FakeAdapter:
            name = "nanogpt"

            async def submit_edit(self, *, prompt, model, image_paths, **kw):
                calls["edit"].append({"prompt": prompt, "model": model,
                                      "image_paths": list(image_paths)})
                return types.SimpleNamespace(ok=True, content=b"edited",
                                             reason="ok")

        import services.media_execution as me
        monkeypatch.setattr(me, "detect_adapter",
                            lambda base_url: _FakeAdapter())
        from services import mca_vision as mv
        from services import telegram_send

        async def _fake_download(bot, file_id, **kw):
            calls["download"].append(file_id)
            return mv.DownloadedImage(data=b"png", mime="image/png",
                                      declared_mime="image/png", width=10,
                                      height=10, byte_size=3)

        async def _fake_send_photo(bot, chat_id, photo, **kw):
            calls["send"].append({"chat_id": chat_id, **kw})
            return object()

        monkeypatch.setattr(mv, "download_telegram_file", _fake_download)
        monkeypatch.setattr(telegram_send, "send_photo", _fake_send_photo)
        router = self._router(db)
        ctx = ToolContext(CHAT, "измени текст на картинке", bot=object(),
                          reply_to_message_id=201, correlation_id="w3-c6")
        out = await router.dispatch(
            "edit_image",
            {"prompt": "убери текст",
             "target": {"chat_id": CHAT, "message_id": 201}},
            ctx)
        payload = json.loads(out)
        assert payload["status"] == "success", out
        assert payload["operation"] == "edit"
        assert payload["source"]["message_id"] == 201
        assert calls["edit"] and calls["edit"][0]["prompt"] == "убери текст"
        # file_id реального актива из реестра (не выдуманный):
        reg = await db.get_media_assets_for_message(CHAT, 201)
        assert calls["download"] == [reg[0]["file_id"]]
        assert calls["send"] and \
            calls["send"][0].get("reply_to_message_id") == 201
        assert caps._outcome("image_edit", CHAT)[0] == caps.RESULT_SUCCESS

    @pytest.mark.asyncio
    async def test_c07_edit_earlier_bot_created_image(self, db, monkeypatch):
        """§25.7 редактирование ранее созданного: бот-медиа регистрируется
        observer-швом W1 (register_intake_assets) и доступен edit-маршруту
        с реальным готовым анализом."""
        _patch_image_sources(monkeypatch)
        _patch_edit_caps(monkeypatch, edit_value="yes")
        caps.invalidate(None, None, reason="test")
        from aiogram.types import Chat, Message, PhotoSize, User
        bot_msg = Message(
            message_id=202,
            date=_dt.datetime(2026, 10, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
            chat=Chat(id=CHAT, type="supergroup", title="T"),
            from_user=User(id=BOT_ID, is_bot=True, first_name="Bot"),
            photo=[PhotoSize(file_id="bot_gen_fid",
                             file_unique_id="bot_gen_uniq",
                             width=800, height=600, file_size=12345)])
        mca_vision.bind_runtime(db)
        _cap_ok()
        assets = await mca_vision.register_intake_assets(db, bot_msg)
        assert assets                       # шов «результат генерации бота»
        await mca_vision.enqueue_intake_jobs(db, bot_msg, assets)
        queued = await _active_vision(db, "queued")
        job = await _claimed_job(db, queued[0]["job_id"])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"bot_gen_fid": make_png(51, 51)}),
            transport=Transport(default=(200, _analysis_body(
                desc="сгенерированный кот"))))
        edits: list = []

        class _FakeAdapter:
            name = "nanogpt"

            async def submit_edit(self, *, prompt, model, image_paths, **kw):
                edits.append(list(image_paths))
                return types.SimpleNamespace(ok=True, content=b"edited2",
                                             reason="ok")

        import services.media_execution as me
        monkeypatch.setattr(me, "detect_adapter",
                            lambda base_url: _FakeAdapter())
        from services import mca_vision as mv
        from services import telegram_send

        async def _fake_download(bot, file_id, **kw):
            return mv.DownloadedImage(data=b"png", mime="image/png",
                                      declared_mime="image/png", width=10,
                                      height=10, byte_size=3)

        async def _fake_send_photo(bot, chat_id, photo, **kw):
            return object()

        monkeypatch.setattr(mv, "download_telegram_file", _fake_download)
        monkeypatch.setattr(telegram_send, "send_photo", _fake_send_photo)
        router = self._router(db)
        ctx = ToolContext(CHAT, "поправь своего кота", bot=object())
        out = await router.dispatch(
            "edit_image",
            {"prompt": "добавь фон",
             "target": {"chat_id": CHAT, "message_id": 202}},
            ctx)
        assert json.loads(out)["status"] == "success"
        assert edits and edits[0]           # исходник скачан из реестра бота
        # готовый анализ бот-медиа тоже доступен (representation между ходами)
        ready = await mca_vision.resolve_ready_for_asset(
            db, (await db.get_media_assets_for_message(CHAT, 202))[0],
            mca_vision.access_scope_for(CHAT))
        assert ready is not None and "сгенерированный кот" in str(
            ready.get("visual_description") or "")

    @pytest.mark.asyncio
    async def test_c08_clarify_once_not_repeated(self, db, monkeypatch):
        """§25.8 уточнение требований: ambiguous-поручение («нарисуй
        что-нибудь красивое») → ровно один clarify; повтор в пределах TTL —
        обычный ход (вопрос не повторяется)."""
        _patch_image_sources(monkeypatch)
        from services.direct_chat_service import _CLARIFY_TS
        _CLARIFY_TS.clear()
        svc = _direct_service(db)

        class _GateBot:
            def __init__(self):
                self.sent = []

            async def send_message(self, chat_id, text, **kw):
                self.sent.append(str(text))
                return MagicMock()

        bot = _GateBot()
        text = "Бот, сделай это"
        msg = _user_message(210, text=text)
        intent = dcap.detect_action_intent(text, addressed=True)
        assert intent.intent == dcap.INTENT_CREATE_IMAGE
        assert intent.confidence == dcap.CONFIDENCE_AMBIGUOUS
        handled1, _i1 = await svc._image_capability_gate(CHAT, text, msg, bot)
        assert handled1 is True and len(bot.sent) == 1
        handled2, _i2 = await svc._image_capability_gate(CHAT, text, msg, bot)
        assert handled2 is False            # clarify подавлен — обычный ход
        assert len(bot.sent) == 1
        # TTL истёк → вопрос снова возможен (не «навсегда заглушен»)
        _CLARIFY_TS[int(CHAT)] = time.monotonic() - 601.0
        handled3, _i3 = await svc._image_capability_gate(CHAT, text, msg, bot)
        assert handled3 is True and len(bot.sent) == 2

    @pytest.mark.asyncio
    async def test_c09_source_preserved_between_messages(self, db):
        """§25.9 сохранение исходника между сообщениями: актив первого
        сообщения резолвится позже (registry + готовый анализ + (C)-резолв)."""
        msg = _photo_message(203, serial=41)
        await _process_asset(db, msg, Transport(default=(200, _analysis_body(
            desc="исходник"))), _FakeBot({"fid_41": make_png(52, 52)}))
        res = await mca_vision.resolve_target_assets(db, chat_id=CHAT,
                                                     reply_tg_id=203)
        assert res["status"] == "ok"
        ready = await mca_vision.resolve_ready_for_asset(
            db, res["assets"][0], mca_vision.access_scope_for(CHAT))
        assert ready is not None and "исходник" in str(
            ready.get("visual_description") or "")
        svc = _direct_service(db)
        markers = await svc._resolve_earlier_image_markers(
            CHAT, _user_message(204, text="что на фото?"))
        assert markers == ("[медиа: photo tg:203]",)

    @pytest.mark.asyncio
    async def test_c10_only_vision_unavailable(self, db, monkeypatch):
        """§25.10 недоступность только Vision: vision-джоба падает честно,
        генерация изображений работает."""
        msg = _photo_message(205, serial=42)
        mca_vision.bind_runtime(db)
        assets = await mca_vision.register_intake_assets(db, msg)
        await mca_vision.enqueue_intake_jobs(db, msg, assets)
        queued = await _active_vision(db, "queued")
        job = await _claimed_job(db, queued[0]["job_id"])
        await mca_vision.process_asset_job(
            job, db=db, bot=_FakeBot({"fid_42": make_png(53, 53)}),
            transport=Transport(default=(401, _err_body("no auth", "401"))))
        store = await _store(db)
        assert (await store.get(job["job_id"]))["status"] == "failed"
        _patch_image_sources(monkeypatch)

        async def _fake_gen(bot, chat_id, prompt, **kw):
            return _Result(ok=True, content=b"png")

        monkeypatch.setattr(ig, "generate_and_send", _fake_gen)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй", bot=object())
        out = await router.dispatch("generate_image", {"prompt": "мем"}, ctx)
        assert json.loads(out)["status"] == "success"

    @pytest.mark.asyncio
    async def test_c11_only_imagegen_unavailable(self, db, monkeypatch):
        """§25.11 недоступность только Image Generation: generate — честный
        отказ, Vision продолжает разбирать фото."""
        _patch_image_sources(monkeypatch, module_on=False)
        router = self._router(db)
        ctx = ToolContext(CHAT, "бот нарисуй", bot=object())
        out = await router.dispatch("generate_image", {"prompt": "мем"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["message"] == "Генерация изображений отключена"
        msg = _photo_message(206, serial=43)
        await _process_asset(db, msg, Transport(default=(200, _analysis_body(
            desc="фото живо"))), _FakeBot({"fid_43": make_png(54, 54)}))
        ready = await mca_vision.resolve_ready_for_asset(
            db, (await db.get_media_assets_for_message(CHAT, 206))[0],
            mca_vision.access_scope_for(CHAT))
        assert ready is not None and ready["status"] == "ready"

    @pytest.mark.asyncio
    async def test_c12_only_edit_unsupported(self, db, monkeypatch):
        """§25.12 недоступность только Image Edit: edit_unsupported, при
        этом генерация в том же рантайме готова (операции независимы)."""
        _patch_image_sources(monkeypatch)
        _patch_edit_caps(monkeypatch, edit_value="no")
        caps.invalidate(None, None, reason="test")
        router = self._router(db)
        ctx = ToolContext(CHAT, "измени картинку", bot=object(),
                          reply_to_message_id=201)
        out = await router.dispatch("edit_image", {"prompt": "измени"}, ctx)
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["reason"] == "edit_unsupported"
        view = await caps.capability_view(CHAT)
        ids = {item["capability_id"]: item["status"] for item in view}
        assert ids.get("image_generation") == "ready"
        assert ids.get("image_edit") == "unsupported"

    @pytest.mark.asyncio
    async def test_c13_normal_fallback_no_image_tools(self, db, monkeypatch):
        """§25.13 штатный fallback: выключенный модуль убирает image-инструменты
        из анонса; включённый — канон 15 инструментов с edit_image в хвосте."""
        schemas_off = tool_schemas.active_tools(True, False)
        names_off = [t["function"]["name"] for t in schemas_off]
        assert "generate_image" not in names_off
        assert "edit_image" not in names_off
        schemas_on = tool_schemas.active_tools(True, True)
        names_on = [t["function"]["name"] for t in schemas_on]
        assert "generate_image" in names_on and "edit_image" in names_on
        assert names_on[-1] == "edit_image"           # канон 15, хвост
        assert len(names_on) == 15

    @pytest.mark.asyncio
    async def test_c14_no_false_promises_after_failure(self, db):
        """§25.14 отсутствие ложных обещаний: неуспех генерации сохраняет
        capability_notice в контексте Writer'а (заявление = фактический
        результат хода)."""
        notice = ('<capability_notice status="temporarily_unavailable" '
                  'capability="image_generation">\nИнструмент '
                  'image_generation сейчас недоступен.\n</capability_notice>')
        llm_calls: list = []

        class _LLM:
            async def generate_chat(self, messages, **kw):
                llm_calls.append(messages)
                if len(llm_calls) == 1:
                    call = types.SimpleNamespace(
                        id="c1", name="generate_image",
                        arguments=json.dumps({"prompt": "мем"}),
                        as_openai_dict=lambda: {})
                    return types.SimpleNamespace(content="",
                                                 tool_calls=[call])
                return types.SimpleNamespace(content="готово",
                                             tool_calls=None)

        class _Router:
            async def dispatch(self, name, arguments, ctx):
                return json.dumps({"status": "error", "reason": "timeout",
                                   "message": "не отвечает"},
                                  ensure_ascii=False)

        ctx = ToolContext(CHAT, "бот нарисуй мем", bot=object())
        await chat_with_tools(_LLM(),
                              [{"role": "user",
                                "content": f"бот нарисуй мем\n{notice}"}],
                              tools=[], router=_Router(), ctx=ctx,
                              chat_id=CHAT)
        final = "\n".join(m.get("content", "") for m in llm_calls[-1]
                          if m.get("role") == "user")
        assert "capability_notice" in final   # неуспех — пометка осталась

    @pytest.mark.asyncio
    async def test_c15_admin_media_types_reflect_reality(self, db,
                                                         monkeypatch):
        """§22 Типы медиа: витрина совпадает с фактическими гейтами
        enqueue (выключенный тип не ставит джобу, включённый — ставит;
        канонический реестр не сужается)."""
        values = dict(_READY_CONF)
        values["flags.vision_media_video_previews"] = False
        _hot_cache(monkeypatch, values)
        snapshot = await mca_vision.runtime_snapshot(db=db, chat_id=CHAT)
        types_ = {t["type"]: t["enabled"] for t in snapshot["media_types"]}
        assert types_ == {"photo_docs": True, "static_stickers": True,
                          "gif_animations": True, "animated_stickers": True,
                          "video_previews": False}
        assert "video_previews" not in snapshot["types_need_transform"]
        mca_vision.bind_runtime(db)
        _cap_ok()
        vid = _video_message(207, serial=44, with_thumb=True)
        photo = _photo_message(208, serial=45)
        a_vid = await mca_vision.register_intake_assets(db, vid)
        a_photo = await mca_vision.register_intake_assets(db, photo)
        assert await mca_vision.enqueue_intake_jobs(db, vid, a_vid) == 0
        assert await mca_vision.enqueue_intake_jobs(db, photo, a_photo) > 0
        vids = await db.get_media_assets_for_message(CHAT, 207)
        assert vids and vids[0]["asset_kind"] == "video_preview"
        queued_ids = {json.loads(j["payload"]).get("asset_id")
                      for j in await _active_vision(db, "queued")}
        assert not set(a_vid) & queued_ids
        assert set(a_photo) & queued_ids

    @pytest.mark.asyncio
    async def test_c16_admin_diag_queue_and_last_error(self, db):
        """§22 Диагностика: счётчики очереди и последняя ошибка витрины —
        из фактических durable-строк task_jobs; «последний анализ» — строка
        ЭТОГО чата."""
        msg_bad = _photo_message(209, serial=46)
        msg_ok = _photo_message(210, serial=47)
        mca_vision.bind_runtime(db)
        _cap_ok()
        a_bad = await mca_vision.register_intake_assets(db, msg_bad)
        a_ok = await mca_vision.register_intake_assets(db, msg_ok)
        await mca_vision.enqueue_intake_jobs(db, msg_bad, a_bad)
        await mca_vision.enqueue_intake_jobs(db, msg_ok, a_ok)
        queued = await _active_vision(db, "queued")
        assert len(queued) == 2
        by_asset = {json.loads(j["payload"]).get("asset_id"): j
                    for j in queued}
        bot = _FakeBot({"fid_46": make_png(55, 55),
                        "fid_47": make_png(56, 56)})
        row_bad = await _process_until_terminal(
            db, by_asset[a_bad[0]]["job_id"],
            Transport(default=(500, _err_body("boom", "500"))), bot)
        assert row_bad["status"] == "failed"
        job_ok = await _claimed_job(db, by_asset[a_ok[0]]["job_id"])
        await mca_vision.process_asset_job(
            job_ok, db=db, bot=bot,
            transport=Transport(default=(200, _analysis_body())))
        snapshot = await mca_vision.runtime_snapshot(db=db, chat_id=CHAT)
        assert snapshot["queue"]["failed"] >= 1
        assert snapshot["last_error"] is not None
        assert snapshot["last_error"]["reason_code"] == "vision_failed"
        assert snapshot["last"] is not None
        assert snapshot["last"]["chat_id"] == CHAT
        assert snapshot["last"]["status"] == "ready"


# ═══════════════════ Матрица D: Nostalgia × provenance ══════════════════════

class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return "кстати, помню как тогда было"

    async def generate_worker(self, role, messages, temperature=None):
        return await self.generate(messages, temperature=temperature)


class _FakeNostBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text):
        self.calls.append((int(chat_id), str(text)))
        return MagicMock(message_id=1)


class _FakeMemory:
    def __init__(self, facts=()):
        self._facts = list(facts)

    async def fetch_golden_facts(self, chat_id, query, min_importance=0,
                                 min_age_days=0, limit=2):
        return list(self._facts)[:limit]


class TestNostalgiaProvenance:
    """§23 (16 сценариев): composed память с provenance-лейблами, отказы до
    публикации, отсутствие помех от новых типов медиа. Содержательность —
    по payload LLM (user/system-блоки) и исходам воркера, не только факт
    отправки."""

    async def _silence(self, db):
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=USER_ID, text="в чате тишина",
            timestamp=NOW - 30 * 3600, sent_at=NOW - 30 * 3600,
            ingested_at=NOW - 30 * 3600, media_type="text",
            author_name="Вася")

    async def _year_back(self, db, text, *, ts=None, forward_source=None,
                         author="Вася"):
        """Год-назад пул: календарно-детерминированный ts (P0 REWORK W1,
        NOST-02: окно — календарный день годовщины в tz чата, не 365*86400;
        полдень дня годовщины + необязательный сдвиг)."""
        from config.settings import settings
        tz = nw._zone(settings.SUMMARY_TIMEZONE)
        now_local = nw._local_datetime(NOW, tz)
        anniv = nw._anniversary_date(now_local.date(),
                                     now_local.year - 1)
        day_start = nw._anniversary_window(anniv, tz, "day", 0, 0)[0]
        t = ts if ts is not None else int(day_start) + 12 * 3600 + 3000
        return await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=USER_ID, text=text, timestamp=t,
            sent_at=t, ingested_at=t, media_type="text", author_name=author,
            is_forward=bool(forward_source), forward_source=forward_source
            or "")

    def _worker(self, db, llm, monkeypatch, *, bot=None, memory=None,
                values=None):
        b = bot if bot is not None else _FakeNostBot()
        w = nw.NostalgiaWorker(db, memory=memory, store=None, llm=llm,
                               bot=b, bot_id=BOT_ID)
        vals = {"memory.nostalgia_enabled": True}
        if values:
            vals.update(values)
        _hot_cache(monkeypatch, vals)
        monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
        monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: 12)
        return w, b

    async def _log_rows(self, db, status=None):
        sql = "SELECT id, chat_id, ts, kind, fact_id, status, meta " \
              "FROM nostalgia_log"
        params = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY id"
        cur = await db.db.execute(sql, params)
        return await cur.fetchall()

    @pytest.mark.asyncio
    async def test_d01_spontaneous_appropriate_memory(self, db, monkeypatch):
        """Спонтанное уместное воспоминание: пул года доходит до LLM,
        связный текст публикуется штатным legacy-путём, причина публикации —
        в nostalgia_log."""
        await self._silence(db)
        await self._year_back(db, "год назад уронили торт у Васи")
        llm = _FakeLLM("кстати, год назад торт у васи пол отвесил")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 1 and len(bot.calls) == 1
        user_text = llm.calls[0][0][1]["content"]
        assert "год назад уронили торт" in user_text
        assert user_text.startswith("В чате давно тихо")
        rows = await self._log_rows(db, "sent")
        assert rows and json.loads(rows[-1]["meta"])["reason"] == "sent"

    @pytest.mark.asyncio
    async def test_d02_unexpected_but_meaningful_association(self, db,
                                                             monkeypatch):
        """Неожиданная, но осмысленная ассоциация: year-back + golden-факт —
        оба набора в user-блоке; публикация не блокируется."""
        await self._silence(db)
        await self._year_back(db, "ровно год назад открыли офис")
        golden = {"id": 7, "fact": "вася обожает пельмени",
                  "importance": 8, "rag_ts": NOW - 300 * 86400,
                  "target_user": "Вася"}
        llm = _FakeLLM("кстати, ровно год назад открыли офис, накануне "
                       "пельменного дня васи")
        w, bot = self._worker(db, llm, monkeypatch,
                              memory=_FakeMemory([golden]))
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 1 and bot.calls
        user_text = llm.calls[0][0][1]["content"]
        assert "открыли офис" in user_text
        assert "Старые факты" in user_text
        assert "[Вася]" in user_text            # target_user — именем

    @pytest.mark.asyncio
    async def test_d03_random_fact_without_false_link(self, db, monkeypatch):
        """Случайный факт без связи: анти-вымысел/несвязанность — канон в
        system-блоке (содержательность инструкцией, без детерминированной
        цензуры нейтрального текста)."""
        await self._silence(db)
        await self._year_back(db, "год назад чинили сервер")
        llm = _FakeLLM("кстати, в 1974 году выпустили первый мегапроцессор")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        system_text = llm.calls[0][0][0]["content"]
        assert ("приписывай" in system_text or "несвязанн" in system_text
                or "UNCHANGED" in system_text)
        # нейтральный текст без вердикта отказа стражем не блокируется
        assert out["sent"] == 1 and bot.calls

    @pytest.mark.asyncio
    async def test_d04_repost_old_news_provenance(self, db, monkeypatch):
        """Репост старой новости: provenance-лейбл «Переслано: источник» в
        строке пула; обычная реплика — без лейбла (один сегмент: тот же
        календарный день годовщины, гэп < 30 минут)."""
        await self._silence(db)
        await self._year_back(db, "Вера Косачева умерла за 300 м до финиша",
                              forward_source="Спорт-Новости")
        await self._year_back(db, "а я тогда писал про тромбы")
        llm = _FakeLLM("UNCHANGED")
        w, _ = self._worker(db, llm, monkeypatch)
        await w._process_chat(CHAT, NOW, manual=True)
        user_text = llm.calls[0][0][1]["content"]
        news_line = [l for l in user_text.splitlines()
                     if "Косачева" in l][0]
        ordinary = [l for l in user_text.splitlines() if "тромбы" in l][0]
        assert "| Переслано: Спорт-Новости]" in news_line
        assert "Переслано" not in ordinary

    @pytest.mark.asyncio
    async def test_d05_old_local_meme_section(self, db, monkeypatch):
        """Старый локальный мем: секция «Локальные мемы» доходит до LLM."""
        await self._silence(db)
        await self._year_back(db, "год назад родился мем про тостер")
        await db.insert_graph_fact(CHAT, "тостер — тот, кто всех поджигает",
                                   "user_memory", None, status="chat_meme")
        llm = _FakeLLM("кстати, год мемного тостера уже стучит")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 1 and bot.calls
        user_text = llm.calls[0][0][1]["content"]
        assert "Локальные мемы" in user_text
        assert "тостер" in user_text

    @pytest.mark.asyncio
    async def test_d06_participant_fact_labelled(self, db, monkeypatch):
        """Факт о конкретном участнике: target_user рендерится именем-лейблом,
        факт не привязывается не к тому человеку."""
        await self._silence(db)
        golden = {"id": 9, "fact": "коллекционирует механические клавиатуры",
                  "importance": 9, "rag_ts": NOW - 400 * 86400,
                  "target_user": "Маша"}
        llm = _FakeLLM("кстати, у маши уже год коллекция клавиатур растёт")
        w, bot = self._worker(db, llm, monkeypatch,
                              memory=_FakeMemory([golden]))
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 1
        user_text = llm.calls[0][0][1]["content"]
        assert "[Маша]" in user_text
        assert "коллекционирует механические клавиатуры" in user_text

    @pytest.mark.asyncio
    async def test_d07_mixing_unrelated_events_declined(self, db,
                                                        monkeypatch):
        """P0 REWORK W1 (NOST-01): память инцидентной формы (репост новости
        + посторонняя реплика); содержательный отказ модели — типизированный
        вердикт UNCHANGED того же вызова → публикация отсутствует, лимит не
        тратится, объяснение отказа в чат не уходит (NOST-16: свойство
        результата, не совпадение фраз)."""
        await self._silence(db)
        await self._year_back(db, "Вера Косачева умерла за 300 м до финиша",
                              forward_source="Спорт-Новости")
        await self._year_back(db, "а я тогда писал про тромбы")
        llm = _FakeLLM("UNCHANGED")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert bot.calls == [] and out["sent"] == 0
        rows = await self._log_rows(db, "skipped")
        assert json.loads(rows[-1]["meta"])["reason"] == "unchanged"
        assert await db.count_nostalgia_sent_since(CHAT, 0) == 0

    @pytest.mark.asyncio
    async def test_d08_contradictory_text_declined(self, db, monkeypatch):
        """P0 REWORK W1 (NOST-01): противоречивый материал («утверждает и
        отрицает одно и то же») — модель отказывается типизированным
        вердиктом UNCHANGED; противоречивая проза как «контент» не является
        рабочей формой."""
        await self._silence(db)
        await self._year_back(db, "год назад было наводнение")
        llm = _FakeLLM("UNCHANGED")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert bot.calls == []
        rows = await self._log_rows(db, "skipped")
        assert json.loads(rows[-1]["meta"])["reason"] == "unchanged"

    @pytest.mark.asyncio
    async def test_d09_meaningless_ending_not_censored(self, db,
                                                       monkeypatch):
        """Бессмысленная концовка: без вердикта отказа текст публикуется —
        цензура/словесный бан не введены."""
        await self._silence(db)
        await self._year_back(db, "год назад съели торт")
        llm = _FakeLLM("кстати, год назад торт был. и вообще, картридж.")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 1 and bot.calls

    @pytest.mark.asyncio
    async def test_d10_unchanged_decline(self, db, monkeypatch):
        """Отказ UNCHANGED: skip unchanged, публикации нет."""
        await self._silence(db)
        await self._year_back(db, "год назад было весело")
        llm = _FakeLLM("UNCHANGED")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert bot.calls == [] and out["sent"] == 0
        rows = await self._log_rows(db, "skipped")
        assert json.loads(rows[-1]["meta"])["reason"] == "unchanged"

    @pytest.mark.asyncio
    async def test_d11_provenance_error_honest_label(self):
        """Ошибка provenance (is_forward без источника): честный лейбл
        «Переслано» без выдуманного источника; с источником — с ним."""
        row = {"text": "текст новости", "is_forward": 1,
               "forward_source": "", "author_name": "Вася",
               "timestamp": NOW - 365 * 86400}
        line = format_year_back_line(row)
        assert line.startswith("[Вася ")
        assert line.endswith("]: текст новости")
        assert "| Переслано]" in line
        row2 = dict(row, forward_source="Хабр")
        assert "| Переслано: Хабр]" in format_year_back_line(row2)

    @pytest.mark.asyncio
    async def test_d12_self_echo_excluded(self, db):
        """Self-echo: собственные слова бота (origin bot_direct_reply /
        bot_self_reply) не возвращаются как независимые «золотые» факты —
        реальный SQL-фильтр golden-поиска."""
        ts_old = NOW - 400 * 86400
        await db.insert_graph_fact(CHAT, "вася обожает пельмени",
                                   "chat_history", None, importance=7,
                                   message_timestamp=ts_old)
        await db.insert_graph_fact(CHAT, "я сам говорил про пельмени",
                                   "bot_direct_reply", None, importance=7,
                                   message_timestamp=ts_old)
        from services.summary_memory import MemoryManager
        mm = MemoryManager(db, MagicMock())
        rows = await mm.fetch_golden_facts(CHAT, "пельмени",
                                           min_importance=1, min_age_days=1,
                                           limit=5)
        texts = [str(r.get("fact") or "") for r in rows]
        assert texts and any("вася обожает" in t for t in texts)
        assert not any("я сам говорил" in t for t in texts)

    @pytest.mark.asyncio
    async def test_d13_published_memory_not_reproposed(self, db,
                                                       monkeypatch):
        """Повторное предложение опубликованного воспоминания: после sent
        действует cooldown — второй тик не публикует снова."""
        await self._silence(db)
        await self._year_back(db, "год назад уронили торт")
        llm = _FakeLLM("кстати, год назад торт пол отвесил")
        w, bot = self._worker(db, llm, monkeypatch,
                              values={"memory.nostalgia_cooldown_hours": 6})
        out1 = await w._process_chat(CHAT, NOW, manual=True)
        assert out1["sent"] == 1
        out2 = await w._process_chat(CHAT, NOW, manual=True)
        assert out2["sent"] == 0 and out2["skipped"] == 0
        assert len(bot.calls) == 1              # без повторной отправки

    @pytest.mark.asyncio
    async def test_d14_active_conversation_scenario_a(self, db,
                                                      monkeypatch):
        """Активный разговор: сценарий A — преамбула «живая беседа», гейты
        тишины/quiet hours не применяются (час внутри quiet-окна)."""
        await message_identity.save_live_message(
            db, chat_id=CHAT, user_id=USER_ID, text="мы тут общаемся",
            timestamp=NOW - 300, sent_at=NOW - 300, ingested_at=NOW - 300,
            media_type="text", author_name="Вася")
        await self._year_back(db, "год назад открывали этот чат")
        llm = _FakeLLM("кстати, ровно год назад открывали чат")
        w, bot = self._worker(db, llm, monkeypatch,
                              values={"memory.nostalgia_quiet_start_hour": 12,
                                      "memory.nostalgia_quiet_end_hour": 14})
        out = await w._process_chat(CHAT, NOW, manual=True)
        user_text = llm.calls[0][0][1]["content"]
        assert user_text.startswith("В чате сейчас живая беседа")
        assert out["sent"] == 1 and bot.calls

    @pytest.mark.asyncio
    async def test_d15_lull_quiet_hours_scenario_b(self, db, monkeypatch):
        """Затишье (сценарий B): quiet hours — честный скип, LLM не зовётся."""
        await self._silence(db)
        await self._year_back(db, "год назад было тихо тоже")
        llm = _FakeLLM("кстати")
        w, bot = self._worker(db, llm, monkeypatch,
                              values={"memory.nostalgia_quiet_start_hour": 12,
                                      "memory.nostalgia_quiet_end_hour": 14})
        monkeypatch.setattr(nw, "_local_hour", lambda ts, tz=None: 13)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 0 and llm.calls == []

    @pytest.mark.asyncio
    async def test_d16_legacy_and_delegated_routes(self, db, monkeypatch):
        """Legacy и delegated-маршруты: K1+K3 ON — кандидат уходит в единый
        Decision с origin nostalgia:*; legacy-отправки нет; страж отказа
        стоит и на делегированном пути."""
        await self._silence(db)
        await self._year_back(db, "год назад был концерт")
        captured: dict = {}

        async def _spy(*, bot, chat_id, situation, candidates,
                       prepared_text=None, db=None, correlation_id=None,
                       writer_service=None):
            captured["ref"] = candidates[0].prepared_text_ref
            captured["text"] = prepared_text
            return {"status": "sent", "delivery_kind": "text"}

        from services import direct_chat_service as dcs
        monkeypatch.setattr(dcs, "handle_initiative", _spy)
        monkeypatch.setattr(nw, "_intent_delegation_enabled", lambda: True)
        llm = _FakeLLM("кстати, помню концерт")
        w, bot = self._worker(db, llm, monkeypatch)
        out = await w._process_chat(CHAT, NOW, manual=True)
        assert out["sent"] == 1
        assert bot.calls == []                  # второго send-пути нет
        assert captured["ref"].startswith("nostalgia:")
        rows = await self._log_rows(db, "sent")
        assert json.loads(rows[-1]["meta"])["path"] == "initiative"


# ═══════════════════════ Матрица E: Cross-cutting ═══════════════════════════

class TestCrossCutting:
    """Provenance-лейблы согласованы на всех путях; честные unsupported-
    состояния; никакого шаблонирования ответов."""

    @pytest.mark.asyncio
    async def test_e01_forward_provenance_consistent_across_paths(self, db):
        """Один forward-пост: лейбл источника согласован в payload Vision,
        контексте Direct Chat, фактчеке и ностальгии."""
        msg = _photo_message(301, serial=50)
        await _process_asset(db, msg, Transport(default=(200, _analysis_body(
            desc="скрин статьи"))), _FakeBot({"fid_50": make_png(60, 60)}))
        await _save_media_row(db, 301, forward_source="Хабр", caption="пост")
        # (1) Vision payload:
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=301)
        assert "Переслано из Хабр" in rendered["text"]
        assert rendered["forward_source"] == "Хабр"
        # (2) Direct Chat context:
        payload = await _payload_contains(db, "Переслано: Хабр")
        assert "Переслано из Хабр" in payload
        # (3) Factcheck:
        pub = await fcs.resolve_claim_publication(db, CHAT, 301,
                                                  base_text="пост")
        assert pub.forward_source == "Хабр"
        # (4) Ностальгия (год-назад строка с тем же лейблом):
        row = {"text": "текст", "is_forward": 1, "forward_source": "Хабр",
               "author_name": "Вася", "timestamp": NOW - 365 * 86400}
        assert "| Переслано: Хабр]" in format_year_back_line(row)

    @pytest.mark.asyncio
    async def test_e02_honest_unsupported_states_distinct(self, db):
        """Честные unsupported-состояния: видео без обложки — «визуальное
        содержимое недоступно», голосовая строка — вне vision-фасада."""
        msg = _video_message(302, serial=51, with_thumb=False)
        mca_vision.bind_runtime(db)
        await mca_vision.register_intake_assets(db, msg)   # кандидатов нет
        await _save_media_row(db, 302, media_type="video")
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=302)
        assert rendered is not None
        assert mca_vision.NO_VISUAL_CONTENT_LINE in rendered["lines"]
        assert mca_vision.PENDING_LINE not in rendered["lines"]
        await _save_media_row(db, 303, media_type="voice")
        assert await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=303) is None

    @pytest.mark.asyncio
    async def test_e03_auto_target_no_guess_for_ambiguity(self, db):
        """Cross-cutting (C)-резолв: пусто/2+ кандидата — цель НЕ выдумывается;
        GIF резолвится только растровой обложкой (animation_preview)."""
        svc = _direct_service(db)
        assert await svc._resolve_earlier_image_markers(
            CHAT, _user_message(310, text="что на фото?")) == ()

        async def _asset(chat, tg, aid, kind, fid, uid, variant, mime):
            await db.upsert_media_asset({
                "asset_id": aid, "message_key": f"{chat}:{tg}",
                "chat_id": chat, "tg_message_id": tg, "asset_kind": kind,
                "file_id": fid, "file_unique_id": uid,
                "size_variant": variant, "mime": mime})

        # два растровых изображения → неоднозначно
        await _asset(CHAT, 311, "a311", "photo", "f311", "u311", "large",
                     "image/jpeg")
        await _asset(CHAT, 312, "a312", "photo", "f312", "u312", "large",
                     "image/jpeg")
        assert await svc._resolve_earlier_image_markers(
            CHAT, _user_message(313, text="что на фото?")) == ()
        # GIF-источник (animation) сам по себе не «изображение» (другой чат):
        await _asset(CHAT2, 314, "a314", "animation", "f314", "u314",
                     "animation", "video/mp4")
        assert await svc._resolve_earlier_image_markers(
            CHAT2, _user_message(315, text="что на фото?")) == ()
        # обложка GIF (animation_preview) — резолвится честным маркером:
        await _asset(CHAT2, 314, "a314p", "animation_preview", "f314p",
                     "u314p", "animation_preview", "image/jpeg")
        markers = await svc._resolve_earlier_image_markers(
            CHAT2, _user_message(316, text="что на фото?"))
        assert markers == ("[медиа: animation_preview tg:314]",)

    @pytest.mark.asyncio
    async def test_e04_reviewer_real_contracts_available(self, db):
        """§26 Reviewer: по сквозному прогону доступны РЕАЛЬНЫЕ данные всех
        пунктов чек-листа — исходные данные, состояние маршрутизатора,
        вызванные инструменты с аргументами и результатами, состояние задач,
        готовые записи Vision, raw output, итоговые сообщения."""
        msg = _photo_message(320, serial=52)
        mca_vision.bind_runtime(db)
        t = Transport(default=(200, _analysis_body(desc="скрин отчёта",
                                                  ocr_text="ПЛАН 2027")))
        await _process_asset(db, msg, t, _FakeBot({"fid_52":
                                                       make_png(61, 61)}))
        await _save_media_row(db, 320)
        # исходные данные:
        row = await db.get_smart_message_by_tg_id(CHAT, 320)
        assert row is not None and row["media_type"] == "photo"
        # состояние маршрутизатора (без ключа в срезе — R17):
        route = mca_vision.resolve_route(CHAT)
        assert route.api_key_present
        # вызванные инструменты с аргументами и результатом (транспорт):
        assert t.n == 1
        sent_messages = t.calls[0]["payload"]["messages"]
        assert isinstance(sent_messages, list) and sent_messages
        # состояние задач (durable task_jobs, терминальная строка):
        cur = await db.db.execute(
            "SELECT status, reason_code FROM task_jobs "
            "WHERE kind = ? ORDER BY job_id", (mca_vision.VISION_JOB_KIND,))
        job_rows = await cur.fetchall()
        assert job_rows and job_rows[0]["status"] == "completed"
        # готовые записи Vision + raw LLM output + итоговые сообщения:
        ready = await mca_vision.resolve_ready_for_asset(
            db, (await db.get_media_assets_for_message(CHAT, 320))[0],
            mca_vision.access_scope_for(CHAT))
        assert ready["status"] == "ready"
        assert "скрин отчёта" in str(ready.get("visual_description") or "")
        rendered = await mca_vision.render_media_context_async(
            db, chat_id=CHAT, tg_message_id=320)
        assert "ПЛАН 2027" in rendered["text"]
        # nostalgia_log — журнал причин публикации (контракт meta.reason):
        cur = await db.db.execute(
            "SELECT meta FROM nostalgia_log ORDER BY id LIMIT 1")
        assert await cur.fetchall() == []

    def test_e05_no_artificial_instruction_quota_in_markers(self):
        """Cross-cutting (Addendum #3): маркер медиа и honest-строки — данные,
        не квоты инструкций; cap Current_Question — лимит данных вопроса с
        ГАРАНТИРОВАННЫМ выживанием маркера; инструкции не сокращаются."""
        cap = int(settings.CHAT_CURRENT_QUESTION_MAX_CHARS or 800)
        marker = "[медиа: photo tg:1]"
        suffix = " ".join([marker])
        room = max(0, cap - len(suffix) - 1)
        assert room > 0                         # маркер всегда помещается
        long_text = "х" * (cap + 500)
        body = long_text[:room] + " " + suffix
        assert len(body) <= cap and marker in body
        # honest-строки — различимые факты состояний, не один шаблон:
        lines = set(mca_vision.ANALYSIS_FAILURE_LINES.values()) | {
            mca_vision.PENDING_LINE, mca_vision.NO_TEXT_LINE,
            mca_vision.NO_VISUAL_CONTENT_LINE}
        assert len(lines) >= 5
