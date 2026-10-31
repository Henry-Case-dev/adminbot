"""EVOL-026..030 (W10) — структурные контракты секционных экранов.

Покрытие (plans/current_task.md):
  * EVOL-026 (L357–373): «Активность по часам» и «Живая лента досье» — в
    «Статусе»; полный виджет «Истории памяти» — в «Аналитике»; превью с
    «Показать всё»; один экземпляр каждого виджета, без битых маршрутов.
  * EVOL-027 (L375–389 + v0.7/v0.8): глобальный тумблер ПРЯМО в карточке
    каталога (немедленная серверная операция, per_chat:false), отдельный
    per-chat override, отсутствие тяжёлой KPI-строки, отсутствие второго
    master-toggle в деталях модуля, честное «enabled ≠ healthy».
  * EVOL-028 (L391–402): «ИИ» — рабочая панель; личность переехала в
    «Речь и характер» (единственный канонический редактор), `#/ai/persona`
    остаётся deep-link'ом; «Умный кэш» не в навигации.
  * EVOL-029 (L404–412): «Память» — читаемый каталог знаний: поиск, типы по
    реальной модели, карточка сущности, «Диагностика / расширенный режим».
  * EVOL-030 (L414–422): «Доступы» — сводка + разделы; матрица прав на mobile
    «сущность → права → эффективные роли»; метаданные фильтров в «Аналитике».

Тесты структурные (разметка/поведение-store) и НЕ дублируют живые прогоны
`tools/ui_evol_w10_sections_e2e.py` (Playwright, скриншоты обоих размеров).
"""
from pathlib import Path

import re
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")

