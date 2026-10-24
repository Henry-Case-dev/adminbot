# -*- coding: utf-8 -*-
"""P0-E (source-2026-10-24 §6, EX-01..EX-03) — фактическая работа FREQUENT.

Доказывает три вещи:
1. слой Expression больше НЕ выпадает молча по аддитивному бюджету
   (раньше `budget_excluded` убирал режим мата из system и давал ложный
   «ноль различий»);
2. формулировка FREQUENT означает привычную и заметную часть СОБСТВЕННОЙ
   речи, а не разрешение «в исключительных случаях»; OFF/OCCASIONAL по
   смыслу не изменены, квот/счётчиков/настоятельных вставок нет;
3. лестница текста (PREV = текущий прод-текст) идемпотентна, кастом
   владельца не перезаписывается; постпроцессор не вставляет и не удаляет
   мат (EX-03).

TEST-LIFECYCLE: CONTRACT owner=P0-E/EX-01..EX-03 (source-2026-10-24 §6, §9)
"""
from __future__ import annotations

import pytest

from services import mca_expression as ex
from services import prompt_composer as pc

HEADER = ex.EXPRESSION_HEADER


def _plan(expression: pc.ExpressionSettings, **overrides) -> pc.PromptPlan:
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=777,
        channel="plain", html_safe=True,
        base_prompt="КАНАЛ: факты, имена, доставка.",
        base_source="global", expression=expression,
        gates=pc.GateState(unified_composer_enabled=True),
        user_parts=("ВОПРОС_МАРКЕР: как оно?",))
    return pc.PromptPlan(**{**plan.__dict__, **overrides}) if overrides else plan


def _layer(manifest, layer: str):
    return [t for t in manifest.layers if t.layer == layer][0]


# ═══ 1. Квоты нет: слой не теряется ═════════════════════════════════════════

@pytest.mark.parametrize("mode", ("off", "occasional", "frequent"))
def test_expression_marker_survives_former_tight_budget(monkeypatch, mode):
    """QUOTA-REMOVAL: прежний «тесный» env инертен — маркер режима на месте."""
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "10")
    expression = ex.build_expression_settings({"profanity": mode}, None)
    assert expression.text and expression.enabled
    manifest = pc.compose_prompt(_plan(expression))
    trace = _layer(manifest, "expression")
    assert trace.rendered is True
    assert trace.skip_reason == ""
    assert "<Expression_Settings>" in manifest.system
    assert ex.PROFANITY_INSTRUCTIONS[mode] in manifest.system
    # слой не помечен тихой потерей ни в одном виде
    assert all(t.skip_reason != "budget_excluded"
               for t in manifest.layers if t.layer == "expression")
    assert not [c for c in manifest.conflicts
                if c.conflict_id == "expression_protected_from_budget"]


def test_no_budget_conflict_objects_are_produced(monkeypatch):
    """QUOTA-REMOVAL: служебных конфликтов о перерасходе квоты больше нет."""
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", "10")
    expression = ex.build_expression_settings({"profanity": "frequent"}, None)
    manifest = pc.compose_prompt(_plan(expression))
    ids = {c.conflict_id for c in manifest.conflicts}
    assert "expression_protected_from_budget" not in ids
    assert "core_protected_from_budget" not in ids
    assert ex.PROFANITY_INSTRUCTIONS["frequent"] in manifest.system
    # R17: в манифесте событий нет текста промпта (диагностика остаётся кодами)
    import json as _json
    payload = _json.dumps(pc.manifest_for_events(manifest), ensure_ascii=False)
    assert "Expression_Settings" not in payload


# ═══ 2. Семантика FREQUENT ═════════════════════════════════════════════════

def test_frequent_is_habit_of_own_speech_not_permission():
    text = ex.PROFANITY_INSTRUCTIONS["frequent"]
    low = text.casefold()
    assert "привычная и заметная" in low
    assert "собственной речи" in low
    assert "всегда, а не изредка" in low
    # не «разрешение в исключительных случаях» и не мягкое допущение
    for banned in ("исключительн", "изредка допустим", "мат разрешён",
                   "мат допустим", "нецензурные выражения допустимы"):
        assert banned not in low, banned
    # нет квот/счётчиков/настоятельных вставок (source §6.3)
    for banned in ("кажд", "минимум", "не менее", "обязательн", "квот",
                   "процент", "вероятн"):
        assert banned not in low, banned
    assert not any(ch.isdigit() for ch in text)


