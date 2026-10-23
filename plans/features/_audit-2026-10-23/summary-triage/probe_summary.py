# -*- coding: utf-8 -*-
"""LANE SUMMARY-PROD-TRIAGE — read-only production probe (1 SSH connection).

Collects, in one batch:
  * summary_runs (all rows), summary_run_stages (all), summary events (mca_events)
  * journal lines for L2 review / legacy fallback / run-done
  * PG llm_usage_events for module='summary' (L2 writer/review call volume)
  * embeddings quota/backlog/index/job state (secondary question)

Nothing is written on the server: the remote script arrives via stdin
(`bash -s`), SQLite is opened `mode=ro` + `query_only=ON`, PG is SELECT-only.

Usage: py -3 probe_summary.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
OUT = Path(__file__).resolve().parent / "raw"


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
    # bare bot tokens / long hex secrets that may appear in tracebacks
    text = re.sub(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", "***BOT_TOKEN***", text)
    return text


SCRIPT = r"""
set +e
export LC_ALL=C
cd /var/www/admin_bot || exit 3
echo "DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "GIT_HEAD=$(git rev-parse HEAD 2>/dev/null)"
echo "GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
systemctl show admin_bot -p ActiveState -p SubState -p NRestarts -p ExecMainStartTimestamp 2>/dev/null | sed 's/^/SVC /'
PYBIN=venv/bin/python
[ -x "$PYBIN" ] || PYBIN=.venv/bin/python
echo "PYBIN=$PYBIN"
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
[ -z "$DBP" ] && DBP=local_database.db
export DBP

echo "===== R1 sqlite: summary runs/stages/events ====="
"$PYBIN" - <<'PYEOF' 2>&1
import glob, json, os, sqlite3, time

dbp = os.environ['DBP']
now = int(time.time())
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=30)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')


def show(label, sql, params=(), cap=400, limit=None):
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e))
        return []
    print('--- %s (n=%d) ---' % (label, len(rows)))
    for r in rows[:limit] if limit else rows:
        d = {}
        for k, v in dict(r).items():
            if isinstance(v, str) and len(v) > cap:
                v = v[:cap] + '..[cut]'
            d[k] = v
        print(d)
    return rows


print('DB_PATH_BASENAME=%s' % os.path.basename(dbp))
show('runs_all',
     "SELECT run_id, chat_id, state, manual, window_from, window_to, "
     "publication_status, pipeline_health, created_at, updated_at, "
     "source_ref, publication_result_ref FROM summary_runs ORDER BY created_at")
show('runs_by_state',
     "SELECT state, publication_status, pipeline_health, COUNT(*) AS n, "
     "MIN(created_at) AS first_ts, MAX(created_at) AS last_ts "
     "FROM summary_runs GROUP BY 1,2,3 ORDER BY n DESC")
show('stage_agg',
     "SELECT stage, status, reason_code, COUNT(*) AS n FROM summary_run_stages "
     "GROUP BY 1,2,3 ORDER BY n DESC")
show('stage_per_run',
     "SELECT s.run_id, s.stage, s.status, s.attempt, s.reason_code, "
     "s.started_at, s.finished_at, s.provider, s.model, s.result_ref "
     "FROM summary_run_stages s ORDER BY s.run_id, s.id", cap=160)
show('events_names',
     "SELECT event_name, outcome, reason_code, COUNT(*) AS n, MAX(ts) AS last_ts "
     "FROM mca_events WHERE event_name LIKE 'SUMMARY%' GROUP BY 1,2,3 "
     "ORDER BY n DESC")
show('l2_stage_detail',
     "SELECT ts, event_name, status, reason_code, pipeline_run_id, usage_json "
     "FROM mca_events "
     "WHERE event_name IN ('SUMMARY_L2_STAGE','SUMMARY_L2_REVIEW',"
     "'SUMMARY_LEGACY_FALLBACK') AND ts >= ? ORDER BY ts",
     (now - 12 * 86400,), cap=520)
show('run_done_detail',
     "SELECT ts, reason_code, status, pipeline_run_id, usage_json "
     "FROM mca_events WHERE event_name='SUMMARY_RUN_DONE' AND ts >= ? "
     "ORDER BY ts", (now - 12 * 86400,), cap=520)
show('chat_running_summary',
     "SELECT chat_id, created_at, expires_at, raw_count, length(summary) AS s_len "
     "FROM chat_running_summary")
show('quota_state',
     "SELECT * FROM embedding_quota_state ORDER BY 1,2", cap=200)
show('memory_jobs',
     "SELECT job_id, owner, kind, status, reason_code, updated_at, "
     "substr(payload,1,220) AS payload FROM task_jobs WHERE owner IN "
     "('memory','summary') ORDER BY updated_at DESC", cap=230)
