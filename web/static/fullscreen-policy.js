/* ═══ W2-FULLSCREEN (asap8-v6.3, U07 / REQ-U07-1..2) + FS-HOTFIX 18.10 ═══
 * FullscreenPolicy — единая политика «client capability × launch mode» для
 * кнопки ⛶ и TMA-fullscreen. Plain IIFE по образцу glass.js/telegram-init.js:
 * CSP-safe, БЕЗ Vue, БЕЗ inline-кода, БЕЗ записи CSS-переменных
 * (--tg-* пишет ТОЛЬКО telegram-init.js, §2.3).
 *
 * FS-HOTFIX (директива владельца, 18.10.2026): прежнее решение —
 * honest-disable на Telegram Desktop + объясняющая заглушка вместо кнопки —
 * признано НЕВЕРНЫМ. Кастомная кнопка РАНЬШЕ работала и реально переключала
 * fullscreen; дефект был в геометрии окна, позиции кнопки и адаптивности, а
 * не в отсутствии API. Поэтому:
 *   • платформенных запретов больше нет — решение принимает фактический API
 *     клиента, а не догадка о платформе; tdesktop — обычный клиент;
 *   • кнопка скрывается ТОЛЬКО при реальном отсутствии API (вне Telegram или
 *     нет ни requestFullscreen, ни exitFullscreen);
 *   • авто-выход из стартового fullscreen (прежний «мягкий exit» на
 *     tdesktop) удалён: клиент, открытый Launch Mode=Fullscreen, остаётся в
 *     нём, кнопка сразу предлагает ВЫХОД (второй request не отправляется);
 *   • UI-заглушек/инструкций нет: причина — в тосте по факту действия;
 *     explain()/diagnostics() остаются dev-API (window.__FullscreenPolicy).
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
 *   • Launch Mode=Fullscreen: повторный requestFullscreen() НЕ отправляется
 *     (clickResult=already_fullscreen) — кнопка = выход;
 *   • window.moveTo/resizeTo/WinAPI/«CSS 100vw = монитор» — запрещены
 *     (U07.0): политика управляет только TMA API и своим layout.
 *
 * Слот кнопки (один DOM-узел .header-fs-btn; писатель html.fs-hidden и
 * data-fs-reason — ТОЛЬКО этот модуль, контракт §2.3):
 *   inline — в потоке row A (штатный, единственный видимый слот); позицию
 *            «рядом с нативными» даёт safe-area-геометрия шапки
 *            (max(env, --tg-safe) + --tg-content-safe-area), а НЕ
 *            fixed-координаты: реальные координаты нативных кнопок клиента
 *            WebView не знает — официального API для них нет
 *            (Telegram-Mini-Apps/issues#62, открыт);
 *   hidden — вне Telegram или клиент без обоих методов (кнопка не должна
 *            вводить в заблуждение, U07.3c).
 *
 * Публичное API: window.__FullscreenPolicy
 *   state() · request() · exit() · subscribe(fn) · init(opts) ·
 *   teardown() · setAckTimeoutMs(ms) · decideOffer(caps) · explain() ·
 *   diagnostics()
 * Чистые функции доступны без DOM (окно-guard) — Node-юнит-тесты:
 * tests/js/asap8_w2_fullscreen_policy_test.js.
 *
 * explain()/diagnostics() (SOUL-12.1/12.3/12.4, dev-API): машинный код
 * причины всегда сопровождается reasonText (человеческий текст) и nextStep;
 * diagnostics() — снимок для воспроизведения (platform/SDK/launch
 * params/факт isFullscreen/методы/viewport/safe area/click result/trace/
 * warnings). Секреты (initData, ключи, токены) НЕ попадают — только факт
 * наличия. launchParams читаются из sessionStorage('__telegram__initParams')
 * (пишет официальный SDK) + hash + query URL по allowlist
 * tgWebAppPlatform/tgWebAppVersion/tgWebAppStartParam; tgWebAppData НЕ
 * выносится (F1 разбора W7: launch-параметры приходят в hash, не в query). */
