"""SOUL-1 (W2) — слои, провенанс и «покажи effective layers».

Доказывает: порядок слоёв == контракт §3; у каждого блока свой владелец и
ревизия; Core рендерится РОВНО один раз; одна инструкция не рендерится
дважды как `system_prompt_overrides` и Core (SOUL-03.6); каждая OFF-ветка
несёт видимую причину из закрытого набора; бюджета хватает на защищённые
слои; в события не утекает текст промпта (R17).

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W2 (SOUL-04.1/04.2, SOUL-03.6, 15.7)
"""
from __future__ import annotations

import json

import pytest

from services import mca_events
from services import prompt_composer as pc

BASE = "КАНАЛ: факты, имена, доставка, безопасность."
CORE = ("Ты общаешься как живой участник чата: наблюдательный, язвительный, "
        "прямой, с абсурдным мышлением, без агрессии. ХАРАКТЕР_МАРКЕР_ЯДРА")
DUPLICATED = "Характер: язвительный, прямой"
IDENTITY = ("<Persona>\nИмя: Бот.\n" + DUPLICATED +
            "\n</Persona>\n\n<Character_Rules>\nНе раскрывать ИИ.\n"
            "</Character_Rules>")
IDENTITY_CLEAN = ("<Persona>\nИмя: Бот.\n</Persona>\n\n<Character_Rules>\n"
                  "Не раскрывать ИИ.\n</Character_Rules>")
STYLE = "<Style_Requests>\nПиши без канцелярита.\n</Style_Requests>"
LESSONS = "<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>"
SPEECH = "<Speech_Understanding>\nact=assert\n</Speech_Understanding>"
EXTENT = "ОЖИДАЕМАЯ ПОЛНОТА: ПОДРОБНО."
EXPRESSION = "<Expression>\nтемпература: средняя\n</Expression>"
HUMOR = "<Humor_Craft>\nприём: буквализм\n</Humor_Craft>"
SAMPLES = "<Few_Shot>\n1. пример\n</Few_Shot>"
HINT = "<Style_Policy_Hint>\n- без кавычек\n</Style_Policy_Hint>"
USER_Q = "ВОПРОС_МАРКЕР: почему упал сервис"
EVIDENCE = "<Tool_Evidence>\nТУЛ_МАРКЕР: out_chars=812\n</Tool_Evidence>"


def full_plan(**overrides) -> pc.PromptPlan:
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=777,
        channel="plain", html_safe=True, run_id="run-A",
        base_prompt=BASE, base_source="global",
        response_plan=pc.PlanRef(text=EXTENT, extent="detailed",
                                 structure="answer", tone="inherit",
                                 revision=pc.sha12(EXTENT), source="l1"),
        core=pc.CoreRef(text=CORE, revision="r7." + pc.sha12(CORE),
                        source="global", document_revision="7",
                        compact_words=16),
        identity=pc.IdentityRef(text=IDENTITY,
                                revision=pc.identity_revision_from_text(
                                    IDENTITY), source="chat"),
        lessons=(pc.LessonRef(text=LESSONS, revision=pc.sha12(LESSONS),
                              lesson_ids=(3, 5)),),
        scoped_requests=(pc.Block("style_requests", STYLE, owner="l1",
                                  source="participant",
                                  revision=pc.sha12(STYLE)),),
        speech=pc.Block("speech_understanding", SPEECH, owner="l1",
                        revision=pc.sha12(SPEECH)),
        expression=pc.ExpressionSettings(text=EXPRESSION, revision="e3"),
        humor=pc.HumorStrategy(text=HUMOR, technique="literalism",
                               revision="h1"),
        samples=(pc.SampleRef(text=SAMPLES, library_version="lib-3",
                              revision="lib-3", technique="literalism"),),
        style_policy=pc.StylePolicyRef(hint=HINT, revision="r12",
                                       source="global", rule_count=2,
                                       soft_count=2),
        gates=pc.GateState(unified_composer_enabled=True,
                           humor_library_enabled=True,
                           humor_craft_enabled=True),
        user_parts=(USER_Q, EVIDENCE))
    return pc.PromptPlan(**{**plan.__dict__, **overrides}) \
        if overrides else plan