show('graph_counts',
     "SELECT (SELECT COUNT(*) FROM graph_facts) AS facts, "
     "(SELECT COUNT(*) FROM nodes) AS nodes, (SELECT COUNT(*) FROM edges) AS edges")
show('index_generations',
     "SELECT generation_id, index_name, generation, status, created_at, "
     "activated_at, superseded_at, provider, model FROM "
     "mca_embedding_index_generations ORDER BY index_name", cap=120)
show('embed_events_7d',
     "SELECT event_name, reason_code, COUNT(*) AS n, MAX(ts) AS last_ts "
     "FROM mca_events WHERE event_name LIKE 'EMBEDDING%' AND ts >= ? "
     "GROUP BY 1,2 ORDER BY n DESC", (now - 7 * 86400,))

# vec0 counts (best effort; extension is optional for the rest of the probe)
try:
    cands = sorted(set(
        glob.glob('venv/**/vec0*.so', recursive=True)
        + glob.glob('.venv/**/vec0*.so', recursive=True)))
    if cands:
        con.enable_load_extension(True)
        con.load_extension(cands[0])
        print('VEC_EXT=%s' % os.path.basename(cands[0]))
        show('vec_counts',
             "SELECT (SELECT COUNT(*) FROM graph_facts_vec) AS facts_vec, "
             "(SELECT COUNT(*) FROM smart_archive) AS archive, "
             "(SELECT COUNT(*) FROM smart_archive_facts) AS archive_facts")
    else:
        print('VEC_EXT=none')
except Exception as e:
    print('VEC_COUNTS_ERROR %s: %s' % (type(e).__name__, e))
con.close()
PYEOF

echo "===== R2 journal (counts since 2026-10-18) ====="
SINCE="2026-10-18 00:00:00"
for pat in "L2_REVIEW |" "LEGACY_FALLBACK |" "L2_ERROR" "finish_reason" "SUMMARY_COMPLETE" "FACT_VIEW_EMPTY"; do
  n=$(journalctl -u admin_bot --since "$SINCE" --no-pager -o cat 2>/dev/null | grep -cF "$pat")
  echo "COUNT[$pat]=$n"
done
echo "----- detail: L2 review / fallback / errors -----"
journalctl -u admin_bot --since "$SINCE" --no-pager -o cat 2>/dev/null \
  | grep -E 'L2_REVIEW \||L2_REVIEW_FINDING_DROPPED|L2_REVIEW_DEGRADED|L2_UNUSABLE_GATE|L2_STAGNATION|LEGACY_FALLBACK \||L2_ERROR|FACT_VIEW_EMPTY|COVERAGE_SKIP_EMPTY' \
  | tail -n 420
echo "----- detail: finish_reason / truncation -----"
journalctl -u admin_bot --since "$SINCE" --no-pager -o cat 2>/dev/null \
  | grep -iE 'finish_reason|truncat|too many paragraphs|too_long|max_tokens|context.*overflow' \
  | tail -n 80

echo "===== R3 postgres: summary llm usage ====="
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
                print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, str(e)[:200]))
                return
            print('--- %s (n=%d) ---' % (label, len(rows)))
            for r in rows:
                print(dict(r))

        await q('usage_by_step_10d',
                "SELECT step, COUNT(*) AS n, COUNT(DISTINCT correlation_id) AS runs, "
                "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
                "MAX(output_tokens) AS max_out, MAX(ts) AS last_ts "
                "FROM llm_usage_events WHERE module='summary' AND ts >= now() - interval '10 days' "
                "GROUP BY step ORDER BY n DESC")
        await q('usage_recent_calls',
                "SELECT ts, correlation_id, step, model, input_tokens, output_tokens, "
                "substr(plan_meta::text,1,200) AS plan_meta "
                "FROM llm_usage_events WHERE module='summary' AND ts >= now() - interval '3 days' "
                "ORDER BY ts DESC LIMIT 40")
    finally:
        await con.close()


asyncio.run(main())
PYEOF2
echo "===== DONE ====="
"""


def main() -> int:
    secret = _pwd("pass")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=22, username=USER, password=secret,
                   timeout=25, banner_timeout=30, auth_timeout=30,
                   look_for_keys=False, allow_agent=False)
    try:
        stdin, stdout, stderr = client.exec_command(
            "bash -s", timeout=600, get_pty=False)
        stdin.write(SCRIPT)
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
    finally:
        client.close()

    text = scrub(out + "\n===STDERR===\n" + err, [secret, _pwd("pass_gti_pull")])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary_probe.txt").write_text(text, encoding="utf-8")
    print(text[:2000])
    print("...\n[bytes=%d] -> %s" % (len(text), OUT / "summary_probe.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
