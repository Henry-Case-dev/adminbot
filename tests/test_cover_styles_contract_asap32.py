"""ASAP-3.2 (ADR-1028-5 D14, §93–§95, §120–§122, §135) — контракт хранения
Cover Styles: API → real registry → PgDatabase → pool.

§120: тесты API list/create/update/duplicate/references/asset GET через
РЕАЛЬНЫЙ ``cover_style_registry`` (БЕЗ monkeypatch registry) с fake
PgDatabase (``.pool`` + asyncpg-подобный контракт). Регрессия обязательна:
на pre-fix реализации (raw Pool на месте PgDatabase) список возвращал ``[]``
fail-open — эти тесты падают.

§121: static contract guard — в ``web/api/cover_styles.py`` запрещено
передавать ``_pool(cache)`` в ``registry.*``; хелпер ``_pool`` удалён.

§135: seeded-стиль мутирует только админ (backend enforcement); обычный
пользователь с базовым доступом может использовать/выбирать.
"""
import asyncio
import base64
import json
import re
import time
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import cover_style_assets as assets
from services import cover_style_registry as registry
from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api.cover_styles import cover_styles_router

pytestmark = pytest.mark.asap32

TEST_TOKEN = "123456:TEST_CONTRACT_TOKEN"
ADMIN_ID = 111222
USER_ID = 999888
SEED_DIR = Path(__file__).resolve().parents[1] / "extra_images"


# ── fake asyncpg-подобный pool (in-memory) ──────────────────────────────────

