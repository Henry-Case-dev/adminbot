"""Раунд 10.20 (БЛОК 0, ADR-1020-1) — канонический контракт метаданных.

Единственная точка рендера строки контекста: LLM нигде не должна получать
«голый» текст, а только
`[Дата Время | Автор | ID | Переслано: Источник]: Текст`.

Канон формата (spec §2.2, ADR-1020-1 п.2):

* ``msg``     — ``[ДД.ММ.ГГГГ ЧЧ:ММ | Автор | ID | Переслано: Источник]: Текст``
* ``fact``    — ``[ММ.ГГГГ | Автор | fact:ID]: Текст``
* ``archive`` — ``[Архивная справка: ДД.ММ.ГГГГ | Автор | ID]: Текст``

Правила (R16):

* отсутствующие поля опускаются ВМЕСТЕ с разделителем (никаких ``None``/заглушек);
* ``\\n``/``\\t`` внутри полей схлопываются в пробел;
* автор/ID/источник НЕ выдумываются — если данных нет, сегмент опускается;
* ``kind="msg"`` показывает дату+время, ``fact``/``archive`` — только ММ.ГГГГ;
* рендер возвращает plain-строку (XML-экранирование — забота вызывающего).

Модуль также отдаёт ``format_chat_time`` — Time Injection БЛОК 5.1 (О2/ADR-1020-3):
строка ``[Текущее время в чате: DD.MM.YYYY, HH:MM, День недели]`` ставится
ПЕРВЫМ user-блоком (system-промпт остаётся статичным — prompt-cache не ломаем).
"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.target_marking import append_marker

logger = logging.getLogger(__name__)

KIND_MSG = "msg"
KIND_FACT = "fact"
KIND_ARCHIVE = "archive"

VALID_KINDS = (KIND_MSG, KIND_FACT, KIND_ARCHIVE)

# ── Двухъярусный контракт представления (ADR-1020-1 ред. 3, Р1/Р2) ──────────
# Реестр точек подачи контекста несёт `representation` + per-point `pattern`
# («нет голого текста»): инвентарный тест ГЕНЕРИРУЕТСЯ из реестра, а не из
# ручного списка.
REPRESENTATION_CANONICAL = "canonical"
REPRESENTATION_XML_ATTRS = "xml_attrs"
REPRESENTATION_BRACKET_HEADER = "bracket_header"
REPRESENTATION_LABEL_EXEMPT = "label_exempt"

VALID_REPRESENTATIONS = (
    REPRESENTATION_CANONICAL,
    REPRESENTATION_XML_ATTRS,
    REPRESENTATION_BRACKET_HEADER,
    REPRESENTATION_LABEL_EXEMPT,
)

# Служебные метки (НЕ элементы данных): «фон: …»/«широкий фон: …» внутри
# <Global_Context> (D5/T-802) и `_SELF_ECHO_INSTRUCTION` внутри <RAG_Memory>
# (F1/ADR-1014-2 D5). Держим строковыми префиксами, чтобы не тянуть импорт
# summary_memory в canonical_context (цикл: summary_memory → canonical_context).
# Синхронность с `summary_memory._SELF_ECHO_INSTRUCTION` проверяется тестом.
# 10.23 (F2, ADR-1023-2, R1023F2-07): структурная обёртка под-блока фактчека
# `<reply_chains …>` / `</reply_chains>` — не элемент данных (как label_exempt);
# внутренние строки цепочки каноничны.
CONTEXT_LABEL_EXEMPT_PREFIXES = (
    "фон: ",
    "широкий фон: ",
    "Ниже — твои ПРОШЛЫЕ слова.",
    "<reply_chains",
    "</reply_chains>",
)


def is_label_exempt(line) -> bool:
    """Служебная строка-метка (allowlist Р2) — критерию «нет голого текста»
    не подлежит. Пустая строка тоже exempt."""
    text = str(line or "").strip()
    if not text:
        return True
    return any(text.startswith(p) for p in CONTEXT_LABEL_EXEMPT_PREFIXES)


def canonical_line_pattern(kind: str = KIND_MSG) -> str:
    """Per-point regex канонического префикса для `format_context_item`.
    Заголовок может содержать ``]`` внутри (uid ``[10]``) → ленивый ``.*?``."""
    if kind == KIND_ARCHIVE:
        return r"^\[Архивная справка.*?\]: "
    if kind == KIND_FACT:
        return r"^\[\d{2}\.\d{4}.*?\]: "
    return r"^\[\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}.*?\]: "


@dataclasses.dataclass(frozen=True)
class ContextPoint:
    """Точка подачи контекста (spec §2.3): файл, kind, ярус представления и
    per-point pattern compliant-строки-элемента данных (None — у
    `label_exempt`/точек вне критерия)."""
    pid: str
    path: str
    kind: str
    description: str
    representation: str
    pattern: str | None = None


# Инвентаризация точек подачи контекста (spec §2.3 / T-1873/T-1874).
# Инвентарный тест «нет голого текста» генерируется из этого реестра.
CONTEXT_POINTS: tuple[ContextPoint, ...] = (
    ContextPoint(
        "chat_history", "services/summary_xml.py", KIND_MSG,
        "<chat_history> саммари", REPRESENTATION_XML_ATTRS,
        r'^<message [^>]*\bid="[^"]*"[^>]*\btimestamp="[^"]*"'
        r'[^>]*\bauthor="'),
    ContextPoint(
        "direct_global_verbatim", "services/direct_chat_service.py", KIND_MSG,
        "Direct <Global_Context> verbatim-хвост", REPRESENTATION_CANONICAL,
        canonical_line_pattern(KIND_MSG)),
    ContextPoint(
        "direct_thread", "services/direct_chat_service.py", KIND_MSG,
        "Direct <Conversation_Thread>/<Conversation_Branch>",
        # ярус A: user-ход — полный канон; бот-ход — ts ОПУЩЕН (источник
        # времени не хранит, R16) → допускаем канон без ts (автор+ID есть).
        REPRESENTATION_CANONICAL,
        r"^(?:\[\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}.*?\]: |\[[^\]]+.*?\]: )"),
    ContextPoint(
        "direct_rag", "services/direct_chat_service.py", KIND_FACT,
        "Direct <RAG_Memory>", REPRESENTATION_BRACKET_HEADER,
        # S10.20-9: обе формы — legacy `[ММ.ГГГГ | Автор: X] текст` и
        # обогащённый канон `[ММ.ГГГГ | X | fact:ID | Переслано: …]: текст`.
        r"^\[[^\]]+\] \[\d{2}\.\d{4}(?: \| [^\]]+)?\]:? "),
    ContextPoint(
        "legacy_rag", "services/summary_memory.py", KIND_FACT,
        "Legacy RAG <context> (search/factcheck/скрипты)",
        REPRESENTATION_BRACKET_HEADER,
        # S10.20-9: `_search_graph_facts` отдаёт 6-кортеж → канонический
        # header факта (`fact:ID`/`Переслано:`); старый 4-кортеж тоже валиден.
        r"^\[\d{2}\.\d{4}(?: \| [^\]]+)?\]:? "),
    ContextPoint(
        "dig_into_lore", "services/tool_router.py", KIND_MSG,
        "dig_into_lore messages/facts", REPRESENTATION_CANONICAL,
        canonical_line_pattern(KIND_MSG)),
    ContextPoint(
        "query_chat_memory", "services/tool_router.py", KIND_MSG,
        "query_chat_memory (основная ветка)", REPRESENTATION_BRACKET_HEADER,
        r"^\[[^\]]+ \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]\]: "),
    ContextPoint(
        "get_recent_history", "services/tool_router.py", KIND_MSG,
        "get_recent_history", REPRESENTATION_CANONICAL,
        canonical_line_pattern(KIND_MSG)),
    ContextPoint(
        "summary_archive", "services/summary_generator.py", KIND_ARCHIVE,
        "/summary архивная справка", REPRESENTATION_CANONICAL,
        canonical_line_pattern(KIND_ARCHIVE)),
    ContextPoint(
        "dream", "services/dream_prompts.py", KIND_FACT,
        "Сон/Дистилляция", REPRESENTATION_BRACKET_HEADER,
        r"^\d+\. \[\d{4}-\d{2}-\d{2}\] "),
    ContextPoint(
        "lore_worker", "services/lore_worker.py", KIND_MSG,
        "Авто-лор", REPRESENTATION_BRACKET_HEADER,
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] "),
    ContextPoint(
        "nostalgia", "services/nostalgia_worker.py", KIND_FACT,
        "Ностальгия", REPRESENTATION_BRACKET_HEADER,
        r"^(?:- )?\[[^\]]+\]"),
    ContextPoint(
        "factcheck_context", "services/factcheck_service.py", KIND_MSG,
        "Фактчек <chat_context> (+ <reply_chains>)", REPRESENTATION_CANONICAL,
        # 10.23 (F2, R1023F2-07): окно — канон с ts; вложенный <reply_chains>
        # добавляет бот-ходы без ts (источник времени не хранит, R16) — как в
        # direct_thread. Открытый/закрытый тег под-блока — label_exempt.
        r"^(?:\[\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}.*?\]: |\[[^\]]+.*?\]: )"),
    ContextPoint(
        "video_web_summary", "services/youtube_summarizer_service.py",
        KIND_FACT, "Видео/веб-выжимки (RAG-префикс)",
        REPRESENTATION_BRACKET_HEADER,
        r"^\[\d{2}\.\d{4} \| Автор: [^\]]+\] "),
)


_HEADER_RE = re.compile(r"^\[.*?\]:\s?")


def split_context_header(text) -> tuple[str, str]:
    """Ведущий канонический заголовок ``[header]:`` → ``(header, body)``.

    ``header`` включает закрывающую ``]:`` и один опциональный пробел;
    ``header + body == исходная строка`` (byte-инвариант реконструкции).
    Нет заголовка → ``("", текст)``."""
    source = str(text or "")
    match = _HEADER_RE.match(source)
    if not match:
        return "", source
    return match.group(0), source[match.end():]


def strip_context_header(line) -> str:
    """Срезает ведущий канонический заголовок ``^\\[[^\\]]*\\]:\\s?``.

    Обязателен там, где строка парсится как ``предикат: контент``
    (`direct_chat_service._line_markers` E1, `summary_memory._fact_tokens`
    F2) — иначе первое ``:`` уезжает внутрь заголовка (``msg:<id>``)."""
    return _HEADER_RE.sub("", str(line or ""), count=1)

ARCHIVE_MARKER = "Архивная справка"
STALE_SUFFIX = " (Внимание: возможно устарело)"

def _squash(value) -> str:
    """Поле контекста → строка без переводов строк/табов (прецедент
    `summary_memory._fact_prefix`: `" ".join(str(x).split())`)."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _fmt_ts(ts, *, with_time: bool) -> str:
    """unix ts → 'ДД.ММ.ГГГГ ЧЧ:ММ' (msg) / 'ММ.ГГГГ' (fact/archive).

    None/0/битый ts → '' (никогда не бросает — RAG не роняет мусорным ts).
    """
    if not ts:
        return ""
    try:
        seconds = int(ts)
    except (TypeError, ValueError):
        return ""
    if not seconds:
        return ""
    try:
        moment = datetime.datetime.fromtimestamp(
            seconds, datetime.timezone.utc)
    except (ValueError, OSError, OverflowError):
        return ""
    return moment.strftime("%d.%m.%Y %H:%M" if with_time else "%m.%Y")


