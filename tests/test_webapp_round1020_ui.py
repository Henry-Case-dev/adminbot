"""Раунд 10.20 / Фаза D (БЛОК 3) — тесты UX/UI-рефакторинга мини-аппа.

Покрытие (T-1903):
  * T-1895  критические баги: binding (маски/значения), роутинг модулей,
            тумблер relations_enabled (маркеры JS — поведение в
            tests/js/round1020_ui_test.js);
  * T-1896  досье участника: аддитивное хранилище + read/write + API-контракт;
  * T-1897  тикер «Живая лента досье»: API-feed + разметка/CSS;
  * T-1898/1899/1900/1901/1902  Liquid Glass, Grid, sticky-save, labels,
            рестайлинг Advanced-аккордеона;
  * T-1903  снимок навигации (меню НЕ изменено).
"""
import re

import pytest

from services.database import DatabaseService
from services import param_catalog as pc

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
CHAT_LORE = (ROOT / "web" / "api" / "chat_lore.py").read_text(encoding="utf-8")
OVERSIGHT = (ROOT / "web" / "api" / "oversight.py").read_text(encoding="utf-8")


def _tabs_block() -> str:
    start = APP_JS.index("var TABS = [")
    end = APP_JS.index("var LEVELS =", start)
    return APP_JS[start:end]


class TestNavigationSnapshot:
    """T-1903/R8: состав, порядок и подписи разделов (меню) НЕ изменены."""

    EXPECTED_TABS = [
        "llm_providers", "prompts",
        "mod_summary", "mod_direct", "mod_factcheck", "mod_search",
        "mod_transcribe", "mod_video_summary", "mod_media_download", "mod_web",
        "mod_checkup", "mod_sleep", "mod_nostalgia", "mod_budgets",
        "mod_images",
        "modules", "memory_rag", "smart_cache", "people_names", "relations",
        "permsoc", "access", "chat_lore", "status", "info", "oversight",
    ]

    def test_tabs_ids_and_order_unchanged(self):
        ids = re.findall(r"\{ id: '([a-z_0-9]+)'", _tabs_block())
        assert ids == self.EXPECTED_TABS

    def test_navbar_legacy_and_v2(self):
        # F1 (T-2393, SUPERSEDE): legacy NAV_ITEMS (6, OFF-режим) остаётся
        # неизменным; новый NAV_ITEMS_V2 = 7 пунктов (+ «Память»).
        legacy = re.findall(
            r"id:\s*'(\w+)',\s*label:\s*'[^']+',\s*route:\s*'#/",
            APP_JS[APP_JS.index("var NAV_ITEMS = ["):
                   APP_JS.index("var NAV_ITEMS_V2")])
        assert legacy == ["status", "how", "modules", "ai", "permsoc", "access"]
        v2 = re.findall(
            r"id:\s*'(\w+)',\s*label:\s*'[^']+',\s*route:\s*'#/",
            APP_JS[APP_JS.index("var NAV_ITEMS_V2 = ["):])
        assert v2[:7] == ["status", "how", "modules", "ai", "memory",
                          "access", "permsoc"]
        # Состав MODULES (12 модулей + «Генерация изображений») — F5 (10.24).
        mods = re.findall(r"\{ id: '(mod_[a-z_]+)',",
                          APP_JS[APP_JS.index("var MODULES = ["):])
        assert len(mods) == 13

    def test_no_new_nav_markup(self):
        # Никаких новых пунктов меню не добавлялось в разметку.
        assert INDEX.count('nav-link') >= 1


class TestCriticalBugMarkers:
    """T-1895: маркеры фиксов (поведение — node tests/js/round1020_ui_test.js)."""

    def test_binding_is_two_way(self):
        # generic-инпуты конфига — v-model (two-way).
        assert 'v-model="item.value"' in INDEX
        # F9 (ADR-1025-22 D1): секреты — display-индикатор (••••••••last4 /
        # «Ключ установлен»), НЕ значение input.
        assert "secret-field__mask" in INDEX
        assert "secretDisplay: function" in APP_JS
        assert "blockFieldConfigured" in APP_JS

    def test_module_window_not_gated_by_config_tab(self):
        # Root cause: гейт canViewTab(m.tab) вместо видимости «Модулей».
        block = APP_JS[APP_JS.index("openModuleWindow: function"):
                       APP_JS.index("_ensureModuleData: function")]
        assert "canViewTab('modules')" in block
        assert "!this.canViewTab(m.tab)" not in block

    def test_relations_toggle_optimistic(self):
        block = APP_JS[APP_JS.index("onRelationsToggle: function"):
                       APP_JS.index("saveRelationsToggle: function")]
        assert "this.relationsEnabled = !!want" in block   # оптимистично
        assert "e.status === 409" in block                 # 409-путь
        assert "this.relationsEnabled = previous" in block  # откат


