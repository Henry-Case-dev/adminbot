# -*- coding: utf-8 -*-
"""DEVOPS-PROD-CHECKS: read-only prod probes for READY_FOR_LIVE rows.

Two SSH logins max (AGENTS.md fail2ban discipline):
  #1 recon (short) -> #2 main batched collection (one bash -s script).

Only SELECT / file reads / journalctl / healthz. No writes, no restarts.

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
OUT = Path(r"C:\Code\Python\adminbot\plans\features\_audit-2026-10-23\prod-checks\raw")
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
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+",
                  r"\1***", text)
    return text


def shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def connect(pw: str) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, pw, timeout=20, banner_timeout=20,
              auth_timeout=20, allow_agent=False, look_for_keys=False)
    return c


RECON_CMD = (
    "export LC_ALL=C; cd /var/www/admin_bot || exit 3; "
    "echo DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ'); "
    "echo DATE_LOCAL=$(date '+%Y-%m-%d %H:%M:%S %Z %z'); "
    "echo HOST=$(hostname); "
    "echo HEAD=$(git rev-parse HEAD); "
    "echo BRANCH=$(git rev-parse --abbrev-ref HEAD); "
    "echo DIRTY=$(git status --porcelain | wc -l); "
    "echo ACTIVE=$(systemctl is-active admin_bot); "
    "systemctl show admin_bot -p NRestarts -p ExecMainStartTimestamp -p MainPID --no-pager; "
    "ls -l venv/bin/python .venv/bin/python 2>/dev/null; "
    "grep -c . .env 2>/dev/null | sed 's/^/ENV_LINES=/'; "
    "grep -E '^DB_PATH=' .env 2>/dev/null || echo NO_DB_PATH_KEY; "
    "ls -la local_database.db local_database.db-wal 2>/dev/null; "
    "if journalctl -u admin_bot -n 1 --no-pager >/dev/null 2>&1; then "
    "echo JOURNAL_PLAIN_OK; else echo JOURNAL_NEEDS_SUDO; fi; "
    "curl -s --max-time 8 http://127.0.0.1:8000/healthz; echo"
)


def run_recon(pw: str, secrets: list[str]) -> int:
    c = connect(pw)
    try:
        _in, out, err = c.exec_command(RECON_CMD, timeout=40)
        data = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "recon.txt").write_text(text + f"\n[rc={rc}]\n", encoding="utf-8")
        print(text)
        print(f"[rc={rc}]")
    finally:
        c.close()
    return 0


MAIN_TEMPLATE = r"""
set +e
export LC_ALL=C
cd __APP__ || exit 3
PW=__PW__
sudoc() { echo "$PW" | sudo -S -p '' "$@"; }

echo "===== S0 identity ====="
echo "DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "HEAD=$(git rev-parse HEAD)"
git log -1 --format='COMMIT=%H %cI %s' | head -c 300; echo
echo "ACTIVE=$(systemctl is-active admin_bot)"
systemctl show admin_bot -p NRestarts -p ExecMainStartTimestamp -p MainPID --no-pager
echo "HZ=$(curl -s --max-time 8 http://127.0.0.1:8000/healthz)"

echo "===== S1 env gates (masked) ====="
grep -hE '^(DIRECT_L1_|DIRECT_|MCA_|EMBEDDING_|EMBED_|SPEECH_|STYLE_|PG_|POSTGRES_|SUMMARY_|GRAPH_RAG|AGENTIC_|TELEMETRY|LOG_LEVEL|DB_PATH|OPENROUTER|OPENAI|DEEPSEEK|API_)' .env 2>/dev/null \
  | sed -E 's/^([A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|DSN|URL)[A-Z0-9_]*)=.*/\1=<set>/' \
  | sort | head -n 160

echo "===== S2 python bin ====="
PYBIN=""
for cand in venv/bin/python .venv/bin/python python3; do
  if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then PYBIN="$cand"; break; fi
done
echo "PYBIN=$PYBIN"
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
[ -z "$DBP" ] && DBP=local_database.db
echo "DB_PATH=$DBP"
export DBP

