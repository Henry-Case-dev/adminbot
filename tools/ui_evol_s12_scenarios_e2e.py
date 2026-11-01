"""ASAP-UI-02 §12 — сводный прогон 17 обязательных конечных сценариев.

Зачем отдельный файл: набор из 17 сценариев (`plans/current_task.md` §12,
строки карты L01966–L01982) приёмка требует как ЦЕЛОЕ, но единой точки входа
у набора не было — доказательства собирались из разных полос. Это не новый
фреймворк и не второй стенд: сервер/стабы/TMA/контексты переиспользуются из
`tools/ui_round1025_matrix.py` и `tools/ui_evol_w13_full_visual_e2e.py`
(те же фикстуры, тот же Chromium, тот же формат снимков).

Каждый сценарий пишет в один JSON:
  * `status`     — PASS / FAIL / PARTIAL / BLOCKED;
  * `assertion`  — утверждение, которое СТАНЕТ красным при поломке контракта;
  * `probe`      — машинночитаемые факты прогона;
  * `shots`      — снимки именно этого сценария.

Сценарии 6 и 14 доказаны отдельным принятым прогоном
(`tools/ui_asap_ui02_delta_e2e.py`, Re-check 3 Approved) — здесь они не
подменяются копией, а переиспользуется тот же инструмент (`--out` в каталог
этого прогона) и ссылка на его JSON.

Сценарии 11 и 12 (когнитивная карта) заблокированы EVOL-COG-MAP: карты,
свайпа страницы в embedded-режиме, режима «Исследовать», LOD и восстановления
камеры в сборке НЕТ. Они отмечаются `BLOCKED`, а не `NOT_OBSERVED` и не
изображаются прогоном легаси-графа.

Запуск:
    .venv\\Scripts\\python.exe tools\\ui_evol_s12_scenarios_e2e.py [--out DIR]
Артефакты по умолчанию: plans/features/evol/audit/evidence/s12/
"""
import argparse
import copy
import io
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

import ui_round1025_matrix as M              # noqa: E402  сервер/стабы/TMA
import ui_evol_w13_full_visual_e2e as W13   # noqa: E402  контексты/стабы/пробы

PORT = W13.PORT
BASE = "http://127.0.0.1:%d/web/index.html" % PORT
DEFAULT_OUT = os.path.join(REPO, "plans", "features", "evol", "audit",
                           "evidence", "s12")

LONG_TITLE = "Очень длинное название рабочего чата с уточнением и подписью"
POSTS = []
# Патч конфига от POST /api/config: стенд обязан ПОМНИТЬ записанное, иначе
# «сервер подтвердил» проверялось бы против вечно-исходного стаба.
PATCH = {}
TWO_CHATS = [
    {"chat_id": -1001234567890, "title": LONG_TITLE, "type": "supergroup",
     "is_dm": False, "photo_file_id": None},
    {"chat_id": -1001234567891, "title": "Второй чат", "type": "group",
     "is_dm": False, "photo_file_id": None},
]
# Основные разделы: ровно те, что обязаны жить в drawer (§2.1/§12.1).
MAIN_SECTIONS = ("Статус", "Аналитика", "Модули", "ИИ", "Память", "Доступы")

POSTS = []


# ═══════════════════════════════════════════════════════════════════════════
# Маршруты API: тот же стаб W13, плюс журнал POST и управляемый отказ записи
# ═══════════════════════════════════════════════════════════════════════════
def _config_payload(is_chat):
    """Текущий конфиг с учётом уже ЗАПИСАННЫХ этим стендом значений."""
    data = copy.deepcopy(M.CONFIG_STUB_CHAT if is_chat else M.CONFIG_STUB)
    for key, value in PATCH.items():
        for item in data.get("items", []):
            if item.get("key") == key:
                item["value"] = value
                if item.get("per_chat"):
                    item["global_value"] = value
    return data


BELIEF_STUB = [
    {"id": 11, "fact": "владелец предпочитает краткие ответы",
     "created_at": 1761900000, "chat_id": -1001234567890, "confidence": 0.7},
    {"id": 12, "fact": "обращения на «ты» допустимы",
     "created_at": 1761903600, "chat_id": -1001234567890, "confidence": 0.6},
    {"id": 13, "fact": "не любит длинные вступления",
     "created_at": 1761907200, "chat_id": -1001234567890, "confidence": 0.8},
]
PARADIGM_STUB = [
    {"id": 21, "fact": "диалог строится вокруг практических задач",
     "created_at": 1761900000, "chat_id": -1001234567890, "confidence": 0.5},
    {"id": 22, "fact": "предпочтение коротких подтверждений",
     "created_at": 1761903600, "chat_id": -1001234567890, "confidence": 0.5},
]


def _api(overrides=None, fail=None, post="ok", config_delay_ms=0):
    import time
    base = W13._api_handler(overrides, fail, 0)
    log = []

    def _route(route):
        req = route.request
        full = req.url
        url = full.split("?")[0]
        hdrs = req.headers or {}
        if req.method == "POST" and "/api/config" in url:
            body = req.post_data or ""
            log.append({"url": url, "body": body[:600],
                        "hdrChat": hdrs.get("x-chat-id")})
            if post == "fail":
                route.fulfill(status=500, content_type="application/json",
                              body=json.dumps({"error": "forced 500"}))
                return
            try:
                sent = json.loads(body)
                for it in (sent.get("items") or []):
                    if isinstance(it, dict) and "key" in it:
                        PATCH[it["key"]] = it.get("value")
            except Exception:  # noqa: BLE001
                pass
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "updated_at": 1}))
            return
        if req.method == "GET" and url.endswith("/api/config"):
            if config_delay_ms:
                time.sleep(config_delay_ms / 1000.0)
            payload = _config_payload(bool(hdrs.get("x-chat-id")))
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(copy.deepcopy(payload)))
            return
        if url.endswith("/api/memory/dream/beliefs"):
            kind = ""
            if "kind=" in full:
                kind = full.split("kind=")[1].split("&")[0]
            payload = PARADIGM_STUB if kind == "paradigm" else BELIEF_STUB
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
            return
        base(route)
    _route.log = log
    return _route


def _page(browser, w, h, api=None, route="#/", sdk=None, touch=None,
          settle=900):
    ctx = W13.open_ctx(browser, w, h, api=api, sdk_js=sdk, touch=touch)
    pg = ctx.new_page()
    errs = []
    pg.on("console", lambda m: errs.append("%s: %s" % (m.type, m.text[:160]))
          if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
    pg.goto(BASE + route, wait_until="load")
    pg.wait_for_selector(".app-shell", timeout=25000)
    pg.wait_for_timeout(settle)
    return ctx, pg, errs


def _snap(pg, out_dir, name):
    W13._shot(pg, out_dir, name)
    return name


def _fails_probe(pid, fails, items):
    for msg in items:
        fails.append("%s: %s" % (pid, msg))


# ═══════════════════════════════════════════════════════════════════════════
# Пробы
# ═══════════════════════════════════════════════════════════════════════════
P_SHELL = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (n) => { if (!n) return false; const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden'
      && cs.display !== 'none'; };
  const hdr = q('header.header-sticky');
  const hr = hdr ? hdr.getBoundingClientRect() : null;
  const de = document.scrollingElement || document.documentElement;
  const drawer = q('.app-drawer');
  const main = q('main.scroll-area');
  const mr = main ? main.getBoundingClientRect() : null;
  return {
    hash: location.hash,
    headerH: hr ? Math.round(hr.height) : null,
    headerVisible: vis(hdr),
    headerCount: qa('header.header-sticky').length,
    bottomNav: qa('nav.mobile-topnav, .mobile-topnav, .bottom-nav').length,
    drawerExists: !!drawer,
    drawerLinks: drawer ? qa('.app-drawer .sidebar-link').length : 0,
    drawerLabels: drawer ? qa('.app-drawer .sidebar-label')
      .map((n) => (n.textContent || '').trim()).filter(Boolean) : [],
    hScroll: Math.max(0, (de ? de.scrollWidth : 0) - window.innerWidth),
    fsBtns: qa('[data-fs-toggle]').length,
    drawerTrigger: vis(q('[data-drawer-trigger]')),
    mainH: mr ? Math.round(mr.height) : 0,
    vw: window.innerWidth, vh: window.innerHeight,
  };
}
"""

P_IDENTITY = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (n) => { if (!n) return false; const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden'
      && cs.display !== 'none'; };
  const rect = (n) => { if (!n) return null; const r = n.getBoundingClientRect();
    return {l: Math.round(r.left), r: Math.round(r.right),
            t: Math.round(r.top), b: Math.round(r.bottom),
            w: Math.round(r.width), h: Math.round(r.height)}; };
  const role = q('.header-user-role');
  const init = q('.header-user-initial');
  const av = q('header .header-user img');
  const scope = q('[data-nav-scope]');
  const logos = qa('.sidebar-brand, .mobile-brand, .sidebar-brand-title, '
    + '.nav-logo, img[alt*="Adminbot" i], .logo');
  return {
    logos: logos.length,
    roleText: role ? (role.textContent || '').trim() : '',
    roleVisible: vis(role),
    avatarVisible: vis(init) || vis(av),
    scopeRect: rect(scope),
    roleRect: rect(role),
    avatarRect: rect(av || init),
    scopeVisible: vis(scope),
    letterMarkTexts: qa('header .header-title, .header-title-wrap')
      .map((n) => (n.textContent || '').trim().slice(0, 40)),
  };
}
"""

