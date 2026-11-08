'use strict';
/* MEM-08-S3 — единое поле «Найти в памяти» (omnibox) в когнитивной карте.
 *
 * TEST-LIFECYCLE: CONTRACT owner=MEM-08-S3
 * Авторитет: `plans/features/memory-cognitive-02/contracts.md` §4.3/§4.9/
 * §4.10, §10 (Visual Preservation Map), MEM-08.14/08.19/08.20/08.23/08.25 и
 * артефакт S1 `plans/features/memory-cognitive-02/search-read-model.md` §1/§3.
 *
 * Что закрепляется (без браузера — только чистые функции адаптера и методы
 * корневого vm; DOM/vis-network не требуются):
 *   * четыре исхода `no_matches` / `no_rights` / `error` / `cursor_stale`
 *     дают РАЗНЫЕ пользовательские состояния (ошибка никогда не выглядит как
 *     «ничего не найдено»), `cursor_stale` — тихий перезапуск без пустого экрана;
 *   * debounce 120–180 мс и отмена предыдущего запроса; поздний ответ
 *     («Пап») не перетирает свежий («Папаха»);
 *   * клавиатура ArrowUp/Down/Enter/Escape и IME-композиция;
 *   * локальный синхронный отклик по загруженной сцене;
 *   * блок сообществ: три честных состояния, отсутствующая метрика —
 *     «Неизвестно», нейтральная подпись не выдаётся за категорию.
 *
 * Запуск: node tests/js/mem08_omnibox_test.js   (маркер MEM-08-S3-OK)
 */
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const CM = require(path.join(ROOT, 'web', 'static', 'cognitive-map.js'));

let checks = 0;
function ok(cond, message) {
  assert.ok(cond, message);
  checks += 1;
}
function eq(actual, expected, message) {
  assert.deepStrictEqual(actual, expected, message);
  checks += 1;
}

// ─── 1. Адаптер: исходы поиска различимы и честны ───────────────────────────
const UI = CM.SEARCH_UI;
ok(UI.NO_MATCHES !== UI.NO_RIGHTS && UI.NO_RIGHTS !== UI.ERROR
  && UI.ERROR !== UI.NO_MATCHES, 'три исхода обязаны быть разными токенами');

const noMatches = CM.searchStateFromResponse({
  status: 'empty', query_state: 'no_matches', reason_code: 'retrieval_empty',
  items: [], next_cursor: null, has_more: false,
});
const noRights = CM.searchStateFromResponse({
  status: 'forbidden', query_state: 'no_rights', reason_code: 'no_rights',
  items: [], next_cursor: null, has_more: false,
});
const failure = CM.searchStateFromResponse({
  status: 'error', query_state: 'error', reason_code: 'retrieval_error',
  items: [], next_cursor: null, has_more: false,
});
const stale = CM.searchStateFromResponse({
  status: 'cursor_stale', query_state: 'local_matches',
  reason_code: 'cursor_revision_mismatch', items: [],
  next_cursor: null, has_more: false,
});
eq(noMatches.state, UI.NO_MATCHES, 'empty/no_matches → no_matches');
eq(noRights.state, UI.NO_RIGHTS, 'forbidden/no_rights → no_rights');
eq(failure.state, UI.ERROR, 'error/error → error');
eq(stale.state, UI.CURSOR_STALE, 'cursor_stale — отдельный технический исход');
ok(noMatches.text !== failure.text, 'сбой и «нет совпадений» различаются словами');
ok(noRights.text !== noMatches.text, '«нет прав» не превращается в «нет данных»');
eq(stale.retryFirstPage, true, 'cursor_stale → тихий перезапуск первой страницы');
eq(stale.text, '', 'cursor_stale не рисует текст пустого состояния');
eq(stale.canRetry, false, 'cursor_stale не просит пользователя повторять вручную');
eq(failure.canRetry, true, 'у сетевой/технической ошибки есть действие повтора');
eq(CM.searchStateFromResponse(null).state, UI.ERROR,
  'битый/пустой ответ — error, не «ничего не найдено»');

