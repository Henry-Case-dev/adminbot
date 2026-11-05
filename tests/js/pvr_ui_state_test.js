'use strict';
/* PVR-FC-CORRECTIVE-01 / PVR-UI — презентация контракта состояния (PVR-01..03,
 * PVR-05.2, C1.2/C3.x handoffs бэкенда d5ee97ef).
 *
 * Проверяется ПОВЕДЕНЧЕСКИЙ контракт UI-состояний:
 *   1. «Действует» — из effective-контракта резолвера (PVR-01.7):
 *      chat_override → «Действует в этом чате», global → «Действует
 *      глобальная версия», code → «Исходный из кода».
 *   2. Несопоставленный текст честно «Не сопоставлено с историей», ревизия
 *      не выдумывается (МУТАЦИЯ «журнальный указатель выдан за matched»
 *      обязана сделать тест красным).
 *   3. draft_dirty — только черновик редактора (проп `dirty`), серверное
 *      поле состояния не рисует метку черновика.
 *   4. Основной список = ТОЛЬКО revisions; события активации живут во
 *      вторичном «Истории действий» со статусом «была применена» и никогда
 *      не становятся active (МУТАЦИЯ «событие отрисовано как active в
 *      основном списке» обязана сделать тест красным).
 *   5. Save-честность: POST /api/config несёт operation_id; 503
 *      partial_save → saveState 'sync_pending' + «Частично сохранено:
 *      сверьте действующее значение» + повторная сверка; 409 → конфликт без
 *      перетирания черновика; 503 истории → «История временно недоступна»
 *      при сохранённом редакторе.
 *   6. retired/incompatible — читаемы и сравнимы, НЕ активируемы.
 *
 * Запуск: node tests/js/pvr_ui_state_test.js
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
const CARD = REGISTRY['prompt-version-card'];
assert(CARD, 'компонент prompt-version-card не зарегистрирован');

// ── Хелперы контекста (как в prompt_version_card_test.js) ────────────────
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

function stateOf(patch) {
  const values = Object.assign({
    promptKey: 'prompts.meme_joke',
    chatId: 42,
    chatTitle: 'Чат A',
    title: 'Промпт прикола',
    hist: { data: null, error: '', entries: [], events: [] },
    busy: false,
    dirty: false,
    canEdit: true,
    modelValue: '',
    effectiveText: '',
    $emit() {},
    $nextTick(fn) { fn(); },
    root: { api: async function () { return {}; } },
  }, patch || {});
  return makeCtx(CARD.computed, CARD.methods, values);
}

function matchedState(patch) {
  return Object.assign({
    effective_origin: 'chat_override', effective_status: 'matched',
    effective_content_hash: '1212121212121212',
    effective_revision_id: 'rev-1',
    revisions: [{ revision_id: 'rev-1',
                  created_at: '2026-11-03T23:42:00+00:00' }],
    activations: [], entries: [],
    active: null, baseline: { baseline: null },
  }, patch || {});
}

// ── 1. Origin-метки действующей версии (PVR-01.1/PVR-01.7 handoff) ───────
{
  const s = stateOf({ hist: { error: '', entries: [], events: [],
    data: matchedState() } });
  assert.strictEqual(s.state.text, 'Действует в этом чате',
    'chat_override → «Действует в этом чате»: ' + s.state.text);
  const g = stateOf({ hist: { error: '', entries: [], events: [],
    data: matchedState({ effective_origin: 'global' }) } });
  assert.strictEqual(g.state.text, 'Действует глобальная версия',
    'global → каноничная фраза PVR-01.7: ' + g.state.text);
  assert.strictEqual(g.state.detail, 'наследуется чатом');
  const c = stateOf({ hist: { error: '', entries: [], events: [],
    data: matchedState({ effective_origin: 'code' }) } });
  assert.strictEqual(c.state.text, 'Исходный из кода');
  // Технические токены origin не протекают в основную строку.
  ['chat_override', 'global', 'code'].forEach(function (tok) {
    assert.strictEqual(stateOf({ hist: { error: '', entries: [], events: [],
      data: matchedState({ effective_origin: tok }) } }).state.text
      .indexOf(tok), -1, 'сырой токен origin в основной строке: ' + tok);
  });
}

// ── 2. Unmatched-честность + МУТАЦИЯ «журнальный указатель = matched» ────
// Текст действует, сохранённой ревизии с такими байтами нет. Журнальный
// указатель указывает на rev-1 — он НЕ имеет права давать метку «активная»
// и не подставляется как «сопоставленная ревизия» (PVR-01.2/C1.1).
{
  const s = stateOf({ hist: { error: '', entries: [], events: [],
    data: matchedState({
      effective_status: 'unmatched',
      effective_revision_id: null,
      effective_content_hash: 'abababababababab',
      active: { revision_id: 'rev-1', origin: 'manual', source: 'manual',
                created_at: '2026-11-03T23:42:00+00:00' },
      journal_active_revision_id: 'rev-1',
      journal_last_activation_id: 42,
    }) } });
  assert.strictEqual(s.state.text, 'Не сопоставлено с историей',
    'МУТАЦИЯ: unmatched, выданный за matched (по журнальному указателю), '
    + 'делает тест красным — got: ' + s.state.text);
  assert.strictEqual(s.drifted, false);
  // Ни одна ревизия не помечена активной — в том числе журнальный rev-1.
  assert.strictEqual(s.isActiveEntry({ revision_id: 'rev-1' }), false,
    'МУТАЦИЯ: journal-based isActiveEntry пометил бы rev-1 активным');
  assert.strictEqual(s.activeLabel, 'не сопоставлено с историей',
    'панель не показывает журнал как действующий: ' + s.activeLabel);
  const det = s.detailsLines.join(' | ');
  assert.ok(det.indexOf('действующая ревизия: не сопоставлена') >= 0,
    'в подробностях честная строка без выдуманного revision_id: ' + det);
  assert.ok(det.indexOf('журнальный указатель: rev-1') >= 0,
    'журнальный указатель остаётся отдельной журнальной строкой');
  assert.strictEqual(det.indexOf('действующая ревизия: rev-1'), -1,
    'журнальная ревизия не подписана «действующей»');
}

// ── 3. Drift: ни одна карточка не активна + честный статус (PVR-01.7) ────
{
  const s = stateOf({ hist: { error: '', entries: [], events: [],
    data: matchedState({
      effective_status: 'drift',
      active: { revision_id: 'rev-1', origin: 'manual', source: 'manual',
                created_at: '2026-11-03T23:42:00+00:00' },
      journal_active_revision_id: 'rev-1',
    }) } });
  assert.strictEqual(s.state.text, 'Журнал и действующий текст расходятся');
  assert.strictEqual(s.drifted, true);
  assert.strictEqual(s.isActiveEntry({ revision_id: 'rev-1' }), false);
  assert.strictEqual(s.isActiveEntry({ revision_id: 'rev-2' }), false,
    'при drift не активна ни одна строка, включая эффективную');
  assert.ok(INDEX.indexOf('data-pv-drift') >= 0,
    'drift-баннер обязан быть в разметке панели');
  assert.ok(INDEX.indexOf('ни одна версия не\n помечена активной') >= 0
    || /ни одна версия не\s+помечена активной/.test(INDEX),
    'текст drift-баннера говорит об отсутствии активной метки');
}

// ── 4. draft_dirty — только черновик редактора (PVR-01.5) ─────────────────
{
  // Серверное draft_dirty (в реальном API всегда False) не рисует метку
  // черновика: маркер привязан ТОЛЬКО к пропу dirty.
  const dirtyMarker = INDEX.slice(INDEX.indexOf('data-pv-dirty') - 60,
                                  INDEX.indexOf('data-pv-dirty') + 60);
  assert.ok(/v-if="dirty"/.test(dirtyMarker),
    'метка черновика привязана к пропу dirty: ' + JSON.stringify(dirtyMarker));
  const s = stateOf({ dirty: false, hist: { error: '', entries: [],
    events: [], data: matchedState({ draft_dirty: true }) } });
  assert.strictEqual(s.dirty, false,
    'server draft_dirty не становится dirty-состоянием редактора');
  assert.strictEqual(s.state.text, 'Действует в этом чате',
    'draft_dirty не влияет на метку действующей версии');
  const s2 = stateOf({ dirty: true, hist: { error: '', entries: [],
    events: [], data: matchedState() } });
  assert.strictEqual(s2.dirty, true,
    'черновик редактора — клиентское состояние (проп dirty)');
  // Черновик не попадает в состояние, от которого зависит LLM-payload:
  // state не читает modelValue.
  assert.strictEqual(
    stateOf({ modelValue: 'несохранённый черновик', hist: { error: '',
      entries: [], events: [], data: matchedState() } }).state.text,
    'Действует в этом чате',
    'несохранённый текст поля не выдаётся за действующий');
}

// ── 5. Основной список = только revisions; события — вторичны ─────────────
// МУТАЦИЯ «событие applied отрисовано как active в основном списке» обязана
// падать: (а) merged-лента не рендерится, (б) событие не получает active.
{
  const data = matchedState({
    revisions: [
      { revision_id: 'rev-1', status: 'active', source: 'manual',
        created_at: '2026-11-03T23:42:00+00:00', body_available: true },
      { revision_id: 'rev-2', status: 'inactive', source: 'manual',
        created_at: '2026-11-02T10:00:00+00:00', body_available: true },
    ],
    activations: [
      { activation_id: 1, revision_id: 'rev-1', status: 'was_applied',
        status_label: 'была применена', source: 'manual',
        created_at: '2026-11-03T23:42:00+00:00', body_available: true },
      { activation_id: 2, revision_id: 'rev-1', status: 'was_applied',
        status_label: 'была применена', source: 'manual',
        created_at: '2026-11-01T09:00:00+00:00', body_available: true },
    ],
  });
  const s = stateOf({ hist: { error: '', entries: [], events: [], data } });
  const rows = s.revisionRows;
  assert.deepStrictEqual(rows.map(function (r) { return r.revision_id; }),
    ['rev-1', 'rev-2'],
    'основной список — ровно сохранённые ревизии, без событий и дублей');
  assert.ok(rows.every(function (r) {
    return r.activation_id == null && r.entry_type == null;
  }), 'в основном списке нет событий активации');
  assert.strictEqual(s.eventRows.length, 2, 'события живут во вторичном списке');
  assert.ok(s.eventRows.every(function (ev) {
    return ev.status !== 'active' && ev.status === 'was_applied';
  }), 'МУТАЦИЯ: событие со статусом active/was_applied в основном списке — '
    + 'красный кейс; события остаются «была применена»');
  // Разметка: события рендерятся только в отдельном блоке; в блоке событий
  // нет кнопок «Применить»/«Назначить базовой».
  const evHead = INDEX.indexOf('class="pv-events"');
  assert.ok(evHead >= 0, 'вторичный блок «История действий» обязан быть');
  const evBlock = INDEX.slice(evHead, INDEX.indexOf('</template>', evHead));
  assert.strictEqual(evBlock.indexOf('data-pv-row-activate'), -1,
    'у событий нет своей кнопки «Применить» (PVR-02.1)');
  assert.strictEqual(evBlock.indexOf('data-pv-row-baseline'), -1,
    'у событий нет кнопки «Назначить базовой»');
  assert.ok(evBlock.indexOf('data-pv-event-status-label') >= 0,
    'статус события отображается отдельной меткой');
  // Основной список рендерит revisionRows (через visibleRevisionRows —
  // поиск фильтрует загруженный список), а не merged entries.
  const listBlock = INDEX.slice(INDEX.indexOf('data-prompt-history-versions'),
                                INDEX.indexOf('class="pv-events"'));
  assert.ok(listBlock.indexOf('v-for="rev in visibleRevisionRows"') >= 0,
    'основной список рендерит revisionRows (только revisions)');
  assert.strictEqual(listBlock.indexOf('hist.entries'), -1,
    'merged-лента (entries) больше не рендерится в основном списке');
  // Активная подсветка привязана к isActiveEntry (effective-matched), а не
  // к серверному статусу строки (который приходит из журнала).
  assert.ok(listBlock.indexOf("isActiveEntry(rev) ? 'pv-row__status--active'") >= 0,
    'active-статус строки рисуется только через effective-matched проверку');
  // Догрузка основного списка — по revisions_cursor (не merged cursor).
  assert.ok(APP.indexOf('revisions_cursor=') >= 0,
    'догрузка ревизий по revisions_cursor');
  assert.ok(APP.indexOf('activations_cursor=') >= 0,
    'догрузка событий по activations_cursor');
}

// ── 6. 503 history-unavailable → «История временно недоступна» ────────────
{
  const s = stateOf({});
  const msg = s.errText({ status: 503, message: 'журнал версий недоступен' });
  assert.ok(msg.indexOf('История временно недоступна') === 0,
    'каноничная метка PVR-05.2: ' + msg);
  // Редактор НЕ привязан к состоянию истории: textarea рендерится вне
  // v-if/hist.error, черновик остаётся в поле.
  const tpl = INDEX.slice(INDEX.indexOf('id="prompt-version-card-tpl"'),
                          INDEX.indexOf('</script>', INDEX.indexOf(
                            'id="prompt-version-card-tpl"')));
  const taHead = tpl.indexOf('data-prompt-textarea');
  assert.ok(taHead >= 0);
  assert.strictEqual(tpl.slice(0, taHead).indexOf('hist.error'), -1,
    'textarea не должна прятаться при недоступной истории');
  const st = stateOf({ hist: { error: 'История временно недоступна: x',
                               data: null, entries: [], events: [] } });
  assert.strictEqual(st.state.text, 'История временно недоступна');
}

// ── 7. retired/incompatible: читаемы/сравнимы, НЕ активируемы ─────────────
{
  const data = matchedState({
    revisions: [
      { revision_id: 'rev-ret', status: 'retired', actionable: false,
        body_available: true, reason_text: 'retired: версия снята' },
      { revision_id: 'rev-inc', status: 'incompatible', actionable: false,
        body_available: true, reason_text: 'несовместима' },
    ],
  });
  const s = stateOf({ hist: { error: '', entries: [], events: [], data } });
  const retired = s.revisionRows[0];
  const incompatible = s.revisionRows[1];
  assert.strictEqual(s.canActivate(retired), false,
    'retired не активируется');
  assert.strictEqual(s.canActivate(incompatible), false,
    'несовместимая не активируется');
  assert.strictEqual(s.canAssign(retired), false);
  assert.strictEqual(s.canViewBody(retired), true,
    'retired остаётся читаемым');
  assert.ok(s.rowReason(retired).indexOf('retired') >= 0,
    'честная причина для retired');
  assert.ok(s.rowReason(incompatible).indexOf('несовместима') >= 0,
    'честная причина для несовместимой');
  // Сравнение доступно независимо от actionable (diffable): compare не
  // проверяет actionable.
  assert.strictEqual(typeof CARD.methods.compare, 'function');
}

// ── 8. Save-честность: operation_id + 503 partial_save → sync_pending ────
async function saveHonestyTest() {
  const posts = [];
  const rootCtx = {
    _opSeq: 0,
    saving: new Set(),
    activeChatId: null,
    configChatUpdatedAt: '2026-11-03T00:00:00Z',
    scopeEpoch: 1,
    stickyConflict: [],
    stickySyncPending: [],
    stickyFailed: [],
    stickyFailedKeys: [],
    toast() {},
    notify() {},
    async loadConfig() {},
    _serializeValue(v) { return JSON.stringify(v); },
    async api(path, opts) {
      posts.push({ path: path, opts: opts });
      const detail = { code: 'partial_save',
                       message: 'Промпты сохранены, настройки — нет',
                       applied: ['prompts.meme_joke'],
                       rejected: [{ key: 'limits.x', reason: 'PG' }] };
      const err = new Error('partial_save');
      err.status = 503;
      err.message = detail;
      throw err;
    },
  };
  const self = makeCtx(computed, methods, rootCtx);
  // makeCtx привязывает НАСТОЯЩИЕ методы root поверх value-стабов —
  // переопределяем тестовые двойники напрямую на контексте.
  self.toast = function () {};
  self.notify = function () {};
  self.loadConfig = async function () {};
  self.api = async function (path, opts) {
    posts.push({ path: path, opts: opts });
    const detail = { code: 'partial_save',
                     message: 'Промпты сохранены, настройки — нет',
                     applied: ['prompts.meme_joke'],
                     rejected: [{ key: 'limits.x', reason: 'PG' }] };
    const err = new Error('partial_save');
    err.status = 503;
    err.message = detail;
    throw err;
  };
  const res = await methods.persistItems.call(self, [
    { key: 'prompts.meme_joke', value: 'новый текст', per_chat: false },
    { key: 'limits.x', value: 5, per_chat: false },
  ]);
  // operation_id уходит в оба POST (PVR-02.3 op-id seam).
  assert.strictEqual(posts.length, 1, 'один scope — один POST');
  const body = JSON.parse(posts[0].opts.body);
  assert.ok(body.operation_id, 'operation_id обязателен в теле POST');
  assert.strictEqual(body.operation_id, res.operationId,
    'operation_id ответа совпадает с отправленным');
  // Применённый промпт — НЕ «ошибка» и НЕ тихий успех: sync_pending.
  assert.deepStrictEqual(res.saved, ['prompts.meme_joke'],
    'частично применённый ключ — применён: ' + JSON.stringify(res.saved));
  assert.deepStrictEqual(res.syncPending, ['prompts.meme_joke'],
    'syncPending перечисляет применённые без подтверждения кэша');
  assert.strictEqual(res.state, 'sync_pending');
  assert.deepStrictEqual(self.stickySyncPending, ['prompts.meme_joke'],
    'sync_pending держится до повторной сверки');
  assert.strictEqual(self.stickyFailedKeys.indexOf('limits.x') >= 0, true,
    'отклонённый ключ остаётся провалом');
  const notice = self.promptEditorNotice;
  assert.ok(notice.indexOf('Частично сохранено') >= 0,
    'метка «Частично сохранено»: ' + JSON.stringify(notice));
  assert.ok(notice.indexOf('сверьте действующее значение') >= 0,
    'требование сверки effective value в тексте');
  assert.strictEqual(self.promptEditorNoticeOk, false,
    'sync_pending — не «успех»');
  assert.strictEqual(self.saveState, 'sync_pending',
    'saveState формы = sync_pending');
  // Повторная сверка доступна одной кнопкой (re-check action).
  assert.ok(INDEX.indexOf('data-prompt-sync-recheck') >= 0,
    'кнопка повторной сверки effective value обязана быть');
  assert.ok(INDEX.indexOf('data-prompt-sync-pending') >= 0,
    'блок sync_pending в разметке редактора');
  // Обновление без partial_save снимает метку.
  const okCtx = Object.assign({}, rootCtx, {
    stickySyncPending: ['prompts.meme_joke'],
  });
  const self2 = makeCtx(computed, methods, okCtx);
  self2.notify = function () {};
  self2.toast = function () {};
  self2.loadConfig = async function () {};
  self2.api = async function (path, opts) {
    posts.push({ path: path, opts: opts });
    return { updated: ['prompts.meme_joke'] };
  };
  const res2 = await methods.persistItems.call(self2, [
    { key: 'prompts.meme_joke', value: 'текст 2', per_chat: false },
  ]);
  assert.strictEqual(res2.state, 'saved');
  assert.deepStrictEqual(self2.stickySyncPending, [],
    'успешный прогон снимает sync_pending');
}

// ── 9. CAS 409: конфликт без перетирания черновика ────────────────────────
async function conflictTest() {
  const posts = [];
  const item = { key: 'prompts.meme_joke', value: 'мой черновик',
                 per_chat: false };
  const rootCtx = {
    _opSeq: 0,
    saving: new Set(),
    activeChatId: null,
    configChatUpdatedAt: '2026-11-03T00:00:00Z',
    scopeEpoch: 1,
    stickyConflict: [],
    stickySyncPending: [],
    stickyFailed: [],
    stickyFailedKeys: [],
    configItems: [item],
    toast() {},
    notify() {},
    async loadConfig() {
      // Сервер вернул ЧУЖОЕ значение: черновик «мой черновик» не совпадает.
      item.value = 'чужая правка из другой вкладки';
    },
    _serializeValue(v) { return JSON.stringify(v); },
    async api(path, opts) {
      posts.push({ path: path, opts: opts });
      const err = new Error('conflict');
      err.status = 409;
      err.message = { code: 'conflict', conflicting: [],
                      current_updated_at: 'later' };
      throw err;
    },
  };
  const self = makeCtx(computed, methods, rootCtx);
  // Стабы поверх привязанных методов root (см. saveHonestyTest).
  self.toast = function () {};
  self.notify = function () {};
  self.loadConfig = async function () {
    // Сервер вернул ЧУЖОЕ значение: черновик «мой черновик» не совпадает.
    item.value = 'чужая правка из другой вкладки';
  };
  self._findConfigItem = function (key) {
    return key === item.key ? item : null;
  };
  self.api = async function (path, opts) {
    posts.push({ path: path, opts: opts });
    const err = new Error('conflict');
    err.status = 409;
    err.message = { code: 'conflict', conflicting: [],
                    current_updated_at: 'later' };
    throw err;
  };
  const res = await methods.persistItems.call(self, [item]);
  assert.strictEqual(res.state, 'error');
  assert.strictEqual(self.stickyConflict.indexOf('prompts.meme_joke') >= 0,
    true, 'конфликт остаётся sticky-conflict');
  assert.strictEqual(item.value, 'мой черновик',
    'CAS 409: чужая правка НЕ перетирает черновик молча — черновик '
    + 'возвращён в поле');
  assert.strictEqual(self.saveState, 'conflict');
  assert.ok(self.promptEditorNotice.indexOf('остановлено') >= 0
    && self.promptEditorNotice.indexOf('черновик остался') >= 0,
    'уведомление о конфликте без перетирания: '
    + JSON.stringify(self.promptEditorNotice));
  assert.strictEqual(self.promptEditorNoticeOk, false);
}

// ── 10. Panel/meta honesty: действует — из effective, указатели отдельно ──
{
  const tplHead = INDEX.indexOf('id="prompt-version-card-tpl"');
  const TPL = INDEX.slice(tplHead, INDEX.indexOf('</script>', tplHead));
  assert.ok(TPL.indexOf('data-pv-panel-active') >= 0);
  assert.ok(TPL.indexOf('data-pv-panel-factory') >= 0);
  assert.ok(TPL.indexOf('data-pv-panel-baseline') >= 0);
  // Библиотечный редактор сохраняет через единый write-path.
  assert.ok(INDEX.indexOf('@save="saveConfigItem(workspacePromptFocus)"') >= 0,
    'Save библиотечного редактора идёт через saveConfigItem');
  assert.strictEqual(INDEX.indexOf('@save="saveConfig()"'), -1,
    'сломанный @save="saveConfig()" удалён');
  assert.ok(CSS.indexOf('.pv-events') >= 0, 'стили блока событий на токенах');
}

// ── 11. PVR-04: новый визуальный язык вокруг честного контракта ───────────
// Редизайн меняет представление, не семантику: поиск фильтрует загруженный
// список без выдумок; строки редакций — максимум один уместный статус,
// привязанный к effective-matched; selection ≠ active; «История N» — только
// честно известное число.
{
  const data = matchedState({
    revisions: [
      { revision_id: 'rev-1', source: 'manual',
        created_at: '2026-11-03T23:42:00+00:00', body_available: true },
      { revision_id: 'rev-2', source: 'from_release',
        created_at: '2026-11-02T10:00:00+00:00', body_available: true },
    ],
  });
  const s = stateOf({ hist: { query: '', error: '', entries: [], events: [],
                              data: data } });
  assert.strictEqual(s.visibleRevisionRows.length, 2,
    'без запроса видны все загруженные ревизии');
  s.hist.query = 'Вручную';
  assert.deepStrictEqual(s.visibleRevisionRows.map(function (r) {
    return r.revision_id;
  }), ['rev-1'], 'поиск по каноничному источнику находит строку');
  s.hist.query = 'из релиза';
  assert.deepStrictEqual(s.visibleRevisionRows.map(function (r) {
    return r.revision_id;
  }), ['rev-2'], 'поиск по «Из релиза» находит релизную ревизию');
  s.hist.query = 'rev-2';
  assert.deepStrictEqual(s.visibleRevisionRows.map(function (r) {
    return r.revision_id;
  }), ['rev-2'], 'поиск по revision_id — честный доступ для power-user');
  s.hist.query = 'чеготакогонет';
  assert.strictEqual(s.visibleRevisionRows.length, 0,
    'несовпадающий запрос не подставляет «похожие» строки');
  s.hist.query = '';
  // Разметка панели: поиск, справка о наследовании, ОДИН блок «Сейчас
  // действует» (PVR-04.2.2).
  const tplHead = INDEX.indexOf('id="prompt-version-card-tpl"');
  const TPL = INDEX.slice(tplHead, INDEX.indexOf('</script>', tplHead));
  assert.ok(TPL.indexOf('data-pv-search') >= 0,
    'поиск по версиям в шапке панели (PVR-04.2.2)');
  assert.ok(TPL.indexOf('data-pv-panel-hint') >= 0,
    'короткая справка о наследовании в шапке панели');
  assert.strictEqual(
    (TPL.match(/class="pv-now__title">Сейчас действует/g) || []).length, 1,
    'блок «Сейчас действует» в панели ровно один');
  assert.ok(TPL.indexOf('data-pv-panel-back') >= 0,
    'у деталей версии есть «Назад» (PVR-04.3.1)');
  // Источник строки — каноничная карта PVR-04.2.3; события журнала —
  // серверная подпись (kind-специфичная, точнее).
  assert.strictEqual(s.sourceLabel({ source: 'manual' }), 'Вручную');
  assert.strictEqual(s.sourceLabel({ source: 'from_release' }), 'Из релиза');
  assert.strictEqual(s.sourceLabel({ source: 'imported' }), 'Импортирована');
  assert.strictEqual(s.sourceLabel({ source: 'legacy' }), 'Историческая');
  assert.strictEqual(s.sourceLabel({ source: 'restored',
                                     activation_id: 3,
                                     source_label: 'назначена базовая' }),
    'назначена базовая',
    'для событий журнала серверная подпись приоритетнее каноничной карты');
  // Максимум ОДИН уместный статус строки; «Действует» — только
  // effective-matched (мутация «журнальный указатель = active» красная).
  const active = s.visibleRevisionRows[0];
  assert.strictEqual(s.rowBadge(active), 'Действует');
  assert.strictEqual(s.rowBadge({ revision_id: 'rev-x',
                                  body_available: false }), 'Недоступна');
  assert.strictEqual(s.rowBadge({ revision_id: 'rev-y',
                                  body_available: true }), '',
    'обычная неактивная строка без статусного шума');
  const drift = stateOf({ hist: { query: '', error: '', entries: [], events: [],
    data: matchedState({ effective_status: 'drift',
                         journal_active_revision_id: 'rev-1' }) } });
  assert.strictEqual(drift.rowBadge(drift.visibleRevisionRows[0]), '',
    'МУТАЦИЯ: при drift ни одна строка не помечена «Действует»');
  // selection ≠ active: выбранная строка — отдельная привязка к selectedId.
  const listBlock2 = INDEX.slice(INDEX.indexOf('data-prompt-history-versions'),
                                 INDEX.indexOf('class="pv-events"'));
  assert.ok(listBlock2.indexOf("'is-selected': hist.selectedId === rev.revision_id") >= 0,
    'selection привязан к selectedId, а не к isActiveEntry');
  // «История N» (PVR-04.0): число версий только когда список догружен
  // целиком — в API нет total, неполный список не выдаёт неверное число.
  const sPartial = stateOf({ hist: { query: '', error: '', entries: [],
                                     events: [], data: data, more: true } });
  assert.strictEqual(sPartial.historyCount, null,
    'есть непрочитанные страницы — числа у «История» нет');
  assert.strictEqual(s.historyCount, 2,
    'полностью загруженный список показывает точное число версий');
}

Promise.all([saveHonestyTest(), conflictTest()]).then(function () {
  console.log('PVR-UI-STATE-OK');
}).catch(function (e) {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
