"""Single-SSH-session driver #2: stage new code (py-only), dump read-only context.

One TCP/SSH connection for everything (fail2ban). No writes to prod DBs.
"""
from __future__ import annotations

import json
import os
import sys
import time

import paramiko

HOST = "198.46.175.136"
USER = "nik"
LOCAL_TAR = r"C:\Users\main\AppData\Local\Temp\opencode\p0_new_code.tar.gz"
LOCAL_DUMP_SCRIPT = r"C:\Users\main\AppData\Local\Temp\opencode\p0_dump.py"
OUT_DIR = r"C:\Users\main\AppData\Local\Temp\opencode"
DEPLOY_CMDS = r"C:\Code\Python\adminbot\deploy_commands.txt"

PY_DISCOVER = r'''
PY=""
for c in /var/www/admin_bot/.venv/bin/python /var/www/admin_bot/venv/bin/python \
         /var/www/admin_bot/env/bin/python /var/www/admin_bot/.venv/bin/python3 \
         $(systemctl show -p ExecStart --value admin_bot 2>/dev/null | sed -n 's/.*path=\([^ ;]*\).*/\1/p') \
         $(command -v python3); do
  [ -x "$c" ] || continue
  if "$c" -c "import asyncpg" 2>/dev/null; then PY="$c"; break; fi
done
echo PY=$PY
'''


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


def run(client, cmd, timeout=900):
    chan = client.get_transport().open_session()
    chan.settimeout(timeout)
    chan.exec_command(cmd)
    out, err = b"", b""
    while True:
        if chan.recv_ready():
            out += chan.recv(65536)
        if chan.recv_stderr_ready():
            err += chan.recv_stderr(65536)
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        time.sleep(0.05)
    code = chan.recv_exit_status()
    chan.close()
    return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    t0 = time.time()
    client.connect(HOST, port=22, username=USER, pkey=key(),
                   password=password(), look_for_keys=False, allow_agent=False,
                   timeout=25, banner_timeout=25, auth_timeout=25)
    print("SSH_UP %.1fs" % (time.time() - t0))
    steps = []
    log = lambda name, code, out, err: (steps.append(
        {"step": name, "code": code, "out": out.strip()[-1600:],
         "err": err.strip()[-600:]}),
        print("== %s (rc=%s)\n%s\n%s" % (name, code, out.strip()[-1600:], err.strip()[-600:])))
    try:
        sftp = client.open_sftp()
        sftp.put(LOCAL_DUMP_SCRIPT, "/tmp/p0_dump.py")
        sftp.put(LOCAL_TAR, "/tmp/p0_new_code.tar.gz")
        sftp.close()

        command = "\n".join([
            "df -h /tmp | tail -1",
            "git -C /var/www/admin_bot rev-parse --short HEAD",
            PY_DISCOVER,
            "rm -rf /tmp/p0-full-new && mkdir -p /tmp/p0-full-new",
            "cd /tmp/p0-full-new && tar -xzf /tmp/p0_new_code.tar.gz && echo TAR_OK=1",
            "cp -f /var/www/admin_bot/.env /tmp/p0-full-new/.env && echo ENV_OK=1",
            "grep -c '_renders_extent_block' /tmp/p0-full-new/services/direct_l1.py",
            "grep -c 'analysis_directive_needed' /tmp/p0-full-new/services/direct_l1.py",
        ])
        code, out, err = run(client, command, timeout=300)
        log("stage", code, out, err)

        py_line = [l for l in out.splitlines() if l.startswith("PY=")]
        py = py_line[-1].split("=", 1)[1].strip() if py_line else ""
        if not py:
            raise SystemExit("interpreter not found")

        code, out, err = run(
            client,
            "cd /tmp/p0-full-new && %s -c \"import services.direct_l1, "
            "services.prompt_composer, services.prompt_style_blocks, "
            "services.mca_expression, services.response_extent; "
            "print('IMPORT_OK', services.direct_l1.__file__)\"" % py,
            timeout=300)
        log("import_new", code, out, err)

        code, out, err = run(
            client,
            "%s /tmp/p0_dump.py --root /var/www/admin_bot "
            "--out /tmp/p0_pg_dump.json --out-sqlite /tmp/p0_sqlite_dump.json" % py,
            timeout=900)
        log("dump", code, out, err)

        code, out, err = run(client, "ls -l /tmp/p0_pg_dump.json /tmp/p0_sqlite_dump.json; md5sum /tmp/p0_pg_dump.json /tmp/p0_sqlite_dump.json", timeout=120)
        log("files", code, out, err)

        sftp = client.open_sftp()
        sftp.get("/tmp/p0_pg_dump.json", os.path.join(OUT_DIR, "p0_pg_dump.json"))
        sftp.get("/tmp/p0_sqlite_dump.json", os.path.join(OUT_DIR, "p0_sqlite_dump.json"))
        sftp.close()
        print("FETCH_OK")
    finally:
        client.close()
    json.dump({"elapsed_s": round(time.time() - t0, 1), "steps": steps},
              open(os.path.join(OUT_DIR, "p0_ssh_log2.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SSH_DONE %.1fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
