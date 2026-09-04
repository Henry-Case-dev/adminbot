"""Раунд 3 (T-687, AC-B1/AC-B2) — services/media_share + эндпоинт GET /media.

Покрытие: publish (тикет/файл в каталоге/TTL-URL), no-op без секрета,
ext-whitelist, размерный потолок, sign/verify, delete_file, cleanup_expired
(ленивая чистка по mtime), маска file_id; эндпоинт через TestClient:
200 video/* inline / 403 (битая подпись, просрочка) / 404 (нет файла,
мусорный file_id, traversal `../`/`%2e%2e`).
"""
import asyncio
import dataclasses
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import settings as real_settings
from services import hot_config as hot
from services import media_share
from services.config_cache import ConfigCache
from services.media_share import (
    ShareTicket,
    build_media_url,
    cleanup_expired,
    delete_file,
    enabled,
    publish_media_file,
    sign,
    verify,
)
from web.app import create_app

CHAT_ID = -1001234567890


def _stub(tmp_path, **overrides):
    """Настройки медиа-шары (секрет задан, каталог — tmp)."""
    base = {
        "MEDIA_SHARE_SECRET": "test_media_share_secret",
        "MEDIA_SHARE_DIR": str(tmp_path / "share"),
        "MEDIA_SHARE_TTL_SECONDS": 900,
        "MEDIA_PUBLIC_BASE_URL": "https://media.example.test",
        "MEDIA_SHARE_MAX_MB": 200,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


@pytest.fixture
def share_env(tmp_path, monkeypatch):
    """media_share без hot-кэша: settings-модуль → стаб (каталог — tmp)."""
    stub = _stub(tmp_path)
    monkeypatch.setattr(media_share, "settings", stub)
    old_cache = hot.get_config_cache()
    hot.set_config_cache(None)
    yield stub
    hot.set_config_cache(old_cache)


def _write_src(tmp_path, name="video.mp4", size=1024, data=b"videodata"):
    src = tmp_path / name
    src.write_bytes(data * (max(1, size // len(data))))
    return src


# ── 1. publish / тикет / no-op-пути (AC-B1) ──────────────────────────

class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_creates_copy_and_ticket(self, tmp_path, share_env):
        src = _write_src(tmp_path)
        ticket = await publish_media_file(str(src), 900)
        assert isinstance(ticket, ShareTicket)
        assert media_share._SHARE_FILE_RE.match(ticket.file_id)
        dst = Path(share_env.MEDIA_SHARE_DIR) / ticket.file_id
        assert dst.exists()
        assert dst.read_bytes() == src.read_bytes()
        assert ticket.rel_url == f"/media/{ticket.file_id}?e={ticket.expires}&s={ticket.sig}"
        assert ticket.abs_url.startswith("https://media.example.test/media/")
        assert ticket.expires > int(time.time())
        assert verify(ticket.file_id, ticket.expires, ticket.sig)

    @pytest.mark.asyncio
    async def test_publish_disabled_without_secret(self, tmp_path, share_env,
                                                   monkeypatch):
        monkeypatch.setattr(media_share, "settings", _stub(
            tmp_path, MEDIA_SHARE_SECRET=""))
        assert not enabled()
        assert await publish_media_file(str(_write_src(tmp_path)), 900) is None
        assert not (Path(share_env.MEDIA_SHARE_DIR)).exists()

    @pytest.mark.asyncio
    async def test_publish_ext_whitelist(self, tmp_path, share_env):
        for bad in ("gif", "pdf", "bin", "m4a"):
            src = _write_src(tmp_path, f"x.{bad}")
            assert await publish_media_file(str(src), 900) is None, bad
        for good in ("mp4", "webm", "mov", "mkv", "avi"):
            src = _write_src(tmp_path, f"ok.{good}")
            assert await publish_media_file(str(src), 900) is not None, good

    @pytest.mark.asyncio
    async def test_publish_size_cap(self, tmp_path, share_env, monkeypatch):
        monkeypatch.setattr(media_share, "settings",
                            _stub(tmp_path, MEDIA_SHARE_MAX_MB=1))
        src = _write_src(tmp_path, "big.mp4", size=2 * 1024 * 1024)
        assert await publish_media_file(str(src), 900) is None
        small = _write_src(tmp_path, "small.mp4", size=10)
        assert await publish_media_file(str(small), 900) is not None

    @pytest.mark.asyncio
    async def test_publish_missing_source_none(self, share_env, tmp_path):
        assert await publish_media_file(str(tmp_path / "нет.mp4"), 900) is None


# ── 2. sign/verify / delete / cleanup (AC-B2) ─────────────────────────

class TestSignVerifyCleanup:
    def test_sign_verify_roundtrip(self, share_env):
        sig = sign("a" * 32 + ".mp4", 12345)
        assert len(sig) == 64
        assert verify("a" * 32 + ".mp4", 12345, sig)
        assert not verify("b" * 32 + ".mp4", 12345, sig)   # другой file_id
        assert not verify("a" * 32 + ".mp4", 12346, sig)   # другой expires
        assert not verify("a" * 32 + ".mp4", 12345, "0" * 64)
        assert not verify("a" * 32 + ".mp4", 12345, "")    # пустая подпись

    def test_verify_non_ascii_sig_false_not_raise(self, share_env):
        """fix-round 04.09 (M1): не-ASCII s= ломает hmac.compare_digest
        (TypeError → HTTP 500 на публичном /media); гейт → False (403)."""
        assert not verify("a" * 32 + ".mp4", 12345, "ё" * 64)
        assert not verify("a" * 32 + ".mp4", 12345, "подпись" + "0" * 57)

    def test_build_media_url_has_query_shape(self, share_env):
        file_id = "c" * 32 + ".mp4"
        url = build_media_url(file_id, 111)
        assert url == f"/media/{file_id}?e=111&s={sign(file_id, 111)}"

    @pytest.mark.asyncio
    async def test_delete_file_removes_copy(self, tmp_path, share_env):
        ticket = await publish_media_file(str(_write_src(tmp_path)), 900)
        path = Path(share_env.MEDIA_SHARE_DIR) / ticket.file_id
        assert path.exists()
        await delete_file(ticket.file_id)
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_delete_rejects_junk_ids(self, share_env, tmp_path):
        await delete_file("../evil.mp4")        # не падает, ничего не удаляет
        await delete_file("nothex.mp4")

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_old_files(self, tmp_path, share_env):
        import os as _os
        t1 = await publish_media_file(str(_write_src(tmp_path, "a.mp4")), 900)
        t2 = await publish_media_file(str(_write_src(tmp_path, "b.mp4")), 900)
        share = Path(share_env.MEDIA_SHARE_DIR)
        # состарим ТОЛЬКО t1 на TTL+5с (база — реальное «сейчас»)
        old_ts = int(time.time()) - 905
        _os.utime(share / t1.file_id, (old_ts, old_ts))
        removed = cleanup_expired()
        assert removed == 1
        assert not (share / t1.file_id).exists()
        assert (share / t2.file_id).exists()

    def test_cleanup_without_secret_noop(self, tmp_path, share_env, monkeypatch):
        monkeypatch.setattr(media_share, "settings", _stub(
            tmp_path, MEDIA_SHARE_SECRET=""))
        assert cleanup_expired() == 0

    def test_share_file_mask(self):
        assert media_share._SHARE_FILE_RE.match("a" * 32 + ".mp4")
        assert media_share._SHARE_FILE_RE.match("f" * 32 + ".webm")
        assert not media_share._SHARE_FILE_RE.match("a" * 31 + ".mp4")
        assert not media_share._SHARE_FILE_RE.match("a" * 32 + ".gif")
        assert not media_share._SHARE_FILE_RE.match("../" + "a" * 32 + ".mp4")
        assert not media_share._SHARE_FILE_RE.match("A" * 32 + ".mp4")


# ── 3. Эндпоинт GET /media/{file_id} (AC-B2) ─────────────────────────

class _FakeConn:
    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        return []


class _FakePool:
    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self):
        self._conn = _FakeConn()
        self._pool = _FakePool()
        self.closed = False

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        self.closed = True


@pytest.fixture
def media_client(tmp_path, monkeypatch):
    """TestClient c create_app: media_share включён (стаб-секрет), каталог tmp."""
    stub = _stub(tmp_path)
    monkeypatch.setattr(media_share, "settings", stub)
    old_cache = hot.get_config_cache()
    hot.set_config_cache(None)

    class _InitCache:
        def __init__(self):
            self.is_initialized = False
            self.pg_available = False

        async def init(self):
            self.is_initialized = True

    cache = _InitCache()
    app = create_app(cache)
    with TestClient(app) as client:
        yield client, stub
    hot.set_config_cache(old_cache)


@pytest.fixture
def published(tmp_path, media_client):
    """Опубликованный файл: (client, stub, ticket)."""
    client, stub = media_client
    src = _write_src(tmp_path, "clip.mp4", size=2048)
    ticket = asyncio.run(publish_media_file(str(src), 900))
    return client, stub, ticket


class TestMediaEndpoint:
    def test_valid_url_serves_file_inline(self, published):
        client, stub, ticket = published
        resp = client.get(ticket.rel_url)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"
        assert resp.headers["content-disposition"].startswith('inline; filename="')
        assert ticket.file_id in resp.headers["content-disposition"]

    def test_bad_signature_403(self, published):
        client, _, ticket = published
        resp = client.get(
            f"/media/{ticket.file_id}?e={ticket.expires}&s={'0' * 64}")
        assert resp.status_code == 403

    def test_non_ascii_signature_403_not_500(self, published):
        """fix-round 04.09 (M1): запрос с не-ASCII подписью (публичный
        эндпоинт) → 403 (битая подпись), НЕ 500 (TypeError compare_digest)."""
        client, _, ticket = published
        resp = client.get(
            f"/media/{ticket.file_id}?e={ticket.expires}&s={'ё' * 64}")
        assert resp.status_code == 403

    def test_expired_403(self, published):
        client, _, ticket = published
        past = int(time.time()) - 10
        old_sig = sign(ticket.file_id, past)
        resp = client.get(f"/media/{ticket.file_id}?e={past}&s={old_sig}")
        assert resp.status_code == 403

    def test_missing_file_404(self, media_client):
        client, stub = media_client
        file_id = "f" * 32 + ".mp4"
        exp = int(time.time()) + 900
        resp = client.get(f"/media/{file_id}?e={exp}&s={sign(file_id, exp)}")
        assert resp.status_code == 404

    def test_junk_file_id_masked_404(self, media_client):
        client, _ = media_client
        assert client.get("/media/../etc/passwd").status_code == 404
        assert client.get("/media/%2e%2e/x.mp4").status_code == 404
        assert client.get("/media/not-a-valid-id.mp4").status_code == 404
        assert client.get("/media/" + "f" * 32 + ".gif").status_code == 404

    def test_bad_expiry_param_403(self, published):
        client, _, ticket = published
        assert client.get(f"/media/{ticket.file_id}?e=abc&s=x").status_code == 403
        assert client.get(f"/media/{ticket.file_id}?e=&s=").status_code == 403

    def test_delete_then_404(self, published):
        client, _, ticket = published
        asyncio.run(delete_file(ticket.file_id))
        resp = client.get(ticket.rel_url)
        assert resp.status_code == 404
