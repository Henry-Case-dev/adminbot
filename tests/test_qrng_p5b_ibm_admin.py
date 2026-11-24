"""QRNG P5B — защищённые поля IBM и админ-проверки (QAN-REC-IBM-01/02).

Проверяется фактический HTTP-контракт без сети/реального IBM:
  * POST /api/random/test provider=ibm_quantum — read-only, RBAC global admin,
    черновой key/CRN только в body, ответ не эхо-ит секреты;
  * POST /api/random/ibm/smoke — отдельное действие, требует confirm;
  * POST /api/config для keys.random_ibm_* — только global admin, форма
    key/CRN валидируется, GET /api/config отдаёт маску (raw никогда),
    instance/region остаются видимыми (это не секреты);
  * ключ/CRN не попадают в ответ и логи.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import mca_random_source as mrs
from services.config_cache import ConfigCache
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS_P5B"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079

IBM_KEY = "keys.random_ibm_api_key"
IBM_CRN = "keys.random_ibm_crn"
IBM_INSTANCE = "keys.random_ibm_instance"
IBM_REGION = "keys.random_ibm_region"
GOOD_KEY = "ibm-api-key-0123456789abcdef0123456789"
GOOD_CRN = "crn:v1:bluemix:public:quantum-compute:us-east:a/x:y::"

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


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(role_rows=_ROLE_ROWS, admin_rows=_ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


class _FakeIbmClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or {}
        self.error = error

    async def check_access(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return dict(self.result)

    def status(self):
        return {"fails": 0, "circuit_open_until": 0.0, "last_error": None,
                "last_success_at": None, "last_failure_at": None}


@pytest.fixture
def pinned_service(monkeypatch):
    svc = mrs.RandomSourceService(None, auto_refill=False)
    monkeypatch.setattr(mrs, "_service", svc)
    return svc


class TestRandomTestIbmRoute:
    def test_requires_global_admin(self, client, pinned_service):
        resp = client.post("/api/random/test", headers=_hdr(MODERATOR_ID),
                           json={"provider": "ibm_quantum", "key": GOOD_KEY})
        assert resp.status_code == 403

    def test_unknown_provider_422(self, client, pinned_service):
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"provider": "not-a-provider", "key": GOOD_KEY})
        assert resp.status_code == 422

    def test_unconfigured_is_honest_and_no_secret_echo(self, client,
                                                        pinned_service):
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"provider": "ibm_quantum", "key": "",
                                 "crn": ""})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["healthy"] is False
        assert body["blocker"] == "provider_unconfigured"
        assert body["stage"] == "key"
        assert body["deposited"] is False

    def test_draft_key_crn_checked_read_only_and_not_echoed(
            self, client, pinned_service):
        fake = _FakeIbmClient(result={
            "provider": "ibm_quantum", "healthy": True, "blocker": None,
            "stage": None, "reason": "", "key_present": True,
            "crn_present": True, "instance": "open-instance",
            "region": "us-east", "channel": "ibm_quantum_platform",
            "plan": "Open", "usage": {"usage_remaining_ru": 590},
            "backends": [{"name": "ibm_hw", "num_qubits": 127,
                          "pending_jobs": 2, "operational": True,
                          "simulator": False}],
            "selected_backend": "ibm_hw", "queue": {"pending_jobs": 2},
            "is_simulator": False, "checked_at": 1700000000,
        })
        pinned_service.set_ibm_client(fake)
        resp = client.post("/api/random/test", headers=_hdr(),
                           json={"provider": "ibm_quantum",
                                 "key": GOOD_KEY, "crn": GOOD_CRN})
        assert resp.status_code == 200, resp.text
        assert fake.calls and fake.calls[0]["api_key"] == GOOD_KEY
        assert fake.calls[0]["crn"] == GOOD_CRN
        body = resp.json()
        assert body["healthy"] is True
        assert body["plan"] == "Open"
        assert body["selected_backend"] == "ibm_hw"
        assert body["persisted"] is False
        assert GOOD_KEY not in resp.text
        assert GOOD_CRN not in resp.text
        assert "usage_remaining_ru" in body["usage"]


class TestRandomIbmSmokeRoute:
    def test_requires_confirm(self, client, pinned_service, monkeypatch):
        called = []

        async def _smoke(**kwargs):
            called.append(kwargs)
            return {"healthy": True}

        monkeypatch.setattr(pinned_service, "ibm_hardware_smoke", _smoke)
        resp = client.post("/api/random/ibm/smoke", headers=_hdr(),
                           json={"key": GOOD_KEY, "crn": "", "shots": 256,
                                 "confirm": False})
        assert resp.status_code == 422
        assert resp.json()["detail"].startswith("confirmation_required")
        assert called == []

    def test_confirmed_smoke_calls_service_without_secret_echo(
            self, client, pinned_service, monkeypatch):
        seen = {}

        async def _smoke(**kwargs):
            seen.update(kwargs)
            return {"healthy": True, "job_id": "JOB1", "backend": "ibm_hw",
                    "shots": 256, "bits": 128, "usage_seconds": 0.5,
                    "deposited": False, "checked_at": 1700000000}

        monkeypatch.setattr(pinned_service, "ibm_hardware_smoke", _smoke)
        resp = client.post("/api/random/ibm/smoke", headers=_hdr(),
                           json={"key": GOOD_KEY, "crn": GOOD_CRN,
                                 "shots": 256, "confirm": True})
        assert resp.status_code == 200, resp.text
        assert seen["draft_key"] == GOOD_KEY
        assert seen["draft_crn"] == GOOD_CRN
        assert seen["shots"] == 256
        assert GOOD_KEY not in resp.text
        assert GOOD_CRN not in resp.text
        assert resp.json()["deposited"] is False

    def test_moderator_403(self, client, pinned_service):
        resp = client.post("/api/random/ibm/smoke",
                           headers=_hdr(MODERATOR_ID),
                           json={"key": GOOD_KEY, "confirm": True})
        assert resp.status_code == 403


class TestIbmAdminFields:
    def test_save_key_and_crn_masked_and_never_echoed(self, client):
        resp = client.post("/api/config", headers=_hdr(), json={
            "items": [{"key": IBM_KEY, "value": GOOD_KEY},
                      {"key": IBM_CRN, "value": GOOD_CRN}]})
        assert resp.status_code == 200, resp.text
        assert GOOD_KEY not in resp.text
        assert GOOD_CRN not in resp.text
        assert set(resp.json()["updated"]) == {IBM_KEY, IBM_CRN}

        read = client.get("/api/config", headers=_hdr())
        assert read.status_code == 200
        items = {i["key"]: i for i in read.json()["items"]}
        assert items[IBM_KEY]["secret"] is True
        assert items[IBM_KEY]["value"] == {"configured": True,
                                           "last4": GOOD_KEY[-4:]}
        assert items[IBM_CRN]["secret"] is True
        assert items[IBM_CRN]["value"]["configured"] is True
        assert GOOD_KEY not in read.text
        assert GOOD_CRN not in read.text
        # Instance/region — не секреты и видны владельцу (r8 finding).
        assert items[IBM_INSTANCE]["secret"] is False
        assert items[IBM_INSTANCE]["value"] == "open-instance"
        assert items[IBM_REGION]["value"] == "us-east"

    def test_clear_key_crn_and_reset_instance(self, client):
        # R1/P5B-R1-01: явное удаление/сброс — НЕ 422. Секрет очищается,
        # GET снова {configured:false}; instance возвращается к пустому
        # значению (runtime использует заводской open-instance).
        saved = client.post("/api/config", headers=_hdr(), json={
            "items": [{"key": IBM_KEY, "value": GOOD_KEY},
                      {"key": IBM_CRN, "value": GOOD_CRN},
                      {"key": IBM_INSTANCE, "value": "open-instance"}]})
        assert saved.status_code == 200, saved.text

        cleared_key = client.post("/api/config", headers=_hdr(), json={
            "items": [{"key": IBM_KEY, "value": ""}]})
        assert cleared_key.status_code == 200, cleared_key.text
        read = client.get("/api/config", headers=_hdr())
        item = next(i for i in read.json()["items"] if i["key"] == IBM_KEY)
        assert item["value"] == {"configured": False, "last4": None}

        cleared_crn = client.post("/api/config", headers=_hdr(), json={
            "items": [{"key": IBM_CRN, "value": ""}]})
        assert cleared_crn.status_code == 200, cleared_crn.text
        read_crn = client.get("/api/config", headers=_hdr())
        item = next(i for i in read_crn.json()["items"]
                    if i["key"] == IBM_CRN)
        assert item["value"]["configured"] is False

        reset_instance = client.post("/api/config", headers=_hdr(), json={
            "items": [{"key": IBM_INSTANCE, "value": ""}]})
        assert reset_instance.status_code == 200, reset_instance.text
        read2 = client.get("/api/config", headers=_hdr())
        item = next(i for i in read2.json()["items"]
                    if i["key"] == IBM_INSTANCE)
        assert item["value"] == ""

    def test_whitespace_only_is_empty_and_values_are_trimmed(self, client):
        # R2/P5B-R2-02: пробелы не являются значением. whitespace-only —
        # clear/reset; непустое значение сохраняется без обрамляющих пробелов.
        saved = client.post("/api/config", headers=_hdr(), json={
            "items": [{"key": IBM_KEY, "value": f"  {GOOD_KEY}  "},
                      {"key": IBM_CRN, "value": f" \t {GOOD_CRN} "},
                      {"key": IBM_INSTANCE, "value": " open-instance "}]})
        assert saved.status_code == 200, saved.text
        read = client.get("/api/config", headers=_hdr())
        item = next(i for i in read.json()["items"] if i["key"] == IBM_KEY)
        assert item["value"] == {"configured": True,
                                 "last4": GOOD_KEY[-4:]}
        item = next(i for i in read.json()["items"] if i["key"] == IBM_CRN)
        assert item["value"]["configured"] is True
        item = next(i for i in read.json()["items"] if i["key"] == IBM_INSTANCE)
        assert item["value"] == "open-instance"

        for key, value in ((IBM_KEY, "   \t  "), (IBM_CRN, "  \n  "),
                           (IBM_INSTANCE, " \t ")):
            resp = client.post("/api/config", headers=_hdr(),
                               json={"items": [{"key": key,
                                                "value": value}]})
            assert resp.status_code == 200, (key, resp.text)
        read2 = client.get("/api/config", headers=_hdr())
        item = next(i for i in read2.json()["items"] if i["key"] == IBM_KEY)
        assert item["value"] == {"configured": False, "last4": None}
        item = next(i for i in read2.json()["items"] if i["key"] == IBM_CRN)
        assert item["value"]["configured"] is False
        item = next(i for i in read2.json()["items"]
                    if i["key"] == IBM_INSTANCE)
        assert item["value"] == ""

    def test_422_never_echoes_submitted_secret(self, client):
        # R1/M6: даже ошибочный ввод не возвращается в теле 422.
        cases = (
            (IBM_KEY, "P5B SENTINEL KEY", "P5B SENTINEL KEY"),
            (IBM_KEY, "P5BSECRET", "P5BSECRET"),
            (IBM_CRN,
             "crn:v1:bluemix:public:other:us-east:a/P5B-SENTINEL-CRN:x::",
             "P5B-SENTINEL-CRN"),
            (IBM_INSTANCE, "P5B SENTINEL INSTANCE", "P5B SENTINEL INSTANCE"),
        )
        for key, value, sentinel in cases:
            resp = client.post("/api/config", headers=_hdr(),
                               json={"items": [{"key": key,
                                                "value": value}]})
            assert resp.status_code == 422, (key, resp.text)
            assert sentinel not in resp.text, (key, resp.text)
            assert value not in resp.text, (key, resp.text)

    def test_non_admin_cannot_write_provider_fields(self, client):
        for key, value in ((IBM_KEY, GOOD_KEY), (IBM_CRN, GOOD_CRN),
                           (IBM_INSTANCE, "open-instance")):
            resp = client.post("/api/config", headers=_hdr(MODERATOR_ID),
                               json={"items": [{"key": key, "value": value}]})
            assert resp.status_code == 403, (key, resp.text)

    def test_invalid_key_and_crn_shapes_422(self, client):
        for key, value, code in (
                (IBM_KEY, "short", "too_short"),
                (IBM_KEY, "bad key with spaces", "invalid_chars"),
                (IBM_CRN, "crn:full:value", "incomplete"),
                (IBM_CRN, "crn:v1:bluemix:public:other:us-east:a/x:y::",
                 "service"),
                (IBM_INSTANCE, "open instance", "invalid_chars"),
                (IBM_REGION, "us east", "региона"),
                (mrs.SETTING_IBM_CHANNEL, "ibm_cloud", "канал")):
            resp = client.post("/api/config", headers=_hdr(),
                               json={"items": [{"key": key, "value": value}]})
            assert resp.status_code == 422, (key, value, resp.text)
            assert code in resp.text

    def test_key_not_in_logs(self, client, pinned_service, caplog):
        import logging
        fake = _FakeIbmClient(result={
            "provider": "ibm_quantum", "healthy": False,
            "blocker": "auth_failed", "stage": "permission",
            "reason": "unauthorized", "key_present": True,
            "crn_present": False, "instance": "open-instance",
            "region": "us-east", "channel": "ibm_quantum_platform",
            "backends": [], "checked_at": 1,
        })
        pinned_service.set_ibm_client(fake)
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/api/random/test", headers=_hdr(),
                               json={"provider": "ibm_quantum",
                                     "key": GOOD_KEY})
        assert resp.status_code == 200
        assert GOOD_KEY not in caplog.text
