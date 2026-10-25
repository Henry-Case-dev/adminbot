"""SOUL-1 (W2) — машинные стадии не получают личность и юмор.

SOUL-04.6 / SOUL-BOUND.4: аналитические и машинные стадии (JSON L1,
factcheck verification, summary extraction, Experience JSON) остаются
нейтральными и точными; творческий Core к ним не применяется. Профиль
`machine_json` = только канал-контракт, байт-в-байт прежний канон.

Проверяется на РЕАЛЬНЫХ путях Direct (L1 planner, System2 Stage-1) при
включённом композере, плюс редакционная eligibility (`editorial_report`,
`internal_silent`) и отсутствие лишних LLM-вызовов.

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W2 (SOUL-04.6, SOUL-BOUND.4/05)
"""
from __future__ import annotations

import json

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_gates
from services import prompt_composer as pc
from services.summary_aliases import AliasResolver

CORE = "ЯДРО_ХАРАКТЕРА_ВЕСЁЛОЕ"
HUMOR = "<Humor_Craft>\nбуквализм\n</Humor_Craft>"
SAMPLES = "<Few_Shot>\n1. пример\n</Few_Shot>"
BASE = "КАНАЛ_МАШИННОЙ_СТАДИИ"


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def set(self, key, value):
        raise AssertionError("запись в hot-конфиг на read-path")


class FakeChatCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}

    async def get_chat_params_full(self, chat_id):
        return {"overrides": {}}, None


class StubLLM:
    def __init__(self) -> None:
        self.captured: list[dict] = []
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.captured.append({"step": kwargs.get("step"),
                              "messages": [dict(m) for m in messages]})
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
                "user_question": "q", "answer_outline": "o",
                "facts": [], "limitations": [],
                "response_mode": "serious",
            }, ensure_ascii=False)
        return "ТЕКСТ"

    def _pg(self):
        return None


class StubMemory:
    async def get_window_messages(self, chat_id):
        return []


class StubMessage:
    text = "бот: распиши подробно"
    caption = None
    message_id = 1
    chat = type("C", (), {"type": "supergroup"})()
    reply_to_message = None
    from_user = None


def build_service():
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _render_current_question = D._render_current_question

        def _l1_reply_block(self, message):
            # P0 corrective 25.10.2026 (F1): метод инстанса (alias по uid).
            return D._l1_reply_block(self, message)

        _l1_speech_hints = D._l1_speech_hints
        _build_speech_understanding = D._build_speech_understanding
        _attach_l1_plan_meta = D._attach_l1_plan_meta
        _compose_speech_system = D._compose_speech_system

        async def _history_partial(self, chat_id, window):
            # ASAP2 T10-BOUNDARY: у стенда окно = вся сохранённая история
            # (старше ничего нет) → пометки «ГРАНИЦА ИСТОРИИ» нет; проверяются
            # профили машинных стадий, не граница.
            return False

        def __init__(self, llm):
            self.llm = llm
            self.memory = StubMemory()
            self.db = None
            self.bot_id = 999
            # ASAP 3 Corrective §4.4: read-path L1 берёт per-chat резолвер —
            # тот же реальный тип с пустым payload (окно стенда пустое).
            self.aliases = AliasResolver({})

    return Stub, D


def composer_on():
    hot.set_config_cache(FakeHot({
        "flags.unified_composer_enabled": True,
        "character.core": {"revision": 5, "enabled": True,
                           "full_text": CORE, "compact_text": CORE},
    }))
    chat_params.set_chat_params_cache(FakeChatCache())
    pc.reset_state()


def composer_off():
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    yield
    monkeypatch.delenv("UNIFIED_COMPOSER_ENABLED", raising=False)
    composer_off()


# ═══ профиль machine_json ═══════════════════════════════════════════════════

def test_machine_json_is_channel_contract_only():
    manifest = pc.compose_machine_system(BASE, writer="l1_planner", chat_id=7)
    assert manifest.system == BASE
    assert manifest.profile == "machine_json"
    trace = {t.layer: t for t in manifest.layers}
    assert trace["channel_contract"].rendered is True
    for layer in ("core", "identity", "context_lessons", "response_plan",
                  "expression", "humor_craft", "few_shot",
                  "style_policy_hint"):
        assert trace[layer].rendered is False, layer
        assert trace[layer].skip_reason == "profile:machine_stage", layer


def test_machine_json_ignores_core_and_humor_even_if_provided():
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile="machine_json", writer="factcheck_extract", chat_id=7,
        base_prompt=BASE,
        core=pc.CoreRef(text=CORE, revision="r5.c"),
        humor=pc.HumorStrategy(text=HUMOR, technique="literalism"),
        samples=(pc.SampleRef(text=SAMPLES, library_version="lib-1"),),
        style_policy=pc.StylePolicyRef(hint="hint", revision="r1"),
        gates=pc.GateState(unified_composer_enabled=True,
                           humor_library_enabled=True)))
    assert manifest.system == BASE
    assert CORE not in manifest.system
    assert HUMOR not in manifest.system and SAMPLES not in manifest.system
    assert manifest.versions["core"] == "r5.c"   # версия видна, но не рендерится


