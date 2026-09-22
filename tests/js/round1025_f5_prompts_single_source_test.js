'use strict';
/* F5 round1025 (ADR-1025-15 D3/§48/§85) — «один промпт — один источник».
 *
 * Проверяет РЕАЛЬНУЮ логику web/app.js:
 *   (a) два маршрута (workspace модуля и библиотека промптов) открывают ОДИН
 *       и тот же объект configItems (`prompts.*`) — правка видна в обоих,
 *       копий нет;
 *   (b) фокус промпта резолвится ключом; неизвестный ключ → без падения;
 *   (c) §48: главный редактор виден сразу (не в аккордеоне); аккордеон — не
 *       основная навигация;
 *   (d) один write-path (saveConfigItem/persistItems), нет второго канала;
 *   (e) маршруты-«двери» строятся корректно (openWorkspacePrompt /
 *       openPromptLibrary);
 *   (f) канон промптов не переписывается (тексты — только чтение/запись F0).
 *   (g) M-F5S-1: промпт из библиотеки для модуля без объявленной
 *       промпт-вкладки (mod_summary) открывает РЕДАКТОР, не «Обзор»;
 *       дверь библиотеки сохраняется, объект остаётся один.
 *
 * Запуск: node tests/js/round1025_f5_prompts_single_source_test.js
 */
const path = require('path');
const assert = require('assert');
const fs = require('fs');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(__dirname, '..', '..', 'web', 'app.js'));
const data = captured.data();
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;
const TABS = data.tabs;
const APP_JS = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');

function moduleById(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}

// configItems — РЕАЛЬНЫЕ объекты (один источник); группы ссылаются на них.
// `sharedItems` позволяет смоделировать ДВА маршрута к одному источнику.
function mkPromptsCtx(sharedItems, gid) {
  const items = sharedItems || [
    { key: 'prompts.factcheck_analyst_system_prompt', category: 'prompts',
      group: 'prompts_factcheck', stage: 'synthesizer',
      title: 'Синтезатор фактчека', value: 'CANON-SYNTH' },
    { key: 'prompts.factcheck_verbalizer_system_prompt', category: 'prompts',
      group: 'prompts_factcheck', stage: 'verbalizer',
      title: 'Вербализатор фактчека', value: 'CANON-VERB' },
  ];
  const group = gid || 'prompts_factcheck';
  const ctx = {
    modules: MODULES, tabs: TABS, configItems: items,
    _workspaceGroupsFor: methods._workspaceGroupsFor,
    workspaceGroupTab: methods.workspaceGroupTab,
    _workspacePromptGroup: methods._workspacePromptGroup,
    workspacePromptItems: methods.workspacePromptItems,
    promptStageItems: methods.promptStageItems,
    groupedForTab(t) {
      if (t && t.id === 'prompts') {
        return [{ id: group, category: 'prompts',
                  uid: 'prompts/' + group, items: items }];
      }
      return [];
    },
  };
  ctx.workspace = computed.workspace.call(ctx);
  ctx.workspaceModule = computed.workspaceModule.call(ctx);
  return ctx;
}

