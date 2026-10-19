# -*- coding: utf-8 -*-
"""One SSH session: final cleanup of doubled-run leftovers + diag fix + markers."""
from __future__ import annotations

import importlib.util
import sys

SPEC = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\acceptance-97\run_accept97.py"
spec = importlib.util.spec_from_file_location("run97", SPEC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FILES = {"accept97_final_clean.py": "/tmp/accept97_final_clean.py"}
SINCE = "2026-10-19 20:12:00"


def main() -> int:
    r = mod.Runner(mod._pwd())
    try:
        r.connect()
        r.step("RECON", r.run,
               "date -u '+%Y-%m-%d %H:%M:%S UTC'; "
               "systemctl show admin_bot -p MainPID -p NRestarts -p "
               "ActiveState --no-pager; "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               "curl -s https://admin-bot.duckdns.org/healthz; echo", 60)
        if r.harness_sudo:
            r.maybe_root("true", timeout=30)
        sftp = r.client.open_sftp()
        try:
            for name, remote in FILES.items():
                sftp.put(str(mod.LOCAL / name), remote)
                r.emit("[runner] uploaded %s" % name)
        finally:
            sftp.close()
        rc, o, e = r.step("FINAL_CLEAN", r.maybe_root,
                          "cd %s && ./venv/bin/python "
                          "/tmp/accept97_final_clean.py" % mod.APP,
                          timeout=600)
        try:
            r.sftp_get("/tmp/accept97/evidence/final-clean.json",
                       mod.LOCAL / "evidence" / "final-clean.json")
            r.emit("[runner] downloaded final-clean.json")
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] final-clean.json FAILED %s"
                   % type(exc).__name__)
        r.step("MARKERS", r.run,
               "systemctl show admin_bot -p MainPID -p NRestarts "
               "-p ExecMainStatus -p ActiveState --no-pager; "
               "curl -s http://127.0.0.1:8000/healthz; echo; "
               "curl -s https://admin-bot.duckdns.org/healthz; echo; "
               f"cd {mod.APP} && ./venv/bin/python -c \"import sqlite3;from "
               "config.settings import settings as s;"
               "print('USER_VERSION='+str(sqlite3.connect(s.DB_PATH).execute("
               "'PRAGMA user_version').fetchone()[0]))\" 2>&1 | tail -1; "
               f"echo ERR_WAVE=$(journalctl -u admin_bot --since '{SINCE}' "
               "--no-pager 2>/dev/null | grep -cE 'ERROR|CRITICAL|Traceback'); "
               f"echo LOCK_WAVE=$(journalctl -u admin_bot --since '{SINCE}' "
               "--no-pager 2>/dev/null | grep -cE 'database is locked|lock "
               "exhausted'); "
               f"echo SKIPS_T0=$(journalctl -u admin_bot --since "
               f"'{mod.DEPLOY_T0}' --no-pager 2>/dev/null | grep -c "
               "'maximum number of running instances'); "
               "cd %s && echo HEAD=$(git rev-parse HEAD) "
               "TRACKED_MOD=$(git status --porcelain | grep -v '^??' | wc -l)"
               % mod.APP, timeout=180)
        return 0
    finally:
        r.close()
        out = mod.LOCAL / "logs" / "final-clean.log"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(r.lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
