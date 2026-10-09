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
    → ``None``, AMEND ADR-1026-10 D1/D4/D8, S6);
  * MCA-23 (P2-B, §33-§36): planned-слой Direct-ответа (Pre-execution план
    ResponsePlan → ``set_planned``) + planned-vs-actual view в
    ``build_graph`` (совпало/отклонилось/не выполнилось/лишнее); in-memory,
    без DDL, без второй telemetry-модели.

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
# ASAP 7 (F2, §8/§18): pre-tool L1 Planner Direct — отдельный этап
# (usage step="l1_planner" + agentic L1_PLAN). Kind — llm (это LLM-вызов).
STAGE_L1_PLANNER = "l1_planner"

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
    # ASAP 7 (F2, §18): узел «L1 Planner» карты Direct-ответа.
    STAGE_L1_PLANNER: "L1 Planner",
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
    # ASAP 7 (F2, §18): L1 Planner — LLM-вызов (usage step="l1_planner").
    STAGE_L1_PLANNER: KIND_LLM,
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
    STAGE_L1_PLANNER: STAGE_LABELS[STAGE_L1_PLANNER],
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
# MCA-23 (P2-B, §33 current_task): planned-слой Direct-ответа живёт в ТОМ ЖЕ
# in-memory снапшоте (ключ `planned`), отдельной telemetry-модели НЕТ
# (§33: «Не строить отдельную вторую telemetry model»). Без DDL.
_PLANNED_KEY = "planned"
_PLANNED_MAX_NODES = 8
# R17-whitelist полей planned-узла: только enum/коды/шаблоны причин —
# никаких промптов/сырых текстов.
_PLANNED_NODE_FIELDS = frozenset({
    "key", "label", "title", "expected", "axes", "reason_ru", "planned",
})
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
            # MCA-23 (P2-B): не терять planned-слой при перезаписи снапшота
            # (та же merge-семантика, что у агентных событий выше).
            if (prior is not None and _PLANNED_KEY not in snapshot
                    and _PLANNED_KEY in prior[1]):
                snapshot[_PLANNED_KEY] = prior[1][_PLANNED_KEY]
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

    def put_planned(self, run_id, payload: dict) -> None:
        """MCA-23 (P2-B §33): сохранить planned-слой прогона (in-memory).

        Merge-семантика ``append_agentic``: создаёт/дополняет запись, сохраняя
        прочие поля (агентные события не теряются). Fail-open."""
        try:
            run_id = str(run_id or "")
            if not run_id or not isinstance(payload, dict):
                return
            now = time.monotonic()
            with self._lock:
                prior = self._items.get(run_id)
                snapshot = dict(prior[1]) if prior is not None \
                    else {"run_id": run_id}
                snapshot[_PLANNED_KEY] = dict(payload)
                self._items[run_id] = (now, snapshot)
                self._items.move_to_end(run_id)
                while len(self._items) > self._maxlen:
                    self._items.popitem(last=False)
        except Exception:      # pragma: no cover - best-effort
            return

    def snapshots(self) -> list:
        """Свежие снапшоты (новые → старые; окно агрегатов P2-B ≤ maxlen)."""
        with self._lock:
            self._fresh(time.monotonic())
            return [dict(item[1])
                    for item in (self._items[k]
                                 for k in reversed(self._items))]

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
    # ASAP-4 волна E (T-4440/T-4441, spec §5 E.1, §61.6): coverage —
    # first-class поля run state + разделённые оси publication/health
    # (§50.53) + grade/fallback. Только числа/коды/enum (R17).
    "source_total", "source_considered", "source_coverage",
    "pipeline_health", "package_grade", "fallback", "model", "provider",
    "reason",
    # Волна E: bounded-проекция stage events (§50.54; список dict'ов,
    # уже спроецированный на R17-safe ключи в record_run_from_context).
    "stage_events",
)

# Волна E: bounded-проекция append-only stage events (§50.54) в снапшот —
# R17-safe ключи (числа/коды/id), последние 24 события (лимит реестра).
_STAGE_EVENT_KEYS = frozenset({
    "stage", "attempt", "status", "reason_code", "started_at", "finished_at",
    "input_count", "output_count", "provider", "model", "fallback_target",
    "repair_target",
    # ASAP 4.4 Z5 (T-4877): diagnostics L2 Reviewer/Revision — коды/числа/id
    # (без raw text/prompt/секретов).
    "review_attempt", "verdict", "finding_codes", "blocking_count",
    "paragraph_ids", "revision_target", "revision_result",
    "revision_failure_reason", "deterministic_validation_codes",
})
_STAGE_EVENTS_MAX = 24


def _project_stage_events(events) -> list:
    """Последние ≤24 stage events, только R17-safe ключи (fail-open)."""
    try:
        rows = [dict(e) for e in (events or []) if isinstance(e, dict)]
        projected = [{k: row.get(k) for k in _STAGE_EVENT_KEYS
                      if row.get(k) is not None} for row in rows]
        return projected[-_STAGE_EVENTS_MAX:]
    except Exception:      # pragma: no cover - best-effort
        return []


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
            # Волна E (§61.6/§50.53): coverage/health — first-class run state.
            "source_total": getattr(ctx, "source_total", None),
            "source_considered": getattr(ctx, "source_considered", None),
            "source_coverage": getattr(ctx, "source_coverage", None),
            "pipeline_health": getattr(ctx, "pipeline_health", None),
            "package_grade": getattr(ctx, "package_grade", None),
            "fallback": getattr(ctx, "fallback", None),
            "model": getattr(ctx, "model", None),
            "provider": getattr(ctx, "provider", None),
            "reason": getattr(ctx, "reason", None),
            "stage_events": _project_stage_events(
                getattr(ctx, "stage_events", None)),
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