(function run() {
  // ── (a) один объект на два маршрута ───────────────────────────────────
  {
    const m = moduleById('mod_factcheck');

    // Дверь 1: workspace модуля (вкладка Синтезатор).
    const wsCtx = mkPromptsCtx();
    wsCtx.route = '#/modules/factcheck/synthesizer';
    wsCtx.workspaceModule = m;
    wsCtx.workspace = computed.workspace.call(wsCtx);
    const wsItems = methods.workspacePromptItems.call(wsCtx, m, 'synthesizer');
    assert.strictEqual(wsItems.length, 1, 'a: Синтезатор — один промпт');
    assert.strictEqual(wsItems[0].key,
      'prompts.factcheck_analyst_system_prompt', 'a: ключ Синтезатора');

    // Дверь 2: библиотека промптов (#/ai/prompts/factcheck/synthesizer).
    const libItems = wsCtx.groupedForTab({ id: 'prompts' })[0].items;
    assert.strictEqual(libItems[0], wsItems[0],
      'a: обе двери → ОДИН объект configItems (не копия)');

    // Правка через маршрут A видна через маршрут B (тот же объект).
    wsItems[0].value = 'EDITED';
    const again = methods.workspacePromptItems.call(wsCtx, m, 'synthesizer');
    assert.strictEqual(again[0].value, 'EDITED',
      'a: правка A видна в B (общий объект)');
    assert.strictEqual(wsCtx.configItems[0].value, 'EDITED',
      'a: источник — configItems, не копия');

    // Нет серверных/клиентских копий: ровно 2 элемента prompts.*.
    const promptKeys = wsCtx.configItems.filter(function (i) {
      return String(i.key).indexOf('prompts.') === 0;
    });
    assert.strictEqual(promptKeys.length, 2, 'a: копий промптов нет');
  }

  // ── (a2) вторая дверь #/ai/prompts/<slug>/<stage> → тот же config-item ─
  {
    // Дверь 1 (страница модуля) и дверь 2 (библиотека) — один объект.
    const sharedItems = mkPromptsCtx().configItems;
    const fromModule = mkPromptsCtx(sharedItems);
    fromModule.route = '#/modules/factcheck/synthesizer';
    fromModule.workspace = computed.workspace.call(fromModule);
    const focusModule = computed.workspacePromptFocus.call(fromModule);

    const fromLibrary = mkPromptsCtx(sharedItems);
    fromLibrary.route = '#/ai/prompts/factcheck/synthesizer';
    fromLibrary.workspace = computed.workspace.call(fromLibrary);
    const wsLib = fromLibrary.workspace;
    assert.strictEqual(wsLib.door, 'library', 'a2: дверь библиотеки');
    assert.strictEqual(wsLib.module.id, 'mod_factcheck', 'a2: тот же модуль');
    assert.strictEqual(wsLib.stage, 'synthesizer',
      'a2: <stage> не перепутан с promptKey');
    const focusLibrary = computed.workspacePromptFocus.call(fromLibrary);

    assert.ok(focusModule && focusLibrary, 'a2: фокус в обеих дверях');
    assert.strictEqual(focusLibrary, focusModule,
      'a2: обе двери → ОДИН объект configItems (не копия)');
    assert.strictEqual(focusLibrary.key,
      'prompts.factcheck_analyst_system_prompt', 'a2: ключ Синтезатора');
  }

  // ── (b) фокус промпта ─────────────────────────────────────────────────
  {
    const m = moduleById('mod_factcheck');
    const ctx = mkPromptsCtx();
    ctx.route = '#/modules/factcheck/synthesizer/prompts.factcheck_verbalizer_system_prompt';
    ctx.workspace = computed.workspace.call(ctx);
    const focus = computed.workspacePromptFocus.call(ctx);
    assert.ok(focus, 'b: фокус найден');
    assert.strictEqual(focus.key,
      'prompts.factcheck_verbalizer_system_prompt', 'b: фокус по ключу маршрута');

    ctx.route = '#/modules/factcheck/synthesizer/unknown-key';
    ctx.workspace = computed.workspace.call(ctx);
    assert.strictEqual(computed.workspacePromptFocus.call(ctx), null,
      'b: неизвестный ключ → фокус не назначен (без падения)');
  }

  // ── (c) редактор виден сразу; аккордеон — не навигация ────────────────
  {
    // Шаблон workspace-промптов: главный textarea — не внутри <details>.
    const start = INDEX.indexOf('data-workspace-prompts');
    assert.ok(start >= 0, 'c: master-detail в шаблоне');
    const end = INDEX.indexOf('F3 (10.19, ADR-1019-3 D1/D4', start);
    const block = INDEX.slice(start, end > start ? end : start + 8000);
    assert.ok(block.indexOf('data-prompt-textarea') >= 0,
      'c: основной редактор промпта присутствует');
    assert.ok(block.indexOf('<details') < 0,
      'c: редактор НЕ спрятан в аккордеон');

    // promptsShowAccordion в новых раскладках = false (V2 ON).
    const sec = { advanced: [{ key: 'x' }] };
    assert.strictEqual(methods.promptsShowAccordion.call(
      { uiFlag() { return true; } }, sec), false,
      'c: V2 ON → аккордеон отключён');
  }

  // ── (d) один write-path ───────────────────────────────────────────────
  {
    // Канон: write-path F0 используется, второго канала записи промптов нет.
    assert.ok(APP_JS.indexOf('saveConfigItem: async function') >= 0,
      'd: канонический write-path F0');
    assert.ok(APP_JS.indexOf('persistItems(') >= 0, 'd: persistItems (F0)');
    // Нет «промпт-объекта» в localStorage/домене UI.
    assert.strictEqual(APP_JS.indexOf('localStorage.setItem(\'adminbot.prompt'), -1,
      'd: нет второго хранилища промптов');
  }

  // ── (e) две двери строятся корректно ──────────────────────────────────
  {
    const ws = {
      workspace: { module: moduleById('mod_factcheck'), slug: 'factcheck',
                   tab: 'synthesizer', stage: 'synthesizer', promptKey: '' },
      navigateTo(r) { this._nav = r; },
    };
    methods.openWorkspacePrompt.call(ws, { key: 'prompts.factcheck_analyst_system_prompt' });
    assert.strictEqual(ws._nav,
      '#/modules/factcheck/synthesizer/prompts.factcheck_analyst_system_prompt',
      'e: workspace-дверь с фокусом промпта');
    const lib = {
      routeSlugOf: methods.routeSlugOf,
      navigateTo(r) { this._nav = r; },
    };
    methods.openPromptLibrary.call(lib, moduleById('mod_factcheck'), 'synthesizer');
    assert.strictEqual(lib._nav, '#/ai/prompts/factcheck/synthesizer',
      'e: библиотека-дверь #/ai/prompts/<slug>/<stage>');
  }

  // ── (f) канон промптов не переписывается в JS-текстах ────────────────
  {
    // Промпты-каноны живут в services/**; app.js их не содержит/не меняет.
    const src = APP_JS;
    assert.ok(src.indexOf('FACTCHECK_SYSTEM_PROMPT') < 0,
      'f: канон не продублирован в web/app.js');
  }

  // ── (g) M-F5S-1: промпт из библиотеки открывает РЕДАКТОР ──────────────
  // Для модуля с промптами без объявленной промпт-вкладки (mod_summary,
  // mod_sleep) клик по промпту в библиотеке не должен строить
  // `#/modules/<slug>/prompts/<key>` (его `applyRoute` отбрасывает на
  // «Обзор»). Дверь библиотеки остаётся библиотекой; фокус — тот же объект.
  {
    const summaryItems = [
      { key: 'prompts.summary_system_prompt', category: 'prompts',
        group: 'prompts_summary', title: 'Системный промпт саммари',
        value: 'SUM-SYS' },
      { key: 'prompts.summary_cover_style', category: 'prompts',
        group: 'prompts_summary', title: 'Стиль обложки', value: 'COVER' },
      { key: 'prompts.summary_editor_system_prompt', category: 'prompts',
        group: 'prompts_summary', stage: 'synthesizer',
        title: 'Синтезатор саммари', value: 'EDIT' },
      { key: 'prompts.summary_narrator_system_prompt', category: 'prompts',
        group: 'prompts_summary', stage: 'verbalizer',
        title: 'Вербализатор саммари', value: 'NARR' },
    ];
    const ctx = mkPromptsCtx(summaryItems, 'prompts_summary');
    ctx.route = '#/ai/prompts/summary';
    ctx.workspace = computed.workspace.call(ctx);
    assert.strictEqual(ctx.workspace.door, 'library', 'g: дверь библиотеки');
    assert.strictEqual(ctx.workspace.module.id, 'mod_summary', 'g: модуль Саммари');
    // Шаблон рендерит редактор при workspaceTab ∈ prompts|synthesizer|verbalizer.
    assert.ok(['prompts', 'synthesizer', 'verbalizer']
      .indexOf(ctx.workspace.tab) >= 0, 'g: вкладка-редактор');
    assert.notStrictEqual(ctx.workspace.tab, 'overview', 'g: НЕ «Обзор»');

    // Клик по промпту без stage → ключ в маршруте библиотеки.
    const click1 = mkPromptsCtx(summaryItems, 'prompts_summary');
    click1.route = '#/ai/prompts/summary';
    click1.workspace = computed.workspace.call(click1);
    click1.navigateTo = function (r) { this._nav = r; };
    methods.openWorkspacePrompt.call(click1, summaryItems[1]);
    assert.strictEqual(click1._nav,
      '#/ai/prompts/summary/prompts.summary_cover_style',
      'g: библиотека + ключ (без несуществующей вкладки модуля)');

    // Маршрут после клика → редактор открыт на ИМЕННО выбранном промпте.
    const after1 = mkPromptsCtx(summaryItems, 'prompts_summary');
    after1.route = click1._nav;
    after1.workspace = computed.workspace.call(after1);
    assert.strictEqual(after1.workspace.tab, 'prompts', 'g: вкладка редактора');
    assert.strictEqual(after1.workspace.promptKey,
      'prompts.summary_cover_style', 'g: ключ промпта из hash');
    const focus1 = computed.workspacePromptFocus.call(after1);
    assert.strictEqual(focus1, summaryItems[1],
      'g: клик открыл выбранный промпт (один объект configItems)');

    // stage-промпт: маршрут сохраняет этап (не путает с ключом).
    const click2 = mkPromptsCtx(summaryItems, 'prompts_summary');
    click2.route = '#/ai/prompts/summary';
    click2.workspace = computed.workspace.call(click2);
    click2.navigateTo = function (r) { this._nav = r; };
    methods.openWorkspacePrompt.call(click2, summaryItems[3]);
    assert.strictEqual(click2._nav,
      '#/ai/prompts/summary/verbalizer/prompts.summary_narrator_system_prompt',
      'g: stage-промпт библиотеки');
    const after2 = mkPromptsCtx(summaryItems, 'prompts_summary');
    after2.route = click2._nav;
    after2.workspace = computed.workspace.call(after2);
    assert.strictEqual(computed.workspacePromptFocus.call(after2), summaryItems[3],
      'g: фокус по stage-маршруту библиотеки');

    // applyRoute НЕ отбрасывает библиотечный маршрут на «Обзор».
    const appCtx = {
      route: click1._nav, iaV2: true, me: { role_name: 'admin' },
      activeTab: 'status', tabs: TABS, modules: MODULES,
      configItems: summaryItems,
      canViewTab() { return true; }, _flagTabHidden: methods._flagTabHidden,
      toast() {}, syncBackButton() {}, setTab(id) { this.activeTab = id; },
      workspace: { module: moduleById('mod_summary') },
    };
    methods.applyRoute.call(appCtx, click1._nav);
    assert.strictEqual(appCtx.route, click1._nav,
      'g: library-маршрут не отброшен на #/modules/summary');
    assert.strictEqual(appCtx.activeTab, 'prompts', 'g: activeTab = prompts');

    // mod_sleep (prompts_memory, без stage) — та же ветка, что и Саммари.
    const sleepItems = [
      { key: 'prompts.extract_system_prompt', category: 'prompts',
        group: 'prompts_memory', title: 'Извлечение фактов', value: 'EX' },
      { key: 'prompts.compress_system_prompt', category: 'prompts',
        group: 'prompts_memory', title: 'Сжатие истории', value: 'CP' },
    ];
    const sctx = mkPromptsCtx(sleepItems, 'prompts_memory');
    sctx.route = '#/ai/prompts/sleep';
    sctx.workspace = computed.workspace.call(sctx);
    assert.strictEqual(sctx.workspace.module.id, 'mod_sleep', 'g: модуль Сна');
    assert.notStrictEqual(sctx.workspace.tab, 'overview', 'g: sleep не «Обзор»');
    sctx.navigateTo = function (r) { this._nav = r; };
    methods.openWorkspacePrompt.call(sctx, sleepItems[1]);
    assert.strictEqual(sctx._nav,
      '#/ai/prompts/sleep/prompts.compress_system_prompt',
      'g: sleep библиотека → ключ');
    const sAfter = mkPromptsCtx(sleepItems, 'prompts_memory');
    sAfter.route = sctx._nav;
    sAfter.workspace = computed.workspace.call(sAfter);
    assert.strictEqual(sAfter.workspace.tab, 'prompts', 'g: sleep редактор');
    assert.strictEqual(computed.workspacePromptFocus.call(sAfter), sleepItems[1],
      'g: sleep фокус — выбранный промпт');

    // factcheck (применимая вкладка synthesizer): дверь библиотеки сохранена.
    const fctx = mkPromptsCtx();
    fctx.route = '#/ai/prompts/factcheck';
    fctx.workspace = computed.workspace.call(fctx);
    fctx.navigateTo = function (r) { this._nav = r; };
    methods.openWorkspacePrompt.call(fctx, fctx.configItems[0]);
    assert.strictEqual(fctx._nav,
      '#/ai/prompts/factcheck/synthesizer/prompts.factcheck_analyst_system_prompt',
      'g: factcheck библиотека → stage + key');
    const fAfter = mkPromptsCtx();
    fAfter.route = fctx._nav;
    fAfter.workspace = computed.workspace.call(fAfter);
    assert.strictEqual(computed.workspacePromptFocus.call(fAfter),
      fAfter.configItems[0], 'g: factcheck фокус — тот же объект');
  }

  console.log('PROMPTS-SINGLE-SOURCE-OK');
  process.exit(0);
})();
