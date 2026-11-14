# -*- coding: utf-8 -*-
"""Upload the harness, run it in ONE SSH session, download evidence, clean up."""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, r"C:\Users\main\.config\opencode\WorkspaceData\runs"
                   r"\c742e4de9e92c489\vmq-q1-39dc7cff5121\temp-13fea3ab4b")
import prod_conn as P  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
BASE = "/root/vmq2/measure"
UPLOADS = {
    "cand.bundle": HERE / "cand.bundle",
    "probe.py": HERE / "probe.py",
    "entities.py": HERE / "entities.py",
    "cfg_probe.py": HERE / "cfg_probe.py",
    "driver.sh": HERE / "driver.sh",
}
DOWNLOADS = ("base.json", "cand.json", "sha256.txt", "dbcopy.sha256")
CLEANUP = (
    "chmod -R u+w {b}/repo-base {b}/repo-cand 2>/dev/null; "
    "rm -rf {b}/repo-base {b}/repo-cand {b}/out {b}/entities.json "
    "{b}/cfg.json {b}/dbcopy.db {b}/dbcopy.db-wal {b}/dbcopy.db-shm "
    "{b}/cand.bundle {b}/probe.py {b}/entities.py {b}/cfg_probe.py "
    "{b}/driver.sh; rmdir {b} 2>/dev/null; "
    "echo left:; ls -la /root/vmq2 2>&1 | tail -4"
).format(b=BASE)


def main() -> int:
    cli = P.connect(timeout=25.0)
    try:
        rc, out, err = P.run(cli, "mkdir -p %s/out && df -Pk /root | tail -1"
                             % BASE, timeout=60)
        print("mkdir rc=%s %s %s" % (rc, out.strip(), err.strip()[:200]))
        sftp = cli.open_sftp()
        try:
            for name, local in UPLOADS.items():
                payload = local.read_bytes()
                if not name.endswith(".bundle"):
                    payload = payload.replace(b"\r\n", b"\n")
                remote = "%s/%s" % (BASE, name)
                with sftp.open(remote, "wb") as fh:
                    fh.write(payload)
                print("uploaded %-12s %8d bytes sha256=%s"
                      % (name, len(payload),
                         hashlib.sha256(payload).hexdigest()[:12]),
                      flush=True)
        finally:
            sftp.close()
        rc, out, err = P.run(cli, "bash %s/driver.sh" % BASE, timeout=3600)
        print(out)
        if err.strip():
            print("[stderr] " + err[-3000:])
        print("DRIVER_RC=%s" % rc)

        got = {}
        sftp = cli.open_sftp()
        try:
            for name in DOWNLOADS:
                remote = "%s/out/%s" % (BASE, name)
                local = HERE / name
                try:
                    sftp.get(remote, str(local))
                    digest = hashlib.sha256(local.read_bytes()).hexdigest()
                    got[name] = (local.stat().st_size, digest[:16])
                    print("downloaded %-14s %8d sha256=%s"
                          % (name, local.stat().st_size, digest[:16]))
                except OSError as exc:
                    print("download FAILED %s: %s" % (name, exc))
        finally:
            sftp.close()
        rc2, out2, err2 = P.run(cli, CLEANUP, timeout=600)
        print(out2.strip())
        if err2.strip():
            print("[cleanup stderr] " + err2[-500:])
        print("CLEANUP_RC=%s" % rc2)
        return 0 if got.get("base.json") and got.get("cand.json") else 1
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
