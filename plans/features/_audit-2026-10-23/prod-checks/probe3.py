# -*- coding: utf-8 -*-
"""DEVOPS-PROD-CHECKS follow-up #2 (connection #4): remaining targeted reads.

Fixes the %-format bug from probe2 (all SQL parameterized) and collects:
  * SOUL-14.2: feedback signals (fact_correction/wrong_addressee), repetition,
    payload mismatch, one_word samples over 30d
  * B10-R11: DIRECT event mix, tool-call evidence, PG plan_meta durability,
    no-key sandbox guard hits
  * B10-R10: retrieval per chat + samples (isolation proxy)
  * anomalies: summary runs/stages, incidents

Read-only. Usage: py -3 probe3.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
OUT = Path(r"C:\Code\Python\adminbot\plans\features\_audit-2026-10-23\prod-checks\raw")


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
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+",
                  r"\1***", text)
    return text


SCRIPT = r"""
set +e
export LC_ALL=C
cd /var/www/admin_bot || exit 3
echo "DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PYBIN=venv/bin/python
[ -x "$PYBIN" ] || PYBIN=.venv/bin/python
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
[ -z "$DBP" ] && DBP=local_database.db
export DBP

echo "===== U1 sqlite targeted ====="
"$PYBIN" - <<'PYEOF' 2>&1
import os, sqlite3, time
dbp = os.environ['DBP']
now = int(time.time())
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=20)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
T = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type in ('table','view')")}

def q(label, sql, params=(), limit=25):
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e)); return []
    print('--- %s (n=%d) ---' % (label, len(rows)))
    for r in rows[:limit]:
        print(dict(r))
    if len(rows) > limit:
        print('...(%d more)' % (len(rows)-limit))
    return rows

w30 = now - 30*86400
w7 = now - 7*86400

q('feedback_signals_30d',
  "SELECT json_extract(signal_json,'$.domain') AS domain, json_extract(signal_json,'$.signal') AS signal, "
  "COUNT(*) AS n FROM mca_experience_feedback WHERE ts>=? GROUP BY 1,2 ORDER BY n DESC", (w30,))
q('feedback_sources_30d',
  "SELECT source_kind, authority, reliability, COUNT(*) AS n FROM mca_experience_feedback WHERE ts>=? "
  "GROUP BY 1,2,3 ORDER BY n DESC", (w30,))
q('style_repetition_30d',
  "SELECT COUNT(*) AS n FROM mca_events WHERE event_name='style_policy' "
  "AND json_array_length(json_extract(usage_json,'$.repetition'))>0 AND ts>=?", (w30,))
q('style_payload_mismatch_30d',
  "SELECT COUNT(*) AS n FROM mca_events WHERE event_name='style_policy' "
  "AND json_extract(usage_json,'$.payload_status')='mismatch' AND ts>=?", (w30,))
q('speech_oneword_30d',
  "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN json_extract(usage_json,'$.one_word_exact')=1 THEN 1 ELSE 0 END),0) AS exact "
  "FROM mca_events WHERE event_name='speech_extent' AND json_extract(usage_json,'$.extent')='one_word' AND ts>=?", (w30,))
q('speech_words_all',
  "SELECT json_extract(usage_json,'$.extent') AS extent, json_extract(usage_json,'$.words') AS words, "
  "json_extract(usage_json,'$.status') AS status, COUNT(*) AS n FROM mca_events "
  "WHERE event_name='speech_extent' GROUP BY 1,2,3 ORDER BY n DESC")
q('direct_events_7d',
  "SELECT event_name, outcome, COUNT(*) AS n, MAX(ts) AS last_ts FROM mca_events "
  "WHERE event_name LIKE ? AND ts>=? GROUP BY 1,2 ORDER BY n DESC", ('DIRECT%', w7))
q('direct_fresh_samples',
  "SELECT ts, chat_id, outcome, usage_json FROM mca_events WHERE event_name='DIRECT_FRESH_GENERATION' "
  "ORDER BY ts DESC LIMIT 3")
q('l1_meta_update', "SELECT COUNT(*) FROM bot_replies")
q('retrieval_30d',
  "SELECT chat_id, outcome, reason_code, COUNT(*) AS n, MAX(ts) AS last_ts FROM mca_events "
  "WHERE event_name='mca07_retrieval' AND ts>=? GROUP BY 1,2,3 ORDER BY n DESC", (w30,))
q('retrieval_samples',
  "SELECT ts, chat_id, outcome, reason_code, usage_json FROM mca_events "
  "WHERE event_name='mca07_retrieval' ORDER BY ts DESC LIMIT 3")
q('summary_runs_detail',
  "SELECT run_id, chat_id, state, publication_status, pipeline_health, created_at, updated_at "
  "FROM summary_runs ORDER BY created_at DESC LIMIT 6")
