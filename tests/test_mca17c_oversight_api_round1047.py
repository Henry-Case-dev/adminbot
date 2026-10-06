"""MCA-17c `mca-17c-analytics-matrix` (round 10.47, ADR-1028-23) — API.

Контрактные тесты write/read-API витрины наблюдаемости (spec §5/§7,
T-5189-частично; Builder-покрытие):
  * санкция routes +3: NEW `web/api/oversight_router.py` — ровно 3 маршрута
    (GET /api/oversight/runs, GET /api/oversight/experience/funnel,
    POST /api/oversight/jobs/{job_id}/action — единственный write);
  * TH-1/RBAC (RED-first): 401 без initData и 403 не-глоб-админ на ВСЕХ трёх;
  * runs: агрегаты поверх mca_events, read-render статуса (partial при
    failed+success — ошибка ветви не стирает успехи; degraded по
    run_degraded; stalled — ОТДЕЛЬНЫЙ флаг, не подмена outcome; silent —
    валидное молчание ≠ падение), серверные фильтры (status/chat),
    keyset-пагинация без дублей, detail по run_id (+ контракт стадий из
    PIPELINE_VERSIONS), R17-форма (без usage_json/source_ref_json/stack);
  * funnel: периодные счётчики из существующих таблиц mca-16, chat-фильтр,
    unknown отдельным числом, notes присутствуют;
  * POST action: cancel (queued → cancelled, fencing bump; повтор —
    идемпотентный no-op БЕЗ нового bump), resume failed → queued, retry
    failed → queued + next_retry_at + СОХРАНЁННЫЙ error_code, 404/409/422,
    гейт супервизора OFF → 409, audit `oversight_job_action` — одно
    событие на запрос (TH-8) c action/actor/idempotent;
  * форма ответов: ключи dict'ов == контракту (защита UI-полосы).

R17: в тестах числа/коды/ID, секретов нет.
"""
import asyncio
import json
import time
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import mca_events
from services import mca_gates
from services import lore_runtime
from services.database import DatabaseService
from services.permissions import Permissions
from services.config_cache import ConfigCache
from services.task_supervisor import TaskJobStore
from web.api import deps as deps_mod
from web.api.oversight_router import oversight17c_router

TEST_TOKEN = "123456:TEST_MCA17C_TOKEN"
ADMIN_ID = 111222
USER_ID = 999888
CHAT = -100500
NOW = int(time.time())   # динамический: периоды funnel считаются от now


# ── инфраструктура (прецедент test_mca12_stories_round1046) ─────────────────

def make_init_data(token: str, user_id: int) -> str:
    import hashlib
    import hmac
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "a"}, separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, v)
                           for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _fake_cache(*, admin: bool) -> ConfigCache:
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    if admin:
        cache._roles = {
            "admin": {"permissions": {"wildcard": True},
                      "is_custom": False, "role_type": "global_admin"},
        }
        cache._permissions = {
            "admin": Permissions.from_dict({"wildcard": True})}
        cache._admins = {ADMIN_ID: "admin"}
    else:
        cache._roles = {
            "user": {"permissions": {"sections": ["memory"]},
                     "is_custom": False, "role_type": "user"},
        }
        cache._permissions = {
            "user": Permissions.from_dict({"sections": ["memory"]})}
        cache._admins = {}
    cache._pg_available = True
    cache._initialized = True
    cache._pg = None
    return cache


def _client(db, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.state.cache = _fake_cache(admin=admin)
    app.include_router(oversight17c_router, prefix="/api/oversight")
    return TestClient(app)


def _hdr(user=ADMIN_ID):
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user)}


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


@pytest.fixture(autouse=True)
def _clean_events():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture()
def db(tmp_path):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    database = DatabaseService(str(tmp_path / "mca17c.db"))
    loop.run_until_complete(database.initialize())
    yield database
    loop.run_until_complete(database.close())
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _wire_lore(db, monkeypatch):
    """Роутер читает БД через lore_runtime.get_lore_db() — подключаем
    фикстурную (прецедент oversight-зон)."""
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)


