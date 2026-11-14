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

    Бонусы ограничены так, чтобы канал оставался доминирующим: старый
    «сомнительный» vector-hit не выигрывает у свежего точного assertion
    только за счёт similarity, но и не перебивает более сильный канал."""
    score = float(candidate.score)
    if candidate.provenance_backed:
        score += _TYPED_TRUST_BONUS
    elif candidate.entity_type == "graph_fact":
        score -= _TYPED_LEGACY_PENALTY      # legacy/unverified — weak hint
    if candidate.sent_at:
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


def project_relations(links, limit: int = 20) -> tuple[dict, ...]:
    """MEMORY-06 (§7.5): санкционированная проекция связей субъекта.

    Вход — УЖЕ прочитанные рёбра (`get_persona_card.links`): своего поиска,
    индекса или второго хранилища здесь нет. Проекция сохраняет основание
    ребра (`legacy_ids` — edge/fact id, `has_unsupported_sources` — «источник
    не указан»), чтобы потребитель не выдавал ребро без основания за
    подтверждённое знание. Порядок входа сохраняется, размер ограничен.
    """
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
        out.append({
            "text": f"{source_name} ({relation}) {target_name}".strip(),
            "edge_id": edge_id,
            "fact_id": fact_id,
            "origin": origin,
            "weight": link.get("weight"),
            "legacy_ids": legacy_ids,
            "has_unsupported_sources": not supported,
            "source_basis": "" if supported else "источник не указан",
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
        card = await getter(int(request.chat_id), name, max(1, int(limit)),
                            int(time.time()))
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
    """Фильтры по времени (событийное `sent_at`) и участникам (`author_id`)."""
    out = []
    for cand in candidates:
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
                         chat_id=request.chat_id)
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
    period_match = ""
    period_keywords: list = []
    if request.period_fill:
        period_keywords = _period_fts_keywords(keywords)
        period_match = build_fts_query(
            period_keywords,
            mode=("prefix_or_stem" if request.lexical_stem else "prefix_or")
        ) if period_keywords else ""
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
        for chat_id in chat_ids:
            try:
                rows = await db.search_messages_fts(
                    chat_id, match, max(1, fetch_k * 2))
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
            if not callable(reader):
                period_stats["vector_leg"] = "unsupported_memory"
                period_stats["knn_ms_reason"] = "vector_leg_unsupported"
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
    emit_stage_event(
        "retrieval", "success" if ordered else "silent",
        reason_code=reason, chat_id=request.chat_id,
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
        fact_rows=tuple(fact_rows[_candidate_identity(cand)] for cand in ordered
                        if _candidate_identity(cand) in fact_rows),
        period_fill=period_usage)


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


def _period_fts_keywords(keywords: list[str]) -> list[str]:
    """§2-совместимые токены ПЕРИОДНОГО FTS-запроса (VMQ-NEXT-02 §A).

    §2 (`_rag_subject_stems`) считает только основы длиной `>= 4`. Токен,
    чья основа короче, всё равно будет отброшен потребителем, поэтому он не
    должен формировать периодный пул. Зеркалим §2 на той же морфологии
    (`text_morphology.stem_word`), не меняя глобальный `build_fts_query`:
    длинные содержательные токены и их prefix/stem варианты сохраняются.
    Пустой результат — честная деградация вызывающей ветки, а не пустое
    или неограниченное FTS-выражение.
    """
    from services.text_morphology import stem_word
    out: list = []
    for word in keywords or ():
        token = str(word or "")
        if token and len(stem_word(token)) >= 4:
            out.append(token)
    return out


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
        subject_entity_id=subject_id,
        speaker_entity_id=row.get("speaker_author_id"),
        assertion_kind=row.get("assertion_kind"),
        attribution_method=row.get("attribution_method"),
        origin_type=(str(row.get("origin") or "") or None),
        provenance_backed=(subject_ref not in (None, "")))


def _chain_candidate(item, position: int):
    item_id = getattr(item, "item_id", "") or ""
    is_bot = bool(getattr(item, "is_bot", False))
    return RetrievalCandidate(
        id=item_id or f"reply:{position}",
        entity_type="message",
        entity_id=item_id.split(":", 1)[1] if ":" in item_id else item_id,
        sent_at=int(getattr(item, "ts", 0) or 0),
        author_id=getattr(item, "uid", None),
        score=_channel_rank("reply_graph", position), channel="reply_graph",
        preview=str(getattr(item, "text", "") or ""))


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
        episode_id = _row_get(row, "id")
        out.append(RetrievalCandidate(
            id=f"episode:{episode_id}", entity_type="episode",
            entity_id=str(episode_id), chat_id=request.chat_id,
            sent_at=int(_row_get(row, "last_ts") or 0),
            score=_channel_rank("episode", position) + overlap,
            channel="episode",
            preview=str(_row_get(row, "topic") or "")))
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
]

