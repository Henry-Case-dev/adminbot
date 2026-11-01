"""ASAP-UI-02 — дельта единого слоя overlay, motion-токенов, Back-stack и
стандарта детального просмотра.

TEST-LIFECYCLE: CONTRACT owner=ASAP-UI-02 §4.2/§10/§11 (§12 п.6/п.7)
  Строки карты: L01848 (один z-index/portal/focus/backdrop), L01854
  (select/combobox), L01950 (единые motion-токены), L01958/L01971 (Back
  закрывает вложенную область), L01843 (один стандарт детального просмотра).

Что здесь проверяется (не «наличие элемента», а инварианты контракта):
  * ранг слоя задаётся ОДНИМ набором токенов, и их порядок совпадает с
    требованиями §4.2 (скрим < панель, dropdown выше шапки/стекла, модалка
    выше dropdown, тост выше модалки, палитра выше модалок, dev — выше всех);
  * за пределами лестницы не остаётся «магических» z-index: любые числовые
    значения допустимы только для декоративного подъёма ВНУТРИ карточки
    (-1/0/1/2), где стек образует сама карточка;
  * стандарт детального просмотра один: окно записи использует ту же
    модалку/лист (`html.w9-sheet-bottom .modal-card`) и тот же ранг скрима,
    что остальные диалоги;
  * движение переходов и лент идёт из одного масштаба `--motion-*`;
  * Back/Esc/BackButton читают ОДИН список слоёв, а не собственные if-чейны.

Запуск: py -3 -m pytest tests/test_webapp_asap_ui02_delta.py -q -p no:randomly
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


CSS = _read(os.path.join("web", "static", "app.css"))
HTML = _read(os.path.join("web", "index.html"))
JS = _read(os.path.join("web", "app.js"))


def _tokens():
    """Все числовые `--z-*` из таблицы стилей (ранг слоя)."""
    out = {}
    for name, val in re.findall(r"--z-([a-z-]+):\s*(\d+);", CSS):
        out[name] = int(val)
    return out


def _rule(body_re):
    """Тело ПЕРВОГО правила, чей селектор матчится регуляркой."""
    m = re.search(body_re + r"\s*\{([^}]*)\}", CSS)
    assert m, "правило не найдено: %s" % body_re
    return m.group(1)


def _decl(selector_re, prop):
    """Последнее объявление свойства во ВСЕХ правилах этого селектора."""
    found = None
    for m in re.finditer(selector_re + r"\s*\{([^}]*)\}", CSS):
        d = re.search(re.escape(prop) + r"\s*:\s*([^;]+);", m.group(1))
        if d:
            found = d.group(1).strip()
    assert found is not None, "%s не задан в правилах %s" % (prop, selector_re)
    return found


# ═══ 1. Одна лестница слоёв (L01848) ═══════════════════════════════════════
def test_single_z_layer_ladder_exists_and_ordered():
    z = _tokens()
    for name in ("base", "content", "inline", "sidebar", "scrim", "nav",
                 "local", "menu", "modal-scrim", "modal", "toast",
                 "palette", "dev", "dev-top"):
        assert name in z, "нет ранга --z-%s в единой лестнице" % name
    # Порядок = смысл слоя. Если кто-то «поправит» одно число, порядок сломается.
    assert z["base"] < z["content"] < z["inline"] < z["sidebar"] < z["scrim"]
    assert z["scrim"] < z["nav"] < z["local"]
    assert z["nav"] < 50 < z["menu"], "dropdown/меню должны быть выше шапки"
    assert z["menu"] < z["modal-scrim"] < z["modal"] < z["toast"]
    assert z["toast"] < z["palette"] < z["dev"] < z["dev-top"]
    # Существующий контракт EVOL-023 не переписан: база dropdown осталась 50.
    assert "--overlay-z: 50;" in CSS, "--overlay-z остаётся базой dropdown"


def test_no_magic_z_index_outside_decorative_in_card():
    """Вне лестницы допустимы только декоративные подъёмы внутри карточки."""
    bad = []
    for m in re.finditer(r"z-index:\s*(-?\d+)\s*;", CSS):
        if int(m.group(1)) not in (-1, 0, 1, 2):
            line = CSS[:m.start()].count("\n") + 1
            bad.append("app.css:%d z-index:%s" % (line, m.group(1)))
    assert not bad, "числовые z-index вне лестницы: %s" % ", ".join(bad)


def test_overlay_surfaces_read_the_ladder():
    expected = [
        (r"\.modal-backdrop", "z-index", "var(--z-modal-scrim)"),
        (r"\.sfeed-modal-backdrop", "z-index", "var(--z-modal-scrim)"),
        (r"\.exec-detail-backdrop", "z-index", "var(--z-modal-scrim)"),
        (r"\.exec-detail", "z-index", "var(--z-modal)"),
        (r"\.app-drawer", "z-index", "var(--z-nav)"),
        (r"header\.header-sticky", "z-index", "var(--z-nav)"),
        (r"\.drawer-backdrop", "z-index", "var(--z-scrim)"),
        (r"\.scope-panel", "z-index", "var(--overlay-z)"),
        (r"\.palette-root", "z-index", "var(--z-palette)"),
        (r"\.toast-wrap", "z-index", "var(--z-toast)"),
    ]
    problems = []
    for sel, prop, want in expected:
        got = _decl(sel, prop)
        if got != want:
            problems.append("%s: %s = %r (ожидалось %r)" % (sel, prop, got, want))
    assert not problems, "; ".join(problems)


def test_dropdown_is_opaque_and_not_clipped():
    """Dropdown читаем и не режется родителем: плотная подложка + свой скролл."""
    body = _rule(r"\.ctl-pop")
    assert "position: fixed" in body, "панель комбобокса — отдельный слой (portal)"
    assert "calc(var(--overlay-z) + 10)" in body
    assert "overflow-y: auto" in body and "overscroll-behavior: contain" in body
    bg = _decl(r"\.ctl-pop", "background-color")
    assert bg == "var(--overlay-bg)"
    # Подложка overlay непрозрачна до читаемости (не «стекло в стекле»).
    m = re.search(r"--overlay-bg:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)", CSS)
    assert m, "--overlay-bg должен быть rgba"
    assert float(m.group(4)) >= 0.9, "подложка dropdown должна быть плотной"


def test_scope_combobox_flip_and_sheet_states():
    """Единственный кастомный комбобокс: flip вверх и лист в тесном низком окне."""
    assert ".scope-panel[data-placement=\"top\"]" in CSS
    assert ".scope-panel[data-placement=\"sheet\"]" in CSS
    sheet = _rule(r"\.scope-panel\[data-placement=\"sheet\"\]")
    assert "position: fixed" in sheet and "bottom: calc(var(--kb-inset)" in sheet
    assert "_ctlPlacePopover" in JS and "setAttribute('data-placement'" in JS


# ═══ 2. Один motion-масштаб для переходов и лент (L01950) ═════════════════
def test_motion_tokens_single_source():
    assert "--dur-fast:var(--motion-fast);" in CSS
    assert "--dur-normal:var(--motion-base);" in CSS
    assert "--dur-slow:var(--motion-slow);" in CSS
    assert "--ease-out:var(--motion-ease);" in CSS
    for token in ("--motion-fast:", "--motion-base:", "--motion-slow:",
                  "--motion-ease:", "--motion-feed-speed:",
                  "--motion-feed-resume:", "--motion-feed-end-hold:",
                  "--motion-feed-rewind:", "--motion-feed-start-hold:"):
        assert token in CSS, "нет токена движения %s" % token


def test_feed_engine_reads_motion_tokens():
    assert "function resolveMotionTokens(" in JS
    assert "var DEFAULTS = resolveMotionTokens(readCssMotionToken, MOTION_FALLBACK);" in JS
    for token in ("--motion-feed-speed", "--motion-feed-resume",
                  "--motion-feed-end-hold", "--motion-feed-rewind",
                  "--motion-feed-start-hold"):
        assert token in JS, "движок лент не читает %s" % token
    # Значение берётся из CSS один раз и используется как единственный DEFAULTS.
    assert JS.count("resolveMotionTokens(") >= 2


# ═══ 3. Один Back-stack (L01958 / L01971) ═════════════════════════════════
def test_back_stack_is_single_source_of_order():
    assert JS.count("function backStackLayers(vm)") == 1
    assert JS.count("function backStackClose(vm)") == 1
    assert re.search(r"escClose: function \(\) \{\s*backStackClose\(this\);", JS), \
        "Esc обязан закрывать верхний слой через единый Back-stack"
    assert "if (backStackClose(this)) return;" in JS, \
        "Back обязан сначала закрывать вложенный слой"
    # Старый рукописный порядок в escClose/goBack не вернулся.
    assert "if (this.drawerOpen) { this.closeDrawer(); return; }" not in JS
    assert "if (this.paletteOpen) { this.closePalette(); return; }" not in JS


def test_back_button_visible_for_nested_layers():
    body = JS[JS.index("syncBackButton: function ()"):]
    body = body[:body.index("// ═══ Material Symbols")]
    assert "backStackLayers().length" in body
    assert "routeDepth(this.route) > 0 || stack > 0" in body, \
        "BackButton обязан быть доступен и при открытом вложенном слое"


# ═══ 4. Один стандарт детального просмотра (L01843) ══════════════════════
def test_record_detail_uses_the_single_dialog_standard():
    assert HTML.count("data-sfeed-modal") == 1, "окно записи объявлено один раз"
    start = HTML.index('v-if="statusRecordOpen"')
    end = HTML.index("</transition>", start)
    block = HTML[start - 200:end]
    assert 'role="dialog"' in block and 'aria-modal="true"' in block
    assert 'aria-labelledby="sfeed-rec-title"' in block
    assert "modal-card" in block, "тот же компонент модалки, а не отдельное окно"
    assert "statusRecordKeydown" in block, "Esc/Tab-ловушка на самом диалоге"
    assert '@click.self="closeStatusRecord()"' in block, "внешний клик закрывает"
    # Мобильный лист — общий стандарт, а не отдельная реализация.
    sheet = _rule(r"html\.w9-sheet-bottom \.modal-card")
    assert "max-height" in sheet and "border-radius: 18px 18px 0 0" in sheet
    # Тот же ранг скрима, что у остальных диалогов (один слой overlay).
    assert _decl(r"\.sfeed-modal-backdrop", "z-index") == "var(--z-modal-scrim)"


def test_record_detail_keeps_same_record_and_separate_dates():
    body = JS[JS.index("_statusRecordFrom: function"):]
    body = body[:body.index("openStatusRecord: function")]
    for key in ("created_at", "event_at", "confirmed_at", "origin", "sources",
                "scope"):
        assert "'%s'" % key in body, "поле %s потеряно в карточке записи" % key
    # Дата записи и дата события — разные поля, одна не подменяет другую.
    assert "graph_facts.created_at" in body
    assert "graph_facts.message_timestamp" in body
    assert "graph_facts.last_confirmed_at" in body
    assert "id: (it.id != null) ? it.id : null" in body, "record_id той же записи"
