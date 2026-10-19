# -*- coding: utf-8 -*-
"""Local self-test for the ACCEPTANCE-96 mat scanner / criteria helpers.

Imports accept96_live.py as a module (it has no side effects at import except
chdir; chdir is harmless locally). Verifies:
  * own/protected/euphemism classification;
  * quote-with-mat probe semantics;
  * sentence stats;
  * no false positives on plain Russian business text.
"""
from __future__ import annotations

import importlib.util
import sys

spec = importlib.util.spec_from_file_location(
    "acc96", r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\acceptance-96"
             r"\accept96_live.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CASES = [
    # (text, expected_own, expected_protected, note)
    ("Ну ты и выдал, бля, зато никто не уснул.", 1, 0, "own mat"),
    ("Передаю дословно: «да пошёл он нахуй со своими правками»", 0, 1,
     "quote preserved"),
    ("Передаю дословно: \"да пошёл он нахуй\"", 0, 1, "double-quote span"),
    ("Классика, пиздец как стабильно.", 1, 0, "own pizd"),
    ("Выдал, признаю. Зато никто не уснул.", 0, 0, "clean"),
    ("Он не работает у того, кто ставит его криво. У меня крутится, и "
     "стабильно.", 0, 0, "clean2"),
    ("Бляха-муха, ну и дела.", 0, 0, "euphemism"),
    ("Смотри https://example.com/ebanutiy-page — там всё.", 0, 0, "url span"),
    ("Код: `git commit -m \"заебал\"` — так не надо.", 0, 1, "code span"),
    ("Апельсин отправил, но квота на картинки кончилась.", 0, 0, "clean3"),
    ("это полный абзац, сука, я устал", 1, 0, "suka standalone"),
    ("пойду посмотрю сериал про сукачёва", 0, 0, "sukachev not mat"),
    ("Да что ты говоришь, нихуя себе", 1, 0, "nihuya"),
    ("Мат: обсценная разговорная лексика появляется изредка.", 0, 0,
     "instruction line not mat"),
]

fail = 0
for text, exp_own, exp_prot, note in CASES:
    res = mod.scan_own(text)
    ok = (res["own_count"] == exp_own and res["protected_count"] == exp_prot)
    if not ok:
        fail += 1
    print("%-4s %-28s own=%d/%d prot=%d/%d eup=%d | %s"
          % ("OK" if ok else "FAIL", note, res["own_count"], exp_own,
             res["protected_count"], exp_prot, len(res["euphemism"]),
             [r["word"] for r in res["own"]] +
             [r["word"] for r in res["protected"]]))

st = mod.sentence_stats("Ну ты и выдал, бля. Зато никто не уснул. И это "
                        "смешно, пиздец.")
print("sentence_stats:", st)
assert st["sentences"] == 3 and st["sentences_with_mat"] == 2, st

print("SELFTEST", "PASS" if fail == 0 else "FAIL:%d" % fail)
sys.exit(0 if fail == 0 else 1)
