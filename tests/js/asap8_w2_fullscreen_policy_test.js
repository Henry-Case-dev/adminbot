'use strict';
/* W2-FULLSCREEN (asap8-v6.3, U07 / REQ-U07-1..3) + FS-HOTFIX 18.10: юнит-матрица
 * web/static/fullscreen-policy.js — чистые функции + машина состояний на
 * mock Telegram.WebApp (без DOM/браузера; Playwright-прогоны — отдельный
 * tools/ui_asap8_w2_fullscreen_e2e.py).
 *
 * Покрытие (TEST-LIFECYCLE: CONTRACT owner=REQ-U07-1/REQ-U07-2):
 *   1. decideOffer: no_telegram_context; tdesktop — ОБЫЧНЫЙ клиент
 *      (FS-HOTFIX 18.10: honest-disable/`tdesktop_disabled_until_e2e` и
 *      float-слот удалены по директиве владельца; кнопка видима там, где API
 *      реально есть); request_fullscreen_unsupported; fullscreen_unavailable
 *      (кнопка не вводит в заблуждение, U07.3c);
 *   2. Машина состояний: ack через fullscreenChanged; ack без boolean —
 *      БЕЗ инверсии факта (U07.1c, legacy app.js:12818–12821 удалён);
 *      UNSUPPORTED — прежнее состояние + retry; ALREADY_FULLSCREEN —
 *      пересчёт из SDK, кнопка=выход, без ложного SUCCESS (U07.1d);
 *      pending-guard (повторный тап — один запрос); ack-таймаут задаётся,
 *      очищается, факт НЕ инвертирует; rotation/viewportChanged — без
 *      запросов; Launch Mode=Fullscreen — ВТОРОГО requestFullscreen нет,
 *      сразу рабочая кнопка выхода (U07.1e); tdesktop-launch — НИКАКИХ
 *      автоматических вызовов SDK (авто-exit удалён FS-HOTFIX), кнопка
 *      выхода доступна; обычный тап на tdesktop = реальный request;
 *   3. Структура: политика до app.js; legacy-инверсия удалена; нет
 *      window.moveTo/resizeTo (U07.0-NOHACKS); aria «На весь экран»/
 *      «Выйти из полноэкранного режима»; sum-формула нативной зоны шапки
 *      max(env, --tg-safe) + --tg-content (FS-HOTFIX: кнопка не заходит
 *      под нативные кнопки клиента); НЕТ стеклянной подложки ::before/
 *      data-fs-scheme/float-резерва; НЕТ UI-заглушек и диагностических
 *      блоков (SOUL-12-стрип удалён — dev-API политики вместо него);
 *   4. Dev-API (не UI): explain() не отдаёт «голых» кодов и НЕ выдумывает
 *      причину для работающего клиента; diagnostics() — факты
 *      воспроизведения (platform/SDK/launch params/методы/viewport/safe
 *      area/clickResult/initCount/trace/warnings) БЕЗ секретов; launchParams
 *      читаются из sessionStorage('__telegram__initParams') и hash URL
 *      (F1 разбора W7), tgWebAppData не выносится; негативы
 *      UNSUPPORTED/ALREADY_FULLSCREEN/pending-guard; двойная инициализация и
 *      ACK_TIMEOUT видны.
 *
 * Запуск: node tests/js/asap8_w2_fullscreen_policy_test.js → FS-POLICY-OK
 */
const path = require('path');
const assert = require('assert');
const fs = require('fs');

const REPO = path.resolve(__dirname, '..', '..');
const POLICY_PATH = path.join(REPO, 'web', 'static', 'fullscreen-policy.js');

/* ── Стабы окружения (минимальные; Node без DOM) ────────────────────────── */

function makeDocumentStub() {
  const html = {
    attrs: {},
    classes: new Set(),
    classList: {
      add(c) { html.classes.add(c); },
      remove(c) { html.classes.delete(c); },
      contains(c) { return html.classes.has(c); },
    },
    setAttribute(k, v) { html.attrs[k] = String(v); },
    removeAttribute(k) { delete html.attrs[k]; },
    getAttribute(k) { return html.attrs[k]; },
  };
  return { documentElement: html, html };
}

function mockWa(opts) {
  opts = opts || {};
  const handlers = {};
  const wa = {
    platform: opts.platform,
    version: opts.version || '8.0',
    viewportStableHeight: opts.stableHeight != null ? opts.stableHeight : 800,
    safeAreaInset: opts.safeAreaInset || { top: 0, bottom: 0, left: 0, right: 0 },
    contentSafeAreaInset: opts.contentSafeAreaInset ||
      { top: 0, bottom: 0, left: 0, right: 0 },
    __calls: [],
    requestFullscreen() { this.__calls.push('request'); },
    exitFullscreen() { this.__calls.push('exit'); },
    onEvent(ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); },
    offEvent(ev, fn) {
      const a = handlers[ev] || [];
      const i = a.indexOf(fn);
      if (i >= 0) a.splice(i, 1);
    },
    __emit(ev, payload) { (handlers[ev] || []).slice().forEach((f) => f(payload)); },
    __handlers: handlers,
  };
  if (opts.hasBoolean) wa.isFullscreen = !!opts.isFullscreen;
  return wa;
}

