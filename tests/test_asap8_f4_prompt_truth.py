"""ASAP 8 F4 — Exact prompt UX (C5/C6/C7) + REV-F3 хвосты.

1.  C5 latest-mode auto-load: ``GET /api/analytics/pipeline/runs/latest``
    — server-side resolve latest run_id ТОЙ ЖЕ сортировкой, что список
    инспектора (collect_runs_list: SUMMARY_RUN_DONE ts DESC, id DESC,
    dedup по run_id); global-admin fail-closed (не-глобал → 403, C5
    негатив); include_prompt=true → detail + cover_prompts +
    cover_prompts_status; без параметра — прежний safe-ответ (ключей нет).
2.  C6: ``load_run_cover_prompts`` reason-модель — ok |
    base_manifest_missing | style_job_not_linked | style_job_failed |
    legacy_run (по durable-артефактам; absent/legacy неразличимы — честный
    общий код).
3.  C7: ``POST /api/cover/preview-compile`` mode="style" — ТОТ ЖЕ server
    compiler (compile_style_prompt, F3-контракт не меняется): parity
    финального промпта с прямым вызовом компилятора; честный no_context
    placeholder + reserved budget; fail-soft сигнал style_publish_skip_reason
    при overflow; mode invalid → 422; не-глобал → 403 (R17).
4.  REV-F3 хвосты: gap-утилиты присутствуют в подключаемом app.css;
    JS-контракты (CONTENT_PRESERVATION RU, latest-режим) — в
    tests/js/asap7_f8_cover_prompts_test.js (запуск из
    test_asap7_cover_readpath).

TEST-LIFECYCLE: CONTRACT owner=ASAP8/F4
REGRESSION owner=ASAP8/F4 (status-модель reader'а)
"""
from __future__ import annotations

import asyncio
import json
import time
import types

import pytest

# Прод-дефолты для pipeline-events (конфорт conftest: без маркера
# SUMMARY_PIPELINE_EVENTS_ENABLED выключается — collect_runs_list пуст).
pytestmark = [pytest.mark.asap4]

from services import cover_prompt_assembly as cpa
from services import cover_style_jobs as cjobs

STYLE_TEXT = "photorealistic cover, cinematic light, strict magazine grid"
STORY_TEXT = ("Медведь в цилиндре открывает Чемпионат мира по шахматам "
              "на Красной площади")
PROMPT_BASE = "STYLE-BLOCK STORY-BLOCK CONTEXT-BLOCK"


def _asyncio_run(coro):
    return asyncio.run(coro)


def _make_db(tmp_path, name="f4.sqlite3"):
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / name))
    _asyncio_run(db.initialize())
    return db


# ── 1. C6: status-модель reader'а ────────────────────────────────────────────

def _seed_style_job(db, run_id: str, *, manifest: dict | None) -> None:
    """Засеять durable cover-джобу с/без манифеста (тот же носитель, что
    production: task_jobs payload.cursor → CoverJobState)."""
    from services.cover_style_jobs import CoverJobState

    async def _seed():
        jid = await cjobs.start_cover_job(
            db, chat_id=0, correlation_id=run_id, payload={},
            coalesce_key="cover_style:%s" % run_id)
        cursor = await db.db.execute(
            "SELECT payload FROM task_jobs WHERE job_id = ?", (jid,))
        row = dict(await cursor.fetchone())
        payload = {}
        try:
            payload = json.loads(row.get("payload") or "{}")
        except (ValueError, TypeError):
            payload = {}
        state = CoverJobState(style_id="csp_f4")
        state.prompt_manifest = manifest
        payload["cursor"] = state.to_json()
        await db.db.execute(
            "UPDATE task_jobs SET payload = ? WHERE job_id = ?",
            (json.dumps(payload), jid))
        await db.db.commit()

    _asyncio_run(_seed())


def _style_manifest() -> dict:
    return cpa.build_style_manifest(
        issue_display="ВЫПУСК 2", instruction="INSTR-F4",
        base_style_prompt=STYLE_TEXT, story_scene=STORY_TEXT,
        context_text="CTX-F4", final_prompt="STYLE-SENT-F4",
        provider="prov", model="model-x", route="image_api",
        attempts=[{"attempt": 1, "prompt": "STYLE-SENT-F4",
                   "outcome": "ok", "reason": ""}])


