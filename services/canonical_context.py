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


# ── EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 §4.2 (GLOBAL-OUTPUT-BOUNDARY-01) ─────
# Одна структура — ДВЕ проекции в этом же модуле (нового сервиса/движка нет).
#
# Машинная сторона неизменна: `resolve_item_id` продолжает отдавать
# `tg:/msg:/fact:`, `format_context_item` остаётся сырым рендером по
# умолчанию — его используют L1/планировщик/retrieval/dedup/attribution,
# которым нужны настоящие ID (§5.4 прямо разрешает типизированные refs
# специализированным стадиям; ADR-1020-1 п.4).
#
# Речевая сторона — `format_speech_item` (+ `SpeechProjection`): тот же набор
# полей (абсолютное время, автор, forward, цитата, отношения), но вместо
# транспортных ключей — стабильные метки прогона с ОБРАТНЫМ отображением на
# реальные ID. Метки — адресная разметка, НЕ часть реплики: они стоят в
# заголовке строки и в явных отношениях, никогда внутри цитируемого текста
# участника (§4.3 п.3, §9.5 п.1).
#
# Обратная карта живёт ровно один прогон и уходит в run-манифест
# (`SpeechProjection.manifest()`): пары «метка → ID» и счётчики типов, без
# приватных текстов (§7 «логи — ID, коды»).
REPRESENTATION_INTERNAL = "internal"
REPRESENTATION_WRITER = "writer"
REPRESENTATION_EXPLICIT_ADMIN_DIAGNOSTIC = "explicit_admin_diagnostic"
VALID_SPEECH_REPRESENTATIONS = (
    REPRESENTATION_INTERNAL,
    REPRESENTATION_WRITER,
    REPRESENTATION_EXPLICIT_ADMIN_DIAGNOSTIC,
)

SPEECH_LABEL_MESSAGES = "M"
SPEECH_LABEL_FACTS = "F"
SPEECH_LABEL_PEOPLE = "U"

# Роль элемента в прогоне (§5.4 «Зачем включено»): проверяемое сообщение
# помечается в теле, не в адресной разметке.
SPEECH_ROLE_TARGET = "target"
SPEECH_TARGET_ROLE_PREFIX = "(цель проверки) "

# Типы отношений (§4.3 п.4, §9.5 п.2): подтверждённый Reply, семантическая
# связь (НЕ Reply) и известная, но не извлечённая связь.
RELATION_REPLY = "reply"
RELATION_SEMANTIC = "semantic"
RELATION_MISSING_EDGE = "missing_edge"
VALID_RELATION_KINDS = (RELATION_REPLY, RELATION_SEMANTIC, RELATION_MISSING_EDGE)

# Компактная форма клауз (§5.1/§5.2, R7 «дельта размера <= 0»): длинные
# пояснения на каждый reply-ход съедали бюджет под-блока цепочек
# (`_REPLY_CHAINS_MAX_CHARS` = 1200, keep-end) и молча вытесняли корень
# цепочки. Смысл тот же: подтверждённый Reply, семантическая связь (НЕ Reply)
# и известная-но-неизвлечённая связь остаются различимыми, а занимают на
# ~24 символа меньше на ход.
SPEECH_RELATION_REPLY = "↳ Reply {label}"
SPEECH_RELATION_SEMANTIC = "↳ по теме {label} (не Reply)"
SPEECH_RELATION_SEMANTIC_UNRESOLVED = (
    "↳ по теме (не Reply; реплика вне доступного окна)")
SPEECH_RELATION_MISSING_EDGE = (
    "↳ родитель вне доступного окна (связь известна)")
SPEECH_RELATION_UNRESOLVED = (
    "↳ связь не подтверждена (реплика вне доступного окна)")
SPEECH_QUOTE_AUTHOR_UNKNOWN = "автор цитаты не определён"

# Роль «бот» в речевой форме (§5.4 «и самого бота», §13 сц.116): сырой вид
# помечал бот-хода `[bot]`, речевая проекция этот маркер теряла — прошлый
# ответ бота становился неотличим от реплики человека без user id. Метка роли
# фиксированная (не сервисный id, не user id) и живёт в поле автора.
SPEECH_BOT_ROLE = "бот"
SPEECH_BOT_LABEL = f"({SPEECH_BOT_ROLE})"

