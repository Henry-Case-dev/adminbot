# -*- coding: utf-8 -*-
"""Independent re-check of ACCEPTANCE-96 evidence (main + follow-up).

Recomputes criteria numbers from the saved reply texts and verifies the
restore/global-doc equality independently of the harness aggregation.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

BASE = Path(r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH"
            r"\acceptance-96\evidence")
MAIN = BASE / "main"
spec = importlib.util.spec_from_file_location(
    "acc96", r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\acceptance-96"
             r"\accept96_live.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CONV = mod.CONVERSATIONAL
problems = 0


def check(label, cond, detail=""):
    global problems
    print(("OK   " if cond else "FAIL ") + label + (" | " + detail if detail
                                                   else ""))
    if not cond:
        problems += 1


main_summary = json.loads((MAIN / "summary.json").read_text(encoding="utf-8"))
print("=== MAIN RUN (27 turns) ===")
for mode in ("off", "occasional", "frequent"):
    w = json.loads((MAIN / ("wave-%s.json" % mode)).read_text(
        encoding="utf-8"))
    turns = w["turns"]
    ok = [t for t in turns if t["status"] == "ok" and t.get("answer")]
    conv = [t for t in ok if t["context"].split("_")[0] in CONV]
    with_mat = [(t["label"], mod.scan_own(t["answer"])["own_words"])
                for t in conv if mod.scan_own(t["answer"])["own_count"] > 0]
    rec = main_summary["criteria"][mode]
    print("%-11s recomputed=%d/%d harness=%d/%d verdict=%s"
          % (mode, len(with_mat), len(conv),
             rec["conversational_with_mat"], rec["conversational"],
             rec["verdict"]))
    for label, words in with_mat:
        print("    %-22s %s" % (label, words))
    check("%s counts match" % mode,
          len(with_mat) == rec["conversational_with_mat"]
          and len(conv) == rec["conversational"])
    # все ответы (для отчёта/ревью)
    for t in turns:
        print("  [%s] %-22s %s" % (t["status"], t["label"],
                                   (t.get("answer") or "")[:200]
                                   .replace("\n", " / ")))

print("\n=== FOLLOW-UP ===")
fup = json.loads((BASE / "summary.json").read_text(encoding="utf-8"))
iso = json.loads((BASE / "isolation.json").read_text(encoding="utf-8"))
b_turns = iso.get("turns_b") or []
b_own = sum(mod.scan_own(t.get("answer") or "")["own_count"] for t in b_turns)
check("isolation verdict", fup["isolation"]["verdict"] == "PASS",
      fup["isolation"]["verdict"])
check("A frequent / B off (effective)",
      fup["isolation"]["a_effective"]["value"] == "frequent"
      and fup["isolation"]["b_effective"]["value"] == "off")
check("A wire mode lines frequent",
      fup["isolation"]["a_wire_mode_lines"] == ["frequent", "frequent"])
check("B wire mode lines off",
      fup["isolation"]["b_wire_mode_lines"] == ["off", "off"])
check("B own mat recomputed == 0", b_own == 0, str(b_own))
quote = json.loads((BASE / "quote-off.json").read_text(encoding="utf-8"))
check("quote preserved", "нахуй" in (quote["turn"]["answer"] or ""),
      (quote["turn"]["answer"] or "")[:120])
diag = json.loads((BASE / "diag.json").read_text(encoding="utf-8"))
check("diag class model_ignored_instruction",
      diag["frequent"]["class"] == "model_ignored_instruction",
      str(diag["frequent"]))
check("model CAN produce mat on direct request (provider not limited)",
      fup["diag_direct"]["frequent"]["own_mat"] >= 1,
      fup["diag_direct"]["frequent"]["answer"][:120])
check("off + 'матерись' -> no mat",
      fup["diag_direct"]["off"]["own_mat"] == 0,
      fup["diag_direct"]["off"]["answer"][:60])

# restore: exact equality of override key sets + global doc
p0b = json.loads((BASE / "p0b-state.json").read_text(encoding="utf-8"))
rest = json.loads((BASE / "restore.json").read_text(encoding="utf-8"))


def keyset(rows):
    return sorted((int(r["chat_id"]), str(r["key"])) for r in (rows or []))


before, after = keyset(p0b.get("pg_overrides")), keyset(
    rest.get("pg_overrides_after"))
check("override key sets before == after", before == after,
      "n=%d" % len(before))
check("no character.expression override before/after",
      all(k != "character.expression" for _, k in before)
      and all(k != "character.expression" for _, k in after))
check("global expression doc unchanged",
      (p0b.get("pg_global_expression") or [{}])[0].get("value")
      == (rest.get("pg_global_expression_after") or [{}])[0].get("value"),
      ((rest.get("pg_global_expression_after") or [{}])[0].get("value")
       or "")[:120])
check("A/B expression override docs absent (after)",
      all((r or {}).get("doc") is None
          for r in (rest.get("pg_expr_override_after") or [])))

print("\nVERIFY", "PASS" if problems == 0 else "FAIL:%d" % problems)
sys.exit(0 if problems == 0 else 1)
