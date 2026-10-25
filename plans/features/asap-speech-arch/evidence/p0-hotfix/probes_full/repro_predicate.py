# -*- coding: utf-8 -*-
"""Local (no network/LLM) reproduction of the two probe-validity facts:

1. The analysis directive is gated by `analysis_directive_needed`: for the REAL
   L1 plans recorded in `raw_full_*.json` it is False (casual/compact route),
   while for a research/detailed/report plan it is True and the exact texts
   appear exactly once. Forcing `include_analysis=True` adds them for any plan.
2. The raw counters `analysis_directive`/`analysis_writer` count the ASCII
   literal "ANALYSIS_DIRECTIVE", which never occurs in the Russian texts, so a
   reported 0 is not evidence of absence.

Usage (from the repository root, with the fixed tree available):
    set P0_WT=<worktree at 9650e099>          # default: C:\\Code\\Python\\adminbot-wt-speech-p0
    python probes_full/repro_predicate.py
Reads raw_full_*.json next to this file. No DB, no network, no writes.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
WT = pathlib.Path(os.environ.get("P0_WT", r"C:\Code\Python\adminbot-wt-speech-p0"))
sys.path.insert(0, str(WT))
os.chdir(WT)

from services import direct_l1 as l1                      # noqa: E402
from services import prompt_style_blocks as psb           # noqa: E402


def plan_from(raw_plan: dict) -> "l1.L1Plan":
    p = raw_plan or {}
    return l1.L1Plan(
        action=p.get("action"), response_act=p.get("response_act"),
        extent=p.get("extent"), structure=p.get("structure"),
        tone=p.get("tone"), delivery_hint=p.get("delivery_hint"),
        confidence=p.get("confidence"), source=p.get("source"),
        needs_clarification=bool(p.get("needs_clarification")))


def block_stats(block: str) -> dict:
    return {
        "chars": len(block),
        "sha12": hashlib.sha256(block.encode("utf-8")).hexdigest()[:12],
        "exact_directive": block.count(psb.ANALYSIS_DIRECTIVE_TEXT),
        "exact_writer": block.count(psb.ANALYSIS_WRITER_TEXT),
        "ascii_marker_directive": block.count("ANALYSIS_DIRECTIVE"),
        "ascii_marker_writer": block.count("ANALYSIS_WRITER"),
    }


out = {"tree": str(WT), "texts": {
    "directive_chars": len(psb.ANALYSIS_DIRECTIVE_TEXT),
    "writer_chars": len(psb.ANALYSIS_WRITER_TEXT),
    "ascii_marker_in_text": "ANALYSIS_DIRECTIVE" in psb.ANALYSIS_DIRECTIVE_TEXT,
}, "recorded_plans": {}, "control_plans": {}}

for path in sorted(glob.glob(str(HERE / "raw_full_*.json"))):
    if path.endswith("selfecho.json"):
        continue
    d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    plan = plan_from(d.get("l1_plan") or {})
    pred = l1.analysis_directive_needed(plan, modes_on=True)
    out["recorded_plans"][pathlib.Path(path).name] = {
        "l1_plan": d.get("l1_plan"),
        "response_mode": l1.plan_response_mode(plan),
        "predicate": pred,
        "block_by_predicate": block_stats(
            l1.build_l2_plan_block(plan, include_analysis=pred)),
        "block_forced": block_stats(
            l1.build_l2_plan_block(plan, include_analysis=True)),
        "probe_reported_plan_block": d.get("plan_block"),
    }

def mk(**kw):
    base = dict(action="reply", response_act="research", extent="detailed",
                structure="report", tone="neutral", delivery_hint="plain",
                confidence=0.9, source="llm", needs_clarification=False)
    base.update(kw)
    return l1.L1Plan(**base)

for name, p in {
    "research__detailed__report": mk(),
    "banter__compact": mk(response_act="banter", extent="compact",
                          structure="chat", tone="playful"),
    "answer__normal": mk(response_act="answer", extent="normal",
                         structure="answer"),
}.items():
    pred = l1.analysis_directive_needed(p, modes_on=True)
    out["control_plans"][name] = {
        "predicate": pred,
        "block_by_predicate": block_stats(
            l1.build_l2_plan_block(p, include_analysis=pred)),
    }

print(json.dumps(out, ensure_ascii=False, indent=1))
