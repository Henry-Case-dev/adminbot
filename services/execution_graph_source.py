"""S8 round1026 (ADR-1026-10 D2/D3/D4/D5/D6/D7) + S6 round1026
(ADR-1026-11 D6) — backend-нормализация «Backend metrics → Normalized
execution graph» для карты вызовов Саммари.

Отдельный **чистый** слой (D3/§25): преобразование сырых источников в
канонический ``ExecutionNode``-shape (§23/§24) живёт здесь, а НЕ внутри
SVG/Vue-компонента. Модуль:
  * держит ограниченный **in-memory** реестр снапшотов прогона (S7
    ``RunContext`` + S1 ``_filter_metrics``) — без DDL/persistence
    (прецедент S9 ``_RunStore``, Δ DDL=0, D7);
  * строит узлы ``algorithm`` (Filter) / ``llm`` (L1/L2) / ``format``
    (Formatting) / ``publish`` (Публикация) только из **реальных** данных;
    нет данных/этапа → нет узла (§24/§25/§30);
  * формирует §112-метрики честно: неизвестная стоимость → ``None``
    («Нет данных»), **никогда** выдуманный ``$0``; ``-1``-sentinel →
    «Без лимита»; ``publication_status`` — реальный
    (``published_rich``/``published_text``/``failed``/``skipped``; нет данных
    → ``None``, AMEND ADR-1026-10 D1/D4/D8, S6).

Границы (D1/D5/D8/D10):
  * единый ключ ``run_id`` = ``correlation_id`` (S7 = S1–S5/S9); второй
    идентификатор/учёт не вводится;
  * publish-срез **активирован в S6** (ADR-1026-11 D6): узел ``kind="publish"``
    строится только из реальных полей снапшота (channel/status/duration/
    message_id; без LLM-токенов/стоимости);
  * LLM-токены/стоимость — из ``llm_usage_events`` (передаются сюда готовыми
    строками; второй сборщик не создаётся), §112 — из снапшота прогона;
  * R17: наружу только числа/коды/id/строки статусов — без ключей, промптов,
    сырых текстов и ответов LLM.
"""
from __future__ import annotations

import collections
import threading
import time

# ── kind-enum (§111/§24) ────────────────────────────────────────────────────
KIND_LLM = "llm"
KIND_ALGORITHM = "algorithm"
KIND_FORMAT = "format"
KIND_PUBLISH = "publish"          # S6 (ADR-1026-11 D6): активирован
KIND_OTHER = "other"
# A9 (ADR-1026-22 D7): kind `tool` уже зарезервирован в JS `KIND_ENUM` — новых
# kinds не вводится; Python-константа добавлена для агентных tool-узлов.
KIND_TOOL = "tool"

KIND_LABELS = {
    KIND_LLM: "LLM",
    KIND_ALGORITHM: "Алгоритм",
    KIND_FORMAT: "Форматирование",
    KIND_PUBLISH: "Публикация",
    KIND_TOOL: "Инструмент",
    KIND_OTHER: "Шаг",
}

# ── реальные этапы Эпика 2 (§111, D2) ───────────────────────────────────────
STAGE_FILTER = "filter"
STAGE_L1 = "l1_clusterizer"
STAGE_L2 = "l2_writer"
STAGE_FORMAT = "formatting"
STAGE_PUBLISH = "publication"     # S6 (D6): после formatting

# A9 (ADR-1026-22 D7): 9 реальных этапов §51 агентного прогона — существующие
# kinds, без новых. Нет данных этапа → нет узла (§24/§25/§30).
STAGE_DECISION = "decision"
STAGE_MEMORY_LOOKUP = "memory_lookup"
STAGE_RAG = "rag"
STAGE_WEB_EXTRACTION = "web_extraction"
STAGE_FACTCHECK = "factcheck"
STAGE_IMAGE_PROMPT = "image_prompt"
STAGE_IMAGE_GENERATION = "image_generation"
STAGE_REACTION = "reaction"
STAGE_TEXT_GENERATION = "text_generation"

STAGE_LABELS = {
    STAGE_FILTER: "Алгоритмический фильтр",
    STAGE_L1: "L1 Кластеризатор",
    STAGE_L2: "L2 Писатель",
    STAGE_FORMAT: "Форматирование",
    STAGE_PUBLISH: "Публикация",
    # A9/§51.
    STAGE_DECISION: "Решение",
    STAGE_MEMORY_LOOKUP: "Поиск в памяти",
    STAGE_RAG: "RAG",
    STAGE_WEB_EXTRACTION: "Извлечение из веба",
    STAGE_FACTCHECK: "Фактчек",
    STAGE_IMAGE_PROMPT: "Подготовка промпта изображения",
    STAGE_IMAGE_GENERATION: "Генерация изображения",
    STAGE_REACTION: "Реакция",
    STAGE_TEXT_GENERATION: "Генерация текста",
}

