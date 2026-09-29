# -*- coding: utf-8 -*-
"""ASAP-3.1: массовое переиздание каталожных/версионных пинов релизных
тестов (санкция spec 10.1: REGISTRY 483→484, categorized 458→459, delta
72→73, APP_VERSION 2.58.36→2.58.37; прецедент ASAP-3 §6). Контекстные
замены только пин-паттернов, не произвольных чисел."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

REGISTRY_PATTERNS = [
    (re.compile(r"(len\(pc\.REGISTRY\)\s*==\s*)483\b"), r"\g<1>484"),
    (re.compile(r"(len\(pc\.REGISTRY\)\s*==\s*FIXTURE\[.counts.\]\[.REGISTRY.\]\s*==\s*)483\b"), r"\g<1>484"),
    (re.compile(r"(len\(rows\)\s*==\s*)483\b"), r"\g<1>484"),
    (re.compile(r"(_REGISTRY_COUNT\s*=\s*)483\b"), r"\g<1>484"),
    (re.compile(r"(REGISTRY.*?==\s*)483\b(?!\\d)"), r"\g<1>484"),
    (re.compile(r"(registry_count.*?483\b)"), r"\g<1>".replace("483", "484")),
    (re.compile(r"(category is not None\]\)\s*==\s*)458\b"), r"\g<1>459"),
    (re.compile(r"(len\(delta\)\s*==\s*FIXTURE\[.counts.\]\[.delta.\]\s*==\s*)72\b"), r"\g<1>73"),
]
VERSION_PATTERNS = [
    (re.compile(r'"2\.58\.36"'), '"2.58.37"'),
    (re.compile(r"'2\.58\.36'"), "'2.58.37'"),
]

changed = []
for p in sorted(TESTS.glob("test_*.py")):
    text = p.read_text(encoding="utf-8")
    original = text
    for pattern, repl in REGISTRY_PATTERNS:
        text = pattern.sub(repl, text)
    for pattern, repl in VERSION_PATTERNS:
        text = pattern.sub(repl, text)
    if text != original:
        p.write_text(text, encoding="utf-8")
        changed.append(p.name)

print("patched:", len(changed))
for name in changed:
    print(" -", name)
