# -*- coding: utf-8 -*-
"""Runner ACCEPTANCE-96 (ADD-EXP Ф6 live, prod 2.58.96) — один SSH-сеанс.

Дисциплина fail2ban: один коннект на прогон, максимум один авто-reconnect
(>=95 c) при обрыве канала; креды не печатаются.

Шаги: RECON (read-only) → UPLOAD → CLEAN → START harness → POLL → LIVE_TAIL →
download evidence → JOURNAL (read-only) → CLEANUP (правило владельца) →
FINAL (версия/PID/HEAD).

Usage: py -3 run_accept96.py [poll_minutes]
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
DEPLOY_T0 = "2026-10-19 14:51:18"
EXPECT_VER = "2.58.96"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH"
             r"\acceptance-96")
FILES = {
    "accept96_base.py": "/tmp/accept96_base.py",
    "accept96_live.py": "/tmp/accept96_live.py",
    "accept96b_live.py": "/tmp/accept96b_live.py",
    "accept96b_clean.py": "/tmp/accept96b_clean.py",
    "accept96b_journal.sh": "/tmp/accept96b_journal.sh",
}
OUT = "/tmp/accept96b/live.out"
LOG = LOCAL / "logs" / "accept96b-run.log"
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
            for d in ("/tmp/accept96b", "/tmp/accept96b/evidence"):
                try:
                    sftp.mkdir(d)
                except Exception:
                    pass
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
            try:
                names = sftp.listdir("/tmp/accept96b/evidence")
            except Exception:
                names = []
            EVID_LOCAL.mkdir(parents=True, exist_ok=True)
            for name in names:
                if only is not None and name != only:
                    continue
                try:
                    sftp.get("/tmp/accept96b/evidence/" + name,
                             str(EVID_LOCAL / name))
                    downloaded.append(name)
                except Exception as exc:  # noqa: BLE001
                    self.emit("[download] %s failed %s"
                              % (name, type(exc).__name__))
            if only is None:
                for remote, local in ((OUT, LOCAL / "live.out"),
                                      ("/tmp/accept96b/cleanup_spec.json",
                                       LOCAL / "cleanup_spec.json"),
                                      ("/tmp/accept96b/journal.txt",
                                       LOCAL / "journal.txt")):
                    try:
                        sftp.get(remote, str(local))
                    except Exception as exc:  # noqa: BLE001
                        self.emit("[download] %s failed %s"
                                  % (remote, type(exc).__name__))
        finally:
            sftp.close()
        return downloaded


def main() -> int:
    poll_minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0
    r = Runner(_pwd())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        r.connect()
        r.step("RECON", r.run,
               "date -u '+%Y-%m-%d %H:%M:%S UTC'; "
               f"cd {APP} && echo HEAD=$(git rev-parse HEAD) "
               "BRANCH=$(git rev-parse --abbrev-ref HEAD) "
               "TRACKED_MOD=$(git status --porcelain | grep -v '^??' | wc -l); "
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ActiveState -p SubState --no-pager; "
               "echo PROD_USER=$(ps -o user= -p "
               "$(systemctl show admin_bot -p MainPID --value) 2>/dev/null); "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               "curl -s https://admin-bot.duckdns.org/healthz; echo; "
               "df -h /tmp | tail -1; "
               "ls -la /tmp/accept96b* 2>/dev/null | head -12 || "
               "echo NO_ACCEPT96_LEFTOVERS",
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
        r.step("VERIFY_UPLOAD", r.run,
               "cd /tmp && sha256sum accept96_base.py accept96_live.py "
               "accept96b_live.py accept96b_clean.py accept96b_journal.sh "
               "| sed 's/  */ /'",
               timeout=60)
        r.step("CLEAN_EVID", r.maybe_root,
               "rm -rf /tmp/accept96b/evidence; "
               "mkdir -p /tmp/accept96b/evidence; "
               f"rm -f {OUT} /tmp/accept96b/cleanup_spec.json "
               "/tmp/accept96b/journal.txt; "
               "echo CLEANED=1; chmod -R a+rX /tmp/accept96 2>/dev/null; true",
               timeout=120)
        r.step("KILL_STALE", r.maybe_root,
               "pkill -f '[a]ccept96b_live.py' >/dev/null 2>&1 || true; "
               "sleep 1; pgrep -f '[a]ccept96b_live.py' >/dev/null 2>&1 "
               "&& echo STILL || echo CLEAR", timeout=60, retry=False)
        rc, o, e = r.run("date -u '+%Y-%m-%d %H:%M:%S'", timeout=30)
        wave_since = o.strip() or DEPLOY_T0
        r.emit("[runner] WAVE_SINCE=%s" % wave_since)
        start_inner = ("cd %s && setsid nohup env PYTHONIOENCODING=utf-8 "
                       "./venv/bin/python /tmp/accept96b_live.py "
                       "< /dev/null > %s 2>&1 & echo STARTED_PID=$!; "
                       "sleep 1; chmod 644 %s 2>/dev/null; "
                       "chmod -R a+rX /tmp/accept96 2>/dev/null; true"
                       % (APP, OUT, OUT))
        r.step("START", r.maybe_root, start_inner, timeout=90, retry=False)
        time.sleep(8)
        verify_cmd = (f"echo OUT_LINES=$(wc -l < {OUT} 2>/dev/null || echo 0); "
                      "pgrep -f '[a]ccept96b_live.py' >/dev/null 2>&1 "
                      "&& echo PROC_RUNNING || echo PROC_ABSENT")
        rc, o, e = r.step("VERIFY_START", r.maybe_root, verify_cmd,
                          timeout=60, retry=False)
        if "PROC_RUNNING" not in (o or "") and "OUT_LINES=0" in (o or ""):
            r.emit("[runner] harness not detected — retrying start once")
            r.step("START_RETRY", r.maybe_root, start_inner, timeout=90,
                   retry=False)
            time.sleep(8)
            r.step("VERIFY_START2", r.maybe_root, verify_cmd, timeout=60,
                   retry=False)

        done = False
        iters = max(6, int(poll_minutes * 6))     # poll every 10 s
        for i in range(iters):
            time.sleep(10)
            try:
                poll_inner = (
                    f"if grep -q 'ACC96B RC=' {OUT} 2>/dev/null; then "
                    f"echo DONE; elif grep -q 'ACC96B FATAL' {OUT} 2>/dev/null; "
                    f"then echo FATAL; elif ! pgrep -f '[a]ccept96b_live.py' "
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
               f"wc -l {OUT}; grep -E 'ACC96 (WAVE|TURN|ISO|ROUTE|LIVE_CHECK|"
               f"P0|P1|RESTORE|SUMMARY|SPEC|CHAT_B)' {OUT} | tail -80; "
               f"tail -n 40 {OUT}", timeout=90)
        try:
            dl = r.sftp_download()
            r.emit("[runner] downloaded evidence (pass 1): %s"
                   % ", ".join(dl))
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] FAILED %s" % type(exc).__name__)
            try:
                r.connect(wait_first=True)
                dl = r.sftp_download()
                r.emit("[runner] downloaded evidence (retry): %s"
                       % ", ".join(dl))
            except Exception as exc2:  # noqa: BLE001
                r.emit("[download] retry FAILED %s" % type(exc2).__name__)

        r.step("JOURNAL", r.sudo_run,
               "sh /tmp/accept96b_journal.sh %s" % _shq(wave_since),
               timeout=420)

        # cleanup wave (owner rule): удалить все тестовые сообщения
        rc, o, e = r.maybe_root(
            "test -s /tmp/accept96b/cleanup_spec.json && echo SPEC_OK || "
            "echo SPEC_MISSING", timeout=30)
        r.emit("### CLEANUP_SPEC (rc=%s) %s" % (rc, o.strip()))
        if "SPEC_OK" in (o or ""):
            clean_inner = ("cd %s && ./venv/bin/python /tmp/accept96b_clean.py"
                           % APP)
            if r.harness_sudo:
                r.step("CLEANUP", r.sudo_run, "sh -c %s" % _shq(clean_inner),
                       timeout=420)
            else:
                r.step("CLEANUP", r.run, clean_inner, timeout=420)
            try:
                dl2 = r.sftp_download(only="cleanup-register.json")
                r.emit("[runner] downloaded cleanup register: %s"
                       % ", ".join(dl2))
            except Exception as exc:  # noqa: BLE001
                r.emit("[download] cleanup register FAILED %s"
                       % type(exc).__name__)
        else:
            r.emit("[runner] cleanup skipped: no spec (harness may have "
                   "failed before SPEC)")

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
