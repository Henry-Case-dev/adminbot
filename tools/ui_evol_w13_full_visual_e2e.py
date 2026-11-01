"""EVOL-033 (W13) — сквозная визуальная приёмка ВСЕХ маршрутов Mini App.

Детерминированный Playwright-прогон НАСТОЯЩЕГО `web/index.html` + `web/app.js`
+ `web/static/*` (сервер/стабы — из `tools/ui_round1025_matrix.py`, секретов
нет, живых сообщений в Telegram не отправляется).

Проверяется (plans/current_task.md L478–552, строка карты L00478):

  1. ИНВЕНТАРЬ: маршрутный граф читается из самого `web/app.js`
     (`ROUTE_TO_TAB` / `ROUTE_ALIAS` / `ROOT_ROUTES` / `WORKSPACE_TABS`),
     поэтому ни один экран не «забыт» списком в тесте; каждый адрес
     валидируется в рантайме (канонический hash после applyRoute, заголовок
     экрана, непустой контент). Легаси-алиасы фиксируются как редиректы,
     а не как экраны.
  2. РАЗВЁРТКА: каждый экран × 10 вьюпортов (320/360/390/430, 600/768/1024,
     1440/1920, низкий ландшафт 667×375): горизонтальный скролл, элементы за
     вьюпортом, обрезанный текст, тач-цели < 44 px, высота шапки, ошибки
     консоли, длина текста контента.
  3. СОСТОЯНИЯ: normal/degraded/failed/unknown/disabled и
     empty/loading/partial/error на реальных поверхностях (карточка бота,
     сердцебиение, каталог модулей, прогресс, палитра, лист записи) —
     состояние считается тем же кодом `web/app.js`, что и в проде
     (`healthStateFrom`), проверяется по фактическому `data-health-state`.
  4. ПОРТАЛЫ/ФОКУС: один лестничный механизм `--z-*`, портал в `<body>`,
     ловушка фокуса, возврат фокуса, Esc/Back закрывает РОВНО один слой.

Запуск:
    C:\\Code\\Python\\adminbot\\.venv\\Scripts\\python.exe \\
        tools\\ui_evol_w13_full_visual_e2e.py [--only inv|sweep|states|portal|extras]
                                              [--out DIR] [--limit N]

Артефакты по умолчанию: plans/features/evol/audit/evidence/evol-033/
"""
import argparse
import copy
import io
import json
import os
import re
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

import ui_round1025_matrix as M          # noqa: E402  сервер/стабы/TMA
import ui_evol_w9_responsive_e2e as W9   # noqa: E402  стабы/вьюпорты
import ui_evol_w7_nav_e2e as W7          # noqa: E402  эвристика «за вьюпортом»
# W10: стаб ленты досье (`_DOSSIER`) нужен листу записи — тот же набор
# фикстур, что у волны секций, без второй копии данных в этом инструменте.
import ui_evol_w10_sections_e2e as W10   # noqa: E402

PORT = 8853
DEFAULT_OUT = os.path.join(REPO, "plans", "features", "evol", "audit",
                           "evidence", "evol-033")

# ── вьюпорты: эталонная шкала строки L00478 ─────────────────────────────────
VIEWPORTS = (
    (320, 568), (360, 640), (390, 844), (430, 932),      # телефоны
    (600, 800), (768, 1024), (1024, 768),                # планшет
    (1440, 900), (1920, 1080),                           # десктоп
    (667, 375),                                          # низкий ландшафт
)
SHOT_VIEWPORTS = ((390, 844), (1440, 900))
SHRUNK_VIEWPORTS = ((320, 568), (360, 640), (430, 932), (600, 800),
                    (768, 1024), (1024, 768), (1920, 1080), (667, 375))

HEAD_MAX_PHONE = 78
HEAD_MAX_LAND = 62
HEAD_MAX_MID = 132
TOUCH_MIN = 44
# Плотная сетка часов: 24 ячейки в ряд не могут быть 44 px без потери
# читаемости — проверяется отдельно, как в W9 (тот же осознанный exemption).
# `.sr-only` — визуально скрытый input тумблера (1×1): видимая цель — трек,
# а не сам input (иначе замер даёт ложные 1×1).
TOUCH_EXEMPT = (".viz-heat__cell", ".sr-only")

SETTLE_MS = 320
CELL_SETTLE_MS = 260


# ═══════════════════════════════════════════════════════════════════════════
# 1. МАРШРУТНЫЙ ИНВЕНТАРЬ — из самого app.js (не список в тесте)
# ═══════════════════════════════════════════════════════════════════════════
def _app_src():
    return io.open("web/app.js", encoding="utf-8").read()


def _literal_block(src, marker):
    i = src.find(marker)
    if i < 0:
        raise RuntimeError("маркер %r не найден в web/app.js" % marker)
    j = src.find("};", i)
    return src[i:j]


def _pairs(block):
    return list(re.finditer(r"'(#[^']*)'\s*:\s*'([a-z0-9_]+)'", block))


def build_screens():
    """Возвращает (screens, aliases, meta) — полный граф адресов приложения."""
    src = _app_src()
    r2t_block = _literal_block(src, "var ROUTE_TO_TAB = {")
    route_to_tab = [(m.group(1), m.group(2)) for m in _pairs(r2t_block)]
    alias_block = _literal_block(src, "var ROUTE_ALIAS = {")
    alias = [(m.group(1), m.group(2)) for m in
             re.finditer(r"'(#[^']*)'\s*:\s*'(#[^']*)'", alias_block)]
    root_block = src[src.find("var ROOT_ROUTES = ["):]
    root_block = root_block[:root_block.find("];")]
    root_routes = re.findall(r"'(#[^']*)'", root_block)
    wt_block = _literal_block(src, "var WORKSPACE_TABS = {")
    modules = []
    for m in re.finditer(r"(mod_[a-z0-9_]+):\s*\[([^\]]*)\]", wt_block):
        tabs = re.findall(r"'([a-z0-9_]+)'", m.group(2))
        modules.append({"id": m.group(1),
                        "slug": m.group(1)[len("mod_"):], "tabs": tabs})

    alias_map = dict(alias)
    screens, seen = [], set()

    def _add(route, kind, **kw):
        if route in seen:
            return
        seen.add(route)
        row = {"route": route, "kind": kind}
        row.update(kw)
        screens.append(row)

    for route, tab in route_to_tab:
        if route in alias_map:
            continue
        _add(route, "primary" if route in root_routes else "secondary",
             tab=tab)
    # Динамический резолвер workspace: `#/modules/<slug>` (статические
    # `#/modules/budgets|images|vision` уже добавлены выше и не дублируются).
    for m in modules:
        _add("#/modules/%s" % m["slug"], "module", tab="overview",
             module=m["id"], slug=m["slug"])
    # Вкладки workspace: каждая — отдельный экран (`workspace` computed).
    for m in modules:
        for tab in m["tabs"]:
            if tab == "overview":
                continue
            _add("#/modules/%s/%s" % (m["slug"], tab), "module-tab", tab=tab,
                 module=m["id"], slug=m["slug"])
    # Вторая дверь §48: `#/ai/prompts/<slug>` — та же комната из библиотеки.
    for m in modules:
        _add("#/ai/prompts/%s" % m["slug"], "library-door", tab="",
             module=m["id"], slug=m["slug"])
    return screens, alias, {"routeToTab": route_to_tab, "rootRoutes": root_routes,
                            "modules": modules}


