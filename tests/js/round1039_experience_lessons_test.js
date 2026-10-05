'use strict';
/* MCA-16 (round 10.39, ADR-1028-15 D9/D10, T-5006/T-5007) — JS-проверки:
 *   * computed `experienceFeed` — проекция аддитивного /api/status.experience;
 *     K1 OFF → honest disabled; unknown-исход → без выдуманного улучшения;
 *   * «Память»: loadLessons/lessonAction/saveLessonCorrection/openLessonTrace —
 *     права (suspend/activate/correct), trace только разрешённого чата;
 *   * wiring index.html: лента «Опыт» (Статус), таблица/карточка lessons
 *     (Память), A57-подпись, suspended виден и не применяется;
 *   * зеркало TABS: memory_experience на memory_rag.
 *
 * Запуск: node tests/js/round1039_experience_lessons_test.js → MCA16-EXP-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const ROOT = path.join(__dirname, '..', '..');
global.document = {
  addEventListener() {},
  getElementById() { return null; },
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
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;
const computed = captured.computed;
assert(computed && computed.experienceFeed,
  'computed.experienceFeed не найден');
for (const name of ['loadLessons', 'lessonAction', 'saveLessonCorrection',
                    'openLessonTrace', 'lessonTypeLabel', 'lessonStatusLabel',
                    'openLessonCard']) {
  assert(methods && methods[name], 'methods.' + name + ' не найден');
}

// ── 1. Лента «Опыт»: нет данных / OFF / implemented ────────────────────────
(function () {
  const empty = computed.experienceFeed.call({ statusData: null });
  assert.strictEqual(empty.ready, false);
  const off = computed.experienceFeed.call({ statusData: {
    experience: { enabled: false, state: 'disabled', items: [] } } });
  assert.strictEqual(off.ready, true);
  assert.strictEqual(off.enabled, false);
  assert.strictEqual(off.stateLabel, 'выключено');
  const on = computed.experienceFeed.call({ statusData: {
    experience: {
      enabled: true, state: 'implemented',
      items: [{ kind: 'activated', label: 'исправлен способ действия',
                summary: 'канон', scope: 'chat', ts: 1000 }],
      counters: { lessons: 1, active: 1, suspended: 0, applications: 0,
                  success: 0, failure: 0, unknown: 0 },
      improvement: { measured: false },
    } } });
  assert.strictEqual(on.ready, true);
  assert.strictEqual(on.enabled, true);
  assert.strictEqual(on.items.length, 1);
  assert.strictEqual(on.items[0].label, 'исправлен способ действия');
  assert.strictEqual(on.improvement.measured, false);
  assert.strictEqual(on.stateLabel, 'работает');
})();

// ── 2. «Память»: загрузка/действия/правка/trace ────────────────────────────
(async function () {
  const calls = [];
  const c = {
    _cidQuery: function () { return '?chat_id=-100'; },
    lessonsData: null, lessonsBusy: false, lessonCard: null,
    lessonDraft: { applicability: '', exceptions: '' },
    mcaLogFilter: { trace_id: '', chat_id: '', component: '',
                    reason_code: '' },
    api: async function (url, opts) {
      calls.push({ url: url, opts: opts });
      if (url.indexOf('/api/memory/lessons') === 0 && !opts) {
        return { enabled: true, state: 'implemented', count: 1,
                 lessons: [{ lesson_id: 'L1', version: 1, type: 'tool_usage',
                             scope: 'chat', status: 'active',
                             applicability: 'tool:web', exceptions: '',
                             counters: { success: 0, failure: 1, unknown: 0 },
                             applications_count: 1, grounds_count: 3,
                             versions: { policy: 'mca16-policy-1' },
                             applied: true, trace_available: true,
                             trace_ids: ['tr-1'] }] };
      }
      if (opts && opts.method === 'POST') {
        return { ok: true, lesson_id: 'L1', status: 'suspended' };
      }
      return null;
    },
    loadRelatedEvents: async function () { calls.push({ url: 'related' }); },
    navigateTo: function (r) { calls.push({ url: 'nav:' + r }); },
  };
  // Vue-методы на инстансе: saveLessonCorrection вызывает this.lessonAction.
  c.lessonAction = methods.lessonAction;
  await methods.loadLessons.call(c);
  assert.strictEqual(calls[0].url, '/api/memory/lessons?chat_id=-100');
  assert.strictEqual(c.lessonsData.count, 1);

  // suspend: POST с телом {lesson_id, version, action}; busy-защита
  await methods.lessonAction.call(c, c.lessonsData.lessons[0], 'suspend');
  const post = calls.filter(x => x.opts && x.opts.method === 'POST')[0];
  assert.strictEqual(post.url, '/api/memory/lessons/action');
  const body = JSON.parse(post.opts.body);
  assert.strictEqual(body.lesson_id, 'L1');
  assert.strictEqual(body.version, 1);
  assert.strictEqual(body.action, 'suspend');

  // correct: пустая правка → нет POST; изменённая → correct-версия
  c.lessonCard = c.lessonsData.lessons[0];
  c.lessonDraft = { applicability: 'tool:web', exceptions: '' };
  const before = calls.length;
  await methods.saveLessonCorrection.call(c);
  assert.strictEqual(calls.length, before, 'no-op правка не должна слать POST');
  c.lessonDraft = { applicability: 'tool:search', exceptions: '' };
  await methods.saveLessonCorrection.call(c);
  const corr = calls.filter(x => x.opts && x.opts.method === 'POST').pop();
  assert.strictEqual(JSON.parse(corr.opts.body).action, 'correct');
  assert.strictEqual(JSON.parse(corr.opts.body).applicability, 'tool:search');

  // trace: только разрешённый (trace_available) + фильтр + переход на Статус
  methods.openLessonTrace.call(c, { trace_available: true,
                                    trace_ids: ['tr-1'] });
  assert.strictEqual(c.mcaLogFilter.trace_id, 'tr-1');
  assert(calls.some(x => x.url === 'related'), 'связанные события не загружены');
  assert(calls.some(x => x.url === 'nav:#/'), 'нет перехода на Статус');
  const beforeForeign = calls.length;
  methods.openLessonTrace.call(c, { trace_available: false,
                                    trace_ids: ['tr-foreign'] });
  assert.strictEqual(calls.length, beforeForeign,
    'чужой trace не должен открываться');

  // ── 3. Wiring index.html + зеркало TABS ────────────────────────────────
  const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
  assert(INDEX.indexOf('data-experience') !== -1, 'лента «Опыт» не найдена');
  assert(INDEX.indexOf('data-experience-feed') !== -1,
    'элемент ленты опыта не найден');
  assert(INDEX.indexOf('data-lessons') !== -1, 'карточка уроков не найдена');
  assert(INDEX.indexOf('data-lessons-table') !== -1,
    'таблица уроков не найдена');
  assert(INDEX.indexOf('data-lesson-card') !== -1, 'карточка урока не найдена');
  assert(INDEX.indexOf('data-lesson-trace') !== -1, 'кнопка trace не найдена');
  assert(INDEX.indexOf('Измеренного улучшения нет') !== -1,
    'A57-подпись об отсутствии измеренного улучшения не найдена');
  assert(INDEX.indexOf('Урок приостановлен и не применяется') !== -1,
    'suspended-подпись не найдена');
  assert(INDEX.indexOf('Исправить (новая версия)') !== -1,
    'право «исправить» не найдено');
  assert(INDEX.indexOf('Отключить') !== -1, 'право «отключить» не найдено');
  assert(INDEX.indexOf('lessonCard.trace_available') !== -1
         || INDEX.indexOf('l.trace_available') !== -1,
    'trace-кнопка должна зависеть от разрешённого trace');
  assert(APP_JS.indexOf("groups: ['memory_experience']") !== -1,
    'зеркало TABS: memory_experience на memory_rag');
  assert(APP_JS.indexOf("'/api/memory/lessons'") !== -1);
  assert(APP_JS.indexOf("'/api/memory/lessons/action'") !== -1);
  assert(APP_JS.indexOf("this.navigateTo('#/')") !== -1);
  // R17: черновики правок не уходят в localStorage/sessionStorage
  assert(!/localStorage[^\n]*lessonDraft/.test(APP_JS),
    'черновик урока не должен попадать в localStorage');
  assert(!/sessionStorage[^\n]*lessonDraft/.test(APP_JS),
    'черновик урока не должен попадать в sessionStorage');

  console.log('MCA16-EXP-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
