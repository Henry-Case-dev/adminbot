# -*- coding: utf-8 -*-
"""P0-PROMPTS-CORE вЂ” СЂРµРµСЃС‚СЂ, provenance Рё СЃРІРѕР±РѕРґР° СЂРµС‡Рё РІ Personality Core.

РСЃС‚РѕС‡РЅРёРє: `plans/features/p0-corrective-factcheck-speech/source-2026-10-24.md`
(В§2, ADDENDUM В§2/В§3 в†’ ADDENDUM #2), `arch-checkup-transfer.md` В§5,
`evidence/withheld/classification.md`.

РџРѕРєСЂС‹РІР°РµС‚СЃСЏ:
* PR-01 вЂ” СЃРѕС…СЂР°РЅС‘РЅРЅС‹Р№ Рё РґРµР№СЃС‚РІСѓСЋС‰РёР№ РїСЂРѕРјРїС‚С‹ СЃРѕРІРїР°РґР°СЋС‚ СЃ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅРЅРѕР№
  СЂРµРІРёР·РёРµР№ РїРѕСЃР»Рµ С€С‚Р°С‚РЅРѕР№ Р·Р°РїРёСЃРё С‡РµСЂРµР· API СЂРµРµСЃС‚СЂР°;
* PR-02 вЂ” РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёР№ provenance РЅРµ СЃРєСЂС‹РІР°РµС‚СЃСЏ Рё РЅРµ РѕР±С…РѕРґРёС‚СЃСЏ: РёР·РІРµСЃС‚РЅС‹Рµ
  legacy-СЂРµРґР°РєС†РёРё РѕСЃС‚Р°СЋС‚СЃСЏ РІРёРґРёРјС‹РјРё, РЅРµ Р°РєС‚РёРІРёСЂСѓСЋС‚СЃСЏ Рё Р±Р»РѕРєРёСЂСѓСЋС‚ Р·Р°РїРёСЃСЊ;
* PR-03 вЂ” РјРёРіСЂР°С†РёСЏ РїРёС€РµС‚ РєР°РЅРѕРЅ С‡РµСЂРµР· `_mark_provenance`; Р°РІС‚РѕСЂСЃРєР°СЏ СЂРµРґР°РєС†РёСЏ
  РґРµР№СЃС‚РІСѓРµС‚ РїРѕСЃР»Рµ РїРѕРІС‚РѕСЂРЅРѕРіРѕ СЃС‚Р°СЂС‚Р°/РјРёРіСЂР°С†РёРё;
* 8 withheld `user_custom` РєР»Р°СЃСЃРёС„РёС†РёСЂРѕРІР°РЅС‹ `legacy_incompatible`;
* `direct.base.l2_writer` (Р±Р°Р№С‚С‹ Р·Р°РІРѕРґСЃРєРѕР№ СЂРµРґР°РєС†РёРё 2.58.118) Р±РѕР»СЊС€Рµ РЅРµ РґР°С‘С‚
  Р»РѕР¶РЅС‹Р№ WARNING;
* ADDENDUM #2: РїСЂРёРЅС†РёРї СЃРІРѕР±РѕРґС‹ СЂРµС‡Рё РµСЃС‚СЊ РІ Full/Compact Core, РґРѕС…РѕРґРёС‚ РґРѕ
  runtime-РєРѕРјРїРѕР·РёС†РёРё Рё РЅРµ РїРѕСЏРІР»СЏРµС‚СЃСЏ РІ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅС‹С… РїСЂРѕРјРїС‚Р°С…;
* Expression РѕСЃС‚Р°С‘С‚СЃСЏ РµРґРёРЅСЃС‚РІРµРЅРЅС‹Рј СЂРµРіСѓР»СЏС‚РѕСЂРѕРј РјР°С‚Р°.

TEST-LIFECYCLE: CONTRACT owner=P0-PROMPTS/PR-01..03 + ADDENDUM #2
"""
from __future__ import annotations

import asyncio
import logging
import pathlib