echo "===== S3 sqlite read-only snapshot ====="
"$PYBIN" - <<'PYEOF' 2>&1
import json, os, sqlite3, time
dbp = os.environ.get('DBP') or 'local_database.db'
print('SQLITE', dbp)
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=20)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
now = int(time.time())

def tables():
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type in ('table','view')")}

T = tables()

def cols(t):
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(%s)" % t)}
    except Exception:
        return set()

def q(label, sql, params=(), limit=40):
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e)); return
    print('--- %s (n=%d) ---' % (label, len(rows)))
    for r in rows[:limit]:
        print(dict(r) if isinstance(r, sqlite3.Row) else r)
    if len(rows) > limit:
        print('...(%d more)' % (len(rows) - limit))

def one(label, sql, params=()):
    try:
        r = con.execute(sql, params).fetchone()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e)); return None
    print('--- %s --- %s' % (label, tuple(r) if r is not None else None))
    return r

one('user_version', 'PRAGMA user_version')
q('schema_migrations_last', "SELECT version, name FROM schema_migrations ORDER BY version DESC LIMIT 5")
print('TABLE_HAS', {t: sorted(cols(t)) for t in
      ['chat_id_migrations','chat_migration_backup','chat_running_summary','chat_summary_levels',
       'smart_messages','smart_archive_facts','graph_facts','nodes','edges','protected_facts',
       'mca_episodes','graph_fact_compressions','mca_events','task_jobs','embedding_quota_state',
       'mca_embedding_index_generations','embedding_cache'] if t in T})

# ---- B09: chat id migrations + memory/profile carriers ----
if 'chat_id_migrations' in T:
    q('b09_chat_id_migrations', "SELECT * FROM chat_id_migrations ORDER BY observed_at DESC LIMIT 20")
    one('b09_migrations_total', "SELECT COUNT(*) FROM chat_id_migrations")
if 'chat_migration_backup' in T:
    q('b09_backup_ids', "SELECT migration_id, COUNT(*) AS rows, MIN(created_at) AS t0, MAX(created_at) AS t1 FROM chat_migration_backup GROUP BY migration_id ORDER BY t1 DESC LIMIT 10")
for t in ['smart_messages','smart_archive_facts','graph_facts','nodes','edges','protected_facts',
          'mca_episodes','graph_fact_compressions','chat_summary_levels','chat_running_summary']:
    if t in T and 'chat_id' in cols(t):
        q('b09_rows_' + t, "SELECT chat_id, COUNT(*) AS n FROM %s GROUP BY chat_id ORDER BY n DESC LIMIT 12" % t)
if 'chat_running_summary' in T:
    q('b09_running_summary_meta',
      "SELECT chat_id, window_start_ts, window_end_ts, raw_count, created_at, expires_at FROM chat_running_summary ORDER BY chat_id")
if 'chat_summary_levels' in T:
    q('b09_summary_levels_meta',
      "SELECT chat_id, level, raw_count, window_end_ts, updated_at FROM chat_summary_levels ORDER BY chat_id, level")

