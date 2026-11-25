"""P0 26.11 — MEDIA BINDING F1: «своё медиа» = визуальный актив, не токен.

Cause C1 (`plans/features/unified-reply/evidence/p0-media-binding-diagnosis-
2026-11-26.md`): `_prepare_turn_media_evidence` объявлял любой транспортный
медиа-токен (audio/voice/PDF-документ) «своей картинкой», `is_media_dependent`
возвращал True, `resolve_target_media` не находил актива (обложка трека — не
актив), и Direct безусловно создавал durable-намерение «жду изображение»,
которое позже связывалось с посторонним фото и давало ответ описанием фото на
пересланный трек.

Контракт (owner input 2026-11-26 §4, F1): own_media/reply_media считаются тем
же предикатом, что и канонический реестр Vision
(`mca_vision.extract_image_assets`).

Границы: без Telegram, без сети, без LLM. Проверяется шов
`DirectChatService._prepare_turn_media_evidence` и существующий путь
«просьба → фото позже» (намерение/привязка/sweep).

TEST-LIFECYCLE: REGRESSION owner=P0-MEDIA-F1 (owner input 2026-11-26 §4,
diagnosis C1; `plans/features/unified-reply/evidence/
p0-media-phantom-intent-2026-11-26.md`).
"""
from __future__ import annotations

import datetime as _dt
import time
from contextlib import contextmanager

import pytest
import pytest_asyncio

from aiogram.types import (Animation, Audio, Chat, Document, Message,
                           PhotoSize, Sticker, User, Video, Voice)

from config.settings import settings
from services import hot_config as hot
from services import mca_vision
from services import media_readiness as mr
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService, _message_user_text

CHAT = -1005555001
USER_ID = 4242
AD_CAPTION = "Нажми чтобы найти песню\nСкидочный бот"

pytestmark = [pytest.mark.asap3]


@contextmanager
def patched_settings(**kw):
    saved = {k: getattr(settings, k) for k in kw}
    for key, value in kw.items():
        object.__setattr__(settings, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            object.__setattr__(settings, key, value)


@pytest.fixture(autouse=True)
def _vision_enabled():
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)
    with patched_settings(VISION_ENABLED=True):
        yield
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "p0-media-f1.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


@pytest.fixture
def service(db):
    class _LLM:
        async def generate(self, *a, **k):      # pragma: no cover - не зовётся
            return ""

    return DirectChatService(memory=None, db=db, llm=_LLM(), aliases=None)


# ── обвязка сообщений (aiogram 3, как в существующих vision-тестах) ─────────

def _thumb(serial: int) -> PhotoSize:
    return PhotoSize(file_id=f"thumb_f{serial}",
                     file_unique_id=f"thumb_u{serial}",
                     width=320, height=240, file_size=1000)


def _base(tg_id, *, user_id=USER_ID, **kwargs) -> Message:
    return Message(
        message_id=tg_id,
        date=_dt.datetime(2026, 11, 26, 12, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=CHAT, type="supergroup", title="T"),
        from_user=User(id=user_id, is_bot=False, first_name="Сергей"),
        **kwargs)


def _audio_track(tg_id, *, caption=AD_CAPTION, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id, caption=caption,
                 audio=Audio(file_id=f"aud_f{tg_id}",
                             file_unique_id=f"aud_u{tg_id}",
                             duration=180, title="track", performer="artist",
                             file_size=4_000_000))


def _voice(tg_id, *, caption=None, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id, caption=caption,
                 voice=Voice(file_id=f"voi_f{tg_id}",
                             file_unique_id=f"voi_u{tg_id}",
                             duration=7, file_size=20_000))


def _pdf(tg_id, *, caption="документ", user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id, caption=caption,
                 document=Document(file_id=f"pdf_f{tg_id}",
                                   file_unique_id=f"pdf_u{tg_id}",
                                   file_name="doc.pdf", mime_type="application/pdf",
                                   file_size=3_000))


def _photo(tg_id, *, serial=1, caption=None, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id, caption=caption,
                 photo=[PhotoSize(file_id=f"ph_f{serial}",
                                  file_unique_id=f"ph_u{serial}",
                                  width=800, height=600, file_size=12_345)])


def _sticker(tg_id, *, serial=2, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id,
                 sticker=Sticker(file_id=f"st_f{serial}",
                                 file_unique_id=f"st_u{serial}",
                                 width=512, height=512, type="regular",
                                 is_animated=False, is_video=False))


