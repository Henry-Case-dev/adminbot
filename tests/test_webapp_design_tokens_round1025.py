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
    "--ok", "--warn", "--err", "--err-text", "--ok-bg", "--warn-bg", "--err-bg",
    "--grad-a", "--grad-b", "--grad-c", "--grad-d",
    "--grad-speed", "--grad-speed-slow", "--grad-angle", "--accent-grad",
    "--glass-bg", "--glass-bg-strong", "--glass-blur", "--glass-border",
    "--glass-displace",
}
EXPECTED_VALUES = {
    "--surface-0": "#090D17", "--surface-1": "#151B2A", "--surface-2": "#1C2537",
    "--text-1": "#F4F7FB", "--text-2": "#AAB6C8", "--text-3": "#A2B0C6",
    "--teal-500": "#42D6C4", "--purple-500": "#A78BFA", "--indigo-300": "#77A8FF",
    "--warn": "#F6C56F", "--err": "#F07178", "--err-text": "#FCA5A5",
    "--grad-a": "#42D6C4", "--grad-b": "#77A8FF", "--grad-c": "#A78BFA",
    "--grad-d": "#5C7CFA",
    "--glass-bg": "rgba(21, 27, 42, 0.5)",
    "--glass-bg-strong": "rgba(21, 27, 42, 0.85)",
}

# D5 (симметрия, итерация @Reviewer): полный набор токенов дизайн-системы.
# Сравниваем множество фактических токенов семейств с эталоном → ловим и
# пропажи, и ЛИШНИЕ маркеры (напр. забытый --grad-old / --glass-foo).
INVENTORY_PREFIXES = ("--surface-", "--text-", "--grad-", "--glass-",
                      "--teal-", "--purple-", "--indigo-", "--magenta-",
                      "--lilac-")
INVENTORY_STATUS = {"--ok", "--warn", "--err", "--err-text", "--ok-bg",
                    "--warn-bg", "--err-bg"}
INVENTORY_TOKENS = {
    "--surface-0", "--surface-1", "--surface-2", "--surface-3",
    "--surface-border", "--surface-glass",
    "--text-1", "--text-2", "--text-3",
    "--grad-a", "--grad-b", "--grad-c", "--grad-d", "--grad-angle",
    "--grad-ease", "--grad-speed", "--grad-speed-slow",
    "--glass-bg", "--glass-bg-strong", "--glass-blur", "--glass-border",
    "--glass-border-color", "--glass-displace", "--glass-highlight",
    "--glass-highlight-soft", "--glass-shadow",
    # HOTFIX10 (ADR-1025-18 D1): тема frosted-слоя GlassSurface — тёмная
    # paper/ink вместо белого дефолта vendored-библиотеки.
    "--glass-paper", "--glass-ink",
    "--teal-500", "--teal-600", "--purple-400", "--purple-500", "--indigo-300",
    "--magenta-400", "--magenta-600", "--lilac-200",
} | INVENTORY_STATUS
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


def _rgb(h: str) -> list:
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _over(fg: list, a: float, bg: list) -> list:
    return [round(fg[i] * a + bg[i] * (1 - a)) for i in range(3)]


