#!/usr/bin/env bash
# Release 2.58.274 deploy run (single SSH session, ONE connection).
# Mutations only: git fetch/checkout of the exact expected SHA, .deploy/release.json
# (tools/release_manifest.py), chown/chmod, systemctl restart, disk cleanup --apply,
# temporary rollback worktree (removed). Everything else is read-only.
set -u
APP=/var/www/admin_bot
EXPECT_SHA=731a7e51cdb747fb3c0507ec80b885e4217766b0
EXPECT_TREE=16d79f701767a932bf942c1b49a21650915559bd
ROLLBACK_SHA=74ef57ef469220627207603ae133da308f37866f
BRANCH=release/2.58.274
EXPECT_ROUTES=5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf
EXPECT_APPJS=20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74
EXPECT_INDEX=b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907
EXPECT_FACTCHECK=6046df0c2f777446a0d4016608de2c4f19a69cfc04976629fa1f76793ee92a5b
EXPECT_PTHROTTLE=0a4d0ee071114696dee1ed7ce3f904896b04c046a9fdfa965dd9680d885c6cf2
EXPECT_STHROTTLE=9021fe9ee546f5ccedbdf8f89fe23b69c7a75912d4afcd400bbb22a5c465dc03
EXPECT_TESTS4=fd9671393a022e4f0a29c6074d315cc0c16209b631b994ec7d22c5e6724dcab7
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
PY=python3
for cand in "$APP/venv/bin/python" "$APP/.venv/bin/python"; do
  [ -x "$cand" ] && { PY="$cand"; break; }
done
echo "PY=$PY"
echo "PY_VERSION=$($PY -V 2>&1)"

echo "== PRE =="
echo "PRE_HEAD=$(git rev-parse HEAD)"
echo "PRE_REF=$(git symbolic-ref -q HEAD || echo detached)"
echo "PRE_TREE=$(git rev-parse HEAD:)"
echo "PRE_MANIFEST=$(tr -d '\n' < .deploy/release.json 2>/dev/null)"
DIRTY=$(git status --porcelain --untracked-files=no | wc -l)
echo "PRE_DIRTY_TRACKED=$DIRTY"
echo "PRE_UNTRACKED=$(git status --porcelain --untracked-files=all | grep -c '^??' || true)"
echo "PRE_UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot)"
echo "PRE_VER=$($PY -c 'import config.settings as s; print(s.APP_VERSION)' 2>&1 | tail -1)"
echo "PRE_DISK=$(df -h / | tail -1) PRE_AVAIL_KB=$(df -k --output=avail / | tail -1 | tr -d ' ')"
if [ "$DIRTY" != "0" ]; then
  echo "ABORT_DIRTY_TRACKED"
  git status --porcelain --untracked-files=no | head -20
  exit 11
fi

echo "== PRE DB/STATE FINGERPRINT =="
$PY - <<'PYEOF'
import asyncio, hashlib, os, sqlite3

APP = "/var/www/admin_bot"