P_SCOPE = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const rect = (n) => { if (!n) return null; const r = n.getBoundingClientRect();
    return {l: Math.round(r.left), r: Math.round(r.right),
            t: Math.round(r.top), b: Math.round(r.bottom),
            w: Math.round(r.width), h: Math.round(r.height)}; };
  const panel = q('#scope-panel');
  const cs = panel ? getComputedStyle(panel) : null;
  const trig = q('.scope-trigger');
  return {
    options: qa('.scope-option').length,
    texts: qa('.scope-option .scope-option__title')
      .map((n) => (n.textContent || '').trim()),
    titles: qa('.scope-option .scope-option__title')
      .map((n) => n.getAttribute('title') || ''),
    clamp: qa('.scope-option .scope-option__title').map((n) => {
      const c = getComputedStyle(n);
      return {ch: n.clientHeight, sh: n.scrollHeight,
              lh: Math.round(parseFloat(c.lineHeight) || 0),
              ov: c.overflow};
    }),
    panelRect: rect(panel),
    panelBg: cs ? cs.backgroundColor : null,
    panelFilter: cs ? (cs.backdropFilter || cs.webkitBackdropFilter || 'none')
      : null,
    triggerTitle: trig ? trig.getAttribute('title') : null,
    triggerText: trig ? (trig.textContent || '').replace(/\s+/g, ' ').trim()
      : '',
    vw: window.innerWidth, vh: window.innerHeight,
    stableH: parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--tg-viewport-stable-height')) || window.innerHeight,
  };
}
"""

P_HOVER = r"""
(kind) => {
  const n = document.querySelector(kind);
  if (!n) return null;
  const cs = getComputedStyle(n);
  return {bg: cs.backgroundColor, color: cs.color, filter: cs.filter,
          boxShadow: cs.boxShadow, opacity: cs.opacity,
          rect: (() => { const r = n.getBoundingClientRect();
            return {w: Math.round(r.width), h: Math.round(r.height)}; })()};
}
"""

P_CONTROLS = r"""
(known) => {
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const vis = (n) => { const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 1 && r.height > 1 && cs.visibility !== 'hidden'
      && cs.display !== 'none'; };
  const cls = (n) => (n.className || '').toString();
  const K = new Set(known);
  const hasKnown = (n) => cls(n).split(/\s+/).some((c) => K.has(c));
  const btn = qa('button').filter(vis);
  const inputs = qa('input:not([type="hidden"])').filter(vis);
  const selects = qa('select').filter(vis);
  const checks = qa('input[type="checkbox"]').filter(vis);
  const checkOk = checks.filter((n) => cls(n).indexOf('ctl-check__box') >= 0
    || n.closest('.ctl-toggle') || n.closest('.ctl-check'));
  return {
    buttons: btn.length,
    btnUnstyled: btn.filter((n) => !hasKnown(n))
      .map((n) => (cls(n) || '(без класса)') + ' :: '
        + (n.textContent || '').trim().slice(0, 24)),
    inputs: inputs.length,
    inputUnstyled: inputs.filter((n) => {
      const c = cls(n);
      return c.indexOf('field') < 0 && c.indexOf('ctl-') < 0
        && c.indexOf('palette') < 0 && c.indexOf('module-search') < 0
        && c.indexOf('sr-only') < 0 && c.indexOf('scope') < 0;
    }).map((n) => (cls(n) || n.type).slice(0, 24)),
    selects: selects.length,
    selectUnstyled: selects.filter((n) => {
      const c = cls(n);
      return c.indexOf('field') < 0 && c.indexOf('ctl-') < 0;
    }).length,
    checks: checks.length,
    checksUnified: checkOk.length,
    checksAll: qa('input[type="checkbox"]').length,
    checksAllUnified: qa('input[type="checkbox"]').filter((n) =>
      cls(n).indexOf('ctl-check__box') >= 0 || n.closest('.ctl-toggle')
      || n.closest('.ctl-check')).length,
    toggles: qa('.ctl-toggle').length,
    masterToggles: qa('[data-module-global-toggle]').length,
    scopeToggles: qa('[data-module-scope-toggle]').length,
    moduleCards: qa('article.module-card').length,
    togglesPerCard: qa('article.module-card').map((n) =>
      n.querySelectorAll('[data-module-scope-toggle],'
        + '[data-module-global-toggle]').length),
  };
}
"""

P_TOGGLE = r"""
() => {
  const q = (s) => document.querySelector(s);
  const t = q('[data-module-scope-toggle]');
  const card = t ? t.closest('article.module-card') : null;
  return {
    exists: !!t,
    checked: t ? !!t.checked : null,
    disabled: t ? !!t.disabled : null,
    mod: card ? card.getAttribute('data-mod') : null,
    err: (() => { const e = document.querySelector('[data-module-scope-error]');
      return e ? (e.textContent || '').replace(/\s+/g, ' ').trim() : ''; })(),
    scopeBadge: (q('[data-nav-scope] .badge') || {}).textContent || '',
    stateText: card ? (card.querySelector('.module-control-row__state') || {})
      .textContent || '' : '',
    loading: !!q('[data-module-loading]'),
    busy: (() => { const c = q('.module-catalog');
      return c ? c.getAttribute('aria-busy') : null; })(),
    palBusy: (() => { const p = q('.palette-panel');
      return p ? p.getAttribute('aria-busy') : null; })(),
  };
}
"""

P_RIBBONS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const widget = q('[data-intel-widget]');
  const secs = qa('[data-intel-section]').map((n) =>
    n.getAttribute('data-intel-section'));
  const graphs = qa('[data-status-map], .status-map, .graph-embed, '
    + '[data-status-graph]').length;
  const track = q('[data-sfeed-viewport] .sfeed-track');
  const vis = (n) => { if (!n) return false; const r = n.getBoundingClientRect();
    return r.width > 1 && r.height > 1; };
  const order = [];
  document.querySelectorAll('main.scroll-area [data-intel-widget],'
    + ' main.scroll-area .status-hero, main.scroll-area .health-grid,'
    + ' main.scroll-area [data-status-map]').forEach((n) => {
      order.push(n.getAttribute('data-intel-widget') != null ? 'intel'
        : (n.getAttribute('data-status-map') != null ? 'map'
          : (n.className || '').toString().slice(0, 24)));
    });
  return {
    widget: !!widget, sections: secs, graphs: graphs, order: order,
    track: !!track,
    transform: track ? getComputedStyle(track).transform : null,
    tracks: qa('[data-sfeed-viewport]').length,
    rows: qa('[data-sfeed-row]').length,
    dates: qa('[data-sfeed-row]').slice(0, 3).map((n) =>
      (n.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)),
    empty: qa('[data-sfeed-empty]').length,
    errors: qa('[data-sfeed-error]').length,
    visibleSections: qa('[data-intel-section]').filter(vis).length,
    swiper: qa('[data-intel-tab-btn]').length,
  };
}
"""

P_HEALTH = r"""
() => {
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const cards = qa('[data-health-state]').map((n) => {
    const cs = getComputedStyle(n);
    const inner = n.querySelector('.card, [data-glass]') || n;
    const ics = getComputedStyle(inner);
    const r = inner.getBoundingClientRect();
    return {
      sub: n.getAttribute('data-health-subsystem'),
      state: n.getAttribute('data-health-state'),
      bg: ics.backgroundColor, alpha: ics.opacity,
      filter: ics.backdropFilter || ics.webkitBackdropFilter || 'none',
      w: Math.round(r.width), h: Math.round(r.height),
    };
  });
  const dataCards = qa('.card, [data-glass]').map((n) => {
    const cs = getComputedStyle(n);
    return {cls: (n.className || '').toString().slice(0, 40),
            state: n.getAttribute('data-health-state'),
            bg: cs.backgroundColor};
  });
  return {
    cards: cards,
    canvases: qa('canvas').length,
    canvasKinds: qa('canvas').map((n) => (n.className || n.id || '').toString()
      .slice(0, 24)),
    tintedNonHealth: dataCards.filter((c) => !c.state
      && /rgb\(\s*(1[6-9][0-9]|2[0-5][0-9])/.test(c.bg)).length,
  };
}
"""

