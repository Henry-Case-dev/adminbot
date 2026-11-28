#!/usr/bin/env bash
# Post-deploy verification for 2.58.275: journal traceback context + which
# bot_settings rows changed at restart + final health/unit state. Read-only.
set -u
APP=/var/www/admin_bot
cd "$APP" || exit 90
PY=python3
for cand in "$APP/venv/bin/python" "$APP/.venv/bin/python"; do
  [ -x "$cand" ] && { PY="$cand"; break; }
done
MARK=2026-11-28T14:29:06Z
echo "== JOURNAL TRACEBACK CONTEXT (since $MARK) =="
journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -n -i -B3 -A18 'Traceback' | head -80
echo "== JOURNAL TRACEBACK LINE COUNT =="
journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -ci 'Traceback' || true
echo "== SETTINGS ROWS CHANGED AT RESTART =="
$PY - <<'PYEOF'
import asyncio, os

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
    import asyncpg
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        rows = await conn.fetch(
            "SELECT key, value::text AS v, category, updated_at FROM bot_settings "
            "WHERE updated_at >= '2026-11-28 14:29:00+00' ORDER BY updated_at")
        print("CHANGED_ROWS=%d" % len(rows))
        for r in rows:
            v = r["v"] if r["v"] is None or len(r["v"]) <= 120 else r["v"][:120] + "..."
            print("CHANGED key=%s cat=%s upd=%s value=%r" % (r["key"], r["category"], r["updated_at"], v))
    finally:
        await conn.close()


asyncio.run(main())
PYEOF
echo "== PROMPTS SUMMARY =="
$PY - <<'PYEOF'
import asyncio, os

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
    import asyncpg
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        rows = await conn.fetch("SELECT key, value::text AS v, updated_at FROM bot_settings WHERE key LIKE 'prompts.%'")
        empty = [r["key"] for r in rows if not r["v"] or r["v"] in ("null", "")]
        print("PROMPTS_KEYS=%d EMPTY=%d" % (len(rows), len(empty)))
        print("PROMPTS_MAXUPD=%s" % max((str(r["updated_at"]) for r in rows), default="-"))
        if empty:
            print("EMPTY_KEYS=%s" % ",".join(empty[:10]))
    finally:
        await conn.close()


asyncio.run(main())
PYEOF
echo "== FINAL STATE =="
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot)"
echo "LOCAL_HEALTHZ=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz)"
echo "PUBLIC_HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "HEAD=$(git rev-parse HEAD) TREE=$(git rev-parse HEAD:) REF=$(git symbolic-ref -q HEAD) DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l)"
echo "DISK=$(df -h / | tail -1)"
echo "TMP=$(ls -d /tmp/wt_rb275* 2>/dev/null | wc -l)"
echo "== DONE =="
