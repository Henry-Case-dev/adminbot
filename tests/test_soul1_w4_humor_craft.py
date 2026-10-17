"""SOUL-1 / W4 — SOUL-06: Humor Craft как управляемый ситуационный слой.

Покрытие требований (requirements-map.json W4):
  * SOUL-06.0 — управляемый блок с toggle и измеримым влиянием приёмов;
  * SOUL-06.1–06.5 — пять техник воспроизводимы как ЗАВОДСКИЕ редакции
    (реестр `humor.technique.*`), каждая даёт свой измеримый слой;
  * SOUL-06.6 — главный критерий: причинная связность/уместность, а не
    частота мата; нет требований «метафора в каждой реплике», нет
    шаблонных зачинов/финалов; серьёзный контекст не ломается;
  * SOUL-06.7 — диагностическое выключение ремесла ПРИ ЖИВОМ Core;
    тестируемость отдельных приёмов; **0 дополнительных LLM-вызовов** на
    обычный ответ; опциональная оценка кандидатов — bounded, default OFF.

TEST-LIFECYCLE: CONTRACT owner=soul-1/W4
"""
import dataclasses
import inspect

import pytest

from services import mca_gates
from services import mca_humor_craft as hc
from services import prompt_composer as pc
from services import prompt_registry as pr
from services import direct_l1


CORE = "ТЫ — ХАРАКТЕР. Отвечай как живой участник."
BASE = "БАЗА КАНАЛА"


def _gates(**overrides) -> pc.GateState:
    gates = pc.GateState(unified_composer_enabled=True,
                         character_core_enabled=True,
                         speech_style_policy_enabled=True,
                         humor_library_enabled=False,
                         humor_craft_enabled=True)
    return dataclasses.replace(gates, **overrides) if overrides else gates


def _manifest(*, humor=None, gates=None) -> pc.PromptManifest:
    return pc.compose_prompt(pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=101,
        base_prompt=BASE, core=pc.CoreRef(text=CORE, revision="r1"),
        humor=humor, gates=gates or _gates()))


def _layer(manifest, name):
    return [t for t in manifest.layers if t.layer == name][0]


# ═══ SOUL-06.0/06.7: ось и диагностический toggle ══════════════════════════

def test_gate_defaults_off_and_is_env_and_catalog():
    assert mca_gates.W2_GATES["HUMOR_CRAFT_ENABLED"][0] is False
    assert mca_gates.w2_gate_default("HUMOR_CRAFT_ENABLED") is False
    assert "HUMOR_CRAFT_ENABLED" in mca_gates.W2_ENV_KEYS.values()
    assert hc.gate_on() is False


def test_craft_off_keeps_core_and_marks_reason():
    """SOUL-06.7: выключенное ремесло не выключает характер."""
    manifest = _manifest(humor=pc.HumorStrategy(text=hc.render_layer("deadpan"),
                                                technique="deadpan"),
                         gates=_gates(humor_craft_enabled=False))
    humor = _layer(manifest, "humor_craft")
    assert humor.rendered is False and humor.skip_reason == "humor_disabled"
    assert _layer(manifest, "core").rendered is True
    assert CORE in manifest.system
    assert hc.render_layer("deadpan") not in manifest.system


def test_every_axis_off_is_documented_and_visible_in_manifest():
    manifest = _manifest()
    assert manifest.flags["humor_craft_enabled"] is True
    assert manifest.flags["humor_library_enabled"] is False
    for name, (default, parity) in mca_gates.W2_GATES.items():
        assert isinstance(default, bool) and len(parity) > 20, name


# ═══ SOUL-06.1–06.5: пять техник ═══════════════════════════════════════════

def test_five_techniques_match_l1_closed_set():
    assert set(hc.TECHNIQUES) == set(direct_l1.COMIC_STRATEGIES) - {"none"}


@pytest.mark.parametrize("technique", hc.TECHNIQUES)
def test_each_technique_is_registered_factory_edition(technique):
    """Каждая техника — редактируемая заводская редакция реестра."""
    block_id = f"humor.technique.{technique}"
    spec = pr.block(block_id)
    assert spec is not None, block_id
    assert spec.owner_lane == "W4" and spec.speech is True
    assert spec.migration == "factory"
    assert pr.factory_text(block_id) == hc.technique_text(technique)
    assert pr.factory_revision(block_id).startswith(pr.FACTORY_PREFIX)
    assert technique in pr.FACTORY_REVISION_LABELS[block_id] or \
        pr.FACTORY_REVISION_LABELS[block_id] == "humor-technique-w4"


