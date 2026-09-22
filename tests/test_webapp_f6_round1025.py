"""F6 round 10.25 (`memory-analytics-reorg-round1025`, ADR-1025-19) —
статический контроль фронтенда «Аналитика»/«Память» и инвариантов §116.

Не API-тест: контракт `/api/analytics/*` (`web/api/analytics.py`) НЕ меняется
(R16). Проверяем:
  * adapter `web/static/execution_graph.js` существует, CSP-safe (без DOM/внеш-
    них ресурсов), подключён внешним <script> до app.js;
  * два несмешиваемых режима §26 и честные состояния §28;
  * §116: одна система аналитики/визуализации; `backdrop-filter: url(` = 0;
  * read-only `web/api/analytics.py` (эндпоинты не добавлены);
  * `APP_VERSION` 2.58.14 (bump F6).

Δ каталога = 0 и Δ DDL = 0 дополнительно покрыты существующими маркер-тестами
(`tests/test_ia_inventory_round1025.py`, `test_frontend_tab_mapping.py`,
`test_budget_guardrails_round1024.py`).

Автор: @Builder (F6, Step 4).
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_INDEX = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
_APP_JS = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
_CSS = (_ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
_ADAPTER_PATH = _ROOT / "web" / "static" / "execution_graph.js"
_ADAPTER = _ADAPTER_PATH.read_text(encoding="utf-8")
_ANALYTICS = (_ROOT / "web" / "api" / "analytics.py").read_text(encoding="utf-8")
_SETTINGS = (_ROOT / "config" / "settings.py").read_text(encoding="utf-8")


class TestAdapterModule:
    def test_adapter_exists_and_csp_safe(self):
        assert _ADAPTER_PATH.exists(), "adapter ExecutionGraph не создан"
        for lib in ("mermaid", "cytoscape", "d3.min.js", "unpkg.com",
                    "cdn.jsdelivr.net", "http://", "https://"):
            assert lib not in _ADAPTER, f"запрещён внешний ресурс: {lib}"
        # Не вторая визуализация: adapter не рисует DOM.
        assert "createElement" not in _ADAPTER
        assert "innerHTML" not in _ADAPTER

    def test_adapter_loaded_before_app(self):
        idx_adapter = _INDEX.index("/static/execution_graph.js")
        idx_app = _INDEX.index("/web/app.js")
        assert idx_adapter < idx_app, "adapter должен грузиться ДО app.js"
        assert "window.ExecutionGraph" in _ADAPTER or "root.ExecutionGraph" in _ADAPTER

    def test_canonical_execution_node_contract(self):
        # §24/§25/ADR D1: нет выдуманных parent_id/status/токенов.
        assert "status: 'unknown'" in _ADAPTER
        assert "parentIds" in _ADAPTER
        assert "'algorithm'" in _ADAPTER and "'format'" in _ADAPTER \
            and "'publish'" in _ADAPTER, "enum зарезервирован под Эпик 2"
        assert "price_known === true" in _ADAPTER, "цена только при подтверждении"


class TestTwoModes:
    def test_four_modes_present(self):
        for marker in ("setExecMode('latest')", "setExecMode('day')",
                       "setExecMode('week')", "setExecMode('month')"):
            assert marker in _INDEX, f"режим отсутствует: {marker}"

    def test_trace_and_aggregate_branches_are_exclusive(self):
        assert "execIsTrace" in _INDEX and "execIsTrace" in _APP_JS
        assert "execAggregate" in _INDEX and "execAggregate" in _APP_JS
        # Режимы не смешиваются на уровне данных.
        assert "fromTrace" not in _APP_JS or "ExecutionGraph" in _APP_JS


class TestHonestStates:
    def test_no_fake_zero_cost(self):
        assert "fmtCost" in _APP_JS
        assert "'Нет данных'" in _APP_JS, "нет honest-подписи неизвестной цены"
        assert "'Безлимит (∞)'" in _INDEX or "Безлимит (∞)" in _INDEX

    def test_no_fictitious_stages_in_render(self):
        # Фиктивных узлов Эпика 2 из текущих данных нет.
        assert "stageKind" not in _INDEX
        assert "algorithm" not in _INDEX, "algorithm-узел не должен рендериться"


class TestMemorySection:
    def test_five_subgroups_present(self):
        for s in ("Поиск", "Граф знаний", "Хранение", "Ночной синтез",
                  "Отношения"):
            assert f"'{s}'" in _APP_JS, f"подгруппа памяти отсутствует: {s}"

    def test_existing_renders_preserved(self):
        assert "relationsTab()" in _INDEX
        assert "chatLoreTab" in _INDEX
        assert "currentTab.id === 'memory_rag'" in _INDEX

    def test_no_catalog_edit_in_web(self):
        # Δ каталога = 0: web-слой не содержит каталоговых определений.
        assert "GroupSpec(" not in _APP_JS


class TestInvariant116:
    def test_single_analytics_system(self):
        assert _INDEX.count('class="token-flow mb-3"') == 1, \
            "должна быть ровно одна карта вызовов (§116)"
        for lib in ("mermaid", "cytoscape", "d3.min.js", "unpkg.com",
                    "cdn.jsdelivr.net"):
            assert lib not in _INDEX and lib not in _APP_JS

    def test_no_backdrop_filter_url(self):
        assert "backdrop-filter: url(" not in _CSS

    def test_analytics_api_read_only(self):
        # R16: новых эндпоинтов нет — ровно существующие 4 маршрута.
        routes = re.findall(r"@analytics_router\.(get|put|post|delete)\(\"([^\"]+)\"",
                            _ANALYTICS)
        assert len(routes) == 4, f"изменён контракт analytics API: {routes}"
        assert "/analytics/usage/latest" in _ANALYTICS
        assert "/analytics/usage/summary" in _ANALYTICS

    def test_status_preview_present(self):
        assert "Последний вызов" in _INDEX
        assert "execPreview" in _INDEX and "execPreview" in _APP_JS
        assert "loadExecPreview" in _APP_JS


class TestAnalyticsFilters:
    """H2/M-F6S-1/L-F6S-4/L-F6S-5: поиск, статус, сброс, a11y деталей."""

    def test_search_and_status_controls_present(self):
        # H2 §27: поле поиска + select «статус», привязанные к _execFilters.
        assert 'v-model="execFilterQuery"' in _INDEX
        assert 'v-model="execFilterStatus"' in _INDEX
        assert "execStatusOptions" in _APP_JS
        assert "execFilterQuery" in _APP_JS
        # adapter поддерживает строку поиска.
        assert "query" in _ADAPTER and "searchHaystack" in _ADAPTER

    def test_filters_reset_on_mode_change(self):
        # M-F6S-1: смена режима сбрасывает фильтры (нет «утечки» в агрегат).
        assert "if (mode !== this.execMode) this.resetExecFilters();" in _APP_JS

    def test_detail_closes_on_esc_and_backdrop(self):
        # L-F6S-4: aria-modal + подложка + Esc.
        assert 'aria-modal="true"' in _INDEX
        assert "exec-detail-backdrop" in _INDEX and "exec-detail-backdrop" in _CSS
        assert '@click.self="closeExecDetail()"' in _INDEX
        assert "if (this.execDetailOpen) { this.closeExecDetail(); return; }" in _APP_JS

    def test_memory_subgroup_seam_removed(self):
        # L-F6S-5: мёртвый шов удалён; подгруппа сбрасывается при входе.
        assert "card.memorySubgroup" not in _APP_JS
        assert "c.memorySubgroup" not in _INDEX


class TestVersionBump:
    def test_app_version(self):
        m = re.search(r'APP_VERSION = "([\d.]+)"', _SETTINGS)
        assert m and m.group(1) == "2.58.18", m and m.group(1)
