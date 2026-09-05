"""Раунд 7 (chat-lore-management-v2, T-775/C1) — канон промптов авто-лора.

Верх файла — КАНОН-константы `LORE_MERGE_SYSTEM_PROMPT` и
`LORE_INIT_SYSTEM_PROMPT` (правки — ТОЛЬКО через PR, как все каноны; тексты
дословно из spec §3.6). Переменная `{max_words}` подставляется из горячего
ключа `limits.lore_max_words` при каждом вызове:

    LORE_MERGE_SYSTEM_PROMPT.format(max_words=150)

Ниже — чистые функции форматирования (НЕ канон): инжект-блок, урезание с
маркером, разбор UNCHANGED, нормализация, user-контент merge/init (spec §3.6).
"""
import re

# ── КАНОН (spec §3.6; не редактировать без PR) ──────────────────────────────
LORE_MERGE_SYSTEM_PROMPT = """\
Ты архивариус чата. У тебя есть текущий лор чата, новые сообщения за последнее время
и защищённые факты о чате.

Обнови лор: сохрани всё постоянное (история чата, ключевые люди и их статусы, мемы,
устоявшийся вайб), перепиши устаревшее, разреши противоречия. Игнорируй микро-события:
разовые шутки, бытовые реплики, то, что не имеет значения для новичка.

Верни связный текст на русском, 1-3 абзаца, максимум {max_words} слов, в стиле сообщений
этого чата. Не используй кавычки-ёлочки и длинные тире.

Если за окно не случилось ничего глобального и лор обновлять не нужно, верни ровно
строку: UNCHANGED
"""

LORE_INIT_SYSTEM_PROMPT = """\
Ты архивариус чата. По сообщениям чата за последнее время составь лор чата: кто эти
люди, чем живёт чат, ключевые мемы, истории, статусы, вайб.

Верни связный текст на русском, 1-3 абзаца, максимум {max_words} слов, в стиле сообщений
этого чата. Не используй кавычки-ёлочки и длинные тире.

Если в окне нет ничего глобального, верни ровно строку: UNCHANGED
"""

_UNCHANGED = "UNCHANGED"
_MARKER = "\n…[обрезано]"
_SEP = "\n---\n"
_TAG_OVERHEAD = len("<chat_lore>\n") + len("\n</chat_lore>")


def is_unchanged_response(text: str | None) -> bool:
    """Ответ LLM равен ровно UNCHANGED (после strip, регистронезависимо)."""
    return bool(text and text.strip().upper() == _UNCHANGED)


def normalize_lore(text: str) -> str:
    """Нормализация текста лора: strip + схлопывание пустых строк до абзацев."""
    if not text:
        return ""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cut_at_boundary(text: str) -> str:
    """Обрезка по границе: сначала абзац (\n\n), затем конец предложения
    (spec §3.6: «по границе абзаца, затем предложения»)."""
    best = -1
    end = 0
    idx = text.rfind("\n\n")
    if idx > best:
        best, end = idx, idx + 2
    for delim in (". ", "! ", "? ", "… ", "\n"):
        idx = text.rfind(delim)
        if idx > best:
            best, end = idx, idx + len(delim)
    if best <= 0:
        return text
    return text[:end].rstrip()


def truncate_with_marker(text: str, limit: int) -> str:
    """Обрезать текст до `limit` символов (по границе абзаца/предложения);
    при обрезке в конец добавляется маркер «…[обрезано]» ВНУТРИ бюджета limit.
    Уже влезающий текст возвращается как есть (без маркера)."""
    if not text:
        return ""
    limit = max(0, int(limit))
    if len(text) <= limit:
        return text
    budget = max(0, limit - len(_MARKER))
    if budget <= 0:
        return ""
    return _cut_at_boundary(text[:budget]) + _MARKER


