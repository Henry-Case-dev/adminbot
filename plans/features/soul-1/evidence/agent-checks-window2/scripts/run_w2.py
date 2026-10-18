# -*- coding: utf-8 -*-
"""AGENT-CHECKS-2: runner — ОДНА SSH-сессия (paramiko) на прод 2.58.89.

Шаги: recon (HEAD/healthz/systemctl PID+NRestarts) -> sftp upload -> pre-state
-> nohup-прогон (W2_PHASES, поллинг до ~25 мин) -> сырой вывод -> post-state ->
journal-счётчики (sudo) -> systemctl after -> healthz -> очистка /tmp.

Устойчив к обрыву локального процесса: прод-проба пишет в /tmp/w2_probe.out,
статус снимается polling'ом. Креды не печатаются.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
APP = "/var/www/admin_bot"
CREDS = Path(r"C:\Code\Python\adminbot\deploy_commands.txt")
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\agent-checks-w2")
PROBE = LOCAL / "agent_checks_w2_probe.py"
STATE = LOCAL / "w2_state.py"
LOG = LOCAL / os.environ.get("W2_LOG", "run-w2.log")
REMOTE_PROBE = "/tmp/agent_checks_w2_probe.py"
REMOTE_STATE = "/tmp/w2_state.py"
OUT = "/tmp/w2_probe.out"
SYNTH_A = "-1009900000201"
SYNTH_B = "-1009900000202"
W2_PHASES = os.environ.get("W2_PHASES", "")
W2_SKIP_L3 = os.environ.get("W2_SKIP_L3", "")


def _pwd(pattern: str) -> str:
    m = re.search(rf"^{pattern}:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit(f"credential '{pattern}' not found")
    return m.group(1)


class Tee:
    def __init__(self, path: Path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, *parts) -> None:
        s = " ".join(str(p) for p in parts)
        try:
            print(s)
        except Exception:
            print(s.encode("ascii", "replace").decode("ascii"))
        self.f.write(s + "\n")
        self.f.flush()

    def close(self) -> None:
        self.f.close()


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


class Sh:
    def __init__(self, shell):
        self.shell = shell
        self.buf = ""
        self.search_from = 0

    def expect(self, patterns, timeout):
        deadline = time.time() + timeout
        rx = [re.compile(p, re.M) for p in patterns]
        while time.time() < deadline:
            if self.shell.recv_ready():
                self.buf += self.shell.recv(65536).decode("utf-8", "replace")
                continue
            window = self.buf[self.search_from:]
            for i, r in enumerate(rx):
                m = r.search(window)
                if m:
                    return f"#{i}:{m.group(0).strip()}"
            time.sleep(0.25)
        raise TimeoutError(f"expect timeout; tail: ...{self.buf[-600:]!r}")

    def send(self, cmd: str, pause: float = 0.3) -> None:
        self.shell.sendall(cmd.encode() + b"\n")
        time.sleep(pause)


def run(cmd: str, sh: Sh, secrets, *, timeout: float = 180) -> str:
    start = len(sh.buf)
    sh.search_from = start
    sh.send(cmd + '; echo "###RC=$?###"')
    sh.expect([r'(?<!["\'])###RC=\d+###'], timeout)
    sh.search_from = len(sh.buf)
    return scrub(sh.buf[start:], secrets)


def sudo_run(cmd: str, sh: Sh, pw: str, secrets, *, timeout: float = 240) -> str:
    start = len(sh.buf)
    sh.search_from = start
    sh.send("sudo -S " + cmd + ' ; echo "###RC=$?###"')
    got = sh.expect([r"\[sudo\][^\r\n]*:", r'(?<!["\'])###RC=\d+###'], timeout)
    if got.startswith("#0:"):
        sh.send(pw)
        sh.expect([r'(?<!["\'])###RC=\d+###'], timeout)
    sh.search_from = len(sh.buf)
    out = sh.buf[start:]
    out = out.replace(pw, "***")
    return scrub(out, secrets)


def main() -> int:
    tee = Tee(LOG)
    pw = _pwd("pass")
    secrets = [pw]
    client = paramiko.SSHClient()
    try:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                       auth_timeout=30, allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()
        sftp.put(str(PROBE), REMOTE_PROBE)
        sftp.put(str(STATE), REMOTE_STATE)
        sftp.close()
        tee(f"[runner] uploaded: probe={PROBE.stat().st_size} "
            f"state={STATE.stat().st_size} bytes; phases={W2_PHASES or 'ALL'}")
        shell = client.invoke_shell(width=250, height=8000)
        sh = Sh(shell)
        sh.expect([r"\$ $", r"# $"], 30)

        tee("=== PRE: время/процессы/биндинг ===")
        tee(run("date -u '+%Y-%m-%d %H:%M:%S UTC'; "
                "echo PROBE_PROCS=$(ps -ef | grep -c '[a]gent_checks_w2_probe'); "
                "echo STALE_STATE_PROCS=$(ps -ef | grep -c '[w]2_state'); "
                "pkill -f '[w]2_state.py' >/dev/null 2>&1; echo PKILL_RC=$?; "
                "echo OLD_OUT_BYTES=$([ -f /tmp/w2_probe.out ] && "
                "wc -c < /tmp/w2_probe.out || echo 0); "
                f"cd {APP} && echo HEAD=$(git rev-parse HEAD) && "
                "echo TRACKED_MOD=$(git status --porcelain | wc -l) && "
                "systemctl show admin_bot -p MainPID -p NRestarts "
                "-p ActiveEnterTimestamp --no-pager; "
                "curl -s http://127.0.0.1:8000/healthz",
                sh, secrets, timeout=90))

        tee("=== PRE-STATE ===")
        tee(run(f"cd {APP} && PYTHONIOENCODING=utf-8 timeout 100 "
                f"{APP}/venv/bin/python {REMOTE_STATE}", sh, secrets,
                timeout=150))

        tee("=== PROBE (nohup, phases=%s, skip_l3=%s) ==="
            % (W2_PHASES or "ALL", W2_SKIP_L3 or "0"))
        tee(run(f"cd {APP} && rm -f {OUT} && nohup env W2_PHASES={W2_PHASES} "
                f"W2_SKIP_L3={W2_SKIP_L3} "
                f"PYTHONIOENCODING=utf-8 {APP}/venv/bin/python {REMOTE_PROBE} "
                f"> {OUT} 2>&1 & echo STARTED_PID=$!",
                sh, secrets, timeout=60))
        done = False
        i = 0
        for i in range(150):          # до 25 минут (10 c * 150)
            time.sleep(10)
            got = run(
                f"grep -qE 'W2 SUMMARY|W2 RC=' {OUT} 2>/dev/null && echo DONE "
                f"|| echo WAIT", sh, secrets, timeout=30)
            if re.search(r"\r?\nDONE\r?\n", got):
                done = True
                break
        tee(f"[runner] probe finished={done} (poll iterations={i + 1})")
        tee("=== PROBE OUTPUT ===")
        tee(run(f"cat {OUT}", sh, secrets, timeout=120))

        tee("=== POST-STATE ===")
        tee(run(f"cd {APP} && PYTHONIOENCODING=utf-8 timeout 100 "
                f"{APP}/venv/bin/python {REMOTE_STATE}", sh, secrets,
                timeout=150))

        tee("=== POST: journal окна (read-only, sudo) ===")
        snippet = ("-1009900000201|-1009900000202|\\[image\\]|"
                   "direct_chat_throttle|capability")
        tee(sudo_run(
            "journalctl -u admin_bot --since '45 min ago' --no-pager | "
            "grep -c ' ERROR ' ; echo ---ERR_END; "
            "journalctl -u admin_bot --since '45 min ago' --no-pager | "
            "grep -c ' CRITICAL ' ; echo ---CRIT_END; "
            "journalctl -u admin_bot --since '45 min ago' --no-pager | "
            "grep -c 'Traceback' ; echo ---TB_END; "
            "journalctl -u admin_bot --since '45 min ago' -o short-iso "
            "--no-pager | grep -c '\\[tma-auth\\].*valid=True' ; "
            "echo ---TMA_END; "
            "journalctl -u admin_bot --since '45 min ago' -o short-iso "
            "--no-pager | grep -E '" + snippet + "' | tail -n 60 ; "
            "echo ---SNIPPET_END; "
            "journalctl -u admin_bot -n 3 --no-pager ; echo ---TAIL_END",
            sh, pw, secrets, timeout=240))
        tee("=== POST: systemctl/healthz after ===")
        tee(run("systemctl show admin_bot -p MainPID -p NRestarts "
                "-p ActiveEnterTimestamp --no-pager; "
                "curl -s http://127.0.0.1:8000/healthz",
                sh, secrets, timeout=60))

        tee("=== CLEANUP /tmp ===")
        tee(run(f"rm -f {REMOTE_PROBE} {REMOTE_STATE} {OUT}; echo CLEANED=1",
                sh, secrets, timeout=60))
        return 0
    finally:
        try:
            client.close()
        except Exception:
            pass
        tee.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        try:
            msg = msg.replace(_pwd("pass"), "***")
        except SystemExit:
            pass
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("RUNNER_EXCEPTION: " + str(msg) + "\n")
        except Exception:
            pass
        print("RUNNER_EXCEPTION:", msg)
        sys.exit(4)
