# -*- coding: utf-8 -*-
"""Runner ACCEPTANCE-95e: one tiny read-only journal probe — classify the
95c-window traceback (14:17:06Z) and re-verify the final service state.

Usage: py -3 run_accept95e.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH"
             r"\acceptance-95")
LOG = LOCAL / "logs" / "accept95e-run.log"
RECONNECT_WAIT_S = 95


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    text = re.sub(r"https://[^@\s/]+@", "https://***@", text)
    return text


def main() -> int:
    pw = _pwd()
    lines: list[str] = []

    def emit(s: str) -> None:
        s = scrub(s, [pw])
        print(s, flush=True)
        lines.append(s)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                  auth_timeout=30, allow_agent=False, look_for_keys=False)
        emit("[runner] connected")

        def sudo(cmd: str, timeout: float = 180.0):
            _in, out, err = c.exec_command("sudo -S " + cmd, timeout=timeout)
            try:
                _in.write(pw + "\n")
                _in.flush()
            except Exception:
                pass
            o = out.read().decode("utf-8", "replace")
            e = err.read().decode("utf-8", "replace")
            out.channel.recv_exit_status()
            return scrub(o, [pw]), scrub(e, [pw])

        emit("=== 95C TRACEBACK CONTEXT (14:16:50-14:17:40Z) ===")
        o, e = sudo("journalctl -u admin_bot --since '2026-10-19 14:16:50' "
                    "--until '2026-10-19 14:17:40' --no-pager | tail -n 60")
        emit(o.rstrip())
        emit("=== 95C FULL WINDOW ERR/CRIT (14:14:30-14:19:30Z) ===")
        o, e = sudo("journalctl -u admin_bot --since '2026-10-19 14:14:30' "
                    "--until '2026-10-19 14:19:30' --no-pager | "
                    "grep -cE 'ERROR|CRITICAL|Traceback'")
        emit("95C_ERR_COUNT=" + o.strip())
        o, e = sudo("journalctl -u admin_bot --since '2026-10-19 14:14:30' "
                    "--until '2026-10-19 14:19:30' --no-pager | "
                    "grep -E 'ERROR|CRITICAL|Traceback' | head -12")
        emit(o.rstrip())
        emit("=== FINAL STATE ===")
        o, e = sudo("systemctl show admin_bot -p MainPID -p NRestarts "
                    "-p ActiveState -p SubState -p ExecMainStatus --no-pager")
        emit(o.rstrip())
        o, e = sudo("curl -s http://127.0.0.1:8000/healthz; echo; "
                    "curl -s https://admin-bot.duckdns.org/healthz; echo; "
                    "date -u '+%Y-%m-%d %H:%M:%S UTC'")
        emit(o.rstrip())
        return 0
    finally:
        try:
            c.close()
        except Exception:
            pass
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print("RUNNER_EXCEPTION:", "%s: %s" % (type(exc).__name__, exc))
        sys.exit(4)