# ── ASAP 7 (F2, §18): L1 Planner — факты и узел карты Direct-ответа ────────

def _l1_facts_from_events(events) -> dict:
    """Факты L1 прогона ТОЛЬКО из реальных событий (R17-safe).

    ``requested`` — capabilities из ``L1_PLAN``; ``rejected`` — пары
    (capability, reason) из ``L1_CAPABILITY_REJECTED``; ``resolved`` —
    requested минус rejected (честная деривация: никаких выдуманных
    resolved). Пусто (событий нет / legacy-прогон) → ``{}``."""
    plan_event = None
    rejected: list = []
    for event in (events or []):
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "")
        if name == "L1_PLAN":
            if plan_event is None or (event.get("ts") or 0) >= \
                    (plan_event.get("ts") or 0):
                plan_event = event
        elif name == "L1_CAPABILITY_REJECTED":
            cap = str(event.get("capability") or "")
            if cap:
                rejected.append((cap, str(event.get("reason") or "")))
    if plan_event is None:
        return {}
    requested_raw = plan_event.get("capabilities") or ""
    requested = [c for c in str(requested_raw).split(",") if c]
    rejected_caps = {cap for cap, _ in rejected}
    resolved_from_event = [t for t in str(plan_event.get("tools") or "")
                           .split(",") if t]
    if resolved_from_event:
        # F1 отдаёт фактический resolved-подсет (tools) — реальное данное.
        resolved = resolved_from_event
    else:
        # REV-2 (a): F1 пока отдаёт resolved=() → честная деривация
        # requested минус rejected (никаких выдуманных resolved).
        resolved = [c for c in requested if c not in rejected_caps]
    facts = {
        "action": _plan_axis(plan_event.get("action"),
                             ("reply", "react", "silent", "tool")),
        "response_act": _str_or_none(plan_event.get("response_act")) or "",
        "extent": _str_or_none(plan_event.get("extent")) or "",
        "tone": _str_or_none(plan_event.get("tone")) or "",
        "bucket": _str_or_none(plan_event.get("bucket")) or "",
        "source": _str_or_none(plan_event.get("source")) or "",
        "fallback": _str_or_none(plan_event.get("fallback")) or "",
        "inherited": bool(plan_event.get("inherited")),
        "confidence": _num_or_none(plan_event.get("confidence")),
        "latency_ms": _num_or_none(plan_event.get("latency_ms")),
        "input_chars": _int_or_none(plan_event.get("input_chars")),
        "requested": requested,
        "resolved": resolved,
        "rejected": [(cap, reason) for cap, reason in rejected
                     if cap in requested or cap],
    }
    return facts


def _l1_planner_usage(llm_rows) -> dict | None:
    """Токены/модель/стоимость step="l1_planner" из реальных usage-строк."""
    rows = [row for row in (llm_rows or []) if isinstance(row, dict)
            and _str_or_none(row.get("step")) == STAGE_L1_PLANNER]
    if not rows:
        return None
    total_in = total_out = 0
    cost = 0.0
    known = True
    model = None
    for row in rows:
        if row.get("price_known") is not True:
            known = False
        total_in += _int_or_none(row.get("input_tokens")) or 0
        total_out += _int_or_none(row.get("output_tokens")) or 0
        if row.get("price_known") is True:
            cost += _num_or_none(row.get("cost_usd")) or 0.0
        model = _str_or_none(row.get("model")) or model
    return {"model": model, "input_tokens": total_in,
            "output_tokens": total_out,
            "cost": (round(cost, 6) if known else None),
            "price_known": known}


def _agentic_l1_planner_node(run_id, events, llm_rows) -> dict | None:
    """Узел ``l1_planner`` (kind ``llm``) — ТОЛЬКО из реальных данных (§30):
    agentic ``L1_PLAN``/``L1_CAPABILITY_REJECTED`` + usage-строки
    step="l1_planner". Нет ни события, ни usage-строки → ``None``
    (legacy-прогон/план не строился). Метрики: план-оси §18 (action/
    response_act/extent/tone/capabilities requested-resolved/bucket/model/
    inherited/fallback)."""
    facts = _l1_facts_from_events(events)
    usage = _l1_planner_usage(llm_rows)
    if not facts and usage is None:
        return None
    metrics: dict = {}
    if facts:
        for key in ("action", "response_act", "extent", "tone", "bucket",
                    "source", "fallback", "confidence", "latency_ms",
                    "input_chars"):
            value = facts.get(key)
            if value not in (None, ""):
                metrics[key] = value
        metrics["inherited"] = bool(facts.get("inherited"))
        if facts.get("requested"):
            metrics["capabilities"] = ",".join(facts["requested"])
        if facts.get("resolved"):
            metrics["tools_resolved"] = ",".join(facts["resolved"])
        if facts.get("rejected"):
            metrics["tools_rejected"] = ",".join(
                cap for cap, _ in facts["rejected"])
    model = (usage or {}).get("model")
    if model:
        metrics["model"] = model
    status = "ok"
    if facts.get("fallback") == "deterministic":
        status = "degraded"
    return _node(
        run_id, STAGE_L1_PLANNER, KIND_LLM,
        stage_label=STAGE_LABELS[STAGE_L1_PLANNER], status=status,
        model=model,
        input_tokens=(usage or {}).get("input_tokens"),
        output_tokens=(usage or {}).get("output_tokens"),
        cost=(usage or {}).get("cost"),
        price_known=bool((usage or {}).get("price_known")),
        duration_ms=facts.get("latency_ms") if facts else None,
        metrics=metrics or None,
        metadata={"kindGroup": KIND_LLM, "agentic": True})


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
    # ASAP 7 (F2, §18): узел L1 Planner — ПЕРВЫЙ в цепочке Direct-прогона
    # (пре-tool решение). В AGENTIC_STAGE_ORDER не входит (это Direct-этап,
    # не §51-агентный), поэтому прикрепляется до сортировки §51-узлов.
    l1_node = _agentic_l1_planner_node(run_id, events, llm_rows)
    if l1_node is not None:
        nodes.insert(0, l1_node)
    return nodes


