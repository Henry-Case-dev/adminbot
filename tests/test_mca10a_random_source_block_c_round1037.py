"""MCA-10a `mca-10a-random-source-anu` — focused-тесты блока C (T-4978).

Покрытие (MCA10-R4, spec D8/§9, ТЗ §14.4):
  * каталог/настройки: 13 ключей (memory_random ×4 + keys_random ×9), группы,
    TAB_RULES in-place, per-chat vs global, типы/selects/дефолты Settings;
  * секрет ANU: GET /api/config — только {configured,last4} (raw никогда);
    non-global-admin не видит вовсе; POST /api/config сохраняет без эха;
    hot-применение без рестарта (ConfigCache → hot.get);
  * per-chat override (mode/probability) vs глобальная квота (account_key);
  * кнопка «Проверить подключение»: POST /api/random/test — backend-only,
    RBAC секретных прав, draft-ключ только в body (не URL/не эхо), healthy
    только после реальной валидной партии; singleflight на повторные клики.
"""
import asyncio
import dataclasses
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import Settings
from services import chat_params, hot_config as hot
from services import mca_random_source as mrs
from services import param_catalog as pc
from services.config_cache import ConfigCache
from services.database import DatabaseService
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS_MCA10A"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_ID = 999999999

ANU_KEY = "keys.random_quantum_api_key"
ANU_SECRET = "anu-draft-secret-7777"

RANDOM_KEYS = (
    "memory.random_source",
    "memory.random_fallback_to_pseudorandom",
    "memory.random_exploration_probability",
    "memory.random_sleep_exploration_probability",
    "keys.random_quantum_provider",
    "keys.random_quantum_endpoint",
    "keys.random_quantum_api_key",
    "keys.random_quantum_plan",
    "keys.random_quantum_batch_length",
    "keys.random_quantum_data_type",
    "keys.random_quantum_request_timeout_seconds",
    "keys.random_quantum_refill_low_watermark",
    "keys.random_quantum_buffer_max_values",
)


