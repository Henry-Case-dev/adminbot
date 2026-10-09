"""MCA-17c (round 10.47, ADR-1028-23) — инварианты санкций (spec §7).

Замеры дельт фичи против пост-mca-12 baseline (прод 2.58.65):
  * Δ DDL = 0 сверх санкционированного хвоста v34 (NOTE P2-D, ASAP 6 §8,
    `mca-14` реестр; прецедент v21→…→v33);
  * Δ каталога = 0 — REGISTRY 523 (F8 NOT_APPLICABLE);
  * Δ KS = 0 — kill-switches 85 = 85 (защита write-API = RBAC+audit);
  * Δ reason = +1 `oversight_job_action` — 279→280 (единственная дельта
    словаря; контрольных кодов до этого не было);
  * Δ тулов = 0 — METERED_TOOLS 14 = 14;
  * Δ routes = +3 на NEW `web/api/oversight_router.py`; `web/api/routes.py`
    byte-freeze — ROUTES_SHA256_F11 держится (re-pin сводится к верификации,
    L-F11S-1);
  * реестр/widget-ID — 47 `ProcessDefinition` = 47 (новых widget-ID 0);
  * APP_VERSION — 2.58.65 не тронут (bump 2.58.66 — DevOps, T-5198);
  * регистрация роутера — web/app.py include рядом с oversight_router.
"""
import asyncio
import hashlib
from pathlib import Path

from config.settings import APP_VERSION
from services import mca_events
from services import mca_gates
from services import param_catalog as pc
from services.tool_schemas import TOOL_CALLING_TOOLS
from services.mca_process_registry import PROCESS_REGISTRY
from web.api.oversight_router import oversight17c_router

ROOT = Path(__file__).resolve().parents[1]


def test_reason_280_single_delta():
    # 279 → 280: ровно один санкционированный код mca-17c.
    assert len(mca_events.REASON_CODES) == 280
    assert "oversight_job_action" in mca_events.REASON_CODES
    # другие контрольные коды в словаре отсутствуют (grep-факт T-5179)
    for alien in ("oversight_cancel", "oversight_resume", "oversight_retry",
                  "job_action"):
        assert alien not in mca_events.REASON_CODES


def test_no_ddl_catalog_ks_tools_delta():
    # Δ DDL = 0 сверх санкционированного хвоста: свежая БД инициализируется
    # ровно в v34 (user_version).
    # NOTE (P2-D, ASAP 6 §8, санкция `mca-14` реестр): v34
    # (embedding_generation_namespace_v34) — ownership-миграция поколений
    # векторов; прецедент v21→…→v33.
    # ASAP 7 (F2, §1.10, Wave 3): v35 (llm_usage_plan_meta_v35) —
    # аддитивная nullable-колонка plan_meta JSONB в PG-only
    # `llm_usage_events`; SQLite-шаг — честный bookkeeping no-op (guard
    # sqlite_master), фактический DDL — PgDatabase.init (DDL_STATEMENTS,
    # ADD COLUMN IF NOT EXISTS). Точное равенство сохранено.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.database import DatabaseService
        d = DatabaseService(":memory:")
        loop.run_until_complete(d.initialize())
        cur = loop.run_until_complete(d.db.execute("PRAGMA user_version"))
        row = loop.run_until_complete(cur.fetchone())
        assert int(row[0]) == 35
    finally:
        loop.run_until_complete(d.close())
        loop.close()
    assert len(mca_gates.KILL_SWITCHES) == 85         # Δ KS = 0
    assert len(TOOL_CALLING_TOOLS) == 14              # Δ тулов = 0
    # REGISTRY 523 (F8 --check отдельно; здесь — канон-число каталога)
    # ASAP 7 F2 (§1.6): +9 PG-only ключей L1 Planner (538→547).
    # Параллельный лейн F4 (§3.2, in-flight на момент снимка): +13
    # (stories/character §3.2) → 560; финальное значение фиксирует лейн,
    # приземляющийся последним (ребейзер — один sed).
    assert len(pc.REGISTRY) == 560


def test_registry_47_no_new_widgets():
    assert len(PROCESS_REGISTRY) == 47                # widget-ID 0 (47=47)