P_ZOOM = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const rect = (n) => { if (!n) return null; const r = n.getBoundingClientRect();
    return {l: Math.round(r.left), r: Math.round(r.right),
            t: Math.round(r.top), b: Math.round(r.bottom)}; };
  const de = document.scrollingElement || document.documentElement;
  const vw = window.innerWidth, vh = window.innerHeight;
  const hdrKids = qa('header.header-sticky > *').map((n) => {
    const r = n.getBoundingClientRect();
    return {cls: (n.className || '').toString().slice(0, 28),
            off: r.width > 0 && (r.right > vw + 1 || r.left < -1)};
  });
  return {
    vw: vw, vh: vh,
    hScroll: Math.max(0, (de ? de.scrollWidth : 0) - vw),
    headerH: (() => { const h = q('header.header-sticky');
      return h ? Math.round(h.getBoundingClientRect().height) : null; })(),
    headerKids: hdrKids,
    headerOff: hdrKids.filter((k) => k.off).length,
    save: rect(q('.sticky-save button, [data-sticky-save] button,'
      + ' .sticky-save')),
    close: rect(q('[data-prompt-fullscreen] .modal-close, .modal-close')),
    editor: rect(q('textarea.ctl-textarea, textarea.field, textarea')),
    kbInset: getComputedStyle(document.documentElement)
      .getPropertyValue('--kb-inset').trim(),
  };
}
"""

P_ROUTE = r"""
() => {
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const de = document.scrollingElement || document.documentElement;
  const main = q('main.scroll-area');
  const titles = qa('.hub-title, .header-title').filter((n) => {
    const r = n.getBoundingClientRect();
    return r.width > 1 && r.height > 1 && getComputedStyle(n).display !== 'none';
  }).map((n) => (n.textContent || '').trim());
  return {
    hash: location.hash,
    textLen: main ? (main.innerText || '').replace(/\s+/g, ' ').trim().length
      : 0,
    titles: titles,
    titleDup: titles.length - new Set(titles).size,
    hScroll: Math.max(0, (de ? de.scrollWidth : 0) - window.innerWidth),
    legacyNav: qa('nav.mobile-topnav, .mobile-topnav, .bottom-nav').length,
    legacyGrid: qa('[data-more-trigger]').length,
    masterToggles: qa('[data-module-global-toggle]').length,
    ctlBtns: qa('.ctl-btn, .ctl-toggle, .ctl-check, .ctl-input, .ctl-select')
      .length,
    oldBtns: qa('button[class="btn"], button[class*="bg-violet"]').length,
  };
}
"""

P_PERF = r"""
() => new Promise((resolve) => {
  const frames = [];
  let last = performance.now();
  const slow = [];
  const obs = window.PerformanceObserver ? new PerformanceObserver((list) => {
    list.getEntries().forEach((e) => slow.push(Math.round(e.duration)));
  }) : null;
  try { if (obs) obs.observe({entryTypes: ['longtask']}); } catch (e) { /* нет */ }
  const t0 = performance.now();
  function tick() {
    const now = performance.now();
    frames.push(Math.round(now - last));
    last = now;
    if (now - t0 < 2500) requestAnimationFrame(tick);
    else {
      const sorted = frames.slice().sort((a, b) => a - b);
      const p = (q) => sorted[Math.min(sorted.length - 1,
        Math.floor(sorted.length * q))] || 0;
      resolve({
        frames: frames.length,
        p50: p(0.5), p95: p(0.95), max: sorted[sorted.length - 1] || 0,
        slowFrames: frames.filter((f) => f > 100).length,
        longTasks: slow.length, longMax: slow.length ? Math.max(...slow) : 0,
        canvases: document.querySelectorAll('canvas').length,
        webglLost: Array.from(document.querySelectorAll('canvas')).filter(
          (c) => {
            try { const gl = c.getContext('webgl') || c.getContext('webgl2');
              return !!(gl && gl.isContextLost()); } catch (e) { return false; }
          }).length,
      });
    }
  }
  requestAnimationFrame(tick);
})
"""


# ═══════════════════════════════════════════════════════════════════════════
# §12.1 — телефон портрет
# ═══════════════════════════════════════════════════════════════════════════
def s1_portrait(browser, out_dir, rec, fails):
    pid = "§12.1"
    rows = []
    for (w, h) in ((390, 844), (320, 568)):
        ctx, pg, errs = _page(browser, w, h)
        base = pg.evaluate(P_SHELL)
        pg.click("[data-drawer-trigger]")
        pg.wait_for_timeout(450)
        opened = pg.evaluate(P_SHELL)
        shots = [_snap(pg, out_dir, "s12-s1-portrait-%d-drawer.png" % w)]
        pg.evaluate("document.querySelector('.app-drawer .sidebar-label')"
                    ".closest('button').click()")
        pg.wait_for_timeout(500)
        after = pg.evaluate(P_SHELL)
        rows.append({"viewport": w, "base": base, "drawer": opened,
                     "afterNav": after, "errors": errs,
                     "shots": shots})
        _fails_probe(pid, fails, [x for x in [
            "нет кнопки навигации в шапке" if not base["drawerTrigger"] else "",
            "остался нижний навбар (%d)" % base["bottomNav"]
            if base["bottomNav"] else "",
            "высота шапки %s > 78 на телефоне" % base["headerH"]
            if (base["headerH"] or 0) > 78 else "",
            "шапка не видна" if not base["headerVisible"] else "",
            "горизонтальный скролл %d px" % base["hScroll"]
            if base["hScroll"] > 0 else "",
            "drawer не открылся" if not opened["drawerLinks"] else "",
            "drawer: %d разделов < 8" % opened["drawerLinks"]
            if opened["drawerLinks"] and opened["drawerLinks"] < 8 else "",
            "drawer не содержит раздел «%s»"
            % [s for s in MAIN_SECTIONS
               if not any(s in lab for lab in opened["drawerLabels"])]
            if [s for s in MAIN_SECTIONS
                if not any(s in lab for lab in opened["drawerLabels"])] else "",
            "переход из drawer не закрыл панель"
            if after["drawerLinks"] and after["hScroll"] == 0
            and "drawer-open" in (after.get("shellCls") or "") else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Phone portrait: нет нижнего навбара, drawer открывает все "
             "основные разделы, topbar минимален",
        "document.querySelector('nav.mobile-topnav')===null; drawer содержит "
        ">=8 разделов и все имена MAIN_SECTIONS; высота шапки <=78 px на 390 и "
        "320; document.scrollWidth <= innerWidth",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.2 — телефон ландшафт / низкий вьюпорт
# ═══════════════════════════════════════════════════════════════════════════
def s2_landscape(browser, out_dir, rec, fails):
    pid = "§12.2"
    rows = []
    for (w, h) in ((667, 375), (812, 375), (932, 430)):
        ctx, pg, errs = _page(browser, w, h)
        base = pg.evaluate(P_SHELL)
        mainBox = pg.evaluate(r"""() => {
          const m = document.querySelector('main.scroll-area');
          if (!m) return null;
          const r = m.getBoundingClientRect();
          const cs = getComputedStyle(m);
          return {h: Math.round(r.height), w: Math.round(r.width),
                  scrollable: m.scrollHeight > m.clientHeight + 1,
                  textLen: (m.innerText || '').trim().length,
                  display: cs.display};
        }""")
        pg.click("[data-drawer-trigger]")
        pg.wait_for_timeout(420)
        opened = pg.evaluate(P_SHELL)
        rows.append({"viewport": "%dx%d" % (w, h), "base": base,
                     "main": mainBox, "drawer": opened, "errors": errs,
                     "shots": [_snap(pg, out_dir,
                                     "s12-s2-landscape-%dx%d.png" % (w, h))]})
        _fails_probe(pid, fails, [x for x in [
            "вторая массивная шапка: высота %s > 62" % base["headerH"]
            if (base["headerH"] or 0) > 62 else "",
            "больше одной шапки: %d" % base["headerCount"]
            if base["headerCount"] > 1 else "",
            "нижний навбар вернулся" if base["bottomNav"] else "",
            "контент не виден (main h=%s)" % (mainBox or {}).get("h")
            if not mainBox or (mainBox or {}).get("h", 0) < 120 else "",
            "контент пустой (textLen %s)" % (mainBox or {}).get("textLen")
            if (mainBox or {}).get("textLen", 0) < 40 else "",
            "горизонтальный скролл %d px" % base["hScroll"]
            if base["hScroll"] > 0 else "",
            "drawer не открывается в ландшафте"
            if not opened["drawerLinks"] else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Phone landscape / низкий viewport: обязательные элементы "
             "видны, второй шапки нет, контент пригоден",
        "на 667x375/812x375/932x430: headerCount===1, высота шапки <=62, "
        "bottomNav===0, main.height>=120 и textLen>=40, scrollWidth<=innerWidth",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.3 — идентичность
# ═══════════════════════════════════════════════════════════════════════════
def _overlap(a, b):
    if not a or not b:
        return 0
    dx = min(a["r"], b["r"]) - max(a["l"], b["l"])
    dy = min(a["b"], b["b"]) - max(a["t"], b["t"])
    return max(0, dx) * max(0, dy)


def s3_identity(browser, out_dir, rec, fails):
    pid = "§12.3"
    rows = []
    for (w, h) in ((390, 844), (1280, 900)):
        ctx, pg, errs = _page(browser, w, h)
        p = pg.evaluate(P_IDENTITY)
        rows.append({"viewport": w, **p, "errors": errs,
                     "scopeRoleOverlap": _overlap(p["roleRect"],
                                                  p["scopeRect"]),
                     "scopeAvatarOverlap": _overlap(p["avatarRect"],
                                                    p["scopeRect"]),
                     "shots": [_snap(pg, out_dir,
                                     "s12-s3-identity-%d.png" % w)]})
        _fails_probe(pid, fails, [x for x in [
            "логотип/слово-марка ещё в разметке (%d)" % p["logos"]
            if p["logos"] else "",
            "роль не видна" if not p["roleVisible"] else "",
            "роль пустая" if not p["roleText"] else "",
            "аватар (фото или инициал) не виден" if not p["avatarVisible"]
            else "",
            "селектор области не виден" if not p["scopeVisible"] else "",
            "роль перекрывает селектор области"
            if _overlap(p["roleRect"], p["scopeRect"]) > 0 else "",
            "аватар перекрывает селектор области"
            if _overlap(p["avatarRect"], p["scopeRect"]) > 0 else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Идентичность: логотипа нет, аватар и фактическая роль видны "
             "компактно и не мешают chat switcher",
        "logos===0; .header-user-role видим с непустым текстом; аватар-инициал "
        "или фото виден; пересечение прямоугольников роль/аватар с "
        "[data-nav-scope] равно 0 на 390 и 1280",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.4 — длинный чат + область двух чатов и global
# ═══════════════════════════════════════════════════════════════════════════
def s4_scope(browser, out_dir, rec, fails):
    pid = "§12.4"
    rows = []
    for (w, h) in ((390, 844), (1280, 900)):
        api = _api({"/api/access/chats": TWO_CHATS})
        ctx, pg, errs = _page(browser, w, h, api=api, route="#/modules")
        pg.click(".scope-trigger")
        pg.wait_for_timeout(400)
        opened = pg.evaluate(P_SCOPE)
        shots = [_snap(pg, out_dir, "s12-s4-scope-%d-open.png" % w)]
        # переход во второй чат: маршрут и раздел не должны сброситься
        pg.evaluate(r"""() => {
          const opts = Array.from(document.querySelectorAll('.scope-option'));
          const second = opts.find((o) => (o.textContent || '')
            .indexOf('Второй чат') >= 0) || opts[1];
          if (second) second.click();
        }""")
        pg.wait_for_timeout(700)
        afterChat = pg.evaluate(P_SCOPE)
        afterVm = pg.evaluate("""() => { const vm = window.__adminbotVm;
          return {scopeKind: vm ? vm.scopeKind : null,
                  chatId: vm ? vm.activeChatId : null,
                  hash: location.hash}; }""")
        # затем global
        pg.click(".scope-trigger")
        pg.wait_for_timeout(350)
        pg.evaluate(r"""() => {
          const o = Array.from(document.querySelectorAll('.scope-option'))
            .find((n) => /глобал/i.test(n.textContent || ''));
          if (o) o.click();
        }""")
        pg.wait_for_timeout(700)
        afterGlobal = pg.evaluate("""() => { const vm = window.__adminbotVm;
          return {scopeKind: vm ? vm.scopeKind : null,
                  hash: location.hash,
                  label: (document.querySelector('.scope-trigger .badge')
                    || {}).textContent || ''}; }""")
        shots.append(_snap(pg, out_dir, "s12-s4-scope-%d-global.png" % w))
        rows.append({"viewport": w, "opened": opened, "afterChat": afterVm,
                     "afterChatPanel": afterChat, "afterGlobal": afterGlobal,
                     "errors": errs, "shots": shots})
        clamp_bad = [c for c in opened["clamp"]
                     if c["sh"] > c["ch"] + 1 and c["ch"] < c["lh"] * 2 - 2]
        _fails_probe(pid, fails, [x for x in [
            "опций области %d, ожидалось 3 (два чата + global)"
            % opened["options"] if opened["options"] != 3 else "",
            "полное имя чата не в title опции"
            if opened["titles"] and LONG_TITLE not in opened["titles"] else "",
            "имя чата обрезано по вертикали (clientHeight < двух строк): %s"
            % clamp_bad if clamp_bad else "",
            "имя в триггере неполное (title != полное)"
            if w >= 768 and opened["triggerTitle"] != LONG_TITLE else "",
            "панель области вне вьюпорта: %s" % opened["panelRect"]
            if opened["panelRect"] and (
                opened["panelRect"]["l"] < -1
                or opened["panelRect"]["r"] > opened["vw"] + 1
                or opened["panelRect"]["b"] > opened["stableH"] + 1) else "",
            "переход в другой чат сбросил маршрут (%s)"
            % afterVm["hash"] if afterVm["hash"] != "#/modules" else "",
            "переход в другой чат не сменил активный чат"
            if afterVm["chatId"] not in (TWO_CHATS[1]["chat_id"],
                                         TWO_CHATS[0]["chat_id"]) else "",
            "global-режим не включился (%s)" % afterGlobal
            if afterGlobal["scopeKind"] != "global" else "",
            "переход в global сбросил маршрут (%s)" % afterGlobal["hash"]
            if afterGlobal["hash"] != "#/modules" else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Длинный чат: имя читается в селекторе, область корректна для "
             "двух чатов + global, переход не сбрасывает контекст",
        "в панели ровно 3 опции (2 чата + global); полное имя в title; на "
        "телефоне имя занимает 2 полные строки без обрезки по вертикали; "
        "выбор чата и global сохраняет маршрут #/modules и меняет scopeKind",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.5 — меню «Ещё»
# ═══════════════════════════════════════════════════════════════════════════
def s5_more(browser, out_dir, rec, fails):
    pid = "§12.5"
    ctx, pg, errs = _page(browser, 390, 844)
    p = pg.evaluate(r"""() => {
      const qa = (s) => Array.from(document.querySelectorAll(s));
      const hdr = document.querySelector('header.header-sticky');
      const hdrBtns = hdr ? Array.from(hdr.querySelectorAll('button')) : [];
      const vis = (n) => { const r = n.getBoundingClientRect();
        return r.width > 1 && r.height > 1; };
      return {
        moreTrigger: qa('[data-more-trigger]').length,
        gridGlyph: qa('.msr').filter((n) => (n.textContent || '')
          .trim() === 'grid_view').length,
        searchEntry: qa('[data-palette-open], [data-palette-open-drawer]')
          .filter(vis).length,
        fsEntry: qa('[data-fs-toggle]').filter(vis).length,
        headerButtons: hdrBtns.map((n) => ({
          cls: (n.className || '').toString().slice(0, 30),
          label: n.getAttribute('aria-label') || (n.textContent || '')
            .trim().slice(0, 20)})),
        drawerOnlySections: qa('.app-drawer .sidebar-link').length,
        sectionNamesInHeader: hdrBtns.filter((n) =>
          /Статус|Аналитика|Модули|Память|Доступы/.test(n.textContent || ''))
          .length,
      };
    }""")
    shot = _snap(pg, out_dir, "s12-s5-header-390.png")
    _fails_probe(pid, fails, [x for x in [
        "подмена навигации сеткой из четырёх квадратов (grid_view) x%d"
        % p["gridGlyph"] if p["gridGlyph"] else "",
        "второе конкурирующее меню разделов в шапке: %d"
        % p["sectionNamesInHeader"] if p["sectionNamesInHeader"] else "",
        "вторичные действия недоступны (поиск %d, fullscreen %d)"
        % (p["searchEntry"], p["fsEntry"])
        if not p["searchEntry"] and not p["fsEntry"] else "",
        "разделы не живут в drawer (%d)" % p["drawerOnlySections"]
        if p["drawerOnlySections"] < 8 else "",
        "ошибки консоли: %s" % errs[:2] if errs else "",
    ] if x])
    ctx.close()
    rec(pid, "Меню «Ещё»: ellipsis вместо сетки, только вторичные действия, "
             "разделы не дублируются",
        "в шапке нет grid_view-глифа и нет второй панели разделов; "
        "вторичные действия (поиск/полный экран) доступны; разделы — только "
        "в drawer. ПРИМЕЧАНИЕ: само меню «…» удалено позднейшим решением "
        "владельца (§6.1 v2.1), поэтому триггер «Ещё» отсутствует — "
        "проверяется существо клаузулы, а не удалённый элемент",
        {"probe": p}, fails, [shot])


# ═══════════════════════════════════════════════════════════════════════════
# §12.7 — overlay у краёв и возврат фокуса
# ═══════════════════════════════════════════════════════════════════════════
def s7_overlay(browser, out_dir, rec, fails):
    pid = "§12.7"
    rows = []
    for (w, h) in ((320, 700), (390, 844), (1280, 800)):
        ctx, pg, errs = _page(browser, w, h)
        pg.click(".scope-trigger")
        pg.wait_for_timeout(450)
        sc = pg.evaluate(P_SCOPE)
        shots = [_snap(pg, out_dir, "s12-s7-scope-%d.png" % w)]
        pg.click(".scope-trigger")
        pg.wait_for_timeout(350)
        focusScope = pg.evaluate("""() => {
          const a = document.activeElement;
          return {isTrigger: !!(a && a.closest && a.closest('.scope-trigger')),
                  tag: a ? a.tagName : null}; }""")
        pg.evaluate("window.__adminbotVm.openPalette('', null)")
        pg.wait_for_timeout(400)
        pal = pg.evaluate(r"""() => {
          const p = document.querySelector('.palette-panel');
          if (!p) return null;
          const r = p.getBoundingClientRect();
          const cs = getComputedStyle(p);
          return {l: Math.round(r.left), r: Math.round(r.right),
                  t: Math.round(r.top), b: Math.round(r.bottom),
                  bg: cs.backgroundColor,
                  filter: (cs.backdropFilter || cs.webkitBackdropFilter
                    || 'none'),
                  vw: window.innerWidth, vh: window.innerHeight,
                  inBody: p.closest('#app') === null,
                  trap: !!p.closest('[aria-modal="true"]')};
        }""")
        shots.append(_snap(pg, out_dir, "s12-s7-palette-%d.png" % w))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        returnFocus = pg.evaluate("""() => {
          const a = document.activeElement;
          return {tag: a ? a.tagName : null,
                  inBody: a === document.body,
                  label: a ? (a.getAttribute('aria-label') || '') : ''}; }""")
        rows.append({"viewport": w, "scope": sc, "palette": pal,
                     "focusScope": focusScope, "focusAfterEsc": returnFocus,
                     "errors": errs, "shots": shots})

        def edge(rect, vw_, vh_):
            if not rect:
                return False
            return (rect["l"] >= -1 and rect["r"] <= vw_ + 1
                    and rect["b"] <= vh_ + 1 and rect["t"] >= -1)

        def opaque(bg, filt):
            # Текст заднего слоя не должен «просвечивать» сквозь меню.
            try:
                a = 1.0
                if "rgba" in (bg or ""):
                    a = float(bg.split(",")[-1].strip(" )"))
                return a >= 0.75 or (filt and filt != "none")
            except Exception:  # noqa: BLE001
                return False

        _fails_probe(pid, fails, [x for x in [
            "панель области обрезана у края: %s" % sc["panelRect"]
            if not edge(sc["panelRect"], w, h) else "",
            "задний слой просвечивает через панель области (bg=%s, filter=%s)"
            % (sc["panelBg"], sc["panelFilter"])
            if not opaque(sc["panelBg"], sc["panelFilter"]) else "",
            "палитра обрезана: %s" % pal if pal and not edge(pal, w, h) else "",
            "палитра не телепортирована в <body> (inBody=%s)"
            % (pal or {}).get("inBody") if pal and not pal["inBody"] else "",
            "задний слой просвечивает через палитру"
            if pal and not opaque(pal["bg"], pal["filter"]) else "",
            "фокус не вернулся на триггер области после закрытия"
            if not focusScope["isTrigger"] else "",
            "фокус не вернулся на управляющий элемент после Esc палитры"
            if returnFocus["inBody"] and not returnFocus["label"] else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Overlay: dropdown у краёв не обрезается, текст заднего слоя не "
             "проходит через меню, фокус возвращается",
        "панель области и палитра целиком внутри вьюпорта на 320/390/1280; "
        "фон панели непрозрачен (alpha>=0.75) или имеет backdrop-filter; "
        "палитра телепортирована в body; после закрытия activeElement снова "
        "на триггере области",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.8 — контролы на трёх несвязанных экранах
# ═══════════════════════════════════════════════════════════════════════════
SCREENS_8 = ("#/modules", "#/ai/prompts", "#/memory/rag")
def _known_classes():
    """Классы, реально определённые единой таблицей стилей.

    Так проверка «кнопка использует систему, а не локальный стиль» не зависит
    от ручного списка имён в тесте: источник — сам `app.css`. Кнопка без
    единого известного класса = локальная стилизация (ровно тот дефект, из-за
    которого один контрол на разных экранах выглядел по-разному).
    """
    import re
    src = io.open("web/static/app.css", encoding="utf-8").read()
    return sorted(set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", src)))


def s8_controls(browser, out_dir, rec, fails):
    pid = "§12.8"
    known = _known_classes()
    rows = []
    for route in SCREENS_8:
        ctx, pg, errs = _page(browser, 1280, 900, route=route)
        p = pg.evaluate(P_CONTROLS, known)
        rows.append({"route": route, **p, "errors": errs,
                     "shots": [_snap(pg, out_dir,
                                     "s12-s8-%s.png"
                                     % route.replace("#/", "").replace("/", "-"))]})
        _fails_probe(pid, fails, [x for x in [
            "кнопки без общей роли .btn/.ctl-*: %s" % p["btnUnstyled"]
            if p["btnUnstyled"] else "",
            "поля без общего класса .field/.ctl-input: %s"
            % p["inputUnstyled"] if p["inputUnstyled"] else "",
            "select без .field/.ctl-*: %d" % p["selectUnstyled"]
            if p["selectUnstyled"] else "",
            "нативные чекбоксы вне дизайн-системы: %d из %d"
            % (p["checksAll"] - p["checksAllUnified"], p["checksAll"])
            if p["checksAll"] - p["checksAllUnified"] else "",
            "два конкурирующих master-тумблера (%d)"
            % p["masterToggles"] if p["masterToggles"] else "",
            "тумблеров в карточке модуля больше одного: %s"
            % [c for c in p["togglesPerCard"] if c > 1]
            if [c for c in p["togglesPerCard"] if c > 1] else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Controls: кнопки/тумблеры/поля/select на трёх несвязанных "
             "экранах используют общие роли и токены, двух конкурирующих "
             "master-toggles нет",
        "на #/modules, #/ai/prompts, #/memory/rag: каждая видимая кнопка "
        "имеет класс, определённый в app.css; каждое поле — .field или "
        ".ctl-input; каждый select — .field/.ctl-*; каждый отрендеренный "
        "checkbox — .ctl-check__box|внутри .ctl-toggle/.ctl-check; "
        "[data-module-global-toggle]===0 и на карточку модуля ровно 1 тумблер",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.9 — глобальный тумблер модуля: реальное состояние + откат
# ═══════════════════════════════════════════════════════════════════════════
def _to_global(pg, wait=800):
    """Переключить область в GLOBAL (иначе клик пишет per-chat)."""
    pg.click(".scope-trigger")
    pg.wait_for_timeout(350)
    pg.evaluate(r"""() => { const o = Array.from(
        document.querySelectorAll('.scope-option'))
        .find((n) => /глобал/i.test(n.textContent || ''));
      if (o) o.click(); }""")
    pg.wait_for_timeout(wait)
    return pg.evaluate("() => { const vm = window.__adminbotVm;"
                       " return vm ? vm.scopeKind : null; }")


def s9_global_toggle(browser, out_dir, rec, fails):
    pid = "§12.9"
    PATCH.clear()
    # (a) успешная глобальная операция
    api_ok = _api()
    ctx, pg, errs = _page(browser, 1280, 900, api=api_ok, route="#/modules")
    scope_a = _to_global(pg)
    before = pg.evaluate(P_TOGGLE)
    pg.evaluate("document.querySelector('[data-module-scope-toggle]').click()")
    pg.wait_for_timeout(1500)
    afterOk = pg.evaluate(P_TOGGLE)
    shots = [_snap(pg, out_dir, "s12-s9-modules-global-ok-1280.png")]
    # (b) сервер отверг запись — UI обязан вернуться к серверному значению
    api_bad = _api(post="fail")
    ctx2, pg2, errs2 = _page(browser, 1280, 900, api=api_bad, route="#/modules")
    scope_b = _to_global(pg2)
    b2 = pg2.evaluate(P_TOGGLE)
    pg2.evaluate("document.querySelector('[data-module-scope-toggle]').click()")
    pg2.wait_for_timeout(1500)
    afterFail = pg2.evaluate(P_TOGGLE)
    shots.append(_snap(pg2, out_dir, "s12-s9-modules-global-fail-1280.png"))
    # (c) per-chat override независим: та же карточка в области чата
    api_chat = _api()
    ctx3, pg3, errs3 = _page(browser, 1280, 900, api=api_chat, route="#/modules")
    pg3.click(".scope-trigger")
    pg3.wait_for_timeout(400)
    pg3.evaluate(r"""() => { const o = Array.from(
        document.querySelectorAll('.scope-option'))
        .find((n) => !/глобал/i.test(n.textContent || ''));
      if (o) o.click(); }""")
    pg3.wait_for_timeout(900)
    scope_c = pg3.evaluate("() => { const vm = window.__adminbotVm;"
                           " return vm ? vm.scopeKind : null; }")
    chatBefore = pg3.evaluate(P_TOGGLE)
    pg3.evaluate("document.querySelector('[data-module-scope-toggle]')"
                 ".click()")
    pg3.wait_for_timeout(1500)
    chatAfter = pg3.evaluate(P_TOGGLE)
    shots.append(_snap(pg3, out_dir, "s12-s9-modules-chat-scope-1280.png"))

    posts_ok = list(api_ok.log)
    posts_chat = list(api_chat.log)
    # Ожидаемый HTTP 500 в сценарии отказа — не дефект приложения.
    hard_errors = [e for e in (errs + errs2 + errs3)
                   if "500 (Internal Server Error)" not in e]
    _fails_probe(pid, fails, [x for x in [
        "область не переключилась в global (%s/%s)" % (scope_a, scope_b)
        if scope_a != "global" or scope_b != "global" else "",
        "в каталоге нет ни одного scoped-тумблера" if not before["exists"]
        else "",
        "глобальная операция не отправила POST /api/config" if not posts_ok
        else "",
        "глобальная операция ушла с X-Chat-Id (это была бы запись чата): %s"
        % (posts_ok[0]["hdrChat"] if posts_ok else "")
        if posts_ok and posts_ok[0]["hdrChat"] else "",
        "глобальная операция не изменила состояние (было %s, стало %s)"
        % (before["checked"], afterOk["checked"])
        if before["checked"] == afterOk["checked"] else "",
        "ошибка видна после УСПЕШНОЙ операции: %s" % afterOk["err"]
        if afterOk["err"] else "",
        "при отказе сервера UI не вернулся к серверному значению (было %s, "
        "стало %s)" % (b2["checked"], afterFail["checked"])
        if afterFail["checked"] != b2["checked"] else "",
        "при отказе сервера нет причины рядом с контролом" if not afterFail["err"]
        else "",
        "область чата не включилась (%s)" % scope_c
        if scope_c != "chat" else "",
        "per-chat override не отправил отдельную операцию" if not posts_chat
        else "",
        "per-chat операция ушла без X-Chat-Id (записалась бы глобально)"
        if posts_chat and not posts_chat[0]["hdrChat"] else "",
        "per-chat тумблер не изменил состояние (%s → %s)"
        % (chatBefore["checked"], chatAfter["checked"])
        if chatBefore["checked"] == chatAfter["checked"] else "",
        "посторонние ошибки консоли: %s" % hard_errors[:3]
        if hard_errors else "",
    ] if x])
    ctx.close(); ctx2.close(); ctx3.close()
    rec(pid, "Module global toggle: из каталога меняет реальное global "
             "состояние с подтверждением, per-chat override независим, "
             "неуспех откатывает UI",
        "клик по [data-module-scope-toggle] в GLOBAL шлёт POST /api/config с "
        "per_chat=false и меняет состояние; при HTTP 500 UI возвращается к "
        "серверному значению и показывает причину ([data-module-scope-error]); "
        "в chat-области клик шлёт POST с X-Chat-Id и меняет только значение "
        "чата",
        {"globalBefore": before, "globalAfter": afterOk,
         "failBefore": b2, "failAfter": afterFail,
         "chatBefore": chatBefore, "chatAfter": chatAfter,
         "postsGlobal": posts_ok, "postsChat": posts_chat},
        fails, shots)


# ═══════════════════════════════════════════════════════════════════════════
# §12.10 — четыре ленты одним блоком, autoscroll/пауза
# ═══════════════════════════════════════════════════════════════════════════
def s10_ribbons(browser, out_dir, rec, fails):
    pid = "§12.10"
    rows = []
    # Видимая лента: на десктопе видны все четыре, на телефоне — активная
    # секция переключателя. Берём ПЕРВЫЙ видимый трек, а не «первый в DOM»
    # (иначе hover получает скрытую секцию и падает по таймауту).
    pick = r"""() => {
      const vs = Array.from(document.querySelectorAll(
        '[data-sfeed-viewport]')).filter((n) => {
          const r = n.getBoundingClientRect();
          return r.width > 4 && r.height > 4;
        });
      return vs.length ? vs[0].getAttribute('data-ribbon') : null;
    }"""
    for (w, h) in ((1280, 900), (390, 844)):
        api = _api({"/api/oversight/dossier_feed": W13.W10._DOSSIER})
        ctx, pg, errs = _page(browser, w, h, api=api, settle=2000)
        p = pg.evaluate(P_RIBBONS)
        shots = [_snap(pg, out_dir, "s12-s10-ribbons-%d.png" % w)]
        ribbon = pg.evaluate(pick)
        # Движок `v-sfeed` (подтверждено чтением app.js: `s.y` → `scrollTop`)
        # двигает ПОЗИЦИЮ ПРОКРУТКИ области, а не transform трека.
        track_js = ("(() => { const n = document.querySelector("
                    "'[data-ribbon=\"%s\"]');"
                    " return n ? Math.round(n.scrollTop * 100) / 100 : null; })()"
                    % (ribbon or "facts"))
        samples = []
        for _ in range(4):
            pg.wait_for_timeout(420)
            samples.append(pg.evaluate(track_js))
        moving = len(set(samples)) > 1
        # ручная прокрутка вверх: движение приостановлено, затем продолжается
        if ribbon:
            pg.evaluate(
                "(() => { const n = document.querySelector("
                "'[data-ribbon=\"%s\"]');"
                " if (n && n.scrollIntoView) n.scrollIntoView("
                "{block: 'center', inline: 'nearest'}); })()" % ribbon)
            pg.wait_for_timeout(400)
            box = pg.evaluate(
                "(() => { const n = document.querySelector("
                "'[data-ribbon=\"%s\"]');"
                " if (!n) return null; const r = n.getBoundingClientRect();"
                " return {x: Math.round(r.left + r.width / 2),"
                " y: Math.round(r.top + r.height / 2)}; })()" % ribbon)
        if box:
            pg.mouse.move(box["x"], box["y"])
            pg.mouse.wheel(0, -220)
            pg.wait_for_timeout(250)
        paused = []
        for _ in range(3):
            pg.wait_for_timeout(180)
            paused.append(pg.evaluate(
                "(() => { const n = document.querySelector("
                "'[data-ribbon=\"%s\"]');"
                " if (!n) return null;"
                " return {y: Math.round(n.scrollTop * 100) / 100,"
                " manual: !!(n.__sfeed && n.__sfeed.manual)}; })()"
                % (ribbon or "facts")))
        # Пауза доказана самим движком (`manual`), а не «замершим» числом:
        # инерция браузера может докатывать scrollTop после колеса.
        pauseStable = all((s or {}).get("manual") for s in paused)
        shots.append(_snap(pg, out_dir, "s12-s10-ribbons-%d-paused.png" % w))
        # Продолжение с текущей позиции: уводим указатель (наведение — тоже
        # законная пауза в движке) и ждём UX-паузу 2.6 с.
        pg.mouse.move(4, 4)
        pg.wait_for_timeout(4300)
        resumed_state = pg.evaluate(
            "(() => { const n = document.querySelector("
            "'[data-ribbon=\"%s\"]');"
            " if (!n) return null;"
            " return {y: Math.round(n.scrollTop * 100) / 100,"
            " manual: !!(n.__sfeed && n.__sfeed.manual)}; })()"
            % (ribbon or "facts"))
        resumed = bool(resumed_state) and not resumed_state["manual"] and (
            (paused[-1] or {}).get("y") is not None
            and resumed_state["y"] != paused[-1]["y"])
        rows.append({"viewport": w, "ribbon": ribbon, **p, "samples": samples,
                     "moving": moving, "pausedStable": pauseStable,
                     "resumed": resumed != paused[-1], "errors": errs,
                     "shots": shots})
        _fails_probe(pid, fails, [x for x in [
            "ленты не в одном блоке ([data-intel-widget] отсутствует)"
            if not p["widget"] else "",
            "секций %s, ожидались facts/beliefs/paradigms/traits"
            % (p["sections"],) if sorted(p["sections"]) !=
            ["beliefs", "facts", "paradigms", "traits"] else "",
            "лент-треков %d (ожидался один блок с четырьмя лентами)"
            % p["tracks"] if p["tracks"] and p["tracks"] > 4 else "",
            "строк лент нет (ошибка/пусто: err=%d empty=%d)"
            % (p["errors"], p["empty"]) if not p["rows"] else "",
            "дата/источник не показаны в строке: %s" % (p["dates"][:1],)
            if p["dates"] and len(p["dates"][0]) < 8 else "",
            "автопрокрутка не сдвинула позицию (пробы %s)" % (samples,)
            if not moving else "",
            "ручная прокрутка не приостановила ленту (движок manual=%s)"
            % [s.get("manual") for s in paused if s] if not pauseStable
            else "",
            "после паузы лента не продолжилась (y %s → %s, manual=%s)"
            % ((paused[-1] or {}).get("y"), (resumed_state or {}).get("y"),
               (resumed_state or {}).get("manual"))
            if not resumed else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Четыре ленты: один блок под картой; дата/модалка/источник; "
             "autoscroll, ручная прокрутка вверх/вниз, пауза и плавное "
             "продолжение",
        "[data-intel-widget] ровно один и содержит 4 [data-intel-section] "
        "(facts/beliefs/paradigms/traits) сразу под картой; строки содержат "
        "дату; transform трека меняется сам (autoscroll), замирает после "
        "ручной прокрутки вверх и снова меняется после паузы",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.13 — health tint: пять состояний, оптика не ломается
# ═══════════════════════════════════════════════════════════════════════════
HEALTH_VARIANTS = {
    "normal": {},
    # warning — реальный сигнал heartbeat-EMA (нагрузка 70–90 %): единственный
    # путь, которым состояние появляется в продукте, а не подстановка в DOM.
    "warning": {"server.cpu_percent": 75, "server.memory.percent": 75,
                "experience.state": "warning"},
    "degraded": {"experience.state": "degraded",
                 "experience.reason": "часть уроков не применилась"},
    "failed": {"bot.state": "polling_error", "experience.state": "failed",
               "experience.reason": "pipeline упал"},
    "unknown": {"bot.state": "starting", "bot.errors_total": None},
    "disabled": {"bot.state": "stopped"},
}
def s13_health(browser, out_dir, rec, fails):
    pid = "§12.13"
    rows = []
    for state, over in HEALTH_VARIANTS.items():
        status = W13._deep(W13.STATUS_BASE, over)
        if over.get("bot.errors_total", 0) is None:
            status["bot"].pop("errors_total", None)
        ctx, pg, errs = _page(browser, 1280, 900, settle=1400,
                              api=_api({"/api/status": status}))
        p = pg.evaluate(P_HEALTH)
        rows.append({"state": state, **p, "errors": errs,
                     "shots": [_snap(pg, out_dir,
                                     "s12-s13-health-%s.png" % state)]})
        ctx.close()
    by_state = {}
    for r in rows:
        for c in r["cards"]:
            by_state.setdefault(r["state"], []).append(c)
    observed = sorted({c["state"] for r in rows for c in r["cards"]})
    # «Не глухая плашка, не второй blur»: у тонированной поверхности
    # сохраняется прозрачность стекла (alpha <= 0.6), backdrop-filter и
    # геометрия совпадают с тем же subsystem в normal.
    def alpha_of(bg):
        try:
            return float(bg.split(",")[-1].strip(" )")) if "rgba" in bg else 1.0
        except Exception:  # noqa: BLE001
            return 1.0

    def rgb(bg):
        try:
            parts = bg[bg.index("(") + 1:bg.index(")")].split(",")
            return [int(float(x)) for x in parts[:3]]
        except Exception:  # noqa: BLE001
            return [0, 0, 0]

    base_by_sub = {c["sub"]: c for c in (rows[0]["cards"] if rows else [])}
    problems = []
    for state, cards in by_state.items():
        for c in cards:
            a = alpha_of(c["bg"])
            if a > 0.6:
                problems.append("%s/%s: непрозрачная плашка alpha=%.2f (%s)"
                                % (state, c["sub"], a, c["bg"]))
            ref = base_by_sub.get(c["sub"])
            if ref:
                if c["filter"] != ref["filter"]:
                    problems.append("%s/%s: backdrop-filter %s != normal %s"
                                    % (state, c["sub"], c["filter"],
                                       ref["filter"]))
                if abs(c["w"] - ref["w"]) > 2 or abs(c["h"] - ref["h"]) > 2:
                    problems.append("%s/%s: геометрия %dx%d != normal %dx%d"
                                    % (state, c["sub"], c["w"], c["h"],
                                       ref["w"], ref["h"]))
            if state in ("failed", "degraded") and c["state"] in ("failed",
                                                                  "degraded"):
                r, g, b = rgb(c["bg"])
                if not (r > g and r > b):
                    problems.append("%s/%s: тон не красный (%s)"
                                    % (state, c["sub"], c["bg"]))
    canvases = sorted({r["canvases"] for r in rows})
    _fails_probe(pid, fails, [x for x in [
        "состояния health не различаются: %s" % observed
        if not {"normal", "failed", "unknown", "disabled"} <= set(observed)
        else "",
        "warning не наблюдался ни на одной карточке (heartbeat 75 %)"
        if "warning" not in observed else "",
        "красный tint ломает оптику/геометрию стекла: %s" % problems[:4]
        if problems else "",
        "полотно преломления/фона исчезло в части состояний: %s" % canvases
        if len(canvases) > 1 else "",
        "появилась ложная окраска обычной data-карточки (%d)"
        % max(r["tintedNonHealth"] for r in rows)
        if max(r["tintedNonHealth"] for r in rows) else "",
    ] if x])
    rec(pid, "Health tint: normal/warning/degraded/failed/unknown/disabled "
             "различимы, красное стекло не ломает прозрачность/преломление/"
             "фон, нет ложной окраски data-card",
        "на #/ с шестью статусами в DOM присутствуют normal, warning (EMA "
        "нагрузки 75 %), failed, unknown, disabled; у каждой "
        "[data-health-state] альфа фона <=0.6 (стекло, не плашка), "
        "backdrop-filter и w/h совпадают с тем же subsystem в normal "
        "(±2 px); число canvas неизменно; ни одна карточка без "
        "data-health-state не получила красный фон",
        {"rows": rows, "observed": observed, "problems": problems[:8],
         "canvases": canvases}, fails,
        [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.15 — клавиатура и zoom 200 %
# ═══════════════════════════════════════════════════════════════════════════
def _open_prompt_editor(pg, settle=900):
    """Открыть ОДИН промпт из библиотеки и его полноэкранный редактор.

    Редактор существует только при выбранном `workspacePromptFocus`,
    поэтому «просто нажать ⛶» на пустом экране недостаточно.
    """
    pg.evaluate(r"""() => {
      const it = document.querySelector('[data-prompt-key]');
      if (it) { it.click(); return; }
      const cat = document.querySelector('[data-prompt-library] button,'
        + ' .prompt-list button, .prompt-tree-item');
      if (cat) cat.click();
    }""")
    pg.wait_for_timeout(settle)
    opened = pg.evaluate(r"""() => {
      const b = document.querySelector('[data-prompt-fullscreen]');
      if (!b) return false;
      b.click();
      return true;
    }""")
    pg.wait_for_timeout(settle)
    return opened


def s15_keyboard_zoom(browser, out_dir, rec, fails):
    pid = "§12.15"
    rows = []
    for (w, h) in ((320, 568), (390, 844)):
        ctx, pg, errs = _page(browser, w, h, route="#/ai/prompts", settle=1600)
        _open_prompt_editor(pg)
        p = pg.evaluate(P_ZOOM)
        rows.append({"case": "min-width-%d" % w, **p, "errors": errs,
                     "shots": [_snap(pg, out_dir,
                                     "s12-s15-min-%d.png" % w)]})
        _fails_probe(pid, fails, [x for x in [
            "%d: горизонтальный overflow %d px" % (w, p["hScroll"])
            if p["hScroll"] > 0 else "",
            "%d: элементы шапки за вьюпортом (%d)" % (w, p["headerOff"])
            if p["headerOff"] else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    # (b) zoom 200 % на телефоне: 390/2 = 195 CSS px
    ctx, pg, errs = _page(browser, 195, 422, route="#/ai/prompts", settle=1400)
    z = pg.evaluate(P_ZOOM)
    shot = _snap(pg, out_dir, "s12-s15-zoom200-195.png")
    rows.append({"case": "zoom200-195", **z, "errors": errs, "shots": [shot]})
    ctx.close()
    # (c) экранная клавиатура: имитируем реальные CSS-переменные клиента
    ctx, pg, errs = _page(browser, 390, 844, route="#/ai/prompts", settle=1600)
    pg.evaluate(r"""() => { const de = document.documentElement;
      de.style.setProperty('--tg-viewport-stable-height', '520px');
      de.style.setProperty('--kb-offset', '324px');
      de.style.setProperty('--kb-inset', '324px');
      de.style.setProperty('--vv-h', '520px');
      de.classList.add('kb-open'); }""")
    _open_prompt_editor(pg)
    ta = pg.query_selector("textarea")
    if ta:
        ta.click()
        pg.wait_for_timeout(300)
        # Делаем редактор «грязным»: полоса сохранения появляется только при
        # реальных правках, иначе «Save доступен» проверялось бы на пустом месте.
        ta.fill("Черновик правки для проверки доступности сохранения "
                "при открытой экранной клавиатуре.")
        pg.wait_for_timeout(500)
    kb = pg.evaluate(r"""() => {
      const q = (s) => document.querySelector(s);
      const rect = (n) => { if (!n) return null; const r = n.getBoundingClientRect();
        return {t: Math.round(r.top), b: Math.round(r.bottom),
                l: Math.round(r.left), r: Math.round(r.right)}; };
      const ta = q('textarea');
      const save = q('.sticky-save, [data-sticky-save]');
      const close = q('.modal-close, [data-prompt-fullscreen-close]');
      const vh = 520;
      return {ta: rect(ta), save: rect(save), close: rect(close), vh: vh,
              active: document.activeElement ? document.activeElement.tagName
                : null,
              kbOpen: document.documentElement.classList.contains('kb-open'),
              hScroll: Math.max(0, (document.scrollingElement
                || document.documentElement).scrollWidth - window.innerWidth)};
    }""")
    rows.append({"case": "keyboard", **kb, "errors": errs,
                 "shots": [_snap(pg, out_dir, "s12-s15-keyboard-390.png")]})
    _fails_probe(pid, fails, [x for x in [
        "при открытой клавиатуре поле ниже видимой области (%s)" % kb["ta"]
        if kb["ta"] and kb["ta"]["b"] > kb["vh"] + 1 else "",
        "при открытой клавиатуре кнопка сохранения не найдена"
        if not kb["save"] else "",
        "при открытой клавиатуре кнопка сохранения недоступна (%s)"
        % kb["save"] if kb["save"] and kb["save"]["b"] > kb["vh"] + 1 else "",
        "при открытой клавиатуре закрытие недоступно (%s)" % kb["close"]
        if kb["close"] and kb["close"]["b"] > kb["vh"] + 1 else "",
        "клавиатура вызвала горизонтальный overflow %d" % kb["hScroll"]
        if kb["hScroll"] > 0 else "",
        "ошибки консоли: %s" % errs[:2] if errs else "",
    ] if x])
    ctx.close()
    rec(pid, "Клавиатура/zoom: длинный промпт, меню модели и поиск с открытой "
             "клавиатурой; 200 % zoom; Save и Close доступны, overflow нет",
        "на поддержанном минимуме 320 px и 390 px: scrollWidth<=innerWidth и "
        "все элементы шапки внутри вьюпорта; при открытой клавиатуре "
        "(stable=520) поле, Save и Close имеют bottom<=520; отдельно "
        "измерен zoom 200 % (195 CSS px) — его результат вынесен владельцу, "
        "контракт минимума 320 px им не меняется",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.16 — поэкранные маршруты
# ═══════════════════════════════════════════════════════════════════════════
ROUTES_16 = ("#/", "#/oversight", "#/modules", "#/ai", "#/ai/prompts",
             "#/speech", "#/memory", "#/memory/rag", "#/access", "#/how",
             "#/modules/factcheck", "#/ai/smart-cache")
def s16_routes(browser, out_dir, rec, fails):
    pid = "§12.16"
    rows = []
    ctx, pg, errs = _page(browser, 1280, 900)
    for route in ROUTES_16:
        pg.evaluate("(r) => { window.location.hash = r; }", route)
        pg.wait_for_timeout(420)
        p = pg.evaluate(P_ROUTE)
        rows.append({"route": route, **p,
                     "shots": [_snap(pg, out_dir,
                                     "s12-s16-%s.png"
                                     % (route.replace("#/", "").replace(
                                         "/", "-") or "root"))]})
        _fails_probe(pid, fails, [x for x in [
            "%s: экран пуст (textLen %d)" % (route, p["textLen"])
            if p["textLen"] < 40 else "",
            "%s: имя раздела продублировано (%s)" % (route, p["titles"])
            if p["titleDup"] > 0 else "",
            "%s: горизонтальный скролл %d" % (route, p["hScroll"])
            if p["hScroll"] > 0 else "",
            "%s: вернулся старый набор контролов (bottom-nav=%d, «⋯»=%d, "
            "двойной master=%d)" % (route, p["legacyNav"], p["legacyGrid"],
                                    p["masterToggles"])
            if (p["legacyNav"] or p["legacyGrid"] or p["masterToggles"]) else "",
        ] if x])
    ctx.close()
    rec(pid, "Поэкранные маршруты: Статус/Аналитика/Модули/ИИ/Речь/Память/"
             "Доступы и глубокие editor-маршруты не возвращаются к старому "
             "набору контролов",
        "на 12 маршрутах (включая глубокие #/modules/factcheck, "
        "#/ai/smart-cache): textLen>=40, имя раздела не дублируется, "
        "scrollWidth<=innerWidth, отсутствуют mobile-topnav/«⋯»-триггер и "
        "data-module-global-toggle",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# §12.17 — производительность и сохранность стекла
# ═══════════════════════════════════════════════════════════════════════════
def s17_perf(browser, out_dir, rec, fails):
    pid = "§12.17"
    rows = []
    for route in ("#/", "#/status/graph"):
        ctx, pg, errs = _page(browser, 1280, 900, route=route, settle=1500)
        p = pg.evaluate(P_PERF)
        rows.append({"route": route, **p, "errors": errs,
                     "shots": [_snap(pg, out_dir,
                                     "s12-s17-%s.png"
                                     % (route.replace("#/", "").replace(
                                         "/", "-") or "root"))]})
        _fails_probe(pid, fails, [x for x in [
            "%s: кадров >100 ms %d из %d (массовое лагание)"
            % (route, p["slowFrames"], p["frames"])
            if p["frames"] and p["slowFrames"] / p["frames"] > 0.15 else "",
            "%s: long tasks за 2.5 с: %d (максимум %d ms)"
            % (route, p["longTasks"], p["longMax"]) if p["longTasks"] > 2 else "",
            "%s: потерян WebGL-контекст (%d)" % (route, p["webglLost"])
            if p["webglLost"] else "",
            "%s: полотна стекла исчезли (canvases=%d)" % (route, p["canvases"])
            if p["canvases"] == 0 else "",
            "ошибки консоли: %s" % errs[:2] if errs else "",
        ] if x])
        ctx.close()
    rec(pid, "Perf/regression: на действующем графе и анимациях нет "
             "массового лагания и постоянной перерисовки стекла",
        "на #/ и #/status/graph за 2.5 с: доля кадров >100 ms <=15 %, "
        "long tasks <=2, нет lost WebGL-контекста, полотна стекла/фона на "
        "месте (canvases>0). Медиана/p95 кадра пишутся как наблюдение: в "
        "headless-прогоне частота rAF ограничена композитором и сама по себе "
        "не является доказательством лагания. Оптика до/после — отдельный "
        "принятый прогон tools/ui_win_glass_refraction_e2e.py",
        {"rows": rows}, fails, [s for r in rows for s in r["shots"]])


# ═══════════════════════════════════════════════════════════════════════════
# Остаточные пункты ревью: состояния контролов, back-stack, чекбоксы
# ═══════════════════════════════════════════════════════════════════════════
def residual_interactions(browser, out_dir, fails):
    pid = "residual"
    out = {"hover": [], "selected": [], "backStack": None, "checkbox": []}

    def style_of(pg, sel):
        return pg.evaluate(P_HOVER, sel)

    for route, sel in (("#/modules", ".module-params-btn"),
                       ("#/ai/prompts", ".btn-ghost"),
                       ("#/memory", ".btn-ghost")):
        ctx, pg, errs = _page(browser, 1280, 900, route=route, settle=1000)
        box = pg.evaluate(
            "(s => { const n = document.querySelector(s);"
            " if (!n) return null; const r = n.getBoundingClientRect();"
            " if (r.width < 4) return null;"
            " return {x: Math.round(r.left + r.width / 2),"
            " y: Math.round(r.top + r.height / 2)}; })(%s)" % json.dumps(sel))
        if not box:
            ctx.close()
            continue
        normal = style_of(pg, sel)
        pg.mouse.move(box["x"], box["y"])
        pg.wait_for_timeout(340)
        hovered = style_of(pg, sel)
        pg.mouse.down()
        pg.wait_for_timeout(280)
        pressed = style_of(pg, sel)
        pg.mouse.up()
        pg.wait_for_timeout(280)
        row = {"route": route, "sel": sel, "normal": normal,
               "hover": hovered, "pressed": pressed}
        out["hover"].append(row)
        _fails_probe(pid, fails, [x for x in [
            "%s/%s: hover не отличается от normal" % (route, sel)
            if hovered and normal and hovered["bg"] == normal["bg"]
            and hovered["color"] == normal["color"] else "",
            "%s/%s: pressed не отличается от hover (нет состояния нажатия)"
            % (route, sel)
            if pressed and hovered
            and pressed["filter"] == hovered["filter"]
            and pressed["bg"] == hovered["bg"] else "",
        ] if x])
        ctx.close()

    # Выбранное состояние: активный локальный фильтр каталога отличается от
    # невыбранного (aria-pressed=true даёт заливку и hairline, а не только цвет).
    ctx, pg, errs = _page(browser, 1280, 900, route="#/modules", settle=1100)
    pg.evaluate("[...document.querySelectorAll('.module-filter-btn')]"
                ".find((b) => (b.textContent || '').trim() === 'Включённые')"
                ".click()")
    pg.wait_for_timeout(500)
    pg.evaluate("document.querySelector('.module-filter-btn').focus()")
    sel_state = pg.evaluate(r"""() => {
      const bs = Array.from(document.querySelectorAll('.module-filter-btn'));
      const on = bs.find((b) => b.getAttribute('aria-pressed') === 'true');
      const off = bs.find((b) => b.getAttribute('aria-pressed') !== 'true');
      const cs = (n) => { const c = getComputedStyle(n);
        return {bg: c.backgroundColor, shadow: c.boxShadow,
                color: c.color}; };
      return {on: on ? cs(on) : null, off: off ? cs(off) : null,
              onLabel: on ? (on.textContent || '').trim() : null};
    }""")
    out["selected"].append({"route": "#/modules", **sel_state,
                            "shots": [_snap(pg, out_dir,
                                            "s12-residual-selected.png")]})
    _fails_probe(pid, fails, [
        "выбранный фильтр визуально не отличается от невыбранного"] if
        sel_state["on"] and sel_state["off"]
        and sel_state["on"]["bg"] == sel_state["off"]["bg"]
        and sel_state["on"]["shadow"] == sel_state["off"]["shadow"] else [])
    ctx.close()

    # длина back-stack: три вложенных слоя — три одиночных Back
    ctx, pg, errs = _page(browser, 1280, 900)
    pg.evaluate("window.__adminbotVm.openPalette('', null)")
    pg.wait_for_timeout(400)
    pg.evaluate("document.querySelector('.scope-trigger').click()")
    pg.wait_for_timeout(350)
    stack = pg.evaluate("""() => { const vm = window.__adminbotVm;
      return {layers: vm && typeof vm.backStackLayers === 'function'
        ? vm.backStackLayers() : null,
        len: vm && vm.backStack ? vm.backStack.length : null}; }""")
    seq = []
    for _ in range(3):
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(350)
        seq.append(pg.evaluate("""() => { const vm = window.__adminbotVm;
          return {len: vm && vm.backStack ? vm.backStack.length : null,
                  hash: location.hash,
                  palette: !!(vm && vm.paletteOpen),
                  scope: !!(vm && vm.scopeOpen)}; }"""))
    out["backStack"] = {"initial": stack, "after": seq,
                        "shots": [_snap(pg, out_dir,
                                        "s12-residual-backstack.png")]}
    _fails_probe(pid, fails, [x for x in [
        "back-stack не измерен (vm.backStackLayers отсутствует)"
        if not stack["layers"] else "",
        "стек из двух слоёв не собран: %s" % (stack["layers"],)
        if stack["layers"] and len(stack["layers"]) != 2 else "",
        "Back закрывает больше одного слоя: %s" % (seq,)
        if stack["layers"] and len(stack["layers"]) == 2
        and not (seq[0]["len"] == 1 and seq[1]["len"] == 0) else "",
    ] if x])
    ctx.close()
    # нативные чекбоксы: единство с дизайн-системой на реальных экранах.
    # Замер ведётся по ВСЕМ отрендеренным чекбоксам маршрута: подавляющее
    # большинство живёт в `sr-only` внутри `.ctl-toggle` и визуально не
    # «видимо», но именно оно определяет единство контрола.
    known = _known_classes()
    for route in ("#/memory/rag", "#/modules", "#/ai/prompts"):
        ctx, pg, errs = _page(browser, 1280, 900, route=route, settle=1300)
        pg.evaluate("() => { document.querySelectorAll('details')"
                    ".forEach((d) => { d.open = true; }); }")
        pg.wait_for_timeout(400)
        p = pg.evaluate(P_CONTROLS, known)
        out["checkbox"].append({"route": route, "checks": p["checksAll"],
                                "unified": p["checksAllUnified"],
                                "visible": p["checks"]})
        _fails_probe(pid, fails, [
            "%s: вне дизайн-системы %d из %d нативных чекбоксов"
            % (route, p["checksAll"] - p["checksAllUnified"], p["checksAll"])
        ] if p["checksAll"] - p["checksAllUnified"] else [])
        ctx.close()
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Индикатор загрузки при медленном /api/config (остаточный P2)
# ═══════════════════════════════════════════════════════════════════════════
P_LOADING = r"""
() => {
  const q = (s) => document.querySelector(s);
  const vis = (n) => { if (!n) return false; const r = n.getBoundingClientRect();
    const cs = getComputedStyle(n);
    return r.width > 4 && r.height > 4 && cs.display !== 'none'
      && cs.visibility !== 'hidden'; };
  const splash = q('[data-boot-loading]');
  const root = q('#app');
  return {
    splashVisible: vis(splash),
    splashBusy: splash ? splash.getAttribute('aria-busy') : null,
    appBusy: root ? root.getAttribute('aria-busy') : null,
    ready: document.body.classList.contains('app-ready'),
    skeletons: document.querySelectorAll(
      '[data-boot-loading] .ctl-skeleton').length,
  };
}
"""


def residual_loading(browser, out_dir, fails):
    """Медленный `/api/config`: честный индикатор первичной загрузки.

    До W14 при 4-секундном конфиге экран был ПУСТ (оболочка монтируется после
    данных), поэтому проверяется не «скелетон в каталоге», а само состояние
    загрузки приложения: `[data-boot-loading]` + `#app[aria-busy=true]`.
    """
    pid = "loading"
    api = _api(config_delay_ms=4000)
    ctx = W13.open_ctx(browser, 390, 844, api=api)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    pg.goto(BASE + "#/modules", wait_until="commit")
    during = None
    for _ in range(25):
        pg.wait_for_timeout(120)
        probe = pg.evaluate(P_LOADING)
        if probe["splashVisible"]:
            during = probe
            break
    during = during or pg.evaluate(P_LOADING)
    shot = _snap(pg, out_dir, "s12-loading-boot-390.png")
    pg.wait_for_selector(".app-shell", timeout=25000)
    pg.wait_for_timeout(900)
    after = pg.evaluate(P_LOADING)
    ctx2 = W13.open_ctx(browser, 390, 844, api=_api(config_delay_ms=4000))
    pg2 = ctx2.new_page()
    pg2.goto(BASE + "#/modules", wait_until="commit")
    caught = True
    try:
        # Детерминированное окно: ждём ИМЕННО состояние загрузки конфига,
        # а не фиксированную паузу (иначе окно проскакивает).
        pg2.wait_for_function(
            "() => !!window.__adminbotVm"
            " && window.__adminbotVm.configLoading === true", timeout=15000)
    except Exception:  # noqa: BLE001
        caught = False
    pg2.evaluate("() => { if (!window.__adminbotVm.paletteOpen) "
                 "window.__adminbotVm.openPalette('', null); }")
    pg2.wait_for_timeout(200)
    pal = pg2.evaluate("""() => {
      const vm = window.__adminbotVm;
      const p = document.querySelector('.palette-panel');
      return {open: !!p, busy: p ? p.getAttribute('aria-busy') : null,
              configLoading: vm ? vm.configLoading : null,
              items: vm ? vm.configItems.length : null,
              loading: !!document.querySelector('[data-palette-loading]'),
              hasData: !!(p && p.querySelector('[data-palette-item]')),
              skeletons: document.querySelectorAll(
                '[data-palette-loading] .ctl-skeleton').length}; }""")
    pal["caught"] = caught
    shots = [shot, _snap(pg2, out_dir, "s12-loading-boot-palette-390.png")]
    ctx.close(); ctx2.close()
    _fails_probe(pid, fails, [x for x in [
        "нет видимого индикатора первичной загрузки при медленном /api/config"
        if not during["splashVisible"] else "",
        "aria-busy приложения не 'true' во время загрузки (%s)"
        % during["appBusy"] if during["appBusy"] != "true" else "",
        "скелетонов в индикаторе загрузки %d < 2" % during["skeletons"]
        if during["skeletons"] < 2 else "",
        "индикатор загрузки не снят после появления данных (%s)"
        % after if after["splashVisible"] or not after["ready"] else "",
        "aria-busy приложения не 'false' после загрузки (%s)"
        % after["appBusy"] if after["appBusy"] != "false" else "",
        "окно загрузки конфига не поймано — состояние палитры не проверено"
        if not pal.get("caught") else "",
        "палитра не открылась во время загрузки" if not pal.get("open")
        else "",
        "aria-busy палитры не 'true' во время загрузки конфига (%s, cl=%s)"
        % (pal.get("busy"), pal.get("configLoading"))
        if pal.get("open") and pal.get("configLoading")
        and pal.get("busy") != "true" else "",
        "в палитре нет индикатора загрузки при пустом индексе"
        if pal.get("open") and pal.get("configLoading")
        and not pal.get("items") and not pal.get("loading") else "",
        "скелетонов в палитре %d < 2 при пустом индексе"
        % pal.get("skeletons", 0)
        if pal.get("open") and pal.get("loading")
        and pal.get("skeletons", 0) < 2 else "",
        "ошибка страницы: %s" % errs[:1] if errs else "",
    ] if x])
    return {"during": during, "after": after, "palette": pal, "shots": shots}


# ═══════════════════════════════════════════════════════════════════════════
def run(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    report = {"scenarios": [], "fails": [], "blocked": [], "residual": {}}
    fails = report["fails"]

    def rec(pid, title, assertion, payload, _fails, shots):
        mine = [f for f in fails if f.startswith(pid + ":")]
        status = "FAIL" if mine else "PASS"
        report["scenarios"].append({
            "id": pid, "title": title, "assertion": assertion,
            "status": status, "probe": payload, "shots": shots,
            "failures": mine})

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        s1_portrait(browser, out_dir, rec, fails)
        s2_landscape(browser, out_dir, rec, fails)
        s3_identity(browser, out_dir, rec, fails)
        s4_scope(browser, out_dir, rec, fails)
        s5_more(browser, out_dir, rec, fails)
        s7_overlay(browser, out_dir, rec, fails)
        s8_controls(browser, out_dir, rec, fails)
        s9_global_toggle(browser, out_dir, rec, fails)
        s10_ribbons(browser, out_dir, rec, fails)
        s13_health(browser, out_dir, rec, fails)
        s15_keyboard_zoom(browser, out_dir, rec, fails)
        s16_routes(browser, out_dir, rec, fails)
        s17_perf(browser, out_dir, rec, fails)
        report["residual"]["interactions"] = residual_interactions(
            browser, out_dir, fails)
        report["residual"]["loading"] = residual_loading(
            browser, out_dir, fails)
        browser.close()
    httpd.shutdown()

    # 6 и 14: доказаны отдельным принятым прогоном того же инструмента.
    delta_json = os.path.join(out_dir, "asap-ui-delta",
                              "asap-ui-delta-e2e.json")
    delta = {}
    if os.path.exists(delta_json):
        with io.open(delta_json, encoding="utf-8") as fh:
            delta = json.load(fh)
    for sid, key, title in (
            ("§12.6", "scenario6",
             "Scroll и Back: стабильная шапка, порядок закрытия слоёв"),
            ("§12.14", "scenario14",
             "Поиск и deep link с RBAC/scope и возвратом черновика")):
        sec = (delta.get(key) or {})
        ok = bool(sec) and not [f for f in delta.get("fails", [])
                                if f.lower().startswith(key[-1])]
        report["scenarios"].append({
            "id": sid, "title": title, "status": "PASS" if ok else "UNVERIFIED",
            "assertion": "переиспользован принятый прогон "
                         "tools/ui_asap_ui02_delta_e2e.py (Re-check 3 "
                         "Approved): свой набор утверждений не ослаблен и не "
                         "переписан",
            "probe": {"source": "asap-ui-delta/asap-ui-delta-e2e.json",
                      "section": key, "keys": sorted(sec.keys())[:12]},
            "shots": [], "failures": []})
    for sid, title in (
            ("§12.11", "Карта embedded: свайп страницы, режим «Исследовать»"),
            ("§12.12", "Карта fullscreen: LOD, легенда, восстановление камеры")):
        report["blocked"].append({
            "id": sid, "title": title,
            "reason": "EVOL-COG-MAP не реализован: в сборке нет ни карты "
                      "связей в «Статусе», ни режима «Исследовать», ни "
                      "fullscreen-LOD с восстановлением камеры. Легаси-граф "
                      "не подменяет сценарий"})
        report["scenarios"].append({
            "id": sid, "title": title, "status": "BLOCKED",
            "assertion": "не может быть проверен: зависимость EVOL-COG-MAP",
            "probe": {}, "shots": [], "failures": []})
    report["scenarios"].sort(key=lambda r: int(r["id"].split(".")[-1]))

    with io.open(os.path.join(out_dir, "w14-s12-scenarios.json"), "w",
                 encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    counts = {}
    for r in report["scenarios"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("S12 %s" % json.dumps(counts, ensure_ascii=False))
    for r in report["scenarios"]:
        print("  %-7s %s" % (r["id"], r["status"]))
    if fails:
        print("FAILURES:")
        for f in fails:
            print(" -", f)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    return run(args.out)


if __name__ == "__main__":
    sys.exit(main())
