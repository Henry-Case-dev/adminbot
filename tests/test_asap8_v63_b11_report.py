"""B11 (asap8-v6.3, REQ-B11/SCOPE/CHAIN/E2E) — read-only генератор отчёта
«Интеграционная проверка скрытых фоновых механизмов».

Проверки:
  * фикстурная БД с известными состояниями (worker crashed, cursor stalled,
    producer off, пустой вход, ok) → отчёт РАЗЛИЧАЕТ причины (не всё
    зелёное/не всё красное) — REQ-B11-E2E;
  * полнота перечня механизмов (10, REQ-B11-SCOPE) и полнота цепочки
    (REQ-B11-CHAIN) в JSON и человекочитаемом выводе;
  * fail-soft per секция (нет таблиц → honest unavailable, не краш);
  * строго read-only: SELECT-режим SQLite, записи не выполняются;
  * unit-матрица диагнозов (все коды REQ-B11-E2E).

TEST-LIFECYCLE: REGRESSION owner=REQ-B11-E2E (диагнозы), CONTRACT
owner=REQ-B11-SCOPE/CHAIN (структура отчёта).
"""
import json
import sqlite3

import pytest

from services.database import DatabaseService
from tools.v63_b11_mechanisms_report import (
    DIAG_ATTENTION,
    DIAG_CURSOR_STALLED,
    DIAG_DEGRADED,
    DIAG_NEVER_RUN,
    DIAG_NO_INPUT,
    DIAG_OK,
    DIAG_PRODUCER_OFF,
    DIAG_TTL_DUE,
    DIAG_UNAVAILABLE,
    DIAG_UNKNOWN,
    DIAG_WORKER_CRASHED,
    ReadOnlyDB,
    collect_report,
    diagnose,
    format_human,
)

CHAT = -100500
NOW = 1790000000


async def _db(tmp_path, name="b11.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _exec(db, sql, params=()):
    await db.db.execute(sql, params)
    await db.db.commit()


async def _seed_message(db, ts, chat_id=CHAT):
    await _exec(
        db, "INSERT INTO smart_messages (user_id, chat_id, text, "
            "reply_to_id, timestamp, media_type, author_name, "
            "tg_message_id) VALUES (1, ?, 'сообщение из обычной конфы', "
            "NULL, ?, 'text', '', NULL)", (chat_id, ts))


async def _seed_job(db, *, kind, status, now, heartbeat_at=None,
                    finished_at=None, reason=None, payload=None,
                    coalesce_key=None):
    await _exec(
        db, "INSERT INTO task_jobs (job_id, owner, kind, coalesce_key, "
            "payload, status, reason_code, error_code, attempt, "
            "max_attempts, deadline_at, heartbeat_at, generation, "
            "fencing_token, created_at, updated_at, finished_at) VALUES (?, "
            "'test', ?, ?, ?, ?, ?, NULL, 1, 3, NULL, ?, 0, 0, ?, ?, ?)",
        (f"job-{kind}-{status}-{now}", kind, coalesce_key,
         payload, status, reason, heartbeat_at, now - 60,
         finished_at if finished_at is not None else now - 60,
         finished_at))


async def _seed_event(db, *, ts, event_name, outcome, component,
                      chat_id=CHAT, reason=None):
    await _exec(
        db, "INSERT INTO mca_events (ts, level, event_name, outcome, "
            "chat_id, component, stage, reason_code) VALUES (?, 'INFO', ?, "
            "?, ?, ?, 'run', ?)", (ts, event_name, outcome, chat_id,
                                   component, reason))


async def _seed_dream_log(db, *, run_at, kind="run", status="ok",
                          chat_id=CHAT):
    await _exec(
        db, "INSERT INTO memory_dream_log (chat_id, run_at, kind, "
            "cluster_id, source_ids, belief_id, tokens, status) VALUES (?, "
            "?, ?, NULL, NULL, NULL, 10, ?)", (chat_id, run_at, kind,
                                               status))


async def _seed_graph_fact(db, *, created_at, fact="факт из чата",
                           chat_id=CHAT, belief_meta=None):
    await _exec(
        db, "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "belief_meta) VALUES (?, ?, 'chat_history', ?, ?)",
        (chat_id, fact, created_at, belief_meta))


