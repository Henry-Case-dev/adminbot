# -*- coding: utf-8 -*-
"""ACCEPTANCE-96d runner — один SSH-сеанс: upload + run + download (cleanup)."""
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
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH"
             r"\acceptance-96")
SCRIPT = LOCAL / "accept96d_clean_quote.py"


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
    return text


def main() -> int:
    pw = _pwd()
    lines: list[str] = []

    def emit(s: str) -> None:
        s = scrub(s, [pw])
        print(s)
        lines.append(s)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                  auth_timeout=30, allow_agent=False, look_for_keys=False)
        emit("[d] connected")
        sftp = c.open_sftp()
        try:
            try:
                sftp.mkdir("/tmp/accept96d")
            except Exception:
                pass
            try:
                sftp.mkdir("/tmp/accept96d/evidence")
            except Exception:
                pass
            sftp.put(str(SCRIPT), "/tmp/accept96d_clean_quote.py")
            emit("[d] uploaded script")
        finally:
            sftp.close()
        _in, out, err = c.exec_command(
            "sudo -S sh -c 'cd %s && ./venv/bin/python "
            "/tmp/accept96d_clean_quote.py'" % APP, timeout=300)
        try:
            _in.write(pw + "\n")
            _in.flush()
        except Exception:
            pass
        emit(out.read().decode("utf-8", "replace"))
        e = err.read().decode("utf-8", "replace")
        if e.strip():
            emit("[stderr] " + e.strip()[:400])
        sftp = c.open_sftp()
        try:
            sftp.get("/tmp/accept96d/evidence/cleanup-quote.json",
                     str(LOCAL / "evidence" / "cleanup-quote.json"))
            emit("[d] downloaded cleanup-quote.json")
        finally:
            sftp.close()
        _in, out, err = c.exec_command(
            "curl -s http://127.0.0.1:8000/healthz; echo; "
            f"cd {APP} && echo HEAD=$(git rev-parse HEAD) "
            "TRACKED_MOD=$(git status --porcelain | grep -v '^??' | wc -l)",
            timeout=60)
        emit(out.read().decode("utf-8", "replace"))
        return 0
    finally:
        try:
            c.close()
        except Exception:
            pass
        (LOCAL / "logs" / "accept96d-run.log").write_text(
            "\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
