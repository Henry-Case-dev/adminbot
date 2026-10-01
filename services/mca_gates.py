"""Раунд 10.27 (MCA Wave 0) — единый реестр kill-switch'ей волны 0.

Политика (ADR-1027-1 D7 / ADR-1027-3 D9; рамка `mca-round1027-arch-frames.md` §3):

* **env-only** `ClassVar[bool]` в `config/settings.py`, **default ON**;
* **резолв per-call** (значение читается при каждом обращении, не кешируется
  на импорте), **никогда не бросает**;
* **OFF = точный паритет baseline** — ровно прежнее поведение, без новых
  записей/эффектов;
* Δ каталога = 0 (`param_catalog.py` не меняется);
* существующие рубильники `DB_LOCK_RESILIENCE_ENABLED` (F0.5/ADR-1024-18),
  `AGENTIC_EVENTS_ENABLED` (ADR-1026-22 D3) **уважаются и не дублируются**.

ВАЖНО: имя модуля — `mca_gates` (не `feature_gates`), чтобы не конфликтовать
с существующим `services/feature_gates.py` (F-10 worker-budget gates).
"""
from __future__ import annotations

from config.settings import settings

# Реестр kill-switch'ей волны 0 (mca-14 / mca-01). Используется тестами
# политики (T-3759/T-3747) и release-manifest'ом: имя → (default, OFF-паритет).
KILL_SWITCHES: dict[str, tuple[bool, str]] = {
    "MCA_SCHEMA_MIGRATIONS_ENABLED": (
        True,
        "legacy-путь миграций (hardcoded `_migrate_*`), без runner/backup",
    ),
    "MCA_TX_OWNERSHIP_ENABLED": (
        True,
        "прежний `write_transaction`: rollback вне lock, отмена ожидающего "
        "может откатить общую connection (baseline-дефект §5.1 сохраняется "
        "по дизайну OFF)",
    ),
    "MCA_TASK_SUPERVISOR_ENABLED": (
        True,
        "без реестра/durable-очереди/coalescing (текущее поведение задач)",
    ),
    "MCA_EVENT_CONTRACT_ENABLED": (
        True,
        "события как сейчас (`emit_agentic_event` без start/outcome/durable)",
    ),
    "MCA_TELEMETRY_STORE_ENABLED": (
        True,
        "только структурный лог, без durable-персистенции (`mca_events`)",
    ),
    "MCA_MESSAGE_IDENTITY_ENABLED": (
        True,
        "legacy ingestion/импорт без канонической идентичности и source "
        "records (`save_smart_message`; паритет baseline 7165ff7)",
    ),
    "MCA_MESSAGE_REVISION_TRACKING_ENABLED": (
        True,
        "редакции без версионирования (текущее поведение baseline)",
    ),
    "MCA_SAFE_FETCH_ENABLED": (
        True,
        "legacy-путь загрузки (как сейчас, без SSRF-обвязки/лимитов-обёртки; "
        "паритет baseline)",
    ),
    "MCA_EGRESS_GUARD_ENABLED": (
        True,
        "без эквивалентного egress-контроля для подпроцессов/yt-dlp/прокси "
        "(legacy; паритет baseline)",
    ),
    "MCA_PROVENANCE_ENABLED": (
        True,
        "legacy-путь без типизированных SourceRef/EvidenceLink/статусов "
        "(новые записи/связи не создаются; паритет baseline)",
    ),
    "MCA_FACT_ATTRIBUTION_ENABLED": (
        True,
        "legacy-атрибуция фактов (`target=asker`, name-scope читатели, "
        "Layer B person_facts не сохраняются; паритет §8.3.2-baseline)",
    ),
    "MCA_EVIDENCE_RECONSTRUCTION_ENABLED": (
        True,
        "восстановление старых записей не запускается (прямо сохранённое "
        "происхождение по-прежнему фиксируется)",
    ),
    # ── mca-07 (ADR-1027-7 D12) ─────────────────────────────────────────────
    "MCA_RETRIEVAL_CONTEXT_ENABLED": (
        True,
        "legacy-путь retrieval/embedding (раздельные каналы без единого "
        "контракта; sha256(casefold+strip) + dim-проверка) — паритет baseline",
    ),
    "MCA_EVIDENCE_BUNDLE_ENABLED": (
        True,
        "legacy-сборка контекста без единого in-memory EvidenceBundle",
    ),
    "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED": (
        True,
        "прежний `_apply_context_budget` (без полного учёта payload/"
        "адаптивности/protected spans)",
    ),
    "MCA_TYPED_RERANKER_ENABLED": (
        True,
        "прежний reranker (без типизированного списка ID; ошибка/пустой парс "
        "→ исходные кандидаты)",
    ),
    "MCA_SUMMARY_SINGLEFLIGHT_ENABLED": (
        True,
        "прежний fire-and-forget без singleflight/high-watermark/CAS",
    ),
    "MCA_CONTEXT_ANSWER_CACHE_ENABLED": (
        True,
        "прежний ответный кеш по одному нормализованному query/chat/user "
        "(text-replay) — паритет baseline; ON = context-keyed политика",
    ),
    # ── mca-17a (ADR-1027-8 D12) — ядро наблюдаемости ───────────────────────
    "MCA_OBSERVABILITY_ENABLED": (
        True,
        "OFF → паритет baseline целиком (без реестра/span/lifecycle/watchdog/"
        "инцидентов; `emit_mca_event`/ExecutionGraph как есть)",
    ),
    "MCA_PROCESS_REGISTRY_ENABLED": (
        True,
        "OFF → реестр процессов не публикуется/не регистрируется",
    ),
    "MCA_TRACE_SPAN_ENABLED": (
        True,
        "OFF → события без расширенных span-полей (только контракт MCA-13)",
    ),
    "MCA_JOB_LIFECYCLE_ENABLED": (
        True,
        "OFF → lifecycle/`partial`/`degraded`/linked job не вычисляются",
    ),
    "MCA_HEARTBEAT_WATCHDOG_ENABLED": (
        True,
        "OFF → нет watchdog/takeover/stale-детекта",
    ),
    "MCA_INCIDENTS_ENABLED": (
        True,
        "OFF → инциденты не группируются/не ведутся",
    ),
    "MCA_INCIDENT_PUSH_ENABLED": (
        True,
        "OFF → доставка инцидентов в миниапп выключена",
    ),
    "MCA_TELEMETRY_SPOOL_ENABLED": (
        True,
        "OFF → нет дискового spool/degraded-счётчика (structural fallback)",
    ),
    # ── mca-04b (ADR-1027-9 D13) — dossier rebuild ──────────────────────────
    "MCA_DOSSIER_REBUILD_ENABLED": (
        True,
        "legacy `run_dossier_rebuild` как сейчас (без нового контракта/"
        "состояний; паритет baseline)",
    ),
    "MCA_DOSSIER_BACKGROUND_PASS_ENABLED": (
        True,
        "фоновый проход по архиву не запускается",
    ),
    "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED": (
        True,
        "read-time восстановление не запускается (инертен при "
        "MCA_EVIDENCE_RECONSTRUCTION_ENABLED=OFF)",
    ),
    "MCA_DOSSIER_RECLASSIFY_ENABLED": (
        True,
        "безопасная реклассификация накопленных данных не выполняется",
    ),
    "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED": (
        True,
        "прямая запись как сейчас (без staging/generation)",
    ),
    "MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED": (
        True,
        "gate mca-07 FTS-only как сейчас (активация поколения не выполняется)",
    ),
    "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED": (
        True,
        "прежний namespace-отпечаток импорта (legacy_import_v1/v1-digest)",
    ),
    # ── mca-05 (ADR-1027-12 D13) — episodes/stories ─────────────────────────
    "MCA_EPISODES_ENABLED": (
        True,
        "legacy-путь целиком: `lore_stories`/компилятор/mca-07 канал работают "
        "как сегодня (пайплайн/backfill/фасад неактивны; паритет baseline)",
    ),
    "MCA_EPISODES_BACKFILL_ENABLED": (
        True,
        "фоновый backfill по архиву не запускается (инертен при master OFF)",
    ),
    "MCA_EPISODES_CONTINUATION_ENABLED": (
        True,
        "кандидаты/подтверждения продолжений не строятся (без новых склеек)",
    ),
    "MCA_EPISODES_COMPILER_FACADE_ENABLED": (
        True,
        "компилятор/mca-07 episode-канал как сегодня (legacy `lore_stories` "
        "без фасада нового store)",
    ),
}


