"""EVOL-033 (W13, P1) — тач-цели, единая ловушка фокуса и единый портал.

Что проверяется (строка L00478 §A «touch hit area ≥44×44», §A/E.2 «один
механизм overlay/portal и focus management», §4.2 лестница слоёв):

  * у плотных технических примитивов (ключ параметра + «копировать», хлебные
    крошки, пункты дерева промптов, нативные чекбоксы) есть явное расширение
    области нажатия на `pointer: coarse`, при этом десктопная плотность не
    меняется;
  * ловушка Tab реализована ОДИН раз (`_trapTabKey`) и используется палитрой,
    листом записи и drawer — второй копии цикла фокусируемых узлов нет;
  * все оверлеи рендерятся через ОДИН механизм порталов (`<teleport to="body">`),
    полноэкранный редактор — с `:disabled`, чтобы обычный режим не менялся;
  * шапка и тост получили собственные ранги (`--z-header`, тост выше палитры);
  * два дубля текста закрыты: причина «Сердцебиения» выводится один раз,
    у модалки ролей один заголовок (внутренняя секция сохраняет своё имя).

Это СТРУКТУРНЫЙ контракт (разметка/стили/наличие одного хелпера); фактическое
поведение (44×44 hit-тестом, 8/8 и 16/16 Tab, Esc и возврат фокуса, z-index
живого DOM, кадры состояний) измеряется живым стендом
`tools/ui_evol_w13_full_visual_e2e.py`
секции `touch`, `portal`, `defects` и лежит в
`plans/features/evol/audit/evidence/evol-033/`.

Запуск: pytest tests/test_webapp_evol_w13_touch_portal.py
"""
import re
from pathlib import Path

ROOT = Path(".")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

TOUCH_MARK = "EVOL-033 (W13, P1): тач-цели ≥ 44×44"
TOUCH_CSS = CSS[CSS.index(TOUCH_MARK):]


def _coarse_block():
    """Тело `@media (pointer: coarse)` ПОСЛЕ маркера волны (с балансом скобок)."""
    start = TOUCH_CSS.index("@media (pointer: coarse)")
    i = TOUCH_CSS.index("{", start)
    depth = 0
    for j in range(i, len(TOUCH_CSS)):
        if TOUCH_CSS[j] == "{":
            depth += 1
        elif TOUCH_CSS[j] == "}":
            depth -= 1
            if depth == 0:
                return TOUCH_CSS[start:j + 1]
    raise AssertionError("блок @media (pointer: coarse) не закрыт")


def _handler_body(name):
    """Тело метода по имени: от объявления до следующего объявления метода."""
    i = APP_JS.index(name + ": function")
    tail = APP_JS[i + 10:]
    ends = [m.start() for m in re.finditer(r"\n {6}\w+: function", tail)]
    return APP_JS[i:i + (min(ends) if ends else 4000)]


class TestTouchTargets44:
    """§A: touch hit area ≥44×44 без потери десктопной плотности."""

    def test_coarse_block_declares_each_named_primitive(self):
        block = _coarse_block()
        # Ключ параметра и «копировать» — плотная техническая строка.
        assert re.search(r"\.tech-key\s*\{[^}]*min-height:\s*44px", block), \
            "ключ параметра: строка должна получать 44 px на touch"
        assert re.search(r"\.tech-key__value\s*\{[^}]*min-height:\s*44px",
                         block), "значение ключа — 44 px область нажатия"
        assert re.search(r"\.tech-key__copy\s*\{[^}]*min-height:\s*44px",
                         block) and \
            re.search(r"\.tech-key__copy\s*\{[^}]*min-width:\s*44px", block), \
            "кнопка «копировать» — 44×44"
        # Дерево промптов (33 px на 768–1199 до правки).
        assert re.search(r"\.prompt-tree-item\s*\{[^}]*min-height:\s*44px",
                         block), "пункт дерева промптов — 44 px на touch"
        # Нативные чекбоксы: цель — <label class="ctl-check">.
        assert re.search(r"\.ctl-check\s*\{[^}]*min-height:\s*44px", block), \
            "label нативного чекбокса — 44 px"

    def test_breadcrumbs_expand_hit_area_not_header(self):
        block = _coarse_block()
        assert re.search(r"\.breadcrumb-link::after\s*\{[^}]*inset:\s*-16px",
                         block), \
            "крошки расширяют ЗОНУ НАЖАТИЯ, а не высоту шапки"
        # ::after не должен занимать место в потоке (иначе шапка вырастет).
        assert "position: absolute" in block

    def test_desktop_density_not_touched(self):
        """Fine-pointer: правило не применяется — плотность 32–40 px остаётся."""
        assert TOUCH_CSS.index("@media (pointer: coarse)") < \
            TOUCH_CSS.index(".tech-key { min-height: 44px")
        # Обратного правила (min-height 44 вне coarse) в слое волны нет.
        outside = TOUCH_CSS[:TOUCH_CSS.index("@media (pointer: coarse)")]
        assert "min-height: 44px" not in outside

    def test_native_checkbox_labels_marked(self):
        """Три нативных чекбокса вне компонента тумблера получили ctl-check."""
        assert INDEX.count('class="ctl-check flex items-center gap-2') >= 3, \
            "label-обёртки нативных чекбоксов помечены ctl-check"


