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
# PREV_NOSTALGIA_PROMPT — байт-в-байт слепок канона ДО ревампа round 10.15
# (T-1579/T-1580, ADR-1013-3): служит для отката/диффа. НЕ удалять.
PREV_NOSTALGIA_PROMPT = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день и/или старые факты по последней теме разговора. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""

# Новый канон round 10.15 (ТЗ §3): «давний участник, которого пробило на
# воспоминания», ирония/сленг из лора, анти-«робот-архивариус».
NOSTALGIA_PROMPT = """\
Ты - тот же токсично-тёплый участник чата. В чате давно тихо. Тебе дают кусок памяти чата: события примерно год назад в этот день, старые факты по последней теме, а также лор чата и список местных мемов. Вбрось этот старый факт так, как будто ты давний участник беседы, которого внезапно пробило на воспоминания: с иронией и сленгом из лора, по-свойски, будто вспомнил вслух. Не пиши как робот-архивариус. Если вспомнить уместно и по делу - напиши 1-2 короткие фразы «кстати...» в своём стиле: ленивая печать, без маркдауна, без кавычек-ёлочек и длинных тире. Максимум {max_words} слов в ответе.

Если вспоминать неуместно или память бедна - ответь ровно одним словом: UNCHANGED
"""

# Капы инжекта Лора/мемов (spec §4, F4-Q2): лор важнее мемов (идёт выше).
_LORE_MAX_CHARS = 600        # лор — обрезка по границе слова
_MEMES_LIMIT = 10            # число мемов
_MEME_MAX_CHARS = 120        # обрезка текста одного мема

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


def _collapse(text) -> str:
    """Санитизация строки: схлопывание любых пробелов/переводов строк."""
    return " ".join(str(text or "").split())


def _cap_words(text: str, cap: int) -> str:
    """Обрезка до `cap` символов по границе слова (кап лора)."""
    if cap <= 0:
        return ""
    if len(text) <= cap:
        return text
    cut = text[:cap]
    head = cut.rsplit(" ", 1)[0].rstrip()
    return head or cut.rstrip()


def _cap_chars(text: str, cap: int) -> str:
    """Жёсткая обрезка до `cap` символов (кап текста одного мема)."""
    if cap <= 0:
        return ""
    return text[:cap].rstrip() if len(text) > cap else text


def _render_meme(row) -> str:
    """Строка мема: `- {fact}`; при непустом `target_user` → `- [label] {fact}`
    (R16: target_user — имя-лейбл, не id). Пустой факт → ""."""
    fact = _cap_chars(_collapse(_row_get(row, "fact")), _MEME_MAX_CHARS)
    if not fact:
        return ""
    target = _collapse(_row_get(row, "target_user"))
    return f"- [{target}] {fact}" if target else f"- {fact}"


def build_nostalgia_user(year_lines: list[str], golden_lines: list[str],
                         lore: str = "", memes=None) -> str:
    """User-блок LLM-вызова (spec §3.5.4 + round 10.15 §4): «В чате давно
    тихо. Вот память:» + кандидаты (год-назад, старые факты по теме) +
    аддитивные секции «Лор чата»/«Локальные мемы» (пустые секции
    опускаются; всё пусто → ""). Сигнатура обратно совместима: вызов
    `build_nostalgia_user(year, golden)` работает как раньше."""
    parts: list[str] = []
    if year_lines:
        parts.append("События примерно год назад в этот день:\n"
                     + "\n".join(str(l) for l in year_lines))
    if golden_lines:
        parts.append("Старые факты по последней теме разговора:\n"
                     + "\n".join(f"- {l}" for l in golden_lines))
    lore_text = _cap_words(_collapse(lore), _LORE_MAX_CHARS)
    if lore_text:
        parts.append("Лор чата (как тут принято общаться):\n" + lore_text)
    meme_lines = [l for l in (_render_meme(r)
                              for r in (memes or [])[:_MEMES_LIMIT]) if l]
    if meme_lines:
        parts.append("Локальные мемы (местные ярлыки и шутки):\n"
                     + "\n".join(meme_lines))
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
