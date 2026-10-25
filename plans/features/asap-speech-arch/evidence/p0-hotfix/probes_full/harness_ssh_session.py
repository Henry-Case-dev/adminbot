"""Single-SSH-session interactive runner (fail2ban-safe).

Keeps one SSH connection open and executes commands appended to a local queue
file, appending output to a local log. Exit with __EXIT__ or after idle timeout.
No writes to prod DBs are issued by the commands themselves.
"""
from __future__ import annotations

import json
import os
import sys
import time

import paramiko

HOST = "198.46.175.136"
USER = "nik"
OUT_DIR = r"C:\Users\main\AppData\Local\Temp\opencode"
CMD_FILE = os.path.join(OUT_DIR, "p0_cmd.txt")
LOG_FILE = os.path.join(OUT_DIR, "p0_out.txt")
DEPLOY_CMDS = r"C:\Code\Python\adminbot\deploy_commands.txt"
UPLOADS = {
    os.path.join(OUT_DIR, "probe_full.py"): "/tmp/p0-full-new/probe_full.py",
    os.path.join(OUT_DIR, "p0_dump.py"): "/tmp/p0_dump.py",
}
IDLE_LIMIT_S = float(os.environ.get("P0_IDLE_LIMIT", "2400"))


def password() -> str:
    for line in open(DEPLOY_CMDS, encoding="utf-8", errors="replace"):
        s = line.strip()
        low = s.lower()
        if low.startswith("pass:"):
            return s.split(":", 1)[1].strip()
        if low.startswith("pass="):
            return s.split("=", 1)[1].strip()
    raise SystemExit("no password line")


def key():
    path = os.path.expanduser("~/.ssh/id_ed25519")
    if os.path.exists(path):
        return paramiko.Ed25519Key.from_private_key_file(path)
    return None


def run(client, cmd, timeout=600):
    chan = client.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out, err = b"", b""
    t0 = time.time()
    while True:
        if chan.recv_ready():
            out += chan.recv(65536)
        if chan.recv_stderr_ready():
            err += chan.recv_stderr(65536)
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        if time.time() - t0 > timeout:
            break
        time.sleep(0.05)
    code = chan.recv_exit_status()
    chan.close()
    return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def log(text):
    with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
        f.write(text + "\n")
        f.flush()


def main() -> int:
    open(CMD_FILE, "w", encoding="utf-8").close()
    open(LOG_FILE, "w", encoding="utf-8").close()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=22, username=USER, pkey=key(),
                   password=password(), look_for_keys=False, allow_agent=False,
                   timeout=25, banner_timeout=25, auth_timeout=25)
    sftp = client.open_sftp()
    for local, remote in UPLOADS.items():
        sftp.put(local, remote)
    sftp.close()
    log("READY connection up")
    seen = 0
    last = time.time()
    while True:
        lines = [l.rstrip("\n") for l in open(CMD_FILE, encoding="utf-8",
                                             errors="replace").read().splitlines() if l.strip()]
        if seen >= len(lines):
            if time.time() - last > IDLE_LIMIT_S:
                log("IDLE_TIMEOUT")
                break
            time.sleep(1.0)
            continue
        cmd = lines[seen]
        seen += 1
        last = time.time()
        if cmd == "__EXIT__":
            log("EXIT_OK")
            break
        log(">>> %s" % cmd)
        try:
            code, out, err = run(client, cmd, timeout=900)
        except Exception as exc:                          # noqa: BLE001
            log("EXC %s: %s" % (type(exc).__name__, str(exc)[:300]))
            continue
        log("<<< rc=%s" % code)
        if out.strip():
            log(out[-8000:])
        if err.strip():
            log("[stderr] " + err[-3000:])
    client.close()
    log("CLOSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
