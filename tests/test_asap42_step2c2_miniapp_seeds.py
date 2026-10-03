"""ASAP 4.2 Step 2c-2 (T-4817…T-4827) — targeted tests: seeds e2e, Test Style
UX, preview persistence, RBAC seeded Medved Press, MiniApp layout contract.

Покрывает §49-пункты: seed expectations; style preview persistence;
test-style endpoint не тратит counter и не требует upload; RBAC seeded Medved
Press; mobile bottom-layout measurements (closed more-sheet contract);
Modules Quick Access absent.

Полный pytest НЕ гоняется (owner §49). Запуск:
    pytest tests/test_asap42_step2c2_miniapp_seeds.py -q
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import cover_style_assets as assets
from services import cover_style_registry as registry
from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api.cover_styles import _public_profile, cover_styles_router

ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN = "123456:STEP2C2_TOKEN"
ADMIN_ID = 111222
USER_ID = 999888


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_init_data(token: str, user_id: int = ADMIN_ID) -> str:
    import hmac
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A", "username": "a"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, v) for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _profile(**over):
    p = {
        "profile_id": "medved_press",
        "name": "Графический роман Медведь Press",
        "origin": "seeded_example", "pipeline_mode": "generate_then_edit",
        "instruction": "instr", "counter_enabled": True, "counter_value": 5,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 2,
        "enabled": True, "preview_before_asset_id": "cas_seed_before",
        "preview_after_asset_id": "cas_seed_after", "preview_revision": None,
        "references": [{"ref_id": "r1", "asset_id": "cas_ref",
                        "label": "Медведь Press", "description": "знак",
                        "ordering": 0}],
    }
    p.update(over)
    return p


def _client(role_name: str = "admin"):
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    if role_name == "admin":
        cache._roles = {
            "admin": {"permissions": {"wildcard": True},
                      "is_custom": False, "role_type": "global_admin"},
        }
        cache._permissions = {"admin": Permissions.from_dict({"wildcard": True})}
        cache._admins = {ADMIN_ID: "admin"}
    else:
        cache._roles = {
            "user": {"permissions": {"sections": ["access"]},
                     "is_custom": False, "role_type": "user"},
        }
        cache._permissions = {
            "user": Permissions.from_dict({"sections": ["access"]})}
        cache._admins = {}
    cache._pg_available = False
    cache._initialized = True
    cache._pg = types.SimpleNamespace(pool=object())
    app = FastAPI()
    app.state.cache = cache
    app.include_router(cover_styles_router, prefix="/api")
    return TestClient(app)


def _hdr(user=ADMIN_ID):
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user)}


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


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")


# ── Seeds e2e (§49: seed expectations; T-4818) ─────────────────────────────

class TestSeedExpectations:
    def test_seed_files_mapping(self):
        assert registry.SEED_FILES == {
            "reference": "medved_press.png",
            "preview_before": "style_example_01.png",
            "preview_after": "style_example_02.jpg",
        }

    def test_seed_files_import_chain_durable_bytes(self, tmp_path):
        """SEED_FILES → import_seed_file → durable copy; sha/asset_id/bytes
        совпадают (никаких substitute assets)."""
        seed_dir = ROOT / "extra_images"
        for key, filename in registry.SEED_FILES.items():
            src = seed_dir / filename
            assert src.exists(), key
            meta = assets.import_seed_file(src, origin="seed")
            assert meta is not None, key
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            assert meta["sha256"] == digest, key
            assert meta["asset_id"] == assets.asset_id_for(digest), key
            durable = Path(meta["disk_path"])
            assert durable.exists(), key
            assert durable.read_bytes() == src.read_bytes(), key

    def test_seed_end_to_end_wiring(self, monkeypatch, tmp_path):
        """`seed_seeded_style`: import_seed_file → upsert_asset → add_reference,
        profile получает preview before/after asset ids (T-4818)."""
        seed_dir = ROOT / "extra_images"

        class _Conn:
            async def fetchrow(self, *a, **k):
                return None

            async def fetch(self, *a, **k):
                return []

            async def execute(self, *a, **k):
                return "INSERT 0 1"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Pool:
            def acquire(self):
                return _Conn()

        pg = types.SimpleNamespace(pool=_Pool())

        captured = {"assets": [], "refs": [], "profile": None}

        async def _upsert_asset(_pg, meta):
            captured["assets"].append(dict(meta))
            return True

        async def _add_reference(_pg, profile_id, ref):
            captured["refs"].append((profile_id, dict(ref)))
            return "csr_seed_ref"

        async def _upsert_profile(_pg, profile):
            captured["profile"] = dict(profile)
            return True

        monkeypatch.setattr(registry, "get_profile",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(registry, "get_profile_with_refs",
                            AsyncMock(return_value={"profile_id":
                                                    "medved_press"}))
        monkeypatch.setattr(registry, "upsert_asset", _upsert_asset)
        monkeypatch.setattr(registry, "add_reference", _add_reference)
        monkeypatch.setattr(registry, "upsert_profile", _upsert_profile)

        real_import = registry.import_seed_file
        seen = []

        def _import(src, *a, **k):
            meta = real_import(src, *a, **k)
            if meta is not None:
                seen.append(Path(src).name)
            return meta

        monkeypatch.setattr(registry, "import_seed_file", _import)

        result = _run(registry.seed_seeded_style(pg, seed_dir=seed_dir))
        assert result is not None
        assert set(seen) == set(registry.SEED_FILES.values())
        assert len(captured["assets"]) == len(registry.SEED_FILES)
        by_name = {a["filename"]: a for a in captured["assets"]}
        ref_asset = by_name["medved_press.png"]["asset_id"]
        assert captured["refs"], "reference добавлен"
        assert captured["refs"][0][0] == "medved_press"
        assert captured["refs"][0][1]["asset_id"] == ref_asset
        prof = captured["profile"]
        assert prof["preview_before_asset_id"] == \
            by_name["style_example_01.png"]["asset_id"]
        assert prof["preview_after_asset_id"] == \
            by_name["style_example_02.jpg"]["asset_id"]


# ── Test Style UX (T-4819) ─────────────────────────────────────────────────

def _patch_test_style(monkeypatch, tmp_path, profile, preview_meta):
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=profile))
    monkeypatch.setattr(
        "services.cover_style_registry.upsert_asset", AsyncMock(return_value=True))
    captured = {"set_preview": [], "issue_calls": 0}

    async def _set_preview(pg, profile_id, **kw):
        captured["set_preview"].append((profile_id, kw))
        return True

    async def _resolve_issue(*a, **k):
        captured["issue_calls"] += 1
        return 99

    monkeypatch.setattr("services.cover_style_registry.set_preview", _set_preview)
    monkeypatch.setattr("services.cover_style_registry.resolve_issue_number",
                        _resolve_issue)

    base = tmp_path / "base.png"
    base.write_bytes(PNG_BYTES)
    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose",
        AsyncMock(return_value=(str(base), "ok")))
    monkeypatch.setattr(
        "services.cover_style_jobs.run_style_preview",
        AsyncMock(return_value=preview_meta))
    return captured


def test_test_style_generates_base_no_upload_no_counter(monkeypatch, tmp_path):
    styled = tmp_path / "styled.jpg"
    styled.write_bytes(b"STYLED")
    captured = _patch_test_style(monkeypatch, tmp_path, _profile(),
                                 {"applied": True, "styled_path": str(styled),
                                  "preview_issue": "ВЫПУСК 00", "model": "m",
                                  "provider": "p", "duration_ms": 12})
    resp = _client().post("/api/cover/test-style", headers=_hdr(),
                          json={"profile_id": "medved_press"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["base_source"] == "generated"
    assert body["preview_source"] == "test"
    assert body["preview_source_label"] == "Результат теста"
    # counter не потрачен (mode=preview, resolve_issue_number не вызван)
    assert captured["issue_calls"] == 0, "Test Style не тратит issue counter"
    # preview сохранён с РЕАЛЬНЫМ before и after
    assert captured["set_preview"], "preview persist"
    assert captured["set_preview"][0][1]["before_asset_id"]
    assert captured["set_preview"][0][1]["after_asset_id"]
    assert captured["set_preview"][0][1]["revision"] == 2


def test_test_style_requires_no_file(monkeypatch, tmp_path):
    """Основной путь не содержит `content_base64` — endpoint не должен
    пытаться декодировать/сохранять пользовательский upload."""
    styled = tmp_path / "styled.jpg"
    styled.write_bytes(b"STYLED")
    decode_calls = {"n": 0}
    real_decode = None
    import web.api.cover_styles as cs
    real_decode = cs._decode_upload

    def _spy_decode(body):
        decode_calls["n"] += 1
        return real_decode(body)

    monkeypatch.setattr(cs, "_decode_upload", _spy_decode)
    _patch_test_style(monkeypatch, tmp_path, _profile(),
                      {"applied": True, "styled_path": str(styled),
                       "preview_issue": "ВЫПУСК 00"})
    resp = _client().post("/api/cover/test-style", headers=_hdr(),
                          json={"profile_id": "medved_press"})
    assert resp.status_code == 200
    assert decode_calls["n"] == 0, "upload-путь не задействован без файла"


def test_test_style_failure_keeps_last_preview(monkeypatch, tmp_path):
    captured = _patch_test_style(
        monkeypatch, tmp_path,
        _profile(preview_after_asset_id="cas_old_after",
                 preview_before_asset_id="cas_old_before",
                 preview_revision=2),
        {"applied": False, "reason": "style_failed",
         "fail_reason": "route_unverified", "message": "",
         "preview_issue": "ВЫПУСК 00"})
    resp = _client().post("/api/cover/test-style", headers=_hdr(),
                          json={"profile_id": "medved_press"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is False
    # человеческая фраза в основном виде, machine reason — в developer
    assert "провайдер отклонил" in body["message"].lower()
    assert body["developer_reason"] == "route_unverified"
    # прошлый preview не уничтожен
    assert body["preview_after_url"] == "/api/cover/assets/cas_old_after"
    assert body["preview_before_url"] == "/api/cover/assets/cas_old_before"
    assert captured["set_preview"] == [], "провал не перезаписывает preview"


# ── Provenance / preview fields (T-4818/T-4819) ────────────────────────────

class TestPreviewProvenance:
    def test_example_vs_test_source(self):
        seeded = _public_profile(_profile(), viewer_is_admin=True)
        assert seeded["preview_source"] == "example"
        assert seeded["preview_source_label"] == "Пример"
        tested = _public_profile(
            _profile(preview_revision=2), viewer_is_admin=True)
        assert tested["preview_source"] == "test"
        assert tested["preview_source_label"] == "Результат теста"

    def test_seeded_can_edit_only_admin(self):
        assert _public_profile(_profile(), viewer_is_admin=False)["can_edit"] \
            is False
        assert _public_profile(_profile(), viewer_is_admin=True)["can_edit"] \
            is True
        custom = _public_profile(_profile(origin="custom"),
                                 viewer_is_admin=False)
        assert custom["can_edit"] is True


# ── RBAC seeded Medved Press (T-4821) ──────────────────────────────────────

class TestRbacSeeded:
    def test_non_admin_cannot_edit_or_delete_seeded(self, monkeypatch):
        seeded = _profile()
        monkeypatch.setattr("services.cover_style_registry.get_profile",
                            AsyncMock(return_value=seeded))
        client = _client(role_name="user")
        up = client.post("/api/cover/styles?style_id=medved_press",
                         headers=_hdr(USER_ID),
                         json={"name": "hack", "instruction": "",
                               "pipeline_mode": "generate_then_edit"})
        assert up.status_code == 403
        dl = client.delete("/api/cover/styles/medved_press",
                           headers=_hdr(USER_ID))
        assert dl.status_code == 403
        up_ref = client.post(
            "/api/cover/styles/medved_press/references", headers=_hdr(USER_ID),
            json={"filename": "x.png",
                  "content_base64": base64.b64encode(b"PNG").decode()})
        assert up_ref.status_code == 403

    def test_non_admin_can_clone_seeded(self, monkeypatch):
        monkeypatch.setattr("services.cover_style_registry.get_profile",
                            AsyncMock(return_value=_profile()))
        monkeypatch.setattr("services.cover_style_registry.duplicate_profile",
                            AsyncMock(return_value="csp_copy"))
        monkeypatch.setattr(
            "services.cover_style_registry.get_profile_with_refs",
            AsyncMock(return_value=_profile(profile_id="csp_copy",
                                            origin="custom")))
        client = _client(role_name="user")
        resp = client.post("/api/cover/styles/medved_press/duplicate",
                           headers=_hdr(USER_ID))
        assert resp.status_code == 200, resp.text
        assert resp.json()["origin"] == "custom"

    def test_non_admin_cannot_test_seeded_style(self, monkeypatch):
        """M-ASAP42-1: backend-guard `_assert_can_edit_seeded` в
        `cover_test_style` — non-admin не запускает Test Style на seeded:
        403 ДО генерации base/edit (не мутирует preview seeded, не тратит
        платный image-budget). UI прячет кнопку, но API обязан закрывать."""
        monkeypatch.setattr(
            "services.cover_style_registry.get_profile_with_refs",
            AsyncMock(return_value=_profile()))
        gen = AsyncMock(return_value=(None, "must_not_run"))
        monkeypatch.setattr(
            "services.image_generation.generate_image_verbose", gen)
        run = AsyncMock(return_value={"applied": True, "styled_path": "x"})
        monkeypatch.setattr("services.cover_style_jobs.run_style_preview", run)
        resp = _client(role_name="user").post(
            "/api/cover/test-style", headers=_hdr(USER_ID),
            json={"profile_id": "medved_press"})
        assert resp.status_code == 403, resp.text
        gen.assert_not_awaited()
        run.assert_not_awaited()

    def test_admin_can_test_seeded_style(self, monkeypatch, tmp_path):
        """Админ проходит guard и получает обычный Test Style-результат."""
        styled = tmp_path / "styled.jpg"
        styled.write_bytes(b"STYLED")
        _patch_test_style(monkeypatch, tmp_path, _profile(),
                          {"applied": True, "styled_path": str(styled),
                           "preview_issue": "ВЫПУСК 00"})
        resp = _client(role_name="admin").post(
            "/api/cover/test-style", headers=_hdr(),
            json={"profile_id": "medved_press"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["applied"] is True


# ── MiniApp layout contract (T-4823/T-4825/T-4826/T-4827) ──────────────────

def _html() -> str:
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _app_js() -> str:
    return (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _css() -> str:
    return (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


class TestModulesQuickAccess:
    def test_quick_access_panel_absent(self):
        html = _html()
        start = html.index("activeTab === 'modules'")
        end = html.index("activeTab === 'oversight'", start)
        branch = html[start:end]
        for marker in ("module-quick-wrap", "module-quick-item",
                       "quickpickVisible", "Быстрое управление",
                       'v-for="m in filteredModules"'):
            if marker == 'v-for="m in filteredModules"':
                assert marker in branch, marker
            else:
                assert marker not in branch, marker


class TestMoreSheetClosedContract:
    def test_more_sheet_is_unmounted_when_closed(self):
        html = _html()
        idx = html.index('class="more-sheet" data-glass="shell"')
        # ближайший v-if перед тегом содержит moreOpen (unmount, не overlay)
        window = html[max(0, idx - 220):idx]
        assert "moreOpen" in window, \
            "closed .more-sheet должен отсутствовать в DOM (v-if moreOpen)"
        assert "<transition name=\"more-sheet\">" in html
        # старый «всегда смонтирован» паттерн удалён
        assert ':class="{ open: moreOpen }"' not in html
        # transition-классы в CSS (анимация без dormant-overlay)
        css = _css()
        assert ".more-sheet-enter-from" in css
        assert ".more-sheet-leave-to" in css


class TestStyleCardsCompact:
    def test_compact_before_after_and_material_arrow(self):
        html = _html()
        for marker in ("data-cover-mini-before", "data-cover-mini-after",
                       "data-cover-mini-arrow", "cover-mini",
                       "data-cover-preview-source"):
            assert marker in html, marker
        # Material arrow (не текстовый «→»)
        assert "iconGlyph('chevron_right')" in html
        assert 'class="text-gray-400 text-xl flex-none">→<' not in html
        css = _css()
        assert ".cover-mini {" in css
        assert ".cover-mini-arrow" in css
        # editor preview компактный (ограничен max-width/height)
        assert ".cover-preview {" in css
        assert "max-width: 11rem" in css and "max-height: 11rem" in css


class TestHumanNaming:
    def test_machine_reason_only_in_developer_details(self):
        html = _html()
        assert "data-cover-test-human" in html
        assert "data-cover-developer-toggle" in html
        assert "data-cover-developer-reason" in html
        assert "developer_reason" in _app_js()
        # основной вид — человеческая фраза «Стиль не применён…»
        assert "провайдер отклонил запрос" in _html() \
            or "провайдер отклонил запрос" in _app_js()
