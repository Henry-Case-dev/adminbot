"""B11 (asap8-v6.3, REQ-B11/SCOPE/CHAIN/E2E) — read-only генератор отчёта
«Интеграционная проверка скрытых фоновых механизмов».

Для 10 механизмов — сон, глубокий сон, пересмотр убеждений, парадигмы,
self-model/traits, graph memory, инкрементальный embedding/backfill,
Experience, Initiative, Summary scheduler — собирает цепочку (REQ-B11-CHAIN):

    название → gate effective (env + settings-default + PG global + PG chat)
    → последняя попытка (время/ошибка/skip reason) → реальный вход (есть ли
    данные) → producer registered? → последний job/run + результат записи
    → использованное в ответе/поведении (если трекается) → 24h/7d счётчики.

Источники — ТОЛЬКО реальные таблицы (task_jobs, mca_events, memory_dream_log,
dream_state, graph_facts, mca_belief_reviews, mca_trait_observations,
mca_self_identity, mca_embedding_index_generations, mca_experience_*,
mca_lessons/mca_lesson_applications, mca_intents, summary_runs,
smart_messages, embedding_quota_state) + code-реестр процессов
(`services.mca_process_registry`) + env/настройки. Никаких dummy-счётчиков.

Диагноз различает (REQ-B11-E2E): недостаток входов (`no_input`) / отключённый
producer (`producer_off`) / cursor stalled (`cursor_stalled`) / worker
crashed (`worker_crashed`) / неверные TTL (`ttl_due`) / никогда не
запускался (`never_run`) / техошибка последней попытки (`attention`) / ok.
«Включено, но не запускалось» НЕ перекрашивается в зелёное (never_run).

Read-only: SQLite открывается в `mode=ro`; PG (если задан DSN и доступен
asyncpg) — только SELECT; каждая секция fail-soft → `unavailable` с причиной.
Запуск (прод, Wave 4):

    py -3 tools/v63_b11_mechanisms_report.py --db local_database.db \
        [--chat-id -100...] [--json report.json] [--pg-dsn $POSTGRES_DSN]

Без аргументов: JSON в stdout + человекочитаемый хвост. Код выхода — 0,
если отчёт собран (диагнозы механизмов на код выхода не влияют).
"""
from __future__ import annotations

import sys
from pathlib import Path

# REV-W3PRE N2: запуск из корня репо без PYTHONPATH (прецедент
# config_snapshot_diff.py) — иначе `ModuleNotFoundError: No module named
# 'config'`; ломает задокументированный прод-прогон Wave 4.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from typing import Any

# ── диагнозы (фиксированный словарь — контракт REQ-B11-E2E) ─────────────────
DIAG_OK = "ok"
DIAG_PRODUCER_OFF = "producer_off"
DIAG_NO_INPUT = "no_input"
DIAG_CURSOR_STALLED = "cursor_stalled"
DIAG_WORKER_CRASHED = "worker_crashed"
DIAG_TTL_DUE = "ttl_due"
DIAG_NEVER_RUN = "never_run"
DIAG_ATTENTION = "attention"
DIAG_DEGRADED = "degraded"
DIAG_UNKNOWN = "unknown"
DIAG_UNAVAILABLE = "unavailable"

# ── словари статусов попыток (реальные писатели, не догадки) ────────────────
# Сравнение — casefold: `summary_runs.state` пишется в ВЕРХНЕМ регистре
# (`services.summary_run_store.TERMINAL_STATES` = DONE/DEGRADED/FAILED), а
# `mca_events.outcome`/`task_jobs.status` — в нижнем (services/mca_events.py:
# success/failed/skipped/cancelled/interrupted/...;
# services/task_supervisor.py: queued/running/completed/failed/cancelled/
# interrupted).
_FAILED_ATTEMPT_STATUSES = frozenset({
    "failed", "failure", "error", "cancelled", "canceled", "interrupted",
    "crashed", "timeout", "timed_out",
})
_DEGRADED_ATTEMPT_STATUSES = frozenset({"degraded", "partial"})
_OK_ATTEMPT_STATUSES = frozenset({
    "done", "ok", "success", "succeeded", "completed", "published",
    "kept", "narrowed", "split", "disputed", "replaced", "pass", "applied",
})
# `status_semantics="classification"` — статус-колонка описывает не исход
# (например `mca_trait_observations.subject_status`: self/other/ambiguous),
# поэтому словарная проверка к ней не применяется.
_STATUS_SEMANTICS_OUTCOME = "outcome"

DEFAULT_STALE_SECONDS = 30 * 60      # heartbeat старше → worker crashed
_WINDOW_24H = 24 * 3600
_WINDOW_7D = 7 * 86400

HOUR = 3600

# ── реестр механизмов (REQ-B11-SCOPE; порядок = порядок ТЗ) ─────────────────
# catalog_keys — PG dotted-ключи (bot_settings/chat_profiles.chat_params);
# env_keys — env/имена settings; registry — process_id код-реестра.