(function () {
  'use strict';

  var PLATFORMS = ['android', 'ios', 'macos', 'tdesktop', 'weba', 'web', 'unknown'];
  var DEFAULT_ACK_TIMEOUT_MS = 4000;       // таймаут ожидания ack хоста

  /* ── Чистые функции (без DOM/window — unit-матрица) ─────────────────── */

  function normalizePlatform(raw) {
    return PLATFORMS.indexOf(raw) >= 0 ? raw : 'unknown';
  }

  /* decideOffer(caps) → {canOfferFullscreen, canOfferExit, reason, slot}
   * caps: {isTelegram, hasRequestFullscreen, hasExitFullscreen,
   *        hasBooleanIsFullscreen, actualFullscreen}
   * reason-коды: no_telegram_context | request_fullscreen_unsupported |
   * fullscreen_unavailable | ''.
   * FS-HOTFIX: платформа в решении НЕ участвует (tdesktop — обычный
   * клиент); запретов/скрытий по имени платформы нет. Единственная
   * причина скрытия — реальное отсутствие API. */
  function decideOffer(caps) {
    caps = caps || {};
    var actual = caps.actualFullscreen;
    var out = { canOfferFullscreen: false, canOfferExit: false, reason: '', slot: 'inline' };
    if (!caps.isTelegram) {
      out.reason = 'no_telegram_context';
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
    if (!out.canOfferFullscreen && !out.canOfferExit) {
      // Кнопка не должна вводить в заблуждение (U07.3c) — скрываем.
      out.slot = 'hidden';
      if (!out.reason) out.reason = 'fullscreen_unavailable';
    }
    return out;
  }

  /* ── Человеческие объяснения причин (dev-API, SOUL-12.1/12.4) ─────────
   * В UI эти тексты НЕ рендерятся (FS-HOTFIX 18.10: заглушки удалены).
   * Остаются в explain()/diagnostics() как dev-API — для отчётов, логов и
   * воспроизведения: машинный код причины без человеческого текста не
   * отдаётся. Коды, которые политика может выдать: no_telegram_context
   * (кнопка скрыта — Telegram-контекста нет), request_fullscreen_unsupported
   * и fullscreen_unavailable (клиент реально не даёт API). */
  var REASON_TEXT = {
    no_telegram_context:
      'Приложение открыто вне Telegram — полноэкранный режим Telegram здесь недоступен.',
    request_fullscreen_unsupported:
      'Эта версия клиента Telegram не предоставляет requestFullscreen — ' +
      'вход в полноэкранный режим недоступен.',
    fullscreen_unavailable:
      'Клиент не отдаёт ни вход, ни выход из полноэкранного режима — ' +
      'кнопка не показывается, чтобы не вводить в заблуждение.'
  };
  var REASON_NEXT_STEP = {
    no_telegram_context:
      'Откройте Mini App из Telegram (кнопка бота) — там управление ' +
      'полноэкранным режимом доступно.',
    request_fullscreen_unsupported:
      'Обновите Telegram до актуальной версии либо запускайте Mini App из ' +
      'основного чата (кнопка бота) на поддерживаемом клиенте.',
    fullscreen_unavailable:
      'Проверьте версию и платформу клиента: на поддерживаемом клиенте ' +
      'кнопка появляется автоматически.'
  };

  function explainReason(code) {
    if (!code) return { code: '', text: '', nextStep: '' };
    return {
      code: code,
      text: REASON_TEXT[code] || ('Полноэкранный режим недоступен (' + code + ').'),
      nextStep: REASON_NEXT_STEP[code] || ''
    };
  }

  /* explain() → состояние-независимое объяснение текущей причины (dev-API). */
  function explain() {
    return explainReason(_state.reason);
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
    reasonText: '',                // SOUL-12.1: причина без текста запрещена
    nextStep: '',                  // SOUL-12.4: что владельцу сделать
    slot: 'inline',
    viewport: {
      width: 0, height: 0, stableHeight: 0,
      safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
      contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 }
    }
  };

  var _subscribers = [];
  var _ackTimer = null;
  var _ackTimeoutMs = DEFAULT_ACK_TIMEOUT_MS;
  var _sdkSubscribed = false;
  var _initCount = 0;              // SOUL-12.5: двойная инициализация видна
  var _clickResult = 'never';      // результат последнего касания ⛶
  var _trace = [];                 // SOUL-12.5: последовательность событий
  var _warnings = [];              // предупреждения SDK/политики (коды)
  var TRACE_CAP = 40;
  var WARN_CAP = 20;
  var LAUNCH_PARAM_KEYS = ['tgWebAppPlatform', 'tgWebAppVersion',
                           'tgWebAppStartParam'];

  function _now() {
    try { return Date.now(); } catch (e) { return 0; }
  }

  function _pushTrace(code, extra) {
    _trace.push({ code: code, at: _now(), extra: extra || '' });
    if (_trace.length > TRACE_CAP) _trace.splice(0, _trace.length - TRACE_CAP);
  }

  function _pushWarning(code) {
    for (var i = 0; i < _warnings.length; i++) {
      if (_warnings[i].code === code) { _warnings[i].count++; return; }
    }
    _warnings.push({ code: code, at: _now(), count: 1 });
    if (_warnings.length > WARN_CAP) _warnings.splice(0, _warnings.length - WARN_CAP);
  }

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
      reasonText: _state.reasonText,
      nextStep: _state.nextStep,
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
      actualFullscreen: _state.actualFullscreen
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
    _readViewport(wa);   // факты insets/viewport до решения (diagnostics/dev)
    var caps = _capabilities(wa);
    _state.hasRequestFullscreen = caps.hasRequestFullscreen;
    _state.hasExitFullscreen = caps.hasExitFullscreen;
    var offer = decideOffer(caps);
    _state.canOfferFullscreen = offer.canOfferFullscreen;
    _state.canOfferExit = offer.canOfferExit;
    _state.reason = offer.reason;
    _state.slot = offer.slot;
    // SOUL-12.1: код причины всегда с человеческим текстом и следующим шагом.
    var quoted = explainReason(offer.reason);
    _state.reasonText = quoted.text;
    _state.nextStep = quoted.nextStep;
  }

  /* ── diagnostics(): снимок для воспроизведения (SOUL-12.3) ────────────
   * Секретов нет: initData/initDataUnsafe/ключи/токены НЕ читаются —
   * только булев факт их наличия. launchParams — публичные ключи
   * tgWebApp* по allowlist. */
  var LAUNCH_PARAM_STORAGE_KEY = '__telegram__initParams';

  function _hashPairs() {
    var out = [];
    try {
      if (typeof window === 'undefined' || !window.location) return out;
      var raw = String(window.location.search || '') +
                '&' + String(window.location.hash || '').replace(/^#/, '');
      var q = raw.replace(/^&+/, '').split('&');
      for (var i = 0; i < q.length; i++) {
        if (!q[i]) continue;
        var kv = q[i].split('=');
        out.push([kv[0], decodeURIComponent(kv.slice(1).join('=') || '')]);
      }
    } catch (e) { /* guard */ }
    return out;
  }

  /* F1 (разбор W7): официальный SDK присылает launch-параметры в HASH
   * (`#tgWebAppPlatform=...`) и складывает их в
   * sessionStorage('__telegram__initParams'); приложение затем заменяет hash
   * на `#/`. Поэтому порядок источников: storage (переживает замену hash) →
   * hash/search URL. Значения — ТОЛЬКО allowlist-ключи (tgWebAppData,
   * initData и секреты не выносятся). */
  function _launchParams() {
    var out = {};
    var i;
    for (i = 0; i < LAUNCH_PARAM_KEYS.length; i++) out[LAUNCH_PARAM_KEYS[i]] = null;
    function apply(k, v) {
      if (LAUNCH_PARAM_KEYS.indexOf(k) < 0) return;
      if (out[k] === null || out[k] === undefined) out[k] = String(v);
    }
    try {
      if (typeof window !== 'undefined' && window.sessionStorage) {
        var raw = window.sessionStorage.getItem(LAUNCH_PARAM_STORAGE_KEY);
        if (raw) {
          var obj = JSON.parse(raw);
          if (obj && typeof obj === 'object') {
            for (i = 0; i < LAUNCH_PARAM_KEYS.length; i++) {
              var k = LAUNCH_PARAM_KEYS[i];
              if (typeof obj[k] === 'string' || typeof obj[k] === 'number') {
                apply(k, obj[k]);
              }
            }
          }
        }
      }
    } catch (e0) { /* guard: нет storage/битый JSON */ }
    var pairs = _hashPairs();
    for (i = 0; i < pairs.length; i++) apply(pairs[i][0], pairs[i][1]);
    return out;
  }

  function diagnostics() {
    var wa = _wa();
    var params = _launchParams();
    // initData/ключи не отдаём: только факт присутствия (R17).
    var hasInitData = false, hasInitDataUnsafe = false;
    try {
      hasInitData = !!(wa && wa.initData);
      hasInitDataUnsafe = !!(wa && wa.initDataUnsafe);
    } catch (e) { /* guard */ }
    return {
      platform: _state.telegramPlatform,
      sdkVersion: _state.sdkVersion,
      launchParams: params,
      hasInitData: hasInitData,
      hasInitDataUnsafe: hasInitDataUnsafe,
      isFullscreenSupported: !!(_state.actualFullscreen === true ||
                                _state.actualFullscreen === false),
      actualFullscreen: _state.actualFullscreen,
      launchFullscreen: _state.launchFullscreen,
      hasRequestFullscreen: _state.hasRequestFullscreen,
      hasExitFullscreen: _state.hasExitFullscreen,
      hasExpand: !!(wa && typeof wa.expand === 'function'),
      hasReady: !!(wa && typeof wa.ready === 'function'),
      isExpanded: !!(wa && wa.isExpanded),
      slot: _state.slot,
      reason: _state.reason,
      reasonText: _state.reasonText,
      nextStep: _state.nextStep,
      canOfferFullscreen: _state.canOfferFullscreen,
      canOfferExit: _state.canOfferExit,
      requestPending: _state.requestPending,
      lastError: _state.lastError ? _state.lastError.code : null,
      width: _state.viewport.width,
      height: _state.viewport.height,
      stableHeight: _state.viewport.stableHeight,
      safeAreaInset: _state.viewport.safeAreaInset,
      contentSafeAreaInset: _state.viewport.contentSafeAreaInset,
      ackTimeoutMs: _ackTimeoutMs,
      initCount: _initCount,
      clickResult: _clickResult,
      hostBehaviour: {
        sdkSubscribed: _sdkSubscribed
      },
      trace: _trace.slice(0),
      warnings: _warnings.slice(0)
    };
  }

  /* ── DOM-зеркало слота (html.fs-hidden / data-fs-reason; единственный
   * writer) ────────────────────────────────────────────────────────────── */

  function _applyDomMirror() {
    if (typeof document === 'undefined' || !document.documentElement) return;
    var de = document.documentElement;
    if (!de.classList) return;
    if (_state.slot === 'hidden') {
      de.classList.add('fs-hidden');
    } else {
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
        _pushTrace('ackTimeout');
        _pushWarning('ACK_TIMEOUT');
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

  /* ── События SDK ─────────────────────────────────────────────────────── */

  function _onFullscreenChanged() {
    var wasPending = _state.requestPending;
    _clearAckTimer();
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
      _pushWarning('ACK_WITHOUT_BOOLEAN');
    }
    _pushTrace('fullscreenChanged', String(_state.actualFullscreen));
    _recompute();
    _notify();
  }

  function _onFullscreenFailed(payload) {
    _clearAckTimer();
    _state.requestPending = false;
    var code = (payload && (payload.error_code || payload.error || payload.errorCode)) || 'UNKNOWN';
    _pushTrace('fullscreenFailed', String(code));
    _pushWarning(String(code));
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
    _pushTrace('viewportChanged');
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
    if (!wa) { _clickResult = 'no_sdk'; return false; }
    if (_state.actualFullscreen === true) {
      // U07.1e/U07.1d: Launch-fullscreen / уже в fullscreen — ВТОРОЙ
      // requestFullscreen не отправляем; честный статус + кнопка выхода.
      _recompute();
      if (_state.actualFullscreen === true) {
        _state.lastError = { code: 'ALREADY_FULLSCREEN', message: 'Уже в полноэкранном режиме' };
        _clickResult = 'already_fullscreen';
        _pushTrace('request', 'already_fullscreen');
        _notify();
        return false;
      }
    }
    if (_state.requestPending) {          // повторный тап — игнор
      _clickResult = 'pending_guard';
      _pushTrace('request', 'pending_guard');
      return false;
    }
    if (!_state.canOfferFullscreen || !_state.hasRequestFullscreen) {
      _state.lastError = {
        code: 'UNSUPPORTED',
        message: 'Полноэкранный режим недоступен' + (_state.reason ? ' (' + _state.reason + ')' : '')
      };
      _clickResult = 'unsupported';
      _pushTrace('request', 'unsupported');
      _pushWarning('UNSUPPORTED');
      _notify();
      return false;
    }
    _state.requestPending = true;
    _clickResult = 'request_sent';
    _pushTrace('request', 'sent');
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
    if (!wa) { _clickResult = 'no_sdk'; return false; }
    if (_state.requestPending) {          // повторный тап — игнор
      _clickResult = 'pending_guard';
      _pushTrace('exit', 'pending_guard');
      return false;
    }
    if (!_state.hasExitFullscreen) {
      _state.lastError = { code: 'UNSUPPORTED', message: 'exitFullscreen недоступен' };
      _clickResult = 'unsupported';
      _pushTrace('exit', 'unsupported');
      _pushWarning('UNSUPPORTED');
      _notify();
      return false;
    }
    if (_state.actualFullscreen === false) {
      // Выход, когда SDK честно говорит «не в fullscreen» — не отправляем
      // заведомо бессмысленный запрос (кнопка exit при этом скрыта политикой).
      _clickResult = 'noop_not_fullscreen';
      return false;
    }
    _state.requestPending = true;
    _clickResult = 'exit_sent';
    _pushTrace('exit', 'sent');
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
    _initCount++;
    _pushTrace('init', 'n=' + _initCount);
    if (_initCount > 1) _pushWarning('DOUBLE_INIT');
    if (typeof opts.ackTimeoutMs === 'number') setAckTimeoutMs(opts.ackTimeoutMs);
    var wa = _wa();
    _recompute();
    if (_state.launchFullscreen === null && typeof _state.actualFullscreen === 'boolean') {
      // Фактическое начальное состояние (не CSS-guess), фиксируется один раз.
      _state.launchFullscreen = _state.actualFullscreen;
    }
    _subscribeSdk(wa);
    // Launch Mode=Fullscreen: если клиент стартовал уже в fullscreen,
    // повторный requestFullscreen НЕ отправляется (U07.1e) — кнопка сразу
    // = выход. Прежний автоматический «мягкий exit» на tdesktop УДАЛЁН
    // (FS-HOTFIX 18.10): политика не выводит клиента из запрошенного
    // владельцем режима за его спиной.
    _applyDomMirror();
    _notify();               // подписчики (Vue-зеркало) получают стартовое состояние
    return state();
  }

  function teardown() {
    _clearAckTimer();
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
    // Чистое решение «что предлагать» (unit-матрица; платформа не участвует)
    decideOffer: decideOffer,
    // Dev-API (в UI не рендерится): объяснение причины и снимок фактов
    explain: explain,
    diagnostics: diagnostics
  };

  if (typeof window !== 'undefined') {
    window.__FullscreenPolicy = api;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
