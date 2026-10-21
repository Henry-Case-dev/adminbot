# -*- coding: utf-8 -*-
"""Одноразовая подготовка resume: бэкап прогона-1 (авария провайдера) +
восстановление results-partial.jsonl из валидных записей.

Запуск: py -3 ab_prep_resume.py  (cwd любой; EVID — рядом)
TEST-LIFECYCLE: PROVISIONAL owner=SOUL-14.0
"""
from __future__ import annotations

import json
import pathlib
import shutil

EVID = pathlib.Path(__file__).resolve().parent.parent

results_path = EVID / "results.json"
results = json.loads(results_path.read_text(encoding="utf-8"))

backup = EVID / "results-run1-outage.json"
if not backup.exists():
    shutil.copyfile(results_path, backup)
    print("backup ->", backup.name)

runs = results["runs"]
good = [r for r in runs if r.get("reply")]
empty = [(r["scene_id"], r["arm"]) for r in runs if not r.get("reply")]
print("runs=%d good=%d empty=%d" % (len(runs), len(good), len(empty)))

part = EVID / "results-partial.jsonl"
meta = {
    "_meta": {
        "head_fingerprints": results["head_fingerprints"],
        "model": results["model"],
        "note": ("rebuilt from results-run1-outage.json after provider "
                 "outage; only non-empty generations reused"),
        "source": backup.name,
    }
}
lines = [json.dumps(meta, ensure_ascii=False)]
for r in good:
    lines.append(json.dumps(r, ensure_ascii=False))
part.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print("partial ->", part.name, "records:", len(good))
print("missing arms:", " ".join("%s:%s" % (s, a) for s, a in empty))
