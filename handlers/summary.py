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
import logging
import random
import time

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command

from config.settings import settings
from services import hot_config as hot
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
        try:
            await _db.save_smart_message(
                user_id=user.id,
                chat_id=message.chat.id,
                text=text,
                reply_to_id=reply_to_id,
                timestamp=int(time.time()),
                media_type=media_type,
                author_name=author_name,
                is_forward=is_forward,
                forward_source=(forward_source or "")[:_FORWARD_SOURCE_MAX_CHARS],
                message_id=message.message_id,   # Epic 50 (58.7): TG id для reply-цепочек
            )
        except Exception:
            logger.warning(
                "SmartModule observer: save failed | chat=%s user=%s",
                message.chat.id, user.id, exc_info=True,
            )
    except Exception:
        logger.warning("SmartModule observer: unexpected error", exc_info=True)
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
    await _generator.generate_and_send(message.chat.id, manual=True, focus=focus)  # B2
    return
