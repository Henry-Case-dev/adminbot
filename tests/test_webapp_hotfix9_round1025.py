"""hotfix9 round 10.25 — маркер-гейт `hotfix9-shell-liquidglass-darkaurora-round1025`.

Задачи T-2793…T-2836 (ADR-1025-17 D1–D8). Поведение (rendering/CSP) — в
`tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js` (запускается из
`tests/test_webapp_js_unit.py`); здесь — атомарные маркеры и инварианты:

  * A (D1) — единый источник `--app-usable-height` (+ алиас `--shell-h`),
    flex-колонка `shell-mobile`/fullscreen, nav в потоке, safe-area один раз.
  * B/C (D1/D2) — 4 пункта nav нажимаемы; header `flex:0 0 auto`; scrollTop.
  * D (D3) — `modal-card > modal-head/modal-body/modal-actions`; SaveBar в footer.
  * E/F (D4) — `--shell-texture` удалена; графитовые токены §8.
  * G/H (D5/D6) — vendored OGL/Liquid Glass, модули aurora-flow/glass, CSP-safe.
  * Δ DDL = 0, Δ каталога = 0; env-only флаги.
"""
import dataclasses
import re
from html.parser import HTMLParser
from pathlib import Path

from config.settings import Settings

ROOT = Path(".")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
TG_INIT = (ROOT / "web" / "static" / "telegram-init.js").read_text(encoding="utf-8")
AURORA = (ROOT / "web" / "static" / "aurora-flow.js").read_text(encoding="utf-8")
GLASS = (ROOT / "web" / "static" / "glass.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
MATRIX = (ROOT / "tools" / "ui_round1025_matrix.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")

HOTFIX9_FLAGS = ("UI_SHELL_FLEX_V3", "UI_SHELL_GRAPHITE_V3",
                 "UI_LIQUID_GLASS_LIB", "UI_AURORA_FLOW_V2")


class _ModalFooterParser(HTMLParser):
    """Стек тегов для контроля ВЛОЖЕННОСТИ `footer.modal-actions`.

    Регекс-проверка «наличие» не ловила, что футер может оказаться внутри
    `.modal-body`; здесь считаем множество классов-предков реального элемента.
    """

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # [(tag, set(classes))]
        self.actions = []    # [(line, ancestor_classes)]

    def handle_starttag(self, tag, attrs):
        classes = set()
        for key, value in attrs:
            if key == "class" and value:
                classes = set(value.split())
        if tag == "footer" and "modal-actions" in classes:
            ancestors = set()
            for _t, cls in self.stack:
                ancestors |= cls
            self.actions.append((self.getpos()[0], ancestors))
        if tag not in self._VOID:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        if tag in self._VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _token(name: str) -> str:
    m = re.search(re.escape(name) + r"\s*:\s*([^;]+);", APP_CSS)
    return m.group(1).strip() if m else ""


class TestGeometry:
    def test_single_height_source(self):
        assert _token("--app-usable-height") == "100vh"
        assert _token("--shell-h") == "var(--app-usable-height)"
        assert re.search(r"@supports \(height: 100dvh\)[\s\S]{0,200}"
                         r"--app-usable-height:\s*100dvh", APP_CSS)

    def test_flex_column_and_nav(self):
        assert re.search(
            r"\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\),[\s\S]{0,220}"
            r"height:\s*var\(--app-usable-height", APP_CSS)
        assert re.search(
            r"\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\)"
            r" > main\.scroll-area[\s\S]{0,220}overflow-y:\s*auto", APP_CSS)
        nav = re.search(r"\.bottom-nav \{([^}]*)\}", APP_CSS).group(1)
        assert "position: relative" in nav and "flex: 0 0 auto" in nav
        assert "position: fixed" not in nav
        # safe-area ровно один раз — nav без собственного offset/padding.
        assert "--tg-viewport-bottom-offset" not in nav
        assert "padding-bottom" not in nav

    def test_telegram_init_sets_usable_height(self):
        assert "--app-usable-height" in TG_INIT
        assert "computeBottomOffset" in TG_INIT
        assert "visualViewport" in TG_INIT

    def test_scrolltop_on_section_change(self):
        assert ".scroll-area" in APP_JS
        assert re.search(r"area\.scrollTop = 0", APP_JS)


class TestHeaderGlassTexture:
    def test_header_flex_and_scope_row(self):
        assert "header.header-sticky { flex: 0 0 auto; }" in APP_CSS
        assert ".header-scope-row" in APP_CSS

    def test_shell_texture_removed(self):
        assert "--shell-texture:" not in APP_CSS
        assert "var(--shell-texture)" not in APP_CSS

    def test_graphite_tokens(self):
        assert _token("--shell-bg").replace(" ", "") == "rgba(27,29,34,0.94)"
        assert _token("--shell-bg-mobile").replace(" ", "") == \
            "rgba(27,29,34,0.96)"
        assert _token("--shell-border-color").replace(" ", "") == \
            "rgba(255,255,255,0.09)"
        assert _token("--shell-highlight").replace(" ", "") == \
            "rgba(255,255,255,0.055)"
        assert _token("--shell-shadow").replace(" ", "") == \
            "04px16pxrgba(0,0,0,0.16)"
        blur = _token("--shell-blur").replace(" ", "")
        assert "blur(14px)" in blur and "saturate(105%)" in blur
        assert _token("--shell-bg") != _token("--glass-bg")


class TestModal:
    def test_modal_dom_actions(self):
        assert re.search(r"\.modal-actions \{[\s\S]{0,200}flex: 0 0 auto",
                         APP_CSS)
        assert re.search(
            r"\.modal-actions > \.sticky-save \{[\s\S]{0,120}position: static",
            APP_CSS)
        assert re.search(r"\.modal-card \{[\s\S]{0,200}app-usable-height",
                         APP_CSS)
        assert re.search(r'<footer class="modal-actions[^"]*">[\s\S]{0,300}'
                         r"<sticky-save", INDEX)
        assert re.search(r'<footer class="modal-actions">[\s\S]{0,400}'
                         r'<div class="sticky-save">', INDEX)

    def test_modal_actions_sibling_of_body(self):
        # H-H9S-1: футер обязан быть СИБЛИНГОМ `.modal-body` (не внутри него) —
        # иначе SaveBar уезжает в скроллер. Парсер проверяет предков каждого
        # `footer.modal-actions` (в т.ч. модалки модуля), а не соседство строк.
        parser = _ModalFooterParser()
        parser.feed(INDEX)
        assert parser.actions, "footer.modal-actions не найден в index.html"
        nested = [line for line, ancestors in parser.actions
                  if "modal-body" in ancestors]
        assert not nested, (
            "footer.modal-actions вложен ВНУТРЬ .modal-body (строки %s); "
            "ожидается modal-card > modal-head/modal-body/modal-actions"
            % nested)


class TestVendoredGlassAurora:
    def test_vendored_bundles_and_readme(self):
        for f in ("web/static/vendor/ogl.1.0.11.min.js",
                  "web/static/vendor/liquidglass.core.0.5.3.min.js",
                  "web/static/vendor/liquidglass.core.0.5.3.css"):
            assert (ROOT / f).exists(), f
        assert (ROOT / "tools" / "vendor" / "package.json").exists()
        assert (ROOT / "tools" / "vendor" / "package-lock.json").exists()
        readme = (ROOT / "web" / "static" / "vendor" / "README.md").read_text(
            encoding="utf-8")
        for need in ("0.5.3", "1.0.11", "MIT", "Unlicense", "SHA-256", "npm"):
            assert need in readme, need

    def test_same_origin_csp(self):
        assert 'src="/static/vendor/liquidglass.core.0.5.3.min.js' in INDEX
        assert 'src="/static/vendor/ogl.1.0.11.min.js' in INDEX
        assert 'src="/static/aurora-flow.js' in INDEX
        assert 'src="/static/glass.js' in INDEX
        assert 'href="/static/vendor/liquidglass.core.0.5.3.css' in INDEX
        assert not re.search(r'src="https?://', INDEX)
        # Никакого авторского backdrop url()-фильтра.
        assert not re.search(r"backdrop-filter\s*:\s*url\(", APP_CSS)

    def test_mount_and_aurora_contracts(self):
        assert "mountGlass" in GLASS and "data-lg-failed" in GLASS
        assert "OGL" in AURORA and "getContext('2d')" in AURORA
        assert "webglcontextlost" in AURORA
        assert "prefers-reduced-motion" in AURORA
        assert "aurora-flow-v2" in APP_CSS and "aurora-flow-canvas" in APP_CSS


class TestFlagsAcceptance:
    def test_app_version_bumped(self):
        m = re.search(r'APP_VERSION = "([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.12", m and m.group(1)

    def test_env_only_flags_delivered(self):
        for flag in HOTFIX9_FLAGS:
            assert f"{flag}: ClassVar" in SETTINGS, flag
            assert flag in ROUTES, f"{flag} не доставлен в ui_flags"
            assert flag in ENV_EXAMPLE, f"{flag} не в .env.example"
            assert flag in APP_JS, f"{flag} не читается фронтом"

    def test_flags_not_in_catalog(self):
        from services import param_catalog as pc
        for flag in HOTFIX9_FLAGS:
            assert flag not in pc.REGISTRY, flag

    def test_catalog_invariants(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 459
        assert len(pc.GROUPS) == 98
        assert len(pc._TAB_BY_GROUP) == 96
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 418

    def test_matrix_hotfix9_probes(self):
        for mode in ("desktop_normal", "desktop_fullscreen", "tablet",
                     "mobile_regular", "mobile_fullscreen"):
            assert mode in MATRIX, mode
        for probe in ("H9_PROBE_JS", "_h9_failures", "_bg_motion",
                      "H9_MODAL_PROBE_JS", "H9_MODULE_MODAL_OPEN_JS",
                      "H9_CONTEXT_LOSS_JS", "H9_CONTEXT_LOSS_PROBE_JS",
                      "elementFromPoint"):
            assert probe in MATRIX, probe

    def test_persist_and_ia_untouched(self):
        assert "persistItems" in APP_JS
        assert re.search(r"bottomNavItems:\s*function", APP_JS)
        assert "computeBottomOffset" in TG_INIT
