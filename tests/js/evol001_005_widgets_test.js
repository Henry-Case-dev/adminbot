'use strict';
/* EVOL-001..005 — единая система строк статусных виджетов.
 *
 * Покрытие:
 *   EVOL-001: одна модель строки на четыре источника (`_ribbonLoop` — один
 *             проход, без дублей; семантика — только лейбл типа).
 *   EVOL-002: чистое ядро авто-движения `SFeed.step` (шаг/конец/возврат),
 *             отсутствие искусственного движения при недополнении, пауза и
 *             возобновление С ТЕКУЩЕЙ позиции, идемпотентный `attach`
 *             (один контроллер/слушатели на контейнер).
 *   EVOL-003: `_statusRecordFrom` — даты с РАЗНЫМ смыслом, отсутствующее поле
 *             помечено отсутствующим, provenance без выдумок.
 *   EVOL-005: дата/возраст строки, честная причина пустого состояния.
 *
 * Запуск: node tests/js/evol001_005_widgets_test.js → EVOL-001-005-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf-8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf-8');
const JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf-8');

// ── Минимальный stubbed-контекст (по образцу round1025) ────────────────────
let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  matchMedia: function () { return { matches: false, addEventListener() {} }; },
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      getContext() { return null; },
    };
  },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
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

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const computed = captured.computed || {};
const methods = captured.methods || {};
const SFeed = global.window.__StatusFeed;
assert(SFeed && typeof SFeed.step === 'function',
  'EVOL-002: контроллер лент доступен как window.__StatusFeed');

// ═══ EVOL-002: чистое ядро движения ═══════════════════════════════════════
(function () {
  const D = SFeed.DEFAULTS;
  assert(D.speedPxS > 0 && D.resumeMs > 0 && D.rewindMs > 0,
    'EVOL-002: параметры движения/паузы заданы явно');

  // Недополнение: никакого искусственного движения.
  const empty = SFeed.step({ y: 0, max: 0, phase: 'run' }, 100);
  assert.strictEqual(empty.phase, 'idle', 'EVOL-002: нет переполнения → idle');
  assert.strictEqual(empty.y, 0, 'EVOL-002: не двигаем искусственно');
  assert.strictEqual(empty.moving, false, 'EVOL-002: не двигаем искусственно');

  // Равномерный шаг: px = speed * dt.
  const one = SFeed.step({ y: 0, max: 1000, phase: 'run' }, 1000);
  assert.ok(Math.abs(one.y - D.speedPxS) < 0.001,
    'EVOL-002: шаг = speed × dt (плавно, не рывками)');
  assert.strictEqual(one.moving, true);

  // Возобновление С ТЕКУЩЕЙ позиции: y берётся из фактического scrollTop,
  // а не сбрасывается в 0 (никакого прыжка в начало списка).
  const resumed = SFeed.step({ y: 420, max: 1000, phase: 'run' }, 100);
  assert.ok(resumed.y > 420 && resumed.y < 440,
    'EVOL-002: возобновление продолжает текущую позицию');

  // Конец списка → удержание → плавный возврат в начало → старт.
  const atEnd = SFeed.step({ y: 999.5, max: 1000, phase: 'run' }, 1000);
  assert.strictEqual(atEnd.phase, 'hold_end', 'EVOL-002: конец → пауза');
  assert.ok(atEnd.y <= 1000 + 0.001, 'EVOL-002: не выходим за max');
  let st = atEnd;
  let guard = 0;
  while (st.phase === 'hold_end' && guard++ < 100) st = SFeed.step(st, 100);
  assert.strictEqual(st.phase, 'rewind', 'EVOL-002: после паузы — возврат');
  const rewind1 = SFeed.step(st, 200);
  assert.ok(rewind1.y < st.y, 'EVOL-002: возврат идёт плавно, без скачка');
  assert.ok(rewind1.y > 0, 'EVOL-002: возврат не мгновенный');
  let back = rewind1;
  guard = 0;
  while (back.phase === 'rewind' && guard++ < 200) back = SFeed.step(back, 100);
  assert.strictEqual(back.y, 0, 'EVOL-002: возврат завершается в начале');
  assert.strictEqual(back.phase, 'hold_start', 'EVOL-002: короткая пауза');
  let run = back;
  guard = 0;
  while (run.phase === 'hold_start' && guard++ < 100) run = SFeed.step(run, 100);
  assert.strictEqual(run.phase, 'run', 'EVOL-002: движение возобновляется');
})();

// ═══ EVOL-002: один контроллер на контейнер (идемпотентный attach) ═════════
(function () {
  const listeners = [];
  const el = {
    scrollTop: 0, scrollHeight: 900, clientHeight: 168, children: [],
    getAttribute() { return null; },
    setAttribute() {},
    removeAttribute() {},
    addEventListener(t, fn) { listeners.push(t); },
    removeEventListener() {},
  };
  const a = SFeed.attach(el);
  assert.ok(a, 'EVOL-002: контроллер создан');
  const b = SFeed.attach(el);
  assert.strictEqual(a, b, 'EVOL-002: повторный attach — тот же экземпляр');
  assert.strictEqual(SFeed.viewports.filter(function (v) {
    return v.el === el;
  }).length, 1, 'EVOL-002: один экземпляр на контейнер');
  const once = listeners.length;
  SFeed.attach(el);
  assert.strictEqual(listeners.length, once,
    'EVOL-002: слушатели не дублируются повторным attach');
  ['wheel', 'touchstart', 'keydown', 'scroll', 'mouseenter', 'focusin']
    .forEach(function (t) {
      assert.ok(listeners.indexOf(t) >= 0,
        'EVOL-002: ручное управление слушает ' + t);
    });
  // Пауза модалки не двигает список; после закрытия — снова двигает.
  a.setModal(true);
  assert.strictEqual(a.modal, true);
  assert.strictEqual(a.active(), false, 'EVOL-003: при открытом окне не двигаем');
  a.setModal(false);
  assert.strictEqual(a.active(), true, 'EVOL-003: после закрытия — двигаем');
  a.destroy();
  assert.strictEqual(el.__sfeed, a, 'EVOL-002: destroy не теряет ссылку до cleanup');
})();

// ═══ EVOL-001: одна модель строки, без дублей ══════════════════════════════
(function () {
  const loop = methods._ribbonLoop.call({
    ribbonItemClass: methods.ribbonItemClass,
  }, [
    { id: 1, fact: 'a', created_at: 100, status: 'confirmed',
      source_ids: [7], weight: 0.7, type: 'belief', chat_id: -100 },
    { id: 2, fact: 'b', created_at: 200 },
  ]);
  assert.strictEqual(loop.length, 2, 'EVOL-002: без дублирования рендера');
  assert.strictEqual(loop[0].fact, 'a');
  assert.strictEqual(loop[0].status, 'confirmed', 'EVOL-003: статус сохранён');
  assert.deepStrictEqual(loop[0].source_ids, [7], 'EVOL-004: источники сохранены');
  assert.strictEqual(loop[0].weight, 0.7);
  assert.strictEqual(loop[1].status, null, 'EVOL-003: нет статуса → null');
  assert.ok(loop[0].op.indexOf('ribbon-op-') === 0,
    'EVOL-001: подсветка по позиции (та же модель)');

  // Лимит модели — 12 строк, как было (без изменения поведения).
  const many = [];
  for (let i = 0; i < 20; i++) many.push({ id: i, fact: 'f' + i });
  assert.strictEqual(methods._ribbonLoop.call({
    ribbonItemClass: methods.ribbonItemClass,
  }, many).length, 12);
})();

// ═══ EVOL-003/005: «Новые факты» — даты не подменяются ════════════════════
(function () {
  const feed = computed.factsFeed.call({
    dossierFeed: [{
      chat_id: -100, name: 'Толян', user_name: 'Толян', user_id: 5,
      excerpt: 'кратко', text: 'полный текст факта', id: 42, kind: 'fact',
      origin: 'chat_history', tg_message_id: 777, attribution_method: 'direct',
      created_at: 1000, message_timestamp: 900, last_confirmed_at: 1100,
    }, { chat_id: -100, name: 'Пусто', excerpt: 'x' }],
  });
  const a = feed[0];
  assert.strictEqual(a.full, 'полный текст факта',
    'EVOL-003: полный текст, не только excerpt');
  assert.strictEqual(a.created_at, 1000);
  assert.strictEqual(a.event_at, 900, 'EVOL-005: дата события отдельно');
  assert.strictEqual(a.confirmed_at, 1100, 'EVOL-005: подтверждение отдельно');
  assert.strictEqual(a.tg_message_id, 777, 'EVOL-004: адрес сообщения');
  assert.strictEqual(a.origin, 'chat_history');
  const b = feed[1];
  assert.strictEqual(b.created_at, null, 'EVOL-005: нет даты — null, не 0');
  assert.strictEqual(b.event_at, null);
  assert.strictEqual(b.confirmed_at, null);
  assert.strictEqual(b.time, null, 'D5: time не выдумывается');
  assert.strictEqual(b.kind, null, 'D5: kind не выдумывается');
})();

// ═══ EVOL-003: поля окна записи (включая честное «нет данных») ═════════════
(function () {
  const ctx = {
    fmtTs: function (ts) { return 'T' + ts; },
    fmtClock: function () { return '12:00'; },
    fmtDayMonth: function () { return '30.10'; },
    oversightData: { chats: [{ chat_id: -100, title: 'Семья' }] },
    accessChats: [],
  };
  ctx.statusSourceMeta = methods.statusSourceMeta;
  ctx._statusOriginLabel = methods._statusOriginLabel;
  ctx._statusScopeLabel = methods._statusScopeLabel;
  ctx._shortText = methods._shortText;
  const rec = methods._statusRecordFrom.call(ctx, 'fact', {
    key: 'k1', id: 42, name: 'Толян', user_name: 'Толян', user_id: 5,
    chat_id: -100, full: 'полный текст', kind: 'fact',
    created_at: 1000, event_at: 900, confirmed_at: 1100,
    origin: 'chat_history', tg_message_id: 777,
  });
  const byKey = {};
  rec.fields.forEach(function (f) { byKey[f.key] = f; });
  ['text', 'type', 'scope', 'subject', 'user_id', 'created_at', 'event_at',
    'confirmed_at', 'updated_at', 'origin', 'status', 'sources', 'changes']
    .forEach(function (k) {
      assert.ok(byKey[k], 'EVOL-003: поле окна присутствует: ' + k);
    });
  assert.strictEqual(byKey.text.value, 'полный текст');
  assert.strictEqual(byKey.scope.value, 'Семья', 'EVOL-005: подпись чата');
  assert.strictEqual(byKey.user_id.value, '5');
  // Даты: значения и подписи РАЗНЫЕ (одна не подменяет другую).
  assert.strictEqual(byKey.created_at.value, 'T1000');
  assert.strictEqual(byKey.event_at.value, 'T900');
  assert.strictEqual(byKey.confirmed_at.value, 'T1100');
  const labels = [byKey.created_at.label, byKey.event_at.label,
    byKey.confirmed_at.label, byKey.updated_at.label];
  assert.strictEqual(new Set(labels).size, 4,
    'EVOL-005: четыре разных смысла дат');
  // Обновления в ответе нет → честное «нет данных», не подстановка.
  assert.strictEqual(byKey.updated_at.missing, true,
    'EVOL-003: отсутствующее поле помечено отсутствующим');
  assert.strictEqual(byKey.updated_at.value, null);
  assert.strictEqual(byKey.origin.value, 'сырое сообщение чата',
    'EVOL-003: происхождение человеческими словами');
  assert.ok(byKey.sources.value.indexOf('777') >= 0,
    'EVOL-004: адрес первоисточника показан');

  // Запись без адреса сообщения: источники отсутствуют честно.
  const bare = methods._statusRecordFrom.call(ctx, 'belief', {
    key: 'k2', id: 7, fact: 'убеждение', created_at: 500, chat_id: null,
  });
  const b = {};
  bare.fields.forEach(function (f) { b[f.key] = f; });
  assert.strictEqual(b.sources.missing, true, 'EVOL-004: нет адреса — нет данных');
  assert.strictEqual(b.scope.missing, true,
    'EVOL-005: неизвестный чат — «нет данных», не выдуманный GLOBAL');
  assert.strictEqual(bare.source, 'belief');
  assert.strictEqual(bare.badge, 'убеждение', 'EVOL-001: тип различается');
  assert.strictEqual(bare.section, 'Убеждения (Сон)');
  // Семантика четырёх источников различается лейблом.
  const metas = ['fact', 'belief', 'paradigm', 'trait'].map(function (s) {
    return methods.statusSourceMeta.call(ctx, s);
  });
  assert.strictEqual(new Set(metas.map(function (m) { return m.label; })).size, 4,
    'EVOL-001: тип записи различим для всех четырёх источников');
})();

// ═══ EVOL-005: дата/возраст строки ════════════════════════════════════════
(function () {
  const now = Math.floor(Date.now() / 1000);
  const ctx = {
    fmtClock: function (ts) { return 'C' + ts; },
    fmtDayMonth: function (ts) { return 'D' + ts; },
    fmtTs: function (ts) { return 'TS' + ts; },
  };
  assert.strictEqual(methods.statusRowAgeLabel.call(ctx, null), '',
    'EVOL-005: нет времени — пусто, без выдуманного возраста');
  assert.strictEqual(methods.statusRowAgeLabel.call(ctx, now - 30), 'сейчас');
  assert.ok(methods.statusRowAgeLabel.call(ctx, now - 600).indexOf('мин') >= 0);
  assert.ok(methods.statusRowAgeLabel.call(ctx, now - 7200).indexOf('ч') >= 0);
  assert.ok(methods.statusRowAgeLabel.call(ctx, now - 86400 * 3).indexOf('дн') >= 0);
  assert.strictEqual(methods.statusRowDateLabel.call(ctx, null), '');
  assert.ok(methods.statusRowDateLabel.call(ctx, now).indexOf('C') === 0,
    'EVOL-005: сегодня — время');
  assert.ok(methods.statusRowDateLabel.call(ctx, now - 86400 * 10)
    .indexOf('D') === 0, 'EVOL-005: иначе — день/месяц');
  assert.ok(methods.statusRowTitle.call(ctx, now, 'Записано')
    .indexOf('Записано: TS') === 0, 'EVOL-005: точный timestamp в title');
  assert.strictEqual(methods.statusRowTitle.call(ctx, null, 'Записано'), '');
})();

// ═══ EVOL-005: пустое состояние по фактической причине ════════════════════
(function () {
  const base = {
    statusFeedEmptyTitle: methods.statusFeedEmptyTitle,
    statusFeedEmptyText: methods.statusFeedEmptyText,
    statusFeedEmptyReason: methods.statusFeedEmptyReason,
    lastAttemptLabel: function () { return null; },
  };
  assert.ok(methods.statusFeedEmptyReason.call(
    Object.assign({ dossierFeedLoaded: false }, base), 'fact')
    .indexOf('не запрашивалась') >= 0,
    'EVOL-005: пусто ≠ «не загружали»');
  assert.ok(methods.statusFeedEmptyReason.call(
    Object.assign({ dossierFeedLoaded: true, memoryHealth: null }, base), 'fact')
    .indexOf('не передаёт') >= 0,
    'EVOL-005: недостающая причина названа недостающей, а не выдумана');
  assert.ok(methods.statusFeedEmptyReason.call(
    Object.assign({ dossierFeedLoaded: true,
      memoryHealth: { facts_unconfirmed: 4, facts_overdue: 2 } }, base), 'fact')
    .indexOf('не подтверждено: 4') >= 0,
    'EVOL-005: реальные счётчики вместо догадок');
  // Сон: выключен настройкой vs задача ещё не наступала — разные причины.
  assert.strictEqual(methods.statusFeedEmptyReason.call(
    Object.assign({ cognition: { dream: { enabled: false } } }, base), 'belief'),
    'сон выключен настройкой');
  assert.strictEqual(methods.statusFeedEmptyReason.call(
    Object.assign({ cognition: { dream: { enabled: true, last_run_at: null } } },
      base), 'belief'), 'задача ещё не наступала');
  assert.strictEqual(methods.statusFeedEmptyTitle.call(base, 'fact'),
    'Новых подтверждённых фактов нет');
})();

// ═══ Маркеры разметки/CSS (структурный контракт) ══════════════════════════
(function () {
  const viewports = (INDEX.match(/v-sfeed="statusRecordOpen"/g) || []).length;
  assert.strictEqual(viewports, 4,
    'EVOL-002: одна схема движения на все четыре источника');
  assert.ok(INDEX.indexOf('data-sfeed-row') >= 0, 'EVOL-001: строки лент');
  assert.ok(INDEX.indexOf('data-sfeed-modal') >= 0, 'EVOL-003: окно записи');
  assert.ok(INDEX.indexOf('data-rec-field') >= 0, 'EVOL-003: поля окна');
  assert.ok(INDEX.indexOf('data-rec-drill') >= 0, 'EVOL-004: первоисточник');
  assert.ok(INDEX.indexOf('data-rec-related') >= 0, 'EVOL-004: связанные записи');
  assert.ok(INDEX.indexOf('data-rec-dossier') >= 0, 'EVOL-004: досье субъекта');
  assert.ok(INDEX.indexOf('Что бот недавно запомнил') >= 0,
    'EVOL-001: подзаголовок раздела сохранён');
  assert.ok(/\.sfeed-viewport \{[\s\S]{0,400}overflow-y: auto/.test(CSS),
    'EVOL-002: окно — реальный скролл-контейнер');
  assert.ok(CSS.indexOf('.ribbon-track.sfeed-track { animation: none !important; }') >= 0,
    'EVOL-002: legacy CSS-marquee не конкурирует с контроллером');
  assert.ok(CSS.indexOf('.app-shell.sfeed-modal-open main.scroll-area') >= 0,
    'EVOL-003: фон не прокручивается');
  assert.ok(/@media \(prefers-reduced-motion: reduce\)[\s\S]{0,400}\.sfeed-viewport/.test(CSS),
    'EVOL-002: reduced-motion учтён в CSS');
  assert.ok(JS.indexOf("app.directive('sfeed'") >= 0,
    'EVOL-002: жизненный цикл контроллера — директива Vue');
  assert.ok(JS.indexOf('MutationObserver') >= 0 && JS.indexOf('ResizeObserver') >= 0,
    'EVOL-002: изменение списка и размеры окна обрабатываются');
  assert.ok(JS.indexOf('pauseManual') >= 0 && JS.indexOf('setModal') >= 0,
    'EVOL-002/003: пауза ручного действия и модалки');
})();

console.log('EVOL-001-005-OK');
