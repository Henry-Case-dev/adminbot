'use strict';
/* F4 round1024 (dossier-live-feed-round1024, ADR-1024-8) →
 * M4B B1 (MOD-ACL-UX-01, MAC-S6-FEED-01/02/03, MAC-S15-03, AC-16) —
 * РЕАЛЬНЫЙ JS-тест пятой ленты «Досье» на «Статусе»:
 *   - `dossierPeopleFeed` — person-centric проекция того же dossier_feed:
 *     один участник = одна строка (последняя запись, число записей, чат),
 *     а не 1:1 копия «Новых фактов» и не второй API/store;
 *   - identity: user_id → имя → честная строка «Участники не определены»;
 *     дата записи (`created_at`) не подменяется датой события/подтверждения;
 *   - `openFeedDossier`:
 *       · user_id=null → НЕ вызывается openDossier (нет ложного affordance);
 *       · GLOBAL (activeChatId пуст) → сначала setActiveChat(chat_id),
 *         затем openDossier с верным user_id;
 *       · активный чат совпадает → setActiveChat НЕ вызывается;
 *       · chat_id null/0 → toast, модалка не открывается (контракт §3.2(2));
 *       · ошибка setActiveChat → toast, модалка не открывается;
 *   - `loadDossierFeed`: chat_id-фильтр реально работает, global — без него;
 *     ответ прошлой области отбрасывается (S15-03);
 *   - wiring: досье — пятая секция единого виджета; нижней карточки,
 *     тикера/клонов и старого kill-switch больше нет; клик открывает
 *     существующее окно записи, provenance/даты — реальные;
 *   - статика: CSP/no-CDN, один endpoint.
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
assert(computed && computed.dossierPeopleFeed, 'dossierPeopleFeed — computed');
assert.strictEqual(computed.dossierFeedLoop, undefined,
  'мёртвая 1:1-модель тикера удалена');
assert.strictEqual(computed.dossierFeedSpeed, undefined,
  'мёртвая скорость тикера удалена');
assert(methods && methods.openFeedDossier, 'root.methods.openFeedDossier');
assert(methods && methods.uiFlag, 'root.methods.uiFlag');
assert.strictEqual(typeof methods.chatTitleFor, 'function',
  'root.methods.chatTitleFor (подпись чата)');

function row(over) {
  return Object.assign({
    chat_id: -100, name: 'A', user_name: 'Аня', user_id: 5,
    excerpt: 'факт A', text: 'Аня любит кофе', created_at: 100,
    message_timestamp: 900, last_confirmed_at: 120,
    origin: 'chat_history', id: 1, tg_message_id: 11,
  }, over || {});
}

// ── 1. dossierPeopleFeed: person-проекция + дубли ───────────────────────────
(function () {
  const rows = computed.dossierPeopleFeed.call({
    dossierFeed: [
      row({ id: 1, created_at: 100, excerpt: 'факт A' }),
      row({ id: 2, chat_id: -200, excerpt: 'факт A2', created_at: 200,
        origin: 'summary' }),
      row({ id: 3, name: 'B', user_name: 'B', user_id: null,
        excerpt: 'факт B', created_at: 150 }),
      row({ id: 4, name: null, user_name: null, user_id: null,
        excerpt: 'сырое', created_at: 120 }),
    ],
    chatTitleFor(id) { return String(id) === '-100' ? 'Чат А' : ''; },
  });
  assert.strictEqual(rows.length, 3,
    '4 записи → 3 участника (не 1:1 копия «Новых фактов»)');
  assert.deepStrictEqual(rows.map((r) => r.name),
    ['Аня', 'B', 'Участники не определены']);
  const anya = rows[0];
  assert.strictEqual(anya.count, 2, 'число записей участника');
  assert.strictEqual(anya.key, 'u:5', 'ключ identity по user_id');
  assert.strictEqual(anya.latest.id, 2, 'последняя запись по created_at');
  assert.strictEqual(anya.last_at, 200, 'дата записи, не события');
  assert.strictEqual(anya.latest.event_at, 900,
    'дата события хранится отдельно и не подменяет дату записи');
  assert.strictEqual(anya.chatLabel, 'разные чаты',
    'один человек в двух чатах — честная подпись');
  assert.strictEqual(anya.scopePrefix, 'разные чаты · ');
  assert.ok(anya.originLabel.indexOf('chat_history') >= 0
    && anya.originLabel.indexOf('summary') >= 0, 'provenance из реальных origin');
  const b = rows[1];
  assert.strictEqual(b.key, 'n:B', 'fallback identity по имени');
  assert.strictEqual(b.user_id, null, 'user_id не выдумывается');
  assert.strictEqual(b.chatLabel, 'Чат А');
  assert.strictEqual(rows[2].known, false, 'неизвестный участник — честно');
  assert.strictEqual(rows[2].key, 'unknown');
  rows.forEach((r) => {
    assert.ok(r.latest && r.latest.key.indexOf('ff|') === 0,
      'строке доступна существующая запись для окна деталей');
    assert.ok(r.count >= 1);
  });
  assert.strictEqual(rows.reduce((n, r) => n + r.count, 0), 4,
    'ни одна запись не потеряна и не задвоена');
})();

// ── 2. Пустая лента / детерминизм / подпись чата ───────────────────────────
(function () {
  assert.strictEqual(computed.dossierPeopleFeed.call({
    dossierFeed: [], chatTitleFor() { return ''; },
  }).length, 0, 'пустая лента → пусто');
  const one = computed.dossierPeopleFeed.call({
    dossierFeed: [row({ id: 9 })],
    chatTitleFor() { return 'Чат А'; },
  });
  assert.deepStrictEqual(one.map((r) => r.key), ['u:5'], 'уникальные ключи');
  const twice = computed.dossierPeopleFeed.call({
    dossierFeed: [row({ id: 9 })],
    chatTitleFor() { return 'Чат А'; },
  });
  assert.deepStrictEqual(twice.map((r) => r.key), one.map((r) => r.key),
    'проекция детерминирована (без дублей при обновлении)');
  const noTitle = computed.dossierPeopleFeed.call({
    dossierFeed: [row({ chat_id: -777 })],
    chatTitleFor() { return ''; },
  });
  assert.strictEqual(noTitle[0].chatLabel, 'Чат -777',
    'нет названия — честный id, не выдуманное имя');
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

  // 3a-2. chat_id null/0 → toast, чат не переключаем, модалку не открываем.
  {
    const toasts = [];
    let switched = 0, opened = 0;
    const ctx = {
      activeChatId: -100,
      toast(m) { toasts.push(m); },
      setActiveChat() { switched += 1; },
      async openDossier() { opened += 1; },
    };
    await methods.openFeedDossier.call(ctx,
      { chat_id: null, user_id: 5, name: 'A', user_name: 'Аня' });
    await methods.openFeedDossier.call(ctx,
      { chat_id: 0, user_id: 5, name: 'A', user_name: 'Аня' });
    assert.strictEqual(switched, 0, 'неизвестный чат → без setActiveChat');
    assert.strictEqual(opened, 0, 'неизвестный чат → модалка не открыта');
    assert.strictEqual(toasts.length, 2, 'неизвестный чат → toast');
  }

  // 3b. GLOBAL (нет активного чата) → setActiveChat, затем openDossier.
  {
    const order = [];
    let opened = null;
    const ctx = {
      activeChatId: null,
      toast() {},
      setActiveChat(id) { order.push('chat:' + id); this.activeChatId = parseInt(id, 10); },
      async openDossier(rowArg) { opened = rowArg; order.push('dossier'); },
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
      async openDossier(rowArg) { opened = rowArg; },
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

// ── 4. loadDossierFeed: chat_id/global + epoch-guard смены области ─────────
(async function () {
  // 4a. Конкретный чат → chat_id в запросе; global → без chat_id.
  {
    const calls = [];
    const ctx = {
      activeChatId: -100, dossierFeedBusy: false, dossierFeed: [],
      dossierFeedError: '', dossierFeedLoaded: false, dossierFeedAt: 0,
      scopeEpoch: 1,
      _scopeGuard(ep) { return ep === this.scopeEpoch; },
      loreErrText(e) { return String(e); },
      async api(url) {
        calls.push(url);
        return { items: [{ chat_id: -100, name: 'A', excerpt: 'x' }] };
      },
    };
    await methods.loadDossierFeed.call(ctx);
    assert.strictEqual(calls.length, 1, 'один запрос ленты');
    assert.ok(calls[0].indexOf('chat_id=-100') >= 0,
      'конкретный чат → фильтр chat_id в запросе');
    assert.strictEqual(ctx.dossierFeed.length, 1, 'лента заполнена');
    ctx.activeChatId = null;
    await methods.loadDossierFeed.call(ctx);
    assert.ok(calls[1].indexOf('chat_id') < 0, 'global → без chat_id');
  }

  // 4b. Смена области до ответа → чужие данные не попадают в новый чат.
  {
    let resolveApi;
    const ctx = {
      activeChatId: -100, dossierFeedBusy: false, dossierFeed: [],
      dossierFeedError: '', dossierFeedLoaded: false, dossierFeedAt: 0,
      scopeEpoch: 1,
      _scopeGuard(ep) { return ep === this.scopeEpoch; },
      loreErrText(e) { return String(e); },
      api() { return new Promise((r) => { resolveApi = r; }); },
    };
    const load = methods.loadDossierFeed.call(ctx);
    ctx.scopeEpoch = 2;
    resolveApi({ items: [{ chat_id: -100, name: 'A', excerpt: 'stale' }] });
    await load;
    assert.strictEqual(ctx.dossierFeed.length, 0,
      'ответ прошлой области отброшен (S15-03)');
    assert.strictEqual(ctx.dossierFeedLoaded, false);
  }

  // 4c. 503 — причина, а не «0 записей».
  {
    const ctx = {
      activeChatId: null, dossierFeedBusy: false, dossierFeed: [],
      dossierFeedError: '', dossierFeedLoaded: false, dossierFeedAt: 0,
      scopeEpoch: 4,
      _scopeGuard(ep) { return ep === this.scopeEpoch; },
      loreErrText(e) { return 'HTTP ' + e.status; },
      async api() { throw Object.assign(new Error('x'), { status: 503 }); },
    };
    await methods.loadDossierFeed.call(ctx);
    assert.strictEqual(ctx.dossierFeedError, 'HTTP 503');
    assert.deepStrictEqual(ctx.dossierFeed, [], '503 не выдаёт себя за пустую ленту');
  }
})();

// ── 5. Wiring: пятая секция, старой карточки/тикера/флага нет ─────────────
(function () {
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  const CSS = fs.readFileSync(
    path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
  assert(INDEX.indexOf('data-intel-section="dossier"') !== -1,
    'досье — пятая секция единого виджета');
  assert(INDEX.indexOf('data-ribbon="dossier"') !== -1,
    'ключ секции для сохранения позиции');
  assert(INDEX.indexOf('v-sfeed="statusRecordOpen"') !== -1,
    'досье — на общем контроллере лент');
  assert(INDEX.indexOf('openStatusRecord(\'fact\', it.latest, $event)') !== -1,
    'клик открывает существующее окно записи');
  assert(INDEX.indexOf('dossierPeopleAriaLabel(it)') !== -1, 'a11y-подпись строки');
  assert(INDEX.indexOf('data-status-dossier') === -1,
    'нижняя карточка «Живая лента досье» удалена');
  assert(INDEX.indexOf('dossier-ticker') === -1,
    'дублирующий тикер и клоны удалены');
  assert(INDEX.indexOf('DOSSIER_LIVE_FEED_ENABLED') === -1,
    'старый kill-switch тикера больше не управляет лентой');
  assert(INDEX.indexOf('data-rec-dossier') !== -1,
    'вторичное действие «Досье субъекта» сохранено');
  assert(APP_JS.indexOf('dossierPeopleFeed') !== -1, 'проекция во фронте');
  assert(APP_JS.indexOf('dossierFeedLoop') === -1, 'мёртвая модель удалена');
  assert(APP_JS.indexOf('dossierFeedSpeed') === -1, 'мёртвая скорость удалена');
  assert(APP_JS.indexOf('ui_flags') !== -1, 'uiFlag читает this.me.ui_flags');
  assert(CSS.indexOf('.dossier-ticker') === -1, 'CSS тикера удалён');
  assert(CSS.indexOf('.status-dossier__track') === -1, 'CSS нижней карточки удалён');
  assert(CSS.indexOf('.sfeed-item__badge--dossier') !== -1,
    'общий слой строк используется и для досье');
  assert(CSS.indexOf('prefers-reduced-motion') !== -1, 'reduced-motion сохранён');
  for (const lib of ['cdn.jsdelivr.net', 'unpkg.com', 'http://', 'https://']) {
    assert(INDEX.indexOf(lib) === -1, 'без внешних ресурсов (CSP): ' + lib);
  }
})();

console.log('DOSSIER-FEED-OK');
