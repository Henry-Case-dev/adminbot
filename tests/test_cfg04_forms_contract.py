"""CFG-04 — контракт мобильных форм MiniApp (один save-сценарий, dirty,
safe-area/клавиатура, последнее поле, полный технический ключ, поворот).

Источник: `plans/features/cfg/source-cfg-addendum.md`
L149/L153/L157–L161/L165–L169/L173–L177 (карта CFG-04 req_id B.1–B.5,
C.1–C.5, D.2/D.3, A.1, F/ADD-1.T4/ADD-1.C5).
Подготовка: `plans/features/cfg/prep-cfg-04.md` (Ф2 — RED на базовом SHA).

Тест статически разбирает `web/index.html`, `web/app.js`, `web/static/app.css`
и **не подменяет** живые проверки: геометрия/скриншоты — в
`tools/ui_cfg04_forms_e2e.py`, поведение dirty/save — в
`tests/js/cfg04_forms_contract_test.js`.

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-04
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
    return [
        (ctx, body, _parse_decls(body))
        for ctx, sel, body in RULES
        if sel == selector and (not top_level_only or ctx == "")
    ]


def _effective_decls(selector: str) -> dict:
    merged = {}
    for ctx, sel, body in RULES:
        if ctx == "" and sel == selector:
            merged.update(_parse_decls(body))
    assert merged, f"нет CSS-правил для селектора {selector!r}"
    return merged


def _tokens() -> dict:
    ctx, body, decls = _rules_for(":root")[-1]
    return {k: v for k, v in decls.items() if k.startswith("--")}


def _token(name: str) -> str:
    return _tokens().get(name, "")


def _balanced(src: str, open_idx: int) -> str:
    """Фрагмент от `{` (open_idx) до парной закрывающей скобки."""
    depth, i = 1, open_idx + 1
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    assert depth == 0, "не закрыта фигурная скобка"
    return src[open_idx:i]


def _func_source(name: str) -> str:
    """Тело метода/функции `name`, объявленной как `name: function (...)`,
    `name = function (...)`, `name: async function (...)` — по балансу скобок,
    а не по подстроке до следующего имени."""
    m = re.search(r"\b" + re.escape(name)
                  + r"\s*[:=]\s*(?:async\s+)?function\s*\(", APP_JS)
    assert m, f"нет функции {name} в app.js"
    return _balanced(APP_JS, APP_JS.index("{", m.end() - 1))


def _component_source(name: str) -> str:
    """Тело `app.component('<name>', {...})` по балансу скобок."""
    m = re.search(r"app\.component\(\s*'" + re.escape(name) + r"'\s*,\s*\{",
                  APP_JS)
    assert m, f"нет компонента {name} в app.js"
    return _balanced(APP_JS, APP_JS.index("{", m.end() - 1))


def _chip_markup() -> str:
    """Разметка save-индикатора в шапке (элемент целиком)."""
    m = re.search(r'<(button|div|span)\b[^>]*class="header-save-chip[^"]*"'
                  r'[\s\S]{0,500}?</\1>', INDEX)
    assert m, "нет разметки .header-save-chip"
    return m.group(0)


# ═════════════ CFG-04B.1 (L157): один основной сценарий сохранения ══════════
class TestOneSaveFlow:
    def test_header_chip_is_not_a_save_action(self):
        """Чип в шапке — компактный индикатор (не CTA). Второй физический
        доступ к тому же действию конкурирует с нижней панелью на мобильном
        экране; источник L157 оставляет счётчик, но не второе сохранение."""
        chip = _chip_markup()
        assert "@click" not in chip, (
            "B.1: чип шапки не должен быть интерактивным сохранением")
        assert "saveModalEdits" not in chip, (
            "B.1: чип не вызывает saveModalEdits (единственное действие — панель)")
        assert 'role="status"' in chip, "B.1: чип — статус-индикатор (role=status)"
        assert 'data-save-indicator' in chip, "B.1: чип помечен data-save-indicator"

    def test_single_save_call_site_in_markup(self):
        """`saveModalEdits` — только внутри панели <sticky-save> (JS-шаблон
        компонента), не в разметке страницы."""
        assert '@click="saveModalEdits()"' not in INDEX, (
            "B.1: в index.html не должно быть второго save-CTA")
        assert "saveModalEdits" in _component_source("sticky-save")

    def test_chip_computed_is_indicator(self):
        body = _func_source("headerSaveChip")
        assert "actionable: false" in body, (
            "B.1: computed headerSaveChip отдаёт actionable=false")
        assert "'не сохранено'" in body, (
            "B.1: подпись dirty-индикатора не повторяет действие «Сохранить»")
        assert "'Сохранить'" not in body, (
            "B.1: индикатор не подписан как кнопка сохранения")

    def test_panel_is_the_only_save_surface(self):
        assert INDEX.count("<sticky-save") >= 3
        panel = _component_source("sticky-save")
        assert panel.count('@click="save"') == 1
        assert panel.count('@click="cancel"') == 1


# ═══════ CFG-04B.2 (L158): safe-area один раз + клавиатура у панели ═════════
class TestPanelSafeArea:
    def test_sticky_save_safe_area_formula(self):
        decls = _effective_decls(".sticky-save")
        pb = decls.get("padding-bottom", "")
        assert "max(" in pb, decls
        for token in ("env(safe-area-inset-bottom",
                      "var(--tg-safe-area-inset-bottom",
                      "var(--tg-content-safe-area-inset-bottom"):
            assert token in pb, (token, decls)
        assert pb.count("env(safe-area-inset-bottom") == 1, (
            "D3: safe-area учитывается ровно один раз")

    def test_modal_actions_do_not_subtract_safe_area_again(self):
        body = _effective_decls(".modal-actions").get("padding-bottom", "")
        assert "safe-area-inset-bottom" not in body

    def test_keyboard_moves_panel_geometry(self):
        decls = _effective_decls(".sticky-save")
        assert "var(--kb-offset" in decls.get("bottom", ""), (
            "B.2: клавиатура (--kb-offset) должна двигать геометрию панели, "
            "а не только scroll-margin")


# ═══════ CFG-04B.3 (L159): динамическая высота + последнее поле ═════════════
class TestLastField:
    def test_token_is_only_a_fallback(self):
        assert _token("--sticky-save-h") == "4.5rem", (
            "статический токен остаётся fallback-значением")

    def test_panel_height_is_measured(self):
        assert "_syncPanelHeight: function" in APP_JS
        body = _func_source("_syncPanelHeight")
        assert "--sticky-save-h" in body, (
            "B.3: фактическая высота панели пишется в --sticky-save-h")
        assert "getBoundingClientRect" in body
        assert "ResizeObserver" in APP_JS, (
            "B.3: высота пересчитывается при переносе панели (320 px)")

    def test_scroll_padding_matches_panel_and_keyboard(self):
        body = _effective_decls(".modal-body").get("scroll-padding-bottom", "")
        assert "var(--sticky-save-h)" in body and "var(--kb-offset" in body, body
        found = _rules_for(".scroll-area:has(> .sticky-save)")
        assert found, "нет правила .scroll-area:has(> .sticky-save)"
        _, _, decls = found[-1]
        sp = decls.get("scroll-padding-bottom", "")
        assert "var(--sticky-save-h)" in sp and "var(--kb-offset" in sp, decls
        assert decls.get("padding-bottom") in (None, "0", "0px"), (
            "M-1: padding-bottom контейнера не резервирует место")

    def test_fields_scroll_above_panel(self):
        decls = _effective_decls(".field")
        assert "scroll-margin-bottom" in decls
        assert "var(--sticky-save-h)" in decls["scroll-margin-bottom"]


# ═══════ CFG-04B.4/B.5 (L160/L161): dirty/save без фальшивого успеха ═══════
class TestDirtySaveContract:
    def test_dirty_is_value_based(self):
        body = _func_source("dirtyItems")
        assert "_serializeValue(it.value)" in body
        assert "snap[it.key] !== " in body, (
            "B.4: dirty считается сравнением значений (возврат к исходному снимает)")

    def test_save_waits_for_ack_and_keeps_baseline_on_failure(self):
        body = _func_source("saveModalEdits")
        assert "await this.persistItems" in body, (
            "B.4: сохранение ждёт ответа сервера")
        failure = body.index("if (failed.length)")
        snapshot = body.index("_snapshotConfig()")
        assert failure < snapshot, (
            "B.4: baseline сдвигается только когда провалов нет")
        assert "stickyFailed = failed" in body, (
            "B.4: при ошибке причина и ввод сохраняются")

    def test_cancel_restores_only_current_form(self):
        body = _func_source("cancelModalEdits")
        assert "JSON.parse(snap[it.key])" in body
        assert "this.keyDrafts = {}" in body
        assert "confirm" not in body, "B.4: «Отмена» не спрашивает разрешения"

    def test_single_save_engine(self):
        assert APP_JS.count("persistItems: async function") == 1
        assert APP_JS.count("saveModalEdits: async function") == 1
        # tумблеры/select — существующий автосейв (не второй движок).
        assert INDEX.count('@change="saveConfigItem(item)"') >= 3

    def test_chat_override_reset_is_distinct(self):
        assert 'class="btn-ghost text-xs px-2 shrink-0 btn-reset-global"' in INDEX
        assert 'aria-label="Вернуть глобальное значение"' in INDEX


# ═══════ CFG-04C.1/C.2 (L165/L166): колонки и touch-зоны ═══════════════════
class TestLayoutAndTouch:
    def test_mobile_single_column(self):
        found = [
            body for ctx, sel, body in RULES
            if sel == ".app-shell.ia-v2 main.scroll-area" and "max-width: 767px" in ctx
        ]
        assert found, "нет mobile-правила одной колонки для main.scroll-area"
        assert "minmax(0, 1fr)" in found[-1] and "!important" in found[-1]

    def test_primary_touch_targets(self):
        decls = _effective_decls(".sticky-save .btn-accent")
        assert decls.get("min-height") == "44px", (
            "C.2: «Сохранить» — touch-зона ≥44 px")
        ghost = _effective_decls(".sticky-save .btn-ghost")
        assert ghost.get("min-height") == "44px"
        toggle = _effective_decls(".card .param-toggle")
        assert toggle.get("min-height") == "44px" and toggle.get("min-width") == "44px"
        assert INDEX.count("param-toggle") >= 1

    def test_source_label_visible(self):
        assert "configSourceLabel(item)" in INDEX
        assert "configSourceTitle(item)" in INDEX


# ═══════ CFG-04C.3 (L167): полный технический ключ ═════════════════════════
class TestTechnicalKey:
    def test_component_registered(self):
        assert "app.component('tech-key'" in APP_JS
        src = _component_source("tech-key")
        assert "props:" in src and "value:" in src
        assert ":title=\"value\"" in src

    def test_keys_use_disclosure_component(self):
        assert 'font-mono truncate' not in INDEX, (
            "C.3: голый truncate ключа больше не используется")
        assert INDEX.count('<tech-key :value="item.key"') >= 10
        assert INDEX.count("<tech-key") >= 15, (
            "C.3: все витрины ключей используют общий компонент")

    def test_disclosure_contract(self):
        src = _component_source("tech-key")
        assert ':title="value"' in src, "C.3: полное значение в title"
        assert "aria-expanded" in src, "C.3: раскрытие доступно с клавиатуры"
        assert "navigator.clipboard" in src and "writeText" in src, (
            "C.3: копирование полного ключа")
        assert "data-copied" in src, "C.3: обратная связь копирования"
        assert ".tech-key" in CSS and ".tech-key__copy" in CSS
        assert ".tech-key__value--open" in CSS, "C.3: раскрытие без обрезки"

    def test_russian_meaning_stays(self):
        # русский заголовок/описание/значение в карточке не заменяются ключом
        assert "{{ item.title }}" in INDEX
        assert "{{ item.description }}" in INDEX


# ═══════ CFG-04A.1 (L153): поворот не теряет ввод/скролл/маршрут ═══════════
class TestOrientation:
    def test_viewport_state_is_preserved(self):
        for name in ("_captureEditViewport", "_restoreEditViewport",
                     "_preserveEditViewport", "_preserveOnViewportChange"):
            assert name + ": function" in APP_JS, name
        resize = _func_source("_onResize")
        assert "_preserveOnViewportChange(" in resize, (
            "A.1: смена viewport сохраняет скролл/активное поле")
        wrapper = _func_source("_preserveOnViewportChange")
        assert "_preserveEditViewport(" in wrapper and "_syncShellMode()" in wrapper

    def test_fields_have_stable_keys(self):
        assert INDEX.count("data-cfg-key") >= 10, (
            "A.1: поля помечены ключом параметра для восстановления фокуса")

    def test_no_config_reload_on_resize(self):
        resize = _func_source("_onResize")
        for forbidden in ("loadConfig", "fetch(", "refreshConfig"):
            assert forbidden not in resize, (
                "A.1: поворот не перезагружает конфиг (%s)" % forbidden)


# ═══════ CFG-04C.5 / CFG-04.F (guard): glass/фон и чужие владельцы ══════════
class TestProtectedSurfaces:
    def test_glass_tokens_unchanged(self):
        tokens = _tokens()
        assert tokens.get("--glass-bg-strong") == "rgba(21, 27, 42, 0.85)"
        assert tokens.get("--glass-blur") == "blur(16px)"
        assert tokens.get("--glass-border-color") == "rgba(170, 182, 200, 0.16)"
        assert tokens.get("--glass-border") == "1px solid var(--glass-border-color)"

    def test_panel_keeps_glass(self):
        decls = _effective_decls(".sticky-save")
        assert "var(--glass-bg-strong)" in decls.get("background-color", "")
        assert "var(--glass-blur)" in decls.get("backdrop-filter", "")

    def test_header_navigation_not_rebuilt(self):
        # CFG-04.F / ADD-1.T4 / ADD-1.C5: шапка/навигация/fullscreen не
        # переделываются — правится только узел save-индикатора.
        # ASAP-UI-02 §2.1/§2.2: навигация — drawer (без нижней панели),
        # визуального бренда Adminbot в шапке нет.
        assert 'data-drawer-trigger' in INDEX
        assert "toggleFullscreen()" in INDEX
        assert 'class="mobile-brand' not in INDEX