# ── MCA-23 (P2-B): planned-слой Direct-ответа (§33-§36 current_task) ────────
# Pre-execution план (ResponsePlan, детерминированная классификация ДО LLM)
# → PlannedGraph → сравнение с RuntimeGraph. UI-контракт §34: цепочка
# TRIGGER → PLANNER → TOOLS → WRITER → DELIVERY → ИТОГ; REACT/SILENT не
# рисуют фиктивный Writer. Сравнение §33: совпало / отклонилось / не
# выполнилось / лишнее. Человекочитаемые причины §36 — ШАБЛОНЫ по осям
# плана (никакого сырого текста пользователя, R17).

PLAN_TRIGGER = "trigger"
PLAN_PLANNER = "planner"
PLAN_TOOLS = "tools"
PLAN_WRITER = "writer"
PLAN_DELIVERY = "delivery"
PLAN_OUTCOME = "outcome"

PLAN_LABELS = {
    PLAN_TRIGGER: "TRIGGER",
    PLAN_PLANNER: "PLANNER",
    PLAN_TOOLS: "TOOLS",
    PLAN_WRITER: "WRITER",
    PLAN_DELIVERY: "DELIVERY",
    PLAN_OUTCOME: "ИТОГ",
}
PLAN_TITLES = {
    PLAN_TRIGGER: "Триггер",
    PLAN_PLANNER: "Планировщик",
    PLAN_TOOLS: "Инструменты",
    PLAN_WRITER: "Writer",
    PLAN_DELIVERY: "Доставка",
    PLAN_OUTCOME: "Итог",
}

# Сравнение planned-vs-actual (§33): честные 4 исхода.
CMP_MATCH = "match"            # совпало
CMP_DEVIATED = "deviated"      # отклонилось
CMP_MISSING = "missing"        # не выполнилось
CMP_EXTRA = "extra"            # лишнее (не планировалось)
CMP_STATUS_LABELS = {
    CMP_MATCH: "Совпало",
    CMP_DEVIATED: "Отклонилось",
    CMP_MISSING: "Не выполнилось",
    CMP_EXTRA: "Лишнее",
}

# Human-лейблы осей плана (§34/§36; значения response_extent.TASK_KINDS и др.)
TASK_KIND_LABELS = {
    "social_chat": "болтовня", "direct_answer": "прямой ответ",
    "explanation": "объяснение", "creative_writing": "творческий текст",
    "research": "исследование", "comparison": "сравнение",
    "summarization": "выжимка", "historical_recall": "ответ из памяти",
    "media_download": "скачивание медиа", "media_generation": "генерация изображения",
    "transcription": "транскрибация",
}
EXTENT_LABELS = {
    "micro": "микро", "compact": "коротко", "normal": "обычный объём",
    "detailed": "подробно", "longform": "длинный текст",
    "exhaustive": "исчерпывающе",
}
STRUCTURE_LABELS = {
    "chat": "чат", "answer": "ответ", "explanation": "объяснение",
    "story": "история", "summary": "саммари", "comparison": "сравнение",
    "report": "отчёт", "steps": "по шагам",
}
TOOL_POLICY_LABELS = {
    "none": "без инструментов", "auto": "по необходимости",
    "required": "нужны инструменты", "constrained": "ограниченный набор",
}
DELIVERY_LABELS = {
    "plain": "обычное сообщение", "rich": "Rich-карточка", "media": "медиа",
    "none": "без текста",
}
ACTION_LABELS = {
    "reply": "ответ текстом", "react": "реакция", "silent": "молчание",
    "tool": "работа через инструменты",
}

# §36: человекочитаемые причины — шаблоны по осям плана (без raw text).
_EXTENT_REASON_RU = {
    "micro": "Запрос предполагает короткий ответ («да или нет») — "
             "планируется минимальный объём.",
    "compact": "Обычный разговорный ответ — без развёрнутой структуры.",
    "normal": "Стандартная полнота ответа.",
    "detailed": "Запрос просит подробный разбор — снимается cap «1–2 "
                "предложения», планируется полный объём.",
    "longform": "Запрос на большой связный текст — cap снят, планируется "
                "законченное произведение.",
    "exhaustive": "Запрос на исчерпывающий разбор — максимальная полнота.",
}
_TASK_REASON_RU = {
    "creative_writing": "Почему tools не использовались? Запрос творческий — "
                        "внешние данные не требовались.",
    "research": "Запрос исследовательский — планируются инструменты сбора "
                "данных.",
    "comparison": "Сравнение — ожидается несколько источников/сущностей.",
    "summarization": "Нужна выжимка — планируется чтение источника.",
    "media_download": "Запрос на скачивание медиа — нужен media-инструмент.",
    "media_generation": "Запрос на изображение — планируется генерация.",
    "transcription": "Запрос на расшифровку — нужен media-инструмент.",
    "historical_recall": "Вопрос о прошлом — планируется поиск в памяти.",
    "explanation": "Объяснение по теме — инструменты по необходимости.",
    "social_chat": "Разговорный запрос — внешние данные не требуются.",
    "direct_answer": "Прямой вопрос — короткий фактологический ответ.",
}
_TOOL_POLICY_REASON_RU = {
    "none": "Почему tools не использовались? План не требует внешних данных.",
    "auto": "Инструменты по необходимости — модель решает в ходе ответа.",
    "required": "Для ответа нужны инструменты (ссылки/поиск/медиа).",
    "constrained": "Инструменты ограничены планом.",
}
_DELIVERY_REASON_RU = {
    "plain": "Обычное сообщение: ответ простой или короткий.",
    "rich": "Почему Rich? Ответ состоит из нескольких разделов — planned "
            "Rich-карточка.",
    "media": "Ответ с медиа (изображение/видео/файл).",
    "none": "Текстовый ответ не планируется (реакция/молчание).",
}


