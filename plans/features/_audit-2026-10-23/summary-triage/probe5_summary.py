# -*- coding: utf-8 -*-
"""LANE SUMMARY-PROD-TRIAGE — probe #5 (read-only, 1 tiny SSH connection).

Only question left: was the service stopped at 2026-10-19 19:13:31Z, when
b61e74b5 ended without publishing?

Usage: py -3 probe5_summary.py
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

SCRIPT = r"""
set +e
export LC_ALL=C
echo "DATE_UTC=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "===== 10-19 19:13:15 .. 19:14:10 (all lines, filtered) ====="
journalctl -u admin_bot --since "2026-10-19 19:13:15" --until "2026-10-19 19:14:10" \
  --no-pager -o cat 2>/dev/null \
  | grep -vE 'VisionMediaWorker|apscheduler.executors.default|WATCHDOG_SWEEP|ingestion_live' \
  | head -n 40
echo "===== restart markers 10-19 18:00 .. 10-19 22:00 ====="
journalctl -u admin_bot --since "2026-10-19 18:00:00" --until "2026-10-19 22:00:00" \
  --no-pager -o short-iso 2>/dev/null \
  | grep -E 'Stopping admin_bot|Started admin_bot' | head -n 12
"""


def _pwd(pattern: str) -> str:
    m = re.search(rf"^{pattern}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{pattern}' not found")
    return m.group(1)


def main() -> int:
    secret = _pwd("pass")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=22, username=USER, password=secret,
                   timeout=25, banner_timeout=30, auth_timeout=30,
                   look_for_keys=False, allow_agent=False)
    try:
        stdin, stdout, stderr = client.exec_command(
            "bash -s", timeout=180, get_pty=False)
        stdin.write(SCRIPT)
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
    finally:
        client.close()
    text = out.replace(secret, "***")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b61_window.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