def tx_ownership_enabled() -> bool:
    """`MCA_TX_OWNERSHIP_ENABLED` (default ON).

    ON → транзакцией владеет задача, получившая lock; rollback/очистка
    выполняются под lock; отмена ожидающего не меняет чужую транзакцию.
    OFF → прежний `write_transaction` (паритет baseline 7165ff7)."""
    return bool(getattr(settings, "MCA_TX_OWNERSHIP_ENABLED", True))


def task_supervisor_enabled() -> bool:
    """`MCA_TASK_SUPERVISOR_ENABLED` (default ON).

    ON → активны примитивы TaskSupervisor (coalescing/singleflight,
    bounded-очереди; durable `task_jobs` — v14). OFF → прозрачный
    pass-through без коалесинга/ограничения."""
    return bool(getattr(settings, "MCA_TASK_SUPERVISOR_ENABLED", True))


def schema_migrations_enabled() -> bool:
    """`MCA_SCHEMA_MIGRATIONS_ENABLED` (default ON).

    ON → реестр шагов + книга `schema_migrations` + backup/read-back.
    OFF → hardcoded legacy-последовательность `_migrate_*` (паритет baseline)."""
    return bool(getattr(settings, "MCA_SCHEMA_MIGRATIONS_ENABLED", True))


def event_contract_enabled() -> bool:
    """`MCA_EVENT_CONTRACT_ENABLED` (default ON).

    ON → контракт §17.1: `start`+терминальный `outcome`, словарь `reason_code`,
    ошибки/агрегация. OFF → события ровно как в baseline (без start/outcome)."""
    return bool(getattr(settings, "MCA_EVENT_CONTRACT_ENABLED", True))


