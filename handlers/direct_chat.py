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

Epic 60 (Section 65.2/65.5, T-470/T-473): edited_message бота → обновить
bot_replies (правки людей НЕ переотвечаем); команды /clear /persona /tone
/forget — Command-хендлеры ВЫШЕ catch-all (aiogram внутри роутера идёт по
порядку регистрации; прочие «/»-команды по-прежнему UNHANDLED вниз).
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command, CommandObject

from config.settings import settings
from services import hot_config as hot
from handlers.voice_transcription import is_reply_to_transcription
from services.direct_chat_service import DirectChatService
from services.smartmodule_phrases import (
    CHAT_CLEAR_DONE_PHRASE,
    CHAT_ERROR_PHRASES,
    CHAT_FORGET_DONE_PHRASE,
    CHAT_FORGET_MISS_PHRASE,
    CHAT_FORGET_NOARG_PHRASE,
    CHAT_MEMORY_ALREADY_KNOWN_PHRASES,
    CHAT_MEMORY_CMD_DENIED_PHRASES,
    CHAT_MEMORY_FORGET_NOARG_PHRASES,
    CHAT_MEMORY_FORGOT_DONE_PHRASE,
    CHAT_MEMORY_FORGOT_NONE_PHRASES,
    CHAT_MEMORY_REMEMBERED_PHRASE,
    CHAT_MEMORY_TOO_SHORT_PHRASES,
    CHAT_PERSONA_ADMIN_ONLY_PHRASE,
    CHAT_PERSONA_EMPTY_PHRASE,
    CHAT_PERSONA_FOREIGN_PHRASE,
    CHAT_PERSONA_LIST_EMPTY_PHRASE,
    CHAT_PERSONA_PHRASE,
    CHAT_TONE_SET_PHRASES,
    CHAT_TONE_SHOW_PHRASE,
    CHAT_TONE_UNKNOWN_PHRASE,
)
from services.smartmodule_utils import _reply

logger = logging.getLogger(__name__)

direct_chat_router = Router(name="direct_chat")

_service = None            # DirectChatService (DI)
_bot_id = None
_bot_username = ""

# T-411 (Epic 52, R52-4): keyword-триггеры «бот»-семьи (word-boundary).
# «робот»/«работа»/«забота» — lookbehind блокирует; «ботва» — lookahead;
# «ботохуета» матчится СВОИМ токеном бот+охуета. Сборка один раз на уровне модуля.
# L3 (review-fix): «домен.бот»/«путь/бот» — '.'/'/' в lookbehind не триггерят.
# Epic 60 (67.2, T-492, правило п.49): паттерн — КОНФИГ
# settings.CHAT_BOTWORD_PATTERN (дефолт байт-в-байт = старый литерал);
# невалидный regex → WARNING + дефолт (D104-стиль), бот не падает.
_BOTWORD_PATTERN_DEFAULT = (
    r"(?i)(?<![0-9a-zа-яё_./])бот(?:ина|яра|ик|охуета|охуйня)?(?![0-9a-zа-яё_])"
)


def _compile_botword(pattern: str) -> "re.Pattern[str]":
    try:
        return re.compile(pattern)
    except re.error:
        logger.warning(
            "CHAT_BOTWORD_PATTERN invalid regex — using default (D104)")
        return re.compile(_BOTWORD_PATTERN_DEFAULT)


_BOTWORD_RE = _compile_botword(hot.get("reactions.chat_botword_pattern", settings.CHAT_BOTWORD_PATTERN))

# H2 (review-fix, Section 61.5.2): юзеры, за которыми закреплены свои роутеры/
# сценарии (kostik 2, alan 3 и т.д.). Для них keyword-ветка «бот» НЕ триггерит
# (0h возвращает UNHANDLED → их роутеры видят сообщение). Reply на бота и
# mention (осознанное обращение) — работают как раньше.
_BOTWORD_EXCLUDED_USER_IDS = {hot.get("reactions.alan_user_id", settings.ALAN_USER_ID), hot.get("reactions.kostik_user_id", settings.KOSTIK_USER_ID)}


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
            # Epic 72 (74.C, T-556): расшифровка — НЕ direct chat; гейт даёт
            # 0i транскрибировать голосовой реплай на неё штатно.
            if is_reply_to_transcription(message):
                return False
            return True
    if _has_bot_mention(message):
        return True
    text = message.text or ""
    if _bot_username and re.search(rf"(?i)@{re.escape(_bot_username)}\b", text):
        return True
    # T-411 (R52-4): keyword-ветка под флагом — «бот»/«ботохуета»/«ботина»/…
    if hot.get("flags.direct_chat_botword_enabled", settings.DIRECT_CHAT_BOTWORD_ENABLED) and _BOTWORD_RE.search(text):
        # H2 (review-fix): НЕ триггеримся на сообщения юзеров, за которыми
        # закреплены свои роутеры (alan 3 / kostik 2) — их «бот»-сообщения
        # уходят дальше по цепочке (0h → UNHANDLED). Reply/mention выше —
        # осознанное обращение к боту, исключение ТОЛЬКО для keyword-ветки.
        if message.from_user.id in _BOTWORD_EXCLUDED_USER_IDS:
            return False
        return True
    return False