def layers_of(manifest: pc.PromptManifest) -> dict:
    return {t.layer: t for t in manifest.layers}


def test_layer_order_ownership_and_provenance():
    manifest = pc.compose_prompt(full_plan())
    order = [t.layer for t in manifest.layers]
    assert list(dict.fromkeys(order)) == list(pc.LAYER_ORDER)
    for trace in manifest.layers:
        assert trace.layer in pc.LAYERS
        assert trace.owner in pc.OWNERS, trace
        assert trace.source in pc.SOURCES, trace
        assert trace.skip_reason in pc.SKIP_REASONS, trace
    by_layer = layers_of(manifest)
    assert by_layer["core"].rendered is True
    assert by_layer["identity"].rendered is True
    assert by_layer["response_plan"].rendered is True
    assert by_layer["core"].revision == "r7." + pc.sha12(CORE)
    assert by_layer["style_policy_hint"].source == "global"
    # Каждый блок присутствует в system ровно один раз.
    for text in (BASE, CORE, STYLE, LESSONS, SPEECH, EXTENT, EXPRESSION,
                 HUMOR, SAMPLES, HINT):
        assert manifest.system.count(text) == 1, text
    assert manifest.user_parts == (USER_Q, EVIDENCE)
    assert USER_Q in manifest.user_parts[0]


def test_core_injected_exactly_once_between_channel_and_identity():
    manifest = pc.compose_prompt(full_plan())
    system = manifest.system
    assert system.startswith(BASE)
    assert system.count(CORE) == 1
    assert system.index(BASE) < system.index(CORE) < system.index("<Persona>")
    assert [t.layer for t in manifest.layers].count("core") == 1


def test_no_duplicate_owner_character_conflict():
    """SOUL-03.6: та же инструкция не рендерится и как overrides, и как Core."""
    manifest = pc.compose_prompt(full_plan())
    assert DUPLICATED not in manifest.system, "дубль owner-характера остался"
    assert manifest.system.count("язвительный, прямой") == 1  # остался в Core
    assert manifest.system.count(CORE) == 1
    assert "<Persona>" in manifest.system, "остальная персона не пострадала"
    assert "duplicate_owner_character" in [
        c.conflict_id for c in manifest.conflicts]
    identity = layers_of(manifest)["identity"]
    assert identity.conflict == "duplicate_owner_character"
    assert identity.rendered is True
    assert identity.revision == pc.identity_revision_from_text(IDENTITY_CLEAN)
    conflict = manifest.conflicts[0]
    assert conflict.outcome == "keep_stronger"
    assert conflict.provenance.startswith("core:")


def test_identity_not_touched_without_core():
    """Без Core личность рендерится как есть (вычистки нет)."""
    manifest = pc.compose_prompt(full_plan(core=pc.CoreRef(
        skip_reason="core_absent", source="default")))
    assert manifest.system.count(DUPLICATED) == 1
    assert "<Persona>" in manifest.system
    assert not manifest.conflicts
    assert layers_of(manifest)["core"].skip_reason == "core_absent"


def test_effective_layers_api_and_diff():
    pc.reset_state()
    first = pc.compose_prompt(full_plan(core=pc.CoreRef(
        text=CORE, revision="r7.x", source="global")))
    rendered_first = pc.render_effective_layers(first)
    assert rendered_first["order_matches_canonical"] is True
    assert rendered_first["tokens_total"] > 0
    assert rendered_first["diff_vs_previous"] is None
    assert rendered_first["versions"]["core"] == "r7.x"
    second = pc.compose_prompt(full_plan(core=pc.CoreRef(
        text=CORE + " ПРАВКА8", revision="r8.y", source="global")))
    rendered_second = pc.render_effective_layers(second)
    diff = rendered_second["diff_vs_previous"]
    assert diff["previous_manifest_id"] == first.manifest_id
    assert "core" in diff["changed_layers"]
    assert second.manifest_id != first.manifest_id


