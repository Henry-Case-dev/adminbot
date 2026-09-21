/* F4 10.16 (ADR-1016-2 §2, T-1653): Telegram WebApp init вынесен из inline
 * <script> в index.html → CSP `script-src 'self'` без 'unsafe-inline'/nonce.
 * Загружается ПОСЛЕ /static/vendor/telegram-web-app.js и /web/app.js
 * (порядок как у прежнего inline-блока; app.mount уже выполнен).
 * Задание B (2026-09-03): тема миниаппа согласуется с тёмной темой админки;
 * setBottomBarColor — Bot API 7.10+ (guard). Саму инлайн-кнопку бота клиент
 * рисует по своей теме — из бота её цвет/форму изменить нельзя. */
(function () {
  if (!(window.Telegram && Telegram.WebApp)) return;
  var wa = Telegram.WebApp;
  var _tp = wa.themeParams || {};
  wa.ready();
  wa.expand();
  // F2 round 10.25 (ADR-1025-9 D1/T-2536): фолбэки темы → палитра §8
  // (Background #090D17 / Surface #151B2A) вместо прежних OD4-фолбэков.
  wa.setHeaderColor(_tp.header_bg_color || '#151B2A');
  wa.setBackgroundColor(_tp.bg_color || '#090D17');
  if (typeof wa.setBottomBarColor === 'function') {
    wa.setBottomBarColor(_tp.bottom_bar_bg_color || '#151B2A');
  }

  /* F1 round 10.25 (ADR-1025-1 D7/T-2399): прокидываем safe-area и стабильную
   * высоту вьюпорта в CSS-переменные (CSP-safe, без inline). CSS читает
   * max(env(safe-area-inset-*), var(--tg-*)) — значения Telegram точнее env. */
  var root = document.documentElement;
  function setVar(name, value) {
    if (value === undefined || value === null || value === '') return;
    root.style.setProperty(name, value + 'px');
  }
  /* hotfix6 (T-2593, AMEND ADR-1025-12 D3): нижний offset — МАКСИМУМ трёх
   * кандидатов (все описывают одну нижнюю «занятую» зону; сумма дала бы ложный
   * «задир» панели). A — разница layout/stable (hotfix4); B — Telegram UI снизу
   * (contentSafeAreaInset.bottom); C — системная зона (safeAreaInset.bottom).
   * Guard hotfix4 (stableH>0) сохранён. Клиенты без инсетов → 0 (панель на
   * bottom:0). Чистая функция — юнит-тестируема (window.__computeTgBottomOffset). */
  function computeBottomOffset(innerHeight, viewportStableHeight,
                               contentSafeAreaInsetBottom, safeAreaInsetBottom) {
    var a = 0;
    var ih = (typeof innerHeight === 'number' && innerHeight > 0) ? innerHeight : 0;
    if (ih > 0 && typeof viewportStableHeight === 'number' &&
        viewportStableHeight > 0) {
      a = Math.max(0, Math.min(ih, ih - viewportStableHeight));
    }
    var b = (typeof contentSafeAreaInsetBottom === 'number' &&
             contentSafeAreaInsetBottom > 0) ? contentSafeAreaInsetBottom : 0;
    var c = (typeof safeAreaInsetBottom === 'number' &&
             safeAreaInsetBottom > 0) ? safeAreaInsetBottom : 0;
    return Math.max(a, b, c);
  }
  window.__computeTgBottomOffset = computeBottomOffset;
  function applyInsets() {
    var sa = wa.safeAreaInset;
    if (sa) {
      setVar('--tg-safe-area-inset-top', sa.top);
      setVar('--tg-safe-area-inset-bottom', sa.bottom);
      setVar('--tg-safe-area-inset-left', sa.left);
      setVar('--tg-safe-area-inset-right', sa.right);
    }
    var csa = wa.contentSafeAreaInset;
    if (csa) {
      setVar('--tg-content-safe-area-inset-top', csa.top);
      setVar('--tg-content-safe-area-inset-bottom', csa.bottom);
      setVar('--tg-content-safe-area-inset-left', csa.left);
      setVar('--tg-content-safe-area-inset-right', csa.right);
    }
    if (typeof wa.viewportStableHeight === 'number') {
      setVar('--tg-viewport-stable-height', wa.viewportStableHeight);
    }
    /* hotfix6 (T-2593): offset = max(hotfix4-разница, contentSafeAreaInset.bottom,
     * safeAreaInset.bottom) — учитываем Telegram UI снизу, а не только системный
     * бар. Пересчёт на всех ниже-подписках + resize (страховка от «залипания»). */
    var offset = computeBottomOffset(
      window.innerHeight || 0,
      wa.viewportStableHeight,
      csa ? csa.bottom : 0,
      sa ? sa.bottom : 0);
    setVar('--tg-viewport-bottom-offset', offset);
  }
  applyInsets();
  if (typeof wa.onEvent === 'function') {
    wa.onEvent('viewportChanged', applyInsets);
    wa.onEvent('safeAreaChanged', applyInsets);
    wa.onEvent('contentSafeAreaChanged', applyInsets);
  }
  /* hotfix4 (T-2516): пересчёт на resize окна/повороте — страховка, если
   * клиент не прислал Telegram-событие (offset не должен «залипать»). */
  if (typeof window.addEventListener === 'function') {
    window.addEventListener('resize', applyInsets);
  }

  /* F1 (UPD §8.4): BackButton show/hide управляет app.js (syncBackButton);
   * здесь только гарантируем корректный старт состояния — скрыт на корне. */
  if (wa.BackButton && typeof wa.BackButton.hide === 'function') {
    wa.BackButton.hide();
  }
})();