# ═══════════════════════════════════════════════════════════════════════════
# 2. ПРОБЫ
# ═══════════════════════════════════════════════════════════════════════════
ROUTE_PROBE = r"""() => {
  const de = document.documentElement;
  const vw = window.innerWidth, vh = window.innerHeight;
  const label = (el) => {
    const cls = (el.className && el.className.toString
      ? el.className.toString() : '').split(/\s+/).filter(Boolean).slice(0, 3);
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  };
  const exempt = %s;
  const inScroller = (el) => {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
      p = p.parentElement;
    }
    return false;
  };
  const off = [], clip = [], small = [], smallLink = [];
  const all = document.querySelectorAll('body *');
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    if (el.closest('[aria-hidden="true"]')) continue;
    const tn = el.tagName;
    if (tn === 'CANVAS' || tn === 'SCRIPT' || tn === 'STYLE'
        || tn === 'TEMPLATE' || tn === 'LINK' || tn === 'OPTION') continue;
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
  // Тач-цели: контролы отдельно от строчных ссылок в тексте (иначе шум).
  const CTRL = 'button,[role="button"],input:not([type="hidden"]),select,'
    + 'textarea,summary,[tabindex]:not([tabindex="-1"])';
  const skip = (el) => {
    for (const sel of exempt) if (el.matches(sel) || el.closest(sel)) return true;
    return false;
  };
  document.querySelectorAll(CTRL).forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    if (parseFloat(cs.opacity) === 0) return;
    if (el.closest('[aria-hidden="true"]')) return;
    if (skip(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.width < 44 || r.height < 44) {
      small.push({el: label(el), w: Math.round(r.width),
                  h: Math.round(r.height),
                  txt: (el.textContent || el.value || '').trim()
                        .slice(0, 28).replace(/\s+/g, ' '),
                  disabled: !!el.disabled});
    }
  });
  document.querySelectorAll('a[href]').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    if (el.closest('[aria-hidden="true"]')) return;
    if (skip(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.width < 44 || r.height < 44) {
      smallLink.push({el: label(el), w: Math.round(r.width),
                      h: Math.round(r.height),
                      txt: (el.textContent || '').trim().slice(0, 28)});
    }
  });
  const hdr = document.querySelector('header.header-sticky');
  const hb = hdr ? hdr.getBoundingClientRect() : null;
  const main = document.querySelector('main.scroll-area');
  const mb = main ? main.getBoundingClientRect() : null;
  const titleEl = document.querySelector('.header-title');
  const text = (main ? main.innerText : document.body.innerText) || '';
  const shell = document.querySelector('.app-shell');
  return {
    vw: vw, vh: vh, sw: de.scrollWidth, hScroll: de.scrollWidth > vw + 1,
    docH: de.scrollHeight,
    shellH: shell ? Math.round(shell.getBoundingClientRect().height) : null,
    // Вертикальный скролл документа (а не внутренней области `main`) —
    // отдельный класс дефекта: шапка/панель не должны раздувать страницу.
    vScroll: de.scrollHeight > vh + 2,
    offCount: off.length, offscreen: off.slice(0, 6),
    clippedCount: clip.length, clipped: clip.slice(0, 6),
    smallCount: small.length, small: small.slice(0, 12),
    smallLinkCount: smallLink.length, smallLinks: smallLink.slice(0, 8),
    headerH: hb ? Math.round(hb.height) : null,
    headerRows: (() => {
      if (!hdr) return null;
      const els = Array.from(hdr.querySelectorAll(':scope > *')).filter((el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return r.height > 1 && cs.display !== 'none' && cs.position !== 'fixed';
      }).map((el) => el.getBoundingClientRect())
        .sort((a, b) => a.top - b.top);
      let rows = 0, bottom = -Infinity;
      els.forEach((r) => { if (r.top >= bottom - 2) { rows++; bottom = r.bottom; } });
      return rows;
    })(),
    shellMode: de.getAttribute('data-shell-mode'),
    title: titleEl ? titleEl.textContent.trim() : '',
    mainTextLen: text.replace(/\s+/g, ' ').trim().length,
    mainTop: mb ? Math.round(mb.top) : null,
    overlap: (hb && mb) ? Math.max(0, Math.round(hb.bottom - mb.top)) : null,
    cards: document.querySelectorAll(
      '[data-glass], .glass-card, .card, section').length,
    hash: window.location.hash,
  };
}
""" % json.dumps(list(TOUCH_EXEMPT))


TITLE_PROBE = r"""
() => {
  const t = document.querySelector('.header-title');
  const main = document.querySelector('main.scroll-area');
  return {
    hash: window.location.hash,
    title: t ? t.textContent.trim() : '',
    textLen: main ? main.innerText.replace(/\s+/g, ' ').trim().length : 0,
    sections: document.querySelectorAll('[data-glass], section').length,
  };
}
"""

CONSOLE_PROBE_SETUP = """
window.__w13Errors = [];
window.addEventListener('error', (e) => {
  window.__w13Errors.push('error: ' + String(e.message || e).slice(0, 200));
});
"""


# ═══════════════════════════════════════════════════════════════════════════
# 3. СТАБЫ API
# ═══════════════════════════════════════════════════════════════════════════
STATUS_BASE = copy.deepcopy(M.STATUS_STUB)
STATUS_BASE["bot"] = {"uptime_seconds": 3600, "state": "running",
                      "errors_total": 0}
STATUS_BASE["uptime"] = {"generated_at": "2026-11-02T09:00:00Z",
                         "started_at": "2026-11-02T08:00:00Z"}
STATUS_BASE["experience"] = {"state": "implemented",
                             "observed_at": "2026-11-02T09:00:00Z"}


# `/api/persona` в наборе стабов матрицы отсутствует → `personaMeta=null`, и
# охранник несохранённых правок (`hasUnsavedEdits`: «сравнить не с чем →
# считаем грязным») блокирует любой переход между адресами через настоящий
# `window.confirm`. Реальный сервер отдаёт `values`, поэтому в фикстуре они
# есть и СОВПАДАЮТ с инициализацией черновика (пустые строки) — это честный
# «пользователь ничего не правил», а не отключение охраны.
PERSONA_STUB = {
    "scope": "global", "chat_id": None, "is_global": True,
    "persona_enabled": True,
    "values": {"name": "", "biography": "", "system_prompt_overrides": "",
               "is_aware_ai": False},
    "updated_at": None,
}
BASE_OVERRIDES = {"/api/persona": PERSONA_STUB}


def _deep(base, overrides):
    data = copy.deepcopy(base)
    for path, value in (overrides or {}).items():
        if path.startswith("__del__"):
            continue
        node = data
        keys = path.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        if value is _DELETE:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return data


class _Delete(object):
    pass


_DELETE = _Delete()


def _api_handler(overrides=None, fail=None, delay_ms=0):
    """`overrides` — путь-суффикс → payload; `fail` — суффикс → HTTP-код."""
    merged = dict(BASE_OVERRIDES)
    merged.update(overrides or {})
    overrides = merged
    fail = fail or {}

    def _route(route):
        url = route.request.url.split("?")[0]
        for marker, code in fail.items():
            if url.endswith(marker):
                route.fulfill(status=code,
                              content_type="application/json",
                              body=json.dumps({"error": "forced %d" % code}))
                return
        for marker, payload in overrides.items():
            if url.endswith(marker):
                if delay_ms:
                    import time
                    time.sleep(delay_ms / 1000.0)
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))
                return
        W9._routes()(route)
    return _route


# ═══════════════════════════════════════════════════════════════════════════
# 4. КОНТЕКСТЫ
# ═══════════════════════════════════════════════════════════════════════════
def _sdk_js(safe_top=0, safe_bottom=0, stable_extra=0, fullscreen=None):
    """Мок SDK: инсеты/стабильная высота/fullscreen — ровно заданные факты."""
    import ui_asap8_w2_fullscreen_e2e as FS
    cfg = {
        "platform": "android", "version": "8.0",
        "hasBoolean": fullscreen is not None,
        "isFullscreen": bool(fullscreen),
        "viewportHeight": 0, "stableHeight": 0,
        "safeAreaInset": {"top": safe_top, "bottom": safe_bottom,
                          "left": 0, "right": 0},
        "contentSafeAreaInset": {"top": 0, "bottom": safe_bottom,
                                 "left": 0, "right": 0},
    }
    return FS.mock_sdk_js(cfg)


def open_ctx(browser, w, h, api=None, sdk_js=None, touch=None):
    phone = w <= 430 or (w <= 940 and h <= 500)
    if touch is None:
        touch = w <= 1024
    ctx = browser.new_context(
        viewport={"width": w, "height": h},
        device_scale_factor=3 if phone else 1,
        is_mobile=phone, has_touch=touch,
    )
    if sdk_js is not None:
        # Официальный SDK подменяется моком СЦЕНАРИЯ (как в FS-прогоне):
        # init-script бесполезен — `/static/vendor/telegram-web-app.js`
        # выполнится позже и перетрёт `window.Telegram`. Мок сам засевает
        # initData, поэтому базовый TMA_STUB тоже не нужен.
        ctx.route("**/static/vendor/telegram-web-app.js",
                  lambda route: route.fulfill(
                      status=200, content_type="application/javascript",
                      body=sdk_js))
    else:
        ctx.add_init_script(M.TMA_STUB)
    ctx.add_init_script(CONSOLE_PROBE_SETUP)
    ctx.route("**/api/**", api or _api_handler())
    return ctx


def _shot(page, out_dir, name, quality=58):
    page.screenshot(path=os.path.join(out_dir, name), type="jpeg",
                    quality=quality)
    return name


def _slug(route):
    s = route.replace("#/", "").replace("/", "-").strip("-")
    return s or "root"


