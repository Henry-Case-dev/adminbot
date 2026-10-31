"""EVOL-026..030 (W10) — структурные контракты секционных экранов.

Покрытие (plans/current_task.md):
  * EVOL-026 (L357–373): «Активность по часам» и «Живая лента досье» — в
    «Статусе»; полный виджет «Истории памяти» — в «Аналитике»; превью с
    «Показать всё»; один экземпляр каждого виджета, без битых маршрутов.
  * EVOL-027 (L375–389 + v0.7/v0.8): глобальный тумблер ПРЯМО в карточке
    каталога (немедленная серверная операция, per_chat:false), отдельный
    per-chat override, отсутствие тяжёлой KPI-строки, отсутствие второго
    master-toggle в деталях модуля, честное «enabled ≠ healthy».
  * EVOL-028 (L391–402): «ИИ» — рабочая панель; личность переехала в
    «Речь и характер» (единственный канонический редактор), `#/ai/persona`
    остаётся deep-link'ом; «Умный кэш» не в навигации.
  * EVOL-029 (L404–412): «Память» — читаемый каталог знаний: поиск, типы по
    реальной модели, карточка сущности, «Диагностика / расширенный режим».
  * EVOL-030 (L414–422): «Доступы» — сводка + разделы; матрица прав на mobile
    «сущность → права → эффективные роли»; метаданные фильтров в «Аналитике».

Тесты структурные (разметка/поведение-store) и НЕ дублируют живые прогоны
`tools/ui_evol_w10_sections_e2e.py` (Playwright, скриншоты обоих размеров).
"""
from pathlib import Path

import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# ═══ EVOL-026: разделение «Статус» ↔ «Аналитика» ═══════════════════════════

class TestEvol026Widgets:
    def test_heatmap_lives_in_status(self):
        status = _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")
        assert status.count("data-viz-heatmap") == 1
        assert "vizHeatPick(c)" in status
        assert "data-viz-heat-picked" in status
        assert "vizHeatTzLabel()" in status
        assert "data-viz-heat-legend" in status
        # ровно один экземпляр на весь документ (нет дубля в «Аналитике»)
        assert INDEX.count("data-viz-heatmap") == 1

    def test_dossier_feed_lives_in_status(self):
        status = _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")
        assert "data-status-dossier" in status
        assert "dossier-ticker--y" in status
        assert "openFeedDossier(it)" in status
        assert "dossierFeedStamp()" in status
        assert INDEX.count("data-status-dossier") == 1

    def test_full_stories_widget_in_analytics(self):
        oversight = _block(INDEX, "activeTab === 'oversight'",
                           "activeTab === 'relations'")
        assert oversight.count("data-stories-feed") == 1
        assert "data-stories-analytics" in oversight
        assert "storiesFeedFiltered()" in oversight
        assert "data-stories-recovery-toggle" in oversight
        # причина невосстановления объясняется реальными данными
        assert "episodeRecovery.by_reason" in oversight

    def test_status_keeps_bounded_preview(self):
        status = _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")
        assert "data-stories-preview" in status
        assert "data-stories-show-all" in status
        assert "openStoriesAnalytics()" in status
        # полной ленты в «Статусе» нет
        assert "data-stories-feed" not in status

    def test_heatmap_keyboard_and_honest_states(self):
        for marker in ("vizHeatStep(1, 0)", "vizHeatStep(-1, 0)",
                       "vizHeatStep(0, 1)", "@keydown.space.prevent"):
            assert marker in INDEX, marker
        block = _block(APP_JS, "vizHeatPick: function", "vizHeatOpenEvents:")
        assert "this.vizHeatSel = {" in block
        # нет фиктивных нулей: пустое окно объясняется причиной
        assert "empty_reason" in INDEX

    def test_no_fake_updating_label(self):
        assert "dossierFeedStamp: function" in APP_JS
        block = _block(APP_JS, "dossierFeedStamp: function",
                       "vizHeatTzLabel: function")
        assert "обновляется" not in block
        assert "данные от " in block


# ═══ EVOL-027: каталог модулей ═════════════════════════════════════════════

