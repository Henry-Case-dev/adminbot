# -*- coding: utf-8 -*-
"""AGENT-CHECKS-1: runner — ОДНА SSH-сессия (paramiko) на прод 2.58.88.

Делает: короткий контекст (read-only) -> загрузка /tmp/agent_checks_w1_probe.py
через sftp в ТОЙ ЖЕ сессии -> запуск пробы (venv) -> пост-сбор журнала
(греп окон + счётчики по синтетическому чату). Креды не печатаются.
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
LOCAL_DIR = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\agent-checks-w1")
PROBE = LOCAL_DIR / "agent_checks_w1_probe.py"
LOG = Path(os.environ.get("AC1_LOG", str(LOCAL_DIR / "run-w1.log")))
REMOTE_PROBE = "/tmp/agent_checks_w1_probe.py"
SYNTH_CHAT = "-1009900000201"
AC1_PHASES = os.environ.get("AC1_PHASES", "")
AC1_SKIP_IMAGE_GEN = os.environ.get("AC1_SKIP_IMAGE_GEN", "")


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

    def send(self, cmd: str, pause: float = 0.4) -> None:
        self.shell.sendall(cmd.encode() + b"\n")
        time.sleep(pause)


def run(cmd: str, sh: Sh, secrets, *, timeout: float = 180) -> str:
    start = len(sh.buf)
    sh.search_from = start
    sh.send(cmd + '; echo "###RC=$?###"')
    # (?<![\"']) — не матчить ЭХО самой команды (там marker в кавычках)
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
    LOG.parent.mkdir(parents=True, exist_ok=True)
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
        sftp.close()
        tee(f"[runner] probe uploaded: {REMOTE_PROBE} "
            f"({PROBE.stat().st_size} bytes)")
        shell = client.invoke_shell(width=250, height=8000)
        sh = Sh(shell)
        sh.expect([r"\$ $", r"# $"], 30)

        tee("=== CTX: clock/head/healthz ===")
        tee(run("date -u '+%Y-%m-%d %H:%M:%S UTC'; cd /var/www/admin_bot && "
                "echo HEAD=$(git rev-parse HEAD) && "
                "echo TRACKED_MOD=$(git status --porcelain | grep -vc '^??' || true) && "
                "echo APP=$(grep -o 'APP_VERSION = \"2\\.[0-9]*\\.[0-9]*\"' "
                "config/settings.py | head -1) && "
                "curl -s http://127.0.0.1:8000/healthz", sh, secrets, timeout=90))
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        tee("=== PROBE RUN (venv, PYTHONIOENCODING=utf-8) ===")
        env_bits = []
        if AC1_PHASES:
            env_bits.append(f"export AC1_PHASES={AC1_PHASES}")
        if AC1_SKIP_IMAGE_GEN:
            env_bits.append(f"export AC1_SKIP_IMAGE_GEN={AC1_SKIP_IMAGE_GEN}")
        env_str = ("; ".join(env_bits) + "; ") if env_bits else ""
        tee(f"[runner] probe env: {env_str or '(все фазы)'}")
        tee(run(f"cd {APP} && {env_str}PYTHONIOENCODING=utf-8 "
                f"{APP}/venv/bin/python {REMOTE_PROBE} 2>&1",
                sh, secrets, timeout=900))
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        tee("=== POST: journal окна (read-only, sudo) ===")
        tee(sudo_run(
            "journalctl -u admin_bot --since '25 min ago' --no-pager | "
            "grep -c ' ERROR ' ; echo ---; "
            "journalctl -u admin_bot --since '25 min ago' --no-pager | "
            "grep -c ' CRITICAL ' ; echo ---; "
            "journalctl -u admin_bot --since '25 min ago' --no-pager | "
            "grep -c 'Traceback' ; echo ---; "
            "journalctl -u admin_bot --since '25 min ago' -o short-iso --no-pager "
            "| grep -c '\\[tma-auth\\].*valid=True' ; echo ---; "
            "journalctl -u admin_bot --since '25 min ago' -o short-iso --no-pager "
            f"| grep -E 'tma-auth.*path=/api/speech/style|tma-auth.*path=/api/config' "
            "| tail -6",
            sh, pw, secrets, timeout=240))

        tee("=== POST: сервис/юзер-версии (read-only) ===")
        tee(sudo_run(
            "systemctl show admin_bot -p ActiveState -p SubState -p MainPID "
            "-p NRestarts | tr '\\n' ' '; echo; "
            "curl -s --resolve admin-bot.duckdns.org:443:127.0.0.1 "
            "https://admin-bot.duckdns.org/healthz", sh, pw, secrets, timeout=90))
        tee(f"[runner] probe window start(UTC)≈{now}")
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