def _mechanism_specs() -> list[dict]:
    return [
        {
            "key": "dream",
            "title": "Сон (dream)",
            "registry": ["sleep.dream"],
            "env_keys": {"DREAM_ENABLED": True},
            "catalog_keys": ["memory.dream_enabled"],
            "event_names": ["sleep_dream"],
            "event_components": ["dream"],
            "job_kinds": [],
            "tables": ["memory_dream_log", "dream_state", "graph_facts",
                       "mca_events"],
            "input_sql": "SELECT COUNT(*) AS c FROM graph_facts",
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM graph_facts "
                                "WHERE created_at >= ?"),
        },
        {
            "key": "deep_sleep",
            "title": "Глубокий сон (deep sleep)",
            "registry": ["sleep.dream"],
            "env_keys": {"DEEP_SLEEP_ENABLED": False},
            "catalog_keys": ["memory.deep_sleep_enabled",
                             "memory.deep_sleep_trigger"],
            "event_names": ["sleep_dream", "deep_sleep_paradigm"],
            "event_components": ["dream"],
            "job_kinds": [],
            "tables": ["memory_dream_log", "graph_facts", "mca_events"],
            "input_sql": "SELECT COUNT(*) AS c FROM graph_facts",
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM graph_facts "
                                "WHERE created_at >= ?"),
        },
        {
            "key": "belief_revision",
            "title": "Пересмотр убеждений (belief revision)",
            "registry": ["sleep.dream"],
            "env_keys": {"MCA_DREAM_REVISION_QUEUE_ENABLED": True},
            "catalog_keys": ["memory.dream_revision_queue_enabled"],
            "event_names": ["belief_review"],
            "event_components": ["dream"],
            "job_kinds": [],
            "tables": ["mca_belief_reviews", "graph_facts",
                       "memory_dream_log", "mca_events"],
            "input_sql": ("SELECT COUNT(*) AS c FROM graph_facts "
                          "WHERE kind = 'belief'"),
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM graph_facts "
                                "WHERE kind = 'belief' AND created_at >= ?"),
        },
        {
            "key": "paradigms",
            "title": "Парадигмы (paradigms)",
            "registry": ["sleep.dream"],
            "env_keys": {"DEEP_SLEEP_ENABLED": False,
                         "DEEP_SLEEP_MAX_PARADIGMS": 3},
            "catalog_keys": ["memory.deep_sleep_enabled"],
            "event_names": ["deep_sleep_paradigm"],
            "event_components": ["dream"],
            "job_kinds": [],
            "tables": ["graph_facts", "memory_dream_log", "mca_events"],
            "input_sql": ("SELECT COUNT(*) AS c FROM graph_facts WHERE "
                          "(belief_meta LIKE '%\"type\":\"paradigm\"%' OR "
                          "belief_meta LIKE '%\"type\": \"paradigm\"%')"),
            "fresh_input_sql": None,
        },
        {
            "key": "self_model",
            "title": "Self-model / traits (характер)",
            "registry": ["self.model", "persona.traits"],
            "env_keys": {"MCA_SELF_MODEL_ENABLED": True},
            "catalog_keys": ["flags.self_model_enabled",
                             "flags.trait_rules_enabled"],
            "event_names": ["self_model_update", "traits_update"],
            "event_components": ["self_model"],
            "job_kinds": [],
            "tables": ["mca_trait_observations", "mca_self_identity",
                       "mca_behavior_rules", "mca_events"],
            "input_sql": ("SELECT COUNT(*) AS c FROM "
                          "mca_trait_observations"),
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM "
                                "mca_trait_observations "
                                "WHERE observed_at >= ?"),
        },
        {
            "key": "graph_memory",
            "title": "Graph memory (GraphRAG)",
            "registry": ["embeddings.index"],
            "env_keys": {"GRAPHRAG_SHADOW_REBUILD_ENABLED": True},
            "catalog_keys": ["flags.graphrag_rebuild_enabled"],
            "event_names": ["graphrag_rebuild"],
            "event_components": ["graphrag"],
            "job_kinds": ["graphrag_rebuild"],
            "tables": ["graph_facts", "nodes", "edges",
                       "mca_embedding_index_generations", "task_jobs",
                       "mca_events"],
            "input_sql": "SELECT COUNT(*) AS c FROM graph_facts",
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM graph_facts "
                                "WHERE created_at >= ?"),
            "backlog_sql": ("SELECT (SELECT COUNT(*) FROM graph_facts) - "
                            "(SELECT COUNT(*) FROM graph_facts_vec) AS c"),
        },
        {
            "key": "embeddings",
            "title": "Инкрементальный embedding/backfill",
            "registry": ["embeddings.index"],
            "env_keys": {"EMBED_CONTROL_PLANE_ENABLED": True,
                         "EMBED_ASYNC_BATCH_ENABLED": False},
            "catalog_keys": ["flags.embeddings_enabled"],
            "event_names": ["embedding_index"],
            "event_components": ["embeddings"],
            "job_kinds": ["graphrag_rebuild", "dossier_rebuild"],
            "tables": ["mca_embedding_index_generations",
                       "embedding_quota_state", "graph_facts", "task_jobs",
                       "mca_events"],
            "input_sql": "SELECT COUNT(*) AS c FROM graph_facts",
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM graph_facts "
                                "WHERE created_at >= ?"),
            "backlog_sql": ("SELECT (SELECT COUNT(*) FROM graph_facts) - "
                            "(SELECT COUNT(*) FROM graph_facts_vec) AS c"),
        },
        {
            "key": "experience",
            "title": "Experience (семантическое обучение)",
            "registry": ["self_learning.run"],
            "env_keys": {"MCA_EXPERIENCE_LESSONS_ENABLED": True,
                         "MCA_EXPERIENCE_REVIEW_ENABLED": True},
            "catalog_keys": ["memory.experience_learning_enabled",
                             "memory.experience_review_cadence"],
            "event_names": ["experience_review", "lesson_applied"],
            "event_components": ["experience"],
            "job_kinds": ["experience.review"],
            "tables": ["mca_experience_episodes", "mca_experience_feedback",
                       "mca_lessons", "mca_lesson_applications",
                       "task_jobs", "mca_events"],
            "input_sql": ("SELECT COUNT(*) AS c FROM "
                          "mca_experience_episodes"),
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM "
                                "mca_experience_episodes "
                                "WHERE created_at >= ?"),
        },
        {
            "key": "initiative",
            "title": "Initiative (проактивный наблюдатель)",
            "registry": ["intent.initiative"],
            "env_keys": {"INITIATIVE_OBSERVER_ENABLED": True,
                         "INITIATIVE_ENABLED": True},
            "catalog_keys": ["flags.initiative_enabled"],
            "event_names": ["initiative_observe", "intent_decision"],
            "event_components": ["initiative", "intents"],
            "job_kinds": ["initiative.observe"],
            "tables": ["mca_intents", "task_jobs", "smart_messages",
                       "mca_events"],
            "input_sql": ("SELECT COUNT(*) AS c FROM smart_messages "
                          "WHERE timestamp >= ?"),
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM smart_messages "
                                "WHERE timestamp >= ?"),
        },
        {
            "key": "summary_scheduler",
            "title": "Summary scheduler (планировщик пересказа)",
            "registry": ["summary.window", "summary.publish"],
            "env_keys": {"SUMMARY_ENABLED": True,
                         "SYSTEM2_SUMMARY_ENABLED": True},
            "catalog_keys": ["memory.summary_enabled"],
            "event_names": ["summary_run", "summary_publish"],
            "event_components": ["summary"],
            "job_kinds": [],
            "tables": ["summary_runs", "summary_run_stages",
                       "chat_running_summary", "smart_messages",
                       "mca_events"],
            "input_sql": ("SELECT COUNT(*) AS c FROM smart_messages "
                          "WHERE timestamp >= ?"),
            "fresh_input_sql": ("SELECT COUNT(*) AS c FROM smart_messages "
                                "WHERE timestamp >= ?"),
        },
    ]


# ── read-only SQLite (fail-soft per запрос) ──────────────────────────────────