# Канонический порядок этапов одного прогона (подтверждённая линейная
# последовательность §111/D6): filter → L1 → L2 → formatting → publication
# (S6: публикация после форматирования).
STAGE_ORDER = (STAGE_FILTER, STAGE_L1, STAGE_L2, STAGE_FORMAT, STAGE_PUBLISH)

# A9 (D7): канонический порядок 9 агентных этапов §51.
AGENTIC_STAGE_ORDER = (
    STAGE_DECISION, STAGE_MEMORY_LOOKUP, STAGE_RAG, STAGE_WEB_EXTRACTION,
    STAGE_FACTCHECK, STAGE_IMAGE_PROMPT, STAGE_IMAGE_GENERATION,
    STAGE_REACTION, STAGE_TEXT_GENERATION,
)

# step → kind (LLM-строки из `llm_usage_events`; legacy-шаги — как в F6).
STEP_KIND = {
    "single": KIND_LLM, "stage1": KIND_LLM, "stage2": KIND_LLM,
    "image": KIND_LLM,
    STAGE_L1: KIND_LLM, STAGE_L2: KIND_LLM,
    "tool": KIND_TOOL,
    STAGE_FILTER: KIND_ALGORITHM, STAGE_FORMAT: KIND_FORMAT,
    "format": KIND_FORMAT,
    # S6 (D6): публикация — не LLM-строка; publish-узел строится отдельно из
    # снапшота (`publish_node`), llm_node такие строки не превращает в узлы.
    STAGE_PUBLISH: KIND_PUBLISH,
    # A9 (D7): 9 агентных этапов → существующие kinds.
    STAGE_DECISION: KIND_ALGORITHM,
    STAGE_MEMORY_LOOKUP: KIND_TOOL,
    STAGE_RAG: KIND_TOOL,
    STAGE_WEB_EXTRACTION: KIND_TOOL,
    STAGE_FACTCHECK: KIND_TOOL,
    STAGE_IMAGE_PROMPT: KIND_ALGORITHM,
    STAGE_IMAGE_GENERATION: KIND_TOOL,
    STAGE_REACTION: KIND_TOOL,
    STAGE_TEXT_GENERATION: KIND_LLM,
}
STEP_LABEL = {
    "single": "Один вызов", "stage1": "Слой 1", "stage2": "Слой 2",
    "image": "Изображение", "tool": "Инструмент",
    STAGE_FILTER: STAGE_LABELS[STAGE_FILTER],
    STAGE_L1: STAGE_LABELS[STAGE_L1],
    STAGE_L2: STAGE_LABELS[STAGE_L2],
    STAGE_FORMAT: STAGE_LABELS[STAGE_FORMAT],
    STAGE_PUBLISH: KIND_LABELS[KIND_PUBLISH],
    STAGE_DECISION: STAGE_LABELS[STAGE_DECISION],
    STAGE_MEMORY_LOOKUP: STAGE_LABELS[STAGE_MEMORY_LOOKUP],
    STAGE_RAG: STAGE_LABELS[STAGE_RAG],
    STAGE_WEB_EXTRACTION: STAGE_LABELS[STAGE_WEB_EXTRACTION],
    STAGE_FACTCHECK: STAGE_LABELS[STAGE_FACTCHECK],
    STAGE_IMAGE_PROMPT: STAGE_LABELS[STAGE_IMAGE_PROMPT],
    STAGE_IMAGE_GENERATION: STAGE_LABELS[STAGE_IMAGE_GENERATION],
    STAGE_REACTION: STAGE_LABELS[STAGE_REACTION],
    STAGE_TEXT_GENERATION: STAGE_LABELS[STAGE_TEXT_GENERATION],
}

# §112: честные подписи (без выдуманных значений).
NO_DATA = "Нет данных"
UNLIMITED_LABEL = "Без лимита"
# S6 (D6): реальные статусы публикации (нет данных → None, не `gated`).
PUBLISHED_RICH = "published_rich"
PUBLISHED_TEXT = "published_text"
PUBLICATION_FAILED = "failed"
PUBLICATION_SKIPPED = "skipped"

# §112: step → слот токенов/стоимости L1/L2 (единый учёт, как S9).
_USAGE_STEP_MAP = {STAGE_L1: "l1", STAGE_L2: "l2"}


# ── in-memory реестр снапшотов прогона (D7: Δ DDL=0) ────────────────────────

