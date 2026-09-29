"""Epic 24/25 — SmartModule Summary handlers (Sections 33.9 + 34.5/34.6).

summary_observer_router (position 0a): catch-all observer — saves ALL chat
messages to smart_messages, ALWAYS returns UNHANDLED so propagation to the
other routers is guaranteed even on failures. Epic 25 (B9): commands starting
with /summary are NOT saved to memory.

summary_router (position 0b): /summary manual trigger. ALLOWED_SUMMARY_IDS
empty = everyone; non-empty = listed IDs only (silent absorb). Handler never
returns UNHANDLED on its own path (A4) — Slava's catch-all must not fire.
Epic 25: ack before the pipeline (B1), best-effort command deletion (B7), UX
safety net when the generator is not injected (B6), INFO logs for every state
(B8). Epic 29 (D81/D82): команда удаляется СРАЗУ, ДО ack; ack — random.choice
из пула вариаций _UX_ACK_VARIANTS. Epic 31 (D94): SUMMARY_ADMIN_ONLY=true →
доступ только ADMIN_USER_ID (ALLOWED_SUMMARY_IDS игнорируется).
"""
import datetime
import logging
import random
import time

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command

from config.settings import settings
from services import hot_config as hot
from services import message_identity
from services.media_group_buffer import record_media_group_message
from services.summary_throttling import ThrottlingMiddleware

logger = logging.getLogger(__name__)

summary_observer_router = Router(name="summary_observer")
summary_router = Router(name="summary")

_generator = None
_db = None
_aliases = None
_bot_id = None

# B1/D82 (Epic 29): ручной вызов, до пайплайна; random.choice при каждом вызове.
# Канон (D82) — первым элементом; 20 вариаций, полный список — Section 38.2.
_UX_ACK_VARIANTS: tuple[str, ...] = (
    "ща гляну, подожди",                          # канон (D82)
    "секунду, роюсь в истории",
    "погнали, сейчас посчитаю шизов",
    "так, кому тут саммари? ща сделаю",
    "минуту, перечитываю вашу ленту",
    "ща, собираю мысли в кучу",
    "уже бегу по вашим сообщениям",
    "подожди, листаю архив позора",
    "сейчас всё разложу по полочкам, ну или не разложу",
    "одну секунду, вспоминаю кто тут кто",
    "ща посмотрю, кто тут наговорил",
    "минуточку, анализирую вашу дичь",
    "погоди, выжимаю суть из этого балагана",
    "сейчас, кручу ленту назад",
    "терпи, читаю как вы тут живёте",
    "ща, соберу цитатки",
    "секунду, грею нейроны",
    "погоди, вытаскиваю главного шиза",
    "ща, всё посмотрю и расскажу",
    "минутку, ваш саммари уже в печи",
)
_UX_NOT_READY = "не смог сделать саммари"     # B6: страховка вайринга (R13-стиль)

_FORWARD_SOURCE_MAX_CHARS = 100


def _extract_forward_source(origin) -> str | None:
    """Epic 28 (R28-1): label of the forward origin; None = save as ordinary."""
    if origin is None:
        return None
    try:
        if isinstance(origin, types.MessageOriginChannel):
            chat = getattr(origin, "chat", None)
            title = (getattr(chat, "title", None) or "").strip()
            username = (getattr(chat, "username", None) or "").strip()
            signature = (getattr(origin, "author_signature", None) or "").strip()
            parts = [title] + ([f"@{username}"] if username else []) + ([signature] if signature else [])
            return " ".join(parts) or None
        if isinstance(origin, types.MessageOriginUser):
            sender = getattr(origin, "sender_user", None)
            if sender is None:
                return None
            if _aliases is not None:
                return _aliases.resolve(
                    sender.id,
                    nickname=_build_nickname(sender),
                    username=getattr(sender, "username", None),
                )
            nickname = _build_nickname(sender)
            return nickname or (getattr(sender, "username", None) or str(sender.id)).lstrip("@")
        if isinstance(origin, types.MessageOriginHiddenUser):
            name = getattr(origin, "sender_user_name", None)
            return (name or "").strip() or None
        if isinstance(origin, types.MessageOriginChat):
            chat = getattr(origin, "sender_chat", None)
            title = (getattr(chat, "title", None) or "").strip()
            username = (getattr(chat, "username", None) or "").strip()
            parts = [title] + ([f"@{username}"] if username else [])
            return " ".join(parts) or None
        return None
    except Exception:
        logger.warning("SmartModule observer: forward source extraction failed", exc_info=True)
        return None


