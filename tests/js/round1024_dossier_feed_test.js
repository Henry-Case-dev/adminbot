'use strict';
/* F4 round1024 (dossier-live-feed-round1024, ADR-1024-8, UPD2 п.2 + UPD3 №9) —
 * РЕАЛЬНЫЙ JS-тест «Живой ленты досье»:
 *   - `dossierFeedLoop` дублирует элементы (seamless), ключи уникальны,
 *     переносит user_id/user_name/chat_id (кликабельность);
 *   - `dossierFeedSpeed` = max(72s, items × 6s) — заметно медленнее 42s;
 *   - `openFeedDossier`:
 *       · user_id=null → НЕ вызывается openDossier (нет ложного affordance);
 *       · GLOBAL (activeChatId пуст) → сначала setActiveChat(chat_id),
 *         затем openDossier с верным user_id;
 *       · активный чат совпадает → setActiveChat НЕ вызывается;
 *       · ошибка setActiveChat → toast, модалка не открывается;
 *   - wiring: шаблон гейтит uiFlag('DOSSIER_LIVE_FEED_ENABLED'), вертикальная
 *     дорожка/`role=button`/keydown, OFF-ветка сохраняет горизонталь;
 *   - статика: флаг доставляется через ui_flags; CSP/no-CDN.
 *
 * Запуск: node tests/js/round1024_dossier_feed_test.js  → DOSSIER-FEED-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component(name, compOpts) {
        global.__components = global.__components || {};
        global.__components[name] = compOpts;
      },
      provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const _bodyChildren = [];
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() {
        const idx = _bodyChildren.indexOf(this);
        if (idx >= 0) _bodyChildren.splice(idx, 1);
      },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) {
      const idx = _bodyChildren.indexOf(el);
      if (idx >= 0) _bodyChildren.splice(idx, 1);
      return el;
    },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('x'); } } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

const ROOT = path.join(__dirname, '..', '..');
require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
assert(computed && computed.dossierFeedLoop, 'dossierFeedLoop — computed');
assert(computed && computed.dossierFeedSpeed, 'dossierFeedSpeed — computed');
assert(methods && methods.openFeedDossier, 'root.methods.openFeedDossier');
assert(methods && methods.uiFlag, 'root.methods.uiFlag');

// ── 1. dossierFeedLoop: дублирование + ключи + user_id/user_name ────────────
(function () {
  const loop = computed.dossierFeedLoop.call({
    dossierFeed: [
      { chat_id: -100, name: 'A', excerpt: 'факт A', user_id: 5, user_name: 'Аня' },
      { chat_id: -200, name: 'B', excerpt: 'факт B', user_id: null },
    ],
    oversightData: { chats: [{ chat_id: -100, title: 'Чат А' }] },
  });
  assert.strictEqual(loop.length, 4, 'лента дублируется (2×2)');
  assert.strictEqual(loop[0].key !== loop[2].key, true, 'ключи дублей уникальны');
  assert.strictEqual(loop[0].chatLabel, 'Чат А');
  assert.strictEqual(loop[1].chatLabel, 'Чат -200', 'неизвестный чат → id');
  assert.strictEqual(loop[0].user_id, 5, 'user_id перенесён');
  assert.strictEqual(loop[0].user_name, 'Аня', 'user_name перенесён');
  assert.strictEqual(loop[1].user_id, null, 'null user_id сохраняется');
  assert.strictEqual(loop[1].user_name, 'B', 'fallback user_name = name');
  assert.strictEqual(loop[0].chat_id, -100, 'chat_id перенесён');
  assert.strictEqual(
    computed.dossierFeedLoop.call({ dossierFeed: [] }).length, 0,
    'пустая лента → пусто');
})();

// ── 2. dossierFeedSpeed = max(72s, items × 6s) ──────────────────────────────
(function () {
  const speed = function (n) {
    return computed.dossierFeedSpeed.call({ dossierFeed: new Array(n) });
  };
  assert.strictEqual(speed(0), '72s');
  assert.strictEqual(speed(2), '72s', 'короткий список — база 72s');
  assert.strictEqual(speed(12), '72s');
  assert.strictEqual(speed(20), '120s', '20×6=120 > 72');
  // Заметно медленнее прежней горизонтали 42s.
  assert.ok(parseInt(speed(12), 10) >= 72, 'скорость ≥ 72s (медленнее 42s)');
})();

// ── 3. openFeedDossier: клик-путь GLOBAL → чат → досье ──────────────────────
(async function () {
  // 3a. user_id=null → ничего не вызываем.
  {
    let called = 0;
    const ctx = {
      activeChatId: null,
      toast() { called += 1; },
      setActiveChat() { called += 1; },
      async openDossier() { called += 1; },
    };
    methods.openFeedDossier.call(ctx, { chat_id: -100, user_id: null, name: 'X' });
    methods.openFeedDossier.call(ctx, null);
    assert.strictEqual(called, 0, 'null user_id → нет вызова (нет affordance)');
  }

  // 3b. GLOBAL (нет активного чата) → setActiveChat, затем openDossier.
  {
    const order = [];
    let opened = null;
    const ctx = {
      activeChatId: null,
      toast() {},
      setActiveChat(id) { order.push('chat:' + id); this.activeChatId = parseInt(id, 10); },
      async openDossier(row) { opened = row; order.push('dossier'); },
    };
    await methods.openFeedDossier.call(ctx, {
      chat_id: -100, user_id: 5, name: 'A', user_name: 'Аня',
    });
    assert.deepStrictEqual(order, ['chat:-100', 'dossier'], 'сначала чат, затем досье');
    assert.strictEqual(opened.user_id, 5, 'верный user_id');
    assert.strictEqual(opened.name, 'Аня', 'канон-имя из user_name');
  }

  // 3c. Активный чат совпадает → openDossier сразу (без переключения).
  {
    let switched = 0, opened = null;
    const ctx = {
      activeChatId: -100,
      toast() {},
      setActiveChat() { switched += 1; },
      async openDossier(row) { opened = row; },
    };
    await methods.openFeedDossier.call(ctx, {
      chat_id: -100, user_id: 7, name: 'B', user_name: 'Борис',
    });
    assert.strictEqual(switched, 0, 'тот же чат → без setActiveChat');
    assert.strictEqual(opened.user_id, 7);
  }

  // 3d. Ошибка переключения → toast, модалка НЕ открывается.
  {
    let opened = 0, toasts = [];
    const ctx = {
      activeChatId: null,
      toast(m) { toasts.push(m); },
      setActiveChat() { throw new Error('scope fail'); },
      async openDossier() { opened += 1; },
    };
    await methods.openFeedDossier.call(ctx, {
      chat_id: -200, user_id: 9, name: 'C', user_name: 'C',
    });
    assert.strictEqual(opened, 0, 'ошибка переключения → модалка не открыта');
    assert.ok(toasts.length >= 1, 'ошибка → понятный toast');
  }
})();

// ── 4. Kill-switch uiFlag('DOSSIER_LIVE_FEED_ENABLED') ──────────────────────
(function () {
  assert.strictEqual(methods.uiFlag.call({ me: null },
    'DOSSIER_LIVE_FEED_ENABLED'), true);
  assert.strictEqual(methods.uiFlag.call(
    { me: { ui_flags: { DOSSIER_LIVE_FEED_ENABLED: false } } },
    'DOSSIER_LIVE_FEED_ENABLED'), false);
})();

// ── 5. Wiring: шаблон вертикален/кликабелен, OFF = горизонталь ───────────────
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  const CSS = fs.readFileSync(
    path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
  assert(INDEX.indexOf("uiFlag('DOSSIER_LIVE_FEED_ENABLED')") !== -1,
    'шаблон гейтит флаг');
  assert(INDEX.indexOf('dossier-ticker--y') !== -1, 'вертикальная лента');
  assert(INDEX.indexOf('dossier-ticker__item--click') !== -1, 'строка-кнопка');
  assert(INDEX.indexOf('@keydown.enter.prevent') !== -1, 'клавиатура a11y');
  assert(INDEX.indexOf('openFeedDossier(it)') !== -1, 'клик → досье');
  assert(INDEX.indexOf('role="marquee"') !== -1, 'OFF: горизонтальный тикер');
  assert(APP_JS.indexOf('dossierFeedSpeed') !== -1, 'скорость во фронте');
  assert(APP_JS.indexOf('ui_flags') !== -1, 'uiFlag читает this.me.ui_flags');
  assert(CSS.indexOf('@keyframes dossier-ticker-scroll-y') !== -1,
    'вертикальный keyframe');
  assert(CSS.indexOf('@keyframes dossier-ticker-scroll') !== -1,
    'горизонтальный keyframe (OFF) сохранён');
  assert(CSS.indexOf('translateY') !== -1, 'движение по Y');
  assert(CSS.indexOf('prefers-reduced-motion') !== -1, 'reduced-motion сохранён');
  for (const lib of ['cdn.jsdelivr.net', 'unpkg.com', 'http://', 'https://']) {
    assert(INDEX.indexOf(lib) === -1, 'без внешних ресурсов (CSP): ' + lib);
  }
})();

console.log('DOSSIER-FEED-OK');
