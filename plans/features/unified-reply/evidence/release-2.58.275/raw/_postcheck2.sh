#!/usr/bin/env bash
# Final 2.58.275 verification: stored L1 canon == code canon (R4),
# truncated_reasoning baseline frequency, changed-module journal lines. Read-only.
set -u
APP=/var/www/admin_bot
cd "$APP" || exit 90
PY=python3
for cand in "$APP/venv/bin/python" "$APP/.venv/bin/python"; do
  [ -x "$cand" ] && { PY="$cand"; break; }
done
MARK=2026-11-28T14:29:06Z

echo "== STORED CANON vs CODE CANON =="
$PY - <<'PYEOF'
import asyncio, hashlib, os, sys
APP = "/var/www/admin_bot"
sys.path.insert(0, APP)


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
    from services import chat_prompts as cp
    code_canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    dsn = os.environ.get("POSTGRES_DSN", "")
    import asyncpg
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        row = await conn.fetchrow(
            "SELECT value::text AS v, updated_at FROM bot_settings WHERE key = 'prompts.direct_l1_planner_system_prompt'")
    finally:
        await conn.close()
    db_canon = row["v"]
    if len(db_canon) >= 2 and db_canon.startswith('"') and db_canon.endswith('"'):
        db_canon = db_canon[1:-1]
    db_canon = db_canon.replace("\\n", "\n").replace('\\"', '"')
    print("DB_SHA12=%s LEN=%d" % (hashlib.sha256(db_canon.encode()).hexdigest()[:12], len(db_canon)))
    print("CODE_SHA12=%s LEN=%d" % (hashlib.sha256(code_canon.encode()).hexdigest()[:12], len(code_canon)))
    print("DB_EQUALS_CODE=%s" % (db_canon.strip() == code_canon.strip()))
    print("DB_HAS_R4_PHRASE=%s" % ("окно или сообщение текущего хода" in db_canon))
    print("DB_HAS_R3_INITIATIVE_NARROWING=%s" % ("этот вызов относится к инициативе" in db_canon))
    print("DB_UPDATED_AT=%s" % row["updated_at"])


asyncio.run(main())
PYEOF

echo "== TRUNCATED_REASONING BASELINE (journal before deploy) =="
echo "PRE_DEPLOY_COUNT_24H=$(journalctl -u admin_bot --since '2026-11-27 14:00:00' --until '2026-11-28 14:29:00' --no-pager 2>/dev/null | grep -c 'truncated_reasoning' || true)"
echo "POST_DEPLOY_COUNT=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -c 'truncated_reasoning' || true)"
echo "PRE_DEPLOY_INITIATIVE_EVAL_FAIL=$(journalctl -u admin_bot --since '2026-11-27 14:00:00' --until '2026-11-28 14:29:00' --no-pager 2>/dev/null | grep -c 'opportunity eval failed' || true)"
echo "POST_DEPLOY_INITIATIVE_EVAL_FAIL=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -c 'opportunity eval failed' || true)"

echo "== CHANGED-MODULE SIGNALS (since deploy) =="
echo "REPLY_BINDING_LOGS=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -c 'reply target unavailable' || true)"
echo "PROMPT_MIGRATION_LOGS=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -ci 'migration\|prompt_migrations' || true)"
echo "DIRECT_ERRORS=$(journalctl -u admin_bot --since "$MARK" --no-pager 2>/dev/null | grep -ciE '\[direct\].*(error|failed)' || true)"

echo "== FINAL =="
echo "UNIT=$(systemctl is-active admin_bot) NRESTS=$(systemctl show -p NRestarts --value admin_bot) MAINPID=$(systemctl show -p MainPID --value admin_bot)"
echo "LOCAL_HEALTHZ=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz)"
echo "PUBLIC_HEALTHZ=$(curl -s --max-time 10 https://admin-bot.duckdns.org/healthz)"
echo "== DONE =="
