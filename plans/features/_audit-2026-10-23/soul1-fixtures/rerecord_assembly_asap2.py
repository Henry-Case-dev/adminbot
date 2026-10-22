# -*- coding: utf-8 -*-
"""Re-record the SOUL-1 OFF-path baseline under the ASAP 2 canons.

Same offline stand as `tests/test_soul1_composer_parity_off.py` and
`OPENCODE_WORKFLOW_SCRATCH/asap-w1/rerecord_assembly.py` (the script that
produced the W1 artifact). Only the provenance header changes: the canon
basis is now ASAP 2 §4.1/§4.2 (L1 planner + L2 verbalizer), implemented in
commit 5ad73933.

No Telegram send, no external LLM call, no DB write. Local PG is absent, so
every hot_config.get() falls back to the code canon (same as the test).

Outputs
  tests/fixtures/soul1/direct-runtime-assembly-asap2.txt   (test baseline)
  plans/features/_audit-2026-10-23/soul1-fixtures/after/raw-sections.json
"""
import asyncio
import hashlib
import json
import os
import sys

ROOT = r"C:\Code\Python\adminbot"
sys.path.insert(0, ROOT)

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc
from services import response_extent as _extent

OUT = os.path.join(ROOT, "tests", "fixtures", "soul1",
                   "direct-runtime-assembly-asap2.txt")
RAW = os.path.join(ROOT, "plans", "features", "_audit-2026-10-23",
                   "soul1-fixtures", "after", "raw-sections.json")


