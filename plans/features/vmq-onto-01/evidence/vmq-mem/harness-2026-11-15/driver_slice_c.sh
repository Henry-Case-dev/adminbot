#!/bin/bash
# VMQ-MEM/TIME Slice C corpus proof driver (runs ON the production host).
# Read-only w.r.t. live data: both trees are throwaway clones, the database is a
# COPY under /root/vmqC/measure, /var/www/admin_bot is only read.
# Nothing is restarted, nothing is sent, no live row is written.
set -u

APP=/var/www/admin_bot
BASE=/root/vmqC/measure
BASE_SHA=d159ea8ad8362616ec78b43cb64a3e54ec7de2e6   # Slice B (baseline)
CAND_SHA=16931216                                     # Slice C (code commit)
HARNESS="$BASE/probe_slice_c.py"

say() { echo "== $* =="; }
mkdir -p "$BASE/out" || exit 2

say "0 deployed identity (must stay c97c06e4 / no deploy)"
echo "deployed_head=$(git -C $APP rev-parse HEAD 2>&1)"
echo "deployed_branch=$(git -C $APP rev-parse --abbrev-ref HEAD 2>&1)"
echo "deployed_dirty=$(git -C $APP status --porcelain 2>/dev/null | wc -l)"
date -u '+utc=%Y-%m-%dT%H:%M:%SZ'
VENV=""
for c in venv .venv env; do
  if [ -x "$APP/$c/bin/python" ]; then VENV="$APP/$c/bin/python"; break; fi
done
echo "VENV=$VENV"
[ -x "$VENV" ] || { echo "STOP: no venv python"; exit 3; }
"$VENV" -V
echo "nrestarts=$(systemctl show admin_bot -p NRestarts --value 2>&1)"
echo "active_enter=$(systemctl show admin_bot -p ActiveEnterTimestamp --value 2>&1)"

say "0b free disk guard (copy is ~3.3 GB)"
FREE_KB=$(df -Pk /root | awk 'NR>1 {print $4}')
echo "free_kb_before=$FREE_KB"
if [ "${FREE_KB:-0}" -lt 7000000 ]; then
  echo "STOP: not enough free space for a fresh DB copy"
  exit 12
fi

say "1 clones (baseline $BASE_SHA, candidate $CAND_SHA)"
rm -rf "$BASE/repo-base" "$BASE/repo-cand"
git clone -q --shared --no-checkout "$APP" "$BASE/repo-base" 2>&1 | tail -2
[ -d "$BASE/repo-base/.git" ] || { echo "STOP: clone failed"; exit 4; }
REMOTE=$(git -C "$APP" remote get-url origin 2>/dev/null || true)
if [ -z "${REMOTE:-}" ]; then
  echo "STOP: no origin url on the deployed repo"
  exit 4
fi
git -C "$BASE/repo-base" remote add gh "$REMOTE" 2>&1 | tail -2
git -C "$BASE/repo-base" fetch -q gh refs/heads/vmq/mem-b refs/heads/vmq/mem-c 2>&1 | tail -3
GOTBASE=$(git -C "$BASE/repo-base" cat-file -t "$BASE_SHA" 2>&1)
GOTCAND=$(git -C "$BASE/repo-base" cat-file -t "$CAND_SHA" 2>&1)
echo "base_object=$GOTBASE candidate_object=$GOTCAND"
[ "$GOTBASE" = "commit" ] || { echo "STOP: base commit unavailable"; exit 4; }
[ "$GOTCAND" = "commit" ] || { echo "STOP: candidate commit unavailable"; exit 5; }
echo "mem_b_tip=$(git -C "$BASE/repo-base" rev-parse gh/vmq/mem-b)"
echo "mem_c_tip=$(git -C "$BASE/repo-base" rev-parse gh/vmq/mem-c)"
git -C "$BASE/repo-base" checkout -q "$BASE_SHA" || exit 6
git clone -q --shared "$BASE/repo-base" "$BASE/repo-cand" 2>&1 | tail -2
git -C "$BASE/repo-cand" checkout -q "$CAND_SHA" || exit 7
echo "base_head=$(git -C $BASE/repo-base rev-parse HEAD)"
echo "base_tree=$(git -C $BASE/repo-base rev-parse 'HEAD^{tree}')"
echo "cand_head=$(git -C $BASE/repo-cand rev-parse HEAD)"
echo "cand_tree=$(git -C $BASE/repo-cand rev-parse 'HEAD^{tree}')"
echo "merge_base=$(git -C $BASE/repo-base merge-base $BASE_SHA $CAND_SHA)"
echo "base_dirty=$(git -C $BASE/repo-base status --porcelain | wc -l)"
echo "cand_dirty=$(git -C $BASE/repo-cand status --porcelain | wc -l)"
for f in services/mca_retrieval_context.py services/direct_chat_service.py \
         services/database.py services/mca_episodes.py services/mca_gates.py; do
  echo "file_sha $f $(sha256sum "$BASE/repo-base/$f" | cut -c1-16) $(sha256sum "$BASE/repo-cand/$f" | cut -c1-16)"
