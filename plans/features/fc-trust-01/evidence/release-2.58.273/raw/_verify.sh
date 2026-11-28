#!/usr/bin/env bash
# Release 2.58.273 post-deploy verification (read-only).
set -u
APP=/var/www/admin_bot
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
PY=/var/www/admin_bot/venv/bin/python
MARK=$(systemctl show -p ActiveEnterTimestamp --value admin_bot)
echo "ACTIVE_SINCE=$MARK"
echo "MANIFEST=$(tr -d '\n' < .deploy/release.json 2>/dev/null)"
echo "MANIFEST_EFFECT=$($PY -c 'import json;d=json.load(open("/var/www/admin_bot/.deploy/release.json"));print(d["effect"],d["version"],d["deployed_sha"][:9])' 2>&1 | tail -1)"
echo "HEAD=$(git rev-parse HEAD) REF=$(git symbolic-ref -q HEAD || echo detached) TREE=$(git rev-parse HEAD:) DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l) WORKTREES=$(git worktree list | wc -l)"
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot) BOTPROCS=$(pgrep -fc 'python.*bot.py' || true)"
echo "LOCAL_HEALTHZ_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/healthz)"
echo "LOCAL_HEALTHZ=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz)"
echo "PUBLIC_HEALTHZ_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "PUBLIC_HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "PUBLIC_APPJS_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://admin-bot.duckdns.org/web/app.js)"
echo "PUBLIC_APPJS_BYTES=$(curl -s --max-time 20 https://admin-bot.duckdns.org/web/app.js | wc -c)"
J=$(journalctl -u admin_bot --since "2 hours ago" --no-pager 2>/dev/null)
echo "JOURNAL_2H_LINES=$(printf '%s\n' "$J" | wc -l)"
echo "J_TRACEBACK=$(printf '%s\n' "$J" | grep -ci 'traceback' || true)"
echo "J_SQL_ERR=$(printf '%s\n' "$J" | grep -ciE 'sqlite3\.(Operational|Integrity|Database)Error|asyncpg\.|sqlalchemy\.exc|ProgrammingError' || true)"
echo "J_CRITICAL=$(printf '%s\n' "$J" | grep -c 'CRITICAL' || true)"
echo "J_402_403=$(printf '%s\n' "$J" | grep -cE '\b(402|403)\b' || true)"
echo "J_FACTCHECK_ERROR=$(printf '%s\n' "$J" | grep -ci 'factcheck.*error' || true)"
echo "DF=$(df -h / | tail -1)"
$PY manage.py disk audit 2>&1 | grep -E 'deploy_backup|db_backup|forecast|total' | head -8
$PY manage.py disk cleanup 2>&1 | tail -3
echo "TMP_LEFTOVERS=$(ls -d /tmp/wt_rb273* /tmp/wt_rb272* /tmp/_rel273* 2>/dev/null | wc -l)"
echo "PYTEST_PROCS=$(pgrep -fc pytest || true)"
echo "== DONE =="