def _command_user(message: types.Message) -> bool:
    """65.5: команды — per-user (память о юзере). False → UNHANDLED."""
    user = message.from_user
    return user is not None and user.id != _bot_id


@direct_chat_router.message(Command("clear"))
async def cmd_clear(message: types.Message, bot: Bot = None) -> None:
    """65.5 /clear: стереть диалог с юзером (bot_replies + bot_direct_reply-
    факты). Ответ VERBATIM, строчными, без эмодзи."""
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    if not _command_user(message):
        return UNHANDLED
    await _service.clear_user_dialogue(message.chat.id, message.from_user)
    await _reply(bot, message.chat.id, CHAT_CLEAR_DONE_PHRASE,
                 message.message_id)
    logger.info("[direct] /clear | chat=%s user=%s",
                message.chat.id, message.from_user.id)


@direct_chat_router.message(Command("persona"))
async def cmd_persona(message: types.Message, bot: Bot = None,
                      command: CommandObject = None) -> None:
    """65.5 /persona: показать персону + текущий тон (user_prefs).
    Epic 60 (66.9, T-487): /persona <имя> — карточка человека (агрегация
    графа: прямые факты + связи; свою — сам, чужую — только админ, R17);
    /persona list — список карточек (только админ)."""
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    if not _command_user(message):
        return UNHANDLED
    chat_id = message.chat.id
    args = (command.args or "").strip() if command is not None else ""
    if not args:
        preset = await _service.get_tone_preset(chat_id, message.from_user.id)
        text = CHAT_PERSONA_PHRASE.replace(
            "{tone}", settings.tone_display_name(preset))
        await _reply(bot, chat_id, text, message.message_id)
        logger.info("[direct] /persona | chat=%s user=%s",
                    chat_id, message.from_user.id)
        return
    if args.lower() == "list":
        # 66.9: список карточек — только ADMIN_USER_ID (R17).
        if message.from_user.id != settings.ADMIN_USER_ID:
            await _reply(bot, chat_id, CHAT_PERSONA_ADMIN_ONLY_PHRASE,
                         message.message_id)
            logger.warning("[direct] /persona list denied | chat=%s user=%s",
                           chat_id, message.from_user.id)
            return
        names = await _service.list_persona_names(chat_id)
        if not names:
            await _reply(bot, chat_id, CHAT_PERSONA_LIST_EMPTY_PHRASE,
                         message.message_id)
        else:
            body = "\n".join(f"{name} — {count} фактов" for name, count in names)
            await _reply(bot, chat_id, body, message.message_id)
        logger.info("[direct] /persona list | chat=%s admin=%s",
                    chat_id, message.from_user.id)
        return
    # 66.9: карточка по имени/алиасу.
    if not _service.persona_access(message.from_user, args):
        await _reply(bot, chat_id, CHAT_PERSONA_FOREIGN_PHRASE,
                     message.message_id)
        logger.warning("[direct] /persona foreign denied | chat=%s user=%s name=%s",
                       chat_id, message.from_user.id, args)
        return
    card = await _service.build_persona_card(chat_id, args)
    if card is None:
        card = CHAT_PERSONA_EMPTY_PHRASE.replace("{имя}", args)
    await _reply(bot, chat_id, card, message.message_id)
    logger.info("[direct] /persona card | chat=%s user=%s name=%s",
                chat_id, message.from_user.id, args)


