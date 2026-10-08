"""ASAP 7 F8 — Cover exact-prompt read path (§2.5/§10, R17).

1.  ``load_run_cover_prompts`` — production-читатель манифестов run'а
    (Base: task_jobs kind=cover_base; Style: durable state production
    Style-Edit по coalesce_key='cover_style:<run_id>'); поведение записи
    не меняется.
2.  Инвариант §2.6.3: manifest.final_prompt == фактически отправленный
    request.prompt — сверка с durable-артефактом отправки:
      * Base: media job coalesce_key содержит prompt_hash отправленного
        prompt (полный текст media job сознательно не хранит, R17) —
        пересчёт ключа по манифесту обязан совпасть, расхождение = RED;
      * Style: fake edit_call фиксирует фактический промпт → durable
        state.prompt_manifest обязан с ним совпасть.
3.  R17 fail-closed API: ``GET /api/analytics/pipeline/runs/{run_id}
    ?include_prompt=true`` — только global admin (не-глобал → 403,
    промпта нет); без include_prompt — прежний safe-ответ, ключа
    ``cover_prompts`` в ответе нет вообще.
4.  UI-контракт (статика): блок рендерится только при admin + данных,
    machine reason — в developer-details.

TEST-LIFECYCLE: CONTRACT owner=asap7/F8
"""
from __future__ import annotations

import asyncio

import pytest

from services import cover_prompt_assembly as cpa
from services import cover_style_jobs as cjobs
from services import media_execution as me
from services.cover_style_edit import EditResult
from services import image_capabilities as cap

STYLE_TEXT = ("photorealistic cover, cinematic light, strict magazine grid")
STORY_TEXT = ("Медведь в цилиндре открывает Чемпионат мира по шахматам "
              "на Красной площади")
CONTEXT_TEXT = "Титул выпуска. Медведь победил в тай-брейке."


def _asyncio_run(coro):
    return asyncio.run(coro)


def _profile(**over):
    p = {
        "profile_id": "csp_f8", "name": "ReadPath", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": True, "counter_value": 1,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


def _caps_unknown():
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit())


STYLED_BYTES = b"\x89PNG\r\n\x1a\n" + b"styled" * 8


def _make_db(tmp_path):
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / "readpath.sqlite3"))
    _asyncio_run(db.initialize())
    return db


# ── 1. Reader: production-читатель манифестов run'а (§2.5) ─────────────────

