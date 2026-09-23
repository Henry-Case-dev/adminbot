"""S5 round1026 (ADR-1026-7 D1/D4/D6) — L2 «Писатель» (§96–§99).

**Автономный модуль S5** (в живой путь врезается за флагом
``flags.summary_hybrid_l2_enabled``; с S10/ADR-1026-12 D2 default **ON**,
явный ``false`` — аварийный kill-switch): вход — контент-секция
``FactPackage`` (S4, §96) → **ровно 1 LLM-вызов** L2 → парсер строгого
JSON-документа §99 → детерминированный валидатор (структура §98, запрет
выдуманных цитат/приписанных реплик, изоляция ID) → fail-closed ``L2Result``.

Инварианты (ADR-1026-7):
  * **ровно 1 вызов L2-слоя** (целевой пайплайн S5 = 2: L1+L2; третий вызов —
    блокер). Вход — контент пакета (§96), без ``service``/``budget``/
    ``unassigned_message_ids`` и без сырого лога;
  * **выход §99** — структурированный документ
    ``{schema_version:1, title, paragraphs:[{text, emphasis|null}]}``;
    лишние поля/типы → ``invalid``; L2 НЕ форматирует HTML (§99);
  * **§97-качество**: умеренная ирония допустима, приоритет — точность;
    **выдуманные цитаты не публикуются** (нет нормализованного совпадения с
    текстами пакета → снятие кавычек + WARN), **приписанные реплики** →
    fail-closed ``invalid`` (``quote_attribution``); сырые ID/``fact:``/``msg:``
    вырезаются;
  * **слот §82 — env-only** (D3): ``SUMMARY_L2_BASE_URL``/``SUMMARY_L2_MODEL_NAME``
    /``SUMMARY_L2_API_KEY`` (ClassVar, Δ каталога = 0), hot-first резолв,
    пусто → глобальная основная модель (наследование ≠ аварийное
    резервирование);
  * **логи §108/§109 аддитивны и R17-safe**: ``L2_START``/``L2_COMPLETE``/
    ``L2_ERROR``/``L2_SKIPPED`` — только числа/коды/id (без ключей, текстов и
    сырого ответа); узлы ExecutionGraph НЕ эмитятся (их эмитит S8);
  * fail-closed (§106): ``empty``/``invalid``/``error`` → публикации нет,
    legacy-фолбэка НЕТ (это был бы третий вызов).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
import unicodedata

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMError
from services.prompt_style_blocks import resolve_prompt
from services.summary_prompts import SUMMARY_L2_WRITER_SYSTEM_PROMPT
# S7 (ADR-1026-9 D6/SC-07): §109-детали ошибки — http_status/attempts.
from services.summary_run_log import attempts_of, http_status_of
from services.system2_handoff import parse_json_object
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

MODULE = "summary"
STEP = "l2_writer"
PROMPT_PG_KEY = "prompts.summary_l2_writer_system_prompt"

# ── Схема §99 (единый источник для парсера/валидатора/тестов) ──────────────

SCHEMA_VERSION = 1
TITLE_MAX = 200
PARAGRAPH_MAX = 900
# Жёсткий потолок блоков Article (Bot API 500 блоков; 498 — с запасом на
# служебный H1/обложку, D2).
MAX_PARAGRAPHS_HARD = 498
# Совместимость с `limits.max_summary_parts` (существующий ключ, D2/D4).
MAX_PARAGRAPHS_DEFAULT = 6
RICH_MAX_CHARS = 32000

TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {"schema_version", "title", "paragraphs"})
PARAGRAPH_FIELDS: frozenset[str] = frozenset({"text", "emphasis"})

# Статусы L2Result (D6). ok — публикуемо; empty/invalid/error — fail-closed.
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_INVALID = "invalid"
STATUS_ERROR = "error"

# Коды причин (R17-safe: только коды, без контента модели).
REASON_OK = "ok"
REASON_EMPTY_RESPONSE = "empty_response"
REASON_INVALID_JSON = "invalid_json"
REASON_UNKNOWN_FIELD = "unknown_field"
REASON_BAD_TYPE = "bad_type"
REASON_BAD_SCHEMA_VERSION = "bad_schema_version"
REASON_INVALID_TITLE = "invalid_title"
REASON_INVALID_PARAGRAPH = "invalid_paragraph"
REASON_INVALID_EMPHASIS = "invalid_emphasis"
REASON_TOO_MANY_PARAGRAPHS = "too_many_paragraphs"
REASON_TOO_LONG = "too_long"
REASON_QUOTE_ATTRIBUTION = "quote_attribution"
REASON_NO_PACKAGE = "no_package"
REASON_PACKAGE_NOT_DELIVERABLE = "package_not_deliverable"
REASON_NOT_BUILT = "not_built"
REASON_LLM_ERROR = "llm_error"
REASON_LLM_TIMEOUT = "llm_timeout"
REASON_INTERNAL_ERROR = "internal_error"

# Режимы детализации ON-пути (D4): serious/casual — короче, deep_research —
# больше абзацев. Legacy-блоки `MODE_CASUAL_*` на ON НЕ применяются.
DETAIL_DEFAULT = "serious"
_DETAIL_PARAGRAPH_HINT = {"casual": 4, "serious": 6, "deep_research": 10}

# Цитаты: «…» "…" „…" “…” ‹…› (разные кавычки одного уровня) + одиночные
# `'…'`/`‚…‘` и восточные `「…」`/`『…』` (S-R1026S5-2, defense-in-depth).
# L-R1026S5-6 (S6/ADR-1026-11 D7): ASCII-апостроф — кавычка ТОЛЬКО по границам
# слова: `'` внутри слова (`don't`, `it's`) не открывает/не закрывает цитату.
_QUOTE_RE = re.compile(
    r"«[^»]*»|\"[^\"]*\"|„[^“]*“|“[^”]*”|‹[^›]*›|"
    r"『[^』]*』|「[^」]*」|‚[^‘]*‘|(?<!\w)'[^']*'(?!\w)")
_WS_RE = re.compile(r"\s+")
# Сырые ID/служебные метки (§4.4/D6): вырезаются из текста.
_FACT_ID_RE = re.compile(r"\bfact\s*:\s*\d+\b", re.IGNORECASE)
_MSG_ID_RE = re.compile(r"\bmsg\s*:\s*\d+\b", re.IGNORECASE)
_PHANTOM_BRACKET_RE = re.compile(r"\[\s*\d{2}\.\d{4}\s*\|")
# Именованная атрибуция реплики: `Имя: «…»` либо `«…», — сказал Имя`.
_ATTR_PREFIX_RE = re.compile(r"([A-Za-zА-Яа-яЁё0-9_@\-]{2,30})\s*:")
_ATTR_VERB_RE = re.compile(
    r"[»\"],?\s*[—\-–]?\s*(сказал|сказала|написал|написала|заявил|заявила|"
    r"ответил|ответила|добавил|добавила|произнёс|произнес|воскликнул|"
    r"воскликнула)\b(?:\s+([A-Za-zА-Яа-яЁё0-9_@\-]{2,30}))?",
    re.IGNORECASE)


class L2SlotError(RuntimeError):
    """Слот L2 не резолвится (§82): fail-closed до врезки (T-3335)."""


@dataclasses.dataclass(frozen=True)
class L2Slot:
    """Резолв слота summary L2 §82 (env-only, D3)."""

    base_url: str
    model: str
    api_key: str
    dedicated: bool


@dataclasses.dataclass(frozen=True)
class L2Result:
    """Fail-closed-результат L2 (ADR-1026-7 D1/D6).

    ``document`` — канонический §99-документ (только при ``ok``); ``usage`` —
    ``{input_tokens, output_tokens}`` (или ``None``); ``metrics`` — аддитивные
    счётчики (абзацы/длительность/violations) для S7/S8; ``invalid_reason`` —
    R17-safe код причины.
    """

    status: str
    document: dict | None
    invalid_reason: str | None
    usage: dict | None
    metrics: dict
    duration_ms: float

    @property
    def usable(self) -> bool:
        """Документ допустим к публикации (§99/§106): только ``ok``."""
        return self.status == STATUS_OK and self.document is not None

    def as_metrics(self) -> dict:
        """Аддитивные счётчики для S7/S8 (без узлов ExecutionGraph)."""
        return dict(self.metrics or {})


def _make_result(status: str, *, document=None, reason=None, usage=None,
                 metrics=None, duration_ms=0.0) -> L2Result:
    return L2Result(status=status, document=document, invalid_reason=reason,
                    usage=usage, metrics=metrics or {}, duration_ms=duration_ms)


def invalid_result(reason: str, **kwargs) -> L2Result:
    """Fail-closed ``invalid``: ``document=None`` — публиковать нечего."""
    return _make_result(STATUS_INVALID, reason=reason, **kwargs)


def error_result(reason: str, **kwargs) -> L2Result:
    """``error``: исключение/``LLMError`` — без тихой потери (WARN L2_ERROR)."""
    return _make_result(STATUS_ERROR, reason=reason, **kwargs)


def empty_result(**kwargs) -> L2Result:
    """``empty``: пустой/непригодный вход (пакет не deliverable)."""
    return _make_result(STATUS_EMPTY, **kwargs)


# ── Слот §82 (env-only, D3) ────────────────────────────────────────────────

def resolve_l2_slot(*, hot_get=None, settings_obj=None) -> L2Slot:
    """Согласованная пара (``base_url``, ``model``) + ключ слоя summary L2.

    Приоритет рантайма — hot-first (forward-compatible с будущими PG-ключами
    ``models.summary_l2_*``/``keys.summary_l2_api_key``, S6), дефолты —
    env-only ClassVars ``SUMMARY_L2_*`` (Δ каталога = 0). Пустое поле пары
    добирается из глобальной основной модели; ``dedicated=True``, если задан
    хотя бы один из трёх env-ключей слоя. Секрет не логируется (R17).
    """
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings

    def _read(key: str, field: str) -> str:
        return str(hot_get(key, getattr(st, field, "")) or "").strip()

    raw_base = _read("models.summary_l2_base_url", "SUMMARY_L2_BASE_URL")
    raw_model = _read("models.summary_l2_model_name", "SUMMARY_L2_MODEL_NAME")
    raw_key = _read("keys.summary_l2_api_key", "SUMMARY_L2_API_KEY")
    global_base = _read("models.llm_base_url", "LLM_BASE_URL")
    global_model = _read("models.llm_model_name", "LLM_MODEL_NAME")
    global_key = str(hot_get("keys.llm_api_key",
                             getattr(st, "LLM_API_KEY", "")) or "").strip()
    return L2Slot(
        base_url=raw_base or global_base,
        model=raw_model or global_model,
        api_key=raw_key or global_key,
        dedicated=bool(raw_base or raw_model or raw_key))


def resolve_l2_slot_safe(*, hot_get=None, settings_obj=None) -> L2Slot:
    """Fail-closed-обёртка резолва слота L2 (T-3335, L-R1026S3-1).

    Любая ошибка резолва → :class:`L2SlotError` (fail-closed: L2 не
    вызывается); в сообщении нет секретов (R17).
    """
    try:
        return resolve_l2_slot(hot_get=hot_get, settings_obj=settings_obj)
    except L2SlotError:
        raise
    except Exception as exc:  # pragma: no cover - защитная ветка
        raise L2SlotError("l2 slot resolve failed") from exc


def resolve_l2_max_paragraphs(*, hot_get=None, settings_obj=None) -> int:
    """Эффективный кап абзацев: ``limits.max_summary_parts`` (D2/D4)."""
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings
    raw = hot_get("limits.max_summary_parts",
                  getattr(st, "MAX_SUMMARY_PARTS", MAX_PARAGRAPHS_DEFAULT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = MAX_PARAGRAPHS_DEFAULT
    if value <= 0:
        value = MAX_PARAGRAPHS_DEFAULT
    return min(value, MAX_PARAGRAPHS_HARD)


# ── Пакет §96: доступ к контент-секции (изоляция) ──────────────────────────

def _package_threads(package) -> list:
    if not isinstance(package, dict):
        return []
    threads = package.get("threads")
    return threads if isinstance(threads, list) else []


def _package_text_pool(package) -> list[str]:
    """Тексты пакета для пост-валидации цитат: ``facts ∪ fragments`` (§4.4).

    ``service``/``budget``/``unassigned_message_ids`` в пул НЕ входят
    (изоляция §96); тексты берутся verbatim (нормализуются при сравнении).
    """
    pool: list[str] = []
    for thread in _package_threads(package):
        if not isinstance(thread, dict):
            continue
        for fact in thread.get("facts") or []:
            if isinstance(fact, dict) and isinstance(fact.get("text"), str):
                pool.append(fact["text"])
        for fragment in thread.get("fragments") or []:
            if isinstance(fragment, dict) and isinstance(fragment.get("text"), str):
                pool.append(fragment["text"])
    return pool


# ── Вход L2 (§96, компактность) ────────────────────────────────────────────

def build_l2_input(package: dict, *, detail: str = "serious") -> str:
    """Собрать контент-секцию ``FactPackage`` для L2 (§96, D1).

    На тему: ``name``/``description``/``chronology`` (только timestamp/порядок)
    /``facts[].text`` + ``evidence_message_ids``/отобранные ``fragments[].text``.
    ``service``/``budget``/``unassigned_message_ids`` в контент НЕ идут; сырой
    лог повторно не передаётся. Формат — компактные JSON-строки, детерминиро-
    ванный порядок; ``detail`` — уровень детализации (serious/casual — короче,
    deep_research — подробнее).
    """
    detail_value = str(detail or DETAIL_DEFAULT).strip().lower()
    if detail_value not in _DETAIL_PARAGRAPH_HINT:
        detail_value = DETAIL_DEFAULT
    content = {
        "schema_version": SCHEMA_VERSION,
        "detail": detail_value,
        "threads": [],
    }
    for thread in _package_threads(package):
        if not isinstance(thread, dict):
            continue
        chronology = []
        for entry in thread.get("chronology") or []:
            if isinstance(entry, dict):
                chronology.append({
                    "message_id": entry.get("message_id"),
                    "timestamp": entry.get("timestamp"),
                })
        facts = []
        for fact in thread.get("facts") or []:
            if isinstance(fact, dict):
                facts.append({
                    "text": fact.get("text"),
                    "evidence_message_ids": list(
                        fact.get("evidence_message_ids") or []),
                })
        fragments = []
        for fragment in thread.get("fragments") or []:
            if isinstance(fragment, dict):
                fragments.append({
                    "message_id": fragment.get("message_id"),
                    "text": fragment.get("text"),
                })
        content["threads"].append({
            "thread_id": thread.get("thread_id"),
            "name": thread.get("name"),
            "description": thread.get("description"),
            "chronology": chronology,
            "facts": facts,
            "fragments": fragments,
        })
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return ("ПАКЕТ ФАКТОВ (компактный JSON; пиши статью по нему; "
            "служебные поля не передаются):\n" + body)


# ── Парсер (переиспользует политику system2_handoff) ───────────────────────

def parse_l2_document(raw: str) -> tuple[dict | None, str | None]:
    """Строгий разбор ответа L2: ``(document | None, reason)``.

    ``ok`` | ``empty_response`` (пустой ответ) | ``invalid_json`` (не JSON /
    не объект). Фенсы/обрамление/reasoning-теги снимает существующий
    ``system2_handoff.parse_json_object`` (политика не переписывается).
    """
    source = str(raw or "")
    if not source.strip():
        return None, REASON_EMPTY_RESPONSE
    data = parse_json_object(source)
    if not isinstance(data, dict):
        return None, REASON_INVALID_JSON
    return data, REASON_OK


# ── Нормализация/сравнение цитат (§4.4) ────────────────────────────────────

def _normalize_text(value: str) -> str:
    """Casefold + схлопывание пробелов (NFKC)."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return _WS_RE.sub(" ", text).strip().casefold()