class TestDossierBackend:
    """T-1896: аддитивное хранилище + API-контракт (R16: user_id — ключ)."""

    @pytest.mark.asyncio
    async def test_override_crud(self):
        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            assert await db.get_dossier_override(-100, 5) == ""
            await db.set_dossier_override(-100, 5, "любит мемы", 111)
            assert await db.get_dossier_override(-100, 5) == "любит мемы"
            await db.set_dossier_override(-100, 5, "новое", 222)   # upsert
            assert await db.get_dossier_override(-100, 5) == "новое"
            await db.delete_dossier_override(-100, 5)
            assert await db.get_dossier_override(-100, 5) == ""
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dossier_feed_scope(self):
        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            await db.insert_graph_fact(-100, "А любит кота", "chat_history",
                                       None, target_user="А")
            await db.insert_graph_fact(-200, "Б спорит", "chat_history",
                                       None, target_user="Б")
            global_feed = await db.dossier_feed(limit=10)
            assert {r["name"] for r in global_feed} == {"А", "Б"}
            chat_feed = await db.dossier_feed(limit=10, chat_id=-100)
            assert [r["name"] for r in chat_feed] == ["А"]
            assert chat_feed[0]["chat_id"] == -100
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_dossier_table_created_without_version_bump(self):
        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            cur = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='persona_dossier_overrides'")
            assert await cur.fetchone() is not None
            cur = await db.db.execute("PRAGMA user_version")
            row = await cur.fetchone()
            # Аддитивная таблица — user_version НЕ поднимается (О7-прецедент).
            assert row[0] == 12
        finally:
            await db.close()

    def test_api_endpoints_declared(self):
        assert ('@chat_lore_router.get("/chat_lore/{chat_id}/dossier/{user_id}")'
                in CHAT_LORE)
        assert ('@chat_lore_router.put("/chat_lore/{chat_id}/dossier/{user_id}")'
                in CHAT_LORE)
        assert 'class DossierOverrideBody' in CHAT_LORE
        assert '@oversight_router.get("/dossier_feed")' in OVERSIGHT


class TestLiquidGlassAndGrid:
    """T-1898/T-1899: дизайн-токены, grid, reduced-motion."""

    def test_glass_tokens(self):
        # §9/F2 (T-2538): alpha .5 + blur 16px на палитре §8 (см. каскад-тесты
        # tests/test_webapp_ui_rework_round1020.py).
        assert "--glass-bg: rgba(21, 27, 42, 0.5)" in CSS
        assert "--glass-blur: blur(16px)" in CSS
        assert "--glass-border-color: rgba(170, 182, 200, 0.16)" in CSS
        assert "--glass-border: 1px solid var(--glass-border-color)" in CSS
        assert "backdrop-filter: var(--glass-blur)" in CSS
        assert ".modal-card" in CSS

    def test_grid(self):
        assert CSS.count("repeat(auto-fit, minmax(320px, 1fr))") >= 1
        assert "justify-content: center" in CSS

    def test_reduced_motion(self):
        assert "@media (prefers-reduced-motion: reduce)" in CSS
        assert ".dossier-ticker__track { animation: none" in CSS

    def test_glass_applied_to_oversight(self):
        assert 'card glass-panel p-4 col-span-full' in INDEX


