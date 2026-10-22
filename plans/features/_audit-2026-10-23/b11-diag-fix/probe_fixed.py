"""B11-DIAG-FIX: воспроизведение прод-строки summary_runs (read-only отчёт).

Сценарий 1 (прод 22.10.2026, raw/main3.txt):
  state='FAILED', publication_status='failed', pipeline_health='degraded'
  → до фикса инструмент показывал `ok` (регистр), после — `attention`.

Сценарий 2: state='DEGRADED', publication_status='published'
  → `degraded` (не зелёное).

Сценарий 3: state='DONE', publication_status='published'
  → `ok` (контракт не сломан).

Плюс backlog: `graph_facts_vec` — vec0-таблица; без sqlite_vec запрос
падал и поле молчало `null`. Теперь честный статус + причина.

Запуск: PYTHONPATH=. .venv/Scripts/python.exe <этот файл>
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.database import DatabaseService          # noqa: E402
from tools.v63_b11_mechanisms_report import collect_report  # noqa: E402

CHAT = -1002661910336
NOW = 1792674860          # updated_at прод-рана из raw/main3.txt


async def _seed(db, run_id: str, state: str, publication: str,
                health: str) -> None:
    await db.db.execute(
        "INSERT INTO summary_runs (run_id, chat_id, state, manual, "
        "created_at, updated_at, publication_status, pipeline_health) "
        "VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
        (run_id, CHAT, state, NOW - 500, NOW - 400, publication, health))
    await db.db.commit()


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "b11-probe.db")
        db = DatabaseService(path)
        await db.initialize()
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
            "timestamp, media_type, author_name, tg_message_id) VALUES "
            "(1, ?, 'сообщение', NULL, ?, 'text', '', NULL)",
            (CHAT, NOW - 600))
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, 'факт без эмбеддинга', 'chat_history', ?)",
            (CHAT, NOW - 3600))
        await db.db.commit()
        out = {}
        for label, (state, pub, health) in {
                "prod_FAILED": ("FAILED", "failed", "degraded"),
                "prod_DEGRADED": ("DEGRADED", "published", "degraded"),
                "prod_DONE": ("DONE", "published", "ok"),
        }.items():
            await db.db.execute("DELETE FROM summary_runs")
            await _seed(db, f"run-{label}", state, pub, health)
            report = await collect_report(path, chat_id=CHAT, now=NOW)
            summary = next(m for m in report["mechanisms"]
                           if m["key"] == "summary_scheduler")
            out[label] = summary["diagnosis"]
        report = await collect_report(path, chat_id=CHAT, now=NOW)
        graph = next(m for m in report["mechanisms"]
                     if m["key"] == "graph_memory")
        out["backlog"] = graph["write_result"]
        out["summary_block"] = report["summary"]
        await db.close()

    # Сценарий 4 (прод-эквивалент backlog=4162): vec0-таблица ЕСТЬ, но
    # read-only коннект её не видит без загруженного расширения.
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "b11-vec.db")
        db = DatabaseService(path)
        await db.initialize()
        for i in range(3):
            await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
                "VALUES (?, ?, 'chat_history', ?)",
                (CHAT, f"факт-{i}", NOW - 3600 + i))
        await db.db.commit()
        await db.close()
        import sqlite3
        import sqlite_vec
        conn = sqlite3.connect(path)
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        conn.execute(
            "CREATE VIRTUAL TABLE graph_facts_vec USING vec0("
            "embedding float[4] distance_metric=cosine, +fact_id INTEGER, "
            "+chat_id INTEGER, +origin TEXT, +expires_at INTEGER)")
        for i in (1, 2):
            conn.execute(
                "INSERT INTO graph_facts_vec (embedding, fact_id, chat_id, "
                "origin, expires_at) VALUES (?, ?, ?, 'chat_history', NULL)",
                ("[0.1, 0.2, 0.3, 0.4]", i, CHAT))
        conn.commit()
        conn.close()
        report = await collect_report(path, chat_id=CHAT, now=NOW)
        graph = next(m for m in report["mechanisms"]
                     if m["key"] == "graph_memory")
        out["backlog_with_vec"] = graph["write_result"]
        out["backlog_with_vec_diagnosis"] = graph["diagnosis"]
    # Сценарий 5 (ревью N1): job-ветка. Текущий job cancelled/paused/… при
    # более ранней УСПЕШНОЙ попытке не должен давать ok.
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "b11-jobs.db")
        db = DatabaseService(path)
        await db.initialize()
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, 'факт', 'chat_history', ?)", (CHAT, NOW - 3600))
        await db.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
            "component, stage) VALUES (?, 'INFO', 'graphrag_rebuild', "
            "'success', ?, 'graphrag', 'run')", (NOW - 7200, CHAT))
        await db.db.commit()
        jobs = {}
        for job_status in ("cancelled", "validation_failed", "finished",
                           "paused_rate_limit", "failed", "completed"):
            await db.db.execute("DELETE FROM task_jobs")
            await db.db.execute(
                "INSERT INTO task_jobs (job_id, owner, kind, coalesce_key, "
                "payload, status, reason_code, error_code, attempt, "
                "max_attempts, deadline_at, heartbeat_at, generation, "
                "fencing_token, created_at, updated_at, finished_at) VALUES "
                "(?, 'memory', 'graphrag_rebuild', NULL, NULL, ?, "
                "'test_reason', NULL, 1, 3, NULL, ?, 0, 0, ?, ?, ?)",
                (f"job-{job_status}", job_status, NOW - 60, NOW - 60,
                 NOW - 60, NOW - 60))
            await db.db.commit()
            report = await collect_report(path, chat_id=CHAT, now=NOW)
            graph = next(m for m in report["mechanisms"]
                         if m["key"] == "graph_memory")
            jobs[job_status] = {
                "code": graph["diagnosis"]["code"],
                "detail": graph["diagnosis"]["detail"],
                "old_success_attempt_present":
                    graph["last_attempt"] is not None,
            }
        out["job_branch"] = jobs
        await db.close()
        payload = json.dumps(out, ensure_ascii=False, indent=1)
        # Пишем сразу UTF-8 (консольный redirect на Windows портит кириллицу).
        Path(__file__).with_name("probe-fixed-output.json").write_text(
            payload + "\n", encoding="utf-8")
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