def load_env():
    try:
        for line in open(APP + "/.env", encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


async def main():
    load_env()
    dsn = os.environ.get("POSTGRES_DSN", "")
    if not dsn:
        print("PG=NO_DSN")
        return
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            rows = await conn.fetch("SELECT key, value::text AS v, category, updated_at FROM bot_settings")
        finally:
            await conn.close()
        kv = sorted((r["key"], r["v"], r["category"], str(r["updated_at"])) for r in rows)
        body = "\n".join(f"{k}={v}" for k, v, c, u in kv)
        print("SETTINGS_ROWS=%d" % len(kv))
        print("SETTINGS_MD5_KV=%s" % hashlib.md5(body.encode()).hexdigest())
        print("SETTINGS_MAXUPD=%s" % max((u for _, _, _, u in kv), default="-"))
        print("PROMPTS_KEYS=%d" % sum(1 for k, _, _, _ in kv if k.startswith("prompts.")))
        print("PROMPT_KEYS_EMPTY=%d" % sum(1 for k, v, _, _ in kv if k.startswith("prompts.") and (not v or v in ("null", ""))))
        hot = [r for r in kv if r[0] == "flags.factcheck_pipeline_v2"]
        print("HOT_FLAG=%s" % (("present:" + hot[0][1]) if hot else "absent"))
    except Exception as exc:
        print("PG_ERROR=%s" % type(exc).__name__)


asyncio.run(main())

try:
    con = sqlite3.connect("file:%s/local_database.db?mode=ro" % APP, uri=True)
    print("SQLITE_USER_VERSION=%s" % con.execute("PRAGMA user_version").fetchone()[0])
    con.close()
except Exception as exc:
    print("SQLITE_ERROR=%s" % type(exc).__name__)
PYEOF

echo "== FETCH / CHECKOUT =="
git fetch --prune origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" >/dev/null 2>&1
GOT=$(git rev-parse "origin/$BRANCH")
echo "REMOTE_SHA=$GOT"
if [ "$GOT" != "$EXPECT_SHA" ]; then
  echo "ABORT_SHA_MISMATCH expected=$EXPECT_SHA"
  exit 12
fi
git checkout -B "$BRANCH" "$EXPECT_SHA" >/dev/null 2>&1 || { echo "ABORT_CHECKOUT"; exit 13; }
echo "NEW_HEAD=$(git rev-parse HEAD)"
echo "NEW_REF=$(git symbolic-ref -q HEAD || echo detached)"
echo "NEW_TREE=$(git rev-parse HEAD:)"
echo "POST_CHECKOUT_DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l)"
if [ "$(git rev-parse HEAD)" != "$EXPECT_SHA" ]; then echo "ABORT_HEAD_MISMATCH"; exit 19; fi
if [ "$(git rev-parse HEAD:)" != "$EXPECT_TREE" ]; then echo "ABORT_TREE_MISMATCH"; exit 19; fi
echo "== PRODUCT FILE SHA256 AFTER CHECKOUT =="
sha256sum handlers/factcheck.py services/persistent_throttling.py services/smartmodule_throttling.py tests/test_fc_trust_s4_reliability.py web/api/routes.py web/app.js web/index.html config/settings.py
F_SHA=$(sha256sum handlers/factcheck.py | cut -d' ' -f1)
P_SHA=$(sha256sum services/persistent_throttling.py | cut -d' ' -f1)
S_SHA=$(sha256sum services/smartmodule_throttling.py | cut -d' ' -f1)
T_SHA=$(sha256sum tests/test_fc_trust_s4_reliability.py | cut -d' ' -f1)
R_SHA=$(sha256sum web/api/routes.py | cut -d' ' -f1)
A_SHA=$(sha256sum web/app.js | cut -d' ' -f1)
I_SHA=$(sha256sum web/index.html | cut -d' ' -f1)
echo "FACTCHECK_MATCH=$([ "$F_SHA" = "$EXPECT_FACTCHECK" ] && echo yes || echo NO)"
echo "PTHROTTLE_MATCH=$([ "$P_SHA" = "$EXPECT_PTHROTTLE" ] && echo yes || echo NO)"
echo "STHROTTLE_MATCH=$([ "$S_SHA" = "$EXPECT_STHROTTLE" ] && echo yes || echo NO)"
echo "TEST_S4_MATCH=$([ "$T_SHA" = "$EXPECT_TESTS4" ] && echo yes || echo NO)"
echo "ROUTES_MATCH=$([ "$R_SHA" = "$EXPECT_ROUTES" ] && echo yes || echo NO)"
echo "APPJS_MATCH=$([ "$A_SHA" = "$EXPECT_APPJS" ] && echo yes || echo NO)"
echo "INDEX_MATCH=$([ "$I_SHA" = "$EXPECT_INDEX" ] && echo yes || echo NO)"
$PY tools/release_manifest.py || { echo "ABORT_MANIFEST"; exit 14; }
echo "MANIFEST=$(tr -d '\n' < .deploy/release.json)"
chown -R adminbot:adminbot "$APP"
chmod 644 config/settings.py web/api/routes.py web/app.js web/index.html

echo "== RESTART =="
MARK=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "RESTART_MARK=$MARK"
systemctl restart admin_bot || { echo "ABORT_RESTART"; exit 15; }
CODE=000
for i in $(seq 1 45); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/healthz || echo 000)
  [ "$CODE" = "200" ] && break
  sleep 2