def test_editorial_and_silent_profiles_need_explicit_eligibility():
    for profile, reason in (("editorial_report", "profile:editorial_eligibility"),
                            ("internal_silent", "profile:internal_silent")):
        manifest = pc.compose_prompt(pc.PromptPlan(
            profile=profile, writer="summary_editor", chat_id=7,
            base_prompt=BASE, core=pc.CoreRef(text=CORE, revision="r5.c"),
            include_mode_block=False,
            gates=pc.GateState(unified_composer_enabled=True)))
        core = [t for t in manifest.layers if t.layer == "core"][0]
        assert core.rendered is False and core.skip_reason == reason
        assert CORE not in manifest.system
        assert manifest.system == BASE


def test_channel_text_only_profile_keeps_core_but_text_channel():
    """plain-текстовые каналы: Core есть, HTML-акцентов нет (формат канала)."""
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile="channel_text_only", writer="checkup_verbalizer", chat_id=7,
        channel="plain", html_safe=False, base_prompt=BASE, include_mode_block=False,
        core=pc.CoreRef(text=CORE, revision="r5.c"),
        gates=pc.GateState(unified_composer_enabled=True)))
    assert manifest.system.startswith(BASE)
    assert manifest.system.count(CORE) == 1
    assert "<b>" not in manifest.system


# ═══ реальные машинные стадии Direct при включённом композере ═══════════════

@pytest.mark.asyncio
async def test_direct_l1_planner_stage_has_no_core_and_no_extra_calls():
    from services import prompt_style_blocks as psb
    from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT as CANON
    Stub, D = build_service()

    composer_off()
    llm_off = StubLLM()
    await D._plan_direct_l1(
        Stub(llm_off), 12345, StubMessage(), "почему упал сервис", None,
        bundle=None, target_name="Аня", user_id=None, character_block=CORE,
        lore_enabled=False, image_enabled=False, force_required=False,
        reply_bot=False)

    composer_on()
    llm_on = StubLLM()
    assert mca_gates.unified_composer_enabled() is True
    await D._plan_direct_l1(
        Stub(llm_on), 12345, StubMessage(), "почему упал сервис", None,
        bundle=None, target_name="Аня", user_id=None, character_block=CORE,
        lore_enabled=False, image_enabled=False, force_required=False,
        reply_bot=False)

    cap_on = [c for c in llm_on.captured if c["step"] == "l1_planner"]
    cap_off = [c for c in llm_off.captured if c["step"] == "l1_planner"]
    assert cap_on and cap_off
    system_on = cap_on[0]["messages"][0]["content"]
    system_off = cap_off[0]["messages"][0]["content"]
    assert system_on == system_off == psb.resolve_prompt(
        "prompts.direct_l1_planner_system_prompt", CANON)
    assert CORE not in system_on
    assert llm_on.calls == llm_off.calls, "композер добавил LLM-вызов"
    manifest = pc.get_manifest(12345, writer="l1_planner")
    assert manifest is not None
    assert manifest.profile == "machine_json"


@pytest.mark.asyncio
async def test_direct_stage1_synthesizer_has_no_core_and_no_extra_calls():
    from services import prompt_style_blocks as psb
    from services.chat_prompts import DIRECT_SYNTHESIZER_SYSTEM_PROMPT as CANON
    Stub, D = build_service()
    raw = type("R", (), {"tool_context": "tool output",
                         "tool_trace": [{"tool": "web", "out_chars": 10}]})()

    composer_off()
    llm_off = StubLLM()
    await D._synthesize_direct_answer(Stub(llm_off), 12345, "q", raw, 0.7,
                                     character_block=CORE)

    composer_on()
    llm_on = StubLLM()
    await D._synthesize_direct_answer(Stub(llm_on), 12345, "q", raw, 0.7,
                                     character_block=CORE)

    stage1_on = [c for c in llm_on.captured if c["step"] == "stage1"]
    stage1_off = [c for c in llm_off.captured if c["step"] == "stage1"]
    assert stage1_on and stage1_off
    assert stage1_on[0]["messages"][0]["content"] == \
        stage1_off[0]["messages"][0]["content"] == psb.resolve_prompt(
            "prompts.direct_chat_synthesizer_system_prompt", CANON)
    assert CORE not in stage1_on[0]["messages"][0]["content"]
    assert llm_on.calls == llm_off.calls, "композер добавил LLM-вызов"
    manifest = pc.get_manifest(12345, writer="system2_stage1")
    assert manifest is not None and manifest.profile == "machine_json"
    # Stage-2 того же вызова — речевой профиль (личность по контракту есть).
    stage2 = [c for c in llm_on.captured if c["step"] == "stage2"]
    assert stage2 and CORE in stage2[0]["messages"][0]["content"]
