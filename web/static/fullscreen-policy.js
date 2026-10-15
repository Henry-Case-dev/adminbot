/* ═══ W2-FULLSCREEN (asap8-v6.3, U07 / REQ-U07-1..2) ═══
 * FullscreenPolicy — единая политика «platform × client capability ×
 * launch mode» для кнопки ⛶ и TMA-fullscreen. Plain IIFE по образцу
 * glass.js/telegram-init.js: CSP-safe, БЕЗ Vue, БЕЗ inline-кода, БЕЗ
 * записи CSS-переменных (--tg-* пишет ТОЛЬКО telegram-init.js, §2.3).
 *
 * Источник истины состояния — ТОЛЬКО факты SDK:
 *   • actualFullscreen — из Telegram.WebApp.isFullscreen (boolean) или
 *     'unknown'; локальный флаг НЕ инвертируется (U07.1c, бывш. legacy
 *     app.js:12818–12821 удалён);
 *   • launchFullscreen — фактическое начальное состояние (не CSS-guess);
 *   • fullscreenChanged подтверждает, fullscreenFailed снимает pending и
 *     отдаёт ошибку (UNSUPPORTED — прежнее состояние; ALREADY_FULLSCREEN —
 *     пересчёт из SDK, кнопка = выход, без ложного SUCCESS — U07.1d);
 *   • ack-таймаут задаётся и очищается внутри политики; повторный тап /
 *     rotation не создают параллельных запросов;
 *   • Launch Mode=Fullscreen (BotFather): повторный requestFullscreen()
 *     НЕ отправляется; на мобильном сразу рабочая кнопка выхода; на
 *     Windows (tdesktop) — ОДИН мягкий exitFullscreen() при поддержке
 *     API, если хост игнорирует — документированное ограничение
 *     (последнее средство владельцу: ручная правка Launch Mode в
 *     BotFather — САМ BotFather программно не меняется, U07.1e);
 *   • window.moveTo/resizeTo/WinAPI/«CSS 100vw = монитор» — запрещены
 *     (U07.0): политика управляет только TMA API и своим layout.
 *
 * Слоты кнопки (§2.1 w2-contract, один DOM-узел .header-fs-btn):
 *   inline — в потоке row A (нет Telegram; web/weba без SDK-boolean;
 *            unknown; csa.top === 0; ошибка измерений);
 *   float  — position:fixed у native-зоны: platform ∈ {android, ios,
 *            weba} И hasRequestFullscreen И csaTop >= 36 И SDK отдаёт
 *            boolean isFullscreen (без него честный ACK невозможен);
 *   hidden — tdesktop (до platform-specific e2e, U07.1a; expand() — НЕ
 *            fallback полноценного fullscreen) и клиенты без обоих
 *            методов (кнопка не должна вводить в заблуждение).
 * Писатель html-классов fs-slot-float / fs-hidden и data-fs-reason —
 * ТОЛЬКО этот модуль (контракт §2.3).
 *
 * Публичное API: window.__FullscreenPolicy
 *   state() · request() · exit() · subscribe(fn) · init(opts) ·
 *   teardown() · setAckTimeoutMs(ms) · slotFromGeometry(...) ·
 *   decideOffer(...)
 * Чистые функции доступны без DOM (окно-guard) — Node-юнит-тесты:
 * tests/js/asap8_w2_fullscreen_policy_test.js. */