# ═══════════════════════════════════════════════════════════════════════════
# 5. ИНВЕНТАРЬ (рантайм-валидация адресов)
# ═══════════════════════════════════════════════════════════════════════════
def run_inventory(browser, out_dir):
    screens, alias, meta = build_screens()
    rows, alias_rows = [], []
    ctx = open_ctx(browser, 1280, 900, touch=False)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT, wait_until="load")
    page.wait_for_selector(".app-shell", timeout=20000)
    page.wait_for_timeout(900)
    for row in screens:
        page.evaluate("(r) => { window.location.hash = r; }", row["route"])
        page.wait_for_timeout(CELL_SETTLE_MS)
        d = page.evaluate(TITLE_PROBE)
        row.update({"canonicalHash": d["hash"], "title": d["title"],
                    "textLen": d["textLen"], "sections": d["sections"],
                    "rendered": bool(d["textLen"] > 40),
                    "redirected": d["hash"] != row["route"]})
        rows.append(row)
    for route, target in alias:
        page.evaluate("(r) => { window.location.hash = r; }", route)
        page.wait_for_timeout(CELL_SETTLE_MS)
        d = page.evaluate(TITLE_PROBE)
        alias_rows.append({"route": route, "declaredTarget": target,
                           "actualHash": d["hash"], "title": d["title"],
                           "textLen": d["textLen"]})
    page.evaluate("() => { window.location.hash = '#/'; }")
    ctx.close()
    data = {"screens": rows, "aliases": alias_rows,
            "meta": {"routeToTab": meta["routeToTab"],
                     "rootRoutes": meta["rootRoutes"],
                     "modules": meta["modules"]},
            "summary": {
                "screens": len(rows),
                "sweepable": sum(1 for r in rows if not r["redirected"]),
                "primary": sum(1 for r in rows if r["kind"] == "primary"),
                "secondary": sum(1 for r in rows if r["kind"] == "secondary"),
                "module": sum(1 for r in rows if r["kind"] == "module"),
                "moduleTabs": sum(1 for r in rows if r["kind"] == "module-tab"),
                "libraryDoors": sum(1 for r in rows
                                    if r["kind"] == "library-door"),
                "aliases": len(alias_rows),
                "notRendered": [r["route"] for r in rows if not r["rendered"]],
                "redirected": [{"route": r["route"],
                                "to": r["canonicalHash"]}
                               for r in rows if r["redirected"]],
                "aliasMismatch": [a for a in alias_rows
                                  if a["actualHash"] != a["declaredTarget"]],
            }}
    with io.open(os.path.join(out_dir, "w13-routes-inventory.json"), "w",
                 encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("[inventory] %s" % json.dumps(data["summary"], ensure_ascii=False))
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 6. РАЗВЁРТКА: маршруты × вьюпорты
# ═══════════════════════════════════════════════════════════════════════════
def _targets_fail(small, base):
    """Контролы < 44 px. `base` — метка для списка дефектов."""
    out = []
    for s in small:
        out.append("%s: тач-цель %s %sx%s «%s»"
                   % (base, s["el"], s["w"], s["h"], s["txt"]))
    return out


def run_sweep(browser, out_dir, inventory, limit=0):
    screens = inventory["screens"]
    # Адрес, который приложение само перенаправляет (неприменимая вкладка,
    # библиотечная дверь модуля без промптов), — не отдельный экран: он не
    # разворачивается, поэтому в матрицу не входит (учтён в инвентаре).
    routes = [s["route"] for s in screens if not s["redirected"]]
    if limit:
        routes = routes[:limit]
    cells, fails = [], []
    viewports = []
    for (w, h) in VIEWPORTS:
        viewports.append("%dx%d" % (w, h))
    sweep = {"viewports": viewports, "routes": routes, "cells": [],
             "failures": [], "console": {}}
    for (w, h) in VIEWPORTS:
        vp = "%dx%d" % (w, h)
        ctx = open_ctx(browser, w, h)
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m, e=errors: e.append(m.text[:180])
                if m.type == "error" else None)
        page.on("pageerror", lambda exc, e=errors: e.append(
            "pageerror: " + str(exc)[:200]))
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(900)
        coarse = page.evaluate("() => matchMedia('(pointer: coarse)').matches")
        shot_here = (w, h) in SHOT_VIEWPORTS
        for route in routes:
            before = len(errors)
            page.evaluate("(r) => { window.location.hash = r; }", route)
            page.wait_for_timeout(CELL_SETTLE_MS)
            d = page.evaluate(ROUTE_PROBE)
            d.update({"viewport": vp, "route": route, "coarse": coarse,
                      "consoleErrors": errors[before:][:6]})
            cells.append(d)
            base = "%s %s" % (vp, route)
            if d["hScroll"]:
                fails.append("%s: горизонтальный скролл %s > %s"
                             % (base, d["sw"], d["vw"]))
            # Вертикальный скролл ДОКУМЕНТА на desktop/tablet — штатное
            # поведение (`html { scroll-padding-top }`, прокрутка страницы);
            # дефект — только когда mobile-shell растягивает страницу вместо
            # внутренней прокрутки `main`.
            if d["vScroll"] and d["shellMode"] == "mobile":
                fails.append("%s: mobile-shell растянул документ %s > %s"
                             % (base, d["docH"], d["vh"]))
            if d["offCount"]:
                fails.append("%s: за вьюпортом %d (%s)"
                             % (base, d["offCount"], d["offscreen"][:2]))
            if d["clippedCount"]:
                fails.append("%s: обрезанный текст %d (%s)"
                             % (base, d["clippedCount"], d["clipped"][:2]))
            if not d["mainTextLen"] or d["mainTextLen"] < 40:
                fails.append("%s: экран пуст (%d символов)"
                             % (base, d["mainTextLen"]))
            # Тач-цели НЕ валят матрицу раскладки: здесь считается rect, а
            # контракт 44×44 — про ОБЛАСТЬ НАЖАТИЯ (у плотных примитивов она
            # расширена невидимой зоной, у чекбокса цель — <label>). Живой
            # hit-тест — секция `touch` этого же инструмента; здесь число
            # публикуется как `smallCount`/`tapSmall` без приговора.
            if d["consoleErrors"]:
                fails.append("%s: консоль %s" % (base, d["consoleErrors"][:2]))
            if shot_here:
                _shot(page, out_dir, "w13-%s-%s.jpg"
                      % ("m" if w == 390 else "w", _slug(route)))
        sweep["console"][vp] = {"coarse": coarse,
                                "errors": sorted(set(errors))[:20]}
        ctx.close()
    sweep["cells"] = cells
    sweep["failures"] = fails
    sweep["summary"] = {
        "routes": len(routes), "viewports": len(VIEWPORTS),
        "cells": len(cells),
        "hScroll": sum(1 for c in cells if c["hScroll"]),
        "vScroll": sum(1 for c in cells if c["vScroll"]),
        "offscreen": sum(1 for c in cells if c["offCount"]),
        "clipped": sum(1 for c in cells if c["clippedCount"]),
        "tapSmall": sum(1 for c in cells if c["smallCount"]),
        "consoleErrors": sum(1 for c in cells if c["consoleErrors"]),
        "empty": sum(1 for c in cells if c["mainTextLen"] < 40),
        "failures": len(fails),
    }
    with io.open(os.path.join(out_dir, "w13-sweep.json"), "w",
                 encoding="utf-8") as f:
        json.dump(sweep, f, ensure_ascii=False, indent=1)
    print("[sweep] %s" % json.dumps(sweep["summary"], ensure_ascii=False))
    return sweep


# ═══════════════════════════════════════════════════════════════════════════
# 7. СОСТОЯНИЯ
# ═══════════════════════════════════════════════════════════════════════════
STATE_HEALTH_PROBE = r"""
() => {
  const out = [];
  document.querySelectorAll('[data-health-state]').forEach((el) => {
    out.push({subsystem: el.getAttribute('data-health-subsystem'),
              state: el.getAttribute('data-health-state'),
              indicator: el.getAttribute('data-health-indicator'),
              reason: (el.querySelector('.health-why, .health-reason, '
                + '.health-status-line') || {}).textContent || ''});
  });
  const inline = [];
  document.querySelectorAll('[data-health-indicator]').forEach((el) => {
    inline.push({inline: el.getAttribute('data-health-inline') || '',
                 indicator: el.getAttribute('data-health-indicator'),
                 txt: (el.textContent || '').trim().slice(0, 60)});
  });
  return {cards: out, inline: inline.slice(0, 12)};
}
"""

PROGRESS_PROBE = r"""
() => {
  const out = [];
  document.querySelectorAll('[role="progressbar"], .ctl-progress, .prog, '
    + '[data-progress]').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none') return;
    const fill = el.querySelector('.ctl-progress__fill, .prog__fill, i, span');
    const r = el.getBoundingClientRect();
    out.push({cls: (el.className || '').toString().slice(0, 60),
              now: el.getAttribute('aria-valuenow'),
              text: (el.textContent || '').trim().slice(0, 50),
              width: Math.round(r.width),
              fillW: fill ? Math.round(fill.getBoundingClientRect().width) : null,
              state: el.getAttribute('data-state') || ''});
  });
  return out.slice(0, 10);
}
"""

PALETTE_PROBE = r"""
() => {
  const root = document.querySelector('[data-command-palette]');
  if (!root) return {open: false};
  const rows = Array.from(root.querySelectorAll('[data-palette-item]'));
  const empty = root.querySelector('[data-palette-empty]');
  const input = root.querySelector('[data-palette-input]');
  const r = root.getBoundingClientRect();
  return {
    open: true, rows: rows.length,
    empty: empty ? (empty.textContent || '').trim().slice(0, 60) : '',
    count: (root.querySelector('[data-palette-count]') || {}).textContent || '',
    inputFocused: document.activeElement === input,
    zIndex: getComputedStyle(root).zIndex,
    inBody: root.parentElement === document.body,
    rect: {w: Math.round(r.width), h: Math.round(r.height)},
  };
}
"""

