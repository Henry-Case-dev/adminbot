"""ASAP 4.3 (T-4844…T-4848, §14 targeted) — хирургический corrective pass:
durable preview job stages, reference chain в edit request, observed/manual
prompt-limit, placeholders endpoint, fail-soft ladder.

Запуск (точечно, без полного suite):
    pytest tests/test_asap43_cover_style_surgical.py -q
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import cover_style_edit
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
SEED_DIR = ROOT / "extra_images"
TEST_TOKEN = "123456:ASAP43_TOKEN"
ADMIN_ID = 111222

# ASAP 4.3 — прод-дефолты (snapshot/diagnostics ON), не legacy-контур.
pytestmark = pytest.mark.asap4


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── temp-SQLite asyncpg-compatible shim (тот же контур, что step3) ──────────

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
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


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


def _profile(**over):
    p = {
        "profile_id": "csp_x", "name": "Test", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": True, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 3,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


# ── §2.2/§11: stages проходят (durable job) ─────────────────────────────────

def test_status_stages_progress_through_durable_job(
        pg, tmp_path, monkeypatch, job_db):
    base = tmp_path / "b.png"
    base.write_bytes(PNG_BYTES)
    styled = tmp_path / "s.jpg"
    styled.write_bytes(b"STYLED")
    edit_gate = asyncio.Event()
    base_gate = asyncio.Event()
    loop_holder = {}

    async def _slow_edit(**kw):
        loop_holder["loop"] = asyncio.get_running_loop()
        await edit_gate.wait()
        return {"applied": True, "reason": "", "styled_path": str(styled),
                "model": "m1", "provider": "p1"}

    async def _slow_base(*a, **kw):
        loop_holder["loop"] = asyncio.get_running_loop()
        await base_gate.wait()
        return (str(base), "ok")

    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose", _slow_base)
    monkeypatch.setattr("services.cover_style_jobs.run_style_job", _slow_edit)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=_profile()))
    monkeypatch.setattr("services.cover_style_registry.upsert_asset",
                        AsyncMock(return_value=True))
    monkeypatch.setattr("services.cover_style_registry.set_preview",
                        AsyncMock(return_value=True))
    seen = set()
    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        # base generation gated → стадия base_generating наблюдаема
        deadline = time.time() + 10
        while time.time() < deadline:
            snap = client.get("/api/cover/test-style/" + jid,
                              headers=_hdr()).json()
            seen.add(snap["stage"])
            if snap["stage"] == "base_generating":
                break
            time.sleep(0.03)
        assert "base_generating" in seen, seen
        loop_holder["loop"].call_soon_threadsafe(base_gate.set)
        deadline = time.time() + 10
        while time.time() < deadline:
            snap = client.get("/api/cover/test-style/" + jid,
                              headers=_hdr()).json()
            seen.add(snap["stage"])
            if snap["stage"] in ("base_ready", "style_editing"):
                break
            time.sleep(0.03)
        assert "base_ready" in seen, seen
        loop_holder["loop"].call_soon_threadsafe(edit_gate.set)
        deadline = time.time() + 10
        while time.time() < deadline:
            snap = client.get("/api/cover/test-style/" + jid,
                              headers=_hdr()).json()
            seen.add(snap["stage"])
            if snap["status"] in ("completed", "failed"):
                break
            time.sleep(0.03)
    assert snap["status"] == "completed"
    assert "completed" in seen
    assert snap["stage"] == "completed"
    assert snap["preview_before_url"] and snap["preview_after_url"]


# ── Canary A fix: base-ассет preview обязан отдаваться UI (PG-регистрация) ──

def test_preview_base_asset_registered_and_fetchable(
        pg, tmp_path, monkeypatch, job_db):
    """Prod canary A 04.10.2026 (2.58.50): base сохранялся в CAS без строки
    `cover_style_assets` → `GET /cover/assets/{before_id}` = 404 → UI терял
    «До». Здесь реальный registry (без моков `upsert_asset`/`set_preview`)."""
    base = tmp_path / "b.png"
    base.write_bytes(PNG_BYTES)
    styled = tmp_path / "s.jpg"
    styled.write_bytes(b"STYLED")

    async def _base(*a, **kw):
        return (str(base), "ok")

    async def _edit(**kw):
        return {"applied": True, "reason": "", "styled_path": str(styled),
                "model": "m1", "provider": "p1"}

    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose", _base)
    monkeypatch.setattr("services.cover_style_jobs.run_style_job", _edit)
    assert _run(registry.upsert_profile(pg, _profile()))

    with _client(pg) as client:
        r = client.post("/api/cover/test-style", headers=_hdr(),
                        json={"profile_id": "csp_x"})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        deadline = time.time() + 10
        snap = None
        while time.time() < deadline:
            snap = client.get("/api/cover/test-style/" + jid,
                              headers=_hdr()).json()
            if snap["status"] in ("completed", "failed"):
                break
            time.sleep(0.03)
        assert snap["status"] == "completed", snap
        before_id = snap["preview_before_url"].rsplit("/", 1)[-1]
        after_id = snap["preview_after_url"].rsplit("/", 1)[-1]

        stored = _run(registry.get_profile_with_refs(pg, "csp_x"))
        assert stored["preview_before_asset_id"] == before_id
        assert stored["preview_after_asset_id"] == after_id
        assert stored["preview_revision"] == stored["revision"]
        assert registry.preview_pair_current(stored) is True

        # before-ассет зарегистрирован в PG и реально отдаётся API/UI.
        base_row = _run(registry.get_asset(pg, before_id))
        assert base_row is not None, "base asset не зарегистрирован в PG"
        assert Path(base_row["disk_path"]).exists()
        assert client.get("/api/cover/assets/" + before_id,
                          headers=_hdr()).status_code == 200
        assert client.get("/api/cover/assets/" + after_id,
                          headers=_hdr()).status_code == 200


# ── §6/T-4846: Medved reference реально resolved и уходит в edit request ────

def test_medved_reference_chain_into_edit_request(pg, monkeypatch, tmp_path):
    from services import cover_style_pipeline as pipeline
    from services import hot_config
    slot_values = {
        pipeline.KEY_STYLE_BASE_URL: "https://provider.test/v1",
        pipeline.KEY_STYLE_MODEL: "edit-model",
    }
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: slot_values.get(key, default))
    seeded = _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
    assert seeded is not None
    profile = _run(registry.get_profile_with_refs(pg, "medved_press"))
    ref = profile["references"][0]
    # asset row → disk read → MIME/signature (integrity §45)
    details = _run(preview_jobs.jobs._resolve_reference_details(pg, profile))
    assert details and details[0]["db_row"] is True
    assert details[0]["file"] is True
    assert details[0]["mime_ok"] is True
    assert details[0]["readable"] is True
    assert details[0]["bytes"] == (SEED_DIR / "medved_press.png").stat().st_size
    ref_path = details[0]["path"]
    # Durable-хранилище — CAS (`<asset_id><ext>`, round1028 §3.6): basename
    # отличается, но содержимое обязано БЫТЬ байтами medved_press.png, а не
    # placeholder'а. Проверяем sha исходника, не имя CAS-файла.
    ref_bytes = Path(ref_path).read_bytes()
    assert hashlib.sha256(ref_bytes).hexdigest() == hashlib.sha256(
        (SEED_DIR / "medved_press.png").read_bytes()).hexdigest()
    assert "style_example" not in Path(ref_path).name

    captured = {}

    async def edit_call(prompt, **kw):
        captured.update(kw)
        return EditResult(ok=True, content=b"STYLED", reason="ok")

    base = tmp_path / "base.png"
    base.write_bytes(PNG_BYTES)
    cap.reset_cache()
    meta = _run(preview_jobs.jobs.run_style_job(
        chat_id=0, base_image_path=str(base), profile=profile,
        summary_run_id=None, pg=pg, edit_call=edit_call))
    assert meta["applied"] is True
    assert captured.get("reference_paths") == [ref_path], \
        "medved_press.png реально передан в edit"
    # reference не подменён placeholder'ом
    assert "style_example" not in " ".join(captured["reference_paths"])
    payload = cover_style_edit.build_edit_payload(
        "p", model="edit-model", image_paths=captured["reference_paths"])
    assert payload["input_references"], "edit request содержит reference"
    # сигнатура медиафайла — настоящий PNG
    assert cover_style_edit._mime_for(ref_path) == "image/png"


def test_seeded_reference_survives_reload(pg):
    _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
    pg2 = _SqlitePg(pg.path)
    profile = _run(registry.get_profile_with_refs(pg2, "medved_press"))
    assert profile["references"], "reference переживает reload"
    asset = _run(registry.get_asset(pg2, profile["references"][0]["asset_id"]))
    assert asset is not None and Path(asset["disk_path"]).exists()
    assert asset["filename"] == "medved_press.png"


# ── §7.1/§14-10/11: observed limit + unknown не блокирует ───────────────────

def test_observed_numeric_limit_persisted_per_route():
    cap.reset_cache()
    cap.record_runtime_limit("nanogpt", "https://n.test/v1", "m1",
                             "image_api", 1234, "chars")
    got = cap.resolve_capabilities("nanogpt", "https://n.test/v1", "m1",
                                   route="image_api")
    assert got.prompt_limit.value == 1234
    assert got.prompt_limit.source == cap.SOURCE_RUNTIME_DISCOVERED
    # другой route — не получает чужой observed limit
    other = cap.resolve_capabilities("nanogpt", "https://n.test/v1", "m1",
                                     route="image_edits")
    assert other.prompt_limit.value is None
    # другой model/base_url — тоже
    other_model = cap.resolve_capabilities("nanogpt", "https://n.test/v1",
                                           "m2", route="image_api")
    assert other_model.prompt_limit.value is None
    cap.reset_cache()


def test_prompt_too_long_without_number_stays_unknown():
    assert cap.extract_prompt_limit("prompt too long") is None
    assert cap.extract_prompt_limit("maximum prompt length is 800") == (
        800, "chars")


def test_unknown_limit_does_not_pre_block(tmp_path, monkeypatch):
    # Конфигурируемый слот (в проде edit без connection не уходит — §36);
    # проверяем именно prompt-limit: unknown НЕ блокирует отправку.
    from services import cover_style_pipeline as pipeline
    from services import hot_config
    slot_values = {
        pipeline.KEY_STYLE_BASE_URL: "https://provider.test/v1",
        pipeline.KEY_STYLE_MODEL: "edit-model",
    }
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: slot_values.get(key, default))
    base = tmp_path / "b.png"
    base.write_bytes(PNG_BYTES)
    prompts = []

    async def edit_call(prompt, **kw):
        prompts.append(prompt)
        return EditResult(ok=True, content=b"S", reason="ok")

    caps = cap.ImageModelCapabilities(image_edit=cap.TRUE,
                                      max_input_images=3,
                                      prompt_limit=cap.PromptLimit())
    meta = _run(preview_jobs.jobs.run_style_job(
        chat_id=0, base_image_path=str(base), profile=_profile(),
        summary_run_id=None, capabilities=caps, edit_call=edit_call,
        reference_paths=[]))
    assert meta["applied"] is True
    assert meta["prompt_diagnostics"]["resolved_limit"] is None
    assert meta["prompt_diagnostics"]["exceeded"] is False
    assert len(prompts) == 1, "unknown limit не блокирует отправку"
    assert "Сделай обложку в стиле серии" in prompts[0]


def test_no_hardcoded_800_in_new_runtime():
    for rel in ("services/cover_style_preview.py",
                "web/api/cover_styles.py",
                "services/cover_style_jobs.py",
                "services/cover_style_registry.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == 800:
                pytest.fail(f"hardcoded 800 in {rel}:{node.lineno}")


# ── §5: placeholders endpoint (read-only extra_images) ──────────────────────

def test_placeholders_endpoint_serves_actual_files(pg):
    files = registry.placeholder_files(SEED_DIR)
    with _client(pg) as client:
        for name in files.values():
            resp = client.get(f"/api/cover/placeholders/{name}",
                              headers=_hdr())
            assert resp.status_code == 200
            assert resp.content == (SEED_DIR / name).read_bytes()
        bad = client.get("/api/cover/placeholders/../app.js", headers=_hdr())
        assert bad.status_code == 404
        unknown = client.get("/api/cover/placeholders/nope.png",
                             headers=_hdr())
        assert unknown.status_code == 404


# ── DoD-22: fail-soft ladder styled→base→Rich→plain не сломан ───────────────

def test_fallback_ladder_intact():
    assert preview_jobs.jobs.classify_cover_result(
        published_channel="rich",
        cover_outcome="styled")["cover_result"] == "styled"
    base = preview_jobs.jobs.classify_cover_result(
        published_channel="rich", cover_outcome="base",
        cover_reason="style_failed")
    assert base["cover_result"] == "base" and base["fallback"] == \
        "style_failed"
    richless = preview_jobs.jobs.classify_cover_result(
        published_channel="rich", cover_outcome="none",
        cover_reason="base_failed")
    assert richless["cover_result"] == "none"
    plain = preview_jobs.jobs.classify_cover_result(
        published_channel="plain", cover_outcome="base")
    assert plain["publication"] == "plain_send_message"
    assert plain["reason"] == "rich_failed"