done
echo "LOCAL_HEALTHZ_HTTP=$CODE"
echo "LOCAL_HEALTHZ=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz)"
echo "PUBLIC_HEALTHZ_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "PUBLIC_HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot) BOTPROCS=$(pgrep -fc 'python.*bot.py' || true) SINCE=$(systemctl show -p ActiveEnterTimestamp --value admin_bot)"

echo "== VERSION (three sources) =="
$PY - <<'PYEOF'
import ast
from pathlib import Path
src = Path("/var/www/admin_bot/config/settings.py").read_text(encoding="utf-8-sig")
val = None
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "APP_VERSION":
        val = node.value.value
print("VER_AST=%s" % val)
PYEOF
echo "VER_IMPORT=$($PY -c 'import config.settings as s; print(s.APP_VERSION)' 2>&1 | tail -1)"
echo "VER_MANIFEST=$($PY -c 'import json;print(json.load(open("/var/www/admin_bot/.deploy/release.json"))["version"])' 2>&1 | tail -1)"

echo "== POST DB/STATE FINGERPRINT =="
$PY - <<'PYEOF'
import asyncio, hashlib, os, sqlite3

APP = "/var/www/admin_bot"


def load_env():
    try:
        for line in open(APP + "/.env", encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


async def main():
    load_env()
    dsn = os.environ.get("POSTGRES_DSN", "")
    if not dsn:
        print("PG=NO_DSN")
        return
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            rows = await conn.fetch("SELECT key, value::text AS v, category, updated_at FROM bot_settings")
        finally:
            await conn.close()
        kv = sorted((r["key"], r["v"], r["category"], str(r["updated_at"])) for r in rows)
        body = "\n".join(f"{k}={v}" for k, v, c, u in kv)
        print("SETTINGS_ROWS=%d" % len(kv))
        print("SETTINGS_MD5_KV=%s" % hashlib.md5(body.encode()).hexdigest())
        print("SETTINGS_MAXUPD=%s" % max((u for _, _, _, u in kv), default="-"))
        print("PROMPTS_KEYS=%d" % sum(1 for k, _, _, _ in kv if k.startswith("prompts.")))
        print("PROMPT_KEYS_EMPTY=%d" % sum(1 for k, v, _, _ in kv if k.startswith("prompts.") and (not v or v in ("null", ""))))
        hot = [r for r in kv if r[0] == "flags.factcheck_pipeline_v2"]
        print("HOT_FLAG=%s" % (("present:" + hot[0][1]) if hot else "absent"))
    except Exception as exc:
        print("PG_ERROR=%s" % type(exc).__name__)


asyncio.run(main())

try:
    con = sqlite3.connect("file:%s/local_database.db?mode=ro" % APP, uri=True)
    print("SQLITE_USER_VERSION=%s" % con.execute("PRAGMA user_version").fetchone()[0])
    con.close()
except Exception as exc:
    print("SQLITE_ERROR=%s" % type(exc).__name__)
PYEOF

echo "== QUICK_CHECK =="
timeout 900 $PY - <<'PYEOF'
import sqlite3, time
t0 = time.time()
con = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro", uri=True)
print("QUICK_CHECK=%s elapsed=%.1fs" % (con.execute("PRAGMA quick_check").fetchone()[0], time.time() - t0))
print("USER_VERSION_AFTER=%s" % con.execute("PRAGMA user_version").fetchone()[0])
con.close()
PYEOF

echo "== JOURNAL (first window, 5s after restart) =="
sleep 5
J=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null)
echo "JOURNAL_LINES=$(printf '%s\n' "$J" | wc -l)"
echo "J_TRACEBACK=$(printf '%s\n' "$J" | grep -ci 'traceback' || true)"
echo "J_SQL_ERR=$(printf '%s\n' "$J" | grep -ciE 'sqlite3\.(Operational|Integrity|Database)Error|asyncpg\.|sqlalchemy\.exc|ProgrammingError' || true)"
echo "J_CRITICAL=$(printf '%s\n' "$J" | grep -c 'CRITICAL' || true)"
echo "J_402_403=$(printf '%s\n' "$J" | grep -cE '\b(402|403)\b' || true)"
echo "J_STARTED=$(printf '%s\n' "$J" | grep -c 'Uvicorn running\|Started server\|Application startup complete' || true)"
echo "J_ERROR_SAMPLE=$(printf '%s\n' "$J" | grep -iE 'error|exception' | head -5 | tr '\n' '|')"
NR1=$(systemctl show -p NRestarts --value admin_bot)
echo "NRESTS_T0=$NR1"