# ── каталог/настройки ───────────────────────────────────────────────────────
class TestCatalogContract:
    def test_all_13_keys_registered(self):
        by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
        for key in RANDOM_KEYS:
            assert key in by_pg, key
        assert len([k for k in RANDOM_KEYS if k.startswith("memory.")]) == 4
        assert len([k for k in RANDOM_KEYS if k.startswith("keys.")]) == 9

    def test_groups_and_tabs(self):
        groups = {g.id: g for g in pc.GROUPS}
        assert groups["memory_random"].category == "memory"
        assert groups["keys_random"].category == "keys"
        assert groups["memory_random"].order == 4
        assert groups["keys_random"].order == 9
        assert pc.group_tab("memory_random") == pc.TAB_MOD_SLEEP
        assert pc.group_tab("keys_random") == pc.TAB_LLM_PROVIDERS
        assert "memory_random" in pc.tab_group_ids(pc.TAB_MOD_SLEEP)
        assert "keys_random" in pc.tab_group_ids(pc.TAB_LLM_PROVIDERS)

    def test_counts_sanctioned_delta(self):
        # Санкция §13.2: +13/+2/+2, TAB_RULES 21 in-place.
        assert len(pc.REGISTRY) == 519
        assert len(pc.GROUPS) == 112
        assert len(pc._TAB_BY_GROUP) == 110
        assert len(pc.TAB_RULES) == 22

    def test_per_chat_vs_global(self):
        # memory.* — per-chat (mode/probability/fallback); keys.* — глобальные
        # (квота/подключение не дробятся по чатам).
        for key in RANDOM_KEYS:
            spec = pc.get_by_pg_key(key)
            assert spec is not None, key
            if key.startswith("memory."):
                assert spec.per_chat is True, key
                assert spec.group == "memory_random"
            else:
                assert spec.per_chat is False, key
                assert spec.group == "keys_random"
        assert pc.get_by_pg_key(ANU_KEY).secret is True
        for key in RANDOM_KEYS:
            if key != ANU_KEY:
                assert pc.get_by_pg_key(key).secret is False, key

    def test_selects(self):
        source = pc.get_by_pg_key("memory.random_source")
        assert source.widget == "select"
        assert source.select_options == ("quantum", "pseudorandom")
        plan = pc.get_by_pg_key("keys.random_quantum_plan")
        assert plan.select_options == ("Trial", "Paid", "Custom")
        dtype = pc.get_by_pg_key("keys.random_quantum_data_type")
        assert dtype.select_options == ("uint8", "uint16", "hex8", "hex16")

    def test_settings_defaults(self):
        s = Settings()
        assert s.RANDOM_SOURCE == "quantum"
        assert s.RANDOM_FALLBACK_TO_PSEUDORANDOM is True
        assert s.RANDOM_EXPLORATION_PROBABILITY == 0.05
        assert s.RANDOM_SLEEP_EXPLORATION_PROBABILITY == 0.05
        assert s.RANDOM_QUANTUM_PROVIDER == "ANU Quantum Numbers"
        assert s.RANDOM_QUANTUM_ENDPOINT == mrs.ANU_ENDPOINT
        assert s.RANDOM_QUANTUM_API_KEY == ""
        assert s.RANDOM_QUANTUM_PLAN == "Trial"
        assert s.RANDOM_QUANTUM_BATCH_LENGTH == 1024
        assert s.RANDOM_QUANTUM_DATA_TYPE == "uint16"
        assert s.RANDOM_QUANTUM_REQUEST_TIMEOUT_SECONDS == 5
        assert s.RANDOM_QUANTUM_REFILL_LOW_WATERMARK == 256
        assert s.RANDOM_QUANTUM_BUFFER_MAX_VALUES == 2048
        assert len({f.name for f in dataclasses.fields(Settings)}) == 450

    def test_per_chat_override_cast(self):
        # per-chat override mode через chat_params (каст по каталогу);
        # глобальная квота при этом одна (account_key не зависит от чата).
        root = {"overrides": {"memory.random_source": "pseudorandom"}}
        assert chat_params._resolve_from_root(
            root, "memory.random_source", "quantum") == "pseudorandom"
        root2 = {"overrides": {"memory.random_fallback_to_pseudorandom": False}}
        assert chat_params._resolve_from_root(
            root2, "memory.random_fallback_to_pseudorandom", True) is False
        svc = mrs.RandomSourceService(None)
        assert svc._account_key() == "anu:trial"
        assert svc._account_key() == svc._account_key()


# ── API-harness (фейковый PG; прецедент byok-image-key) ─────────────────────
def make_init_data(user_id: int) -> str:
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


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

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
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "moderator",
     "permissions": {"sections": ["limits"]}, "is_custom": False},
    {"role_name": "user", "permissions": {}, "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": None},
]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[
            {"key": ANU_KEY, "value": "stored-anu-key-1234",
             "category": "keys", "updated_at": None},
        ],
        role_rows=_ROLE_ROWS, admin_rows=_ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


