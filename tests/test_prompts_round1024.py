"""F6 (раунд 10.24, ADR-1024-10) — «Промпты»: плоский grid без аккордеонов,
fallback-предохранитель (`casual`) и табы режимов внутри карточек модулей.

Ключевые контракты, которые доказываем:
  * **Δ каталога = 0:** ключ `prompts.verbilizer_default_mode` сохранён, но
    подпись → «Резервный режим (Fallback)», select-опции не изменены;
  * **fail-safe сбойного пути:** валидный `response_mode` из Stage-1 НИКОГДА
    не переопределяется fallback-ключом; ключ читается только при пустом/
    невалидном `response_mode`;
  * **UI:** дропдаун один раз (`data-block="prompts-fallback-mode"`), табы
    режимов внутри карточек с Вербализатором (`data-block="prompt-mode-tabs"`),
    аккордеон промптов гейтится флагом `PROMPTS_UI_V2_ENABLED`.
"""
from __future__ import annotations

import pytest

from services import hot_config as hot
from services import param_catalog as pc
from services.prompt_style_blocks import (
    MODE_CASUAL_BLOCK,
    MODE_DEEP_RESEARCH_BLOCK,
    MODE_SERIOUS_BLOCK,
    VERBILIZER_DEFAULT_MODE,
    _resolve_default_mode,
    compose_verbalizer_system,
)

pytestmark = pytest.mark.system2

HTML = open("web/index.html", encoding="utf-8").read()
JS = open("web/app.js", encoding="utf-8").read()
ROUTES = open("web/api/routes.py", encoding="utf-8").read()


class _FakeCache:
    def __init__(self, values=None):
        self._settings = dict(values or {})
        self.pg_available = False

    def get(self, key, default=None):
        return self._settings.get(key, default)

    async def set(self, key, value, category):
        self._settings[key] = value


@pytest.fixture(autouse=True)
def _reset_cache():
    hot.set_config_cache(None)
    yield
    hot.set_config_cache(None)


# ── A. Каталог: ключ сохранён (Δ=0), подпись/дефолт обновлены ────────────────

class TestCatalogFallbackMode:
    def test_key_kept_and_select_contract_unchanged(self):
        spec = pc.get_by_pg_key("prompts.verbilizer_default_mode")
        assert spec is not None
        assert spec.widget == "select"
        assert spec.select_options == ("casual", "serious", "deep_research")
        assert len(spec.select_labels) == 3
        assert spec.code_source == (
            "services.prompt_style_blocks.VERBILIZER_DEFAULT_MODE")

    def test_title_is_fallback(self):
        spec = pc.get_by_pg_key("prompts.verbilizer_default_mode")
        assert "Резервный режим (Fallback)" in spec.title_ru

    def test_code_default_is_casual(self):
        assert VERBILIZER_DEFAULT_MODE == "casual"


# ── B. Fallback-контракт: штатный путь приоритетнее предохранителя ───────────

class TestFallbackContract:
    def test_valid_stage1_mode_wins_over_fallback_key(self):
        """Валидный `response_mode` приоритетен: fallback-ключ НЕ читается.

        Сентинелы на режимных блоках делают плечо однозначным: если бы ключ
        дефолта перехватывал роутинг, в промпте оказался бы DEEP_SENTINEL.
        """
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_casual": "CASUAL_SENTINEL",
            "prompts.verbilizer_mode_deep_research": "DEEP_SENTINEL",
            "prompts.verbilizer_default_mode": "deep_research",
        }))
        composed = compose_verbalizer_system("BASE", "casual")
        assert "CASUAL_SENTINEL" in composed
        assert "DEEP_SENTINEL" not in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_fallback_key_read_only_on_failure_path(self):
        """Пустой `response_mode` → предохранитель из ключа (casual)."""
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "casual",
        }))
        composed = compose_verbalizer_system("BASE", "")
        assert MODE_CASUAL_BLOCK in composed

    def test_fallback_key_uses_configured_mode_on_failure(self):
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_mode_serious": "SERIOUS_SENTINEL",
            "prompts.verbilizer_default_mode": "serious",
        }))
        composed = compose_verbalizer_system("BASE", None)
        assert "SERIOUS_SENTINEL" in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_invalid_fallback_key_falls_back_to_code_default_casual(self):
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "bogus",
        }))
        composed = compose_verbalizer_system("BASE", "wat")
        assert MODE_CASUAL_BLOCK in composed
        assert MODE_SERIOUS_BLOCK not in composed

    def test_valid_deep_research_not_overridden(self):
        """Штатный deep_research из Stage-1 сохраняет и mode-, и канал-блок."""
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "casual",
        }))
        composed = compose_verbalizer_system("BASE", "deep_research", "rich")
        assert MODE_DEEP_RESEARCH_BLOCK in composed
        assert MODE_CASUAL_BLOCK not in composed

    def test_resolve_default_mode_fail_safe(self):
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "deep_research"}))
        assert _resolve_default_mode() == "deep_research"
        hot.set_config_cache(_FakeCache({
            "prompts.verbilizer_default_mode": "  "}))
        assert _resolve_default_mode() == "casual"


# ── C. Kill-switch и UI-маркеры новой раскладки ──────────────────────────────

class TestUiGateAndMarkers:
    def test_flag_delivered_via_me(self):
        from config.settings import settings
        assert bool(settings.PROMPTS_UI_V2_ENABLED) is True
        assert '"PROMPTS_UI_V2_ENABLED"' in ROUTES

    def test_fallback_dropdown_rendered_once(self):
        assert 'data-block="prompts-fallback-mode"' in HTML
        assert "promptDefaultModeItem().title" in HTML
        assert "предохранитель" in HTML

    def test_mode_tabs_live_inside_module_cards(self):
        assert 'data-block="prompt-mode-tabs"' in HTML
        assert "&& sec.id === 'verbalizer' && promptModeItem()" in HTML
        # Табы используют общий selected-режим и сохранение как в 10.23.
        assert "@click=\"selectPromptMode(m.id)\"" in HTML

    def test_prompts_accordion_gated_by_flag(self):
        assert ("v-if=\"!uiFlag('PROMPTS_UI_V2_ENABLED') "
                "&& sec.advanced.length > 0\"") in HTML

    def test_verbilizer_group_card_skipped_in_v2(self):
        assert "grp.id === 'prompts_verbilizer')" in HTML
        assert "!(uiFlag('PROMPTS_UI_V2_ENABLED')" in HTML

    def test_js_flat_items_and_casual_sync(self):
        assert "promptVisibleItems" in JS
        assert "uiFlag('PROMPTS_UI_V2_ENABLED')" in JS
        # Санитайз дефолтного режима → casual (а не serious).
        assert "? value : 'casual';" in JS
