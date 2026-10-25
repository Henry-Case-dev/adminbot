#!/usr/bin/env python3
"""P0 LIVE-META-CLASS: guard recheck for `e2d9b335` (offline, read-only).

Applies candidate `strip_l2_meta_lead` to the EXACT live first sentences from
final6 (E1/E2), final7 (E1/E2) and final8 (E2 `Ну ок, давай разложу ...`),
plus the general class (addressee/particles x 1st-person meta-verb), and to
negative forms where the same words carry content. Full body is appended so
the "exactly one sentence, body byte-intact" contract is checked.
No DB, no network, no writes to prod; prints JSON to stdout.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

BODY = "\n\nПервый факт: конфликта в логе не было, проверено по журналу."

CASES = [
    # (name, first sentence, must_remove)
    ("live_final6_E1", "Ну давай, разложу по полочкам, раз уж попросил.", True),
    ("live_final6_E2", "Окей, давай без лишних прелюдий.", True),
    ("live_final7_E1", "Ладно, смотри.", True),
    ("live_final7_E2", "Макс, ну давай, раз уж попросил.", True),
    ("live_final8_E2", "Ну ок, давай разложу по полочкам, раз уж попросили.", True),
    ("class_vocative", "Оля, разложу по полочкам.", True),
    ("class_tak_posmotryu", "Так, посмотрю по порядку.", True),
    ("class_seichas_proveryu", "Сейчас проверю по журналу.", True),
    ("positive_smotri_ka", "Ладно, смотри-ка.", True),
    ("negative_maks_content", "Макс, ты не злобный.", False),
    ("negative_subbota", "Ну давай в субботу.", False),
    ("negative_ladno_colon", "Ладно, смотри: конфликта в логе не было.", False),
    ("negative_razberu_colon", "Разберу твой вопрос: конфликта в логе не было.", False),
    ("negative_fakty_colon", "Давай разложу факты: конфликта в логе не было.", False),
    ("negative_fakty_comma", "Ну давай по фактам: конфликта в логе не было.", False),
    ("negative_maks_fakty", "Макс, ну давай, раз уж попросил, по фактам.", False),
    ("negative_filler", "Ок, ты не молодец.", False),
]


def sha12(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def first_sentence(text):
    head = str(text or "").split("\n", 1)[0]
    m = re.search(r"[.!?\u2026]+(?=\s|$)", head)
    return head[:m.end()] if m else head


def main():
    root = sys.argv[1]
    sys.path.insert(0, root)
    from services import direct_chat_service as dcs

    out = {"root": root, "guard": "strip_l2_meta_lead", "cases": []}
    ok = True
    for name, first, must_remove in CASES:
        raw = first + BODY
        got, stats = dcs.strip_l2_meta_lead(raw)
        removed = bool(stats.get("announce_removed"))
        body = BODY.lstrip()
        rec = {
            "name": name,
            "raw_sha12": sha12(raw),
            "final_sha12": sha12(got),
            "raw_chars": len(raw),
            "final_chars": len(got),
            "raw_first": first_sentence(raw)[:160],
            "final_first": first_sentence(got)[:160],
            "stats": stats,
            "removed": removed,
            "expected_removed": must_remove,
            "pass": removed is must_remove,
        }
        if must_remove:
            rec["body_intact"] = got == body
            rec["pass"] = rec["pass"] and rec["body_intact"]
        ok = ok and rec["pass"]
        out["cases"].append(rec)
    out["pass"] = ok
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
