"""W16 — адаптивность узкого вьюпорта (контракт владельца 02.11.2026).

Документ: `plans/owner_inputs/2026-11-02-narrow-viewport-decision.md`.
Пункты контракта и что проверяется здесь (структурная часть):

  §2  эффективная ширина < 320 px (page zoom 200 %, системный шрифт) — reflow,
      а не «не поддерживается»: шапка переключается по ФАКТИЧЕСКОМУ
      переполнению (`_syncHeaderFit`), а не только по ширине окна;
  §3  второстепенное уходит (имя/роль пользователя, имя области, подпись
      счётчика) и остаётся доступным в СУЩЕСТВУЮЩЕМ drawer (профиль);
  §4  никакого нижнего навбара и второго меню; на обычных мобильных размерах
      шапка остаётся однорядной (режим не включается без переполнения);
  §5  шрифты и тач-цели не уменьшаются ради прохождения теста: правила
      плотности не задают `font-size`, иконочные кнопки держат ≥44 px;
  §6  три режима масштаба различаются живым стендом
      (`tools/ui_evol_w15_composition_e2e.py`, секция `adaptive`), который
      читает реальную геометрию: 4 режима × 3 ширины × 5 экранов = 60 ячеек.

Живой reflow, доступность действий, отсутствие обрезки/overflow/наложений и
перестройка раскладки проверяются стендом; здесь — структура, которая этот
контракт удерживает.
"""
import re
from pathlib import Path

ROOT = Path(".")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
TOOL = (ROOT / "tools" / "ui_evol_w15_composition_e2e.py").read_text(
    encoding="utf-8")


def _rule_bodies(selector_substr):
    out = []
    for m in re.finditer(r"([^{}]*)\{([^}]*)\}", CSS):
        if selector_substr in m.group(1):
            out.append((m.group(1).strip(), m.group(2)))
    return out


# ── §2: режим плотности включается фактом переполнения, а не только шириной ─
def test_header_fit_is_measured_not_guessed():
    assert "_syncHeaderFit: function" in APP_JS, \
        "нужен метод, вычисляющий плотность шапки по фактическому переполнению"
    body = APP_JS[APP_JS.index("_syncHeaderFit: function"):]
    body = body[:body.index("\n      },")]
    assert "scrollWidth" in body and "clientWidth" in body, \
        "плотность обязана считаться из реального переполнения шапки"
    assert "data-header-fit" in body, "режим обязан попадать в DOM-атрибут"
    # Порог ниже 320 CSS px (page zoom / WebView) — тоже повод включить режим.
    assert "320" in body, "эффективная ширина < 320 px должна включать reflow"


def test_header_fit_is_wired_to_real_signals():
    """Пересчёт на: ResizeObserver шапки, resize окна, visualViewport, роут."""
    assert "vm._syncHeaderFit" in APP_JS, \
        "ResizeObserver шапки должен пересчитывать плотность (шрифт/зум)"
    assert "_appVm._syncHeaderFit" in APP_JS, \
        "resize/visualViewport должны пересчитывать плотность"
    assert "self._syncHeaderFit" in APP_JS, \
        "после применения маршрута (меняется заголовок) плотность пересчитывается"


# ── §3: второстепенное уходит, критическое остаётся; профиль — в drawer ─────
def test_tight_mode_hides_only_secondary_labels():
    tight = _rule_bodies('[data-header-fit="tight"]')
    assert tight, "нет правил режима tight"
    joined = "\n".join(sel + " {" + body for sel, body in tight)
    for cls in (".header-user-name", ".header-user-role",
                ".scope-trigger .scope-name", ".header-save-chip__label"):
        assert cls in joined, "в режиме tight должен скрываться %s" % cls
    # Критическое (навигация, область, ⛶, заголовок) не скрывается.
    for forbidden in (".header-nav-btn", ".header-fs-btn", ".scope-trigger {",
                      ".header-title-wrap { display: none"):
        assert forbidden not in joined, \
            "режим tight не имеет права скрывать %r" % forbidden
    # §5: плотность не уменьшает шрифты и тач-цели.
    decls = "\n".join(body for _sel, body in tight)
    assert "font-size" not in decls, \
        "режим плотности не уменьшает шрифты (контракт §5)"
    assert "min-height" not in decls, \
        "режим плотности не уменьшает тач-цели (контракт §5)"


def test_drawer_has_profile_block():
    assert "data-drawer-profile" in INDEX, \
        "имя/роль обязаны оставаться доступными в существующем drawer"
    body = " ".join(b for _s, b in _rule_bodies(".sidebar-profile"))
    assert body, "профиль drawer должен быть оформлен существующей системой"


def test_no_second_menu_or_bottom_navbar_added():
    assert ".bottom-nav" not in CSS, "нижний навбар не возвращается (контракт §4)"
    assert "data-bottom-nav" not in INDEX
    # «Ещё»-меню не возвращено: единственная точка fullscreen — существующая.
    assert "data-more-trigger" not in INDEX


# ── §1/§2: сетки не выезжают при эффективной ширине меньше своего пола ──────
def test_grids_clamp_min_track_to_available_width():
    offenders = []
    for sel, body in _rule_bodies("grid-template-columns"):
        for m in re.finditer(r"minmax\(\s*(\d+)px", body):
            if int(m.group(1)) >= 200:
                offenders.append((sel[:50], m.group(0)))
    assert not offenders, ("жёсткий пол трека ≥200 px без min(100%, …): %s"
                           % offenders)


# ── §6: стенд различает три режима масштаба и меряет реальную геометрию ─────
def test_stand_measures_three_scale_modes_separately():
    block = TOOL[TOOL.index("ADAPTIVE_MODES = ("):]
    block = block[:block.index(")\nADAPTIVE_WIDTHS")]
    for mode in ("normal", "pagezoom200", "font200", "telegram_kb"):
        assert '"%s"' % mode in block, "режим масштаба %r не измеряется" % mode
    assert "window.innerWidth" in TOOL, \
        "ширина обязана читаться из браузера, а не вычисляться делением"
    # Клаузы контракта закреплены как отдельные проверки в стенде.
    for marker in ('"hScroll"', '"outsideCount"', '"headerOverlaps"',
                   '"hittable"', '"inVisible"', '"drawerProfile"'):
        assert marker in TOOL, "стенд не проверяет %s" % marker