def telemetry_store_enabled() -> bool:
    """`MCA_TELEMETRY_STORE_ENABLED` (default ON).

    ON → терминальные события durable-персистятся в `mca_events` (v15).
    OFF → только структурный лог, без durable-записи (паритет baseline)."""
    return bool(getattr(settings, "MCA_TELEMETRY_STORE_ENABLED", True))


def message_identity_enabled() -> bool:
    """`MCA_MESSAGE_IDENTITY_ENABLED` (default ON, ADR-1027-4 D9).

    ON → producers пишут каноническую идентичность `(chat_id, tg_message_id)`,
    source records и поля времени/ролей; OFF → legacy-путь
    (`save_smart_message`), паритет baseline 7165ff7."""
    return bool(getattr(settings, "MCA_MESSAGE_IDENTITY_ENABLED", True))


def message_revision_tracking_enabled() -> bool:
    """`MCA_MESSAGE_REVISION_TRACKING_ENABLED` (default ON, ADR-1027-4 D9).

    ON → правки человека создают версию (`message_revisions`) и обновляют
    актуальную; OFF → редакции без версионирования (текущее поведение)."""
    return bool(getattr(settings, "MCA_MESSAGE_REVISION_TRACKING_ENABLED",
                        True))


def safe_fetch_enabled() -> bool:
    """`MCA_SAFE_FETCH_ENABLED` (default ON, ADR-1027-5 D12).

    ON → внешние загрузки идут через SafeFetcher (SSRF/redirect/лимиты/
    peer-проверка). OFF → legacy-путь загрузки (паритет baseline 7165ff7)."""
    return bool(getattr(settings, "MCA_SAFE_FETCH_ENABLED", True))


