"""MOD-ACL-UX-01 M4B B2 — аддитивные read-only данные D1/D3.

D1 (approved): `/api/analytics/usage/latest` отдаёт nullable
`latency_ms`, `l1_failure_mode`, `l1_finish_reason` из существующей
колонки `llm_usage_events.plan_meta` (DDL 0, без второго endpoint/store).

D3 (approved): `/api/memory/intel-funnels` отдаёт `initiative.domains`
с серверным объяснением «0 активных намерений при N публикациях»:
это разные сущности (durable-снимок mca_intents vs события
initiative_sent), а не конверсия.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01 M4B B2 (D1/D3)
"""
import datetime
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from web.api import analytics as analytics_api
from web.api import memory_overview as mo


def _ts():
    return datetime.datetime(2026, 11, 20, 12, 0, 0)


class _AnalyticsConn:
    def __init__(self, *, latest=None, steps=None):
        self.latest = latest
        self.steps = steps or []

    async def fetchrow(self, sql, *args):
        if "ORDER BY ts DESC" in sql:
            return self.latest
        return None

    async def fetch(self, sql, *args):
        if "correlation_id = $1" in sql:
            return self.steps
        return []


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


def _request():
    cache = SimpleNamespace(pg=SimpleNamespace(pool=_Pool(_AnalyticsConn())))
    app = SimpleNamespace(state=SimpleNamespace(cache=cache))
    return SimpleNamespace(app=app)


def _latest_request(steps):
    conn = _AnalyticsConn(latest={"correlation_id": "cid", "ts": _ts()},
                          steps=steps)
    cache = SimpleNamespace(pg=SimpleNamespace(pool=_Pool(conn)))
    app = SimpleNamespace(state=SimpleNamespace(cache=cache))
    return SimpleNamespace(app=app)


def _base_step(**over):
    row = {
        "ts": _ts(), "module": "direct_chat", "step": "stage1",
        "tool_name": "", "source": "global", "model": "deepseek-v4",
        "input_tokens": 4000, "output_tokens": 600,
        "tokens_estimated": False, "cost_usd": Decimal("0.00174"),
        "price_known": True,
    }
    row.update(over)
    return row


@pytest.mark.asyncio
async def test_d1_latest_exposes_plan_meta_fields():
    steps = [_base_step(latency_ms="820.5", l1_failure_mode="timeout",
                        l1_finish_reason="length")]
    res = await analytics_api.usage_latest(
        _latest_request(steps), user=SimpleNamespace(id=1))
    row = res["steps"][0]
    assert row["latency_ms"] == pytest.approx(820.5)
    assert row["l1_failure_mode"] == "timeout"
    assert row["l1_finish_reason"] == "length"
    # Старые поля не сломаны.
    assert row["module"] == "direct_chat"
    assert row["cost_usd"] == pytest.approx(0.00174)


@pytest.mark.asyncio
async def test_d1_latest_is_nullable_for_rows_without_plan_meta():
    res = await analytics_api.usage_latest(
        _latest_request([_base_step()]), user=SimpleNamespace(id=1))
    row = res["steps"][0]
    assert row["latency_ms"] is None
    assert row["l1_failure_mode"] is None
    assert row["l1_finish_reason"] is None


@pytest.mark.asyncio
async def test_d1_latest_malformed_latency_is_null_not_zero():
    res = await analytics_api.usage_latest(
        _latest_request([_base_step(latency_ms="not-a-number")]),
        user=SimpleNamespace(id=1))
    assert res["steps"][0]["latency_ms"] is None, (
        "битое plan_meta.latency_ms не должно превращаться в 0")


@pytest.mark.asyncio
async def test_d1_empty_shape_unchanged():
    res = await analytics_api.usage_latest(
        _request(), user=SimpleNamespace(id=1))
    assert res["steps"] == []
    assert res["correlation_id"] == ""


# ── D3: серверное объяснение доменов ───────────────────────────────────────

class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class _Row:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeSqlConn:
    def __init__(self):
        self.task_jobs = []
        self.event_counts = []

    async def execute(self, sql, *args):
        sql_l = " ".join(str(sql).split())
        if "FROM task_jobs" in sql_l:
            params = args[0] if args and isinstance(args[0], tuple) else args
            kind = params[0] if params else None
            rows = [dict(r) for r in self.task_jobs
                    if kind is None or r.get("kind") == kind]
            return _Cursor(rows)
        if "FROM mca_events" in sql_l:
            return _Cursor([dict(r) for r in self.event_counts])
        if "FROM smart_messages" in sql_l:
            return _Row({"m": 0})
        if "FROM mca_lesson_applications" in sql_l:
            return _Row(None)
        return _Cursor([])


class _FakeDb:
    def __init__(self):
        self.db = _FakeSqlConn()


def _seed_zero_intents_two_publications(db: _FakeDb) -> None:
    """Durable: намерений создано 0; в окне — 2 публикации.

    Это ровно неудобный сценарий MAC-S15-02: 0 намерений при N публикациях.
    """
    db.db.task_jobs = [{
        "kind": "initiative.observe",
        "status": "completed", "reason_code": None,
        "payload": json.dumps({
            "counters": {"observed": 420, "eligible": 25,
                         "opportunities": 4, "intents_created": 0,
                         "silent_decisions": 2, "react_decisions": 2,
                         "sent": 2, "writer_unavailable": 0, "errors": 0},
        }),
        "created_at": 1791800000, "updated_at": 1791890000,
        "finished_at": 1791890000,
    }]
    db.db.event_counts = [
        {"event_name": "initiative_observer_scan", "c": 260},
        {"event_name": "initiative_sent", "c": 2},
    ]


@pytest.mark.asyncio
async def test_d3_domains_explain_zero_intents_with_publications(monkeypatch):
    db = _FakeDb()
    _seed_zero_intents_two_publications(db)
    mo._funnels_cache.clear()
    monkeypatch.setattr(mo, "_require_global_admin", lambda request, user: None)
    monkeypatch.setattr(mo, "_db_or_503", lambda: db)

    body = await mo.memory_intel_funnels(
        SimpleNamespace(), SimpleNamespace(id=1), chat_id=-100)
    ini = body["initiative"]
    assert ini["job"]["counters"]["intents_created"] == 0
    domains = ini["domains"]
    assert domains["intents"]["created_total"] == 0
    assert domains["publications"]["events_24h"] == 2
    assert domains["same_cohort"] is False
    explain = domains["explain"]
    assert "эфемерн" in explain, (
        "объяснение должно называть эфемерный повод, не создающий намерение")
    assert "не конверсия" in explain, (
        "объяснение прямо запрещает трактовать числа как конверсию")
    mo._funnels_cache.clear()
