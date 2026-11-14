# -*- coding: utf-8 -*-
"""Run the lore-material probe in one SSH session, download, clean up."""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, r"C:\Users\main\.config\opencode\WorkspaceData\runs"
                   r"\c742e4de9e92c489\vmq-q1-39dc7cff5121\temp-13fea3ab4b")
import prod_conn as P  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
BASE = "/root/vmq2/measure4"
UPLOADS = {
    "cand.bundle": HERE / "cand.bundle",
    "cfg_probe.py": HERE / "cfg_probe.py",
    "lore_probe.py": HERE / "lore_probe.py",
}
DRIVER = r"""
set -u
APP=/var/www/admin_bot
BASE=/root/vmq2/measure4
BASE_SHA=c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
CAND_SHA=f7a9c596638ea733de5673c5fd31675c746e20a7
say() { echo "== $* =="; }
mkdir -p "$BASE/out" || exit 2
VENV=""
for c in venv .venv env; do
  [ -x "$APP/$c/bin/python" ] && VENV="$APP/$c/bin/python" && break
done
[ -x "$VENV" ] || { echo "STOP: no venv"; exit 3; }
say clones
rm -rf "$BASE/repo-base" "$BASE/repo-cand"
git clone -q --shared --no-checkout "$APP" "$BASE/repo-base" || exit 4
git -C "$BASE/repo-base" fetch -q "$BASE/cand.bundle" \
  refs/heads/tmp/vmq2-evidence:refs/heads/vmq2cand || exit 5
git -C "$BASE/repo-base" checkout -q "$BASE_SHA" || exit 6
git clone -q --shared --no-checkout "$BASE/repo-base" "$BASE/repo-cand" || exit 7
git -C "$BASE/repo-cand" checkout -q "$CAND_SHA" || exit 8
say db copy
rm -f "$BASE/dbcopy.db"*
"$VENV" - "$APP/local_database.db" "$BASE/dbcopy.db" <<'PY'
import os, sqlite3, sys
s = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
print("db_bytes=%d" % os.path.getsize(sys.argv[2]))
PY
[ -s "$BASE/dbcopy.db" ] || exit 9
DBSHA=$(sha256sum "$BASE/dbcopy.db" | cut -d' ' -f1)
echo "db_sha256=$DBSHA"
say cfg
cd "$APP" || exit 10
VMQ_CFG="$BASE/cfg.json" timeout 300 "$VENV" "$BASE/cfg_probe.py" 2>&1 | tail -3
say lore base
cd "$BASE/repo-base" || exit 10
VMQ_VARIANT=base VMQ_CLONE="$BASE/repo-base" VMQ_DB="$BASE/dbcopy.db" \
  VMQ_DB_SHA="$DBSHA" VMQ_CFG="$BASE/cfg.json" \
  VMQ_HEAD=$(git -C "$BASE/repo-base" rev-parse HEAD) \
  VMQ_OUT="$BASE/out/lore-base.json" timeout 900 "$VENV" "$BASE/lore_probe.py" 2>&1 | tail -10
say lore cand
cd "$BASE/repo-cand" || exit 10
VMQ_VARIANT=cand VMQ_CLONE="$BASE/repo-cand" VMQ_DB="$BASE/dbcopy.db" \
  VMQ_DB_SHA="$DBSHA" VMQ_CFG="$BASE/cfg.json" \
  VMQ_HEAD=$(git -C "$BASE/repo-cand" rev-parse HEAD) \
  VMQ_OUT="$BASE/out/lore-cand.json" timeout 900 "$VENV" "$BASE/lore_probe.py" 2>&1 | tail -10
say files
ls -la "$BASE/out"; sha256sum "$BASE/out"/*.json
echo "== DONE =="
"""
CLEANUP = (
    "chmod -R u+w {b}/repo-base {b}/repo-cand 2>/dev/null; "
    "rm -rf {b}/repo-base {b}/repo-cand {b}/out {b}/cfg.json "
    "{b}/dbcopy.db {b}/dbcopy.db-wal {b}/dbcopy.db-shm {b}/cand.bundle "
    "{b}/cfg_probe.py {b}/lore_probe.py; rmdir {b} 2>/dev/null; "
    "ls -la /root/vmq2 2>&1 | tail -3"
).format(b=BASE)


def main() -> int:
    cli = P.connect(timeout=25.0)
    try:
        rc, out, err = P.run(cli, "mkdir -p %s/out" % BASE, timeout=60)
        print("mkdir rc=%s %s %s" % (rc, out.strip(), err.strip()[:200]))
        sftp = cli.open_sftp()
        try:
            for name, local in UPLOADS.items():
                payload = local.read_bytes()
                if not name.endswith(".bundle"):
                    payload = payload.replace(b"\r\n", b"\n")
                with sftp.open("%s/%s" % (BASE, name), "wb") as fh:
                    fh.write(payload)
                print("uploaded %-16s %7d sha256=%s"
                      % (name, len(payload),
                         hashlib.sha256(payload).hexdigest()[:12]))
        finally:
            sftp.close()
        rc, out, err = P.run(cli, "bash -s <<'EOS'\n" + DRIVER + "\nEOS\n",
                             timeout=2400)
        print(out)
        if err.strip():
            print("[stderr] " + err[-1500:])
        print("DRIVER_RC=%s" % rc)
        sftp = cli.open_sftp()
        try:
            for name in ("lore-base.json", "lore-cand.json"):
                local = HERE / name
                try:
                    sftp.get("%s/out/%s" % (BASE, name), str(local))
                    print("downloaded %-16s %7d sha256=%s"
                          % (name, local.stat().st_size,
                             hashlib.sha256(local.read_bytes()).hexdigest()[:16]))
                except OSError as exc:
                    print("download FAILED %s: %s" % (name, exc))
        finally:
            sftp.close()
        rc2, out2, err2 = P.run(cli, CLEANUP, timeout=600)
        print(out2.strip())
        if err2.strip():
            print("[cleanup stderr] " + err2[-400:])
        print("CLEANUP_RC=%s" % rc2)
        return 0
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
