#!/bin/bash
# 2.58.203 controlled deploy: 0beed63d -> c97c06e4
set -u
APP=/var/www/admin_bot
PY=$APP/venv/bin/python
EXPECT=c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
PREV=0beed63df8037002ccfaacef019b8ea948d957f6
TS=$(date -u +%Y%m%dT%H%M%SZ)
cd "$APP" || exit 90

say() { echo "[deploy203] $*"; }

echo "=== A. PRE-STATE ==="
date -u +%Y-%m-%dT%H:%M:%SZ
echo "HEAD=$(git rev-parse HEAD)"
echo "BRANCH=$(git branch --show-current)"
echo "TRACKED_DIRTY=$(git status --porcelain --untracked-files=no | wc -l)"
echo "UNTRACKED=$(git status --porcelain | grep -c '^??' || true)"
git status --porcelain | head -20
echo "APP_VERSION_LINE=$(grep -m1 '^APP_VERSION' config/settings.py | cut -c1-40)"
systemctl show admin_bot -p ActiveState -p MainPID -p ExecMainStartTimestamp --no-pager | tr '\n' ' '; echo
echo "HZ_LOCAL=$(curl -s --max-time 10 http://127.0.0.1:8000/healthz)"
echo "HZ_PUBLIC=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
df -k / | tail -1
echo "DB_BYTES=$(stat -c %s local_database.db)"
echo "BACKUPS_BYTES=$(du -sb backups 2>/dev/null | cut -f1)"
echo "MANIFEST_BEFORE=$(cat .deploy/release.json 2>/dev/null | tr -d '\n')"
echo "LS_TMP=$(ls -1 /tmp | grep -E 'snapshot|fc_live|verify203|prov203' | tr '\n' ' ')"

say "snapshot pre"
$PY /tmp/snapshot203.py /tmp/snapshot_pre_203.json >/tmp/snapshot_pre_203.stdout 2>/tmp/snapshot_pre_203.err
PRE_RC=$?
say "snapshot pre rc=$PRE_RC"
if [ $PRE_RC -ne 0 ]; then tail -20 /tmp/snapshot_pre_203.err; echo "ABORT snapshot_pre_failed"; exit 2; fi

echo "=== B. DB BACKUP ==="
BK=$APP/backups/pre_deploy_258203_${TS}.db
$PY - "$BK" <<'PYBK'
import sqlite3, sys
src = "/var/www/admin_bot/local_database.db"
dst = sys.argv[1]
con = sqlite3.connect(src, timeout=60)
con.execute("VACUUM INTO ?", (dst,))
con.close()
chk = sqlite3.connect(dst, timeout=60)
print("BK_INTEGRITY=%s" % (chk.execute("PRAGMA integrity_check").fetchone()[0],))
print("BK_USER_VERSION=%s" % (chk.execute("PRAGMA user_version").fetchone()[0],))
print("BK_TABLES=%s" % (chk.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],))
chk.close()
PYBK
BK_RC=$?
say "backup rc=$BK_RC"
if [ $BK_RC -ne 0 ]; then echo "ABORT backup_failed"; exit 3; fi
echo "BK_PATH=$BK"
echo "BK_SIZE=$(stat -c %s "$BK")"

echo "=== C. FETCH / FF ==="
git fetch --prune origin release/smart-corrective-01; echo "FETCH_RC=$?"
echo "FETCH_HEAD=$(git rev-parse FETCH_HEAD)"
git switch release/smart-corrective-01; echo "SWITCH_RC=$?"
git merge --ff-only FETCH_HEAD; MERGE_RC=$?
echo "MERGE_RC=$MERGE_RC"
echo "HEAD_AFTER_PULL=$(git rev-parse HEAD)"
echo "BRANCH_AFTER_PULL=$(git branch --show-current)"
echo "TRACKED_DIRTY_AFTER_PULL=$(git status --porcelain --untracked-files=no | wc -l)"
echo "APP_VERSION_AFTER_PULL=$(grep -m1 '^APP_VERSION' config/settings.py | cut -c1-40)"
if [ "$(git rev-parse HEAD)" != "$EXPECT" ]; then echo "ABORT head_mismatch"; exit 4; fi

echo "=== D. MANIFEST (before restart) ==="
$PY tools/release_manifest.py; MAN_RC=$?
echo "MANIFEST_RC=$MAN_RC"
chown adminbot:adminbot .deploy/release.json 2>/dev/null
chmod 644 .deploy/release.json 2>/dev/null
echo "MANIFEST_AFTER=$(cat .deploy/release.json | tr -d '\n')"
ls -l .deploy/release.json

echo "=== E. RESTART ==="
systemctl restart admin_bot; RESTART_RC=$?
echo "RESTART_RC=$RESTART_RC"
HZ=""
for i in $(seq 1 15); do
  sleep 2
  HZ=$(curl -s --max-time 8 http://127.0.0.1:8000/healthz)
  echo "POLL_$i=$HZ"
  case "$HZ" in *'"version":"2.58.203"'*) break;; esac
done
echo "HZ_PUBLIC_AFTER=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
systemctl show admin_bot -p ActiveState -p MainPID -p NRestarts -p ExecMainStatus --no-pager | tr '\n' ' '; echo

echo "=== F. POST-STATE ==="
sleep 4
date -u +%Y-%m-%dT%H:%M:%SZ
echo "HEAD=$(git rev-parse HEAD)"
echo "TRACKED_DIRTY=$(git status --porcelain --untracked-files=no | wc -l)"
echo "APP_VERSION_LINE=$(grep -m1 '^APP_VERSION' config/settings.py | cut -c1-40)"
$PY /tmp/snapshot203.py /tmp/snapshot_post_203.json >/tmp/snapshot_post_203.stdout 2>/tmp/snapshot_post_203.err
POST_RC=$?
say "snapshot post rc=$POST_RC"
if [ $POST_RC -ne 0 ]; then tail -20 /tmp/snapshot_post_203.err; fi

echo "=== G. JOURNAL (since restart) ==="
START_RAW=$(systemctl show admin_bot -p ExecMainStartTimestamp --value | sed 's/^[A-Za-z]* //; s/ UTC$//')
SINCE_EPOCH=$(date -u -d "$START_RAW" +%s)
echo "START_RAW=$START_RAW SINCE_EPOCH=$SINCE_EPOCH"
journalctl -u admin_bot --since "@$SINCE_EPOCH" --no-pager > /tmp/journal_203.txt 2>/dev/null
echo "JOURNAL_LINES=$(wc -l < /tmp/journal_203.txt)"
echo "TRACEBACK=$(grep -c 'Traceback' /tmp/journal_203.txt || true)"
echo "ERROR=$(grep -c ' - ERROR - ' /tmp/journal_203.txt || true)"
echo "CRITICAL=$(grep -c ' - CRITICAL - ' /tmp/journal_203.txt || true)"
echo "WARNING=$(grep -c ' - WARNING - ' /tmp/journal_203.txt || true)"
echo "--- prompt_release lines ---"
grep -F '[prompt_release]' /tmp/journal_203.txt | cut -c1-600
echo "--- error/warning lines ---"
grep -E ' - (ERROR|CRITICAL|WARNING) - ' /tmp/journal_203.txt | cut -c1-400
echo "--- traceback sample ---"
grep -n -A5 'Traceback' /tmp/journal_203.txt | head -30

echo "=== H. VERDICT INPUTS ==="
echo "POST_RC=$POST_RC RESTART_RC=$RESTART_RC MERGE_RC=$MERGE_RC"
df -k / | tail -1
echo "DONE_STAGE_DEPLOY"
