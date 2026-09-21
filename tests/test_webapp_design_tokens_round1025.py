"""F2 round 10.25 — дизайн-токены §8, Liquid Glass A/B/C §9, фон §10.

Задачи: T-2531…T-2534 (палитра/контраст), T-2535 (иерархия кнопок),
T-2536 (зачистка OD4-хардкода), T-2538…T-2540 (Liquid Glass A/B/C, allow/deny),
T-2544…T-2548 (фон §10, пауза, reduced-motion), T-2550 (inventory «множества»).
ADR-1025-9 (D1–D5).

Инварианты: имена токенов-потребителей сохранены; OD4-литералов в first-party
`web/**` нет (vendor исключён); длительности — §10; мелкий текст ≥4.5:1 (AA).
"""
import re
from pathlib import Path

ROOT = Path(".")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
TG_INIT = (ROOT / "web" / "static" / "telegram-init.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")

# ── D5: жёсткий эталон-множество маркеров дизайн-системы (presence) ──────────
EXPECTED_TOKENS = {
    "--surface-0", "--surface-1", "--surface-2", "--surface-3",
    "--text-1", "--text-2", "--text-3",
    "--teal-500", "--teal-600", "--purple-500", "--purple-400", "--indigo-300",
    "--ok", "--warn", "--err", "--ok-bg", "--warn-bg", "--err-bg",
    "--grad-a", "--grad-b", "--grad-c", "--grad-d",
    "--grad-speed", "--grad-speed-slow", "--grad-angle", "--accent-grad",
    "--glass-bg", "--glass-bg-strong", "--glass-blur", "--glass-border",
    "--glass-displace",
}
EXPECTED_VALUES = {
    "--surface-0": "#090D17", "--surface-1": "#151B2A", "--surface-2": "#1C2537",
    "--text-1": "#F4F7FB", "--text-2": "#AAB6C8",
    "--teal-500": "#42D6C4", "--purple-500": "#A78BFA", "--indigo-300": "#77A8FF",
    "--warn": "#F6C56F", "--err": "#F07178",
    "--grad-a": "#42D6C4", "--grad-b": "#77A8FF", "--grad-c": "#A78BFA",
    "--grad-d": "#5C7CFA",
    "--glass-bg": "rgba(21, 27, 42, 0.5)",
    "--glass-bg-strong": "rgba(21, 27, 42, 0.85)",
}
GLASS_LEVELS = {"a", "b", "c"}

# OD4/Relume-литералы (SUPERSEDE, ADR-1025-9) — не должны остаться в web/**.
OD4_LITERALS = {
    "#0E0E0E", "#161616", "#1F1F1F", "#262626",
    "#F5F5F5", "#BABABA", "#9E9E9E",
    "#14CBB6", "#12B7A4", "#664EA0", "#8D6BDC", "#A78DE4",
    "#A91443", "#C25879", "#D9CDF3",
    "#16B364", "#EAAA08", "#FF4848", "#FF8A3D",
    "rgba(20, 25, 30", "rgba(20,25,30",
    "rgba(22, 22, 22", "rgba(22,22,22",
    "rgba(20, 203, 182", "rgba(20,203,182",
}


def _tokens(css: str) -> set:
    """Имена CSS-переменных, объявленных через `--name: value`."""
    return set(re.findall(r"(--[\w-]+)\s*:", css))


def _token_value(name: str) -> str:
    m = re.search(re.escape(name) + r"\s*:\s*([^;]+);", APP_CSS)
    return m.group(1).strip() if m else ""


def _first_party_web() -> dict:
    out = {}
    for p in (ROOT / "web").rglob("*"):
        if p.suffix.lower() not in (".css", ".js", ".html"):
            continue
        if "\\vendor\\" in str(p) or "/vendor/" in str(p):
            continue
        out[str(p)] = p.read_text(encoding="utf-8")
    return out


