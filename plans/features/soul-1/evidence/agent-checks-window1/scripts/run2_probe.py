# -*- coding: utf-8 -*-
"""AGENT-CHECKS-1: runner v2 — ОДНА SSH-сессия: состояние -> nohup-прогон
фазы A,D (без повторной генерации) -> состояние + журнал (sudo).

Устойчив к обрыву локального процесса: прод-проба пишет в /tmp/ac1_probe.out,
статус снимается polling'ом.
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
LOCAL = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\agent-checks-w1")
PROBE = LOCAL / "agent_checks_w1_probe.py"
STATE = LOCAL / "ac1_state.py"
LOG = LOCAL / "run-w1b.log"
REMOTE_PROBE = "/tmp/agent_checks_w1_probe.py"
REMOTE_STATE = "/tmp/ac1_state.py"
OUT = "/tmp/ac1_probe.out"
SYNTH_CHAT = "-1009900000201"
AC1_PHASES = os.environ.get("AC1_PHASES", "A,D")
AC1_SKIP_IMAGE_GEN = os.environ.get("AC1_SKIP_IMAGE_GEN", "1")


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
    sh.expect([r"(?<![\"'])###RC=\d+###"], timeout)
    sh.search_from = len(sh.buf)
    return scrub(sh.buf[start:], secrets)


def sudo_run(cmd: str, sh: Sh, pw: str, secrets, *, timeout: float = 240) -> str:
    start = len(sh.buf)
    sh.search_from = start
    sh.send("sudo -S " + cmd + ' ; echo "###RC=$?###"')
    got = sh.expect([r"\[sudo\][^\r\n]*:", r"(?<![\"'])###RC=\d+###"], timeout)
    if got.startswith("#0:"):
        sh.send(pw)
        sh.expect([r"(?<![\"'])###RC=\d+###"], timeout)
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
            f"state={STATE.stat().st_size} bytes")
        shell = client.invoke_shell(width=250, height=8000)
        sh = Sh(shell)
        sh.expect([r"\$ $", r"# $"], 30)

        tee("=== PRE: процессы/состояние ===")
        tee(run("date -u '+%Y-%m-%d %H:%M:%S UTC'; "
                "echo PROBE_PROCS=$(ps -ef | grep -c '[a]gent_checks_w1_probe'); "
                "echo OLD_OUT_BYTES=$([ -f /tmp/ac1_probe.out ] && "
                "wc -c < /tmp/ac1_probe.out || echo 0)", sh, secrets, timeout=60))
        tee(run(f"cd {APP} && PYTHONIOENCODING=utf-8 {APP}/venv/bin/python "
                f"{REMOTE_STATE}", sh, secrets, timeout=120))

        tee("=== PROBE (nohup, фазы %s, skip_image_gen=%s) ==="
            % (AC1_PHASES, AC1_SKIP_IMAGE_GEN))
        tee(run(f"cd {APP} && rm -f {OUT} && nohup env AC1_PHASES={AC1_PHASES} "
                f"AC1_SKIP_IMAGE_GEN={AC1_SKIP_IMAGE_GEN} "
                f"PYTHONIOENCODING=utf-8 {APP}/venv/bin/python {REMOTE_PROBE} "
                f"> {OUT} 2>&1 & echo STARTED_PID=$!",
                sh, secrets, timeout=60))
        # bounded polling: до 240 c
        done = False
        for i in range(48):
            time.sleep(5)
            got = run(f"grep -c 'AC1 SUMMARY' {OUT} 2>/dev/null || true",
                      sh, secrets, timeout=30)
            if "1" in got.split("\n")[-2:][0] or re.search(r"\n1\s*\n", got):
                done = True
                break
        tee(f"[runner] probe finished={done} (poll iterations={i + 1})")
        tee("=== PROBE OUTPUT ===")
        tee(run(f"cat {OUT}", sh, secrets, timeout=120))

        tee("=== POST: состояние после прогона ===")
        tee(run(f"cd {APP} && PYTHONIOENCODING=utf-8 {APP}/venv/bin/python "
                f"{REMOTE_STATE}", sh, secrets, timeout=120))
        tee("=== POST: journal окна (read-only, sudo) ===")
        tee(sudo_run(
            "journalctl -u admin_bot --since '30 min ago' --no-pager | "
            "grep -c ' ERROR ' ; echo ---ERR_END; "
            "journalctl -u admin_bot --since '30 min ago' --no-pager | "
            "grep -c ' CRITICAL ' ; echo ---CRIT_END; "
            "journalctl -u admin_bot --since '30 min ago' --no-pager | "
            "grep -c 'Traceback' ; echo ---TB_END; "
            "journalctl -u admin_bot --since '30 min ago' -o short-iso --no-pager "
            "| grep -c '\\[tma-auth\\].*valid=True' ; echo ---TMA_END; "
            "curl -s http://127.0.0.1:8000/healthz",
            sh, pw, secrets, timeout=240))
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
