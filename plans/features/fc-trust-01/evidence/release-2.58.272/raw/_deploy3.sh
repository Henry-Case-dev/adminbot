#!/usr/bin/env bash
# Release 2.58.272 post-deploy evidence run 3 (read-only, no mutations).
set -u
APP=/var/www/admin_bot
cd "$APP" || { echo "ABORT_NO_APP_DIR"; exit 90; }
PY=/var/www/admin_bot/venv/bin/python

echo "== GIT STATE =="
echo "HEAD=$(git rev-parse HEAD)"
echo "REF=$(git symbolic-ref -q HEAD || echo detached)"
echo "DIRTY_TRACKED=$(git status --porcelain --untracked-files=no | wc -l)"
echo "WORKTREES=$(git worktree list | wc -l)"
git worktree list
echo "UNTRACKED_TOP=$(git status --porcelain --untracked-files=all | grep '^??' | head -10 | tr '\n' ' ')"

echo "== FACTORY LITERAL (walk, BOM-safe) =="
"$PY" - <<'PYEOF'
import ast
from pathlib import Path
src = Path("/var/www/admin_bot/config/settings.py").read_text(encoding="utf-8-sig")
tree = ast.parse(src)
factory = None
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "FACTCHECK_PIPELINE_V2_ENABLED":
        consts = [a.value for a in node.value.args if isinstance(a, ast.Constant)]
        factory = consts[-1] if consts else None
print("FACTORY_LITERAL=%s" % factory)
PYEOF

echo "== SETTINGS MD5 VARIANTS (find the recorded method) =="
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
        rows = await conn.fetch("SELECT key, value::text AS v, category FROM bot_settings ORDER BY key")
        pairs = [(r["key"], r["v"], r["category"]) for r in rows]
        variants = {
            "kv_nl": "\n".join(f"{k}={v}" for k, v, c in pairs),
            "kv_tab_nl": "\n".join(f"{k}\t{v}" for k, v, c in pairs),
            "kv_nl_trailing": "\n".join(f"{k}={v}" for k, v, c in pairs) + "\n",
            "kcv_tab_nl": "\n".join(f"{k}\t{c}\t{v}" for k, v, c in pairs),
            "kv_nl_nospace": "\n".join(f"{k}={v}" for k, v, c in pairs if v not in ("null", "")),
            "value_only_nl": "\n".join(v for k, v, c in pairs),
        }
        print("ROWS=%d" % len(pairs))
        for name, s in variants.items():
            print("MD5_%s=%s" % (name, hashlib.md5(s.encode()).hexdigest()))
        print("SAMPLE_HEAD=%r" % ("\n".join(f"{k}={v}" for k, v, c in pairs[:3])))
    finally:
        await conn.close()


asyncio.run(main())
PYEOF

echo "== NO ORPHAN PROCESSES / TEMP ARTIFACTS =="
echo "PYTEST_PROCS=$(pgrep -fc 'pytest' || true)"
echo "TMP_WT=$(ls -d /tmp/wt_rb272* 2>/dev/null | wc -l)"
echo "TMP_FILES_MINE=$(ls /tmp/h.json /tmp/j*.txt /tmp/a*.js /tmp/pubapp.js 2>/dev/null | wc -l)"
echo "PPID1_PYTEST=$(ps -eo ppid,pid,cmd | awk '$1==1 && /pytest|rollback/ {c++} END{print c+0}')"

echo "== FINAL HEALTH =="
echo "HEALTHZ_LOCAL=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz)"
echo "HEALTHZ_PUBLIC=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot)"
echo "== DONE3 =="
