"""mca-06 (ADR-1028-9 D3/D4, spec §4) — исторический профиль поиска
глубокого сна: кандидаты поверх каналов mca-07 + эпизодов, возраст ДО top_k,
возраст от `message_timestamp`, тематические пакеты, семантический фильтр +
ранжирование, bounded resumable enrichment, точность source window.

Модуль изолирован в sleep-контуре: direct-RAG (`get_rag_facts`) и его смысл
не меняются (регресс), ACL не обходится (каналы уже scoped по chat_id).
Второй retrieval/резолвер НЕ создаётся — REUSE `retrieve_fact_candidates`.

Kill-switch `MCA_DREAM_HISTORICAL_PROFILE_ENABLED` (env-only, default ON):
OFF → DreamWorker использует прежний порядок (`get_rag_facts` → top_k →
возраст; spec §11.1).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from services import mca_dream_random
from services import mca_gates

logger = logging.getLogger(__name__)

_DAY = 86400


# ── возраст: ТОЛЬКО проверяемое время сообщения (D4, §4.3) ──────────────────

def message_timestamp_of(item) -> int | None:
    """Проверяемое время исходного сообщения основания (unix) или None.

    Источник — `message_timestamp` (mca-03 пара `(chat_id, tg_message_id)`).
    `rag_ts` (COALESCE(message_timestamp, created_at)) и `created_at`
    (дата индексации) доказанной датой события НЕ считаются и в порог
    не подставляются (§4.3, D4: unknown ≠ «старая»)."""
    if isinstance(item, dict):
        ts = item.get("message_timestamp")
    elif isinstance(item, (tuple, list)) and len(item) > 5:
        # legacy 6-кортеж get_rag_facts: даты события там нет по контракту.
        ts = None
    else:
        ts = None
    try:
        ts = int(ts)
        return ts if ts > 0 else None
    except (TypeError, ValueError):
        return None


def is_historical(item, now: int, min_age_days: int) -> bool:
    """Основание старше порога ПО message_timestamp. Нет валидного времени →
    False (unknown не проходит порог, §4.3/THR-2)."""
    ts = message_timestamp_of(item)
    if ts is None:
        return False
    return (int(now) - ts) > int(min_age_days) * _DAY


# ── тематические пакеты (bound, §4.4) ───────────────────────────────────────

@dataclass
class TopicPacket:
    """Ограниченный тематический пакет (субъекты + сравниваемый период)."""
    key: str
    subjects: tuple[str, ...]
    facts: list = field(default_factory=list)


def _subject_tokens(text: str) -> tuple[str, ...]:
    """Устойчивые субъекты пакета: значимые токены факта (REUSE
    `significant_tokens` из dream_worker, MCA05-R2 «тема ≠ событие»)."""
    from services.dream_worker import significant_tokens
    return tuple(dict.fromkeys(significant_tokens(text)))[:6]


def build_topic_packets(items, *, max_packets: int | None = None) -> list[TopicPacket]:
    """Разбить основания на ограниченные тематические пакеты.

    Один общий запрос из несвязанных убеждений не расширяется бесконечно:
    не более `max_packets` пакетов; переполнение присоединяется к последнему
    (bounded), а не создаёт неограниченный список."""
    bound = int(max_packets or mca_gates.dream_max_topic_packets())
    bound = max(1, bound)
    packets: list[TopicPacket] = []
    index: dict[str, TopicPacket] = {}
    overflow = 0
    for it in list(items or []):
        text = _item_text(it)
        subs = _subject_tokens(text)
        key = "|".join(subs[:3]) or "__misc__"
        pkt = index.get(key)
        if pkt is None:
            if len(packets) >= bound:
                overflow += 1
                packets[-1].facts.append(it)      # bounded-слияние
                continue
            pkt = TopicPacket(key=key, subjects=subs)
            index[key] = pkt
            packets.append(pkt)
        pkt.facts.append(it)
    if overflow:
        logger.info("[dream_history] topic packets bounded | packets=%d | "
                    "merged=%d", len(packets), overflow)
    return packets


# ── семантический фильтр + ранжирование (§4.4: тема/участники/freshness) ────

def _item_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("fact") or item.get("summary")
                   or item.get("title") or "")
    if isinstance(item, (tuple, list)) and len(item) > 1:
        return str(item[1] or "")
    return str(item or "")


def _item_participants(item) -> tuple[str, ...]:
    if isinstance(item, dict):
        parts = item.get("participants")
        if parts:
            return tuple(str(p) for p in parts)
        tu = item.get("target_user")
        return (str(tu),) if tu else ()
    if isinstance(item, (tuple, list)) and len(item) > 3 and item[3]:
        return (str(item[3]),)
    return ()


def rank_candidates(items, *, query: str, now: int, participants=(),
                    min_age_days: int | None = None) -> list:
    """Детерминированное ранжирование: релевантность от retrieval + тема +
    пересечение участников + freshness. Случайность не участвует (§8.7)."""
    q_terms = set(_subject_tokens(query))
    want = {str(p).casefold() for p in (participants or ()) if p}
    now = int(now)
    scored: list[tuple[float, object]] = []
    for it in list(items or []):
        base = 0.0
        if isinstance(it, dict):
            try:
                base = float(it.get("score") or 0.0)
            except (TypeError, ValueError):
                base = 0.0
        text = _item_text(it)
        t_terms = set(_subject_tokens(text))
        topic = len(q_terms & t_terms) / max(1, len(q_terms))
        parts = {p.casefold() for p in _item_participants(it)}
        p_overlap = 1.0 if (want and want & parts) else 0.0
        ts = message_timestamp_of(it)
        # freshness: нормируем логарифмически к 1 году (свежее — выше).
        freshness = 0.0
        if ts is not None:
            age_days = max(0.0, (now - ts) / float(_DAY))
            freshness = 1.0 / (1.0 + age_days / 365.0)
        score = (base * 0.5) + (topic * 0.3) + (p_overlap * 0.1) \
            + (freshness * 0.1)
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored]


# ── отбор: возраст/дедуп/период ДО финального top_k (§4.2) ──────────────────

@dataclass
class HistoricalSelection:
    candidates: list = field(default_factory=list)
    total: int = 0
    missing_timestamp: int = 0
    excluded_young: int = 0
    duplicates: int = 0
    episodes_total: int = 0
    fts_fallback: bool = False
    reason: str | None = None
    packets: list = field(default_factory=list)
    # T-4730: bounded selection_meta выбора материала (`DreamRandomSource.pick`).
    selection_meta: dict | None = None

    @property
    def missing_timestamp_ratio(self) -> float:
        return (float(self.missing_timestamp) / float(self.total)
                if self.total else 0.0)


def _dedup_key(item) -> tuple:
    """Каноническая идентичность основания: `(chat_id, tg_message_id)` /
    `id` / текст. Пересказы одного события → один ключ (§5.1 пре-дубль)."""
    if isinstance(item, dict):
        cid = item.get("chat_id")
        tg = item.get("tg_message_id")
        if tg is not None:
            return ("tg", cid, tg)
        if item.get("item_id"):
            return ("item", item.get("item_id"))
        if item.get("id") is not None:
            return ("id", item.get("id"))
    return ("text", _item_text(item).strip().casefold()[:200])


async def _fetch_fact_candidates(memory, chat_id: int, query: str,
                                 limit: int) -> tuple[list, bool]:
    """Кандидаты-факты mca-07. REUSE `retrieve_fact_candidates` — второго
    retrieval НЕ создаётся. FTS-фолбэк — БЕЗ vec-предусловия (§4.5): сам
    канал (`_search_graph_facts`) уходит в FTS/lexical при неактивном
    vec-поколении/карантине. `fts_fallback` — best-effort подсказка для
    отчёта (по флагу неактивного vec-поколения)."""
    retrieve = getattr(memory, "retrieve_fact_candidates", None)
    if not callable(retrieve):
        return [], False
    rows = await retrieve(chat_id, query, limit=limit)
    fts_fallback = getattr(memory, "_vec_available", None) is False
    return list(rows or []), fts_fallback


async def _fetch_episodes(episodes_repo, chat_id: int, limit: int) -> list[dict]:
    """Эпизоды как кандидат-источник (`EpisodeRepository.list_episodes`).
    Пустой пул — штатная ветка, не сбой (§4.4/CA-4)."""
    if episodes_repo is None:
        return []
    try:
        rows = await episodes_repo.list_episodes(chat_id, limit=limit)
    except Exception:
        logger.warning("[dream_history] episodes read failed — empty | "
                       "chat_id=%s", chat_id, exc_info=True)
        return []
    out: list[dict] = []
    for r in list(rows or []):
        row = dict(r) if not isinstance(r, dict) else r
        out.append({
            "id": row.get("episode_id"),
            "item_id": f"episode:{row.get('episode_id')}",
            "chat_id": row.get("chat_id"),
            "fact": str(row.get("summary") or row.get("title") or ""),
            "message_timestamp": row.get("event_start_ts"),
            "created_at": row.get("discovered_at"),
            "participants": _parse_participants(row.get("participants_json")),
            "score": 0.0,
            "source_kind": "episode",
        })
    return out


def _parse_participants(raw):
    import json
    if isinstance(raw, (list, tuple)):
        return list(raw)
    try:
        val = json.loads(str(raw or "[]"))
        return val if isinstance(val, list) else []
    except Exception:
        return []


async def select_historical_candidates(
    memory, episodes_repo, chat_id: int, query: str, *,
    top_k: int, now: int, min_age_days: int,
    prelimit_factor: int | None = None,
    participants=(),
    max_packets: int | None = None,
    random_source=None,
) -> HistoricalSelection:
    """Профиль исторического поиска (spec §4.1–4.3, D3/D7).

    Порядок: предвыборка (pre-limit ≥ factor×top_k) → возраст/дедуп ДО
    финального top_k → материал. Direct-RAG и его контракты не меняются;
    ACL не обходится.

    `random_source` (T-4730/AM-2): при активном исследовании менее изученных
    периодов материал выбирает ТОЛЬКО `DreamRandomSource.pick` (seed =
    `(pipeline_run_id, chat_id)`), `selection_meta` → отчёт §7.2. Случайность
    выбирает материал; вердикт — по доказательствам §5.3 (downstream).
    `None` (kill-switch OFF) → прежнее детерминированное ранжирование."""
    top_k = max(1, int(top_k))
    factor = int(prelimit_factor or mca_gates.dream_historical_prelimit_factor())
    pre_limit = max(top_k * max(1, factor), top_k)

    facts, fts_fallback = await _fetch_fact_candidates(
        memory, chat_id, query, pre_limit)
    episodes = await _fetch_episodes(episodes_repo, chat_id, pre_limit)
    pool = facts + episodes
    result = HistoricalSelection(total=len(pool), episodes_total=len(episodes),
                                 fts_fallback=fts_fallback)

    # Тематические пакеты (bound) — материал для поиска, но отбор общий.
    packets = build_topic_packets(
        [{"fact": _item_text(x)} for x in pool], max_packets=max_packets)

    # 1) возраст ДО top_k; missing_timestamp учитывается честно.
    aged: list = []
    seen: set = set()
    for it in pool:
        if message_timestamp_of(it) is None:
            result.missing_timestamp += 1
            continue
        if not is_historical(it, now, min_age_days):
            result.excluded_young += 1
            continue
        key = _dedup_key(it)
        if key in seen:
            result.duplicates += 1
            continue
        seen.add(key)
        aged.append(it)

    if not aged:
        result.reason = "no_anchors"
        result.candidates = []
        result.packets = packets
        return result

    # 2) материал: T-4730 — при активном исследовании выбор ТОЛЬКО через
    # `DreamRandomSource.pick` (seed=(pipeline_run_id, chat_id)); иначе прежнее
    # детерминированное ранжирование (тема/участники/freshness).
    if random_source is not None:
        try:
            items, meta = random_source.pick(
                aged, chat_id=chat_id,
                purpose=mca_dream_random.PURPOSE_LESS_STUDIED, k=top_k)
            result.candidates = list(items)
            result.selection_meta = dict(meta or {})
            result.packets = packets
            return result
        except Exception:
            logger.warning("[dream_history] random pick failed — ranked "
                           "fallback | chat_id=%s", chat_id, exc_info=True)
    ranked = rank_candidates(aged, query=query, now=now,
                             participants=participants,
                             min_age_days=min_age_days)
    # 3) финальный top_k — значение `limits.deep_sleep_top_k` не трогается.
    result.candidates = ranked[:top_k]
    result.packets = packets
    return result


# ── bounded resumable enrichment (§4.4; донор mca-05 worker-budget) ─────────

@dataclass
class EnrichmentResult:
    status: str            # 'completed' | 'paused' | 'skipped'
    processed: int = 0
    rounds: int = 0
    checkpoint: dict = field(default_factory=dict)
    duplicates: int = 0
    reason: str | None = None


async def enrich_history(chat_id: int, messages, *, checkpoint: dict | None = None,
                         max_rounds: int | None = None,
                         batch_size: int | None = None,
                         worker=None) -> EnrichmentResult:
    """Ограниченный resumable enrichment старой истории без фактов.

    Bounded бюджет (`worker_budget.consume`), checkpoint (resume без дублей),
    hexagonal/durable-job-friendly (checkpoint возвращается наружу — durable
    носитель `task_jobs`, не `payload`-трекинг; урок L-EXTRA-6). Exhaustion →
    `paused`, НИКОГДА не гильотина. Kill-switch OFF → enrichment не
    запускается (вызывающий проверяет гейт до вызова)."""
    rounds_max = int(max_rounds or mca_gates.dream_enrich_max_rounds())
    batch = int(batch_size or mca_gates.dream_enrich_batch_messages())
    rounds_max = max(1, rounds_max)
    batch = max(1, batch)
    ckpt = dict(checkpoint or {})
    seen = set(str(x) for x in (ckpt.get("seen") or []))
    offset = int(ckpt.get("offset") or 0)
    items = list(messages or [])
    processed = 0
    rounds = 0
    duplicates = 0
    # REUSE worker-budget: предпроверка деградации (fail-open при отсутствии).
    try:
        from services import worker_budget
        if not await worker_budget.global_degradation_allows(
                worker_budget.WORKER_DEEP_SLEEP):
            ckpt.update({"offset": offset, "seen": sorted(seen)})
            return EnrichmentResult("paused", 0, 0, ckpt, 0,
                                    "worker_budget_degraded")
    except Exception:
        worker_budget = None
    while rounds < rounds_max and offset < len(items):
        chunk = items[offset:offset + batch]
        for it in chunk:
            key = repr(_dedup_key(it))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            processed += 1
        offset += len(chunk)
        rounds += 1
        try:
            if worker_budget is not None:
                ok = await worker_budget.consume(None, "global", "llm_calls", 1)
                if not ok:
                    ckpt.update({"offset": offset, "seen": sorted(seen)})
                    return EnrichmentResult("paused", processed, rounds, ckpt,
                                            duplicates, "budget_exhausted")
        except Exception:
            pass
    ckpt.update({"offset": offset, "seen": sorted(seen)})
    status = "completed" if offset >= len(items) else "paused"
    reason = None if status == "completed" else "enrich_max_rounds"
    return EnrichmentResult(status, processed, rounds, ckpt, duplicates, reason)


# ── точность source window (§4.3/§4.2: message timestamps + bounded) ────────

@dataclass
class SourceWindow:
    items: list = field(default_factory=list)
    missing_timestamp: int = 0
    out_of_range: int = 0
    start_ts: int | None = None
    end_ts: int | None = None


def bound_source_window(items, *, start_ts: int | None = None,
                        end_ts: int | None = None, limit: int | None = None
                        ) -> SourceWindow:
    """Source window по message_timestamp (не по индексации), bounded.

    Основания без валидного времени не попадают в окно (missing_timestamp++),
    что честно учитывается в отчёте §7.2 п.7."""
    win = SourceWindow()
    ts_list: list[int] = []
    count = 0
    for it in list(items or []):
        ts = message_timestamp_of(it)
        if ts is None:
            win.missing_timestamp += 1
            continue
        if start_ts is not None and ts < int(start_ts):
            win.out_of_range += 1
            continue
        if end_ts is not None and ts > int(end_ts):
            win.out_of_range += 1
            continue
        if limit is not None and count >= int(limit):
            break
        win.items.append(it)
        ts_list.append(ts)
        count += 1
    if ts_list:
        win.start_ts = min(ts_list)
        win.end_ts = max(ts_list)
    return win