class FakeDB:
    def __init__(self):
        self.profiles = {}          # pid -> dict
        self.refs = {}              # pid -> {rid: dict}
        self.assets = {}            # aid -> dict
        self.connections = {}       # cid -> dict


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def transaction(self):
        return self

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT asset_id FROM cover_style_assets"):
            sha, scope = args
            for a in self.db.assets.values():
                if (a.get("sha256") == sha
                        and a.get("scope", "global") == scope
                        and not a.get("deleted_at")):
                    return {"asset_id": a["asset_id"]}
            return None
        if s.startswith("SELECT * FROM cover_style_assets WHERE asset_id"):
            a = self.db.assets.get(args[0])
            if a is not None and not a.get("deleted_at"):
                return dict(a)
            return None
        if s.startswith("SELECT revision FROM cover_style_profiles"):
            p = self.db.profiles.get(args[0])
            if p is not None and not p.get("is_deleted"):
                return {"revision": p.get("revision", 1)}
            return None
        if s.startswith("SELECT * FROM cover_style_profiles WHERE profile_id"):
            p = self.db.profiles.get(args[0])
            if p is not None and not p.get("is_deleted"):
                return dict(p)
            return None
        if s.startswith("SELECT profile_id FROM cover_style_profiles"):
            p = self.db.profiles.get(args[0])
            if p is not None and p.get("is_deleted"):
                return {"profile_id": args[0]}
            return None
        if s.startswith("SELECT * FROM cover_style_connections"):
            c = self.db.connections.get(args[0])
            if c is not None and not c.get("deleted_at"):
                return dict(c)
            return None
        if s.startswith("SELECT issue_number FROM cover_style_issue_assignments"):
            pid, run_id = args
            key = (pid, run_id)
            val = self.db.issue.get(key) if hasattr(self.db, "issue") else None
            return {"issue_number": val} if val is not None else None
        if s.startswith("UPDATE cover_style_profiles SET counter_value"):
            p = self.db.profiles.get(args[0])
            if p is None:
                return None
            p["counter_value"] = int(p.get("counter_value") or 0) + 1
            return {"counter_value": p["counter_value"]}
        return None

    async def fetch(self, sql, *args):
        s = " ".join(sql.split())
        if "FROM cover_style_profiles WHERE is_deleted = false" in s:
            rows = [dict(p) for p in self.db.profiles.values()
                    if not p.get("is_deleted")]
            if "AND enabled = true" in s:
                rows = [r for r in rows if r.get("enabled")]
            rows.sort(key=lambda r: (
                0 if r.get("origin") == "seeded_example" else 1,
                r.get("name") or ""))
            return rows
        if "FROM cover_style_references WHERE profile_id" in s:
            pid = args[0]
            rows = [dict(r) for r in self.db.refs.get(pid, {}).values()]
            rows.sort(key=lambda r: (r.get("ordering", 0), 0))
            return rows
        if "JOIN cover_style_profiles" in s:
            aid = args[0]
            out = []
            for pid, refs in self.db.refs.items():
                for r in refs.values():
                    if r.get("asset_id") == aid:
                        p = self.db.profiles.get(pid)
                        if p is not None and not p.get("is_deleted"):
                            out.append({"profile_id": pid,
                                        "name": p.get("name")})
            return out
        return []

    async def execute(self, sql, *args):
        s = " ".join(sql.split())

        class _Cursor:
            def __init__(self, n):
                self.rowcount = n

        if s.startswith("INSERT INTO cover_style_assets"):
            (aid, scope, filename, mime, size, sha, origin, disk) = args
            self.db.assets[aid] = {
                "asset_id": aid, "scope": scope, "filename": filename,
                "mime": mime, "size_bytes": size, "sha256": sha,
                "origin": origin, "disk_path": disk, "deleted_at": None}
            return _Cursor(1)
        if s.startswith("UPDATE cover_style_assets SET deleted_at"):
            a = self.db.assets.get(args[0])
            if a is not None:
                a["deleted_at"] = "now"
                return _Cursor(1)
            return _Cursor(0)
        if s.startswith("INSERT INTO cover_style_profiles"):
            (pid, name, origin, pipeline_mode, instruction, counter_enabled,
             counter_value, counter_format, model_mode, connection_id,
             model_id, preview_before, preview_after, preview_rev,
             enabled, validation_mode) = args
            self.db.profiles[pid] = {
                "profile_id": pid, "name": name, "origin": origin,
                "pipeline_mode": pipeline_mode, "instruction": instruction,
                "counter_enabled": counter_enabled,
                "counter_value": counter_value,
                "counter_format": counter_format, "model_mode": model_mode,
                "connection_id": connection_id, "model_id": model_id,
                "preview_before_asset_id": preview_before,
                "preview_after_asset_id": preview_after,
                "preview_revision": preview_rev, "revision": 1,
                "enabled": enabled, "validation_mode": validation_mode,
                "is_deleted": False}
            return _Cursor(1)
        if s.startswith("UPDATE cover_style_profiles SET name="):
            (pid, name, pipeline_mode, instruction, counter_enabled,
             counter_value, counter_format, model_mode, connection_id,
             model_id, preview_before, preview_after, preview_rev,
             enabled, validation_mode) = args
            p = self.db.profiles.get(pid)
            if p is None:
                return _Cursor(0)
            p.update({"name": name, "pipeline_mode": pipeline_mode,
                      "instruction": instruction,
                      "counter_enabled": counter_enabled,
                      "counter_value": counter_value,
                      "counter_format": counter_format,
                      "model_mode": model_mode,
                      "connection_id": connection_id, "model_id": model_id,
                      "preview_before_asset_id": preview_before,
                      "preview_after_asset_id": preview_after,
                      "preview_revision": preview_rev,
                      "enabled": enabled,
                      "validation_mode": validation_mode})
            p["revision"] = int(p.get("revision") or 1) + 1
            return _Cursor(1)
        if s.startswith("UPDATE cover_style_profiles SET is_deleted"):
            p = self.db.profiles.get(args[0])
            if p is not None:
                p["is_deleted"] = True
                return _Cursor(1)
            return _Cursor(0)
        if s.startswith("UPDATE cover_style_profiles SET "
                        "preview_after_asset_id"):
            p = self.db.profiles.get(args[0])
            if p is None:
                return _Cursor(0)
            p["preview_after_asset_id"] = args[1]
            if len(args) >= 4:
                if not p.get("preview_before_asset_id"):
                    p["preview_before_asset_id"] = args[2]
                p["preview_revision"] = args[3]
            else:
                p["preview_revision"] = args[2]
            return _Cursor(1)
        if s.startswith("INSERT INTO cover_style_references"):
            rid, pid, asset_id, label, description, ordering = args
            self.db.refs.setdefault(pid, {})[rid] = {
                "ref_id": rid, "profile_id": pid, "asset_id": asset_id,
                "label": label, "description": description,
                "ordering": ordering}
            return _Cursor(1)
        if s.startswith("DELETE FROM cover_style_references"):
            pid, rid = args
            bucket = self.db.refs.get(pid, {})
            if rid in bucket:
                del bucket[rid]
                return _Cursor(1)
            return _Cursor(0)
        if s.startswith("UPDATE cover_style_references SET"):
            pid, rid, asset_id, label, description = args
            r = self.db.refs.get(pid, {}).get(rid)
            if r is None:
                return _Cursor(0)
            if asset_id:
                r["asset_id"] = asset_id
            if label:
                r["label"] = label
            if description:
                r["description"] = description
            return _Cursor(1)
        if s.startswith("INSERT INTO cover_style_connections"):
            cid, label, provider, base_url, api_key = args
            existing = self.db.connections.get(cid) or {}
            self.db.connections[cid] = {
                "connection_id": cid, "label": label, "provider": provider,
                "base_url": base_url,
                "api_key": api_key or existing.get("api_key", ""),
                "deleted_at": None}
            return _Cursor(1)
        if s.startswith("UPDATE cover_style_connections SET deleted_at"):
            c = self.db.connections.get(args[0])
            if c is not None:
                c["deleted_at"] = "now"
                return _Cursor(1)
            return _Cursor(0)
        if s.startswith("INSERT INTO cover_style_issue_assignments"):
            pid, run_id, issue = args
            if not hasattr(self.db, "issue"):
                self.db.issue = {}
            self.db.issue.setdefault((pid, run_id), issue)
            return _Cursor(1)
        return _Cursor(0)