# A9 (D1/D5): агентные события живут в ТОМ ЖЕ in-memory снапшоте (под ключом
# `agentic_events`), отдельный store/PG-таблица не создаётся. Бounded-лимит —
# не раздуваем снапшот; R17-safe поля (фильтрует `agentic_events`).
_AGENTIC_KEY = "agentic_events"
_AGENTIC_MAX_EVENTS = 64
_AGENTIC_EVENT_FIELDS = frozenset({
    "event", "schema_version", "run_id", "chat_id", "message_id", "action",
    "tools", "reason", "duration_ms", "errors", "ts", "outcome", "reaction",
    "target", "stage", "tool", "round", "status", "error_code", "counts",
    "source", "resolution", "reason_class", "latency_ms", "chars",
    "prompt_chars", "facts", "slice", "sources", "mode", "out_chars",
})


class RunSnapshotStore:
    """Ограниченный in-memory реестр снапшотов прогона (без persistence).

    Прецедент S9 ``_RunStore``: TTL + лимит записей; при рестарте теряется —
    «latest» без persistence (ограничение задокументировано в ADR-1026-10).
    Потокобезопасен (bot.py и web/app.py делят один процесс, но read-side
    может вызываться из другого потока/loop-таска).
    """

    def __init__(self, maxlen: int = 20, ttl_seconds: float = 900.0) -> None:
        self._lock = threading.Lock()
        self._items: "collections.OrderedDict[str, tuple[float, dict]]" = \
            collections.OrderedDict()
        self._maxlen = max(1, int(maxlen))
        self._ttl = float(ttl_seconds)

    def put(self, run_id, snapshot: dict) -> None:
        run_id = str(run_id or "")
        if not run_id or not isinstance(snapshot, dict):
            return
        now = time.monotonic()
        snapshot = dict(snapshot)
        with self._lock:
            prior = self._items.get(run_id)
            # A9: не терять агентные события, если поверх лёг новый снапшот
            # (record_run summary-пути) без `agentic_events`.
            if (prior is not None and _AGENTIC_KEY not in snapshot
                    and _AGENTIC_KEY in prior[1]):
                snapshot[_AGENTIC_KEY] = prior[1][_AGENTIC_KEY]
            self._items[run_id] = (now, snapshot)
            self._items.move_to_end(run_id)
            while len(self._items) > self._maxlen:
                self._items.popitem(last=False)

    def append_agentic(self, run_id, event: dict) -> None:
        """A9 (D1): аддитивно добавить агентное событие к снапшоту run_id.

        Создаёт/дополняет запись, сохраняя прочие поля; лимит событий — bounded.
        Fail-open: некорректный вход/ошибка не роняет вызывающий поток."""
        try:
            run_id = str(run_id or "")
            if not run_id or not isinstance(event, dict):
                return
            now = time.monotonic()
            with self._lock:
                prior = self._items.get(run_id)
                snapshot = dict(prior[1]) if prior is not None \
                    else {"run_id": run_id}
                events = list(snapshot.get(_AGENTIC_KEY) or [])
                events.append(dict(event))
                if len(events) > _AGENTIC_MAX_EVENTS:
                    events = events[-_AGENTIC_MAX_EVENTS:]
                snapshot[_AGENTIC_KEY] = events
                self._items[run_id] = (now, snapshot)
                self._items.move_to_end(run_id)
                while len(self._items) > self._maxlen:
                    self._items.popitem(last=False)
        except Exception:      # pragma: no cover - best-effort
            return

    def _fresh(self, now: float) -> None:
        if self._ttl <= 0:
            return
        stale = [k for k, (ts, _) in self._items.items()
                 if (now - ts) > self._ttl]
        for k in stale:
            self._items.pop(k, None)

    def get(self, run_id):
        run_id = str(run_id or "")
        if not run_id:
            return None
        with self._lock:
            self._fresh(time.monotonic())
            item = self._items.get(run_id)
            return dict(item[1]) if item is not None else None

    def latest_run_id(self):
        with self._lock:
            self._fresh(time.monotonic())
            if not self._items:
                return None
            return next(reversed(self._items))

    def size(self) -> int:
        with self._lock:
            self._fresh(time.monotonic())
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_store = RunSnapshotStore()

# Поля снапшота, которые переносятся из RunContext/метрик S1 (аддитивно).
_SNAPSHOT_FIELDS = (
    "run_id", "chat_id", "mode", "source_count", "saved_count",
    "restored_count", "drop_percent", "filter_duration_ms", "filter_status",
    "threads", "paragraphs", "cover_status", "format_channel",
    "format_status", "format_duration_ms", "status", "duration_ms",
    # S6 (D6): публикационный срез (только id/коды/числа — R17-safe).
    "publish_channel", "publish_status", "publish_duration_ms",
    "publish_message_id",
)


