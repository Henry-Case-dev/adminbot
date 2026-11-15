#!/bin/bash
# VMQ-MEM/TIME Slice A corpus proof driver (parity cfg with embedding route keys) (runs ON the production host).
# Read-only w.r.t. live data: both trees are throwaway clones, the database is
# a COPY under /root/vmqA/measure, /var/www/admin_bot is only read.
# Nothing is restarted, nothing is sent, no live row is written.
set -u

APP=/var/www/admin_bot
BASE=/root/vmqD/measure
BASE_SHA=c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
CAND_SHA=570a49db9aa0d1d487e43e2d0ffae0dffcb00497

say() { echo "== $* =="; }
mkdir -p "$BASE/out" || exit 2

say "0 deployed identity"
echo "deployed_head=$(git -C $APP rev-parse HEAD 2>&1)"
echo "deployed_branch=$(git -C $APP rev-parse --abbrev-ref HEAD 2>&1)"
echo "deployed_dirty=$(git -C $APP status --porcelain 2>/dev/null | wc -l)"
df -Pk /root | awk 'NR>1 {print "free_kb="$4}'
VENV=""
for c in venv .venv env; do
  if [ -x "$APP/$c/bin/python" ]; then VENV="$APP/$c/bin/python"; break; fi
done
echo "VENV=$VENV"
[ -x "$VENV" ] || { echo "STOP: no venv python"; exit 3; }
"$VENV" -V

say "0b free disk guard (copy is ~3.3 GB)"
FREE_KB=$(df -Pk /root | awk 'NR>1 {print $4}')
echo "free_kb_before=$FREE_KB"
if [ "${FREE_KB:-0}" -lt 6500000 ]; then
  echo "STOP: not enough free space for a fresh DB copy"
  exit 12
fi

say "1 clones (base + candidate)"
rm -rf "$BASE/repo-base" "$BASE/repo-cand"
git clone -q --shared --no-checkout "$APP" "$BASE/repo-base" 2>&1 | tail -2
GOTBASE=$(git -C "$BASE/repo-base" cat-file -t "$BASE_SHA" 2>&1)
echo "base_object=$GOTBASE"
[ "$GOTBASE" = "commit" ] || { echo "STOP: base commit unavailable"; exit 4; }
git -C "$BASE/repo-base" fetch -q "$BASE/cand.bundle" \
    refs/heads/tmp/mem-a:refs/heads/mem-a-cand 2>&1 | tail -3
GOT=$(git -C "$BASE/repo-base" rev-parse refs/heads/mem-a-cand 2>/dev/null)
echo "candidate_fetched=$GOT"
[ "$GOT" = "$CAND_SHA" ] || { echo "STOP: candidate object unavailable"; exit 5; }
git -C "$BASE/repo-base" checkout -q "$BASE_SHA" || exit 6
echo "base_head=$(git -C $BASE/repo-base rev-parse HEAD)"
echo "base_tree=$(git -C $BASE/repo-base rev-parse 'HEAD^{tree}')"
git clone -q --shared --no-checkout "$BASE/repo-base" "$BASE/repo-cand" 2>&1 | tail -2
git -C "$BASE/repo-cand" checkout -q "$CAND_SHA" || exit 7
echo "cand_head=$(git -C $BASE/repo-cand rev-parse HEAD)"
echo "cand_tree=$(git -C $BASE/repo-cand rev-parse 'HEAD^{tree}')"
echo "cand_dirty=$(git -C $BASE/repo-cand status --porcelain | wc -l)"
echo "base_dirty=$(git -C $BASE/repo-base status --porcelain | wc -l)"
echo "merge_base=$(git -C $BASE/repo-base merge-base $BASE_SHA $CAND_SHA)"