def _plan_axis(value, valid) -> str:
    """Валидная ось плана или ``""`` (fail-open, без импорта response_extent)."""
    candidate = str(value or "").strip().lower()
    return candidate if candidate in valid else ""


def _planned_node(key: str, expected: str, *, axes=None, reason_ru: str = ""
                  ) -> dict:
    """R17-safe planned-узел §34 (только enum/коды/шаблоны причин)."""
    node = {
        "key": key,
        "label": PLAN_LABELS.get(key, key),
        "title": PLAN_TITLES.get(key, key),
        "expected": str(expected or ""),
        "reason_ru": str(reason_ru or ""),
    }
    if isinstance(axes, dict) and axes:
        node["axes"] = {k: v for k, v in axes.items()
                        if isinstance(v, str) and v}
    return node


def planned_nodes_from_plan(plan, action: str = "") -> list:
    """Собрать PlannedGraph §34 из ResponsePlan (duck-typed; никогда не бросает).

    Порядок: TRIGGER → PLANNER → TOOLS → WRITER(при reply/tool) → DELIVERY →
    ИТОГ. REACT/SILENT (§34): WRITER-узел НЕ строится — фиктивный Writer
    запрещён."""
    try:
        from services import response_extent as _ext
        task_kind = _plan_axis(getattr(plan, "task_kind", ""),
                               _ext.TASK_KINDS)
        extent = _plan_axis(getattr(plan, "extent", ""), _ext.EXTENTS)
        structure = _plan_axis(getattr(plan, "structure", ""), _ext.STRUCTURES)
        delivery = _plan_axis(getattr(plan, "delivery_hint", ""),
                              _ext.DELIVERY_HINTS)
        tool_policy = _plan_axis(getattr(plan, "tool_policy", ""),
                                 _ext.TOOL_POLICIES)
        source = _plan_axis(getattr(plan, "source", ()),
                            ("explicit", "task-kind", "mode_alias", "default",
                             # ASAP 7 (F2, §18): план от L1 Planner.
                             "l1"))
    except Exception:      # pragma: no cover - защитная ветка
        return []
    act = _plan_axis(action, ("reply", "react", "silent", "tool"))
    # §34: REACT/SILENT — ни Writer, ни tools, ни текстовой доставки;
    # фиксируем это в плане честно (фиктивные узлы запрещены).
    no_text = act in ("react", "silent")
    if no_text:
        delivery = "none"
        tool_policy = "none"

    nodes = [_planned_node(
        PLAN_TRIGGER, ACTION_LABELS.get(act, act or "ответ текстом"),
        axes={"action": act},
        reason_ru=("Прямое обращение к боту — требуется ответ."
                   if act in ("reply", "tool", "")
                   else "Реакция на сообщение без текстового ответа."
                   if act == "react"
                   else "Осознанное молчание (без ответа)."))]
    planner_reason = " ".join(
        part for part in (_TASK_REASON_RU.get(task_kind, ""),
                          _EXTENT_REASON_RU.get(extent, "")) if part)
    # §36-полировка: «Почему tools…» не дублируется на PLANNER и TOOLS —
    # при policy=none причина живёт на TOOLS-узле.
    if tool_policy == "none" and planner_reason.startswith("Почему tools"):
        planner_reason = _EXTENT_REASON_RU.get(extent, "")
    nodes.append(_planned_node(
        PLAN_PLANNER,
        " · ".join(part for part in (
            task_kind and TASK_KIND_LABELS.get(task_kind, task_kind),
            extent and EXTENT_LABELS.get(extent, extent),
            structure and STRUCTURE_LABELS.get(structure, structure),
        ) if part),
        axes={"task_kind": task_kind, "extent": extent,
              "structure": structure, "source": source},
        reason_ru=planner_reason or
        "План построен до генерации (детерминированная классификация)."))
    # ── ASAP 7 (F2, §18/D-5): план пришёл от L1 Planner (source="l1") →
    # честная идентификация узла: title «L1 Planner» (не дет. классификатор).
    if source == "l1":
        planner = nodes[-1]
        planner["title"] = "L1 Planner"
        planner["reason_ru"] = (planner_reason or
                                "План построен L1 Planner (отдельный быстрый "
                                "LLM-вызов до инструментов).")
    nodes.append(_planned_node(
        PLAN_TOOLS, TOOL_POLICY_LABELS.get(tool_policy, tool_policy or "—"),
        axes={"tool_policy": tool_policy},
        reason_ru=_TOOL_POLICY_REASON_RU.get(
            tool_policy,
            _TASK_REASON_RU.get(task_kind, "Инструменты по необходимости."))))
    # §34: Writer — только для текстовых исходов; REACT/SILENT его не имеют.
    if act in ("reply", "tool", ""):
        nodes.append(_planned_node(
            PLAN_WRITER, "генерация текста по плану",
            reason_ru="Планируется вызов Writer — один текстовый проход "
                      "без каскада рерайтеров."))
    nodes.append(_planned_node(
        PLAN_DELIVERY, DELIVERY_LABELS.get(delivery, delivery or "—"),
        axes={"delivery_hint": delivery},
        reason_ru=_DELIVERY_REASON_RU.get(
            delivery, "Канал доставки определяется в ходе ответа.")))
    nodes.append(_planned_node(
        PLAN_OUTCOME, "успешная доставка ответа",
        reason_ru="Ответ доставлен в чат; расхождение с планом видно выше."))
    return nodes