# ---- SOUL-14.2: speech_extent telemetry ----
if 'mca_events' in T:
    ec = cols('mca_events')
    one('events_total', "SELECT COUNT(*), MIN(ts), MAX(ts) FROM mca_events")
    q('events_top48h', "SELECT event_name, COUNT(*) AS n FROM mca_events WHERE ts>=? GROUP BY event_name ORDER BY n DESC LIMIT 45", (now-48*3600,))
    q('events_by_day', "SELECT date(ts,'unixepoch') AS d, COUNT(*) AS n FROM mca_events WHERE ts>=? GROUP BY d ORDER BY d DESC LIMIT 10", (now-14*86400,))
    if 'usage_json' in ec:
        q('soul142_extent_total', "SELECT COUNT(*) AS n, MIN(ts), MAX(ts) FROM mca_events WHERE event_name='speech_extent'")
        q('soul142_extent_by_extent',
          "SELECT json_extract(usage_json,'$.extent') AS extent, json_extract(usage_json,'$.status') AS status, "
          "json_extract(usage_json,'$.one_word_exact') AS owx, json_extract(usage_json,'$.context') AS ctx, "
          "COUNT(*) AS n FROM mca_events WHERE event_name='speech_extent' GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT 40")
        q('soul142_words_hist',
          "SELECT json_extract(usage_json,'$.words') AS words, COUNT(*) AS n FROM mca_events "
          "WHERE event_name='speech_extent' AND json_extract(usage_json,'$.extent')='one_word' GROUP BY 1 ORDER BY n DESC LIMIT 20")
        q('soul142_reasons',
          "SELECT json_extract(usage_json,'$.reason') AS reason, COUNT(*) AS n FROM mca_events "
          "WHERE event_name='speech_extent' AND json_extract(usage_json,'$.reason') IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 20")
        q('soul142_style_events',
          "SELECT event_name, outcome, COUNT(*) AS n FROM mca_events WHERE event_name IN ('style_policy','speech_extent') AND ts>=? GROUP BY 1,2", (now-30*86400,))
    q('repetition_events', "SELECT event_name, outcome, COUNT(*) AS n FROM mca_events WHERE event_name LIKE '%REPET%' AND ts>=? GROUP BY 1,2 LIMIT 20", (now-30*86400,))

# ---- B10-R06: embeddings quota/index/backlog ----
if 'embedding_quota_state' in T:
    q('b10_quota_state', "SELECT * FROM embedding_quota_state ORDER BY quota_group_id LIMIT 20")
if 'mca_embedding_index_generations' in T:
    q('b10_index_generations', "SELECT generation_id, index_name, generation, status, provider, model, dims, created_at, activated_at, superseded_at FROM mca_embedding_index_generations ORDER BY generation_id DESC LIMIT 12")
if 'embedding_cache' in T:
    one('b10_embedding_cache_rows', "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM embedding_cache")
for t in ['graph_facts_vec','smart_archive']:
    if t in T:
        one('b10_veccount_' + t, "SELECT COUNT(*) FROM %s" % t)
    else:
        print('--- b10_veccount_%s --- TABLE_ABSENT' % t)
if 'smart_archive_facts' in T and 'smart_archive' in T:
    one('b10_backlog_archive', "SELECT COUNT(*) FROM smart_archive_facts WHERE id NOT IN (SELECT fact_id FROM smart_archive)")
if 'graph_facts' in T and 'graph_facts_vec' in T:
    one('b10_backlog_graph', "SELECT COUNT(*) FROM graph_facts WHERE id NOT IN (SELECT fact_id FROM graph_facts_vec) AND (expires_at IS NULL OR expires_at > %d)" % now)
one('b10_graph_facts_total', "SELECT COUNT(*) FROM graph_facts")
one('b10_graph_facts_7d', "SELECT COUNT(*) FROM graph_facts WHERE created_at >= %d" % (now-7*86400))

# ---- jobs / producers ----
if 'task_jobs' in T:
    q('jobs_active', "SELECT owner, kind, status, COUNT(*) AS n, MAX(updated_at) AS last_upd FROM task_jobs WHERE status IN ('queued','running','paused','paused_rate_limit','paused_provider','building') GROUP BY 1,2,3 ORDER BY n DESC LIMIT 25")
    q('jobs_kinds_7d', "SELECT owner, kind, status, COUNT(*) AS n, MAX(updated_at) AS last_upd FROM task_jobs WHERE updated_at>=? GROUP BY 1,2,3 ORDER BY last_upd DESC LIMIT 30", (now-7*86400,))
    q('jobs_running_age', "SELECT job_id, owner, kind, status, %d-COALESCE(heartbeat_at,0) AS hb_age_s, %d-COALESCE(updated_at,0) AS upd_age_s FROM task_jobs WHERE status='running' ORDER BY updated_at DESC LIMIT 15" % (now, now))
    q('jobs_graphrag', "SELECT job_id, coalesce_key, status, reason_code, updated_at FROM task_jobs WHERE kind='graphrag_rebuild' ORDER BY created_at DESC LIMIT 10")