# Тип служебного поля по префиксу ref'а — для манифеста (только типы/счётчики).
_REF_FIELD_TYPES = {"tg": "tg_id", "msg": "msg_id", "fact": "fact_id"}

# Метка речевой проекции: `M12` / `F3` / `U7` (санитайзер вставки).
SPEECH_LABEL_RE = re.compile(r"^[MFU]\d+$")


# Типизированное чтение рубильника (§6.2 + B3 ревью). Ключ осознанно НЕ
# регистрируется в `param_catalog` (Δ каталога = 0, конвенция kill-switch
# репозитория), поэтому `hot_config._coerce` его не типизирует и значением
# может прийти jsonb-строка. `bool("false") is True` — здесь это давало
# «строковый OFF читается как ON»; ниже строка разбирается явно.
_FLAG_TRUE_TOKENS = frozenset({"true", "1", "yes", "on", "enabled"})
_FLAG_FALSE_TOKENS = frozenset({"false", "0", "no", "off", "disabled"})


def coerce_switch_flag(value, default: bool = True) -> bool:
    """Рубильник из нетипизированного источника → bool.

    Принимает ``bool``, числа (``0``/``1``) и строки в обоих регистрах
    (``"false"``/``"off"``/``"0"`` → OFF). Пустое значение = «не задано» →
    ``default``. Неизвестное значение НЕ включает и НЕ выключает молча —
    тоже ``default`` с предупреждением."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = str(value).strip().lower()
    if not token:
        return default                      # «не задано» ≠ «выключено»
    if token in _FLAG_TRUE_TOKENS:
        return True
    if token in _FLAG_FALSE_TOKENS:
        return False
    logger.warning("[canonical_context] неизвестное значение рубильника "
                   "проекции — default | value=%r", value)
    return default


def speech_projection_enabled() -> bool:
    """Единый рубильник речевой проекции (§6.2), читается В САМОМ ШВЕ.

    Значение берётся из hot-ключа ``flags.context_speech_projection``
    (ConfigCache, дефолт ON) на КАЖДОМ рендере — без кэша в шве, поэтому
    изменение значения в живом кэше конфигурации действует со следующего
    payload без рестарта. Строковые jsonb-значения типизируются
    (`coerce_switch_flag`), затем дефолт из Settings (env
    ``CONTEXT_SPEECH_PROJECTION_ENABLED``).

    Честная граница (B3 ревью): ключ НЕ зарегистрирован в `param_catalog`,
    поэтому у него нет админ-тумблера в Mini App, а `PUT /api/config` его
    отвергает (422 «неизвестный ключ»). Откат — значением
    `flags.context_speech_projection` в `bot_settings` (подхватывается
    ConfigCache'ом при загрузке/записи кэша) либо env-флагом с рестартом;
    per-module флагов нет.
    """
    value = None
    try:
        from services import hot_config
        value = hot_config.get("flags.context_speech_projection", None)
    except Exception:                       # hot-кэш не должен ронять рендер
        logger.debug("[canonical_context] hot-ключ проекции недоступен",
                     exc_info=True)
    default = True
    if value is None:
        try:
            from config.settings import settings
            default = getattr(
                settings, "CONTEXT_SPEECH_PROJECTION_ENABLED", True)
        except Exception:                   # pragma: no cover — Settings нет
            default = True
        value = default
    return coerce_switch_flag(value, bool(default))


def ref_field_type(item_id) -> str:
    """``tg:123`` → ``tg_id``; ``msg:9`` → ``msg_id``; ``fact:4`` → ``fact_id``.
    Всё остальное → ``""`` (не служебный ref)."""
    head = str(item_id or "").split(":", 1)[0].strip().lower()
    return _REF_FIELD_TYPES.get(head, "")


def _label_prefix_for(item_id: str) -> str:
    """Префикс метки по типу ref'а: факты — отдельная нумерация (``F``)."""
    return (SPEECH_LABEL_FACTS if ref_field_type(item_id) == "fact_id"
            else SPEECH_LABEL_MESSAGES)


@dataclasses.dataclass
class SpeechProjection:
    """Проекция одного прогона: ``label -> реальный идентификатор``.

    ``representation`` — какое представление реально ушло в payload
    (§9.4): ``writer`` (речевая проекция), ``internal`` (сырой машинный вид),
    ``explicit_admin_diagnostic`` (RBAC-канал диагностики).

    Метки выдаются по первому появлению и НЕ переиспользуются внутри прогона;
    `reserve` позволяет пред-регистрировать их в порядке хронологии, когда
    рендер идёт не в хронологическом порядке (§4.3 п.3).
    """

    run_id: str = ""
    representation: str = REPRESENTATION_WRITER
    _item_labels: dict = dataclasses.field(default_factory=dict)
    _label_items: dict = dataclasses.field(default_factory=dict)
    _person_labels: dict = dataclasses.field(default_factory=dict)
    _label_people: dict = dataclasses.field(default_factory=dict)
    _suppressed: dict = dataclasses.field(default_factory=dict)
    _sequence: dict = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        representation = str(self.representation or "").strip().lower()
        if representation not in VALID_SPEECH_REPRESENTATIONS:
            logger.warning(
                "[canonical_context] unknown speech representation — "
                "fallback writer | representation=%r", self.representation)
            representation = REPRESENTATION_WRITER
        self.representation = representation

    # ── метки ────────────────────────────────────────────────────────────
    def _next_label(self, prefix: str) -> str:
        number = self._sequence.get(prefix, 0) + 1
        self._sequence[prefix] = number
        return f"{prefix}{number}"

    def record_suppressed(self, field_type) -> None:
        """Учесть тип служебного поля, вынесенного из речевой проекции.

        Манифест пишет то, что реально ушло (§9.3 п.7): типы и счётчики, не
        декларация «not_exposed»."""
        name = str(field_type or "").strip()
        if name:
            self._suppressed[name] = self._suppressed.get(name, 0) + 1

    def message_label(self, item_id) -> str:
        """``tg:1234``/``msg:9``/``fact:4`` → ``M1``/``M1``/``F1`` (стабильно в
        рамках прогона). Пустой ref → ``""`` (сегмент заголовка опускается)."""
        raw = str(item_id or "").strip()
        if not raw:
            return ""
        known = self._item_labels.get(raw)
        if known:
            return known
        label = self._next_label(_label_prefix_for(raw))
        self._item_labels[raw] = label
        self._label_items[label] = raw
        self.record_suppressed(ref_field_type(raw))
        return label

    def reserve(self, item_ids) -> None:
        """Пред-регистрация меток в порядке хронологии прогона."""
        for item_id in item_ids or ():
            self.message_label(item_id)

    def label_of_item(self, item_id) -> str | None:
        raw = str(item_id or "").strip()
        return self._item_labels.get(raw) if raw else None

    def person_label(self, user_id=None, display_name="", *,
                     is_bot: bool = False) -> str:
        """Участник → ``"Имя (U3)"``. Одноимённые люди НЕ сливаются: ключ —
        user id (§5.4, §13 сц.12/97). Без user id метки нет — честно без
        адресации вместо ложного слияния.

        Бот получает ФИКСИРОВАННУЮ метку роли ``бот`` вместо ``U``-метки
        (§5.4 «и самого бота», §13 сц.116): собственный прошлый ответ бота
        нельзя перепутать с репликой человека, у которой нет user id.
        Метка роли не занимает номер участника и не попадает в обратную
        карту людей (это не человек)."""
        name = _squash(display_name)
        if is_bot:
            # Имя-роль («бот») уже и есть метка роли — не дублируем её.
            if not name or name.lower() == SPEECH_BOT_ROLE:
                return SPEECH_BOT_ROLE
            return f"{name} {SPEECH_BOT_LABEL}"
        key = ""
        if user_id not in (None, "", 0):
            key = str(user_id).strip()
            if key.isdigit():
                key = str(int(key))
        if not key:
            return name
        label = self._person_labels.get(key)
        if label is None:
            label = self._next_label(SPEECH_LABEL_PEOPLE)
            self._person_labels[key] = label
            self._label_people[label] = key
            self.record_suppressed("user_id")
        return f"{name} ({label})" if name else label

    def raw_of(self, label) -> str | None:
        """Обратное отображение метки: ``M1``→``tg:123``, ``U3``→user id."""
        key = str(label or "").strip()
        if not key:
            return None
        raw = self._label_items.get(key)
        if raw is not None:
            return raw
        return self._label_people.get(key)

    def manifest(self) -> dict:
        """Run-манифест прогона: пары «метка → ID» и счётчики. Без текстов.

        ``items`` — все адресуемые элементы контекста (``tg:``/``msg:`` и
        ``fact:`` графа), ``participants`` — люди по user id."""
        return {
            "run_id": self.run_id,
            "representation": self.representation,
            "items": dict(self._label_items),
            "participants": dict(self._label_people),
            "counts": {
                "labels": len(self._label_items) + len(self._label_people),
                "items": len(self._label_items),
                "participants": len(self._label_people),
            },
            "suppressed_field_types": sorted(self._suppressed),
            "suppressed_field_counts": dict(sorted(self._suppressed.items())),
        }


@dataclasses.dataclass(frozen=True)
class SpeechQuote:
    """Выделенная цитата хода в речевом виде: автор — имя/метка, не число.

    Семантика доставки (``original_available``/``priority_subject``) —
    паритет с сырой аннотацией `thread_chain._quote_annotation` (§9.5 п.1:
    цитату нельзя терять, её источник нельзя терять)."""

    text: str
    author_name: str = ""
    author_uid: int | None = None
    original_available: bool | None = None
    priority_subject: bool = False

    def render(self, projection=None) -> str:
        quote_text = str(self.text or "").strip()
        if not quote_text:
            return ""
        author = ""
        if projection is not None:
            author = projection.person_label(self.author_uid, self.author_name)
        elif str(self.author_name or "").strip():
            author = _squash(self.author_name)
        author = author or SPEECH_QUOTE_AUTHOR_UNKNOWN
        base = f"цитата (автор: {author}): «{quote_text}»"
        if self.original_available is False:
            return (f"{base} — выделенный фрагмент, оригинал недоступен "
                    f"(контекст ограничен)")
        if self.priority_subject:
            return (f"{base} — выделенный фрагмент оригинала, ПРИОРИТЕТНЫЙ "
                    f"ПРЕДМЕТ ответа; полное исходное сообщение — контекст")
        return f"{base} (выделенный фрагмент оригинала выше по цепочке)"


@dataclasses.dataclass(frozen=True)
class SpeechRelation:
    """Отношение элемента к другому сообщению — ЯВНО (§4.3 п.4).

    ``reply`` печатается только при подтверждённом Telegram Reply,
    ``semantic`` — только при подтверждённом семантическом основании, и
    никогда под видом Reply (§9.5 п.2). Связь без извлечённого сообщения —
    `missing_edge` без выдуманной метки (§8)."""

    kind: str
    target_item_id: str = ""
    basis: str = ""

    def render(self, projection=None) -> str:
        """Компактная клауза отношения (смысл полный, форма короткая).

        Длинная пояснительная форма на каждый reply-ход раздувала под-блок
        цепочек на 10–28 % и на узком маршруте молча вытесняла корень
        (§5.1/§5.2, R7). Поэтому: `↳ Reply M2` — только подтверждённый
        Telegram Reply; `↳ по теме M1 (не Reply)` — семантическая связь с
        явным отрицанием Reply; `↳ родитель вне доступного окна (связь
        известна)` — известная, но не извлечённая связь без выдуманного
        идентификатора."""
        kind = str(self.kind or "").strip().lower()
        label = ""
        if projection is not None and self.target_item_id:
            label = projection.label_of_item(self.target_item_id) or ""
        if kind == RELATION_REPLY:
            if not label:
                return SPEECH_RELATION_MISSING_EDGE
            return SPEECH_RELATION_REPLY.format(label=label)
        if kind == RELATION_SEMANTIC:
            if not label:
                return SPEECH_RELATION_SEMANTIC_UNRESOLVED
            return SPEECH_RELATION_SEMANTIC.format(label=label)
        if kind == RELATION_MISSING_EDGE or not label:
            return SPEECH_RELATION_MISSING_EDGE
        return SPEECH_RELATION_UNRESOLVED


def format_speech_item(*, ts=None, author=None, item_id=None,
                       forward_source=None, text="", kind: str = KIND_MSG,
                       stale: bool = False, is_target: bool = False,
                       role: str = "", projection=None, author_uid=None,
                       relations=(), quote=None, is_bot: bool = False) -> str:
    """РЕЧЕВАЯ проекция канонической строки (§4.2 п.2).

    Тот же заголовок и то же тело, что у `format_context_item` (абсолютное
    время, автор, `Переслано:`, архивная пометка), но в слоте ID — метка
    прогона, автор — «Имя (U3)», а связи/цитата печатаются явно.
    ``is_bot`` сохраняет роль автора в речевой форме (`Adminbot (бот)`) —
    §5.4 «и самого бота», §13 сц.116.

    Откат: флаг OFF (§6.2) или отсутствие `projection` → сырой канон
    байт-в-байт (без меток и без явных отношений — ровно поведение до шва).
    """
    if projection is None or not speech_projection_enabled():
        return format_context_item(
            ts=ts, author=author, item_id=item_id,
            forward_source=forward_source, text=text, kind=kind,
            stale=stale, is_target=is_target)

    display_author = ""
    if author not in (None, "") or is_bot:
        display_author = projection.person_label(
            author_uid, author, is_bot=is_bot)
    elif author_uid not in (None, "", 0):
        display_author = projection.person_label(author_uid, "")
    label = projection.message_label(item_id)

    body = _squash(text)
    if stale:
        body = f"{body}{STALE_SUFFIX}" if body else STALE_SUFFIX
    if is_target and kind == KIND_MSG:
        body = append_marker(body)
    if str(role or "").strip().lower() == SPEECH_ROLE_TARGET:
        body = (f"{SPEECH_TARGET_ROLE_PREFIX}{body}" if body
                else SPEECH_TARGET_ROLE_PREFIX.strip())

    quote_line = quote.render(projection) if quote is not None else ""
    extra = [quote_line] if quote_line else []
    for relation in relations or ():
        line = (relation.render(projection)
                if isinstance(relation, SpeechRelation)
                else _squash(relation))
        if line:
            extra.append(line)
    if extra:
        body = f"{body} {' '.join(extra)}" if body else " ".join(extra)

    return format_context_item(
        ts=ts, author=display_author, item_id=label,
        forward_source=forward_source, text=body, kind=kind)


def emit_speech_projection_event(projection, *, chat_id=None,
                                 message_id=None, run_id=None) -> None:
    """§9.4/§13 сц.109 + §4.5/§7: в защищённой трассе — точное соответствие
    метки и реального ID, счётчики и КОРРЕЛЯЦИЯ с прогоном.

    Корреляция (R1 ревью): ``chat_id`` + ``message_id`` (ход-якорь) —
    штатные поля события MCA, ``run_id``/``trace_id`` — идентификатор
    прогона (``SpeechProjection.run_id``). Без них событие было durable, но
    не привязывалось к конкретному factcheck-прогону. Только ID/коды, без
    приватных текстов (§7). Fail-open: телеметрия не рвёт рендер."""
    if projection is None:
        return
    try:
        from services.mca_events import emit_mca_event
        manifest = projection.manifest()
        correlation = str(run_id or manifest.get("run_id") or "").strip()
        anchor = message_id
        if isinstance(anchor, str):
            anchor = int(anchor) if anchor.strip().isdigit() else None
        chat_ref = chat_id
        if isinstance(chat_ref, str):
            chat_ref = int(chat_ref) if chat_ref.strip().lstrip("-").isdigit() \
                else None
        entity_ids = {
            "items": manifest["items"],
            "participants": manifest["participants"],
            "counts": manifest["counts"],
            "suppressed_field_types": manifest["suppressed_field_types"],
        }
        if correlation:
            entity_ids["run_id"] = correlation
        emit_mca_event(
            "speech_projection", outcome="success", component="context",
            stage="speech_projection", status=manifest["representation"],
            chat_id=chat_ref, message_id=anchor,
            **({"trace_id": correlation} if correlation else {}),
            entity_ids=entity_ids)
    except Exception:
        pass


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
