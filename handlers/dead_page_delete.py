"""Epic 52 (T-417) — dead page delete detection via InaccessibleMessage (R52-8, D214).

Bot API НЕ присылает боту update об удалении сообщений в группах. Детект —
пассивный: когда кто-то делает reply/quote на УДАЛЁННЫЙ репост Славика,
входящий update несёт reply_to_message = InaccessibleMessage (date == 0,
поля from_user НЕТ — подтверждено в aiogram 3.29.1).

При срабатывании (есть маппинг в dead_page_repost_map):
  (а) бот удаляет СВОИ dead page (delete_message по id из маппинга);
  (б) при 403/Forbidden — отправляет ОДНУ токсичную фразу с reply на вызвавшее
      сообщение (пул DEAD_PAGE_DELETE_PHRASES).
Классификация ошибок delete_message (Section 61.9 risk table):
  - 403 (TelegramForbiddenError) → фраза, маппинг снят атомарным claim'ом (M2);
  - 400 «message can't be deleted» / 404 (TelegramNotFound) → идемпотентно
    удалён, БЕЗ фразы, маппинг снят (H1);
  - 5xx / сетевые / 429 (TelegramServerError, TelegramNetworkError,
    TelegramRetryAfter) → транзиентные: маппинг НЕ снимаем, следующий reply
    перепробует (M3);
  - прочие TelegramAPIError → маппинг сохраняем (не теряем безвозвратно).
Возвращает UNHANDLED если маппинга нет (пропагация живёт), None при срабатывании
(consume — иначе slavik_router дал бы «пошёл нахуй» на реплику Славы).
"""
import logging
import random

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InaccessibleMessage

logger = logging.getLogger(__name__)

dead_page_delete_router = Router(name="dead_page_delete")

_db = None
_bot_id = None

# Пул токсичных фраз (стиль «пошёл нахуй»-семейства, упоминание удаления репоста)
DEAD_PAGE_DELETE_PHRASES = [
    "снёс репост мёртвой страницы? стыдно стало?",
    "удалил репост — испугался мёртвой страницы?",
    "что, репост сам удалился? мёртвые страницы так просто не умирают",
    "снёс свою dead page, как будто её и не было? она ещё припомнит",
    "удалил репост мёртвой страницы? не живи долго",
]


def setup_dead_page_delete(db, bot_id: int | None = None) -> None:
    """DI. Вызывается из bot.py on_startup (позиция 4a)."""
    global _db, _bot_id
    _db = db
    _bot_id = bot_id