def setup_summary(generator, db=None, aliases=None, bot_id=None) -> None:
    """Inject dependencies. Called from bot.py on_startup() (33.9) — ПОСЛЕ
    set_config_cache. Middleware /summary регистрируется ЗДЕСЬ (не на
    module-level): ThrottlingMiddleware создаётся с живым значением из кэша
    (значение из админки), а не бейкдится при импорте (N1)."""
    global _generator, _db, _aliases, _bot_id
    _generator = generator
    _db = db
    _aliases = aliases
    _bot_id = bot_id
    # N1: регистрация строго один раз (идемпотентный guard — повторный
    # setup_summary не дублирует middleware).
    if not getattr(summary_router.message, "_throttle_registered", False):
        summary_router.message.outer_middleware(ThrottlingMiddleware())
        summary_router.message._throttle_registered = True


def _detect_media_type(message: types.Message) -> str:
    """Map message fields to smart_messages.media_type (33.9)."""
    if getattr(message, "text", None) is not None:
        return "text"
    if getattr(message, "photo", None) is not None:
        return "photo"
    if getattr(message, "video", None) is not None or getattr(message, "video_note", None) is not None:
        return "video"
    if getattr(message, "voice", None) is not None:
        return "voice"
    if getattr(message, "audio", None) is not None:
        return "audio"
    if getattr(message, "animation", None) is not None:
        return "animation"
    if getattr(message, "sticker", None) is not None:
        return "sticker"
    if getattr(message, "document", None) is not None:
        return "document"
    return "other"


def _build_nickname(user) -> str | None:
    parts = []
    for attr in ("first_name", "last_name"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts) if parts else None


def _media_ref(message: types.Message, media_type: str) -> str | None:
    """MCA-03 (D3): ссылка на медиа (НЕ байты) — `media_type:file_unique_id`.

    Для media-сообщений берётся последний элемент списка (photo) либо сам
    объект; при отсутствии `file_unique_id` — честный None."""
    if media_type in ("text", "other"):
        return None
    obj = getattr(message, media_type, None)
    if isinstance(obj, (list, tuple)):
        obj = obj[-1] if obj else None
    uid = getattr(obj, "file_unique_id", None)
    return f"{media_type}:{uid}" if isinstance(uid, str) and uid else None


def _sent_at_of(message: types.Message) -> int | None:
    """Дата СОБЫТИЯ (message.date) в unix; None при отсутствии/поломке."""
    try:
        date = message.date
        if isinstance(date, datetime.datetime):
            return int(date.timestamp())
    except (AttributeError, TypeError, OverflowError, OSError, ValueError):
        return None
    return None


# ── 0a. Observer ──────────────────────────────────────────────