def _exec(db, sql, params=()):
    return _run(db.db.execute(sql, params))


def _seed_event(db, *, run_id, event_name, outcome, ts, stage=None,
                seq=None, reason=None, chat=CHAT, ptype="summary.window",
                error_json=None, component="summary_worker"):
    _exec(
        db,
        "INSERT INTO mca_events (ts, level, event_name, outcome, trace_id, "
        "operation_id, chat_id, component, stage, reason_code, model, "
        "provider, error_json, pipeline_run_id, pipeline_type, "
        "pipeline_version, span_id, event_sequence, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, "INFO", event_name, outcome, f"trace-{run_id}", f"op-{run_id}",
         chat, component, stage, reason, "gpt-x", "openai", error_json,
         run_id, ptype, "1", f"sp-{run_id}-{seq}", seq, None))
    _run(db.db.commit())


# ═══ Санкция routes +3 ═══════════════════════════════════════════════════════

def test_routes_exactly_three():
    paths = sorted({r.path for r in oversight17c_router.routes})
    assert paths == ["/experience/funnel", "/jobs/{job_id}/action", "/runs"]
    methods = {r.path: sorted(r.methods) for r in oversight17c_router.routes}
    assert methods["/runs"] == ["GET"]
    assert methods["/experience/funnel"] == ["GET"]
    assert methods["/jobs/{job_id}/action"] == ["POST"]


# ═══ TH-1/RBAC: 401/403 на всех трёх (RED-first) ═════════════════════════════

def test_rbac_401_403_all_three(db):
    client = _client(db, admin=False)      # не-глоб-админ
    probes = (("get", "/api/oversight/runs"),
              ("get", "/api/oversight/experience/funnel"),
              ("post", "/api/oversight/jobs/j1/action"))
    for method, url in probes:
        # 401 без initData
        resp = client.post(url, json={}) if method == "post" \
            else client.get(url)
        assert resp.status_code == 401, (method, url, resp.status_code)
        # 403 не-глоб-админ
        if method == "post":
            resp = client.post(url, headers=_hdr(USER_ID), json={})
        else:
            resp = client.get(url, headers=_hdr(USER_ID))
        assert resp.status_code == 403, (method, url, resp.status_code)


# ═══ GET /runs: агрегаты + read-render статуса ═══════════════════════════════

