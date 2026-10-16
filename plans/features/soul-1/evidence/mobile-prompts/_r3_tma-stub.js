try {
  // Реальный telegram-web-app.js перетирает window.Telegram своим WebApp с
  // пустым initData (нет настоящего TG). app.js::getInitData кэширует/читает
  // sessionStorage — засеваем его, чтобы hasInitData() был истинным.
  sessionStorage.setItem('adminbot.initData', 'user=%7B%22id%22%3A5885953495%7D&hash=audit');
} catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  themeParams: {}, colorScheme: 'dark',
  get viewportStableHeight() {
    return Math.max(0, (window.innerHeight || 800) - 56);
  },
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
  setBottomBarColor() {}, isExpanded: true,
  _stubHandlers: {},
  onEvent(ev, fn) {
    (this._stubHandlers[ev] = this._stubHandlers[ev] || []).push(fn);
  },
  offEvent(ev, fn) {
    var a = this._stubHandlers[ev] || [];
    this._stubHandlers[ev] = a.filter(function (f) { return f !== fn; });
  },
  __emit(ev) {
    (this._stubHandlers[ev] || []).forEach(function (f) { f(); });
  },
  BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
} };