# ── JS-харнесс: app.js грузится в node с минимальными DOM-заглушками (тот же
# приём, что в tests/js/evol_w9_responsive_test.js), затем вызвается РЕАЛЬНАЯ
# vizHeatStep на фикстуре из четырёх часов с данными.
_HEAT_JS = r"""
'use strict';
const path = require('path');
const assert = require('assert');

const focused = [];
let queryResult = null;
global.Vue = { createApp(opts) { global.__opts = opts;
  return { component() {}, provide() {}, use() {}, mount() {} }; } };
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null,
                  innerWidth: 1280, innerHeight: 900 };
global.document = {
  documentElement: { setAttribute() {}, getAttribute() { return null; },
                     classList: { toggle() {}, contains() { return false; } },
                     style: { setProperty() {}, removeProperty() {} } },
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { tagName: 'div', className: '', value: '', style: {},
                             setAttribute() {}, focus() {}, select() {},
                             remove() {} }; },
  querySelector(sel) {
    if (queryResult) return queryResult(sel);
    return null;
  },
  querySelectorAll() { return []; },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', { configurable: true,
  value: { clipboard: { writeText: async () => { throw new Error('no'); } } } });
global.sessionStorage = { _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.localStorage = { _s: {}, getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(process.env.W10_REPO, 'web', 'app.js'));
const methods = global.__opts.methods || {};

const pad = (n) => (n < 10 ? '0' : '') + n;
const dkey = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-'
  + pad(d.getDate());
const now = new Date();
const TODAY = dkey(now);
const YDAY = dkey(new Date(now.getTime() - 86400000));

// Фикстура: 4 часа с данными на двух днях (уровни l1..l4 при max=70).
const vm = {
  vizActivityDays: 14,
  vizActivity: { available: true, total: 125, buckets: [
    { d: YDAY, h: 9, c: 1, errs: 0 },
    { d: YDAY, h: 10, c: 18, errs: 1 },
    { d: TODAY, h: 9, c: 36, errs: 0 },
    { d: TODAY, h: 10, c: 70, errs: 1 },
  ] },
  vizHeatSel: null,
  $nextTick(fn) { fn(); },
};
vm.vizHeatCells = methods.vizHeatCells;
vm.vizHeatIsPicked = methods.vizHeatIsPicked;
vm.vizHeatPick = methods.vizHeatPick;
vm.vizHeatStep = methods.vizHeatStep;
vm._vizHeatAt = methods._vizHeatAt;
vm._vizHeatFocus = methods._vizHeatFocus;
vm._vizHeatFocused = methods._vizHeatFocused;

assert.strictEqual(typeof methods.vizHeatStep, 'function',
  'vizHeatStep существует (иначе шаблон падает TypeError)');

// Фокус пишется в журнал — это то, что видит клавиатурный пользователь.
queryResult = (sel) => {
  focused.push(sel);
  return { focus() { vm.__active = sel; } };
};

const cells = vm.vizHeatCells.call(vm);
assert.strictEqual(cells.filter((c) => c.has).length, 4,
  'фикстура: 4 заполненных часа');
const sel = () => vm.vizHeatSel;
const keyOf = (s) => (s ? s.d + ':' + s.h : null);

// 1. Шаг вправо от 09:00 → 10:00 того же дня.
vm.vizHeatSel = { d: TODAY, h: 9, c: 36, errs: 0 };
vm.vizHeatStep.call(vm, 1, 0);
assert.strictEqual(keyOf(sel()), TODAY + ':10', 'вправо: следующий час с данными');
assert.ok(vm.vizHeatIsPicked.call(vm, sel()), 'выбранная ячейка отмечена');
assert.ok(focused[focused.length - 1].indexOf(TODAY + ':10') >= 0,
  'фокус переехал на выбранную кнопку: ' + focused[focused.length - 1]);

// 2. Вправо от 10:00 — по кругу на 09:00 (часы не «упираются»).
vm.vizHeatStep.call(vm, 1, 0);
assert.strictEqual(keyOf(sel()), TODAY + ':9', 'вправо: часы идут по кругу');

// 3. Влево от 09:00 — по кругу на 10:00.
vm.vizHeatStep.call(vm, -1, 0);
assert.strictEqual(keyOf(sel()), TODAY + ':10', 'влево: часы идут по кругу');

// 4. Вниз за последний день окна — кламп (остаёмся на месте, не теряем фокус).
vm.vizHeatStep.call(vm, 0, 1);
assert.strictEqual(keyOf(sel()), TODAY + ':10', 'вниз за краем: остаёмся');

// 5. Вверх — предыдущий день, тот же час (если там есть данные).
vm.vizHeatStep.call(vm, 0, -1);
assert.strictEqual(keyOf(sel()), YDAY + ':10', 'вверх: предыдущий день');

// 6. Вверх от самого первого дня — тоже кламп.
vm.vizHeatStep.call(vm, 0, -1);
assert.strictEqual(keyOf(sel()), YDAY + ':10', 'вверх за краем: остаёмся');

// 7. Без выбора и без фокуса — первый заполненный час (не пустой).
vm.vizHeatSel = null;
vm.__active = null;
queryResult = null;
vm.vizHeatStep.call(vm, 1, 0);
assert.deepStrictEqual({ d: sel().d, h: sel().h }, { d: YDAY, h: 9 },
  'первый шаг: первый час с данными');

// 8. Нет данных — функция не падает и ничего не выбирает.
const empty = { vizActivity: { available: false, buckets: [] },
                vizActivityDays: 14, vizHeatSel: null, $nextTick(f) { f(); } };
empty.vizHeatCells = methods.vizHeatCells;
empty.vizHeatStep = methods.vizHeatStep;
empty._vizHeatAt = methods._vizHeatAt;
empty._vizHeatFocus = methods._vizHeatFocus;
empty._vizHeatFocused = methods._vizHeatFocused;
empty.vizHeatStep.call(empty, 1, 0);
assert.strictEqual(empty.vizHeatSel, null, 'без данных шаг — no-op');

console.log('EVOL-W10-HEAT-OK');
"""

