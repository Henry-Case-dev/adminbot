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
assert.strictEqual((INDEX.match(/<prompt-version-card/g) || []).length, 8,
  'ожидаются: библиотека, 2 полосы модулей, 2 мема, каталог, блок речи, '
  + 'раздел «Характер»');
// B1 (§2 / §2.2 п.1): раздел «Характер» — тоже prompt-field
// (`core.personality` / `core.personality.compact`), поэтому он использует
// тот же компонент, а не свой bounded-список с сырым sha и «Откатить».
{
  const coreStart = INDEX.indexOf("speechSection === 'core' && speechCore");
  assert.ok(coreStart >= 0, 'раздел «Характер» не найден в разметке');
  const coreEnd = INDEX.indexOf("speechSection === 'style' && speechStyle",
                                coreStart);
  const coreBlock = INDEX.slice(coreStart, coreEnd > coreStart
    ? coreEnd : coreStart + 20000);
  assert.ok(coreBlock.indexOf('<prompt-version-card') >= 0,
    '«Характер» обязан монтировать единый компонент версий');
  assert.ok(coreBlock.indexOf('speechCore.block_ids') >= 0,
    'ключ истории «Характера» — активная редакция из реестра');
  assert.strictEqual(coreBlock.indexOf('data-speech-core-more'), -1,
    'legacy-блок «Дополнительно: версии и откат» должен исчезнуть');
  assert.strictEqual(coreBlock.indexOf('Откатить</button>'), -1,
    'отдельный «Откатить» в «Характере» запрещён (§2.2 п.6: действия в панели)');
  assert.strictEqual(coreBlock.indexOf('sha256_12'), -1,
    'сырой sha не показывается в разделе «Характер»');
  assert.strictEqual(coreBlock.indexOf('rollbackSpeechBlock'), -1);
  assert.strictEqual(APP.indexOf('rollbackSpeechBlock'), -1,
    'мёртвый обработчик второго UI истории удалён');
  assert.strictEqual(APP.indexOf('speechHistKind'), -1);
  assert.strictEqual(APP.indexOf('speechHistScope'), -1);
}
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

// ── 2b. B2: «Подробности и диагностика» реально раскрывают блок ──────────
(function () {
  // Технические строки живут в постоянном <details data-pv-details>, который
  // раскрывается пунктом меню: иначе клик закрывал меню и ничего не показывал.
  assert.ok(TPL.indexOf('data-pv-details') >= 0,
    'нет постоянного блока подробностей');
  assert.ok(TPL.indexOf(':open="details"') >= 0,
    'блок подробностей должен управляться состоянием `details`');
  const det = TPL.slice(TPL.indexOf('data-pv-details'));
  assert.ok(det.indexOf('v-for="ln in detailsLines"') >= 0,
    'технические строки должны рендериться в блоке подробностей');
  assert.ok(det.indexOf('v-if="details"') >= 0,
    'содержимое подробностей рендерится только в раскрытом виде '
    + '(в свёрнутой карточке сырых id нет)');
  const menuTpl = TPL.slice(TPL.indexOf('data-pv-more-menu'));
  const menuEnd = menuTpl.indexOf('</div>');
  const menuOnly = menuTpl.slice(0, menuEnd > 0 ? menuEnd : 1200);
  assert.ok(menuOnly.indexOf('data-pv-more-details') >= 0,
    'пункт меню «Подробности и диагностика» обязателен');
  assert.strictEqual(menuOnly.indexOf('v-for="ln in detailsLines"'), -1,
    'технические строки не должны быть пунктами меню (исчезают вместе с ним)');
  // Состояние и метод: раскрытие — реальное, а не «закрыть меню».
  const c = ctx({ details: false });
  assert.strictEqual(c.details, false);
  CARD.methods.toggleDetails.call(c);
  assert.strictEqual(c.details, true);
  CARD.methods.toggleDetails.call(c);
  assert.strictEqual(c.details, false);
  const lines = stateOf({ hist: { data: {
    block_id: 'core.personality', pg_key: 'character.core', scope: 'global',
    factory_revision: 'fac:1', active: activeRow('manual'), entries: [] },
    error: '', entries: [] } }).detailsLines;
  assert.ok(lines.length >= 3 && lines.join(' ').indexOf('блок:') >= 0,
    'блок подробностей должен содержать человеко-технические строки: '
    + JSON.stringify(lines));
})();

