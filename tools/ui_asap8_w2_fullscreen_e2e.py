"""W2-FULLSCREEN (asap8-v6.3, U07/V06-prep) + FS-HOTFIX 18.10 — Playwright-e2e
кнопки ⛶, геометрии слота и ack-модели.

Харнесс: локальный http-сервер + РЕАЛЬНЫЕ web/index.html + web/app.js +
web/static/fullscreen-policy.js. Telegram SDK НЕ стабится addInitScript'ом
(контракт w2 §4.2: реальный SDK sync в <head> и перетёр бы мок) —
`/static/vendor/telegram-web-app.js` перехватывается ROUTE-ом и отдаётся
управляемый мок (platform × capability × launch mode × insets, ручная эмиссия
fullscreenChanged/fullscreenFailed). `/api/*` — фейковые ответы (без
секретов/БД). Запускается поверх расширяемого харнесса
tools/ui_round1025_matrix.py (тот же сервер/стабы — новых стеков нет).

FS-HOTFIX 18.10 (директива владельца): кнопка возвращена на ВСЕ клиенты, где
есть API (включая tdesktop); слот — всегда inline (row A, под нативной
панелью клиента); стеклянная подложка/float-резерв/авто-exit удалены;
launch-fullscreen больше не «гасится» политикой.

Проверяется (mock-only! живой клиент — только у владельца, U07.3b):
  * android csa.top=36 → inline-кнопка с hit ≥44×44, ниже band = safe+content,
    НЕ пересекается с мок-зоной нативных кнопок (rect-пересечение == 0) и НЕ
    пересекается с контентом шапки; стиль «как у нативных»: без ::before,
    без backdrop-filter; ack-флоу: 1 request → exit;
  * csa.top=0 (windowed) → inline; ширины 320/390 — без h-overflow;
  * tdesktop → кнопка ВИДИМА (FS-HOTFIX), причин-заглушек нет, авто-вызовов
    SDK на старте НЕТ; launch-fullscreen tdesktop → тоже без авто-exit,
    кнопка = выход;
  * stand-alone без Telegram → hidden (U07.3c), data-fs-reason;
  * ack-флоу: ALREADY_FULLSCREEN → факт из SDK без второго request;
    UNSUPPORTED → состояние прежнее + тост; ack-таймаут снимает pending без
    инверсии; повторный тап при pending — один запрос; SDK без boolean — без
    инверсии (legacy-дефект устранён);
  * Launch Mode=Fullscreen (android) → ВТОРОГО requestFullscreen нет, сразу
    рабочая кнопка выхода (U07.1e);
  * ширины 320/390/667×375: геометрия (портрет/ландшафт), hit ≥44×44,
    компактная шапка в ландшафте (числа в отчёте);
  * мульти-переходы fullscreen↔window (кнопка + JS-транзиции) без
    перезагрузки: hash/раздел/чат/незакрытый ввод сохраняются, кнопка при
    выходе из fullscreen НЕ исчезает; поворот viewport пересчитывает
    геометрию без потери состояния (S9);
  * FOLLOW-UP §7 №8: скрытие логотипа AdminBot освобождает ширину селектору,
    кнопка ⛶ не смещается, шапка не растёт, пересечений/overflow нет (S10);
  * FOLLOW-UP §7 №12: длинное имя чата (ellipsis) и состояния GLOBAL/ЧАТ не
    ломают положение кнопки; выбор чата не теряется (S11);
  * FOLLOW-UP §8: admin-диагностика геометрии — off by default, admin-гейт,
    компактный снимок (платформа/SDK/isFullscreen/viewport+stable/оба
    insets/rect ⛶/rect шапки/layout/логотип/высота/API/последнее
    переключение), копирование одним действием, без секретов, оверлей
    вычисленных границ по кнопке (S12); вне admin-прав — ничего (S13).

Запуск: .venv/Scripts/python.exe tools/ui_asap8_w2_fullscreen_e2e.py
Артефакты: plans/features/soul-1/evidence/fs-hotfix/e2e-w2/
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
PORT = M.PORT + 9
EVIDENCE = os.environ.get(
    "FS_E2E_EVIDENCE",
    os.path.join(REPO, "plans", "features", "soul-1", "evidence", "fs-hotfix",
                 "e2e-w2"))
RAW = os.path.join(EVIDENCE, "_results.json")
os.makedirs(EVIDENCE, exist_ok=True)

BASE_URL = "http://127.0.0.1:%d" % PORT

ME = json.loads(json.dumps(M.ME_JSON))
ME["ui_flags"]["TOKEN_FLOW_NODEFLOW_ENABLED"] = False   # чужой known render-error
ME["ui_flags"]["UI_POLYGON_BG_ENABLED"] = False         # детерминированный фон


def mock_sdk_js(cfg):
    """Мок официального SDK: РОВНО те факты, что задаёт сценарий. Методы
    только фиксируют вызовы (эмуляция хоста); события — ручная эмиссия.
    cfg.nativeStrip=True рисует НЕинтерактивную мок-зону нативных кнопок
    клиента (pointer-events:none) — для геометрической проверки «не
    пересекается с зоной нативных кнопок» (координаты в моке честные:
    band = safeAreaInset.top + contentSafeAreaInset.top)."""
    return """
