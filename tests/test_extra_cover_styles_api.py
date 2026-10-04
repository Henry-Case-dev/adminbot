"""EXTRA Pass 2 (ADR-1028-4 D12; spec §3.5–§3.9/§12/§36–§38/§56/§63–§67/§73–§74) —
Style Registry/Editor API: список/CRUD/references/preview/capability/connections.

Права — только глобальный админ; kill-switch; R17 (секретов наружу нет);
dangling-guard §64; Test Style не расходует counter; RU-сообщения §75.
"""
import base64
import json
import time
import types
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import image_capabilities as cap
from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api.cover_styles import (
    MAX_UPLOAD_BYTES,
    NO_STYLE_LABEL,
    _public_profile,
    cover_styles_router,
)
from web.api.deps import get_tma_user  # noqa: F401  (сборка зависимостей)

TEST_TOKEN = "123456:TEST_COVER_STYLES_TOKEN"
ADMIN_ID = 111222
USER_ID = 999888


def make_init_data(token: str, user_id: int = ADMIN_ID) -> str:
    import hashlib
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
        "profile_id": "csp_x", "name": "Графический роман Медведь Press",
        "origin": "seeded_example", "pipeline_mode": "generate_then_edit",
        "instruction": "instr", "counter_enabled": True, "counter_value": 5,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 2,
        "enabled": True, "preview_before_asset_id": "cas_before",
        "preview_after_asset_id": "cas_after", "preview_revision": None,
        "references": [{"ref_id": "r1", "asset_id": "cas_ref", "label": "logo",
                        "description": "знак", "ordering": 0}],
    }
    p.update(over)
    return p


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


def _client(pg=None):
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    cache._roles = {
        "admin": {"permissions": {"wildcard": True}, "is_custom": False},
        "user": {"permissions": {}, "is_custom": False},
    }
    cache._permissions = {n: Permissions.from_dict(r["permissions"])
                          for n, r in cache._roles.items()}
    cache._admins = {ADMIN_ID: "admin"}
    cache._pg_available = False
    cache._initialized = True
    cache._pg = pg if pg is not None else types.SimpleNamespace(pool=object())
    app = FastAPI()
    app.state.cache = cache
    app.include_router(cover_styles_router, prefix="/api")
    return TestClient(app)


def _hdr(user=ADMIN_ID):
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user)}


def test_list_disabled_kill_switch(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: False)
    resp = _client().get("/api/cover/styles", headers=_hdr())
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False and body["styles"] == []
    assert body["no_style_label"] == NO_STYLE_LABEL


def test_list_shape_and_no_secret_leak(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.list_profiles",
        AsyncMock(return_value=[_profile()]))
    monkeypatch.setattr(
        "services.cover_style_registry.list_references",
        AsyncMock(return_value=[{"ref_id": "r1", "asset_id": "cas_ref",
                                 "label": "logo", "description": "d",
                                 "ordering": 0}]))
    monkeypatch.setattr(
        "services.cover_style_pipeline.resolve_selected_style_id",
        AsyncMock(return_value="csp_x"))
    resp = _client().get("/api/cover/styles?chat_id=-100",
                         headers=_hdr())
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_style_id"] == "csp_x"
    style = body["styles"][0]
    assert style["is_example"] is True
    assert style["reference_count"] == 1
    # ASAP 4.3 (§4/§5): placeholder-указатели (preview_revision=None) НЕ
    # отдаются как реальная пара; placeholders приходят отдельно.
    assert style["preview_before_url"] is None
    assert style["preview_after_url"] is None
    assert style["preview_pair_valid"] is False
    assert body["placeholders"]["before_url"]
    assert body["placeholders"]["after_url"]
    assert "api_key" not in json.dumps(body)


def test_detail_not_found(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=None))
    assert _client().get("/api/cover/styles/nope",
                         headers=_hdr()).status_code == 404


def test_upsert_requires_admin():
    resp = _client().post("/api/cover/styles", headers=_hdr(user=USER_ID),
                          json={"name": "X"})
    assert resp.status_code == 403


def test_upsert_invalid_mode(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    resp = _client().post("/api/cover/styles", headers=_hdr(),
                          json={"name": "X", "pipeline_mode": "bogus"})
    assert resp.status_code == 422


def test_upsert_create_ok(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)

    async def _upsert(pg, profile, **_kw):
        profile["profile_id"] = profile.get("profile_id") or "csp_new"
        return True

    monkeypatch.setattr("services.cover_style_registry.upsert_profile", _upsert)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=_profile(profile_id="csp_new", origin="custom",
                                        name="Мой стиль")))
    resp = _client().post("/api/cover/styles", headers=_hdr(),
                          json={"name": "Мой стиль", "instruction": "i",
                                "counter_enabled": True, "counter_value": 1})
    assert resp.status_code == 200
    assert resp.json()["profile_id"] == "csp_new"


