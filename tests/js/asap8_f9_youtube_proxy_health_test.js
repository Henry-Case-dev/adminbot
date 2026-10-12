'use strict';
/* ASAP 8 F9 (§16, Y4/Y5) — JS-проверки MiniApp-блока «YouTube прокси»:
 *   * блок youtube-proxy-health-block ТОЛЬКО на вкладке «Выжимка видео»
 *     (mod_video_summary) и ТОЛЬКО для global admin (fail-closed 403 на API);
 *   * ленивый GET /api/youtube/proxy/health при первом открытии вкладки
 *     (setTab-хук), живая проба — ТОЛЬКО по кнопке (POST /api/youtube/proxy/test);
 *   * busy-guard: повторный клик не дублирует пробу;
 *   * подписи шагов человекочитаемы (§18I.6): auth 407 → явный текст + next
 *     action («проверьте логин/пароль прокси» в шаблоне); секреты не
 *     рендерятся (только masked endpoint + коды — контракт API Y5).
 *
 * Запуск: node tests/js/asap8_f9_youtube_proxy_health_test.js → F9-PROXY-UI-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
const ROOT = path.join(__dirname, '..', '..');
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    // Расширенный стаб: Vue runtime-compiler (decodeEntities) требует
    // innerHTML/children/textContent на созданном элементе; getAttribute
    // разбирает значение из установленного innerHTML (`<div foo="X">`).
    const el = {
      tagName: tag, className: '', value: '', style: {},
      setAttribute() {}, focus() {}, select() {}, remove() {},
      _html: '',
      get innerHTML() { return el._html; },
      set innerHTML(v) { el._html = String(v); },
      textContent: '',
    };
    el.children = [{
      getAttribute(name) {
        const m = el._html.match(new RegExp(name + '="([^"]*)"'));
        return m ? m[1] : null;
      },
    }];
    return el;
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
const data = captured.data();

assert(methods.loadYoutubeProxyHealth, 'methods.loadYoutubeProxyHealth не найден');
assert(methods.runYoutubeProxyTest, 'methods.runYoutubeProxyTest не найден');
assert(methods.ytProxyStepLabel, 'methods.ytProxyStepLabel не найден');
assert(methods.ytProxyCodeLabel, 'methods.ytProxyCodeLabel не найден');
assert('ytProxyHealth' in data, 'state.ytProxyHealth не найден');
assert('ytProxyHealthBusy' in data, 'state.ytProxyHealthBusy не найден');

// ── 1. Подписи шагов: ok / fail(407) / unreachable / skipped ────────────────
(function () {
  const label = methods.ytProxyStepLabel;
  assert.strictEqual(label.call(null, { status: 'ok' }), 'OK');
  assert.strictEqual(
    label.call(null, { status: 'fail', reason: 'proxy_auth_failed' }),
    'ОШИБКА · авторизация отклонена (407)');
  assert.strictEqual(
    label.call(null, { status: 'fail', reason: 'proxy_unreachable' }),
    'ОШИБКА');
  assert.strictEqual(label.call(null, { status: 'unreachable' }), 'недоступен');
  assert.strictEqual(label.call(null, { status: 'skipped' }), '—');
  assert.strictEqual(label.call(null, null), '—');
})();

// ── 2. Коды классов — по-русски, unknown код не падает ──────────────────────
(function () {
  const code = methods.ytProxyCodeLabel;
  assert.strictEqual(code('proxy_auth_failed'), 'ошибка авторизации прокси (407)');
  assert.strictEqual(code('rate_limited'), 'слишком много запросов (429)');
  assert.strictEqual(code('mystery_code'), 'mystery_code');
  assert.strictEqual(code(null), '');
})();

// ── 3. runYoutubeProxyTest: POST + busy-guard ───────────────────────────────
(async function () {
  const calls = [];
  const ctx = {
    ytProxyHealthBusy: false,
    ytProxyHealth: null,
    toast() {},
    api: async function (p, opts) {
      calls.push({ path: p, opts: opts || {} });
      return { configured: true };
    },
  };
  await methods.runYoutubeProxyTest.call(ctx);
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].path, '/api/youtube/proxy/test');
  assert.strictEqual(calls[0].opts.method, 'POST');
  assert.strictEqual(ctx.ytProxyHealth.configured, true);
  assert.strictEqual(ctx.ytProxyHealthBusy, false);
  // busy-guard: пока идёт проба, повторный клик — no-op
  ctx.ytProxyHealthBusy = true;
  await methods.runYoutubeProxyTest.call(ctx);
  assert.strictEqual(calls.length, 1, 'busy-клик не должен дублировать POST');
})();

// ── 4. setTab-хук: ленивый GET только для global admin и один раз ───────────
(function () {
  const shared = { loaded: 0, ytProxyHealth: null };
  function ctx(overrides) {
    return Object.assign({
      copiedTimer: null,
      copiedIndex: null,
      activeTab: '',
      configSearch: '',
      canViewTab() { return false; },
      isGlobalAdmin: true,
      ytProxyHealth: shared.ytProxyHealth,
      ytProxyHealthBusy: false,
      loadYoutubeProxyHealth() {
        shared.loaded += 1;
        shared.ytProxyHealth = { configured: true };  // как реальный метод
      },
      loadModules() {},
      loadGateInfo() {},
      stopStatusPolling() {},
      stopCognitionPolling() {},
      destroyCognitionGraph() {},
      $nextTick(fn) { fn(); },
    }, overrides || {});
  }
  methods.setTab.call(ctx(), 'mod_video_summary');
  assert.strictEqual(shared.loaded, 1, 'первое открытие → ленивый GET');
  methods.setTab.call(ctx(), 'mod_video_summary');
  assert.strictEqual(shared.loaded, 1, 'повторное открытие (данные есть) → без GET');
  shared.ytProxyHealth = null;   // данные нет — но грузит только global admin
  methods.setTab.call(ctx({ isGlobalAdmin: false }), 'mod_video_summary');
  assert.strictEqual(shared.loaded, 1, 'не global admin → блок/GET нет (fail-closed)');
  methods.setTab.call(ctx(), 'mod_direct');
  assert.strictEqual(shared.loaded, 1, 'другая вкладка → без GET');
})();

// ── 5. index.html: блок, гейты, кнопка, next-action подсказка ───────────────
(function () {
  const html = fs.readFileSync(
    path.join(ROOT, 'web', 'index.html'), 'utf8');
  const blockAt = html.indexOf('youtube-proxy-health-block');
  assert(blockAt >= 0, 'блок youtube-proxy-health-block не найден');
  const gate = html.slice(Math.max(0, blockAt - 600), blockAt);
  assert(gate.includes("activeTab === 'mod_video_summary'"),
    'блок должен быть прибит к вкладке «Выжимка видео»');
  assert(gate.includes('isGlobalAdmin'),
    'блок должен быть только для global admin');
  const block = html.slice(blockAt, blockAt + 3500);
  assert(block.includes('data-yt-proxy-test'), 'кнопка пробы не найдена');
  assert(block.includes('Проверить подключение'), 'кнопка без подписи');
  assert(block.includes('Путь yt-dlp'), 'строка «Путь yt-dlp» не найдена');
  assert(block.includes('Путь transcript-api'),
    'строка «Путь transcript-api» не найдена');
  assert(block.includes('Авторизация прокси'), 'строка auth не найдена');
  assert(block.includes('Последняя проверка'), 'last_check не найден');
  assert(block.includes('проверьте логин/пароль прокси'),
    'next-action при 407 (§18I.6) не найден');
  assert(!block.includes('ytProxyHealth.proxy_url'),
    'секрет proxy_url не должен рендериться');
  assert(!block.includes('JSON.stringify'),
    'сырой дамп ответа в UI запрещён (Y5)');
})();

// ── 6. Шаблон блока реально компилируется Vue (runtime-compiler, прецедент
//      vue_mount_test) — защита от синтаксической поломки общей страницы ────
(function () {
  const fs2 = require('vm');
  const BUNDLE = path.join(ROOT, 'web', 'static', 'vendor',
                           'vue.global.prod.min.js');
  global.window = global;
  fs2.runInThisContext(fs.readFileSync(BUNDLE, 'utf8'), { filename: BUNDLE });
  assert.strictEqual(typeof Vue, 'object', 'Vue не определён после загрузки');
  const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const start = html.indexOf(
    '<template v-if="activeTab === \'mod_video_summary\' && isGlobalAdmin">');
  assert(start >= 0, 'обёртка шаблона блока не найдена');
  const endMarker = '<template v-for="grp in currentTabGroups"';
  const end = html.indexOf(endMarker, start);
  assert(end > start, 'конец блока не найден');
  let chunk = html.slice(start, end).trim();
  assert(chunk.endsWith('</template>'),
    'ожидается закрытие обёртки </template>');
  // Компилируем ВНУТРЕННОСТЬ обёртки (single root): срезаем внешний
  // <template ...> и его закрывающий тег.
  const inner = chunk.slice(chunk.indexOf('>') + 1,
                            chunk.lastIndexOf('</template>'));
  const render = Vue.compile('<div>' + inner + '</div>');
  assert.strictEqual(typeof render, 'function',
    'шаблон блока YouTube proxy health не компилируется');
})();

console.log('F9-PROXY-UI-OK');