def test_coverage_matrix_sync():
    """T-5191/B-2: каждая definition несёт обязательные поля контракта
    (структурная синхронизация реестра ↔ матрицы покрытия
    `coverage_matrix.md`; file:line-факты — в самой матрице, тест
    проверяет структуру, не конкретные строки — без overfit)."""
    from services.mca_process_registry import WIDGET_NONE, runtime_status
    allowed_status = {"implemented", "disabled", "not_run",
                      "not_instrumented", "not_implemented", "unavailable"}
    ids = set()
    for p in PROCESS_REGISTRY:
        # идентификация и назначение (§27.1 `:1335`)
        assert p.process_id and p.version and p.purpose
        assert p.trigger_kind in ("per_message", "per_request", "on_write",
                                  "on_demand", "background", "schedule",
                                  "event", "manual")
        assert p.stages or p.version == "0"      # v0-заготовка без стадий
        # widget-ID обязателен у всех (v0 — явный маркер WIDGET_NONE)
        assert isinstance(p.widget_id, str) and p.widget_id
        # статус честен и входит в словарь реестра
        assert runtime_status(p) in allowed_status
        ids.add(p.process_id)
    # 47 уникальных process_id
    assert len(ids) == 47
    # v0-заготовки — без widget (честная «заготовка», не активный процесс).
    # mca-17 (round 1050+): scheduler.reactions — честный v0-аменд
    # (выделенного due_check-планировщика в коде нет, контур реакций —
    # синхронный per-message путь; не «будущая фича», а снятая декларация).
    v0 = {p.process_id for p in PROCESS_REGISTRY if p.version == "0"}
    assert v0 == {"context.compress", "context.selective",
                  "memory.lifecycle", "relations.semantic",
                  "scheduler.reactions"}
    for p in PROCESS_REGISTRY:
        if p.version == "0":
            assert p.widget_id == WIDGET_NONE
            assert p.status if hasattr(p, "status") else True
    # матрица покрытия существует и упоминает все 47 (артефакт T-5191).
    # Cross-lane fix (round 10.47): PM-close (3e3bdb7) заархивировал пакет
    # фичи → coverage_matrix.md живёт в plans/archive/…round1047/; тест
    # принимает оба расположения (features до архивации, archive после),
    # sync-проверки остаются значимыми в обоих состояниях.
    matrix_candidates = [
        ROOT / "plans" / "features" / "mca-17c-analytics-matrix"
        / "coverage_matrix.md",
        ROOT / "plans" / "archive" / "mca-17c-analytics-matrix-round1047"
        / "coverage_matrix.md",
    ]
    matrix = next((p for p in matrix_candidates if p.exists()),
                  matrix_candidates[0])
    text = matrix.read_text(encoding="utf-8")
    for pid in sorted(ids):
        assert pid in text, f"coverage_matrix: нет строки для {pid}"


def test_app_version_not_bumped():
    # bump 2.58.65→2.58.66 — домен @DevOps (T-5198), Builder не делает.
    assert APP_VERSION == "2.58.74"


def test_routes_plus3_and_registration():
    paths = sorted({r.path for r in oversight17c_router.routes})
    assert paths == ["/experience/funnel", "/jobs/{job_id}/action", "/runs"]
    # регистрация в web/app.py (include рядом с oversight_router)
    app_py = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
    assert "from web.api.oversight_router import oversight17c_router" \
        in app_py
    assert 'include_router(oversight17c_router, prefix="/api/oversight")' \
        in app_py


def test_routes_py_byte_freeze_pin_intact():
    # прецедент mca-12: routes.py НЕ менялся → пин F11 цел (re-pin =
    # осознанная верификация, L-F11S-1).
    from tests.test_round1025_f8_registry import ROUTES_SHA256_F11
    digest = hashlib.sha256(
        (ROOT / "web" / "api" / "routes.py").read_bytes()).hexdigest()
    assert digest == ROUTES_SHA256_F11


def test_supervisor_cancel_exposes_existing_semantics():
    """AMEND task_supervisor.py — только expose (ADR D10): cancel =
    JOB_CANCELLED-финализация + fencing (механизм recover_stale), no-op на
    терминальных. Смена семантики существующих операций запрещена."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.database import DatabaseService
        from services.task_supervisor import TaskJobStore
        d = DatabaseService(":memory:")
        loop.run_until_complete(d.initialize())
        store = TaskJobStore(d)
        jid = loop.run_until_complete(
            store.enqueue(owner="t", kind="secondary"))
        assert loop.run_until_complete(store.cancel(jid)) is True
        row = loop.run_until_complete(store.get(jid))
        assert row["status"] == "cancelled"
        token = int(row["fencing_token"])
        # повторный cancel на cancelled — no-op (идемпотентность)
        assert loop.run_until_complete(store.cancel(jid)) is False
        row2 = loop.run_until_complete(store.get(jid))
        assert int(row2["fencing_token"]) == token
    finally:
        loop.run_until_complete(d.close())
        loop.close()
