"""P0 SPEECH-SIMPLIFY (25.10.2026) — точные речевые тексты и их доставка.

Доказывает по source-owner-speech-simplify-2026-10-25.md:
* §2.1-2.6, §5 — runtime-тексты совпадают с текстами владельца байт-в-байт;
* одновременно активен ровно один режим мата, текст берётся из конфигурации;
* базовый речевой блок (манера/юмор/длина/достоверность) доходит до system
  L2-payload ровно один раз, без второго слоя и без квот;
* длинные конкурирующие юмористические инструкции удалены;
* §3 — заводской стиль "Завсегдатай Двача" есть в существующем реестре
  пресетов, не активируется сам и не протекает при другом стиле;
* мат не режется детерминированной постобработкой Style Policy.

TEST-LIFECYCLE: CONTRACT owner=SPEECH-SIMPLIFY/§2/§3/§8
"""
from __future__ import annotations

import pytest

from services import mca_expression as ex
from services import mca_humor_craft as humor
from services import prompt_composer as pc
from services import prompt_style_blocks as psb
from services import style_policy as sp

# Точные тексты владельца (source §2.1-2.6, §5) — независимые литералы,
# чтобы тест ловил любое изменение runtime-константы.
BASE_SPEECH = (
    "Говори естественно, как обычный человек в интернет-чате. Отвечай по "
    "существу, без воды и искусственной драматургии. Простому вопросу обычно "
    "достаточно короткого ответа. Если тема требует подробностей - раскрывай "
    "её нормально. Не изображай характер специально, просто разговаривай."
)
HUMOR = (
    "Шути естественно и только когда хочется или ситуация располагает. "
    "Допустимы ирония, сарказм, абсурд и грубоватые приколы. Не вымучивай "
    "шутки, не превращай ответы в стендап, не придумывай истории ради "
    "панчлайна и не объясняй собственный юмор."
)
RESPONSE_LENGTH = (
    "Подбирай длину ответа по ситуации. Иногда достаточно пары слов или "
    "одного предложения. Не пересказывай очевидное, не повторяй мысль и не "
    "растягивай ответ ради выразительности. Если нужен подробный разбор - "
    "отвечай подробно."
)
OFF = (
    "Не используй мат в собственной речи. Цитаты и исходные пользовательские "
    "данные не переписывай ради этого правила."
)
OCCASIONAL = (
    "Матерись иногда, когда это естественно вписывается в разговор. Не "
    "добавляй ругательства специально и не делай их обязательной частью "
    "каждого ответа."
)
FREQUENT = (
    "Матерись часто и непринуждённо, как человек, для которого мат - обычная "
    "часть разговорной речи. Не избегай крепких выражений без причины, но и "
    "не вставляй их механически."
)
FACTUAL = (
    "Не придумывай реальные события, чужие цитаты и подробности прошлого, "
    "выдавая их за факты. Если чего-то не помнишь или не знаешь, не "
    "притворяйся очевидцем. Выдумывать и преувеличивать ради шутки можно, "
    "когда понятно, что это шутка."
)
DVACH = (
    "Говори как старый завсегдатай Двача: прямолинейно, ехидно, неформально, "
    "с привычным имиджбордным сленгом. Можешь подкалывать, троллить, язвить и "
    "использовать чёрный или абсурдный юмор. Не церемонься и не изображай "
    "вежливого консультанта. Обычно говори коротко и по делу. Не форси мемы, "
    "не объясняй шутки и не изображай карикатурного анона."
)
DVACH_DESCRIPTION = (
    "Старый анон с имиджборды. Ехидный, прямолинейный, грубоватый, с "
    "характерным интернет-сленгом, чёрным юмором и привычкой говорить без "
    "церемоний."
)


# ── §2: точные тексты ──────────────────────────────────────────────────────


def test_base_speech_humor_length_factual_are_owner_texts():
    assert ex.BASE_SPEECH_TEXT == BASE_SPEECH
    assert ex.HUMOR_TEXT == HUMOR
    assert ex.RESPONSE_LENGTH_TEXT == RESPONSE_LENGTH
    assert ex.FACTUAL_SPEECH_TEXT == FACTUAL


def test_profanity_modes_are_owner_texts():
    assert ex.PROFANITY_INSTRUCTIONS == {
        "off": OFF, "occasional": OCCASIONAL, "frequent": FREQUENT}
    assert ex.PROFANITY_OFF_TEXT == OFF
    assert ex.PROFANITY_OCCASIONAL_TEXT == OCCASIONAL
    assert ex.PROFANITY_FREQUENT_TEXT == FREQUENT


def test_frequent_has_no_extra_quotas_or_examples():
    """§2.6: никаких процентов, триггеров, категорий и примеров."""
    text = ex.PROFANITY_INSTRUCTIONS["frequent"].casefold()
    for banned in ("%", "пример", "каждом сообщении", "обязательно"):
        assert banned not in text, banned


@pytest.mark.parametrize("mode", ["off", "occasional", "frequent"])
def test_single_mode_renders_its_own_text_only(mode):
    """§2.7: одновременно активен ровно один режим мата."""
    text = ex.render_expression_final_contract(mode)
    assert ex.PROFANITY_INSTRUCTIONS[mode] in text
    others = [m for m in ("off", "occasional", "frequent") if m != mode]
    for other in others:
        assert ex.PROFANITY_INSTRUCTIONS[other] not in text, other


