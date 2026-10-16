# -*- coding: utf-8 -*-
"""INC-SUMMARY-01: read-only prod forensics for the stuck Summary run.

Two SSH logins total (AGENTS.md fail2ban discipline):
  #1 recon (short) -> #2 main batched collection (one bash -s script).
Credentials from repo deploy_commands.txt; never printed (scrubbed).

Usage: py -3 probe.py recon | py -3 probe.py main
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
OUT = Path(r"C:\Code\Python\adminbot\plans\features\asap8-v6-3-live-correction\evidence\incident-summary-01")
APP = "/var/www/admin_bot"


def _pwd(pattern: str) -> str:
    m = re.search(rf"^{pattern}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{pattern}' not found")
    return m.group(1)


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    text = re.sub(r"(postgres(?:ql)?://[^:\s]+:)[^@\s]+@", r"\1***@", text)
    text = re.sub(r"(sk-[A-Za-z0-9_\-]{8})[A-Za-z0-9_\-]+", r"\1***", text)
    return text


def shq(s: str) -> str:
    """bash single-quote."""
    return "'" + s.replace("'", "'\\''") + "'"


def connect(pw: str) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, pw, timeout=20, banner_timeout=20,
              auth_timeout=20, allow_agent=False, look_for_keys=False)
    return c


RECON_CMD = (
    "echo HOST=$(hostname); "
    "echo DATE_LOCAL=$(date '+%Y-%m-%d %H:%M:%S %Z %z'); "
    "echo DATE_UTC=$(date -u '+%Y-%m-%d %H:%M:%S'); "
    "echo ACTIVE=$(systemctl is-active admin_bot); "
    "systemctl show admin_bot -p ExecMainStartTimestamp -p MainPID -p NRestarts --no-pager; "
    "curl -s --max-time 6 http://127.0.0.1:8000/healthz; echo; "
    "cd /var/www/admin_bot && echo HEAD=$(git rev-parse HEAD)"
)


def run_recon(pw: str, secrets: list[str]) -> int:
    c = connect(pw)
    try:
        _in, out, err = c.exec_command(RECON_CMD, timeout=30)
        data = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        (OUT / "recon.txt").write_text(text, encoding="utf-8")
        print(text)
    finally:
        c.close()
    return 0


MAIN_TEMPLATE = r"""
set +e
export LC_ALL=C
cd __APP__
PW=__PW__
sudoc() { echo "$PW" | sudo -S -p '' "$@"; }
echo "===== S0: identity ====="
echo "DATE_LOCAL=$(date '+%Y-%m-%d %H:%M:%S %Z %z')"
echo "DATE_UTC=$(date -u '+%Y-%m-%d %H:%M:%S')"
echo "HEAD=$(git rev-parse HEAD)"
echo "BRANCH=$(git rev-parse --abbrev-ref HEAD)"
git log -1 --format='COMMIT=%H %cI %s'
echo "DIRTY=$(git status --porcelain | wc -l)"
echo "HZ_LOCAL=$(curl -s --max-time 8 http://127.0.0.1:8000/healthz)"
echo "HZ_443=$(curl -s --max-time 8 --resolve admin-bot.duckdns.org:443:127.0.0.1 https://admin-bot.duckdns.org/healthz)"
echo "===== S1: service state ====="
systemctl show admin_bot -p ActiveState,SubState,MainPID,ExecMainPID,NRestarts,ExecMainStartTimestamp,ExecMainStatus,ActiveEnterTimestamp,InvocationID,TimeoutStopUSec --no-pager
sudoc systemctl status admin_bot --no-pager -n 3 | head -n 25
PID=$(systemctl show admin_bot -p MainPID --value)
echo "MAINPID=$PID"
ps -o pid,etime,stat,pcpu,pmem,rss,cmd -p "$PID" 2>/dev/null
echo "PROCSTAT=$(sudo cat /proc/$PID/status 2>/dev/null | grep -E 'Threads|VmRSS' | tr '\n' ' ')"
echo "FDCOUNT=$(sudo ls /proc/$PID/fd 2>/dev/null | wc -l)"
sudo ls -l /proc/$PID/fd 2>/dev/null | head -n 40
echo "===== S2: .env config keys (masked) ====="
grep -E '^(SUMMARY_|INFINITE_RETENTION|GRAPH_RAG|MCA_|EMBEDDING_|IMPORT_RETENTION|DB_PATH|DB_WAL|POSTGRES_DB|LOG_LEVEL)' .env 2>/dev/null | sed -E 's/(KEY|TOKEN|PASSWORD|SECRET)=.*/\1=***/; s/(DSN)=.*/\1=***/' | head -n 80
echo "===== S3: db files ====="
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
[ -z "$DBP" ] && DBP=local_database.db
export DBP
echo "DB_PATH=$DBP"
ls -la "$DBP" "$DBP-wal" "$DBP-shm" 2>/dev/null
stat -c '%n size=%s mtime=%y' "$DBP" "$DBP-wal" "$DBP-shm" 2>/dev/null
echo "===== S4: journal full window 12:30->now ====="
SINCE=$(date -d '2026-10-16 12:30:00 UTC' '+%Y-%m-%d %H:%M:%S')
JCOUNT=$(sudoc journalctl -u admin_bot --since "$SINCE" --no-pager | wc -l)
echo "JOURNAL_COUNT_1230_NOW=$JCOUNT"
if [ "$JCOUNT" -le 16000 ]; then
  sudoc journalctl -u admin_bot --since "$SINCE" --no-pager | head -n 18000