class ReadOnlyDB:
    """sqlite3 в mode=ro: никогда не пишет и не мигрирует; каждый запрос
    fail-soft (пустой результат + запись ошибки в `errors`)."""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self.errors: list[str] = []
        self._missing: set[str] = set()
        self._vec_loaded: tuple[bool, str | None] | None = None
        try:
            self.conn = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, timeout=10.0)
            self.conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            self.conn = None
            self.errors.append(f"open: {exc}")

    def ok(self) -> bool:
        return self.conn is not None

    def table_exists(self, name: str) -> bool:
        if not self.ok():
            return False
        try:
            cur = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (str(name),))
            return cur.fetchone() is not None
        except sqlite3.Error:
            return False

    def q(self, sql: str, params: tuple = ()) -> list[dict] | None:
        """Fail-soft SELECT: [] при пустом результате, None при недоступной
        таблице/ошибке (вызывающий помечает секцию unavailable)."""
        if not self.ok():
            return None
        try:
            cur = self.conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.Error as exc:
            self.errors.append(f"{sql[:60]}: {exc}")
            return None

    def scalar(self, sql: str, params: tuple = ()) -> int | None:
        rows = self.q(sql, params)
        if rows is None:
            return None
        try:
            return int(rows[0].get("c", 0) or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return 0

    def scalar_with_error(self, sql: str, params: tuple = ()) \
            -> tuple[int | None, str | None]:
        """scalar + причина: (значение, None) либо (None, текст ошибки).

        Нужен там, где `None` нельзя отдавать без объяснения (backlog:
        `graph_facts_vec` — vec0-таблица, без загруженного расширения запрос
        падает и раньше давал молчаливый `null`)."""
        before = len(self.errors)
        rows = self.q(sql, params)
        if rows is None:
            reason = (self.errors[-1] if len(self.errors) > before
                      else "unknown read error")
            return None, reason
        try:
            return int(rows[0].get("c", 0) or 0), None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return None, f"unexpected result: {type(exc).__name__}"

    def ensure_vec(self) -> tuple[bool, str | None]:
        """Догрузить sqlite-vec в read-only коннект (idempotent, fail-soft).

        Нужно для чтения vec0-таблиц (`graph_facts_vec`, `smart_archive`).
        Загрузка расширения НЕ пишет в БД. Нет пакета/расширения →
        (False, причина) — вызывающий обязан отдать честный `unknown`."""
        if not self.ok():
            return False, "sqlite недоступна"
        if self._vec_loaded is not None:
            return self._vec_loaded
        try:
            import sqlite_vec
        except Exception as exc:       # noqa: BLE001 - fail-soft
            self._vec_loaded = (False, f"sqlite_vec не установлен: "
                                       f"{type(exc).__name__}")
            return self._vec_loaded
        try:
            self.conn.enable_load_extension(True)
            self.conn.load_extension(sqlite_vec.loadable_path())
        except Exception as exc:       # noqa: BLE001 - fail-soft
            self._vec_loaded = (False, f"sqlite_vec не загрузился: "
                                       f"{type(exc).__name__}: {exc}")
            return self._vec_loaded
        finally:
            try:
                self.conn.enable_load_extension(False)
            except sqlite3.Error:
                pass
        self._vec_loaded = (True, None)
        return self._vec_loaded

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass


# ── env/settings/PG слои гейта ───────────────────────────────────────────────

def _env_layer(env_keys: dict) -> dict:
    """env-слой: фактическое значение os.environ + settings-дефолт."""
    from config.settings import settings
    out: dict[str, dict] = {}
    for name, default in (env_keys or {}).items():
        raw = os.getenv(name)
        default_value = getattr(settings, name, default)
        if raw is None or str(raw).strip() == "":
            out[name] = {"value": bool(default_value), "source": "default",
                         "default": default_value}
        else:
            parsed = _parse_bool(raw, default_value)
            out[name] = {"value": parsed, "source": "env", "default":
                         default_value}
    return out


def _parse_bool(raw: str, default):
    text = str(raw).strip().casefold()
    if text in ("1", "true", "yes", "on", "да"):
        return True
    if text in ("0", "false", "no", "off", "нет"):
        return False
    try:
        return type(default)(text) if isinstance(default, int) else default
    except (TypeError, ValueError):
        return default


def _pg_value(raw):
    """bot_settings.value (TEXT/JSON) → bool/значение (fail-soft)."""
    if raw is None:
        return None
    text = str(raw).strip()
    low = text.casefold()
    if low in ("true", "1", "on", "yes"):
        return True
    if low in ("false", "0", "off", "no"):
        return False
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text or None


def _walk_dotted(params: dict, key: str):
    """Dotted-ключ в chat_params JSON: nested-walk с фолбэком на плоский
    ключ (прецедент chat_params._resolve_from_root)."""
    if not isinstance(params, dict):
        return None
    node: Any = params
    for part in str(key).split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return params.get(key)
    return node


async def _pg_gate_layer(dsn: str | None, catalog_keys: list[str],
                         chat_id: int | None) -> dict:
    """PG-слой (global bot_settings + chat_profiles.chat_params) — только
    SELECT; недоступен → {"available": False, "reason": ...}."""
    out: dict = {"available": False, "global": {}, "chat": {}}
    if not dsn:
        out["reason"] = "pg_dsn_not_provided"
        return out
    try:
        import asyncpg  # noqa: PLC0415 — опциональная зависимость скрипта
    except ImportError:
        out["reason"] = "asyncpg_unavailable"
        return out
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(dsn=dsn, timeout=10), timeout=15)
    except Exception as exc:
        out["reason"] = f"pg_connect_failed: {type(exc).__name__}"
        return out
    try:
        for key in catalog_keys or ():
            try:
                row = await conn.fetchrow(
                    "SELECT value FROM bot_settings WHERE key = $1", key)
            except Exception:
                row = None
            out["global"][key] = (_pg_value(row["value"])
                                  if row is not None else None)
        if chat_id is not None:
            try:
                row = await conn.fetchrow(
                    "SELECT chat_params FROM chat_profiles "
                    "WHERE chat_id = $1", int(chat_id))
                params = json.loads(row["chat_params"]) if row and \
                    row["chat_params"] else {}
                if not isinstance(params, dict):
                    params = {}
                for key in catalog_keys or ():
                    value = _walk_dotted(params, key)
                    out["chat"][key] = _pg_value(value) \
                        if isinstance(value, str) else value
            except Exception:
                out["chat"] = {"error": "chat_profile_read_failed"}
        out["available"] = True
        out.pop("reason", None)
    finally:
        try:
            await conn.close()
        except Exception:
            pass
    return out


def _gate_effective(env_layer: dict, pg_layer: dict, chat_id: int | None,
                    ) -> tuple[bool | None, str]:
    """Effective = master-env (ПЕРВЫЙ ключ spec — kill-switch producer'а;
    остальные env-ключи информационные) AND PG global AND PG chat.
    Источник решения — самый специфичный заданный слой (честно именуется)."""
    master = next(iter(env_layer), None)
    if master is not None:
        info = env_layer[master]
        if not info.get("value"):
            return False, f"{info.get('source')}:{master}=off"
        if info.get("source") == "env":
            return True, f"env:{master}=on"
    if pg_layer.get("available"):
        for key, value in (pg_layer.get("global") or {}).items():
            if value is not None and not value:
                return False, f"pg_global:{key}=off"
        if chat_id is not None:
            for key, value in (pg_layer.get("chat") or {}).items():
                if value is not None and not value:
                    return False, f"pg_chat:{key}=off"
    return True, "default_on"


# ── общие коллекторы (mca_events / task_jobs / реестр) ──────────────────────

def _events_window(db: ReadOnlyDB, *, event_names, components,
                   chat_id: int | None, since: int) -> dict | None:
    """Счётчики mca_events окна по event_name (+component); None —
    таблица недоступна."""
    if not db.table_exists("mca_events"):
        return None
    where = ["ts >= ?"]
    params: list = [int(since)]
    if event_names:
        where.append("event_name IN (%s)"
                     % ",".join("?" * len(event_names)))
        params.extend(event_names)
    if components:
        where.append("component IN (%s)"
                     % ",".join("?" * len(components)))
        params.extend(components)
    if chat_id is not None:
        where.append("chat_id = ?")
        params.append(int(chat_id))
    rows = db.q("SELECT event_name, outcome, COUNT(*) AS c FROM mca_events "
                f"WHERE {' AND '.join(where)} "
                "GROUP BY event_name, outcome", tuple(params))
    if rows is None:
        return None
    out: dict[str, dict] = {}
    for r in rows:
        by = out.setdefault(str(r["event_name"]), {})
        by[str(r["outcome"] or "?")] = int(r["c"] or 0)
    return out


def _last_event(db: ReadOnlyDB, *, event_names, components,
                chat_id: int | None) -> dict | None:
    if not db.table_exists("mca_events"):
        return None
    where = []
    params: list = []
    if event_names:
        where.append("event_name IN (%s)"
                     % ",".join("?" * len(event_names)))
        params.extend(event_names)
    if components:
        where.append("component IN (%s)"
                     % ",".join("?" * len(components)))
        params.extend(components)
    if chat_id is not None:
        where.append("chat_id = ?")
        params.append(int(chat_id))
    if not where:
        return None
    rows = db.q("SELECT ts, event_name, outcome, reason_code, stage, "
                "error_json FROM mca_events WHERE "
                f"{' AND '.join(where)} ORDER BY id DESC LIMIT 1",
                tuple(params))
    return rows[0] if rows else None


def _last_job(db: ReadOnlyDB, *, kinds: list[str], coalesce_keys:
              list[str]) -> dict | None:
    if not db.table_exists("task_jobs"):
        return None
    where = []
    params: list = []
    if kinds:
        where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
        params.extend(kinds)
    if coalesce_keys:
        where.append("coalesce_key IN (%s)"
                     % ",".join("?" * len(coalesce_keys)))
        params.extend(coalesce_keys)
    if not where:
        return None
    rows = db.q("SELECT job_id, kind, coalesce_key, status, reason_code, "
                "error_code, attempt, max_attempts, payload, heartbeat_at, "
                "created_at, updated_at, finished_at FROM task_jobs WHERE "
                f"{' OR '.join(where)} ORDER BY created_at DESC, "
                "job_id DESC LIMIT 1", tuple(params))
    return rows[0] if rows else None


def _job_window_counts(db: ReadOnlyDB, *, kinds: list[str],
                       coalesce_keys: list[str], since: int) -> dict | None:
    if not db.table_exists("task_jobs"):
        return None
    where = ["created_at >= ?"]
    params: list = [int(since)]
    if kinds:
        where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
        params.extend(kinds)
    if coalesce_keys:
        where.append("coalesce_key IN (%s)"
                     % ",".join("?" * len(coalesce_keys)))
        params.extend(coalesce_keys)
    rows = db.q("SELECT status, COUNT(*) AS c FROM task_jobs WHERE "
                f"{' AND '.join(where)} GROUP BY status", tuple(params))
    if rows is None:
        return None
    return {str(r["status"] or "?"): int(r["c"] or 0) for r in rows}


