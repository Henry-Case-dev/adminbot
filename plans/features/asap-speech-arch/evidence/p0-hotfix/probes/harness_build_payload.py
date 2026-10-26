"""P0 probe: build the REAL old/new system payloads from repository code.

Read-only: imports the variant's modules, uses the variant's own constants and
the real `simplify_core_for_prompt`. No production call, no chat access.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def load_core(core_md: str) -> str:
    text = io.open(core_md, encoding="utf-8").read()
    m = re.search(r"## 3\..*?```text\r?\n(.*?)\r?\n```", text, re.S)
    if not m:
        raise SystemExit("core block not found in " + core_md)
    return m.group(1)


SYNTHETIC_L2 = """\
<Global_Context>
конспект чата: участники обсуждали отпуск, ремонт на кухне и сериал;
в спорах о политике Ринтаро повышал голос и один раз назвал собеседника
«диванным экспертом». Ниже - 4 последних сообщения.
[msg:901] Влад: кто заберёт посылку с почты?
[msg:902] Ринтаро: я не могу, у меня смена до восьми.
[msg:903] Влад: ок, тогда я.
[msg:904] Ринтаро: спасибо.
</Global_Context>"""

SYNTHETIC_L2_WITH_MARKER = """\
<Global_Context>
источник: конспект чата - пересказ, а не подтверждённые факты.
конспект чата: участники обсуждали отпуск, ремонт на кухне и сериал;
в спорах о политике Ринтаро повышал голос и один раз назвал собеседника
«диванным экспертом». Ниже - 4 последних сообщения (дословно).
[msg:901] Влад: кто заберёт посылку с почты?
[msg:902] Ринтаро: я не могу, у меня смена до восьми.
[msg:903] Влад: ок, тогда я.
[msg:904] Ринтаро: спасибо.
</Global_Context>"""

CASES = {
    "c1": {
        "route": "serious",
        "user": "Бот, проанализируй мои сообщения в чате и скажи, я злобный?",
        "note": "prod A, run 83ad82c8a08d4e62b5a1105d13b97b62",
    },
    "c2": {
        "route": "deep",
        "user": "Проанализируй сообщения Ринтаро и скажи, он злобный или нет?",
        "note": "prod B, run 8f93324b6e1b4d7fa7d0b7ebc64ef1e8",
    },
    "c3": {
        "route": "serious",
        "user": "Слушай, а сколько по времени варить куриное яйцо всмятку?",
        "note": "short household question",
    },
    "c4": {
        "route": "casual",
        "user": "Как думаешь, стоит ли мне сегодня идти на работу или забить?",
        "note": "invites one rude remark",
    },
    "c5": {
        "route": "deep",
        "user": ("Разбери подробно, чем отличаются HTTP/2 и HTTP/3, какие "
                 "проблемы решает QUIC и что это меняет для обычного сайта."),
        "note": "requires detailed factual analysis",
    },
    "c6": {
        "route": "deep",
        "user": "Напомни, что было на той встрече в феврале, где мы ругались?",
        "note": "event from chat history without confirmed data",
    },
}


def build(root: str, variant: str, core_md: str) -> dict:
    sys.path.insert(0, root)
    os.chdir(root)
    from services import mca_expression as expr
    from services import prompt_style_blocks as psb
    from services.prompt_composer import simplify_core_for_prompt

    core_raw = load_core(core_md)
    core = simplify_core_for_prompt(core_raw)
    expression = expr.render_expression_text(
        {"enabled": True, "controls": {"profanity": {"value": "frequent"}}})
    final_contract = expr.render_expression_final_contract("frequent")

    plan_block = ""
    plan_cls = None
    if variant == "new":
        from services.direct_l1 import L1Plan, build_l2_plan_block
        plan_cls = L1Plan
        plan = L1Plan(action="reply", response_act="research",
                      extent="normal", tone="inherit", structure="answer",
                      delivery_hint="plain", confidence=0.8,
                      confidence_bucket="high", source="llm")
        plan_block = build_l2_plan_block(plan, include_analysis=True)

    payloads = {}
    for cid, case in CASES.items():
        if case["route"] == "deep":
            mode_block = psb.MODE_DEEP_RESEARCH_BLOCK
        elif case["route"] == "serious":
            mode_block = psb.MODE_SERIOUS_BLOCK
        else:
            mode_block = psb.MODE_CASUAL_BLOCK
        if case["route"] == "serious" and variant == "new":
            mode_block = psb.MODE_SERIOUS_BLOCK + "\n" + plan_block
        l2 = SYNTHETIC_L2 if variant == "old" else SYNTHETIC_L2_WITH_MARKER
        system = "\n\n".join(p for p in (core, expression, mode_block, l2,
                                         final_contract) if p)
        payloads[cid] = {
            "case": cid, "route": case["route"], "user": case["user"],
            "note": case["note"],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": case["user"]}],
            "system_chars": len(system),
            "system_sha12": sha12(system),
            "core_raw_chars": len(core_raw),
            "core_used_chars": len(core),
            "core_sha12": sha12(core),
            "expression_chars": len(expression),
            "mode_block_chars": len(mode_block),
            "plan_block_chars": len(plan_block),
        }
    meta = {
        "variant": variant,
        "root": root,
        "core_raw_chars": len(core_raw),
        "core_raw_sha12": sha12(core_raw),
        "core_used_chars": len(core),
        "core_used_sha12": sha12(core),
        "expression_sha12": sha12(expression),
        "final_contract_sha12": sha12(final_contract),
        "deep_block_sha12": sha12(psb.MODE_DEEP_RESEARCH_BLOCK),
    }
    return {"meta": meta, "payloads": payloads}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--variant", required=True, choices=("old", "new"))
    ap.add_argument("--core-md", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = build(args.root, args.variant, args.core_md)
    io.open(args.out, "w", encoding="utf-8").write(
        json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps(data["meta"], ensure_ascii=False))
    for cid, p in data["payloads"].items():
        print(cid, p["route"], p["system_chars"], p["system_sha12"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