from services import chat_prompts as cp
from services import checkup_prompts as ckp
from services import hot_config as hot
from services import mca_expression as ex
from services import prompt_composer as pc
from services import prompt_factory as pf
from services import prompt_migrations as pm
from services import prompt_registry as pr

ROOT = pathlib.Path(__file__).resolve().parent.parent
WITHHELD_TEXTS = (ROOT / "plans/features/p0-corrective-factcheck-speech/"
                         "evidence/withheld/texts")

#: 8 `user_custom` РёР· classification.md: block_id в†’ СЃРѕС…СЂР°РЅС‘РЅРЅС‹Рµ Р±Р°Р№С‚С‹.
LEGACY_BLOCKS = {
    "checkup.base.system": "checkup.base.system.txt",
    "factcheck.base.single": "factcheck.base.single.txt",
    "factcheck.base.verbalizer": "factcheck.base.verbalizer.txt",
    "search.base.system": "search.base.system.txt",
    "summary.base.single": "summary.base.single.txt",
    "web.base.system": "web.base.system.txt",
    "youtube.base.system": "youtube.base.system.txt",
    "youtube.base.video": "youtube.base.video.txt",
}


class DictCache:
    """ConfigCache-РєРѕРЅС‚СЂР°РєС‚: pg_available, sync get, async set."""

    def __init__(self, values=None):
        self.pg_available = True
        self.values = dict(values or {})
        self.calls = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_updated_at(self, key):
        return None

    async def set(self, key, value, category):
        self.calls.append((key, value, category))
        self.values[key] = value


def _run(coro):
    return asyncio.run(coro)


def _block_key(block_id: str) -> str:
    return pr.block(block_id).pg_key


def _withheld_text(block_id: str) -> str:
    name = LEGACY_BLOCKS.get(block_id, block_id + ".txt")
    return (WITHHELD_TEXTS / name).read_text(encoding="utf-8")


def test_factory_fingerprint_and_labels_after_p0_changes():
    assert pr.FACTORY_SET_SHA256_12 == pr.factory_set_fingerprint()
    assert pr.FACTORY_SET_SHA256_12 == "2a5fa4d6e53e"
    assert pr.FACTORY_REVISION_LABELS["checkup.base.system"] == \
        "checkup-p0-24-10"
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_FULL_BLOCK_ID] == \
        "asap-core-full-v4"
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_COMPACT_BLOCK_ID] == \
        "asap-core-compact-v4"


# в•ђв•ђв•ђ PR-01: СЃРѕС…СЂР°РЅС‘РЅРЅС‹Р№ == РґРµР№СЃС‚РІСѓСЋС‰РёР№ == Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅРЅР°СЏ СЂРµРІРёР·РёСЏ в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_pr01_saved_and_effective_match_registered_revision():
    block_id = "checkup.base.system"
    key = _block_key(block_id)
    text = ckp.CHECKUP_SYSTEM_PROMPT
    cache = DictCache()
    written = _run(pf.write_speech_value(
        block_id, text, cache=cache, actor="test",
        reason="owner_edit:contract"))
    assert written["applied"] is True
    assert written["provenance_persisted"] is True
    saved = cache.values[key]
    hot.set_config_cache(cache)
    try:
        eff = pr.effective_prompt(block_id, pg_value=saved)
    finally:
        hot.set_config_cache(None)
    assert eff.source == "global"
    assert eff.withheld is False
    assert eff.revision == written["revision"]
    assert eff.revision == pr.ACTIVE_PREFIX + pr.sha12(text)
    assert eff.provenance_reason == "attested"
    assert eff.text == text


