# -*- coding: utf-8 -*-
"""DEPLOY 2.58.196: prod c134f93d (2.58.195) -> e8e2619b (release/2.58.196).

ONE SSH login (fail2ban discipline). Steps:
  A pre-state (HEAD/branch/tracked/version/unit/healthz/disk)
  B predeploy snapshot via sqlite backup API + read-back (integrity, uv, tables, sha256)
  C fetch + verify origin branch sha + fast-forward possible -> checkout -B
  D restart + is-active + NRestarts
  E healthz with bounded retries + version check
  F post-state: HEAD, branch, tracked, served app.js sha256 vs disk, live uv,
    journal counts (traceback/ERROR/CRITICAL/attempt LOST)
Rollback: c134f93d + restart if version/health fail.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import paramiko

APP = "/var/www/admin_bot"
PUBLIC = "https://admin-bot.duckdns.org"
KEY = Path.home() / ".ssh" / "adminbot_vps"
TARGET = "e8e2619b251dc6f01367975edf0bdef955d6c4a7"
PREV = "c134f93d5c4a68f0ea906498cb9e0b78fc795f1e"
VER_BEFORE = "2.58.195"
VER_AFTER = "2.58.196"
BRANCH = "release/2.58.196"


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.255.209.205", port=22, username="root",
                   pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY)),
                   look_for_keys=False, allow_agent=False,
                   timeout=15, banner_timeout=15, auth_timeout=15)
    log: list[str] = []

    def run(cmd: str, timeout: int = 300) -> tuple[int, str]:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        text = out + (("\n[stderr]\n" + err) if err.strip() else "")
        log.append(text.rstrip())
        return rc, text

    def section(name: str) -> None:
        log.append("\n=== %s ===" % name)

    status = "UNKNOWN"
    try:
        section("A pre-state")
        rc, out = run("cd %s && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && "
                      "git status --porcelain --untracked-files=no | head -5" % APP)
        log.append("tracked_dirty=%d" % len([l for l in out.strip().splitlines()[2:] if l.strip()]))
        if PREV not in out:
            log.append("ABORT: prod HEAD is not the expected 2.58.195 base")
            status = "ABORT_BASE"
            return 2
        rc, out = run(
            ("cd %s && python3 - <<'PY'\n" % APP) +
            "import re\n"
            "t = open('config/settings.py', encoding='utf-8').read()\n"
            "m = re.search(r'APP_VERSION = \"([0-9.]+)\"', t)\n"
            "print('APP_VERSION_ON_DISK=%s' % (m.group(1) if m else '?'))\n"
            "PY")
        log.append(out.strip())
        if VER_BEFORE not in out:
            log.append("ABORT: on-disk version is not %s" % VER_BEFORE)
            status = "ABORT_VERSION_BEFORE"
            return 2
        rc, out = run("systemctl is-active admin_bot; systemctl show admin_bot -p NRestarts --value; "
                      "systemctl show admin_bot -p ActiveEnterTimestamp --value; "
                      "systemctl show admin_bot -p MainPID --value")
        log.append(out.strip())
        rc, out = run("curl -s --max-time 15 %s/healthz; echo; df -h / | tail -1; "
                      "ls -la %s/local_database.db | awk '{print \"db_bytes=\"$5}'" % (PUBLIC, APP))
        log.append(out.strip())

        section("B predeploy snapshot")
        t0 = time.time()
        snap = r'''
import hashlib, os, sqlite3, time
ts = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
dst = 'backups/predeploy-258196-%s.db' % ts
src = sqlite3.connect('file:local_database.db?mode=ro', uri=True)
out = sqlite3.connect(dst)
src.backup(out)
out.close(); src.close()
chk = sqlite3.connect('file:%s?mode=ro' % dst, uri=True)
integrity = chk.execute('PRAGMA integrity_check').fetchone()[0]
uv = chk.execute('PRAGMA user_version').fetchone()[0]
tables = chk.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
chk.close()
h = hashlib.sha256()
with open(dst, 'rb') as f:
    for chunk in iter(lambda: f.read(1 << 20), b''):
        h.update(chunk)
print('BACKUP=%s' % dst)
print('BACKUP_BYTES=%d' % os.path.getsize(dst))
print('BACKUP_SHA256=%s' % h.hexdigest())
print('READBACK_INTEGRITY=%s' % integrity)
print('READBACK_USER_VERSION=%d' % uv)
print('READBACK_TABLES=%d' % tables)
'''
        rc, out = run("cd %s && python3 - <<'PY'\n%s\nPY" % (APP, snap), timeout=900)
        log.append(out.strip())
        log.append("snapshot_sec=%.1f" % (time.time() - t0))
        if "READBACK_INTEGRITY=ok" not in out or "BACKUP_SHA256=" not in out:
            log.append("ABORT: snapshot read-back failed; no restart")
            status = "ABORT_SNAPSHOT"
            return 3

        section("C fetch + fast-forward checkout")
        rc, out = run("cd %s && git fetch --prune origin 2>&1 | tail -3" % APP)
        log.append(out.strip())
        rc, out = run("cd %s && git rev-parse origin/%s" % (APP, BRANCH))
        log.append("origin_%s=%s" % (BRANCH.replace("/", "_"), out.strip()))
        if out.strip() != TARGET:
            log.append("ABORT: origin branch sha is not the release commit")
            status = "ABORT_REMOTE_SHA"
            return 4
        rc, out = run("cd %s && git cat-file -e %s && echo TARGET_PRESENT" % (APP, TARGET))
        log.append(out.strip())
        if "TARGET_PRESENT" not in out:
            status = "ABORT_NO_TARGET"
            return 4
        rc, out = run("cd %s && git merge-base --is-ancestor HEAD %s && echo FF_OK" % (APP, TARGET))
        log.append(out.strip())
        if "FF_OK" not in out:
            log.append("ABORT: not a fast-forward from the deployed HEAD")
            status = "ABORT_NOT_FF"
            return 4
        rc, out = run("cd %s && git checkout -B %s %s 2>&1 | tail -3" % (APP, BRANCH, TARGET))
        log.append(out.strip())
        rc, out = run("cd %s && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && "
                      "git status --porcelain --untracked-files=no | head -5" % APP)
        log.append(out.strip())
        if TARGET not in out:
            log.append("ABORT: HEAD != release commit; rolling back to %s" % PREV)
            run("cd %s && git checkout -B release/2.58.195 %s" % (APP, PREV))
            status = "ABORT_CHECKOUT"
            return 5
        rc, out = run(
            ("cd %s && python3 - <<'PY'\n" % APP) +
            "import re\n"
            "t = open('config/settings.py', encoding='utf-8').read()\n"
            "m = re.search(r'APP_VERSION = \"([0-9.]+)\"', t)\n"
            "print('APP_VERSION_ON_DISK=%s' % (m.group(1) if m else '?'))\n"
            "PY")
        log.append(out.strip())
        rc, out = run("cd %s && git rev-parse HEAD:web/app.js && "
                      "git cat-file -s HEAD:web/app.js" % APP)
        log.append("app_js_git=%s" % out.strip())

        section("D restart")
        rc, out = run('date -u "+%Y-%m-%dT%H:%M:%SZ"')
        log.append("restart_pre_utc=%s" % out.strip())
        run("systemctl restart admin_bot")
        time.sleep(7)
        rc, out = run("systemctl is-active admin_bot; systemctl show admin_bot -p NRestarts --value; "
                      "systemctl show admin_bot -p ActiveEnterTimestamp --value")
        log.append(out.strip())
        if "active" not in out:
            log.append("ROLLBACK: unit not active -> restore %s" % PREV)
            run("cd %s && git checkout -B release/2.58.195 %s && systemctl restart admin_bot"
                % (APP, PREV))
            time.sleep(6)
            rc, out = run("systemctl is-active admin_bot; curl -s --max-time 15 %s/healthz" % PUBLIC)
            log.append(out.strip())
            status = "ROLLED_BACK"
            return 6

        section("E healthz (bounded retries)")
        healthy = False
        for attempt in range(1, 11):
            rc, out = run("curl -s --max-time 15 %s/healthz" % PUBLIC)
            log.append("attempt %d: %s" % (attempt, out.strip()))
            if VER_AFTER in out and '"status":"ok"' in out:
                healthy = True
                break
            time.sleep(2)
        if not healthy:
            log.append("ROLLBACK: healthz did not report %s -> restore %s" % (VER_AFTER, PREV))
            run("cd %s && git checkout -B release/2.58.195 %s && systemctl restart admin_bot"
                % (APP, PREV))
            time.sleep(6)
            rc, out = run("curl -s --max-time 15 %s/healthz" % PUBLIC)
            log.append(out.strip())
            status = "ROLLED_BACK"
            return 7

        section("F post-state")
        rc, out = run("cd %s && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && "
                      "git status --porcelain --untracked-files=no | wc -l" % APP)
        log.append(out.strip())
        rc, out = run("cd %s && python3 - <<'PY'\n"
                      "import sqlite3\n"
                      "c = sqlite3.connect('file:local_database.db?mode=ro', uri=True)\n"
                      "print('LIVE_USER_VERSION=%%d' %% c.execute('PRAGMA user_version').fetchone()[0])\n"
                      "PY" % APP)
        log.append(out.strip())
        rc, out = run("curl -s --max-time 30 %s/app.js | sha256sum" % PUBLIC, timeout=120)
        log.append("served_app_js=%s" % out.strip())
        rc, out = run("cd %s && sha256sum web/app.js && stat -c %%s web/app.js" % APP)
        log.append("disk_app_js=%s" % out.strip())
        rc, out = run("journalctl -u admin_bot --since '-15 min' --no-pager -o cat 2>/dev/null | "
                      "awk 'BEGIN{tb=0;er=0;cr=0;wr=0;lost=0} /Traceback/{tb++} /ERROR/{er++} "
                      "/CRITICAL/{cr++} /WARNING/{wr++} /attempt LOST/{lost++} "
                      "END{printf \"TB=%d ERR=%d CRIT=%d WARN=%d LOST=%d\\n\",tb,er,cr,wr,lost}'")
        log.append(out.strip())
        rc, out = run("journalctl -u admin_bot --since '-15 min' --no-pager -o cat 2>/dev/null | wc -l")
        log.append("journal_lines=%s" % out.strip())
        rc, out = run('date -u "+%Y-%m-%dT%H:%M:%SZ"')
        log.append("now_utc=%s" % out.strip())
        status = "DONE"
    finally:
        client.close()

    text = "\n".join(log)
    Path(sys.argv[1]).write_text(text, encoding="utf-8")
    print(text)
    print("\nSTATUS=%s" % status)
    return 0 if status == "DONE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