def _base_manifest() -> dict:
    return cpa.build_base_manifest(
        base_style="STYLE-BLOCK", story_scene="STORY-BLOCK",
        summary_context="CONTEXT-BLOCK", final_prompt=PROMPT_BASE,
        provider="prov")


class TestReaderStatusModel:
    def test_both_manifests_ok(self, tmp_path):
        db = _make_db(tmp_path)
        try:
            rid = "f4-both"
            assert _asyncio_run(cjobs.record_base_cover_manifest(
                db, summary_run_id=rid, chat_id=-100,
                manifest=_base_manifest())) is True
            _seed_style_job(db, rid, manifest=_style_manifest())
            out = _asyncio_run(cjobs.load_run_cover_prompts(db, rid))
            assert out["base"] is not None and out["style"] is not None
            assert out["cover_prompts_status"] == {
                "base": "ok", "style": "ok"}
        finally:
            _asyncio_run(db.close())

    def test_base_missing_and_style_not_linked(self, tmp_path):
        """Style-манифест есть, Base-джобы нет → base_manifest_missing;
        обратный случай (Base есть, Style-джобы нет) →
        style_job_not_linked (C6, современный run без Style-стадии)."""
        db = _make_db(tmp_path)
        try:
            rid = "f4-style-only"
            _seed_style_job(db, rid, manifest=_style_manifest())
            out = _asyncio_run(cjobs.load_run_cover_prompts(db, rid))
            assert out["style"] is not None
            assert out["cover_prompts_status"] == {
                "base": "base_manifest_missing", "style": "ok"}

            rid2 = "f4-base-only"
            assert _asyncio_run(cjobs.record_base_cover_manifest(
                db, summary_run_id=rid2, chat_id=-100,
                manifest=_base_manifest())) is True
            out2 = _asyncio_run(cjobs.load_run_cover_prompts(db, rid2))
            assert out2["base"] is not None and out2["style"] is None
            assert out2["cover_prompts_status"] == {
                "base": "ok", "style": "style_job_not_linked"}
        finally:
            _asyncio_run(db.close())

    def test_style_job_failed_linked_without_manifest(self, tmp_path):
        """Style-джоба linked, манифеста в state нет → style_job_failed
        (прогон с failed Style Edit: блок не прячется — явная причина)."""
        db = _make_db(tmp_path)
        try:
            rid = "f4-style-failed"
            assert _asyncio_run(cjobs.record_base_cover_manifest(
                db, summary_run_id=rid, chat_id=-100,
                manifest=_base_manifest())) is True
            _seed_style_job(db, rid, manifest=None)
            out = _asyncio_run(cjobs.load_run_cover_prompts(db, rid))
            assert out["style"] is None
            assert out["cover_prompts_status"] == {
                "base": "ok", "style": "style_job_failed"}
        finally:
            _asyncio_run(db.close())

    def test_legacy_run_explicit_reason(self, tmp_path):
        db = _make_db(tmp_path)
        try:
            out = _asyncio_run(cjobs.load_run_cover_prompts(db, "f4-legacy"))
            assert out["base"] is None and out["style"] is None
            assert out["cover_prompts_status"] == {
                "base": "legacy_run", "style": "legacy_run"}
        finally:
            _asyncio_run(db.close())


# ── 2. C5: latest endpoint (RBAC + сортировка + контракты) ──────────────────

from fastapi.testclient import TestClient          # noqa: E402
from web.app import create_app                     # noqa: E402

from tests.test_webapp_analytics_api import (       # noqa: E402
    ADMIN_ID,
    MODERATOR_ID,
    TEST_TOKEN,
    USER_NO_ROLE,
    _FakeConn,
    _FakePg,
    _hdr,
)
from services.config_cache import ConfigCache       # noqa: E402
from web.api import deps as deps_mod                # noqa: E402


def _seed_done_event(db, run_id: str, ts: int) -> None:
    _asyncio_run(db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, trace_id, "
        "operation_id, chat_id, component, stage, reason_code, model, "
        "provider, error_json, pipeline_run_id, pipeline_type, "
        "pipeline_version, span_id, event_sequence, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, "INFO", "SUMMARY_RUN_DONE", "done", "trace-%s" % run_id,
         "op-%s" % run_id, -100, "summary_worker", None, None, "gpt-x",
         "openai", None, run_id, "summary.window", "1",
         "sp-%s" % run_id, ts, "ok")))
    _asyncio_run(db.db.commit())


