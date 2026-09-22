"""UPD3 (T-1939) — каскад/состояние-ориентированные тесты UI-rework.

Корень провала 10.20 — string-presence проверки («строка есть в файле»).
Здесь CSS **парсится по селекторам** и резолвится каскад реальной цепочки
классов (специфичность + порядок исходника), а не ищется подстрока.

Покрытие:
  * дефект 1 — Liquid Glass: токены, glass-set, отсутствие solid-override;
  * дефект 2 — Grid: тройка правил + ветка «ИИ» (prov-grid, без max-w-3xl);
  * дефект 4 — градиент: оранжевый токен, скорость 5–8 s, reduced-motion;
  * дефект 5 — sticky-save: sticky/bottom/safe-area + отсутствие inline
    max-height у `.modal-body`;
  * T-1903 — снимок навигации (меню НЕ изменено).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


# ═════════════════════════ мини-CSS-парсер ═════════════════════════════════
def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _iter_rules(css: str):
    """Yield (context, selector, body) для всех правил; @media/@supports
    раскрываются, контекст сохраняется. @keyframes/@font-face/@property —
    пропускаются (это не селекторные правила)."""
    text = _strip_comments(css)
    out = []

    def walk(chunk: str, context: str):
        i, n = 0, len(chunk)
        while i < n:
            open_idx = chunk.find("{", i)
            if open_idx < 0:
                break
            prelude = chunk[i:open_idx].strip()
            depth, j = 1, open_idx + 1
            while j < n and depth > 0:
                c = chunk[j]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            body = chunk[open_idx + 1:j - 1]
            if prelude.startswith("@"):
                at = prelude.split()[0]
                if at in ("@media", "@supports"):
                    walk(body, (context + " " + prelude).strip())
                # @keyframes/@font-face/@property/@charset — вне селекторов
            else:
                for sel in prelude.split(","):
                    sel = " ".join(sel.split())
                    if sel:
                        out.append((context, sel, body))
            i = j

    walk(text, "")
    return out


RULES = _iter_rules(CSS)


def _parse_decls(body: str) -> dict:
    decls = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        decls[key.strip().lower()] = " ".join(value.split())
    return decls


def _rules_for(selector: str, top_level_only: bool = True):
    """Все правила, где селектор встречается ровно как указанная строка."""
    return [
        (ctx, body, _parse_decls(body))
        for ctx, sel, body in RULES
        if sel == selector and (not top_level_only or ctx == "")
    ]


def _last_rule_for(selector: str, top_level_only: bool = True):
    found = _rules_for(selector, top_level_only=top_level_only)
    assert found, f"нет CSS-правила для селектора {selector!r}"
    return found[-1]


def _tokens() -> dict:
    """Значения CSS-переменных из :root."""
    ctx, body, decls = _last_rule_for(":root")
    return {k: v for k, v in decls.items() if k.startswith("--")}


def _token(name: str) -> str:
    toks = _tokens()
    assert name in toks, f"нет токена {name}"
    return toks[name]


def _bg_decls(decls: dict) -> str:
    """Эффективный фон правила: background-color, иначе background."""
    return decls.get("background-color") or decls.get("background") or ""


def _specificity(sel: str):
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+", sel))
    classes += len(re.findall(r"(?<!:):(?!:)[\w-]+", sel))  # pseudo-classes
    elements = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel))
    return (ids, classes, elements)


def _match_compound(sel: str, classes, tag=None) -> bool:
    """Сопоставляет ПРОСТОЙ (без комбинаторов) селектор элементу."""
    if any(ch in sel for ch in (" ", ">", "+", "~", "[", "*")):
        return False
    m = re.match(r"^(?P<el>[a-zA-Z][\w-]*)?(?P<rest>.*)$", sel)
    el, rest = m.group("el"), m.group("rest")
    if el and tag and el.lower() != tag.lower():
        return False
    sel_classes = re.findall(r"\.([\w-]+)", rest)
    if not all(c in classes for c in sel_classes):
        return False
    return bool(sel_classes or el)


def _resolve(classes, prop: str, tag=None):
    """Победитель каскада для простого элемента с classes. Возвращает
    (value, selector, key), где key = (specificity, order); или
    (None, None, None)."""
    winner = (None, None, None)
    for order, (ctx, sel, body) in enumerate(RULES):
        if ctx != "":
            continue
        if not _match_compound(sel, classes, tag=tag):
            continue
        decls = _parse_decls(body)
        value = decls.get(prop)
        if value is None and prop == "background-color":
            value = decls.get("background")   # shorthand-фолбэк
        if value is None:
            continue
        key = (_specificity(sel), order)
        if winner[2] is None or key > winner[2]:
            winner = (value, sel, key)
    return winner


GLASS_SET = [
    ".card", ".modal-card", ".module-card", ".hub-card", ".prov-block",
    "details.advanced", ".scope-panel", ".glass-panel", ".oversight-panel",
]
LOOSE_ALPHA_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\.?\d+)\s*\)")


def _is_opaque(bg: str) -> bool:
    """Непрозрачный фон (alpha >= .8) — «кирпич»."""
    if not bg:
        return False
    m = LOOSE_ALPHA_RE.search(bg)
    if m:
        return float(m.group(4)) >= 0.8
    if bg.startswith("#") or bg.startswith("rgb("):
        return True
    return False


# ═════════════════════════════ T-1903 снимок ══════════════════════════════
class TestNavigationSnapshot:
    EXPECTED_TABS = [
        "llm_providers", "prompts",
        "mod_summary", "mod_direct", "mod_factcheck", "mod_search",
        "mod_transcribe", "mod_video_summary", "mod_media_download", "mod_web",
        "mod_checkup", "mod_sleep", "mod_nostalgia", "mod_budgets",
        "mod_images",
        "modules", "memory_rag", "smart_cache", "people_names", "relations",
        "permsoc", "access", "chat_lore", "status", "info", "oversight",
    ]

    def test_tabs_ids_and_order_unchanged(self):
        start = APP_JS.index("var TABS = [")
        end = APP_JS.index("var LEVELS =", start)
        ids = re.findall(r"\{ id: '([a-z_0-9]+)'", APP_JS[start:end])
        assert ids == self.EXPECTED_TABS

    def test_navbar_and_modules_unchanged(self):
        for nid in ["status", "how", "modules", "ai", "permsoc", "access"]:
            assert "'" + nid + "'" in APP_JS
        mods = re.findall(r"\{ id: '(mod_[a-z_]+)',",
                          APP_JS[APP_JS.index("var MODULES = ["):])
        assert len(mods) == 13


# ═══════════════════════════ Дефект 1: стекло ═════════════════════════════
class TestLiquidGlass:
    def test_tokens_exact(self):
        # F2/T-2538: значения §9 на палитре §8 (surface-1 #151B2A = rgb 21,27,42).
        assert _token("--glass-bg").replace(" ", "") == "rgba(21,27,42,0.5)"
        assert _token("--glass-blur").replace(" ", "") == "blur(16px)"
        assert _token("--glass-bg-strong").replace(" ", "") == "rgba(21,27,42,0.85)"
        assert _token("--glass-border-color").replace(" ", "") == \
            "rgba(170,182,200,0.16)"

    def test_each_glass_selector_carries_glass(self):
        for sel in GLASS_SET:
            classes = re.findall(r"\.([\w-]+)", sel)
            el = sel.split(".")[0]
            tag = el if el else "div"
            bg, bsel, _ = _resolve(classes, "background-color", tag=tag)
            assert bg is not None and "var(--glass-bg)" in bg, (sel, bsel, bg)
            blur, _, _ = _resolve(classes, "backdrop-filter", tag=tag)
            wblur, _, _ = _resolve(classes, "-webkit-backdrop-filter", tag=tag)
            assert blur is not None and "var(--glass-blur)" in blur, (sel, blur)
            assert wblur is not None and "var(--glass-blur)" in wblur, (sel, wblur)

    def test_cascade_modal_card_chain(self):
        """Реальная цепочка class="modal-card card …" → glass."""
        value, sel, _ = _resolve(["modal-card", "card"], "background-color",
                                 tag="div")
        assert value is not None and "var(--glass-bg)" in value, (sel, value)
        blur, bsel, _ = _resolve(["modal-card", "card"], "backdrop-filter",
                                 tag="div")
        assert blur is not None and "var(--glass-blur)" in blur, (bsel, blur)
        wblur, _, _ = _resolve(["modal-card", "card"],
                               "-webkit-backdrop-filter", tag="div")
        assert wblur is not None and "var(--glass-blur)" in wblur

    def test_cascade_beats_card_solid(self):
        """Даже при наличии card-solid стекло выигрывает по порядку."""
        value, sel, _ = _resolve(["card", "card-solid"], "background-color",
                                 tag="div")
        assert value is not None and "var(--glass-bg)" in value, (sel, value)

    def test_no_opaque_override_after_glass_rule(self):
        """После glass-правила нет opaque background для glass-селекторов."""
        order_of = {}
        for order, (ctx, sel, body) in enumerate(RULES):
            if ctx == "" and sel in GLASS_SET:
                order_of.setdefault(sel, order)
        glass_order = min(order_of.values())
        for order, (ctx, sel, body) in enumerate(RULES):
            if ctx != "" or order <= glass_order or sel not in GLASS_SET:
                continue
            decls = _parse_decls(body)
            bg = _bg_decls(decls)
            assert not _is_opaque(bg), (
                f"{sel} @order {order}: opaque override ({bg!r})")
            # условные медиа (reduced-motion) не считаем override

    def test_grid_containers_are_transparent(self):
        for sel in (".module-list", ".hub-grid", ".prov-grid"):
            _, body, _ = _last_rule_for(sel)
            decls = _parse_decls(body)
            assert "transparent" in _bg_decls(decls), (sel, decls)
            assert decls.get("border") in ("0", "none"), (sel, decls)
            assert decls.get("backdrop-filter") in ("none", "transparent"), \
                (sel, decls)

    def test_no_card_solid_on_modals(self):
        assert "modal-card card card-solid" not in INDEX
        # G1.3: card-solid остаётся только у header-sticky и scope-panel.
        assert INDEX.count("card-solid") == 2, INDEX.count("card-solid")
        assert 'main-header header-sticky card-solid' in INDEX
        assert 'scope-panel card-solid' in INDEX

    def test_supports_not_fallback_uses_strong(self):
        found = False
        for ctx, sel, body in RULES:
            if "not" in ctx and "backdrop-filter" in ctx and sel in GLASS_SET:
                decls = _parse_decls(body)
                assert "var(--glass-bg-strong)" in _bg_decls(decls), (sel, decls)
                found = True
        assert found, "нет @supports not (backdrop-filter) фолбэка"

    def test_modal_backdrop_blur_token(self):
        rules = _rules_for(".modal-backdrop")
        joined = " ".join(b for _, b, _ in rules)
        assert "var(--glass-blur)" in joined or "blur(16px)" in joined

    def test_no_tailwind_bg_on_glass_nodes(self):
        bad = re.compile(
            r'class="[^"]*\b(?:modal-card|prov-block|hub-card|card)\b[^"]*'
            r'\bbg-(?:\[|[a-z])')
        assert not bad.search(INDEX), bad.search(INDEX).group(0)


# ═══════════════════════════ Дефект 2: Grid ═══════════════════════════════
class TestGrid:
    def test_grid_triple(self):
        for sel in (".prov-grid", ".module-list", ".hub-grid"):
            _, body, _ = _last_rule_for(sel)
            decls = _parse_decls(body)
            assert decls.get("display") == "grid", (sel, decls)
            assert decls.get("grid-template-columns") == \
                "repeat(auto-fit, minmax(320px, 1fr))", (sel, decls)
            assert decls.get("gap") == "1rem", (sel, decls)

    def test_llm_providers_branch_uses_prov_grid(self):
        start = INDEX.index("activeTab === 'llm_providers'")
        # первый контейнер ветки (до секции prov-block)
        chunk = INDEX[start:start + 1200]
        assert "prov-grid" in chunk, "ветка ИИ без prov-grid"
        assert "max-w-3xl" not in INDEX, "max-w-3xl всё ещё в разметке"

    def test_mobile_single_column(self):
        found = False
        for ctx, sel, body in RULES:
            if "(max-width: 479px)" in ctx and sel in (
                    ".prov-grid", ".module-list", ".hub-grid"):
                decls = _parse_decls(body)
                assert decls.get("grid-template-columns") == "1fr", (sel, decls)
                found = True
        assert found, "нет мобильного 1fr-правила"


# ═══════════════════════════ Дефект 4: градиент ═══════════════════════════
class TestGradient:
    def test_no_orange_token(self):
        # F2/T-2545: --grad-d больше не оранжевый (§10 — приглушённый синий).
        assert _token("--grad-d").upper() == "#5C7CFA"

    def test_speed_in_range(self):
        # F2/T-2544: основной цикл §10 — 60–90 c; вторичный — 90–120 c.
        raw = _token("--grad-speed")
        m = re.match(r"^([\d.]+)s$", raw)
        assert m, raw
        assert 60.0 <= float(m.group(1)) <= 90.0, raw
        raw2 = _token("--grad-speed-slow")
        m2 = re.match(r"^([\d.]+)s$", raw2)
        assert m2, raw2
        assert 90.0 <= float(m2.group(1)) <= 120.0, raw2

    def test_orange_in_stops_and_wash(self):
        band = [b for ctx, sel, b in RULES
                if sel == ".grad-band" and ctx == "" and "conic-gradient" in b]
        assert band, "нет conic-gradient у .grad-band"
        assert "var(--grad-d)" in band[-1]
        # HOTFIX8 (ADR-1025-16 D3): REVISE фона §10 — `body::before` теперь
        # aurora/mesh (radial-gradient blob, палитра §8/§10 без оранжевого),
        # прежний conic page-wash сохранён как legacy-фолбэк
        # (UI_AURORA_BG_ENABLED=OFF → `html.bg-wash-legacy body::before`).
        wash = [b for ctx, sel, b in RULES
                if sel == "body::before" and ctx == ""]
        assert wash, "нет правила body::before"
        assert "radial-gradient" in wash[-1], "aurora: radial blob-слои"
        assert "var(--surface-0)" in wash[-1], "aurora: подложка surface-0"
        # оранжевого стопа в aurora-слое нет
        assert "#FF8A3D" not in wash[-1]
        legacy = [b for ctx, sel, b in RULES
                  if sel == "html.bg-wash-legacy body::before"]
        assert legacy and "conic-gradient" in legacy[-1], \
            "net legacy conic page-wash (UI_AURORA_BG_ENABLED=OFF)"
        assert re.search(r"opacity:\s*\.3", legacy[-1] + " ") or \
            re.search(r"opacity:\s*0\.3", legacy[-1]), legacy[-1]

    def test_reduced_motion_and_contrast_kept(self):
        assert "@media (prefers-reduced-motion: reduce)" in CSS
        assert "@media (prefers-contrast: more)" in CSS
        # анимация wash гасится
        assert re.search(r"body::before[^}]*animation:\s*none", CSS), \
            "reduced-motion не гасит body::before"


# ═══════════════════════════ Дефект 5: sticky ═════════════════════════════
class TestStickySave:
    def test_sticky_rule(self):
        _, body, _ = _last_rule_for(".sticky-save")
        decls = _parse_decls(body)
        assert decls.get("position") == "sticky", decls
        assert decls.get("bottom") == "0", decls
        assert "var(--glass-bg-strong)" in _bg_decls(decls), decls
        assert "safe-area-inset-bottom" in decls.get("padding-bottom", ""), decls
        assert decls.get("margin") == "0", decls

    def test_sticky_h_token(self):
        m = re.match(r"^([\d.]+)rem$", _token("--sticky-save-h"))
        assert m and float(m.group(1)) == 4.5

    def test_modal_scroller(self):
        _, body, _ = _last_rule_for(".modal-body")
        decls = _parse_decls(body)
        assert decls.get("overflow-y") == "auto", decls
        assert "scroll-padding-bottom" in decls, decls
        _, cbody, _ = _last_rule_for(".modal-card")
        cdecls = _parse_decls(cbody)
        assert cdecls.get("display") == "flex", cdecls
        assert cdecls.get("flex-direction") == "column", cdecls
        assert "max-height" in cdecls and "46rem" in cdecls["max-height"], cdecls

    def test_scroll_area_reserve(self):
        joined = "\n".join(b for _, b, _ in _rules_for(".scroll-area"))
        assert "scroll-padding-bottom" in joined or ":has(" in CSS
        assert ":has(> .sticky-save)" in CSS
        assert "@supports not (selector(:has(*)))" in CSS

    def test_scroll_area_has_no_padding_bottom_shift(self):
        """M-1: `padding-bottom` на скролл-контейнере сужает content-box, и
        `position:sticky; bottom:0` прижимается к нему (панель «висела» на
        88px выше низа). У вкладки-скроллера остаётся только
        `scroll-padding-bottom`; запас снизу — спейсер, не padding."""
        found = _rules_for(".scroll-area:has(> .sticky-save)",
                           top_level_only=False)
        assert found, "нет правила .scroll-area:has(> .sticky-save)"
        _, _, decls = found[-1]
        assert "scroll-padding-bottom" in decls, decls
        # Допустим только `padding-bottom: 0` (снятие fullscreen-паддинга);
        # любое ненулевое значение снова смещает sticky-панель вверх.
        assert decls.get("padding-bottom") in (None, "0", "0px"), \
            "M-1: padding-bottom контейнера не должен резервировать место"
        # Фолбэк без :has() тоже не должен возвращать padding-bottom (L-3).
        fallbacks = [(ctx, b) for ctx, sel, b in RULES
                     if sel == ".scroll-area" and "@supports not" in ctx]
        assert fallbacks, "нет @supports-фолбэка для .scroll-area"
        for _, fb in fallbacks:
            assert "padding-bottom" not in _parse_decls(fb), \
                "M-1/L-3: фолбэк не должен задавать padding-bottom"

    def test_sticky_spacer_reserves_space(self):
        """M-1: место над панелью резервирует спейсер в потоке (перед
        панелью), чтобы контент не уходил под неё, а панель не отрывалась
        от низа скролл-порта."""
        _, _, decls = _last_rule_for(".sticky-spacer", top_level_only=False)
        assert "height" in decls, decls
        assert "var(--sticky-save-h)" in decls["height"], decls
        assert INDEX.count('class="sticky-spacer') >= 2, \
            "нет спейсера в обеих scroll-area-ветках (config/access)"
        assert re.search(
            r'<div class="sticky-spacer[^"]*"[^>]*></div>\s*<sticky-save',
            INDEX), "спейсер обязан стоять непосредственно перед <sticky-save>"

    def test_no_inline_max_height(self):
        assert "max-height:80dvh" not in INDEX
        assert "max-height:70dvh" not in INDEX

    def test_panel_inside_modal_body_markup(self):
        # sticky-save не должен стоять в .modal-footer
        for m in re.finditer(r'<footer class="modal-footer[^"]*">(.*?)</footer>',
                             INDEX, flags=re.S):
            assert "<sticky-save" not in m.group(1), "sticky-save в footer"
        # досье-футер перенесён внутрь .modal-body
        assert INDEX.count("<sticky-save") >= 3
        # панель в каждой ветке (config/modules/access) — S10.20-1
        config = INDEX[INDEX.index("currentTabIsConfig"):
                       INDEX.index("activeTab === 'modules'")]
        modules = INDEX[INDEX.index("activeTab === 'modules'"):
                        INDEX.index("activeTab === 'oversight'")]
        access = INDEX[INDEX.index("activeTab === 'access'"):
                       INDEX.index("activeTab === 'relations'")]
        for name, block in (("config", config), ("modules", modules),
                            ("access", access)):
            assert "<sticky-save" in block, f"нет панели в ветке {name}"

    def test_footer_static_defensive_rule(self):
        assert ".modal-footer > .sticky-save" in CSS
        _, body, _ = _last_rule_for(".modal-footer > .sticky-save",
                                    top_level_only=False)
        assert _parse_decls(body).get("position") == "static"