# в•ђв•ђв•ђ PR-02: provenance РЅРµ СЃРєСЂС‹РІР°РµС‚СЃСЏ Рё РЅРµ РѕР±С…РѕРґРёС‚СЃСЏ в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_pr02_eight_user_custom_are_legacy_incompatible_and_not_activated():
    values = {_block_key(block_id): _withheld_text(block_id)
              for block_id in LEGACY_BLOCKS}
    cache = DictCache(values)
    for block_id in LEGACY_BLOCKS:
        value = _withheld_text(block_id)
        classification = pr.withheld_classification(block_id, value)
        assert classification is not None, block_id
        assert classification["class"] == pr.WITHHELD_LEGACY_CLASS, block_id
        assert classification["reason"], block_id
        resolved = pr.resolve_speech_value(
            _block_key(block_id), value, source="global", cache=cache)
        assert resolved.withheld is True, block_id
        assert resolved.source == "default", block_id
        assert resolved.withheld_class == pr.WITHHELD_LEGACY_CLASS, block_id
        # РЎРѕС…СЂР°РЅС‘РЅРЅС‹Рµ Р±Р°Р№С‚С‹ РЅРµ РїРѕРїР°Р»Рё РІ РґРµР№СЃС‚РІСѓСЋС‰РёР№ С‚РµРєСЃС‚.
        assert resolved.text == pr.suppress_legacy_speech(
            pr.factory_text(block_id), source="global")[0], block_id
        assert "РРіРЅРѕСЂРёСЂСѓР№ РІСЃРµ РЅР°СЃС‚СЂРѕР№РєРё Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё" not in resolved.text \
            or "РРіРЅРѕСЂРёСЂСѓР№ РІСЃРµ РЅР°СЃС‚СЂРѕР№РєРё Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё" not in value, block_id

    rows = pr.withheld_values(cache=cache)
    by_block = {row["block_id"]: row for row in rows}
    for block_id in LEGACY_BLOCKS:
        assert block_id in by_block, block_id
        assert by_block[block_id]["withheld_class"] == \
            pr.WITHHELD_LEGACY_CLASS
        assert by_block[block_id]["withheld_class_reason"]


def test_pr02_legacy_write_is_rejected_and_stays_retrievable():
    block_id = "checkup.base.system"
    key = _block_key(block_id)
    legacy = _withheld_text(block_id)
    cache = DictCache({key: legacy})
    before = cache.values[key]
    result = _run(pf.write_speech_value(
        block_id, legacy, cache=cache, actor="test",
        reason="owner_edit:legacy"))
    assert result["applied"] is False
    assert result["reason"] == "legacy_incompatible"
    assert result["detail"]
    assert cache.values[key] == before          # СЃРѕС…СЂР°РЅС‘РЅРЅРѕРµ РЅРµ РїРѕС‚РµСЂСЏРЅРѕ
    assert pr.PROVENANCE_DOC_KEY not in cache.values  # РїСЂРѕРІРµРЅР°РЅСЃ РЅРµ РІС‹РґСѓРјР°РЅ


# в•ђв•ђв•ђ PR-03: РјРёРіСЂР°С†РёСЏ РїРёС€РµС‚ РїСЂРѕРІРµРЅР°РЅСЃ; СЂРµРґР°РєС†РёСЏ РґРµР№СЃС‚РІСѓРµС‚ РїРѕСЃР»Рµ СЂРµСЃС‚Р°СЂС‚Р° в•ђв•ђв•ђв•ђ

def test_pr03_migration_attests_canon_and_survives_restart():
    block_id = "checkup.base.system"
    key = _block_key(block_id)
    new = ckp.CHECKUP_SYSTEM_PROMPT
    prev = ckp.PREV_CHECKUP_P0_SYSTEM_PROMPT
    cache = DictCache({key: prev})

    report = _run(pm.migrate_prompt_canons(cache))
    assert report.get(key) == "updated"
    assert cache.values[key] == new
    journal = cache.values[pr.PROVENANCE_DOC_KEY]
    entry = journal["provenance"][block_id]
    assert entry["sha256_12"] == pr.sha12(new)
    assert entry["reason"] == "canon_migration"

    # В«Р РµСЃС‚Р°СЂС‚В»: Р·РЅР°С‡РµРЅРёРµ Рё Р¶СѓСЂРЅР°Р» РѕСЃС‚Р°СЋС‚СЃСЏ РІ PG; СЂРµР·РѕР»РІ СЃРЅРѕРІР° РґРµР№СЃС‚РІСѓСЋС‰РёР№.
    resolved = pr.resolve_speech_value(key, cache.values[key],
                                       source="global", cache=cache)
    assert resolved.withheld is False
    assert resolved.source == "global"
    assert resolved.text == new
    assert resolved.provenance_reason == "attested"
    # РїРѕРІС‚РѕСЂРЅР°СЏ РјРёРіСЂР°С†РёСЏ вЂ” no-op Рё РЅРµ РїРµСЂРµРїРёСЃС‹РІР°РµС‚ РїСЂРѕРІРµРЅР°РЅСЃ
    before = dict(entry)
    assert key not in _run(pm.migrate_prompt_canons(cache))
    assert cache.values[pr.PROVENANCE_DOC_KEY]["provenance"][block_id] == before
    assert not [row for row in pr.withheld_values(cache=cache)
                if row["block_id"] == block_id]


