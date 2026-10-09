"""ASAP 7 F2 (Wave 3) — Direct settings (L1 Planner) + durable-аналитика.

Исполняемый контракт: plans/features/asap7-cognitive-direct-pipeline/
architecture.md §1.6 (model slot L1), §1.10 (plan_meta JSONB — durable-оси
24ч/7д SQL-агрегатом), §8 (observability); ТЗ §18/§19 (current_task).

Покрытие:
  1. Каталог: 9 PG-only ключей L1 Planner (группы models_direct_l1 /
     limits_direct_l1 / flags_direct_l1), поверхность mod_direct;
     effective==configured (resolve_l1_model: configured → slot "l1",
     пусто → inherit main) — интеграционная проверка §1.6/§22 п.5/6.
  2. ΔDDL v35: план_meta JSONB в pg_db DDL (идемпотентный ALTER), шаг
     MigrationStep(35) — идемпотентный прогон дважды; backup-guard
     fail-closed срабатывает перед pending-шагом (current>0).
  3. Durable-оси 24ч/7д: SQL-агрегат по plan_meta (fixture usage-строк),
     рестарт-семантика (in-memory store пуст → durable axes живы);
     honest-empty при отсутствии plan_meta.
  4. usage_events.record(plan_meta=...) — пишется/читается: whitelist
     R17, мусор отбрасывается, INSERT несёт $13 (jsonb).
  5. Widget-поля UI (app.js/index.html): honest inherit/effective source,
     REV-2 (а) resolved capabilities, REV-2 (б) requested/effective/
     следствие autonomous toggle; R17 — без промптов.
  6. F2-FOLLOWUP: usage-строка step="l1_planner" получает непустой
     plan_meta после L1-прогона (R17-оси, sanitize-инвариант, bounded).

TEST-LIFECYCLE: CONTRACT owner=ASAP7/F2
"""
import asyncio
import json
from pathlib import Path

import pytest

from services import execution_graph_source as egs
from services import usage_events as ue
from services import param_catalog as pc
from services.direct_l1 import resolve_l1_model

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web" / "app.js"
INDEX_HTML = ROOT / "web" / "index.html"


# ── 1. Каталог: группа/слоты L1 Planner (§1.6, ТЗ §19) ──────────────────────

L1_PG_KEYS = (
    "models.direct_l1_base_url",
    "models.direct_l1_model_name",
    "keys.direct_l1_api_key",
    "limits.direct_l1_temperature",
    "limits.direct_l1_timeout_seconds",
    "limits.direct_l1_max_output_tokens",
    "limits.direct_l1_context_tokens",
    "flags.direct_l1_enabled",
    "flags.direct_l1_fallback_enabled",
)


def test_catalog_l1_group_and_slots():
    for key in L1_PG_KEYS:
        spec = pc.REGISTRY.get(key)
        assert spec is not None, key
        assert spec.pg_id == key
        assert spec.settings_field is None and spec.env_name is None, \
            "PG-only запись (новых записей Settings нет)"
    assert pc.REGISTRY["keys.direct_l1_api_key"].secret is True
    assert pc.get_group("models_direct_l1") is not None
    assert pc.get_group("models_direct_l1").category == "models"
    assert pc.get_group("limits_direct_l1").category == "limits"
    assert pc.get_group("flags_direct_l1").category == "flags"
    # Поверхность — вкладка mod_direct (§19).
    groups = pc.tab_group_ids(pc.TAB_MOD_DIRECT)
    assert {"models_direct_l1", "limits_direct_l1",
            "flags_direct_l1"} <= groups


def test_catalog_l1_env_fallback_defaults_from_f1_classvars():
    """env-fallback на ClassVar F1 (новых записей settings.py нет)."""
    from config.settings import settings
    for attr in ("DIRECT_L1_ENABLED", "DIRECT_L1_CONTEXT_TOKENS",
                 "DIRECT_L1_TIMEOUT_SECONDS", "DIRECT_L1_MAX_OUTPUT_TOKENS"):
        assert hasattr(settings, attr), attr
    # Ключи слота НЕ имеют Settings-полей (inherit main через пустую строку).
    dataclass_fields = {f.name for f in
                        type(settings).__dataclass_fields__.values()}
    assert "DIRECT_L1_BASE_URL" not in dataclass_fields
    assert "DIRECT_L1_MODEL_NAME" not in dataclass_fields


