"""ASAP 5 web-slice (T-5252/T-5253, D7/D17) — CoverPromptManifest в ответе
СУЩЕСТВУЮЩЕГО job-endpoint'а /api/cover/test-style/{job_id}.

Контракт (spec D7: «чтение — только admin-authorized существующие API,
расширение ответов, не новые роуты»):
  - глобальный админ: полный манифест (include_prompt=True): компоненты,
    attempts с полными строками, prompt_hash;
  - не-админ (роль user, право access): ключа `prompt_manifest` в ответе
    НЕТ вообще — fail-closed, R17 (полные тексты не покидают evidence);
  - нет манифеста — ключа нет даже у админа (UI прячет блок, не «пусто»).
routes.py НЕ затрагивается (байт-пин 8153b8bd…, Δ=0 эндпоинтов).

Запуск: .venv\\Scripts\\python.exe -m pytest tests/test_asap5_cover_manifest_web.py -q
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import cover_style_jobs as cjobs
from services import cover_style_preview as preview_jobs
from services import cover_prompt_assembly as cpa
from services import lore_runtime
from services.config_cache import ConfigCache
from services.database import DatabaseService
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api.cover_styles import cover_styles_router

ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN = "123456:ASAP5_WEB_TOKEN"
ADMIN_ID = 111222
USER_ID = 444555

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_asap42_step3_style_integration import (  # noqa: E402
    _SqlitePg,
    create_schema,
    make_init_data,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


RUNTIME_TEXT = cpa.runtime_invariants_text("ВЫПУСК 11")
FINAL_PROMPT = (RUNTIME_TEXT
                + " Чёрно-белый минимализм 1970-х. Кот сидит на крыше и "
                  "смотрит на город. Тема готовый текст выпуска")

MANIFEST = cpa.build_style_manifest(
    issue_display="ВЫПУСК 11",
    instruction="Сделай обложку в стиле серии, не дублируй элементы.",
    base_style_prompt="Чёрно-белый минимализм 1970-х",
    refs_text="логотип сверху",
    ref_roles_text="логотип",
    story_scene="Кот сидит на крыше и смотрит на город.",
    context_text="Тема готовый текст выпуска",
    final_prompt=FINAL_PROMPT,
    provider="nano-gpt.com", model="seedream-4", route="style_edit",
    resolved_limit=1000, limit_unit="chars",
    limit_source="capability_registry",
    attempts=[{"attempt": 1, "prompt": FINAL_PROMPT, "outcome": "sent",
               "reason": ""}],
)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        type("S", (), {"API_TOKEN": TEST_TOKEN})())


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)


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


def _cache(pg, *, admin: bool) -> ConfigCache:
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    cache._roles = {
        "admin": {"permissions": {"wildcard": True},
                  "is_custom": False, "role_type": "global_admin"},
    }
    cache._permissions = {"admin": Permissions.from_dict({"wildcard": True})}
    if admin:
        cache._admins = {ADMIN_ID: "admin"}
    else:
        # роль user с секцией access, БЕЗ global_admin/wildcard —
        # endpoint достижим, манифест скрыт (fail-closed).
        cache._roles["user"] = {"permissions": {"sections": ["access"]},
                                "is_custom": False, "role_type": "user"}
        cache._permissions["user"] = Permissions.from_dict(
            {"sections": ["access"]})
        cache._admins = {}
    cache._pg_available = True
    cache._initialized = True
    cache._pg = pg
    return cache


def _client(pg, *, admin: bool, user_id: int) -> TestClient:
    app = FastAPI()
    app.state.cache = _cache(pg, admin=admin)
    app.include_router(cover_styles_router, prefix="/api")
    return TestClient(app)


def _hdr(user_id: int = ADMIN_ID):
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user_id)}


def _completed_preview_job(db, *, with_manifest: bool) -> str:
    started, _state = _run(cjobs.begin_cover_job(
        db, chat_id=0, correlation_id="asap5-web-slice",
        style_id="csp_x", summary_run_id=None,
        payload={"mode": preview_jobs.MODE_PREVIEW,
                 "profile_id": "csp_x", "kind": preview_jobs.KIND_PREVIEW},
        kind=preview_jobs.KIND_PREVIEW,
        initial_state=cjobs.STATE_CREATED))
    assert started
    jid = str(started)
    state = cjobs.CoverJobState(style_id="csp_x",
                                mode=preview_jobs.MODE_PREVIEW,
                                provider="nano-gpt.com", model="seedream-4")
    state.mark(cjobs.STATE_STYLE_SUCCEEDED)
    if with_manifest:
        state.prompt_manifest = MANIFEST
    assert _run(cjobs.save_cover_state(db, jid, state))
    assert _run(cjobs.finish_cover_job(db, jid, outcome=cjobs.RESULT_STYLED,
                                       checkpoint=state))
    return jid


def test_admin_gets_full_manifest(pg, job_db):
    """Глобальный админ видит В ТОЧНОСТИ что отправилось: компоненты +
    attempts с полными строками + hash (D7)."""
    jid = _completed_preview_job(job_db, with_manifest=True)
    client = _client(pg, admin=True, user_id=ADMIN_ID)
    resp = client.get("/api/cover/test-style/" + jid, headers=_hdr(ADMIN_ID))
    assert resp.status_code == 200, resp.text
    snap = resp.json()
    m = snap.get("prompt_manifest")
    assert isinstance(m, dict), "админ получает манифест"
    assert len(m["components"]) == 6
    keys = {c["key"] for c in m["components"]}
    assert keys == {"RUNTIME_INVARIANTS", "STYLE_PROFILE", "BASE_STYLE",
                    "REFERENCES", "STORY_SCENE", "SUMMARY_CONTEXT"}
    assert m["final_prompt"] == FINAL_PROMPT, "include_prompt=True"
    assert m["prompt_hash"] == MANIFEST["prompt_hash"]
    assert m["attempts"][0]["prompt"] == FINAL_PROMPT
    assert m["limit_source"] == "capability_registry"
    # фактическая сборка: runtime-инварианты и сюжет дошли
    by_key = {c["key"]: c for c in m["components"]}
    assert by_key["RUNTIME_INVARIANTS"]["status"] == "kept"
    assert by_key["STORY_SCENE"]["status"] == "kept"


def test_non_admin_gets_no_manifest_key(pg, job_db):
    """R17 fail-closed: не-админ получает 200 и НЕТ ключа prompt_manifest —
    ни полного, ни «пустого»."""
    jid = _completed_preview_job(job_db, with_manifest=True)
    client = _client(pg, admin=False, user_id=USER_ID)
    resp = client.get("/api/cover/test-style/" + jid, headers=_hdr(USER_ID))
    assert resp.status_code == 200, resp.text
    snap = resp.json()
    assert "prompt_manifest" not in snap, snap.get("prompt_manifest")
    # базовый снимок статуса при этом жив (обратная совместимость UI)
    assert snap.get("status") == "completed"


def test_admin_without_manifest_gets_no_key(pg, job_db):
    """Нет манифеста — ключа нет даже у админа (UI прячет блок)."""
    jid = _completed_preview_job(job_db, with_manifest=False)
    client = _client(pg, admin=True, user_id=ADMIN_ID)
    resp = client.get("/api/cover/test-style/" + jid, headers=_hdr(ADMIN_ID))
    assert resp.status_code == 200, resp.text
    assert "prompt_manifest" not in resp.json()


def test_routes_py_untouched():
    """Пин цел: routes.py не содержит web-слайс дельты (Δ=0 эндпоинтов)."""
    src = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
    assert "prompt_manifest" not in src
    assert "job_manifest" not in src
