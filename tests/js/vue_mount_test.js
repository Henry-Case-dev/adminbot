'use strict';
/* F4 10.16 (T-1659, ревью-итерация 1) — ПОВЕДЕНЧЕСКИЙ гейт миниаппа.
 *
 * Критический дефект итерации 1: CSP `script-src 'self'` без `'unsafe-eval'`
 * запрещал `Function()`, который исполняет рантайм-компилятор FULL-сборки
 * Vue → приложение не монтировалось (EvalError). Статические маркеры этого
 * не ловили. Тест реально:
 *   1) загружает self-host бандл `web/static/vendor/vue.global.prod.min.js`
 *      в global-контекст (как браузер);
 *   2) КОМПИЛИРУЕТ шаблон (in-DOM путь `compileToFunction` → `Function`);
 *   3) симулирует CSP без `'unsafe-eval'` (подменяет `Function` на throwing
 *      stub) и убеждается, что компиляция падает — т.е. без `'unsafe-eval'`
 *      мини-апп действительно НЕ взлетит;
 *   4) проверяет отсутствие inline-скриптов и внешних ресурсов в index.html.
 *
 * Запуск: node tests/js/vue_mount_test.js  (печатает VUE-MOUNT-OK)
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const BUNDLE = path.join(ROOT, 'web', 'static', 'vendor',
                         'vue.global.prod.min.js');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// Браузероподобный global: бандл piggyback'ится на window/document.
global.window = global;
vm.runInThisContext(fs.readFileSync(BUNDLE, 'utf8'), { filename: BUNDLE });
assert.strictEqual(typeof Vue, 'object', 'Vue не определён после загрузки');
assert.strictEqual(Vue.version, '3.5.42', 'неожиданная версия Vue: ' + Vue.version);
assert.strictEqual(typeof Vue.compile, 'function',
                   'full-сборка обязана экспортировать runtime-compiler');

// 1. Компиляция in-DOM шаблона (представитель: v-for/v-if/@click/:class/{{ }}).
const tpl = '<div :class="{ on: x }"><span v-for="n in list" :key="n">' +
            '{{ n }}</span><em v-if="x" @click="x = !x">tap</em></div>';
const render = Vue.compile(tpl);
assert.strictEqual(typeof render, 'function', 'compile не вернул render-функцию');

// 2. CSP-симуляция: без 'unsafe-eval' Function() запрещён → компиляция падает.
const RealFunction = global.Function;
global.Function = function () {
  throw new EvalError('EvalError: CSP blocks Function/eval (unsafe-eval)');
};
let cspBlocked = false;
try {
  Vue.compile('<b>{{ cspProbe }}</b>');
} catch (err) {
  cspBlocked = err instanceof EvalError;
} finally {
  global.Function = RealFunction;
}
assert.ok(cspBlocked, "рантайм-компилятор не использует Function() — " +
                      "гипотеза о необходимости 'unsafe-eval' не подтверждена");
// After restore compiler works again.
assert.strictEqual(typeof Vue.compile('<i>{{ ok }}</i>'), 'function');

// 3. Приложение действительно опирается на рантайм-компиляцию (in-DOM).
assert.ok(/app\.mount\(\s*['"]#app['"]\s*\)/.test(APP_JS),
          "не найден app.mount('#app') — маркер in-DOM шаблона");
assert.ok(APP_JS.indexOf("template: '#kv-editor-tpl'") !== -1 &&
          APP_JS.indexOf("template: '#list-editor-tpl'") !== -1,
          'не найдены строковые template:-селекторы (in-DOM)');

// 4. Нет inline-ИСПОЛНЯЕМЫХ скриптов и внешних ресурсов. Данные `<script
//    type="text/x-template">` (шаблоны Vue) CSP не исполняет и не блокирует.
const scripts = INDEX.match(/<script\b[^>]*>/gi) || [];
assert.ok(scripts.length > 0, 'в index.html нет <script> вообще');
for (const tag of scripts) {
  if (/\ssrc\s*=/.test(tag)) continue;
  assert.ok(/type\s*=\s*["']text\/x-template["']/i.test(tag),
            'inline исполняемый <script> без src: ' + tag);
}
assert.strictEqual(INDEX.indexOf('<style'), -1, 'найден inline <style>');
assert.strictEqual(INDEX.indexOf('http://'), -1, 'внешний http:// ресурс');
assert.strictEqual(INDEX.indexOf('https://'), -1, 'внешний https:// ресурс');
for (const host of ['unpkg.com', 'cdn.jsdelivr.net', 'cdn.tailwindcss.com',
                    'telegram.org/js', 'fonts.gstatic.com']) {
  assert.strictEqual(INDEX.indexOf(host), -1, 'внешний CDN: ' + host);
}

console.log('VUE-MOUNT-OK');
