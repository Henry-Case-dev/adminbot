"""F3 round 10.24 (token-metrics-nodeflow-round1024, ADR-1024-7/13), review
iter1 — статический веб-смок раздела «Сводка» (дерево вызова Node Flow).

Не API-тест: аналитика (`web/api/analytics.py`) не меняется, контракт
`steps[]`/`total` уже полон. Проверяем статику фронтенда:
  * чистый русский нейминг без англо-жаргона (spec §3.5);
  * гейт kill-switch `TOKEN_FLOW_NODEFLOW_ENABLED` через `uiFlag`
    (OFF = прежние плоские бейджи 10.23 «байт-в-байт», ADR-1024-7 §6);
  * реальное ветвление в шаблоне (`.token-flow__branch` из `node.children`),
    а не линейный список (review High #1);
  * CSP/zero-build: без граф-библиотек и внешних ресурсов.

Вынесено из `tests/test_webapp_analytics_api.py` (review Low #6): это статика
фронтенда, а не RBAC/контракт API аналитики.
Автор: @Builder (review iter1).
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_INDEX = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
_APP_JS = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")


class TestNodeFlowNaming:
    def test_russian_labels_present(self):
        assert "Аналитика токенов" in _INDEX
        assert "Последний запрос (Дерево вызова)" in _INDEX
        assert "График расходов" in _INDEX

    def test_no_english_jargon(self):
        assert "Token Metrics" not in _INDEX
        # Технический жаргон наружу не выводится (spec §3.5).
        assert "stage1" not in _INDEX
        assert "stage2" not in _INDEX
        assert "correlation_id" not in _INDEX


class TestNodeFlowFlagGate:
    def test_template_uses_ui_flag(self):
        assert "uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED')" in _INDEX
        assert "ui_flags" in _APP_JS

    def test_off_branch_is_legacy_badges(self):
        # OFF (v-else) → прежние плоские бейджи 10.23.
        assert "tokenFlowNodes()" in _INDEX
        assert "badge badge-muted" in _INDEX

    def test_heading_and_axis_inside_on_gate(self):
        # ADR-1024-7 §6 / spec §9: OFF = «байт-в-байт» 10.23. Значит новые
        # элементы («График расходов», ось) выводятся ТОЛЬКО в ON-ветке.
        heading = '<div class="text-xs font-bold mb-1">График расходов</div>'
        assert heading in _INDEX
        off_marker = _INDEX.index("СТАРЫЙ рендер (10.23)")
        assert _INDEX.index(heading) < off_marker, (
            "заголовок графика должен быть в ON-ветке, до OFF-бейджей")
        # Ось гейтится флагом: OFF → не рендерится.
        assert ("uiFlag('TOKEN_FLOW_NODEFLOW_ENABLED') && tokenSeriesBars.length"
                in _INDEX)


class TestNodeFlowBranchWiring:
    def test_branch_container_rendered_from_children(self):
        # High #1: ветка — отдельный контейнер под родителем, под-ноды из
        # `.children` (производное от `edges`), НЕ на спине.
        assert 'class="token-flow__branch"' in _INDEX
        assert 'v-for="child in node.children"' in _INDEX
        assert "tokenFlowTree.main" in _INDEX
        # Старый линейный рендер удалён.
        assert "tokenFlowTree().nodes" not in _INDEX
        assert "node.kind === 'result'" not in _INDEX
        # Коннектор ↓ — только к следующей ноде спины.
        assert "idx < tokenFlowTree.main.length - 1" in _INDEX

    def test_app_js_builds_branches_from_edges(self):
        assert "hasBranch" in _APP_JS and "edges" in _APP_JS
        assert "children.push" in _APP_JS
        # computed, а не methods (Medium #4).
        assert _APP_JS.count("tokenFlowTree: function") == 1
        assert "tokenFlowTree: function" in _APP_JS


class TestNodeFlowCssOnly:
    def test_no_chart_libraries_or_external_resources(self):
        for lib in ("mermaid", "cytoscape", "d3.min.js", "chart.js",
                    "unpkg.com", "cdn.jsdelivr.net"):
            assert lib not in _INDEX
            assert lib not in _APP_JS
        assert "http://" not in _INDEX and "https://" not in _INDEX
