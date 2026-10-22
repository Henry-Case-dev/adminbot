# -*- coding: utf-8 -*-
"""Mutation witnesses for the re-recorded OFF-path baseline.

Each case mutates the baseline file, runs the target test, restores the file
and reports whether the test detected the mutation. A baseline that still
passes with a mutated body/metrics would be "tuned", not a contract.
"""
import io
import subprocess
import sys

ROOT = r"C:\Code\Python\adminbot"
FIX = ROOT + r"\tests\fixtures\soul1\direct-runtime-assembly-asap2.txt"
PY = ROOT + r"\.venv\Scripts\python.exe"

CASES = [
    ("MUT1 body char (P4 SYSTEM text)",
     "Естественные вопросы в обычном живом разговоре",
     "Естественные вопросы в обычном живом разговореX"),
    ("MUT2 metric sha line (P2 SYSTEM)",
     "## P2  Direct L2 WRITER (extent=micro)\nSYSTEM  chars=3073 tokens=769 "
     "sha256_12=d7281532954d",
     "## P2  Direct L2 WRITER (extent=micro)\nSYSTEM  chars=3073 tokens=769 "
     "sha256_12=d7281532954e"),
    ("MUT3 body char (P1 USER text)",
     "<Context>окно чата</Context>", "<Context>окно чата!X</Context>"),
    ("MUT4 metric chars line (P5b SYSTEM)",
     "## P5b  System2 Stage-2 (verbalizer over JSON report)\n"
     "SYSTEM  chars=3225 tokens=807 sha256_12=1d4c51c39147",
     "## P5b  System2 Stage-2 (verbalizer over JSON report)\n"
     "SYSTEM  chars=3226 tokens=807 sha256_12=1d4c51c39147"),
]


def run():
    p = subprocess.run([PY, "-m", "pytest",
                        "tests/test_soul1_composer_parity_off.py", "-q"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (p.stdout or "").strip().splitlines()
    return p.returncode, tail[-1] if tail else ""


def main():
    original = io.open(FIX, encoding="utf-8", newline="").read()
    rc0, line0 = run()
    print(f"baseline: rc={rc0} | {line0}")
    try:
        for name, old, new in CASES:
            assert original.count(old) == 1, (name, original.count(old))
            io.open(FIX, "w", encoding="utf-8", newline="").write(
                original.replace(old, new, 1))
            rc, line = run()
            print(f"{name}: rc={rc} | {line} | "
                  f"{'DETECTED' if rc != 0 else 'NOT DETECTED'}")
    finally:
        io.open(FIX, "w", encoding="utf-8", newline="").write(original)
    rc1, line1 = run()
    print(f"restored: rc={rc1} | {line1}")
    return 0 if rc0 == 0 and rc1 == 0 else 1


sys.exit(main())
