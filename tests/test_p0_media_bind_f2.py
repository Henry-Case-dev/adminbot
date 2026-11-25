"""P0 MEDIA-BINDING F2 — одно намерение на медиа-сообщение и авторство медиа.

Причина C2 (планы: `plans/features/unified-reply/evidence/
p0-media-binding-diagnosis-2026-11-26.md`): `media_readiness.
link_pending_intent_for_message` связывал ЛЮБОЕ следующее медиа чата с
новейшим ожидающим намерением — без идентичности сообщения и без проверки
автора. Приём одного фото вызывает функцию ДВАЖДЫ
(`mca_vision.register_intake_assets` и `mca_vision.enqueue_intake_jobs`,
оба из `handlers/summary.py`), поэтому одно фото связывалось с двумя
намерениями и отвечало дважды; фото другого автора приписывалось чужому
запросу.

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=P0-MEDIA-BINDING-F2.
Границы: без Telegram, без сети. Vision-транспорт не вызывается — анализ
записывается готовым (как после обработки воркером).
"""
from __future__ import annotations

import datetime as _dt

import pytest
import pytest_asyncio
from aiogram.types import Chat, Message, PhotoSize, User

from config.settings import settings
from services import hot_config as hot
from services import mca_vision
from services import media_readiness as mr
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore

pytestmark = [pytest.mark.asap3]

CHAT = -1009000100
USER_ID = 4242
FOREIGN_ID = 777
BOT_ID = 999000111
VISION_BASE = "http://vlm.local/v1"