_DEEPLINK_JS = r"""
'use strict';
const path = require('path');
const assert = require('assert');

global.Vue = { createApp(opts) { global.__opts = opts;
  return { component() {}, provide() {}, use() {}, mount() {} }; } };
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null,
                  innerWidth: 1280, innerHeight: 900 };
global.document = {
  documentElement: { setAttribute() {}, getAttribute() { return null; },
                     classList: { toggle() {}, contains() { return false; } },
                     style: { setProperty() {}, removeProperty() {} } },
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { tagName: 'div', className: '', value: '', style: {},
                             setAttribute() {}, focus() {}, select() {},
                             remove() {} }; },
  querySelector() { return null; }, querySelectorAll() { return []; },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', { configurable: true,
  value: { clipboard: { writeText: async () => { throw new Error('no'); } } } });
global.sessionStorage = { _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.localStorage = { _s: {}, getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(process.env.W10_REPO, 'web', 'app.js'));
const methods = global.__opts.methods || {};

const order = [];
const vm = {
  vizHeatSel: { d: '2026-10-31', h: 10, c: 70, errs: 1 },
  mca17cRunF: { days: '30', status: 'failed' },
  oversightFocusNote: '',
  oversightTab: 'overview',
  oversightSetTab(tab) { order.push('setTab:' + tab); this.oversightTab = tab; },
  navigateTo(route) { order.push('navigate:' + route); },
};
vm.vizHeatOpenEvents = methods.vizHeatOpenEvents;
vm.vizHeatOpenEvents.call(vm);

assert.deepStrictEqual(order, ['setTab:runs', 'navigate:#/oversight?tab=runs'],
  'сначала суб-вкладка «Запуски», затем переход: ' + JSON.stringify(order));
assert.ok(vm.oversightFocusNote.indexOf('2026-10-31 10:00') >= 0,
  'подпись выбранного часа сохранена: ' + vm.oversightFocusNote);
assert.strictEqual(vm.mca17cRunF.days, '7', 'период запусков = выбранный день');
assert.strictEqual(vm.mca17cRunF.status, 'failed',
  'остальные фильтры не затёрты');

// Без выбора функция — no-op (никакой навигации «в никуда»).
const empty = { vizHeatSel: null, oversightFocusNote: '',
                oversightSetTab() { throw new Error('не должен зваться'); },
                navigateTo() { throw new Error('не должен зваться'); } };
empty.vizHeatOpenEvents = methods.vizHeatOpenEvents;
empty.vizHeatOpenEvents.call(empty);

console.log('EVOL-W10-DEEPLINK-OK');
"""


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# ═══ EVOL-026: разделение «Статус» ↔ «Аналитика» ═══════════════════════════