q('summary_stages_nonok',
  "SELECT run_id, stage, status, attempt, reason_code, started_at, finished_at FROM summary_run_stages "
  "WHERE status NOT IN ('done','skipped','ok') ORDER BY id DESC LIMIT 8")
q('incidents',
  "SELECT incident_id, process_id, pipeline_type, stage, severity, title, first_ts, last_ts, repeat_count, "
  "impact, fallback_used, resolved_at FROM mca_incidents ORDER BY created_at DESC LIMIT 4")
q('events_speech_samples',
  "SELECT ts, chat_id, stage, outcome, usage_json FROM mca_events WHERE event_name='speech_extent' "
  "ORDER BY ts DESC LIMIT 3")
con.close()
PYEOF

echo "===== U2 journal: direct/tool/L1 guard ====="
since7=$(date -d '-7 days' '+%Y-%m-%d %H:%M:%S')
echo "TOOL_PLAN=$(journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -c 'TOOL_PLAN_CREATED')"
echo "TOOL_START=$(journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -c 'TOOL_CALL_START')"
echo "TOOL_OK=$(journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -c 'TOOL_CALL_COMPLETE')"
echo "TOOL_FAIL=$(journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -c 'TOOL_CALL_FAILED')"
journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -E 'TOOL_CALL_COMPLETE|TOOL_CALL_FAILED' | tail -n 6
echo "NO_KEY_SANDBOX_30D=$(journalctl -u admin_bot --since "$(date -d '-30 days' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>/dev/null | grep -c 'no key — sandbox')"
echo "L1_META_FAIL_30D=$(journalctl -u admin_bot --since "$(date -d '-30 days' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>/dev/null | grep -c 'plan_meta attach failed')"
echo "L1_LADDER_WARN_7D=$(journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -cE 'l1 (dedicated|ladder)|l1_plan fallback')"
journalctl -u admin_bot --since "$since7" --no-pager 2>/dev/null | grep -iE 'l1 (dedicated|ladder)|l1_plan fallback' | tail -n 6

echo "===== U3 postgres: L1 plan_meta durability ====="
"$PYBIN" - <<'PYEOF2' 2>&1
import asyncio
dsn = None
for line in open('.env', encoding='utf-8', errors='replace'):
    if line.startswith('POSTGRES_DSN='):
        dsn = line.split('=', 1)[1].strip().strip('"').strip("'")
import asyncpg

async def main():
    con = await asyncpg.connect(dsn, timeout=12)
    try:
        async def q(label, sql):
            try:
                rows = await con.fetch(sql)
            except Exception as e:
                print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, str(e)[:160])); return
            print('--- %s (n=%d) ---' % (label, len(rows)))
            for r in rows[:12]:
                print(dict(r))
        await q('l1_usage_7d',
                "SELECT COUNT(*) AS n, COUNT(DISTINCT correlation_id) AS runs, "
                "COUNT(plan_meta) AS with_meta, MAX(ts) AS last_ts, "
                "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok "
                "FROM llm_usage_events WHERE module='direct_chat' AND step='l1_planner' "
                "AND ts >= now() - interval '7 days'")
        await q('l1_usage_daily',
                "SELECT date_trunc('day', ts)::date AS d, COUNT(*) AS n, COUNT(plan_meta) AS with_meta "
                "FROM llm_usage_events WHERE module='direct_chat' AND step='l1_planner' "
                "AND ts >= now() - interval '7 days' GROUP BY d ORDER BY d DESC")
        await q('l1_plan_meta_samples',
                "SELECT ts, chat_id, plan_meta::text AS plan_meta FROM llm_usage_events "
                "WHERE module='direct_chat' AND step='l1_planner' AND plan_meta IS NOT NULL "
                "ORDER BY ts DESC LIMIT 3")
        await q('tool_usage_7d',
                "SELECT module, step, tool_name, COUNT(*) AS n FROM llm_usage_events "
                "WHERE ts >= now() - interval '7 days' AND tool_name <> '' GROUP BY 1,2,3 ORDER BY n DESC LIMIT 12")
    finally:
        await con.close()

asyncio.run(main())
PYEOF2
echo "===== U4_DONE ====="
"""


def run(pw: str, secrets: list[str]) -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, pw, timeout=20, banner_timeout=20,
              auth_timeout=20, allow_agent=False, look_for_keys=False)
    try:
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=600)
        stdin.write(SCRIPT)
        stdin.channel.shutdown_write()
        data = stdout.read().decode("utf-8", "replace")
        e = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "main3.txt").write_text(text, encoding="utf-8")
        print(text[:3000])
        print("\n[exit] rc=%s, bytes=%d" % (rc, len(text)))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    pw = _pwd("pass")
    secrets = [pw]
    try:
        secrets.append(_pwd("pass_gti_pull"))
    except SystemExit:
        pass
    sys.exit(run(pw, secrets))