done

say "2 fresh database copy (read-only .backup)"
rm -f "$BASE/dbcopy.db" "$BASE/dbcopy.db-wal" "$BASE/dbcopy.db-shm"
"$VENV" - "$APP/local_database.db" "$BASE/dbcopy.db" <<'PY'
import hashlib, os, sqlite3, sys, time
src, dst = sys.argv[1], sys.argv[2]
t0 = time.time()
s = sqlite3.connect("file:%s?mode=ro" % src, uri=True, timeout=20)
d = sqlite3.connect(dst)
s.backup(d)
d.close(); s.close()
print("copy_seconds=%.1f size=%d" % (time.time() - t0, os.path.getsize(dst)))
h = hashlib.sha256()
with open(dst, "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
print("sha256=%s" % h.hexdigest())
c = sqlite3.connect("file:%s?mode=ro" % dst, uri=True)
print("user_version=%s journal=%s page_size=%s pages=%s" % (
    c.execute("PRAGMA user_version").fetchone()[0],
    c.execute("PRAGMA journal_mode").fetchone()[0],
    c.execute("PRAGMA page_size").fetchone()[0],
    c.execute("PRAGMA page_count").fetchone()[0]))
print("msgs=%s facts=%s episodes=%s" % (
    c.execute("SELECT COUNT(*) FROM smart_messages").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM graph_facts").fetchone()[0],
    c.execute("SELECT COUNT(*) FROM mca_episodes").fetchone()[0]))
print("schema_version=%s" % (c.execute("PRAGMA schema_version").fetchone()[0],))
c.close()
PY
[ -s "$BASE/dbcopy.db" ] || { echo "STOP: db copy failed"; exit 8; }
sha256sum "$BASE/dbcopy.db" | tee "$BASE/out/dbcopy.sha256"
ls -la "$BASE/dbcopy.db" | awk '{print "db_bytes="$5}' | tee -a "$BASE/out/dbcopy.sha256"

say "3 entity selection (deterministic, same file for both variants)"
cd "$BASE/repo-base" || exit 9
VMQ_CLONE="$BASE/repo-base" VMQ_DB="$BASE/dbcopy.db" VMQ_ENT="$BASE/entities.json" \
  timeout 1800 "$VENV" "$BASE/entities.py" 2>&1 | tail -12
[ -s "$BASE/entities.json" ] || { echo "STOP: entity selection failed"; exit 10; }

say "4 effective config snapshot (read-only PG SELECT)"
cd "$APP" || exit 9
VMQ_CFG="$BASE/cfg_frozen.json" timeout 300 "$VENV" "$BASE/cfg_probe.py" 2>&1 | tail -6
[ -s "$BASE/cfg_frozen.json" ] || { echo "STOP: frozen cfg probe failed"; exit 11; }

run_probe() {  # $1=variant $2=clone $3=out
  if [ -s "$3" ]; then
    echo "PROBE_REUSE existing out=$3"
    return 0
  fi
  echo "PROBE_START variant=$1 clone=$2 out=$3"
  cd "$2" || return 9
  VMQ_VARIANT="$1" VMQ_CLONE="$2" VMQ_DB="$BASE/dbcopy.db" \
    VMQ_ENT="$BASE/entities.json" VMQ_CFG="$BASE/cfg_frozen.json" \
    VMQ_HEAD=$(git -C "$2" rev-parse HEAD) \
    VMQ_TREE=$(git -C "$2" rev-parse 'HEAD^{tree}') \
    VMQ_OUT="$3" timeout 2400 "$VENV" "$HARNESS" 2>&1 | tail -30
  [ -s "$3" ] || echo "PROBE_NO_OUTPUT variant=$1 out=$3"
}

say "5 probes: frozen cfg (13 keys, parity with corpus-run-2026-11-15)"
run_probe base "$BASE/repo-base" "$BASE/out/base_frozen.json"
run_probe cand "$BASE/repo-cand" "$BASE/out/cand_frozen.json"

say "6 evidence files"
ls -la "$BASE/out"
sha256sum "$BASE/out"/*.json > "$BASE/out/sha256.txt"
cat "$BASE/out/sha256.txt"
df -Pk /root | awk 'NR>1 {print "free_kb_after="$4}'
echo "deployed_head_after=$(git -C $APP rev-parse HEAD 2>&1)"
echo "nrestarts_after=$(systemctl show admin_bot -p NRestarts --value 2>&1)"
date -u '+utc_end=%Y-%m-%dT%H:%M:%SZ'
echo "DONE" > "$BASE/out/DONE"
echo "== DONE (cleanup runs after transfer) =="