(function () {
  var cfg = %s;
  var handlers = {};
  var calls = [];
  var webapp = {
    platform: cfg.platform,
    version: cfg.version || '8.0',
    initData: 'user=%%7B%%22id%%22%%3A5885953495%%7D&hash=audit',
    initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
    themeParams: {}, colorScheme: 'dark',
    viewportStableHeight: cfg.stableHeight,
    viewportHeight: cfg.viewportHeight,
    safeAreaInset: cfg.safeAreaInset,
    contentSafeAreaInset: cfg.contentSafeAreaInset,
    ready() {}, expand() {},
    setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
    isExpanded: true,
    requestFullscreen() { calls.push('requestFullscreen'); },
    requestFullScreen() { calls.push('requestFullScreen'); },
    exitFullscreen() { calls.push('exitFullscreen'); },
    onEvent(ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); },
    offEvent(ev, fn) {
      var a = handlers[ev] || []; var i = a.indexOf(fn);
      if (i >= 0) a.splice(i, 1);
    },
    __emit(ev, payload) {
      (handlers[ev] || []).slice().forEach(function (f) { f(payload); });
    },
    __calls: calls,
  };
  if (cfg.hasBoolean) webapp.isFullscreen = !!cfg.isFullscreen;
  window.Telegram = { WebApp: webapp };
  window.__tma = webapp;
  try {
    sessionStorage.setItem('adminbot.initData',
      'user=%%7B%%22id%%22%%3A5885953495%%7D&hash=audit');
    sessionStorage.setItem('__telegram__initParams', JSON.stringify({
      tgWebAppPlatform: cfg.platform, tgWebAppVersion: cfg.version || '8.0',
      tgWebAppStartParam: 'e2e'
    }));
  } catch (e) {}
  if (cfg.nativeStrip) {
    var paint = function () {
      var h = ((cfg.safeAreaInset || {}).top || 0) +
              ((cfg.contentSafeAreaInset || {}).top || 0);
      var s = document.createElement('div');
      s.id = 'mock-native-strip';
      s.setAttribute('style', 'position:fixed;left:0;right:0;top:0;height:' + h +
        'px;z-index:9999;pointer-events:none;background:rgba(220,40,40,0.18);' +
        'border-bottom:1px dashed rgba(220,40,40,0.55);color:rgba(255,220,220,0.9);' +
        'font:10px/1.1 monospace;padding:2px 6px;box-sizing:border-box;');
      s.textContent = 'MOCK native zone (Telegram-owned)  ✕           ⌄  ⋮';
      document.body.appendChild(s);
    };
    if (document.body) paint();
    else document.addEventListener('DOMContentLoaded', paint);
  }
})();
""" % json.dumps(cfg)


NO_SDK_JS = "/* stand-alone: SDK не загружается (симуляция прямого линка) */"


def _api_handler_factory(me=None, overrides=None):
    me_payload = me if me is not None else ME
    over = overrides or {}

    def handler(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me_payload))
            return
        for marker, payload in over.items():
            if url.endswith(marker):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))
                return
        payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return handler


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _first_diff(a, b):
    """Первое расхождение двух строк (для диагностики clipboard-проверки)."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return (i, a[max(0, i - 20):i + 20], b[max(0, i - 20):i + 20])
    if len(a) != len(b):
        return (n, a[n:n + 20], b[n:n + 20])
    return ('равны', '', '')


class Check:
    """Копилка проверок сценария (fail → фиксация, не падение всего прогона)."""

    def __init__(self, name):
        self.name = name
        self.failures = []
        self.count = 0

    def ok(self, cond, msg):
        self.count += 1
        if not cond:
            self.failures.append(msg)
        return bool(cond)


PROBE_FS = """
(() => {
  const btn = document.querySelector('.header-fs-btn');
  const r = btn ? btn.getBoundingClientRect() : null;
  const cs = btn ? getComputedStyle(btn) : null;
  const before = btn ? getComputedStyle(btn, '::before') : null;
  const de = document.documentElement;
  const header = document.querySelector('header.header-sticky');
  const hr = header ? header.getBoundingClientRect() : null;
  const strip = document.getElementById('mock-native-strip');
  const sr = strip ? strip.getBoundingClientRect() : null;
  const wa = window.Telegram && window.Telegram.WebApp;
  const band = wa ? (((wa.safeAreaInset || {}).top || 0) +
                     ((wa.contentSafeAreaInset || {}).top || 0)) : 0;
  const round = (v) => Math.round(v);
  const rect = (q) => q ? { x: round(q.x), y: round(q.y),
                            w: round(q.width), h: round(q.height),
                            right: round(q.right), bottom: round(q.bottom) } : null;
  const inter = (a, b) => {
    if (!a || !b) return null;
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return (w > 0 && h > 0) ? (w * h) : 0;   // площадь пересечения, px^2
  };
  const contentRects = ['.scope-trigger', '.header-user', '.header-more-btn',
                        '.header-save-chip']
    .map((s) => document.querySelector(s))
    .filter(Boolean)
    .map((e) => e.getBoundingClientRect());
  const icon = document.querySelector('.header-fs-btn .fs-ic');
  const ir = icon ? icon.getBoundingClientRect() : null;
  return {
    btnPresent: !!btn,
    rect: rect(r),
    bandTop: band,
    stripRect: rect(sr),
    btnXStripArea: inter(r, sr),
    btnXContentAreas: r ? contentRects.map((e) => inter(r, e)) : [],
    posFixed: cs ? cs.position === 'fixed' : null,
    btnBg: cs ? cs.backgroundColor : null,
    btnBeforeContent: before ? before.content : null,
    btnBackdrop: cs ? (cs.backdropFilter || cs.webkitBackdropFilter || 'none') : null,
    iconRect: rect(ir),
    ariaPressed: btn ? btn.getAttribute('aria-pressed') : null,
    ariaLabel: btn ? (btn.getAttribute('aria-label') || '') : '',
    title: btn ? (btn.getAttribute('title') || '') : '',
    hiddenClass: de.classList.contains('fs-hidden'),
    fsReason: de.getAttribute('data-fs-reason'),
    shellFullscreen: (() => {
      const sh = document.querySelector('.app-shell');
      return sh ? sh.classList.contains('fullscreen-mode') : null;
    })(),
    scrollWidth: de.scrollWidth,
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    hOverflow: de.scrollWidth > window.innerWidth + 1,
    headerRect: rect(hr),
    headerPadTop: header ? parseFloat(getComputedStyle(header).paddingTop) : null,
    interceptTopRight: (() => {
      const el = document.elementFromPoint(window.innerWidth - 10, 8);
      return el ? (el.className || '').toString() + '#' + el.tagName : null;
    })(),
    interceptTopLeft: (() => {
      const el = document.elementFromPoint(24, 8);
      return el ? (el.className || '').toString() + '#' + el.tagName : null;
    })(),
    toasts: Array.from(document.querySelectorAll('.toast-text'))
      .map((t) => t.textContent.trim()).slice(0, 3),
    fsStripInDom: !!document.querySelector('[data-fs-diagnostics]'),
    brandPresent: document.querySelectorAll('.mobile-brand, .sidebar-brand').length > 0,
    brandDisplay: (() => {
      // ASAP-UI-02 §2.2: узла бренда в UI больше нет — вернуть фактическое
      // состояние (null), если он отсутствует.
      const b = document.querySelector('.mobile-brand, .sidebar-brand');
      if (!b) return null;
      const cs = getComputedStyle(b);
      return cs.display + (b.offsetParent === null ? '/hidden' : '/visible');
    })(),
    scopeRect: (() => { const s = document.querySelector('.scope-trigger');
      return s ? { x: round(s.getBoundingClientRect().x),
                   y: round(s.getBoundingClientRect().y),
                   w: round(s.getBoundingClientRect().width),
                   h: round(s.getBoundingClientRect().height),
                   right: round(s.getBoundingClientRect().right),
                   bottom: round(s.getBoundingClientRect().bottom) } : null; })(),
    scopeBadge: (() => {
      const b = document.querySelector('.scope-trigger .badge');
      return b ? b.textContent.trim() : null;
    })(),
    scopeTitleSpanTruncated: (() => {
      const s = document.querySelector('.scope-trigger span.truncate');
      return s ? (s.scrollWidth > s.clientWidth + 1) : null;
    })(),
    scopeTriggerTitle: (() => {
      const s = document.querySelector('.scope-trigger');
      return s ? (s.getAttribute('title') || '') : null;
    })(),
    policyExplain: (() => {
      try { return window.__FullscreenPolicy.explain(); } catch (e) { return null; }
    })(),
  };
})()
"""

