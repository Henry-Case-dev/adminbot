"""F11 round 10.25 — витрина «Статус» (status-showcase-dashboard-round1025).

ADR-1025-23 (D1–D7), ТЗ §11–§21, §70, §77, §117 (п.7–10).

Поведение (сетка/нулевые метрики/сон/граф/факты/счётчики) реально
прогоняется в `tests/js/round1025_f11_status_grid_test.js`
(`F11-STATUS-GRID-OK` / `F11-HEARTBEAT-OK`). Playwright-матрица §70 —
`tools/ui_round1025_matrix.py` (`failures: 0`). Здесь — статические
инварианты: Δ каталога=0, Δ DDL=0, bump, kill-switch, CSP/zero-build,
сохранность виджетов §11.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    return node


def _run_js(script: str, *ok_markers: str):
    node = _node()
    res = subprocess.run(
        [node, os.path.join(*script.split("/"))],
        capture_output=True, text=True, timeout=90, cwd=str(ROOT))
    assert res.returncode == 0, (
        "JS-UNIT не прошёл (%s):\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (script, res.stdout, res.stderr))
    for marker in ok_markers:
        assert marker in res.stdout, "%s отсутствует в %s" % (marker, script)


class TestF11JsBehaviour:
    """Поведенческие JS-маркеры композиции (реальный node, не grep)."""

    def test_status_grid_js(self):
        _run_js("tests/js/round1025_f11_status_grid_test.js",
                "F11-STATUS-GRID-OK", "F11-HEARTBEAT-OK")

    def test_log_counts_js(self):
        # H-F11S-1: реальные счётчики (count > 1), раздельные ERROR/WARNING.
        _run_js("tests/js/round1025_f11_log_counts_test.js",
                "F11-LOG-COUNTS-OK")


class TestD1Grid:
    def test_container_and_spans(self):
        assert 'class="status-grid"' in INDEX
        for span in ("sg-5", "sg-7", "sg-8", "sg-4", "sg-12"):
            assert span in INDEX, span

    def test_css_12_6_1(self):
        assert re.search(
            r"\.status-grid \{[\s\S]{0,240}repeat\(12, minmax\(0, 1fr\)\)",
            CSS)
        assert re.search(
            r"@media \(max-width: 991px\)[\s\S]{0,240}repeat\(6, minmax\(0, 1fr\)\)",
            CSS)
        assert re.search(
            r"@media \(max-width: 767px\)[\s\S]{0,160}minmax\(0, 1fr\)", CSS)
        assert ".status-grid--legacy" in CSS

    def test_main_scroll_area_untouched(self):
        # `main.scroll-area` (auto-fill) не меняется — состав прочих вкладок цел.
        assert 'grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));' \
            in INDEX

    def test_kill_switch_default_on(self):
        assert re.search(
            r'UI_STATUS_GRID_V2: ClassVar\[bool\] = _env_bool\(\s*'
            r'"UI_STATUS_GRID_V2",\s*True\)', SETTINGS)
        assert "statusGridV2: function" in JS
        assert '"UI_STATUS_GRID_V2": bool(settings.UI_STATUS_GRID_V2),' in ROUTES

    def test_dom_order_section12(self):
        order = ["status-hero", 'class="card p-4 status-block"', "status-graph",
                 "status-sleep", "Мониторинг Интеллекта", "exec-preview",
                 "status-facts", "status-budgets", "status-logs"]
        prev = -1
        for marker in order:
            i = INDEX.index(marker)
            assert i > prev, "§12: порядок DOM нарушен на %s" % marker
            prev = i


class TestD2HeroMetrics:
    def test_hero_and_metrics(self):
        assert "status-hero" in INDEX
        assert 'class="card p-4 status-block"' in INDEX
        assert 'class="status-block__grid"' in INDEX
        assert "status-block__pulse" in INDEX
        assert "status-block__bot" in INDEX
        assert "status-block__server" in INDEX

    def test_null_is_not_zero(self):
        assert "statusSys: function" in JS
        # нет `(cpu_percent || 0)` в разметке метрик (0 при null устранён)
        assert "statusData.server.cpu_percent ?? '—'" not in INDEX
        assert "(statusData.server.cpu_percent || 0)" not in INDEX
        assert "нет данных" in INDEX

    def test_server_metrics_note(self):
        assert "Метрики относятся ко всему серверу" in INDEX

    def test_bot_last_activity(self):
        assert "botLastActivity: function" in JS
        assert "botLastActivity" in INDEX


class TestD3Sleep:
    def test_sleep_widget_reuses_cognition(self):
        assert "sleepWidget: function" in JS
        assert "/api/memory/cognition/status" in JS
        assert "dreamPhaseBadge" in INDEX and "deepPhaseBadge" in INDEX

    def test_no_new_timers_in_sleep(self):
        block = JS[JS.index("sleepWidget: function"):]
        block = block[:block.index("graphGroupOptions: function")]
        assert "setInterval" not in block and "setTimeout" not in block
        # активность — только с сервера (active берётся из ответа).
        assert "p.active" in block

    def test_sleep_card_span(self):
        assert "status-sleep" in INDEX


class TestD4Graph:
    def test_search_alias(self):
        block = JS[JS.index("searchCognitionGraph: async function"):]
        block = block[:block.index("clearCognitionGraphSearch: function")]
        assert "summaryAliasesMap" in block, "§16: поиск по алиасу"
        assert "В графе нет узла" in JS

    def test_enhancements(self):
        for m in ("graphNeighborsOf: function", "graphSelectNode: function",
                  "focusGraphNode: function", "applyGraphFilter: function",
                  "graphResetView: function"):
            assert m in JS, m

    def test_weight_layout_unchanged(self):
        assert "barnesHut" in JS
        assert "_graphSignature" in JS

    def test_full_screen_route(self):
        assert "'#/status/graph': 'status'" in JS
        assert "'#/status/graph': '#/'" in JS
        assert "status-graph-full" in INDEX
        assert "status-graph-full" in CSS

    def test_full_screen_a11y(self):
        # L-F11S-3: Esc/initial-focus/aria-modal + тач-цели ≥44px.
        assert 'ref="graphFullPanel"' in INDEX
        assert 'tabindex="-1"' in INDEX
        assert 'aria-modal="true"' in INDEX
        assert "_focusGraphFull: function" in JS
        assert "if (this.graphFullVisible) { this.closeGraphFull(); return; }" in JS
        assert ".status-graph-full .badge" in CSS
        assert "min-height: 44px" in CSS

    def test_mobile_simple_graph(self):
        assert "simpleGraph" in JS


class TestD5FactsBudgetsCounters:
    def test_facts_reuse_dossier(self):
        assert "factsFeed: function" in JS
        assert "/api/oversight/dossier_feed" in JS
        assert "Что бот недавно запомнил" in INDEX
        assert "status-facts" in INDEX

    def test_facts_no_horizontal_ticker(self):
        # Факты — вертикальный список `.facts-list`, НЕ бегущая строка.
        block = INDEX[INDEX.index("status-facts"):]
        block = block[:block.index("status-budgets")]
        assert "facts-list" in block
        assert "dossier-ticker" not in block

    def test_budgets_unlimited_no_bar(self):
        assert "status-budgets" in INDEX
        assert "Без лимита" in INDEX
        assert "Нет данных" in INDEX
        # «Безлимит» не рисует заполненный progress.
        assert "memoryContext.unlimited" in INDEX

    def test_counters_from_logs(self):
        assert "loadLogCounts: async function" in JS
        # H-F11S-1: читаем аддитивный `counts` (реальные числа), не `count`
        # (ограничен limit → максимум 1).
        assert "/api/status/logs?level=ALL&limit=1" in JS
        assert "counts.ERROR" in JS and "counts.WARNING" in JS
        assert "scrollToLogs: function" in JS
        assert "Ошибки:" in INDEX and "Предупреждения:" in INDEX

    def test_route_returns_additive_counts(self):
        # H-F11S-1: аддитивное поле `counts` в существующем эндпоинте
        # (R16-safe: новых endpoint'ов нет) + read-only агрегатор в логе.
        assert "level_counts" in ROUTES
        assert '"counts": ring.level_counts()' in ROUTES
        log_ring = (ROOT / "services" / "log_ring.py").read_text(encoding="utf-8")
        assert "def level_counts(self)" in log_ring


class TestD6Invariants:
    def test_version_bump(self):
        assert 'APP_VERSION = "2.58.27"' in SETTINGS
        assert "v2.58.27" in README

    def test_catalog_delta_zero(self):
        import services.param_catalog as pc
        assert len(pc.REGISTRY) == 469
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_no_new_routes(self):
        routes = sorted(set(re.findall(
            r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', ROUTES)))
        assert "/me" in routes
        # F11: новых endpoint'ов нет (R16).
        assert not any("status/graph" in r for r in routes)

    def test_csp_zero_build(self):
        # Нет inline `onclick=`/`<script>`-блоков в добавленной разметке и
        # нет внешних CDN в композиции Статуса.
        status = INDEX[INDEX.index("activeTab === 'status'"):
                       INDEX.index("activeTab === 'persona'")]
        assert "http://" not in status and "https://" not in status
        assert "<script" not in status
        assert "v-html" not in status


class TestD7WidgetPreservation:
    def test_section11_widgets_present(self):
        for label in ("Сердцебиение", "Бот", "Сервер", "Мониторинг Интеллекта",
                      "Доступность ключей", "История доступности ключей",
                      "Убеждения", "Парадигмы", "Эволюция характера"):
            assert label in INDEX, "§11: потерян виджет %s" % label

    def test_log_viewer_not_rewritten(self):
        assert 'class="log-panel scroll-thin"' in INDEX
        assert "copyLogRow(log, i)" in INDEX
        assert "ERROR+WARNING" in INDEX
        assert 'log.expanded && log.exc_text' in INDEX

    def test_heartbeat_not_rewritten(self):
        assert ".status-block { max-width: 100%; overflow: hidden; }" in CSS
        assert "hb-canvas" in INDEX and "ekg-trace" in INDEX
        assert "_applyHeartbeatSample" in JS
        assert "heartbeatCanvasEnabled" in JS

    def test_exec_preview_preserved(self):
        assert "exec-preview" in INDEX
        assert "loadExecPreview" in JS
