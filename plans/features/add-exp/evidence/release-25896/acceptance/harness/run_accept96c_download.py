# -*- coding: utf-8 -*-
"""ACCEPTANCE-96c — read-only download of the MAIN-run evidence (one session).

The follow-up runner wrote into the same local evidence dir and overwrote
summary/isolation/routes/restore/cleanup-register + live.out of the main run
(they are intact on prod under /tmp/accept96). This script re-downloads the
main-run artifacts into evidence/main/ (no product writes, no restarts).
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
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH"
             r"\acceptance-96")
OUTDIR = LOCAL / "evidence" / "main"
LOGDIR = LOCAL / "logs"


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

    OUTDIR.mkdir(parents=True, exist_ok=True)
    LOGDIR.mkdir(parents=True, exist_ok=True)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                  auth_timeout=30, allow_agent=False, look_for_keys=False)
        emit("[dl] connected")
        _in, out, err = c.exec_command(
            "date -u '+%Y-%m-%d %H:%M:%S UTC'; "
            "ls -la /tmp/accept96/evidence /tmp/accept96/*.out "
            "/tmp/accept96/*.txt /tmp/accept96b/*.out /tmp/accept96b/*.txt "
            "2>&1 | head -60",
            timeout=60)
        emit(out.read().decode("utf-8", "replace"))
        sftp = c.open_sftp()
        try:
            downloaded = []
            for name in sftp.listdir("/tmp/accept96/evidence"):
                try:
                    sftp.get("/tmp/accept96/evidence/" + name,
                             str(OUTDIR / name))
                    downloaded.append(name)
                except Exception as exc:  # noqa: BLE001
                    emit("[dl] %s failed %s" % (name, type(exc).__name__))
            for remote, local in (
                    ("/tmp/accept96/live.out", OUTDIR / "live.out"),
                    ("/tmp/accept96/journal.txt", OUTDIR / "journal.txt"),
                    ("/tmp/accept96b/live.out", LOCAL / "followup-live.out"),
                    ("/tmp/accept96b/journal.txt",
                     LOCAL / "followup-journal.txt")):
                try:
                    sftp.get(remote, str(local))
                    downloaded.append(str(local.name))
                except Exception as exc:  # noqa: BLE001
                    emit("[dl] %s failed %s" % (remote,
                                                type(exc).__name__))
            emit("[dl] downloaded: %s" % ", ".join(downloaded))
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
        (LOGDIR / "accept96c-download.log").write_text(
            "\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
