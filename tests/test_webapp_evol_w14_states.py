"""W14 (ASAP-UI-02 §12, строка L00478) - состояния контролов, загрузка.

Источник требований: `plans/current_task.md` §3 (единая визуальная система),
§4 (`E.2` один тип компонента на визуальную роль, `E.3` состояния контролов и
честный loading), §12 п.8/п.15; строка карты L00478.

Что проверяется здесь (структура реальных файлов, не подстановка флагов):

  * `E.2` чекбоксы: **каждый** `input[type=checkbox]` в `web/index.html`
    оформлен дизайн-системой — `ctl-check__box` либо внутри
    `.ctl-toggle`/`.ctl-check`. Раньше 24 «голых» чекбокса жили с размерами
    13/15/16/22 px и разными акцентами (замер ревью W13 §2.1);
  * `E.3` pressed/selected: у кнопок семейства `.btn*`/`.ctl-btn` есть
    состояние нажатия, а `[aria-pressed="true"]`/`[aria-selected="true"]`
    отличаются заливкой и hairline, а не только цветом текста;
  * `E.3` загрузка: `#app` несёт `aria-busy`, статический индикатор
    `[data-boot-loading]` виден до готовности оболочки и снимается классом
    `app-ready`; `app.js` действительно переключает `aria-busy` на реальной
    загрузке конфига (`_setAppBusy`) и снимает индикатор в `finally`.

Живая проверка тех же контрактов - `tools/ui_evol_s12_scenarios_e2e.py`
(§12.8 контролы на трёх экранах, §12.15 клавиатура/zoom, остаточные
`loading`/`interactions`).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


def _checkbox_inputs():
    """Все объявления `<input type="checkbox" ...>` с их классом и позицией."""
    out = []
    for m in re.finditer(r"<input\b[^>]*type=\"checkbox\"[^>]*>", INDEX,
                         re.S):
        tag = m.group(0)
        cls = re.search(r"class=\"([^\"]*)\"", tag)
        out.append((m.start(), cls.group(1) if cls else ""))
    return out


class TestUnifiedCheckboxes:
    def test_every_native_checkbox_is_a_design_system_control(self):
        """E.2: ни одного «голого» чекбокса со своим размером/акцентом."""
        items = _checkbox_inputs()
        assert len(items) >= 20, (
            "регресс теста: чекбоксы перестали находиться (%d)" % len(items))
        raw = []
        for pos, cls in items:
            classes = cls.split()
            if "ctl-check__box" in classes:
                continue
            # Внутри `.ctl-toggle`/`.ctl-check`: ближайшее объявление
            # контрола-контейнера выше по разметке (sr-only input тумблера).
            window = INDEX[max(0, pos - 900):pos]
            if "ctl-toggle" in window or "ctl-check" in window:
                continue
            raw.append((pos, cls))
        assert not raw, "нативные чекбоксы вне дизайн-системы: %s" % raw[:5]

    def test_self_diag_matrix_uses_design_system_checkbox(self):
        """SELF-DIAG-01 D6: чекбоксы ролей в матрице «Самодиагностики» — контрол
        дизайн-системы (`ctl-check__box`), а не нативный input. Семантика
        (RBAC/диагностическая политика, `diagToggleRole`) не меняется."""
        start = INDEX.index("data-self-diag-action=")
        block = INDEX[start:INDEX.index("</label>", start)]
        assert '<input type="checkbox"' in block
        tag = block[block.index('<input type="checkbox"'):]
        tag = tag[:tag.index(">")]
        assert 'class="ctl-check__box"' in tag, tag
        assert ":disabled=" in tag and "@change=" in tag

    def test_checkbox_box_style_uses_system_tokens(self):
        """Размер/акцент/кольцо фокуса — из токенов, а не локальные значения."""
        rest = CSS[CSS.index("input[type=\"checkbox\"].ctl-check__box"):]
        block = rest[:rest.index(":focus-visible")]
        assert "width: 18px" in block and "height: 18px" in block
        assert "accent-color: var(--purple-400)" in block
        focus = rest[rest.index(":focus-visible"):]
        focus = focus[:focus.index("}")]
        assert "outline: 2px solid var(--focus-ring)" in focus
        disabled = rest[rest.index(":disabled"):]
        disabled = disabled[:disabled.index("}")]
        assert "opacity" in disabled, "disabled отличается от обычного"


class TestControlStates:
    def test_buttons_have_pressed_state(self):
        """E.3: нажатие читается, а не только hover."""
        block = CSS[CSS.index("W14. Единые интерактивные состояния"):]
        block = block[:block.index("/* ── W14. Первичная загрузка")]
        assert ".btn:active:not(:disabled)" in block
        assert ".ctl-btn:active:not(:disabled)" in block
        assert ".module-filter-btn:active" in block
        assert "prefers-reduced-motion: reduce" in block, \
            "нажатие остаётся видимым при reduced-motion, но без скачка"

    def test_selected_state_is_not_color_only(self):
        """Выбранное состояние: заливка + hairline, а не только оттенок."""
        block = CSS[CSS.index("W14. Единые интерактивные состояния"):]
        block = block[:block.index("/* ── W14. Первичная загрузка")]
        assert '[aria-pressed="true"]' in block
        assert '[aria-selected="true"]' in block
        assert "box-shadow: inset 0 0 0 var(--ctl-hairline)" in block


class TestOverlayBacking:
    """§12.7: текст заднего слоя не читается через открытое меню."""

    def test_floating_popovers_use_opaque_working_surface(self):
        block = CSS[CSS.index("W14-fix (§12.7"):]
        block = block[:block.index("/* Подпись управляющего элемента")]
        assert "background-color: var(--surface-2" in block, \
            "popover обязан иметь непрозрачную рабочую поверхность"
        assert "backdrop-filter: none" in block
        # Механизм overlay-контракта остаётся: бордюр/радиус/тень — из токенов.
        assert "var(--overlay-border)" in CSS
        for sel in (".scope-panel", ".scope-tech-body", ".more-menu-panel"):
            assert sel in block, "нет правила для %s" % sel

    def test_palette_keeps_its_opaque_surface(self):
        # Палитра была непрозрачной раньше — контракт тот же, не разъезжается.
        block = CSS[CSS.index(".palette-panel {"):]
        block = block[:block.index("}")]
        assert "var(--surface-2" in block


class TestWideHeaderNoClipping:
    """§C/§12.15: шапка не обрезает контролы ни на zoom, ни с черновиком."""

    def test_save_chip_lives_in_scope_row(self):
        start = INDEX.index('<div class="header-scope-row">')
        # Находим ПАРНЫЙ закрывающий тег строки области подсчётом вложенности,
        # иначе срез обрывается на первом же вложенном </div>.
        depth = 0
        i = start
        end = None
        for m in re.finditer(r"<div\b|</div>", INDEX[start:]):
            if m.group(0) == "</div>":
                depth -= 1
                if depth == 0:
                    end = start + m.start()
                    break
            else:
                depth += 1
        assert end, "не найден конец строки области"
        inside = INDEX[start:end]
        assert "header-save-chip" in inside, \
            "счётчик черновика обязан переноситься вместе со строкой области"

    def test_mobile_scope_row_may_wrap(self):
        block = CSS[CSS.index(".app-shell.shell-mobile header.header-sticky.header-compact-v2\n    .header-scope-row"):]
        block = block[:block.index("}")]
        assert "flex-wrap: wrap" in block

    def test_under_320_header_wraps_instead_of_clipping(self):
        block = CSS[CSS.index("@media (max-width: 319px)"):]
        block = block[:block.index("/* ── W14-fix (§12.7")]
        assert "flex-wrap: wrap" in block
        assert "flex: 1 1 100%" in block, \
            "строка области уходит на свою строку вместо обрезки"


class TestHeartbeatTransientStates:
    """§12.21: transient и намеренно выключенное — не авария."""

    def test_sample_flags_transient_and_stopped(self):
        assert "sample.botStarting" in APP_JS
        assert "sample.botStopped" in APP_JS
        assert "bot.state === 'starting'" in APP_JS
        assert "'stopped'" in APP_JS and "'disabled'" in APP_JS

    def test_transition_returns_honest_states(self):
        block = APP_JS[APP_JS.index("_heartbeatTransition: function"):]
        block = block[:block.index("heartbeatSample: function")]
        assert "state: 'disabled'" in block
        assert "бот остановлен" in block
        assert "state: 'unknown'" in block and "бот запускается" in block

    def test_heartbeat_state_mapping(self):
        block = APP_JS[APP_JS.index("function healthSubsystemState"):]
        block = block[:block.index("if (id === 'experience')")]
        assert "if (hb === 'disabled') return 'disabled';" in block


class TestFullscreenSaveBar:
    """§12.15 (блокер Re-check 2): полоса сохранения в полноэкранном редакторе.

    Дефект: панель оставалась в `main.scroll-area` ПОД оверлеем
    (`position: fixed; z-index: var(--z-modal)`), поэтому «Сохранить» и
    «Отмена» были недоступны — `elementFromPoint` возвращал TEXTAREA.
    """

    def test_save_bar_is_teleported_into_fullscreen_layer(self):
        marker = '<teleport to="body" :disabled="!promptEditorFull">'
        assert marker in INDEX
        blocks = []
        start = 0
        while True:
            i = INDEX.find(marker, start)
            if i < 0:
                break
            blocks.append(INDEX[i:i + 700])
            start = i + 1
        assert any("<sticky-save" in b for b in blocks), \
            "та же панель (без второй копии) обязана переезжать в слой диалога"

    def test_teleported_bar_sits_above_overlay_and_keyboard(self):
        block = CSS[CSS.index("body > .sticky-save[data-save-panel]"):]
        block = block[:block.index("}")]
        assert "position: fixed" in block
        assert "z-index: calc(var(--z-modal) + 1)" in block, \
            "панель обязана быть выше оверлея редактора"
        assert "bottom: calc(var(--kb-inset" in block, \
            "панель обязана стоять над экранной клавиатурой"

    def test_fullscreen_editor_has_scroll_reserve(self):
        assert ".prompt-editor--full { scroll-padding-bottom: 92px; }" in CSS


class TestLeakCriterion:
    """§12.7: критерий просвечивания обязан ловить исходный дефект."""

    def test_criterion_is_strict(self):
        tool = (ROOT / "tools" / "ui_evol_s12_scenarios_e2e.py").read_text(
            encoding="utf-8")
        block = tool[tool.index("def _fails_leak"):]
        block = block[:block.index("def s7_overlay")]
        assert 'stats["max"] <= 3' in block, "порог утечки ослаблен"
        assert 'stats["shareOver2"] <= 0.004' in block, \
            "доля контрастных пикселей не ограничена"
        assert 'sharpShare"] <= 0.002' not in block, \
            "вернулась прежняя мягкая формулировка (max<=60 + контуры)"

    def test_negative_fixture_exists_and_runs(self):
        tool = (ROOT / "tools" / "ui_evol_s12_scenarios_e2e.py").read_text(
            encoding="utf-8")
        assert "def leak_mutation_check" in tool, \
            "нет негативной фикстуры alpha 0.94"
        assert "rgba(23, 28, 42, 0.94)" in tool
        assert 'report["residual"]["leakMutation"]' in tool, \
            "фикстура не подключена к прогону"


class TestLoadingState:
    def test_boot_indicator_exists_and_is_accessible(self):
        """E.3: до готовности оболочки видно загрузку, а не пустой экран."""
        assert "data-boot-loading" in INDEX
        splash = INDEX[INDEX.index("data-boot-loading"):]
        splash = splash[:splash.index("</div>\n  </div>")]
        assert 'role="status"' in splash
        assert 'aria-live="polite"' in splash
        assert 'aria-busy="true"' in splash
        assert splash.count("ctl-skeleton") >= 2, "скелетон, а не один спиннер"

    def test_app_root_reports_busy(self):
        """`aria-busy` живёт на корне приложения и снимается после загрузки."""
        assert re.search(r'<div id="app"[^>]*aria-busy="true"', INDEX)
        assert "function _setAppBusy" in APP_JS
        assert "function _markAppReady" in APP_JS
        assert "_setAppBusy(true)" in APP_JS
        assert "_setAppBusy(false)" in APP_JS
        assert "_markAppReady();" in APP_JS
        # Индикатор снимается по ЗАВЕРШЕНИИ загрузки (в том числе при ошибке
        # или пустом ответе) — иначе экран залип бы на скелетоне.
        body = APP_JS[APP_JS.index("loadConfig: async function"):]
        body = body[:body.index("itemMatchesSource")]
        assert "if (!this.configLoading) _markAppReady();" in body

    def test_boot_splash_hidden_by_ready_class(self):
        assert "body.app-ready .boot-splash" in CSS
        assert "display: none" in CSS[
            CSS.index("body.app-ready .boot-splash"):][:120]

    def test_catalog_and_palette_expose_busy(self):
        """Каталог модулей и палитра честно сообщают о загрузке."""
        assert ":aria-busy=\"catalogLoading ? 'true' : 'false'\"" in INDEX
        assert ":aria-busy=\"configLoading ? 'true' : 'false'\"" in INDEX
        assert "catalogLoading: function ()" in APP_JS
        assert "paletteLoading: function ()" in APP_JS
        assert "data-module-loading" in INDEX
        assert "data-palette-loading" in INDEX
