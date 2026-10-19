# -*- coding: utf-8 -*-
"""One SSH session: residual synthetic-turn cleanup + download the register."""
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
            sftp.put(str(mod.LOCAL / "accept97_residual_clean.py"),
                     "/tmp/accept97_residual_clean.py")
            r.emit("[runner] uploaded residual-clean script")
        finally:
            sftp.close()
        r.step("RESIDUAL", r.run,
               "cd %s && ./venv/bin/python /tmp/accept97_residual_clean.py"
               % mod.APP, timeout=300)
        try:
            r.sftp_get("/tmp/accept97/residual-clean.json",
                       mod.LOCAL / "evidence" / "residual-clean.json")
            r.emit("[runner] downloaded residual-clean.json")
        except Exception as exc:  # noqa: BLE001
            r.emit("[download] residual-clean.json FAILED %s"
                   % type(exc).__name__)
        return 0
    finally:
        r.close()
        out = mod.LOCAL / "logs" / "residual-clean.log"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(r.lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
