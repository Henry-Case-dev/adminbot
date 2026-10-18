# -*- coding: utf-8 -*-
"""AGENT-CHECKS-2: микро-recon git-статуса прод-дерева (read-only)."""
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
LOG = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\agent-checks-w2\recon-git.txt")


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


def run(cmd: str, sh: Sh, *, timeout: float = 120) -> str:
    start = len(sh.buf)
    sh.search_from = start
    sh.send(cmd + '; echo "###RC=$?###"')
    sh.expect([r'(?<!["\'])###RC=\d+###'], timeout)
    sh.search_from = len(sh.buf)
    return sh.buf[start:]


def main() -> int:
    tee = Tee(LOG)
    pw = _pwd("pass")
    client = paramiko.SSHClient()
    try:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                       auth_timeout=30, allow_agent=False, look_for_keys=False)
        shell = client.invoke_shell(width=250, height=8000)
        sh = Sh(shell)
        sh.expect([r"\$ $", r"# $"], 30)
        tee("=== prod git status (read-only) ===")
        tee(run(f"cd {APP} && git rev-parse HEAD && "
                "git status --porcelain=v1 && "
                "echo ---DIFFSTAT--- && "
                "git diff --stat | tail -n 20 && "
                "echo ---DIFF_NAMES--- && git diff --name-only", sh,
                timeout=120))
        tee("=== healthz ===")
        tee(run("curl -s http://127.0.0.1:8000/healthz", sh, timeout=60))
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
        print("RECON_EXCEPTION:", msg)
        sys.exit(4)
