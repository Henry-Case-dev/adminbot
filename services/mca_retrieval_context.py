"""Раунд 10.27 (MCA Wave 1, `mca-07-retrieval-context`, ADR-1027-7) — единый
контракт retrieval/reranker/EvidenceBundle.

Это **контрактный слой**, а не второй движок (GEN-R19): retrieval
**оборачивает** существующие каналы (FTS/exact `search_*_fts`, vector через
`MemoryManager`, reply-граф `thread_chain`, эпизоды `lore_stories`), reranker —
единое типизированное ядро, к которому приводятся существующие
`summary_memory.rerank_rag_facts`/`search_service._rerank_results` адаптерами,
EvidenceBundle — in-memory ссылочный контракт §11.2 (ссылается на SourceRef
`mca-04a`, не копирует архив).

Kill-switch (env-only, default ON, per-call, не бросают):
  * `MCA_RETRIEVAL_CONTEXT_ENABLED` — единый retrieval-контракт + embedding
    identity-политика;
  * `MCA_TYPED_RERANKER_ENABLED` — типизированный reranker;
  * `MCA_EVIDENCE_BUNDLE_ENABLED` — единый bundle.

R17: наружу — только id/коды/длины; сырой контекст/секреты не логируются.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import re
import time

from services import mca_gates
from services import memory_contracts as _mc

logger = logging.getLogger(__name__)

# ── версии политик (участвуют в context_version) ────────────────────────────
BUNDLE_SCHEMA_VERSION = "mca07-bundle-1"
RETRIEVAL_POLICY_VERSION = "mca07-retrieval-1"

# ── границы fallback (детерминированный bounded pre-rerank-порядок, D3) ─────
DEFAULT_RERANK_FALLBACK_TOP_K = 8

# ── статусы reranker (типизированный контракт §4.2) ─────────────────────────
RERANK_OK = "ok"
RERANK_EMPTY = "empty"
RERANK_INVALID = "invalid"
RERANK_TIMEOUT = "timeout"
RERANK_ERROR = "error"
RERANK_STATUSES = frozenset({RERANK_OK, RERANK_EMPTY, RERANK_INVALID,
                             RERANK_TIMEOUT, RERANK_ERROR})

_NUM_RE = re.compile(r"\d+")


@dataclasses.dataclass(frozen=True)
class RerankItem:
    """Элемент типизированного выбора reranker: стабильный ID + оценка."""
    id: str
    score: float


@dataclasses.dataclass(frozen=True)
class RerankResult:
    """Типизированный результат reranker (§4.2).

    ``status``: ``ok|empty|invalid|timeout|error``. ``ok`` + ``selected=[]``
    (== ``empty``) — валидный пустой результат: контекст пуст, **не**
    разворачивается во всех кандидатов. ``invalid``/``timeout``/``error`` —
    отдельный статус с явным bounded fallback (pre-rerank-порядок)."""
    status: str
    selected: tuple[RerankItem, ...] = ()
    reason_code: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.status in (RERANK_INVALID, RERANK_TIMEOUT, RERANK_ERROR)

    @property
    def is_valid_empty(self) -> bool:
        return self.status == RERANK_EMPTY or (
            self.status == RERANK_OK and not self.selected)


def classify_rerank_response(raw) -> tuple[str, tuple[int, ...]]:
    """Разбор ответа LLM в (status, упорядоченные числа).

    * ``None`` → ``("error", ())``;
    * пустая строка / ``[]`` / ``{}`` → ``("empty", ())`` — валидный пустой;
    * есть числа → ``("ok", nums)`` (порядок оценки; дубликаты убраны по
      первому вхождению);
    * непустой текст без чисел → ``("invalid", ())``.

    Числа НЕ валидируются по диапазону кандидатов здесь — это делает адаптер
    (``select_by_rerank``): невалидные диапазоны → ``invalid``.
    """
    if raw is None:
        return RERANK_ERROR, ()
    text = str(raw).strip()
    if text in ("", "[]", "[ ]", "{}", "нет"):
        return RERANK_EMPTY, ()
    nums: list[int] = []
    for token in _NUM_RE.findall(text):
        try:
            value = int(token)
        except ValueError:      # pragma: no cover - защитная ветка
            continue
        if value not in nums:
            nums.append(value)
    if not nums:
        return RERANK_INVALID, ()
    return RERANK_OK, tuple(nums)


def classify_rerank_exception(exc: BaseException) -> str:
    """Класс исключения LLM → статус reranker (``timeout`` либо ``error``)."""
    name = type(exc).__name__.lower()
    if "timeout" in name or isinstance(exc, TimeoutError):
        return RERANK_TIMEOUT
    return RERANK_ERROR


def select_by_rerank(candidates: list, status: str,
                     numbers: tuple[int, ...], *, id_of=None,
                     top_k: int | None = None) -> RerankResult:
    """Собрать ``RerankResult`` из разобранных чисел и списка кандидатов.

    ``id_of(candidate, index)`` — стабильный ID кандидата (по умолчанию
    ``candidate["id"]``/``candidate.id``). Числа трактуются как 1-based
    позиции. ``ok`` без валидных позиций → ``invalid`` (модель не дала
    корректного выбора — отдельное состояние, НЕ «все кандидаты»)."""
    def _id(candidate, index):
        if id_of is not None:
            return str(id_of(candidate, index))
        if isinstance(candidate, dict):
            return str(candidate.get("id", index + 1))
        return str(getattr(candidate, "id", index + 1))

    if status == RERANK_EMPTY:
        return RerankResult(RERANK_EMPTY, ())
    if status in (RERANK_TIMEOUT, RERANK_ERROR):
        return RerankResult(status, (), status)
    n = len(candidates)
    selected: list[RerankItem] = []
    score = float(len(numbers) or 1)
    for position in numbers:
        if 1 <= position <= n:
            selected.append(RerankItem(id=_id(candidates[position - 1],
                                              position - 1),
                                       score=score))
            score -= 1.0
    if not selected:
        # Числа были, но ни одно не попало в диапазон → непарсимое.
        return RerankResult(RERANK_INVALID, (), RERANK_INVALID)
    return RerankResult(RERANK_OK, tuple(selected))


def fallback_top_k(count: int, top_k: int | None = None) -> int:
    """Граница детерминированного bounded fallback (pre-rerank-порядок)."""
    limit = DEFAULT_RERANK_FALLBACK_TOP_K if top_k is None else int(top_k)
    return max(0, min(int(count), max(0, limit)))


# ── EvidenceBundle §11.2 (in-memory, ссылочный) ─────────────────────────────

@dataclasses.dataclass(frozen=True)
class EvidenceItem:
    """Ссылка на факт/эпизод: SourceRef `mca-04a` + время (не копия сырья)."""
    source_ref_id: int | None
    entity_type: str
    entity_id: str
    sent_at: int = 0
    revision: str | None = None
    label: str = ""


@dataclasses.dataclass(frozen=True)
class ExcludedItem:
    """Исключённый материал + причина (видим в диагностике, A24)."""
    ref: str
    position: int = 0
    reason_code: str = ""
    estimated_tokens: int = 0


# ── MCA-16 (AM-1; ADR-1028-15 D6, T-4993): lessons — отдельный тип в
# ЕДИНСТВЕННОМ EvidenceBundle (аддитивно; пустое поле = байт-паритет
# 2.58.58; `BUNDLE_SCHEMA_VERSION` не меняется). Знания о людях ≠
# процедурные рекомендации: LessonRef — ссылка + серверно-канонический
# текст, не копия реплик (R17).
@dataclasses.dataclass(frozen=True)
class LessonRef:
    """Ссылка на проверенный урок (mca-16) для bounded-блока контекста."""
    lesson_id: str
    version: int
    type: str
    scope: str
    applicability: str = ""
    recommendation: str = ""
    exceptions: str = ""
    # MOD-ACL-UX-01 amendment: адаптивный временной ранг урока (1.0 старт,
    # cap 2.0). Только для выдачи/сортировки; текст в prompt не добавляется.
    temporal_rank: float = 1.0


@dataclasses.dataclass(frozen=True)
class EvidenceBundle:
    """Логический контракт §11.2 (frozen, in-memory).

    Ссылается на уже durable SourceRef/EvidenceLink/`smart_messages`, НЕ
    копирует архив (§11.2). Durable-наружу — только `context_version` +
    SourceRef-ссылки (R17)."""
    trigger: str | None = None
    current_message_ref: str | None = None
    current_revision: str | None = None
    addressee: str | None = None
    author: str | None = None
    mentioned: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    branch: tuple[str, ...] = ()
    local_context: tuple[str, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    constraints: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    persona: str | None = None
    interests: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    chosen_intent: str | None = None
    recent_actions: tuple[str, ...] = ()
    context_version: str = ""
    excluded: tuple[ExcludedItem, ...] = ()
    schema_version: str = BUNDLE_SCHEMA_VERSION
    # ── MCA-22 (C6, §11/§28 ТЗ; ADR-1028-6 D7): bundle v2 — раздельные
    # смысловые слоты (author и addressee НЕ схлопываются в target_name),
    # реальный revision MCA-03 и subjects ретрив-утверждений. Заполняется
    # только под `MCA_CANONICAL_ATTRIBUTION_ENABLED` (OFF = паритет legacy).
    direct_addressee: str | None = None       # кому адресован ответ (bot/user)
    reply_addressee: str | None = None        # автор сообщения-ответа
    quoted_speaker: str | None = None         # автор цитаты (≠ author!)
    subjects: tuple[str, ...] = ()            # subjects retrieval-кандидатов
    structured: bool = False                  # True = собран structure-first
    # ── MCA-16 (AM-1; ADR-1028-15 D6): проверенные уроки — ОТДЕЛЬНЫЙ тип в
    # единственном bundle (аддитивно; пустое поле = байт-паритет 2.58.58).
    # Наполняет LessonService (scope/active → compat → relevance → utility);
    # suspended/disabled/stale не включаются. Поля M-MCA07-2 не трогаются.
    lessons: tuple[LessonRef, ...] = ()
    # ── MEMORY-06 (§7.2, MEM-06.8): ЧЕЛОВЕЧЕСКИЙ evidence summary для Writer
    # (дата/автор/источник, без внутренних id и метрик). Дополнение к bundle,
    # а не изменение активных промптов: в Telegram не выводится, в логи — без
    # текста (R17). Пусто → байт-паритет прежнего bundle.
    summary_text: tuple[str, ...] = ()
    # ── VMQ-M2 (M-04; ARCH_REUSE_CONFIRMED): bounded overview-слоты ЕДИНОГО
    # bundle. Наполняет `apply_overview_to_bundle` из результата того же
    # `retrieve()`; своего bundle/хранилища не появляется. Пусто = точный
    # паритет прежнего bundle (schema_version не меняется).
    coverage: tuple[str, ...] = ()            # что реально покрыто (периоды)
    independent_periods: tuple[str, ...] = ()  # периоды с независимой опорой
    counterexamples: tuple[str, ...] = ()      # контрпримеры (отдельно от опоры)
    limitations: tuple[str, ...] = ()          # честные ограничения покрытия
    episode_refs: tuple[str, ...] = ()         # эпизоды-опора (lineage-ссылки)
    semantic_hints: tuple[str, ...] = ()       # типизированные определения-хинты


# ── MEMORY-06 (§7.2, MEM-06.8): человеческий evidence summary ──────────────
# Writer получает дату/автора/источник и «предположение/пересылку» обычным
# текстом; внутренние id, cosine, channel= и raw-тройки в него не попадают.
_SUMMARY_INTERNAL_RE = re.compile(
    r"\b(?:tg|msg|fact|ent|edge|comm|episode):\S*"
    r"|\b(?:node_id|edge_id|source_ref_id|chat_id|cosine)\b"
    r"|\bchannel=\S*", re.IGNORECASE)


def humanize_summary_text(value) -> str:
    """Убрать внутренние id/метрики из человеческой строки (§7.2/S-7/R17)."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    text = _SUMMARY_INTERNAL_RE.sub("", text)
    return " ".join(text.replace("()", "").split()).strip(" -—:;,")


def summary_date(ts, tz_name: str = "") -> str:
    """Дата события в поясе ЧАТА (§7.2: `chat_clock`, не UTC-число)."""
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
    if tz_name:
        try:
            import zoneinfo
            moment = moment.astimezone(zoneinfo.ZoneInfo(str(tz_name)))
        except Exception:
            pass                     # неизвестный пояс → UTC (честно)
    return moment.strftime("%d.%m.%Y")


async def chat_timezone_name(chat_id) -> str:
    """IANA-пояс чата через существующий `chat_clock.snapshot` (fail-open)."""
    try:
        from services import chat_clock
        snap = await chat_clock.snapshot(chat_id)
        return str(getattr(snap, "timezone", "") or "")
    except Exception:
        return ""


_SUMMARY_CERTAINTY_PREFIX = {
    "assumption": "предположение / гипотеза: ",
    "unconfirmed": "не подтверждено: ",
    "archive": "архивный факт: ",
}


def render_evidence_summary(rows, *, tz_name: str = "") -> tuple[str, ...]:
    """Собрать человеческие строки evidence summary (§7.2).

    ``rows`` — словари: ``kind`` (fact|message|episode), ``text``, ``author``,
    ``ts``, ``forward_from``, ``certainty`` (assumption|unconfirmed|archive),
    ``episode_bounds``. Никаких id/score в выходе; пустой текст не выводится.
    """
    lines: list[str] = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        text = humanize_summary_text(row.get("text"))
        if not text:
            continue
        kind = str(row.get("kind") or "fact").strip().lower()
        author = humanize_summary_text(row.get("author"))
        date = summary_date(row.get("ts"), tz_name)
        certainty = str(row.get("certainty") or "").strip().lower()
        prefix = _SUMMARY_CERTAINTY_PREFIX.get(certainty, "")
        if kind == "episode":
            bounds = humanize_summary_text(row.get("episode_bounds"))
            line = (f"эпизод ({bounds}): {text}" if bounds
                    else f"эпизод: {text}")
        elif author and date:
            line = f"{author} сказал(а) {date}: {text}"
        elif author:
            line = f"{author} сказал(а): {text}"
        elif date:
            line = f"Записано {date}: {text}"
        else:
            line = f"Записано: {text}"
        forward = humanize_summary_text(row.get("forward_from"))
        if forward:
            line += f" — пересланное сообщение, первоисточник: {forward}"
        lines.append(prefix + line)
    return tuple(lines)


def compute_context_version(*, current_revision=None, selected_refs=(),
                            summary_revision=None, persona_version=None,
                            config_version=None, policy_version=None,
                            embedding_generation=None,
                            embedding_fingerprint=None) -> str:
    """Детерминированный fingerprint зависимостей bundle (§4.4/D5).

    Меняется при изменении любой зависимости; **не** отдельная таблица
    (derived). ``selected_refs`` — упорядоченный список
    ``(SourceRef-id, revision)`` выбранных материалов."""
    parts = [
        "schema=" + BUNDLE_SCHEMA_VERSION,
        "policy=" + str(policy_version or RETRIEVAL_POLICY_VERSION),
        "current=" + str(current_revision or ""),
        "summary=" + str(summary_revision or ""),
        "persona=" + str(persona_version or ""),
        "config=" + str(config_version or ""),
        "embed_gen=" + str(embedding_generation if embedding_generation is not None else ""),
        "embed_fp=" + str(embedding_fingerprint or ""),
    ]
    for ref in selected_refs or ():
        try:
            ref_id, revision = ref
        except (TypeError, ValueError):
            ref_id, revision = ref, None
        parts.append(f"ref={ref_id}:{revision or ''}")
    material = "\x1f".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


# ── события (REUSE mca-13; второй store запрещён) ───────────────────────────

def emit_stage_event(stage: str, outcome: str, *, level: str | None = None,
                     **fields):
    """Fail-open событие стадии (retrieval/reranker/bundle/budget/summary).

    REUSE `emit_mca_event` (mca-13). Не бросает — импорт ленивый (циклы)."""
    try:
        from services.mca_events import (
            LEVEL_INFO, emit_mca_event,
        )
        return emit_mca_event(
            "mca07_" + str(stage), outcome=outcome,
            level=level or LEVEL_INFO, component="retrieval_context",
            stage=str(stage)[:60], **fields)
    except Exception:      # fail-open: контракт не рвёт поток
        return None


# ── единый retrieval-контракт (D1/D2) ───────────────────────────────────────

RETRIEVAL_OK = "ok"
RETRIEVAL_EMPTY = "empty"
RETRIEVAL_ERROR = "error"

# Веса каналов (детерминированная агрегация, не «движок»).
_CHANNEL_WEIGHTS = {
    "exact": 100.0,
    # §7.5 MEMORY-06 (фикс регрессии): канал `subject` — ФАКТЫ О СУБЪЕКТЕ,
    # отобранные по существующим колонкам субъекта (`subject_ref_id`/
    # `target_user`), а НЕ по совпадению текста с запросом. Факт «любит дронов»
    # не содержит имени человека и FTS его не находит, но он о нём. Вес сразу
    # под exact: это самое точное знание о конкретном человеке.
    "subject": 95.0,
    # §4.4 MEMORY-06: новый канал `entity` (канонический узел C-1 по
    # `subject_node_ids`) — вес между exact и lexical. Это bounded чтение
    # `nodes` ПО ID, а не второй поиск.
    "entity": 90.0,
    "lexical": 80.0,
    "vector": 60.0,
    "reply_graph": 40.0,
    # §4.4/§6: членство в активной сборке сообществ (C-6). Таблицы сборки
    # появляются в MEMORY-07; до неё канал честно пуст (не выдумывается).
    "community": 30.0,
    "episode": 20.0,
    # §7.5 MEMORY-06: bounded-срез последних сообщений ЯВНО
    # запрошенных участников (`get_recent_messages`) — существующее
    # чтение для профиля речи; включается только `scope='participants'`
    # + явный канал, второй поиск не создаётся.
    "recent": 70.0,
}
_CHANNEL_ORDER = ("exact", "subject", "entity", "lexical", "recent", "vector",
                  "reply_graph", "community", "episode")
#: SXR-C2 (финальный срез): это ТОЛЬКО граница UI-сниппета поиска памяти
#: (`memory_contracts.preview_max_chars()`/`memory_search`), а не кап данных
#: retrieval. Кандидат несёт полный фрагмент источника: срез 400 удалён,
#: иначе `get_user_context` отдавал бы памяти усечённый текст без пометки.
_PREVIEW_MAX_CHARS = 400
#: §7.5: во сколько раз срез `get_recent_messages` шире запрошенного top_k
#: (bounded: окно чтения конечно и не зависит от корпуса).
_RECENT_SCAN_FACTOR = 6

# ── MEMORY-06 (§4.4/§7.1): расширение ЕДИНОГО retrieval-контракта ───────────
# Purpose/mode/scope — REUSE закрытых наборов MEMORY-01 (`memory_contracts`);
# второй закрытый набор значений не создаётся (§0.2/INV-03).
RETRIEVAL_PURPOSES = tuple(p.value for p in _mc.MemoryPurpose)
RETRIEVAL_MODES = tuple(m.value for m in _mc.IntentMode)
RETRIEVAL_INTENTS = ("fact", "who", "what-happened", "history",
                     "relationship", "current", "follow-up", "broad-theme",
                     "auto")
#: §4.1: верхняя граница выдачи UI-поиска (только `purpose='ui_search'`).
UI_SEARCH_MAX_LIMIT = _mc.SEARCH_LIMIT_MAX
#: Политика каналов по умолчанию (порядок — приоритет стабильности выдачи).
_DEFAULT_CHANNELS = ("exact", "entity", "lexical", "vector", "reply_graph",
                     "episode")
#: `mode` в трёх режимах MEM-06.6 → существующие ветки retrieval (§7.1).
_INTENT_TO_MODE = {
    "fact": "specific", "who": "specific", "relationship": "specific",
    "current": "specific",
    "what-happened": "episodic", "history": "episodic",
    "broad-theme": "thematic",
    # `follow-up`/`auto` — без принудительного режима: существующая
    # эвристика `_HISTORY_MARKERS`, иначе обычная смешанная выдача.
}
#: VMQ-MEM (измерение 2.58.179 §5): эпизод — сжатый АГРЕГАТ по тому же
#: корпусу (topic/story), а не независимый источник. Пока `history_bias` был
#: первым ключом сортировки, эпизоды стояли ВЫШЕ любого другого канала, и на
#: архиве 2 067 222 сообщений срез истории заполнялся ими целиком: 40/40
#: слотов эпизодами при score 25 против 79-80 у корпусных message-хитов, из-за
#: чего verbatim-потребитель (`<Old_Episode>`) получал 0 материала. Резерв:
#: эпизоды по-прежнему первыми, но занимают не более 1/N среза, пока есть
#: кандидаты других каналов (эпизоды-первыми НЕ отменяются — ADR-1027-7 D2).
_HISTORY_EPISODE_SLICE_DIV = 2
#: Максимальный «бонус свежести» в единицах типизированного ранга. Строго
#: меньше разрыва между соседними каналами (20), поэтому близкая по времени
#: запись не перебивает более сильный канал (§7.1/MEM-06.4).
_TYPED_RECENCY_BONUS = 12.0
_TYPED_TRUST_BONUS = 8.0
_TYPED_LEGACY_PENALTY = 8.0
# Маркеры исторического запроса (эвристика mode=auto; явный mode имеет приоритет).
_HISTORY_MARKERS = (
    "истори", "расскажи", "что было", "что происходило", "раньше", "когда-то",
    "когда то", "вспомни, как", "вспомни как", "хроник", "летопис",
)

# ── VMQ-MEM/TIME Slice A (15.11.2026): структурированный периодный intent ───
# Явный год или обнаруженный мемуарный/исторический запрос передаются в
# периодный добор отдельным значением, а не угадываются потребителем повторно.
# `_HISTORY_MARKERS` выше НЕ расширяется: набор форм ниже добавляет только
# повествовательные словоформы, и с Slice C тот же `PeriodIntent` (а не
# отдельный словарь потребителя) решает и допустимость M2-обзора.
PERIOD_INTENT_NONE = "none"
PERIOD_INTENT_YEAR = "explicit_year"
PERIOD_INTENT_HISTORICAL = "historical"
#: Slice B (15.11.2026): структурный multi-year intent для вопроса о событии
#: БЕЗ года. Источник — существующий request/plan-сигнал
#: (`RetrievalRequest.intent`/`mode`, `L1Plan.response_act`), НЕ словарь
#: «напомни/что было»: `_HISTORY_MARKERS` и `_PERIOD_HISTORY_MARKERS` не
#: расширяются.
PERIOD_INTENT_MULTI_YEAR = "multi_year"