say "2 fresh database copy (read-only .backup)"
rm -f "$BASE/dbcopy.db" "$BASE/dbcopy.db-wal" "$BASE/dbcopy.db-shm"
"$VENV" - "$APP/local_database.db" "$BASE/dbcopy.db" <<'PY'
import os, sqlite3, sys, time
src, dst = sys.argv[1], sys.argv[2]
t0 = time.time()
s = sqlite3.connect("file:%s?mode=ro" % src, uri=True, timeout=20)
d = sqlite3.connect(dst)
s.backup(d)
d.close(); s.close()
print("copy_seconds=%.1f size=%d" % (time.time() - t0, os.path.getsize(dst)))
c = sqlite3.connect("file:%s?mode=ro" % dst, uri=True)
print("user_version=%s msgs=%s facts=%s episodes=%s" % (
    c.execute("PRAGMA user_version").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM smart_messages").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM graph_facts").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM mca_episodes").fetchone()[0]))
c.close()
PY
[ -s "$BASE/dbcopy.db" ] || { echo "STOP: db copy failed"; exit 8; }

say "3 corpus freeze"
sha256sum "$BASE/dbcopy.db" | tee "$BASE/out/dbcopy.sha256"
ls -la "$BASE/dbcopy.db" | awk '{print "db_bytes="$5}' | tee -a "$BASE/out/dbcopy.sha256"

say "4 entity selection (deterministic, same file for both variants)"
cd "$BASE/repo-base" || exit 9
VMQ_CLONE="$BASE/repo-base" VMQ_DB="$BASE/dbcopy.db" VMQ_ENT="$BASE/entities.json" \
  timeout 1200 "$VENV" "$BASE/entities.py" 2>&1 | tail -12
[ -s "$BASE/entities.json" ] || { echo "STOP: entity selection failed"; exit 10; }

say "5 effective config snapshot (read-only PG SELECT)"
cd "$APP" || exit 9
VMQ_CFG="$BASE/cfg_full.json" timeout 300 "$VENV" "$BASE/cfg_probe_slice_a.py" 2>&1 | tail -8
[ -s "$BASE/cfg_full.json" ] || { echo "STOP: config probe failed"; exit 11; }

say "6 probe BASELINE $BASE_SHA"
cd "$BASE/repo-base" || exit 9
VMQ_VARIANT=base VMQ_CLONE="$BASE/repo-base" VMQ_DB="$BASE/dbcopy.db" \
  VMQ_ENT="$BASE/entities.json" VMQ_CFG="$BASE/cfg_full.json" \
  VMQ_HEAD=$(git -C "$BASE/repo-base" rev-parse HEAD) \
  VMQ_TREE=$(git -C "$BASE/repo-base" rev-parse 'HEAD^{tree}') \
  VMQ_OUT="$BASE/out/base_full.json" \
  timeout 2400 "$VENV" "$BASE/probe_slice_a.py" 2>&1 | tail -45
[ -s "$BASE/out/base_full.json" ] || echo "BASE_NO_OUTPUT"

say "7 probe CANDIDATE $CAND_SHA"
cd "$BASE/repo-cand" || exit 9
VMQ_VARIANT=cand VMQ_CLONE="$BASE/repo-cand" VMQ_DB="$BASE/dbcopy.db" \
  VMQ_ENT="$BASE/entities.json" VMQ_CFG="$BASE/cfg_full.json" \
  VMQ_HEAD=$(git -C "$BASE/repo-cand" rev-parse HEAD) \
  VMQ_TREE=$(git -C "$BASE/repo-cand" rev-parse 'HEAD^{tree}') \
  VMQ_OUT="$BASE/out/cand_full.json" \
  timeout 2400 "$VENV" "$BASE/probe_slice_a.py" 2>&1 | tail -45
[ -s "$BASE/out/cand_full.json" ] || echo "CAND_NO_OUTPUT"

say "8 evidence files"
ls -la "$BASE/out"
sha256sum "$BASE/out"/*.json | tee "$BASE/out/sha256.txt"
df -Pk /root | awk 'NR>1 {print "free_kb="$4}'
echo "== DONE (cleanup runs after download) =="