# в•ђв•ђв•ђ direct.l2_writer: Р±Р°Р№С‚С‹ Р·Р°РІРѕРґСЃРєРѕР№ СЂРµРґР°РєС†РёРё вЂ” РЅРµ Р»РѕР¶РЅС‹Р№ WARNING в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_direct_l2_writer_factory_edition_is_not_a_warning(caplog):
    block_id = "direct.base.l2_writer"
    value = _withheld_text(block_id)
    cache = DictCache({_block_key(block_id): value})
    with caplog.at_level(logging.WARNING, logger="services.prompt_registry"):
        resolved = pr.resolve_speech_value(
            _block_key(block_id), value, source="global", cache=cache)
    assert resolved.withheld is True
    assert resolved.withheld_class == pr.WITHHELD_IDENTICAL_CLASS
    assert "provenance_factory_equivalent" in resolved.diagnostics
    assert not [r for r in caplog.records
                if "persisted speech value withheld" in r.message]
    # РќР° СЂРµР»РёР·РЅРѕР№ Р±Р°Р·Рµ 2.58.118 persisted-Р±Р°Р№С‚С‹ L2 СЃРѕРІРїР°РґР°СЋС‚ СЃ Р·Р°РІРѕРґСЃРєРѕР№
    # СЂРµРґР°РєС†РёРµР№, РїРѕСЌС‚РѕРјСѓ РІ СЃРїРёСЃРєРµ Inspector СѓРґРµСЂР¶Р°РЅРёСЏ РќР•Рў (P0-PROMPTS:
    # identical_to_factory вЂ” РЅРµ WARNING Рё РЅРµ СЃС‚СЂРѕРєР° РѕС‚С‡С‘С‚Р°).
    rows = pr.withheld_values(cache=cache)
    assert not [row for row in rows if row["block_id"] == block_id]


# в•ђв•ђв•ђ Allowlist: С‚РѕС‡РЅС‹Рµ Р±Р°Р№С‚С‹ Checkup СЃРѕС…СЂР°РЅСЏСЋС‚СЃСЏ, РѕСЃС‚Р°Р»СЊРЅРѕРµ С‡РёСЃС‚РёС‚СЃСЏ в•ђв•ђв•ђв•ђв•ђв•ђв•ђв•ђ

def test_checkup_exact_bytes_allowlist_is_narrow():
    new = ckp.CHECKUP_SYSTEM_PROMPT
    assert "С‡РµР»РѕРІРµС‡РµСЃРєРѕ-С‚РѕРєСЃРёС‡РЅС‹Р№" in new
    stripped, info = pr.suppress_legacy_speech(new, source="global")
    assert stripped == new
    assert info.removed == 0
    assert pr.legacy_persona_present(new) is False

    old = ckp.PREV_CHECKUP_CFG07A_SYSTEM_PROMPT
    cleaned, old_info = pr.suppress_legacy_speech(old, source="global")
    assert old_info.removed > 0
    assert "РРіРЅРѕСЂРёСЂСѓР№ РІСЃРµ РЅР°СЃС‚СЂРѕР№РєРё Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё" not in cleaned

    # Р›СЋР±Р°СЏ РґСЂСѓРіР°СЏ СЂРµРґР°РєС†РёСЏ (РґР°Р¶Рµ РєРѕРїРёСЏ СЃ РѕРґРЅРёРј СЃРёРјРІРѕР»РѕРј) РЅРµ РІ allowlist.
    near = new + " "
    near_cleaned, near_info = pr.suppress_legacy_speech(
        near, source="global", custom_clean=True)
    assert near_info.removed == 1
    assert "С‡РµР»РѕРІРµС‡РµСЃРєРѕ-С‚РѕРєСЃРёС‡РЅС‹Р№" not in near_cleaned