def _gates_on(monkeypatch):
    monkeypatch.setattr(mca_gates, "observability_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "telemetry_store_enabled", lambda: True)


def test_runs_list_shape_and_status_render(db, monkeypatch):
    _gates_on(monkeypatch)
    # run A: success в конце, одна failed-ветвь + run_partial → partial
    _seed_event(db, run_id="rA", event_name="STAGE_DONE", outcome="success",
                ts=NOW - 100, stage="collect", seq=1)
    _seed_event(db, run_id="rA", event_name="STAGE_DONE", outcome="failed",
                ts=NOW - 90, stage="publish", seq=2,
                error_json=json.dumps({"type": "SendError",
                                       "cause": "Timeout",
                                       "stack": "SECRET-STACK"}))
    _seed_event(db, run_id="rA", event_name="RUN_DONE", outcome="success",
                ts=NOW - 80, seq=3, reason="run_partial")
    # run B: валидное молчание (silent) → succeeded
    _seed_event(db, run_id="rB", event_name="SUMMARY_SILENT",
                outcome="silent", ts=NOW - 50, seq=1, ptype="direct.reply")
    # run C: degraded
    _seed_event(db, run_id="rC", event_name="STAGE_DONE",
                outcome="skipped", ts=NOW - 40, seq=1, reason="run_degraded")

    client = _client(db, admin=True)
    resp = client.get("/api/oversight/runs", headers=_hdr())
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True and data["enabled"] is True
    assert set(data.keys()) == {"available", "enabled", "runs", "counts",
                                "next_cursor", "filters", "generated_at"}
    by_id = {r["pipeline_run_id"]: r for r in data["runs"]}
    assert by_id["rA"]["status"] == "partial"     # failed+success → partial
    assert by_id["rA"]["stages_failed"] == 1
    assert by_id["rA"]["stages_ok"] == 2
    assert by_id["rA"]["error_last"] == {"type": "SendError",
                                         "cause": "Timeout"}  # БЕЗ stack
    assert by_id["rB"]["status"] == "succeeded"   # silent ≠ падение
    assert by_id["rC"]["status"] == "degraded"
    assert by_id["rA"]["duration_ms"] == 20000    # (100-80)с → мс
    # R17-форма хедера
    allowed = {"pipeline_run_id", "pipeline_type", "pipeline_version",
               "status", "stalled", "started_ts", "updated_ts",
               "duration_ms", "events_total", "stages_total",
               "stages_failed", "stages_ok", "chat_id", "component",
               "model", "provider", "trace_id", "last_stage",
               "reason_codes", "error_last"}
    for run in data["runs"]:
        assert set(run.keys()) <= allowed
        assert "usage_json" not in run and "source_ref_json" not in run


def test_runs_stalled_flag_not_status(db, monkeypatch):
    _gates_on(monkeypatch)
    _seed_event(db, run_id="rS", event_name="STAGE_DONE", outcome="success",
                ts=NOW - 30, seq=1, reason="run_stalled")
    client = _client(db, admin=True)
    data = client.get("/api/oversight/runs", headers=_hdr()).json()
    run = next(r for r in data["runs"] if r["pipeline_run_id"] == "rS")
    assert run["stalled"] is True
    assert run["status"] == "succeeded"     # stalled — диагностика, не исход


def test_runs_server_filters_and_keyset(db, monkeypatch):
    _gates_on(monkeypatch)
    _seed_event(db, run_id="f1", event_name="E", outcome="success",
                ts=NOW - 300, chat=CHAT)
    _seed_event(db, run_id="f2", event_name="E", outcome="failed",
                ts=NOW - 200, chat=-100999)
    _seed_event(db, run_id="f3", event_name="E", outcome="success",
                ts=NOW - 100, chat=CHAT)
    client = _client(db, admin=True)
    # фильтр чата — серверный (чужой чат отфильтрован)
    data = client.get("/api/oversight/runs", headers=_hdr(),
                      params={"chat_id": CHAT}).json()
    ids = {r["pipeline_run_id"] for r in data["runs"]}
    assert ids == {"f1", "f3"}
    # фильтр статуса — серверный
    data = client.get("/api/oversight/runs", headers=_hdr(),
                      params={"status": "failed"}).json()
    assert {r["pipeline_run_id"] for r in data["runs"]} == {"f2"}
    # keyset: limit=1 → следующая страница без дублей
    page1 = client.get("/api/oversight/runs", headers=_hdr(),
                       params={"limit": 1}).json()
    assert len(page1["runs"]) == 1
    assert page1["next_cursor"] is not None
    page2 = client.get("/api/oversight/runs", headers=_hdr(),
                       params={"limit": 10,
                               "cursor": page1["next_cursor"]}).json()
    assert page1["runs"][0]["pipeline_run_id"] not in \
        {r["pipeline_run_id"] for r in page2["runs"]}
    # невалидный status → 422 (серверная валидация, TH-4/TH-2)
    resp = client.get("/api/oversight/runs", headers=_hdr(),
                      params={"status": "DROP"})
    assert resp.status_code == 422


def test_runs_detail_contract_stages(db, monkeypatch):
    _gates_on(monkeypatch)
    _seed_event(db, run_id="d1", event_name="STAGE_DONE", outcome="success",
                ts=NOW - 20, stage="collect", seq=1)
    _seed_event(db, run_id="d1", event_name="STAGE_DONE", outcome="success",
                ts=NOW - 10, stage="summarize", seq=2)
    client = _client(db, admin=True)
    data = client.get("/api/oversight/runs", headers=_hdr(),
                      params={"run_id": "d1"}).json()
    assert data["run"] is not None
    run = data["run"]
    assert set(run.keys()) >= {"events", "required_stages",
                               "optional_stages", "status"}
    assert run["required_stages"] is not None  # summary.window v1 известен
    assert "summarize" in run["required_stages"]
    assert [e["stage"] for e in run["events"]] == ["collect", "summarize"]
    ev_allowed = {"event_name", "ts", "event_sequence", "outcome", "stage",
                  "status", "reason_code", "component", "span_id",
                  "parent_span_id", "pipeline_type", "pipeline_version",
                  "attempt", "duration_ms", "model", "provider", "chat_id",
                  "operation_id", "trace_id", "job_id", "heartbeat_at",
                  "progress_at", "deadline_at", "error_type", "error_cause"}
    for ev in run["events"]:
        assert set(ev.keys()) <= ev_allowed
        assert "usage_json" not in ev and "error_json" not in ev
    # неизвестный run → честный null (fail-open форма, не 500)
    data = client.get("/api/oversight/runs", headers=_hdr(),
                      params={"run_id": "nope"}).json()
    assert data["run"] is None


def test_runs_gates_off_disabled(db, monkeypatch):
    monkeypatch.setattr(mca_gates, "observability_enabled", lambda: False)
    monkeypatch.setattr(mca_gates, "telemetry_store_enabled", lambda: True)
    client = _client(db, admin=True)
    data = client.get("/api/oversight/runs", headers=_hdr()).json()
    assert data["available"] is False and data["enabled"] is False
    assert data["runs"] == []               # честный disabled, не нули-зелень


# ═══ GET /experience/funnel ══════════════════════════════════════════════════

def _seed_funnel(db):
    _exec(db,
          "INSERT INTO mca_experience_episodes (episode_id, idempotency_key, "
          "created_at, updated_at, scope, outcome_kind, outcome_source, "
          "outcome_reliability) VALUES ('e1','k1',?,?,'chat','success',"
          "'technical','verified')", (NOW - 100, NOW - 100))
    _exec(db,
          "INSERT INTO mca_experience_episodes (episode_id, idempotency_key, "
          "created_at, updated_at, scope, chat_id, outcome_kind, "
          "outcome_source, outcome_reliability) VALUES "
          "('e2','k2',?,?,'chat',?,'unknown','technical','hypothesis')",
          (NOW - 90, NOW - 90, CHAT))
    for lid, st in (("l1", "active"), ("l2", "candidate"), ("l3", "suspended")):
        _exec(db,
              "INSERT INTO mca_lessons (lesson_id, version, type, scope, "
              "recommendation, status, created_at, updated_at) VALUES "
              "(?,1,'tool_usage','global','r',?,?,?)", (lid, st, NOW, NOW))
    _exec(db,
          "INSERT INTO mca_lesson_applications (dedup_key, lesson_id, "
          "lesson_version, applied_at, outcome) VALUES "
          "('a1','l1',1,?,'success')", (NOW - 50,))
    _exec(db,
          "INSERT INTO mca_lesson_applications (dedup_key, lesson_id, "
          "lesson_version, applied_at, chat_id, outcome) VALUES "
          "('a2','l1',1,?,?,'unknown')", (NOW - 40, CHAT))
    _exec(db,
          "INSERT INTO mca_experience_feedback (feedback_id, dedup_key, "
          "source_kind, reliability, authority, status, chat_id, ts) VALUES "
          "('fb1','dk1','owner_correction','verified','owner','active',?,?)",
          (CHAT, NOW - 30))
    _run(db.db.commit())


def test_funnel_counts_and_notes(db, monkeypatch):
    monkeypatch.setattr(mca_gates, "experience_lessons_enabled", lambda: True)
    _seed_funnel(db)
    client = _client(db, admin=True)
    data = client.get("/api/oversight/experience/funnel", headers=_hdr(),
                      params={"days": 30}).json()
    assert data["available"] is True and data["enabled"] is True
    assert data["episodes"]["total"] == 2
    assert data["episodes"]["success"] == 1
    assert data["episodes"]["unknown"] == 1     # unknown отдельным числом
    assert data["lessons"]["active"] == 1
    assert data["lessons"]["candidate"] == 1
    assert data["lessons"]["scope"] == "current"
    assert data["applications"]["total"] == 2
    assert data["applications"]["unknown"] == 1
    assert data["applications"]["unique_lessons"] == 1
    assert data["feedback"]["total"] == 1
    assert any("≠" in n for n in data["notes"])
    # chat-фильтр — серверный
    data2 = client.get("/api/oversight/experience/funnel", headers=_hdr(),
                       params={"days": 30, "chat_id": CHAT}).json()
    assert data2["episodes"]["total"] == 1
    assert data2["episodes"]["unknown"] == 1
    # ключи == контракту (защита UI-полосы)
    assert set(data.keys()) == {"available", "enabled", "period", "episodes",
                                "lessons", "applications", "feedback",
                                "notes", "generated_at"}


def test_funnel_gate_off_disabled(db, monkeypatch):
    monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                        lambda: False)
    client = _client(db, admin=True)
    data = client.get("/api/oversight/experience/funnel",
                      headers=_hdr()).json()
    assert data["enabled"] is False and data["available"] is False


