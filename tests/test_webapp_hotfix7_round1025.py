"""hotfix7 round 10.25 — маркер-гейт `hotfix7-shell-glass-heartbeat-round1025`.

Задачи T-2658…T-2694 (ADR-1025-13 D1–D5). Поведение (рендер/фолбэки) — в
`tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` (запускается из
`tests/test_webapp_js_unit.py`); здесь — атомарные маркеры и инварианты:

  * A (D1) — единый сток `--shell-h`, два режима normal/fullscreen, legacy-класс.
  * B (D2) — premium ECG sweep-wipe, отсутствие pulseX, флаг отката.
  * C (D3) — `--shell-*`-токены, specular/texture (CSS-градиенты), снятие виньетки.
  * D (D4/D5) — env-only флаги (Δ каталога = 0), матрица 5 режимов, APP_VERSION.
"""
import dataclasses
import re
from pathlib import Path

from config.settings import Settings

ROOT = Path(".")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
MATRIX = (ROOT / "tools" / "ui_round1025_matrix.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")

HOTFIX7_FLAGS = ("UI_SHELL_GLASS_V2", "UI_HEARTBEAT_PREMIUM",
                 "UI_SHELL_LAYOUT_V2")


def _first_party_web() -> dict:
    out = {}
    for p in (ROOT / "web").rglob("*"):
        if p.suffix.lower() not in (".css", ".js", ".html"):
            continue
        if "\\vendor\\" in str(p) or "/vendor/" in str(p):
            continue
        out[str(p)] = p.read_text(encoding="utf-8")
    return out


class TestAreaA_Layout:
    def test_single_height_token_chain(self):
        # HOTFIX9 (ADR-1025-17 D1): единственный источник — --app-usable-height
        # (база 100vh, апгрейд 100dvh за @supports); --shell-h — алиас.
        assert "--app-usable-height: 100vh;" in APP_CSS
        assert "--shell-h: var(--app-usable-height);" in APP_CSS
        assert re.search(
            r"@supports \(height: 100dvh\)[\s\S]{0,200}"
            r"--app-usable-height:\s*100dvh",
            APP_CSS), "нет @supports-апгрейда до 100dvh"

    def test_two_explicit_modes(self):
        shell = re.search(r"\.app-shell \{([^}]*)\}", APP_CSS)
        assert shell and "min-height: var(--shell-h)" in shell.group(1)
        fs = re.search(
            r"\.app-shell\.fullscreen-mode:not\(\.shell-layout-legacy\)\s*\{"
            r"([^}]*)\}", APP_CSS)
        assert fs, "нет .app-shell.fullscreen-mode (flex-колонка)"
        body = fs.group(1)
        assert "height: var(--app-usable-height" in body
        assert "max-height: var(--app-usable-height" in body
        assert "min-height: 0" in body
        assert "overflow: hidden" in body
        # mobile — та же фиксированная колонка.
        mob = re.search(
            r"\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\)\s*[,{]"
            r"([^}]*)\}", APP_CSS)
        assert mob, "нет .app-shell.shell-mobile (flex-колонка)"
        assert "height: var(--app-usable-height" in mob.group(1)
        assert "min-height: 0" in mob.group(1)
        # Скроллится только центральная зона.
        assert re.search(
            r"\.app-shell\.shell-mobile:not\(\.shell-layout-legacy\)"
            r" > main\.scroll-area[\s\S]{0,200}overflow-y:\s*auto", APP_CSS)
        # Навигация — последний flex-child, не fixed.
        assert re.search(r"\.bottom-nav \{[^}]*flex: 0 0 auto", APP_CSS)
        assert re.search(r"\.bottom-nav \{[^}]*position: relative", APP_CSS)

    def test_legacy_layout_rollback(self):
        assert ".app-shell.shell-layout-legacy" in APP_CSS
        assert re.search(
            r"\.app-shell\.shell-layout-legacy\.fullscreen-mode \{[\s\S]{0,200}"
            r"height: 100dvh", APP_CSS)
        assert "shell-layout-legacy" in INDEX

    def test_heartbeat_not_collapsed(self):
        assert re.search(r"\.hb-wrap \{[^}]*min-height: 56px", APP_CSS)
        assert re.search(r"\.fullscreen-mode \.scroll-area \{[\s\S]{0,200}"
                         r"overflow-y: auto", APP_CSS)


class TestAreaB_Heartbeat:
    def test_premium_render_markers(self):
        for m in ("_hbEcg", "_hbDrawPremium", "_hbDrawLegacy", "_hbDrawGrid",
                  "createRadialGradient", "sweep"):
            assert m in APP_JS, m
        # «линия + плавающая точка» удалена.
        assert "pulseX" not in APP_JS, "pulseX-паттерн остался"

    def test_canvas_not_webgl(self):
        assert "getContext('2d')" in APP_JS
        assert not re.search(r"getContext\(['\"]webgl", APP_JS)

    def test_state_semantics_untouched(self):
        assert "_heartbeatTransition: function" in APP_JS
        assert "heartbeatSample: function" in APP_JS
        assert not re.search(r"bpm\s*[:=]", APP_JS, re.I)
        # F-3 (review): HEALTHY-трасса читает статус-токен --ok (единство с бейджем).
        assert "_hbPalette" in APP_JS and "--ok" in APP_JS
        assert re.search(r"healthy:\s*'#3DD68C'", APP_JS)

    def test_glow_state_dependent(self):
        # F-4 (review): свечение — лестница по состояниям, CRITICAL заметно сильнее.
        assert "glowAlpha" in APP_JS
        assert re.search(r"critical:\s*0\.85", APP_JS)
        assert re.search(r"healthy:\s*0\.45", APP_JS)
        assert re.search(r"unknown:\s*0\b", APP_JS)
        assert "glowScale" in APP_JS

    def test_premium_flag_gate(self):
        assert "heartbeatPremium" in APP_JS
        assert "UI_HEARTBEAT_PREMIUM" in APP_JS