def test_skip_reasons_are_closed_and_visible_without_core_layer():
    manifest = pc.compose_prompt(full_plan(
        core=None,
        style_policy=None,
        samples=(),
        feedback_hint=None) if False else full_plan(
        core=None, style_policy=None, samples=(),
        gates=pc.GateState(unified_composer_enabled=True,
                           humor_library_enabled=False)))
    by_layer = layers_of(manifest)
    assert by_layer["core"].rendered is False
    assert by_layer["core"].skip_reason == "core_absent"
    assert by_layer["few_shot"].rendered is False
    assert by_layer["few_shot"].skip_reason in ("samples_disabled",
                                                "samples_absent")
    assert by_layer["style_policy_hint"].skip_reason == "style_policy_absent"
    assert all(t.skip_reason in pc.SKIP_REASONS for t in manifest.layers)


def test_budget_never_evicts_channel_identity_question_or_evidence(monkeypatch):
    """SOUL-04.5: бюджет режет добавку, но не вопрос/инструкцию/evidence."""
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "40")
    manifest = pc.compose_prompt(full_plan())
    by_layer = layers_of(manifest)
    assert by_layer["channel_contract"].rendered is True
    assert by_layer["identity"].rendered is True
    assert by_layer["response_plan"].rendered is True
    assert manifest.user_parts == (USER_Q, EVIDENCE)
    assert by_layer["few_shot"].skip_reason in ("budget_excluded",
                                                "samples_absent",
                                                "samples_disabled")
    assert USER_Q in manifest.user_parts[0]
    assert EVIDENCE in manifest.user_parts[1]
    assert all(t.skip_reason in pc.SKIP_REASONS for t in manifest.layers)


def test_core_is_never_evicted_by_additive_budget(monkeypatch):
    """F5 (review-w2): Core — обязательный слой, бюджет его не вытесняет.

    Перерасход из-за Core виден конфликтом `core_protected_from_budget`
    (outcome `exempted_protected`), режется при этом добавка (expression/
    humor/samples/hint), а не личность.
    """
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "20")
    manifest = pc.compose_prompt(full_plan())
    by_layer = layers_of(manifest)
    core = by_layer["core"]
    assert core.rendered is True
    assert core.skip_reason == ""
    assert CORE in manifest.system
    assert "budget_excluded" != core.skip_reason
    for layer in ("expression", "humor_craft", "few_shot",
                  "style_policy_hint"):
        assert by_layer[layer].rendered is False, layer
        assert by_layer[layer].skip_reason == "budget_excluded", layer
    conflict = [c for c in manifest.conflicts
                if c.conflict_id == "core_protected_from_budget"]
    assert conflict, "перерасход Core обязан быть видимым"
    assert conflict[0].outcome == "exempted_protected"
    assert conflict[0].outcome in pc.CONFLICT_OUTCOMES
    assert conflict[0].layer == "core"
    assert conflict[0].provenance.startswith("core:")
    assert CORE not in conflict[0].provenance, "R17: без текста промпта"
    assert "budget=20" in conflict[0].detail
    # Защищённая user-часть не изменилась.
    assert manifest.user_parts == (USER_Q, EVIDENCE)