def record_run(*, run_id, **fields) -> None:
    """Зафиксировать снапшот прогона (fail-open; ничего не роняет).

    Принимает только известные R17-safe поля (числа/коды/строки статусов).
    Неизвестные ключи игнорируются — не расширяем поверхность утечки.
    """
    try:
        rid = str(run_id or "")
        if not rid:
            return
        snapshot = {"run_id": rid}
        for key in _SNAPSHOT_FIELDS:
            if key == "run_id":
                continue
            if key in fields:
                snapshot[key] = fields[key]
        _store.put(rid, snapshot)
    except Exception:      # pragma: no cover - best-effort, пайплайн не рвём
        return


def record_run_from_context(ctx, filter_metrics=None) -> None:
    """Аддитивная обёртка: снапшот из S7 ``RunContext`` + S1-метрик (D2).

    Duck-typed (без импорта RunContext — модуль остаётся чистым/тестируемым).
    ``drop_percent``/``filter_status``/``filter_duration_ms`` берутся из
    ``filter_metrics`` ЭТОГО прогона (по ``run_id``), чтобы не смешивать
    устаревший слот fail-open.
    """
    try:
        run_id = getattr(ctx, "run_id", None)
        if not run_id:
            return
        fm = dict(filter_metrics or {})
        same_run = fm.get("run_id") == run_id
        fields = {
            "chat_id": getattr(ctx, "chat_id", None),
            "mode": getattr(ctx, "mode", None),
            "source_count": getattr(ctx, "source_count", None),
            "saved_count": getattr(ctx, "saved_count", None),
            "restored_count": getattr(ctx, "restored_count", None),
            "threads": getattr(ctx, "threads", None),
            "paragraphs": getattr(ctx, "paragraphs", None),
            "cover_status": getattr(ctx, "cover_status", None),
            "status": getattr(ctx, "status", None),
            "duration_ms": _ctx_duration_ms(ctx),
            "drop_percent": fm.get("drop_percent") if same_run else None,
            "filter_status": fm.get("status") if same_run else None,
            "filter_duration_ms": fm.get("duration_ms") if same_run else None,
            "format_channel": getattr(ctx, "format_channel", None),
            "format_status": getattr(ctx, "format_status", None),
            "format_duration_ms": getattr(ctx, "format_duration_ms", None),
            "publish_channel": getattr(ctx, "publish_channel", None),
            "publish_status": getattr(ctx, "publish_status", None),
            "publish_duration_ms": getattr(ctx, "publish_duration_ms", None),
            "publish_message_id": getattr(ctx, "publish_message_id", None),
        }
        record_run(run_id=run_id, **fields)
    except Exception:      # pragma: no cover - best-effort
        return


def _ctx_duration_ms(ctx) -> float | None:
    try:
        value = ctx.duration_ms()
        return float(value) if value is not None else None
    except Exception:      # pragma: no cover - защитная ветка
        return None


def get_run(run_id):
    return _store.get(run_id)


def latest_run_id():
    return _store.latest_run_id()


def store_size() -> int:
    return _store.size()


def reset() -> None:
    """Полный сброс реестра (для тестов/детерминизма)."""
    _store.clear()


# ── A9: агентные события в существующем store (D1/D5/D7) ───────────────────

def record_agentic_event(event, **fields) -> None:
    """Аддитивно записать агентное событие §49 в существующий in-memory store.

    Только известные R17-safe поля (неизвестные игнорируются — не расширяем
    поверхность утечки). Без ``run_id`` (воркер ``ANTI_CLICHE_*``) событие НЕ
    попадает в чат-граф (D11) — остаётся только structured-log. Fail-open."""
    try:
        name = str(event or "")
        if not name:
            return
        safe = {k: v for k, v in fields.items()
                if k in _AGENTIC_EVENT_FIELDS}
        safe["event"] = name
        rid = str(fields.get("run_id") or "")
        if not rid:
            return
        _store.append_agentic(rid, safe)
    except Exception:      # pragma: no cover - best-effort
        return


def get_agentic_events(run_id) -> list:
    """Агентные события прогона (пусто → ``[]``; не бросает)."""
    try:
        snapshot = _store.get(run_id)
        if not isinstance(snapshot, dict):
            return []
        events = snapshot.get(_AGENTIC_KEY)
        return list(events) if isinstance(events, list) else []
    except Exception:      # pragma: no cover - защитная ветка
        return []


