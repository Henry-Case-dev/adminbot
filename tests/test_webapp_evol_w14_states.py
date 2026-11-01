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