// Кандидаты: строки без внутренних ID, смысловое совпадение помечено честно.
const candidates = CM.searchStateFromResponse({
  status: 'ok', query_state: 'candidates', items: [{
    ref_kind: 'entity', canonical_id: 'ent:-1001:42', title: 'Кирилл',
    category: 'Человек', snippet: 'обсуждали оптику', match_cause: 'semantic',
    evidence_status: 'legacy', event_ts: 1760000000, ambiguity: null,
    focus: { chat_id: -1001, node_id: 42 },
  }], next_cursor: null, has_more: false,
});
eq(candidates.state, UI.CANDIDATES, 'candidates → есть релевантные результаты');
eq(candidates.canRetry, false, 'у найденных результатов нет «повторить»');
eq(noMatches.canRetry, false, '«нет совпадений» не предлагает повтор');
eq(noRights.canRetry, false, '«нет прав» не предлагает повтор');
eq(candidates.items.length, 1, 'строка результата построена');
const row = candidates.items[0];
ok(row.title === 'Кирилл' && row.category === 'Человек', 'заголовок и категория');
ok(row.metaLine.indexOf('источник не указан') >= 0,
  'legacy-запись честно помечена «источник не указан»');
ok(row.metaLine.indexOf('может относиться к запросу') >= 0,
  'смысловое совпадение не выдаётся за точное');
ok(JSON.stringify([row.title, row.metaLine, row.snippet]).indexOf('ent:') < 0,
  'внутренний ID не попадает в видимый текст (S-7)');
ok(row.focusNodeId === '42', 'focus.node_id нужен обработчику выбора');
eq(row.evidenceLabel, 'источник не указан', 'подпись статуса достоверности');

// Неоднозначность → варианты, «самый популярный» не выбирается (MEM-08.22).
const ambiguous = CM.searchStateFromResponse({
  status: 'ambiguous', query_state: 'candidates', items: [{
    ref_kind: 'entity', canonical_id: 'ent:-1001:7', title: 'Папаха',
    category: 'Человек', match_cause: 'exact_name', evidence_status: 'tentative',
    ambiguity: { reason: 'same_name', variants: [
      { title: 'Папаха (человек)' }, { title: 'Папаха (предмет)' }] },
  }],
});
eq(ambiguous.state, UI.AMBIGUOUS, 'variants → ambiguous, а не «выбран один»');
eq(ambiguous.items[0].variants.length, 2, 'оба реальных варианта показаны');

// Debounce/страница — в контрактном диапазоне (§4.8: 120–180 мс; 6–8 строк).
ok(CM.DEFAULTS.searchDebounceMs >= 120 && CM.DEFAULTS.searchDebounceMs <= 180,
  'debounce в пределах 120–180 мс');
ok(CM.DEFAULTS.searchPageSize >= 6 && CM.DEFAULTS.searchPageSize <= 8,
  'страница подсказок 6–8 результатов');

// Гейт (§4.10): поле есть только при включённом гейте.
eq(CM.searchGateEnabled({ search: { enabled: true } }), true, 'гейт ON прочитан');
eq(CM.searchGateEnabled({}), false, 'без поля — OFF-паритет');
eq(CM.searchGateEnabled(null), false, 'битый payload — OFF, не «включено»');

// ─── 2. Блок сообществ: три честных состояния + неизвестное ≠ 0 ────────────
const noTables = CM.communitiesView({ state: 'unavailable', reason_code: 'tables_absent' });
eq(noTables.state, 'unavailable', 'нет таблиц — не пустой успех');
ok(noTables.text.indexOf('н/д') >= 0, '«Сообщества: н/д» для unavailable');

const noBuild = CM.communitiesView({ state: 'no_active_build', reason_code: 'no_active_build' });
eq(noBuild.state, 'no_active_build', 'нет активной сборки — отдельное состояние');
ok(/не собраны/.test(noBuild.text), 'честный текст «ещё не собраны»');

const emptyProven = CM.communitiesView({
  state: 'ok', reason_code: 'no_proven_communities', items: [],
  total: 0, shown: 0, truncated: false,
});
eq(emptyProven.state, 'none', 'ok без proven-набора — не «все сообщества»');
ok(emptyProven.items.length === 0, 'фейковых сообществ не появляется');

