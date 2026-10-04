"""ASAP 4.1 волна 5 (эпик asap-4-1-durable-whole-window-summary) — T-4616:
Durable SummaryRun (spec §5 E.1; ADR-1028-8 D6; SQLite `summary_runs` +
`summary_run_stages` v24, append-only; PostgreSQL — no-op).

Покрытие:
  * DDL v24: 3 таблицы (`summary_source_windows` + `summary_runs` +
    `summary_run_stages`), стабильный run_id PK; повторный прогон — no-op;
  * state machine §20: CREATED→SOURCE_READY→…→PUBLISHING→DONE; любая
    стадия → DEGRADED/FAILED;
  * персистентность полного набора полей; run читается после рестарта
    (новый DatabaseService на том же файле);
  * append-only stage events §50.54 (retry = новая строка; UPDATE/DELETE
    истории не существует — scan);
  * kill-switch `SUMMARY_RUN_DURABLE_ENABLED` (OFF → runs не пишутся —
    бит-в-бит 2.58.46);
  * TTL-purge гейт: только после DONE/DEGRADED/FAILED;
  * rank-guard: checkpoint не отматывается назад.
"""
import time

import pytest

from config.settings import Settings
from services.database import DatabaseService, _SCHEMA_VERSION_DREAM_RUNS
from services import summary_run_store as srs

pytestmark = pytest.mark.asap41


@pytest.fixture(autouse=True)
def _env_on(monkeypatch):
    """Kill-switch зоны E default ON для изоляции конфигурации теста."""
    monkeypatch.setattr(Settings, "SUMMARY_RUN_DURABLE_ENABLED", True,
                        raising=False)
    monkeypatch.setattr(Settings, "SUMMARY_SOURCE_WINDOW_RETENTION_DAYS", 7,
                        raising=False)


