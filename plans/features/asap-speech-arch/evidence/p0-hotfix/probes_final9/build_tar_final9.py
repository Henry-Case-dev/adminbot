"""Build the exact-candidate archive for /tmp/p0-final9 (no plans/tests/media)."""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile

WT = r"C:\Code\Python\adminbot-wt-speech-p0"
CAND = "e2d9b3357c29838bb89943f5df1f53587da2e639"
OUT = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\final9\new_code.tar.gz"
EXCLUDE = ("plans", "media", "extra_images", "tests")


def main() -> int:
    raw = subprocess.run(["git", "-C", WT, "archive", "--format=tar", CAND],
                         check=True, capture_output=True).stdout
    src = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    kept = skipped = 0
    with tarfile.open(OUT, "w:gz", compresslevel=6) as dst:
        for info in src.getmembers():
            if info.name.split("/")[0] in EXCLUDE:
                skipped += 1
                continue
            dst.addfile(info, src.extractfile(info) if info.isfile() else None)
            kept += 1
    h = hashlib.sha256()
    with open(OUT, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    print({"commit": CAND, "kept": kept, "skipped": skipped,
           "bytes": os.path.getsize(OUT), "sha256": h.hexdigest()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