const realBlock = CM.communitiesView({
  state: 'ok', reason_code: null, total: 2, shown: 1, truncated: true,
  items: [{
    community_id: 'c-1', member_count: 3, label: 'Сообщество: Кирилл, Лёха',
    label_kind: 'named', label_basis: 'доминирующее имя', dominant_names: ['Кирилл'],
    metrics: { confirmed_links: null, tentative_links: 2 },
    metrics_basis: 'partial',
  }],
});
eq(realBlock.state, 'ok', 'реальные сообщества показаны');
eq(realBlock.items[0].label, 'Сообщество: Кирилл, Лёха', 'подпись из сборки');
eq(realBlock.items[0].labelKind, 'named', 'подпись семантическая — named');
eq(realBlock.items[0].confirmedLinks, null, 'неизвестная метрика остаётся null');
ok(realBlock.items[0].memberText.indexOf('3') === 0, 'member_count реальный');
ok(realBlock.truncated === true && realBlock.total === 2,
  'усечение блока видно числами');

const neutral = CM.communitiesView({
  state: 'ok', items: [{
    community_id: 'c-2', member_count: 2, label: 'Сообщество 2',
    label_kind: 'neutral', label_basis: 'нет семантической подписи',
    metrics: {},
  }],
});
eq(neutral.items[0].labelKind, 'neutral',
  'нейтральная подпись не выдаётся за категорию');
eq(neutral.items[0].memberText.indexOf('Неизвестно'), -1,
  'известное число участников не подменяется «Неизвестно»');
const unknownMembers = CM.communitiesView({
  state: 'ok', items: [{ community_id: 'c-3', member_count: null,
    label: 'Сообщество 3', label_kind: 'neutral', metrics: {} }],
});
eq(unknownMembers.items[0].memberText, 'Неизвестно',
  'отсутствующая метрика — «Неизвестно», а не 0');

// ─── 3. Корневой vm: debounce, гонка, клавиатура, состояния ────────────────
let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() {
    return { tagName: 'div', className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      appendChild() {}, querySelector() { return null; } };
  },
  querySelector() { return null; },
  head: { appendChild() {} },
  body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
});
global.sessionStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.localStorage = {
  _s: {}, getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; },
};
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'app.js обязан зарегистрировать корневое приложение');
const methods = captured.methods || {};
const baseData = typeof captured.data === 'function' ? captured.data() : captured.data;

function newVm(extra) {
  const vm = Object.assign({}, baseData, methods);
  vm.activeChatId = -1001;
  vm.cognitionGraphData = null;
  vm.cogSearchEnabled = true;
  vm.cogSearch = {
    query: '', open: false, state: 'empty_input', notice: '', rows: [],
    activeIndex: -1, busy: false, canRetry: false, retryFirstPage: false,
    hasMore: false, cursor: null, reasonCode: '',
  };
  vm._cogSearchGen = 0;
  vm._cogSearchTimer = null;
  vm._cogSearchAbort = null;
  vm.toast = function () {};
  vm.api = async function () { return null; };
  return Object.assign(vm, extra || {});
}

global.window.CognitiveMap = CM;

function modelWith(names) {
  return CM.normalizePayload({
    version: 'cog-map/1', state: 'ok',
    nodes: names.map(function (n, i) {
      return { id: 'ent:-1001:' + (i + 1), kind: 'entity', title: n,
        chat_id: -1001, scope: 'chat' };
    }),
    edges: [],
  });
}

// (а) debounce: два быстрых ввода → ОДИН отложенный запрос, последний текст.
(function debounceCase() {
  const vm = newVm();
  const timers = [];
  const realSetTimeout = global.setTimeout;
  const realClearTimeout = global.clearTimeout;
  global.setTimeout = function (fn, ms) {
    timers.push({ fn: fn, ms: ms, cleared: false });
    return timers.length;
  };
  global.clearTimeout = function (id) {
    const t = timers[id - 1];
    if (t) t.cleared = true;
  };
  try {
    vm.cogSearch.query = 'Пап';
    vm.cogSearchInput({ target: { value: 'Пап' } });
    vm.cogSearch.query = 'Папаха';
    vm.cogSearchInput({ target: { value: 'Папаха' } });
  } finally {
    global.setTimeout = realSetTimeout;
    global.clearTimeout = realClearTimeout;
  }
  eq(timers.length, 2, 'каждый ввод планирует свой debounce');
  ok(timers[0].cleared, 'предыдущий debounce отменён (Пап не улетает)');
  ok(timers[1].ms >= 120 && timers[1].ms <= 180, 'debounce 120–180 мс');
  eq(timers[1].cleared, false, 'последний debounce жив');
  eq(vm.cogSearch.state, 'server_searching', 'сразу — «сервер ищет»');
  ok(vm.cogSearch.busy === true, 'индикатор загрузки внутри поля');
  ok(/Ищем/.test(vm.cogSearch.notice), 'честное «Ищем по всей памяти…»');
})();

