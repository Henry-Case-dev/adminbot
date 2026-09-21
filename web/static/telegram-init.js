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
  wa.setHeaderColor(_tp.header_bg_color || '#161616');
  wa.setBackgroundColor(_tp.bg_color || '#0E0E0E');
  if (typeof wa.setBottomBarColor === 'function') {
    wa.setBottomBarColor(_tp.bottom_bar_bg_color || '#161616');
  }

  /* F1 round 10.25 (ADR-1025-1 D7/T-2399): прокидываем safe-area и стабильную
   * высоту вьюпорта в CSS-переменные (CSP-safe, без inline). CSS читает
   * max(env(safe-area-inset-*), var(--tg-*)) — значения Telegram точнее env. */
  var root = document.documentElement;
  function setVar(name, value) {
    if (value === undefined || value === null || value === '') return;
    root.style.setProperty(name, value + 'px');
  }
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
    /* hotfix4 (T-2514/T-2516, ADR-1025-8 D2): нижняя панель/шторка позициони-
     * руются по layout-вьюпорту (bottom:0 = под системным баром), а
     * viewportStableHeight — уже видимая высота. Считаем разницу и прокидываем
     * offset в CSS. UI-кламп: 0 при отсутствии разницы (Desktop/Android без
     * бара), clamp по высоте вьюпорта; inset-ы учитываем через stableHeight. */
    var layoutH = (window.innerHeight || 0);
    var stableH = wa.viewportStableHeight;
    var offset = 0;
    if (typeof stableH === 'number' && layoutH > 0) {
      offset = Math.max(0, Math.min(layoutH, layoutH - stableH));
    }
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
