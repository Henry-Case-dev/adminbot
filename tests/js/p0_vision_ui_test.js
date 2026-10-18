'use strict';
/* P0 Vision — UI-контракт D10–D12 (§4 директивы владельца).

 * D10 (P0V-UI-NATIVE): `visionStateLine` — COMPUTED-строка: метод печатался
 *   в разметке как значение → `function () { [native code] }`. Проверяем:
 *   - в computed есть visionStateLine, в methods его НЕТ;
 *   - значение — строка (никогда не функция), при пустом state — '';
 *   - index.html выводит `{{ visionStateLine }}` внутри
 *     `[data-vision-effective-line]`, без вызова-метода в значении;
 *   - в исходнике нет мусора `[native code]` (кроме комментариев).
 * D11 (P0V-UI-REASONS): `visionProbeResult`/`visionVisibleReason` —
 *   человеческие причины; внутренние коды (vision_unavailable/http_401/…)
 *   НЕ попадают в текст; клиентский маппинг покрывает классы
 *   конфиг/авторизация/нет модели/модальность/плохое изображение/rate/
 *   timeout/5xx/пустой ответ.
 * D12 (P0V-UI-DISPLAY): `visionStateFacts` отдаёт факты фактического
 *   подключения (провайдер/модель/тип/результат/+detail) из state; в
 *   index.html есть блок `[data-vision-facts]` в обоих местах (LLM-вкладка
 *   и карточка модуля).
 *
 * Запуск: node tests/js/p0_vision_ui_test.js → P0V-UI-OK
 *
 * TEST-LIFECYCLE: CONTRACT owner=P0V-UI-NATIVE/REASONS/DISPLAY (§4 директивы;
 * D10–D12 recon P0 Vision).
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

const ROOT = path.join(__dirname, '..', '..');
require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const computed = captured.computed || {};
const methods = captured.methods || {};
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');

// ── D10: значение — computed-строка, метода нет ────────────────────────────
assert.strictEqual(typeof computed.visionStateLine, 'function',
  'D10: computed.visionStateLine отсутствует (метод печатался как значение)');
assert.strictEqual(methods.visionStateLine, undefined,
  'D10: visionStateLine не должен оставаться в methods (иначе Vue биндит метод)');

const noState = computed.visionStateLine.call({ visionState: null });
assert.strictEqual(noState, '', 'D10: без state линия — пустая строка');
assert.strictEqual(typeof noState, 'string', 'D10: значение — строка, не функция');
assert.ok(!/native code|function\s*\(/.test(noState),
  'D10: в значении нет техмусора function/native code');

const disabled = computed.visionStateLine.call({
  visionState: {
    effective_enabled: false,
    visible_reason: 'Провайдер временно недоступен (ошибка сервера)',
    queue: { queued: 3, running: 2 },
  },
});
assert.notStrictEqual(typeof disabled, 'function', 'D10: строка даже с state');
assert.ok(disabled.indexOf('Не активно:') === 0, 'D10: выключено — «Не активно: …»');
assert.ok(disabled.indexOf('Провайдер временно недоступен') > 0,
  'D10/D11: человеческая причина в линии');
assert.ok(disabled.indexOf('очередь 2/5') > 0, 'D10: очередь running/всего сохранена');

const ok = computed.visionStateLine.call({
  visionState: { effective_enabled: true, visible_reason: 'Распознавание работает' },
});
assert.strictEqual(ok, 'Распознавание работает', 'D10: работающее состояние');

// Разметка: значение-биндинг в единственном месте линии.
assert.ok(INDEX.indexOf('data-vision-effective-line') >= 0,
  'D10: якорь линии [data-vision-effective-line] сохранён');
assert.ok(INDEX.indexOf('{{ visionStateLine }}') >= 0,
  'D10: шаблон печатает {{ visionStateLine }} (computed-значение)');
assert.strictEqual(INDEX.indexOf('{{ visionStateLine() }}'), -1,
  'D10: поле НЕ вызывает метод в интерполяции');

// ── D11: человеческие причины, без внутренних кодов ───────────────────────
const RAW = /vision_unavailable|vision_rate_limited|vision_unsupported|vision_key_missing|api_type_unsupported|image_modality|image_rejected|empty_completion|bad_request|http_\d{3}/;
const cases = [
  [{ capability: 'access_error', reason: 'vision_unavailable', detail: 'http_401' },
    'Неверный ключ'],
  [{ capability: 'rate_limited', reason: 'vision_rate_limited', detail: 'http_429' },
    'Превышен лимит'],
  [{ capability: 'no_vision', reason: 'vision_unsupported',
     detail: 'image_modality_unsupported/http_400' }, 'Модель не принимает изображения'],
  [{ capability: 'no_vision', reason: 'main_model_no_vision' },
    'Основная модель не поддерживает изображения'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'vision_key_missing' },
    'отдельный ключ'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'api_type_unsupported' },
    'не поддерживается'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'model_not_found/http_404' },
    'не найдена'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'timeout' },
    'таймаут'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'http_5xx' },
    'временно недоступен'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'empty_completion' },
    'пустой ответ'],
  [{ capability: 'unavailable', reason: 'vision_unavailable',
     detail: 'image_rejected/http_400' }, 'изображение не принято'],
  [{ capability: 'unavailable', reason: 'vision_unavailable', detail: 'transport' },
    'Нет соединения'],
  [{ capability: '', reason: '' }, 'ещё не выполнялась'],
  [{ capability: 'disabled' }, 'выключено'],
];
cases.forEach(([probe, want]) => {
  const text = methods.visionVisibleReason.call({}, probe);
  assert.strictEqual(typeof text, 'string', 'D11: текст — строка');
  assert.ok(text.indexOf(want) >= 0,
    'D11: класс ' + JSON.stringify(probe) + ' → «' + want + '», получено «' + text + '»');
  assert.ok(!RAW.test(text),
    'D11: внутренний код не течёт наружу: «' + text + '»');
});
// Серверный visible_reason — источник истины (приоритет над маппингом).
assert.strictEqual(
  methods.visionVisibleReason.call({}, {
    visible_reason: 'Провайдер временно недоступен (ошибка сервера)',
    reason: 'vision_unavailable', detail: 'http_500',
  }), 'Провайдер временно недоступен (ошибка сервера)',
  'D11: visible_reason сервера приоритетен');
// Неизвестное — честная общая фраза, не код.
const unknown = methods.visionVisibleReason.call({}, {
  capability: 'unavailable', reason: 'vision_unavailable', detail: 'weird_class',
});
assert.ok(!RAW.test(unknown) && unknown.length > 10,
  'D11: неизвестный класс → общая человеческая фраза');

const okRes = methods.visionProbeResult.call(methods, {
  ok: true, model: 'google/gemma-4-31b-it:free', image_input: true,
});
assert.strictEqual(okRes.ok, true, 'D11: успех распознан');
assert.ok(okRes.text.indexOf('изображение поддерживается') >= 0,
  'D11: успешный текст сохранён');
const failRes = methods.visionProbeResult.call(methods, {
  ok: false, capability: 'access_error', reason: 'vision_unavailable',
  detail: 'http_401',
});
assert.strictEqual(failRes.ok, false, 'D11: отказ распознан');
assert.ok(!RAW.test(failRes.text), 'D11: отказ без кода: «' + failRes.text + '»');

// ── D12: факты фактического подключения ───────────────────────────────────
assert.strictEqual(typeof computed.visionStateFacts, 'function',
  'D12: computed.visionStateFacts отсутствует');
assert.deepStrictEqual(
  computed.visionStateFacts.call({ visionState: null }), [],
  'D12: без state — пустой список (блок скрыт)');

const stateCtx = {
  visionState: {
    effective_enabled: false,
    visible_reason: 'Провайдер временно недоступен (ошибка сервера)',
    provider: 'openrouter.ai', model: 'google/gemma-4-31b-it:free',
    api_type: 'openai_compatible', detail: 'http_5xx',
    checked_at: 1777000000.0,
  },
  visionApiTypeLabel: methods.visionApiTypeLabel,
};
const facts = computed.visionStateFacts.call(stateCtx);
const byKey = {};
facts.forEach((f) => { byKey[f.key] = f.value; });
assert.strictEqual(byKey.provider, 'openrouter.ai', 'D12: провайдер');
assert.strictEqual(byKey.model, 'google/gemma-4-31b-it:free', 'D12: модель');
assert.strictEqual(byKey.api_type, 'OpenAI-совместимый', 'D12: тип подключения');
assert.ok(byKey.result.indexOf('Провайдер временно недоступен') >= 0,
  'D12: результат проверки — человеческая причина');
assert.ok(byKey.detail === 'http_5xx', 'D12: R17-safe detail показан как «деталь»');
assert.strictEqual(methods.visionApiTypeLabel.call({}, 'openai_compatible'),
  'OpenAI-совместимый', 'D12: известный тип — человеческая подпись');
assert.strictEqual(methods.visionApiTypeLabel.call({}, 'anthropic'),
  'anthropic', 'D12: неизвестный тип — как есть (конфиг, не код ошибки)');
assert.strictEqual(methods.visionApiTypeLabel.call({}, ''), '—',
  'D12: пустой тип — «—»');

// Разметка: факты в обоих местах (LLM-вкладка и карточка модуля).
const factsMarkers = INDEX.split('data-vision-facts').length - 1;
assert.strictEqual(factsMarkers, 2,
  'D12: блок фактов в двух местах (LLM Провайдеры + карточка модуля)');
assert.ok(INDEX.indexOf("b.id === 'vision' && visionStateFacts.length") >= 0,
  'D12: LLM-вкладка рендерит факты по visionStateFacts');
assert.ok(INDEX.indexOf("c.id === 'vision' && visionStateFacts.length") >= 0,
  'D12: карточка модуля рендерит факты по visionStateFacts');

// ── D11 (тест-хук): тост пробы vision получает человеческий текст ─────────
const appSrc = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
assert.ok(appSrc.indexOf('this.visionProbeResult(vprobe)') >= 0,
  'D11: ветка /api/vision/test использует visionProbeResult (не сырой reason)');
assert.strictEqual(appSrc.indexOf("(vprobe.visible_reason || vprobe.reason)"), -1,
  'D11: старый вывод reason-кода удалён');

/* D12 fail-open: фоновая загрузка `/api/vision/state` не должна показывать
 * тост «Доступ запрещён» пользователю без права на ключ (серверный гейт
 * строже видимости вкладки). `silent403` подавляет тост ТОЛЬКО на этом пути;
 * явные действия (save/test) сохраняют прежнее поведение. Проверяем и то, что
 * служебный флаг не уходит в fetch-init. */
