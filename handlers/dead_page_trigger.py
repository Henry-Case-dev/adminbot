import logging
import time
from collections import OrderedDict

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import MessageOriginChannel
from config.settings import settings
from services import hot_config as hot
from filters.user_id import UserIdFilter

logger = logging.getLogger(__name__)

# ── Media group deduplication (Epic 14) ──
_seen_media_groups: OrderedDict[str, float] = OrderedDict()
# M1 (review-fix): bot_msg_ids, отправленные для первого сообщения альбома, —
# чтобы записать маппинг и для последующих (дедуп скипает отправку, но маппинг
# должен существовать для ВСЕХ элементов — reply на удалённый 2-й элемент).
_media_group_bot_ids: dict[str, list[int]] = {}
# B1 (review-fix): aiogram с handle_as_tasks=True обрабатывает апдейты альбома
# конкурентно (asyncio.create_task на каждый апдейт) — 2-й+ элемент может
# попасть в dedup-ветку, пока первый ещё внутри send_dead_page (медленный
# сетевой вызов), и _media_group_bot_ids ещё не записан. Копим message_id в
# pending-структуру; первый элемент после send_dead_page допишет маппинг
# и для них. TTL/эвикция — та же, что у _seen_media_groups.
_pending_media_group_ids: dict[str, list[int]] = {}
_MEDIA_GROUP_DEDUP_TTL = 5  # seconds
_MAX_DEDUP_ENTRIES = 100


def _cleanup_expired_media_groups():
    """Remove expired entries to prevent unbounded memory growth."""
    now = time.monotonic()
    expired = [k for k, v in _seen_media_groups.items() if now - v > _MEDIA_GROUP_DEDUP_TTL]
    for k in expired:
        del _seen_media_groups[k]
        _media_group_bot_ids.pop(k, None)
        _pending_media_group_ids.pop(k, None)


dead_page_router = Router()

_relay = None
_db = None


def setup_dead_page(relay, db):
    """Inject DeadPageRelay + DatabaseService.

    Epic 22 / D53: is_present-гейт убран — репост Славы сам по себе означает,
    что Слава в чате. Epic 52 (T-417): db используется для записи маппинга
    «репост Славы → dead page бота» (dead_page_repost_map).
    """
    global _relay, _db
    _relay = relay
    _db = db


@dead_page_router.message(
    F.forward_origin,
    # N3 (ЧЕСТНО): импорт-time декоратор — значение из админки НЕ применяется
    # без рефакторинга фильтра; на каждом старте — фолбек settings.
    UserIdFilter(hot.get("reactions.slavik_user_id", settings.SLAVIK_USER_ID)),  # D53: только репосты Славы
)
async def on_forward(message: types.Message):
    origin = message.forward_origin
    
    if not isinstance(origin, MessageOriginChannel):
        logger.debug(f"Forward origin is not a channel: {type(origin).__name__}")
        return UNHANDLED
    
    source_username = hot.get("reactions.dead_page_source_channel_username", settings.DEAD_PAGE_SOURCE_CHANNEL_USERNAME)
    source_id = hot.get("reactions.dead_page_source_channel_id", settings.DEAD_PAGE_SOURCE_CHANNEL_ID)
    
    is_target = False
    
    if source_username and origin.chat.username == source_username:
        is_target = True
        logger.info(
            f"Detected repost from @{source_username} "
            f"in chat {message.chat.id} (by username match)"
        )
    
    if source_id and origin.chat.id == source_id:
        is_target = True
        logger.info(
            f"Detected repost from channel ID {source_id} "
            f"in chat {message.chat.id} (by ID match)"
        )
    
    if not is_target:
        return UNHANDLED

    # ── Epic 14: Deduplicate media group forwards ──
    _cleanup_expired_media_groups()
    if message.media_group_id:
        now = time.monotonic()
        if message.media_group_id in _seen_media_groups:
            logger.debug(
                f"[dead_page] Dedup skip: media_group_id={message.media_group_id}"
            )
            # M1 (review-fix): дедуп скипает ПОВТОРНУЮ отправку, но маппинг
            # {репост → dead page бота} пишем и для этого элемента альбома —
            # иначе reply на удалённый 2-й элемент не найдёт маппинга.
            if _db is not None:
                bot_ids = _media_group_bot_ids.get(message.media_group_id)
                if bot_ids:
                    try:
                        await _db.record_dead_page_repost_map(
                            message.chat.id, message.message_id, bot_ids
                        )
                    except Exception:
                        logger.warning(
                            "[dead_page] record_dead_page_repost_map failed (dedup) | "
                            "chat=%s | repost_msg_id=%s",
                            message.chat.id, message.message_id,
                            exc_info=True,
                        )
                else:
                    # B1: маппинга ещё нет — первый элемент альбома всё ещё в
                    # send_dead_page (конкурентная обработка handle_as_tasks).
                    # Копим message_id: первый элемент допишет маппинг после
                    # send_dead_page (для своего id И для всех pending).
                    _pending_media_group_ids.setdefault(
                        message.media_group_id, []
                    ).append(message.message_id)
            return
        _seen_media_groups[message.media_group_id] = now
        # LRU eviction: remove oldest if over limit
        if len(_seen_media_groups) > _MAX_DEDUP_ENTRIES:
            oldest_key, _ = _seen_media_groups.popitem(last=False)
            _media_group_bot_ids.pop(oldest_key, None)
            _pending_media_group_ids.pop(oldest_key, None)

    # ── D53 (Epic 22): is_present-гейт УДАЛЁН ──
    # Репост Славы сам по себе означает, что Слава в чате.
    # _db используется ниже для записи маппинга dead_page_repost_map (T-417).

    if _relay is None:
        logger.error("DeadPageRelay not initialized — cannot send dead page")
        return

    chat_id = message.chat.id

    # T-417 (Epic 52, Section 61.6.2): записываем маппинг {репост → dead page бота}.
    # send_dead_page возвращает id сообщений бота В ГРУППЕ (list[int]).
    bot_msg_ids = await _relay.send_dead_page(chat_id, slot="repost")
    if bot_msg_ids and _db is not None:
        try:
            await _db.record_dead_page_repost_map(chat_id, message.message_id, bot_msg_ids)
            # M1: сохраняем bot_ids для последующих элементов альбома (маппинг
            # пишется для всех, не только для первого сообщения группы).
            if message.media_group_id:
                _media_group_bot_ids[message.media_group_id] = bot_msg_ids
                # B1: flush pending message_id — элементы альбома, пришедшие
                # в dedup-ветку, пока send_dead_page был в полёте (конкурентная
                # обработка). Маппинг дописывается и для них.
                pending = _pending_media_group_ids.pop(message.media_group_id, None)
                if pending:
                    for pending_id in pending:
                        try:
                            await _db.record_dead_page_repost_map(
                                chat_id, pending_id, bot_msg_ids
                            )
                        except Exception:
                            logger.warning(
                                "[dead_page] record_dead_page_repost_map failed (pending) | "
                                "chat=%s | repost_msg_id=%s",
                                chat_id, pending_id,
                                exc_info=True,
                            )
        except Exception:
            logger.warning(
                "[dead_page] record_dead_page_repost_map failed | chat=%s | repost_msg_id=%s",
                chat_id, message.message_id,
                exc_info=True,
            )
