"""Раунд 9 (AGI Memory, spec §3.5, T-826/T-827, Q10) — промпт-канон
ностальгии (слой B NostalgiaWorker) и хелперы рендера кандидатов/маркера
слоя A.

Канон-константа модуля `NOSTALGIA_PROMPT` (НЕ PG-сид и НЕ REGISTRY-ключ —
прецедент dream_prompts/lore_prompts; Q10). Финальный текст — spec §3.5.4:
системная роль токсично-тёплого участника, 1-2 фразы «кстати...», запрет
маркдауна/кавычек-ёлочек/длинных тире в ОТВЕТЕ, иначе ровно UNCHANGED.
Переменная `{max_words}` подставляется вызывающим из
limits(память) при каждом вызове.

Ниже — чистые функции форматирования (НЕ канон): маркер слоя A
(format_nostalgia_hint, spec §3.5.1), строки кандидата «год назад»
(format_year_back_line), user-блок для LLM (build_nostalgia_user) и
детект UNCHANGED (is_unchanged_response).
"""
import datetime
import re

# ── КАНОН (spec §3.5.4; не редактировать без PR) ────────────────────────────
NOSTALGIA_PROMPT = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день и/или старые факты по последней теме разговора. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""

_DEFAULT_MAX_WORDS = 60
_UNCHANGED = "UNCHANGED"


def is_unchanged_response(text: str | None) -> bool:
    """Ответ LLM равен ровно UNCHANGED (после strip, регистронезависимо —
    spec §3.5.4: «равенство с точностью до регистра/пробелов»)."""
    return bool(text and str(text).strip().upper() == _UNCHANGED)


def format_nostalgia_hint(fact_text: str, ts, cap_chars: int) -> str:
    """Маркер слоя A (spec §3.5.1/E1): одна строка
    `nostalgia_hint: вспомни и вплети, если уместно: [ГГГГ-ММ-ДД] текст`.
    Фикс-кап `cap_chars` ДО инжекта (обрезается текст факта, не метка).
    Пустой факт/нулевой кап → ""."""
    text = " ".join(str(fact_text or "").split())
    if not text:
        return ""
    date = _ts_date(ts)
    prefix = f"nostalgia_hint: вспомни и вплети, если уместно: [{date}] "
    cap = max(int(cap_chars or 0), 0)
    if cap <= 0:
        return ""
    budget = max(0, cap - len(prefix))
    if budget <= 0:
        return ""
    return prefix + text[:budget]


def _ts_date(ts) -> str:
    """unix ts → ГГГГ-ММ-ДД (local; битое/пустое → '????-??-??')."""
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "????-??-??"


def _speaker_name(row) -> str:
    """Имя автора строки smart_messages: author_name; пусто → «?»."""
    name = str(_row_get(row, "author_name") or "").strip()
    if name:
        return name
    uid = _row_get(row, "user_id")
    return str(uid) if uid not in (None, 0) else "?"


def _row_get(row, key: str, default=None):
    """Доступ к полю строки (dict ИЛИ sqlite3.Row/aiosqlite.Row)."""
    try:
        return row.get(key, default)
    except AttributeError:
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default


def format_year_back_line(row) -> str:
    """Строка кандидата «N лет назад» (spec §3.5.2): `[Имя ГГГГ-ММ-ДД]: текст`
    — рендер для LLM и лога."""
    text = " ".join(str(_row_get(row, "text") or "").split())
    if not text:
        return ""
    return (f"[{_speaker_name(row)} "
            f"{_ts_date(_row_get(row, 'timestamp'))}]: {text}")


def format_golden_line(row: dict) -> str:
    """Строка «золотого» факта (spec §3.5.2): `[ГГГГ-ММ-ДД] текст факта`."""
    text = " ".join(str(_row_get(row, "fact") or "").split())
    if not text:
        return ""
    ts = _row_get(row, "rag_ts") or _row_get(row, "created_at")
    return f"[{_ts_date(ts)}] {text}"


def build_nostalgia_user(year_lines: list[str], golden_lines: list[str]) -> str:
    """User-блок LLM-вызова (spec §3.5.4): «В чате давно тихо. Вот память:»
    + кандидаты (секции год-назад и старые факты по теме; пустые секции
    опускаются)."""
    parts: list[str] = []
    if year_lines:
        parts.append("События примерно год назад в этот день:\n"
                     + "\n".join(str(l) for l in year_lines))
    if golden_lines:
        parts.append("Старые факты по последней теме разговора:\n"
                     + "\n".join(f"- {l}" for l in golden_lines))
    if not parts:
        return ""
    return "В чате давно тихо. Вот память:\n" + "\n\n".join(parts)


def clean_llm_text(raw: str | None, cap_chars: int = 400) -> str:
    """Нормализация текста ответа LLM (spec §3.5.4): strip, схлопывание
    пробелов/пустых строк, кап `cap_chars` символов. UNCHANGED/пусто →
    "" (вызывающий решает статус по is_unchanged_response ДО обрезки)."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    cap = max(int(cap_chars or 0), 0)
    if cap > 0 and len(text) > cap:
        return text[:cap].rstrip()
    return text