STATE_PROBE = """
(() => ({
  hash: window.location.hash,
  activeNav: (() => {
    const a = document.querySelector('.app-drawer .sidebar-link.active, '
                                     + '.app-sidebar .sidebar-link.active');
    return a ? a.textContent.trim() : null;
  })(),
  scopeText: (() => {
    const t = document.querySelector('.scope-trigger');
    return t ? t.textContent.trim().replace(/\\s+/g, ' ') : null;
  })(),
  dropdownOpen: !!document.querySelector('.scope-panel'),
  searchValue: (() => {
    const i = document.querySelector('.scope-panel input[type=search]');
    return i ? i.value : null;
  })(),
  keepMarker: window.__fsKeepMarker || null,
  navEntries: performance.getEntriesByType('navigation').length,
  scrollTop: (() => {
    const m = document.querySelector('main.scroll-area');
    return m ? Math.round(m.scrollTop) : null;
  })(),
}))()
"""

SCRIPT_ORDER_JS = """
(() => {
  const srcs = Array.from(document.querySelectorAll('script[src]'))
    .map((s) => s.getAttribute('src').split('?')[0]);
  const idx = (m) => srcs.findIndex((s) => s.indexOf(m) >= 0);
  return {
    policyBeforeApp: idx('fullscreen-policy.js') >= 0 &&
      idx('fullscreen-policy.js') < idx('/web/app.js'),
    tgInitLast: idx('telegram-init.js') === srcs.length - 1,
  };
})()
"""

ANDROID_PORTRAIT = dict(
    platform="android", hasBoolean=True, isFullscreen=False,
    stableHeight=788, viewportHeight=844,
    safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
    contentSafeAreaInset={"top": 36, "bottom": 0, "left": 0, "right": 0})


def new_page(browser, cfg, sdk_js, viewport, me=None, overrides=None):
    ctx = browser.new_context(
        viewport=viewport, device_scale_factor=2,
        locale="ru-RU")
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception:  # noqa: BLE001 — среда без clipboard-API
        pass
    page = ctx.new_page()
    page.route("**/static/vendor/telegram-web-app.js",
               lambda route: route.fulfill(
                   status=200, content_type="application/javascript",
                   body=sdk_js))
    page.route("**/api/**", _api_handler_factory(me, overrides))
    page.set_viewport_size(viewport)
    page.goto(BASE_URL + "/#/", wait_until="domcontentloaded", timeout=30000)
    return ctx, page


def wait_ready(page, want_btn=True, timeout=20000):
    if want_btn:
        page.wait_for_selector(".header-fs-btn", state="attached",
                               timeout=timeout)
    else:
        page.wait_for_selector("header.header-sticky", state="visible",
                               timeout=timeout)
        page.wait_for_timeout(600)   # политика/зеркало успевают применить слот
    page.wait_for_timeout(400)


def scenario_android_inline(browser, shots):
    """S1: android, csa.top=36 → inline-кнопка под нативной зоной; ack-цикл;
    геометрия rect-пересечений (нативные зоны / контент шапки)."""
    c = Check("S1_android_inline")
    cfg = dict(ANDROID_PORTRAIT, nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    order = page.evaluate(SCRIPT_ORDER_JS)
    c.ok(order["policyBeforeApp"], "fullscreen-policy.js загружен до app.js")
    c.ok(order["tgInitLast"], "telegram-init.js остаётся последним")
    p = page.evaluate(PROBE_FS)
    c.ok(p["btnPresent"] and p["posFixed"] is False,
         "кнопка видима и в потоке row A (не fixed)")
    c.ok(not p["hiddenClass"] and not p["fsReason"], "hidden-маркеров нет")
    c.ok(p["rect"]["w"] >= 44 and p["rect"]["h"] >= 44,
         "hit-target >= 44x44 (факт %sx%s)" % (p["rect"]["w"], p["rect"]["h"]))
    c.ok(16 <= p["iconRect"]["w"] <= 24,
         "иконка 16–24px (факт %s)" % p["iconRect"]["w"])
    c.ok(p["rect"]["y"] >= p["bandTop"],
         "кнопка ниже нативной зоны: y=%s >= band=%s" % (p["rect"]["y"], p["bandTop"]))
    c.ok(p["btnXStripArea"] == 0,
         "пересечение с мок-зоной нативных кнопок = 0 (факт %s px^2)"
         % p["btnXStripArea"])
    c.ok(all(a == 0 for a in p["btnXContentAreas"]),
         "кнопка не перекрывает контент шапки (площади %s)" % p["btnXContentAreas"])
    c.ok(p["btnBeforeContent"] in (None, "none"),
         "стеклянной подложки ::before нет (факт content=%r)" % p["btnBeforeContent"])
    c.ok(p["btnBackdrop"] in (None, "none"),
         "декоративного размытия у кнопки нет (факт %r)" % p["btnBackdrop"])
    c.ok("header-fs-btn" not in (p["interceptTopRight"] or ""),
         "зона native ⋮/✕ (верхняя полоса) не перехвачена web-кнопкой")
    c.ok("header-fs-btn" not in (p["interceptTopLeft"] or ""),
         "верхний левый угол не перехвачен web-кнопкой")
    c.ok(p["headerPadTop"] >= p["bandTop"],
         "шапка начинается под нативной зоной (padding-top=%s >= band=%s)"
         % (p["headerPadTop"], p["bandTop"]))
    c.ok(p["ariaLabel"] == "На весь экран" and p["title"] == "На весь экран",
         "aria по ACK-состоянию: «На весь экран»")
    c.ok(p["ariaPressed"] == "false", "aria-pressed=false вне fullscreen")
    c.ok(not p["fsStripInDom"], "диагностического стрипа в UI нет (FS-HOTFIX)")
    page.screenshot(path=os.path.join(shots, "S1_android_inline_390.png"))
    # tap → request ровно 1 → ack
    page.click(".header-fs-btn")
    page.wait_for_timeout(120)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls.count("requestFullscreen") == 1, "первый тап = 1 requestFullscreen")
    page.evaluate("window.__tma.isFullscreen = true; window.__tma.__emit('fullscreenChanged')")
    page.wait_for_timeout(250)
    p = page.evaluate(PROBE_FS)
    c.ok(p["ariaPressed"] == "true", "после ack aria-pressed=true")
    c.ok(p["title"] == "Выйти из полноэкранного режима", "title → «Выйти из…»")
    c.ok(p["shellFullscreen"] is True, ".app-shell получил fullscreen-mode")
    c.ok(p["btnPresent"] and p["btnXStripArea"] == 0,
         "в fullscreen кнопка остаётся вне нативной зоны")
    page.screenshot(path=os.path.join(shots, "S1_android_inline_fullscreen_390.png"))
    # tap → exit → ack
    page.click(".header-fs-btn")
    page.wait_for_timeout(120)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls.count("exitFullscreen") == 1, "второй тап = exitFullscreen")
    page.evaluate("window.__tma.isFullscreen = false; window.__tma.__emit('fullscreenChanged')")
    page.wait_for_timeout(250)
    p = page.evaluate(PROBE_FS)
    c.ok(p["ariaPressed"] == "false" and p["title"] == "На весь экран",
         "после exit-ack кнопка вернулась к «На весь экран»")
    c.ok(p["btnPresent"], "после выхода из fullscreen кнопка НЕ исчезла")
    page.screenshot(path=os.path.join(shots, "S1_after_exit_390.png"))
    ctx.close()
    return c, p