else
  echo "JOURNAL_LARGE: dumping 12:30-13:10 fully + filtered 13:10->now"
  UNTIL=$(date -d '2026-10-16 13:10:00 UTC' '+%Y-%m-%d %H:%M:%S')
  sudoc journalctl -u admin_bot --since "$SINCE" --until "$UNTIL" --no-pager | head -n 12000
  sudoc journalctl -u admin_bot --since "$UNTIL" --no-pager | grep -iE 'SUMMARY|summary:|memory|compress|graph|extract|embed|LLM|timeout|permit|lock|queue|ERROR|WARN|Traceback|scheduler|Started|Stopping|Stopped|heartbeat|watchdog|Cancelled' | tail -n 5000
fi
echo "===== S5: previous successful run window 06:50-07:30 ====="
SINCE2=$(date -d '2026-10-16 06:50:00 UTC' '+%Y-%m-%d %H:%M:%S')
UNTIL2=$(date -d '2026-10-16 07:30:00 UTC' '+%Y-%m-%d %H:%M:%S')
echo "PREV_COUNT=$(sudoc journalctl -u admin_bot --since "$SINCE2" --until "$UNTIL2" --no-pager | wc -l)"
sudoc journalctl -u admin_bot --since "$SINCE2" --until "$UNTIL2" --no-pager | head -n 6000
echo "===== S6: filtered summary/memory/llm keywords 12:30->now ====="
sudoc journalctl -u admin_bot --since "$SINCE" --no-pager | grep -iE 'SUMMARY_RUN|SUMMARY_RESUME|SUMMARY_SOURCE|SUMMARY_START|SUMMARY_COMPLETE|SUMMARY_FAILED|SmartModule|graph extract|compress|embed|LLM|timeout|permit|lock busy|queued|watchdog|heartbeat|Cancelled|shutdown|Stopping|Stopped|Started admin' | tail -n 1200
echo "===== S7: restart window 12:59:30-13:02 ====="
S7A=$(date -d '2026-10-16 12:59:30 UTC' '+%Y-%m-%d %H:%M:%S')
S7B=$(date -d '2026-10-16 13:02:00 UTC' '+%Y-%m-%d %H:%M:%S')
sudoc journalctl -u admin_bot --since "$S7A" --until "$S7B" --no-pager | head -n 3000
echo "===== S8: sqlite read-only ====="
PYBIN=$(command -v python3)
[ -z "$PYBIN" ] && PYBIN=.venv/bin/python
echo "PYBIN=$PYBIN"
"$PYBIN" - <<'PYEOF' 2>&1
import os, sqlite3, datetime
dbp = os.environ.get('DBP') or 'local_database.db'
print('PYDB_OPEN', dbp)
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=15)
con.execute('PRAGMA query_only=ON')
def q(label, sql, params=()):
    try:
        rows = con.execute(sql, params).fetchall()
        print('--- %s ---' % label)
        n = 0
        for r in rows:
            print(r)
            n += 1
            if n >= 100:
                print('...(%d more)' % (len(rows) - n)); break
    except Exception as e:
        print('--- %s --- ERROR: %s' % (label, e))
