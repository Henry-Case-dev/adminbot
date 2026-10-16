"""SOUL-1 r3: реальная сборка `/api/config` — приложение как в проде.

Без pytest: реплика фикстуры `tests/test_webapp_api.py::client` (фейковый PG,
реальный `web.app.create_app` + `ConfigCache`, реальный роут
`web/api/routes.py::get_config`). Наружу — только JSON-сводка, без секретов.

Запуск: .venv\\Scripts\\python.exe <этот файл>
"""
import hashlib
import hmac
import json
import os
import sys
import time
import types
import urllib.parse

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from fastapi.testclient import TestClient  # noqa: E402

from services.config_cache import ConfigCache  # noqa: E402
from web.api import deps as deps_mod  # noqa: E402
from web.app import create_app  # noqa: E402

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495


def make_init_data(user_id=ADMIN_ID) -> str:
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


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False
        return _Tx()

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
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()

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

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        pass


def main() -> int:
    deps_mod.settings = types.SimpleNamespace(API_TOKEN=TEST_TOKEN)
    conn = _FakeConn(
        settings_rows=[],
        role_rows=[{"role_name": "admin", "permissions": {"wildcard": True},
                    "is_custom": False}],
        admin_rows=[{"telegram_id": ADMIN_ID, "role_name": "admin",
                     "added_by": None,
                     "created_at": "2026-08-30T00:00:00+00:00"}],
    )
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    out = {"endpoint": "GET /api/config (real route)", "ok": False}
    with TestClient(app) as client:
        resp = client.get(
            "/api/config",
            headers={"X-Telegram-Init-Data": make_init_data(ADMIN_ID)})
        out["status"] = resp.status_code
        if resp.status_code != 200:
            out["detail"] = resp.text[:300]
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        body = resp.json()
        prompts = [it for it in body["items"]
                   if it["key"].startswith("prompts.")]
        key = next((it for it in prompts
                    if it["key"] == "prompts.direct_l1_planner_system_prompt"),
                   None)
        out["prompts_items"] = len(prompts)
        out["group_ids_category_prompts"] = sorted(
            {g["id"] for g in body["groups"] if g["category"] == "prompts"})
        if key is None:
            out["error"] = "L1 planner key MISSING from real /api/config"
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        out["l1_key"] = {
            "group": key["group"], "stage": key["stage"],
            "title": key["title"],
            "progressive_level": key["progressive_level"],
            "widget": key["widget"], "secret": key["secret"],
            "value_len": len(key["value"]) if isinstance(key["value"], str)
            else None,
        }
        assert key["group"] == "prompts_direct_chat"
        assert key["stage"] == "synthesizer"
        assert key["progressive_level"] == "advanced"
        assert isinstance(key["value"], str) and len(key["value"]) > 100, \
            "value must be the code canon"
        out["ok"] = True
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