def sha12(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


class StubLLM:
    def __init__(self):
        self.captured = []
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.captured.append({"messages": [dict(m) for m in messages],
                              "step": kwargs.get("step")})
        step = kwargs.get("step")
        if step == "l1_planner":
            return json.dumps({
                "action": "reply", "response_act": "explanation",
                "tone": "inherit", "extent": "detailed",
                "structure": "answer", "delivery_hint": "plain",
                "tool_policy": "none", "confidence": 0.8,
                "capabilities_needed": [],
            }, ensure_ascii=False)
        if step == "stage1":
            return json.dumps({
                "user_question": "почему упал сервис",
                "answer_outline": "сначала причина, затем следствия",
                "facts": [{"topic": "лог", "finding": "в логе HTTP 502",
                           "source": "tool", "confidence": "medium"}],
                "limitations": [],
                "response_mode": "serious",
            }, ensure_ascii=False)
        return "ЗАГЛУШКА ОТВЕТА"

    def _pg(self):
        return None


class StubMemory:
    async def get_window_messages(self, chat_id):
        return [{"speaker": "Аня", "text": "ну и что там с сервером",
                 "created_at": "2026-10-16T10:00:00+00:00"}]


class StubMessage:
    text = "бот: распиши подробно, почему упал сервис"
    caption = None
    message_id = 4242
    chat = type("C", (), {"type": "supergroup"})()
    reply_to_message = None
    from_user = None


def build_service():
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _render_current_question = D._render_current_question
        _l1_reply_block = staticmethod(D._l1_reply_block)
        _l1_speech_hints = D._l1_speech_hints
        _build_speech_understanding = D._build_speech_understanding
        _attach_l1_plan_meta = D._attach_l1_plan_meta
        _compose_speech_system = D._compose_speech_system

        def __init__(self, llm):
            self.llm = llm
            self.memory = StubMemory()
            self.db = None
            self.bot_id = 999

    return Stub, D


CHARACTER_BLOCK = ("<Persona>\nИмя: Бот. Характер: язвительный, прямой.\n"
                   "</Persona>\n\n<Character_Rules>\nНе раскрывать, что ты "
                   "ИИ.\n</Character_Rules>")
STYLE_DIRECTIVES = ("<Style_Requests>\nПиши без канцелярита.\n"
                    "</Style_Requests>")
LESSONS = "<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>"
SPEECH = "<Speech_Understanding>\nact=assert\n</Speech_Understanding>"
TIME_LINE = "Время: 16.10.2026 10:05"
CONTEXT_BLOCK = "<Context>окно чата</Context>"

PLAN_DETAILED = _extent.ResponsePlan(
    task_kind="explanation", extent="detailed", structure="answer",
    delivery_hint="plain", tool_policy="none", source="l1")
PLAN_MICRO = _extent.ResponsePlan(
    task_kind="social_chat", extent="micro", structure="chat",
    delivery_hint="plain", tool_policy="none", source="l1")


def _metrics(system, user=None):
    rows = [f"SYSTEM  chars={len(system)} "
            f"tokens={(len(system) + 3) // 4} sha256_12={sha12(system)}"]
    if user is not None:
        rows.append(f"USER    chars={len(user)} "
                    f"tokens={(len(user) + 3) // 4} sha256_12={sha12(user)}")
    return "\n".join(rows)


def _reset():
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


async def main():
    os.environ.pop("UNIFIED_COMPOSER_ENABLED", None)
    sections = {}

    lines = [
        "ASAP 2 - DIRECT RUNTIME PROMPT ASSEMBLY (real code, offline)",
        "produced by plans/features/_audit-2026-10-23/soul1-fixtures/"
        "rerecord_assembly_asap2.py",
        "no Telegram send, no external LLM call, no DB write",
        "local PG is DOWN -> every hot_config.get() falls back to the code canon",
        "basis: ASAP 2 factory texts (source-2026-10-22.md §4.1 L1 planner,",
        "§4.2 L2 verbalizer), code commit 5ad73933 (prod 2.58.111 canons +",
        "Direct Chat clarification corrective).",
        "supersedes: plans/features/asap-speech-arch/evidence/w1/"
        "direct-runtime-assembly-w1.txt (W1 canons; kept as history).",
        "",
        "=" * 78,
    ]

    # P1
    _reset()
    Stub, D = build_service()
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "почему упал сервис", temperature=0.7,
        character_block=CHARACTER_BLOCK, style_directives=STYLE_DIRECTIVES,
        response_plan=PLAN_DETAILED, plan_block="<Plan>extent=detailed</Plan>",
        user_blocks=[CONTEXT_BLOCK], time_line=TIME_LINE,
        evidence="[tool: execute_web_search out_chars=812]",
        lessons_block=LESSONS, speech_block=SPEECH, max_tokens=4096)
    cap = llm.captured[-1]["messages"]
    sections["P1"] = {"system": cap[0]["content"], "user": cap[1]["content"]}
    lines += ["## P1  Direct L2 WRITER (primary Direct answer path)",
              "note: ASAP2 §4.2 — абзацы уточнений в каноне §3.1 (КАК ПИСАТЬ),",
              "note: один раз; личность/стиль остаются отдельными слоями.",
              _metrics(cap[0]["content"], cap[1]["content"]),
              "-" * 78,
              "[SYSTEM]", cap[0]["content"], "", "[USER]", cap[1]["content"],
              ""]

    # P2
    _reset()
    Stub, D = build_service()
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "да или нет?", temperature=0.7,
        character_block=CHARACTER_BLOCK, style_directives="",
        response_plan=PLAN_MICRO, plan_block="<Plan>extent=micro</Plan>",
        user_blocks=["<Context>окно</Context>"])
    cap = llm.captured[-1]["messages"]
    sections["P2"] = {"system": cap[0]["content"], "user": cap[1]["content"]}
    lines += ["## P2  Direct L2 WRITER (extent=micro)",
              _metrics(cap[0]["content"], cap[1]["content"]),
              "-" * 78,
              "[SYSTEM]", cap[0]["content"], "", "[USER]", cap[1]["content"],
              ""]

    # P3 (modes OFF) — legacy base canon, NOT touched by ASAP 2
    from config.settings import settings
    prev_flag = getattr(type(settings), "SMART_VERBALIZER_MODES_ENABLED", True)
    try:
        type(settings).SMART_VERBALIZER_MODES_ENABLED = False
        _reset()
        Stub, D = build_service()
        llm = StubLLM()
        await D._l2_write_answer(
            Stub(llm), 12345, "почему упал сервис", temperature=0.7,
            character_block=CHARACTER_BLOCK, response_plan=PLAN_DETAILED,
            plan_block="<Plan>x</Plan>")
        cap = llm.captured[-1]["messages"]
        sections["P3"] = {"system": cap[0]["content"], "user": None}
        lines += ["## P3  Direct L2 WRITER (SMART_VERBALIZER_MODES_ENABLED=0)",
                  _metrics(cap[0]["content"]),
                  "-" * 78,
                  "[SYSTEM]", cap[0]["content"], ""]
    finally:
        type(settings).SMART_VERBALIZER_MODES_ENABLED = prev_flag

    # P5 (system2)
    _reset()
    Stub, D = build_service()
    llm = StubLLM()
    raw = type("R", (), {"tool_context": "tool output", "tool_trace": [
        {"tool": "execute_web_search", "out_chars": 812}]})()
    await D._synthesize_direct_answer(
        Stub(llm), 12345, "почему упал сервис", raw, 0.7,
        character_block=CHARACTER_BLOCK, style_directives=STYLE_DIRECTIVES,
        plan=PLAN_DETAILED)
    steps = {c["step"]: c["messages"] for c in llm.captured}
    sections["P5a"] = {"system": steps["stage1"][0]["content"],
                       "user": steps["stage1"][1]["content"]}
    sections["P5b"] = {"system": steps["stage2"][0]["content"],
                       "user": steps["stage2"][1]["content"]}
    lines += ["## P5a  System2 Stage-1 (synthesizer, machine_json)",
              _metrics(steps["stage1"][0]["content"], steps["stage1"][1]["content"]),
              "-" * 78,
              "[SYSTEM]", steps["stage1"][0]["content"], "",
              "[USER]", steps["stage1"][1]["content"], ""]
    lines += ["## P5b  System2 Stage-2 (verbalizer over JSON report)",
              _metrics(steps["stage2"][0]["content"], steps["stage2"][1]["content"]),
              "-" * 78,
              "[SYSTEM]", steps["stage2"][0]["content"], "",
              "[USER]", steps["stage2"][1]["content"], ""]

    # P4 (L1 planner)
    from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT
    from services import prompt_style_blocks as psb
    _reset()
    Stub, D = build_service()
    llm = StubLLM()
    await D._plan_direct_l1(
        Stub(llm), 12345, StubMessage(), "почему упал сервис", None,
        bundle=None, target_name="Аня", user_id=None,
        character_block=CHARACTER_BLOCK, lore_enabled=False,
        image_enabled=False, force_required=False, reply_bot=False)
    cap = [c for c in llm.captured if c["step"] == "l1_planner"][0]
    system = cap["messages"][0]["content"]
    assert system == psb.resolve_prompt(
        "prompts.direct_l1_planner_system_prompt",
        DIRECT_L1_PLANNER_SYSTEM_PROMPT)
    sections["P4"] = {"system": system,
                      "user": cap["messages"][1]["content"]}
    lines += ["## P4  L1 PLANNER (machine_json)",
              "note: ASAP2 §4.1 — секция «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА»;",
              "note: правило 5 — структурная отсылка; §3.7 не тронута.",
              _metrics(system, cap["messages"][1]["content"]),
              "-" * 78,
              "[SYSTEM]", system, "",
              "[USER]", cap["messages"][1]["content"], ""]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(RAW, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sections, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    for name in ("P1", "P2", "P3", "P5a", "P5b", "P4"):
        sys_t = sections[name]["system"]
        usr_t = sections[name]["user"]
        print(f"{name} system len={len(sys_t)} sha={sha12(sys_t)} "
              f"user_len={len(usr_t) if usr_t is not None else '-'}")
    print("written", OUT)
    print("written", RAW)


asyncio.run(main())