echo "== DISK =="
df -h / | tail -1
$PY manage.py disk audit 2>&1 | tail -12
$PY manage.py disk cleanup --apply 2>&1 | tail -6
df -h / | tail -1

echo "== ROLLBACK DRY-RUN ($ROLLBACK_SHA) =="
RB=/tmp/wt_rb274_$$
git worktree add --detach "$RB" "$ROLLBACK_SHA" >/dev/null 2>&1 || { echo "RB_WORKTREE_FAIL"; exit 16; }
cd "$RB" || exit 17
RBVER=$($PY - <<'PYEOF'
import ast
from pathlib import Path
src = Path("config/settings.py").read_text(encoding="utf-8")
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "APP_VERSION":
        print(node.value.value)
PYEOF
)
echo "RB_VERSION=$RBVER"
RB_OUT=$(timeout 120 $PY tools/release_manifest.py --dry-run --effect rollback 2>&1)
RB_RC=$?
echo "$RB_OUT" | tr -d '\n'; echo
echo "RB_RC=$RB_RC"
cd "$APP" || exit 18
git worktree remove "$RB" >/dev/null 2>&1 || echo "RB_REMOVE_FAILED"
git worktree prune
echo "RB_WORKTREE_LEFT=$(git worktree list | grep -c wt_rb274 || true)"

echo "== SETTLE WINDOW (6 min, no restart storm) =="
sleep 360
echo "SETTLE_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "SETTLE_UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot) BOTPROCS=$(pgrep -fc 'python.*bot.py' || true)"
echo "SETTLE_LOCAL_HEALTHZ_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/healthz)"
echo "SETTLE_LOCAL_HEALTHZ=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz)"
echo "SETTLE_PUBLIC_HEALTHZ_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "SETTLE_PUBLIC_HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
J2=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null)
echo "J2_LINES=$(printf '%s\n' "$J2" | wc -l)"
echo "J2_TRACEBACK=$(printf '%s\n' "$J2" | grep -ci 'traceback' || true)"
echo "J2_SQL_ERR=$(printf '%s\n' "$J2" | grep -ciE 'sqlite3\.(Operational|Integrity|Database)Error|asyncpg\.|sqlalchemy\.exc|ProgrammingError' || true)"
echo "J2_CRITICAL=$(printf '%s\n' "$J2" | grep -c 'CRITICAL' || true)"
echo "J2_402_403=$(printf '%s\n' "$J2" | grep -cE '\b(402|403)\b' || true)"
echo "J2_ERROR_SAMPLE=$(printf '%s\n' "$J2" | grep -iE 'error|exception' | head -8 | tr '\n' '|')"
echo "J2_THROTTLE=$(printf '%s\n' "$J2" | grep -ciE 'throttl|cooldown' || true)"
echo "FINAL_DISK=$(df -h / | tail -1)"

echo "== FINAL GIT =="
echo "HEAD=$(git rev-parse HEAD) REF=$(git symbolic-ref -q HEAD || echo detached) TREE=$(git rev-parse HEAD:) DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l) WORKTREES=$(git worktree list | wc -l)"
echo "TMP_LEFTOVERS=$(ls -d /tmp/wt_rb274* /tmp/_rel274* 2>/dev/null | wc -l)"
echo "== DONE =="