#: Коды причин отсева периодного пула (наружу — только коды и числа).
PERIOD_DROP_OUT_OF_TARGET_YEAR = "out_of_target_year"
PERIOD_DROP_UNKNOWN_YEAR = "unknown_year"
PERIOD_DROP_SUBJECT = "subject_mismatch"
PERIOD_DROP_POOL_CAP = "period_pool_cap"
#: Slice D: статус строки не участвует в исторической выдаче (не
#: `confirmed`/`archived_*`). SQL-каналы такие строки и так не отдают; отбор
#: обязан вести себя так же, если строка пришла от другого канала.
PERIOD_DROP_STATUS = "status_not_usable"
#: Как строка вошла: год-цель сохранён / мягкий предметный fallback / вектор /
#: ограниченная историческая квота / multi-year квота.
PERIOD_KEEP_IN_TARGET = "in_target_year"
PERIOD_KEEP_SOFT_FALLBACK = "subject_soft_fallback"
PERIOD_KEEP_VECTOR = "vector_leg_no_threshold"
PERIOD_KEEP_HISTORICAL_QUOTA = "historical_quota"
PERIOD_KEEP_MULTI_YEAR = "multi_year_quota"

#: Порог «тот же предмет, не то же слово» (действующий §2: ≥2 общих основы).
PERIOD_MIN_SHARED_STEMS = 2
#: Мягкий fallback исторического намерения включается, только когда пул даёт
#: НЕ МЕНЬШЕ двух строк с одной общей основой: одна случайная строка блок не
#: собирает (действующий контракт next-stage «§2/§5 одна чужая строка»).
PERIOD_SOFT_FALLBACK_MIN_ROWS = 2
#: Формы исторического/мемуарного запроса для ПЕРИОДНОГО намерения. Только
#: основа сравнения уже существующих маркеров + повествовательные словоформы
#: («рассказ» не входит в `_HISTORY_MARKERS`, где стоит «расскажи»).
_PERIOD_HISTORY_MARKERS = _HISTORY_MARKERS + (
    "рассказ", "за все годы", "за эти годы", "биограф",
)
_YEAR_IN_QUERY_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


@dataclasses.dataclass(frozen=True)
class PeriodIntent:
    """Структурированное намерение периода (Slice A/B): отбор пула и M2-обзор.

    ``kind`` — закрытый набор `none|explicit_year|historical|multi_year`;
    ``years`` — явные годы запроса (только для `explicit_year`); ``source`` —
    откуда намерение взялось (`query_year|request_intent|plan_act|
    request_mode|memory_scope|query_marker`). Пустой `PeriodIntent()` —
    прежнее поведение: отбор по одному порогу основ.

    Slice C: тот же объект — единственный структурный сигнал допустимости
    M2-обзора (`wants_overview`); второго словаря у потребителя нет."""
    kind: str = PERIOD_INTENT_NONE
    years: tuple[int, ...] = ()
    source: str = ""

    @property
    def is_explicit_year(self) -> bool:
        return self.kind == PERIOD_INTENT_YEAR and bool(self.years)

    @property
    def is_historical(self) -> bool:
        return self.kind == PERIOD_INTENT_HISTORICAL

    @property
    def is_multi_year(self) -> bool:
        return self.kind == PERIOD_INTENT_MULTI_YEAR

    @property
    def wants_year_diverse(self) -> bool:
        """Исторический/много летний вопрос: нужен bounded multi-year вклад."""
        return self.is_historical or self.is_multi_year

    @property
    def wants_overview(self) -> bool:
        """VMQ-MEM/TIME Slice C: структурный сигнал bounded-обзора (M2/O-04).

        Обзор покрытия допустим ровно тогда, когда периодное намерение
        распознано: явный год, исторический/много летний вопрос или принятое
        решение (план `historical_recall`, политика `historical`). `source`
        называет сработавший СУЩЕСТВУЮЩИЙ сигнал (`query_year`, `plan_act`,
        `request_intent`, `request_mode`, `memory_scope`, `query_marker`).
        `none` — сигнала нет: обзор НЕ запрашивается (никакого нового списка
        слов и никакой догадки о «творческом» запросе)."""
        return self.kind != PERIOD_INTENT_NONE

    def as_dict(self) -> dict:
        return {"kind": self.kind, "years": list(self.years),
                "source": self.source}


def resolve_period_intent(query, *, memory_scope: str = "auto",
                          request_intent: str = "", request_mode: str = "",
                          plan_act: str = "") -> PeriodIntent:
    """Детерминированное периодное намерение запроса (без LLM и без словаря
    «сейчас»). Приоритет: явный год → СТРУКТУРНЫЙ request/plan-сигнал →
    `memory_scope=historical` → маркеры исторического/мемуарного запроса →
    `none` (прежний путь).

    Slice B: `request_intent` (`what-happened|history`), `request_mode`
    (`history|episodic`) и `plan_act` (`historical_recall`) — существующие
    закрытые значения retrieval/L1-плана, а не новый список слов. Вопрос о
    событии без года получает `multi_year` независимо от того, назван ли год
    или слово «вспомни»."""
    text = str(query or "").casefold()
    years = tuple(sorted({int(y) for y in _YEAR_IN_QUERY_RE.findall(text)}))
    if years:
        return PeriodIntent(PERIOD_INTENT_YEAR, years, "query_year")
    intent_kind = str(request_intent or "").strip().lower()
    if intent_kind in ("what-happened", "history"):
        return PeriodIntent(PERIOD_INTENT_MULTI_YEAR, (),
                            "request_intent")
    plan_kind = str(plan_act or "").strip().lower()
    if plan_kind == "historical_recall":
        return PeriodIntent(PERIOD_INTENT_MULTI_YEAR, (), "plan_act")
    mode_kind = str(request_mode or "").strip().lower()
    if mode_kind in ("history", "episodic"):
        return PeriodIntent(PERIOD_INTENT_MULTI_YEAR, (), "request_mode")
    try:
        scope = str(_mc.normalize_memory_scope(memory_scope).value)
    except Exception:                                     # pragma: no cover
        scope = "auto"
    if scope == "historical":
        return PeriodIntent(PERIOD_INTENT_HISTORICAL, (), "memory_scope")
    for marker in _PERIOD_HISTORY_MARKERS:
        if marker in text:
            return PeriodIntent(PERIOD_INTENT_HISTORICAL, (), "query_marker")
    return PeriodIntent()


#: Slice D (ARCH_DECISION 15.11.2026): источники `PeriodIntent`, которым
#: разрешено ЗАМЕЩАТЬ текущий срез старым материалом. Авторитет «настоящее vs
#: историческое» — только решение L1 (`memory_scope`, `response_act`) и явный
#: год запроса. `query_marker` (словарная эвристика) в множество НЕ входит:
#: формулировка не имеет права вытеснять текущий срез; она может лишь
#: запросить overview (M2/Slice C), который сам по себе не замещает факты.
PERIOD_REPLACE_SOURCES = frozenset({
    "query_year", "request_intent", "plan_act", "request_mode",
    "memory_scope",
})


def period_replace_allowed(intent, policy: str) -> bool:
    """Можно ли этому намерению замещать текущий срез старым материалом.

    Единственный предикат на все пути (retrieval-консьюмер, профиль, трасса):
    `operative` — никогда; `historical` — всегда; `auto` — только если
    намерение пришло из структурного решения L1/плана или явного года
    (`PERIOD_REPLACE_SOURCES`), но не из словарного `query_marker`. Никогда не
    бросает: неизвестная политика нормализуется в `auto`."""
    scope = _mc.normalize_memory_scope(policy).value
    if scope == "operative":
        return False
    if scope == "historical":
        return True
    return str(getattr(intent, "source", "") or "") in PERIOD_REPLACE_SOURCES


