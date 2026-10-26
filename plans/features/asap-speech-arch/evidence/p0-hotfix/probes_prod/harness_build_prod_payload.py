"""R2 production-context payload builder (old/new variant, A/B case).

Uses the variant's OWN code path (`prompt_composer.compose_prompt` with the
real prod gates/base prompt), real PG texts (Core/Expression/verbalizer
template) and the real SQLite window around the traced messages.

Not re-created (documented honestly): RAG retrieval, stats tool, identity
(persona) block, L1 LLM call (route taken from the traces).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

SCRATCH = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\r2"


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def load(p):
    return json.load(open(os.path.join(SCRATCH, p), encoding="utf-8"))


def build_window_text(rows, limit=50):
    tail = rows[-limit:]
    lines = []
    for m in tail:
        txt = (m.get("text") or "").strip()
        if not txt:
            continue
        lines.append("%s: %s" % (m.get("author_name") or "?", txt))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--variant", required=True, choices=("old", "new"))
    ap.add_argument("--case", required=True, choices=("A", "B"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.environ.setdefault("UNIFIED_COMPOSER_ENABLED", "1")
    os.environ.setdefault("SMART_VERBALIZER_MODES_ENABLED", "1")
    sys.path.insert(0, args.root)
    os.chdir(args.root)

    from services import prompt_composer as pc
    from services import prompt_style_blocks as psb
    from services import response_extent as _extent
    from services import mca_expression as expr_mod

    pg = load("pg_dump.json")
    ctx = load("ctx_out.json")

    core_doc = pg["character.core"]
    core_raw = core_doc.get("full_text") or ""
    expression_doc = pg["character.expression"]
    base_prompt = pg["prompts.direct_chat_verbalizer_system_prompt"]

    targets = {int(t["tg_message_id"]): t for t in ctx["targets"]}
    trig = targets[1175252 if args.case == "A" else 1175255]
    win = [m for m in ctx["windows"][trig["chat_id"]]
           if int(m["timestamp"]) < int(trig["timestamp"])
           and str(m["tg_message_id"]) != str(trig["tg_message_id"])]

    if args.case == "A":
        response_mode = "serious"
        plan = _extent.ResponsePlan(task_kind="research", extent="normal",
                                    structure="answer", delivery_hint="plain")
    else:
        response_mode = "deep_research"
        plan = _extent.ResponsePlan(task_kind="research", extent="detailed",
                                    structure="report", delivery_hint="plain")

    extent_block = _extent.render_extent_block(plan)
    expression_text = expr_mod.render_expression_text(expression_doc)
    expression_mode = str(expression_doc.get("profanity") or "")

    gates = pc.GateState(
        unified_composer_enabled=True,
        character_core_enabled=True,
        speech_style_policy_enabled=True,
        humor_library_enabled=False,
        humor_feedback_enabled=False,
        humor_craft_enabled=True,
        expression_examples_enabled=True,
        persona_enabled=True,
        character_layers_enabled=True,
        smart_verbalizer_modes_enabled=True,
        response_plan_enabled=True,
    )

    prompt_plan = pc.PromptPlan(
        profile=pc.PROFILE_SPEECH_PLAIN if hasattr(pc, "PROFILE_SPEECH_PLAIN") else pc.PROFILE_SPEECH,
        writer="l2_writer",
        chat_id=int(trig["chat_id"]),
        channel="plain",
        html_safe=True,
        base_prompt=base_prompt,
        base_source="pg",
        include_mode_block=True,
        response_mode=response_mode,
        core=pc.CoreRef(text=core_raw, revision=str(core_doc.get("revision") or ""),
                        source="global", detail_level=str(core_doc.get("detail_level") or "full"),
                        origin=str(core_doc.get("origin") or "owner_edit")),
        response_plan=pc.PlanRef(text=extent_block, source="l1",
                                 extent=plan.extent, structure=plan.structure,
                                 tone="inherit"),
        expression=pc.ExpressionSettings(text=expression_text,
                                         mode=expression_mode,
                                         source="global",
                                         revision=str(expression_doc.get("revision") or "")),
        gates=gates,
    )
    manifest = pc.compose_prompt(prompt_plan)
    system = manifest.system

    parts = []
    if args.variant == "new":
        from services.direct_l1 import L1Plan, build_l2_plan_block
        l1 = L1Plan(action="reply", response_act="research",
                    extent=("normal" if args.case == "A" else "detailed"),
                    tone="inherit",
                    structure=("answer" if args.case == "A" else "report"),
                    delivery_hint="plain", confidence=0.85,
                    confidence_bucket="high", source="recorded_trace_route")
        parts.append(build_l2_plan_block(l1, include_analysis=True))
    parts.append("<Target_User>%s</Target_User>" % trig["author_name"])
    parts.append("<Global_Context>\n" + build_window_text(win) + "\n</Global_Context>")
    parts.append("<Current_Question>\n%s\n</Current_Question>"
                 % (trig.get("text") or ""))
    user = "\n\n".join(p for p in parts if p)

    out = {
        "variant": args.variant,
        "case": args.case,
        "root": args.root,
        "route": {"response_mode": response_mode,
                  "task_kind": plan.task_kind, "extent": plan.extent,
                  "structure": plan.structure,
                  "l1_plan_block": args.variant == "new"},
        "sources": {
            "core_raw_chars": len(core_raw),
            "core_sha12": sha12(core_raw),
            "core_revision": core_doc.get("revision"),
            "base_prompt_chars": len(base_prompt),
            "base_prompt_sha12": sha12(base_prompt),
            "expression_chars": len(expression_text),
            "expression_sha12": sha12(expression_text),
            "extent_block_chars": len(extent_block),
            "extent_block_sha12": sha12(extent_block),
            "window_messages_used": len([1 for m in win if (m.get("text") or "").strip()]),
            "window_from": win[0]["timestamp"] if win else None,
            "window_to": win[-1]["timestamp"] if win else None,
        },
        "layers": [{"layer": t.layer, "block_id": t.block_id, "chars": t.chars,
                    "rendered": bool(t.rendered), "skip_reason": t.skip_reason}
                   for t in manifest.layers],
        "system_chars": len(system),
        "system_sha12": sha12(system),
        "user_chars": len(user),
        "user_sha12": sha12(user),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"variant": args.variant, "case": args.case,
                      "system_chars": out["system_chars"],
                      "system_sha12": out["system_sha12"],
                      "user_chars": out["user_chars"],
                      "route": out["route"],
                      "sources": out["sources"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
