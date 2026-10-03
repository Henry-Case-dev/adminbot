"""S5 round1026 (ADR-1026-7 D1/D4/D6) + ASAP-2 round1027 (ADR-1027-10 D5/D6).

**Модуль L2 «Писатель»** (живой путь за флагом
``flags.summary_hybrid_l2_enabled``; default **ON**, явный ``false`` —
аварийный kill-switch): вход — контент-секция
``FactPackage`` (S4, §96) → **ровно 1 LLM-вызов** L2 → парсер строгого
JSON-документа §99 → детерминированный валидатор (структура §98, запрет
выдуманных цитат/приписанных реплик, изоляция ID) → fail-closed ``L2Result``.

Инварианты (ADR-1026-7 + AMEND ADR-1027-10):
  * **ровно 1 вызов L2-слоя** (happy path = 2: L1+L2). Recovery-бюджет
    (ADR-1027-10 D3): при негодности L2 — LEVEL-3 Legacy fallback в
    ``summary_generator`` (AMEND ADR-1026-7 D5: «legacy-фолбэка нет»
    отменён владельцем §8/§9); L2 correction retry НЕ вводится;
  * **выход §99** — структурированный документ
    ``{schema_version:1, title, paragraphs:[{text, emphasis|null}]}``;
    лишние поля/типы → ``invalid``; L2 НЕ форматирует HTML (§99);
  * **§97-качество**: умеренная ирония допустима, приоритет — точность;
    **выдуманные цитаты не публикуются** (нет нормализованного совпадения с
    текстами пакета → снятие кавычек + WARN), **приписанные реплики** →
    fail-closed ``invalid`` (``quote_attribution``); сырые ID/``fact:``/``msg:``
    вырезаются;
  * **ASAP-2 §1/§2/§3/§10/§16**: `limits.max_summary_parts` из Hybrid ВЫВЕДЕН
    (ни кап абзацев, ни trim); длина — мягкие targets из НОВЫХ
    ``limits.summary_hybrid_*`` (пресеты casual/serious/deep_research) в
    детерминированном length-блоке user-контента; hard-проверки — только
    технические §99 (200/900/498/32000); `summary_hybrid_max_chars` —
    WARN-порог наблюдения (`L2_OVER_SOFT_CEILING`), никогда не обрезка;
  * **слот §82**: hot-first ``models/keys.summary_l2_*`` (каталог с ASAP-2
    §13), дефолты env ClassVar ``SUMMARY_L2_*``;
  * **логи §108/§109/§18 аддитивны и R17-safe**: ``L2_START`` (+=
    response_mode/target_chars/target_paragraphs)/``L2_COMPLETE`` (+= chars;
    ``trimmed=`` УДАЛЁН)/``L2_ERROR``/``L2_SKIPPED`` — только числа/коды/id.
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
from services.prompt_style_blocks import resolve_prompt, resolve_prompt_with_source
from services.summary_cleanup import cleanup_llm_text
from services.summary_prompts import (
    PREV_SUMMARY_L2_WRITER_R1029_ASAP41,
    SUMMARY_L2_WRITER_SYSTEM_PROMPT,
)
# Волна C (T-4423): quote pipeline импортируется ЛЕНИВО в _validate
# (summary_quote_repair импортирует из этого модуля чистые утилиты цитат —
# верхнеуровневый импорт дал бы цикл).
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
# служебный H1/обложку, D2). Единственный кап числа абзацев Hybrid-статьи
# (ASAP-2 §1/§3: `limits.max_summary_parts` из Hybrid выведен полностью).
MAX_PARAGRAPHS_HARD = 498
RICH_MAX_CHARS = 32000

# ── ASAP-2 §2/§10 (ADR-1027-10 D6): пресеты мягких целей Hybrid-статьи ─────
# (target_chars, target_paragraphs) — середины диапазонов владельца
# §2:2011–2018; serious=6500/8 подтверждён примером §10:2316–2318. Все
# пресеты влезают в rich-канал (RICH_MAX_CHARS=32000) с запасом ≥2.9×.
# Это TARGETS: валидатор НИКОГДА не сравнивает результат с целями (§3:2071).
HYBRID_PRESETS: dict[str, tuple[int, int]] = {
    "casual": (4000, 5),
    "serious": (6500, 8),
    "deep_research": (11000, 14),
}
HYBRID_MODE_DEFAULT = "serious"
# Широкий safety ceiling наблюдения (0.75×RICH_MAX_CHARS): 24000<chars≤32000 →
# публикуем + WARN `L2_OVER_SOFT_CEILING`; chars>32000 → технический
# fail-closed `too_long` (§99 hard limit). Никогда не механическая обрезка.
HYBRID_MAX_CHARS_DEFAULT = 24000

TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {"schema_version", "title", "paragraphs", "finale"})
# ASAP-4 волна D (T-4429, §50.7): paragraphs получают аддитивное internal-
# поле evidence_message_ids (ID только из пакета; invented → validation
# error; shared evidence разрешён). schema_version остаётся 1 — документы
# без новых полей валидны (прецедент ASAP-2.1 emphasis_spans).
PARAGRAPH_FIELDS: frozenset[str] = frozenset(
    {"text", "emphasis", "emphasis_spans", "evidence_message_ids"})

# ── ASAP-2.1 (§99 v1.1, ADR-1028-1 D3): акценты/финал ──────────────────────
# emphasis_spans — массив {text, kind}; kind ∈ {"person","event"} (прочие
# kind НЕ бракуют документ — рендер одинаково bold, но пишутся в счётчик);
# schema_version остаётся 1 — аддитивно, документы без новых полей валидны.
EMPHASIS_SPAN_MAX = 4          # кап принятых span'ов на абзац (анти «жирная каша»)
EMPHASIS_KINDS = ("person", "event")
# Тегоподобные span'ы отбрасываются (raw HTML от L2 не проходит как разметка).
_TAGLIKE_RE = re.compile(r"</?[A-Za-z]")
# finale: одна строка, после cleanup+strip 1..200 симв.; иначе отброшен.
FINALE_MAX = 200

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
# ASAP-4 волна D (T-4429, §50.7): evidence-ссылки абзаца — invented/битый тип
# → validation error (fail-closed, детерминированный слой до Reviewer).
REASON_INVALID_EVIDENCE = "invalid_evidence"
REASON_NO_PACKAGE = "no_package"
REASON_PACKAGE_NOT_DELIVERABLE = "package_not_deliverable"
REASON_NOT_BUILT = "not_built"
REASON_LLM_ERROR = "llm_error"
REASON_LLM_TIMEOUT = "llm_timeout"
REASON_INTERNAL_ERROR = "internal_error"

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


# ── Hybrid-длина (ASAP-2 §2/§10/§13, ADR-1027-10 D6): резолв целей ─────────

def _read_hot_int(hot_get, key: str, default) -> int:
    try:
        return int(hot_get(key, default))
    except (TypeError, ValueError):
        return int(default)


def resolve_hybrid_length(chat_id=None, *, hot_get=None, settings_obj=None,
                          per_chat_get=None) -> dict:
    """Эффективные цели Hybrid-статьи: per-chat → hot → env → пресет.

    Ключи (контракт (f)): ``limits.summary_hybrid_response_mode`` (default
    ``serious``), ``limits.summary_hybrid_target_chars``/
    ``_target_paragraphs`` (``0`` — по пресету; явное >0 побеждает пресет),
    ``limits.summary_hybrid_max_chars`` (default 24000 — WARN-порог, НЕ
    обрезка). Конфиг-режим ПОЛЬЗОВАТЕЛЯ побеждает L1-``response_mode`` (spec
    (f)): длина больше не определяется моделью. Не бросает: любое значение
    вне диапазона/непарсится → дефолт.
    """
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings

    def _env(field: str, default):
        return getattr(st, field, default)

    mode = str(hot_get("limits.summary_hybrid_response_mode",
                       _env("SUMMARY_HYBRID_RESPONSE_MODE",
                            HYBRID_MODE_DEFAULT)) or "").strip().lower()
    if mode not in HYBRID_PRESETS:
        mode = HYBRID_MODE_DEFAULT
    # per-chat override (существующий `_chat_limit`-паттерн: None → нет
    # override; инъекция для тестов).
    if per_chat_get is not None:
        try:
            pc_mode = per_chat_get("limits.summary_hybrid_response_mode")
            pc_mode = str(pc_mode or "").strip().lower()
            if pc_mode in HYBRID_PRESETS:
                mode = pc_mode
        except Exception:  # pragma: no cover - fail-open к глобальному
            pass
    preset_chars, preset_paragraphs = HYBRID_PRESETS[mode]

    def _override(key: str, env_field: str, fallback: int) -> int:
        raw = hot_get(key, _env(env_field, 0))
        if per_chat_get is not None:
            try:
                pc_raw = per_chat_get(key)
                if pc_raw is not None and str(pc_raw) != "":
                    raw = pc_raw
            except Exception:  # pragma: no cover - fail-open к глобальному
                pass
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 0
        # 0/отрицательное/мусор → по пресету.
        return value if value > 0 else fallback

    target_chars = _override("limits.summary_hybrid_target_chars",
                             "SUMMARY_HYBRID_TARGET_CHARS", preset_chars)
    target_paragraphs = _override(
        "limits.summary_hybrid_target_paragraphs",
        "SUMMARY_HYBRID_TARGET_PARAGRAPHS", preset_paragraphs)
    max_chars = _read_hot_int(hot_get, "limits.summary_hybrid_max_chars",
                              _env("SUMMARY_HYBRID_MAX_CHARS",
                                   HYBRID_MAX_CHARS_DEFAULT))
    if max_chars <= 0:
        max_chars = HYBRID_MAX_CHARS_DEFAULT
    return {"response_mode": mode, "target_chars": target_chars,
            "target_paragraphs": target_paragraphs, "max_chars": max_chars}


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


# ── ASAP-4 волна D (T-4429, §50.7–§50.9): evidence id-space + roster ───────

def _as_plain_int(value) -> int | None:
    """Строгий int без bool-ловушки (``True`` — не message_id)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def package_message_id_space(package) -> set[int]:
    """Все известные пакету message_id (§50.7 «Writer ссылается только на ID
    из переданного пакета»): хронология ∪ фрагменты ∪ evidence фактов ∪
    unassigned. ``service``/``budget`` — служебные секции, ID оттуда не
    берутся. Не бросает."""
    ids: set[int] = set()
    for thread in _package_threads(package):
        if not isinstance(thread, dict):
            continue
        for entry in thread.get("chronology") or []:
            if isinstance(entry, dict):
                value = _as_plain_int(entry.get("message_id"))
                if value is not None:
                    ids.add(value)
        for fact in thread.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            for ref in fact.get("evidence_message_ids") or []:
                value = _as_plain_int(ref)
                if value is not None:
                    ids.add(value)
        for fragment in thread.get("fragments") or []:
            if isinstance(fragment, dict):
                value = _as_plain_int(fragment.get("message_id"))
                if value is not None:
                    ids.add(value)
    unassigned = (package.get("unassigned_message_ids")
                  if isinstance(package, dict) else None)
    for ref in unassigned or []:
        value = _as_plain_int(ref)
        if value is not None:
            ids.add(value)
    return ids