cut = int(datetime.datetime(2026, 10, 16, 6, 50, tzinfo=datetime.timezone.utc).timestamp())
w1 = int(datetime.datetime(2026, 10, 16, 12, 59, 30, tzinfo=datetime.timezone.utc).timestamp())
w2 = int(datetime.datetime(2026, 10, 16, 13, 2, 0, tzinfo=datetime.timezone.utc).timestamp())
q('user_version', 'PRAGMA user_version')
q('tables', "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
q('summary_runs_recent', "SELECT run_id, chat_id, state, manual, window_from, window_to, source_ref, publication_status, created_at, updated_at FROM summary_runs ORDER BY created_at DESC LIMIT 15")
q('summary_runs_nonterminal', "SELECT run_id, chat_id, state, created_at, updated_at FROM summary_runs WHERE state NOT IN ('DONE','DEGRADED','FAILED') ORDER BY created_at DESC LIMIT 10")
q('summary_runs_states', "SELECT state, count(*) FROM summary_runs GROUP BY state")
q('summary_run_stages_recent', "SELECT run_id, stage, status, started_at, last_activity_at, finished_at, attempt, provider, model, reason_code FROM summary_run_stages ORDER BY id DESC LIMIT 40")
q('summary_source_windows_cnt', "SELECT count(*) FROM summary_source_windows")
q('events_counts_window', "SELECT event_name, count(*) FROM mca_events WHERE ts>=? GROUP BY event_name ORDER BY 2 DESC LIMIT 60", (cut,))
q('events_summary_window', "SELECT id, ts, level, event_name, outcome, trace_id, pipeline_run_id, chat_id, component, stage, reason_code, status, attempt, model, provider, span_id, job_id, causation_id, event_sequence, usage_json, error_json FROM mca_events WHERE ts>=? AND (event_name LIKE 'SUMMARY%' OR component='summary') ORDER BY ts, id LIMIT 300", (cut,))
q('events_around_restart', "SELECT id, ts, event_name, outcome, pipeline_run_id, trace_id, chat_id, stage, reason_code, event_sequence FROM mca_events WHERE ts BETWEEN ? AND ? ORDER BY id LIMIT 250", (w1, w2))
q('runs_in_window', "SELECT pipeline_run_id, count(*), min(ts), max(ts) FROM mca_events WHERE ts>=? AND pipeline_run_id IS NOT NULL GROUP BY pipeline_run_id ORDER BY max(ts) DESC LIMIT 25", (cut,))
q('watchdog_events', "SELECT id, ts, event_name, outcome, reason_code, job_id FROM mca_events WHERE event_name LIKE 'WATCHDOG%' AND ts>=? ORDER BY ts DESC LIMIT 40", (cut,))
q('timeout_events', "SELECT id, ts, event_name, component, reason_code FROM mca_events WHERE ts>=? AND reason_code IN ('timeout','rate_limit','provider_stalled','execution_deadline_exceeded','retry_time_budget_exhausted','quota_exhausted','paused_rate_limit') ORDER BY ts DESC LIMIT 40", (cut,))
q('task_jobs_recent', "SELECT job_id, owner, kind, coalesce_key, status, reason_code, attempt, max_attempts, heartbeat_at, created_at, updated_at, finished_at FROM task_jobs WHERE updated_at>=? ORDER BY updated_at DESC LIMIT 60", (cut,))
q('task_jobs_active', "SELECT status, owner, kind, count(*) FROM task_jobs WHERE status IN ('queued','running') GROUP BY status, owner, kind ORDER BY 4 DESC LIMIT 40")
q('task_jobs_summary_like', "SELECT job_id, owner, kind, coalesce_key, status, attempt, heartbeat_at, updated_at FROM task_jobs WHERE coalesce_key LIKE '%summary%' OR coalesce_key LIKE 'cover_style:%' OR owner LIKE '%summary%' OR kind LIKE '%summary%' ORDER BY updated_at DESC LIMIT 30")
q('task_jobs_running_ages', "SELECT job_id, owner, kind, status, heartbeat_at, updated_at, strftime('%s','now')-COALESCE(heartbeat_at,0) AS hb_age_s FROM task_jobs WHERE status='running' ORDER BY updated_at DESC LIMIT 30")
q('smart_messages_total', "SELECT count(*) FROM smart_messages")
q('smart_messages_top_chats', "SELECT chat_id, count(*), min(timestamp), max(timestamp) FROM smart_messages GROUP BY chat_id ORDER BY 2 DESC LIMIT 6")
q('smart_cols', "SELECT name FROM pragma_table_info('smart_messages')")
q('smart_last5', "SELECT id, chat_id, timestamp, substr(COALESCE(text,''),1,40) FROM smart_messages ORDER BY id DESC LIMIT 5")
q('smart_new_in_window', "SELECT count(*) FROM smart_messages WHERE timestamp>=?", (cut,))
q('smart_unprocessed_per_chat', "SELECT chat_id, count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL GROUP BY chat_id ORDER BY 2 DESC LIMIT 8")
q('smart_cutoff_candidates', "SELECT chat_id, count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL AND timestamp < strftime('%s','now')-604800 GROUP BY chat_id ORDER BY 2 DESC LIMIT 8")
q('archive_facts_cnt', "SELECT count(*) FROM smart_archive_facts")
q('nodes_edges_cnt', "SELECT (SELECT count(*) FROM nodes), (SELECT count(*) FROM edges)")
q('edges_max', "SELECT max(id), max(last_updated) FROM edges")
q('mca_events_max', "SELECT max(id), max(ts) FROM mca_events")
q('schema_migrations_last', "SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 5")
con.close()
PYEOF
echo "===== S9: postgres snapshot (read-only) ====="
if [ -x .venv/bin/python ]; then
  .venv/bin/python - <<'PYEOF2' 2>&1 | head -n 120
import asyncio, os, re, datetime
dsn = None
try:
    for line in open('.env', encoding='utf-8', errors='replace'):
        if line.startswith('POSTGRES_DSN='):
            dsn = line.split('=', 1)[1].strip().strip('"').strip("'")
except Exception as e:
    print('PG_ENV_ERR', e)
print('PG_DSN_PRESENT', bool(dsn))
if dsn:
    import asyncpg
    async def main():
        con = await asyncpg.connect(dsn, timeout=10)
        try:
            print('--- pg_activity ---')
            rows = await con.fetch("SELECT pid, state, wait_event_type, wait_event, "
                                   "extract(epoch from now()-query_start)::int AS dur_s, left(query,90) AS q "
                                   "FROM pg_stat_activity WHERE state IS NOT NULL AND state <> 'idle' "
                                   "ORDER BY dur_s DESC NULLS LAST LIMIT 15")
            for r in rows: print(dict(r))
            print('--- pg_locks ---')
            rows = await con.fetch("SELECT mode, granted, count(*) AS n FROM pg_locks GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20")
            for r in rows: print(dict(r))
            print('--- pg_idle_in_tx ---')
            rows = await con.fetch("SELECT count(*) AS n FROM pg_stat_activity WHERE state = 'idle in transaction'")
            for r in rows: print(dict(r))
            print('--- uptime_events ---')
            rows = await con.fetch("SELECT ts, status FROM uptime_events ORDER BY ts DESC LIMIT 15")
            for r in rows: print(dict(r))
        finally:
            await con.close()
    asyncio.run(main())
PYEOF2
else
  echo "NO_VENV_PYTHON"
fi
echo "===== S10: net + resources ====="
ss -tlnp 2>/dev/null | head -n 20
ss -tnp 2>/dev/null | head -n 40
free -m | head -n 3
df -h / /var 2>/dev/null | head -n 6
echo "===== S11: py-spy (nonblocking) ====="
PYSPY=$(command -v py-spy)
if [ -n "$PYSPY" ]; then
  echo "PYSPY_AT=$PYSPY"
  echo "$PW" | sudo -S -p '' "$PYSPY" dump --nonblocking --pid "$PID" 2>&1 | head -n 250
else
  echo "NO_PYSPY"
fi
echo "===== S12: error counts in window ====="
echo "ERR_COUNT=$(sudoc journalctl -u admin_bot --since "$SINCE" --no-pager | grep -cE ' ERROR | CRITICAL |Traceback')"
echo "LOCKED_COUNT=$(sudoc journalctl -u admin_bot --since "$SINCE" --no-pager | grep -cF 'database is locked')"
echo "===== MAIN_DONE ====="
"""


def run_main(pw: str, secrets: list[str]) -> int:
    script = MAIN_TEMPLATE.replace("__APP__", APP).replace("__PW__", shq(pw))
    c = connect(pw)
    try:
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=900)
        stdin.write(script)
        stdin.channel.shutdown_write()
        data = stdout.read().decode("utf-8", "replace")
        e = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        (OUT / "main.txt").write_text(text, encoding="utf-8")
        print(text[-4000:])
        print("\n[exit] rc=%s, bytes=%d" % (rc, len(text)))
    finally:
        c.close()
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "recon"
    pw = _pwd("pass")
    secrets = [pw]
    try:
        secrets.append(_pwd("pass_gti_pull"))
    except SystemExit:
        pass
    if mode == "recon":
        return run_recon(pw, secrets)
    if mode == "main":
        return run_main(pw, secrets)
    raise SystemExit("usage: probe.py recon|main")


if __name__ == "__main__":
    sys.exit(main())