def egress_guard_enabled() -> bool:
    """`MCA_EGRESS_GUARD_ENABLED` (default ON, ADR-1027-5 D12).

    ON → in-process loopback egress-guard для медиа-подпроцессов/yt-dlp/
    transcript-api. OFF → legacy без egress-обвязки (паритет baseline)."""
    return bool(getattr(settings, "MCA_EGRESS_GUARD_ENABLED", True))


def provenance_enabled() -> bool:
    """`MCA_PROVENANCE_ENABLED` (default ON, ADR-1027-6 D11).

    ON → создаются/читаются типизированные SourceRef/EvidenceLink/статусы.
    OFF → legacy-путь (`source_ids`/`tg_message_id` как есть; новые записи/
    связи не создаются; паритет baseline)."""
    return bool(getattr(settings, "MCA_PROVENANCE_ENABLED", True))


def fact_attribution_enabled() -> bool:
    """`MCA_FACT_ATTRIBUTION_ENABLED` (default ON, ADR-1027-6 D11).

    Инертен при `MCA_PROVENANCE_ENABLED=OFF`: без provenance субъект-атрибуция
    не создаётся, поэтому effective = OFF. ON → субъект-атрибуция личных
    фактов + subject-scope читателей + сохранение Layer B `person_facts`.
    OFF → legacy-атрибуция (`target=asker`, name-scope; паритет baseline)."""
    if not provenance_enabled():
        return False
    return bool(getattr(settings, "MCA_FACT_ATTRIBUTION_ENABLED", True))


def evidence_reconstruction_enabled() -> bool:
    """`MCA_EVIDENCE_RECONSTRUCTION_ENABLED` (default ON, ADR-1027-6 D11).

    Инертен при `MCA_PROVENANCE_ENABLED=OFF`. ON → восстановление старых
    записей (read-time/backfill-recovery) разрешено; OFF → восстановление не
    запускается (прямо сохранённое происхождение по-прежнему фиксируется)."""
    if not provenance_enabled():
        return False
    return bool(getattr(settings, "MCA_EVIDENCE_RECONSTRUCTION_ENABLED", True))


def retrieval_context_enabled() -> bool:
    """`MCA_RETRIEVAL_CONTEXT_ENABLED` (default ON, ADR-1027-7 D12).

    ON → единый retrieval-контракт (комбинация каналов + эпизоды-первыми для
    истории) и embedding-identity-политика (fingerprint/generation). OFF →
    legacy-вызовы каналов и прежний `sha256(casefold+strip)` + dim-проверка
    (паритет baseline)."""
    return bool(getattr(settings, "MCA_RETRIEVAL_CONTEXT_ENABLED", True))


def evidence_bundle_enabled() -> bool:
    """`MCA_EVIDENCE_BUNDLE_ENABLED` (default ON, ADR-1027-7 D5/D6).

    ON → контекст собирается в один in-memory EvidenceBundle, проходящий все
    стадии. OFF → legacy-сборка контекста (паритет baseline)."""
    return bool(getattr(settings, "MCA_EVIDENCE_BUNDLE_ENABLED", True))


def adaptive_context_budget_enabled() -> bool:
    """`MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` (default ON, ADR-1027-7 D7).

    ON → полный учёт payload (system/developer/personality, tools, tool
    results, output reserve, overhead) + консервативная оценка + protected
    spans + pre-flight. OFF → прежний `_apply_context_budget`."""
    return bool(getattr(settings, "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED", True))


def typed_reranker_enabled() -> bool:
    """`MCA_TYPED_RERANKER_ENABLED` (default ON, ADR-1027-7 D3).

    ON → reranker возвращает типизированный список ID; валидный пустой список
    ≠ все кандидаты; `invalid`/`timeout`/`error` → отдельный статус +
    детерминированный bounded fallback. OFF → прежнее поведение."""
    return bool(getattr(settings, "MCA_TYPED_RERANKER_ENABLED", True))