DRAWER_PROBE = r"""
() => {
  const d = document.querySelector('aside.app-drawer');
  if (!d) return {present: false, open: false};
  const cs = getComputedStyle(d);
  const r = d.getBoundingClientRect();
  const backdrop = document.querySelector('.drawer-backdrop');
  return {present: true,
          open: d.classList.contains('open'),
          ariaHidden: d.getAttribute('aria-hidden'),
          inert: d.hasAttribute('inert'),
          display: cs.display, zIndex: cs.zIndex,
          inBody: d.parentElement === document.body,
          rect: {x: Math.round(r.x), w: Math.round(r.width)},
          backdropZ: backdrop ? getComputedStyle(backdrop).zIndex : null,
          focusInside: d.contains(document.activeElement),
          active: (document.activeElement && (document.activeElement.tagName
            + '.' + (document.activeElement.className || '').toString()
              .split(/\s+/).slice(0, 2).join('.'))) || ''};
}
"""

SHEET_PROBE = r"""
() => {
  const m = document.querySelector('[data-sfeed-modal]');
  if (!m) return {open: false};
  const cs = getComputedStyle(m);
  const r = m.getBoundingClientRect();
  const rootEl = m.closest('.modal-backdrop') || m;
  return {open: cs.display !== 'none' && r.width > 1, zIndex: cs.zIndex,
          parentIsBody: rootEl.parentElement === document.body,
          insideMain: !!m.closest('main'),
          rect: {x: Math.round(r.x), y: Math.round(r.y),
                 w: Math.round(r.width), h: Math.round(r.height)},
          focusInside: m.contains(document.activeElement),
          bottomAnchored: (window.innerHeight - r.bottom) < 40,
          sheetMode: document.documentElement.classList.contains(
            'w9-sheet-bottom')};
}
"""

FOCUS_PROBE = r"""
() => {
  const el = document.activeElement;
  if (!el) return null;
  const inOverlay = !!(el.closest('[data-command-palette], aside.app-drawer, '
    + '[data-sfeed-modal], .prompt-editor--full, .more-menu-host, .more-menu'));
  return {tag: el.tagName,
          cls: (el.className || '').toString().split(/\s+/).slice(0, 3).join('.'),
          id: el.id || '',
          attr: el.getAttribute && (el.getAttribute('data-focus-id')
            || el.getAttribute('data-palette-item') || ''),
          inOverlay: inOverlay,
          label: (el.textContent || el.value || '').trim().slice(0, 40)};
}
"""

ZINDEX_PROBE = r"""
() => {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return {sel: sel, z: cs.zIndex, position: cs.position,
            // true только для НАСТОЯЩЕГО портала: прямой ребёнок <body>.
            parentIsBody: el.parentElement === document.body,
            // null — оверлей не внутри прокручиваемого контента.
            insideMain: !!el.closest('main'),
            visible: cs.display !== 'none' && cs.visibility !== 'hidden'};
  };
  const root = getComputedStyle(document.documentElement);
  const vars = {};
  ['--z-base', '--z-content', '--z-inline', '--z-sidebar', '--z-header',
   '--z-scrim', '--z-nav', '--z-local', '--z-menu', '--z-modal-scrim',
   '--z-modal', '--z-palette', '--z-toast'].forEach((v) => {
    vars[v] = root.getPropertyValue(v).trim();
  });
  return {vars: vars,
          stickyHeader: pick('header.header-sticky'),
          drawer: pick('aside.app-drawer'),
          drawerScrim: pick('.drawer-backdrop'),
          moreMenu: pick('.more-menu'),
          palette: pick('[data-command-palette]'),
          sheetModal: pick('.sfeed-modal-backdrop, .modal-backdrop'),
          fullscreen: pick('.prompt-editor--full, .status-graph-full'),
          toast: pick('.toast, [role="status"].toast')};
}
"""


# ── EVOL-033 (W13, P1): тач-цели живым hit-тестом ───────────────────────────
# Геометрия элемента не доказывает размер ОБЛАСТИ НАЖАТИЯ: у плотных
# примитивов она расширена невидимой `::after`-зоной, а у чекбокса внутри
# `<label>` реальная цель — сам label. Поэтому ниже идёт `elementFromPoint`
# по четырём направлениям от центра: возвращает фактическую ширину/высоту
# нажатия, а не rect. Кандидат — только то, что МЕНЬШЕ 44 px по rect (иначе
# мерить нечего); чекбоксы/радио заменяются на ближайший `<label>`.
HIT_PROBE = r"""
async () => {
  const CTRL = 'button, [role="button"], input:not([type="hidden"]), '
    + 'select, textarea, summary, [tabindex]:not([tabindex="-1"])';
  const exempt = ['.viz-heat__cell', '.sr-only'];
  const label = (el) => el.tagName.toLowerCase() + '.'
    + (el.className || '').toString().split(/\s+/).filter(Boolean)
        .slice(0, 2).join('.');
  const cand = [];
  document.querySelectorAll(CTRL).forEach((el) => {
    if (el.closest('[aria-hidden="true"]')) return;
    if (exempt.some((s) => el.matches(s) || el.closest(s))) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden'
        || parseFloat(cs.opacity) === 0) return;
    let target = el;
    if ((el.type === 'checkbox' || el.type === 'radio') && el.closest('label')) {
      target = el.closest('label');
    }
    const r = target.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.width >= 44 && r.height >= 44) return;   // уже соответствует
    cand.push(target);
  });
  const out = [];
  for (const el of cand) {
    try { el.scrollIntoView({block: 'center', inline: 'nearest'}); } catch (e) {}
    await new Promise((res) => requestAnimationFrame(() => res()));
    await new Promise((res) => setTimeout(res, 60));
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cx = Math.min(Math.max(r.left + r.width / 2, 1), window.innerWidth - 1);
    const cy = Math.min(Math.max(r.top + r.height / 2, 1), window.innerHeight - 1);
    const hit = (x, y) => {
      if (x < 0 || y < 0 || x > window.innerWidth - 1
          || y > window.innerHeight - 1) return false;
      const t = document.elementFromPoint(x, y);
      return !!(t && (t === el || el.contains(t) || t.contains(el)));
    };
    let up = 0, dn = 0, lf = 0, rt = 0;
    // Элемент может быть ПЕРЕКРЫТ открытым оверлеем (например, роут
    // `#/access/<id>` сразу открывает окно поверх шапки). Такой узел сейчас не
    // является целью нажатия — это не «маленькая цель», а окклюзия: считаем
    // отдельно и в метрику 44×44 не включаем.
    if (!hit(cx, cy)) {
      out.push({el: label(el), w: Math.round(r.width), h: Math.round(r.height),
                hitW: 0, hitH: 0, occluded: true,
                txt: (el.textContent || el.value || '').trim()
                      .replace(/\s+/g, ' ').slice(0, 26)});
      continue;
    }
    while (up < 30 && hit(cx, cy - up - 2)) up += 2;
    while (dn < 30 && hit(cx, cy + dn + 2)) dn += 2;
    while (lf < 40 && hit(cx - lf - 2, cy)) lf += 2;
    while (rt < 40 && hit(cx + rt + 2, cy)) rt += 2;
    out.push({el: label(el), w: Math.round(r.width), h: Math.round(r.height),
              hitW: Math.round(lf + rt + 2), hitH: Math.round(up + dn + 2),
              txt: (el.textContent || el.value || '').trim().replace(/\s+/g, ' ')
                    .slice(0, 26)});
  }
  return out;
}
"""

# Кадры двух дефектов + счётчик повторяющегося текста (проверка дублей).
DUP_PROBE = r"""
() => {
  const zone = document.querySelector('[data-health-subsystem="heartbeat"]')
    || document.querySelector('.status-block');
  const text = zone ? (zone.innerText || '') : '';
  const line = document.querySelector('[data-health-inline="heartbeat"]');
  const reasonEl = line ? line.querySelector('.health-status-line__reason') : null;
  const reason = reasonEl ? reasonEl.textContent.trim() : '';
  let count = 0;
  if (reason) {
    let idx = text.indexOf(reason);
    while (idx >= 0) { count += 1; idx = text.indexOf(reason, idx + reason.length); }
  }
  return {reason: reason, reasonCount: count,
          headings: Array.from(document.querySelectorAll(
            '[role="dialog"] h2, [role="dialog"] .text-sm.font-bold'))
            .map((h) => (h.textContent || '').trim())
            .filter((t) => t === 'Матрица ролей' || t === 'Роли и права'),
          dialogTitle: (() => {
            const d = document.querySelector('[role="dialog"]');
            const h = d ? d.querySelector('h2') : null;
            return h ? h.textContent.trim() : '';
          })()};
}
"""


def _drive_status(browser, out_dir, records):
    """5 состояний health-карточек на `#/`."""
    variants = {
        "normal": {},
        "degraded": {"experience.state": "degraded",
                     "experience.reason": "часть уроков не применилась"},
        "failed": {"bot.state": "polling_error",
                   "experience.state": "failed",
                   "experience.reason": "pipeline упал"},
        "unknown": {"bot.state": "starting", "bot.errors_total": None,
                    "uptime.generated_at": _DELETE},
        "disabled": {"bot.state": "stopped"},
    }
    for state, over in variants.items():
        status = _deep(STATUS_BASE, over)
        if over.get("bot.errors_total", 0) is None:
            status["bot"].pop("errors_total", None)
        api = _api_handler({"/api/status": status})
        for (w, h) in ((390, 844), (1280, 900)):
            ctx = open_ctx(browser, w, h, api=api)
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                      wait_until="load")
            page.wait_for_selector(".app-shell", timeout=20000)
            page.wait_for_timeout(1200)
            probe = page.evaluate(STATE_HEALTH_PROBE)
            name = "w13-state-status-%s-%d.jpg" % (state, w)
            _shot(page, out_dir, name)
            records.append({"surface": "status", "state": state,
                            "viewport": w, "shot": name,
                            "cards": probe["cards"],
                            "inline": probe["inline"],
                            "observedStates": sorted({c["state"] for c in
                                                      probe["cards"]})})
            ctx.close()