def set_planned(run_id, planned_nodes) -> None:
    """MCA-23 §33 API: зафиксировать planned-узлы прогона (fail-open).

    Вызывается при формировании решения (одна интеграционная точка в
    ``direct_chat_service``). In-memory, без DDL; ограничение ≤8 узлов;
    R17-whitelist полей."""
    try:
        rid = str(run_id or "")
        if not rid or not isinstance(planned_nodes, (list, tuple)):
            return
        nodes = []
        for raw in list(planned_nodes)[:_PLANNED_MAX_NODES]:
            if not isinstance(raw, dict) or not str(raw.get("key") or ""):
                continue
            nodes.append({k: raw[k] for k in _PLANNED_NODE_FIELDS
                          if k in raw})
        if not nodes:
            return
        _store.put_planned(rid, {"ts": round(time.time(), 3),
                                 "nodes": nodes})
    except Exception:      # pragma: no cover - best-effort, пайплайн не рвём
        return


def record_response_plan(run_id, *, plan, action: str = "") -> None:
    """Удобная обёртка: ResponsePlan → planned-узлы → ``set_planned``.

    Единственная точка вызова из ``direct_chat_service`` (guard/fail-open
    там же). Никогда не бросает."""
    try:
        nodes = planned_nodes_from_plan(plan, action=action)
        if nodes:
            set_planned(run_id, nodes)
    except Exception:      # pragma: no cover - best-effort
        return


def get_planned(run_id):
    """Planned-слой прогона (``{"ts":…, "nodes":[…]}`` или ``None``)."""
    try:
        snapshot = _store.get(run_id)
        if not isinstance(snapshot, dict):
            return None
        planned = snapshot.get(_PLANNED_KEY)
        return dict(planned) if isinstance(planned, dict) else None
    except Exception:      # pragma: no cover - защитная ветка
        return None


def _actual_facts(snapshot, nodes, llm_rows) -> dict:
    """Фактические факты прогона для сравнения (только реальные события)."""
    action = ""
    tool_names: list = []
    tool_failed = 0
    decision_ms: list = []
    for event in (snapshot.get(_AGENTIC_KEY) or []):
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "")
        if name in ("DECISION_COMPLETE", "DECISION_START") and not action:
            action = _plan_axis(event.get("action"),
                                ("reply", "react", "silent", "tool"))
        if name in ("TOOL_CALL_COMPLETE", "TOOL_CALL_FAILED"):
            if name == "TOOL_CALL_FAILED":
                tool_failed += 1
            tool_name = str(event.get("tool") or "")
            if tool_name:
                tool_names.append(tool_name)
        if name == "DECISION_COMPLETE":
            value = _num_or_none(event.get("duration_ms"))
            if value is not None:
                decision_ms.append(value)
    # ASAP 7 (F2, §18): L1-факты (requested/resolved/rejected capabilities)
    # — реальная деривация из L1_PLAN/L1_CAPABILITY_REJECTED событий.
    l1_facts = _l1_facts_from_events(snapshot.get(_AGENTIC_KEY) or [])
    delivery = publication_status_of(snapshot)
    writer_ran = any(node.get("kind") == KIND_LLM and
                     node.get("stageKey") != STAGE_L1_PLANNER
                     for node in nodes)
    if not writer_ran:
        # Прогон без агентных событий: фактический Writer — реальная
        # LLM-строка текстовой генерации (single/stage1/stage2/text).
        # L1 Planner (step="l1_planner") — НЕ Writer (решение, не текст).
        writer_ran = any(
            (row.get("step") or "") in ("single", "stage1", "stage2")
            for row in (llm_rows or []) if isinstance(row, dict))
    return {
        "action": action,
        "tools_used": len(tool_names),
        "tools_failed": tool_failed,
        "tool_names": tool_names[:8],
        "writer_ran": writer_ran,
        "delivery": delivery,
        "run_status": _str_or_none(snapshot.get("status")),
        "l1_requested": l1_facts.get("requested") or [],
        "l1_resolved": l1_facts.get("resolved") or [],
        "l1_rejected": l1_facts.get("rejected") or [],
    }


def _cmp_row(key: str, planned: str, actual: str, status: str,
             reason_ru: str = "") -> dict:
    return {"key": key, "label": PLAN_LABELS.get(key, key),
            "title": PLAN_TITLES.get(key, key),
            "planned": planned, "actual": actual, "status": status,
            "reason_ru": str(reason_ru or "")}