# ═══ POST /jobs/{job_id}/action ══════════════════════════════════════════════

def test_action_cancel_idempotent_and_fencing(db):
    store = TaskJobStore(db)
    jid = _run(store.enqueue(owner="t", kind="secondary"))
    before = _run(store.get(jid))
    assert before["status"] == "queued"
    client = _client(db, admin=True)
    resp = client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                       json={"action": "cancel"})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"ok": True, "job_id": jid, "action": "cancel",
                    "status": "cancelled", "changed": True,
                    "idempotent": False, "delivery": "accepted"}
    after = _run(store.get(jid))
    assert after["status"] == "cancelled"
    assert int(after["fencing_token"]) == int(before["fencing_token"]) + 1
    # повтор cancel — идемпотентный no-op, токен НЕ растёт
    resp2 = client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                        json={"action": "cancel"})
    assert resp2.status_code == 200
    assert resp2.json()["idempotent"] is True
    assert resp2.json()["changed"] is False
    after2 = _run(store.get(jid))
    assert int(after2["fencing_token"]) == int(after["fencing_token"])


def test_action_resume_retry_preserve_error(db):
    store = TaskJobStore(db)
    jid = _run(store.enqueue(owner="t", kind="secondary"))
    _run(store.finish(jid, status="failed",
                      reason_code="provider_unavailable",
                      error_code="timeout"))
    client = _client(db, admin=True)
    # resume failed → queued
    data = client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                       json={"action": "resume"}).json()
    assert data["changed"] is True and data["status"] == "queued"
    # снова в failed с ошибкой → retry сохраняет error_code (не затирает)
    _run(store.finish(jid, status="failed",
                      reason_code="provider_unavailable",
                      error_code="timeout"))
    data = client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                       json={"action": "retry"}).json()
    assert data["changed"] is True and data["status"] == "queued"
    row = _run(store.get(jid))
    assert row["error_code"] == "timeout"       # прошлая ошибка не затёрта
    assert int(row["next_retry_at"]) > 0