def _image_document(tg_id, *, serial=3, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id,
                 document=Document(file_id=f"imgdoc_f{serial}",
                                   file_unique_id=f"imgdoc_u{serial}",
                                   file_name="pic.jpg", mime_type="image/jpeg",
                                   file_size=3_000))


def _animation(tg_id, *, serial=4, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id,
                 animation=Animation(file_id=f"gif_f{serial}",
                                     file_unique_id=f"gif_u{serial}",
                                     width=320, height=240, duration=3,
                                     mime_type="video/mp4",
                                     thumbnail=_thumb(serial)))


def _video(tg_id, *, serial=5, with_thumb=True, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id,
                 video=Video(file_id=f"vid_f{serial}",
                             file_unique_id=f"vid_u{serial}",
                             width=1280, height=720, duration=10,
                             file_size=900_000,
                             thumbnail=(_thumb(serial) if with_thumb else None)))


def _text(tg_id, text, *, user_id=USER_ID) -> Message:
    return _base(tg_id, user_id=user_id, text=text)


# ── обвязка реестра/анализа/доставки ───────────────────────────────────────

async def _ready_analysis(db, asset_id: str, *, text="описание фото"):
    analysis_id = await db.record_media_analysis({
        "asset_id": asset_id,
        "access_scope": mca_vision.access_scope_for(CHAT),
        "analysis_schema_version": mca_vision.ANALYSIS_SCHEMA_VERSION,
        "analyzer_provider": "dedicated", "analyzer_model": "test-vlm",
        "analyzer_config_revision": "cfg1",
        "prompt_version": mca_vision.PROMPT_VERSION,
        "quality_profile": mca_vision.QUALITY_PROFILE_DEFAULT,
        "status": "running", "config_revision": "cfg1", "revision": 1})
    await db.finish_media_analysis(
        analysis_id, expected_revision=1, status="ready",
        ocr_blocks=[{"text": text, "channel": "untrusted_data"}],
        visual_description=text)
    return analysis_id


async def _intents(db):
    return await mr._load_intents(db, CHAT)


async def _deliveries(db):
    sent: list = []

    async def _resume(intent, states):
        sent.append((intent["trigger_message_id"], intent["tg_message_id"]))
        return True

    summary = await mr.resume_deferred_requests(db, chat_id=CHAT,
                                                resume=_resume)
    return sent, summary


# ── (a) пересланный трек с рекламной подписью — фантомного намерения нет ────

@pytest.mark.asyncio
async def test_forwarded_audio_creates_no_phantom_intent(service, db):
    """3 пересланных трека → ни одного намерения «жду изображение».

    RED на базе: readiness=('missing', True) ×3 и 3 pending intent (C1)."""
    observed = []
    for tg_id in (9001, 9002, 9003):
        message = _audio_track(tg_id)
        readiness = await service._prepare_turn_media_evidence(
            CHAT, message, query=_message_user_text(message),
            correlation_id=f"p{tg_id}")
        observed.append(None if readiness is None
                        else (readiness.association_status,
                              readiness.media_dependent))
    assert observed == [None, None, None], observed
    assert await _intents(db) == [], "аудио не должно создавать намерение"


@pytest.mark.asyncio
async def test_forwarded_audio_is_not_answered_with_unrelated_photo(service, db):
    """Позднее постороннее фото не возобновляет «запрос» из пересланного трека.

    RED на базе: 2 доставки reply_to=трек с описанием фото (C1+C2)."""
    for tg_id in (9101, 9102, 9103):
        message = _audio_track(tg_id)
        assert await service._prepare_turn_media_evidence(
            CHAT, message, query=_message_user_text(message),
            correlation_id=f"q{tg_id}") is None
    assert await _intents(db) == []

    photo = _photo(9500, serial=500)
    assets = await mca_vision.register_intake_assets(db, photo)
    assert assets, "фото должно попасть в канонический реестр"
    await mca_vision.enqueue_intake_jobs(db, photo, list(assets))
    for asset_id in assets:
        await _ready_analysis(db, asset_id)

    sent, summary = await _deliveries(db)
    assert sent == [], f"ответ на трек описанием чужого фото: {sent}"
    assert summary["resumed"] == 0, summary


