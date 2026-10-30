"""EVOL-023 / EVOL-024 (W7) — live-прогон навигации, topbar и overlay-слоя.

Детерминированная Playwright-проверка НАСТОЯЩЕГО `web/index.html` + `web/app.js`
(сервер и стабы API переиспользуются из `tools/ui_round1025_matrix.py`; секретов
нет, живая отправка в Telegram-чаты не выполняется).

Проверяется:
  * desktop 1280 — компактный topbar (контент начинается сразу под шапкой,
    перекрытия нет), имя РАЗДЕЛА в шапке, дубль заголовка убран, ОДИН
    переключатель области, ⛶ — ghost-icon (computed: прозрачная подложка,
    без градиента/рамки/тени/blur, hit-цель 44×44);
  * выпадающая панель области: не уезжает под sidebar/за вьюпорт, читаемая
    подложка (alpha ≥ .9), поиск, Esc, длинные названия, Esc из поиска
    возвращает фокус в триггер (ревью F2);
  * rail постоянной панели (сворачивание, персист) и возврат к полной;
  * tablet 900 — drawer: фокус внутрь, Esc, возврат фокуса, без h-скролла;
  * mobile 390 — шапка/область/«Ещё» в границах вьюпорта, без h-скролла;
  * 320 и zoom 200% — нет горизонтального скролла всей страницы;
  * модалка модуля — в пределах вьюпорта, внутренний скролл, фокус в диалоге;
  * медленный API — каркас не ломается (нет overflow/перекрытия);
  * машинная инвентаризация EVOL-024: 19 маршрутов × 6 вьюпортов
    (320/390/768/1024/1280/1920) → `w7-nav-inventory.json`.

Запуск: .venv\\Scripts\\python.exe tools\\ui_evol_w7_nav_e2e.py [--out DIR]
Артефакты по умолчанию: plans/features/evol/audit/evidence/
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8841
DEFAULT_SHOTS = os.path.join(REPO, "plans", "features", "evol", "audit",
                             "evidence")

HEAD_MAX_DESKTOP = 76      # компактная строка: 44px контрол + padding
HEAD_MAX_MOBILE = 132      # строка области + строка разделов

LONG_CHAT = {
    "chat_id": -1001234567890,
    "title": "Очень длинное название рабочего чата с уточнением и подписью",
    "type": "supergroup", "is_dm": False,
}

# EVOL-024: машинная инвентаризация «19 маршрутов × 6 вьюпортов» (канонический
# список маршрутов — из матрицы §71, чтобы не заводить второй реестр).
INV_ROUTES = list(M.ROUTES)
INV_VIEWPORTS = ((320, 700), (390, 844), (768, 1024), (1024, 768),
                 (1280, 800), (1920, 1080))

INV_PROBE = r"""
() => {
  const de = document.documentElement;
  const vw = window.innerWidth;
  const label = (el) => {
    const cls = (el.className && el.className.toString
      ? el.className.toString() : '').split(/\s+/).filter(Boolean).slice(0, 3);
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  };
  // Элемент внутри горизонтального скроллера — намеренная прокрутка, не дефект.
  const inScroller = (el) => {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
      p = p.parentElement;
    }
    return false;
  };
  const off = [];
  const clip = [];
  const all = document.querySelectorAll('body *');
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (el.closest('[aria-hidden="true"]')) continue;
    const tn = el.tagName;
    if (tn === 'CANVAS' || tn === 'SCRIPT' || tn === 'STYLE'
        || tn === 'TEMPLATE' || tn === 'LINK') continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (parseFloat(cs.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if ((r.right > vw + 1 || r.left < -1) && !inScroller(el)) {
      off.push(label(el) + '@' + Math.round(r.left) + '..' + Math.round(r.right));
    }
    const txt = (el.textContent || '').trim();
    if (txt && el.children.length === 0
        && (cs.overflowX === 'hidden' || cs.overflowX === 'clip')
        && el.scrollWidth > el.clientWidth + 1
        && cs.textOverflow !== 'ellipsis') {
      clip.push(label(el) + ':' + el.clientWidth + '<' + el.scrollWidth);
    }
  }
  return {vw: vw, sw: de.scrollWidth, hScroll: de.scrollWidth > vw + 1,
          offCount: off.length, offscreen: off.slice(0, 5),
          clippedCount: clip.length, clipped: clip.slice(0, 5)};
}
"""


class _Handler(M._Handler):
    pass


def _app():
    return "http://127.0.0.1:%d/web/index.html" % PORT


def _routes(extra_delay_ms=0):
    """Обработчик /api/** с теми же стабами, что у матрицы §71."""

    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps([LONG_CHAT,
                                           {"chat_id": 424242,
                                            "title": "Второй чат",
                                            "type": "group", "is_dm": False}]))
            return
        if url.endswith("/api/config") and extra_delay_ms:
            # slow API: ответ приходит позже, каркас обязан остаться целым
            import time
            time.sleep(extra_delay_ms / 1000.0)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(M.CONFIG_STUB))
            return
        if url.endswith("/api/config"):
            hdrs = route.request.headers or {}
            payload = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                       else M.CONFIG_STUB)
        else:
            payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))

    return _route


PROBE_SHELL = r"""
() => {
  const de = document.documentElement;
  const h = document.querySelector('header.header-sticky');
  const main = document.querySelector('main.scroll-area');
  const hb = h ? h.getBoundingClientRect() : null;
  const mb = main ? main.getBoundingClientRect() : null;
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    sw: de.scrollWidth,
    over: de.scrollWidth > window.innerWidth + 1,
    headerH: hb ? Math.round(hb.height) : null,
    headerBottom: hb ? Math.round(hb.bottom) : null,
    mainTop: mb ? Math.round(mb.top) : null,
    // перекрытие: верх контента не должен быть выше низа шапки
    overlap: (hb && mb) ? Math.max(0, Math.round(hb.bottom - mb.top)) : null,
    title: (document.querySelector('.header-title') || {}).textContent || '',
    scopeTriggers: document.querySelectorAll('.scope-trigger').length,
    scopeWrap: document.querySelectorAll('[data-nav-scope]').length,
    hubTitleDisplay: (() => {
      const t = document.querySelector('.hub-head .hub-title');
      return t ? getComputedStyle(t).display : null; })(),
    sidebar: (() => {
      const s = document.querySelector('.app-sidebar');
      if (!s) return null;
      const r = s.getBoundingClientRect();
      return {x: Math.round(r.x), w: Math.round(r.width)}; })(),
    sidebarLabels: (() => {
      const l = document.querySelector('.app-sidebar .sidebar-label');
      return l ? getComputedStyle(l).display !== 'none' : null; })(),
    mainX: mb ? Math.round(mb.x) : null,
    collapsed: (() => {
      const s = document.querySelector('.app-shell');
      return s ? s.classList.contains('sidebar-collapsed') : null; })(),
    fsBtn: (() => {
      const b = document.querySelector('.header-fs-btn');
      if (!b) return null;
      const r = b.getBoundingClientRect();
      const cs = getComputedStyle(b);
      return {w: Math.round(r.width), h: Math.round(r.height),
              title: b.getAttribute('title'),
              right: Math.round(r.right), vw: window.innerWidth,
              // EVOL-023 §4 (ревью F1): ghost-icon — прозрачная hit-цель,
              // никакого декоративного материала (линза снята с узла).
              bg: cs.backgroundColor,
              bgImage: (cs.backgroundImage || 'none').slice(0, 80),
              shadow: (cs.boxShadow || 'none').slice(0, 80),
              border: cs.borderTopWidth + ' ' + cs.borderTopStyle,
              blur: (cs.backdropFilter || cs.webkitBackdropFilter
                     || 'none').slice(0, 60),
              radius: cs.borderTopLeftRadius,
              color: cs.color,
              lens: b.classList.contains('lg-mini-lens')}; })(),
    topnav: (() => {
      const n = document.querySelector('.mobile-topnav');
      if (!n) return null;
      const r = n.getBoundingClientRect();
      return {h: Math.round(r.height), bottom: Math.round(r.bottom)}; })(),
  };
}
"""

PROBE_PANEL = r"""
() => {
  const p = document.querySelector('.scope-panel');
  if (!p) return {open: false};
  const r = p.getBoundingClientRect();
  const cs = getComputedStyle(p);
  const sb = document.querySelector('.app-sidebar');
  const sbRight = sb ? sb.getBoundingClientRect().right : 0;
  const mid = document.elementFromPoint(
    Math.min(window.innerWidth - 2, r.left + r.width / 2),
    Math.min(window.innerHeight - 2, r.top + r.height / 2));
  const name = document.querySelector('.scope-trigger .scope-name');
  const badge = document.querySelector('.scope-trigger .badge');
  const tr = document.querySelector('.scope-trigger').getBoundingClientRect();
  const br = badge ? badge.getBoundingClientRect() : null;
  return {
    open: true,
    x: Math.round(r.x), right: Math.round(r.right),
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    vw: window.innerWidth, vh: window.innerHeight,
    insideViewport: r.left >= -1 && r.right <= window.innerWidth + 1
                    && r.top >= -1 && r.bottom <= window.innerHeight + 1,
    overlapsSidebar: r.left < sbRight - 0.5,
    hitTestInside: mid ? (p.contains(mid) || mid === p) : false,
    bg: cs.backgroundColor,
    search: !!p.querySelector('input[type="search"]'),
    options: p.querySelectorAll('.scope-option').length,
    nameTruncated: name ? name.scrollWidth > name.clientWidth + 1 : null,
    badgeOverlapsName: (br && name)
      ? br.left < name.getBoundingClientRect().right - 0.5 : null,
    triggerInsideViewport: tr.right <= window.innerWidth + 1,
  };
}
"""


def _backdrop_alpha(bg: str) -> float:
    """alpha из css-строки rgba(...) (0..1)."""
    try:
        parts = bg.replace("rgba(", "").replace(")", "").split(",")
        return float(parts[3].strip())
    except Exception:  # noqa: BLE001
        return 1.0 if bg.startswith("rgb(") else 0.0


def _ghost_fails(btn, where):
    """⛶ должен быть compact ghost-icon (EVOL-023 §4, ревью F1).

    Проверяется ФАКТИЧЕСКИЙ computed-стиль: прозрачная подложка, отсутствие
    градиента/рамки/тени/blur/скругления-линзы и класса `.lg-mini-lens`.
    """
    if not btn:
        return ["%s: кнопка ⛶ не найдена" % where]
    out = []
    if btn["w"] < 44 or btn["h"] < 44:
        out.append("%s: hit-цель ⛶ %sx%s < 44x44" % (where, btn["w"], btn["h"]))
    if btn["bg"] not in ("rgba(0, 0, 0, 0)", "transparent"):
        out.append("%s: у ⛶ непрозрачная подложка %s" % (where, btn["bg"]))
    if btn["bgImage"] not in ("none", ""):
        out.append("%s: у ⛶ декоративный градиент %s" % (where, btn["bgImage"]))
    if btn["shadow"] not in ("none", ""):
        out.append("%s: у ⛶ тень/блики %s" % (where, btn["shadow"]))
    if btn["blur"] not in ("none", ""):
        out.append("%s: у ⛶ backdrop-filter %s" % (where, btn["blur"]))
    if not str(btn["border"]).startswith("0px"):
        out.append("%s: у ⛶ рамка %s" % (where, btn["border"]))
    if btn["radius"] not in ("0px", "0%", "0"):
        out.append("%s: у ⛶ скругление линзы %s" % (where, btn["radius"]))
    if btn["lens"]:
        out.append("%s: на ⛶ снова висит .lg-mini-lens" % where)
    # Иконка должна остаться видимой: ghost ≠ невидимая кнопка.
    rgb = btn.get("color") or ""
    try:
        nums = [float(x) for x in rgb[rgb.index("(") + 1:rgb.index(")")]
                .replace("/", ",").split(",")][:3]
        bright = sum(nums) / 3.0
    except Exception:  # noqa: BLE001
        bright = -1
    if bright < 120:
        out.append("%s: иконка ⛶ не читается (color=%s)" % (where, rgb))
    return out


def run(out_dir: str) -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    fails = []
    report = {}

    def shot(page, name):
        page.screenshot(path=os.path.join(out_dir, "w7-nav-" + name + ".png"))

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── desktop 1280 ────────────────────────────────────────────────
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _routes())
        page = ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text[:160])
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        page.goto(_app() + "#/modules", wait_until="load")
        page.wait_for_selector(".app-shell", timeout=10000)
        page.wait_for_timeout(900)
        d = page.evaluate(PROBE_SHELL)
        report["desktop"] = d
        if d["headerH"] is None or d["headerH"] > HEAD_MAX_DESKTOP:
            fails.append("desktop: header %s px > %d" % (d["headerH"], HEAD_MAX_DESKTOP))
        if d["overlap"]:
            fails.append("desktop: контент под шапкой на %s px" % d["overlap"])
        if d["over"]:
            fails.append("desktop: горизонтальный скролл %s > %s" % (d["sw"], d["vw"]))
        if d["scopeTriggers"] != 1 or d["scopeWrap"] != 1:
            fails.append("desktop: переключателей области %s/%s (нужен ровно 1)"
                         % (d["scopeTriggers"], d["scopeWrap"]))
        if d["title"].strip() != "Модули":
            fails.append("desktop: имя раздела в топбаре %r" % d["title"])
        if d["hubTitleDisplay"] != "none":
            fails.append("desktop: дубль заголовка (hub-title) виден")
        if not d["fsBtn"] or d["fsBtn"]["w"] < 44 or d["fsBtn"]["h"] < 44:
            fails.append("desktop: ⛶ меньше 44×44 или отсутствует")
        if d["fsBtn"] and not d["fsBtn"]["title"]:
            fails.append("desktop: у ⛶ нет tooltip")
        fails.extend(_ghost_fails(d["fsBtn"], "desktop"))
        page.locator("header.header-sticky").screenshot(
            path=os.path.join(out_dir, "w7-nav-fs-ghost-header-1280.png"))
        shot(page, "desktop-modules")

        # панель области: геометрия/подложка/длинное имя
        page.click(".scope-trigger")
        page.wait_for_timeout(400)
        pj = page.evaluate(PROBE_PANEL)
        report["desktop_panel"] = pj
        if not pj.get("open"):
            fails.append("desktop: панель области не открылась")
        else:
            if not pj["insideViewport"]:
                fails.append("desktop: панель области вне вьюпорта")
            if pj["overlapsSidebar"]:
                fails.append("desktop: панель области накрывает sidebar")
            if not pj["hitTestInside"]:
                fails.append("desktop: панель перекрыта другим слоем")
            if _backdrop_alpha(pj["bg"]) < 0.9:
                fails.append("desktop: подложка панели слишком прозрачна (%s)"
                             % pj["bg"])
            if not pj["search"]:
                fails.append("desktop: нет поиска по чатам в панели")
            if not pj["nameTruncated"]:
                fails.append("desktop: длинное имя не обрезается")
            if pj["badgeOverlapsName"]:
                fails.append("desktop: имя наезжает на бейдж области")
        shot(page, "desktop-scope-panel")
        # F2 (ревью 31.10.2026): Esc из поиска возвращает фокус в триггер,
        # а не бросает клавиатурного пользователя на BODY.
        page.locator('.scope-panel input[type="search"]').click()
        focused_in_search = page.evaluate(
            """() => {
                const a = document.activeElement;
                const p = document.querySelector('.scope-panel');
                return !!(a && p && p.contains(a) && a.matches('input'));
            }""")
        if not focused_in_search:
            fails.append("desktop: фокус не встал в поиск панели области")
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        after_esc = page.evaluate(
            """() => {
                const a = document.activeElement;
                return {panel: !!document.querySelector('.scope-panel'),
                        tag: a ? a.tagName : null,
                        isTrigger: !!(a && a.classList &&
                                      a.classList.contains('scope-trigger')),
                        expanded: (() => {
                          const t = document.querySelector('.scope-trigger');
                          return t ? t.getAttribute('aria-expanded') : null;
                        })()};
            }""")
        report["desktop_scope_escape"] = after_esc
        if after_esc["panel"]:
            fails.append("desktop: Esc не закрывает панель области")
        if not after_esc["isTrigger"] or after_esc["tag"] == "BODY":
            fails.append("desktop: после Esc фокус не вернулся в .scope-trigger "
                         "(activeElement=%s)" % after_esc["tag"])
        if after_esc["expanded"] != "false":
            fails.append("desktop: aria-expanded триггера не сброшен после Esc")

        # rail: сворачивание + персист
        page.click("[data-sidebar-collapse]")
        page.wait_for_timeout(350)
        rail = page.evaluate(PROBE_SHELL)
        report["desktop_rail"] = rail
        if not rail["collapsed"]:
            fails.append("desktop: rail-класс не применился")
        if rail["sidebar"] and rail["sidebar"]["w"] > 80:
            fails.append("desktop: rail шириной %s px" % rail["sidebar"]["w"])
        if rail["sidebarLabels"]:
            fails.append("desktop: в rail остались подписи разделов")
        if rail["mainX"] != (rail["sidebar"] or {}).get("w"):
            fails.append("desktop: контент не сдвинулся за rail (%s vs %s)"
                         % (rail["mainX"], (rail["sidebar"] or {}).get("w")))
        if rail["over"]:
            fails.append("desktop: rail → горизонтальный скролл")
        shot(page, "desktop-rail")
        page.reload(wait_until="load")
        page.wait_for_selector(".app-shell", timeout=10000)
        page.wait_for_timeout(800)
        persisted = page.evaluate(PROBE_SHELL)
        report["desktop_rail_persisted"] = persisted
        if not persisted["collapsed"]:
            fails.append("desktop: rail-состояние не персистится после reload")
        page.click("[data-sidebar-collapse]")   # назад в полную панель
        page.wait_for_timeout(300)

        # модалка модуля: в вьюпорте, внутренний скролл, фокус в диалоге
        page.evaluate("""() => {
            const vm = window.__adminbotVm;
            if (!vm || !vm.modules || !vm.modules.length) return;
            vm.openModuleWindow(vm.modules[0]);
        }""")
        page.wait_for_timeout(700)
        modal = page.evaluate(r"""() => {
            const m = document.querySelector('.modal-card');
            if (!m) return {modal: false};
            const r = m.getBoundingClientRect();
            const body = m.querySelector('.modal-body');
            return {modal: true,
                    inViewport: r.top >= -1 && r.left >= -1
                                && r.right <= window.innerWidth + 1
                                && r.bottom <= window.innerHeight + 1,
                    bodyScroll: body ? getComputedStyle(body).overflowY : null,
                    focusInside: m.contains(document.activeElement),
                    overflowPage: document.documentElement.scrollWidth
                                  > window.innerWidth + 1};
        }""")
        report["desktop_modal"] = modal
        if modal.get("modal"):
            if not modal["inViewport"]:
                fails.append("desktop: модалка вне вьюпорта")
            if modal["bodyScroll"] != "auto":
                fails.append("desktop: у модалки нет внутреннего скролла")
            if not modal["focusInside"]:
                fails.append("desktop: фокус не входит в модалку")
        shot(page, "desktop-modal")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        if errs:
            fails.append("desktop: console errors: %s" % errs[:3])
        report["desktop_console"] = errs[:5]
        ctx.close()

        # ── tablet 900: drawer ──────────────────────────────────────────
        ctx2 = browser.new_context(viewport={"width": 900, "height": 700})
        ctx2.add_init_script(M.TMA_STUB)
        ctx2.route("**/api/**", _routes())
        p2 = ctx2.new_page()
        p2.goto(_app() + "#/memory", wait_until="load")
        p2.wait_for_selector(".app-shell", timeout=10000)
        p2.wait_for_timeout(900)
        d2 = p2.evaluate(PROBE_SHELL)
        report["tablet"] = d2
        if d2["headerH"] > HEAD_MAX_MOBILE:
            fails.append("tablet: шапка %s px (высокая)" % d2["headerH"])
        if d2["over"]:
            fails.append("tablet: горизонтальный скролл")
        p2.click("[data-drawer-trigger]")
        p2.wait_for_timeout(450)
        dr = p2.evaluate(r"""() => {
            const d = document.querySelector('.app-drawer');
            const r = d.getBoundingClientRect();
            return {open: d.classList.contains('open'), w: Math.round(r.width),
                    x: Math.round(r.x),
                    focusInside: d.contains(document.activeElement),
                    ariaHidden: d.getAttribute('aria-hidden')};
        }""")
        report["tablet_drawer"] = dr
        if not dr["open"] or dr["x"] < -1:
            fails.append("tablet: drawer не открылся на месте")
        if not dr["focusInside"]:
            fails.append("tablet: фокус не входит в drawer")
        if dr["ariaHidden"] != "false":
            fails.append("tablet: aria-hidden drawer не снят")
        shot(p2, "tablet-drawer")
        p2.keyboard.press("Escape")
        p2.wait_for_timeout(300)
        back = p2.evaluate(r"""() => ({
            open: document.querySelector('.app-drawer')
                  .classList.contains('open'),
            triggerFocused: !!document.activeElement
              && document.activeElement.hasAttribute('data-drawer-trigger'),
        })""")
        report["tablet_drawer_closed"] = back
        if back["open"] or not back["triggerFocused"]:
            fails.append("tablet: Esc/focus-возврат drawer не работает: %s" % back)
        ctx2.close()

        # ── mobile 390 ─────────────────────────────────────────────────
        ctx3 = browser.new_context(viewport={"width": 390, "height": 844})
        ctx3.add_init_script(M.TMA_STUB)
        ctx3.route("**/api/**", _routes())
        p3 = ctx3.new_page()
        p3.goto(_app() + "#/oversight", wait_until="load")
        p3.wait_for_selector(".app-shell", timeout=10000)
        p3.wait_for_timeout(900)
        d3 = p3.evaluate(PROBE_SHELL)
        report["mobile"] = d3
        if d3["over"]:
            fails.append("mobile: горизонтальный скролл")
        if d3["overlap"]:
            fails.append("mobile: контент под шапкой")
        if d3["headerH"] > HEAD_MAX_MOBILE:
            fails.append("mobile: шапка %s px" % d3["headerH"])
        fails.extend(_ghost_fails(d3["fsBtn"], "mobile"))
        p3.locator("header.header-sticky").screenshot(
            path=os.path.join(out_dir, "w7-nav-fs-ghost-header-390.png"))

        p3.click(".scope-trigger")
        p3.wait_for_timeout(400)
        pj3 = p3.evaluate(PROBE_PANEL)
        report["mobile_panel"] = pj3
        if not pj3.get("open"):
            fails.append("mobile: панель области не открылась")
        else:
            if not pj3["insideViewport"]:
                fails.append("mobile: панель области вне вьюпорта")
            if _backdrop_alpha(pj3["bg"]) < 0.9:
                fails.append("mobile: подложка панели слишком прозрачна")
        shot(p3, "mobile-scope-panel")
        p3.keyboard.press("Escape")
        p3.wait_for_timeout(250)
        p3.click(".mobile-topnav-more")
        p3.wait_for_timeout(400)
        more = p3.evaluate(r"""() => {
            const m = document.querySelector('.more-menu-panel');
            if (!m) return null;
            const r = m.getBoundingClientRect();
            return {inside: r.left >= -1 && r.right <= window.innerWidth + 1
                            && r.top >= -1
                            && r.bottom <= window.innerHeight + 1,
                    bottom: Math.round(r.bottom), vh: window.innerHeight};
        }""")
        report["mobile_more"] = more
        if not more:
            fails.append("mobile: меню «Ещё» не открылось")
        elif not more["inside"]:
            fails.append("mobile: меню «Ещё» вне вьюпорта")
        shot(p3, "mobile-more")
        ctx3.close()

        # ── 320 + zoom 200% + slow API ─────────────────────────────────
        for (w, h, zoom, delay) in ((320, 700, 1, 0), (1280, 800, 2, 0),
                                    (1280, 800, 1, 900)):
            c = browser.new_context(viewport={"width": w, "height": h})
            c.add_init_script(M.TMA_STUB)
            c.route("**/api/**", _routes(delay))
            pg = c.new_page()
            pg.goto(_app() + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=10000)
            pg.wait_for_timeout(700)
            if zoom > 1:
                pg.evaluate("(z) => { document.body.style.zoom = z; }", str(zoom))
                pg.wait_for_timeout(400)
            key = "%dx%d-z%d-d%d" % (w, h, zoom, delay)
            shell = pg.evaluate(PROBE_SHELL)
            report["case_" + key] = {k: shell[k] for k in
                                     ("vw", "sw", "over", "headerH",
                                      "overlap", "mainX")}
            if shell["over"]:
                fails.append("%s: горизонтальный скролл %s > %s"
                             % (key, shell["sw"], shell["vw"]))
            if shell["overlap"]:
                fails.append("%s: контент под шапкой" % key)
            shot(pg, "case-" + key)
            c.close()

        # ── EVOL-024: машинная инвентаризация 19 маршрутов × 6 вьюпортов ──
        # Ревью W7 (31.10.2026): «19×6» должен существовать как артефакт, а не
        # как утверждение в отчёте. Пишем w7-nav-inventory.json (ячейка на
        # маршрут×вьюпорт: h-скролл, элементы за вьюпортом, обрезанный текст).
        inv = {"routes": INV_ROUTES, "viewports": [], "cells": [],
               "failures": []}
        for (vw, vh) in INV_VIEWPORTS:
            c = browser.new_context(viewport={"width": vw, "height": vh})
            c.add_init_script(M.TMA_STUB)
            c.route("**/api/**", _routes())
            pg = c.new_page()
            pg.goto(_app() + "#/", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=10000)
            pg.wait_for_timeout(900)
            vp = "%dx%d" % (vw, vh)
            inv["viewports"].append(vp)
            for route in INV_ROUTES:
                pg.evaluate("(r) => { window.location.hash = r; }", route)
                pg.wait_for_timeout(400)
                cell = pg.evaluate(INV_PROBE)
                cell["viewport"] = vp
                cell["route"] = route
                inv["cells"].append(cell)
                if cell["hScroll"]:
                    inv["failures"].append(
                        "%s %s: горизонтальный скролл %s > %s"
                        % (vp, route, cell["sw"], cell["vw"]))
                if cell["offCount"]:
                    inv["failures"].append(
                        "%s %s: элементов за вьюпортом %s %s"
                        % (vp, route, cell["offCount"], cell["offscreen"][:2]))
                if cell["clippedCount"]:
                    inv["failures"].append(
                        "%s %s: обрезанный текст без ellipsis %s %s"
                        % (vp, route, cell["clippedCount"], cell["clipped"][:2]))
            c.close()
        inv["summary"] = {
            "routes": len(INV_ROUTES), "viewports": len(INV_VIEWPORTS),
            "cells": len(inv["cells"]),
            "hScroll": sum(1 for x in inv["cells"] if x["hScroll"]),
            "offscreen": sum(1 for x in inv["cells"] if x["offCount"]),
            "clipped": sum(1 for x in inv["cells"] if x["clippedCount"]),
            "failures": len(inv["failures"]),
        }
        with open(os.path.join(out_dir, "w7-nav-inventory.json"), "w",
                  encoding="utf-8") as f:
            json.dump(inv, f, ensure_ascii=False, indent=1)
        report["inventory_summary"] = inv["summary"]
        print("[inventory] %s" % json.dumps(inv["summary"], ensure_ascii=False))
        fails.extend(inv["failures"][:30])

        browser.close()
    httpd.shutdown()

    report["failures"] = fails
    with open(os.path.join(out_dir, "w7-nav-probe.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if fails:
        print("EVOL-W7-NAV FAIL (%d):" % len(fails))
        for f_ in fails:
            print(" -", f_)
        return 1
    print("EVOL-W7-NAV OK — артефакты: %s" % out_dir)
    return 0


def main() -> int:
    out = DEFAULT_SHOTS
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    return run(out)


if __name__ == "__main__":
    sys.exit(main())
