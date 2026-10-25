#!/usr/bin/env python3
"""Offline meta-gap recheck for LIVE-META-FINAL (same 134ac385 tree).

Why: the strict first-sentence detector used since final6 does not strip a
leading addressee ("Макс, ..."). Recompute both counts on the captured live
texts and apply the candidate guard to the two new live forms.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

ROOT = sys.argv[1]
ANALYSIS = sys.argv[2]
OUT = sys.argv[3]
sys.path.insert(0, ROOT)
os.chdir(ROOT)

STRICT = re.compile(
    r"^(?:ну|ладно|ок|окей|окэй|так|итак|сейчас|давай|глянул|посмотрел|"
    r"разложу|разберу|разберём|начну|начнём)\b", re.IGNORECASE)
ADDRESSEE = re.compile(r"^([А-ЯЁA-Z][\w\-]{1,20}),\s*(.+)$", re.UNICODE)


def first(text):
    head = str(text or "").split("\n", 1)[0]
    m = re.search(r"[.!?…]+(?=\s|$)", head)
    return (head[:m.end()] if m else head).strip()


def strip_markup(text):
    return re.sub(r"^[\s*_\"'«»]+", "", text or "")


def meta_strict(text):
    return bool(STRICT.match(strip_markup(first(text))))


def meta_addressee(text):
    head = strip_markup(first(text))
    m = ADDRESSEE.match(head)
    core = m.group(2) if m else head
    return bool(STRICT.match(core))


def sha12(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def main():
    from services import direct_chat_service as dcs

    d = json.load(open(ANALYSIS, encoding="utf-8"))
    runs = []
    strict_n = addressee_n = union_n = total = 0
    for r in d.get("runs") or []:
        if r.get("group") != "primary":
            continue
        for i, t in enumerate(r.get("l2") or []):
            text = t.get("final_text") or ""
            total += 1
            s = meta_strict(text)
            a = meta_addressee(text)
            strict_n += int(s)
            addressee_n += int(a)
            union_n += int(s or a)
            runs.append({"label": r["label"], "repeat": i + 1,
                         "first": first(text)[:160],
                         "strict": s, "addressee_branch": a,
                         "union": s or a})
    body = "\n\nПервый факт: конфликта в логе не было."
    prior = {
        "final6_E1": "Ну давай, разложу по полочкам, раз уж попросил.",
        "final6_E2": "Окей, давай без лишних прелюдий.",
        "final7_E1": "Ладно, смотри.",
        "final7_E2": "Макс, ну давай, раз уж попросил.",
        "final8_E2": "Ну ок, давай разложу по полочкам, раз уж попросили.",
    }
    gaps = {}

    def guard_of(name, text):
        raw = text + body
        out, stats = dcs.strip_l2_meta_lead(raw)
        gaps[name] = {"raw_sha12": sha12(raw), "final_sha12": sha12(out),
                      "raw_chars": len(raw), "final_chars": len(out),
                      "first": first(text)[:160],
                      "guard_stats": stats,
                      "removed": bool(stats.get("announce_removed")),
                      "body_intact": out == body.strip()}

    for name, text in prior.items():
        guard_of(name, text)
    for i, t in enumerate(next(r for r in d["runs"]
                               if r["label"] == "new_E")["l2"]):
        guard_of("live_run_E_%d" % (i + 1), t.get("final_text") or "")
    out = {
        "root": ROOT,
        "analysis": ANALYSIS,
        "counts": {"total": total, "strict": strict_n,
                   "addressee_branch": addressee_n, "union": union_n},
        "runs": runs,
        "live_gap_guard": gaps,
        "note": "offline; same tree/commit as the live run (module sha256 binding)",
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