@pytest.fixture(autouse=True)
def _vision_enabled():
    mca_vision.reset_capability_cache()
    mca_vision.reset_route_param_memo()
    hot.set_config_cache(None)
    saved = {k: getattr(settings, k) for k in (
        "VISION_ENABLED", "VISION_API_BASE_URL", "VISION_MODEL",
        "VISION_API_KEY", "VISION_API_TYPE")}
    for key, value in {
            "VISION_ENABLED": True,
            "VISION_API_BASE_URL": VISION_BASE,
            "VISION_MODEL": "test-vlm",
            "VISION_API_KEY": "test-key",
            "VISION_API_TYPE": "openai_compatible"}.items():
        object.__setattr__(settings, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            object.__setattr__(settings, key, value)
        mca_vision.reset_capability_cache()
        mca_vision.reset_route_param_memo()
        mr.set_resume_handler(None)
        hot.set_config_cache(None)


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "media-bind-f2.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


# ── обвязка ────────────────────────────────────────────────────────────────

def _photo_message(tg_id: int, serial: int = 1, *, chat_id: int = CHAT,
                   user_id: int = USER_ID, is_bot: bool = False) -> Message:
    """Реальное aiogram-сообщение с фото (intake-путь, без сети)."""
    return Message(
        message_id=int(tg_id),
        date=_dt.datetime(2026, 11, 26, 12, 0, 0, tzinfo=_dt.timezone.utc),
        chat=Chat(id=int(chat_id), type="supergroup", title="T"),
        from_user=User(id=int(user_id), is_bot=is_bot, first_name="Сергей"),
        photo=[PhotoSize(file_id=f"fid_{serial}", file_unique_id=f"uniq_{serial}",
                         width=800, height=600, file_size=12345)])


async def _ready_analysis(db, asset_id: str, *, text: str = "фото: грилзы",
                          chat_id: int = CHAT):
    analysis_id = await db.record_media_analysis({
        "asset_id": asset_id,
        "access_scope": mca_vision.access_scope_for(chat_id),
        "analysis_schema_version": mca_vision.ANALYSIS_SCHEMA_VERSION,
        "analyzer_provider": "dedicated", "analyzer_model": "test-vlm",
        "analyzer_config_revision": "cfg1",
        "prompt_version": mca_vision.PROMPT_VERSION,
        "quality_profile": mca_vision.QUALITY_PROFILE_DEFAULT,
        "status": "running", "config_revision": "cfg1", "revision": 1})
    await db.finish_media_analysis(
        analysis_id, expected_revision=1, status="ready",
        ocr_blocks=[{"text": text, "channel": "untrusted_data"}],
        visual_description="фото: грилзы, VHS-эффекты")
    return analysis_id


async def _intent_states(db, chat_id: int = CHAT) -> list[dict]:
    """Активные намерения чата: триггер, автор запроса и фактическая ссылка."""
    out = []
    for job in await mr._load_intents(db, chat_id):
        payload = mr._intent_payload(job)
        linked = payload.get("linked") or {}
        out.append({
            "trigger": int(payload.get("trigger_message_id") or 0),
            "user_id": payload.get("user_id"),
            "linked_tg": int(linked.get("tg_message_id") or 0),
            "asset_ids": [str(a) for a in (linked.get("asset_ids") or [])],
        })
    return out


async def _register_intent(db, trigger: int, *, user_id=None,
                           question: str = "сейчас скину фото, разбери"):
    return await mr.register_pending_intent(
        db, chat_id=CHAT, trigger_message_id=int(trigger), consumer="direct",
        question=question, user_id=user_id, ttl_seconds=600)


# ── (a) одно фото + два намерения → одна привязка и один ответ ─────────────

@pytest.mark.asyncio
async def test_f2_one_photo_two_intents_links_once_and_resumes_once(db):
    """Одно фото при двух ожидающих запросах: связывается РОВНО одно
    намерение (второй вызов шва приёма — no-op) и уходит РОВНО один ответ."""
    await _register_intent(db, 9001, user_id=USER_ID, question="первый запрос")
    await _register_intent(db, 9002, user_id=USER_ID, question="второй запрос")
    assert len(await _intent_states(db)) == 2

    msg = _photo_message(9500, serial=1, user_id=USER_ID)
    assets = await mca_vision.register_intake_assets(db, msg)   # шов #1
    assert assets
    await mca_vision.enqueue_intake_jobs(db, msg, list(assets))  # шов #2

    states = await _intent_states(db)
    linked = [s for s in states if s["linked_tg"] == 9500]
    assert len(linked) == 1, f"одно фото связало {len(linked)} намерения"
    assert linked[0]["asset_ids"] == assets
    assert [s["trigger"] for s in states
            if s["linked_tg"] == 0], "второе намерение осталось ждать"

    await _ready_analysis(db, assets[0], text="фото: бриллиантовые грилзы")
    calls: list = []

    async def _handler(intent_payload, states, bot):
        calls.append(dict(intent_payload))
        return True

    mr.set_resume_handler(_handler)
    worker = mca_vision.VisionMediaWorker(db, None)
    worker._store = TaskJobStore(db)
    await worker._resume_intents()
    await worker._resume_intents()          # повторный проход — no-op

    assert len(calls) == 1, f"sweep доставил {len(calls)} ответа на одно фото"
    assert calls[0]["trigger_message_id"] == linked[0]["trigger"]
    assert calls[0]["tg_message_id"] == 9500


# ── (b) два вызова шва приёма подряд → одна привязка ───────────────────────

@pytest.mark.asyncio
async def test_f2_link_is_idempotent_per_media_message(db):
    """Второй вызов `link_pending_intent_for_message` для того же
    tg_message_id ничего не связывает (первый вызов уже выиграл)."""
    await _register_intent(db, 9101, user_id=USER_ID)
    await _register_intent(db, 9102, user_id=USER_ID)

    first = await mr.link_pending_intent_for_message(
        db, chat_id=CHAT, tg_message_id=9150, media_group_id=None,
        asset_ids=["asset-a"])
    assert first is not None and first["tg_message_id"] == 9150

    second = await mr.link_pending_intent_for_message(
        db, chat_id=CHAT, tg_message_id=9150, media_group_id=None,
        asset_ids=["asset-b"])
    assert second is None

    linked = [s for s in await _intent_states(db) if s["linked_tg"] == 9150]
    assert len(linked) == 1
    assert linked[0]["asset_ids"] == ["asset-a"]


# ── (c) фото чужого автора не приписывается запросу ───────────────────────

@pytest.mark.asyncio
async def test_f2_foreign_author_photo_does_not_link_asker_intent(db):
    """Фото от другого участника не закрывает «сейчас скину» автора запроса."""
    await _register_intent(db, 9201, user_id=USER_ID)

    foreign = _photo_message(9250, serial=7, user_id=FOREIGN_ID)
    assets = await mca_vision.register_intake_assets(db, foreign)
    assert assets
    assert [s for s in await _intent_states(db)
            if s["linked_tg"] == 9250] == []

    direct = await mr.link_pending_intent_for_message(
        db, chat_id=CHAT, tg_message_id=9251, asset_ids=["asset-f"],
        author_user_id=FOREIGN_ID)
    assert direct is None
    assert all(s["linked_tg"] == 0 for s in await _intent_states(db))


# ── (d) собственное фото автора связывается штатно ────────────────────────

@pytest.mark.asyncio
async def test_f2_own_author_photo_links_normally(db):
    """Фото автора запроса связывается как прежде — фикс не ломает
    продуктовый сценарий «просьба → фото позже»."""
    await _register_intent(db, 9301, user_id=USER_ID)
    own = _photo_message(9350, serial=8, user_id=USER_ID)
    assets = await mca_vision.register_intake_assets(db, own)
    assert assets

    states = await _intent_states(db)
    linked = [s for s in states if s["linked_tg"] == 9350]
    assert len(linked) == 1
    assert linked[0]["trigger"] == 9301
    assert linked[0]["asset_ids"] == assets


@pytest.mark.asyncio
async def test_f2_unknown_author_keeps_structural_link(db):
    """Неизвестное авторство (с любой стороны) не выдумывает запрет:
    поведение остаётся структурным, как у `_same_author`."""
    await _register_intent(db, 9401, user_id=USER_ID)
    no_author = await mr.link_pending_intent_for_message(
        db, chat_id=CHAT, tg_message_id=9450, asset_ids=["asset-u"],
        author_user_id=None)
    assert no_author is not None and no_author["trigger_message_id"] == 9401

    # Намерение без user_id (legacy) — автор медиа известен, запрета нет.
    await _register_intent(db, 9402, user_id=None)
    legacy = await mr.link_pending_intent_for_message(
        db, chat_id=CHAT, tg_message_id=9451, asset_ids=["asset-v"],
        author_user_id=USER_ID)
    assert legacy is not None and legacy["trigger_message_id"] == 9402


# ── (e) изображение, сгенерированное ботом, не закрывает запрос ───────────

@pytest.mark.asyncio
async def test_f2_bot_generated_image_does_not_satisfy_pending_request(db):
    """Собственный медиа-вывод бота (from_user.id = bot) не связывается с
    ожидающим запросом участника; запрос остаётся открыт до фото участника."""
    await _register_intent(db, 9501, user_id=USER_ID)

    bot_photo = _photo_message(9550, serial=9, user_id=BOT_ID, is_bot=True)
    bot_assets = await mca_vision.register_intake_assets(db, bot_photo)
    assert bot_assets
    assert all(s["linked_tg"] == 0 for s in await _intent_states(db))

    own = _photo_message(9551, serial=10, user_id=USER_ID)
    own_assets = await mca_vision.register_intake_assets(db, own)
    assert own_assets
    states = await _intent_states(db)
    linked = [s for s in states if s["linked_tg"] == 9551]
    assert len(linked) == 1 and linked[0]["trigger"] == 9501