class TestEvol026Widgets:
    def test_heatmap_lives_in_status(self):
        status = _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")
        assert status.count("data-viz-heatmap") == 1
        assert "vizHeatPick(c)" in status
        assert "data-viz-heat-picked" in status
        assert "vizHeatTzLabel()" in status
        assert "data-viz-heat-legend" in status
        # ровно один экземпляр на весь документ (нет дубля в «Аналитике»)
        assert INDEX.count("data-viz-heatmap") == 1

    def test_dossier_feed_lives_in_status(self):
        status = _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")
        assert "data-status-dossier" in status
        assert "dossier-ticker--y" in status
        assert "openFeedDossier(it)" in status
        assert "dossierFeedStamp()" in status
        assert INDEX.count("data-status-dossier") == 1

    def test_full_stories_widget_in_analytics(self):
        oversight = _block(INDEX, "activeTab === 'oversight'",
                           "activeTab === 'relations'")
        assert oversight.count("data-stories-feed") == 1
        assert "data-stories-analytics" in oversight
        assert "storiesFeedFiltered()" in oversight
        assert "data-stories-recovery-toggle" in oversight
        # причина невосстановления объясняется реальными данными
        assert "episodeRecovery.by_reason" in oversight

    def test_status_keeps_bounded_preview(self):
        status = _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")
        assert "data-stories-preview" in status
        assert "data-stories-show-all" in status
        assert "openStoriesAnalytics()" in status
        # полной ленты в «Статусе» нет
        assert "data-stories-feed" not in status

    def test_heatmap_keyboard_and_honest_states(self):
        # F1 (review EVOL-026): шаблон вызывает vizHeatStep(dx, dy) — здесь
        # проверяем САМУ функцию на фикстуре (раньше проверялась только строка
        # шаблона, а функции не существовало → TypeError в Chromium).
        for marker in ("vizHeatStep(1, 0)", "vizHeatStep(-1, 0)",
                       "vizHeatStep(0, 1)", "@keydown.space.prevent"):
            assert marker in INDEX, marker
        block = _block(APP_JS, "vizHeatPick: function", "vizHeatOpenEvents:")
        assert "this.vizHeatSel = {" in block
        assert "vizHeatStep: function" in APP_JS
        # нет фиктивных нулей: пустое окно объясняется причиной
        assert "empty_reason" in INDEX

    def test_heat_cell_single_class_binding(self):
        """F2: у ячейки часа РОВНО одна привязка class.

        Два `:class` на одном элементе недопустимы: второй затирал первый,
        поэтому в живом DOM терялся либо уровень заливки, либо `is-picked`
        (проверено в реальном Chromium: className = `...--l1`, без is-picked).
        """
        block = _block(INDEX, "v-for=\"c in row.cells\"", "</button>")
        assert block.count(":class=") == 1, block[:400]
        assert "vizHeatClass(c)" in block
        assert "'is-picked'" in block
        assert "vizHeatIsPicked(c)" in block
        # у легенды и прокрутки — свои маркеры, сетку не дублируют
        assert "viz-heat__scroll-hint" in INDEX

    def test_heatmap_keyboard_behaviour_js(self, tmp_path):
        """Реальное поведение стрелок: шаг по часам с данными, фокус, aria."""
        js = tmp_path / "w10_heatmap_kbd_test.js"
        js.write_text(_HEAT_JS, encoding="utf-8")
        out = subprocess.run(["node", str(js)], capture_output=True, text=True,
                             encoding="utf-8",
                             env={**os.environ, "W10_REPO": str(ROOT)})
        assert "EVOL-W10-HEAT-OK" in (out.stdout or ""), \
            (out.stdout or "") + (out.stderr or "")

    def test_heat_deep_link_sets_tab_before_navigate_js(self, tmp_path):
        """F3: вкладка «Запуски» выставляется ДО навигации (query теряется)."""
        js = tmp_path / "w10_heat_deeplink_test.js"
        js.write_text(_DEEPLINK_JS, encoding="utf-8")
        out = subprocess.run(["node", str(js)], capture_output=True, text=True,
                             encoding="utf-8",
                             env={**os.environ, "W10_REPO": str(ROOT)})
        assert "EVOL-W10-DEEPLINK-OK" in (out.stdout or ""), \
            (out.stdout or "") + (out.stderr or "")

    def test_no_fake_updating_label(self):
        assert "dossierFeedStamp: function" in APP_JS
        block = _block(APP_JS, "dossierFeedStamp: function",
                       "vizHeatTzLabel: function")
        assert "обновляется" not in block
        assert "данные от " in block


# ═══ EVOL-027: каталог модулей ═════════════════════════════════════════════

class TestEvol027Catalog:
    def _catalog(self) -> str:
        return _block(INDEX, "activeTab === 'modules'", "activeTab === 'oversight'")

    def test_no_kpi_row_and_caption_present(self):
        cat = self._catalog()
        assert "module-counters" not in cat
        assert "module-counter" not in cat
        assert "data-module-caption" in cat
        assert "filteredModules.length" in cat

    def test_global_master_toggle_on_card(self):
        cat = self._catalog()
        assert "data-module-global-toggle" in cat
        assert "setModuleGlobalState(m, $event.target.checked)" in cat
        assert ":aria-label=\"moduleGlobalToggleLabel(m)\"" in cat
        # подпись области действия явная, рядом с тумблером
        assert "Глобально" in cat
        # чатовый override — отдельная, подписанная строка
        assert "data-module-chat-toggle" in cat
        assert "В этом чате" in cat

    def test_global_write_is_its_own_path(self):
        block = _block(APP_JS, "setModuleGlobalState: async function",
                       "moduleHealthView: function")
        assert "per_chat: false" in block
        assert "this.persistItems(" in block
        assert "moduleGlobalPending" in block
        assert "moduleGlobalOptimistic" in block
        # откат/ошибка и повторная защита от гонок
        assert "skipped: true" in block
        assert "Не удалось изменить глобально" in block

    def test_no_duplicate_master_toggle_in_details(self):
        modal = _block(INDEX, "Окно параметров модуля", "activeModuleGroups")
        assert "data-module-readonly-status" in modal
        assert "data-module-managed-hint" in modal
        assert "toggleModule(activeModule" not in modal
        assert "type=\"checkbox\"" not in modal
        ws = _block(INDEX, "data-workspace-head", "data-workspace-tabs")
        assert "toggleModule(workspaceModule" not in ws
        assert "data-module-managed-link" in ws

    def test_health_is_separate_from_enabled(self):
        assert "moduleHealthView: function" in APP_JS
        for marker in ("moduleHealthLine: function",
                       "moduleLastEventLine: function",
                       "moduleEffectiveLine: function"):
            assert marker in APP_JS, marker
        cat = self._catalog()
        assert "moduleHealthView(m)" in cat
        # «включено ≠ работает»: подпись здоровья отдельная
        assert "module-health" in cat


