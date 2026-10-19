# -*- coding: utf-8 -*-
"""Served-marker counts on the downloaded prod bytes (same metric as rel97)."""
from __future__ import annotations

import json
import sys

ROOT = sys.argv[1]
OUT = sys.argv[2]
ver = "2.58.97"


def count_lines(path, needle):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if needle in line)


html = ROOT + r"\web\index.html"
css = ROOT + r"\web\static\app.css"
data = {
    "PAGE_VER": count_lines(html, ver),
    "SUBST_CSS": count_lines(css, ver),
    "STICKY_SAVE_SERVED": count_lines(html, "sticky-save"),
    "CFG04_SAVE_INDICATOR": count_lines(html, "data-save-indicator"),
    "CFG04_TECH_KEY_LINES": count_lines(html, "tech-key"),
    "CFG04_KB_OFFSET_CSS": count_lines(css, "--kb-offset"),
    "CFG04_SAFE_AREA": count_lines(css, "safe-area-inset-bottom"),
}
open(OUT, "w", encoding="utf-8").write(json.dumps(data, indent=1))
print(json.dumps(data, indent=1))
