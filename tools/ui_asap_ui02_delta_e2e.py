"""ASAP-UI-02 — живая проверка дельты: один слой overlay, лист/dropdown области,
Back-stack, палитра (RBAC, deep link, возврат), окно записи.

Детерминированная Playwright-проверка НАСТОЯЩИХ `web/index.html` + `web/app.js`
(сервер/стабы/TMA — переиспользуются из `tools/ui_round1025_matrix.py`; второго
тестового стенда не заводится). Секретов нет, в Telegram ничего не отправляется.

Секции (каждая пишет свой JSON и снимки в один каталог):
  * `layers`      — единая лестница `--z-*`, computed z-index, dropdown области,
                    палитра, окно записи (L01848/L01843/L01950/L01940);
  * `sheet`       — панель области на телефоне = ЛИСТ: 320/360/390/667×375,
                    читаемые названия, выбор тапом; на ≥768 — прежний dropdown
                    с flip (L01854);
  * `scenario6`   — §12 п.6: стабильная шапка без прыжков + порядок Back
                    (scope → палитра → лист записи → fullscreen-граф → маршрут),
                    Telegram Back (тот же `goBack`) (L01971);
  * `scenario14`  — §12 п.14: поиск из любого экрана ведёт к конкретному
                    объекту (focus), scope сохраняется, RBAC соблюдён, возврат
                    не теряет чат/scope и черновик (L01979);
  * `rbac`        — ограниченная роль: палитра не содержит запрещённых целей,
                    честное состояние на deep-link к недоступному, секреты не
                    индексируются (L01943).

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

# Один чат намеренно с длинным названием: на телефоне лист обязан показать его
# читаемо (перенос на две строки), а не «Очень дли…».
LONG_TITLE = "Очень длинное название рабочего чата с уточнением и подписью"
# 120 символов: проверяем, что лист ставит многоточие ровно на второй строке и
# НЕ обрезает её по вертикали (ревью B1: clientHeight 38 против scrollHeight 42).
HUGE_TITLE = ("Очень длинное название рабочего чата с уточнением, подписью и "
              "дополнительным продолжением имени, которое заведомо не влезает "
              "в две строки листа и должно быть аккуратно сокращено")
CHATS = [
    {"chat_id": -1001234567890, "title": LONG_TITLE, "type": "supergroup",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": -1001234567891, "title": HUGE_TITLE, "type": "supergroup",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424242, "title": "Второй чат", "type": "group",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424243, "title": "Рабочий чат 3", "type": "group",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424244, "title": "Рабочий чат 4", "type": "group",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424245, "title": "Рабочий чат 5", "type": "group",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424246, "title": "Рабочий чат 6", "type": "group",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424247, "title": "Рабочий чат 7", "type": "group",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": 424248, "title": "Рабочий чат 8", "type": "group",
     "is_dm": False, "photo_file_id": None},
]

# Ограниченная роль: НИ wildcard, НИ is_global_admin, единственная секция
# memory. Такой payload реально сужает `canViewTab` (проверено живым замером:
# индекс палитры 540 против 627 у админа, 22 вкладки закрыты).
PERSONA_STUB = {
    "scope": "global", "chat_id": None, "is_global": True,
    "persona_enabled": True,
    "values": {"name": "Adminbot", "biography": "",
               "system_prompt_overrides": "", "is_aware_ai": False},
    "updated_at": None,
}

RESTRICTED_ME = {
    "telegram_id": 5885953495, "username": "reader", "first_name": "Reader",
    "last_name": None, "photo_url": None, "role_name": "reader",
    "permissions": {"sections": ["memory"], "params": [], "keys": []},
    "is_custom": False, "is_global_admin": False,
    "ui_flags": dict(M.ME_JSON["ui_flags"]),
}

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

# Панель области как комбобокс: лист на телефоне / dropdown на ≥768.
PROBE_SCOPE = r"""
() => {
  const p = document.querySelector('.scope-panel');
  if (!p) return null;
  const r = p.getBoundingClientRect();
  const cs = getComputedStyle(p);
  const vv = window.visualViewport;
  const vh = Math.round((vv && vv.height) || window.innerHeight);
  const opts = Array.from(p.querySelectorAll('.scope-option'));
  const title = p.querySelector('.scope-option__title');
  const tcs = title ? getComputedStyle(title) : null;
  const tr = title ? title.getBoundingClientRect() : null;
  const lh = tcs ? parseFloat(tcs.lineHeight) || 0 : 0;
  return {
    open: true,
    placement: p.getAttribute('data-placement'),
    position: cs.position,
    rect: { l: Math.round(r.left), t: Math.round(r.top),
            r: Math.round(r.right), b: Math.round(r.bottom),
            w: Math.round(r.width), h: Math.round(r.height) },
    vw: window.innerWidth, vh: vh,
    inside: r.left >= -1 && r.right <= window.innerWidth + 1
            && r.top >= -1 && r.bottom <= vh + 1,
    bottomGap: Math.round(vh - r.bottom),
    options: opts.length,
    optionH: opts.length ? Math.round(opts[0].getBoundingClientRect().height) : null,
    titleText: title ? title.textContent.trim() : null,
    titleClip: title ? (title.scrollWidth - title.clientWidth) : null,
    titleLines: (tr && lh) ? Math.round(tr.height / lh) : null,
    titleAttr: title ? title.getAttribute('title') : null,
    // Вертикаль (ревью B1): линии не должны обрезаться по высоте. Для каждой
    // длинной подписи — реальные clientHeight/scrollHeight и число строк.
    titleRows: Array.from(p.querySelectorAll('.scope-option__title'))
      .map((n) => {
        const cs2 = getComputedStyle(n);
        const lh2 = parseFloat(cs2.lineHeight) || 0;
        const text = n.textContent.trim();
        return {len: text.length,
                clientH: n.clientHeight, scrollH: n.scrollHeight,
                clientW: n.clientWidth, scrollW: n.scrollWidth,
                lh: lh2, clamp: cs2.webkitLineClamp, maxH: cs2.maxHeight,
                lines: lh2 ? Math.round(n.getBoundingClientRect().height / lh2) : null};
      })
      .filter((r) => r.len > 30),
    titleWorst: (() => {
      let worst = null;
      Array.from(p.querySelectorAll('.scope-option__title')).forEach((n) => {
        const cs2 = getComputedStyle(n);
        const lh2 = parseFloat(cs2.lineHeight) || 0;
        const h2 = n.getBoundingClientRect().height;
        const text = n.textContent.trim();
        const item = {text: text.slice(0, 48), len: text.length,
                      clip: n.scrollWidth - n.clientWidth,
                      h: Math.round(h2),
                      full: n.scrollWidth <= n.clientWidth + 1,
                      lines: lh2 ? Math.round(h2 / lh2) : null};
        if (!worst || item.len > worst.len) worst = item;
      });
      return worst;
    })(),
    scrolls: p.scrollHeight > p.clientHeight + 1,
    hScrollPage: document.documentElement.scrollWidth > window.innerWidth + 1,
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

# Состояние приложения, нужное сценариям: слои, маршрут, scope, черновик.
PROBE_VM = r"""
() => {
  const vm = window.__adminbotVm || null;
  const q = (s) => document.querySelector(s);
  const main = q('main.scroll-area');
  return {
    route: window.location.hash,
    shellMode: vm ? vm.shellMode : null,
    backStack: vm ? vm.backStack : null,
    scopeKind: vm ? vm.scopeKind : null,
    activeChatId: vm ? vm.activeChatId : null,
    scopeLabel: (q('[data-palette-scope]') || {}).textContent || null,
    paletteOpen: !!(vm && vm.paletteOpen),
    paletteCount: (vm && vm.paletteIndexEntries) ? vm.paletteIndexEntries.length : null,
    dirty: vm && typeof vm.hasUnsavedEdits === 'function'
      ? !!vm.hasUnsavedEdits() : null,
    scrollTop: (() => {
      const m = q('main.scroll-area');
      const de = document.scrollingElement || document.documentElement;
      const inside = (m && m.scrollHeight > m.clientHeight + 1)
        ? Math.round(m.scrollTop) : 0;
      return Math.max(inside, de ? Math.round(de.scrollTop) : 0);
    })(),
    headerTop: Math.round((q('header.header-sticky') || {getBoundingClientRect: () => ({top: -999})}).getBoundingClientRect().top),
    headerH: Math.round((q('header.header-sticky') || {getBoundingClientRect: () => ({height: 0})}).getBoundingClientRect().height),
    paletteItems: Array.from(document.querySelectorAll('[data-palette-item]'))
      .slice(0, 6).map((n) => n.getAttribute('data-palette-dest')),
    focusPulse: !!q('.focus-pulse'),
    paletteEmpty: !!q('[data-palette-empty]'),
    toastText: Array.from(document.querySelectorAll('.toast')).map(
      (n) => n.textContent.trim()).join(' | ')
      || (vm && vm.toasts ? vm.toasts.map((t) => t.text).join(' | ') : ''),
    backCalls: (window.__backCalls || []).slice(),
  };
}
"""


class _Handler(M._Handler):
    pass


def _app():
    return "http://127.0.0.1:%d/web/index.html" % PORT


def _routes(me_payload=None):
    def _route(route):
        url = route.request.url.split("?")[0]
        if me_payload is not None and url.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me_payload))
            return
        if url.endswith("/api/oversight/dossier_feed"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"items": DOSSIER_ITEMS}))
            return
        if url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(CHATS))
            return
        if url.endswith("/api/persona"):
            # Без baseline `/api/persona` UI считает личность «изменённой»
            # (задокументированный артефакт фикстуры W15): тогда любой переход
            # упирается в confirm о несохранённых правках. Отдаём реальные
            # values, чтобы стенд соответствовал продукту.
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(PERSONA_STUB))
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


