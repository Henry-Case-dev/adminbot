'use strict';
/* MOD-ACL-UX-01 — узкий corrective 2026-11-27 (D1/D2/D4/D5), реальный app.js.

Предмет (блокирующие дефекты приёмки M6 на 2.58.257):
  D1 `BL-03`  — описание модуля больше не дублируется дословно в карточке
                каталога (`module-card-phrase`) и шапке страницы
                (`data-workspace-phrase` не рендерится);
  D2 `BL-09`  — конверт журнала уроков не склеивается со статусом соседней
                записи в ложное «активен уроков: 100»: размер страницы
                назван страницей («на странице: N»), реальный total журнала
                берётся из `/api/experience/pipeline` и печатается отдельно
                («всего в журнале: T»); 100 и 500 строк страницы различимы
                и не выдаются за число записей журнала;
  D4 `S10-18` — `prefers-reduced-motion: reduce` останавливает `.spinner`;
  D5 `BL-04`  — чипы осей не дублируют подпись («Готовность: Готовность…»,
                «Измерение: Измерение…», «Исполняется: Исполняется»), а
                состояние модуля без измерения не утверждает «работа …».

D3 (`BL-11`/`S10-18` тач-цели) и D6 (`S7-454`/`S17-728`) в этом файле только
фиксируются как НЕвоспроизведённые на выложенной линии: hit-area 22-px
контролов расширен псевдоэлементом до 44 px (проверка — живой elementFromPoint
в evidence), а резолвер обучения уже читает чат-оверрайд
(`learning_state` → `resolve_param_capability`); их регрессия ниже —
структурные инварианты, чтобы фикс нельзя было молча потерять.

Запуск: node tests/js/mod_acl_ux_m5c_corrective_test.js
*/
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'),
  'utf8');