@direct_chat_router.message(Command("tone"))
async def cmd_tone(message: types.Message, bot: Bot = None,
                   command: CommandObject = None) -> None:
    """65.5 /tone: показать текущий тон или переключить пресет
    (точный/сбалансированный/болтливый → user_prefs)."""
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    if not _command_user(message):
        return UNHANDLED
    chat_id, user_id = message.chat.id, message.from_user.id
    args = (command.args or "").strip() if command is not None else ""
    if not args:
        preset = await _service.get_tone_preset(chat_id, user_id)
        await _reply(bot, chat_id,
                     CHAT_TONE_SHOW_PHRASE.replace(
                         "{tone}", settings.tone_display_name(preset)),
                     message.message_id)
        return
    preset_key = settings.tone_preset_key(args)
    if preset_key is None:
        await _reply(bot, chat_id, CHAT_TONE_UNKNOWN_PHRASE, message.message_id)
        return
    await _service.set_tone_preset(chat_id, user_id, preset_key)
    await _reply(bot, chat_id, CHAT_TONE_SET_PHRASES[preset_key],
                 message.message_id)
    logger.info("[direct] /tone | chat=%s user=%s preset=%s",
                chat_id, user_id, preset_key)


@direct_chat_router.message(Command("forget"))
async def cmd_forget(message: types.Message, bot: Bot = None,
                     command: CommandObject = None) -> None:
    """65.5/65.10 /forget <фраза>: удалить конкретные bot_direct_reply-факты
    юзера (FTS); защищённые факты НЕ трогаются; журнал — graph_fact_compressions
    (reason='forget'). Без аргумента — подсказка."""
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    if not _command_user(message):
        return UNHANDLED
    args = (command.args or "").strip() if command is not None else ""
    if not args:
        await _reply(bot, message.chat.id, CHAT_FORGET_NOARG_PHRASE,
                     message.message_id)
        return
    removed = await _service.forget_user_fact(message.chat.id, message.from_user, args)
    phrase = CHAT_FORGET_DONE_PHRASE if removed else CHAT_FORGET_MISS_PHRASE
    await _reply(bot, message.chat.id, phrase, message.message_id)
    logger.info("[direct] /forget | chat=%s user=%s removed=%d",
                message.chat.id, message.from_user.id, removed)


@direct_chat_router.edited_message()
async def direct_chat_edited_handler(message: types.Message, bot: Bot = None) -> None:
    """65.2 (T-470): бот отредактировал СВОЁ сообщение → обновить запись в
    bot_replies (UPSERT — цепочка на следующем обращении соберётся из свежего
    текста). Правка ЧЕЛОВЕКОМ своего сообщения — UNHANDLED, НЕ переотвечаем."""
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    if message.from_user is None or message.from_user.id != _bot_id:
        return UNHANDLED                       # правка человеком — не трогаем
    text = (message.text or message.caption or "").strip()
    if not text:
        return UNHANDLED
    await _service.remember_bot_reply(message.chat.id, message.message_id, text)


# ── Раунд 4 (T-712, FR-D1, spec 3.4.2): память-команды «запомни/забудь» ──
# Отдельный роутер НЕ регистрируется: команда ищется в начале сообщения ПОСЛЕ
# срабатывания direct-chat-триггера (reply на бота / mention / «бот»-слово) —
# консистентно с direct_chat, ложных срабатываний на обычных сообщениях нет.
# Fix-раунд 4 (M-1/M-4): regex-эталоны — байт-в-байт spec 3.4.2: forget
# нормирован ТОЛЬКО «забудь» («забыть/удали из памяти/выкинь из памяти» —
# обычный LLM-диалог, НЕ команда: ответ модели не теряется); remember
# требует разделитель `\s*[,:]?\s+` — «запомни:бензин» без пробела не команда.
_PEER_PREFIX_RE = re.compile(
    r"^(?:(?:бот(?:ина|яра|ик)?|@[\w_]+)[,:]?\s+)+", re.IGNORECASE)
_MEMORY_FACT_MAX_CHARS = 500      # spec 3.4.2: кап аргумента «запомни» (спам)
_CMD_REMEMBER_RE = re.compile(
    r"^(?:запомни|запомнить|запиши)\s*[,:]?\s+(.+)$", re.IGNORECASE)
_CMD_FORGET_RE = re.compile(r"^забудь\s*[:]?\s*(.*)$", re.IGNORECASE)


