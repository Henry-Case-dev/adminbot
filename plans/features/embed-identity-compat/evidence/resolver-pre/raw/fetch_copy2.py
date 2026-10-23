"""EMBED-RESOLVER-PREDEPLOY: one SSH session.

1) picks a python interpreter on prod that can load sqlite_vec (diagnostics
   printed for every candidate),
2) builds a read-only reduced copy of the prod DB in /tmp scratch,
3) gzips it, prints sha256,
4) downloads it over the SAME connection (SFTP),
5) removes the server scratch.

The prod DB is opened mode=ro with PRAGMA query_only=ON. Nothing is written
outside /tmp/embed-resolver-pre.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
REPO = Path(__file__).resolve().parents[2]
CREDS = REPO / "deploy_commands.txt"
LOCAL = REPO / "OPENCODE_WORKFLOW_SCRATCH" / "embed-resolver-pre"
REMOTE_DIR = "/tmp/embed-resolver-pre"

REMOTE_SH = r"""
set -u
cd /var/www/admin_bot || exit 3
D=/tmp/embed-resolver-pre
mkdir -p "$D" || exit 4
echo "UNIT_PY=$(systemctl show -p ExecStart admin_bot 2>/dev/null | grep -oE '/[^ ]*venv/bin/python[0-9.]*' | head -1)"
echo "--- candidates ---"
for PY in venv/bin/python venv/bin/python3 .venv/bin/python3 python3; do
  [ -x "$PY" ] || { echo "SKIP $PY (absent)"; continue; }
  echo "TRY $PY $($PY -c 'import sys;print(sys.version.split()[0])' 2>&1 | head -1)"
  $PY - <<'PYEOF'
import sqlite3
try:
    import sqlite_vec
except Exception as exc:
    print("  import sqlite_vec FAILED", type(exc).__name__, str(exc)[:120]); raise SystemExit(0)
print("  loadable_path", sqlite_vec.loadable_path())
c = sqlite3.connect(":memory:")
try:
    c.enable_load_extension(True)
except Exception as exc:
    print("  enable_load_extension FAILED", type(exc).__name__, str(exc)[:120]); raise SystemExit(0)
try:
    c.load_extension(sqlite_vec.loadable_path())
    print("  VEC_OK", c.execute("select vec_version()").fetchone()[0])
except Exception as exc:
    print("  load FAILED", type(exc).__name__, str(exc)[:160])
PYEOF
done
echo "--- build ---"
PY=""
for CAND in venv/bin/python venv/bin/python3 .venv/bin/python3 python3; do
  [ -x "$CAND" ] || continue
  if $CAND -c "import sqlite3,sqlite_vec;c=sqlite3.connect(':memory:');c.enable_load_extension(True);c.load_extension(sqlite_vec.loadable_path());c.execute('select vec_version()')" 2>/dev/null; then
    PY="$CAND"; break
  fi
done
if [ -z "$PY" ]; then echo "NO_VEC_PYTHON"; exit 7; fi
echo "WORKING_PY=$PY"
$PY "$D/remote_copy.py" "$D"
rc=$?
echo "PY_RC=$rc"
[ $rc -eq 0 ] || exit 5
gzip -1 -c "$D/copy.db" > "$D/copy.db.gz" || exit 6
rm -f "$D/copy.db"
ls -l "$D"
sha256sum "$D/copy.db.gz"
echo "REMOTE_DONE"
"""


def pwd(name: str = "pass") -> str:
    m = re.search(rf"^{name}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{name}' not found")
    return m.group(1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    LOCAL.mkdir(parents=True, exist_ok=True)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, pwd(), timeout=20, banner_timeout=20,
                   auth_timeout=20, allow_agent=False, look_for_keys=False)
    remote_sha = ""
    try:
        sftp = client.open_sftp()
        try:
            try:
                sftp.mkdir(REMOTE_DIR)
            except OSError:
                pass
            sftp.put(str(LOCAL / "remote_copy.py"), f"{REMOTE_DIR}/remote_copy.py")
        finally:
            sftp.close()
        _stdin, stdout, stderr = client.exec_command(REMOTE_SH, timeout=1800)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        print(out)
        if err.strip():
            print("[stderr]", err[:2000])
        print("[exec rc]", rc)
        if rc != 0 or "REMOTE_DONE" not in out:
            return rc or 9
        for line in out.splitlines():
            if re.match(r"^[0-9a-f]{64}\s", line):
                remote_sha = line.split()[0]
        sftp = client.open_sftp()
        try:
            sftp.get(f"{REMOTE_DIR}/meta.json", str(LOCAL / "remote_meta.json"))
            sftp.get(f"{REMOTE_DIR}/copy.db.gz", str(LOCAL / "copy.db.gz"))
        finally:
            sftp.close()
    finally:
        try:
            _i, so, _e = client.exec_command(f"rm -rf {REMOTE_DIR}; echo CLEAN_OK",
                                             timeout=60)
            print(so.read().decode("utf-8", "replace").strip())
        except Exception as exc:  # pragma: no cover
            print("cleanup failed:", exc)
        client.close()

    gz = LOCAL / "copy.db.gz"
    local_sha = sha256_file(gz)
    print("size_gz", gz.stat().st_size)
    print("remote_sha", remote_sha)
    print("local_sha ", local_sha)
    ok = bool(remote_sha) and remote_sha == local_sha
    print("SHA_MATCH", ok)
    (LOCAL / "transfer.json").write_text(json.dumps({
        "remote_sha256": remote_sha, "local_sha256": local_sha,
        "size_gz": gz.stat().st_size, "sha_match": ok}, indent=1),
        encoding="utf-8")
    return 0 if ok else 8


if __name__ == "__main__":
    raise SystemExit(main())