class FakePool:
    def __init__(self, db: FakeDB):
        self._db = db

    def acquire(self):
        return FakeConn(self._db)


class FakePgDatabase:
    """Мимикрия PgDatabase: поле `.pool` — ровно контракт реестра."""

    def __init__(self):
        self.pool = FakePool(FakeDB())


# ── API harness (БЕЗ monkeypatch registry) ──────────────────────────────────

def make_init_data(token: str, user_id: int) -> str:
    import hashlib
    import hmac
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "a"}, separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, v) for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _client(pg, *, user_role="admin"):
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    if user_role == "admin":
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
    cache._pg_available = True
    cache._initialized = True
    cache._pg = pg
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
    monkeypatch.setenv("COVER_STYLE_ASSETS_DIR", str(tmp_path / "assets"))
    (tmp_path / "assets").mkdir(exist_ok=True)


PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")).decode()


# ── §120: сквозные тесты контракта (API → registry → PgDatabase) ────────────

def _run(coro):
    """Синхронно выполнить async-функцию реестра (тесты — sync; TestClient
    живёт в своём портале)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seed(pg):
    return _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))


class TestPgDatabaseContract:
    def test_seed_and_list_via_public_api(self):
        """§119/§98: seed через реестр → GET /api/cover/styles содержит
        `medved_press` c 1 reference и before/after asset id. НА PRE-FIX
        (raw Pool на месте PgDatabase) этот тест падал: list → []."""
        pg = FakePgDatabase()
        seeded = _seed(pg)
        assert seeded is not None, "seed создан"
        client = _client(pg)
        resp = client.get("/api/cover/styles", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        ids = [s["profile_id"] for s in body["styles"]]
        assert "medved_press" in ids, "seeded виден через ПУБЛИЧНЫЙ API"
        style = next(s for s in body["styles"]
                     if s["profile_id"] == "medved_press")
        assert style["is_example"] is True
        assert style["reference_count"] == 1
        assert style["preview_before_asset_id"]
        assert style["preview_after_asset_id"]

    def test_create_update_delete_roundtrip_real_registry(self):
        """§94: POST → 200 (не 503 «save failed»), reload сохраняет."""
        pg = FakePgDatabase()
        client = _client(pg)
        resp = client.post("/api/cover/styles", json={
            "name": "Мой стиль", "instruction": "делай красиво",
            "pipeline_mode": "generate_then_edit"}, headers=_hdr())
        assert resp.status_code == 200, resp.text
        style_id = resp.json()["profile_id"]
        # reload — persisted
        again = client.get(f"/api/cover/styles/{style_id}", headers=_hdr())
        assert again.status_code == 200
        assert again.json()["name"] == "Мой стиль"
        # update
        up = client.post(f"/api/cover/styles?style_id={style_id}", json={
            "name": "Мой стиль 2", "instruction": "ещё лучше",
            "pipeline_mode": "generate_then_edit"}, headers=_hdr())
        assert up.status_code == 200
        detail = client.get(f"/api/cover/styles/{style_id}", headers=_hdr())
        assert detail.json()["name"] == "Мой стиль 2"
        assert detail.json()["revision"] == 2
        # delete
        resp = client.delete(f"/api/cover/styles/{style_id}", headers=_hdr())
        assert resp.status_code == 200
        gone = client.get(f"/api/cover/styles/{style_id}", headers=_hdr())
        assert gone.status_code == 404

    def test_duplicate_and_reference_crud(self):
        """§63/§101: duplicate; reference upload→thumbnail→replace→remove."""
        pg = FakePgDatabase()
        client = _client(pg)
        created = client.post("/api/cover/styles", json={
            "name": "Источник", "instruction": "",
            "pipeline_mode": "generate_then_edit"}, headers=_hdr())
        sid = created.json()["profile_id"]
        # upload reference
        up = client.post(f"/api/cover/styles/{sid}/references", json={
            "filename": "logo.png", "content_base64": PNG_1PX,
            "label": "Логотип", "description": "знак"}, headers=_hdr())
        assert up.status_code == 200, up.text
        refs = up.json()["references"]
        assert len(refs) == 1
        ref_id = refs[0]["ref_id"]
        asset_id = refs[0]["asset_id"]
        assert refs[0]["url"] == f"/api/cover/assets/{asset_id}"
        # duplicate — референс копируется
        dup = client.post(f"/api/cover/styles/{sid}/duplicate",
                          headers=_hdr())
        assert dup.status_code == 200
        dup_id = dup.json()["profile_id"]
        assert dup_id != sid
        assert dup.json()["reference_count"] == 1
        # replace
        rep = client.put(
            f"/api/cover/styles/{sid}/references/{ref_id}", json={
                "filename": "logo2.png", "content_base64": PNG_1PX,
                "label": "Логотип 2"}, headers=_hdr())
        assert rep.status_code == 200
        assert rep.json()["references"][0]["label"] == "Логотип 2"
        # remove
        rem = client.delete(
            f"/api/cover/styles/{sid}/references/{ref_id}", headers=_hdr())
        assert rem.status_code == 200
        assert rem.json()["reference_count"] == 0

    def test_asset_get_returns_real_bytes_and_missing_integrity(self):
        """§100: asset GET → реальные байты; файл удалён с диска →
        integrity 404 (не тихое «нет превью»)."""
        pg = FakePgDatabase()
        client = _client(pg)
        created = client.post("/api/cover/styles", json={
            "name": "С", "instruction": "",
            "pipeline_mode": "generate_then_edit"}, headers=_hdr())
        sid = created.json()["profile_id"]
        up = client.post(f"/api/cover/styles/{sid}/references", json={
            "filename": "logo.png", "content_base64": PNG_1PX},
            headers=_hdr())
        asset_id = up.json()["references"][0]["asset_id"]
        got = client.get(f"/api/cover/assets/{asset_id}", headers=_hdr())
        assert got.status_code == 200
        assert got.content[:8] == bytes.fromhex("89504e470d0a1a0a")
        # файл с диска исчез → integrity error
        disk = pg.pool._db.assets[asset_id]["disk_path"]
        Path(disk).unlink(missing_ok=True)
        missing = client.get(f"/api/cover/assets/{asset_id}", headers=_hdr())
        assert missing.status_code == 404
        assert "отсутствует" in missing.json()["detail"]

    def test_regression_raw_pool_fails_open_pgdatabase_works(self):
        """§120 regression (падает на pre-fix): raw Pool на месте PgDatabase
        → fail-open `[]`; PgDatabase → данные. Контракт ровно один."""
        pg = FakePgDatabase()
        _seed(pg)
        raw_pool = pg.pool                     # ← pre-fix API передавал ЭТО
        raw_result = _run(registry.list_profiles(raw_pool))
        assert raw_result == [], (
            "raw Pool не является контрактом реестра (fail-open)")
        proper = _run(registry.list_profiles(pg))
        assert len(proper) == 1

    def test_seed_idempotent_and_deleted_not_resurrected(self):
        """§99: повторный seed — no-op; удалённый владельцем НЕ воскрешается."""
        pg = FakePgDatabase()
        first = _seed(pg)
        assert first is not None
        # редактируем владельцем
        edited = dict(first)
        edited["name"] = "Переименовано владельцем"
        assert _run(registry.upsert_profile(pg, edited))
        second = _seed(pg)
        assert second["name"] == "Переименовано владельцем", \
            "повторный seed не перезатирает правки владельца"
        assert len(pg.pool._db.profiles) == 1, "без дублей"
        # владелец удаляет → seed НЕ воскрешает
        assert _run(registry.soft_delete_profile(pg, "medved_press"))
        third = _seed(pg)
        assert third is None
        assert pg.pool._db.profiles["medved_press"]["is_deleted"] is True


# ── §104: connection model (FK, не raw URL; секреты в Connections) ──────────

class TestConnectionModel:
    def test_connection_crud_and_fk_validation(self):
        pg = FakePgDatabase()
        client = _client(pg)
        # create connection
        resp = client.post("/api/cover/connections", json={
            "connection_id": "csc_1", "label": "NanoGPT Images",
            "provider": "nanogpt", "base_url": "https://nano-gpt.com/v1",
            "api_key": "sk-secret"}, headers=_hdr())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["api_key_set"] is True
        assert "sk-secret" not in json.dumps(body), "секрет не возвращается"
        # profile с raw URL → 422 (Base URL принадлежит Connections)
        bad = client.post("/api/cover/styles", json={
            "name": "S", "instruction": "",
            "pipeline_mode": "generate_then_edit",
            "model_mode": "custom",
            "connection_id": "https://custom/v1"}, headers=_hdr())
        assert bad.status_code == 422
        # profile с несуществующим FK → 422
        missing = client.post("/api/cover/styles", json={
            "name": "S", "instruction": "",
            "pipeline_mode": "generate_then_edit",
            "model_mode": "custom",
            "connection_id": "csc_missing"}, headers=_hdr())
        assert missing.status_code == 422
        # profile с валидным FK → 200
        ok = client.post("/api/cover/styles", json={
            "name": "S", "instruction": "",
            "pipeline_mode": "generate_then_edit",
            "model_mode": "custom", "connection_id": "csc_1",
            "model_id": "qwen-image-3-pro"}, headers=_hdr())
        assert ok.status_code == 200
        detail = client.get(
            f"/api/cover/styles/{ok.json()['profile_id']}", headers=_hdr())
        assert detail.json()["connection"]["connected"] is True
        assert detail.json()["connection"]["connection_id"] == "csc_1"


# ── §135: права — seeded мутирует только админ ──────────────────────────────

class TestPermissionsSeeded:
    def test_non_admin_can_list_and_select(self, monkeypatch):
        pg = FakePgDatabase()
        _seed(pg)
        # chat_params — НЕ registry-граница (§120); стабим запись выбора.

        async def _fake_set(chat_id, params, changed_by=None):
            return True

        monkeypatch.setattr("services.chat_params.set_chat_params",
                            _fake_set)
        client = _client(pg, user_role="user")
        resp = client.get("/api/cover/styles", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        ids = [s["profile_id"] for s in resp.json()["styles"]]
        assert "medved_press" in ids, "non-admin видит seeded для выбора"
        sel = client.post("/api/cover/select", json={
            "chat_id": -100, "style_id": "medved_press"},
            headers=_hdr(USER_ID))
        assert sel.status_code == 200, "non-admin может выбрать/использовать"

    def test_non_admin_cannot_mutate_seeded_or_bypass(self):
        """§135 backend enforcement: прямое mutation API без права → 403,
        PostgreSQL НЕ изменяется."""
        pg = FakePgDatabase()
        _seed(pg)
        before = json.dumps(pg.pool._db.profiles, sort_keys=True)
        client = _client(pg, user_role="user")
        for method, url, payload in (
            ("post", "/api/cover/styles?style_id=medved_press", {
                "name": "hack", "instruction": "",
                "pipeline_mode": "generate_then_edit"}),
            ("delete", "/api/cover/styles/medved_press", None),
            ("post", "/api/cover/styles/medved_press/duplicate", None),
        ):
            fn = getattr(client, method)
            if payload is None:
                resp = fn(url, headers=_hdr(USER_ID))
            else:
                resp = fn(url, json=payload, headers=_hdr(USER_ID))
            assert resp.status_code == 403, (method, url, resp.status_code)
        after = json.dumps(pg.pool._db.profiles, sort_keys=True)
        assert before == after, "seeded не изменён без права"


# ── §121: static contract guard ─────────────────────────────────────────────

class TestStaticContractGuard:
    def test_api_never_passes_raw_pool_to_registry(self):
        """§121: в web/api/cover_styles.py запрещено `registry.*(_pool(...)`
        и хелпер `_pool` (распаковка pg.pool до реестра) — контракт ровно
        один: registry получает PgDatabase."""
        source = Path("web/api/cover_styles.py").read_text(encoding="utf-8")
        assert "def _pool(" not in source, \
            "хелпер _pool(cache) удалён (единственный контракт — _pg)"
        assert not re.search(r"registry\.\w+\(\s*_pool\(", source), \
            "registry.* получает PgDatabase, а не raw pool"
        skip_prefixes = ("ORIGIN_", "MODE_", "SEEDED", "PIPELINE", "preview_",
                         "format_issue", "build_revision_snapshot",
                         "_public_connection")
        for m in re.finditer(r"registry\.(\w+)\(", source):
            name = m.group(1)
            if any(name.startswith(p) or name == p.rstrip("_")
                   for p in skip_prefixes):
                continue
            tail = source[m.end():m.end() + 40]
            first_arg = re.match(r"\s*([A-Za-z_][\w.]*)", tail)
            if first_arg:
                assert first_arg.group(1) in ("pg", "_pg", "None", "obj"), \
                    (f"registry.{name}: первый аргумент "
                     f"{first_arg.group(1)!r} — не PgDatabase-уровень")

    def test_jobs_and_pipeline_use_pgdatabase_level(self):
        jobs_src = Path("services/cover_style_jobs.py").read_text(
            encoding="utf-8")
        # jobs резолвит slot через pg (PgDatabase), не через raw pool
        assert "resolve_style_slot(profile=profile, connection=_connection)" \
            in jobs_src
