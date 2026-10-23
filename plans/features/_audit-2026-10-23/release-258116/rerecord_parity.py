# -*- coding: utf-8 -*-
"""Re-record the SOUL-1 OFF-path baseline under the R3/R3B canons (2.58.114+).

Same offline stand as `tests/test_soul1_composer_parity_off.py` and
`soul1-fixtures/rerecord_assembly_asap2.py` (the script that produced the
previous ASAP 2 artifact). Only the provenance header changes: the canon
basis is now the active 2.58.115 line (R3 §3.7 `af7de4e9` + R3B `a8d047a7`,
FACTORY_SET 0163a686c401) instead of ASAP 2 (24ae494ac422).

No Telegram send, no external LLM call, no DB write. Local PG is absent, so
every hot_config.get() falls back to the code canon (same as the test).

Outputs
  tests/fixtures/soul1/direct-runtime-assembly-asap2.txt     (test baseline)
  plans/features/_audit-2026-10-23/release-258116/
    parity-after.txt                                          (same bytes)
    after/raw-sections.json                                   (per-section)
"""
import asyncio
import hashlib
import json
import os
import sys

ROOT = os.environ.get("PARITY_ROOT", r"C:\Code\Python\adminbot-wt258115")
BASE_MODE = os.environ.get("PARITY_BASE_MODE") == "1"
sys.path.insert(0, ROOT)

from services import chat_params                       # noqa: E402
from services import hot_config as hot                 # noqa: E402
from services import prompt_composer as pc             # noqa: E402
from services import response_extent as _extent        # noqa: E402

EV = os.path.join(ROOT, "plans", "features", "_audit-2026-10-23",
                  "release-258116")
OUT = os.path.join(ROOT, "tests", "fixtures", "soul1",
                   "direct-runtime-assembly-asap2.txt")
AFTER = os.path.join(EV, "parity-after.txt")
RAW = os.path.join(EV, "after", "raw-sections.json")


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

        async def _history_partial(self, chat_id, window):
            # ASAP2 T10-BOUNDARY: в стенде окно = вся сохранённая история
            # (старше ничего нет), поэтому пометка «ГРАНИЦА ИСТОРИИ» не
            # появляется — ровно условия, в которых снят эталонный дамп.
            return False

        def __init__(self, llm):
            self.llm = llm
            self.memory = StubMemory()
            self.db = None
            self.bot_id = 999
            self.aliases = None

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

    from services import prompt_registry as pr
    factory = pr.FACTORY_SET_SHA256_12
    if not BASE_MODE:
        assert factory == "0163a686c401", factory

    lines = ([
        "2.58.115 - DIRECT RUNTIME PROMPT ASSEMBLY (real code, offline)",
        "produced by plans/features/_audit-2026-10-23/release-258116/"
        "rerecord_parity.py",
        "no Telegram send, no external LLM call, no DB write",
        "local PG is DOWN -> every hot_config.get() falls back to the code canon",
        f"basis: active canons 2.58.114+ (R3 §3.7 af7de4e9 + R3B a8d047a7),",
        f"FACTORY_SET_SHA256_12={factory} (2.58.115 release line).",
        "supersedes: ASAP 2 artifact 24ae494ac422, kept byte-exact as",
        "plans/features/_audit-2026-10-23/release-258116/parity-before.txt.",
        "",
        "=" * 78,
    ] if not BASE_MODE else [
        "BASE-MODE regeneration of the OLD artifact (stand only, no canon claim)",
        "produced by release-258116/rerecord_parity.py with PARITY_BASE_MODE=1",
        "=" * 78,
    ])

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
              "note: один раз; R3B добавляет только инструкцию о границе истории.",
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

    # P3 (modes OFF) — legacy base canon, NOT touched by R3/R3B
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
              "note: R3 §3.7 — семантические критерии чата/адресата; правило 5 —",
              "note: структурная отсылка; R3B — одно усиление продолжения §4.1.",
              _metrics(system, cap["messages"][1]["content"]),
              "-" * 78,
              "[SYSTEM]", system, "",
              "[USER]", cap["messages"][1]["content"], ""]

    body = "\n".join(lines) + "\n"
    for path in (() if BASE_MODE else (OUT, AFTER)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
    raw_path = (os.environ.get("PARITY_BASE_OUT")
                or os.path.join(EV, "parity-base-regen.txt"))
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)
    if BASE_MODE:
        with open(raw_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
    else:
        with open(RAW, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(sections, fh, ensure_ascii=False, indent=2,
                      sort_keys=True)
            fh.write("\n")
    for name in ("P1", "P2", "P3", "P5a", "P5b", "P4"):
        sys_t = sections[name]["system"]
        usr_t = sections[name]["user"]
        print(f"{name} system len={len(sys_t)} sha={sha12(sys_t)} "
              f"user_len={len(usr_t) if usr_t is not None else '-'}")
    if BASE_MODE:
        print("written", raw_path)
    else:
        print("written", OUT)
        print("written", AFTER)
        print("written", RAW)


asyncio.run(main())
