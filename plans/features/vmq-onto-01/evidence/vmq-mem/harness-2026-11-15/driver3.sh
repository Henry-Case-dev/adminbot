#!/bin/bash
# Focused relations probe (MEM-03 metric 4). Read-only, throwaway clones/copy.
set -u
APP=/var/www/admin_bot
BASE=/root/vmq2/measure3
BASE_SHA=c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
CAND_SHA=f7a9c596638ea733de5673c5fd31675c746e20a7
say() { echo "== $* =="; }
mkdir -p "$BASE/out" || exit 2
VENV=""
for c in venv .venv env; do
  [ -x "$APP/$c/bin/python" ] && VENV="$APP/$c/bin/python" && break
done
[ -x "$VENV" ] || { echo "STOP: no venv"; exit 3; }
say "clones"
rm -rf "$BASE/repo-base" "$BASE/repo-cand"
git clone -q --shared --no-checkout "$APP" "$BASE/repo-base" || exit 4
git -C "$BASE/repo-base" fetch -q "$BASE/cand.bundle" \
  refs/heads/tmp/vmq2-evidence:refs/heads/vmq2cand || exit 5
echo "cand=$(git -C $BASE/repo-base rev-parse refs/heads/vmq2cand)"
git -C "$BASE/repo-base" checkout -q "$BASE_SHA" || exit 6
git clone -q --shared --no-checkout "$BASE/repo-base" "$BASE/repo-cand" || exit 7
git -C "$BASE/repo-cand" checkout -q "$CAND_SHA" || exit 8
say "db copy"
rm -f "$BASE/dbcopy.db"*
"$VENV" - "$APP/local_database.db" "$BASE/dbcopy.db" <<'PY'
import os, sqlite3, sys
s = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
print("bytes=%d" % os.path.getsize(sys.argv[2]))
PY
[ -s "$BASE/dbcopy.db" ] || exit 9
say "entities"
cd "$BASE/repo-base" || exit 10
VMQ_CLONE="$BASE/repo-base" VMQ_DB="$BASE/dbcopy.db" VMQ_ENT="$BASE/entities.json" \
  timeout 900 "$VENV" "$BASE/entities.py" 2>&1 | tail -6
say "cfg"
cd "$APP" || exit 10
VMQ_CFG="$BASE/cfg.json" timeout 300 "$VENV" "$BASE/cfg_probe.py" 2>&1 | tail -3
say "relations base"
cd "$BASE/repo-base" || exit 10
VMQ_VARIANT=base VMQ_CLONE="$BASE/repo-base" VMQ_DB="$BASE/dbcopy.db" \
  VMQ_ENT="$BASE/entities.json" VMQ_CFG="$BASE/cfg.json" \
  VMQ_HEAD=$(git -C "$BASE/repo-base" rev-parse HEAD) \
  VMQ_OUT="$BASE/out/rel-base.json" timeout 900 "$VENV" "$BASE/relations_probe.py" 2>&1 | tail -12
say "relations cand"
cd "$BASE/repo-cand" || exit 10
VMQ_VARIANT=cand VMQ_CLONE="$BASE/repo-cand" VMQ_DB="$BASE/dbcopy.db" \
  VMQ_ENT="$BASE/entities.json" VMQ_CFG="$BASE/cfg.json" \
  VMQ_HEAD=$(git -C "$BASE/repo-cand" rev-parse HEAD) \
  VMQ_OUT="$BASE/out/rel-cand.json" timeout 900 "$VENV" "$BASE/relations_probe.py" 2>&1 | tail -12
say "files"
ls -la "$BASE/out"; sha256sum "$BASE/out"/*.json
echo "== DONE =="