def _lum(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    parts = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in parts)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    l1, l2 = _lum(fg), _lum(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ═══════════════════════ T-2550: inventory-множество ═══════════════════════
class TestInventory:
    def test_expected_tokens_present(self):
        """Presence: каждый маркер присутствует (сравнение множеств, не in)."""
        missing = EXPECTED_TOKENS - _tokens(APP_CSS)
        assert not missing, f"потеряны токены-маркеры: {sorted(missing)}"

    def test_token_values_section8(self):
        wrong = {k: (_token_value(k), v) for k, v in EXPECTED_VALUES.items()
                 if _token_value(k).upper() != v.upper()}
        assert not wrong, f"значения §8 разошлись (факт, ожидание): {wrong}"

    def test_no_od4_literals_in_first_party(self):
        """Absence: в first-party web/** нет OD4-литералов (vendor исключён)."""
        found = {}
        for path, text in _first_party_web().items():
            hits = {lit for lit in OD4_LITERALS if lit in text}
            if hits:
                found[path] = sorted(hits)
        assert not found, f"остаточные OD4-литералы: {found}"

    def test_glass_levels_declared(self):
        for lvl in GLASS_LEVELS:
            assert f'data-glass="{lvl}"' in APP_CSS or f'data-glass="{lvl}"' in INDEX, \
                f"уровень glass {lvl} не объявлен"

    def test_app_version_pinned(self):
        m = re.search(r'APP_VERSION\s*=\s*"([\d.]+)"', SETTINGS)
        assert m, "APP_VERSION не найден"
        assert m.group(1) == "2.58.5", f"APP_VERSION = {m.group(1)} (ожидалось 2.58.5)"


# ═══════════════ T-2531/T-2533/T-2534: палитра §8 и контраст ═══════════════
class TestPaletteSection8:
    def test_status_tokens(self):
        assert _token_value("--warn").upper() == "#F6C56F"
        assert _token_value("--err").upper() == "#F07178"
        # ok согласован с палитрой (не OD4 #16B364)
        assert _token_value("--ok").upper() != "#16B364"

    def test_status_tints_match_base(self):
        assert "61,214,140" in _token_value("--ok-bg").replace(" ", "")
        assert "246,197,111" in _token_value("--warn-bg").replace(" ", "")
        assert "240,113,120" in _token_value("--err-bg").replace(" ", "")

    def test_text_contrast_aa(self):
        """D4/T-2534: .75rem (12px, нормальный) ≥4.5:1 на surface-0..3."""
        surfaces = {"s0": "#090D17", "s1": "#151B2A", "s2": "#1C2537",
                    "s3": "#232E45"}
        fgs = {"--text-1": "#F4F7FB", "--text-2": "#AAB6C8", "--text-3": "#94A3B8"}
        fails = []
        for fn, fv in fgs.items():
            for sn, sv in surfaces.items():
                ratio = _contrast(fv, sv)
                if ratio < 4.5:
                    fails.append((fn, sn, round(ratio, 2)))
        assert not fails, f"контраст ниже 4.5:1: {fails}"

    def test_accent_contrast_on_dark(self):
        for a in ("#42D6C4", "#A78BFA", "#77A8FF", "#F6C56F", "#F07178"):
            assert _contrast(a, "#090D17") >= 4.5, a

    def test_telegram_fallbacks_section8(self):
        assert "'#151B2A'" in TG_INIT and "'#090D17'" in TG_INIT
        assert "'#161616'" not in TG_INIT and "'#0E0E0E'" not in TG_INIT

    def test_chart_palette_section8(self):
        assert "#42D6C4" in APP_JS and "'#AAB6C8'" in APP_JS
        assert "#14CBB6" not in APP_JS and "#8D6BDC" not in APP_JS


# ═══════════════════ T-2535: иерархия кнопок §8 ═══════════════════
class TestButtons:
    def test_three_levels_distinct(self):
        accent = _token_value("--accent-grad")
        assert accent and "#FF8A3D" not in accent.upper()
        # primary — светлая заливка + тёмный текст (AA);
        assert re.search(r"\.btn-accent\s*\{[^}]*color:\s*#081018", APP_CSS)
        # secondary — прозрачно-приглушённая с бордером;
        assert re.search(r"\.btn-ghost\s*\{[^}]*border:\s*var\(--card-border\)",
                         APP_CSS)
        # danger — семантический --err, не как primary.
        assert re.search(r"\.btn-danger\s*\{[^}]*var\(--err\)", APP_CSS)

    def test_no_random_accent_on_cards(self):
        # §8: запрещён «случайный цвет на карточку» — карточки не заливаются
        # акцентным conic/lineargradient.
        assert not re.search(r"\.card\s*\{[^}]*var\(--accent-grad\)", APP_CSS)


# ═══════════ T-2538…T-2543: Liquid Glass A/B/C, allow/deny ═══════════
class TestLiquidGlassV2:
    def test_single_inline_svg_filter(self):
        assert INDEX.count('id="lg-displace"') == 1, "должен быть ОДИН фильтр"
        assert "feDisplacementMap" in INDEX
        assert "feTurbulence" in INDEX and "feGaussianBlur" in INDEX
        # CSP/zero-build: без внешних ссылок/data-URI на фильтр.
        assert "lg-displace" in INDEX.split("filter id=")[1][:2000]
        assert 'href="http' not in INDEX.split("lg-displace")[0][-400:]

    def test_level_a_opt_in_only(self):
        # A применяется только к [data-glass="a"] и через токен --glass-displace.
        m = re.search(
            r'\[data-glass="a"\]\s*\{([^}]*var\(--glass-displace\)[^}]*)\}', APP_CSS)
        assert m, "нет правила [data-glass=\"a\"] с преломлением"
        body = m.group(1)
        assert "var(--glass-blur)" in body
        assert _token_value("--glass-displace").startswith("url(#lg-displace")

    def test_level_b_default(self):
        assert "backdrop-filter: var(--glass-blur) saturate(140%)" in APP_CSS
        assert "var(--glass-bg)" in APP_CSS

    def test_deny_list_level_c(self):
        # textarea/таблицы/логи — без преломления и blur.
        assert re.search(r"\[data-glass=\"c\"\][^{]*\{[^}]*backdrop-filter:\s*none",
                         APP_CSS)
        for sel in ("textarea", ".avail-list", ".log-panel", "textarea.field"):
            assert sel in APP_CSS
        for el in ('data-glass="c"',):
            assert el in INDEX

    def test_supports_fallback_defined(self):
        assert "@supports not ((backdrop-filter: blur(1px))" in APP_CSS
        assert "@supports not ((backdrop-filter: url(#lg-displace))" in APP_CSS

    def test_no_animated_blur(self):
        # T-2541: никакой animation по filter/backdrop-filter на viewport-слоях.
        assert not re.search(r"animation:[^;}]*(backdrop-)?filter", APP_CSS)

    def test_glass_js_reconcile(self):
        assert "reconcileLiquidGlass" in APP_JS
        assert "_liquidGlassSupported" in APP_JS
        assert "240" in APP_JS  # min-сторона страховки
        assert 'data-glass="a"' in INDEX
        assert "getBoundingClientRect" in APP_JS


# ═══════════════ T-2544…T-2549: фон §10, пауза, reduced-motion ═══════════════
class TestBackgroundSection10:
    def test_durations_section10(self):
        m = re.search(r"--grad-speed\s*:\s*([\d.]+)s", APP_CSS)
        assert m and 60.0 <= float(m.group(1)) <= 90.0, m and m.group(1)
        m2 = re.search(r"--grad-speed-slow\s*:\s*([\d.]+)s", APP_CSS)
        assert m2 and 90.0 <= float(m2.group(1)) <= 120.0, m2 and m2.group(1)

    def test_mechanics_preserved(self):
        assert "@property --grad-angle" in APP_CSS
        assert "@keyframes grad-spin" in APP_CSS
        assert "@keyframes grad-drift" in APP_CSS
        assert "animation: grad-spin var(--grad-speed) linear infinite" in APP_CSS
        assert "grad-drift var(--grad-speed-slow)" in APP_CSS

    def test_no_orange_zone(self):
        assert "#FF8A3D" not in APP_CSS and "var(--grad-d)" in APP_CSS
        d = _token_value("--grad-d").lstrip("#")
        r, g, b = int(d[0:2], 16), int(d[2:4], 16), int(d[4:6], 16)
        assert not (r > 200 and 100 < g < 200 and b < 120), "--grad-d всё ещё оранжевый"

    def test_hidden_pause(self):
        assert ".lg-bg-paused" in APP_CSS
        assert "animation-play-state: paused" in APP_CSS
        assert "setBgPaused" in APP_JS
        assert "lg-bg-paused" in APP_JS
        # не заводим второй обработчик — пауза внутри onVisibilityChange.
        assert APP_JS.count("document.addEventListener('visibilitychange'") == 1

    def test_reduced_motion_and_contrast(self):
        assert re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?body::before"
            r"[^}]*animation:\s*none", APP_CSS)
        assert "@media (prefers-contrast: more)" in APP_CSS
