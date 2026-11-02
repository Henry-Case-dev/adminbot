"""EVOL-033 (W15, §A/§B/§E.2) — единые компоненты: карточка, строка, таблица, график.

Строка карты **L00478** (`EVOL-033`, слайс `EVOL-UI-FULLDOD`). Что проверяется:

  * одна визуальная роль = один тип компонента (§L01826): карточка/панель,
    компактная строка-сущность, строка таблицы и каркас графика берут радиус,
    границу и ритм из ОДНОЙ группы токенов (`--card-*`, `--row-*`,
    `--table-*`, `--chart-*`), а не из литералов в каждом экране;
  * токены выведены из существующей шкалы (`--radius-*`, `--space-*`,
    `--surface-border`, `--tx-*`) — второго независимого набора переменных нет;
  * у одной роли не остаётся второй альфы границы: материал `[data-glass="b"]`
    не вводит свою кромку поверх карточки;
  * объявленные варианты плотности (паддинг ленты в жёстком слоте 64 px,
    p-2…p-6 у карточек) остаются вариантами ОДНОГО компонента.

**Главный инвариант (ревью 5.3):** ни одно правило класса-роли не задаёт
`border-radius` / `border*` / `padding*` литеральным значением — только через
`var(--…)`. Проверка перебирает ВСЕ правила файла (включая правила, дописанные
в конец), поэтому возвращённый вариант краснеет. Сама проверка проверяется
отдельным тестом на намеренно испорченном CSS (иначе «зелено» ничего не значит).

Это СТРУКТУРНЫЙ контракт. Живая геометрия каждого экземпляра (радиус, альфа
границы, padding, типографика меты, обрезка, h-скролл, тач-цель) измеряется
стендом `tools/ui_evol_w15_composition_e2e.py` на 27 состояниях + 28 маршрутах
§D-7 × 2 вьюпорта; доказательства — `plans/features/evol/audit/evidence/w15-composition/`.

Запуск: pytest tests/test_webapp_evol_w15_composition.py
"""
import re
from pathlib import Path

ROOT = Path(".")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")

ROLE_MARK = "EVOL-033 §A/§E.2 (W15)"

# ── классы-роли: геометрия ОБЯЗАНА идти через токены ───────────────────────
ROLE_CLASSES = {
    # карточка/панель
    "card": (".card", ".module-card", ".hub-card", ".prov-block", ".intel-card",
             ".prompt-module-card", ".speech-card", ".modal-card", ".run-card",
             ".conn-card", ".ep-card", ".story-card"),
    # компактная строка-сущность
    "row": (".sfeed-item", ".mem-item", ".access-section-row",
            ".speech-layer-card", ".ribbon-item"),
    # плотная строка таблицы / ячейка
    "table": (".speech-rule", ".speech-soft", ".speech-hist", ".speech-lesson",
              ".speech-layer-row", ".speech-cap-row", ".speech-trace-row",
              ".speech-block-row", ".speech-skip-row", ".speech-conflict-row",
              ".speech-hier-row", ".speech-limits", ".speech-diff-line",
              ".speech-preview-line", ".mem-kv", ".exp-window", ".funnel-cell"),
    # уведомление/заметка
    "notice": (".access-audit", ".speech-warn"),
}

# Свойства, которые у роли не имеют права быть литералом.
CHECKED = ("border-radius", "border", "border-top", "border-bottom",
           "border-left", "border-right", "padding", "padding-top",
           "padding-bottom", "padding-left", "padding-right")

# Разрешённые литералы: объявленные варианты, которые нельзя выразить токеном
# без потери смысла. Каждая запись — (селектор, свойство, значение, причина).
LITERAL_ALLOW = (
    ("html.w9-sheet-bottom .modal-card", "border-radius", "18px 18px 0 0",
     "верхний радиус мобильного листа — платформенное поведение листа"),
    (".speech-subblock", "border-radius", "0",
     "подраздел с акцентной линией: радиус 0 — это отсутствие радиуса"),
    (".speech-subblock", "padding-left", "10px",
     "отступ от акцентной линии подраздела (не ритм строки)"),
)


def _rules(css):
    """Все пары (селектор, тело, номер строки) с балансом скобок.

    Комментарии заменяются пробелами с сохранением переводов строк: иначе
    селектор склеивается с комментарием и нарушение приписывается чужому
    правилу (проверено на реальном CSS).
    """
    css = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                 css, flags=re.S)
    out = []
    i = 0
    while i < len(css):
        brace = css.find("{", i)
        if brace == -1:
            break
        sel_start = css.rfind("}", 0, brace) + 1
        sel = css[sel_start:brace].strip()
        depth = 0
        j = brace
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = css[brace + 1:j]
        line = css[:sel_start].count("\n") + 1
        out.append((sel, body, line))
        i = j + 1
    return out