# ── (b) визуальные медиа — паритет прежнего поведения ───────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory,caption,tg_id",
    [
        (_photo, "смотри", 9601),
        (_sticker, None, 9602),
        (_image_document, "скан", 9603),
        (_animation, None, 9604),
        (_video, "видео", 9605),
    ],
    ids=["photo", "sticker", "image_document", "animation",
         "video_preview"],
)
async def test_visual_media_stays_media_dependent(service, db, factory,
                                                 caption, tg_id):
    """Фото/стикер/image-документ/animation/превью видео остаются зависимыми
    и (пока цели в реестре нет) сохраняют одно намерение — как на базе."""
    message = factory(tg_id)
    # Предикат реестра действительно находит визуальный актив.
    assert mca_vision.extract_image_assets(message), "ожидался визуальный актив"

    readiness = await service._prepare_turn_media_evidence(
        CHAT, message, query=caption or "", correlation_id="vis")
    assert readiness is not None, "визуальный ход не должен терять readiness"
    assert readiness.media_dependent is True
    assert readiness.association_status == mr.ASSOC_MISSING  # цели ещё нет
    intents = await _intents(db)
    assert len(intents) == 1
    payload = mr._intent_payload(intents[0])
    assert payload["trigger_message_id"] == tg_id
    assert payload["consumer"] == "direct"


# ── (c) voice/PDF — не медиа-зависимы, намерения нет ───────────────────────

@pytest.mark.asyncio
async def test_voice_and_pdf_create_no_intent(service, db):
    for message in (_voice(9701), _pdf(9702)):
        readiness = await service._prepare_turn_media_evidence(
            CHAT, message, query=_message_user_text(message),
            correlation_id="voice-pdf")
        assert readiness is None
    assert await _intents(db) == []


@pytest.mark.asyncio
async def test_video_without_preview_has_no_visual_asset(service, db):
    """Граница предиката: видео без превью = нет визуального актива, значит
    и нет «зависимости от картинки» (фантомное намерение не создаётся)."""
    message = _video(9750, serial=750, with_thumb=False)
    assert mca_vision.extract_image_assets(message) == []
    readiness = await service._prepare_turn_media_evidence(
        CHAT, message, query="видео", correlation_id="video-no-thumb")
    assert readiness is None
    assert await _intents(db) == []


# ── (d) «просьба текстом → фото позже» сохраняется ─────────────────────────

@pytest.mark.asyncio
async def test_text_request_then_photo_still_resumes_once(service, db):
    """Текстовая просьба разобрать изображение создаёт намерение; пришедшее
    фото связывается и отвечает ровно один раз на сообщение-просьбу."""
    request = _text(9800, "бот, разбери скрин, сейчас скину")
    readiness = await service._prepare_turn_media_evidence(
        CHAT, request, query=_message_user_text(request),
        correlation_id="d-request")
    assert readiness is not None
    assert readiness.association_status == mr.ASSOC_MISSING
    assert readiness.media_dependent is True
    intents = await _intents(db)
    assert len(intents) == 1
    assert mr._intent_payload(intents[0])["trigger_message_id"] == 9800

    photo = _photo(9801, serial=801)
    assets = await mca_vision.register_intake_assets(db, photo)
    assert assets
    await mca_vision.enqueue_intake_jobs(db, photo, list(assets))
    linked = mr._intent_payload((await _intents(db))[0]).get("linked") or {}
    assert linked.get("tg_message_id") == 9801
    for asset_id in assets:
        await _ready_analysis(db, asset_id, text="Скрин: перевод 15 000")

    sent, summary = await _deliveries(db)
    assert sent == [(9800, 9801)], sent
    assert summary["resumed"] == 1, summary
    sent_again, summary_again = await _deliveries(db)
    assert sent_again == [], "повторный sweep не должен дублировать ответ"
    assert summary_again["resumed"] == 0, summary_again


@pytest.mark.asyncio
async def test_reply_to_audio_is_not_own_image_media(service, db):
    """Reply без собственного текста на пересланный трек — не «картинка».

    RED на базе: reply_media=audio → is_media_dependent=True → phantom intent."""
    parent = _audio_track(9900)
    message = _base(9901, reply_to_message=parent)      # ни text, ни caption
    assert _message_user_text(message) == ""
    readiness = await service._prepare_turn_media_evidence(
        CHAT, message, query=_message_user_text(message),
        correlation_id="reply-audio")
    assert readiness is None
    assert await _intents(db) == []


@pytest.mark.asyncio
async def test_reply_to_photo_stays_media_dependent(service, db):
    """Reply без текста на ФОТО остаётся зависимым от изображения (паритет)."""
    parent = _photo(9910, serial=910)
    message = _base(9911, reply_to_message=parent)
    readiness = await service._prepare_turn_media_evidence(
        CHAT, message, query=_message_user_text(message),
        correlation_id="reply-photo")
    assert readiness is not None
    assert readiness.media_dependent is True
    intents = await _intents(db)
    assert len(intents) == 1
    assert mr._intent_payload(intents[0])["trigger_message_id"] == 9911
