"""Раунд 10.7 — UI/UX-маркеры (spec admin-ui-bugfixes-round107).

Проверяются CSS/шаблонные фиксы 1b/1c/1d/2a/3a/3b/3c и отсутствие
контекст-потери в копировании логов. Тесты статические (grep-маркеры).
"""
from pathlib import Path

ROOT = Path(".")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """Тело CSS-правила по селектору (selector .. '}')."""
    start = HTML.index(selector)
    end = HTML.index("}", start)
    return HTML[start:end]


class TestSafeArea1b:
    def test_horizontal_safe_area(self):
        assert "env(safe-area-inset-right" in HTML
        assert "calc(1rem + env(safe-area-inset-right, 0px))" in HTML
        assert "calc(1rem + env(safe-area-inset-left, 0px))" in HTML

    def test_sticky_and_fullscreen_intact(self):
        assert "position: sticky" in HTML
        assert ".fullscreen-mode .scroll-area" in HTML


class TestCompactUserBlock1c:
    def test_compact_sizes(self):
        assert "w-6 h-6" in HTML
        assert "max-w-[7rem]" in HTML
        assert "gap-1.5 text-xs" in HTML

    def test_elements_and_handlers_preserved(self):
        assert '@error="onMeAvatarError()"' in HTML
        assert "@click=\"toggleFullscreen()\"" in HTML
        assert "me.role_name" in HTML


class TestNavLabels1d:
    def test_no_anywhere_break_in_nav(self):
        # 1d: подписи не рвутся внутри слова — проверяем внутри .nav-label.
        nav = _rule(".nav-label {")
        assert "word-break: keep-all" in nav
        assert "overflow-wrap: break-word" in nav
        assert "-webkit-line-clamp: 2" in nav
        assert "text-overflow: ellipsis" in nav
        assert "overflow-wrap: anywhere" not in nav
        assert "0.625rem" in nav

    def test_nav_labels_present(self):
        assert 'class="nav-label"' in HTML
        assert ".nav-label {" in HTML
        assert ".nav-link > span:not(.msr) { display: none; }" not in HTML


class TestKeysTable2a:
    def test_scoped_fixed_layout(self):
        assert "keys-avail" in HTML
        assert ".keys-avail .avail-list { table-layout: fixed; }" in HTML
        # ellipsis — именно в scoped td-правиле таблицы ключей.
        assert "text-overflow: ellipsis" in _rule(".keys-avail .avail-list td {")

    def test_row_titles(self):
        assert ':title="p.module_title || p.module_id"' in HTML
        assert ':title="p.model || \'—\'"' in HTML


class TestGhostAndLogs3:
    def test_ghost_focusable_and_isolated(self):
        assert "preventScroll" in JS
        assert ".remove()" in JS
        ghost = _rule(".clipboard-ghost {")
        # DEF-1: visibility:hidden ломает фокус/execCommand → его быть не должно.
        assert "visibility: hidden" not in ghost
        assert "opacity: 0" in ghost
        assert "contain: strict" in ghost
        assert "position: fixed" in ghost

    def test_log_columns(self):
        assert ".log-level {" in HTML
        assert ".log-ts {" in HTML
        assert ".log-msg {" in HTML
        assert ".log-level { min-width: 4.5rem;" in HTML
        # word-break в scoped-правиле сообщения.
        assert "word-break: break-word" in _rule(".log-msg {")

    def test_copy_row_feedback(self):
        assert "copyLogRow(log, i)" in HTML
        assert "log-copied" in HTML
        assert "copyLogRow: function (log, i)" in JS

    def test_copy_all_explicit_context(self):
        body = JS[JS.index("copyAllLogs: function ()"):]
        body = body[:body.index("requestControl: function")]
        assert "self.logText(l)" in body
        assert "this.logs.map(this.logText)" not in body
