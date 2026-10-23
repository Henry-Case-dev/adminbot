# -*- coding: utf-8 -*-
"""LANE SUMMARY-PROD-TRIAGE — probe #2 (read-only, 1 SSH connection).

Focus: the 5 FAILED runs (why exactly), publication/legacy outcomes,
durable trace availability for reviewer finding codes, resume-ticker evidence.

Usage: py -3 probe2_summary.py
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

FAILED = [
    "da33f05db7754a38bdea7d591cf6eccc",
    "9aea8508552e491aa91511dadff58258",
    "b61e74b53c034f7c83b8d4e891a399a3",
    "cff5c18e4e174010837f61a64404a548",
    "718e9ea64810446399970ed4ea01a2f1",
]


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
    text = re.sub(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", "***BOT_TOKEN***", text)
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
export FIDS="__IDS__"

echo "===== P1 sqlite: failed runs trace ====="
"$PYBIN" - <<'PYEOF' 2>&1
import ast, json, os, sqlite3
ids = ast.literal_eval(os.environ['FIDS'])
con = sqlite3.connect('file:%s?mode=ro' % os.environ['DBP'], uri=True, timeout=30)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
ph = ','.join('?' * len(ids))


def show(label, sql, params=(), cap=600):
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        print('--- %s --- ERROR %s: %s' % (label, type(e).__name__, e))
        return
    print('--- %s (n=%d) ---' % (label, len(rows)))
    for r in rows:
        d = {}
        for k, v in dict(r).items():
            if isinstance(v, str) and len(v) > cap:
                v = v[:cap] + '..[cut]'
            d[k] = v
        print(d)


show('runs_by_chat',
     "SELECT chat_id, state, COUNT(*) n, MIN(created_at) mn, MAX(created_at) mx "
     "FROM summary_runs GROUP BY 1,2 ORDER BY n DESC")
show('failed_events',
     "SELECT ts, event_name, stage, outcome, reason_code, status, error_json, "
     "usage_json FROM mca_events WHERE pipeline_run_id IN (%s) "
     "ORDER BY ts, id" % ph, tuple(ids), cap=430)
show('text_ready',
     "SELECT ts, event_name, stage, outcome, status, usage_json FROM mca_events "
     "WHERE event_name='SUMMARY_TEXT_READY' AND pipeline_run_id IN (%s) "
     "ORDER BY ts" % ph, tuple(ids), cap=300)
show('runs_rows',
     "SELECT run_id, state, publication_status, publication_result_ref, "
     "pipeline_health, created_at, updated_at, source_ref FROM summary_runs "
     "WHERE run_id IN (%s) ORDER BY created_at" % ph, tuple(ids))

try:
    cols = [r[1] for r in con.execute("PRAGMA table_info(mca_pipeline_runs)")]
    print('mca_pipeline_runs_cols=', cols)
    key = ('pipeline_run_id' if 'pipeline_run_id' in cols
           else ('run_id' if 'run_id' in cols else None))
    if key:
        rows = con.execute(
            "SELECT %s AS rid, status, report_json FROM mca_pipeline_runs "
            "WHERE %s IN (%s) ORDER BY rowid DESC LIMIT 3" % (key, key, ph),
            tuple(ids)).fetchall()
        print('--- pipeline_runs (n=%d) ---' % len(rows))
        for r in rows:
            d = dict(r)
            txt = str(d.get('report_json') or '')
            print({'rid': d['rid'], 'status': d['status'],
                   'report_len': len(txt),
                   'has_finding_codes': 'finding_codes' in txt,
                   'has_verdict': '"verdict"' in txt,
                   'head': txt[:300]})
    else:
        print('pipeline_runs: no run-id column')
except Exception as e:
    print('pipeline_runs ERROR %s: %s' % (type(e).__name__, e))
con.close()
PYEOF

echo "===== P2 journal: the 5 failed runs ====="
journalctl -u admin_bot --since "2026-10-16 12:00:00" --no-pager -o cat 2>/dev/null \
  | grep -E 'da33f05d|9aea8508|b61e74b5|cff5c18e|718e9ea6' \
  | grep -vE 'mca_event=|SUMMARY_(L1_ACTIVITY|WRITER_ACTIVITY|LLM_SUPERVISOR|CAPACITY|EXECUTION_MODE|SOURCE_WINDOW|RUN_START|SEGMENT)' \
  | tail -n 260

echo "===== P3 resume ticker ====="
echo "TICKS=$(journalctl -u admin_bot --since '2026-10-20 00:00:00' --no-pager -o cat 2>/dev/null | grep -c 'graphrag rebuild: resume tick')"
journalctl -u admin_bot --since '2026-10-22 00:00:00' --no-pager -o cat 2>/dev/null \
  | grep -E 'graphrag rebuild: (resume tick|resume ticker started)|EMBEDDING_GENERATION_PAUSED' \
  | tail -n 12
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
            "bash -s", timeout=420, get_pty=False)
        stdin.write(SCRIPT.replace("__IDS__", repr(FAILED)))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
    finally:
        client.close()

    text = scrub(out + "\n===STDERR===\n" + err, [secret, _pwd("pass_gti_pull")])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "failed_runs_probe.txt").write_text(text, encoding="utf-8")
    print(text[:1500])
    print("...\n[bytes=%d] -> %s" % (len(text), OUT / "failed_runs_probe.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
