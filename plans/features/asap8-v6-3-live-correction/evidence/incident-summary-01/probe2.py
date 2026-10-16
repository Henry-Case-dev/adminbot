# -*- coding: utf-8 -*-
"""INC-SUMMARY-01 follow-up batch (3rd and last SSH login; read-only).

Closes: hot-config values (PG bot_settings + chat overrides), restart history,
eligible extract backlog, PG snapshot, uptime/restart correlation.

Usage: py -3 probe2.py
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
    return text


def shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


SCRIPT = r"""
set +e
export LC_ALL=C
cd __APP__
PW=__PW__
sudoc() { echo "$PW" | sudo -S -p '' "$@"; }
echo "===== F1: restart history (journal grep since 2026-10-08) ====="
sudoc journalctl -u admin_bot --since '2026-10-08 00:00:00' --no-pager | grep -E 'Stopping admin_bot|Started admin_bot|stop-sigterm|Received SIGTERM|Bot shutting down|Killing process' | tail -n 80
echo "===== F2: sqlite follow-up ====="
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
export DBP
PYBIN=$(command -v python3); [ -z "$PYBIN" ] && PYBIN=venv/bin/python
"$PYBIN" - <<'PYEOF' 2>&1
import os, sqlite3, datetime
dbp = os.environ.get('DBP') or 'local_database.db'
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=15)
con.execute('PRAGMA query_only=ON')
def q(label, sql, params=()):
    try:
        rows = con.execute(sql, params).fetchall()
        print('--- %s ---' % label)
        for r in rows: print(r)
    except Exception as e:
        print('--- %s --- ERROR: %s' % (label, e))
now = "strftime('%s','now')"
q('eligible_30d', "SELECT count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL AND timestamp < %s-2592000" % now)
q('eligible_90d', "SELECT count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL AND timestamp < %s-7776000" % now)
q('eligible_365d', "SELECT count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL AND timestamp < %s-31536000" % now)
q('eligible_all', "SELECT count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL")
q('eligible_newer_30d', "SELECT count(*) FROM smart_messages WHERE history_processed=0 AND import_key IS NULL AND timestamp >= %s-2592000" % now)
q('stuck_run_row', "SELECT * FROM summary_runs WHERE run_id='da33f05db7754a38bdea7d591cf6eccc'")
q('stuck_run_events', "SELECT * FROM mca_events WHERE pipeline_run_id='da33f05db7754a38bdea7d591cf6eccc'")
q('stuck_run_stages', "SELECT * FROM summary_run_stages WHERE run_id='da33f05db7754a38bdea7d591cf6eccc'")
q('chat_running_summary', "SELECT chat_id, window_end_ts, raw_count, created_at, expires_at FROM chat_running_summary ORDER BY created_at DESC LIMIT 5")
q('mca_pipeline_runs_summary', "SELECT pipeline_type, started_at, finished_at, chat_id FROM mca_pipeline_runs WHERE pipeline_type LIKE '%summary%' ORDER BY started_at DESC LIMIT 8")
q('summary_source_windows_recent', "SELECT run_id, chat_id, window_from, window_to, created_at FROM summary_source_windows ORDER BY created_at DESC LIMIT 5")
con.close()
PYEOF
echo "===== F3: postgres hot config + snapshot ====="
if [ -x venv/bin/python ]; then
  venv/bin/python - <<'PYEOF2' 2>&1 | head -n 140
import asyncio
dsn = None
for line in open('.env', encoding='utf-8', errors='replace'):
    if line.startswith('POSTGRES_DSN='):
        dsn = line.split('=', 1)[1].strip().strip('"').strip("'")
print('PG_DSN_PRESENT', bool(dsn))
if dsn:
    import asyncpg
    KEYS = ('memory.infinite_retention', 'limits.full_memory_retention_days',
            'limits.summary_compress_batch', 'flags.summary_enabled',
            'flags.graph_rag_enabled', 'flags.chat_running_summary_enabled',
            'limits.summary_timezone', 'limits.graph_episode_merge_interval_days')
    async def main():
        con = await asyncpg.connect(dsn, timeout=10)
        try:
            print('--- bot_settings ---')
            rows = await con.fetch("SELECT key, value FROM bot_settings WHERE key = ANY($1::text[]) ORDER BY key", list(KEYS))
            for r in rows: print(dict(r))
            print('--- chat_profiles_overrides ---')
            rows = await con.fetch("SELECT chat_id, chat_params->'overrides' AS overrides FROM chat_profiles WHERE chat_id IN (-1002661910336, -1004482340693)")
            for r in rows: print(dict(r))
            print('--- pg_activity ---')
            rows = await con.fetch("SELECT pid, state, wait_event_type, wait_event, "
                                   "extract(epoch from now()-query_start)::int AS dur_s, left(query,80) AS q "
                                   "FROM pg_stat_activity WHERE state IS NOT NULL AND state <> 'idle' "
                                   "ORDER BY dur_s DESC NULLS LAST LIMIT 12")
            for r in rows: print(dict(r))
            print('--- pg_locks ---')
            rows = await con.fetch("SELECT mode, granted, count(*) AS n FROM pg_locks GROUP BY 1,2 ORDER BY 3 DESC LIMIT 12")
            for r in rows: print(dict(r))
            print('--- uptime_events ---')
            rows = await con.fetch("SELECT ts, status FROM uptime_events ORDER BY ts DESC LIMIT 20")
            for r in rows: print(dict(r))
            print('--- uptime_gaps_13h ---')
            rows = await con.fetch("SELECT ts, status FROM uptime_events WHERE ts >= '2026-10-16 11:00:00+00' ORDER BY ts ASC LIMIT 40")
            for r in rows: print(dict(r))
        finally:
            await con.close()
    asyncio.run(main())
PYEOF2
else
  echo "NO_VENV"
fi
echo "===== F4: current state sanity ====="
systemctl show admin_bot -p MainPID,ExecMainStartTimestamp,NRestarts --no-pager
echo "HZ=$(curl -s --max-time 6 http://127.0.0.1:8000/healthz)"
echo "===== F_DONE ====="
"""


def main() -> int:
    pw = _pwd("pass")
    secrets = [pw]
    try:
        secrets.append(_pwd("pass_gti_pull"))
    except SystemExit:
        pass
    script = SCRIPT.replace("__APP__", APP).replace("__PW__", shq(pw))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, pw, timeout=20, banner_timeout=20,
              auth_timeout=20, allow_agent=False, look_for_keys=False)
    try:
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=600)
        stdin.write(script)
        stdin.channel.shutdown_write()
        data = stdout.read().decode("utf-8", "replace")
        e = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        (OUT / "main2.txt").write_text(text, encoding="utf-8")
        print(text)
        print("\n[exit] rc=%s bytes=%d" % (rc, len(text)))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
