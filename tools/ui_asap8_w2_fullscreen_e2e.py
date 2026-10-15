"""W2-FULLSCREEN (asap8-v6.3, U07/V06-prep) — Playwright-e2e слота кнопки ⛶.

Харнесс: локальный http-сервер + РЕАЛЬНЫЕ web/index.html + web/app.js +
web/static/fullscreen-policy.js. Telegram SDK НЕ стабится addInitScript'ом
(контракт w2 §4.2: реальный SDK sync в <head> и перетёр бы мок) —
`/static/vendor/telegram-web-app.js` перехватывается ROUTE-ом и отдаётся
управляемый мок (platform × capability × launch mode × insets, ручная
эмиссия fullscreenChanged/fullscreenFailed). `/api/*` — фейковые ответы
(без секретов/БД). Запускается поверх расширяемого харнесса
tools/ui_round1025_matrix.py (тот же сервер/стабы — новых стеков нет).

Проверяется (mock-only! VERIFIED_LIVE — только Wave 4 на реальных клиентах):
  * android csa.top=36 → слот float: хит ≥44×44, визуал 32px, кнопка ниже
    csa.top и у правого края; elementFromPoint в зонах нативных ⋮/✕ — не
    наша кнопка (нет перехвата);
  * csa.top=0 → честный fallback inline (в потоке row A);
  * tdesktop → кнопка скрыта (v-if), html.fs-hidden + data-fs-reason
    (U07.1a); stand-alone без Telegram → hidden (U07.3c);
  * ack-флоу: tap → requestFullscreen ровно 1 раз; fullscreenChanged →
    aria-pressed=true и title=«Выйти…»; ALREADY_FULLSCREEN → факт из SDK,
    кнопка=выход без второго request (U07.1d); UNSUPPORTED → состояние
    прежнее + тост с причиной; ack-таймаут снимает pending без инверсии
    факта; повторный тап при pending — один запрос (U07.1c/1d);
  * SDK без boolean isFullscreen → нет инверсии (legacy-дефект устранён);
  * Launch Mode=Fullscreen (android) → ВТОРОГО requestFullscreen нет,
    сразу рабочая кнопка выхода (U07.1e); tdesktop-launch → ровно один
    мягкий exitFullscreen, UI не даёт повторно попасть в ловушку;
  * ширины 320/390/667×375: без горизонтального overflow, геометрия в отчёте.

Запуск: .venv/Scripts/python.exe tools/ui_asap8_w2_fullscreen_e2e.py
Артефакты: plans/features/asap8-v6-3-live-correction/w2-evidence-fullscreen/
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
EVIDENCE = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",
                        "w2-evidence-fullscreen")
RAW = os.path.join(EVIDENCE, "_results.json")
os.makedirs(EVIDENCE, exist_ok=True)

BASE_URL = "http://127.0.0.1:%d" % PORT

ME = json.loads(json.dumps(M.ME_JSON))
ME["ui_flags"]["TOKEN_FLOW_NODEFLOW_ENABLED"] = False   # чужой known render-error
ME["ui_flags"]["UI_POLYGON_BG_ENABLED"] = False         # детерминированный фон


def mock_sdk_js(cfg):
    """Мок официального SDK: РОВНО те факты, что задаёт сценарий. Методы
    только фиксируют вызовы (эмуляция хоста); события — ручная эмиссия."""
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
  } catch (e) {}
})();
""" % json.dumps(cfg)


NO_SDK_JS = "/* stand-alone: SDK не загружается (симуляция прямого линка) */"


