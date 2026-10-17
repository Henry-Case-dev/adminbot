'use strict';
/* ═══ SOUL-1 / W5 — панель диагностики инициативы (Статус) ══════════════════
 * Контракт UI (SOUL-18.4/18.5/18.6):
 *   1) воронка и диагностика живут в ОДНОМ месте (якорь
 *      `data-initiative-independent` единственный, вторая аналитическая
 *      стена/страница/пункт навигации не добавлены);
 *   2) предупреждение «возможности есть, сообщений нет» показывается только
 *      когда оно реально есть (health ≠ outcome: тики не выдаются за
 *      отправку);
 *   3) блок причин/решений/доставок читает реальные поля (reason_label,
 *      message_id, ревизии Core/Style) и честен при их отсутствии;
 *   4) кнопка «Проверить инициативу» существует, грузит trace и ПО УМОЛЧАНИЮ
 *      не публикует (`publish:false`, `confirm_publish:false`);
 *   5) мягкие цели показываются с объяснением границ;
 *   6) навигация и фон/линза не изменены (никаких lg-lens/polymer в новом
 *      markup), новых таймеров нет.
 *
 * TEST-LIFECYCLE: CONTRACT owner=SOUL-18.4/18.5/18.6 (soul-1, W5)
 *
 * Запуск: node tests/js/soul1_w5_initiative_panel_test.js
 *         (печатает SOUL1-W5-PANEL-OK)
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

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
  addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) {
    return {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {},
      remove() { const i = _bodyChildren.indexOf(this); if (i >= 0) _bodyChildren.splice(i, 1); },
    };
  },
  body: {
    appendChild(el) { _bodyChildren.push(el); return el; },
    removeChild(el) { const i = _bodyChildren.indexOf(el); if (i >= 0) _bodyChildren.splice(i, 1); return el; },
  },
  execCommand() { return true; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () { throw new Error('no'); } } },
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
const methods = captured.methods || {};
const computed = captured.computed || {};
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

function vm(init) {
  // Харнесс как в Vue: computed — свойства (getter вызывает функцию),
  // data-поля теста перекрываются явно.
  const base = Object.create(methods);
  Object.keys(computed).forEach((k) => {
    Object.defineProperty(base, k, {
      configurable: true,
      get() { return computed[k].call(base); },
    });
  });
  Object.keys(init || {}).forEach((k) => {
    Object.defineProperty(base, k, {
      value: init[k], writable: true, configurable: true,
    });
  });
  return base;
}

// ── 1. Одно место: единственный якорь, без новых страниц/пунктов ───────────
{
  const anchor = INDEX.split('data-initiative-independent').length - 1;
  assert.strictEqual(anchor, 1,
    'W5: диагностика и воронка — в одном месте (якорь один: ' + anchor + ')');
  const check = INDEX.split('data-initiative-check').length - 1;
  assert.strictEqual(check, 1,
    'W5: кнопка проверки ровно одна (найдено: ' + check + ')');
  assert.ok(INDEX.indexOf('data-initiative-trace') >= 0,
    'W5: trace проверки рендерится в том же блоке');
  // Навигация и хаб «ИИ» не менялись: состав nav-пунктов прежний.
  const navItems = (APP.match(/\{ id: 'mod_\w+', icon:/g) || []).length;
  assert.strictEqual(navItems, 15,
    'W5: пункты модулей не добавлены/не удалены (найдено: ' + navItems + ')');
  assert.ok(APP.indexOf("href=\"#/modules/initiative\"") >= 0
    || APP.indexOf("'#/modules/initiative'") >= 0
    || APP.indexOf('modules/initiative') >= 0,
    'W5: вход в модуль «Инициатива» сохранён (прежняя навигация)');
  // Фон/линза не тронуты новым markup.
  const seg = INDEX.slice(INDEX.indexOf('data-initiative-independent'),
    INDEX.indexOf('data-initiative-independent') + 4200);
  ['lg-lens', 'polymer', '--lg-'].forEach((forbidden) => {
    assert.strictEqual(seg.indexOf(forbidden), -1,
      'W5: новый markup не трогает фон/линзу (' + forbidden + ')');
  });
}

// ── 2. Health ≠ outcome: предупреждение только когда оно есть ──────────────
{
  const v = vm({ initiativeFunnel: { stages: [] } });
  v.initiativeVitality = null;
  assert.strictEqual(v.w5Vitality, null,
    'W5: без данных панель не рисует выводов');
  v.initiativeVitality = { available: true,
    activity: { state: 'ok', level: 'ok', warning: '', title: 'Инициатива доставляется' } };
  assert.strictEqual(v.w5Warning, null,
    'W5: при реальной доставке предупреждения нет');
  v.initiativeVitality = { available: true,
    activity: { state: 'opportunities_no_messages', level: 'warn',
      title: 'Возможности есть, сообщений нет',
      warning: 'За окно найдено возможностей: 4, решений молчанием: 4, доставлено: 0.',
      recommendation: 'Сверить распределение причин ниже.' } };
  const w = v.w5Warning;
  assert.ok(w && w.warning.indexOf('доставлено: 0') >= 0,
    'W5: предупреждение «возможности есть, сообщений нет» показано');
  assert.strictEqual(w.level, 'warn');
  assert.ok(w.recommendation, 'W5: предупреждение сопровождается советом');
  // Метка здоровья отделяет тики от отправок.
  v.initiativeVitality.activity.health = { heartbeat_ok: true, jobs_processed: 7 };
  v.initiativeVitality.activity.counters = { delivered: 0 };
  const label = v.w5HealthLabel;
  assert.ok(label.indexOf('отправок: 0') >= 0,
    'W5: health-строка честно показывает нулевую отправку');
}

// ── 3. Причины, ворота, решения, доставки ─────────────────────────────────
{
  const v = vm({ initiativeFunnel: { stages: [] } });
  v.initiativeVitality = { available: true, activity: { warning: '' },
    gates: { items: [
      { gate: 'master', status: 'pass', label: 'ok' },
      { gate: 'min_gap', status: 'block', reason_code: 'min_gap',
        label: 'С последней реплики бота: 60 с (пауза 7200 с)',
        value: 60, limit: 7200, unit: 's' },
      { gate: 'live_context', status: 'warn', reason_code: 'empty_context',
        label: 'Живых сообщений за 24ч: 0', value: 0, limit: 1, unit: 'count' },
    ], soft_targets: { active: false, bounds: 'мягкая цель влияет только…' } },
    activity: { warning: '', reasons: [
      { reason_code: 'min_gap', label: 'пауза после последней реплики бота', count: 12 }] },
    decisions: [
      { ts: 1, action: 'silent', reason_code: 'recent_reply',
        reason_label: 'бот недавно уже отвечал', stage: 'new_message' }],
    refusals: [
      { ts: 2, action: 'say', reason_code: 'intent_closed',
        reason_label: 'намерение закрылось до отправки' }],
    sends: [
      { ts: 3, message_id: 777, chars: 48, core_revision: 'abc12345xyz',
        style_policy_revision: 'def45678xyz', composer: 'on' }],
  };
  const blockers = v.w5GateBlockers;
  assert.strictEqual(blockers.length, 2, 'W5: показываются только блок/warn');
  assert.ok(blockers[0].label.indexOf('пауза') > 0);
  const reasons = v.w5Reasons;
  assert.strictEqual(reasons[0].count, 12);
  const decisions = v.w5Decisions;
  assert.strictEqual(decisions[0].reason_label, 'бот недавно уже отвечал');
  const sends = v.w5Sends;
  assert.strictEqual(sends[0].hasMessageId, true);
  assert.strictEqual(sends[0].messageId, '777');
  assert.strictEqual(sends[0].core, 'abc12345');
  assert.strictEqual(sends[0].style, 'def45678');
  assert.strictEqual(sends[0].hasManifest, true);
  // Доставка без манифеста — честная пометка, не выдуманные ревизии.
  v.initiativeVitality.sends = [{ ts: 4, message_id: null, chars: 10 }];
  const bare = v.w5Sends;
  assert.strictEqual(bare[0].hasMessageId, false);
  assert.strictEqual(bare[0].hasManifest, false);
  // Мягкие цели с границами.
  assert.ok(v.w5SoftLabel.indexOf('не заданы') >= 0,
    'W5: незаданные мягкие цели названы честно');
  v.initiativeVitality.gates.soft_targets = {
    active: true, replies_per_day: 6, observation_interval_seconds: 1800,
    bounds: 'дневной лимит не отключается' };
  const soft = v.w5SoftLabel;
  assert.ok(soft.indexOf('6 инициатив/сутки') >= 0
    && soft.indexOf('1800') >= 0, 'W5: мягкие цели видны владельцу');
  assert.ok(v.w5SoftBounds.indexOf('не отключается') >= 0,
    'W5: границы мягких целей показаны');
}

// ── 4. Проверка «Проверить инициативу»: mock по умолчанию ─────────────────
{
  const body = APP.slice(APP.indexOf("runInitiativeCheck: async function"),
    APP.indexOf("runInitiativeCheck: async function") + 1400);
  assert.ok(body.indexOf('/api/memory/initiative-check') >= 0,
    'W5: кнопка ходит в существующий endpoint проверки');
  assert.ok(body.indexOf('publish: false') >= 0
    && body.indexOf('confirm_publish: false') >= 0,
    'W5: по умолчанию проверка НЕ публикует');
  assert.ok(body.indexOf('setInterval') < 0 && body.indexOf('setTimeout') < 0,
    'W5: проверка без новых таймеров');
  const loadBody = APP.slice(APP.indexOf('loadInitiativeVitality: async function'),
    APP.indexOf('loadInitiativeVitality: async function') + 900);
  assert.ok(loadBody.indexOf('/api/memory/initiative-vitality') >= 0,
    'W5: панель читает единый диагностический endpoint');
  // Ручная проверка: методы (не computed) присутствуют и держат scope-guard.
  assert.ok(loadBody.indexOf('_scopeGuard') >= 0,
    'W5: смена чата не оставляет чужой снимок в панели');

  const v = vm();
  v.initiativeCheck = null;
  v.initiativeVitality = { available: true };
  assert.strictEqual(v.w5CheckNote, '',
    'W5: без прогона нет и заявлений о нём');
  v.initiativeCheck = { available: true, published: false, publish_mode: 'mock',
    publish_disabled_reason: 'publish_axis_off', llm_calls: 2,
    trace: [{ stage: 'mock_send', status: 'ok', reason_code: '',
              label: 'Готово к отправке: 42 символов' }],
    mock_send: { attempted: true, preview: 'Реплика', published: false } };
  const note = v.w5CheckNote;
  assert.ok(note.indexOf('выключена настройкой владельца') >= 0,
    'W5: выключенная публикация объясняется честно');
  assert.strictEqual(v.w5CheckTrace.length, 1);
  assert.strictEqual(v.w5CheckPreview, 'Реплика');
  v.initiativeCheck = { available: true, published: true, publish_mode: 'real',
    mock_send: { attempted: false, preview: '', published: true } };
  assert.ok(v.w5CheckNote.indexOf('РЕАЛЬНАЯ отправка') >= 0,
    'W5: реальная отправка помечается явно, а не как mock');
}

// ── 5. Каталоговые подписи мягких целей ────────────────────────────────────
{
  ['initiative.soft_target_replies_per_day',
    'initiative.observation_target_interval_seconds',
    'flags.initiative_diagnostics_publish_enabled'].forEach((key) => {
    assert.ok(APP.indexOf("'" + key + "'") >= 0,
      'W5: подпись каталога для ' + key);
  });
  assert.ok(APP.indexOf('мягкая цель влияет только') >= 0
    || APP.indexOf('Это цель, а не обещание') >= 0,
    'W5: границы мягких целей объяснены владельцу словами');
}

console.log('SOUL1-W5-PANEL-OK');
