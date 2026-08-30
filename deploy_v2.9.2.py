#!/usr/bin/env python3
"""Deploy AdminBot v2.9.2 to 198.46.175.136 using paramiko.

SANITIZED (этап зачистки): хардкод-секреты PASSWORD / GIT_PASSWORD /
SUDO_PASSWORD убраны. SSH-пароль: env DEPLOY_SSH_PASSWORD → иначе getpass
(без эха). GIT_PASSWORD в исходнике был объявлен, но нигде не использовался —
удалён как мёртвый секрет (git pull на сервере идёт под деплой-ключом/иным
механизмом, скрипт его не применяет).
"""
import getpass
import json
import os
import re
import sys
import time
import paramiko

HOST = "198.46.175.136"
PORT = 22
USER = "nik"
PROJECT_DIR = "/var/www/admin_bot"


def _password() -> str:
    """SSH/SUDO-пароль: env DEPLOY_SSH_PASSWORD → иначе интерактивный getpass."""
    value = os.getenv("DEPLOY_SSH_PASSWORD", "").strip()
    if value:
        return value
    return getpass.getpass(f"SSH/sudo password for {USER}@{HOST}: ")


def run_cmd(client: paramiko.SSHClient, cmd: str, timeout: float = 15.0) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def run_sudo(client: paramiko.SSHClient, cmd: str, sudo_password: str, timeout: float = 20.0) -> tuple[int, str, str]:
    safe_pass = sudo_password.replace("'", "'\\''")
    full_cmd = f"echo '{safe_pass}' | sudo -S {cmd}"
    return run_cmd(client, full_cmd, timeout)


def clean(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)


def parse_status(output: str) -> dict:
    result = {"pid": None, "active": "unknown"}
    m = re.search(r"Main PID:\s*(\d+)", output)
    if m:
        result["pid"] = int(m.group(1))
    m = re.search(r"Active:\s*(\S+(?:\s+\([^)]+\))?)", output)
    if m:
        raw = m.group(1).lower()
        if "running" in raw:
            result["active"] = "running"
        elif "dead" in raw or "inactive" in raw or "failed" in raw:
            result["active"] = "dead"
        else:
            result["active"] = raw
    return result


def parse_logs(output: str) -> list[str]:
    lines = clean(output).split("\n")
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Filter out sudo password prompt noise
        if "[sudo] password" in line:
            continue
        out.append(line)
    return out[-10:]


def main():
    result = {"status": "error", "pid": None, "active": "unknown", "last_logs": [], "steps": {}}

    password = _password()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print("[1/5] Connecting to", HOST, "...")
        client.connect(HOST, PORT, USER, password, timeout=15, allow_agent=False, look_for_keys=False)
        print("  Connected.")

        # Step 1: git pull
        print("[2/5] git pull...")
        rc, git_out, git_err = run_cmd(client, f"cd {PROJECT_DIR} && git pull 2>&1", timeout=30)
        result["steps"]["git_pull"] = clean(git_out + git_err).strip()
        print(f"  git pull rc={rc}")

        # Step 2: restart
        print("[3/5] sudo systemctl restart admin_bot...")
        rc, out, err = run_sudo(client, "systemctl restart admin_bot", password)
        result["steps"]["restart"] = clean(out + err).strip()
        print(f"  restart rc={rc}")
        time.sleep(2)

        # Step 3: status
        print("[4/5] sudo systemctl status admin_bot...")
        rc, out, err = run_sudo(client, "systemctl status admin_bot --no-pager", password)
        status_raw = out + err
        result["steps"]["status"] = clean(status_raw).strip()
        parsed = parse_status(status_raw)
        result["pid"] = parsed["pid"]
        result["active"] = parsed["active"]
        print(f"  rc={rc}, PID={result['pid']}, active={result['active']}")

        # Step 4: journal
        print("[5/5] sudo journalctl -u admin_bot...")
        rc, out, err = run_sudo(client, "journalctl -u admin_bot --no-pager -n 10", password)
        journal_raw = out + err
        result["steps"]["journal"] = clean(journal_raw).strip()
        result["last_logs"] = parse_logs(journal_raw)
        print(f"  Got {len(result['last_logs'])} log lines.")

        # Final
        if result["active"] == "running" and result["pid"] is not None:
            result["status"] = "ok"
            print("\n[DEPLOY OK] Service is running.")
        else:
            result["status"] = "error"
            print(f"\n[DEPLOY WARN] active={result['active']}, pid={result['pid']}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"\n[DEPLOY FAIL] {e}")

    finally:
        client.close()

    # Clean output JSON
    json_str = json.dumps(result, indent=2, ensure_ascii=True)
    print("\n" + "=" * 60)
    print(json_str)

    with open("deploy_result.json", "w", encoding="utf-8") as f:
        f.write(json_str)

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
