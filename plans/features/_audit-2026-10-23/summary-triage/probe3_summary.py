# -*- coding: utf-8 -*-
"""LANE SUMMARY-PROD-TRIAGE — probe #3 (read-only, 1 SSH connection).

Question: why did 9aea8508 / b61e74b5 / cff5c18e end without publishing
(process restart? cancellation? cover watchdog?) — narrow journal windows
plus mca_incidents rows.

Usage: py -3 probe3_summary.py
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

echo "===== I1 incidents for the failed runs ====="
"$PYBIN" - <<'PYEOF' 2>&1
import os, sqlite3
ids = ['da33f05db7754a38bdea7d591cf6eccc',
       '9aea8508552e491aa91511dadff58258',
       'b61e74b53c034f7c83b8d4e891a399a3',
       'cff5c18e4e174010837f61a64404a548',
       '718e9ea64810446399970ed4ea01a2f1']
con = sqlite3.connect('file:%s?mode=ro' % os.environ['DBP'], uri=True, timeout=30)
con.row_factory = sqlite3.Row
con.execute('PRAGMA query_only=ON')
ph = ','.join('?' * len(ids))
try:
    cols = [r[1] for r in con.execute("PRAGMA table_info(mca_incidents)")]
    print('incident_cols=', cols)
    rows = con.execute(
        "SELECT * FROM mca_incidents WHERE pipeline_run_id IN (%s) "
        "OR operation_id IN (%s) ORDER BY first_ts" % (ph, ph),
        tuple(ids) + tuple(ids)).fetchall()
    print('--- incidents (n=%d) ---' % len(rows))
    for r in rows:
        d = {k: v for k, v in dict(r).items() if k in (
            'incident_id', 'pipeline_run_id', 'pipeline_type', 'stage',
            'severity', 'title', 'first_ts', 'last_ts', 'repeat_count',
            'impact', 'fallback_used', 'resolved_at', 'reason_code')}
        print(d)
except Exception as e:
    print('incidents ERROR %s: %s' % (type(e).__name__, e))
con.close()
PYEOF

echo "===== I2 journal windows (restart / cancel markers) ====="
for w in "2026-10-19 13:06:30 2026-10-19 13:09:00" \
         "2026-10-19 19:12:30 2026-10-19 19:14:30" \
         "2026-10-20 19:08:00 2026-10-20 19:10:30"; do
  set -- $w
  echo "----- window $1 .. $2 -----"
  journalctl -u admin_bot --since "$1" --until "$2" --no-pager -o cat 2>/dev/null \
    | grep -E 'Started|Stopping|Stopped|SIGTERM|Shutdown|shutdown|CancelledError|Cancelled|SUMMARY_INTERRUPTED|abort_in_flight|worker_lost|INCIDENT|Traceback|summary cover|cover:|Cancelled task' \
    | grep -vE 'TOOL_CALL|DIRECT_|mca07|speech|style_policy' \
    | head -n 40
done
echo "----- service restart history (systemd) -----"
journalctl -u admin_bot --since "2026-10-18 00:00:00" --no-pager -o cat 2>/dev/null \
  | grep -E ' Started | Stopping | Stopped | Deactivated successfully|systemd\[1\]: Started' \
  | tail -n 20
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
        stdin.write(SCRIPT)
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
    finally:
        client.close()

    text = scrub(out + "\n===STDERR===\n" + err, [secret, _pwd("pass_gti_pull")])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "silent_death_probe.txt").write_text(text, encoding="utf-8")
    print(text[:3000])
    print("...\n[bytes=%d] -> %s" % (len(text), OUT / "silent_death_probe.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