def test_action_invalid_states_and_validation(db):
    client = _client(db, admin=True)
    # 404
    resp = client.post("/api/oversight/jobs/no-such/action", headers=_hdr(),
                       json={"action": "cancel"})
    assert resp.status_code == 404
    # 422 неизвестное действие
    resp = client.post("/api/oversight/jobs/any/action", headers=_hdr(),
                       json={"action": "drop-table"})
    assert resp.status_code == 422
    # 409 completed
    store = TaskJobStore(db)
    jid = _run(store.enqueue(owner="t", kind="secondary"))
    _run(store.finish(jid, status="completed", reason_code=None))
    resp = client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                       json={"action": "cancel"})
    assert resp.status_code == 409


def test_action_supervisor_gate_off(db, monkeypatch):
    monkeypatch.setattr(mca_gates, "task_supervisor_enabled", lambda: False)
    client = _client(db, admin=True)
    resp = client.post("/api/oversight/jobs/whatever/action", headers=_hdr(),
                       json={"action": "cancel"})
    assert resp.status_code == 409


def test_action_audit_one_event_per_request(db, monkeypatch):
    """Мок-проверка контракта вызова (TH-8: одно событие на ЗАПРОС).

    Rework R1: мок больше НЕ единственное доказательство — ниже добавлен
    persistence-тест без мока (реальный emit → flush → SELECT)."""
    calls = []

    def _capture(*a, **kw):
        calls.append((a, kw))
        return {"ok": 1}

    monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
    store = TaskJobStore(db)
    jid = _run(store.enqueue(owner="t", kind="secondary"))
    client = _client(db, admin=True)
    client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                json={"action": "cancel"})
    client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                json={"action": "cancel"})
    assert len(calls) == 2        # TH-8: одно событие на ЗАПРОС
    args0, kw = calls[0]
    assert args0 and args0[0] == "OVERSIGHT_JOB_ACTION"
    assert kw.get("reason_code") == "oversight_job_action"
    assert kw.get("outcome") == "success"   # Rework R1: валидный исход
    usage = kw.get("usage_json")
    if isinstance(usage, str):
        usage = json.loads(usage)
    assert usage["action"] == "cancel"
    assert usage["actor"] == ADMIN_ID
    replay = calls[1][1].get("usage_json")
    if isinstance(replay, str):
        replay = json.loads(replay)
    assert replay["idempotent"] is True


