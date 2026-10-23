# -*- coding: utf-8 -*-
"""DEVOPS-PROD-CHECKS follow-up (connection #3): targeted read-only queries.

Resolves leftovers from batch #1:
  * vec-extension index size / backlog (B10-R06)
  * embedding generation progress events + deferred/failed per day
  * humor feedback signals (fact_correction / wrong_addressee) for SOUL-14.2
  * repetition counts, L1 persistence, DIRECT tool/mode evidence (B10-R11)
  * retrieval isolation proxy per chat (B10-R10)
  * journal detail for Summary FAILED run + 06:20 DB incident (anomalies)

Read-only. Usage: py -3 probe2.py main
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


def connect(pw: str) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, pw, timeout=20, banner_timeout=20,
              auth_timeout=20, allow_agent=False, look_for_keys=False)
    return c


SCRIPT = r"""
set +e
export LC_ALL=C
cd /var/www/admin_bot || exit 3
echo "DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PYBIN=venv/bin/python
[ -x "$PYBIN" ] || PYBIN=.venv/bin/python
echo "PYBIN=$PYBIN"
DBP=$(grep -E '^DB_PATH=' .env | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
[ -z "$DBP" ] && DBP=local_database.db
export DBP

echo "===== T1 sqlite + vec extension ====="
"$PYBIN" - <<'PYEOF' 2>&1
import glob, json, os, sqlite3, time
dbp = os.environ['DBP']
now = int(time.time())
con = sqlite3.connect('file:%s?mode=ro' % dbp, uri=True, timeout=20)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
T = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type in ('table','view')")}

def q(label, sql, params=(), limit=30):
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

def one(label, sql, params=()):
    r = q(label, sql, params)
    return r[0] if r else None

# --- vec extension ---
loaded = None
cands = sorted(set(glob.glob('venv/**/vec0*.so', recursive=True)
                   + glob.glob('.venv/**/vec0*.so', recursive=True)
                   + glob.glob('venv/**/*vec*.so', recursive=True)))
print('VEC_SO_CANDIDATES', [c[-70:] for c in cands][:6])
try:
    con.enable_load_extension(True)
except Exception as e:
    print('VEC_ENABLE_FAIL', type(e).__name__, e)
for c in cands:
    try:
        con.load_extension(c)
        loaded = c
        print('VEC_LOADED', c[-70:])
        break
    except Exception as e:
        print('VEC_LOAD_TRY_FAIL', c[-50:], type(e).__name__, str(e)[:80])
print('VEC_LOADED_FINAL', bool(loaded))
if loaded:
    for t in ('graph_facts_vec', 'smart_archive'):
        if t in T:
            one('vec_count_' + t, "SELECT COUNT(*) FROM %s" % t)
    one('backlog_archive', "SELECT COUNT(*) FROM smart_archive_facts WHERE id NOT IN (SELECT fact_id FROM smart_archive)")
    one('backlog_graph', "SELECT COUNT(*) FROM graph_facts WHERE id NOT IN (SELECT fact_id FROM graph_facts_vec) AND (expires_at IS NULL OR expires_at > %d)" % now)
    q('vec_by_chat_graph', "SELECT chat_id, COUNT(*) AS n FROM graph_facts_vec GROUP BY chat_id ORDER BY n DESC LIMIT 8")
else:
    print('VEC_TABLES_UNREADABLE_WITHOUT_EXTENSION')

one('has_chat_migration_backup', "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='chat_migration_backup'")
one('chat_migration_backup_rows', "SELECT COUNT(*) FROM chat_migration_backup") if 'chat_migration_backup' in T else print('chat_migration_backup: ABSENT')

# --- embedding generation progress ---
q('embed_gen_events', "SELECT event_name, outcome, COUNT(*) AS n, MAX(ts) AS last_ts FROM mca_events WHERE event_name LIKE 'EMBEDDING_GENERATION%' GROUP BY 1,2 ORDER BY last_ts DESC LIMIT 15")
q('embed_gen_samples', "SELECT ts, event_name, outcome, chat_id, usage_json FROM mca_events WHERE event_name LIKE 'EMBEDDING_GENERATION%' ORDER BY ts DESC LIMIT 4")
q('embed_deferred_by_day', "SELECT date(ts,'unixepoch') AS d, COUNT(*) AS n FROM mca_events WHERE event_name='EMBED_API_DEFERRED' AND ts>=%d GROUP BY d ORDER BY d DESC LIMIT 12" % (now-14*86400))
q('embed_failed', "SELECT event_name, outcome, reason_code, COUNT(*) AS n, MAX(ts) FROM mca_events WHERE event_name LIKE 'EMBED%FAIL%' GROUP BY 1,2,3 ORDER BY n DESC LIMIT 12")
q('embed_api_events_7d', "SELECT event_name, outcome, COUNT(*) AS n, MAX(ts) AS last_ts FROM mca_events WHERE event_name LIKE 'EMBED%' AND ts>=%d GROUP BY 1,2 ORDER BY n DESC LIMIT 15" % (now-7*86400))

# --- SOUL-14.2 extra: feedback signals + repetition + one_word over 30d ---
q('feedback_signals_30d', "SELECT json_extract(signal_json,'$.domain') AS domain, json_extract(signal_json,'$.signal') AS signal, COUNT(*) AS n FROM mca_experience_feedback WHERE ts>=%d GROUP BY 1,2 ORDER BY n DESC LIMIT 20" % (now-30*86400))
q('feedback_sources_30d', "SELECT source_kind, authority, reliability, COUNT(*) AS n FROM mca_experience_feedback WHERE ts>=%d GROUP BY 1,2,3 ORDER BY n DESC LIMIT 12" % (now-30*86400))
q('style_repetition_30d', "SELECT COUNT(*) AS n FROM mca_events WHERE event_name='style_policy' AND json_array_length(json_extract(usage_json,'$.repetition'))>0 AND ts>=%d" % (now-30*86400))
q('style_payload_mismatch_30d', "SELECT COUNT(*) AS n FROM mca_events WHERE event_name='style_policy' AND json_extract(usage_json,'$.payload_status')='mismatch' AND ts>=%d" % (now-30*86400))
q('speech_extent_oneword_30d', "SELECT COUNT(*) AS n, SUM(CASE WHEN json_extract(usage_json,'$.one_word_exact')=1 THEN 1 ELSE 0 END) AS exact FROM mca_events WHERE event_name='speech_extent' AND json_extract(usage_json,'$.extent')='one_word' AND ts>=%d" % (now-30*86400))
q('speech_extent_words_all', "SELECT json_extract(usage_json,'$.extent') AS extent, json_extract(usage_json,'$.words') AS words, COUNT(*) AS n FROM mca_events WHERE event_name='speech_extent' GROUP BY 1,2 ORDER BY n DESC LIMIT 15")
q('direct_events_7d', "SELECT event_name, outcome, COUNT(*) AS n, MAX(ts) FROM mca_events WHERE event_name LIKE 'DIRECT%' AND ts>=%d GROUP BY 1,2 ORDER BY n DESC LIMIT 25" % (now-7*86400))
q('direct_fresh_samples', "SELECT ts, chat_id, usage_json FROM mca_events WHERE event_name='DIRECT_FRESH_GENERATION' ORDER BY ts DESC LIMIT 3")
q('tool_events_7d', "SELECT event_name, outcome, COUNT(*) AS n FROM mca_events WHERE event_name LIKE '%%TOOL%%' AND ts>=%d GROUP BY 1,2 ORDER BY n DESC LIMIT 20" % (now-7*86400))
BT = [r[1] for r in con.execute("PRAGMA table_info(bot_replies)")]
print('BOT_REPLIES_HAS_L1', [c for c in BT if 'l1' in c.lower() or 'plan' in c.lower()])
if any('l1' in c.lower() for c in BT):
    cols = [c for c in BT if 'l1' in c.lower()]
    one('bot_replies_l1_nonnull', "SELECT COUNT(*) FROM bot_replies WHERE %s IS NOT NULL" % (' OR '.join('%s IS NOT NULL' % c for c in cols)))

# --- B10-R10 retrieval proxy ---
q('retrieval_30d', "SELECT chat_id, outcome, reason_code, COUNT(*) AS n, MAX(ts) FROM mca_events WHERE event_name='mca07_retrieval' AND ts>=%d GROUP BY 1,2,3 ORDER BY n DESC LIMIT 15" % (now-30*86400))
q('retrieval_samples', "SELECT ts, chat_id, outcome, reason_code, usage_json FROM mca_events WHERE event_name='mca07_retrieval' ORDER BY ts DESC LIMIT 4")
q('graph_facts_per_chat', "SELECT chat_id, COUNT(*) AS n, MAX(created_at) FROM graph_facts GROUP BY chat_id ORDER BY n DESC LIMIT 8")

# --- summary failure context ---
q('summary_runs_detail', "SELECT run_id, chat_id, state, publication_status, pipeline_health, created_at, updated_at FROM summary_runs ORDER BY created_at DESC LIMIT 6")
q('summary_stages_failed', "SELECT run_id, stage, status, attempt, reason_code, started_at, finished_at FROM summary_run_stages WHERE status NOT IN ('done','skipped') ORDER BY id DESC LIMIT 8") if 'summary_run_stages' in T else None
q('incidents', "SELECT incident_id, fingerprint, process_id, pipeline_type, stage, severity, title, first_ts, last_ts, repeat_count, impact, fallback_used, resolved_at FROM mca_incidents ORDER BY created_at DESC LIMIT 4") if 'mca_incidents' in T else print('mca_incidents ABSENT')
con.close()
PYEOF

echo "===== T2 journal: summary failure window ====="
journalctl -u admin_bot --since '2026-10-22 12:55:00' --until '2026-10-22 13:17:00' --no-pager 2>/dev/null \
  | grep -iE 'summary|publish|ERROR|WARN|Traceback|incident' | tail -n 60
echo "===== T3 journal: 06:18-06:22 DB incident ====="
journalctl -u admin_bot --since '2026-10-22 06:18:00' --until '2026-10-22 06:23:00' --no-pager 2>/dev/null \
  | grep -iE 'ERROR|CRITICAL|Traceback|unrecoverable|locked|disk|sqlite' | tail -n 40
echo "===== T4 journal: embedding failures 3d ====="
journalctl -u admin_bot --since '2026-10-19 16:00:00' --no-pager 2>/dev/null \
  | grep -iE 'embed.*(fail|error|429|quota|exhaust|cooldown)|EMBED_API_FAILED' | tail -n 20

echo "===== T5 postgres: profiles/keys/admins ====="
"$PYBIN" - <<'PYEOF2' 2>&1
import asyncio, os
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
            for r in rows[:25]:
                print(dict(r))
        await q('pg_chat_keys_names', "SELECT chat_id, key_name, updated_at FROM chat_keys ORDER BY chat_id, key_name")
        await q('pg_admins', "SELECT telegram_id, role_name FROM bot_admins ORDER BY created_at")
        await q('pg_roles_count', "SELECT COUNT(*) AS n FROM bot_roles")
        await q('pg_profile_param_keys', "SELECT chat_id, jsonb_object_keys(chat_params) AS k FROM chat_profiles ORDER BY chat_id")
    finally:
        await con.close()

asyncio.run(main())
PYEOF2
echo "===== T6_DONE ====="
"""


def run_main(pw: str, secrets: list[str]) -> int:
    script = SCRIPT.replace("__APP__", APP)
    c = connect(pw)
    try:
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=600)
        stdin.write(script)
        stdin.channel.shutdown_write()
        data = stdout.read().decode("utf-8", "replace")
        e = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        text = scrub(data + ("\n[stderr]\n" + e if e.strip() else ""), secrets)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "main2.txt").write_text(text, encoding="utf-8")
        print(text[-2500:])
        print("\n[exit] rc=%s, bytes=%d" % (rc, len(text)))
    finally:
        c.close()
    return 0


def main() -> int:
    pw = _pwd("pass")
    secrets = [pw]
    try:
        secrets.append(_pwd("pass_gti_pull"))
    except SystemExit:
        pass
    return run_main(pw, secrets)


if __name__ == "__main__":
    sys.exit(main())