def format_lore_block(manual_lore: str, auto_lore: str, cap_chars: int) -> str:
    """Инжект-блок (spec §3.6/Q1): `<chat_lore>…</chat_lore>`, ВЕСЬ блок
    ≤ cap_chars (теги/разделитель входят в бюджет); разделитель `---` ТОЛЬКО
    при двух непустых полях; пустой блок — "" (не рендерится). Урезается
    в первую очередь auto_lore, при необходимости — manual_lore; при обрезке
    добавляется маркер. (XML-экранирование — на вызывающем.)"""
    manual = (manual_lore or "").strip()
    auto = (auto_lore or "").strip()
    if not manual and not auto:
        return ""
    cap = max(int(cap_chars or 0), 0)
    if cap <= _TAG_OVERHEAD:
        return ""                       # теги не помещаются — блока нет
    budget = cap - _TAG_OVERHEAD        # бюджет содержимого (с ---)

    def fits(a: str, b: str) -> bool:
        if a and b:
            return len(a) + len(_SEP) + len(b) <= budget
        return len(a or b) <= budget

    if fits(manual, auto):
        return _wrap(manual, auto)
    # 1) урезаем auto_lore (spec: auto первым)
    if auto:
        room = budget - len(manual) - len(_SEP) if manual else budget
        auto = truncate_with_marker(auto, max(0, room))
    # 2) если всё ещё не влезает — урезаем manual_lore
    if not fits(manual, auto):
        room = budget - len(auto) - (len(_SEP) if auto and manual else 0)
        manual = truncate_with_marker(manual, max(0, room))
    # 3) страховочный жёсткий урез составного текста
    if not fits(manual, auto):
        inner = manual
        if manual and auto:
            inner = f"{manual}{_SEP}{auto}"
        elif auto:
            inner = auto
        return (f"<chat_lore>\n"
                f"{truncate_with_marker(inner, budget)}\n</chat_lore>")
    return _wrap(manual, auto)


def _wrap(manual: str, auto: str) -> str:
    inner = manual
    if manual and auto:
        inner = f"{manual}{_SEP}{auto}"
    elif auto:
        inner = auto
    return f"<chat_lore>\n{inner}\n</chat_lore>"


def format_merge_user_content(auto_lore: str, window_text: str,
                              facts: list[str] | None = None) -> str:
    """User-контент merge-режима (spec §3.6): текущий авто-лор (или
    «(нет)»), окно сообщений, защищённые факты (без legacy-константы)."""
    auto = (auto_lore or "").strip()
    parts = [f"Текущий авто-лор чата:\n{auto}" if auto
             else "Текущий авто-лор чата:\n(нет)"]
    parts.append(f"Новые сообщения чата (окно):\n{window_text}")
    if facts:
        parts.append("Защищённые факты о чате:\n"
                     + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


def format_init_user_content(window_text: str,
                             facts: list[str] | None = None) -> str:
    """User-контент INIT-режима (auto_lore пуст): без секции текущего лора."""
    parts = [f"Новые сообщения чата (окно):\n{window_text}"]
    if facts:
        parts.append("Защищённые факты о чате:\n"
                     + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


# ── хелперы сборки user-контента (интерфейс постановки; поверх spec-функций) ──

def build_merge_user(auto_lore: str, messages: list[str] | tuple[str, ...],
                     window_hours: int | None = None,
                     facts: list[str] | None = None) -> str:
    """Merge-режим: строки окна (уже оформленные `[ts] имя: текст` воркером)
    → единый user-контент. window_hours — опциональная пометка окна в шапке
    (None → ровно формат spec §3.6 без часов)."""
    window = "\n".join(str(m) for m in messages)
    auto = (auto_lore or "").strip()
    parts = [f"Текущий авто-лор чата:\n{auto}" if auto
             else "Текущий авто-лор чата:\n(нет)"]
    if window_hours:
        parts.append(f"Новые сообщения чата (окно, последние "
                     f"{int(window_hours)} ч):\n{window}")
    else:
        parts.append(f"Новые сообщения чата (окно):\n{window}")
    if facts:
        parts.append("Защищённые факты о чате:\n"
                     + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


def build_init_user(messages: list[str] | tuple[str, ...],
                    window_hours: int | None = None,
                    facts: list[str] | None = None) -> str:
    """INIT-режим (auto_lore пуст): только окно (+факты); merge-секции нет."""
    window = "\n".join(str(m) for m in messages)
    parts = []
    if window_hours:
        parts.append(f"Новые сообщения чата (окно, последние "
                     f"{int(window_hours)} ч):\n{window}")
    else:
        parts.append(f"Новые сообщения чата (окно):\n{window}")
    if facts:
        parts.append("Защищённые факты о чате:\n"
                     + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)
