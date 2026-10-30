"""EVOL-025 (W9) — живая проверка сквозной адаптивности Mini App.

Детерминированный Playwright-прогон НАСТОЯЩЕГО `web/index.html` + `web/app.js`
+ `web/static/app.css` (сервер/стабы API — из `tools/ui_round1025_matrix.py`,
секретов нет, живых сообщений в Telegram не отправляется).

Проверяется (plans/current_task.md L341–355 + EVOL-033 §C L517–527):
  * адаптивность по ФАКТИЧЕСКОМУ размеру: 320/360/390/430, 600/768/1024,
    1440/1920, низкий ландшафт, zoom 200 %;
  * портрет телефона: шапка — одна рабочая строка (контент начинается рано),
    навигация — нижняя панель разделов (тач-цель ≥44, без горизонтального
    скролла), длинные названия не перекрываются;
  * низкий ландшафт: mobile shell — плавающий рейл (высоту не занимает),
    compact shell — шапка в одну строку; контент получает реальную высоту;
  * планшет/десктоп: сетки по месту, нет «островка» фиксированной ширины;
  * модалки на узком экране — bottom sheet (низ, скругление сверху,
    safe-area, внутренний скролл, клавиатура), на десктопе — окно по центру;
  * меню «Ещё» — лист НАД нижней панелью, в границах вьюпорта, Esc + фокус;
  * инвентаризация: N маршрутов × M вьюпортов — нет h-скролла страницы,
    нет элементов за вьюпортом, нет обрезанного без ellipsis текста;
  * CLS: суммарный layout shift на загрузке в пределах бюджета;
  * поворот (портрет → ландшафт) без перезагрузки: режим навигации меняется,
    h-скролл не появляется.

Запуск: .venv\\Scripts\\python.exe tools\\ui_evol_w9_responsive_e2e.py [--out DIR]
        [--baseline REV]   # замерить базовую ревизию (git show) для сравнения
Артефакты по умолчанию: plans/features/evol/audit/evidence/
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M            # noqa: E402  сервер/стабы/TMA
# Инвентаризационный зонд переиспользуется из W7 (один источник эвристики
# «элемент за вьюпортом / обрезанный текст»), чтобы не заводить второй.
import ui_evol_w7_nav_e2e as W7            # noqa: E402

INV_PROBE = W7.INV_PROBE

PORT = 8843
DEFAULT_SHOTS = os.path.join(REPO, "plans", "features", "evol", "audit",
                             "evidence")

PHONES = ((320, 568), (360, 640), (390, 844), (430, 932))
MIDS = ((600, 800), (768, 1024), (1024, 768))
WIDES = ((1440, 900), (1920, 1080))
LANDSCAPES = ((667, 375), (812, 375), (932, 430))
ZOOMS = ((1280, 800), (390, 844))   # моделируются как CSS-вьюпорт / 2

MAIN_ROUTES = ("#/", "#/modules", "#/memory", "#/oversight", "#/ai")
INV_VIEWPORTS = ((320, 568), (390, 844), (600, 800), (768, 1024),
                 (1024, 768), (1440, 900), (1920, 1080), (667, 375))

# Бюджеты (тестовое ориентирование, не «device table»):
HEAD_MAX_PHONE = 78          # одна рабочая строка + safe area
HEAD_MAX_LAND = 62           # низкий ландшафт: ровно одна строка
HEAD_MAX_MID = 132           # 768–1199 — утверждённая двухстрочная шапка
MAIN_TOP_MAX_PHONE = 92      # контент начинается рано
NAV_MIN_TOUCH = 44
CONTENT_SHARE_PHONE = 0.62   # доля видимой высоты под контент в портрете
CONTENT_SHARE_LAND = 0.72    # в низком ландшафте рейл высоту не занимает
CLS_BUDGET = 0.25


class _Handler(SimpleHTTPRequestHandler):
    """Статика репозитория (или базовой копии) без кэша."""

    root = REPO

    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0].split("#")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[1:]
        elif p in ("/", "", "/index.html"):
            rel = "web/index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(self.root, rel.replace("/", os.sep))

    def log_message(self, *args):  # тишина в выводе
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def _routes(extra_delay_ms=0):
    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/config") and extra_delay_ms:
            import time
            time.sleep(extra_delay_ms / 1000.0)
        if url.endswith("/api/config"):
            hdrs = route.request.headers or {}
            payload = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                       else M.CONFIG_STUB)
        else:
            payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return _route


# ── зонды ────────────────────────────────────────────────────────────────────
PROBE_SHELL = r"""
() => {
  const de = document.documentElement;
  const hdr = document.querySelector('header.header-sticky');
  const main = document.querySelector('main.scroll-area');
  const nav = document.querySelector('.mobile-topnav');
  const shell = document.querySelector('.app-shell');
  const hb = hdr ? hdr.getBoundingClientRect() : null;
  const mb = main ? main.getBoundingClientRect() : null;
  const nb = nav ? nav.getBoundingClientRect() : null;
  const sb = shell ? shell.getBoundingClientRect() : null;
  const navCs = nav ? getComputedStyle(nav) : null;
  const scrolled = main ? (main.scrollHeight > main.clientHeight + 1) : null;
  const contentH = mb ? mb.height : null;
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    sw: de.scrollWidth,
    hScroll: de.scrollWidth > window.innerWidth + 1,
    shellMode: de.getAttribute('data-shell-mode'),
    sheetMode: de.classList.contains('w9-sheet-bottom'),
    headerH: hb ? Math.round(hb.height) : null,
    headerBottom: hb ? Math.round(hb.bottom) : null,
    headerRows: hb && hdr
      ? Array.from(hdr.children).filter(el => {
          const r = el.getBoundingClientRect();
          const cs = getComputedStyle(el);
          return r.height > 1 && cs.display !== 'none'
            && cs.position !== 'fixed';
        }).length : null,
    mainTop: mb ? Math.round(mb.top) : null,
    mainH: mb ? Math.round(mb.height) : null,
    mainBottom: mb ? Math.round(mb.bottom) : null,
    contentTopGap: (hb && mb) ? Math.round(mb.top - hb.bottom) : null,
    overlap: (hb && mb) ? Math.max(0, Math.round(hb.bottom - mb.top)) : null,
    navPresent: !!nav,
    navH: nb ? Math.round(nb.height) : null,
    navTop: nb ? Math.round(nb.top) : null,
    navBottom: nb ? Math.round(nb.bottom) : null,
    navFixed: navCs ? navCs.position : null,
    navFlexDir: navCs ? navCs.flexDirection : null,
    navInsideHeader: nav ? !!nav.closest('header') : null,
    navInsideViewport: nb ? (nb.top >= -1 && nb.bottom <= window.innerHeight + 1) : null,
    shellBottom: sb ? Math.round(sb.bottom) : null,
    contentShare: (contentH && window.innerHeight)
      ? +(contentH / window.innerHeight).toFixed(3) : null,
    scrollable: scrolled,
  };
}
"""

PROBE_TOUCH = r"""
() => {
  const sel = 'button, a[href], select, input[type="checkbox"], ' +
              'input[type="radio"], summary, [role="button"], ' +
              '[role="option"], [role="menuitem"], [role="switch"]';
  const bad = [];
  const nodes = document.querySelectorAll(sel);
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (parseFloat(cs.opacity) === 0) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    if (el.classList.contains('sr-only')) continue;
    if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (r.bottom < 0 || r.top > window.innerHeight) continue;
    if (r.width >= 43.5 && r.height >= 43.5) continue;
    // Инлайновая текстовая ссылка/абзацный control — исключение WCAG 2.5.8.
    const inlineText = (el.tagName === 'A' || el.tagName === 'SUMMARY')
      && cs.display.indexOf('inline') === 0 && el.textContent.trim().length > 12;
    if (inlineText) continue;
    const cls = (el.className && el.className.toString ? el.className.toString() : '')
      .split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    bad.push(el.tagName.toLowerCase() + (cls ? '.' + cls : '')
             + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  }
  return {total: nodes.length, bad: bad.length, sample: bad.slice(0, 8)};
}
"""

PROBE_MODAL = r"""
() => {
  const m = document.querySelector('.modal-card');
  if (!m) return {modal: false};
  const r = m.getBoundingClientRect();
  const cs = getComputedStyle(m);
  const body = m.querySelector('.modal-body');
  const de = document.documentElement;
  return {
    modal: true,
    sheetClass: de.classList.contains('w9-sheet-bottom'),
    x: Math.round(r.x), w: Math.round(r.width),
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    vw: window.innerWidth, vh: window.innerHeight,
    inViewport: r.top >= -1 && r.left >= -1
                && r.right <= window.innerWidth + 1
                && r.bottom <= window.innerHeight + 1,
    radiusTop: cs.borderTopLeftRadius, radiusBottom: cs.borderBottomLeftRadius,
    padBottom: cs.paddingBottom,
    bodyScroll: body ? getComputedStyle(body).overflowY : null,
    bodyScrollable: body ? body.scrollHeight > body.clientHeight + 1 : null,
    focusInside: m.contains(document.activeElement),
    hScroll: de.scrollWidth > window.innerWidth + 1,
  };
}
"""

PROBE_MORE = r"""
() => {
  const p = document.querySelector('.more-menu-panel');
  if (!p) return {open: false};
  const r = p.getBoundingClientRect();
  const nav = document.querySelector('.mobile-topnav');
  const nb = nav ? nav.getBoundingClientRect() : null;
  const navCs = nav ? getComputedStyle(nav) : null;
  return {
    open: true,
    x: Math.round(r.x), y: Math.round(r.y),
    w: Math.round(r.width), h: Math.round(r.height),
    bottom: Math.round(r.bottom),
    vw: window.innerWidth, vh: window.innerHeight,
    inside: r.left >= -1 && r.right <= window.innerWidth + 1
            && r.top >= -1 && r.bottom <= window.innerHeight + 1,
    aboveNav: (nb && navCs && navCs.position !== 'fixed')
      ? r.bottom <= nb.top + 2 : true,
    gapToNav: (nb && navCs && navCs.position !== 'fixed')
      ? Math.round(nb.top - r.bottom) : null,
    clearOfRail: (nb && navCs && navCs.position === 'fixed')
      ? r.right <= nb.left + 2 : true,
    scrolls: p.scrollHeight > p.clientHeight + 1,
    focusInside: p.contains(document.activeElement),
  };
}
"""

PROBE_SCOPE = r"""
() => {
  const t = document.querySelector('.scope-trigger');
  const p = document.querySelector('.scope-panel');
  if (!t) return {trigger: false};
  const tr = t.getBoundingClientRect();
  const out = {trigger: true, triggerW: Math.round(tr.width),
               triggerH: Math.round(tr.height),
               triggerInside: tr.left >= -1
                              && tr.right <= window.innerWidth + 1};
  if (!p) { out.open = false; return out; }
  const r = p.getBoundingClientRect();
  const mid = document.elementFromPoint(
    Math.min(window.innerWidth - 2, r.left + r.width / 2),
    Math.min(window.innerHeight - 2, r.top + Math.max(6, r.height / 2)));
  out.open = true;
  out.x = Math.round(r.x); out.y = Math.round(r.y);
  out.inside = r.left >= -1 && r.right <= window.innerWidth + 1
               && r.top >= -1 && r.bottom <= window.innerHeight + 1;
  out.hitTestInside = mid ? (p.contains(mid) || mid === p) : false;
  out.hScroll = document.documentElement.scrollWidth > window.innerWidth + 1;
  return out;
}
"""

PROBE_CLS = r"""
() => {
  const e = performance.getEntriesByType('layout-shift');
  let sum = 0;
  for (let i = 0; i < e.length; i++) if (!e[i].hadRecentInput) sum += e[i].value;
  return {cls: +sum.toFixed(4), entries: e.length};
}
"""

PROBE_GRIDS = r"""
() => {
  const out = {};
  const pick = (sel, name) => {
    const el = document.querySelector(sel);
    if (!el) return;
    const cs = getComputedStyle(el);
    out[name] = {cols: cs.gridTemplateColumns.split(' ').filter(Boolean).length,
                 width: Math.round(el.getBoundingClientRect().width),
                 maxWidth: cs.maxWidth};
  };
  pick('.module-list', 'moduleList');
  pick('.hub-grid', 'hubGrid');
  pick('main.scroll-area', 'main');
  return out;
}
"""


def run(out_dir, baseline=None, port=PORT):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    fails = []
    report = {"viewports": {}, "checks": {}}

    tmp_root = None
    if baseline:
        base_dir = os.environ.get("OPENCODE_WORKSPACE_DATA")
        runs = os.path.join(base_dir, "runs") if base_dir else None
        if not (runs and os.path.isdir(runs)):
            runs = tempfile.gettempdir()
        tmp_root = tempfile.mkdtemp(prefix="w9-base-", dir=runs)
        _Handler.root = tmp_root
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only",
                                baseline, "web/"], capture_output=True,
                               text=True, check=True).stdout.split()
        for rel in files:
            dest = os.path.join(tmp_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            blob = subprocess.run(["git", "show", "%s:%s" % (baseline, rel)],
                                  capture_output=True, check=True).stdout
            with open(dest, "wb") as f:
                f.write(blob)
    else:
        _Handler.root = REPO

    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = "http://127.0.0.1:%d/web/index.html" % port

    def shot(page, name):
        page.screenshot(path=os.path.join(out_dir, "w9-responsive-%s.png"
                                          % name))

    def click(page, sel, where, timeout=8000):
        """Клик с диагностикой: при провале печатаем состояние страницы."""
        try:
            page.click(sel, timeout=timeout)
            return True
        except Exception as exc:  # noqa: BLE001
            try:
                info = page.evaluate(r"""(sel) => {
                    const el = document.querySelector(sel);
                    const all = document.querySelectorAll(sel).length;
                    if (!el) return {count: all, found: false,
                                     mode: document.documentElement
                                       .getAttribute('data-shell-mode')};
                    const r = el.getBoundingClientRect();
                    const cs = getComputedStyle(el);
                    const mid = document.elementFromPoint(
                        r.left + r.width / 2, r.top + r.height / 2);
                    return {count: all, found: true,
                            rect: [Math.round(r.x), Math.round(r.y),
                                   Math.round(r.width), Math.round(r.height)],
                            display: cs.display, visibility: cs.visibility,
                            position: cs.position,
                            topEl: mid ? (mid.tagName + '.' +
                              (mid.className || '').toString().slice(0, 60)) : null};
                }""", sel)
            except Exception:  # noqa: BLE001
                info = {"eval": "failed"}
            print("[click-fail] %s %s %s: %s" % (where, sel, str(exc)[:120],
                                                 json.dumps(info,
                                                            ensure_ascii=False)))
            raise

    def open_ctx(browser, w, h):
        # Мобильная эмуляция для телефонов: DPR 3, touch — реальный сценарий
        # WebView, а не «узкое окно десктопа».
        phone = w <= 430
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=3 if phone else 1,
            is_mobile=phone, has_touch=phone,
        )
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _routes())
        return ctx

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── 1. Портрет телефона: шапка/навигация/верх контента ──────────────
        for (w, h) in PHONES:
            key = "phone-%dx%d" % (w, h)
            ctx = open_ctx(browser, w, h)
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text[:160])
                  if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
            pg.goto(base_url + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=15000)
            pg.wait_for_timeout(900)
            d = pg.evaluate(PROBE_SHELL)
            d["cls"] = pg.evaluate(PROBE_CLS)
            report["viewports"][key] = d
            if d["hScroll"]:
                fails.append("%s: горизонтальный скролл %s > %s"
                             % (key, d["sw"], d["vw"]))
            if d["overlap"]:
                fails.append("%s: контент под шапкой на %s px"
                             % (key, d["overlap"]))
            if d["shellMode"] != "mobile":
                fails.append("%s: data-shell-mode=%r (ожидался mobile)"
                             % (key, d["shellMode"]))
            if not d["sheetMode"]:
                fails.append("%s: не включён bottom-sheet режим модалок" % key)
            if d["headerH"] is None or d["headerH"] > HEAD_MAX_PHONE:
                fails.append("%s: шапка %s px > %d (вторая строка вернулась?)"
                             % (key, d["headerH"], HEAD_MAX_PHONE))
            if d["mainTop"] is None or d["mainTop"] > MAIN_TOP_MAX_PHONE:
                fails.append("%s: контент начинается на %s px"
                             % (key, d["mainTop"]))
            if not d["navPresent"]:
                fails.append("%s: нижней панели разделов нет" % key)
            elif d["navInsideHeader"]:
                fails.append("%s: блок навигации остался внутри шапки" % key)
            else:
                if d["navH"] < NAV_MIN_TOUCH:
                    fails.append("%s: панель %s px ниже тач-минимума"
                                 % (key, d["navH"]))
                if d["navBottom"] and d["shellBottom"] and \
                        abs(d["navBottom"] - d["shellBottom"]) > 2:
                    fails.append("%s: панель не прижата к низу shell (%s vs %s)"
                                 % (key, d["navBottom"], d["shellBottom"]))
            if d["contentShare"] is not None and \
                    d["contentShare"] < CONTENT_SHARE_PHONE:
                fails.append("%s: контенту остаётся %s высоты (<%s)"
                             % (key, d["contentShare"], CONTENT_SHARE_PHONE))
            if d["cls"]["cls"] > CLS_BUDGET:
                fails.append("%s: CLS %s > %s" % (key, d["cls"]["cls"], CLS_BUDGET))

            # тач-цели на главных маршрутах: КОНТРАКТ — ни одного интерактивного
            # контрола меньше 44×44 (инлайновые текстовые ссылки исключены выше).
            worst = {"route": None, "bad": 0, "sample": []}
            for route in MAIN_ROUTES:
                pg.evaluate("(r) => { window.location.hash = r; }", route)
                pg.wait_for_timeout(350)
                t = pg.evaluate(PROBE_TOUCH)
                report["checks"].setdefault(key + "-touch", {})[route] = t
                if t["bad"] > worst["bad"]:
                    worst = {"route": route, "bad": t["bad"],
                             "sample": t["sample"], "total": t["total"]}
            if worst["bad"]:
                fails.append("%s: контролы <44×44 на %s: %s"
                             % (key, worst["route"], worst["sample"][:4]))
            acc = pg.evaluate(r"""() => {
                const b = document.querySelector('button[aria-label="Обновить"]');
                if (!b) return null;
                const r = b.getBoundingClientRect();
                return {w: Math.round(r.width), h: Math.round(r.height)};
            }""")
            if acc and (acc["w"] < 44 or acc["h"] < 44):
                fails.append("%s: иконочная «Обновить» %sx%s < 44"
                             % (key, acc["w"], acc["h"]))

            # селектор области: открытие/границы/тач-цель
            pg.evaluate("(r) => { window.location.hash = r; }", "#/modules")
            pg.wait_for_timeout(300)
            click(pg, ".scope-trigger", key)
            pg.wait_for_timeout(320)
            sc = pg.evaluate(PROBE_SCOPE)
            report["checks"][key + "-scope"] = sc
            if sc.get("triggerH", 0) < NAV_MIN_TOUCH:
                fails.append("%s: триггер области %s px < 44"
                             % (key, sc.get("triggerH")))
            if not sc.get("open"):
                fails.append("%s: панель области не открылась" % key)
            elif not sc.get("inside") or not sc.get("hitTestInside"):
                fails.append("%s: панель области вне вьюпорта/перекрыта" % key)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(220)

            # меню «Ещё» над нижней панелью
            click(pg, ".mobile-topnav-more", key)
            pg.wait_for_timeout(320)
            mm = pg.evaluate(PROBE_MORE)
            report["checks"][key + "-more"] = mm
            if not mm.get("open"):
                fails.append("%s: меню «Ещё» не открылось" % key)
            else:
                if not mm["inside"]:
                    fails.append("%s: меню «Ещё» вне вьюпорта" % key)
                if not mm["aboveNav"]:
                    fails.append("%s: меню «Ещё» перекрывает нижнюю панель" % key)
                if mm.get("gapToNav") is not None and mm["gapToNav"] > 12:
                    fails.append("%s: лист «Ещё» не прижат к панели (зазор %s px)"
                                 % (key, mm["gapToNav"]))
                if not mm["focusInside"]:
                    fails.append("%s: фокус не вошёл в меню «Ещё»" % key)
            shot(pg, key + "-more")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(220)
            back = pg.evaluate(r"""() => ({
                open: !!document.querySelector('.more-menu-panel'),
                focusedTrigger: !!(document.activeElement
                  && document.activeElement.classList
                  && document.activeElement.classList.contains('mobile-topnav-more')),
            })""")
            if back["open"] or not back["focusedTrigger"]:
                fails.append("%s: Esc/возврат фокуса меню «Ещё»: %s"
                             % (key, back))

            # модалка = bottom sheet
            pg.evaluate("""() => {
                const vm = window.__adminbotVm;
                if (vm && vm.modules && vm.modules.length) {
                    vm.openModuleWindow(vm.modules[0]);
                }
            }""")
            pg.wait_for_timeout(600)
            md = pg.evaluate(PROBE_MODAL)
            report["checks"][key + "-modal"] = md
            if md.get("modal"):
                if not md["sheetClass"]:
                    fails.append("%s: модалка без sheet-режима" % key)
                if not md["inViewport"]:
                    fails.append("%s: модалка вне вьюпорта" % key)
                if abs(md["bottom"] - md["vh"]) > 2:
                    fails.append("%s: лист модалки не прижат к низу (%s vs %s)"
                                 % (key, md["bottom"], md["vh"]))
                if md["radiusBottom"] not in ("0px", "0%"):
                    fails.append("%s: у листа снизу скругление %s"
                                 % (key, md["radiusBottom"]))
                if md["bodyScroll"] != "auto":
                    fails.append("%s: у листа нет внутреннего скролла" % key)
                if not md["focusInside"]:
                    fails.append("%s: фокус не вошёл в лист модалки" % key)
                if md["hScroll"]:
                    fails.append("%s: модалка дала горизонтальный скролл" % key)
                shot(pg, key + "-modal-sheet")
                # виртуальная клавиатура: --kb-offset поднимает лист
                pg.evaluate("() => document.documentElement.style"
                            ".setProperty('--kb-offset', '280px')")
                pg.wait_for_timeout(220)
                kb = pg.evaluate(PROBE_MODAL)
                report["checks"][key + "-modal-kb"] = {
                    "bottom": kb.get("bottom"), "vh": kb.get("vh")}
                if kb.get("modal") and kb["bottom"] > kb["vh"] - 280 + 4:
                    fails.append("%s: лист не поднялся над клавиатурой (%s)"
                                 % (key, kb["bottom"]))
                pg.evaluate("() => document.documentElement.style"
                            ".removeProperty('--kb-offset')")
            else:
                fails.append("%s: модалка не открылась" % key)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(220)
            if errs:
                fails.append("%s: console errors: %s" % (key, errs[:2]))
            shot(pg, key + "-modules")

            # safe area Telegram: панель поднимается над системной зоной
            sa = pg.evaluate(r"""() => {
                const de = document.documentElement;
                const nav = document.querySelector('.mobile-topnav');
                const before = nav ? Math.round(nav.getBoundingClientRect().height) : null;
                de.style.setProperty('--tg-safe-area-inset-bottom', '34px');
                const after = nav ? Math.round(nav.getBoundingClientRect().height) : null;
                const shell = document.querySelector('.app-shell');
                const nb = nav ? nav.getBoundingClientRect() : null;
                const sb = shell ? shell.getBoundingClientRect() : null;
                de.style.removeProperty('--tg-safe-area-inset-bottom');
                return {before: before, after: after,
                        navInsideShell: (nb && sb) ? nb.bottom <= sb.bottom + 1 : null};
            }""")
            report["checks"][key + "-safearea"] = sa
            if sa["before"] is not None and (sa["after"] or 0) - sa["before"] < 30:
                fails.append("%s: нижний safe-area не учтён панелью (%s→%s)"
                             % (key, sa["before"], sa["after"]))
            ctx.close()

        # ── 2. Низкий ландшафт ─────────────────────────────────────────────
        for (w, h) in LANDSCAPES:
            key = "land-%dx%d" % (w, h)
            ctx = open_ctx(browser, w, h)
            pg = ctx.new_page()
            pg.goto(base_url + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=15000)
            pg.wait_for_timeout(900)
            d = pg.evaluate(PROBE_SHELL)
            report["viewports"][key] = d
            mobile = d["shellMode"] == "mobile"
            if d["hScroll"]:
                fails.append("%s: горизонтальный скролл" % key)
            if d["overlap"]:
                fails.append("%s: контент под шапкой" % key)
            if d["headerH"] is None or d["headerH"] > HEAD_MAX_LAND:
                fails.append("%s: шапка %s px в низком ландшафте (нужна одна "
                             "строка)" % (key, d["headerH"]))
            if d["mainTop"] is None or d["mainTop"] > HEAD_MAX_LAND + 6:
                fails.append("%s: контент начинается на %s px"
                             % (key, d["mainTop"]))
            if mobile:
                if not d["navPresent"]:
                    fails.append("%s: рейла навигации нет" % key)
                else:
                    if d["navFlexDir"] != "column":
                        fails.append("%s: nav не перестроилась в рейл (%s)"
                                     % (key, d["navFlexDir"]))
                    if d["navFixed"] != "fixed":
                        fails.append("%s: рейл не плавающий (%s)"
                                     % (key, d["navFixed"]))
                    if d["mainBottom"] and d["shellBottom"] and \
                            abs(d["mainBottom"] - d["shellBottom"]) > 2:
                        fails.append("%s: рейл отнял высоту у контента" % key)
                if d["contentShare"] is not None and \
                        d["contentShare"] < CONTENT_SHARE_LAND:
                    fails.append("%s: контенту остаётся %s высоты (<%s)"
                                 % (key, d["contentShare"], CONTENT_SHARE_LAND))
                under = pg.evaluate(r"""() => {
                    const nav = document.querySelector('.mobile-topnav');
                    const main = document.querySelector('main.scroll-area');
                    if (!nav || !main) return null;
                    const nb = nav.getBoundingClientRect();
                    const mb = main.getBoundingClientRect();
                    // Контентом считается РАБОЧАЯ область main: рамка main
                    // растянута на всю ширину, а резерв справа задан padding.
                    const cs = getComputedStyle(main);
                    const contentRight = mb.right - parseFloat(cs.paddingRight || 0);
                    let widest = contentRight;
                    const kids = main.children;
                    for (let i = 0; i < kids.length; i++) {
                        const kr = kids[i].getBoundingClientRect();
                        if (kr.width > 1 && kr.right > widest) widest = kr.right;
                    }
                    return {contentRight: Math.round(contentRight),
                            widestChildRight: Math.round(widest),
                            railLeft: Math.round(nb.left),
                            paddingRight: cs.paddingRight,
                            ok: widest <= nb.left + 2};
                }""")
                report["checks"][key + "-rail"] = under
                if under and not under["ok"]:
                    fails.append("%s: контент уходит под рейл (right %s > rail %s)"
                                 % (key, under["widestChildRight"],
                                    under["railLeft"]))
                click(pg, ".mobile-topnav-more", key)
                pg.wait_for_timeout(320)
                mm = pg.evaluate(PROBE_MORE)
                report["checks"][key + "-more"] = mm
                if not mm.get("open"):
                    fails.append("%s: меню «Ещё» из рейла не открылось" % key)
                else:
                    if not mm["inside"]:
                        fails.append("%s: меню «Ещё» вне вьюпорта" % key)
                    if not mm["clearOfRail"]:
                        fails.append("%s: меню «Ещё» накрыло рейл" % key)
                    shot(pg, key + "-more")
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(200)
            else:
                # compact shell: навигация — drawer, шапка в одну строку
                if d["navPresent"]:
                    fails.append("%s: мобильная панель видна в compact shell"
                                 % key)
                click(pg, "[data-drawer-trigger]", key)
                pg.wait_for_timeout(350)
                dr = pg.evaluate(r"""() => {
                    const dd = document.querySelector('.app-drawer');
                    if (!dd) return {open: false};
                    const r = dd.getBoundingClientRect();
                    return {open: dd.classList.contains('open'),
                            h: Math.round(r.height),
                            inside: r.top >= -1
                                    && r.bottom <= window.innerHeight + 1,
                            focusInside: dd.contains(document.activeElement)};
                }""")
                report["checks"][key + "-drawer"] = dr
                if not dr["open"] or not dr["inside"]:
                    fails.append("%s: drawer вне вьюпорта/не открылся" % key)
                if not dr["focusInside"]:
                    fails.append("%s: фокус не вошёл в drawer" % key)
                shot(pg, key + "-drawer")
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(250)
            shot(pg, key + "-modules")
            ctx.close()

        # ── 3. Планшет / десктоп: сетки по месту, модалка по центру ─────────
        for (w, h) in MIDS + WIDES:
            key = ("mid-%dx%d" % (w, h)) if (w, h) in MIDS \
                else ("wide-%dx%d" % (w, h))
            ctx = browser.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _routes())
            pg = ctx.new_page()
            pg.goto(base_url + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=15000)
            pg.wait_for_timeout(900)
            d = pg.evaluate(PROBE_SHELL)
            d["grids"] = pg.evaluate(PROBE_GRIDS)
            report["viewports"][key] = d
            if d["hScroll"]:
                fails.append("%s: горизонтальный скролл" % key)
            if d["overlap"]:
                fails.append("%s: контент под шапкой" % key)
            if d["sheetMode"] and w >= 768 and h > 520:
                fails.append("%s: sheet-режим включён на широком экране" % key)
            if d["headerH"] and d["headerH"] > HEAD_MAX_MID:
                fails.append("%s: шапка %s px" % (key, d["headerH"]))
            if d["navPresent"] and w >= 768:
                fails.append("%s: мобильная панель видна вне mobile shell" % key)
            # модалка: окно по центру, внутренний скролл
            pg.evaluate("""() => {
                const vm = window.__adminbotVm;
                if (vm && vm.modules && vm.modules.length) {
                    vm.openModuleWindow(vm.modules[0]);
                }
            }""")
            pg.wait_for_timeout(500)
            md = pg.evaluate(PROBE_MODAL)
            report["checks"][key + "-modal"] = md
            if md.get("modal"):
                if md["sheetClass"] and d["shellMode"] == "desktop":
                    fails.append("%s: sheet-режим на широком desktop-экране"
                                 % key)
                if not md["inViewport"]:
                    fails.append("%s: модалка вне вьюпорта" % key)
                if md["top"] < 8:
                    fails.append("%s: модалка прижата к верху (не центрирована)"
                                 % key)
                if md["bodyScroll"] != "auto":
                    fails.append("%s: нет внутреннего скролла модалки" % key)
                if not md["focusInside"]:
                    fails.append("%s: фокус не в модалке" % key)
                shot(pg, key + "-modal")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            if w >= 1440:
                g = d.get("grids") or {}
                hub = g.get("hubGrid")
                if hub and hub["width"] and hub["width"] < min(w * 0.55, 1200):
                    fails.append("%s: хаб-сетка «островок» %s px при окне %s"
                                 % (key, hub["width"], w))
            shot(pg, key + "-modules")
            ctx.close()

        # ── 4. Zoom 200 % ──────────────────────────────────────────────────
        # Настоящий zoom страницы в Chromium УМЕНЬШАЕТ CSS-вьюпорт (масштаб
        # отрисовки растёт, layout-ширина падает). `body { zoom: 2 }` медиа-
        # запросы не меняет и проверял бы несуществующий сценарий, поэтому
        # zoom 200 % моделируется как вьюпорт вдвое уже при DPR 2.
        for (w, h) in ZOOMS:
            key = "zoom200-%dx%d" % (w, h)
            ctx = browser.new_context(
                viewport={"width": w // 2, "height": h // 2},
                device_scale_factor=2, is_mobile=(w // 2 <= 430),
                has_touch=(w // 2 <= 430))
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _routes())
            pg = ctx.new_page()
            pg.goto(base_url + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=15000)
            pg.wait_for_timeout(900)
            d = pg.evaluate(PROBE_SHELL)
            d["touch"] = pg.evaluate(PROBE_TOUCH)
            report["viewports"][key] = d
            if d["hScroll"]:
                fails.append("%s: горизонтальный скролл при zoom 200%% (%s > %s)"
                             % (key, d["sw"], d["vw"]))
            if d["overlap"]:
                fails.append("%s: контент под шапкой при zoom 200%%" % key)
            # Кнопки и подписи не обрезаны: сегменты навигации и триггер
            # области остаются читаемыми (высота/подпись внутри).
            labels = pg.evaluate(r"""() => {
                const bad = [];
                document.querySelectorAll('.mobile-topnav-label, .scope-name')
                  .forEach(el => {
                    const cs = getComputedStyle(el);
                    if (cs.display === 'none') return;
                    if (el.scrollWidth > el.clientWidth + 2
                        && cs.textOverflow !== 'ellipsis'
                        && cs.overflow !== 'hidden') bad.push(el.className);
                  });
                return bad;
            }""")
            if labels:
                fails.append("%s: подписи обрезаны без ellipsis: %s"
                             % (key, labels[:3]))
            shot(pg, key)
            ctx.close()

        # ── 4b. Увеличенный системный шрифт (прокси: root font-size 125 %) ────
        # Android/WebView позволяют крупный системный шрифт; проверяем, что
        # верхняя область, панель и подписи не разъезжаются и не дают
        # горизонтального скролла.
        for (w, h) in ((320, 568), (390, 844)):
            key = "font125-%dx%d" % (w, h)
            ctx = open_ctx(browser, w, h)
            pg = ctx.new_page()
            pg.goto(base_url + "#/modules", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=15000)
            pg.wait_for_timeout(700)
            pg.evaluate("() => { document.documentElement.style.fontSize = '20px'; }")
            pg.wait_for_timeout(400)
            d = pg.evaluate(PROBE_SHELL)
            d["labels"] = pg.evaluate(r"""() => {
                const bad = [];
                document.querySelectorAll('.mobile-topnav-label')
                  .forEach(el => {
                    const cs = getComputedStyle(el);
                    if (cs.display === 'none') return;
                    if (el.scrollWidth > el.clientWidth + 2
                        && cs.textOverflow !== 'ellipsis') bad.push(el.className);
                  });
                return bad;
            }""")
            report["viewports"][key] = d
            if d["hScroll"]:
                fails.append("%s: горизонтальный скролл при крупном шрифте"
                             % key)
            if d["overlap"]:
                fails.append("%s: контент под шапкой при крупном шрифте" % key)
            if d["navPresent"] and d["navH"] < NAV_MIN_TOUCH:
                fails.append("%s: панель %s px при крупном шрифте"
                             % (key, d["navH"]))
            if d["labels"]:
                fails.append("%s: подписи панели обрезаны без ellipsis: %s"
                             % (key, d["labels"][:3]))
            shot(pg, key)
            ctx.close()

        # ── 5. Поворот: портрет → ландшафт без перезагрузки ────────────────
        ctx = open_ctx(browser, 390, 844)
        pg = ctx.new_page()
        pg.goto(base_url + "#/oversight", wait_until="load")
        pg.wait_for_selector(".app-shell", timeout=15000)
        pg.wait_for_timeout(800)
        before = pg.evaluate(PROBE_SHELL)
        pg.set_viewport_size({"width": 844, "height": 390})
        pg.wait_for_timeout(700)
        after = pg.evaluate(PROBE_SHELL)
        report["checks"]["rotate"] = {"before": before, "after": after}
        if after["hScroll"]:
            fails.append("rotate: горизонтальный скролл после поворота")
        if after["overlap"]:
            fails.append("rotate: контент под шапкой после поворота")
        if after["headerH"] and after["headerH"] > HEAD_MAX_LAND:
            fails.append("rotate: шапка %s px после поворота" % after["headerH"])
        if before["navPresent"] and before["navFlexDir"] == "column":
            fails.append("rotate: рейл остался в портрете")
        if after["navPresent"] and after["navFlexDir"] != "column":
            fails.append("rotate: навигация не перестроилась в рейл")
        if after["contentShare"] is not None and \
                after["contentShare"] < CONTENT_SHARE_LAND:
            fails.append("rotate: контенту остаётся %s высоты"
                         % after["contentShare"])
        shot(pg, "rotate-landscape")
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.wait_for_timeout(700)
        back = pg.evaluate(PROBE_SHELL)
        report["checks"]["rotate-back"] = back
        metric = pg.evaluate(r"""() => {
            const v = getComputedStyle(document.documentElement)
              .getPropertyValue('--bottom-nav-h').trim();
            const nav = document.querySelector('.mobile-topnav');
            return {var: v, nav: nav
              ? Math.round(nav.getBoundingClientRect().height) : null};
        }""")
        report["checks"]["rotate-back-nav-metric"] = metric
        if metric["nav"] is not None:
            try:
                mv = float(metric["var"].replace("px", "") or 0)
            except ValueError:
                mv = -1
            if abs(mv - metric["nav"]) > 1:
                fails.append("rotate-back: --bottom-nav-h %s не совпадает с "
                             "фактической панелью %s (метрика залипла после "
                             "поворота)" % (metric["var"], metric["nav"]))
        # Лист «Ещё» после поворота тоже должен стоять вплотную к панели.
        click(pg, ".mobile-topnav-more", "rotate-back")
        pg.wait_for_timeout(320)
        mm = pg.evaluate(PROBE_MORE)
        report["checks"]["rotate-back-more"] = mm
        if mm.get("open") and mm.get("gapToNav") is not None \
                and mm["gapToNav"] > 12:
            fails.append("rotate-back: лист «Ещё» с зазором %s px от панели"
                         % mm["gapToNav"])
        pg.keyboard.press("Escape")
        if back["hScroll"] or back["overlap"]:
            fails.append("rotate-back: overflow/перекрытие после возврата")
        if back["navPresent"] and back["navFlexDir"] == "column":
            fails.append("rotate-back: рейл остался после возврата в портрет")
        if back["headerH"] and back["headerH"] > HEAD_MAX_PHONE:
            fails.append("rotate-back: шапка %s px" % back["headerH"])
        ctx.close()

        # ── 6. Инвентаризация маршрутов × вьюпортов ────────────────────────
        inv = {"routes": list(M.ROUTES), "viewports": [], "cells": [],
               "failures": []}
        for (vw, vh) in INV_VIEWPORTS:
            ctx = open_ctx(browser, vw, vh)
            pg = ctx.new_page()
            pg.goto(base_url + "#/", wait_until="load")
            pg.wait_for_selector(".app-shell", timeout=15000)
            pg.wait_for_timeout(900)
            vp = "%dx%d" % (vw, vh)
            inv["viewports"].append(vp)
            for route in M.ROUTES:
                pg.evaluate("(r) => { window.location.hash = r; }", route)
                pg.wait_for_timeout(320)
                cell = pg.evaluate(INV_PROBE)
                cell["viewport"] = vp
                cell["route"] = route
                inv["cells"].append(cell)
                if cell["hScroll"]:
                    inv["failures"].append(
                        "%s %s: h-скролл %s > %s"
                        % (vp, route, cell["sw"], cell["vw"]))
                if cell["offCount"]:
                    inv["failures"].append(
                        "%s %s: за вьюпортом %s %s"
                        % (vp, route, cell["offCount"], cell["offscreen"][:2]))
                if cell["clippedCount"]:
                    inv["failures"].append(
                        "%s %s: обрезанный текст %s %s"
                        % (vp, route, cell["clippedCount"], cell["clipped"][:2]))
            ctx.close()
        inv["summary"] = {
            "routes": len(M.ROUTES), "viewports": len(INV_VIEWPORTS),
            "cells": len(inv["cells"]),
            "hScroll": sum(1 for x in inv["cells"] if x["hScroll"]),
            "offscreen": sum(1 for x in inv["cells"] if x["offCount"]),
            "clipped": sum(1 for x in inv["cells"] if x["clippedCount"]),
            "failures": len(inv["failures"]),
        }
        with open(os.path.join(out_dir, "w9-responsive-inventory.json"), "w",
                  encoding="utf-8") as f:
            json.dump(inv, f, ensure_ascii=False, indent=1)
        report["inventory"] = inv["summary"]
        print("[inventory] %s" % json.dumps(inv["summary"], ensure_ascii=False))
        fails.extend(inv["failures"][:30])

        browser.close()
    httpd.shutdown()
    if tmp_root:
        shutil.rmtree(tmp_root, ignore_errors=True)

    report["failures"] = fails
    with open(os.path.join(out_dir, "w9-responsive-probe.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if fails:
        print("EVOL-W9-RESPONSIVE FAIL (%d):" % len(fails))
        for f_ in fails:
            print(" -", f_)
        return 1
    print("EVOL-W9-RESPONSIVE OK — артефакты: %s" % out_dir)
    return 0


def main() -> int:
    out = DEFAULT_SHOTS
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    baseline = None
    if "--baseline" in sys.argv:
        baseline = sys.argv[sys.argv.index("--baseline") + 1]
    return run(out, baseline=baseline)


if __name__ == "__main__":
    sys.exit(main())