def resolve_item_id(*, tg_message_id=None, message_id=None,
                    fact_id=None) -> str:
    """ID-политика ADR-1020-1 п.4: `tg:<tg_message_id>` → `msg:<id>` →
    `fact:<graph_facts.id>` → '' (данных нет — сегмент опускается, R16)."""
    if tg_message_id not in (None, "", 0):
        return f"tg:{tg_message_id}"
    if message_id not in (None, "", 0):
        return f"msg:{message_id}"
    if fact_id not in (None, "", 0):
        return f"fact:{fact_id}"
    return ""


def format_context_item(*, ts=None, author=None, item_id=None,
                        forward_source=None, text="", kind: str = KIND_MSG,
                        stale: bool = False, is_target: bool = False) -> str:
    """Каноническая строка контекста (spec §2.2).

    Поля-метаданные, которых нет, опускаются вместе с разделителем. Если
    метаданных нет вообще — возвращается сам текст (нечем размечать).
    ``stale=True`` добавляет существующий суффикс «(Внимание: возможно
    устарело)» ПОСЛЕ текста (прецедент `_stale_suffix`).
    ``is_target=True`` (раунд 10.23, F1, ADR-1023-1) дописывает ПОСЛЕ текста
    маркер `<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` (plain, без экранирования) —
    только для ``kind="msg"``; дефолт ``False`` → все прочие вызывающие
    байт-в-байт неизменны.
    """
    kind = (str(kind or KIND_MSG)).strip().lower()
    if kind not in VALID_KINDS:
        logger.warning("[canonical_context] unknown kind — fallback msg | "
                       "kind=%r", kind)
        kind = KIND_MSG
    with_time = kind == KIND_MSG
    stamp = _fmt_ts(ts, with_time=with_time)
    name = _squash(author)
    ident = _squash(item_id)
    source = _squash(forward_source)
    body = _squash(text)

    head: list[str] = []
    if kind == KIND_ARCHIVE:
        head.append(f"{ARCHIVE_MARKER}: {stamp}" if stamp else ARCHIVE_MARKER)
    elif stamp:
        head.append(stamp)
    if name:
        head.append(name)
    if ident:
        head.append(ident)
    if source:
        head.append(f"Переслано: {source}")
    if stale:
        body = f"{body}{STALE_SUFFIX}" if body else STALE_SUFFIX
    if is_target and kind == KIND_MSG:
        body = append_marker(body)
    if not head:
        return body
    return f"[{' | '.join(head)}]: {body}"


