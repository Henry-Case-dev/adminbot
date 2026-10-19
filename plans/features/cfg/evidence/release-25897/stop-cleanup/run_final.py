# -*- coding: utf-8 -*-
"""STOP-ACCEPTANCE-97 step 3 — one SSH login: run the read-only final check.

Single login per invocation; keep >= 90 s between invocations.
Credentials are read from deploy_commands.txt and never printed.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
APP = "/var/www/admin_bot"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\stop-accept-97")
REMOTE = "/tmp/cleanup_all"


def pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def main() -> int:
    pw = pwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                   auth_timeout=30, allow_agent=False, look_for_keys=False)
    log: list[str] = []

    def emit(s: str) -> None:
        print(s, flush=True)
        log.append(s)

    def run(cmd: str, timeout: float = 300.0):
        _in, out, err = client.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        return out.channel.recv_exit_status(), o, e

    def su(inner: str, timeout: float = 900.0):
        cmd = "printf '%%s\\n' %s | sudo -S sh -c %s" % (
            "'" + pw.replace("'", "'\"'\"'") + "'",
            "'" + inner.replace("'", "'\"'\"'") + "'")
        return run(cmd, timeout=timeout)

    try:
        rc, o, _e = run("date -u '+PRE_UTC %%Y-%%m-%%dT%%H:%%M:%%SZ'; "
                        "ps -eo pid,args --no-headers "
                        "| grep -Ei 'accept9[0-9][a-z_]*\\.py' "
                        "| grep -v -E 'grep|sshd' || echo 'HARNESS_NONE'")
        emit("### PRE rc=%s\n%s" % (rc, o.strip()))

        sftp = client.open_sftp()
        try:
            run("mkdir -p %s" % REMOTE)
            sftp.put(str(LOCAL / "stop97_final.py"),
                     REMOTE + "/stop97_final.py")
            emit("[upload] stop97_final.py")
            inner = ("cd %s && ./venv/bin/python %s/stop97_final.py"
                     % (APP, REMOTE))
            rc, o, e = su(inner, timeout=900)
            emit("### FINAL rc=%s" % rc)
            for line in o.splitlines():
                if line.startswith(("STOP97F ", "STOP97F_", "Traceback")):
                    emit(line[:800])
            if e.strip():
                emit("[stderr] " + e.strip()[:400])
            try:
                sftp.get(REMOTE + "/stop-final.json",
                         str(LOCAL / "stop-final.json"))
                emit("[download] stop-final.json")
            except Exception as exc:  # noqa: BLE001
                emit("[download] FAILED %s" % type(exc).__name__)
        finally:
            sftp.close()

        rc, o, _e = run(
            "date -u '+POST_UTC %%Y-%%m-%%dT%%H:%%M:%%SZ'; "
            "systemctl show admin_bot -p MainPID -p NRestarts -p ActiveState "
            "-p SubState --no-pager; "
            "curl -s -m 8 http://127.0.0.1:8000/healthz; echo; "
            "cd %s && echo HEAD=$(git rev-parse --short HEAD)" % APP,
            timeout=90)
        emit("### POST rc=%s\n%s" % (rc, o.strip()))
        return 0
    finally:
        client.close()
        (LOCAL / "stop-final.out").write_text("\n".join(log) + "\n",
                                              encoding="utf-8")


if __name__ == "__main__":
    t0 = time.time()
    try:
        rc = main()
    except Exception as exc:  # noqa: BLE001
        print("RUNNER_FATAL %s: %s" % (type(exc).__name__, str(exc)[:300]))
        rc = 5
    print("elapsed=%.1fs" % (time.time() - t0))
    sys.exit(rc)