def planned_vs_actual(planned_nodes, actual: dict) -> list:
    """Сравнение planned-vs-actual (§33): совпало/отклонилось/не
    выполнилось/лишнее. Честность: строка сравнения строится ТОЛЬКО на
    реальном факте события — нет факта (доставка/итог неизвестны) →
    строки нет (planned-цепочка выше всё равно показывает план)."""
    by_key = {}
    for node in (planned_nodes or []):
        if isinstance(node, dict):
            by_key[node.get("key")] = node
    rows = []
    act = actual.get("action") or ""
    trig = by_key.get(PLAN_TRIGGER) or {}
    planned_action = ((trig.get("axes") or {}).get("action") or "")
    if planned_action and act:
        if act == planned_action:
            status, reason = CMP_MATCH, ""
        else:
            status = CMP_DEVIATED
            reason = ("Планировалось «%s», фактически — «%s»." % (
                ACTION_LABELS.get(planned_action, planned_action),
                ACTION_LABELS.get(act, act)))
        rows.append(_cmp_row(PLAN_TRIGGER,
                             ACTION_LABELS.get(planned_action,
                                               planned_action),
                             ACTION_LABELS.get(act, act),
                             status, reason))
    # PLANNER — informational: это сам план, факт сравнивает его оси ниже.
    planner = by_key.get(PLAN_PLANNER) or {}
    if planner:
        rows.append(_cmp_row(PLAN_PLANNER, str(planner.get("expected") or ""),
                             "план применён к запросу", CMP_MATCH))

    tools = by_key.get(PLAN_TOOLS) or {}
    if tools:
        policy = (tools.get("axes") or {}).get("tool_policy") or ""
        used = int(actual.get("tools_used") or 0)
        failed = int(actual.get("tools_failed") or 0)
        names = actual.get("tool_names") or []
        # ASAP 7 (F2, §18/REV-2 (a)): requested→resolved capabilities L1 —
        # честная деривация (rejected из L1_CAPABILITY_REJECTED событий).
        resolved = actual.get("l1_resolved") or []
        rejected = actual.get("l1_rejected") or []
        requested = actual.get("l1_requested") or []
        if resolved:
            actual_txt = "resolved: " + ", ".join(resolved)
        elif requested:
            actual_txt = ("из %d запрошенных не резолвилось ни одной"
                          % len(requested))
        else:
            actual_txt = ""
        if rejected:
            actual_txt += (" · отклонено: "
                           + ", ".join(cap for cap, _ in rejected))
        if names:
            actual_txt = (", ".join(names) + ("" if not actual_txt
                                              else " · " + actual_txt))
        elif not actual_txt:
            actual_txt = ("попыток не было" if used == 0 and failed == 0
                          else "неизвестно")
        if failed:
            actual_txt += " · упало: %d" % failed
        if policy == "none":
            if used or failed:
                status = CMP_EXTRA
                reason = ("Почему tools не использовались? План был без "
                          "инструментов, но фактический прогон их вызвал.")
            else:
                status, reason = CMP_MATCH, ""
        elif policy == "required":
            if used:
                status, reason = CMP_MATCH, ""
            elif failed:
                status = CMP_MISSING
                reason = "Инструменты планировались — вызовы упали."
            else:
                status = CMP_MISSING
                reason = ("Инструменты планировались (нужны внешние данные), "
                          "но не выполнились.")
        else:   # auto/constrained
            status, reason = CMP_MATCH, ""
        rows.append(_cmp_row(PLAN_TOOLS,
                             str(tools.get("expected") or ""), actual_txt,
                             status, reason))

    writer = by_key.get(PLAN_WRITER)
    writer_ran = bool(actual.get("writer_ran"))
    if writer is not None:
        rows.append(_cmp_row(
            PLAN_WRITER, str(writer.get("expected") or ""),
            "выполнился" if writer_ran else "не выполнялся",
            CMP_MATCH if writer_ran else CMP_MISSING,
            "" if writer_ran else "Writer не выполнился (нет текстовой "
                                 "генерации в событиях)."))
    elif writer_ran:
        # §34: REACT/SILENT не планируют Writer; фактическая генерация —
        # лишний этап.
        rows.append(_cmp_row(
            PLAN_WRITER, "не планировался", "выполнился", CMP_EXTRA,
            "Writer не планировался (реакция/молчание), но генерация была."))

    delivery = by_key.get(PLAN_DELIVERY) or {}
    if delivery:
        hint = (delivery.get("axes") or {}).get("delivery_hint") or ""
        fact = actual.get("delivery") or ""
        # Честность: нет факта доставки (прогон ещё идёт / Direct-прогон без
        # publish-событий) → строки сравнения нет (фиктивный «missing»
        # запрещён).
        if fact:
            fact_label = {
                "published_rich": "Rich-карточка", "published_text": "обычное "
                "сообщение", "failed": "доставка упала", "skipped": "доставки "
                "не было", "": "неизвестно",
            }.get(fact, fact)
            status, reason = CMP_MATCH, ""
            if fact == "failed":
                status = CMP_MISSING
                reason = "Что упало: публикация ответа не удалась."
            elif hint == "rich" and fact == "published_text":
                status = CMP_DEVIATED
                reason = ("Планировалась Rich-карточка, ответ ушёл обычным "
                          "сообщением (fallback доставки).")
            elif hint == "plain" and fact == "published_rich":
                status = CMP_DEVIATED
                reason = "Планировалось обычное сообщение, фактически Rich."
            elif hint == "media" and fact in ("published_rich",
                                              "published_text"):
                status = CMP_DEVIATED
                reason = "Планировалось медиа, фактически текстовая доставка."
            elif hint == "none" and fact not in ("skipped",):
                status = CMP_EXTRA
                reason = "Доставка не планировалась, но состоялась."
            rows.append(_cmp_row(PLAN_DELIVERY,
                                 DELIVERY_LABELS.get(hint, hint or "—"),
                                 fact_label, status, reason))

    outcome = by_key.get(PLAN_OUTCOME) or {}
    if outcome:
        run_status = actual.get("run_status") or ""
        # Нет факта итога → строки нет (не приписываем прогону «успех»).
        if run_status:
            if run_status == "ok":
                status, actual_txt, reason = CMP_MATCH, "успех", ""
            elif run_status in ("degraded", "empty"):
                status = CMP_DEVIATED
                actual_txt = run_status
                reason = ("Прогон завершился с деградацией — итог "
                          "отличается от плана.")
            else:
                status = CMP_MISSING
                actual_txt = run_status
                reason = "Что упало: прогон завершился ошибкой."
            rows.append(_cmp_row(PLAN_OUTCOME,
                                 str(outcome.get("expected") or "успех"),
                                 actual_txt, status, reason))
    return rows


