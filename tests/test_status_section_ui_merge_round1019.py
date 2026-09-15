"""Раунд 10.19 — F5 `status-section-ui-merge` (T-1823/T-1824).

Статические маркеры объединённого блока «Статус» и компактного поиска по
графу; API-контракт «Статуса» не изменён (R16).

Гейты: `node --check`/`routing_test.js`/`vue_mount_test.js` — в отчёте прогона;
здесь — пины разметки/стилей (без JS-движка).
"""
from pathlib import Path

ROOT = Path(".")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
STATUS_SRC = (ROOT / "services" / "status_service.py").read_text(encoding="utf-8")


class TestStatusSectionMerge:
    def test_single_status_block_with_three_sections(self):
        assert 'class="card p-4 status-block"' in HTML
        assert 'class="status-block__grid"' in HTML
        for section in ("status-block__pulse", "status-block__bot",
                        "status-block__server"):
            assert section in HTML, section
        # порядок подсекций: Сердцебиение → Бот → Сервер
        assert HTML.index("status-block__pulse") < \
            HTML.index("status-block__bot") < \
            HTML.index("status-block__server")

    def test_mode_version_line_removed(self):
        assert "Режим:" not in HTML
        assert "· версия" not in HTML
        assert "statusData.bot.mode" not in HTML
        assert "statusData.bot.version" not in HTML

    def test_api_fields_kept(self):
        """R16: поля bot.mode/bot.version остаются в ответе сервера."""
        assert '"mode"' in STATUS_SRC
        assert '"version"' in STATUS_SRC

    def test_ekg_and_controls_preserved(self):
        assert "ekg-trace" in HTML
        assert "requestControl('restart')" in HTML
        assert "hasPerm('action.control.start')" in HTML


class TestGraphSearchCompact:
    def test_mobile_input_compact(self):
        start = CSS.index(".graph-search {")
        block = CSS[start:start + 1100]
        assert "max-width: 460px" in block          # десктоп — не на всю ширину
        assert "font-size: 0.8rem" in block         # мобила — компактный
        assert "padding: 0.3rem 0.5rem" in block

    def test_field_base_untouched(self):
        # базовый .field (общий для форм) не переопределяем глобально
        assert ".graph-search .graph-search__input" in CSS

    def test_graph_search_logic_intact(self):
        JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        assert "searchCognitionGraph" in JS
        assert "clearCognitionGraphSearch" in JS
        assert "graphSearchQuery" in JS