# ═══ EVOL-028: «ИИ» — рабочая панель и единый редактор личности ════════════

class TestEvol028AiHub:
    def test_working_panel_markup(self):
        assert "aiHubPanel: function" in APP_JS
        assert "data-ai-hub" in INDEX
        assert "data-ai-models" in INDEX
        assert "data-ai-speech" in INDEX
        assert "data-ai-names" in INDEX
        assert "data-ai-prompts" in INDEX
        assert "data-ai-persona-link" in INDEX

    def test_connection_vs_function_distinguished(self):
        block = _block(INDEX, "data-ai-models", "data-ai-speech")
        assert "проверка соединения" in block
        assert "не проверка работы функции" in block
        assert "aiModelGroups()" in block
        assert "healthBadge" in block or "healthText" in block

    def test_persona_moved_into_speech_editor(self):
        speech = _block(INDEX, "activeTab === 'speech'", "activeTab === 'info'")
        assert 'id="speech-persona"' in speech
        for marker in ("personaDraft.name", "personaDraft.biography",
                       "personaDraft.system_prompt_overrides",
                       "personaDraft.is_aware_ai", "savePersona()",
                       "resetPersona()"):
            assert marker in speech, marker
        # второго экрана/дубля нет
        assert "activeTab === 'persona'" not in INDEX

    def test_persona_route_is_deeplink(self):
        route_map = _block(APP_JS, "var ROUTE_TO_TAB = {", "};")
        assert "'#/ai/persona': 'speech'," in route_map
        parent = _block(APP_JS, "var ROUTE_PARENT = {", "};")
        assert "'#/ai/persona': '#/ai'," in parent
        assert "speech: '#/ai/speech'," in _block(
            APP_JS, "var TAB_TO_ROUTE = {", "};")

    def test_smart_cache_not_in_navigation(self):
        hub = _block(APP_JS, "var HUBS_V2 = {", "'#/memory': {")
        assert "Умный кэш" not in hub
        assert "smart-cache" not in hub
        # и на панели нет управляющих настроек кеша ответов
        panel = _block(INDEX, "data-ai-hub", "data-memory-catalog")
        assert "выведен из эксплуатации" in panel


# ═══ EVOL-029: «Память» — читаемый каталог знаний ══════════════════════════