def _lum_rgb(rgb: list) -> float:
    def f(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_rgb(a: list, b: list) -> float:
    l1, l2 = _lum_rgb(a), _lum_rgb(b)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ═══════════════════════ T-2550: inventory-множество ═══════════════════════
class TestInventory:
    def test_expected_tokens_present(self):
        """Presence: каждый маркер присутствует (сравнение множеств, не in)."""
        missing = EXPECTED_TOKENS - _tokens(APP_CSS)
        assert not missing, f"потеряны токены-маркеры: {sorted(missing)}"

    def test_inventory_symmetric_difference(self):
        """D5/@Reviewer: симметрия — ловим и пропажи, и ЛИШНИЕ маркеры."""
        actual = {t for t in _tokens(APP_CSS)
                  if t.startswith(INVENTORY_PREFIXES) or t in INVENTORY_STATUS}
        extra = sorted(actual - INVENTORY_TOKENS)
        missing = sorted(INVENTORY_TOKENS - actual)
        assert not extra and not missing, (
            "лишние маркеры: %s; пропавшие: %s" % (extra, missing))

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
        # HOTFIX10 (10.25) — bump 2.58.12 → 2.58.13 (ADR-1025-18, T-2864).
        assert m.group(1) == "2.58.29", f"APP_VERSION = {m.group(1)} (ожидалось 2.58.29)"


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
        fgs = {"--text-1": "#F4F7FB", "--text-2": "#AAB6C8", "--text-3": "#A2B0C6"}
        fails = []
        for fn, fv in fgs.items():
            for sn, sv in surfaces.items():
                ratio = _contrast(fv, sv)
                if ratio < 4.5:
                    fails.append((fn, sn, round(ratio, 2)))
        assert not fails, f"контраст ниже 4.5:1: {fails}"

    def test_contrast_on_glass_effective_bg(self):
        """D4/@Reviewer: текст читаем на эффективном фоне стекла
        (--glass-bg alpha .5 поверх анимированного wash §10 alpha .42 поверх
        surface-0). Берём САМЫЙ СВЕТЛЫЙ фон фазы — худший контраст."""
        s0 = _rgb("#090D17")
        glass = _rgb("#151B2A")
        wash = ["#42D6C4", "#77A8FF", "#5C7CFA", "#A78BFA"]
        effs = [_over(glass, 0.5, _over(_rgb(w), 0.42, s0)) for w in wash]
        light = max(effs, key=_lum_rgb)
        fails = []
        for name, fg in (("--text-1", "#F4F7FB"), ("--text-2", "#AAB6C8"),
                         ("--text-3", "#A2B0C6"), ("--warn", "#F6C56F"),
                         ("--ok", "#3DD68C")):
            ratio = _contrast_rgb(_rgb(fg), light)
            if ratio < 4.5:
                fails.append((name, round(ratio, 2)))
        assert not fails, f"на стекле ниже 4.5:1: {fails}"

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


# ═══════ D-1/@Reviewer: Tailwind-утилиты 12px в стекле ≥4.5:1 ═══════
class TestUtilityColorsOnGlass:
    CLASSES = {".text-gray-500": "--text-3", ".text-gray-600": "--text-3",
               ".text-gray-400": "--text-2", ".text-red-400": "--err-text"}

    @staticmethod
    def _glass_worst() -> list:
        s0 = _rgb("#090D17")
        glass = _rgb("#151B2A")
        wash = ["#42D6C4", "#77A8FF", "#5C7CFA", "#A78BFA"]
        return max([_over(glass, 0.5, _over(_rgb(w), 0.42, s0)) for w in wash],
                   key=_lum_rgb)

    def test_utilities_overridden_to_tokens(self):
        for cls, tok in self.CLASSES.items():
            pat = (re.escape(cls) + r"\s*(?:,[^{]*)?\{[^}]*color:\s*var\("
                   + re.escape(tok) + r"\)")
            assert re.search(pat, APP_CSS), (cls, tok)

    def test_overrides_win_over_tailwind_order(self):
        # app.css подключается ПОСЛЕ tailwind.css (index.html) → равная
        # специфичность, наше правило выигрывает.
        assert INDEX.index("/static/app.css") > INDEX.index("tailwind.css")

    def test_utilities_pass_on_worst_glass(self):
        light = self._glass_worst()
        fails = []
        for cls, tok in self.CLASSES.items():
            fg = _rgb(_token_value(tok))
            ratio = _contrast_rgb(fg, light)
            if ratio < 4.5:
                fails.append((cls, tok, round(ratio, 2)))
        assert not fails, f"утилиты на стекле <4.5:1: {fails}"

    def test_old_tailwind_values_would_fail(self):
        # Доказательство необходимости правки: исходные Tailwind-цвета <4.5:1.
        light = self._glass_worst()
        for name, rgb in ((".text-gray-500", _rgb("#6B7280")),
                          (".text-red-400", _rgb("#F87171"))):
            assert _contrast_rgb(rgb, light) < 4.5, name


# ═══════════ T-2538…T-2543: Liquid Glass A/B/C, allow/deny ═══════════
class TestLiquidGlassV2:
    def test_single_inline_svg_filter(self):
        assert INDEX.count('id="lg-lens"') == 1, "должен быть ОДИН фильтр #lg-lens"
        assert "feDisplacementMap" in INDEX
        assert "feTurbulence" in INDEX and "feGaussianBlur" in INDEX
        # CSP/zero-build: без внешних ссылок/data-URI на фильтр.
        assert "lg-lens" in INDEX.split("filter id=")[1][:2000]
        assert 'href="http' not in INDEX.split("lg-lens")[0][-400:]

    def test_level_a_opt_in_only(self):
        # A (AMEND ADR-1025-12 D1): преломление на ФОРГРАУНД-линзе ::before через
        # токен --glass-displace; backdrop несёт только blur (без url()).
        base = re.search(r'\[data-glass="a"\]\s*\{([^}]*)\}', APP_CSS)
        assert base, "нет базового правила [data-glass=\"a\"]"
        assert "var(--glass-blur)" in base.group(1)
        assert "url(#lg-lens)" not in base.group(1), "url() НЕ на backdrop"
        m = re.search(r'\[data-glass="a"\]::before\s*\{([^}]*)\}', APP_CSS)
        assert m, "нет foreground-линзы [data-glass=\"a\"]::before"
        body = m.group(1)
        assert "var(--glass-displace)" in body
        assert "radial-gradient" in body and "mask-image" in body
        assert "z-index: -1" in body
        assert _token_value("--glass-displace").startswith("url(#lg-lens")

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
        # §9: нигде не опираемся на backdrop url-фильтр (grep-инвариант).
        assert not re.search(r"backdrop-filter\s*:\s*url\(", APP_CSS)
        assert "backdrop-filter: url(" not in APP_CSS

    def test_no_animated_blur(self):
        # T-2541: никакой animation по filter/backdrop-filter на viewport-слоях.
        assert not re.search(r"animation:[^;}]*(backdrop-)?filter", APP_CSS)

    def test_glass_js_reconcile(self):
        assert "reconcileLiquidGlass" in APP_JS
        assert "_liquidGlassSupported" in APP_JS
        # T-2585: перф-кап заменил min-240.
        assert "_lensMaxNodes" in APP_JS
        assert "data-glass-tier" in APP_JS and "data-glass-reason" in APP_JS
        assert 'data-glass="a"' in INDEX
        assert "getBoundingClientRect" in APP_JS

    def test_downgrade_reversible_and_transitive(self):
        """@Reviewer: обратимое понижение A↔B + транзитивность (observer)."""
        # JS не переписывает opt-in data-glass, а ведёт data-glass-downgraded.
        assert "data-glass-downgraded" in APP_JS
        assert "setAttribute('data-glass', 'b')" not in APP_JS
        assert "removeAttribute('data-glass-downgraded')" in APP_JS
        # CSS-профиль понижения + транзитивность после смены вкладки/маршрута.
        assert '[data-glass="a"][data-glass-downgraded="1"]' in APP_CSS
        assert "_initLiquidGlassObserver" in APP_JS
        assert "MutationObserver" in APP_JS
        assert "$nextTick" in APP_JS

    def test_feature_detect_tier(self):
        """AMEND ADR-1025-12 D1: tier — feature-detect filter:url(#lg-lens),
        БЕЗ UA-gate Blink-only (WKWebView/iOS-Edge учитываются честно)."""
        assert "css.supports('filter', 'url(#lg-lens)')" in APP_JS
        assert "AppleWebKit" not in APP_JS

    def test_glass_approximation_documented(self):
        """@Reviewer: приближение карты смещения зафиксировано (не выдаётся за оптику)."""
        assert "ДОКУМЕНТИРОВАННОЕ" in INDEX and "ПРИБЛИЖЕНИЕ" in INDEX
        assert "feTurbulence" in INDEX and "feGaussianBlur" in INDEX
        # усиление у краёв — CSS radial-mask линзы, а не равномерный шум
        assert "radial-gradient(ellipse at center" in APP_CSS
        assert "inset 0 1px 0 var(--glass-highlight)" in APP_CSS


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


# ═══════ T-2554/@Reviewer: сам F2-чекер матрицы (min-сторона, диапазоны) ═══════
class TestMatrixF2Probe:
    @staticmethod
    def _checker():
        # ленивый импорт: модуль харнесса делает os.chdir(REPO) на импорте.
        from tools.ui_round1025_matrix import _f2_failures
        return _f2_failures

    def _base(self) -> dict:
        return {
            "tokens": {"s0": "#090D17", "s1": "#151B2A", "teal": "#42D6C4",
                       "warn": "#F6C56F", "err": "#F07178", "errText": "#FCA5A5",
                       "gs": "75s", "gss": "105s",
                       "glassBg": "rgba(21, 27, 42, 0.5)",
                       "displace": "url(#lg-lens)"},
            "beforeAnim": "grad-spin",
            "beforeDur": "75s, 105s",
            "hasLensFilter": True,
            "allow": [{"minSide": 120, "tier": "a", "reason": "auto",
                       "downgraded": False}],
            "utility": "rgb(162, 176, 198)",  # --text-3
            "denyCount": 1, "denyBf": "none",
            "panels": {"header": {"bf": "blur(16px) saturate(140%)"}},
            "overflow": False,
        }

    def test_compliant_probe_passes(self):
        assert self._checker()(self._base(), "t") == []

    def test_catches_missing_tier_marker(self):
        # reconcile не отработал → нет data-glass-tier.
        p = self._base()
        p["allow"] = [{"minSide": 120, "tier": "", "reason": "",
                       "downgraded": False}]
        fails = self._checker()(p, "320x700")
        assert any("data-glass-tier" in f for f in fails), fails

    def test_catches_all_downgraded(self):
        # Ни один узел не получил A (напр. feature-detect сломан) → FAIL.
        p = self._base()
        p["allow"] = [{"minSide": 120, "tier": "b",
                       "reason": "filter-unsupported", "downgraded": True}]
        fails = self._checker()(p, "t")
        assert any("tier A" in f for f in fails), fails

    def test_catches_panel_without_blur(self):
        # A2: стеклянная панель без backdrop-filter → FAIL.
        p = self._base()
        p["panels"] = {"bottomNav": {"bf": "none"}}
        fails = self._checker()(p, "t")
        assert any("panel bottomNav" in f for f in fails), fails

    def test_catches_low_contrast_utility(self):
        # orig Tailwind .text-gray-500 rgb(107,114,128) на стекле → ~2.4:1.
        p = self._base()
        p["utility"] = "rgb(107, 114, 128)"
        fails = self._checker()(p, "t")
        assert any("D-1" in f for f in fails), fails

    def test_catches_out_of_range_duration(self):
        p = self._base()
        p["beforeDur"] = "6s"
        fails = self._checker()(p, "t")
        assert any("60,90" in f for f in fails), fails
