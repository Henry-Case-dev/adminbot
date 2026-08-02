#!/usr/bin/env python3
"""
Remote AdminBot status checker via paramiko.
Server: 198.46.175.136 / User: nik / Path: /var/www/admin_bot
Sudo commands: invoke_shell → send cmd → wait 1s → send password+\\n → wait 3s
"""

import paramiko
import time
import sys

HOST = "198.46.175.136"
PORT = 22
USER = "nik"
PASSWORD = "aUt44)FO1lDm"
WORKDIR = "/var/www/admin_bot"


def run_via_shell(ssh: paramiko.SSHClient, cmd: str, sudo: bool = False) -> str:
    """
    Execute command via invoke_shell.
    If sudo=True: sends command, waits 1s, sends password+\\n, waits 3s.
    """
    print(f"\n  [shell] {cmd}")
    channel = ssh.invoke_shell(width=300, height=120)
    time.sleep(0.6)

    # Drain initial banner
    banner = b""
    while channel.recv_ready():
        banner += channel.recv(4096)
        time.sleep(0.1)

    # Send command
    channel.send(cmd + "\n")

    if sudo:
        time.sleep(1)
        channel.send(PASSWORD + "\n")
        time.sleep(3)
    else:
        time.sleep(2)

    # Collect output until we see a prompt or timeout
    output = ""
    deadline = time.time() + 12
    while time.time() < deadline:
        if channel.recv_ready():
            chunk = channel.recv(65536).decode("utf-8", errors="replace")
            output += chunk
            # If last line looks like a prompt, we're done
            lines = output.strip().splitlines()
            if lines:
                last = lines[-1].strip()
                if last.endswith(("$", "#", ">")) and len(last) < 80:
                    time.sleep(0.4)
                    if not channel.recv_ready():
                        break
        else:
            time.sleep(0.3)

    channel.close()
    # Clean: remove command echo and prompt lines
    cleaned = _clean_output(output, cmd)
    return cleaned


def _clean_output(raw: str, cmd_sent: str) -> str:
    """Remove the echoed command and trailing prompts."""
    lines = raw.splitlines()
    result = []
    skip_next = True  # first line is usually echoed command
    for line in lines:
        stripped = line.strip()
        # Skip echoed command
        if skip_next and (cmd_sent in stripped or stripped.startswith("$") or stripped.startswith("#")):
            skip_next = False
            continue
        # Skip blank/welcome/prompt-only lines at edges
        if stripped in ("", "$", "#"):
            continue
        if "Welcome to" in stripped:
            continue
        if "Last login" in stripped:
            continue
        if stripped.endswith("$") and len(stripped) < 50:
            continue
        if stripped.endswith("#") and len(stripped) < 50:
            continue
        result.append(line)
    return "\n".join(result).strip()


def run_exec(ssh: paramiko.SSHClient, cmd: str, timeout: int = 15) -> str:
    """Execute via exec_command (for non-sudo)."""
    print(f"\n  [exec] {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        return f"{err}\n{out}" if out else err
    return out


def main():
    print("=" * 70)
    print("  AdminBot Remote Status Check")
    print(f"  Host: {HOST}  User: {USER}  Path: {WORKDIR}")
    print("=" * 70)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print("\n[1] Connecting...")
        ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
        print("    [OK] Connected")

        # ── systemctl status (sudo via shell) ──
        print("\n[2] systemctl status admin_bot")
        status = run_via_shell(ssh, "sudo systemctl status admin_bot --no-pager -l", sudo=True)
        print(status)

        # ── PID ──
        print("\n[3] PID")
        pid = run_exec(ssh, "systemctl show admin_bot --property=MainPID")
        print(pid)

        # ── journalctl logs (sudo via shell) ──
        print("\n[4] journalctl -u admin_bot -n 20")
        logs = run_via_shell(ssh, "sudo journalctl -u admin_bot --no-pager -n 20", sudo=True)
        print(logs)

        # ── git log ──
        print("\n[5] git log --oneline -3")
        git_log = run_exec(ssh, f"cd {WORKDIR} && git log --oneline -3")
        print(git_log)

        # ── Error search (sudo via shell, combined) ──
        print("\n[6] Searching errors (war_alert / slavic / photo / forward)")
        err_search = run_via_shell(
            ssh,
            "sudo journalctl -u admin_bot --no-pager -n 500 --output=cat 2>/dev/null | grep -iE 'war_alert|slavic|photo|forward|error|traceback|exception' | tail -30",
            sudo=True,
        )
        print(err_search if err_search else "    (no matching errors found)")

        print("\n" + "=" * 70)
        print("  CHECK COMPLETE")
        print("=" * 70)

    except Exception as e:
        print(f"\n!!! FATAL: {e}")
        sys.exit(1)
    finally:
        ssh.close()
        print("  SSH closed.")


if __name__ == "__main__":
    main()