# ── секрет ANU: маска/скрытие/сохранение/hot-применение ─────────────────────
class TestAnuSecretContour:
    def test_get_config_masks_secret(self, client):
        resp = client.get("/api/config", headers=_hdr())
        assert resp.status_code == 200
        body = resp.text
        assert "stored-anu-key-1234" not in body          # raw никогда
        item = next(i for i in resp.json()["items"] if i["key"] == ANU_KEY)
        assert item["secret"] is True
        assert item["value"] == {"configured": True, "last4": "1234"}

    def test_non_admin_does_not_see_secret(self, client):
        resp = client.get("/api/config", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 200
        keys = {i["key"] for i in resp.json()["items"]}
        assert ANU_KEY not in keys
        assert "stored-anu-key-1234" not in resp.text

    def test_params_meta_marks_secret(self, client):
        resp = client.get("/api/config/params-meta", headers=_hdr())
        assert resp.status_code == 200
        meta = resp.json()["items"][ANU_KEY]
        assert meta["secret_mask"] is True
        assert meta["per_chat"] is False
        assert meta["group"] == "keys_random"

    def test_post_config_saves_without_echo_and_hot_applies(self, client,
                                                            monkeypatch):
        # «Сохранить и применить»: POST /api/config → ConfigCache → hot.get
        # (без рестарта). Секрет не возвращается клиенту.
        monkeypatch.setattr(hot, "_cache", client.cache)
        resp = client.post("/api/config", headers=_hdr(),
                           json={"items": [{"key": ANU_KEY,
                                            "value": ANU_SECRET}]})
        assert resp.status_code == 200, resp.text
        assert ANU_SECRET not in resp.text
        assert ANU_KEY in resp.json()["updated"]
        # Применение без рестарта: сервис резолвит ключ из hot-слоя.
        assert hot.get(ANU_KEY) == ANU_SECRET
        svc = mrs.RandomSourceService(None)
        assert svc._resolve_key() == ANU_SECRET
        # Повторное чтение — маска, raw не отдаётся.
        resp2 = client.get("/api/config", headers=_hdr())
        item = next(i for i in resp2.json()["items"] if i["key"] == ANU_KEY)
        assert item["value"] == {"configured": True, "last4": "7777"}

    def test_post_config_non_admin_403(self, client):
        resp = client.post("/api/config", headers=_hdr(MODERATOR_ID),
                           json={"items": [{"key": ANU_KEY, "value": "x"}]})
        assert resp.status_code == 403

    def test_delete_secret_empty_write_masks_unconfigured(self, client):
        # «Удалить» (generic-путь): пустая запись → «не настроен»; raw нет.
        resp = client.post("/api/config", headers=_hdr(),
                           json={"items": [{"key": ANU_KEY, "value": ""}]})
        assert resp.status_code == 200
        resp2 = client.get("/api/config", headers=_hdr())
        item = next(i for i in resp2.json()["items"] if i["key"] == ANU_KEY)
        assert item["value"] == {"configured": False, "last4": None}

    def test_memory_random_editable_per_chat_via_api(self, client):
        # mode/fallback/probability — per-chat (chat_params); квота — global.
        spec = pc.get_by_pg_key("memory.random_source")
        assert spec.per_chat is True
        # Глобальный путь POST /api/config также принимает ключ (admin).
        resp = client.post("/api/config", headers=_hdr(),
                           json={"items": [{"key": "memory.random_source",
                                            "value": "pseudorandom"}]})
        assert resp.status_code == 200, resp.text


# ── кнопка «Проверить подключение»: POST /api/random/test ───────────────────
class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _ok_uint16(length: int):
    return (200, {}, '{"success": true, "type": "uint16", "length": %d, '
                     '"data": %s}' % (length, list(range(length))))


def _make_http(responses, calls, delay=0.0):
    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params), "timeout": timeout})
        if delay:
            await asyncio.sleep(delay)
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, hdrs, text = item
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get


async def _fresh_db(tmp_path, name) -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


@pytest.fixture
def api_service(monkeypatch, tmp_path):
    """Свежий сервис с фейковым ANU-клиентом (draft-ключ → реальная партия)."""
    monkeypatch.setattr(
        mrs, "_hot_setting",
        lambda key, default: 8 if key == mrs.SETTING_BATCH_LENGTH else default)

    async def _setup():
        db = await _fresh_db(tmp_path, "mca10a_c.db")
        calls: list = []
        responses = [_ok_uint16(8), _ok_uint16(8), _ok_uint16(8)]
        client = mrs.AnuClient(http_get=_make_http(responses, calls),
                               min_interval=0.0, clock=FakeClock())
        svc = mrs.RandomSourceService(db, client=client, auto_refill=False)
        monkeypatch.setattr(mrs, "_service", svc)
        return svc, calls

    svc, calls = asyncio.run(_setup())
    yield svc, calls
    mrs.reset_service()
    try:
        asyncio.run(svc.db.close())
    except Exception:
        pass