def test_duplicate(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.duplicate_profile",
        AsyncMock(return_value="csp_copy"))
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=_profile(profile_id="csp_copy",
                                        origin="custom")))
    resp = _client().post("/api/cover/styles/csp_x/duplicate", headers=_hdr())
    assert resp.status_code == 200
    assert resp.json()["profile_id"] == "csp_copy"


def test_delete(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.soft_delete_profile",
        AsyncMock(return_value=True))
    resp = _client().delete("/api/cover/styles/csp_x", headers=_hdr())
    assert resp.status_code == 200 and resp.json()["deleted"] is True


def test_select_per_chat(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile",
        AsyncMock(return_value=_profile()))
    get_calls = {}
    set_calls = {}

    async def _get_all(chat_id, pg=None):
        get_calls["chat_id"] = chat_id
        get_calls["pg"] = pg
        return {"v": 1, "overrides": {"flags.summary_enabled": True},
                "gates": {}, "keys": {}, "perm_overrides": {}, "meta": {}}

    async def _set(chat_id, patch, **kw):
        set_calls["chat_id"] = chat_id
        set_calls["patch"] = patch
        set_calls["pg"] = kw.get("pg")
        return {}

    monkeypatch.setattr("services.chat_params.get_all_chat_params", _get_all)
    monkeypatch.setattr("services.chat_params.set_chat_params", _set)
    resp = _client().post("/api/cover/select", headers=_hdr(),
                          json={"chat_id": -100, "style_id": "csp_x"})
    assert resp.status_code == 200
    # HOTFIX 2.58.43: pg= обязателен (без него ChatLorePgUnavailable → 503),
    # патч — namespace overrides (плоский ключ set_chat_params выбрасывает),
    # read-modify-write — чужие overrides чата сохраняются.
    assert set_calls["patch"] == {"overrides": {
        "flags.summary_enabled": True,
        "prompts.summary_cover_style_id": "csp_x"}}
    assert set_calls["pg"] is not None
    assert set_calls["pg"] is get_calls["pg"]
    assert get_calls["chat_id"] == -100


def test_select_clear_removes_override(monkeypatch):
    """Снятие выбора (пустой style_id) удаляет override, а не хард-пинит
    пустоту: работает resolve-чейн override → hot.get → дефолт (DC-5)."""
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    set_calls = {}

    async def _get_all(chat_id, pg=None):
        return {"v": 1,
                "overrides": {"prompts.summary_cover_style_id": "csp_x",
                              "flags.summary_enabled": True},
                "gates": {}, "keys": {}, "perm_overrides": {}, "meta": {}}

    async def _set(chat_id, patch, **kw):
        set_calls["patch"] = patch
        return {}

    monkeypatch.setattr("services.chat_params.get_all_chat_params", _get_all)
    monkeypatch.setattr("services.chat_params.set_chat_params", _set)
    resp = _client().post("/api/cover/select", headers=_hdr(),
                          json={"chat_id": -100, "style_id": ""})
    assert resp.status_code == 200
    assert "prompts.summary_cover_style_id" \
        not in set_calls["patch"]["overrides"]
    # чужой override не затёрт
    assert set_calls["patch"]["overrides"] == {"flags.summary_enabled": True}


def test_upload_reference_base64(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile",
        AsyncMock(return_value=_profile()))
    monkeypatch.setattr(
        "services.cover_style_assets.store_file_bytes",
        lambda data, filename="", origin="upload", **kw: {
            "asset_id": "cas_new", "scope": "global", "filename": filename,
            "mime": "image/png", "size_bytes": len(data), "sha256": "s",
            "origin": origin, "disk_path": "x"})
    monkeypatch.setattr("services.cover_style_registry.upsert_asset",
                        AsyncMock(return_value=True))
    monkeypatch.setattr("services.cover_style_registry.list_references",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr("services.cover_style_registry.add_reference",
                        AsyncMock(return_value="r1"))
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=_profile()))
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 8).decode()
    resp = _client().post("/api/cover/styles/csp_x/references", headers=_hdr(),
                          json={"filename": "a.png", "content_base64": png,
                                "label": "logo", "description": "d"})
    assert resp.status_code == 200
    assert resp.json()["profile_id"] == "csp_x"


