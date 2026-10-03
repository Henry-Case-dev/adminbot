"""ASAP 4.2 Step 4 (T-4829, §50 Style integration) — локальный e2e-контур
реального Style Registry на **temp-SQLite** (без прода): seed реальных
`extra_images` → style list → preview → test flow → preview update → persist
после reload.

Здесь НЕ prod-БД: поднимается одноразовый SQLite-файл (удаляется вместе с
`tmp_path`) и asyncpg-совместимый thin-shim поверх `sqlite3` (реальные
registry-функции `seed_seeded_style`/`list_profiles`/`get_profile_with_refs`/
`set_preview` исполняются без моков). Провайдер генерации/edit мокается —
их live-контракт закрывается canary T-4830/T-4831 (PO-1), а не этот контур.

Покрывает §49-пункты: style seed extra_images; style preview persistence;
test-style endpoint не тратит counter и не вызывает upload; §50 Style flow.

Полный pytest НЕ гоняется (owner §49). Запуск:
    pytest tests/test_asap42_step3_style_integration.py -q
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import sqlite3
import time
import types
from datetime import datetime, timezone
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
from web.api.cover_styles import cover_styles_router

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "extra_images"
TEST_TOKEN = "123456:STEP3_STYLE_TOKEN"
ADMIN_ID = 111222


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── temp-SQLite asyncpg-compatible pool (только нужный SQL-поднабор) ─────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cover_style_profiles (
    profile_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    origin          TEXT NOT NULL DEFAULT 'custom',
    pipeline_mode   TEXT NOT NULL DEFAULT 'generate_then_edit',
    instruction     TEXT NOT NULL DEFAULT '',
    counter_enabled INTEGER NOT NULL DEFAULT 0,
    counter_value   INTEGER NOT NULL DEFAULT 0,
    counter_format  TEXT NOT NULL DEFAULT 'ВЫПУСК {counter}',
    model_mode      TEXT NOT NULL DEFAULT 'default',
    connection_id   TEXT,
    model_id        TEXT,
    preview_before_asset_id TEXT,
    preview_after_asset_id  TEXT,
    preview_revision        INTEGER,
    revision        INTEGER NOT NULL DEFAULT 1,
    enabled         INTEGER NOT NULL DEFAULT 1,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    validation_mode TEXT NOT NULL DEFAULT 'off',
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cover_style_references (
    ref_id      TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL,
    asset_id    TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    ordering    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cover_style_assets (
    asset_id    TEXT PRIMARY KEY,
    scope       TEXT NOT NULL DEFAULT 'global',
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT 'upload',
    disk_path   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at  TEXT
);
CREATE TABLE IF NOT EXISTS cover_style_issue_assignments (
    profile_id     TEXT NOT NULL,
    summary_run_id TEXT NOT NULL,
    issue_number   INTEGER NOT NULL,
    assigned_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, summary_run_id)
);
CREATE TABLE IF NOT EXISTS cover_style_provenance (
    provenance_id     TEXT PRIMARY KEY,
    summary_run_id    TEXT,
    job_id            TEXT,
    style_id          TEXT,
    style_revision    INTEGER,
    issue_number      INTEGER,
    base_asset_id     TEXT,
    final_asset_id    TEXT,
    provider          TEXT,
    model             TEXT,
    connection_id     TEXT,
    reference_asset_ids TEXT,
    status            TEXT NOT NULL,
    fallback_mode     TEXT,
    mode              TEXT NOT NULL DEFAULT 'production',
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cover_style_connections (
    connection_id TEXT PRIMARY KEY,
    label         TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    base_url      TEXT NOT NULL,
    api_key       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    TEXT
);
"""