def summary_singleflight_enabled() -> bool:
    """`MCA_SUMMARY_SINGLEFLIGHT_ENABLED` (default ON, ADR-1027-7 D8).

    ON → singleflight/coalescing + high-watermark/CAS сводок (поздний старый
    запрос не перезаписывает новую версию). OFF → прежний fire-and-forget."""
    return bool(getattr(settings, "MCA_SUMMARY_SINGLEFLIGHT_ENABLED", True))


def context_answer_cache_enabled() -> bool:
    """`MCA_CONTEXT_ANSWER_CACHE_ENABLED` (default ON, ADR-1027-7 D9).

    ON → MCA-07 context-keyed политика: legacy text-replay по одному
    нормализованному query/chat/user для контекстных ответов отключён;
    update-дедуп по `(chat_id, tg_message_id)` сохранён. OFF → прежний
    ответный кеш (паритет baseline)."""
    return bool(getattr(settings, "MCA_CONTEXT_ANSWER_CACHE_ENABLED", True))


# ── mca-17a (ADR-1027-8 D6/D7/D12): ядро наблюдаемости ─────────────────────
# Мастер `MCA_OBSERVABILITY_ENABLED`: OFF → паритет baseline целиком. Под-гейты
# инертны при master OFF (кроме fault-injection — он вне product-контура).

def observability_enabled() -> bool:
    """`MCA_OBSERVABILITY_ENABLED` (мастер, default ON, ADR-1027-8 D12)."""
    return bool(getattr(settings, "MCA_OBSERVABILITY_ENABLED", True))


def process_registry_enabled() -> bool:
    """`MCA_PROCESS_REGISTRY_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_PROCESS_REGISTRY_ENABLED", True))


def trace_span_enabled() -> bool:
    """`MCA_TRACE_SPAN_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_TRACE_SPAN_ENABLED", True))


def job_lifecycle_enabled() -> bool:
    """`MCA_JOB_LIFECYCLE_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_JOB_LIFECYCLE_ENABLED", True))


def heartbeat_watchdog_enabled() -> bool:
    """`MCA_HEARTBEAT_WATCHDOG_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_HEARTBEAT_WATCHDOG_ENABLED", True))


def incidents_enabled() -> bool:
    """`MCA_INCIDENTS_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_INCIDENTS_ENABLED", True))


def incident_push_enabled() -> bool:
    """`MCA_INCIDENT_PUSH_ENABLED` (default ON; инертен при master/incidents)."""
    if not observability_enabled() or not incidents_enabled():
        return False
    return bool(getattr(settings, "MCA_INCIDENT_PUSH_ENABLED", True))


def telemetry_spool_enabled() -> bool:
    """`MCA_TELEMETRY_SPOOL_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_TELEMETRY_SPOOL_ENABLED", True))


# ── mca-04b (ADR-1027-9 D13): dossier rebuild ───────────────────────────────
# Мастер + под-гейты; `MCA_DOSSIER_*` инертны при OFF нижележащих.

def dossier_rebuild_enabled() -> bool:
    """`MCA_DOSSIER_REBUILD_ENABLED` (мастер, default ON).

    ON → единый контракт full rebuild (keyset/staging/честная финализация);
    OFF → legacy `run_dossier_rebuild` как сейчас (паритет baseline)."""
    return bool(getattr(settings, "MCA_DOSSIER_REBUILD_ENABLED", True))


def dossier_background_pass_enabled() -> bool:
    """`MCA_DOSSIER_BACKGROUND_PASS_ENABLED` (default ON; инертен при master)."""
    if not dossier_rebuild_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_BACKGROUND_PASS_ENABLED", True))


def dossier_read_reconstruction_enabled() -> bool:
    """`MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED` (default ON).

    Инертен при `MCA_EVIDENCE_RECONSTRUCTION_ENABLED=OFF` (§98 — не
    дублируется): без нижележащего гейта восстановление невозможно."""
    if not evidence_reconstruction_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED",
                        True))


