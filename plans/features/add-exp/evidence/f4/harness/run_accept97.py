# -*- coding: utf-8 -*-
"""Runner ACCEPTANCE-97 (ADD-EXP F4 live, prod 2.58.97) — один SSH-сеанс.

Дисциплина fail2ban: один коннект на прогон, максимум один авто-reconnect
(>=95 c) при обрыве канала; креды не печатаются.

Шаги: RECON (read-only) → UPLOAD → CLEAN → START harness → POLL → LIVE_TAIL →
download evidence → JOURNAL (read-only) → CLEANUP (правило владельца) →
FINAL (версия/PID/HEAD).

Usage: py -3 run_accept97.py [poll_minutes]
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
DEPLOY_T0 = "2026-10-19 19:13:31"
EXPECT_VER = "2.58.97"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
LOCAL = Path(r"C:\Users\main\.config\opencode\OpenCodeScratch"
             r"\adminbot-ccef72c25768\acceptance-97")
FILES = {
    "accept97_base.py": "/tmp/accept97_base.py",
    "accept97_live.py": "/tmp/accept97_live.py",
    "accept97_clean.py": "/tmp/accept97_clean.py",
    "accept97_journal.sh": "/tmp/accept97_journal.sh",
    "accept97_prep.py": "/tmp/accept97_prep.py",
    "accept97_sweep.py": "/tmp/accept97_sweep.py",
}
OUT = "/tmp/accept97/live.out"
LOG = LOCAL / "logs" / "accept97-run.log"
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
            for d in ("/tmp/accept97", "/tmp/accept97/evidence"):
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

    def sftp_get(self, remote: str, local: Path) -> None:
        assert self.client is not None
        sftp = self.client.open_sftp()
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote, str(local))
        finally:
            sftp.close()

    def sftp_download(self, only: str | None = None) -> list[str]:
        assert self.client is not None
        sftp = self.client.open_sftp()
        downloaded = []
        try:
            try:
                names = sftp.listdir("/tmp/accept97/evidence")
            except Exception:
                names = []
            EVID_LOCAL.mkdir(parents=True, exist_ok=True)
            for name in names:
                if only is not None and name != only:
                    continue
                try:
                    sftp.get("/tmp/accept97/evidence/" + name,
                             str(EVID_LOCAL / name))
                    downloaded.append(name)
                except Exception as exc:  # noqa: BLE001
                    self.emit("[download] %s failed %s"
                              % (name, type(exc).__name__))
            if only is None:
                for remote, local in ((OUT, LOCAL / "live.out"),
                                      ("/tmp/accept97/cleanup_spec.json",
                                       LOCAL / "cleanup_spec.json"),
                                      ("/tmp/accept97/journal.txt",
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
               "./venv/bin/python -c \"import sqlite3;from config.settings import "
               "settings as s;print('APP_VER='+str(s.APP_VERSION));"
               "print('USER_VERSION='+str(sqlite3.connect(s.DB_PATH).execute("
               "'PRAGMA user_version').fetchone()[0]))\" 2>&1 | tail -3; "
               "echo SERVED_APP_JS=$(curl -s http://127.0.0.1:8000/web/app.js "
               "| sha256sum | cut -c1-12) "
               "SERVED_APP_CSS=$(curl -s http://127.0.0.1:8000/static/app.css "
               "| sha256sum | cut -c1-12); "
               "curl -s http://127.0.0.1:8000/web/ | grep -oE "
               "'(PAGE_VER|SUBST_CSS|STICKY_SAVE_SERVED)[^<]{0,20}' | head -5; "
               "echo SKIPS_T0=$(journalctl -u admin_bot --since "
               f"'{DEPLOY_T0}' --no-pager 2>/dev/null | "
               "grep -c 'maximum number of running instances'); "
               "df -h /tmp | tail -1; "
               "ls -la /tmp/accept97* 2>/dev/null | head -12 || "
               "echo NO_ACCEPT97_LEFTOVERS",
               timeout=180)
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
               "cd /tmp && sha256sum accept97_base.py accept97_live.py "
               "accept97_clean.py accept97_journal.sh accept97_prep.py "
               "accept97_sweep.py "
               "| sed 's/  */ /'",
               timeout=60)
        r.step("CLEAN_EVID", r.maybe_root,
               "rm -rf /tmp/accept97/evidence; "
               "mkdir -p /tmp/accept97/evidence; "
               f"rm -f {OUT} /tmp/accept97/cleanup_spec.json "
               "/tmp/accept97/journal.txt; "
               "echo CLEANED=1; chmod -R a+rX /tmp/accept97 2>/dev/null; true",
               timeout=120)
        r.step("KILL_STALE", r.maybe_root,
               "systemctl stop accept97wave >/dev/null 2>&1 || true; "
               "pkill -f '[a]ccept97_live.py' >/dev/null 2>&1 || true; "
               "sleep 1; pgrep -f '[a]ccept97_live.py' >/dev/null 2>&1 "
               "&& echo STILL || echo CLEAR; "
               "command -v systemd-run >/dev/null && echo HAS_SYSTEMD_RUN "
               "|| echo NO_SYSTEMD_RUN", timeout=60, retry=False)

        # SWEEP: убрать ВСЕ тестовые сообщения прошлых попыток в окне волны
        rc, o, e = r.maybe_root(
            "cd %s && ./venv/bin/python /tmp/accept97_sweep.py" % APP,
            timeout=420)
        r.emit("### SWEEP (rc=%s)" % rc)
        if o.strip():
            r.emit(o.rstrip()[-2500:])
        if e.strip():
            r.emit("[stderr] " + e.strip()[:300])
        try:
            dls = r.sftp_download(only="sweep.json")
            r.emit("[runner] downloaded sweep.json: %s" % ", ".join(dls))
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] sweep.json FAILED %s" % type(exc).__name__)

        # PREP: убрать остатки прерванной попытки, вернуть A в global
        rc, o, e = r.maybe_root(
            "cd %s && ./venv/bin/python /tmp/accept97_prep.py" % APP,
            timeout=420)
        r.emit("### PREP (rc=%s)" % rc)
        if o.strip():
            r.emit(o.rstrip()[-3000:])
        if e.strip():
            r.emit("[stderr] " + e.strip()[:400])
        try:
            dlp = r.sftp_download(only="prep.json")
            r.emit("[runner] downloaded prep.json: %s" % ", ".join(dlp))
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] prep.json FAILED %s" % type(exc).__name__)
        rc, o, e = r.run("date -u '+%Y-%m-%d %H:%M:%S'", timeout=30)
        wave_since = DEPLOY_T0
        r.emit("[runner] WAVE_SINCE=%s (journal window = since deploy T0)"
               % wave_since)
        # systemd-run: transient unit survives the SSH session (выход из
        # сессии не убивает волну); логи — append в OUT.
        start_unit = ("systemd-run --unit=accept97wave --collect "
                      "--property=Type=simple "
                      "--property=WorkingDirectory=%s "
                      "--property=StandardOutput=append:%s "
                      "--property=StandardError=append:%s "
                      "--setenv=PYTHONIOENCODING=utf-8 "
                      "--setenv=PYTHONFAULTHANDLER=1 "
                      "/bin/sh -c 'cd %s && ./venv/bin/python "
                      "/tmp/accept97_live.py < /dev/null; "
                      "chmod -R a+rX /tmp/accept97 2>/dev/null'"
                      % (APP, OUT, OUT, APP))
        start_inner = ("cd %s && setsid nohup env PYTHONIOENCODING=utf-8 "
                       "PYTHONFAULTHANDLER=1 "
                       "./venv/bin/python /tmp/accept97_live.py "
                       "< /dev/null >> %s 2>&1 & echo STARTED_PID=$!; "
                       "sleep 1; chmod 644 %s 2>/dev/null; "
                       "chmod -R a+rX /tmp/accept97 2>/dev/null; true"
                       % (APP, OUT, OUT))
        rc, o, e = r.step("START", r.maybe_root, start_unit, timeout=90,
                          retry=False)
        # «Running as unit: …» печатается в stderr sudo — проверяем оба канала
        started = ("Running as unit" in (o or "")
                   or "Running as unit" in (e or ""))
        if not started:
            rc2, o2, _ = r.maybe_root("systemctl is-active accept97wave 2>/dev/null "
                                      "|| true", timeout=30)
            started = "active" in (o2 or "")
        if not started:
            r.emit("[runner] systemd-run not active — falling back to nohup")
            r.step("START_NOHUP", r.maybe_root, start_inner, timeout=90,
                   retry=False)
        time.sleep(8)
        rc, o, _ = r.maybe_root("pgrep -fc '[a]ccept97_live.py' || true",
                                timeout=30)
        r.emit("[runner] harness processes=%s (ожидается 1)" % (o or "").strip())
        verify_cmd = (f"echo OUT_LINES=$(wc -l < {OUT} 2>/dev/null || echo 0); "
                      "systemctl is-active accept97wave 2>/dev/null || true; "
                      "pgrep -f '[a]ccept97_live.py' >/dev/null 2>&1 "
                      "&& echo PROC_RUNNING || echo PROC_ABSENT")
        r.step("VERIFY_START", r.maybe_root, verify_cmd,
               timeout=60, retry=False)

        done = False
        iters = max(6, int(poll_minutes * 6))     # poll every 10 s
        for i in range(iters):
            time.sleep(10)
            try:
                poll_inner = (
                    f"if grep -q 'ACC97 RC=' {OUT} 2>/dev/null; then "
                    f"echo DONE; elif grep -q 'ACC97 FATAL' {OUT} 2>/dev/null; "
                    f"then echo FATAL; elif systemctl is-active accept97wave "
                    f">/dev/null 2>&1; then echo WAIT; "
                    f"elif pgrep -f '[a]ccept97_live.py' >/dev/null 2>&1; "
                    f"then echo WAIT; else echo GONE; fi")
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
        r.step("UNIT_RESULT", r.maybe_root,
               "systemctl show accept97wave -p ActiveState -p SubState "
               "-p Result -p ExecMainStatus --no-pager 2>/dev/null || "
               "echo UNIT_GONE", timeout=60, retry=False)

        r.step("LIVE_TAIL", r.maybe_root,
               f"wc -l {OUT}; grep -E 'ACC97 (WAVE|TURN|CACHE|BOOT|P0|RESTORE|"
               f"SUMMARY|SPEC)' {OUT} | tail -100; "
               f"grep -E 'ACC97 RC=' {OUT} || echo NO_RC_LINE; "
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
               "sh /tmp/accept97_journal.sh %s; "
               "chmod 644 /tmp/accept97/journal.txt 2>/dev/null; true"
               % _shq(wave_since),
               timeout=420)
        try:
            r.sftp_get("/tmp/accept97/journal.txt", LOCAL / "journal.txt")
            r.emit("[runner] downloaded journal.txt")
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] journal.txt FAILED %s" % type(exc).__name__)

        # cleanup wave (owner rule): удалить все тестовые сообщения
        rc, o, e = r.maybe_root(
            "test -s /tmp/accept97/cleanup_spec.json && echo SPEC_OK || "
            "echo SPEC_MISSING", timeout=30)
        r.emit("### CLEANUP_SPEC (rc=%s) %s" % (rc, o.strip()))
        if "SPEC_OK" in (o or ""):
            clean_inner = ("cd %s && ./venv/bin/python /tmp/accept97_clean.py"
                           "; rc=$?; chmod -R a+rX /tmp/accept97 2>/dev/null; "
                           "exit $rc" % APP)
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
               "./venv/bin/python -c \"import sqlite3;from config.settings import "
               "settings as s;print('APP_VER='+str(s.APP_VERSION));"
               "print('USER_VERSION='+str(sqlite3.connect(s.DB_PATH).execute("
               "'PRAGMA user_version').fetchone()[0]))\" 2>&1 | tail -2; "
               "echo SKIPS_T0=$(journalctl -u admin_bot --since "
               f"'{DEPLOY_T0}' --no-pager 2>/dev/null | "
               "grep -c 'maximum number of running instances'); "
               "echo RUNTIMEWARN_T0=$(journalctl -u admin_bot --since "
               f"'{DEPLOY_T0}' --no-pager 2>/dev/null | "
               "grep -c 'RuntimeWarning'); "
               "date -u '+%Y-%m-%d %H:%M:%S UTC'", timeout=180)
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
