#!/usr/bin/env bash
# Release 2.58.274 post-deploy read-only verification (single short SSH session, no mutations).
set -u
APP=/var/www/admin_bot
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
PY=python3
for cand in "$APP/venv/bin/python" "$APP/.venv/bin/python"; do
  [ -x "$cand" ] && { PY="$cand"; break; }
done

echo "== ROLLBACK TARGET VERSION =="
git show 74ef57ef469220627207603ae133da308f37866f:config/settings.py > /tmp/_rb274_settings.py
$PY - <<'PYEOF'
import ast
from pathlib import Path
src = Path("/tmp/_rb274_settings.py").read_text(encoding="utf-8-sig")
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "APP_VERSION":
        print("RB_VERSION_AST=%s" % node.value.value)
PYEOF
rm -f /tmp/_rb274_settings.py
echo "RB_BLOB=$(git rev-parse 74ef57ef469220627207603ae133da308f37866f:config/settings.py)"

echo "== ANTICLICHE WIKIPEDIA ERROR: PRE-EXISTING ON 2.58.273? =="
echo "PRE_PERIOD_ERROR_COUNT=$(journalctl -u admin_bot --until '2026-11-28 10:41:00' --no-pager 2>/dev/null | grep -c 'refresh | status=fetch_error' || true)"
echo "PRE_PERIOD_LAST=$(journalctl -u admin_bot --until '2026-11-28 10:41:00' --no-pager 2>/dev/null | grep 'refresh | status=fetch_error' | tail -1 | cut -c1-160)"
echo "POST_PERIOD_ERROR_COUNT=$(journalctl -u admin_bot --since '2026-11-28 10:41:13' --no-pager 2>/dev/null | grep -c 'refresh | status=fetch_error' || true)"

echo "== THROTTLE / COOLDOWN STATE (read-only) =="
$PY - <<'PYEOF'
import sqlite3
con = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro", uri=True)
names = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%throttl%' OR name LIKE '%cooldown%')").fetchall()]
print("THROTTLE_TABLES=%s" % (names or "none"))
for n in names:
    try:
        cnt = con.execute('SELECT COUNT(*) FROM "%s"' % n).fetchone()[0]
        cols = [c[1] for c in con.execute('PRAGMA table_info("%s")' % n).fetchall()]
        print("TABLE %s rows=%d cols=%s" % (n, cnt, cols))
    except Exception as exc:
        print("TABLE %s error=%s" % (n, type(exc).__name__))
print("USER_VERSION=%s" % con.execute("PRAGMA user_version").fetchone()[0])
print("INTEGRITY_QUICK=%s" % con.execute("PRAGMA quick_check").fetchone()[0])
con.close()
PYEOF

echo "== MANIFEST ON DISK =="
echo "MANIFEST=$(tr -d '\n' < .deploy/release.json)"
echo "GIT=$(git rev-parse HEAD) $(git symbolic-ref -q HEAD) TREE=$(git rev-parse HEAD:) DIRTY=$(git status --porcelain --untracked-files=no | wc -l)"
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot)"
echo "HEALTHZ_LOCAL=$(curl -s --max-time 3 http://127.0.0.1:8000/healthz)"
echo "HEALTHZ_PUBLIC=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "DISK=$(df -h / | tail -1)"
echo "TMP_LEFTOVERS=$(ls -d /tmp/wt_rb274* /tmp/_rel274* /tmp/_rb274* 2>/dev/null | wc -l)"
echo "== DONE =="