def _producer_registration(process_ids: list[str]) -> dict:
    """Producer registered? — из code-реестра процессов (не из БД): 
    декларация + kill-switch + инструментирование; disabled → producer_off
    слой кода."""
    try:
        from services import mca_process_registry as reg
    except Exception as exc:
        return {"registered": None, "reason": f"registry_import: {exc}"}
    out = {"registered": False, "processes": []}
    for pid in process_ids or ():
        proc = reg.get_process(pid)
        if proc is None:
            out["processes"].append({"process_id": pid, "declared": False})
            continue
        try:
            enabled = reg._process_enabled(proc)
        except Exception:
            enabled = None
        out["registered"] = True
        out["processes"].append({
            "process_id": pid,
            "declared": True,
            "enabled_gate": proc.enabled_gate,
            "enabled": enabled,
            "instrumented": proc.declared_instrumented,
            "event_names": list(proc.event_names),
        })
    return out


def _payload_cursor(payload_raw) -> dict:
    """cursor_ts/cursor_id из payload job (если есть) — для cursor-stalled."""
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {"cursor_ts": payload.get("cursor_ts"),
            "cursor_id": payload.get("cursor_id"),
            "counters": payload.get("counters")}


# ── диагноз (REQ-B11-E2E: причины различаются явно) ──────────────────────────

def diagnose(*, gate_effective: bool | None, gate_source: str,
             input_available: bool | None, last_attempt: dict | None,
             last_job: dict | None, now: int,
             stale_seconds: int = DEFAULT_STALE_SECONDS,
             backlog: int | None = None, ttl_seconds: int | None = None,
             sources_unavailable: bool = False) -> dict:
    """Правила (в порядке приоритета; каждая причина named):
      1. источники недоступны → unavailable (не зелёное);
      2. gate OFF (любой слой) → producer_off;
      3. входа нет → no_input;
      4. job queued/running с протухшим heartbeat → worker_crashed;
      5. job failed → worker_crashed;
      6. backlog растёт, а job давно завершён без прогресса → cursor_stalled;
      7. попыток не было → never_run («включено, но не запускалось»);
      8. последняя попытка ошибочна (failed/error/cancelled/interrupted —
         без учёта регистра) или публикация failed → attention;
      9. попытка деградировала (DEGRADED/partial) → degraded (не зелёное);
     10. статус попытки не из известного словаря → unknown (не зелёное);
     11. TTL пр_interval просрочен → ttl_due;
     12. иначе → ok."""
    if sources_unavailable:
        return {"code": DIAG_UNAVAILABLE,
                "detail": "источники секции недоступны (fail-soft)"}
    if gate_effective is False:
        return {"code": DIAG_PRODUCER_OFF,
                "detail": f"gate off ({gate_source})"}
    if input_available is False:
        return {"code": DIAG_NO_INPUT, "detail": "нет входных данных"}
    if last_job is not None:
        status = str(last_job.get("status") or "")
        if status in ("queued", "running"):
            hb = last_job.get("heartbeat_at") or last_job.get("updated_at") \
                or 0
            try:
                hb = int(hb or 0)
            except (TypeError, ValueError):
                hb = 0
            if hb and (int(now) - hb) > int(stale_seconds):
                return {"code": DIAG_WORKER_CRASHED,
                        "detail": (f"job {status}, heartbeat "
                                   f"{int(now) - hb}s назад > "
                                   f"{int(stale_seconds)}s")}
            return {"code": DIAG_OK,
                    "detail": f"job {status} жив (heartbeat свежий)"}
        if status in ("failed", "interrupted"):
            return {"code": DIAG_WORKER_CRASHED,
                    "detail": (f"последний job {status} "
                               f"(reason={last_job.get('reason_code')}, "
                               f"error={last_job.get('error_code')})")}
        if backlog is not None and int(backlog) > 0 and status == \
                "completed":
            finished = last_job.get("finished_at") or \
                last_job.get("updated_at") or 0
            try:
                age = int(now) - int(finished or 0)
            except (TypeError, ValueError):
                age = 0
            if age > int(stale_seconds):
                return {"code": DIAG_CURSOR_STALLED,
                        "detail": (f"backlog={backlog}, job completed "
                                   f"{age}s назад без прогресса")}
    if last_attempt is None:
        return {"code": DIAG_NEVER_RUN,
                "detail": "включено, но попыток не было (не зелёное)"}
    status_raw = str(last_attempt.get("status") or "").strip()
    if str(last_attempt.get("status_semantics")
           or _STATUS_SEMANTICS_OUTCOME) == _STATUS_SEMANTICS_OUTCOME:
        status = status_raw.casefold()
        if status in _FAILED_ATTEMPT_STATUSES:
            return {"code": DIAG_ATTENTION,
                    "detail": f"последняя попытка {status_raw} "
                              f"({last_attempt.get('detail')})"}
        # Публикация провалена при формально успешном state — тоже не зелёное
        # (summary_runs.publication_status пишется 'published'/'failed').
        publication = str(last_attempt.get("publication_status")
                          or "").strip().casefold()
        if publication == "failed":
            return {"code": DIAG_ATTENTION,
                    "detail": f"публикация failed "
                              f"(state={status_raw or '—'}, "
                              f"{last_attempt.get('detail')})"}
        if status in _DEGRADED_ATTEMPT_STATUSES:
            return {"code": DIAG_DEGRADED,
                    "detail": f"последняя попытка {status_raw} — резервный "
                              f"контур ({last_attempt.get('detail')})"}
        if status not in _OK_ATTEMPT_STATUSES:
            return {"code": DIAG_UNKNOWN,
                    "detail": (f"статус попытки {status_raw!r} не "
                               "распознан (не зелёное; REQ-B11-E2E)")}
    if ttl_seconds is not None:
        ts = int(last_attempt.get("ts") or 0)
        if ts and (int(now) - ts) > int(ttl_seconds):
            return {"code": DIAG_TTL_DUE,
                    "detail": f"последний запуск {int(now) - ts}s назад "
                              f"> TTL {int(ttl_seconds)}s"}
    return {"code": DIAG_OK, "detail": "gate on, вход есть, попытки свежие"}


# ── секции механизмов ────────────────────────────────────────────────────────

