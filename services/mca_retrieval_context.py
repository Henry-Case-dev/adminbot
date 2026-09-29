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
import hashlib
import logging
import re
import time

from services import mca_gates

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
    "lexical": 80.0,
    "vector": 60.0,
    "reply_graph": 40.0,
    "episode": 20.0,
}
_CHANNEL_ORDER = ("exact", "lexical", "vector", "reply_graph", "episode")
_PREVIEW_MAX_CHARS = 400
# Маркеры исторического запроса (эвристика mode=auto; явный mode имеет приоритет).
_HISTORY_MARKERS = (
    "истори", "расскажи", "что было", "что происходило", "раньше", "когда-то",
    "когда то", "вспомни, как", "вспомни как", "хроник", "летопис",
)


@dataclasses.dataclass(frozen=True)
class RetrievalRequest:
    """Вход единого retrieval-контракта (§4.1)."""
    chat_id: int
    query: str
    trigger_ref: int | None = None
    scope: str = "auto"       # auto|time_range|participants|parent|branch
    mode: str = "auto"        # auto|history|exact
    top_k: int = 12
    policy_version: str = RETRIEVAL_POLICY_VERSION
    time_from: int | None = None
    time_to: int | None = None
    participants: tuple[int, ...] = ()
    reply_depth: int = 6


@dataclasses.dataclass(frozen=True)
class RetrievalCandidate:
    """Кандидат: ССЫЛКА на источник (SourceRef `mca-04a` + время `mca-03`),
    НЕ копия сырья. ``preview`` — транзиентный display для reranker."""
    id: str
    entity_type: str          # message|graph_fact|episode
    entity_id: str
    chat_id: int | None = None
    source_ref_id: int | None = None
    sent_at: int = 0
    author_id: int | None = None
    score: float = 0.0
    channel: str = ""
    revision: str | None = None
    preview: str = ""


@dataclasses.dataclass(frozen=True)
class RetrievalResult:
    """Выход единого retrieval-контракта (§4.1)."""
    status: str
    candidates: tuple[RetrievalCandidate, ...] = ()
    channels_used: tuple[str, ...] = ()
    generation_fingerprint: str | None = None
    reason_code: str | None = None


def is_history_query(query: str) -> bool:
    """Эвристика «запрос об истории» (D2): сначала эпизоды."""
    text = str(query or "").casefold()
    return any(marker in text for marker in _HISTORY_MARKERS)


def _tokenize(query: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", str(query or "").casefold())


def _truncate_preview(text, limit: int = _PREVIEW_MAX_CHARS) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit]


def _row_get(row, key, default=None):
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except Exception:
        return default


def _channel_rank(channel: str, position: int) -> float:
    return _CHANNEL_WEIGHTS.get(channel, 0.0) - float(position)


def _dedup(candidates: list) -> list:
    """Дедуп по стабильному id — сохраняется лучший (макс score) канал."""
    best: dict[str, RetrievalCandidate] = {}
    for cand in candidates:
        current = best.get(cand.id)
        if current is None or cand.score > current.score:
            best[cand.id] = cand
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