// (б) локальный синхронный отклик по загруженной сцене (MEM-08.19а).
(function localCase() {
  const vm = newVm({ cognitionGraphData: modelWith(['Кирилл', 'Папаха']) });
  const timers = [];
  const realSetTimeout = global.setTimeout;
  global.setTimeout = function (fn, ms) { timers.push({ fn: fn, ms: ms }); return 1; };
  try {
    vm.cogSearchInput({ target: { value: 'Кирилл' } });
  } finally {
    global.setTimeout = realSetTimeout;
  }
  eq(vm.cogSearch.state, 'local_matches', 'сцена отвечает сразу');
  ok(vm.cogSearch.rows.length === 1, 'локальная строка показана сразу');
  ok(/ищем по всей памяти/.test(vm.cogSearch.notice),
    'локальный отклик не выдаётся за полный серверный поиск');
  ok(vm.cogSearch.open === true, 'панель раскрыта');
})();

// (в) поздний ответ «Пап» не перетирает свежий «Папаха» (поколение).
async function raceCase() {
  const vm = newVm();
  const pending = [];
  vm.api = function (url) {
    return new Promise(function (resolve, reject) {
      pending.push({ url: url, resolve: resolve, reject: reject });
    });
  };
  vm.cogSearch.query = 'Папаха';
  vm._cogSearchGen = 1;
  const runStale = vm._cogSearchRun.call(vm, 'Пап', 1, {});
  vm._cogSearchGen = 2;
  const runFresh = vm._cogSearchRun.call(vm, 'Папаха', 2, {});
  ok(pending.length === 2, 'два запроса в полёте');
  ok(pending[0].url.indexOf('q=%D0%9F%D0%B0%D0%BF') > 0
    && pending[1].url.indexOf('%D0%9F%D0%B0%D0%BF%D0%B0%D1%85%D0%B0') > 0,
    'URL кодирует запрос (Пап / Папаха)');
  ok(pending[0].url.indexOf('limit=') > 0, 'страница подсказок запрошена');
  // Свежий приходит первым.
  pending[1].resolve({
    status: 'ok', query_state: 'candidates', items: [{
      ref_kind: 'entity', canonical_id: 'ent:-1001:1', title: 'Папаха',
      category: 'Человек', match_cause: 'exact_name', evidence_status: 'confirmed',
    }], next_cursor: null, has_more: false,
  });
  await runFresh;
  eq(vm.cogSearch.state, 'candidates', 'свежий ответ применён');
  // Запоздалый «Пап» приходит с «ничего не найдено» — обязан быть отброшен.
  pending[0].resolve({
    status: 'empty', query_state: 'no_matches', items: [],
    next_cursor: null, has_more: false,
  });
  await runStale;
  eq(vm.cogSearch.state, 'candidates',
    'поздний ответ не перетёр свежий (MEM-08.19в)');
  ok(vm.cogSearch.rows.length === 1, 'выдача свежего запроса сохранена');
}

// (г) cursor_stale — тихий перезапуск первой страницы, без пустого экрана.
async function staleCase() {
  const vm = newVm();
  const calls = [];
  vm.api = async function (url) {
    calls.push(url);
    if (calls.length === 1) {
      return { status: 'cursor_stale', query_state: 'local_matches',
        reason_code: 'cursor_revision_mismatch', items: [],
        next_cursor: null, has_more: false };
    }
    return { status: 'ok', query_state: 'candidates', items: [{
      ref_kind: 'entity', canonical_id: 'ent:-1001:1', title: 'Кирилл',
      category: 'Человек', match_cause: 'exact_name', evidence_status: 'confirmed',
    }], next_cursor: null, has_more: false };
  };
  vm.cogSearch.query = 'Кирилл';
  vm._cogSearchGen = 1;
  await vm._cogSearchRun.call(vm, 'Кирилл', 1, { cursor: 'stale-cursor' });
  eq(calls.length, 2, 'cursor_stale → автоматический повтор первой страницы');
  ok(calls[1].indexOf('cursor=') < 0, 'повтор идёт БЕЗ устаревшего курсора');
  eq(vm.cogSearch.state, 'candidates', 'экран не остался пустым');
  eq(vm.cogSearch.notice.indexOf('Ничего не найдено'), -1,
    'cursor_stale не превращается в «ничего не найдено»');
}

