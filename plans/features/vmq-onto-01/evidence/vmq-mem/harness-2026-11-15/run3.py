# -*- coding: utf-8 -*-
"""Run the focused relations probe in one SSH session, download, clean up."""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, r"C:\Users\main\.config\opencode\WorkspaceData\runs"
                   r"\c742e4de9e92c489\vmq-q1-39dc7cff5121\temp-13fea3ab4b")
import prod_conn as P  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
BASE = "/root/vmq2/measure3"
UPLOADS = {
    "cand.bundle": HERE / "cand.bundle",
    "entities.py": HERE / "entities.py",
    "cfg_probe.py": HERE / "cfg_probe.py",
    "relations_probe.py": HERE / "relations_probe.py",
    "driver3.sh": HERE / "driver3.sh",
}
DOWNLOADS = ("rel-base.json", "rel-cand.json")
CLEANUP = (
    "chmod -R u+w {b}/repo-base {b}/repo-cand 2>/dev/null; "
    "rm -rf {b}/repo-base {b}/repo-cand {b}/out {b}/entities.json "
    "{b}/cfg.json {b}/dbcopy.db {b}/dbcopy.db-wal {b}/dbcopy.db-shm "
    "{b}/cand.bundle {b}/entities.py {b}/cfg_probe.py "
    "{b}/relations_probe.py {b}/driver3.sh; rmdir {b} 2>/dev/null; "
    "ls -la /root/vmq2 2>&1 | tail -3"
).format(b=BASE)


def main() -> int:
    cli = P.connect(timeout=25.0)
    try:
        rc, out, err = P.run(cli, "mkdir -p %s/out" % BASE, timeout=60)
        print("mkdir rc=%s %s %s" % (rc, out.strip(), err.strip()[:200]))
        sftp = cli.open_sftp()
        try:
            for name, local in UPLOADS.items():
                payload = local.read_bytes()
                if not name.endswith(".bundle"):
                    payload = payload.replace(b"\r\n", b"\n")
                with sftp.open("%s/%s" % (BASE, name), "wb") as fh:
                    fh.write(payload)
                print("uploaded %-20s %7d sha256=%s"
                      % (name, len(payload),
                         hashlib.sha256(payload).hexdigest()[:12]))
        finally:
            sftp.close()
        rc, out, err = P.run(cli, "bash %s/driver3.sh" % BASE, timeout=2400)
        print(out)
        if err.strip():
            print("[stderr] " + err[-2000:])
        print("DRIVER_RC=%s" % rc)
        sftp = cli.open_sftp()
        try:
            for name in DOWNLOADS:
                local = HERE / name
                try:
                    sftp.get("%s/out/%s" % (BASE, name), str(local))
                    print("downloaded %-16s %7d sha256=%s"
                          % (name, local.stat().st_size,
                             hashlib.sha256(local.read_bytes()).hexdigest()[:16]))
                except OSError as exc:
                    print("download FAILED %s: %s" % (name, exc))
        finally:
            sftp.close()
        rc2, out2, err2 = P.run(cli, CLEANUP, timeout=600)
        print(out2.strip())
        if err2.strip():
            print("[cleanup stderr] " + err2[-400:])
        print("CLEANUP_RC=%s" % rc2)
        return 0
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