def _normalize_quote(value: str) -> str:
    """Нормализованное ядро цитаты без обрамляющих кавычек/пунктуации."""
    return _normalize_text(value).strip("«»„“”\"'‹› .,;:!?—–-")


def _quote_matches_pool(quote: str, pool_normalized: list[str]) -> bool:
    core = _normalize_quote(quote)
    if not core:
        return False
    return any(core in candidate for candidate in pool_normalized)


def _strip_quotes(quote: str) -> str:
    """Снять обрамляющие кавычки (перевести в косвенную речь, §4.4).

    L-R1026S5-6: ASCII-апостроф снимается только как ПАРНАЯ кавычка `'…'`
    (её матчит `_QUOTE_RE` по границам слова); одиночный `'` из fallback-strip
    исключён — апостроф внутри слова (`don't`) кавычкой не считается.
    """
    for left, right in (("«", "»"), ("„", "“"), ("“", "”"), ("‹", "›"),
                        ("『", "』"), ("「", "」"), ("‚", "‘"),
                        ("'", "'"), ("\"", "\"")):
        if (len(quote) > len(left) + len(right)
                and quote.startswith(left) and quote.endswith(right)):
            return quote[len(left):len(quote) - len(right)]
    return quote.strip("\"«»„“”‹›『』「」‚‘")