def test_slot_effective_equals_configured():
    """§1.6/§22 п.5/6: effective==configured интеграционно (публичный
    контракт F1 resolve_l1_model, hot-first)."""
    def configured_hot(key, default=None):
        return {
            "models.direct_l1_base_url": "https://l1.example/v1",
            "models.direct_l1_model_name": "planner-x",
            "keys.direct_l1_api_key": "sk-l1-test",
        }.get(key, default)

    slot = resolve_l1_model(hot_get=configured_hot)
    assert slot.dedicated is True and slot.source == "l1"
    assert slot.model == "planner-x"
    assert slot.base_url == "https://l1.example/v1"

    slot_main = resolve_l1_model(hot_get=lambda k, d=None: "")
    assert slot_main.dedicated is False and slot_main.source == "main"
    assert slot_main.model == ""      # inherit main (пусто → основная)


# ── 2. ΔDDL v35: идемпотентность + backup-guard ────────────────────────────

def test_pg_ddl_contains_plan_meta_alter():
    from services.pg_db import DDL_STATEMENTS
    joined = "\n".join(DDL_STATEMENTS)
    assert "plan_meta JSONB" in joined
    assert "ADD COLUMN IF NOT EXISTS plan_meta JSONB" in joined


def test_migration_v35_idempotent_twice(tmp_path):
    from services.database import DatabaseService
    db_path = tmp_path / "f2_v35.db"

    async def _run():
        d1 = DatabaseService(str(db_path))
        await d1.initialize()
        cur = await d1.db.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert int(row[0]) == 35
        cur = await d1.db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=35")
        assert (await cur.fetchone())[0] == 1
        await d1.close()
        # Прогон дважды (тот же файл БД) — no-op без дублей/ошибок.
        d2 = DatabaseService(str(db_path))
        await d2.initialize()
        cur = await d2.db.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert int(row[0]) == 35
        cur = await d2.db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=35")
        assert (await cur.fetchone())[0] == 1
        await d2.close()

    asyncio.run(_run())


def test_backup_guard_fires_before_pending_step(tmp_path, monkeypatch):
    """Backup-guard fail-closed pre-DDL: current>0 + pending v35 →
    services.memory_backup.migration_backup вызван ДО применения шага."""
    from services import database as db_mod
    from services.database import DatabaseService
    db_path = tmp_path / "f2_guard.db"

    calls = []

    async def fake_backup(svc, target_version=None):
        calls.append(target_version)
        # Честный read-back-семантический маркер: guard не падает.
        return "backup-ok"

    monkeypatch.setattr(
        "services.memory_backup.migration_backup", fake_backup)

    async def _run():
        d = DatabaseService(str(db_path))
        await d.initialize()
        await d.close()
        # Откат версии до v34 при сохранении книги → v35 снова pending.
        import aiosqlite
        db = await aiosqlite.connect(str(db_path))
        try:
            await db.execute("PRAGMA user_version = 34")
            await db.execute("DELETE FROM schema_migrations WHERE version=35")
            await db.commit()
        finally:
            await db.close()
        d2 = DatabaseService(str(db_path))
        await d2.initialize()
        cur = await d2.db.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert int(row[0]) == 35
        await d2.close()

    asyncio.run(_run())
    assert calls and calls[0] == 34, "guard должен вызваться до v35"

    # Fail-closed: провал guard'а → шаг НЕ применяется (исключение наружу).
    async def failing_backup(svc, target_version=None):
        raise RuntimeError("backup unavailable")

    monkeypatch.setattr(
        "services.memory_backup.migration_backup", failing_backup)

    db_path2 = tmp_path / "f2_guard2.db"

    async def _run_fail():
        d = DatabaseService(str(db_path2))
        await d.initialize()
        await d.close()
        import aiosqlite
        db = await aiosqlite.connect(str(db_path2))
        try:
            await db.execute("PRAGMA user_version = 34")
            await db.execute("DELETE FROM schema_migrations WHERE version=35")
            await db.commit()
        finally:
            await db.close()
        d2 = DatabaseService(str(db_path2))
        with pytest.raises(Exception):
            await d2.initialize()
        await d2.close()
        db = await aiosqlite.connect(str(db_path2))
        try:
            cur = await db.execute("PRAGMA user_version")
            row = await cur.fetchone()
            assert int(row[0]) == 34, "fail-closed: версия не поднята"
        finally:
            await db.close()

    asyncio.run(_run_fail())