class TestEvol027Catalog:
    def _catalog(self) -> str:
        return _block(INDEX, "activeTab === 'modules'", "activeTab === 'oversight'")

    def test_no_kpi_row_and_caption_present(self):
        cat = self._catalog()
        assert "module-counters" not in cat
        assert "module-counter" not in cat
        assert "data-module-caption" in cat
        assert "filteredModules.length" in cat

    def test_global_master_toggle_on_card(self):
        cat = self._catalog()
        assert "data-module-global-toggle" in cat
        assert "setModuleGlobalState(m, $event.target.checked)" in cat
        assert ":aria-label=\"moduleGlobalToggleLabel(m)\"" in cat
        # подпись области действия явная, рядом с тумблером
        assert "Глобально" in cat
        # чатовый override — отдельная, подписанная строка
        assert "data-module-chat-toggle" in cat
        assert "В этом чате" in cat

    def test_global_write_is_its_own_path(self):
        block = _block(APP_JS, "setModuleGlobalState: async function",
                       "moduleHealthView: function")
        assert "per_chat: false" in block
        assert "this.persistItems(" in block
        assert "moduleGlobalPending" in block
        assert "moduleGlobalOptimistic" in block
        # откат/ошибка и повторная защита от гонок
        assert "skipped: true" in block
        assert "Не удалось изменить глобально" in block

    def test_no_duplicate_master_toggle_in_details(self):
        modal = _block(INDEX, "Окно параметров модуля", "activeModuleGroups")
        assert "data-module-readonly-status" in modal
        assert "data-module-managed-hint" in modal
        assert "toggleModule(activeModule" not in modal
        assert "type=\"checkbox\"" not in modal
        ws = _block(INDEX, "data-workspace-head", "data-workspace-tabs")
        assert "toggleModule(workspaceModule" not in ws
        assert "data-module-managed-link" in ws

    def test_health_is_separate_from_enabled(self):
        assert "moduleHealthView: function" in APP_JS
        for marker in ("moduleHealthLine: function",
                       "moduleLastEventLine: function",
                       "moduleEffectiveLine: function"):
            assert marker in APP_JS, marker
        cat = self._catalog()
        assert "moduleHealthView(m)" in cat
        # «включено ≠ работает»: подпись здоровья отдельная
        assert "module-health" in cat


# ═══ EVOL-028: «ИИ» — рабочая панель и единый редактор личности ════════════

class TestEvol028AiHub:
    def test_working_panel_markup(self):
        assert "aiHubPanel: function" in APP_JS
        assert "data-ai-hub" in INDEX
        assert "data-ai-models" in INDEX
        assert "data-ai-speech" in INDEX
        assert "data-ai-names" in INDEX
        assert "data-ai-prompts" in INDEX
        assert "data-ai-persona-link" in INDEX

    def test_connection_vs_function_distinguished(self):
        block = _block(INDEX, "data-ai-models", "data-ai-speech")
        assert "проверка соединения" in block
        assert "не проверка работы функции" in block
        assert "aiModelGroups()" in block
        assert "healthBadge" in block or "healthText" in block

    def test_persona_moved_into_speech_editor(self):
        speech = _block(INDEX, "activeTab === 'speech'", "activeTab === 'info'")
        assert 'id="speech-persona"' in speech
        for marker in ("personaDraft.name", "personaDraft.biography",
                       "personaDraft.system_prompt_overrides",
                       "personaDraft.is_aware_ai", "savePersona()",
                       "resetPersona()"):
            assert marker in speech, marker
        # второго экрана/дубля нет
        assert "activeTab === 'persona'" not in INDEX

    def test_persona_route_is_deeplink(self):
        route_map = _block(APP_JS, "var ROUTE_TO_TAB = {", "};")
        assert "'#/ai/persona': 'speech'," in route_map
        parent = _block(APP_JS, "var ROUTE_PARENT = {", "};")
        assert "'#/ai/persona': '#/ai'," in parent
        assert "speech: '#/ai/speech'," in _block(
            APP_JS, "var TAB_TO_ROUTE = {", "};")

    def test_smart_cache_not_in_navigation(self):
        hub = _block(APP_JS, "var HUBS_V2 = {", "'#/memory': {")
        assert "Умный кэш" not in hub
        assert "smart-cache" not in hub
        # и на панели нет управляющих настроек кеша ответов
        panel = _block(INDEX, "data-ai-hub", "data-memory-catalog")
        assert "выведен из эксплуатации" in panel


# ═══ EVOL-029: «Память» — читаемый каталог знаний ══════════════════════════