def scenario_windowed_zero_insets(browser, shots):
    """S2: windowed — csa.top=0 → inline; плюс случай «системная safe area +
    Telegram-зона» (safe=24, csa=36, как на реальном Android): кнопка обязана
    быть ниже ПОЛНОЙ нативной зоны (это и был дефект «частично перекрыта»);
    ширины 320/390."""
    c = Check("S2_windowed_inline")
    cases = [
        ("320", 320, 700, {"top": 0, "bottom": 0, "left": 0, "right": 0},
         {"top": 0, "bottom": 0, "left": 0, "right": 0}),
        ("390", 390, 844, {"top": 0, "bottom": 0, "left": 0, "right": 0},
         {"top": 0, "bottom": 0, "left": 0, "right": 0}),
        # дефект «кастомная кнопка под нативными, частично перекрыта»:
        # системная safe area (статус-бар) + Telegram-зона (его header)
        ("390+insets", 390, 844, {"top": 24, "bottom": 0, "left": 0, "right": 0},
         {"top": 36, "bottom": 0, "left": 0, "right": 0}),
    ]
    for tag, w, h, sa, csa in cases:
        cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
                   stableHeight=h - 56, viewportHeight=h,
                   safeAreaInset=sa, contentSafeAreaInset=csa,
                   nativeStrip=True)
        ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": w, "height": h})
        wait_ready(page)
        p = page.evaluate(PROBE_FS)
        c.ok(p["btnPresent"] and not p["hiddenClass"], "%s: кнопка видима inline" % tag)
        c.ok(p["posFixed"] is False, "%s: inline — в потоке row A (не fixed)" % tag)
        c.ok(not p["hOverflow"], "%s: нет горизонтального overflow (%s<=%s)"
             % (tag, p["scrollWidth"], p["innerWidth"]))
        c.ok(p["rect"]["w"] >= 44 and p["rect"]["h"] >= 44,
             "%s: inline hit >= 44x44 (%sx%s)" % (tag, p["rect"]["w"], p["rect"]["h"]))
        c.ok(p["rect"]["y"] >= p["bandTop"],
             "%s: y=%s >= полная нативная зона %s" % (tag, p["rect"]["y"], p["bandTop"]))
        c.ok(p["btnXStripArea"] == 0, "%s: нативная зона не пересечена" % tag)
        c.ok(all(a == 0 for a in p["btnXContentAreas"]),
             "%s: контент шапки не перекрыт (%s)" % (tag, p["btnXContentAreas"]))
        page.screenshot(path=os.path.join(shots, "S2_inline_%s.png" % tag))
        ctx.close()
    return c, {}


def scenario_tdesktop(browser, shots):
    """S3: tdesktop — FS-HOTFIX: кнопка ВИДИМА (работающий переключатель),
    никаких авто-вызовов SDK и UI-заглушек."""
    c = Check("S3_tdesktop_visible")
    cfg = dict(platform="tdesktop", hasBoolean=True, isFullscreen=False,
               stableHeight=700, viewportHeight=768,
               safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
               contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0,
                                     "right": 0},
               nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 1024, "height": 768})
    wait_ready(page, want_btn=True)
    p = page.evaluate(PROBE_FS)
    c.ok(p["btnPresent"], "tdesktop: кнопка ЕСТЬ (FS-HOTFIX 18.10)")
    c.ok(not p["hiddenClass"] and not p["fsReason"],
         "tdesktop: hidden-маркеров/причин-заглушек нет")
    c.ok(p["policyExplain"]["code"] == "",
         "tdesktop: explain() не выдумывает причину")
    c.ok(not p["fsStripInDom"], "tdesktop: диагностического стрипа в UI нет")
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [], "tdesktop: авто-вызовов fullscreen API на старте нет")
    page.click(".header-fs-btn")
    page.wait_for_timeout(150)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == ["requestFullscreen"],
         "tdesktop: тап по кнопке = реальный requestFullscreen (факт %s)" % calls)
    page.screenshot(path=os.path.join(shots, "S3_tdesktop_visible_1024.png"))
    ctx.close()
    return c, p


def scenario_no_telegram(browser, shots):
    """S4: stand-alone браузер без window.Telegram → hidden (U07.3c)."""
    c = Check("S4_no_telegram")
    ctx, page = new_page(browser, None, NO_SDK_JS, {"width": 1280, "height": 800})
    wait_ready(page, want_btn=False, timeout=25000)
    p = page.evaluate(PROBE_FS)
    c.ok(not p["btnPresent"], "вне TG кнопка не вводит в заблуждение (hidden)")
    c.ok(p["fsReason"] == "no_telegram_context", "data-fs-reason=no_telegram_context")
    c.ok(not p["fsStripInDom"], "вне TG поясняющих блоков не добавлено")
    page.screenshot(path=os.path.join(shots, "S4_standalone_hidden_1280.png"))
    ctx.close()
    return c, p