def _drive_progress(browser, out_dir, records):
    variants = {
        "normal": {},
        "unknown": {"server.memory": {"used": None, "total": None,
                                      "percent": None}},
        "partial": {"server.memory": {"used": 512000000, "total": 2048000000,
                                      "percent": None}},
        "completed": {"server.disk": {"used": 100, "total": 100,
                                      "percent": 100}},
    }
    for state, over in variants.items():
        status = _deep(STATUS_BASE, over)
        status["server"]["cpu_percent"] = 42.0
        status["server"]["disk"] = over.get("server.disk",
                                           status["server"]["disk"])
        api = _api_handler({"/api/status": status})
        for (w, h) in ((390, 844), (1280, 900)):
            ctx = open_ctx(browser, w, h, api=api)
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                      wait_until="load")
            page.wait_for_selector(".app-shell", timeout=20000)
            page.wait_for_timeout(1100)
            bars = page.evaluate(PROGRESS_PROBE)
            name = "w13-state-progress-%s-%d.jpg" % (state, w)
            _shot(page, out_dir, name)
            records.append({"surface": "progress", "state": state,
                            "viewport": w, "shot": name, "bars": bars})
            ctx.close()


def _drive_modules(browser, out_dir, records):
    """Каталог модулей: включено / выключено / частично / нет права правки."""
    flags_off = copy.deepcopy(M.CONFIG_STUB)
    for it in flags_off.get("items", []):
        if it.get("key", "").startswith("flags.") and it.get("type") == "bool":
            it["value"] = False
    flags_on = copy.deepcopy(M.CONFIG_STUB)
    for it in flags_on.get("items", []):
        if it.get("key", "").startswith("flags.") and it.get("type") == "bool":
            it["value"] = True
    # Ме без права правки: тот же каталог, но тумблеры обязаны быть
    # заблокированы (RBAC-состояние `disabled`, а не «просто выключено»).
    me_readonly = copy.deepcopy(M.ME_JSON)
    me_readonly["is_global_admin"] = False
    me_readonly["role_name"] = "user"
    me_readonly["permissions"] = {"actions": []}
    variants = {
        "normal": (M.CONFIG_STUB, None),
        "disabled": (flags_off, None),
        "partial": (flags_on, None),
        "readonly": (M.CONFIG_STUB, me_readonly),
    }
    for state, (cfg, me) in variants.items():
        over = {"/api/config": cfg}
        if me is not None:
            over["/api/me"] = me
        api = _api_handler(over)
        for (w, h) in ((390, 844), (1280, 900)):
            ctx = open_ctx(browser, w, h, api=api)
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                      wait_until="load")
            page.wait_for_selector(".app-shell", timeout=20000)
            page.wait_for_timeout(1200)
            toggles = page.evaluate(r"""
            () => {
              // Состояние тумблера — `input[type=checkbox]` внутри
              // `.ctl-toggle` (видимый трек — декорация). «disabled» =
              // либо галочка снята без права правки, либо нет права.
              const rows = [];
              document.querySelectorAll('.ctl-toggle').forEach((el) => {
                const cs = getComputedStyle(el);
                if (cs.display === 'none') return;
                const inp = el.querySelector('input[type="checkbox"]');
                if (!inp) return;
                const card = el.closest('[data-module-card], .module-card,'
                  + ' .card, li');
                rows.push({name: (card ? (card.textContent || '') : '')
                             .trim().replace(/\s+/g, ' ').slice(0, 26),
                           checked: inp.checked === true,
                           disabled: inp.disabled === true});
              });
              return {total: rows.length,
                      on: rows.filter((r) => r.checked).length,
                      off: rows.filter((r) => !r.checked).length,
                      locked: rows.filter((r) => r.disabled).length,
                      sample: rows.slice(0, 4)};
            }""")
            name = "w13-state-modules-%s-%d.jpg" % (state, w)
            _shot(page, out_dir, name)
            records.append({"surface": "modules-catalog", "state": state,
                            "viewport": w, "shot": name, "toggles": toggles})
            ctx.close()


def _drive_palette(browser, out_dir, records):
    variants = {"normal": ("", ), "partial": ("prompt", ),
                "empty": ("zzzzqqqq", )}
    for state, (query,) in variants.items():
        for (w, h) in ((390, 844), (1280, 900)):
            ctx = open_ctx(browser, w, h)
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                      wait_until="load")
            page.wait_for_selector(".app-shell", timeout=20000)
            page.wait_for_timeout(900)
            page.evaluate(r"""() => {
              window.__adminbotVm.openPalette();
            }""")
            page.wait_for_timeout(300)
            if query:
                page.fill("[data-palette-input]", query)
                page.wait_for_timeout(350)
            probe = page.evaluate(PALETTE_PROBE)
            name = "w13-state-palette-%s-%d.jpg" % (state, w)
            _shot(page, out_dir, name)
            records.append({"surface": "palette", "state": state,
                            "query": query, "viewport": w, "shot": name,
                            "probe": probe})
            ctx.close()


def _drive_sheet(browser, out_dir, records):
    """Лист записи: normal / empty (лент нет — каталог пуст) / error (500)."""
    variants = {
        "normal": {"/api/oversight/dossier_feed": W10._DOSSIER},
        "empty": {"/api/oversight/dossier_feed": {"chat_id": None,
                                                  "items": []}},
        "error": {},
    }
    fails = {"error": {"/api/oversight/dossier_feed": 500}}
    for state, over in variants.items():
        api = _api_handler(over, fail=fails.get(state))
        for (w, h) in ((390, 844), (1280, 900)):
            ctx = open_ctx(browser, w, h, api=api)
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/web/index.html#/memory" % PORT,
                      wait_until="load")
            page.wait_for_selector(".app-shell", timeout=20000)
            page.wait_for_timeout(1400)
            catalog = page.evaluate(r"""
            () => {
              const c = document.querySelector('[data-memory-catalog]')
                || document.querySelector('main.scroll-area');
              const items = document.querySelectorAll('[data-memory-item]');
              const empty = document.querySelector('[data-memory-empty]');
              return {items: items.length,
                      empty: empty ? (empty.textContent || '').trim() : '',
                      text: c ? (c.innerText || '').replace(/\s+/g, ' ')
                             .trim().slice(0, 160) : ''};
            }""")
            card = page.query_selector('[data-memory-item="facts"]') or \
                page.query_selector("[data-memory-item]")
            if card:
                card.click()
                page.wait_for_timeout(500)
            probe = page.evaluate(SHEET_PROBE)
            name = "w13-state-sheet-%s-%d.jpg" % (state, w)
            _shot(page, out_dir, name)
            records.append({"surface": "record-sheet", "state": state,
                            "viewport": w, "shot": name,
                            "cardFound": bool(card), "catalog": catalog,
                            "probe": probe})
            ctx.close()


def _drive_loading(browser, out_dir, records):
    """Загрузка: медленный `/api/config` — каркас жив, состояние видно."""
    api = _api_handler({}, delay_ms=1800)
    for (w, h) in ((390, 844), (1280, 900)):
        ctx = open_ctx(browser, w, h, api=api)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
                  wait_until="commit")
        page.wait_for_timeout(700)
        probe = page.evaluate(r"""
        () => {
          const shell = document.querySelector('.app-shell');
          const main = document.querySelector('main.scroll-area');
          return {shell: !!shell, shellH: shell ? Math.round(
                    shell.getBoundingClientRect().height) : null,
                  mainText: main ? main.innerText.replace(/\s+/g, ' ')
                    .trim().slice(0, 120) : '',
                  skeletons: document.querySelectorAll(
                    '.skeleton, [aria-busy="true"], .loading').length};
        }""")
        name = "w13-state-loading-%d.jpg" % w
        _shot(page, out_dir, name)
        records.append({"surface": "shell-loading", "state": "loading",
                        "viewport": w, "shot": name, "probe": probe})
        ctx.close()


