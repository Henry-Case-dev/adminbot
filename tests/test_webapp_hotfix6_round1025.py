"""hotfix6 round 10.25 — области A/B/C/D (T-2583…T-2613, ADR-1025-12).

Проверяет:
  * A — преломление без `backdrop-filter: url()` (grep-инвариант §9),
    foreground-линза `#lg-lens`, allow-list панелей, feature-detect + кап.
  * B — нижний offset = max(A,B,C) (`contentSafeAreaInset.bottom`), матрица
    усиливает вертикальный контроль при симулированном нижнем баре.
  * C — §15: Canvas 2D (не SVG/WebGL), телеметрия отделена, состояния/гистерезис,
    UNKNOWN, тултип, reduced-motion, C1-overflow.
  * D — двухстрочная шапка под гейтом, резерв `--header-h`, fullscreen.
  * Общее — `APP_VERSION` 2.58.8 (bump hotfix7); env-only флаги вне `param_catalog` (Δ каталога=0).
"""
import re
from pathlib import Path

ROOT = Path(".")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
TG_INIT = (ROOT / "web" / "static" / "telegram-init.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
MATRIX = (ROOT / "tools" / "ui_round1025_matrix.py").read_text(encoding="utf-8")


def _first_party_web() -> dict:
    out = {}
    for p in (ROOT / "web").rglob("*"):
        if p.suffix.lower() not in (".css", ".js", ".html"):
            continue
        if "\\vendor\\" in str(p) or "/vendor/" in str(p):
            continue
        out[str(p)] = p.read_text(encoding="utf-8")
    return out


# ═══════════════════════════ A — преломление ═══════════════════════════════
class TestAreaA:
    def test_no_backdrop_url_filter_anywhere(self):
        """§9/ADR-1025-12 D1: нигде в first-party web/** нет backdrop url-фильтра."""
        found = {p: True for p, t in _first_party_web().items()
                 if re.search(r"backdrop-filter\s*:\s*url\(", t)}
        assert not found, f"backdrop url-фильтр остался: {sorted(found)}"

    def test_foreground_lens_mechanism(self):
        """A = foreground-линза (#lg-lens) через filter:url(), не backdrop."""
        assert INDEX.count('id="lg-lens"') == 1
        assert re.search(r"--glass-displace\s*:\s*url\(#lg-lens\)", APP_CSS)
        lens = re.search(r'\[data-glass="a"\]::before\s*\{([^}]*)\}', APP_CSS)
        assert lens, "нет линзы [data-glass=\"a\"]::before"
        body = lens.group(1)
        assert "var(--glass-displace)" in body          # foreground filter
        assert "radial-gradient(ellipse at center" in body  # edge-weighted
        assert "mask-image" in body
        assert "z-index: -1" in body                    # под контентом

    def test_feature_detect_and_cap(self):
        """A: tier — feature-detect filter:url(#lg-lens) + кап (не UA/min-240)."""
        assert "css.supports('filter', 'url(#lg-lens)')" in APP_JS
        assert "UI_LENS_MAX_NODES" in APP_JS
        assert "_lensMaxNodes" in APP_JS
        assert "data-glass-tier" in APP_JS and "data-glass-reason" in APP_JS
        # UA-gate Blink-only снят.
        assert "AppleWebKit" not in APP_JS
        assert "backdrop-filter', 'url(#lg-displace)" not in APP_JS

    def test_panels_in_allow_list(self):
        """A2: панели (sidebar/drawer/header/bottom-nav/more-sheet) в allow-list."""
        assert 'class="app-sidebar" data-glass="a"' in INDEX
        assert 'class="app-drawer"' in INDEX and "data-glass=\"a\"" in INDEX
        assert 'class="bottom-nav" data-glass="a"' in INDEX
        assert 'class="more-sheet" data-glass="a"' in INDEX
        assert "data-glass=\"a\"\n" in INDEX  # header (многострочный тег)

    def test_panels_glass_and_fallback(self):
        """A2: панели получают blur; @supports-фолбэк переводит их в C."""
        for sel in (".app-sidebar", ".app-drawer", ".bottom-nav", ".more-sheet"):
            assert sel in APP_CSS
        assert "backdrop-filter: var(--glass-blur) saturate(140%)" in APP_CSS
        # fallback-набор включает панели (непрозрачная подложка).
        assert re.search(
            r"@supports not \(\(backdrop-filter: blur\(1px\)\)[\s\S]{0,900}"
            r"\.bottom-nav, \.more-sheet", APP_CSS), "панели не в fallback-наборе"

    def test_reduced_motion_tier_b(self):
        """LOW/T-2548/D1: reduced-motion → tier B (осознанное решение)."""
        assert "else if (reduced) reason = 'reduced-motion';" in APP_JS

    def test_lens_gradient_uses_tokens(self):
        """LOW/T-2591: градиент линзы — токены §10 (--grad-*), без хардкод-rgba."""
        lens = re.search(r'\[data-glass="a"\]::before\s*\{([^}]*)\}', APP_CSS)
        assert lens
        assert "rgba(66, 214, 196" not in lens.group(1), "хардкод-градиент остался"
        assert "var(--grad-a)" in lens.group(1)

    def test_matrix_aa_panel_probe(self):
        """HIGH/T-2591: матрица меряет AA текста панелей (композит стекла)."""
        assert "_panel_contrast_failures" in MATRIX
        assert "panelText" in MATRIX
        assert "glassBgStrong" in MATRIX
        assert "_PANEL_TEXT_TARGETS" in MATRIX
        assert "MORE_ITEM_PROBE_JS" in MATRIX


# ═══════════════════════════ B — нижний offset ═════════════════════════════
class TestAreaB:
    def test_offset_is_max_of_three(self):
        assert "computeBottomOffset" in TG_INIT
        assert "Math.max(a, b, c)" in TG_INIT
        assert "contentSafeAreaInset" in TG_INIT and "safeAreaInset" in TG_INIT

    def test_nav_and_sheet_use_offset(self):
        assert "var(--tg-viewport-bottom-offset" in APP_CSS
        assert re.search(
            r"\.bottom-nav \{[^}]*--tg-viewport-bottom-offset", APP_CSS)
        assert re.search(
            r"\.more-sheet \{[^}]*--tg-viewport-bottom-offset", APP_CSS)

    def test_matrix_vertical_and_contentsafe(self):
        """T-2595: матрица усиливает вертикаль + симулирует contentSafeArea."""
        assert "_vertical_failures" in MATRIX
        assert "contentSafeAreaInset" in MATRIX
        assert "--tg-content-safe-area-inset-bottom" in MATRIX
        assert "rect.bottom" in MATRIX or "bottom: Math.round(r.bottom)" in MATRIX

    def test_nav_order_untouched(self):
        """Порядок навигации F1/hotfix4 не менялся."""
        assert "bottomNavItems" in APP_JS
        assert re.search(r"bottomNavItems:\s*function", APP_JS)

    def test_matrix_stable_bar_restored(self):
        """LOW/T-2595: системный бар = разница видимой высоты (stable=h−56)."""
        assert "Math.max(0, h - 56)" in MATRIX
        assert "--tg-content-safe-area-inset-bottom" in MATRIX


# ═══════════════════════════ C — сердцебиение §15 ══════════════════════════
class TestAreaC:
    def test_canvas_not_svg_not_webgl(self):
        assert 'class="hb-canvas"' in INDEX
        assert "getContext('2d')" in APP_JS
        assert not re.search(r"getContext\(['\"]webgl", APP_JS)
        assert "requestAnimationFrame" in APP_JS
        # legacy SVG сохранён под v-else (откат).
        assert 'v-if="heartbeatCanvasEnabled"' in INDEX
        assert 'class="ekg"' in INDEX

    def test_state_machine_and_hysteresis(self):
        assert "_heartbeatTransition" in APP_JS
        # пороги входа/выхода зафиксированы.
        assert "0.85" in APP_JS and "0.65" in APP_JS
        assert "0.90" in APP_JS and "0.70" in APP_JS
        # состояния §15.
        for st in ("healthy", "warning", "critical", "unknown"):
            assert st in APP_JS, st
        # тултип содержит обязательные поля.
        for f in ("cpu", "mem", "disk", "updated", "reason"):
            assert f in APP_JS
        assert 'class="hb-tip"' in INDEX

    def test_telemetry_separate_no_new_poller(self):
        assert "this._applyHeartbeatSample(this.heartbeatSample())" in APP_JS
        assert "_applyHeartbeatSample({ missing: true })" in APP_JS
        # новый поллер не вводится: EKG-цикла с setInterval нет.
        assert "startStatusPolling" in APP_JS
        assert "_hbPoller" not in APP_JS

    def test_overflow_c1(self):
        assert re.search(r"\.status-block \{ max-width: 100%; overflow: hidden; \}",
                         APP_CSS)
        assert re.search(r"\.hb-canvas \{[^}]*width: 100%", APP_CSS)
        assert "--tg-content-safe-area-inset-bottom" in TG_INIT

    def test_off_path_legacy_semantics(self):
        """HIGH/T-2599: UI_HEARTBEAT_CANVAS_ENABLED=false откатывает семантику."""
        assert "heartbeatLegacy: function" in APP_JS
        assert "this.heartbeatCanvasEnabled === false" in APP_JS
        assert "return this.heartbeatLegacy;" in APP_JS
        # legacy-класс уровня на SVG-обёртке при OFF.
        assert "'ekg-' + heartbeat.level" in INDEX

    def test_dwell_counter(self):
        """MEDIUM/T-2601: dwell — N последовательных подтверждающих сэмплов."""
        assert "DWELL_N" in APP_JS
        assert "dwellPending" in APP_JS and "dwellCount" in APP_JS

    def test_unknown_missing_vs_bad(self):
        """MEDIUM/T-2603: missing ≠ bad; polling_error → CRITICAL; нет gen → stale."""
        assert "'polling_error'" in APP_JS
        assert "'нет отметки времени'" in APP_JS
        assert "missing: true, reason: 'нет состояния бота'" in APP_JS

    def test_tooltip_a11y(self):
        """LOW/T-2602: у тултипа id, у canvas — aria-describedby."""
        assert 'id="hb-tip"' in INDEX
        assert 'aria-describedby="hb-tip"' in INDEX


# ═══════════════════════════ D — шапка/fullscreen ══════════════════════════
class TestAreaD:
    def test_two_row_header_gated(self):
        assert "headerCompactV2" in APP_JS
        assert "UI_HEADER_COMPACT_V2" in APP_JS
        assert "header-scope-row" in INDEX
        assert "header-fs-btn" in INDEX
        # селектор области — ОДИН экземпляр (F3-инвариант, без дублирования).
        assert INDEX.count("{{ scopeLabel }}") == 1
        assert ".header-scope-row { display: contents; }" in APP_CSS

    def test_header_height_reserve(self):
        assert "_initHeaderHeight" in APP_JS
        assert "--header-h" in APP_JS
        assert re.search(r"scroll-padding-top: calc\(var\(--header-h", APP_CSS)

    def test_header_user_class_live(self):
        """LOW/D4: правило `.header-user span` не мёртвое — класс в разметке."""
        assert "header-user" in INDEX
        assert ".header-compact-v2 .header-scope-row .header-user span" in APP_CSS

    def test_fullscreen_preserved_and_hardened(self):
        # ADR-1024-24 не отменён.
        for m in ("toggleFullscreen", "initFullscreen",
                  "setFullscreenFromTma", "teardownFullscreen"):
            assert m in APP_JS, m
        assert "requestFullScreen" in APP_JS  # устойчивость к вариантам имени


# ═══════════════════════════ Общее: версия/флаги ═══════════════════════════
class TestCommon:
    def test_app_version_bumped(self):
        m = re.search(r'APP_VERSION\s*=\s*"([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.9", m and m.group(1)

    def test_matrix_hotfix6_probes(self):
        """T-2598/T-2611: матрица проверяет C1-overflow и ⛶ в вьюпорте."""
        assert "_hotfix6_failures" in MATRIX
        assert "hbOverflow" in MATRIX and "fsBtnInViewport" in MATRIX
        assert "header-compact-v2" in MATRIX

    def test_env_only_flags_defined(self):
        for flag in ("UI_GLASS_TIER_OVERRIDE", "UI_HEARTBEAT_CANVAS_ENABLED",
                     "UI_HEADER_COMPACT_V2", "UI_LENS_MAX_NODES"):
            assert f"{flag}: ClassVar" in SETTINGS, flag
            assert flag in ROUTES, f"флаг {flag} не доставлен в ui_flags"

    def test_flags_not_in_param_catalog(self):
        """Δ каталога = 0: флаги — env-only ClassVar, не ключи каталога."""
        from services import param_catalog as pc
        for flag in ("UI_GLASS_TIER_OVERRIDE", "UI_HEARTBEAT_CANVAS_ENABLED",
                     "UI_HEADER_COMPACT_V2", "UI_LENS_MAX_NODES"):
            assert flag not in pc.REGISTRY, f"{flag} попал в каталог (Δ≠0)"

    def test_contrast_report_exists(self):
        """HIGH/T-2591: артефакт AA-таблицы новых стеклянных панелей."""
        rep = (ROOT / "plans" / "reports" / "round1025_hotfix6_contrast.md")
        assert rep.exists(), "нет plans/reports/round1025_hotfix6_contrast.md"
        text = rep.read_text(encoding="utf-8")
        for cls in (".sidebar-link", ".bottom-nav-label", ".more-item", "header"):
            assert cls in text, f"нет класса {cls} в AA-таблице"
        assert "PASS" in text and "4.5" in text
