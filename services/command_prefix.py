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
import re

from config.settings import settings
from services import bot_persona
from services import command_registry
from services import hot_config as hot

#: Семейство ботвордов (используется, когда Имя не задано).
_DEFAULT_TOKENS: tuple[str, ...] = ("бот", "ботик", "ботяра")

#: F6-Q2: эвристические склонения (только при len(name) >= 3).
_NAME_SUFFIXES: tuple[str, ...] = (
    "", "а", "я", "у", "ю", "ом", "ем", "е", "ы", "и",
)

#: Разделитель префикса: «Олег загугли», «Олег, загугли», «Олег: загугли» …
_SEP = r"[\s,:.!\-]+"


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