def run_states(browser, out_dir):
    records = []
    _drive_status(browser, out_dir, records)
    _drive_progress(browser, out_dir, records)
    _drive_modules(browser, out_dir, records)
    _drive_palette(browser, out_dir, records)
    _drive_sheet(browser, out_dir, records)
    _drive_loading(browser, out_dir, records)
    data = {"records": records,
            "summary": {
                "records": len(records),
                "surfaces": sorted({r["surface"] for r in records}),
                "states": sorted({r["state"] for r in records}),
                "statusObserved": sorted({
                    s for r in records if r["surface"] == "status"
                    for s in r["observedStates"]}),
            }}
    with io.open(os.path.join(out_dir, "w13-states.json"), "w",
                 encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("[states] %s" % json.dumps(data["summary"], ensure_ascii=False))
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 8. ПОРТАЛЫ / ФОКУС
# ═══════════════════════════════════════════════════════════════════════════
def run_portal(browser, out_dir):
    res = {"checks": {}, "layers": {}, "focus": []}

    def note(key, value):
        res["checks"][key] = value
        print("[portal] %-42s %s" % (key, json.dumps(value,
                                                    ensure_ascii=False)[:160]))

    # ── 8.1 лестница слоёв и портал в <body> ───────────────────────────────
    ctx = open_ctx(browser, 1280, 900, touch=False)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
              wait_until="load")
    page.wait_for_selector(".app-shell", timeout=20000)
    page.wait_for_timeout(900)

    page.evaluate("() => window.__adminbotVm.openPalette()")
    page.wait_for_timeout(300)
    layers = {"palette": page.evaluate(ZINDEX_PROBE)}
    _shot(page, out_dir, "w13-portal-palette-1280.jpg")
    focus_open = page.evaluate(FOCUS_PROBE)
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)

    # Настоящий пользовательский вход: кнопка «Поиск» в шапке. Проверяем и
    # ловушку, и возврат фокуса ИМЕННО на триггер (контракт, а не «куда-то»).
    trig = page.query_selector("[data-palette-open]")
    if trig:
        trig.click()
        page.wait_for_timeout(320)
    # ловушка: Tab не выводит фокус из палитры
    inside, steps = [], []
    for _ in range(8):
        page.keyboard.press("Tab")
        page.wait_for_timeout(60)
        f = page.evaluate(FOCUS_PROBE)
        steps.append(f)
        inside.append(bool(f and f["inOverlay"]))
    note("palette.focusTrap", {"steps": inside, "allInside": all(inside),
                               "openedFromTrigger": bool(trig),
                               "openFocus": focus_open,
                               "focusPath": [[(s or {}).get("tag", "?"),
                                              (s or {}).get("cls", ""),
                                              (s or {}).get("label", "")[:20]]
                                             for s in steps]})
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    after = page.evaluate(r"""() => {
      const el = document.activeElement;
      const has = (a) => !!(el && el.hasAttribute && el.hasAttribute(a));
      return {
        open: !!document.querySelector('[data-command-palette]'),
        focus: el ? el.tagName : '',
        isPaletteTrigger: has('data-palette-open')
          || has('data-palette-open-drawer'),
        cls: el ? (el.className || '').toString().split(/\s+/)[0] : '',
        label: el ? (el.textContent || '').trim().slice(0, 24) : ''};
    }""")
    note("palette.escClose", after)
    res["focus"].append({"overlay": "palette", "openFocus": focus_open,
                         "trapSteps": inside, "afterEsc": after})

    # ── 8.1b та же ловушка при НЕПУСТОЙ выдаче (не дискриминирующий случай
    # «два узла»): 16 результатов + 8 Tab — фокус обязан остаться внутри.
    page.evaluate("() => window.__adminbotVm.openPalette()")
    page.wait_for_timeout(320)
    page.fill("[data-palette-input]", "prompt")
    page.wait_for_timeout(400)
    rows_n = page.evaluate(
        "() => document.querySelectorAll('[data-palette-item]').length")
    inside_rich = []
    for _ in range(10):
        page.keyboard.press("Tab")
        page.wait_for_timeout(60)
        f = page.evaluate(FOCUS_PROBE)
        inside_rich.append(bool(f and f["inOverlay"]))
    note("palette.focusTrapRich", {"rows": rows_n, "steps": inside_rich,
                                   "allInside": all(inside_rich)})
    res["focus"].append({"overlay": "palette-16-results",
                         "rows": rows_n, "trapSteps": inside_rich})
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)

    # ── 8.2 лист записи (mobile sheet + desktop modal) ─────────────────────
    for (w, h) in ((390, 844), (1280, 900)):
        c2 = open_ctx(browser, w, h,
                      api=_api_handler({"/api/oversight/dossier_feed":
                                        W10._DOSSIER}))
        p2 = c2.new_page()
        p2.goto("http://127.0.0.1:%d/web/index.html#/memory" % PORT,
                wait_until="load")
        p2.wait_for_selector(".app-shell", timeout=20000)
        p2.wait_for_timeout(1000)
        card = p2.query_selector('[data-memory-item="facts"]') or \
            p2.query_selector("[data-memory-item]")
        before_focus = p2.evaluate(FOCUS_PROBE)
        if card:
            card.click()
            p2.wait_for_timeout(450)
        sheet = p2.evaluate(SHEET_PROBE)
        z = p2.evaluate(ZINDEX_PROBE)
        layers["sheet-%d" % w] = z
        _shot(p2, out_dir, "w13-portal-sheet-%d.jpg" % w)
        inside_sheet = []
        for _ in range(6):
            p2.keyboard.press("Tab")
            p2.wait_for_timeout(50)
            f = p2.evaluate(FOCUS_PROBE)
            inside_sheet.append(bool(f and f["inOverlay"]))
        p2.keyboard.press("Escape")
        p2.wait_for_timeout(350)
        closed = p2.evaluate(r"""() => ({
          open: !!document.querySelector('[data-sfeed-modal]'),
          lock: !!document.querySelector('.app-shell.sfeed-modal-open'),
          focusTag: (document.activeElement || {}).tagName || '',
          focusInSheet: !!((document.activeElement || {}).closest
            && document.activeElement.closest('[data-sfeed-modal]'))})""")
        note("sheet.%d" % w, {"sheet": sheet, "trap": inside_sheet,
                              "before": before_focus, "afterEsc": closed})
        res["focus"].append({"overlay": "record-sheet@%d" % w, "sheet": sheet,
                             "trapSteps": inside_sheet, "afterEsc": closed})
        c2.close()

    # ── 8.3 drawer (mobile) + возврат фокуса ───────────────────────────────
    ctxm = open_ctx(browser, 390, 844)
    pm = ctxm.new_page()
    pm.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
            wait_until="load")
    pm.wait_for_selector(".app-shell", timeout=20000)
    pm.wait_for_timeout(900)
    trig = pm.query_selector("[data-drawer-trigger]")
    if trig:
        trig.click()
        pm.wait_for_timeout(400)
    drawer = pm.evaluate(DRAWER_PROBE)
    layers["drawer-390"] = pm.evaluate(ZINDEX_PROBE)
    _shot(pm, out_dir, "w13-portal-drawer-390.jpg")
    in_drawer = []
    for _ in range(6):
        pm.keyboard.press("Tab")
        pm.wait_for_timeout(50)
        f = pm.evaluate(FOCUS_PROBE)
        in_drawer.append(bool(f and f["inOverlay"]))
    pm.keyboard.press("Escape")
    pm.wait_for_timeout(350)
    back = pm.evaluate(r"""() => ({
      drawer: !!document.querySelector('.app-drawer') &&
        getComputedStyle(document.querySelector('.app-drawer')).display !== 'none',
      focusOnTrigger: !!document.activeElement
        && (document.activeElement.getAttribute
              ? document.activeElement.getAttribute('data-drawer-trigger') !== null
              : false)})""")
    note("drawer.390", {"open": drawer, "trap": in_drawer, "afterEsc": back})
    res["focus"].append({"overlay": "drawer@390", "open": drawer,
                         "trapSteps": in_drawer, "afterEsc": back})
    ctxm.close()

    # ── 8.4 fullscreen промпта: портал, z, Esc ─────────────────────────────
    ctxf = open_ctx(browser, 1280, 900, touch=False)
    pf = ctxf.new_page()
    pf.goto("http://127.0.0.1:%d/web/index.html#/ai/prompts" % PORT,
            wait_until="load")
    pf.wait_for_selector(".app-shell", timeout=20000)
    pf.wait_for_timeout(1200)
    # Полноэкранный редактор живёт внутри конкретного промпта (W12): открываем
    # первый реальный prompt-item первого модуля, у которого они есть.
    tgt = pf.evaluate(r"""
        () => {
          const vm = window.__adminbotVm;
          const m = (vm.modules || []).find(
            (x) => vm.workspacePromptItems(x).length > 0);
          if (!m) return null;
          const it = vm.workspacePromptItems(m)[0];
          const slug = vm.routeSlugOf(m);
          vm.navigateTo('#/ai/prompts/' + slug + '/' + it.key);
          return {slug: slug, key: it.key};
        }
    """)
    pf.wait_for_timeout(1200)
    has_btn = pf.evaluate("() => !!document.querySelector('[data-prompt-fullscreen]')")
    if has_btn:
        pf.click("[data-prompt-fullscreen]")
        pf.wait_for_timeout(500)
    fs = pf.evaluate(r"""() => {
      const root = document.querySelector('.prompt-editor--full');
      if (!root) return {open: false};
      const cs = getComputedStyle(root);
      const r = root.getBoundingClientRect();
      return {open: cs.display !== 'none', z: cs.zIndex,
              parentIsBody: root.parentElement === document.body,
              insideMain: !!root.closest('main'),
              position: cs.position,
              rect: {x: Math.round(r.x), y: Math.round(r.y),
                     w: Math.round(r.width), h: Math.round(r.height)},
              fillsViewport: Math.abs(r.x) < 2 && Math.abs(r.y) < 2
                && Math.abs(r.width - window.innerWidth) < 2
                && Math.abs(r.height - window.innerHeight) < 2,
              cls: (root.className || '').toString().slice(0, 60),
              focusInside: root.contains(document.activeElement)};
    }""")
    _shot(pf, out_dir, "w13-portal-fullscreen-1280.jpg")
    layers["fullscreen-1280"] = pf.evaluate(ZINDEX_PROBE)
    pf.keyboard.press("Escape")
    pf.wait_for_timeout(400)
    fs_after = pf.evaluate(r"""() => ({
      stillOpen: !!document.querySelector('.prompt-editor--full'),
      focusTag: (document.activeElement || {}).tagName || ''})""")
    note("fullscreen.1280", {"button": has_btn, "open": fs, "afterEsc": fs_after})
    res["focus"].append({"overlay": "fullscreen@1280", "open": fs,
                         "afterEsc": fs_after})
    ctxf.close()

    # ── 8.5 стек слоёв: два оверлея, Esc закрывает РОВНО верхний ───────────
    ctxs = open_ctx(browser, 390, 844)
    ps = ctxs.new_page()
    ps.goto("http://127.0.0.1:%d/web/index.html#/modules" % PORT,
            wait_until="load")
    ps.wait_for_selector(".app-shell", timeout=20000)
    ps.wait_for_timeout(900)
    ps.evaluate("() => window.__adminbotVm.toggleDrawer()")
    ps.wait_for_timeout(300)
    ps.evaluate("() => window.__adminbotVm.openPalette()")
    ps.wait_for_timeout(400)
    stack_open = ps.evaluate(r"""() => ({
      palette: !!document.querySelector('[data-command-palette]'),
      drawer: (function () {
        const d = document.querySelector('.app-drawer');
        return !!d && getComputedStyle(d).display !== 'none';
      })(),
      backStack: (window.__adminbotVm.__backStackLen
        ? window.__adminbotVm.__backStackLen() : null)})""")
    _shot(ps, out_dir, "w13-portal-stack-390.jpg")
    ps.keyboard.press("Escape")
    ps.wait_for_timeout(350)
    stack_after = ps.evaluate(r"""() => ({
      palette: !!document.querySelector('[data-command-palette]'),
      drawer: (function () {
        const d = document.querySelector('.app-drawer');
        return !!d && getComputedStyle(d).display !== 'none';
      })()})""")
    note("stack.palette-over-drawer.390", {"open": stack_open,
                                           "afterEsc": stack_after})
    res["focus"].append({"overlay": "stack@390", "open": stack_open,
                         "afterEsc": stack_after})
    ctxs.close()

    # ── 8.6 та же лестница на широком экране ───────────────────────────────
    note("z.vars", layers["palette"]["vars"])
    note("z.palette", layers["palette"]["palette"])
    note("z.sheet", layers["sheet-1280"].get("sheetModal"))
    note("z.fullscreen", layers.get("fullscreen-1280", {}).get("fullscreen"))
    note("z.drawer", layers["drawer-390"].get("drawer"))
    note("z.header", layers["palette"]["stickyHeader"])
    res["layers"] = layers
    ctx.close()

    with io.open(os.path.join(out_dir, "w13-portal-focus.json"), "w",
                 encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("[portal] saved")
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 8.5. ТАЧ-ЦЕЛИ (P1 L00478 §A): живой hit-тест по классам контролов
# ═══════════════════════════════════════════════════════════════════════════
# Три coarse-полосы: 320 (узкий телефон), 390 (телефон), 768 (планшет,
# compact-shell). Правило 44×44 привязано к `(pointer: coarse)`, а не к
# ширине, поэтому эти три вьюпорта покрывают обе полосы; десктоп (fine
# pointer) по контракту сохраняет плотность 32–40 px и в счётчик не входит.
TOUCH_VIEWPORTS = ((320, 568), (390, 844), (768, 1024))


def run_touch(browser, out_dir, inventory, limit=0):
    routes = [s["route"] for s in inventory["screens"] if not s["redirected"]]
    if limit:
        routes = routes[:limit]
    cells, fails = [], []
    by_class = {}
    for (w, h) in TOUCH_VIEWPORTS:
        vp = "%dx%d" % (w, h)
        ctx = open_ctx(browser, w, h)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(900)
        for route in routes:
            page.evaluate("(r) => { window.location.hash = r; }", route)
            page.wait_for_timeout(CELL_SETTLE_MS)
            rows = page.evaluate(HIT_PROBE)
            measured = [r for r in rows if not r.get("occluded")]
            occluded = [r for r in rows if r.get("occluded")]
            bad = [r for r in measured if r["hitW"] < 44 or r["hitH"] < 44]
            cells.append({"viewport": vp, "route": route, "controls": rows,
                          "below44": bad,
                          "occluded": [{"el": r["el"], "txt": r["txt"]}
                                       for r in occluded]})
            for r in measured:
                agg = by_class.setdefault(r["el"], {
                    "minHitW": 999, "minHitH": 999, "samples": 0,
                    "below44": 0, "example": r["txt"]})
                agg["minHitW"] = min(agg["minHitW"], r["hitW"])
                agg["minHitH"] = min(agg["minHitH"], r["hitH"])
                agg["samples"] += 1
                if r["hitW"] < 44 or r["hitH"] < 44:
                    agg["below44"] += 1
            for r in bad:
                fails.append("%s %s: %s цель %s×%s (rect %s×%s) «%s»"
                             % (vp, route, r["el"], r["hitW"], r["hitH"],
                                r["w"], r["h"], r["txt"]))
        if (w, h) in SHOT_VIEWPORTS or (w, h) == (320, 568):
            _shot(page, out_dir, "w13-touch-%s-modules.jpg" % vp)
        ctx.close()
    data = {"viewports": [("%dx%d" % vp) for vp in TOUCH_VIEWPORTS],
            "routes": len(routes), "cells": cells, "byClass": by_class,
            "failures": fails,
            "summary": {
                "routes": len(routes),
                "viewports": len(TOUCH_VIEWPORTS),
                "cells": len(cells),
                "cellsBelow44": sum(1 for c in cells if c["below44"]),
                "controlsMeasured": sum(
                    1 for c in cells for r in c["controls"]
                    if not r.get("occluded")),
                "controlsBelow44": sum(len(c["below44"]) for c in cells),
                "occluded": sum(len(c["occluded"]) for c in cells),
                "classes": len(by_class),
                "classesBelow44": sorted(
                    k for k, v in by_class.items() if v["below44"]),
            }}
    with io.open(os.path.join(out_dir, "w13-touch-targets.json"), "w",
                 encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("[touch] %s" % json.dumps(data["summary"], ensure_ascii=False))
    for k, v in sorted(by_class.items()):
        print("   %-34s min %s×%s  below44=%d/%d  «%s»"
              % (k, v["minHitW"], v["minHitH"], v["below44"], v["samples"],
                 v["example"][:24]))
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 8.6. КАДРЫ ДВУХ ДЕФЕКТОВ (дубли текста) + состояние degraded в кадре
# ═══════════════════════════════════════════════════════════════════════════
def run_defects(browser, out_dir):
    res = {"checks": {}, "shots": []}

    def shot(page, name):
        _shot(page, out_dir, name)
        res["shots"].append(name)
        return name

    # 1. «Статус»: причина сердцебиения ровно один раз.
    for (w, h) in ((390, 844), (1280, 900)):
        ctx = open_ctx(browser, w, h)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1600)
        d = page.evaluate(DUP_PROBE)
        res["checks"]["heartbeat.%d" % w] = d
        page.evaluate(r"""() => {
          const el = document.querySelector(
            '[data-health-subsystem="heartbeat"]')
            || document.querySelector('.status-block');
          if (el) el.scrollIntoView({block: 'center'});
        }""")
        page.wait_for_timeout(400)
        shot(page, "w13-defect-heartbeat-%d.jpg" % w)
        ctx.close()

    # 2. `#/access/roles`: заголовок модалки один раз.
    for (w, h) in ((390, 844), (1440, 900)):
        ctx = open_ctx(browser, w, h)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/access/roles" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1400)
        clicked = page.evaluate(r"""() => {
          const vm = window.__adminbotVm;
          if (vm && typeof vm.openAccessWindow === 'function') {
            vm.openAccessWindow('roles');
            return true;
          }
          return false;
        }""")
        page.wait_for_timeout(700)
        d = page.evaluate(DUP_PROBE)
        d["openedViaVm"] = clicked
        res["checks"]["roles.%d" % w] = d
        shot(page, "w13-defect-roles-%d.jpg" % w)
        ctx.close()

    # 3. degraded-состояние: карточка experience В КАДРЕ (а не за срезом).
    status = _deep(STATUS_BASE, {"experience.state": "degraded",
                                 "experience.reason": "часть уроков не применилась"})
    for (w, h) in ((390, 844), (1280, 900)):
        ctx = open_ctx(browser, w, h,
                       api=_api_handler({"/api/status": status}))
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1600)
        d = page.evaluate(r"""() => {
          const el = document.querySelector(
            '[data-health-subsystem="experience"]');
          if (el) el.scrollIntoView({block: 'center'});
          const r = el ? el.getBoundingClientRect() : null;
          return {found: !!el, state: el ? el.getAttribute('data-health-state')
                    : null,
                  inViewport: r ? (r.top >= 0 && r.bottom <= window.innerHeight)
                    : false,
                  texts: Array.from(document.querySelectorAll(
                    '[data-health-state]')).map((c) => c.getAttribute(
                      'data-health-subsystem') + '=' + c.getAttribute(
                        'data-health-state'))};
        }""")
        page.wait_for_timeout(400)
        res["checks"]["degraded.%d" % w] = d
        shot(page, "w13-state-status-degraded-%d.jpg" % w)
        ctx.close()

    with io.open(os.path.join(out_dir, "w13-defects.json"), "w",
                 encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("[defects] %s" % json.dumps(res["checks"], ensure_ascii=False)[:700])
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 9. ОСОБЫЕ РЕЖИМЫ: ландшафт, zoom 200%, safe area, fullscreen, видео
# ═══════════════════════════════════════════════════════════════════════════
SPECIAL_ROUTES = ("#/", "#/modules", "#/memory", "#/ai", "#/access",
                  "#/oversight", "#/modules/factcheck", "#/modules/summary")


def run_extras(browser, out_dir):
    res = {"shots": [], "checks": {}}

    def snap(ctx, route, name, settle=1100):
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html%s" % (PORT, route),
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(settle)
        d = page.evaluate(ROUTE_PROBE)
        _shot(page, out_dir, name)
        page.close()
        res["shots"].append({"shot": name, "route": route, "probe": d})
        return d

    # 9.1 низкий ландшафт (667×375) — уже в sweep, здесь эталонный кадр
    ctx = open_ctx(browser, 667, 375)
    for r in ("#/", "#/modules"):
        snap(ctx, r, "w13-extra-landscape-%s.jpg" % _slug(r))
    ctx.close()

    # 9.2 zoom 200% — модель браузерного зума: CSS-вьюпорт вдвое уже при
    # удвоенной плотности пикселей (та же модель, что в W9). `style.zoom`
    # не подходит: он масштабирует уже свёрстанный layout и даёт ложные
    # «элементы за вьюпортом».
    for (w, h) in ((390, 844), (1280, 800)):
        ctx = browser.new_context(
            viewport={"width": w // 2, "height": h // 2},
            device_scale_factor=2, is_mobile=w <= 430,
            has_touch=w <= 430)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler())
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1000)
        d = page.evaluate(ROUTE_PROBE)
        name = "w13-extra-zoom200-%d.jpg" % w
        _shot(page, out_dir, name)
        res["shots"].append({"shot": name, "route": "#/", "zoom": 200,
                             "probe": d})
        res["checks"]["zoom200.%d" % w] = {
            "cssViewport": "%dx%d" % (w // 2, h // 2),
            "hScroll": d["hScroll"], "sw": d["sw"], "vw": d["vw"],
            "headerH": d["headerH"], "offCount": d["offCount"],
            "off": d["offscreen"][:3], "clipped": d["clipped"][:3],
            "tapSmall": d["smallCount"]}
        page.close()
        ctx.close()

    # 9.3 safe area: реальные инсеты SDK (top 44 / bottom 34)
    for safe in (44, 0):
        sdk = _sdk_js(safe_top=safe, safe_bottom=34 if safe else 0)
        ctx = open_ctx(browser, 390, 844, sdk_js=sdk)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1000)
        d = page.evaluate(r"""() => {
          const root = getComputedStyle(document.documentElement);
          const hdr = document.querySelector('header.header-sticky');
          const hb = hdr ? hdr.getBoundingClientRect() : null;
          const r = hdr ? getComputedStyle(hdr) : null;
          const main = document.querySelector('main.scroll-area');
          return {
            safeTopVar: root.getPropertyValue('--tg-safe-area-inset-top').trim(),
            safeBottomVar: root.getPropertyValue('--tg-safe-area-inset-bottom')
              .trim(),
            headerTop: hb ? Math.round(hb.top) : null,
            headerPadTop: r ? r.paddingTop : null,
            mainTop: main ? Math.round(main.getBoundingClientRect().top) : null,
          };
        }""")
        name = "w13-extra-safearea-%s.jpg" % ("on" if safe else "off")
        _shot(page, out_dir, name)
        res["checks"]["safeArea.%s" % ("on" if safe else "off")] = d
        res["shots"].append({"shot": name, "route": "#/", "probe": d})
        page.close()
        ctx.close()

    # 9.4 fullscreen Telegram (isFullscreen=true через SDK)
    sdk = _sdk_js(fullscreen=True, safe_top=0, safe_bottom=0)
    for (w, h) in ((390, 844), (1280, 900)):
        ctx = open_ctx(browser, w, h, sdk_js=sdk)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1100)
        d = page.evaluate(r"""() => ({
          fs: window.__adminbotVm ? window.__adminbotVm.isFullscreen : null,
          fsAttr: document.documentElement.getAttribute('data-fullscreen'),
          shell: (document.querySelector('.app-shell') || {}).className || '',
          hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
        })""")
        name = "w13-extra-fullscreen-%d.jpg" % w
        _shot(page, out_dir, name)
        res["checks"]["fullscreen.%d" % w] = d
        res["shots"].append({"shot": name, "route": "#/", "probe": d})
        page.close()
        ctx.close()

    # 9.5 короткое видео: телефон и десктоп (реальные пиксели, реальный hash)
    vids = {}
    for (w, h) in ((390, 844), (1280, 900)):
        vdir = os.path.join(out_dir, "_video-%d" % w)
        os.makedirs(vdir, exist_ok=True)
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=1,
            record_video_dir=vdir,
            record_video_size={"width": w, "height": h},
        )
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler())
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/web/index.html#/" % PORT,
                  wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1200)
        for route in ("#/modules", "#/ai", "#/memory", "#/access", "#/oversight"):
            page.evaluate("(r) => { window.location.hash = r; }", route)
            page.wait_for_timeout(900)
            page.evaluate("() => { const m = document.querySelector("
                          "'main.scroll-area'); if (m) m.scrollTop = "
                          "Math.min(320, m.scrollHeight); }")
            page.wait_for_timeout(700)
        page.wait_for_timeout(400)
        video = page.video
        page.close()
        name = "w13-video-%d.webm" % w
        try:
            video.save_as(os.path.join(out_dir, name))
            vids[name] = os.path.getsize(os.path.join(out_dir, name))
        except Exception as exc:  # noqa: BLE001
            vids[name] = "error: %s" % str(exc)[:120]
        ctx.close()
        import shutil
        shutil.rmtree(vdir, ignore_errors=True)
    res["checks"]["videos"] = vids

    with io.open(os.path.join(out_dir, "w13-extras.json"), "w",
                 encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("[extras] %s" % json.dumps(res["checks"], ensure_ascii=False)[:600])
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 10. ЗАПУСК
# ═══════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--only", default="inv,sweep,states,portal,extras,touch,defects")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    from playwright.sync_api import sync_playwright

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    run = {"started": None, "sections": {}}
    import datetime
    run["started"] = datetime.datetime.now().isoformat(timespec="seconds")

    inv = None
    inv_path = os.path.join(out_dir, "w13-routes-inventory.json")
    if "inv" not in only and os.path.exists(inv_path):
        with io.open(inv_path, encoding="utf-8") as f:
            inv = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        if "inv" in only:
            inv = run_inventory(browser, out_dir)
        if "sweep" in only:
            run["sections"]["sweep"] = run_sweep(browser, out_dir, inv,
                                                 limit=args.limit)["summary"]
        if "states" in only:
            run["sections"]["states"] = run_states(browser, out_dir)["summary"]
        if "portal" in only:
            portal = run_portal(browser, out_dir)
            run["sections"]["portal"] = portal["checks"]
        if "extras" in only:
            run["sections"]["extras"] = run_extras(browser, out_dir)["checks"]
        if "touch" in only:
            run["sections"]["touch"] = run_touch(browser, out_dir, inv,
                                                 limit=args.limit)["summary"]
        if "defects" in only:
            run["sections"]["defects"] = run_defects(browser, out_dir)["checks"]
        browser.close()

    httpd.shutdown()
    import datetime
    run["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    # Сводка по всем секциям: если секцию в этом прогоне не запускали, берём
    # её summary из уже лежащего JSON (иначе w13-run.json показывал бы только
    # последний частичный запуск).
    for key, fname, field in (
            ("inv", "w13-routes-inventory.json", "summary"),
            ("sweep", "w13-sweep.json", "summary"),
            ("states", "w13-states.json", "summary"),
            ("touch", "w13-touch-targets.json", "summary"),
            ("portal", "w13-portal-focus.json", "checks"),
            ("defects", "w13-defects.json", "checks"),
            ("extras", "w13-extras.json", "checks")):
        if key in run["sections"]:
            continue
        path = os.path.join(out_dir, fname)
        if not os.path.exists(path):
            continue
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
        if field in data:
            run["sections"][key] = data[field]
    with io.open(os.path.join(out_dir, "w13-run.json"), "w",
                 encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)
    print("[run] %s" % json.dumps(run["sections"], ensure_ascii=False)[:800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
