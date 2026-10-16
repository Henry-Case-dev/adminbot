[matrix] config stub: items=570 groups=120
[matrix] chat-╨▓╨░╤А╨╕╨░╨╜╤В config: override items=114

try {
  // ╨а╨╡╨░╨╗╤М╨╜╤Л╨╣ telegram-web-app.js ╨┐╨╡╤А╨╡╤В╨╕╤А╨░╨╡╤В window.Telegram ╤Б╨▓╨╛╨╕╨╝ WebApp ╤Б
  // ╨┐╤Г╤Б╤В╤Л╨╝ initData (╨╜╨╡╤В ╨╜╨░╤Б╤В╨╛╤П╤Й╨╡╨│╨╛ TG). app.js::getInitData ╨║╤Н╤И╨╕╤А╤Г╨╡╤В/╤З╨╕╤В╨░╨╡╤В
  // sessionStorage тАФ ╨╖╨░╤Б╨╡╨▓╨░╨╡╨╝ ╨╡╨│╨╛, ╤З╤В╨╛╨▒╤Л hasInitData() ╨▒╤Л╨╗ ╨╕╤Б╤В╨╕╨╜╨╜╤Л╨╝.
  sessionStorage.setItem('adminbot.initData', 'user=%7B%22id%22%3A5885953495%7D&hash=audit');
} catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  themeParams: {}, colorScheme: 'dark',
  // hotfix4 (T-2517): ╨╕╨╝╨╕╤В╨╕╤А╤Г╨╡╨╝ ╤Б╨╕╤Б╤В╨╡╨╝╨╜╤Л╨╣ ╨╜╨╕╨╢╨╜╨╕╨╣ ╨▒╨░╤А Telegram тАФ visible
  // (stable) ╨▓╤Л╤Б╨╛╤В╨░ ╨╝╨╡╨╜╤М╤И╨╡ layout (innerHeight) ╨╜╨░ 56px. ╨в╨╛╨│╨┤╨░ ╨┐╨░╨╜╨╡╨╗╤М ╤Б
  // bottom:0 ╨▓╤Л╤Е╨╛╨┤╨╕╤В ╨╖╨░ ╨▓╨╕╨┤╨╕╨╝╤Г╤О ╨╛╨▒╨╗╨░╤Б╤В╤М, ╨░ ╤Б offset-╨║╨╛╨╝╨┐╨╡╨╜╤Б╨░╤Ж╨╕╨╡╨╣ тАФ ╨╜╨╡╤В.
  get viewportStableHeight() {
    return Math.max(0, (window.innerHeight || 800) - 56);
  },
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
  setBottomBarColor() {}, isExpanded: true,
  // HOTFIX7 (T-2681): ╨╝╨╕╨╜╨╕╨╝╨░╨╗╤М╨╜╨░╤П ╤И╨╕╨╜╨░ ╤Б╨╛╨▒╤Л╤В╨╕╨╣ тАФ fullscreenChanged/
  // viewportChanged ╨╜╤Г╨╢╨╜╤Л ╨┤╨╗╤П ╨┐╤А╨╛╨▓╨╡╤А╨║╨╕ ╨┐╨╡╤А╨╡╤Е╨╛╨┤╨░ shell ╨▓ fullscreen-╤А╨╡╨╢╨╕╨╝.
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