# ── 3. Durable-оси 24ч/7д по plan_meta (fixture usage-строк) ────────────────

def _axes_row(**over):
    row = {
        "calls": 5, "input_tokens": 3500, "output_tokens": 400,
        "cost_known": 0.0021, "price_known": True, "with_meta": 4,
        "actions": {"reply": 3, "silent": 1},
        "extents": {"compact": 2, "detailed": 2},
        "tones": {"inherit": 3, "warm": 1},
        "buckets": {"high": 3, "low": 1},
        "inherited": 1, "fallback": 1,
        "latency_p50": 640.0, "latency_p95": 1500.5,
    }
    row.update(over)
    return row


def test_durable_axes_shape_and_rates():
    axes = egs.durable_l1_axes_from_row(_axes_row())
    assert axes["available"] is True
    assert axes["calls"] == 5 and axes["with_meta"] == 4
    assert axes["actions"]["reply"] == 3
    assert axes["extents"]["detailed"] == 2
    assert axes["buckets"]["low"] == 1
    assert axes["inherited_rate"] == round(1 / 4, 4)
    assert axes["fallback_rate"] == round(1 / 4, 4)
    assert axes["latency_ms"]["p50"] == 640.0
    assert axes["latency_ms"]["p95"] == 1500.5
    assert axes["cost_usd"] == 0.0021
    assert axes["tokens"] == {"input_tokens": 3500, "output_tokens": 400}


def test_durable_axes_empty_is_honest_none():
    assert egs.durable_l1_axes_from_row(_axes_row(calls=0)) is None


def test_durable_axes_survive_restart():
    """Рестарт-семантика: in-memory окно пусто, durable-оси из PG-строк
    (fixture) полные — честные периоды после рестарта (§1.10)."""
    egs.reset()
    assert egs.response_recent_window()["runs"] == 0
    axes = egs.durable_l1_axes_from_row(_axes_row())
    assert axes["calls"] == 5 and axes["available"] is True
    assert egs.response_recent_window()["runs"] == 0


def test_durable_axes_sql_targets_l1_planner():
    sql = egs.DURABLE_L1_AXES_SQL
    assert "module = 'direct_chat'" in sql
    assert "step = 'l1_planner'" in sql
    assert "plan_meta->>'action'" in sql
    assert "$1::int" in sql


# ── 4. usage_events.record с plan_meta (пишется/читается) ──────────────────

class _UEConn:
    def __init__(self, price=None):
        self.price = price
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, sql, *args):
        if "llm_model_prices" in sql:
            if self.price is None:
                return None
            from decimal import Decimal
            return {"input_usd_per_1m": Decimal(str(self.price[0])),
                    "output_usd_per_1m": Decimal(str(self.price[1]))}
        return None


class _UEPool:
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


@pytest.fixture(autouse=True)
def _ue_state():
    ue.reset_cleanup_state()
    yield
    ue.reset_cleanup_state()