@dead_page_delete_router.message()
async def dead_page_delete_handler(message: types.Message) -> None:
    """Реакция на reply/quote к удалённому dead-page репосту Славика.

    Цепочка возвратов (Section 61.6.4 + H1/M2/M3 review-fix):
      1. reply_to нет или это живое сообщение (есть from_user) → UNHANDLED.
      2. reply_to — не InaccessibleMessage (date != 0) → UNHANDLED.
      3. свои сообщения бота → UNHANDLED.
      4. маппинга в БД нет → UNHANDLED (пропагация живёт).
      5. срабатывание:
         - delete_message успех → маппинг снят → None;
         - 403 → атомарный claim + ОДНА фраза → None;
         - 400/404 → идемпотентно удалён, БЕЗ фразы, маппинг снят → None;
         - 5xx/сетевые/429 → маппинг СОХРАНЁН → None;
         - прочие TelegramAPIError → маппинг СОХРАНЁН → None.
    """
    reply_to = message.reply_to_message
    if reply_to is None:
        return UNHANDLED
    reply_from = getattr(reply_to, "from_user", None)
    if reply_from is not None:
        return UNHANDLED                    # живое сообщение — не наш кейс
    if not isinstance(reply_to, InaccessibleMessage) and getattr(reply_to, "date", 1) != 0:
        return UNHANDLED                    # не InaccessibleMessage

    user = message.from_user
    if user is None or user.id == _bot_id:
        return UNHANDLED                    # свои сообщения не триггерят

    if _db is None:
        logger.error("dead_page_delete: db not initialized — cannot check mapping")
        return UNHANDLED

    chat_id = message.chat.id
    repost_msg_id = reply_to.message_id

    try:
        bot_ids = await _db.get_dead_page_repost_map(chat_id, repost_msg_id)
    except Exception:
        logger.warning(
            "dead_page_delete: DB read failed | chat=%s | repost_msg_id=%s",
            chat_id, repost_msg_id, exc_info=True,
        )
        return None                          # не спамить повторами

    if not bot_ids:
        logger.debug(
            "dead_page_delete: no mapping for reply on deleted message | "
            "chat=%s | reply_to_msg_id=%s",
            chat_id, repost_msg_id,
        )
        return UNHANDLED

    # ── Действие (а): удалить свои dead pages ──
    try:
        for bid in bot_ids:
            await message.bot.delete_message(chat_id=chat_id, message_id=bid)
        logger.info(
            "dead_page_delete: deleted bot dead pages | chat=%s | repost_msg_id=%s | bot_ids=%s",
            chat_id, repost_msg_id, bot_ids,
        )
    except TelegramForbiddenError:
        # ── Действие (б): ТОЛЬКО 403 → ОДНА токсичная фраза с reply ──
        # (H1: Section 61.9 — фраза при 403; 400/404 — идемпотентно удалён.)
        # M2: атомарный claim (DELETE + rowcount) — при двойном reply в одном
        # цикле (оба прочитали маппинг до delete) фразу шлёт ровно первый.
        try:
            claimed = await _db.try_claim_dead_page_repost_map(chat_id, repost_msg_id)
        except Exception:
            logger.warning(
                "dead_page_delete: mapping claim failed | chat=%s | repost_msg_id=%s",
                chat_id, repost_msg_id, exc_info=True,
            )
            claimed = False
        if claimed:
            try:
                phrase = random.choice(DEAD_PAGE_DELETE_PHRASES)
                await message.reply(phrase)
                logger.info(
                    "dead_page_delete: 403 — sent phrase | chat=%s | repost_msg_id=%s",
                    chat_id, repost_msg_id,
                )
            except Exception:
                logger.warning(
                    "dead_page_delete: phrase send failed | chat=%s", chat_id, exc_info=True,
                )
    except (TelegramBadRequest, TelegramNotFound):
        # H1: 400 «message can't be deleted» (старее 48ч / нет прав) и 404
        # «message not found» → считаем идемпотентно удалённым, фразы НЕТ.
        # Маппинг снимается (действие свершилось).
        logger.warning(
            "dead_page_delete: delete failed (400/404), treating as deleted | "
            "chat=%s | repost_msg_id=%s",
            chat_id, repost_msg_id, exc_info=True,
        )
        try:
            await _db.delete_dead_page_repost_map(chat_id, repost_msg_id)
        except Exception:
            logger.warning(
                "dead_page_delete: mapping cleanup failed | chat=%s | repost_msg_id=%s",
                chat_id, repost_msg_id, exc_info=True,
            )
    except (TelegramServerError, TelegramNetworkError, TelegramRetryAfter):
        # M3: 5xx/сетевые/429 — транзиентные: маппинг НЕ снимаем, следующий
        # reply на удалённый репост перепробует действие.
        logger.warning(
            "dead_page_delete: delete failed (transient 5xx/network/429), "
            "mapping KEPT | chat=%s | repost_msg_id=%s",
            chat_id, repost_msg_id, exc_info=True,
        )
        return None
    except TelegramAPIError:
        # Прочие Telegram-ошибки — не рискуем безвозвратно терять маппинг.
        logger.warning(
            "dead_page_delete: delete failed (unexpected), mapping KEPT | "
            "chat=%s | repost_msg_id=%s",
            chat_id, repost_msg_id, exc_info=True,
        )
        return None
    else:
        try:
            await _db.delete_dead_page_repost_map(chat_id, repost_msg_id)
        except Exception:
            logger.warning(
                "dead_page_delete: mapping cleanup failed | chat=%s | repost_msg_id=%s",
                chat_id, repost_msg_id, exc_info=True,
            )

    return None                              # consume: одно действие на сообщение