# ---- B10-R11: Direct L1 signals ----
if 'mca_events' in T:
    q('b11_l1_plan', "SELECT COUNT(*) AS n, MIN(ts), MAX(ts) FROM mca_events WHERE event_name='L1_PLAN'")
    q('b11_l1_dist', "SELECT json_extract(usage_json,'$.response_act') AS act, json_extract(usage_json,'$.extent') AS extent, "
                     "json_extract(usage_json,'$.fallback') AS fb, COUNT(*) AS n FROM mca_events "
                     "WHERE event_name='L1_PLAN' AND ts>=? GROUP BY 1,2,3 ORDER BY n DESC LIMIT 25", (now-7*86400,))
    q('b11_l1_latency', "SELECT COUNT(*) AS n, ROUND(AVG(json_extract(usage_json,'$.latency_ms')),1) AS avg_ms, "
                        "MAX(json_extract(usage_json,'$.latency_ms')) AS max_ms FROM mca_events "
                        "WHERE event_name='L1_PLAN' AND ts>=? AND json_extract(usage_json,'$.latency_ms') IS NOT NULL", (now-7*86400,))
    q('b11_l1_rejected', "SELECT json_extract(usage_json,'$.capability') AS cap, json_extract(usage_json,'$.reason') AS reason, COUNT(*) AS n "
                        "FROM mca_events WHERE event_name='L1_CAPABILITY_REJECTED' AND ts>=? GROUP BY 1,2 ORDER BY n DESC LIMIT 20", (now-7*86400,))
    q('b11_tool_events', "SELECT event_name, outcome, COUNT(*) AS n FROM mca_events WHERE event_name LIKE 'DIRECT%' AND ts>=? GROUP BY 1,2 ORDER BY n DESC LIMIT 30", (now-7*86400))
    q('b11_reason_codes', "SELECT reason_code, event_name, COUNT(*) AS n FROM mca_events WHERE ts>=? AND reason_code IS NOT NULL GROUP BY 1,2 ORDER BY n DESC LIMIT 30", (now-7*86400))

# ---- activity inputs ----
if 'smart_messages' in T:
    q('activity_messages_7d', "SELECT chat_id, COUNT(*) AS n, MAX(timestamp) AS last_ts FROM smart_messages WHERE timestamp>=? GROUP BY chat_id ORDER BY n DESC LIMIT 10", (now-7*86400,))
    q('activity_messages_total', "SELECT chat_id, COUNT(*) AS n, MAX(timestamp) AS last_ts FROM smart_messages GROUP BY chat_id ORDER BY n DESC LIMIT 10")
if 'summary_runs' in T:
    q('summary_runs_states', "SELECT state, COUNT(*) AS n FROM summary_runs GROUP BY state")
    q('summary_runs_recent', "SELECT run_id, chat_id, state, created_at, updated_at FROM summary_runs ORDER BY created_at DESC LIMIT 8")
con.close()
PYEOF

echo "===== S4 postgres read-only ====="
"$PYBIN" - <<'PYEOF2' 2>&1
import asyncio, json, os
dsn = None
try:
    for line in open('.env', encoding='utf-8', errors='replace'):
        if line.startswith('POSTGRES_DSN='):
            dsn = line.split('=', 1)[1].strip().strip('"').strip("'")
except Exception as e:
    print('PG_ENV_ERR', type(e).__name__)
print('PG_DSN_PRESENT', bool(dsn))
if not dsn:
    raise SystemExit(0)
import asyncpg

