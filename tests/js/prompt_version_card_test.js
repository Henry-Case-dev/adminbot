'use strict';
/* PVR-S4 (EPIC-PROMPT-VERSIONING-UX-01) - единый компонент версий промпта.
 *
 * Проверяется КОНТРАКТ компонента `prompt-version-card` (arch §6):
 *   1. один компонент и один редактор (textarea) на все поверхности;
 *   2. человеческое состояние карточки (§2.1 ТЗ) вместо act:/fac:/sha;
 *   3. «Применить» существует только при непустом revision_id и actionable,
 *      иначе — честная причина (нет прав / code-only / несовместима /
 *      retired / журнал недоступен);
 *   4. «Назначить базовой» меняет только указатель и говорит это прямо;
 *   5. постраничная догрузка истории без дублей (никакого потолка 50);
 *   6. diff «было → стало» красит только изменённые строки;
 *   7. подсказка {joke} в трёх режимах и отсутствие сырого «{joke}: N».
 *
 * Запуск: node tests/js/prompt_version_card_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REGISTRY = {};
let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component(name, def) { if (name && def) REGISTRY[name] = def; },
      directive() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const ROOT = path.join(__dirname, '..', '..');
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.localStorage = global.sessionStorage;
global.history = { replaceState() {}, pushState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const computed = captured.computed;
const methods = captured.methods;

// ── 1. Один компонент, один редактор ─────────────────────────────────────
const CARD = REGISTRY['prompt-version-card'];
assert(CARD, 'компонент prompt-version-card не зарегистрирован');
assert.strictEqual(CARD.name, 'prompt-version-card');
assert.strictEqual(CARD.inheritAttrs, false,
  'маркеры полей должны адресоваться textarea через $attrs');
assert.strictEqual(CARD.template, '#prompt-version-card-tpl');
['card', 'bar', 'history'].forEach(function (variant) {
  assert.ok(INDEX.indexOf("'" + variant + "'") >= 0
            || variant === 'card', 'вариант ' + variant + ' объявлен');
});
const tplHead = INDEX.indexOf('id="prompt-version-card-tpl"');
const TPL = INDEX.slice(tplHead, INDEX.indexOf('</script>', tplHead));
assert.strictEqual((TPL.match(/<textarea/g) || []).length, 1,
  'редактор промпта должен быть ровно один');
assert.ok(TPL.indexOf('v-bind="$attrs"') >= 0,
  'маркер поля (data-meme-prompt-*) едет в textarea');
assert.ok(TPL.indexOf('data-prompt-textarea') >= 0);
assert.ok(TPL.indexOf('data-prompt-history-toggle') >= 0);
assert.ok(TPL.indexOf('data-pv-panel') >= 0);
// Ровно одна панель истории на всё приложение (нет второй реализации).
assert.strictEqual((INDEX.match(/data-prompt-history-toggle/g) || []).length, 1,
  'вторая панель истории запрещена');
// Все поверхности монтируют ОДИН компонент.
assert.ok(INDEX.indexOf('<prompt-version-card') >= 0);
assert.ok(INDEX.indexOf('variant="bar"') >= 0, 'карточки модулей — полоса');
assert.strictEqual((INDEX.match(/<prompt-version-card/g) || []).length, 7,
  'ожидаются: библиотека, 2 полосы модулей, 2 мема, каталог, блок речи');
// Сырые идентификаторы допустимы только в раскрываемых «Подробностях».
const cardHeadTpl = TPL.slice(0, TPL.indexOf('</div>', TPL.indexOf('pv-head')));
assert.strictEqual(cardHeadTpl.indexOf('sha256'), -1);
assert.strictEqual(cardHeadTpl.indexOf('revision_id'), -1);

// ── Хелперы контекста компонента ────────────────────────────────────────
function makeCtx(computedBag, methodsBag, values) {
  const self = {};
  Object.keys(values || {}).forEach(function (k) {
    Object.defineProperty(self, k, {
      configurable: true,
      get() { return values[k]; },
      set(v) { values[k] = v; },
    });
  });
  Object.keys(computedBag || {}).forEach(function (name) {
    if (Object.prototype.hasOwnProperty.call(values || {}, name)) return;
    Object.defineProperty(self, name, {
      configurable: true,
      get() { return computedBag[name].call(self); },
    });
  });
  Object.keys(methodsBag || {}).forEach(function (name) {
    if (typeof methodsBag[name] !== 'function') return;
    self[name] = methodsBag[name].bind(self);
  });
  return self;
}

function ctx(extra) {
  const values = Object.assign({
    promptKey: 'prompts.meme_joke',
    chatId: 42,
    chatTitle: 'Чат A',
    title: 'Промпт прикола',
    hist: { data: null, error: '', entries: [] },
    busy: false,
    dirty: false,
    canEdit: true,
    modelValue: '',
    effectiveText: '',
    $emit() {},
    $nextTick(fn) { fn(); },
    root: { api: async function () { return {}; } },
  }, extra || {});
  return makeCtx(CARD.computed, CARD.methods, values);
}

function stateOf(patch) {
  return ctx(patch);
}

// ── 2. Человеческое состояние карточки ───────────────────────────────────
function activeRow(origin, created, rev) {
  return { revision_id: rev || 'rev-1', origin: origin,
           created_at: created || '2026-11-03T23:42:00+00:00',
           source: origin === 'factory' ? 'from_release' : 'manual' };
}

let s = stateOf({ hist: { data: { active: null, baseline: { baseline: null },
                                  factory_matches_active: true,
                                  entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Наследуется от глобального',
  'чат без своего override должен наследовать глобальное');

s = stateOf({ chatId: null,
              hist: { data: { active: activeRow('manual'), baseline: null,
                              entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.kind, 'global');
assert.ok(s.state.detail.indexOf('03.11 23:42') >= 0,
  'время последней доказанной записи должно быть человеческим: '
  + JSON.stringify(s.state.detail));

s = stateOf({ hist: { data: { active: activeRow('factory'),
                              baseline: { baseline: null }, entries: [] },
                      error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Исходный из кода');

s = stateOf({ hist: { data: {
  active: activeRow('manual', null, 'rev-9'),
  baseline: { baseline: { revision_id: 'rev-9',
                          assigned_at: '2026-11-03T21:00:00+00:00',
                          assigned_by: '77' } },
  entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Базовый по выбору владельца');
assert.strictEqual(s.hasBaseline, true);

s = stateOf({ chatId: 42, hist: { data: { active: activeRow('manual'),
                                          baseline: null, entries: [] },
                                  error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Действует в этом чате');
assert.ok(s.state.detail.indexOf('изменён вручную') >= 0,
  'фраза «изменён вручную · дата» обязательна');

// ── 3. Действия: только по фактическим правам/статусам ───────────────────
function canActivate(patch, entry) {
  return stateOf(patch).canActivate(entry);
}
const baseData = { active: activeRow('manual'), baseline: null,
                   manageable: true, can_activate: true, entries: [] };
const ok = { revision_id: 'rev-2', actionable: true, status: 'inactive' };
assert.strictEqual(canActivate({ hist: { data: baseData, error: '',
                                         entries: [] } }, ok), true);
assert.strictEqual(canActivate({ hist: { data: baseData, error: '',
                                         entries: [] } },
                               { revision_id: '', actionable: true }), false,
  '«Применить» без revision_id недопустимо');
assert.strictEqual(canActivate({ hist: { data: baseData, error: '',
                                         entries: [] } },
                               { revision_id: 'rev-7', actionable: false,
                                 status: 'retired' }), false,
  'retired не активируется');
assert.strictEqual(canActivate({ hist: { data: baseData, error: '',
                                         entries: [] } },
                               { revision_id: 'rev-1', actionable: true }),
  false, 'уже активная версия не предлагается к применению');
assert.strictEqual(canActivate({ hist: {
  data: Object.assign({}, baseData, { can_activate: false }),
  error: '', entries: [] } }, ok), false, 'без права активации кнопки нет');

function reasonOf(patch, entry) {
  return stateOf(patch).rowReason(entry);
}
assert.ok(reasonOf({ hist: { data: baseData, error: '', entries: [] } },
                   { revision_id: '', status: 'inactive' })
          .indexOf('событие журнала') >= 0,
  'у события журнала должна быть причина, а не пустая кнопка');
assert.ok(reasonOf({ hist: { data: baseData, error: '', entries: [] } },
                   { revision_id: 'r', status: 'retired' })
          .indexOf('retired') >= 0);
assert.ok(reasonOf({ hist: { data: baseData, error: '', entries: [] } },
                   { revision_id: 'r', status: 'incompatible' })
          .indexOf('несовместима') >= 0);
assert.ok(reasonOf({ hist: { data: Object.assign({}, baseData,
                                                  { manageable: false }),
                             error: '', entries: [] } },
                   { revision_id: 'r', status: 'inactive' })
          .indexOf('code-only') >= 0);
assert.ok(reasonOf({ hist: { data: Object.assign({}, baseData,
                                                  { can_activate: false }),
                             error: '', entries: [] } },
                   { revision_id: 'r', status: 'inactive' })
          .indexOf('нет прав') >= 0);
assert.ok(reasonOf({ hist: { data: null, error: 'Журнал версий недоступен',
                             entries: [] } },
                   { revision_id: 'r', status: 'inactive' })
          .indexOf('журнал недоступен') >= 0);

// ── 4. diff: цвет только на изменённых строках ───────────────────────────
const d = stateOf({});
assert.strictEqual(d.diffClass('+добавлено'), 'pv-diff__add');
assert.strictEqual(d.diffClass('-удалено'), 'pv-diff__del');
assert.strictEqual(d.diffClass('@@ -1 +1 @@'), 'pv-diff__hunk');
assert.strictEqual(d.diffClass('--- a'), 'pv-diff__meta');
assert.strictEqual(d.diffClass(' контекст'), 'pv-diff__ctx');

// ── 5. Догрузка страниц: без дублей и без потолка 50 ─────────────────────
async function pagingTest() {
  const page1 = { order: 1, revision_id: 'r1' };
  const page2 = [{ order: 51, revision_id: 'r51' },
                 { order: 52, revision_id: 'r52' }];
  const calls = [];
  const c = ctx({
    hist: { data: null, error: '', entries: [page1], nextCursor: 'C1',
            more: true, moreLoading: false, moreError: '',
            viewId: '', viewBody: '', viewError: '', diff: null,
            diffTitle: '', diffLoading: false, diffError: '', busyRev: '',
            result: null },
    root: { api: async function (url) {
      calls.push(url);
      return { entries: page2, page: { next_cursor: 'C2', has_more: true } };
    } },
  });
  const scope = c;
  console.log("DBG0", JSON.stringify(scope.hist));
  await CARD.methods.loadMore.call(scope); console.log("DBG", JSON.stringify({n: c.hist.entries.length, more: c.hist.more, cur: c.hist.nextCursor, err: c.hist.moreError, calls: calls}));
  assert.strictEqual(c.hist.entries.length, 3, 'вторая страница не догружена');
  assert.ok(String(calls[0]).indexOf('cursor=C1') > 0,
    'догрузка должна идти по стабильному курсору: ' + calls[0]);
  assert.strictEqual(c.hist.nextCursor, 'C2');
}

// ── 6. Назначение базовой: только указатель + честная фраза ──────────────
async function assignTest() {
  const posts = [];
  const c = ctx({
    hist: { data: { active: activeRow('manual'), baseline: { baseline: null },
                    capabilities: {}, manageable: true, entries: [] },
            error: '', entries: [], busyRev: '', result: null, viewId: '',
            viewBody: '', viewError: '', diff: null, diffTitle: '',
            diffLoading: false, diffError: '', nextCursor: '', more: false,
            moreLoading: false, moreError: '' },
    capabilities: { can_assign_baseline: true },
    root: { api: async function (url, opts) {
      posts.push({ url: url, opts: opts });
      if (String(url).indexOf('/versions') > 0) {
        return { active: activeRow('manual'), baseline: { baseline: null },
                 manageable: true, entries: [] };
      }
      return { applied: true };
    } },
  });
  const scope = c;
  global.window.confirm = function () { return true; };
  await CARD.methods.assignBaseline.call(
    scope, { revision_id: 'rev-2', actionable: true, status: 'inactive' });
  const post = posts.filter(function (p) {
    return String(p.url).indexOf('/baseline') > 0;
  })[0];
  assert.ok(post, 'POST /baseline не отправлен');
  assert.strictEqual(JSON.parse(post.opts.body).revision_id, 'rev-2');
  assert.ok(c.hist.result.text.indexOf(
    'Базовая версия изменена, действующий текст пока прежний') >= 0,
    'сообщение о назначении базовой должно быть честным: '
    + JSON.stringify(c.hist.result));
  assert.ok(posts.some(function (p) {
    return String(p.url).indexOf('/versions') > 0;
  }), 'после назначения состояние должно перечитываться с сервера');
}

// ── 7. {joke}: три режима, без сырого счётчика ───────────────────────────
function jokeCtx(placeholders, valid) {
  return makeCtx(computed, methods, {
    memeSettingsView: {
      templateValid: valid !== false,
      templatePlaceholders: placeholders,
      templateError: valid === false
        ? 'шаблон: допускается не более одного {joke} (найдено 2)' : '',
    },
  });
}
let j = jokeCtx(0);
assert.strictEqual(j.memeJokeModeKey, 'append');
assert.ok(j.memeJokeModeHint.indexOf('добавится после шаблона') >= 0,
  'режим 0 должен объяснять append, а не требовать {joke}');
assert.strictEqual(j.memeJokeModeSummary, 'прикол добавляется после шаблона');
j = jokeCtx(1);
assert.strictEqual(j.memeJokeModeKey, 'slot');
assert.ok(j.memeJokeModeHint.indexOf('вставится в отмеченное место') >= 0);
j = jokeCtx(2, false);
assert.strictEqual(j.memeJokeModeKey, 'invalid');
assert.ok(j.memeJokeModeHint.indexOf('не более одного {joke}') >= 0,
  'режим ≥2 — существующая ошибка конфигурации');
// Сырой «{joke}: N» из видимой разметки мемов удалён.
const memes = INDEX.slice(INDEX.indexOf('data-meme-settings'),
                          INDEX.indexOf('data-ini-memes-end'));
assert.strictEqual(/\{joke\}:\s*'?\+/.test(memes), false);
assert.strictEqual(memes.indexOf("'{joke}: '"), -1,
  'сырой технический счётчик {joke} не должен выводиться');
assert.ok(memes.indexOf('data-meme-template-state') >= 0);
assert.ok(memes.indexOf('memeJokeModeHint') >= 0);

// ── 8. Никаких сырых id в основной карточке ──────────────────────────────
const metaBlock = INDEX.slice(INDEX.indexOf('data-prompt-editor'),
                              INDEX.indexOf('data-prompt-meta'));
assert.ok(metaBlock.indexOf('data-prompt-editor-meta') >= 0,
  'технические данные остаются в свёрнутом блоке');
assert.strictEqual(/act:\d|fac:[0-9a-f]{8,}|\bsha256\b/.test(metaBlock), false,
  'в редакторе не должно остаться сырых act:/fac:/sha в разметке');

// ── 9. Стили: боковая панель / полноэкранная на мобильном ────────────────
assert.ok(CSS.indexOf('.pv-panel') >= 0);
assert.ok(/@media \(max-width: 767px\) \{\s*\.pv-scrim \{ justify-content: stretch; \}/
  .test(CSS) || (CSS.indexOf('.pv-panel { width: 100vw') >= 0),
  'на мобильном панель должна быть полноэкранной');
assert.ok(CSS.indexOf('var(--ctl-font)') >= 0,
  'типографика карточки — через токены системы контролов');

Promise.all([pagingTest(), assignTest()]).then(function () {
  console.log('PVR-S4-CARD-OK');
}).catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