def test_upload_reference_bad_format(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile",
        AsyncMock(return_value=_profile()))
    monkeypatch.setattr("services.cover_style_assets.store_file_bytes",
                        lambda *a, **kw: None)
    resp = _client().post("/api/cover/styles/csp_x/references", headers=_hdr(),
                          json={"filename": "a.gif",
                                "content_base64": base64.b64encode(b"GIF").decode()})
    assert resp.status_code == 422


def test_dangling_guard(monkeypatch):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr("services.cover_style_registry.references_using_asset",
                        AsyncMock(return_value=[{"profile_id": "csp_x",
                                                 "name": "S"}]))
    removed = {"n": 0}

    async def _rm(pg, profile_id, ref_id):
        removed["n"] += 1
        return True
    monkeypatch.setattr("services.cover_style_registry.list_references",
                        AsyncMock(return_value=[{"ref_id": "r1",
                                                 "asset_id": "cas_ref"}]))
    monkeypatch.setattr("services.cover_style_registry.remove_reference", _rm)
    monkeypatch.setattr("services.cover_style_registry.soft_delete_asset",
                        AsyncMock(return_value=True))
    client = _client()
    blocked = client.delete("/api/cover/assets/cas_ref", headers=_hdr())
    assert blocked.status_code == 409
    ok = client.delete("/api/cover/assets/cas_ref?confirm=true", headers=_hdr())
    assert ok.status_code == 200 and removed["n"] == 1


def test_asset_raw_missing(monkeypatch):
    monkeypatch.setattr("services.cover_style_registry.get_asset",
                        AsyncMock(return_value=None))
    assert _client().get("/api/cover/assets/cas_x",
                         headers=_hdr()).status_code == 404


def test_capabilities_and_no_secret(monkeypatch):
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=_profile()))
    # ASAP 4.4 (§2/T-4873): endpoint использует единый effective-resolver;
    # capability-слой стыкуется на уровне image_capabilities.resolve_capabilities.
    monkeypatch.setattr(
        "services.image_capabilities.resolve_capabilities",
        lambda *a, **kw: cap.ImageModelCapabilities(
            image_edit=cap.TRUE, text_to_image=cap.TRUE, max_input_images=3,
            prompt_limit=cap.PromptLimit(value=1000, unit="chars",
                                         source="internal_config"),
            source="provider_or_registry"))
    monkeypatch.setattr(
        "services.cover_style_pipeline.connection_status",
        lambda **kw: {"configured": True, "connected": True,
                      "api_key_set": True, "edit_supported": True,
                      "message": "Подключено"})
    resp = _client().get("/api/cover/capabilities?profile_id=csp_x",
                         headers=_hdr())
    assert resp.status_code == 200
    body = resp.json()
    assert body["edit_supported"] is True
    assert body["references_available"] == 2
    assert body["prompt_limit"]["value"] == 1000
    dumped = json.dumps(body)
    assert '"api_key":' not in dumped          # ключ-значение не отдаётся
    assert "keys." not in dumped


def test_connections_status(monkeypatch):
    monkeypatch.setattr(
        "services.cover_style_pipeline.connection_status",
        lambda **kw: {"configured": False, "connected": False,
                      "api_key_set": False, "edit_supported": None,
                      "message": "Адрес и модель не настроены"})
    resp = _client().get("/api/cover/connections/status", headers=_hdr())
    assert resp.status_code == 200
    assert resp.json()["message"] == "Адрес и модель не настроены"


def _patch_upload_deps(monkeypatch, profile):
    monkeypatch.setattr("services.cover_style_pipeline.cover_styles_enabled",
                        lambda: True)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=profile))
    monkeypatch.setattr(
        "services.cover_style_assets.store_file_bytes",
        lambda data, filename="", origin="upload", **kw: {
            "asset_id": "cas_p", "scope": "global", "filename": filename,
            "mime": "image/png", "size_bytes": len(data), "sha256": "s",
            "origin": origin, "disk_path": "x"})
    monkeypatch.setattr("services.cover_style_registry.upsert_asset",
                        AsyncMock(return_value=True))


