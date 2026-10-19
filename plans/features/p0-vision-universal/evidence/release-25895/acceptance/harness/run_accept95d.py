# -*- coding: utf-8 -*-
"""Runner for ACCEPTANCE-95d (prod 2.58.95): final ONE-session pass.

Upload -> final verification + cleanup completion (accept95d_final.py) ->
read-only journal slice for the 95c wave (14:14-14:30Z: [vision] adapt /
vision_adapt / errors) -> final service state -> download.

Usage: py -3 run_accept95d.py
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
             r"\acceptance-95")
FILES = {
    "accept95_base.py": "/tmp/accept95_base.py",
    "accept95d_final.py": "/tmp/accept95d_final.py",
}
LOG = LOCAL / "logs" / "accept95d-run.log"
EVID_LOCAL = LOCAL / "evidence"
RECONNECT_WAIT_S = 95


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    text = re.sub(r"https://[^@\s/]+@", "https://***@", text)
    return text


class Runner:
    def __init__(self, pw: str):
        self.pw = pw
        self.secrets = [pw]
        self.lines: list[str] = []
        self.client: paramiko.SSHClient | None = None
        self.harness_sudo = False

    def emit(self, s: str) -> None:
        s = scrub(s, self.secrets)
        print(s, flush=True)
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
        return rc, scrub(o, self.secrets), scrub(e, self.secrets)

    def sudo_run(self, cmd: str, timeout: float = 420.0) -> tuple[int, str, str]:
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
        return rc, scrub(o, self.secrets), scrub(e, self.secrets)

    def step(self, name: str, fn, *args, retry: bool = True, **kwargs):
        for attempt in (1, 2):
            try:
                result = fn(*args, **kwargs)
                if not (isinstance(result, tuple) and len(result) == 3):
                    self.emit("### %s (ok)" % name)
                    return 0, "", ""
                rc, o, e = result
                self.emit("### %s (rc=%s)" % (name, rc))
                if o.strip():
                    self.emit(o.rstrip())
                if e.strip():
                    self.emit("[stderr] " + e.strip()[:500])
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
                self.emit("[runner] uploaded %s -> %s (%d bytes)"
                          % (name, remote, (LOCAL / name).stat().st_size))
        finally:
            sftp.close()

    def sftp_download(self, only: str | None = None) -> list[str]:
        assert self.client is not None
        sftp = self.client.open_sftp()
        downloaded = []
        try:
            names = sftp.listdir("/tmp/accept95/evidence")
            EVID_LOCAL.mkdir(parents=True, exist_ok=True)
            for name in names:
                if only is not None and name != only:
                    continue
                try:
                    sftp.get("/tmp/accept95/evidence/" + name,
                             str(EVID_LOCAL / name))
                    downloaded.append(name)
                except Exception as exc:  # noqa: BLE001
                    self.emit("[download] %s failed %s"
                              % (name, type(exc).__name__))
        finally:
            sftp.close()
        return downloaded


def main() -> int:
    r = Runner(_pwd())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        r.connect()
        r.step("RECON", r.run,
               "date -u '+%Y-%m-%d %H:%M:%S UTC'; "
               f"cd {APP} && echo HEAD=$(git rev-parse HEAD); "
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ActiveState --no-pager | tr '\\n' ' '; echo; "
               "curl -s http://127.0.0.1:8000/healthz; echo",
               timeout=120)
        rc, o, e = r.run(
            "PUSER=$(ps -o user= -p $(systemctl show admin_bot -p MainPID "
            "--value) 2>/dev/null); echo PUSER=[$PUSER]", timeout=60)
        r.harness_sudo = "PUSER=[root]" in o
        r.emit("[runner] harness_sudo=%s" % r.harness_sudo)
        r.step("UPLOAD", r.sftp_upload)
        if r.harness_sudo:
            r.step("FINAL95D", r.sudo_run,
                   "sh -c %s" % _shq(
                       "cd %s && ./venv/bin/python /tmp/accept95d_final.py "
                       "> /tmp/accept95/final95d.out 2>&1; "
                       "tail -n 25 /tmp/accept95/final95d.out" % APP),
                   timeout=420)
        else:
            r.step("FINAL95D", r.run,
                   "cd %s && ./venv/bin/python /tmp/accept95d_final.py "
                   "> /tmp/accept95/final95d.out 2>&1; "
                   "tail -n 25 /tmp/accept95/final95d.out" % APP,
                   timeout=420)
        r.step("JOURNAL_95C", r.sudo_run,
               "journalctl -u admin_bot --since '2026-10-19 14:14:30' "
               "--no-pager | grep -E '\\[vision\\]|vision_adapt|"
               "image_postgen_vision|ERROR|CRITICAL|Traceback|maximum number "
               "of running instances' | head -60", timeout=180)
        try:
            dl = r.sftp_download(only="final95d.json")
            r.emit("[runner] downloaded: %s" % ", ".join(dl))
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] FAILED %s" % type(exc).__name__)
        r.step("FINAL", r.run,
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ActiveState -p SubState -p ExecMainStatus --no-pager; "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               "curl -s https://admin-bot.duckdns.org/healthz; echo; "
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
