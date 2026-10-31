"""EVOL-034..042 (W12) - внутренние экраны: один поиск, единая модель
источников настроек, семантические группы тумблеров, каталог промптов,
панель моделей и режимы Effective Prompt Inspector.

Источник требований - plans/current_task.md L562-688 (EVOL-034..042).

Что проверяется здесь (структура реальных файлов):
  * EVOL-037 - единственный глобальный поиск/command palette: точка входа в
    topbar (desktop), пункт в навигации/меню (tablet/mobile), Ctrl+K, Esc,
    структурный реестр результатов с группами, deep-link `?focus=` и фокус
    конкретного элемента; секретов и ключей API в индексе нет;
  * EVOL-040 - master-флаг модуля не имеет второго записывающего тумблера
    внутри модуля (read-only статус + вход в каталог), guard в saveConfigItem;
  * EVOL-035 - семантические группы тумблеров «Инициативы», per-chat opt-in
    отдельным действием, предохранители/диагностика в «Дополнительно»;
  * EVOL-038 - каталог промптов с поиском, один выбранный редактор, мета
    prompt_id/потребитель/scope, полноэкранный режим и предупреждение о
    конфликте версий;
  * EVOL-039 - в карточке подключения результат и время проверки соединения
    отделены от проверки функции;
  * EVOL-041/042 - навигация «Речи и характера» по задачам и явные режимы
    инспектора «последний реальный вызов» / «предпросмотр (не отправлено)».

Поведение (JS-логика) проверяет node-тест tests/js/evol_w12_internals_test.js;
живая вёрстка на 1280/390 - tools/ui_evol_w12_internals_e2e.py.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
NODE_TEST = ROOT / "tests" / "js" / "evol_w12_internals_test.js"
LIVE_TOOL = ROOT / "tools" / "ui_evol_w12_internals_e2e.py"

W12_CSS = CSS[CSS.index("W12-01."):]


def _node(*args):
    return subprocess.run(["node"] + [str(a) for a in args], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8")


# ═══ EVOL-037: один поиск/command palette ═══════════════════════════════════

class TestGlobalSearch:
    def test_palette_markup_is_single_and_accessible(self):
        """Одна палитра: диалог, поле, список, закрытие; без второй копии."""
        assert INDEX.count("data-command-palette") == 1, "палитра объявлена ровно один раз"
        assert INDEX.count("data-palette-input") == 1, "одно поле поиска"
        assert 'aria-label="Поиск по приложению"' in INDEX
        assert 'role="dialog"' in INDEX and 'aria-modal="true"' in INDEX
        assert 'aria-label="Результаты поиска"' in INDEX
        assert 'role="listbox"' in INDEX
        assert 'role="option"' in INDEX, "результаты — опции списка (скринридер)"
        assert "data-palette-empty" in INDEX, "пустая выдача объясняется"

    def test_entry_points_desktop_mobile_and_hotkey(self):
        """Desktop — topbar; tablet/mobile — навигация/меню; Ctrl+K + Esc."""
        assert 'data-palette-open' in INDEX, "desktop-точка входа в topbar"
        assert "header-search-btn" in INDEX
        assert "aria-keyshortcuts=\"Control+K Meta+K\"" in INDEX, \
            "хоткей объявлен для доступности"
        assert 'data-palette-open-drawer' in INDEX, \
            "на планшете/телефоне вход в навигации (шапку не раздуваем)"
        assert 'data-palette-open-mobile' in INDEX, "пункт меню «⋯»"
        assert "v-if=\"!hasDrawer\"" in INDEX, \
            "кнопка topbar не дублируется там, где есть drawer"
        # Ctrl+K обрабатывается глобально, Esc закрывает панель первой.
        assert "_paletteHotkey" in APP_JS
        assert "event.ctrlKey || event.metaKey" in APP_JS
        assert "if (this.paletteOpen) { this.closePalette(); return; }" in APP_JS
        assert "paletteKeydown" in APP_JS and "ArrowDown" in APP_JS

    def test_registry_not_hardcoded_module_list(self):
        """Индекс строится из существующих структур, а не из списка названий."""
        assert "paletteIndexEntries" in APP_JS
        for source in ("this.tabs", "this.modules", "this.configItems",
                       "this.providerConnectionBlocks"):
            assert source in APP_JS, "индекс читает существующий источник %s" % source
        # Секреты/ключи исключены из индексации.
        assert "it.secret === true || it.category === 'keys'" in APP_JS
        # Группы результатов — фиксированный словарь, не «прочее».
        for group in ("'Разделы'", "'Модули'", "'Настройки'", "'Промпты'",
                      "'Модели'", "'Данные'"):
            assert group in APP_JS, "группа результатов %s" % group
        # Никакого LLM-вызова на поиск.
        assert "openPalette" in APP_JS and "api(" not in APP_JS[
            APP_JS.index("openPalette: function"):APP_JS.index("paletteSelect: function")
        ], "поиск не вызывает сервер/LLM"

    def test_deeplink_focuses_exact_element(self):
        """Выбор открывает точку, а не верх страницы (общий deep-link)."""
        assert "?focus=" in APP_JS
        assert "_applyRouteFocus" in APP_JS
        assert 'data-focus-id="' in APP_JS, "токены целей для составных элементов"
        assert "data-cfg-key" in APP_JS
        assert "scrollIntoView" in APP_JS and ".focus(" in APP_JS
        assert "String(node.tagName).toLowerCase() === 'details'" in APP_JS, \
            "цель внутри свёрнутого блока раскрывается"
        # Фокус применяется и при повторном выборе того же маршрута.
        assert "this._applyRouteFocus();" in APP_JS

    def test_no_redundant_parameter_search_controls(self):
        """Бессмысленных дублей «Поиск по параметрам…» больше нет."""
        assert INDEX.count("Поиск по параметрам…") == 1, \
            "остался максимум один локальный фильтр (он реально фильтрует вкладку)"

    def test_palette_css_is_safe_area_and_motion_aware(self):
        assert ".palette-root" in W12_CSS and ".palette-panel" in W12_CSS
        assert "env(safe-area-inset-top" in W12_CSS
        assert "--vv-h" in W12_CSS and "--kb-offset" in W12_CSS, \
            "лист поиска учитывает клавиатуру/видимую область"
        assert "@media (max-width: 767px)" in W12_CSS, "мобильный полноэкранный лист"
        assert ".focus-pulse" in W12_CSS
        assert "prefers-reduced-motion" in W12_CSS.split(".focus-pulse")[1][:400], \
            "подсветка цели уважает reduced motion"
        # Контракт W11: в системе контролов нет «магических» размеров.
        assert not re.search(r"\bfont-size:\s*[0-9.]+\s*(?:px|rem)", W12_CSS)
        assert not re.search(r"\bborder-radius:\s*[0-9.]+\s*(?:px|rem)", W12_CSS)


# ═══ EVOL-040/035: источники настроек и тумблеры ════════════════════════════

class TestSettingsSources:
    def test_master_key_has_single_write_path(self):
        """Master-флаг модуля: read-only внутри модуля, запись — из каталога."""
        assert "isModuleMasterItem" in APP_JS
        assert "readonly_master: true" in APP_JS
        assert "data-module-master-note" in INDEX, \
            "внутри модуля у master-ключа объяснение, а не второй тумблер"
        assert "Управляется из каталога" in INDEX
        assert "К каталогу →" in INDEX
        # Guard: запись master-ключа из деталей отклоняется.
        assert "if (item.readonly_master)" in APP_JS
        assert "Включение модуля — в карточке каталога" in APP_JS
        # Ни один модуль не рендерит второй активный тумблер master-ключа:
        # в шаблонах master-ключ ведётся через readonly-ветку.
        assert INDEX.count('v-if="item.readonly_master"') >= 1

    def test_registry_maps_setting_to_editor(self):
        """Каждый параметр имеет адрес редактора: настройки/промпт/модель."""
        for fn in ("_tabOfItem", "_settingRouteOf", "_modelRouteOf"):
            assert fn + ": function" in APP_JS, "реестр %s" % fn
        assert "#/modules/' + slug + '/prompts/' + item.key" in APP_JS, \
            "промпт открывается в единственном редакторе с ключом"
        assert "#/modules/' + mslug + '/settings'" in APP_JS

    def test_initiative_flags_are_grouped_semantically(self):
        """4 смысловые группы; master и per-chat — отдельно."""
        for title in ("Автономная активность", "Планирование и расписание",
                      "Проверки безопасности", "Диагностика и журнал решений"):
            assert title in APP_JS, "группа %s" % title
        assert "INITIATIVE_PER_CHAT_KEY" in APP_JS
        assert "'initiative.enabled'" in APP_JS
        assert "INITIATIVE_MASTER_KEY" in APP_JS
        assert "data-initiative-flags" in INDEX
        assert "data-initiative-per-chat" in INDEX
        assert "data-initiative-advanced" in INDEX, \
            "предохранители и диагностика — в «Дополнительно»"
        assert INDEX.count("data-initiative-master-link") == 1
        # Пять ключей инициативы не дублируются в generic-сетке модуля.
        assert "it.key === INITIATIVE_PER_CHAT_KEY" in APP_JS
        assert "INITIATIVE_FLAG_GROUPS.forEach" in APP_JS

    def test_undeclared_keys_are_not_invented(self):
        """Группы собираются только из реально полученных ключей."""
        assert "var it = byKey[k];" in APP_JS and "if (it) rows.push(it);" in APP_JS
        assert "filter(function (g) { return g.items.length || g.links.length; })" \
            in APP_JS


# ═══ EVOL-038/039: промпты и подключения ═══════════════════════════════════

class TestPromptLibraryAndModels:
    def test_master_detail_single_editor(self):
        """Один выбранный промпт, поиск по каталогу, мета и полный экран."""
        assert "data-prompt-tree-search" in INDEX
        assert "promptTreeGroups" in APP_JS
        assert "data-prompt-tree-empty" in INDEX
        assert "data-prompt-editor-meta" in INDEX
        assert "prompt_id:" in INDEX and "потребитель:" in INDEX
        assert "data-prompt-fullscreen" in INDEX
        assert "promptEditorFull" in APP_JS
        assert "prompt-editor--full" in W12_CSS
        assert "data-prompt-conflict" in INDEX, "конфликт версий виден в редакторе"
        # Второго независимого редактора того же промпта нет.
        assert len(re.findall(r'data-prompt-editor(?!-)', INDEX)) == 1

    def test_connection_check_separates_http_and_function(self):
        """Соединение (HTTP/API) ≠ проверка функции; результат и время в карточке."""
        assert "data-conn-check" in INDEX
        assert "data-conn-check-function" in INDEX
        assert "connFunctionalCheckLabel" in APP_JS
        assert "_recordBlockCheck" in APP_JS
        assert "connCheckWhen" in APP_JS
        assert "ещё не проверялось" in INDEX
        assert "отдельной функциональной проверки нет" in APP_JS, \
            "где проверки нет — это сказано прямо"
        assert "Соединение" in INDEX and "Функция" in INDEX


# ═══ EVOL-041/042: «Речь и характер» и инспектор ═══════════════════════════

class TestSpeechCenterAndInspector:
    def test_task_areas_replace_long_catalog(self):
        assert "data-speech-area-nav" in INDEX
        assert "openSpeechArea" in APP_JS
        for area in ("Обзор", "Характер", "Манера речи", "Юмор",
                     "Опыт и обучение", "Как собирается ответ"):
            assert area in APP_JS, "область %s" % area
        assert "SPEECH_AREAS" in APP_JS
        assert ".speech-area-nav" in W12_CSS

    def test_single_persona_editor(self):
        """Второй одинаковый блок «Личность» удалён; id сохранён на редакторе."""
        assert INDEX.count('id="speech-persona"') == 1
        assert "data-speech-persona-editor" in INDEX
        # Прежняя дублирующая шапка «Личность и характер» больше не рендерится
        # отдельной карточкой перед редактором.
        assert INDEX.count("Личность и характер") <= 1

    def test_inspector_modes_are_explicit(self):
        assert "data-inspector-modes" in INDEX
        assert 'data-inspector-mode="real"' in INDEX
        assert 'data-inspector-mode="preview"' in INDEX
        assert "Последний реальный вызов" in INDEX
        assert "data-inspector-not-sent" in INDEX
        assert "НЕ отправлено" in INDEX
        assert "data-inspector-no-snapshot" in INDEX
        assert "Нет подтверждённого снимка" in INDEX
        assert "data-inspector-honest-note" in INDEX
        assert "speechInspectorHasReal" in APP_JS
        assert "setSpeechInspectorMode" in APP_JS
        # Реальные слои не показываются в режиме предпросмотра и наоборот.
        assert 'v-if="speechInspectorMode === \'real\'"' in INDEX
        assert 'v-if="speechInspectorMode === \'preview\'"' in INDEX


# ═══ Исполнение: JS-поведение + живая вёрстка ═══════════════════════════════

class TestExecution:
    def test_node_behavior_suite(self):
        out = _node(NODE_TEST)
        assert out.returncode == 0, (out.stdout or "") + (out.stderr or "")
        assert "EVOL-W12-INTERNALS-OK" in out.stdout

    def test_live_render_w12_e2e(self):
        try:
            import playwright  # noqa: F401
        except Exception:  # noqa: BLE001
            pytest.skip("playwright не установлен в этом окружении")
        res = subprocess.run([sys.executable, str(LIVE_TOOL)],
                             cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", timeout=1800,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        assert res.returncode == 0, (res.stdout or "") + (res.stderr or "")
        assert "EVOL-W12-INTERNALS OK" in (res.stdout or "")
