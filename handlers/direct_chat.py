"""Epic 50 — DirectChat handler (R50-1, D202, Section 58.4).

Роутер 0h (сразу после 0g checkup, до admin_commands). F5 (ТЗ §18H): роутер
зарегистрирован ВСЕГДА; master-гейт ``flags.direct_chat_botword_enabled``
проверяется в рантайме на всей триггерной поверхности (reply/mention/имя/
keyword — см. _is_direct_trigger); зависимости от Summary нет.
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

ADD-TR.2 (19.10.2026, M-ADTR-ENTRY-EVENT/TRIGGERS): единый вход — текст
события = ``message.text``, при его отсутствии ``caption`` подписи к медиа;
упоминания — ``entities`` текста ИЛИ ``caption_entities`` подписи. Подпись
НЕ становится отдельной репликой (тот же роутер, тот же сервисный ход):
«бот …» / @username / reply боту активируют Direct и в подписи. «Голое»
photo/image-document реплаем на бота (без подписи) — тоже осознанное
обращение; прочие медиа без подписи (голос/видео/стикер…) пропагируют в
свои пути (0i и ниже) как раньше. Отдельного «caption bot» нет.
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command, CommandObject

from config.settings import settings
from services import command_prefix
from services import feature_gates
from services import hot_config as hot
from services import bot_persona
from services import mca_style_scope
from handlers.voice_transcription import is_reply_to_transcription
from handlers.video_download import download_available
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
# P0 DIRECT-TRIGGER (owner 26.11.2026): паттерн и триггер-типы живут в
# services.command_prefix — один источник для хендлера и сервиса (повторной
# независимой классификации того же текста в сервисе больше нет).
_BOTWORD_PATTERN_DEFAULT = command_prefix.BOTWORD_PATTERN_DEFAULT
_BOTWORD_RE = command_prefix.BOTWORD_RE


def _compile_botword(pattern: str) -> "re.Pattern[str]":
    return command_prefix.compile_botword(pattern)

# H2 (review-fix, Section 61.5.2): юзеры, за которыми закреплены свои роутеры/
# сценарии (kostik 2, alan 3 и т.д.). Для них keyword-ветка «бот» НЕ триггерит
# (0h возвращает UNHANDLED → их роутеры видят сообщение). Reply на бота и
# mention (осознанное обращение) — работают как раньше.
_BOTWORD_EXCLUDED_USER_IDS = {hot.get("reactions.alan_user_id", settings.ALAN_USER_ID), hot.get("reactions.kostik_user_id", settings.KOSTIK_USER_ID)}

# Раунд 10.15 (F6, review-fix M2): функциональная команда yield-ится в
# direct_chat ТОЛЬКО когда соответствующий воркер реально включён. Иначе
# (напр. «Бот, скачай …» при flags.download_enabled=false) сообщение уходит в
# обычный путь LLM, а не теряется без ответа.
_FUNCTIONAL_FLAGS: dict[str, tuple[str, bool]] = {
    "search": ("flags.search_enabled", settings.SEARCH_ENABLED),
    "youtube": ("flags.video_summary_enabled", settings.VIDEO_SUMMARY_ENABLED),
    "web": ("flags.webpage_enabled", settings.WEBPAGE_ENABLED),
    "checkup": ("flags.checkup_enabled", settings.CHECKUP_ENABLED),
    "download": ("flags.download_enabled", settings.DOWNLOAD_ENABLED),
}


def _functional_module_active(group: str | None) -> bool:
    """Включён ли воркер группы (master-флаг + доступность сервиса).

    Синхронная legacy-форма для тестов и вызовов без чата: читает только
    глобальный слой. Runtime-путь `direct_chat_handler` использует
    `_functional_module_active_for_chat` — тот же вопрос, но per chat
    (MOD-ACL-UX-01 M2.1).

    R10.15-4: для `download` одного hot-флага мало — роутер 4e регистрируется
    в `bot.py` всегда, но yield оправдан только когда поднят DI-сервис
    (`_downloader`). Иначе сообщение не должно покидать direct_chat без
    ответа: пропускаем его в обычный путь (LLM).

    S10.16-3: при текущем безусловном DI (`setup_video_download` всегда)
    ветка `download_available()` всегда True — это осознанная
    defense-in-depth для будущего условного DI (см. `download_available`),
    покрыта тестами TestDownloadAlwaysRegistered."""
    spec = _FUNCTIONAL_FLAGS.get(group or "")
    if spec is None:
        return False
    if not hot.get(spec[0], spec[1]):
        return False
    if group == "download":
        return download_available()
    return True


async def _functional_module_active_for_chat(chat_id, group: str | None) -> bool:
    """Per-chat форма `_functional_module_active` (MOD-ACL-UX-01 M2.1).

    GLOBAL-дефолт → явный CHAT-override через канонический резолвер; иначе
    функциональная команда («Бот, скачай …») при GLOBAL OFF + CHAT ON не
    доходила бы до своего воркера: direct_chat съедал бы её как обычный
    ответ. Shared-сервис (download DI) остаётся отдельной проверкой.
    """
    spec = _FUNCTIONAL_FLAGS.get(group or "")
    if spec is None:
        return False
    if not await feature_gates.module_enabled(
            chat_id, key=spec[0], default=spec[1]):
        return False
    if group == "download":
        return download_available()
    return True


def setup_direct_chat(service: DirectChatService | None, bot_id: int | None,
                      bot_username: str | None) -> None:
    """DI. Вызывается из bot.py on_startup (58.4)."""
    global _service, _bot_id, _bot_username
    _service = service
    _bot_id = bot_id
    _bot_username = (bot_username or "").lower()


def _effective_text(message: types.Message) -> str:
    """ADD-TR.2 (ADTR-ENTRY): единый текст Telegram-события.

    ``message.text``, при его отсутствии — ``message.caption`` подписи к
    медиа (photo/document_image/…). Оба поля — один пользовательский текст
    одного события; подпись не становится отдельной репликой и не теряется
    до семантических путей. Не-str/none → "" (защита от тест-двойников)."""
    text = getattr(message, "text", None)
    if text is None:
        text = getattr(message, "caption", None)
    if not isinstance(text, str):
        return ""
    return text.strip()


def _has_image_attachment(message: types.Message) -> bool:
    """ADD-TR.2: photo или image-document (единая политика MCA-19
    `mca_vision.extract_image_assets`: документ — только ``mime_type``
    ``image/*``). Не любой документ считается картинкой. Для реальных
    aiogram-типов: ``photo`` — непустой список; прочее → False."""
    photo = getattr(message, "photo", None)
    if isinstance(photo, (list, tuple)) and len(photo) > 0:
        return True
    document = getattr(message, "document", None)
    mime = str(getattr(document, "mime_type", "") or "")
    return bool(document is not None and mime.startswith("image/"))


def _message_entities(message: types.Message) -> tuple[str, tuple]:
    """ADD-TR.2: пара (текст, entities) БЕЗ смешения источников.

    Для текста — (text, entities); для подписи — (caption,
    caption_entities). Смещения entity валидны только относительно своей
    строки, поэтому пары не миксуются. Если ни text, ни caption нет —
    сохраняется прежний путь (entities текста; в реальных Telegram-объектах
    их там не бывает — совместимость с тест-двойниками)."""
    def _as_entities(value):
        return value if isinstance(value, (list, tuple)) else ()

    raw = getattr(message, "text", None)
    if isinstance(raw, str):
        return raw, _as_entities(getattr(message, "entities", None))
    caption = getattr(message, "caption", None)
    if isinstance(caption, str):
        return caption, _as_entities(getattr(message, "caption_entities", None))
    return "", _as_entities(getattr(message, "entities", None))


def _has_bot_mention(message: types.Message) -> bool:
    """Триггер 2: entities mention/text_mention (основной путь, D202).

    aiogram 3.x MessageEntity НЕ несёт username (поле отсутствует — REVISE S1):
    юзернейм извлекается из текста через entity.extract_from(text)
    (срез [offset:offset+length]), срезается '@' и приводится к нижнему
    регистру. text_mention несёт user (entity.user.id == bot.id).
    ADD-TR.2: для подписи — caption/caption_entities (см. _message_entities).
    P0 (26.11.2026): упоминание внутри цитируемого блока — не собственное
    обращение участника; диапазоны entity (UTF-16) сравниваются напрямую."""
    text, entities = _message_entities(message)
    spans = command_prefix.quoted_spans(entities)
    for entity in entities:
        etype = getattr(entity, "type", None)
        if etype not in ("mention", "text_mention"):
            continue
        offset = getattr(entity, "offset", None)
        length = getattr(entity, "length", None)
        if spans and isinstance(offset, int) and isinstance(length, int):
            end = offset + length
            if any(offset < span_end and span_start < end
                   for span_start, span_end in spans):
                continue            # цитируемый фрагмент — не обращение
        if etype == "mention":
            raw = entity.extract_from(text)
            if raw.removeprefix("@").lower() == _bot_username:
                return True
        elif etype == "text_mention":
            user = getattr(entity, "user", None)
            if user is not None and user.id == _bot_id:
                return True
    return False


def _is_direct_trigger(message: types.Message,
                       module_enabled: bool | None = None) -> bool:
    """Триггеры 1-4 (58.4 + R52-4) + master-гейт модуля.

    MOD-ACL-UX-01 M2.1: ``module_enabled`` — уже разрешённое per-chat
    состояние из канонического резолвера. ``None`` сохраняет синхронную
    legacy-семантику по глобальному слою (прямые вызовы/тесты). Runtime-
    handler использует `_is_direct_trigger_unscoped` после своего per-chat
    гейта, чтобы GLOBAL OFF + CHAT ON действительно работал.
    """
    if module_enabled is None:
        if not hot.get("flags.direct_chat_botword_enabled",
                       settings.DIRECT_CHAT_BOTWORD_ENABLED):
            return False
    elif not module_enabled:
        return False
    return _is_direct_trigger_unscoped(message)


def _direct_trigger_type(message: types.Message,
                         own_text: str | None = None) -> str | None:
    """Один раз определить тип адресации и происхождение командного текста.

    P0 DIRECT-TRIGGER (owner 26.11.2026): команда «бот» срабатывает только на
    СОбственном тексте участника (:func:`command_prefix.own_message_text`) —
    не на пересланном содержимом/подписи, не на цитируемом фрагменте, не на
    тексте стороннего бота. Reply-связь с ботом остаётся осознанным
    обращением независимо от вложенного материала.

    Приоритет прежний: reply → mention → имя персоны → keyword. Результат
    передаётся в сервис как есть (без повторной классификации).
    """
    reply_to = message.reply_to_message
    if reply_to is not None:
        reply_from = getattr(reply_to, "from_user", None)
        if reply_from is not None and reply_from.id == _bot_id:
            # Epic 72 (74.C, T-556): расшифровка — НЕ direct chat; гейт даёт
            # 0i транскрибировать голосовой реплай на неё штатно.
            if is_reply_to_transcription(message):
                return None
            return command_prefix.TRIGGER_REPLY_TO_BOT
    # Пересылка/чужой бот: содержимое не становится словами участника.
    if (command_prefix.is_forwarded(message)
            or command_prefix.sender_is_bot(message)):
        return None
    # Упоминание — по entities собственного события (mention без текста в
    # реальном Telegram невозможен, но entity — структурное доказательство).
    if _has_bot_mention(message):
        return command_prefix.TRIGGER_MENTION
    own = (own_text if own_text is not None
           else command_prefix.own_message_text(message))
    if not own:
        return None
    if _bot_username and re.search(rf"(?i)@{re.escape(_bot_username)}\b", own):
        return command_prefix.TRIGGER_MENTION
    # Раунд 10.15 (F6, T-1598): триггер = непустое Имя персоны. Имя задано →
    # обращение по имени (со склонениями); дефолтные ботворды ОТКЛЮЧАЮТСЯ.
    # Имя пусто → дефолтная keyword-ветка «бот»/«ботик»/«ботяра».
    persona_on = hot.get("flags.persona_enabled", settings.PERSONA_ENABLED)
    name_set = bool(str(bot_persona.get_cached_global_name() or "").strip())
    if persona_on and name_set:
        if command_prefix.name_mentioned(own):
            return command_prefix.TRIGGER_PERSONA_NAME
    # T-411 (R52-4): keyword-ветка под тем же master-гейтом модуля (F5):
    # «бот»/«ботохуета»/«ботина»/… Активна, только если НЕ (persona_enabled
    # AND name_set); master-флаг проверён выше на входе _is_direct_trigger.
    if (not (persona_on and name_set)) and _BOTWORD_RE.search(own):
        # H2 (review-fix): НЕ триггеримся на сообщения юзеров, за которыми
        # закреплены свои роутеры (alan 3 / kostik 2) — их «бот»-сообщения
        # уходят дальше по цепочке (0h → UNHANDLED). Reply/mention выше —
        # осознанное обращение к боту, исключение ТОЛЬКО для keyword-ветки.
        user = getattr(message, "from_user", None)
        uid = getattr(user, "id", None) if user is not None else None
        if uid in _BOTWORD_EXCLUDED_USER_IDS:
            return None
        return command_prefix.TRIGGER_KEYWORD
    return None


def _is_direct_trigger_unscoped(message: types.Message) -> bool:
    """Триггерная поверхность БЕЗ модульного master-гейта.

    Тонкая обёртка над единым классификатором `_direct_trigger_type`.
    Гейт модуля проверяется вызывающим: `_is_direct_trigger` (legacy/global)
    или `direct_chat_handler` (per-chat резолвер).
    """
    return _direct_trigger_type(message) is not None


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


@direct_chat_router.message(Command("style"))
async def cmd_style(message: types.Message, bot: Bot = None,
                    command: CommandObject = None) -> None:
    """MCA-08 (D3–D5, T-4903): скрытая /style — scoped-просьбы по стилю.

    K3 OFF → `None` от сервиса → UNHANDLED (команда неактивна: паритет
    2.58.54, меню bot_commands.py не меняется). R17: в лог — только
    chat/user/флаг.
    """
    if _service is None or bot is None or _bot_id is None:
        return UNHANDLED
    if not _command_user(message):
        return UNHANDLED
    args = (command.args or "") if command is not None else ""
    phrase = await mca_style_scope.handle_command(
        getattr(_service, "db", None), chat_id=message.chat.id,
        user_id=message.from_user.id, args=args)
    if phrase is None:
        return UNHANDLED                       # K3 OFF → команда неактивна
    await _reply(bot, message.chat.id, phrase, message.message_id)
    logger.info("[direct] /style | chat=%s user=%s",
                message.chat.id, message.from_user.id)


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
    # Раунд 10.15 (F6, T-1598): обращение по Имени персоны (со склонениями) —
    # «Олег, запомни …» работает как «бот, запомни …».
    tok, rest = command_prefix.split_prefix(text)
    if tok is not None:
        text = rest
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
    if command_prefix.sender_is_bot(message):
        # P0 (26.11.2026): текст стороннего бота — не слова участника
        # (командный запуск по чужому тексту недопустим).
        return UNHANDLED
    # ADD-TR.2 (ADTR-ENTRY): текст события = text ИЛИ caption подписи.
    # P0 (26.11.2026): для команд — собственный текст участника: пересылка
    # и цитируемые блоки не активируют «бот»-команду.
    text = command_prefix.own_message_text(message)
    if text.startswith("/"):
        return UNHANDLED                       # команды не перехватываются
    if not text and not _has_image_attachment(message):
        # Пустая подпись без картинки — прежнее поведение (голос/видео/
        # стикер и т.п. уходят в 0i и ниже). «Голое» photo/image-document
        # доходит до триггер-гейта: сработать может только осознанное
        # обращение (reply боту) — keyword/mention без текста невозможны.
        return UNHANDLED
    # MOD-ACL-UX-01 M2.1: master-флаг модуля решается per chat через
    # канонический резолвер (GLOBAL-дефолт → явный CHAT-override). Значение
    # передаётся в триггер-гейт, чтобы GLOBAL OFF + CHAT ON действительно
    # работал, а GLOBAL ON + CHAT OFF — нет.
    module_enabled = await feature_gates.module_enabled(
        message.chat.id, key="flags.direct_chat_botword_enabled",
        default=settings.DIRECT_CHAT_BOTWORD_ENABLED)
    if not module_enabled:
        return UNHANDLED
    # P0 (26.11.2026): триггер вычисляется ОДИН раз здесь и передаётся в
    # сервис — там больше нет собственной повторной классификации текста.
    # Собственный текст (`text`) уже посчитан выше и переиспользуется.
    trigger_type = _direct_trigger_type(message, own_text=text)
    if trigger_type is None:
        return UNHANDLED                       # не триггер → пропагация живёт
    # Раунд 10.15 (F6, T-1598, ADR-1015-1): «Префикс + канонический триггер» —
    # функциональная команда имеет наивысший приоритет и НЕ уходит в LLM.
    # Yield (UNHANDLED) → D49-пропагация доносит сообщение до 4e download
    # (search/youtube/web/checkup 0d–0g уже отработали ДО 0h). Review-fix M2:
    # yield только при ВКЛЮЧЁННОМ воркере, иначе сообщение не теряется и идёт
    # обычным путём LLM. Триггер без цели консьюмится функциональным воркером.
    group = command_prefix.functional_group(text)
    if group is not None and await _functional_module_active_for_chat(
            message.chat.id, group):
        return UNHANDLED
    # Раунд 4 (T-712, FR-D1): память-команды — ПОСЛЕ триггера, ДО handle.
    # Распознанный синтаксис → ответ/подтверждение + consumed (в LLM НЕ
    # уходит; команды работают даже при активном кулдауне диалога).
    parsed = _parse_memory_command(text)
    if parsed is not None:
        kind, arg = parsed
        return await _handle_memory_command(bot, message, kind, arg)
    await _service.handle(bot, message, user, trigger_type=trigger_type)
    return