# ═══ CONTRACT: полнота перечня и цепочки ═════════════════════════════════════

class TestReportStructure:
    @pytest.mark.asyncio
    async def test_ten_mechanisms_full_chain(self, tmp_path):
        """REQ-B11-SCOPE: все 10 механизмов; REQ-B11-CHAIN: каждая секция
        несёт полную цепочку gate→attempt→input→producer→job→write→used→
        counters→diagnosis."""
        db = await _db(tmp_path)
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        keys = [m["key"] for m in report["mechanisms"]]
        assert keys == ["dream", "deep_sleep", "belief_revision",
                        "paradigms", "self_model", "graph_memory",
                        "embeddings", "experience", "initiative",
                        "summary_scheduler"]
        for section in report["mechanisms"]:
            for field in ("gate", "last_attempt", "real_input", "producer",
                          "write_result", "used_in_response", "counters_24h",
                          "counters_7d", "diagnosis", "sources"):
                assert field in section, (section["key"], field)
            gate = section["gate"]
            assert {"env", "pg_catalog", "effective",
                    "effective_source"} <= set(gate)
            assert section["diagnosis"]["code"]
            assert section["producer"].get("registered") is not None
        await db.close()

    @pytest.mark.asyncio
    async def test_human_output_readable(self, tmp_path):
        db = await _db(tmp_path)
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        human = format_human(report)
        assert "B11 — механизмы" in human
        assert "Сон (dream)" in human
        assert "Summary scheduler" in human
        for section in report["mechanisms"]:
            assert section["title"] in human
            assert section["diagnosis"]["code"] in human
        await db.close()

    @pytest.mark.asyncio
    async def test_readonly_no_writes(self, tmp_path):
        """Скрипт строго read-only: mode=ro, INSERT отклонён и зафиксирован
        как ошибка чтения (fail-soft)."""
        db = await _db(tmp_path)
        ro = ReadOnlyDB(str(tmp_path / "b11.db"))
        assert ro.ok()
        assert ro.table_exists("task_jobs")
        assert ro.q("SELECT COUNT(*) AS c FROM task_jobs") == [{"c": 0}]
        assert ro.q("INSERT INTO task_jobs (job_id, owner, kind, status, "
                    "attempt, max_attempts, generation, fencing_token, "
                    "created_at, updated_at) VALUES ('x', 'x', 'x', 'run', "
                    "0, 1, 0, 0, 0, 0)") is None
        assert any("attempt to write a readonly database" in e
                   for e in ro.errors)
        ro.close()
        await db.close()


# ═══ REGRESSION: диагнозы различают известные состояния ══════════════════════