def scenario_ack_flows(browser, shots):
    """S5: ALREADY_FULLSCREEN / UNSUPPORTED / timeout / pending-conflict /
       SDK без boolean (без инверсии)."""
    c = Check("S5_ack_flows")
    cfg = dict(ANDROID_PORTRAIT)

    # 5a ALREADY_FULLSCREEN: факт из SDK, кнопка = выход, БЕЗ второго request.
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    page.click(".header-fs-btn")
    page.evaluate("window.__tma.isFullscreen = true; "
                  "window.__tma.__emit('fullscreenFailed', { error_code: 'ALREADY_FULLSCREEN' })")
    page.wait_for_timeout(250)
    p = page.evaluate(PROBE_FS)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls.count("requestFullscreen") == 1, "5a ALREADY: второго request нет")
    c.ok(p["ariaPressed"] == "true" and p["title"] == "Выйти из полноэкранного режима",
         "5a ALREADY: кнопка = выход по факту SDK")
    c.ok(not p["toasts"] or all("Уже в полноэкранном" not in t for t in p["toasts"]),
         "5a ALREADY: без ложного сообщения (факт подтверждён — это не ошибка)")
    ctx.close()

    # 5b UNSUPPORTED: прежнее состояние + тост с причиной + retry.
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    page.click(".header-fs-btn")
    page.evaluate("window.__tma.__emit('fullscreenFailed', { error_code: 'UNSUPPORTED' })")
    page.wait_for_timeout(250)
    p = page.evaluate(PROBE_FS)
    c.ok(p["ariaPressed"] == "false" and p["title"] == "На весь экран",
         "5b UNSUPPORTED: состояние прежнее")
    c.ok(any("Полноэкранный режим" in t for t in p["toasts"]),
         "5b UNSUPPORTED: тост с причиной (не молчание): %s" % p["toasts"])
    page.screenshot(path=os.path.join(shots, "S5_unsupported_toast_390.png"))
    page.click(".header-fs-btn")
    page.wait_for_timeout(120)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls.count("requestFullscreen") == 2, "5b: после fail повторный тап возможен")
    ctx.close()

    # 5c ack-таймаут: pending снят, факт НЕ инвертирован.
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    page.evaluate("window.__FullscreenPolicy.setAckTimeoutMs(250)")
    page.click(".header-fs-btn")
    page.wait_for_timeout(600)
    p = page.evaluate(PROBE_FS)
    c.ok(p["ariaPressed"] == "false" and p["title"] == "На весь экран",
         "5c timeout: без инверсии факта")
    c.ok(any("не подтвердил" in t for t in p["toasts"]),
         "5c timeout: тост о таймауте: %s" % p["toasts"])
    pending = page.evaluate("window.__FullscreenPolicy.state().requestPending")
    c.ok(pending is False, "5c timeout: pending снят")
    ctx.close()

    # 5d pending-conflict: два быстрых тапа = один запрос.
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    page.evaluate("window.__FullscreenPolicy.setAckTimeoutMs(3000)")
    page.click(".header-fs-btn")
    page.click(".header-fs-btn", force=True)
    page.wait_for_timeout(150)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls.count("requestFullscreen") == 1,
         "5d: повторный тап при pending игнорируется (1 запрос)")
    ctx.close()

    # 5e SDK без boolean isFullscreen: инверсии нет (U07.1c).
    cfg_nb = dict(cfg, hasBoolean=False)
    ctx, page = new_page(browser, cfg_nb, mock_sdk_js(cfg_nb), {"width": 390, "height": 844})
    wait_ready(page)
    page.click(".header-fs-btn")
    page.evaluate("window.__tma.__emit('fullscreenChanged')")
    page.wait_for_timeout(250)
    p = page.evaluate(PROBE_FS)
    c.ok(p["ariaPressed"] is None, "5e: без boolean aria-pressed не выставляется")
    c.ok(p["title"] == "На весь экран", "5e: без ack-факта кнопка НЕ «выход»")
    c.ok(p["shellFullscreen"] is False, "5e: fullscreen-mode не включён угадыванием")
    ctx.close()
    return c, {}


def scenario_launch_fullscreen(browser, shots):
    """S6/S7: Launch Mode=Fullscreen — android и tdesktop (FS-HOTFIX: без
    авто-exit, кнопка выхода сразу)."""
    c = Check("S6S7_launch_fullscreen")
    cfg = dict(platform="android", hasBoolean=True, isFullscreen=True,
               stableHeight=788, viewportHeight=844,
               safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
               contentSafeAreaInset={"top": 36, "bottom": 0, "left": 0,
                                     "right": 0},
               nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [], "S6 launch-fullscreen: ВТОРОГО requestFullscreen на старте нет")
    p = page.evaluate(PROBE_FS)
    c.ok(p["title"] == "Выйти из полноэкранного режима" and p["ariaPressed"] == "true",
         "S6: сразу рабочая кнопка ВЫХОДА")
    c.ok(p["btnXStripArea"] == 0, "S6: кнопка вне нативной зоны")
    page.screenshot(path=os.path.join(shots, "S6_launch_fullscreen_android_390.png"))
    ctx.close()

    cfg2 = dict(platform="tdesktop", hasBoolean=True, isFullscreen=True,
                stableHeight=700, viewportHeight=768,
                safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
                contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0,
                                      "right": 0},
                nativeStrip=True)
    ctx, page = new_page(browser, cfg2, mock_sdk_js(cfg2), {"width": 1024, "height": 768})
    wait_ready(page, want_btn=True)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [],
         "S7 tdesktop-launch: НИКАКИХ авто-выходов (FS-HOTFIX снял soft-exit)")
    p = page.evaluate(PROBE_FS)
    c.ok(p["btnPresent"], "S7: кнопка видима (никаких заглушек)")
    c.ok(p["title"] == "Выйти из полноэкранного режима",
         "S7: кнопка сразу = выход (клиент остаётся в запрошенном режиме)")
    page.evaluate("window.__tma.__emit('fullscreenChanged')")  # хост подтверждает
    page.wait_for_timeout(150)
    page.click(".header-fs-btn")
    page.wait_for_timeout(150)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == ["exitFullscreen"], "S7: выход по кнопке = реальный exitFullscreen")
    page.screenshot(path=os.path.join(shots, "S7_tdesktop_launch_fullscreen_1024.png"))
    ctx.close()
    return c, {}


def scenario_widths(browser, shots):
    """S8: android 320/390/667×375 — геометрия (портрет/ландшафт) в отчёт."""
    c = Check("S8_widths")
    rows = []
    for w, h, tag, insets in (
            (320, 700, "320", {"top": 36, "bottom": 0, "left": 0, "right": 0}),
            (390, 844, "390", {"top": 36, "bottom": 0, "left": 0, "right": 0}),
            (667, 375, "667x375", {"top": 24, "bottom": 0, "left": 44, "right": 44})):
        cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
                   stableHeight=max(300, h - 56), viewportHeight=h,
                   safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
                   contentSafeAreaInset=insets, nativeStrip=True)
        ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": w, "height": h})
        wait_ready(page)
        p = page.evaluate(PROBE_FS)
        c.ok(p["btnPresent"] and p["posFixed"] is False, "%s: inline-кнопка" % tag)
        c.ok(p["rect"]["y"] >= p["bandTop"], "%s: y=%s >= band=%s"
             % (tag, p["rect"]["y"], p["bandTop"]))
        c.ok(p["rect"]["w"] >= 44 and p["rect"]["h"] >= 44,
             "%s: hit %sx%s" % (tag, p["rect"]["w"], p["rect"]["h"]))
        c.ok(not p["hOverflow"], "%s: без h-overflow" % tag)
        c.ok(p["btnXStripArea"] == 0, "%s: нативная зона не пересечена" % tag)
        c.ok(all(a == 0 for a in p["btnXContentAreas"]),
             "%s: контент шапки не перекрыт" % tag)
        rows.append({"width": w, "height": h, "btn": p["rect"],
                     "icon": p["iconRect"], "header": p["headerRect"],
                     "headerPadTop": p["headerPadTop"], "band": p["bandTop"]})
        page.screenshot(path=os.path.join(shots, "S8_inline_%s.png" % tag.replace("x", "_")))
        ctx.close()
    return c, {"rows": rows}


