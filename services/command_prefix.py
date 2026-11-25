"""Раунд 10.15 (F6, T-1594) — резолв динамического префикса команд.

Триггер системы — **непустое `active_persona.name`** (sync-кэш глобального
имени, гейт `flags.persona_enabled`). Никакого флага-рубильника:

- **Имя непусто** (напр. «Олег»): префикс = имя (+ эвристические склонения при
  ``len(name) >= 3``); дефолтные ботворды ``бот``/``ботик``/``ботяра``
  отключаются (см. `handlers.direct_chat`).
- **Имя пусто**: префикс = семейство ``бот``/``ботик``/``ботяра``; дефолтные
  триггеры остаются активными (мягкий переход).

Разделитель префикса: пробел / ``,`` / ``:`` / ``!`` / дефис (ADR-1015-1).
Код, без каталога (Δ=0), sync-путь без блокирующих PG-запросов.
"""
import logging
import re

from config.settings import settings
from services import bot_persona
from services import command_registry
from services import hot_config as hot

logger = logging.getLogger(__name__)

#: Семейство ботвордов (используется, когда Имя не задано).
_DEFAULT_TOKENS: tuple[str, ...] = ("бот", "ботик", "ботяра")

#: F6-Q2: эвристические склонения (только при len(name) >= 3).
_NAME_SUFFIXES: tuple[str, ...] = (
    "", "а", "я", "у", "ю", "ом", "ем", "е", "ы", "и",
)

#: Разделитель префикса: «Олег загугли», «Олег, загугли», «Олег: загугли» …
_SEP = r"[\s,:.!\-]+"

# ── P0 DIRECT-TRIGGER (owner 26.11.2026): командный текст и его происхождение ─
# Единственный источник настраиваемого семейства обращений-«ботвордов»:
# handlers.direct_chat и services.direct_chat_service используют ЭТИ объекты,
# поэтому повторной независимой классификации того же текста нет.
BOTWORD_PATTERN_DEFAULT = (
    r"(?i)(?<![0-9a-zа-яё_./])бот(?:ина|яра|ик|охуета|охуйня)?(?![0-9a-zа-яё_])"
)


def compile_botword(pattern: str) -> "re.Pattern[str]":
    """Скомпилировать конфигурируемый паттерн; битый → дефолт + WARNING."""
    try:
        return re.compile(pattern)
    except re.error:
        logger.warning(
            "CHAT_BOTWORD_PATTERN invalid regex — using default (D104)")
        return re.compile(BOTWORD_PATTERN_DEFAULT)


BOTWORD_RE = compile_botword(
    hot.get("reactions.chat_botword_pattern", settings.CHAT_BOTWORD_PATTERN))


def keyword_mentioned(text: str) -> bool:
    """Командное слово семейства «бот» в переданном (уже собственном) тексте."""
    return bool(BOTWORD_RE.search(str(text or "")))


#: Типы адресации, которые считаются действительным обращением к боту.
TRIGGER_KEYWORD = "keyword"
TRIGGER_MENTION = "mention"
TRIGGER_PERSONA_NAME = "persona_name"
TRIGGER_REPLY_TO_BOT = "reply_to_bot"
TRIGGER_FREE_WILL = "free_will"
GENUINE_TRIGGERS = frozenset({
    TRIGGER_KEYWORD, TRIGGER_MENTION, TRIGGER_PERSONA_NAME,
    TRIGGER_REPLY_TO_BOT,
})


def is_genuine_address(trigger_type) -> bool:
    """Действительное обращение к боту (не фоновая инициатива/free_will)."""
    return trigger_type in GENUINE_TRIGGERS


#: Entity-типы цитируемых блоков внутри собственного текста (не «свои слова»).
_QUOTED_ENTITY_TYPES = frozenset({"blockquote", "expandable_blockquote"})

