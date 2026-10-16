"""SOUL-1 (W2) — композиция флагов: OFF-ветка = паритет + видимая причина.

Проверяется таблица истинности новых осей композера против существующих
рубильников (SOUL-15.6/15.7, §6 контракта):

* `UNIFIED_COMPOSER_ENABLED` доходит только через env AND каталог; OFF →
  композер не участвует, сборка прежняя (см. также parity-off файл);
* `CHARACTER_CORE_ENABLED` OFF → Core не рендерится, личность живёт;
* `SPEECH_STYLE_POLICY_ENABLED` OFF → нет hint/политики, Core жив;
* `HUMOR_LIBRARY_ENABLED` OFF → нет few-shot слоя;
* `HUMOR_FEEDBACK_ENABLED` OFF → **речь не деградирует** (не гейтит рендер);
* нулевой дополнительный LLM-вызов (SOUL-06.6);
* новые оси не дублируют существующие «тихие» рубильники.

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W2 (SOUL-15.6/15.7, SOUL-04.5)
"""
from __future__ import annotations

import inspect

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_gates
from services import prompt_composer as pc

BASE = "КАНАЛ"
CORE = "ЯДРО_ХАРАКТЕРА"
IDENTITY = "<Persona>\nИмя: Бот.\n</Persona>"
HINT = "<Style_Policy_Hint>\n- без кавычек\n</Style_Policy_Hint>"
SAMPLES = "<Few_Shot>\n1. пример\n</Few_Shot>"
HUMOR = "<Humor_Craft>\nбуквализм\n</Humor_Craft>"


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list = []

    def get(self, key, default=None):
        if key in self.values:
            return self.values[key]
        return default

    def set(self, key, value):
        self.writes.append(("set", key))

    def set_many(self, items):
        self.writes.append(("set_many", len(items)))


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})
        self.writes: list = []

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


def plan(**gate_overrides) -> pc.PromptPlan:
    gates = pc.GateState(
        unified_composer_enabled=True, character_core_enabled=True,
        speech_style_policy_enabled=True, humor_library_enabled=True,
        humor_feedback_enabled=False)
    gates = dataclasses_replace(gates, **gate_overrides)
    return pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=404,
        base_prompt=BASE, core=pc.CoreRef(text=CORE, revision="r1.x",
                                          source="global"),
        identity=pc.IdentityRef(text=IDENTITY, revision="i1"),
        style_policy=pc.StylePolicyRef(hint=HINT, revision="r2.p",
                                       source="global"),
        humor=pc.HumorStrategy(text=HUMOR, technique="literalism",
                               revision="h1"),
        samples=(pc.SampleRef(text=SAMPLES, library_version="lib-1"),),
        gates=gates)


def dataclasses_replace(obj, **kwargs):
    import dataclasses
    return dataclasses.replace(obj, **kwargs)


def by_layer(manifest, layer):
    return [t for t in manifest.layers if t.layer == layer][0]


# ═══ композиция axes ════════════════════════════════════════════════════════

@pytest.mark.parametrize("env_on,catalog_on,expected", [
    (False, False, False),
    (False, True, False),      # env-ось важнее (аварийный рубильник)
    (True, False, False),
    (True, True, True),
])
def test_composer_master_axis_is_env_and_catalog(monkeypatch, env_on,
                                                 catalog_on, expected):
    hot.set_config_cache(FakeHot(
        {"flags.unified_composer_enabled": catalog_on}))
    if env_on:
        monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    else:
        monkeypatch.delenv("UNIFIED_COMPOSER_ENABLED", raising=False)
    try:
        assert mca_gates.unified_composer_enabled() is expected
        assert pc.gates_from_config().unified_composer_enabled is expected
    finally:
        hot.set_config_cache(None)


def test_core_axis_off_keeps_identity_and_reports_reason():
    manifest = pc.compose_prompt(plan(character_core_enabled=False))
    core = by_layer(manifest, "core")
    assert core.rendered is False and core.skip_reason == "core_disabled"
    assert by_layer(manifest, "identity").rendered is True
    assert CORE not in manifest.system
    assert "persona_disabled" not in [t.skip_reason for t in manifest.layers]


def test_style_policy_axis_off_keeps_core():
    manifest = pc.compose_prompt(plan(speech_style_policy_enabled=False))
    hint = by_layer(manifest, "style_policy_hint")
    assert hint.rendered is False and hint.skip_reason == "style_policy_disabled"
    assert by_layer(manifest, "core").rendered is True
    assert HINT not in manifest.system


def test_humor_library_axis_off_removes_few_shot_only():
    manifest = pc.compose_prompt(plan(humor_library_enabled=False))
    samples = by_layer(manifest, "few_shot")
    assert samples.rendered is False and samples.skip_reason == "samples_disabled"
    assert by_layer(manifest, "core").rendered is True
    assert SAMPLES not in manifest.system