class TestRunCoverPromptsReader:
    def test_base_reader_roundtrip_and_media_job_invariant(self, tmp_path):
        """Инвариант §2.6.3 (Base): manifest.final_prompt == фактически
        отправленный request.prompt. Durable-артефакт отправки — media job
        (полный prompt не хранит, R17): coalesce_key содержит prompt_hash
        фактического prompt; пересчёт ключа по манифесту обязан совпасть."""
        db = _make_db(tmp_path)
        try:
            run_id = "run-f8-base"
            prompt = cpa.compose_base_cover_prompt(
                STYLE_TEXT, STORY_TEXT, CONTEXT_TEXT)
            jid, _mj = _asyncio_run(me.begin_media_job(
                db, operation=me.OPERATION_GENERATE, provider="prov",
                model="model-x", prompt=prompt, chat_id=-100,
                correlation_id=run_id))
            manifest = cpa.build_base_manifest(
                base_style=STYLE_TEXT, story_scene=STORY_TEXT,
                summary_context=CONTEXT_TEXT, final_prompt=prompt,
                provider="prov")
            assert _asyncio_run(cjobs.record_base_cover_manifest(
                db, summary_run_id=run_id, chat_id=-100,
                manifest=manifest)) is True

            # durable-артефакт отправки: coalesce_key media job == ключ,
            # пересчитанный из манифеста (расхождение = RED).
            import asyncio as _aio

            async def _fetch():
                cur = await db.db.execute(
                    "SELECT coalesce_key FROM task_jobs WHERE job_id = ?",
                    (jid,))
                r = await cur.fetchone()
                return dict(r)

            coalesce = _asyncio_run(_fetch())["coalesce_key"]
            expected = "media_job:" + me.media_job_key(
                me.OPERATION_GENERATE, "prov", "model-x",
                me.prompt_hash(manifest["final_prompt"]))
            assert coalesce == expected

            prompts = _asyncio_run(cjobs.load_run_cover_prompts(db, run_id))
            assert prompts["base"] is not None
            assert prompts["base"]["final_prompt"] == prompt
            assert prompts["base"]["prompt_hash"] == cpa.prompt_hash(prompt)
            assert prompts["style"] is None          # style-джобы нет — None
            assert prompts["base"]["attempts"][0][
                "prompt"] == prompt
        finally:
            _asyncio_run(db.close())

    def test_style_reader_durable_state_matches_sent_prompt(self, tmp_path):
        """Инвариант §2.6.3 (Style): manifest.final_prompt == фактически
        отправленный edit_call prompt; читается из durable state по
        coalesce_key (production-путь), запись — без изменений."""
        db = _make_db(tmp_path)
        try:
            run_id = "run-f8-style"
            jid = _asyncio_run(cjobs.start_cover_job(
                db, chat_id=0, correlation_id=run_id,
                payload={"kind": "cover_style"},
                coalesce_key="cover_style:%s" % run_id))
            assert jid
            # production-паттерн (summary_generator → begin_cover_job):
            # state создаётся вызывающим и передаётся в run_style_job;
            # персист-точки внутри джобы пишут его в durable checkpoint.
            state = cjobs.CoverJobState(style_id="csp_f8")
            sent: list = []

            async def edit_call(prompt, **_kw):
                sent.append(prompt)
                return EditResult(ok=True, content=STYLED_BYTES, reason="ok")

            meta = _asyncio_run(cjobs.run_style_job(
                chat_id=0, base_image_path="unused",
                profile=_profile(), summary_run_id=run_id,
                capabilities=_caps_unknown(), edit_call=edit_call,
                reference_paths=[], summary_text=CONTEXT_TEXT,
                story_scene=STORY_TEXT, base_style_prompt=STYLE_TEXT,
                db=db, job_id=jid, state=state))
            assert meta["applied"] is True, meta
            assert len(sent) == 1

            prompts = _asyncio_run(cjobs.load_run_cover_prompts(db, run_id))
            assert prompts["style"] is not None
            style = prompts["style"]
            # фактическая отправка == durable манифест (обе оси)
            assert style["final_prompt"] == sent[-1]
            assert style["attempts"][-1]["prompt"] == sent[-1]
            assert style["prompt_hash"] == cpa.prompt_hash(sent[-1])
            assert style["final_chars"] == len(sent[-1])
            # Base-пустота честная: base-джобы для этого run нет
            assert prompts["base"] is None
        finally:
            _asyncio_run(db.close())

    def test_reader_fail_open(self, tmp_path):
        db = _make_db(tmp_path)
        try:
            assert _asyncio_run(cjobs.load_run_cover_prompts(
                None, "run-x")) == {"base": None, "style": None}
            assert _asyncio_run(cjobs.load_run_cover_prompts(
                db, "")) == {"base": None, "style": None}
            assert _asyncio_run(cjobs.load_run_cover_prompts(
                db, "run-absent")) == {"base": None, "style": None}
        finally:
            _asyncio_run(db.close())


# ── 2. R17 fail-closed API (§2.5/§10) ───────────────────────────────────────

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

RUN_LIVE = "run-f8-live"
PROMPT_SENT = "STYLE-BLOCK STORY-BLOCK CONTEXT-BLOCK"


def _seed_run(db):
    manifest = cpa.build_base_manifest(
        base_style="STYLE-BLOCK", story_scene="STORY-BLOCK",
        summary_context="CONTEXT-BLOCK", final_prompt=PROMPT_SENT,
        provider="prov")
    assert _asyncio_run(cjobs.record_base_cover_manifest(
        db, summary_run_id=RUN_LIVE, chat_id=-100,
        manifest=manifest)) is True


