"""MCA-23 фаза 2 (P2-B) — ExecutionGraph planned-vs-actual + «Ответ
(Pipeline)» агрегаты (§33-§36 current_task).

Покрытие:
  * planned-слой: ``record_response_plan`` → ``set_planned`` → ``get_planned``
    (in-memory, Δ DDL=0, без второй telemetry-модели);
  * §34: цепочка TRIGGER → PLANNER → TOOLS → WRITER → DELIVERY → ИТОГ;
    REACT/SILENT — фиктивный Writer/tools/delivery НЕ планируются;
  * §33: сравнение planned-vs-actual — совпало / отклонилось / не
    выполнилось / лишнее; ЧЕСТНОСТЬ: нет факта → строки сравнения нет
    (никаких фиктивных «missing»/«match»);
  * ``build_graph``: аддитивное поле ``planned`` (нет плана → ``None``);
  * planned переживает перезапись снапшота ``record_run`` (merge-семантика);
  * R17: planned-узлы — только enum/коды/шаблоны причин;
  * endpoints: ``/api/analytics/execution/latest`` отдаёт ``planned``;
    ``/api/analytics/response/summary`` (24h/7d) — агрегаты из СУЩЕСТВУЮЩИХ
    событий, честный fail-open (нет данных → available=False, «—»);
  * routes.py не менялся (byte-freeze f25e759e…; аддитивный endpoint — в
    analytics.py, регистрация в web/app.py).

Автор: @Builder (MCA-23 P2-B).
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import execution_graph_source as egs
from services import response_extent as ext

_ROOT = Path(__file__).resolve().parent.parent
_ROUTES = (_ROOT / "web" / "api" / "routes.py").read_bytes()
_ANALYTICS = (_ROOT / "web" / "api" / "analytics.py").read_text(
    encoding="utf-8")

ROUTES_SHA256_F11 = (
    "f25e759efeb610c5b28fe91a691eb8011eb9defda6042b0480687468b8353a98")


@pytest.fixture(autouse=True)
def _clean_store():
    egs.reset()
    yield
    egs.reset()


# ── §33: planned-слой ────────────────────────────────────────────────────────

class TestPlannedLayer:
    def test_fanfic_plan_axes(self):
        plan = ext.classify_request("бот, напиши фанфик про космос")
        assert plan.task_kind == "creative_writing"
        egs.record_response_plan("run-b", plan=plan, action="reply")
        planned = egs.get_planned("run-b")
        assert planned is not None
        keys = [n["key"] for n in planned["nodes"]]
        assert keys == ["trigger", "planner", "tools", "writer",
                        "delivery", "outcome"]
        planner = planned["nodes"][1]
        assert planner["axes"]["task_kind"] == "creative_writing"
        assert planner["axes"]["extent"] == "longform"
        assert planner["axes"]["structure"] == "story"
        # §36: человекочитаемая причина — шаблон, без сырого текста юзера.
        assert planner["reason_ru"]
        assert "космос" not in json.dumps(planned, ensure_ascii=False)

    def test_react_silent_no_fictive_writer(self):
        # §34: REACT/SILENT не рисуют фиктивный Writer; tools/delivery — none.
        egs.record_response_plan("run-j", plan=ext.ResponsePlan(),
                                 action="react")
        keys = [n["key"] for n in egs.get_planned("run-j")["nodes"]]
        assert "writer" not in keys
        tools = next(n for n in egs.get_planned("run-j")["nodes"]
                     if n["key"] == "tools")
        assert tools["axes"]["tool_policy"] == "none"
        delivery = next(n for n in egs.get_planned("run-j")["nodes"]
                        if n["key"] == "delivery")
        assert delivery["axes"]["delivery_hint"] == "none"

    def test_set_planned_fail_open(self):
        # Мусор/пустота не бросают и не пишут.
        egs.set_planned("", [{"key": "planner"}])
        assert egs.get_planned("x") is None
        egs.set_planned("run-x", [])
        assert egs.get_planned("run-x") is None
        egs.set_planned("run-x", ["garbage", None, {"key": "planner",
                                                    "prompt": "secret"}])
        planned = egs.get_planned("run-x")
        assert [n["key"] for n in planned["nodes"]] == ["planner"]
        # R17: неизвестные поля отброшены.
        assert "prompt" not in planned["nodes"][0]

    def test_set_planned_bounded(self):
        nodes = [{"key": "k%d" % i} for i in range(20)]
        egs.set_planned("run-max", nodes)
        assert len(egs.get_planned("run-max")["nodes"]) <= 8

    def test_planned_survives_record_run_overwrite(self):
        egs.record_response_plan("run-k", plan=ext.ResponsePlan(),
                                 action="reply")
        egs.record_run(run_id="run-k", status="ok")
        assert egs.get_planned("run-k") is not None
        # …и агентные события не теряются от put_planned.
        egs.record_agentic_event("DECISION_COMPLETE", run_id="run-k",
                                 action="reply")
        snap = egs.get_run("run-k")
        assert snap["planned"]["nodes"]
        assert any(e["event"] == "DECISION_COMPLETE"
                   for e in snap["agentic_events"])


# ── §33: planned-vs-actual ───────────────────────────────────────────────────

def _run_graph(run_id, plan, action, *, events=(), llm_rows=(),
               snapshot_patch=None):
    egs.record_response_plan(run_id, plan=plan, action=action)
    for name, fields in events:
        egs.record_agentic_event(name, run_id=run_id, **fields)
    snapshot = egs.get_run(run_id) or {}
    if snapshot_patch:
        snapshot.update(snapshot_patch)
    return egs.build_graph(run_id, snapshot, list(llm_rows))


class TestPlannedVsActual:
    def test_match_full_reply(self):
        plan = ext.classify_request("бот, напиши фанфик")
        graph = _run_graph(
            "r1", plan, "reply",
            events=[("DECISION_COMPLETE", {"action": "reply",
                                           "duration_ms": 100})],
            llm_rows=[{"step": "stage1", "input_tokens": 1,
                       "output_tokens": 2, "price_known": True,
                       "cost_usd": 0.0, "model": "m", "ts": "t"}])
        cmp_rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert cmp_rows["trigger"]["status"] == "match"
        assert cmp_rows["writer"]["status"] == "match"
        summary = graph["planned"]["summary"]
        assert summary["match"] >= 3
        assert summary["deviated"] == summary["missing"] == \
            summary["extra"] == 0

    def test_delivery_fallback_rich_to_text_is_deviated(self):
        plan = ext.classify_request(
            "бот, сделай глубокий анализ и собери данные")
        assert plan.delivery_hint == "rich"
        graph = _run_graph(
            "r2", plan, "reply",
            events=[("DECISION_COMPLETE", {"action": "reply"}),
                    ("TOOL_CALL_COMPLETE", {"tool": "fetch_article"}),
                    ("TOOL_CALL_FAILED", {"tool": "web_search"})],
            llm_rows=[{"step": "stage1", "input_tokens": 1,
                       "output_tokens": 2, "price_known": True,
                       "cost_usd": 0.0, "model": "m", "ts": "t"}],
            snapshot_patch={"publish_status": "ok",
                            "publish_channel": "text"})
        rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert rows["delivery"]["status"] == "deviated"
        assert rows["delivery"]["actual"] == "обычное сообщение"
        # Что упало: tool-фейл виден.
        assert "упало: 1" in rows["tools"]["actual"]
        assert graph["planned"]["summary"]["deviated"] >= 1

    def test_missing_writer_when_no_generation(self):
        plan = ext.ResponsePlan(task_kind="explanation", extent="detailed",
                                structure="explanation")
        graph = _run_graph(
            "r3", plan, "reply",
            events=[("DECISION_COMPLETE", {"action": "reply"})])
        rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert rows["writer"]["status"] == "missing"
        assert rows["writer"]["reason_ru"]

    def test_extra_tools_when_policy_none(self):
        plan = ext.classify_request("бот, напиши рассказ")
        assert plan.tool_policy == "none"
        graph = _run_graph(
            "r4", plan, "reply",
            events=[("DECISION_COMPLETE", {"action": "reply"}),
                    ("TOOL_CALL_COMPLETE", {"tool": "web_search"})],
            llm_rows=[{"step": "single", "input_tokens": 1,
                       "output_tokens": 2, "price_known": True,
                       "cost_usd": 0.0, "model": "m", "ts": "t"}])
        rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert rows["tools"]["status"] == "extra"

    def test_required_tools_missing(self):
        plan = ext.ResponsePlan(task_kind="research", extent="detailed",
                                structure="report", tool_policy="required")
        graph = _run_graph(
            "r5", plan, "tool",
            events=[("DECISION_COMPLETE", {"action": "tool"})])
        rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert rows["tools"]["status"] == "missing"

    def test_extra_writer_when_react(self):
        # §34/§46: REACT не планировал Writer; фактическая генерация — лишнее.
        egs.record_response_plan("r6", plan=ext.ResponsePlan(),
                                 action="react")
        egs.record_agentic_event("DECISION_COMPLETE", run_id="r6",
                                 action="react")
        graph = egs.build_graph("r6", egs.get_run("r6"), [
            {"step": "single", "input_tokens": 1, "output_tokens": 2,
             "price_known": True, "cost_usd": 0.0, "model": "m", "ts": "t"}])
        rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert rows["writer"]["status"] == "extra"

    def test_honest_no_fact_no_row(self):
        # Нет фактов доставки/итога (Direct-прогон без publish-полей) →
        # строк delivery/outcome НЕТ; никаких фиктивных «match»/«missing».
        plan = ext.ResponsePlan()
        graph = _run_graph(
            "r7", plan, "reply",
            events=[("DECISION_COMPLETE", {"action": "reply"})],
            llm_rows=[{"step": "stage1", "input_tokens": 1,
                       "output_tokens": 2, "price_known": True,
                       "cost_usd": 0.0, "model": "m", "ts": "t"}])
        keys = {r["key"] for r in graph["planned"]["comparison"]}
        assert "delivery" not in keys
        assert "outcome" not in keys

    def test_trigger_deviated(self):
        egs.record_response_plan("r8", plan=ext.ResponsePlan(),
                                 action="reply")
        egs.record_agentic_event("DECISION_COMPLETE", run_id="r8",
                                 action="react")
        graph = egs.build_graph("r8", egs.get_run("r8"), [])
        rows = {r["key"]: r for r in graph["planned"]["comparison"]}
        assert rows["trigger"]["status"] == "deviated"
        assert "реакция" in rows["trigger"]["actual"]

    def test_no_plan_planned_is_none(self):
        # Плана нет → честный None (не пустая фикция).
        egs.record_agentic_event("DECISION_COMPLETE", run_id="r9",
                                 action="reply")
        graph = egs.build_graph("r9", egs.get_run("r9"), [])
        assert graph["planned"] is None


# ── §35: свежее in-memory окно (существующие снапшоты) ──────────────────────

class TestRecentWindow:
    def test_aggregates_real_runs(self):
        egs.record_response_plan("w1", plan=ext.classify_request(
            "бот, напиши фанфик"), action="reply")
        egs.record_agentic_event("DECISION_COMPLETE", run_id="w1",
                                 action="reply", duration_ms=100)
        egs.record_response_plan("w2", plan=ext.ResponsePlan(),
                                 action="react")
        egs.record_agentic_event("DECISION_COMPLETE", run_id="w2",
                                 action="react", duration_ms=300)
        egs.record_agentic_event("TOOL_CALL_FAILED", run_id="w1",
                                 tool="web_search")
        window = egs.response_recent_window()
        assert window["runs"] == 2
        assert window["actions"] == {"reply": 1, "react": 1}
        assert window["task_kinds"] == {"creative_writing": 1,
                                        "social_chat": 1}
        assert window["extents"] == {"longform": 1, "compact": 1}
        assert window["tool_calls"] == 1
        assert window["tool_failures"] == 1
        assert window["tool_failure_rate"] == 1.0
        assert window["decision_latency_ms"]["p50"] == 200.0

    def test_empty_window_honest(self):
        window = egs.response_recent_window()
        assert window["runs"] == 0
        assert window["tool_failure_rate"] is None
        assert window["decision_latency_ms"]["p50"] is None


# ── endpoints (RBAC + форма) ────────────────────────────────────────────────

TEST_TOKEN = "123456:TEST_TOKEN_MCA23"
ADMIN_ID = 5885953495
USER_NO_ROLE = 999999999


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(),
                         hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) \
        + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


def _roles():
    return [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False, "role_type": "global_admin"},
        {"role_name": "user", "permissions": {}, "is_custom": False,
         "role_type": "user"},
    ]


def _admins():
    return [{"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-09-07T00:00:00+00:00"}]


class _FakeConn:
    def __init__(self, runs_rows=None):
        self.runs_rows = runs_rows or []

    async def execute(self, sql, *args):
        return "OK"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return list(_roles())
        if "FROM bot_admins" in sql:
            return list(_admins())
        if "GROUP BY correlation_id" in sql:
            return list(self.runs_rows)
        # /analytics/response/summary: пустое окно → honest empty.
        return []

    class _CM:
        async def __aenter__(self):
            return conn_holder["conn"]

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return _FakeConn._CM()


conn_holder = {"conn": None}


class _FakePool:
    def __init__(self, conn=None):
        self._conn = conn

    def acquire(self):
        return _FakeConn._CM()


class _FakePg:
    def __init__(self, runs_rows=None):
        self.pool = _FakePool(runs_rows)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    from services.config_cache import ConfigCache
    from web.app import create_app
    from web.api import deps as deps_mod
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn()
    conn_holder["conn"] = conn
    cache = ConfigCache(pg=_FakePg(), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        yield tc
    egs.reset()


@pytest.fixture
def client_with_runs(monkeypatch):
    """PG-заглушка с реальными строками прогонов (module='direct_chat')."""
    from decimal import Decimal

    from services.config_cache import ConfigCache
    from web.app import create_app
    from web.api import deps as deps_mod
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    rows = [
        {"correlation_id": "c1", "calls": 2,
         "input_tokens": 1000, "output_tokens": 500,
         "cost_known": Decimal("0.001"), "price_known": True,
         "tool_calls": 2, "span_ms": 1200.0,
         "first_ts": "2026-10-08T10:00:00+00:00"},
        {"correlation_id": "c2", "calls": 1,
         "input_tokens": 200, "output_tokens": 50,
         "cost_known": None, "price_known": False,
         "tool_calls": 0, "span_ms": 0.0,
         "first_ts": "2026-10-08T09:00:00+00:00"},
    ]
    conn_holder["conn"] = _FakeConn(runs_rows=rows)
    cache = ConfigCache(pg=_FakePg(runs_rows=rows), retry_attempts=1,
                        retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        yield tc
    egs.reset()


class TestResponseEndpoints:
    def test_routes_pin_untouched(self):
        # routes.py byte-freeze: аддитивный endpoint живёт в analytics.py.
        assert hashlib.sha256(_ROUTES).hexdigest() == ROUTES_SHA256_F11
        assert "/analytics/response/summary" in _ANALYTICS

    def test_execution_latest_planned_roundtrip(self, client):
        plan = ext.classify_request("бот, напиши фанфик")
        egs.record_response_plan("cid-mca23", plan=plan, action="reply")
        egs.record_agentic_event("DECISION_COMPLETE", run_id="cid-mca23",
                                 action="reply")
        resp = client.get("/api/analytics/execution/latest?run_id=cid-mca23",
                          headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        planned = body["planned"]
        assert planned is not None
        assert [n["key"] for n in planned["nodes"]] == [
            "trigger", "planner", "tools", "writer", "delivery", "outcome"]
        assert planned["summary"]["match"] >= 1
        # R17: без сырых текстов.
        assert "фанфик" not in json.dumps(planned, ensure_ascii=False)

    def test_execution_latest_no_plan_honest_none(self, client):
        egs.record_agentic_event("DECISION_COMPLETE", run_id="cid-noplan",
                                 action="reply")
        resp = client.get("/api/analytics/execution/latest?run_id=cid-noplan",
                          headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["planned"] is None

    def test_response_summary_401_403(self, client):
        assert client.get(
            "/api/analytics/response/summary").status_code == 401
        assert client.get(
            "/api/analytics/response/summary",
            headers=_hdr(USER_NO_ROLE)).status_code == 403

    def test_response_summary_empty_honest(self, client):
        resp = client.get("/api/analytics/response/summary?period=24h",
                          headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert body["runs"] == 0
        # §14 ASAP 6 / §35: нет данных → честный None, не выдуманные %.
        assert body["tool_failure_rate"] is None
        assert body["plan_axes"] is None
        assert body["latency"]["p50_ms"] is None
        assert body["note_ru"]
        assert body["recent"]["runs"] == 0

    def test_response_summary_period_whitelist(self, client):
        resp = client.get("/api/analytics/response/summary?period=bogus",
                          headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["period"] == "24h"
        resp = client.get("/api/analytics/response/summary?period=7d",
                          headers=_hdr())
        assert resp.json()["period"] == "7d"
        assert resp.json()["days"] == 7

    def test_response_summary_aggregates_from_existing_events(
            self, client_with_runs):
        # §35: агрегаты считаются ТОЛЬКО из существующих llm_usage_events
        # (module='direct_chat'); оси плана за период — честный None.
        resp = client_with_runs.get(
            "/api/analytics/response/summary?period=24h", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["runs"] == 2
        assert body["calls"] == 3
        # tools/run = (2+0)/2; multi-tool rate = 1/2 (c1 имеет 2 tool-вызова).
        assert body["tools_per_run"] == 1.0
        assert body["multi_tool_rate"] == 0.5
        # Ошибки tool-вызовов в usage events не пишутся → честный None.
        assert body["tool_failure_rate"] is None
        # Cost: только price_known-строки; c2 неизвестна → cost_known False.
        assert body["price_known"] is False
        assert body["cost_usd"] is None
        # Latency по span'у LLM-вызовов (ненулевые span'ы: только 1200).
        assert body["latency"]["p50_ms"] == 1200.0
        assert body["latency"]["p95_ms"] == 1200.0
        # Свежее in-memory окно рядом (пустое в тестовом процессе).
        assert body["recent"]["runs"] == 0
        assert body["note_ru"]


# ── интеграционная точка ────────────────────────────────────────────────────

class TestIntegrationPoint:
    def test_direct_chat_single_guarded_hook(self):
        # Единственная guarded точка в direct_chat_service: import fail-open
        # + record_response_plan. Больше вызовов execution_graph_source там
        # нет.
        src = (_ROOT / "services" / "direct_chat_service.py").read_text(
            encoding="utf-8")
        assert src.count("record_response_plan") == 1
        assert "from services import execution_graph_source as _egs" in src
        # Guard: try/except вокруг вызова.
        hook = src[src.index("record_response_plan") - 400:
                   src.index("record_response_plan") + 200]
        assert "except Exception" in hook
