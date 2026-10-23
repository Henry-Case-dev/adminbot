"""EMBED-RESOLVER-PREDEPLOY: effective model check (read-only, no secrets)."""
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
venv/bin/python - <<'PYEOF'
import asyncio, os
import config.settings  # load_dotenv() заполняет os.environ
dsn = os.getenv("POSTGRES_DSN")
print("PG_DSN_PRESENT", bool(dsn))
if dsn:
    import asyncpg
    async def main():
        c = await asyncpg.connect(dsn, timeout=10)
        try:
            rows = await c.fetch(
                "SELECT key, value FROM bot_settings WHERE key IN "
                "('models.embedding_model_name','models.embedding_dim',"
                "'models.embedding_base_url') ORDER BY key")
            for r in rows:
                print("PG_ROW", r["key"], "=", str(r["value"])[:80])
            print("PG_ROWS", len(rows))
            n = await c.fetchval(
                "SELECT count(*) FROM bot_settings WHERE key LIKE '%embedding%'")
            print("PG_EMBED_KEYS_TOTAL", int(n or 0))
        finally:
            await c.close()
    asyncio.run(main())
PYEOF
echo "--- recent effective model in logs ---"
journalctl -u admin_bot --since "-48h" --no-pager 2>/dev/null | grep -oE "embed_once OK \| model=[^ ]+" | tail -5 || echo "(journal unavailable)"
echo "--- task_jobs ---"
venv/bin/python - <<'PYEOF'
import sqlite3
c = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro", uri=True, timeout=15)
c.row_factory = sqlite3.Row
c.execute("PRAGMA query_only=ON")
cols = [r[1] for r in c.execute("PRAGMA table_info(task_jobs)")]
print("TASK_JOBS_COLS", cols)
sel = ", ".join(c for c in cols if c in ("job_id","id","kind","status","reason",
                                         "created_at","updated_at","checkpoint"))
try:
    for r in c.execute(f"SELECT {sel} FROM task_jobs WHERE kind LIKE '%graphrag%' "
                       "OR kind LIKE '%embedding%' ORDER BY rowid DESC LIMIT 8"):
        print("JOB", dict(r))
except Exception as exc:
    print("JOB_ERR", type(exc).__name__, str(exc)[:140])
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
        _i, stdout, stderr = client.exec_command(REMOTE, timeout=240)
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