@summary_observer_router.message()
async def summary_observer(message: types.Message):
    """Catch-all: save every chat message. ALWAYS returns UNHANDLED."""
    try:
        if _db is None or _aliases is None:
            return UNHANDLED
        user = message.from_user
        if user is None:
            return UNHANDLED
        if _bot_id is not None and user.id == _bot_id:
            return UNHANDLED
        command_text = message.text or message.caption
        if command_text and command_text.lstrip().startswith("/summary"):
            # B9: команды — не контент чата; в окно LLM не попадают
            return UNHANDLED
        text = command_text
        media_type = _detect_media_type(message)
        if not text and media_type == "other":
            # чистые сервисные (join/pin и т.п.) — не сохраняем
            return UNHANDLED
        try:
            record_media_group_message(message)     # Epic 36 (R36-1, Section 45.1)
        except Exception:
            logger.warning("SmartModule observer: media group buffer fill failed", exc_info=True)
        reply_to_id = (
            message.reply_to_message.message_id if message.reply_to_message else None
        )
        author_name = _aliases.resolve(
            user.id,
            nickname=_build_nickname(user),
            username=getattr(user, "username", None),
        )
        origin = getattr(message, "forward_origin", None)   # getattr-защита (риск 7)
        is_forward = origin is not None
        forward_source = _extract_forward_source(origin) if is_forward else None
        # MCA-03 (ADR-1027-4 D3/D4): дата события ≠ дата записи; роли
        # (адресат ответа/цитируемый/forward-автор) разделены. Значения —
        # честный unknown (None), не выдуманы.
        reply_author_id = None
        if message.reply_to_message is not None:
            reply_user = getattr(message.reply_to_message, "from_user", None)
            reply_author_id = getattr(reply_user, "id", None)
        quote_text = None
        quote = getattr(message, "quote", None)
        if quote is not None:
            quote_text = getattr(quote, "text", None)
        forward_author_id = None
        if origin is not None:
            fwd_user = getattr(origin, "sender_user", None)
            forward_author_id = getattr(fwd_user, "id", None)
        # MCA-03 (ADR-1027-4 D3): дата СОБЫТИЯ (`sent_at` = message.date) и
        # дата ЗАПИСИ (`ingested_at` = now) считаются НЕЗАВИСИМО и не
        # приравниваются друг к другу; legacy `timestamp` = время записи.
        # Для «поздно доставленного» сообщения sent_at < ingested_at.
        sent_at = _sent_at_of(message)
        ingested_at = int(time.time())
        try:
            await message_identity.save_live_message(
                _db,
                user_id=user.id,
                chat_id=message.chat.id,
                text=text,
                caption=message.caption,
                timestamp=ingested_at,          # legacy-колонка = время записи
                sent_at=sent_at,                # дата события (Telegram)
                ingested_at=ingested_at,        # независимый write-clock
                media_type=media_type,
                author_name=author_name,
                is_forward=is_forward,
                forward_source=(forward_source or "")[:_FORWARD_SOURCE_MAX_CHARS],
                tg_message_id=message.message_id,   # Epic 50 (58.7)
                media_ref=_media_ref(message, media_type),
                reply_to_id=reply_to_id,
                reply_to_author_id=reply_author_id,
                quote_text=quote_text,
                forward_author_id=forward_author_id,
            )
        except Exception:
            logger.warning(
                "SmartModule observer: save failed | chat=%s user=%s",
                message.chat.id, user.id, exc_info=True,
            )
    except Exception:
        logger.warning("SmartModule observer: unexpected error", exc_info=True)
    return UNHANDLED


@summary_observer_router.edited_message()
async def summary_observer_edited(message: types.Message):
    """MCA-03 (T-3788, ADR-1027-4 D5): правка сообщения человеком → новая
    версия. Kill-switch OFF (`MCA_MESSAGE_REVISION_TRACKING_ENABLED=false`) →
    no-op (паритет baseline: версий нет). Всегда UNHANDLED — не перехватываем
    чужие edited-хендлеры (напр. bot_replies в direct_chat)."""
    try:
        if _db is None or message.from_user is None:
            return UNHANDLED
        if _bot_id is not None and message.from_user.id == _bot_id:
            return UNHANDLED
        text = message.text or message.caption
        if text and text.lstrip().startswith("/summary"):
            return UNHANDLED
        edited_at = None
        try:
            if isinstance(message.edit_date, datetime.datetime):
                edited_at = int(message.edit_date.timestamp())
        except (AttributeError, OverflowError, OSError, ValueError):
            edited_at = None
        await message_identity.record_edit(
            _db, chat_id=message.chat.id, tg_message_id=message.message_id,
            text=text, caption=message.caption, edited_at=edited_at)
    except Exception:
        logger.warning("SmartModule observer: edited handler error",
                       exc_info=True)
    return UNHANDLED


# ── 0b. /summary command ─────────────────────────────────────

