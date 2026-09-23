"""S9 round1026 (ADR-1026-8 D1/D4) — интеграционные/RBAC-тесты API тест-контура.

По образцу `tests/test_webapp_analytics_api.py`: реальный `TestClient(create_app)`.
Проверяем: флаг OFF → 404 (до auth); 401 (без initData); 403 (не глобальный
админ); 422 (невалидный chat_id); 202 + polling (dry-run без публикации);
409 (параллельный прогон); 429 (лимит одновременных / rate-limit); in-memory
store (TTL 15 мин, ≤20, без DDL); обложка по умолчанию не генерируется.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from services import web_runtime
from services.config_cache import ConfigCache
from web.api import deps as deps_mod
from web.api import summary_test as api_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_SUMMARY_TEST"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_NO_ROLE = 999999999
CHAT_ID = -1001234567890

L1_JSON = json.dumps({
    "schema_version": 1,
    "threads": [
        {"thread_id": "t1", "topic": "Тема", "message_ids": [101],
         "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}]},
    ],
    "unassigned_message_ids": [102],
})
L2_JSON = json.dumps({
    "schema_version": 1,
    "title": "Тестовая статья",
    "paragraphs": [{"text": "Первый абзац статьи.", "emphasis": "Первый"}],
})


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


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
    def __init__(self):
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
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


class _FakeGenerator:
    """Мини-генератор: read-only окно + мок LLM (ровно 2 вызова)."""

    def __init__(self):
        self.llm = MagicMock()
        self.llm.generate = AsyncMock(side_effect=[L1_JSON, L2_JSON])

    async def build_test_rows(self, chat_id, *, since_ts, limit=None,
                              correlation_id=None, trigger_message_id=None):
        rows = [
            {"id": 1, "tg_message_id": 101, "text": "Первое",
             "timestamp": 1000, "user_id": 1, "author_name": "A",
             "reply_to_id": None, "media_type": None},
            {"id": 2, "tg_message_id": 102, "text": "Второе",
             "timestamp": 1001, "user_id": 2, "author_name": "B",
             "reply_to_id": None, "media_type": None},
        ]
        return {"source": rows, "filtered": rows, "dropped": [], "restored": [],
                "filter_metrics": {"status": "ok", "source_count": 2,
                                   "saved_count": 2, "restored_count": 0,
                                   "drop_percent": 0.0, "duration_ms": 1.0},
                "source_count": 2, "filtered_count": 2, "restored_count": 0,
                "limit": 500}


def _flag_env_off(monkeypatch):
    """Явный env ``SUMMARY_TEST_UI_ENABLED=false`` → OFF-ветка (D8).

    ClassVar frozen-настроек не патчится instance-attr, поэтому пересобираем
    модульный singleton с env-переменной и подменяем его в роутере; teardown
    monkeypatch возвращает исходный объект, autouse-фикстура класса — продовый
    singleton (env снят → default ON).
    """
    import importlib
    import config.settings as settings_mod
    monkeypatch.setenv("SUMMARY_TEST_UI_ENABLED", "false")
    reloaded = importlib.reload(settings_mod)
    monkeypatch.setattr(api_mod, "settings", reloaded.settings)
    assert api_mod._flag_enabled() is False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    # Флаг не патчим: default ON (D8) — вкладка/API доступны из коробки.
    api_mod.reset_test_store()
    web_runtime.reset_web_runtime()
    conn = _FakeConn()
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        tc.conn = conn
        yield tc
    api_mod.reset_test_store()
    web_runtime.reset_web_runtime()


def _poll(client, test_id, tries=40):
    for _ in range(tries):
        resp = client.get(f"/api/summary/test/{test_id}", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        if body.get("status") != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("прогон не завершился")


class TestFlagAndRbac:
    @pytest.fixture(autouse=True)
    def _restore_settings_singleton(self, monkeypatch):
        # OFF-тест пересобирает config.settings с env=false — вернуть продовый
        # singleton (env снят → default ON) до monkeypatch-teardown.
        yield
        import importlib
        import config.settings as settings_mod
        monkeypatch.delenv("SUMMARY_TEST_UI_ENABLED", raising=False)
        importlib.reload(settings_mod)

    def test_flag_default_on(self, client):
        # default (env не задан) → вкладка/API доступны без ручного включения (D8).
        assert settings.SUMMARY_TEST_UI_ENABLED is True
        assert api_mod._flag_enabled() is True
        assert client.get("/api/summary/test/availability",
                          headers=_hdr()).status_code == 200

    def test_flag_off_404_before_auth(self, client, monkeypatch):
        _flag_env_off(monkeypatch)
        # даже без initData — 404 (флаг-гард раньше auth).
        assert client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID}).status_code == 404
        assert client.get("/api/summary/test/availability").status_code == 404

    def test_401_without_init_data(self, client):
        assert client.get("/api/summary/test/availability").status_code == 401
        assert client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID}).status_code == 401

    def test_403_non_admin(self, client):
        assert client.get("/api/summary/test/availability",
                          headers=_hdr(MODERATOR_ID)).status_code == 403
        assert client.get("/api/summary/test/availability",
                          headers=_hdr(USER_NO_ROLE)).status_code == 403
        assert client.post("/api/summary/test/run", json={"chat_id": CHAT_ID},
                           headers=_hdr(USER_NO_ROLE)).status_code == 403

    def test_admin_availability_200(self, client):
        resp = client.get("/api/summary/test/availability", headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_422_invalid_chat_id(self, client):
        assert client.post("/api/summary/test/run", json={"chat_id": 0},
                           headers=_hdr()).status_code == 422
        assert client.post("/api/summary/test/run", json={"chat_id": "abc"},
                           headers=_hdr()).status_code == 422


class TestRunFlow:
    def test_run_202_poll_and_dry_run(self, client):
        web_runtime.set_summary_generator(_FakeGenerator())
        resp = client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID, "window_hours": 24},
                           headers=_hdr())
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "running"
        assert body["test_id"]
        result = _poll(client, body["test_id"])
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert result["publication"] == {"status": "not_published",
                                         "reason": "dry_run"}
        assert result["metrics"]["publication_status"] == "не публиковалось (dry-run)"
        assert "<h1>" in result["artifacts"]["rich_preview"]

    def test_run_no_generator_still_polls_error(self, client):
        # генератор не установлен → TEST_NO_GENERATOR, публикации нет.
        resp = client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID}, headers=_hdr())
        assert resp.status_code == 202
        result = _poll(client, resp.json()["test_id"])
        assert result["status"] == "error"
        assert result["diagnostics"][0]["code"] == "TEST_NO_GENERATOR"
        # B-R1026S9-2: error-ответ контракт-валиден (UI не падает на undefined).
        assert result["metrics"]["tokens"]["l1"]["input"] == "Нет данных"
        assert result["metrics"]["drop_percent"] is None
        assert result["artifacts"]["source"] == []
        assert "has_more" in result["display"]

    def test_execute_exception_payload_contract(self, client, monkeypatch):
        # B-R1026S9-2: непредвиденное исключение оркестрации → валидный
        # error-результат с диагностикой (не `entry.result=None`).
        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(api_mod, "run_summary_test", _boom)
        web_runtime.set_summary_generator(_FakeGenerator())
        resp = client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID}, headers=_hdr())
        assert resp.status_code == 202
        result = _poll(client, resp.json()["test_id"])
        assert result["status"] == "error"
        assert result["diagnostics"][0]["code"] == "TEST_RUN_FAILED"
        assert result["metrics"]["tokens"]["l2"]["output"] == "Нет данных"
        assert result["artifacts"]["clusters"] == []
        assert "display" in result

    def test_latest_returns_last(self, client):
        web_runtime.set_summary_generator(_FakeGenerator())
        resp = client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID}, headers=_hdr())
        _poll(client, resp.json()["test_id"])
        latest = client.get(f"/api/summary/test/latest?chat_id={CHAT_ID}",
                            headers=_hdr())
        assert latest.status_code == 200
        assert latest.json()["status"] == "ok"

    def test_404_unknown_test_id(self, client):
        assert client.get("/api/summary/test/nope",
                          headers=_hdr()).status_code == 404

    def test_409_parallel_same_chat(self, client):
        # искусственно «running» запись для (user, chat).
        api_mod._STORE.put_running("running-1", ADMIN_ID, CHAT_ID, 6)
        resp = client.post("/api/summary/test/run", json={"chat_id": CHAT_ID},
                           headers=_hdr())
        assert resp.status_code == 409

    def test_429_too_many_concurrent(self, client):
        api_mod._STORE.put_running("r1", ADMIN_ID, CHAT_ID, 6)
        api_mod._STORE.put_running("r2", ADMIN_ID, CHAT_ID + 1, 6)
        resp = client.post("/api/summary/test/run",
                           json={"chat_id": CHAT_ID + 2}, headers=_hdr())
        assert resp.status_code == 429

    def test_429_rate_limit(self, client):
        entry = api_mod._STORE.put_running("r-done", ADMIN_ID, CHAT_ID, 6)
        entry.status = "ok"
        entry.finished = time.time()
        resp = client.post("/api/summary/test/run", json={"chat_id": CHAT_ID},
                           headers=_hdr())
        assert resp.status_code == 429


class TestCover:
    def test_cover_default_not_generated(self, client):
        web_runtime.set_summary_generator(_FakeGenerator())
        resp = client.post("/api/summary/test/run", json={"chat_id": CHAT_ID},
                           headers=_hdr())
        test_id = resp.json()["test_id"]
        _poll(client, test_id)
        out = client.post(f"/api/summary/test/{test_id}/cover",
                          json={"confirm": False}, headers=_hdr())
        assert out.status_code == 200
        assert out.json()["cover_status"] == "not_generated"

    def test_cover_confirm_no_prompt_failed(self, client):
        # Прогон без cover_prompt → подтверждение даёт COVER_GENERATION_FAILED,
        # статья-предпросмотр сохраняется (0 вызовов generate_image).
        from services import image_generation
        gen_image = MagicMock()
        orig = image_generation.generate_image_verbose
        image_generation.generate_image_verbose = gen_image
        try:
            web_runtime.set_summary_generator(_FakeGenerator())
            resp = client.post("/api/summary/test/run",
                               json={"chat_id": CHAT_ID}, headers=_hdr())
            test_id = resp.json()["test_id"]
            _poll(client, test_id)
            out = client.post(f"/api/summary/test/{test_id}/cover",
                              json={"confirm": True}, headers=_hdr())
            assert out.status_code == 200
            assert out.json()["cover_status"] == "COVER_GENERATION_FAILED"
            gen_image.assert_not_called()
        finally:
            image_generation.generate_image_verbose = orig


class TestStore:
    def test_store_limit_20(self):
        # Лимит ≤20 применяется к завершённым записям (running защищён, L-R1026S9-3).
        store = api_mod._RunStore()
        for i in range(25):
            e = store.put_running(f"t{i}", ADMIN_ID, CHAT_ID, 6)
            e.status = "ok"
            e.finished = time.time()
        assert len(store._items) == 20

    def test_store_ttl_purge(self):
        store = api_mod._RunStore()
        entry = store.put_running("old", ADMIN_ID, CHAT_ID, 6)
        entry.status = "ok"
        entry.finished = time.time() - store.TTL_SECONDS - 5
        assert store.get("old") is None

    def test_store_latest_for_user(self):
        store = api_mod._RunStore()
        store.put_running("a", ADMIN_ID, CHAT_ID, 6)
        e2 = store.put_running("b", ADMIN_ID, CHAT_ID, 6)
        assert store.latest_for(ADMIN_ID, CHAT_ID).test_id == e2.test_id

    def test_store_ttl_keeps_running(self):
        # L-R1026S9-3: running-запись НЕ вычищается по TTL (polling жив).
        store = api_mod._RunStore()
        entry = store.put_running("live", ADMIN_ID, CHAT_ID, 6)
        entry.created = time.time() - store.TTL_SECONDS - 10
        assert store.get("live") is not None
        assert store.active_count() == 1

    def test_store_eviction_keeps_running(self):
        # L-R1026S9-3: эвикция при переполнении не выбрасывает running.
        store = api_mod._RunStore()
        live = store.put_running("live", ADMIN_ID, CHAT_ID, 6)
        for i in range(store.MAX_ENTRIES - 1):
            e = store.put_running(f"done{i}", ADMIN_ID, CHAT_ID, 6)
            e.status = "ok"
            e.finished = time.time()
        # Добавление сверх лимита вытесняет только завершённые.
        e = store.put_running("done-extra", ADMIN_ID, CHAT_ID, 6)
        e.status = "ok"
        e.finished = time.time()
        assert store.get("live") is not None
        assert live.status == "running"