def build_participant_roster(package) -> list[dict]:
    """Participant roster §50.8 (0 LLM, детерминированно из фрагментов пакета).

    ``[{author_id, display_name, aliases}]``: каноническое display_name —
    первое по порядку в пакете; aliases — остальные display_name того же
    author_id (смена имени в окне ≠ два человека, §50.43). Одинаковые имена
    у разных author_id НЕ склеиваются (§50.44). Без author_id фрагмент
    roster не пополняет (не выдумываем идентичность). Не бросает.
    """
    order: list = []
    by_author: dict = {}
    for thread in _package_threads(package):
        if not isinstance(thread, dict):
            continue
        for fragment in thread.get("fragments") or []:
            if not isinstance(fragment, dict):
                continue
            author = fragment.get("author_id")
            if isinstance(author, bool) or not isinstance(author, int):
                continue
            name = str(fragment.get("display_name") or "").strip()
            if not name:
                continue
            entry = by_author.get(author)
            if entry is None:
                entry = {"author_id": author, "display_name": name,
                         "aliases": []}
                by_author[author] = entry
                order.append(entry)
                continue
            if name == entry["display_name"]:
                continue
            if name not in entry["aliases"]:
                entry["aliases"].append(name)
    return order


# ── Вход L2 (§96/§12, компактность) ────────────────────────────────────────