def dossier_reclassify_enabled() -> bool:
    """`MCA_DOSSIER_RECLASSIFY_ENABLED` (default ON; инертен при master)."""
    if not dossier_rebuild_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_RECLASSIFY_ENABLED", True))


def dossier_staging_activation_enabled() -> bool:
    """`MCA_DOSSIER_STAGING_ACTIVATION_ENABLED` (default ON; инертен при master).

    ON → staging/generation + атомарная активация; OFF → прямая запись
    существующими writer'ами (паритет baseline-записи)."""
    if not dossier_rebuild_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED",
                        True))


def embedding_generation_activation_enabled() -> bool:
    """`MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` (default ON).

    ON → операция активации vec-поколения (N-MCA07-1, REUSE v18);
    OFF → gate mca-07 FTS-only как сейчас."""
    return bool(getattr(settings, "MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED",
                        True))


def dossier_namespace_fingerprint_v2_enabled() -> bool:
    """`MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED` (default ON, L-MCA03-8).

    ON → namespace-отпечаток импорта версионируется (`v2` в отпечатке,
    content-fingerprint); OFF → прежний `import:<tag>:<digest>`."""
    return bool(getattr(
        settings, "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED", True))


# ── mca-05 (ADR-1027-12 D13): episodes/stories ──────────────────────────────
# Мастер + под-гейты; под-гейты инертны при master OFF.

def episodes_enabled() -> bool:
    """`MCA_EPISODES_ENABLED` (мастер, default ON, ADR-1027-12 D13).

    ON → модель/пайплайн эпизодов/историй активны; OFF → точный паритет
    baseline (`lore_stories`/компилятор/mca-07 канал работают как сегодня)."""
    return bool(getattr(settings, "MCA_EPISODES_ENABLED", True))


def episodes_backfill_enabled() -> bool:
    """`MCA_EPISODES_BACKFILL_ENABLED` (default ON; инертен при master OFF)."""
    if not episodes_enabled():
        return False
    return bool(getattr(settings, "MCA_EPISODES_BACKFILL_ENABLED", True))


def episodes_continuation_enabled() -> bool:
    """`MCA_EPISODES_CONTINUATION_ENABLED` (default ON; инертен при master)."""
    if not episodes_enabled():
        return False
    return bool(getattr(settings, "MCA_EPISODES_CONTINUATION_ENABLED", True))


def episodes_compiler_facade_enabled() -> bool:
    """`MCA_EPISODES_COMPILER_FACADE_ENABLED` (default ON; инертен при master).

    ON → компилятор и mca-07 episode-канал читают новый store через фасад
    (legacy `lore_stories` сохраняются); OFF → как сегодня (legacy-путь)."""
    if not episodes_enabled():
        return False
    return bool(getattr(settings, "MCA_EPISODES_COMPILER_FACADE_ENABLED", True))


def episodes_batch_max_messages() -> int:
    """`MCA_EPISODES_BATCH_MAX_MESSAGES` (env-only, default 500).

    Размер ПОРЦИИ обработки в сообщениях (не токен-бюджет, ADR-1027-12 D6
    по прецеденту ADR-1027-9 D14); значение <1 → 500."""
    try:
        return max(1, int(getattr(settings, "MCA_EPISODES_BATCH_MAX_MESSAGES",
                                  500)))
    except Exception:      # pragma: no cover - защитная ветка
        return 500


def episodes_direct_priority_enabled() -> bool:
    """`MCA_EPISODES_DIRECT_PRIORITY_ENABLED` (env-only, default ON).

    ON → фоновая сборка эпизодов не блокирует direct-flow (приоритет прямых
    ответов)."""
    return bool(getattr(settings, "MCA_EPISODES_DIRECT_PRIORITY_ENABLED", True))


def dossier_direct_priority_enabled() -> bool:
    """`MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (env-only, default ON).

    ON → фоновая пересборка не блокирует direct-flow (приоритет прямых
    ответов)."""
    return bool(getattr(settings, "MCA_DOSSIER_DIRECT_PRIORITY_ENABLED", True))


