# -*- coding: utf-8 -*-
"""ASAP-3.1: reissue JS-харнесс пинов (APP_VERSION 2.58.36→2.58.37,
NAV_ITEMS_V2 7→8, polygon TOPO policy) в tests/js/*.js."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "tests" / "js"
changed = []
for p in sorted(JS.glob("*.js")):
    text = p.read_text(encoding="utf-8")
    original = text
    text = text.replace("2\\.58\\.36", "2\\.58\\.37")
    text = text.replace('APP_VERSION = "2.58.36"', 'APP_VERSION = "2.58.37"')
    # NAV_ITEMS_V2: ровно 7 пунктов (ON) → 8 (oversight возвращён, T-4082).
    text = re.sub(r"(NAV_ITEMS_V2[^\n]{0,80}?)\b7\b( пунктов?)",
                  r"\g<1>8\g<2>", text)
    if text != original:
        p.write_text(text, encoding="utf-8")
        changed.append(p.name)
print("patched:", len(changed))
for name in changed:
    print(" -", name)