def year_time_bounds(year) -> tuple[int, int] | None:
    """UTC-границы календарного года `[start, end]` (секунды) или None.

    Один примитив для явного года: используется периодным отбором и
    `<Old_Episode>`, чтобы окно не собиралось в двух местах по-разному.
    Невалидный/нечисловой год → None (fail-closed, без догадки)."""
    try:
        value = int(year)
    except (TypeError, ValueError):
        return None
    if value < 1970 or value > 9999:
        return None
    try:
        start = int(datetime.datetime(
            value, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
        end = int(datetime.datetime(
            value, 12, 31, 23, 59, 59,
            tzinfo=datetime.timezone.utc).timestamp())
    except (ValueError, OverflowError, OSError):          # pragma: no cover
        return None
    return start, end


def period_row_year(row) -> int | None:
    """Год строки-факта периодного пула (`message_timestamp`→`created_at`→
    `rag_ts`) в UTC. Неизвестное время — None (не догадка)."""
    if not isinstance(row, dict):
        return None
    ts = (row.get("message_timestamp") or row.get("created_at")
          or row.get("rag_ts"))
    if not ts:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).year
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _candidate_year(cand) -> int | None:
    """Год retrieval-кандидата по событийному `sent_at` (UTC)."""
    try:
        ts = int(getattr(cand, "sent_at", 0) or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc).year
    except (OSError, OverflowError, ValueError):            # pragma: no cover
        return None


def period_subject_stems(text, *, explicit_year: bool = False) -> set:
    """Основы значимых слов + аддитивный 3-символьный content-stem (RC4/A2).

    Никаких списков тем/годов: тот же `_tokenize`, `text_morphology.stem_word`
    и retrieval-only `short_stem_word`, что использует SQL-окно периодного
    FTS (`_period_fts_keywords`). `explicit_year=True` исключает годовые слова
    и служебные предлоги (D4), но не меняет порог §2.
    """
    try:
        from services.text_morphology import short_stem_word, stem_word
    except Exception:                                     # pragma: no cover
        return set()
    out: set = set()
    for word in _tokenize(text):
        token = str(word).casefold()
        if explicit_year and (
                _YEAR_IN_QUERY_RE.fullmatch(token)
                or token in _YEAR_WORD_TOKENS
                or token in _MESSAGE_WINDOW_STOPWORDS):
            continue
        if token in _MESSAGE_WINDOW_STOPWORDS:
            # RC4-R1-01: служебное слово не получает short-stem; его обычная
            # основа (если >=4) остаётся для различения субъектов, но не
            # может обходить порог 2 через «мен»/«что»/«для».
            stem = stem_word(token)
            if len(stem) >= 4:
                out.add(stem)
            continue
        # Одна нормализация на слово: short-stem является АЛЬТЕРНАТИВОЙ
        # обычной основе, а не вторым независимым stem (иначе одно слово
        # даёт два «общих» стема и обходит порог §2).
        short = short_stem_word(token)
        stem = short or stem_word(token)
        if len(stem) >= (3 if short else 4):
            out.add(stem)
    return out


def period_subject_shared(query_stems: set, text, *,
                          explicit_year: bool = False) -> int:
    """Сколько РАЗНЫХ основ делят вопрос и текст факта (§2).

    Это лексическая релевантность пары «вопрос ↔ строка», а не независимость
    оснований; значение пишется в строку (`stems_shared`) один раз."""
    if not query_stems or not str(text or "").strip():
        return 0
    return len(set(query_stems) & period_subject_stems(
        text, explicit_year=explicit_year))


def period_row_proxy(row) -> str | None:
    """Как строка вошла в периодный добор: `knn` (векторная нога) / `stems`."""
    if not isinstance(row, dict):
        return None
    proxy = row.get("subject_proxy")
    if proxy:
        return str(proxy)
    source = str(row.get("period_source") or "")
    if source == "vector":
        return "knn"
    if source == "lexical":
        return "stems"
    return source or None


def _mark_period_row(row, shared, reason: str) -> None:
    """Записать единственное вычисление `stems_shared` в саму строку."""
    if not isinstance(row, dict):
        return
    row["stems_shared"] = None if shared is None else int(shared)
    row["stems_shared_reason"] = reason


def select_period_rows(rows, *, query: str = "", intent: "PeriodIntent | None" = None,
                       policy: str = "auto", slots: int = 2,
                       reference_year: int | None = None,
                       review: bool = False) -> tuple[list, dict]:
    """Отбор периодного пула: время-цель ПЕРВЫМ, предмет — с мягким fallback.

    VMQ-MEM/TIME Slice A (15.11.2026). Прежний безусловный порог ≥2 основ
    отклонял корректные строки явного года (13 строк 2023 в пуле → 0
    принятых). Здесь:

    * `explicit_year` — строки ВНУТРИ целевого года сохраняются (порядок — по
      числу общих основ), строки другого года и с неизвестным временем
      отбрасываются с кодом причины: 2026-строка не выдаёт себя за 2023;
    * `historical`/`review` — действующий порог ≥2 сохраняется, но если
      принятых меньше слотов и пул даёт не меньше двух строк с одной общей
      основой, добираются они (`subject_soft_fallback`, bounded) — «тот же
      предмет» без потери темы; одна слабая строка блок не собирает;
    * `none` — прежний путь (порог ≥2, векторная строка под `auto` тоже
      проходит порог): текущее состояние не ослабляется, словаря «сейчас»
      нет. Slice D (ARCH_DECISION 15.11.2026): паритет обычного вопроса
      удалён — замещать текущий срез имеет право только структурный сигнал
      L1/плана/явного года (`period_replace_allowed` у потребителя), а не
      формулировка запроса.

    TIME-03 natural memory (контракт 2026-11-20 §3.3/§4.2): календарной
    квоты/«другого года» здесь НЕТ. `review=True` — существующий L1-сигнал
    `research` (разбор материала), который разрешает тот же предметный
    soft-fallback, что `historical`, но не делает запрос «историческим
    режимом». Порядок добора — `-stems_shared`, затем индекс пула; год не
    участвует. `historical_quota`/`multi_year_quota` остаются нулями только
    для совместимости читателей трассы. Порядок строк внутри принятого
    набора — смысл/доказательство; `slots` — ресурсный предел вызывающего.

    Возвращает ``(принятые, статистика)``; статистика — только коды и числа
    (`dropped_*`, `kept_*`, `soft_fallback`, `intent`), без текстов фактов.
    Ступени потери года различимы: `pool_status`/`dropped_status` (статус
    материала), `pool_expired` (давность известна, но не является штрафом —
    `age_policy=not_applied`), `dropped_subject` (релевантность),
    `dropped_pool_cap` и `dropped_budget` (бюджет),
    `dropped_out_of_target_year`/`dropped_unknown_year` (время).
    """
    intent = intent or resolve_period_intent(query, memory_scope=policy)
    slots = max(1, int(slots or 1))
    query_stems = period_subject_stems(
        query, explicit_year=intent.is_explicit_year)
    rows = list(rows or ())
    vector_rows = [row for row in rows if period_row_proxy(row) == "knn"]
    lexical_rows = [row for row in rows if period_row_proxy(row) != "knn"]
    ordered = vector_rows + lexical_rows
    if reference_year is not None:
        try:
            current_year = int(reference_year)
        except (TypeError, ValueError):
            current_year = datetime.datetime.now(datetime.timezone.utc).year
    else:
        current_year = datetime.datetime.now(datetime.timezone.utc).year
    stats = {
        "intent": intent.as_dict(),
        "rows": len(rows),
        "kept": 0,
        "kept_in_target": 0,
        "kept_vector": 0,
        "dropped_out_of_target_year": 0,
        "dropped_unknown_year": 0,
        "dropped_subject": 0,
        "dropped_pool_cap": 0,
        "dropped_status": 0,
        "dropped_budget": 0,
        "pool_status": {"confirmed": 0, "archived": 0, "other": 0},
        "pool_expired": 0,
        "age_policy": "not_applied",
        "soft_fallback": 0,
        "historical_quota": 0,
        "multi_year_quota": 0,
        "lexical_strict_passed": 0,
    }
    now_ts = int(time.time())
    eligible: list = []
    for row in ordered:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if not status or status == "confirmed":
            stats["pool_status"]["confirmed"] += 1
        elif status in ("archived_fact", "archived_belief"):
            stats["pool_status"]["archived"] += 1
        else:
            stats["pool_status"]["other"] += 1
            stats["dropped_status"] += 1
            _mark_period_row(row, None, PERIOD_DROP_STATUS)
            continue
        expires_at = row.get("expires_at")
        if expires_at not in (None, ""):
            try:
                if int(expires_at) <= now_ts:
                    stats["pool_expired"] += 1
            except (TypeError, ValueError):
                pass
        eligible.append(row)
    ordered = eligible
    accepted: list = []
    # ── явный год: время-цель первым, предмет только упорядочивает ──────────
    if intent.is_explicit_year:
        years = set(int(y) for y in intent.years)
        cap = max(4, slots * 4)
        in_target: list[tuple[int, int, dict]] = []
        for index, row in enumerate(ordered):
            year = period_row_year(row)
            if year is None:
                stats["dropped_unknown_year"] += 1
                _mark_period_row(row, None, PERIOD_DROP_UNKNOWN_YEAR)
                continue
            if year not in years:
                stats["dropped_out_of_target_year"] += 1
                _mark_period_row(row, None, PERIOD_DROP_OUT_OF_TARGET_YEAR)
                continue
            shared = period_subject_shared(
                query_stems, (row or {}).get("fact"),
                explicit_year=intent.is_explicit_year)
            _mark_period_row(row, shared, PERIOD_KEEP_IN_TARGET)
            in_target.append((shared, index, row))
        in_target.sort(key=lambda item: (-item[0], item[1]))
        for _shared, _index, row in in_target:
            if len(accepted) >= cap:
                stats["dropped_pool_cap"] += 1
                continue
            accepted.append(row)
            stats["kept_in_target"] += 1
        # Бюджет для явного года — тот же `period_pool_cap` (под-категория,
        # а не второй счётчик: суммы причин не удваиваются).
        stats["dropped_budget"] = stats["dropped_pool_cap"]
        stats["kept"] = len(accepted)
        return accepted, stats
    # ── historical / none: действующий порог §2 + bounded мягкий fallback ────
    # Порог лексики остаётся прежним: векторная строка под `auto` тоже проходит
    # его (контракт C1 — «чужой текущий разговор» не входит). Обнаруженное
    # историческое намерение даёт только мягкий fallback ниже, а не отмену
    # порога: текущее состояние не ослабляется.
    if str(policy or "").strip().lower() == "operative":
        # Slice D: явная политика «только действующее» НЕ получает старый
        # материал даже синтетически (пул периода в норме и так исключает
        # текущий год). Строка текущего года остаётся; чужой год — отсев.
        for row in ordered:
            year = period_row_year(row)
            if year == current_year:
                shared = period_subject_shared(
                    query_stems, (row or {}).get("fact"),
                    explicit_year=intent.is_explicit_year)
                _mark_period_row(row, shared, PERIOD_KEEP_IN_TARGET)
                accepted.append(row)
            else:
                stats["dropped_out_of_target_year"] += 1
                _mark_period_row(row, None, PERIOD_DROP_OUT_OF_TARGET_YEAR)
        stats["kept"] = len(accepted)
        return accepted, stats
    strict = str(policy or "") != "historical"
    soft_pool: list[tuple[int, int, dict]] = []
    lexical_strict_passed = 0
    for index, row in enumerate(ordered):
        knn_row = period_row_proxy(row) == "knn"
        if knn_row and not strict:
            # Смысловой путь под `historical` порог не проходит (действующий
            # контракт next-stage §2): ближайший сосед в окне, не оракул.
            _mark_period_row(row, None, PERIOD_KEEP_VECTOR)
            stats["kept_vector"] += 1
            accepted.append(row)
            continue
        shared = period_subject_shared(
            query_stems, (row or {}).get("fact"),
            explicit_year=intent.is_explicit_year)
        _mark_period_row(row, shared, "lexical_threshold_applied")
        if shared >= PERIOD_MIN_SHARED_STEMS:
            accepted.append(row)
            lexical_strict_passed += 1
            continue
        stats["dropped_subject"] += 1
        if shared >= 1:
            soft_pool.append((shared, index, row))
    # Slice D (ARCH_DECISION 15.11.2026): словарный `query_marker` больше не
    # имеет права замещать текущий срез; паритет обычного вопроса удалён.
    # Здесь остаётся только исторический/много-летний вклад, разрешённый
    # структурным сигналом (его проверяет потребитель через
    # `period_replace_allowed`).
    #
    # TIME-03 natural memory (§3.3/§4.2): `review` — существующий L1-сигнал
    # `research`; он разрешает тот же предметный soft-fallback, что
    # `historical`. `multi_year` — прежний `historical_recall`/request-сигнал:
    # его материал тоже не должен исчезать вместе с удалённой календарной
    # квотой (доставка старого не хуже NEXT-02). Календарного выбора нет —
    # только «тот же предмет» (одна общая основа) при ≥2 строках пула.
    if (intent.is_historical or intent.is_multi_year or review) and soft_pool \
            and len(accepted) < slots \
            and lexical_strict_passed == 0 \
            and len(soft_pool) >= PERIOD_SOFT_FALLBACK_MIN_ROWS:
        # Мягкий fallback: порог §2 не дал ни одной лексической строки, но пул
        # даёт не меньше двух строк «одного предмета» с одной основой. Тогда
        # добираем лучшие из них (bounded слотами) с явным кодом причины.
        # TIME-03: год НЕ выбирает строки — порядок `-stems_shared`, затем
        # индекс пула; годичной квоты и требования «другой год» больше нет.
        # Одна слабая строка блок не собирает — контракт §2/§5 сохранён.
        soft_pool.sort(key=lambda item: (-item[0], item[1]))
        for shared, _index, row in soft_pool:
            if len(accepted) >= slots:
                break
            _mark_period_row(row, shared, PERIOD_KEEP_SOFT_FALLBACK)
            accepted.append(row)
            stats["soft_fallback"] += 1
            stats["dropped_subject"] -= 1
    # TIME-03 natural memory (§4.2): календарной квоты (`historical_quota`/
    # `multi_year_quota`) больше нет — ключи остаются нулями только для
    # совместимости существующих читателей трассы. Строки, не вошедшие из-за
    # предмета/предела, остаются в `dropped_subject` (без второго счётчика).
    stats["lexical_strict_passed"] = lexical_strict_passed
    stats["kept"] = len(accepted)
    return accepted, stats


@dataclasses.dataclass(frozen=True)
class RetrievalRequest:
    """Вход единого retrieval-контракта (§4.1 + §4.4/§7.1 MEMORY-06).

    Новые поля MEMORY-06 аддитивны и по умолчанию сохраняют прежнее
    поведение: `chat_ids=None` → ровно `(chat_id,)`; `channels=None` →
    политика по умолчанию; `purpose='reply'`; `limit/cursor` не заданы.
    """
    chat_id: int
    query: str
    trigger_ref: int | None = None
    scope: str = "auto"       # auto|time_range|participants|parent|branch
    mode: str = "auto"        # auto|history|exact|specific|episodic|thematic
    top_k: int = 12
    policy_version: str = RETRIEVAL_POLICY_VERSION
    time_from: int | None = None
    time_to: int | None = None
    participants: tuple[int, ...] = ()
    reply_depth: int = 6
    # ── MCA-22 (C5, §21 ТЗ): query planning — структурированные identity ──
    # current speaker/subject candidates переносятся в identity-prior;
    # episodes-first не нарушается (эпизоды не штрафуются prior'ом).
    # ВАЖНО (§7.1): это Telegram `user id` (uid), НЕ `nodes.id`.
    subject_entity_ids: tuple[int, ...] = ()   # subject candidates запроса (uid)
    speaker_entity_id: int | None = None       # current speaker
    reply_target_entity_id: int | None = None  # reply-адресат триггера
    quote_source_ref: str | None = None        # резолвнутый источник цитаты
    # ── MEMORY-06 (§4.4/§7.1): аддитивное расширение контракта ─────────────
    #: Разрешённый ACL-набор чатов (`None` = ровно `chat_id`). Набор приходит
    #: только от владельца прав; `retrieve` ничего не угадывает.
    chat_ids: tuple[int, ...] | None = None
    #: Ограничение каналов (`None` = политика по умолчанию).
    channels: tuple[str, ...] | None = None
    #: Назначение выборки (§4.4): reply|initiative|factcheck_context|
    #: ui_search|dossier.
    purpose: str = "reply"
    #: `cursor`/`limit` активны ТОЛЬКО при `purpose='ui_search'` (§4.4).
    cursor: str | None = None
    limit: int | None = None
    offset_bucket: str | None = None
    #: Канонические узлы C-1 (`nodes.id` ПОСЛЕ redirect-схлопывания). Это НЕ
    #: uid: смешивать `subject_entity_ids` (uid) и `subject_node_ids` запрещено
    #: (§7.1) — иначе uid случайно совпал бы с `nodes.id`.
    subject_node_ids: tuple[int, ...] = ()
    #: Детерминированная подсказка ранжированию (§7.1): intent — не фильтр.
    intent: str = "auto"
    #: Неразрешённые варианты субъекта из C-1 (для честной неоднозначности).
    ambiguous_subjects: tuple[str, ...] = ()
    #: Явный исторический/архивный запрос (только `dig_into_lore`-подобный
    #: путь). Обычные reply/initiative/context пути НИКОГДА не ставят True:
    #: `archived_fact` (вытеснено квотой) остаётся невидимым.
    include_archived: bool = False
    # ── MEMORY-06 (§7.5/MEM-06.10): каналы, которым нужен прямой путь ───────
    #: Passive direct-путь: свои прошлые слова участвуют в пуле (прежняя
    #: семантика `get_rag_facts(include_self=True)`); self-выводы всё равно
    #: отфильтровываются существующим predicate потребителя.
    include_self: bool = False
    #: Passive direct-путь: факты прямых ответов бота в пуле (прежняя
    #: семантика `get_rag_facts(include_direct_reply=True)`).
    include_direct_reply: bool = False
    #: Санкционированная проекция связей субъекта (`get_persona_card.links`)
    #: в `RetrievalResult.relations` — без собственного SQL у потребителя.
    include_relations: bool = False
    # ── MEMORY-06 (§7.5/MEM-06.10, фикс регрессии ре-ревью): субъект-канал ──
    #: Имена/алиасы субъекта для канала `subject`. Канал отбирает ФАКТЫ О
    #: СУБЪЕКТЕ по существующим колонкам `subject_ref_id`/`target_user`
    #: (устойчивый ref разрешается по `subject_entity_ids`), поэтому факт без
    #: имени в тексте («любит дронов») не теряется. Это НЕ текстовый поиск:
    #: FTS по имени человека не может служить отбором фактов о нём.
    subject_names: tuple[str, ...] = ()
    #: Порядок выдачи = собственный порядок канала (в порядке политики
    #: каналов), без типизированного переупорядочивания. Для путей, чей
    #: принятый контракт — порядок САМОГО канала: KNN/MMR direct-RAG
    #: (`MemoryManager`), `weight DESC` профиля субъекта, срез `recent`.
    #: По умолчанию False — прежний типизированный ранг (§7.1).
    preserve_channel_order: bool = False
    #: VMQ-MEM-TIME (§2, уточнение владельца 10.11.2026): ОДНО аддитивное
    #: allowlisted-поле политики временнóго охвата памяти —
    #: `operative|historical|auto` (закрытый набор `memory_contracts.
    #: MemoryScope`). Смысл запроса решает существующий L1
    #: (`L1Plan.memory_scope`); сервер нормализует мусор/отсутствие в `auto`,
    #: поэтому модель не может «понизить» явный `historical`. Словарных
    #: триггеров года здесь нет: год, как и раньше, разбирают только
    #: существующие технические парсеры диапазона — и только как дату.
    memory_scope: str = "auto"
    #: VMQ-MEM-TIME (решение 11.11.2026): аддитивный режим сборки FTS-запроса
    #: для лексического канала — прежние префиксы ПЛЮС префикс основы слова
    #: (`text_morphology.stem_word`). Нужен периодному добору: FTS5 без
    #: стемминга находил «колбас*», но не «колбасой». Default False →
    #: `build_fts_query(..., mode="prefix_or")` байт-в-байт как раньше.
    #: Списков годов/периодов не появляется — обобщаются обычные словоформы.
    lexical_stem: bool = False
    #: VMQ-MEM next stage (§1, 11.11.2026): признак ПЕРИОДНОГО добора —
    #: второго вызова того же `retrieve` из direct-RAG. Меняет ровно две
    #: вещи: (1) векторный канал идёт периодной ногой (фиксированный пул,
    #: JOIN по rowid, фильтр по годам ПОСЛЕ среза), (2) `exclude_years`
    #: применяется к SQL-окну `search_graph_facts_fts`. Default False —
    #: все прочие вызывающие байт-идентичны.
    period_fill: bool = False
    #: Годы, УЖЕ лежащие в базовом срезе (int из среза, не текст вопроса).
    #: Предикат добавляется только при непустом наборе; пустой набор
    #: `NOT IN ()` не строит. Действует только при `period_fill=True`.
    exclude_years: tuple[int, ...] = ()
    #: VMQ-MEM/TIME Slice A (15.11.2026): структурированное периодное намерение
    #: (`PeriodIntent`) — явный год или обнаруженный исторический запрос.
    #: Передаётся потребителем вместе с `period_fill`; None → `retrieve`
    #: разрешает его сам (`resolve_period_intent`). Для `explicit_year` пул
    #: периода сохраняет строки целевого года до предметного порога, а
    #: строки другого года отбрасываются с кодом причины (2026 ≠ 2023).
    period_intent: "PeriodIntent | None" = None
    #: TIME-03 natural memory (контракт 2026-11-20 §4.2): аддитивный запрет
    #: возрастного бонуса типизированного ранга. Default False сохраняет
    #: прежнее поведение прочих вызывающих; эпизодный путь direct-ответа
    #: ставит True — старый якорь не проигрывает свежему аналогу только по
    #: дате. Бонус «внутри запрошенного окна» остаётся: это период вопроса,
    #: а не свежесть. Читается через `getattr(request, ...)` для двойников.
    no_age_bias: bool = False
    #: VMQ-MEM/TIME Slice B (15.11.2026): лексический канал учитывает
    #: `time_from`/`time_to` В SQL (`search_messages_fts(since_ts/until_ts,
    #: order='time')`) вместо пост-фильтра top-N. Нужен только явному
    #: временному окну (`<Old_Episode>` по году вопроса); default False —
    #: все прочие вызывающие байт-идентичны.
    lexical_time_window: bool = False
    #: VMQ-MEM RC2 (D3, 2026-11-23): explicit-year message-anchor использует
    #: узкий content-match (без 4-значного года, годовых слов и служебных
    #: предлогов) и `order='rank'` ВНУТРИ существующего `time_from/time_to`,
    #: а не `order='time'` + LIMIT. Default False → прежний байт-идентичный
    #: вызов `search_messages_fts(order='time')` для всех прочих путей.
    lexical_window_rank: bool = False
    #: VMQ-M2 (M-04/O-04; ARCH_REUSE_CONFIRMED): запросить bounded
    #: overview-проекцию покрытия/периодов/контрпримеров/ограничений и
    #: semantic-hints в ТОМ ЖЕ `retrieve()`. Default False — прочие
    #: вызывающие получают прежний результат байт-в-байт (ноль новых чтений).
    #: Проекция ничего не выбирает и не ранжирует: кандидаты/каналы/порядок
    #: остаются прежними (semantic definitions — hint, не router).
    include_overview: bool = False
    #: VMQ-TIME-09 (19.11.2026): correlation_id хода direct-пути. Аддитивное
    #: поле для СВЯЗИ durable-событий `mca07_retrieval` с Writer-блоками того
    #: же хода (`direct_turn_selection`) по одному `trace_id`. `None` =
    #: прежнее поведение байт-в-байт: поле в событие не добавляется, отбор,
    #: ранжирование, бюджеты и лимиты не меняются.
    trace_id: str | None = None



@dataclasses.dataclass(frozen=True)
class RetrievalCandidate:
    """Кандидат: ССЫЛКА на источник (SourceRef `mca-04a` + время `mca-03`),
    НЕ копия сырья. ``preview`` — транзиентный display для reranker.

    MCA-22 (ADR-1028-6 D7, §10 ТЗ): attribution-метаданные — аддитивные
    поля с честными дефолтами (None/""), заполняются конструкторами там,
    где источник их знает. Exact subject match сильнее vector hit про
    другого человека (`apply_identity_prior`)."""
    id: str
    entity_type: str          # message|graph_fact|episode|entity|community
    entity_id: str
    chat_id: int | None = None
    source_ref_id: int | None = None
    sent_at: int = 0
    author_id: int | None = None
    score: float = 0.0
    channel: str = ""
    revision: str | None = None
    preview: str = ""
    # ── HC-TIME (B, arch contract §3.1): машинное различение времени ───────
    # Аддитивные поля с дефолтами: все существующие конструкторы/тесты
    # совместимы, `sent_at` не переопределяется, ranking/_apply_filters не
    # меняются. ``time_kind``: source|event|recorded|unknown ("" = не задан).
    # ``recorded_at`` — время записи (smart_messages.ingested_at /
    # graph_facts.created_at). ``valid_from/valid_to`` — срок действия факта.
    # ``event_start/event_end`` — окно события (эпизод/событие).
    # ``discovered_at`` — время обнаружения записи: НЕ событие.
    time_kind: str = ""
    recorded_at: int = 0
    valid_from: int = 0
    valid_to: int = 0
    event_start: int = 0
    event_end: int = 0
    discovered_at: int = 0
    # ── MCA-22 (C5): attribution-метаданные ────────────────────────────────
    subject_entity_id: int | None = None   # о ком факт (target_user/subject)
    speaker_entity_id: int | None = None   # кто сказал (speaker_author_id/user_id)
    assertion_kind: str | None = None      # v17 graph_facts / envelope
    attribution_method: str | None = None  # self_report|third_party|…
    verification: str | None = None        # provenance verification/status
    origin_type: str | None = None         # origin / provenance_channel
    contradiction_status: str | None = None   # mca_provenance_status
    provenance_backed: bool = False        # False = legacy/unverified (§9)
    # ── MEMORY-06 (§4.4): канонический узел C-1 (`nodes.id`), НЕ uid ────────
    subject_node_id: int | None = None
    # ── MEMORY-06 (§7.5, фикс потери фактов): идентичность сущности для
    #    дедупликации. `id` — ID-ПРЕДСТАВЛЕНИЕ ссылки на источник по
    #    ADR-1020-1 (`tg:<tg_message_id>` → `msg:` → `fact:`), поэтому
    #    несколько РАЗНЫХ фактов одного сообщения законно несут один `tg:`.
    #    Дедуп по `id` склеивал их в один кандидат и терял тексты (профиль
    #    субъекта отдавал меньше подтверждённых фактов, чем хранится).
    #    `dedup_id` = идентичность самой сущности (`fact:<graph_facts.id>` у
    #    факта); None → ключом остаётся `id` (сообщения/узлы/эпизоды —
    #    прежнее поведение).
    dedup_id: str | None = None
    # ── MEMORY-07 §14.3: качество сообщества (только proven попадает в выдачу) ─
    community: "CommunityMeta | None" = None


@dataclasses.dataclass(frozen=True)
class CommunityMeta:
    """Качество сообщества из сборки (§14.2/§14.3): статус и метрики.

    `status` — `proven|weak` по порогам сборщика; `label` заполнен ТОЛЬКО
    для не-нейтральной подписи: «Сообщество N» не выводится как категория.
    `size`/`strong_share`/`density`/`basis` — из `change_summary_json`
    сборки; неизвестное остаётся None/"" (не выдумывается).
    """

    community_id: str
    status: str
    size: int | None = None
    strong_share: float | None = None
    density: float | None = None
    basis: str = ""
    label: str | None = None

    def as_dict(self) -> dict:
        return {
            "community_id": self.community_id, "status": self.status,
            "size": self.size, "strong_share": self.strong_share,
            "density": self.density, "basis": self.basis,
            "label": self.label,
        }


def apply_identity_prior(candidates: list, *, subject_entity_ids: tuple = (),
                         participant_ids: tuple = (),
                         subject_node_ids: tuple = ()) -> list:
    """Identity-aware prior поверх канальных рангов (C5, §10/§21; D7).

    Детерминированный буст (не «второй движок»): exact subject match
    сильнее приблизительного vector hit про другого человека; участники
    текущего контекста получают мягкий буст; `provenance_backed=False`
    (legacy/unverified) — мягкий штраф. SourceRef/reply-match про нужного
    subject не вытесняется similarity сам по себе (truth-set K).

    MEMORY-06 (§7.1): `subject_node_ids` — канонические `nodes.id` из C-1,
    отдельный вход от uid (`subject_entity_ids`), поэтому uid, случайно
    совпавший с `nodes.id`, не даёт ложный exact-subject prior.
    Возвращает НОВЫЙ список (sorted by скор), без мутаций входа."""
    subjects = {int(s) for s in subject_entity_ids or () if s is not None}
    nodes = {int(n) for n in subject_node_ids or () if n is not None}
    participants = {int(p) for p in participant_ids or () if p is not None}
    if not subjects and not nodes and not participants:
        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def _adjusted(cand: RetrievalCandidate) -> float:
        score = float(cand.score)
        node_match = (nodes and cand.subject_node_id is not None
                      and int(cand.subject_node_id) in nodes)
        uid_match = (subjects and cand.subject_entity_id is not None
                     and int(cand.subject_entity_id) in subjects)
        if node_match or uid_match:
            score += 150.0                  # exact subject — доминирующий prior
        elif subjects and cand.subject_entity_id is not None:
            score -= 80.0                   # факт про другого человека — вниз
        elif nodes and cand.subject_node_id is not None:
            score -= 80.0                   # узел другого субъекта — вниз
        if participants and cand.speaker_entity_id is not None and \
                int(cand.speaker_entity_id) in participants:
            score += 15.0                   # source role: участник контекста
        if not cand.provenance_backed:
            score -= 10.0                   # legacy/unverified — weak hint (§9)
        return score

    return sorted(candidates, key=_adjusted, reverse=True)


@dataclasses.dataclass(frozen=True)
class RelevanceDecision:
    """Решение «использовать ли память» (MEM-06.7, §7.1).

    Ответ не обязан включать всё найденное: `use_memory=False` — допустимый
    исход («не подходящий субъект», «неоднозначно», «нет кандидатов»).
    """
    use_memory: bool
    reason_code: str = ""
    matched_subject: bool = False
    dropped: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class RetrievalResult:
    """Выход единого retrieval-контракта (§4.1 + §4.4/§7.1)."""
    status: str
    candidates: tuple[RetrievalCandidate, ...] = ()
    channels_used: tuple[str, ...] = ()
    generation_fingerprint: str | None = None
    reason_code: str | None = None
    # P0-HA ISOLATION (архконтракт §3): вне-диапазонный остаток ТОЛЬКО для
    # scope="time_range" — кандидат за краями количественной выборки. В набор
    # диапазона не входит никогда; потребитель обязан подавать его только
    # как явно помеченное дополнение (не как факты диапазона). Для прочих
    # запросов всегда пусто.
    supplementary: tuple[RetrievalCandidate, ...] = ()
    # ── MEMORY-06: эхо режима/назначения и честные гейты ───────────────────
    mode: str = ""
    purpose: str = "reply"
    chat_ids: tuple[int, ...] = ()
    #: Явная неоднозначность субъекта: варианты, без автовыбора «популярного».
    ambiguity: tuple[dict, ...] = ()
    #: Решение «память уместна/не уместна» и почему (MEM-06.7).
    relevance: RelevanceDecision | None = None
    #: MEMORY-06 (§7.5): санкционированная проекция связей субъекта (рёбра
    #: `get_persona_card.links` c основанием `legacy_ids`/
    #: `has_unsupported_sources`). Пусто = не запрашивалось/нет рёбер.
    relations: tuple[dict, ...] = ()
    #: MEMORY-06 (§7.5): полные строки graph_facts отобранных кандидатов (текст,
    #: вес, статус, v17-provenance) — канал их уже прочитал, поэтому потребителю
    #: не нужно второе чтение по id. Порядок = порядок кандидатов.
    fact_rows: tuple[dict, ...] = ()
    #: VMQ-MEM next stage (§1/§4): наблюдаемость периодного добора — только
    #: счётчики/коды, без текстов фактов: `{vector_leg, vector_rows,
    #: vector_pool, vector_pool_miss, subject_proxy}`. None — обычный запрос.
    period_fill: dict | None = None
    #: VMQ-M2 (M-04/O-04): bounded overview покрытия/периодов/контрпримеров/
    #: ограничений + semantic-hints ТОГО ЖЕ вызова (`include_overview`).
    #: None — прежний результат байт-в-байт (прочие вызывающие не затронуты).
    overview: "RetrievalOverview | None" = None


def is_history_query(query: str) -> bool:
    """Эвристика «запрос об истории» (D2): сначала эпизоды."""
    text = str(query or "").casefold()
    return any(marker in text for marker in _HISTORY_MARKERS)


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY-06 (§4.4/§7.1): расширение ЕДИНОГО retrieval-контракта, не второй
# поиск (S-1). Здесь только детерминированные политики: валидация запроса,
# выбор режима/каналов, типизированный ранг, гейты уместности. Ноль LLM.
# ═══════════════════════════════════════════════════════════════════════════

def request_reason_code(request: RetrievalRequest) -> str | None:
    """Валидация расширенного запроса. ``None`` = запрос валиден.

    §4.4: `limit`/`cursor` активны ТОЛЬКО при `purpose='ui_search'`, там же
    `1 ≤ limit ≤ 20` (иначе честный отказ, а не «подрезанная» выдача)."""
    purpose = str(request.purpose or "")
    if purpose not in RETRIEVAL_PURPOSES:
        return "invalid_purpose"
    if purpose == _mc.MemoryPurpose.UI_SEARCH.value:
        if request.limit is None:
            return None
        limit = request.limit
        if isinstance(limit, bool) or not isinstance(limit, int):
            return "invalid_limit"
        if not 1 <= int(limit) <= UI_SEARCH_MAX_LIMIT:
            return "invalid_limit"
        return None
    if request.limit is not None or request.cursor:
        return "limit_not_allowed"
    return None


def resolve_intent_mode(request: RetrievalRequest, *,
                        range_active: bool = False) -> str:
    """Детерминированный режим retrieval (§7.1/MEM-06.6), без LLM.

    Приоритет: явный `request.mode` → intent-подсказка → существующая
    эвристика `_HISTORY_MARKERS` → `auto` (смешанная выдача). Неизвестный
    intent не «угадывается»: остаётся `auto`."""
    mode = str(request.mode or "auto")
    if mode not in ("auto",) + tuple(RETRIEVAL_MODES) + ("history", "exact"):
        mode = "auto"
    if mode != "auto":
        return mode
    mapped = _INTENT_TO_MODE.get(str(request.intent or ""))
    if mapped:
        return mapped
    if range_active:
        return "auto"           # P0-HA: диапазон не разворачивается в историю
    return "episodic" if is_history_query(request.query) else "auto"


def resolve_channels(request: RetrievalRequest, mode: str) -> tuple[str, ...]:
    """Активные каналы (§4.4): `None` = политика по умолчанию.

    Режимы используют существующие ветки: `specific` — точный субъект/факт
    (эпизоды только по reply-связи), `episodic` — последовательность,
    `thematic` — широкий обзор (+ членство активной сборки, если она есть).
    Неизвестное имя канала игнорируется (не превращается в полный скан)."""
    selected = list(_DEFAULT_CHANNELS if request.channels is None
                    else request.channels)
    # §7.5 (фикс регрессии): запрос, объявивший субъекта по имени, получает
    # канал `subject` в политике ПО УМОЛЧАНИЮ. Профильные назначения читают
    # именно факты о человеке; отбор по тексту запроса терял факты без имени
    # в тексте. Явный набор каналов (`channels is not None`) действует
    # буквально — канал не добавляется.
    if request.channels is None and _subject_names(request) \
            and "subject" not in selected:
        selected.append("subject")
    if mode == "specific" and request.channels is None:
        if request.trigger_ref is None:
            selected = [c for c in selected if c != "episode"]
    if mode == "thematic" and "community" not in selected:
        selected.append("community")
    return tuple(c for c in _CHANNEL_ORDER if c in set(selected))


def effective_chat_ids(request: RetrievalRequest) -> tuple[int, ...]:
    """ACL-набор чатов запроса: `None` → ровно `chat_id` (§4.4).

    Сам `retrieve` ничего не угадывает: набор передаёт владелец прав."""
    if request.chat_ids is None:
        out = [int(request.chat_id)]
    else:
        out = []
        for value in request.chat_ids:
            try:
                chat_id = int(value)
            except (TypeError, ValueError):
                continue
            if chat_id not in out:
                out.append(chat_id)
        if not out:
            out = [int(request.chat_id)]
    return tuple(out)


def request_limit(request: RetrievalRequest) -> int:
    """Сколько кандидатов вернуть: `limit` (ui_search) либо прежний `top_k`."""
    if request.purpose == _mc.MemoryPurpose.UI_SEARCH.value \
            and request.limit is not None:
        return max(1, min(int(request.limit), UI_SEARCH_MAX_LIMIT))
    return max(1, int(request.top_k or 1))


def typed_rank_score(candidate: RetrievalCandidate, request: RetrievalRequest,
                     mode: str, *, now: int | None = None) -> float:
    """Типизированный ранг (MEM-06.4): канал + доверие источника +
    актуальность времени + режим. Никогда не заменяет канальный вес.

    TIME-03 natural memory (§4.2): при `request.no_age_bias=True` возрастного
    бонуса нет (эпизодный путь direct-ответа); бонус «внутри запрошенного
    окна» остаётся, потому что это период вопроса, а не свежесть. Default
    False сохраняет прежнее поведение прочих путей байт-в-байт."""

    score = float(candidate.score)
    if candidate.provenance_backed:
        score += _TYPED_TRUST_BONUS
    elif candidate.entity_type == "graph_fact":
        score -= _TYPED_LEGACY_PENALTY      # legacy/unverified — weak hint
    if candidate.sent_at and not getattr(request, "no_age_bias", False):
        age_days = max(0.0, (int(now if now is not None else time.time())
                             - int(candidate.sent_at)) / 86400.0)
        if age_days < 365.0:
            score += _TYPED_RECENCY_BONUS * (1.0 - age_days / 365.0)
    if (request.time_from is not None and request.time_to is not None
            and candidate.sent_at
            and int(request.time_from) <= int(candidate.sent_at)
            <= int(request.time_to)):
        score += _TYPED_RECENCY_BONUS       # внутри запрошенного окна
    if mode == "specific":
        if candidate.entity_type in ("graph_fact", "entity"):
            score += 4.0
        elif candidate.entity_type == "episode":
            score -= 6.0
    elif mode == "episodic":
        if candidate.entity_type == "episode":
            score += 6.0
        elif candidate.entity_type == "message":
            score += 2.0
    elif mode == "thematic":
        if candidate.entity_type in ("community", "entity"):
            score += 4.0
    return score


def _edge_timestamp(value) -> int | None:
    """`edges.last_updated` (SQLite TEXT UTC) → epoch seconds или None.

    Год ребра — существующая колонка `last_updated`, а не выдуманная дата.
    Невалидная/пустая строка → None (честное «времени нет»)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            stamp = int(value)
        except (TypeError, ValueError):
            return None
        return stamp if stamp > 0 else None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            moment = datetime.datetime.strptime(text, fmt).replace(
                tzinfo=datetime.timezone.utc)
            return int(moment.timestamp())
        except (ValueError, OverflowError, OSError):
            continue
    return None


def project_relations(links, limit: int = 20) -> tuple[dict, ...]:
    """MEMORY-06 (§7.5): санкционированная проекция связей субъекта.

    Вход — УЖЕ прочитанные рёбра (`get_persona_card.links`): своего поиска,
    индекса или второго хранилища здесь нет. Проекция сохраняет основание
    ребра (`legacy_ids` — edge/fact id, `has_unsupported_sources` — «источник
    не указан»), чтобы потребитель не выдавал ребро без основания за
    подтверждённое знание. Порядок входа сохраняется, размер ограничен.

    VMQ-MEM/TIME Slice B: `last_updated` существующего ребра проецируется как
    `ts`/`year` (временная ось отношений). Никаких синтезированных рёбер и
    дат: нет валидного `last_updated` → `ts=None`, год не выдумывается."""
    out: list[dict] = []
    for link in links or ():
        if len(out) >= max(1, int(limit or 1)):
            break
        if not isinstance(link, dict):
            continue
        source_name = str(link.get("source_name") or "").strip()
        target_name = str(link.get("target_name") or "").strip()
        relation = str(link.get("relation_type") or "").strip()
        if not source_name and not target_name:
            continue
        edge_id = link.get("edge_id", link.get("id"))
        fact_id = link.get("fact_id")
        origin = str(link.get("origin") or "").strip()
        legacy_ids = [str(v) for v in (edge_id, fact_id) if v not in (None, "")]
        supported = (fact_id not in (None, "") or
                     (bool(origin) and origin != "legacy_unknown"))
        ts = _edge_timestamp(link.get("last_updated") or link.get("created_at")
                             or link.get("ts"))
        year = None
        if ts is not None:
            try:
                year = datetime.datetime.fromtimestamp(
                    ts, datetime.timezone.utc).year
            except (ValueError, OSError, OverflowError):  # pragma: no cover
                year = None
        out.append({
            "text": f"{source_name} ({relation}) {target_name}".strip(),
            "edge_id": edge_id,
            "fact_id": fact_id,
            "origin": origin,
            "weight": link.get("weight"),
            "legacy_ids": legacy_ids,
            "has_unsupported_sources": not supported,
            "source_basis": "" if supported else "источник не указан",
            "ts": ts,
            "year": year,
        })
    return tuple(out)


async def _relations_projection(db, request: RetrievalRequest, limit: int
                                ) -> tuple[dict, ...]:
    """Связи субъекта через существующее чтение `get_persona_card`."""
    getter = getattr(db, "get_persona_card", None)
    name = str(request.query or "").strip()
    if not callable(getter) or not name:
        return ()
    try:
        uids = tuple(int(v) for v in (request.subject_entity_ids or ())
                     if v is not None)
    except (TypeError, ValueError):
        uids = ()
    uid = uids[0] if len(uids) == 1 else None
    try:
        if uid is not None:
            try:
                card = await getter(int(request.chat_id), name,
                                    max(1, int(limit)), int(time.time()),
                                    user_id=int(uid))
            except TypeError:
                card = await getter(int(request.chat_id), name,
                                    max(1, int(limit)), int(time.time()))
        else:
            card = await getter(int(request.chat_id), name,
                                max(1, int(limit)), int(time.time()))
    except Exception:
        logger.warning("[mca07] relations projection failed", exc_info=True)
        return ()
    return project_relations((card or {}).get("links") or (), limit)


def _subject_sets(request: RetrievalRequest) -> tuple[set, set]:
    """(uid-субъекты, node-субъекты) — раздельно, смешивать запрещено (§7.1)."""
    uids = set()
    for value in request.subject_entity_ids or ():
        try:
            uids.add(int(value))
        except (TypeError, ValueError):
            continue
    nodes = set()
    for value in request.subject_node_ids or ():
        try:
            nodes.add(int(value))
        except (TypeError, ValueError):
            continue
    return uids, nodes


def _subject_names(request: RetrievalRequest) -> tuple[str, ...]:
    """Имена/алиасы субъекта для канала `subject` (порядок, без дублей).

    Это НЕ поисковый запрос: имена нужны только для legacy-строк
    (`subject_ref_id IS NULL`), которые привязаны к человеку по
    `target_user`. Устойчивый `subject_ref_id` разрешается по uid
    (`subject_entity_ids`) — имя для него не требуется."""
    out: list[str] = []
    seen: set[str] = set()
    for value in request.subject_names or ():
        name = " ".join(str(value or "").split())
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return tuple(out)


async def _subject_fact_rows(db, request: RetrievalRequest, limit: int) -> list:
    """Факты О СУБЪЕКТЕ по существующим колонкам (`subject_ref_id`/`target_user`).

    REUSE `DatabaseService.get_user_context_facts` — ровно то чтение, которым
    пользовался прежний `get_user_context` (только `confirmed`, живой TTL,
    исключены `world_knowledge`/`bot_self_reply`, порядок `weight DESC,
    created_at DESC`). Поэтому архивные (`archived_fact`) строки сюда не
    попадают, а новых индексов/поиска/хранилищ не появляется: отбор идёт по
    субъекту, а не по совпадению текста с запросом (факт «любит дронов» о
    человеке не содержит его имени и FTS его не находит).

    VMQ-MEM-TIME (§5): при `memory_scope ∈ (historical, auto)` чтение идёт в
    историческом режиме (`scope='historical'`) — профиль строится из
    нескольких периодов с годовой квотой `limit//5` и участвующими
    `archived_fact`. При `operative` — прежнее оперативное чтение
    байт-в-байт (никакого расширения истории на текущий вопрос).

    Устойчивый ref разрешается по uid (`user_id=`), legacy-строки — по имени.
    Двойник без `user_id`-параметра → чтение по имени (совместимость).
    """
    reader = getattr(db, "get_user_context_facts", None)
    if not callable(reader):
        return []
    names = _subject_names(request)
    if not names:
        return []
    scope = ("historical"
             if _mc.normalize_memory_scope(request.memory_scope).value
             in ("historical", "auto") else "operative")
    uids, _nodes = _subject_sets(request)
    uid_list = sorted(uids)[:2]
    pairs: list[tuple[int | None, str]] = []
    for name in names[:4]:
        if uid_list:
            pairs.extend((uid, name) for uid in uid_list)
        else:
            pairs.append((None, name))
    rows: list = []
    seen: set = set()
    for uid, name in pairs[:4]:
        now = int(time.time())
        try:
            if uid is None:
                batch = await reader(int(request.chat_id), name,
                                     int(limit), now, scope=scope)
            else:
                batch = await reader(int(request.chat_id), name,
                                     int(limit), now, user_id=int(uid),
                                     scope=scope)
        except TypeError:
            # Двойник без `scope`: то же субъект-чтение по прежнему контракту
            # (расширение истории не «выдумывается» на несовместимом API).
            try:
                if uid is None:
                    batch = await reader(int(request.chat_id), name,
                                         int(limit), now)
                else:
                    batch = await reader(int(request.chat_id), name,
                                         int(limit), now, user_id=int(uid))
            except Exception:
                logger.warning("[mca07] subject channel read failed",
                               exc_info=True)
                continue
        except Exception:
            logger.warning("[mca07] subject channel read failed",
                           exc_info=True)
            continue
        for row in batch or ():
            key = _row_get(row, "id")
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(row))
    if len(pairs) > 1:
        # Несколько субъект-scope-чтений: та же колонковая упорядоченность,
        # что у самого чтения (weight DESC, created_at DESC).
        def _order_key(row):
            try:
                weight = float(_row_get(row, "weight") or 0.0)
            except (TypeError, ValueError):
                weight = 0.0
            try:
                created = int(_row_get(row, "created_at") or 0)
            except (TypeError, ValueError):
                created = 0
            return (weight, created)

        rows.sort(key=_order_key, reverse=True)
    return rows[:int(limit)]


def apply_subject_gate(candidates: list, request: RetrievalRequest
                       ) -> tuple[list, tuple[str, ...]]:
    """Гейт «не перепутан человек» (MEM-06.7).

    Если запрос явно называет субъекта, кандидат, объявивший ДРУГОГО
    субъекта, остаётся только при реальном совпадении с текстом запроса;
    иначе отбрасывается (`dropped` виден в диагностике). Кандидаты без
    объявленного субъекта не трогаются — «неизвестно» ≠ «другой человек»."""
    uids, nodes = _subject_sets(request)
    if not uids and not nodes:
        return list(candidates), ()
    tokens = set(_tokenize(request.query))
    kept: list = []
    dropped: list[str] = []
    for cand in candidates:
        subject_uid = cand.subject_entity_id
        subject_node = cand.subject_node_id
        mismatch = False
        if subject_uid is not None and uids and int(subject_uid) not in uids:
            mismatch = True
        if subject_node is not None and nodes \
                and int(subject_node) not in nodes:
            mismatch = True
        if not mismatch:
            kept.append(cand)
            continue
        overlap = bool(tokens) and bool(
            tokens & set(_tokenize(cand.preview or "")))
        if overlap:
            kept.append(cand)       # текстовое совпадение — не выкидываем
        else:
            dropped.append(cand.id)
    return kept, tuple(dropped)


def ambiguity_variants(request: RetrievalRequest) -> tuple[dict, ...]:
    """Явные варианты субъекта (§4.2/S-5): популярный не выбирается."""
    variants = []
    for raw in request.ambiguous_subjects or ():
        value = str(raw or "").strip()
        if value:
            variants.append({"variant": value, "discriminator": value})
    return tuple(variants)


def assess_relevance(candidates: list, request: RetrievalRequest, *,
                     dropped: tuple[str, ...] = (),
                     mode: str = "") -> RelevanceDecision:
    """Уместна ли память для этого хода (MEM-06.7). Детерминированно."""
    if not candidates:
        return RelevanceDecision(False, "no_candidates", False, tuple(dropped))
    uids, nodes = _subject_sets(request)
    if (uids or nodes) and not any(_candidate_matches_subject(c, uids, nodes)
                                   for c in candidates):
        return RelevanceDecision(False, "subject_mismatch", False,
                                 tuple(dropped))
    if request.ambiguous_subjects and not (uids or nodes):
        return RelevanceDecision(False, "ambiguous_subject", False,
                                 tuple(dropped))
    return RelevanceDecision(True, "relevant", bool(uids or nodes),
                             tuple(dropped))


def _candidate_matches_subject(candidate: RetrievalCandidate, uids: set,
                               nodes: set) -> bool:
    if uids and candidate.subject_entity_id is not None \
            and int(candidate.subject_entity_id) in uids:
        return True
    if nodes and candidate.subject_node_id is not None \
            and int(candidate.subject_node_id) in nodes:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED-REPLY UR-13.2: запрос памяти из ТЕМЫ + АДРЕСАТА + REPLY-PARENT.
#
# Раньше retrieval строился по последней реплике («дай цифры») — местоимения
# не разрешались. Здесь запрос собирается из смысловой темы, имени/uid
# адресата и текста сообщения, на которое отвечают (плюс цитата), а identity
# prior передаёт реальные uid/reply-связи существующего контракта
# (`RetrievalRequest.subject_entity_ids/speaker_entity_id/
# reply_target_entity_id`). Провайдер/модель эмбеддингов и индексы НЕ
# меняются (UR-13): используется тот же `retrieve()`.
# ═══════════════════════════════════════════════════════════════════════════

#: Предел ТЕКСТА ЗАПРОСА retrieval (FTS/vector query), не входа модели:
#: смысловой вход L1/L2 режет только allocator композера.
MEMORY_QUERY_MAX_CHARS = 900

#: Сколько символов reply-parent попадает в запрос (местоимения/предмет).
MEMORY_QUERY_PARENT_CHARS = 400


def build_memory_query(*, topic: str, addressee_name: str = "",
                       reply_parent_text: str = "", quote_text: str = "",
                       extra_terms=()) -> str:
    """Собрать запрос памяти из темы + адресата + reply-parent (UR-13.2).

    Приоритет частей (при переполнении ``MEMORY_QUERY_MAX_CHARS`` отпадает
    хвост менее значимой части, а не конец темы): тема → reply-parent →
    цитата → адресат → extra_terms. Тема не обрезается молча: при превышении
    сохраняются её начало и конец с явным маркером."""
    parts: list[str] = []
    topic_text = " ".join(str(topic or "").split())
    if topic_text:
        if len(topic_text) > MEMORY_QUERY_MAX_CHARS:
            head = MEMORY_QUERY_MAX_CHARS // 2
            tail = MEMORY_QUERY_MAX_CHARS - head
            topic_text = (topic_text[:head].rstrip() + " … "
                          + topic_text[-tail:].lstrip())
        parts.append(topic_text)
    parent = " ".join(str(reply_parent_text or "").split())
    if parent:
        parts.append(parent[:MEMORY_QUERY_PARENT_CHARS].strip())
    quote = " ".join(str(quote_text or "").split())
    if quote:
        parts.append(quote[:MEMORY_QUERY_PARENT_CHARS // 2].strip())
    name = " ".join(str(addressee_name or "").split())
    if name:
        parts.append(name[:120])
    for term in extra_terms or ():
        value = " ".join(str(term or "").split())
        if value:
            parts.append(value[:120])
    query = " | ".join(part for part in parts if part)
    if len(query) > MEMORY_QUERY_MAX_CHARS * 2:
        query = query[:MEMORY_QUERY_MAX_CHARS * 2]
    return query


def build_memory_request(*, chat_id: int, topic: str,
                         addressee_uid: int | None = None,
                         reply_parent_uid: int | None = None,
                         reply_parent_text: str = "", quote_text: str = "",
                         addressee_name: str = "", trigger_ref: int | None
                         = None, top_k: int = 10,
                         participants=()) -> RetrievalRequest:
    """`RetrievalRequest` для памяти с identity-prior из реальных uid/reply.

    Адресат и автор reply-parent становятся subject/participant кандидатами —
    местоимения разрешаются связями, а не догадкой по семантике (UR-13.2/
    UR-13.6: чужой человек не подставляется вместо адресата)."""
    query = build_memory_query(
        topic=topic, addressee_name=addressee_name,
        reply_parent_text=reply_parent_text, quote_text=quote_text)
    subjects: list[int] = []
    for value in (addressee_uid, reply_parent_uid):
        try:
            if value is not None:
                subjects.append(int(value))
        except (TypeError, ValueError):
            continue
    people: list[int] = []
    for value in tuple(subjects) + tuple(participants or ()):
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid not in people:
            people.append(uid)
    return RetrievalRequest(
        chat_id=int(chat_id), query=query, trigger_ref=trigger_ref,
        mode="auto", top_k=max(1, int(top_k or 1)),
        participants=tuple(people),
        subject_entity_ids=tuple(subjects),
        speaker_entity_id=(int(addressee_uid)
                           if addressee_uid is not None else None),
        reply_target_entity_id=(int(reply_parent_uid)
                                if reply_parent_uid is not None else None))


def bind_quantitative_range(request: RetrievalRequest, *, time_from,
                            time_to) -> RetrievalRequest:
    """P0-HA ISOLATION (архконтракт §3): связать RetrievalRequest с РЕАЛЬНЫМИ
    краями количественной выборки «последние N» — ``time_from`` = timestamp
    N-й (старейшей in-sample) строки, ``time_to`` = захваченный якорь (старт
    хода), НЕ ``time.time()`` повторного чтения. ``scope="time_range"``,
    ``mode="auto"`` — НЕ ``"history"`` (маркеры истории не разворачивают
    корпус на этом ходе). Секундная точность существующего контракта полей.
    Возвращает НОВЫЙ frozen-запрос; исходный не меняется. Некорректные
    границы (не int / ≤0) → запрос без связки (старые вызывающие без этой
    функции не меняются вовсе)."""
    try:
        t_from, t_to = int(time_from), int(time_to)
    except (TypeError, ValueError):
        return request
    if t_from <= 0 or t_to <= 0:
        return request
    return dataclasses.replace(request, scope="time_range", mode="auto",
                               time_from=t_from, time_to=t_to)


def _range_bound(request: RetrievalRequest) -> bool:
    """Активная количественная связка: scope=time_range и оба края заданы."""
    return (request.scope == "time_range"
            and request.time_from is not None
            and request.time_to is not None)


def _split_range(candidates: list, request: RetrievalRequest) -> tuple:
    """P0-HA ISOLATION (§3): ТОЛЬКО для scope=time_range — делит raw-кандидаты
    на (диапазонный набор, вне-диапазонный остаток). Диапазонный набор:
    та же семантика, что у ``_apply_filters`` (время + участники), плюс
    fail-closed — кандидат с ``sent_at == 0`` (неизвестное время) в набор
    диапазона НЕ входит. Остаток: только кандидаты за краями [time_from,
    time_to] — для явно помеченного supplementary-канала (никогда не факты
    диапазона). Для прочих запросов не вызывается: их поведение остаётся
    байт-в-байт в ``_apply_filters``."""
    t_from, t_to = int(request.time_from), int(request.time_to)
    participants = (set(int(p) for p in request.participants)
                    if request.participants else None)
    in_range: list = []
    outside: list = []
    for cand in candidates:
        if not cand.sent_at:
            continue                       # fail closed: время неизвестно
        if participants and cand.author_id is not None and \
                int(cand.author_id) not in participants:
            continue
        if cand.sent_at < t_from or cand.sent_at > t_to:
            outside.append(cand)
            continue
        in_range.append(cand)
    return in_range, outside


def _tokenize(query: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", str(query or "").casefold())


def tokenize_query(query: str) -> list[str]:
    """Публичный token-примитив mca-07 (REUSE для semantic-gate mca-16:
    второй retrieval-движок/индекс не создаётся)."""
    return _tokenize(query)


def _row_get(row, key, default=None):
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except Exception:
        return default


def _as_int(value) -> int:
    """HC-TIME (B): кривой/пустой ts → 0 (honest unknown, не исключение)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _time_kind_of_message(row) -> str:
    """Источник времени сообщения: timestamp/sent_at → source, иначе unknown."""
    if _as_int(_row_get(row, "timestamp")) or _as_int(_row_get(row, "sent_at")):
        return "source"
    return "unknown"


def _time_kind_of_fact(row) -> str:
    """Graph fact: message_timestamp → source; created_at → recorded."""
    if _as_int(_row_get(row, "message_timestamp")):
        return "source"
    if _as_int(_row_get(row, "created_at")):
        return "recorded"
    return "unknown"


def _canonical_enabled() -> bool:
    """`MCA_CANONICAL_ATTRIBUTION_ENABLED` (mca-22 C5; per-call, не бросает)."""
    try:
        from services import mca_gates as _g
        return _g.canonical_attribution_enabled()
    except Exception:                                     # pragma: no cover
        return True


def _channel_rank(channel: str, position: int) -> float:
    return _CHANNEL_WEIGHTS.get(channel, 0.0) - float(position)


def _channel_native_order(candidates: list, channels: tuple[str, ...]) -> list:
    """Порядок = собственный порядок канала (последовательность политики).

    Для путей, чей принятый контракт — порядок САМОГО канала (KNN/MMR
    direct-RAG, `weight DESC` профиля субъекта, `recent`-срез): каналы идут в
    порядке политики запроса, а внутри канала сохраняется его собственная
    упорядоченность. `candidate.score` канального конструктора = вес канала −
    позиция в канале, поэтому сортировка по убыванию score воспроизводит
    порядок канала без типизированных бонусов (доверие/свежесть/режим),
    которые могли бы переставить местами уже отобранный топ."""
    priority = {name: index for index, name in enumerate(channels)}
    fallback = len(priority)
    return sorted(candidates,
                  key=lambda cand: (priority.get(cand.channel, fallback),
                                    -float(cand.score)))


def _candidate_identity(cand) -> str:
    """Ключ дедупликации = идентичность СУЩНОСТИ, а не представления ссылки.

    ADR-1020-1 задаёт `id` как политику ПРЕДСТАВЛЕНИЯ ссылки на источник
    (`tg:<tg_message_id>` → `msg:` → `fact:`), а не как идентичность строки:
    несколько разных фактов, извлечённых из одного сообщения, законно несут
    один и тот же `tg:`. Дедуп по такому `id` склеивал их в один кандидат и
    терял тексты (профиль субъекта возвращал меньше подтверждённых фактов,
    чем хранится в `graph_facts`; direct-RAG терял факты одного сообщения).

    Поэтому у факта ключ — строка `graph_facts` (`dedup_id`), у прочих типов
    (сообщение/узел/эпизод/сообщество) — прежний стабильный `id`.
    Повтор ТОГО ЖЕ факта из другого канала по-прежнему склеивается: остаётся
    лучший по score канал."""
    return getattr(cand, "dedup_id", None) or cand.id


def _dedup(candidates: list) -> list:
    """Дедуп по идентичности сущности — сохраняется лучший (макс score) канал.

    Разные факты одного сообщения — РАЗНЫЕ сущности (общий только источник),
    поэтому они не склеиваются; повтор того же факта склеивается."""
    best: dict[str, RetrievalCandidate] = {}
    for cand in candidates:
        key = _candidate_identity(cand)
        current = best.get(key)
        if current is None or cand.score > current.score:
            best[key] = cand
    return list(best.values())


def _apply_filters(candidates: list, request: RetrievalRequest) -> list:
    """Фильтры по времени (событийное `sent_at`) и участникам (`author_id`).

    VMQ-MEM/TIME Slice D (15.11.2026): при ЗАДАННОМ временном окне кандидат с
    неизвестным временем (`sent_at == 0`) отклоняется fail-closed. Раньше он
    проходил оба сравнения и мог попасть в блок, посвящённый конкретному году
    (`<Old_Episode>` явного года): «время неизвестно» выдавалось за событие
    года. Для запроса без окна поведение прежнее (неизвестное время не
    отбрасывается — байт-паритет прежних путей, `test_history_isolation`)."""
    out = []
    windowed = request.time_from is not None or request.time_to is not None
    for cand in candidates:
        if windowed and not cand.sent_at:
            continue
        if request.time_from is not None and cand.sent_at and \
                cand.sent_at < int(request.time_from):
            continue
        if request.time_to is not None and cand.sent_at and \
                cand.sent_at > int(request.time_to):
            continue
        if request.participants and cand.author_id is not None and \
                int(cand.author_id) not in set(int(p) for p in request.participants):
            continue
        out.append(cand)
    return out


def _year_coverage(ordered: list, fact_rows: dict) -> dict:
    """Годы ВЫДАННОГО материала (§10): `{"2023": 2, "2026": 8}`.

    Год берётся у кандидата: у факта — из `message_timestamp`/`created_at`
    строки (реальный источник), у прочих — `sent_at`. Нет даты → кандидат
    в гистограмму не попадает (нули и «примерные» годы не выдумываются).
    """
    years: dict = {}
    for cand in ordered or ():
        ts = 0
        row = fact_rows.get(_candidate_identity(cand)) if fact_rows else None
        if isinstance(row, dict):
            for key in ("message_timestamp", "created_at", "rag_ts"):
                try:
                    ts = int(row.get(key) or 0)
                except (TypeError, ValueError):
                    ts = 0
                if ts:
                    break
        if not ts:
            try:
                ts = int(getattr(cand, "sent_at", 0) or 0)
            except (TypeError, ValueError):
                ts = 0
        if not ts:
            continue
        try:
            year = time.gmtime(ts).tm_year
        except (ValueError, OSError, OverflowError):
            continue
        if year <= 0:
            continue
        years[str(year)] = years.get(str(year), 0) + 1
    return dict(sorted(years.items()))


# ═══════════════════════════════════════════════════════════════════════════
# VMQ-M2 (M-04/M-05/O-04; ARCH_REUSE_CONFIRMED 15.11.2026): bounded overview
# ЕДИНОГО retrieval — покрытие/периоды/контрпримеры/ограничения + semantic
# hints. Контракт: evidence/m2-contract-confirmation-2026-11-15.md.
#
# Здесь нет ни второго поиска/маршрута/хранилища, ни записи, ни DDL, ни
# LLM/embedding-вызова: проекция читает УЖЕ существующие владельцы
# (`mca_episodes` EpisodeView/LongitudinalView из M1, `semantic_contracts`
# typed meanings из ONTO-A) и только складывает bounded значения. Кандидаты,
# каналы, порядок и top_k не меняются: семантическое определение — hint,
# а не отбор (§13 контракта M2).
# ═══════════════════════════════════════════════════════════════════════════

OVERVIEW_VERSION = "vmq-m2/overview/v1"
OVERVIEW_MAX_EPISODES = 200          # == mca_episodes.EPISODE_VIEW_LIMIT_MAX
OVERVIEW_MAX_PERIODS = 24
OVERVIEW_MAX_COUNTEREXAMPLES = 5
OVERVIEW_MAX_LIMITATIONS = 12
OVERVIEW_MAX_HINTS = 12
OVERVIEW_MAX_REFS = 20
OVERVIEW_TEXT_MAX = 200
OVERVIEW_MAX_HINT_ROWS = 20

#: Коды ограничений покрытия (bounded, R17-safe: без текстов/секретов).
LIMIT_REPEATED_CLAIMS = "repeated_claims_present"
LIMIT_SOURCE_INTEGRITY = "episode_source_integrity_partial"
LIMIT_STALE_EPISODES = "episodes_stale"
LIMIT_CROSS_CHAT_SCOPE = "cross_chat_acl_scope_overview_single_chat"
LIMIT_SUBJECT_AMBIGUOUS = "subject_ambiguous_overview_unfiltered"
LIMIT_SUBJECT_NAME_ONLY = "subject_identity_name_hint_only"


def _overview_text(value) -> str:
    """Bounded текст для bundle/диагностики (без служебных id-мусора)."""
    text = " ".join(str(value or "").split())
    return text[:OVERVIEW_TEXT_MAX]


def _overview_refs(refs) -> tuple[str, ...]:
    out: list[str] = []
    for ref in refs or ():
        text = str(ref or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= OVERVIEW_MAX_REFS:
            break
    return tuple(out)


@dataclasses.dataclass(frozen=True)
class RetrievalOverview:
    """Bounded overview ЕДИНОГО retrieval (M-04): покрытие, а не биография.

    `coverage` — календарные bucket'ы по времени ИСХОДНЫХ сообщений;
    пропущенный период означает «нет эпизодов», а НЕ «не было событий».
    `independent_periods` — периоды, у которых есть РАЗЛИЧНАЯ опора с
    собственными source refs: повтор одного мема/корня независимость не
    повышает. `counterexamples` отделены от support; `limitations` —
    честные коды. `semantic_hints` — типизированные определения уже
    выбранных кандидатов (hint, не отбор). `coverage['complete']` всегда
    False: границы архива не доказаны.
    """

    chat_id: int
    subject_id: str | None
    state: str
    coverage: dict
    independent_periods: tuple[str, ...]
    period_support: tuple[dict, ...]
    episode_refs: tuple[str, ...]
    episode_versions: tuple[dict, ...]
    support_source_refs: tuple[str, ...]
    independent_support_count: int
    repeated_claims: int
    counterexamples: tuple[dict, ...]
    limitations: tuple[str, ...]
    semantic_hints: tuple[dict, ...]
    derived_version: str = OVERVIEW_VERSION

    def as_dict(self) -> dict:
        """JSON-совместимая проекция (кортежи → списки): диагностика/bundle."""
        def _plain(value):
            if isinstance(value, dict):
                return {key: _plain(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [_plain(item) for item in value]
            return value

        return _plain(dataclasses.asdict(self))


def _overview_period_support(views, *, timezone: str) -> tuple[tuple[dict, ...],
                                                              tuple[str, ...]]:
    """Периоды с РАЗЛИЧНОЙ опорой (нормализованный текст) — повтор ≠ опора.

    Использует ТОЛЬКО существующие примитивы M1 (`period_year`,
    `normalize_claim_text`) и уже прочитанные `EpisodeView.claims`: своего
    вывода независимости и второго чтения здесь нет."""
    from services.mca_episodes import normalize_claim_text, period_year

    seen_norm: dict[str, str] = {}
    per_period: dict[str, dict] = {}
    ordered = sorted(views or (),
                     key=lambda v: (int(v.event_start_ts or 0), v.episode_ref))
    for view in ordered:
        period = period_year(view.event_end_ts or view.event_start_ts,
                            timezone=timezone)
        if period is None:
            continue
        period_key = str(period)
        bucket = per_period.setdefault(
            period_key, {"period": period_key, "independent": 0,
                         "repeated": 0})
        for claim in view.claims:
            norm = normalize_claim_text(str(claim.get("text") or ""))
            refs = tuple(str(r) for r in (claim.get("refs") or ()) if r)
            if not norm or not refs:
                continue
            if norm in seen_norm:
                bucket["repeated"] = int(bucket["repeated"]) + 1
                continue
            seen_norm[norm] = period_key
            bucket["independent"] = int(bucket["independent"]) + 1
    rows = tuple(per_period[key] for key in sorted(per_period))
    independent = tuple(row["period"] for row in rows if row["independent"])
    return rows, independent


def overview_from_views(*, chat_id: int, subject_id: str | None, longitudinal,
                        views, subject_ambiguous: bool = False,
                        cross_chat_scope: bool = False,
                        semantic_hints=()) -> RetrievalOverview:
    """Собрать bounded overview из УЖЕ прочитанных M1 views (чистая функция).

    Ошибки/неполнота не разворачиваются в «полное покрытие»: отсутствующее
    значение остаётся пустым/unknown, а причина попадает в `limitations`."""
    timezone = str(getattr(longitudinal, "timezone", "") or "UTC")
    coverage_in = dict(getattr(longitudinal, "coverage", {}) or {})
    present: list[dict] = []
    for block in list(coverage_in.get("present_periods") or [])[:OVERVIEW_MAX_PERIODS]:
        if not isinstance(block, dict):
            continue
        present.append({
            "period": str(block.get("period") or ""),
            "episodes": int(block.get("count") or 0),
            "episode_refs": list(_overview_refs(block.get("episode_refs"))),
        })
    coverage = {
        "period_grain": str(coverage_in.get("period_grain") or ""),
        "present_periods": present,
        "missing_periods": [
            str(value) for value in
            list(coverage_in.get("missing_periods") or [])[:OVERVIEW_MAX_PERIODS]],
        "unknown_time_episode_refs": list(_overview_refs(
            coverage_in.get("unknown_time_episode_refs"))),
        "earliest_ts": coverage_in.get("earliest_ts"),
        "latest_ts": coverage_in.get("latest_ts"),
        # Покрытие НИКОГДА не объявляется полным: границы архива не доказаны.
        "complete": False,
        "complete_reason": str(coverage_in.get("complete_reason")
                               or "archive_bounds_unknown"),
        "timezone": timezone,
    }
    period_support, independent_periods = _overview_period_support(
        views, timezone=timezone)

    episode_versions: list[dict] = []
    for view in list(views or ())[:OVERVIEW_MAX_EPISODES]:
        episode_versions.append({
            "episode_ref": str(view.episode_ref),
            "source_fingerprint": str(view.source_fingerprint or ""),
            "content_status": str(view.content_status or ""),
            "stale": bool(view.stale),
            "source_integrity": str(view.source_integrity or ""),
        })

    counterexamples: list[dict] = []
    for pair in list(getattr(longitudinal, "counterexample_pairs", ()) or ())[
            :OVERVIEW_MAX_COUNTEREXAMPLES]:
        if not isinstance(pair, dict):
            continue
        counterexamples.append({
            "left_text": _overview_text(pair.get("left_text")),
            "left_refs": list(_overview_refs(pair.get("left_refs"))),
            "right_text": _overview_text(pair.get("right_text")),
            "right_refs": list(_overview_refs(pair.get("right_refs"))),
        })

    limitations: list[str] = []
    for note in list(getattr(longitudinal, "notes", ()) or ()):
        code = str(note or "").strip()
        if code and code not in limitations:
            limitations.append(code)
    if any(row["repeated"] for row in period_support) or int(
            getattr(longitudinal, "repeated_claims", 0) or 0):
        if LIMIT_REPEATED_CLAIMS not in limitations:
            limitations.append(LIMIT_REPEATED_CLAIMS)
    if any(str(view.source_integrity or "") in ("partial", "missing")
           for view in (views or ())):
        limitations.append(LIMIT_SOURCE_INTEGRITY)
    if any(bool(view.stale) for view in (views or ())):
        limitations.append(LIMIT_STALE_EPISODES)
    if cross_chat_scope:
        # ACL-набор чатов не сливается: overview остаётся одного chat scope.
        limitations.append(LIMIT_CROSS_CHAT_SCOPE)
    if subject_ambiguous:
        limitations.append(LIMIT_SUBJECT_AMBIGUOUS)
    if subject_id is None and any(
            hint.get("kind") == "subject_identity"
            and not hint.get("entity_id") and hint.get("mention")
            for hint in semantic_hints):
        limitations.append(LIMIT_SUBJECT_NAME_ONLY)
    limitations = list(dict.fromkeys(limitations))[:OVERVIEW_MAX_LIMITATIONS]

    return RetrievalOverview(
        chat_id=int(chat_id),
        subject_id=(str(subject_id) if subject_id is not None else None),
        state=str(getattr(longitudinal, "state", "") or ""),
        coverage=coverage,
        independent_periods=independent_periods,
        period_support=period_support,
        episode_refs=_overview_refs(getattr(longitudinal, "episode_refs", ())),
        episode_versions=tuple(episode_versions),
        support_source_refs=_overview_refs(
            getattr(longitudinal, "support_source_refs", ())),
        independent_support_count=int(
            getattr(longitudinal, "independent_support_count", 0) or 0),
        repeated_claims=int(getattr(longitudinal, "repeated_claims", 0) or 0),
        counterexamples=tuple(counterexamples),
        limitations=tuple(limitations),
        semantic_hints=tuple(dict(hint) for hint in
                             list(semantic_hints or ())[:OVERVIEW_MAX_HINTS]),
    )


def _semantic_hints(request: RetrievalRequest, fact_rows=()) -> tuple[dict, ...]:
    """Typed definitions как HINTS (O-04): ничего не разрешает и не отбирает.

    Значения берутся у существующего владельца `semantic_contracts`
    (ONTO-A/B): `project_identity` — для определения субъекта запроса,
    `project_fact_meaning` — для уже прочитанных строк `graph_facts`.
    Ошибка/недоступность модуля → пусто (fail-open, базовая выдача не
    деградирует), отсутствующее значение остаётся unknown/tentative."""
    try:
        from services import semantic_contracts as _sc
    except Exception:                                     # pragma: no cover
        return ()
    hints: list[dict] = []
    uids: list[int] = []
    for value in request.subject_entity_ids or ():
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid not in uids:
            uids.append(uid)
    for uid in uids[:1]:                # один субъект: >1 — неоднозначно
        try:
            identity = _sc.project_identity(
                chat_id=request.chat_id, entity_type="user",
                participant_id=uid)
        except Exception:
            continue
        hints.append({
            "kind": "subject_identity", "entity_id": str(uid),
            "basis": str(identity.basis), "status": str(identity.status),
            "reason_code": str(identity.reason_code or ""),
            "candidates": len(identity.candidates or ()),
        })
    if not uids:
        names = _subject_names(request)
        if names:
            try:
                identity = _sc.project_identity(
                    chat_id=request.chat_id, entity_type="user",
                    mention=names[0])
                hints.append({
                    "kind": "subject_identity", "entity_id": "",
                    "mention": names[0], "basis": str(identity.basis),
                    "status": str(identity.status),
                    "reason_code": str(identity.reason_code or ""),
                    "candidates": len(identity.candidates or ()),
                })
            except Exception:
                pass
    for row in list(fact_rows or ())[:OVERVIEW_MAX_HINT_ROWS]:
        if not isinstance(row, dict):
            continue
        # Историческое multi-period чтение профиля не возвращает `chat_id`
        # (оконный SELECT), но scope чтения — ровно чат запроса: подставляем
        # фактический scope, а не выдуманное значение.
        payload = dict(row)
        if payload.get("chat_id") in (None, ""):
            payload["chat_id"] = request.chat_id
        try:
            meaning = _sc.project_fact_meaning(payload)
        except Exception:
            continue
        origin_class = meaning.origin_class
        hints.append({
            "kind": "fact_definition",
            "fact_id": meaning.fact_id,
            "entity_type": str(meaning.entity_type),
            "verification": str(meaning.verification),
            "type_status": str(meaning.type.status),
            "provenance_class": meaning.provenance_class,
            "origin_class": (origin_class.value
                             if origin_class is not None else None),
            "conflict_status": str(meaning.conflict_status),
            "degraded": list(meaning.degraded),
            "reason_code": str(meaning.reason_code or ""),
        })
        if len(hints) >= OVERVIEW_MAX_HINTS:
            break
    return tuple(hints[:OVERVIEW_MAX_HINTS])


def _overview_subject(request: RetrievalRequest) -> tuple[str | None, bool]:
    """(subject_id для scoped view, ambiguous). Имя — НЕ идентичность (§5.3).

    Фильтр возможен только по устойчивому uid; отсутствие/несколько
    кандидатов дают честное «не фильтруем» + код ограничения, а не выбор
    «популярного» субъекта."""
    if tuple(request.ambiguous_subjects or ()):
        return None, True
    uids: list[int] = []
    for value in request.subject_entity_ids or ():
        try:
            uid = int(value)
        except (TypeError, ValueError):
            continue
        if uid not in uids:
            uids.append(uid)
    if len(uids) == 1:
        return str(uids[0]), False
    return None, len(uids) > 1


async def build_retrieval_overview(db, request: RetrievalRequest, *,
                                   fact_rows=()) -> RetrievalOverview | None:
    """Bounded overview для ТОГО ЖЕ `retrieve()` (M-04). Без второго поиска.

    Читает существующие M1-проекции (`subject_longitudinal_view`,
    `list_episode_views`) в строгом chat scope и типизирует уже прочитанные
    строки фактов (`_semantic_hints`). Гейт — существующий
    `MCA_EPISODES_ENABLED`; любая ошибка → `None` (базовая выдача не
    блокируется, ложного покрытия не появляется)."""
    try:
        from services import mca_gates as _gates
        if not _gates.episodes_enabled():
            return None
        from services.mca_episodes import (
            list_episode_views, subject_longitudinal_view,
        )
        chat_id = int(request.chat_id)
        subject_id, subject_ambiguous = _overview_subject(request)
        longitudinal = await subject_longitudinal_view(
            db, chat_id, subject_id=subject_id, limit=OVERVIEW_MAX_EPISODES)
        views = await list_episode_views(
            db, chat_id, limit=OVERVIEW_MAX_EPISODES)
        return overview_from_views(
            chat_id=chat_id, subject_id=subject_id,
            longitudinal=longitudinal, views=views,
            subject_ambiguous=subject_ambiguous,
            cross_chat_scope=len(effective_chat_ids(request)) > 1,
            semantic_hints=_semantic_hints(request, fact_rows))
    except Exception:
        logger.warning("[mca07] retrieval overview failed", exc_info=True)
        return None


def overview_bundle_slots(overview) -> dict:
    """Bounded overview → текстовые слоты (ЕДИНЫЙ формат для bundle и tool).

    Один источник формы: и `EvidenceBundle` живого пути, и envelope
    person-overview инструмента читают отсюда — второго форматтера нет.
    Тексты bounded (`OVERVIEW_TEXT_MAX`), внутренние id не раскрываются.
    ``overview is None`` → ``{}`` (паритет прежних потребителей)."""
    if overview is None:
        return {}
    try:
        coverage_lines: list[str] = []
        coverage = getattr(overview, "coverage", None) or {}
        for block in coverage.get("present_periods") or ():
            coverage_lines.append(
                f"{block.get('period')}: эпизодов "
                f"{int(block.get('episodes') or 0)}")
        earliest = coverage.get("earliest_ts")
        latest = coverage.get("latest_ts")
        if earliest and latest:
            coverage_lines.append(
                "границы: " + summary_date(earliest) + " — "
                + summary_date(latest))
        missing = [str(value) for value in coverage.get("missing_periods")
                   or ()]
        if missing:
            coverage_lines.append("пропущены периоды: " + ", ".join(missing))
        counterexample_lines = [
            _overview_text(pair.get("left_text")) + " ↔ "
            + _overview_text(pair.get("right_text"))
            for pair in (getattr(overview, "counterexamples", ()) or ())]
        hint_lines = []
        for hint in (getattr(overview, "semantic_hints", ()) or ()):
            if hint.get("kind") == "subject_identity":
                hint_lines.append(
                    "субъект: " + str(hint.get("basis"))
                    + "/" + str(hint.get("status")))
            elif hint.get("kind") == "fact_definition":
                hint_lines.append(
                    "определение: " + str(hint.get("verification")))
        return {
            "coverage": tuple(_overview_text(line) for line
                              in coverage_lines[:OVERVIEW_MAX_PERIODS + 2]),
            "independent_periods": tuple(
                getattr(overview, "independent_periods", ()) or ()),
            "counterexamples": tuple(counterexample_lines[
                :OVERVIEW_MAX_COUNTEREXAMPLES]),
            "limitations": tuple(
                getattr(overview, "limitations", ()) or ()),
            "episode_refs": tuple(
                getattr(overview, "episode_refs", ()) or ()),
            "semantic_hints": tuple(_overview_text(line) for line
                                    in hint_lines[:OVERVIEW_MAX_HINTS]),
        }
    except Exception:                                     # pragma: no cover
        logger.warning("[mca07] overview slots shaping failed", exc_info=True)
        return {}


def apply_overview_to_bundle(bundle, overview) -> "EvidenceBundle | None":
    """Наполнить ЕДИНЫЙ `EvidenceBundle` overview-слотами M-04 (чистая).

    Возвращает НОВЫЙ frozen-bundle через `dataclasses.replace`: второго
    bundle не создаётся, `context_version`/`schema_version` и все прочие
    слоты не меняются. `overview is None` → исходный bundle (паритет).
    Тексты bounded и без служебных метрик; внутренние id не раскрываются
    (только ссылки эпизодов, как и остальные refs bundle)."""
    if bundle is None or overview is None:
        return bundle
    slots = overview_bundle_slots(overview)
    if not slots:
        return bundle
    return dataclasses.replace(
        bundle,
        coverage=slots["coverage"],
        independent_periods=slots["independent_periods"],
        counterexamples=slots["counterexamples"],
        limitations=slots["limitations"],
        episode_refs=slots["episode_refs"],
        semantic_hints=slots["semantic_hints"],
    )


async def retrieve(db, memory, request: RetrievalRequest) -> RetrievalResult:
    """Единая точка retrieval-запроса, ОБОРАЧИВАЮЩАЯ существующие каналы.

    Комбинация: exact (quoted-FTS) + subject (ФАКТЫ О СУБЪЕКТЕ по его
    колонкам `subject_ref_id`/`target_user` — не текстовый поиск) +
    lexical/FTS (сообщения + граф-факты) +
    vector (`MemoryManager.retrieve_fact_candidates`) + reply-граф
    (`thread_chain`) + эпизоды (`lore_stories`) + entity (`nodes` по
    `subject_node_ids` C-1, bounded по id) + community (членство активной
    сборки C-6, если она есть). Для исторических/эпизодических запросов —
    эпизоды ПЕРВЫМИ. Кандидаты несут SourceRef-ссылку/время.
    Никогда не бросает: ошибка канала → честная деградация (пропуск канала);
    ошибка всех → ``status='empty'``/``reason_code='retrieval_empty'``.

    MEMORY-06 (§4.4/§7.1): `chat_ids` — ACL-набор от владельца прав;
    `purpose='ui_search'` получает `limit` (1…20) и НЕ предполагает reranker
    (LLM на поиск запрещён); `subject_entity_ids` (uid) и `subject_node_ids`
    (`nodes.id`) раздельны; `include_archived=True` — только явный
    исторический путь (`dig_into_lore`), обычные пути архив не видят."""
    from services.mca_retrieval_context import (  # self (lazy — циклы)
        RETRIEVAL_EMPTY as _EMPTY,
    )
    from services.summary_memory import build_fts_query
    from services.canonical_context import resolve_item_id

    chat_ids = effective_chat_ids(request)
    invalid = request_reason_code(request)
    if invalid:
        emit_stage_event("retrieval", "invalid", reason_code=invalid,
                         chat_id=request.chat_id,
                         trace_id=request.trace_id)
        return RetrievalResult(status=RETRIEVAL_ERROR, reason_code=invalid,
                               purpose=str(request.purpose or ""),
                               mode=str(request.mode or "auto"),
                               chat_ids=chat_ids)

    keywords = _tokenize(request.query)
    # VMQ-MEM-TIME (решение 11.11.2026): `lexical_stem` — аддитивный режим
    # сборки FTS-запроса (прежние префиксы + префикс основы слова). Включён
    # только у периодного добора; все прочие потребители `retrieve` получают
    # байт-идентичную прежнюю формулу (`prefix_or`).
    match = build_fts_query(
        keywords,
        mode=("prefix_or_stem" if request.lexical_stem else "prefix_or")
    ) if keywords else ""
    # VMQ-NEXT-02 (§A, 13.11.2026): у ПЕРИОДНОГО FTS-вызова (граф-факты с
    # годовым окном) источник кандидатов обязан быть согласован с §2. Токен,
    # чья основа (§2: `len(stem_word(token)) >= 4`) отбрасывается предметным
    # фильтром, не должен сам формировать пул: иначе `"к"*`/`"в"*`/`"что"*`
    # выбирают весь LIMIT, а потребитель отклоняет 100 % строк. Фильтр
    # применяется ТОЛЬКО здесь; глобальный `build_fts_query` и все прочие
    # вызовы `retrieve` сохраняют прежнюю формулу байт-в-байт. Длинные
    # содержательные токены и их prefix/stem варианты остаются прежними.
    now = int(time.time())
    # P0-HA ISOLATION (§3): при активной количественной связке mode НЕ
    # повышается до "history" по _HISTORY_MARKERS (список маркеров не меняет)
    # — корпусный FTS/эпизоды не разворачиваются поверх диапазона. Запрос без
    # количественной границы эти ветки не касается (H24).
    range_active = _range_bound(request)
    mode = resolve_intent_mode(request, range_active=range_active)
    allowed_channels = resolve_channels(request, mode)
    limit = request_limit(request)
    fetch_k = max(1, limit)
    # VMQ-MEM-TIME (§2/§10): политика охвата — закрытое значение из запроса
    # (L1 → RetrievalRequest), мусор/отсутствие → `auto`. Словарных
    # триггеров года нет: здесь только валидация уже принятого решения.
    memory_scope = _mc.normalize_memory_scope(request.memory_scope)
    policy = memory_scope.value
    # VMQ-MEM/TIME Slice A (15.11.2026): структурированное периодное намерение
    # (явный год / исторический запрос) — из запроса, иначе детерминированно
    # из вопроса и политики. Применяется ТОЛЬКО к периодному добору.
    period_intent = None
    if request.period_fill:
        period_intent = request.period_intent or resolve_period_intent(
            request.query, memory_scope=policy,
            request_intent=request.intent, request_mode=request.mode)
    # RC4 (A2/D4): short-stem variant только для периодного content-FTS;
    # explicit-year дополнительно исключает годовые/служебные токены.
    period_match = ""
    period_keywords: list = []
    if request.period_fill:
        period_keywords = _period_fts_keywords(
            keywords,
            explicit_year=bool(period_intent
                               and period_intent.is_explicit_year))
        period_match = build_fts_query(
            period_keywords,
            mode=("prefix_or_stem_short" if request.lexical_stem
                  else "prefix_or")
        ) if period_keywords else ""
    #: Счётчики причин исключения (§10): policy→status→expired→relevance→
    #: budget. Только числа, без текстов фактов; уходят в durable-событие.
    excluded: dict = {}
    channels: list[str] = []
    raw: list[RetrievalCandidate] = []
    #: §7.5 MEMORY-06: полные строки graph_facts по кандидату — канал их уже
    #: прочитал, поэтому потребитель (direct-RAG/context) не делает второе
    #: чтение ради текста/веса/provenance.
    fact_rows: dict[str, dict] = {}
    #: VMQ-MEM next stage (§1): идентичности строк ПЕРИОДНОЙ векторной ноги —
    #: они идут первыми в обходе и не проходят порог §2 (смысловой путь).
    period_vector_ids: set = set()
    #: VMQ-NEXT-05 (13.11.2026): раздельные длительности уже выполняемых
    #: периодных вызовов (`knn_ms`/`fts_ms`) и коды отсутствия измерения.
    #: Накопитель общий для каналов: FTS-ветка пишет `fts_ms`, векторная —
    #: `knn_ms`; отсутствие вызова остаётся отсутствием (не 0 ms).
    period_stats: dict = {}
    exact_used = False      # L-MCA07-3: reason_code `exact_match_used`

    def _allow(name: str) -> bool:
        return name in allowed_channels

    # ── эпизоды (для истории/эпизодики — ПЕРВЫМИ) ───────────────────────────
    if _allow("episode") and (mode in ("history", "episodic")
                              or request.channels is not None):
        for chat_id in chat_ids:
            try:
                episodes = await _episode_candidates(
                    db, dataclasses.replace(request, chat_id=chat_id,
                                            top_k=fetch_k), keywords)
                if episodes:
                    raw.extend(episodes)
                    channels.append("episode")
            except Exception:
                logger.warning("[mca07] episode channel failed", exc_info=True)

    # ── recent (§7.5 MEMORY-06): bounded-срез последних сообщений явно
    #     запрошенных участников. Включается ТОЛЬКО при `scope='participants'`
    #     и явном канале `recent` — существующее чтение
    #     `get_recent_messages` (+ фильтр участников), без второго поиска.
    #     Нужен тем purpose, где источник — собственная речь человека
    #     (профиль речи), а не совпадение по ключевым словам.
    _participants = {int(p) for p in request.participants or ()
                     if p is not None}
    if _allow("recent") and request.scope == "participants" \
            and _participants:
        for chat_id in chat_ids:
            try:
                rows = await db.get_recent_messages(
                    chat_id, max(1, int(fetch_k) * _RECENT_SCAN_FACTOR))
                picked = []
                eligible = []
                for pos, row in enumerate(rows or ()):
                    author = _row_get(row, "user_id")
                    if author is None or int(author) not in _participants:
                        continue
                    if not str(_row_get(row, "text") or "").strip():
                        continue
                    eligible.append((pos, row))
                # Последние (самые свежие в окне) сообщения участника —
                # прежняя семантика среза собственной речи.
                for pos, row in eligible[-max(1, int(fetch_k)):]:
                    picked.append(_message_candidate(
                        row, "recent", pos, resolve_item_id))
                if picked:
                    raw.extend(picked)
                    channels.append("recent")
            except Exception:
                logger.warning("[mca07] recent channel failed", exc_info=True)

    # ── exact (quoted-фраза всегда доступна) ────────────────────────────────
    phrases = re.findall(r'"([^"]{2,})"', request.query)
    if _allow("exact"):
        for chat_id in chat_ids:
            for phrase in phrases[:4]:
                try:
                    exact_match = ('"' + phrase.replace('"', "")
                                   .replace("*", "") + '"')
                    rows = await db.search_messages_fts(
                        chat_id, exact_match, fetch_k)
                    for pos, row in enumerate(rows or []):
                        raw.append(_message_candidate(
                            row, "exact", pos, resolve_item_id))
                    if rows:
                        channels.append("exact")
                        exact_used = True
                except Exception:
                    logger.warning("[mca07] exact channel failed",
                                   exc_info=True)

    # ── subject (§7.5, фикс регрессии): ФАКТЫ О СУБЪЕКТЕ ────────────────────
    #     Отбор по существующим колонкам субъекта (`subject_ref_id` по uid /
    #     legacy `target_user`), а НЕ по совпадению текста с запросом: факт
    #     «работает программистом» о человеке имени не содержит, поэтому FTS
    #     его не находит, хотя он именно о нём.
    if _allow("subject") and _subject_names(request):
        scope_uids = sorted(_subject_sets(request)[0])
        for chat_id in chat_ids:
            try:
                rows = await _subject_fact_rows(
                    db, dataclasses.replace(request, chat_id=chat_id), fetch_k)
                for pos, row in enumerate(rows or ()):
                    cand = _fact_candidate(row, "subject", pos, resolve_item_id)
                    if cand.subject_entity_id is None and len(scope_uids) == 1 \
                            and not (isinstance(row, dict)
                                     and row.get("unattributed")):
                        # Строка отобрана В scope объявленного субъекта
                        # (`subject_ref_id` по uid либо legacy
                        # `target_user` = имя), т.е. факт — о нём. Честная
                        # атрибуция нужна гейтам/уместности и identity-prior,
                        # а не новому ранжированию. VMQ-MEM-TIME (§5):
                        # добор «без привязки» к субъекту НЕ атрибутируется —
                        # иначе общий контекст чата выдавался бы за сведения
                        # о человеке.
                        cand = dataclasses.replace(
                            cand, subject_entity_id=scope_uids[0])
                    raw.append(cand)
                    fact_rows[_candidate_identity(cand)] = dict(row)
                if rows:
                    channels.append("subject")
            except Exception:
                logger.warning("[mca07] subject channel failed", exc_info=True)

    # ── entity (§4.4): канонический узел C-1 по `nodes.id`, bounded ─────────
    if _allow("entity") and request.subject_node_ids:
        for chat_id in chat_ids:
            try:
                rows = await _entity_rows(db, chat_id,
                                          request.subject_node_ids)
                for pos, row in enumerate(rows or []):
                    raw.append(_entity_candidate(row, chat_id, pos))
                if rows:
                    channels.append("entity")
            except Exception:
                logger.warning("[mca07] entity channel failed", exc_info=True)

    # ── lexical/FTS: сообщения + граф-факты ─────────────────────────────────
    # VMQ-NEXT-02 (§A, 13.11.2026): периодный FTS граф-фактов использует
    # match, из которого удалены токены, заведомо отбрасываемые §2. Канал
    # сообщений сохраняет прежний match: §2 судит факты, а сообщения не
    # входят в периодный пул. Если §2-совместимых токенов нет вовсе —
    # честная деградация: лексическая нога периода не выполняется,
    # векторная продолжает работу; пустое/неограниченное FTS-выражение не
    # строится и основной retrieval не прекращается.
    if request.period_fill:
        period_stats["fts_words_total"] = len(keywords)
        period_stats["fts_words_kept"] = len(period_keywords)
        period_stats["fts_words_dropped"] = max(
            0, len(keywords) - len(period_keywords))
    if _allow("lexical") and match:
        # VMQ-MEM/TIME Slice B: явное временное окно (год вопроса) уходит в
        # SQL существующего чтения, а не режет уже полученный top-N. `order=
        # "time"` — bounded план по `idx_smart_messages_chat_ts` (дефект 3);
        # default False → прежний байт-идентичный вызов.
        # RC2 (D3): explicit-year message-anchor использует узкий
        # content-match + `order="rank"` ВНУТРИ окна, а не time-срез.
        _fts_window: dict = {}
        message_match = match
        rank_window = False
        if request.lexical_time_window and request.time_from is not None \
                and request.time_to is not None:
            _fts_window = {"since_ts": int(request.time_from),
                           "until_ts": int(request.time_to),
                           "order": "time"}
            if getattr(request, "lexical_window_rank", False):
                rank_window = True
                message_match = _explicit_year_message_match(keywords)
                _fts_window = {}
        for chat_id in chat_ids:
            try:
                if message_match:
                    if rank_window:
                        rows = await _ranked_message_rows(
                            db, chat_id, message_match, max(1, fetch_k * 2),
                            int(request.time_from), int(request.time_to),
                            fetch_k)
                    else:
                        try:
                            rows = await db.search_messages_fts(
                                chat_id, message_match, max(1, fetch_k * 2),
                                **_fts_window)
                        except TypeError:
                            # Двойник без kw-окна: прежний вызов, окно режет
                            # существующий пост-фильтр (не второй поиск).
                            rows = await db.search_messages_fts(
                                chat_id, message_match, max(1, fetch_k * 2))
                else:
                    rows = []
                for pos, row in enumerate(rows or []):
                    raw.append(_message_candidate(row, "lexical", pos,
                                                  resolve_item_id))
                if rows:
                    channels.append("lexical")
            except Exception:
                logger.warning("[mca07] lexical messages channel failed",
                               exc_info=True)
            facts_match = period_match if request.period_fill else match
            if not facts_match:
                period_stats["fts_ms_reason"] = "fts_match_empty"
                continue
            try:
                # VMQ-NEXT-05: длительность ИМЕННО периодного FTS-вызова
                # (граф-факты с годовым окном), а не сообщений; остальные
                # вызовы того же SQL не измеряются.
                fts_clock = (time.perf_counter() if request.period_fill
                             else None)
                rows = await db.search_graph_facts_fts(
                    chat_id, facts_match, max(1, fetch_k * 2), now,
                    include_direct_reply=bool(request.include_direct_reply),
                    include_archived=bool(request.include_archived),
                    include_self=bool(request.include_self),
                    exclude_years=_exclude_years_of(request))
                if fts_clock is not None:
                    _period_add_ms(period_stats, "fts_ms", fts_clock)
                for pos, row in enumerate(rows or []):
                    cand = _fact_candidate(row, "lexical", pos,
                                           resolve_item_id)
                    raw.append(cand)
                    fact_rows[_candidate_identity(cand)] = _period_marked(
                        row, request, "lexical")
                if rows:
                    channels.append("lexical")
            except TypeError:
                # Совместимость с двойниками без include_archived: обычный
                # (не архивный) вызов — архив в них и так не виден.
                try:
                    fts_clock = (time.perf_counter() if request.period_fill
                                 else None)
                    rows = await db.search_graph_facts_fts(
                        chat_id, facts_match, max(1, fetch_k * 2), now)
                    if fts_clock is not None:
                        _period_add_ms(period_stats, "fts_ms", fts_clock)
                    for pos, row in enumerate(rows or []):
                        cand = _fact_candidate(row, "lexical", pos,
                                               resolve_item_id)
                        raw.append(cand)
                        fact_rows[_candidate_identity(cand)] = _period_marked(
                            row, request, "lexical")
                    if rows:
                        channels.append("lexical")
                except Exception:
                    if request.period_fill and "fts_ms" not in period_stats:
                        period_stats["fts_ms_reason"] = "fts_error"
                    logger.warning("[mca07] lexical facts channel failed",
                                   exc_info=True)
            except Exception:
                if request.period_fill and "fts_ms" not in period_stats:
                    period_stats["fts_ms_reason"] = "fts_error"
                logger.warning("[mca07] lexical facts channel failed",
                               exc_info=True)

    # ── vector (REUSE MemoryManager; единый retrieval-контракт) ─────────────
    if _allow("vector") and memory is not None:
        if request.period_fill:
            # VMQ-MEM next stage (§1): периодная нога — НЕ
            # `_search_graph_facts`/MMR/staged k×4. Там срез 2026-доминирован
            # и фильтр после MMR старое не достаёт. Здесь один float-MATCH с
            # фиксированным k, JOIN по rowid к graph_facts и окно по годам
            # ПОСЛЕ среза. Функция живёт рядом с `_vec_candidates`; её нет у
            # двойников → честная деградация на лексику с кодом причины.
            rows = []
            reader = getattr(memory, "period_fill_candidates", None)
            # VMQ-MEM/TIME Slice A (15.11.2026): векторная нога участвует
            # только после допуска существующей контроль-плоскости. Отказ
            # (`insufficient`/`incompatible`) не маскируется лексикой —
            # наружу уходит честный `vector_unavailable` + причина.
            admission = await _period_vector_admission(db, memory)
            period_stats["vector_admission"] = admission
            if not callable(reader):
                period_stats["vector_leg"] = "unsupported_memory"
                period_stats["knn_ms_reason"] = "vector_leg_unsupported"
            elif admission.get("admitted") is False:
                reason = str(admission.get("reason_code")
                             or admission.get("state") or "vector_unavailable")
                period_stats["vector_leg"] = reason
                period_stats["vector_unavailable_reason"] = reason
                period_stats["knn_ms_reason"] = "vector_leg_unavailable"
            else:
                for chat_id in chat_ids:
                    knn_clock = time.perf_counter()
                    try:
                        rows = await reader(
                            chat_id, request.query, k=fetch_k,
                            exclude_years=tuple(request.exclude_years or ()),
                            include_direct_reply=bool(
                                request.include_direct_reply),
                            include_self=bool(request.include_self),
                            include_archived=bool(
                                request.include_archived),
                            stats=period_stats)
                        # VMQ-NEXT-05: измерение выполнено — длительность
                        # уже случившегося периодного KNN-вызова (embed+KNN).
                        _period_add_ms(period_stats, "knn_ms", knn_clock)
                    except TypeError:
                        period_stats["vector_leg"] = "unsupported_memory"
                        period_stats["knn_ms_reason"] = "vector_leg_unsupported"
                        rows = []
                    except Exception:
                        period_stats["vector_leg"] = "error"
                        period_stats["knn_ms_reason"] = "vector_leg_error"
                        rows = []
                    break
            unavailable = _vector_unavailable_reason(period_stats)
            if unavailable:
                # Код отказа уже лежит в `vector_leg` (совместимость прежних
                # читателей); `vector_unavailable` — явная метка честной
                # недоступности ноги, а не доказанного результата.
                period_stats["vector_unavailable"] = 1
                period_stats["vector_unavailable_reason"] = unavailable
            for pos, row in enumerate(rows or ()):
                if not isinstance(row, dict):
                    continue
                cand = _fact_meta_candidate(row, pos, resolve_item_id)
                raw.append(cand)
                marked = _period_marked(row, request, "vector")
                fact_rows[_candidate_identity(cand)] = marked
                period_vector_ids.add(_candidate_identity(cand))
            if rows:
                channels.append("vector")
        else:
            for chat_id in chat_ids:
                try:
                    try:
                        facts = await memory.retrieve_fact_candidates(
                            chat_id, request.query, limit=fetch_k,
                            include_archived=bool(request.include_archived),
                            include_self=bool(request.include_self),
                            include_direct_reply=bool(
                                request.include_direct_reply),
                            policy=policy, stats=excluded)
                    except TypeError:
                        # Двойник без политики/счётчиков: те же прежние флаги
                        # доставки сохраняются (иначе live/direct/self-пул молча
                        # сузился бы на несовместимом API).
                        try:
                            facts = await memory.retrieve_fact_candidates(
                                chat_id, request.query, limit=fetch_k,
                                include_archived=bool(request.include_archived),
                                include_self=bool(request.include_self),
                                include_direct_reply=bool(
                                    request.include_direct_reply))
                        except TypeError:
                            # Совместимость: реализации без archival-параметра —
                            # обычная (live) выдача, как раньше.
                            facts = await memory.retrieve_fact_candidates(
                                chat_id, request.query, limit=fetch_k)
                    for pos, row in enumerate(facts or []):
                        cand = _fact_meta_candidate(row, pos, resolve_item_id)
                        raw.append(cand)
                        if isinstance(row, dict):
                            fact_rows[_candidate_identity(cand)] = dict(row)
                    if facts:
                        channels.append("vector")
                except Exception:
                    logger.warning("[mca07] vector channel failed",
                                   exc_info=True)

    # ── community (§4.4/C-6): членство активной сборки, если она есть ───────
    if _allow("community") and mode == "thematic":
        for chat_id in chat_ids:
            try:
                rows = await _community_candidates(db, chat_id, keywords,
                                                   fetch_k)
                for pos, row in enumerate(rows or []):
                    raw.append(_community_candidate(row, chat_id, pos))
                if rows:
                    channels.append("community")
            except Exception:
                logger.warning("[mca07] community channel failed",
                               exc_info=True)

    # ── reply-граф (REUSE thread_chain; scope parent/branch/auto-trigger) ────
    if _allow("reply_graph") and request.trigger_ref is not None \
            and request.scope in ("auto", "parent", "branch") \
            and request.reply_depth > 0:
        try:
            from services.thread_chain import collect_thread_chain
            chain = await collect_thread_chain(
                db, request.chat_id, int(request.trigger_ref),
                request.reply_depth)
            for pos, item in enumerate(chain or []):
                raw.append(_chain_candidate(item, pos))
            if chain:
                channels.append("reply_graph")
        except Exception:
            logger.warning("[mca07] reply-graph channel failed", exc_info=True)

    # P0-HA ISOLATION (§3): только для scope=time_range — деление на
    # диапазонный набор (fail-closed для sent_at==0) и вне-диапазонный
    # остаток (явно помеченное дополнение). Прочие запросы — прежний
    # _apply_filters байт-в-байт.
    supplementary: list = []
    if range_active:
        raw, supplementary = _split_range(raw, request)
    else:
        raw = _apply_filters(raw, request)
    # MEMORY-06 (§7.1): «не перепутан человек» — кандидат про другого
    # объявленного субъекта выпадает, если не совпал и по тексту запроса.
    deduped = _dedup(raw)
    deduped, subject_dropped = apply_subject_gate(deduped, request)
    # VMQ-MEM/TIME Slice A (15.11.2026): при ЯВНОМ годе пул периода сохраняет
    # строки целевого года первыми. Строка другого года и строка без
    # известного времени отбрасываются с кодом причины — 2026-строка не
    # выдаёт себя за 2023 и не занимает периодные слоты. Прочие запросы
    # (включая current-state) этот фильтр не касается вовсе.
    period_in_target = 0
    period_out_of_target = 0
    period_unknown_year = 0
    if period_intent is not None and period_intent.is_explicit_year:
        years = set(int(year) for year in period_intent.years)
        kept: list = []
        for cand in deduped:
            year = _candidate_year(cand)
            if year is None:
                period_unknown_year += 1
                continue
            if year not in years:
                period_out_of_target += 1
                continue
            kept.append(cand)
            period_in_target += 1
        deduped = kept
    # Порядок: история/эпизодика — эпизоды первыми, далее типизированный ранг
    # (канал + доверие + актуальность + режим), а не одна similarity.
    # P0-HA ISOLATION: при активной связке history_bias не применяется
    # (эпизоды не ставятся первыми поверх корпуса).
    def _sort_key(cand: RetrievalCandidate):
        history_bias = (1 if (mode in ("history", "episodic")
                              and cand.channel == "episode"
                              and not range_active) else 0)
        return (history_bias, typed_rank_score(cand, request, mode, now=now))
    if request.preserve_channel_order:
        # §7.5/§4.4: путь, чей принятый контракт — порядок самого канала
        # (KNN/MMR direct-RAG, weight DESC профиля, recent-срез), получает
        # канальный порядок без типизированных бонусов: иначе свежесть/доверие
        # переставляли бы уже отобранный топ и меняли состав при малом top_k.
        ordered = _channel_native_order(deduped, allowed_channels)
    else:
        ordered = sorted(deduped, key=_sort_key, reverse=True)
    # MCA-22 (C5, D7): identity-prior — exact subject match про нужного
    # человека сильнее приблизительного vector hit про другого (§10/§21).
    # Гейт canonical OFF → prior не применяется (паритет baseline).
    # При `preserve_channel_order` порядок канала неприкосновенен.
    uids, nodes = _subject_sets(request)
    prior_uids = tuple(sorted(uids))
    prior_nodes = tuple(sorted(nodes))
    if not request.preserve_channel_order and _canonical_enabled() and (
            prior_uids or prior_nodes or request.participants):
        non_eps = [c for c in ordered if c.channel != "episode"]
        eps = [c for c in ordered if c.channel == "episode"]
        non_eps = apply_identity_prior(
            non_eps, subject_entity_ids=prior_uids,
            participant_ids=request.participants,
            subject_node_ids=prior_nodes)
        ordered = (eps + non_eps) if mode in ("history", "episodic") else \
            apply_identity_prior(
                ordered, subject_entity_ids=prior_uids,
                participant_ids=request.participants,
                subject_node_ids=prior_nodes)
    # VMQ-MEM next stage (§1): обход периодного пула — СНАЧАЛА строки
    # векторной ноги (они и есть смысловой путь), затем лексические: иначе
    # слоты `limit//5` забирает лексика, и смысловой добор не доходит.
    if request.period_fill and period_vector_ids:
        ordered = ([cand for cand in ordered
                    if _candidate_identity(cand) in period_vector_ids]
                   + [cand for cand in ordered
                      if _candidate_identity(cand) not in period_vector_ids])
    # Ограничение выдачи (эпизоды-первыми не вытесняются при истории, но и не
    # занимают срез целиком — см. `_HISTORY_EPISODE_SLICE_DIV`).
    cut_before = len(ordered)
    if len(ordered) > limit:
        if not request.preserve_channel_order and mode in ("history",
                                                           "episodic"):
            eps = [c for c in ordered if c.channel == "episode"]
            rest = [c for c in ordered if c.channel != "episode"]
            if not rest:
                ordered = eps[:limit]
            else:
                # Эпизоды — первыми (их порядок не меняется), но не более
                # `1/_HISTORY_EPISODE_SLICE_DIV` среза: остаток гарантирован
                # кандидатам других каналов, иначе более сильный корпусный хит
                # не доходит до потребителя вообще (дефект 1 измерения 2.58.179).
                eps_cap = max(1, limit // _HISTORY_EPISODE_SLICE_DIV)
                head = eps[:eps_cap]
                tail = rest[:limit - len(head)]
                if len(head) + len(tail) < limit:
                    # `rest` короче остатка — добираем эпизодами (не теряем срез)
                    head = eps[:limit - len(tail)]
                ordered = head + tail
        else:
            ordered = ordered[:limit]

    generation_fingerprint = None
    try:
        active = await db.get_active_embedding_generation("graph_facts_vec")
        if active is not None:
            generation_fingerprint = active.get("fingerprint")
    except Exception:
        generation_fingerprint = None

    relevance = assess_relevance(ordered, request, dropped=subject_dropped,
                                 mode=mode)
    ambiguity = ambiguity_variants(request)
    # §7.5 MEMORY-06: санкционированная проекция связей субъекта — только по
    # явному запросу (`include_relations`), из существующего чтения; поиск не
    # дублируется и в ранжирование кандидатов не вмешивается.
    relations = (await _relations_projection(db, request, limit)
                 if request.include_relations else ())
    # ── VMQ-M2 (M-04/O-04): bounded overview ТОГО ЖЕ вызова. Никакого
    # второго маршрута: кандидаты/каналы/порядок уже определены выше, а
    # проекция только читает существующие episode-views/typed meanings.
    # Include False (default) → ноль новых чтений (паритет прежних путей).
    delivered_fact_rows = tuple(
        fact_rows[_candidate_identity(cand)] for cand in ordered
        if _candidate_identity(cand) in fact_rows)
    overview = None
    if request.include_overview:
        overview = await build_retrieval_overview(
            db, request, fact_rows=delivered_fact_rows)
    status = RETRIEVAL_OK if ordered else _EMPTY
    reason = None if ordered else "retrieval_empty"
    if mode in ("history", "episodic") and ordered and any(
            c.channel == "episode" for c in ordered):
        reason = "episodes_used"
    if ordered and not relevance.use_memory and relevance.reason_code:
        reason = relevance.reason_code      # «память не уместна» — честно
    if exact_used:
        # L-MCA07-3: точная фраза/имя/дата всегда доступна — отдельный код.
        emit_stage_event("retrieval", "success",
                         reason_code="exact_match_used",
                         chat_id=request.chat_id)
    # VMQ-MEM-TIME (§10, уточнение владельца 10.11.2026): durable-событие
    # несёт покрытие ВЫДАННОГО материала по годам и причины исключения
    # кандидатов (квота/статус/давность/релевантность/бюджет). Bounded,
    # R17-safe: только политика, годы и числа — ни текстов фактов, ни id
    # сообщений. Фиктивных значений нет: пустая выдача → пустые словари.
    years = _year_coverage(ordered, fact_rows)
    excluded["relevance"] = (excluded.get("relevance") or 0) + len(
        subject_dropped or ())
    excluded["budget"] = (excluded.get("budget") or 0) + max(
        0, cut_before - len(ordered))
    # VMQ-MEM next stage (§4): наблюдаемость периодного добора — только
    # счётчики и `subject_proxy` (как строка вошла), без текстов фактов.
    period_usage = None
    if request.period_fill:
        period_usage = {
            "vector_leg": str(period_stats.get("vector_leg")
                              or ("ok" if period_vector_ids else "no_rows")),
            "vector_rows": len(period_vector_ids),
            "vector_pool_miss": int(bool(
                period_stats.get("vector_pool_miss"))),
            "subject_proxy": _subject_proxy_counts(ordered, fact_rows,
                                                   period_vector_ids),
            # VMQ-NEXT-02 (§A): сколько токенов запроса отброшено из
            # периодного FTS как §2-несовместимые (основа <4). Bounded числа,
            # без текстов запроса/фактов.
            "fts_words_total": int(period_stats.get("fts_words_total") or 0),
            "fts_words_kept": int(period_stats.get("fts_words_kept") or 0),
            "fts_words_dropped": int(
                period_stats.get("fts_words_dropped") or 0),
            # VMQ-NEXT-05 (§2, 13.11.2026): раздельные длительности УЖЕ
            # выполненных периодных вызовов. Поля аддитивны для legacy
            # readers; отсутствие измерения — `None` + код причины, никогда
            # не выдуманный `0 ms`, и на отбор/status/fallback не влияет.
            "knn_ms": _period_ms_of(period_stats, "knn_ms"),
            "fts_ms": _period_ms_of(period_stats, "fts_ms"),
            # VMQ-MEM/TIME Slice A (15.11.2026): структурированное периодное
            # намерение и честная недоступность векторной ноги — только коды и
            # числа. `vector_leg`/`vector_rows` остаются прежними ключами для
            # существующих читателей.
            "period_intent": (period_intent.as_dict()
                              if period_intent is not None else None),
            "rows_in_target": int(period_in_target),
            "dropped_out_of_target_year": int(period_out_of_target),
            "dropped_unknown_year": int(period_unknown_year),
            "vector_unavailable": int(
                bool(period_stats.get("vector_unavailable"))),
            "vector_unavailable_reason": (
                str(period_stats.get("vector_unavailable_reason") or "") or None),
            "vector_admission": (dict(period_stats["vector_admission"])
                                 if isinstance(period_stats.get(
                                     "vector_admission"), dict) else None),
        }
        for _field in ("knn_ms", "fts_ms"):
            if period_usage[_field] is None:
                period_usage[_field + "_reason"] = str(
                    period_stats.get(_field + "_reason") or "not_executed")
    usage_json = {"policy": policy, "years": years,
                  "excluded": {key: int(value) for key, value
                               in sorted(excluded.items()) if int(value)}}
    if period_usage is not None:
        usage_json["period_fill"] = period_usage
        if period_usage.get("subject_proxy"):
            usage_json["subject_proxy"] = period_usage["subject_proxy"]
    # VMQ-M2 (M-04): наблюдаемость overview — только коды/числа (R17): ни
    # текстов утверждений, ни эпизодных refs. Путь default-off не меняется.
    if overview is not None:
        usage_json["overview"] = {
            "state": str(overview.state),
            "periods": len(overview.coverage.get("present_periods") or ()),
            "independent_periods": len(overview.independent_periods),
            "counterexamples": len(overview.counterexamples),
            "limits": len(overview.limitations),
            "hints": len(overview.semantic_hints),
        }
    emit_stage_event(
        "retrieval", "success" if ordered else "silent",
        reason_code=reason, chat_id=request.chat_id,
        trace_id=request.trace_id,
        entity_ids=[c.id for c in ordered[:20]],
        message_id=request.trigger_ref,
        usage_json=usage_json)
    return RetrievalResult(
        status=status, candidates=tuple(ordered),
        channels_used=tuple(sorted(set(channels), key=_CHANNEL_ORDER.index)),
        generation_fingerprint=generation_fingerprint, reason_code=reason,
        supplementary=tuple(_dedup(supplementary)),
        mode=mode, purpose=str(request.purpose or "reply"),
        chat_ids=chat_ids, ambiguity=ambiguity, relevance=relevance,
        relations=relations,
        fact_rows=delivered_fact_rows,
        period_fill=period_usage,
        overview=overview)


def _message_candidate(row, channel: str, position: int, resolve_item_id):
    message_id = _row_get(row, "id")
    tg_id = _row_get(row, "tg_message_id")
    item_id = resolve_item_id(tg_message_id=tg_id, message_id=message_id)
    return RetrievalCandidate(
        id=item_id or f"msg:{message_id}",
        entity_type="message", entity_id=str(message_id),
        chat_id=_row_get(row, "chat_id"),
        sent_at=int(_row_get(row, "timestamp")
                    or _row_get(row, "sent_at")
                    or _row_get(row, "rag_ts") or 0),
        author_id=_row_get(row, "user_id"),
        score=_channel_rank(channel, position), channel=channel,
        revision=(f"tg:{tg_id}" if tg_id is not None else None),
        preview=str(_row_get(row, "text") or ""),
        # HC-TIME (B): timestamp/sent_at — время источника; ingested_at
        # (если канал его отдаёт) — дата записи; отсутствие → 0/unknown.
        time_kind=_time_kind_of_message(row),
        recorded_at=_as_int(_row_get(row, "ingested_at")),
        # C5 (D7): speaker сообщения = author; subject-поле честно пусто
        # (subject сообщения — уровень ClaimEnvelope, не re-ranking).
        speaker_entity_id=_row_get(row, "user_id"),
        origin_type=str(_row_get(row, "source_kind") or "") or None)


def _fact_candidate(row, channel: str, position: int, resolve_item_id):
    fact_id = _row_get(row, "id")
    tg_id = _row_get(row, "tg_message_id")
    item_id = resolve_item_id(tg_message_id=tg_id, fact_id=fact_id)
    subject = _row_get(row, "target_user")
    speaker = _row_get(row, "speaker_author_id")
    subject_ref = _row_get(row, "subject_ref_id")
    origin = str(_row_get(row, "origin") or "")
    try:
        subject_id = int(subject) if subject not in (None, "") else None
    except (TypeError, ValueError):
        subject_id = None
    return RetrievalCandidate(
        id=item_id or f"fact:{fact_id}",
        entity_type="graph_fact", entity_id=str(fact_id),
        chat_id=_row_get(row, "chat_id"),
        source_ref_id=(int(subject_ref)
                       if subject_ref not in (None, "") else None),
        sent_at=int(_row_get(row, "rag_ts")
                    or _row_get(row, "message_timestamp")
                    or _row_get(row, "created_at") or 0),
        author_id=speaker if speaker is not None else subject_id,
        score=_channel_rank(channel, position), channel=channel,
        # §7.5 (фикс потери фактов): дедуп по строке факта, а не по `tg:`-
        # представлению источника — иначе 4 факта одного сообщения → 1.
        dedup_id=(f"fact:{fact_id}" if fact_id not in (None, "") else None),
        preview=str(_row_get(row, "fact") or ""),
        # HC-TIME (B): message_timestamp ≠ created_at. `sent_at` выше
        # сохранён как COALESCE(rag_ts…) — поле не переопределяется; здесь
        # добавлено машинное различие курсора времени и окна действия.
        time_kind=_time_kind_of_fact(row),
        recorded_at=_as_int(_row_get(row, "created_at")),
        valid_from=_as_int(_row_get(row, "valid_from")),
        valid_to=_as_int(_row_get(row, "valid_to")),
        # C5 (D7): subject/speaker/provenance — из v17-колонок (§10):
        # факт без subject_ref_id = legacy/unverified → weak hint.
        subject_entity_id=subject_id,
        speaker_entity_id=speaker,
        assertion_kind=(str(_row_get(row, "assertion_kind") or "") or None),
        attribution_method=(
            str(_row_get(row, "attribution_method") or "") or None),
        origin_type=(origin or str(_row_get(row, "provenance_channel")
                                   or "") or None),
        provenance_backed=(subject_ref not in (None, "")))


def _period_fts_keywords(keywords: list[str], *,
                         explicit_year: bool = False) -> list[str]:
    """§2-совместимые токены ПЕРИОДНОГО FTS-запроса (VMQ-NEXT-02 §A).

    §2 (`_rag_subject_stems`) считает только основы длиной `>= 4`. Токен,
    чья основа короче, всё равно будет отброшен потребителем, поэтому он не
    должен формировать периодный пул. Зеркалим §2 на той же морфологии
    (`text_morphology.stem_word`), не меняя глобальный `build_fts_query`:
    длинные содержательные токены и их prefix/stem варианты сохраняются.
    `short_stem_word`-токены (`шиз`) сохраняются, если обычная основа короче
    4; explicit-year (RC4/D4) дополнительно исключает годовые слова и
    служебные предлоги. Пустой результат — честная деградация, а не
    неограниченное FTS-выражение.
    """
    from services.text_morphology import stem_word
    out: list = []
    for word in keywords or ():
        token = str(word or "").casefold()
        if not token:
            continue
        if explicit_year and (
                _YEAR_IN_QUERY_RE.fullmatch(token)
                or token in _YEAR_WORD_TOKENS
                or token in _MESSAGE_WINDOW_STOPWORDS):
            continue
        if len(stem_word(token)) >= 4:
            out.append(token)
    return out


def _explicit_year_message_keywords(keywords: list[str]) -> list[str]:
    """Узкий content-match explicit-year message-поиска (RC2/D3).

    Год уже применён структурным `time_from/time_to`; 4-значный год,
    годовые слова и служебные предлоги/местоимения не должны формировать
    FTS-пул иначе `order='time'`/шумный rank выбирает нерелевантные
    сообщения. Списка тем здесь нет — только служебные токены.
    """
    out: list[str] = []
    for word in keywords or ():
        token = str(word or "").casefold()
        if not token:
            continue
        if _YEAR_IN_QUERY_RE.fullmatch(token):
            continue
        if token in _YEAR_WORD_TOKENS:
            continue
        if token in _MESSAGE_WINDOW_STOPWORDS:
            continue
        if token not in out:
            out.append(token)
    return out


_MESSAGE_WINDOW_STOPWORDS = frozenset({
    "а", "без", "бы", "в", "вам", "вас", "вот", "все", "всё", "вы", "где",
    "да", "даже", "для", "до", "его", "ее", "её", "ей", "если", "есть",
    "же", "за", "и", "из", "или", "им", "их", "к", "как", "какая", "какие",
    "какой", "ко", "когда", "кто", "ли", "между", "меня", "мне", "мы",
    "на", "над", "нас", "не", "него", "нее", "ней", "ни", "ним", "них",
    "но", "о", "об", "он", "она", "они", "от", "по", "под", "при", "про",
    "с", "себе", "со", "так", "там", "тебе", "то", "тогда", "тот", "тут",
    "у", "чего", "чем", "через", "что", "чтобы", "эта", "эти", "это",
    "этот", "я",
})
_YEAR_WORD_TOKENS = frozenset({
    "год", "года", "годе", "годов", "годом", "году", "годы", "годах",
})


def _explicit_year_message_match(keywords: list[str]) -> str:
    """Узкий selective FTS-match explicit-year message-поиска (RC2/D3).

    Требует co-occurrence минимум двух content-основ (OR по парам AND), чтобы
    короткие сообщения с одним общим словом не забивали rank. При одной
    основе — обычный prefix. Списка тем нет; только служебные токены
    отфильтрованы `_explicit_year_message_keywords`.
    """
    tokens = _explicit_year_message_keywords(keywords)
    if not tokens:
        return ""
    from services.text_morphology import stem_word
    terms: list[str] = []
    for token in tokens:
        stem = str(stem_word(token) or token)
        term = stem if len(stem) >= 4 else token
        term = term.replace('"', "").replace("*", "")
        if term and term not in terms:
            terms.append(term)
    terms = terms[:8]
    if not terms:
        return ""
    if len(terms) == 1:
        return f'"{terms[0]}"*'
    pairs: list[str] = []
    for i, first in enumerate(terms):
        for second in terms[i + 1:]:
            pairs.append(f'("{first}"* AND "{second}"*)')
    return " OR ".join(pairs)


def _window_chunks(start: int, end: int, parts: int = 4) -> list[tuple[int, int]]:
    """Bounded disjoint time chunks для explicit-year rank (RC2)."""
    start, end = int(start), int(end)
    if end <= start:
        return [(start, end)]
    span = end - start + 1
    parts = max(1, min(int(parts), 8))
    step = max(1, span // parts)
    chunks: list[tuple[int, int]] = []
    cursor = start
    for _ in range(parts):
        chunk_end = min(end, cursor + step - 1)
        if chunk_end < cursor:
            break
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + 1
        if cursor > end:
            break
    if not chunks or chunks[-1][1] < end:
        chunks.append((max(start, chunks[-1][1] + 1 if chunks else start), end))
    return chunks


async def _ranked_message_rows(db, chat_id: int, match_query: str, limit: int,
                               since_ts: int, until_ts: int,
                               fetch_k: int) -> list:
    """Bounded candidate chunks + FTS rank only for candidate rowids (RC2).

    Полный `ORDER BY rank` по году дорог; здесь time-index candidate cap по
    каждому bounded chunk, затем rank только для этих rowid. Это честный
    sampling: `candidate_cap` ограничивает пул, финальный порядок — rank.
    """
    reader = getattr(db, "search_messages_fts_ranked_window", None)
    if not callable(reader):
        return await db.search_messages_fts(
            int(chat_id), match_query, max(1, int(limit)),
            since_ts=int(since_ts), until_ts=int(until_ts), order="rank")
    cap = max(64, int(fetch_k) * 8)
    rows: list = []
    for chunk_start, chunk_end in _window_chunks(since_ts, until_ts):
        try:
            chunk = await reader(
                int(chat_id), match_query, max(1, int(limit)),
                chunk_start, chunk_end, candidate_cap=cap)
        except TypeError:
            chunk = await reader(
                int(chat_id), match_query, max(1, int(limit)),
                chunk_start, chunk_end)
        rows.extend(chunk or ())
    seen: set = set()
    unique: list = []
    for row in rows:
        key = _row_get(row, "id")
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    if any(_row_get(row, "_fts_rank", None) is not None
           for row in unique):
        unique.sort(key=lambda row: (
            float(_row_get(row, "_fts_rank", 0.0) or 0.0),
            int(_row_get(row, "id", 0) or 0)))
    return unique[:max(1, int(limit))]


def _exclude_years_of(request: RetrievalRequest):
    """Годы SQL-окна FTS: только у периодного добора, иначе None (прежний SQL)."""
    if not request.period_fill:
        return None
    years: list = []
    for year in (request.exclude_years or ()):
        try:
            years.append(int(year))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(set(years))) or None


async def _period_vector_admission(db, memory) -> dict:
    """Read-only состояние допуска индекс-поколения для периодной векторной
    ноги (VMQ-MEM/TIME Slice A).

    Единый контракт — существующий `embedding_control_plane.resolve_index_compat`
    (никакого второго решения и никаких записей): `state=compatible`
    (`class=admitted|instant`) — нога допущена (`admitted=True`,
    `proven=True`); `insufficient`/`incompatible` — нога НЕ участвует, наружу
    уходит честный `vector_unavailable` + `reason_code`; `no_generation`/
    `source_empty` — доказательства совместимости нет ни в одну сторону,
    поэтому решает прежний гейт A06 внутри `MemoryManager` (`admitted=None`,
    `proven=False`). Исключение контроль-плоскости — отказ (`admission_error`),
    а не молчаливое участие. Никогда не бросает."""
    try:
        from services import embedding_control_plane as _ecp
    except Exception:                                     # pragma: no cover
        return {"state": "unavailable", "class": "", "reason_code":
                "admission_unavailable", "action": "", "admitted": False,
                "proven": False}
    current_fp = None
    fingerprint = getattr(memory, "_identity_fingerprint", None)
    if callable(fingerprint):
        try:
            current_fp = fingerprint()
        except Exception:                                 # pragma: no cover
            current_fp = None
    dims = getattr(memory, "_vec_dim", None)
    try:
        compat = await _ecp.resolve_index_compat(
            db, "graph_facts_vec", current_fp=current_fp,
            current_dims=dims)
    except Exception:
        logger.warning("[mca07] period vector admission failed", exc_info=True)
        return {"state": "unavailable", "class": "", "reason_code":
                "admission_error", "action": "", "admitted": False,
                "proven": False}
    state = str(compat.get("state") or "")
    reason = str(compat.get("reason_code") or "")
    admission = {
        "state": state,
        "class": str(compat.get("class") or ""),
        "reason_code": reason,
        "action": str(compat.get("action") or ""),
    }
    if state == str(_ecp.STATE_COMPATIBLE):
        admission.update({"admitted": True, "proven": True})
    elif state in (str(_ecp.STATE_NO_GENERATION), str(_ecp.STATE_SOURCE_EMPTY)):
        # Доказательства совместимости нет ни в одну сторону: действует
        # прежний гейт A06 внутри MemoryManager (не строже основного KNN).
        admission.update({"admitted": None, "proven": False})
    else:
        admission.update({"admitted": False, "proven": False,
                          "reason_code": reason or state or "insufficient"})
    return admission


def _vector_unavailable_reason(stats: dict) -> str | None:
    """Код причины, если периодная векторная нога не дала результата по
    состоянию (не «ok»/пусто/неподдерживаемая память). Иначе None."""
    code = str(stats.get("vector_leg") or "")
    if code in ("", "ok", "no_rows", "unsupported_memory"):
        return None
    return code


def _period_add_ms(stats: dict, field: str, started: float) -> None:
    """Аддитивно накопить длительность уже выполненного периодного вызова.

    `field` — `knn_ms`/`fts_ms`; значение пишется только когда вызов реально
    исполнялся. Отсутствующий вызов сюда не попадает вовсе (его код причины
    ставит вызывающая ветка), поэтому «нет измерения» никогда не становится
    нулём. Неотрицательное число, мс с тысячными."""
    elapsed = max(0.0, (time.perf_counter() - started) * 1000.0)
    previous = stats.get(field)
    base = float(previous) if isinstance(previous, (int, float)) else 0.0
    stats[field] = round(base + elapsed, 3)


def _period_ms_of(stats: dict, field: str):
    """Измеренная длительность периодного канала либо `None` (не 0)."""
    value = stats.get(field)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, float(value))
    return None


def _period_marked(row, request: RetrievalRequest, source: str) -> dict:
    """Полная строка факта − пометка канала периодного добора (`period_source`).

    `period_fill` — не только «другой период»: потребителю нужно знать, как
    строка вошла. Векторная строка (`vector`) — ближайший сосед в окне, а НЕ
    доказанный ответ (под выключенным реранком входит с `subject_proxy=knn`);
    лексическая (`lexical`) — совпадение текста. Пометка аддитивна и не
    попадает ни в один рендер."""
    try:
        marked = dict(row)
    except (TypeError, ValueError):
        # Не-mapping (совместимый двойник отдал объект) — прежнее поведение
        # потребителя: строка без полей, ничего не выдумываем.
        marked = {"raw": row}
    if request.period_fill:
        marked["period_source"] = source
    return marked


def _subject_proxy_counts(ordered, fact_rows, period_vector_ids) -> dict:
    """Счётчики «как вошла строка» для периодного пула: только числа/коды."""
    counts: dict = {}
    for cand in ordered or ():
        identity = _candidate_identity(cand)
        if identity not in fact_rows:
            continue
        row = fact_rows[identity]
        if not isinstance(row, dict):
            continue
        if identity in period_vector_ids:
            key = "knn"
        elif row.get("period_source"):
            key = str(row.get("period_source"))
        else:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _fact_meta_candidate(row, position: int, resolve_item_id):
    """Кандидат из `MemoryManager.retrieve_fact_candidates` (dict with id)."""
    fact_id = row.get("id")
    item_id = row.get("item_id") or resolve_item_id(
        tg_message_id=row.get("tg_message_id"), fact_id=fact_id)
    subject_ref = row.get("subject_ref_id")
    try:
        subject_id = (int(row["target_user"])
                      if row.get("target_user") not in (None, "") else None)
    except (TypeError, ValueError, KeyError):
        subject_id = None
    return RetrievalCandidate(
        id=item_id or f"fact:{fact_id}",
        entity_type="graph_fact", entity_id=str(fact_id),
        chat_id=row.get("chat_id"),
        source_ref_id=(int(subject_ref)
                       if subject_ref not in (None, "") else None),
        sent_at=int(row.get("rag_ts") or 0),
        score=_channel_rank("vector", position), channel="vector",
        # §7.5 (фикс потери фактов): эта же идентичность строки факта, что и у
        # канальных конструкторов, — повтор ТОГО ЖЕ факта из другого канала
        # склеивается, разные факты одного сообщения — нет.
        dedup_id=(f"fact:{fact_id}" if fact_id not in (None, "") else None),
        preview=str(row.get("fact") or ""),
        # HC-TIME (B): строка vector-ноги несёт message_timestamp/created_at
        # (и, где доступно, готовый time_origin) — дата события не выдаётся
        # за дату записи. rag_ts/ранг не меняются.
        time_kind=(str(row.get("time_origin") or "")
                   or _time_kind_of_fact(row)),
        recorded_at=_as_int(row.get("created_at")),
        valid_from=_as_int(row.get("valid_from")),
        valid_to=_as_int(row.get("valid_to")),
        subject_entity_id=subject_id,
        speaker_entity_id=row.get("speaker_author_id"),
        assertion_kind=row.get("assertion_kind"),
        attribution_method=row.get("attribution_method"),
        origin_type=(str(row.get("origin") or "") or None),
        provenance_backed=(subject_ref not in (None, "")))


def _chain_candidate(item, position: int):
    item_id = getattr(item, "item_id", "") or ""
    is_bot = bool(getattr(item, "is_bot", False))
    ts = int(getattr(item, "ts", 0) or 0)
    return RetrievalCandidate(
        id=item_id or f"reply:{position}",
        entity_type="message",
        entity_id=item_id.split(":", 1)[1] if ":" in item_id else item_id,
        sent_at=ts,
        author_id=getattr(item, "uid", None),
        score=_channel_rank("reply_graph", position), channel="reply_graph",
        preview=str(getattr(item, "text", "") or ""),
        # HC-TIME (B): ChainItem.ts — время хода (ledger/сообщение); нет → unknown.
        time_kind=("source" if ts else "unknown"))


# ── MEMORY-06 (§4.4): entity/community каналы — bounded чтение по ID/членству,
#    НЕ второй поиск: никаких новых индексов, embedding-моделей и ранжирования.
async def _entity_rows(db, chat_id: int, node_ids) -> list:
    """Узлы канонического субъекта C-1 по id (`nodes.id`), bounded.

    REUSE существующего чтения БД (`DatabaseService.get_nodes_by_ids`):
    диапазон `id IN (...)` + активный redirect `member → canonical`.
    Двойник без такого метода → честно пусто (канал пропускается)."""
    reader = getattr(db, "get_nodes_by_ids", None)
    if not callable(reader):
        return []
    ids: list[int] = []
    for value in node_ids or ():
        try:
            node = int(value)
        except (TypeError, ValueError):
            continue
        if node and node not in ids:
            ids.append(node)
    if not ids:
        return []
    return list(await reader(chat_id, ids) or [])


def _entity_candidate(row, chat_id: int, position: int) -> RetrievalCandidate:
    """Кандидат-сущность (`ent:<chat>:<node>` — канонический id §4.3)."""
    canonical = _row_get(row, "canonical_node_id") or _row_get(row, "id")
    try:
        node_id = int(canonical)
    except (TypeError, ValueError):
        node_id = 0
    return RetrievalCandidate(
        id=f"ent:{chat_id}:{node_id}",
        entity_type="entity", entity_id=str(node_id), chat_id=chat_id,
        score=_channel_rank("entity", position), channel="entity",
        preview=str(_row_get(row, "entity_name") or ""),
        subject_node_id=(node_id or None),
        provenance_backed=True)


async def _active_community_quality(db, chat_id: int
                                   ) -> tuple[str | None, dict[str, dict]]:
    """Активная сборка → `(build_id, {community_id: качество})` ТОЛЬКО proven.

    §14.2/§14.3: статус сообщества — данные сборки (`change_summary_json`),
    а не константа чтения. Нормативный ключ — `proven_community_ids`;
    `proven_communities` добавляет метрики. Сборка без ключа (например,
    собранная до quality contract) трактуется как «proven нет» — WEAK
    исключается из выдачи целиком, поэтому неизвестный статус не выдаётся
    за доказанный.
    """
    proven_value = _mc.CommunityStatus.PROVEN.value
    raw_db = getattr(db, "db", None)
    execute = getattr(raw_db, "execute", None)
    if not callable(execute):
        return None, {}
    cursor = await execute(
        "SELECT build_id, change_summary_json FROM mca_community_builds "
        "WHERE chat_id = ? AND status = 'active' "
        "ORDER BY started_at DESC, build_id DESC LIMIT 1", (int(chat_id),))
    row = await cursor.fetchone()
    if row is None:
        return None, {}
    build_id = str(row["build_id"])
    try:
        summary = json.loads(row["change_summary_json"] or "{}")
    except (TypeError, ValueError):
        summary = {}
    if not isinstance(summary, dict):
        return build_id, {}
    proven: dict[str, dict] = {}
    for item in summary.get("proven_communities") or ():
        if not isinstance(item, dict):
            continue
        community_id = str(item.get("community_id") or "").strip()
        if not community_id or item.get("status") != proven_value:
            continue
        proven[community_id] = dict(item)
    for community_id in summary.get("proven_community_ids") or ():
        key = str(community_id or "").strip()
        if key:
            proven.setdefault(key, {"community_id": key,
                                    "status": proven_value})
    return build_id, proven


async def _community_candidates(db, chat_id: int, keywords: list[str],
                                limit: int) -> list:
    """Членство ТОЛЬКО proven-сообществ действующей сборки (C-6 §6, §14.3).

    * гейт `MCA_MEMORY_COMMUNITIES_ENABLED` резолвится здесь (per chat:
      env AND каталоговый ключ) → OFF даёт пусто, не трогая таблицы;
    * членство читается исключительно через реестр сборок по
      `status='active'` того же чата: `building`/`superseded`/`failed` не
      читаются вообще, поэтому вытесненная (superseded) или недопубликованная
      сборка не может попасть в выдачу;
    * WEAK-сообщества исключены ИЗ КАНАЛА ЦЕЛИКОМ (не демоция): канал
      существует ради тематической группировки, а участники слабой пары уже
      достижимы обычными каналами. Proven-набор — из
      `change_summary_json` активной сборки, поэтому это данные, а не
      константа;
    * нет таблиц (`v44` не применён) или нет active-сборки → честно пусто:
      сообщество не выдумывается из раскладки витрины.

    Поле `member_weight` строк — ВНУТРЕННИЙ вес ребра кластера (вклад
    подтверждённых/сомнительных/legacy/cooccurrence связей узла в это
    сообщество), а НЕ нормированный 0..1-скор и не ранжирующий балл канала.
    Канал его не перенормирует и в `score` не подмешивает.
    """
    from services import mca_gates
    if not await mca_gates.memory_communities_enabled(int(chat_id)):
        return []
    raw_db = getattr(db, "db", None)
    execute = getattr(raw_db, "execute", None)
    if not callable(execute):
        return []
    cursor = await execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' "
        "AND name IN ('mca_community_members', 'mca_community_builds')")
    present = await cursor.fetchone()
    if present is None or int(present[0]) != 2:
        return []
    build_id, proven = await _active_community_quality(db, chat_id)
    if build_id is None or not proven:
        return []
    placeholders = ",".join("?" for _ in sorted(proven))
    cursor = await execute(
        "SELECT m.community_id, m.node_id, m.member_weight, n.entity_name "
        "FROM mca_community_members m "
        "JOIN nodes n ON n.id = m.node_id "
        "WHERE m.chat_id = ? AND m.build_id = ? "
        f"AND m.community_id IN ({placeholders}) "
        "ORDER BY m.community_id, m.node_id LIMIT ?",
        (int(chat_id), build_id, *sorted(proven),
         max(1, int(limit) * 4)))
    rows = []
    for row in await cursor.fetchall():
        item = dict(row)
        quality = proven.get(str(item.get("community_id"))) or {}
        item["status"] = quality.get("status")
        item["size"] = quality.get("size")
        item["strong_share"] = quality.get("strong_share")
        item["density"] = quality.get("density")
        item["basis"] = quality.get("basis") or ""
        item["label"] = quality.get("label")
        rows.append(item)
    tokens = set(keywords)
    if not tokens:
        return rows[:limit]
    matched = [row for row in rows
               if any(tok in str(row.get("entity_name") or "").casefold()
                      for tok in tokens)]
    return (matched or [])[:limit]


def _community_candidate(row, chat_id: int, position: int,
                         *, status: str | None = None) -> RetrievalCandidate:
    """Кандидат-сообщество: `community_id` сборки + `nodes.id` участника.

    Оба значения — из пространства идентификаторов БД (`mca_community_*`,
    `nodes.id`), а не Telegram UID: `subject_entity_ids` (uid) здесь не
    используются и не смешиваются (C-6 §6 / §7.1).

    `provenance_backed` ВЫВОДИТСЯ из статуса сообщества (§14.3): `True`
    только для `proven`; неизвестный/слабый статус → `False`. Константа
    `True` здесь больше недопустима — иначе слабое сообщество выдавалось бы
    за подтверждённое. Метрики (`status/size/strong_share/density/basis`)
    идут в `community`; нейтральная подпись не выводится (`label=None`).
    """
    community_id = _row_get(row, "community_id")
    raw_status = status if status is not None else _row_get(row, "status")
    resolved_status = str(raw_status).strip() if raw_status is not None else ""
    proven_value = _mc.CommunityStatus.PROVEN.value
    size = _row_get(row, "size")
    try:
        size = None if size is None else int(size)
    except (TypeError, ValueError):
        size = None
    strong_share = _row_get(row, "strong_share")
    try:
        strong_share = None if strong_share is None else float(strong_share)
    except (TypeError, ValueError):
        strong_share = None
    density = _row_get(row, "density")
    try:
        density = None if density is None else float(density)
    except (TypeError, ValueError):
        density = None
    raw_label = _row_get(row, "label")
    label = str(raw_label).strip() if raw_label else None
    meta = CommunityMeta(
        community_id=str(community_id),
        status=resolved_status or _mc.CommunityStatus.WEAK.value,
        size=size, strong_share=strong_share, density=density,
        basis=str(_row_get(row, "basis") or ""), label=label or None)
    return RetrievalCandidate(
        id=f"comm:{community_id}:{_row_get(row, 'node_id')}",
        entity_type="community", entity_id=str(community_id),
        chat_id=chat_id, score=_channel_rank("community", position),
        channel="community",
        preview=str(_row_get(row, "entity_name") or ""),
        provenance_backed=meta.status == proven_value,
        community=meta)


def _episode_candidate(row, chat_id: int, position: int,
                       overlap: float = 0.0) -> RetrievalCandidate:
    """HC-TIME (B): эпизод/story-кандидат с разделением event/discovered.

    ``event_start_ts``/``event_end_ts`` рендерятся как окно события ТОЛЬКО
    когда реально присутствуют в строке; ``discovered_at``/``created_at`` —
    отдельная дата записи, не событие. ``sent_at`` сохраняется прежним
    (``last_ts``): поле не переопределяется. Каналы, чья строка не несёт
    event-колонок, честно получают ``time_kind=recorded``/``unknown`` —
    догадка о событии не подставляется.
    """
    episode_id = _row_get(row, "id")
    event_start = _as_int(_row_get(row, "event_start_ts"))
    event_end = _as_int(_row_get(row, "event_end_ts"))
    created = _as_int(_row_get(row, "created_at"))
    discovered = _as_int(_row_get(row, "discovered_at"))
    last_ts = _as_int(_row_get(row, "last_ts"))
    if event_start or event_end:
        time_kind = "event"
    elif created or discovered:
        time_kind = "recorded"
    elif last_ts:
        time_kind = "source"
    else:
        time_kind = "unknown"
    return RetrievalCandidate(
        id=f"episode:{episode_id}", entity_type="episode",
        entity_id=str(episode_id), chat_id=chat_id,
        sent_at=last_ts,
        score=_channel_rank("episode", position) + overlap,
        channel="episode",
        preview=str(_row_get(row, "topic") or ""),
        time_kind=time_kind,
        recorded_at=discovered or created,
        event_start=event_start,
        event_end=event_end,
        discovered_at=discovered or created)


async def _episode_candidates(db, request: RetrievalRequest,
                              keywords: list[str]) -> list:
    """Эпизоды-фасад (mca-05 AMEND, ADR-1027-12 D11): при включённом
    `MCA_EPISODES_COMPILER_FACADE_ENABLED` читает новый store через фасад
    (REUSE list-контракт, второй каталог запрещён — L-MCA07-5); legacy
    `lore_stories` без mapped-связи остаются видимы; `excluded_from_retrieval`
    и `verification='rejected'` не попадают (уважает статусы). Три
    состояния (SC-14, фикс M-MCA05-1): (a) гейт OFF или (b) ошибка
    фасада → санкционированный legacy-путь `list_lore_stories`
    (паритет baseline / fail-open mca-07); (c) фасад ответил (в т.ч.
    честно ПУСТО) → ответ и есть результат: пусто при успехе означает
    намеренное исключение (excluded/rejected/redirect), legacy-фолбэк
    здесь запрещён — иначе excluded-контент утекал бы через mapped-
    двойника в `lore_stories`."""
    from services.lore_compiler_service import topic_tokens
    facade_rows: list | None = None
    try:
        from services import mca_gates as _gates
        if _gates.episodes_compiler_facade_enabled():
            from services.mca_episodes import list_stories_for_retrieval
            facade_rows = await list_stories_for_retrieval(
                db, request.chat_id, limit=200)
    except Exception:
        logger.warning("[mca07] episode facade read failed", exc_info=True)
        facade_rows = None
    if facade_rows is not None:
        rows = facade_rows
    else:
        stories = await db.list_lore_stories(request.chat_id, limit=200)
        rows = [dict(r) for r in (stories or [])]
    if not rows:
        return []
    tokens = set(topic_tokens(request.query)) or set(keywords)
    scored: list[tuple[float, object]] = []
    for row in rows:
        topic = str(_row_get(row, "topic") or "").casefold()
        story = str(_row_get(row, "story") or "").casefold()
        overlap = 0
        for token in tokens:
            if token in topic:
                overlap += 3
            elif token in story:
                overlap += 1
        if overlap:
            scored.append((float(overlap), row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    out: list[RetrievalCandidate] = []
    for position, (overlap, row) in enumerate(scored[:max(1, request.top_k)]):
        out.append(_episode_candidate(
            row, request.chat_id, position, overlap=overlap))
    return out


def apply_retrieval_rerank(result: RetrievalResult,
                           rerank: RerankResult) -> tuple[list, str]:
    """Применить типизированный reranker к кандидатам retrieval (D3).

    Возвращает ``(kept_candidates, status)``: ``ok`` → выбранные в порядке
    оценки; ``empty`` → пусто (НЕ все кандидаты); ``invalid``/``timeout``/
    ``error`` → bounded pre-rerank-fallback (retrieval-порядок)."""
    candidates = list(result.candidates)
    if rerank.status == RERANK_EMPTY or (
            rerank.status == RERANK_OK and not rerank.selected):
        return [], RERANK_EMPTY
    if rerank.is_fallback:
        return candidates[:fallback_top_k(len(candidates))], rerank.status
    by_id = {c.id: c for c in candidates}
    kept = [by_id[item.id] for item in rerank.selected if item.id in by_id]
    return kept, RERANK_OK


__all__ = [
    "BUNDLE_SCHEMA_VERSION", "RETRIEVAL_POLICY_VERSION",
    "RERANK_OK", "RERANK_EMPTY", "RERANK_INVALID", "RERANK_TIMEOUT",
    "RERANK_ERROR", "RERANK_STATUSES", "RerankItem", "RerankResult",
    "classify_rerank_response", "classify_rerank_exception", "select_by_rerank",
    "fallback_top_k", "EvidenceItem", "ExcludedItem", "LessonRef",
    "EvidenceBundle",
    "compute_context_version", "emit_stage_event",
    "RETRIEVAL_OK", "RETRIEVAL_EMPTY", "RETRIEVAL_ERROR",
    "RETRIEVAL_PURPOSES", "RETRIEVAL_MODES", "RETRIEVAL_INTENTS",
    "UI_SEARCH_MAX_LIMIT", "RelevanceDecision",
    "RetrievalRequest", "RetrievalCandidate", "RetrievalResult",
    "is_history_query", "retrieve", "apply_retrieval_rerank",
    "bind_quantitative_range", "project_relations",
    "MEMORY_QUERY_MAX_CHARS", "MEMORY_QUERY_PARENT_CHARS",
    "build_memory_query", "build_memory_request",
    "tokenize_query",
    # MEMORY-06 (§4.4/§7.1/§7.2)
    "request_reason_code", "resolve_intent_mode", "resolve_channels",
    "effective_chat_ids", "request_limit", "typed_rank_score",
    "apply_identity_prior", "apply_subject_gate", "ambiguity_variants",
    "assess_relevance",
    "humanize_summary_text", "summary_date", "chat_timezone_name",
    "render_evidence_summary",
    # VMQ-M2 (M-04/M-05/O-04): bounded overview ЕДИНОГО retrieval
    "OVERVIEW_VERSION", "OVERVIEW_MAX_EPISODES", "OVERVIEW_MAX_PERIODS",
    "OVERVIEW_MAX_COUNTEREXAMPLES", "OVERVIEW_MAX_LIMITATIONS",
    "OVERVIEW_MAX_HINTS", "RetrievalOverview", "overview_from_views",
    "build_retrieval_overview", "apply_overview_to_bundle",
    "overview_bundle_slots",
    # VMQ-MEM/TIME Slice A (15.11.2026): структурированный периодный intent
    "PERIOD_INTENT_NONE", "PERIOD_INTENT_YEAR", "PERIOD_INTENT_HISTORICAL",
    # VMQ-MEM/TIME Slice B (15.11.2026): multi-year intent + квоты
    "PERIOD_INTENT_MULTI_YEAR", "PERIOD_KEEP_HISTORICAL_QUOTA",
    "PERIOD_KEEP_MULTI_YEAR", "year_time_bounds",
    "PERIOD_DROP_OUT_OF_TARGET_YEAR", "PERIOD_DROP_UNKNOWN_YEAR",
    "PERIOD_DROP_SUBJECT", "PERIOD_DROP_POOL_CAP",
    "PERIOD_KEEP_IN_TARGET", "PERIOD_KEEP_SOFT_FALLBACK", "PERIOD_KEEP_VECTOR",
    "PERIOD_MIN_SHARED_STEMS", "PERIOD_SOFT_FALLBACK_MIN_ROWS",
    "PeriodIntent", "resolve_period_intent",
    "period_row_year", "period_row_proxy", "period_subject_stems",
    "period_subject_shared", "select_period_rows",
]

