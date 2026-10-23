"""EMBED-RESOLVER-PREDEPLOY: read-only recon on prod (one SSH connect, no retry).

Prints registry rows + db sizes. Never writes to prod DB, never prints secrets.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
REPO = Path(__file__).resolve().parents[2]
CREDS = REPO / "deploy_commands.txt"


def pwd(name: str = "pass") -> str:
    m = re.search(rf"^{name}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{name}' not found")
    return m.group(1)


REMOTE = r"""
set -u
cd /var/www/admin_bot || exit 3
echo "== FILES =="
ls -l local_database.db local_database.db-wal local_database.db-shm 2>/dev/null
python3 - <<'PY'
import json, sqlite3
c = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro", uri=True, timeout=15)
c.row_factory = sqlite3.Row
c.execute("PRAGMA query_only=ON")
print("QUERY_ONLY", c.execute("PRAGMA query_only").fetchone()[0])
cols = [r["name"] for r in c.execute("PRAGMA table_info(mca_embedding_index_generations)")]
print("COLS", json.dumps(cols))
print("COUNT", c.execute("SELECT count(*) FROM mca_embedding_index_generations").fetchone()[0])
for r in c.execute("SELECT * FROM mca_embedding_index_generations "
                   "ORDER BY index_name, generation DESC LIMIT 40"):
    print("ROW", json.dumps(dict(r), ensure_ascii=False, default=str))
print("NS", json.dumps([dict(r) for r in c.execute(
    "SELECT namespace, count(*) AS n FROM mca_embedding_index_generations GROUP BY namespace")]))
tables = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'smart_archive%' "
    "OR name LIKE 'graph_facts%' OR name LIKE 'mca_embedding%') ORDER BY name")]
print("TABLES", json.dumps(tables))
for t in ("graph_facts_vec", "smart_archive"):
    row = c.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()
    print("DDL", t, (row[0] if row else "")[:400])
try:
    print("COUNTS", json.dumps(dict(zip(
        ("graph_facts_vec", "graph_facts", "smart_archive", "smart_archive_facts"),
        [c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in
         ("graph_facts_vec", "graph_facts", "smart_archive", "smart_archive_facts")]))))
except Exception as exc:
    print("COUNTS_ERR", type(exc).__name__, str(exc)[:200])
PY
echo "== DONE =="
"""


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, pwd(), timeout=15, banner_timeout=15,
                   auth_timeout=15, allow_agent=False, look_for_keys=False)
    try:
        _stdin, stdout, stderr = client.exec_command(REMOTE, timeout=180)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
    finally:
        client.close()
    sys.stdout.write(out)
    if err.strip():
        sys.stdout.write("\n[stderr]\n" + err)
    sys.stdout.write(f"\n[rc] {rc}\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