const JOBS = fs.readFileSync(
  path.join(ROOT, 'services', 'mca_experience_jobs.py'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() {
    return { style: {}, setAttribute() {}, remove() {},
             appendChild() {}, removeChild() {} };
  },
  body: { appendChild() {}, removeChild() {} },
  querySelector() { return null; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');

const { applyModuleDto } = require('./module_fixture.js');
const data = applyModuleDto(captured);
const methods = captured.methods;

let checks = 0;
const failures = [];
function ok(v, msg) {
  checks += 1;
  if (!v) failures.push('FAIL: ' + msg);
}
function eq(a, b, msg) {
  checks += 1;
  if (a !== b) {
    failures.push('FAIL: ' + msg + ' | got=' + JSON.stringify(a)
      + ' want=' + JSON.stringify(b));
  }
}

function moduleById(id) {
  return data.modules.filter(function (m) { return m.id === id; })[0];
}
const EXPERIENCE = moduleById('mod_experience');
assert(EXPERIENCE, 'каталог DTO должен содержать mod_experience');

// ── D1 (BL-03): описание не дублируется в шапке страницы ───────────────────
{
  ok(INDEX.indexOf('data-workspace-phrase') < 0,
    'D1: шапка модуля не рендерит вторую копию описания');
  ok(INDEX.indexOf('module-card-phrase') >= 0,
    'D1: описание осталось в карточке каталога');
  ok(INDEX.indexOf('workspaceModule.subtitle') < 0,
    'D1: шапка не выводит workspaceModule.subtitle');
  const phrase = EXPERIENCE.subtitle || '';
  ok(phrase.length > 0, 'D1: у модуля есть описание из DTO');
  // Тот же текст не должен встречаться вторым шаблонным выводом.
  const occurrences = INDEX.split('m.subtitle').length - 1;
  eq(occurrences, 1, 'D1: ровно один шаблонный вывод m.subtitle (карточка)');
}

// ── D2 (BL-09) / F1: размер страницы ≠ число записей журнала ───────────────
//
// `/api/memory/lessons` отдаёт страницу (`count` = len(rows), limit≤500) —
// это НЕ размер журнала. UI обязан называть страницу страницей, а реальный
// total брать из существующего источника (`/api/experience/pipeline`
// counters.lessons) и печатать отдельно. Тест различает 100 и 500 строк
// страницы при одном и том же журнале (544).
{
  function env(count, state, opts) {
    const c = Object.assign({}, methods);
    METHODS_BIND(c);
    const o = opts || {};
    c.activeChatId = o.chatId === undefined ? null : o.chatId;
    c.lessonsData = null;
    c.expPipeline = o.pipeline === undefined ? null : o.pipeline;
    c.expPipelineScope = o.pipelineScope === undefined
      ? (o.pipeline ? 'global' : null) : o.pipelineScope;
    if (o.meta !== false) {
      c._wsHistoryMeta = function () {
        return { count: count, state: state };
      };
    } else {
      c.lessonsData = {
        enabled: true, state: state, count: count, lessons: [],
      };
    }
    return methods.historyEnvelopeText.call(c, EXPERIENCE);
  }

  const journal = {
    counters: { lessons: { active: 1, suspended: 464, superseded: 79 } },
  };
  const page100 = env(100, 'implemented', { pipeline: journal });
  const page500 = env(500, 'implemented', { pipeline: journal });

  eq(page100, 'на странице: 100 · всего в журнале: 544',
    'F1: limit=100 — это страница, total отдельно (544)');
  eq(page500, 'на странице: 500 · всего в журнале: 544',
    'F1: limit=500 — та же подпись страницы, total не меняется');
  ok(page100 !== page500, 'F1: разные страницы различимы');
  ok(page100.indexOf('в журнале: 100') < 0
    && page500.indexOf('в журнале: 500') < 0,
    'F1: размер страницы не выдаётся за число записей журнала');
  ok(page100.indexOf('implemented') < 0,
    'D2: сырой англ. код состояния не печатается');
  ok(/всего в журнале: 544/.test(page100)
    && /всего в журнале: 544/.test(page500),
    'F1: total берётся из pipeline counters, а не из страницы');

  // Total неизвестен (pipeline ещё не загружен) — честно только страница.
  const noTotal = env(100, 'implemented', { pipeline: null });
  eq(noTotal, 'на странице: 100',
    'F1: без total печатается только размер страницы');
  ok(noTotal.indexOf('журнале') < 0,
    'F1: без total нет утверждения о размере журнала');

  // fallback: learning_analytics.lessons.total
  const pageAnalytics = env(100, 'implemented', {
    pipeline: { learning_analytics: { lessons: { total: 544 } } },
  });
  ok(/всего в журнале: 544/.test(pageAnalytics),
    'F1: total берётся и из learning_analytics.lessons.total');

  ok(env(0, 'not_run', { pipeline: null }).indexOf('записей нет') >= 0,
    'D2: not_run без total → «записей нет»');
  eq(env(0, 'disabled', {}), 'функция выключена',
    'D2: disabled → «функция выключена»');
  ok(env(7, 'weird_code', {}).indexOf('состояние: weird_code') >= 0,
    'D2: неизвестный код назван как состояние, а не выдуман');

  // ── F1 (r2): total только того же scope, что и страница ──────────────────
  //
  // deep link/refresh в GLOBAL грузит глобальный pipeline; после
  // setActiveChat(B) тот же снимок НЕ должен выдаваться за журнал чата B.
  const GLOBAL_PIPE = {
    counters: { lessons: { active: 4000, suspended: 800, superseded: 99 } },
  };
  const CHAT_PIPE = {
    counters: { lessons: { active: 1, suspended: 464, superseded: 79 } },
  };
  const CHAT = -1004482340693;
  const OTHER = -1009999999999;

  const globalCtx = Object.assign({}, methods);
  globalCtx.activeChatId = null;
  globalCtx.expPipeline = GLOBAL_PIPE;
  globalCtx.expPipelineScope = 'global';
  eq(methods.lessonsJournalTotal.call(globalCtx), 4899,
    'F1: глобальный scope — глобальный total 4899');

  // Страница чата, а снимок всё ещё глобальный (репорт r2: 100 · 611).
  globalCtx.activeChatId = CHAT;
  eq(methods.lessonsJournalTotal.call(globalCtx), null,
    'F1: чужой (глобальный) снимок не даёт total для чата');
  eq(methods.historyEnvelopeText.call(Object.assign({}, methods, {
    activeChatId: CHAT, expPipeline: GLOBAL_PIPE,
    expPipelineScope: 'global', lessonsData: null,
    _wsHistoryMeta: function () { return { count: 3, state: 'implemented' }; },
  }), EXPERIENCE), 'на странице: 3',
  'F1: при неизвестном scope total не показывается (только страница)');

  // После перезагрузки pipeline для этого чата total = 544.
  globalCtx.expPipeline = CHAT_PIPE;
  globalCtx.expPipelineScope = 'chat:' + CHAT;
  eq(methods.lessonsJournalTotal.call(globalCtx), 544,
    'F1: total чата 544 после скоуп-корректной загрузки');

  // Переключение на другой чат — снова неизвестный scope, а не 544.
  globalCtx.activeChatId = OTHER;
  eq(methods.lessonsJournalTotal.call(globalCtx), null,
    'F1: после переключения чата чужой total не показывается');

  // Сброс снимка чистит и данные, и scope.
  const resetCtx = Object.assign({}, methods);
  resetCtx.activeChatId = CHAT;
  resetCtx.expPipeline = CHAT_PIPE;
  resetCtx.expPipelineScope = 'chat:' + CHAT;
  resetCtx.expPipelineError = 'x';
  resetCtx.expPipelineBusy = true;
  ok(typeof methods._resetExperiencePipeline === 'function',
    'F1: есть метод сброса снимка pipeline');
  if (typeof methods._resetExperiencePipeline === 'function') {
    methods._resetExperiencePipeline.call(resetCtx);
    ok(resetCtx.expPipeline === null && resetCtx.expPipelineScope === null,
      'F1: _resetExperiencePipeline чистит снимок и scope');
  }
  eq(methods.lessonsJournalTotal.call(resetCtx), null,
    'F1: после сброса total неизвестен');

  // Миграция со старым снимком без scope-метки: total не выдумывается.
  const legacyCtx = Object.assign({}, methods);
  legacyCtx.activeChatId = CHAT;
  legacyCtx.expPipeline = CHAT_PIPE;
  legacyCtx.expPipelineScope = undefined;
  eq(methods.lessonsJournalTotal.call(legacyCtx), null,
    'F1: снимок без scope-метки не выдаётся за журнал чата');

  // Соседняя строка «Сейчас:» не образует фразу «активен уроков: N».
  const row = Object.assign({}, methods);
  METHODS_BIND(row);
  const lesson = {
    lesson_id: 'L1', version: 1, created_at: 1795760000,
    type: 'failure_pattern', status: 'active', scope: 'chat',
    scope_chat_id: -1004482340693,
  };
  const nowLine = methods.historyRowLine.call(row, EXPERIENCE, lesson);
  eq(nowLine.indexOf(' · активен'), nowLine.length - ' · активен'.length,
    'D2: строка записи заканчивается статусом «активен»');
  const composed = 'Сейчас: ' + nowLine + ' · ' + page100;
  ok(!/активен\s+(уроков|на странице)/.test(composed),
    'D2/F1: статус записи не склеивается со счётчиком страницы');
  ok(/на странице: 100/.test(composed),
    'F1: строка «Сейчас» несёт размер страницы, а не «уроков: N»');
  ok(composed.indexOf('в журнале: 100') < 0,
    'F1: размер страницы не читается как число записей журнала');
  ok(INDEX.indexOf('· {{ historyEnvelopeText') >= 0,
    'D2: шаблон ставит разделитель перед счётчиком журнала');
}

// ── D5 (BL-04): чипы осей без дублей, состояние без ложного «работа …» ─────
{
  const mod = {
    id: 'mod_experience', title: 'Опыт и уроки', toggleKey: 'k',
    permissions: { can_read: true, can_edit: true },
    state: {
      desired: true, effective_runtime: true, ready: null, observed: null,
      source: 'global', checked_at: '2026-11-27T19:54:22Z',
      last_activity_at: null,
    },
  };
  const ctx = Object.assign({}, methods);
  METHODS_BIND(ctx);
  const chips = methods.moduleStateChips.call(ctx, mod);
  const byId = {};
  chips.forEach(function (c) { byId[c.id] = c; });
  eq(byId.effective.text, 'Исполняется', 'D5: ось effective — «Исполняется»');
  ok(byId.effective.standalone === true,
    'D5: effective — самодостаточная подпись без «label:»');
  eq(byId.ready.text, 'Готовность не проверяется',
    'D5: ready без повтора подписи');
  ok(byId.ready.standalone === true, 'D5: ready — standalone');
  eq(byId.observed.text, 'Измерение не подтверждено',
    'D5: observed без повтора подписи');
  ok(byId.observed.standalone === true, 'D5: observed — standalone');
  eq(byId.desired.label, 'Настройка', 'D5: «Настройка» остаётся с label');
  eq(byId.source.label, 'Источник', 'D5: «Источник» остаётся с label');

  // Ни один чип не печатает «X: X…» (двойная подпись оси).
  chips.forEach(function (c) {
    if (c.standalone) return;
    const line = c.label + ': ' + c.text;
    ok(line.indexOf(c.label + ': ' + c.label) < 0,
      'D5: чип ' + c.id + ' не дублирует подпись: ' + line);
  });

  eq(methods.moduleStateText.call(ctx, mod),
    'Включено · измерение не подтверждено',
    'D5: при observed=null шапка не утверждает «работа …»');

  // Противоположный случай: подтверждённое измерение — прежняя честная строка.
  const modOk = JSON.parse(JSON.stringify(mod));
  modOk.state.observed = true;
  modOk.state.last_activity_at = '2026-11-27T19:54:22Z';
  eq(methods.moduleStateText.call(ctx, modOk), 'Работает',
    'D5: observed=true → «Работает» (подтверждено измерением)');
  ok(methods.moduleStateChips.call(ctx, modOk)
    .filter(function (c) { return c.id === 'observed'; })[0]
    .text.indexOf('Подтверждено') === 0,
  'D5: observed=true → «Подтверждено: …»');
}

// ── D4 (S10-18): reduced motion останавливает .spinner ────────────────────
{
  const m = CSS.match(
    /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*\.spinner[^}]*animation:\s*none/);
  ok(m, 'D4: под prefers-reduced-motion .spinner имеет animation: none');
  ok(/\.spinner\s*\{[^}]*animation:\s*spin/.test(CSS),
    'D4: базовая анимация спиннера не удалена');
}

// ── D3/D6: поведенческий гейт — в e2e (реальный DOM), здесь только CSS-факты ─
//
// F3: текстовые проверки НЕ доказывают hit-area (они проходят и на дефектной
// базе), поэтому поведение ±20 px проверяет
// `tests/test_mod_acl_ux_m5c_corrective_e2e.py` (Chromium + elementFromPoint).
// Здесь остаются инварианты, которые нельзя потерять молча.
{
  const coarse = CSS.match(
    /@media\s*\(pointer:\s*coarse\),\s*\(max-width:\s*767px\)\s*\{[\s\S]*?\n\}/);
  ok(coarse, 'D3: блок coarse/mobile-правил hit-area найден');
  const block = coarse ? coarse[0] : '';
  // F2 (r2): кликабельная площадь = РЕАЛЬНЫЙ 44-px бокс кнопки; текст
  // (подпись/состояние) вне его, поэтому никакого вертикального
  // псевдоэлемента-перекрытия быть не должно.
  ok(/\.module-card \.module-tristate-btn\s*\{[^}]*min-height:\s*44px/.test(block),
    'D3/F2: кнопка tri-state реально ≥44 px');
  ok(!/module-tristate-btn::after\s*\{[^}]*inset:\s*-2\dpx/.test(block),
    'D3/F2: hit-area не расширяется псевдоэлементом поверх текста');
  ok(block.indexOf('.module-card-footer .btn-ghost::after') >= 0,
    'D3: hit-area кнопки «Открыть» расширяется псевдоэлементом');
  ok(/async def learning_state\(/.test(JOBS),
    'D6: единый резолвер обучения присутствует');
  ok(/resolve_param_capability\(/.test(JOBS),
    'D6: резолвер читает чат-оверрайд (GLOBAL — наследуемый дефолт)');
  ok(!/if not _learning_enabled\(\):\s*\n\s*return False/.test(JOBS),
    'D6: глобальная ось не гасит чат до чтения оверрайда');
  ok(/def review_enabled\(\)[\s\S]{0,600}experience_lessons_enabled\(\)[\s\S]{0,200}experience_review_enabled\(\)/.test(JOBS),
    'D6: review_enabled решают только аварийные env-оси K1/K3');
}

function METHODS_BIND(ctx) {
  // Ничего не переопределяем: все хелперы (fmtLogTs/moduleReasonText/…)
  // уже на объекте methods, который копируется в ctx.
  return ctx;
}

if (failures.length) {
  console.error('MOD-ACL-UX-01 CORRECTIVE unit FAILED: '
    + failures.length + ' / ' + checks);
  failures.forEach(function (f) { console.error('  ' + f); });
  process.exit(1);
}
console.log('MOD-ACL-UX-01 CORRECTIVE D1/D2/D4/D5 unit: ' + checks
  + ' checks OK');
console.log('MODACL-CORRECTIVE-UNIT-OK');
