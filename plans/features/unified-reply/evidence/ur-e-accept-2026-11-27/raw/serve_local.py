"""UR-BAN-08 local UI harness: runs the REAL FastAPI app (no PG, temp DB).

Read-only: only GET endpoints are exercised by the browser; POST is never sent.
DB_PATH points to a throwaway SQLite file next to this script. Identities are
synthetic (no Telegram, no token of the project): the local bot token is a
literal placeholder and the identity gets a global-admin role injected into the
in-memory ConfigCache only, so the admin UI can be reviewed. No project
credential, no production host, no Telegram chat.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import quote

REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\ur-e-accept-1ef96b25076e-1e7769b0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(REPO)

TOKEN = "123456:LOCAL_UI_CHECK_TOKEN"          # synthetic, not a project secret
LOCAL_USER_ID = 111111111
os.environ["API_TOKEN"] = TOKEN
os.environ["TMA_AUTH_MAX_AGE"] = "0"
os.environ["DB_PATH"] = os.path.join(HERE, "ui_check.db")

from services.config_cache import ConfigCache          # noqa: E402
from services.permissions import Permissions           # noqa: E402
from web.app import create_app                         # noqa: E402


def sign_init_data(user: dict) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF-local-ui-check",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    dcs = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return "&".join("%s=%s" % (k, quote(str(v), safe="")) for k, v in fields.items())


INIT_DATA = sign_init_data({"id": LOCAL_USER_ID, "first_name": "Local",
                            "username": "local_check", "language_code": "ru"})

cache = ConfigCache(retry_attempts=1, retry_delay=0)
app = create_app(cache)


@app.on_event("startup")
async def _inject_local_admin() -> None:
    """In-memory only: the real RBAC resolver is untouched; the synthetic local
    identity just gets a global-admin role so the admin surface can render."""
    if not cache.is_initialized:
        await cache.init()
    cache._admins[LOCAL_USER_ID] = "global_admin"
    cache._permissions["global_admin"] = Permissions.from_dict({"wildcard": True})


if __name__ == "__main__":
    import uvicorn
    with open(os.path.join(HERE, "init_data.txt"), "w", encoding="utf-8") as fh:
        fh.write(INIT_DATA)
    uvicorn.run(app, host="127.0.0.1", port=8871, log_level="warning")