class TestAreaC_GlassShell:
    def test_shell_tokens_present(self):
        # HOTFIX9 (ADR-1025-17 D4): --shell-texture удалена; --shell-specular сохранён.
        for tok in ("--shell-bg", "--shell-bg-strong", "--shell-border-color",
                    "--shell-highlight", "--shell-highlight-soft",
                    "--shell-shadow", "--shell-blur", "--shell-specular",
                    "--card-shadow"):
            assert tok + ":" in APP_CSS, tok
        assert "--shell-texture:" not in APP_CSS
        assert "var(--shell-texture)" not in APP_CSS

    def test_shell_panels_use_shell_layer(self):
        for sel in (".app-sidebar", ".app-drawer", "header.header-sticky",
                    ".bottom-nav", ".more-sheet"):
            assert sel in APP_CSS
        assert "box-shadow: var(--shell-shadow)" in APP_CSS
        assert re.search(r"background-image: var\(--shell-specular\);", APP_CSS)
        assert not re.search(
            r"background-image: var\(--shell-specular\), var\(--shell-texture\)",
            APP_CSS)
        assert re.search(r"\.bottom-nav \{[\s\S]{0,1200}"
                         r"background-color: var\(--shell-bg\)", APP_CSS)
        assert re.search(r"\.more-sheet \{[\s\S]{0,1400}"
                         r"background-color: var\(--shell-bg\)", APP_CSS)

    def test_cards_not_repainted(self):
        # Карточки остаются на --glass-bg; значения §8 не меняются.
        assert "--glass-bg: rgba(21, 27, 42, 0.5)" in APP_CSS
        assert "--glass-bg-strong: rgba(21, 27, 42, 0.85)" in APP_CSS
        assert re.search(r"box-shadow: var\(--card-shadow\)", APP_CSS)
        assert "shell-glass-legacy" in INDEX

    def test_vignette_removed(self):
        assert re.search(r"body::before \{[\s\S]{0,900}opacity: \.30;", APP_CSS)
        assert re.search(r"--glass-shadow:[^;]*0\.55", APP_CSS)
        # Механика §10 сохранена.
        assert "@keyframes grad-spin" in APP_CSS
        assert "--grad-speed:75s" in APP_CSS

    def test_no_backdrop_url_and_no_assets(self):
        for _path, text in _first_party_web().items():
            assert not re.search(r"backdrop-filter\s*:\s*url\(", text)
        assert not re.search(r"--shell-(texture|specular)\s*:\s*url\(", APP_CSS)
        assert "data:image" not in APP_CSS


class TestAreaD_FlagsAcceptance:
    def test_app_version_bumped(self):
        m = re.search(r'APP_VERSION = "([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.22", m and m.group(1)

    def test_env_only_flags_delivered(self):
        for flag in HOTFIX7_FLAGS:
            assert f"{flag}: ClassVar" in SETTINGS, flag
            assert flag in ROUTES, f"{flag} не доставлен в ui_flags"
            assert flag in ENV_EXAMPLE, f"{flag} не в .env.example"

    def test_flags_not_in_catalog(self):
        from services import param_catalog as pc
        for flag in HOTFIX7_FLAGS:
            assert flag not in pc.REGISTRY, flag

    def test_catalog_invariants(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 468
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426

    def test_matrix_five_modes_and_probes(self):
        for mode in ("desktop_normal", "desktop_fullscreen", "tablet",
                     "mobile_regular", "mobile_fullscreen"):
            assert mode in MATRIX, mode
        assert "F7_PROBE_JS" in MATRIX
        assert "_hotfix7_failures" in MATRIX
        assert "fullscreenChanged" in MATRIX
        assert "__emit" in MATRIX
        assert "urlBackdropFilter" in MATRIX
        assert "hbVisible" in MATRIX
        assert "f2ShellH" in MATRIX
        assert "__f2_broken" in MATRIX

    def test_contrast_report(self):
        rep = (ROOT / "plans" / "reports" / "round1025_hotfix7_contrast.md")
        assert rep.exists(), "нет plans/reports/round1025_hotfix7_contrast.md"
        text = rep.read_text(encoding="utf-8")
        for cls in (".sidebar-link", ".sidebar-link.active",
                    ".bottom-nav-label", ".bottom-nav-link.active",
                    ".more-item", "header", ".hb-tip"):
            assert cls in text, f"нет класса {cls} в AA-таблице"
        assert "PASS" in text and "4.5" in text

    def test_ia_and_nav_untouched(self):
        # Порядок навигации F1/hotfix4 не менялся.
        assert re.search(r"bottomNavItems:\s*function", APP_JS)
        assert "sidebarGroups" in APP_JS