class TestEvol029MemoryCatalog:
    def test_catalog_markup(self):
        assert "memoryHubPanel: function" in APP_JS
        assert "data-memory-catalog" in INDEX
        assert "data-memory-search" in INDEX
        assert "data-memory-list" in INDEX
        assert "data-memory-diagnostics" in INDEX

    def test_knowledge_types_follow_real_model(self):
        block = _block(APP_JS, "memoryCatalogTypes: function",
                       "memoryCatalogItems: function")
        for label in ("Факты", "Люди", "Связи", "Контекст", "Эпизоды"):
            assert label in block, label

    def test_items_use_real_sources_only(self):
        block = _block(APP_JS, "memoryCatalogItems: function",
                       "memoryCatalogFiltered: function")
        assert "this.factsFeed" in block           # записи досье
        assert "this.chatRelations" in block       # участники чата
        assert "this.cognitionGraphData" in block  # рёбра графа
        assert "this.cognitionBeliefs" in block    # убеждения
        assert "episodeFeedView" in block          # эпизоды
        # человеческое представление первично
        assert "status:" in block and "meta:" in block

    def test_detail_opens_existing_record_and_technical_is_separate(self):
        block = _block(APP_JS, "openMemoryCatalogItem: function",
                       "memoryCatalogIsOpen: function")
        assert "this.openStatusRecord(" in block
        assert "this.openEpisodeCard(" in block
        tech = _block(INDEX, "data-memory-diagnostics", "</details>")
        assert "Диагностика / расширенный режим" in tech
        assert "memorySearchAvailability()" in tech

    def test_no_fake_past(self):
        block = _block(INDEX, "data-memory-catalog", "</template>")
        assert "придумывать" not in block.lower()
        # отсутствие данных — честная причина, а не выдуманный сюжет
        # (текст причины формируется в app.js рядом с источником данных)
        src = _block(APP_JS, "memoryCatalogItems: function",
                     "memoryCatalogFiltered: function")
        assert "не восстановлено" in src
        assert "когда: неизвестно" in src


# ═══ EVOL-030: «Доступы», матрица, аналитика ═══════════════════════════════

class TestEvol030AccessAndAnalytics:
    def test_hub_summary_and_sections(self):
        assert "accessHubPanel: function" in APP_JS
        assert "data-access-summary" in INDEX
        assert "data-access-section=\"matrix\"" in INDEX
        assert "data-access-section=\"admins\"" in INDEX
        assert "data-access-section=\"roles\"" in INDEX
        for label in ("Матрица прав", "Администраторы чата",
                      "Роли и пользователи"):
            assert label in INDEX, label
        # тяжёлые плитки-витрины убраны
        hub = _block(INDEX, "accessHubPanel", "</template>")
        assert "hub-card" not in hub

    def test_matrix_mobile_effective_roles(self):
        assert "matrixEffectiveRoles: function" in APP_JS
        assert "data-matrix-effective" in INDEX
        assert ".matrix-perm-summary" in CSS
        # на узком экране сводка ролей видима, таблица не превращается в кашу
        css = _block(CSS, ".matrix-perm-summary {", "/* ── W10-8")
        assert "display: block" in css

    def test_scope_and_audit_before_changes(self):
        block = _block(APP_JS, "accessScopeLabel: function",
                       "oversighRunsFilterLabel: function")
        assert "scopeKind" in block
        assert "accessScopeLabel()" in INDEX
        assert "RBAC" in INDEX
        # права скрыты/запрещены сервером, а не только видом
        assert "Права проверяются на сервере" in INDEX

    def test_analytics_filter_metadata_and_advanced_fields(self):
        assert "data-runs-filter-meta" in INDEX
        assert "oversighRunsFilterLabel()" in INDEX
        # технические поля сохранены (advanced/debug), не удалены
        assert "trace_ids" in INDEX
        assert "reason_code" in INDEX
        assert "pipeline_run_id" in INDEX

    def test_heatmap_deeplink_sets_focus_note(self):
        block = _block(APP_JS, "vizHeatOpenEvents: function",
                       "loadCognition: async function")
        assert "this.oversightFocusNote" in block
        assert "navigateTo('#/oversight?tab=runs')" in block


# ═══ Живой прогон (обязателен при визуальных изменениях) ═══════════════════

def test_live_render_sections_e2e():
    import subprocess
    import sys

    tool = ROOT / "tools" / "ui_evol_w10_sections_e2e.py"
    assert tool.exists(), "нет сквозного Playwright-прогона W10"
    try:
        import playwright  # noqa: F401
    except Exception:  # noqa: BLE001
        import pytest

        pytest.skip("playwright не установлен в этом окружении")
    res = subprocess.run([sys.executable, str(tool)], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8",
                         timeout=1800)
    assert res.returncode == 0, (res.stdout or "") + (res.stderr or "")
    assert "EVOL-W10-SECTIONS OK" in (res.stdout or "")