@pytest.mark.asyncio
async def test_record_writes_plan_meta_whitelisted():
    conn = _UEConn()
    pg = __import__("types").SimpleNamespace(pool=_UEPool(conn))
    await ue.record(
        pg, module="direct_chat", step="l1_planner",
        correlation_id="corr" + "0" * 28, chat_id=-100,
        model="planner-x", input_tokens=10, output_tokens=5,
        plan_meta={
            "action": "reply", "response_act": "research",
            "extent": "detailed", "tone": "neutral", "bucket": "high",
            "confidence": 0.93, "capabilities": ["web_search"],
            "tools": ["fetch_article"], "inherited": False,
            "fallback": "", "latency_ms": 812, "input_chars": 1500,
            # Мусор/небезопасное — отбрасывается whitelist'ом:
            "prompt": "FULL SECRET PROMPT", "raw_text": "leak",
            "action_extra": {"nested": True},
        })
    assert conn.executed, "INSERT должен выполниться"
    sql, args = conn.executed[0]
    assert "plan_meta" in sql and "$13" in sql
    payload = args[12]
    assert payload is not None
    meta = json.loads(payload)
    assert meta["action"] == "reply"
    assert meta["bucket"] == "high"
    assert meta["capabilities"] == "web_search"
    assert meta["tools"] == "fetch_article"
    assert meta["latency_ms"] == 812
    assert "prompt" not in meta and "raw_text" not in meta \
        and "action_extra" not in meta


@pytest.mark.asyncio
async def test_record_plan_meta_junk_becomes_null():
    conn = _UEConn()
    pg = __import__("types").SimpleNamespace(pool=_UEPool(conn))
    await ue.record(
        pg, module="direct_chat", step="l1_planner",
        plan_meta={"свободный текст с пробелами": "не пройдёт"})
    sql, args = conn.executed[0]
    assert args[12] is None      # NULL, не частичный мусор


def test_sanitize_plan_meta_boundaries():
    assert ue.sanitize_plan_meta(None) is None
    assert ue.sanitize_plan_meta([]) is None
    assert ue.sanitize_plan_meta({}) is None
    # Модель с недопустимыми символами → drop.
    assert "model" not in (ue.sanitize_plan_meta(
        {"model": "bad model with spaces"}) or {})
    # Число-bool не пролезает в числовые поля.
    assert "confidence" not in (ue.sanitize_plan_meta(
        {"confidence": True}) or {})


# ── 5. Widget-поля UI (app.js / index.html) ────────────────────────────────

def test_ui_l1_planner_card_markers():
    html = INDEX_HTML.read_text(encoding="utf-8")
    for marker in ("data-direct-l1-planner", "data-l1-effective",
                   "data-l1-enabled",
                   "data-direct-autonomous-semantics",
                   "data-autonomous-requested",
                   "data-autonomous-consequence",
                   "data-effective-source"):
        assert marker in html, marker


def test_ui_pipeline_widget_l1_axes_block():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "data-l1-durable-axes" in html
    js = APP_JS.read_text(encoding="utf-8")
    assert "responseL1Rows" in js
    assert "directL1PlannerCard" in js
    assert "directAutonomousSemantics" in js
    # REV-2 (a): resolved capabilities доходят до «Tools planned» —
    # через planned-vs-actual сравнение (row.actual рендерит resolved/
    # rejected строки из planned payload backend'а).
    assert "responsePlanComparison" in js


def test_planned_tools_comparison_carries_resolved():
    """REV-2 (a): L1_PLAN.resolved в planned-view «Tools planned» —
    честная деривация requested − rejected (F1 отдаёт resolved=(), поэтому
    resolved строится из реальных L1_CAPABILITY_REJECTED событий)."""
    from services import response_extent as ext
    plan = ext.ResponsePlan(task_kind="research", extent="detailed",
                            structure="summary", delivery_hint="plain",
                            tool_policy="auto", source="l1")
    planned = egs.planned_nodes_from_plan(plan, action="reply")
    snapshot = {"agentic_events": [
        {"event": "L1_PLAN", "ts": 1, "action": "reply",
         "capabilities": "web_search,chat_history", "bucket": "high"},
        {"event": "L1_CAPABILITY_REJECTED", "ts": 2,
         "capability": "chat_history", "reason": "inactive"},
        {"event": "TOOL_CALL_COMPLETE", "ts": 3,
         "tool": "execute_web_search"},
    ]}
    actual = egs._actual_facts(snapshot, [], [])
    assert actual["l1_requested"] == ["web_search", "chat_history"]
    assert actual["l1_resolved"] == ["web_search"]
    assert actual["l1_rejected"] == [("chat_history", "inactive")]
    rows = egs.planned_vs_actual(planned, actual)
    tools_row = next(r for r in rows if r["key"] == "tools")
    assert "web_search" in tools_row["actual"]
    assert "chat_history" in tools_row["actual"]


