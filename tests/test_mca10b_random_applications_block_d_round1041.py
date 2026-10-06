"""MCA-10b `mca-10b-random-applications` — focused-тесты блока D
(T-5060 живая визуализация §14.11 / T-5061 наблюдаемость / блок E —
каталог `random.uses.*` + F8-переиздание; ADR-1028-17 D11/D12/D16;
приёмка A35 + OFF-честность витрины).

Покрытие:
  * A35/T-5060: ID показанного события существует в журнале; метка
    источника = фактический (actual_source); открытие/чтение витрины —
    БЕЗ внешних QRNG/LLM-вызовов; Δ routes = 0; OFF (master или
    `random.uses.ui_visualization`) → живая часть честно выключена;
    chat scope/R17 (чужой чат без прав — события не отдаются);
  * T-5061: процесс `random.uses` v1 в реестре (code-declared, стадии =
    lifecycle, widget-ID строки §27.1, gate-resolver); OFF → честный
    disabled; trace `mca_pipeline_runs` — сквозной выбор→проверка→исход;
  * Блок E (санкция §13.2/D16): REGISTRY 504→510 (+6 PG-only bool
    `memory.random_uses_*`, группа memory_random существующая, per-chat,
    не-секреты), GROUPS/_TAB_BY_GROUP/TAB_RULES без роста, F8 `--check`
    зелёный, f8_baseline/catalog_baseline консистентны.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from services import mca_events, mca_gates
from services import mca_exploration as mx
from services import mca_random_source as mrs
from services.database import DatabaseService
from services.status_service import StatusService

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_state():
    mca_events.reset_pending()
    mx.reset_delivery_pendings()
    yield
    mca_events.reset_pending()
    mx.reset_delivery_pendings()


async def _fresh_db(tmp_path, name="mca10b_d.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class FakeSource:
    """Детерминированный источник (explored-путь, quantum-метка)."""

    def __init__(self, probability=0.0, index=0):
        self.probability = probability
        self.index = index
        self.prob_calls = 0
        self.index_calls = 0

    async def choose(self, primary, alternatives, **kwargs):
        return await mrs.ExplorationPolicy(self).choose(
            primary, alternatives, **kwargs)

    async def draw_probability(self, **kwargs):
        self.prob_calls += 1
        return mrs.DrawResult(value=self.probability, source="quantum",
                              draw_id="prob-draw")

    async def draw_index(self, n, **kwargs):
        self.index_calls += 1
        return mrs.DrawResult(index=self.index, source="quantum",
                              draw_id="sel-draw")


class _Cand:
    """Минимальный допустимый кандидат (R17-safe ID)."""

    candidate_id = "c1"
    admissible = True
    candidate_version = 1
    source_refs = ()


# ── A35/T-5060: витрина применений ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_A35_shown_event_exists_in_journal_and_source_actual(
        tmp_path, monkeypatch):
    """ID показанного события существует в журнале; метка источника =
    actual_source (фактический, не запрошенный); детали — R17-safe."""
    db = await _fresh_db(tmp_path)
    src = FakeSource(probability=0.0, index=0)
    monkeypatch.setattr(mx, "get_source", lambda db=None: src)
    choice, result = await mx.choose_conversation_alternative(
        db, chat_id=-5, primary=None, pool=[_Cand()], source=src,
        requested_source="anu")
    assert choice is not None and choice.explored
    assert choice.source == "quantum"
    await mca_events.flush_events(db)
    snap = await StatusService.random_uses_snapshot(db=db,
        chat_id=-5, chat_scope_allowed=True)
    assert snap["enabled"] is True and snap["scope"] == "chat"
    assert snap["events"], "событие применения ожидается в ленте"
    ev = snap["events"][0]
    shown_id = (ev.get("details") or {}).get("operation_id")
    assert shown_id
    # ID показанного события существует в durable-журнале
    rows = await mca_events.query_events(db, chat_id=-5, component="random",
                                         limit=50)
    journal_ids = {(r.get("entity_ids") or "") for r in rows}
    assert any(shown_id in blob for blob in journal_ids)
    # источник в витрине = фактический (quantum)
    details = ev.get("details") or {}
    assert details.get("actual_source") == "quantum"
    await db.close()


@pytest.mark.asyncio
async def test_A35_snapshot_makes_no_external_calls(tmp_path, monkeypatch):
    """Открытие/чтение витрины не делает QRNG/LLM-вызовов (A35/THR-12):
    чтение журнала работает даже при недоступном RandomSourceService; курсор
    = max(ts) событий; повтор — это чтение тех же записанных данных."""

    def _boom(db=None):
        raise AssertionError("витрина не должна вызывать источник случайности")

    monkeypatch.setattr(mrs, "get_service", _boom)
    db = await _fresh_db(tmp_path)
    mca_events.emit_mca_event(
        "random_uses", outcome=mca_events.OUTCOME_SUCCESS, component="random",
        stage="conversation_variant", chat_id=-5,
        entity_ids={"purpose": "conversation_variant", "selected": "c1",
                    "actual_source": "quantum"})
    await mca_events.flush_events(db)
    snap = await StatusService.random_uses_snapshot(db=db,
        chat_id=-5, chat_scope_allowed=True)
    assert snap["enabled"] is True
    assert snap["cursor"] == max(int(e["ts"]) for e in snap["events"])
    assert snap["events"][0]["details"]["selected"] == "c1"
    await db.close()


@pytest.mark.asyncio
async def test_A35_off_hides_live_part(tmp_path, monkeypatch):
    """OFF (master или `random.uses.ui_visualization=false`) → живая часть
    честно выключена (enabled=false, без событий); остаётся статичный блок
    10a (на координатор/события не влияет)."""
    db = await _fresh_db(tmp_path)
    mca_events.emit_mca_event(
        "random_uses", outcome=mca_events.OUTCOME_SUCCESS, component="random",
        stage="belief_review", chat_id=-5, entity_ids={"purpose": "x"})
    await mca_events.flush_events(db)
    monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: False)
    snap = await StatusService.random_uses_snapshot(db=db,
        chat_id=-5, chat_scope_allowed=True)
    assert snap == {"enabled": False, "events": [], "cursor": None,
                    "scope": ""}
    monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: True)

    async def _vis_off(db_, use, chat_id=None, default=True):
        return use != mx.USE_UI_VISUALIZATION

    monkeypatch.setattr(mx, "use_enabled", _vis_off)
    snap = await StatusService.random_uses_snapshot(db=db,
        chat_id=-5, chat_scope_allowed=True)
    assert snap["enabled"] is False and snap["events"] == []
    await db.close()


@pytest.mark.asyncio
async def test_A35_chat_scope_and_no_foreign_events(tmp_path):
    """Права/chat scope: без чата и без global-админ прав события не
    отдаются (scope=restricted); чужой чат не виден (R17/THR-11)."""
    db = await _fresh_db(tmp_path)
    mca_events.emit_mca_event(
        "random_uses", outcome=mca_events.OUTCOME_SUCCESS, component="random",
        stage="memory_recall", chat_id=-5, entity_ids={"purpose": "x"})
    await mca_events.flush_events(db)
    snap = await StatusService.random_uses_snapshot(db=db,
        chat_id=None, is_global_admin=False,
        chat_scope_allowed=False)
    assert snap["events"] == [] and snap["scope"] == "restricted"
    snap_other = await StatusService.random_uses_snapshot(db=db,
        chat_id=-99, chat_scope_allowed=True)
    assert snap_other["events"] == []      # чужой чат
    await db.close()


# ── T-5061: реестр/trace/матрица ────────────────────────────────────────────

def test_T5061_registry_declares_random_uses():
    """Процесс `random.uses` v1 code-declared (прецедент random.source):
    стадии = lifecycle §14.5, widget-ID строки §27.1 — контракт mca-17c,
    gate-resolver master-выключателя, события единого словаря."""
    from services import mca_process_registry as reg
    proc = reg.get_process("random.uses")
    assert proc is not None and proc.version == "1"
    assert proc.stages == ("candidate", "selected", "checking", "accepted",
                           "rejected", "deferred", "failed")
    assert proc.widget_id == "Случайность и её применения"
    assert proc.enabled_gate == "MCA_RANDOM_USES_ENABLED"
    assert proc.owner_feature == "mca-10b"
    assert set(proc.event_names) == {"random_uses", "random_uses_lifecycle",
                                     "random_uses_background"}
    assert reg._GATE_RESOLVERS.get("MCA_RANDOM_USES_ENABLED") == \
        "random_uses_enabled"
    pv = reg.get_pipeline("random.uses")
    assert pv is not None and pv.stage("selected") is not None
    assert "checking" in pv.required_stages


def test_T5061_registry_off_honest_disabled(monkeypatch):
    """Master OFF → честный `disabled` в реестре (не «работает»); без
    событий → `not_run` (честная матрица §27.1)."""
    from services import mca_process_registry as reg
    proc = reg.get_process("random.uses")
    monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: False)
    assert reg.runtime_status(proc) == reg.STATUS_DISABLED
    monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: True)
    assert reg.runtime_status(proc, event_names_present=frozenset()) == \
        reg.STATUS_NOT_RUN
    assert reg.runtime_status(
        proc, event_names_present=frozenset({"random_uses"})) == \
        reg.STATUS_IMPLEMENTED


@pytest.mark.asyncio
async def test_T5061_trace_run_choice_check_outcome(tmp_path, monkeypatch):
    """Trace `mca_pipeline_runs`: сквозной переход выбор → проверка → исход
    одного operation; события несут pipeline_run_id; run закрыт честным
    итогом; R17 (только ID/коды)."""
    db = await _fresh_db(tmp_path)
    src = FakeSource(probability=0.0, index=0)
    monkeypatch.setattr(mx, "get_source", lambda db=None: src)
    choice, result = await mx.choose_conversation_alternative(
        db, chat_id=-5, primary=None, pool=[_Cand()], source=src)
    assert choice is not None
    cursor = await db.db.execute(
        "SELECT pipeline_run_id, pipeline_type, pipeline_version, status, "
        "reason_code FROM mca_pipeline_runs WHERE pipeline_type = "
        "'random.uses' ORDER BY started_at DESC LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    run = dict(row)
    assert run["pipeline_version"] == "1"
    assert run["status"] == "succeeded"
    assert run["pipeline_run_id"]
    await mca_events.flush_events(db)
    events = await mca_events.query_run_events(db, run["pipeline_run_id"])
    assert [e["event_name"] for e in events if
            e["event_name"].startswith("random_uses")]
    assert all(e.get("pipeline_run_id") == run["pipeline_run_id"]
               for e in events)
    blob = json.dumps(events, ensure_ascii=False)
    assert "prepared_text" not in blob and "summary" not in blob
    await db.close()


# ── Блок E: каталог + F8 (санкция §13.2/D16) ────────────────────────────────

def test_blockE_catalog_random_uses_keys():
    """+6 PG-only bool `memory.random_uses_*` в существующей группе
    memory_random: per-chat, не-секреты, все default ON (read-path
    fail-open True); GROUPS/_TAB_BY_GROUP/TAB_RULES без роста."""
    from services import param_catalog as pc
    assert len(pc.REGISTRY) == 523
    assert len(pc.GROUPS) == 113
    assert len(pc._TAB_BY_GROUP) == 111
    assert len(pc.TAB_RULES) == 22
    uses = [f"memory.random_uses_{u}" for u in sorted(mx.USES)]
    assert len(uses) == 6
    for key in uses:
        spec = pc.get_by_pg_key(key)
        assert spec is not None, key
        assert spec.group == "memory_random"
        assert spec.type == "bool" and spec.secret is False
        assert spec.per_chat is True
        assert spec.category == "memory"
        assert pc.group_tab(spec.group) is not None
    # master kill-switch в каталог НЕ входит (env-only, прецедент mca-16)
    assert pc.get_by_pg_key("memory.random_uses_enabled") is None
    # секрет-счётчик не изменился
    secrets = [s for s in pc.REGISTRY.values() if s.secret]
    assert len(secrets) == 33


def test_blockE_f8_check_green_and_baselines():
    """F8 ADR-1026-2: `--check` зелёный на новой фиксации каталога
    (REGISTRY 510, delta 99); fixtures консистентны; Δ routes = 0."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools/gen_param_registry_round1025.py"),
         "--check"], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "523" in res.stdout   # mca-20 round 10.44: 519 → 523
    fx = json.loads((ROOT / "tests/fixtures/round1025/f8_baseline.json")
                    .read_text(encoding="utf-8"))
    assert fx["counts"]["REGISTRY"] == 523
    assert fx["counts"]["GROUPS"] == 113
    assert fx["counts"]["TAB_BY_GROUP"] == 111
    assert fx["counts"]["TAB_RULES"] == 22
    assert fx["counts"]["delta"] == 112
    cb = json.loads((ROOT / "tests/fixtures/round1025/catalog_baseline.json")
                    .read_text(encoding="utf-8"))
    assert len(cb["registry_keys"]) == 523
    for key in ("memory.random_uses_belief_review",
                "memory.random_uses_ui_visualization"):
        assert key in cb["registry_keys"]
    # routes: mca-18 (ADR-1028-18 D8/D10, CA-18-8, round 10.42) — routes +4
    # в существующем экране «Личность» (self-model compact + rules
    # pause/resume/sources); rework M-1: GET .../sources фильтрует по
    # source_observation_ids правила (review M-1); хэш переутверждён
    # осознанно (L-F11S-1; прецедент mca-10a POST /api/random/test).
    # Каталог Δ=0 (errata).
    # MCA-19 (10.43 Wave 2, ADR-1028-19 D4/D15): routes +2 в mod_vision
    # (POST /api/vision/test + GET /api/vision/state) — хэш переутверждён
    # осознанно (L-F11S-1; синхронно с ROUTES_SHA256_F11 в
    # test_round1025_f8_registry).
    # MCA-20 (round 10.44, ADR-1028-20 D11/D13): routes +2 в «Аналитике»
    # (GET /api/factcheck/temporal/runs[/{run_id}]) — хэш переутверждён
    # осознанно (L-F11S-1; tools/_mca20_reissue_f8.py).
    import hashlib
    routes_sha = hashlib.sha256(
        (ROOT / "web/api/routes.py").read_bytes()).hexdigest()
    assert routes_sha == ("8153b8bd389711e9cb7a61352e58f6f8217c0a23657"
                          "5f75489ca617c0d0c7b45")