class TestSingleFocusTrap:
    """§A/E.2: одна ловушка фокуса вместо трёх реализаций."""

    def test_helper_defined_once(self):
        assert APP_JS.count("function _trapTabKey(") == 1
        assert APP_JS.count("function _overlayFocusables(") == 1
        assert APP_JS.count("function _restoreOverlayFocus(") == 1

    def test_list_built_only_inside_helper(self):
        """Второй копии списка фокусируемых узлов нет ни в одном обработчике."""
        # Селектор объявлен ровно один раз — в константе хелпера.
        assert APP_JS.count("var OVERLAY_FOCUSABLE =") == 1
        assert APP_JS.count("querySelectorAll(OVERLAY_FOCUSABLE)") == 1
        # Ни один обработчик не собирает свой список вручную.
        assert APP_JS.count("'button, [href]") == 1, \
            "селектор фокусируемых узлов должен быть только в хелпере"

    def test_three_overlays_use_the_helper(self):
        for name in ("paletteKeydown", "statusRecordKeydown",
                     "drawerOnKeydown", "moreMenuOnKeydown"):
            assert "_trapTabKey(" in _handler_body(name), \
                "%s должен вызывать общую ловушку" % name
        # Возврат фокуса — тоже через общий хелпер.
        for closer in ("closePalette", "closeStatusRecord", "closeDrawer"):
            assert "_restoreOverlayFocus(" in _handler_body(closer), \
                "%s должен возвращать фокус общим хелпером" % closer
        # Первичный фокус — тот же список узлов.
        assert "_focusFirstIn(" in _handler_body("_focusOpenedDialog")


class TestSinglePortalMechanism:
    """§A/E.2: один механизм порталов для оверлеев."""

    def test_overlays_teleport_to_body(self):
        assert INDEX.count('<teleport to="body"') >= 3, \
            "палитра, лист записи и полноэкранный редактор — один механизм"
        assert INDEX.count("<teleport to=\"body\" :disabled=") == 1, \
            "редактор телепортируется ТОЛЬКО в полноэкранном режиме"

    def test_palette_and_sheet_are_inside_teleports(self):
        for anchor, name in (("data-command-palette", "палитра"),
                             ("sfeed-modal-backdrop", "лист записи")):
            pos = INDEX.index(anchor)
            opened = INDEX.rfind('<teleport to="body', 0, pos)
            closed = INDEX.rfind("</teleport>", 0, pos)
            assert opened >= 0, "%s: teleport не найден" % name
            assert opened > closed, \
                "%s должна лежать внутри teleport (портал), а не вне его" % name

    def test_fullscreen_editor_teleport_disabled_by_default(self):
        i = INDEX.index("data-prompt-editor")
        opened = INDEX.rfind('<teleport to="body" :disabled=', 0, i)
        assert opened >= 0, \
            "обычный режим редактора остаётся в сетке (teleport выключен)"
        assert "togglePromptFullscreen()" in INDEX, \
            "переключение — методом (возврат фокуса после переноса DOM)"
        assert "togglePromptFullscreen: function" in APP_JS


class TestZLadderRefinements:
    """§4.2: шапка ниже подложки, тост выше палитры."""

    def test_header_has_own_rank_below_scrim(self):
        m = re.search(r"--z-header:\s*(\d+);", CSS)
        scrim = re.search(r"--z-scrim:\s*(\d+);", CSS)
        nav = re.search(r"--z-nav:\s*(\d+);", CSS)
        assert m and scrim and nav
        assert int(m.group(1)) < int(scrim.group(1)) < int(nav.group(1))
        i = CSS.index("header.header-sticky {")
        assert "z-index: var(--z-header);" in CSS[i:i + 400], \
            "шапка читает собственный ранг"

    def test_toast_above_palette(self):
        toast = int(re.search(r"--z-toast:\s*(\d+);", CSS).group(1))
        palette = int(re.search(r"--z-palette:\s*(\d+);", CSS).group(1))
        dev = int(re.search(r"--z-dev:\s*(\d+);", CSS).group(1))
        assert palette < toast < dev, \
            "уведомление должно быть выше палитры и ниже dev-слоя"


class TestDuplicateTextClosed:
    """Два дубля, найденные ревьюером в кадрах полосы."""

    def test_heartbeat_reason_rendered_once(self):
        body = _handler_body("heartbeat")
        assert "detail: ''" in body, \
            "canvas-путь не дублирует причину в detail"
        assert "reason: this.hbReason" in body
        # Якорь — сама каноническая строка статуса, а не комментарий о ней.
        j = INDEX.index(':data-health-indicator="heartbeatHealth.state"')
        near = INDEX[j:j + 1400]
        assert 'v-if="heartbeat.detail"' in near, \
            "второй рендер причины скрыт, когда detail пуст"
        # legacy-путь OFF-флага сохраняет свой отдельный текст.
        assert "detail: 'нагрузка в норме'" in APP_JS

    def test_roles_modal_has_single_title(self):
        i = INDEX.index('id="acc-roles-title"')
        assert "Роли и права" in INDEX[i - 200:i + 200], \
            "заголовок модалки описывает окно целиком"
        # Внутри секции матрицы имя осталось ровно одно (не дубль заголовка).
        start = INDEX.index('id="sec-matrix"')
        section = INDEX[start:INDEX.index("</div>", start + 4000)]
        assert section.count("Матрица ролей") == 1
