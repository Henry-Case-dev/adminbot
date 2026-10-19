# -*- coding: utf-8 -*-
"""One SSH session: run the final verify script and download its JSON."""
from __future__ import annotations

import importlib.util
import sys

SPEC = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\acceptance-97\run_accept97.py"
spec = importlib.util.spec_from_file_location("run97", SPEC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> int:
    r = mod.Runner(mod._pwd())
    try:
        r.connect()
        sftp = r.client.open_sftp()
        try:
            sftp.put(str(mod.LOCAL / "accept97_final_verify.py"),
                     "/tmp/accept97_final_verify.py")
            r.emit("[runner] uploaded verify script")
        finally:
            sftp.close()
        r.step("VERIFY", r.run,
               "cd %s && ./venv/bin/python /tmp/accept97_final_verify.py"
               % mod.APP, timeout=300)
        try:
            r.sftp_get("/tmp/accept97/final-verify.json",
                       mod.LOCAL / "evidence" / "final-verify.json")
            r.emit("[runner] downloaded final-verify.json")
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] final-verify.json FAILED %s"
                   % type(exc).__name__)
        return 0
    finally:
        r.close()
        out = mod.LOCAL / "logs" / "final-verify.log"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(r.lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