// (д) четыре состояния → четыре разных пользовательских сообщения.
async function statesCase() {
  const payloads = {
    no_matches: { status: 'empty', query_state: 'no_matches', items: [],
      next_cursor: null, has_more: false },
    no_rights: { status: 'forbidden', query_state: 'no_rights', items: [],
      next_cursor: null, has_more: false },
    error: { status: 'error', query_state: 'error', items: [],
      next_cursor: null, has_more: false },
  };
  const seen = {};
  for (const name of Object.keys(payloads)) {
    const vm = newVm();
    vm.api = async function () { return payloads[name]; };
    vm.cogSearch.query = 'Кирилл';
    vm._cogSearchGen = 1;
    await vm._cogSearchRun.call(vm, 'Кирилл', 1, {});
    seen[name] = { state: vm.cogSearch.state, notice: vm.cogSearch.notice };
    eq(vm.cogSearch.busy, false, name + ': индикатор снят');
  }
  ok(seen.no_matches.state === UI.NO_MATCHES, 'no_matches → свой токен');
  ok(seen.no_rights.state === UI.NO_RIGHTS, 'no_rights → свой токен');
  ok(seen.error.state === UI.ERROR, 'error → свой токен');
  const texts = [seen.no_matches.notice, seen.no_rights.notice, seen.error.notice];
  ok(new Set(texts).size === 3, 'три исхода звучат по-разному');
  ok(texts[2].indexOf('Ничего не найдено') < 0,
    'ошибка никогда не показывается как «ничего не найдено»');
}

// (е) сетевой сбой — «Попробовать ещё раз», не пустая выдача.
async function networkCase() {
  const vm = newVm();
  vm.api = async function () { const e = new Error('network'); e.status = 0; throw e; };
  vm.cogSearch.query = 'Кирилл';
  vm._cogSearchGen = 1;
  await vm._cogSearchRun.call(vm, 'Кирилл', 1, {});
  eq(vm.cogSearch.state, UI.ERROR, 'сеть недоступна → error');
  eq(vm.cogSearch.canRetry, true, 'есть действие повтора');
  eq(vm.cogSearch.reasonCode, 'network', 'причина сохранена для диагностики');
}

// (ж) клавиатура: стрелки/Enter/Escape, IME не запускает выбор.
(function keyboardCase() {
  const vm = newVm();
  vm.cogSearch.rows = [
    { id: 'a', title: 'A', variants: [] },
    { id: 'b', title: 'B', variants: [] },
    { id: 'c', title: 'C', variants: [] },
  ];
  vm.cogSearch.open = true;
  vm.cogSearch.activeIndex = 0;
  const prevented = [];
  const ev = function (key, extra) {
    return Object.assign({ key: key, preventDefault: function () { prevented.push(key); } }, extra || {});
  };
  vm.cogSearchKeydown(ev('ArrowDown'));
  eq(vm.cogSearch.activeIndex, 1, 'ArrowDown двигает активный пункт');
  vm.cogSearchKeydown(ev('ArrowDown'));
  vm.cogSearchKeydown(ev('ArrowDown'));
  eq(vm.cogSearch.activeIndex, 0, 'переход по кругу');
  vm.cogSearchKeydown(ev('ArrowUp'));
  eq(vm.cogSearch.activeIndex, 2, 'ArrowUp назад по кругу');

  let selected = null;
  vm.cogSearchSelect = function (index) { selected = index; };
  vm.cogSearchKeydown(ev('Enter'));
  eq(selected, 2, 'Enter открывает выделенный результат');
  ok(prevented.indexOf('Enter') >= 0, 'Enter не отправляет форму');

  vm.cogSearch.open = true;
  vm.cogSearchKeydown(ev('Escape'));
  eq(vm.cogSearch.open, false, 'Escape закрывает подсказки');
  ok(vm.cogSearch.activeIndex === -1, 'highlight снят');

  // IME/композиция не запускает ни выбор, ни закрытие преждевременно.
  selected = null;
  vm.cogSearch.open = true;
  vm.cogSearchKeydown(ev('Enter', { isComposing: true }));
  eq(selected, null, 'IME-композиция не выбирает результат');
  eq(vm.cogSearch.open, true, 'IME-композиция не закрывает панель');
  vm.cogSearchKeydown(ev('Enter', { keyCode: 229 }));
  eq(selected, null, 'keyCode 229 (IME) игнорируется');

  // Escape при пустом вводе — снимает фокус, не ломая back-stack.
  const vm2 = newVm();
  vm2.cogSearch.query = '';
  vm2.cogSearch.open = false;
  let blurred = false;
  let cleared = false;
  vm2.cogSearchClear = function () { cleared = true; };
  vm2.cogSearchKeydown(ev('Escape', { target: { blur: function () { blurred = true; } } }));
  ok(blurred === true, 'Escape снимает фокус с поля');
  eq(cleared, false, 'пустой ввод не вызывает очистку истории');
})();