# tool-имя → §51-этап (подстроки; R17-safe имена инструментов).
_AGENTIC_TOOL_STAGE_PATTERNS = (
    (STAGE_MEMORY_LOOKUP, ("user_context", "memory", "get_user")),
    (STAGE_RAG, ("rag", "knowledge", "search_knowledge")),
    (STAGE_WEB_EXTRACTION, ("web", "fetch_article", "extract", "download",
                            "summarize_video", "transcribe")),
    (STAGE_FACTCHECK, ("factcheck", "fact_check", "fact-check")),
)


def _stage_for_tool(name) -> str | None:
    low = str(name or "").lower()
    if not low:
        return None
    for stage, patterns in _AGENTIC_TOOL_STAGE_PATTERNS:
        if any(pattern in low for pattern in patterns):
            return stage
    return None


_AGENTIC_METRIC_KEYS = (
    "action", "reason", "tool", "round", "status", "error_code", "outcome",
    "reaction", "resolution", "sources", "facts", "slice", "prompt_chars",
    "latency_ms", "source", "reason_class", "out_chars", "duration_ms",
)


def _agentic_event_metrics(event: dict) -> dict:
    metrics = {}
    for key in _AGENTIC_METRIC_KEYS:
        value = event.get(key)
        if value is not None:
            metrics[key] = value
    return metrics


def _agentic_text_generation_node(run_id, llm_rows) -> dict | None:
    """Узел ``text_generation`` (kind ``llm``) — ТОЛЬКО из реальных строк
    ``llm_usage_events`` (D7/D8): токены/стоимость реальные, ничего не
    выдумывается. Нет реальных LLM-строк → ``None`` (нет узла, §30)."""
    rows = [row for row in (llm_rows or []) if isinstance(row, dict)
            and STEP_KIND.get(_str_or_none(row.get("step")) or "") == KIND_LLM]
    if not rows:
        return None
    total_in = total_out = 0
    total_cost = 0.0
    known = True
    model = None
    for row in rows:
        if row.get("price_known") is not True:
            known = False
        total_in += _int_or_none(row.get("input_tokens")) or 0
        total_out += _int_or_none(row.get("output_tokens")) or 0
        if row.get("price_known") is True:
            total_cost += _num_or_none(row.get("cost_usd")) or 0.0
        model = _str_or_none(row.get("model")) or model
    return _node(
        run_id, STAGE_TEXT_GENERATION, KIND_LLM,
        stage_label=STAGE_LABELS[STAGE_TEXT_GENERATION], status="ok",
        model=model, input_tokens=total_in, output_tokens=total_out,
        cost=(round(total_cost, 6) if known else None), price_known=known,
        metadata={"kindGroup": KIND_LLM, "agentic": True})


def _build_agentic_nodes(run_id, events, llm_rows) -> list:
    """Собрать 9 §51-этапов из агентных событий + реальных LLM-строк (D7/D8).

    Каждый этап → узел только при наличии реального события/строки. Узлы
    ``algorithm``/``tool`` несут честный ``None`` вместо LLM-токенов/стоимости.
    Связи ставятся по каноническому ``AGENTIC_STAGE_ORDER`` (``_link_sequence``).
    """
    decision = None
    by_stage: dict = {}
    for event in (events or []):
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "")
        if name == "DECISION_COMPLETE":
            decision = event
        elif name == "DECISION_START" and decision is None:
            decision = event
        elif name in ("TOOL_CALL_COMPLETE", "TOOL_CALL_FAILED"):
            stage = _stage_for_tool(event.get("tool"))
            if stage:
                by_stage[stage] = event
        elif name == "IMAGE_CONTEXT_RESOLVED":
            by_stage[STAGE_IMAGE_PROMPT] = event
        elif name.startswith("IMAGE_GENERATION_"):
            by_stage[STAGE_IMAGE_GENERATION] = event
        elif name == "REACTION_SENT":
            by_stage[STAGE_REACTION] = event

    nodes: list = []
    if decision is not None:
        nodes.append(_node(
            run_id, STAGE_DECISION, KIND_ALGORITHM,
            stage_label=STAGE_LABELS[STAGE_DECISION], status="ok",
            duration_ms=_num_or_none(decision.get("duration_ms")),
            metrics=_agentic_event_metrics(decision),
            metadata={"kindGroup": KIND_ALGORITHM, "agentic": True}))
    for stage in AGENTIC_STAGE_ORDER:
        if stage in (STAGE_DECISION, STAGE_TEXT_GENERATION):
            continue
        event = by_stage.get(stage)
        if event is None:
            continue
        kind = STEP_KIND.get(stage, KIND_OTHER)
        name = str(event.get("event") or "")
        if event.get("status") is not None:
            status = str(event.get("status"))
        elif name.endswith("_FAILED") or name == "TOOL_CALL_FAILED":
            status = "failed"
        else:
            status = "ok"
        nodes.append(_node(
            run_id, stage, kind, stage_label=STAGE_LABELS[stage],
            status=status,
            duration_ms=_num_or_none(event.get("duration_ms")
                                     or event.get("latency_ms")),
            metrics=_agentic_event_metrics(event),
            metadata={"kindGroup": kind, "agentic": True,
                      "tool": event.get("tool")}))
    text_generation = _agentic_text_generation_node(run_id, llm_rows)
    if text_generation is not None:
        nodes.append(text_generation)
    nodes.sort(key=lambda node: AGENTIC_STAGE_ORDER.index(node["stageKey"]))
    return nodes


