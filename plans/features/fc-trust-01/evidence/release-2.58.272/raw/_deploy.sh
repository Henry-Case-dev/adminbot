#!/usr/bin/env bash
# Release 2.58.272 deploy run (single SSH session, one connection).
# Reads only; the ONLY mutations are: git checkout of the exact expected SHA,
# .deploy/release.json write (tools/release_manifest.py), chown/chmod,
# systemctl restart, disk cleanup --apply, temporary rollback worktree (removed).
set -u
APP=/var/www/admin_bot
EXPECT_SHA=a2195fe3f9289d75461f27c7278d52779e2b812a
ROLLBACK_SHA=3a78484b92a6f3ba1273360e4a34de396dcf52f1
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
PY=python3
[ -x "$APP/.venv/bin/python" ] && PY="$APP/.venv/bin/python"
echo "PY=$PY"

echo "== PRE =="
echo "PRE_HEAD=$(git rev-parse HEAD)"
echo "PRE_REF=$(git symbolic-ref -q HEAD || echo detached)"
echo "PRE_MANIFEST=$(tr -d '\n' < .deploy/release.json 2>/dev/null)"
DIRTY=$(git status --porcelain --untracked-files=no | wc -l)
echo "PRE_DIRTY_TRACKED=$DIRTY"
echo "PRE_UNTRACKED=$(git status --porcelain --untracked-files=all | grep -c '^??' || true)"
echo "PRE_UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot)"
if [ "$DIRTY" != "0" ]; then
  echo "ABORT_DIRTY_TRACKED"
  git status --porcelain --untracked-files=no | head -20
  exit 11
fi

"$PY" - <<'PYEOF'
import hashlib, json, os, sqlite3

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


def flat(v):
    if isinstance(v, dict):
        for k in ("value", "v", "text", "string"):
            if k in v:
                return flat(v[k])
        return json.dumps(v, sort_keys=True, default=str)
    return v


load_env()
dsn = os.environ.get("POSTGRES_DSN", "")
if not dsn:
    print("PG=NO_DSN")
else:
    try:
        import asyncio, asyncpg

        async def main():
            conn = await asyncpg.connect(dsn, timeout=10)
            try:
                rows = await conn.fetch("SELECT key, value, category, updated_at FROM bot_settings")
                kv = sorted((r["key"], flat(r["value"]), r["category"], str(r["updated_at"]))
                            for r in rows)
                s1 = "\n".join(f"{k}={v}" for k, v, c, u in kv)
                s2 = "\n".join(f"{k}\t{c}\t{v}" for k, v, c, u in kv)
                print("SETTINGS_ROWS=%d" % len(kv))
                print("SETTINGS_MD5_KV=%s" % hashlib.md5(s1.encode()).hexdigest())
                print("SETTINGS_MD5_KCV=%s" % hashlib.md5(s2.encode()).hexdigest())
                print("SETTINGS_MAXUPD=%s" % max((u for _, _, _, u in kv), default="-"))
                prompts = [k for k, _, _, _ in kv if k.startswith("prompts.")]
                print("PROMPTS_KEYS=%d" % len(prompts))
                hot = [r for r in rows if r["key"] == "flags.factcheck_pipeline_v2"]
                if not hot:
                    print("HOT_FLAG=absent")
                else:
                    print("HOT_FLAG=present value=%r category=%r updated_at=%s"
                          % (flat(hot[0]["value"]), hot[0]["category"], hot[0]["updated_at"]))
            finally:
                await conn.close()

        asyncio.run(main())
    except Exception as exc:
        print("PG_ERROR=%s" % type(exc).__name__)

db = APP + "/local_database.db"
try:
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    print("SQLITE_USER_VERSION=%s" % con.execute("PRAGMA user_version").fetchone()[0])
    con.close()
except Exception as exc:
    print("SQLITE_ERROR=%s" % type(exc).__name__)
PYEOF

echo "== POST_CHECKOUT =="
git fetch --prune origin "+refs/heads/release/2.58.272:refs/remotes/origin/release/2.58.272" >/dev/null 2>&1
GOT=$(git rev-parse origin/release/2.58.272)
echo "REMOTE_SHA=$GOT"
if [ "$GOT" != "$EXPECT_SHA" ]; then
  echo "ABORT_SHA_MISMATCH expected=$EXPECT_SHA"
  exit 12
fi
git checkout --detach "$EXPECT_SHA" >/dev/null 2>&1 || { echo "ABORT_CHECKOUT"; exit 13; }
echo "NEW_HEAD=$(git rev-parse HEAD)"
echo "POST_CHECKOUT_DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l)"
"$PY" tools/release_manifest.py || { echo "ABORT_MANIFEST"; exit 14; }
echo "MANIFEST=$(tr -d '\n' < .deploy/release.json)"
chown -R adminbot:adminbot "$APP"
chmod 644 config/settings.py web/api/routes.py web/app.js web/index.html
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
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot) BOTPROCS=$(pgrep -fc 'python.*bot.py' || true)"