def create_schema(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _bind(sql: str, args: tuple):
    """asyncpg `$N` → sqlite `?` с корректным переупорядочиванием аргументов."""
    nums = [int(m.group(1)) for m in re.finditer(r"\$(\d+)", sql)]
    new_sql = re.sub(r"\$(\d+)", "?", sql)
    return new_sql, tuple(args[n - 1] for n in nums)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.create_function(
        "now", 0,
        lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    return conn


class _NoopTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SqliteConn:
    def __init__(self, path: str):
        self._path = str(path)

    def _sync(self, fn):
        conn = _connect(self._path)
        try:
            return fn(conn)
        finally:
            conn.close()

    async def execute(self, sql, *args):
        def _do(conn):
            stmt, bound = _bind(sql, args)
            cur = conn.execute(stmt, bound)
            conn.commit()
            return cur.rowcount, stmt.lstrip().split()[0].upper()
        rowcount, verb = await asyncio.to_thread(self._sync, _do)
        if verb == "INSERT":
            return f"INSERT 0 {rowcount}"
        if verb in ("UPDATE", "DELETE"):
            return f"{verb} {rowcount}"
        return f"{verb} {rowcount}"

    async def fetchrow(self, sql, *args):
        def _do(conn):
            stmt, bound = _bind(sql, args)
            row = conn.execute(stmt, bound).fetchone()
            return dict(row) if row is not None else None
        return await asyncio.to_thread(self._sync, _do)

    async def fetch(self, sql, *args):
        def _do(conn):
            stmt, bound = _bind(sql, args)
            return [dict(r) for r in conn.execute(stmt, bound).fetchall()]
        return await asyncio.to_thread(self._sync, _do)

    def transaction(self):
        return _NoopTx()


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _SqlitePool:
    def __init__(self, path: str):
        self.conn = _SqliteConn(path)

    def acquire(self):
        return _Acquire(self.conn)


class _SqlitePg:
    """`pg.pool` — asyncpg-совместимый shim; новый экземпляр = «reload»."""

    def __init__(self, path: str):
        self.path = str(path)
        self.pool = _SqlitePool(str(path))


# ── WebApp auth (прецедент step2c2) ─────────────────────────────────────────

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


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")


# ── seed → list → preview (§50) ─────────────────────────────────────────────

class TestStyleSeedListPreview:
    def test_seed_imports_durable_reference_and_placeholders(self, pg):
        profile = _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
        assert profile is not None
        assert profile["profile_id"] == "medved_press"
        assert profile["origin"] == registry.ORIGIN_SEEDED
        assert profile["pipeline_mode"] == "generate_then_edit"

        # references: medved_press.png → реальный durable asset
        refs = profile["references"]
        assert len(refs) == 1
        assert refs[0]["label"] == "Медведь Press"
        ref_asset = _run(registry.get_asset(pg, refs[0]["asset_id"]))
        assert ref_asset is not None
        ref_src = SEED_DIR / "medved_press.png"
        assert Path(ref_asset["disk_path"]).read_bytes() == ref_src.read_bytes()
        assert ref_asset["sha256"] == hashlib.sha256(
            ref_src.read_bytes()).hexdigest()

        # placeholders seeded из реальных extra_images
        before = _run(registry.get_asset(pg, profile["preview_before_asset_id"]))
        after = _run(registry.get_asset(pg, profile["preview_after_asset_id"]))
        assert before is not None and after is not None
        assert Path(before["disk_path"]).read_bytes() == \
            (SEED_DIR / "style_example_01.png").read_bytes()
        assert Path(after["disk_path"]).read_bytes() == \
            (SEED_DIR / "style_example_02.jpg").read_bytes()

    def test_seed_does_not_mutate_extra_images(self, pg):
        before = {name: (SEED_DIR / name).read_bytes()
                  for name in registry.SEED_FILES.values()}
        _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
        for name, data in before.items():
            assert (SEED_DIR / name).read_bytes() == data, name

    def test_style_list_contains_seeded_with_example_preview(self, pg):
        _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
        rows = _run(registry.list_profiles(pg))
        assert [r["profile_id"] for r in rows] == ["medved_press"]
        assert registry.preview_is_stale(rows[0]) is False
        # preview_source = example (реальный тест ещё не запускался)
        assert rows[0]["preview_revision"] is None

    def test_seed_is_idempotent_no_duplicate_assets(self, pg):
        _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
        _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
        assets_rows = _run(pg.pool.conn.fetch(
            "SELECT asset_id FROM cover_style_assets"))
        assert len(assets_rows) == len(registry.SEED_FILES)
        profiles = _run(registry.list_profiles(pg))
        assert len(profiles) == 1


# ── test flow → preview update → persist (§50) ──────────────────────────────

def _patch_provider(monkeypatch, tmp_path):
    """Реальный registry + temp-SQLite; провайдер (base gen + style edit)
    мокается — live-контракт закрывается canary, не этим контуром."""
    base = tmp_path / "gen_base.png"
    base.write_bytes(PNG_BYTES)
    styled = tmp_path / "gen_styled.jpg"
    styled.write_bytes(b"STYLED-REAL-BYTES")
    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose",
        AsyncMock(return_value=(str(base), "ok")))
    monkeypatch.setattr(
        "services.cover_style_jobs.run_style_preview",
        AsyncMock(return_value={"applied": True, "reason": "",
                                "styled_path": str(styled),
                                "preview_issue": "ВЫПУСК 00",
                                "model": "qwen-image-3-pro",
                                "provider": "nanogpt", "duration_ms": 42}))
    decode_calls = {"n": 0}
    real_decode = None
    import web.api.cover_styles as cs
    real_decode = cs._decode_upload

    def _spy(body):
        decode_calls["n"] += 1
        return real_decode(body)

    monkeypatch.setattr(cs, "_decode_upload", _spy)
    return decode_calls


def test_test_style_updates_preview_persists_across_reload(pg, tmp_path,
                                                           monkeypatch):
    seeded = _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
    counter_before = seeded["counter_value"]
    decode_calls = _patch_provider(monkeypatch, tmp_path)
    client = _client(pg)

    resp = client.post("/api/cover/test-style", headers=_hdr(),
                       json={"profile_id": "medved_press"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["base_source"] == "generated"
    assert body["preview_source"] == "test"
    assert body["preview_source_label"] == "Результат теста"
    # upload не задействован (File Explorer не открыт)
    assert decode_calls["n"] == 0, "Test Style не вызывает upload"
    # counter не потрачен (mode=preview)
    reloaded = _run(registry.get_profile_with_refs(pg, "medved_press"))
    assert reloaded["counter_value"] == counter_before == 0
    # previews обновлены реальными generated assets
    assert reloaded["preview_before_asset_id"] == body["preview_before_url"] \
        .rsplit("/", 1)[-1]
    assert reloaded["preview_after_asset_id"] == body["asset_id"]
    assert reloaded["preview_revision"] == reloaded["revision"]

    # ── reload: НОВЫЙ pool/connection на том же SQLite-файле ──
    pg2 = _SqlitePg(pg.path)
    persisted = _run(registry.get_profile_with_refs(pg2, "medved_press"))
    assert persisted["preview_after_asset_id"] == body["asset_id"]
    assert persisted["preview_before_asset_id"] == \
        reloaded["preview_before_asset_id"]
    assert persisted["preview_revision"] == reloaded["revision"]
    assert registry.preview_is_stale(persisted) is False
    # обновлённый preview реально читается с диска (bytes сохранены)
    after_asset = _run(registry.get_asset(pg2, persisted["preview_after_asset_id"]))
    assert after_asset is not None
    assert Path(after_asset["disk_path"]).read_bytes() == b"STYLED-REAL-BYTES"


def test_test_style_requires_no_file(pg, tmp_path, monkeypatch):
    _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
    decode_calls = _patch_provider(monkeypatch, tmp_path)
    resp = _client(pg).post("/api/cover/test-style", headers=_hdr(),
                            json={"profile_id": "medved_press"})
    assert resp.status_code == 200
    assert decode_calls["n"] == 0


# ── failure keeps last success (§50) ────────────────────────────────────────

def test_test_style_failure_keeps_previous_preview(pg, tmp_path, monkeypatch):
    _run(registry.seed_seeded_style(pg, seed_dir=SEED_DIR))
    _patch_provider(monkeypatch, tmp_path)
    # первый успех → preview стал «test»
    first = _client(pg).post("/api/cover/test-style", headers=_hdr(),
                             json={"profile_id": "medved_press"}).json()
    assert first["applied"] is True
    # второй прогон — провал провайдера
    monkeypatch.setattr(
        "services.cover_style_jobs.run_style_preview",
        AsyncMock(return_value={"applied": False, "reason": "style_failed",
                                "fail_reason": "route_unverified",
                                "preview_issue": "ВЫПУСК 00"}))
    second = _client(pg).post("/api/cover/test-style", headers=_hdr(),
                              json={"profile_id": "medved_press"}).json()
    assert second["applied"] is False
    assert second["developer_reason"] == "route_unverified"
    assert "провайдер отклонил" in second["message"].lower()
    # прошлый preview НЕ уничтожен
    persisted = _run(registry.get_profile_with_refs(pg, "medved_press"))
    assert persisted["preview_after_asset_id"] == first["asset_id"]
    assert second["preview_after_url"] == first["preview_after_url"]