def _api_handler_factory():
    def handler(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(ME))
            return
        payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return handler


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


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
  const before = btn ? getComputedStyle(btn, '::before') : null;
  const de = document.documentElement;
  const header = document.querySelector('header.header-sticky');
  const hr = header ? header.getBoundingClientRect() : null;
  return {
    btnPresent: !!btn,
    rect: r ? { x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
                right: Math.round(r.right), bottom: Math.round(r.bottom) } : null,
    visual: before ? { w: parseFloat(before.width), h: parseFloat(before.height),
                       radius: before.borderRadius } : null,
    posFixed: btn ? getComputedStyle(btn).position === 'fixed' : null,
    ariaPressed: btn ? btn.getAttribute('aria-pressed') : null,
    ariaLabel: btn ? (btn.getAttribute('aria-label') || '') : '',
    title: btn ? (btn.getAttribute('title') || '') : '',
    slotFloatClass: de.classList.contains('fs-slot-float'),
    hiddenClass: de.classList.contains('fs-hidden'),
    fsReason: de.getAttribute('data-fs-reason'),
    shellFullscreen: (() => {
      const sh = document.querySelector('.app-shell');
      return sh ? sh.classList.contains('fullscreen-mode') : null;
    })(),
    scrollWidth: de.scrollWidth,
    innerWidth: window.innerWidth,
    hOverflow: de.scrollWidth > window.innerWidth + 1,
    headerRect: hr ? { y: Math.round(hr.y), h: Math.round(hr.height) } : null,
    headerPadTop: header ? parseFloat(getComputedStyle(header).paddingTop) : null,
    interceptTopRight: (() => {
      const el = document.elementFromPoint(window.innerWidth - 10, 18);
      return el ? (el.className || '').toString() + '#' + el.tagName : null;
    })(),
    interceptTopLeft: (() => {
      const el = document.elementFromPoint(24, 18);
      return el ? (el.className || '').toString() + '#' + el.tagName : null;
    })(),
    toasts: Array.from(document.querySelectorAll('.toast-text'))
      .map((t) => t.textContent.trim()).slice(0, 3),
  };
})()
"""

# Порядок загрузки скриптов (§1.3.4) — фиксируем один раз.
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


def new_page(browser, cfg, sdk_js, viewport):
    ctx = browser.new_context(
        viewport=viewport, device_scale_factor=2,
        locale="ru-RU")
    page = ctx.new_page()
    page.route("**/static/vendor/telegram-web-app.js",
               lambda route: route.fulfill(
                   status=200, content_type="application/javascript",
                   body=sdk_js))
    page.route("**/api/**", _api_handler_factory())
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


def scenario_android_float(browser, shots):
    """S1: android, csa.top=36 → float; полный ack-цикл; перехват ⋮/✕."""
    c = Check("S1_android_float")
    cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
               stableHeight=788, viewportHeight=844,
               safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
               contentSafeAreaInset={ "top": 36, "bottom": 0, "left": 0, "right": 0 })
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    order = page.evaluate(SCRIPT_ORDER_JS)
    c.ok(order["policyBeforeApp"], "fullscreen-policy.js загружен до app.js")
    c.ok(order["tgInitLast"], "telegram-init.js остаётся последним")
    p = page.evaluate(PROBE_FS)
    c.ok(p["slotFloatClass"], "html.fs-slot-float выставлен политикой")
    c.ok(not p["hiddenClass"] and not p["fsReason"], "hidden-маркеров нет")
    c.ok(p["btnPresent"] and p["posFixed"], "кнопка в float-режиме (position:fixed)")
    c.ok(p["rect"]["w"] >= 44 and p["rect"]["h"] >= 44,
         "hit-target >= 44x44 (факт %sx%s)" % (p["rect"]["w"], p["rect"]["h"]))
    c.ok(28 <= p["visual"]["w"] <= 34, "визуал 28–34px (факт %s)" % p["visual"]["w"])
    c.ok(p["rect"]["y"] >= 36, "кнопка начинается ниже csa.top=36 (y=%s)" % p["rect"]["y"])
    c.ok(p["rect"]["right"] >= p["innerWidth"] - 12,
         "кнопка у правого края (right=%s)" % p["rect"]["right"])
    c.ok("header-fs-btn" not in (p["interceptTopRight"] or ""),
         "зона native ⋮ (top-right, y=18) не перехвачена web-кнопкой")
    c.ok("header-fs-btn" not in (p["interceptTopLeft"] or ""),
         "зона native ✕ (top-left, y=18) не перехвачена web-кнопкой")
    c.ok(p["ariaLabel"] == "На весь экран" and p["title"] == "На весь экран",
         "aria по ACK-состоянию: «На весь экран»")
    c.ok(p["ariaPressed"] == "false", "aria-pressed=false вне fullscreen")
    c.ok((p["headerPadTop"] or 0) >= 36 + 50,
         "row A резерв: header padding-top >= csa+50 (факт %s)" % p["headerPadTop"])
    page.screenshot(path=os.path.join(shots, "S1_android_float_390.png"))
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
    c.ok(p["ariaLabel"] == "Выйти из полноэкранного режима", "aria-label → «Выйти из…»")
    c.ok(p["shellFullscreen"] is True, ".app-shell получил fullscreen-mode")
    page.screenshot(path=os.path.join(shots, "S1_android_float_fullscreen_390.png"))
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
    ctx.close()
    return c, p


def scenario_inline_fallback(browser, shots):
    """S2: csa.top=0 → честный fallback inline; ширины 320/390."""
    c = Check("S2_inline_fallback")
    for w, h, tag in ((320, 700, "320"), (390, 844, "390")):
        cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
                   stableHeight=h - 56, viewportHeight=h,
                   safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
                   contentSafeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 })
        ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": w, "height": h})
        wait_ready(page)
        p = page.evaluate(PROBE_FS)
        c.ok(not p["slotFloatClass"], "%s: csa.top=0 → НЕ float (inline)" % tag)
        c.ok(not p["hiddenClass"] and p["btnPresent"], "%s: кнопка видима inline" % tag)
        c.ok(p["posFixed"] is False, "%s: inline — в потоке row A (не fixed)" % tag)
        c.ok(not p["hOverflow"], "%s: нет горизонтального overflow (%s<=%s)"
             % (tag, p["scrollWidth"], p["innerWidth"]))
        c.ok(p["rect"]["w"] >= 44 and p["rect"]["h"] >= 44,
             "%s: inline hit >= 44x44 (%sx%s)" % (tag, p["rect"]["w"], p["rect"]["h"]))
        page.screenshot(path=os.path.join(shots, "S2_inline_%s.png" % tag))
        ctx.close()
    return c, {}


def scenario_tdesktop_hidden(browser, shots):
    """S3: tdesktop → hidden + честная причина (U07.1a)."""
    c = Check("S3_tdesktop_hidden")
    cfg = dict(platform="tdesktop", hasBoolean=True, isFullscreen=False,
               stableHeight=700, viewportHeight=768,
               safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
               contentSafeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 })
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 1024, "height": 768})
    wait_ready(page, want_btn=False)
    p = page.evaluate(PROBE_FS)
    c.ok(not p["btnPresent"], "tdesktop: кнопка НЕ рендерится (v-if)")
    c.ok(p["hiddenClass"], "html.fs-hidden выставлен")
    c.ok(p["fsReason"] == "tdesktop_disabled_until_e2e",
         "data-fs-reason=tdesktop_disabled_until_e2e")
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [], "tdesktop: никаких автоматических вызовов fullscreen API")
    page.screenshot(path=os.path.join(shots, "S3_tdesktop_hidden_1024.png"))
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
    page.screenshot(path=os.path.join(shots, "S4_standalone_hidden_1280.png"))
    ctx.close()
    return c, p


def scenario_ack_flows(browser, shots):
    """S5: ALREADY_FULLSCREEN / UNSUPPORTED / timeout / pending-conflict /
       SDK без boolean (без инверсии)."""
    c = Check("S5_ack_flows")

    # 5a ALREADY_FULLSCREEN: факт из SDK, кнопка = выход, БЕЗ второго request.
    cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
               stableHeight=788, viewportHeight=844,
               safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
               contentSafeAreaInset={ "top": 36, "bottom": 0, "left": 0, "right": 0 })
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
    """S6/S7: Launch Mode=Fullscreen — android и tdesktop (U07.1e)."""
    c = Check("S6S7_launch_fullscreen")
    cfg = dict(platform="android", hasBoolean=True, isFullscreen=True,
               stableHeight=788, viewportHeight=844,
               safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
               contentSafeAreaInset={ "top": 36, "bottom": 0, "left": 0, "right": 0 })
    ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": 390, "height": 844})
    wait_ready(page)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [], "S6 launch-fullscreen: ВТОРОГО requestFullscreen на старте нет")
    p = page.evaluate(PROBE_FS)
    c.ok(p["title"] == "Выйти из полноэкранного режима" and p["ariaPressed"] == "true",
         "S6: сразу рабочая кнопка ВЫХОДА")
    page.screenshot(path=os.path.join(shots, "S6_launch_fullscreen_android_390.png"))
    ctx.close()

    cfg2 = dict(platform="tdesktop", hasBoolean=True, isFullscreen=True,
                stableHeight=700, viewportHeight=768,
                safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
                contentSafeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 })
    ctx, page = new_page(browser, cfg2, mock_sdk_js(cfg2), {"width": 1024, "height": 768})
    wait_ready(page, want_btn=False)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == ["exitFullscreen"],
         "S7 tdesktop-launch: ровно ОДИН мягкий exitFullscreen, без request")
    page.evaluate("window.__tma.__emit('fullscreenChanged')")  # хост игнорирует
    page.wait_for_timeout(150)
    p = page.evaluate(PROBE_FS)
    c.ok(not p["btnPresent"], "S7: UI не даёт повторно запросить fullscreen")
    c.ok(p["fsReason"] == "tdesktop_disabled_until_e2e", "S7: причина задокументирована")
    page.screenshot(path=os.path.join(shots, "S7_tdesktop_launch_fullscreen_1024.png"))
    ctx.close()
    return c, {}


def scenario_widths(browser, shots):
    """S8: android float на 320/390/667×375 — геометрия в отчёт."""
    c = Check("S8_widths")
    rows = []
    for w, h, tag in ((320, 700, "320"), (390, 844, "390"), (667, 375, "667x375")):
        cfg = dict(platform="android", hasBoolean=True, isFullscreen=False,
                   stableHeight=max(300, h - 56), viewportHeight=h,
                   safeAreaInset={ "top": 0, "bottom": 0, "left": 0, "right": 0 },
                   contentSafeAreaInset={ "top": 36, "bottom": 0, "left": 0, "right": 0 })
        ctx, page = new_page(browser, cfg, mock_sdk_js(cfg), {"width": w, "height": h})
        wait_ready(page)
        p = page.evaluate(PROBE_FS)
        c.ok(p["slotFloatClass"] and p["posFixed"], "%s: float-слот" % tag)
        c.ok(p["rect"]["y"] >= 36, "%s: y=%s >= csa.top" % (tag, p["rect"]["y"]))
        c.ok(p["rect"]["w"] >= 44 and p["rect"]["h"] >= 44,
             "%s: hit %sx%s" % (tag, p["rect"]["w"], p["rect"]["h"]))
        c.ok(not p["hOverflow"], "%s: без h-overflow" % tag)
        c.ok("header-fs-btn" not in (p["interceptTopRight"] or ""),
             "%s: native ⋮ не перехвачен" % tag)
        rows.append({"width": w, "height": h, "btn": p["rect"],
                     "visual": p["visual"], "header": p["headerRect"]})
        page.screenshot(path=os.path.join(shots, "S8_float_%s.png" % tag.replace("x", "_")))
        ctx.close()
    return c, {"rows": rows}


def main():
    from playwright.sync_api import sync_playwright
    httpd = _start_server()
    print("[w2-fs] server on %d" % PORT)
    scenarios = [scenario_android_float, scenario_inline_fallback,
                 scenario_tdesktop_hidden, scenario_no_telegram,
                 scenario_ack_flows, scenario_launch_fullscreen,
                 scenario_widths]
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