async def _fresh(tmp_path, name="runs.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── DDL v24 (3 таблицы; spec §10) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_v24_migration_fresh_db_three_tables(tmp_path):
    d = await _fresh(tmp_path, "fresh.db")
    cursor = await d.db.execute("PRAGMA user_version")
    # mca-06 (ADR-1028-9 D5): хвост реестра — v25 (mca_pipeline_runs:
    # chat_id/report_json + индекс); mca-08 (ADR-1028-11 D3): хвост — v26;
    # fresh init доводит user_version до актуального конца реестра
    # (v24-таблицы созданы ранее в цепочке) — фронтир >= v25.
    assert int((await cursor.fetchone())[0]) >= _SCHEMA_VERSION_DREAM_RUNS == 25
    names = set()
    cursor = await d.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")
    for row in await cursor.fetchall():
        names.add(row["name"])
    for table in ("summary_source_windows", "summary_runs",
                  "summary_run_stages"):
        assert table in names
    await d.close()


@pytest.mark.asyncio
async def test_v24_migration_idempotent_rerun(tmp_path):
    path = str(tmp_path / "idem.db")
    d1 = DatabaseService(path)
    await d1.initialize()
    await srs.create_run(d1, "run-keep", -100)
    d2 = DatabaseService(path)
    await d2.initialize()          # повторный прогон — no-op
    run = await srs.get_run(d2, "run-keep")
    assert run is not None         # данные не потеряны, таблицы не пересозданы
    await d1.close()
    await d2.close()


@pytest.mark.asyncio
async def test_pg_noop_no_pg_sql_in_zone_e_modules():
    """PG — no-op (spec §10.5): в зоне E нет asyncpg/PG-DDL/cover_style_."""
    import inspect
    import services.summary_run_store as mod
    src = inspect.getsource(mod)
    assert "asyncpg" not in src and "cover_style_" not in src
    for method in ("create_summary_run", "update_summary_run_state",
                   "set_summary_run_publication", "get_summary_run",
                   "record_summary_run_stage", "purge_expired_summary_runs"):
        assert hasattr(DatabaseService, method)


# ── State machine §20 ───────────────────────────────────────────────────

def test_state_machine_happy_path_transitions():
    path = ("CREATED", "SOURCE_READY", "STRUCTURING", "STRUCTURE_READY",
            "WRITING", "REVIEWING", "TEXT_READY", "BASE_COVER", "STYLE_EDIT",
            "PUBLISHING", "DONE")
    for a, b in zip(path, path[1:]):
        assert srs.transition_allowed(a, b), (a, b)
    assert not srs.transition_allowed("DONE", "WRITING")
    assert not srs.transition_allowed("FAILED", "PUBLISHING")


def test_state_machine_any_stage_degraded_failed():
    for state in ("CREATED", "SOURCE_READY", "STRUCTURING",
                  "STRUCTURE_READY", "WRITING", "REVIEWING", "TEXT_READY",
                  "BASE_COVER", "STYLE_EDIT", "PUBLISHING"):
        assert srs.transition_allowed(state, "DEGRADED"), state
        assert srs.transition_allowed(state, "FAILED"), state
    for terminal in ("DONE", "DEGRADED", "FAILED"):
        assert not srs.transition_allowed(terminal, "TEXT_READY")


@pytest.mark.asyncio
async def test_run_state_machine_persisted_full_flow(tmp_path):
    d = await _fresh(tmp_path, "flow.db")
    rid = "run-flow"
    assert await srs.create_run(d, rid, -100, manual=True) is True
    for state in (srs.STATE_SOURCE_READY, srs.STATE_STRUCTURING,
                  srs.STATE_STRUCTURE_READY, srs.STATE_WRITING,
                  srs.STATE_REVIEWING, srs.STATE_TEXT_READY,
                  srs.STATE_BASE_COVER, srs.STATE_STYLE_EDIT,
                  srs.STATE_PUBLISHING, srs.STATE_DONE):
        assert await srs.set_state(d, rid, state) is True, state
    run = await srs.get_run(d, rid)
    assert run["state"] == "DONE"
    assert run["manual"] == 1
    assert run["chat_id"] == -100
    await d.close()


@pytest.mark.asyncio
async def test_run_full_field_set_persisted(tmp_path):
    d = await _fresh(tmp_path, "fields.db")
    rid = "run-fields"
    await srs.create_run(d, rid, -100, manual=True)
    await srs.set_state(d, rid, srs.STATE_SOURCE_READY, window_from=1000,
                        window_to=2000, source_ref="summary_source_window:x",
                        pipeline_health="ok")
    await srs.complete_publication(d, rid, result_ref="bot_output:77")
    run = await srs.get_run(d, rid)
    assert run["state"] == "SOURCE_READY"
    assert run["window_from"] == 1000
    assert run["window_to"] == 2000
    assert run["source_ref"] == "summary_source_window:x"
    assert run["publication_status"] == "published"
    assert run["publication_result_ref"] == "bot_output:77"
    assert run["pipeline_health"] == "ok"
    await d.close()


@pytest.mark.asyncio
async def test_run_readable_after_process_restart(tmp_path):
    path = str(tmp_path / "restart.db")
    d1 = DatabaseService(path)
    await d1.initialize()
    rid = "run-restart"
    await srs.create_run(d1, rid, -100)
    await srs.set_state(d1, rid, srs.STATE_PUBLISHING)
    await srs.record_stage(d1, rid, "l1", status="ok", started_at=123,
                           attempt=1, provider="host.example", model="m-1")
    # «Рестарт»: новый инстанс DatabaseService на том же файле.
    d2 = DatabaseService(path)
    await d2.initialize()
    run = await srs.get_run(d2, rid)
    assert run is not None and run["state"] == "PUBLISHING"
    stages = await srs.stage_history(d2, rid)
    assert len(stages) == 1
    assert stages[0]["stage"] == "l1" and stages[0]["status"] == "ok"
    assert stages[0]["provider"] == "host.example"
    last = await srs.last_completed_stage(d2, rid)
    assert last is not None and last["stage"] == "l1"
    await d1.close()
    await d2.close()


# ── Append-only stage events (§50.54) ──────────────────────────────────

def test_stage_events_append_only_no_update_delete_surface():
    """Append-only §50.54: строки стадий только INSERT; UPDATE строк стадий
    не существует; DELETE — только TTL-очистка терминальных run'ов."""
    import inspect
    from services.database import DatabaseService as DS
    src = inspect.getsource(DS)
    assert "UPDATE summary_run_stages" not in src
    deletes = [line.strip() for line in src.splitlines()
               if "DELETE" in line and "summary_run_stages" in line]
    assert len(deletes) == 1, deletes   # только purge_expired_summary_runs


@pytest.mark.asyncio
async def test_stage_retry_is_new_row_history_kept(tmp_path):
    d = await _fresh(tmp_path, "stages.db")
    rid = "run-retry"
    await srs.create_run(d, rid, -100)
    await srs.record_stage(d, rid, "l1", status="failed", attempt=1,
                           reason_code="timeout")
    await srs.record_stage(d, rid, "l1", status="ok", attempt=2)
    rows = await srs.stage_history(d, rid)
    assert [r["status"] for r in rows] == ["failed", "ok"]
    assert [r["attempt"] for r in rows] == [1, 2]
    # История не переписывается: обе строки живы.
    last = await srs.last_completed_stage(d, rid)
    assert last["attempt"] == 2
    await d.close()


# ── publication_status идемпотентность (T-4617 базис) ──────────────────

@pytest.mark.asyncio
async def test_mark_publishing_pending_then_publishing(tmp_path):
    d = await _fresh(tmp_path, "pub.db")
    rid = "run-pub"
    await srs.create_run(d, rid, -100)
    proceed, status = await srs.mark_publishing(d, rid)
    assert proceed is True and status is None
    run = await srs.get_run(d, rid)
    assert run["publication_status"] == "publishing"   # зафиксировано ДО send
    await d.close()


@pytest.mark.asyncio
async def test_mark_publishing_published_never_republished(tmp_path):
    d = await _fresh(tmp_path, "pub2.db")
    rid = "run-pub2"
    await srs.create_run(d, rid, -100)
    await srs.complete_publication(d, rid, result_ref="bot_output:5")
    proceed, status = await srs.mark_publishing(d, rid)
    assert proceed is False and status == "published"
    # Повторная попытка записи published — no-op (идемпотентность).
    assert await srs.complete_publication(d, rid, result_ref="other") is False
    run = await srs.get_run(d, rid)
    assert run["publication_result_ref"] == "bot_output:5"
    await d.close()


@pytest.mark.asyncio
async def test_mark_publishing_stuck_publishing_detected(tmp_path):
    d = await _fresh(tmp_path, "pub3.db")
    rid = "run-pub3"
    await srs.create_run(d, rid, -100)
    await srs.mark_publishing(d, rid)
    proceed, status = await srs.mark_publishing(d, rid)
    assert proceed is False and status == "publishing"
    await d.close()


# ── Kill-switch (OFF = бит-в-бит 2.58.46) ──────────────────────────────

@pytest.mark.asyncio
async def test_kill_switch_off_no_persistence(tmp_path, monkeypatch):
    d = await _fresh(tmp_path, "off.db")
    rid = "run-off"
    monkeypatch.setattr(Settings, "SUMMARY_RUN_DURABLE_ENABLED", False,
                        raising=False)
    assert await srs.create_run(d, rid, -100) is False
    assert await srs.set_state(d, rid, srs.STATE_WRITING) is False
    assert await srs.record_stage(d, rid, "l1") is None
    assert await srs.mark_publishing(d, rid) == (True, None)
    assert await srs.get_run(d, rid) is None
    cursor = await d.db.execute("SELECT COUNT(*) c FROM summary_runs")
    assert int((await cursor.fetchone())["c"]) == 0
    cursor = await d.db.execute("SELECT COUNT(*) c FROM summary_run_stages")
    assert int((await cursor.fetchone())["c"]) == 0
    await d.close()


# ── TTL-purge гейт (только после DONE/FAILED) ──────────────────────────

@pytest.mark.asyncio
async def test_ttl_purge_gate_terminal_only(tmp_path):
    d = await _fresh(tmp_path, "purge.db")
    now = int(time.time())
    old = now - 30 * 86400                      # сильно старше TTL (7д)
    # Терминальный DONE run + стадия + окно → удаляются.
    await d.create_summary_run(run_id="run-done", chat_id=-1, state="DONE",
                               created_at=old)
    await d.record_summary_run_stage("run-done", "l1", status="ok",
                                     started_at=old)
    await d.save_summary_source_window(
        run_id="run-done", chat_id=-1, window_from=old, window_to=old,
        source_message_count=3, messages_json="[]", created_at=old)
    # Незавершённый (PUBLISHING) run + окно → НЕ удаляются.
    await d.create_summary_run(run_id="run-stuck", chat_id=-1,
                               state="PUBLISHING", created_at=old)
    await d.save_summary_source_window(
        run_id="run-stuck", chat_id=-1, window_from=old, window_to=old,
        source_message_count=3, messages_json="[]", created_at=old)
    purged = await srs.purge_expired_runs(d, now=now)
    assert purged == 1                          # только DONE-run
    assert await srs.get_run(d, "run-done") is None
    stages = await srs.stage_history(d, "run-done")
    assert stages == []
    win_done = await d.get_summary_source_window("run-done")
    assert win_done is None                     # окно терминального удалено
    stuck = await srs.get_run(d, "run-stuck")
    assert stuck is not None                    # незавершённый не задет
    win_stuck = await d.get_summary_source_window("run-stuck")
    assert win_stuck is not None                # его окно не тронуто
    await d.close()


@pytest.mark.asyncio
async def test_ttl_purge_no_terminal_states_noop(tmp_path):
    d = await _fresh(tmp_path, "purge2.db")
    now = int(time.time())
    await d.create_summary_run(run_id="run-a", chat_id=-1, state="CREATED",
                               created_at=now - 30 * 86400)
    assert await srs.purge_expired_runs(d, now=now) == 0
    assert await srs.get_run(d, "run-a") is not None
    await d.close()


# ── Rank-guard (resume не отматывает checkpoint) ────────────────────────

@pytest.mark.asyncio
async def test_rank_guard_no_rewind(tmp_path):
    d = await _fresh(tmp_path, "rank.db")
    rid = "run-rank"
    await srs.create_run(d, rid, -100)
    await srs.set_state(d, rid, srs.STATE_WRITING)
    assert await srs.set_state(d, rid, srs.STATE_STRUCTURING) is False
    assert (await srs.get_run(d, rid))["state"] == "WRITING"
    # Терминальный не реанимируется.
    await srs.set_state(d, rid, srs.STATE_DONE)
    assert await srs.set_state(d, rid, srs.STATE_TEXT_READY) is False
    assert (await srs.get_run(d, rid))["state"] == "DONE"
    await d.close()


def test_terminal_state_for_run_mapping():
    assert srs.terminal_state_for_run(
        status="ok", health="ok", published=True) == "DONE"
    assert srs.terminal_state_for_run(
        status="ok", health="degraded", published=True) == "DEGRADED"
    assert srs.terminal_state_for_run(
        status="failed", health="failed") == "FAILED"
    assert srs.terminal_state_for_run(
        status="ok", health="ok", published=False) == "FAILED"


# ── Resume §21: reader активного run'а (рестарт → докат, не пересоздание) ──

@pytest.mark.asyncio
async def test_active_run_reader_resume_semantics(tmp_path):
    """Рестарт: незавершённый run чата возвращается читателем (тот же
    стабильный run_id — докат); терминальный — нет (свежий run)."""
    d = await _fresh(tmp_path, "active.db")
    await srs.create_run(d, "run-active", -90)
    await srs.set_state(d, "run-active", srs.STATE_WRITING)
    prior = await d.get_active_summary_run_for_chat(-90)
    assert prior is not None and prior["run_id"] == "run-active"
    assert prior["state"] == "WRITING"
    await srs.set_state(d, "run-active", srs.STATE_DONE)
    assert await d.get_active_summary_run_for_chat(-90) is None
    await d.close()