def test_common_guard_is_registered_and_carries_the_criterion():
    spec = pr.block("humor.craft.common")
    assert spec is not None and spec.code_source.endswith("HUMOR_CRAFT_GUARD")
    text = pr.factory_text("humor.craft.common").casefold()
    # главный критерий — связность/уместность, а не частота мата
    assert "уместность" in text
    assert "не частота мата" in text
    # серьёзное не ломается; нет предписаний частоты
    assert "неприкосновенны" in text
    for banned in ("в каждой реплике", "обязательно обматери",
                   "три ступени"):
        assert banned not in text


def test_registry_fingerprint_matches_declared_constant():
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12


# ═══ измеримое влияние приёмов (SOUL-06.0/06.7) ════════════════════════════

def test_probe_gives_measurable_layer_for_each_technique():
    seen: set[str] = set()
    for technique in hc.TECHNIQUES:
        probe = hc.probe_technique(technique)
        assert probe.enabled is True and probe.layer_tokens > 0
        assert probe.layer_chars <= hc.MAX_LAYER_CHARS
        assert probe.layer_revision and probe.layer_revision not in seen
        assert f"llm_calls=0" in probe.detail
        seen.add(probe.layer_revision)
    assert len(seen) == len(hc.TECHNIQUES)


def test_catalog_reports_owner_state_and_reason_per_technique():
    cfg = hc.CraftConfig(enabled=True,
                         disabled_techniques=("deadpan",), source="chat",
                         revision=3)
    rows = {row["id"]: row for row in hc.technique_catalog(cfg)}
    assert rows["deadpan"]["owner_enabled"] is False
    assert rows["deadpan"]["reason"] == "humor_disabled"
    assert rows["literalism"]["owner_enabled"] is True
    assert rows["literalism"]["source"] == "chat"


def test_rendered_layer_lands_in_composer_once():
    layer = hc.render_layer("literalism")
    manifest = _manifest(humor=pc.HumorStrategy(text=layer,
                                                technique="literalism"))
    trace = _layer(manifest, "humor_craft")
    assert trace.rendered is True and trace.owner == "library"
    assert manifest.system.count(layer) == 1
    assert trace.tokens > 0


# ═══ SOUL-06.6: уместность и запреты ══════════════════════════════════════

def test_selection_requires_l1_advice_and_respects_serious_context():
    assert hc.select_technique(comic_strategy="").reason == "humor_no_strategy"
    assert hc.select_technique(comic_strategy="none").reason == \
        "humor_no_strategy"
    serious = hc.select_technique(comic_strategy="literalism",
                                  structure="report")
    assert serious.technique == "" and serious.reason == \
        "humor_serious_context"
    dry = hc.select_technique(comic_strategy="literalism", tone="serious")
    assert dry.reason == "humor_serious_context"
    code = hc.select_technique(comic_strategy="absurd_escalation",
                               structure="code")
    assert code.reason == "humor_serious_context"


def test_short_extents_do_not_break_length_contract():
    """Строгий one_word/micro не ломается комической экспансией."""
    assert hc.select_technique(comic_strategy="absurd_escalation",
                               extent="one_word").reason == "humor_extent_fit"
    assert hc.select_technique(comic_strategy="literalism",
                               extent="micro").reason == "humor_extent_fit"
    ok = hc.select_technique(comic_strategy="deadpan", extent="micro")
    assert ok.technique == "deadpan"


def test_negative_feedback_weakens_strategy_in_context():
    """SOUL-06.6/08.10: штраф контекста гасит приём, но не характер."""
    weak = hc.select_technique(comic_strategy="literalism",
                               context_weight=0.01)
    assert weak.technique == ""
    assert weak.reason == "humor_context_penalty"
    mild = hc.select_technique(comic_strategy="literalism",
                               context_weight=0.5)
    assert mild.technique == "literalism"


def test_no_repeated_templates_and_no_tool_call_names():
    for technique in hc.TECHNIQUES:
        text = hc.technique_text(technique).casefold()
        for banned in hc.BANNED_TEMPLATES:
            assert banned not in text, (technique, banned)
    ok, reason = hc.accepts_output("Ну ты и дал, классика жанра")
    assert ok is False and "классика_жанра" in reason
    assert hc.accepts_output("Логично, вопросов нет") == (True, "")