def _log_last_attempt(db: ReadOnlyDB, table: str, kinds: list[str],
                      *, chat_id: int | None, ts_col: str = "run_at",
                      status_col: str = "status",
                      kind_col: str | None = "kind",
                      detail_cols: tuple = ("tokens",)) -> dict | None:
    """Последняя попытка из журнала (memory_dream_log/nostalgia_log/
    mca_trait_observations). kind_col=None → без фильтра/группировки по
    kind (таблицы без колонки kind, напр. mca_trait_observations)."""
    if not db.table_exists(table):
        return None
    where = []
    params: list = []
    if kind_col and kinds:
        where.append(f"{kind_col} IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)
    if chat_id is not None:
        where.append("chat_id = ?")
        params.append(int(chat_id))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    kind_sel = f"{kind_col} AS kind, " if kind_col else "'' AS kind, "
    detail_sel = ", ".join(detail_cols) if detail_cols else "''"
    rows = db.q(f"SELECT {ts_col} AS ts, {status_col} AS status, "
                f"{kind_sel}{detail_sel} FROM {table} {where_sql} "
                f"ORDER BY {ts_col} DESC LIMIT 1", tuple(params))
    if not rows:
        return None
    row = rows[0]
    return {"ts": int(row.get("ts") or 0) or None,
            "status": str(row.get("status") or ""),
            "kind": str(row.get("kind") or ""),
            "source_table": table,
            "detail": ", ".join(f"{c}={row.get(c)}" for c in detail_cols)}


def _window_log_counts(db: ReadOnlyDB, table: str, kinds: list[str], *,
                       chat_id: int | None, since: int,
                       kind_col: str | None = "kind",
                       ts_col: str | None = None,
                       status_col: str = "status") -> dict | None:
    """Счётчики журнала за окно (по kind×status); kind_col=None — только
    status (таблицы без kind). None — таблица недоступна."""
    if not db.table_exists(table):
        return None
    ts_col = ts_col or db_col_ts(table)
    where = [f"{ts_col} >= ?"]
    params: list = [int(since)]
    if kind_col and kinds:
        where.append(f"{kind_col} IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)
    if chat_id is not None:
        where.append("chat_id = ?")
        params.append(int(chat_id))
    kind_sel = (f"{kind_col} AS kind, " if kind_col
                else "'' AS kind, ")
    rows = db.q(f"SELECT {kind_sel}{status_col} AS status, COUNT(*) AS c "
                f"FROM {table} WHERE {' AND '.join(where)} "
                f"GROUP BY {kind_col + ', ' if kind_col else ''}"
                f"{status_col}", tuple(params))
    if rows is None:
        return None
    out: dict[str, dict] = {}
    for r in rows:
        by = out.setdefault(str(r["kind"] or "?"), {})
        by[str(r["status"] or "?")] = int(r["c"] or 0)
    return out


def db_col_ts(table: str) -> str:
    """Колонка времени журнала (таблицы фиксированы — контракт схемы)."""
    return "observed_at" if table == "mca_trait_observations" else "run_at"


def _dream_section(db, spec, now, chat_id, stale_seconds) -> dict:
    kinds = ["run"]
    last = _log_last_attempt(db, "memory_dream_log", kinds, chat_id=chat_id)
    input_total = db.scalar(spec["input_sql"])
    fresh = None
    if spec.get("fresh_input_sql"):
        fresh = db.scalar(spec["fresh_input_sql"], (now - _WINDOW_24H,))
    state = None
    if db.table_exists("dream_state"):
        sql = "SELECT chat_id, last_run_at, last_processed_fact_id FROM " \
              "dream_state"
        params: tuple = ()
        if chat_id is not None:
            sql += " WHERE chat_id = ?"
            params = (int(chat_id),)
        rows = db.q(sql, params)
        state = rows[0] if rows else None
    return {
        "last_attempt": last,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": ({"state": "watermark",
                          "last_run_at": (state or {}).get("last_run_at"),
                          "last_processed_fact_id":
                              (state or {}).get("last_processed_fact_id")}
                         if state else {"state": "no_watermark"}),
        "used_in_response": {"tracked": True,
                             "source": "graph_facts(kind='belief')",
                             "beliefs_total": db.scalar(
                                 "SELECT COUNT(*) AS c FROM graph_facts "
                                 "WHERE kind = 'belief'")},
        "counters_24h": _window_log_counts(
            db, "memory_dream_log", ["run", "distilled", "skipped", "error"],
            chat_id=chat_id, since=now - _WINDOW_24H),
        "counters_7d": _window_log_counts(
            db, "memory_dream_log", ["run", "distilled", "skipped", "error"],
            chat_id=chat_id, since=now - _WINDOW_7D),
        "events_24h": _events_window(db, event_names=spec["event_names"],
                                     components=spec["event_components"],
                                     chat_id=chat_id,
                                     since=now - _WINDOW_24H),
        "events_7d": _events_window(db, event_names=spec["event_names"],
                                    components=spec["event_components"],
                                    chat_id=chat_id,
                                    since=now - _WINDOW_7D),
        "last_event": _last_event(db, event_names=spec["event_names"],
                                  components=spec["event_components"],
                                  chat_id=chat_id),
        "last_job": None,
        "job_24h": None,
        "job_7d": None,
        "ttl_seconds": 25 * HOUR,
        "extra": {},
    }


def _deep_section(db, spec, now, chat_id, stale_seconds) -> dict:
    last = _log_last_attempt(db, "memory_dream_log", ["deep_run"],
                             chat_id=chat_id)
    input_total = db.scalar(spec["input_sql"])
    fresh = None
    if spec.get("fresh_input_sql"):
        fresh = db.scalar(spec["fresh_input_sql"], (now - _WINDOW_24H,))
    paradigms = db.scalar(
        "SELECT COUNT(*) AS c FROM graph_facts WHERE "
        "(belief_meta LIKE '%\"type\":\"paradigm\"%' OR belief_meta LIKE "
        "'%\"type\": \"paradigm\"%')")
    counters24 = _window_log_counts(
        db, "memory_dream_log", ["deep_run"], chat_id=chat_id,
        since=now - _WINDOW_24H)
    counters7d = _window_log_counts(
        db, "memory_dream_log", ["deep_run"], chat_id=chat_id,
        since=now - _WINDOW_7D)
    return {
        "last_attempt": last,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"paradigms_total": paradigms,
                         "bootstrap_pending": (paradigms == 0)},
        "used_in_response": {"tracked": False,
                             "note": "парадигмы входят в retrieval "
                                     "graph_facts; прямой трейс нет"},
        "counters_24h": counters24,
        "counters_7d": counters7d,
        "events_24h": _events_window(db, event_names=spec["event_names"],
                                     components=spec["event_components"],
                                     chat_id=chat_id,
                                     since=now - _WINDOW_24H),
        "events_7d": _events_window(db, event_names=spec["event_names"],
                                    components=spec["event_components"],
                                    chat_id=chat_id,
                                    since=now - _WINDOW_7D),
        "last_event": _last_event(db, event_names=spec["event_names"],
                                  components=spec["event_components"],
                                  chat_id=chat_id),
        "last_job": None,
        "job_24h": None,
        "job_7d": None,
        "ttl_seconds": None,
        "extra": {},
    }


def _belief_section(db, spec, now, chat_id, stale_seconds) -> dict:
    where_chat = ""
    params: tuple = ()
    if chat_id is not None and db.table_exists("mca_belief_reviews"):
        # review_id-таблица chat-scope по belief; фильтр по chat_id если
        # колонка есть (fail-soft ниже всё равно отработает).
        where_chat = " WHERE chat_id = ?"
        params = (int(chat_id),)
    last_rows = db.q(
        "SELECT reviewed_at, belief_id, outcome, reason_code, job_id FROM "
        f"mca_belief_reviews{where_chat} ORDER BY reviewed_at DESC LIMIT 1",
        params)
    last = None
    if last_rows:
        row = last_rows[0]
        last = {"ts": int(row.get("reviewed_at") or 0) or None,
                "status": str(row.get("outcome") or ""),
                "kind": "belief_review",
                "source_table": "mca_belief_reviews",
                "detail": f"belief={row.get('belief_id')}, "
                          f"reason={row.get('reason_code')}"}
    input_total = db.scalar(spec["input_sql"])
    fresh = db.scalar(spec["fresh_input_sql"], (now - _WINDOW_24H,))

    def window(since):
        sql = ("SELECT outcome, COUNT(*) AS c FROM mca_belief_reviews "
               "WHERE reviewed_at >= ?")
        p: list = [int(since)]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            p.append(int(chat_id))
        sql += " GROUP BY outcome"
        rows = db.q(sql, tuple(p))
        if rows is None:
            return None
        return {str(r["outcome"] or "?"): int(r["c"] or 0) for r in rows}

    return {
        "last_attempt": last,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"reviews_total": db.scalar(
            "SELECT COUNT(*) AS c FROM mca_belief_reviews")},
        "used_in_response": {"tracked": False,
                             "note": "пересмотренные убеждения живут в "
                                     "graph_facts; трейс в ответе нет"},
        "counters_24h": window(now - _WINDOW_24H),
        "counters_7d": window(now - _WINDOW_7D),
        "events_24h": _events_window(db, event_names=spec["event_names"],
                                     components=spec["event_components"],
                                     chat_id=chat_id,
                                     since=now - _WINDOW_24H),
        "events_7d": _events_window(db, event_names=spec["event_names"],
                                    components=spec["event_components"],
                                    chat_id=chat_id,
                                    since=now - _WINDOW_7D),
        "last_event": _last_event(db, event_names=spec["event_names"],
                                  components=spec["event_components"],
                                  chat_id=chat_id),
        "last_job": None,
        "job_24h": None,
        "job_7d": None,
        "ttl_seconds": None,
        "extra": {},
    }


