#!/usr/bin/env bash
# Release 2.58.272 final verification: temp-artifact audit, md5 variant probing,
# final state. Removes ONLY the exact documented 2.58.271-era scratch names if present.
set -u
APP=/var/www/admin_bot
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
PY=/var/www/admin_bot/venv/bin/python

echo "== /tmp AUDIT =="
ls -l --time-style=long-iso /tmp/h.json /tmp/j*.txt /tmp/a*.js /tmp/appjs*.js /tmp/pubapp.js 2>/dev/null
echo "TMP_AUDIT_COUNT=$(ls /tmp/h.json /tmp/j*.txt /tmp/a*.js /tmp/appjs*.js /tmp/pubapp.js 2>/dev/null | wc -l)"
echo "TMP_DIRS=$(ls -d /tmp/wt_* /tmp/rollback* 2>/dev/null | wc -l)"

echo "== REMOVE ONLY DOCUMENTED 2.58.271 SCRATCH =="
for f in /tmp/appjs271.js /tmp/a271.js /tmp/pubapp.js /tmp/j*.txt /tmp/h.json; do
  if [ -f "$f" ]; then
    echo "REMOVING $f size=$(stat -c %s "$f") mtime=$(stat -c %y "$f")"
    rm -f "$f"
  fi
done
echo "TMP_AFTER=$(ls /tmp/h.json /tmp/j*.txt /tmp/a*.js /tmp/appjs*.js /tmp/pubapp.js 2>/dev/null | wc -l)"
ls -l --time-style=long-iso /tmp/h.json /tmp/j*.txt /tmp/a*.js /tmp/appjs*.js /tmp/pubapp.js 2>/dev/null

echo "== SETTINGS MD5 PROBES =="
"$PY" - <<'PYEOF'
import asyncio, hashlib, json, os


def load_env():
    for line in open("/var/www/admin_bot/.env", encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def main():
    load_env()
    import asyncpg
    conn = await asyncpg.connect(os.environ["POSTGRES_DSN"], timeout=10)
    try:
        rows = await conn.fetch("SELECT key, value::text AS v FROM bot_settings ORDER BY key")
        scalars = [(r["key"], r["v"]) for r in rows if len(r["v"]) < 120]
        print("ROWS=%d SCALARISH=%d" % (len(rows), len(scalars)))
        probes = {
            "all_kv_sorted_value": "\n".join(sorted(f"{k}={v}" for k, v in scalars)),
            "all_kv_file_order": "\n".join(f"{k}={v}" for k, v in scalars),
            "json_compact": json.dumps({k: v for k, v in scalars}, sort_keys=True, separators=(",", ":")),
            "json_default": json.dumps({k: v for k, v in scalars}, sort_keys=True),
        }
        for name, s in probes.items():
            print("MD5_%s=%s len=%d" % (name, hashlib.md5(s.encode()).hexdigest(), len(s)))
        print("TARGET=50887d362fe93bf7646beae77cce32c6 (2.58.264/2.58.271 recorded)")
    finally:
        await conn.close()


asyncio.run(main())
PYEOF

echo "== FINAL STATE =="
echo "HEAD=$(git rev-parse HEAD)"
echo "DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l)"
echo "WORKTREES=$(git worktree list | wc -l)"
echo "MANIFEST=$(tr -d '\n' < .deploy/release.json)"
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot)"
echo "HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "DF=$(df -h / | tail -1)"
echo "== DONE4 =="
