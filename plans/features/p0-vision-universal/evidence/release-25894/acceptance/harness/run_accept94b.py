# -*- coding: utf-8 -*-
"""ACCEPTANCE-94 follow-up runner (ONE SSH session).

Steps (all in a single connection):
  1. PRE (read-only).
  2. Upload accept94b_cover.py / accept94b_clean.py.
  3. JOURNAL-FIX: read-only journal wave with the correct T0 argument
     (the first run passed the version as a second arg -> journalctl could
     not parse the timestamp; all journal counters were invalid).
  4. COVER-FIX: cover isolation retry (unspent 1-cover budget) + restore.
  5. CLEANUP-FIX: residual DB rows of the wave's test mids + ERROR-event dump.
  6. Download c5-cover-fix.json / cleanup-register-2.json / cover94-base.png.

Usage: py -3 run_accept94b.py
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
T0 = "2026-10-19 08:18:20"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH"
             r"\acceptance-94")
FILES = {
    "accept94b_cover.py": "/tmp/accept94b_cover.py",
    "accept94b_clean.py": "/tmp/accept94b_clean.py",
}
LOG = LOCAL / "logs" / "accept94b-run.log"
EVID_LOCAL = LOCAL / "evidence"
RECONNECT_WAIT_S = 65


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


class Runner:
    def __init__(self, pw: str):
        self.pw = pw
        self.secrets = [pw]
        self.lines: list[str] = []
        self.client: paramiko.SSHClient | None = None

    def emit(self, s: str) -> None:
        for x in self.secrets:
            if x:
                s = s.replace(x, "***")
        s = re.sub(r"https://[^@\s/]+@", "https://***@", s)
        print(s)
        self.lines.append(s)

    def connect(self, wait_first: bool = False) -> None:
        if wait_first:
            self.emit("[runner] waiting %ds before reconnect (fail2ban)"
                      % RECONNECT_WAIT_S)
            time.sleep(RECONNECT_WAIT_S)
        self.close()
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, 22, USER, self.pw, timeout=30, banner_timeout=30,
                  auth_timeout=30, allow_agent=False, look_for_keys=False)
        self.client = c
        self.emit("[runner] connected %s@%s" % (USER, HOST))

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def run(self, cmd: str, timeout: float = 120.0) -> tuple[int, str, str]:
        assert self.client is not None
        _in, out, err = self.client.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        return rc, o, e

    def sudo_run(self, cmd: str, timeout: float = 900.0):
        assert self.client is not None
        _in, out, err = self.client.exec_command("sudo -S " + cmd,
                                                 timeout=timeout)
        try:
            _in.write(self.pw + "\n")
            _in.flush()
        except Exception:
            pass
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        return rc, o, e

    def step(self, name, fn, *args, retry=True, save=None, **kwargs):
        for attempt in (1, 2):
            try:
                rc, o, e = fn(*args, **kwargs)
                self.emit("### %s (rc=%s)" % (name, rc))
                if save is not None:
                    Path(save).write_text(o, encoding="utf-8", newline="\n")
                    self.emit("[saved] %s (%d bytes)" % (save, len(o)))
                else:
                    if o.strip():
                        self.emit(o.rstrip()[:12000])
                if e.strip():
                    self.emit("[stderr] " + e.strip()[:600])
                return rc, o, e
            except Exception as exc:  # noqa: BLE001
                self.emit("### %s FAILED attempt %d: %s: %s"
                          % (name, attempt, type(exc).__name__,
                             str(exc)[:200]))
                if attempt == 1 and retry:
                    self.connect(wait_first=True)
                    continue
                return -1, "", str(exc)
        return -1, "", "unreachable"

    def sftp_upload(self) -> None:
        assert self.client is not None
        sftp = self.client.open_sftp()
        try:
            for name, remote in FILES.items():
                sftp.put(str(LOCAL / name), remote)
                self.emit("[runner] uploaded %s (%d bytes)"
                          % (name, (LOCAL / name).stat().st_size))
        finally:
            sftp.close()

    def sftp_download(self, names) -> list[str]:
        assert self.client is not None
        sftp = self.client.open_sftp()
        got = []
        EVID_LOCAL.mkdir(parents=True, exist_ok=True)
        try:
            for name in names:
                try:
                    sftp.get("/tmp/accept94/evidence/" + name,
                             str(EVID_LOCAL / name))
                    got.append(name)
                except Exception as exc:  # noqa: BLE001
                    self.emit("[download] %s failed %s"
                              % (name, type(exc).__name__))
        finally:
            sftp.close()
        return got


def main() -> int:
    r = Runner(_pwd())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        r.connect()
        r.step("PRE", r.run,
               "date -u '+%Y-%m-%d %H:%M:%S UTC'; "
               f"cd {APP} && echo HEAD=$(git rev-parse HEAD) "
               "TRACKED_MOD=$(git status --porcelain | grep -v '^??' | wc -l); "
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ActiveState -p SubState --no-pager; "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               "curl -s https://admin-bot.duckdns.org/healthz; echo",
               timeout=90)
        r.step("UPLOAD", r.sftp_upload)
        r.step("JOURNAL_FIX", r.sudo_run,
               "sh /tmp/accept94_journal.sh %s" % _shq(T0), timeout=420,
               save=str(LOCAL / "logs" / "journal-since-t0.txt"))
        r.step("COVER_FIX", r.sudo_run,
               "sh -c %s" % _shq("cd %s && ./venv/bin/python "
                                 "/tmp/accept94b_cover.py" % APP),
               timeout=900)
        r.step("CLEANUP_FIX", r.sudo_run,
               "sh -c %s" % _shq("cd %s && ./venv/bin/python "
                                 "/tmp/accept94b_clean.py" % APP),
               timeout=420)
        got = r.sftp_download(["c5-cover-fix.json",
                               "cleanup-register-2.json",
                               "cover94-base.png"])
        r.emit("[runner] downloaded: %s" % ", ".join(got))
        r.step("FINAL", r.run,
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ActiveState -p SubState -p ExecMainStatus --no-pager; "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               f"cd {APP} && echo HEAD=$(git rev-parse HEAD) "
               "TRACKED_MOD=$(git status --porcelain | grep -v '^??' | wc -l); "
               "date -u '+%Y-%m-%d %H:%M:%S UTC'", timeout=120)
        return 0
    finally:
        r.close()
        LOG.write_text("\n".join(r.lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        msg = "%s: %s" % (type(exc).__name__, exc)
        try:
            msg = msg.replace(_pwd(), "***")
        except Exception:
            pass
        print("RUNNER_EXCEPTION:", msg)
        sys.exit(4)
