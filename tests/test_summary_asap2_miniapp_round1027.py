"""ASAP-2 round1027 (T-3960, §17 №14–16) — структура секций miniapp.

Проверяет по КАТАЛОГУ (источник истины фронтенда):
  14 Hybrid-настройки — отдельная workspace-вкладка 'hybrid' (группы
     flags_summary_hybrid / models_summary_hybrid / limits_summary_hybrid);
  15 Legacy-настройки — отдельная вкладка 'legacy' (flags_summary_legacy /
     limits_summary_legacy); общие группы — вне обеих;
  16 подпись MAX_SUMMARY_PARTS — ДОСЛОВНО «…только Legacy… Не влияет на
     Hybrid Article» (§13:2445–2449, verbatim);
     + cross-isolation: ни один hybrid-ключ не описан в legacy-группах и
     наоборот (§21 «не смешивать»);
     + JS-витрина: вкладки/маппинг (полный DOM-поведенческий срез —
     tests/js/round1027_asap2_summary_sections_test.js + браузерные
     S1–S7 Reviewer).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services import param_catalog as pc

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

HYBRID_GROUPS = {"flags_summary_hybrid", "models_summary_hybrid",
                 "limits_summary_hybrid"}
LEGACY_GROUPS = {"flags_summary_legacy", "limits_summary_legacy"}

# Верbatim-подпись §13:2445–2449 (spec контракт (j)).
MAX_PARTS_SIGNATURE = ("Максимальное число обычных Telegram-сообщений, на "
                       "которые может быть разбит Legacy Summary. Не влияет "
                       "на Hybrid Article.")


def _group_keys(group_id: str) -> set[str]:
    return {s.pg_key for s in pc.REGISTRY.values() if s.group == group_id}


# ── §17.14 Hybrid-настройки отображаются отдельно ──────────────────────────

def test_t3960_14_hybrid_section_exists_and_complete():
    ids = {g.id for g in pc.GROUPS}
    assert HYBRID_GROUPS <= ids
    for gid in HYBRID_GROUPS:
        assert pc.group_tab(gid) == pc.TAB_MOD_SUMMARY
    # Состав (контракт (j)): enabled + repair + retry; L1/L2 model/base/key;
    # context ×2; режим + targets ×2 + max_chars.
    flags = _group_keys("flags_summary_hybrid")
    assert flags == {"flags.summary_hybrid_l2_enabled",
                     "flags.summary_hybrid_l1_repair_enabled",
                     "flags.summary_hybrid_l1_retry_enabled"}
    models = _group_keys("models_summary_hybrid")
    assert models == {"models.summary_l1_base_url",
                      "models.summary_l1_model_name",
                      "keys.summary_l1_api_key",
                      "models.summary_l2_base_url",
                      "models.summary_l2_model_name",
                      "keys.summary_l2_api_key"}
    limits = _group_keys("limits_summary_hybrid")
    assert limits == {"limits.summary_hybrid_context_tokens",
                      "limits.summary_hybrid_context_chars",
                      "limits.summary_hybrid_response_mode",
                      "limits.summary_hybrid_target_chars",
                      "limits.summary_hybrid_target_paragraphs",
                      "limits.summary_hybrid_max_chars"}
    # секреты api_key — masked (secret=True; PG-only записи ключуются pg_id)
    by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
    for key in ("keys.summary_l1_api_key", "keys.summary_l2_api_key"):
        assert by_pg[key].secret is True


def test_t3960_14b_hybrid_descriptions_human_readable():
    # человеческие русские описания (S2: не пустые)
    for spec in pc.REGISTRY.values():
        if spec.group in HYBRID_GROUPS:
            assert spec.description.strip(), spec.pg_key
            assert spec.title_ru.strip(), spec.pg_key
    retry = pc.REGISTRY["SUMMARY_L1_RETRY_ENABLED"] if (
        "SUMMARY_L1_RETRY_ENABLED" in pc.REGISTRY) else None
    # retry-описание даёт ссылку на LEGACY-секцию (дубль «Fallback to Legacy»
    # запрещён §13:2451–2452)
    spec = next(s for s in pc.REGISTRY.values()
                if s.pg_key == "flags.summary_hybrid_l1_retry_enabled")
    assert "LEGACY SUMMARY FALLBACK" in spec.description
    assert "Полный отказ Hybrid" in spec.description


# ── §17.15 Legacy-настройки отображаются отдельно ──────────────────────────

def test_t3960_15_legacy_section_exists_and_complete():
    ids = {g.id for g in pc.GROUPS}
    assert LEGACY_GROUPS <= ids
    assert pc.group_tab("flags_summary_legacy") == pc.TAB_MOD_SUMMARY
    assert pc.group_tab("limits_summary_legacy") == pc.TAB_MOD_SUMMARY
    assert _group_keys("flags_summary_legacy") == {
        "flags.summary_legacy_fallback_enabled"}
    # Перенос (не дельта) 3 существующих ключей + ретитл «Legacy».
    assert _group_keys("limits_summary_legacy") == {
        "limits.max_summary_parts",
        "limits.summary_max_context_tokens",
        "limits.summary_max_context_chars"}
    spec = next(s for s in pc.REGISTRY.values()
                if s.pg_key == "flags.summary_legacy_fallback_enabled")
    assert "пользователь всё равно получит" in spec.description


def test_t3960_15b_common_groups_outside_sections():
    # Общие ключи саммари (throttle/timezone/chunk_delay/…) — ВНЕ двух секций.
    common = {s.pg_key for s in pc.REGISTRY.values()
              if s.group == "limits_summary"}
    assert common, "нейтральная группа limits_summary должна остаться"
    assert not (common & {"limits.max_summary_parts",
                          "limits.summary_max_context_tokens",
                          "limits.summary_max_context_chars"})
    assert "flags.summary_streaming_enabled" in {
        s.pg_key for s in pc.REGISTRY.values()
        if s.group == "flags_summary"}


# ── §17.16 подпись MAX_SUMMARY_PARTS + cross-isolation ─────────────────────

def test_t3960_16_max_summary_parts_signature_verbatim():
    spec = next(s for s in pc.REGISTRY.values()
                if s.pg_key == "limits.max_summary_parts")
    assert spec.description == MAX_PARTS_SIGNATURE      # verbatim §13:2445–2449
    assert "Не влияет на Hybrid Article" in spec.description
    assert "Legacy" in spec.title_ru
    # backward-compat: env/py-имя не переименовано
    assert spec.env_name == "MAX_SUMMARY_PARTS" or spec.settings_field == \
        "MAX_SUMMARY_PARTS"
    assert spec.category == pc.CATEGORY_LIMITS


def test_t3960_cross_isolation_keys_vs_groups():
    """Ни один hybrid-ключ не описан в legacy-группах и наоборот (§21)."""
    hybrid_keys = _group_keys("flags_summary_hybrid") | _group_keys(
        "models_summary_hybrid") | _group_keys("limits_summary_hybrid")
    legacy_keys = _group_keys("flags_summary_legacy") | _group_keys(
        "limits_summary_legacy")
    assert not (hybrid_keys & legacy_keys)
    # гибридные префиксы не встречаются в legacy-записях (по pg_key)
    for key in legacy_keys:
        assert "summary_hybrid" not in key and "summary_l1" not in key \
            and "summary_l2" not in key
    for key in hybrid_keys:
        assert "legacy" not in key and key != "limits.max_summary_parts" \
            and "summary_max_context" not in key


# ── JS-витрина: вкладки и маппинг (структурный срез; DOM — браузерный S1–S7) ─

def test_t3960_js_workspace_sections():
    assert re.search(
        r"mod_summary: \[[^\]]*'hybrid', 'legacy'[^\]]*\]", APP_JS)
    assert "hybrid: 'HYBRID SUMMARY'" in APP_JS
    assert "legacy: 'LEGACY SUMMARY FALLBACK'" in APP_JS
    for gid in HYBRID_GROUPS | LEGACY_GROUPS:
        assert f"'{gid}'" in APP_JS, gid        # id-маппинг в workspaceGroupTab
    # currentTabGroups: обе вкладки отдают свои generic-группы
    assert re.search(r"wt === 'hybrid'\) return this\._workspaceGroupsFor",
                     APP_JS)
    assert re.search(r"wt === 'legacy'\) return this\._workspaceGroupsFor",
                     APP_JS)


def test_t3960_tab_rules_mod_summary_covers_new_groups():
    """Правило mod_summary правится in-place (TAB_RULES 21 без роста)."""
    assert len(pc.TAB_RULES) == 21
    rules = dict(pc.TAB_RULES)[pc.TAB_MOD_SUMMARY]
    claimed: set[str] = set()
    for _cat, sel in rules:
        claimed |= pc._resolve_tab_groups(_cat, sel)
    assert claimed >= HYBRID_GROUPS | LEGACY_GROUPS
    # прежние общие группы НЕ переехали (нейтральные вне секций остаются);
    # ASAP-2.1 (ADR-1028-1 D1, контракт (i)): группы префильтра удалены —
    # в правиле mod_summary их больше нет, счётчики 481/105/103.
    assert {"limits_summary", "flags_summary",
            "reactions_summary"} <= claimed
    assert "flags_summary_filter" not in claimed
    assert "limits_summary_filter" not in claimed
    assert len(pc._TAB_BY_GROUP) == 103
    assert len(pc.GROUPS) == 105
    assert len(pc.REGISTRY) == 483