def test_humor_feedback_off_does_not_touch_speech():
    """HUMOR_FEEDBACK_ENABLED OFF → речь не деградирует (SOUL-15.6)."""
    off = pc.compose_prompt(plan(humor_feedback_enabled=False))
    on = pc.compose_prompt(plan(humor_feedback_enabled=True))
    rendered_off = [t.layer for t in off.layers if t.rendered]
    rendered_on = [t.layer for t in on.layers if t.rendered]
    assert rendered_off == rendered_on
    assert off.system == on.system
    assert off.manifest_id == on.manifest_id
    assert off.flags["humor_feedback_enabled"] is False
    assert on.flags["humor_feedback_enabled"] is True


def test_all_axes_visible_in_manifest_flags():
    manifest = pc.compose_prompt(plan())
    for key in ("unified_composer_enabled", "character_core_enabled",
                "speech_style_policy_enabled", "humor_library_enabled",
                "humor_feedback_enabled", "persona_enabled",
                "character_layers_enabled", "smart_verbalizer_modes_enabled",
                "response_plan_enabled"):
        assert key in manifest.flags, key


def test_legacy_axes_respected_not_overridden():
    """Существующие рубильники сохраняют свой смысл (не дублируются)."""
    manifest = pc.compose_prompt(plan(persona_enabled=False,
                                     smart_verbalizer_modes_enabled=False,
                                     response_plan_enabled=False))
    assert by_layer(manifest, "identity").skip_reason == "persona_disabled"
    assert by_layer(manifest, "response_plan").skip_reason == \
        "response_plan_disabled"
    base = by_layer(manifest, "channel_contract")
    assert base.skip_reason == "verbilizer_modes_disabled"
    assert by_layer(manifest, "core").rendered is True


def test_w2_gates_do_not_duplicate_existing_kill_switches():
    assert not (set(mca_gates.W2_GATES) & set(mca_gates.KILL_SWITCHES))
    assert set(mca_gates.W2_ENV_KEYS.values()) == set(mca_gates.W2_GATES)
    silent = {"SMART_VERBALIZER_MODES_ENABLED", "MCA_CHARACTER_LAYERS_ENABLED",
              "MCA_CHARACTER_SPEECH_ENABLED", "MCA_STYLE_SCOPE_ENABLED",
              "MCA_SELF_MODEL_ENABLED", "MCA_POSTPROCESS_FORM_GUARD_ENABLED"}
    assert not (set(mca_gates.W2_GATES) & silent)
    assert mca_gates.unified_composer_env_enabled() is False


def test_every_off_axis_has_documented_parity_text():
    for name, (default, parity) in mca_gates.W2_GATES.items():
        assert isinstance(default, bool)
        assert len(parity) > 20, f"{name}: OFF-паритет не описан"


# ═══ нулевой дополнительный LLM-вызов (SOUL-06.6) ═══════════════════════════

class _StubLLM:
    def __init__(self):
        self.calls = 0
        self.captured: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.captured.append([dict(m) for m in messages])
        return "ОТВЕТ"


@pytest.mark.asyncio
async def test_zero_extra_llm_calls_on_normal_answer(monkeypatch):
    """Сборка композера не стоит ни одного лишнего LLM-вызова."""
    import json as _json

    from services import response_extent as _extent
    from services.direct_chat_service import DirectChatService as D

    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot.set_config_cache(FakeHot({"flags.unified_composer_enabled": True,
                                  "character.core": {"revision": 1,
                                                     "enabled": True,
                                                     "full_text": CORE,
                                                     "compact_text": CORE}}))
    chat_params.set_chat_params_cache(FakeChatCache({}))
    pc.reset_state()

    class Stub:
        _l2_write_answer = D._l2_write_answer
        _compose_speech_system = D._compose_speech_system

        def __init__(self, llm):
            self.llm = llm
            self.db = None

    llm = _StubLLM()
    svc = Stub(llm)
    result = await D._l2_write_answer(
        svc, 404, "вопрос", temperature=0.7, correlation_id="run-llm",
        character_block=IDENTITY,
        response_plan=_extent.ResponsePlan(task_kind="explanation",
                                           extent="detailed",
                                           structure="answer",
                                           delivery_hint="plain"))
    assert result is not None
    assert llm.calls == 1, f"лишние LLM-вызовы: {llm.calls}"
    manifest = pc.get_manifest(404, run_id="run-llm", writer="l2_writer")
    assert manifest is not None and CORE in manifest.system
    source = inspect.getsource(pc)
    assert ".generate(" not in source and "from services.llm" not in source
    assert _json.dumps(pc.manifest_for_events(manifest)).count("ОТВЕТ") == 0
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
