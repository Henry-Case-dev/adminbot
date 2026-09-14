/* F4 10.16 (ADR-1016-2 §2, T-1653): Telegram WebApp init вынесен из inline
 * <script> в index.html → CSP `script-src 'self'` без 'unsafe-inline'/nonce.
 * Загружается ПОСЛЕ /static/vendor/telegram-web-app.js и /web/app.js
 * (порядок как у прежнего inline-блока; app.mount уже выполнен).
 * Задание B (2026-09-03): тема миниаппа согласуется с тёмной темой админки;
 * setBottomBarColor — Bot API 7.10+ (guard). Саму инлайн-кнопку бота клиент
 * рисует по своей теме — из бота её цвет/форму изменить нельзя. */
(function () {
  if (!(window.Telegram && Telegram.WebApp)) return;
  var _tp = Telegram.WebApp.themeParams || {};
  Telegram.WebApp.ready();
  Telegram.WebApp.expand();
  Telegram.WebApp.setHeaderColor(_tp.header_bg_color || '#161616');
  Telegram.WebApp.setBackgroundColor(_tp.bg_color || '#0E0E0E');
  if (typeof Telegram.WebApp.setBottomBarColor === 'function') {
    Telegram.WebApp.setBottomBarColor(_tp.bottom_bar_bg_color || '#161616');
  }
})();
