# -*- coding: utf-8 -*-
"""Одноразовый скрипт: reissue каталожных пинов 483→484 в релизных тестах
(ASAP-3.1, санкция spec 10.1; прецедент ASAP-3 §6)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
files = [
    "tests/test_summary_publish_integration_round1026.py",
    "tests/test_image_context_memory_round1026.py",
]
for rel in files:
    p = ROOT / rel
    t = p.read_text(encoding="utf-8")
    changed = 0
    if "len(pc.REGISTRY) == 483" in t:
        t = t.replace("len(pc.REGISTRY) == 483",
                      "len(pc.REGISTRY) == 484")
        changed += 1
    # Комментарий-маркер санкции при первом вхождении.
    t = t.replace(
        "assert len(pc.REGISTRY) == 484",
        "# ASAP-3.1 (ADR-1028-3, санкция spec 10.1): +1 ключ → 484.\n"
        "        assert len(pc.REGISTRY) == 484", 1)
    p.write_text(t, encoding="utf-8")
    print(rel, "patched" if changed else "no REGISTRY pin")
