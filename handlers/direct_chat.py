"""Epic 50 — DirectChat handler (R50-1, D202, Section 58.4).

Роутер 0h (сразу после 0g checkup, до admin_commands; гейт SUMMARY_ENABLED).
Реактивный — бот НИКОГДА не инициирует. Триггеры:
  1. Reply на бота: reply_to_message.from_user.id == bot.id;
  2. Упоминание (entities): mention с username бота (регистронезависимо)
     ЛИБО text_mention с user.id == bot.id;
  3. Fallback-текст: regex (?i)@username\b (старые клиенты без entities).
Исключения (UNHANDLED, пропагация живёт): нет DI; from_user.id == bot.id;
текст начинается с «/» (команды не перехватываются); пустой текст.
H2 (review-fix): keyword-ветка «бот» НЕ триггерит на юзеров со своими
роутерами/сценариями (alan 3 / kostik 2 — см. _BOTWORD_EXCLUDED_USER_IDS) —
их сообщения уходят дальше; reply на бота / mention — осознанное обращение,
работают как раньше.
Каналы (channel-post) — вне скоупа; группы/супергруппы/ЛС работают
(троттлинг защищает от спама, 58.5).
"""
import logging
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services.direct_chat_service import DirectChatService

logger = logging.getLogger(__name__)

direct_chat_router = Router(name="direct_chat")

_service = None            # DirectChatService (DI)
_bot_id = None
_bot_username = ""

# T-411 (Epic 52, R52-4): keyword-триггеры «бот»-семьи (word-boundary).
# «робот»/«работа»/«забота» — lookbehind блокирует; «ботва» — lookahead;
# «ботохуета» матчится СВОИМ токеном бот+охуета. Сборка один раз на уровне модуля.
# L3 (review-fix): «домен.бот»/«путь/бот» — '.'/'/' в lookbehind не триггерят.
_BOTWORD_RE = re.compile(
    r"(?i)(?<![0-9a-zа-яё_./])бот(?:ина|яра|ик|охуета|охуйня)?(?![0-9a-zа-яё_])"
)

# H2 (review-fix, Section 61.5.2): юзеры, за которыми закреплены свои роутеры/
# сценарии (kostik 2, alan 3 и т.д.). Для них keyword-ветка «бот» НЕ триггерит
# (0h возвращает UNHANDLED → их роутеры видят сообщение). Reply на бота и
# mention (осознанное обращение) — работают как раньше.
_BOTWORD_EXCLUDED_USER_IDS = {settings.ALAN_USER_ID, settings.KOSTIK_USER_ID}


def setup_direct_chat(service: DirectChatService | None, bot_id: int | None,
                      bot_username: str | None) -> None:
    """DI. Вызывается из bot.py on_startup (58.4)."""
    global _service, _bot_id, _bot_username
    _service = service
    _bot_id = bot_id
    _bot_username = (bot_username or "").lower()


def _has_bot_mention(message: types.Message) -> bool:
    """Триггер 2: entities mention/text_mention (основной путь, D202).

    aiogram 3.x MessageEntity НЕ несёт username (поле отсутствует — REVISE S1):
    юзернейм извлекается из текста через entity.extract_from(text)
    (срез [offset:offset+length]), срезается '@' и приводится к нижнему
    регистру. text_mention несёт user (entity.user.id == bot.id)."""
    text = message.text or ""
    for entity in (getattr(message, "entities", None) or ()):
        etype = getattr(entity, "type", None)
        if etype == "mention":
            raw = entity.extract_from(text)
            if raw.removeprefix("@").lower() == _bot_username:
                return True
        elif etype == "text_mention":
            user = getattr(entity, "user", None)
            if user is not None and user.id == _bot_id:
                return True
    return False


def _is_direct_trigger(message: types.Message) -> bool:
    """Триггеры 1-4 (58.4 + R52-4). Вызывается ПОСЛЕ исключений (команды/пустой текст).

    Приоритет reply/mention ≥ keyword соблюдается автоматически (OR-ветки;
    reply/mention дешевле и проверяются раньше)."""
    reply_to = message.reply_to_message
    if reply_to is not None:
        reply_from = getattr(reply_to, "from_user", None)
        if reply_from is not None and reply_from.id == _bot_id:
            return True
    if _has_bot_mention(message):
        return True
    text = message.text or ""
    if _bot_username and re.search(rf"(?i)@{re.escape(_bot_username)}\b", text):
        return True
    # T-411 (R52-4): keyword-ветка под флагом — «бот»/«ботохуета»/«ботина»/…
    if settings.DIRECT_CHAT_BOTWORD_ENABLED and _BOTWORD_RE.search(text):
        # H2 (review-fix): НЕ триггеримся на сообщения юзеров, за которыми
        # закреплены свои роутеры (alan 3 / kostik 2) — их «бот»-сообщения
        # уходят дальше по цепочке (0h → UNHANDLED). Reply/mention выше —
        # осознанное обращение к боту, исключение ТОЛЬКО для keyword-ветки.
        if message.from_user.id in _BOTWORD_EXCLUDED_USER_IDS:
            return False
        return True
    return False


@direct_chat_router.message()
async def direct_chat_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    user = message.from_user
    if user is None or user.id == _bot_id:
        return UNHANDLED                       # само-сообщения бота
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return UNHANDLED                       # команды не перехватываются
    if not _is_direct_trigger(message):
        return UNHANDLED                       # не триггер → пропагация живёт
    await _service.handle(bot, message, user)
    return