def _role_classes(sel):
    """Какие классы-роли упоминает селектор (по границе имени класса)."""
    found = []
    for group in ROLE_CLASSES.values():
        for cls in group:
            if re.search(re.escape(cls) + r"(?![\w-])", sel):
                found.append(cls)
    return found


def _literal_geometry(css):
    """Список нарушений: (строка, селектор, свойство, значение)."""
    bad = []
    allow = {(s, p, v) for (s, p, v, _r) in LITERAL_ALLOW}
    for sel, body, line in _rules(css):
        if sel.startswith("@") or not _role_classes(sel):
            continue
        for decl in body.split(";"):
            d = decl.strip()
            if not d or ":" not in d:
                continue
            prop, val = d.split(":", 1)
            prop = prop.strip().lower()
            val = val.strip()
            if prop not in CHECKED:
                continue
            if "var(" in val:
                continue
            # «нет границы» — это не литерал геометрии
            if val in ("0", "none", "0 0", "unset", "inherit"):
                continue
            if prop.startswith("border") and val.startswith("0 "):
                continue
            if any(sel.strip() == a[0] and prop == a[1] and val == a[2]
                   for a in LITERAL_ALLOW):
                continue
            bad.append((line, sel[:80], prop, val))
    return bad


def _tokens():
    """Тело :root-блока, где объявлена группа W15 (до первого `}`)."""
    i = CSS.index(ROLE_MARK)
    start = CSS.rindex(":root", 0, i)
    end = CSS.index("}", i)
    return CSS[start:end]


def _rules_of(selector, css=CSS):
    pat = re.compile(r"(?m)^\s*" + re.escape(selector) + r"\s*\{")
    out = []
    for m in pat.finditer(css):
        end = css.index("}", m.end())
        out.append(css[m.start():end + 1])
    assert out, "правило %r не найдено" % selector
    return out


def _body(selector, needle, css=CSS):
    bodies = _rules_of(selector, css)
    for b in bodies:
        if needle in b:
            return b
    return max(bodies, key=len)


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
    banned = ("--w15-", "--rg-", "--cmp-", "--ui-kit-", "--ds-")
    for b in banned:
        assert b not in CSS, "параллельный набор переменных %r не нужен" % b


# ── 2. ГЛАВНЫЙ ИНВАРИАНТ: роли без литеральной геометрии ────────────────────
def test_role_classes_have_no_literal_geometry():
    bad = _literal_geometry(CSS)
    assert not bad, ("литеральная геометрия у классов-ролей (нужен var(--…)):\n"
                     + "\n".join("  строка %d: %s { %s: %s }" % b for b in bad))


def test_invariant_catches_reintroduced_variant():
    """Самопроверка инварианта: дописанный литерал обязан краснеть.

    Без этого теста «зелёный инвариант» ничего не доказывает (ревью 5.3:
    структурный тест не ловил возвращённый вариант).
    """
    mutated = CSS + "\n.mem-item { border-radius: 10px; }\n"
    bad = _literal_geometry(mutated)
    assert bad and any("mem-item" in b[1] for b in bad), \
        "инвариант не поймал возвращённый вариант .mem-item"
    mutated2 = CSS + "\n.speech-rule { padding: 8px 10px; }\n"
    bad2 = _literal_geometry(mutated2)
    assert bad2 and any("speech-rule" in b[1] for b in bad2), \
        "инвариант не поймал возвращённый padding .speech-rule"
    mutated3 = CSS + "\n.run-card { border: 1px solid rgba(255,255,255,.1); }\n"
    bad3 = _literal_geometry(mutated3)
    assert bad3 and any("run-card" in b[1] for b in bad3), \
        "инвариант не поймал литеральную границу .run-card"


# ── 3. Точки применения токенов (не только объявление) ──────────────────────
def test_card_uses_role_tokens():
    card = _body(".card", "--card-hairline")
    assert "border: var(--card-hairline)" in card
    assert "border-radius: var(--card-radius)" in card
    assert "1rem" not in card, "литеральный радиус карточки вернулся"


def test_card_panel_variants_use_role_tokens():
    for sel in (".prov-block", ".hub-card", ".run-card", ".ep-card"):
        body = _body(sel, "--card-radius")
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


def test_compact_rows_use_row_tokens():
    for sel in (".mem-item", ".access-section-row", ".sfeed-item",
                ".speech-layer-card"):
        body = _body(sel, "--row-hairline")
        assert "var(--row-radius)" in body, sel
        assert "var(--row-hairline)" in body, sel
    for sel in (".mem-item", ".access-section-row", ".speech-layer-card"):
        body = _body(sel, "--row-pad")
        assert "padding: var(--row-pad)" in body, sel


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


def test_table_like_blocks_use_table_tokens():
    for sel in (".speech-limits", ".mem-kv", ".exp-window", ".funnel-cell"):
        body = _body(sel, "--table-row-radius")
        assert "var(--table-row-radius)" in body, sel
        assert "var(--table-row-pad)" in body, sel


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
