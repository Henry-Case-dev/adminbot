# -*- coding: utf-8 -*-
"""LANE SUMMARY-PROD-TRIAGE — probe #4 (read-only, 1 SSH connection).

Narrow journal windows for b61e74b5 (10-19 19:13Z) and cff5c18e (10-20 19:09Z):
did a service restart/cancel end the run before publish?

Usage: py -3 probe4_summary.py
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

echo "===== W1 2026-10-19 19:11:00 .. 19:14:30 ====="
journalctl -u admin_bot --since "2026-10-19 19:11:00" --until "2026-10-19 19:14:30" \
  --no-pager -o cat 2>/dev/null \
  | grep -vE 'mca_event=(SUMMARY_(L1_ACTIVITY|WRITER_ACTIVITY|LLM_SUPERVISOR|CAPACITY|EXECUTION_MODE|SOURCE_WINDOW|SEGMENT)|TOOL_|DIRECT_)' \
  | head -n 90

echo "===== W2 2026-10-20 19:07:30 .. 19:11:00 ====="
journalctl -u admin_bot --since "2026-10-20 19:07:30" --until "2026-10-20 19:11:00" \
  --no-pager -o cat 2>/dev/null \
  | grep -vE 'mca_event=(SUMMARY_(L1_ACTIVITY|WRITER_ACTIVITY|LLM_SUPERVISOR|CAPACITY|EXECUTION_MODE|SOURCE_WINDOW|SEGMENT)|TOOL_|DIRECT_)' \
  | head -n 90

echo "===== W3 restart markers 10-18..10-23 ====="
journalctl -u admin_bot --since "2026-10-18 00:00:00" --no-pager -o short-iso 2>/dev/null \
  | grep -E 'Stopping admin_bot|Started admin_bot|Deactivated successfully' \
  | tail -n 30
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
    (OUT / "windows_probe.txt").write_text(text, encoding="utf-8")
    print(text[:5000])
    print("...\n[bytes=%d] -> %s" % (len(text), OUT / "windows_probe.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