echo "== VERSION (three sources) =="
"$PY" - <<'PYEOF'
import ast
from pathlib import Path
src = Path("/var/www/admin_bot/config/settings.py").read_text(encoding="utf-8")
val = None
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "APP_VERSION":
        val = node.value.value
print("VER_AST=%s" % val)
PYEOF
echo "VER_IMPORT=$("$PY" -c 'import config.settings as s; print(s.APP_VERSION)')"
echo "VER_MANIFEST=$("$PY" -c 'import json;print(json.load(open("/var/www/admin_bot/.deploy/release.json"))["version"])')"

echo "== FILE IDENTITY =="
sha256sum web/api/routes.py web/app.js web/index.html config/settings.py services/factcheck_orchestrator.py services/factcheck_prompts.py
echo "APPJS_BYTES=$(stat -c %s web/app.js)"

echo "== EFFECTIVE FLAG v2 =="
echo "FACTORY_LITERAL=$("$PY" - <<'PYEOF'
import ast
from pathlib import Path
src = Path("/var/www/admin_bot/config/settings.py").read_text(encoding="utf-8")
tree = ast.parse(src)
found = None
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "FACTCHECK_PIPELINE_V2_ENABLED":
        call = node.value
        args = [a.value for a in call.args if isinstance(a, ast.Constant)]
        found = args[-1] if args else None
print(found)
PYEOF
)"
echo "ENV_UNIT=$(systemctl show admin_bot -p Environment --value | tr ' ' '\n' | grep -c '^FACTCHECK_PIPELINE_V2_ENABLED=')"
echo "ENV_UNIT_VALUE=$(systemctl show admin_bot -p Environment --value | tr ' ' '\n' | grep '^FACTCHECK_PIPELINE_V2_ENABLED=' | cut -d= -f2)"
echo "ENV_FILE=$(grep -c '^FACTCHECK_PIPELINE_V2_ENABLED=' .env 2>/dev/null || echo 0)"
echo "FRESH_EFFECTIVE=$("$PY" -c 'import services.factcheck_orchestrator as o; print(o.pipeline_v2_enabled())' 2>&1 | tail -1)"

echo "== AGGREGATE ENDPOINT (no initData) =="
BODY=$(curl -s --max-time 10 -w '\nHTTP_CODE=%{http_code}' https://admin-bot.duckdns.org/api/factcheck/temporal/aggregate)
echo "$BODY"
echo "BODY_HAS_TRACEBACK=$(echo "$BODY" | grep -c 'Traceback' || true)"
echo "BODY_HAS_SECRET_WORD=$(echo "$BODY" | grep -ci 'secret' || true)"
echo "BODY_HAS_PY_PATH=$(echo "$BODY" | grep -c '\.py' || true)"

echo "== DB QUICK_CHECK (bounded) =="
timeout 900 "$PY" - <<'PYEOF'
import sqlite3, time
t0 = time.time()
con = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro", uri=True)
print("QUICK_CHECK=%s elapsed=%.1fs" % (con.execute("PRAGMA quick_check").fetchone()[0], time.time() - t0))
print("USER_VERSION_AFTER=%s" % con.execute("PRAGMA user_version").fetchone()[0])
con.close()
PYEOF

echo "== DISK =="
df -h / | tail -1
"$PY" manage.py disk audit 2>&1 | tail -12
"$PY" manage.py disk cleanup --apply 2>&1 | tail -6

echo "== ROLLBACK DRY-RUN ($ROLLBACK_SHA) =="
RB=/tmp/wt_rb272_$$
git worktree add --detach "$RB" "$ROLLBACK_SHA" >/dev/null 2>&1 || { echo "RB_WORKTREE_FAIL"; exit 16; }
cd "$RB" || exit 17
RBVER=$("$PY" - <<'PYEOF'
import ast
from pathlib import Path
src = Path("config/settings.py").read_text(encoding="utf-8")
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "APP_VERSION":
        print(node.value.value)
PYEOF
)
echo "RB_VERSION=$RBVER"
RB_OUT=$(timeout 120 "$PY" tools/release_manifest.py --dry-run --effect rollback 2>&1)
RB_RC=$?
echo "$RB_OUT" | tr -d '\n'; echo
echo "RB_RC=$RB_RC"
cd "$APP" || exit 18
git worktree remove "$RB" >/dev/null 2>&1 || echo "RB_REMOVE_FAILED"
git worktree prune
echo "RB_WORKTREE_LEFT=$(git worktree list | grep -c wt_rb272 || true)"
echo "== DONE =="