def test_manifest_for_events_has_no_prompt_text_and_events_are_deduped(
        monkeypatch):
    calls: list[dict] = []

    def _capture(name, **fields):
        calls.append({"name": name, **fields})
        return {"event_name": name, **fields}

    monkeypatch.setattr(mca_events, "emit_mca_event", _capture)
    pc.reset_state()
    manifest = pc.compose_prompt(full_plan(core=None, style_policy=None))
    payload = json.dumps(pc.manifest_for_events(manifest), ensure_ascii=False)
    for leak in (CORE, USER_Q, EVIDENCE, IDENTITY, BASE, HINT, "<Persona>"):
        assert leak not in payload
    assert manifest.system not in payload
    pc.emit_layer_events_once(manifest)
    pc.emit_layer_events_once(manifest)          # повтор — без спама
    core_events = [c for c in calls if c["status"] == "core:core_absent"]
    assert len(core_events) == 1
    for call in calls:
        assert "system" not in json.dumps(call, ensure_ascii=False)
        assert call["component"] == "prompt_composer"


def test_source_error_gives_skip_reason_not_silence(monkeypatch):
    """Ошибка источника → skip_reason + notable-событие, а не пустота."""
    calls: list[dict] = []
    monkeypatch.setattr(mca_events, "emit_mca_event",
                        lambda name, **f: calls.append({"name": name, **f})
                        or {"event_name": name})
    manifest = pc.compose_prompt(full_plan(core=pc.CoreRef(
        skip_reason="core_read_error", source="global")))
    trace = layers_of(manifest)["core"]
    assert trace.rendered is False
    assert trace.skip_reason == "core_read_error"
    pc.reset_state()
    pc.emit_layer_events_once(manifest)
    failed = [c for c in calls if c.get("outcome") == "failed"]
    assert failed, calls
    assert failed[0]["level"] == "WARN"
    assert failed[0]["status"] == "core:core_read_error"


def test_compose_never_raises_on_broken_ref():
    bad = full_plan()
    bad = pc.PromptPlan(**{**bad.__dict__,
                           "response_plan": "НЕ_PLAN_REF"})
    manifest = pc.compose_prompt(bad)          # не должно бросить
    assert isinstance(manifest, pc.PromptManifest)
    assert BASE in manifest.system


def test_one_word_extent_is_not_lost_and_has_no_conflict_after_w3():
    """Шов 3 (обновлён W3): `one_word` — поддерживаемый extent, не алиас `micro`.

    Композер не подменяет значение алиасом (никакой legacy-склейки) и не
    теряет его: после W3 `one_word` входит в ``response_extent.EXTENTS``,
    поэтому конфликта `one_word_not_supported` больше нет, а значение едет в
    манифест как есть (строгий блок рендерит `response_extent`).
    """
    micro_text = "ОЖИДАЕМАЯ ПОЛНОТА: МИКРО."
    manifest = pc.compose_prompt(full_plan(response_plan=pc.PlanRef(
        text=micro_text, extent="one_word", structure="chat",
        revision=pc.sha12(micro_text), source="l1")))
    trace = layers_of(manifest)["response_plan"]
    assert trace.rendered is True
    assert trace.conflict == ""
    assert manifest.system.count(micro_text) == 1
    assert "one_word_not_supported" not in [
        c.conflict_id for c in manifest.conflicts]
    assert pc.render_effective_layers(manifest)["conflict_ids"] == [
        "duplicate_owner_character"]
    # Оба режима — отдельные поддерживаемые значения (никакого схлопывания).
    from services import response_extent as _extent
    assert "one_word" in _extent.EXTENTS and "micro" in _extent.EXTENTS
    clean = pc.compose_prompt(full_plan(response_plan=pc.PlanRef(
        text=micro_text, extent="micro", revision=pc.sha12(micro_text))))
    assert "one_word_not_supported" not in [
        c.conflict_id for c in clean.conflicts]


def test_manifest_id_is_stable_and_content_bound():
    a = pc.compose_prompt(full_plan())
    b = pc.compose_prompt(full_plan())
    assert a.manifest_id == b.manifest_id
    c = pc.compose_prompt(full_plan(core=pc.CoreRef(
        text=CORE + "ДРУГОЕ", revision="r9.z", source="global")))
    assert c.manifest_id != a.manifest_id
