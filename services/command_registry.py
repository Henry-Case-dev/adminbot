"""Раунд 10.15 (F6, T-1594) — канонический реестр функциональных команд.

Точный маппинг из ТЗ §6 + UPD §2: 17 префиксных триггеров (search 3 /
youtube 4 / web 4 / checkup 3 / download 3) + bare-исключения ``чекап`` и
``фактчек`` (вызываются ОДНИМ СЛОВОМ, без префикса).

Код, без каталога (Δ=0): новые ключи настроек НЕ вводятся. Подстановка Имени
персоны вместо «Бот» выполняется резолвом префикса
(:mod:`services.command_prefix`), а не дублированием строк.

F6-U1: legacy-алиасы, не входящие в канон (``перескажи видос``, ``че в видосе``,
``поясни за статью``, ``че на сайте``, ``перескажи статью``, ``живой собака``,
``пульс бота``, ``как сервак``, ``спизди``, ``скачать``), из префиксного пути
УДАЛЕНЫ осознанно.

Review-fix M1 (14.09.2026): у КАЖДОГО триггера проверяется правая граница
слова ``(?![0-9a-zа-яё_])`` — «Бот, загуглика»/«Бот, транскриптер» больше не
матчатся как префикс более длинного слова.
"""
import re

#: Группа → канонические префиксные триггеры (регистронезависимо).
FUNCTIONAL_COMMANDS: dict[str, tuple[str, ...]] = {
    "search":   ("найди", "поищи", "загугли"),
    "youtube":  ("транскрипт", "че за видос", "о чем видео", "поясни за видос"),
    "web":      ("поясни за ссылку", "че по ссылке", "о чем статья", "выжимка"),
    "checkup":  ("ты в порядке", "живой?", "чекни здоровье"),
    "download": ("скачай", "загрузи", "стяни"),
}

#: Исключения: вызываются ОДНИМ СЛОВОМ (без префикса «Бот,/Имя,»).
BARE_COMMANDS: tuple[str, ...] = ("чекап", "фактчек")

#: Плоский список всех префиксных триггеров.
ALL_TRIGGERS: tuple[str, ...] = tuple(
    t for cmds in FUNCTIONAL_COMMANDS.values() for t in cmds)

#: Словесные границы: кириллица/латиница/цифры/`_` (Review-fix M1).
_CHAR_CLASS = "0-9a-zа-яё_"
_TAIL = rf"(?![{_CHAR_CLASS}])"
_HEAD = rf"(?<![{_CHAR_CLASS}])"


def _compile(triggers: tuple[str, ...], *, anchor: bool) -> re.Pattern:
    """Собрать regex группы: длинные триггеры первыми (иначе «поясни за видос»
    перехватится более коротким «поясни…»-префиксом). ``anchor`` — матч с
    начала строки (префиксный путь) vs поиск отдельного слова в любом месте."""
    body = "|".join(re.escape(t)
                    for t in sorted(triggers, key=len, reverse=True))
    head = "^" if anchor else _HEAD
    return re.compile(f"{head}(?:{body}){_TAIL}", re.IGNORECASE)


# Сборка один раз на уровне модуля.
_GROUP_START_RES = {g: _compile(t, anchor=True)
                    for g, t in FUNCTIONAL_COMMANDS.items()}
_GROUP_WORD_RES = {g: _compile(t, anchor=False)
                   for g, t in FUNCTIONAL_COMMANDS.items()}


def group_of(text: str) -> str | None:
    """Группа, чей канонический триггер начинает остаток, иначе None."""
    stripped = str(text or "").strip()
    if not stripped:
        return None
    for group, rx in _GROUP_START_RES.items():
        if rx.match(stripped):
            return group
    return None


def matches_group(group: str, text: str) -> bool:
    """Остаток начинается с триггера конкретной группы (search/youtube/...)."""
    rx = _GROUP_START_RES.get(group)
    return bool(rx and rx.match(str(text or "").strip()))


def has_trigger_word(group: str, text: str) -> bool:
    """Триггер группы встречается как ОТДЕЛЬНОЕ слово в любом месте текста.

    Используется youtube/web, где триггер может стоять не в начале остатка
    (Review-fix M1: границы с обеих сторон отсекают «транскриптер»)."""
    rx = _GROUP_WORD_RES.get(group)
    return bool(rx and rx.search(str(text or "")))
