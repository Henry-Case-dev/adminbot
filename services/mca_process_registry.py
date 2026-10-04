"""Раунд 10.27 (MCA Wave 0 — остаток, `mca-17a-observability-core`) — реестр
процессов §27.1 и контракты pipeline-version §27.4.

**Code-declared (ADR-1027-8 D1).** Единственный источник правды — этот модуль;
доменная таблица `mca_process_registry` НЕ создаётся (вторая копия в БД
дрейфует от кода и нарушает REUSE). Viewer получает реестр из code-контракта
через read-only API.

Реестр сверяется с фактическими handlers/workers/расписаниями/инструментами/
путями отправки. Runtime-статус (`implemented`/`disabled`/`not_run`/
`not_instrumented`) вычисляется **при чтении** из декларации + резолва
kill-switch per-call + наличия событий/стадий. «Новый процесс без
наблюдаемости = незавершённая интеграция».

REUSE: стадии/виджет-ID закрытых фич (`mca-03`/`mca-02`/`mca-04a`/`mca-07`)
регистрируются ссылками на их уже существующие события (без переизобретения).
Процессы будущих фич присутствуют как `not_run`/`not_instrumented` до
реализации.

Kill-switch: `MCA_PROCESS_REGISTRY_ENABLED` (default ON, master-aware).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from services import mca_gates

logger = logging.getLogger(__name__)

# ── статусы регистрации (§4.1) ──────────────────────────────────────────────
STATUS_IMPLEMENTED = "implemented"
STATUS_DISABLED = "disabled"
STATUS_NOT_RUN = "not_run"
STATUS_NOT_INSTRUMENTED = "not_instrumented"
REGISTRATION_STATUSES = frozenset({
    STATUS_IMPLEMENTED, STATUS_DISABLED, STATUS_NOT_RUN, STATUS_NOT_INSTRUMENTED,
})

# Режимы триггера (§4.1).
TRIGGER_KINDS = frozenset({
    "per_message", "schedule", "on_write", "per_request", "manual",
    "background", "event", "on_demand",
})

# Виджеты (REUSE widget-map/`_TAB_BY_GROUP`; не-UI — явный маркер).
WIDGET_NONE = "—"


@dataclass(frozen=True)
class ProcessDefinition:
    """Запись реестра §27.1: фактический процесс из кода."""

    process_id: str
    version: str
    purpose: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    stages: tuple[str, ...]
    branches: tuple[str, ...] = ()
    trigger_kind: str = "background"
    schedule: str = ""
    settings_ref: tuple[str, ...] = ()
    state_source: tuple[str, ...] = ()
    recovery_ops: tuple[str, ...] = ()
    widget_id: str = WIDGET_NONE
    stages_to_events: dict = field(default_factory=dict)
    instrumentation: tuple[str, ...] = ()
    owner_feature: str = ""
    enabled_gate: str = ""      # имя kill-switch процесса ("" = всегда активен)
    event_names: tuple[str, ...] = ()
    note: str = ""

    @property
    def declared_instrumented(self) -> bool:
        return bool(self.instrumentation and self.event_names)


@dataclass(frozen=True)
class PipelineStageSpec:
    """Стадия pipeline-version (§4.4): имя + обязательность + тип + fallback."""

    name: str
    required: bool = True
    stage_type: str = "generic"   # generic|llm|video|archive
    has_fallback: bool = False


@dataclass(frozen=True)
class PipelineVersion:
    """Контракт pipeline-version: стадии + ветви (§4.4/D5)."""

    pipeline_type: str
    version: str
    stages: tuple[PipelineStageSpec, ...]

    def stage(self, name: str) -> PipelineStageSpec | None:
        for s in self.stages:
            if s.name == name:
                return s
        return None

    @property
    def required_stages(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.stages if s.required)

    @property
    def optional_stages(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.stages if not s.required)


# ── контракты pipeline-version (§4.4) ───────────────────────────────────────

PIPELINE_VERSIONS: dict[tuple[str, str], PipelineVersion] = {}


def _register_pipeline(pv: PipelineVersion) -> None:
    PIPELINE_VERSIONS[(pv.pipeline_type, pv.version)] = pv


# `direct.reply` — прямой ответ (decision → tool chain → память → lesson).
_register_pipeline(PipelineVersion(
    pipeline_type="direct.reply",
    version="1",
    stages=(
        PipelineStageSpec("queued", required=True, stage_type="generic"),
        PipelineStageSpec("retrieval", required=False, stage_type="llm",
                          has_fallback=True),
        PipelineStageSpec("decision", required=True, stage_type="llm"),
        PipelineStageSpec("tools", required=False, stage_type="llm",
                          has_fallback=True),
        PipelineStageSpec("llm", required=True, stage_type="llm"),
        PipelineStageSpec("write", required=True, stage_type="generic"),
        PipelineStageSpec("deliver", required=True, stage_type="generic"),
    ),
))

# `archive.rebuild` — длительный архивный job (root + batch).
_register_pipeline(PipelineVersion(
    pipeline_type="archive.rebuild",
    version="1",
    stages=(
        PipelineStageSpec("queued", required=True),
        PipelineStageSpec("batch", required=True, stage_type="archive"),
        PipelineStageSpec("finalize", required=True),
    ),
))

# `summary.window` — окно/сводка.
_register_pipeline(PipelineVersion(
    pipeline_type="summary.window",
    version="1",
    stages=(
        PipelineStageSpec("queued", required=True),
        PipelineStageSpec("collect", required=True),
        PipelineStageSpec("summarize", required=True, stage_type="llm"),
        PipelineStageSpec("persist", required=True),
        PipelineStageSpec("publish", required=False, stage_type="generic",
                          has_fallback=True),
    ),
))

# `sleep.deep` — ночной глубокий сон (mca-06, ADR-1028-9 D11): стадии
# «собрать пакет → якоря/мост → LLM → запись парадигм». LLM-стадия допускает
# законную длительность (progress-stall по типу, §8.5).
_register_pipeline(PipelineVersion(
    pipeline_type="sleep.deep",
    version="1",
    stages=(
        PipelineStageSpec("queued", required=True),
        PipelineStageSpec("collect", required=True),
        PipelineStageSpec("anchors", required=True),
        PipelineStageSpec("bridge", required=True, stage_type="llm"),
        PipelineStageSpec("write", required=True),
    ),
))


def get_pipeline(pipeline_type: str, version: str | None = None
                 ) -> PipelineVersion | None:
    """Контракт pipeline-version (последний доступный, если version=None)."""
    if version is not None:
        return PIPELINE_VERSIONS.get((pipeline_type, str(version)))
    candidates = [pv for (pt, _), pv in PIPELINE_VERSIONS.items()
                  if pt == pipeline_type]
    if not candidates:
        return None
    return max(candidates, key=lambda pv: str(pv.version))


def known_pipeline_types() -> tuple[str, ...]:
    return tuple(sorted({pt for (pt, _) in PIPELINE_VERSIONS}))


# ── обязательный минимум реестра (§4.2; Builder сверяет построчно) ──────────
# `event_names`/`stages_to_events` указывают ТОЛЬКО фактически эмитируемые
# имена событий `mca_events` (реальная сверка — регресс-тест
# `test_registry_event_names_exist_in_code`). Процессы без подключённого к
# `mca_events` инструментирования честно помечаются пустыми
# `instrumentation`/`event_names` → runtime-статус `not_instrumented`
# (§27.1: отсутствие данных не выдаётся за норму; имя события не выдумывается).

PROCESS_REGISTRY: tuple[ProcessDefinition, ...] = (
    # ── mca-03: идентичность сообщений (реальные события message_identity.py) ─
    ProcessDefinition(
        process_id="ingestion.live", version="1",
        purpose="Приём живых сообщений из чата в хранилище памяти",
        inputs=("telegram update",), outputs=("smart_messages",),
        stages=("receive", "identity", "persist"),
        trigger_kind="per_message", schedule="по сообщению",
        settings_ref=("MCA_MESSAGE_IDENTITY_ENABLED",),
        state_source=("smart_messages", "message_source_records"),
        recovery_ops=("resume_stream",),
        widget_id="Приём/импорт/редакции",
        owner_feature="mca-03",
        enabled_gate="MCA_MESSAGE_IDENTITY_ENABLED",
        note="handler не эмитит mca_events (identity-события — у "
             "identity.resolve); зарегистрировано как not_instrumented",
    ),
    ProcessDefinition(
        process_id="ingestion.import", version="1",
        purpose="Импорт истории из экспорта (парсер → LLM-worker → загрузка)",
        inputs=("export file",), outputs=("smart_messages",),
        stages=("parse", "extract", "load"),
        trigger_kind="manual",
        settings_ref=("IMPORT_RETENTION_ENABLED",),
        state_source=("import_checkpoints", "task_jobs"),
        recovery_ops=("resume_checkpoint",),
        widget_id="Приём/импорт/редакции",
        owner_feature="mca-03",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="identity.resolve", version="1",
        purpose="Каноническая идентичность (chat_id, tg_message_id) и редакции",
        inputs=("message",), outputs=("message_revisions",),
        stages=("resolve", "version", "migrate"),
        trigger_kind="on_write",
        settings_ref=("MCA_MESSAGE_REVISION_TRACKING_ENABLED",),
        state_source=("smart_messages", "message_revisions"),
        recovery_ops=("recompute_identity",),
        widget_id="Идентичность и адресаты",
        stages_to_events={"version": "message_revision",
                          "migrate": "message_identity_migration"},
        instrumentation=("version", "migrate"),
        owner_feature="mca-03",
        enabled_gate="MCA_MESSAGE_IDENTITY_ENABLED",
        event_names=("message_revision", "message_identity_migration"),
    ),
    ProcessDefinition(
        process_id="chat.lifecycle", version="1",
        purpose="Миграции/жизненный цикл чата (смена chat_id и т.п.)",
        inputs=("event",), outputs=("chat_id_migrations",),
        stages=("detect", "migrate"),
        trigger_kind="event",
        settings_ref=("MCA_MESSAGE_IDENTITY_ENABLED",),
        state_source=("smart_messages", "chat_id_migrations"),
        recovery_ops=("reconcile",),
        widget_id="Приём/импорт",
        owner_feature="mca-03",
        enabled_gate="MCA_MESSAGE_IDENTITY_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    # ── процессы памяти/сводок (инструментирование mca_events не подключено) ──
    ProcessDefinition(
        process_id="summary.window", version="1",
        purpose="Накопление окна сообщений и построение running-summary",
        inputs=("smart_messages",), outputs=("chat_running_summary",),
        stages=("collect", "summarize", "persist"),
        trigger_kind="schedule", schedule="по давлению окна",
        settings_ref=("CHAT_RUNNING_SUMMARY_ENABLED",),
        state_source=("chat_running_summary",),
        recovery_ops=("rebuild_window",),
        widget_id="Окно/summary",
        owner_feature="summary",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="summary.hybrid", version="1",
        purpose="Гибридные уровни сводок (L1-кластеризация → L2-писатель)",
        inputs=("smart_messages",), outputs=("chat_summary_levels",),
        stages=("filter", "l1", "l2", "format"),
        trigger_kind="schedule", schedule="по давлению",
        settings_ref=("SUMMARY_FILTER_ENABLED", "SUMMARY_HYBRID_L2_ENABLED"),
        state_source=("chat_summary_levels",),
        recovery_ops=("rebuild_level",),
        widget_id="Summary Hybrid",
        owner_feature="summary",
        enabled_gate="SUMMARY_HYBRID_L2_ENABLED",
        note="инструментирование mca_events не подключено (mca07_summary — "
             "стадия retrieval-контура, а не hybrid-писателя)",
    ),
    ProcessDefinition(
        process_id="facts.extract", version="1",
        purpose="Извлечение фактов из истории в граф памяти",
        inputs=("messages",), outputs=("graph_facts",),
        stages=("extract", "persist"),
        trigger_kind="background", schedule="очередь",
        settings_ref=("GRAPH_RAG_ENABLED",),
        state_source=("graph_facts",),
        recovery_ops=("reprocess_batch",),
        widget_id="Факты/граф",
        owner_feature="factext",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="dossier.rebuild", version="2",
        purpose="Полная пересборка/исправление досье: full rebuild (keyset), "
                "backfill архива, реклассификация, staging-активация, каскад",
        inputs=("smart_messages", "graph_facts",),
        outputs=("graph_facts", "mca_dossier_generations",
                 "mca_dossier_staging_items",),
        stages=("snapshot", "extract", "synthesize", "activate", "cascade",
                "finalize"),
        trigger_kind="manual", schedule="по кнопке + фоновый backfill",
        settings_ref=("DOSSIER_REBUILD_UI_ENABLED",
                      "MCA_DOSSIER_REBUILD_ENABLED",
                      "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED",
                      "MCA_DOSSIER_BACKGROUND_PASS_ENABLED",
                      "MCA_DOSSIER_RECLASSIFY_ENABLED"),
        state_source=("DossierRebuildJobStore", "task_jobs",
                      "mca_dossier_generations"),
        recovery_ops=("resume_checkpoint", "rollback_snapshot",
                      "reactivate_generation"),
        widget_id="Досье/архив",
        owner_feature="dossier",
        stages_to_events={"extract": "dossier_rebuild",
                          "cascade": "dossier_cascade"},
        instrumentation=("extract", "cascade"),
        event_names=("dossier_rebuild", "dossier_cascade"),
        enabled_gate="MCA_DOSSIER_REBUILD_ENABLED",
        note="mca-04b (ADR-1027-9): инструментирование dossier_rebuild/"
             "dossier_cascade (start+терминальный outcome, reason_code); "
             "прогресс — progress_cb + job-store (batch-состояния "
             "queued/running/paused/interrupted/failed/completed)",
    ),
    # ── mca-04a: provenance (реальное событие memory_provenance) ─────────────
    ProcessDefinition(
        process_id="provenance.record", version="1",
        purpose="Типизированные ссылки на источник и связь «объект↔источник»",
        inputs=("fact/message",), outputs=("mca_source_refs",),
        stages=("record", "link", "status"),
        trigger_kind="on_write",
        settings_ref=("MCA_PROVENANCE_ENABLED",),
        state_source=("mca_source_refs", "mca_evidence_links",
                      "mca_provenance_status"),
        recovery_ops=("reconstruct",),
        widget_id="Provenance",
        stages_to_events={"record": "memory_provenance"},
        instrumentation=("record",),
        owner_feature="mca-04a",
        enabled_gate="MCA_PROVENANCE_ENABLED",
        event_names=("memory_provenance",),
    ),
    ProcessDefinition(
        process_id="embeddings.index", version="1",
        purpose="Генерация/кэширование эмбеддингов и реестр поколений индекса",
        inputs=("text",), outputs=("embedding_cache",),
        stages=("embed", "index", "generation"),
        trigger_kind="on_write",
        settings_ref=("MCA_RETRIEVAL_CONTEXT_ENABLED", "EMBED_CACHE_ENABLED"),
        state_source=("embedding_cache", "mca_embedding_index_generations"),
        recovery_ops=("rebuild_index",),
        widget_id="Embeddings/индексы",
        owner_feature="mca-07",
        enabled_gate="MCA_RETRIEVAL_CONTEXT_ENABLED",
        note="инструментирование mca_events не подключено (mca07_* — стадии "
             "retrieval-контура)",
    ),
    # ── mca-07: retrieval (реальные события mca07_<stage>) ──────────────────
    ProcessDefinition(
        process_id="retrieval.query", version="1",
        purpose="Единый retrieval-контракт: сбор EvidenceBundle по запросу",
        inputs=("query",), outputs=("EvidenceBundle",),
        stages=("channels", "rerank", "bundle", "budget"),
        trigger_kind="per_request",
        settings_ref=("MCA_RETRIEVAL_CONTEXT_ENABLED",
                      "MCA_TYPED_RERANKER_ENABLED",
                      "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED"),
        state_source=("in-memory bundle", "mca_source_refs"),
        recovery_ops=("fallback_channels",),
        widget_id="Retrieval/RAG",
        stages_to_events={"channels": "mca07_retrieval",
                          "rerank": "mca07_reranker",
                          "bundle": "mca07_bundle",
                          "budget": "mca07_budget"},
        instrumentation=("channels", "rerank", "bundle", "budget"),
        owner_feature="mca-07",
        enabled_gate="MCA_RETRIEVAL_CONTEXT_ENABLED",
        event_names=("mca07_retrieval", "mca07_reranker", "mca07_bundle",
                     "mca07_budget"),
    ),
    ProcessDefinition(
        process_id="nostalgia.run", version="1",
        purpose="Ностальгические подборки по истории чата",
        inputs=("graph_facts",), outputs=("nostalgia_posts",),
        stages=("select", "render"),
        trigger_kind="schedule",
        settings_ref=("NOSTALGIA_ENABLED",),
        state_source=("task_jobs", "graph_facts"),
        recovery_ops=("resume_job",),
        widget_id="Ностальгия",
        owner_feature="nostalgia", enabled_gate="NOSTALGIA_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="lore.compile", version="1",
        purpose="Компиляция эпизодов/лора из истории",
        inputs=("smart_messages",), outputs=("lore_stories",),
        stages=("select", "compile", "persist"),
        trigger_kind="schedule",
        settings_ref=("LORE_COMPILER_ENABLED", "LORE_WORKER_ENABLED"),
        state_source=("lore_stories",),
        recovery_ops=("resume_job",),
        widget_id="Эпизоды/lore",
        owner_feature="lore", enabled_gate="LORE_WORKER_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="sleep.dream", version="1",
        purpose="Ночная обработка убеждений на основе памяти",
        inputs=("graph_facts",), outputs=("graph_facts(derived_belief)",),
        stages=("collect", "dream", "persist"),
        trigger_kind="schedule",
        settings_ref=("DREAM_ENABLED",),
        state_source=("task_jobs",),
        recovery_ops=("resume_job",),
        widget_id="Сон/убеждения",
        owner_feature="dream", enabled_gate="DREAM_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="sleep.deep", version="1",
        purpose="Глубокий сон: парадигмы/самоосмысление",
        inputs=("graph_facts",), outputs=("paradigms",),
        stages=("collect", "anchors", "bridge", "write"),
        trigger_kind="schedule",
        settings_ref=("DEEP_SLEEP_ENABLED", "MCA_DREAM_RUN_REPORTS_ENABLED"),
        state_source=("mca_pipeline_runs", "memory_dream_log"),
        recovery_ops=("resume_job",),
        widget_id="Глубокий сон/парадигмы",
        stages_to_events={"collect": "DREAM_DEEP_RUN",
                          "anchors": "DREAM_DEEP_RUN",
                          "bridge": "DREAM_DEEP_RUN",
                          "write": "DREAM_DEEP_RUN"},
        instrumentation=("collect", "anchors", "bridge", "write"),
        owner_feature="dream", enabled_gate="DEEP_SLEEP_ENABLED",
        event_names=("DREAM_DEEP_RUN",),
        note="mca-06 (ADR-1028-9 D11): run-строка на каждый запуск + "
             "span-события стадий (v19/v25); OFF `MCA_DREAM_RUN_REPORTS_ENABLED` "
             "→ только `_trace_deep`/лог, реестр честный `not_run`",
    ),
    ProcessDefinition(
        process_id="persona.traits", version="1",
        purpose="Черты личности/интересы бота",
        inputs=("memory",), outputs=("persona_*",),
        stages=("derive", "persist"),
        trigger_kind="on_demand",
        settings_ref=("PERSONA_ENABLED",),
        state_source=("persona_*",),
        recovery_ops=("recompute",),
        widget_id="Личность/интересы",
        owner_feature="persona", enabled_gate="PERSONA_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="anticliche.run", version="1",
        purpose="Анти-клише: подбор свежих формулировок",
        inputs=("chat context",), outputs=("anticliche_cache",),
        stages=("detect", "generate", "persist"),
        trigger_kind="schedule",
        settings_ref=("DYNAMIC_ANTICLICHE_ENABLED",),
        state_source=("anticliche_cache",),
        recovery_ops=("recompute",),
        widget_id="Анти-клише",
        owner_feature="anticliche", enabled_gate="DYNAMIC_ANTICLICHE_ENABLED",
        note="инструментирование mca_events не подключено (agentic_events — "
             "отдельный контракт ExecutionGraph)",
    ),
    ProcessDefinition(
        process_id="goodmorning.run", version="1",
        purpose="Планировщик утренних сообщений",
        inputs=("schedule",), outputs=("telegram send",),
        stages=("due_check", "send"),
        trigger_kind="schedule", schedule="cron",
        settings_ref=(),
        state_source=("task_jobs",),
        recovery_ops=("resume_job",),
        widget_id="Планировщики",
        owner_feature="goodmorning",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="scheduler.reactions", version="1",
        purpose="Планировщик реакций бота на события чата",
        inputs=("schedule/event",), outputs=("telegram reaction",),
        stages=("due_check", "react"),
        trigger_kind="schedule",
        settings_ref=("REACTION_MECHANICS_ENABLED",),
        state_source=("task_jobs",),
        recovery_ops=("resume_job",),
        widget_id="Планировщики",
        owner_feature="scheduler",
        note="инструментирование mca_events не подключено",
    ),
    # ── direct_chat: стадия answer_cache эмитит mca07_answer_cache ──────────
    ProcessDefinition(
        process_id="direct.reply", version="1",
        purpose="Прямой ответ: решение → tool chain → память → ответ",
        inputs=("user message",), outputs=("telegram reply",),
        stages=("queued", "decision", "llm", "write", "deliver",
                "answer_cache"),
        branches=("retrieval", "tools"),
        trigger_kind="per_message",
        settings_ref=("DIRECT_DECISION_MAKING_ENABLED",),
        state_source=("task_jobs", "mca_events"),
        recovery_ops=("resume_job", "delivery_reconcile"),
        widget_id="Ответы (decision/System2)",
        stages_to_events={"answer_cache": "mca07_answer_cache"},
        instrumentation=("answer_cache",),
        owner_feature="direct_chat",
        enabled_gate="DIRECT_DECISION_MAKING_ENABLED",
        event_names=("mca07_answer_cache",),
    ),
    ProcessDefinition(
        process_id="tools.chain", version="1",
        purpose="Tool chain: маршрутизация и исполнение инструментов",
        inputs=("tool calls",), outputs=("tool results",),
        stages=("route", "execute", "aggregate"),
        trigger_kind="per_request",
        settings_ref=("TOOL_CHAIN_LIMITS_ENABLED",),
        state_source=("mca_events", "task_jobs"),
        recovery_ops=("fallback_single",),
        widget_id="Tool chain",
        owner_feature="tools",
        note="инструментирование mca_events не подключено (agentic_events — "
             "отдельный контракт ExecutionGraph)",
    ),
    # ── mca-02: safe_fetch (реальное событие safe_fetch) ────────────────────
    ProcessDefinition(
        process_id="web.fetch", version="1",
        purpose="Безопасная загрузка веб-страниц/медиа (SSRF/лимиты)",
        inputs=("url",), outputs=("extracted content",),
        stages=("validate_url", "resolve", "fetch", "extract"),
        trigger_kind="per_request",
        settings_ref=("MCA_SAFE_FETCH_ENABLED", "MCA_EGRESS_GUARD_ENABLED"),
        state_source=("mca_events",),
        recovery_ops=("retry_bounded",),
        widget_id="Web/видео/медиа",
        stages_to_events={"fetch": "safe_fetch"},
        instrumentation=("fetch",),
        owner_feature="mca-02",
        enabled_gate="MCA_SAFE_FETCH_ENABLED",
        event_names=("safe_fetch",),
    ),
    ProcessDefinition(
        process_id="media.download", version="1",
        purpose="Загрузка видео/транскриптов",
        inputs=("url",), outputs=("media file",),
        stages=("prepare", "download", "transcribe"),
        trigger_kind="per_request",
        settings_ref=("DOWNLOAD_ENABLED", "YTDLP_FOR_YOUTUBE"),
        state_source=("task_jobs", "filesystem"),
        recovery_ops=("resume_download",),
        widget_id="Web/видео/медиа",
        owner_feature="media",
        enabled_gate="DOWNLOAD_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="image.generate", version="1",
        purpose="Генерация изображений по запросу",
        inputs=("prompt",), outputs=("image file",),
        stages=("reserve", "generate", "deliver"),
        trigger_kind="per_request",
        settings_ref=("IMAGE_GENERATION_ENABLED", "IMAGE_DAILY_LIMIT_ENABLED"),
        state_source=("mca_events", "reservation"),
        recovery_ops=("release_reservation",),
        widget_id="Tool chain",
        owner_feature="image",
        enabled_gate="IMAGE_GENERATION_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="summary.publish", version="1",
        purpose="Публикация rich/plain сводки",
        inputs=("summary text",), outputs=("telegram message",),
        stages=("render", "send"),
        trigger_kind="event",
        settings_ref=("SUMMARY_ENABLED",),
        state_source=("mca_events",),
        recovery_ops=("delivery_reconcile",),
        widget_id="Публикация",
        owner_feature="summary", enabled_gate="SUMMARY_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="factcheck.run", version="1",
        purpose="Проверка фактов (CoVe/grounding)",
        inputs=("claim",), outputs=("verdict",),
        stages=("extract_claims", "verify", "summary"),
        trigger_kind="per_request",
        settings_ref=("FACTCHECK_ENABLED", "SYSTEM2_FACTCHECK_ENABLED"),
        state_source=("in-memory", "mca_events"),
        recovery_ops=("fallback_single",),
        widget_id="Фактчек",
        owner_feature="factcheck", enabled_gate="FACTCHECK_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="maintenance.retention", version="1",
        purpose="Ретенция памяти/диска",
        inputs=("schedule",), outputs=("deleted rows/files",),
        stages=("select", "delete"),
        trigger_kind="schedule",
        settings_ref=("DISK_RETENTION_ENABLED",),
        state_source=("task_jobs", "filesystem"),
        recovery_ops=("resume_job",),
        widget_id="Сохранение/ресурсы",
        owner_feature="maintenance",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="backup.memory", version="1",
        purpose="Резервное копирование памяти/БД",
        inputs=("schedule",), outputs=("backup files",),
        stages=("snapshot", "verify"),
        trigger_kind="schedule",
        settings_ref=("MEMORY_BACKUP_ENABLED",),
        state_source=("filesystem", "task_jobs"),
        recovery_ops=("restore",),
        widget_id="Сохранение/ресурсы",
        owner_feature="backup", enabled_gate="MEMORY_BACKUP_ENABLED",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="uptime.heartbeat", version="1",
        purpose="Внешний heartbeat/uptime-наблюдение",
        inputs=("schedule",), outputs=("heartbeat file",),
        stages=("ping",),
        trigger_kind="schedule",
        settings_ref=(),
        state_source=("filesystem", "task_jobs"),
        recovery_ops=("restart_notice",),
        widget_id="Сохранение/ресурсы",
        owner_feature="uptime",
        note="инструментирование mca_events не подключено",
    ),
    ProcessDefinition(
        process_id="telemetry.events", version="1",
        purpose="Durable-персистенция и ретенция событий телеметрии",
        inputs=("terminal events",), outputs=("mca_events",),
        stages=("buffer", "flush", "prune"),
        trigger_kind="background",
        settings_ref=("MCA_EVENT_CONTRACT_ENABLED",
                      "MCA_TELEMETRY_STORE_ENABLED",
                      "MCA_TELEMETRY_SPOOL_ENABLED"),
        state_source=("mca_events", "spool"),
        recovery_ops=("spool_drain",),
        widget_id="Сохранение/ресурсы",
        owner_feature="mca-17a",
        enabled_gate="MCA_TELEMETRY_STORE_ENABLED",
        note="flush/prune не эмитят mca_events (структурный лог + счётчики)",
    ),
    # ── mca-17a: собственные инструментированные процессы ───────────────────
    ProcessDefinition(
        process_id="watchdog.jobs", version="1",
        purpose="Проверка stale-lease/heartbeat, takeover и recovery задач",
        inputs=("durable job state",), outputs=("interrupted/retry",),
        stages=("sweep", "takeover"),
        trigger_kind="background", schedule="старт + периодически",
        settings_ref=("MCA_HEARTBEAT_WATCHDOG_ENABLED",
                      "MCA_JOB_STALE_SECONDS"),
        state_source=("task_jobs", "mca_pipeline_runs"),
        recovery_ops=("recover_stale", "resume_checkpoint"),
        widget_id="Сохранение/ресурсы",
        stages_to_events={"sweep": "WATCHDOG_SWEEP",
                          "takeover": "WATCHDOG_TAKEOVER"},
        instrumentation=("sweep", "takeover"),
        owner_feature="mca-17a",
        enabled_gate="MCA_HEARTBEAT_WATCHDOG_ENABLED",
        event_names=("WATCHDOG_SWEEP", "WATCHDOG_TAKEOVER"),
    ),
    ProcessDefinition(
        process_id="incidents.delivery", version="1",
        purpose="Группировка инцидентов и их доставка в миниапп (polling)",
        inputs=("error events",), outputs=("mca_incidents",),
        stages=("group", "deliver"),
        trigger_kind="background", schedule="polling ≤10s",
        settings_ref=("MCA_INCIDENTS_ENABLED", "MCA_INCIDENT_PUSH_ENABLED"),
        state_source=("mca_incidents",),
        recovery_ops=("cursor_reconcile",),
        widget_id="Инциденты",
        stages_to_events={"group": "INCIDENT"},
        instrumentation=("group",),
        owner_feature="mca-17a",
        enabled_gate="MCA_INCIDENTS_ENABLED",
        event_names=("INCIDENT",),
    ),
    # ── mca-05: episodes/stories (ADR-1027-12 D12; стадии пайплайна) ─────────
    ProcessDefinition(
        process_id="episodes.build", version="1",
        purpose="Сборка эпизодов/историй: сегментация → извлечение → "
                "подтверждение продолжений → assemble → provenance/индекс",
        inputs=("smart_messages",), outputs=("mca_episodes", "mca_stories",),
        stages=("segment", "extract", "confirm", "assemble", "link",
                "index"),
        trigger_kind="background", schedule="batch/backfill",
        settings_ref=("MCA_EPISODES_ENABLED",
                      "MCA_EPISODES_CONTINUATION_ENABLED"),
        state_source=("mca_episodes", "mca_stories", "task_jobs"),
        recovery_ops=("resume_checkpoint",),
        widget_id="Эпизоды/lore",
        stages_to_events={"segment": "episodes_build",
                          "extract": "episodes_build",
                          "confirm": "episodes_build",
                          "assemble": "episodes_build",
                          "link": "episodes_build",
                          "index": "episodes_build"},
        instrumentation=("segment", "extract", "confirm", "assemble",
                         "link", "index"),
        owner_feature="mca-05",
        enabled_gate="MCA_EPISODES_ENABLED",
        event_names=("episodes_build", "story_discovered", "story_extended",
                     "source_linked", "contradiction_found", "story_rebuilt"),
        note="mca-05 (ADR-1027-12): стадии/события start+terminal outcome, "
             "reason_code; single-writer mca-01, короткие транзакции",
    ),
    ProcessDefinition(
        process_id="episodes.backfill", version="1",
        purpose="Resumable backfill эпизодов/историй по архиву чата "
                "(durable task_jobs, checkpoint, честная финализация)",
        inputs=("smart_messages (archive)",),
        outputs=("mca_episodes", "mca_stories",),
        stages=("segment", "extract", "confirm", "assemble", "link",
                "index"),
        trigger_kind="manual", schedule="по задаче (coalesce per-chat)",
        settings_ref=("MCA_EPISODES_ENABLED",
                      "MCA_EPISODES_BACKFILL_ENABLED",
                      "MCA_EPISODES_BATCH_MAX_MESSAGES"),
        state_source=("task_jobs", "mca_episodes"),
        recovery_ops=("resume_checkpoint",),
        widget_id="Эпизоды/lore",
        stages_to_events={"segment": "episodes_build",
                          "extract": "episodes_build",
                          "confirm": "episodes_build",
                          "assemble": "episodes_build",
                          "index": "episodes_build"},
        instrumentation=("segment", "extract", "confirm", "assemble",
                         "index"),
        owner_feature="mca-05",
        enabled_gate="MCA_EPISODES_BACKFILL_ENABLED",
        event_names=("episodes_build", "story_discovered", "story_extended",
                     "story_rebuilt"),
        note="unique key episodes.backfill:<chat_id>; paused при "
             "budget/LLM-ошибке — никогда ложный completed; send-path нет",
    ),
    # ── будущие фичи: not_run/not_instrumented до реализации (§1.2/§4.1) ────
    ProcessDefinition(
        process_id="context.compress", version="0",
        purpose="Сжатие контекста (mca-09)",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-09", widget_id=WIDGET_NONE,
        note="не реализовано (mca-09)",
    ),
    ProcessDefinition(
        process_id="context.selective", version="0",
        purpose="Выборочная подача контекста (mca-10a)",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-10a", widget_id=WIDGET_NONE,
        note="не реализовано (mca-10a)",
    ),
    ProcessDefinition(
        process_id="memory.lifecycle", version="0",
        purpose="Жизненный цикл памяти (mca-10b)",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-10b", widget_id=WIDGET_NONE,
        note="не реализовано (mca-10b)",
    ),
    ProcessDefinition(
        process_id="relations.semantic", version="0",
        purpose="Семантические отношения участников (mca-11)",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-11", widget_id=WIDGET_NONE,
        note="не реализовано (mca-11)",
    ),
    ProcessDefinition(
        process_id="episodes.timeline", version="0",
        purpose="Хронология эпизодов (mca-15)",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-15", widget_id=WIDGET_NONE,
        note="не реализовано (mca-15)",
    ),
    ProcessDefinition(
        process_id="self_learning.run", version="0",
        purpose="Самообучение/опыт (lessons)",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-16", widget_id=WIDGET_NONE,
        note="не реализовано (mca-16)",
    ),
    ProcessDefinition(
        process_id="self_model.update", version="0",
        purpose="SelfModel/TraitObservation/BehaviorRule/BehaviorFrame",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-18", widget_id=WIDGET_NONE,
        note="не реализовано (mca-18)",
    ),
    ProcessDefinition(
        process_id="vision.analyze", version="0",
        purpose="vision/MediaAsset/MediaAnalysis",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-19", widget_id=WIDGET_NONE,
        note="не реализовано (mca-19)",
    ),
    ProcessDefinition(
        process_id="temporal.factcheck", version="0",
        purpose="ClaimEnvelope/TemporalVerdict",
        inputs=(), outputs=(), stages=(), trigger_kind="background",
        owner_feature="mca-20", widget_id=WIDGET_NONE,
        note="не реализовано (mca-20)",
    ),
)
_PROCESS_BY_ID = {p.process_id: p for p in PROCESS_REGISTRY}


def get_process(process_id: str) -> ProcessDefinition | None:
    return _PROCESS_BY_ID.get(process_id)


# Имя kill-switch → функция-резолвер `mca_gates` (для runtime-статуса).
_GATE_RESOLVERS = {
    "MCA_MESSAGE_IDENTITY_ENABLED": "message_identity_enabled",
    "MCA_MESSAGE_REVISION_TRACKING_ENABLED": "message_revision_tracking_enabled",
    "MCA_PROVENANCE_ENABLED": "provenance_enabled",
    "MCA_RETRIEVAL_CONTEXT_ENABLED": "retrieval_context_enabled",
    "MCA_TYPED_RERANKER_ENABLED": "typed_reranker_enabled",
    "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED": "adaptive_context_budget_enabled",
    "MCA_SAFE_FETCH_ENABLED": "safe_fetch_enabled",
    "MCA_EGRESS_GUARD_ENABLED": "egress_guard_enabled",
    "MCA_TELEMETRY_STORE_ENABLED": "telemetry_store_enabled",
    "MCA_HEARTBEAT_WATCHDOG_ENABLED": "heartbeat_watchdog_enabled",
    "MCA_INCIDENTS_ENABLED": "incidents_enabled",
    "MCA_INCIDENT_PUSH_ENABLED": "incident_push_enabled",
    "MCA_TELEMETRY_SPOOL_ENABLED": "telemetry_spool_enabled",
    # mca-05 (ADR-1027-12 D13): episodes/stories.
    "MCA_EPISODES_ENABLED": "episodes_enabled",
    "MCA_EPISODES_BACKFILL_ENABLED": "episodes_backfill_enabled",
    "MCA_EPISODES_CONTINUATION_ENABLED": "episodes_continuation_enabled",
    "MCA_EPISODES_COMPILER_FACADE_ENABLED": "episodes_compiler_facade_enabled",
    # product-гейты из `config.settings` (не mca_gates) — резолв через settings.
}


def runtime_status(process: ProcessDefinition, *,
                   event_names_present: frozenset | None = None) -> str:
    """Вычислить runtime-статус процесса (§4.1).

    * declared-инструментирование отсутствует → `not_instrumented`;
    * процесс выключен гейтом → `disabled`;
    * есть инструментирование, но не зарегистрировано ни одного события →
      `not_run`;
    * иначе → `implemented`.

    `event_names_present` — множество имён событий, реально встреченных в
    durable-сторе (None → проверка «наличия событий» недоступна, статус
    вычисляется только по декларации/гейту)."""
    if process.version == "0" or not process.stages:
        return STATUS_NOT_RUN
    if not process.declared_instrumented:
        return STATUS_NOT_INSTRUMENTED
    if not _process_enabled(process):
        return STATUS_DISABLED
    if event_names_present is not None:
        if not (set(process.event_names) & set(event_names_present)):
            return STATUS_NOT_RUN
    return STATUS_IMPLEMENTED


def _settings_gate(gate: str) -> bool:
    from config.settings import settings
    return bool(getattr(settings, gate, True))


def _process_enabled(process: ProcessDefinition) -> bool:
    """Kill-switch процесса (master-aware; mca_gates-резолвер либо settings)."""
    if not mca_gates.process_registry_enabled():
        return False
    gate = process.enabled_gate
    if not gate:
        return True
    resolver = _GATE_RESOLVERS.get(gate)
    if resolver:
        fn = getattr(mca_gates, resolver, None)
        if fn is not None:
            try:
                return bool(fn())
            except Exception:      # pragma: no cover
                return True
    return _settings_gate(gate)


async def event_names_present(db) -> frozenset:
    """Имена событий, реально присутствующие в `mca_events` (bounded).

    Fail-open: недоступный store → пустое множество (статус по декларации)."""
    if db is None:
        return frozenset()
    try:
        cursor = await db.db.execute(
            "SELECT DISTINCT event_name FROM mca_events LIMIT 500")
        return frozenset(str(r["event_name"]) for r in await cursor.fetchall())
    except Exception:
        return frozenset()


async def registry_snapshot(db=None) -> dict:
    """Read-only выдача реестра + runtime-статуса (для `mca-17c`/витрины).

    Не бросает; при OFF-гейте реестр не публикуется."""
    result = {
        "enabled": mca_gates.process_registry_enabled(),
        "count": len(PROCESS_REGISTRY),
        "processes": [],
        "pipelines": [],
        "coverage": {},
    }
    if not result["enabled"]:
        return result
    present = await event_names_present(db)
    have_store = db is not None
    statuses: dict = {}
    for p in PROCESS_REGISTRY:
        status = runtime_status(
            p, event_names_present=present if have_store else None)
        statuses[status] = statuses.get(status, 0) + 1
        result["processes"].append({
            "process_id": p.process_id,
            "version": p.version,
            "purpose": p.purpose,
            "inputs": list(p.inputs),
            "outputs": list(p.outputs),
            "stages": list(p.stages),
            "branches": list(p.branches),
            "trigger_kind": p.trigger_kind,
            "schedule": p.schedule,
            "settings_ref": list(p.settings_ref),
            "state_source": list(p.state_source),
            "recovery_ops": list(p.recovery_ops),
            "widget_id": p.widget_id,
            "stages_to_events": dict(p.stages_to_events),
            "instrumentation": list(p.instrumentation),
            "owner_feature": p.owner_feature,
            "event_names": list(p.event_names),
            "status": status,
            "note": p.note,
        })
    for pv in PIPELINE_VERSIONS.values():
        result["pipelines"].append({
            "pipeline_type": pv.pipeline_type,
            "version": pv.version,
            "required": list(pv.required_stages),
            "optional": list(pv.optional_stages),
            "stages": [{"name": s.name, "required": s.required,
                        "stage_type": s.stage_type,
                        "has_fallback": s.has_fallback} for s in pv.stages],
        })
    active = [p for p in PROCESS_REGISTRY if p.stages and p.version != "0"]
    result["coverage"] = {
        "active": len(active),
        "implemented": statuses.get(STATUS_IMPLEMENTED, 0),
        "disabled": statuses.get(STATUS_DISABLED, 0),
        "not_run": statuses.get(STATUS_NOT_RUN, 0),
        "not_instrumented": statuses.get(STATUS_NOT_INSTRUMENTED, 0),
    }
    return result


def coverage_report() -> dict:
    """Отчёт покрытия «реализовано/выключено/не запускается/не инструментировано»."""
    counters = {STATUS_IMPLEMENTED: 0, STATUS_DISABLED: 0, STATUS_NOT_RUN: 0,
                STATUS_NOT_INSTRUMENTED: 0}
    rows = []
    for p in PROCESS_REGISTRY:
        status = runtime_status(p)
        counters[status] = counters.get(status, 0) + 1
        rows.append({"process_id": p.process_id, "status": status,
                     "owner_feature": p.owner_feature,
                     "reason": p.note or (
                         "declared без инструментирования"
                         if status == STATUS_NOT_INSTRUMENTED else "")})
    return {"counters": counters, "processes": rows}