async def main():
    con = await asyncpg.connect(dsn, timeout=12)
    try:
        async def q(label, sql, *args):
            try:
                rows = await con.fetch(sql, *args)
            except Exception as e:
                print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, str(e)[:200])); return
            print('--- %s (n=%d) ---' % (label, len(rows)))
            for r in rows[:30]:
                print(dict(r))
            if len(rows) > 30:
                print('...(%d more)' % (len(rows)-30))
        await q('pg_chat_profiles', "SELECT chat_id, updated_at FROM chat_profiles ORDER BY chat_id")
        await q('pg_chat_keys', "SELECT chat_id, key, updated_at FROM chat_keys ORDER BY chat_id, key")
        await q('pg_chat_admins', "SELECT chat_id, COUNT(*) AS n FROM chat_admins GROUP BY chat_id ORDER BY chat_id")
        await q('pg_roles', "SELECT chat_id, user_id, role FROM bot_roles ORDER BY chat_id LIMIT 40")
        await q('pg_chat_usage', "SELECT chat_id, updated_at FROM chat_usage ORDER BY chat_id")
        await q('pg_uptime_last', "SELECT ts, status FROM uptime_events ORDER BY ts DESC LIMIT 5")
        await q('pg_activity', "SELECT state, COUNT(*) AS n FROM pg_stat_activity GROUP BY state")
    finally:
        await con.close()

asyncio.run(main())
PYEOF2

echo "===== S5 journal (read-only) ====="
J() { journalctl -u admin_bot "$@" --no-pager 2>/dev/null; }
JS() { sudoc journalctl -u admin_bot "$@" --no-pager 2>/dev/null; }
if J -n 1 >/dev/null 2>&1; then JC="journal"; else JC="sudo"; fi
echo "JOURNAL_MODE=$JC"
if [ "$JC" = "journal" ]; then RUNJ() { J "$@"; }; else RUNJ() { JS "$@"; }; fi
since=$(date -d '-48 hours' '+%Y-%m-%d %H:%M:%S')
echo "SINCE=$since"
echo "JLINES_48H=$(RUNJ --since "$since" | wc -l)"
echo "ERR_48H=$(RUNJ --since "$since" | grep -cE ' ERROR | CRITICAL |Traceback')"
echo "WARN_48H=$(RUNJ --since "$since" | grep -cE ' WARNING ')"
echo "--- journal error tails ---"
RUNJ --since "$since" | grep -E ' ERROR | CRITICAL |Traceback' | tail -n 25
echo "--- embedding/quota lines 7d (counts) ---"
since7=$(date -d '-7 days' '+%Y-%m-%d %H:%M:%S')
RUNJ --since "$since7" | grep -icE 'EmbeddingGroupCoolingDown|EMBED_API_DEFERRED|quota' | sed 's/^/EMB_QUOTA_LINES=/'
RUNJ --since "$since7" | grep -iE 'EmbeddingGroupCoolingDown|EMBED_API_DEFERRED|quota' | tail -n 12
echo "--- rate limit / 429 7d ---"
RUNJ --since "$since7" | grep -icE '429|rate.?limit|cooldown' | sed 's/^/RATELIMIT_LINES=/'
RUNJ --since "$since7" | grep -iE '429|rate.?limit|cooldown' | tail -n 10
echo "--- injected core tokens (composer detail) 7d ---"
RUNJ --since "$since7" | grep -c 'core_tokens=' | sed 's/^/CORE_TOKEN_LINES=/'
RUNJ --since "$since7" | grep -oE 'core_tokens=[0-9]+ budget=[0-9]+' | tail -n 10
echo "--- L1 / direct markers 7d ---"
RUNJ --since "$since7" | grep -icE '\[l1\]|l1_plan|policy_not_injected|L1 truncated' | sed 's/^/L1_LINES=/'
RUNJ --since "$since7" | grep -iE '\[l1\]|l1_plan|policy_not_injected|L1 truncated' | tail -n 12
echo "--- summary/graphrag/vector 48h ---"
RUNJ --since "$since" | grep -iE 'graphrag|vector|embed|summary' | tail -n 15

echo "===== S6 B11 mechanisms report (read-only tool) ====="
PY="$PYBIN"
if [ ! -x "$PY" ]; then PY=$(command -v python3); fi
DSN=$(grep -E '^POSTGRES_DSN=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
POSTGRES_DSN="$DSN" "$PY" tools/v63_b11_mechanisms_report.py --db "$DBP" 2>&1
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
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "main.txt").write_text(text, encoding="utf-8")
        print(text[-3000:])
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
