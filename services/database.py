import asyncio
import contextlib
import dataclasses
import datetime
import functools
import hashlib
import json
import logging
import re
import time
from typing import Awaitable, Callable

import aiosqlite
from pathlib import Path

from config.settings import settings
from services import hot_config as hot
from services.mca_gates import (
    schema_migrations_enabled as _schema_migrations_enabled,
    summary_singleflight_enabled as _summary_singleflight_enabled,
    tx_ownership_enabled as _tx_ownership_enabled,
)
from services.graph_stoplist import (
    METAFACT_PENALTY_IMPORTANCE,
    is_center_stopword,
    is_metafact_stopword,
)
from services.user_relations import decay_weight, decide_stage, \
    relations_limits, stage_candidate

logger = logging.getLogger(__name__)

# ── Тумблер memory.infinite_retention (фаза 2, T-756): гейты TTL/retention ──
# ON = «сырьё и факты памяти не удаляются и не сжимаются по TTL/ретенции»
# (для исторического импорта). Список точек-гейтов (самодокументация):
#   G1 summary_memory.compress_and_purge — extract-only ветка (без сжатия/
#      удаления/архива); пачки импортированных строк (import_key IS NOT NULL)
#      исключаются из extract (get_smart_raw exclude_imported=True);
#      обработанные live-строки помечаются history_processed=1
#      (mark_smart_messages_processed) — повторный крон не пере-экстрактит;
#   G2 summary_memory._purge_archive — skip (архив живёт до OFF);
#   G3 database.purge_expired_graph_facts (:1261) — return 0 без SQL;
#   G4 database.purge_unconfirmed_graph_facts (:1792) — return 0;
#   G5 database.trim_compression_log (:1814) — return 0;
#   G6 memory_maintenance.review — фазы expired/unconfirmed/trim скипаются
#      самими гейтами G3-G5 (merge-фазы — слияние, не удаление — работают).
# Явные команды «забудь»/«/clear» работают всегда (гейтов не имеют).
# Чтение: hot.get("memory.infinite_retention", settings.INFINITE_RETENTION).
# Импорт hot_config циклов не создаёт: hot_config → param_catalog →
# config.settings; param_catalog не импортирует database.py.

_RETENTION_PG_KEY = "memory.infinite_retention"


def _infinite_retention_on() -> bool:
    """ON-состояние тумблера бессрочного хранения (фолбэк False без кэша)."""
    return bool(hot.get(_RETENTION_PG_KEY, settings.INFINITE_RETENTION))

_BUSY_TIMEOUT_MS = 5000          # R46-8: «database is locked» → ждём до 5с
_REFRESH_ACTIVE_CAP = 5000       # recalc_chat_users: потолок участников окна

# ── F0.5 (раунд 10.25, ADR-1025-5 — AMEND ADR-1024-18) ─────────────────────
# Bounded retry на `database is locked` для main write-path + сериализация
# многошаговых транзакций (single-writer). Зеркало memory_rebuild.py:71-72 и
# smart_cache.py:33-35; значения — локальные константы.
_LOCK_RETRIES = 3                # зеркало services/memory_rebuild.py:71
_LOCK_BACKOFF = 0.1              # зеркало services/memory_rebuild.py:72

# In-process счётчик исчерпаний (Δ DDL = 0: метрика = лог + счётчик; сброс
# процесса = сброс счётчика — событие остаётся в логе).
_lock_exhausted_total = 0
# MCA-13 §17.4: in-process счётчик выполненных retry на `locked` (метрика
# витрины `lock retries`); Δ DDL = 0, сброс процесса = сброс счётчика.
_lock_retry_total = 0


def database_lock_exhausted_total() -> int:
    """F0.5: число исчерпаний retry на `database is locked` в этом процессе.

    Δ DDL = 0 (PG-таблиц/миграций нет). Сброс процесса = сброс счётчика;
    само событие остаётся в логе (`event=database_lock_exhausted`)."""
    return _lock_exhausted_total


def database_lock_retry_total() -> int:
    """MCA-13 §17.4: число выполненных retry на `database is locked`.

    Δ DDL = 0 (in-process счётчик); сброс процесса = сброс счётчика."""
    return _lock_retry_total


def _lock_resilience_enabled() -> bool:
    """F0.5: kill-switch `DB_LOCK_RESILIENCE_ENABLED` (env-only ClassVar,
    default ON). OFF → ровно прежнее поведение: без сериализации и повторов."""
    return bool(getattr(settings, "DB_LOCK_RESILIENCE_ENABLED", True))


_SCHEMA_VERSION = 1              # PRAGMA user_version; 0 = до Epic 46 (R46-8)
_SCHEMA_VERSION_DIRECT_CHAT = 2  # Epic 50 (58.7): user_version 1→2
_SCHEMA_VERSION_EPIC60 = 3       # Epic 60 (63.3): user_version 2→3
_SCHEMA_VERSION_VIDEO_ORIGINS = 4  # Раунд 3 (3.6/B7): user_version 3→4
_SCHEMA_VERSION_USER_MEMORY = 5  # Раунд 4 (T-713, 3.4.3): user_version 4→5
_SCHEMA_VERSION_CHAT_PROTECTED_FACTS = 6  # Раунд 5 (T-731, 3.2.1): 5→6
_SCHEMA_VERSION_HISTORY_IMPORT = 7  # Фаза 2 (T-758): 6→7 (message_timestamp +
                                    # history_import + smart_messages.import_key)
_SCHEMA_VERSION_AGI_MEMORY_V8 = 8  # Раунд 9 (T-822, spec §3.3.1): 7→8 —
                                # graph_facts rebuild (importance/source_ids/
                                # kind/belief_meta + origin 'derived_belief').
                                # Историческая ступень каскада — НЕ цель.
_SCHEMA_VERSION_AGI_MEMORY = 9   # Раунд 10.14 (F1 anti-echo-self-reply,
                                # ADR-1014-2 D2 / spec §2.1): 8→9 — graph_facts
                                # rebuild (origin '+ bot_self_reply').
                                # Историческая ступень каскада — НЕ цель.
_SCHEMA_VERSION_EDGES_FACT_ID = 10  # Раунд 10.18 (F3 graph-density-scoring-
                                # stoplist, ADR-1018-3 D1): 9→10 — edges
                                # ADD COLUMN fact_id (provenance ребра → факт
                                # для скоринга Σ importance). Историческая
                                # ступень каскада — НЕ текущая цель.
_SCHEMA_VERSION_IMPORT_KEY_CHAT_SCOPE = 11  # Раунд 10.19 (F7 memory-
                                # retention-health, ADR-1019-6 D1b/D7, UPD3
                                # п.2): 10→11 — изоляция импорта по чату:
                                # idx_smart_messages_import_key (ГЛОБАЛЬНЫЙ
                                # UNIQUE) → idx_smart_messages_chat_import_key
                                # UNIQUE(chat_id, import_key); import_checkpoints
                                # ключ (path, chat_id). Формула import_key НЕ
                                # меняется (идемпотентность 1.27M строк).
                                # Это ТЕКУЩАЯ цель user_version.
_SCHEMA_VERSION_GRAPH_FACTS_V12 = 12  # Раунд 10.20 (БЛОК 7.3b, ADR-1020-1
                                # ред. 3 / ADR-1020-7 §3, T-1924): 11→12 —
                                # graph_facts ADD COLUMN tg_message_id INTEGER
                                # (nullable) + forward_from TEXT NOT NULL
                                # DEFAULT '' (provenance: ID-политика `tg:` и
                                # сегмент «Переслано:»). PG — no-op (таблицы
                                # graph_facts в PG нет). Это ТЕКУЩАЯ цель.

# ── Раунд 10.27 (MCA Wave 0, `mca-14-schema-additive`, ADR-1027-1 D1/D8) ────
# v13 — книга реестра применённых миграций (`schema_migrations`). Δ DDL
# волны 0: v13 (mca-14) → v14 (mca-01, `task_jobs`) → v15 (mca-13,
# `mca_events`). Индексов у книги нет: `version INTEGER PRIMARY KEY` —
# rowid-алиас, отдельной индексной записи не требует (D5: индексы только
# по реальным запросам/EXPLAIN). Аддитивность: только `CREATE TABLE IF NOT
# EXISTS`; старые таблицы/ID не трогаются (D3).
_SCHEMA_VERSION_SCHEMA_MIGRATIONS = 13
_SCHEMA_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "version INTEGER PRIMARY KEY, "
    "name TEXT NOT NULL, "
    "applied_at INTEGER NOT NULL, "
    "checksum TEXT NOT NULL)"
)

# ── Раунд 10.27 (MCA Wave 0, `mca-01-tx-task-supervisor`, ADR-1027-3 D5/D10) ──
# v14 — durable-очередь фоновых задач `task_jobs` (рамка §1.1.1). Каждая
# будущая DDL-фича добавляет СВОЮ строку реестра; эта — `mca-01`. Старые
# таблицы/ID не трогаются (аддитивно). PG — no-op.
_SCHEMA_VERSION_TASK_JOBS = 14
_TASK_JOBS_DDL = (
    "CREATE TABLE IF NOT EXISTS task_jobs ("
    "job_id TEXT PRIMARY KEY, "
    "owner TEXT NOT NULL, "
    "kind TEXT NOT NULL, "
    "coalesce_key TEXT, "
    "payload TEXT, "
    "status TEXT NOT NULL, "
    "reason_code TEXT, "
    "result_ref TEXT, "
    "error_code TEXT, "
    "attempt INTEGER NOT NULL DEFAULT 0, "
    "max_attempts INTEGER NOT NULL DEFAULT 1, "
    "deadline_at INTEGER, "
    "heartbeat_at INTEGER, "
    "generation INTEGER NOT NULL DEFAULT 0, "
    "fencing_token INTEGER NOT NULL DEFAULT 0, "
    "created_at INTEGER NOT NULL, "
    "updated_at INTEGER NOT NULL, "
    "finished_at INTEGER)"
)
# Индексы v14 — по реальным запросам планировщика (T-3740):
#   * выборка очереди по статусу в порядке создания (recover/next);
#   * singleflight по активным `coalesce_key` (unique partial).
_TASK_JOBS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_task_jobs_status_created "
    "ON task_jobs (status, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_jobs_coalesce_active "
    "ON task_jobs (coalesce_key) WHERE coalesce_key IS NOT NULL "
    "AND status IN ('queued', 'running')",
)

# ── Раунд 10.27 (MCA Wave 0, `mca-13-event-contract`, ADR-1027-2 D4/D11) ─────
# v15 — durable-стор терминальных событий `mca_events` + агрегаты (рамка
# §1.1.2). Единственный store телеметрии; `mca-17a` читает ЕГО, второй не
# создаётся. Старые таблицы/ID не трогаются. PG — no-op.
_SCHEMA_VERSION_MCA_EVENTS = 15
_MCA_EVENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "ts INTEGER NOT NULL, "
    "level TEXT NOT NULL, "
    "event_name TEXT NOT NULL, "
    "outcome TEXT NOT NULL, "
    "trace_id TEXT, "
    "operation_id TEXT, "
    "parent_operation_id TEXT, "
    "chat_id INTEGER, "
    "component TEXT, "
    "stage TEXT, "
    "reason_code TEXT, "
    "duration_ms INTEGER, "
    "attempt INTEGER, "
    "config_version TEXT, "
    "model TEXT, "
    "provider TEXT, "
    "entity_ids TEXT, "
    "usage_json TEXT, "
    "error_json TEXT, "
    "source_ref_json TEXT)"
)
_MCA_EVENT_AGGREGATES_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_event_aggregates ("
    "fingerprint TEXT PRIMARY KEY, "
    "count INTEGER NOT NULL DEFAULT 0, "
    "first_ts INTEGER NOT NULL, "
    "last_ts INTEGER NOT NULL, "
    "first_trace_id TEXT, "
    "first_error_json TEXT)"
)
# Индексы v15 — по реальным фильтрам §17.4 (trace/chat+component/reason/ts).
_MCA_EVENTS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_events_ts ON mca_events (ts)",
    "CREATE INDEX IF NOT EXISTS idx_mca_events_trace ON mca_events (trace_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_events_chat_component "
    "ON mca_events (chat_id, component)",
    "CREATE INDEX IF NOT EXISTS idx_mca_events_reason "
    "ON mca_events (reason_code)",
)

# ── Раунд 10.27 (MCA Wave 1, `mca-03-message-identity`, ADR-1027-4 D3/D7/D11) ─
# v16 — логическая идентичность `(chat_id, tg_message_id)`, время события,
# роли, версии и mapping `chat_id`. Всё АДДИТИВНО (ALTER ADD COLUMN + CREATE
# TABLE/INDEX IF NOT EXISTS); старые `id`/`timestamp`/FTS не переименовываются
# и не удаляются (mca-14 D3). Новые nullable-колонки = честный unknown.
_SCHEMA_VERSION_MESSAGE_IDENTITY = 16
# 18 nullable-колонок `smart_messages` (порядок = порядок DDL spec §5).
_MESSAGE_IDENTITY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("sent_at", "INTEGER"),
    ("ingested_at", "INTEGER"),
    ("edited_at", "INTEGER"),
    ("sent_at_source", "TEXT"),
    ("source_kind", "TEXT"),
    ("namespace", "TEXT"),
    ("source_record_id", "TEXT"),
    ("caption", "TEXT"),
    ("content_hash", "TEXT"),
    ("media_ref", "TEXT"),
    ("reply_to_kind", "TEXT"),
    ("reply_to_author_id", "INTEGER"),
    ("quote_text", "TEXT"),
    ("quote_author_id", "INTEGER"),
    ("forward_author_id", "INTEGER"),
    ("message_state", "TEXT"),
    ("state_evidence", "TEXT"),
    ("current_revision", "INTEGER"),
)
# Вхождения сообщений (namespace + stable local record id, НЕ Telegram ID).
_MESSAGE_SOURCE_RECORDS_DDL = (
    "CREATE TABLE IF NOT EXISTS message_source_records ("
    "source_record_id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "message_id INTEGER NOT NULL, "
    "namespace TEXT NOT NULL, "
    "local_record_id TEXT, "
    "tg_message_id INTEGER, "
    "chat_id INTEGER NOT NULL, "
    "source_kind TEXT NOT NULL, "
    "observed_at INTEGER NOT NULL, "
    "UNIQUE (namespace, local_record_id))"
)
# Версии сообщений (редакция/исчезновение по свидетельству).
_MESSAGE_REVISIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS message_revisions ("
    "revision_id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "message_id INTEGER NOT NULL, "
    "chat_id INTEGER NOT NULL, "
    "tg_message_id INTEGER, "
    "revision_no INTEGER NOT NULL, "
    "revision_kind TEXT NOT NULL, "
    "text TEXT, "
    "caption TEXT, "
    "content_hash TEXT NOT NULL, "
    "evidence_kind TEXT, "
    "editor_user_id INTEGER, "
    "created_at INTEGER NOT NULL, "
    "UNIQUE (message_id, revision_no))"
)
# Явный mapping исторических смен chat_id (только по подтверждённым данным).
_CHAT_ID_MIGRATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS chat_id_migrations ("
    "old_chat_id INTEGER NOT NULL, "
    "new_chat_id INTEGER NOT NULL, "
    "evidence TEXT NOT NULL, "
    "observed_at INTEGER NOT NULL, "
    "PRIMARY KEY (old_chat_id, new_chat_id))"
)
_MESSAGE_IDENTITY_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_message_source_records_message "
    "ON message_source_records(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_message_source_records_chat_tg "
    "ON message_source_records(chat_id, tg_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_message_revisions_message "
    "ON message_revisions(message_id, revision_no)",
)
# Индексы `smart_messages` по каноническому lookup/окну дат (EXPLAIN сверен:
# lookup `chat_id+tg_message_id` и `chat_id+sent_at`).
_SMART_MESSAGES_IDENTITY_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_tg "
    "ON smart_messages(chat_id, tg_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_sent "
    "ON smart_messages(chat_id, sent_at)",
)
# Partial UNIQUE — усиливает каноничность live-строк; создаётся ТОЛЬКО при
# прохождении duplicate pre-check (иначе legacy-дубли сломали бы миграцию).
_SMART_MESSAGES_LIVE_UNIQUE_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_messages_chat_tg_live_unique "
    "ON smart_messages(chat_id, tg_message_id) "
    "WHERE tg_message_id IS NOT NULL AND import_key IS NULL"
)
# Backfill bounded/resumable: guard `sent_at_source IS NULL`, батчами.
_MESSAGE_IDENTITY_BACKFILL_BATCH = 1000
_LEGACY_IMPORT_NAMESPACE = "legacy_import_v1"

# ── Раунд 10.27 (MCA Wave 1, `mca-04a-provenance-contract`, ADR-1027-6 D1/D10) ─
# v17 — типизированные ссылки на источники (`mca_source_refs`), связь
# «объект ↔ источник» (`mca_evidence_links`), статусы происхождения
# (`mca_provenance_status`) + 6 nullable-колонок `graph_facts`. Всё АДДИТИВНО
# (`CREATE TABLE/INDEX IF NOT EXISTS` + `ALTER ADD COLUMN` под guard); старые
# таблицы/ID/FTS/`origin` CHECK не переименовываются и не удаляются (mca-14
# D3). Новые nullable-колонки = честный unknown. PG — no-op (рамка §1.2.2).
# Backfill — ТОЛЬКО прямые ссылки (без семантического поиска: иначе ложный
# `original` — A09/D6).
_SCHEMA_VERSION_PROVENANCE = 17
_PROVENANCE_BACKFILL_BATCH = 500

_PROVENANCE_SOURCE_REFS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_source_refs ("
    "source_ref_id    INTEGER PRIMARY KEY AUTOINCREMENT, "
    "store            TEXT NOT NULL, "
    "entity_type      TEXT NOT NULL, "
    "entity_id        TEXT NOT NULL, "
    "chat_id          INTEGER, "
    "revision         TEXT, "
    "tg_message_id    INTEGER, "
    "dataset_id       TEXT, "
    "source_record_id TEXT, "
    "resolution       TEXT, "
    "created_at       INTEGER NOT NULL)"
)
_PROVENANCE_SOURCE_REFS_INDEX_DDL = (
    # Дедуп типизированного адреса в (store, entity_type) пространстве.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_source_refs_dedup "
    "ON mca_source_refs(store, entity_type, entity_id, "
    "COALESCE(chat_id, -1), COALESCE(revision, ''))",
    # Резолв/листинг по чату и типу (subject-scope/диагностика).
    "CREATE INDEX IF NOT EXISTS idx_mca_source_refs_chat_type "
    "ON mca_source_refs(chat_id, entity_type)",
)
_PROVENANCE_EVIDENCE_LINKS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_evidence_links ("
    "link_id           INTEGER PRIMARY KEY AUTOINCREMENT, "
    "subject_ref_id    INTEGER NOT NULL, "
    "source_ref_id     INTEGER NOT NULL, "
    "link_type         TEXT NOT NULL, "
    "method            TEXT NOT NULL, "
    "verification      TEXT NOT NULL, "
    "independence      TEXT NOT NULL, "
    "claim_key         TEXT, "
    "extractor_version TEXT, "
    "basis             TEXT, "
    "checks_json       TEXT, "
    "established_at    INTEGER NOT NULL, "
    "created_at        INTEGER NOT NULL)"
)
_PROVENANCE_EVIDENCE_LINKS_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_evidence_links_dedup "
    "ON mca_evidence_links(subject_ref_id, source_ref_id, link_type, "
    "COALESCE(claim_key, ''))",
    # Сбор evidence по объекту (A09/A88: «из чего получено»).
    "CREATE INDEX IF NOT EXISTS idx_mca_evidence_links_subject "
    "ON mca_evidence_links(subject_ref_id, link_type)",
    # «Что выведено из источника» (обратный запрос).
    "CREATE INDEX IF NOT EXISTS idx_mca_evidence_links_source "
    "ON mca_evidence_links(source_ref_id)",
)
_PROVENANCE_STATUS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_provenance_status ("
    "object_ref_id     INTEGER PRIMARY KEY, "
    "origin_status     TEXT NOT NULL, "
    "conflict_status   TEXT NOT NULL, "
    "freshness_status  TEXT NOT NULL, "
    "coverage_status   TEXT NOT NULL, "
    "coverage_covered  INTEGER, "
    "coverage_total    INTEGER, "
    "extractor_version TEXT, "
    "updated_at        INTEGER NOT NULL)"
)
# 6 nullable-колонок `graph_facts` (порядок = порядок DDL spec §5).
_PROVENANCE_FACT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("subject_ref_id", "INTEGER"),
    ("attribution_method", "TEXT"),
    ("assertion_kind", "TEXT"),
    ("speaker_author_id", "INTEGER"),
    ("extractor_version", "TEXT"),
    ("provenance_channel", "TEXT"),
)
_PROVENANCE_FACT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_graph_facts_subject_ref "
    "ON graph_facts(subject_ref_id, status)",
)

# ── Раунд 10.27 (MCA Wave 1, `mca-07-retrieval-context`, ADR-1027-7 D4/D12) ──
# v18 — durable-реестр поколений/fingerprint векторных индексов
# (`mca_embedding_index_generations`, +3 индекса) и 5 nullable-колонок
# `embedding_cache` (identity-аудит). Всё АДДИТИВНО (`CREATE ... IF NOT EXISTS`
# + `ALTER ADD COLUMN` под guard); vec-таблицы (`smart_archive`/`graph_facts_vec`)
# НЕ модифицируются (vec0 не поддерживает ALTER; их идентичность обслуживается
# реестром поколений). Старые таблицы/ID/FTS/vec-данные не переименовываются и
# не удаляются (mca-14 D3). Новые nullable-колонки = честный unknown; backfill
# не требуется. PG — no-op (рамка §1.2.3). Бронь: v18 за mca-07 → mca-04b v19+.
_SCHEMA_VERSION_EMBEDDING_IDENTITY = 18

# Статусы поколения индекса (реестр identity).
_EMBEDDING_GENERATION_STATUSES = (
    "active", "building", "superseded", "failed")

_MCA_EMBEDDING_INDEX_GENERATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_embedding_index_generations ("
    "generation_id         INTEGER PRIMARY KEY AUTOINCREMENT, "
    "index_name            TEXT NOT NULL, "
    "generation            INTEGER NOT NULL, "
    "fingerprint           TEXT NOT NULL, "
    "provider              TEXT, "
    "model                 TEXT, "
    "dims                  INTEGER, "
    "preprocessing_version TEXT, "
    "endpoint_fingerprint  TEXT, "
    "status                TEXT NOT NULL, "
    "created_at            INTEGER NOT NULL, "
    "activated_at          INTEGER, "
    "superseded_at         INTEGER)"
)
_MCA_EMBEDDING_INDEX_GENERATIONS_INDEX_DDL = (
    # Монотонность поколений per индекс (основа выбора активного).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_eig_name_gen "
    "ON mca_embedding_index_generations(index_name, generation)",
    # Ровно одно активное поколение на индекс (partial UNIQUE).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_eig_active "
    "ON mca_embedding_index_generations(index_name) WHERE status = 'active'",
    # Lookup по fingerprint (mismatch/диагностика/аудит-связь).
    "CREATE INDEX IF NOT EXISTS idx_mca_eig_fingerprint "
    "ON mca_embedding_index_generations(fingerprint)",
)
# 5 nullable identity-колонок `embedding_cache` (порядок = порядок DDL spec §5).
_EMBEDDING_CACHE_IDENTITY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("provider", "TEXT"),
    ("model", "TEXT"),
    ("preprocessing_version", "TEXT"),
    ("endpoint_fingerprint", "TEXT"),
    ("identity_fingerprint", "TEXT"),
)

# ── Раунд 10.27 (MCA Wave 0 — остаток, `mca-17a-observability-core`, ADR-1027-8 D2) ─
# v19 — durable run/incident-состояние + correlation/span-колонки поверх
# `task_jobs`/`mca_events`. Механизм `mca-14` (§93): аддитивно/идемпотентно,
# self-guard по `sqlite_master`/`PRAGMA table_info`, `user_version` +1, повторный
# прогон — no-op, PG — no-op. `mca_process_registry` НЕ создаётся (реестр
# code-declared, D1). `event_id` = `mca_events.id`; `start`/`end` = `ts`;
# `heartbeat_at`/`fencing_token`/`generation`/`attempt`/`deadline_at` в
# `task_jobs` НЕ дублируются (v14). Бронь: v19 за `mca-17a` → `mca-04b` v20+.
_SCHEMA_VERSION_OBSERVABILITY = 19

# 5.1.1. `mca_pipeline_runs` — durable run/root-job state.
_MCA_PIPELINE_RUNS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_pipeline_runs ("
    "pipeline_run_id   TEXT PRIMARY KEY, "
    "pipeline_type     TEXT NOT NULL, "
    "pipeline_version  TEXT NOT NULL, "
    "root_job_id       TEXT, "
    "status            TEXT NOT NULL, "
    "reason_code       TEXT, "
    "started_at        INTEGER NOT NULL, "
    "finished_at       INTEGER, "
    "heartbeat_at      INTEGER, "
    "progress_at       INTEGER, "
    "deadline_at       INTEGER, "
    "checkpoint_ref    TEXT, "
    "config_version    TEXT, "
    "created_at        INTEGER NOT NULL, "
    "updated_at        INTEGER NOT NULL)"
)
_MCA_PIPELINE_RUNS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_status "
    "ON mca_pipeline_runs (status, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_type_started "
    "ON mca_pipeline_runs (pipeline_type, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_root_job "
    "ON mca_pipeline_runs (root_job_id)",
)

# 5.1.2. `mca_incidents` — durable инциденты (acknowledged ≠ resolved).
_MCA_INCIDENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_incidents ("
    "incident_id        TEXT PRIMARY KEY, "
    "fingerprint        TEXT NOT NULL, "
    "process_id         TEXT, "
    "pipeline_type      TEXT, "
    "stage              TEXT, "
    "severity           TEXT NOT NULL, "
    "title              TEXT, "
    "first_ts           INTEGER NOT NULL, "
    "last_ts            INTEGER NOT NULL, "
    "repeat_count       INTEGER NOT NULL DEFAULT 1, "
    "jobs_json          TEXT, "
    "chats_json         TEXT, "
    "impact             TEXT, "
    "fallback_used      INTEGER NOT NULL DEFAULT 0, "
    "first_trace_id     TEXT, "
    "last_trace_id      TEXT, "
    "acknowledged_at    INTEGER, "
    "acknowledged_by    INTEGER, "
    "resolved_at        INTEGER, "
    "resolution_evidence TEXT, "
    "created_at         INTEGER NOT NULL, "
    "updated_at         INTEGER NOT NULL)"
)
_MCA_INCIDENTS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_incidents_fingerprint "
    "ON mca_incidents (fingerprint, last_ts)",
    "CREATE INDEX IF NOT EXISTS idx_mca_incidents_active "
    "ON mca_incidents (resolved_at, last_ts)",
    "CREATE INDEX IF NOT EXISTS idx_mca_incidents_severity "
    "ON mca_incidents (severity, last_ts)",
)

# 5.1.3. `task_jobs` — correlation/span/progress (8 nullable).
_TASK_JOBS_CORRELATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pipeline_run_id", "TEXT"),
    ("span_id", "TEXT"),
    ("parent_span_id", "TEXT"),
    ("causation_id", "TEXT"),
    ("attempt_id", "TEXT"),
    ("progress_at", "INTEGER"),
    ("next_retry_at", "INTEGER"),
    ("checkpoint_ref", "TEXT"),
)
_TASK_JOBS_CORRELATION_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_task_jobs_pipeline_run "
    "ON task_jobs (pipeline_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_jobs_status_heartbeat "
    "ON task_jobs (status, heartbeat_at)",
    "CREATE INDEX IF NOT EXISTS idx_task_jobs_status_next_retry "
    "ON task_jobs (status, next_retry_at)",
)

# 5.1.4. `mca_events` — расширение span-контракта §27.3 (15 nullable).
_MCA_EVENTS_SPAN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pipeline_run_id", "TEXT"),
    ("pipeline_type", "TEXT"),
    ("pipeline_version", "TEXT"),
    ("span_id", "TEXT"),
    ("parent_span_id", "TEXT"),
    ("linked_span_ids", "TEXT"),
    ("job_id", "TEXT"),
    ("attempt_id", "TEXT"),
    ("causation_id", "TEXT"),
    ("event_sequence", "INTEGER"),
    ("status", "TEXT"),
    ("heartbeat_at", "INTEGER"),
    ("progress_at", "INTEGER"),
    ("deadline_at", "INTEGER"),
    ("checkpoint_ref", "TEXT"),
)
_MCA_EVENTS_SPAN_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_events_pipeline_run "
    "ON mca_events (pipeline_run_id, event_sequence)",
    "CREATE INDEX IF NOT EXISTS idx_mca_events_span "
    "ON mca_events (span_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_events_status "
    "ON mca_events (status)",
)

# ── Раунд 10.27 (MCA Wave 2, `mca-04b-dossier-rebuild`, ADR-1027-9 D8/D13) ──
# v20 — staging/generation исправления досье (§8.3.4): регистр поколений +
# staging-элементы + nullable-тег `graph_facts.dossier_generation_id`
# (NULL = legacy/честный unknown). Механизм `mca-14` (§93): аддитивно/
# идемпотентно, self-guard по `sqlite_master`/`PRAGMA table_info`,
# `user_version` 19→20, повторный прогон — no-op, PG — no-op (GEN-R4).
# Старые таблицы/ID/FTS/vec/`origin` CHECK сохранены. Бронь: v20 за
# `mca-04b` (рамка §1.2.5); **v21 остаётся свободной** (не объявляется).
# Точный DDL — spec §5.2 (нормативный текст, Builder — по нему).
_SCHEMA_VERSION_DOSSIER_STAGING = 20

_MCA_DOSSIER_GENERATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_dossier_generations ("
    "generation_id            TEXT PRIMARY KEY, "
    "chat_id                  INTEGER NOT NULL, "
    "subject_ref_id           INTEGER NOT NULL, "
    "state                    TEXT NOT NULL, "
    "scope_kind               TEXT, "
    "range_from_ts            INTEGER, "
    "range_to_ts              INTEGER, "
    "snapshot_boundary_ts     INTEGER, "
    "snapshot_boundary_id     INTEGER, "
    "extractor_version        TEXT NOT NULL, "
    "kernel_version           TEXT, "
    "counters_json            TEXT, "
    "staging_ref              TEXT, "
    "supersedes_generation_id TEXT, "
    "backup_ref               TEXT, "
    "created_at               INTEGER NOT NULL, "
    "activated_at             INTEGER, "
    "finished_at              INTEGER)"
)
_MCA_DOSSIER_GENERATIONS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_dossier_gen_subject "
    "ON mca_dossier_generations (chat_id, subject_ref_id, state)",
    # Ровно одна активная версия на (chat, subject) — partial UNIQUE.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_dossier_gen_active "
    "ON mca_dossier_generations (chat_id, subject_ref_id) "
    "WHERE state = 'active'",
)
_MCA_DOSSIER_STAGING_ITEMS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_dossier_staging_items ("
    "staging_id         INTEGER PRIMARY KEY AUTOINCREMENT, "
    "generation_id      TEXT NOT NULL, "
    "item_kind          TEXT NOT NULL, "
    "subject_ref_id     INTEGER, "
    "source_ref_id      INTEGER, "
    "classification     TEXT, "
    "payload_json       TEXT NOT NULL, "
    "verification       TEXT NOT NULL, "
    "extractor_version  TEXT, "
    "created_at         INTEGER NOT NULL)"
)
_MCA_DOSSIER_STAGING_ITEMS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_dossier_staging_gen "
    "ON mca_dossier_staging_items (generation_id, item_kind)",
)
# Nullable-колонка `graph_facts` (ALTER под guard `PRAGMA table_info`);
# NULL = legacy/unknown (читатели используют активное поколение).
_GRAPH_FACTS_DOSSIER_GENERATION_COLUMN = ("dossier_generation_id", "TEXT")
_GRAPH_FACTS_DOSSIER_GENERATION_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_graph_facts_dossier_gen "
    "ON graph_facts (dossier_generation_id)",
)
# Закрытый набор состояний поколения (spec §4.4/D8).
DOSSIER_GENERATION_STATES = frozenset(
    {"building", "active", "superseded", "failed"})
# Закрытый набор kind staged-элементов (spec §5.2).
DOSSIER_STAGING_ITEM_KINDS = frozenset(
    {"portrait", "person_fact", "meme", "tree"})
# Закрытый набор verification staged-элементов.
DOSSIER_STAGING_VERIFICATIONS = frozenset(
    {"verified", "tentative", "unknown", "rejected"})

# ── Раунд 10.27 (MCA Wave 2, `mca-05-episodes-stories`, ADR-1027-12 D2) ─────
# v21 — Episode/Story-модель (§9.1/§9.2): 7 таблиц + индексы «по реальным
# запросам» (ADR-1027-12 §5). Механизм `mca-14` (§93): аддитивно/
# идемпотентно, self-guard по `sqlite_master`/`PRAGMA table_info`,
# `user_version` 20→21, повторный прогон — no-op, PG — no-op (GEN-R4).
# Старые `lore_stories`/ID/потребители НЕ трогаются. Nullable = честный
# unknown. Override-колонки `mca_stories` — nullable ALTER под guard
# (ручные правки переживают пересборку — A13). `state` истории
# (`open/closed/uncertain`) ≠ статус job (`task_status_ref`) — разные поля.
_SCHEMA_VERSION_EPISODES_STORIES = 21

_MCA_EPISODES_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_episodes ("
    "episode_id          TEXT PRIMARY KEY, "
    "chat_id             INTEGER NOT NULL, "
    "title               TEXT NOT NULL DEFAULT '', "
    "summary             TEXT NOT NULL DEFAULT '', "
    "participants_json   TEXT NOT NULL DEFAULT '[]', "
    "event_start_ts      INTEGER, "
    "event_end_ts        INTEGER, "
    "discovered_at       INTEGER NOT NULL, "
    "updated_at          INTEGER NOT NULL, "
    "claims_json         TEXT NOT NULL DEFAULT '[]', "
    "outcome             TEXT NOT NULL DEFAULT '', "
    "open_questions      TEXT NOT NULL DEFAULT '', "
    "message_keys_json   TEXT NOT NULL DEFAULT '[]', "
    "segment_key         TEXT NOT NULL DEFAULT '', "
    "extraction_version  TEXT NOT NULL DEFAULT '', "
    "mapping_status      TEXT NOT NULL DEFAULT 'unmapped', "
    "recheck_pending     INTEGER NOT NULL DEFAULT 0, "
    "UNIQUE (chat_id, segment_key))"
)
_MCA_STORIES_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_stories ("
    "story_id             TEXT PRIMARY KEY, "
    "chat_id              INTEGER NOT NULL, "
    "title                TEXT NOT NULL DEFAULT '', "
    "summary              TEXT NOT NULL DEFAULT '', "
    "participants_json    TEXT NOT NULL DEFAULT '[]', "
    "event_start_ts       INTEGER, "
    "event_end_ts         INTEGER, "
    "discovered_at        INTEGER NOT NULL, "
    "updated_at           INTEGER NOT NULL, "
    "claims_json          TEXT NOT NULL DEFAULT '[]', "
    "outcome              TEXT NOT NULL DEFAULT '', "
    "open_questions       TEXT NOT NULL DEFAULT '', "
    "state                TEXT NOT NULL DEFAULT 'open', "
    "verification         TEXT NOT NULL DEFAULT 'unknown', "
    "excluded_from_retrieval INTEGER NOT NULL DEFAULT 0, "
    "active_version_id    TEXT, "
    "expected_version     INTEGER NOT NULL DEFAULT 1, "
    "extractor_version    TEXT NOT NULL DEFAULT '', "
    "task_status_ref      TEXT, "
    "override_title       TEXT, "
    "override_summary     TEXT, "
    "override_outcome     TEXT, "
    "override_state       TEXT, "
    "override_open_questions TEXT)"
)
_MCA_STORY_VERSIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_story_versions ("
    "version_id          TEXT PRIMARY KEY, "
    "story_id            TEXT NOT NULL, "
    "version_no          INTEGER NOT NULL, "
    "payload_json        TEXT NOT NULL, "
    "created_at          INTEGER NOT NULL, "
    "created_by          TEXT NOT NULL DEFAULT 'pipeline', "
    "extractor_version   TEXT, "
    "UNIQUE (story_id, version_no))"
)
_MCA_STORY_EPISODE_LINKS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_story_episode_links ("
    "story_id            TEXT NOT NULL, "
    "episode_id          TEXT NOT NULL, "
    "order_no            INTEGER NOT NULL DEFAULT 0, "
    "PRIMARY KEY (story_id, episode_id))"
)
_MCA_STORY_CONTINUATIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_story_continuations ("
    "continuation_id     INTEGER PRIMARY KEY AUTOINCREMENT, "
    "from_episode_id     TEXT NOT NULL, "
    "to_episode_id       TEXT NOT NULL, "
    "confirmation_json   TEXT, "
    "status              TEXT NOT NULL DEFAULT 'candidate', "
    "created_at          INTEGER NOT NULL, "
    "UNIQUE (from_episode_id, to_episode_id))"
)
_MCA_STORY_REDIRECTS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_story_redirects ("
    "old_kind            TEXT NOT NULL, "
    "old_id              TEXT NOT NULL, "
    "new_kind            TEXT NOT NULL, "
    "new_id              TEXT NOT NULL, "
    "created_at          INTEGER NOT NULL, "
    "PRIMARY KEY (old_kind, old_id))"
)
_MCA_STORY_LEGACY_LINKS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_story_legacy_links ("
    "lore_story_id       INTEGER PRIMARY KEY, "
    "story_id            TEXT, "
    "mapping_status      TEXT NOT NULL DEFAULT 'unmapped', "
    "updated_at          INTEGER NOT NULL DEFAULT 0)"
)
# Индексы v21 — по фактическим запросам репозитория (ADR-1027-12 §5):
#   * chat-scope списки эпизодов/историй (фасад/канал mca-07, витрина mca-12);
#   * state-фильтр историй;
#   * реверс-lookup «эпизод → история» и «история → legacy-запись»;
#   * redirect — PK (old_kind, old_id) покрывает резолв.
_MCA_EPISODES_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_episodes_chat_updated "
    "ON mca_episodes (chat_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_mca_stories_chat_updated "
    "ON mca_stories (chat_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_mca_stories_chat_state "
    "ON mca_stories (chat_id, state)",
    "CREATE INDEX IF NOT EXISTS idx_mca_story_episode_links_episode "
    "ON mca_story_episode_links (episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_story_continuations_to "
    "ON mca_story_continuations (to_episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_story_legacy_links_story "
    "ON mca_story_legacy_links (story_id)",
)
# Override-колонки `mca_stories` — nullable ALTER под guard (A13: ручные
# правки переживают пересборку; NULL = override нет, автоматика не трогает).
_MCA_STORIES_OVERRIDE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("override_title", "TEXT"),
    ("override_summary", "TEXT"),
    ("override_outcome", "TEXT"),
    ("override_state", "TEXT"),
    ("override_open_questions", "TEXT"),
)
# Закрытые наборы mca-05 (ADR-1027-12 D3/D8).
EPISODE_STORY_STATES = frozenset({"open", "closed", "uncertain"})
EPISODE_MAPPING_STATUSES = frozenset({"mapped", "legacy", "unmapped"})
EPISODE_CONTINUATION_STATUSES = frozenset(
    {"candidate", "confirmed", "rejected"})
# «Исход неизвестен» — честный маркер (§9.1; финал не выдумывается).
# Значение — единый источник из канона промптов (re-export).
from services.mca_episode_prompts import (  # noqa: E402
    EPISODE_UNKNOWN_OUTCOME,
)

# ── Раунд 10.27 (MCA-22 FINAL INTEGRATION, spec §4.1 / ADR-1028-6 D2/D10) ──
# Durable Own Output Ledger — ЕДИНСТВЕННАЯ DDL-дельта фичи: v22 `mca_bot_outputs`
# (+3 индекса). Аддитивно/идемпотентно (self-guard `sqlite_master`), PG — no-op
# (memory-контур SQLite-only; `pg_db.py` вне diff). §31-обоснование: reuse
# `smart_messages` загрязнял бы human-only corpus (FTS/окно/L1/L2/persona/
# GraphRAG), reuse `bot_replies` ломал бы контракт TTL-кеша 63.1. Append-only:
# правка собственного сообщения → новая revision-строка (не UPDATE).
_SCHEMA_VERSION_BOT_OUTPUTS = 22

BOT_OUTPUT_KINDS = frozenset({
    "direct_reply", "autonomous_reply", "rich_message", "media_caption",
    "other",
})
BOT_OUTPUT_DELIVERY_STATUSES = frozenset({"delivered", "failed", "unknown"})

_MCA_BOT_OUTPUTS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_bot_outputs ("
    "output_id        INTEGER PRIMARY KEY AUTOINCREMENT, "
    "bot_user_id      INTEGER, "
    "chat_id          INTEGER NOT NULL, "
    "tg_message_id    INTEGER, "
    "revision_no      INTEGER NOT NULL DEFAULT 1, "
    "sent_at          INTEGER, "
    "parent_message_ref TEXT, "
    "output_kind      TEXT NOT NULL, "
    "content_text     TEXT, "
    "content_ref      TEXT, "
    "content_hash     TEXT, "
    "correlation_id   TEXT, "
    "source_feature   TEXT, "
    "delivery_status  TEXT NOT NULL DEFAULT 'delivered', "
    "created_at       INTEGER NOT NULL)"
)
_MCA_BOT_OUTPUTS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_bot_outputs_chat_tg "
    "ON mca_bot_outputs (chat_id, tg_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_bot_outputs_hash "
    "ON mca_bot_outputs (content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_mca_bot_outputs_corr "
    "ON mca_bot_outputs (correlation_id)",
)

# ── ASAP-4 волна A (spec §1/§7, ADR-1028-7 D1; 02.10.2026) ──────────────────
# v23 — Embedding Control Plane: runtime-состояние quota-групп (`embedding_
# quota_state`) + 3 аддитивные nullable-колонки реестра поколений v18
# (pause_reason / next_allowed_at / attempts_total — AM-1: 429 → paused_
# rate_limit, НЕ terminal failed; checkpoint/progress/attempt history).
# Аддитивно: CREATE TABLE IF NOT EXISTS + ALTER ADD COLUMN под guard
# `PRAGMA table_info`; НИ ОДНОГО UPDATE существующих строк; повторный
# прогон — no-op; PG — no-op (спека §7: credential-метаданные — конфиг).
# Обратимость: DROP embedding_quota_state безопасен; новые колонки
# NULL/default — старый код совместим.
_SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE = 23

# ── ASAP 4.1 волна 2 (эпик asap-4-1-durable-whole-window-summary, spec
# §10.1 + ADR-1028-8 D1): durable per-run snapshot полного окна Саммари.
# Аддитивно (CREATE TABLE IF NOT EXISTS); НИ ОДНОГО UPDATE/DELETE
# существующих строк при миграции; повторный прогон — no-op; PG — no-op
# (Summary живёт в SQLite; cover_style_* PG-таблицы не трогаются).
# Обратимость: DROP summary_source_windows безопасен (таблица не читается
# старым кодом). `user_version 23→24`.
_SCHEMA_VERSION_SUMMARY_SOURCE_WINDOW = 24

_SUMMARY_SOURCE_WINDOWS_DDL = (
    "CREATE TABLE IF NOT EXISTS summary_source_windows ("
    "run_id                TEXT PRIMARY KEY, "
    "chat_id               INTEGER NOT NULL, "
    "window_from           INTEGER, "
    "window_to             INTEGER, "
    "source_message_count  INTEGER NOT NULL, "
    "messages_json         TEXT NOT NULL, "
    "created_at            INTEGER NOT NULL)"
)

# ── ASAP 4.1 волна 5 (эпик asap-4-1-durable-whole-window-summary, spec
# §5 E.1/§10.2–§10.3 + ADR-1028-8 D6): durable SummaryRun — dedicated
# additive SQLite-таблицы `summary_runs` (стабильный run_id PK; state
# machine §20; publication_status/result_ref; pipeline_health) +
# `summary_run_stages` (append-only §50.54). Носитель — НЕ task_jobs
# payload (L-EXTRA-6 не наследуется) и НЕ перегрузка mca_pipeline_runs
# (тот остаётся root-lifecycle/heartbeat mca-17a). Аддитивно
# (CREATE TABLE IF NOT EXISTS); НИ ОДНОГО UPDATE/DELETE существующих
# строк ПРИ МИГРАЦИИ (checkpoint-UPDATE самих run-строк — runtime
# семантика store'а, не миграции); повторный прогон — no-op; PG — no-op.
# Обратимость: DROP обеих таблиц безопасен (не читаются старым кодом).
# `user_version` остаётся 24 (spec §10: v24 = 3 таблицы всего).

_SUMMARY_RUNS_DDL = (
    "CREATE TABLE IF NOT EXISTS summary_runs ("
    "run_id                    TEXT PRIMARY KEY, "
    "chat_id                   INTEGER NOT NULL, "
    "state                     TEXT NOT NULL DEFAULT 'CREATED', "
    "manual                    INTEGER NOT NULL DEFAULT 0, "
    "window_from               INTEGER, "
    "window_to                 INTEGER, "
    "source_ref                TEXT, "
    "publication_status        TEXT, "
    "publication_result_ref    TEXT, "
    "pipeline_health           TEXT, "
    "created_at                INTEGER NOT NULL, "
    "updated_at                INTEGER NOT NULL)"
)

_SUMMARY_RUNS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_summary_runs_state "
    "ON summary_runs (state)",
    "CREATE INDEX IF NOT EXISTS idx_summary_runs_chat "
    "ON summary_runs (chat_id, created_at)",
)

_SUMMARY_RUN_STAGES_DDL = (
    "CREATE TABLE IF NOT EXISTS summary_run_stages ("
    "id                 INTEGER PRIMARY KEY AUTOINCREMENT, "
    "run_id             TEXT NOT NULL, "
    "stage              TEXT NOT NULL, "
    "status             TEXT NOT NULL, "
    "started_at         INTEGER NOT NULL, "
    "last_activity_at   INTEGER, "
    "finished_at        INTEGER, "
    "attempt            INTEGER NOT NULL DEFAULT 0, "
    "provider           TEXT, "
    "model              TEXT, "
    "result_ref         TEXT, "
    "reason_code        TEXT)"
)

_SUMMARY_RUN_STAGES_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_summary_run_stages_run "
    "ON summary_run_stages (run_id, id)",
)

# ── mca-06 T-4727 (spec §7.2/§11.2, ADR-1028-9 D5): durable отчёт прогона
# сна. Δ DDL = v25 — ровно 2 nullable-колонки `mca_pipeline_runs`
# (`chat_id` — пер-чат прогоны сна, NULL = глобальный; `report_json` —
# bounded R17-safe отчёт §7.2) + 1 индекс под реальные запросы витрины.
# Аддитивно/идемпотентно через реестр `mca-14` (guard `PRAGMA table_info`),
# повторный прогон — no-op, PG — no-op (GEN-R4). Обратимость: колонки
# nullable, старый код их не читает; индекс DROP безопасен. НЕ
# `task_jobs.payload` (урок L-EXTRA-6); второй run-store не создаётся.
_SCHEMA_VERSION_DREAM_RUNS = 25

_MCA_PIPELINE_RUNS_DREAM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("chat_id", "INTEGER"),
    ("report_json", "TEXT"),
)
_MCA_PIPELINE_RUNS_CHAT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_chat "
    "ON mca_pipeline_runs (pipeline_type, chat_id, started_at)",
)


def _summary_window_unique_violation(exc: BaseException) -> bool:
    """IntegrityError «UNIQUE constraint» → write-once guard snapshot'а."""
    try:
        return type(exc).__name__ == "IntegrityError" \
            and "UNIQUE" in str(getattr(exc, "args", ())).upper()
    except Exception:      # pragma: no cover - защитная ветка
        return False

EMBEDDING_QUOTA_GROUP_STATES = frozenset(
    {"healthy", "cooling_down", "exhausted", "unknown"})

_EMBEDDING_QUOTA_STATE_DDL = (
    "CREATE TABLE IF NOT EXISTS embedding_quota_state ("
    "quota_group_id  TEXT PRIMARY KEY, "
    "state           TEXT NOT NULL DEFAULT 'healthy', "
    "next_allowed_at INTEGER, "
    "note            TEXT, "
    "updated_at      INTEGER NOT NULL DEFAULT 0)"
)

# Аддитивные колонки реестра поколений (v18) — порядок (имя, SQL-декларация).
_EMBEDDING_GENERATIONS_V23_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pause_reason", "TEXT"),
    ("next_allowed_at", "INTEGER"),
    ("attempts_total", "INTEGER NOT NULL DEFAULT 0"),
)

# Раунд 3 (3.6/B7, T-693): полный список origin для CHECK graph_facts — в ОДНОМ
# месте (CREATE TABLE + пересоздание в _migrate_direct_chat_v2 + миграции v4/v5).
# Включает ВНЕШНИЕ скобки списка IN (формат вставки в «CHECK (origin IN %s)»).
# user_memory (раунд 4, T-713/FR-D2): память-команды «запомни» — явные факты
# юзера/чата, без LLM-экстракции (graph_facts достаточно, nodes/edges НЕ
# создаются — см. spec 3.4.3 п.5).
# history_import (фаза 2, T-758): импортированные GraphRAG-факты истории —
# вес 0.3, expires_at NULL (вечно), message_timestamp = дата сообщения.
# derived_belief (раунд 9, T-822, spec §3.3.1): убеждения DreamWorker
# («сон») — единый CHECK; вступает в силу при rebuild graph_facts (v8).
# bot_self_reply (раунд 10.14, F1 anti-echo-self-reply, ADR-1014-2 D1):
# ЧЕСТНЫЙ 11-й origin для собственных сообщений бота (суть ответа, LLM-
# экстрактор); не переиспользует status='self_reply'. Вступает в силу при
# rebuild graph_facts (v9). Вес 0.2, важность 2, target_user NULL.
_GRAPH_FACT_ORIGINS_SQL = (
    "('chat_history', 'search_fact', 'youtube_content', 'web_content', "
    "'bot_direct_reply', 'voice_transcript', 'video_transcript', 'user_memory', "
    "'history_import', 'derived_belief', 'bot_self_reply')"
)

# Раунд 9 (AGI Memory, spec §3.3.2, T-823): importance-правило БЕЗ LLM на
# записи фактов (единая точка — insert_graph_fact при importance=None).
# База по origin (§3.3.2; derived_belief через правило НЕ ходит — DreamWorker
# передаёт явный importance) + бонусы: +1 текст содержит год/число ≥3 цифр,
# +1 длина ≥200 симв.; clamp 1..10 — записываемые факты никогда не 0 (Q8).
_IMPORTANCE_BASE = {
    "user_memory": 6,
    "chat_history": 4,
    "bot_direct_reply": 3,
    "history_import": 2,
    "voice_transcript": 2,
    "video_transcript": 2,
    "youtube_content": 3,
    "web_content": 3,
    "search_fact": 3,
    # Раунд 10.14 (F1 anti-echo-self-reply, ADR-1014-2 D3): собственные
    # высказывания бота — НИЖЕ пользовательских (bot_direct_reply=3).
    "bot_self_reply": 2,
}
_RE_YEAR_OR_NUM3 = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{3,}\b")


def rule_importance(origin: str, fact: str) -> int:
    """Правило важности §3.3.2: база по origin + бонусы (год/число ≥3 цифр,
    длина ≥200 симв.), clamp 1..10. Чистая функция (тесты границ/дефолтов)."""
    base = int(_IMPORTANCE_BASE.get(str(origin or ""), 0))
    text = str(fact or "")
    if _RE_YEAR_OR_NUM3.search(text):
        base += 1
    if len(text) >= 200:
        base += 1
    return max(1, min(10, base))

_EDGE_WEIGHT_CAP = 5             # Epic 60 (66.3/T-459 тема 5): подтверждение
                                 # связи +инкремент, cap 5 — вес не растёт вечно


def row_get(row, key, default=None):
    """Field accessor: if row has .get (dict) — row.get(key, default);
    otherwise row[key], falling back to default on KeyError/IndexError/TypeError."""
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def parse_belief_meta(raw) -> dict:
    """Единый парсер `belief_meta` (S10.13-13).

    Принимает dict / JSON-строку / None. Битое, не-JSON и не-dict значение →
    ``{}`` (fail-open, никогда не бросает). Три прежних дубля-парсера
    (`database._parse_belief_meta`, `dream_worker._belief_meta`,
    `summary_memory._belief_base_weight`) сведены сюда — рассинхрон форматов
    между воркером сна и read-path исключён."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parse_source_ids(raw) -> list[int]:
    """`source_ids` JSON → список целых id-источников (fail-open → []).

    MCA-04a (v17 backfill, T-3821): existing `source_ids` belief/paradigm
    типизируются в `derived_from`-SourceRef раннера; битое/не-список значение
    честно игнорируется (не выдумываем id)."""
    if raw is None:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[int] = []
    for item in data:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            out.append(int(item))
        elif isinstance(item, str) and item.strip().lstrip("-").isdigit():
            out.append(int(item.strip()))
    return out


# ── «Летописец» (раунд 10.20, БЛОК 1, ADR-1020-4): модульные хелперы ────────
# Токены топика для casefold-матча узлов графа и FTS.
_LORE_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
# Потолок скана узлов чата при поиске узла топика (детерминированно по id).
_LORE_NODE_SCAN_LIMIT = 2000


def _lore_fact_row(row: dict) -> dict:
    """Строка ``graph_facts`` → структурный факт «Летописца» (R16).

    ``rag_ts`` = message_timestamp (дата источника) или created_at — та же
    логика, что в RAG/скоринге; пустые поля не выдумываются."""
    rag_ts = row.get("message_timestamp") or row.get("created_at") or 0
    return {
        "id": int(row.get("id") or 0),
        "fact": str(row.get("fact") or ""),
        "target_user": row.get("target_user"),
        "rag_ts": int(rag_ts or 0),
        "kind": str(row.get("kind") or "fact"),
        "origin": str(row.get("origin") or ""),
        "status": str(row.get("status") or ""),
        "weight": float(row.get("weight") or 0.0),
    }


def _dossier_render_portrait(payload: dict) -> str:
    """mca-04b: рендер портрета из staged-payload (REUSE правила
    `dossier_prompts.render_generated_portrait`; fail-open → '')."""
    try:
        from services.dossier_prompts import render_generated_portrait
        return str(render_generated_portrait(
            payload.get("portrait"),
            [str(x).strip() for x in (payload.get("patterns") or [])
             if str(x).strip()],
            [str(x).strip() for x in (payload.get("themes") or [])
             if str(x).strip()],
        ) or "")
    except Exception:
        return ""


def _provenance_extractor_version() -> str:
    """Версия экстрактора контракта §8.3.2 (REUSE `provenance`)."""
    try:
        from services import provenance
        return str(provenance.EXTRACTOR_VERSION)
    except Exception:
        return "unknown"


@dataclasses.dataclass(frozen=True)
class MigrationStep:
    """Шаг реестра миграций (ADR-1027-1 D1).

    `version` — целое, строго +1 между шагами; `name` — стабильный
    человекочитаемый идентификатор (пишется в книгу); `apply` — async
    callable(DatabaseService) -> None, идемпотентный (self-guard по
    `sqlite_master`/`PRAGMA table_info`) и фиксирующий `PRAGMA user_version`.
    """

    version: int
    name: str
    apply: Callable[[object], Awaitable[None]]


def _serialized_write(method):
    """B-MCA01-1 (ADR-1027-3 D3): обернуть доменный write-метод
    `DatabaseService` в single-writer lock.

    Гарантирует, что прямые `self.db.execute(...)+commit()` внутри метода
    не интерливятся с чужой открытой транзакцией (`write_transaction`):
    метод и `write_transaction` используют один и тот же `self._lock`
    (через `_single_writer`, reentrancy по задаче). Пакетные (многошаговые)
    транзакции оформляются явно через `write_transaction`.

    Обёртка НЕ меняет сигнатуру/возврат метода; применяется точечно к
    write-методам (чтения не оборачиваются, чтобы не сериализовать чтения).
    """
    @functools.wraps(method)
    async def _wrapped(self, *args, **kwargs):
        async with self._single_writer():
            return await method(self, *args, **kwargs)
    return _wrapped


def _require_write_owner(service, op_name: str) -> None:
    """B-MCA01-1: `commit=False`-запись обязана идти внутри чужой транзакции.

    Иначе частичный write утёк бы на общую connection без владельца (ровно
    класс дефекта §5.1). Вызывающий обязан держать `serialized()`/
    `write_transaction()` в ТОЙ ЖЕ задаче (reentrancy тем же owner'ом)."""
    if service._write_owner is not asyncio.current_task():
        raise RuntimeError(
            f"{op_name}(commit=False) вызван вне serialized()/"
            "write_transaction() — открытая транзакция утекла бы на общую "
            "connection (ADR-1027-3 D3)")


class DatabaseService:
    """Async SQLite wrapper using aiosqlite. Manages schema, connections, and all queries."""
    
    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS user_presence (
            user_id    INTEGER NOT NULL,
            chat_id    INTEGER NOT NULL,
            is_present INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, chat_id)
        );
        
        CREATE TABLE IF NOT EXISTS message_counters (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );
        
        CREATE TABLE IF NOT EXISTS dead_page_posts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            slot      TEXT    NOT NULL,
            date      TEXT    NOT NULL,
            timestamp INTEGER
        );

        CREATE TABLE IF NOT EXISTS channel_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relay_album_map (
            message_id INTEGER PRIMARY KEY,
            media_group_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_relay_album_media_group ON relay_album_map(media_group_id);

        -- ── SmartModule: Summary (Epic 24) ─────────────────────────
        -- R1: сырьё всех сообщений чата (+author_name — резолв A8 на момент сохранения;
        -- Epic 28: is_forward/forward_source — forward-маркировка, R28-1;
        -- Epic 50 (58.7): tg_message_id — id TG-сообщения для цепочек <Conversation_Thread>)
        CREATE TABLE IF NOT EXISTS smart_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            chat_id         INTEGER NOT NULL,
            text            TEXT,
            reply_to_id     INTEGER,
            timestamp       INTEGER NOT NULL,
            media_type      TEXT NOT NULL DEFAULT 'text',
            author_name     TEXT NOT NULL DEFAULT '',
            is_forward      INTEGER NOT NULL DEFAULT 0,
            forward_source  TEXT NOT NULL DEFAULT '',
            tg_message_id   INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_ts ON smart_messages(chat_id, timestamp);
        -- idx_smart_messages_tg создаётся в _migrate_direct_chat_v2 (старые БД
        -- не имеют колонки tg_message_id до ALTER — индекс тут упал бы)

        -- FTS5 над сырьём L1/L2 (встроенный, без расширений) — L2-RAG + фоллбек
        CREATE VIRTUAL TABLE IF NOT EXISTS smart_messages_fts USING fts5(
            text, content='smart_messages', content_rowid='id', tokenize='unicode61'
        );

        -- L3: архивные факты — обычная таблица (пишется ВСЕГДА при сжатии)
        CREATE TABLE IF NOT EXISTS smart_archive_facts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            fact      TEXT NOT NULL,
            timestamp INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_archive_facts_chat_ts ON smart_archive_facts(chat_id, timestamp);
        CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive_facts_fts USING fts5(
            fact, content='smart_archive_facts', content_rowid='id', tokenize='unicode61'
        );

        -- L3: векторы создаются ЛЕНИВО из MemoryManager.initialize()
        -- (только если sqlite-vec загрузился; dim из конфига EMBEDDING_DIM)

        -- ── GraphRAG: граф знаний (Epic 26/46) ──────────────────
        CREATE TABLE IF NOT EXISTS nodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('user', 'topic', 'event', 'fact')),
            origin      TEXT NOT NULL DEFAULT 'chat_history',
            expires_at  INTEGER,
            UNIQUE (chat_id, entity_name)
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);

        CREATE TABLE IF NOT EXISTS edges (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            source_id     INTEGER NOT NULL REFERENCES nodes(id),
            target_id     INTEGER NOT NULL REFERENCES nodes(id),
            relation_type TEXT NOT NULL,
            weight        INTEGER NOT NULL DEFAULT 1,
            last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            origin        TEXT NOT NULL DEFAULT 'chat_history',
            expires_at    INTEGER,
            -- Раунд 10.18 (F3, ADR-1018-3 D1): provenance ребра → факт
            -- graph_facts.id для скоринга Σ importance. Nullable; legacy
            -- рёбра остаются NULL осознанно (ниже — COALESCE(importance, weight)).
            fact_id       INTEGER,
            UNIQUE (source_id, target_id, relation_type)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_chat_weight ON edges(chat_id, weight);
        -- idx_edges_fact_id создаётся в _migrate_edges_fact_id_v10 (legacy-БД
        -- до миграции не имеют колонки fact_id — CREATE INDEX здесь упал бы).

        -- GraphRAG v2 (Epic 46, Section 55.3): факты гибридного RAG
        -- (origin/expires_at — ТЗ R46-1; TTL-исключение — ленивое WHERE, D175;
        -- Epic 50 (58.7): CHECK + 'bot_direct_reply' и target_user — пересоздание
        -- в _migrate_direct_chat_v2 для старых БД;
        -- Раунд 3 (3.6/B7): + 'voice_transcript'/'video_transcript' (Epic 67
        -- кружочки и видео-инъекции молча скипались — CHECK их не пускал))
        CREATE TABLE IF NOT EXISTS graph_facts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER NOT NULL,
            fact       TEXT NOT NULL,
            origin     TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
                       ('chat_history', 'search_fact', 'youtube_content', 'web_content',
                        'bot_direct_reply', 'voice_transcript', 'video_transcript')),
            expires_at INTEGER,
            created_at INTEGER NOT NULL,
            target_user TEXT,
            -- Раунд 10.20 (БЛОК 7.3b, ADR-1020-1 ред. 3 / ADR-1020-7 §3,
            -- T-1924): provenance факта — id TG-сообщения-источника
            -- (ID-политика `tg:`) и источник пересылки (сегмент «Переслано:»).
            -- Схема-база; для legacy-БД колонки добавляет
            -- `_migrate_graph_facts_metadata_v12` (идемпотентно).
            tg_message_id INTEGER,
            forward_from  TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin ON graph_facts(chat_id, origin);
        -- idx_graph_facts_target_user создаётся в _migrate_direct_chat_v2
        -- (старые БД не имеют колонки target_user до пересоздания)
        CREATE VIRTUAL TABLE IF NOT EXISTS graph_facts_fts USING fts5(
            fact, content='graph_facts', content_rowid='id', tokenize='unicode61'
        );

        -- ── Smart Cache (Epic 51, Section 59.2, D209) ────────────
        -- Аддитивное хранилище Exact Match Cache; user_version НЕ поднимается
        -- (кэш — новое хранилище, не миграция, R51-5).
        CREATE TABLE IF NOT EXISTS smart_cache (
            key        TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        -- ── Dead page repost map (Epic 52, Section 61.6.2, T-417) ──
        -- Маппинг «репост Славика (в группе) → dead page бота (id в группе)»
        -- для детекта удаления репоста через InaccessibleMessage. Аддитивно,
        -- CREATE IF NOT EXISTS (миграций нет, R52-8).
        -- Индекс по (chat_id, repost_msg_id) НЕ создаём отдельно — UNIQUE
        -- авто-создаёт его (sqlite_autoindex, L4 review-fix).
        CREATE TABLE IF NOT EXISTS dead_page_repost_map (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            repost_msg_id INTEGER NOT NULL,          -- message_id репоста Славика в группе
            bot_msg_ids   TEXT    NOT NULL,          -- JSON-массив id dead page бота в группе
            created_at    REAL    NOT NULL,          -- time.time()
            UNIQUE (chat_id, repost_msg_id)
        );

        -- ── Раунд 8 (Context-Layer X-Features, spec §3.G1, T-800/T-804) ──
        -- Аддитивные структуры, user_version НЕ поднимается (RUNTIME WARNING,
        -- NFR-4). bot_reply_parents: parent-линк «бот-ответ → на какое сообщение
        -- отвечал» — Conversation_Thread ходит СКВОЗЬ бот-сообщения без
        -- миграции v8; TTL/LRU — тот же паттерн, что bot_replies (63.1).
        CREATE TABLE IF NOT EXISTS bot_reply_parents (
            chat_id INTEGER NOT NULL,
            tg_message_id INTEGER NOT NULL,
            parent_tg_message_id INTEGER,
            last_used_at REAL NOT NULL,
            PRIMARY KEY (chat_id, tg_message_id)
        );
        -- chat_summary_levels (E2/T-804): уровни конспекта — level 1 =
        -- chat_running_summary (широкий не строится из него), level 2 =
        -- «широкий фон» (сжатие ПРЕДЫДУЩЕГО L1 тем же COMPRESS_PROMPT).
        -- msg_count_highwater — raw_count prev-L1 на момент сборки; перезапись
        -- L2 меньшим окном запрещена (highwater-условие). TTL уровня не вводится.
        CREATE TABLE IF NOT EXISTS chat_summary_levels (
            chat_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            summary TEXT NOT NULL,
            updated_at REAL NOT NULL,
            msg_count_highwater INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, level)
        );

        -- ── Раунд 9 (AGI Memory, spec §3.1.1, T-816): users_meta ────────
        -- Карточка «отношений» участника чата. Аддитивно, CREATE IF NOT
        -- EXISTS, user_version НЕ поднимается (RUNTIME WARNING; образец
        -- bot_reply_parents/chat_summary_levels выше).
        -- first_seen/last_seen — по всей истории чата (агрегат refresh;
        -- first_seen импортированных «стариков» уходит в 2024 — цель
        -- фичи, Q5); msg_count — счётчик-касание (touch, +1 на сообщение),
        -- refresh перезаписывает авторитетным all-time COUNT(*);
        -- active_days/activity_score — 30д-окно с decay 0.5^((now-ts)/14д);
        -- relationship_stage — АВТО-стадия (manual живёт в PG relations);
        -- last_stage_change — маркер анти-отката (§3.1.2);
        -- last_recalc_at — TTL-метка ленивого пересчёта
        -- (limits.relations_recalc_ttl_minutes).
        CREATE TABLE IF NOT EXISTS users_meta (
            chat_id            INTEGER NOT NULL,
            user_id            INTEGER NOT NULL,
            first_seen         INTEGER,              -- unix ts первого сообщения
            last_seen          INTEGER,              -- unix ts последнего сообщения
            msg_count          INTEGER NOT NULL DEFAULT 0,   -- всего (touch/refresh)
            active_days        INTEGER NOT NULL DEFAULT 0,   -- уникальных дней в 30д-окне
            activity_score     REAL    NOT NULL DEFAULT 0,   -- Σ 0.5^((now-ts)/half-life) за 30д
            relationship_stage TEXT    NOT NULL DEFAULT 'stranger',  -- авто-стадия (manual в PG)
            last_stage_change  INTEGER,               -- unix ts последнего изменения стадии
            last_recalc_at     INTEGER NOT NULL DEFAULT 0,   -- unix ts пересчёта (TTL-метка)
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_users_meta_chat_last
            ON users_meta (chat_id, last_seen DESC);

        -- ── Раунд 10.20 (БЛОК 3.2/T-1896): ручные правки Досье участника ──
        -- Аддитивное хранилище, CREATE IF NOT EXISTS, user_version НЕ
        -- поднимается (прецедент smart_cache/bot_reply_parents/users_meta).
        -- Ключ — (chat_id, user_id) (R16: id — ключ, не имя). traits —
        -- свободный текст ручной правки, который UI показывает рядом с
        -- досье, собранным PersonalityExtractor'ом. Удаление строки = откат.
        CREATE TABLE IF NOT EXISTS persona_dossier_overrides (
            chat_id    INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            traits     TEXT    NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );

        -- ── Раунд 10.20 (БЛОК 1/О7, ADR-1020-4 п.4, T-1891): «Летописец» ──
        -- UPD-хранилище историй. Аддитивно, CREATE IF NOT EXISTS,
        -- user_version НЕ поднимается (прецеденты smart_cache/
        -- bot_reply_parents/persona_dossier_overrides; RUNTIME WARNING).
        -- topic_key = normalize_text(topic) (services/smart_cache.py);
        -- UNIQUE (chat_id, topic_key) — hit → is_update + previous_story_at;
        -- last_ts — last_seen на момент компиляции (дотягивание новых
        -- сообщений только с ts > last_ts). Удаление таблицы = откат.
        CREATE TABLE IF NOT EXISTS lore_stories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER NOT NULL,
            topic_key  TEXT    NOT NULL,
            topic      TEXT    NOT NULL,
            story      TEXT    NOT NULL,
            last_ts    INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE (chat_id, topic_key)
        );

        -- ── Раунд 9 (AGI Memory, spec §3.4.1, T-824): «сон» — DreamWorker ──
        -- Аддитивные структуры, user_version НЕ поднимается (RUNTIME WARNING;
        -- образец bot_reply_parents выше). dream_state — watermark «сна» per
        -- chat (PK chat_id; §3.4.2): last_run_at — unix ts последнего тика,
        -- last_processed_fact_id — max обработанный graph_facts.id чата
        -- (двигается только по успеху полного тик-батча чата).
        CREATE TABLE IF NOT EXISTS dream_state (
            chat_id INTEGER PRIMARY KEY,
            last_run_at INTEGER,
            last_processed_fact_id INTEGER NOT NULL DEFAULT 0
        );
        -- memory_dream_log — аудит «снов» (D-13): одна строка на тик-чат
        -- (kind='run', cluster_id NULL) + одна строка на попытку дистилляции
        -- (kind='distilled' | 'skipped' | 'error'); status:
        -- 'ok'/'unchanged'/'error'/'window_skip'. tokens — оценка
        -- max(1, len/4) промпта+ответа (денежный суточный бюджет §3.4.4
        -- считается суммой по этой колонке за local-сутки).
        CREATE TABLE IF NOT EXISTS memory_dream_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            run_at INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'run',
            cluster_id INTEGER,
            source_ids TEXT,
            belief_id INTEGER,
            tokens INTEGER NOT NULL DEFAULT 0,
            status TEXT
        );
        -- ── Раунд 9 (AGI Memory, spec §3.5.2, T-827): ностальгия ──────────
        -- Аудит срабатываний слоя B (NostalgiaWorker). Аддитивно, CREATE IF
        -- NOT EXISTS, user_version НЕ поднимается (образцы выше; RUNTIME
        -- WARNING). Одна строка на событие тика чата ПОСЛЕ «дорогих» шагов
        -- (candidate/threshold/llm/send — spec §3.5.3); дешёвые гейты
        -- (тишина/quiet hours/cooldown/лимиты) строк НЕ пишут.
        -- kind: 'year_back' | 'golden' | 'none'; fact_id — graph_facts.id
        -- для 'golden'; status: 'sent' | 'skipped' | 'error';
        -- meta — JSON {reason, candidate_text, ...}.
        CREATE TABLE IF NOT EXISTS nostalgia_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            ts INTEGER NOT NULL,                 -- unix ts события
            kind TEXT NOT NULL DEFAULT 'golden', -- 'year_back' | 'golden' | 'none'
            fact_id INTEGER,                     -- graph_facts.id (для 'golden')
            status TEXT NOT NULL,                -- 'sent' | 'skipped' | 'error'
            meta TEXT,                           -- JSON: reason, candidate_text, llm_skipped
            created_at INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_nostalgia_log_chat_ts
            ON nostalgia_log (chat_id, ts);
    """
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        # T-3735 (ADR-1027-3 D2): True после провала rollback/восстановления —
        # connection в неизвестном состоянии; следующий write_transaction
        # делает явную попытку восстановления и видимую ошибку в логе.
        self._connection_degraded = False
        # B-MCA01-1 (ADR-1027-3 D3): задача, владеющая single-writer lock в
        # данный момент. Нужна для reentrancy: `_serialized_write`-методы и
        # `write_transaction`, вызванные вложенно в одной задаче, не должны
        # повторно брать `self._lock` (дедлок).
        self._write_owner: asyncio.Task | None = None

    # ── B-MCA01-1 (ADR-1027-3 D3): единый single-writer для всех записей ────

    @contextlib.asynccontextmanager
    async def _single_writer(self):
        """Single-writer lock с reentrancy по задаче.

        Все доменные write-методы `DatabaseService` защищены этим же lock
        (`_serialized_write`), что и `write_transaction`. Пока lock удерживает
        задача, её вложенные записи не пере-захватывают lock (owner-проверка);
        чужие задачи ждут освобождения. Это закрывает класс дефекта §5.1
        (интерливинг прямых `execute+commit` с чужой открытой транзакцией).
        """
        if self._write_owner is asyncio.current_task():
            yield
            return
        await self._lock.acquire()
        self._write_owner = asyncio.current_task()
        try:
            yield
        finally:
            self._write_owner = None
            self._lock.release()

    def serialized(self):
        """Публичный single-writer контекст для доменных модулей (ADR-1027-3 D3).

        Внешние модули (`summary_memory`, `chat_lore`, `dossier_rebuild_jobs`,
        `memory_rebuild`, `persistent_throttling`, maintenance), которые по
        историческим причинам писали напрямую через `db.db.execute()+commit`,
        оборачивают write-блок в `async with db.serialized():`. Тем самым их
        записи сериализуются с `write_transaction` и декорированными
        методами (`_serialized_write`) на ОДНОМ lock — интерливинг чужой
        открытой транзакции (класс дефекта §5.1) невозможен.

        Reentrancy по задаче: вложенные декорированные вызовы внутри блока
        не пере-захватывают lock."""
        return self._single_writer()

    # ── F0.5 (раунд 10.25, ADR-1025-5): bounded retry + single-writer ──────

    @staticmethod
    def _is_locked(exc: BaseException) -> bool:
        """F0.5: True только для `OperationalError` с `locked` в тексте.

        Прочие исключения (в т.ч. OperationalError по другим причинам) не
        ретраятся — маскирование неретраибельных дефектов запрещено."""
        return (isinstance(exc, aiosqlite.OperationalError)
                and "locked" in str(exc).lower())

    def _note_lock_exhausted(self, op_name: str, attempts: int,
                             exc: BaseException, chat_id=None) -> None:
        """F0.5: явный структурный WARNING при исчерпании попыток + счётчик.

        R17: логируем op/attempts/chat_id и текст исключения — содержимое
        фактов/ответов в лог НЕ попадает. `exc_info=True` сохраняет причину."""
        global _lock_exhausted_total
        _lock_exhausted_total += 1
        logger.warning(
            "database: lock exhausted | event=database_lock_exhausted | "
            "op=%s | attempts=%d | chat_id=%s | error=%s",
            op_name, attempts, chat_id, exc, exc_info=True)

    async def write_transaction(self, op, *, op_name: str = "write",
                                chat_id=None, commit_if=None):
        """Single-writer обёртка логической транзакции (F0.5 + MCA-01 §5.1).

        `op(conn)` выполняет НЕСКОЛЬКО стейтментов и НЕ коммитит сам; коммит
        делает эта обёртка. `self._lock` держится на **всё время** транзакции —
        включая `COMMIT`/`ROLLBACK` и отменоустойчивую очистку (устраняет
        self-lock `database is locked`). При `locked` — bounded retry
        (`_LOCK_RETRIES`, backoff 0.1/0.2/0.4с), `rollback` перед повтором,
        повтор **всей** транзакции. Исчерпание → WARNING + счётчик + re-raise
        (fail-open остаётся за вызывающим хендлером — T-2450).

        **Владение транзакцией (§5.1, ADR-1027-3 D1; `MCA_TX_OWNERSHIP_ENABLED`
        default ON):** транзакцией владеет ТОЛЬКО задача, реально получившая
        lock. Провал acquisition (в т.ч. отмена ожидающего) не попадает в ветку
        rollback и не может откатить чужую/уже освобождённую транзакцию;
        `rollback` вызывается **внутри** `async with self._lock`. Отмена
        владельца выполняет очистку под lock (не оставляет открытую
        транзакцию следующему писателю).

        **Known-state (§5.1, ADR-1027-3 D2):** провал `COMMIT`/`ROLLBACK`
        переводит connection в известное состояние (новый `ROLLBACK` под
        lock) и делает ошибку видимой в логе; при неустранимости connection
        помечается degraded, следующий вызов пробует явное восстановление
        (`ROLLBACK`) и при провале — видимая ошибка (без тихого
        «неизвестного» состояния).

        `commit_if(result)` — необязательный предикат: `False` → commit НЕ
        делается (baseline-паритет для методов, коммитящих только при
        изменениях, напр. `touch_graph_facts`). `None` → коммит всегда.

        `MCA_TX_OWNERSHIP_ENABLED=false` → **точный паритет baseline**
        (7165ff7): одна попытка без сериализации/повторов, rollback вне lock,
        отмена ожидающего откатывает общую connection (дефект §5.1 сохраняется
        по дизайну OFF); путь `DB_LOCK_RESILIENCE_ENABLED=false` — как был."""
        if _tx_ownership_enabled() and _lock_resilience_enabled():
            return await self._write_transaction_owned(op, op_name,
                                                       chat_id, commit_if)
        return await self._write_transaction_baseline(op, op_name, commit_if,
                                                      chat_id)

    async def _write_transaction_baseline(self, op, op_name: str,
                                          commit_if=None, chat_id=None):
        """Паритет baseline 7165ff7 (`MCA_TX_OWNERSHIP_ENABLED=false` или
        `DB_LOCK_RESILIENCE_ENABLED=false`).

        Одна попытка; при `DB_LOCK_RESILIENCE_ENABLED=false` вообще без
        блокировки. Rollback — на ЛЮБОЕ исключение (включая
        `BaseException`/`CancelledError`, M-1), и, как в baseline, **вне
        lock** — отменённый ожидающий тоже откатывает общую connection."""
        global _lock_retry_total
        if not _lock_resilience_enabled():
            logger.debug(
                "database: write_transaction baseline (resilience OFF) | op=%s",
                op_name)
            try:
                result = await op(self.db)
                if commit_if is None or commit_if(result):
                    await self.db.commit()
                return result
            except BaseException:
                # M-1 (ревью): BaseException (в т.ч. CancelledError) — тоже
                # откатываем, чтобы огрызки не подхватил следующий писатель.
                await self._best_effort_rollback(op_name)
                raise
        attempt = 0
        while True:
            try:
                async with self._single_writer():
                    result = await op(self.db)
                    if commit_if is None or commit_if(result):
                        await self.db.commit()
                    return result
            except BaseException as exc:
                # F0.5 (ревью): rollback на ЛЮБОЕ исключение (в т.ч.
                # BaseException/CancelledError) — иначе частичная транзакция
                # остаётся на общем соединении и может быть закоммичена
                # следующей операцией. Retry — только для `locked`.
                await self._best_effort_rollback(op_name)
                if not self._is_locked(exc):
                    raise
                if attempt >= _LOCK_RETRIES:
                    self._note_lock_exhausted(op_name, attempt + 1, exc,
                                              chat_id=chat_id)
                    raise
                attempt += 1
                _lock_retry_total += 1
                await asyncio.sleep(_LOCK_BACKOFF * (2 ** (attempt - 1)))

    async def _write_transaction_owned(self, op, op_name: str, chat_id,
                                       commit_if=None):
        """MCA-01 §5.1: владение транзакцией под lock + known-state.

        `async with self._lock` стоит **вне** `try`: провал acquisition
        (включая отмену ожидающего `CancelledError` на входе в `with`) не
        попадает в ветку очистки и не трогает чужую транзакцию. Внутри lock —
        `BEGIN` (SQLite неявный `BEGIN` от первого DML, если транзакции нет),
        тело `op`, `COMMIT`; на исключение — очистка под тем же lock."""
        global _lock_retry_total
        if self.db is None:
            raise RuntimeError(
                "write_transaction: connection is not open (initialize() "
                "не вызван)")
        attempt = 0
        last_exc: BaseException | None = None
        while True:
            async with self._single_writer():
                if self._connection_degraded:
                    # B-MCA01-4 / D2: recovery-rollback выполняется СТРОГО под
                    # `self._lock` (иначе мог бы откатить чужую in-flight
                    # транзакцию). Провал → видимая ошибка (не тихое
                    # «неизвестное состояние»).
                    self._connection_degraded = not \
                        await self._safe_rollback_locked(
                            op_name, "recover-degraded")
                    if self._connection_degraded:
                        logger.error(
                            "database: connection unrecoverable | event="
                            "database_connection_unrecoverable | op=%s",
                            op_name)
                try:
                    result = await op(self.db)
                    if commit_if is None or commit_if(result):
                        await self._commit_locked(op_name)
                    return result
                except BaseException as exc:
                    last_exc = exc
                    # rollback ВНУТРИ lock — владелец очищает свою
                    # транзакцию; чужой/уже освобождённой не касается.
                    degraded = not await self._safe_rollback_locked(
                        op_name, "op-error")
                    if degraded:
                        self._connection_degraded = True
                        logger.error(
                            "database: rollback failed — connection marked "
                            "unrecoverable | event=database_connection_"
                            "unrecoverable | op=%s", op_name, exc_info=True)
                    if not self._is_locked(exc):
                        raise
                    # retry/backoff только после выхода из lock (п. §5.1:
                    # «Retry/backoff после освобождения lock»).
            if attempt >= _LOCK_RETRIES:
                self._note_lock_exhausted(op_name, attempt + 1,
                                          last_exc, chat_id)
                raise last_exc
            attempt += 1
            _lock_retry_total += 1
            await asyncio.sleep(_LOCK_BACKOFF * (2 ** (attempt - 1)))

    async def _commit_locked(self, op_name: str) -> None:
        """`COMMIT` под lock; провал → очистка rollback'ом (known-state).

        Ошибка коммита не глотается: поднимается наверх, но перед этим
        выполняется `ROLLBACK`, чтобы следующая операция не подхватила
        частичную транзакцию (D2)."""
        try:
            await self.db.commit()
        except BaseException:
            degraded = not await self._safe_rollback_locked(
                op_name, "commit-error")
            if degraded:
                self._connection_degraded = True
                logger.error(
                    "database: commit+rollback failed — connection marked "
                    "unrecoverable | event=database_connection_unrecoverable | "
                    "op=%s", op_name, exc_info=True)
            raise

    async def _safe_rollback_locked(self, op_name: str, phase: str) -> bool:
        """Rollback в известное состояние. `False` — rollback провалился
        (connection degraded); `True` — транзакция закрыта.

        Вызывается ТОЛЬКО под `self._lock` (phase: `op-error`,
        `commit-error`, `recover-degraded`). R17: имя op/фаза без контента."""
        try:
            await self.db.rollback()
            return True
        except BaseException:
            logger.warning(
                "database: rollback failed | event=database_rollback_failed | "
                "op=%s | phase=%s", op_name, phase)
            return False

    async def _best_effort_rollback(self, op_name: str = "write") -> None:
        """F0.5 baseline: best-effort rollback; провал — только debug.

        Сохранён для OFF-паритета (`MCA_TX_OWNERSHIP_ENABLED=false` /
        `DB_LOCK_RESILIENCE_ENABLED=false`)."""
        try:
            await self.db.rollback()
        except Exception:
            logger.debug("database: rollback failed (best-effort) | op=%s",
                         op_name, exc_info=True)

    # ── Раунд 10.27 (MCA Wave 0, `mca-14-schema-additive`, ADR-1027-1 D1) ──
    # Реестр шагов миграций. Каждая будущая DDL-фича добавляет СВОЮ строку
    # (не правит общую последовательность); шаги применяются по возрастанию
    # `version`; `PRAGMA user_version` сохраняется как маркер; книга
    # `schema_migrations` даёт аудит/дрейф-детект.
    #
    # Legacy-БД (v1…v12 без книги): шаги v1…v12 НЕ переисполняются — они уже
    # зафиксированы `user_version`, а раннер применяет только `version >
    # current`. Книга back-fill'ится одним baseline-рядом. Существующие
    # методы `_migrate_*` переиспользуются как тела шагов (REUSE).

    @staticmethod
    def migration_steps() -> list["MigrationStep"]:
        """Упорядоченный реестр шагов миграций (по возрастанию версии).

        REUSE (ADR-1027-1 D1): существующие методы `_migrate_*` переиспользуются
        как тела шагов без переписывания. v1…v12 — исторические ступени
        (fresh-БД проигрывает их с нуля; legacy-БД пропускает по
        `version > current`). v13 (`schema_migrations`) — волна 0 `mca-14`;
        v14 (`task_jobs`, `mca-01`) и v15 (`mca_events`, `mca-13`)
        добавляются своими фичами отдельными строками."""
        return [
            MigrationStep(1, "graphrag_v2",
                          lambda svc: svc._migrate_graphrag_v2()),
            MigrationStep(2, "direct_chat_v2",
                          lambda svc: svc._migrate_direct_chat_v2()),
            MigrationStep(3, "epic60_v3",
                          lambda svc: svc._migrate_epic60_v3()),
            MigrationStep(4, "video_origins_v4",
                          lambda svc: svc._migrate_video_origins_v4()),
            MigrationStep(5, "user_memory_v5",
                          lambda svc: svc._migrate_user_memory_v5()),
            MigrationStep(6, "chat_protected_facts_v6",
                          lambda svc: svc._migrate_chat_protected_facts_v6()),
            MigrationStep(7, "history_import_v7",
                          lambda svc: svc._migrate_history_import_v7()),
            MigrationStep(8, "agi_memory_v8",
                          lambda svc: svc._migrate_agi_memory_v8()),
            MigrationStep(9, "self_origin_v9",
                          lambda svc: svc._migrate_self_origin_v9()),
            MigrationStep(10, "edges_fact_id_v10",
                          lambda svc: svc._migrate_edges_fact_id_v10()),
            MigrationStep(11, "import_key_chat_scope_v11",
                          lambda svc: svc._migrate_import_key_chat_scope_v11()),
            MigrationStep(12, "graph_facts_metadata_v12",
                          lambda svc: svc._migrate_graph_facts_metadata_v12()),
            MigrationStep(_SCHEMA_VERSION_SCHEMA_MIGRATIONS,
                          "schema_migrations_book",
                          lambda svc: svc._migrate_schema_migrations_v13()),
            MigrationStep(_SCHEMA_VERSION_TASK_JOBS,
                          "task_jobs",
                          lambda svc: svc._migrate_task_jobs_v14()),
            MigrationStep(_SCHEMA_VERSION_MCA_EVENTS,
                          "mca_events",
                          lambda svc: svc._migrate_mca_events_v15()),
            MigrationStep(_SCHEMA_VERSION_MESSAGE_IDENTITY,
                          "message_identity",
                          lambda svc: svc._migrate_message_identity_v16()),
            MigrationStep(_SCHEMA_VERSION_PROVENANCE,
                          "provenance_contract",
                          lambda svc: svc._migrate_provenance_v17()),
            MigrationStep(_SCHEMA_VERSION_EMBEDDING_IDENTITY,
                          "embedding_identity",
                          lambda svc: svc._migrate_embedding_identity_v18()),
            MigrationStep(_SCHEMA_VERSION_OBSERVABILITY,
                          "observability_core",
                          lambda svc: svc._migrate_observability_v19()),
            MigrationStep(_SCHEMA_VERSION_DOSSIER_STAGING,
                          "dossier_staging",
                          lambda svc: svc._migrate_dossier_staging_v20()),
            MigrationStep(_SCHEMA_VERSION_EPISODES_STORIES,
                          "episodes_stories",
                          lambda svc: svc._migrate_episodes_stories_v21()),
            MigrationStep(_SCHEMA_VERSION_BOT_OUTPUTS,
                          "bot_outputs_ledger",
                          lambda svc: svc._migrate_bot_outputs_v22()),
            MigrationStep(_SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE,
                          "embedding_control_plane",
                          lambda svc: svc._migrate_embedding_control_plane_v23()),
            MigrationStep(_SCHEMA_VERSION_SUMMARY_SOURCE_WINDOW,
                          "summary_source_windows",
                          lambda svc: svc._migrate_summary_source_window_v24()),
            # mca-06 (ADR-1028-9 D5): v25 — 2 nullable-колонки
            # `mca_pipeline_runs` (chat_id/report_json) + индекс; аддитивно,
            # повтор — no-op, PG — no-op.
            MigrationStep(_SCHEMA_VERSION_DREAM_RUNS,
                          "dream_run_reports",
                          lambda svc: svc._migrate_dream_runs_v25()),
            # ASAP 4.1 волна 5 (T-4616, spec §10.2–§10.3): v24 = 3 таблицы
            # (summary_source_windows + summary_runs + summary_run_stages).
            # Один MigrationStep на версию — книга `schema_migrations` имеет
            # PK=version (одна строка на версию; три шага затирали бы друг
            # друга INSERT OR REPLACE). Полный DDL-набор v24 применяется
            # внутри `_migrate_summary_source_window_v24` (шаги 2/3 —
            # self-guarded хелперы того же шага); шаги аддитивные,
            # повтор — no-op.
        ]

    @staticmethod
    def _step_checksum(step: "MigrationStep") -> str:
        """Стабильный checksum шага (аудит/дрейф-детект).

        R17: хэшируется только версия/имя шага — не содержимое БД, не пути."""
        return hashlib.sha256(
            f"{step.version}:{step.name}".encode("utf-8")).hexdigest()

    async def _run_migrations(self) -> None:
        """Идемпотентный версионируемый runner (ADR-1027-1 D1).

        `current = PRAGMA user_version`; применяются шаги со `version >
        current` по возрастанию; книга `schema_migrations` дописывается
        идемпотентно (`INSERT OR REPLACE`); `user_version` фиксирует сам шаг.

        Legacy-БД (v1…v12 без книги): baseline-ряд `version=current, name=
        'legacy_baseline'` → шаги v1…v12 не исполняются повторно. Повторный
        запуск на актуальной БД — no-op (0 изменений, 0 дублей).
        """
        cursor = await self.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        current = int(row[0]) if row is not None else 0
        steps = sorted(self.migration_steps(), key=lambda s: s.version)
        # MCA-14 (ADR-1027-1 D2): backup ПЕРЕД применением ЛЮБЫХ новых шагов
        # (включая книгу v13) — `VACUUM INTO` + free-space + read-back.
        # Провал → явный отказ применять (никакого частичного применения).
        # Свежая БД (current == 0) не содержит данных — бэкапить нечего.
        if current > 0 and any(s.version > current for s in steps):
            from services.memory_backup import migration_backup
            await migration_backup(self, target_version=current)
        # B-MCA14-1: книга создаётся БЕЗ выставления `user_version` (иначе
        # pre-call поднял бы маркер до 13 → на свежей БД при сбое раннего шага
        # повторный `initialize()` пропустил бы v1…v12). Версию v13 фиксирует
        # сам шаг v13 в общем цикле (по возрастанию, после v12).
        await self._ensure_migration_book()
        applied_versions: set[int] = set()
        try:
            cursor = await self.db.execute(
                "SELECT version FROM schema_migrations")
            applied_versions = {int(r[0]) for r in await cursor.fetchall()}
        except Exception:
            logger.warning("[database] migration book read failed", exc_info=True)
        if current > 0 and current not in applied_versions:
            # legacy v1…v12 без книги → один baseline-ряд (аудит/дрейф).
            await self.db.execute(
                "INSERT OR REPLACE INTO schema_migrations "
                "(version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (current, "legacy_baseline", int(time.time()),
                 hashlib.sha256(b"legacy_baseline").hexdigest()))
            await self.db.commit()
        for step in steps:
            if step.version <= current:
                continue
            # L-MCA14-3 (санкционированное исключение): runner работает на этапе
            # `initialize()` ДО старта сервинга/конкурентных писателей, поэтому
            # прямые `execute+commit` здесь безопасны и не интерливятся с чужой
            # транзакцией (нет второго писателя). Доменные записи после старта
            # идут только через single-writer (см. `_serialized_write`).
            await step.apply(self)
            await self.db.execute(
                "INSERT OR REPLACE INTO schema_migrations "
                "(version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (step.version, step.name, int(time.time()),
                 self._step_checksum(step)))
            await self.db.commit()
            logger.info("[database] migration v%d applied | %s",
                        step.version, step.name)

    async def _ensure_migration_book(self) -> None:
        """B-MCA14-1: создать книгу `schema_migrations`, НЕ трогая
        `user_version` (книга нужна раннеру для аудита/дрейф-детекта до
        применения шагов; версия фиксируется шагом v13 в общем цикле)."""
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("schema_migrations",))
        if await cursor.fetchone() is None:
            await self.db.execute(_SCHEMA_MIGRATIONS_DDL)
            await self.db.commit()

    async def _migrate_schema_migrations_v13(self) -> None:
        """v13 (`mca-14-schema-additive`, ADR-1027-1 D1/D8): книга реестра.

        Аддитивно (`CREATE TABLE IF NOT EXISTS`), self-guard по
        `sqlite_master`; повторный запуск — no-op. Старые таблицы/ID НЕ
        трогаются (D3). PG — no-op (SQLite-механизм). `user_version = 13`
        ставится ТОЛЬКО если текущая версия меньше 13 — шаг не понижает
        маркер уже применённых v14/v15 (монотонность)."""
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("schema_migrations",))
        if await cursor.fetchone() is None:
            await self.db.execute(_SCHEMA_MIGRATIONS_DDL)
            await self.db.commit()
            logger.info("[database] migration v13: schema_migrations book")
        cursor = await self.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        current = int(row[0]) if row is not None else 0
        if current < _SCHEMA_VERSION_SCHEMA_MIGRATIONS:
            await self.db.execute(
                f"PRAGMA user_version = {_SCHEMA_VERSION_SCHEMA_MIGRATIONS}")
            await self.db.commit()

    async def _migrate_task_jobs_v14(self) -> None:
        """v14 (`mca-01-tx-task-supervisor`, ADR-1027-3 D5/D10): durable-очередь
        фоновых задач `task_jobs` + 2 индекса (рамка §1.1.1).

        Аддитивно (`CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT
        EXISTS`); self-guard по `sqlite_master`; повторный запуск — no-op.
        Старые таблицы/ID НЕ трогаются (mca-14 D3). PG — no-op. Фиксирует
        `PRAGMA user_version = 14` безусловно (прецедент v9…v13)."""
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("task_jobs",))
        if await cursor.fetchone() is None:
            await self.db.execute(_TASK_JOBS_DDL)
            await self.db.commit()
            logger.info("[database] migration v14: task_jobs durable queue")
        for ddl in _TASK_JOBS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_TASK_JOBS}")
        await self.db.commit()

    async def _migrate_mca_events_v15(self) -> None:
        """v15 (`mca-13-event-contract`, ADR-1027-2 D4/D11): durable-стор
        терминальных событий `mca_events` + `mca_event_aggregates` + 4 индекса
        (рамка §1.1.2). Единственный store телеметрии (второй запрещён).

        Аддитивно (`CREATE TABLE IF NOT EXISTS`); self-guard по
        `sqlite_master`; повторный запуск — no-op. Старые таблицы/ID НЕ
        трогаются. PG — no-op. Фиксирует `PRAGMA user_version = 15`."""
        for table, ddl in (("mca_events", _MCA_EVENTS_DDL),
                           ("mca_event_aggregates",
                            _MCA_EVENT_AGGREGATES_DDL)):
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,))
            if await cursor.fetchone() is None:
                await self.db.execute(ddl)
                await self.db.commit()
                logger.info("[database] migration v15: %s", table)
        for ddl in _MCA_EVENTS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_MCA_EVENTS}")
        await self.db.commit()

    async def _smart_messages_columns(self) -> set:
        """Имена колонок `smart_messages` (guard для ALTER ADD COLUMN)."""
        cursor = await self.db.execute("PRAGMA table_info(smart_messages)")
        return {r["name"] for r in await cursor.fetchall()}

    async def count_duplicate_identity_rows(self) -> int:
        """Число legacy live-групп с дублем `(chat_id, tg_message_id)`.

        Нужен для duplicate pre-check v16 (ADR-1027-4 D7): при наличии дублей
        partial UNIQUE НЕ создаётся (иначе миграция упала бы), эмитится WARN
        `duplicate_identity_rows`; старые записи сохраняются. Устойчиво к
        усечённой synthetic-legacy без `import_key` (тогда живых/импортных
        различий нет — считаем по всем строкам с tg_message_id)."""
        cols = await self._smart_messages_columns()
        where = ("WHERE tg_message_id IS NOT NULL AND import_key IS NULL"
                 if "import_key" in cols
                 else "WHERE tg_message_id IS NOT NULL")
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS c FROM ("
            f"SELECT chat_id, tg_message_id FROM smart_messages {where} "
            "GROUP BY chat_id, tg_message_id HAVING COUNT(*) > 1)")
        row = await cursor.fetchone()
        return int(row["c"]) if row is not None else 0

    async def _migrate_message_identity_v16_backfill(self,
                                                     has_import_key: bool) -> None:
        """Bounded/resumable backfill (ADR-1027-4 D3/D7).

        Guard `sent_at_source IS NULL` → повторный прогон no-op; обрабатывается
        пачками. Импорт: `sent_at=timestamp` (`import_date`), namespace/record
        id. Live-legacy: `sent_at=NULL` (`legacy_unverified`) — `timestamp`
        НЕ переносится (это время записи, не события). Для усечённой
        synthetic-legacy без `import_key` все строки трактуются как live."""
        if has_import_key:
            while True:
                cursor = await self.db.execute(
                    "UPDATE smart_messages SET "
                    "source_kind='import', namespace=?, "
                    "source_record_id='k:'||import_key, "
                    "sent_at=timestamp, sent_at_source='import_date', "
                    "reply_to_kind='export' "
                    "WHERE import_key IS NOT NULL AND sent_at_source IS NULL "
                    "AND id IN (SELECT id FROM smart_messages "
                    "WHERE import_key IS NOT NULL AND sent_at_source IS NULL "
                    "LIMIT ?)",
                    (_LEGACY_IMPORT_NAMESPACE,
                     _MESSAGE_IDENTITY_BACKFILL_BATCH))
                await self.db.commit()
                if cursor.rowcount <= 0:
                    break
        live_where = "import_key IS NULL" if has_import_key else "1 = 1"
        while True:
            cursor = await self.db.execute(
                "UPDATE smart_messages SET "
                "source_kind='live', sent_at=NULL, ingested_at=NULL, "
                f"sent_at_source='legacy_unverified' WHERE {live_where} "
                "AND sent_at_source IS NULL "
                "AND id IN (SELECT id FROM smart_messages "
                f"WHERE {live_where} AND sent_at_source IS NULL LIMIT ?)",
                (_MESSAGE_IDENTITY_BACKFILL_BATCH,))
            await self.db.commit()
            if cursor.rowcount <= 0:
                break

    async def _migrate_message_identity_v16(self) -> None:
        """v16 (`mca-03-message-identity`, ADR-1027-4 D3/D7/D11): логическая
        идентичность `(chat_id, tg_message_id)`, поля времени/ролей, версии,
        mapping `chat_id`.

        Аддитивно (`ALTER ADD COLUMN` под guard `PRAGMA table_info` +
        `CREATE ... IF NOT EXISTS`); self-guard; повторный прогон — no-op.
        Старые `id`/`timestamp`/FTS сохраняются. PG — no-op. Duplicate
        pre-check перед partial UNIQUE; backfill bounded/resumable."""
        cols = await self._smart_messages_columns()
        for name, decl in _MESSAGE_IDENTITY_COLUMNS:
            if name not in cols:
                await self.db.execute(
                    f"ALTER TABLE smart_messages ADD COLUMN {name} {decl}")
        await self.db.commit()
        for table, ddl in (("message_source_records",
                            _MESSAGE_SOURCE_RECORDS_DDL),
                           ("message_revisions", _MESSAGE_REVISIONS_DDL),
                           ("chat_id_migrations", _CHAT_ID_MIGRATIONS_DDL)):
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,))
            if await cursor.fetchone() is None:
                await self.db.execute(ddl)
                await self.db.commit()
                logger.info("[database] migration v16: %s", table)
        for ddl in (_MESSAGE_IDENTITY_INDEX_DDL
                    + _SMART_MESSAGES_IDENTITY_INDEX_DDL):
            await self.db.execute(ddl)
        await self.db.commit()
        duplicates = await self.count_duplicate_identity_rows()
        has_import_key = "import_key" in cols
        if duplicates:
            # WARN через контракт MCA-13 + структурный лог; UNIQUE не создаётся.
            from services import message_identity as _mi
            _mi.emit_duplicate_identity_warning(duplicates)
        if not duplicates and has_import_key:
            await self.db.execute(_SMART_MESSAGES_LIVE_UNIQUE_DDL)
            await self.db.commit()
        await self._migrate_message_identity_v16_backfill(has_import_key)
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_MESSAGE_IDENTITY}")
        await self.db.commit()

    async def _graph_facts_columns(self) -> set:
        """Имена колонок `graph_facts` (guard для ALTER ADD COLUMN v17)."""
        cursor = await self.db.execute("PRAGMA table_info(graph_facts)")
        return {r["name"] for r in await cursor.fetchall()}

    # ── Раунд 10.27 (MCA Wave 1, `mca-04a-provenance-contract`, ADR-1027-6) ─
    # v17-хелперы записи. Во время миграции (initialize) прямые execute+commit
    # санкционированы (L-MCA14-3: раннер работает до старта писателей); в
    # рантайме доменные записи идут через `write_transaction` (`provenance.py`).

    async def _provenance_resolve_ref(self, *, store: str, entity_type: str,
                                      entity_id: str, chat_id=None,
                                      revision=None, tg_message_id=None,
                                      dataset_id=None, source_record_id=None,
                                      resolution=None, now: int) -> int | None:
        """Get-or-create SourceRef с дедупом по (store,type,id,chat,revision)."""
        await self.db.execute(
            "INSERT OR IGNORE INTO mca_source_refs (store, entity_type, "
            "entity_id, chat_id, revision, tg_message_id, dataset_id, "
            "source_record_id, resolution, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(store), str(entity_type), str(entity_id), chat_id, revision,
             tg_message_id, dataset_id, source_record_id, resolution, int(now)))
        cursor = await self.db.execute(
            "SELECT source_ref_id FROM mca_source_refs WHERE store = ? AND "
            "entity_type = ? AND entity_id = ? AND COALESCE(chat_id, -1) = "
            "COALESCE(?, -1) AND COALESCE(revision, '') = COALESCE(?, '')",
            (str(store), str(entity_type), str(entity_id), chat_id, revision))
        row = await cursor.fetchone()
        return int(row["source_ref_id"]) if row is not None else None

    async def _provenance_link(self, subject_ref_id: int, source_ref_id: int,
                               link_type: str, method: str, verification: str,
                               independence: str, now: int, *,
                               claim_key=None, basis=None, checks_json=None,
                               extractor_version=None) -> None:
        """Идемпотентная EvidenceLink (дедуп по объект+источник+тип+claim)."""
        await self.db.execute(
            "INSERT OR IGNORE INTO mca_evidence_links (subject_ref_id, "
            "source_ref_id, link_type, method, verification, independence, "
            "claim_key, extractor_version, basis, checks_json, established_at, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (int(subject_ref_id), int(source_ref_id), str(link_type),
             str(method), str(verification), str(independence), claim_key,
             extractor_version, basis, checks_json, int(now), int(now)))

    async def _provenance_set_status(self, object_ref_id: int,
                                     origin_status: str, now: int) -> None:
        """Origin/конфликт/актуальность/покрытие объекта (1:1 с SourceRef)."""
        await self.db.execute(
            "INSERT OR REPLACE INTO mca_provenance_status (object_ref_id, "
            "origin_status, conflict_status, freshness_status, "
            "coverage_status, coverage_covered, coverage_total, "
            "extractor_version, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (int(object_ref_id), str(origin_status), "unknown", "unknown",
             "unknown", None, None, None, int(now)))

    async def _migrate_provenance_v17_backfill(self) -> None:
        """Bounded/resumable backfill v17 — **только прямые ссылки** (D6/A09).

        (1) объектный SourceRef + `mca_provenance_status` на каждый
        `graph_facts` (guard — отсутствие объектного SourceRef); `origin_status`
        = `original` **только** при сохранённом прямом источнике
        (`tg_message_id IS NOT NULL` → message SourceRef + `derived_from` +
        `verified`), иначе честный `unknown`. (2) существующие `source_ids`
        belief/paradigm → `derived_from` SourceRefs (dedup идемпотентен).
        Семантический поиск НЕ выполняется (ложный `original` запрещён)."""
        now = int(time.time())
        while True:
            cursor = await self.db.execute(
                "SELECT f.id AS id, f.chat_id AS chat_id, "
                "f.tg_message_id AS tg_message_id FROM graph_facts f "
                "WHERE NOT EXISTS (SELECT 1 FROM mca_source_refs r "
                "WHERE r.store = 'sqlite' AND r.entity_type = 'graph_fact' "
                "AND r.entity_id = CAST(f.id AS TEXT)) "
                "ORDER BY f.id LIMIT ?", (_PROVENANCE_BACKFILL_BATCH,))
            rows = await cursor.fetchall()
            if not rows:
                break
            for row in rows:
                fid = int(row["id"])
                chat_id = row["chat_id"]
                tg = row["tg_message_id"]
                obj_ref = await self._provenance_resolve_ref(
                    store="sqlite", entity_type="graph_fact",
                    entity_id=str(fid), chat_id=chat_id,
                    resolution="resolved", now=now)
                origin_status = "unknown"
                if tg is not None and obj_ref is not None:
                    msg_key = await self._smart_message_entity_id(
                        int(chat_id) if chat_id is not None else None, int(tg))
                    src_ref = await self._provenance_resolve_ref(
                        store="sqlite", entity_type="message",
                        entity_id=msg_key, chat_id=chat_id,
                        tg_message_id=int(tg), resolution="resolved", now=now)
                    if src_ref is not None:
                        await self._provenance_link(
                            obj_ref, src_ref, "derived_from",
                            "migration_backfill", "verified", "unknown", now,
                            basis="backfill: direct tg_message_id")
                        origin_status = "original"
                if obj_ref is not None:
                    await self._provenance_set_status(obj_ref, origin_status,
                                                      now)
            await self.db.commit()
        # (2) source_ids (belief/paradigm) → derived_from (идемпотентный dedup).
        # Guard: колонка `source_ids` (v8) может отсутствовать на усечённой
        # legacy-БД — тогда прямых id-источников нет, шаг честно no-op.
        cols = await self._graph_facts_columns()
        if "source_ids" not in cols:
            return
        cursor_id = 0
        while True:
            cursor = await self.db.execute(
                "SELECT id, chat_id, source_ids FROM graph_facts "
                "WHERE source_ids IS NOT NULL AND source_ids != '' AND id > ? "
                "ORDER BY id LIMIT ?",
                (cursor_id, _PROVENANCE_BACKFILL_BATCH))
            rows = await cursor.fetchall()
            if not rows:
                break
            for row in rows:
                cursor_id = int(row["id"])
                src_ids = _parse_source_ids(row["source_ids"])
                if not src_ids:
                    continue
                chat_id = row["chat_id"]
                obj_ref = await self._provenance_resolve_ref(
                    store="sqlite", entity_type="graph_fact",
                    entity_id=str(cursor_id), chat_id=chat_id,
                    resolution="resolved", now=now)
                if obj_ref is None:
                    continue
                for sid in src_ids:
                    if sid == cursor_id:
                        continue
                    ref = await self._provenance_resolve_ref(
                        store="sqlite", entity_type="graph_fact",
                        entity_id=str(sid), chat_id=chat_id,
                        resolution="resolved", now=now)
                    if ref is not None:
                        await self._provenance_link(
                            obj_ref, ref, "derived_from", "migration_backfill",
                            "verified", "unknown", now,
                            basis="backfill: source_ids")
            await self.db.commit()

    async def _smart_message_entity_id(self, chat_id, tg_message_id) -> str:
        """`entity_id` message-SourceRef: канонический `smart_messages.id`
        при наличии строки, иначе `tg:<tg_message_id>` (opaque, не смешивается
        с внутренним ID; TG-ID остаётся отдельным полем)."""
        if chat_id is not None and tg_message_id is not None:
            try:
                cursor = await self.db.execute(
                    "SELECT id FROM smart_messages WHERE chat_id = ? AND "
                    "tg_message_id = ? LIMIT 1", (int(chat_id),
                                                  int(tg_message_id)))
                row = await cursor.fetchone()
                if row is not None:
                    return str(int(row["id"]))
            except Exception:
                logger.debug("[database] smart_messages id lookup failed",
                             exc_info=True)
        return f"tg:{int(tg_message_id)}" if tg_message_id is not None else ""

    async def _migrate_provenance_v17(self) -> None:
        """v17 (`mca-04a-provenance-contract`, ADR-1027-6 D1/D10): SourceRef/
        EvidenceLink/статусы происхождения + 6 nullable-колонок `graph_facts`.

        Аддитивно (`CREATE TABLE/INDEX IF NOT EXISTS` + `ALTER ADD COLUMN` под
        guard `PRAGMA table_info`); self-guard по `sqlite_master`; повторный
        прогон — no-op. Старые таблицы/ID/FTS/`origin` CHECK НЕ трогаются.
        Backfill — только прямые ссылки (bounded/resumable). Фиксирует
        `PRAGMA user_version = 17`."""
        for table, ddl in (
                ("mca_source_refs", _PROVENANCE_SOURCE_REFS_DDL),
                ("mca_evidence_links", _PROVENANCE_EVIDENCE_LINKS_DDL),
                ("mca_provenance_status", _PROVENANCE_STATUS_DDL)):
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,))
            if await cursor.fetchone() is None:
                await self.db.execute(ddl)
                await self.db.commit()
                logger.info("[database] migration v17: %s", table)
        for ddl in (_PROVENANCE_SOURCE_REFS_INDEX_DDL
                    + _PROVENANCE_EVIDENCE_LINKS_INDEX_DDL):
            await self.db.execute(ddl)
        await self.db.commit()
        cols = await self._graph_facts_columns()
        for name, decl in _PROVENANCE_FACT_COLUMNS:
            if name not in cols:
                await self.db.execute(
                    f"ALTER TABLE graph_facts ADD COLUMN {name} {decl}")
        await self.db.commit()
        for ddl in _PROVENANCE_FACT_INDEX_DDL:
            # Self-guard (spec §5): индекс `(subject_ref_id, status)` требует
            # колонку `status` (v8). На реальной legacy-БД она есть; на
            # синтетической/усечённой — деградируем до индекса по субъекту,
            # чтобы аддитивный шаг не падал (старые данные не читаются иначе).
            if "status" not in cols and "status" in ddl:
                ddl = ("CREATE INDEX IF NOT EXISTS idx_graph_facts_subject_ref "
                       "ON graph_facts(subject_ref_id)")
            await self.db.execute(ddl)
        await self.db.commit()
        await self._migrate_provenance_v17_backfill()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_PROVENANCE}")
        await self.db.commit()

    async def _embedding_cache_columns(self) -> set:
        """Имена колонок `embedding_cache` (guard для ALTER ADD COLUMN v18)."""
        cursor = await self.db.execute("PRAGMA table_info(embedding_cache)")
        return {r["name"] for r in await cursor.fetchall()}

    async def _migrate_embedding_identity_v18(self) -> None:
        """v18 (`mca-07-retrieval-context`, ADR-1027-7 D4/D12): durable-реестр
        поколений/fingerprint векторных индексов
        (`mca_embedding_index_generations` + 3 индекса) и 5 nullable identity-
        колонок `embedding_cache`.

        Аддитивно (`CREATE ... IF NOT EXISTS` + `ALTER ADD COLUMN` под guard
        `PRAGMA table_info`); self-guard; повторный прогон — no-op. Vec-таблицы
        (`smart_archive`/`graph_facts_vec`) НЕ модифицируются; старые
        таблицы/ID/FTS/vec-данные не трогаются. `nullable` = честный unknown;
        backfill не требуется. Фиксирует `PRAGMA user_version = 18`."""
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("mca_embedding_index_generations",))
        if await cursor.fetchone() is None:
            await self.db.execute(_MCA_EMBEDDING_INDEX_GENERATIONS_DDL)
            await self.db.commit()
            logger.info("[database] migration v18: mca_embedding_index_"
                        "generations")
        for ddl in _MCA_EMBEDDING_INDEX_GENERATIONS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        # `embedding_cache` создаётся в Epic 60 (v3) — на реальной БД колонки
        # есть; guard `PRAGMA table_info` (аддитивный ALTER идемпотентен).
        # Синтетическая/усечённая legacy-БД может не иметь таблицы вовсе —
        # тогда шаг честно no-op (колонки появятся вместе с таблицей позже).
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("embedding_cache",))
        if await cursor.fetchone() is not None:
            cols = await self._embedding_cache_columns()
            for name, decl in _EMBEDDING_CACHE_IDENTITY_COLUMNS:
                if name not in cols:
                    await self.db.execute(
                        f"ALTER TABLE embedding_cache ADD COLUMN {name} {decl}")
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_EMBEDDING_IDENTITY}")
        await self.db.commit()

    async def _table_columns(self, table: str) -> set:
        """Имена колонок произвольной таблицы (guard для ALTER ADD COLUMN)."""
        cursor = await self.db.execute(f"PRAGMA table_info({table})")
        return {r["name"] for r in await cursor.fetchall()}

    async def _table_exists(self, table: str) -> bool:
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,))
        return await cursor.fetchone() is not None

    async def _migrate_observability_v19(self) -> None:
        """v19 (`mca-17a-observability-core`, ADR-1027-8 D2): durable run/
        incident-состояние + correlation/span-колонки.

        Аддитивно (`CREATE TABLE/INDEX IF NOT EXISTS` + `ALTER ADD COLUMN` под
        guard `PRAGMA table_info`); self-guard по `sqlite_master`; повторный
        прогон — no-op. `mca_process_registry` НЕ создаётся (реестр
        code-declared, D1). Старые таблицы/ID/vec-данные не трогаются.
        Всё `nullable` = честный unknown. PG — no-op. Фиксирует
        `PRAGMA user_version = 19`."""
        for table, ddl in (("mca_pipeline_runs", _MCA_PIPELINE_RUNS_DDL),
                           ("mca_incidents", _MCA_INCIDENTS_DDL)):
            if not await self._table_exists(table):
                await self.db.execute(ddl)
                await self.db.commit()
                logger.info("[database] migration v19: %s", table)
        for ddl in (_MCA_PIPELINE_RUNS_INDEX_DDL
                    + _MCA_INCIDENTS_INDEX_DDL):
            await self.db.execute(ddl)
        await self.db.commit()
        # task_jobs (v14) — correlation/span/progress; guard каждой колонки.
        if await self._table_exists("task_jobs"):
            cols = await self._table_columns("task_jobs")
            for name, decl in _TASK_JOBS_CORRELATION_COLUMNS:
                if name not in cols:
                    await self.db.execute(
                        f"ALTER TABLE task_jobs ADD COLUMN {name} {decl}")
            await self.db.commit()
            for ddl in _TASK_JOBS_CORRELATION_INDEX_DDL:
                await self.db.execute(ddl)
            await self.db.commit()
        # mca_events (v15) — расширение §27.3; guard каждой колонки.
        if await self._table_exists("mca_events"):
            cols = await self._table_columns("mca_events")
            for name, decl in _MCA_EVENTS_SPAN_COLUMNS:
                if name not in cols:
                    await self.db.execute(
                        f"ALTER TABLE mca_events ADD COLUMN {name} {decl}")
            await self.db.commit()
            for ddl in _MCA_EVENTS_SPAN_INDEX_DDL:
                await self.db.execute(ddl)
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_OBSERVABILITY}")
        await self.db.commit()

    async def _migrate_dossier_staging_v20(self) -> None:
        """v20 (`mca-04b-dossier-rebuild`, ADR-1027-9 D8/D13): регистр
        поколений + staging досье + nullable-тег `graph_facts`.

        Аддитивно (`CREATE TABLE/INDEX IF NOT EXISTS` + `ALTER ADD COLUMN`
        под guard `PRAGMA table_info`); self-guard по `sqlite_master`;
        повторный прогон — no-op. Старые таблицы/ID/FTS/vec/`origin` CHECK
        не трогаются; `nullable` = честный unknown (legacy-строки без
        поколения). PG — no-op (GEN-R4). Фиксирует
        `PRAGMA user_version = 20`."""
        if not await self._table_exists("mca_dossier_generations"):
            await self.db.execute(_MCA_DOSSIER_GENERATIONS_DDL)
            await self.db.commit()
            logger.info("[database] migration v20: mca_dossier_generations")
        for ddl in _MCA_DOSSIER_GENERATIONS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        if not await self._table_exists("mca_dossier_staging_items"):
            await self.db.execute(_MCA_DOSSIER_STAGING_ITEMS_DDL)
            await self.db.commit()
            logger.info("[database] migration v20: mca_dossier_staging_items")
        for ddl in _MCA_DOSSIER_STAGING_ITEMS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        # graph_facts — nullable-тег поколения (guard каждой колонки).
        if await self._table_exists("graph_facts"):
            cols = await self._table_columns("graph_facts")
            name, decl = _GRAPH_FACTS_DOSSIER_GENERATION_COLUMN
            if name not in cols:
                await self.db.execute(
                    f"ALTER TABLE graph_facts ADD COLUMN {name} {decl}")
                await self.db.commit()
                logger.info("[database] migration v20: graph_facts.%s", name)
            for ddl in _GRAPH_FACTS_DOSSIER_GENERATION_INDEX_DDL:
                await self.db.execute(ddl)
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_DOSSIER_STAGING}")
        await self.db.commit()

    async def _migrate_episodes_stories_v21(self) -> None:
        """v21 (`mca-05-episodes-stories`, ADR-1027-12 D2/§5): Episode/Story-
        модель — 7 таблиц + индексы + nullable override-колонки `mca_stories`.

        Аддитивно (`CREATE TABLE/INDEX IF NOT EXISTS` + `ALTER ADD COLUMN`
        под guard `PRAGMA table_info`); self-guard по `sqlite_master`;
        повторный прогон — no-op. Старые `lore_stories`/ID/потребители НЕ
        трогаются (паритет legacy); `nullable` = честный unknown. PG —
        no-op (GEN-R4). Фиксирует `PRAGMA user_version = 21`."""
        for table, ddl in (
                ("mca_episodes", _MCA_EPISODES_DDL),
                ("mca_stories", _MCA_STORIES_DDL),
                ("mca_story_versions", _MCA_STORY_VERSIONS_DDL),
                ("mca_story_episode_links", _MCA_STORY_EPISODE_LINKS_DDL),
                ("mca_story_continuations", _MCA_STORY_CONTINUATIONS_DDL),
                ("mca_story_redirects", _MCA_STORY_REDIRECTS_DDL),
                ("mca_story_legacy_links", _MCA_STORY_LEGACY_LINKS_DDL)):
            if not await self._table_exists(table):
                await self.db.execute(ddl)
                await self.db.commit()
                logger.info("[database] migration v21: %s", table)
        for ddl in _MCA_EPISODES_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        # Override-колонки (guard каждой — свежесозданная таблица уже имеет
        # их из DDL; legacy-созданная без них достраивается ALTER'ом).
        if await self._table_exists("mca_stories"):
            cols = await self._table_columns("mca_stories")
            for name, decl in _MCA_STORIES_OVERRIDE_COLUMNS:
                if name not in cols:
                    await self.db.execute(
                        f"ALTER TABLE mca_stories ADD COLUMN {name} {decl}")
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_EPISODES_STORIES}")
        await self.db.commit()

    async def _migrate_bot_outputs_v22(self) -> None:
        """v22 (`mca-22-attribution-memory-coherence`, spec §4.1/ADR-1028-6
        D2/D10): Durable Own Output Ledger — таблица `mca_bot_outputs` +
        3 индекса.

        Аддитивно (`CREATE TABLE/INDEX IF NOT EXISTS`, self-guard по
        `sqlite_master`); повторный прогон — no-op; существующие таблицы
        (`smart_messages`/`bot_replies`/прочие) НЕ трогаются. Append-only
        по контракту (UPDATE не выполняется ни в одной ветке кода). PG —
        no-op. Фиксирует `PRAGMA user_version = 22`."""
        if not await self._table_exists("mca_bot_outputs"):
            await self.db.execute(_MCA_BOT_OUTPUTS_DDL)
            await self.db.commit()
            logger.info("[database] migration v22: mca_bot_outputs")
        for ddl in _MCA_BOT_OUTPUTS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_BOT_OUTPUTS}")
        await self.db.commit()

    async def _migrate_embedding_control_plane_v23(self) -> None:
        """v23 (`asap-4-embedding-graphrag-cover-runtime`, spec §1 A.1/§7 +
        ADR-1028-7 D1/AM-1): Embedding Control Plane — таблица
        `embedding_quota_state` (runtime-состояние quota-групп) + 3
        аддитивные nullable-колонки реестра поколений v18 (`pause_reason`,
        `next_allowed_at`, `attempts_total`).

        Аддитивно: `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN`
        под guard `PRAGMA table_info`; НИ ОДНОГО UPDATE существующих строк;
        повторный прогон — no-op (self-guard); PG — no-op (спека §7).
        Обратимость: DROP новой таблицы безопасен; колонки NULL/default
        совместимы со старым кодом. Фиксирует `PRAGMA user_version = 23`."""
        if not await self._table_exists("embedding_quota_state"):
            await self.db.execute(_EMBEDDING_QUOTA_STATE_DDL)
            await self.db.commit()
            logger.info("[database] migration v23: embedding_quota_state")
        if await self._table_exists("mca_embedding_index_generations"):
            cols = await self._table_columns("mca_embedding_index_generations")
            for name, decl in _EMBEDDING_GENERATIONS_V23_COLUMNS:
                if name not in cols:
                    await self.db.execute(
                        f"ALTER TABLE mca_embedding_index_generations "
                        f"ADD COLUMN {name} {decl}")
                    logger.info(
                        "[database] migration v23: generations.%s added",
                        name)
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = "
            f"{_SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE}")
        await self.db.commit()

    async def _migrate_summary_source_window_v24(self) -> None:
        """v24 (`asap-4-1-durable-whole-window-summary`, spec §10.1 + §1 A.1
        + ADR-1028-8 D1): immutable per-run snapshot окна Саммари — таблица
        `summary_source_windows` (run_id PK, messages_json write-once).

        Аддитивно (`CREATE TABLE IF NOT EXISTS`); НИ ОДНОГО UPDATE/DELETE
        существующих строк; повторный прогон — no-op (self-guard по
        `sqlite_master`); PG — no-op (спека §0.1). Обратимость: DROP
        таблицы безопасен (не читается старым кодом). Фиксирует
        `PRAGMA user_version = 24`.

        Один шаг на версию v24: тут же применяются DDL таблиц 2/3
        (`summary_runs`/`summary_run_stages` — T-4616, self-guarded
        хелперы); покрывает и частично-мигрированные v24-БД (барьер
        `version > current` пропустил бы отдельные шаги при
        user_version=24 без таблиц)."""
        if not await self._table_exists("summary_source_windows"):
            await self.db.execute(_SUMMARY_SOURCE_WINDOWS_DDL)
            await self.db.commit()
            logger.info("[database] migration v24: summary_source_windows")
        await self._migrate_summary_runs_v24()
        await self._migrate_summary_run_stages_v24()
        await self.db.execute(
            f"PRAGMA user_version = "
            f"{_SCHEMA_VERSION_SUMMARY_SOURCE_WINDOW}")
        await self.db.commit()

    async def _migrate_summary_runs_v24(self) -> None:
        """v24, таблица 2 (T-4616, spec §10.2 + §5 E.1; ADR-1028-8 D6):
        durable SummaryRun — `summary_runs` (стабильный run_id PK, state
        machine §20, publication_status/result_ref, pipeline_health).

        Аддитивно (`CREATE TABLE IF NOT EXISTS` + индексы); НИ ОДНОГО
        UPDATE/DELETE существующих строк при миграции; повторный прогон —
        no-op (self-guard); PG — no-op (спека §0.1). Обратимость: DROP
        таблицы безопасен (не читается старым кодом). Фиксирует
        `PRAGMA user_version = 24` (спека §10: v24 = 3 таблицы)."""
        if not await self._table_exists("summary_runs"):
            await self.db.execute(_SUMMARY_RUNS_DDL)
            await self.db.commit()
            logger.info("[database] migration v24: summary_runs")
        for ddl in _SUMMARY_RUNS_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = "
            f"{_SCHEMA_VERSION_SUMMARY_SOURCE_WINDOW}")
        await self.db.commit()

    async def _migrate_summary_run_stages_v24(self) -> None:
        """v24, таблица 3 (T-4616, spec §10.3 + §5 E.1; ADR-1028-8 D6):
        append-only stage events `summary_run_stages` (§50.54-схема).

        Аддитивно (`CREATE TABLE IF NOT EXISTS` + индекс); НИ ОДНОГО
        UPDATE/DELETE существующих строк при миграции; повторный прогон —
        no-op (self-guard); PG — no-op. Обратимость: DROP таблицы безопасен.
        Фиксирует `PRAGMA user_version = 24`."""
        if not await self._table_exists("summary_run_stages"):
            await self.db.execute(_SUMMARY_RUN_STAGES_DDL)
            await self.db.commit()
            logger.info("[database] migration v24: summary_run_stages")
        for ddl in _SUMMARY_RUN_STAGES_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = "
            f"{_SCHEMA_VERSION_SUMMARY_SOURCE_WINDOW}")
        await self.db.commit()

    async def _migrate_dream_runs_v25(self) -> None:
        """v25 (`mca-06-sleep-paradigms`, spec §7.2/§11.2, ADR-1028-9 D5):
        durable отчёт прогона сна — 2 nullable-колонки `mca_pipeline_runs`
        (`chat_id`, `report_json`) + индекс `idx_mca_pipeline_runs_chat`.

        Аддитивно (`ALTER TABLE ADD COLUMN` под guard `PRAGMA table_info` +
        `CREATE INDEX IF NOT EXISTS`); НИ ОДНОГО UPDATE/DELETE существующих
        строк; повторный прогон — no-op (self-guard по `sqlite_master`); PG —
        no-op (GEN-R4). Обратимость: nullable-колонки старым кодом не
        читаются. Фиксирует `PRAGMA user_version = 25`."""
        if not await self._table_exists("mca_pipeline_runs"):
            # v19 создаёт таблицу раньше; на частично-мигрированной БД без неё
            # шаг честно no-op (колонки появятся вместе с таблицей).
            await self.db.execute(
                f"PRAGMA user_version = {_SCHEMA_VERSION_DREAM_RUNS}")
            await self.db.commit()
            return
        cols = await self._table_columns("mca_pipeline_runs")
        for name, decl in _MCA_PIPELINE_RUNS_DREAM_COLUMNS:
            if name not in cols:
                await self.db.execute(
                    f"ALTER TABLE mca_pipeline_runs ADD COLUMN {name} {decl}")
                logger.info("[database] migration v25: pipeline_runs.%s added",
                            name)
        await self.db.commit()
        for ddl in _MCA_PIPELINE_RUNS_CHAT_INDEX_DDL:
            await self.db.execute(ddl)
        await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_DREAM_RUNS}")
        await self.db.commit()

    # ── mca-22 (ADR-1028-6 D2): Durable Own Output Ledger — write/read ──────
    # Запись ТОЛЬКО реально доставленных outputs (недоставленный draft — не
    # «слова бота»; `delivery_status='failed'` не пишется write-path'ом фичи).
    # Правка собственного сообщения → новая revision-строка (append-only,
    # UPDATE/DELETE не выполняются). R17: content_hash — sha256 текста.

    async def record_bot_output(
            self, *, chat_id: int, bot_user_id: int | None = None,
            tg_message_id: int | None = None, revision_no: int = 1,
            sent_at: int | None = None, parent_message_ref: str | None = None,
            output_kind: str = "direct_reply", content_text: str | None = None,
            content_ref: str | None = None, content_hash: str | None = None,
            correlation_id: str | None = None, source_feature: str | None
            = None, delivery_status: str = "delivered",
            created_at: int | None = None) -> int | None:
        """Записать доставленный output бота (append-only). Fail-open: None.

        Косвенный маркер недоставленного — write-path фичи не вызывает этот
        метод (reason_code `bot_output_undelivered_skipped`), в таблице
        `delivery_status` остаётся контрактом схемы."""
        if output_kind not in BOT_OUTPUT_KINDS:
            output_kind = "other"
        if delivery_status not in BOT_OUTPUT_DELIVERY_STATUSES:
            delivery_status = "unknown"
        now = int(created_at if created_at is not None else time.time())

        async def _body(conn):
            cursor = await conn.execute(
                "INSERT INTO mca_bot_outputs (bot_user_id, chat_id, "
                "tg_message_id, revision_no, sent_at, parent_message_ref, "
                "output_kind, content_text, content_ref, content_hash, "
                "correlation_id, source_feature, delivery_status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bot_user_id, int(chat_id), tg_message_id,
                 max(1, int(revision_no or 1)), sent_at, parent_message_ref,
                 output_kind, content_text, content_ref, content_hash,
                 correlation_id, source_feature, delivery_status, now))
            return int(cursor.lastrowid)

        try:
            return await self.write_transaction(
                _body, op_name="bot_output_record")
        except Exception:
            logger.warning("[mca22] bot_output record failed | chat=%s",
                           chat_id, exc_info=True)
            return None

    @staticmethod
    def _bot_output_row_to_dict(row) -> dict | None:
        if row is None:
            return None
        keys = ("output_id", "bot_user_id", "chat_id", "tg_message_id",
                "revision_no", "sent_at", "parent_message_ref", "output_kind",
                "content_text", "content_ref", "content_hash",
                "correlation_id", "source_feature", "delivery_status",
                "created_at")
        return {k: row[k] for k in keys}

    async def get_bot_output_by_tg(self, chat_id: int,
                                   tg_message_id: int) -> dict | None:
        """Ledger-строка по `(chat_id, tg_message_id)` — последняя revision."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM mca_bot_outputs "
                "WHERE chat_id = ? AND tg_message_id = ? "
                "ORDER BY revision_no DESC, output_id DESC LIMIT 1",
                (int(chat_id), int(tg_message_id)))
            return self._bot_output_row_to_dict(await cursor.fetchone())
        except Exception:
            return None

    async def find_bot_outputs_by_hash(self, chat_id: int, content_hash: str,
                                       limit: int = 5) -> list[dict]:
        """Exact-match поиск по content_hash в чате (quote-priority 5)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM mca_bot_outputs "
                "WHERE chat_id = ? AND content_hash = ? AND "
                "delivery_status = 'delivered' "
                "ORDER BY output_id DESC LIMIT ?",
                (int(chat_id), str(content_hash), max(1, int(limit))))
            rows = await cursor.fetchall()
            return [d for d in (self._bot_output_row_to_dict(r)
                                for r in rows) if d is not None]
        except Exception:
            return []

    async def list_recent_bot_outputs(self, chat_id: int, limit: int = 20,
                                      kinds: tuple[str, ...] | None = None
                                      ) -> list[dict]:
        """Последние delivered-outputs чата (thread_chain/история обещаний).

        kinds — фильтр по `output_kind` (None = все)."""
        try:
            if kinds:
                marks = ",".join("?" for _ in kinds)
                sql = (f"SELECT * FROM mca_bot_outputs WHERE chat_id = ? AND "
                       f"delivery_status = 'delivered' AND output_kind IN "
                       f"({marks}) ORDER BY output_id DESC LIMIT ?")
                params = (int(chat_id), *kinds, max(1, int(limit)))
            else:
                sql = ("SELECT * FROM mca_bot_outputs WHERE chat_id = ? AND "
                       "delivery_status = 'delivered' "
                       "ORDER BY output_id DESC LIMIT ?")
                params = (int(chat_id), max(1, int(limit)))
            cursor = await self.db.execute(sql, params)
            rows = await cursor.fetchall()
            return [d for d in (self._bot_output_row_to_dict(r)
                                for r in rows) if d is not None]
        except Exception:
            return []

    # ── ASAP 4.1 волна 2 (ADR-1028-8 D1, spec §1 A.1): durable per-run
    # snapshot окна Саммари (`summary_source_windows`, v24). Write-once:
    # INSERT без overwrite; повторный INSERT → IntegrityError → False
    # (guard-инвариант: UPDATE messages_json после создания = дефект —
    # UPDATE строки не существует ни в одной ветке кода, закреплён тестом).
    # R17: messages_json живёт только в БД, наружу не логируется.

    async def save_summary_source_window(
            self, *, run_id: str, chat_id: int, window_from: int | None,
            window_to: int | None, source_message_count: int,
            messages_json: str, created_at: int) -> bool:
        """Write-once запись snapshot'а окна (single write в SOURCE_READY).

        ``True`` — записан; ``False`` — run_id уже существует (в т.ч. незави-
        симый совпадающий run) — fail-open, без overwrite. Никогда не бросает."""
        async def _body(conn):
            cursor = await conn.execute(
                "INSERT INTO summary_source_windows (run_id, chat_id, "
                "window_from, window_to, source_message_count, "
                "messages_json, created_at) VALUES (?,?,?,?,?,?,?)",
                (str(run_id), int(chat_id), window_from, window_to,
                 int(source_message_count), str(messages_json),
                 int(created_at)))
            return True

        try:
            return await self.write_transaction(
                _body, op_name="summary_source_window_save")
        except Exception as exc:
            # Write-once guard: повторный INSERT того же run_id — честный
            # сигнал «snapshot уже создан» (без overwrite/UPDATE).
            if _summary_window_unique_violation(exc):
                logger.info(
                    "[summary41] source window already exists (write-once) | "
                    "run_id=%s", str(run_id)[:64])
                return False
            logger.warning(
                "[summary41] source window save failed | run_id=%s",
                str(run_id)[:64], exc_info=True)
            return False

    async def get_summary_source_window(self, run_id: str) -> dict | None:
        """Прочитать snapshot row по run_id (restart-safe; fail-open → None)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM summary_source_windows WHERE run_id = ?",
                (str(run_id),))
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "run_id": row["run_id"],
                "chat_id": row["chat_id"],
                "window_from": row["window_from"],
                "window_to": row["window_to"],
                "source_message_count": row["source_message_count"],
                "messages_json": row["messages_json"],
                "created_at": row["created_at"],
            }
        except Exception:
            logger.warning("[summary41] source window read failed "
                           "| run_id=%s", str(run_id)[:64], exc_info=True)
            return None

    async def purge_summary_source_windows(self, *, before_ts: int) -> int:
        """TTL-очистка snapshot'ов (единственный удалитель окон; только эта
        таблица, НИ ОДНОЙ существующей SQL). Fail-open → 0."""
        async def _body(conn):
            cursor = await conn.execute(
                "DELETE FROM summary_source_windows WHERE created_at < ?",
                (int(before_ts),))
            return int(cursor.rowcount or 0)

        try:
            return await self.write_transaction(
                _body, op_name="summary_source_window_purge")
        except Exception:
            logger.warning("[summary41] source window purge failed",
                           exc_info=True)
            return 0

    async def purge_summary_source_windows_gated(
            self, *, before_ts: int, terminal_states: tuple[str, ...]) -> int:
        """TTL-очистка окон с гейтом незавершённых run'ов (T-4616, spec §5
        E.1: purge только после DONE/FAILED).

        Удаляет окна старше горизонта, чей run терминален ИЛИ отсутствует
        в `summary_runs` (window-only контур волны 2 — совместимо: окна без
        run-row очищаются как раньше). Fail-open → 0."""
        states = tuple(str(s) for s in (terminal_states or ()))
        if not states:
            return await self.purge_summary_source_windows(before_ts=before_ts)

        async def _body(conn):
            marks = ",".join("?" for _ in states)
            cursor = await conn.execute(
                "DELETE FROM summary_source_windows WHERE created_at < ? AND "
                "run_id NOT IN (SELECT run_id FROM summary_runs WHERE "
                f"state NOT IN ({marks}))",
                (int(before_ts), *states))
            return int(cursor.rowcount or 0)

        try:
            return await self.write_transaction(
                _body, op_name="summary_source_window_purge_gated")
        except Exception:
            # fail-open: гейт не должен блокировать очистку — обычный путь.
            return await self.purge_summary_source_windows(before_ts=before_ts)

    # ── ASAP 4.1 волна 5 (T-4616/T-4617, spec §5 E.1/E.2; ADR-1028-8 D6):
    # durable SummaryRun (`summary_runs`) + append-only stage events
    # (`summary_run_stages`). Checkpoint run-state — ЗДЕСЬ, не в task_jobs
    # payload (L-EXTRA-6 не наследуется); mca_pipeline_runs не перегружается.
    # R17: в строках только state-машина/числа/safe refs (никаких текстов).

    _SUMMARY_RUN_COLS = ("run_id", "chat_id", "state", "manual",
                         "window_from", "window_to", "source_ref",
                         "publication_status", "publication_result_ref",
                         "pipeline_health", "created_at", "updated_at")

    async def create_summary_run(
            self, *, run_id: str, chat_id: int, state: str = "CREATED",
            manual: bool = False, created_at: int | None = None) -> bool:
        """Создать run-row (стабильный run_id, один раз; INSERT OR IGNORE
        — повторный вызов того же run_id идемпотентен). Fail-open → False."""
        now = int(created_at if created_at is not None else time.time())

        async def _body(conn):
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO summary_runs (run_id, chat_id, state, "
                "manual, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (str(run_id), int(chat_id), str(state or "CREATED"),
                 1 if manual else 0, now, now))
            return int(cursor.rowcount or 0)

        try:
            return bool(await self.write_transaction(
                _body, op_name="summary_run_create"))
        except Exception:
            logger.warning("[summary41] run create failed | run_id=%s",
                           str(run_id)[:64], exc_info=True)
            return False

    async def update_summary_run_state(
            self, run_id: str, state: str, *, window_from: int | None = None,
            window_to: int | None = None, source_ref: str | None = None,
            pipeline_health: str | None = None) -> bool:
        """Checkpoint run-state (§20 state machine; не immutable — это
        checkpoint, в отличие от write-once snapshot'а окна). Adдитивные
        поля пишутся только при переданных not-None значениях."""
        sets = ["state = ?", "updated_at = ?"]
        params: list = [str(state), int(time.time())]
        if window_from is not None:
            sets.append("window_from = ?")
            params.append(int(window_from))
        if window_to is not None:
            sets.append("window_to = ?")
            params.append(int(window_to))
        if source_ref is not None:
            sets.append("source_ref = ?")
            params.append(str(source_ref))
        if pipeline_health is not None:
            sets.append("pipeline_health = ?")
            params.append(str(pipeline_health))
        params.append(str(run_id))

        async def _body(conn):
            cursor = await conn.execute(
                f"UPDATE summary_runs SET {', '.join(sets)} "
                "WHERE run_id = ?", tuple(params))
            return cursor.rowcount

        try:
            return bool(await self.write_transaction(
                _body, op_name="summary_run_state"))
        except Exception:
            logger.warning("[summary41] run state update failed | run_id=%s",
                           str(run_id)[:64], exc_info=True)
            return False

    async def set_summary_run_publication(
            self, run_id: str, publication_status: str, *,
            result_ref: str | None = None) -> bool:
        """publication_status (T-4617: PUBLISHING фиксируется ДО отправки;
        published/failed — по исходу). Существующий published никогда не
        перезаписывается (идемпотентность — двойной финал невозможен)."""
        async def _body(conn):
            cursor = await conn.execute(
                "SELECT publication_status FROM summary_runs WHERE "
                "run_id = ?", (str(run_id),))
            row = await cursor.fetchone()
            if row is None:
                return 0
            if str(row["publication_status"] or "") == "published":
                return 0        # уже опубликован — no-op (идемпотентность)
            if result_ref is not None:
                cursor = await conn.execute(
                    "UPDATE summary_runs SET publication_status = ?, "
                    "publication_result_ref = ?, updated_at = ? "
                    "WHERE run_id = ?",
                    (str(publication_status),
                     str(result_ref), int(time.time()), str(run_id)))
            else:
                cursor = await conn.execute(
                    "UPDATE summary_runs SET publication_status = ?, "
                    "updated_at = ? WHERE run_id = ?",
                    (str(publication_status), int(time.time()), str(run_id)))
            return cursor.rowcount

        try:
            return bool(await self.write_transaction(
                _body, op_name="summary_run_publication"))
        except Exception:
            logger.warning("[summary41] run publication update failed "
                           "| run_id=%s", str(run_id)[:64], exc_info=True)
            return False

    async def get_summary_run(self, run_id: str) -> dict | None:
        """Прочитать run-row (restart-safe resume; fail-open → None)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM summary_runs WHERE run_id = ?", (str(run_id),))
            row = await cursor.fetchone()
            if row is None:
                return None
            return {k: row[k] for k in self._SUMMARY_RUN_COLS}
        except Exception:
            logger.warning("[summary41] run read failed | run_id=%s",
                           str(run_id)[:64], exc_info=True)
            return None

    async def get_active_summary_run_for_chat(self, chat_id: int) -> dict | None:
        """Незавершённый run чата (T-4617 resume §21: рестарт не начинает
        Summary заново — докатывается ЭТОТ run). Терминальные состояния
        исключены; самый свежий по created_at."""
        marks = ",".join("?" for _ in ("DONE", "DEGRADED", "FAILED"))
        try:
            cursor = await self.db.execute(
                "SELECT * FROM summary_runs WHERE chat_id = ? AND "
                f"state NOT IN ({marks}) ORDER BY created_at DESC LIMIT 1",
                (int(chat_id), "DONE", "DEGRADED", "FAILED"))
            row = await cursor.fetchone()
            if row is None:
                return None
            return {k: row[k] for k in self._SUMMARY_RUN_COLS}
        except Exception:
            logger.warning("[summary41] active run read failed | chat=%s",
                           chat_id, exc_info=True)
            return None

    async def get_bot_output_by_correlation(
            self, chat_id: int, correlation_id: str) -> dict | None:
        """Последний доставленный output run'а по correlation_id
        (T-4617 reconcile kill-in-PUBLISHING: sent unknown → ledger-факт).
        Индекс `idx_mca_bot_outputs_corr`; fail-open → None."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM mca_bot_outputs WHERE chat_id = ? AND "
                "correlation_id = ? AND delivery_status = 'delivered' "
                "ORDER BY output_id DESC LIMIT 1",
                (int(chat_id), str(correlation_id)))
            row = await cursor.fetchone()
            return self._bot_output_row_to_dict(row) if row is not None \
                else None
        except Exception:
            return None

    async def record_summary_run_stage(
            self, run_id: str, stage: str, *, status: str = "ok",
            started_at: int | None = None, attempt: int = 0,
            provider: str | None = None, model: str | None = None,
            result_ref: str | None = None,
            reason_code: str | None = None) -> int | None:
        """Append-only stage event (§50.54, T-4616): одна строка на
        завершённую стадию/попытку (retry = НОВАЯ строка; история не
        переиспользуется и не удаляется — единственный UPDATE surface у
        таблицы отсутствует вовсе). Возвращает stage_id (fail-open → None)."""
        now = int(time.time())
        start = int(started_at) if started_at is not None else now

        async def _body(conn):
            cursor = await conn.execute(
                "INSERT INTO summary_run_stages (run_id, stage, status, "
                "started_at, last_activity_at, finished_at, attempt, "
                "provider, model, result_ref, reason_code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(run_id), str(stage), str(status), start, now, now,
                 max(0, int(attempt or 0)),
                 str(provider) if provider else None,
                 str(model) if model else None,
                 str(result_ref) if result_ref else None,
                 str(reason_code) if reason_code else None))
            return int(cursor.lastrowid)

        try:
            return await self.write_transaction(
                _body, op_name="summary_run_stage_record")
        except Exception:
            logger.warning("[summary41] stage record failed | run_id=%s "
                           "| stage=%s", str(run_id)[:64], str(stage),
                           exc_info=True)
            return None

    async def list_summary_run_stages(self, run_id: str) -> list[dict]:
        """Stage-история run'а (append-only порядок; источник Inspector'а
        зоны G — structured state, не парсинг логов)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM summary_run_stages WHERE run_id = ? "
                "ORDER BY id ASC", (str(run_id),))
            rows = await cursor.fetchall()
            out = []
            for row in rows:
                out.append({
                    "id": row["id"], "run_id": row["run_id"],
                    "stage": row["stage"], "status": row["status"],
                    "started_at": row["started_at"],
                    "last_activity_at": row["last_activity_at"],
                    "finished_at": row["finished_at"],
                    "attempt": row["attempt"], "provider": row["provider"],
                    "model": row["model"], "result_ref": row["result_ref"],
                    "reason_code": row["reason_code"]})
            return out
        except Exception:
            logger.warning("[summary41] stage list failed | run_id=%s",
                           str(run_id)[:64], exc_info=True)
            return []

    async def last_completed_summary_run_stage(self, run_id: str
                                               ) -> dict | None:
        """Последняя успешно завершённая стадия (resume после рестарта,
        §21: продолжение с неё)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM summary_run_stages WHERE run_id = ? AND "
                "status IN ('ok', 'degraded') ORDER BY id DESC LIMIT 1",
                (str(run_id),))
            row = await cursor.fetchone()
            if row is None:
                return None
            return {"stage": row["stage"], "status": row["status"],
                    "finished_at": row["finished_at"],
                    "attempt": row["attempt"],
                    "result_ref": row["result_ref"]}
        except Exception:
            logger.warning("[summary41] stage read failed | run_id=%s",
                           str(run_id)[:64], exc_info=True)
            return None

    async def purge_expired_summary_runs(
            self, *, before_ts: int, terminal_states: tuple[str, ...]) -> int:
        """TTL-очистка run'ов + стадий (T-4616: гейт ТОЛЬКО после
        DONE/FAILED/DEGRADED — незавершённые/активные run'ы не задеваются;
        их окна защищены тем же гейтом). Возвращает число удалённых run'ов."""
        states = tuple(str(s) for s in (terminal_states or ()))
        if not states:
            return 0

        async def _body(conn):
            marks = ",".join("?" for _ in states)
            cursor = await conn.execute(
                "SELECT run_id FROM summary_runs WHERE updated_at < ? AND "
                f"state IN ({marks})", (int(before_ts), *states))
            ids = [r["run_id"] for r in await cursor.fetchall()]
            for rid in ids:
                await conn.execute(
                    "DELETE FROM summary_run_stages WHERE run_id = ?", (rid,))
                await conn.execute(
                    "DELETE FROM summary_source_windows WHERE run_id = ?",
                    (rid,))
                await conn.execute(
                    "DELETE FROM summary_runs WHERE run_id = ?", (rid,))
            return len(ids)

        try:
            return int(await self.write_transaction(
                _body, op_name="summary_run_purge") or 0)
        except Exception:
            logger.warning("[summary41] run purge failed", exc_info=True)
            return 0

    async def resolve_source_ref_ids(self, chat_id: int,
                                     entity_pairs: list[tuple[str, str]]
                                     ) -> dict[tuple[str, str], int]:
        """Batched get-or-lookup SourceRef id по (entity_type, entity_id)
        (mca-04a; ОДИН SELECT, без N+1 — §30). Только существующие ссылки
        попадают в результат (создание — обязанность producers, не read)."""
        if not entity_pairs:
            return {}
        try:
            marks = ",".join("(?,?)" for _ in entity_pairs)
            sql = (f"SELECT entity_type, entity_id, source_ref_id "
                   f"FROM mca_source_refs WHERE chat_id = ? AND "
                   f"(entity_type, entity_id) IN ({marks})")
            params: list = [int(chat_id)]
            for etype, eid in entity_pairs:
                params.extend([str(etype), str(eid)])
            cursor = await self.db.execute(sql, tuple(params))
            rows = await cursor.fetchall()
            return {(r["entity_type"], r["entity_id"]):
                    int(r["source_ref_id"]) for r in rows}
        except Exception:
            return {}

    # ── mca-04b (ADR-1027-9 D8): регистр поколений + staging + активация ────
    # Атомарная активация — одна короткая транзакция под single-writer
    # (`write_transaction`); прежняя версия (`active`) → `superseded` и
    # остаётся в `graph_facts` (не удаляется); повтор/рестарт идемпотентны.
    # MCA14-R3: без долгой транзакции (чтение/LLM/staging — снаружи).

    async def create_dossier_generation(
            self, chat_id: int, subject_ref_id: int, *,
            scope_kind: str | None = None, range_from_ts: int | None = None,
            range_to_ts: int | None = None, snapshot_boundary_ts: int | None
            = None, snapshot_boundary_id: int | None = None,
            extractor_version: str | None = None,
            kernel_version: str | None = None, counters_json: str | None
            = None, staging_ref: str | None = None,
            supersedes_generation_id: str | None = None,
            backup_ref: str | None = None,
            now: int | None = None) -> str | None:
        """Зарегистрировать поколение досье со статусом `building`.

        Возвращает `generation_id` (UUID4 hex) или None (fail-open: ошибка/
        provenance-реестр недоступен). Одна `active` на (chat, subject)
        гарантируется partial UNIQUE при активации."""
        import uuid
        generation_id = uuid.uuid4().hex
        ts = int(now if now is not None else time.time())

        async def _body(_conn):
            await self.db.execute(
                "INSERT INTO mca_dossier_generations (generation_id, chat_id, "
                "subject_ref_id, state, scope_kind, range_from_ts, "
                "range_to_ts, snapshot_boundary_ts, snapshot_boundary_id, "
                "extractor_version, kernel_version, counters_json, "
                "staging_ref, supersedes_generation_id, backup_ref, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (generation_id, int(chat_id), int(subject_ref_id), "building",
                 scope_kind, range_from_ts, range_to_ts, snapshot_boundary_ts,
                 snapshot_boundary_id,
                 str(extractor_version or "unknown"), kernel_version,
                 counters_json, staging_ref, supersedes_generation_id,
                 backup_ref, ts))
            return generation_id

        try:
            return await self.write_transaction(
                _body, op_name="dossier_generation_create")
        except Exception:
            logger.warning("[database] dossier generation create failed",
                           exc_info=True)
            return None

    async def get_dossier_generation(self, generation_id: str) -> dict | None:
        """Поколение по id или None (fail-open)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM mca_dossier_generations WHERE generation_id = ?",
                (str(generation_id),))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        except Exception:
            logger.debug("[database] dossier generation read failed",
                         exc_info=True)
            return None

    async def get_active_dossier_generation(
            self, chat_id: int, subject_ref_id: int) -> dict | None:
        """Активное поколение (chat, subject) или None (fail-open)."""
        try:
            cursor = await self.db.execute(
                "SELECT * FROM mca_dossier_generations WHERE chat_id = ? AND "
                "subject_ref_id = ? AND state = 'active'",
                (int(chat_id), int(subject_ref_id)))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        except Exception:
            logger.debug("[database] active dossier generation read failed",
                         exc_info=True)
            return None

    async def set_dossier_generation_state(
            self, generation_id: str, state: str, *,
            counters_json: str | None = None, staging_ref: str | None = None,
            backup_ref: str | None = None, finished: bool = False,
            now: int | None = None) -> bool:
        """Обновить состояние поколения (building→failed/active и т. п.).

        Активацию выполняет `activate_dossier_generation` (атомарно) — здесь
        только служебные переходы (failed/superseded вручную не ставятся).
        False — поколение не найдено/ошибка."""
        if state not in (DOSSIER_GENERATION_STATES - {"active", "superseded"}):
            logger.warning(
                "[database] set_dossier_generation_state: state=%s не "
                "допустим через этот путь (активация — атомарная)", state)
            return False
        ts = int(now if now is not None else time.time())
        sets = ["state = ?"]
        params: list = [state]
        if counters_json is not None:
            sets.append("counters_json = ?")
            params.append(counters_json)
        if staging_ref is not None:
            sets.append("staging_ref = ?")
            params.append(staging_ref)
        if backup_ref is not None:
            sets.append("backup_ref = ?")
            params.append(backup_ref)
        if finished:
            sets.append("finished_at = ?")
            params.append(ts)

        async def _body(_conn):
            await self.db.execute(
                f"UPDATE mca_dossier_generations SET {', '.join(sets)} "
                "WHERE generation_id = ?", [*params, str(generation_id)])
            return True

        try:
            return bool(await self.write_transaction(
                _body, op_name="dossier_generation_state"))
        except Exception:
            logger.warning("[database] dossier generation state update failed",
                           exc_info=True)
            return False

    async def insert_dossier_staging_item(
            self, generation_id: str, item_kind: str, *,
            subject_ref_id: int | None = None, source_ref_id: int | None
            = None, classification: str | None = None, payload: dict | None
            = None, verification: str = "tentative",
            extractor_version: str | None = None,
            now: int | None = None) -> int | None:
        """Добавить staged-элемент (до активации читателям не виден).

        Возвращает `staging_id` или None (fail-open). `payload` — R17-safe
        структура (без сырого контекста)."""
        if item_kind not in DOSSIER_STAGING_ITEM_KINDS:
            logger.warning("[database] staging item kind=%s недопустим",
                           item_kind)
            return None
        if verification not in DOSSIER_STAGING_VERIFICATIONS:
            verification = "tentative"
        ts = int(now if now is not None else time.time())

        async def _body(_conn):
            cursor = await self.db.execute(
                "INSERT INTO mca_dossier_staging_items (generation_id, "
                "item_kind, subject_ref_id, source_ref_id, classification, "
                "payload_json, verification, extractor_version, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (str(generation_id), item_kind, subject_ref_id, source_ref_id,
                 classification,
                 json.dumps(payload or {}, ensure_ascii=False), verification,
                 extractor_version, ts))
            return int(cursor.lastrowid or 0)

        try:
            return await self.write_transaction(
                _body, op_name="dossier_staging_insert")
        except Exception:
            logger.warning("[database] staging item insert failed",
                           exc_info=True)
            return None

    async def list_dossier_staging_items(
            self, generation_id: str) -> list[dict]:
        """Staged-элементы поколения (по `staging_id` ASC)."""
        try:
            cursor = await self.db.execute(
                "SELECT staging_id, generation_id, item_kind, subject_ref_id, "
                "source_ref_id, classification, payload_json, verification, "
                "extractor_version, created_at FROM mca_dossier_staging_items "
                "WHERE generation_id = ? ORDER BY staging_id ASC",
                (str(generation_id),))
            return [dict(r) for r in await cursor.fetchall()]
        except Exception:
            logger.debug("[database] staging items read failed",
                         exc_info=True)
            return []

    async def activate_dossier_generation(
            self, generation_id: str, *, now: int | None = None) -> dict:
        """Атомарная активация поколения досье (ADR-1027-9 D8, SC-12).

        Одна короткая транзакция под single-writer:
          1. применить staged-элементы к `graph_facts`
             (с `dossier_generation_id` = поколение; идемпотентно — дедуп
             портрет/личный факт/мем);
          2. прежнее `active` (chat, subject) → `superseded` (+superseded_at);
          3. поколение `building` → `active` (+activated_at).

        Идемпотентно: повтор на `active`-поколении — no-op (ничего не
        удваивается). Строки `superseded`-поколения НЕ удаляются (прежняя
        версия доступна до замены/для rollback). Ручные правки
        (`persona_dossier_overrides`) и исходные сообщения не затрагиваются.
        Возврат: `{"applied", "superseded_generation_id", "state"}`.
        Бросает `ValueError` при недопустимом переходе (failed/unknown)."""
        ts = int(now if now is not None else time.time())
        result = {"applied": 0, "superseded_generation_id": None,
                  "state": "unknown"}

        async def _body(_conn):
            cursor = await self.db.execute(
                "SELECT generation_id, chat_id, subject_ref_id, state, "
                "supersedes_generation_id FROM mca_dossier_generations "
                "WHERE generation_id = ?", (str(generation_id),))
            gen = await cursor.fetchone()
            if gen is None:
                raise ValueError("generation_not_found")
            if gen["state"] == "active":
                # Идемпотентный повтор — ничего не применяем повторно.
                result["state"] = "active"
                return result
            if gen["state"] != "building":
                raise ValueError(f"generation_state_invalid:{gen['state']}")
            chat_id = int(gen["chat_id"])
            subject_ref_id = int(gen["subject_ref_id"])
            # 1. Применить staged-элементы (идемпотентно).
            cursor = await self.db.execute(
                "SELECT staging_id, item_kind, subject_ref_id, source_ref_id, "
                "classification, payload_json, verification, "
                "extractor_version FROM mca_dossier_staging_items "
                "WHERE generation_id = ? ORDER BY staging_id ASC",
                (str(generation_id),))
            items = await cursor.fetchall()
            applied = 0
            for item in items:
                try:
                    payload = json.loads(item["payload_json"] or "{}")
                except (TypeError, ValueError):
                    payload = {}
                kind = str(item["item_kind"] or "")
                target = str(payload.get("target_user") or "").strip()
                if kind == "portrait":
                    text = _dossier_render_portrait(payload)
                    if not text or not target:
                        continue
                    cursor = await self.db.execute(
                        "SELECT id FROM graph_facts WHERE chat_id = ? AND "
                        "target_user = ? AND status = 'dossier_portrait' "
                        "ORDER BY id DESC LIMIT 1", (chat_id, target))
                    row = await cursor.fetchone()
                    meta_json = json.dumps({
                        "generated": True, "generator": "layer_b",
                        "contract_version": 2,
                        "generation_id": str(generation_id),
                        "patterns": [str(x) for x in
                                     (payload.get("patterns") or [])],
                        "themes": [str(x) for x in
                                   (payload.get("themes") or [])],
                        "updated_at": ts,
                    }, ensure_ascii=False)
                    if row is None:
                        cursor = await self.db.execute(
                            "INSERT INTO graph_facts (chat_id, fact, origin, "
                            "expires_at, created_at, target_user, status, "
                            "weight, last_confirmed_at, importance, kind, "
                            "belief_meta, dossier_generation_id) "
                            "VALUES (?,?,'chat_history',NULL,?,?,"
                            "'dossier_portrait',0.3,?,"
                            "5,'fact',?,?)",
                            (chat_id, text, ts, target, ts, meta_json,
                             str(generation_id)))
                        fid = cursor.lastrowid
                    else:
                        fid = int(row["id"])
                        # FIX (инвариант 10): прежний портрет — в историю
                        # meta (не стирается), строка обновляется на месте.
                        cursor = await self.db.execute(
                            "SELECT belief_meta FROM graph_facts WHERE "
                            "id = ?", (fid,))
                        old = await cursor.fetchone()
                        prev_meta: dict = {}
                        try:
                            parsed = json.loads(
                                (old["belief_meta"] if old else "") or "{}")
                            if isinstance(parsed, dict):
                                prev_meta = parsed
                        except (TypeError, ValueError):
                            prev_meta = {}
                        history = list(prev_meta.get("portrait_history") or [])
                        prev_text = prev_meta.get("previous_text")
                        if prev_text:
                            history.append({
                                "text": str(prev_text)[:400],
                                "updated_at": int(
                                    prev_meta.get("updated_at") or 0)})
                        history = history[-4:]
                        prev_meta.update({
                            "previous_text": text,
                            "portrait_history": history,
                            "updated_at": ts,
                            "generation_id": str(generation_id),
                        })
                        await self.db.execute(
                            "DELETE FROM graph_facts_fts WHERE rowid = ?",
                            (fid,))
                        await self.db.execute(
                            "UPDATE graph_facts SET fact = ?, belief_meta = ?,"
                            " created_at = ?, dossier_generation_id = ? "
                            "WHERE id = ?",
                            (text, json.dumps(prev_meta, ensure_ascii=False),
                             ts, str(generation_id), fid))
                        await self.db.execute(
                            "INSERT INTO graph_facts_fts(rowid, fact) "
                            "VALUES (?, ?)", (fid, text))
                    applied += 1
                elif kind == "person_fact":
                    text = str(payload.get("text") or "").strip()
                    if not text:
                        continue
                    cursor = await self.db.execute(
                        "SELECT 1 FROM graph_facts WHERE chat_id = ? AND "
                        "fact = ? AND status = 'unconfirmed' LIMIT 1",
                        (chat_id, text))
                    if await cursor.fetchone() is not None:
                        continue                     # дедуп (идемпотентность)
                    method = payload.get("attribution_method") or "third_party"
                    akind = payload.get("assertion_kind") or "unknown"
                    cursor = await self.db.execute(
                        "INSERT INTO graph_facts (chat_id, fact, origin, "
                        "expires_at, created_at, target_user, status, weight,"
                        " last_confirmed_at, importance, kind, "
                        "subject_ref_id, attribution_method, assertion_kind,"
                        " extractor_version, provenance_channel, "
                        "dossier_generation_id) "
                        "VALUES (?,?,'chat_history',NULL,?,?,'unconfirmed',"
                        "0.5,?,5,'fact',"
                        "?,?,?,?,'dossier_layer_b',?)",
                        (chat_id, text, ts, target, ts,
                         item["subject_ref_id"], method, akind,
                         item["extractor_version"]
                         or _provenance_extractor_version(),
                         str(generation_id)))
                    fid = cursor.lastrowid
                    await self.db.execute(
                        "INSERT INTO graph_facts_fts(rowid, fact) VALUES "
                        "(?, ?)", (fid, text))
                    applied += 1
                elif kind == "meme":
                    text = str(payload.get("text") or "").strip()
                    if not text or not target:
                        continue
                    cursor = await self.db.execute(
                        "SELECT 1 FROM graph_facts WHERE chat_id = ? AND "
                        "target_user = ? AND fact = ? AND status = "
                        "'chat_meme' LIMIT 1", (chat_id, target, text))
                    if await cursor.fetchone() is not None:
                        continue
                    cursor = await self.db.execute(
                        "INSERT INTO graph_facts (chat_id, fact, origin, "
                        "expires_at, created_at, target_user, status, weight,"
                        " last_confirmed_at, importance, kind, belief_meta, "
                        "dossier_generation_id) "
                        "VALUES (?,?,'chat_history',NULL,?,?,'chat_meme',0.4,"
                        "?,5,'fact',"
                        "?,?)",
                        (chat_id, text, ts, target, ts,
                         json.dumps({"meme": True, "source": "dossier",
                                     "classified_by": "llm",
                                     "confidence": 0.8, "created_at": ts},
                                    ensure_ascii=False),
                         str(generation_id)))
                    fid = cursor.lastrowid
                    await self.db.execute(
                        "INSERT INTO graph_facts_fts(rowid, fact) VALUES "
                        "(?, ?)", (fid, text))
                    applied += 1
            result["applied"] = applied
            # 2. Прежнее active → superseded.
            cursor = await self.db.execute(
                "SELECT generation_id FROM mca_dossier_generations WHERE "
                "chat_id = ? AND subject_ref_id = ? AND state = 'active'",
                (chat_id, subject_ref_id))
            prev = await cursor.fetchone()
            if prev is not None:
                await self.db.execute(
                    "UPDATE mca_dossier_generations SET state = 'superseded',"
                    " finished_at = ? WHERE generation_id = ?",
                    (ts, prev["generation_id"]))
                result["superseded_generation_id"] = prev["generation_id"]
            # 3. building → active.
            await self.db.execute(
                "UPDATE mca_dossier_generations SET state = 'active', "
                "activated_at = ?, finished_at = ? WHERE generation_id = ?",
                (ts, ts, str(generation_id)))
            result["state"] = "active"
            return result

        return await self.write_transaction(
            _body, op_name="dossier_generation_activate")

    async def activate_embedding_generation(
            self, index_name: str, generation_id: str) -> dict | None:
        """N-MCA07-1 (ADR-1027-9 D12/spec §4.8): single-writer операция
        активации vec-поколения (REUSE v18 — без новой таблицы).

        Текущее `active` → `superseded` (+superseded_at); целевое
        (`building`/`failed`) → `active` (+activated_at). Повтор на уже
        активном — no-op. `ensure_embedding_generation` при существующем
        active остаётся no-op (A06 не нарушается). Гейт —
        `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` (проверяет вызывающий).
        Возврат — dict операции или None (не найдено/ошибка)."""
        now = int(time.time())
        result: dict | None = None

        async def _body(_conn):
            cursor = await self.db.execute(
                "SELECT generation_id, index_name, status FROM "
                "mca_embedding_index_generations WHERE generation_id = ?",
                (str(generation_id),))
            target = await cursor.fetchone()
            if target is None:
                return None
            if str(target["index_name"]) != str(index_name):
                return None
            if target["status"] == "active":
                return {"generation_id": str(generation_id),
                        "status": "active", "superseded_generation_id": None}
            if target["status"] not in ("building", "failed"):
                return None
            cursor = await self.db.execute(
                "SELECT generation_id FROM mca_embedding_index_generations "
                "WHERE index_name = ? AND status = 'active'",
                (str(index_name),))
            prev = await cursor.fetchone()
            if prev is not None:
                await self.db.execute(
                    "UPDATE mca_embedding_index_generations SET status = "
                    "'superseded', superseded_at = ? WHERE generation_id = ?",
                    (now, prev["generation_id"]))
            await self.db.execute(
                "UPDATE mca_embedding_index_generations SET status = "
                "'active', activated_at = ?, superseded_at = NULL WHERE "
                "generation_id = ?", (now, str(generation_id)))
            return {"generation_id": str(generation_id), "status": "active",
                    "superseded_generation_id": (
                        prev["generation_id"] if prev is not None else None)}

        try:
            async with self.serialized():
                result = await _body(self.db)
                await self.db.commit()
            return result
        except Exception:
            logger.warning("[database] activate_embedding_generation failed",
                           exc_info=True)
            return None

    async def facts_without_evidence_links(
            self, chat_id: int, *, target_user: str | None = None,
            limit: int = 5) -> list[dict]:
        """Confirmed-факты чата/(участника) без прямой EvidenceLink
        (read-time reconstruction — mca-04b T-3896/T-3903, bounded).

        Кандидаты — свежие первыми (SQL LIMIT = bounded-скан); фильтр «нет
        derived_from/supports» — в Python через `get_evidence_links`
        (идемпотентно: у факта с уже записанной связкой
        `reconstruct_fact_provenance` сам no-op). Fail-open → []."""
        sql = ("SELECT id, fact, chat_id, target_user FROM graph_facts "
               "WHERE chat_id = ? AND status = 'confirmed' AND kind = 'fact' ")
        params: list = [int(chat_id)]
        if target_user:
            sql += "AND target_user = ? "
            params.append(str(target_user))
        sql += "ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)) * 4)
        try:
            cursor = await self.db.execute(sql, params)
            rows = [dict(r) for r in await cursor.fetchall()]
        except Exception:
            return []
        out: list[dict] = []
        for row in rows:
            try:
                from services import provenance as _prov
                ref = await _prov.resolve_source_ref(
                    self, _prov.graph_fact_source_ref(chat_id, row["id"]))
                if ref is None:
                    continue
                links = await _prov.get_evidence_links(self, ref)
                if not any(str(l.get("link_type")) in
                           ("derived_from", "supports") for l in links):
                    out.append(row)
            except Exception:
                continue
            if len(out) >= max(1, int(limit)):
                break
        return out

    async def get_active_embedding_generation(self, index_name: str) -> dict | None:
        """Активное поколение индекса (реестр v18) или None.

        Fail-open: любая ошибка → None (честная деградация вызывающего)."""
        try:
            cursor = await self.db.execute(
                "SELECT generation_id, index_name, generation, fingerprint, "
                "provider, model, dims, preprocessing_version, "
                "endpoint_fingerprint, status, created_at, activated_at, "
                "superseded_at, pause_reason, next_allowed_at, attempts_total FROM mca_embedding_index_generations "
                "WHERE index_name = ? AND status = 'active'", (str(index_name),))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        except Exception:
            logger.debug("[database] active embedding generation read failed",
                         exc_info=True)
            return None

    async def get_latest_embedding_generation(self, index_name: str) -> dict | None:
        """Последнее (старшее `generation`) поколение индекса, любой статус.

        Нужно guard'у A06: `building`/`superseded`/`failed` — тоже карантин.
        Fail-open: ошибка → None."""
        try:
            cursor = await self.db.execute(
                "SELECT generation_id, index_name, generation, fingerprint, "
                "provider, model, dims, preprocessing_version, "
                "endpoint_fingerprint, status, created_at, activated_at, "
                "superseded_at, pause_reason, next_allowed_at, attempts_total FROM mca_embedding_index_generations "
                "WHERE index_name = ? ORDER BY generation DESC LIMIT 1",
                (str(index_name),))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        except Exception:
            logger.debug("[database] latest embedding generation read failed",
                         exc_info=True)
            return None

    async def get_generation_by_fingerprint(self, index_name: str,
                                            fingerprint: str) -> dict | None:
        """Поколение индекса по fingerprint (использует `idx_mca_eig_fingerprint`).

        Аудит/guard A06: позволяет узнать, есть ли уже поколение для данного
        fingerprint (и каким статусом). Fail-open: ошибка → None."""
        if not fingerprint:
            return None
        try:
            cursor = await self.db.execute(
                "SELECT generation_id, index_name, generation, fingerprint, "
                "provider, model, dims, preprocessing_version, "
                "endpoint_fingerprint, status, created_at, activated_at, "
                "superseded_at, pause_reason, next_allowed_at, attempts_total FROM mca_embedding_index_generations "
                "WHERE index_name = ? AND fingerprint = ? "
                "ORDER BY generation DESC LIMIT 1",
                (str(index_name), str(fingerprint)))
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        except Exception:
            logger.debug("[database] fingerprint generation read failed",
                         exc_info=True)
            return None

    async def ensure_embedding_generation(
            self, index_name: str, fingerprint: str, *, provider=None,
            model=None, dims=None, preprocessing_version=None,
            endpoint_fingerprint=None, activate: bool = True) -> dict | None:
        """Get-or-create поколения (идемпотентно, single-writer).

        MCA-07 B-MCA07-1 (A06): **никогда не затирает существующее активное
        поколение**. Если активное поколение есть и его fingerprint отличается —
        оно НЕ помечается `superseded` (оно описывает модель, построившую
        текущие векторы); возвращается как есть, а несовместимость гейтится
        вызывающим (`_index_generation_ok`).

        При отсутствии активного поколения новое регистрируется со статусом
        `active` (``activate=True``, если векторы построены текущим конфигом)
        или `building` (``activate=False`` — карантин до перестройки `mca-04b`).
        Повторный вызов с тем же fingerprint активного — no-op.
        Fail-open: ошибка → None."""
        if not fingerprint:
            return None
        async with self.serialized():
            existing = await self.get_active_embedding_generation(index_name)
            if existing is not None:
                # Никогда не подменяем активное поколение (A06).
                return existing
            now = int(time.time())
            status = "active" if activate else "building"
            activated = now if activate else None
            try:
                cursor = await self.db.execute(
                    "SELECT COALESCE(MAX(generation), 0) AS m FROM "
                    "mca_embedding_index_generations WHERE index_name = ?",
                    (str(index_name),))
                row = await cursor.fetchone()
                next_gen = int(row["m"] or 0) + 1
                await self.db.execute(
                    "INSERT INTO mca_embedding_index_generations "
                    "(index_name, generation, fingerprint, provider, model, "
                    "dims, preprocessing_version, endpoint_fingerprint, status, "
                    "created_at, activated_at, superseded_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                    (str(index_name), next_gen, str(fingerprint), provider,
                     model, dims, preprocessing_version, endpoint_fingerprint,
                     status, now, activated))
                await self.db.commit()
                logger.info("[database] embedding generation registered | "
                            "index=%s gen=%d status=%s", index_name, next_gen,
                            status)
            except Exception:
                await self.db.rollback()
                logger.warning("[database] ensure_embedding_generation failed",
                               exc_info=True)
                return None
            return await self.get_active_embedding_generation(index_name)

    async def initialize(self) -> None:
        """Open connection, create tables, enable WAL mode."""
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        # Epic 60 (63.1, T-459 тема 9): single-writer — synchronous=NORMAL
        # (WAL-журнал уже есть).
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.executescript(self._SCHEMA_SQL)
        await self.db.commit()
        if _schema_migrations_enabled():
            # MCA-14 (ADR-1027-1 D1): версионируемый идемпотентный runner +
            # backup/read-back обвязка (v13+). OFF → legacy hardcoded-путь
            # (точный паритет baseline 7165ff7).
            await self._run_migrations()
        else:
            logger.debug(
                "database: schema migrations runner OFF (legacy path)")
            await self._migrate_graphrag_v2()
            await self._migrate_direct_chat_v2()
            await self._migrate_epic60_v3()
            await self._migrate_video_origins_v4()
            await self._migrate_user_memory_v5()
            await self._migrate_chat_protected_facts_v6()
            await self._migrate_history_import_v7()
            await self._migrate_agi_memory_v8()
            await self._migrate_self_origin_v9()
            await self._migrate_edges_fact_id_v10()
            await self._migrate_import_key_chat_scope_v11()
            await self._migrate_graph_facts_metadata_v12()

        # Migration: add timestamp column if missing (Dead Page V2)
        try:
            await self.db.execute("ALTER TABLE dead_page_posts ADD COLUMN timestamp INTEGER")
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Epic 28 (R28-1): forward-marking columns for existing smart_messages tables
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN is_forward INTEGER NOT NULL DEFAULT 0"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN forward_source TEXT NOT NULL DEFAULT ''"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # GraphRAG (Epic 26): log the actual FK pragma state (Q4).
        # FK constraints are declared as documentation only — we never enable
        # the pragma because it would change semantics of the existing connection.
        try:
            cursor = await self.db.execute("PRAGMA foreign_keys")
            row = await cursor.fetchone()
            logger.debug("PRAGMA foreign_keys = %s (declared as docs, not enforced — Q4)",
                         row[0] if row is not None else None)
        except Exception:
            logger.debug("PRAGMA foreign_keys check failed", exc_info=True)

    async def initialize_existing(self) -> None:
        """Открыть УЖЕ существующую/мигрированную БД БЕЗ DDL и миграций.

        10.20 (CLI retention, ADR-1020-5 п.6, T-1910a): внешний CLI при ЖИВОМ
        боте (`manage.py retention --apply`) не должен конкурировать с
        основным процессом за DDL-лок — схема уже создана, `user_version`
        поднят. Здесь только соединение + WAL/busy_timeout (R13: не падать на
        «database is locked»). Свежая/пустая БД → ошибка уровня запроса
        (утилите нужна готовая схема) — вызывающий fail-safe.

        S10.20-13: мягкая валидация существования/схемы — неверный путь или
        пустой файл дают понятную ошибку вместо «deleted=0» по несуществующим
        таблицам (R17: без полного пути в тексте).
        """
        is_memory = str(self.db_path) in (":memory:", "")
        if not is_memory and not self.db_path.exists():
            raise FileNotFoundError(
                f"БД не найдена: {self.db_path.name} — retention работает "
                "только по существующей схеме (проверьте путь)")
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await self.db.execute("PRAGMA journal_mode=WAL")
        # Epic 60 (63.1): single-writer — synchronous=NORMAL (WAL-журнал есть).
        await self.db.execute("PRAGMA synchronous=NORMAL")
        # S10.20-13: пустая/чужая БД → понятная ошибка до любых запросов.
        try:
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            has_tables = await cursor.fetchone() is not None
        except Exception:
            has_tables = False
        if not has_tables:
            await self.db.close()
            self.db = None
            raise RuntimeError(
                "В БД нет таблиц — схема не найдена (это не рабочая база "
                "adminbot)")

    async def initialize_readonly(self) -> None:
        """Открыть существующую БД СТРОГО READ-ONLY (S10.21-6).

        Для `manage.py memory audit`: никакого DDL/миграций и PRAGMA,
        меняющих состояние (в т.ч. `journal_mode`). SQLite URI `mode=ro`
        блокирует любую запись. Отсутствие файла/таблиц — явная ошибка (файл
        НЕ создаётся). Fail-closed: вызывающий сам решает, что показать."""
        raw = str(self.db_path)
        is_memory = raw in (":memory:", "")
        if not is_memory and not self.db_path.exists():
            raise FileNotFoundError(
                f"readonly: БД не найдена: {self.db_path.name}")
        if is_memory:
            raise FileNotFoundError(
                "readonly: требуется существующий файл БД")
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        self.db = await aiosqlite.connect(uri, uri=True)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        try:
            cursor = await self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            has_tables = await cursor.fetchone() is not None
        except Exception:
            has_tables = False
        if not has_tables:
            await self.db.close()
            self.db = None
            raise RuntimeError(
                "В БД нет таблиц — схема не найдена (это не рабочая база "
                "adminbot)")

    async def _migrate_graphrag_v2(self) -> None:
        """Идемпотентная миграция Epic 46 (55.3): origin/expires_at в nodes/edges,
        CHECK entity_type + 'fact' (пересоздание nodes с сохранением id),
        PRAGMA user_version = 1. Повторный запуск — no-op."""
        for table in ("nodes", "edges"):
            for sql in (
                f"ALTER TABLE {table} ADD COLUMN origin TEXT NOT NULL DEFAULT 'chat_history'",
                f"ALTER TABLE {table} ADD COLUMN expires_at INTEGER",
            ):
                try:
                    await self.db.execute(sql)
                    await self.db.commit()
                except aiosqlite.OperationalError:
                    pass                        # колонка уже есть
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "'fact'" not in row["sql"]:
            # SQLite не умеет ALTER CHECK — пересоздание с сохранением id (55.1 #4)
            await self.db.executescript(
                "ALTER TABLE nodes RENAME TO nodes_old; "
                "CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "chat_id INTEGER NOT NULL, entity_name TEXT NOT NULL, "
                "entity_type TEXT NOT NULL CHECK (entity_type IN "
                "('user','topic','event','fact')), "
                "origin TEXT NOT NULL DEFAULT 'chat_history', expires_at INTEGER, "
                "UNIQUE (chat_id, entity_name)); "
                "INSERT INTO nodes (id, chat_id, entity_name, entity_type, origin, expires_at) "
                "SELECT id, chat_id, entity_name, entity_type, 'chat_history', NULL "
                "FROM nodes_old; "
                "DROP TABLE nodes_old; "
                "CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);"
            )
            await self.db.commit()
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        await self.db.commit()

    async def _migrate_direct_chat_v2(self) -> None:
        """Идемпотентная миграция Epic 50 (58.7, D201): (а) graph_facts —
        CHECK-расширение 'bot_direct_reply' + target_user через пересоздание
        (SQLite не умеет ALTER CHECK; id сохраняются → FTS/vec валидны БЕЗ
        пересоздания); (б) smart_messages.tg_message_id + индекс; (в)
        PRAGMA user_version = 2. Повторный запуск — no-op (guard + PRAGMA).
        Прецедент _migrate_graphrag_v2 (55.3)."""
        # (б) tg_message_id — ALTER для старых БД (новая схема уже имеет колонку)
        try:
            await self.db.execute("ALTER TABLE smart_messages ADD COLUMN tg_message_id INTEGER")
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass                        # колонка уже есть
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_smart_messages_tg ON smart_messages(chat_id, tg_message_id)")
        await self.db.commit()
        # (а) graph_facts: CHECK-расширение через пересоздание
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "bot_direct_reply" not in row["sql"]:
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, created_at, target_user) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, NULL FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user ON graph_facts(chat_id, target_user);"
            )
            await self.db.commit()
        # (в)
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION_DIRECT_CHAT}")
        await self.db.commit()

    async def _migrate_epic60_v3(self) -> None:
        """Идемпотентная миграция Epic 60 (63.3, D245): user_version 2→3.
        ТОЛЬКО CREATE/ALTER (никаких пересозданий с потерей данных; guard по
        CREATE IF NOT EXISTS + try/except OperationalError на ALTER):
        1. throttle_state (63.1) + индекс;
        2. bot_replies (63.1 — персистентный _bot_replies, TTL+LRU);
        3. user_prefs (65.5: tone-пресет; стачка живёт в throttle_state
           scope='direct_silence' — 65.3);
        4. embedding_cache (64.4);
        5. chat_running_summary (64.6);
        6. graph_fact_compressions (64.2 — лог сжатий);
        7. protected_facts (65.10);
        8. graph_facts: weight/status/last_confirmed_at (backfill=created_at,
           66.3)/supersedes — НЕ пересоздавать CHECK (origins не меняются);
        9. edges: created_at (backfill из strftime('%s', last_updated) — 66.3);
        10. PRAGMA user_version = 3.
        Повторный запуск — no-op. Прецеденты _migrate_graphrag_v2 /
        _migrate_direct_chat_v2."""
        await self.db.executescript(
            "CREATE TABLE IF NOT EXISTS throttle_state ("
            "scope TEXT NOT NULL, chat_id INTEGER NOT NULL, "
            "user_id INTEGER NOT NULL, burst_left INTEGER, "
            "last_ts REAL NOT NULL, "
            "PRIMARY KEY (scope, chat_id, user_id)); "
            "CREATE INDEX IF NOT EXISTS idx_throttle_state_ts "
            "ON throttle_state(last_ts); "
            "CREATE TABLE IF NOT EXISTS bot_replies ("
            "chat_id INTEGER, tg_message_id INTEGER, text TEXT NOT NULL, "
            "last_used_at REAL NOT NULL, "
            "PRIMARY KEY (chat_id, tg_message_id)); "
            "CREATE TABLE IF NOT EXISTS user_prefs ("
            "chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
            "tone_preset TEXT, PRIMARY KEY (chat_id, user_id)); "
            "CREATE TABLE IF NOT EXISTS embedding_cache ("
            "text_hash TEXT PRIMARY KEY, text TEXT NOT NULL, "
            "vector TEXT NOT NULL, dim INTEGER NOT NULL, "
            "created_at REAL NOT NULL, last_used_at REAL NOT NULL); "
            "CREATE INDEX IF NOT EXISTS idx_embedding_cache_lru "
            "ON embedding_cache(last_used_at); "
            "CREATE TABLE IF NOT EXISTS chat_running_summary ("
            "chat_id INTEGER PRIMARY KEY, summary TEXT NOT NULL, "
            "window_start_ts INTEGER NOT NULL, window_end_ts INTEGER NOT NULL, "
            "raw_count INTEGER NOT NULL, created_at REAL NOT NULL, "
            "expires_at REAL NOT NULL); "
            "CREATE TABLE IF NOT EXISTS graph_fact_compressions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
            "fact_id INTEGER, fact_before TEXT NOT NULL, fact_after TEXT, "
            "reason TEXT NOT NULL, created_at REAL NOT NULL); "
            "CREATE TABLE IF NOT EXISTS protected_facts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
            "user_name TEXT NOT NULL, fact TEXT NOT NULL, "
            "created_at REAL NOT NULL, UNIQUE (chat_id, user_name, fact));"
        )
        await self.db.commit()
        for sql in (
            "ALTER TABLE graph_facts ADD COLUMN weight REAL NOT NULL DEFAULT 0.5",
            "ALTER TABLE graph_facts ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'",
            "ALTER TABLE graph_facts ADD COLUMN last_confirmed_at INTEGER",
            "ALTER TABLE graph_facts ADD COLUMN supersedes INTEGER",
            "ALTER TABLE edges ADD COLUMN created_at INTEGER",
        ):
            try:
                await self.db.execute(sql)
                await self.db.commit()
            except aiosqlite.OperationalError:
                pass                        # колонка уже есть (повторный запуск)
        # backfill: last_confirmed_at = created_at (66.3); edges.created_at —
        # из существующей колонки last_updated ('YYYY-MM-DD HH:MM:SS' UTC).
        await self.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = created_at "
            "WHERE last_confirmed_at IS NULL")
        await self.db.execute(
            "UPDATE edges SET created_at = CAST(strftime('%s', last_updated) AS INTEGER) "
            "WHERE created_at IS NULL")
        await self.db.commit()
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION_EPIC60}")
        await self.db.commit()

    async def _migrate_video_origins_v4(self) -> None:
        """Раунд 3 (3.6/B7, T-693): CHECK graph_facts.origin + 'voice_transcript'/
        'video_transcript' через пересоздание с сохранением ВСЕХ колонок
        (id, chat_id, fact, origin, expires_at, created_at, target_user,
        weight, status, last_confirmed_at, supersedes — статусы/веса Epic 60
        добавлялись отдельными ALTER, в rebuild включаем) + INSERT…SELECT +
        DROP old + индексы; PRAGMA user_version = 4. Повторный запуск — no-op
        (guard '"video_transcript" not in sql' + PRAGMA). FTS5 graph_facts_fts
        НЕ пересоздаётся (content-таблица пересоздана с теми же rowid —
        прецедент D201; content='graph_facts' резолвится динамически).
        Заметка (3.6): PostgreSQL-схемы graph_facts СЕЙЧАС НЕТ (pg_db.py —
        только bot_settings/bot_roles/bot_admins/uptime_events); эпик 86
        «GraphRAG→PG» — будущий, при его реализации origin-список
        синхронизировать."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "video_transcript" not in row["sql"]:
            logger.info(
                "[database] migration v4: graph_facts origins rebuild "
                "(voice/video_transcript)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes "
                "FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user);"
            )
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_VIDEO_ORIGINS}")
        await self.db.commit()

    async def _migrate_user_memory_v5(self) -> None:
        """Раунд 4 (T-713, spec 3.4.3): CHECK graph_facts.origin + 'user_memory'
        через пересоздание с сохранением ВСЕХ колонок (точная копия паттерна
        _migrate_video_origins_v4): guard по sqlite_master ('user_memory' ещё
        не в CHECK) → ALTER RENAME + CREATE (origin-список из
        _GRAPH_FACT_ORIGINS_SQL — единое место) + INSERT…SELECT + DROP old +
        индексы; PRAGMA user_version = 5. Повторный запуск — no-op. FTS5
        graph_facts_fts НЕ пересоздаётся (rowid сохранены — прецедент D201).
        Новых таблиц нет. PostgreSQL-схемы graph_facts по-прежнему НЕТ
        (pg_db.py — только bot_settings/роли/админы/uptime_events); при
        реализации эпика 86 origin-список синхронизировать."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "user_memory" not in row["sql"]:
            logger.info(
                "[database] migration v5: graph_facts origins rebuild "
                "(user_memory)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes "
                "FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user);"
            )
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_USER_MEMORY}")
        await self.db.commit()

    async def _migrate_chat_protected_facts_v6(self) -> None:
        """Раунд 5 (T-731, spec 3.2.1, FR-C1): protected_facts.user_name →
        nullable (чат-уровневые факты — «лор чата», user_name NULL, видны всем
        юзерам чата) через пересоздание с сохранением id (прецедент D201 /
        _migrate_user_memory_v5): guard по sqlite_master ('user_name TEXT NOT
        NULL' ещё в CREATE) → ALTER RENAME + CREATE (user_name TEXT без NOT
        NULL; UNIQUE (chat_id, user_name, fact) сохраняется) + частичный
        уникальный индекс idx_protected_facts_chat_level (чат-уровневые
        уникальны по (chat_id, fact): в SQLite NULL != NULL, обычный UNIQUE
        их не защищает от дублей) + INSERT…SELECT + DROP old; PRAGMA
        user_version = 6. Повторный запуск — no-op (guard false → только
        PRAGMA). Старые данные — только user_name NOT NULL → конфликтов при
        копировании нет; id сохраняются (FTS/ссылки не затронуты).
        CREATE в _migrate_epic60_v3 НЕ меняется (свежая БД проходит v3→v6;
        rebuild пустой таблицы — дешёвый)."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='protected_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "user_name TEXT NOT NULL" in row["sql"]:
            logger.info(
                "[database] migration v6: protected_facts rebuild "
                "(chat-level user_name NULL)")
            await self.db.executescript(
                "ALTER TABLE protected_facts RENAME TO protected_facts_old; "
                "CREATE TABLE protected_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "user_name TEXT, fact TEXT NOT NULL, created_at REAL NOT NULL, "
                "UNIQUE (chat_id, user_name, fact)); "
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_protected_facts_chat_level "
                "ON protected_facts(chat_id, fact) WHERE user_name IS NULL; "
                "INSERT INTO protected_facts (id, chat_id, user_name, fact, created_at) "
                "SELECT id, chat_id, user_name, fact, created_at "
                "FROM protected_facts_old; "
                "DROP TABLE protected_facts_old;"
            )
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_CHAT_PROTECTED_FACTS}")
        await self.db.commit()

    async def _migrate_history_import_v7(self) -> None:
        """Фаза 2 (T-758, spec 3.4/FR-6): user_version 6→7. Три независимые
        части, каждая идемпотентная (повторный запуск — no-op, только PRAGMA):

        (а) graph_facts rebuild по паттерну _migrate_user_memory_v5 (D201):
        + колонка message_timestamp INTEGER (nullable), CHECK origin +=
        'history_import' (список из _GRAPH_FACT_ORIGINS_SQL — единое место),
        все 11 существующих колонок сохраняются, INSERT…SELECT копирует
        message_timestamp = NULL → backfill = created_at (рендер COALESCE не
        меняет вывода для существующих фактов); индексы (chat_origin,
        target_user) воссоздаются; + частичный UNIQUE-индекс
        idx_graph_facts_history_import (chat_id, fact, message_timestamp) WHERE
        origin='history_import' AND message_timestamp IS NOT NULL —
        идемпотентность Graph-этапа/переноса дельты. FTS5 graph_facts_fts НЕ
        пересоздаётся (rowid сохранены — прецедент D201/v4/v5). GUARD по
        колонке message_timestamp (в sqlite_master CREATE-тексте): свежая БД
        после v5-rebuild уже содержит 'history_import' в CHECK (константа
        пополнена), но НЕ колонку — guard по origin не сработал бы.

        (б) smart_messages: import_key TEXT + history_processed INTEGER NOT
        NULL DEFAULT 0 — только ALTER-веткой (CREATE TABLE не трогаем;
        прецедент tg_message_id) + частичные индексы:
        idx_smart_messages_import_key (UNIQUE, WHERE import_key IS NOT NULL —
        идемпотентность FTS-импорта) и idx_smart_messages_history_pending
        (chat_id, history_processed, WHERE history_processed = 0 — выборка
        пачек Graph-воркера). Внешняя FTS5 smart_messages_fts не затрагивается
        (rebuild не происходит — rowid валидны).

        (в) PRAGMA user_version = 7.
        """
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "message_timestamp" not in row["sql"]:
            logger.info(
                "[database] migration v7: graph_facts rebuild "
                "(message_timestamp + history_import origin)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER, "
                "message_timestamp INTEGER); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes, message_timestamp) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes, NULL "
                "FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user);"
            )
            # backfill: существующие факты рендерятся как раньше (COALESCE)
            await self.db.execute(
                "UPDATE graph_facts SET message_timestamp = created_at "
                "WHERE message_timestamp IS NULL")
            await self.db.commit()
        # частичный UNIQUE-индекс идемпотентности (после backfill — guard)
        await self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_facts_history_import "
            "ON graph_facts(chat_id, fact, message_timestamp) "
            "WHERE origin='history_import' AND message_timestamp IS NOT NULL")
        await self.db.commit()
        # (б) smart_messages: ALTER-ветка (как tg_message_id; fresh CREATE не трогаем)
        for alter_sql in (
            "ALTER TABLE smart_messages ADD COLUMN import_key TEXT",
            "ALTER TABLE smart_messages ADD COLUMN history_processed "
            "INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await self.db.execute(alter_sql)
                await self.db.commit()
            except aiosqlite.OperationalError:
                pass                        # колонка уже есть (повторный запуск)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_smart_messages_history_pending "
            "ON smart_messages(chat_id, history_processed) "
            "WHERE history_processed = 0")
        await self.db.commit()
        # F7 (v11, ADR-1019-6 D1b): глобальный UNIQUE-индекс создаётся ТОЛЬКО
        # до v11. После v11 живёт chat-scoped `idx_smart_messages_chat_import_key`
        # — иначе v7 на каждом старте пересоздавал бы глобальный UNIQUE и снова
        # подавлял импорт одного контента во второй чат (cross-chat дефект).
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_smart_messages_chat_import_key'")
        if await cursor.fetchone() is None:
            await self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_messages_import_key "
                "ON smart_messages(import_key) WHERE import_key IS NOT NULL")
        await self.db.commit()
        # (в)
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_HISTORY_IMPORT}")
        await self.db.commit()

    async def _migrate_agi_memory_v8(self) -> None:
        """Раунд 9 (T-822, spec §3.3.1/FR-8, AC-3): user_version 7→8.

        rebuild graph_facts по образцу _migrate_history_import_v7 (guard по
        sqlite_master): 12 существующих колонок сохраняются + новые
        `importance INTEGER NOT NULL DEFAULT 0`, `source_ids TEXT`,
        `kind TEXT NOT NULL DEFAULT 'fact' CHECK(kind IN ('fact','belief'))`,
        `belief_meta TEXT`; CHECK origin расширяется 'derived_belief'
        (список _GRAPH_FACT_ORIGINS_SQL — единое место). id сохраняются —
        FTS5 graph_facts_fts НЕ пересоздаётся (rowid валидны). После
        INSERT…SELECT: backfill importance правилом §3.3.2 БЕЗ LLM (два
        UPDATE: (а) база по origin CASE, (б) +1 при length(fact)>=200 c
        MIN(10,…) — clamp); DROP legacy; индексы v7 повторяются + новые
        idx_graph_facts_chat_kind (chat_id, kind) и частичный
        idx_graph_facts_beliefs (chat_id) WHERE kind='belief'
        (сон/ностальгия/API). PRAGMA user_version = 8. Повторный запуск —
        no-op (guard: 'importance' уже в CREATE-тексте)."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "importance" not in row["sql"]:
            logger.info(
                "[database] migration v8: graph_facts rebuild "
                "(importance/source_ids/kind/belief_meta + derived_belief)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_v8_legacy; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER, "
                "message_timestamp INTEGER, "
                "importance INTEGER NOT NULL DEFAULT 0, "
                "source_ids TEXT, "
                "kind TEXT NOT NULL DEFAULT 'fact' "
                "CHECK (kind IN ('fact','belief')), "
                "belief_meta TEXT); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes, message_timestamp) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes, "
                "message_timestamp FROM graph_facts_v8_legacy; "
                "DROP TABLE graph_facts_v8_legacy; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user); "
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_facts_history_import "
                "ON graph_facts(chat_id, fact, message_timestamp) "
                "WHERE origin='history_import' AND message_timestamp IS NOT NULL; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_kind "
                "ON graph_facts(chat_id, kind); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_beliefs "
                "ON graph_facts(chat_id) WHERE kind='belief';"
            )
            # (а) база по origin (§3.3.2); (б) +1 длина ≥200 (clamp MIN)
            await self.db.execute(
                "UPDATE graph_facts SET importance = CASE origin "
                "WHEN 'user_memory' THEN 6 WHEN 'chat_history' THEN 4 "
                "WHEN 'history_import' THEN 2 WHEN 'bot_direct_reply' THEN 3 "
                "WHEN 'voice_transcript' THEN 2 WHEN 'video_transcript' THEN 2 "
                "WHEN 'search_fact' THEN 3 WHEN 'youtube_content' THEN 3 "
                "WHEN 'web_content' THEN 3 WHEN 'bot_self_reply' THEN 2 END")
            await self.db.execute(
                "UPDATE graph_facts SET importance = MIN(10, importance + 1) "
                "WHERE length(fact) >= 200")
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_AGI_MEMORY_V8}")
        await self.db.commit()

    async def _migrate_self_origin_v9(self) -> None:
        """Раунд 10.14 (F1 anti-echo-self-reply, ADR-1014-2 D2 / spec §2.1):
        user_version 8→9. CHECK graph_facts.origin расширяется ЧЕСТНЫМ
        11-м origin 'bot_self_reply' через rebuild (SQLite не умеет ALTER
        CHECK) — образец _migrate_agi_memory_v8 / _migrate_history_import_v7.

        - GUARD (идемпотентность): rebuild ТОЛЬКО если 'bot_self_reply' нет в
          CREATE-тексте graph_facts (sqlite_master). Повторный запуск — no-op.
          ВАЖНО: ``PRAGMA user_version = 9`` ставится ВСЕГДА (вне guard):
          свежая БД проходит через v5/v7/v8-rebuild, которые интерполируют
          уже обновлённый _GRAPH_FACT_ORIGINS_SQL (origin присутствует) —
          rebuild корректно пропускается, но версия всё равно фиксируется.
        - REBUILD копирует ВСЕ 16 колонок v8 (id, chat_id, fact, origin,
          expires_at, created_at, target_user, weight, status,
          last_confirmed_at, supersedes, message_timestamp, importance,
          source_ids, kind, belief_meta) 1:1 — id сохраняются, поэтому FTS5
          graph_facts_fts (content='graph_facts') и vec0 graph_facts_vec
          (rowid=fact_id) остаются валидными БЕЗ пересоздания (прецедент
          D201). Данные НЕ теряются.
        - Индексы v8 пересоздаются (5): idx_graph_facts_chat_origin,
          idx_graph_facts_target_user, idx_graph_facts_history_import
          (partial UNIQUE), idx_graph_facts_chat_kind, idx_graph_facts_beliefs
          (partial).
        - Обратимость (откат, документирован в ADR §D2): перед git revert —
          ``UPDATE graph_facts SET origin='bot_direct_reply'
          WHERE origin='bot_self_reply'`` (иначе старый CHECK отклонит строки);
          сама миграция повторно не срабатывает (guard по 'bot_self_reply')."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "bot_self_reply" not in row["sql"]:
            logger.info(
                "[database] migration v9: graph_facts origins rebuild "
                "(bot_self_reply)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_v9_legacy; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER, "
                "message_timestamp INTEGER, "
                "importance INTEGER NOT NULL DEFAULT 0, "
                "source_ids TEXT, "
                "kind TEXT NOT NULL DEFAULT 'fact' "
                "CHECK (kind IN ('fact','belief')), "
                "belief_meta TEXT); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes, message_timestamp, importance, source_ids, kind, "
                "belief_meta) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes, "
                "message_timestamp, importance, source_ids, kind, belief_meta "
                "FROM graph_facts_v9_legacy; "
                "DROP TABLE graph_facts_v9_legacy; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user); "
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_facts_history_import "
                "ON graph_facts(chat_id, fact, message_timestamp) "
                "WHERE origin='history_import' AND message_timestamp IS NOT NULL; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_kind "
                "ON graph_facts(chat_id, kind); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_beliefs "
                "ON graph_facts(chat_id) WHERE kind='belief';"
            )
            await self.db.commit()
        # user_version фиксируется БЕЗУСЛОВНО (вне guard) — см. docstring.
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_AGI_MEMORY}")
        await self.db.commit()

    async def _migrate_edges_fact_id_v10(self) -> None:
        """Раунд 10.18 (F3 graph-density-scoring-stoplist, ADR-1018-3 D1):
        user_version 9→10. `ALTER TABLE edges ADD COLUMN fact_id INTEGER`
        (nullable, БЕЗ rebuild) + индекс `idx_edges_fact_id` — provenance
        ребра → `graph_facts.id` для скоринга `Σ importance` (T-1728).

        - ADD COLUMN без rebuild: FTS5 `graph_facts_fts` (content='graph_facts')
          и vec `graph_facts_vec` (rowid=fact_id) НЕ затрагиваются, id строк не
          меняются, данные не теряются (миграция касается ТОЛЬКО `edges`).
        - GUARD (идемпотентность): колонка добавляется ТОЛЬКО если 'fact_id'
          нет в `PRAGMA table_info(edges)`; повторный запуск — no-op.
        - ``PRAGMA user_version = 10`` ставится ВСЕГДА, вне guard (свежая БД
          уже имеет fact_id из `_SCHEMA_SQL`, но версию всё равно фиксируем —
          прецедент `_migrate_self_origin_v9`).
        - Legacy-рёбра: `fact_id` остаётся NULL осознанно — backfill по
          triple-строке недетерминирован (ADR-1018-3 A7); формула скоринга для
          NULL деградирует к `COALESCE(f.importance, e.weight)`.
        - Обратный путь отката: колонка аддитивна и безвредна → ``git revert``
          безопасен. Полный откат схемы:
          ``DROP INDEX IF EXISTS idx_edges_fact_id`` +
          ``ALTER TABLE edges DROP COLUMN fact_id`` (SQLite ≥3.35) +
          ``PRAGMA user_version = 9`` — данные не теряются."""
        cursor = await self.db.execute("PRAGMA table_info(edges)")
        cols = {row["name"] for row in await cursor.fetchall()}
        if "fact_id" not in cols:
            logger.info(
                "[database] migration v10: edges.fact_id (provenance факта)")
            await self.db.execute(
                "ALTER TABLE edges ADD COLUMN fact_id INTEGER")
        # Индекс создаётся ВСЕГДА (вне guard): на legacy-БД колонки ещё не
        # было при отработке _SCHEMA_SQL, поэтому индекс живёт здесь.
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_fact_id ON edges(fact_id)")
        await self.db.commit()
        # user_version фиксируется БЕЗУСЛОВНО (вне guard) — см. docstring.
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_EDGES_FACT_ID}")
        await self.db.commit()

    async def _migrate_import_key_chat_scope_v11(self) -> None:
        """F7 (10.19, ADR-1019-6 D1b/D7; UPD3 п.2): user_version 10→11.

        Изоляция импортированной истории по чату (латентный cross-chat дефект):
        `import_key = sha256(ts|user_id|text)` НЕ включает `chat_id`, а индекс
        `idx_smart_messages_import_key` был ГЛОБАЛЬНЫМ UNIQUE → импорт одного
        и того же контента в два чата молча подавлял строку второго
        (`INSERT OR IGNORE`). `import_checkpoints` ключевался только `path` →
        второй чат видел чужой «done».

        (а) `smart_messages`: DROP глобального UNIQUE +
        CREATE `idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key)
        WHERE import_key IS NOT NULL`. Глобальный UNIQUE СИЛЬНЕЕ пер-чат, поэтому
        на существующих 1.27M строк индекс создаётся без конфликтов. Формула
        `import_key` НЕ меняется (идемпотентность сохранена).
        (б) `import_checkpoints`: rebuild — ключ `(path, chat_id)`. Legacy-строки
        (без чата) получают `chat_id=0` (unscoped; повторный импорт в реальный
        чат не считается «завершённым»). Таблица создаётся лениво
        `tools.history_import.checkpoints.ensure_table` — если её ещё нет, шаг
        no-op (новая схема будет создана сразу с `chat_id`).
        (в) ``PRAGMA user_version = 11`` ставится ВСЕГДА, вне guard (прецедент
        v9/v10 — свежая БД тоже фиксирует версию).

        FTS5 `smart_messages_fts` (content='smart_messages', rowid=id) и vec-слои
        НЕ затрагиваются (таблица-источник не пересоздаётся, id/rowid валидны).
        Идемпотентно (guard по `sqlite_master`/`PRAGMA table_info`).
        Обратный путь отката: `DROP INDEX IF EXISTS
        idx_smart_messages_chat_import_key` + `CREATE UNIQUE INDEX
        idx_smart_messages_import_key ON smart_messages(import_key) WHERE
        import_key IS NOT NULL`; у `import_checkpoints` — `ALTER TABLE … RENAME`
        к старой DDL (path PK); `PRAGMA user_version = 10` — данные не теряются.
        """
        # (а) chat-scoped UNIQUE вместо глобального.
        await self.db.execute("DROP INDEX IF EXISTS idx_smart_messages_import_key")
        # MCA-14 (v13 runner, REUSE): на древних/частичных фикстурах колонки
        # `import_key` может не быть — v7 rebuild обычно её создаёт, но guard
        # по `PRAGMA table_info` делает шаг безопасным при любом составе
        # (idempotent self-guard, ADR-1027-1 D1). Нет колонки → нечего
        # индексировать, шаг фиксирует только user_version.
        cursor = await self.db.execute("PRAGMA table_info(smart_messages)")
        _sm_cols = {row["name"] for row in await cursor.fetchall()}
        if "import_key" not in _sm_cols:
            logger.info(
                "[database] migration v11: smart_messages.import_key отсутствует "
                "— индекс/rebuild пропущены (guard)")
            await self.db.execute(
                f"PRAGMA user_version = {_SCHEMA_VERSION_IMPORT_KEY_CHAT_SCOPE}")
            await self.db.commit()
            return
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_smart_messages_chat_import_key'")
        if await cursor.fetchone() is None:
            logger.info(
                "[database] migration v11: import_key chat-scoped UNIQUE "
                "(cross-chat isolation)")
            await self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_smart_messages_chat_import_key "
                "ON smart_messages(chat_id, import_key) "
                "WHERE import_key IS NOT NULL")
        await self.db.commit()
        # (б) import_checkpoints: ключ (path, chat_id).
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='import_checkpoints'")
        if await cursor.fetchone() is not None:
            cursor = await self.db.execute("PRAGMA table_info(import_checkpoints)")
            cols = {row["name"] for row in await cursor.fetchall()}
            if "chat_id" not in cols:
                logger.info(
                    "[database] migration v11: import_checkpoints chat-scoped "
                    "(path, chat_id)")
                # D-Low (ревью Батча E): rebuild в ОДНОЙ транзакции
                # (DROP old-хвоста → RENAME → CREATE → INSERT → DROP old),
                # иначе между шагами остаётся промежуточное состояние и
                # повторный прогон падает на «import_checkpoints_old exists».
                await self.db.execute("BEGIN")
                try:
                    await self.db.execute(
                        "DROP TABLE IF EXISTS import_checkpoints_old")
                    await self.db.execute(
                        "ALTER TABLE import_checkpoints "
                        "RENAME TO import_checkpoints_old")
                    await self.db.execute(
                        "CREATE TABLE import_checkpoints ("
                        "path TEXT NOT NULL, "
                        "chat_id INTEGER NOT NULL DEFAULT 0, "
                        "processed INTEGER NOT NULL DEFAULT 0, total INTEGER, "
                        "done INTEGER NOT NULL DEFAULT 0, updated_at INTEGER, "
                        "PRIMARY KEY (path, chat_id))")
                    await self.db.execute(
                        "INSERT INTO import_checkpoints "
                        "(path, chat_id, processed, total, done, updated_at) "
                        "SELECT path, 0, processed, total, done, updated_at "
                        "FROM import_checkpoints_old")
                    await self.db.execute(
                        "DROP TABLE IF EXISTS import_checkpoints_old")
                    await self.db.commit()
                except Exception:
                    await self.db.rollback()
                    raise
        # (в)
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_IMPORT_KEY_CHAT_SCOPE}")
        await self.db.commit()

    async def _migrate_graph_facts_metadata_v12(self) -> None:
        """Раунд 10.20 (БЛОК 7.3b, ADR-1020-1 ред. 3 / ADR-1020-7 §3, T-1924):
        user_version 11→12. `graph_facts` += `tg_message_id INTEGER` (nullable)
        и `forward_from TEXT NOT NULL DEFAULT ''` — provenance факта для
        ID-политики `tg:`/`fact:` и сегмента «Переслано:» (Tier-A строк фактов).

        - GUARD (идемпотентность): колонки добавляются ТОЛЬКО если их нет в
          `PRAGMA table_info(graph_facts)`; повторный запуск — no-op. На свежей
          БД `_SCHEMA_SQL` уже содержит колонки → guard пропускает ALTER.
        - ADD COLUMN без rebuild: FTS5 `graph_facts_fts` (content='graph_facts',
          rowid=id) и vec0 `graph_facts_vec` (rowid=fact_id) НЕ затрагиваются,
          id/rowid строк не меняются, данные не теряются (прецедент D201/v10).
        - Новых индексов НЕТ (документировано: запросов по `tg_message_id` нет;
          `idx_graph_facts_chat_origin` сохраняется).
        - Legacy-строки: `tg_message_id` = NULL (честное опускание ID, R16);
          `forward_from` = '' (= не forward).
        - ``PRAGMA user_version = 12`` ставится ВСЕГДА, вне guard (прецедент
          v9/v10/v11 — свежая БД тоже фиксирует версию).
        - **PG — no-op:** таблицы `graph_facts` в PostgreSQL нет
          (`pg_db.py` — только settings/роли/админы/uptime_events);
          phantom-таблицу НЕ создаём (вне скоупа).
        - Обратный путь отката: колонки аддитивны и безвредны → `git revert`
          безопасен; полный откат — `ALTER TABLE graph_facts DROP COLUMN
          tg_message_id` + `DROP COLUMN forward_from` (SQLite ≥3.35) +
          `PRAGMA user_version = 11` — данные не теряются."""
        cursor = await self.db.execute("PRAGMA table_info(graph_facts)")
        cols = {row["name"] for row in await cursor.fetchall()}
        additions = []
        if "tg_message_id" not in cols:
            additions.append(("tg_message_id",
                              "ALTER TABLE graph_facts ADD COLUMN "
                              "tg_message_id INTEGER"))
        if "forward_from" not in cols:
            additions.append(("forward_from",
                              "ALTER TABLE graph_facts ADD COLUMN "
                              "forward_from TEXT NOT NULL DEFAULT ''"))
        for name, sql in additions:
            logger.info(
                "[database] migration v12: graph_facts.%s (provenance факта)",
                name)
            await self.db.execute(sql)
        if additions:
            await self.db.commit()
        # user_version фиксируется БЕЗУСЛОВНО (вне guard) — см. docstring.
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_GRAPH_FACTS_V12}")
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()
    # ── Slava Presence ──────────────────────────────────
    
    @_serialized_write
    async def set_presence(self, user_id: int, chat_id: int, present: bool) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO user_presence (user_id, chat_id, is_present) VALUES (?, ?, ?)",
            (user_id, chat_id, 1 if present else 0)
        )
        await self.db.commit()
    
    async def is_present(self, user_id: int, chat_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT is_present FROM user_presence WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        row = await cursor.fetchone()
        return bool(row and row["is_present"])
    
    async def get_present_chats(self, user_id: int) -> list[int]:
        cursor = await self.db.execute(
            "SELECT chat_id FROM user_presence WHERE user_id = ? AND is_present = 1",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]
    
    # ── Message Counters ────────────────────────────────
    
    @_serialized_write
    async def increment_and_get_count(self, chat_id: int, user_id: int) -> int:
        """Atomically increment counter and return new value."""
        # B-MCA01-1: single-writer уже удерживается декоратором `_serialized_write`
        # (через `_single_writer`); повторный `async with self._lock` был бы
        # самодедлоком (Lock нереентерабельный).
        await self.db.execute(
            "INSERT INTO message_counters (chat_id, user_id, count) "
            "VALUES (?, ?, 1) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
            (chat_id, user_id)
        )
        await self.db.commit()
        cursor = await self.db.execute(
            "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0
    
    async def get_count(self, chat_id: int, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0
    
    # ── Dead Page Posts ─────────────────────────────────

    async def was_dead_page_recently(self, chat_id: int, cooldown_seconds: int) -> bool:
        """Check if a dead page was posted in this chat within the last N seconds."""
        cutoff = int(time.time()) - cooldown_seconds
        cursor = await self.db.execute(
            "SELECT 1 FROM dead_page_posts WHERE chat_id = ? AND slot = 'repost' AND timestamp > ?",
            (chat_id, cutoff)
        )
        row = await cursor.fetchone()
        return row is not None

    @_serialized_write
    async def record_dead_page_post(self, chat_id: int, slot: str) -> None:
        """Record that a dead page post was made."""
        today = datetime.date.today().isoformat()
        now_ts = int(time.time())
        await self.db.execute(
            "INSERT INTO dead_page_posts (chat_id, slot, date, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, slot, today, now_ts)
        )
        await self.db.commit()

    # ── Леха activity (код-ключи alan_last_msg:* не переименовываются) ──

    async def get_alan_last_message_ts(self, chat_id: int) -> float | None:
        """Get the timestamp of Леха's last message in a chat."""
        key = f"alan_last_msg:{chat_id}"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            try:
                return float(row["value"])
            except (ValueError, TypeError):
                return None
        return None

    @_serialized_write
    async def set_alan_last_message_ts(self, chat_id: int, timestamp: float) -> None:
        """Record the timestamp of Леха's last message in a chat."""
        key = f"alan_last_msg:{chat_id}"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(timestamp))
        )
        await self.db.commit()

    # ── Channel State ───────────────────────────────────

    async def get_last_known_message_id(self, channel_id: int = 0) -> int | None:
        """Get the last known message_id in the relay channel."""
        key = f"last_msg_id:{channel_id}" if channel_id else "last_known_message_id"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            return int(row["value"])
        return None

    @_serialized_write
    async def update_last_known_message_id(self, msg_id: int, channel_id: int = 0) -> None:
        """Update the last known message_id in the relay channel."""
        key = f"last_msg_id:{channel_id}" if channel_id else "last_known_message_id"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(msg_id))
        )
        await self.db.commit()

    # ── Dead Page Anti-Repeat (Epic 22 / D54) ─────────────

    async def get_dead_page_last_sent(self, chat_id: int) -> int | None:
        """Primary relay-channel msg_id forwarded into this chat last time (anti-repeat).

        Uses channel_state key `dead_page_last_sent:{chat_id}`. Returns None when
        the key is missing or holds a broken (non-int) value.
        """
        key = f"dead_page_last_sent:{chat_id}"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            try:
                return int(row["value"])
            except (ValueError, TypeError):
                return None
        return None

    @_serialized_write
    async def set_dead_page_last_sent(self, chat_id: int, msg_id: int) -> None:
        """Record the primary relay-channel msg_id forwarded into this chat."""
        key = f"dead_page_last_sent:{chat_id}"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(msg_id)),
        )
        await self.db.commit()

    # ── Dead Page Repost Map (Epic 52 / T-417, Section 61.6.2) ─────

    _DEAD_PAGE_REPOST_MAP_TTL_SECONDS = 86400   # 24ч
    _DEAD_PAGE_REPOST_MAP_CAP = 500             # cap-очистка

    @_serialized_write
    async def record_dead_page_repost_map(
        self, chat_id: int, repost_msg_id: int, bot_msg_ids: list[int]
    ) -> None:
        """INSERT OR REPLACE маппинга {репост Славика → dead page бота}.

        Ленивая TTL-очистка (> 24ч) + cap-очистка (оставить последние 500 по id).
        """
        now = time.time()
        await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE created_at < ?",
            (now - self._DEAD_PAGE_REPOST_MAP_TTL_SECONDS,),
        )
        await self.db.execute(
            "INSERT OR REPLACE INTO dead_page_repost_map "
            "(chat_id, repost_msg_id, bot_msg_ids, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, repost_msg_id, json.dumps(bot_msg_ids), now),
        )
        # cap-очистка ПОСЛЕ вставки: оставить последние CAP по id (иначе
        # количество осциллирует 500/501 на границе)
        await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE id NOT IN "
            "(SELECT id FROM dead_page_repost_map ORDER BY id DESC LIMIT ?)",
            (self._DEAD_PAGE_REPOST_MAP_CAP,),
        )
        await self.db.commit()
        logger.info(
            "[dead_page_repost_map] recorded | chat=%s | repost_msg_id=%s | bot_ids=%s",
            chat_id, repost_msg_id, bot_msg_ids,
        )

    async def get_dead_page_repost_map(self, chat_id: int, repost_msg_id: int) -> list[int] | None:
        """bot_msg_ids по (chat_id, repost_msg_id); None = маппинга нет."""
        cursor = await self.db.execute(
            "SELECT bot_msg_ids FROM dead_page_repost_map "
            "WHERE chat_id = ? AND repost_msg_id = ?",
            (chat_id, repost_msg_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["bot_msg_ids"])
        except (ValueError, TypeError):
            logger.warning(
                "[dead_page_repost_map] broken JSON | chat=%s | repost_msg_id=%s",
                chat_id, repost_msg_id,
            )
            return None

    @_serialized_write
    async def delete_dead_page_repost_map(self, chat_id: int, repost_msg_id: int) -> None:
        """Снять маппинг (срабатывание ровно один раз на пару (чат, репост))."""
        await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE chat_id = ? AND repost_msg_id = ?",
            (chat_id, repost_msg_id),
        )
        await self.db.commit()

    @_serialized_write
    async def try_claim_dead_page_repost_map(
        self, chat_id: int, repost_msg_id: int
    ) -> bool:
        """Атомарно снять маппинг; True = claim выполнен, False = уже снят.

        M2 (review-fix): DELETE + rowcount — при двойном reply на удалённый
        репост в одном цикле оба хендлера успевают прочитать маппинг до
        delete, но фразу отправляет ровно первый claimer.
        """
        cursor = await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE chat_id = ? AND repost_msg_id = ?",
            (chat_id, repost_msg_id),
        )
        await self.db.commit()
        return cursor.rowcount == 1

    # ── Slavic Photo Counter (Epic 12) ──

    @_serialized_write
    async def slavic_photo_count_tick(self, chat_id: int, interval: int) -> bool:
        """Increment Slava's photo counter. Returns True if photo should be sent.

        Counter auto-resets after reaching the configured interval.
        Uses channel_state key: slavic_photo:{chat_id}
        """
        key = f"slavic_photo:{chat_id}"
        logger.debug("slavic_photo_count_tick: key=%s interval=%d", key, interval)
        # B-MCA01-1: single-writer уже удерживается `@_serialized_write` —
        # повторный `async with self._lock` здесь дал бы self-дедлок.
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        current = int(row["value"]) if row else 0
        logger.debug("slavic_photo_count_tick: current=%d", current)
        new_count = current + 1
        logger.debug("slavic_photo_count_tick: new_count=%d", new_count)
        if new_count >= interval:
            logger.debug("slavic_photo_count_tick: interval reached, resetting counter")
            await self.db.execute(
                "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
                (key, "0"),
            )
            await self.db.commit()
            return True
        else:
            logger.debug("slavic_photo_count_tick: incrementing counter to %d", new_count)
            await self.db.execute(
                "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
                (key, str(new_count)),
            )
            await self.db.commit()
            return False

    # ── Relay Album Map (Epic 14) ──────────────────────

    @_serialized_write
    async def save_relay_album_map(self, message_id: int, media_group_id: str) -> None:
        """Save media_group_id for a relay channel message. Idempotent."""
        await self.db.execute(
            "INSERT OR REPLACE INTO relay_album_map (message_id, media_group_id) VALUES (?, ?)",
            (message_id, media_group_id),
        )
        await self.db.commit()

    async def get_relay_media_group_id(self, message_id: int) -> str | None:
        """Get media_group_id for a relay channel message. Returns None if not found."""
        cursor = await self.db.execute(
            "SELECT media_group_id FROM relay_album_map WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        return row["media_group_id"] if row else None

    async def get_relay_album_message_ids(self, media_group_id: str) -> list[int]:
        """Get all message_ids belonging to the same media group, sorted ascending."""
        cursor = await self.db.execute(
            "SELECT message_id FROM relay_album_map WHERE media_group_id = ? ORDER BY message_id ASC",
            (media_group_id,),
        )
        rows = await cursor.fetchall()
        return [row["message_id"] for row in rows]

    # ── SmartModule: Summary (Epic 24) ──────────────────

    @_serialized_write
    async def save_smart_message(
        self,
        user_id: int,
        chat_id: int,
        text: str | None,
        reply_to_id: int | None,
        timestamp: int,
        media_type: str,
        author_name: str,
        is_forward: bool = False,
        forward_source: str = "",
        message_id: int | None = None,
    ) -> int:
        """Insert a chat message into smart_messages + FTS index. Returns the new row id.
        Epic 50 (58.7, D201): message_id = TG message_id (для reply-цепочек
        <Conversation_Thread>); None → NULL (легаси-вызовы без изменений)."""
        cursor = await self.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name,
             int(is_forward), forward_source, message_id),
        )
        row_id = cursor.lastrowid
        if text:
            await self.db.execute(
                "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
        # Раунд 9 (spec §3.1.1, T-816): «касание» users_meta на сообщение
        # юзера. 1 UPSERT по PK (~1 мс), внутри текущей транзакции (commit
        # ниже). fail-open: сбой НЕ роняет сохранение (NFR-4/NFR-7); импорт
        # истории (user_id NULL) и бот-строки сюда не попадают.
        if user_id is not None:
            try:
                await self.touch_user_meta(chat_id, user_id, timestamp)
            except Exception:
                logger.warning(
                    "[database] touch_user_meta failed — fail-open | "
                    "chat_id=%s user_id=%s", chat_id, user_id, exc_info=True)
        await self.db.commit()
        return row_id

    @_serialized_write
    async def update_smart_message_text(self, chat_id: int, tg_message_id: int,
                                        text: str) -> int:
        """Epic 67 (Section 71.3, D267): инъекция транскрипта в smart_messages
        вместо плейсхолдера «[голосовое]». Матч по (chat_id, tg_message_id);
        возвращает число обновлённых строк (0 = observer не сохранил — no-op).
        FTS-индекс пересобирается под новый текст."""
        cursor = await self.db.execute(
            "SELECT id, text FROM smart_messages WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0
        row_id = row["id"]
        old_text = row["text"] or ""
        await self.db.execute(
            "UPDATE smart_messages SET text = ? WHERE id = ?", (text, row_id))
        # FTS: DELETE несуществующего rowid в FTS5 даёт «malformed» — трогаем
        # индекс только если строка там была (текст был непустой).
        if old_text:
            await self.db.execute(
                "DELETE FROM smart_messages_fts WHERE rowid = ?", (row_id,))
        if text:
            await self.db.execute(
                "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
        await self.db.commit()
        return 1

    async def get_smart_window(self, chat_id: int, since_ts: int, limit: int) -> list:
        """L1: messages within the generation window (timestamp >= since_ts), ASC order."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (chat_id, since_ts, limit),
        )
        rows = await cursor.fetchall()
        rows.reverse()
        return rows

    async def get_smart_raw(self, chat_id: int, older_than_ts: int, limit: int,
                            exclude_imported: bool = False,
                            exclude_processed: bool = False) -> list:
        """L2/сжатие: messages older than the cutoff timestamp, ASC order.
        Фаза 2 (T-756, G1): exclude_imported=True → + AND import_key IS NULL
        (импортированные строки графом пополняются ТОЛЬКО Graph-воркером по
        history_processed — крон-LLM-экстракция по ним не гоняется);
        exclude_processed=True → + AND history_processed = 0 (extract-only:
        live-строки после успешной экстракции помечаются
        mark_smart_messages_processed — повторный крон их не пере-экстрактит)."""
        sql = (
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, "
            "author_name, is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? AND timestamp < ? "
        )
        if exclude_imported:
            sql += "AND import_key IS NULL "
        if exclude_processed:
            sql += "AND history_processed = 0 "
        sql += "ORDER BY timestamp ASC LIMIT ?"
        cursor = await self.db.execute(sql, (chat_id, older_than_ts, limit))
        return await cursor.fetchall()

    async def get_recent_messages(self, chat_id: int, limit: int) -> list:
        """Epic 65: ПОСЛЕДНИЕ limit сообщений чата, хронологически (ASC).
        Для chat_context фактчека/поиска (обогащение контекста вокруг цели)."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        rows.reverse()                     # DESC-выборка → хронологический порядок
        return rows


    async def get_messages_around(self, chat_id: int, target_tg_message_id,
                                  before: int, after: int) -> list:
        """Раунд 10.23 (F2, ADR-1023-2): двунаправленное окно вокруг целевого
        сообщения (anchor) — ``before`` старше якоря + сам якорь + ``after``
        новее, хронологически ASC (по ``id``). Каждое сообщение включается
        ровно один раз (якорь — из отдельного SELECT).
        Fail-open: пустой/нечисловой anchor, якорь не найден, ошибка БД →
        legacy ``get_recent_messages(before + after)`` (прежнее поведение)."""
        try:
            before = max(0, int(before or 0))
            after = max(0, int(after or 0))
        except (TypeError, ValueError):
            before = after = 0
        _fields = ("id, user_id, chat_id, text, reply_to_id, timestamp, "
                   "media_type, author_name, is_forward, forward_source, "
                   "tg_message_id")
        try:
            anchor_id = None
            if target_tg_message_id not in (None, "", 0):
                cursor = await self.db.execute(
                    "SELECT id FROM smart_messages "
                    "WHERE chat_id = ? AND tg_message_id = ? "
                    "ORDER BY id ASC LIMIT 1",
                    (chat_id, int(target_tg_message_id)),
                )
                anchor_row = await cursor.fetchone()
                anchor_id = anchor_row["id"] if anchor_row is not None else None
            if anchor_id is None:
                return await self.get_recent_messages(chat_id, before + after)
            older: list = []
            if before:
                cursor = await self.db.execute(
                    f"SELECT {_fields} FROM smart_messages "
                    "WHERE chat_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                    (chat_id, anchor_id, before),
                )
                older = list(await cursor.fetchall())
                older.reverse()            # DESC-выборка → ASC
            cursor = await self.db.execute(
                f"SELECT {_fields} FROM smart_messages "
                "WHERE chat_id = ? AND id = ?",
                (chat_id, anchor_id),
            )
            anchor = await cursor.fetchone()
            newer: list = []
            if after:
                cursor = await self.db.execute(
                    f"SELECT {_fields} FROM smart_messages "
                    "WHERE chat_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                    (chat_id, anchor_id, after),
                )
                newer = list(await cursor.fetchall())
            result = older
            if anchor is not None:
                result.append(anchor)
            result.extend(newer)
            return result
        except Exception:
            logger.warning(
                "db: get_messages_around failed — fallback к последним | "
                "chat=%s", chat_id, exc_info=True)
            try:
                return await self.get_recent_messages(chat_id, before + after)
            except Exception:
                logger.warning("db: get_recent_messages fallback failed | "
                               "chat=%s", chat_id, exc_info=True)
                return []


    async def get_smart_message_by_tg_id(self, chat_id: int, tg_message_id: int):
        """Epic 50 (58.7, D201): строка smart_messages по TG message_id
        (рекурсия reply-цепочек <Conversation_Thread>); None — нет записи.

        MCA-03 (ADR-1027-4 D1): chat-scoped lookup — канонический ключ
        `(chat_id, tg_message_id)`; возвращаются и поля идентичности/времени/
        ролей/версий (v16)."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id, "
            "caption, sent_at, ingested_at, edited_at, sent_at_source, "
            "source_kind, namespace, source_record_id, content_hash, media_ref, "
            "reply_to_kind, reply_to_author_id, quote_text, quote_author_id, "
            "forward_author_id, message_state, state_evidence, current_revision "
            "FROM smart_messages WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        return await cursor.fetchone()

    # ── Раунд 10.27 (MCA Wave 1, `mca-03-message-identity`, ADR-1027-4) ─────
    # Канонический get-or-create/версии/mapping. Все доменные записи — через
    # единый write-механизм `mca-01` (`write_transaction`), не прямым commit.

    async def save_smart_message_identity(self, rec: dict) -> int:
        """Канонический write сообщения (ADR-1027-4 D1/D2/D3).

        Lookup по `(chat_id, tg_message_id)` ДО вставки: живое повторное
        наблюдение того же TG-сообщения не создаёт вторую строку; изменение
        текста/подписи обновляет canonical source (FTS пересобирается). Новый
        ряд получает `initial`-версию и source record. `timestamp` (legacy) не
        переименовывается; `sent_at`/`ingested_at` пишутся отдельно."""
        chat_id = int(rec["chat_id"])
        tg = rec.get("tg_message_id")
        text = rec.get("text")
        caption = rec.get("caption")
        content_hash = rec.get("content_hash")
        now = int(time.time())

        async def _record_occurrence(conn, message_id: int) -> None:
            """Вхождение (namespace + local record id) для canonical source.

            Вызывается и на insert, и на существующей строке (M-MCA03-4):
            live-наблюдение импортной копии добавляет live-вхождение к тому же
            canonical source; `INSERT OR IGNORE` (UNIQUE namespace+local) —
            повторная запись идемпотентна."""
            namespace = rec.get("namespace")
            source_record_id = rec.get("source_record_id")
            if namespace and source_record_id:
                await conn.execute(
                    "INSERT OR IGNORE INTO message_source_records "
                    "(message_id, namespace, local_record_id, tg_message_id, "
                    "chat_id, source_kind, observed_at) VALUES (?,?,?,?,?,?,?)",
                    (message_id, namespace, source_record_id, tg, chat_id,
                     rec.get("source_kind") or "unknown",
                     rec.get("ingested_at", now)))

        async def _body(conn):
            existing = None
            if tg is not None:
                cur = await conn.execute(
                    "SELECT id FROM smart_messages "
                    "WHERE chat_id = ? AND tg_message_id = ?", (chat_id, tg))
                existing = await cur.fetchone()
            if existing is not None:
                message_id = int(existing["id"])
                cur = await conn.execute(
                    "SELECT text, caption FROM smart_messages WHERE id = ?",
                    (message_id,))
                prev = await cur.fetchone()
                changed = (text != prev["text"]) or (caption != prev["caption"])
                if changed:
                    # FTS external-content: удаление ДО UPDATE контент-таблицы
                    # (иначе FTS5 читает уже новый текст и не снимает старые
                    # токены).
                    if prev["text"]:
                        await conn.execute(
                            "DELETE FROM smart_messages_fts WHERE rowid = ?",
                            (message_id,))
                    await conn.execute(
                        "UPDATE smart_messages SET text=?, caption=?, "
                        "content_hash=?, media_ref=COALESCE(?, media_ref), "
                        "sent_at=COALESCE(sent_at, ?), "
                        "ingested_at=COALESCE(ingested_at, ?), "
                        "sent_at_source=COALESCE(sent_at_source, ?), "
                        "source_kind=COALESCE(source_kind, ?) WHERE id=?",
                        (text, caption, content_hash, rec.get("media_ref"),
                         rec.get("sent_at"), rec.get("ingested_at", now),
                         rec.get("sent_at_source"), rec.get("source_kind"),
                         message_id))
                    if text:
                        await conn.execute(
                            "INSERT INTO smart_messages_fts(rowid, text) "
                            "VALUES (?, ?)", (message_id, text))
                else:
                    await conn.execute(
                        "UPDATE smart_messages SET "
                        "sent_at=COALESCE(sent_at, ?), "
                        "ingested_at=COALESCE(ingested_at, ?), "
                        "sent_at_source=COALESCE(sent_at_source, ?), "
                        "source_kind=COALESCE(source_kind, ?) WHERE id=?",
                        (rec.get("sent_at"), rec.get("ingested_at", now),
                         rec.get("sent_at_source"), rec.get("source_kind"),
                         message_id))
                await _record_occurrence(conn, message_id)
                return message_id
            cur = await conn.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, "
                "reply_to_id, timestamp, media_type, author_name, is_forward, "
                "forward_source, tg_message_id, caption, sent_at, ingested_at, "
                "edited_at, sent_at_source, source_kind, namespace, "
                "source_record_id, content_hash, media_ref, reply_to_kind, "
                "reply_to_author_id, quote_text, quote_author_id, "
                "forward_author_id, message_state, state_evidence, "
                "current_revision) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?)",
                (rec.get("user_id"), chat_id, text, rec.get("reply_to_id"),
                 int(rec.get("timestamp", now)), rec.get("media_type", "text"),
                 rec.get("author_name", ""), int(bool(rec.get("is_forward"))),
                 rec.get("forward_source", ""), tg, caption, rec.get("sent_at"),
                 rec.get("ingested_at", now), rec.get("edited_at"),
                 rec.get("sent_at_source"), rec.get("source_kind"),
                 rec.get("namespace"), rec.get("source_record_id"),
                 content_hash, rec.get("media_ref"), rec.get("reply_to_kind"),
                 rec.get("reply_to_author_id"), rec.get("quote_text"),
                 rec.get("quote_author_id"), rec.get("forward_author_id"),
                 rec.get("message_state"), rec.get("state_evidence"),
                 rec.get("current_revision", 1)))
            message_id = int(cur.lastrowid)
            if text:
                await conn.execute(
                    "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                    (message_id, text))
            revision_no = int(rec.get("current_revision", 1) or 1)
            await conn.execute(
                "INSERT INTO message_revisions (message_id, chat_id, "
                "tg_message_id, revision_no, revision_kind, text, caption, "
                "content_hash, evidence_kind, editor_user_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (message_id, chat_id, tg, revision_no, "initial", text,
                 caption, content_hash or "", None, None, now))
            await _record_occurrence(conn, message_id)
            return message_id

        message_id = await self.write_transaction(
            _body, op_name="save_smart_message_identity")
        user_id = rec.get("user_id")
        if user_id is not None:
            try:
                await self.touch_user_meta(
                    chat_id, user_id, int(rec.get("timestamp", now)))
            except Exception:
                logger.warning(
                    "[database] touch_user_meta failed — fail-open | "
                    "chat_id=%s user_id=%s", chat_id, user_id, exc_info=True)
        return message_id

    async def apply_message_revision(self, *, message_id: int, chat_id: int,
                                     tg_message_id, revision_kind: str,
                                     text, caption=None, content_hash=None,
                                     edited_at=None, evidence_kind=None,
                                     editor_user_id=None) -> int:
        """Append версии + обновление canonical source + FTS (D5).

        `current_revision` = номер новой версии (актуальна только последняя);
        FTS пересобирается под новый текст."""
        async def _body(conn):
            cur = await conn.execute(
                "SELECT COALESCE(MAX(revision_no), 0) AS m "
                "FROM message_revisions WHERE message_id = ?", (message_id,))
            next_no = int((await cur.fetchone())["m"]) + 1
            cur = await conn.execute(
                "SELECT text FROM smart_messages WHERE id = ?", (message_id,))
            prev = await cur.fetchone()
            old_text = prev["text"] if prev is not None else None
            # FTS external-content: удаление ДО UPDATE контент-таблицы.
            if old_text:
                await conn.execute(
                    "DELETE FROM smart_messages_fts WHERE rowid = ?",
                    (message_id,))
            await conn.execute(
                "UPDATE smart_messages SET text=?, caption=?, content_hash=?, "
                "edited_at=COALESCE(?, edited_at), current_revision=?, "
                "message_state=COALESCE(message_state, 'active') WHERE id=?",
                (text, caption, content_hash, edited_at, next_no, message_id))
            if text:
                await conn.execute(
                    "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                    (message_id, text))
            await conn.execute(
                "INSERT INTO message_revisions (message_id, chat_id, "
                "tg_message_id, revision_no, revision_kind, text, caption, "
                "content_hash, evidence_kind, editor_user_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (message_id, chat_id, tg_message_id, next_no, revision_kind,
                 text, caption, content_hash or "", evidence_kind,
                 editor_user_id, int(time.time())))
            return next_no

        return int(await self.write_transaction(
            _body, op_name="apply_message_revision"))

    async def apply_message_state(self, *, message_id: int, state: str,
                                  evidence: str, revision_kind=None,
                                  chat_id=None, tg_message_id=None,
                                  editor_user_id=None) -> int:
        """Смена `message_state` + версия-свидетельство (D5).

        Вызывается только при непустом `evidence` (проверяет контракт)."""
        async def _body(conn):
            cur = await conn.execute(
                "SELECT chat_id, tg_message_id, text, caption, content_hash "
                "FROM smart_messages WHERE id = ?", (message_id,))
            row = await cur.fetchone()
            if row is None:
                return 0
            cur = await conn.execute(
                "SELECT COALESCE(MAX(revision_no), 0) AS m "
                "FROM message_revisions WHERE message_id = ?", (message_id,))
            next_no = int((await cur.fetchone())["m"]) + 1
            await conn.execute(
                "UPDATE smart_messages SET message_state=?, state_evidence=?, "
                "current_revision=? WHERE id=?",
                (state, evidence, next_no, message_id))
            await conn.execute(
                "INSERT INTO message_revisions (message_id, chat_id, "
                "tg_message_id, revision_no, revision_kind, text, caption, "
                "content_hash, evidence_kind, editor_user_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (message_id, row["chat_id"], row["tg_message_id"], next_no,
                 revision_kind or state, row["text"], row["caption"],
                 row["content_hash"] or "", evidence, editor_user_id,
                 int(time.time())))
            return next_no

        return int(await self.write_transaction(
            _body, op_name="apply_message_state"))

    async def insert_message_source_record(self, *, message_id: int,
                                           namespace: str,
                                           local_record_id, tg_message_id,
                                           chat_id: int, source_kind: str,
                                           observed_at=None) -> bool:
        """Вхождение сообщения (namespace + stable local record id) — D2.

        `local_record_id`/`source_record_id` — локальные, НЕ Telegram ID;
        UNIQUE(namespace, local_record_id) → повторный импорт идемпотентен."""
        async def _body(conn):
            cur = await conn.execute(
                "INSERT OR IGNORE INTO message_source_records "
                "(message_id, namespace, local_record_id, tg_message_id, "
                "chat_id, source_kind, observed_at) VALUES (?,?,?,?,?,?,?)",
                (message_id, namespace, local_record_id, tg_message_id,
                 chat_id, source_kind,
                 int(observed_at if observed_at is not None else time.time())))
            return cur.rowcount

        return bool(await self.write_transaction(
            _body, op_name="insert_message_source_record"))

    async def upsert_chat_id_migration(self, *, old_chat_id: int,
                                       new_chat_id: int, evidence: str,
                                       observed_at=None) -> bool:
        """Явный mapping смены `chat_id` по подтверждённым метаданным (D6)."""
        async def _body(conn):
            await conn.execute(
                "INSERT OR REPLACE INTO chat_id_migrations "
                "(old_chat_id, new_chat_id, evidence, observed_at) "
                "VALUES (?,?,?,?)",
                (old_chat_id, new_chat_id, evidence,
                 int(observed_at if observed_at is not None else time.time())))

        await self.write_transaction(
            _body, op_name="upsert_chat_id_migration")
        return True

    async def resolve_canonical_chat_id(self, chat_id: int, *,
                                        max_hops: int = 10) -> int:
        """Канонический `chat_id` по цепочке mapping (D6), с защитой от цикла."""
        current = int(chat_id)
        seen: set[int] = set()
        for _ in range(max(1, int(max_hops))):
            cursor = await self.db.execute(
                "SELECT new_chat_id FROM chat_id_migrations "
                "WHERE old_chat_id = ?", (current,))
            row = await cursor.fetchone()
            if row is None:
                break
            nxt = int(row["new_chat_id"])
            if nxt == current or nxt in seen:
                break
            seen.add(current)
            current = nxt
        return current

    async def get_message_source_records(self, message_id: int) -> list:
        """Вхождения canonical source (D2) — для provenance-потребителей."""
        cursor = await self.db.execute(
            "SELECT source_record_id, message_id, namespace, local_record_id, "
            "tg_message_id, chat_id, source_kind, observed_at "
            "FROM message_source_records WHERE message_id = ? "
            "ORDER BY source_record_id", (message_id,))
        return await cursor.fetchall()

    async def get_message_revisions(self, message_id: int) -> list:
        """Версии сообщения по возрастанию `revision_no` (D5)."""
        cursor = await self.db.execute(
            "SELECT revision_id, message_id, chat_id, tg_message_id, "
            "revision_no, revision_kind, text, caption, content_hash, "
            "evidence_kind, editor_user_id, created_at "
            "FROM message_revisions WHERE message_id = ? "
            "ORDER BY revision_no", (message_id,))
        return await cursor.fetchall()

    @_serialized_write
    async def delete_smart_messages_older_than(self, chat_id: int, cutoff_ts: int) -> int:
        """Delete messages (+ FTS rows) older than cutoff. Returns count of deleted rows."""
        await self.db.execute(
            "DELETE FROM smart_messages_fts WHERE rowid IN "
            "(SELECT id FROM smart_messages WHERE chat_id = ? AND timestamp < ? "
            "AND text IS NOT NULL AND text != '')",
            (chat_id, cutoff_ts),
        )
        cursor = await self.db.execute(
            "DELETE FROM smart_messages WHERE chat_id = ? AND timestamp < ?",
            (chat_id, cutoff_ts),
        )
        await self.db.commit()
        return cursor.rowcount

    async def _delete_fts_rows(self, chat_id: int, ids: list[int]) -> None:
        """FTS5-строки указанных id чата (external-content). НЕ коммитит.

        D-2.5 (Low, ревью итерации 4): общий хелпер для
        `delete_smart_messages_by_ids` и `purge_imported_history` (раньше
        FTS-удаление в purge инлайнилось, а его docstring ссылался на метод
        как на единственный путь). `aiosqlite.DatabaseError` (rowid вне
        индекса — рассинхрон/legacy) поднимается наверх: обрабатывает
        вызывающий."""
        placeholders = ",".join("?" for _ in ids)
        await self.db.execute(
            f"DELETE FROM smart_messages_fts WHERE rowid IN "
            f"(SELECT id FROM smart_messages WHERE chat_id = ? "
            f"AND id IN ({placeholders}) AND text IS NOT NULL AND text != '')",
            [int(chat_id), *ids])

    @_serialized_write
    async def delete_smart_messages_by_ids(self, chat_id: int, ids: list[int]) -> int:
        """Delete specific messages (+ FTS rows) of a chat. Returns count deleted."""
        if not ids:
            return 0
        await self._delete_fts_rows(chat_id, ids)
        placeholders = ",".join("?" for _ in ids)
        cursor = await self.db.execute(
            f"DELETE FROM smart_messages WHERE chat_id = ? AND id IN ({placeholders})",
            [chat_id, *ids],
        )
        await self.db.commit()
        return cursor.rowcount

    @_serialized_write
    async def mark_smart_messages_processed(self, chat_id: int,
                                            ids: list[int]) -> int:
        """Фаза 2 (T-756/G1, fix): маркер обработанности live-строк
        (history_processed=1) ПОСЛЕ успешной extract-only экстракции окна —
        повторный крон (4×/день) не пере-экстрактит те же строки вечно
        (инфляция весов рёбер). Только live-строки (import_key IS NULL):
        выборка extract-ветки и выборка Graph-воркера (import_key IS NOT
        NULL AND history_processed = 0) не пересекаются. Returns count."""
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cursor = await self.db.execute(
            f"UPDATE smart_messages SET history_processed = 1 "
            f"WHERE chat_id = ? AND import_key IS NULL "
            f"AND id IN ({placeholders})",
            [chat_id, *ids])
        await self.db.commit()
        return cursor.rowcount

    # ── F7 (10.19, ADR-1019-6 D1/D4): retention импорта + метрики памяти ────

    async def select_imported_history(self, chat_id: int, cutoff_ts: int,
                                      after_id: int = 0,
                                      limit: int = 2000) -> list:
        """F7: пачка импортированных строк чата для архивации перед purge
        (`import_key IS NOT NULL AND history_processed = 1 AND timestamp <
        cutoff`, id > after_id, ORDER BY id). Только чтение (fail-open на
        вызывающем)."""
        cursor = await self.db.execute(
            "SELECT id, chat_id, user_id, text, reply_to_id, timestamp, "
            "media_type, author_name, is_forward, forward_source, "
            "tg_message_id, import_key, history_processed "
            "FROM smart_messages WHERE chat_id = ? AND import_key IS NOT NULL "
            "AND history_processed = 1 AND timestamp < ? AND id > ? "
            "ORDER BY id LIMIT ?",
            (int(chat_id), int(cutoff_ts), int(after_id), max(1, int(limit))))
        return await cursor.fetchall()

    @_serialized_write
    async def purge_imported_history(self, *, chat_cutoffs: dict[int, int],
                                     batch: int = 2000,
                                     dry_run: bool = False,
                                     chat_max_ids: dict[int, int] | None = None
                                     ) -> dict:
        """F7 (ADR-1019-6 D1/D2; ADR-1019-8 D5): удаление импортированной истории
        `smart_messages` по **keyword-only allow-list** чатов.

        Удаляются строки `WHERE chat_id = ? AND import_key IS NOT NULL AND
        history_processed = 1 AND timestamp < chat_cutoffs[chat_id]` (+ строки
        FTS5 через внутренний `_delete_fts_rows`), батчами `batch`.
        Маппинг `chat_cutoffs` **обязателен** (нет дефолта): «удалить всем по
        глобальному сроку» невозможно по построению — вызывающий обязан
        заранее отфильтровать «вечные» чаты через
        `retention_policy.imported_history_purge_allowed` (чаты с retention `0` сюда не
        попадает никогда). `dry_run=True` → ТОЛЬКО подсчёт кандидатов.

        D-7 (ревью Батча E): `chat_max_ids` фиксирует ВЕРХНЮЮ границу id,
        реально заархивированную для чата (`id <= max_id` в дополнение к
        `timestamp < cutoff`). Строки, ставшие `history_processed=1` между
        снапшотом архива и удалением, имеют id > заархивированного максимума
        и НЕ удаляются (вызывающий дополнительно сверяет
        `candidates == archived`). Без `chat_max_ids` поведение прежнее
        (idempotent по `timestamp`).

        `candidates` — фактическое число подходящих строк (не `deleted`).
        Идемпотентно. Возвращает
        `{candidates, deleted, batches, dry_run}`."""
        out = {"candidates": 0, "deleted": 0, "batches": 0,
               "dry_run": bool(dry_run)}
        if not chat_cutoffs:
            return out
        batch = max(1, int(batch))
        max_ids = chat_max_ids or {}

        def _where(chat_id: int, cutoff: int) -> tuple[str, list]:
            sql = ("chat_id = ? AND import_key IS NOT NULL "
                   "AND history_processed = 1 AND timestamp < ?")
            params: list = [int(chat_id), int(cutoff)]
            max_id = max_ids.get(int(chat_id))
            if max_id is not None:
                sql += " AND id <= ?"
                params.append(int(max_id))
            return sql, params

        for chat_id, cutoff in chat_cutoffs.items():
            where, params = _where(chat_id, cutoff)
            cursor = await self.db.execute(
                f"SELECT COUNT(*) AS c FROM smart_messages WHERE {where}",
                params)
            row = await cursor.fetchone()
            out["candidates"] += int(row["c"]) if row else 0
        if dry_run:
            return out
        for chat_id, cutoff in chat_cutoffs.items():
            where, params = _where(chat_id, cutoff)
            while True:
                cursor = await self.db.execute(
                    f"SELECT id FROM smart_messages WHERE {where} "
                    f"ORDER BY id LIMIT ?", [*params, batch])
                ids = [row["id"] for row in await cursor.fetchall()]
                if not ids:
                    break
                placeholders = ",".join("?" for _ in ids)
                # FTS5 external-content: удаление rowid, отсутствующего в
                # индексе (рассинхрон ФС↔БД/legacy-строки), поднимает
                # DatabaseError — основной DELETE при этом обязан пройти
                # (поиск JOIN'ит smart_messages, stale-строки невидимы).
                try:
                    await self._delete_fts_rows(chat_id, ids)
                except aiosqlite.DatabaseError:
                    logger.warning(
                        "[database] import purge: FTS delete skipped "
                        "(out-of-sync index) | chat=%s | batch=%d",
                        chat_id, len(ids))
                cursor = await self.db.execute(
                    f"DELETE FROM smart_messages WHERE chat_id = ? "
                    f"AND id IN ({placeholders})", [int(chat_id), *ids])
                await self.db.commit()
                out["deleted"] += int(cursor.rowcount or 0)
                out["batches"] += 1
                if len(ids) < batch:
                    break
        return out

    async def count_smart_messages(self, chat_id: int | None = None) -> int:
        """F7/D4: число строк сырья (всего или по чату)."""
        sql = "SELECT COUNT(*) AS c FROM smart_messages"
        params: list = []
        if chat_id is not None:
            sql += " WHERE chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def count_overdue_facts(self, chat_id: int | None = None) -> int:
        """F7/D4: «просроченные» факты (expires_at < now, статус не
        терминальный). R17: только число."""
        sql = ("SELECT COUNT(*) AS c FROM graph_facts "
               "WHERE expires_at IS NOT NULL AND expires_at < ? "
               "AND status NOT IN ('expired', 'archived_belief')")
        params: list = [int(time.time())]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def count_unconfirmed_facts(self, chat_id: int | None = None) -> int:
        """F7/D4: неподтверждённые факты (`status='unconfirmed'`)."""
        sql = "SELECT COUNT(*) AS c FROM graph_facts WHERE status = 'unconfirmed'"
        params: list = []
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    @_serialized_write
    async def save_archive_fact(self, chat_id: int, fact: str, timestamp: int) -> int:
        """L3: save a compressed archive fact (+ FTS row). Returns the new fact id."""
        cursor = await self.db.execute(
            "INSERT INTO smart_archive_facts (chat_id, fact, timestamp) VALUES (?, ?, ?)",
            (chat_id, fact, timestamp),
        )
        fact_id = cursor.lastrowid
        await self.db.execute(
            "INSERT INTO smart_archive_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, fact),
        )
        await self.db.commit()
        return fact_id

    @_serialized_write
    async def delete_archive_facts_older_than(self, chat_id: int, cutoff_ts: int) -> int:
        """Delete archive facts (+ FTS rows) older than cutoff. Returns count deleted."""
        await self.db.execute(
            "DELETE FROM smart_archive_facts_fts WHERE rowid IN "
            "(SELECT id FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?)",
            (chat_id, cutoff_ts),
        )
        cursor = await self.db.execute(
            "DELETE FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?",
            (chat_id, cutoff_ts),
        )
        await self.db.commit()
        return cursor.rowcount

    async def search_messages_fts(self, chat_id: int, match_query: str, limit: int) -> list:
        """L2-RAG / фоллбек: FTS5 search over raw messages, ordered by rank.

        10.20 (БЛОК 2.8, ADR-1020-2): аддитивно отдаём `tg_message_id` —
        для ID-политики канонического рендера (`tg:` приоритетнее `msg:`)."""
        cursor = await self.db.execute(
            "SELECT m.id, m.user_id, m.chat_id, m.text, m.reply_to_id, m.timestamp, "
            "m.media_type, m.author_name, m.is_forward, m.forward_source, "
            "m.tg_message_id "
            "FROM smart_messages_fts JOIN smart_messages m ON m.id = smart_messages_fts.rowid "
            "WHERE smart_messages_fts MATCH ? AND m.chat_id = ? "
            "ORDER BY smart_messages_fts.rank LIMIT ?",
            (match_query, chat_id, limit),
        )
        return await cursor.fetchall()

    async def search_messages_fts_count(self, chat_id: int, match_query: str,
                                        since_ts: int = 0) -> dict:
        """(count, first_seen, last_seen) по FTS-совпадениям smart_messages.
        since_ts>0 — окно по timestamp (в SQL, не пост-фильтр top-N).
        Bugfix-раунд 04.09.2026 (Часть 2, FR-19): точный счётчик для
        query_chat_memory (строки режутся top-40 по rank ДО фильтра окна —
        точное «N раз в окне» из выборки не извлекается)."""
        sql = ("SELECT COUNT(*) AS cnt, MIN(m.timestamp) AS first_ts, "
               "MAX(m.timestamp) AS last_ts FROM smart_messages m "
               "WHERE m.chat_id = ? AND m.id IN "
               "(SELECT rowid FROM smart_messages_fts WHERE smart_messages_fts MATCH ?)")
        params: list = [chat_id, match_query]
        if since_ts:
            sql += " AND m.timestamp >= ?"
            params.append(since_ts)
        cursor = await self.db.execute(sql, tuple(params))
        row = await cursor.fetchone()
        return {"count": int(row["cnt"] or 0) if row else 0,
                "first_seen": row["first_ts"] if row else None,
                "last_seen": row["last_ts"] if row else None}

    async def search_messages_fts_count_by_author(self, chat_id: int,
                                                  match_query: str,
                                                  since_ts: int = 0,
                                                  until_ts: int = 0) -> dict:
        """10.20 (БЛОК 2.8, ADR-1020-2 п.2, R16): счётчик упоминаний
        FTS-совпадений smart_messages с РАЗБИВКОЙ ПО АВТОРАМ.

        Возвращает ``{"count", "first_seen", "last_seen", "by_author":
        [{"author_name", "user_id", "count"}, ...]}`` — ``by_author`` отсортирован
        по убыванию count (имя резолвит вызывающий тем же R16-каскадом
        `tool_router._resolve_name`: здесь отдаём сырые author_name+user_id,
        чтобы каскад алиасов/ников работал — имя НЕ выдумываем).

        ``since_ts``/``until_ts`` (>0) — окно по timestamp В SQL (не
        пост-фильтр top-N, прецедент `search_messages_fts_count`)."""
        sql = ("SELECT COUNT(*) AS cnt, MIN(m.timestamp) AS first_ts, "
               "MAX(m.timestamp) AS last_ts, "
               "COALESCE(m.author_name, '') AS author_name, "
               "m.user_id AS user_id "
               "FROM smart_messages m "
               "WHERE m.chat_id = ? AND m.id IN "
               "(SELECT rowid FROM smart_messages_fts "
               "WHERE smart_messages_fts MATCH ?)")
        params: list = [chat_id, match_query]
        if since_ts:
            sql += " AND m.timestamp >= ?"
            params.append(since_ts)
        if until_ts:
            sql += " AND m.timestamp <= ?"
            params.append(until_ts)
        sql += " GROUP BY COALESCE(m.author_name, ''), m.user_id"
        cursor = await self.db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        total = 0
        first_ts = None
        last_ts = None
        by_author: list[dict] = []
        for row in rows:
            chunk = int(row["cnt"] or 0)
            total += chunk
            first = row["first_ts"]
            last = row["last_ts"]
            if first is not None and (first_ts is None or first < first_ts):
                first_ts = first
            if last is not None and (last_ts is None or last > last_ts):
                last_ts = last
            by_author.append({
                "author_name": row["author_name"] or "",
                "user_id": row["user_id"],
                "count": chunk,
            })
        by_author.sort(key=lambda item: (-item["count"],
                                         str(item["author_name"])))
        return {"count": total, "first_seen": first_ts, "last_seen": last_ts,
                "by_author": by_author}

    # ── «Летописец» (раунд 10.20, БЛОК 1, ADR-1020-4, T-1888/T-1889/T-1891) ──

    async def get_lore_story(self, chat_id: int, topic_key: str) -> dict | None:
        """UPD-hit «Летописца» (T-1891): сохранённая история по
        ``(chat_id, normalize_text(topic))`` или None. Ошибки чтения —
        пустой результат (диалог не роняется, NFR-4)."""
        try:
            cursor = await self.db.execute(
                "SELECT id, chat_id, topic_key, topic, story, last_ts, "
                "created_at, updated_at FROM lore_stories "
                "WHERE chat_id = ? AND topic_key = ?",
                (chat_id, str(topic_key or "")))
            row = await cursor.fetchone()
            return dict(row) if row else None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[database] get_lore_story failed — None | "
                           "chat=%s", chat_id, exc_info=True)
            return None

    async def list_lore_stories(self, chat_id: int, limit: int = 200) -> list:
        """MCA-07 (T-3845): bounded-список сохранённых историй «Летописца»
        чата (эпизоды-фасад; REUSE `lore_stories`, второй каталог запрещён).
        Ошибка чтения → [] (деградация, не бросает)."""
        try:
            cursor = await self.db.execute(
                "SELECT id, chat_id, topic_key, topic, story, last_ts, "
                "created_at, updated_at FROM lore_stories WHERE chat_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (int(chat_id), max(1, int(limit))))
            return await cursor.fetchall()
        except Exception:
            logger.warning("[database] list_lore_stories failed — empty | "
                           "chat=%s", chat_id, exc_info=True)
            return []

    @_serialized_write
    async def upsert_lore_story(self, chat_id: int, topic_key: str, topic: str,
                                story: str, last_ts: int = 0) -> None:
        """Запись истории «Летописца» (T-1891): UPSERT по UNIQUE
        ``(chat_id, topic_key)``; ``last_ts`` — last_seen на момент компиляции
        (для дотягивания новых сообщений ``ts > last_ts``). Ошибки — WARNING
        (деградация без UPD, NFR-4), НЕ бросает."""
        now = int(time.time())
        try:
            await self.db.execute(
                "INSERT INTO lore_stories "
                "(chat_id, topic_key, topic, story, last_ts, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id, topic_key) DO UPDATE SET "
                "topic = excluded.topic, story = excluded.story, "
                "last_ts = excluded.last_ts, updated_at = excluded.updated_at",
                (chat_id, str(topic_key or ""), str(topic or ""),
                 str(story or ""), int(last_ts or 0), now, now))
            await self.db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[database] upsert_lore_story failed | chat=%s",
                           chat_id, exc_info=True)

    async def lore_graph_slice(self, chat_id: int, topic: str, *,
                               depth: int = 2, max_nodes: int = 20,
                               max_edges: int = 120,
                               max_facts: int = 30) -> dict:
        """Шаг А «Летописца» (T-1888): структурный срез графа вокруг топика.

        Узел топика (``nodes.entity_name`` casefold-содержит токен темы) →
        связи 1..``depth`` уровня в ОБЕ стороны (``edges``: relation_type/
        weight/fact_id-provenance, ADR-1018-3 D1) → привязанные факты и
        Убеждения (``graph_facts`` по ``edge.fact_id``).

        Возврат ``{"nodes": [...], "edges": [...], "facts": [...]}`` (сырые
        строки). Детерминизм: узлы/рёбра — по id, факты — ASC по
        ``(rag_ts, id)``. Рендер ``format_context_item(kind="fact")`` — на
        сервисе. НЕ бросает: ошибка → пустой срез + WARNING.

        M2 (S10.20-8): поиск узла топика — детерминированный скан первых
        ``_LORE_NODE_SCAN_LIMIT`` (=2000) узлов чата по ``id``; узлы сверх
        лимита срезом не находятся (перф-защита на росте БД, осознанный кап)."""
        empty = {"nodes": [], "edges": [], "facts": []}
        seeds = sorted({tok for tok in _LORE_TOKEN_RE.findall(
            str(topic or "").casefold()) if len(tok) >= 3})
        if not seeds:
            return dict(empty)
        try:
            cap_depth = min(max(1, int(depth)), 2)
            cap_nodes = max(1, int(max_nodes))
            cap_edges = max(1, int(max_edges))
            cursor = await self.db.execute(
                "SELECT id, entity_name, entity_type FROM nodes "
                "WHERE chat_id = ? ORDER BY id LIMIT ?",
                (chat_id, _LORE_NODE_SCAN_LIMIT))
            nodes: dict[int, dict] = {}
            for row in (dict(r) for r in await cursor.fetchall()):
                name = str(row.get("entity_name") or "")
                if not any(seed in name.casefold() for seed in seeds):
                    continue
                nodes[int(row["id"])] = {
                    "id": int(row["id"]),
                    "entity_name": name,
                    "entity_type": str(row.get("entity_type") or ""),
                }
                if len(nodes) >= cap_nodes:
                    break
            if not nodes:
                return dict(empty)
            frontier = set(nodes)
            edge_keys: set[tuple] = set()
            edges: list[dict] = []
            for _ in range(cap_depth):
                if not frontier or len(edges) >= cap_edges:
                    break
                front = sorted(frontier)
                placeholders = ",".join("?" * len(front))
                cursor = await self.db.execute(
                    "SELECT e.source_id AS sid, e.target_id AS tid, "
                    "e.relation_type AS rel, e.weight AS weight, "
                    "e.fact_id AS fact_id, ns.entity_name AS sname, "
                    "nt.entity_name AS tname FROM edges e "
                    "JOIN nodes ns ON ns.id = e.source_id "
                    "JOIN nodes nt ON nt.id = e.target_id "
                    "WHERE e.chat_id = ? AND (e.source_id IN (" + placeholders
                    + ") OR e.target_id IN (" + placeholders + ")) "
                    "ORDER BY e.source_id, e.target_id, e.relation_type "
                    "LIMIT ?",
                    [chat_id] + front + front + [cap_edges])
                next_frontier: set[int] = set()
                for row in (dict(r) for r in await cursor.fetchall()):
                    sid = int(row["sid"])
                    tid = int(row["tid"])
                    key = (sid, tid, str(row["rel"] or ""))
                    if key in edge_keys:
                        continue
                    if len(edges) >= cap_edges:
                        break
                    edge_keys.add(key)
                    edges.append({
                        "source_id": sid, "target_id": tid,
                        "relation_type": key[2],
                        "source": str(row.get("sname") or ""),
                        "target": str(row.get("tname") or ""),
                        "weight": int(row.get("weight") or 0),
                        "fact_id": row.get("fact_id"),
                    })
                    for nid, nname in ((sid, row.get("sname")),
                                       (tid, row.get("tname"))):
                        if nid not in nodes:
                            nodes[nid] = {"id": nid,
                                          "entity_name": str(nname or ""),
                                          "entity_type": ""}
                            next_frontier.add(nid)
                frontier = next_frontier
            facts: list[dict] = []
            fact_ids = sorted({int(edge["fact_id"]) for edge in edges
                               if edge.get("fact_id")})
            if fact_ids:
                placeholders = ",".join("?" * len(fact_ids))
                cursor = await self.db.execute(
                    "SELECT id, fact, target_user, created_at, "
                    "message_timestamp, kind, origin, status, weight "
                    "FROM graph_facts WHERE chat_id = ? AND id IN ("
                    + placeholders + ") ORDER BY id",
                    [chat_id] + fact_ids)
                facts = [_lore_fact_row(dict(r))
                         for r in await cursor.fetchall()]
            facts.sort(key=lambda f: (int(f.get("rag_ts") or 0),
                                      int(f.get("id") or 0)))
            return {"nodes": list(nodes.values()), "edges": edges,
                    "facts": facts[:max(1, int(max_facts))]}
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[database] lore_graph_slice failed — empty | "
                           "chat=%s", chat_id, exc_info=True)
            return dict(empty)

    async def lore_dense_dialogs(self, chat_id: int, match_query: str, *,
                                 max_dialogs: int = 3,
                                 window_minutes: int = 30,
                                 since_ts: int = 0,
                                 max_scan: int = 300,
                                 max_window_rows: int = 60) -> dict:
        """Шаг Б «Летописца» (T-1889): хронология упоминаний топика.

        FTS-совпадения ``smart_messages`` → ``earliest``/``latest``/``total``
        (точный COUNT) → жадное бакетирование по ``window_minutes`` → топ-N
        бакетов по плотности совпадений (тай-брейк — раннее окно) → ПОЛНЫЙ
        текст окна **строго ASC** (``timestamp, id``).

        ``since_ts>0`` — UPD-режим: только новые сообщения ``ts > since_ts``.
        Возврат ``{"earliest", "latest", "total", "dialogs": [[row, ...], ...]}``
        (окна — ASC по началу). НЕ бросает: ошибка → пустая структура."""
        empty = {"earliest": None, "latest": None, "total": 0, "dialogs": []}
        match = str(match_query or "").strip()
        if not match:
            return dict(empty)
        try:
            since = int(since_ts or 0)
            sql_count = (
                "SELECT COUNT(*) AS cnt, MIN(m.timestamp) AS first_ts, "
                "MAX(m.timestamp) AS last_ts FROM smart_messages m "
                "WHERE m.chat_id = ? AND m.id IN "
                "(SELECT rowid FROM smart_messages_fts "
                "WHERE smart_messages_fts MATCH ?)")
            params: list = [chat_id, match]
            if since:
                sql_count += " AND m.timestamp > ?"
                params.append(since)
            cursor = await self.db.execute(sql_count, tuple(params))
            row = await cursor.fetchone()
            total = int(row["cnt"] or 0) if row else 0
            earliest = row["first_ts"] if row else None
            latest = row["last_ts"] if row else None
            if not total:
                return dict(empty)
            sql = ("SELECT m.id, m.timestamp FROM smart_messages m "
                   "WHERE m.chat_id = ? AND m.id IN "
                   "(SELECT rowid FROM smart_messages_fts "
                   "WHERE smart_messages_fts MATCH ?)")
            params = [chat_id, match]
            if since:
                sql += " AND m.timestamp > ?"
                params.append(since)
            sql += " ORDER BY m.timestamp ASC, m.id ASC LIMIT ?"
            params.append(max(1, int(max_scan)))
            cursor = await self.db.execute(sql, tuple(params))
            hits = [int(r["timestamp"] or 0) for r in await cursor.fetchall()]
            if not hits:
                return {"earliest": earliest, "latest": latest, "total": total,
                        "dialogs": []}
            window = max(1, int(window_minutes)) * 60
            buckets: list[tuple[int, int, int]] = []
            start: int | None = None
            end = 0
            count = 0
            for ts in hits:
                if start is None:
                    start, end, count = ts, ts + window, 1
                elif ts <= end:
                    count += 1
                else:
                    buckets.append((start, end, count))
                    start, end, count = ts, ts + window, 1
            if start is not None:
                buckets.append((start, end, count))
            top = sorted(buckets, key=lambda b: (-b[2], b[0]))[
                :max(1, int(max_dialogs))]
            top.sort(key=lambda b: b[0])
            dialogs: list[list[dict]] = []
            for win_start, win_end, _cnt in top:
                cursor = await self.db.execute(
                    "SELECT id, user_id, author_name, text, timestamp, "
                    "media_type, is_forward, forward_source, tg_message_id "
                    "FROM smart_messages WHERE chat_id = ? AND timestamp >= ? "
                    "AND timestamp <= ? ORDER BY timestamp ASC, id ASC LIMIT ?",
                    (chat_id, win_start, win_end, max(1, int(max_window_rows))))
                dialogs.append([dict(r) for r in await cursor.fetchall()])
            return {"earliest": earliest, "latest": latest, "total": total,
                    "dialogs": dialogs}
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[database] lore_dense_dialogs failed — empty | "
                           "chat=%s", chat_id, exc_info=True)
            return dict(empty)

    async def search_archive_fts(self, chat_id: int, match_query: str, limit: int) -> list[str]:
        """L3 фоллбек: FTS5 search over archive facts, ordered by rank."""
        cursor = await self.db.execute(
            "SELECT f.fact FROM smart_archive_facts_fts "
            "JOIN smart_archive_facts f ON f.id = smart_archive_facts_fts.rowid "
            "WHERE smart_archive_facts_fts MATCH ? AND f.chat_id = ? "
            "ORDER BY smart_archive_facts_fts.rank LIMIT ?",
            (match_query, chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def get_smart_chat_ids(self) -> list[int]:
        """Distinct chat ids that have at least one saved message."""
        cursor = await self.db.execute("SELECT DISTINCT chat_id FROM smart_messages")
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]

    # ── GraphRAG: nodes/edges (Epic 26, Section 35.2) ───────

    async def upsert_node(self, chat_id: int, entity_name: str, entity_type: str,
                          origin: str = "chat_history", expires_at=None,
                          commit: bool = True) -> int:
        """INSERT OR IGNORE (ключ chat_id+entity_name): существующий узел сохраняет
        СВОЙ тип/origin (не перезаписывается); новые получают origin/expires_at.

        Раунд 10.24 (F1, ADR-1024-6 D3): `commit=False` — запись остаётся в
        текущей транзакции вызывающего (атомарная фаза B graph-extract);
        дефолт True сохраняет поведение всех прочих вызовов.

        B-MCA01-1 (D3): при `commit=True` — общий механизм
        (`write_transaction`, single-writer + retry); при `commit=False`
        транзакцией владеет ВЫЗЫВАЮЩИЙ (обязан держать `serialized()`/
        `write_transaction` — иначе открытая транзакция утекла бы на общую
        connection)."""
        async def _body(conn):
            await conn.execute(
                "INSERT OR IGNORE INTO nodes (chat_id, entity_name, "
                "entity_type, origin, expires_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, entity_name, entity_type, origin, expires_at),
            )
            cursor = await conn.execute(
                "SELECT id FROM nodes WHERE chat_id = ? AND entity_name = ?",
                (chat_id, entity_name),
            )
            row = await cursor.fetchone()
            return row["id"]

        if not commit:
            _require_write_owner(self, "upsert_node")
            return await _body(self.db)
        return await self.write_transaction(_body, op_name="upsert_node")

    @_serialized_write
    async def upsert_edge(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        weight_increment: int = 1,
        origin: str = "chat_history",
        expires_at=None,
        fact_id: int | None = None,
        commit: bool = True,
    ) -> None:
        """Merge a graph edge; duplicate (source,target,relation) bumps weight (D70).

        chat_id is taken from the source node (both nodes always belong to the
        same chat by construction). One statement → atomic. Epic 46 (55.3):
        origin/expires_at записываются. Epic 60 (66.3, T-481): подтверждение
        связи — +инкремент с cap 5 (T-459 тема 5: «+1 cap 5»), last_updated =
        CURRENT_TIMESTAMP (сброс затухания).

        Раунд 10.18 (F3, ADR-1018-3 D1): `fact_id` — provenance ребра →
        `graph_facts.id` (скоринг Σ importance). Дефолт None сохраняет ВСЕ
        существующие вызовы (cron `_extract_and_save_graph` — осознанный NULL).
        При конфликте `fact_id = COALESCE(excluded.fact_id, edges.fact_id)`:
        новый точный факт перезаписывает NULL-legacy, но НЕ затирается NULL-ом.

        B3-5 (атомарность fact+edge): `commit=False` оставляет запись в текущей
        транзакции — вызывающий (`_memorize_facts_inner`) коммитит пару
        `insert_graph_fact`+`upsert_edge` ОДНИМ commit и откатывает при сбое
        второго шага. Дефолт True — поведение всех прочих вызовов неизменно.

        B-MCA01-1 (D3): при `commit=True` — `write_transaction`
        (single-writer); при `commit=False` транзакцией владеет ВЫЗЫВАЮЩИЙ."""
        async def _body(conn):
            cursor = await conn.execute(
                "INSERT INTO edges (chat_id, source_id, target_id, "
                "relation_type, weight, origin, expires_at, fact_id) "
                "SELECT chat_id, ?, ?, ?, ?, ?, ?, ? FROM nodes WHERE id = ? "
                "ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET "
                "weight = MIN(weight + excluded.weight, ?), "
                "last_updated = CURRENT_TIMESTAMP, "
                "fact_id = COALESCE(excluded.fact_id, edges.fact_id)",
                (source_id, target_id, relation_type, weight_increment, origin,
                 expires_at, fact_id, source_id, _EDGE_WEIGHT_CAP),
            )
            # S10.18-33: `INSERT … SELECT … FROM nodes WHERE id = ?` при
            # отсутствующем узле-источнике вставляет 0 строк — факт мог остаться
            # закоммиченным без ребра. Fail-open: WARNING (транзакцию не ломаем —
            # вызывающий сам коммитит/откатывает пару fact+edge, B3-5).
            if cursor.rowcount == 0:
                logger.warning(
                    "[database] upsert_edge: source node id=%s not found — edge "
                    "NOT written (fail-open) | target_id=%s | relation=%s",
                    source_id, target_id, relation_type)

        if not commit:
            _require_write_owner(self, "upsert_edge")
            return await _body(self.db)
        return await self.write_transaction(_body, op_name="upsert_edge")

    async def match_nodes(
        self, chat_id: int, user_names: list[str], topic_keywords: list[str]
    ) -> list[int]:
        """Node ids matched by exact user names or topic substring LIKE (35.5).
        Epic 50 (58.8): сущности origin='bot_direct_reply' в /summary-справки
        НЕ попадают (R26-3-фильтр от direct-диалогов)."""
        conditions = []
        params: list = []
        if user_names:
            placeholders = ",".join("?" for _ in user_names)
            conditions.append(f"(entity_type = 'user' AND entity_name IN ({placeholders}))")
            params.extend(user_names)
        if topic_keywords:
            like_clauses = " OR ".join("entity_name LIKE ?" for _ in topic_keywords)
            conditions.append(f"(entity_type = 'topic' AND ({like_clauses}))")
            params.extend(f"%{kw}%" for kw in topic_keywords)
        if not conditions:
            return []
        sql = ("SELECT id FROM nodes WHERE chat_id = ? AND origin != 'bot_direct_reply' AND ("
               + " OR ".join(conditions) + ")")
        cursor = await self.db.execute(sql, [chat_id, *params])
        rows = await cursor.fetchall()
        return [row["id"] for row in rows]

    async def get_top_edges(self, chat_id: int, entity_ids: list[int], limit: int) -> list:
        """Top edges incident to any of entity_ids, weight DESC (35.5).
        Epic 50 (58.8): фильтр origin='bot_direct_reply' (рёбра и оба конца)."""
        if not entity_ids:
            return []
        placeholders = ",".join("?" for _ in entity_ids)
        cursor = await self.db.execute(
            "SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, "
            "e.weight, e.last_updated, "
            "s.entity_name AS source_name, s.entity_type AS source_type, "
            "t.entity_name AS target_name, t.entity_type AS target_type "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            f"WHERE e.chat_id = ? AND (e.source_id IN ({placeholders}) "
            f"OR e.target_id IN ({placeholders})) "
            "AND e.origin != 'bot_direct_reply' "
            "AND s.origin != 'bot_direct_reply' AND t.origin != 'bot_direct_reply' "
            "ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC "
            "LIMIT ?",
            [chat_id, *entity_ids, *entity_ids, limit],
        )
        return await cursor.fetchall()

    async def get_top_edges_all(self, chat_id: int, limit: int) -> list:
        """Chat-wide top edges, weight DESC (cold-graph fallback, 35.5).
        Epic 50 (58.8): фильтр origin='bot_direct_reply' (рёбра и оба конца)."""
        cursor = await self.db.execute(
            "SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, "
            "e.weight, e.last_updated, "
            "s.entity_name AS source_name, s.entity_type AS source_type, "
            "t.entity_name AS target_name, t.entity_type AS target_type "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            "WHERE e.chat_id = ? "
            "AND e.origin != 'bot_direct_reply' "
            "AND s.origin != 'bot_direct_reply' AND t.origin != 'bot_direct_reply' "
            "ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC "
            "LIMIT ?",
            (chat_id, limit),
        )
        return await cursor.fetchall()

    # ── GraphRAG v2 (Epic 46, Section 55.3): graph_facts ─────────

    async def insert_graph_fact(self, chat_id, fact, origin, expires_at,
                                target_user=None, status="confirmed",
                                supersedes=None, weight=None,
                                message_timestamp: int | None = None,
                                or_ignore: bool = False,
                                importance: int | None = None,
                                source_ids: str | None = None,
                                kind: str | None = None,
                                belief_meta: str | None = None,
                                subject: str | None = None,
                                object: str | None = None,
                                commit: bool = True,
                                tg_message_id: int | None = None,
                                forward_from: str = "",
                                subject_ref_id: int | None = None,
                                attribution_method: str | None = None,
                                assertion_kind: str | None = None,
                                speaker_author_id: int | None = None,
                                extractor_version: str | None = None,
                                provenance_channel: str | None = None,
                                dossier_generation_id: str | None = None
                                ) -> int:
        """Факт-строка (+FTS-индекс). Возвращает id. Epic 50 (58.8, D205):
        target_user — имя обращающегося (origin='bot_direct_reply'); created_at
        ставится автоматически (int(time.time())). Epic 60 (64.1/64.2):
        status ('confirmed' default | 'unconfirmed' — зона 0.85–0.95) и
        supersedes (id инвалидированного предшественника). Epic 60 (66.1/66.3,
        T-479/T-481): weight 0..1 (None → 0.5; вне [0,1] — кламп + WARNING),
        last_confirmed_at = created_at (факт рождается подтверждённым).
        Фаза 2 (T-758, spec 3.4): message_timestamp — дата сообщения-источника
        (Graph-воркер истории; origin='history_import'); None для live-вызовов
        (поведение не меняется; рендер COALESCE использует created_at).
        Фаза 2 (T-763, Graph-воркер): or_ignore=True → INSERT OR IGNORE:
        дубль по частичному UNIQUE-индексу idx_graph_facts_history_import
        (chat_id, fact, message_timestamp, origin='history_import') молча
        пропускается → возврат 0 и БЕЗ FTS-строки (FTS5 external content не
        знает о дублях rowid — edge 5 spec; идемпотентность повторных
        прогонов/переноса дельты FR-10). Live-путь (or_ignore=False) —
        ровно прежний INSERT (дубль → IntegrityError, как и раньше).
        Раунд 9 (T-822/T-823, spec §3.3.1/§3.3.2): + колонки v8.
        importance=None → правило rule_importance (никогда не 0 на записи,
        Q8); явный importance — clamp 1..10. kind: None → 'fact'
        ('belief' — только DreamWorker). source_ids — JSON-массив id
        фактов-источников, belief_meta — JSON-метаданные (только beliefs).
        B3-5 (атомарность fact+edge): `commit=False` оставляет строку факта и
        FTS-строку в текущей транзакции — вызывающий (`_memorize_facts_inner`)
        коммитит пару с `upsert_edge(..., commit=False)` ОДНИМ commit.
        Дефолт True — поведение всех прочих вызовов неизменно.
        F5 (T-1744, ADR-1018-5 D2): аддитивные `subject`/`object` — для
        программного хард-лимита importance мета-фактов (стоп-лист
        `METAFACT_PENALTY_STOPLIST` → imp=min(imp,1)); None → прежнее
        поведение (дефолты).
        Раунд 10.20 (БЛОК 7.3b, ADR-1020-1 ред. 3, T-1924): аддитивные
        `tg_message_id`/`forward_from` — provenance факта (ID-политика `tg:`
        и сегмент «Переслано:» в канонической строке). None/'' → прежнее
        поведение (R16: не выдумываем). Существующие вызовы НЕ меняются.
        mca-04b (ADR-1027-9 D8): аддитивный `dossier_generation_id` — тег
        поколения при активации staging (NULL = legacy/честный unknown);
        существующие вызовы НЕ меняются."""
        w = 0.5 if weight is None else float(weight)
        if not 0.0 <= w <= 1.0:
            logger.warning("graph fact weight %s outside [0,1] — clamped (66.1)", w)
            w = min(1.0, max(0.0, w))
        imp = (rule_importance(origin, str(fact or "")) if importance is None
               else max(1, min(10, int(importance))))
        # F5 (T-1744, ADR-1018-5 D2/D3): программный хард-лимит мета-фактов.
        # Если нормализованный subject ИЛИ object строго равен слову
        # METAFACT_PENALTY_STOPLIST («видеосообщение/голосовое/фото/кружочек/
        # ссылка/стикер») → importance = min(imp, 1), независимо от
        # rule_importance()/LLM. Мета-факты СОХРАНЯЮТСЯ (не удаляются), но не
        # проходят гейты Сна и не доминируют в RAG. subject/object=None (крон,
        # direct-reply) → срез не применяется (осознанное ограничение, D2).
        if is_metafact_stopword(subject) or is_metafact_stopword(object):
            imp = min(imp, METAFACT_PENALTY_IMPORTANCE)
        k = "belief" if kind == "belief" else "fact"
        now = int(time.time())
        insert_sql = (
            "INSERT OR IGNORE INTO graph_facts "
            if or_ignore else
            "INSERT INTO graph_facts ")
        _insert_args = (chat_id, fact, origin, expires_at, now, target_user,
                        status, supersedes, w, now, message_timestamp, imp, k,
                        source_ids, belief_meta, tg_message_id,
                        str(forward_from or ""),
                        subject_ref_id, attribution_method, assertion_kind,
                        speaker_author_id, extractor_version,
                        provenance_channel, dossier_generation_id)

        async def _body(conn):
            cursor = await conn.execute(
                insert_sql +
                "(chat_id, fact, origin, expires_at, created_at, "
                "target_user, status, supersedes, weight, last_confirmed_at, "
                "message_timestamp, importance, kind, source_ids, belief_meta, "
                "tg_message_id, forward_from, subject_ref_id, "
                "attribution_method, assertion_kind, speaker_author_id, "
                "extractor_version, provenance_channel, "
                "dossier_generation_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?)",
                _insert_args)
            if cursor.rowcount == 0:
                # дубль (INSERT OR IGNORE) — FTS-строку НЕ пишем (edge 5),
                # коммитить нечего
                return 0
            fid = cursor.lastrowid
            await conn.execute(
                "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
                (fid, fact))
            return fid

        if not commit:
            # B3-5 (атомарность fact+edge): вызывающий коммитит пару сам —
            # обёртку write_transaction НЕ применяем (её commit сломал бы пару).
            return await _body(self.db)
        # F0.5: сериализация + bounded retry (одна логическая транзакция).
        return await self.write_transaction(
            _body, op_name="insert_graph_fact", chat_id=chat_id)

    # ── Раунд 9 (AGI Memory, spec §3.4, T-824/T-825): «сон» (DreamWorker) ──
    # Watermark/аудит-таблицы — dream_state/memory_dream_log (CREATE IF NOT
    # EXISTS в _SCHEMA_SQL). Короткие транзакции, одно соединение WAL.
    # Всё состояние per chat_id (NFR-3); глобальные суточные бюджеты —
    # агрегатами по memory_dream_log за local-сутки (§3.4.4).

    async def get_dream_state(self, chat_id: int) -> dict | None:
        """Watermark-строка чата (dream_state) или None (тик ещё не был)."""
        cursor = await self.db.execute(
            "SELECT chat_id, last_run_at, last_processed_fact_id "
            "FROM dream_state WHERE chat_id = ?", (chat_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    @_serialized_write
    async def set_dream_state(self, chat_id: int, *, last_run_at: int,
                              last_processed_fact_id: int) -> None:
        """UPSERT watermark «сна» чата (конец успешного тик-батча, §3.4.2)."""
        await self.db.execute(
            "INSERT INTO dream_state (chat_id, last_run_at, last_processed_fact_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "last_run_at = excluded.last_run_at, "
            "last_processed_fact_id = excluded.last_processed_fact_id",
            (chat_id, int(last_run_at), int(last_processed_fact_id)))
        await self.db.commit()

    async def get_dream_candidate_chats(self, now_ts: int, *, origins,
                                        initial_window_hours: int,
                                        min_new_facts: int, max_chats: int,
                                        quiet_after_ts: int | None = None
                                        ) -> list[dict]:
        """Чаты-кандидаты тика (Q9/§3.4.2): новые confirmed kind='fact'
        (id > watermark для чатов со строкой dream_state; created_at в окне
        прогрева — для чатов БЕЗ строки), новых ≥ min_new_facts; сортировка
        по числу новых DESC, лимит max_chats. quiet_after_ts — «не пик»:
        чат с сообщениями в окне тишины исключается (smart_messages)."""
        in_origins = ",".join("?" * len(origins))
        sql = (
            "SELECT f.chat_id AS chat_id, COUNT(*) AS new_count, "
            "MAX(f.id) AS max_fact_id FROM graph_facts f "
            "LEFT JOIN dream_state ds ON ds.chat_id = f.chat_id "
            "WHERE f.status = 'confirmed' AND f.kind = 'fact' "
            f"AND f.origin IN ({in_origins}) "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) "
            "AND ((ds.chat_id IS NOT NULL "
            "AND f.id > ds.last_processed_fact_id) "
            "OR (ds.chat_id IS NULL AND f.created_at >= ?)) "
        )
        params: list = [*origins, now_ts,
                        now_ts - int(initial_window_hours) * 3600]
        if quiet_after_ts is not None:
            sql += ("AND NOT EXISTS (SELECT 1 FROM smart_messages s "
                    "WHERE s.chat_id = f.chat_id AND s.timestamp >= ?) ")
            params.append(int(quiet_after_ts))
        sql += ("GROUP BY f.chat_id HAVING COUNT(*) >= ? "
                "ORDER BY new_count DESC, f.chat_id ASC LIMIT ?")
        params.extend([int(min_new_facts), int(max_chats)])
        cursor = await self.db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]

    async def get_dream_candidates(self, chat_id: int, now_ts: int, *,
                                   origins, since_id: int = 0,
                                   since_ts: int | None = None,
                                   limit: int = 1000) -> list:
        """Кандидаты чата: confirmed kind='fact' живые в списке origins,
        id ASC. since_id>0 → новые после watermark (id > since_id); иначе —
        created_at >= since_ts (окно прогрева первого «сна», §3.4.2).
        Лимит строк — потолок одного тик-батча чата (хвост доберёт
        следующий тик: watermark двигается до MAX обработанного)."""
        in_origins = ",".join("?" * len(origins))
        sql = (
            "SELECT id, fact, origin, created_at, message_timestamp, "
            "importance, weight FROM graph_facts "
            "WHERE chat_id = ? AND status = 'confirmed' AND kind = 'fact' "
            f"AND origin IN ({in_origins}) "
            "AND (expires_at IS NULL OR expires_at > ?) "
        )
        params: list = [chat_id, *origins, now_ts]
        if since_id and int(since_id) > 0:
            sql += "AND id > ? "
            params.append(int(since_id))
        else:
            sql += "AND created_at >= ? "
            params.append(int(since_ts or 0))
        sql += "ORDER BY id ASC LIMIT ?"
        params.append(int(limit))
        cursor = await self.db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]

    # ── Раунд 9 (фикс-раунд, spec §3.2.1 п.4/major-2): имена из графа ─────
    # Источник ИМЁН для FTS dig_into_lore: BFS по nodes/edges (имена людей/
    # тем из графа знаний) + фолбэк target_user фактов. Best-effort:
    # методы НЕ бросают (пусто при ошибке/пустом графе).

    async def dig_graph_related_names(self, chat_id: int, seed_terms,
                                      *, max_depth: int = 2,
                                      cap: int = 40) -> list[str]:
        """BFS по рёбрам графа от узлов, чьи entity_name (casefold) содержат
        токен из seed_terms (len >= 4): возвращает имена узлов уровней 0..N
        (N = max_depth, hop = одно ребро), до cap имён. Пусто — узлы/рёбра
        не найдены. НЕ бросает (любая ошибка → [])."""
        seeds = sorted({str(t).casefold().strip()
                        for t in (seed_terms or [])
                        if len(str(t).strip()) >= 4})
        if not seeds or int(max_depth) < 1:
            return []
        try:
            like = " OR ".join("entity_name LIKE ?" for _ in seeds)
            cursor = await self.db.execute(
                "SELECT id, entity_name FROM nodes WHERE chat_id = ? AND "
                f"({like}) LIMIT ?",
                [chat_id] + [f"%{s}%" for s in seeds] + [int(cap)])
            start_rows = [dict(row) for row in await cursor.fetchall()]
            if not start_rows:
                return []
            names: list[str] = []
            seen_ids: set[int] = set()
            for row in start_rows:
                name = str(row.get("entity_name") or "").strip()
                if name and name not in names:
                    names.append(name)
                seen_ids.add(int(row["id"]))
            layer_ids = {int(r["id"]) for r in start_rows}
            for _ in range(min(int(max_depth), 5)):
                if not layer_ids:
                    break
                if len(names) >= int(cap):
                    break
                placeholders = ",".join("?" * len(layer_ids))
                cursor = await self.db.execute(
                    "SELECT e.target_id AS nid, n.entity_name AS ename "
                    "FROM edges e JOIN nodes n ON n.id = e.target_id "
                    "WHERE e.chat_id = ? AND e.source_id IN (" +
                    placeholders + ") AND n.entity_name IS NOT NULL "
                    "AND n.entity_name != '' LIMIT ?",
                    [chat_id] + sorted(layer_ids) + [int(cap)])
                rows = await cursor.fetchall()
                next_ids: set[int] = set()
                for row in rows:
                    nid = int(row["nid"])
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)
                    next_ids.add(nid)
                    name = str(row["ename"] or "").strip()
                    if name and name not in names:
                        names.append(name)
                    if len(names) >= int(cap):
                        break
                layer_ids = next_ids
            return names
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[database] dig_graph_related_names failed — empty | "
                "chat=%s", chat_id, exc_info=True)
            return []

    async def dig_fallback_target_names(self, chat_id: int, seed_terms,
                                        cap: int = 300) -> list[str]:
        """Фолбэк spec п.4: DISTINCT target_user фактов чата (confirmed,
        непустые), чьи имена (casefold) содержат токен из seed_terms.
        Best-effort — ошибка/пусто → []."""
        seeds = {str(t).casefold().strip()
                 for t in (seed_terms or []) if str(t).strip()}
        if not seeds:
            return []
        try:
            cursor = await self.db.execute(
                "SELECT DISTINCT target_user FROM graph_facts "
                "WHERE chat_id = ? AND status = 'confirmed' "
                "AND target_user IS NOT NULL AND length(target_user) > 1 "
                "LIMIT ?", (chat_id, int(cap)))
            rows = await cursor.fetchall()
            out: list[str] = []
            for row in rows:
                name = str(row["target_user"] or "").strip()
                low = name.casefold()
                if any(s in low for s in seeds) and name not in out:
                    out.append(name)
            return out
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[database] dig_fallback_target_names failed — empty | "
                "chat=%s", chat_id, exc_info=True)
            return []

    async def get_chat_protected_texts(self, chat_id: int) -> list[str]:
        """Тексты protected_facts чата (chat-level user_name NULL + per-user) —
        гейт protected-семантики кандидатов «сна» (§3.4.3; до 500 текстов)."""
        cursor = await self.db.execute(
            "SELECT fact FROM protected_facts WHERE chat_id = ?", (chat_id,))
        return [str(row["fact"] or "") for row in await cursor.fetchall()]

    @_serialized_write
    async def log_dream_event(self, chat_id: int, run_at: int, *, kind: str,
                              cluster_id: int | None = None,
                              source_ids: str | None = None,
                              belief_id: int | None = None,
                              tokens: int = 0,
                              status: str | None = None) -> int:
        """Строка аудита memory_dream_log (D-13/§3.4.6). kind: 'run' на
        тик-чат; 'distilled'/'skipped'/'error' на попытку дистилляции."""
        cursor = await self.db.execute(
            "INSERT INTO memory_dream_log "
            "(chat_id, run_at, kind, cluster_id, source_ids, belief_id, "
            "tokens, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, int(run_at), kind, cluster_id, source_ids, belief_id,
             int(tokens or 0), status))
        await self.db.commit()
        return cursor.lastrowid

    async def count_dream_log(self, since_ts: int, *, kind: str,
                              chat_id: int | None = None) -> int:
        """Счётчик строк лога за local-сутки (суточный бюджет §3.4.4:
        дистилляции считаются по kind='distilled').

        F7/S10.18-1: `chat_id` — per-chat учёт расхода (None — глобально, как
        раньше). Схема `memory_dream_log` уже содержит `chat_id` — DDL не
        нужен; глобальное событие decay пишется с `chat_id=0` и в per-chat
        бюджет дистилляций не попадает (другой kind)."""
        sql = ("SELECT COUNT(*) AS c FROM memory_dream_log "
               "WHERE kind = ? AND run_at >= ?")
        params: list = [kind, int(since_ts)]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def sum_dream_log_tokens(self, since_ts: int,
                                   kind: str | None = None,
                                   *, chat_id: int | None = None) -> int:
        """Оценка токенов за local-сутки (денежный бюджет §3.4.4): сумма
        memory_dream_log.tokens (max(1, len/4) промпта+ответа). F3/T-1438:
        опциональный `kind` — суточный токен-кап глубокого сна считается
        только по строкам kind='deep_run' (без смешения с обычным сном).

        F7/S10.18-1: `chat_id` — per-chat сумма токенов (None — глобально)."""
        sql = ("SELECT COALESCE(SUM(tokens), 0) AS s FROM memory_dream_log "
               "WHERE run_at >= ?")
        params: list = [int(since_ts)]
        if kind:
            sql += " AND kind = ?"
            params.append(str(kind))
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["s"]) if row else 0

    async def list_beliefs_for_supersede(self, chat_id: int,
                                         limit: int = 20) -> list:
        """Живые beliefs чата для supersede-поиска (§3.4.6/D-6): kind='belief',
        confirmed, supersedes IS NULL; свежие первыми (created_at DESC)."""
        cursor = await self.db.execute(
            "SELECT id, fact FROM graph_facts "
            "WHERE chat_id = ? AND kind = 'belief' AND status = 'confirmed' "
            "AND supersedes IS NULL "
            "ORDER BY created_at DESC, id DESC LIMIT ?", (chat_id, limit))
        return await cursor.fetchall()

    @_serialized_write
    async def mark_belief_superseded(self, old_id: int, new_id: int) -> None:
        """Новый belief заменил старый того же чата/темы (D-6): старый
        остаётся (status не меняется — RAG ранжит), supersedes фиксирует
        замену (spec §3.4.6)."""
        await self.db.execute(
            "UPDATE graph_facts SET supersedes = ? WHERE id = ?",
            (int(new_id), int(old_id)))
        await self.db.commit()

    # ── F2 (cognition-belief-decay, spec §2/§4): decay + resurrection ───────
    # Модель: archived_belief — значение существующей колонки status (CHECK
    # отсутствует), БЕЗ DDL; base_weight/archived_at/decay_months/
    # last_reinforced_fact_id/resurrected_at/resurrections — JSON belief_meta.

    _BELIEF_COLS = ("id, chat_id, fact, origin, status, weight, "
                    "last_confirmed_at, message_timestamp, created_at, "
                    "target_user, belief_meta")

    @staticmethod
    def _parse_belief_meta(raw) -> dict:
        """belief_meta (JSON-строка/None) → dict (битое → {}, fail-open).

        S10.13-13: делегирует единому `parse_belief_meta` (модульный хелпер),
        сохранён как тонкая обёртка для обратной совместимости вызовов."""
        return parse_belief_meta(raw)

    async def list_confirmed_beliefs(self, chat_id: int | None = None,
                                     limit: int = 1000) -> list[dict]:
        """Активные beliefs (kind='belief', status='confirmed') — кандидаты
        декай-шага (F2/T-1425). chat_id None → все чаты.

        S10.13-3: F3-парадигмы (marker `belief_meta.type='paradigm'`) исключены
        из отбора — «вечный» исторический слой не охлаждается общей формулой
        (spec F3 §2). Обычные beliefs тоже пишутся `origin='derived_belief'`,
        поэтому различаем только по JSON-маркеру (не по origin)."""
        marker = '%"type":"paradigm"%'
        marker_spaced = '%"type": "paradigm"%'
        sql = (f"SELECT {self._BELIEF_COLS} FROM graph_facts "
               "WHERE kind = 'belief' AND status = 'confirmed' "
               "AND (belief_meta IS NULL OR (belief_meta NOT LIKE ? "
               "AND belief_meta NOT LIKE ?)) ")
        params: list = [marker, marker_spaced]
        if chat_id is not None:
            sql += "AND chat_id = ? "
            params.append(int(chat_id))
        sql += "ORDER BY id ASC LIMIT ?"
        params.append(int(limit))
        cursor = await self.db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]

    async def list_archived_beliefs(self, chat_id: int | None = None,
                                    limit: int = 200) -> list[dict]:
        """Архивные beliefs (status='archived_belief') чата/всех — источник
        резонанса/реаниматора/граф-активации (F2/T-1427…T-1429)."""
        sql = (f"SELECT {self._BELIEF_COLS} FROM graph_facts "
               "WHERE kind = 'belief' AND status = 'archived_belief' ")
        params: list = []
        if chat_id is not None:
            sql += "AND chat_id = ? "
            params.append(int(chat_id))
        sql += "ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        cursor = await self.db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]

    async def list_new_confirmed_facts(self, chat_id: int, since_id: int,
                                       now_ts: int | None = None,
                                       limit: int = 500) -> list[dict]:
        """Новые сырые факты чата (kind='fact', status='confirmed', живые,
        id > since_id) — кандидаты «подкрепления» belief (F2/T-1425, §2):
        фильтр по якорному токену делает вызывающий в Python.
        Раунд 10.14 (F1, ADR-1014-2 D6): self-факты исключены по origin."""
        now = int(now_ts if now_ts is not None else time.time())
        cursor = await self.db.execute(
            "SELECT id, fact FROM graph_facts "
            "WHERE chat_id = ? AND kind = 'fact' AND status = 'confirmed' "
            "AND origin != 'bot_self_reply' "
            "AND id > ? AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY id ASC LIMIT ?",
            (int(chat_id), int(since_id), now, int(limit)))
        return [dict(r) for r in await cursor.fetchall()]

    @_serialized_write
    async def set_belief_status(self, belief_id: int, status: str, *,
                                weight: float | None = None,
                                last_confirmed_at: int | None = None,
                                belief_meta_patch: dict | None = None) -> bool:
        """Обновление статуса belief + опционально веса/даты/патча
        belief_meta (merge с текущим JSON). True — строка обновлена.
        Единая точка декай-архива/восстановления (F2, БЕЗ DDL)."""
        sets = ["status = ?"]
        params: list = [str(status)]
        if weight is not None:
            sets.append("weight = ?")
            params.append(max(0.0, min(1.0, float(weight))))
        if last_confirmed_at is not None:
            sets.append("last_confirmed_at = ?")
            params.append(int(last_confirmed_at))
        if belief_meta_patch:
            cursor = await self.db.execute(
                "SELECT belief_meta FROM graph_facts WHERE id = ? AND "
                "kind = 'belief'", (int(belief_id),))
            row = await cursor.fetchone()
            if row is None:
                return False
            meta = self._parse_belief_meta(row["belief_meta"])
            meta.update(belief_meta_patch)
            sets.append("belief_meta = ?")
            params.append(json.dumps(meta, ensure_ascii=False))
        params.append(int(belief_id))
        cursor = await self.db.execute(
            f"UPDATE graph_facts SET {', '.join(sets)} "
            "WHERE id = ? AND kind = 'belief'", params)
        await self.db.commit()
        return bool(cursor.rowcount)

    async def reinforce_belief(self, belief_id: int, weight: float,
                               now_ts: int, last_fact_id: int) -> bool:
        """Подкрепление belief новым сырым фактом (F2/T-1425, §2):
        last_confirmed_at=now, weight=base, belief_meta.last_reinforced_fact_id
        = max(id фактов)."""
        return await self.set_belief_status(
            belief_id, "confirmed", weight=weight, last_confirmed_at=now_ts,
            belief_meta_patch={"last_reinforced_fact_id": int(last_fact_id)})

    async def resurrect_belief(self, belief_id: int, weight: float,
                               now_ts: int) -> bool:
        """Воскрешение архивного belief (F2/T-1427/T-1428, §4.2/§4.3):
        status='confirmed', weight=base, last_confirmed_at=now,
        belief_meta.resurrected_at=now + resurrections+=1 (счётчик телеметрии).
        Дату события архива (archived_at) сохраняем — история."""
        cursor = await self.db.execute(
            "SELECT belief_meta FROM graph_facts WHERE id = ? AND "
            "kind = 'belief'", (int(belief_id),))
        row = await cursor.fetchone()
        if row is None:
            return False
        meta = self._parse_belief_meta(row["belief_meta"])
        meta["resurrected_at"] = int(now_ts)
        meta["resurrections"] = int(meta.get("resurrections") or 0) + 1
        return await self.set_belief_status(
            belief_id, "confirmed", weight=weight, last_confirmed_at=now_ts,
            belief_meta_patch=meta)

    async def count_beliefs_by_status(self) -> dict:
        """Счётчики beliefs по статусу (телеметрия F2/T-1430): все kind=
        'belief' (включая legacy unconfirmed), КРОМЕ F3-парадигм — у них
        отдельная телеметрия (`count_paradigms`), иначе «активные убеждения»
        завышены (S10.13-3/-6)."""
        cursor = await self.db.execute(
            "SELECT status, COUNT(*) AS c FROM graph_facts "
            "WHERE kind = 'belief' "
            "AND (belief_meta IS NULL OR (belief_meta NOT LIKE ? "
            "AND belief_meta NOT LIKE ?)) GROUP BY status",
            ('%"type":"paradigm"%', '%"type": "paradigm"%'))
        return {str(r["status"] or ""): int(r["c"])
                for r in await cursor.fetchall()}

    async def last_decay_run(self) -> int | None:
        """run_at последнего прогона декай-шага (kind='decay_run') или None
        — интервальный гейт раз в BELIEF_DECAY_INTERVAL_DAYS (F2/T-1425)."""
        cursor = await self.db.execute(
            "SELECT MAX(run_at) AS ts FROM memory_dream_log "
            "WHERE kind = 'decay_run'")
        row = await cursor.fetchone()
        return int(row["ts"]) if row and row["ts"] is not None else None

    # ── F3 (cognition-deep-sleep, spec §3/§6): маркеры глубокого сна ────────
    # Идемпотентность/cooldown — через memory_dream_log(kind='deep_run'),
    # парадигмы — через belief_meta.type='paradigm' (ноль DDL).

    async def last_deep_run(self, chat_id: int | None = None) -> int | None:
        """run_at последнего УСПЕШНОГО прогона глубокого сна (kind='deep_run').
        chat_id=None → глобальный максимум; задан → по конкретному чату.
        None — прогонов ещё не было (для отображения last_run_at/идемпотентности)."""
        sql = ("SELECT MAX(run_at) AS ts FROM memory_dream_log "
               "WHERE kind = 'deep_run'")
        params: list = []
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["ts"]) if row and row["ts"] is not None else None

    async def last_deep_attempt(self, chat_id: int | None = None) -> int | None:
        """run_at последней ПОПЫТКИ глубокого сна (kind='deep_run' ИЛИ
        'deep_skip') — гейт cooldown (S10.13-2). Скип-прогоны
        (no_anchors/unchanged/duplicate/error/budget_skip) тоже пишут
        `memory_dream_log`, иначе попытки повторяются каждый тик/after_sleep."""
        sql = ("SELECT MAX(run_at) AS ts FROM memory_dream_log "
               "WHERE kind IN ('deep_run', 'deep_skip')")
        params: list = []
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["ts"]) if row and row["ts"] is not None else None

    # Скип-статусы глубокого сна, потратившие LLM-токены (стоимостной учёт).
    _DEEP_SKIP_COST_STATUSES = ("error", "unchanged", "duplicate")

    async def count_deep_attempts(self, since_ts: int, *,
                                  chat_id: int | None = None) -> int:
        """Число стоимостных прогонов глубокого сна за local-сутки (S10.13-2):
        успешные (`deep_run`) + скипы, потратившие токены (`deep_skip` со
        status error/unchanged/duplicate). Пре-LLM скипы no_anchors/budget_skip
        НЕ считаются — они не мешают обходу остальных чатов.

        mca-06 T-4723 (spec §6.1, D9/О3): `chat_id` — per-chat доступность
        (тот же kind/status-набор + `AND chat_id = ?`); None — глобальная
        защита ресурсов (прежнее поведение, паритет 2.58.48 бит-в-бит)."""
        sql = ("SELECT COUNT(*) AS c FROM memory_dream_log "
               "WHERE run_at >= ? AND (kind = 'deep_run' OR "
               "(kind = 'deep_skip' AND status IN (?, ?, ?)))")
        params: list = [int(since_ts)] + list(self._DEEP_SKIP_COST_STATUSES)
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def deep_error_state(self, chat_id: int) -> tuple[int | None, int]:
        """Состояние ошибок глубокого сна чата для ограниченного backoff
        (mca-06 T-4724, spec §6.2).

        Возвращает `(last_error_ts, streak)`: `streak` — число подряд идущих
        (свежих вниз) `deep_skip`/status='error' строк до первой не-error
        попытки; `last_error_ts` — время самой свежей ошибки. Нет ошибок/
        ошибка перекрыта успешной попыткой → `(None, 0)`. Bounded LIMIT 50."""
        cursor = await self.db.execute(
            "SELECT run_at, status FROM memory_dream_log "
            "WHERE chat_id = ? AND kind IN ('deep_run', 'deep_skip') "
            "ORDER BY run_at DESC, id DESC LIMIT 50", (int(chat_id),))
        last_error: int | None = None
        streak = 0
        for row in await cursor.fetchall():
            if str(row["status"] or "") == "error":
                if last_error is None:
                    last_error = int(row["run_at"])
                streak += 1
            else:
                break
        return last_error, streak

    async def latest_dream_data_ts(self, chat_id: int) -> int | None:
        """Время самых свежих dream-кандидатов/эпизодов чата (mca-06 T-4724).

        Сигнал «появились новые данные после последней ошибки» → backoff
        сбрасывается (ограниченный ретрай). Источники — graph_facts источников
        `_DREAM_SOURCE_ORIGINS` и `mca_episodes` (если таблица есть). Fail-open
        → None (нет данных/ошибка)."""
        best: int | None = None
        origins = ("chat_history", "history_import", "bot_direct_reply",
                   "user_memory")
        try:
            placeholders = ",".join("?" for _ in origins)
            cursor = await self.db.execute(
                f"SELECT MAX(created_at) AS m FROM graph_facts "
                f"WHERE chat_id = ? AND origin IN ({placeholders})",
                (int(chat_id), *origins))
            row = await cursor.fetchone()
            if row is not None and row["m"] is not None:
                best = int(row["m"])
        except Exception:
            pass
        try:
            cursor = await self.db.execute(
                "SELECT MAX(discovered_at) AS m FROM mca_episodes "
                "WHERE chat_id = ?", (int(chat_id),))
            row = await cursor.fetchone()
            if row is not None and row["m"] is not None:
                best = max(best, int(row["m"])) if best is not None \
                    else int(row["m"])
        except Exception:
            pass
        return best


    async def count_paradigms(self, chat_id: int | None = None) -> int:
        """Число парадигм глубокого сна (kind='belief' + маркер
        belief_meta.type='paradigm'); chat_id=None → по всей базе. Учитываем
        оба варианта сериализации JSON (компактный и с пробелом после ':')."""
        sql = ("SELECT COUNT(*) AS c FROM graph_facts "
               "WHERE kind = 'belief' AND (belief_meta LIKE ? "
               "OR belief_meta LIKE ?)")
        params: list = ['%"type":"paradigm"%', '%"type": "paradigm"%']
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def list_chat_nodes(self, chat_id: int, limit: int = 100) -> list:
        """Узлы графа чата (id/entity_name) — кандидаты граф-активации
        (F2/T-1429, spec §4.4): matcher имён делает вызывающий в Python."""
        cursor = await self.db.execute(
            "SELECT id, entity_name FROM nodes "
            "WHERE chat_id = ? AND entity_name IS NOT NULL "
            "AND entity_name != '' ORDER BY id ASC LIMIT ?",
            (int(chat_id), int(limit)))
        return [dict(r) for r in await cursor.fetchall()]

    # ── API beliefs/логи (Раунд 9, spec §3.6.2, T-829/F2): read-only
    #    методы для web/api/memory_agi.py + мягкое удаление (D-7) ─────────

    async def list_recent_beliefs(self, chat_id: int | None = None,
                                   limit: int = 50,
                                   status: str | None = None,
                                   belief_type: str | None = None) -> list:
        """Последние beliefs (kind='belief', DESC по id) для TMA «Синтез
        (сон)» (spec §3.6.2). chat_id=None → все чаты; v8-колонки
        importance/source_ids/belief_meta в SELECT (парсит API).
        F2/T-1430 (spec §3): status=None → без фильтра (дашборд видит архив);
        status='confirmed'|'archived_belief' → только этот статус.
        F3/T-1438 (spec §2): belief_type — 'paradigm' (мета-факты глубокого
        сна, belief_meta.type='paradigm') | 'belief' (обычные убеждения) |
        None (все kind='belief'); фильтр по JSON-маркеру без DDL."""
        cols = ("id, chat_id, fact, origin, status, supersedes, weight, "
                "importance, source_ids, belief_meta, created_at, "
                "last_confirmed_at")
        where = ["kind = 'belief'"]
        params: list = []
        if chat_id is not None:
            where.append("chat_id = ?")
            params.append(int(chat_id))
        if status:
            where.append("status = ?")
            params.append(str(status))
        marker = '%"type":"paradigm"%'
        marker_spaced = '%"type": "paradigm"%'
        if belief_type == "paradigm":
            where.append("(belief_meta LIKE ? OR belief_meta LIKE ?)")
            params.extend([marker, marker_spaced])
        elif belief_type in ("belief", "non_paradigm"):
            where.append("(belief_meta IS NULL OR (belief_meta NOT LIKE ? "
                         "AND belief_meta NOT LIKE ?))")
            params.extend([marker, marker_spaced])
        sql = ("SELECT " + cols + " FROM graph_facts WHERE "
               + " AND ".join(where) + " ORDER BY id DESC LIMIT ?")
        params.append(int(limit))
        cursor = await self.db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]

    async def get_graph_fact(self, fact_id: int) -> dict | None:
        """Строка graph_facts по id (для beliefs-эндпоинтов: DELETE/protect
        — проверка kind='belief'; 404 при отсутствии)."""
        cursor = await self.db.execute(
            "SELECT id, chat_id, fact, kind, status FROM graph_facts "
            "WHERE id = ?", (int(fact_id),))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    @_serialized_write
    async def soft_delete_belief(self, fact_id: int) -> bool:
        """Мягкое удаление belief (spec §3.4.8/D-7): status='unconfirmed',
        last_confirmed_at=NULL — belief исключается из RAG (status-фильтр
        confirmed везде), вычищается существующим review-воркером.
        Hard-delete не делаем (согласованность FTS5/vec0). True — удалён;
        False — id нет/не belief (404 в API)."""
        cursor = await self.db.execute(
            "UPDATE graph_facts SET status = 'unconfirmed', "
            "last_confirmed_at = NULL WHERE id = ? AND kind = 'belief'",
            (int(fact_id),))
        await self.db.commit()
        return bool(cursor.rowcount)

    @_serialized_write
    async def protect_belief_text(self, chat_id: int, text: str) -> bool:
        """«Сделать protected» (spec §3.4.8): текст belief → protected_facts
        чата (user_name NULL — chat-level, INSERT OR IGNORE на уникальном
        индексе чат-уровня v6). True — строка добавлена; False — уже была.
        Belief остаётся в графе; гейт «сна» (§3.4.3) его больше не тронет."""
        cursor = await self.db.execute(
            "INSERT OR IGNORE INTO protected_facts "
            "(chat_id, user_name, fact, created_at) VALUES (?, NULL, ?, ?)",
            (int(chat_id), str(text), int(time.time())))
        await self.db.commit()
        return bool(cursor.rowcount)

    async def recent_dream_log(self, limit: int = 100,
                               chat_id: int | None = None) -> list:
        """Последние строки memory_dream_log (TMA «последние сны», spec
        §3.6.2): DESC по id; chat_id — фильтр чата (None — все чаты)."""
        if chat_id is None:
            cursor = await self.db.execute(
                "SELECT id, chat_id, run_at, kind, cluster_id, source_ids, "
                "belief_id, tokens, status FROM memory_dream_log "
                "ORDER BY id DESC LIMIT ?", (int(limit),))
        else:
            cursor = await self.db.execute(
                "SELECT id, chat_id, run_at, kind, cluster_id, source_ids, "
                "belief_id, tokens, status FROM memory_dream_log "
                "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                (int(chat_id), int(limit)))
        return [dict(row) for row in await cursor.fetchall()]

    # ── ностальгия (Раунд 9, spec §3.5.2, T-827/E2): nostalgia_log и
    #    SQLite-хелперы условий тика/кандидатов ──────────────────────────

    @_serialized_write
    async def log_nostalgia(self, chat_id: int, ts: int, *, kind: str = "golden",
                            fact_id: int | None = None,
                            status: str = "skipped",
                            meta: str | None = None) -> int:
        """Строка аудита nostalgia_log (§3.5.2): событие «дорогого» шага тика
        (candidate/threshold/llm/send). kind: 'year_back'|'golden'|'none';
        status: 'sent'|'skipped'|'error'; meta — JSON-строка (reason и пр.)."""
        cursor = await self.db.execute(
            "INSERT INTO nostalgia_log "
            "(chat_id, ts, kind, fact_id, status, meta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(chat_id), int(ts), kind, fact_id, status, meta, int(ts)))
        await self.db.commit()
        return cursor.lastrowid

    async def count_nostalgia_sent_since(self, chat_id: int,
                                          since_ts: int) -> int:
        """Счётчик status='sent' чата за период (local-сутки — дневной лимит
        §3.5.3 п.5: лимит тратят ТОЛЬКО отправки)."""
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS c FROM nostalgia_log "
            "WHERE chat_id = ? AND status = 'sent' AND ts >= ?",
            (int(chat_id), int(since_ts)))
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def recent_nostalgia_sent(self, chat_id: int, since_ts: int | None,
                                    limit: int) -> list:
        """Последние status='sent' чата (ts DESC). since_ts=None → по всей
        истории (cooldown §3.5.3 п.4); окно 24 ч — Q14 (неотвеченные)."""
        if since_ts is not None:
            cursor = await self.db.execute(
                "SELECT id, ts, kind, fact_id, status, meta FROM nostalgia_log "
                "WHERE chat_id = ? AND status = 'sent' AND ts >= ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (int(chat_id), int(since_ts), int(limit)))
        else:
            cursor = await self.db.execute(
                "SELECT id, ts, kind, fact_id, status, meta FROM nostalgia_log "
                "WHERE chat_id = ? AND status = 'sent' "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (int(chat_id), int(limit)))
        return await cursor.fetchall()

    async def recent_nostalgia_log(self, chat_id: int | None = None,
                                   limit: int = 100) -> list:
        """Последние строки nostalgia_log ЛЮБЫХ статусов (TMA «последние
        срабатывания», spec §3.6.2): DESC по id; chat_id=None → все чаты.
        meta — JSON-строка (парсит вызывающий)."""
        if chat_id is None:
            cursor = await self.db.execute(
                "SELECT id, chat_id, ts, kind, fact_id, status, meta "
                "FROM nostalgia_log ORDER BY id DESC LIMIT ?",
                (int(limit),))
        else:
            cursor = await self.db.execute(
                "SELECT id, chat_id, ts, kind, fact_id, status, meta "
                "FROM nostalgia_log WHERE chat_id = ? "
                "ORDER BY id DESC LIMIT ?", (int(chat_id), int(limit)))
        return [dict(row) for row in await cursor.fetchall()]

    async def get_last_user_message_ts(self, chat_id: int,
                                       bot_id: int | None) -> int | None:
        """ts последнего ЮЗЕРСКОГО сообщения чата (бот исключён — §3.5.3
        п.7/п.15: бот-строки в smart_messages не пишутся, но фильтр
        обязателен — импорт истории). None → у юзеров истории нет вовсе."""
        cursor = await self.db.execute(
            "SELECT MAX(timestamp) AS ts FROM smart_messages "
            "WHERE chat_id = ? AND user_id IS NOT NULL AND user_id != ?",
            (int(chat_id), int(bot_id or 0)))
        row = await cursor.fetchone()
        if row is None or row["ts"] is None:
            return None
        return int(row["ts"])

    async def count_user_messages_after(self, chat_id: int,
                                        bot_id: int | None,
                                        after_ts: int) -> int:
        """Юзерских сообщений ПОСЛЕ ts (Q14-«отвеченность»: импортированные
        строки user_id NULL и бот-сообщения не считаются)."""
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages "
            "WHERE chat_id = ? AND user_id IS NOT NULL AND user_id != ? "
            "AND timestamp > ?",
            (int(chat_id), int(bot_id or 0), int(after_ts)))
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def get_year_back_messages(self, chat_id: int, ts_from: int,
                                     ts_to: int, center_ts: int,
                                     limit: int = 3) -> list:
        """Кандидаты «N лет назад в этот день» (§3.5.2): smart_messages чата
        с timestamp ∈ [ts_from, ts_to] (год назад ± окно), непустой текст.
        Строки импорта истории (user_id NULL) участвуют — главный источник
        год-назад-контента (edge 7); бот-строки в smart_messages не пишутся
        (observer). Ближайшие к center_ts (abs) — первыми, ≤ limit строк."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, timestamp, author_name "
            "FROM smart_messages "
            "WHERE chat_id = ? AND timestamp BETWEEN ? AND ? "
            "AND text IS NOT NULL AND TRIM(text) != '' "
            "ORDER BY ABS(timestamp - ?) ASC, id ASC LIMIT ?",
            (int(chat_id), int(ts_from), int(ts_to), int(center_ts),
             int(limit)))
        return await cursor.fetchall()

    async def get_recent_user_messages(self, chat_id: int,
                                       bot_id: int | None,
                                       limit: int = 5) -> list:
        """Последние limit ЮЗЕРСКИХ сообщений чата (ts DESC) — «последняя
        тема диалога» для «золотых» кандидатов (§3.5.2). Непустой текст."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, timestamp, author_name "
            "FROM smart_messages "
            "WHERE chat_id = ? AND user_id IS NOT NULL AND user_id != ? "
            "AND text IS NOT NULL AND TRIM(text) != '' "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            (int(chat_id), int(bot_id or 0), int(limit)))
        return await cursor.fetchall()

    async def search_golden_facts_fts(self, chat_id, match_query, limit,
                                      now_ts, *, min_importance,
                                      max_age_ts) -> list:
        """FTS-поиск «золотых» фактов (§3.5.1/E1, §3.5.2/E2): тот же путь,
        что search_graph_facts_fts, но с SQL-фильтром золотых —
        `f.kind='fact'` (beliefs исключены: даты события нет) И
        `f.importance >= min_importance` И
        `COALESCE(f.message_timestamp, f.created_at) < max_age_ts`
        (давность ≥ порога). Отбирает по рангу; importance/kind/ts в SELECT
        для рендера/весов вызывающего. Раунд 10.14 (F1, ADR-1014-2 D6):
        self-факты («золотые» не должны быть собственными словами бота)
        исключены по origin."""
        sql = (
            "SELECT f.id, f.fact, f.origin, f.created_at, f.target_user, "
            "f.weight, f.last_confirmed_at, f.message_timestamp, f.importance, "
            "COALESCE(f.message_timestamp, f.created_at) AS rag_ts "
            "FROM graph_facts_fts "
            "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
            "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) "
            "AND f.status = 'confirmed' AND f.kind = 'fact' "
            "AND f.importance >= ? "
            "AND COALESCE(f.message_timestamp, f.created_at) < ? "
            "AND f.origin != 'bot_direct_reply' "
            "AND f.origin != 'bot_self_reply' "
            "ORDER BY graph_facts_fts.rank LIMIT ?")
        cursor = await self.db.execute(
            sql, (match_query, chat_id, now_ts, int(min_importance),
                  int(max_age_ts), int(limit)))
        return await cursor.fetchall()


    async def search_graph_facts_fts(self, chat_id, match_query, limit, now_ts,
                                     include_direct_reply=False,
                                     include_archived=False,
                                     include_self=False) -> list:
        """FTS-фолбек RAG с ленивым TTL-фильтром (D175). Epic 50 (58.8, D206):
        include_direct_reply=False (default) → origin='bot_direct_reply' НЕ
        подмешивается в чужие пайплайны; + created_at/target_user в SELECT.
        Epic 60 (64.2): статус-фильтр — unconfirmed-факты в RAG НЕ участвуют.
        Epic 60 (66.3, T-481): + weight/last_confirmed_at — время-взвешивание
        (пересортировка по w_eff) происходит в Python (SQL не меняем).
        F2/T-1426 (spec §2): include_archived=True (dig_into_lore — прямое
        копание) → status ∈ ('confirmed','archived_belief'); обычный RAG
        (False) архив не видит.
        Раунд 10.14 (F1, ADR-1014-2 D7): include_self=False (default) →
        origin='bot_self_reply' невидим (Сон/золотые/чужие пайплайны);
        direct-путь передаёт include_self=True (свои прошлые слова с меткой).
        Раунд 10.18 (F5, ADR-1018-5 D7): в SELECT добавлена ``f.importance`` —
        вызывающий (`summary_memory._search_graph_facts`) домножает Python-ранг
        на ``_importance_factor(imp)=0.5+0.05·imp ∈ [0.55,1.0]``, чтобы
        мета-факты (imp=1) не перебивали важные (SQL-порядок по FTS-рангу не
        меняется; множитель накладывается при пересортировке в Python)."""
        statuses = ("('confirmed', 'archived_belief')" if include_archived
                    else "('confirmed')")
        # MCA-22 (ADR-1028-6 D7/C5): SELECT АДДИТИВНО расширен provenance-
        # колонками v17 (subject_ref_id/attribution_method/assertion_kind/
        # speaker_author_id/provenance_channel) — retrieval переносит
        # subject/speaker в RetrievalCandidate (§10); порядок/существующие
        # колонки не меняются (потребители читают по имени).
        sql = (
            "SELECT f.id, f.fact, f.origin, f.created_at, f.target_user, "
            "f.weight, f.last_confirmed_at, f.message_timestamp, f.status, "
            "f.importance, f.tg_message_id, f.forward_from, "
            "f.subject_ref_id, f.attribution_method, f.assertion_kind, "
            "f.speaker_author_id, f.provenance_channel, "
            "COALESCE(f.message_timestamp, f.created_at) AS rag_ts "
            "FROM graph_facts_fts "
            "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
            "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) "
            f"AND f.status IN {statuses} ")
        if not include_direct_reply:
            sql += "AND f.origin != 'bot_direct_reply' "
        if not include_self:
            sql += "AND f.origin != 'bot_self_reply' "
        sql += "ORDER BY graph_facts_fts.rank LIMIT ?"
        cursor = await self.db.execute(sql, (match_query, chat_id, now_ts, limit))
        return await cursor.fetchall()

    async def get_graph_fact_texts(self, fact_ids, status=None) -> list:
        """[(origin, fact, ts), ...] в порядке fact_ids (порядок KNN
        сохраняется). ts = message_timestamp or created_at (фаза 2, T-759:
        дата-рендер COALESCE — импортированные факты с датой сообщения).
        Epic 50 (58.7): + created_at/target_user (только SELECT).
        Epic 60 (64.2): status='confirmed' → unconfirmed исключаются из RAG."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        sql = (f"SELECT id, fact, origin, created_at, target_user, "
               f"message_timestamp FROM graph_facts WHERE id IN ({placeholders})")
        params: list = list(fact_ids)
        if status:
            sql += " AND status = ?"
            params.append(status)
        cursor = await self.db.execute(sql, params)
        by_id = {
            row["id"]: (row["origin"], row["fact"],
                        row["message_timestamp"] or row["created_at"])
            for row in await cursor.fetchall()
        }
        return [by_id[fid] for fid in fact_ids if fid in by_id]

    @_serialized_write
    async def purge_expired_graph_facts(self, chat_id=None) -> int:
        """Опциональный purge (D175, 55.1 #5): edges истёкших узлов → edges с
        истёкшим expires_at → истёкшие nodes → истёкшие graph_facts (+FTS).
        Epic 60 (66.11, T-489): chat_id=None → глобальный проход по всем чатам
        (пересмотр); с chat_id — piggyback 55.1 #5 (без изменений).
        Фаза 2 (T-756, гейт G3): memory.infinite_retention ON → return 0
        без SQL (TTL-факты не удаляются; единая точка — покрывает всех
        вызывающих: compress_and_purge :1930 и memory_maintenance.review).
        Раунд 8 (E3/T-805, spec §3.E3): гейт защиты graph_facts-строк —
        истёкший факт НЕ удаляется, если выполнено хотя бы одно:
          - вес >= limits.graph_purge_protect_weight (default 0.8) — защищает
            user_memory 1.0 и «вечные» origin, не трогая chat_history 0.5 /
            bot_direct_reply 0.7 (веса по _origin_weight);
          - last_confirmed_at свежее limits.graph_purge_protect_days
            (default 3 дня; подтверждение = недавний дедуп-hit);
          - текст факта совпадает с protected_facts (защищённый факт);
          - expires_at IS NULL (вечные — и не кандидаты по условию).
        FTS-строки чистятся тем же предикатом (иначе защищённый факт
        потерял бы поиск). nodes/edges — общий граф без per-fact-атрибуции,
        их expires_at-каскад не меняется."""
        if _infinite_retention_on():
            logger.info(
                "[database] purge_expired_graph_facts skipped — "
                "memory.infinite_retention ON (T-756)")
            return 0
        now = int(time.time())
        protect_weight = float(hot.get(
            "limits.graph_purge_protect_weight",
            settings.GRAPH_PURGE_PROTECT_WEIGHT) or 0.8)
        protect_days = int(hot.get(
            "limits.graph_purge_protect_days",
            settings.GRAPH_PURGE_PROTECT_DAYS) or 0) or 3
        protect_cutoff = now - protect_days * 86400
        chat_filter = "AND e.chat_id = ?" if chat_id is not None else ""
        node_chat = "AND chat_id = ?" if chat_id is not None else ""
        params = (now,) if chat_id is None else (now, chat_id)
        # E3: предикат «факт — кандидат на удаление» (истёкший, слабый,
        # давно не подтверждённый, не защищённый текстом).
        fact_candidate = (
            "expires_at IS NOT NULL AND expires_at <= ? AND "
            "NOT (weight >= ? OR "
            "(last_confirmed_at IS NOT NULL AND last_confirmed_at >= ?) OR "
            "EXISTS (SELECT 1 FROM protected_facts p "
            "WHERE p.chat_id = graph_facts.chat_id AND p.fact = graph_facts.fact))"
        )
        for side in ("source_id", "target_id"):
            await self.db.execute(
                f"DELETE FROM edges WHERE id IN ("
                f"SELECT e.id FROM edges e JOIN nodes n ON n.id = e.{side} "
                f"WHERE n.expires_at IS NOT NULL AND n.expires_at <= ? "
                f"{chat_filter})", params)
        await self.db.execute(
            "DELETE FROM edges WHERE expires_at IS NOT NULL AND expires_at <= ?"
            + node_chat,
            params)
        await self.db.execute(
            "DELETE FROM nodes WHERE expires_at IS NOT NULL AND expires_at <= ?"
            + node_chat,
            params)
        fact_params = (now, protect_weight, protect_cutoff) + \
            (() if chat_id is None else (chat_id,))
        await self.db.execute(
            "DELETE FROM graph_facts_fts WHERE rowid IN "
            f"(SELECT id FROM graph_facts WHERE {fact_candidate}{node_chat})",
            fact_params)
        cursor = await self.db.execute(
            f"DELETE FROM graph_facts WHERE {fact_candidate}{node_chat}",
            fact_params)
        await self.db.commit()
        return cursor.rowcount

    # ── bot_replies (Epic 60, Section 63.1, T-460) ─────────────
    # Персистентный аналог in-memory LRU _bot_replies (TTL 3600с лениво,
    # cap 200 — паттерн TTL+LRU, T-459 тема 8). last_used_at — время записи
    # (write-per-read запрещён: на чтении last_used_at НЕ обновляется — LRU
    # движется только записями, как в старом OrderedDict).

    _BOT_REPLIES_TTL_SECONDS = 3600.0   # 63.1
    _BOT_REPLIES_CAP = 200              # 63.1

    async def upsert_bot_reply(self, chat_id: int, tg_message_id: int,
                               text: str, now: float) -> None:
        """UPSERT текста ответа бота (63.1) + ленивый TTL-sweep + LRU-cap
        (NOT IN … ORDER BY last_used_at DESC LIMIT N — тема 8).

        F0.5: одна логическая транзакция под single-writer + bounded retry."""
        async def _body(conn):
            await conn.execute(
                "DELETE FROM bot_replies WHERE last_used_at < ?",
                (now - self._BOT_REPLIES_TTL_SECONDS,),
            )
            await conn.execute(
                "INSERT INTO bot_replies (chat_id, tg_message_id, text, last_used_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id, tg_message_id) DO UPDATE SET "
                "text = excluded.text, last_used_at = excluded.last_used_at",
                (chat_id, tg_message_id, text, now),
            )
            await conn.execute(
                "DELETE FROM bot_replies WHERE (chat_id, tg_message_id) NOT IN "
                "(SELECT chat_id, tg_message_id FROM bot_replies "
                "ORDER BY last_used_at DESC LIMIT ?)",
                (self._BOT_REPLIES_CAP,),
            )

        await self.write_transaction(
            _body, op_name="upsert_bot_reply", chat_id=chat_id)

    @_serialized_write
    async def get_bot_reply(self, chat_id: int, tg_message_id: int,
                            now: float) -> str | None:
        """Текст ответа бота; None — нет записи. Протухший (> TTL) →
        ленивый DELETE + None (тема 8)."""
        cursor = await self.db.execute(
            "SELECT text, last_used_at FROM bot_replies "
            "WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if now - row["last_used_at"] > self._BOT_REPLIES_TTL_SECONDS:
            await self.db.execute(
                "DELETE FROM bot_replies WHERE chat_id = ? AND tg_message_id = ?",
                (chat_id, tg_message_id),
            )
            await self.db.commit()
            return None
        return row["text"]

    # ── bot_reply_parents (Раунд 8, spec §3.G1/D3, T-800) ─────────
    # Parent-линк «бот-ответ → сообщение, на которое отвечал» — thread-walk
    # продолжает цепочку сквозь бот-сообщения. Тот же TTL/LRU-паттерн, что
    # bot_replies (63.1): ленивый TTL на чтении, cap на записи.

    @_serialized_write
    async def set_bot_reply_parent(self, chat_id: int, tg_message_id: int,
                                   parent_tg_message_id: int | None,
                                   now: float) -> None:
        """Запись parent-линка (UPSERT + TTL-sweep + LRU-cap — паттерн
        upsert_bot_reply). parent=None (edit-путь, родитель неизвестен) →
        no-op: существующая строка линка НЕ перезаписывается (D3/Q9)."""
        if parent_tg_message_id is None:
            return
        await self.db.execute(
            "DELETE FROM bot_reply_parents WHERE last_used_at < ?",
            (now - self._BOT_REPLIES_TTL_SECONDS,),
        )
        await self.db.execute(
            "INSERT INTO bot_reply_parents "
            "(chat_id, tg_message_id, parent_tg_message_id, last_used_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, tg_message_id) DO UPDATE SET "
            "parent_tg_message_id = excluded.parent_tg_message_id, "
            "last_used_at = excluded.last_used_at",
            (chat_id, tg_message_id, parent_tg_message_id, now),
        )
        await self.db.execute(
            "DELETE FROM bot_reply_parents WHERE (chat_id, tg_message_id) NOT IN "
            "(SELECT chat_id, tg_message_id FROM bot_reply_parents "
            "ORDER BY last_used_at DESC LIMIT ?)",
            (self._BOT_REPLIES_CAP,),
        )
        await self.db.commit()

    @_serialized_write
    async def get_bot_reply_parent(self, chat_id: int, tg_message_id: int,
                                   now: float) -> int | None:
        """Parent-сообщение бот-ответа; None — нет линка/протух. Протухший
        (> TTL) → ленивый DELETE + None (паттерн get_bot_reply)."""
        cursor = await self.db.execute(
            "SELECT parent_tg_message_id, last_used_at FROM bot_reply_parents "
            "WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if now - row["last_used_at"] > self._BOT_REPLIES_TTL_SECONDS:
            await self.db.execute(
                "DELETE FROM bot_reply_parents "
                "WHERE chat_id = ? AND tg_message_id = ?",
                (chat_id, tg_message_id),
            )
            await self.db.commit()
            return None
        return row["parent_tg_message_id"]

    # ── Активные участники (Раунд 8, spec §3.C2, T-793) ──────────
    # UserResolutionMap строится не только по окну, но и по активным
    # участникам за limits.chat_map_participants_hours: SQL-агрегат по
    # smart_messages. Существующий индекс idx_smart_messages_chat_ts
    # (chat_id, timestamp) покрывает диапазон; GROUP BY/ORDER по cap ≤ 150 —
    # дешёвый temp b-tree (новый индекс НЕ создаём — RUNTIME WARNING).

    async def get_active_participants(self, chat_id: int, since_ts: int,
                                      cap: int) -> list:
        """Участники чата за период: user_id + MAX(author_name) (последний
        канон-самописей) + счётчик сообщений, ORDER BY cnt DESC, user_id ASC
        (стабильно), LIMIT cap."""
        cursor = await self.db.execute(
            "SELECT user_id, MAX(author_name) AS author_name, COUNT(*) AS cnt "
            "FROM smart_messages "
            "WHERE chat_id = ? AND timestamp >= ? AND user_id IS NOT NULL "
            "GROUP BY user_id ORDER BY cnt DESC, user_id ASC LIMIT ?",
            (chat_id, since_ts, cap),
        )
        return await cursor.fetchall()

    # ── users_meta: отношения (Раунд 9, spec §3.1.1/§3.1.2, T-816/T-817) ──
    # «Считаемое» участника чата. Пересчёт — SQL-агрегаты по smart_messages
    # (образец get_active_participants; покрыт idx_smart_messages_chat_ts) +
    # Python-decay по ts окна; touch — инкремент на сообщение (горячий путь,
    # см. save_smart_message). Единственное соединение WAL, короткие
    # транзакции; метод всегда возвращает число строк.

    async def get_users_meta(self, chat_id: int, user_ids=None,
                             limit: int | None = None) -> list[dict]:
        """Строки users_meta чата (user_ids — фильтр-подмножество);
        ORDER BY last_seen DESC, стабильно по user_id (None last)."""
        params: list = [chat_id]
        sql = "SELECT * FROM users_meta WHERE chat_id = ?"
        if user_ids is not None:
            ids = [int(uid) for uid in user_ids if uid]
            if not ids:
                return []
            sql += " AND user_id IN (%s)" % ",".join("?" * len(ids))
            params.extend(ids)
        sql += " ORDER BY last_seen DESC, user_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cursor = await self.db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]

    async def get_user_meta(self, chat_id: int, user_id: int) -> dict | None:
        """Строка users_meta одного юзера (None — нет записи)."""
        rows = await self.get_users_meta(chat_id, [user_id])
        return rows[0] if rows else None

    @_serialized_write
    async def touch_user_meta(self, chat_id: int, user_id: int, ts: int) -> None:
        """«Касание» на сообщение юзера (spec §3.1.1): новая строка с
        first_seen=ts/last_seen=ts/msg_count=1; существующая — last_seen
        растёт (max), first_seen — минимум (min), msg_count+1. Коммит в
        конце (в save_smart_message лишний коммит — no-op)."""
        await self.db.execute(
            "INSERT INTO users_meta "
            "(chat_id, user_id, first_seen, last_seen, msg_count, "
            "last_recalc_at) VALUES (?, ?, ?, ?, 1, 0) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "first_seen = min(first_seen, excluded.first_seen), "
            "last_seen = max(last_seen, excluded.last_seen), "
            "msg_count = msg_count + 1",
            (chat_id, user_id, ts, ts),
        )
        await self.db.commit()

    @_serialized_write
    async def refresh_users_meta(self, chat_id: int, user_ids=None, *,
                                 now: int | None = None) -> int:
        """Полный пересчёт карточек чата/подмножества (spec §3.1.1).

        Один SQL-агрегат по smart_messages (all-time: total/first_ts/last_ts
        + 30д-окно msg30/active_days30 — «старики» импорта корректно выходят
        на veteran, Q5) + лёгкий SELECT ts окна для activity_score
        (Σ 0.5**((now−ts)/half_life), 14д; окно 30д, при переполнении
        relations_scan_max_rows — сжатие вдвое до 3 итераций) → батч-UPSERT
        с правилом стадии и анти-откатом §3.1.2 (decide_stage). last_recalc_at
        = now. Возврат — число обновлённых строк. Пустой user_ids → 0."""
        if user_ids is not None:
            ids = [int(uid) for uid in user_ids if uid]
            if not ids:
                return 0
        else:
            ids = None
        now = int(now) if now is not None else int(time.time())
        limits = relations_limits()
        win30 = now - 30 * 86400
        in_clause = ""
        args: list = [win30, win30, chat_id]
        if ids is not None:
            in_clause = " AND user_id IN (%s)" % ",".join("?" * len(ids))
            args.extend(ids)
        if ids is None:
            tail = " GROUP BY user_id ORDER BY msg30 DESC, user_id ASC LIMIT ?"
            args.append(int(limits["api_max_users"]))
        else:
            tail = " GROUP BY user_id ORDER BY msg30 DESC, user_id ASC"
        sql = (
            "SELECT user_id, COUNT(*) AS total, MIN(timestamp) AS first_ts, "
            "MAX(timestamp) AS last_ts, "
            "COUNT(CASE WHEN timestamp >= ? THEN 1 END) AS msg30, "
            "COUNT(DISTINCT CASE WHEN timestamp >= ? THEN timestamp / 86400 "
            "END) AS active_days30 "   # целочисленное деление SQLite
            "FROM smart_messages "
            "WHERE chat_id = ? AND user_id IS NOT NULL" + in_clause + tail)
        cursor = await self.db.execute(sql, args)
        rows = await cursor.fetchall()
        if not rows:
            return 0
        stored = {row["user_id"]: row
                  for row in await self.get_users_meta(chat_id)}
        decay = await self._fetch_decay_ts(chat_id, win30, now, ids, limits)
        half_life = float(limits["decay_half_life_days"])
        upserts: list[tuple] = []
        for row in rows:
            uid = row["user_id"]
            first_ts = row["first_ts"]
            last_ts = row["last_ts"]
            total = int(row["total"])
            msg30 = int(row["msg30"])
            prev = stored.get(uid) or {}
            candidate = stage_candidate(
                total, max(0, now - first_ts) // 86400,
                acquaintance_min_msg=int(limits["acquaintance_min_msg"]),
                acquaintance_min_days=int(limits["acquaintance_min_days"]),
                regular_min_msg=int(limits["regular_min_msg"]),
                regular_min_days=int(limits["regular_min_days"]),
                veteran_min_msg=int(limits["veteran_min_msg"]),
                veteran_min_days=int(limits["veteran_min_days"]),
            )
            stage, changed = decide_stage(
                prev.get("relationship_stage") or "stranger", candidate,
                now=now, last_seen=last_ts,
                last_stage_change=prev.get("last_stage_change"),
                msg_30d=msg30,
                hold_absent_days=int(limits["hold_absent_days"]),
                stage_change_min_days=int(limits["stage_change_min_days"]),
                downgrade_msg_30d=int(limits["downgrade_msg_30d"]),
            )
            score = sum(
                decay_weight(now, ts, half_life) for ts in decay.get(uid, ()))
            upserts.append((
                chat_id, uid, first_ts, last_ts, total,
                int(row["active_days30"]), score, stage,
                now if changed else prev.get("last_stage_change"), now,
            ))
        await self.db.executemany(
            "INSERT INTO users_meta (chat_id, user_id, first_seen, last_seen, "
            "msg_count, active_days, activity_score, relationship_stage, "
            "last_stage_change, last_recalc_at) VALUES (?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "first_seen = excluded.first_seen, last_seen = excluded.last_seen, "
            "msg_count = excluded.msg_count, active_days = excluded.active_days, "
            "activity_score = excluded.activity_score, "
            "relationship_stage = excluded.relationship_stage, "
            "last_stage_change = excluded.last_stage_change, "
            "last_recalc_at = excluded.last_recalc_at",
            upserts,
        )
        await self.db.commit()
        return len(upserts)

    async def count_user_msg30(self, chat_id: int, user_id: int, *,
                               now: int | None = None) -> int:
        """Фикс-раунд (D-14): COUNT сообщений юзера за 30д-окно — для
        карточки `<user_relations>` («N сообщ. за 30 дней»). Отдельный лёгкий
        агрегат (значение не хранится в users_meta — состав колонок §3.1.1
        без изменений); вызывается только на редком пути инжекта (гейты
        relations_tone_enabled + per-chat)."""
        win = (int(now) if now is not None else int(time.time())) - 30 * 86400
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM smart_messages "
            "WHERE chat_id = ? AND user_id = ? AND timestamp >= ?",
            (chat_id, int(user_id), win))
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def recalc_user_meta(self, chat_id: int, user_id: int, *,
                               now: int | None = None) -> int:
        """Пересчёт карточки одного юзера (удобная обёртка refresh)."""
        return await self.refresh_users_meta(chat_id, [user_id], now=now)

    async def recalc_chat_users(self, chat_id: int, *,
                                now: int | None = None) -> int:
        """Пересчёт активных участников (get_active_participants, окно 30д)
        + всех, у кого уже есть строка users_meta."""
        now = int(now) if now is not None else int(time.time())
        active = await self.get_active_participants(chat_id, now - 30 * 86400,
                                                    cap=_REFRESH_ACTIVE_CAP)
        ids = {row["user_id"] for row in active}
        ids.update(row["user_id"]
                   for row in await self.get_users_meta(chat_id))
        if not ids:
            return 0
        return await self.refresh_users_meta(chat_id, sorted(ids), now=now)

    async def _fetch_decay_ts(self, chat_id: int, win_start: int, now: int,
                              ids, limits) -> dict[int, list[int]]:
        """ts сообщений окна для decay: {user_id: [ts, ...]}. При строках
        окна > limits.relations_scan_max_rows окно сжимается вдвое (до 3
        итераций) — вклад отброшенных < 0.35 и затухает (деградация
        осознанная, spec §3.1.1)."""
        in_clause = ""
        args: list = [chat_id, win_start]
        if ids is not None:
            in_clause = " AND user_id IN (%s)" % ",".join("?" * len(ids))
            args.extend(ids)
        scan_max = int(limits["scan_max_rows"])
        length = now - win_start
        window = win_start
        for _ in range(3):
            args[1] = window
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM smart_messages "
                "WHERE chat_id = ? AND user_id IS NOT NULL AND timestamp >= ?"
                + in_clause, args)
            count = (await cursor.fetchone())[0]
            if count is not None and int(count) <= scan_max:
                break
            length = max(86400, length // 2)   # сжатие окна вдвое
            window = now - length
        cursor = await self.db.execute(
            "SELECT user_id, timestamp FROM smart_messages "
            "WHERE chat_id = ? AND user_id IS NOT NULL AND timestamp >= ?"
            + in_clause, args)
        ts_by_user: dict[int, list[int]] = {}
        async for row in cursor:
            ts_by_user.setdefault(row["user_id"], []).append(row["timestamp"])
        return ts_by_user

    # ── Epic 60 Фаза C (65.4/65.5/65.8/65.10) ─────────────────
    # Стилевые якоря, пресеты тона (user_prefs), /clear, /forget,
    # защищённые факты (protected_facts).

    async def last_bot_replies(self, chat_id: int, limit: int, now: float) -> list[str]:
        """65.4: последние (по last_used_at) НЕ протухшие ответы бота чата,
        ASC (от старейшего к свежайшему) — для <style_anchors>."""
        cursor = await self.db.execute(
            "SELECT text FROM bot_replies "
            "WHERE chat_id = ? AND last_used_at > ? "
            "ORDER BY last_used_at DESC LIMIT ?",
            (chat_id, now - self._BOT_REPLIES_TTL_SECONDS, limit),
        )
        return [row["text"] for row in (await cursor.fetchall())][::-1]

    async def get_user_tone_preset(self, chat_id: int, user_id: int) -> str | None:
        """65.8: tone_preset из user_prefs (None — нет записи)."""
        cursor = await self.db.execute(
            "SELECT tone_preset FROM user_prefs WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
        return row["tone_preset"] if row is not None else None

    @_serialized_write
    async def set_user_tone_preset(self, chat_id: int, user_id: int,
                                   preset: str) -> None:
        """65.5/65.8: UPSERT tone_preset в user_prefs (/tone — единственная
        команда записи)."""
        await self.db.execute(
            "INSERT INTO user_prefs (chat_id, user_id, tone_preset) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "tone_preset = excluded.tone_preset",
            (chat_id, user_id, preset),
        )
        await self.db.commit()

    async def get_protected_facts(self, chat_id: int, user_name: str,
                                  include_chat_level: bool = True) -> list[str]:
        """65.10: защищённые факты юзера (подмешиваются в контекст; /forget
        их НЕ трогает). include_chat_level=True (default, раунд 5/T-732):
        + чат-уровневые факты (user_name IS NULL — «лор чата»), они идут
        ПЕРВЫМИ (не тонут при обрезке блока). False — старое поведение
        (только user_name = ?). Порядок: чат-уровневые → ASC по created_at, id."""
        if include_chat_level:
            cursor = await self.db.execute(
                "SELECT fact FROM protected_facts "
                "WHERE chat_id = ? AND (user_name = ? OR user_name IS NULL) "
                "ORDER BY (user_name IS NULL) DESC, created_at ASC, id ASC",
                (chat_id, user_name))
        else:
            cursor = await self.db.execute(
                "SELECT fact FROM protected_facts "
                "WHERE chat_id = ? AND user_name = ? "
                "ORDER BY created_at ASC, id ASC",
                (chat_id, user_name))
        return [row["fact"] for row in await cursor.fetchall()]

    @_serialized_write
    async def clear_direct_dialogue(self, chat_id: int, target_user: str) -> int:
        """/clear (65.5): стереть цепочки чата (bot_replies) + graph_facts с
        origin='bot_direct_reply' AND target_user=имя юзера (+FTS-строки).
        chat_history-факты НЕ трогаем. Возвращает число удалённых фактов."""
        await self.db.execute("DELETE FROM bot_replies WHERE chat_id = ?", (chat_id,))
        cursor = await self.db.execute(
            "SELECT id FROM graph_facts "
            "WHERE chat_id = ? AND origin = 'bot_direct_reply' AND target_user = ?",
            (chat_id, target_user),
        )
        fact_ids = [row["id"] for row in await cursor.fetchall()]
        for fact_id in fact_ids:
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (fact_id,))
        await self.db.commit()
        return len(fact_ids)

    @staticmethod
    def _fts_forget_query(phrase: str) -> str:
        """FTS5-prefix-запрос для /forget (прецедент build_fts_query из
        summary_memory: `"слово"*` OR …; кавычки/`*` юзера вырезаны,
        слова <2 симв. отброшены — unicode61 их не токенизирует)."""
        cleaned = []
        for word in re.findall(r"[0-9a-zа-яё]+", phrase.lower()):
            word = word.replace('"', "").replace("*", "")
            if len(word) >= 2:
                cleaned.append(f'"{word}"*')
        return " OR ".join(cleaned)

    @_serialized_write
    async def forget_direct_facts(self, chat_id: int, target_user: str,
                                  phrase: str, now_ts: int) -> int:
        """/forget (65.5/65.10): FTS-поиск по bot_direct_reply-фактам юзера →
        DELETE + запись в graph_fact_compressions (reason='forget').
        Защищённые факты (точное совпадение fact с protected_facts) НЕ
        удаляются. Fail-open: ошибка FTS → WARNING + 0. Возвращает число
        удалённых фактов."""
        match_query = self._fts_forget_query(phrase)
        if not match_query:
            return 0
        try:
            cursor = await self.db.execute(
                "SELECT f.id, f.fact FROM graph_facts_fts "
                "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
                "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
                "AND f.origin = 'bot_direct_reply' AND f.target_user = ? "
                "AND (f.expires_at IS NULL OR f.expires_at > ?) "
                "AND NOT EXISTS (SELECT 1 FROM protected_facts p "
                "WHERE p.chat_id = f.chat_id AND p.user_name = f.target_user "
                "AND p.fact = f.fact)",
                (match_query, chat_id, target_user, now_ts),
            )
            rows = await cursor.fetchall()
        except Exception:
            logger.warning(
                "direct: /forget FTS search failed — fail-open | chat=%s",
                chat_id, exc_info=True)
            return 0
        for row in rows:
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (row["id"],))
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (row["id"],))
            await self.log_fact_compression(
                chat_id, row["id"], row["fact"], None, "forget")
        await self.db.commit()
        return len(rows)

    # ── Раунд 4 (T-714, FR-D3, spec 3.4.5): «забудь» — user_memory ──

    @staticmethod
    def _memory_forget_words(phrase: str) -> list[str]:
        """Слова запроса «забудь»: [0-9a-zа-яё]+ из lower(phrase), длина >= 3,
        срез до 5 (AND-семантика; fail-open → [])."""
        return [
            w for w in re.findall(r"[0-9a-zа-яё]+", str(phrase or "").lower())
            if len(w) >= 3
        ][:5]

    @_serialized_write
    async def forget_memory_facts(self, chat_id: int, words: list[str],
                                  target_user: str | None = None,
                                  now_ts: int = 0) -> int:
        """«забудь» (T-714/FR-D3): ТОЛЬКО origin='user_memory'. words — слова
        запроса (>=3 симв, до 5). FTS-prefix первого слова (fail-open → 0) →
        кандидаты; Python-фильтр: КАЖДОЕ слово содержится в lower(fact) (AND).
        target_user None → весь чат; иначе — свои факты юзера (scope по
        канон-имени). Удаление: graph_facts_fts → graph_facts → best-effort
        graph_facts_vec (vec-таблицы может не быть — FTS-режим); на каждый
        удалённый факт — журнал graph_fact_compressions (reason='user_forget').
        protected_facts в выборку НЕ попадают (отдельная таблица; запрос
        ограничен origin='user_memory'). Повторный вызов безвреден.
        Граница: chat_history/bot_direct_reply/прочее НЕ трогаются."""
        if now_ts <= 0:
            now_ts = int(time.time())
        words = [w for w in (words or []) if len(w) >= 3][:5]
        if not words:
            return 0
        match_query = f'"{words[0]}"*'
        sql = (
            "SELECT f.id, f.fact FROM graph_facts_fts "
            "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
            "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
            "AND f.origin = 'user_memory' "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) ")
        params: list = [match_query, chat_id, now_ts]
        if target_user is not None:
            sql += "AND f.target_user = ? "
            params.append(target_user)
        sql += "LIMIT 500"
        try:
            cursor = await self.db.execute(sql, params)
            rows = await cursor.fetchall()
        except Exception:
            logger.warning(
                "direct: «забудь» FTS search failed — fail-open | chat=%s",
                chat_id, exc_info=True)
            return 0
        removed = 0
        for row in rows:
            fact_lower = str(row["fact"] or "").lower()
            if not all(w in fact_lower for w in words):
                continue
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (row["id"],))
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (row["id"],))
            try:
                await self.db.execute(
                    "DELETE FROM graph_facts_vec WHERE rowid = ?", (row["id"],)
                )
            except Exception:
                pass                        # vec-таблицы может не быть (FTS-режим)
            await self.log_fact_compression(
                chat_id, row["id"], row["fact"], None, "user_forget")
            removed += 1
        await self.db.commit()
        return removed

    # ── Epic 60 Фаза B (64.1/64.2/64.6, T-462/T-463/T-467) ─────

    @staticmethod
    def _like_escape(value: str) -> str:
        """Экранирование LIKE-паттерна (ESCAPE '!')."""
        return (str(value).replace("!", "!!").replace("%", "!%").replace("_", "!_"))

    async def find_graph_fact_exact(self, chat_id: int, key: str, now_ts: int):
        """64.1: точный дубль — строка graph_facts того же чата с фактом
        's p o' или 's p o (context)', не протухшая. Возвращает row
        (id/fact/weight/status) или None."""
        pattern = self._like_escape(key) + "%"
        cursor = await self.db.execute(
            "SELECT id, fact, weight, status, expires_at FROM graph_facts "
            "WHERE chat_id = ? AND fact LIKE ? ESCAPE '!' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY created_at DESC LIMIT 5",
            (chat_id, pattern, now_ts),
        )
        for row in await cursor.fetchall():
            if row["fact"] == key or row["fact"].startswith(key + " ("):
                return row
        return None

    @_serialized_write
    async def confirm_graph_fact(self, fact_id: int, now_ts: int,
                                 bonus: float) -> None:
        """64.1/64.2: noop-подтверждение — weight += bonus (cap 1.0, floor
        0.1), last_confirmed_at = now, status → 'confirmed'."""
        await self.db.execute(
            "UPDATE graph_facts SET "
            "weight = MIN(MAX(weight + ?, 0.1), 1.0), "
            "last_confirmed_at = ?, status = 'confirmed' WHERE id = ?",
            (bonus, now_ts, fact_id),
        )
        await self.db.commit()

    @_serialized_write
    async def invalidate_graph_fact(self, fact_id: int, now_ts: int) -> None:
        """64.2: инвалидация (НЕ удаление) — expires_at = now; vec-строка
        удаляется (иначе KNN продолжил бы выдавать старый текст — TTL в
        vec-таблице живёт своей копией)."""
        await self.db.execute(
            "UPDATE graph_facts SET expires_at = ? WHERE id = ?",
            (now_ts, fact_id),
        )
        try:
            await self.db.execute(
                "DELETE FROM graph_facts_vec WHERE rowid = ?", (fact_id,)
            )
        except Exception:
            pass                        # vec-таблицы может не быть (FTS-режим)
        await self.db.commit()

    @_serialized_write
    async def log_fact_compression(self, chat_id: int, fact_id, fact_before: str,
                                   fact_after, reason: str) -> None:
        """64.2: журнал «что во что» (supersede/сжатие/forget/conflict) —
        обратимость антиотравления. fact_id — id нового/пережившего факта."""
        await self.db.execute(
            "INSERT INTO graph_fact_compressions "
            "(chat_id, fact_id, fact_before, fact_after, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, fact_id, fact_before, fact_after, reason, time.time()),
        )
        await self.db.commit()

    async def get_graph_fact_rows(self, fact_ids: list) -> list:
        """Строки graph_facts по id (для дедупа 64.1): id/fact/status/weight/
        expires_at."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        cursor = await self.db.execute(
            f"SELECT id, fact, status, weight, expires_at FROM graph_facts "
            f"WHERE id IN ({placeholders})", fact_ids,
        )
        return await cursor.fetchall()

    async def get_running_summary(self, chat_id: int, now: float) -> dict | None:
        """64.6: конспект чата (chat_running_summary) или None — нет строки.
        Раунд 8 (E4/T-806, Q11): expires_at при ЧТЕНИИ НЕ «убивает» конспект —
        lazy-DELETE по TTL убран (в тихом чате конспект живёт и остаётся в
        Global_Context; пересборка — по заполнению окна новыми сообщениями,
        триггер get_window_messages). expires_at продолжает писаться
        (диагностика/запасной механизм), колонки не меняются. Раунд 8
        (D5/T-802): SELECT несёт created_at (для логов; метке объёма нужен
        raw_count — уже был в выборке)."""
        cursor = await self.db.execute(
            "SELECT summary, window_start_ts, window_end_ts, raw_count, "
            "created_at, expires_at FROM chat_running_summary WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row

    @_serialized_write
    async def upsert_running_summary(self, chat_id: int, summary: str,
                                     window_start_ts: int, window_end_ts: int,
                                     raw_count: int, created_at: float,
                                     expires_at: float) -> bool:
        """64.6: UPSERT конспекта (chat_id — PRIMARY KEY).

        Раунд 10.27 (MCA-07, ADR-1027-7 D8): при `MCA_SUMMARY_SINGLEFLIGHT_
        ENABLED` ON запись становится **high-watermark/CAS** — поздний старый
        запрос (меньший `window_end_ts`, при равенстве — меньший `raw_count`)
        НЕ перезаписывает более новую версию (A03). Возвращает True, если
        строка записана, False — если CAS её отклонил. OFF → прежний слепой
        UPSERT (паритет baseline), возвращает True."""
        params = (chat_id, summary, window_start_ts, window_end_ts, raw_count,
                  created_at, expires_at)
        if not _summary_singleflight_enabled():
            await self.db.execute(
                "INSERT INTO chat_running_summary "
                "(chat_id, summary, window_start_ts, window_end_ts, raw_count, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET "
                "summary = excluded.summary, "
                "window_start_ts = excluded.window_start_ts, "
                "window_end_ts = excluded.window_end_ts, "
                "raw_count = excluded.raw_count, "
                "created_at = excluded.created_at, "
                "expires_at = excluded.expires_at",
                params,
            )
            await self.db.commit()
            return True
        # CAS: высокий watermark (window_end_ts, затем raw_count) побеждает.
        cursor = await self.db.execute(
            "INSERT INTO chat_running_summary "
            "(chat_id, summary, window_start_ts, window_end_ts, raw_count, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "summary = excluded.summary, "
            "window_start_ts = excluded.window_start_ts, "
            "window_end_ts = excluded.window_end_ts, "
            "raw_count = excluded.raw_count, "
            "created_at = excluded.created_at, "
            "expires_at = excluded.expires_at "
            "WHERE excluded.window_end_ts > chat_running_summary.window_end_ts "
            "OR (excluded.window_end_ts = chat_running_summary.window_end_ts "
            "AND excluded.raw_count >= chat_running_summary.raw_count)",
            params,
        )
        written = cursor.rowcount != 0
        await self.db.commit()
        if not written:
            logger.info("[database] running summary CAS dropped (stale) | "
                        "chat_id=%s | end_ts=%s", chat_id, window_end_ts)
        return written

    # ── Уровни конспекта (Раунд 8, spec §3.E2, T-804) ─────────
    # chat_summary_levels: level 2 = «широкий фон» — сжатие ПРЕДЫДУЩЕГО level 1
    # (running_summary) тем же COMPRESS_PROMPT. msg_count_highwater защищает
    # от перезаписи более узким окном. TTL уровня не вводится (E2.4).

    async def get_summary_level(self, chat_id: int, level: int) -> dict | None:
        """E2/T-804: строка уровня конспекта (None — уровня нет)."""
        cursor = await self.db.execute(
            "SELECT summary, updated_at, msg_count_highwater "
            "FROM chat_summary_levels WHERE chat_id = ? AND level = ?",
            (chat_id, level),
        )
        return await cursor.fetchone()

    @_serialized_write
    async def upsert_summary_level(self, chat_id: int, level: int,
                                   summary: str, updated_at: float,
                                   msg_count_highwater: int) -> None:
        """E2/T-804: UPSERT уровня конспекта (PK chat_id+level)."""
        await self.db.execute(
            "INSERT INTO chat_summary_levels "
            "(chat_id, level, summary, updated_at, msg_count_highwater) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, level) DO UPDATE SET "
            "summary = excluded.summary, "
            "updated_at = excluded.updated_at, "
            "msg_count_highwater = excluded.msg_count_highwater",
            (chat_id, level, summary, updated_at, msg_count_highwater),
        )
        await self.db.commit()

    # ── Epic 60 Фаза D (66.1–66.12, T-479…T-490) ───────────────

    async def get_graph_fact_records(self, fact_ids, status=None) -> list:
        """66.1/66.3: полные строки graph_facts по id (id/fact/origin/
        created_at/target_user/weight/status/last_confirmed_at) — для
        weight×decay-ранжирования KNN-пути в Python. status-фильтр — как в
        get_graph_fact_texts (64.2). Фаза 2 (T-759): + message_timestamp
        (рендер COALESCE делает вызывающий — _knn_graph_facts).
        F2/T-1427 (spec §4.2): + belief_meta/kind — KNN-путь различает
        архивные beliefs (status='archived_belief', пенальти) и читает
        base_weight из belief_meta при воскрешении. status=None → без
        SQL-фильтра (фильтрация статусов — на стороне вызывающего)."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        sql = (f"SELECT id, fact, origin, created_at, target_user, weight, "
               f"status, last_confirmed_at, message_timestamp, belief_meta, "
               f"kind, importance, tg_message_id, forward_from "
               f"FROM graph_facts "
               f"WHERE id IN ({placeholders})")
        params: list = list(fact_ids)
        if status:
            sql += " AND status = ?"
            params.append(status)
        cursor = await self.db.execute(sql, params)
        return await cursor.fetchall()

    async def touch_graph_facts(self, fact_ids, extend_days: int,
                                direct_ttl_days, archive_ttl_days: int,
                                now_ts: int) -> int:
        """66.5 (T-483): «используется — живёт» — RAG-hit продлевает
        expires_at на extend_days, cap: не дальше created_at + 2 × базовый TTL
        (вечное протухание невозможно). Только факты с expires_at NOT NULL
        (chat_history/вечные не трогаем). Базовая TTL по origin: direct —
        direct_ttl_days (None → пропуск), архивные — archive_ttl_days.
        Обновление по id списком (батч, без write-per-read)."""
        if not fact_ids:
            return 0
        placeholders = ",".join("?" for _ in fact_ids)
        extend = extend_days * 86400.0

        async def _body(conn):
            touched = 0
            for origins, ttl_days in ((
                ("'search_fact'", "'youtube_content'", "'web_content'"),
                archive_ttl_days), (("'bot_direct_reply'",), direct_ttl_days)):
                if ttl_days in (None, 0):
                    continue
                origin_sql = ",".join(origins)
                cursor = await conn.execute(
                    f"UPDATE graph_facts SET expires_at = "
                    f"MIN(expires_at + ?, created_at + ?) "
                    f"WHERE id IN ({placeholders}) AND expires_at IS NOT NULL "
                    f"AND origin IN ({origin_sql})",
                    (extend, 2 * ttl_days * 86400.0, *fact_ids))
                touched += cursor.rowcount
            return touched

        # F0.5: сериализация + bounded retry (single-writer). commit_if —
        # baseline-паритет: коммит ТОЛЬКО если были изменения (touched > 0),
        # как в исходном коде (`if touched: commit`).
        return await self.write_transaction(
            _body, op_name="touch_graph_facts",
            commit_if=lambda touched: bool(touched))

    @_serialized_write
    async def delete_graph_fact(self, fact_id: int) -> None:
        """66.4/66.11: полное удаление факта — graph_facts_fts + vec-строка
        (rowid == fact_id) + строка graph_facts."""
        await self.db.execute(
            "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
        try:
            await self.db.execute(
                "DELETE FROM graph_facts_vec WHERE rowid = ?", (fact_id,))
        except Exception:
            pass                        # vec-таблицы может не быть (FTS-режим)
        await self.db.execute(
            "DELETE FROM graph_facts WHERE id = ?", (fact_id,))
        await self.db.commit()

    async def is_fact_protected(self, chat_id: int, fact_text: str) -> bool:
        """65.10/66.2/66.10: факт совпадает с защищённым (по тексту, чат-скоп) —
        дедуп/слияние/пересмотр его НЕ трогают."""
        cursor = await self.db.execute(
            "SELECT 1 FROM protected_facts WHERE chat_id = ? AND fact = ? LIMIT 1",
            (chat_id, fact_text))
        return await cursor.fetchone() is not None

    async def get_quota_victim(self, chat_id: int, target_user: str, quota: int,
                               now_ts: int):
        """66.4 (T-482): вытеснение — при live-фактах юзера >= quota вернуть
        самого лёгкого и старого: score = weight / (age_days + 1) MIN.
        Защищённые факты — вне кандидатов на вытеснение (65.10).
        Раунд 8 (E3/T-805): расширение защищённого множества — высоковесные
        (weight >= limits.graph_purge_protect_weight) и недавно подтверждённые
        (last_confirmed_at свежее limits.graph_purge_protect_days) тоже не
        выбираются жертвой (гейт purge/eviction spec §3.E3.2). None — квота
        не превышена / все кандидаты защищены."""
        protect_weight = float(hot.get(
            "limits.graph_purge_protect_weight",
            settings.GRAPH_PURGE_PROTECT_WEIGHT) or 0.8)
        protect_days = int(hot.get(
            "limits.graph_purge_protect_days",
            settings.GRAPH_PURGE_PROTECT_DAYS) or 0) or 3
        protect_cutoff = now_ts - protect_days * 86400
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts "
            "WHERE chat_id = ? AND target_user = ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (chat_id, target_user, now_ts))
        if (await cursor.fetchone())["c"] < quota:
            return None
        cursor = await self.db.execute(
            "SELECT id, fact FROM graph_facts "
            "WHERE chat_id = ? AND target_user = ? "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "AND NOT EXISTS (SELECT 1 FROM protected_facts p "
            "WHERE p.chat_id = graph_facts.chat_id "
            "AND p.user_name = graph_facts.target_user "
            "AND p.fact = graph_facts.fact) "
            "AND NOT (weight >= ? OR "
            "(last_confirmed_at IS NOT NULL AND last_confirmed_at >= ?)) "
            "ORDER BY (weight / (((? - created_at) / 86400.0) + 1.0)) ASC, "
            "id ASC LIMIT 1",
            (chat_id, target_user, now_ts, protect_weight, protect_cutoff,
             now_ts))
        return await cursor.fetchone()

    async def get_live_graph_facts(self, chat_id: int, now_ts: int) -> list:
        """66.2/66.11: живые (не протухшие) confirmed-факты чата для слияния/
        пересмотра. Раунд 10.14 (F1, ADR-1014-2 D6): self-факты исключены по
        origin (собственные слова бота не «подтверждаются» слиянием).
        S10.18-35 (F5): + ``importance`` в SELECT — merge-путь (`_merge_cluster`)
        переносит F5-пенальти мета-фактов в слитую строку (кластер из фактов
        с imp<=1 → merged imp=1), а не теряет его в ``rule_importance``."""
        cursor = await self.db.execute(
            "SELECT id, fact, origin, expires_at, created_at, weight, "
            "target_user, last_confirmed_at, importance FROM graph_facts "
            "WHERE chat_id = ? AND status = 'confirmed' "
            "AND origin != 'bot_self_reply' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (chat_id, now_ts))
        return await cursor.fetchall()

    async def get_graph_chat_ids(self) -> list[int]:
        """66.11: чаты, в которых есть graph_facts (пересмотр по всем)."""
        cursor = await self.db.execute(
            "SELECT DISTINCT chat_id FROM graph_facts")
        return [row["chat_id"] for row in await cursor.fetchall()]

    async def find_exact_dup_groups(self, chat_id: int, now_ts: int) -> list:
        """66.11 (T-489): точные дубли (идентичный текст факта) живых
        confirmed-фактов чата — группы ≥2 (для склейки пересмотром).
        Раунд 10.14 (F1, ADR-1014-2 D6): self-факты исключены по origin."""
        cursor = await self.db.execute(
            "SELECT id, fact, weight, created_at FROM graph_facts "
            "WHERE chat_id = ? AND status = 'confirmed' "
            "AND origin != 'bot_self_reply' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (chat_id, now_ts))
        groups: dict[str, list] = {}
        for row in await cursor.fetchall():
            key = str(row["fact"]).casefold().strip()
            groups.setdefault(key, []).append(row)
        return [rows for rows in groups.values() if len(rows) >= 2]

    @_serialized_write
    async def purge_unconfirmed_graph_facts(self, now_ts: int,
                                            retention_days: int) -> int:
        """66.11 (T-489): выброс unconfirmed старше retention (64.2) — по всем
        чатам; vec/FTS-строки чистим вместе (иначе KNN выдавал бы текст).
        Фаза 2 (T-756, гейт G4): memory.infinite_retention ON → return 0
        без SQL."""
        if _infinite_retention_on():
            logger.info(
                "[database] purge_unconfirmed_graph_facts skipped — "
                "memory.infinite_retention ON (T-756)")
            return 0
        cursor = await self.db.execute(
            "SELECT id FROM graph_facts WHERE status = 'unconfirmed' "
            "AND created_at <= ?",
            (now_ts - retention_days * 86400,))
        ids = [row["id"] for row in await cursor.fetchall()]
        for fact_id in ids:
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
            try:
                await self.db.execute(
                    "DELETE FROM graph_facts_vec WHERE rowid = ?", (fact_id,))
            except Exception:
                pass
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (fact_id,))
        await self.db.commit()
        return len(ids)

    @_serialized_write
    async def trim_compression_log(self, now: float, retention_days: int) -> int:
        """66.11 (T-489): усечение graph_fact_compressions старше retention —
        лог не растёт вечно. Фаза 2 (T-756, гейт G5): memory.infinite_retention
        ON → return 0 без SQL."""
        if _infinite_retention_on():
            logger.info(
                "[database] trim_compression_log skipped — "
                "memory.infinite_retention ON (T-756)")
            return 0
        cursor = await self.db.execute(
            "DELETE FROM graph_fact_compressions WHERE created_at < ?",
            (now - retention_days * 86400.0,))
        await self.db.commit()
        return cursor.rowcount

    async def get_persona_card(self, chat_id: int, name: str, limit: int,
                               now_ts: int, *, user_id: int | None = None
                               ) -> dict:
        """66.9 (T-487): карточка человека БЕЗ отдельной таблицы — агрегация:
        прямые факты (target_user = имя, weight DESC) + связи графа (edges по
        user-узлу с entity_name = имя, weight DESC). Без техдеталей (id/весов
        в ответе нет).

        MCA-04a FIX п.2 (spec §4.6): при `MCA_FACT_ATTRIBUTION_ENABLED` факты
        читаются субъект-ориентированно (`subject_ref_id` устойчивого ID);
        legacy-строки без `subject_ref_id` — по имени (честный unknown);
        общие знания и self-referential ответы бота исключены всегда (A85)."""
        scope, excl, sparams = await self._person_scope_clause(
            chat_id, name, user_id=user_id)
        cursor = await self.db.execute(
            "SELECT fact FROM graph_facts "
            f"WHERE chat_id = ? AND {scope} AND {excl} "
            "AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY weight DESC, created_at DESC",
            [chat_id, *sparams, now_ts])
        facts = [row["fact"] for row in await cursor.fetchall()]
        cursor = await self.db.execute(
            "SELECT e.relation_type, "
            "s.entity_name AS source_name, t.entity_name AS target_name "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            "WHERE e.chat_id = ? "
            "AND ((s.entity_name = ? AND s.entity_type = 'user') "
            "OR (t.entity_name = ? AND t.entity_type = 'user')) "
            "AND e.origin != 'bot_direct_reply' "
            "AND s.origin != 'bot_direct_reply' AND t.origin != 'bot_direct_reply' "
            "ORDER BY e.weight DESC, e.id DESC LIMIT ?",
            (chat_id, name, name, limit))
        links = [dict(row) for row in await cursor.fetchall()]
        return {"facts": facts, "links": links}

    async def _person_scope_clause(self, chat_id, name, *, user_id=None):
        """Субъект-scope для чтения личных фактов (MCA-04a FIX п.2, spec §4.6).

        Возврат `(scope_sql, exclude_sql, params)`. Provenance-строки — по
        `subject_ref_id` (устойчивый ID); legacy (`subject_ref_id IS NULL`) —
        по `target_user`-имени. Общие знания (`world_knowledge`) и ответы бота
        (`bot_self_reply`) исключаются всегда (A85)."""
        from services import mca_gates, provenance
        ref_id = None
        if mca_gates.fact_attribution_enabled():
            if user_id is None:
                try:
                    ref = await provenance.resolve_subject_ref(self, chat_id,
                                                               name)
                    if ref.resolution == "resolved":
                        user_id = ref.entity_id
                except Exception:
                    logger.debug("[database] subject resolve failed",
                                 exc_info=True)
            if user_id is not None:
                try:
                    cursor = await self.db.execute(
                        "SELECT source_ref_id FROM mca_source_refs WHERE "
                        "store = 'telegram' AND entity_type = 'user' AND "
                        "entity_id = ? AND COALESCE(chat_id, -1) = "
                        "COALESCE(?, -1) LIMIT 1", (str(user_id), chat_id))
                    row = await cursor.fetchone()
                    if row is not None:
                        ref_id = int(row["source_ref_id"])
                except Exception:
                    logger.debug("[database] subject ref lookup failed",
                                 exc_info=True)
        clauses = []
        params: list = []
        if ref_id is not None:
            clauses.append("subject_ref_id = ?")
            params.append(ref_id)
        clauses.append("(subject_ref_id IS NULL AND target_user = ?)")
        params.append(name)
        scope = "(" + " OR ".join(clauses) + ")"
        exclude = ("COALESCE(attribution_method, '') != 'world_knowledge' "
                   "AND COALESCE(assertion_kind, '') != 'world_knowledge' "
                   "AND COALESCE(origin, '') != 'bot_self_reply'")
        return scope, exclude, params

    async def get_user_context_facts(self, chat_id: int, target_user: str,
                                     limit: int, now_ts: int, *,
                                     user_id: int | None = None) -> list:
        """A6/ADR-1026-18 D4 (read-only): confirmed-факты участника с
        провенанс-метаданными для envelope `get_user_context` (sources/
        confidence §3.3/D4).

        MCA-04a FIX п.2 (spec §4.6): субъект-scope по `subject_ref_id` вместо
        `target_user`-имени (устойчивый ID); legacy без `subject_ref_id` —
        по имени; `world_knowledge`/`bot_self_reply` исключены. Сортировка
        `weight DESC, created_at DESC`. Только чтение."""
        target = str(target_user or "").strip()
        if not target:
            return []
        scope, exclude, sparams = await self._person_scope_clause(
            chat_id, target, user_id=user_id)
        cursor = await self.db.execute(
            "SELECT id, fact, origin, created_at, target_user, weight, status, "
            "last_confirmed_at, tg_message_id, message_timestamp, kind, "
            "subject_ref_id, attribution_method, assertion_kind, "
            "speaker_author_id, provenance_channel "
            f"FROM graph_facts WHERE chat_id = ? AND {scope} AND {exclude} "
            "AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY weight DESC, created_at DESC LIMIT ?",
            [int(chat_id), *sparams, int(now_ts), int(limit)])
        return [dict(row) for row in await cursor.fetchall()]

    async def get_persona_names(self, chat_id: int, now_ts: int) -> list:
        """66.9: /persona list (только админ) — имена + счётчики прямых фактов
        (живых, confirmed)."""
        cursor = await self.db.execute(
            "SELECT target_user AS name, COUNT(*) AS c FROM graph_facts "
            "WHERE chat_id = ? AND target_user IS NOT NULL "
            "AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "GROUP BY target_user ORDER BY name ASC",
            (chat_id, now_ts))
        return [(row["name"], row["c"]) for row in await cursor.fetchall()]

    # ── Раунд 10.20 (БЛОК 3.2/T-1896): ручные правки Досье ─────────────────
    # Аддитивные read/write над persona_dossier_overrides. Fail-open — на
    # уровне вызывающего (API) исключения → 503/деградация.

    async def get_dossier_override(self, chat_id: int, user_id: int) -> str:
        """Ручная правка досье участника (пустая строка — правок нет)."""
        cursor = await self.db.execute(
            "SELECT traits FROM persona_dossier_overrides "
            "WHERE chat_id = ? AND user_id = ?",
            (int(chat_id), int(user_id)))
        row = await cursor.fetchone()
        return str(row["traits"]) if row and row["traits"] else ""

    @_serialized_write
    async def set_dossier_override(self, chat_id: int, user_id: int,
                                   traits: str, now_ts: int) -> None:
        """Upsert ручной правки досье (id — ключ; R16)."""
        await self.db.execute(
            "INSERT OR REPLACE INTO persona_dossier_overrides "
            "(chat_id, user_id, traits, updated_at) VALUES (?, ?, ?, ?)",
            (int(chat_id), int(user_id), str(traits or ""), int(now_ts)))
        await self.db.commit()

    @_serialized_write
    async def delete_dossier_override(self, chat_id: int,
                                      user_id: int) -> None:
        """Сброс ручной правки досье участника (откат к авто-досье)."""
        await self.db.execute(
            "DELETE FROM persona_dossier_overrides "
            "WHERE chat_id = ? AND user_id = ?",
            (int(chat_id), int(user_id)))
        await self.db.commit()

    async def dossier_feed(self, limit: int = 12,
                           chat_id: int | None = None,
                           now_ts: int | None = None) -> list:
        """Раунд 10.20 (БЛОК 3.3/T-1897): случайные живые факты-«выдержки»
        из досье для виджета-тикера. chat_id None → по всем чатам (GLOBAL),
        иначе — только участники чата. Возвращает [{chat_id, name, fact}].

        M3/S10.20-16: выборка ограничена свежим пулом ``limit*20``
        (``ORDER BY id DESC`` по PK) — ``ORDER BY RANDOM()`` по всему скану
        при GLOBAL-поллинге 45с бил по росту ``graph_facts``. Ошибки доступа
        к БД НЕ глотаются (API-слой ловит сам, `web/api/oversight.py`) —
        «fail-open» здесь только про пустой результат ([]) на пустой БД."""
        ts = int(now_ts if now_ts is not None else time.time())
        cap = max(1, int(limit))
        pool = max(cap, cap * 20)
        sql = ("SELECT chat_id, name, fact FROM ("
               "SELECT chat_id, target_user AS name, fact, id "
               "FROM graph_facts "
               "WHERE target_user IS NOT NULL AND fact IS NOT NULL "
               "AND fact != '' AND status = 'confirmed' "
               "AND (expires_at IS NULL OR expires_at > ?) ")
        params: list = [ts]
        if chat_id is not None:
            sql += "AND chat_id = ? "
            params.append(int(chat_id))
        sql += "ORDER BY id DESC LIMIT ?) ORDER BY RANDOM() LIMIT ?"
        params.append(pool)
        params.append(cap)
        cursor = await self.db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]

    # ── F8 (cognition-irony-dossier-round1013, spec §3/§6): chat_memes ──────
    # Мемы живут в ТОЙ ЖЕ graph_facts со status='chat_meme' (status без CHECK,
    # нулевой DDL). Все читающие пути со status='confirmed' их не видят —
    # «real vs meme» разделение бесплатно (spec §3).

    async def meme_exists(self, chat_id: int, target_user: str,
                          fact: str) -> bool:
        """F8: есть ли уже такой мем (`status='chat_meme'`) — идемпотентность
        повторных классификаций досье. Fail-open: ошибка → False (мем будет
        записан, дубль допустимее пропажи)."""
        cursor = await self.db.execute(
            "SELECT 1 FROM graph_facts WHERE chat_id = ? AND target_user = ? "
            "AND fact = ? AND status = 'chat_meme' LIMIT 1",
            (chat_id, target_user, fact))
        return await cursor.fetchone() is not None

    async def person_fact_exists(self, chat_id: int, fact: str,
                                 provenance_channel: str | None = None
                                 ) -> bool:
        """MCA-04a FIX п.3: есть ли уже такой личный факт Layer A
        (`status='unconfirmed'`, опционально по каналу) — идемпотентность
        повторных прогонов досье. Fail-open: ошибка → False."""
        sql = ("SELECT 1 FROM graph_facts WHERE chat_id = ? AND fact = ? "
               "AND status = 'unconfirmed' ")
        params: list = [chat_id, fact]
        if provenance_channel is not None:
            sql += "AND provenance_channel = ? "
            params.append(provenance_channel)
        sql += "LIMIT 1"
        cursor = await self.db.execute(sql, params)
        return await cursor.fetchone() is not None

    async def list_chat_memes(self, chat_id: int,
                              target_user: str | None = None,
                              limit: int = 50,
                              now_ts: int | None = None) -> list:
        """F8: мемы чата (`status='chat_meme'`), свежие первыми. target_user
        None → все мемы чата. Возвращает list[dict]: id/fact/target_user/
        created_at/weight/status (без служебных деталей), как get_rag_facts."""
        ts = int(now_ts if now_ts is not None else time.time())
        sql = ("SELECT id, fact, target_user, created_at, weight, status "
               "FROM graph_facts WHERE chat_id = ? AND status = 'chat_meme' "
               "AND (expires_at IS NULL OR expires_at > ?) ")
        params: list = [chat_id, ts]
        if target_user is not None:
            sql += "AND target_user = ? "
            params.append(target_user)
        sql += "ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        cursor = await self.db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]

    # ── F1 раунд 10.21 (spec §3.2.1, ADR-1021-1 §8): сгенерированный портрет
    #    Слоя Б — производная строка graph_facts.status='dossier_portrait'
    #    (нулевой DDL, v12). Статус ≠ 'confirmed' изолирует её от FTS-RAG/KNN/
    #    get_persona_card/get_persona_names/get_dream_candidates/list_chat_memes/
    #    _list_orphan_facts. Ручные persona_dossier_overrides НЕ трогаются.

    async def get_generated_dossier(self, chat_id: int,
                                    target_user: str) -> dict | None:
        """Сгенерированный портрет Слоя Б для (chat, target) или None.

        Fail-open: ошибка чтения/битый `belief_meta` → None / пустые списки.
        Возврат: {portrait, patterns, themes, generated, generator,
        updated_at}."""
        target = str(target_user or "").strip()
        if not target:
            return None
        try:
            cursor = await self.db.execute(
                "SELECT fact, belief_meta, created_at FROM graph_facts "
                "WHERE chat_id = ? AND target_user = ? "
                "AND status = 'dossier_portrait' ORDER BY id DESC LIMIT 1",
                (int(chat_id), target))
            row = await cursor.fetchone()
        except Exception:
            logger.warning(
                "[database] generated dossier read failed — fail-open | "
                "chat=%s", chat_id, exc_info=True)
            return None
        if not row:
            return None
        meta: dict = {}
        raw_meta = row["belief_meta"]
        if raw_meta:
            try:
                parsed = json.loads(raw_meta)
                if isinstance(parsed, dict):
                    meta = parsed
            except (TypeError, ValueError):
                meta = {}

        def _strings(key: str) -> list[str]:
            value = meta.get(key)
            if not isinstance(value, (list, tuple)):
                return []
            return [str(x).strip() for x in value if str(x).strip()]

        return {
            "portrait": str(row["fact"] or ""),
            "patterns": _strings("patterns"),
            "themes": _strings("themes"),
            "generated": bool(meta.get("generated")),
            "generator": meta.get("generator"),
            "updated_at": int(meta.get("updated_at")
                              or row["created_at"] or 0),
        }

    @_serialized_write
    async def upsert_generated_dossier(self, chat_id: int, target_user: str,
                                       portrait: str | None, patterns=(),
                                       themes=(), now_ts: int | None = None
                                       ) -> int:
        """Идемпотентная запись портрета Слоя Б (spec §3.2.1).

        Ровно одна строка `graph_facts.status='dossier_portrait'` на
        (chat, target): SELECT → FTS-safe UPDATE либо insert_graph_fact.
        `fact`=непустой портрет, иначе детерминированный рендер
        patterns/themes; если всё пусто — строка НЕ создаётся (0). Схема/DDL
        не меняются (v12). Возвращает id строки (0 — нечего писать).

        FIX mca-04b (инвариант 10, §8.3.3/§8.3.4): обновление НЕ стирает
        долгосрочную картину — прежний текст портрета сохраняется в
        `belief_meta.previous_text` + bounded-истории `portrait_history`
        (версионирование изменений во времени; старое место работы не
        удаляется только потому, что появилось новое). Накопленные личные
        факты (`unconfirmed` person_facts) этой функцией не трогаются."""
        from services.dossier_prompts import render_generated_portrait

        target = str(target_user or "").strip()
        if not target:
            return 0
        pat = [str(x).strip() for x in (patterns or []) if str(x).strip()]
        th = [str(x).strip() for x in (themes or []) if str(x).strip()]
        text = render_generated_portrait(portrait, pat, th)
        if not text:
            return 0
        now = int(now_ts if now_ts is not None else time.time())
        cursor = await self.db.execute(
            "SELECT id, belief_meta FROM graph_facts WHERE chat_id = ? "
            "AND target_user = ? AND status = 'dossier_portrait' "
            "ORDER BY id DESC LIMIT 1", (int(chat_id), target))
        row = await cursor.fetchone()
        if row is None:
            meta_json = json.dumps({
                "generated": True,
                "generator": "layer_b",
                "contract_version": 2,
                "patterns": pat,
                "themes": th,
                "previous_text": text,
                "updated_at": now,
            }, ensure_ascii=False)
            return await self.insert_graph_fact(
                chat_id, text, "chat_history", None, target_user=target,
                status="dossier_portrait", kind="fact", weight=0.3,
                belief_meta=meta_json)
        fact_id = int(row["id"])
        prev_meta: dict = {}
        try:
            parsed = json.loads(row["belief_meta"] or "{}")
            if isinstance(parsed, dict):
                prev_meta = parsed
        except (TypeError, ValueError):
            prev_meta = {}
        history = list(prev_meta.get("portrait_history") or [])
        prev_text = prev_meta.get("previous_text")
        if prev_text:
            history.append({"text": str(prev_text)[:400],
                            "updated_at": int(prev_meta.get("updated_at")
                                              or 0)})
        history = history[-4:]
        prev_meta.update({
            "generated": True,
            "generator": "layer_b",
            "contract_version": 2,
            "patterns": pat,
            "themes": th,
            "previous_text": text,
            "portrait_history": history,
            "updated_at": now,
        })
        meta_json = json.dumps(prev_meta, ensure_ascii=False)
        await self.db.execute(
            "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
        await self.db.execute(
            "UPDATE graph_facts SET fact = ?, belief_meta = ?, weight = ?, "
            "created_at = ? WHERE id = ?",
            (text, meta_json, 0.3, now, fact_id))
        await self.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, text))
        await self.db.commit()
        return fact_id

    # ── F5 (cognition-dashboard-round1013, spec §3.3–§3.5): read-хелперы
    #    дашборда «Осмысление» (граф/статистика/время последнего сна).
    #    Только аддитивные SELECT: ноль DDL, R16/R17-safe (id/имена/типы/
    #    счётчики — без эмбеддингов и сырых секретов). ────────────────────

    async def last_run_at(self, kinds: tuple[str, ...],
                          chat_id: int | None = None) -> int | None:
        """MAX(run_at) по выбранным kind из memory_dream_log (spec §3.2:
        last_run_at обычного/глубокого сна). kinds пусто → None."""
        if not kinds:
            return None
        placeholders = ",".join("?" for _ in kinds)
        sql = ("SELECT MAX(run_at) AS ts FROM memory_dream_log "
               "WHERE kind IN (" + placeholders + ")")
        params: list = list(kinds)
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["ts"]) if row and row["ts"] is not None else None

    async def sum_dream_tokens(self, since_ts: int,
                               chat_id: int | None = None) -> int:
        """Сумма tokens memory_dream_log за период (spec §3.2: state
        'limit_exhausted' — суточный бюджет токенов сна). Fail-safe 0."""
        sql = ("SELECT COALESCE(SUM(tokens), 0) AS t FROM memory_dream_log "
               "WHERE run_at >= ?")
        params: list = [int(since_ts)]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return int(row["t"]) if row else 0

    async def _belief_participation_blob(self, chat_id: int | None) -> str:
        """Текст живых Убеждений/Парадигм чата (casefold, ё→е, '\\n'-склейка).

        F3 (ADR-1018-3 D4): узел «участвует в Убеждении/Парадигме», если его
        entity_name встречается в тексте живого belief (`kind='belief'`,
        `status='confirmed'`, `supersedes IS NULL` — заменённые не считаем).
        Живых beliefs немного → bounded-выборка; матчинг в Python (SQLite
        lower() не умеет кириллицу). B3-4: нормализуем ё→е заранее — сравнение
        идёт по ГРАНИЦАМ ТОКЕНОВ (regex в `graph_snapshot`), а не по подстроке
        (иначе «тема» матчилась бы внутри «система», «дом» — внутри
        «домашний»). Пусто/ошибка → '' (множитель ×1, fail-open).
        """
        try:
            sql = ("SELECT fact FROM graph_facts "
                   "WHERE kind = 'belief' AND status = 'confirmed' "
                   "AND supersedes IS NULL")
            params: list = []
            if chat_id is not None:
                sql += " AND chat_id = ?"
                params.append(int(chat_id))
            cursor = await self.db.execute(sql, params)
            rows = await cursor.fetchall()
        except Exception:
            logger.warning("[database] belief blob failed — ×1 (fail-open)",
                           exc_info=True)
            return ""
        return "\n".join(
            str(r["fact"] or "").casefold().replace("ё", "е") for r in rows)

    @staticmethod
    def _belief_name_participates(name: str, token_set: set[str],
                                  padded: str) -> bool:
        """S10.18-30: O(1)-аналог прежнего `re.search` по belief-блобу.

        Семантика та же (границы токенов `(?<![\\wё])…(?![\\wё])`, B3-4):
          * однословное имя — точное совпадение с токеном блоба: «тема» ⊄
            «система», «дом» ⊄ «домашний» (подстрока ×2 не даёт);
          * многословное имя (пробел/дефис/иной не-словный разделитель) —
            непрерывная последовательность его слов внутри padded-строки
            токенов блоба («тема дня» матчится, разорванные слова — нет).

        `name` уже casefold + ё→е; `token_set`/`padded` строятся один раз на
        весь вызов `graph_snapshot`. Пустой блоб/имя короче 2 символов → False.
        """
        if not token_set or len(name) < 2:
            return False
        words = re.findall(r"[\wё]+", name)
        if not words:
            return False
        if len(words) == 1:
            # Однословное — точное совпадение токена (не подстрока).
            return name in token_set
        # Многословное — непрерывная последовательность слов в padded.
        return f" {' '.join(words)} " in padded

    async def graph_snapshot(self, chat_id: int | None = None,
                             max_nodes: int = 800,
                             max_edges: int = 2400,
                             seed_nodes: int = 150) -> dict:
        """Узлы/рёбра SQLite GraphRAG для force-directed графа (F3 —
        graph-density-scoring-stoplist, ADR-1018-3; SUPERSEDE ADR-1015-2).

        Алгоритм (read-only):
          1. Score узла = **Σ importance** инцидентных рёбер (НЕ degree):
             importance ребра = `COALESCE(graph_facts.importance, edges.weight)`
             через новый `edges.fact_id` (v10). Legacy-рёбра с NULL `fact_id`
             деградируют к повторяемости (`weight`) — не «фейковый вес», а
             честная обработка исторических данных без provenance.
          2. Сиды — топ-`seed_nodes` по `score DESC, degree DESC, id ASC`
             ПОСЛЕ фильтра STOP_LIST центров (`services.graph_stoplist`;
             периферия сохраняется) и с ×2 для узлов-участников Убеждений/
             Парадигм. Кандидатный пул для ранжирования — bounded
             `max(seed_nodes × 10, 2000)`.
          3. Все смежные сидам узлы (окрестность 1 шаг).
          4. Рёбра — только с ОБОИМИ концами внутри набора узлов (S10.13-14:
             висячих рёбер нет).
          5. Сироты (узел без рёбер внутри итоговой выборки) удаляются.
          6. Финальный cap `max_nodes`/`max_edges` — ПОСЛЕ раскрытия/очистки.

        R16: id — ключ, label — entity_name, group — entity_type, degree
        сохранён (фронт `_graphSignature`; degree — отдельная метрика, НЕ
        сортировка). `truncated` — упёрлись в cap узлов/рёбер либо отброшены
        сироты."""
        chat = int(chat_id) if chat_id is not None else None
        seed_n = max(1, int(seed_nodes))
        pool_n = max(seed_n * 10, 2000)
        scope = " AND e.chat_id = ?" if chat is not None else ""
        scope_params: list = [chat, chat] if chat is not None else []

        nwhere = ["n.entity_name IS NOT NULL", "n.entity_name != ''"]
        nparams: list = []
        if chat is not None:
            nwhere.append("n.chat_id = ?")
            nparams.append(chat)

        # (1) Кандидатный пул: score = Σ importance инцидентных рёбер.
        score_sql = (
            "WITH re AS ("
            "  SELECT e.source_id AS nid, e.target_id AS oid, e.id AS eid"
            "   FROM edges e WHERE e.origin != 'bot_direct_reply'" + scope +
            "  UNION ALL"
            "  SELECT e.target_id AS nid, e.source_id AS oid, e.id AS eid"
            "   FROM edges e WHERE e.origin != 'bot_direct_reply'" + scope + "),"
            " imp AS ("
            "  SELECT e.id AS eid, COALESCE(f.importance, e.weight) AS eimp"
            "   FROM edges e LEFT JOIN graph_facts f ON f.id = e.fact_id"
            "   WHERE e.origin != 'bot_direct_reply'" + scope + "),"
            " deg AS (SELECT nid, COUNT(*) AS degree FROM re GROUP BY nid),"
            " score AS (SELECT r.nid AS nid, SUM(i.eimp) AS s"
            "           FROM re r JOIN imp i ON i.eid = r.eid GROUP BY r.nid)"
            " SELECT n.id AS id, n.entity_name AS label, d.degree AS degree,"
            "        sc.s AS score"
            "  FROM score sc"
            "  JOIN nodes n ON n.id = sc.nid"
            "  JOIN deg d ON d.nid = sc.nid"
            " WHERE " + " AND ".join(nwhere) +
            " ORDER BY sc.s DESC, d.degree DESC, n.id ASC LIMIT ?")
        # score_sql использует scope ТРИ раза (re ×2 + imp ×1).
        cursor = await self.db.execute(
            score_sql,
            scope_params + ([chat] if chat is not None else [])
            + nparams + [int(pool_n)])
        rows = [dict(r) for r in await cursor.fetchall()]

        # (2) STOP_LIST центров (только сиды!) + ×2 за Убеждение/Парадигму.
        #     Ranking в Python: SQLite lower() не понижает кириллицу.
        # S10.18-30 (perf): прежде ×2-фаза делала per-node `re.search(name, blob)`
        # — доминирующая стоимость (≈176 мс на 2000 строк при blob 5 КБ; до
        # секунд при росте числа beliefs) и выполнялась в event loop на каждый
        # `GET /api/memory/graph`. Теперь токены блоба строятся ОДИН раз, а
        # проверка — O(1) на узел (границы токенов сохранены, см.
        # `_belief_name_participates`).
        belief_blob = await self._belief_participation_blob(chat)
        belief_tokens = (re.findall(r"[\wё]+", belief_blob)
                         if belief_blob else [])
        token_set = set(belief_tokens)
        padded = (" " + " ".join(belief_tokens) + " ") if belief_tokens else ""
        ranked: list[tuple[float, int, int]] = []
        for r in rows:
            label = str(r["label"] or r["id"])
            if is_center_stopword(label):
                continue
            score = float(r["score"] or 0)
            name = label.strip().casefold().replace("ё", "е")
            # B3-4: матч по ГРАНИЦАМ ТОКЕНОВ, не подстрокой. «тема» не должна
            # получать ×2 от «система», «дом» — от «домашний». Многословные
            # имена поддерживаются (границы `\w` — на краях строки).
            if self._belief_name_participates(name, token_set, padded):
                score *= 2.0
            ranked.append((score, int(r["degree"] or 0), int(r["id"])))
        ranked.sort(key=lambda t: (-t[0], -t[1], t[2]))
        seed_ids = [t[2] for t in ranked[:seed_n]]
        if not seed_ids:
            return {"nodes": [], "edges": [], "truncated": False}

        # (3-4) Окрестность сидов + рёбра строго с обоими концами (S10.13-14).
        seed_values = ",".join("(?)" for _ in seed_ids)
        adj_sql = (
            "WITH re AS ("
            "  SELECT e.source_id AS nid, e.target_id AS oid FROM edges e"
            "   WHERE e.origin != 'bot_direct_reply'" + scope +
            "  UNION ALL"
            "  SELECT e.target_id AS nid, e.source_id AS oid FROM edges e"
            "   WHERE e.origin != 'bot_direct_reply'" + scope + "),"
            " deg AS (SELECT nid, COUNT(*) AS degree FROM re GROUP BY nid),"
            " seed(nid) AS (VALUES " + seed_values + "),"
            " adj AS (SELECT DISTINCT r.nid FROM re r"
            "          WHERE r.oid IN (SELECT nid FROM seed)),"
            " cand AS (SELECT nid FROM seed UNION SELECT nid FROM adj)"
            " SELECT n.id AS id, n.entity_name AS label,"
            "        n.entity_type AS grp, d.degree AS degree"
            "  FROM cand c"
            "  JOIN nodes n ON n.id = c.nid"
            "  JOIN deg d ON d.nid = c.nid"
            " WHERE " + " AND ".join(nwhere) +
            " ORDER BY (c.nid IN (SELECT nid FROM seed)) DESC,"
            "          d.degree DESC, n.id ASC LIMIT ?")
        cursor = await self.db.execute(
            adj_sql,
            scope_params + seed_ids + nparams + [int(max_nodes) + 1])
        rows = [dict(r) for r in await cursor.fetchall()]
        truncated_nodes = len(rows) > max_nodes
        rows = rows[:max_nodes]
        nodes = [{"id": int(r["id"]),
                  "label": str(r["label"] or r["id"]),
                  "group": str(r["grp"] or "topic"),
                  "degree": int(r["degree"] or 0)} for r in rows]
        node_ids = [n["id"] for n in nodes]
        if not node_ids:
            return {"nodes": [], "edges": [], "truncated": False}

        # Рёбра строго с обоими концами в наборе (S10.13-14).
        marks = ",".join("?" for _ in node_ids)
        ewhere = ["source_id IN (" + marks + ")",
                  "target_id IN (" + marks + ")",
                  "origin != 'bot_direct_reply'"]
        eparams: list = node_ids + node_ids
        if chat is not None:
            ewhere.append("chat_id = ?")
            eparams.append(chat)
        cursor = await self.db.execute(
            "SELECT source_id, target_id, relation_type, weight FROM edges "
            "WHERE " + " AND ".join(ewhere) +
            " ORDER BY weight DESC, id DESC LIMIT ?",
            eparams + [int(max_edges) + 1])
        erows = [dict(r) for r in await cursor.fetchall()]
        truncated_edges = len(erows) > max_edges
        erows = erows[:max_edges]
        edges = [{"from": int(r["source_id"]), "to": int(r["target_id"]),
                  "label": str(r["relation_type"] or ""),
                  "weight": int(r["weight"] or 1)} for r in erows]

        # Очистка сирот: узел без рёбер ВНУТРИ выборки (после edge-cap).
        edge_nodes = {e["from"] for e in edges} | {e["to"] for e in edges}
        orphans = [n for n in nodes if n["id"] not in edge_nodes]
        if orphans:
            nodes = [n for n in nodes if n["id"] in edge_nodes]

        return {"nodes": nodes, "edges": edges,
                "truncated": bool(truncated_nodes or truncated_edges
                                  or orphans)}

    async def graph_stats(self, chat_id: int | None = None) -> dict:
        """Счётчики «Интеллект и Память» (spec §3.4) + граф-статистика для
        «Модулей» (§4.4). R17-safe — только числа; chat_id=None → вся база."""

        def _scope(sql: str) -> tuple[str, list]:
            params: list = []
            if chat_id is not None:
                sql += " AND chat_id = ?"
                params.append(int(chat_id))
            return sql, params

        async def _one(sql: str, params: list) -> int:
            cursor = await self.db.execute(sql, params)
            row = await cursor.fetchone()
            return int(row["c"]) if row and row["c"] is not None else 0

        out = {"facts": 0, "beliefs": 0, "archived_beliefs": 0,
               "protected_facts": 0, "paradigms": 0, "memes": 0,
               "graph_nodes": 0, "graph_edges": 0, "relation_types": 0,
               # Раунд 10.14 (F1, spec §3.6): отдельный счётчик self-фактов
               # (мониторинг F4) — из «facts» они исключены.
               "bot_self_replies": 0}
        sql, p = _scope("SELECT COUNT(*) AS c FROM graph_facts "
                        "WHERE kind = 'fact' AND status = 'confirmed' "
                        "AND origin != 'bot_self_reply'")
        out["facts"] = await _one(sql, p)
        sql, p = _scope("SELECT COUNT(*) AS c FROM graph_facts "
                        "WHERE origin = 'bot_self_reply'")
        out["bot_self_replies"] = await _one(sql, p)
        # S10.13-6: «Убеждений» = kind='belief' без F3-парадигм (у них свой
        # счётчик `paradigms`), иначе парадигмы считались дважды.
        sql, p = _scope("SELECT COUNT(*) AS c FROM graph_facts "
                        "WHERE kind = 'belief' "
                        "AND (belief_meta IS NULL OR (belief_meta NOT LIKE ? "
                        "AND belief_meta NOT LIKE ?))")
        out["beliefs"] = await _one(
            sql, ['%"type":"paradigm"%', '%"type": "paradigm"%'] + list(p))
        # S10.13-6b: `archived_beliefs` — тот же фильтр F3-парадигм, что у
        # `beliefs`/`count_beliefs_by_status`, иначе счётчики расходятся.
        sql, p = _scope("SELECT COUNT(*) AS c FROM graph_facts "
                        "WHERE kind = 'belief' AND status = 'archived_belief' "
                        "AND (belief_meta IS NULL OR (belief_meta NOT LIKE ? "
                        "AND belief_meta NOT LIKE ?))")
        out["archived_beliefs"] = await _one(
            sql, ['%"type":"paradigm"%', '%"type": "paradigm"%'] + list(p))
        sql, p = _scope("SELECT COUNT(*) AS c FROM protected_facts WHERE 1=1")
        out["protected_facts"] = await _one(sql, p)
        out["paradigms"] = await self.count_paradigms(chat_id)
        sql, p = _scope("SELECT COUNT(*) AS c FROM graph_facts "
                        "WHERE status = 'chat_meme'")
        out["memes"] = await _one(sql, p)
        # Граф-статистика (узлы/рёбра/типы связей) — для «Модулей».
        nwhere = "WHERE entity_name IS NOT NULL AND entity_name != ''"
        nparams: list = []
        if chat_id is not None:
            nwhere += " AND chat_id = ?"
            nparams.append(int(chat_id))
        out["graph_nodes"] = await _one("SELECT COUNT(*) AS c FROM nodes "
                                        + nwhere, nparams)
        ewhere = "WHERE origin != 'bot_direct_reply'"
        eparams: list = []
        if chat_id is not None:
            ewhere += " AND chat_id = ?"
            eparams.append(int(chat_id))
        out["graph_edges"] = await _one("SELECT COUNT(*) AS c FROM edges "
                                        + ewhere, eparams)
        out["relation_types"] = await _one(
            "SELECT COUNT(DISTINCT relation_type) AS c FROM edges " + ewhere,
            eparams)
        return out