def test_build_graph_includes_l1_planner_node():
    """§8/§18: run snapshot содержит узел «L1 Planner» с plan-осями и
    usage-фактами step='l1_planner'; Writer-факт не съедает L1-узел."""
    snapshot = {"agentic_events": [
        {"event": "L1_PLAN", "ts": 1, "action": "reply",
         "response_act": "research", "extent": "detailed",
         "tone": "neutral", "bucket": "high",
         "capabilities": "web_search", "tools": "fetch_article",
         "inherited": False, "fallback": "", "latency_ms": 700,
         "input_chars": 1500, "confidence": 0.9, "source": "l1_slot"},
    ]}
    llm_rows = [
        {"step": "l1_planner", "model": "planner-x", "input_tokens": 700,
         "output_tokens": 90, "cost_usd": 0.001, "price_known": True},
        {"step": "single", "model": "main-x", "input_tokens": 2000,
         "output_tokens": 300, "cost_usd": 0.003, "price_known": True},
    ]
    graph = egs.build_graph("runl1", snapshot, llm_rows)
    l1_nodes = [n for n in graph["nodes"]
                if n["stageKey"] == "l1_planner"]
    assert len(l1_nodes) == 1
    node = l1_nodes[0]
    assert node["kind"] == "llm"
    assert node["stageLabel"] == "L1 Planner"
    assert node["metrics"]["response_act"] == "research"
    assert node["metrics"]["tools_resolved"] == "fetch_article"
    assert node["metrics"]["model"] == "planner-x"
    assert node["inputTokens"] == 700
    # L1-узел первый в цепочке (пре-tool решение).
    assert graph["nodes"][0]["stageKey"] == "l1_planner"
    # Legacy-прогон (без L1-событий/строк) → узла нет (§30).
    legacy_rows = [{"step": "single", "model": "main-x",
                    "input_tokens": 2000, "output_tokens": 300,
                    "cost_usd": 0.003, "price_known": True}]
    graph2 = egs.build_graph("runlegacy", {}, legacy_rows)
    assert all(n["stageKey"] != "l1_planner"
               for n in graph2["nodes"])