def _self_model_section(db, spec, now, chat_id, stale_seconds) -> dict:
    last = _log_last_attempt(
        db, "mca_trait_observations", [], chat_id=chat_id,
        ts_col="observed_at", kind_col=None, status_col="subject_status",
        detail_cols=("dimension",))
    if last is not None:
        # `subject_status` — классификация субъекта (self/other/ambiguous,
        # services/mca_self_model.SUBJECT_STATUSES), НЕ исход попытки:
        # словарная проверка статусов к ней не применяется.
        last["status_semantics"] = "classification"
    input_total = db.scalar(spec["input_sql"])
    fresh = db.scalar(spec["fresh_input_sql"], (now - _WINDOW_24H,))
    identity = None
    if db.table_exists("mca_self_identity"):
        rows = db.q("SELECT agent_id, bot_user_id, bound_at, updated_at "
                    "FROM mca_self_identity LIMIT 1")
        identity = rows[0] if rows else None
    behavior_rules = db.scalar(
        "SELECT COUNT(*) AS c FROM mca_behavior_rules")
    return {
        "last_attempt": last,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"self_identity": identity,
                         "behavior_rules_total": behavior_rules},
        "used_in_response": {"tracked": True,
                             "source": ("persona (bot_persona) читает "
                                        "traits; events component="
                                        "self_model")},
        "counters_24h": _window_log_counts(
            db, "mca_trait_observations", [], chat_id=chat_id,
            since=now - _WINDOW_24H, kind_col=None,
            status_col="subject_status"),
        "counters_7d": _window_log_counts(
            db, "mca_trait_observations", [], chat_id=chat_id,
            since=now - _WINDOW_7D, kind_col=None,
            status_col="subject_status"),
        "events_24h": _events_window(db, event_names=spec["event_names"],
                                     components=spec["event_components"],
                                     chat_id=chat_id,
                                     since=now - _WINDOW_24H),
        "events_7d": _events_window(db, event_names=spec["event_names"],
                                    components=spec["event_components"],
                                    chat_id=chat_id,
                                    since=now - _WINDOW_7D),
        "last_event": _last_event(db, event_names=spec["event_names"],
                                  components=spec["event_components"],
                                  chat_id=chat_id),
        "last_job": None,
        "job_24h": None,
        "job_7d": None,
        "ttl_seconds": None,
        "extra": {},
    }


def _input_block(db, spec, total, fresh, now) -> dict:
    return {"available": bool(total), "total": total,
            "fresh_24h": fresh, "detail": "по " +
            str(spec.get("tables", [])[:1] or ["источникам"])}


def _backlog_block(db, spec) -> dict:
    """Backlog «фактов без эмбеддинга» + честный статус.

    `graph_facts_vec` — vec0-таблица: без загруженного `sqlite_vec` запрос
    падает, и прежний `scalar()` молча отдавал `null` (на проде 22.10.2026
    так и было: backlog всегда null, при фактических 4162). Теперь: пробуем
    запрос, при ошибке догружаем расширение (read-only, без записи) и
    повторяем; если и это не удалось — `backlog_status=unknown` + причина."""
    sql = spec.get("backlog_sql")
    if not sql:
        return {"backlog_missing_embedding": None,
                "backlog_status": "not_instrumented",
                "backlog_reason": "механизм не пишет эмбеддинги"}
    before = len(db.errors)
    value, err = db.scalar_with_error(sql)
    loaded, why = False, None
    if value is None:
        del db.errors[before:]          # ошибка ниже уйдёт в backlog_reason
        loaded, why = db.ensure_vec()
        if loaded:
            before = len(db.errors)
            value, err = db.scalar_with_error(sql)
            if value is None:
                del db.errors[before:]
    if value is not None:
        return {"backlog_missing_embedding": value,
                "backlog_status": "ok", "backlog_reason": None}
    reason = err or "неизвестная ошибка чтения"
    if not loaded and why:
        reason = f"{reason}; {why}"
    return {"backlog_missing_embedding": None,
            "backlog_status": "unknown", "backlog_reason": reason}


def _graph_or_embed_section(db, spec, now, chat_id, stale_seconds) -> dict:
    last = _last_event(db, event_names=spec["event_names"],
                       components=spec["event_components"], chat_id=chat_id)
    last_attempt = None
    if last:
        last_attempt = {"ts": int(last.get("ts") or 0) or None,
                        "status": str(last.get("outcome") or ""),
                        "kind": str(last.get("event_name") or ""),
                        "source_table": "mca_events",
                        "detail": (f"reason={last.get('reason_code')}, "
                                   f"stage={last.get('stage')}")}
    job = _last_job(db, kinds=spec["job_kinds"], coalesce_keys=[])
    backlog_block = _backlog_block(db, spec)
    backlog = backlog_block["backlog_missing_embedding"]
    input_total = db.scalar(spec["input_sql"])
    fresh = db.scalar(spec["fresh_input_sql"], (now - _WINDOW_24H,))
    generations = None
    if db.table_exists("mca_embedding_index_generations"):
        generations = db.q(
            "SELECT index_name, generation, status, created_at, "
            "activated_at FROM mca_embedding_index_generations "
            "ORDER BY created_at DESC LIMIT 5")
    quota = None
    if db.table_exists("embedding_quota_state"):
        quota = db.q("SELECT * FROM embedding_quota_state LIMIT 5")
    return {
        "last_attempt": last_attempt,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"recent_generations": generations,
                         "quota_state": quota,
                         **backlog_block},
        "used_in_response": {"tracked": True,
                             "source": ("GraphRAG retrieval читает "
                                        "graph_facts/nodes/edges")},
        "counters_24h": _events_window(db, event_names=spec["event_names"],
                                       components=spec["event_components"],
                                       chat_id=chat_id,
                                       since=now - _WINDOW_24H),
        "counters_7d": _events_window(db, event_names=spec["event_names"],
                                      components=spec["event_components"],
                                      chat_id=chat_id,
                                      since=now - _WINDOW_7D),
        "events_24h": None,
        "events_7d": None,
        "last_job": job,
        "job_24h": (_job_window_counts(db, kinds=spec["job_kinds"],
                                       coalesce_keys=[],
                                       since=now - _WINDOW_24H)
                    if spec["job_kinds"] else None),
        "job_7d": (_job_window_counts(db, kinds=spec["job_kinds"],
                                      coalesce_keys=[],
                                      since=now - _WINDOW_7D)
                   if spec["job_kinds"] else None),
        "ttl_seconds": None,
        "extra": {"payload_cursor": _payload_cursor(
            (job or {}).get("payload"))},
    }


def _experience_section(db, spec, now, chat_id, stale_seconds) -> dict:
    last_rows = None
    if db.table_exists("mca_experience_episodes"):
        where_chat = ""
        params: tuple = ()
        if chat_id is not None:
            where_chat = " WHERE chat_id = ?"
            params = (int(chat_id),)
        last_rows = db.q(
            "SELECT created_at, task_type, outcome_kind FROM "
            f"mca_experience_episodes{where_chat} "
            "ORDER BY created_at DESC LIMIT 1", params)
    last = None
    if last_rows:
        row = last_rows[0]
        last = {"ts": int(row.get("created_at") or 0) or None,
                "status": str(row.get("outcome_kind") or ""),
                "kind": str(row.get("task_type") or "episode"),
                "source_table": "mca_experience_episodes",
                "detail": ""}
    job = _last_job(db, kinds=["experience.review"],
                    coalesce_keys=["experience.review:global"])
    input_total = db.scalar(spec["input_sql"])
    fresh = db.scalar(spec["fresh_input_sql"], (now - _WINDOW_24H,))
    lessons = db.scalar("SELECT COUNT(*) AS c FROM mca_lessons") \
        if db.table_exists("mca_lessons") else None
    applied = db.scalar(
        "SELECT COUNT(*) AS c FROM mca_lesson_applications") \
        if db.table_exists("mca_lesson_applications") else None
    return {
        "last_attempt": last,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"lessons_total": lessons,
                         "lesson_applications_total": applied},
        "used_in_response": {"tracked": True,
                             "source": ("mca_lesson_applications "
                                        "(инъекция-гард Direct)")},
        "counters_24h": _events_window(db, event_names=spec["event_names"],
                                       components=spec["event_components"],
                                       chat_id=chat_id,
                                       since=now - _WINDOW_24H),
        "counters_7d": _events_window(db, event_names=spec["event_names"],
                                      components=spec["event_components"],
                                      chat_id=chat_id,
                                      since=now - _WINDOW_7D),
        "events_24h": None,
        "events_7d": None,
        "last_job": job,
        "job_24h": _job_window_counts(db, kinds=["experience.review"],
                                      coalesce_keys=[], since=now - _WINDOW_24H),
        "job_7d": _job_window_counts(db, kinds=["experience.review"],
                                     coalesce_keys=[], since=now - _WINDOW_7D),
        "ttl_seconds": None,
        "extra": {},
    }


