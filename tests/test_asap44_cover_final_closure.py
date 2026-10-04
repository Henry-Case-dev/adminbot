"""ASAP 4.4 (T-4868…T-4872, T-4881 #1–10, T-4884) — focused cover closure:
counter contract, preview issue display, draft snapshot, revision no-op/promote,
real backend E2E chain (real registry/assets/API; provider+HTTP seam mocked).

Pre-fix RED для RC-B…RC-E зафиксирован в
`plans/features/asap-4-4-final-live-closure/evidence.md` §0 (этот файл до
фиксов падал; см. evidence).

Запуск (точечно, без полного suite):
    .venv\\Scripts\\python.exe -m pytest tests/test_asap44_cover_final_closure.py -q
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import cover_style_jobs as cjobs
from services import cover_style_preview as preview_jobs
from services import cover_style_registry as registry
from services import image_capabilities as cap
from services import lore_runtime
from services.config_cache import ConfigCache
from services.cover_style_edit import EditResult
from services.database import DatabaseService
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api.cover_styles import cover_styles_router

ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN = "123456:ASAP44_TOKEN"
ADMIN_ID = 111222

pytestmark = pytest.mark.asap4


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── temp-SQLite asyncpg-compatible shim (тот же контур, что 4.3/step3) ──────

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_asap42_step3_style_integration import (  # noqa: E402
    _SqlitePg,
    create_schema,
    make_init_data,
)


def _client(pg) -> TestClient:
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    cache._roles = {
        "admin": {"permissions": {"wildcard": True},
                  "is_custom": False, "role_type": "global_admin"},
    }
    cache._permissions = {"admin": Permissions.from_dict({"wildcard": True})}
    cache._admins = {ADMIN_ID: "admin"}
    cache._pg_available = True
    cache._initialized = True
    cache._pg = pg
    app = FastAPI()
    app.state.cache = cache
    app.include_router(cover_styles_router, prefix="/api")
    return TestClient(app)


def _hdr():
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN)}


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        type("S", (), {"API_TOKEN": TEST_TOKEN})())


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)


@pytest.fixture(autouse=True)
def _asset_dir(monkeypatch, tmp_path):
    d = tmp_path / "assets"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("COVER_STYLE_ASSETS_DIR", str(d))


@pytest.fixture
def pg(tmp_path):
    db_path = tmp_path / "cover_style.sqlite3"
    create_schema(db_path)
    return _SqlitePg(db_path)


@pytest.fixture
def job_db(tmp_path):
    db = DatabaseService(str(tmp_path / "jobs.sqlite3"))
    _run(db.initialize())
    lore_runtime.set_lore_components(db=db)
    preview_jobs.reset_preview_runners()
    yield db
    preview_jobs.reset_preview_runners()
    lore_runtime.reset_lore_runtime()
    try:
        _run(db.close())
    except Exception:
        pass


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")
STYLED_BYTES = b"STYLED-ASAP44-BYTES"


def _profile(**over):
    p = {
        "profile_id": "csp_x", "name": "Test", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": True, "counter_value": 10,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


def _stage_stub(captured: dict, styled: Path):
    """Мок style-стадии (продуктовый worker): фиксирует profile/args."""
    async def _fake(**kw):
        captured.update(kw)
        return {"applied": True, "reason": "",
                "styled_path": str(styled), "model": "m1", "provider": "p1",
                "prompt_diagnostics": {"compiled_chars": 10}}
    return _fake


def _base_stub(base: Path):
    async def _fake(*a, **kw):
        return (str(base), "ok")
    return _fake


def _patch_base_and_stage(monkeypatch, tmp_path, captured):
    base = tmp_path / "gen_base.png"
    base.write_bytes(PNG_BYTES)
    styled = tmp_path / "gen_styled.jpg"
    styled.write_bytes(STYLED_BYTES)
    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose", _base_stub(base))
    monkeypatch.setattr("services.cover_style_jobs.run_style_job",
                        _stage_stub(captured, styled))
    return base, styled


def _poll_job(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    snap = None
    while time.time() < deadline:
        resp = client.get("/api/cover/test-style/" + job_id, headers=_hdr())
        assert resp.status_code == 200, (resp.status_code, resp.text)
        snap = resp.json()
        if snap.get("status") in ("completed", "failed"):
            return snap
        time.sleep(0.03)
    return snap


def _save_body(detail: dict, **over) -> dict:
    body = {
        "name": detail["name"],
        "instruction": detail["instruction"],
        "pipeline_mode": detail["pipeline_mode"],
        "counter_enabled": detail["counter_enabled"],
        "next_issue_number": detail.get("next_issue_number"),
        "counter_format": detail["counter_format"],
        "model_mode": detail["model_mode"],
        "connection_id": detail["connection_id"],
        "model_id": detail["model_id"],
        "enabled": detail["enabled"],
    }
    body.update(over)
    return body


def _draft_body(draft: dict, *, name: str = "Test", enabled: bool = True) -> dict:
    return {
        "name": name,
        "instruction": draft["instruction"],
        "pipeline_mode": draft["pipeline_mode"],
        "counter_enabled": draft["counter_enabled"],
        "next_issue_number": draft["next_issue_number"],
        "counter_format": draft["counter_format"],
        "model_mode": draft["model_mode"],
        "connection_id": draft.get("connection_id"),
        "model_id": draft.get("model_id"),
        "enabled": enabled,
    }


def _draft(instruction: str, next_issue: int) -> dict:
    return {
        "instruction": instruction,
        "pipeline_mode": "generate_then_edit",
        "counter_enabled": True,
        "next_issue_number": next_issue,
        "counter_format": "ВЫПУСК {counter}",
        "model_mode": "default",
    }


def _assign_issue(pg, run_id: str, number: int,
                  profile_id: str = "csp_x") -> None:
    async def _do():
        async with pg.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO cover_style_issue_assignments (profile_id, "
                "summary_run_id, issue_number) VALUES ($1,$2,$3)",
                profile_id, run_id, number)
    _run(_do())


def _fetch_assigned_numbers(pg, profile_id: str = "csp_x") -> list:
    async def _do():
        async with pg.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT issue_number FROM cover_style_issue_assignments "
                "WHERE profile_id = $1", profile_id)
        return [int(r["issue_number"]) for r in rows]
    return _run(_do())


# ── #1–#3: RC-A regression (base registered / fetchable / failure => no pair) ─

def test_cover1_generated_base_registered_in_registry(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile()))
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        assert r.status_code == 200, r.text
        snap = _poll_job(client, r.json()["job_id"])
    assert snap["status"] == "completed", snap
    before_id = snap["preview_before_url"].rsplit("/", 1)[-1]
    row = _run(registry.get_asset(pg, before_id))
    assert row is not None, "base asset не зарегистрирован в PG"
    assert Path(row["disk_path"]).read_bytes() == PNG_BYTES


def test_cover2_before_after_fetchable_via_real_api_route(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile()))
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        rb = client.get(snap["preview_before_url"], headers=_hdr())
        ra = client.get(snap["preview_after_url"], headers=_hdr())
        assert rb.status_code == 200 and rb.content == PNG_BYTES
        assert ra.status_code == 200 and ra.content == STYLED_BYTES
        # both assets — реальные registry-строки (не placeholder)
        stored = _run(registry.get_profile_with_refs(pg, "csp_x"))
        assert registry.preview_pair_current(stored) is True


def test_cover3_base_registry_failure_leaves_no_pair(
        pg, tmp_path, monkeypatch, job_db):
    """Negative control RC-A: upsert_asset(base) fails → job failed ДО pair."""
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile()))

    async def _fail_upsert(_pg, _meta):
        return False

    monkeypatch.setattr(registry, "upsert_asset", _fail_upsert)
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "failed", snap
        assert snap["machine_reason"] == "base_generation_failed", snap
        stored = _run(registry.get_profile_with_refs(pg, "csp_x"))
        assert stored["preview_revision"] is None
        assert stored["preview_before_asset_id"] is None
        assert stored["preview_after_asset_id"] is None
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        assert detail["preview_status"] is None


# ── #4: RC-C preview issue display = current next, counter НЕ расходуется ───

def test_cover4_next_issue_display_and_no_counter_mutation(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile(counter_value=10)))
    with _client(pg) as client:
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        assert detail["next_issue_number"] == 11
        assert detail["preview_issue"] == "ВЫПУСК 11"
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        assert r.status_code == 200, r.text
        assert r.json()["preview_issue"] == "ВЫПУСК 11"
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        stored = _run(registry.get_profile(pg, "csp_x"))
        assert stored["counter_value"] == 10, "Test Style израсходовал counter"
        assert client.get("/api/cover/styles/csp_x",
                          headers=_hdr()).json()["preview_issue"] == "ВЫПУСК 11"
    # hardcoded `00`-preview контракт удалён из registry
    src = (ROOT / "services" / "cover_style_registry.py").read_text(
        encoding="utf-8")
    assert "preview_issue_display(counter_format: str) -> str" not in src
    assert "format_issue(counter_format, 0" not in src


# ── #5: production ladder next=11 → allocate 11 → retry 11 → next run 12 ────

def test_cover5_production_ladder_11_retry_11_next_12(pg, job_db):
    assert _run(registry.upsert_profile(pg, _profile(counter_value=0,
                                                      revision=1)))
    with _client(pg) as client:
        body = _save_body(client.get("/api/cover/styles/csp_x",
                                     headers=_hdr()).json(),
                          next_issue_number=11)
        r = client.post("/api/cover/styles?style_id=csp_x", json=body,
                        headers=_hdr())
        assert r.status_code == 200, r.text
        stored = _run(registry.get_profile(pg, "csp_x"))
        assert stored["counter_value"] == 10, "save N пишет counter_value=N-1"
        assert r.json()["next_issue_number"] == 11
        # production allocation: первый = 11, retry того же run = 11
        assert _run(registry.resolve_issue_number(pg, "csp_x", "run_a")) == 11
        assert _run(registry.resolve_issue_number(pg, "csp_x", "run_a")) == 11
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        assert detail["next_issue_number"] == 12  # last_assigned=11
        # следующий независимый run = 12
        assert _run(registry.resolve_issue_number(pg, "csp_x", "run_b")) == 12
        assert client.get("/api/cover/styles/csp_x",
                          headers=_hdr()).json()["next_issue_number"] == 13


# ── F-N2 (live defect): allocation SKIP-ahead past occupied numbers ─────────

def test_issue_allocation_skips_occupied_numbers(
        pg, tmp_path, monkeypatch, job_db):
    """Live: next=11, assignments 11–13 заняты историей → pre-fix
    `resolve_issue_number` падал на UNIQUE(profile_id, issue_number) →
    None (counter rollback); fix: первый свободный = 14, counter=14,
    retry того же run = 14, следующий = 15, Test Style counter не тратит."""
    assert _run(registry.upsert_profile(
        pg, _profile(counter_value=10, revision=1)))
    for run_id, number in (("old_a", 11), ("old_b", 12), ("old_c", 13)):
        _assign_issue(pg, run_id, number)
    with _client(pg) as client:
        assert _run(registry.resolve_issue_number(
            pg, "csp_x", "run_new")) == 14
        # retry того же summary_run_id — идемпотентен, тот же номер
        assert _run(registry.resolve_issue_number(
            pg, "csp_x", "run_new")) == 14
        stored = _run(registry.get_profile(pg, "csp_x"))
        assert stored["counter_value"] == 14, \
            "counter persisted как last_assigned (14)"
        # следующий независимый run получает следующий свободный
        assert _run(registry.resolve_issue_number(
            pg, "csp_x", "run_next")) == 15
        assert _run(registry.get_profile(
            pg, "csp_x"))["counter_value"] == 15
        # занятые номера не переиспользованы (UNIQUE не нарушен)
        assert sorted(_fetch_assigned_numbers(pg)) == [11, 12, 13, 14, 15]
        # editor: display = counter+1 (без redesign), номер не расходуется
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        assert detail["next_issue_number"] == 16
        captured = {}
        _patch_base_and_stage(monkeypatch, tmp_path, captured)
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        assert r.status_code == 200, r.text
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        assert _run(registry.get_profile(
            pg, "csp_x"))["counter_value"] == 15

    # точный read-back после reload (durable)
    pg2 = _SqlitePg(pg.path)
    assert _run(registry.get_profile(pg2, "csp_x"))["counter_value"] == 15
    assert sorted(_fetch_assigned_numbers(pg2)) == [11, 12, 13, 14, 15]


def test_issue_allocation_picks_first_free_gap(pg):
    """Skip-ahead выбирает ПЕРВЫЙ свободный, а не max(occupied)+1."""
    assert _run(registry.upsert_profile(
        pg, _profile(counter_value=10, revision=1)))
    for run_id, number in (("g_b", 12), ("g_c", 13)):
        _assign_issue(pg, run_id, number)
    assert _run(registry.resolve_issue_number(pg, "csp_x", "run_gap")) == 11
    assert _run(registry.get_profile(pg, "csp_x"))["counter_value"] == 11
    assert sorted(_fetch_assigned_numbers(pg)) == [11, 12, 13]


# ── #6: RC-D Test Style uses current draft snapshot, DB not overwritten ─────

def test_cover6_test_style_uses_current_draft_snapshot(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(
        pg, _profile(instruction="SAVED-INSTR", counter_value=10)))
    draft = {"instruction": "DRAFT-INSTR", "next_issue_number": 12}
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x", "draft": draft})
        assert r.status_code == 200, r.text
        assert r.json()["preview_issue"] == "ВЫПУСК 12"
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        # durable preview job несёт snapshot/revision fingerprint
        state = _run(cjobs.load_cover_state(job_db, r.json()["job_id"]))
        expected = dict(_profile(instruction="DRAFT-INSTR", counter_value=11))
        assert state.draft_fingerprint == registry.style_fingerprint(expected)
        assert state.draft_snapshot["instruction"] == "DRAFT-INSTR"
        # ровно то, что видел editor, ушло в style stage
        assert captured["profile"]["instruction"] == "DRAFT-INSTR"
        assert captured["profile"]["counter_value"] == 11
        # DB-профиль НЕ перезаписан snapshot'ом
        stored = _run(registry.get_profile(pg, "csp_x"))
        assert stored["instruction"] == "SAVED-INSTR"
        assert stored["counter_value"] == 10
        # backward compat: без draft — сохранённая DB-версия
        r2 = client.post("/api/cover/test-style", headers=_hdr(),
                         json={"profile_id": "csp_x"})
        snap2 = _poll_job(client, r2.json()["job_id"])
        assert snap2["status"] == "completed", snap2
        assert captured["profile"]["instruction"] == "SAVED-INSTR"
        assert captured["profile"]["counter_value"] == 10


# ── #7–#8: RC-E no-op Save: revision не растёт, pair живёт ──────────────────

def test_cover7_noop_save_does_not_bump_revision(pg, job_db):
    assert _run(registry.upsert_profile(pg, _profile(revision=1)))
    with _client(pg) as client:
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        r = client.post("/api/cover/styles?style_id=csp_x",
                        json=_save_body(detail), headers=_hdr())
        assert r.status_code == 200, r.text
        assert r.json()["revision"] == detail["revision"], \
            "no-op Save увеличил revision"
        # изменение только имени — UI-only, pair/revision не трогает
        r2 = client.post("/api/cover/styles?style_id=csp_x",
                         json=_save_body(detail, name="Renamed"),
                         headers=_hdr())
        assert r2.json()["revision"] == detail["revision"]


def test_cover8_noop_save_keeps_preview_pair(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile(revision=1)))
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        assert detail["preview_status"] == "success"
        before_url = detail["preview_before_url"]
        after_url = detail["preview_after_url"]
        saved = client.post("/api/cover/styles?style_id=csp_x",
                            json=_save_body(detail), headers=_hdr())
        assert saved.status_code == 200, saved.text
        again = saved.json()
        assert again["revision"] == detail["revision"]
        assert again["preview_status"] == "success"
        assert again["preview_before_url"] == before_url
        assert again["preview_after_url"] == after_url
        assert again["preview_job_id"] == snap["preview_job_id"]
        stored = _run(registry.get_profile_with_refs(pg, "csp_x"))
        assert registry.preview_pair_current(stored) is True


# ── #9–#10: честный stale + promote exact tested draft ──────────────────────

def test_cover9_rendering_change_stales_pair_honestly(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile(revision=1)))
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        detail = client.get("/api/cover/styles/csp_x", headers=_hdr()).json()
        saved = client.post(
            "/api/cover/styles?style_id=csp_x",
            json=_save_body(detail,
                            instruction=detail["instruction"] + " Новое."),
            headers=_hdr())
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == detail["revision"] + 1
        assert saved.json()["preview_status"] is None
        assert saved.json()["preview_before_url"] is None
        assert saved.json()["preview_after_url"] is None
        assert saved.json()["preview_stale"] is True
        stored = _run(registry.get_profile_with_refs(pg, "csp_x"))
        assert registry.preview_pair_current(stored) is False


def test_cover10_exact_draft_save_promotes_preview(
        pg, tmp_path, monkeypatch, job_db):
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(
        pg, _profile(instruction="SAVED-INSTR", counter_value=10, revision=1)))
    draft = _draft("DRAFT-EXACT", 12)
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x", "draft": draft})
        assert r.status_code == 200, r.text
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        before = _run(registry.get_profile_with_refs(pg, "csp_x"))
        assert before["preview_revision"] == before["revision"] == 1
        # сохраняем РОВНО протестированный draft → promote без генерации
        saved = client.post("/api/cover/styles?style_id=csp_x",
                            json=_draft_body(draft), headers=_hdr())
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["revision"] == 2
        assert body["preview_revision"] == 2, "pair не promoted к saved revision"
        assert body["preview_status"] == "success"
        assert body["preview_before_url"] == snap["preview_before_url"]
        assert body["preview_after_url"] == snap["preview_after_url"]
        assert body["instruction"] == "DRAFT-EXACT"
        assert body["next_issue_number"] == 12
        # reload editor (новое соединение к тому же файлу)
        pg2 = _SqlitePg(pg.path)
        persisted = _run(registry.get_profile_with_refs(pg2, "csp_x"))
        assert registry.preview_pair_current(persisted) is True
        # сохранение ДРУГОГО контента оставляет pair stale
        other = client.post(
            "/api/cover/styles?style_id=csp_x",
            json=_draft_body(_draft("OTHER-INSTR", 12)), headers=_hdr())
        assert other.status_code == 200, other.text
        assert other.json()["preview_status"] is None
        assert other.json()["preview_stale"] is True


# ── T-4884: real backend path E2E (сиды/регистри/ассеты/API — реальные) ──────

def _patch_e2e_seams(monkeypatch, tmp_path, prompts: list):
    """Провайдер и style-HTTP — моки (без платных вызовов); вся остальная
    цепочка (worker/job → managed asset store → PG registry → public status →
    authenticated GET → Save → reload) — реальный код."""
    base = tmp_path / "e2e_base.png"
    base.write_bytes(PNG_BYTES)
    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose", _base_stub(base))

    async def _slot(**_kw):
        return {"provider": "nanogpt", "base_url": "https://provider.test/v1",
                "model": "qwen-image-3-pro", "connection_id": None,
                "custom_unresolved": False, "configured": True}

    monkeypatch.setattr(cjobs, "resolve_style_slot_inherited", _slot)
    monkeypatch.setattr(
        cap, "resolve_capabilities",
        lambda *a, **kw: cap.ImageModelCapabilities(
            image_edit=cap.TRUE, max_input_images=3,
            prompt_limit=cap.PromptLimit()))

    async def _edit(prompt, **_kw):
        prompts.append(prompt)
        return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

    monkeypatch.setattr(cjobs, "edit_image", _edit)


def test_e2e_worker_registry_status_gets_save_reload(
        pg, tmp_path, monkeypatch, job_db):
    prompts: list = []
    _patch_e2e_seams(monkeypatch, tmp_path, prompts)
    with _client(pg) as client:
        created = client.post("/api/cover/styles", headers=_hdr(), json={
            "name": "E2E", "instruction": "E2E SAVED INSTR",
            "pipeline_mode": "generate_then_edit", "counter_enabled": True,
            "next_issue_number": 11, "counter_format": "ВЫПУСК {counter}",
            "model_mode": "default"})
        assert created.status_code == 200, created.text
        pid = created.json()["profile_id"]
        draft = _draft("E2E DRAFT INSTR", 12)
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": pid, "draft": draft})
        assert r.status_code == 200, r.text
        assert r.json()["preview_issue"] == "ВЫПУСК 12"
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        assert snap["stage"] == "completed"
        before_url, after_url = snap["preview_before_url"], \
            snap["preview_after_url"]
        before_id = before_url.rsplit("/", 1)[-1]
        after_id = after_url.rsplit("/", 1)[-1]
        # managed asset store + PG registry — реальные строки/файлы
        brow = _run(registry.get_asset(pg, before_id))
        arow = _run(registry.get_asset(pg, after_id))
        assert brow is not None and arow is not None
        assert Path(brow["disk_path"]).read_bytes() == PNG_BYTES
        assert Path(arow["disk_path"]).read_bytes() == STYLED_BYTES
        # authenticated GET before/after
        rb = client.get(before_url, headers=_hdr())
        ra = client.get(after_url, headers=_hdr())
        assert rb.status_code == 200 and rb.content == PNG_BYTES
        assert ra.status_code == 200 and ra.content == STYLED_BYTES
        # draft НЕ сохранён как профиль; counter не потрачен
        stored = _run(registry.get_profile(pg, pid))
        assert stored["instruction"] == "E2E SAVED INSTR"
        assert stored["counter_value"] == 10
        assert registry.preview_pair_current(stored) is True
        # реально скомпилированный prompt содержал текущий next number
        assert any("ВЫПУСК 12" in p for p in prompts), prompts
        # Save РОВНО протестированного draft → promote
        saved = client.post(f"/api/cover/styles?style_id={pid}",
                            json=_draft_body(draft, name="E2E"),
                            headers=_hdr())
        assert saved.status_code == 200, saved.text
        detail = saved.json()
        assert detail["revision"] == 2
        assert detail["preview_revision"] == detail["revision"]
        assert detail["preview_status"] == "success"
        assert detail["preview_before_url"] == before_url
        assert detail["preview_after_url"] == after_url
        assert detail["next_issue_number"] == 12
        assert detail["preview_issue"] == "ВЫПУСК 12"
        # reload editor: pair переживает переоткрытие/новое соединение
        pg2 = _SqlitePg(pg.path)
        persisted = _run(registry.get_profile_with_refs(pg2, pid))
        assert registry.preview_pair_current(persisted) is True
        assert persisted["preview_before_asset_id"] == before_id
        assert persisted["preview_after_asset_id"] == after_id


# ── #11–#13 (Z4, T-4873–T-4875): prompt capability — один runtime truth ─────
#
# Pre-fix RED (зафиксирован в evidence.md §0): до правок (а) `POST
# /api/cover/prompt-limit` с одним `profile_id` возвращал 422 (sync
# `resolve_style_slot` vs §35 inherited runtime); (б) 400 «too long» без числа
# классифицировался generic `bad_request`; (в) bounded adaptive retry для
# unknown-лимита отсутствовал; (г) таксономия источника и `runtime_safe`
# ceiling отсутствовали.

def _wire_hot_image_slot(client, *, base_url: str, model: str):
    """Hot-конфиг клиента (как TestPromptLimitOverride 4.3): global image slot.

    PG-write выключен (`_pg_available=False`) — bot_settings пишется в
    in-memory ветке (та же, что в 4.3 §7.2 persistence-тестах)."""
    from services import hot_config
    cache = client.app.state.cache
    cache._lock = asyncio.Lock()
    cache._settings_updated_at = {}
    cache._pg_available = False
    cache._settings["models.image_base_url"] = base_url
    cache._settings["models.image_model"] = model
    hot_config.set_config_cache(cache)
    return cache


def _auto_caps_stub(monkeypatch):
    async def _auto(*_a, **_kw):
        return cap.ImageModelCapabilities(
            image_edit=cap.TRUE, text_to_image=cap.TRUE,
            max_input_images=3, prompt_limit=cap.PromptLimit())
    monkeypatch.setattr(cap, "resolve_capabilities_auto", _auto)


def _style_inheritance_on(monkeypatch):
    monkeypatch.setattr(
        "services.cover_style_pipeline.style_global_default_enabled",
        lambda: True)


def _nanogpt_slot_stub(monkeypatch):
    async def _slot(**_kw):
        return {"provider": "nanogpt", "base_url": "https://provider.test/v1",
                "model": "m1", "connection_id": None,
                "custom_unresolved": False, "configured": True}
    monkeypatch.setattr(cjobs, "resolve_style_slot_inherited", _slot)


def _route_stub(monkeypatch, route: str):
    async def _route(_base_url, _model, **_kw):
        return route
    monkeypatch.setattr("services.cover_style_edit.resolve_edit_route", _route)


def test_cover11_ui_and_runtime_share_one_effective_capability(
        pg, tmp_path, monkeypatch, job_db):
    """T-4873 + T-4874: UI meta/budget/prompt-limit и runtime обязаны резолвить
    один и тот же provider+base_url+model+route+operation; profile-only
    manual override персистится (live §7.2 422 больше не воспроизводится)."""
    from services import cover_style_edit as cse
    from services import hot_config
    cap.reset_cache()
    _auto_caps_stub(monkeypatch)
    _style_inheritance_on(monkeypatch)
    _route_stub(monkeypatch, cse.ROUTE_IMAGE_API)
    profile = _profile(counter_enabled=False, revision=2)
    assert _run(registry.upsert_profile(pg, profile))
    base = tmp_path / "c11_base.png"
    base.write_bytes(PNG_BYTES)
    captured: dict = {}

    async def _edit(prompt, **kw):
        captured.update(kw)
        captured["prompt"] = prompt
        return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

    try:
        with _client(pg) as client:
            _wire_hot_image_slot(client, base_url="https://nano-gpt.com/api/v1",
                                 model="qwen-image-3-pro")
            # реальный UI-контракт §7.2: только profile_id (как шлёт MiniApp)
            post = client.post("/api/cover/prompt-limit", headers=_hdr(), json={
                "profile_id": "csp_x", "operation": "image_edit",
                "mode": "manual", "unit": "chars", "value": 800})
            assert post.status_code == 200, post.text
            got = client.get("/api/cover/prompt-limit?profile_id=csp_x",
                             headers=_hdr()).json()
            assert got["mode"] == "manual" and got["value"] == 800, got
            assert got["source"] == cap.SOURCE_MANUAL, got
            assert got["source_taxonomy"] == "manual", got
            detail = client.get("/api/cover/styles/csp_x",
                                headers=_hdr()).json()
            pl = detail["prompt_limit"]
            assert pl["provider"] == "nano-gpt.com", pl
            assert pl["model"] == "qwen-image-3-pro", pl
            assert pl["base_url"] == "https://nano-gpt.com/api/v1", pl
            assert pl["route"] == cse.ROUTE_IMAGE_API, pl
            assert pl["mode"] == "manual" and pl["value"] == 800, pl
            assert pl["source_taxonomy"] == "manual", pl
            assert (detail["capabilities"]["prompt_limit"]["source_taxonomy"]
                    == "manual"), detail["capabilities"]
            # runtime: тот же effective слот/route (единственный resolver)
            meta = _run(cjobs.run_style_job(
                chat_id=0, base_image_path=str(base), profile=profile,
                summary_run_id=None, pg=pg, edit_call=_edit,
                reference_paths=[], correlation_id="cover_c11"))
            assert meta["applied"] is True, meta
            assert captured["base_url"] == pl["base_url"], captured
            assert captured["model"] == pl["model"], captured
            assert meta["edit_route"] == pl["route"] == cse.ROUTE_IMAGE_API
    finally:
        hot_config.set_config_cache(None)
        cap.reset_cache()


def test_cover12_prompt_limit_unknown_one_shorter_retry(
        tmp_path, monkeypatch):
    """T-4875: 400-too-long без числа → `prompt_limit_unknown`; ровно один
    shorter retry (P2 refs/brief сброшены, P0/P1 сохранены)."""
    cap.reset_cache()
    _nanogpt_slot_stub(monkeypatch)
    base = tmp_path / "c12_base.png"
    base.write_bytes(PNG_BYTES)
    profile = _profile(references=[{
        "ref_id": "r1", "asset_id": "cas_r", "label": "REF-UNIQUE-LABEL",
        "description": "уникальное описание референса", "ordering": 0}])
    prompts: list = []

    async def edit_call(prompt, **_kw):
        prompts.append(prompt)
        if len(prompts) == 1:
            return EditResult(ok=False, reason="prompt_limit_unknown",
                              meta={"prompt_limit_unknown": True,
                                    "route": "image_api"})
        return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

    try:
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=str(base), profile=profile,
            summary_run_id=None, edit_call=edit_call, reference_paths=[],
            summary_text="Сюжетная фраза для краткого брифа. Вторая фраза."))
        assert len(prompts) == 2, "ровно один bounded retry"
        assert len(prompts[1]) < len(prompts[0]), "retry реально короче"
        assert "ВЫПУСК" in prompts[1]
        assert profile["instruction"] in prompts[1]
        assert "REF-UNIQUE-LABEL" not in prompts[1], "P2 refs не сброшены"
        assert "Сюжетная фраза" not in prompts[1], "P2 brief не сброшен"
        assert meta["applied"] is True, meta
        retry = meta.get("prompt_limit_unknown_retry") or {}
        assert retry.get("retry_sent") is True, retry
    finally:
        cap.reset_cache()


def test_cover12b_prompt_limit_unknown_after_retry_honest_reason(
        tmp_path, monkeypatch):
    """Повторный too-long после сокращения → `prompt_limit_unknown_after_retry`
    (не generic `bad_request`), второй retry не отправляется."""
    cap.reset_cache()
    _nanogpt_slot_stub(monkeypatch)
    base = tmp_path / "c12b.png"
    base.write_bytes(PNG_BYTES)
    profile = _profile(references=[{
        "ref_id": "r1", "asset_id": "cas_r", "label": "REF-UNIQUE-LABEL",
        "description": "уникальное описание референса", "ordering": 0}])
    prompts: list = []

    async def edit_call(prompt, **_kw):
        prompts.append(prompt)
        return EditResult(ok=False, reason="prompt_limit_unknown",
                          meta={"prompt_limit_unknown": True})

    try:
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=str(base), profile=profile,
            summary_run_id=None, edit_call=edit_call, reference_paths=[],
            summary_text="Сюжетная фраза для краткого брифа. Вторая фраза."))
        assert len(prompts) == 2, "скрытого multi-paid loop нет"
        assert meta["applied"] is False
        assert meta["fail_reason"] == "prompt_limit_unknown_after_retry", meta
        assert meta["outcome"] == cjobs.RESULT_BASE
    finally:
        cap.reset_cache()


def test_cover12c_prompt_limit_unknown_no_oversized_resend(
        tmp_path, monkeypatch):
    """Если сократить нечего (нет P2/P3) — paid retry НЕ отправляется."""
    cap.reset_cache()
    _nanogpt_slot_stub(monkeypatch)
    base = tmp_path / "c12c.png"
    base.write_bytes(PNG_BYTES)
    profile = _profile()          # без references, без brief
    prompts: list = []

    async def edit_call(prompt, **_kw):
        prompts.append(prompt)
        return EditResult(ok=False, reason="prompt_limit_unknown",
                          meta={"prompt_limit_unknown": True})

    try:
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=str(base), profile=profile,
            summary_run_id=None, edit_call=edit_call, reference_paths=[]))
        assert len(prompts) == 1, "oversized/identical resend запрещён"
        retry = meta.get("prompt_limit_unknown_retry") or {}
        assert retry.get("retry_sent") is False, retry
        assert retry.get("skipped") == "not_shorter", retry
        assert meta["fail_reason"] == "prompt_limit_unknown"
    finally:
        cap.reset_cache()


def test_cover12e_known_retry_then_unknown_failure_no_third_call(
        tmp_path, monkeypatch):
    """T-4875: known-N retry, который снова упал как too-long (уже без числа)
    — ровно 2 paid call, третьего нет (≤1 invariant, нет скрытого loop)."""
    cap.reset_cache()
    _nanogpt_slot_stub(monkeypatch)
    base = tmp_path / "c12e.png"
    base.write_bytes(PNG_BYTES)
    profile = _profile(references=[{
        "ref_id": "r1", "asset_id": "cas_r", "label": "REF-UNIQUE-LABEL",
        "description": "уникальное описание референса", "ordering": 0}])
    caps_unknown = cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit())
    probe = cjobs.compile_style_prompt(
        profile, issue_display="ВЫПУСК 11", capabilities=caps_unknown)
    limit = int(probe.static_len) + 5
    prompts: list = []

    async def edit_call(prompt, **_kw):
        prompts.append(prompt)
        if len(prompts) == 1:
            return EditResult(ok=False, reason="prompt_limit",
                              meta={"prompt_limit": {"value": limit,
                                                     "unit": "chars"},
                                    "route": "image_api"})
        return EditResult(ok=False, reason="prompt_limit_unknown",
                          meta={"prompt_limit_unknown": True})

    try:
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=str(base), profile=profile,
            summary_run_id=None, edit_call=edit_call, reference_paths=[],
            summary_text="Сюжетная фраза для краткого брифа. Вторая фраза."))
        assert len(prompts) == 2, "third call запрещён (≤1 extra call)"
        assert meta["applied"] is False
        assert meta["fail_reason"] in ("prompt_limit_unknown",
                                       "prompt_limit"), meta
        assert meta["fail_reason"] != "bad_request"
    finally:
        cap.reset_cache()


def test_cover12d_edit_400_too_long_classification(tmp_path):
    """T-4875: 400 «too long» без числа → `prompt_limit_unknown`; с числом
    в тексте ошибки → machine-readable `prompt_limit` (runtime_exact)."""
    from services import cover_style_edit as cse
    base = tmp_path / "c12d.png"
    base.write_bytes(PNG_BYTES)
    caps = cap.ImageModelCapabilities(image_edit=cap.TRUE, max_input_images=3)

    class _Resp:
        def __init__(self, text):
            self.status_code = 400
            self.text = text

        def json(self):
            return {"error": {"message": self.text}}

    calls = {"resp": _Resp(
        "Your prompt is too long for Qwen Image 3 Pro. Please shorten")}

    async def _transport(_url, _payload, _headers, _timeout):
        return calls["resp"]

    res = _run(cse.edit_image(
        "p", base_image_path=str(base), reference_paths=[],
        base_url="https://nano-gpt.com/api/v1", model="qwen-image-3-pro",
        capabilities=caps, transport=_transport, route=cse.ROUTE_IMAGE_API))
    assert res.reason == "prompt_limit_unknown", (res.reason, res.meta)
    assert res.meta.get("provider_error", {}).get("status") == 400
    # provider явно сообщил число → machine-readable limit (не unknown)
    calls["resp"] = _Resp(
        "Please shorten the prompt to 800 characters or less")
    res2 = _run(cse.edit_image(
        "p", base_image_path=str(base), reference_paths=[],
        base_url="https://nano-gpt.com/api/v1", model="qwen-image-3-pro",
        capabilities=caps, transport=_transport, route=cse.ROUTE_IMAGE_API))
    assert res2.reason == "prompt_limit", (res2.reason, res2.meta)
    assert res2.meta.get("prompt_limit", {}).get("value") == 800


def test_cover13_adaptive_retry_records_runtime_safe_ceiling(
        tmp_path, monkeypatch):
    """T-4875/T-4874: успешный adaptive retry пишет route-specific
    `learned_safe_ceiling` c source `runtime_safe` (НЕ exact provider max)."""
    cap.reset_cache()
    _nanogpt_slot_stub(monkeypatch)
    base = tmp_path / "c13.png"
    base.write_bytes(PNG_BYTES)
    profile = _profile(references=[{
        "ref_id": "r1", "asset_id": "cas_r", "label": "REF-UNIQUE-LABEL",
        "description": "уникальное описание референса", "ordering": 0}])
    prompts: list = []
    captured: dict = {}

    async def edit_call(prompt, **kw):
        prompts.append(prompt)
        captured.update(kw)
        if len(prompts) == 1:
            return EditResult(ok=False, reason="prompt_limit_unknown",
                              meta={"prompt_limit_unknown": True})
        return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

    try:
        meta = _run(cjobs.run_style_job(
            chat_id=0, base_image_path=str(base), profile=profile,
            summary_run_id=None, edit_call=edit_call, reference_paths=[],
            summary_text="Сюжетная фраза для краткого брифа. Вторая фраза."))
        ceiling = len(prompts[1])
        retry = meta.get("prompt_limit_unknown_retry") or {}
        assert retry.get("learned_safe_ceiling") == ceiling, retry
        assert retry.get("ceiling_source") == "runtime_safe", retry
        route = meta.get("edit_route") or ""
        got = cap.resolve_capabilities(
            meta["provider"], captured["base_url"], meta["model"],
            route=route or None, operation=cap.OPERATION_EDIT)
        assert got.prompt_limit.value == ceiling
        assert got.prompt_limit.source == cap.SOURCE_RUNTIME_SAFE
        assert cap.prompt_limit_source_taxonomy(got.prompt_limit.source) \
            == "learned_safe_ceiling"
        assert cap.prompt_limit_is_exact("learned_safe_ceiling") is False
        # другой route не получает чужой learned ceiling
        other = cap.resolve_capabilities(
            meta["provider"], captured["base_url"], meta["model"],
            route="image_edits", operation=cap.OPERATION_EDIT)
        assert other.prompt_limit.value != ceiling
    finally:
        cap.reset_cache()


def test_e2e_rc_a_negative_control_old_store_base_would_404(
        pg, tmp_path, monkeypatch, job_db):
    """Pre-fix proof RC-A: старая `_store_base` (без registry.upsert_asset)
    даёт completed job с CAS-файлом без PG-строки → authenticated GET before
    = 404. Именно это утверждение ловит RC-A в E2E (RED на pre-fix коде)."""
    captured = {}
    _patch_base_and_stage(monkeypatch, tmp_path, captured)
    assert _run(registry.upsert_profile(pg, _profile(revision=1)))

    from services import cover_style_assets as assets
    from services import cover_style_preview as preview_mod

    async def _old_store_base(pg_, path):
        data = preview_mod._read_bytes(path)
        if not data:
            return None
        return assets.store_file_bytes(
            data, filename="test_base.png", origin="generated_preview")

    monkeypatch.setattr(preview_mod, "_store_base", _old_store_base)
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        snap = _poll_job(client, r.json()["job_id"])
        assert snap["status"] == "completed", snap
        stored = _run(registry.get_profile_with_refs(pg, "csp_x"))
        # pair формально «текущая» (как в prod 2.58.50), но before не отдаётся
        assert registry.preview_pair_current(stored) is True
        assert client.get(snap["preview_after_url"],
                          headers=_hdr()).status_code == 200
        assert client.get(snap["preview_before_url"],
                          headers=_hdr()).status_code == 404, \
            "negative control не воспроизвёл RC-A"