class TestKnownStatesDiagnosed:
    @pytest.mark.asyncio
    async def test_producer_off_when_env_gate_off(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.delenv("DREAM_ENABLED", raising=False)
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 60)
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        dream = next(m for m in report["mechanisms"]
                     if m["key"] == "dream")
        assert dream["gate"]["effective"] is False
        assert dream["diagnosis"]["code"] == DIAG_PRODUCER_OFF
        await db.close()

    @pytest.mark.asyncio
    async def test_env_overrides_default_gate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREAM_ENABLED", "1")
        db = await _db(tmp_path)
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        dream = next(m for m in report["mechanisms"]
                     if m["key"] == "dream")
        assert dream["gate"]["effective"] is True
        assert dream["gate"]["effective_source"].startswith("env")
        await db.close()

    @pytest.mark.asyncio
    async def test_worker_crashed_stale_heartbeat(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.delenv("INITIATIVE_OBSERVER_ENABLED", raising=False)
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 120)
        await _seed_job(db, kind="initiative.observe", status="running",
                        now=NOW, heartbeat_at=NOW - 3600)
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        initiative = next(m for m in report["mechanisms"]
                          if m["key"] == "initiative")
        assert initiative["diagnosis"]["code"] == DIAG_WORKER_CRASHED
        assert "heartbeat" in initiative["diagnosis"]["detail"]
        await db.close()

    @pytest.mark.asyncio
    async def test_worker_crashed_failed_job(self, tmp_path):
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 120)
        await _seed_job(db, kind="initiative.observe", status="failed",
                        now=NOW, reason="model_unavailable")
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        initiative = next(m for m in report["mechanisms"]
                          if m["key"] == "initiative")
        assert initiative["diagnosis"]["code"] == DIAG_WORKER_CRASHED
        assert initiative["last_job"]["reason_code"] == "model_unavailable"
        await db.close()

    @pytest.mark.asyncio
    async def test_cursor_stalled_backlog_without_progress(self, tmp_path):
        db = await _db(tmp_path)
        for i in range(3):
            await _seed_graph_fact(db, created_at=NOW - 3600 + i,
                                   fact=f"факт-{i}")
        # vec-таблица отстаёт от graph_facts (backlog = 2)
        await _exec(db, "CREATE TABLE graph_facts_vec (rowid_ INTEGER "
                        "PRIMARY KEY)")
        await _exec(db, "INSERT INTO graph_facts_vec (rowid_) VALUES (1)")
        await _seed_job(db, kind="graphrag_rebuild", status="completed",
                        now=NOW, finished_at=NOW - 7200)
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        graph = next(m for m in report["mechanisms"]
                     if m["key"] == "graph_memory")
        assert graph["diagnosis"]["code"] == DIAG_CURSOR_STALLED
        assert graph["write_result"]["backlog_missing_embedding"] == 2
        await db.close()

    @pytest.mark.asyncio
    async def test_no_input_empty_source(self, tmp_path):
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 120)   # input для input_sql experience?
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        experience = next(m for m in report["mechanisms"]
                          if m["key"] == "experience")
        assert experience["gate"]["effective"] is True
        assert experience["diagnosis"]["code"] == DIAG_NO_INPUT
        await db.close()

    @pytest.mark.asyncio
    async def test_never_run_not_painted_green(self, tmp_path):
        """«Включено, но не запускалось» → never_run, НЕ зелёное."""
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 120)
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        summary = next(m for m in report["mechanisms"]
                       if m["key"] == "summary_scheduler")
        assert summary["gate"]["effective"] is True
        assert summary["real_input"]["available"] is True
        assert summary["diagnosis"]["code"] == DIAG_NEVER_RUN
        assert summary["diagnosis"]["code"] != DIAG_OK
        await db.close()

    @pytest.mark.asyncio
    async def test_ok_states_fresh_runs(self, tmp_path, monkeypatch):
        """Свежие попытки + вход + gate on → ok (не фикция: реальные
        строки memory_dream_log/summary_runs/mca_belief_reviews)."""
        monkeypatch.setenv("DREAM_ENABLED", "1")
        monkeypatch.setenv("DEEP_SLEEP_ENABLED", "1")
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 600)
        await _seed_message(db, NOW - 600)
        await _seed_dream_log(db, run_at=NOW - 600, kind="run", status="ok")
        await _seed_dream_log(db, run_at=NOW - 300, kind="deep_run",
                              status="ok")
        await _exec(db, "INSERT INTO mca_belief_reviews (review_id, "
                        "belief_id, chat_id, reviewed_at, outcome) VALUES "
                        "('r1', 'b1', ?, ?, 'kept')", (CHAT, NOW - 400))
        await _exec(db, "INSERT INTO summary_runs (run_id, chat_id, state, "
                        "manual, created_at, updated_at, "
                        "publication_status, pipeline_health) VALUES "
                        "('run1', ?, 'DONE', 0, ?, ?, 'published', "
                        "'healthy')", (CHAT, NOW - 500, NOW - 400))
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        codes = {m["key"]: m["diagnosis"]["code"]
                 for m in report["mechanisms"]}
        assert codes["dream"] == DIAG_OK
        assert codes["deep_sleep"] == DIAG_OK
        assert codes["summary_scheduler"] == DIAG_OK
        assert report["summary"]["diagnoses"].get(DIAG_OK, 0) >= 3
        await db.close()

    @pytest.mark.asyncio
    async def test_attention_on_error_attempt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEEP_SLEEP_ENABLED", "1")
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 600)
        await _seed_dream_log(db, run_at=NOW - 600, kind="deep_run",
                              status="error")
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        deep = next(m for m in report["mechanisms"]
                    if m["key"] == "deep_sleep")
        assert deep["diagnosis"]["code"] == DIAG_ATTENTION
        await db.close()

    # TEST-LIFECYCLE: REGRESSION owner=REQ-B11-E2E (ложный `ok` у FAILED/
    # DEGRADED рана; backlog без причины на проде).
    @pytest.mark.asyncio
    async def test_failed_summary_run_not_green(self, tmp_path):
        """REQ-B11-E2E: summary_runs.state пишется в ВЕРХНЕМ регистре
        (`services.summary_run_store.TERMINAL_STATES` = DONE/DEGRADED/
        FAILED). Провалившийся последний run не может быть `ok` (прод
        22.10.2026: state=FAILED, publication=failed → инструмент показывал
        ok из-за регистрозависимого сравнения)."""
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 600)
        await _exec(db, "INSERT INTO summary_runs (run_id, chat_id, state, "
                        "manual, created_at, updated_at, "
                        "publication_status, pipeline_health) VALUES "
                        "('run-failed', ?, 'FAILED', 0, ?, ?, 'failed', "
                        "'degraded')", (CHAT, NOW - 500, NOW - 400))
        report = await collect_report(str(tmp_path / "b11.db"), chat_id=CHAT,
                                      now=NOW)
        summary = next(m for m in report["mechanisms"]
                       if m["key"] == "summary_scheduler")
        assert summary["last_attempt"]["status"] == "FAILED"
        assert summary["diagnosis"]["code"] == DIAG_ATTENTION
        assert summary["diagnosis"]["code"] != DIAG_OK
        assert "FAILED" in summary["diagnosis"]["detail"]
        await db.close()

    @pytest.mark.asyncio
    async def test_degraded_summary_run_not_green(self, tmp_path):
        """DEGRADED (терминальное состояние генератора) — не `ok`: ран
        опубликован резервным контуром, зелёный статус завышал бы картину."""
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 600)
        await _exec(db, "INSERT INTO summary_runs (run_id, chat_id, state, "
                        "manual, created_at, updated_at, "
                        "publication_status, pipeline_health) VALUES "
                        "('run-degraded', ?, 'DEGRADED', 0, ?, ?, "
                        "'published', 'degraded')",
                    (CHAT, NOW - 500, NOW - 400))
        report = await collect_report(str(tmp_path / "b11.db"), chat_id=CHAT,
                                      now=NOW)
        summary = next(m for m in report["mechanisms"]
                       if m["key"] == "summary_scheduler")
        assert summary["diagnosis"]["code"] == DIAG_DEGRADED
        assert summary["diagnosis"]["code"] != DIAG_OK
        await db.close()

    @pytest.mark.asyncio
    async def test_foreign_summary_state_honest_unknown(self, tmp_path):
        """Незнакомое/пустое состояние не перекрашивается в зелёное."""
        db = await _db(tmp_path)
        await _seed_message(db, NOW - 600)
        await _exec(db, "INSERT INTO summary_runs (run_id, chat_id, state, "
                        "manual, created_at, updated_at, "
                        "publication_status, pipeline_health) VALUES "
                        "('run-legacy', ?, 'ARCHIVED_LEGACY', 0, ?, ?, "
                        "'published', 'ok')", (CHAT, NOW - 500, NOW - 400))
        report = await collect_report(str(tmp_path / "b11.db"), chat_id=CHAT,
                                      now=NOW)
        summary = next(m for m in report["mechanisms"]
                       if m["key"] == "summary_scheduler")
        assert summary["diagnosis"]["code"] == DIAG_UNKNOWN
        assert summary["diagnosis"]["code"] != DIAG_OK
        await db.close()

    @pytest.mark.asyncio
    async def test_backlog_unknown_has_reason(self, tmp_path):
        """Без vec-таблицы backlog не `null` без объяснения: честный
        `unknown` + причина (прод: `sqlite_vec` не загружен → всегда null)."""
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 3600)
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        graph = next(m for m in report["mechanisms"]
                     if m["key"] == "graph_memory")
        wr = graph["write_result"]
        assert wr["backlog_missing_embedding"] is None
        assert wr["backlog_status"] == "unknown"
        assert wr["backlog_reason"]
        assert "graph_facts_vec" in wr["backlog_reason"]
        await db.close()

    @pytest.mark.asyncio
    async def test_ttl_due_overdue_schedule(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DREAM_ENABLED", "1")
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 600)
        await _seed_dream_log(db, run_at=NOW - 30 * 3600, kind="run",
                              status="ok")     # > 25h TTL
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        dream = next(m for m in report["mechanisms"]
                     if m["key"] == "dream")
        assert dream["diagnosis"]["code"] == DIAG_TTL_DUE
        await db.close()

    @pytest.mark.asyncio
    async def test_counters_windows(self, tmp_path, monkeypatch):
        """24h/7d счётчики идут от реальных строк memory_dream_log."""
        monkeypatch.setenv("DREAM_ENABLED", "1")
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 600)
        await _seed_dream_log(db, run_at=NOW - 600, kind="run", status="ok")
        await _seed_dream_log(db, run_at=NOW - 5 * 86400, kind="run",
                              status="ok")
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        dream = next(m for m in report["mechanisms"]
                     if m["key"] == "dream")
        assert dream["counters_24h"]["run"]["ok"] == 1
        assert dream["counters_7d"]["run"]["ok"] == 2
        await db.close()