def scenario_state_preservation(browser, shots):
    """S9: мульти-переходы fullscreen↔window, поворот — без перезагрузки и
    без потери раздела/чата/незакрытого ввода; кнопка не исчезает."""
    c = Check("S9_state_preservation")
    cfg = dict(ANDROID_PORTRAIT, nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    page.evaluate("window.__fsKeepMarker = 'keep-42'")
    # незакрытый ввод: открыть селектор чата и набрать текст в поиске
    page.click(".scope-trigger")
    page.wait_for_timeout(200)
    page.fill(".scope-panel input[type=search]", "PERM")
    page.wait_for_timeout(150)
    before = page.evaluate(STATE_PROBE)
    c.ok(before["dropdownOpen"] and before["searchValue"] == "PERM",
         "подготовка: ввод в селекторе виден (%s)" % before["searchValue"])
    # 3 JS-транзиции fullscreen (без клика — клик по кнопке закрыл бы
    # дропдаун как outside click, это поведение не относится к fullscreen)
    for i in range(3):
        page.evaluate("""
          (() => {
            const wa = window.__tma;
            if (window.__FullscreenPolicy.state().actualFullscreen !== true) {
              wa.isFullscreen = true; wa.__emit('fullscreenChanged');
            } else {
              wa.isFullscreen = false; wa.__emit('fullscreenChanged');
            }
          })()
        """)
        page.wait_for_timeout(200)
    after_js = page.evaluate(STATE_PROBE)
    c.ok(after_js["hash"] == before["hash"], "JS-транзиции: раздел (hash) сохранён")
    c.ok(after_js["activeNav"] == before["activeNav"], "JS-транзиции: активный раздел сохранён")
    c.ok(after_js["scopeText"] == before["scopeText"], "JS-транзиции: выбранный чат сохранён")
    c.ok(after_js["keepMarker"] == "keep-42", "JS-транзиции: документ не перезагружен")
    c.ok(after_js["searchValue"] == "PERM" and after_js["dropdownOpen"],
         "JS-транзиции: незакрытый ввод в селекторе сохранён (%s)" % after_js["searchValue"])
    # закрыть дропдаун (Esc) и прогнать 3 РЕАЛЬНЫХ клика по кнопке
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    for i in range(3):
        page.click(".header-fs-btn")
        page.wait_for_timeout(120)
        calls = page.evaluate("window.__tma.__calls")
        is_fs = page.evaluate("window.__FullscreenPolicy.state().actualFullscreen")
        page.evaluate("window.__tma.isFullscreen = " +
                      ("false" if is_fs is True else "true") +
                      "; window.__tma.__emit('fullscreenChanged')")
        page.wait_for_timeout(220)
        probe = page.evaluate(PROBE_FS)
        c.ok(probe["btnPresent"],
             "клик %d: кнопка остаётся видимой (в т.ч. после выхода из fullscreen)" % (i + 1))
    after_click = page.evaluate(STATE_PROBE)
    c.ok(after_click["hash"] == before["hash"], "клики: раздел сохранён")
    c.ok(after_click["activeNav"] == before["activeNav"], "клики: активный раздел сохранён")
    c.ok(after_click["scopeText"] == before["scopeText"], "клики: чат сохранён")
    c.ok(after_click["keepMarker"] == "keep-42", "клики: без перезагрузки документа")
    c.ok(after_click["navEntries"] == 1, "клики: одна навигационная запись (SPA)")
    # поворот: 390x844 → 667x375 → обратно, состояние сохраняется
    page.set_viewport_size({"width": 667, "height": 375})
    page.evaluate("window.__tma.contentSafeAreaInset = { top: 24, bottom: 0, left: 44, right: 44 };"
                  "window.__tma.__emit('viewportChanged');"
                  "window.__tma.__emit('contentSafeAreaChanged')")
    page.wait_for_timeout(350)
    land = page.evaluate(PROBE_FS)
    c.ok(land["btnPresent"] and not land["hOverflow"],
         "ландшафт: кнопка видима, без h-overflow")
    c.ok(land["rect"]["y"] >= land["bandTop"],
         "ландшафт: кнопка ниже нативной зоны (y=%s >= %s)"
         % (land["rect"]["y"], land["bandTop"]))
    c.ok(land["headerRect"]["h"] <= 120,
         "ландшафт: шапка компактна (h=%s)" % (land["headerRect"]["h"]))
    page.screenshot(path=os.path.join(shots, "S9_landscape_667_375.png"))
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("window.__tma.contentSafeAreaInset = { top: 36, bottom: 0, left: 0, right: 0 };"
                  "window.__tma.__emit('viewportChanged')")
    page.wait_for_timeout(300)
    back = page.evaluate(PROBE_FS)
    state = page.evaluate(STATE_PROBE)
    c.ok(back["btnPresent"] and back["rect"]["y"] >= back["bandTop"],
         "обратный поворот: геометрия пересчитана, кнопка доступна")
    c.ok(state["keepMarker"] == "keep-42" and state["hash"] == before["hash"],
         "поворот: состояние и раздел сохранены, без перезагрузки")
    c.ok(state["scopeText"] == before["scopeText"], "поворот: чат сохранён")
    ctx.close()
    return c, {"before": before, "after_js": after_js, "after_click": after_click}


def scenario_logo_freed_space(browser, shots):
    """S10 (§7 №8): скрытие логотипа AdminBot освобождает пространство без
    нарушения соседних элементов — селектор получает ширину, кнопка ⛶
    остаётся на месте, шапка не растёт, пересечений/overflow нет."""
    c = Check("S10_logo_freed_space")
    cfg = dict(ANDROID_PORTRAIT, nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    p_hidden = page.evaluate(PROBE_FS)
    c.ok(p_hidden["brandPresent"],
         "логотип остаётся в разметке (слот сохранён, скрыт стилем)")
    c.ok(p_hidden["brandDisplay"] and p_hidden["brandDisplay"].endswith("/hidden"),
         "mobile-shell: логотип скрыт (директива 18.10), факт %s"
         % p_hidden["brandDisplay"])
    c.ok(p_hidden["scopeRect"] and p_hidden["rect"],
         "селектор чата и кнопка ⛶ обе на месте")
    # вертикальное перекрытие (одна строка row A) и горизонтальная непересечённость
    same_row = (p_hidden["scopeRect"]["bottom"] > p_hidden["rect"]["y"] and
                p_hidden["rect"]["bottom"] > p_hidden["scopeRect"]["y"])
    c.ok(same_row, "селектор и ⛶ в ОДНОЙ строке row A (без новой строки)")
    c.ok(p_hidden["scopeRect"]["right"] <= p_hidden["rect"]["x"],
         "селектор и ⛶ не пересекаются по горизонтали")
    # ASAP-UI-02 §2.2: визуального бренда Adminbot в UI нет вовсе — раньше
    # здесь принудительно показывался `.mobile-brand`; теперь проверяем его
    # фактическое отсутствие (пустых слотов/заглушек тоже нет).
    c.ok(page.evaluate(
        "document.querySelectorAll('.mobile-brand, .sidebar-brand').length") == 0,
        "логотипа Adminbot нет в UI (ASAP-UI-02 §2.2)")
    c.ok(page.evaluate(
        "document.querySelector('.sidebar-brand-title') === null"),
        "слово-марка Adminbot отсутствует и в sidebar")
    c.ok(p_shown["headerRect"]["h"] == p_hidden["headerRect"]["h"] ==
         p_restore["headerRect"]["h"],
         "высота шапки не зависит от логотипа (%s)" % p_hidden["headerRect"]["h"])
    c.ok(not p_shown["hOverflow"] and not p_hidden["hOverflow"],
         "нет горизонтального overflow в обоих состояниях")
    page.screenshot(path=os.path.join(shots, "S10_logo_hidden_390.png"))
    ctx.close()
    return c, {"hidden": {"scope": p_hidden["scopeRect"], "btn": p_hidden["rect"],
                          "header": p_hidden["headerRect"]},
               "shown": {"scope": p_shown["scopeRect"], "btn": p_shown["rect"]}}


LONG_CHAT_TITLE = ("Очень длинное название рабочего чата проекта PERMsoc с "
                   "дополнительным уточнением, номерами 1234567890 и "
                   "окончанием, которое заведомо не влезает в шапку")

GLOBAL_OPT_JS = """
(() => {
  const opts = Array.from(document.querySelectorAll('.scope-panel .scope-option'));
  const t = opts.find((o) => o.textContent.indexOf('Весь бот') >= 0);
  if (t) t.click();
  return !!t;
})()
"""

CHAT_OPT_JS = """
(() => {
  const opts = Array.from(document.querySelectorAll('.scope-panel .scope-option'));
  const t = opts.find((o) => o.textContent.indexOf('Очень длинное название') >= 0);
  if (t) t.click();
  return !!t;
})()
"""


def scenario_long_title_scope(browser, shots):
    """S11 (§7 №12): длинное имя чата и состояния GLOBAL/ЧАТ не ломают
    положение кнопки ⛶ (ellipsis сохранён, выбор не теряется)."""
    c = Check("S11_long_title_scope")
    cfg = dict(ANDROID_PORTRAIT, nativeStrip=True)
    overrides = {"/api/access/chats": [
        {"chat_id": -100999888777, "title": LONG_CHAT_TITLE,
         "is_dm": False, "photo_file_id": None, "access": "admin"}]}
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844},
                         overrides=overrides)
    wait_ready(page)
    base = page.evaluate(PROBE_FS)
    c.ok(base["btnPresent"], "кнопка ⛶ присутствует с длинным именем чата")
    c.ok(base["scopeBadge"] in ("ЧАТ", "GLOBAL", "ЛС"),
         "индикатор области читается (%s)" % base["scopeBadge"])
    c.ok(base["scopeTitleSpanTruncated"] is True,
         "длинное имя чата визуально сокращено (ellipsis, scrollWidth > clientWidth)")
    c.ok(not base["hOverflow"], "нет горизонтального overflow (длинное имя)")
    c.ok(base["scopeRect"]["right"] <= base["rect"]["x"],
         "длинное имя не залезает под кнопку ⛶")
    # GLOBAL: выбрать «Весь бот» (состояние global)
    page.click(".scope-trigger")
    page.wait_for_timeout(200)
    page.evaluate(GLOBAL_OPT_JS)
    page.wait_for_timeout(350)
    g = page.evaluate(PROBE_FS)
    c.ok(g["scopeBadge"] == "GLOBAL",
         "переключение в GLOBAL: бейдж=GLOBAL (факт %s)" % g["scopeBadge"])
    c.ok(abs(g["rect"]["x"] - base["rect"]["x"]) <= 1 and
         g["rect"]["y"] == base["rect"]["y"] and
         g["rect"]["w"] == base["rect"]["w"],
         "GLOBAL не смещает кнопку ⛶ (x/y %s/%s)" % (g["rect"]["x"], g["rect"]["y"]))
    c.ok(not g["hOverflow"], "GLOBAL: без h-overflow")
    # обратно в ЧАТ (выбор не теряется)
    page.click(".scope-trigger")
    page.wait_for_timeout(200)
    page.evaluate(CHAT_OPT_JS)
    page.wait_for_timeout(350)
    b2 = page.evaluate(PROBE_FS)
    c.ok(b2["scopeBadge"] == "ЧАТ",
         "возврат в чат: бейдж=ЧАТ (факт %s)" % b2["scopeBadge"])
    c.ok(abs(b2["rect"]["x"] - base["rect"]["x"]) <= 1 and
         b2["rect"]["y"] == base["rect"]["y"],
         "возврат в чат не смещает кнопку ⛶")
    c.ok(b2["scopeTitleSpanTruncated"] is True,
         "выбор длинного чата сохранён (ellipsis снова активен)")
    page.screenshot(path=os.path.join(shots, "S11_long_title_390.png"))
    ctx.close()
    return c, {"base": base["rect"], "global": g["rect"], "chat": b2["rect"],
               "badges": [base["scopeBadge"], g["scopeBadge"], b2["scopeBadge"]]}


