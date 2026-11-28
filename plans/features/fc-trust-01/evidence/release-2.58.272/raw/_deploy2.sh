#!/usr/bin/env bash
# Release 2.58.272 post-deploy evidence run 2 (single SSH session).
# Read-only, except: `manage.py disk cleanup --apply` (deploy pool keep=2).
set -u
APP=/var/www/admin_bot
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
MARK=2026-11-28T08:14:35Z

PY=$(systemctl show -p ExecStart --value admin_bot | sed -E 's/.*path=([^ ;]*python[^ ;]*).*/\1/')
echo "PY=$PY"
[ -x "$PY" ] || { echo "ABORT_NO_PY"; exit 91; }
echo "PY_VERSION=$("$PY" -V 2>&1)"

echo "== VERSION (three sources, BOM-safe AST) =="
"$PY" - <<'PYEOF'
import ast
from pathlib import Path
src = Path("/var/www/admin_bot/config/settings.py").read_text(encoding="utf-8-sig")
tree = ast.parse(src)
val = None
factory = None
for node in tree.body:
    tgt = getattr(node, "target", None)
    if isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "APP_VERSION" in names:
            val = node.value.value
    if isinstance(node, ast.AnnAssign) and getattr(tgt, "id", "") == "FACTCHECK_PIPELINE_V2_ENABLED":
        call = node.value
        consts = [a.value for a in call.args if isinstance(a, ast.Constant)]
        factory = consts[-1] if consts else None
print("VER_AST=%s" % val)
print("FACTORY_LITERAL=%s" % factory)
PYEOF
echo "VER_IMPORT=$("$PY" -c 'import config.settings as s; print(s.APP_VERSION)' 2>&1 | tail -1)"
echo "VER_MANIFEST=$("$PY" -c 'import json;print(json.load(open("/var/www/admin_bot/.deploy/release.json"))["version"])' 2>&1 | tail -1)"
echo "FRESH_EFFECTIVE=$("$PY" -c 'import services.factcheck_orchestrator as o; print(o.pipeline_v2_enabled())' 2>&1 | tail -1)"

echo "== ENV SURFACE =="
echo "ENV_UNIT_ROWS=$(systemctl show admin_bot -p Environment --value | tr ' ' '\n' | grep -c '^FACTCHECK_PIPELINE_V2_ENABLED=' || true)"
echo "ENV_UNIT_VALUE=$(systemctl show admin_bot -p Environment --value | tr ' ' '\n' | grep '^FACTCHECK_PIPELINE_V2_ENABLED=' | cut -d= -f2)"
echo "ENV_FILE_ROWS=$(grep -c '^FACTCHECK_PIPELINE_V2_ENABLED=' .env 2>/dev/null || true)"

echo "== PG SETTINGS FINGERPRINT / HOT FLAG =="
"$PY" - <<'PYEOF'
import asyncio, hashlib, json, os


def load_env():
    for line in open("/var/www/admin_bot/.env", encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def flat(v):
    if isinstance(v, dict):
        for k in ("value", "v", "text", "string"):
            if k in v:
                return flat(v[k])
        return json.dumps(v, sort_keys=True, default=str)
    return v


async def main():
    load_env()
    dsn = os.environ.get("POSTGRES_DSN", "")
    if not dsn:
        print("PG=NO_DSN")
        return
    import asyncpg
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        rows = await conn.fetch("SELECT key, value, category, updated_at FROM bot_settings")
        kv = sorted((r["key"], flat(r["value"]), r["category"], str(r["updated_at"])) for r in rows)
        print("SETTINGS_ROWS=%d" % len(kv))
        print("SETTINGS_MD5_KV=%s" % hashlib.md5("\n".join(f"{k}={v}" for k, v, c, u in kv).encode()).hexdigest())
        print("SETTINGS_MD5_KCV=%s" % hashlib.md5("\n".join(f"{k}\t{c}\t{v}" for k, v, c, u in kv).encode()).hexdigest())
        print("SETTINGS_MAXUPD=%s" % max((u for _, _, _, u in kv), default="-"))
        print("PROMPTS_KEYS=%d" % len([1 for k, _, _, _ in kv if k.startswith("prompts.")]))
        hot = [r for r in rows if r["key"] == "flags.factcheck_pipeline_v2"]
        if not hot:
            print("HOT_FLAG=absent")
        else:
            print("HOT_FLAG=present value=%r category=%r updated_at=%s"
                  % (flat(hot[0]["value"]), hot[0]["category"], hot[0]["updated_at"]))
    finally:
        await conn.close()


asyncio.run(main())
PYEOF

echo "== JOURNAL SINCE $MARK =="
echo "NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
J=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null)
echo "JOURNAL_LINES=$(printf '%s' "$J" | wc -l)"
echo "JOURNAL_TRACEBACK=$(printf '%s' "$J" | grep -c 'Traceback' || true)"
echo "JOURNAL_ERROR_LEVEL=$(printf '%s' "$J" | grep -cE ' (ERROR|CRITICAL) ' || true)"
echo "JOURNAL_SQL_ERRORS=$(printf '%s' "$J" | grep -ciE 'OperationalError|database is locked|sqlite3\.[A-Za-z]*Error|asyncpg\.|psycopg' || true)"
echo "JOURNAL_HTTP_5XX=$(printf '%s' "$J" | grep -cE 'HTTP/1.1\" 5[0-9][0-9]| 500 Internal' || true)"
echo "--- error-level sample (masked) ---"
printf '%s' "$J" | grep -E ' (ERROR|CRITICAL) ' | tail -6 | cut -c1-220
echo "--- last 5 lines ---"
printf '%s' "$J" | tail -5 | cut -c1-220

echo "== UNIT =="
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot) SINCE=$(systemctl show -p ActiveEnterTimestamp --value admin_bot)"
echo "BOTPROCS=$(pgrep -fc 'python.*bot.py' || true)"

echo "== DISK =="
df -h / | tail -1
"$PY" manage.py disk audit 2>&1 | tail -14
"$PY" manage.py disk cleanup --apply 2>&1 | tail -8
df -h / | tail -1

echo "== SMOKE (public) =="
echo "HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "AGG_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://admin-bot.duckdns.org/api/factcheck/temporal/aggregate)"
echo "APPJS_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://admin-bot.duckdns.org/web/app.js)"
echo "APPJS_REMOTE_BYTES=$(curl -s --max-time 15 https://admin-bot.duckdns.org/web/app.js | wc -c)"
echo "== DONE2 =="