// ── 2c. B4: подтверждение успеха переживает перечитывание ────────────────
(function () {
  let reloaded = 0;
  const okText = 'Сервер подтвердил: действует выбранная версия («ручная»).';
  const c = ctx({
    hist: { data: { active: activeRow('manual'), entries: [] }, error: '',
            entries: [{ order: 1, revision_id: 'r1' }], nextCursor: 'C1',
            more: true, result: { ok: true, text: okText } },
  });
  c.loadHistory = function () { reloaded += 1; return Promise.resolve(); };
  CARD.methods.reloadPreservingResult.call(c);
  assert.strictEqual(reloaded, 1, 'состояние должно перечитываться');
  assert.ok(c.hist.result && c.hist.result.text === okText,
    'подтверждение успеха стёрто перечитыванием: '
    + JSON.stringify(c.hist.result));
  assert.strictEqual(c.hist.data, null,
    'панель обязана перечитать сервер, а не показывать старое');
  // Явное закрытие и смена промпта убирают сообщение.
  CARD.methods.dismissResult.call(c);
  assert.strictEqual(c.hist.result, null, 'сообщение должно закрываться явно');
  assert.ok(TPL.indexOf('data-pv-result-dismiss') >= 0,
    'нужна кнопка закрытия сообщения (deliberate dismissal)');
  // B4: сообщение обязано стоять ПЕРЕД списком внутри тела панели, иначе оно
  // оказывается за 50 строками ленты и пользователь его не видит.
  const bodyIdx = TPL.indexOf('pv-panel__body');
  const resultIdx = TPL.indexOf('data-prompt-history-result');
  const rowsIdx = TPL.indexOf('data-prompt-history-versions');
  assert.ok(bodyIdx >= 0 && resultIdx > bodyIdx && rowsIdx > bodyIdx,
    'блок подтверждения и список должны быть в теле панели');
  assert.ok(resultIdx < rowsIdx,
    'подтверждение стоит после списка версий — пользователь его не увидит');
  assert.ok(TPL.indexOf('pv-result--sticky') >= 0,
    'подтверждение должно быть закреплено вверху тела панели (sticky)');
  const fresh = ctx({ hist: { data: { entries: [] }, error: '', entries: [],
                               result: { ok: true, text: okText } } });
  CARD.methods.resetPanel.call(fresh);
  assert.strictEqual(fresh.hist.result, null,
    'смена промпта/чата не должна тащить чужое сообщение');
})();