def _strip_raw_ids(text: str) -> tuple[str, int]:
    """Вырезать ``fact:``/``msg:``/сырые служебные метки (D6, §4.4)."""
    count = 0
    out, n = _FACT_ID_RE.subn("", text)
    count += n
    out, n = _MSG_ID_RE.subn("", out)
    count += n
    out, n = _PHANTOM_BRACKET_RE.subn("", out)
    count += n
    if count:
        out = _WS_RE.sub(" ", out).strip()
    return out, count


def _has_named_attribution(quote: str, paragraph: str) -> bool:
    """Есть ли именованная атрибуция реплики рядом с цитатой (§4.4)."""
    index = paragraph.find(quote)
    if index < 0:
        return False
    before = paragraph[max(0, index - 40):index]
    # Контекст ПОСЛЕ цитаты включает её закрывающую кавычку (regex ждёт её).
    after = paragraph[max(0, index + len(quote) - 1):index + len(quote) + 60]
    if _ATTR_PREFIX_RE.search(before):
        # `Имя: «…»` — прямо перед цитатой стоит `Имя:`.
        return True
    if _ATTR_VERB_RE.search(after):
        return True
    return False


# ── Валидация + канонизация §99 (D1/D6) ────────────────────────────────────

def validate_l2_document(document: dict,
                         package: dict) -> tuple[dict | None, dict]:
    """Проверить и канонизировать §99-документ (fail-closed, детерминированно).

    Возвращает ``(canonical | None, metrics)``. Любая структурная/типовая
    ошибка или нарушение §97 → ``None`` + R17-safe код причины в ``metrics``.
    Пост-валидация цитат: нет нормализованного совпадения с текстами пакета →
    снять кавычки (+WARN-счётчик); именованная атрибуция → fail-closed
    ``quote_attribution``. Не бросает.
    """
    metrics: dict = {
        "status": STATUS_INVALID,
        "reason": REASON_INTERNAL_ERROR,
        "paragraphs_count": 0,
        "quote_unverified_count": 0,
        "quote_attribution_count": 0,
        "emphasis_dropped_count": 0,
        "ids_stripped_count": 0,
    }
    try:
        return _validate(document, package, metrics)
    except Exception:  # pragma: no cover - защитная ветка
        logger.warning("L2 contract: internal error — fail-closed",
                       exc_info=True)
        metrics["reason"] = REASON_INTERNAL_ERROR
        return None, metrics


