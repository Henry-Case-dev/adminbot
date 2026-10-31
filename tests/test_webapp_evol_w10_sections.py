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

# ── JS-харнесс: РЕАЛЬНАЯ связка «клик по карточке Памяти → окно записи».
# Блокер ре-ревью EVOL-029 был поведенческим (окно жило в ветке «Статуса»),
# поэтому проверяется не строка `openStatusRecord(`, а состояние store:
# карточка каталога поднимает запись с полями, окно закрывается (блокировка
# прокрутки снимается тем же условием).
_MODAL_JS = r"""
'use strict';
const path = require('path');
const assert = require('assert');

global.Vue = { createApp(opts) { global.__opts = opts;
  return { component() {}, provide() {}, use() {}, mount() {} }; } };
global.window = { location: { hash: '#/memory' }, addEventListener() {},
                  Telegram: null, innerWidth: 1280, innerHeight: 900 };
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
const computeds = global.__opts.computed || {};

const vm = {
  statusRecord: null, statusRecordExtra: null, statusRecordExtraError: '',
  statusRecordExtraBusy: false, statusRecordReturnFocus: null,
  factsFeed: [], cognitionTraits: [], memoryCatalogPersonId: null,
  memoryCatalogOpenKey: '', $refs: {}, $nextTick(fn) { fn(); },
};
['openMemoryCatalogItem', 'openStatusRecord', 'closeStatusRecord',
 '_statusRecordFrom', 'statusSourceMeta', '_statusScopeLabel',
 '_statusOriginLabel', 'fmtTs', 'fmtLogTs', 'openEpisodeCard'].forEach((k) => {
  vm[k] = methods[k];
});
assert.strictEqual(typeof computeds.statusRecordOpen, 'function',
  'statusRecordOpen — вычисляемое состояние окна');
vm.__open = computeds.statusRecordOpen;
vm.__tech = computeds.statusRecordTech;
assert.strictEqual(typeof vm.__tech, 'function', 'statusRecordTech существует');

// Реальная форма карточки каталога «Память» (factsFeed → memoryCatalogItems).
const fact = {
  key: 'ff|-1001234567890|Толян|любит мемы', name: 'Толян',
  user_name: 'Толян', text: 'любит мемы', full: 'любит мемы', kind: 'факт',
  id: 777, chat_id: -1001234567890, user_id: 5, tg_message_id: 4242,
  origin: 'message', created_at: 1761800000,
};
assert.strictEqual(vm.__open.call(vm), false, 'до клика окно закрыто');
vm.openMemoryCatalogItem.call(
  vm, { source: 'fact', item: fact, key: 'fact|777' },
  { currentTarget: { focus() {} } });
assert.strictEqual(vm.__open.call(vm), true,
  'клик по карточке «Памяти» открывает окно записи');
assert.strictEqual(vm.statusRecord.source, 'fact');
assert.strictEqual(vm.statusRecord.chat_id, -1001234567890);

const keys = vm.statusRecord.fields.map((f) => f.key);
['text', 'type', 'scope', 'subject', 'user_id', 'created_at', 'event_at',
 'confirmed_at', 'updated_at', 'origin', 'status', 'sources', 'changes']
  .forEach((k) => assert.ok(keys.indexOf(k) >= 0, 'поле окна: ' + k));

const tech = {};
vm.__tech.call(vm).forEach((t) => { tech[t.key] = t.value; });
assert.strictEqual(tech.raw_chat_id, '-1001234567890',
  'сырой chat_id — в «Технических полях»: ' + JSON.stringify(tech));
assert.strictEqual(tech.raw_id, '777', 'сырой id записи доступен');
assert.strictEqual(tech.raw_key, fact.key, 'ключ записи доступен');

vm.closeStatusRecord.call(vm);
assert.strictEqual(vm.__open.call(vm), false,
  'закрытие снимает статус открытого окна (и блокировку прокрутки)');
assert.strictEqual(vm.__tech.call(vm).length, 0, 'после закрытия полей нет');

console.log('EVOL-W10-MEMORY-MODAL-OK');
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


# ═══ EVOL-029 (review-fix2): карточка «Памяти» реально открывает окно ═══════

class TestEvol029RecordModalFromMemory:
    """Блокер ре-ревью: на `#/memory` клик по карточке ставил
    `sfeed-modal-open` (прокрутка фона заблокирована), но само окно жило в
    ветке `activeTab === 'status'` — окна не было. Здесь проверяется
    РАЗМЕЩЕНИЕ (одно окно на уровне `#app`) и РЕАЛЬНОЕ поведение store
    (карточка → запись с полями, закрытие → пусто). Видимое окно в Chromium
    проверяет `tools/ui_evol_w10_sections_e2e.py` (см. также pytest ниже).
    """

    def test_single_modal_at_shell_level(self):
        assert INDEX.count("data-sfeed-modal") == 1, "окно записи — один экземпляр"
        block = _block(INDEX, "<!-- ═══ EVOL-003/004/005: модальное окно записи",
                       "</transition>")
        assert "activeTab ===" not in block, (
            "окно записи не может жить внутри ветки одной вкладки: "
            "иначе «Память» открывает блокировку прокрутки без окна")
        # окно вынесено из `main.scroll-area` — на уровень shell/`#app`
        assert INDEX.index("data-sfeed-modal") > INDEX.index("</main>")
        # фон блокируется ТЕМ ЖЕ условием, что рисует окно
        assert "statusRecordOpen ? 'sfeed-modal-open' : ''" in INDEX
        assert ".app-shell.sfeed-modal-open main.scroll-area" in CSS
        # «Диагностика» карточки памяти обещает сырые id в окне — они там есть
        assert "statusRecordTech: function" in APP_JS
        assert "data-rec-tech" in block
        # закрытие: ✕, клик вне и Esc ведут в один и тот же путь
        assert block.count("closeStatusRecord()") >= 3
        assert "statusRecordKeydown" in block

    def test_memory_card_opens_record_with_fields_js(self, tmp_path):
        js = tmp_path / "w10_memory_modal_test.js"
        js.write_text(_MODAL_JS, encoding="utf-8")
        out = subprocess.run(["node", str(js)], capture_output=True, text=True,
                             encoding="utf-8",
                             env={**os.environ, "W10_REPO": str(ROOT)})
        assert "EVOL-W10-MEMORY-MODAL-OK" in (out.stdout or ""), \
            (out.stdout or "") + (out.stderr or "")


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


# ═══ ASAP-UI-02 §5/§6/§7 (wave 2): порядок «Статуса», единый виджет, tint ══

class TestEvolStatusOrderWave2:
    """§5.3: здоровье → карта (место EVOL-COG) → ОДИН виджет с четырьмя
    секциями → остальные виджеты (сон и прочее — ПОСЛЕ лент)."""

    @staticmethod
    def _status() -> str:
        return _block(INDEX, "activeTab === 'status'", "activeTab === 'info'")

    def test_order_health_map_widget_others(self):
        status = self._status()
        order = [
            'class="card p-4 status-hero',
            'class="card p-4 status-block"',
            'class="card p-4 status-graph',
            'class="card p-4 sg-12 intel-card"',
            'data-status-facts',
            'class="card p-4 status-sleep',
            'exec-preview card p-3',
            'class="card p-4 status-budgets',
            'data-viz-heatmap',
            'data-status-dossier',
        ]
        prev = -1
        for marker in order:
            i = status.index(marker)
            assert i > prev, "ASAP-UI-02 §5: порядок «Статуса» нарушен на %s" % marker
            prev = i

    def test_no_other_big_widget_between_health_and_ribbons(self):
        status = self._status()
        start = status.index('class="card p-4 status-block"')
        end = status.index('class="card p-4 sg-12 intel-card"')
        middle = status[start:end]
        # Между оперативным здоровьем и лентами — только карта (место
        # EVOL-COG). Ни сна, ни превью, ни бюджетов там нет.
        assert middle.count('class="card ') == 2, middle.count('class="card ')
        assert 'status-sleep' not in middle
        assert 'exec-preview' not in middle
        assert 'status-budgets' not in middle
        assert 'status-graph' in middle

    def test_one_widget_with_four_sections(self):
        status = self._status()
        assert status.count('intel-card') == 1, "одна карточка «Мониторинга»"
        card = _block(status, 'class="card p-4 sg-12 intel-card"',
                      'class="card p-4 status-sleep')
        assert card.count('class="ribbon ') == 4
        for section in ("facts", "beliefs", "paradigms", "traits"):
            assert 'data-intel-section="%s"' % section in card
        # четыре окна лент и один контроллер движения на каждое
        assert card.count("data-sfeed-viewport") == 4
        assert card.count('v-sfeed="statusRecordOpen"') == 4
        assert card.count('class="ribbon-track sfeed-track"') == 4
        # данные фактов — те же (dossier_feed), не новый запрос
        assert "factsFeed" in card and "dossierFeedError" in card
        assert "loadDossierFeed()" in APP_JS

    def test_no_separate_lower_facts_card(self):
        status = self._status()
        assert 'class="card p-4 status-facts' not in status
        assert status.count('data-status-facts') == 1
        # «Новые факты» больше не стоят после снов/превью
        facts = status.index('data-status-facts')
        sleep = status.index('class="card p-4 status-sleep')
        assert facts < sleep

    def test_phone_switcher_markup_and_css(self):
        status = self._status()
        assert 'data-intel-switcher' in status
        assert 'v-for="t in statusRibbonTabs"' in status
        assert 'switchStatusRibbon(t.id)' in status
        assert ':aria-pressed="statusRibbonTab === t.id' in status
        assert ':data-intel-tab="statusRibbonTab"' in status
        # переключатель скрыт там, где видны все четыре секции
        assert ".intel-tabs { display: none; }" in CSS
        assert (".cognition-ribbons[data-intel-tab] .ribbon { display: none; }"
                in CSS)
        for section in ("facts", "beliefs", "paradigms", "traits"):
            assert ('.cognition-ribbons[data-intel-tab="%s"] .ribbon--%s'
                    % (section, section)) in CSS
        # четыре колонки на широком экране, 2×2 на планшете
        assert ("grid-template-columns: repeat(4, minmax(0, 1fr));" in CSS)
        assert ("grid-template-columns: repeat(2, minmax(0, 1fr));" in CSS)

    def test_switcher_keeps_data_and_scroll(self):
        """Реальное поведение: данные не перезапрашиваются, позиции целы."""
        js = ROOT / "tests" / "js" / "asap_ui02_status_ribbons_test.js"
        assert js.exists(), "нет js-проверки переключателя секций"
        out = subprocess.run(["node", str(js)], capture_output=True, text=True,
                             encoding="utf-8", cwd=str(ROOT))
        assert "ASAP-UI02-RIBBONS-OK" in (out.stdout or ""), \
            (out.stdout or "") + (out.stderr or "")

    def test_warning_state_is_its_own_tint(self):
        """§6: warning — красное стекло, но мягче degraded/failed."""
        rules = _block(CSS, '[data-health-state="warning"][data-health-material="bg"]',
                       '[data-health-state="degraded"][data-health-material="bg"]')
        assert "rgba(60, 43, 56, 0.5)" in rules
        assert '--health-fill-warning: rgba(60, 43, 56, 0.5);' in CSS
        # порядок интенсивности: warning < degraded < failed
        def red(rgba):
            return sum(int(x) for x in rgba)
        warn = red((60, 43, 56))
        degrad = red((91, 55, 67))
        fail = red((141, 74, 85))
        assert warn < degrad < fail
        assert "background-color: rgba(91, 55, 67, 0.5);" in CSS
        assert "background-color: rgba(141, 74, 85, 0.5);" in CSS
        # единая карта: предупреждение сердцебиения — собственное состояние
        assert "if (hb === 'warning') return 'warning';" in APP_JS
        assert "warning: 'Внимание'" in APP_JS
        assert "warning: 'bolt'" in APP_JS
        # сам по себе WARN в журнале состояния не создаёт
        assert "function healthWarnOnly(payload)" in APP_JS
        # текст и иконка дублируют цвет: подпись warning — янтарная
        assert ('[data-health-indicator="warning"] .health-status-line__label'
                in CSS)

    def test_health_javascript_map(self):
        """Адаптер из РЕАЛЬНОГО app.js: warning не равен degraded/failed."""
        js = ROOT / "tests" / "js" / "evol032_health_glass_test.js"
        out = subprocess.run(["node", str(js)], capture_output=True, text=True,
                             encoding="utf-8", cwd=str(ROOT))
        assert "EVOL032-OK" in (out.stdout or ""), \
            (out.stdout or "") + (out.stderr or "")


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