# ═══ fail-soft + unit-матрица диагнозов ══════════════════════════════════════

class TestFailSoftAndDiagnoseMatrix:
    @pytest.mark.asyncio
    async def test_missing_tables_honest_unavailable(self, tmp_path):
        """Пустой SQLite без таблиц → все секции unavailable, краша нет
        (fail-soft per секция, Wave 4 на проде)."""
        path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE IF NOT EXISTS marker (id INTEGER)")
        conn.commit()
        conn.close()
        report = await collect_report(str(path), now=NOW)
        assert len(report["mechanisms"]) == 10
        for section in report["mechanisms"]:
            assert section["diagnosis"]["code"] == DIAG_UNAVAILABLE
        # fail-soft ошибки чтения отсутствующих таблиц зафиксированы честно
        assert isinstance(report["db_read_errors"], list)

    def test_diagnose_unit_matrix(self):
        now = NOW
        base_job = {"status": "running", "heartbeat_at": now - 60,
                    "updated_at": now - 60, "reason_code": None,
                    "error_code": None, "finished_at": None}
        # 1. источники недоступны
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=None,
                        last_job=None, now=now,
                        sources_unavailable=True)["code"] == \
            DIAG_UNAVAILABLE
        # 2. producer off
        assert diagnose(gate_effective=False, gate_source="env:x=off",
                        input_available=True, last_attempt=None,
                        last_job=None, now=now)["code"] == DIAG_PRODUCER_OFF
        # 3. нет входа
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=False, last_attempt=None,
                        last_job=None, now=now)["code"] == DIAG_NO_INPUT
        # 4. crashed: stale heartbeat
        stale = dict(base_job, heartbeat_at=now - 7200)
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=None,
                        last_job=stale, now=now)["code"] == \
            DIAG_WORKER_CRASHED
        # 5. crashed: failed
        failed = dict(base_job, status="failed", reason_code="boom")
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=None,
                        last_job=failed, now=now)["code"] == \
            DIAG_WORKER_CRASHED
        # 6. cursor stalled: backlog растёт, job давно завершён
        stalled = dict(base_job, status="completed",
                       finished_at=now - 7200)
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=None,
                        last_job=stalled, now=now, backlog=5)["code"] == \
            DIAG_CURSOR_STALLED
        # 7. never_run
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=None,
                        last_job=None, now=now)["code"] == DIAG_NEVER_RUN
        # 8. attention
        attempt = {"ts": now - 60, "status": "error", "detail": "llm"}
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=attempt,
                        last_job=None, now=now)["code"] == DIAG_ATTENTION
        # 9. ttl_due
        old = {"ts": now - 30 * 3600, "status": "ok", "detail": ""}
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=old,
                        last_job=None, now=now, ttl_seconds=25 * 3600)[
                            "code"] == DIAG_TTL_DUE
        # 10. ok
        fresh = {"ts": now - 60, "status": "ok", "detail": ""}
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=fresh,
                        last_job=None, now=now)["code"] == DIAG_OK
        # живой running-job со свежим heartbeat — ok
        assert diagnose(gate_effective=True, gate_source="env",
                        input_available=True, last_attempt=None,
                        last_job=base_job, now=now)["code"] == DIAG_OK

    def test_diagnose_status_case_and_vocabulary(self):
        """TEST-LIFECYCLE: REGRESSION owner=REQ-B11-E2E.

        Статусы попыток сравниваются без учёта регистра и покрывают
        реальные словари писателей: summary_runs.state DONE/DEGRADED/FAILED
        (`services.summary_run_store.py`), mca_events outcome failed/error,
        task_jobs cancelled/interrupted. Незнакомый/пустой статус — `unknown`
        (не зелёное, REQ-B11-E2E)."""
        now = NOW

        def code(status: str, **extra) -> str:
            attempt = {"ts": now - 60, "status": status, "detail": "", **extra}
            return diagnose(gate_effective=True, gate_source="env",
                            input_available=True, last_attempt=attempt,
                            last_job=None, now=now)["code"]

        assert code("FAILED") == DIAG_ATTENTION
        assert code("failed") == DIAG_ATTENTION
        assert code("CANCELLED") == DIAG_ATTENTION
        assert code("cancelled") == DIAG_ATTENTION
        assert code("interrupted") == DIAG_ATTENTION
        assert code("OK") == DIAG_OK
        assert code("DONE") == DIAG_OK
        assert code("DEGRADED") == DIAG_DEGRADED
        assert code("") == DIAG_UNKNOWN
        assert code("ARCHIVED_LEGACY") == DIAG_UNKNOWN
        # статус-классификация (не исход) не превращает секцию в unknown
        assert code("self", status_semantics="classification") == DIAG_OK

    def test_diagnose_job_status_case_and_vocabulary(self):
        """TEST-LIFECYCLE: REGRESSION owner=REQ-B11-E2E.

        job-ветка `diagnose` обязана быть регистронезависимой и знать реальные
        `task_jobs.status`: `services/task_supervisor.py` (queued/running/
        completed/failed/cancelled/interrupted), `services/graphrag_rebuild.py`
        (building/checkpoint/validating/validated/activated/paused*/
        validation_failed/cancelled), `services/embedding_control_plane.py`
        (`finished` = stale-takeover, НЕ успешный терминал)."""
        now = NOW
        base_job = {"heartbeat_at": now - 60, "updated_at": now - 60,
                    "reason_code": None, "error_code": None,
                    "finished_at": None}
        fresh_attempt = {"ts": now - 60, "status": "ok", "detail": ""}

        def code_job(status: str, **extra) -> str:
            job = {**base_job, "status": status, **extra}
            return diagnose(gate_effective=True, gate_source="env",
                            input_available=True, last_attempt=fresh_attempt,
                            last_job=job, now=now)["code"]

        # прежняя семантика не сломана
        assert code_job("failed") == DIAG_WORKER_CRASHED
        assert code_job("interrupted") == DIAG_WORKER_CRASHED
        assert code_job("running") == DIAG_OK
        assert code_job("completed") == DIAG_OK
        # регистр
        assert code_job("COMPLETED") == DIAG_OK
        assert code_job("FAILED") == DIAG_WORKER_CRASHED
        assert code_job("CANCELLED") == DIAG_ATTENTION
        # реальные не-зелёные статусы
        assert code_job("cancelled") == DIAG_ATTENTION
        assert code_job("validation_failed") == DIAG_ATTENTION
        assert code_job("VALIDATION_FAILED") == DIAG_ATTENTION
        assert code_job("finished") == DIAG_ATTENTION   # stale takeover
        assert code_job("paused_rate_limit") == DIAG_DEGRADED
        assert code_job("paused_provider") == DIAG_DEGRADED
        assert code_job("paused") == DIAG_DEGRADED
        # реальные успешные/активные терминалы
        assert code_job("activated") == DIAG_OK
        assert code_job("validated") == DIAG_OK
        assert code_job("building") == DIAG_OK
        assert code_job("CHECKPOINT") == DIAG_OK
        # незнакомый статус job — не зелёное
        assert code_job("state_xyz") == DIAG_UNKNOWN

    @pytest.mark.asyncio
    async def test_cancelled_job_with_old_success_not_green(self, tmp_path):
        """job-ветка: текущий job `cancelled` при более ранней успешной
        попытке не должен давать `ok` (прод: `cancelled`/`validation_failed`/
        `paused_rate_limit`/`finished` в `task_jobs.status`,
        `prod-checks/raw/main.txt:176,187,190,201`)."""
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 3600)
        await _seed_event(db, ts=NOW - 7200, event_name="graphrag_rebuild",
                          outcome="success", component="graphrag")
        await _seed_job(db, kind="graphrag_rebuild", status="cancelled",
                        now=NOW, finished_at=NOW - 60)
        report = await collect_report(str(tmp_path / "b11.db"), now=NOW)
        graph = next(m for m in report["mechanisms"]
                     if m["key"] == "graph_memory")
        assert graph["last_job"]["status"] == "cancelled"
        assert graph["last_attempt"] is not None
        assert graph["diagnosis"]["code"] == DIAG_ATTENTION
        assert graph["diagnosis"]["code"] != DIAG_OK
        await db.close()

    @pytest.mark.asyncio
    async def test_chat_scope_isolation(self, tmp_path, monkeypatch):
        """chat_id фильтрует счётчики: события чужого чата не попадают."""
        monkeypatch.setenv("DREAM_ENABLED", "1")
        db = await _db(tmp_path)
        await _seed_graph_fact(db, created_at=NOW - 600)
        await _seed_dream_log(db, run_at=NOW - 600, kind="run", status="ok")
        await _seed_dream_log(db, run_at=NOW - 300, kind="run", status="ok",
                              chat_id=-999)
        report = await collect_report(str(tmp_path / "b11.db"),
                                      chat_id=CHAT, now=NOW)
        dream = next(m for m in report["mechanisms"]
                     if m["key"] == "dream")
        assert dream["counters_24h"]["run"]["ok"] == 1
        await db.close()
