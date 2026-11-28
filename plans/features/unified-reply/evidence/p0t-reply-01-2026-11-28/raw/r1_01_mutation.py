"""R1-01 mutation: Direct seam `with_ids=True` -> False must break the new
service-level test (evidence only, not a test).

Backup -> replace one exact anchor -> run the service-level case -> restore the
byte-identical backup in `finally` -> verify product file equals HEAD and the
suite is GREEN again.

Usage: python plans/features/unified-reply/evidence/p0t-reply-01-2026-11-28/raw/r1_01_mutation.py
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[6]
PY = sys.executable
DCS = ROOT / "services" / "direct_chat_service.py"

OLD = ("            with_ids=True,\n"
       "            trigger_message_id=getattr(message, \"message_id\", None),\n")
NEW = ("            with_ids=False,\n"
       "            trigger_message_id=getattr(message, \"message_id\", None),\n")

TARGET = ("tests/test_p0t_reply_target.py"
          "::test_service_actually_sends_with_ids_and_p0_refs")
SUITE = "tests/test_p0t_reply_target.py"


def run(test: str) -> tuple[int, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", test, "-q", "--no-header", "--timeout=120"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln for ln in out.splitlines()
             if ln.startswith(("FAILED", "ERROR")) or ln[:1].isdigit()]
    return proc.returncode, "\n".join(lines[-4:])


def main() -> int:
    text = DCS.read_text(encoding="utf-8")
    print(f"anchor_count={text.count(OLD)}")
    if text.count(OLD) != 1:
        print("SKIP: anchor is not unique")
        return 1
    backup = DCS.with_suffix(".r1_01.bak")
    shutil.copy2(DCS, backup)
    try:
        DCS.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        code, tail = run(TARGET)
        print(f"MUTATION with_ids=False: exit={code} -> "
              f"{'RED (good)' if code != 0 else 'GREEN (BAD)'}")
        print(tail)
    finally:
        shutil.copy2(backup, DCS)
        backup.unlink()
    restored = subprocess.run(["git", "diff", "--quiet", "HEAD", "--",
                               "services/direct_chat_service.py"], cwd=ROOT)
    print(f"product_restored_equal_HEAD={restored.returncode == 0}")
    code, tail = run(SUITE)
    print(f"RESTORED suite: exit={code}")
    print(tail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
