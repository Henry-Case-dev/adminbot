# -*- coding: utf-8 -*-
"""Explain the 2 raw≠delivered turns: quote-character stripping only.

Usage: python make_raw_diff.py [evidence_dir]
"""
from __future__ import annotations

import difflib
import json
import pathlib
import re
import sys

EVID = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).parent


def toks(s: str):
    return re.findall(r"[а-яёa-z0-9]+", s.lower())


out = {"turns": []}
for mode in ("off", "occasional", "frequent"):
    data = json.loads((EVID / ("wave-%s.json" % mode)).read_text(
        encoding="utf-8"))
    for t in data["turns"]:
        if t["raw_eq_delivered"]:
            continue
        a, b = t["raw"], t["answer"]
        ops = [(tag, a[i1:i2], b[j1:j2])
               for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                   None, a, b).get_opcodes() if tag != "equal"]
        out["turns"].append({
            "label": t["label"], "mode": mode,
            "raw_len": len(a), "answer_len": len(b),
            "diff_ops": ops,
            "token_equal": toks(a) == toks(b),
            "only_quote_chars": all(
                x.replace('"', "").replace("«", "").replace("»", "")
                == y for _, x, y in ops),
        })
out["verdict"] = {
    "turns": len(out["turns"]),
    "all_token_equal": all(x["token_equal"] for x in out["turns"]),
    "all_quote_only": all(x["only_quote_chars"] for x in out["turns"]),
    "interpretation": ("raw == delivered по словам; отправляющий слой снимает "
                       "кавычки-обозначения UI/цитат. Это форматирование, не "
                       "postprocess_changed: мат не добавляется и не удаляется."),
}
(EVID / "raw-diff.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out["verdict"], ensure_ascii=False))
print(json.dumps(out["turns"], ensure_ascii=False)[:800])
