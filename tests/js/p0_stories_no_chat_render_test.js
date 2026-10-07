'use strict';
/* P0 prod-incident "miniapp blank" (07.10.2026) - регресс-тест render-краша.
 *
 * Root cause: GET /api/stories/summary без выбранного чата отвечает
 * `state: "no_chat", counters: null, progress: null` (web/api/stories.py).
 * Шаблон витрины «Истории чата» (web/index.html, mca-12) читал
 * `storiesSummary.counters.pending_verification` без null-guard'а counters -
 * TypeError на render-фазе (Vue 3 prod) валил всё дерево: владелец видел
 * только polygon-фон, UI не монтировался.
 *
 * Тест извлекает РЕАЛЬНЫЙ фрагмент шаблона из web/index.html, компилирует его
 * self-hosted полным билдом Vue (vendor, 3.5.42 - тот же, что в проде) и
 * исполняет render с продовой формой payload'а. До фикса - TypeError
 * "Cannot read properties of null (reading 'pending_verification')".
 *
 * Запуск: node tests/js/p0_stories_no_chat_render_test.js
 * Успех:  P0-STORIES-NO-CHAT-RENDER-OK
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const BUNDLE = path.join(ROOT, 'web', 'static', 'vendor',
                         'vue.global.prod.min.js');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

global.window = global;
vm.runInThisContext(fs.readFileSync(BUNDLE, 'utf8'), { filename: BUNDLE });
assert.strictEqual(typeof Vue, 'object', 'Vue full build должен загрузиться');
assert.strictEqual(Vue.version, '3.5.42', 'пин версии Vue (self-host)');

// 1) РЕАЛЬНЫЙ байтовый фрагмент из index.html: badge «Ожидает проверки».
const m = INDEX.match(
  /<span v-if="storiesSummary[^"]*pending_verification[\s\S]*?<\/span>/);
assert.ok(m, 'фрагмент badge pending_verification найден в index.html');
const tpl = m[0];

// Продовая форма ответа (web/api/stories.py:110, no_chat):
const NO_CHAT = { state: 'no_chat', chat_id: null, counters: null,
                  progress: null, window_hours: 24, manage_enabled: true,
                  generated_at: null, enabled: true };
// Легитимная форма (state=ok, counters/progress - словари):
const OK = { state: 'ok', chat_id: -1001234567890,
             counters: { total: 3, new_window: 1, extended_window: 1,
                         contradictions_window: 0, pending_verification: 2,
                         excluded_from_retrieval: 0 },
             progress: { episodes_build: { state: 'success', last_ts: 1,
                                           last_outcome: 'success' },
                         episodes_backfill: { state: 'paused', active: false } },
             window_hours: 24, manage_enabled: true, generated_at: 1,
             enabled: true };

function renderOnce(ctx) {
  // decodeEntities - инъекция: браузерный декодер full-build требует DOM,
  // во фрагменте витрины сущностей нет.
  const render = Vue.compile(tpl, { decodeEntities: (s) => s });
  const vnode = render({ storiesSummary: ctx });
  return JSON.stringify(vnode || '');
}

// 2) RED-условие (root cause): render при counters=null не должен бросать.
let threw = null;
try {
  renderOnce(NO_CHAT);
} catch (e) {
  threw = e;
}
assert.strictEqual(threw, null,
  'render при counters=null не должен падать (прод no_chat), было: '
  + (threw && threw.message));

// 3) При no_chat badge «ожидают проверки» скрыт.
const renderedNoChat = renderOnce(NO_CHAT);
assert.ok(!/ожидают проверки/i.test(renderedNoChat),
          'badge скрыт при no_chat');

// 4) Легитимный путь (state=ok) не сломан: badge рендерится с числом.
const renderedOk = renderOnce(OK);
assert.ok(/ожидают проверки/i.test(renderedOk),
          'badge присутствует при state=ok');

// 5) Защита от регрессии класса: выражение обязано guard'ить counters
//    (пин на фиксированное выражение в файле).
assert.ok(/storiesSummary\s*&&\s*storiesSummary\.counters\s*&&\s*storiesSummary\.counters\.pending_verification/.test(tpl),
          'v-if обязан содержать null-guard counters');

console.log('P0-STORIES-NO-CHAT-RENDER-OK');