def _parse_memory_command(raw: str) -> tuple[str, str] | None:
    """('remember'|'forget'|'forget_noarg'|'too_short', arg). Ищет команду в
    начале сообщения (после необязательного обращения «бот…»/«@ник» с
    разделителем). None — не команда (обычный direct_chat, LLM-путь).
    remember-аргумент обязателен (нет «запомни» без текста); «забудь» без
    аргумента → forget_noarg (help-фраза, consumed); forget-аргумент «всё»
    (casefold) → forget_noarg (spec 3.4.8: «забудь всё» намеренно НЕ
    реализуем — help-фраза, consumed, ничего не удаляется); аргумент < 3
    симв → too_short."""
    text = str(raw or "").strip()
    if not text:
        return None
    while True:
        m = _PEER_PREFIX_RE.match(text)
        if not m:
            break
        text = text[m.end():].strip()
    for rx, kind in ((_CMD_REMEMBER_RE, "remember"),
                     (_CMD_FORGET_RE, "forget")):
        m = rx.match(text)
        if not m:
            continue
        arg = m.group(1).strip()
        if kind == "forget" and (not arg or arg.casefold() == "всё"):
            return "forget_noarg", ""
        if len(arg) < 3:
            return "too_short", ""
        return kind, arg
    return None


async def _handle_memory_command(bot: Bot, message: types.Message,
                                 kind: str, arg: str) -> None:
    """Ветка память-команд (consumed — `service.handle` НЕ вызывается;
    троттлинг/кулдаун/LLM не задействованы). RBAC/тумблер — в сервисном
    слое; здесь — вызов + фраза из пула (spec 3.4.2/3.4.7)."""
    if _service is None:
        return
    chat_id = message.chat.id
    user = message.from_user
    phrase = None
    try:
        if kind == "remember":
            # spec 3.4.2: аргумент — схлопывание пробелов + cap 500 (спам).
            # Усечение ДО вызова сервиса: фраза-подтверждение показывает ровно
            # сохранённый текст (сервисный кап — второй рубеж).
            fact_text = " ".join(arg.split())[:_MEMORY_FACT_MAX_CHARS]
            if fact_text != arg:
                logger.info(
                    "[user_memory] remember arg truncated to %d chars | chat=%s",
                    _MEMORY_FACT_MAX_CHARS, chat_id)
            result = await _service.remember_user_fact(chat_id, user, fact_text)
            if result == "saved":
                phrase = CHAT_MEMORY_REMEMBERED_PHRASE.replace(
                    "{факт}", fact_text)
            elif result == "duplicate":
                phrase = random.choice(CHAT_MEMORY_ALREADY_KNOWN_PHRASES)
            elif result == "denied":
                phrase = random.choice(CHAT_MEMORY_CMD_DENIED_PHRASES)
            else:
                phrase = random.choice(CHAT_ERROR_PHRASES)
        elif kind == "forget":
            code, removed, query = await _service.forget_user_facts(
                chat_id, user, arg)
            if code == "denied":
                phrase = random.choice(CHAT_MEMORY_CMD_DENIED_PHRASES)
            elif code == "error":
                phrase = random.choice(CHAT_ERROR_PHRASES)
            elif removed > 0:
                phrase = (CHAT_MEMORY_FORGOT_DONE_PHRASE
                          .replace("{n}", str(removed))
                          .replace("{запрос}", query))
            else:
                phrase = random.choice(CHAT_MEMORY_FORGOT_NONE_PHRASES).replace(
                    "{запрос}", query)
        elif kind == "forget_noarg":
            phrase = random.choice(CHAT_MEMORY_FORGET_NOARG_PHRASES)
        else:                                    # too_short
            phrase = random.choice(CHAT_MEMORY_TOO_SHORT_PHRASES)
    except Exception:
        logger.warning("[user_memory] command handling failed | chat=%s kind=%s",
                       chat_id, kind, exc_info=True)
        phrase = random.choice(CHAT_ERROR_PHRASES)
    if phrase:
        await _reply(bot, chat_id, phrase, message.message_id)
    logger.info("[direct] memory command | chat=%s user=%s kind=%s consumed",
                chat_id, user.id if user is not None else None, kind)


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
    # Раунд 4 (T-712, FR-D1): память-команды — ПОСЛЕ триггера, ДО handle.
    # Распознанный синтаксис → ответ/подтверждение + consumed (в LLM НЕ
    # уходит; команды работают даже при активном кулдауне диалога).
    parsed = _parse_memory_command(text)
    if parsed is not None:
        kind, arg = parsed
        return await _handle_memory_command(bot, message, kind, arg)
    await _service.handle(bot, message, user)
    return