def test_off_and_occasional_semantics_unchanged():
    """OFF/OCCASIONAL — прежние тексты (source §6.3 меняет только FREQUENT)."""
    assert ex.PROFANITY_INSTRUCTIONS["off"] == \
        "Не используй мат в собственной речи."
    assert ex.PROFANITY_INSTRUCTIONS["occasional"] == (
        "Пиши разговорным языком с примесью мата. Нецензурные выражения "
        "используй как обычные эмоциональные оценки и междометия, без "
        "необходимости специально обосновывать их появление. Мат не должен "
        "доминировать в речи.")


def test_expression_is_rendered_top_of_mode_instructions():
    """Слой остаётся единственным носителем режима и рендерится целиком."""
    for mode in ("off", "occasional", "frequent"):
        text = ex.render_expression_text(
            ex.resolve_effective({"profanity": mode}, None))
        assert text.startswith(HEADER + "\n")
        assert text.endswith("\n" + ex.EXPRESSION_FOOTER)
        assert f"- Мат: {ex.PROFANITY_INSTRUCTIONS[mode]}" in text.splitlines()


# ═══ 3. Лестница и кастом владельца ════════════════════════════════════════

def test_ladder_prev_is_current_prod_text_and_next_is_factory():
    step = ex.expression_text_ladder()[0]
    assert step["mode"] == "frequent"
    assert step["prev_sha12"] == ex.sha12(ex.PREV_PROFANITY_FREQUENT_TEXT)
    assert step["next_sha12"] == ex.sha12(
        ex.PROFANITY_INSTRUCTIONS["frequent"])
    assert step["prev_sha12"] != step["next_sha12"]
    # PREV — ровно текущий прод-текст 23.10 (evidence/raw)
    assert ex.PREV_PROFANITY_FREQUENT_TEXT == (
        "Пиши на живом разговорном языке с выраженным использованием мата. "
        "Нецензурная лексика — привычная часть твоего словаря: оценки, "
        "междометия, усиления и разговорные связки. Не заменяй её цензурными "
        "эвфемизмами.")
    assert ex.rollback_profanity_frequent_text() == \
        ex.PREV_PROFANITY_FREQUENT_TEXT


def test_ladder_is_idempotent_and_revision_stable():
    first = ex.expression_text_ladder()
    second = ex.expression_text_ladder()
    assert first == second
    assert first[0]["revision"] == ex.EXPRESSION_TEXT_REVISION
    assert ex.sha12(ex.PROFANITY_INSTRUCTIONS["frequent"]).startswith(
        first[0]["next_sha12"])


def test_owner_custom_mode_and_note_are_not_overwritten():
    """Смена текста не трогает документ владельца (режим/пожелание целы)."""
    chat_doc = {"profanity": "frequent",
                "note": "авторская манера: сухо и по делу"}
    settings = ex.build_expression_settings(chat_doc, {"profanity": "off"})
    assert settings.mode == "frequent"
    assert settings.source == "chat"
    # кастом владельца сохраняется в слое отдельной строкой
    layer = ex.render_expression_text(ex.resolve_effective(chat_doc, None))
    assert "Пожелание владельца: авторская манера: сухо и по делу" in layer
    # документ НЕ мутируется нормализацией/резолвом
    assert chat_doc == {"profanity": "frequent",
                        "note": "авторская манера: сухо и по делу"}


# ═══ 4. EX-03: постпроцессор ничего не вставляет/не удаляет ════════════════

def test_no_postprocessor_inserts_or_removes_profanity():
    """Рендер слоя и счётчик — чистые: мат не добавляется и не вырезается."""
    off = ex.render_expression_text(ex.resolve_effective(
        {"profanity": "off"}, None))
    freq = ex.render_expression_text(ex.resolve_effective(
        {"profanity": "frequent"}, None))
    assert ex.count_profanity(off) == 0
    assert ex.count_profanity(freq) == ex.count_profanity(
        ex.PROFANITY_INSTRUCTIONS["frequent"])
    assert off == ex.render_expression_text(ex.resolve_effective(
        {"profanity": "off"}, None))
    assert freq == ex.render_expression_text(ex.resolve_effective(
        {"profanity": "frequent"}, None))
    raw = "Ну и хуй с ним, поехали дальше."
    assert ex.count_profanity(raw) > 0
    # classify не правит текст и не вставляет мат — только класс
    assert ex.classify_expression_response(raw, "frequent") == ""
    assert ex.classify_expression_response("всё спокойно", "frequent") == ""
    assert raw == "Ну и хуй с ним, поехали дальше."
