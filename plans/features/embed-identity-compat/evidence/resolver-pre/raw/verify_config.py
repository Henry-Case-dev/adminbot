"""EMBED-RESOLVER-PREDEPLOY: verify prod effective embedding config (read-only).

Never prints secrets: only model/dim/base_url keys, and only presence booleans
for credential keys / DSN.
"""
from __future__ import annotations

import re
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
REPO = Path(__file__).resolve().parents[2]
CREDS = REPO / "deploy_commands.txt"

REMOTE = r"""
set -u
cd /var/www/admin_bot || exit 3
echo "GIT=$(git rev-parse --short HEAD 2>/dev/null) | $(git log -1 --format=%s 2>/dev/null | head -c 90)"
echo "ACTIVE_ENTER=$(systemctl show -p ActiveEnterTimestamp --value admin_bot 2>/dev/null)"
echo "N_RESTARTS=$(systemctl show -p NRestarts --value admin_bot 2>/dev/null)"
echo "--- env (non-secret) ---"
grep -E '^(EMBEDDING_MODEL_NAME|EMBEDDING_BASE_URL|EMBEDDING_DIM|EMBED_COMPAT_ADOPTION_ENABLED|GRAPHRAG_SHADOW_REBUILD_ENABLED)=' .env 2>/dev/null || echo "(no such keys)"
echo "HAS_POSTGRES_DSN=$(grep -cE '^POSTGRES_DSN=.+' .env 2>/dev/null || echo 0)"
echo "--- pg hot config ---"
venv/bin/python - <<'PYEOF'
import asyncio, os
async def main():
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        from config.settings import settings
        dsn = getattr(settings, "POSTGRES_DSN", None)
    if not dsn:
        print("PG: POSTGRES_DSN отсутствует → hot config = settings/.env")
        return
    import asyncpg
    c = await asyncpg.connect(dsn, timeout=10)
    try:
        rows = await c.fetch(
            "SELECT key, value FROM bot_settings WHERE key IN "
            "('models.embedding_model_name','models.embedding_dim',"
            "'models.embedding_base_url') ORDER BY key")
        for r in rows:
            print("PG_ROW", r["key"], "=", str(r["value"])[:80])
        print("PG_ROWS", len(rows))
        keyed = await c.fetchval(
            "SELECT count(*) FROM bot_settings WHERE key LIKE '%embedding%api_key%'")
        print("PG_EMBED_KEY_ROWS", int(keyed or 0))
    finally:
        await c.close()
asyncio.run(main())
PYEOF
echo "--- rebuild jobs ---"
venv/bin/python - <<'PYEOF'
import sqlite3
c = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro", uri=True, timeout=15)
c.row_factory = sqlite3.Row
c.execute("PRAGMA query_only=ON")
try:
    for r in c.execute("SELECT id, kind, status, reason, created_at, updated_at "
                       "FROM task_jobs WHERE kind LIKE '%graphrag%' OR kind LIKE "
                       "'%embedding%' ORDER BY id DESC LIMIT 10"):
        print("JOB", dict(r))
except Exception as exc:
    print("JOB_ERR", type(exc).__name__, str(exc)[:120])
PYEOF
echo "--- done ---"
"""


def pwd(name: str = "pass") -> str:
    m = re.search(rf"^{name}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{name}' not found")
    return m.group(1)


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, pwd(), timeout=20, banner_timeout=20,
                   auth_timeout=20, allow_agent=False, look_for_keys=False)
    try:
        _i, stdout, stderr = client.exec_command(REMOTE, timeout=180)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
    finally:
        client.close()
    print(out)
    if err.strip():
        print("[stderr]", err[:1500])
    print("[rc]", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