def _initiative_section(db, spec, now, chat_id, stale_seconds) -> dict:
    job = _last_job(db, kinds=["initiative.observe"],
                    coalesce_keys=["initiative.observe:global"])
    last_attempt = None
    if job:
        last_attempt = {
            "ts": int(job.get("updated_at") or job.get("created_at") or 0)
            or None,
            "status": str(job.get("status") or ""),
            "kind": str(job.get("kind") or ""),
            "source_table": "task_jobs",
            "detail": (f"reason={job.get('reason_code')}, "
                       f"attempt={job.get('attempt')}/"
                       f"{job.get('max_attempts')}")}
    input_total = db.scalar(spec["input_sql"], (now - _WINDOW_24H,))
    fresh = input_total
    intents_total = db.scalar("SELECT COUNT(*) AS c FROM mca_intents") \
        if db.table_exists("mca_intents") else None
    intents_active = None
    if db.table_exists("mca_intents"):
        sql = ("SELECT COUNT(*) AS c FROM mca_intents WHERE status IN "
               "('pending','scheduled')")
        params: tuple = ()
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params = (int(chat_id),)
        intents_active = db.scalar(sql, params)
    return {
        "last_attempt": last_attempt,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"intents_total": intents_total,
                         "intents_active": intents_active},
        "used_in_response": {"tracked": True,
                             "source": (" Initiative funnel mca_events "
                                        "component=initiative/intents")},
        "counters_24h": _events_window(db, event_names=spec["event_names"],
                                       components=spec["event_components"],
                                       chat_id=chat_id,
                                       since=now - _WINDOW_24H),
        "counters_7d": _events_window(db, event_names=spec["event_names"],
                                      components=spec["event_components"],
                                      chat_id=chat_id,
                                      since=now - _WINDOW_7D),
        "events_24h": None,
        "events_7d": None,
        "last_job": job,
        "job_24h": _job_window_counts(db, kinds=["initiative.observe"],
                                      coalesce_keys=[],
                                      since=now - _WINDOW_24H),
        "job_7d": _job_window_counts(db, kinds=["initiative.observe"],
                                     coalesce_keys=[],
                                     since=now - _WINDOW_7D),
        "ttl_seconds": 6 * HOUR,
        "extra": {},
    }


def _summary_section(db, spec, now, chat_id, stale_seconds) -> dict:
    last_rows = None
    if db.table_exists("summary_runs"):
        where_chat = ""
        params: tuple = ()
        if chat_id is not None:
            where_chat = " WHERE chat_id = ?"
            params = (int(chat_id),)
        last_rows = db.q(
            "SELECT run_id, state, manual, created_at, updated_at, "
            "publication_status, pipeline_health FROM "
            f"summary_runs{where_chat} ORDER BY created_at DESC LIMIT 1",
            params)
    last = None
    if last_rows:
        row = last_rows[0]
        last = {"ts": int(row.get("created_at") or 0) or None,
                "status": str(row.get("state") or ""),
                "kind": "summary_run",
                "source_table": "summary_runs",
                # publication_status — часть исхода: провал публикации при
                # успешном state тоже не зелёное (diagnose → attention).
                "publication_status": str(
                    row.get("publication_status") or ""),
                "detail": (f"run={row.get('run_id')}, "
                           f"publication={row.get('publication_status')}, "
                           f"health={row.get('pipeline_health')}")}
    input_total = db.scalar(spec["input_sql"], (now - _WINDOW_24H,))
    fresh = input_total
    return {
        "last_attempt": last,
        "real_input": _input_block(db, spec, input_total, fresh, now),
        "write_result": {"runs_total": db.scalar(
            "SELECT COUNT(*) AS c FROM summary_runs"
        ) if db.table_exists("summary_runs") else None},
        "used_in_response": {"tracked": True,
                             "source": ("summary публикуется в чат; "
                                        "summary_runs.publication_status")},
        "counters_24h": _events_window(db, event_names=spec["event_names"],
                                       components=spec["event_components"],
                                       chat_id=chat_id,
                                       since=now - _WINDOW_24H),
        "counters_7d": _events_window(db, event_names=spec["event_names"],
                                      components=spec["event_components"],
                                      chat_id=chat_id,
                                      since=now - _WINDOW_7D),
        "events_24h": None,
        "events_7d": None,
        "last_job": None,
        "job_24h": None,
        "job_7d": None,
        "ttl_seconds": 12 * HOUR,
        "extra": {},
    }


_SECTION_BUILDERS = {
    "dream": _dream_section,
    "deep_sleep": _deep_section,
    "belief_revision": _belief_section,
    "paradigms": _deep_section,          # те же таблицы, парадигм-фокус
    "self_model": _self_model_section,
    "graph_memory": _graph_or_embed_section,
    "embeddings": _graph_or_embed_section,
    "experience": _experience_section,
    "initiative": _initiative_section,
    "summary_scheduler": _summary_section,
}


# ── сборка отчёта ────────────────────────────────────────────────────────────

async def collect_report(db_path: str, *, chat_id: int | None = None,
                         pg_dsn: str | None = None,
                         stale_seconds: int = DEFAULT_STALE_SECONDS,
                         now: int | None = None) -> dict:
    """Собрать полный отчёт (read-only). Fail-soft per секция."""
    ts = int(time.time()) if now is None else int(now)
    db = ReadOnlyDB(db_path)
    pg_dsn = pg_dsn or os.getenv("POSTGRES_DSN")

    # PG-слой гейтов — один коннект на все механизмы.
    all_catalog_keys: list[str] = []
    for spec in _mechanism_specs():
        for key in spec["catalog_keys"]:
            if key not in all_catalog_keys:
                all_catalog_keys.append(key)
    pg_layer = await _pg_gate_layer(pg_dsn, all_catalog_keys, chat_id)

    sections: list[dict] = []
    for spec in _mechanism_specs():
        builder = _SECTION_BUILDERS.get(spec["key"])
        env_layer = _env_layer(spec["env_keys"])
        catalog_values = {}
        if pg_layer.get("available"):
            for key in spec["catalog_keys"]:
                catalog_values[key] = {
                    "global": (pg_layer.get("global") or {}).get(key),
                    "chat": (pg_layer.get("chat") or {}).get(key),
                }
        effective, source = _gate_effective(env_layer, pg_layer, chat_id)
        section: dict = {
            "key": spec["key"],
            "title": spec["title"],
            "gate": {"env": env_layer,
                     "pg_catalog": catalog_values,
                     "pg_available": bool(pg_layer.get("available")),
                     "pg_reason": pg_layer.get("reason"),
                     "effective": effective,
                     "effective_source": source,
                     "chat_id": chat_id},
            "producer": _producer_registration(spec["registry"]),
            "sources": list(spec["tables"]),
        }
        if builder is None or not db.ok():
            section["gate"]["effective"] = None
            section["diagnosis"] = {
                "code": DIAG_UNAVAILABLE,
                "detail": ("sqlite недоступна" if not db.ok()
                           else "нет сборщика секции")}
            sections.append(section)
            continue
        try:
            data = builder(db, spec, ts, chat_id, stale_seconds)
        except Exception as exc:
            section["diagnosis"] = {
                "code": DIAG_UNAVAILABLE,
                "detail": f"section failed: {type(exc).__name__}: {exc}"}
            sections.append(section)
            continue
        section.update(data)
        # недоступность ключевых таблиц секции → честный unavailable
        missing = [t for t in spec["tables"][:3]
                   if not db.table_exists(t)]
        attempt = section.get("last_attempt")
        job = section.get("last_job")
        section["diagnosis"] = diagnose(
            gate_effective=effective, gate_source=source,
            input_available=section.get("real_input", {}).get("available"),
            last_attempt=attempt, last_job=job, now=ts,
            stale_seconds=stale_seconds,
            backlog=section.get("write_result", {}).get(
                "backlog_missing_embedding")
            if isinstance(section.get("write_result"), dict) else None,
            ttl_seconds=section.get("ttl_seconds"),
            sources_unavailable=len(missing) >= 3)
        section["missing_tables"] = missing
        sections.append(section)
    db_errors = list(db.errors)[:20]
    db.close()
    return {"generated_at": ts,
            "db": db_path,
            "chat_id": chat_id,
            "stale_seconds": stale_seconds,
            "pg_available": bool(pg_layer.get("available")),
            "pg_reason": pg_layer.get("reason"),
            "db_read_errors": db_errors,
            "mechanisms": sections,
            "summary": _summary_block(sections)}