def dossier_batch_max_messages() -> int:
    """`MCA_DOSSIER_BATCH_MAX_MESSAGES` (env-only, default 500).

    Размер ПОРЦИИ обработки в сообщениях (не токен-бюджет, ADR D14);
    значение <1 → 500."""
    try:
        return max(1, int(getattr(settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES",
                                  500)))
    except Exception:      # pragma: no cover - защитная ветка
        return 500


def fault_injection_enabled() -> bool:
    """`MCA_FAULT_INJECTION_ENABLED` (default **OFF**; dev/test-only).

    Не product-функция и не виджет; вне effective-state §20.2 (§5.5)."""
    return bool(getattr(settings, "MCA_FAULT_INJECTION_ENABLED", False))


def _int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(getattr(settings, name, default)))
    except Exception:      # pragma: no cover - защитная ветка
        return default


def job_heartbeat_seconds() -> int:
    """`MCA_JOB_HEARTBEAT_SECONDS` (env-only, default 15)."""
    return _int_setting("MCA_JOB_HEARTBEAT_SECONDS", 15)


def job_stale_seconds() -> int:
    """`MCA_JOB_STALE_SECONDS` (env-only, default 60)."""
    return _int_setting("MCA_JOB_STALE_SECONDS", 60)


def incident_push_interval_seconds() -> int:
    """`MCA_INCIDENT_PUSH_INTERVAL_SECONDS` (env-only, default 10; ≤10 цель)."""
    return _int_setting("MCA_INCIDENT_PUSH_INTERVAL_SECONDS", 10)


def telemetry_spool_max_events() -> int:
    """`MCA_TELEMETRY_SPOOL_MAX_EVENTS` (env-only, default 2000)."""
    return _int_setting("MCA_TELEMETRY_SPOOL_MAX_EVENTS", 2000)


_PROGRESS_STALL_BY_TYPE = {
    "llm": "MCA_PROGRESS_STALL_LLM_SECONDS",
    "video": "MCA_PROGRESS_STALL_VIDEO_SECONDS",
    "archive": "MCA_PROGRESS_STALL_ARCHIVE_SECONDS",
}


def progress_stall_seconds(stage_type: str | None = None) -> int:
    """Порог progress-stall по типу стадии (`MCA_PROGRESS_STALL_<TYPE>_SECONDS`).

    Тип по умолчанию — общий (`MCA_PROGRESS_STALL_DEFAULT_SECONDS`, 600).
    Законная длительная транскрибация/архив не объявляется упавшей по общему
    таймеру stale (ADR-1027-8 D7)."""
    key = _PROGRESS_STALL_BY_TYPE.get(str(stage_type or "").lower())
    if key is not None:
        return _int_setting(key, _int_setting(
            "MCA_PROGRESS_STALL_DEFAULT_SECONDS", 600))
    return _int_setting("MCA_PROGRESS_STALL_DEFAULT_SECONDS", 600)


def detailed_log_retention_days() -> int:
    """`MCA_DETAILED_LOG_RETENTION_DAYS` (env-only, default 14).

    Ретенция подробных диагностических строк (структурный лог/ring). Никогда
    не бросает; значение <1 → 14."""
    try:
        return max(1, int(getattr(settings, "MCA_DETAILED_LOG_RETENTION_DAYS",
                                  14)))
    except Exception:      # pragma: no cover - защитная ветка
        return 14


def terminal_event_retention_days() -> int:
    """`MCA_TERMINAL_EVENT_RETENTION_DAYS` (env-only, default 90).

    Ретенция терминальных событий `mca_events`. Никогда не бросает;
    значение <1 → 90."""
    try:
        return max(1, int(getattr(settings, "MCA_TERMINAL_EVENT_RETENTION_DAYS",
                                  90)))
    except Exception:      # pragma: no cover - защитная ветка
        return 90