// (з) выбор результата: в сцене — фокус, вне сцены — честный текст.
(function selectCase() {
  const vm = newVm({ cognitionGraphData: modelWith(['Кирилл']) });
  let focused = null;
  vm.focusGraphNode = function (id) { focused = id; };
  vm.cogSearch.rows = [{
    id: 'ent:-1001:1', title: 'Кирилл', focusNodeId: '1', variants: [],
  }];
  vm.cogSearchSelect(0);
  eq(focused, 'ent:-1001:1', 'реальный узел сцены фокусируется');
  eq(vm.cogSearch.open, false, 'панель закрывается после выбора');
  ok(vm.cogSearch.notice.indexOf('Показано на карте') === 0, 'честная подпись выбора');

  const vm2 = newVm({ cognitionGraphData: modelWith(['Кирилл']) });
  let focused2 = null;
  vm2.focusGraphNode = function (id) { focused2 = id; };
  vm2.cogSearch.rows = [{
    id: 'fact:777', title: 'Утренний кофе', focusNodeId: null, variants: [],
  }];
  vm2.cogSearchSelect(0);
  eq(focused2, null, 'запись вне сцены не превращается в узел');
  ok(/вне текущего окна/.test(vm2.cogSearch.notice),
    'вне сцены — честное сообщение, а не выдуманный узел');
})();

// (и) `×` очищает ввод и снимает подсветку поиска.
(function clearCase() {
  const vm = newVm();
  let legacyCleared = false;
  vm.clearCognitionGraphSearch = function () { legacyCleared = true; };
  vm.cogSearch.query = 'Кирилл';
  vm.cogSearch.state = 'candidates';
  vm.cogSearch.rows = [{ id: 'a', title: 'A', variants: [] }];
  vm.cogSearch.open = true;
  vm.cogSearchClear();
  eq(vm.cogSearch.query, '', 'очистка ввода');
  eq(vm.cogSearch.state, 'empty_input', 'пустой ввод — обычный обзор (S-6)');
  eq(vm.cogSearch.rows.length, 0, 'подсказки сняты');
  eq(vm.cogSearch.open, false, 'панель закрыта');
  eq(vm.cogSearch.notice, '', 'никаких выдуманных подсказок/историй');
  eq(legacyCleared, true, 'подсветка/фокус прежнего поиска снимаются');
})();

// (к) гейт OFF: запрос сбрасывается при загрузке карты без поля `search`.
async function gateCase() {
  const vm = newVm();
  vm.api = async function () {
    return { version: 'cog-map/1', state: 'ok', nodes: [], edges: [],
      shown_of: { nodes: 0, edges: 0, by_kind: {} } };
  };
  vm.isGlobalAdmin = true;
  vm.activeChatId = -1001;
  vm.activeTab = 'status';
  vm.summaryAliasesMap = function () { return {}; };
  vm.$nextTick = function (fn) { if (fn) fn(); };
  vm.renderCognitionGraph = async function () {};
  vm._cogRefreshCard = function () {};
  vm.cogSearch.query = 'Кирилл';
  await vm.loadCognitionGraph.call(vm);
  eq(vm.cogSearchEnabled, false, 'без поля `search` гейт OFF (паритет)');
  eq(vm.cogSearch.query, '', 'набранный запрос сброшен при OFF');
  eq(vm.cogSearch.state, 'empty_input', 'состояние вернулось в обзор');
}

// Асинхронные кейсы — последовательно, чтобы ошибка любого валила маркер.
(async function main() {
  await raceCase();
  await staleCase();
  await statesCase();
  await networkCase();
  await gateCase();
  console.log('MEM-08-S3-OK checks=' + checks);
})().catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