def _summary_block(sections: list[dict]) -> dict:
    counters: dict[str, int] = {}
    for section in sections:
        code = (section.get("diagnosis") or {}).get("code") or "unknown"
        counters[code] = counters.get(code, 0) + 1
    return {"diagnoses": counters,
            "not_green_rule": ("never_run/producer_off/no_input/unknown/"
                               "degraded/attention никогда не считаются "
                               "зелёными (REQ-B11-E2E)")}


# ── человекочитаемый вывод ───────────────────────────────────────────────────

_DIAG_RU = {
    DIAG_OK: "ok — цепочка работает",
    DIAG_PRODUCER_OFF: "producer отключён (gate off)",
    DIAG_NO_INPUT: "нет входных данных",
    DIAG_CURSOR_STALLED: "cursor stalled (backlog растёт, прогресса нет)",
    DIAG_WORKER_CRASHED: "worker crashed (stale heartbeat/failed)",
    DIAG_TTL_DUE: "просрочен интервал запуска (TTL)",
    DIAG_NEVER_RUN: "включено, но ни одной попытки",
    DIAG_ATTENTION: "последняя попытка не завершилась успешно",
    DIAG_DEGRADED: "последняя попытка деградирована (резервный контур)",
    DIAG_UNKNOWN: "статус попытки не распознан (не зелёное)",
    DIAG_UNAVAILABLE: "источники недоступны (fail-soft)",
}


def _fmt_ts(value) -> str:
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return "—"
    if ts <= 0:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def format_human(report: dict) -> str:
    lines: list[str] = []
    lines.append(f"B11 — механизмы ({_fmt_ts(report.get('generated_at'))})")
    lines.append(f"DB: {report.get('db')} | chat_id: "
                 f"{report.get('chat_id') or '—'} | PG: "
                 f"{'доступен' if report.get('pg_available') else 'нет'}"
                 f"{(' (' + str(report.get('pg_reason')) + ')') if report.get('pg_reason') else ''}")
    if report.get("db_read_errors"):
        lines.append(f"Ошибки чтения (fail-soft, до 20): "
                     f"{len(report['db_read_errors'])}")
    for m in report.get("mechanisms", []):
        diag = m.get("diagnosis") or {}
        lines.append("")
        lines.append(f"== {m.get('title')} — "
                     f"{_DIAG_RU.get(diag.get('code'), diag.get('code'))}")
        gate = m.get("gate") or {}
        lines.append(f"  gate: effective={gate.get('effective')} "
                     f"({gate.get('effective_source')}); env="
                     f"{ {k: v.get('value') for k, v in (gate.get('env') or {}).items()} }; "
                     f"pg_catalog={gate.get('pg_catalog') or '—'}")
        producer = m.get("producer") or {}
        lines.append(f"  producer: registered={producer.get('registered')} "
                     f"processes="
                     f"{[p.get('process_id') for p in producer.get('processes', [])]}")
        attempt = m.get("last_attempt")
        if attempt:
            lines.append(f"  последняя попытка: {_fmt_ts(attempt.get('ts'))} "
                         f"kind={attempt.get('kind')} "
                         f"status={attempt.get('status') or '—'} "
                         f"({attempt.get('detail') or ''})")
        else:
            lines.append("  последняя попытка: НЕТ (never_run)")
        inp = m.get("real_input") or {}
        lines.append(f"  вход: available={inp.get('available')} "
                     f"total={inp.get('total')} fresh_24h={inp.get('fresh_24h')}")
        job = m.get("last_job")
        if job:
            lines.append(f"  job: {job.get('kind')} {job.get('status')} "
                         f"updated={_fmt_ts(job.get('updated_at'))} "
                         f"reason={job.get('reason_code') or '—'} "
                         f"error={job.get('error_code') or '—'}")
        else:
            lines.append("  job: —")
        wr = m.get("write_result") or {}
        lines.append(f"  запись: {json.dumps(wr, ensure_ascii=False)[:200]}")
        if isinstance(wr, dict) and "backlog_status" in wr:
            bl = wr.get("backlog_missing_embedding")
            status = str(wr.get("backlog_status") or "")
            if bl is not None:
                text = f"  backlog (без эмбеддинга): {bl}"
            elif status == "not_instrumented":
                text = "  backlog (без эмбеддинга): не инструментирован"
            else:
                text = "  backlog (без эмбеддинга): unknown"
            if wr.get("backlog_reason"):
                text += f" — {wr.get('backlog_reason')}"
            lines.append(text)
        counters = m.get("counters_24h")
        if counters is None:
            counters = m.get("events_24h")
        lines.append(f"  24h: {json.dumps(counters or {}, ensure_ascii=False)}"
                     f" | job: "
                     f"{json.dumps(m.get('job_24h') or {}, ensure_ascii=False)}")
        counters7 = m.get("counters_7d")
        if counters7 is None:
            counters7 = m.get("events_7d")
        lines.append(f"  7d: {json.dumps(counters7 or {}, ensure_ascii=False)}")
        used = m.get("used_in_response") or {}
        lines.append(f"  использовано в ответе: tracked={used.get('tracked')} "
                     f"{used.get('source') or used.get('note') or ''}")
        lines.append(f"  диагноз: {diag.get('code')} — {diag.get('detail')}")
    return "\n".join(lines)


async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="B11: read-only отчёт по фоновым механизмам")
    parser.add_argument("--db", default=os.getenv("DB_PATH",
                                                  "local_database.db"),
                        help="путь к SQLite (read-only, mode=ro)")
    parser.add_argument("--chat-id", default=None,
                        help="chat_id для per-chat гейтов/счётчиков")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="файл для JSON-отчёта (иначе stdout)")
    parser.add_argument("--pg-dsn", default=os.getenv("POSTGRES_DSN"),
                        help="DSN PostgreSQL для global/chat-гейтов")
    parser.add_argument("--stale-seconds", type=int,
                        default=DEFAULT_STALE_SECONDS,
                        help="порог stale heartbeat (worker crashed)")
    args = parser.parse_args(argv)
    chat_id = int(args.chat_id) if str(args.chat_id or "").strip() else None
    report = await collect_report(
        args.db, chat_id=chat_id, pg_dsn=args.pg_dsn,
        stale_seconds=max(60, int(args.stale_seconds)))
    payload = json.dumps(report, ensure_ascii=False, indent=1,
                         default=str)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"JSON: {args.json_path}")
    else:
        print(payload)
    print()
    print(format_human(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(list(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