_FORWARD_ORIGIN_TYPES: tuple = ()
try:                        # real aiogram MessageOrigin union (Bot API 7+)
    from aiogram import types as _tg_types
    _FORWARD_ORIGIN_TYPES = (
        _tg_types.MessageOriginUser, _tg_types.MessageOriginHiddenUser,
        _tg_types.MessageOriginChat, _tg_types.MessageOriginChannel)
except Exception:           # pragma: no cover - aiogram всегда установлен
    _FORWARD_ORIGIN_TYPES = ()


def _entities(value):
    return value if isinstance(value, (list, tuple)) else ()


def quoted_spans(entities) -> tuple[tuple[int, int], ...]:
    """UTF-16-диапазоны цитируемых блоков (``blockquote``) из entities."""
    raw: list[tuple[int, int]] = []
    for ent in _entities(entities):
        if getattr(ent, "type", None) not in _QUOTED_ENTITY_TYPES:
            continue
        offset = getattr(ent, "offset", None)
        length = getattr(ent, "length", None)
        if isinstance(offset, int) and isinstance(length, int) and length > 0:
            raw.append((offset, offset + length))
    if not raw:
        return ()
    raw.sort()
    merged: list[tuple[int, int]] = [raw[0]]
    for start, end in raw[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def strip_spans(text: str, spans) -> str:
    """Удалить UTF-16-диапазоны (Telegram offset/length) из строки."""
    if not isinstance(text, str) or not text or not spans:
        return text
    encoded = text.encode("utf-16-le")
    parts: list[bytes] = []
    prev = 0
    for start, end in spans:
        start_b = max(0, min(start * 2, len(encoded)))
        end_b = max(start_b, min(end * 2, len(encoded)))
        if prev < start_b:
            parts.append(encoded[prev:start_b])
        parts.append(" ".encode("utf-16-le"))       # не склеивать соседние слова
        prev = max(prev, end_b)
    if prev < len(encoded):
        parts.append(encoded[prev:])
    return b"".join(parts).decode("utf-16-le", errors="ignore")


def is_forwarded(message) -> bool:
    """Сам факт пересылки по Telegram-метаданным (не по имени источника).

    ``forward_origin`` — актуальный признак Bot API 7+; скрытый источник
    (``MessageOriginHiddenUser``) — тоже пересылка. Legacy-поля
    ``forward_from``/``forward_sender_name`` намеренно не читаются: проект
    уже стандартизован на ``forward_origin`` (filters/work_word.py и др.).
    """
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return False
    if _FORWARD_ORIGIN_TYPES and isinstance(origin, _FORWARD_ORIGIN_TYPES):
        return True
    # Тест-двойники/сериализованные origin несут строковый ``type``.
    return isinstance(getattr(origin, "type", None), str)


def sender_is_bot(message) -> bool:
    """Сообщение отправлено ботом (в т.ч. сторонним) — не слова участника."""
    user = getattr(message, "from_user", None)
    return getattr(user, "is_bot", False) is True


def own_message_text(message) -> str:
    """Собственный текст участника для КОМАНДНОГО триггера.

    Пересылка (``forward_origin``) или сообщение стороннего бота → "":
    содержимое не становится словами отправителя, даже если имя источника
    скрыто. Внутри собственного текста цитируемые блоки
    (``blockquote``/``expandable_blockquote``) исключаются; нативная цитата
    ``Message.quote`` в ``text`` не входит по построению Bot API.

    Полный текст события (``_message_user_text``/``_effective_text``)
    по-прежнему доступен семантическим путям: пересланное и цитаты остаются
    в контексте разговора, ограничивается только активация команды.
    """
    if is_forwarded(message) or sender_is_bot(message):
        return ""
    text = getattr(message, "text", None)
    entities = getattr(message, "entities", None)
    if not isinstance(text, str):
        text = getattr(message, "caption", None)
        entities = getattr(message, "caption_entities", None)
    if not isinstance(text, str):
        return ""
    spans = quoted_spans(entities)
    if spans:
        text = strip_spans(text, spans)
    return text.strip()


def active_name() -> str:
    """Непустое имя персоны (sync-кэш) или ``''`` (гейт `flags.persona_enabled`)."""
    if not hot.get("flags.persona_enabled", settings.PERSONA_ENABLED):
        return ""
    return str(bot_persona.get_cached_global_name() or "").strip()


def command_prefix_tokens() -> tuple[str, ...]:
    """Имя+склонения при непустом имени, иначе ботворд-семейство. Всё lower."""
    name = active_name().lower()
    if not name:
        return _DEFAULT_TOKENS
    if len(name) < 3:
        return (name,)
    return tuple(sorted({name + s for s in _NAME_SUFFIXES}))


def split_prefix(text: str) -> tuple[str | None, str]:
    """(совпавший токен, остаток) | (None, исходный текст). Только НАЧАЛО строки."""
    raw = str(text or "").lstrip()
    for tok in command_prefix_tokens():
        m = re.match(rf"(?i)^{re.escape(tok)}(?![0-9a-zа-яё_])(?:{_SEP})", raw)
        if m:
            return tok, raw[m.end():].lstrip()
    return None, text


def split_prefix_anywhere(text: str, url_before=None
                          ) -> tuple[str | None, str, int]:
    """(токен, остаток, позиция токена) — префикс в ЛЮБОМ месте строки.

    Follow-up R10.15-1: сценарий «ссылка-первой» из гайда F7
    (``https://youtu.be/… Олег, поясни за видос``) — обращение стоит ПОСЛЕ
    ссылки, поэтому якорный :func:`split_prefix` его не видит. Позиция
    (индекс начала токена) даёт вызывающему проверить, что URL стоит ДО
    обращения (приоритет «URL раньше триггера»). ``None, text, -1`` — нет
    префикса. :func:`split_prefix` (якорь ``^``) не изменён.

    Follow-up R10.15-10: при ПОВТОРНОМ обращении в строке
    (``эй Олег, смотри URL Олег, поясни…``) выбирается первое вхождение, перед
    которым ``url_before(prefix)`` истинно; если такого нет — последнее
    вхождение (команда обычно хвостовая). Без ``url_before`` поведение прежнее
    (первый токен реестра, его первое вхождение) — контракт не ломается."""
    raw = str(text or "")
    toks = command_prefix_tokens()
    if url_before is None:
        for tok in toks:
            m = re.search(
                rf"(?i)(?<![0-9a-zа-яё_]){re.escape(tok)}"
                rf"(?![0-9a-zа-яё_])(?:{_SEP})", raw)
            if m:
                return tok, raw[m.end():].lstrip(), m.start()
        return None, text, -1
    matches: list[tuple[int, int, str]] = []
    for tok in toks:
        for m in re.finditer(
                rf"(?i)(?<![0-9a-zа-яё_]){re.escape(tok)}"
                rf"(?![0-9a-zа-яё_])(?:{_SEP})", raw):
            matches.append((m.start(), m.end(), tok))
    if not matches:
        return None, text, -1
    for start, end, tok in matches:
        if url_before(raw[:start]):
            return tok, raw[end:].lstrip(), start
    start, end, tok = max(matches, key=lambda m: m[0])
    return tok, raw[end:].lstrip(), start


def name_mentioned(text: str) -> bool:
    """Обращение по имени персоны (со склонениями, word-boundary) в любом месте."""
    raw = str(text or "")
    if not raw:
        return False
    for tok in command_prefix_tokens():
        if re.search(
                rf"(?i)(?<![0-9a-zа-яё_]){re.escape(tok)}(?![0-9a-zа-яё_])",
                raw):
            return True
    return False


def functional_group(text: str) -> str | None:
    """Группа «Префикс + канонический триггер» (search/youtube/... или None).

    Review-fix M2: direct_chat-yield должен знать, чей воркер включается, чтобы
    не «съесть» сообщение при выключенном модуле."""
    tok, rest = split_prefix(text)
    if tok is None:
        return None
    return command_registry.group_of(rest)