def test_base_speech_block_contains_owner_texts_once():
    block = psb.speech_base_block()
    for text in (BASE_SPEECH, HUMOR, RESPONSE_LENGTH, FACTUAL):
        assert block.count(text) == 1, text
    assert block.startswith(psb.SPEECH_BASE_OPEN)
    assert block.endswith(psb.SPEECH_BASE_CLOSE)


# ── §4: юмор больше не длинный набор обязательных приёмов ────────────────────


def test_humor_craft_texts_are_short_and_not_mandatory():
    for technique in humor.TECHNIQUES:
        text = humor.TECHNIQUE_TEXTS[technique]
        assert len(text) <= 260, (technique, len(text))
        for banned in ("кульминац", "в каждом ответе", "комбинируй",
                       "обязательно"):
            assert banned not in text.casefold(), (technique, banned)
    assert len(humor.HUMOR_CRAFT_GUARD) <= 300
    assert "кульминац" not in humor.HUMOR_CRAFT_GUARD.casefold()


# ── §3: заводской стиль "Завсегдатай Двача" ────────────────────────────────


def test_dvach_preset_registered_in_existing_library():
    spec = sp.PRESET_SPECS["dvach"]
    assert spec["title_ru"] == "Завсегдатай Двача"
    assert spec["description"] == DVACH_DESCRIPTION
    assert spec["soft_instructions"] == [DVACH]
    assert "dvach" in sp.PRESET_NAMES


def test_dvach_is_not_activated_automatically():
    doc = sp.build_document()
    assert "dvach" not in (doc.get("presets_applied") or [])
    assert all("Двача" not in str(row.get("text") or "")
               for row in (doc.get("soft_instructions") or []))


def test_other_style_does_not_leak_dvach_instruction():
    doc = sp.build_document(presets=["casual_concise"])
    texts = [str(row.get("text") or "") for row in doc["soft_instructions"]]
    assert DVACH not in texts
    assert all("Двача" not in t for t in texts)


def test_dvach_does_not_override_profanity_mode():
    """§3: стиль не переопределяет Expression — режим живёт отдельно."""
    doc = sp.build_document(presets=["dvach"])
    assert "character.expression" not in doc
    assert doc["presets_applied"] == ["dvach"]
    # В самом тексте стиля нет разрешения/запрета мата.
    assert "мат" not in DVACH.casefold()


def test_existing_presets_untouched():
    for name in ("regular_chat", "no_quotes", "no_trailing_period",
                 "no_emoji", "casual_concise"):
        assert name in sp.PRESET_SPECS


# ── §8: payload — базовый блок доходит до system ровно один раз ─────────────

BASE = "КАНАЛ: технический контракт."
CORE = "Ты живой участник чата: язвительный, наблюдательный. МАРКЕР_ЯДРА"

PLAN = pc.PromptPlan(
    profile="speech_plain", writer="l2_writer", chat_id=7, channel="plain",
    html_safe=False, base_prompt=BASE, base_source="global",
    core=pc.CoreRef(text=CORE, revision="r1", source="global",
                    document_revision="1"),
    expression=pc.ExpressionSettings(
        text="<Expression_Settings>\n- Мат: " + FREQUENT +
             "\n</Expression_Settings>",
        revision="e1", mode="frequent"),
    gates=pc.GateState(unified_composer_enabled=True),
    user_parts=("вопрос",),
)


def test_payload_has_single_short_speech_block():
    manifest = pc.compose_prompt(PLAN)
    system = manifest.system
    for text in (BASE_SPEECH, HUMOR, RESPONSE_LENGTH, FACTUAL):
        assert system.count(text) == 1, text
    # Core не подменяется и не дублируется речевым блоком.
    assert system.count(CORE) == 1
    # Блок идёт до Expression-настроек: манера не перебивает режим мата.
    assert system.index(BASE_SPEECH) < system.index(FREQUENT)


def test_payload_has_no_stale_long_directives():
    system = pc.compose_prompt(PLAN).system
    for stale in ("развивай её", "доведи его до конкретных последствий",
                  "нарастающий абсурд", "строй историю", "сыпь шутками"):
        assert stale not in system, stale


def test_profanity_survives_style_policy_postprocess():
    """§2.7: мат не режется детерминированной постобработкой."""
    import asyncio

    sample = "Ну это пиздец, конечно. Бля, ну и денёк."
    doc = sp.build_document(rules=[
        {"id": "quotation_marks.hard.no_graphic", "kind": "quotation_marks",
         "strictness": "hard", "params": {"mode": "strip"}, "revision": 1},
        {"id": "trailing_period.hard.strip", "kind": "trailing_period",
         "strictness": "hard", "params": {"ellipsis": "keep"}, "revision": 1},
    ])
    policy = sp.effective_policy_sync(doc, None, context="regular")
    result = asyncio.run(sp.apply_style_policy(
        sample, policy=policy, context="regular", emit_events=False))
    out = getattr(result, "text", None) or getattr(result, "outbound_text", "")
    assert "пиздец" in out and "Бля" in out
