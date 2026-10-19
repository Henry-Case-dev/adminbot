# -*- coding: utf-8 -*-
"""Independent re-derivation of the F4 verdicts from the raw wave files.

Proves the saved `summary.json` matches the saved `wave-*.json` turn-by-turn
(guards against the earlier doubled-run artefact mix).
"""
from __future__ import annotations

import json
import pathlib
import sys

EVID = pathlib.Path(sys.argv[1])
CONV = {"banter", "argument", "everyday", "joke_short"}


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def main() -> int:
    summary = load("summary.json")
    waves = {m: load("wave-%s.json" % m) for m in
             ("off", "occasional", "frequent")}
    report = {"checks": {}, "rows": []}
    ok = True

    for mode, wave in waves.items():
        turns = wave["turns"]
        conv = [t for t in turns if t["context"] in CONV]
        with_mat = [t for t in conv if t["answer_scan"]["own_count"] > 0]
        s = summary["criteria"][mode]
        match = (len(conv) == s["conversational"]
                 and len(with_mat) == s["conversational_with_mat"]
                 and sorted({t["context"] for t in with_mat})
                 == s["contexts_with_mat"])
        report["checks"]["%s_counts" % mode] = match
        ok = ok and match
        # per-turn answers identical
        sum_pt = {t["label"]: t["answer"][:400] for t in s["per_turn"]}
        wave_pt = {t["label"]: t["answer"][:400] for t in turns}
        same = sum_pt == wave_pt
        report["checks"]["%s_per_turn_equal" % mode] = same
        ok = ok and same
        for t in turns:
            report["rows"].append({
                "mode": mode, "label": t["label"], "context": t["context"],
                "own": t["answer_scan"]["own_count"],
                "words": t["answer_scan"]["own_words"],
                "max_per_sentence": t["sentences"]["max_roots_in_sentence"],
                "raw_eq": t["raw_eq_delivered"],
                "answer": t["answer"][:220]})

    # raw equality recount from the raw turns
    all_turns = [t for w in waves.values() for t in w["turns"]]
    eq = sum(1 for t in all_turns if t["raw_eq_delivered"])
    report["checks"]["raw_eq_total"] = {
        "turns": len(all_turns), "equal": eq,
        "summary": summary["checks"]["raw_eq_delivered"]}
    ok = ok and (eq == summary["checks"]["raw_eq_delivered"]["equal"])

    # wire recount
    wire = sum(len(t.get("wire") or []) for t in all_turns)
    marker = sum(1 for t in all_turns for w in (t.get("wire") or [])
                 if w.get("has_marker"))
    report["checks"]["wire"] = {"calls": wire, "with_marker": marker,
                                "summary": summary["checks"]
                                ["wire_calls_total"]}
    ok = ok and (wire == summary["checks"]["wire_calls_total"])

    # per-mode verdicts recomputed
    freq = summary["criteria"]["frequent"]
    occ = summary["criteria"]["occasional"]
    off = summary["criteria"]["off"]
    f = [t for t in waves["frequent"]["turns"] if t["context"] in CONV]
    fm = [t for t in f if t["answer_scan"]["own_count"] > 0]
    freq_ok = (len(f) >= 6 and len(fm) >= 3
               and len({t["context"] for t in fm}) >= 3
               and max(t["sentences"]["max_roots_in_sentence"] for t in f) <= 1)
    o = [t for t in waves["occasional"]["turns"] if t["context"] in CONV]
    om = [t for t in o if t["answer_scan"]["own_count"] > 0]
    occ_ok = 1 <= len(om) <= 5
    of = [t for t in waves["off"]["turns"] if t["context"] in CONV]
    off_ok = len(of) == 2 and all(t["answer_scan"]["own_count"] == 0
                                  for t in of)
    report["recomputed"] = {"frequent": "PASS" if freq_ok else "FAIL",
                            "occasional": "PASS" if occ_ok else "FAIL",
                            "off": "PASS" if off_ok else "FAIL"}
    report["saved"] = {"frequent": freq["verdict"],
                       "occasional": occ["verdict"], "off": off["verdict"]}
    ok = ok and report["recomputed"] == report["saved"]
    report["summary_verdict"] = summary["verdict"]
    report["consistent"] = ok
    (EVID / "verify.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"consistent": ok, "recomputed": report["recomputed"],
                      "saved": report["saved"], "checks": report["checks"],
                      "raw_eq": report["checks"]["raw_eq_total"],
                      "wire": report["checks"]["wire"]},
                     ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