async def retrieve(db, memory, request: RetrievalRequest) -> RetrievalResult:
    """Единая точка retrieval-запроса, ОБОРАЧИВАЮЩАЯ существующие каналы.

    Комбинация: exact (quoted-FTS) + lexical/FTS (сообщения + граф-факты) +
    vector (`MemoryManager.retrieve_fact_candidates`) + reply-граф
    (`thread_chain`) + эпизоды (`lore_stories`). Для `mode=history` —
    эпизоды ПЕРВЫМИ, затем сообщения. Кандидаты несут SourceRef-ссылку/время.
    Никогда не бросает: ошибка канала → честная деградация (пропуск канала);
    ошибка всех → ``status='empty'``/``reason_code='retrieval_empty'``."""
    from services.mca_retrieval_context import (  # self (lazy — циклы)
        RETRIEVAL_EMPTY as _EMPTY,
    )
    from services.summary_memory import build_fts_query
    from services.canonical_context import resolve_item_id
    keywords = _tokenize(request.query)
    match = build_fts_query(keywords) if keywords else ""
    now = int(time.time())
    mode = request.mode
    if mode == "auto":
        mode = "history" if is_history_query(request.query) else "auto"
    channels: list[str] = []
    raw: list[RetrievalCandidate] = []
    exact_used = False      # L-MCA07-3: reason_code `exact_match_used`

    # ── эпизоды (для истории — ПЕРВЫМИ) ─────────────────────────────────────
    if mode == "history":
        try:
            episodes = await _episode_candidates(db, request, keywords)
            if episodes:
                raw.extend(episodes)
                channels.append("episode")
        except Exception:
            logger.warning("[mca07] episode channel failed", exc_info=True)

    # ── exact (quoted-фраза всегда доступна) ────────────────────────────────
    phrases = re.findall(r'"([^"]{2,})"', request.query)
    for phrase in phrases[:4]:
        try:
            exact_match = '"' + phrase.replace('"', "").replace("*", "") + '"'
            rows = await db.search_messages_fts(
                request.chat_id, exact_match, max(1, request.top_k))
            for pos, row in enumerate(rows or []):
                raw.append(_message_candidate(row, "exact", pos, resolve_item_id))
            if rows:
                channels.append("exact")
                exact_used = True
        except Exception:
            logger.warning("[mca07] exact channel failed", exc_info=True)

    # ── lexical/FTS: сообщения + граф-факты ─────────────────────────────────
    if match:
        try:
            rows = await db.search_messages_fts(
                request.chat_id, match, max(1, request.top_k * 2))
            for pos, row in enumerate(rows or []):
                raw.append(_message_candidate(row, "lexical", pos, resolve_item_id))
            if rows:
                channels.append("lexical")
        except Exception:
            logger.warning("[mca07] lexical messages channel failed",
                           exc_info=True)
        try:
            rows = await db.search_graph_facts_fts(
                request.chat_id, match, max(1, request.top_k * 2), now)
            for pos, row in enumerate(rows or []):
                raw.append(_fact_candidate(row, "lexical", pos, resolve_item_id))
            if rows:
                channels.append("lexical")
        except Exception:
            logger.warning("[mca07] lexical facts channel failed",
                           exc_info=True)

    # ── vector (REUSE MemoryManager; единый retrieval-контракт) ─────────────
    if memory is not None:
        try:
            facts = await memory.retrieve_fact_candidates(
                request.chat_id, request.query, limit=max(1, request.top_k))
            for pos, row in enumerate(facts or []):
                raw.append(_fact_meta_candidate(row, pos, resolve_item_id))
            if facts:
                channels.append("vector")
        except Exception:
            logger.warning("[mca07] vector channel failed", exc_info=True)

    # ── reply-граф (REUSE thread_chain; scope parent/branch/auto-trigger) ────
    if request.trigger_ref is not None and request.scope in (
            "auto", "parent", "branch") and request.reply_depth > 0:
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

    raw = _apply_filters(raw, request)
    # Порядок: история — эпизоды первыми, далее по весу канала/позиции.
    def _sort_key(cand: RetrievalCandidate):
        history_bias = (1 if (mode == "history" and cand.channel == "episode")
                        else 0)
        return (history_bias, cand.score)
    ordered = sorted(_dedup(raw), key=_sort_key, reverse=True)
    # Ограничение top_k (эпизоды-первыми не вытесняются при истории).
    if len(ordered) > max(1, request.top_k):
        if mode == "history":
            eps = [c for c in ordered if c.channel == "episode"]
            rest = [c for c in ordered if c.channel != "episode"]
            ordered = (eps + rest)[:max(1, request.top_k)]
        else:
            ordered = ordered[:max(1, request.top_k)]

    generation_fingerprint = None
    try:
        active = await db.get_active_embedding_generation("graph_facts_vec")
        if active is not None:
            generation_fingerprint = active.get("fingerprint")
    except Exception:
        generation_fingerprint = None

    status = RETRIEVAL_OK if ordered else _EMPTY
    reason = None if ordered else "retrieval_empty"
    if mode == "history" and ordered and any(
            c.channel == "episode" for c in ordered):
        reason = "episodes_used"
    if exact_used:
        # L-MCA07-3: точная фраза/имя/дата всегда доступна — отдельный код.
        emit_stage_event("retrieval", "success",
                         reason_code="exact_match_used",
                         chat_id=request.chat_id)
    emit_stage_event(
        "retrieval", "success" if ordered else "silent",
        reason_code=reason, chat_id=request.chat_id,
        entity_ids=[c.id for c in ordered[:20]],
        message_id=request.trigger_ref)
    return RetrievalResult(
        status=status, candidates=tuple(ordered),
        channels_used=tuple(sorted(set(channels), key=_CHANNEL_ORDER.index)),
        generation_fingerprint=generation_fingerprint, reason_code=reason)


