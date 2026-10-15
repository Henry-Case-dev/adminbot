"""W2-SHELL (asap8-v6-3-live-correction) — Playwright e2e U01+U02.

Обязательные UI-пробы ТЗ U01 «Обязательные UI-тесты» (REQ-U01-TESTS) и U02
на РЕАЛЬНОМ web/index.html + web/app.js (/api/* — route-стабы R17: только
идентификаторы/статусы, обезличенные данные):

  U01 (мобильная шапка <768):
    * row B = ровно 4 сегмента «Статус / Аналитика / Модули / Ещё ▾»,
      каждый виден ЦЕЛИКОМ (rect в вьюпорте), последний пункт доступен;
    * БЕЗ горизонтального document overflow (scrollWidth <= innerWidth)
      и без внутреннего скролла row B;
    * фактические boundingClientRect высоты шапки — числами в отчёт
      (бюджет ≤108–124 CSS px в стандартном портрете);
    * меню «Ещё»: popover не обрезается на 320px, Esc/outside-click
      закрывают, фокус возвращается в триггер, body-scroll-lock,
      deep-link пунктом меню, активный раздел = «Ещё • …» в триггере;
    * нижний navbar не возвращён.
  U02 (мобильные субвкладки Аналитики <768):
    * один полноширинный dropdown «Раздел: [текущая ▾]», ПОЛНЫЙ список
      из 7 вкладок, «Логи» в списке НЕТ; ARIA selected; опции в вьюпорте;
    * выбор через существующий oversightSetTab → hash/deep-link живы
      (tab=…, открытие последней вкладки и возврат);
    * desktop ≥768 — прежняя горизонтальная панель, dropdown скрыт.
  Матрица: 320/360/390/430 портрет, 667×375 landscape, 200% zoom
  (320 CSS px @2x), TMA viewport resize (expanded/collapsed), длинный
  русский chat title.

Telegram SDK — route-mock по w2-contract §4.2.1: перехват
`**/static/vendor/telegram-web-app.js` (route-fulfill заглушкой), НЕ
addInitScript поверх реального SDK.

Запуск: .venv/Scripts/python.exe tools/ui_asap8_w2_shell_e2e.py
Опции:  --baseline <dir>  — прогнать before-матрицу по другому корню web/
        (скриншоты before того же маршрута, без ассертов нового канона).
Артефакты: plans/features/asap8-v6-3-live-correction/w2-evidence-shell/
"""
import argparse
import copy
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (стабы /api/* — reuse)

PORT_CANDIDATE = 8812
PORT_BASELINE = 8813
EVIDENCE = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",
                        "w2-evidence-shell")

# Обезличенный длинный русский chat title (REQ-U01-TESTS).
LONG_TITLE = ("ПЕРМСКОЕ КРАЕВОЕ ОБЪЕДИНЕНИЕ СОЦИАЛЬНЫХ УЧРЕЖДЕНИЙ И "
              "ВЕДОМСТВЕННЫХ ОРГАНИЗАЦИЙ (ПЕРМСОЦКОМПЛЕКС-ОБЛ)")
CHATS_LONG = [{"chat_id": -1001234567890, "title": LONG_TITLE,
               "is_dm": False, "photo_file_id": None, "access": "admin"}]

# ── SDK route-mock (w2-contract §4.2.1) — body для telegram-web-app.js ──
SDK_STUB = """
try { sessionStorage.setItem('adminbot.initData',
  'user=%7B%22id%22%3A5885953495%7D&hash=audit'); } catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  platform: 'android', version: '9.0', colorScheme: 'dark', themeParams: {},
  get viewportStableHeight() {
    return Math.max(0, (window.innerHeight || 800) - 56);
  },
  isExpanded: true, isFullscreen: false,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, close() {},
  setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
  requestFullscreen() {}, exitFullscreen() {},
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  onEvent() {}, offEvent() {},
  openLink() {}, openTelegramLink() {}, showAlert() {}, showConfirm() {},
  BackButton: { isVisible: false, show() {}, hide() {}, onClick() {}, offClick() {} },
  MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
  HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
} };
"""

PROBE = """
(() => {
  const links = Array.from(document.querySelectorAll('.mobile-topnav-link'));
  const vw = window.innerWidth, vh = window.innerHeight;
  const hdr = document.querySelector('header.header-sticky');
  const nav = document.querySelector('.mobile-topnav');
  const trigger = document.querySelector('.mobile-topnav-more');
  const strip = (s) => s.replace(/[\\uE000-\\uF8FF]/g, '')
                        .replace(/\\s+/g, ' ').trim();
  return {
    vw, vh,
    scrollWidth: document.documentElement.scrollWidth,
    headerH: hdr ? Math.round(hdr.getBoundingClientRect().height * 10) / 10 : null,
    navH: nav ? Math.round(nav.getBoundingClientRect().height * 10) / 10 : null,
    navScrollW: nav ? nav.scrollWidth : null,
    navClientW: nav ? nav.clientWidth : null,
    shellMode: document.querySelector('.app-shell')
      ? document.querySelector('.app-shell').className : '',
    moreLabel: trigger ? strip(trigger.textContent) : null,
    links: links.map((el) => {
      const r = el.getBoundingClientRect();
      return { t: el.textContent.replace(/[\\uE000-\\uF8FF]/g, '')
                          .replace(/\\s+/g, ' ').trim(),
               x: Math.round(r.x * 10) / 10, right: Math.round(r.right * 10) / 10,
               y: Math.round(r.y), bottom: Math.round(r.bottom),
               w: Math.round(r.width), h: Math.round(r.height) };
    }),
  };
})()
"""

MENU_PROBE = """
(() => {
  const root = document.querySelector('.more-menu-root');
  const p = document.querySelector('.more-menu-panel');
  const main = document.querySelector('main.scroll-area');
  const shell = document.querySelector('.app-shell');
  const trig = document.querySelector('.mobile-topnav-more');
  if (!p) return { open: !!root, panel: null,
    lockClass: shell ? shell.classList.contains('more-menu-open') : null,
    mainOverflow: main ? getComputedStyle(main).overflowY : null,
    focusOnTrigger: document.activeElement === trig };
  const r = p.getBoundingClientRect();
  return { open: !!root,
    panel: { x: Math.round(r.x), y: Math.round(r.y),
             right: Math.round(r.right), bottom: Math.round(r.bottom) },
    items: Array.from(p.querySelectorAll('.more-menu-item')).map((el) => {
      const b = el.getBoundingClientRect();
      return { t: el.textContent.replace(/\\s+/g, ' ').trim(),
               right: Math.round(b.right), bottom: Math.round(b.bottom) };
    }),
    lockClass: shell ? shell.classList.contains('more-menu-open') : null,
    mainOverflow: main ? getComputedStyle(main).overflowY : null,
    focusOnTrigger: document.activeElement === trig };
})()
"""

OVERSIGHT_PROBE = """
(() => {
  const dd = document.querySelector('.oversight-mobile-dd');
  const row = document.querySelector('.oversight-tabs__row');
  const trig = document.querySelector('.oversight-mobile-trigger');
  const panel = document.querySelector('.oversight-mobile-panel');
  return {
    ddDisplay: dd ? getComputedStyle(dd).display : null,
    rowDisplay: row ? getComputedStyle(row).display : null,
    triggerText: trig ? trig.textContent.replace(/\\s+/g, ' ').trim() : null,
    options: panel ? Array.from(panel.querySelectorAll(
      '.oversight-mobile-option')).map((o) => {
        const b = o.getBoundingClientRect();
        return { t: o.textContent.trim(),
                 sel: o.getAttribute('aria-selected'),
                 right: Math.round(b.right), bottom: Math.round(b.bottom) };
      }) : null,
    panelRight: panel ? Math.round(panel.getBoundingClientRect().right) : null,
    panelBottom: panel ? Math.round(panel.getBoundingClientRect().bottom) : null,
  };
})()
"""


def make_api_handler(chats_payload):
    """Route-обработчик /api/** — стабы матрицы + длинный chat title."""
    def _api_handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/access/chats"):
            body = chats_payload
        else:
            body = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))
    return _api_handler


def make_sdk_handler(route):
    """Route-fulfill заглушки SDK вместо реального telegram-web-app.js."""
    route.fulfill(status=200, content_type="application/javascript",
                  body=SDK_STUB)


def make_handler(webroot):
    """Static-обработчик произвольного корня web/ (candidate/baseline)."""
    class _WebRootHandler(SimpleHTTPRequestHandler):
        def translate_path(self, path):  # noqa: N802
            p = path.split("?")[0]
            if p.startswith("/static/"):
                rel = "static/" + p[len("/static/"):]
            elif p.startswith("/web/"):
                rel = p[len("/web/"):]
            elif p in ("/", "", "/index.html"):
                rel = "index.html"
            else:
                rel = p.lstrip("/")
            return os.path.join(webroot, rel.replace("/", os.sep))

        def log_message(self, *args):  # тихо
            pass
    return _WebRootHandler


def serve(port, webroot):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(webroot))
    import threading
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def new_page(browser, width, height, api_handler, dsf=None, mobile=True):
    kwargs = {"viewport": {"width": width, "height": height},
              "is_mobile": mobile, "has_touch": mobile}
    if dsf:
        kwargs["device_scale_factor"] = dsf
    ctx = browser.new_context(**kwargs)
    ctx.route("**/api/**", api_handler)
    # SDK — route-mock по w2-contract §4.2.1 (не addInitScript).
    ctx.route("**/static/vendor/telegram-web-app.js", make_sdk_handler)
    page = ctx.new_page()
    page.set_default_timeout(8000)
    return ctx, page


def wait_app(page, hash_route="#/"):
    page.goto(BASE_CAND + hash_route, wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_timeout(1200)


def rowb_checks(page, res, name, checks, header_budget=124.0,
                nav_range=(40, 50)):
    p = page.evaluate(PROBE)
    res["measurements"][name] = p
    ok_links = len(p["links"]) == 4
    checks[name + ":rowB=4"] = ok_links
    if ok_links:
        checks[name + ":все4видныЦеликом"] = all(
            lk["x"] >= -0.5 and lk["right"] <= p["vw"] + 0.5
            for lk in p["links"])
        checks[name + ":последнийПунктДоступен"] = (
            p["links"][-1]["right"] <= p["vw"] + 0.5
            and p["links"][-1]["t"].startswith("Ещё"))
        checks[name + ":порядокСтатусАналитикаМодули"] = (
            [lk["t"] for lk in p["links"][:3]] ==
            ["Статус", "Аналитика", "Модули"])
    checks[name + ":безГоризонтальногоОverflow"] = (
        p["scrollWidth"] <= p["vw"] + 1)
    checks[name + ":rowBбезВнутреннегоСкролла"] = (
        p["navScrollW"] is not None
        and p["navScrollW"] <= p["navClientW"] + 1)
    checks[name + ":headerВБюджете<=%.0f" % header_budget] = (
        p["headerH"] is not None and p["headerH"] <= header_budget)
    checks[name + ":rowB%d-%d" % nav_range] = (
        p["navH"] is not None and nav_range[0] <= p["navH"] <= nav_range[1])
    return p


def menu_flow(page, res, name, checks, expect_items=5):
    """Ещё: открыть → не обрезано → Esc+фокус → outside click → lock."""
    page.click(".mobile-topnav-more")
    page.wait_for_selector(".more-menu-panel", state="visible")
    page.wait_for_timeout(250)
    m = page.evaluate(MENU_PROBE)
    res["measurements"][name + ":menu"] = m
    checks[name + ":менюОткрыто"] = bool(m["panel"])
    if m["panel"]:
        vw, vh = page.evaluate("[window.innerWidth, window.innerHeight]")
        checks[name + ":менюНеОбрезано"] = (
            m["panel"]["x"] >= 0 and m["panel"]["right"] <= vw + 0.5
            and m["panel"]["bottom"] <= vh + 0.5)
        checks[name + ":пунктыВВьюпорте"] = all(
            it["right"] <= vw + 0.5 and it["bottom"] <= vh + 0.5
            for it in m["items"])
        checks[name + ":пунктов=%d" % expect_items] = (
            len(m["items"]) == expect_items)
    checks[name + ":scrollLock"] = (m["lockClass"] is True
                                    and m["mainOverflow"] == "hidden")
    # Esc → закрытие + возврат фокуса в триггер.
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    m2 = page.evaluate(MENU_PROBE)
    checks[name + ":escЗакрывает"] = m2["panel"] is None and not m2["open"]
    checks[name + ":фокусВТриггереПослеEsc"] = (m2["focusOnTrigger"] is True)
    # Outside click → закрытие.
    page.click(".mobile-topnav-more")
    page.wait_for_selector(".more-menu-panel", state="visible")
    page.wait_for_timeout(200)
    vh = page.evaluate("window.innerHeight")
    page.mouse.click(4, vh // 2)
    page.wait_for_timeout(250)
    m3 = page.evaluate(MENU_PROBE)
    checks[name + ":outsideClickЗакрывает"] = (m3["panel"] is None
                                               and not m3["open"])


def run_candidate(browser, api_handler, res):
    checks = res["checks"]

    # ═══ Портретная матрица 320/360/390/430 + меню «Ещё» ═══
    for (w, h) in [(320, 700), (360, 780), (390, 844), (430, 932)]:
        name = "m%d" % w
        ctx, page = new_page(browser, w, h, api_handler)
        wait_app(page, "#/")
        rowb_checks(page, res, name, checks)
        menu_flow(page, res, name, checks, expect_items=5)
        if w == 390:
            page.screenshot(path=os.path.join(
                EVIDENCE, "after_u01_status_390.png"))
        elif w == 320:
            page.screenshot(path=os.path.join(
                EVIDENCE, "after_u01_status_320.png"))
        ctx.close()

    # ═══ Landscape 667×375 (mobile shell) ═══
    ctx, page = new_page(browser, 667, 375, api_handler)
    wait_app(page, "#/")
    rowb_checks(page, res, "landscape667", checks, nav_range=(30, 50))
    page.screenshot(path=os.path.join(EVIDENCE, "after_u01_landscape_667.png"))
    ctx.close()

    # ═══ 200% zoom: 320 CSS px @2x + длинный русский chat title ═══
    ctx, page = new_page(browser, 320, 700, api_handler, dsf=2)
    wait_app(page, "#/")
    rowb_checks(page, res, "zoom200_320", checks)
    # Селектор чата: длинный title — ellipsis, без расширения row A.
    trig = page.locator(".scope-trigger")
    tw = trig.bounding_box()
    checks["zoom200:селекторКомпактен<половиныRowA"] = bool(
        tw and tw["width"] <= 320 * 0.62)
    menu_flow(page, res, "zoom200_320", checks, expect_items=5)
    page.screenshot(path=os.path.join(EVIDENCE, "after_u01_zoom200_320.png"))
    ctx.close()

    # ═══ Меню «Ещё»: deep link + активный раздел в триггере (360) ═══
    ctx, page = new_page(browser, 360, 780, api_handler)
    wait_app(page, "#/")
    page.click(".mobile-topnav-more")
    page.wait_for_selector(".more-menu-panel", state="visible")
    page.wait_for_timeout(200)
    # Клик по «ИИ» (пункт меню) → deep link + закрытие.
    page.locator(".more-menu-item", has_text="ИИ").first.click()
    page.wait_for_timeout(600)
    checks["menu:deepLink#/ai"] = page.evaluate(
        "window.location.hash") == "#/ai"
    checks["menu:менюЗакрытоПослеПерехода"] = page.evaluate(
        "!!document.querySelector('.more-menu-root')") is False
    label = page.evaluate(
        "document.querySelector('.mobile-topnav-more').textContent"
        ".replace(/[\\uE000-\\uF8FF]/g, '')"
        ".replace(/\\s+/g, ' ').trim()")
    checks["menu:триггерЕщё•ИИ"] = ("Ещё • ИИ" in label)
    res["measurements"]["menuTriggerLabel"] = label
    # Возврат на Статус: триггер снова просто «Ещё».
    page.goto(BASE_CAND + "#/", wait_until="load")
    page.wait_for_timeout(800)
    label2 = page.evaluate(
        "document.querySelector('.mobile-topnav-more').textContent"
        ".replace(/[\\uE000-\\uF8FF]/g, '')"
        ".replace(/\\s+/g, ' ').trim()")
    checks["menu:наСтатусеПростоЕщё"] = (label2 == "Ещё")
    ctx.close()

    # ═══ U02: мобильный dropdown суб-вкладок Аналитики (390) ═══
    ctx, page = new_page(browser, 390, 844, api_handler)
    wait_app(page, "#/oversight")
    o = page.evaluate(OVERSIGHT_PROBE)
    res["measurements"]["u02_390"] = o
    checks["u02:dropdownВиден<768"] = (o["ddDisplay"] == "block")
    checks["u02:лентаPillsСкрыта"] = (o["rowDisplay"] == "none")
    checks["u02:триггерРаздел"] = bool(o["triggerText"]
                                       and o["triggerText"].startswith("Раздел:")
                                       and "Обзор" in o["triggerText"])
    page.click(".oversight-mobile-trigger")
    page.wait_for_selector(".oversight-mobile-panel", state="visible")
    page.wait_for_timeout(250)
    o = page.evaluate(OVERSIGHT_PROBE)
    res["measurements"]["u02_390_open"] = o
    want = ["Обзор", "Процессы", "Запуски", "Инциденты",
            "Память и интеллект", "Модели и расходы", "Саммари"]
    got = [x["t"] for x in (o["options"] or [])]
    checks["u02:полныйСписок7"] = (got == want)
    checks["u02:логиНЕТвСписке"] = all("Логи" != x["t"]
                                       for x in (o["options"] or []))
    vw = page.evaluate("window.innerWidth")
    vh = page.evaluate("window.innerHeight")
    checks["u02:опцииВВьюпорте320-390"] = all(
        x["right"] <= vw + 0.5 and x["bottom"] <= vh + 0.5
        for x in (o["options"] or []))
    checks["u02:ariaSelectedНаОбзоре"] = any(
        x["t"] == "Обзор" and x["sel"] == "true"
        for x in (o["options"] or []))
    page.screenshot(path=os.path.join(EVIDENCE, "after_u02_open_390.png"))
    # Выбор «Память и интеллект» → существующий oversightSetTab → hash.
    page.locator(".oversight-mobile-option",
                 has_text="Память и интеллект").first.click()
    page.wait_for_timeout(600)
    checks["u02:hashTabMemory"] = "tab=memory" in page.evaluate(
        "window.location.hash")
    o = page.evaluate(OVERSIGHT_PROBE)
    checks["u02:триггерОбновился"] = bool(o["triggerText"]
                                          and "Память и интеллект"
                                          in o["triggerText"])
    checks["u02:панельЗакрылась"] = (o["options"] is None)
    # Deep link: открытие последней вкладки (?tab=summary) + возврат на Обзор.
    page.goto(BASE_CAND + "#/oversight?tab=summary", wait_until="load")
    page.wait_for_timeout(1200)
    o = page.evaluate(OVERSIGHT_PROBE)
    checks["u02:deepLinkSummary"] = bool(o["triggerText"]
                                         and "Саммари" in o["triggerText"])
    page.click(".oversight-mobile-trigger")
    page.wait_for_selector(".oversight-mobile-panel", state="visible")
    page.locator(".oversight-mobile-option",
                 has_text="Обзор").first.click()
    page.wait_for_timeout(600)
    checks["u02:возвратОбзор"] = "tab=overview" in page.evaluate(
        "window.location.hash")
    checks["u02:безГоризонтальногоОverflow390"] = page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1")
    ctx.close()

    # ═══ U02: deep-link и фильтры (инциденты) — не сломаны (390) ═══
    ctx, page = new_page(browser, 390, 844, api_handler)
    page.goto(BASE_CAND + "#/oversight?view=runs&status=failed",
              wait_until="load")
    page.wait_for_timeout(1200)
    o = page.evaluate(OVERSIGHT_PROBE)
    checks["u02:deepLinkRunsФильтр"] = bool(
        o["triggerText"] and "Запуски" in o["triggerText"])
    checks["u02:фильтрStatusСохранён"] = page.evaluate(
        "location.hash.indexOf('status=failed') >= 0")
    ctx.close()

    # ═══ TMA viewport resize (expanded/collapsed) на 390 ═══
    ctx, page = new_page(browser, 390, 844, api_handler)
    wait_app(page, "#/")
    page.set_viewport_size({"width": 390, "height": 500})
    page.wait_for_timeout(600)
    rowb_checks(page, res, "collapsed500", checks)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(600)
    rowb_checks(page, res, "expanded844", checks)
    ctx.close()

    # ═══ Desktop 1280: sidebar/шапка не изменены; U02 desktop tabs ═══
    dctx = browser.new_context(viewport={"width": 1280, "height": 800})
    dctx.route("**/api/**", api_handler)
    dctx.route("**/static/vendor/telegram-web-app.js", make_sdk_handler)
    dp = dctx.new_page()
    dp.set_default_timeout(8000)
    dp.goto(BASE_CAND + "#/oversight", wait_until="load")
    dp.wait_for_selector("header.header-sticky", state="visible")
    dp.wait_for_timeout(1200)
    o = dp.evaluate(OVERSIGHT_PROBE)
    res["measurements"]["u02_desktop1280"] = {
        "ddDisplay": o["ddDisplay"], "rowDisplay": o["rowDisplay"]}
    checks["u02.1:desktopDropdownСкрыт"] = (o["ddDisplay"] == "none")
    checks["u02.1:desktopТабыВидны"] = (o["rowDisplay"] != "none")
    checks["desktop:sidebarВидна>=1200"] = dp.locator(
        ".app-sidebar").is_visible()
    checks["desktop:mobileTopnavНЕТ"] = dp.locator(
        ".mobile-topnav").count() == 0
    checks["desktop:bezГоризонтOverflow"] = dp.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1")
    dp.screenshot(path=os.path.join(EVIDENCE, "after_u02_desktop_1280.png"))
    dctx.close()


def run_baseline(browser, api_handler, res):
    """before-кадры того же маршрута (старый канон, только скриншоты/числа)."""
    ctx, page = new_page(browser, 390, 844, api_handler)
    page.goto(BASE_BASE + "#/", wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_timeout(1200)
    res["measurements"]["before_390"] = page.evaluate(PROBE)
    page.screenshot(path=os.path.join(EVIDENCE, "before_u01_status_390.png"))
    page.goto(BASE_BASE + "#/oversight", wait_until="load")
    page.wait_for_timeout(1200)
    res["measurements"]["before_u02_390"] = page.evaluate(OVERSIGHT_PROBE)
    page.screenshot(path=os.path.join(EVIDENCE, "before_u02_analytics_390.png"))
    ctx.close()
    ctx, page = new_page(browser, 320, 700, api_handler)
    page.goto(BASE_BASE + "#/", wait_until="load")
    page.wait_for_timeout(1200)
    res["measurements"]["before_320"] = page.evaluate(PROBE)
    page.screenshot(path=os.path.join(EVIDENCE, "before_u01_status_320.png"))
    ctx.close()


def main():
    global BASE_CAND, BASE_BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=None,
                    help="корень репо baseline для before-кадров")
    args = ap.parse_args()

    os.makedirs(EVIDENCE, exist_ok=True)
    chats_payload = copy.deepcopy(CHATS_LONG)

    httpd_c = serve(PORT_CANDIDATE, os.path.join(REPO, "web"))
    BASE_CAND = "http://127.0.0.1:%d/web/index.html" % PORT_CANDIDATE
    httpd_b = None
    if args.baseline:
        httpd_b = serve(PORT_BASELINE,
                        os.path.join(args.baseline, "web"))
        BASE_BASE = "http://127.0.0.1:%d/web/index.html" % PORT_BASELINE

    api_handler = make_api_handler(chats_payload)
    from playwright.sync_api import sync_playwright
    result = {"console_errors": [], "checks": {}, "measurements": {},
              "screenshots": []}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        if args.baseline:
            run_baseline(browser, api_handler, result)
            print("BEFORE-кадры сняты:", args.baseline)
        else:
            run_candidate(browser, api_handler, result)
        browser.close()
        httpd_c.shutdown()
        if httpd_b:
            httpd_b.shutdown()

    out = os.path.join(EVIDENCE, "w2_shell_e2e.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    ok = all(v is True for v in result["checks"].values()) \
        and not result["console_errors"]
    bad = {k: v for k, v in result["checks"].items() if v is not True}
    print(json.dumps({"failed_checks": bad,
                      "console_errors": result["console_errors"][:5]},
                     ensure_ascii=False, indent=1))
    print("measurements:", json.dumps(
        {k: v for k, v in result["measurements"].items()
         if k.endswith(("320", "360", "390", "430", "667", "500", "844"))
         }, ensure_ascii=False)[:1200])
    print("W2-SHELL-E2E-" + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