/* Свежий экземпляр политики на каждый сценарий (модуль — singleton).
 * storage/hash — управляемые фейки (F1: launch params живут в hash и
 * sessionStorage('__telegram__initParams'), в query — только fallback). */
function freshPolicy(wa, opts) {
  opts = opts || {};
  const doc = makeDocumentStub();
  const store = {};
  if (opts.initParams !== undefined) {
    store['__telegram__initParams'] = JSON.stringify(opts.initParams);
  }
  global.window = {
    Telegram: wa ? { WebApp: wa } : null,
    innerWidth: 390,
    innerHeight: 800,
    location: { search: opts.search || '', hash: opts.hash || '' },
    sessionStorage: {
      getItem(k) {
        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
      },
      setItem(k, v) { store[k] = String(v); },
    },
  };
  global.sessionStorage = global.window.sessionStorage;
  global.document = doc;
  delete require.cache[require.resolve(POLICY_PATH)];
  const policy = require(POLICY_PATH);
  return { policy, doc, wa };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  /* ── 1. decideOffer ───────────────────────────────────────────────────── */
  const P = freshPolicy(null).policy;
  const doff = P.decideOffer;
  let o = doff({ isTelegram: false });
  assert.strictEqual(o.slot, 'hidden');
  assert.strictEqual(o.reason, 'no_telegram_context');

  // FS-HOTFIX 18.10: tdesktop — обычный клиент с рабочим API. Кнопка видима,
  // причина не выдумывается (регресс: раньше slot=hidden + reason=
  // tdesktop_disabled_until_e2e — «диагностическая заглушка вместо кнопки»).
  o = doff({ isTelegram: true, hasRequestFullscreen: true,
             hasExitFullscreen: true, hasBooleanIsFullscreen: true,
             actualFullscreen: false });
  assert.strictEqual(o.canOfferFullscreen, true, 'рабочий API → вход предлагается');
  assert.strictEqual(o.slot, 'inline', 'слот inline (кнопка в row A)');
  assert.strictEqual(o.reason, '', 'нет выдуманной причины для рабочего клиента');

  // tdesktop в launch-fullscreen: сразу кнопка ВЫХОДА, без второго request.
  o = doff({ isTelegram: true, hasRequestFullscreen: true,
             hasExitFullscreen: true, hasBooleanIsFullscreen: true,
             actualFullscreen: true });
  assert.strictEqual(o.canOfferFullscreen, false, 'launch-fullscreen: второй request не предлагаем');
  assert.strictEqual(o.canOfferExit, true, 'кнопка выхода сразу');
  assert.strictEqual(o.slot, 'inline');

  o = doff({ isTelegram: true, hasRequestFullscreen: false,
             hasExitFullscreen: false, hasBooleanIsFullscreen: false,
             actualFullscreen: false });
  assert.strictEqual(o.slot, 'hidden');
  assert.strictEqual(o.reason, 'request_fullscreen_unsupported',
    'реально нет API → кнопка не вводит в заблуждение (U07.3c)');

  o = doff({ isTelegram: true, hasRequestFullscreen: false,
             hasExitFullscreen: false, hasBooleanIsFullscreen: true,
             actualFullscreen: true });
  assert.strictEqual(o.slot, 'hidden', ' fullscreen без exit и без request → hidden');
  assert.strictEqual(o.reason, 'fullscreen_unavailable');

  o = doff({ isTelegram: true, hasRequestFullscreen: false,
             hasExitFullscreen: true, hasBooleanIsFullscreen: true,
             actualFullscreen: true });
  assert.strictEqual(o.canOfferExit, true, 'exit-only состояние: кнопка-выход остаётся');
  assert.strictEqual(o.slot, 'inline');
  console.log('1. decideOffer-матрица OK (tdesktop — обычный клиент)');

  /* ── 2. Машина состояний ──────────────────────────────────────────────── */

  // 2.1 request → fullscreenChanged ack → exit.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    let s = policy.init();
    assert.strictEqual(s.slot, 'inline');
    assert.strictEqual(s.canOfferFullscreen, true);
    assert.strictEqual(policy.request(), true);
    assert.deepStrictEqual(wa.__calls, ['request']);
    assert.strictEqual(policy.state().requestPending, true);
    wa.isFullscreen = true;
    wa.__emit('fullscreenChanged');
    s = policy.state();
    assert.strictEqual(s.actualFullscreen, true);
    assert.strictEqual(s.requestPending, false);
    assert.strictEqual(s.lastError, null);
    assert.strictEqual(s.canOfferExit, true, 'после ack доступен exit');
    assert.strictEqual(policy.exit(), true);
    assert.deepStrictEqual(wa.__calls, ['request', 'exit']);
    wa.isFullscreen = false;
    wa.__emit('fullscreenChanged');
    s = policy.state();
    assert.strictEqual(s.actualFullscreen, false);
    assert.strictEqual(s.canOfferExit, false);
    policy.teardown();
  }
  console.log('2.1 request→ack→exit OK');

  // 2.2 SDK без boolean isFullscreen: ack событие НЕ инвертирует факт (U07.1c).
  {
    const wa = mockWa({ platform: 'android', hasBoolean: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    const s0 = policy.init();
    assert.strictEqual(s0.actualFullscreen, 'unknown', 'без boolean — unknown, не false-guess');
    assert.strictEqual(s0.launchFullscreen, null, 'launchFullscreen неизвестен, не угадан');
    assert.strictEqual(policy.request(), true);
    wa.__emit('fullscreenChanged');           // ack без boolean
    const s = policy.state();
    assert.strictEqual(s.actualFullscreen, 'unknown', 'инверсии нет');
    assert.strictEqual(s.requestPending, false, 'pending снят');
    assert.strictEqual(s.lastError.code, 'ACK_WITHOUT_BOOLEAN');
    policy.teardown();
  }
  console.log('2.2 no-inversion без SDK-boolean OK');

  // 2.3 UNSUPPORTED: прежнее состояние, retry разрешён.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    policy.init();
    assert.strictEqual(policy.request(), true);
    wa.__emit('fullscreenFailed', { error_code: 'UNSUPPORTED' });
    let s = policy.state();
    assert.strictEqual(s.requestPending, false);
    assert.strictEqual(s.actualFullscreen, false, 'состояние не изменилось');
    assert.strictEqual(s.lastError.code, 'UNSUPPORTED');
    assert.strictEqual(policy.request(), true, 'повторный тап возможен после fail');
    assert.strictEqual(wa.__calls.length, 2);
    policy.teardown();
  }
  console.log('2.3 UNSUPPORTED OK');

  // 2.4 ALREADY_FULLSCREEN: пересчёт из SDK, кнопка = выход, без ложного SUCCESS.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    policy.init();
    policy.request();
    wa.isFullscreen = true;                   // хост уже в fullscreen
    wa.__emit('fullscreenFailed', { error_code: 'ALREADY_FULLSCREEN' });
    const s = policy.state();
    assert.strictEqual(s.actualFullscreen, true, 'факт пересчитан из SDK');
    assert.strictEqual(s.canOfferFullscreen, false, 'второго request не будет');
    assert.strictEqual(s.canOfferExit, true, 'кнопка = выход');
    assert.strictEqual(s.lastError, null, 'без ложного сообщения об успехе/ошибке входа');
    policy.teardown();
  }
  console.log('2.4 ALREADY_FULLSCREEN OK');

  // 2.5 Launch Mode=Fullscreen (android): ВТОРОГО request нет, сразу exit-кнопка.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: true,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    const s = policy.init();
    assert.deepStrictEqual(wa.__calls, [], 'requestFullscreen на старте НЕ отправляется');
    assert.strictEqual(s.launchFullscreen, true);
    assert.strictEqual(s.canOfferFullscreen, false);
    assert.strictEqual(s.canOfferExit, true, 'сразу рабочая кнопка ВЫХОДА');
    assert.strictEqual(policy.request(), false, 'request() в launch-fullscreen отклонён');
    assert.deepStrictEqual(wa.__calls, [], 'и повторно не отправляется');
    assert.strictEqual(policy.exit(), true, 'выход доступен сразу');
    assert.deepStrictEqual(wa.__calls, ['exit']);
    policy.teardown();
  }
  console.log('2.5 Launch Mode=Fullscreen OK');

  // 2.6 FS-HOTFIX: tdesktop launch-fullscreen — НИКАКИХ авто-вызовов SDK;
  //     кнопка выхода доступна; обычный тап на tdesktop = реальный request.
  {
    const wa = mockWa({ platform: 'tdesktop', hasBoolean: true, isFullscreen: true });
    const { policy } = freshPolicy(wa);
    policy.init();
    assert.deepStrictEqual(wa.__calls, [],
      'авто-exit удалён: политика не трогает SDK за владельца');
    policy.init();                             // re-init из `ready` — тоже без вызовов
    assert.deepStrictEqual(wa.__calls, []);
    let s = policy.state();
    assert.strictEqual(s.slot, 'inline', 'кнопка видима (не hidden)');
    assert.strictEqual(s.reason, '', 'нет причины-заглушки');
    assert.strictEqual(s.canOfferExit, true);
    assert.strictEqual(policy.exit(), true, 'выход доступен по кнопке');
    assert.deepStrictEqual(wa.__calls, ['exit']);
    policy.teardown();
  }
  {
    const wa = mockWa({ platform: 'tdesktop', hasBoolean: true, isFullscreen: false });
    const { policy } = freshPolicy(wa);
    const s = policy.init();
    assert.strictEqual(s.canOfferFullscreen, true, 'Windows Desktop: вход предлагается');
    assert.strictEqual(policy.request(), true, 'тап = реальный requestFullscreen');
    assert.deepStrictEqual(wa.__calls, ['request']);
    wa.isFullscreen = true;
    wa.__emit('fullscreenChanged');
    assert.strictEqual(policy.state().canOfferExit, true, 'после ack — кнопка выхода');
    policy.teardown();
  }
  console.log('2.6 tdesktop: рабочий переключатель без авто-выхода OK');

  // 2.7 Pending-guard: повторный тап при pending — ровно один запрос.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    policy.setAckTimeoutMs(5000);
    policy.init();
    assert.strictEqual(policy.request(), true);
    assert.strictEqual(policy.request(), false, 'повторный тап игнорируется');
    assert.strictEqual(policy.exit(), false);
    assert.deepStrictEqual(wa.__calls, ['request']);
    policy.teardown();
  }
  console.log('2.7 pending-guard OK');

  // 2.8 Ack-таймаут: задаётся, очищается, факт НЕ инвертирует.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    policy.setAckTimeoutMs(40);
    policy.init();
    assert.strictEqual(policy.request(), true);
    assert.strictEqual(policy.state().requestPending, true);
    await sleep(120);
    const s = policy.state();
    assert.strictEqual(s.requestPending, false, 'таймаут снял pending');
    assert.strictEqual(s.lastError.code, 'ACK_TIMEOUT');
    assert.strictEqual(s.actualFullscreen, false, 'факт не инвертирован');
    policy.teardown();
  }
  console.log('2.8 ack-таймаут OK');

  // 2.9 Rotation/viewportChanged: без запросов, pending не трогается.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    policy.setAckTimeoutMs(5000);
    policy.init();
    policy.request();
    wa.contentSafeAreaInset = { top: 0, bottom: 0, left: 0, right: 0 };
    wa.__emit('viewportChanged');
    let s = policy.state();
    assert.deepStrictEqual(wa.__calls, ['request'], 'rotation не создаёт запросов');
    assert.strictEqual(s.slot, 'inline', 'слот остаётся inline (row A — стабильное место)');
    assert.strictEqual(s.requestPending, true, 'pending сохранён');
    wa.__emit('contentSafeAreaChanged');
    s = policy.state();
    assert.strictEqual(s.slot, 'inline');
    policy.teardown();
  }
  console.log('2.9 rotation без конфликтов OK');

  // 2.10 Вне Telegram: кнопка не вводит в заблуждение (hidden).
  {
    const { policy } = freshPolicy(null);
    const s = policy.init();
    assert.strictEqual(s.slot, 'hidden');
    assert.strictEqual(s.reason, 'no_telegram_context');
    assert.strictEqual(policy.request(), false);
    assert.strictEqual(policy.exit(), false);
    policy.teardown();
  }
  console.log('2.10 stand-alone браузер OK');

  // 2.11 subscribe/unsubscribe.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false });
    const { policy } = freshPolicy(wa);
    let n = 0;
    const unsub = policy.subscribe(() => { n += 1; });
    policy.init();
    assert.ok(n >= 1, 'подписчик получил начальный notify');
    unsub();
    const before = n;
    policy.request();
    assert.strictEqual(n, before, 'после unsubscribe уведомлений нет');
    policy.teardown();
  }
  console.log('2.11 subscribe OK');

  /* ── 3. Структура (U07.0-NOHACKS / контракт §1.3.4/§4.1) ──────────────── */
  const appJs = fs.readFileSync(path.join(REPO, 'web', 'app.js'), 'utf8');
  const indexHtml = fs.readFileSync(path.join(REPO, 'web', 'index.html'), 'utf8');
  const appCss = fs.readFileSync(path.join(REPO, 'web', 'static', 'app.css'), 'utf8');
  const policySrc = fs.readFileSync(POLICY_PATH, 'utf8');

  assert.ok(fs.existsSync(POLICY_PATH), 'fullscreen-policy.js существует');
  assert.ok(policySrc.includes('window.__FullscreenPolicy = api'),
    'публичное API window.__FullscreenPolicy');
  assert.ok(indexHtml.indexOf('/static/fullscreen-policy.js') !== -1 &&
            indexHtml.indexOf('/static/fullscreen-policy.js') < indexHtml.indexOf('/web/app.js'),
    'политика загружается ДО app.js (§1.3.4)');
  assert.ok(indexHtml.indexOf('/web/app.js') < indexHtml.indexOf('/static/telegram-init.js'),
    'telegram-init.js остаётся последним');
  assert.ok(!/this\.isFullscreen\s*=\s*!this\.isFullscreen/.test(appJs),
    'legacy-инверсия app.js:12818–12821 УДАЛЕНА (U07.1c)');
  assert.ok(!/window\.(moveTo|resizeTo)\s*\(/.test(appJs) &&
            !/window\.(moveTo|resizeTo)\s*\(/.test(policySrc),
    'нет window.moveTo/resizeTo-хаков (U07.0-NOHACKS; Canvas ctx.moveTo легитимен)');
  assert.ok(!/wa\.expand\(\)/.test(appJs.slice(appJs.indexOf('toggleFullscreen'))),
    'expand() больше не выдаётся за fullscreen-фолбэк (U07.1a)');
  assert.ok(indexHtml.includes("'На весь экран'") &&
            indexHtml.includes("'Выйти из полноэкранного режима'"),
    'aria по ACK-состоянию (U07.2d)');
  assert.ok(indexHtml.includes("fsSlot !== 'hidden'"),
    'слот решает политика; hidden → v-if (без мёртвого контрола)');
  assert.ok(!indexHtml.includes("'fs-slot-' + fsSlot"),
    'мёртвый CSS-хук fs-slot-* удалён (review-fs N3)');
  assert.ok(indexHtml.includes(':aria-pressed="fsAriaPressed"'),
    'aria-pressed — computed по факту');
  assert.ok(policySrc.includes("de.setAttribute('data-fs-reason'"),
    'data-fs-reason пишет только политика (§2.3)');
  // FS-HOTFIX 18.10: sum-формула нативной зоны (кнопка не заходит под
  // native-кнопки клиента: contentSafeAreaInset отсчитывается от системной
  // safe area — рекомендуется суммировать; tma.js#695).
  assert.ok(/max\(env\(safe-area-inset-top, 0px\),\s*var\(--tg-safe-area-inset-top, 0px\)\)\s*\+\s*var\(--tg-content-safe-area-inset-top, 0px\)/.test(appCss),
    'шапка обходит нативную зону целиком (sum-формула)');
  assert.ok(!appCss.includes('fs-slot-float') && !appCss.includes('data-fs-scheme'),
    'float-слот/схема темы удалены (слот только inline)');
  assert.ok(!/\.header-fs-btn::before/.test(appCss) &&
            !/\.header-fs-btn[^{,]*\{[^}]*backdrop-filter/.test(appCss) &&
            !/\.header-fs-btn[^{,]*\{[^}]*\bbackground\s*:/.test(appCss),
    'материал ⛶ только из .lg-mini-lens (U08.4d): правила header-fs-btn не ' +
    'красят фон и не добавляют своё стекло (геометрия — за fullscreen-лейном)');
  assert.ok(/\.header-fs-btn\s*\{[^}]*min-width:\s*44px/.test(appCss) &&
            /\.header-fs-btn\s*\{[^}]*min-height:\s*44px/.test(appCss),
    'кнопка ⛶ остаётся hit-целью ≥44×44');
  // telegram-init.js не изменён ни одним лейном (проверка наличия ключевых маркеров)
  const tgInit = fs.readFileSync(path.join(REPO, 'web', 'static', 'telegram-init.js'), 'utf8');
  assert.ok(tgInit.includes("--tg-content-safe-area-inset-top") &&
            tgInit.includes('--app-usable-height'),
    'telegram-init.js остаётся единственным writer --tg-*');
  console.log('3. структурные проверки OK');

  /* ── 4. Dev-API (не UI): объяснение причины и диагностика ────────────────
   * TEST-LIFECYCLE: CONTRACT owner=SOUL-12.1/12.3/12.4 (dev-канал);
   * REGRESSION owner=FS-HOTFIX (владелец 18.10: «никаких поясняющих заглушек
   * вместо рабочей кнопки» — UI-блоки удалены, диагностика живёт в политике). */
  {
    // 4.1 explain(): объяснение только для реальных причин; работающий
    // клиент НЕ получает выдуманного кода (tdesktop — без причины).
    const noMethods = (over) => {
      const w = mockWa(Object.assign({ platform: 'android', hasBoolean: true,
                                       isFullscreen: false }, over || {}));
      delete w.requestFullscreen;
      return w;
    };
    const cases = [
      { name: 'no_telegram_context', wa: null, caps: { isTelegram: false },
        code: 'no_telegram_context' },
      { name: 'request_fullscreen_unsupported', wa: noMethods(),
        caps: { isTelegram: true, hasRequestFullscreen: false,
                hasExitFullscreen: true, actualFullscreen: false },
        code: 'request_fullscreen_unsupported' },
      { name: 'fullscreen_unavailable',
        wa: (() => { const w = noMethods({ isFullscreen: true });
                     delete w.exitFullscreen; return w; })(),
        caps: { isTelegram: true, hasRequestFullscreen: false,
                hasExitFullscreen: false, actualFullscreen: true },
        code: 'fullscreen_unavailable' },
    ];
    for (const cs of cases) {
      const { policy } = freshPolicy(cs.wa);
      const offer = policy.decideOffer(Object.assign({ actualFullscreen: 'unknown' }, cs.caps));
      assert.strictEqual(offer.reason, cs.code, `${cs.name}: код причины`);
      policy.init();
      const ex = policy.explain();
      assert.strictEqual(ex.code, cs.code, `${cs.name}: explain().code`);
      assert.strictEqual(policy.state().reason, cs.code,
        `${cs.name}: живое состояние несёт тот же код`);
      assert.ok(ex.text && ex.text.length > 20,
        `${cs.name}: причина БЕЗ объяснения запрещена (SOUL-12.1)`);
      assert.ok(ex.nextStep && ex.nextStep.length > 10,
        `${cs.name}: нет конкретного следующего шага (SOUL-12.4)`);
      assert.ok(policy.state().reasonText === ex.text &&
                policy.state().nextStep === ex.nextStep,
        `${cs.name}: state() зеркалит объяснение`);
      policy.teardown();
    }
    // tdesktop: причина НЕ выдумывается, кнопка работает (FS-HOTFIX).
    const tdesk = freshPolicy(mockWa({ platform: 'tdesktop', hasBoolean: true,
                                       isFullscreen: false })).policy;
    const sTd = tdesk.init();
    assert.strictEqual(sTd.reason, '', 'tdesktop: причины нет — нет и заглушки');
    assert.strictEqual(sTd.canOfferFullscreen, true, 'tdesktop: кнопка рабочая');
    const tdEx = tdesk.explain();
    assert.strictEqual(tdEx.code, '', 'tdesktop: explain() не выдумывает код');
    assert.strictEqual(tdEx.text, '');
    assert.ok(!/BotFather/.test(tdEx.text + tdEx.nextStep),
      'tdesktop: инструкция BotFather из UI-канала удалена (FS-HOTFIX)');
    tdesk.teardown();
    const ok = freshPolicy(mockWa({ platform: 'android', hasBoolean: true,
                                    isFullscreen: false,
                                    contentSafeAreaInset: { top: 36, bottom: 0,
                                                            left: 0, right: 0 } })).policy;
    ok.init();
    const okEx = ok.explain();
    assert.strictEqual(okEx.code, '', 'offerable: код пуст');
    assert.strictEqual(ok.state().reasonText, '', 'offerable: reasonText пуст');
    ok.teardown();
    console.log('4.1 explain() без «голых» кодов и без выдуманных причин OK');

    // 4.2 diagnostics(): обязательные факты воспроизведения (SOUL-12.3) + F1.
    const SECRET = 'SECRET-INITDATA-SENTINEL-42';
    const waSec = mockWa({ platform: 'android', hasBoolean: true,
                           isFullscreen: false,
                           contentSafeAreaInset: { top: 36, bottom: 0,
                                                   left: 0, right: 0 } });
    waSec.initData = SECRET;
    waSec.initDataUnsafe = { user: { id: 1 } };
    const { policy: pDiag } = freshPolicy(waSec, {
      initParams: { tgWebAppPlatform: 'android', tgWebAppVersion: '8.0',
                    tgWebAppStartParam: 'deep1',
                    tgWebAppData: 'user=%7B%22id%22%3A1%7D&hash=SUPERSECRET' } });
    pDiag.init();
    const d = pDiag.diagnostics();
    for (const key of ['platform', 'sdkVersion', 'launchParams',
                       'isFullscreenSupported', 'actualFullscreen',
                       'launchFullscreen', 'hasRequestFullscreen',
                       'hasExitFullscreen', 'stableHeight', 'safeAreaInset',
                       'contentSafeAreaInset', 'initCount', 'clickResult',
                       'hostBehaviour', 'trace', 'warnings']) {
      assert.ok(Object.prototype.hasOwnProperty.call(d, key),
        `diagnostics(): поле ${key} обязательно`);
    }
    assert.strictEqual(d.platform, 'android', 'diagnostics().platform');
    assert.strictEqual(d.isFullscreenSupported, true,
      'diagnostics(): факт наличия SDK-boolean isFullscreen');
    assert.strictEqual(d.hasInitData, true,
      'diagnostics(): только булев факт наличия initData');
    const blob = JSON.stringify(d);
    for (const marker of ['initData', 'api_key', 'apikey', 'token', 'Bearer', 'SUPERSECRET']) {
      assert.ok(blob.indexOf(marker) < 0, `секрет-маркер «${marker}» в diagnostics()`);
    }
    assert.ok(blob.indexOf(SECRET) < 0, 'значение initData не утекает (R17)');
    assert.strictEqual(d.launchParams.tgWebAppPlatform, 'android',
      'F1: launch params читаются из sessionStorage официального SDK');
    assert.strictEqual(d.launchParams.tgWebAppVersion, '8.0');
    assert.strictEqual(d.launchParams.tgWebAppStartParam, 'deep1');
    assert.strictEqual(d.launchParams.tgWebAppData, undefined,
      'allowlist: tgWebAppData не выносится');
    assert.ok(d.trace.some((t) => t.code === 'init'),
      'trace фиксирует init (SOUL-12.5)');
    assert.strictEqual(d.initCount, 1, 'initCount=1 после одного init');
    assert.strictEqual(d.clickResult, 'never',
      'clickResult=never до первого касания ⛶');
    pDiag.teardown();

    // F1 (hash): без sessionStorage параметры берутся из hash URL.
    const { policy: pHash } = freshPolicy(
      mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false }),
      { hash: '#tgWebAppPlatform=tdesktop&tgWebAppVersion=8.0&tgWebAppStartParam=deep1&tgWebAppData=user%3Dx' });
    pHash.init();
    const dHash = pHash.diagnostics();
    assert.strictEqual(dHash.launchParams.tgWebAppPlatform, 'tdesktop',
      'F1: hash-транспорт launch-параметров читается');
    assert.strictEqual(dHash.launchParams.tgWebAppStartParam, 'deep1');
    assert.strictEqual(dHash.launchParams.tgWebAppData, undefined,
      'F1: из hash берутся только allowlist-ключи');
    pHash.teardown();
    console.log('4.2 diagnostics() — факты, launch params (F1), без секретов OK');

    // 4.3 clickResult + warnings: request → exit; негативы.
    const waTap = mockWa({ platform: 'android', hasBoolean: true,
                           isFullscreen: false,
                           contentSafeAreaInset: { top: 36, bottom: 0,
                                                   left: 0, right: 0 } });
    const { policy: pTap } = freshPolicy(waTap);
    pTap.init();
    assert.strictEqual(pTap.request(), true, '4.3: request отправлен');
    assert.strictEqual(pTap.diagnostics().clickResult, 'request_sent');
    waTap.isFullscreen = true;
    waTap.__emit('fullscreenChanged');
    assert.strictEqual(pTap.exit(), true, '4.3: exit отправлен');
    assert.strictEqual(pTap.diagnostics().clickResult, 'exit_sent');
    assert.deepStrictEqual(waTap.__calls, ['request', 'exit'],
      '4.3: ровно один request и один exit');
    pTap.teardown();

    // 4.3a UNSUPPORTED (негатив): состояние прежнее, код виден в warning.
    const waUn = mockWa({ platform: 'android', hasBoolean: true,
                          isFullscreen: false,
                          contentSafeAreaInset: { top: 36, bottom: 0,
                                                  left: 0, right: 0 } });
    const { policy: pUn } = freshPolicy(waUn);
    pUn.init();
    pUn.request();
    waUn.__emit('fullscreenFailed', { error_code: 'UNSUPPORTED' });
    assert.strictEqual(pUn.state().actualFullscreen, false,
      '4.3a UNSUPPORTED: факт не инвертирован');
    assert.strictEqual(pUn.state().lastError.code, 'UNSUPPORTED');
    const dUn = pUn.diagnostics();
    assert.strictEqual(dUn.clickResult, 'request_sent',
      '4.3a: clickResult отражает фактическое действие');
    assert.ok(dUn.warnings.some((w) => w.code === 'UNSUPPORTED'),
      '4.3a: warning UNSUPPORTED зафиксирован');
    assert.ok(dUn.trace.some((t) => t.code === 'fullscreenFailed'),
      '4.3a: trace фиксирует fullscreenFailed');
    pUn.teardown();

    // 4.3b ALREADY_FULLSCREEN (негатив): второго request нет.
    const waAl = mockWa({ platform: 'android', hasBoolean: true,
                          isFullscreen: true,
                          contentSafeAreaInset: { top: 36, bottom: 0,
                                                  left: 0, right: 0 } });
    const { policy: pAl } = freshPolicy(waAl);
    pAl.init();
    assert.strictEqual(pAl.request(), false, '4.3b: request отклонён');
    assert.deepStrictEqual(waAl.__calls, [],
      '4.3b ALREADY/launch-fullscreen: второго requestFullscreen НЕТ');
    assert.strictEqual(pAl.diagnostics().clickResult, 'already_fullscreen',
      '4.3b: clickResult=already_fullscreen');
    pAl.teardown();

    // 4.3c tdesktop (FS-HOTFIX): кнопка рабочая, вызов реальный.
    const waTd = mockWa({ platform: 'tdesktop', hasBoolean: true,
                          isFullscreen: false });
    const { policy: pTd } = freshPolicy(waTd);
    pTd.init();
    assert.strictEqual(pTd.request(), true, '4.3c tdesktop: request отправлен');
    assert.deepStrictEqual(waTd.__calls, ['request'],
      '4.3c tdesktop: реальный вызов SDK, а не заглушка');
    assert.strictEqual(pTd.diagnostics().clickResult, 'request_sent');
    assert.strictEqual(pTd.diagnostics().reasonText, '',
      '4.3c tdesktop: причины-заглушки нет');
    pTd.teardown();

    // 4.3d pending-guard (негатив): второй тап — нулевой запрос.
    const waPg = mockWa({ platform: 'android', hasBoolean: true,
                          isFullscreen: false,
                          contentSafeAreaInset: { top: 36, bottom: 0,
                                                  left: 0, right: 0 } });
    const { policy: pPg } = freshPolicy(waPg);
    pPg.init();
    pPg.request();
    assert.strictEqual(pPg.request(), false, '4.3d: повторный тап отклонён');
    assert.deepStrictEqual(waPg.__calls, ['request'],
      '4.3d: ровно один запрос при двойном тапе');
    assert.strictEqual(pPg.diagnostics().clickResult, 'pending_guard');
    pPg.teardown();
    console.log('4.3 clickResult/негативы (UNSUPPORTED/ALREADY/tdesktop/pending) OK');

    // 4.4 initCount/DOUBLE_INIT + ACK_TIMEOUT warning (SOUL-12.5).
    const waDt = mockWa({ platform: 'android', hasBoolean: true,
                          isFullscreen: false,
                          contentSafeAreaInset: { top: 36, bottom: 0,
                                                  left: 0, right: 0 } });
    const { policy: pDt } = freshPolicy(waDt);
    pDt.init();
    pDt.init();
    const dDt = pDt.diagnostics();
    assert.strictEqual(dDt.initCount, 2, '4.4: двойная инициализация видна');
    assert.ok(dDt.warnings.some((w) => w.code === 'DOUBLE_INIT'),
      '4.4: DOUBLE_INIT в warnings');
    pDt.setAckTimeoutMs(120);
    pDt.request();
    await sleep(260);
    const dTo = pDt.diagnostics();
    assert.ok(dTo.warnings.some((w) => w.code === 'ACK_TIMEOUT'),
      '4.4: ACK_TIMEOUT виден в warnings');
    assert.ok(dTo.trace.some((t) => t.code === 'ackTimeout'),
      '4.4: ackTimeout в trace');
    assert.strictEqual(dTo.requestPending, false, '4.4: pending снят');
    pDt.teardown();
    console.log('4.4 trace/warnings (init, DOUBLE_INIT, ACK_TIMEOUT) OK');

    // 4.5 FS-HOTFIX: UI-заглушек и диагностических блоков в интерфейсе НЕТ.
    assert.ok(!indexHtml.includes('data-fs-diagnostics'),
      'index.html: диагностический стрип удалён из UI');
    assert.ok(!indexHtml.includes('Полноэкранный режим недоступен'),
      'index.html: поясняющей заглушки вместо кнопки нет');
    assert.ok(!indexHtml.includes('BotFather'),
      'index.html: инструкции BotFather в UI нет');
    assert.ok(!/platform:\s*\{\{/.test(indexHtml) && !indexHtml.includes('Launch params:'),
      'index.html: технических строк platform/SDK/viewport нет');
    assert.ok(!appJs.includes('fsReasonText') && !appJs.includes('fsNextStep') &&
              !appJs.includes('fsDiag'),
      'app.js: зеркало диагностических полей удалено из UI-кода');
    assert.ok(!policySrc.includes('tdesktop_disabled_until_e2e') &&
              !policySrc.includes('_softExitTimer') &&
              !policySrc.includes('launchExitIgnored') &&
              !policySrc.includes('TDESKTOP_LAUNCH_FULLSCREEN'),
      'policy: honest-disable/авто-exit удалены (директива владельца)');
    assert.ok(typeof P.diagnostics === 'function' && typeof P.explain === 'function',
      'dev-API диагностики сохранён в объекте политики (F1 починен там же)');
    console.log('4.5 UI-заглушек нет, dev-API сохранён OK');

    // 4.6 FS-HOTFIX FOLLOW-UP §8: admin-диагностика геометрии — off by
    // default, admin-гейт, копирование одним действием, без секретов.
    const diagIdx = indexHtml.indexOf('data-fs-geom-diag-entry');
    assert.ok(diagIdx >= 0 && indexHtml.includes('data-fs-geom-diag') &&
              indexHtml.includes('data-fs-geom-diag-copy') &&
              indexHtml.includes('data-fs-safe-overlay'),
      'index.html: админ-диагностика (вход/панель/копирование/оверлей) есть');
    assert.ok(indexHtml.slice(Math.max(0, diagIdx - 400), diagIdx + 200)
                .includes('isGlobalAdminEffective'),
      'вход диагностики — admin-гейт (isGlobalAdminEffective)');
    assert.ok(indexHtml.includes('v-if="fsGeomDiagOpen"') &&
              indexHtml.includes('v-if="fsGeomOverlay"'),
      'панель/оверлей закрыты по умолчанию (v-if на состоянии)');
    assert.ok(/buildFsGeomText: function/.test(appJs) &&
              /copyFsGeomDiag: function/.test(appJs),
      'app.js: снимок собирается точечно и копируется одним действием');
    const geomBody = appJs.slice(appJs.indexOf('buildFsGeomText: function'),
                                 appJs.indexOf('openFsGeomDiag: function'));
    assert.ok(geomBody.length > 200 && geomBody.indexOf('launchParams') < 0 &&
              geomBody.indexOf('initData') < 0 && geomBody.indexOf('activeChatId') < 0,
      'снимок для UI не выносит launchParams/initData/ID чатов');
    assert.ok(/\.fs-geom-diag-root \{ position: fixed; inset: 0; z-index: 57; \}/.test(appCss) &&
              /\.fs-safe-overlay \{[^}]*pointer-events: none/.test(appCss),
      'CSS: панель поверх меню, оверлей границ не перехватывает тапы');
    console.log('4.6 admin-диагностика геометрии (§8) OK');

    console.log('dev-API политики (объяснение + диагностика) OK');
  }

  console.log('FS-POLICY-OK');
}

main().catch((e) => { console.error(e); process.exit(1); });