@pytest.fixture
def client_f4(monkeypatch, tmp_path):
    """Latest endpoint: RBAC через fake PG; pipeline-db — seeded SQLite."""
    import web.api.analytics as analytics_mod
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn()
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    db = _make_db(tmp_path, name="f4_latest.sqlite3")
    # два прогона: run-old (older ts) с Base-манифестом, run-new (latest).
    _seed_done_event(db, "run-old", ts=1000)
    _seed_done_event(db, "run-new", ts=2000)
    assert _asyncio_run(cjobs.record_base_cover_manifest(
        db, summary_run_id="run-old", chat_id=-100,
        manifest=_base_manifest())) is True
    monkeypatch.setattr(analytics_mod, "_pipeline_db",
                        lambda request: db, raising=False)
    try:
        with TestClient(app) as tc:
            yield tc
    finally:
        _asyncio_run(db.close())


class TestLatestEndpoint:
    def test_401_without_init_data(self, client_f4):
        assert client_f4.get(
            "/api/analytics/pipeline/runs/latest?include_prompt=true"
        ).status_code == 401

    def test_403_non_global_admin_fail_closed(self, client_f4):
        """C5 негатив: не-глобал → 403 до любого чтения; промптов нет."""
        for uid in (USER_NO_ROLE, MODERATOR_ID):
            resp = client_f4.get(
                "/api/analytics/pipeline/runs/latest?include_prompt=true",
                headers=_hdr(uid))
            assert resp.status_code == 403, uid
            assert "cover_prompts" not in resp.text, uid
            assert PROMPT_BASE not in resp.text, uid

    def test_latest_resolves_inspector_sort_and_prompts(self, client_f4):
        """C5: latest = первый элемент списка инспектора (ts DESC, id DESC)
        → run-new; его статус честный (манифестов нет); exact-текст ДРУГОГО
        run (run-old) в ответ не утекает."""
        resp = client_f4.get(
            "/api/analytics/pipeline/runs/latest?include_prompt=true",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["run"] is not None
        assert body["run"]["run_id"] == "run-new"
        cp = body["cover_prompts"]
        assert isinstance(cp, dict)
        assert cp["base"] is None and cp["style"] is None
        assert body["cover_prompts_status"] == {
            "base": "legacy_run", "style": "legacy_run"}
        assert PROMPT_BASE not in resp.text

    def test_without_include_prompt_safe_shape(self, client_f4):
        """Без include_prompt — прежний R17-safe контракт: обоих ключей
        нет вообще (даже у global admin)."""
        resp = client_f4.get("/api/analytics/pipeline/runs/latest",
                             headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert "cover_prompts" not in body
        assert "cover_prompts_status" not in body
        assert body["run"] is not None

    def test_no_runs_honest_empty(self, client_f4, monkeypatch, tmp_path):
        import web.api.analytics as analytics_mod
        db2 = _make_db(tmp_path, name="f4_empty.sqlite3")
        monkeypatch.setattr(analytics_mod, "_pipeline_db",
                            lambda request: db2, raising=False)
        try:
            resp = client_f4.get(
                "/api/analytics/pipeline/runs/latest?include_prompt=true",
                headers=_hdr(ADMIN_ID))
            assert resp.status_code == 200
            body = resp.json()
            assert body["run"] is None
            assert "cover_prompts" not in body
            assert "cover_prompts_status" not in body
        finally:
            _asyncio_run(db2.close())


# ── 3. C7: preview-compile mode="style" ─────────────────────────────────────

from tests.test_asap7_cover_preview import (     # noqa: E402
    CTX_EXPECTED,
    DOC_PARAGRAPHS,
    DOC_TITLE,
    STORY_TEXT as PREVIEW_STORY,
    STYLE_TEXT as PREVIEW_STYLE,
    _seed_entry,
)

CHAT_ID = -1001234567890


def _fake_profile(**over):
    p = {
        "profile_id": "csp_f4", "name": "F4", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": True, "counter_value": 1,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


@pytest.fixture
def client_psc(monkeypatch):
    """preview-compile client (паттерн test_asap7_cover_preview.client)."""
    from services import web_runtime
    from services.config_cache import ConfigCache
    from web.api import deps as deps_mod_psc
    from web.api import summary_test as st_api
    from web.app import create_app
    monkeypatch.setattr(deps_mod_psc, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    st_api.reset_test_store()
    web_runtime.reset_web_runtime()
    cache = ConfigCache(pg=_FakePg(_FakeConn()), retry_attempts=1,
                        retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        yield tc
    st_api.reset_test_store()
    web_runtime.reset_web_runtime()


def _patch_profile(monkeypatch):
    """Fake PG без seeded профилей → резолв профиля подменяется фикстурой
    (первый enabled / явный id). Сам реестр не трогается."""
    import web.api.cover_styles as cover_api
    profile = _fake_profile()

    async def fake_get_profile(pg, profile_id):
        return profile if profile_id == profile["profile_id"] else None

    async def fake_list_profiles(pg, *, include_disabled=False):
        return [profile]

    monkeypatch.setattr(cover_api.registry, "get_profile", fake_get_profile)
    monkeypatch.setattr(cover_api.registry, "list_profiles",
                        fake_list_profiles)
    return profile


class TestPreviewCompileStyle:
    def test_422_invalid_mode(self, client_psc):
        resp = client_psc.post("/api/cover/preview-compile", json={
            "mode": "nano", "draft": {"instruction": PREVIEW_STYLE},
        }, headers=_hdr())
        assert resp.status_code == 422

    def test_403_non_admin_style_mode(self, client_psc):
        """R17 fail-closed: не-глобал → 403 в mode=style, exact-текста нет."""
        for uid in (USER_NO_ROLE, MODERATOR_ID):
            resp = client_psc.post("/api/cover/preview-compile", json={
                "mode": "style", "draft": {"instruction": PREVIEW_STYLE},
                "context": {"chat_id": CHAT_ID},
            }, headers=_hdr(uid))
            assert resp.status_code == 403, uid
            assert PREVIEW_STYLE[:20] not in resp.text, uid

    def test_style_without_context_honest_placeholder(self, client_psc,
                                                      monkeypatch):
        """§4.3: контекста нет → честный «контекст недоступен», без
        фейкового промпта, reserved budget виден."""
        _patch_profile(monkeypatch)
        resp = client_psc.post("/api/cover/preview-compile", json={
            "mode": "style", "draft": {"instruction": PREVIEW_STYLE},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_context"
        assert body["mode"] == "style"
        assert body["final_prompt"] is None
        assert body["manifest"] is None
        assert "контекст" in (body["message"] or "").lower()
        assert body["budget"]["reserved"]["story_min"] == cpa.STORY_MIN_CHARS
        assert body["style_source"] == "draft_instruction"

    def test_style_no_profile_honest(self, client_psc):
        """Профилей нет → честный no_profile, не выдуманный стиль."""
        resp = client_psc.post("/api/cover/preview-compile", json={
            "mode": "style", "draft": {"instruction": PREVIEW_STYLE},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_profile"
        assert body["final_prompt"] is None

    def test_style_mode_parity_with_compile_style_prompt(
            self, client_psc, monkeypatch):
        """C7 core: preview final_prompt == прямой вызов ТОГО ЖЕ
        compile_style_prompt с теми же входами (один server compiler,
        §28.9); манифест: preservation kept, story kept, base_style kept
        (без давления); fail-soft сигнала нет."""
        profile = _patch_profile(monkeypatch)
        test_id = "f4psc1"
        _seed_entry(test_id)
        resp = client_psc.post("/api/cover/preview-compile", json={
            "mode": "style", "draft": {"instruction": PREVIEW_STYLE},
            "context": {"chat_id": CHAT_ID},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["mode"] == "style"
        assert body["style_source"] == "draft_instruction"
        assert body["profile_source"] == "first_enabled"
        assert body["context"]["test_id"] == test_id
        assert body["route"] == "preview_compile"
        # parity с прямым компилятором (те же входы; лимит unknown → без cap)
        from services import cover_style_registry as registry
        from services import image_prompt_compiler as compiler
        from services.image_capabilities import (
            ImageModelCapabilities,
            PromptLimit,
        )
        caps_obj = ImageModelCapabilities(
            prompt_limit=PromptLimit(value=None, unit="chars",
                                     source="assembly_cap"))
        issue_display = registry.preview_issue_display(
            str(profile.get("counter_format")
                or registry.SEEDED_COUNTER_FORMAT),
            registry.next_issue_number(profile))
        direct = cjobs.compile_style_prompt(
            profile, issue_display=issue_display, capabilities=caps_obj,
            base_style_prompt=PREVIEW_STYLE,
            brief=compiler.brief_from_text(CTX_EXPECTED),
            story_scene=PREVIEW_STORY)
        assert body["final_prompt"] == direct.prompt
        manifest = body["manifest"]
        assert manifest["final_prompt"] == direct.prompt
        assert manifest["route"] == "preview_compile"
        keys = [c["key"] for c in manifest["components"]]
        assert "CONTENT_PRESERVATION" in keys
        by_key = {c["key"]: c for c in manifest["components"]}
        assert by_key["CONTENT_PRESERVATION"]["status"] == "kept"
        assert by_key["STORY_SCENE"]["status"] == "kept"
        assert by_key["BASE_STYLE"]["status"] == "kept"
        assert by_key["BASE_STYLE"]["sent_text"] == PREVIEW_STYLE
        assert body["style_publish_skip_reason"] is None
        assert manifest["attempts"][0]["outcome"] == "sent"
        assert body["budget"]["used_chars"] == len(direct.prompt)

    def test_style_mode_overflow_honest_skip_signal(self, client_psc,
                                                    monkeypatch):
        """Лимит известен и мал → P0/P1-ядро не влезает: exceeded + честный
        style_publish_skip_reason (в проде будет Base), attempt failed,
        P2 (base_style) — omitted. Никаких платных вызовов."""
        _patch_profile(monkeypatch)
        from services import image_generation

        class _PL:
            value = 200
            unit = "chars"
            source = "observed_provider_400"
            known = True

        async def _gen_limit():
            return _PL()

        monkeypatch.setattr(image_generation,
                            "resolve_generate_prompt_limit_async", _gen_limit)
        test_id = "f4psc2"
        _seed_entry(test_id)
        resp = client_psc.post("/api/cover/preview-compile", json={
            "mode": "style", "draft": {"instruction": PREVIEW_STYLE},
            "context": {"chat_id": CHAT_ID},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["exceeded"] is True
        assert body["style_publish_skip_reason"] == "prompt_limit_exceeded"
        manifest = body["manifest"]
        assert manifest["attempts"][0]["outcome"] == "failed"
        by_key = {c["key"]: c for c in manifest["components"]}
        assert by_key["CONTENT_PRESERVATION"]["status"] == "kept"
        assert by_key["BASE_STYLE"]["status"] == "omitted"
        # story identity (P1) при overflow не теряется молча — либо в
        # промпте, либо честный skip (здесь: skip = prompt_limit_exceeded).

    def test_base_mode_default_backward_compatible(self, client_psc):
        """Default mode="base" — прежний контракт цел (обратная
        совместимость существующих клиентов редактора)."""
        test_id = "f4psc3"
        _seed_entry(test_id)
        resp = client_psc.post("/api/cover/preview-compile", json={
            "draft": {"instruction": PREVIEW_STYLE},
            "context": {"chat_id": CHAT_ID},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["mode"] == "base"
        assert body["manifest"]["operation"] == "base"


# ── 4. REV-F3 хвост b: gap-утилиты в подключаемом CSS ────────────────────────

def test_gap_utilities_present_in_loaded_css():
    """Хвост REV-F3 (b): классы gap-x-4/gap-y-1 используются в index.html,
    но отсутствовали в prebuilt vendor/tailwind.css — в подключаемом
    web/static/app.css добавлены ровно эти 2 утилиты (заголовочные спаны
    панелей больше не слипаются)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "gap-x-4" in html and "gap-y-1" in html
    css = (root / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".gap-x-4" in css and "column-gap" in css
    assert ".gap-y-1" in css and "row-gap" in css
    # ровно 2 утилиты — без разрастания
    import re
    added = re.findall(r"\.gap-[xy]-\d+\s*\{[^}]*\}", css)
    assert sorted(a.split(" ")[0] for a in added) == \
        [".gap-x-4", ".gap-y-1"]


def test_latest_route_registered_before_param_route():
    """Latest-маршрут зарегистрирован ДО параметрического /runs/{run_id}
    (иначе FastAPI съест 'latest' как run_id) и в том же analytics_router."""
    import web.api.analytics as analytics_mod
    paths = [r.path for r in analytics_mod.analytics_router.routes
             if getattr(r, "path", "").startswith("/analytics/pipeline/runs")]
    assert "/analytics/pipeline/runs/latest" in paths
    assert paths.index("/analytics/pipeline/runs/latest") \
        < paths.index("/analytics/pipeline/runs/{run_id}")
