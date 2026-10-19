# -*- coding: utf-8 -*-
"""CFG-04 live matrix digest (C.1-7 evidence table)."""
from __future__ import annotations

import json
import sys

d = json.loads(open(sys.argv[1], encoding="utf-8").read())
rows = []
for name, vp in d["viewports"].items():
    c = vp.get("config_dirty") or {}
    kb = vp.get("config_keyboard") or {}
    kp = kb.get("panel") or {}
    lf = vp.get("last_field") or {}
    tk = vp.get("tech_key") or {}
    tko = vp.get("tech_key_open") or {}
    tkc = vp.get("tech_key_copy") or {}
    ori = vp.get("orientation") or {}
    tog = vp.get("toggle") or {}
    rows.append({
        "vp": name, "safe": vp.get("safe_bottom"),
        "cta": c.get("ctaCount"), "chip_role": (c.get("chip") or {}).get("role"),
        "chip_text": (c.get("chip") or {}).get("text", "").replace("\n", " "),
        "dirty": c.get("dirtyCount"),
        "padBottom": c.get("panelPadBottom"),
        "panelH": (c.get("panel") or {}).get("h"),
        "saveH": (c.get("btnSave") or {}).get("h"),
        "cancelH": (c.get("btnCancel") or {}).get("h"),
        "kb": kb.get("kb"), "kbPanelTop": kp.get("y"),
        "kbPanelBottom": kp.get("bottom"),
        "lastOverlap": lf.get("overlap"), "caret": lf.get("caretVisible"),
        "fieldCount": c.get("fieldCount"),
        "key": tk.get("found"), "keyFull": tko.get("fullText") == tk.get("title"),
        "copyEq": (tkc.get("clipboard") or "") == (tk.get("title") or ""),
        "cards": len(c.get("cardWidths") or []),
        "orient": ({k: ori["after"].get(k) for k in ("value_ok", "dirty_ok",
                                                     "hash_ok", "scroll_ok",
                                                     "active_ok")}
                   if ori else None),
        "toggle": [tog.get("w"), tog.get("h")],
        "gridColumns": c.get("gridColumns"),
        "overflowDoc": c.get("overflowDoc"),
        "module": (vp.get("module_open") or {}).get("opened"),
        "moduleCTA": (vp.get("module_dirty") or {}).get("ctaCount"),
    })
out = {"failures": d.get("failures"), "console_errors": d.get("console_errors"),
       "live_url": d.get("live_url"), "shots": len(d.get("screenshots") or []),
       "rows": rows}
open(sys.argv[2], "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
