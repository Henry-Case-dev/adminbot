# -*- coding: utf-8 -*-
"""ASAP-3.1: второй проход пинов — categorized 458→459 в локальных
переменных (categorized = [s for s in pc.REGISTRY.values() if s.category])."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
patched = []
for p in sorted(TESTS.glob("test_*.py")):
    text = p.read_text(encoding="utf-8")
    original = text
    # len(categorized) == 458 → 459 (локальные списки categorized/каталог).
    text = re.sub(r"(len\(categorized\)\s*==\s*)458\b", r"\g<1>459", text)
    text = re.sub(r"(len\(catalog\)\s*==\s*)458\b", r"\g<1>459", text)
    if text != original:
        p.write_text(text, encoding="utf-8")
        patched.append(p.name)
print("patched:", len(patched))
for name in patched:
    print(" -", name)
