# -*- coding: utf-8 -*-
"""FIX-CORRECTIVE-FOLLOWUP (21.10.2026, В§1-2) вЂ” РёР·РѕР»СЏС†РёСЏ Expression.

РўСЂРµР±РѕРІР°РЅРёРµ РІР»Р°РґРµР»СЊС†Р°: СЂРµРіСѓР»РёСЂРѕРІР°РЅРёРµ РЅРµС†РµРЅР·СѓСЂРЅРѕР№ Р»РµРєСЃРёРєРё РїСЂРёРЅР°РґР»РµР¶РёС‚ РўРћР›Р¬РљРћ
СЃР»РѕСЋ ``<Expression_Settings>``. Personality Core (РїРѕР»РЅР°СЏ/РєРѕРјРїР°РєС‚РЅР°СЏ),
Р°РєС‚РёРІРЅС‹Рµ РєР°РЅРѕРЅС‹ Direct/Checkup/Summary/Factcheck/Search/Youtube/Web, РєР°РЅРѕРЅ
L1-РїР»Р°РЅРµСЂР° Рё РєР°РЅРѕРЅС‹ РЅРѕСЃС‚Р°Р»СЊРіРёРё РќР• СЃРѕРґРµСЂР¶Р°С‚ РёРЅСЃС‚СЂСѓРєС†РёР№ Рѕ РјР°С‚Рµ (СЂР°Р·СЂРµС€РµРЅРёРµ/
Р·Р°РїСЂРµС‚/С‡Р°СЃС‚РѕС‚Р°/СѓРјРµСЃС‚РЅРѕСЃС‚СЊ/РѕР±СЏР·Р°С‚РµР»СЊРЅРѕСЃС‚СЊ). Р—Р°РјРѕСЂРѕР¶РµРЅРЅС‹Рµ PREV/LEGACY-СЃР»РµРїРєРё
(РёСЃС‚РѕС‡РЅРёРєРё Р»РµСЃС‚РЅРёС†С‹ РјРёРіСЂР°С†РёР№) СЃРѕР·РЅР°С‚РµР»СЊРЅРѕ РќР• РїСЂРѕРІРµСЂСЏСЋС‚СЃСЏ вЂ” РѕРЅРё РІРЅРµ
effective-СЃР»РѕСЏ Рё РЅСѓР¶РЅС‹ РґР»СЏ СЂР°СЃРїРѕР·РЅР°РІР°РЅРёСЏ РїСЂРѕРґ-Р·РЅР°С‡РµРЅРёР№.

Р”РёСЂРµРєС‚РёРІС‹ С‚СЂС‘С… СЂРµР¶РёРјРѕРІ Expression Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅС‹ Р±Р°Р№С‚-РІ-Р±Р°Р№С‚
(test_samples_fewshot::test_section2_texts_are_byte_exact).

TEST-LIFECYCLE: CONTRACT owner=FIX-CORRECTIVE-FOLLOWUP/Expression-isolation
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import mca_expression as ex  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from services.chat_prompts import (  # noqa: E402
    CHAT_SYSTEM_PROMPT,
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    PERSONALITY_CORE_COMPACT_TEXT,
    PERSONALITY_CORE_FULL_TEXT,
)
from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT  # noqa: E402
from services.factcheck_prompts import (  # noqa: E402
    FACTCHECK_SYSTEM_PROMPT,)
from services.nostalgia_prompts import (  # noqa: E402
    NOSTALGIA_CORE_CANON,
    NOSTALGIA_PROMPT,
)
from services.search_prompts import SEARCH_SYSTEM_PROMPT  # noqa: E402
from services.summary_prompts import SYSTEM_PROMPT  # noqa: E402
from services.web_prompts import WEBPAGE_SYSTEM_PROMPT  # noqa: E402
from services.youtube_prompts import (  # noqa: E402
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

#: РЎР»РѕРІРµСЃРЅС‹Рµ С„РѕСЂРјС‹ РјР°С‚Р° (РїРѕ РіСЂР°РЅРёС†Рµ СЃР»РѕРІР°: В«С„РѕСЂРјР°С‚РЅС‹Р№В»/В«РјР°С‚РµСЂРёР°Р»В» вЂ” РЅРµС‚).
_MAT_WORD_RE = re.compile(r"\bРјР°С‚(Р°|Сѓ|Рµ|РѕРј|РѕРІ|Р°РјРё|Р°С…)?\b", re.IGNORECASE)

#: РЇРІРЅС‹Рµ РјР°С‚-СЂР°Р·СЂРµС€РµРЅРёСЏ РїСЂРµР¶РЅРёС… РєР°РЅРѕРЅРѕРІ (РЅРµ РґРѕР»Р¶РЅС‹ РІРµСЂРЅСѓС‚СЊСЃСЏ РЅРё РІ РєР°РєРѕРј РІРёРґРµ).
_LEGACY_PERMISSIONS = (
    "Р Р°Р·СЂРµС€РµРЅ РјР°С‚",
    "РјР°С‚ РЅРµ РІСЃС‚Р°РІР»СЏРµС‚СЃСЏ РЅР°СЃРёР»СЊРЅРѕ",
    "Р±РµР· РјР°С‚Р°В» РїРµСЂРµРѕРїСЂРµРґРµР»СЏРµС‚",
)

#: P0-CHECKUP (24.10.2026, addendum В§2): С„СЂР°Р·Р°-СѓРєР°Р·Р°С‚РµР»СЊ СЋСЂРёСЃРґРёРєС†РёРё РІ С†РµР»РµРІРѕРј
#: Р¶Р°РЅСЂРѕРІРѕРј РєР°РЅРѕРЅРµ Checkup вЂ” В«С‡Р°СЃС‚РѕС‚Р° РјР°С‚Р° Рё СЂРµР·РєРѕСЃС‚СЊ вЂ” РёР· ExpressionВ». Р­С‚Рѕ РќР•
#: СЂРµРіСѓР»РёСЂРѕРІР°РЅРёРµ С‡Р°СЃС‚РѕС‚С‹, Р° СЏРІРЅР°СЏ РїРµСЂРµРґР°С‡Р° РїСЂР°РІР° СЃР»РѕСЋ Expression; РїСЂРµР¶РЅРёРµ
#: РјР°С‚-РёРЅСЃС‚СЂСѓРєС†РёРё РєР°РЅРѕРЅР° РїСЂРё СЌС‚РѕРј РѕСЃС‚Р°СЋС‚СЃСЏ Р·Р°РїСЂРµС‰РµРЅС‹ (СЃРј. _LEGACY_PERMISSIONS).
_EXPRESSION_JURISDICTION = "С‡Р°СЃС‚РѕС‚Р° РјР°С‚Р° Рё СЂРµР·РєРѕСЃС‚СЊ вЂ” РёР· Expression"


def _without_expression_jurisdiction(text: str) -> str:
    return str(text or "").replace(_EXPRESSION_JURISDICTION, "")


def _active_speech_canons() -> dict[str, str]:
    """РђРєС‚РёРІРЅС‹Рµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРµ РєР°РЅРѕРЅС‹ (effective-СЃР»РѕР№, РєРѕРґ-РґРµС„РѕР»С‚С‹)."""
    canons: dict[str, str] = {
        "direct_chat": CHAT_SYSTEM_PROMPT,
        "direct_verbalizer": DIRECT_VERBALIZER_SYSTEM_PROMPT,
        "l1_planner": DIRECT_L1_PLANNER_SYSTEM_PROMPT,
        "checkup": CHECKUP_SYSTEM_PROMPT,
        "summary": SYSTEM_PROMPT,
        "factcheck": FACTCHECK_SYSTEM_PROMPT,
        "search": SEARCH_SYSTEM_PROMPT,
        "youtube": YOUTUBE_SYSTEM_PROMPT,
        "youtube_video": YOUTUBE_VIDEO_SYSTEM_PROMPT,
        "webpage": WEBPAGE_SYSTEM_PROMPT,
        "core_full": PERSONALITY_CORE_FULL_TEXT,
        "core_compact": PERSONALITY_CORE_COMPACT_TEXT,
        "nostalgia_prompt": NOSTALGIA_PROMPT,
        "nostalgia_core": NOSTALGIA_CORE_CANON,
        "expression_header": ex.EXPRESSION_HEADER,
    }
    return canons


def test_no_profanity_regulation_outside_expression():
    """Р’ Р°РєС‚РёРІРЅС‹С… РєР°РЅРѕРЅР°С… РЅРµС‚ РЅРё СЃР»РѕРІР° Рѕ РјР°С‚Рµ; РїСЂР°РІРёР»Р° С‡Р°СЃС‚РѕС‚С‹ вЂ” С‚РѕР»СЊРєРѕ
    РґРёСЂРµРєС‚РёРІС‹ Expression (С‚РµРєСЃС‚С‹ СЂРµР¶РёРјРѕРІ РїСЂРѕРІРµСЂРµРЅС‹ РѕС‚РґРµР»СЊРЅРѕ Р±Р°Р№С‚-РІ-Р±Р°Р№С‚)."""
    for name, text in _active_speech_canons().items():
        checked = _without_expression_jurisdiction(text)
        hit = _MAT_WORD_RE.search(checked)
        assert hit is None, f"{name}: РјР°С‚-СЂРµРіСѓР»РёСЂРѕРІР°РЅРёРµ РІРµСЂРЅСѓР»РѕСЃСЊ: {hit.group(0)!r}"
        for legacy in _LEGACY_PERMISSIONS:
            assert legacy not in text, (name, legacy)


def test_expression_is_the_only_profanity_owner():
    """Р•РґРёРЅСЃС‚РІРµРЅРЅС‹Р№ Р»РµРіР°Р»СЊРЅС‹Р№ РЅРѕСЃРёС‚РµР»СЊ С‚РµРјС‹ вЂ” СЃР»РѕР№ Expression."""
    layer = ex.render_expression_text(
        ex.resolve_effective({"profanity": "frequent"}, None))
    assert _MAT_WORD_RE.search(layer) is not None  # РґРёСЂРµРєС‚РёРІР° РЅР° РјРµСЃС‚Рµ
    assert "РњР°С‚:" in layer
    # Р·Р°РІРѕРґСЃРєРёРµ Р·РЅР°С‡РµРЅРёСЏ РѕСЃС‚Р°Р»СЊРЅС‹С… РєРѕРЅС‚СЂРѕР»РѕРІ РЅРµ СѓРїРѕРјРёРЅР°СЋС‚ РјР°С‚
    for control, modes in ex.CONTROL_INSTRUCTIONS.items():
        if control == "profanity":
            continue
        for instruction in modes.values():
            assert _MAT_WORD_RE.search(instruction) is None, control


def test_factory_texts_registered_set_has_no_mat_outside_expression():
    """Р’РµСЃСЊ Р·Р°РІРѕРґСЃРєРѕР№ РЅР°Р±РѕСЂ СЂРµРµСЃС‚СЂР° (factory_texts) С‡РёСЃС‚ РѕС‚ РјР°С‚-СЂРµРіСѓР»РёСЂРѕРІР°РЅРёСЏ.
    РСЃРєР»СЋС‡РµРЅРёСЏ вЂ” РњРђРЁРРќРќР«Р• СЃС‚Р°РґРёРё (СЂРµС‡СЊ РЅРµ РїРёС€СѓС‚; СѓРїРѕРјРёРЅР°РЅРёРµ РјР°С‚Р° вЂ” РіСЂР°РЅРёС†Р°
    СЋСЂРёСЃРґРёРєС†РёРё/РїРѕРєСЂС‹С‚РёСЏ РґР°РЅРЅС‹С…, РЅРµ РёРЅСЃС‚СЂСѓРєС†РёСЏ Рѕ СЂРµС‡Рё):
      * ``memory.extract`` вЂ” JSON-СЌРєСЃС‚СЂР°РєС‚РѕСЂ РєРѕРЅС„Р»РёРєС‚РѕРІ (В«РёР·РІР»РµРєР°Р№ СЃСѓС‚СЊ
        РєРѕРЅС„Р»РёРєС‚РѕРІ РґР°Р¶Рµ РµСЃР»Рё С‚Р°Рј РјР°С‚В» вЂ” РїРѕРєСЂС‹С‚РёРµ РґР°РЅРЅС‹С…, Р° РЅРµ СЂРµС‡СЊ Р±РѕС‚Р°);
      * ``summary.recheck``-СЃРµРјР°РЅС‚РёРєР° Р¶РёРІС‘С‚ РІРЅРµ СЂРµРµСЃС‚СЂР°, РЅРѕ Р°РЅР°Р»РѕРіРёС‡РЅРѕ:
        РІР°Р»РёРґР°С‚РѕСЂСѓ СЃС‚РёР»РµР№ РїСЂРµРґРїРёСЃР°РЅРѕ РќР• Р±СЂР°РєРѕРІР°С‚СЊ РјР°С‚ (СЋСЂРёСЃРґРёРєС†РёСЏ вЂ”
        Expression), СЌС‚Рѕ РЅРµ РјР°С‚-РїСЂР°РІРёР»Рѕ СЂРµС‡Рё.
    Р”РІРѕР№РЅР°СЏ РїСЂРѕРІРµСЂРєР° РѕС‚ В«С‚РёС…РѕРіРѕВ» РІРѕР·РІСЂР°С‚Р° С‚РµРјС‹ РІ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРµ РєР°РЅРѕРЅС‹."""
    allowed_blocks = frozenset({"memory.extract"})
    for block_id, text in pr.factory_texts().items():
        if block_id in allowed_blocks:
            continue
        hit = _MAT_WORD_RE.search(_without_expression_jurisdiction(text))
        assert hit is None, (block_id, hit.group(0) if hit else "")
        for legacy in _LEGACY_PERMISSIONS:
            assert legacy not in text, (block_id, legacy)


def test_fingerprint_constant_matches_recomputed_registry():
    """FACTORY_SET РїРµСЂРµСЃС‡РёС‚Р°РЅ РїРѕСЃР»Рµ РїСЂР°РІРєРё РєР°РЅРѕРЅРѕРІ (Р±Р°РјРїС‹ Р·Р°РґРѕРєСѓРјРµРЅС‚РёСЂРѕРІР°РЅС‹
    РІ prompt_registry: вЂ¦ -> 3507bd6f92eb -> 553a281fe2fd -> fd4e88754749;
    W1-Р±Р°РјРї 22.10.2026: Core full/compact v3 (В§3.2/В§3.3), Direct tool phase
    (В§3.6), Direct L2 writer (В§3.1), L1 В«Р’Р«Р‘РћР  РЈР§РђРЎРўРРЇВ» (В§3.7),
    factcheck-РІРµСЂР±Р°Р»РёР·Р°С‚РѕСЂ Р±РµР· identity вЂ” PREV_*_W1-СЃР»РµРїРєРё + СЃС‚СѓРїРµРЅРё;
    ASAP 2-Р±Р°РјРї 23.10.2026: РєРѕРЅС‚СЂР°РєС‚ СѓС‚РѕС‡РЅРµРЅРёР№ L1 (В§4.1 asap2 source) +
    Р°Р±Р·Р°С†С‹ В§4.2 РІ В«РљРђРљ РџРРЎРђРўР¬В» вЂ” PREV_DIRECT_L1_PLANNER_W1 /
    PREV_CHAT_VERBALIZER_W1_31, changed = 2; R3-Р±Р°РјРї вЂ” СЃРµРєС†РёСЏ СѓС‡Р°СЃС‚РёСЏ
    (PREV_DIRECT_L1_PLANNER_CLAR); R3b-Р±Р°РјРї 23.10.2026: СѓСЃРёР»РµРЅРёРµ
    РїСЂРѕРґРѕР»Р¶РµРЅРёСЏ В§4.1 + РіСЂР°РЅРёС†Р° РёСЃС‚РѕСЂРёРё L2 вЂ” PREV_DIRECT_L1_PLANNER_R3 /
    PREV_CHAT_VERBALIZER_CLAR, changed = 2)."""
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
    assert pr.FACTORY_SET_SHA256_12 == "2a5fa4d6e53e"