def _new_page(browser, width, height, touch=False, me=None):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              has_touch=touch)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", _routes(me))
    page = ctx.new_page()
    page.goto(_app() + "#/ai", wait_until="load")
    page.wait_for_selector(".app-shell", timeout=20000)
    page.wait_for_timeout(900)
    page.evaluate(PATCH_BACK)
    return ctx, page


# ═══ секция 1: слои, dropdown, палитра, окно записи (1280) ════════════════
def run_layers(browser, out_dir, report, fails):
    ctx, page = _new_page(browser, 1280, 800)
    layers = {}
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))

    tok = page.evaluate(PROBE_TOKENS)
    report["tokens"] = tok
    fails.extend(_fails_tokens(tok))

    page.click(".scope-trigger")
    page.wait_for_timeout(400)
    scope = page.evaluate(PROBE_PANEL, ".scope-panel")
    report["scope1280"] = scope
    layers["scope"] = (page.evaluate(PROBE_Z, ".scope-panel") or {}).get("z")
    if not scope or not scope["insideViewport"]:
        fails.append("dropdown области выходит за вьюпорт 1280: %s" % scope)
    if scope and not scope["hitInside"]:
        fails.append("поверх dropdown просвечивает/перехватывает другой слой")
    if scope and (scope["bgAlpha"] or 0) < 0.9:
        fails.append("подложка dropdown прозрачна до нечитаемости: %s"
                     % scope["bgAlpha"])
    if scope and scope["placement"] not in ("bottom", "top"):
        fails.append("на 1280 панель области не dropdown (placement=%s)"
                     % scope["placement"])
    if scope and scope["rect"]["w"] > 480:
        fails.append("на 1280 dropdown растянулся как лист: %s" % scope["rect"])
    page.screenshot(path=os.path.join(out_dir,
                                      "asap-ui-delta-1280-scope.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)

    layers["header"] = (page.evaluate(PROBE_Z, "header.header-sticky") or {}).get("z")
    layers["toast"] = (page.evaluate(PROBE_Z, ".toast-wrap") or {}).get("z")

    route_before = page.evaluate("() => window.location.hash")
    page.evaluate("() => { window.__backCalls = []; }")
    page.click("[data-palette-open]")
    page.wait_for_timeout(350)
    pal = page.evaluate(PROBE_PANEL, ".palette-panel")
    layers["palette"] = (page.evaluate(PROBE_Z, ".palette-root") or {}).get("z")
    back_calls = page.evaluate("() => (window.__backCalls || []).slice()")
    focused = page.evaluate("() => (document.activeElement || {}).id || ''")
    report["palette1280"] = {"panel": pal, "backCalls": back_calls,
                             "focused": focused, "route": route_before}
    if not pal or not pal["insideViewport"]:
        fails.append("палитра выходит за вьюпорт 1280: %s" % pal)
    if pal and (pal["bgAlpha"] or 0) < 0.9:
        fails.append("палитра просвечивает (нечитаемо): %s" % pal["bgAlpha"])
    if focused != "palette-input":
        fails.append("ввод палитры не в фокусе: %r" % focused)
    if 'show' not in back_calls:
        fails.append("при открытой палитре на корневом маршруте Back недоступен")
    page.screenshot(path=os.path.join(out_dir,
                                      "asap-ui-delta-1280-palette.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    after = page.evaluate(
        "() => ({open: !!document.querySelector('[data-command-palette]'),"
        " route: window.location.hash})")
    report["paletteEsc"] = after
    if after["open"]:
        fails.append("Esc не закрыл палитру")
    if after["route"] != route_before:
        fails.append("Esc в палитре изменил маршрут: %s -> %s"
                     % (route_before, after["route"]))

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
        report["record1280"] = rec
        if not rec:
            fails.append("окно записи не открылось по строке")
        else:
            if "#4242" not in rec["allText"]:
                fails.append("окно открыло другую запись: %r"
                             % rec["allText"][:120])
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
            layers["recordScrim"] = (
                page.evaluate(PROBE_Z, ".sfeed-modal-backdrop") or {}).get("z")
            page.screenshot(path=os.path.join(out_dir,
                                              "asap-ui-delta-1280-record.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(350)
            closed = page.evaluate(
                "() => ({open: !!document.querySelector('[data-sfeed-modal]'),"
                " row: !!(document.activeElement && document.activeElement"
                ".getAttribute && document.activeElement"
                ".getAttribute('data-sfeed-row') !== null),"
                " route: window.location.hash})")
            report["recordEsc"] = closed
            if closed["open"]:
                fails.append("Esc не закрыл окно записи")
            if not closed["row"]:
                fails.append("фокус не вернулся в строку записи")
            if closed["route"] != route_status:
                fails.append("закрытие окна записи изменило маршрут: %s -> %s"
                             % (route_status, closed["route"]))
    if errs:
        fails.append("js-ошибки на странице: %s" % errs[:3])
    report["layers"] = layers
    ctx.close()
    return layers


# ═══ секция 2: панель области — ЛИСТ на телефоне, dropdown на ≥768 ════════
def _check_sheet(probe, label, fails):
    """Инварианты листа: внутри видимой области, снизу, фото-читаемое имя."""
    if not probe or not probe.get("open"):
        fails.append("%s: панель области не открылась" % label)
        return
    if probe["placement"] != "sheet":
        fails.append("%s: панель области не лист (placement=%s)"
                     % (label, probe["placement"]))
    if probe["position"] != "fixed":
        fails.append("%s: лист не position:fixed (%s)"
                     % (label, probe["position"]))
    if not probe["inside"]:
        fails.append("%s: лист вне видимой области (rect=%s vh=%s)"
                     % (label, probe["rect"], probe["vh"]))
    if probe["bottomGap"] < -1 or probe["bottomGap"] > 24:
        fails.append("%s: лист не прижат к низу видимой области (gap=%s)"
                     % (label, probe["bottomGap"]))
    if probe["rect"]["w"] < probe["vw"] - 24:
        fails.append("%s: лист уже своей ширины (%s из %s)"
                     % (label, probe["rect"]["w"], probe["vw"]))
    if probe["optionH"] is None or probe["optionH"] < 44:
        fails.append("%s: пункт листа ниже tap-цели 44px (%s)"
                     % (label, probe["optionH"]))
    worst = probe.get("titleWorst") or {}
    if worst.get("clip") is None or worst["clip"] > 1:
        fails.append("%s: самое длинное название обрезано по ширине (clip=%s, %r)"
                     % (label, worst.get("clip"), worst.get("text")))
    if worst.get("lines") and worst["lines"] > 2:
        fails.append("%s: название занимает больше двух строк (%s)"
                     % (label, worst["lines"]))
    # Вертикаль: низ второй строки не должен срезаться (ревью B1: было
    # clientHeight 38 при scrollHeight 42 из-за max-height в 1.35em).
    # У `-webkit-line-clamp` scrollHeight содержит и скрытый остаток, поэтому:
    #   * уместившееся имя — scrollHeight == clientHeight (ничего не спрятано);
    #   * сокращённое — clientHeight ровно 2 реальные строки (кратно line-height),
    #     а не 38 px при строке 21 px.
    rows = probe.get("titleRows") or []
    if not rows:
        fails.append("%s: нет длинных подписей — вертикаль листа не проверена"
                     % label)
    for r in rows:
        lh = r.get("lh") or 0
        if r["lines"] and r["lines"] > 2:
            fails.append("%s: подпись длиной %s занимает %s строк (нужно <= 2)"
                         % (label, r["len"], r["lines"]))
        if r["scrollH"] <= r["clientH"] + 1:
            continue                       # уместилось целиком
        if not lh or r["clientH"] % lh != 0 or round(r["clientH"] / lh) != 2:
            fails.append("%s: подпись обрезана по высоте (len=%s, clientHeight=%s "
                         "при строке %s, clamp=%s) — должно быть ровно 2 строки"
                         % (label, r["len"], r["clientH"], lh, r["clamp"]))
    # 60-символьное имя обязано уместиться целиком (именно это ломал
    # max-height 37.8 px): scrollHeight == clientHeight, 1–2 полные строки.
    fits = [r for r in rows if 40 <= r["len"] <= 80]
    if not fits:
        fails.append("%s: нет подписи средней длины — полноту двух строк "
                     "не проверить" % label)
    for r in fits:
        if r["scrollH"] != r["clientH"] or r["lines"] not in (1, 2):
            fails.append("%s: имя из %s символов не уместилось полностью "
                         "(lines=%s, clientH=%s, scrollH=%s)"
                         % (label, r["len"], r["lines"], r["clientH"], r["scrollH"]))
    if probe["titleClip"] is None or probe["titleClip"] > 1:
        fails.append("%s: название в листе обрезано по ширине (clip=%s)"
                     % (label, probe["titleClip"]))
    if probe["titleLines"] and probe["titleLines"] > 2:
        fails.append("%s: название занимает больше двух строк (%s)"
                     % (label, probe["titleLines"]))
    if probe["hScrollPage"]:
        fails.append("%s: лист дал горизонтальный скролл страницы" % label)


def run_sheet(browser, out_dir, report, fails):
    for (w, h, touch, name) in ((320, 700, True, "320"),
                                (360, 780, True, "360"),
                                (390, 844, True, "390"),
                                (667, 375, True, "667x375")):
        ctx, page = _new_page(browser, w, h, touch=touch)
        if name == "390":
            # Слои навигации измеряем здесь же: drawer нужен только на телефоне.
            page.tap("[data-drawer-trigger]")
            page.wait_for_timeout(400)
            report["drawer390"] = {
                "z": (page.evaluate(PROBE_Z, ".app-drawer") or {}).get("z"),
                "scrim": (page.evaluate(PROBE_Z, ".drawer-backdrop") or {}).get("z"),
            }
            page.screenshot(path=os.path.join(
                out_dir, "asap-ui-delta-390-drawer.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        page.tap(".scope-trigger")
        page.wait_for_timeout(450)
        probe = page.evaluate(PROBE_SCOPE)
        report[name] = probe
        _check_sheet(probe, name, fails)
        page.screenshot(path=os.path.join(
            out_dir, "asap-ui-delta-%s-scope-sheet.png" % name))
        # Выбор тапом: реальный продуктовый путь (pickScope), а не setState.
        if probe and probe.get("options"):
            page.tap(".scope-panel .scope-option:nth-of-type(2)")
            page.wait_for_timeout(450)
            sel = page.evaluate(PROBE_VM)
            report[name + "_select"] = {
                "activeChatId": sel["activeChatId"],
                "scopeKind": sel["scopeKind"],
                "panelOpen": bool(sel["backStack"] and "scope" in sel["backStack"]),
            }
            if sel["activeChatId"] is None or sel["scopeKind"] == "global":
                fails.append("%s: выбор чата тапом не применился (%s)"
                             % (name, report[name + "_select"]))
        ctx.close()

    # ≥768: прежний якорный dropdown с flip (лист не включается)
    for (w, h, name) in ((768, 1024, "768"), (1280, 800, "1280")):
        ctx, page = _new_page(browser, w, h)
        page.click(".scope-trigger")
        page.wait_for_timeout(400)
        probe = page.evaluate(PROBE_SCOPE)
        report[name] = probe
        if not probe:
            fails.append("%s: dropdown области не открылся" % name)
        elif probe["placement"] not in ("bottom", "top"):
            fails.append("%s: на широком экране панель не dropdown (%s)"
                         % (name, probe["placement"]))
        elif probe["rect"]["w"] > 480:
            fails.append("%s: dropdown растянулся как лист (%s)"
                         % (name, probe["rect"]))
        ctx.close()
    return report


# ═══ секция 3: §12 п.6 — стабильная шапка + порядок Back ══════════════════
def run_scenario6(browser, out_dir, report, fails):
    out = {}
    ctx, page = _new_page(browser, 390, 844, touch=True)
    page.evaluate("() => { window.location.hash = '#/status'; }")
    page.wait_for_timeout(1200)

    header_before = page.evaluate(PROBE_VM)
    page.evaluate("() => { const m = document.querySelector('main.scroll-area');"
                  " if (m) m.scrollTop = 600; }")
    page.wait_for_timeout(500)
    header_scrolled = page.evaluate(PROBE_VM)
    out["header"] = {"before": header_before["headerTop"],
                     "afterScroll": header_scrolled["headerTop"],
                     "heightBefore": header_before["headerH"],
                     "heightAfter": header_scrolled["headerH"]}
    if header_scrolled["headerTop"] != header_before["headerTop"]:
        fails.append("сценарий 6: шапка уехала при прокрутке (%s -> %s)"
                     % (header_before["headerTop"], header_scrolled["headerTop"]))
    if abs(header_scrolled["headerH"] - header_before["headerH"]) > 1:
        fails.append("сценарий 6: высота шапки меняется при прокрутке (%s -> %s)"
                     % (header_before["headerH"], header_scrolled["headerH"]))
    page.evaluate("() => { const m = document.querySelector('main.scroll-area');"
                  " if (m) m.scrollTop = 0; }")
    page.wait_for_timeout(300)

    # Порядок Back: два РЕАЛЬНЫХ слоя одновременно (dropdown области + палитра).
    page.tap(".scope-trigger")
    page.wait_for_timeout(350)
    page.evaluate("() => { window.__adminbotVm.openPalette(); }")
    page.wait_for_timeout(350)
    both = page.evaluate(PROBE_VM)
    out["stackTwoLayers"] = both["backStack"]
    route0 = both["route"]
    if not both["backStack"] or both["backStack"][:2] != ["palette", "scope"]:
        fails.append("сценарий 6: ожидался стек ['palette','scope'], получен %s"
                     % both["backStack"])

    page.evaluate("() => { window.__adminbotVm.goBack(); }")   # тот же путь, что BackButton
    page.wait_for_timeout(350)
    one = page.evaluate(PROBE_VM)
    out["afterFirstBack"] = {"stack": one["backStack"], "route": one["route"]}
    if one["backStack"] != ["scope"]:
        fails.append("сценарий 6: первый Back закрыл не только палитру (%s)"
                     % one["backStack"])
    if one["route"] != route0:
        fails.append("сценарий 6: первый Back сменил маршрут (%s -> %s)"
                     % (route0, one["route"]))

    page.evaluate("() => { window.__adminbotVm.goBack(); }")
    page.wait_for_timeout(350)
    zero = page.evaluate(PROBE_VM)
    out["afterSecondBack"] = {"stack": zero["backStack"], "route": zero["route"]}
    if zero["backStack"]:
        fails.append("сценарий 6: второй Back не закрыл dropdown области (%s)"
                     % zero["backStack"])
    if zero["route"] != route0:
        fails.append("сценарий 6: второй Back сменил маршрут (%s -> %s)"
                     % (route0, zero["route"]))

    # Лист записи на корневом маршруте: Back закрывает только его.
    row = page.locator("[data-sfeed-row]").first
    if row.count():
        row.tap()
        page.wait_for_timeout(450)
        with_sheet = page.evaluate(PROBE_VM)
        out["recordOpen"] = {"stack": with_sheet["backStack"],
                             "route": with_sheet["route"]}
        page.screenshot(path=os.path.join(out_dir,
                                          "asap-ui-delta-scenario6-record-390.png"))
        page.evaluate("() => { window.__adminbotVm.goBack(); }")
        page.wait_for_timeout(450)
        after_sheet = page.evaluate(PROBE_VM)
        out["recordBack"] = {"stack": after_sheet["backStack"],
                             "route": after_sheet["route"],
                             "modal": page.evaluate(
                                 "() => !!document.querySelector('[data-sfeed-modal]')")}
        if out["recordBack"]["modal"]:
            fails.append("сценарий 6: Back не закрыл лист записи")
        if after_sheet["route"] != with_sheet["route"]:
            fails.append("сценарий 6: Back из листа записи сменил маршрут")

    # Fullscreen-граф: открывается только админом; Back закрывает только его.
    page.evaluate("() => { window.location.hash = '#/status'; }")
    page.wait_for_timeout(900)
    opened = page.evaluate(
        "() => { const vm = window.__adminbotVm; if (!vm || !vm.isGlobalAdmin)"
        " return 'no-admin'; vm.openGraphFull(); return 'opened'; }")
    if opened == "opened":
        page.wait_for_timeout(700)
        g1 = page.evaluate(PROBE_VM)
        out["graphOpen"] = {"stack": g1["backStack"], "route": g1["route"]}
        page.evaluate("() => { window.__adminbotVm.goBack(); }")
        page.wait_for_timeout(500)
        g2 = page.evaluate(PROBE_VM)
        out["graphBack"] = {"stack": g2["backStack"], "route": g2["route"]}
        if out["graphOpen"]["stack"] != ["graph-full"]:
            fails.append("сценарий 6: fullscreen-граф не единственный верхний "
                         "слой (%s)" % out["graphOpen"]["stack"])
        if g2["backStack"]:
            fails.append("сценарий 6: Back не закрыл fullscreen-граф (%s)"
                         % g2["backStack"])
        if g2["route"] != "#/":
            fails.append("сценарий 6: Back из графа не вернул на родителя "
                         "маршрута (route=%s)" % g2["route"])
    else:
        out["graphOpen"] = opened

    # Telegram Back: нативный обработчик привязан ровно к goBack, поэтому
    # проверяем и доступность кнопки, и сам путь (show уже ловили в layers).
    page.evaluate("() => { window.__backCalls = []; window.__adminbotVm.openPalette(); }")
    page.wait_for_timeout(350)
    tg = page.evaluate(PROBE_VM)
    out["telegramBack"] = {"showRequested": 'show' in tg["backCalls"],
                           "stack": tg["backStack"]}
    if 'show' not in tg["backCalls"]:
        fails.append("сценарий 6: Telegram Back не стал доступен при слое на корне")
    page.evaluate("() => { window.__adminbotVm.goBack(); }")
    page.wait_for_timeout(300)
    report["scenario6"] = out
    ctx.close()
    return out


# ═══ секция 4: §12 п.14 — поиск и deep link ═══════════════════════════════
def _open_prompt_editor(page):
    """Открыть реальный редактор промпта через собственный реестр приложения."""
    page.evaluate("() => { window.location.hash = '#/modules'; }")
    page.wait_for_timeout(1100)
    target = page.evaluate(r"""
        () => {
          const vm = window.__adminbotVm;
          const mods = vm.modules || [];
          if (!mods.length) return {err: 'modules не загрузились'};
          const m = mods.find(
            (x) => vm.workspacePromptItems && vm.workspacePromptItems(x).length > 0);
          if (!m) return {err: 'нет модуля с промптами'};
          const slug = vm.routeSlugOf(m);
          const it = vm.workspacePromptItems(m)[0];
          const route = '#/ai/prompts/' + slug + (it.stage ? '/' + it.stage : '')
            + '/' + it.key;
          vm.navigateTo(route);
          return {slug: slug, key: it.key, route: route};
        }
    """)
    page.wait_for_timeout(1300)
    try:
        page.wait_for_selector("[data-prompt-textarea]", timeout=9000)
    except Exception:  # noqa: BLE001
        return None
    if not target or target.get("err"):
        return None
    return target


def run_scenario14(browser, out_dir, report, fails):
    out = {}
    ctx, page = _new_page(browser, 1280, 800)
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))

    # scope: работаем в конкретном чате, чтобы проверить сохранение области
    page.click(".scope-trigger")
    page.wait_for_timeout(300)
    page.click(".scope-panel .scope-option:nth-of-type(2)")
    page.wait_for_timeout(600)
    base = page.evaluate(PROBE_VM)
    out["scopeBefore"] = {"kind": base["scopeKind"],
                          "chat": base["activeChatId"]}

    # поиск из ЛЮБОГО экрана (здесь — из «Речи и характера»): Ctrl+K
    page.evaluate("() => { window.location.hash = '#/ai/speech'; }")
    page.wait_for_timeout(900)
    page.keyboard.press("Control+k")
    page.wait_for_timeout(400)
    opened = page.evaluate(PROBE_VM)
    out["paletteFromSpeech"] = {"open": opened["paletteOpen"],
                                "scope": opened["scopeLabel"]}
    if not opened["paletteOpen"]:
        fails.append("сценарий 14: Ctrl+K не открыл палитру на экране речи")
    page.fill("#palette-input", "инициатива")
    page.wait_for_timeout(500)
    items = page.evaluate(PROBE_VM)
    out["queryItems"] = items["paletteItems"]
    page.screenshot(path=os.path.join(out_dir,
                                      "asap-ui-delta-scenario14-palette.png"))
    # Берём результат, у которого есть адресный `?focus=` (конкретный объект,
    # а не «верх раздела») — это и есть предмет клаузулы. `data-palette-dest`
    # содержит только маршрут, поэтому focus берём из модели выдачи.
    concrete = page.evaluate(r"""
        () => {
          const vm = window.__adminbotVm;
          const hits = (vm.paletteMatches || []).filter((e) => e.focus);
          const e = hits[0];
          if (!e) return null;
          return {id: e.id, dest: e.route, focus: e.focus, title: e.title};
        }
    """)
    out["concreteRow"] = concrete
    if not items["paletteItems"]:
        fails.append("сценарий 14: поиск не дал результатов по «инициатива»")
    elif not concrete:
        fails.append("сценарий 14: среди результатов нет адресной цели "
                     "(только «верх раздела»): %s" % items["paletteItems"])
    else:
        # Выбор результата — клавиатурный путь палитры (курсор + Enter):
        # так же работает пользователь, и это не зависит от перерисовки строк.
        page.evaluate("(id) => { window.__adminbotVm.paletteCursorId = id; }",
                      concrete["id"])
        page.press("#palette-input", "Enter")
        # Подсветка живёт 1.6 c — ловим её опросом, а не одним замером.
        pulse_seen = False
        for _ in range(8):
            page.wait_for_timeout(200)
            if page.evaluate("() => !!document.querySelector('.focus-pulse')"):
                pulse_seen = True
                break
        after = page.evaluate(PROBE_VM)
        out["target"] = {"route": after["route"],
                         "focusPulse": pulse_seen,
                         "scope": {"kind": after["scopeKind"],
                                   "chat": after["activeChatId"]}}
        if after["route"] == "#/modules" or after["route"] == "#/":
            fails.append("сценарий 14: результат привёл на верх раздела (%s)"
                         % after["route"])
        if "focus=" not in (after["route"] or ""):
            fails.append("сценарий 14: переход без адресного focus (%s)"
                         % after["route"])
        if not after["focusPulse"]:
            fails.append("сценарий 14: целевой элемент не подсвечен (focus)")
        if (after["scopeKind"] != base["scopeKind"]
                or after["activeChatId"] != base["activeChatId"]):
            fails.append("сценарий 14: переход сбросил область (%s -> %s)"
                         % (out["scopeBefore"], after["scopeKind"]))
        page.screenshot(path=os.path.join(out_dir,
                                          "asap-ui-delta-scenario14-target.png"))

        # «Отсутствующий объект» — честное состояние, а не прыжок на верх.
        page.evaluate("() => { window.location.hash = '#/ai?focus=nope-нет-такого'; }")
        page.wait_for_timeout(4800)
        missing = page.evaluate(PROBE_VM)
        out["missingTarget"] = {"route": missing["route"],
                                "toast": missing["toastText"],
                                "focusPulse": missing["focusPulse"]}
        if "Не удалось перейти к параметру" not in (missing["toastText"] or ""):
            fails.append("сценарий 14: отсутствующий объект без честного "
                         "сообщения (%r)" % (missing["toastText"] or "")[:80])

    # Возврат: чат/scope сохраняются, черновик не теряется молча.
    page.evaluate("() => { window.location.hash = '#/ai/speech'; }")
    page.wait_for_timeout(900)

    # Позиция прокрутки: уход по цели и возврат восстанавливают место чтения.
    page.evaluate("() => { window.location.hash = '#/modules'; }")
    page.wait_for_timeout(1100)
    page.evaluate("() => { const m = document.querySelector('main.scroll-area');"
                  " if (m && m.scrollHeight > m.clientHeight + 1) m.scrollTop = 420;"
                  " window.scrollTo(0, 420); }")
    page.wait_for_timeout(400)
    scrolled = page.evaluate(PROBE_VM)
    row = page.evaluate(r"""
        () => {
          const vm = window.__adminbotVm;
          const e = (vm.paletteIndexEntries || []).find(
            (x) => x.kind === 'module' && x.route !== '#/modules');
          if (!e) return null;
          vm.openPalette();
          vm.paletteSelect(e);
          return e.route;
        }
    """)
    page.wait_for_timeout(1200)
    page.evaluate("() => { window.__adminbotVm.closePalette(); }")
    page.evaluate("() => history.back()")
    page.wait_for_timeout(1600)
    back_scroll = page.evaluate(PROBE_VM)
    out["scrollReturn"] = {"before": scrolled["scrollTop"],
                           "after": back_scroll["scrollTop"],
                           "route": back_scroll["route"],
                           "target": row}
    if not row:
        fails.append("сценарий 14: не нашлось целевого модуля для проверки позиции")
    elif back_scroll["route"] != "#/modules":
        fails.append("сценарий 14: возврат не на тот маршрут (%s)"
                     % back_scroll["route"])
    elif scrolled["scrollTop"] < 100:
        fails.append("сценарий 14: страница не прокрутилась — позиция не проверена "
                     "(scrollTop=%s)" % scrolled["scrollTop"])
    elif abs(back_scroll["scrollTop"] - scrolled["scrollTop"]) > 60:
        fails.append("сценарий 14: возврат не восстановил позицию (%s -> %s)"
                     % (scrolled["scrollTop"], back_scroll["scrollTop"]))

    page.evaluate("() => { window.location.hash = '#/ai/speech'; }")
    page.wait_for_timeout(900)
    target = _open_prompt_editor(page)
    if not target:
        fails.append("сценарий 14: редактор промпта не открылся — черновик "
                     "проверить нечем")
    else:
        marker = "черновик-14 не сохранять"
        page.click("[data-prompt-textarea]")
        page.fill("[data-prompt-textarea]", marker)
        page.wait_for_timeout(400)
        dirty_before = page.evaluate(PROBE_VM)
        out["draft"] = {"dirty": dirty_before["dirty"], "route": dirty_before["route"]}
        if not dirty_before["dirty"]:
            fails.append("сценарий 14: ввод в редактор не пометил черновик")
        # Уход по целевому объекту требует подтверждения: отказ = остаёмся.
        page.evaluate("() => { window.__adminbotVm._paletteDeclined = false; }")
        answer = {"value": False}

        def _on_dialog(dialog):
            answer["value"] = True
            dialog.dismiss()

        page.on("dialog", _on_dialog)
        page.evaluate("() => { window.__adminbotVm.openPalette(); }")
        page.wait_for_timeout(300)
        page.fill("#palette-input", "модули")
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(900)
        page.remove_listener("dialog", _on_dialog)
        declined = page.evaluate(PROBE_VM)
        out["draftGuardDecline"] = {"dialogShown": answer["value"],
                                    "route": declined["route"],
                                    "dirty": declined["dirty"]}
        if not answer["value"]:
            fails.append("сценарий 14: уход с черновика прошёл без подтверждения")
        if declined["route"] != dirty_before["route"]:
            fails.append("сценарий 14: отказ не удержал маршрут (%s -> %s)"
                         % (dirty_before["route"], declined["route"]))
        kept = page.evaluate(
            "() => (document.querySelector('[data-prompt-textarea]') || {}).value")
        out["draftKept"] = kept
        if kept != marker:
            fails.append("сценарий 14: черновик потерян при отказе уйти (%r)"
                         % (kept or "")[:60])

        # Согласие: уходим, затем возвращаемся — ввод не «исчез молча».
        page.on("dialog", lambda d: d.accept())
        page.evaluate("() => { window.__adminbotVm.openPalette(); }")
        page.wait_for_timeout(300)
        page.fill("#palette-input", "модули")
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)
        left = page.evaluate(PROBE_VM)
        out["draftLeft"] = {"route": left["route"], "dirty": left["dirty"]}
        page.evaluate("() => history.back()")
        page.wait_for_timeout(1400)
        back = page.evaluate(PROBE_VM)
        back_val = page.evaluate(
            "() => (document.querySelector('[data-prompt-textarea]') || {}).value")
        out["returnFromTarget"] = {
            "route": back["route"], "dirty": back["dirty"],
            "scope": {"kind": back["scopeKind"], "chat": back["activeChatId"]},
            "text": (back_val or "")[:40],
            "scrollTop": back["scrollTop"],
        }
        if (back["scopeKind"] != base["scopeKind"]
                or back["activeChatId"] != base["activeChatId"]):
            fails.append("сценарий 14: возврат сбросил область (%s)"
                         % out["returnFromTarget"]["scope"])
        if back_val is not None and back_val != marker:
            fails.append("сценарий 14: после возврата черновик не восстановлен "
                         "(%r)" % (back_val or "")[:60])
        if back_val is None:
            fails.append("сценарий 14: после возврата редактор не открылся — "
                         "восстановление черновика не доказано")
    if errs:
        fails.append("сценарий 14: js-ошибки %s" % errs[:2])
    report["scenario14"] = out
    ctx.close()
    return out


# ═══ секция 5: RBAC ограниченной роли (L01943) ════════════════════════════
def run_rbac(browser, out_dir, report, fails):
    out = {}
    admin = None
    ctx, page = _new_page(browser, 1280, 800)
    admin = page.evaluate(PROBE_VM)
    out["admin"] = {"count": admin["paletteCount"]}
    ctx.close()

    ctx, page = _new_page(browser, 1280, 800, me=RESTRICTED_ME)
    restricted = page.evaluate(PROBE_VM)
    detail = page.evaluate(r"""
        () => {
          const vm = window.__adminbotVm;
          const idx = vm.paletteIndexEntries || [];
          const routes = idx.map((e) => e.route);
          const secrets = (vm.configItems || []).filter(
            (it) => it && (it.secret === true || it.category === 'keys'));
          const leaked = secrets.filter((it) => routes.indexOf(
            vm._settingDestination && vm._settingDestination(it)
              ? vm._settingDestination(it).route : '') >= 0
            && idx.some((e) => e.id === 'setting:' + it.key
                        || e.id === 'prompt:' + it.key));
          const sections = idx.filter((e) => e.kind === 'section')
            .map((e) => e.route);
          const modules = idx.filter((e) => e.kind === 'module').length;
          return {
            count: idx.length,
            kinds: idx.reduce((a, e) => { a[e.kind] = (a[e.kind] || 0) + 1; return a; }, {}),
            sections: sections,
            modules: modules,
            hasRuns: routes.indexOf('#/oversight?tab=runs') >= 0,
            hasCosts: routes.indexOf('#/oversight?tab=costs') >= 0,
            hasModels: routes.indexOf('#/oversight?tab=models') >= 0,
            hasAccess: routes.indexOf('#/access') >= 0,
            hasMemory: routes.indexOf('#/memory') >= 0,
            blockedTabs: (vm.tabs || []).filter((t) => !vm.canViewTab(t.id))
              .map((t) => t.id),
            blockedModuleLeaks: (() => {
              const blocked = (vm.modules || []).filter(
                (m) => m.tab && !vm.canViewTab(m.tab))
                .map((m) => '#/modules/' + vm.routeSlugOf(m));
              return idx.filter((e) => e.kind === 'module'
                && blocked.indexOf(e.route) >= 0).map((e) => e.route);
            })(),
            secretCount: secrets.length,
            secretLeaks: leaked.length,
            isGlobalAdmin: vm.isGlobalAdmin,
            perms: vm.permissions,
          };
        }
    """)
    out["restricted"] = detail
    page.screenshot(path=os.path.join(out_dir,
                                      "asap-ui-delta-rbac-restricted.png"))
    if detail["count"] >= out["admin"]["count"]:
        fails.append("RBAC: индекс палитры у ограниченной роли не сузился "
                     "(%s против %s)" % (detail["count"], out["admin"]["count"]))
    for key, label in (("hasRuns", "запуски Аналитики"),
                       ("hasCosts", "токены/стоимость"),
                       ("hasModels", "модели/контекст"),
                       ("hasAccess", "Доступы")):
        if detail[key]:
            fails.append("RBAC: в палитре ограниченной роли есть %s" % label)
    if detail["blockedModuleLeaks"]:
        fails.append("RBAC: в палитре есть модули недоступных вкладок (%s)"
                     % detail["blockedModuleLeaks"][:3])
    if not detail["hasMemory"]:
        fails.append("RBAC: у роли с секцией memory пропала разрешённая цель Памяти")
    if detail["secretCount"] and detail["secretLeaks"]:
        fails.append("RBAC: секреты попали в индекс палитры (%s)"
                     % detail["secretLeaks"])

    # (b) deep-link к недоступной цели — честный отказ, а не пустой экран.
    page.evaluate("() => { window.location.hash = '#/access'; }")
    page.wait_for_timeout(1200)
    denied = page.evaluate(PROBE_VM)
    out["deepLinkDenied"] = {"route": denied["route"],
                             "toast": denied["toastText"]}
    if denied["route"] == "#/access":
        fails.append("RBAC: deep-link в недоступный раздел не отклонён")
    if "Нет доступа" not in (denied["toastText"] or ""):
        fails.append("RBAC: отказ без честного сообщения (%r)"
                     % (denied["toastText"] or "")[:80])

    # (b2) недоступная цель через палитру недостижима и через прямой focus.
    # Маршрут обязан отличаться от текущего, иначе applyRoute не выполнится.
    page.evaluate("() => { window.location.hash = '#/memory?focus=module-card:mod_x'; }")
    page.wait_for_timeout(5000)
    focus_denied = page.evaluate(PROBE_VM)
    out["focusDenied"] = {"route": focus_denied["route"],
                          "toast": focus_denied["toastText"]}
    if "Не удалось перейти к параметру" not in (focus_denied["toastText"] or ""):
        fails.append("RBAC: недоступная цель без честного сообщения (%r)"
                     % (focus_denied["toastText"] or "")[:80])

    # (c) возврат восстанавливает чат/scope (стабильность области).
    page.evaluate("() => { const vm = window.__adminbotVm;"
                  " vm.setActiveChat(vm.accessChats.length > 1"
                  "   ? vm.accessChats[1].chat_id : null); }")
    page.wait_for_timeout(800)
    scoped = page.evaluate(PROBE_VM)
    page.evaluate("() => { window.__adminbotVm.openPalette(); }")
    page.wait_for_timeout(300)
    page.fill("#palette-input", "память")
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)
    moved = page.evaluate(PROBE_VM)
    page.evaluate("() => history.back()")
    page.wait_for_timeout(1200)
    returned = page.evaluate(PROBE_VM)
    out["scopeReturn"] = {
        "before": {"kind": scoped["scopeKind"], "chat": scoped["activeChatId"]},
        "after": {"kind": moved["scopeKind"], "chat": moved["activeChatId"]},
        "returned": {"kind": returned["scopeKind"],
                     "chat": returned["activeChatId"]},
    }
    if (returned["scopeKind"] != scoped["scopeKind"]
            or returned["activeChatId"] != scoped["activeChatId"]):
        fails.append("RBAC: переход/возврат сбросил область (%s)"
                     % out["scopeReturn"])
    report["rbac"] = out
    ctx.close()
    return out


def run(out_dir):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    report = {}
    fails = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        layers = run_layers(browser, out_dir, report, fails)
        run_sheet(browser, out_dir, report, fails)
        drawer = report.get("drawer390") or {}
        layers["drawer"] = drawer.get("z")
        layers["drawerBackdrop"] = drawer.get("scrim")
        report["layers"] = layers
        fails.extend(_fails_layer_order(layers))
        run_scenario6(browser, out_dir, report, fails)
        run_scenario14(browser, out_dir, report, fails)
        run_rbac(browser, out_dir, report, fails)
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