def _reject(metrics: dict, reason: str):
    metrics["status"] = STATUS_INVALID
    metrics["reason"] = reason
    return None, metrics


def _valid_title(value):
    if not isinstance(value, str):
        return None
    if "\n" in value or "\r" in value:
        return None
    title = _WS_RE.sub(" ", value).strip()
    if not title or len(title) > TITLE_MAX:
        return None
    return title


def _valid_paragraph_text(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > PARAGRAPH_MAX:
        return None
    return text


def _validate(document, package, metrics):
    if not isinstance(document, dict):
        return _reject(metrics, REASON_BAD_TYPE)

    if set(document) - TOP_LEVEL_FIELDS:
        return _reject(metrics, REASON_UNKNOWN_FIELD)

    version = document.get("schema_version")
    if (not isinstance(version, int) or isinstance(version, bool)
            or version != SCHEMA_VERSION):
        return _reject(metrics, REASON_BAD_SCHEMA_VERSION)

    title = _valid_title(document.get("title"))
    if title is None:
        return _reject(metrics, REASON_INVALID_TITLE)

    paragraphs_raw = document.get("paragraphs")
    if not isinstance(paragraphs_raw, list):
        return _reject(metrics, REASON_BAD_TYPE)
    if len(paragraphs_raw) > MAX_PARAGRAPHS_HARD:
        return _reject(metrics, REASON_TOO_MANY_PARAGRAPHS)

    pool = _package_text_pool(package) if isinstance(package, dict) else []
    pool_normalized = [_normalize_quote(text) for text in pool]
    pool_normalized = [value for value in pool_normalized if value]

    canonical: list[dict] = []
    total_chars = len(title)
    for raw_paragraph in paragraphs_raw:
        if not isinstance(raw_paragraph, dict):
            return _reject(metrics, REASON_BAD_TYPE)
        if set(raw_paragraph) - PARAGRAPH_FIELDS:
            return _reject(metrics, REASON_UNKNOWN_FIELD)
        text = _valid_paragraph_text(raw_paragraph.get("text"))
        if text is None:
            return _reject(metrics, REASON_INVALID_PARAGRAPH)

        # Вырезание сырых ID (§4.4/D6) до проверки цитат.
        text, stripped = _strip_raw_ids(text)
        metrics["ids_stripped_count"] += stripped
        if not text:
            return _reject(metrics, REASON_INVALID_PARAGRAPH)

        # Пост-валидация кавычковых вставок (§4.4).
        for quote in _QUOTE_RE.findall(text):
            if not _quote_matches_pool(quote, pool_normalized):
                metrics["quote_unverified_count"] += 1
                if _has_named_attribution(quote, text):
                    metrics["quote_attribution_count"] += 1
                    return _reject(metrics, REASON_QUOTE_ATTRIBUTION)
                text = text.replace(quote, _strip_quotes(quote))
            elif _has_named_attribution(quote, text):
                metrics["quote_attribution_count"] += 1
                return _reject(metrics, REASON_QUOTE_ATTRIBUTION)

        emphasis_raw = raw_paragraph.get("emphasis")
        emphasis = None
        if emphasis_raw is not None:
            if not isinstance(emphasis_raw, str):
                return _reject(metrics, REASON_BAD_TYPE)
            candidate = emphasis_raw.strip()
            if candidate and candidate in text:
                emphasis = candidate
            else:
                metrics["emphasis_dropped_count"] += 1

        canonical.append({"text": text, "emphasis": emphasis})
        total_chars += len(text) + (len(emphasis) if emphasis else 0)

    if not canonical:
        return _reject(metrics, REASON_INVALID_PARAGRAPH)
    if total_chars > RICH_MAX_CHARS:
        return _reject(metrics, REASON_TOO_LONG)

    document_out = {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "paragraphs": canonical,
    }
    metrics["status"] = STATUS_OK
    metrics["reason"] = REASON_OK
    metrics["paragraphs_count"] = len(canonical)
    return document_out, metrics


# ── Вызов LLM: ровно один, через слот или глобальную модель ────────────────

def _extract_usage(value):
    """``(in, out)`` токены из usage-словаря провайдера; иначе ``(None, None)``."""
    if not isinstance(value, dict):
        return None, None
    try:
        prompt = int(value.get("prompt_tokens"))
    except (TypeError, ValueError):
        prompt = None
    try:
        completion = int(value.get("completion_tokens"))
    except (TypeError, ValueError):
        completion = None
    return prompt, completion


def _normalise_call_result(value):
    """Контракт кастомного ``llm_call``: ``str`` либо ``(str, usage|None)``."""
    if isinstance(value, tuple) and len(value) == 2:
        return str(value[0] or ""), value[1]
    return str(value or ""), None


async def _dedicated_generate(llm, messages, slot: L2Slot) -> tuple[str, dict]:
    """Выделенный слот §82 через существующий транзитный канал LLMClient.

    Прецедент S3 (`summary_l1_clusterizer._dedicated_generate`): per-call
    ``base_url``/``model``/``api_key`` идут через тот же retry/fallback-канал;
    ошибка dedicated уходит в существующую политику ``LLM_FALLBACK_*``, БЕЗ
    подмены на глобальную модель.
    """
    payload = {"model": slot.model, "messages": messages}
    try:
        response = await llm._post(  # noqa: SLF001 - документированный мост S3/S5
            "/chat/completions", payload, api_key=slot.api_key,
            base_url=slot.base_url)
    except LLMError as exc:
        fallback = getattr(llm, "_fallback_with_retries", None)
        active = bool(getattr(llm, "_fallback_active", False))
        if fallback is None or not active or isinstance(exc, LLMBadResponseError):
            raise
        response = await fallback(payload)
        if response is None:
            raise exc from None
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMBadResponseError("L2 dedicated: invalid JSON response") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMBadResponseError(
            "L2 dedicated: no choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMBadResponseError("L2 dedicated: empty content")
    return content, (data.get("usage") if isinstance(data, dict) else None)


def _make_llm_call(llm, slot: L2Slot, correlation_id):
    """Собрать async-callable L2 (ровно один вызов на запуск)."""
    if not slot.dedicated:
        async def _call(messages):
            return await llm.generate(messages, module=MODULE, step=STEP,
                                      correlation_id=correlation_id)
        return _call

    async def _call_dedicated(messages):
        return await _dedicated_generate(llm, messages, slot)
    return _call_dedicated


def _effective_model(llm, slot: L2Slot) -> str:
    if slot.dedicated:
        return slot.model
    return str(getattr(llm, "_chat_model", "") or slot.model)


def _effective_base_url(llm, slot: L2Slot) -> str:
    if slot.dedicated:
        return slot.base_url
    return str(getattr(llm, "_base_url", "") or slot.base_url)


def provider_host(base_url: str) -> str:
    """R17-safe провайдер для логов: только host (без пути/ключа/query)."""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(str(base_url or ""))
        return parts.hostname or ""
    except Exception:  # pragma: no cover - защитная ветка
        return ""


# ── §109: логи (аддитивные, R17-safe) ──────────────────────────────────────

def _log_start(*, correlation_id, chat_id, paragraphs_hint, model, base_url,
               dedicated) -> None:
    logger.info(
        "L2_START | run_id=%s | chat_id=%s | paragraphs_hint=%d | model=%s | "
        "provider=%s | dedicated=%s",
        correlation_id or "none", chat_id, paragraphs_hint, model or "-",
        provider_host(base_url) or "-", bool(dedicated))


def _log_complete(*, correlation_id, chat_id, result: L2Result, model,
                  base_url, tokens_in, tokens_out) -> None:
    metrics = result.metrics or {}
    logger.info(
        "L2_COMPLETE | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "tokens_in=%s | tokens_out=%s | paragraphs=%d | title_len=%d | "
        "quote_unverified=%d | ids_stripped=%d | emphasis_dropped=%d | "
        "status=%s | invalid_reason=%s | duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", tokens_in if tokens_in is not None else "-",
        tokens_out if tokens_out is not None else "-",
        metrics.get("paragraphs_count", 0), metrics.get("title_len", 0),
        metrics.get("quote_unverified_count", 0),
        metrics.get("ids_stripped_count", 0),
        metrics.get("emphasis_dropped_count", 0), result.status,
        result.invalid_reason or "-", result.duration_ms)


def _log_error(*, correlation_id, chat_id, model, base_url, reason, error_type,
               duration_ms, http_status=None, attempts=None) -> None:
    logger.warning(
        "L2_ERROR | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "error=%s | reason=%s | http_status=%s | attempts=%s | duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", error_type or "-", reason or "-",
        http_status if http_status is not None else "-",
        attempts if attempts is not None else "-", duration_ms)


def _log_skipped(*, correlation_id, chat_id, reason) -> None:
    logger.warning(
        "L2_SKIPPED | run_id=%s | chat_id=%s | reason=%s",
        correlation_id or "none", chat_id, reason or "-")


# ── Ядро запуска L2 ────────────────────────────────────────────────────────

async def run_l2(llm=None, package=None, *, service=None, correlation_id=None,
                 slot=None, max_paragraphs=None, chat_id=None,
                 system_prompt=None, llm_call=None) -> L2Result:
    """Один прогон L2: контент пакета §96 → **1 LLM-вызов** → §99-документ.

    ``llm`` — LLMClient (или совместимый мок); ``llm_call`` — инъекция канала
    (тесты/врезка). ``service`` — служебная секция пакета (уровень детализации);
    в контент НЕ попадает (§96/§104). Fail-closed: ``empty``/``invalid``/
    ``error`` → ``document=None``, публикации нет, legacy-фолбэка НЕТ (§106).
    Ровно один физический вызов на запуск.
    """
    started = time.perf_counter()

    def _elapsed() -> float:
        return (time.perf_counter() - started) * 1000.0

    # 1. Пакет должен быть deliverable (§96/§106) — иначе L2 не вызываем.
    if not isinstance(package, dict):
        _log_skipped(correlation_id=correlation_id, chat_id=chat_id,
                     reason=REASON_NO_PACKAGE)
        return empty_result(reason=REASON_NO_PACKAGE, duration_ms=_elapsed())
    status = str(package.get("status") or "")
    if status not in ("ok", "truncated") or package.get("threads") is None:
        _log_skipped(correlation_id=correlation_id, chat_id=chat_id,
                     reason=REASON_PACKAGE_NOT_DELIVERABLE)
        return empty_result(reason=REASON_PACKAGE_NOT_DELIVERABLE,
                            duration_ms=_elapsed())

    detail = DETAIL_DEFAULT
    if isinstance(service, dict):
        detail = str(service.get("response_mode") or DETAIL_DEFAULT)
    paragraphs_hint = _DETAIL_PARAGRAPH_HINT.get(
        str(detail or "").strip().lower(),
        _DETAIL_PARAGRAPH_HINT[DETAIL_DEFAULT])
    cap = max_paragraphs if max_paragraphs is not None \
        else resolve_l2_max_paragraphs()

    try:
        resolved_slot = slot or resolve_l2_slot_safe()
    except L2SlotError as exc:
        _log_error(correlation_id=correlation_id, chat_id=chat_id, model="-",
                   base_url="-", reason=REASON_INTERNAL_ERROR,
                   error_type=type(exc).__name__, duration_ms=_elapsed(),
                   http_status=http_status_of(exc), attempts=attempts_of(exc))
        return error_result(REASON_INTERNAL_ERROR, duration_ms=_elapsed())

    if llm_call is None and llm is None:
        return error_result(REASON_INTERNAL_ERROR, duration_ms=_elapsed())

    model = _effective_model(llm, resolved_slot) if llm is not None \
        else resolved_slot.model
    base_url = _effective_base_url(llm, resolved_slot) if llm is not None \
        else resolved_slot.base_url

    content = build_l2_input(package, detail=detail)
    _log_start(correlation_id=correlation_id, chat_id=chat_id,
               paragraphs_hint=paragraphs_hint, model=model, base_url=base_url,
               dedicated=resolved_slot.dedicated)
    call = llm_call or _make_llm_call(llm, resolved_slot, correlation_id)
    system = system_prompt or resolve_prompt(
        PROMPT_PG_KEY, SUMMARY_L2_WRITER_SYSTEM_PROMPT)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]

    try:
        raw_value = await call(messages)
        raw, usage = _normalise_call_result(raw_value)
        tokens_in, tokens_out = _extract_usage(usage)
        if tokens_in is None:
            tokens_in = count_tokens(content)
        if tokens_out is None:
            tokens_out = count_tokens(raw)
    except LLMError as exc:
        reason = (REASON_LLM_TIMEOUT
                  if type(exc).__name__ == "LLMTimeoutError"
                  else REASON_LLM_ERROR)
        _log_error(correlation_id=correlation_id, chat_id=chat_id, model=model,
                   base_url=base_url, reason=reason, error_type=type(exc).__name__,
                   duration_ms=_elapsed(),
                   http_status=http_status_of(exc), attempts=attempts_of(exc))
        return error_result(reason, duration_ms=_elapsed())
    except Exception as exc:
        _log_error(correlation_id=correlation_id, chat_id=chat_id, model=model,
                   base_url=base_url, reason=REASON_LLM_ERROR,
                   error_type=type(exc).__name__, duration_ms=_elapsed(),
                   http_status=http_status_of(exc), attempts=attempts_of(exc))
        return error_result(REASON_LLM_ERROR, duration_ms=_elapsed())

    usage = {"input_tokens": tokens_in, "output_tokens": tokens_out}
    data, parse_reason = parse_l2_document(raw)
    if data is None:
        reason = parse_reason if parse_reason != REASON_OK else REASON_INTERNAL_ERROR
        result = invalid_result(reason, duration_ms=_elapsed(), usage=usage)
    else:
        document, metrics = validate_l2_document(data, package)
        # Эффективный кап абзацев (limits.max_summary_parts, D2/D4).
        if document is not None and len(document["paragraphs"]) > cap:
            document = None
            metrics = dict(metrics)
            metrics["status"] = STATUS_INVALID
            metrics["reason"] = REASON_TOO_MANY_PARAGRAPHS
        if document is None:
            result = invalid_result(
                metrics.get("reason", REASON_INVALID_PARAGRAPH),
                duration_ms=_elapsed(), usage=usage, metrics=metrics)
        else:
            metrics = dict(metrics)
            metrics["title_len"] = len(document["title"])
            result = _make_result(STATUS_OK, document=document, usage=usage,
                                  metrics=metrics, duration_ms=_elapsed())

    _log_complete(correlation_id=correlation_id, chat_id=chat_id,
                  result=result, model=model, base_url=base_url,
                  tokens_in=tokens_in, tokens_out=tokens_out)
    return result