let s = stateOf({ hist: { data: {
  // PVR-01 contract: chat без override — действует глобальная версия.
  effective_origin: 'global', effective_status: 'matched',
  effective_content_hash: 'ab12cd34ef56ab12',
  effective_revision_id: 'rev-g1',
  revisions: [{ revision_id: 'rev-g1', created_at: '2026-11-03T23:42:00+00:00' }],
  active: null, baseline: { baseline: null },
  factory_matches_active: true, entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Действует глобальная версия',
  'чат без своего override наследует глобальную версию (PVR-01.7): '
  + s.state.text);
assert.strictEqual(s.state.detail, 'наследуется чатом');

s = stateOf({ chatId: null,
              hist: { data: {
                effective_origin: 'global', effective_status: 'matched',
                effective_content_hash: 'ab12cd34ef56ab12',
                effective_revision_id: 'rev-1',
                revisions: [{ revision_id: 'rev-1',
                              created_at: '2026-11-03T23:42:00+00:00' }],
                active: activeRow('manual'), baseline: null, entries: [] },
                error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Действует глобальная версия');
assert.ok(s.activeLabel.indexOf('03.11 23:42') >= 0,
  'дата действующей ревизии — из реальной строки ревизий: '
  + JSON.stringify(s.activeLabel));

s = stateOf({ hist: { data: {
  effective_origin: 'code', effective_status: 'matched',
  effective_content_hash: 'ff00ff00ff00ff00',
  effective_revision_id: 'rev-f1',
  revisions: [{ revision_id: 'rev-f1',
                created_at: '2026-11-01T10:00:00+00:00' }],
  active: activeRow('factory'), baseline: { baseline: null }, entries: [] },
  error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Исходный из кода');

// C3.6: baseline — отдельный указатель, НЕ синоним активного. Метка
// состояния не превращается в «Базовый…» от совпадения указателей.
s = stateOf({ hist: { data: {
  effective_origin: 'chat_override', effective_status: 'matched',
  effective_content_hash: '1212121212121212',
  effective_revision_id: 'rev-9',
  revisions: [{ revision_id: 'rev-9',
                created_at: '2026-11-03T21:00:00+00:00' }],
  active: activeRow('manual', null, 'rev-9'),
  baseline: { baseline: { revision_id: 'rev-9',
                          assigned_at: '2026-11-03T21:00:00+00:00',
                          assigned_by: '77' } },
  journal_active_revision_id: 'rev-9',
  entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Действует в этом чате',
  'baseline-указатель не подменяет метку действующей версии (C3.6): '
  + s.state.text);
assert.strictEqual(s.hasBaseline, true);

s = stateOf({ chatId: 42, hist: { data: {
  effective_origin: 'chat_override', effective_status: 'matched',
  effective_content_hash: '3434343434343434',
  effective_revision_id: 'rev-1',
  revisions: [{ revision_id: 'rev-1',
                created_at: '2026-11-03T23:42:00+00:00' }],
  active: activeRow('manual'), baseline: null, entries: [] },
  error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Действует в этом чате');
assert.ok(s.state.detail.indexOf('локальная версия') >= 0,
  'фраза «локальная версия» обязательна: ' + JSON.stringify(s.state.detail));

// ── PVR-01.2/01.7: честный unmatched — без выдуманной ревизии ────────────
// Текст действует, но в журнале нет ревизии с такими байтами. Журнальный
// указатель при этом существует (data.active/journal_*) — он НЕ даёт метку
// «активная» (мутация «журнальный указатель = matched» обязана падать).
s = stateOf({ hist: { data: {
  effective_origin: 'global', effective_status: 'unmatched',
  effective_content_hash: 'abababababababab',
  effective_revision_id: null,
  revisions: [{ revision_id: 'rev-1', created_at: '2026-11-03T23:42:00+00:00' }],
  active: activeRow('manual', null, 'rev-1'),
  journal_active_revision_id: 'rev-1',
  baseline: { baseline: null }, entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Не сопоставлено с историей',
  'несопоставленный текст честно называется: ' + s.state.text);
assert.strictEqual(s.isActiveEntry({ revision_id: 'rev-1' }), false,
  'при unmatched ни одна ревизия не помечена активной — включая '
  + 'журнальный указатель');
assert.strictEqual(s.canActivate({ revision_id: 'rev-1', actionable: true }),
  true, 'при unmatched применение сохранённой ревизии доступно — это '
  + 'честный способ устранить несоответствие');
assert.ok(s.detailsLines.join(' ').indexOf('не сопоставлена') >= 0,
  'в подробностях честно сказано, что ревизия не сопоставлена');

// ── PVR-01.7: drift — ни одна карточка не активна ────────────────────────
s = stateOf({ hist: { data: {
  effective_origin: 'global', effective_status: 'drift',
  effective_content_hash: 'cdcdcdcdcdcdcdcd',
  effective_revision_id: 'rev-2',
  revisions: [{ revision_id: 'rev-1' }, { revision_id: 'rev-2' }],
  active: activeRow('manual', null, 'rev-1'),
  journal_active_revision_id: 'rev-1',
  baseline: { baseline: null }, entries: [] }, error: '', entries: [] } });
assert.strictEqual(s.state.text, 'Журнал и действующий текст расходятся');
assert.strictEqual(s.drifted, true);
assert.strictEqual(s.isActiveEntry({ revision_id: 'rev-2' }), false,
  'при drift даже эффективная ревизия не помечается активной');
assert.strictEqual(s.isActiveEntry({ revision_id: 'rev-1' }), false);

// ── PVR-05.2 handoff: недоступный журнал — честная метка ─────────────────
s = stateOf({ hist: { error: 'История временно недоступна: журнал версий '
                            + 'недоступен (ошибка чтения)',
                      data: null, entries: [] } });
assert.strictEqual(s.state.text, 'История временно недоступна');
assert.ok(s.state.detail.indexOf('журнал версий недоступен') >= 0,
  'причина сохраняется рядом с меткой');

// ── 3. Действия: только по фактическим правам/статусам ───────────────────
function canActivate(patch, entry) {
  return stateOf(patch).canActivate(entry);
}
// PVR-01: состояние карточек теперь несёт effective-контракт; «активная»
// ревизия — та, которую резолвер сопоставил с действующим текстом.
const baseData = {
  effective_origin: 'chat_override', effective_status: 'matched',
  effective_content_hash: '1212121212121212',
  effective_revision_id: 'rev-1',
  active: activeRow('manual'), baseline: null,
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

// ── 5. Догрузка страниц ревизий: без дублей, по revisions_cursor, без
// событий в основном списке ────────────────────────────────────────────────
async function pagingTest() {
  const rev1 = { revision_id: 'r1', status: 'inactive' };
  const revPage2 = [{ revision_id: 'r51', status: 'inactive' },
                    { revision_id: 'r52', status: 'inactive' }];
  const calls = [];
  const c = ctx({
    hist: { data: { revisions: [rev1], entries: [] },
            error: '', entries: [], events: [], nextCursor: 'C1',
            more: true, moreLoading: false, moreError: '',
            nextEventsCursor: '', moreEvents: false,
            moreEventsLoading: false, moreEventsError: '',
            viewId: '', viewBody: '', viewError: '', diff: null,
            diffTitle: '', diffLoading: false, diffError: '', busyRev: '',
            result: null },
    root: { api: async function (url) {
      calls.push(url);
      return { revisions: revPage2,
               revisions_page: { next_cursor: 'C2', has_more: true } };
    } },
  });
  const scope = c;
  await CARD.methods.loadMore.call(scope);
  assert.strictEqual(c.revisionRows.length, 3, 'вторая страница не догружена');
  assert.ok(String(calls[0]).indexOf('revisions_cursor=C1') > 0,
    'догрузка ревизий идёт по стабильному revisions_cursor: ' + calls[0]);
  assert.strictEqual(c.hist.nextCursor, 'C2');
  // События активации в основной список не попадают (PVR-02.1/C1.2).
  // revision_id события намеренно НЕ совпадает ни с одной ревизией: иначе
  // дедупликация строк скрыла бы подмешивание событий в основной список.
  c.hist.data.activations = [{ activation_id: 7, revision_id: 'rev-event-only',
                               status: 'was_applied' }];
  assert.strictEqual(c.revisionRows.length, 3,
    'событие активации не превратилось в строку основного списка');
  assert.strictEqual(c.eventRows.length, 1);
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
  // B3 (§2.2 п.6, PVR-BASE-05): назначение базовой НЕ активирует версию.
  // Мутация «assign также активирует» обязана падать здесь.
  const activated = posts.filter(function (p) {
    return String(p.url).indexOf('/activate') > 0;
  });
  assert.deepStrictEqual(activated, [],
    '«Назначить базовой» не имеет права звать /activate: '
    + JSON.stringify(activated.map(function (p) { return p.url; })));
  assert.strictEqual(
    (c.hist.data && c.hist.data.active && c.hist.data.active.revision_id),
    'rev-1', 'назначение базовой не меняет активную ревизию');
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