def format_fact_line(*, ts=None, author=None, fact_id=None, text="",
                     stale_suffix: bool = False) -> str:
    """Шорткат `kind="fact"` (RAG/граф); ``stale_suffix`` — существующий
    суффикс устаревания."""
    return format_context_item(
        ts=ts, author=author, item_id=fact_id, text=text, kind=KIND_FACT,
        stale=stale_suffix)


_WEEKDAYS_RU = (
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
)


def resolve_timezone(tz_name, fallback: str = "UTC") -> str:
    """Имя tz → валидное имя (неизвестное/пустое → ``fallback``).

    Реюз существующей tz-инфраструктуры: `limits.chat_timezone` (О4) с
    фолбэком на `limits.summary_timezone` (расписания воркеров НЕ трогаем).
    """
    for candidate in (tz_name, fallback):
        text = str(candidate or "").strip()
        if not text:
            continue
        try:
            ZoneInfo(text)
            return text
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return "UTC"


def format_chat_time(now=None, tz_name=None, *,
                     fallback_tz: str = "UTC") -> str:
    """Time Injection БЛОК 5.1 (О2): `[Текущее время в чате: DD.MM.YYYY,
    HH:MM, День недели]` в таймзоне чата.

    ``now`` — aware/naive/None (None → «сейчас» UTC). Строка ставится
    вызывающим ПЕРВЫМ user-блоком (`build_messages`) — system статичен.
    """
    resolved = resolve_timezone(tz_name, fallback=fallback_tz)
    if now is None:
        moment = datetime.datetime.now(datetime.timezone.utc)
    elif isinstance(now, (int, float)):
        moment = datetime.datetime.fromtimestamp(
            int(now), datetime.timezone.utc)
    else:
        moment = now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    try:
        local = moment.astimezone(ZoneInfo(resolved))
    except (ZoneInfoNotFoundError, ValueError, OverflowError):
        local = moment.astimezone(datetime.timezone.utc)
    weekday = _WEEKDAYS_RU[local.weekday()]
    return (f"[Текущее время в чате: {local.strftime('%d.%m.%Y')}, "
            f"{local.strftime('%H:%M')}, {weekday}]")
