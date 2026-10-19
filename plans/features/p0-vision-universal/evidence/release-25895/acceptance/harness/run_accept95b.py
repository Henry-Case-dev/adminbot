# -*- coding: utf-8 -*-
"""Runner for ACCEPTANCE-95b (prod 2.58.95): resilient ONE-session run.

Uploads accept95b files, starts the follow-up live harness (prod-faithful
user), polls, downloads /tmp/accept95/evidence/**, runs the read-only journal
wave (95b markers + full 95a error blocks), final state. Cleanup is a separate
deliberate connection (its register needs the wave inventory review).

Usage: py -3 run_accept95b.py [poll_minutes]
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
    "accept95b_live.py": "/tmp/accept95b_live.py",
    "accept95b_journal.sh": "/tmp/accept95b_journal.sh",
    "accept95_dbcheck.py": "/tmp/accept95_dbcheck.py",
}
OUT = "/tmp/accept95/live95b.out"
LOG = LOCAL / "logs" / "accept95b-run.log"
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

    def rootsh(self, inner: str, timeout: float = 120.0):
        cmd = "printf '%%s\\n' %s | sudo -S sh -c %s" % (_shq(self.pw),
                                                        _shq(inner))
        return self.run(cmd, timeout=timeout)

    def maybe_root(self, inner: str, timeout: float = 120.0):
        if self.harness_sudo:
            return self.rootsh(inner, timeout=timeout)
        return self.run(inner, timeout=timeout)

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

    def sftp_download(self) -> list[str]:
        assert self.client is not None
        sftp = self.client.open_sftp()
        downloaded = []
        try:
            try:
                names = sftp.listdir("/tmp/accept95/evidence")
            except Exception:
                names = []
            EVID_LOCAL.mkdir(parents=True, exist_ok=True)
            for name in names:
                try:
                    sftp.get("/tmp/accept95/evidence/" + name,
                             str(EVID_LOCAL / name))
                    downloaded.append(name)
                except Exception as exc:  # noqa: BLE001
                    self.emit("[download] %s failed %s"
                              % (name, type(exc).__name__))
            for remote, local in ((OUT, LOCAL / "live95b.out"),
                                  ("/tmp/accept95_cleanup_mids.json",
                                   LOCAL / "accept95_cleanup_mids.json")):
                try:
                    sftp.get(remote, str(local))
                except Exception as exc:  # noqa: BLE001
                    self.emit("[download] %s failed %s"
                              % (remote, type(exc).__name__))
        finally:
            sftp.close()
        return downloaded


def main() -> int:
    poll_minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
    r = Runner(_pwd())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        r.connect()
        r.step("RECON", r.run,
               "date -u '+%Y-%m-%d %H:%M:%S UTC'; "
               f"cd {APP} && echo HEAD=$(git rev-parse HEAD) "
               "TRACKED_MOD=$(git status --porcelain | grep -v '^??' | wc -l); "
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ActiveState --no-pager | tr '\\n' ' '; echo; "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               "curl -s https://admin-bot.duckdns.org/healthz; echo; "
               "ls -la /tmp/accept95* 2>/dev/null | head -20",
               timeout=120)
        rc, o, e = r.run(
            "PUSER=$(ps -o user= -p $(systemctl show admin_bot -p MainPID "
            "--value) 2>/dev/null); echo PUSER=[$PUSER]", timeout=60)
        r.emit("### HARNESS_USER_CHECK (rc=%s)" % rc)
        if o.strip():
            r.emit(o.rstrip())
        r.harness_sudo = "PUSER=[root]" in o
        r.emit("[runner] harness_sudo=%s" % r.harness_sudo)
        r.step("UPLOAD", r.sftp_upload)
        r.step("KILL_STALE", r.maybe_root,
               "pkill -f '[a]ccept95b_live.py' >/dev/null 2>&1 || true; "
               "sleep 1; pgrep -f '[a]ccept95b_live.py' >/dev/null 2>&1 "
               "&& echo STILL || echo CLEAR", timeout=60, retry=False)
        rc, o, e = r.run("date -u '+%Y-%m-%d %H:%M:%S'", timeout=30)
        wave_since = o.strip() or "2026-10-19 13:47:17"
        r.emit("[runner] WAVE_SINCE=%s" % wave_since)
        start_inner = ("cd %s && setsid nohup env PYTHONIOENCODING=utf-8 "
                       "./venv/bin/python /tmp/accept95b_live.py "
                       "< /dev/null > %s 2>&1 & echo STARTED_PID=$!; "
                       "sleep 1; chmod 644 %s 2>/dev/null; "
                       "chmod -R a+rX /tmp/accept95 2>/dev/null; true"
                       % (APP, OUT, OUT))
        r.step("START", r.maybe_root, start_inner, timeout=90, retry=False)
        time.sleep(8)
        verify_cmd = (f"echo OUT_LINES=$(wc -l < {OUT} 2>/dev/null || echo 0); "
                      "pgrep -f '[a]ccept95b_live.py' >/dev/null 2>&1 "
                      "&& echo PROC_RUNNING || echo PROC_ABSENT")
        r.step("VERIFY_START", r.maybe_root, verify_cmd, timeout=60,
               retry=False)
        done = False
        iters = max(6, int(poll_minutes * 6))
        for i in range(iters):
            time.sleep(10)
            try:
                poll_inner = (
                    f"if grep -q 'ACC95B RC=' {OUT} 2>/dev/null; then "
                    f"echo DONE; elif grep -q 'ACC95B FATAL' {OUT} 2>/dev/null; "
                    f"then echo FATAL; elif ! pgrep -f '[a]ccept95b_live.py' "
                    f">/dev/null 2>&1; then echo GONE; else echo WAIT; fi")
                rc, o, e = r.maybe_root(poll_inner, timeout=45)
                state = o.strip().splitlines()[-1] if o.strip() else "?"
            except Exception as exc:  # noqa: BLE001
                r.emit("[poll %d] channel error: %s" % (i + 1,
                                                        type(exc).__name__))
                try:
                    r.connect(wait_first=True)
                except Exception as exc2:  # noqa: BLE001
                    r.emit("[poll] reconnect failed: %s" % type(exc2).__name__)
                    break
                continue
            if i % 6 == 0:
                r.emit("[poll %d] %s" % (i + 1, state))
            if state in ("DONE", "FATAL", "GONE"):
                done = True
                break
        r.emit("[runner] finished=%s" % done)
        r.step("LIVE_TAIL", r.maybe_root,
               f"wc -l {OUT}; tail -n 250 {OUT}", timeout=90)
        try:
            dl = r.sftp_download()
            r.emit("[runner] downloaded evidence: %s" % ", ".join(dl))
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] FAILED %s" % type(exc).__name__)
        r.step("JOURNAL", r.sudo_run,
               "sh /tmp/accept95b_journal.sh %s" % _shq(wave_since),
               timeout=420)
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