def test_action_audit_persisted_real_emit(db, monkeypatch):
    """Rework R1 (T-5196 B-1): persistence-тест БЕЗ мока emit.

    RED-репро ревьюера: `_audit_job_action` слал `outcome="ok"`, которого
    нет в ALL_OUTCOMES → `build_event` возвращал None → ни лог-строки, ни
    записи в `mca_events` (мок-тест этого не видел). GREEN: `outcome=
    "success"` → событие реально пишется в хранилище: реальный emit →
    flush_events → SELECT. Проверяются: существование строки, outcome,
    reason, actor/деталь, а также что строка НЕ записывается при
    невалидном action-вызове (маркеры не размываются)."""
    store = TaskJobStore(db)
    jid = _run(store.enqueue(owner="t", kind="secondary"))
    client = _client(db, admin=True)
    resp = client.post(f"/api/oversight/jobs/{jid}/action", headers=_hdr(),
                       json={"action": "cancel"})
    assert resp.status_code == 200
    # буфер → хранилище (тот же путь, что фоновый flush-контур)
    _run(mca_events.flush_events(db))
    cur = _run(db.db.execute(
        "SELECT event_name, outcome, reason_code, component, operation_id, "
        "job_id, usage_json FROM mca_events WHERE event_name = "
        "'OVERSIGHT_JOB_ACTION'"))
    rows = [dict(r) for r in _run(cur.fetchall())]
    assert len(rows) == 1, f"ровно одно audit-событие, есть: {len(rows)}"
    row = rows[0]
    assert row["outcome"] == "success"        # ВАЛИДНЫЙ исход (не 'ok')
    assert row["reason_code"] == "oversight_job_action"
    assert row["component"] == "oversight_actions"
    assert row["job_id"] == jid
    usage = json.loads(row["usage_json"])
    assert usage["action"] == "cancel"
    assert usage["actor"] == ADMIN_ID
    assert usage["changed"] is True and usage["idempotent"] is False
    # отсутствие ложных срабатываний: событие ровно на запись (нет дублей
    # на чтение runs/funnel того же клиента)
    cur2 = _run(db.db.execute(
        "SELECT COUNT(*) c FROM mca_events WHERE event_name = "
        "'OVERSIGHT_JOB_ACTION'"))
    row2 = _run(cur2.fetchone())
    assert int(row2["c"]) == 1