def build_l2_input(package: dict, *, length: dict | None = None) -> str:
    """Собрать контент-секцию ``FactPackage`` для L2 (§96/§12) + length-блок.

    На тему: ``name``/``description``/``chronology`` (message_id/timestamp/
    ``topic_ids`` — many-to-many карта §12)/``facts[].text`` +
    ``evidence_message_ids``/отобранные ``fragments`` (v2: author_id,
    display_name, timestamp, reply_to_id, text, kind — рассказчик понимает
    «кто что сказал / кто кому отвечал / что переслано», §12/§50.9).
    ``service``/``budget``/``unassigned_message_ids`` в контент НЕ идут;
    сырой лог повторно не передаётся. Формат — компактные JSON-строки,
    детерминированный порядок.

    ASAP-4 волна D (§50.8, T-4429): секция ``participants`` — roster
    (author_id/display_name/aliases), детерминированно из фрагментов пакета;
    Writer не выдумывает имена (см. канон).

    ``length`` (контракт (l)/T-3942) — детерминированный length-блок ПОСЛЕ
    JSON пакета (response_mode/target_chars/target_paragraphs): числа НЕ в
    PG-каноне (hot-правки канона не могут сломать подстановку); это ориентиры,
    а не лимиты; ``max_chars`` в промпт НЕ передаётся (post-hoc guard).
    """
    content = {
        "schema_version": SCHEMA_VERSION,
        "participants": build_participant_roster(package),
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
                    "topic_ids": list(entry.get("topic_ids") or []),
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
                item = {
                    "message_id": fragment.get("message_id"),
                    "author_id": fragment.get("author_id"),
                    "display_name": fragment.get("display_name"),
                    "timestamp": fragment.get("timestamp"),
                    "reply_to_id": fragment.get("reply_to_id"),
                    "text": fragment.get("text"),
                }
                # ASAP-4 волна D (§50.9): раздельные отношения; kind
                # msg|reply|forward|quote из метаданных пакета.
                kind = fragment.get("kind")
                if isinstance(kind, str) and kind:
                    item["kind"] = kind
                if fragment.get("forward_source"):
                    item["forward_source"] = fragment.get("forward_source")
                fragments.append(item)
        content["threads"].append({
            "thread_id": thread.get("thread_id"),
            "name": thread.get("name"),
            "description": thread.get("description"),
            "chronology": chronology,
            "facts": facts,
            "fragments": fragments,
        })
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    out = ("ПАКЕТ ФАКТОВ (компактный JSON; пиши статью по нему; "
           "служебные поля не передаются):\n" + body)
    if isinstance(length, dict):
        out += _length_block(length)
    return out


def _length_block(length: dict) -> str:
    """Детерминированный length-блок (контракт (l)/T-3942) — единый текст
    для пакета и source-входа (байт-в-байт прежняя формулировка)."""
    return (
        "\n\nЗАДАНИЕ ПО ДЛИНЕ И ДЕТАЛИЗАЦИИ: response_mode="
        + str(length.get("response_mode") or HYBRID_MODE_DEFAULT)
        + "; цель ≈ " + str(int(length.get("target_chars") or 0))
        + " символов (мягкий ориентир); абзацев ≈ "
        + str(int(length.get("target_paragraphs") or 0))
        + " (рекомендация). Это ориентиры, а не лимиты: не обрывай события"
          " и не выбрасывай важные темы ради точного числа.")


# ── ASAP 4.1 волна 3 (T-4609, spec §2 B.3; ADR-1028-8 D4/AM-4) ─────────────

def writer_source_input_enabled() -> bool:
    """Kill-switch ``SUMMARY_WRITER_SOURCE_INPUT_ENABLED`` (env-only,
    default ON). OFF → Writer получает FactPackage-центричный вход как
    сегодня (бит-в-бит 2.58.46). Никогда не бросает."""
    try:
        return bool(getattr(settings, "SUMMARY_WRITER_SOURCE_INPUT_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


_SOURCE_HEADER = (
    "ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА (оригинал — истина; §92-сообщения, "
    "хронология ASC; без срезов):")
_MAP_HEADER = (
    "SEMANTIC MAP (структурная подсказка от кластеризатора; оригинал — "
    "истина):")
_MAP_UNAVAILABLE_NOTE = (
    "SEMANTIC MAP ОТСУТСТВУЕТ — структурируй источник сам (semantic map "
    "unavailable — structure source yourself).")
_FACT_VIEW_HEADER = (
    "ПАКЕТ ФАКТОВ (вспомогательный индекс; мог быть урезан по бюджету; "
    "оригинал — истина):")


def build_l2_source_input(payload_items, semantic_map=None, *, package=None,
                          length=None, map_unavailable: bool = False) -> str:
    """WriterInput (T-4609): Full SourceWindow первоклассно + semantic map?
    + fact_view? + length-блок.

    Секции (детерминированный порядок, компактный JSON):
      1. source_window — ВСЕ §92-элементы окна (никаких messages[:N]/эвикций);
      2. semantic_map (если есть) — map v1 по message_id;
      3. инструкция «структурируй источник сам» (map отсутствует — L1 fail);
      4. fact_view (если передан) — вспомогательный индекс;
      5. length-блок (мягкий ориентир; тот же текст, что build_l2_input).
    Не бросает."""
    items = [item for item in (payload_items or []) if isinstance(item, dict)]
    parts: list[str] = [
        _SOURCE_HEADER,
        "Всего сообщений: %d." % len(items),
    ]
    for item in items:
        parts.append(json.dumps(item, ensure_ascii=False,
                                separators=(",", ":")))
    if isinstance(semantic_map, dict) and semantic_map:
        parts.append(_MAP_HEADER)
        parts.append(json.dumps(semantic_map, ensure_ascii=False,
                                separators=(",", ":")))
    elif map_unavailable:
        parts.append(_MAP_UNAVAILABLE_NOTE)
    if isinstance(package, dict) and package:
        parts.append(_FACT_VIEW_HEADER)
        parts.append(build_l2_input(package, length=None)
                     .split("\n", 1)[-1])
    if isinstance(length, dict):
        parts.append(_length_block(length).lstrip("\n"))
    return "\n".join(parts)


def build_writer_merge_input(documents, *, length=None) -> str:
    """Merge-pass иерархического Writer (T-4609 CAPACITY_OVERFLOW): сегментные
    документы §99 → одна статья. Бюджет мягкий; НИЧЕГО не выбрасывается
    (fallback — детерминированная склейка вызывающего контура)."""
    docs = [dict(d) for d in (documents or []) if isinstance(d, dict)]
    parts = [
        "МЕРДЖ СЕГМЕНТНЫХ ЧЕРНОВИКОВ (собери ИТОГОВУЮ статью из документов "
        "сегментов; сохрани все события и evidence_message_ids; дубликат "
        "одного события — расскажи ОДИН раз):",
        json.dumps({"schema_version": SCHEMA_VERSION, "segment_documents":
                    docs}, ensure_ascii=False, separators=(",", ":")),
    ]
    if isinstance(length, dict):
        parts.append(_length_block(length).lstrip("\n"))
    return "\n".join(parts)


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
        # Волна C (T-4423, §53.2): quotes_total/verified/repaired/removed —
        # safe-метрики repair-пайплайна (ON-путь; тексты цитат не логируются).
        "quotes_total": 0,
        "quotes_verified": 0,
        "quotes_repaired": 0,
        "quotes_removed": 0,
        "emphasis_dropped_count": 0,
        "emphasis_spans_count": 0,
        "finale_present": 0,
        "ids_stripped_count": 0,
        # ASAP-4 волна D (T-4429, §50.7): evidence-трассировка абзацев.
        "evidence_refs_total": 0,
        "evidence_paragraphs": 0,
        "paragraphs_without_evidence": 0,
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


def _clean_span_text(value) -> str:
    """Спан чистится ТОЙ ЖЕ картой замен, что и текст абзаца (Q3 п.1)."""
    if not isinstance(value, str):
        return ""
    return cleanup_llm_text(value).strip()


def _valid_span(candidate: str, final_text: str) -> bool:
    """span валиден ⟺ непустая точная подстрока финального текста абзаца,
    len ≤ ``PARAGRAPH_MAX``, без тегоподобных конструкций (Q3 п.2)."""
    if not candidate or len(candidate) > PARAGRAPH_MAX:
        return False
    if _TAGLIKE_RE.search(candidate):
        return False
    return candidate in final_text


def _canonicalize_spans(raw_spans, legacy_emphasis, final_text, metrics):
    """Детерминированная канонизация акцентов абзаца (Q3 п.3–7).

    Очередь кандидатов: legacy ``emphasis`` (строка) — ПЕРВЫМ, затем
    ``emphasis_spans`` в порядке JSON. Позиция = первое вхождение; сортировка
    ``(start ASC, length DESC, порядок_в_JSON ASC)``; жадный приём без
    пересечений; дедуп по text; кап ``EMPHASIS_SPAN_MAX``. Invalid — молча в
    счётчик. Возвращает ``(accepted, first_text|None)``.
    """
    candidates: list = []
    if isinstance(legacy_emphasis, str):
        cleaned = _clean_span_text(legacy_emphasis)
        if cleaned:
            candidates.append(cleaned)
    if raw_spans is not None:
        for raw in raw_spans:
            if not isinstance(raw, dict):
                metrics["emphasis_dropped_count"] += 1
                continue
            cleaned = _clean_span_text(raw.get("text"))
            if not cleaned:
                metrics["emphasis_dropped_count"] += 1
                continue
            candidates.append(cleaned)

    accepted: list = []
    seen_texts: set = set()
    positioned: list = []
    for order, candidate in enumerate(candidates):
        if not _valid_span(candidate, final_text):
            metrics["emphasis_dropped_count"] += 1
            continue
        if candidate in seen_texts:
            metrics["emphasis_dropped_count"] += 1
            continue
        seen_texts.add(candidate)
        positioned.append((final_text.find(candidate), -len(candidate),
                           order, candidate))
    positioned.sort(key=lambda item: (item[0], item[1], item[2]))
    last_end = -1
    for start, _neg_len, _order, candidate in positioned:
        if len(accepted) >= EMPHASIS_SPAN_MAX:
            metrics["emphasis_dropped_count"] += 1
            continue
        if start < last_end:            # пересечение с уже принятым — жадно мимо
            metrics["emphasis_dropped_count"] += 1
            continue
        accepted.append(candidate)
        last_end = start + len(candidate)
    return accepted, (accepted[0] if accepted else None)


def _valid_finale(value, metrics):
    """finale: строка, ОДНА строка, после cleanup+strip 1..200 (Q4).
    Невалидное/отсутствующее → ``None`` (canonical без finale)."""
    if value is None:
        return None
    if not isinstance(value, str):
        metrics["finale_present"] = 0
        return None
    if "\n" in value or "\r" in value:
        # Одна строка required (как title): многострочный финал не канонизируем.
        metrics["finale_present"] = 0
        return None
    finale = _WS_RE.sub(" ", cleanup_llm_text(value)).strip()
    if not finale or len(finale) > FINALE_MAX:
        metrics["finale_present"] = 0
        return None
    metrics["finale_present"] = 1
    return finale


def _validate(document, package, metrics):
    if not isinstance(document, dict):
        return _reject(metrics, REASON_BAD_TYPE)

    if set(document) - TOP_LEVEL_FIELDS:
        return _reject(metrics, REASON_UNKNOWN_FIELD)

    version = document.get("schema_version")
    if (not isinstance(version, int) or isinstance(version, bool)
            or version != SCHEMA_VERSION):
        return _reject(metrics, REASON_BAD_SCHEMA_VERSION)

    # ASAP-2.1 (T-3978, контракт (d)): typography normalizer на канонизации —
    # title проходит cleanup_llm_text (те же 6 замен, содержание не трогает).
    title = _valid_title(cleanup_llm_text(document.get("title") or ""))
    if title is None:
        return _reject(metrics, REASON_INVALID_TITLE)

    # ASAP-2.1 (Q4/T-3979): structured finale — code валидирует/показывает,
    # НЕ выбирает winner; невалидное → canonical без finale.
    finale = _valid_finale(document.get("finale"), metrics)

    paragraphs_raw = document.get("paragraphs")
    if not isinstance(paragraphs_raw, list):
        return _reject(metrics, REASON_BAD_TYPE)
    if len(paragraphs_raw) > MAX_PARAGRAPHS_HARD:
        return _reject(metrics, REASON_TOO_MANY_PARAGRAPHS)

    pool = _package_text_pool(package) if isinstance(package, dict) else []
    pool_normalized = [_normalize_quote(text) for text in pool]
    pool_normalized = [value for value in pool_normalized if value]

    # ASAP-4 волна D (T-4429, §50.7): id-space пакета — invented evidence
    # refs ловит детерминированный слой ДО Semantic Reviewer (§50.18).
    id_space = package_message_id_space(package) \
        if isinstance(package, dict) else set()

    canonical: list[dict] = []
    total_chars = len(title)
    for raw_paragraph in paragraphs_raw:
        if not isinstance(raw_paragraph, dict):
            return _reject(metrics, REASON_BAD_TYPE)
        if set(raw_paragraph) - PARAGRAPH_FIELDS:
            return _reject(metrics, REASON_UNKNOWN_FIELD)
        # T-3978: текст абзаца проходит cleanup_llm_text ДО substring-
        # проверок спанов/цитат (§99 v1.1 Q3 п.1).
        text = _valid_paragraph_text(
            cleanup_llm_text(raw_paragraph.get("text") or ""))
        if text is None:
            return _reject(metrics, REASON_INVALID_PARAGRAPH)

        # Вырезание сырых ID (§4.4/D6) до проверки цитат.
        text, stripped = _strip_raw_ids(text)
        metrics["ids_stripped_count"] += stripped
        if not text:
            return _reject(metrics, REASON_INVALID_PARAGRAPH)

        # ASAP-4 волна D (T-4429/§50.18): evidence_message_ids — строгий
        # детерминированный чек: только int-ID из id-space пакета; invented
        # → validation error (fail-closed). Поле аддитивно: абзацы без
        # evidence валидны (совместимость §99 v1.1), отсутствие — мягкий
        # сигнал для Reviewer (unsupported_claim по месту), не reject.
        evidence_ids: list[int] = []
        raw_evidence = raw_paragraph.get("evidence_message_ids")
        if raw_evidence is not None:
            if not isinstance(raw_evidence, list):
                return _reject(metrics, REASON_INVALID_EVIDENCE)
            for ref in raw_evidence:
                value = _as_plain_int(ref)
                if value is None or value not in id_space:
                    return _reject(metrics, REASON_INVALID_EVIDENCE)
                if value not in evidence_ids:      # дедуп refs абзаца
                    evidence_ids.append(value)
            if evidence_ids:
                metrics["evidence_paragraphs"] += 1
                metrics["evidence_refs_total"] += len(evidence_ids)
            else:
                metrics["paragraphs_without_evidence"] += 1
        else:
            metrics["paragraphs_without_evidence"] += 1

        # Пост-валидация кавычковых вставок (§4.4).
        from services.summary_quote_repair import (  # лениво: цикл импорта
            process_paragraph_quotes,
            quote_repair_enabled,
        )
        if quote_repair_enabled():
            # Волна C (T-4423, §53.2): extract → resolve против FactPackage →
            # validate speaker → deterministic safe repair → revalidate.
            # Fail-closed — только когда safe repair невозможен (§54:
            # неподтверждённая прямая речь не публикуется никогда); одна
            # repairable цитата больше НЕ уносит статью в Legacy (§53).
            text, qstats = process_paragraph_quotes(text, package)
            metrics["quotes_total"] += qstats.quotes_total
            metrics["quotes_verified"] += qstats.verified
            metrics["quotes_repaired"] += qstats.repaired
            metrics["quotes_removed"] += qstats.removed
            metrics["quote_unverified_count"] += (
                qstats.quotes_total - qstats.verified)
            if qstats.reason_codes:
                codes = metrics.setdefault("quote_reason_codes", [])
                for code in qstats.reason_codes:
                    if code not in codes:
                        codes.append(code)
            if qstats.failure_reason:
                # Umbrella-совместимость: отказ repairable-цепочки виден и
                # под прежним классом, и точной подпричиной.
                metrics["quote_attribution_count"] += 1
                return _reject(metrics, qstats.failure_reason)
        else:
            # Kill-switch OFF → прежняя validator-матрица §50.20 бит-в-бит.
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

        # §99 v1.1 (Q3): секвенциальная канонизация emphasis_spans;
        # derived-`emphasis` = первый принятый span (совместимость читателей).
        emphasis_raw = raw_paragraph.get("emphasis")
        if emphasis_raw is not None and not isinstance(emphasis_raw, str):
            return _reject(metrics, REASON_BAD_TYPE)
        spans_raw = raw_paragraph.get("emphasis_spans")
        if spans_raw is not None and not isinstance(spans_raw, list):
            return _reject(metrics, REASON_BAD_TYPE)
        accepted, first = _canonicalize_spans(
            spans_raw, emphasis_raw, text, metrics)
        metrics["emphasis_spans_count"] += len(accepted)

        canonical.append({
            "text": text,
            "emphasis": first,
            "emphasis_spans": accepted,
            # §50.7: internal metadata — форматтер/публикация поле игнорируют
            # (не публикуется); Reviewer использует для evidence-проверок.
            "evidence_message_ids": evidence_ids,
        })
        total_chars += len(text) + (len(first) if first else 0)

    if not canonical:
        return _reject(metrics, REASON_INVALID_PARAGRAPH)
    if total_chars > RICH_MAX_CHARS:
        return _reject(metrics, REASON_TOO_LONG)

    document_out = {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "paragraphs": canonical,
    }
    if finale is not None:
        document_out["finale"] = finale
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


def _make_llm_call(llm, slot: L2Slot, correlation_id, *, operation: str = "writer"):
    """Собрать async-callable L2 (ровно один вызов на запуск).

    ASAP 4.1 волна 4 (T-4612, spec §4 D.1/D.2, ADR-1028-8 D5): при
    Supervisor ON — единый orchestration-owner (attempt-потолок ≤4 HTTP,
    нижний слой только transport, provider-fallback с capacity re-plan
    решает Supervisor); kill-switch OFF → прежний канал байт-в-бит.
    ``operation`` — честная метка телеметрии (writer/reviewer/revision)."""
    wrapped = _supervise_call(llm, slot, correlation_id, operation=operation,
                              module=MODULE, step=STEP)
    if wrapped is not None:
        return wrapped
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


def _supervise_call(llm, slot, correlation_id, *, operation: str,
                    module: str | None = None, step: str | None = None):
    """Точка врезки LLMExecutionSupervisor (ADR-1028-8 D5; kill-switch
    OFF → None = прежний канал байт-в-бит)."""
    try:
        from services import summary_llm_supervisor as _sup
        return _sup.make_wrapped(llm, slot, correlation_id,
                                 operation=operation, module=module,
                                 step=step)
    except Exception:      # pragma: no cover - врезка не рвёт канал
        logger.warning(
            "summary supervisor: wrap failed — legacy channel (байт-в-бит)",
            exc_info=True)
        return None


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
               dedicated, response_mode="", target_chars=0,
               target_paragraphs=0, prompt_key="", prompt_source="") -> None:
    # ASAP-2 §18 (контракт (k)): аддитивные поля длины; paragraphs_hint
    # сохраняется (пин тестов/JS-харнесса).
    # ASAP-2.1 (T-3986, раздел 4 spec): + effective_prompt_key/prompt_source
    # (chat/global/default; проверка T-3977 в проде — DoD-21).
    logger.info(
        "L2_START | run_id=%s | chat_id=%s | paragraphs_hint=%d | "
        "response_mode=%s | target_chars=%d | target_paragraphs=%d | "
        "prompt_key=%s | prompt_source=%s | "
        "model=%s | provider=%s | dedicated=%s",
        correlation_id or "none", chat_id, paragraphs_hint,
        response_mode or "-", int(target_chars), int(target_paragraphs),
        prompt_key or "-", prompt_source or "-",
        model or "-", provider_host(base_url) or "-", bool(dedicated))


def _log_complete(*, correlation_id, chat_id, result: L2Result, model,
                  base_url, tokens_in, tokens_out) -> None:
    # ASAP-2 §16: `trimmed=` УДАЛЁН (trim-костыль 2.58.32 демонтирован);
    # аддитивно `chars` (§18 L2_RESULT: chars=, paragraphs=).
    # ASAP-2.1 (T-3986, раздел 4 spec): + emphasis_spans (принято шт.),
    # emphasis_dropped, finale_present (0/1). Только числа — R17.
    metrics = result.metrics or {}
    logger.info(
        "L2_COMPLETE | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "tokens_in=%s | tokens_out=%s | chars=%s | paragraphs=%d | "
        "title_len=%d | quote_unverified=%d | ids_stripped=%d | "
        "quotes_total=%d | quotes_verified=%d | quotes_repaired=%d | "
        "quotes_removed=%d | "
        "emphasis_spans=%d | emphasis_dropped=%d | finale_present=%d | "
        "status=%s | invalid_reason=%s | duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", tokens_in if tokens_in is not None else "-",
        tokens_out if tokens_out is not None else "-",
        metrics.get("chars", "-"),
        metrics.get("paragraphs_count", 0), metrics.get("title_len", 0),
        metrics.get("quote_unverified_count", 0),
        metrics.get("ids_stripped_count", 0),
        metrics.get("quotes_total", 0),
        metrics.get("quotes_verified", 0),
        metrics.get("quotes_repaired", 0),
        metrics.get("quotes_removed", 0),
        metrics.get("emphasis_spans_count", 0),
        metrics.get("emphasis_dropped_count", 0),
        metrics.get("finale_present", 0),
        result.status, result.invalid_reason or "-", result.duration_ms)


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

async def _hybrid_length_for_chat(chat_id) -> dict:
    """Резолв Hybrid-длины с per-chat слоем (существующий `_chat_limit`-паттерн).

    Fail-open: chat_params недоступен/нет override → глобальный hot→env→пресет.
    """
    per_chat_get = None
    if chat_id is not None:
        try:
            from services import chat_params

            async def _pc(key: str):
                return await chat_params.get_chat_param(chat_id, key, None)

            # Разрешаем лениво: per_chat_get вызывается синхронно внутри
            # резолвера → оборачиваем в await-цикл ниже.
            keys = ("limits.summary_hybrid_response_mode",
                    "limits.summary_hybrid_target_chars",
                    "limits.summary_hybrid_target_paragraphs",
                    "limits.summary_hybrid_max_chars")
            overrides = {}
            for key in keys:
                try:
                    value = await _pc(key)
                except Exception:  # pragma: no cover - fail-open
                    value = None
                if value is not None and str(value) != "":
                    overrides[key] = value

            def per_chat_get(key: str):  # noqa: D103 - closure-резолвер
                return overrides.get(key)
        except Exception:  # pragma: no cover - защитная ветка
            per_chat_get = None
    return resolve_hybrid_length(per_chat_get=per_chat_get)


async def run_l2(llm=None, package=None, *, service=None, correlation_id=None,
                 slot=None, chat_id=None,
                 system_prompt=None, llm_call=None, source_input=None,
                 length=None) -> L2Result:
    """Один прогон L2: контент пакета §96 → **1 LLM-вызов** → §99-документ.

    ``llm`` — LLMClient (или совместимый мок); ``llm_call`` — инъекция канала
    (тесты/врезка). ``service`` — служебная секция пакета (response_mode L1
    остаётся observability/обложкой; ДЛИНУ определяет конфиг пользователя —
    контракт (f)/ADR-1027-10 D6). Fail-closed по hard-контракту §99
    (200/900/498/32000); превышение мягкой цели — НЕ ошибка (§3);
    ``chars > summary_hybrid_max_chars`` → WARN ``L2_OVER_SOFT_CEILING`` и
    публикация (никогда не обрезка). Провал L2 → recovery-контур (LEVEL-3
    Legacy) решает вызывающий ``summary_generator`` (AMEND ADR-1026-7 D5,
    ADR-1027-10 D3): здесь — только ``document=None``.
    Ровно один физический вызов на запуск (L2 correction retry не вводится).

    ASAP 4.1 волна 3 (T-4609, spec §2 B.3; ADR-1028-8 D4/AM-4) — аддитивно:
      * ``source_input`` — готовый WriterInput от Full SourceWindow
        (``build_l2_source_input``); передан → контент = source_input, пакет
        используется только для валидации id-space/эвиденции (Writer НЕ
        зависит от урезания пакета);
      * ``length`` — предр resolved length-блок вызывающим (иначе — прежний
        внутренний резолв, байт-в-байт);
      * system-канон: ON writer-source → канон R1030 (блок источника);
        OFF → прежний прод-канон R1029 (байт-в-бит; PG-override сохранён).
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

    # 2. Цели длины Hybrid (per-chat → hot → env → пресет): config-режим
    # пользователя побеждает L1-`response_mode` (контракт (f)).
    if length is not None:
        length = dict(length)
    else:
        length = await _hybrid_length_for_chat(chat_id)
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

    if isinstance(source_input, str) and source_input.strip():
        # T-4609: WriterInput от Full SourceWindow (пакет — только для
        # валидации; контент = source-секции).
        content = source_input
    else:
        content = build_l2_input(package, length=length)
    # ASAP-2.1 (Q10/T-3965): эффективный prompt + честный источник для
    # observability. Резолв до _log_start (ключ/источник известны к событию).
    if system_prompt:
        system = system_prompt
        prompt_source = "param"
    else:
        # Волна 3 (T-4609): fallback-канон зависит от kill-switch'а входа
        # (ON → R1030 с блоком источника; OFF → прод-канон R1029 байт-в-байт;
        # PG-override — общий ключ prompts.summary_l2_writer_system_prompt).
        default_prompt = (SUMMARY_L2_WRITER_SYSTEM_PROMPT
                          if writer_source_input_enabled()
                          else PREV_SUMMARY_L2_WRITER_R1029_ASAP41)
        system, prompt_source = resolve_prompt_with_source(
            PROMPT_PG_KEY, default_prompt)
    _log_start(correlation_id=correlation_id, chat_id=chat_id,
               paragraphs_hint=int(length["target_paragraphs"]),
               model=model, base_url=base_url,
               dedicated=resolved_slot.dedicated,
               response_mode=length["response_mode"],
               target_chars=length["target_chars"],
               target_paragraphs=length["target_paragraphs"],
               prompt_key=PROMPT_PG_KEY, prompt_source=prompt_source)
    call = llm_call or _make_llm_call(llm, resolved_slot, correlation_id)
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
        if document is None:
            result = invalid_result(
                metrics.get("reason", REASON_INVALID_PARAGRAPH),
                duration_ms=_elapsed(), usage=usage, metrics=metrics)
        else:
            metrics = dict(metrics)
            metrics["title_len"] = len(document["title"])
            # §18: chars-итог статьи (title + абзацы, та же мера, что hard-
            # проверка `too_long`).
            chars = len(document["title"]) + sum(
                len(p["text"]) + (len(p["emphasis"]) if p["emphasis"] else 0)
                for p in document["paragraphs"])
            metrics["chars"] = chars
            # WARN-полоса 24000<chars≤32000 (контракт Q4/T-3939): публикуем,
            # НЕ обрезаем; chars>32000 уже отбракован валидатором (too_long).
            if chars > int(length["max_chars"]):
                logger.warning(
                    "L2_OVER_SOFT_CEILING | run_id=%s | chat_id=%s | "
                    "chars=%d | max_chars=%d — публикуем без обрезки",
                    correlation_id or "none", chat_id, chars,
                    int(length["max_chars"]))
            result = _make_result(STATUS_OK, document=document, usage=usage,
                                  metrics=metrics, duration_ms=_elapsed())

    _log_complete(correlation_id=correlation_id, chat_id=chat_id,
                  result=result, model=model, base_url=base_url,
                  tokens_in=tokens_in, tokens_out=tokens_out)
    return result
