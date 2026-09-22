"""hotfix8 round 10.25 — маркер-гейт `hotfix8-shell-glass-aurora-round1025`.

Задачи T-2748…T-2782 (ADR-1025-16 D1–D5). Поведение (rendering/CSP) — в
`tests/js/round1025_hotfix8_shell_aurora_test.js` (запускается из
`tests/test_webapp_js_unit.py`); здесь — атомарные маркеры и инварианты:

  * A/B (D2) — shell-токены §4, `data-glass="shell"` (снятие цветной линзы A),
    sidebar 208–224px, радиусы, shell-v3-off-откат.
  * C (D3) — aurora/mesh (`body::before`/`body::after`/5 blob), legacy conic
    `bg-wash-legacy`, пауза `lg-bg-paused`, reduced-motion.
  * D (D4/D5) — геометрия/приёмка, env-only флаги (Δ каталога = 0), матрица.
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

HOTFIX8_FLAGS = ("UI_SHELL_V3", "UI_AURORA_BG_ENABLED")


def _first_party_web() -> dict:
    out = {}
    for p in (ROOT / "web").rglob("*"):
        if p.suffix.lower() not in (".css", ".js", ".html"):
            continue
        if "\\vendor\\" in str(p) or "/vendor/" in str(p):
            continue
        out[str(p)] = p.read_text(encoding="utf-8")
    return out


def _token(name: str) -> str:
    m = re.search(re.escape(name) + r"\s*:\s*([^;]+);", APP_CSS)
    return m.group(1).strip() if m else ""


class TestShellV3:
    def test_tokens_section4(self):
        # HOTFIX9 (ADR-1025-17 D4): графитовые токены §8 UPD3.
        assert _token("--shell-bg").replace(" ", "") == "rgba(27,29,34,0.94)"
        assert _token("--shell-bg-mobile").replace(" ", "") == "rgba(27,29,34,0.96)"
        assert _token("--shell-border-color").replace(" ", "") == \
            "rgba(255,255,255,0.09)"
        assert _token("--shell-highlight").replace(" ", "") == \
            "rgba(255,255,255,0.055)"
        assert _token("--shell-shadow").replace(" ", "") == \
            "04px16pxrgba(0,0,0,0.16)"
        blur = _token("--shell-blur").replace(" ", "")
        assert "blur(14px)" in blur and "saturate(105%)" in blur
        # Диагональная текстура удалена полностью (UPD3 §7).
        assert "--shell-texture:" not in APP_CSS
        assert "var(--shell-texture)" not in APP_CSS

    def test_cards_not_repainted(self):
        assert "--glass-bg: rgba(21, 27, 42, 0.5)" in APP_CSS
        assert "--glass-bg-strong: rgba(21, 27, 42, 0.85)" in APP_CSS

    def test_shell_layer_rule(self):
        m = re.search(r'\[data-glass="shell"\]\s*\{([^}]*)\}', APP_CSS)
        assert m, "нет правила [data-glass=\"shell\"]"
        body = m.group(1)
        assert "var(--shell-bg)" in body
        assert "var(--shell-blur)" in body
        assert "radial-gradient" not in body, "shell без цветной радиальной линзы"
        # Нейтральный бесцветный sheen ≤ .05 под контентом.
        s = re.search(r'\[data-glass="shell"\]::after\s*\{([^}]*)\}', APP_CSS)
        assert s, "нет нейтрального sheen ::after"
        assert "linear-gradient" in s.group(1)
        assert "z-index: -1" in s.group(1)
        assert "mask-image" not in s.group(1)
        assert "--shell-sheen-opacity: .05" in APP_CSS

    def test_panels_shell_not_lens_a(self):
        for marker in ('class="app-sidebar" data-glass="shell"',
                       'class="bottom-nav" data-glass="shell"',
                       'class="more-sheet" data-glass="shell"'):
            assert marker in INDEX, marker
        assert 'data-glass="shell"\n' in INDEX          # header (multiline)
        assert 'data-glass="a"' in INDEX                # контентный A сохранён
        # Цветная линза A остаётся только у контента.
        assert re.search(r'\[data-glass="a"\]::before\s*\{', APP_CSS)

    def test_sidebar_width_and_radii(self):
        m = re.search(r"\.app-shell\.ia-v2 \.app-sidebar\s*\{[\s\S]{0,200}"
                      r"width:\s*(\d+)px", APP_CSS)
        assert m and 208 <= int(m.group(1)) <= 224, m and m.group(1)
        pad = re.search(r"\.app-shell\.ia-v2 \{\s*padding-left:\s*(\d+)px",
                        APP_CSS)
        assert pad and 208 <= int(pad.group(1)) <= 224, pad and pad.group(1)
        assert re.search(r"\.more-sheet \{[\s\S]{0,1600}"
                         r"border-radius:\s*18px 18px 0 0", APP_CSS)
        assert re.search(r"\.bottom-nav \{[\s\S]{0,1200}"
                         r"border-radius:\s*18px 18px 0 0", APP_CSS)

    def test_shell_v3_off_rollback(self):
        assert ".app-shell.shell-v3-off" in APP_CSS
        assert "shell-v3-off" in INDEX and "shell-v3" in INDEX
        # UI_SHELL_GRAPHITE_V3=OFF → значения hotfix8 (текстура НЕ возвращается).
        assert re.search(r"\.app-shell\.shell-v3-off\s*\{[\s\S]{0,900}"
                         r"--shell-bg:\s*rgba\(24, 28, 38, 0\.72\)", APP_CSS)
        assert "shellGraphiteV3" in APP_JS


class TestAurora:
    def test_aurora_layer_and_blobs(self):
        assert INDEX.count('class="aurora-blob b') == 5
        assert 'class="aurora-bg"' in INDEX and "aurora-grain" in INDEX
        assert re.search(r"\.aurora-bg \{[^}]*position:\s*fixed", APP_CSS)
        assert re.search(r"\.aurora-bg \{[^}]*z-index:\s*0", APP_CSS)
        assert re.search(r"\.aurora-bg \{[^}]*pointer-events:\s*none", APP_CSS)

    def test_body_before_is_aurora_not_dead_conic(self):
        m = re.search(r"\n    body::before \{([^}]*)\}", APP_CSS)
        assert m
        body = m.group(1)
        assert "radial-gradient" in body
        assert "var(--surface-0)" in body
        assert "conic-gradient" not in body
        assert "aurora-flow var(--grad-speed)" in body
        assert "aurora-morph var(--grad-speed-slow)" in body

    def test_palette_without_orange(self):
        assert "#FF8A3D" not in APP_CSS
        for rgba in ("rgba(66, 214, 196", "rgba(119, 168, 255",
                     "rgba(167, 139, 250", "rgba(92, 124, 250"):
            assert rgba in APP_CSS, rgba

    def test_pause_and_reduced_motion(self):
        assert re.search(r"html\.lg-bg-paused \.aurora-blob", APP_CSS)
        assert re.search(r"html\.lg-bg-paused body::before", APP_CSS)
        assert "animation-play-state: paused" in APP_CSS
        assert re.search(r"@media \(prefers-reduced-motion: reduce\)"
                         r"[\s\S]{0,600}\.aurora-bg \.aurora-blob \{"
                         r" animation: none", APP_CSS)
        assert "lg-bg-paused" in APP_JS
        # Единый обработчик visibilitychange (без второго listener'а).
        assert APP_JS.count("addEventListener('visibilitychange'") == 1

    def test_legacy_conic_flag(self):
        assert re.search(r"html\.bg-wash-legacy body::before \{[\s\S]{0,600}"
                         r"conic-gradient", APP_CSS)
        assert re.search(r"html\.bg-wash-legacy \.aurora-bg \{ display: none",
                         APP_CSS)
        assert "_syncBgLayer" in APP_JS and "bg-wash-legacy" in APP_JS
        # Механика §10 сохранена для кнопок/band.
        assert "@property --grad-angle" in APP_CSS
        assert "@keyframes grad-spin" in APP_CSS
        assert "@keyframes grad-drift" in APP_CSS

    def test_no_csp_violations(self):
        for _path, text in _first_party_web().items():
            assert not re.search(r"backdrop-filter\s*:\s*url\(", text)
        assert not re.search(r"getContext\(['\"]webgl", APP_JS)
        assert "data:image" not in APP_CSS
        # Никаких новых библиотек/Framer/React/CDN.
        assert "framer" not in APP_JS.lower()
        assert "framer" not in INDEX.lower()
        assert not re.search(r"\breact\b", APP_JS.lower())
        assert not re.search(r"\breact\b", INDEX.lower())
        assert 'src="/static/vendor/vue.global.prod.min.js"' in INDEX
        assert 'href="http' not in INDEX.split("lg-lens")[0][-400:]


class TestFlagsAcceptance:
    def test_app_version_bumped(self):
        # T-2834: HOTFIX9 bump 2.58.11 → 2.58.12 (cache-bust shell/glass/aurora).
        m = re.search(r'APP_VERSION = "([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.17", m and m.group(1)

    def test_env_only_flags_delivered(self):
        for flag in HOTFIX8_FLAGS:
            assert f"{flag}: ClassVar" in SETTINGS, flag
            assert flag in ROUTES, f"{flag} не доставлен в ui_flags"
            assert flag in ENV_EXAMPLE, f"{flag} не в .env.example"
            assert flag in APP_JS, f"{flag} не читается фронтом"

    def test_flags_not_in_catalog(self):
        from services import param_catalog as pc
        for flag in HOTFIX8_FLAGS:
            assert flag not in pc.REGISTRY, flag

    def test_catalog_invariants(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 459
        assert len(pc.GROUPS) == 98
        assert len(pc._TAB_BY_GROUP) == 96
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 418

    def test_matrix_five_modes_and_probes(self):
        for mode in ("desktop_normal", "desktop_fullscreen", "tablet",
                     "mobile_regular", "mobile_fullscreen"):
            assert mode in MATRIX, mode
        assert "_hotfix8_failures" in MATRIX
        assert "shellGlass" in MATRIX
        assert "auroraAnim" in MATRIX
        assert "sidebarW" in MATRIX
        assert "headerCardGap" in MATRIX

    def test_f2_checker_rejects_static_background(self):
        from tools.ui_round1025_matrix import _f2_failures
        base = {
            "tokens": {"s0": "#090D17", "s1": "#151B2A", "teal": "#42D6C4",
                       "warn": "#F6C56F", "err": "#F07178",
                       "gs": "75s", "gss": "105s",
                       "glassBg": "rgba(21, 27, 42, 0.5)",
                       "displace": "url(#lg-lens)"},
            "beforeAnim": "none", "beforeDur": "75s, 105s",
            "afterAnim": "none", "auroraAnim": "none",
            "hasLensFilter": True,
            "allow": [{"tier": "a", "reason": "auto", "downgraded": False}],
            "utility": "rgb(162, 176, 198)",
            "denyCount": 1, "denyBf": "none",
            "panels": {"header": {"bf": "blur(16px) saturate(140%)"}},
            "overflow": False,
        }
        fails = _f2_failures(base, "t")
        assert any("static" in f for f in fails), fails

    def test_contrast_report(self):
        rep = (ROOT / "plans" / "reports" / "round1025_hotfix8_contrast.md")
        assert rep.exists(), "нет plans/reports/round1025_hotfix8_contrast.md"
        text = rep.read_text(encoding="utf-8")
        for cls in (".sidebar-link", ".sidebar-link.active",
                    ".bottom-nav-label", ".bottom-nav-link.active",
                    ".more-item", "header", ".scope-trigger"):
            assert cls in text, f"нет класса {cls} в AA-таблице"
        assert "PASS" in text and "4.5" in text

    def test_ia_and_store_untouched(self):
        assert re.search(r"bottomNavItems:\s*function", APP_JS)
        assert "sidebarGroups" in APP_JS
        assert "computeBottomOffset" in (ROOT / "web" / "static" /
                                          "telegram-init.js").read_text(
            encoding="utf-8")