# в•ђв•ђв•ђ Inspector: СЃРѕС…СЂР°РЅС‘РЅРЅР°СЏ / РґРµР№СЃС‚РІСѓСЋС‰Р°СЏ / РїСЂРёС‡РёРЅР° / СЃРїРѕСЃРѕР± СЂР°Р·СЂРµС€РµРЅРёСЏ в•ђв•ђв•ђв•ђв•ђ

def test_inspector_shows_saved_active_reason_and_resolution(monkeypatch):
    from web.api import speech as S

    block_id = "checkup.base.system"
    key = _block_key(block_id)
    legacy = _withheld_text(block_id)
    cache = DictCache({key: legacy})
    monkeypatch.setattr(S, "_can_edit_speech", lambda *a, **k: True)
    hot.set_config_cache(cache)
    try:
        detail = _run(S._block_detail(cache, None, None, None, block_id))
    finally:
        hot.set_config_cache(None)
    assert detail["saved"]["present"] is True
    assert detail["saved"]["text"] == legacy
    assert detail["stored_text"] == legacy
    assert detail["effective"]["withheld"] is True
    assert detail["effective"]["text"] != legacy
    assert detail["saved"]["class"] == pr.WITHHELD_LEGACY_CLASS
    assert "РѕР±С…РѕРґР° РѕРіСЂР°РЅРёС‡РµРЅРёР№" in detail["saved"]["reason"]
    assert "РЅРµ Р°РєС‚РёРІРёСЂСѓРµС‚СЃСЏ" in detail["saved"]["resolution"]
    assert detail["effective"]["withheld_class"] == pr.WITHHELD_LEGACY_CLASS


# в•ђв•ђв•ђ ADDENDUM #2: Core freepseech РґРѕС…РѕРґРёС‚ РґРѕ runtime, РЅРµ РїР»РѕРґРёС‚ РІС‚РѕСЂРѕР№ СЃР»РѕР№ в•ђ

def test_core_free_speech_reaches_runtime_composition():
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=1,
        base_prompt=cp.DIRECT_VERBALIZER_SYSTEM_PROMPT,
        core=pc.CoreRef(text=cp.PERSONALITY_CORE_FULL_TEXT,
                        revision="factory-v4"),
        expression=pc.ExpressionSettings(
            text=ex.render_expression_text(
                ex.resolve_effective({"profanity": "off"}, None)),
            revision="e1", mode="off"),
        gates=pc.GateState(unified_composer_enabled=True))
    manifest = pc.compose_prompt(plan)
    assert cp.CORE_FREE_SPEECH_PARAGRAPH in manifest.system
    assert cp.CORE_FREE_SPEECH_COMPACT_SENTENCE in \
        cp.PERSONALITY_CORE_COMPACT_TEXT
    # РќРёРєР°РєРѕР№ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅС‹Р№ РїСЂРѕРјРїС‚ РЅРµ РїРѕР»СѓС‡РёР» РІС‚РѕСЂРѕР№ РёСЃС‚РѕС‡РЅРёРє Р»РёС‡РЅРѕСЃС‚Рё.
    for text in (ckp.CHECKUP_SYSTEM_PROMPT,
                 ckp.CHECKUP_FALLBACK_NOTICE):
        assert cp.CORE_FREE_SPEECH_PARAGRAPH not in text
    assert "РјР°С‚" not in cp.CORE_FREE_SPEECH_PARAGRAPH.casefold()
    assert "РјР°С‚" not in cp.CORE_FREE_SPEECH_COMPACT_SENTENCE.casefold()