class TestEvol029MemoryCatalog:
    def test_catalog_markup(self):
        assert "memoryHubPanel: function" in APP_JS
        assert "data-memory-catalog" in INDEX
        assert "data-memory-search" in INDEX
        assert "data-memory-list" in INDEX
        assert "data-memory-diagnostics" in INDEX

    def test_knowledge_types_follow_real_model(self):
        block = _block(APP_JS, "memoryCatalogTypes: function",
                       "memoryCatalogItems: function")
        for label in ("Факты", "Люди", "Связи", "Контекст", "Эпизоды"):
            assert label in block, label

    def test_items_use_real_sources_only(self):
        block = _block(APP_JS, "memoryCatalogItems: function",
                       "memoryCatalogFiltered: function")
        assert "this.factsFeed" in block           # записи досье
        assert "this.chatRelations" in block       # участники чата
        assert "this.cognitionGraphData" in block  # рёбра графа
        assert "this.cognitionBeliefs" in block    # убеждения
        assert "episodeFeedView" in block          # эпизоды
        # человеческое представление первично
        assert "status:" in block and "meta:" in block

    def test_detail_opens_existing_record_and_technical_is_separate(self):
        block = _block(APP_JS, "openMemoryCatalogItem: function",
                       "memoryCatalogIsOpen: function")
        assert "this.openStatusRecord(" in block
        assert "this.openEpisodeCard(" in block
        tech = _block(INDEX, "data-memory-diagnostics", "</details>")
        assert "Диагностика / расширенный режим" in tech
        assert "memorySearchAvailability()" in tech

    def test_no_fake_past(self):
        block = _block(INDEX, "data-memory-catalog", "</template>")
        assert "придумывать" not in block.lower()
        # отсутствие данных — честная причина, а не выдуманный сюжет
        # (текст причины формируется в app.js рядом с источником данных)
        src = _block(APP_JS, "memoryCatalogItems: function",
                     "memoryCatalogFiltered: function")
        assert "не восстановлено" in src
        assert "когда: неизвестно" in src

    def test_chat_title_instead_of_raw_id(self):
        """F5: в человеческой карточке — название чата, сырой id только в raw."""
        assert "chatTitleFor: function" in APP_JS
        helper = _block(APP_JS, "chatTitleFor: function",
                        "memoryCatalogTypeCount: function")
        # источник подписи — реальные списки чатов, не догадки
        assert "this.accessChats" in helper
        assert "this.oversightData" in helper
        src = _block(APP_JS, "memoryCatalogItems: function",
                     "memoryCatalogFiltered: function")
        assert "chatTitleFor" in src
        # ни один источник каталога больше не печатает сырой id в meta
        for raw in ("'чат: ' + f.chat_id", "'чат: ' + b.chat_id",
                    "'чат: ' + it.chatId"):
            assert raw not in APP_JS, raw
        # технический id остаётся в «Диагностике» (поле raw)
        assert "'chat_id: ' + f.chat_id" in src
        assert "'episode_id: ' + it.id" in src
        # тот же резолвер имени используется в живой ленте досье («Статус»):
        # «Чат <id>» остаётся только как честный fallback без названия
        feed = _block(APP_JS, "dossierFeedLoop: function",
                      "dossierFeedSpeed:")
        assert "chatTitleFor(it.chat_id)" in feed


# ═══ EVOL-030: «Доступы», матрица, аналитика ═══════════════════════════════

