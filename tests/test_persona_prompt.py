"""Раунд 10.14 (F2 persona-storage-core, spec §3.2) — байт-тесты блока.

Фиксируется канон хвоста системного промпта: точные байты `<Persona>`,
опускание пустых секций, формат черт, `_NO_AI_DISCLOSURE_BLOCK` при
`is_aware_ai=false` и полное молчание при флаге OFF.
"""
import pytest

from services import bot_persona as bp


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(bp.hot, "get", lambda key, default=None: True)


def test_canonical_block_bytes():
    persona = bp.BotPersona(name="Костик", biography="дворовый кот",
                            overrides="язвительный", is_aware_ai=True)
    assert bp.build_persona_prompt_block(persona, ["стал циничнее", "шутит"]) == (
        "<Persona>\n"
        "Имя: Костик\n"
        "Биография: дворовый кот\n"
        "Характер: язвительный\n"
        "Черты, которые ты приобрёл: • стал циничнее • шутит\n"
        "</Persona>")


def test_empty_sections_skipped():
    persona = bp.BotPersona(name="Костик", biography="", overrides="",
                            is_aware_ai=True)
    assert bp.build_persona_prompt_block(persona) == (
        "<Persona>\nИмя: Костик\n</Persona>")


def test_nothing_to_render_empty_string():
    assert bp.build_persona_prompt_block(bp.BotPersona()) == ""
    assert bp.build_persona_prompt_block(None) == ""


def test_no_ai_disclosure_appended_after_persona():
    persona = bp.BotPersona(name="Костик", is_aware_ai=False)
    block = bp.build_persona_prompt_block(persona)
    assert block.endswith("</Persona>\n" + bp._NO_AI_DISCLOSURE_BLOCK)
    assert "Ты НЕ раскрываешь" in bp._NO_AI_DISCLOSURE_BLOCK


def test_aware_ai_no_disclosure():
    persona = bp.BotPersona(name="Костик", is_aware_ai=True)
    assert bp._NO_AI_DISCLOSURE_BLOCK not in bp.build_persona_prompt_block(persona)


def test_appended_as_tail():
    system_prompt = "СИСТЕМА"
    persona = bp.BotPersona(name="Костик")
    block = bp.build_persona_prompt_block(persona)
    assert system_prompt + "\n\n" + block == "СИСТЕМА\n\n<Persona>\nИмя: Костик\n</Persona>"


def test_flag_off_returns_empty(monkeypatch):
    monkeypatch.setattr(bp.hot, "get", lambda key, default=None: False)
    persona = bp.BotPersona(name="Костик", biography="биография")
    assert bp.build_persona_prompt_block(persona, ["черта"]) == ""


def test_enabled_param_is_resolved_source_of_truth():
    """H3: резолвнутый per-chat `enabled` управляет блоком и НЕ перебивается
    глобальным hot.get (per-chat OFF → пусто, даже если глобально ON)."""
    persona = bp.BotPersona(name="Костик", biography="биография")
    assert bp.build_persona_prompt_block(persona, enabled=False) == ""
    assert bp.build_persona_prompt_block(persona, enabled=True) == (
        "<Persona>\nИмя: Костик\nБиография: биография\n</Persona>")
