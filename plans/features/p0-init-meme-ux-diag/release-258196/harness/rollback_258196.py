# -*- coding: utf-8 -*-
"""Rollback 2.58.196 -> 2.58.195 (c134f93d) after a failed mandatory live check.

One SSH login. No data rollback (schema 47, DDL=0).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

APP = "/var/www/admin_bot"
PUBLIC = "https://admin-bot.duckdns.org"
KEY = Path.home() / ".ssh" / "adminbot_vps"
BASE = "c134f93d5c4a68f0ea906498cb9e0b78fc795f1e"
VER = "2.58.195"


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.255.209.205", port=22, username="root",
                   pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY)),
                   look_for_keys=False, allow_agent=False,
                   timeout=15, banner_timeout=15, auth_timeout=15)
    log = []

    def run(cmd: str, timeout: int = 180) -> str:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        stdout.channel.recv_exit_status()
        text = out + (("\n[stderr]\n" + err) if err.strip() else "")
        log.append(text.rstrip())
        return text

    try:
        log.append("=== before ===")
        run("cd %s && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && "
            "git status --porcelain --untracked-files=no | wc -l" % APP)
        run("curl -s --max-time 15 %s/healthz" % PUBLIC)
        log.append("=== checkout rollback target ===")
        run("cd %s && git cat-file -e %s && echo BASE_PRESENT" % (APP, BASE))
        run("cd %s && git merge-base --is-ancestor %s HEAD && echo BASE_IS_ANCESTOR" % (APP, BASE))
        run("cd %s && git checkout -B release/2.58.195 %s 2>&1 | tail -3" % (APP, BASE))
        run("cd %s && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && "
            "git status --porcelain --untracked-files=no | wc -l" % APP)
        log.append("=== restart ===")
        run('date -u "+%Y-%m-%dT%H:%M:%SZ"')
        run("systemctl restart admin_bot")
        time.sleep(7)
        run("systemctl is-active admin_bot; systemctl show admin_bot -p NRestarts --value; "
            "systemctl show admin_bot -p ActiveEnterTimestamp --value")
        ok = False
        for attempt in range(1, 8):
            out = run("curl -s --max-time 15 %s/healthz" % PUBLIC)
            log.append("healthz attempt %d: %s" % (attempt, out.strip()))
            if VER in out and '"status":"ok"' in out:
                ok = True
                break
            time.sleep(2)
        log.append("=== post ===")
        run("cd %s && python3 - <<'PY'\n"
            "import sqlite3\n"
            "c = sqlite3.connect('file:local_database.db?mode=ro', uri=True)\n"
            "print('LIVE_USER_VERSION=%%d' %% c.execute('PRAGMA user_version').fetchone()[0])\n"
            "PY" % APP)
        run("journalctl -u admin_bot --since '-8 min' --no-pager -o cat 2>/dev/null | "
            "awk 'BEGIN{tb=0;er=0;cr=0;lost=0} /Traceback/{tb++} /ERROR/{er++} "
            "/CRITICAL/{cr++} /attempt LOST/{lost++} "
            "END{printf \"TB=%d ERR=%d CRIT=%d LOST=%d\\n\",tb,er,cr,lost}'")
        run('date -u "+%Y-%m-%dT%H:%M:%SZ"')
        log.append("ROLLBACK_OK=%s" % ok)
    finally:
        client.close()
    text = "\n".join(log)
    Path(sys.argv[1]).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