def _message_candidate(row, channel: str, position: int, resolve_item_id):
    message_id = _row_get(row, "id")
    tg_id = _row_get(row, "tg_message_id")
    item_id = resolve_item_id(tg_message_id=tg_id, message_id=message_id)
    return RetrievalCandidate(
        id=item_id or f"msg:{message_id}",
        entity_type="message", entity_id=str(message_id),
        chat_id=_row_get(row, "chat_id"),
        sent_at=int(_row_get(row, "timestamp") or 0),
        author_id=_row_get(row, "user_id"),
        score=_channel_rank(channel, position), channel=channel,
        preview=_truncate_preview(_row_get(row, "text")))


def _fact_candidate(row, channel: str, position: int, resolve_item_id):
    fact_id = _row_get(row, "id")
    tg_id = _row_get(row, "tg_message_id")
    item_id = resolve_item_id(tg_message_id=tg_id, fact_id=fact_id)
    return RetrievalCandidate(
        id=item_id or f"fact:{fact_id}",
        entity_type="graph_fact", entity_id=str(fact_id),
        chat_id=_row_get(row, "chat_id"),
        sent_at=int(_row_get(row, "rag_ts")
                    or _row_get(row, "message_timestamp")
                    or _row_get(row, "created_at") or 0),
        author_id=_row_get(row, "user_id"),
        score=_channel_rank(channel, position), channel=channel,
        preview=_truncate_preview(_row_get(row, "fact")))


def _fact_meta_candidate(row, position: int, resolve_item_id):
    """Кандидат из `MemoryManager.retrieve_fact_candidates` (dict with id)."""
    fact_id = row.get("id")
    item_id = row.get("item_id") or resolve_item_id(
        tg_message_id=row.get("tg_message_id"), fact_id=fact_id)
    return RetrievalCandidate(
        id=item_id or f"fact:{fact_id}",
        entity_type="graph_fact", entity_id=str(fact_id),
        sent_at=int(row.get("rag_ts") or 0),
        score=_channel_rank("vector", position), channel="vector",
        preview=_truncate_preview(row.get("fact")))


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
        preview=_truncate_preview(getattr(item, "text", "")))


async def _episode_candidates(db, request: RetrievalRequest,
                              keywords: list[str]) -> list:
    """Эпизоды-фасад (`lore_stories`; второй каталог запрещён) — REUSE."""
    from services.lore_compiler_service import topic_tokens
    stories = await db.list_lore_stories(request.chat_id, limit=200)
    if not stories:
        return []
    tokens = set(topic_tokens(request.query)) or set(keywords)
    scored: list[tuple[float, object]] = []
    for row in stories:
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
            preview=_truncate_preview(_row_get(row, "topic"))))
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
    "fallback_top_k", "EvidenceItem", "ExcludedItem", "EvidenceBundle",
    "compute_context_version", "emit_stage_event",
    "RETRIEVAL_OK", "RETRIEVAL_EMPTY", "RETRIEVAL_ERROR",
    "RetrievalRequest", "RetrievalCandidate", "RetrievalResult",
    "is_history_query", "retrieve", "apply_retrieval_rerank",
]