(async function () {
  const calls = [];
  global.fetch = async function (url, init) {
    calls.push({ url: url, init: init });
    return { status: 403, ok: false,
             json: async function () { return { detail: 'нет прав' }; } };
  };
  const toasts = [];
  const ctx = {
    authLocked: false,
    hasInitData: function () { return true; },
    activeChatId: null,
    toast: function (m, k) { toasts.push([m, k]); },
  };
  await methods.api.call(ctx, '/api/plain', {}).catch(function () {});
  assert.strictEqual(toasts.length, 1,
    '403 без silent403 — прежний тост «Доступ запрещён»');
  toasts.length = 0;
  await methods.api.call(ctx, '/api/vision/state',
    { silent403: true }).catch(function () {});
  assert.strictEqual(toasts.length, 0,
    '403 + silent403 — фоновая загрузка без тоста (D12 fail-open)');
  const lastInit = calls[calls.length - 1].init;
  assert.strictEqual('silent403' in lastInit, false,
    'silent403 не должен уходить в fetch-init');
  assert.ok(appSrc.indexOf(
    "this.api('/api/vision/state', { silent403: true })") >= 0,
    'D12: maybeLoadVisionState использует silent403');
  console.log('P0V-UI-OK');
})().catch(function (e) {
  console.error(e && e.stack || e);
  process.exit(1);
});
