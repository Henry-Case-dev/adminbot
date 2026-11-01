"""EVOL-033 (W15, §A/§B/§C/§E.2) — единые компоненты: карточка, строка, таблица, график.

Строка карты **L00478** (`EVOL-033`, слайс `EVOL-UI-FULLDOD`). Что проверяется:

  * одна визуальная роль = один тип компонента (§L01826): карточка/панель,
    компактная строка-сущность, строка таблицы и каркас графика берут радиус,
    границу и ритм из ОДНОЙ группы токенов (`--card-*`, `--row-*`,
    `--table-*`, `--chart-*`), а не из литералов в каждом экране;
  * токены выведены из существующей шкалы (`--radius-*`, `--space-*`,
    `--surface-border`, `--tx-*`) — второго независимого набора переменных нет
    (§A: «не должны создавать второй независимый набор CSS-переменных»);
  * у одной роли не остаётся второй альфы границы: материал `[data-glass="b"]`
    не вводит свою кромку поверх карточки;
  * объявленные варианты плотности (паддинг ленты в жёстком слоте 64 px,
    p-2/p-3/p-4/p-5 у карточек) остаются вариантами ОДНОГО компонента.

Это СТРУКТУРНЫЙ контракт (стили/токены). Фактическая геометрия каждого
экземпляра на 22 состояниях × 2 вьюпортах (радиус, альфа границы, padding,
типографика меты, отсутствие обрезки и горизонтального скролла, тач-цель
строки ≥44 px) измеряется живым стендом
`tools/ui_evol_w15_composition_e2e.py`; доказательства (JSON «до/после» и
кадры) лежат в `plans/features/evol/audit/evidence/w15-composition/`.

Запуск: pytest tests/test_webapp_evol_w15_composition.py
"""
import re
from pathlib import Path

ROOT = Path(".")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")

ROLE_MARK = "EVOL-033 §A/§E.2 (W15)"


def _rules(selector, css=CSS):
    """ВСЕ тела правил по точному селектору в начале строки.

    Строгий якорь нужен, чтобы `.card` не совпал с `.module-card`,
    `.card-solid` или `html.w9-sheet-bottom .modal-card`.
    """
    out = []
    pat = re.compile(r"(?m)^\s*" + re.escape(selector) + r"\s*\{")
    for m in pat.finditer(css):
        start = m.start()
        end = css.index("}", m.end())
        out.append(css[start:end + 1])
    assert out, "правило %r не найдено" % selector
    return out


def _body(selector, needle):
    """Тело правила, содержащее `needle` (иначе — самое длинное тело)."""
    bodies = _rules(selector)
    for b in bodies:
        if needle in b:
            return b
    return max(bodies, key=len)


def _tokens():
    """Тело :root-блока, где объявлена группа W15 (до первого `}`)."""
    i = CSS.index(ROLE_MARK)
    start = CSS.rindex(":root", 0, i)
    end = CSS.index("}", i)
    return CSS[start:end]


# ── 1. Токены объявлены и выведены из существующей шкалы ────────────────────
def test_surface_tokens_declared_from_existing_scale():
    body = _tokens()
    expect = {
        "--card-radius": "var(--radius-xl)",
        "--card-hairline": "1px solid var(--surface-border)",
        "--card-pad": "var(--space-4)",
        "--row-radius": "var(--radius-md)",
        "--row-hairline": "1px solid var(--surface-border)",
        "--row-pad": "var(--space-2) var(--space-3)",
        "--row-gap": "var(--space-1)",
        "--table-row-radius": "var(--radius-md)",
        "--table-hairline": "1px solid var(--surface-border)",
        "--table-row-pad": "var(--space-2) var(--space-3)",
        "--chart-title-size": "var(--tx-small)",
        "--chart-meta-size": "var(--tx-tiny)",
        "--chart-legend-gap": "var(--space-1)",
    }
    for name, value in expect.items():
        assert "%s: %s" % (name, value) in body, \
            "%s должен ссылаться на существующую шкалу (%s)" % (name, value)


def test_no_second_variable_set():
    """Новых `--rg-*`/`--cmp-*` и прочих параллельных наборов не появилось."""
    body = _tokens()
    banned = ("--w15-", "--rg-", "--cmp-", "--ui-kit-", "--ds-")
    for b in banned:
        assert b not in CSS, "параллельный набор переменных %r не нужен" % b


# ── 2. Карточка/панель: один радиус и одна hairline ─────────────────────────
def test_card_uses_role_tokens():
    card = _body(".card", "--card-hairline")
    assert "border: var(--card-hairline)" in card
    assert "border-radius: var(--card-radius)" in card
    assert "1rem" not in card, "литеральный радиус карточки вернулся"


def test_card_panel_variants_use_role_tokens():
    for sel in (".prov-block", ".hub-card"):
        body = _body(sel, "--card-radius")
        assert "var(--card-hairline)" in body, sel
        assert "var(--card-radius)" in body, sel
    hub = _body(".hub-card", "--card-pad")
    assert "padding: var(--card-pad)" in hub, \
        ".hub-card должен брать ритм из токена (было 14.4 px)"
    assert "var(--glass-border)" not in hub


def test_modal_card_radius_from_role_token():
    body = _body(".modal-card", "--card-radius")
    assert "border-radius: var(--card-radius)" in body
    assert "var(--radius-lg)" not in body


def test_glass_material_b_does_not_override_hairline():
    """Иначе один и тот же `.card` на разных экранах имел 0.14 и 0.16 альфу."""
    i = CSS.index('[data-glass="b"] {')
    body = CSS[i:CSS.index("}", i) + 1]
    assert "border: var(--card-hairline)" in body
    assert "border: var(--glass-border)" not in body


# ── 3. Компактная строка-сущность ───────────────────────────────────────────
def test_compact_rows_use_row_tokens():
    for sel in (".mem-item", ".access-section-row", ".sfeed-item"):
        body = _body(sel, "--row-hairline")
        assert "var(--row-radius)" in body, sel
        assert "var(--row-hairline)" in body, sel
    for sel in (".mem-item", ".access-section-row"):
        body = _body(sel, "--row-pad")
        assert "padding: var(--row-pad)" in body, sel
        assert "10px" not in body, "%s: литералы 10 px вернулись" % sel


def test_compact_row_keeps_touch_target():
    body = (_body(".mem-item", "--control-h-touch")
            + _body(".access-section-row", "--control-h-touch"))
    assert "var(--control-h-touch)" in body


def test_dossier_ticker_row_aligned_with_feeds():
    body = _body(".dossier-ticker__track--y .dossier-ticker__item", "--row-radius")
    assert "var(--row-radius)" in body
    assert "var(--row-font)" in body


# ── 4. Строка таблицы / инспектора ──────────────────────────────────────────
def test_dense_rows_use_table_tokens():
    i = CSS.index(".speech-rule,")
    body = CSS[i:CSS.index("}", i) + 1]
    assert "var(--table-row-radius)" in body
    assert "var(--table-hairline)" in body
    assert "var(--table-row-pad)" in body
    assert "rgba(148, 163, 184, .18)" not in body


def test_matrix_mobile_rows_use_table_tokens():
    body = _body(".matrix-table tr", "--table-row-radius")
    assert "var(--table-row-radius)" in body
    assert "var(--table-hairline)" in body


# ── 5. Каркас графика: одна типографика меты/заголовка ──────────────────────
def test_chart_tokens_are_declared():
    body = _tokens()
    assert "--chart-title-size" in body
    assert "--chart-meta-size" in body
    assert "--chart-legend-gap" in body