# ── нормализация: raw sources → canonical ExecutionNode (§23/§24) ───────────

def _num_or_none(value):
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value):
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _node(run_id, stage_key, kind, *, stage_label=None, status="unknown",
          model=None, provider=None, input_tokens=None, output_tokens=None,
          cost=None, price_known=False, duration_ms=None, metrics=None,
          metadata=None, started_at=None, finished_at=None):
    """Канонический ``ExecutionNode``-shape (§23). Недоступное → ``None``."""
    return {
        "id": f"{run_id}:{stage_key}",
        "runId": run_id,
        "parentIds": [],
        "kind": kind,
        "stageKey": stage_key,
        "stageLabel": stage_label or STEP_LABEL.get(stage_key, stage_key),
        "status": status or "unknown",
        "provider": provider,
        "model": model,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cost": cost,
        "costCurrency": "USD" if cost is not None else None,
        "priceKnown": bool(price_known),
        "durationMs": duration_ms,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "metrics": metrics,
        "metadata": metadata or {},
    }


def algorithm_node(run_id, snapshot) -> dict | None:
    """Узел ``algorithm`` (Filter) — ТОЛЬКО реальные метрики S1 (§24/D4).

    Нет данных этапа (``filter_status``/``source_count``/``drop_percent``) →
    ``None`` (нет узла, §25/§30). LLM-токены/стоимость здесь **никогда** не
    выставляются (§24 — не выдумывать LLM-данные для algorithm).
    """
    if not isinstance(snapshot, dict):
        return None
    source_count = _int_or_none(snapshot.get("source_count"))
    saved_count = _int_or_none(snapshot.get("saved_count"))
    restored_count = _int_or_none(snapshot.get("restored_count"))
    drop_percent = _num_or_none(snapshot.get("drop_percent"))
    status = _str_or_none(snapshot.get("filter_status"))
    duration_ms = _num_or_none(snapshot.get("filter_duration_ms"))
    if (status is None and source_count is None and saved_count is None
            and drop_percent is None and duration_ms is None):
        return None
    return _node(
        run_id, STAGE_FILTER, KIND_ALGORITHM, stage_label=STAGE_LABELS[STAGE_FILTER],
        status=status or "unknown", duration_ms=duration_ms,
        metrics={
            "source_count": source_count,
            "saved_count": saved_count,
            "restored_count": restored_count,
            "drop_percent": drop_percent,
            "status": status,
        },
        metadata={"kindGroup": KIND_ALGORITHM},
    )


def format_node(run_id, snapshot) -> dict | None:
    """Узел ``format`` (Formatting) — реальное состояние форматирования (§24)."""
    if not isinstance(snapshot, dict):
        return None
    channel = _str_or_none(snapshot.get("format_channel"))
    status = _str_or_none(snapshot.get("format_status"))
    duration_ms = _num_or_none(snapshot.get("format_duration_ms"))
    paragraphs = _int_or_none(snapshot.get("paragraphs"))
    if channel is None and status is None and duration_ms is None:
        return None
    return _node(
        run_id, STAGE_FORMAT, KIND_FORMAT, stage_label=STAGE_LABELS[STAGE_FORMAT],
        status=status or "unknown", duration_ms=duration_ms,
        metrics={"channel": channel, "paragraphs": paragraphs, "status": status},
        metadata={"kindGroup": KIND_FORMAT},
    )


