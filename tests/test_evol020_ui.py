"""EVOL-020 (Wave 4 UI) — цепочка опыта: HTTP-слой и витрина.

TEST-LIFECYCLE: CONTRACT owner=EVOL-020

Сервисный контракт (реальные таблицы/события) проверяется в
`tests/test_evol020_experience_pipeline.py`. Здесь — то, что видит админка:
  * эндпоинт отдаёт 8 стадий в порядке сервера, реальные отметки времени,
    окна 24ч/7д/30д, причины пропусков и классификатор состояния;
  * подписи состояний — С СЕРВЕРА (UI не рисует «работает» там, где
    downstream мёртв: кандидаты без проверки → idle + честная причина);
  * RBAC: не-админ 403, недоступная БД 503; чужой чат не подменяет срез;
  * витрина: стадии с раскрываемой причиной и ссылками только при реальных
    счётчиках; вёрстка не содержит собственного «зелёного» правила.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services import experience_diagnostics as exp_diag
from tests.test_webapp_api import ADMIN_ID, USER_ID, _FakeConn, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "/api/experience/pipeline"
CHAT_A = -100111
CHAT_B = -100222
LOCAL_ADMIN_ID = 424242424


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    conn = _FakeConn(
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-10-30T00:00:00+00:00"},
        ],
    )
    from services.config_cache import ConfigCache
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        tc.cache = cache
        yield tc


def _payload(*, state="idle", reason="lessons_proposed_only",
             stages=None) -> dict:
    """Реалистичный снимок, собранный БОЕВЫМИ хелперами сервиса."""
    now = 1_800_000_000
    built = stages or {
        "candidate": exp_diag._stage(
            key="candidate", enabled=True,
            counters={"total": 2, "windows": {"24h": 2, "7d": 2, "30d": 2}},
            last_run_at=now - 600, last_success_at=now - 600,
            skip_reasons=[{"event": "lesson_proposed",
                           "reason_code": "no_evidence",
                           "last_ts": now - 600, "count_window": 2}]),
        "validation": exp_diag._stage(
            key="validation", enabled=True,
            counters={"total": 0, "windows": {"24h": 0, "7d": 0, "30d": 0}},
            last_run_at=None, last_success_at=None),
    }
    order = list(exp_diag.PIPELINE_STAGES)
    for key in order:
        built.setdefault(key, exp_diag._stage(
            key=key, enabled=True,
            counters={"total": 0, "windows": {"24h": 0, "7d": 0, "30d": 0}},
            last_run_at=None, last_success_at=None))
    return {
        "scope": "global", "chat_id": None, "generated_at": now,
        "enabled": True,
        "gates": {"lessons_enabled": True, "review_enabled": True,
                  "context_enabled": True, "feedback_enabled": True},
        "cadence": {"name": "daily", "seconds": 86400},
        "state": state,
        "state_label": exp_diag.STATE_LABELS[state],
        "reason": reason,
        "reason_label": exp_diag.REASON_LABELS[reason],
        "evidence": {},
        "job": {"kind": "experience.review", "active": False},
        "stages": built, "order": order,
        "definitions": {"states": dict(exp_diag.STATE_LABELS),
                        "reasons": dict(exp_diag.REASON_LABELS)},
        "counters": {"lessons": {"candidate": 2}, "applications_total": 0},
    }


def test_missing_auth_is_401(client):
    assert client.get(ENDPOINT).status_code == 401


def test_non_admin_is_403(client):
    assert client.get(ENDPOINT, headers=_hdr(USER_ID)).status_code == 403


def test_unavailable_db_is_503(client, monkeypatch):
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
    resp = client.get(ENDPOINT, headers=_hdr())
    assert resp.status_code == 503


def test_eight_stages_with_windows_and_server_labels(client, monkeypatch):
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())

    async def _snapshot(db, *, chat_id=None):
        return _payload()

    async def _reasons(db, *, chat_id=None):
        return {"items": [{"event": "lesson_proposed",
                           "count_window": 2, "windows": {"7d": 2},
                           "last_ts": 1_799_999_400,
                           "last_outcome": "success",
                           "last_reason": "no_evidence"}],
                "window_seconds": 604800}

    monkeypatch.setattr(exp_diag, "experience_pipeline_snapshot", _snapshot)
    monkeypatch.setattr(exp_diag, "experience_pipeline_reasons", _reasons)
    resp = client.get(ENDPOINT, headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["order"] == list(exp_diag.PIPELINE_STAGES)
    assert len(body["order"]) == 8
    for key in body["order"]:
        stage = body["stages"][key]
        assert set(stage["windows"]) == {"24h", "7d", "30d"}
        assert "last_run_at" in stage and "last_success_at" in stage
        assert stage["state"] in exp_diag.STATE_LABELS
        assert stage["state_label"] == exp_diag.STATE_LABELS[stage["state"]]
    # Кандидаты без проверки НЕ «работает»: честный idle + причина.
    assert body["state"] == "idle"
    assert body["reason"] == "lessons_proposed_only"
    assert body["state_label"] == exp_diag.STATE_LABELS["idle"]
    assert "Простаивает" in body["state_label"]
    assert body["stages"]["validation"]["state"] == "never_run"
    assert body["stages"]["candidate"]["skip_reasons"]
    # Причины по стадиям приходят отдельным списком (раскрытие в UI).
    assert body["reason_details"][0]["event"] == "lesson_proposed"
    assert body["reasons_window_seconds"] == 604800


def test_chat_scope_is_respected(client, monkeypatch):
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())
    seen = {}

    async def _snapshot(db, *, chat_id=None):
        seen["chat_id"] = chat_id
        return _payload()

    async def _reasons(db, *, chat_id=None):
        return {"items": [], "window_seconds": 604800}

    monkeypatch.setattr(exp_diag, "experience_pipeline_snapshot", _snapshot)
    monkeypatch.setattr(exp_diag, "experience_pipeline_reasons", _reasons)

    # Свой чат (global admin) — срез этого чата.
    assert client.get(ENDPOINT, headers={**_hdr(), "X-Chat-Id": str(CHAT_A)}
                      ).status_code == 200
    assert seen["chat_id"] == CHAT_A


def test_scope_helper_never_returns_foreign_chat(monkeypatch):
    """Чужой чат не превращается в срез: helper отдаёт None (прецедент
    `/api/status`). Проверяется напрямую — эндпоинт доступен только
    глобальному админу, поэтому утечка возможна именно в резолвере."""
    from services.permissions import Permissions
    from services.roles import AccessCtx

    async def access_for(telegram_id, chat_id=None, cache=None):
        return AccessCtx(
            role_global="user", role_chat=None,
            perms_global=Permissions.from_dict({}),
            perms_chat=Permissions.from_dict({}),
            is_global_admin=False, is_local_admin=False, rank=1)

    monkeypatch.setattr(routes_mod.roles_srv, "access_for", access_for)
    import asyncio
    ctx = SimpleNamespace(id=LOCAL_ADMIN_ID)
    resolved = asyncio.run(routes_mod._scoped_chat_or_none(
        SimpleNamespace(), ctx, None, str(CHAT_B)))
    assert resolved is None
    # Нет контекста вовсе — глобальный слой (не «чужой чат»).
    assert asyncio.run(routes_mod._scoped_chat_or_none(
        SimpleNamespace(), ctx, None, None)) is None


def test_ui_wiring_is_honest():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    block = html.split("data-experience-pipeline", 1)[1]
    block = block.split("data-experience-windows", 1)[0]
    assert "data-experience-stage" in block
    assert "data-experience-stage-state" in block
    assert "data-experience-stage-detail" in block
    assert "expStageOpen" in block
    # Подпись состояния — серверная, не локальное «работает».
    assert "st.stateLabel" in block
    assert "badge-ok" in block and "st.state === 'working'" in block
    # Нет жёстко прописанной подписи «работает» (комментарии не считаются).
    assert ">работает<" not in block
    assert "'работает'" not in block
    # Ссылки на реальные уроки/применения — только при счётчиках.
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    view = js.split("expPipelineView: function ()", 1)[1]
    view = view.split("visionRecognitionView: function ()", 1)[0]
    assert "order" in view and "stages" in view
    assert "(st.total || 0) > 0" in view
    assert "loadExperiencePipeline" in js
    assert "'/api/experience/pipeline'" in js


def test_ui_replaces_bare_bars_with_stage_rows():
    """Стадии — раскрываемые строки, а не только «голые» числа окон."""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".exp-funnel" in css
    assert ".exp-stage" in css
    assert "auto-fit" in css
    block = html.split("data-experience-pipeline", 1)[1]
    block = block.split("data-experience-windows", 1)[0]
    assert "прогон:" in block and "успех:" in block
    assert "Причины исключения уроков" in block
