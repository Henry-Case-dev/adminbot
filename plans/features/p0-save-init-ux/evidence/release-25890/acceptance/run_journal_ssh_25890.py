# -*- coding: utf-8 -*-
"""ACCEPTANCE-90 — журнальная фаза: один SSH-коннект, read-only.

Дисциплина fail2ban (AGENTS.md): ровно ОДИН коннект на фазу, один логин,
без ретраев после неудачного auth, без фоновых поллеров; креды читаются из
локального `deploy_commands.txt` и вычищаются из вывода.

Что делает:
  1) SFTP-загрузка `probe_journal_25890.sh` в /tmp;
  2) `sudo -S sh /tmp/acc90_journal.sh "<T0>"` — read-only journalctl + sqlite;
  3) сохранение вывода в этот же каталог (`journal-25890.txt`), а разобранного
     JSON-блока — в `journal-25890.json`.

Запуск:
    python run_journal_ssh_25890.py            # T0 по умолчанию (деплой 2.58.90)
    python run_journal_ssh_25890.py "2026-10-18 13:34:23"
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "198.46.175.136"
PORT = 22
USER = "nik"
DEPLOY_TXT = r"C:\Code\Python\adminbot\deploy_commands.txt"
T0 = sys.argv[1] if len(sys.argv) > 1 else "2026-10-18 13:34:23"
REMOTE = "/tmp/acc90_journal.sh"
LOCAL = os.path.join(HERE, "probe_journal_25890.sh")
LOG = os.path.join(HERE, "journal-25890.txt")
JSON_OUT = os.path.join(HERE, "journal-25890.json")
SECRETS: list[str] = []


def load_secrets() -> tuple[str, str]:
    txt = io.open(DEPLOY_TXT, encoding="utf-8").read()
    pw = re.search(r"^pass:\s*(\S+)", txt, re.M).group(1)
    gp = re.search(r"^pass_gti_pull:\s*(\S+)", txt, re.M).group(1)
    return pw, gp


def scrub(text: str) -> str:
    for secret in SECRETS:
        if secret:
            text = text.replace(secret, "***")
    return text


def main() -> int:
    pw, gp = load_secrets()
    SECRETS.extend([pw, gp])
    started = time.time()
    lines: list[str] = []

    def log(text: str) -> None:
        text = scrub(text)
        lines.append(text)
        print(text, flush=True)

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(HOST, port=PORT, username=USER, password=pw, timeout=25,
                    banner_timeout=25, auth_timeout=30)
    except Exception as exc:                                  # noqa: BLE001
        print("CONNECT_FAILED %s: %s" % (type(exc).__name__,
                                         scrub(str(exc))[:200]))
        return 2
    try:
        log("[acc90] connected, one-shot read-only journal phase")
        sftp = cli.open_sftp()
        try:
            with io.open(LOCAL, "rb") as fh:
                sftp.putfo(fh, REMOTE)
        finally:
            sftp.close()
        cmd = ("SUDO90='%s' sh -c 'printf \"%%s\\n\" \"$SUDO90\" | sudo -S "
               "sh %s \"%s\" 2>&1'" % (pw, REMOTE, T0))
        stdin, stdout, stderr = cli.exec_command(cmd, timeout=600)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        log(out.rstrip())
        if err.strip():
            log("[stderr] " + err.strip())
        log("[acc90] rc=%d elapsed=%.1fs" % (rc, time.time() - started))
    finally:
        cli.close()

    with io.open(LOG, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    payload = None
    for line in lines:
        if line.startswith("MCA90_JSON "):
            try:
                payload = json.loads(line[len("MCA90_JSON "):])
            except ValueError:
                payload = None
    if payload is not None:
        with io.open(JSON_OUT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("[acc90] saved -> %s%s" % (LOG, " + journal-25890.json"
                                     if payload else " (json not parsed)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