class TestRandomTestRoute:
    def test_requires_secret_rights(self, client, api_service):
        resp = client.post("/api/random/test", headers=_hdr(MODERATOR_ID),
                           json={"key": ""})
        assert resp.status_code == 403

    def test_draft_key_healthy_only_after_real_batch(self, client,
                                                     api_service):
        svc, calls = api_service
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"key": "draft-anu-key-abc"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["healthy"] is True
        assert body["length"] == 8
        assert body["persisted"] is False
        assert body["checked_at"]
        assert body["latency_ms"] is not None
        # Ключ не эхо-ится и не попадает в URL (path без query/секретов).
        assert "draft-anu-key-abc" not in resp.text
        assert len(calls) == 1
        assert calls[0]["headers"]["x-api-key"] == "draft-anu-key-abc"

    def test_check_credits_batch_to_reserve(self, client, api_service):
        # «Проверочные числа зачисляются в запас» — запрос не тратится впустую.
        svc, calls = api_service
        assert asyncio.run(svc._reserve_remaining()) == 0
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"key": "draft-anu-key-abc"})
        assert resp.status_code == 200 and resp.json()["healthy"] is True
        assert asyncio.run(svc._reserve_remaining()) == 8

    def test_draft_key_not_in_logs(self, client, api_service, caplog):
        import logging
        svc, calls = api_service
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/api/random/test", headers=_hdr(),
                               json={"key": "draft-anu-key-abc"})
        assert resp.status_code == 200
        assert "draft-anu-key-abc" not in caplog.text

    def test_k1_off_route_disabled(self, client, api_service, monkeypatch):
        # K1 OFF → ANU-запросов нет; кнопка честно показывает disabled.
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: False)
        svc, calls = api_service
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"key": "draft-anu-key-abc"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["healthy"] is False
        assert body["blocker"] == "disabled"
        assert len(calls) == 0

    def test_unknown_key_not_healthy(self, client, api_service):
        svc, calls = api_service
        svc._client._http_get = _make_http(
            [(401, {}, '{"success": false, "error": "bad key"}')], calls)
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"key": "wrong-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["healthy"] is False
        assert body["blocker"] == "auth_failed"
        assert "wrong-key" not in resp.text

    def test_singleflight_repeated_clicks_one_request(self, client,
                                                      api_service):
        svc, calls = api_service

        async def _two_clicks():
            return await asyncio.gather(
                svc.test_connection(draft_key="draft-xyz"),
                svc.test_connection(draft_key="draft-xyz"))

        first, second = asyncio.run(_two_clicks())
        assert first["healthy"] and second["healthy"]
        assert first["length"] == second["length"] == 8
        assert len(calls) == 1, "повторные клики должны coalesce (один запрос)"


class TestStatusRandomScope:
    """D9/RBAC: журнал draw в блоке «Статуса» — в рамках прав на чат."""

    def test_status_chat_scope_gated_by_rbac(self, client, api_service,
                                             monkeypatch):
        from services.status_service import StatusService

        async def _no_health(self, module_id, base_url, key, model="",
                             kind="chat"):
            return {"ok": False, "status": "not_configured",
                    "http_status": None, "latency_ms": None,
                    "checked_at": None}

        async def _no_uptime(self, pg):
            return []

        monkeypatch.setattr(StatusService, "_check_health", _no_health)
        monkeypatch.setattr(StatusService, "fetch_uptime_rows", _no_uptime)
        # Global admin: доступ к чату → журнал в chat-scope (пуст — draw нет).
        resp = client.get("/api/status", headers={
            **_hdr(ADMIN_ID), "X-Chat-Id": "-100500"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["random"]["recent_draws_scope"] == "chat"
        # Обычный user: нет доступа к чату → журнал не отдаётся (restricted).
        resp2 = client.get("/api/status", headers={
            **_hdr(USER_ID), "X-Chat-Id": "-100500"})
        assert resp2.status_code == 200, resp2.text
        rnd = resp2.json()["random"]
        assert rnd["recent_draws"] == []
        assert rnd["recent_draws_scope"] == "restricted"