async def _safe_send(bot: Bot | None, chat_id: int, text: str) -> None:
    """B6: UX-отправка; отказ не должен ронять хендлер.

    Bot берётся из DI хендлера (не из _generator.bot) — работает и при
    _generator is None (замечание PM к T-193).
    """
    if bot is None:
        logger.warning("[/summary] no bot available to send | chat_id=%s", chat_id)
        return
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        logger.exception("[/summary] failed to send | chat_id=%s", chat_id)


async def _delete_command(message: types.Message) -> None:
    """B7: удалить команду из чата. Отказ (нет delete_messages в группе) — WARNING, не падение."""
    try:
        await message.delete()
        logger.info(
            "[/summary] command deleted | chat=%s msg=%s",
            message.chat.id, message.message_id,
        )
    except Exception as exc:
        # Epic 64: без exc_info — трейсбек aiogram в лог не нужен,
        # причина детерминирована (нет прав / старше 48ч).
        logger.warning(
            "[/summary] command delete failed (%s) | chat=%s msg=%s",
            type(exc).__name__, message.chat.id, message.message_id,
        )


@summary_router.message(Command("summary"))
async def cmd_summary(message: types.Message, bot: Bot = None):
    """Manual summary trigger (R9/D62). Delete → ack → pipeline (D81/B1/B2)."""
    user_id = message.from_user.id if message.from_user else 0
    # D94 (Epic 31): порядок проверок — SUMMARY_ADMIN_ONLY → ALLOWED_SUMMARY_IDS.
    # true  → разрешён ТОЛЬКО ADMIN_USER_ID (ALLOWED_SUMMARY_IDS игнорируется);
    # false → старая логика: пусто = всем, список = только перечисленным.
    # Denied — silent absorb (R9/D62): не удаляем, не отвечаем, только INFO-лог.
    if hot.get("flags.summary_admin_only", settings.SUMMARY_ADMIN_ONLY) and user_id != settings.ADMIN_USER_ID:
        logger.info("[/summary] denied | user=%s (SUMMARY_ADMIN_ONLY)", user_id)
        return
    allowed = hot.get("reactions.allowed_summary_ids", settings.ALLOWED_SUMMARY_IDS)
    if not hot.get("flags.summary_admin_only", settings.SUMMARY_ADMIN_ONLY) and allowed and user_id not in allowed:
        logger.info("[/summary] denied | user=%s not in ALLOWED_SUMMARY_IDS", user_id)
        return
    if _generator is None:
        # B6: страховка вайринга — пользователь должен получить ответ
        logger.warning("[/summary] SummaryGenerator not initialized — skipping")
        await _safe_send(bot, message.chat.id, _UX_NOT_READY)
        return
    logger.info("[/summary] triggered | chat=%s user=%s", message.chat.id, user_id)
    # Epic 65: «/summary про X» → фокус-тема (до 200 симв.), None = обычное саммари.
    focus = None
    raw_text = (message.text or "").strip()
    if raw_text.lower().startswith("/summary"):
        rest = raw_text[len("/summary"):]
        if rest.startswith("@"):                       # /summary@botname …
            _, _, rest = rest.partition(" ")
        rest = rest.strip()
        if rest:
            focus = rest[:200]
            logger.info("[/summary] focus | chat=%s | len=%d", message.chat.id, len(focus))
    await _delete_command(message)                                 # D81: удалить СРАЗУ, ДО ack
    await _safe_send(bot, message.chat.id, random.choice(_UX_ACK_VARIANTS))   # B1/D82: ack из пула
    logger.info("[/summary] ack sent | chat=%s", message.chat.id)
    # Раунд 10.23 (F1, ADR-1023-1; R1023F1-04): Telegram id команды передаётся
    # в контракт для симметрии. ВАЖНО: команда `/summary` observer'ом НЕ
    # сохраняется (B9: команды — не контент чата), поэтому её tg_message_id
    # никогда не совпадёт с smart_messages.tg_message_id → для саммари маркер
    # НЕДОСТИЖИМ (всегда legacy-путь, без маркера). Это известное ограничение
    # зафиксировано в spec §9; отдельный носитель триггера саммари — вне F1.
    await _generator.generate_and_send(
        message.chat.id, manual=True, focus=focus,
        trigger_message_id=message.message_id)  # B2
    return