class TestEvol030AccessAndAnalytics:
    def test_hub_summary_and_sections(self):
        assert "accessHubPanel: function" in APP_JS
        assert "data-access-summary" in INDEX
        assert "data-access-section=\"matrix\"" in INDEX
        assert "data-access-section=\"admins\"" in INDEX
        assert "data-access-section=\"roles\"" in INDEX
        for label in ("Матрица прав", "Администраторы чата",
                      "Роли и пользователи"):
            assert label in INDEX, label
        # тяжёлые плитки-витрины убраны
        hub = _block(INDEX, "accessHubPanel", "</template>")
        assert "hub-card" not in hub

    def test_matrix_mobile_effective_roles(self):
        assert "matrixEffectiveRoles: function" in APP_JS
        assert "data-matrix-effective" in INDEX
        assert ".matrix-perm-summary" in CSS
        # на узком экране сводка ролей видима, таблица не превращается в кашу
        css = _block(CSS, ".matrix-perm-summary {", "/* ── W10-8")
        assert "display: block" in css

    def test_scope_and_audit_before_changes(self):
        block = _block(APP_JS, "accessScopeLabel: function",
                       "oversighRunsFilterLabel: function")
        assert "scopeKind" in block
        assert "accessScopeLabel()" in INDEX
        assert "RBAC" in INDEX
        # права скрыты/запрещены сервером, а не только видом
        assert "Права проверяются на сервере" in INDEX

    def test_analytics_filter_metadata_and_advanced_fields(self):
        assert "data-runs-filter-meta" in INDEX
        assert "oversighRunsFilterLabel()" in INDEX
        # технические поля сохранены (advanced/debug), не удалены
        assert "trace_ids" in INDEX
        assert "reason_code" in INDEX
        assert "pipeline_run_id" in INDEX

    def test_heatmap_deeplink_sets_focus_note(self):
        block = _block(APP_JS, "vizHeatOpenEvents: function",
                       "loadCognition: async function")
        assert "this.oversightFocusNote" in block
        assert "navigateTo('#/oversight?tab=runs')" in block
        # F3: вкладку ставим ДО перехода — navigateTo отбрасывает query.
        assert "oversightSetTab('runs')" in block

    def test_heat_levels_and_touch_size(self):
        """F2: уровни заданы с нужной специфичностью, ячейка — тач-цель."""
        for lvl in (0, 1, 2, 3, 4):
            assert ".viz-heat__row .viz-heat__cell--l%d" % lvl in CSS
            assert ".viz-heat__legend-cell.viz-heat__cell--l%d" % lvl in CSS
        # правила уровней идут ПОСЛЕ базовой заливки ячейки (равная
        # специфичность → иначе перекрыты); у легенды специфичность выше
        # (составной селектор), поэтому порядок не важен — важно, что он есть.
        base = CSS.index(".viz-heat__row .viz-heat__cell {")
        assert CSS.index(".viz-heat__row .viz-heat__cell--l3") > base
        i = CSS.index("@media (max-width: 480px), (pointer: coarse) {")
        seg = CSS[i:i + 700]
        assert "min-height: 24px" in seg, "ячейка часов ≥24 px на тач-экране"
        assert "repeat(24, minmax(24px, 1fr))" in seg
        # легенда крупнее базовой (0,2,0 против 0,1,0) и подсказка о прокрутке
        # включается только в этой ветке
        assert ".viz-heat__legend .viz-heat__legend-cell" in seg
        # подсказка о прокрутке включается только там, где 24-тач-ячейки
        # реально не влезают (иначе она врала бы про скролл на планшете)
        assert ".viz-heat__scroll-hint { display: block; }" in CSS
        assert "@media (pointer: coarse) and (max-width: 700px) {" in CSS
        assert ".viz-heat__scroll-hint { display: none; }" in CSS

    def test_audit_before_changing_rights(self):
        """F4: до изменения прав видно кто/когда/что и где."""
        for marker in ("matrixAuditWho: function", "matrixAuditWhen: function",
                       "matrixAuditScope: function"):
            assert marker in APP_JS, marker
        assert "data-access-audit" in INDEX
        assert "data-access-audit-summary" in INDEX
        who = _block(APP_JS, "matrixAuditWho: function",
                     "matrixAuditWhen: function")
        assert "this.me" in who
        assert "telegram_id" in who          # тот же id, что в журнале сервера
        assert "role_name" in who
        when = _block(APP_JS, "matrixAuditWhen: function",
                      "matrixAuditScope: function")
        assert "правки не сохранялись" in when   # честное «изменений не было»
        # отметка времени ставится РЕАЛЬНЫМ сохранением, а не при загрузке
        toggle = _block(APP_JS, "matrixRoleToggle: async function",
                        "matrixReset: async function")
        assert "matrixLastChange = {" in toggle
        assert "Date.now()" in toggle
        reset = _block(APP_JS, "matrixReset: async function", "applyTree:")
        assert "matrixLastChange = {" in reset


# ═══ Живой прогон (обязателен при визуальных изменениях) ═══════════════════

def test_live_render_sections_e2e():
    import subprocess
    import sys

    tool = ROOT / "tools" / "ui_evol_w10_sections_e2e.py"
    assert tool.exists(), "нет сквозного Playwright-прогона W10"
    try:
        import playwright  # noqa: F401
    except Exception:  # noqa: BLE001
        import pytest

        pytest.skip("playwright не установлен в этом окружении")
    res = subprocess.run([sys.executable, str(tool)], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8",
                         timeout=1800)
    assert res.returncode == 0, (res.stdout or "") + (res.stderr or "")
    assert "EVOL-W10-SECTIONS OK" in (res.stdout or "")