def test_test_style_start_contract(monkeypatch):
    """ASAP 4.3 (§2.2): POST возвращает {job_id,status} без ожидания;
    upload/base64 НЕ декодируется на основном пути."""
    from services import cover_style_preview as preview_jobs
    _patch_upload_deps(monkeypatch, _profile(profile_id="csp_x"))
    decode_calls = {"n": 0}
    import web.api.cover_styles as cs

    def _spy(body):
        decode_calls["n"] += 1
        return None

    monkeypatch.setattr(cs, "_decode_upload", _spy)
    start = AsyncMock(return_value={"job_id": "cov_test1",
                                    "status": "queued",
                                    "stage": "queued", "reused": False})
    monkeypatch.setattr(preview_jobs, "start_preview_job", start)
    monkeypatch.setattr(cs, "_job_db", lambda: object())
    resp = _client().post("/api/cover/test-style", headers=_hdr(),
                          json={"profile_id": "csp_x"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == "cov_test1"
    assert body["status"] == "queued"
    assert decode_calls["n"] == 0, "основной путь не читает base64 upload"


def test_test_style_status_contract_no_secrets(monkeypatch):
    """ASAP 4.3 (§2.2): status-endpoint отдаёт только safe-diagnostics."""
    from services import cover_style_preview as preview_jobs
    import web.api.cover_styles as cs
    snapshot = {
        "job_id": "cov_test1", "status": "completed", "stage": "completed",
        "started_at": 1, "last_progress_at": 2, "provider": "nanogpt",
        "model": "qwen", "human_message": "Стиль применён",
        "machine_reason": "", "preview_before_url": "/api/cover/assets/a",
        "preview_after_url": "/api/cover/assets/b", "preview_revision": 7,
        "preview_job_id": "cov_test1", "mode": "preview",
        "prompt": {"total_chars": 42, "limit": None},
    }
    monkeypatch.setattr(preview_jobs, "job_status",
                        AsyncMock(return_value=snapshot))
    monkeypatch.setattr(preview_jobs, "maybe_resume",
                        AsyncMock(return_value=False))
    monkeypatch.setattr(cs, "_job_db", lambda: object())
    resp = _client().get("/api/cover/test-style/cov_test1", headers=_hdr())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["preview_revision"] == 7
    dump = json.dumps(body).lower()
    assert "api_key" not in dump
    # полного prompt нет — только safe-числа breakdown
    assert set(body["prompt"]) <= {"style_chars", "context_chars", "refs_chars",
                                   "system_chars", "total_chars", "limit",
                                   "unit", "exceeded"}


def test_test_style_status_unknown_job_404(monkeypatch):
    from services import cover_style_preview as preview_jobs
    import web.api.cover_styles as cs
    monkeypatch.setattr(preview_jobs, "job_status",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(cs, "_job_db", lambda: object())
    resp = _client().get("/api/cover/test-style/nope", headers=_hdr())
    assert resp.status_code == 404


# ── ASAP 4.3 (§7.2, T-4847): manual prompt-limit (MiniApp) ──────────────────

class TestPromptLimitOverride:
    def _client_with_hot(self):
        import asyncio
        client = _client()
        cache = client.app.state.cache
        cache._lock = asyncio.Lock()
        cache._settings_updated_at = {}
        from services import hot_config
        hot_config.set_config_cache(cache)
        return client

    def test_manual_override_precedence_and_persistence(self):
        from services import image_capabilities as icap
        from services import hot_config
        client = self._client_with_hot()
        body = {"provider": "nanogpt", "base_url": "https://x.test/v1",
                "model": "m1", "operation": "image_edit",
                "mode": "manual", "unit": "chars", "value": 4321}
        try:
            resp = client.post("/api/cover/prompt-limit", headers=_hdr(),
                               json=body)
            assert resp.status_code == 200, resp.text
            out = resp.json()
            assert out["mode"] == "manual" and out["value"] == 4321
            assert out["source"] == icap.SOURCE_MANUAL
            # persistence: значение видно resolver'у (bot_settings-ключ)
            caps = icap.resolve_capabilities(
                "nanogpt", "https://x.test/v1", "m1",
                operation=icap.OPERATION_EDIT)
            assert caps.prompt_limit.value == 4321
            assert caps.prompt_limit.source == icap.SOURCE_MANUAL
            # GET отдаёт состояние лимита
            got = client.get("/api/cover/prompt-limit", headers=_hdr())
            assert got.status_code == 200
            # снятие manual → auto
            resp2 = client.post("/api/cover/prompt-limit", headers=_hdr(),
                                json={**body, "mode": "auto"})
            assert resp2.status_code == 200
            assert resp2.json()["mode"] == "auto"
            caps2 = icap.resolve_capabilities(
                "nanogpt", "https://x.test/v1", "m1",
                operation=icap.OPERATION_EDIT, refresh=True)
            assert caps2.prompt_limit.source != icap.SOURCE_MANUAL
        finally:
            hot_config.set_config_cache(None)

    def test_manual_override_requires_admin(self):
        from services import hot_config
        client = self._client_with_hot()
        try:
            resp = client.post(
                "/api/cover/prompt-limit", headers=_hdr(user=USER_ID),
                json={"provider": "p", "base_url": "https://x.test",
                      "model": "m", "mode": "manual", "unit": "chars",
                      "value": 100})
            assert resp.status_code == 403
        finally:
            hot_config.set_config_cache(None)

    def test_manual_limit_does_not_block_style_save(self):
        """§7.2: маленький manual-лимит НЕ запрещает сохранить стиль."""
        from services import hot_config
        client = self._client_with_hot()
        mp = pytest.MonkeyPatch()

        async def _upsert(pg, profile, **_kw):
            profile["profile_id"] = profile.get("profile_id") or "csp_new"
            return True

        mp.setattr("services.cover_style_registry.upsert_profile", _upsert)
        mp.setattr(
            "services.cover_style_registry.get_profile_with_refs",
            AsyncMock(return_value=_profile(profile_id="csp_new",
                                            origin="custom")))
        try:
            resp = client.post("/api/cover/prompt-limit", headers=_hdr(),
                               json={"provider": "p",
                                     "base_url": "https://x.test",
                                     "model": "m", "mode": "manual",
                                     "unit": "chars", "value": 1})
            assert resp.status_code == 200
            save = client.post("/api/cover/styles", headers=_hdr(),
                               json={"name": "X", "instruction": "i",
                                     "pipeline_mode": "generate_then_edit"})
            assert save.status_code == 200, save.text
        finally:
            mp.undo()
            hot_config.set_config_cache(None)


# ── M-EXTRA-1 (§10/SC-24): preview stale-revision ───────────────────────────

class TestPreviewStale:
    def test_public_profile_stale_flags(self):
        current = _profile(preview_revision=2, revision=2,
                           preview_after_asset_id="cas_after")
        assert _public_profile(current)["preview_stale"] is False
        assert _public_profile(current)["preview_pair_valid"] is True
        old = _profile(preview_revision=1, revision=3,
                       preview_after_asset_id="cas_after")
        assert _public_profile(old)["preview_stale"] is True
        assert _public_profile(old)["preview_pair_valid"] is False
        none = _profile(preview_revision=None)
        assert _public_profile(none)["preview_stale"] is False
        assert _public_profile(none)["preview_pair_valid"] is False
        assert _public_profile(none)["preview_status"] is None
        no_asset = _profile(preview_revision=1, revision=3,
                            preview_after_asset_id=None)
        assert _public_profile(no_asset)["preview_stale"] is False
        assert _public_profile(no_asset)["preview_pair_valid"] is False

    def test_current_pair_requires_both_assets_and_job_provenance(self):
        # ASAP 4.3 (§4): валидная пара текущей revision — оба ассета +
        # revision; preview_job_id отдаётся наружу (provenance job).
        valid = _profile(preview_revision=2, revision=2,
                         preview_after_asset_id="cas_after",
                         preview_before_asset_id="cas_before",
                         preview_job_id="cov_1")
        pub = _public_profile(valid)
        assert pub["preview_pair_valid"] is True
        assert pub["preview_status"] == "success"
        assert pub["preview_before_url"] == "/api/cover/assets/cas_before"
        assert pub["preview_after_url"] == "/api/cover/assets/cas_after"
        assert pub["preview_job_id"] == "cov_1"


# ── Low: §12 size-cap upload + Replace reference ────────────────────────────

def test_upload_reference_size_cap(monkeypatch):
    _patch_upload_deps(monkeypatch, _profile())
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile",
        AsyncMock(return_value=_profile()))
    big = base64.b64encode(b"x" * (MAX_UPLOAD_BYTES + 16)).decode()
    resp = _client().post("/api/cover/styles/csp_x/references", headers=_hdr(),
                          json={"filename": "a.png", "content_base64": big})
    assert resp.status_code == 413


def test_replace_reference(monkeypatch):
    _patch_upload_deps(monkeypatch, _profile())
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile",
        AsyncMock(return_value=_profile()))
    captured = {}

    async def _update(pg, profile_id, ref_id, **kw):
        captured["profile_id"] = profile_id
        captured["ref_id"] = ref_id
        captured.update(kw)
        return True

    monkeypatch.setattr("services.cover_style_registry.update_reference", _update)
    monkeypatch.setattr(
        "services.cover_style_registry.get_profile_with_refs",
        AsyncMock(return_value=_profile()))
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 8).decode()
    resp = _client().put("/api/cover/styles/csp_x/references/r1", headers=_hdr(),
                         json={"filename": "new.png", "content_base64": png,
                               "label": "logo2", "description": "new"})
    assert resp.status_code == 200
    assert captured["ref_id"] == "r1"
    assert captured["asset_id"] == "cas_p"