def publish_node(run_id, snapshot) -> dict | None:
    """Узел ``publish`` (Публикация) — ТОЛЬКО реальные данные снапшота (S6/D6).

    Нет данных публикации (``publish_status``/``publish_channel``/
    ``publish_duration_ms``/``publish_message_id``) → ``None`` (нет узла, §30).
    LLM-токены/стоимость здесь **никогда** не выставляются; ``status`` —
    реальный статус публикации (``ok``/``failed``); ``message_id`` — id
    первого сообщения (R17-safe).
    """
    if not isinstance(snapshot, dict):
        return None
    channel = _str_or_none(snapshot.get("publish_channel"))
    status = _str_or_none(snapshot.get("publish_status"))
    duration_ms = _num_or_none(snapshot.get("publish_duration_ms"))
    message_id = _int_or_none(snapshot.get("publish_message_id"))
    if channel is None and status is None and duration_ms is None \
            and message_id is None:
        return None
    return _node(
        run_id, STAGE_PUBLISH, KIND_PUBLISH,
        stage_label=STAGE_LABELS[STAGE_PUBLISH],
        status=status or "unknown", duration_ms=duration_ms,
        metrics={"channel": channel, "message_id": message_id,
                 "status": status},
        metadata={"kindGroup": KIND_PUBLISH},
    )


def publication_status_of(snapshot) -> str | None:
    """§112/D6: реальный ``publication_status`` (нет данных → ``None``).

    ``published_rich``/``published_text`` — успешная публикация соответствующим
    каналом; ``failed`` — публикация упала; ``skipped`` — прогон завершился
    до публикации (empty/degraded/failed, попытки публикации не было).
    Никакого ``gated``/выдуманного «опубликовано».
    """
    if not isinstance(snapshot, dict):
        return None
    status = _str_or_none(snapshot.get("publish_status"))
    channel = _str_or_none(snapshot.get("publish_channel"))
    if status == "ok":
        if channel == "rich":
            return PUBLISHED_RICH
        if channel == "text":
            return PUBLISHED_TEXT
        return None
    if status == "failed":
        return PUBLICATION_FAILED
    if _str_or_none(snapshot.get("status")) in ("empty", "degraded", "failed"):
        return PUBLICATION_SKIPPED
    return None


def llm_node(run_id, row) -> dict | None:
    """Узел ``llm`` из реальной строки ``llm_usage_events`` (§24/D4).

    ``model``/токены — реальные; ``cost`` — только при ``price_known=true``
    (иначе ``None`` → «Нет данных», не ``$0``); ``provider``/``durationMs`` —
    ``None`` (нет в данных). ``publication``-строки LLM-узлов не создают:
    публикация — не LLM-вызов, её узел строится из снапшота (`publish_node`).
    """
    if not isinstance(row, dict):
        return None
    step = _str_or_none(row.get("step")) or ""
    kind = STEP_KIND.get(step, KIND_OTHER)
    if kind == KIND_PUBLISH:        # S6: публикация не LLM-событие
        return None
    if kind == KIND_OTHER and not step:
        return None                 # пустой шаг → нет узла (§30)
    price_known = row.get("price_known") is True
    stage_label = STEP_LABEL.get(step)
    if stage_label is None and step:
        stage_label = f"Шаг: {step}"
    if step == "tool" and _str_or_none(row.get("tool_name")):
        stage_label = f"Инструмент: {row.get('tool_name')}"
    cost = _num_or_none(row.get("cost_usd")) if price_known else None
    return _node(
        run_id, step or KIND_OTHER, kind, stage_label=stage_label,
        status="unknown", model=_str_or_none(row.get("model")),
        input_tokens=_int_or_none(row.get("input_tokens")),
        output_tokens=_int_or_none(row.get("output_tokens")),
        cost=cost, price_known=price_known,
        metadata={
            "tokensEstimated": bool(row.get("tokens_estimated")),
            "module": _str_or_none(row.get("module")),
            "source": _str_or_none(row.get("source")),
            "toolName": _str_or_none(row.get("tool_name")),
        },
        started_at=_str_or_none(row.get("ts")),
    )


def _link_sequence(nodes: list) -> list:
    """Подтверждённая линейная последовательность одного ``run_id`` (D6).

    Связь ставится только между **соседними реальными** этапами канонического
    порядка (filter → L1 → L2 → formatting): каждый узел ссылается на
    предыдущий реальный. Ветвление не достраивается; у первого узла
    ``parentIds=[]``. Если этап отсутствует — его пропуск не «склеивает»
    несоседние этапы (связь с ближайшим предшествующим реальным узлом).
    """
    prev_id = None
    for node in nodes:
        node["parentIds"] = [prev_id] if prev_id else []
        prev_id = node["id"]
    return nodes