DIAG_PROBE_JS = """
(() => {
  const panel = document.querySelector('[data-fs-geom-diag]');
  const txt = document.querySelector('[data-fs-geom-diag-text]');
  const overlay = document.querySelector('[data-fs-safe-overlay]');
  const band = document.querySelector('.fs-safe-overlay__band');
  return {
    entryPresent: !!document.querySelector('[data-fs-geom-diag-entry]'),
    panelPresent: !!panel,
    text: txt ? txt.textContent : null,
    overlayPresent: !!overlay,
    overlayPointer: overlay ? getComputedStyle(overlay).pointerEvents : null,
    bandHeight: band ? Math.round(band.getBoundingClientRect().height) : null,
    copyBtn: !!document.querySelector('[data-fs-geom-diag-copy]'),
    closeBtn: !!document.querySelector('[data-fs-geom-diag-close]'),
    toasts: Array.from(document.querySelectorAll('.toast-text'))
      .map((t) => t.textContent.trim()).slice(0, 3),
  };
})()
"""


def scenario_admin_geom_diag(browser, shots):
    """S12 (§8): admin-диагностика геометрии — off by default, admin-гейт,
    компактный снимок фактов, копирование одним действием, без секретов,
    оверлей границ по кнопке."""
    c = Check("S12_admin_geom_diag")
    cfg = dict(ANDROID_PORTRAIT, nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    d0 = page.evaluate(DIAG_PROBE_JS)
    c.ok(not d0["panelPresent"] and not d0["overlayPresent"],
         "по умолчанию: панели и оверлея нет (места в обычном UI не занимает)")
    # вход — только из меню «Ещё»
    page.click("[data-more-trigger]")
    page.wait_for_timeout(250)
    d1 = page.evaluate(DIAG_PROBE_JS)
    c.ok(d1["entryPresent"], "admin: вход «Диагностика геометрии ⛶» в меню «Ещё»")
    page.click("[data-fs-geom-diag-entry]")
    page.wait_for_timeout(350)
    d = page.evaluate(DIAG_PROBE_JS)
    c.ok(d["panelPresent"] and d["text"] and len(d["text"]) > 200,
         "панель открыта, снимок собран (%d символов)" % len(d["text"] or ""))
    text = d["text"] or ""
    for needle, label in (
            ("platform:", "платформа"),
            ("SDK:", "версия SDK"),
            ("isFullscreen:", "isFullscreen"),
            ("viewport:", "viewport"),
            ("stableHeight:", "стабильная высота"),
            ("safeAreaInset:", "safeAreaInset"),
            ("contentSafeAreaInset:", "contentSafeAreaInset"),
            ("button ⛶ rect:", "rect кнопки"),
            ("toolbar(header) rect:", "rect тулбара"),
            ("layout:", "layout-режим"),
            ("logo (Adminbot brand):", "наличие логотипа"),
            ("fullscreen API:", "поддержка API"),
            ("last switch:", "результат последнего переключения")):
        c.ok(needle in text, "снимок: %s (%s)" % (label, needle))
    for secret in ("initData", "token", "Bearer", "tgWebApp", "Audit Chat",
                   "1001234567890", "activeChatId"):
        c.ok(secret not in text, "снимок без «%s» (приватность §8)" % secret)
    c.ok(d["copyBtn"] and d["closeBtn"], "кнопки «Скопировать»/«Закрыть» есть")
    # копирование одним действием
    page.click("[data-fs-geom-diag-copy]")
    page.wait_for_timeout(300)
    clip = ""
    try:
        clip = page.evaluate("navigator.clipboard.readText()")
    except Exception:  # noqa: BLE001
        clip = ""
    d2 = page.evaluate(DIAG_PROBE_JS)
    c.ok(("Скопировано" in " ".join(d2["toasts"])) or clip == text,
         "копирование одним действием (тост/clipboard): %s / %d симв."
         % (d2["toasts"], len(clip or "")))
    # буфер сверяем с ТЕКУЩИМ снимком панели (после копирования), CRLF→LF
    text_now = d2["text"] or ""
    clip_norm = (clip or "").replace("\r\n", "\n")
    c.ok(not clip or clip_norm == text_now,
         "в буфере ровно снимок, без лишнего (clip=%d симв., panel=%d симв.; "
         "первое расхождение: %r)" % (len(clip or ""), len(text_now),
                                      _first_diff(clip_norm, text_now)))
    # оверлей вычисленных границ (§8, опционально)
    page.click("[data-fs-geom-diag-overlay]")
    page.wait_for_timeout(250)
    d3 = page.evaluate(DIAG_PROBE_JS)
    c.ok(d3["overlayPresent"] and d3["bandHeight"] == 36,
         "оверлей границ рисует вычисленную зону (band=%s px)" % d3["bandHeight"])
    c.ok(d3["overlayPointer"] == "none",
         "оверлей не перехватывает тапы (pointer-events: none)")
    page.screenshot(path=os.path.join(shots, "S12_admin_geom_diag_390.png"))
    page.click("[data-fs-geom-diag-overlay]")
    page.wait_for_timeout(200)
    c.ok(not page.evaluate(DIAG_PROBE_JS)["overlayPresent"],
         "оверлей выключается повторным нажатием")
    page.click("[data-fs-geom-diag-close]")
    page.wait_for_timeout(250)
    c.ok(not page.evaluate(DIAG_PROBE_JS)["panelPresent"],
         "панель закрывается (UI возвращается в обычный вид)")
    ctx.close()
    return c, {}


def scenario_non_admin_no_diag(browser, shots):
    """S13 (§8): вне admin-прав диагностики в UI нет вообще (панель и вход)."""
    c = Check("S13_non_admin_no_diag")
    me = json.loads(json.dumps(ME))
    me["role_name"] = "user"
    me["permissions"] = {}
    me["is_global_admin"] = False
    cfg = dict(ANDROID_PORTRAIT, nativeStrip=True)
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844},
                         me=me)
    wait_ready(page)
    d0 = page.evaluate(DIAG_PROBE_JS)
    c.ok(not d0["panelPresent"], "не-admin: панели нет по умолчанию")
    page.click("[data-more-trigger]")
    page.wait_for_timeout(250)
    d1 = page.evaluate(DIAG_PROBE_JS)
    c.ok(not d1["entryPresent"], "не-admin: входа «Диагностика геометрии» нет")
    c.ok(d1["panelPresent"] is False, "не-admin: панель не открывается")
    ctx.close()
    return c, {}