def test_technique_texts_never_prescribe_frequency_or_profanity():
    for technique in hc.TECHNIQUES:
        text = hc.technique_text(technique).casefold()
        for banned in ("обязательно", "каждый ответ", "всегда мат",
                       "обматери"):
            assert banned not in text, (technique, banned)


# ═══ SOUL-06.7: 0 дополнительных LLM-вызовов ══════════════════════════════

def test_craft_module_does_not_call_llm():
    source = inspect.getsource(hc)
    assert ".generate(" not in source.split("async def evaluate_candidates")[0]
    assert hc.layer_calls("literalism") == 0
    assert hc.layer_calls("") == 0


@pytest.mark.asyncio
async def test_zero_extra_llm_calls_on_normal_answer(monkeypatch):
    """Обычный ответ с включённым ремеслом = ровно один LLM-вызов (Writer)."""
    from services import chat_params, hot_config
    from services.direct_chat_service import DirectChatService as D
    from services import response_extent as _extent

    class _StubLLM:
        def __init__(self):
            self.calls = 0

        async def generate(self, messages, **kwargs):
            self.calls += 1
            return "ОТВЕТ"

    class _FakeHot:
        def __init__(self, values):
            self.values = values

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            return None

        def set_many(self, items):
            return None

    class _FakeChat:
        async def get_chat_params(self, chat_id):
            return {"overrides": {}}

        async def get_chat_params_full(self, chat_id):
            return await self.get_chat_params(chat_id), None

    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    monkeypatch.setenv("HUMOR_CRAFT_ENABLED", "1")
    monkeypatch.setenv("HUMOR_LIBRARY_ENABLED", "1")
    monkeypatch.setenv("HUMOR_FEEDBACK_ENABLED", "1")
    hot_config.set_config_cache(_FakeHot({
        "flags.unified_composer_enabled": True,
        "flags.humor_craft_enabled": True,
        "flags.humor_library_enabled": True,
        "flags.humor_feedback_enabled": True,
        "character.core": {"revision": 1, "enabled": True,
                           "full_text": CORE, "compact_text": CORE}}))
    chat_params.set_chat_params_cache(_FakeChat())
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
        svc, 505, "а правда, что чайник теперь отчитывается?",
        temperature=0.7, correlation_id="run-w4-llm",
        character_block="ЛИЧНОСТЬ",
        response_plan=_extent.ResponsePlan(task_kind="explanation",
                                          extent="detailed",
                                          structure="answer",
                                          delivery_hint="plain",
                                          comic_strategy="bureaucratic_logic"))
    assert result is not None
    assert llm.calls == 1, f"лишние LLM-вызовы: {llm.calls}"
    manifest = pc.get_manifest(505, run_id="run-w4-llm", writer="l2_writer")
    assert manifest is not None
    humor = _layer(manifest, "humor_craft")
    assert humor.rendered is True and humor.tokens > 0
    assert hc.render_layer("bureaucratic_logic") in manifest.system
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


@pytest.mark.asyncio
async def test_candidate_eval_is_bounded_and_off_by_default(monkeypatch):
    class _StubLLM:
        def __init__(self):
            self.calls = 0

        async def generate(self, messages, **kwargs):
            self.calls += 1
            return "[1]"

    llm = _StubLLM()
    res = await hc.evaluate_candidates(candidates=["а", "б", "в"], llm=llm)
    assert res.applied is False and res.reason == "candidate_eval_disabled"
    assert llm.calls == 0 == res.calls

    monkeypatch.setenv("HUMOR_CANDIDATE_EVAL_ENABLED", "1")

    class _Catalog:
        def get(self, key, default=None):
            return True

    from services import hot_config
    hot_config.set_config_cache(_Catalog())
    try:
        res = await hc.evaluate_candidates(candidates=["а", "б", "в"], llm=llm)
        assert llm.calls == 1
        assert res.applied is True and res.calls == 1
        assert len(res.candidates) <= hc.CANDIDATE_EVAL_MAX_CANDIDATES
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_candidate_eval_failure_is_honest_noop():
    class _BrokenLLM:
        async def generate(self, messages, **kwargs):
            raise RuntimeError("provider down")

    res = await hc.evaluate_candidates(candidates=["а", "б"],
                                      llm=_BrokenLLM())
    assert res.applied is False                       # выключено по умолчанию
    assert res.reason == "candidate_eval_disabled"