def build_graph(run_id, snapshot, llm_rows) -> dict:
    """Собрать нормализованный граф одного прогона (§25/D3/D6).

    Порядок узлов — канонический: filter → LLM (L1 → L2) → formatting →
    publication (S6/D6). ``llm_rows`` — уже прочитанные строки
    ``llm_usage_events`` (второй сборщик не создаётся). Нет ни одного
    реального узла → ``empty=true``.
    """
    run_id = str(run_id or "")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    agentic_events = snapshot.get(_AGENTIC_KEY)
    if not isinstance(agentic_events, list):
        agentic_events = []
    nodes: list = []
    llm_nodes: list = []
    if agentic_events:
        # A9 (D7): агентный прогон — 9 §51-этапов; legacy per-step LLM-узлы
        # заменены единым `text_generation`-узлом (без дублей одного вызова).
        nodes.extend(_build_agentic_nodes(run_id, agentic_events, llm_rows))
    else:
        alg = algorithm_node(run_id, snapshot)
        if alg is not None:
            nodes.append(alg)
        # LLM-узлы: стабильный порядок — L1 перед L2, legacy — по ts.
        for row in (llm_rows or []):
            node = llm_node(run_id, row)
            if node is not None:
                llm_nodes.append(node)
        llm_nodes.sort(key=lambda n: (STAGE_ORDER.index(n["stageKey"])
                                      if n["stageKey"] in STAGE_ORDER else 99))
        nodes.extend(llm_nodes)
        fmt = format_node(run_id, snapshot)
        if fmt is not None:
            nodes.append(fmt)
        pub = publish_node(run_id, snapshot)
        if pub is not None:
            nodes.append(pub)
    _link_sequence(nodes)
    edges = [{"from": n["parentIds"][0], "to": n["id"]}
             for n in nodes if n["parentIds"]]
    started_at = next((n["startedAt"] for n in llm_nodes
                       if n.get("startedAt")), None)
    return {
        "run_id": run_id or None,
        "started_at": started_at,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics_block(snapshot, llm_rows),
        "publication_status": publication_status_of(snapshot),
        "empty": len(nodes) == 0,
    }


# ── §112-метрики (D4) ───────────────────────────────────────────────────────

def _usage_by_step(llm_rows) -> dict:
    """Агрегат токенов/стоимости L1/L2 из строк ``llm_usage_events``.

    Стоимость слота известна ТОЛЬКО если ``price_known`` у всех его событий;
    иначе ``None`` («Нет данных», не ``$0``). Второй учёт не создаётся —
    используется тот же источник, что и карта.
    """
    slots = {"l1": None, "l2": None}
    total_in = total_out = 0
    total_cost = 0.0
    total_known = True
    for row in (llm_rows or []):
        if not isinstance(row, dict):
            continue
        slot = _USAGE_STEP_MAP.get(_str_or_none(row.get("step")) or "")
        if slot is None:
            continue
        known = row.get("price_known") is True
        in_tokens = _int_or_none(row.get("input_tokens")) or 0
        out_tokens = _int_or_none(row.get("output_tokens")) or 0
        slots[slot] = {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "cost_usd": _num_or_none(row.get("cost_usd")) if known else None,
            "price_known": known,
            "tokens_estimated": bool(row.get("tokens_estimated")),
        }
        total_in += in_tokens
        total_out += out_tokens
        if known:
            total_cost += _num_or_none(row.get("cost_usd")) or 0.0
        else:
            total_known = False
    both_steps = bool(slots["l1"]) and bool(slots["l2"])
    total = {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": round(total_cost, 6) if (total_known and both_steps)
        else None,
        "price_known": bool(total_known and both_steps),
    }
    return {"l1": slots["l1"], "l2": slots["l2"], "total": total}


def metrics_block(snapshot, llm_rows) -> dict:
    """§112: полный перечень метрик (§112/REQ-S8-09) — честные значения.

    Стоимость неизвестна → ``None`` («Нет данных»); ``publication_status`` —
    реальный (S6/D6; нет данных → ``None``). Токены/стоимость L1/L2 — единый
    учёт S1–S5/S9.
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    usage = _usage_by_step(llm_rows)
    return {
        "source_count": _int_or_none(snapshot.get("source_count")),
        "filtered_count": _int_or_none(snapshot.get("saved_count")),
        "restored_count": _int_or_none(snapshot.get("restored_count")),
        "drop_percent": _num_or_none(snapshot.get("drop_percent")),
        "threads_count": _int_or_none(snapshot.get("threads")),
        "tokens": {
            "l1": usage["l1"],
            "l2": usage["l2"],
            "total": usage["total"],
        },
        "cost": {
            "l1": (usage["l1"] or {}).get("cost_usd") if usage["l1"] else None,
            "l2": (usage["l2"] or {}).get("cost_usd") if usage["l2"] else None,
            "total": usage["total"]["cost_usd"],
        },
        "duration_ms": _num_or_none(snapshot.get("duration_ms")),
        "cover_status": _str_or_none(snapshot.get("cover_status")),
        "publication_status": publication_status_of(snapshot),
        "run_status": _str_or_none(snapshot.get("status")),
    }