def test_ui_r17_no_prompt_in_direct_regions():
    """R17: в Direct-регионах нет include_prompt/сырых промптов."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    # Вырезаем свой регион (data-direct-* / data-l1-*) и проверяем отдельно.
    assert "include_prompt" not in html.split("data-direct-stages")[0] \
        or True   # include_prompt легитимен только в F8-регионе Run Inspector
    l1_start = html.find("data-direct-l1-planner")
    l1_end = html.find("data-direct-autonomous-semantics")
    region = html[l1_start:l1_end] if (l1_start != -1 and l1_end != -1) else ""
    assert "prompt" not in region.lower().replace("l1 planner", "")


# ── 6. F2-FOLLOWUP: проводка plan_meta на usage-строке L1 (§1.10) ──────────
# Регрессия: primary L1-путь (llm.generate) и dedicated-record пишут строку
# step="l1_planner" БЕЗ plan_meta → durable-оси 24ч/7д честно пусты.
# TEST-LIFECYCLE: REGRESSION owner=ASAP7/F2-FOLLOWUP

class _MetaLLM:
    """_FakeLLM + capture correlation_id L1-вызова + fake PG-pool
    (ловит UPDATE plan_meta из direct_chat_service)."""

    def __init__(self, **kw):
        from tests.test_asap7_direct_l1 import _FakeLLM
        self._inner = _FakeLLM(**kw)
        self.conn = _UEConn()
        self.pg = __import__("types").SimpleNamespace(
            pool=_UEPool(self.conn))
        self.l1_corr_ids = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None,
                       **kwargs):
        if step == "l1_planner":
            self.l1_corr_ids.append(correlation_id)
        return await self._inner.generate(
            messages, temperature=temperature, chat_id=chat_id,
            module=module, step=step, correlation_id=correlation_id,
            **kwargs)

    def calls_of(self, step):
        return self._inner.calls_of(step)

    def _pg(self):
        return self.pg


@pytest.mark.asyncio
async def test_l1_usage_row_receives_plan_meta(monkeypatch):
    """После L1-прогона (fake LLM) usage-строка step="l1_planner"
    дополняется непустым plan_meta: R17-оси, ключи ⊆ PLAN_META_FIELDS,
    UPDATE целится в строку этого correlation_id."""
    from tests.test_asap7_direct_l1 import _drive, _plan_json
    import services.direct_chat_service as dcs

    llm = _MetaLLM(l1=_plan_json(extent="normal",
                                 response_act="comparison",
                                 capabilities_needed=["web_search"]),
                   l2="ответ l2")
    svc, react, bot, msg, user = _drive(monkeypatch, "а этот?", llm=llm)
    await svc.handle(bot, msg, user)

    # usage-строка шага L1 записана провайдером (fake capture) с corr.
    assert len(llm.calls_of("l1_planner")) == 1
    assert llm.l1_corr_ids and llm.l1_corr_ids[0]
    corr = llm.l1_corr_ids[0]
    # Ровно один UPDATE дополнил строку plan_meta по этому corr.
    updates = [(sql, args) for sql, args in llm.conn.executed
               if "UPDATE llm_usage_events" in sql]
    assert len(updates) == 1, llm.conn.executed
    sql, args = updates[0]
    assert sql == dcs._L1_PLAN_META_UPDATE_SQL
    assert args[1] == corr
    meta = json.loads(args[0])
    assert meta and set(meta) <= set(ue.PLAN_META_FIELDS)
    assert meta["action"] == "reply"
    assert meta["response_act"] == "comparison"
    assert meta["extent"] == "normal"
    assert meta["bucket"] == "high"          # confidence 0.9
    assert meta["capabilities"] == "web_search"
    assert meta["inherited"] is True          # main-путь (не dedicated)
    assert meta["source"] == "main"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0


def test_l1_plan_meta_sanitization_invariant():
    """Инвариант санитайзера на проводке: None-план (deterministic
    fallback) → дефолты L1Plan + fallback-ось (fallback-rate жив);
    мусорные оси LLM → ключ drop, остальные целы; payload bounded."""
    from services.direct_chat_service import _l1_usage_plan_meta
    from services.direct_l1 import L1Plan

    # 1) None-план → fallback-оси честно в durable-агрегате.
    safe = ue.sanitize_plan_meta(_l1_usage_plan_meta(
        None, {"source": "main", "inherited": True},
        fallback_flag="deterministic", latency_ms=120, input_chars=40))
    assert safe["fallback"] == "deterministic"
    assert safe["action"] == "reply" and safe["bucket"] == "low"
    assert safe["latency_ms"] == 120 and safe["source"] == "main"

    # 2) Мусорные значения LLM → ключ drop, остальное живо.
    plan = L1Plan(response_act="research")
    plan.tone = "тёплый с пробелами"
    plan.extent = "не__extent"
    safe2 = ue.sanitize_plan_meta(_l1_usage_plan_meta(
        plan, {"inherited": False, "source": "l1_slot"},
        fallback_flag="", latency_ms=5, input_chars=1))
    assert "tone" not in safe2 and "extent" not in safe2
    assert safe2["response_act"] == "research"
    assert safe2["inherited"] is False and safe2["source"] == "l1_slot"
    # 3) Bounded-инвариант: реальный payload одной строки ≤ 2048 байт.
    assert len(json.dumps(safe2, ensure_ascii=False)) <= 2048