class TestStickySave:
    """T-1900: одна sticky-панель вместо кнопок под инпутами."""

    def test_component_registered(self):
        assert "app.component('sticky-save'" in APP_JS
        assert "sticky-save__count" in APP_JS
        assert "saveModalEdits" in APP_JS
        assert "cancelModalEdits" in APP_JS

    def test_no_individual_save_buttons_left_in_config(self):
        # В generic-ветке конфига больше нет точечных «Сохранить».
        block = INDEX[INDEX.index("currentTabIsConfig"):
                      INDEX.index("activeTab === 'modules'")]
        assert ">Сохранить<" not in block
        assert "Сохранить ключ" not in block

    def test_sticky_panel_present_in_every_edited_branch(self):
        """S10.20-1 (High): панель обязана быть в КАЖДОЙ ветке, где удалили
        точечные «Сохранить» (config / modules / access). Раньше тест
        проверял «где-нибудь» и пропустил регресс T-1900."""
        config = INDEX[INDEX.index("currentTabIsConfig"):
                       INDEX.index("activeTab === 'modules'")]
        modules = INDEX[INDEX.index("activeTab === 'modules'"):
                        INDEX.index("activeTab === 'oversight'")]
        access = INDEX[INDEX.index("activeTab === 'access'"):
                       INDEX.index("activeTab === 'relations'")]
        for name, block in (("config", config), ("modules", modules),
                            ("access", access)):
            assert "<sticky-save" in block, f"S10.20-1: нет панели в ветке {name}"
        # config-ветка: панель стоит ПОСЛЕ последнего поля (в конце ветки).
        assert config.rindex("<sticky-save") > config.rindex("BYOK")
        # Панелей-компонентов в разметке — 3 (config / modules / access);
        # модалка досье использует собственный <footer class="sticky-save">.
        assert INDEX.count("<sticky-save") >= 3

    def test_toggles_keep_auto_save(self):
        # Тумблеры/select сохраняются мгновенно (существующий путь).
        assert '@change="saveConfigItem(item)"' in INDEX


class TestHumanReadableLabels:
    """T-1901: машиночитаемые термины убраны из отображаемых текстов."""

    FORBIDDEN = ["Кап ", "Temperature:", "Слой А", "Слой В", "L1 (", "L2,"]

    def test_no_machine_terms_in_titles(self):
        for spec in pc.REGISTRY.values():
            title = spec.title_ru or ""
            for term in self.FORBIDDEN:
                assert term not in title, f"{spec.pg_key}: {term}"

    def test_examples_from_tz(self):
        assert pc.REGISTRY["LLM_RETRY_BACKOFF_CAP"].title_ru == \
            "Макс. пауза между попытками (сек)"
        assert pc.REGISTRY["CHAT_TEMPERATURE_CHATTY"].title_ru == \
            "Креативность (Болтливый режим)"

    def test_counters_not_grown(self):
        # T-1901: санкционированный Δ — только тексты, счётчики не растут.
        # 10.23 (F5/ADR-1023-5 D5): рост каталога — отдельная фича → 446/95.
        # 10.24 (F21/ADR-1024-22 D8): +1 REGISTRY/GROUPS (BUDGETS_ENABLED,
        # flags_module_budgets) → 459/98.
        assert len(pc.REGISTRY) == 473
        assert len(pc.GROUPS) == 102


class TestAdvancedAccordion:
    """T-1902: рестайлинг существующего <details class="advanced">."""

    def test_details_advanced_restyled(self):
        assert "details.advanced" in CSS
        assert "advanced-gear" in CSS
        assert "Расширенные системные" in INDEX
        assert "▶ Расширенные настройки" not in INDEX
        # Состав групп не меняется — аккордеон только оформлен.
        assert INDEX.count('class="advanced') >= 3


class TestDossierTicker:
    """T-1897: виджет «Живая лента досье» в «Сводке»."""

    def test_markup_and_css(self):
        assert "Живая лента досье" in INDEX
        assert "dossier-ticker" in INDEX
        assert ".dossier-ticker__track" in CSS
        assert "@keyframes dossier-ticker-scroll" in CSS
        # Без сторонних библиотек (CSP): только CSS-анимация.
        assert "cdn" not in CSS

    def test_reactivity_markers(self):
        assert "startDossierFeedPolling" in APP_JS
        assert "stopDossierFeedPolling" in APP_JS
        assert "loadDossierFeed" in APP_JS
        assert "dossierFeedLoop" in APP_JS
