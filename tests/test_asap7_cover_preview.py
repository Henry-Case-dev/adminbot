"""ASAP 7 F7 — Cover live preview + унификация компиляторов (§2.3/§2.5/§9).

1. Унификация компиляторов (§2.3): Summary Test cover (``POST /api/summary/
   test/{id}/cover``) собирает промпт тем же production-компилятором
   ``compose_base_cover_prompt`` (3 компоненты + §11-гард + резолв лимита
   §2.2) и пишет ``CoverPromptManifest`` в task_jobs kind=cover_base — тот же
   носитель/контракт, что production Base. Легаци 2-компонентная
   ``compose_cover_image_prompt`` больше НЕ вызывается (regression B3).
2. Compiler-parity golden: production Base / Summary Test / preview-compile →
   одинаковый манифест-контракт для одинаковых входов (components,
   final_prompt, hash, limit-поля).
3. ``POST /api/cover/preview-compile`` (§9.2–§9.4): global admin fail-closed
   (не-глобал → 403, промпта нет); compile-only (0 генераций); без
   test-контекста — честный «preview context not selected», без fake
   production промптов.
4. Cleanup: ``_observed_limit_meta`` определён ровно один раз.
5. Routes-пин: новый маршрут — в cover_styles_router (web/app.py), routes.py
   не меняется → ROUTES_SHA256_F11 цел (прецедент MCA-10b/MCA-18).

TEST-LIFECYCLE: CONTRACT owner=asap7/F7
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from pathlib import Path

import pytest

from services import cover_prompt_assembly as cpa

ROOT = Path(__file__).resolve().parent.parent

STYLE_TEXT = "Comic-book style, set in modern Russia, PERMsoc heading"
STORY_TEXT = ("Медведь в цилиндре открывает Чемпионат мира по шахматам "
              "на Красной площади")
DOC_TITLE = "Титул выпуска"
DOC_PARAGRAPHS = [
    {"text": "Первый абзац финальной статьи с главными событиями.",
     "emphasis": "Первый"},
    {"text": "Второй абзац статьи с деталями.),", "emphasis": ""},
]
CTX_EXPECTED = cpa.summary_context_text(
    DOC_TITLE, [p.get("text") for p in DOC_PARAGRAPHS
                if isinstance(p, dict)])
# уникальные маркеры для R17/fail-closed проверок
CTX_MARKER = CTX_EXPECTED[:24]
STORY_MARKER = STORY_TEXT[:24]


def _asyncio_run(coro):
    return asyncio.run(coro)


def _make_db(tmp_path):
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / "f7_preview.sqlite3"))
    _asyncio_run(db.initialize())
    return db


# ── HTTP-инфраструктура (паттерн tests/test_summary_test_api.py) ────────────

TEST_TOKEN = "123456:TEST_TOKEN_F7_PREVIEW"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_NO_ROLE = 999999999
CHAT_ID = -1001234567890


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                          hashlib.sha256).digest()
    calc = hmac.new(secret_key, data_check.encode(),
                    hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


def _roles():
    return [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False, "role_type": "global_admin"},
        {"role_name": "moderator", "permissions": {"sections": ["limits"]},
         "is_custom": False, "role_type": "moderator"},
        {"role_name": "user", "permissions": {}, "is_custom": False,
         "role_type": "user"},
    ]


def _admins():
    return [
        {"telegram_id": ADMIN_ID, "role_name": "admin", "added_by": None,
         "created_at": "2026-09-07T00:00:00+00:00"},
        {"telegram_id": MODERATOR_ID, "role_name": "moderator",
         "added_by": ADMIN_ID, "created_at": "2026-09-07T00:00:01+00:00"},
    ]


class _FakeConn:
    async def execute(self, sql, *args):
        return "OK"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return list(_roles())
        if "FROM bot_admins" in sql:
            return list(_admins())
        return []


class _FakePool:
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


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


class _FakeMemory:
    def __init__(self, db):
        self.db = db


class _FakeCoverGenerator:
    """Генератор с резолвером стиля и SQLite-memory (для манифеста)."""

    def __init__(self, db, style: str = STYLE_TEXT):
        self.memory = _FakeMemory(db)
        self._style = style

    async def _resolve_cover_style_text(self, chat_id: int) -> str:
        return self._style


def _seed_entry(test_id: str, user_id: int = ADMIN_ID,
                chat_id: int = CHAT_ID, *, cover_prompt: str = STORY_TEXT,
                title: str | None = DOC_TITLE,
                paragraphs: list | None = None, status: str = "ok"):
    """Засеять завершённый тест-прогон в in-memory store (как live-прогон)."""
    from services import summary_test_run as str_run
    from web.api import summary_test as st_api
    entry = st_api._STORE.put_running(test_id, user_id, chat_id, 6)
    entry.status = status
    entry.finished = time.time()
    result = str_run._base_result(test_id=test_id, chat_id=chat_id,
                                  window={"hours": 6}, status=status)
    result.artifacts = {
        "package": {"service": {"cover_prompt": cover_prompt}},
        "article": {"schema_version": 1, "title": title,
                    "paragraphs": (DOC_PARAGRAPHS if paragraphs is None
                                   else paragraphs)},
    }
    entry.result = result
    return entry


@pytest.fixture
def client(monkeypatch):
    from services import web_runtime
    from services.config_cache import ConfigCache
    from web.api import deps as deps_mod
    from web.api import summary_test as st_api
    from web.app import create_app
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    st_api.reset_test_store()
    web_runtime.reset_web_runtime()
    cache = ConfigCache(pg=_FakePg(_FakeConn()), retry_attempts=1,
                        retry_delay=0)
    app = create_app(cache)
    with __import__("fastapi.testclient",
                    fromlist=["TestClient"]).TestClient(app) as tc:
        yield tc
    st_api.reset_test_store()
    web_runtime.reset_web_runtime()


def _cover_env(monkeypatch, tmp_path, db, *, gen_style: str = STYLE_TEXT,
               gen=None, limit=None):
    """Подмена generator + generate_image_verbose + (опц.) лимита GENERATE.

    Возвращает (calls, attempt_logs) для инспекции фактической отправки.
    """
    from services import image_generation
    calls: list = []
    logs: list = []

    async def _gen_limit():
        return limit

    if limit is not None:
        monkeypatch.setattr(image_generation,
                            "resolve_generate_prompt_limit_async", _gen_limit)

    async def fake_generate(prompt, chat_id=None, correlation_id=None,
                            shorter_prompt=None, attempt_log=None):
        calls.append({"prompt": prompt, "chat_id": chat_id,
                      "correlation_id": correlation_id})
        if attempt_log is not None:
            logs.append(attempt_log)
            attempt_log.append({"attempt": 1, "prompt": prompt,
                                "outcome": "ok", "reason": ""})
        out = tmp_path / "cover_f7.png"
        out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
        return str(out), "ok"

    monkeypatch.setattr(image_generation, "generate_image_verbose",
                        fake_generate)
    from services import web_runtime
    web_runtime.set_summary_generator(
        gen if gen is not None else _FakeCoverGenerator(db, gen_style))
    return calls, logs


# ── 1. Summary Test = production-сборка (§2.3, regression B3) ───────────────

class TestSummaryTestCoverProductionCompiler:
    def test_production_3_component_compile_and_manifest(self, client,
                                                         monkeypatch,
                                                         tmp_path):
        """Подтверждение обложки: compile через compose_base_cover_prompt
        (STORY+CONTEXT+STYLE) + durable CoverPromptManifest
        (final_prompt == фактически отправленный prompt, §2.6.3)."""
        from services import cover_style_jobs as cjobs
        test_id = "f7cover1"
        _seed_entry(test_id)
        db = _make_db(tmp_path)
        try:
            calls, _logs = _cover_env(monkeypatch, tmp_path, db)
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            assert resp.json()["cover_status"] == "generated"
            assert len(calls) == 1
            style = STYLE_TEXT
            expected = cpa.compose_base_cover_prompt(
                style, STORY_TEXT, CTX_EXPECTED)
            assert calls[0]["prompt"] == expected
            # production-сборка: все 3 компоненты доехали (B3 regression)
            assert CTX_MARKER in calls[0]["prompt"]
            assert STORY_MARKER in calls[0]["prompt"]
            manifest = _asyncio_run(
                cjobs.load_base_cover_manifest(db, test_id))
            assert manifest is not None
            assert manifest["final_prompt"] == calls[0]["prompt"]
            assert manifest["prompt_hash"] == cpa.prompt_hash(
                calls[0]["prompt"])
            assert manifest["attempts"][-1]["prompt"] == calls[0]["prompt"]
            keys = [c["key"] for c in manifest["components"]]
            assert keys == ["STORY_SCENE", "SUMMARY_CONTEXT", "BASE_STYLE"]
            ctx_comp = manifest["components"][1]
            assert ctx_comp["status"] == "kept"
            assert ctx_comp["sent_chars"] == len(CTX_EXPECTED)
            assert manifest["limit_source"] == "assembly_cap"
            assert manifest["resolved_limit"] == cpa.default_total_cap()
        finally:
            _asyncio_run(db.close())

    def test_legacy_compose_cover_image_prompt_not_called(self, client,
                                                          monkeypatch,
                                                          tmp_path):
        """Regression B3: легаци 2-компонентная сборка не вызывается нигде
        на пути Summary Test cover."""
        test_id = "f7cover2"
        _seed_entry(test_id)
        db = _make_db(tmp_path)
        try:
            _cover_env(monkeypatch, tmp_path, db)

            def _boom(*_a, **_kw):
                raise AssertionError(
                    "легаци compose_cover_image_prompt вызван на пути "
                    "Summary Test cover")

            monkeypatch.setattr(cpa, "compose_cover_image_prompt", _boom)
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            assert resp.json()["cover_status"] == "generated"
        finally:
            _asyncio_run(db.close())

    def test_shorter_retry_manifest_observed_limit(self, client,
                                                   monkeypatch, tmp_path):
        """§2.2: 400 too-long → ровно один shorter-retry; манифест —
        limit_source=observed_provider_400, final == последняя отправка."""
        from services import cover_style_jobs as cjobs
        from services import image_generation
        test_id = "f7cover3"
        _seed_entry(test_id)
        db = _make_db(tmp_path)
        try:
            calls: list = []

            async def fake_generate(prompt, chat_id=None, correlation_id=None,
                                    shorter_prompt=None, attempt_log=None):
                calls.append(prompt)
                # эмуляция внутренней семантики generate_image_verbose:
                # 400 too-long на попытке 1 → ровно один shorter-retry.
                if attempt_log is not None:
                    attempt_log.append({
                        "attempt": 1, "prompt": prompt,
                        "outcome": "retry_superseded",
                        "reason": "prompt_limit",
                        "meta": {"prompt_limit": {"value": 220,
                                                  "unit": "chars"}}})
                shorter = shorter_prompt(prompt, 220, "chars")
                assert shorter and len(shorter) <= 220
                assert STORY_MARKER in shorter, "story не выбрасывается"
                calls.append(shorter)
                if attempt_log is not None:
                    attempt_log.append({"attempt": 2, "prompt": shorter,
                                        "outcome": "ok", "reason": ""})
                out = tmp_path / "cover_f7_retry.png"
                out.write_bytes(b"\x89PNG\r\n\x1a\n")
                return str(out), "ok"

            monkeypatch.setattr(image_generation, "generate_image_verbose",
                                fake_generate)
            from services import web_runtime
            web_runtime.set_summary_generator(
                _FakeCoverGenerator(db, STYLE_TEXT))
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            assert resp.json()["cover_status"] == "generated"
            assert len(calls) == 2          # ровно 2 платные попытки (§2.2)
            assert calls[1] != calls[0]
            manifest = _asyncio_run(
                cjobs.load_base_cover_manifest(db, test_id))
            assert manifest["limit_source"] == "observed_provider_400"
            assert manifest["resolved_limit"] == 220
            assert manifest["attempts"][0]["outcome"] == "retry_superseded"
            assert manifest["final_prompt"] == calls[-1]
            assert manifest["attempts"][-1]["prompt"] == calls[-1]
        finally:
            _asyncio_run(db.close())

    def test_known_limit_caps_compilation(self, client, monkeypatch,
                                          tmp_path):
        """§2.2: known provider-limit → компиляция под консервативные chars,
        манифест честно пишет resolved_limit/limit_source."""
        from services import cover_style_jobs as cjobs
        from services import image_generation
        test_id = "f7cover4"
        _seed_entry(test_id)
        db = _make_db(tmp_path)
        limit = types.SimpleNamespace(known=True, value=400, unit="chars",
                                      source="capability_registry")
        try:
            calls, _ = _cover_env(monkeypatch, tmp_path, db, limit=limit)
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            assert len(calls[0]["prompt"]) <= 400
            manifest = _asyncio_run(
                cjobs.load_base_cover_manifest(db, test_id))
            assert manifest["resolved_limit"] == 400
            assert manifest["limit_source"] == "capability_registry"
            assert manifest["final_prompt"] == calls[0]["prompt"]
            # story физически доезжает (protected budget)
            assert STORY_MARKER in manifest["final_prompt"]
        finally:
            _asyncio_run(db.close())

    def test_generation_failure_still_writes_manifest(self, client,
                                                      monkeypatch, tmp_path):
        """Манифест пишется и на failed-пути (production-паритет
        _remember_base_manifest(ok=False))."""
        from services import cover_style_jobs as cjobs
        from services import image_generation
        test_id = "f7cover5"
        _seed_entry(test_id)
        db = _make_db(tmp_path)
        try:
            async def fake_generate(prompt, **_kw):
                raise RuntimeError("provider down")

            monkeypatch.setattr(image_generation, "generate_image_verbose",
                                fake_generate)
            from services import web_runtime
            web_runtime.set_summary_generator(
                _FakeCoverGenerator(db, STYLE_TEXT))
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            assert resp.json()["cover_status"] == "COVER_GENERATION_FAILED"
            manifest = _asyncio_run(
                cjobs.load_base_cover_manifest(db, test_id))
            assert manifest is not None
            assert manifest["attempts"][0]["prompt"].startswith(STORY_MARKER)
            assert manifest["final_prompt"] == manifest["attempts"][0][
                "prompt"]
        finally:
            _asyncio_run(db.close())

    def test_empty_cover_prompt_honest_no_generation(self, client,
                                                     monkeypatch, tmp_path):
        """Пустая сцена → честный no_cover_prompt, 0 платных вызовов
        (существующий контракт D3 сохранён)."""
        from services import image_generation
        test_id = "f7cover6"
        _seed_entry(test_id, cover_prompt="")
        db = _make_db(tmp_path)
        try:
            gen_image = pytest.importorskip("unittest.mock").MagicMock()
            monkeypatch.setattr(image_generation, "generate_image_verbose",
                                gen_image)
            from services import web_runtime
            web_runtime.set_summary_generator(
                _FakeCoverGenerator(db, STYLE_TEXT))
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            body = resp.json()
            assert body["cover_status"] == "COVER_GENERATION_FAILED"
            gen_image.assert_not_called()
        finally:
            _asyncio_run(db.close())


# ── 2. Compiler-parity golden (§2.3: одинаковый манифест-контракт) ──────────

def _manifest_contract(manifest: dict) -> dict:
    """Контрактные поля манифеста для parity-сравнения (без provider/route/
    attempts-outcome — они легитимно различаются между путями)."""
    return {
        "components": [{k: c[k] for k in ("key", "source", "priority",
                                          "original_chars", "sent_chars",
                                          "status", "reason")}
                       for c in manifest["components"]],
        "final_prompt": manifest["final_prompt"],
        "final_chars": manifest["final_chars"],
        "prompt_hash": manifest["prompt_hash"],
        "resolved_limit": manifest["resolved_limit"],
        "limit_unit": manifest["limit_unit"],
        "limit_source": manifest["limit_source"],
    }


class TestCompilerParityGolden:
    def test_three_paths_same_contract(self, client, monkeypatch, tmp_path):
        """production Base / Summary Test / preview-compile — одинаковые
        манифесты для одинаковых входов (style, story, ctx)."""
        test_id = "f7golden"
        _seed_entry(test_id)
        db = _make_db(tmp_path)
        try:
            calls, _ = _cover_env(monkeypatch, tmp_path, db)
            resp = client.post(f"/api/summary/test/{test_id}/cover",
                               json={"confirm": True}, headers=_hdr())
            assert resp.status_code == 200
            from services import cover_style_jobs as cjobs
            st_manifest = _asyncio_run(
                cjobs.load_base_cover_manifest(db, test_id))

            # production-форма Base (как summary_generator:2934/2992)
            prod_prompt = cpa.compose_base_cover_prompt(
                STYLE_TEXT, STORY_TEXT, CTX_EXPECTED)
            prod_manifest = cpa.build_base_manifest(
                base_style=STYLE_TEXT, story_scene=STORY_TEXT,
                summary_context=CTX_EXPECTED, final_prompt=prod_prompt,
                provider="prov")

            # preview-compile (тот же draft-стиль + тот же test-context)
            resp2 = client.post("/api/cover/preview-compile", json={
                "draft": {"instruction": STYLE_TEXT},
                "context": {"test_id": test_id},
            }, headers=_hdr())
            assert resp2.status_code == 200
            prev = resp2.json()
            assert prev["status"] == "ok"

            assert calls[0]["prompt"] == prod_prompt
            assert _manifest_contract(prev["manifest"]) == \
                _manifest_contract(prod_manifest)
            assert _manifest_contract(st_manifest) == \
                _manifest_contract(prod_manifest)
        finally:
            _asyncio_run(db.close())


# ── 3. POST /api/cover/preview-compile (§9.2–§9.4, R17) ─────────────────────

class TestPreviewCompileApi:
    def test_401_without_init_data(self, client):
        assert client.post("/api/cover/preview-compile",
                           json={}).status_code == 401

    def test_403_non_admin_fail_closed(self, client):
        """Не-глобал → 403; никакого exact-текста/манифеста в ответе."""
        for uid in (USER_NO_ROLE, MODERATOR_ID):
            resp = client.post("/api/cover/preview-compile", json={
                "draft": {"instruction": STYLE_TEXT},
                "context": {"chat_id": CHAT_ID},
            }, headers=_hdr(uid))
            assert resp.status_code == 403, uid
            assert STYLE_TEXT[:20] not in resp.text, uid
            assert STORY_MARKER not in resp.text, uid
            assert "manifest" not in resp.json(), uid

    def test_admin_without_context_honest_placeholder(self, client):
        """§9.4: без test-контекста — честный placeholder: exact current
        draft по BASE_STYLE, STORY/CONTEXT — preview context not selected,
        фейкового production-промпта нет."""
        resp = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_context"
        assert body["final_prompt"] is None
        comps = {c["key"]: c for c in body["components"]}
        assert comps["BASE_STYLE"]["status"] == "kept"
        assert comps["BASE_STYLE"]["sent_text"] == STYLE_TEXT
        for key in ("STORY_SCENE", "SUMMARY_CONTEXT"):
            assert comps[key]["status"] == "omitted"
            assert comps[key]["reason"] == "preview_context_not_selected"
            assert comps[key]["sent_text"] == ""
        # зарезервированные минимумы честно показаны
        assert body["budget"]["reserved"]["story_min"] == cpa.STORY_MIN_CHARS
        assert STORY_MARKER not in resp.text

    def test_admin_with_context_exact_compiled(self, client):
        """§9.3: с выбранным test-context — exact compiled text + breakdown
        + лимит/использовано/остаток; 0 генераций."""
        test_id = "f7prev1"
        _seed_entry(test_id)
        resp = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
            "context": {"chat_id": CHAT_ID},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["context"]["test_id"] == test_id
        expected = cpa.compose_base_cover_prompt(
            STYLE_TEXT, STORY_TEXT, CTX_EXPECTED)
        manifest = body["manifest"]
        assert manifest["final_prompt"] == expected
        assert manifest["operation"] == "base"
        assert manifest["route"] == "preview_compile"
        # единая форма breakdown'а: верхнеуровневые components == manifest
        assert body["components"] == manifest["components"]
        assert body["final_prompt"] == expected
        budget = body["budget"]
        assert budget["used_chars"] == len(expected)
        assert budget["compile_cap_chars"] == cpa.default_total_cap()
        assert budget["remaining_chars"] == \
            max(0, cpa.default_total_cap() - len(expected))
        assert manifest["prompt_hash"] == cpa.prompt_hash(expected)

    def test_context_test_id_respected(self, client):
        test_id = "f7prev2"
        _seed_entry(test_id)
        _seed_entry("f7prev2-older")
        resp = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
            "context": {"test_id": test_id},
        }, headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["context"]["test_id"] == test_id

    def test_context_of_other_user_not_readable(self, client):
        """Fail-closed: чужой (другого админа) test_id не читается."""
        _seed_entry("f7alien", user_id=424242)
        resp = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
            "context": {"test_id": "f7alien"},
        }, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_context"
        assert body["reason"] == "test_run_not_found"
        assert STORY_MARKER not in resp.text

    def test_context_absent_honest(self, client):
        """Выбран несуществующий/неготовый прогон — честный no_context."""
        resp = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
            "context": {"chat_id": -100999},
        }, headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_context"
        assert resp.json()["reason"] == "test_run_not_found"
        # running-прогон ещё не имеет результата
        _seed_entry("f7running", status="running")
        resp2 = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
            "context": {"test_id": "f7running"},
        }, headers=_hdr())
        assert resp2.json()["reason"] == "test_run_not_usable"

    def test_disabled_404(self, client, monkeypatch):
        from services import cover_style_pipeline as pipeline
        monkeypatch.setattr(pipeline, "cover_styles_enabled", lambda: False)
        resp = client.post("/api/cover/preview-compile", json={},
                           headers=_hdr())
        assert resp.status_code == 404

    def test_compile_only_no_generation(self, client, monkeypatch):
        """Compile-only: generate_image_verbose не вызывается вообще."""
        from services import image_generation
        gen_image = pytest.importorskip("unittest.mock").MagicMock()
        monkeypatch.setattr(image_generation, "generate_image_verbose",
                            gen_image)
        test_id = "f7prev3"
        _seed_entry(test_id)
        resp = client.post("/api/cover/preview-compile", json={
            "draft": {"instruction": STYLE_TEXT},
            "context": {"chat_id": CHAT_ID},
        }, headers=_hdr())
        assert resp.status_code == 200
        gen_image.assert_not_called()


# ── 4. Cleanup: _observed_limit_meta определён один раз ─────────────────────

class TestObservedLimitMetaCleanup:
    def test_single_definition(self):
        src = (ROOT / "services" / "summary_generator.py").read_text(
            encoding="utf-8")
        count = src.count("def _observed_limit_meta")
        assert count == 1, (
            "REV-2 #1: дубль _observed_limit_meta должен быть убран "
            "(обнаружено %d определений)" % count)
        # определение и все вызовы в одном локальном скоупе
        assert src.count("_observed_limit_meta()") >= 1


# ── 5. Routes-пин: routes.py не меняется (маршрут в cover_styles_router) ────

class TestRoutesPinUnchanged:
    def test_routes_sha256_f11_intact(self):
        sys_path = str(ROOT)
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from tests.test_round1025_f8_registry import ROUTES_SHA256_F11
        digest = hashlib.sha256(
            (ROOT / "web" / "api" / "routes.py").read_bytes()).hexdigest()
        assert digest == ROUTES_SHA256_F11, (
            "web/api/routes.py изменился — переутверждение ROUTES_SHA256_F11 "
            "по прецеденту (tools/_mca18_repin_routes.py) вне этого теста")

    def test_new_route_in_cover_styles_router(self):
        from web.api.cover_styles import cover_styles_router
        paths = {getattr(r, "path", "") for r in cover_styles_router.routes}
        assert "/cover/preview-compile" in paths
        post_paths = {r.path for r in cover_styles_router.routes
                      if "POST" in getattr(r, "methods", set())}
        assert "/cover/preview-compile" in post_paths

    def test_routes_py_has_no_preview_compile(self):
        routes_txt = (ROOT / "web" / "api" / "routes.py").read_text(
            encoding="utf-8")
        assert "preview-compile" not in routes_txt


# ── 6. UI-контракт: server-compiled only (§22 п.15) ─────────────────────────

def test_js_unit_f7_cover_compile():
    """РЕАЛЬНЫЙ JS-тест UI-логики F7 (паттерн F8/test_webapp_js_unit):
    compile-preview ходит на server compiler, frontend ничего не собирает."""
    import os
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    script = os.path.join("tests", "js", "asap7_f7_cover_compile_test.js")
    assert os.path.exists(script)
    res = subprocess.run([node, script], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, (
        "F7 JS-unit провалился:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "ASAP7-F7-COVER-COMPILE-OK" in res.stdout