(function () {
  'use strict';

  var PLATFORMS = ['android', 'ios', 'macos', 'tdesktop', 'weba', 'web', 'unknown'];
  var FLOAT_PLATFORMS = { android: true, ios: true, weba: true };
  var FLOAT_MIN_CSA_TOP = 36;              // px (§2.1 w2-contract)
  var DEFAULT_ACK_TIMEOUT_MS = 4000;       // таймаут ожидания ack хоста

  /* ── Чистые функции (без DOM/window — unit-матрица) ─────────────────── */

  function normalizePlatform(raw) {
    return PLATFORMS.indexOf(raw) >= 0 ? raw : 'unknown';
  }

  /* slotFromGeometry(platform, csaTop, hasReq[, hasBoolean]) → 'inline'|'float'|'hidden'
   * Геометрическое решение слота (без учёта capability-причин — их добавляет
   * decideOffer). 4-й аргумент: SDK отдаёт boolean isFullscreen; без него
   * float запрещён (честный ACK невозможен) — §2.1 «inline обязателен при
   * web/weba без SDK-boolean». Вызов с тремя аргументами сохраняет
   * контрактное поведение (hasBoolean трактуется как true). */
  function slotFromGeometry(platform, csaTop, hasReq, hasBoolean) {
    if (platform === 'tdesktop') return 'hidden';       // U07.1a
    var booleanOk = (hasBoolean !== undefined) ? hasBoolean !== false : true;
    if (hasReq && booleanOk && FLOAT_PLATFORMS[platform] &&
        typeof csaTop === 'number' && csaTop >= FLOAT_MIN_CSA_TOP) {
      return 'float';
    }
    return 'inline';
  }

  /* decideOffer(platform, caps) → {canOfferFullscreen, canOfferExit, reason, slot}
   * caps: {isTelegram, hasRequestFullscreen, hasExitFullscreen,
   *        hasBooleanIsFullscreen, actualFullscreen, csaTop}
   * reason-коды: no_telegram_context | tdesktop_disabled_until_e2e |
   * request_fullscreen_unsupported | fullscreen_unavailable | ''. */
  function decideOffer(platform, caps) {
    caps = caps || {};
    var actual = caps.actualFullscreen;
    var out = { canOfferFullscreen: false, canOfferExit: false, reason: '', slot: 'inline' };
    if (!caps.isTelegram) {
      out.reason = 'no_telegram_context';
      out.slot = 'hidden';
      return out;
    }
    if (platform === 'tdesktop') {
      out.reason = 'tdesktop_disabled_until_e2e';
      out.slot = 'hidden';
      return out;
    }
    var already = actual === true;
    out.canOfferExit = !!caps.hasExitFullscreen && already;
    if (already) {
      // U07.1e/U07.1d: в fullscreen повторный request не предлагаем —
      // кнопка = выход.
      out.canOfferFullscreen = false;
    } else if (!caps.hasRequestFullscreen) {
      out.reason = 'request_fullscreen_unsupported';
    } else {
      out.canOfferFullscreen = true;
    }
    out.slot = slotFromGeometry(platform, caps.csaTop, caps.hasRequestFullscreen,
                                caps.hasBooleanIsFullscreen);
    if (!out.canOfferFullscreen && !out.canOfferExit) {
      // Кнопка не должна вводить в заблуждение (U07.3c) — скрываем.
      out.slot = 'hidden';
      if (!out.reason) out.reason = 'fullscreen_unavailable';
    }
    return out;
  }

  /* ── Состояние (plain object; источник истины — события SDK) ────────── */

  var _state = {
    telegramPlatform: 'unknown',
    sdkVersion: '',
    hasRequestFullscreen: false,
    hasExitFullscreen: false,
    actualFullscreen: 'unknown',   // true | false | 'unknown' (U07.1)
    launchFullscreen: null,        // boolean | null (неизвестно ≠ false)
    requestPending: false,
    lastError: null,               // {code, message} | null
    canOfferFullscreen: false,
    canOfferExit: false,
    reason: '',
    slot: 'inline',
    viewport: {
      width: 0, height: 0, stableHeight: 0,
      safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
      contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 }
    }
  };

  var _subscribers = [];
  var _ackTimer = null;
  var _softExitTimer = null;       // отдельный ack-таймер launch-exit (tdesktop)
  var _ackTimeoutMs = DEFAULT_ACK_TIMEOUT_MS;
  var _sdkSubscribed = false;
  var _softExitTried = false;      // один мягкий exit на tdesktop-launch
  var _launchExitIgnored = false;  // хост проигнорировал мягкий exit

  function _wa() {
    try {
      return (typeof window !== 'undefined' && window.Telegram &&
              window.Telegram.WebApp) || null;
    } catch (e) { return null; }
  }

  function _notify() {
    var snapshot = state();
    for (var i = 0; i < _subscribers.length; i++) {
      try { _subscribers[i](snapshot); } catch (e) { /* слушатель не роняет политику */ }
    }
    _applyDomMirror();
  }

  function subscribe(fn) {
    if (typeof fn !== 'function') return null;
    _subscribers.push(fn);
    return function unsubscribe() {
      var i = _subscribers.indexOf(fn);
      if (i >= 0) _subscribers.splice(i, 1);
    };
  }

  function state() {
    return {
      telegramPlatform: _state.telegramPlatform,
      sdkVersion: _state.sdkVersion,
      hasRequestFullscreen: _state.hasRequestFullscreen,
      hasExitFullscreen: _state.hasExitFullscreen,
      actualFullscreen: _state.actualFullscreen,
      launchFullscreen: _state.launchFullscreen,
      requestPending: _state.requestPending,
      lastError: _state.lastError,
      canOfferFullscreen: _state.canOfferFullscreen,
      canOfferExit: _state.canOfferExit,
      reason: _state.reason,
      slot: _state.slot,
      viewport: {
        width: _state.viewport.width,
        height: _state.viewport.height,
        stableHeight: _state.viewport.stableHeight,
        safeAreaInset: _state.viewport.safeAreaInset,
        contentSafeAreaInset: _state.viewport.contentSafeAreaInset
      }
    };
  }

  /* ── Чтение фактов SDK (только чтение; переменные не пишет) ─────────── */

  function _readViewport(wa) {
    var v = _state.viewport;
    try {
      v.width = (typeof window !== 'undefined' && window.innerWidth) || 0;
      v.height = (typeof window !== 'undefined' && window.innerHeight) || 0;
    } catch (e) { /* guard */ }
    if (!wa) return;
    if (typeof wa.viewportStableHeight === 'number') v.stableHeight = wa.viewportStableHeight;
    var sa = wa.safeAreaInset, csa = wa.contentSafeAreaInset, k;
    if (sa) {
      for (k in v.safeAreaInset) {
        if (Object.prototype.hasOwnProperty.call(v.safeAreaInset, k)) {
          v.safeAreaInset[k] = (typeof sa[k] === 'number' && sa[k] > 0) ? sa[k] : 0;
        }
      }
    }
    if (csa) {
      for (k in v.contentSafeAreaInset) {
        if (Object.prototype.hasOwnProperty.call(v.contentSafeAreaInset, k)) {
          v.contentSafeAreaInset[k] = (typeof csa[k] === 'number' && csa[k] > 0) ? csa[k] : 0;
        }
      }
    }
  }

  function _capabilities(wa) {
    return {
      isTelegram: !!wa,
      hasRequestFullscreen: !!(wa && (typeof wa.requestFullscreen === 'function' ||
                                      typeof wa.requestFullScreen === 'function')),
      hasExitFullscreen: !!(wa && typeof wa.exitFullscreen === 'function'),
      hasBooleanIsFullscreen: !!(wa && typeof wa.isFullscreen === 'boolean'),
      actualFullscreen: _state.actualFullscreen,
      csaTop: _state.viewport.contentSafeAreaInset.top
    };
  }

  function _recompute() {
    var wa = _wa();
    _state.telegramPlatform = wa ? normalizePlatform(wa.platform) : 'unknown';
    _state.sdkVersion = wa && wa.version ? String(wa.version) : '';
    // Факт — ТОЛЬКО из SDK; «unknown» не инвертируется и не угадывается.
    if (wa && typeof wa.isFullscreen === 'boolean') {
      _state.actualFullscreen = wa.isFullscreen;
    }
    _readViewport(wa);   // сначала факты insets/viewport, потом решение слота
    var caps = _capabilities(wa);
    _state.hasRequestFullscreen = caps.hasRequestFullscreen;
    _state.hasExitFullscreen = caps.hasExitFullscreen;
    var offer = decideOffer(_state.telegramPlatform, caps);
    _state.canOfferFullscreen = offer.canOfferFullscreen;
    _state.canOfferExit = offer.canOfferExit;
    _state.reason = offer.reason;
    _state.slot = offer.slot;
  }

  /* ── DOM-зеркало слота (html.fs-* / data-fs-reason; единственный writer) */

  function _applyDomMirror() {
    if (typeof document === 'undefined' || !document.documentElement) return;
    var de = document.documentElement;
    if (!de.classList) return;
    if (_state.slot === 'float') {
      de.classList.add('fs-slot-float');
      de.classList.remove('fs-hidden');
    } else if (_state.slot === 'hidden') {
      de.classList.add('fs-hidden');
      de.classList.remove('fs-slot-float');
    } else {
      de.classList.remove('fs-slot-float');
      de.classList.remove('fs-hidden');
    }
    try {
      if (_state.slot === 'hidden' && _state.reason) {
        de.setAttribute('data-fs-reason', _state.reason);
      } else {
        de.removeAttribute('data-fs-reason');
      }
    } catch (e) { /* guard */ }
  }

  /* ── Ack-таймер (задаётся/очищается; факт при таймауте НЕ инвертируется) */

  function setAckTimeoutMs(ms) {
    _ackTimeoutMs = (typeof ms === 'number' && ms > 0) ? ms : DEFAULT_ACK_TIMEOUT_MS;
  }

  function _armAckTimer() {
    _clearAckTimer();
    _ackTimer = setTimeout(function () {
      _ackTimer = null;
      if (_state.requestPending) {
        _state.requestPending = false;
        _state.lastError = {
          code: 'ACK_TIMEOUT',
          message: 'Клиент не подтвердил переход в/из полноэкранного режима'
        };
        // фактическое состояние НЕ меняем (не инвертируем)
        _recompute();
        _notify();
      }
    }, _ackTimeoutMs);
  }

  function _clearAckTimer() {
    if (_ackTimer !== null) {
      clearTimeout(_ackTimer);
      _ackTimer = null;
    }
  }

  /* Ack-таймер мягкого launch-exit (tdesktop U07.1e): не путается с
   * пользовательским requestPending — это диагностика ограничения хоста. */
  function _armSoftExitTimer() {
    _clearSoftExitTimer();
    _softExitTimer = setTimeout(function () {
      _softExitTimer = null;
      _recompute();
      if (_state.actualFullscreen === true &&
          _state.telegramPlatform === 'tdesktop') {
        // Хост Windows проигнорировал мягкий exit — документируем
        // ограничение (ручная инструкция владельцу — в отчёте лейна).
        _launchExitIgnored = true;
        _state.lastError = {
          code: 'TDESKTOP_LAUNCH_FULLSCREEN_EXIT_IGNORED',
          message: 'Telegram Desktop не вышел из стартового fullscreen — ' +
                   'измените Launch Mode в BotFather вручную'
        };
        _notify();
      }
    }, _ackTimeoutMs);
  }

  function _clearSoftExitTimer() {
    if (_softExitTimer !== null) {
      clearTimeout(_softExitTimer);
      _softExitTimer = null;
    }
  }

  /* ── События SDK ─────────────────────────────────────────────────────── */

  function _onFullscreenChanged() {
    var wasPending = _state.requestPending;
    _clearAckTimer();
    _clearSoftExitTimer();     // любой ack закрывает и ожидание launch-exit
    _state.requestPending = false;
    var wa = _wa();
    if (wa && typeof wa.isFullscreen === 'boolean') {
      _state.actualFullscreen = wa.isFullscreen;
    } else if (wasPending) {
      // Ack без boolean: честно фиксируем, состояние НЕ угадываем (U07.1c).
      _state.lastError = {
        code: 'ACK_WITHOUT_BOOLEAN',
        message: 'Клиент подтвердил событие без фактического isFullscreen'
      };
    }
    _recompute();
    _notify();
  }

  function _onFullscreenFailed(payload) {
    _clearAckTimer();
    _clearSoftExitTimer();
    _state.requestPending = false;
    var code = (payload && (payload.error_code || payload.error || payload.errorCode)) || 'UNKNOWN';
    if (code === 'ALREADY_FULLSCREEN') {
      // U07.1d: пересчитать факт из SDK; кнопка = выход; без ложного SUCCESS.
      _recompute();
      if (_state.actualFullscreen !== true) {
        _state.lastError = {
          code: 'ALREADY_FULLSCREEN',
          message: 'Уже в полноэкранном режиме (факт SDK не подтверждён)'
        };
      }
    } else if (code === 'UNSUPPORTED') {
      // U07.1d: прежнее состояние без изменений.
      _recompute();
      _state.lastError = {
        code: 'UNSUPPORTED',
        message: 'Полноэкранный режим не поддержан этим клиентом'
      };
    } else {
      _recompute();
      _state.lastError = { code: String(code), message: 'Ошибка полноэкранного режима: ' + code };
    }
    _notify();
  }

  function _onViewportChanged() {
    // Rotation/resize/safe-area: пересчёт слота/viewport. НИКАКИХ запросов и
    // никаких записей в CSS-переменные (их пишет telegram-init.js);
    // requestPending не трогается (ack не подменяется rotation'ом).
    _recompute();
    _notify();
  }

  function _subscribeSdk(wa) {
    if (_sdkSubscribed || !wa || typeof wa.onEvent !== 'function') return;
    wa.onEvent('fullscreenChanged', _onFullscreenChanged);
    if (typeof wa.onEvent === 'function') {
      wa.onEvent('fullscreenFailed', _onFullscreenFailed);
      wa.onEvent('viewportChanged', _onViewportChanged);
      wa.onEvent('safeAreaChanged', _onViewportChanged);
      wa.onEvent('contentSafeAreaChanged', _onViewportChanged);
    }
    _sdkSubscribed = true;
  }

  /* ── Публичные действия: request/exit — ЕДИНСТВЕННЫЕ пути к TMA API ──── */

  function request() {
    var wa = _wa();
    if (!wa) return false;
    if (_state.actualFullscreen === true) {
      // U07.1e/U07.1d: Launch-fullscreen / уже в fullscreen — ВТОРОЙ
      // requestFullscreen не отправляем; честный статус + кнопка выхода.
      _recompute();
      if (_state.actualFullscreen === true) {
        _state.lastError = { code: 'ALREADY_FULLSCREEN', message: 'Уже в полноэкранном режиме' };
        _notify();
        return false;
      }
    }
    if (_state.requestPending) return false;          // повторный тап — игнор
    if (!_state.canOfferFullscreen || !_state.hasRequestFullscreen) {
      _state.lastError = {
        code: 'UNSUPPORTED',
        message: 'Полноэкранный режим недоступен' + (_state.reason ? ' (' + _state.reason + ')' : '')
      };
      _notify();
      return false;
    }
    _state.requestPending = true;
    _armAckTimer();
    _notify();
    try {
      var p = (typeof wa.requestFullscreen === 'function')
        ? wa.requestFullscreen()
        : wa.requestFullScreen();
      if (p && typeof p.catch === 'function') {
        p.catch(function (err) {
          _onFullscreenFailed({ error_code: 'REQUEST_REJECTED',
                                message: err && err.message ? err.message : String(err) });
        });
      }
    } catch (e) {
      _clearAckTimer();
      _state.requestPending = false;
      _state.lastError = { code: 'REQUEST_ERROR', message: String(e && e.message || e) };
      _notify();
      return false;
    }
    return true;
  }

  function exit() {
    var wa = _wa();
    if (!wa) return false;
    if (_state.requestPending) return false;          // повторный тап — игнор
    if (!_state.hasExitFullscreen) {
      _state.lastError = { code: 'UNSUPPORTED', message: 'exitFullscreen недоступен' };
      _notify();
      return false;
    }
    if (_state.actualFullscreen === false) {
      // Выход, когда SDK честно говорит «не в fullscreen» — не отправляем
      // заведомо бессмысленный запрос (кнопка exit при этом скрыта политикой).
      return false;
    }
    _state.requestPending = true;
    _armAckTimer();
    _notify();
    try {
      wa.exitFullscreen();
    } catch (e) {
      _clearAckTimer();
      _state.requestPending = false;
      _state.lastError = { code: 'EXIT_ERROR', message: String(e && e.message || e) };
      _notify();
      return false;
    }
    return true;
  }

  /* ── Init / launch-mode / teardown ───────────────────────────────────── */

  function init(opts) {
    opts = opts || {};
    if (typeof opts.ackTimeoutMs === 'number') setAckTimeoutMs(opts.ackTimeoutMs);
    var wa = _wa();
    _recompute();
    if (_state.launchFullscreen === null && typeof _state.actualFullscreen === 'boolean') {
      // Фактическое начальное состояние (не CSS-guess), фиксируется один раз.
      _state.launchFullscreen = _state.actualFullscreen;
    }
    _subscribeSdk(wa);
    if (_state.actualFullscreen === true) {
      // U07.1e: повторный requestFullscreen НЕ отправляется вовсе — включая
      // старт. Мобильный клиент получает сразу рабочую кнопку ВЫХОДА.
      // Windows (tdesktop) в проблемном стартовом fullscreen: ОДИН мягкий
      // exitFullscreen() при поддержке API; без WinAPI/moveTo/resizeTo.
      if (_state.telegramPlatform === 'tdesktop' && _state.hasExitFullscreen &&
          !_softExitTried) {
        _softExitTried = true;
        try { wa.exitFullscreen(); } catch (e) { /* ack/таймаут задокументируют */ }
        _armSoftExitTimer();
      }
    }
    _applyDomMirror();
    _notify();               // подписчики (Vue-зеркало) получают стартовое состояние
    return state();
  }

  function teardown() {
    _clearAckTimer();
    _clearSoftExitTimer();
    var wa = _wa();
    if (wa && typeof wa.offEvent === 'function' && _sdkSubscribed) {
      try {
        wa.offEvent('fullscreenChanged', _onFullscreenChanged);
        wa.offEvent('fullscreenFailed', _onFullscreenFailed);
        wa.offEvent('viewportChanged', _onViewportChanged);
        wa.offEvent('safeAreaChanged', _onViewportChanged);
        wa.offEvent('contentSafeAreaChanged', _onViewportChanged);
      } catch (e) { /* no-op */ }
    }
    _sdkSubscribed = false;
    _subscribers.length = 0;
    _state.requestPending = false;
  }

  /* ── Экспорт ─────────────────────────────────────────────────────────── */

  var api = {
    state: state,
    request: request,
    exit: exit,
    subscribe: subscribe,
    init: init,
    teardown: teardown,
    setAckTimeoutMs: setAckTimeoutMs,
    slotFromGeometry: slotFromGeometry,
    decideOffer: decideOffer,
    // Диагностика ограничения Windows-launch (отчёт/логи; не меняет поведение)
    launchExitIgnored: function () { return _launchExitIgnored; }
  };

  if (typeof window !== 'undefined') {
    window.__FullscreenPolicy = api;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
