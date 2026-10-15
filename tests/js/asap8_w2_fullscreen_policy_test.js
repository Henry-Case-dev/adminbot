'use strict';
/* W2-FULLSCREEN (asap8-v6.3, U07 / REQ-U07-1..3): юнит-матрица
 * web/static/fullscreen-policy.js — чистые функции + машина состояний на
 * mock Telegram.WebApp (без DOM/браузера; Playwright-прогоны — отдельный
 * tools/ui_asap8_w2_fullscreen_e2e.py).
 *
 * Покрытие (TEST-LIFECYCLE: CONTRACT owner=REQ-U07-1/REQ-U07-2):
 *   1. slotFromGeometry: tdesktop→hidden; float только android/ios/weba +
 *      hasRequestFullscreen + csa.top>=36 + SDK-boolean; csa=0/ошибка
 *      измерений/unknown/web → inline (контракт §2.1);
 *   2. decideOffer: no_telegram_context; tdesktop honest-disable; exit-only
 *      в launch-fullscreen; request_fullscreen_unsupported; hidden без
 *      любой возможности (кнопка не вводит в заблуждение, U07.3c);
 *   3. Машина состояний: ack через fullscreenChanged; ack без boolean —
 *      БЕЗ инверсии факта (U07.1c, legacy app.js:12818–12821 удалён);
 *      UNSUPPORTED — прежнее состояние + retry; ALREADY_FULLSCREEN —
 *      пересчёт из SDK, кнопка=выход, без ложного SUCCESS (U07.1d);
 *      pending-guard (повторный тап — один запрос); ack-таймаут задаётся,
 *      очищается, факт НЕ инвертирует; rotation/viewportChanged — без
 *      запросов; Launch Mode=Fullscreen — ВТОРОГО requestFullscreen нет,
 *      сразу рабочая кнопка выхода (U07.1e); tdesktop-launch — ОДИН мягкий
 *      exitFullscreen, игнор хоста → документированное ограничение;
 *   4. Структура: политика до app.js; legacy-инверсия удалена; нет
 *      window.moveTo/resizeTo (U07.0-NOHACKS); aria «На весь экран»/
 *      «Выйти из полноэкранного режима»; float-геометрия из max(env,--tg-*).
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

/* Свежий экземпляр политики на каждый сценарий (модуль — singleton). */
function freshPolicy(wa) {
  const doc = makeDocumentStub();
  global.window = {
    Telegram: wa ? { WebApp: wa } : null,
    innerWidth: 390,
    innerHeight: 800,
  };
  global.document = doc;
  delete require.cache[require.resolve(POLICY_PATH)];
  const policy = require(POLICY_PATH);
  return { policy, doc, wa };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  /* ── 1. slotFromGeometry (чистая матрица §2.1) ────────────────────────── */
  const P = freshPolicy(null).policy;
  const sg = P.slotFromGeometry;
  assert.strictEqual(sg('tdesktop', 36, true), 'hidden', 'tdesktop → hidden');
  assert.strictEqual(sg('tdesktop', 0, false), 'hidden', 'tdesktop → hidden (любые)');
  assert.strictEqual(sg('android', 36, true), 'float', 'android float');
  assert.strictEqual(sg('ios', 50, true), 'float', 'ios float');
  assert.strictEqual(sg('weba', 50, true, true), 'float', 'weba float (с boolean)');
  assert.strictEqual(sg('weba', 50, true, false), 'inline',
    'weba без SDK-boolean → inline (честный ack невозможен, §2.1)');
  assert.strictEqual(sg('android', 35, true), 'inline', 'csa.top<36 → inline');
  assert.strictEqual(sg('android', 0, true), 'inline', 'csa.top=0 → inline');
  assert.strictEqual(sg('android', NaN, true), 'inline', 'ошибка измерений → inline');
  assert.strictEqual(sg('android', '36', true), 'inline', 'не-число csa → inline');
  assert.strictEqual(sg('web', 60, true), 'inline', 'web → inline');
  assert.strictEqual(sg('macos', 60, true), 'inline', 'macos → inline');
  assert.strictEqual(sg('unknown', 60, true), 'inline', 'unknown → inline');
  assert.strictEqual(sg('android', 60, false), 'inline', 'без requestFullscreen → inline');
  console.log('1. slotFromGeometry-матрица OK');

  /* ── 2. decideOffer ───────────────────────────────────────────────────── */
  const doff = P.decideOffer;
  let o = doff('android', { isTelegram: false });
  assert.strictEqual(o.slot, 'hidden');
  assert.strictEqual(o.reason, 'no_telegram_context');

  o = doff('tdesktop', { isTelegram: true, hasRequestFullscreen: true,
                         hasExitFullscreen: true, hasBooleanIsFullscreen: true,
                         actualFullscreen: false, csaTop: 36 });
  assert.strictEqual(o.slot, 'hidden');
  assert.strictEqual(o.reason, 'tdesktop_disabled_until_e2e');
  assert.strictEqual(o.canOfferFullscreen, false, 'tdesktop: не предлагаем до e2e');
  assert.strictEqual(o.canOfferExit, false);

  o = doff('android', { isTelegram: true, hasRequestFullscreen: true,
                        hasExitFullscreen: true, hasBooleanIsFullscreen: true,
                        actualFullscreen: false, csaTop: 36 });
  assert.strictEqual(o.canOfferFullscreen, true);
  assert.strictEqual(o.slot, 'float');

  o = doff('android', { isTelegram: true, hasRequestFullscreen: false,
                        hasExitFullscreen: false, hasBooleanIsFullscreen: false,
                        actualFullscreen: false, csaTop: 36 });
  assert.strictEqual(o.slot, 'hidden');
  assert.strictEqual(o.reason, 'request_fullscreen_unsupported');

  o = doff('android', { isTelegram: true, hasRequestFullscreen: true,
                        hasExitFullscreen: true, hasBooleanIsFullscreen: true,
                        actualFullscreen: true, csaTop: 36 });
  assert.strictEqual(o.canOfferFullscreen, false, 'launch-fullscreen: второй request не предлагаем');
  assert.strictEqual(o.canOfferExit, true, 'кнопка выхода сразу');
  assert.strictEqual(o.slot, 'float');

  o = doff('weba', { isTelegram: true, hasRequestFullscreen: false,
                     hasExitFullscreen: false, hasBooleanIsFullscreen: true,
                     actualFullscreen: true, csaTop: 0 });
  assert.strictEqual(o.slot, 'hidden', ' fullscreen без exit и без request → hidden');
  assert.strictEqual(o.reason, 'fullscreen_unavailable');
  console.log('2. decideOffer-матрица OK');

  /* ── 3. Машина состояний ──────────────────────────────────────────────── */

  // 3.1 request → fullscreenChanged ack → exit.
  {
    const wa = mockWa({ platform: 'android', hasBoolean: true, isFullscreen: false,
                        contentSafeAreaInset: { top: 36, bottom: 0, left: 0, right: 0 } });
    const { policy } = freshPolicy(wa);
    let s = policy.init();
    assert.strictEqual(s.slot, 'float');
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
  console.log('3.1 request→ack→exit OK');

  // 3.2 SDK без boolean isFullscreen: ack событие НЕ инвертирует факт (U07.1c).
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
  console.log('3.2 no-inversion без SDK-boolean OK');

  // 3.3 UNSUPPORTED: прежнее состояние, retry разрешён.
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
  console.log('3.3 UNSUPPORTED OK');

  // 3.4 ALREADY_FULLSCREEN: пересчёт из SDK, кнопка = выход, без ложного SUCCESS.
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
  console.log('3.4 ALREADY_FULLSCREEN OK');

  // 3.5 Launch Mode=Fullscreen (android): ВТОРОГО request нет, сразу exit-кнопка.
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
    assert.strictEqual(s.slot, 'float');
    policy.teardown();
  }
  console.log('3.5 Launch Mode=Fullscreen OK');

  // 3.6 tdesktop launch-fullscreen: ОДИН мягкий exit; повторный init — не второй.
  {
    const wa = mockWa({ platform: 'tdesktop', hasBoolean: true, isFullscreen: true });
    const { policy } = freshPolicy(wa);
    policy.init();
    assert.deepStrictEqual(wa.__calls, ['exit'], 'один мягкий exitFullscreen');
    policy.init();                             // re-init из `ready` — без второго
    assert.deepStrictEqual(wa.__calls, ['exit']);
    const s = policy.state();
    assert.strictEqual(s.slot, 'hidden', 'кнопка скрыта (U07.1a)');
    assert.strictEqual(s.reason, 'tdesktop_disabled_until_e2e');
    assert.strictEqual(policy.request(), false);
    assert.deepStrictEqual(wa.__calls, ['exit'], 'request из UI невозможен');
    policy.teardown();
  }
  console.log('3.6 tdesktop launch-fullscreen soft-exit OK');

  // 3.7 tdesktop: хост проигнорировал мягкий exit → документированное ограничение.
  {
    const wa = mockWa({ platform: 'tdesktop', hasBoolean: true, isFullscreen: true });
    const { policy } = freshPolicy(wa);
    policy.setAckTimeoutMs(40);
    policy.init();
    await sleep(120);
    const s = policy.state();
    assert.strictEqual(policy.launchExitIgnored(), true, 'ограничение зафиксировано');
    assert.strictEqual(s.requestPending, false);
    assert.strictEqual(s.lastError.code, 'TDESKTOP_LAUNCH_FULLSCREEN_EXIT_IGNORED');
    assert.strictEqual(s.actualFullscreen, true, 'факт не инвертирован таймаутом');
    policy.teardown();
  }
  console.log('3.7 tdesktop exit-ignored ограничение OK');

  // 3.8 Pending-guard: повторный тап при pending — ровно один запрос.
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
  console.log('3.8 pending-guard OK');

  // 3.9 Ack-таймаут: задаётся, очищается, факт НЕ инвертирует.
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
  console.log('3.9 ack-таймаут OK');

  // 3.10 Rotation/viewportChanged: без запросов, pending не трогается.
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
    assert.strictEqual(s.slot, 'inline', 'csa.top=0 → пересчёт в inline');
    assert.strictEqual(s.requestPending, true, 'pending сохранён');
    wa.__emit('contentSafeAreaChanged');
    s = policy.state();
    assert.strictEqual(s.slot, 'inline');
    policy.teardown();
  }
  console.log('3.10 rotation без конфликтов OK');

  // 3.11 Вне Telegram: кнопка не вводит в заблуждение (hidden).
  {
    const { policy } = freshPolicy(null);
    const s = policy.init();
    assert.strictEqual(s.slot, 'hidden');
    assert.strictEqual(s.reason, 'no_telegram_context');
    assert.strictEqual(policy.request(), false);
    assert.strictEqual(policy.exit(), false);
    policy.teardown();
  }
  console.log('3.11 stand-alone браузер OK');

  // 3.12 subscribe/unsubscribe.
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
  console.log('3.12 subscribe OK');

  /* ── 4. Структура (U07.0-NOHACKS / контракт §1.3.4/§2.1/§4.1) ─────────── */
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
  assert.ok(indexHtml.includes("fsSlot !== 'hidden'") && indexHtml.includes("'fs-slot-' + fsSlot"),
    'слот решает политика; hidden → v-if (без мёртвого контрола)');
  assert.ok(indexHtml.includes(':aria-pressed="fsAriaPressed"'),
    'aria-pressed — computed по факту');
  assert.ok(appCss.includes('html.fs-slot-float .header-fs-btn') &&
            appCss.includes('max(env(safe-area-inset-right, 0px)'),
            'float-геометрия max(env, --tg-content-safe-area-*, --tg-safe-area-*)');
  assert.ok(appCss.includes('html.fs-slot-float header.header-sticky'),
    'float: резерв row A в своей секции (§2.1)');
  assert.ok(policySrc.includes("de.setAttribute('data-fs-reason'"),
    'data-fs-reason пишет только политика (§2.3)');
  // telegram-init.js не изменён ни одним лейном (проверка наличия ключевых маркеров)
  const tgInit = fs.readFileSync(path.join(REPO, 'web', 'static', 'telegram-init.js'), 'utf8');
  assert.ok(tgInit.includes("--tg-content-safe-area-inset-top") &&
            tgInit.includes('--app-usable-height'),
    'telegram-init.js остаётся единственным writer --tg-*');
  console.log('4. структурные проверки OK');

  console.log('FS-POLICY-OK');
}

main().catch((e) => { console.error(e); process.exit(1); });