@pytest.fixture
def client_f8(monkeypatch, tmp_path):
    """Run Inspector API: RBAC через fake PG; pipeline-db — seeded SQLite."""
    import types as _types
    import web.api.analytics as analytics_mod
    monkeypatch.setattr(deps_mod, "settings",
                        _types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn()
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    db = _make_db(tmp_path)
    _seed_run(db)
    monkeypatch.setattr(analytics_mod, "_pipeline_db",
                        lambda request: db, raising=False)
    try:
        with TestClient(app) as tc:
            yield tc
    finally:
        _asyncio_run(db.close())


class TestIncludePromptRbac:
    def test_401_without_init_data(self, client_f8):
        assert client_f8.get(
            "/api/analytics/pipeline/runs/%s?include_prompt=true" % RUN_LIVE
        ).status_code == 401

    def test_403_non_global_admin_no_prompt_anywhere(self, client_f8):
        """Не-глобал (юзер без роли / модератор) → 403, промпта нет."""
        for uid in (USER_NO_ROLE, MODERATOR_ID):
            resp = client_f8.get(
                "/api/analytics/pipeline/runs/%s?include_prompt=true"
                % RUN_LIVE, headers=_hdr(uid))
            assert resp.status_code == 403, uid
            assert PROMPT_SENT not in resp.text, uid
            assert "cover_prompts" not in resp.text, uid

    def test_without_include_prompt_safe_shape(self, client_f8):
        """Без include_prompt — прежний R17-safe ответ: ключа cover_prompts
        нет вообще, exact-текст не утекает (даже global admin)."""
        resp = client_f8.get(
            "/api/analytics/pipeline/runs/%s" % RUN_LIVE,
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert "cover_prompts" not in body
        assert PROMPT_SENT not in resp.text
        assert body["run"] is not None

    def test_include_prompt_admin_exact_manifest(self, client_f8):
        """Global admin + include_prompt=true → exact-тексты Base-манифеста
        run'а (+ честные None там, где джоб нет)."""
        resp = client_f8.get(
            "/api/analytics/pipeline/runs/%s?include_prompt=true" % RUN_LIVE,
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        cp = body.get("cover_prompts")
        assert isinstance(cp, dict)
        assert cp["base"] is not None
        assert cp["base"]["final_prompt"] == PROMPT_SENT
        assert cp["base"]["prompt_hash"] == cpa.prompt_hash(PROMPT_SENT)
        assert cp["base"]["attempts"], "обе/base attempts с exact-текстом"
        assert cp["base"]["attempts"][0]["prompt"] == PROMPT_SENT
        # style-джобы для run нет — честный None (не выдумка)
        assert cp["style"] is None

    def test_include_prompt_absent_run_honest_empty(self, client_f8):
        resp = client_f8.get(
            "/api/analytics/pipeline/runs/run-absent?include_prompt=true",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        cp = resp.json()["cover_prompts"]
        assert cp == {"base": None, "style": None}


# ── 3. UI-контракт (статика): гейтинг рендера ──────────────────────────────

def test_js_unit_f8_cover_prompts():
    """РЕАЛЬНЫЙ JS-тест UI-логики F8 (не grep): рендер-гейт admin+данные,
    include_prompt только у global admin, зоны/секреты. Паттерн
    test_webapp_js_unit; пропускается без node."""
    import os
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    script = os.path.join("tests", "js", "asap7_f8_cover_prompts_test.js")
    assert os.path.exists(script)
    res = subprocess.run([node, script], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, (
        "F8 JS-unit провалился:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "ASAP7-F8-COVER-PROMPTS-OK" in res.stdout


class TestUiGatingStatic:
    def test_index_block_and_developer_details_present(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent
                / "web" / "index.html").read_text(encoding="utf-8")
        assert 'id="pipeline-cover-prompts"' in html
        assert 'v-if="pipelineCoverPromptsVisible"' in html
        assert "Фактический промпт" in html
        # machine reason — в developer-details, не в основном тексте
        assert "machine reason попыток" in html
        # copy button на exact-текст
        assert "@click=\"copyText(att.prompt)\"" in html

    def test_app_gating_admin_and_include_prompt(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent
              / "web" / "app.js").read_text(encoding="utf-8")
        # запрос exact-промптов только для global admin
        assert "if (this.isGlobalAdminEffective)" in js
        assert "include_prompt=true" in js
        # рендер-гейт: admin И данные
        assert "pipelineCoverPromptsVisible: function" in js
        gating = js[js.index("pipelineCoverPromptsVisible: function"):]
        assert "isGlobalAdminEffective" in gating[:400]

    def test_delta_routes_zero_include_prompt_is_query_param(self):
        """Δ routes = 0: include_prompt — query-параметр СУЩЕСТВУЮЩЕГО
        endpoint'а; routes.py F8 не трогает (byte-freeze/ROUTES_SHA256_F11 —
        зона ответственности test_round1025_f8_registry, re-pin не требуется;
        прецедент MCA-23: аддитивный endpoint в analytics.py пин не трогает).
        Важно: routes.py может нести НЕЗакоммиченные правки параллельных
        лейнов — этот тест проверяет только ОТСУТСТВИЕ своего вклада F8."""
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        routes_txt = (root / "web" / "api" / "routes.py").read_text(
            encoding="utf-8")
        assert "include_prompt" not in routes_txt
        assert "cover_prompts" not in routes_txt
        # сам drill-down endpoint ровно один, путь не менялся
        analytics_txt = (root / "web" / "api" / "analytics.py").read_text(
            encoding="utf-8")
        assert analytics_txt.count('"/analytics/pipeline/runs/{run_id}"') == 1
        assert "include_prompt: bool = Query(default=False)" in analytics_txt
