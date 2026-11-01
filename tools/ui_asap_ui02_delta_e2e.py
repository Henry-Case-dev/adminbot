"""ASAP-UI-02 — живая проверка дельты: один слой overlay, dropdown/лист,
Back-stack, палитра на телефоне, окно записи (L01848/L01854/L01950/
L01958/L01971/L01843).

Детерминированная Playwright-проверка НАСТОЯЩИХ `web/index.html` + `web/app.js`
(сервер/стабы/TMA — переиспользуются из `tools/ui_round1025_matrix.py`; второго
тестового стенда не заводится). Секретов нет, в Telegram ничего не отправляется.

Что проверяется живым рендером (а не наличием узлов):
  * computed `z-index` всех слоёв равен рангам единой лестницы и порядок
    соблюдён (скрим < панель, dropdown выше шапки, модалка выше dropdown,
    тост выше модалки, палитра выше модалок);
  * `--dur-*`/`--ease-out` реально резолвятся в `--motion-*` (один масштаб), а
    движок лент берёт скорость/паузы из `--motion-feed-*`;
  * панель области: целиком внутри вьюпорта, плотная подложка, перехватывает
    тап (elementFromPoint внутри панели), на низком ландшафте — лист;
  * палитра: desktop из шапки, телефон — из drawer; лист внутри вьюпорта,
    ввод в фокусе, Esc закрывает ТОЛЬКО палитру (маршрут не меняется), и
    BackButton при открытом слое доступен;
  * окно записи: та же запись (`record_id`), три разных типа дат, источник,
    Esc закрывает только окно и возвращает фокус в строку.

Запуск: .venv\\Scripts\\python.exe tools\\ui_asap_ui02_delta_e2e.py [--out DIR]
Артефакты: plans/features/evol/audit/evidence/asap-ui-delta/
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

PORT = 8873
DEFAULT_OUT = os.path.join(REPO, "plans", "features", "evol", "audit",
                           "evidence", "asap-ui-delta")

# Запись досье: одна и та же сущность с РАЗНЫМИ датами и источником.
FACT_TEXT = "Owner prefers concise Russian answers without ceremony"
DOSSIER_ITEMS = [
    {"id": 4242, "chat_id": -1001234567890, "name": "Owner",
     "excerpt": "кратко и по делу", "text": FACT_TEXT,
     "origin": "manual", "tg_message_id": 777,
     "created_at": 1761000000, "message_timestamp": 1760900000,
     "last_confirmed_at": 1761100000, "user_id": 5885953495},
    {"id": 4243, "chat_id": -1001234567890, "name": "Owner",
     "excerpt": "без лишних вступлений", "text": "No long preambles",
     "origin": "extract", "tg_message_id": 778,
     "created_at": 1761000100, "message_timestamp": 1760900100,
     "last_confirmed_at": 1761100100, "user_id": 5885953495},
]

# Живой BackButton Mini App: страница грузит НАСТОЯЩИЙ telegram-web-app.js,
# поэтому записываем show()/hide() уже после загрузки (объект тот же, что взял
# app.js), чтобы увидеть, доступен ли Back при открытом слое.
PATCH_BACK = """
() => {
  try {
    window.__backCalls = [];
    const bb = window.Telegram.WebApp.BackButton;
    bb.show = function () { window.__backCalls.push('show'); };
    bb.hide = function () { window.__backCalls.push('hide'); };
  } catch (e) { window.__backPatchError = String(e); }
}
"""

PROBE_TOKENS = r"""
() => {
  const cs = getComputedStyle(document.documentElement);
  const num = (n) => parseFloat(cs.getPropertyValue(n));
  const raw = (n) => String(cs.getPropertyValue(n) || '').trim();
  return {
    z: {
      base: num('--z-base'), content: num('--z-content'),
      inline: num('--z-inline'), sidebar: num('--z-sidebar'),
      scrim: num('--z-scrim'), nav: num('--z-nav'), local: num('--z-local'),
      menu: num('--z-menu'), overlay: num('--overlay-z'),
      modalScrim: num('--z-modal-scrim'), modal: num('--z-modal'),
      toast: num('--z-toast'), palette: num('--z-palette'),
      dev: num('--z-dev'), devTop: num('--z-dev-top'),
    },
    motion: {
      durFast: raw('--dur-fast'), motionFast: raw('--motion-fast'),
      durNormal: raw('--dur-normal'), motionBase: raw('--motion-base'),
      durSlow: raw('--dur-slow'), motionSlow: raw('--motion-slow'),
      easeOut: raw('--ease-out'), motionEase: raw('--motion-ease'),
      feedSpeed: raw('--motion-feed-speed'),
      feedResume: raw('--motion-feed-resume'),
      feedEndHold: raw('--motion-feed-end-hold'),
      feedRewind: raw('--motion-feed-rewind'),
      feedStartHold: raw('--motion-feed-start-hold'),
    },
    engine: (window.__StatusFeed && window.__StatusFeed.DEFAULTS) || null,
    vw: window.innerWidth, vh: window.innerHeight,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}
"""

PROBE_Z = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    z: cs.zIndex === 'auto' ? null : parseInt(cs.zIndex, 10),
    pos: cs.position,
    bg: cs.backgroundColor,
    rect: { l: Math.round(r.left), t: Math.round(r.top),
            r: Math.round(r.right), b: Math.round(r.bottom),
            w: Math.round(r.width), h: Math.round(r.height) },
  };
}
"""

PROBE_PANEL = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const hit = document.elementFromPoint(cx, cy);
  const alpha = (() => {
    const m = /rgba?\(([^)]+)\)/.exec(cs.backgroundColor);
    if (!m) return null;
    const parts = m[1].split(',').map((x) => parseFloat(x));
    return parts.length >= 4 ? parts[3] : 1;
  })();
  return {
    rect: { l: Math.round(r.left), t: Math.round(r.top),
            r: Math.round(r.right), b: Math.round(r.bottom),
            w: Math.round(r.width), h: Math.round(r.height) },
    placement: el.getAttribute('data-placement'),
    bgAlpha: alpha, position: cs.position,
    insideViewport: r.left >= -1 && r.top >= -1
      && r.right <= window.innerWidth + 1
      && r.bottom <= window.innerHeight + 1,
    hitInside: !!(hit && el.contains(hit)),
    vw: window.innerWidth, vh: window.innerHeight,
  };
}
"""

PROBE_RECORD = r"""
() => {
  const dlg = document.querySelector('[data-sfeed-modal]');
  if (!dlg) return null;
  const rows = Array.from(dlg.querySelectorAll('[data-rec-field]'));
  const field = (k) => {
    const n = dlg.querySelector('[data-rec-field="' + k + '"] .rec-val');
    return n ? n.textContent.trim() : null;
  };
  const active = document.activeElement;
  return {
    inViewport: (() => {
      const r = dlg.getBoundingClientRect();
      return r.left >= -1 && r.top >= -1
        && r.right <= window.innerWidth + 1
        && r.bottom <= window.innerHeight + 1;
    })(),
    fields: rows.map((n) => n.getAttribute('data-rec-field')),
    text: field('text'), created: field('created_at'),
    event: field('event_at'), confirmed: field('confirmed_at'),
    origin: field('origin'), sources: field('sources'),
    heading: (dlg.querySelector('.modal-title') || {}).textContent || '',
    allText: (dlg.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 400),
    sheetMode: document.documentElement.classList.contains('w9-sheet-bottom'),
    activeIsRow: !!(active && active.getAttribute
      && active.getAttribute('data-sfeed-row') !== null),
  };
}
"""


class _Handler(M._Handler):
    pass


def _app():
    return "http://127.0.0.1:%d/web/index.html" % PORT


CHATS = [
    {"chat_id": -1001234567890 - i, "title": "Рабочий чат %d" % (i + 1),
     "type": "supergroup", "is_dm": False, "photo_file_id": None}
    for i in range(8)
]


def _routes():
    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/oversight/dossier_feed"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"items": DOSSIER_ITEMS}))
            return
        if url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(CHATS))
            return
        payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return _route


def _fails_tokens(tok):
    f = []
    z = tok["z"]
    expect = {"nav": 40, "scrim": 35, "overlay": 50, "modalScrim": 75,
              "modal": 80, "toast": 90, "palette": 100}
    for k, v in expect.items():
        if z.get(k) != v:
            f.append("токен --z-%s = %s (ожидалось %s)" % (k, z.get(k), v))
    if not (z["scrim"] < z["nav"] < z["overlay"] < z["menu"]
            < z["modalScrim"] < z["modal"] < z["toast"] < z["palette"]
            < z["dev"] < z["devTop"]):
        f.append("порядок лестницы слоёв нарушен: %s" % z)
    m = tok["motion"]
    pairs = [("durFast", "motionFast"), ("durNormal", "motionBase"),
             ("durSlow", "motionSlow"), ("easeOut", "motionEase")]
    for a, b in pairs:
        if not m[a] or m[a] != m[b]:
            f.append("%s=%r не равен %s=%r (второй масштаб движения)"
                     % (a, m[a], b, m[b]))
    eng = tok["engine"] or {}
    if str(eng.get("speedPxS")) + "px" != m["feedSpeed"]:
        f.append("движок лент: speedPxS=%r, токен %r"
                 % (eng.get("speedPxS"), m["feedSpeed"]))
    for key, token in (("resumeMs", "feedResume"),
                       ("endHoldMs", "feedEndHold"),
                       ("rewindMs", "feedRewind"),
                       ("startHoldMs", "feedStartHold")):
        if str(eng.get(key)) + "ms" != m[token]:
            f.append("движок лент: %s=%r, токен %s=%r"
                     % (key, eng.get(key), token, m[token]))
    return f


def _fails_layer_order(layers):
    f = []
    need = ["header", "drawer", "drawerBackdrop", "scope", "recordScrim",
            "toast", "palette"]
    for k in need:
        if layers.get(k) is None:
            f.append("слой %s не измерен (нет computed z-index)" % k)
    if f:
        return f
    if not (layers["drawerBackdrop"] < layers["drawer"]):
        f.append("подложка drawer не ниже самого drawer: %s" % layers)
    if not (layers["header"] < layers["scope"]):
        f.append("dropdown области не выше шапки: %s" % layers)
    if not (layers["scope"] < layers["recordScrim"]):
        f.append("dropdown рисуется выше скрима модалки: %s" % layers)
    if not (layers["recordScrim"] < layers["palette"]):
        f.append("палитра не выше модалок: %s" % layers)
    if not (layers["recordScrim"] == 75):
        f.append("скрим окна записи не на ранге --z-modal-scrim (75): %s"
                 % layers["recordScrim"])
    if not (layers["toast"] < layers["palette"]):
        f.append("палитра не выше тоста: %s" % layers)
    return f


def run(out_dir):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    report = {"layers": {}, "checks": {}}
    fails = []

    def shot(page, name):
        page.screenshot(path=os.path.join(out_dir, "asap-ui-delta-" + name + ".png"))

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── 1280: слои, dropdown, палитра, окно записи, движение ────────────
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _routes())
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))
        page.goto(_app() + "#/ai", wait_until="load")
        page.wait_for_selector(".app-shell", timeout=15000)
        page.wait_for_timeout(900)
        page.evaluate(PATCH_BACK)

        tok = page.evaluate(PROBE_TOKENS)
        report["tokens"] = tok
        fails.extend(_fails_tokens(tok))

        layers = {}

        # dropdown области: внутри вьюпорта, плотный, перехватывает тап
        page.click(".scope-trigger")
        page.wait_for_timeout(350)
        scope = page.evaluate(PROBE_PANEL, ".scope-panel")
        report["checks"]["scope1280"] = scope
        layers["scope"] = (page.evaluate(PROBE_Z, ".scope-panel") or {}).get("z")
        if not scope or not scope["insideViewport"]:
            fails.append("dropdown области выходит за вьюпорт 1280: %s" % scope)
        if scope and not scope["hitInside"]:
            fails.append("поверх dropdown просвечивает/перехватывает другой слой")
        if scope and (scope["bgAlpha"] or 0) < 0.9:
            fails.append("подложка dropdown прозрачна до нечитаемости: %s"
                         % scope["bgAlpha"])
        shot(page, "1280-scope")
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        layers["header"] = (page.evaluate(PROBE_Z, "header.header-sticky") or {}).get("z")
        layers["toast"] = (page.evaluate(PROBE_Z, ".toast-wrap") or {}).get("z")

        # палитра с шапки (desktop), BackButton доступен при открытом слое
        route_before = page.evaluate("() => window.location.hash")
        page.evaluate("() => { window.__backCalls = []; }")
        page.click("[data-palette-open]")
        page.wait_for_timeout(350)
        pal = page.evaluate(PROBE_PANEL, ".palette-panel")
        layers["palette"] = (page.evaluate(PROBE_Z, ".palette-root") or {}).get("z")
        back_calls = page.evaluate("() => (window.__backCalls || []).slice()")
        back_open = 'show' in back_calls
        focused = page.evaluate("() => (document.activeElement || {}).id || ''")
        report["checks"]["palette1280"] = {
            "panel": pal, "backCalls": back_calls, "focused": focused,
            "route": route_before,
        }
        if not pal or not pal["insideViewport"]:
            fails.append("палитра выходит за вьюпорт 1280: %s" % pal)
        if pal and (pal["bgAlpha"] or 0) < 0.9:
            fails.append("палитра просвечивает (нечитаемо): %s" % pal["bgAlpha"])
        if focused != "palette-input":
            fails.append("ввод палитры не в фокусе: %r" % focused)
        if not back_open:
            fails.append("при открытой палитре на корневом маршруте Back недоступен")
        shot(page, "1280-palette")

        # Esc закрывает РОВНО палитру, маршрут не меняется
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        after = page.evaluate(
            "() => ({open: !!document.querySelector('[data-command-palette]'),"
            " route: window.location.hash})")
        report["checks"]["paletteEsc"] = after
        if after["open"]:
            fails.append("Esc не закрыл палитру")
        if after["route"] != route_before:
            fails.append("Esc в палитре изменил маршрут: %s -> %s"
                         % (route_before, after["route"]))

        report["checks"]["layers1280"] = layers
        shot(page, "1280-after-esc")

        # окно записи: та же запись, разные даты, источник
        page.evaluate("() => { window.location.hash = '#/status'; }")
        page.wait_for_timeout(1200)
        route_status = page.evaluate("() => window.location.hash")
        row = page.locator("[data-sfeed-row]").first
        if row.count() == 0:
            fails.append("строки ленты не отрисованы — окно записи не проверить")
        else:
            row.click()
            page.wait_for_timeout(400)
            rec = page.evaluate(PROBE_RECORD)
            report["checks"]["record1280"] = rec
            if not rec:
                fails.append("окно записи не открылось по строке")
            else:
                if "#4242" not in rec["allText"]:
                    fails.append("окно открыло другую запись: %r" % rec["allText"][:120])
                for key, label in (("created", "записано"), ("event", "событие"),
                                   ("confirmed", "подтверждено")):
                    if not rec.get(key):
                        fails.append("нет даты «%s» в окне записи" % label)
                if rec.get("created") == rec.get("event"):
                    fails.append("дата записи подменена датой события")
                if not rec.get("origin"):
                    fails.append("происхождение записи не показано")
                if not rec.get("sources"):
                    fails.append("источник (TG-сообщение) не показан")
                if not rec["inViewport"]:
                    fails.append("окно записи выходит за вьюпорт 1280")
                scrim = page.evaluate(PROBE_Z, ".sfeed-modal-backdrop") or {}
                layers["modalScrim"] = scrim.get("z")
                layers["recordScrim"] = scrim.get("z")
                shot(page, "1280-record")
                page.keyboard.press("Escape")
                page.wait_for_timeout(350)
                closed = page.evaluate(
                    "() => ({open: !!document.querySelector('[data-sfeed-modal]'),"
                    " row: !!(document.activeElement && document.activeElement"
                    ".getAttribute && document.activeElement"
                    ".getAttribute('data-sfeed-row') !== null),"
                    " route: window.location.hash})")
                report["checks"]["recordEsc"] = closed
                if closed["open"]:
                    fails.append("Esc не закрыл окно записи")
                if not closed["row"]:
                    fails.append("фокус не вернулся в строку записи")
                if closed["route"] != route_status:
                    fails.append("закрытие окна записи изменило маршрут: %s -> %s"
                                 % (route_status, closed["route"]))

        report["layers"] = layers

        # ── 390: drawer + палитра-лист ──────────────────────────────────────
        ctx2 = browser.new_context(viewport={"width": 390, "height": 844},
                                   has_touch=True)
        ctx2.add_init_script(M.TMA_STUB)
        ctx2.add_init_script(M.TMA_STUB)
        ctx2.route("**/api/**", _routes())
        p2 = ctx2.new_page()
        p2.goto(_app() + "#/ai", wait_until="load")
        p2.wait_for_selector(".app-shell", timeout=15000)
        p2.wait_for_timeout(900)
        p2.evaluate(PATCH_BACK)
        p2.click("[data-drawer-trigger]")
        p2.wait_for_timeout(350)
        drawer = {
            "z": (p2.evaluate(PROBE_Z, ".app-drawer") or {}).get("z"),
            "scrim": (p2.evaluate(PROBE_Z, ".drawer-backdrop") or {}).get("z"),
        }
        report["checks"]["drawer390"] = drawer
        layers["drawer"] = drawer["z"]
        layers["drawerBackdrop"] = drawer["scrim"]
        shot(p2, "390-drawer")
        p2.click("[data-palette-open-drawer]")
        p2.wait_for_timeout(400)
        psheet = p2.evaluate(PROBE_PANEL, ".palette-panel")
        mob = p2.evaluate(PROBE_TOKENS)
        report["checks"]["palette390"] = psheet
        if not psheet or not psheet["insideViewport"]:
            fails.append("палитра на 390 выходит за вьюпорт: %s" % psheet)
        if psheet and psheet["rect"]["w"] < 380:
            fails.append("палитра на телефоне не лист во всю ширину: %s"
                         % psheet["rect"])
        if psheet and (psheet["bgAlpha"] or 0) < 0.9:
            fails.append("палитра на 390 просвечивает: %s" % psheet["bgAlpha"])
        if mob["hScroll"]:
            fails.append("палитра на 390 дала горизонтальный скролл")
        inp = p2.evaluate(
            "() => { const el = document.querySelector('.palette-input');"
            " if (!el) return null; const r = el.getBoundingClientRect();"
            " return { h: Math.round(r.height), w: Math.round(r.width) }; }")
        report["checks"]["palette390"]["input"] = inp
        if not inp or inp["h"] < 44:
            fails.append("ввод палитры на 390 ниже tap-цели 44px: %s" % inp)
        shot(p2, "390-palette")

        # ── 390: окно записи = общий мобильный лист ────────────────────────
        # Закрываем палитру и drawer тем же Back/Esc-путём (слой за слоем).
        p2.keyboard.press("Escape")
        p2.wait_for_timeout(250)
        p2.keyboard.press("Escape")
        p2.wait_for_timeout(250)
        layer_state = p2.evaluate(
            "() => ({palette: !!document.querySelector('[data-command-palette]'),"
            " drawer: !!document.querySelector('.app-shell.drawer-open')})")
        report["checks"]["closeOrder390"] = layer_state
        if layer_state["palette"] or layer_state["drawer"]:
            fails.append("Esc не закрыл слои по одному на 390: %s" % layer_state)
        p2.evaluate("() => { window.location.hash = '#/status'; }")
        p2.wait_for_timeout(1200)
        row2 = p2.locator("[data-sfeed-row]").first
        if row2.count() == 0:
            fails.append("на 390 нет строк ленты — мобильный лист записи не проверить")
        else:
            row2.click()
            p2.wait_for_timeout(450)
            rec2 = p2.evaluate(PROBE_RECORD)
            close_btn = p2.evaluate(
                "() => { const b = document.querySelector("
                "'[aria-label=\\\"Закрыть окно записи\\\"]');"
                " if (!b) return null; const r = b.getBoundingClientRect();"
                " return { l: Math.round(r.left), t: Math.round(r.top),"
                " w: Math.round(r.width), h: Math.round(r.height) }; }")
            report["checks"]["record390"] = {"record": rec2, "close": close_btn}
            if not rec2:
                fails.append("окно записи не открылось на 390")
            else:
                if not rec2["sheetMode"]:
                    fails.append("на телефоне окно записи не в режиме листа")
                if not rec2["inViewport"]:
                    fails.append("окно записи на 390 выходит за вьюпорт")
                if "#4242" not in rec2["allText"]:
                    fails.append("на 390 открыта другая запись")
            if not close_btn or close_btn["h"] < 44 or close_btn["w"] < 44:
                fails.append("кнопка закрытия окна записи < 44px на 390: %s"
                             % close_btn)
            shot(p2, "390-record")
            p2.keyboard.press("Escape")
            p2.wait_for_timeout(350)
            closed2 = p2.evaluate(
                "() => ({open: !!document.querySelector('[data-sfeed-modal]'),"
                " row: !!(document.activeElement && document.activeElement"
                ".getAttribute && document.activeElement"
                ".getAttribute('data-sfeed-row') !== null)})")
            report["checks"]["record390Esc"] = closed2
            if closed2["open"]:
                fails.append("Esc не закрыл лист записи на 390")
            if not closed2["row"]:
                fails.append("фокус не вернулся в строку после листа (390)")

        # ── 667×375: низкий ландшафт → dropdown области = лист ─────────────
        ctx3 = browser.new_context(viewport={"width": 667, "height": 375},
                                   has_touch=True)
        ctx3.add_init_script(M.TMA_STUB)
        ctx3.add_init_script(M.TMA_STUB)
        ctx3.route("**/api/**", _routes())
        p3 = ctx3.new_page()
        p3.goto(_app() + "#/ai", wait_until="load")
        p3.wait_for_selector(".app-shell", timeout=15000)
        p3.wait_for_timeout(900)
        p3.evaluate(PATCH_BACK)
        p3.click(".scope-trigger")
        p3.wait_for_timeout(400)
        low = p3.evaluate(PROBE_PANEL, ".scope-panel")
        report["checks"]["scope667x375"] = low
        if not low or not low["insideViewport"]:
            fails.append("dropdown области выходит за вьюпорт 667×375: %s" % low)
        if low and low["placement"] not in ("bottom", "top", "sheet"):
            fails.append("dropdown области без корректного placement: %s"
                         % low["placement"])
        shot(p3, "667x375-scope")

        # ── 320: палитра читаема, без горизонтального скролла ──────────────
        ctx4 = browser.new_context(viewport={"width": 320, "height": 700},
                                   has_touch=True)
        ctx4.add_init_script(M.TMA_STUB)
        ctx4.add_init_script(M.TMA_STUB)
        ctx4.route("**/api/**", _routes())
        p4 = ctx4.new_page()
        p4.goto(_app() + "#/ai", wait_until="load")
        p4.wait_for_selector(".app-shell", timeout=15000)
        p4.wait_for_timeout(900)
        p4.evaluate(PATCH_BACK)
        p4.click("[data-drawer-trigger]")
        p4.wait_for_timeout(300)
        p4.click("[data-palette-open-drawer]")
        p4.wait_for_timeout(400)
        narrow = p4.evaluate(PROBE_PANEL, ".palette-panel")
        tok320 = p4.evaluate(PROBE_TOKENS)
        report["checks"]["palette320"] = narrow
        if not narrow or not narrow["insideViewport"]:
            fails.append("палитра на 320 выходит за вьюпорт: %s" % narrow)
        if tok320["hScroll"]:
            fails.append("палитра на 320 дала горизонтальный скролл")
        shot(p4, "320-palette")

        # Порядок слоёв (после того как все измерения собраны).
        fails.extend(_fails_layer_order(layers))
        report["layers"] = layers

        if errs:
            fails.append("js-ошибки на странице: %s" % errs[:3])

        browser.close()

    httpd.shutdown()
    report["fails"] = fails
    with open(os.path.join(out_dir, "asap-ui-delta-e2e.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    if fails:
        print("ASAP-UI02-DELTA FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("ASAP-UI02-DELTA OK")
    return 0


def main():
    out = DEFAULT_OUT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    return run(out)


if __name__ == "__main__":
    sys.exit(main())