def planned_view(raw_planned, actual: dict) -> dict | None:
    """Planned-блок ответа /analytics/execution/latest (§33 view)."""
    try:
        if not isinstance(raw_planned, dict):
            return None
        nodes = [dict(n) for n in (raw_planned.get("nodes") or [])
                 if isinstance(n, dict)]
        if not nodes:
            return None
        comparison = planned_vs_actual(nodes, actual if isinstance(actual, dict)
                                       else {})
        summary = {CMP_MATCH: 0, CMP_DEVIATED: 0, CMP_MISSING: 0,
                   CMP_EXTRA: 0}
        for row in comparison:
            if row.get("status") in summary:
                summary[row["status"]] += 1
        return {
            "ts": raw_planned.get("ts"),
            "nodes": nodes,
            "comparison": comparison,
            "summary": summary,
        }
    except Exception:      # pragma: no cover - защитная ветка
        return None


def _percentile(values: list, q: float):
    """Честный перцентиль (линейная интерполяция; пусто → ``None``)."""
    if not values:
        return None
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return round(data[0], 1)
    pos = q * (len(data) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return round(data[lo] * (1 - frac) + data[hi] * frac, 1)


def response_recent_window() -> dict:
    """Окно свежих Direct-прогонов (in-memory, ≤20 прогонов / ~15 минут).

    Источник — существующие снапшоты (агентные события + planned-слой),
    второй телеметрии нет. Агрегаты осей плана §35 за БОЛЬШИЕ периоды
    недоступны (durable-осей в ``llm_usage_events`` нет) — это честное
    ограничение, UI показывает «—» с пояснением."""
    actions: dict = {}
    task_kinds: dict = {}
    extents: dict = {}
    deliveries: dict = {"plain": 0, "rich": 0, "media": 0, "none": 0}
    runs = tools_calls = tools_failed = runs_with_tools = 0
    decision_ms: list = []
    for snapshot in _store.snapshots():
        planned = snapshot.get(_PLANNED_KEY)
        events = snapshot.get(_AGENTIC_KEY) or []
        if not isinstance(planned, dict) and not events:
            continue
        runs += 1
        axes = {}
        if isinstance(planned, dict):
            for node in (planned.get("nodes") or []):
                if isinstance(node, dict) and node.get("key") == PLAN_PLANNER:
                    axes = node.get("axes") or {}
        tk = str(axes.get("task_kind") or "")
        ex = str(axes.get("extent") or "")
        if tk:
            task_kinds[tk] = task_kinds.get(tk, 0) + 1
        if ex:
            extents[ex] = extents.get(ex, 0) + 1
        action = ""
        run_tools = run_tool_failed = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            name = str(event.get("event") or "")
            if name in ("DECISION_COMPLETE", "DECISION_START") and not action:
                action = _plan_axis(event.get("action"),
                                    ("reply", "react", "silent", "tool"))
            if name in ("TOOL_CALL_COMPLETE", "TOOL_CALL_FAILED"):
                run_tools += 1
                if name == "TOOL_CALL_FAILED":
                    run_tool_failed += 1
            if name == "DECISION_COMPLETE":
                value = _num_or_none(event.get("duration_ms"))
                if value is not None:
                    decision_ms.append(value)
        if action:
            actions[action] = actions.get(action, 0) + 1
        if run_tools:
            runs_with_tools += 1
        tools_calls += run_tools
        tools_failed += run_tool_failed
        fact = publication_status_of(snapshot)
        if fact == "published_rich":
            deliveries["rich"] += 1
        elif fact == "published_text":
            deliveries["plain"] += 1
    return {
        "runs": runs,
        "actions": actions,
        "task_kinds": task_kinds,
        "extents": extents,
        "deliveries": deliveries,
        "tool_calls": tools_calls,
        "tool_failures": tools_failed,
        "runs_with_tools": runs_with_tools,
        "tool_failure_rate": (round(tools_failed / tools_calls, 4)
                              if tools_calls else None),
        "decision_latency_ms": {"p50": _percentile(decision_ms, 0.5),
                                "p95": _percentile(decision_ms, 0.95)},
        "window_note_ru": "по последним прогонам в памяти (≤20, ~15 минут)",
    }


# ── ASAP 7 (F2, §1.10/§18): durable-оси L1 Planner за 24ч/7д ────────────────
# Единственный durable-источник осей плана: колонка `plan_meta` строк
# `llm_usage_events` (module='direct_chat' AND step='l1_planner'). In-memory
# `response_recent_window` остаётся источником live-виджета; SQL-агрегат
# закрывает честность периодов после рестарта (докстринг
# response_recent_window: оси «за большие периоды» теперь читаются из PG).
# Вторая telemetry-модель не создаётся (§1.10); R17: наружу только
# enum-распределения/числа.

DURABLE_L1_AXES_SQL = (
    "WITH l1 AS ("
    "  SELECT input_tokens, output_tokens, cost_usd, price_known, plan_meta "
    "  FROM llm_usage_events "
    "  WHERE module = 'direct_chat' AND step = 'l1_planner' "
    "    AND ts >= now() - ($1::int * interval '1 day')"
    ") "
    "SELECT "
    "  (SELECT COUNT(*) FROM l1) AS calls, "
    "  (SELECT COALESCE(SUM(input_tokens), 0) FROM l1) AS input_tokens, "
    "  (SELECT COALESCE(SUM(output_tokens), 0) FROM l1) AS output_tokens, "
    "  (SELECT SUM(cost_usd) FILTER (WHERE price_known) FROM l1) "
    "    AS cost_known, "
    "  (SELECT COALESCE(BOOL_AND(price_known), true) FROM l1) "
    "    AS price_known, "
    "  (SELECT COUNT(*) FROM l1 WHERE plan_meta IS NOT NULL) AS with_meta, "
    "  (SELECT COALESCE(jsonb_object_agg(k, c), '{}'::jsonb) FROM "
    "     (SELECT COALESCE(NULLIF(plan_meta->>'action', ''), 'unknown') AS k, "
    "             COUNT(*) AS c FROM l1 "
    "      WHERE plan_meta IS NOT NULL GROUP BY 1) t) AS actions, "
    "  (SELECT COALESCE(jsonb_object_agg(k, c), '{}'::jsonb) FROM "
    "     (SELECT COALESCE(NULLIF(plan_meta->>'extent', ''), 'unknown') AS k, "
    "             COUNT(*) AS c FROM l1 "
    "      WHERE plan_meta IS NOT NULL GROUP BY 1) t) AS extents, "
    "  (SELECT COALESCE(jsonb_object_agg(k, c), '{}'::jsonb) FROM "
    "     (SELECT COALESCE(NULLIF(plan_meta->>'tone', ''), 'unknown') AS k, "
    "             COUNT(*) AS c FROM l1 "
    "      WHERE plan_meta IS NOT NULL GROUP BY 1) t) AS tones, "
    "  (SELECT COALESCE(jsonb_object_agg(k, c), '{}'::jsonb) FROM "
    "     (SELECT COALESCE(NULLIF(plan_meta->>'bucket', ''), 'unknown') AS k, "
    "             COUNT(*) AS c FROM l1 "
    "      WHERE plan_meta IS NOT NULL GROUP BY 1) t) AS buckets, "
    "  (SELECT COUNT(*) FROM l1 WHERE plan_meta->>'inherited' = 'true') "
    "    AS inherited, "
    "  (SELECT COUNT(*) FROM l1 "
    "    WHERE COALESCE(plan_meta->>'fallback', '') <> '') AS fallback, "
    "  (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY "
    "     (plan_meta->>'latency_ms')::double precision) "
    "   FROM l1 WHERE plan_meta ? 'latency_ms') AS latency_p50, "
    "  (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY "
    "     (plan_meta->>'latency_ms')::double precision) "
    "   FROM l1 WHERE plan_meta ? 'latency_ms') AS latency_p95"
)

_L1_AXE_KEYS = ("actions", "extents", "tones", "buckets")


def durable_l1_axes_from_row(row) -> dict | None:
    """Нормализация строки SQL-агрегата → shape durable-осей (fail-open).

    ``None`` — событий за период нет (честное отсутствие, не нули)."""
    try:
        calls = int(row["calls"])
    except (TypeError, KeyError, ValueError):
        return None
    if calls <= 0:
        return None
    try:
        with_meta = int(row["with_meta"] or 0)
        inherited = int(row["inherited"] or 0)
        fallback = int(row["fallback"] or 0)
        price_known = bool(row["price_known"])
        cost_known = row["cost_known"]
        axes = {}
        for key in _L1_AXE_KEYS:
            raw = row[key]
            dist = {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    try:
                        n = int(v)
                    except (TypeError, ValueError):
                        continue
                    if n > 0:
                        dist[str(k)] = n
            axes[key] = dist
        latencies = []
        for key in ("latency_p50", "latency_p95"):
            value = row.get(key) if hasattr(row, "get") else row[key]
            try:
                latencies.append(round(float(value), 1)
                                 if value is not None else None)
            except (TypeError, ValueError):
                latencies.append(None)
        return {
            "available": with_meta > 0,
            "calls": calls,
            "with_meta": with_meta,
            "tokens": {"input_tokens": int(row["input_tokens"] or 0),
                       "output_tokens": int(row["output_tokens"] or 0)},
            "cost_usd": (round(float(cost_known), 6)
                         if (price_known and cost_known is not None) else None),
            "price_known": price_known,
            "inherited_rate": (round(inherited / with_meta, 4)
                               if with_meta else None),
            "fallback_rate": (round(fallback / with_meta, 4)
                              if with_meta else None),
            "latency_ms": {"p50": latencies[0], "p95": latencies[1],
                           "source": "plan_meta_latency"},
            **axes,
        }
    except Exception:      # pragma: no cover - защитная ветка (fail-open)
        return None


async def fetch_durable_l1_axes(conn, days: int) -> dict | None:
    """SQL-агрегат durable-осей L1 за период (24ч/7д). Fail-open: ошибка
    чтения → ``None`` (вызывающий показывает честное «нет данных»)."""
    try:
        row = await conn.fetchrow(DURABLE_L1_AXES_SQL, int(days))
    except Exception:
        return None
    if row is None:
        return None
    return durable_l1_axes_from_row(row)


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
    # MCA-23 (P2-B §33): planned-vs-actual view — аддитивное поле `planned`.
    # Плана нет → None (честно: «план ещё не строился», не выдумываем).
    planned_block = None
    raw_planned = snapshot.get(_PLANNED_KEY)
    if isinstance(raw_planned, dict):
        planned_block = planned_view(raw_planned, _actual_facts(
            snapshot, nodes, llm_rows))
    return {
        "run_id": run_id or None,
        "started_at": started_at,
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics_block(snapshot, llm_rows),
        "publication_status": publication_status_of(snapshot),
        "planned": planned_block,
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
