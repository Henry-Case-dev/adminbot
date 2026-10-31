"""EVOL-043/044/045 (W11) — единая система контролов, клавиатура, прогресс.

Что проверяется (plans/current_task.md L690–739):

  * EVOL-043: ОДИН контракт контрола. Размеры/типографика/radius/hairline/
    акцент/движение читаются только из токенов `--ctl-*`/`--motion-*`; у
    одинаковой роли не появляется второй визуальной реализации (градиент
    primary остаётся один — у `.btn-accent`); фокус-контракт описан один раз
    и покрывает legacy-классы, а не 28 разных правил по компонентам;
  * EVOL-044: клавиатура. Ни одного хардкода высоты клавиатуры/устройства;
    оверлеи/листы считаются от реальной видимой области (`--vv-h`/`--kb-inset`),
    а не от `100vh`; поле в фокусе прокручивается, а не переставляется;
    длинный промпт получает внутренний скролл и опцию переноса строк;
  * EVOL-045: прогресс. Determinate — только от пары done/total, ширина не
    «проигрывается с нуля» на каждом рендере (нет бесконечной анимации заливки),
    unknown/stale/error видны, аномалии не скрываются; пульс — только у
    подтверждённого heartbeat; reduced-motion отключает декоративное движение.

Структурные проверки НЕ заменяют живой прогон
`tools/ui_evol_w11_controls_e2e.py` (Chromium 390/768/1280: клавиатура,
flip оверлея, состояния прогресса).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
TOOL = ROOT / "tools" / "ui_evol_w11_controls_e2e.py"
AUDIT = ROOT / "plans" / "features" / "evol" / "audit" / "w11-controls.md"

MARK = "EVOL-043/044/045 (W11)"
W11 = CSS[CSS.index(MARK):]        # слой этой волны — от маркера до конца файла


def _rule(selector, source=None):
    """Тело ПЕРВОГО правила ровно для этого селектора (в слое W11)."""
    src = W11 if source is None else source
    matches = re.findall(
        re.escape(selector) + r"\s*\{([^}]*)\}", src)
    assert matches, "в слое W11 нет правила %r" % selector
    return matches[0]


def _node(*args):
    out = subprocess.run(["node"] + [str(a) for a in args], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8")
    return out


# ═══ EVOL-043: единый контракт контрола ════════════════════════════════════

class TestControlTokens:
    def test_tokens_are_single_source(self):
        """Все роли берут значения из `--ctl-*` в ОДНОМ :root (не вторая палитра)."""
        for token in ("--ctl-h-sm", "--ctl-h", "--ctl-h-lg", "--ctl-h-touch",
                      "--ctl-radius", "--ctl-radius-sm", "--ctl-hairline",
                      "--ctl-font", "--ctl-font-sm", "--ctl-font-mono",
                      "--ctl-gap", "--ctl-accent", "--ctl-disabled-opacity",
                      "--motion-fast", "--motion-base", "--motion-slow",
                      "--motion-ease", "--ctl-progress-h",
                      "--ctl-progress-radius", "--kb-inset"):
            assert CSS.count(token + ":") == 1, (
                "%s должен быть объявлен ровно один раз (единый источник)" % token)
        # Размеры контролов не дублируются числами: h = существующий control-h.
        assert "--ctl-h: var(--control-h);" in CSS
        assert "--ctl-h-touch: var(--control-h-touch);" in CSS
        assert "--kb-inset: var(--kb-offset, 0px);" in CSS, \
            "EVOL-044: --kb-inset — алиас существующего --kb-offset (нет 2-го канала)"

    def test_button_contract(self):
        body = _rule(".ctl-btn")
        assert "min-height: var(--ctl-h)" in body
        assert "border-radius: var(--ctl-radius)" in body
        assert "font-size: var(--ctl-font)" in body
        assert "border: var(--ctl-hairline) solid transparent" in body
        # Один рецепт градиента: primary не объявляет свой фон.
        primary = _rule(".ctl-btn--primary")
        assert "background-image" not in primary and "gradient" not in primary, \
            "primary не заводит вторую реализацию акцента (она у .btn-accent)"
        assert ".btn-accent" in "".join(re.findall(r"[^\n]*btn-accent[^\n]*", W11))

    def test_one_role_one_component(self):
        """Компоненты роли объявлены по одному разу и с токенами."""
        assert "min-height: var(--ctl-h-touch)" in _rule(".ctl-toggle")
        assert "min-height: var(--ctl-h-sm)" in _rule(".ctl-seg__btn")
        assert "min-height: var(--ctl-h-touch)" in _rule(".ctl-check")
        assert "min-height: var(--ctl-h-touch)" in _rule(".ctl-menu__item")
        # Оформление контроля не использует «магические» размеры шрифта/радиуса.
        assert not re.search(r"\bfont-size:\s*[0-9.]+\s*(?:px|rem)", W11), \
            "в системе контролов размеры шрифта — только через токены"
        assert not re.search(r"\bborder-radius:\s*[0-9.]+\s*(?:px|rem)", W11), \
            "радиусы — только через токены"

    def test_focus_contract_is_single(self):
        """Один список — одно поведение фокуса, включая legacy-контролы."""
        assert "--focus-ring: 2px solid var(--indigo-300);" in CSS
        block = W11[W11.index(".btn-accent:focus-visible,"):]
        block = block[:block.index("}")]
        for sel in (".btn-ghost:focus-visible", ".btn-danger:focus-visible",
                    ".ctl-btn:focus-visible", ".field:focus-visible",
                    ".ctl-toggle:focus-within", ".ctl-seg__btn:focus-visible",
                    ".module-toggle:focus-within"):
            assert sel in block, "фокус-контракт пропускает %s" % sel
        assert "outline: var(--focus-ring);" in block
        assert "outline-offset: var(--focus-ring-offset);" in block

    def test_disabled_is_explained_not_silent(self):
        assert ".ctl-disabled-reason" in W11, \
            "disabled/read-only объясняется текстом, а не только прозрачностью"
        assert "cursor: not-allowed" in _rule(
            '.ctl-btn:disabled, .ctl-btn[aria-disabled="true"],\n'
            '.ctl-control:disabled, .ctl-control[aria-disabled="true"]')

    def test_toggle_pending_is_not_success(self):
        body = W11[W11.index('.ctl-toggle[data-state="pending"]'):]
        body = body[:body.index("}")]
        assert "cursor: progress" in body
        assert "background" not in body, \
            "pending не рисует включённое состояние (ожидание ≠ успех)"
        err = W11[W11.index('.ctl-toggle[data-state="error"]'):]
        err = err[:err.index("}")]
        assert "--err" in err, "ошибка возврата значения видна статически"

    def test_danger_needs_words(self):
        assert ".ctl-danger-note" in W11
        assert "font-weight: 400" in _rule(".ctl-danger-note")


# ═══ EVOL-043/044: оверлей, меню, поля ═════════════════════════════════════

class TestOverlayAndFields:
    def test_portal_above_glass(self):
        body = _rule(".ctl-pop")
        assert "z-index: calc(var(--overlay-z) + 10)" in body, \
            "оверлей выше всех glass-слоёв"
        assert "position: fixed" in body
        assert 'data-placement="top"' in W11
        assert 'data-placement="sheet"' in W11
        assert ".scope-panel[data-placement=\"top\"]" in W11, \
            "flip применяется к реальной панели области, а не только к новым"

    def test_mobile_sheet_above_keyboard(self):
        body = _rule(".ctl-sheet")
        assert "var(--vv-h" in body and "var(--kb-inset)" in body
        assert "max-height" in body
        assert "padding-bottom: var(--ctl-safe-bottom)" in body

    def test_editor_scrolls_internally(self):
        body = _rule(".ctl-editor-area")
        assert "overflow-y: auto" in body
        assert "var(--kb-inset)" in body
        assert "dvh" in body
        assert "overscroll-behavior: contain" in body
        nowrap = _rule('.ctl-textarea[data-nowrap="1"]')
        assert "white-space: pre" in nowrap and "overflow-x: auto" in nowrap, \
            "no-wrap прокручивает ВНУТРИ поля, а не растягивает страницу"

    def test_mono_only_for_code_and_prompts(self):
        assert "textarea.field { font-family: inherit; }" in CSS, \
            "EVOL-043: mono не навязывается каждому описанию"
        mono = re.search(r"textarea\.field\.mono,[\s\S]{0,400}?\{[^}]*\}", CSS)
        assert mono, "нет списка промптов/кода для mono"
        block = mono.group(0)
        for sel in ("[data-prompt-textarea]", "[data-cfg-key]",
                    "[data-cover-style-instruction]", ".speech-editor"):
            assert sel in block, "mono не покрывает %s" % sel

    def test_sticky_actions_use_real_keyboard(self):
        """Действия сохранения — существующий sticky-save; не липнут без места."""
        assert "html.kb-tight .sticky-save" in W11, \
            "при нехватке места над клавиатурой панель не «висит» вечно"
        assert "position: static" in W11[W11.index("html.kb-tight .sticky-save"):
                                        W11.index("html.kb-tight .sticky-save") + 200]
        assert ".ctl-sticky-actions" not in W11, \
            "второго компонента панели действий не заводим"

    def test_card_joints_have_one_hairline(self):
        stack = _rule(".ctl-stack > * + *")
        assert "border-top-color: transparent" in stack, \
            "двойной контур на стыке убирается на источнике (граница), без масок"
        assert "::before" not in stack and "::after" not in stack, \
            "маскирующих псевдоэлементов поверх стыка нет"


# ═══ EVOL-044: клавиатура в JS ═════════════════════════════════════════════

class TestKeyboardAdapter:
    def _block(self, start, stop, src=APP_JS):
        i = src.index(start)
        j = src.index(stop, i + 1)
        return src[i:j]

    def test_platform_signals_only(self):
        block = self._block("function _ctlViewportMetrics", "function _ctlPlacePopover")
        assert "window.visualViewport" in block
        assert "Telegram" in block and "viewportHeight" in block, \
            "TMA viewport API учитывается, когда visualViewport непригоден"
        assert "window.innerHeight" in block, "layout viewport — последний фолбэк"
        assert not re.search(r"\b3[0-9]{2}\b", block.split("keyboard")[0].split("}")[0]), \
            "нет хардкода высоты клавиатуры"

    def test_apply_metrics_sets_observable_contract(self):
        block = self._block("function _ctlApplyKeyboardMetrics",
                            "// round 10.26 (ADR-1026-3 D1/D4)")
        assert "setProperty('--kb-offset'" in block
        assert "setProperty('--vv-h'" in block
        assert "classList.add('kb-open')" in block
        assert "classList.remove('kb-open')" in block
        assert "removeProperty('--vv-h')" in block, \
            "--vv-h снимается, когда клавиатуры нет (TMA-высота не подменяется)"
        assert "_ctlRevealFocusedField" in block

    def test_field_is_scrolled_not_moved(self):
        block = self._block("function _ctlRevealFocusedField", "// Применение уже полученных")
        assert "getBoundingClientRect" in block
        assert "scrollTop" in block
        assert "appendChild" not in block and "innerHTML" not in block, \
            "поле не пересоздаётся (каретка/IME/черновик сохраняются)"
        assert "delta" in block

    def test_no_extra_timers_or_animation_loops(self):
        region = self._block("function _ctlViewportMetrics",
                             "// round 10.26 (ADR-1026-3 D1/D4)")
        assert "setInterval" not in region, "никаких собственных интервалов"
        assert "requestAnimationFrame" not in region, "нет нового rAF-цикла поверх фона"

    def test_sync_keyboard_uses_single_source(self):
        block = self._block("_syncKeyboardOffset: function", "_ctlViewport: function")
        assert "_ctlViewportMetrics()" in block
        assert "window.visualViewport" not in block, \
            "чтение visualViewport живёт в одном месте, а не в двух реализациях"

    def test_scope_panel_gets_placement(self):
        block = self._block("positionScopePanel: function", "closeScope: function")
        assert "_ctlPlacePopover" in block
        assert "setAttribute('data-placement'" in block

    def test_keyboard_js_units(self):
        out = _node("tests/js/evol_w11_controls_test.js")
        assert "EVOL-W11-CONTROLS-OK" in (out.stdout or ""), \
            (out.stdout or "") + (out.stderr or "")


# ═══ EVOL-045: достоверный прогресс и движение ════════════════════════════

class TestHonestProgress:
    def test_determinate_has_no_infinite_animation(self):
        fill = _rule(".ctl-progress__fill")
        assert "transition: width var(--motion-slow)" in fill
        assert "animation" not in fill, \
            "бегущий блик у determinate запрещён (проигрывание с нуля/петля)"
        assert "width: 0" in fill, "стартовое значение — 0, не «случайная доля»"

    def test_unknown_and_stale_are_visible(self):
        track = re.search(r'\.ctl-progress__track\[data-state="unknown"\],\s*'
                          r'\.ctl-progress__track\[data-state="stale"\]\s*\{[^}]*\}',
                          W11)
        assert track, "нет состояния unknown/stale"
        assert "repeating-linear-gradient" in track.group(0), \
            "нет данных — штриховка, а не залитый «успех»"
        zero = re.search(r'\.ctl-progress__track\[data-state="unknown"\] > '
                         r'\.ctl-progress__fill', W11)
        assert zero, "unknown не заливает полосу"
        assert "!important" in W11[zero.start():zero.start() + 200], \
            "заливка гасится и поверх inline-ширины"

    def test_the_impossible_is_diagnosed_in_js(self):
        out = _node("tests/js/evol_w11_controls_test.js")
        assert "EVOL-W11-CONTROLS-OK" in (out.stdout or ""), \
            "юнит-тест прогресса должен пройти (done>total/negative/stale)"
        block = APP_JS[APP_JS.index("function _ctlProgressModel"):
                       APP_JS.index("function _ctlScrollParent")]
        assert "anomaly = 'done>total'" in block
        assert "anomaly = 'negative'" in block
        assert "stale" in block and "unknown" in block
        assert "indeterminate" in block

    def test_pulse_only_for_confirmed_heartbeat(self):
        assert ".ctl-dot[data-live=\"1\"]" in W11
        assert "animation: ctl-pulse" in W11
        # Пульс не навешивается на карточки/границы/фон.
        assert not re.search(r"\.(?:card|status-block|lg-panel)[^{]*\{[^}]*ctl-pulse",
                             W11)
        assert "ctl-flash--once" in W11
        flash = _rule(".ctl-flash--once")
        assert " 1;" in flash, "подсветка одноразовая"

    def test_reduced_motion_kills_decoration_keeps_meaning(self):
        block = W11[W11.index("@media (prefers-reduced-motion: reduce) {"):]
        for needle in ('.ctl-dot[data-live="1"]',
                       '.ctl-progress[data-state="running"] .ctl-progress__track::after',
                       ".ctl-flash--once", ".ctl-btn__spinner"):
            assert needle in block, "reduced-motion не гасит %s" % needle
        assert "display: none" in block, \
            "indeterminate-полоса убирается (остаётся текстовый статус)"
        assert "transition: none" in block

    def test_no_100vh_for_keyboard_layout(self):
        assert not re.search(r"(?:^|[;{\s])(?:max-)?height:\s*100vh", W11), \
            "оверлеи не привязаны к 100vh (за клавиатурой)"
        assert "100dvh" in W11 or "var(--vv-h" in W11


# ═══ Разметка: контракт реально применён на страницах ═════════════════════

class TestMarkupWiring:
    def test_system_and_budget_bars_are_honest(self):
        assert INDEX.count('ctl-progress__track') >= 11, \
            "все системные/бюджетные полосы используют контракт состояния"
        assert INDEX.count('role="progressbar"') >= 11
        assert 'aria-valuenow' in INDEX
        assert 'class="progress"' not in INDEX, \
            "ни одна полоса не осталась с inline-шириной без состояния и aria"
        for computed in ("ctlCpuProg", "ctlMemProg", "ctlDiskProg",
                         "ctlContextProg", "ctlCallsProg", "ctlTokensProg",
                         "ctlDreamProg"):
            assert computed in APP_JS, "нет модели прогресса %s" % computed
            assert computed in INDEX, "модель %s не применена в разметке" % computed
        assert 'data-progress-anomaly' in INDEX

    def test_prompt_editor_gets_wrap_option_and_inner_scroll(self):
        assert "data-prompt-wrap-toggle" in INDEX
        assert "ctl-textarea" in INDEX and "ctl-editor-area" in INDEX
        assert ':data-nowrap="workspacePromptNoWrap' in INDEX
        assert "workspacePromptNoWrap: false" in APP_JS, \
            "по умолчанию перенос включён (поведение не меняется молча)"
        assert "ctl-seg__btn" in INDEX

    def test_no_new_fullscreen_trigger_for_editor(self):
        """Редактор промпта — внутристраничный, app-fullscreen не вызывается."""
        block = INDEX[INDEX.index("data-prompt-editor"):]
        block = block[:block.index("</section>", block.index("data-prompt-history"))]
        for forbidden in ("requestFullscreen", "FullscreenPolicy.request",
                          "toggleAppFullscreen"):
            assert forbidden not in block, \
                "редактор не должен запускать app-fullscreen: %s" % forbidden


# ═══ Тумблеры: контейнер контракта и различимость состояний ═════════════════
# Регрессия (нашёл Reviewer): CSS `.ctl-toggle input:checked ~ …` ждал
# контейнер `.ctl-toggle`, а 15 меток разметки несли только `__track/__thumb`.
# Включённое и выключенное состояния рисовались ОДИНАКОВО.

LABEL_RE = re.compile(r"<label\b[^>]*>[\s\S]*?</label>")


def _toggle_labels():
    """Все <label>, внутри которых рендерится трек тумблера контракта."""
    out = []
    for m in LABEL_RE.finditer(INDEX):
        block = m.group(0)
        if "ctl-toggle__track" not in block:
            continue
        tag_end = block.index(">") + 1
        open_tag = block[:tag_end]
        cls = re.search(r'class="([^"]*)"', open_tag)
        inner = block[tag_end:]
        input_at = inner.find("<input")
        input_end = inner.find(">", input_at) if input_at >= 0 else -1
        track_at = inner.index("ctl-toggle__track")
        track_tag = inner.rfind("<", 0, track_at)
        between = inner[input_end + 1:track_tag] if (
            input_at >= 0 and input_end >= 0 and track_tag > input_end) else None
        out.append({
            "line": INDEX[:m.start()].count("\n") + 1,
            "classes": (cls.group(1) if cls else "").split(),
            "input_before_track": between is not None,
            # `~` (сосед) работает только внутри одного родителя: между input
            # и треком не должно быть открытых обёрток.
            "siblings": between is not None and between.strip() == "",
        })
    return out


class TestToggleStates:
    def test_every_toggle_container_has_contract_class(self):
        """Все треки живут в метке с классом контракта (иначе CSS не совпадёт)."""
        labels = _toggle_labels()
        assert len(labels) == 15, \
            "тумблеров контракта должно быть 15, найдено %d" % len(labels)
        assert INDEX.count("ctl-toggle__track") == len(labels), \
            "есть трек вне метки тумблера (сирота без состояния)"
        bad = [(x["line"], x["classes"]) for x in labels
               if "ctl-toggle" not in x["classes"]]
        assert not bad, "метка без контейнера .ctl-toggle: %s" % (bad,)

    def test_input_and_track_are_siblings(self):
        labels = _toggle_labels()
        bad = [x["line"] for x in labels
               if not (x["input_before_track"] and x["siblings"])]
        assert not bad, \
            ("селектор `input:checked ~ track` требует, чтобы input стоял ДО "
             "трека у того же родителя; нарушено в строках %s" % (bad,))

    def test_state_selector_matches_real_container(self):
        """Селектор состояния и разметка называют ОДИН контейнер."""
        on_rule = re.search(
            r"(\.[\w-]+)\s+input:checked\s*~\s*\.ctl-toggle__track\s*\{([^}]*)\}",
            W11)
        assert on_rule, "нет правила включённого состояния для трека"
        container = on_rule.group(1).lstrip(".")
        assert container == "ctl-toggle", \
            "правило состояния ждёт контейнер .%s" % container
        missing = [x["line"] for x in _toggle_labels()
                   if container not in x["classes"]]
        assert not missing, \
            "контейнер .%s отсутствует в метках %s" % (container, missing)

    def test_checked_and_unchecked_paint_differ(self):
        """Значения состояний РАЗНЫЕ и включённый берёт акцентный токен."""
        off = _rule(".ctl-toggle__track")
        on = _rule(".ctl-toggle input:checked ~ .ctl-toggle__track")
        assert "background" in off and "background" in on
        assert off != on, "состояния объявлены одинаково"
        token = re.search(r"background:\s*var\(--purple-400\)", on)
        assert token, "включённый трек заливается акцентным токеном"
        accent = re.search(r"--purple-400:\s*(#[0-9A-Fa-f]{6})", CSS)
        assert accent, "нет токена --purple-400"
        rgb = tuple(int(accent.group(1)[i:i + 2], 16) for i in (1, 3, 5))
        off_rgb = re.search(
            r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", off)
        assert off_rgb, "выключенный трек не имеет явного цвета"
        assert rgb != tuple(int(g) for g in off_rgb.groups()), \
            "включённый и выключенный трек одного цвета (%s)" % (rgb,)
        # Бегунок едет внутри трека: 44 − 20 − 2 = 22 ≥ сдвиг 20.
        shift = re.search(
            r"input:checked\s*~\s*\.ctl-toggle__track\s+\.ctl-toggle__thumb"
            r"\s*\{[^}]*translateX\((\d+)px\)", W11)
        assert shift, "бегунок не сдвигается во включённом состоянии"
        assert int(shift.group(1)) > 0

    def test_disabled_toggle_is_visible(self):
        assert re.search(
            r"\.ctl-toggle\s+input:disabled\s*~\s*\.ctl-toggle__track\s*\{"
            r"[^}]*opacity", W11), \
            "недоступный тумблер не отличается от доступного"

    def test_no_second_implementation_of_toggle_state(self):
        """Одно состояние — одна реализация: Tailwind peer-checked не вернулся."""
        assert "peer-checked:" not in INDEX, \
            "вернулась вторая (Tailwind) реализация состояния тумблера"
        assert "peer-checked:" not in CSS

    def test_live_tool_checks_toggle_states(self):
        text = TOOL.read_text(encoding="utf-8")
        for needle in ("PROBE_TOGGLES", "PROBE_TOGGLE_FLIP",
                       "#/modules", "#/permsoc"):
            assert needle in text, "живой прогон не проверяет тумблеры: %s" % needle
        assert "toggle_flip_" in text and "check_toggles(" in text


# ═══ Достоверность ресурсной пары used/total ═══════════════════════════════

class TestResourcePairPercent:
    def test_percent_is_taken_from_pair_when_server_omits_it(self):
        """Пара used/total без `percent` считается, а не «нет данных»."""
        block = APP_JS[APP_JS.index("function _ctlPartPercent"):
                       APP_JS.index("function _ctlScrollParent")]
        assert "percent" in block and "used" in block and "total" in block
        assert "total <= 0" in block, "нулевой знаменатель не превращается в 100 %"
        for computed in ("ctlMemProg", "ctlDiskProg"):
            assert "_ctlPartPercent(" in APP_JS[
                APP_JS.index(computed + ": function"):][:400], \
                "%s не использует достоверный процент пары" % computed
        # Подпись строки и полоса берут ОДНО значение (не два источника).
        assert "ctlMemProg.percent" in INDEX
        assert "statusSys.mem.percent != null" not in INDEX
        assert "ctlDiskProg.percent" in INDEX
        assert "statusSys.disk.percent != null" not in INDEX



# ═══ Инвентаризация/аудит и живой прогон ══════════════════════════════════

class TestAuditAndLive:
    def test_audit_doc_has_inventory_and_table(self):
        assert AUDIT.exists(), "нет отчёта w11-controls.md"
        text = AUDIT.read_text(encoding="utf-8")
        assert "EVOL-043" in text and "EVOL-044" in text and "EVOL-045" in text
        assert "Инвентаризация" in text, "нет инвентаризации контролов"
        assert "до" in text and "после" in text, "нет замера до/после"
        assert "w11" in text.lower()

    def test_e2e_tool_covers_required_viewports(self):
        assert TOOL.exists(), "нет живого прогона W11"
        text = TOOL.read_text(encoding="utf-8")
        for vp in ("390", "768", "1280"):
            assert vp in text, "живой прогон не покрывает %s" % vp
        assert "keyboard" in text.lower(), "нет сценария с открытой клавиатурой"
        assert "placement" in text, "нет проверки flip оверлея"
        assert "EVOL-W11-CONTROLS OK" in text, "нет финального маркера прогона"

    def test_methods_dictionary_is_sane(self):
        out = _node("tests/js/app_methods_dup_keys_guard_test.js")
        assert "OK" in (out.stdout or ""), (out.stdout or "") + (out.stderr or "")

    def test_live_render_w11_e2e(self):
        try:
            import playwright  # noqa: F401
        except Exception:  # noqa: BLE001
            import pytest

            pytest.skip("playwright не установлен в этом окружении")
        res = subprocess.run([sys.executable, str(TOOL)], cwd=str(ROOT),
                             capture_output=True, text=True, encoding="utf-8",
                             timeout=1800,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        assert res.returncode == 0, (res.stdout or "") + (res.stderr or "")
        assert "EVOL-W11-CONTROLS OK" in (res.stdout or "")