def main():
    from playwright.sync_api import sync_playwright
    httpd = _start_server()
    print("[w2-fs] server on %d" % PORT)
    scenarios = [scenario_android_inline, scenario_windowed_zero_insets,
                 scenario_tdesktop, scenario_no_telegram,
                 scenario_ack_flows, scenario_launch_fullscreen,
                 scenario_widths, scenario_state_preservation,
                 scenario_logo_freed_space, scenario_long_title_scope,
                 scenario_admin_geom_diag, scenario_non_admin_no_diag]
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in scenarios:
            try:
                c, extra = fn(browser, EVIDENCE)
                status = "PASS" if not c.failures else "FAIL"
                print("[w2-fs] %-24s %s (%d checks)" % (c.name, status, c.count))
                for f in c.failures:
                    print("    FAIL: %s" % f)
                results.append({"scenario": c.name, "status": status,
                                "checks": c.count, "failures": c.failures,
                                "extra": extra})
            except Exception as exc:  # noqa: BLE001
                print("[w2-fs] %-24s ERROR: %s" % (fn.__name__, exc))
                results.append({"scenario": fn.__name__, "status": "ERROR",
                                "error": str(exc)[:500]})
        browser.close()
    httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    failed = [r for r in results if r["status"] != "PASS"]
    print("[w2-fs] итог: %d/%d PASS, артефакты: %s"
          % (len(results) - len(failed), len(results), EVIDENCE))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
