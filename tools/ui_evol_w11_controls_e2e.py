"""EVOL-043/044/045 (W11) — живая проверка контролов, клавиатуры и прогресса.

Детерминированный Playwright-прогон НАСТОЯЩЕГО `web/index.html` + `web/app.js`
+ `web/static/app.css` (сервер/стабы API — из `tools/ui_round1025_matrix.py`,
секретов нет, живых сообщений в Telegram не отправляется).

Проверяется (plans/current_task.md L690–739):

  * EVOL-045 — системные/бюджетные полосы честны: подтверждённая пара
    done/total даёт determinate с единицами и aria; `percent: null` даёт
    состояние `unknown` (штриховка, нулевая заливка), а не «успешные 0 %»;
  * EVOL-044 — экранная клавиатура: видимая область приходит из платформенных
    сигналов, поле в фокусе остаётся выше клавиатуры, каретка/черновик целы,
    страница не получает горизонтальный скролл;
  * EVOL-043/044 — выпадающая панель области не уходит под клавиатуру и за
    край экрана (flip/sheet), пункты доступны;
  * EVOL-044 — длинный промпт: внутренний безопасный скролл, опция
    «Без переноса» реально переключает white-space, app-fullscreen не
    запускается;
  * EVOL-045 — reduced motion отключает декоративный пульс и бегущую
    indeterminate-полосу, текстовое состояние остаётся;
  * стыки карточек: двойных волосяных контуров нет.

Запуск: py -3 tools\\ui_evol_w11_controls_e2e.py [--out DIR]
Артефакты по умолчанию: plans/features/evol/audit/evidence/
Маркер успеха: EVOL-W11-CONTROLS OK
"""
import json
import os
import sys
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

import ui_round1025_matrix as M  # noqa: E402  сервер/стабы/TMA

PORT = 8847
DEFAULT_SHOTS = os.path.join(REPO, "plans", "features", "evol", "audit",
                             "evidence")

# Детерминированная фикстура /api/status: одна подтверждённая метрика (CPU),
# одна БЕЗ данных (RAM percent=null) и одна завершённая (Диск 100 %).
STATUS_FIXTURE = {
    "bot": {"uptime_seconds": 3600, "state": "running", "errors_total": 0},
    "server": {
        "cpu_percent": 42.0,
        "memory": {"used": 536870912, "total": 2147483648, "percent": None},
        "disk": {"used": 107374182400, "total": 107374182400, "percent": 100},
        "loadavg": [0.1, 0.2, 0.3],
        "process": {"pid": 1234, "rss_mb": 120, "threads": 8},
    },
    "llm": [],
    "context": {},
}


class _Handler(SimpleHTTPRequestHandler):
    """Статика репозитория без кэша."""

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

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def _routes():
    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/status"):
            payload = STATUS_FIXTURE
        elif url.endswith("/api/config"):
            hdrs = route.request.headers or {}
            payload = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                       else M.CONFIG_STUB)
        else:
            payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return _route


# ── зонды ────────────────────────────────────────────────────────────────────
PROBE_PROGRESS = r"""
() => {
  const tracks = Array.from(document.querySelectorAll('.ctl-progress__track'));
  const out = tracks.map((el) => {
    const fill = el.querySelector('.ctl-progress__fill');
    const cs = getComputedStyle(el);
    const fcs = fill ? getComputedStyle(fill) : null;
    const r = el.getBoundingClientRect();
    return {
      state: el.getAttribute('data-state'),
      role: el.getAttribute('role'),
      now: el.getAttribute('aria-valuenow'),
      label: el.getAttribute('aria-label'),
      widthPct: fill ? Math.round((fill.getBoundingClientRect().width
        / (r.width || 1)) * 100) : null,
      hatch: (cs.backgroundImage || '').indexOf('repeating-linear-gradient') >= 0,
      fillBg: fcs ? (fcs.backgroundImage || '').slice(0, 60) : null,
      visible: r.width > 4 && r.height > 1,
    };
  });
  return {
    count: tracks.length,
    tracks: out,
    anomalies: Array.from(document.querySelectorAll('[data-progress-anomaly]'))
      .map((el) => (el.textContent || '').trim().slice(0, 80)),
  };
}
"""

PROBE_EDITOR = r"""
() => {
  const ta = document.querySelector('[data-prompt-textarea]');
  if (!ta) return {found: false};
  const cs = getComputedStyle(ta);
  const wrap = ta.closest('[data-prompt-editor]');
  const r = ta.getBoundingClientRect();
  const vh = (window.visualViewport && window.visualViewport.height)
    || window.innerHeight;
  return {
    found: true,
    nowrap: ta.getAttribute('data-nowrap'),
    whiteSpace: cs.whiteSpace,
    overflowX: cs.overflowX,
    maxHeight: cs.maxHeight,
    bottom: Math.round(r.bottom),
    visibleH: Math.round(vh),
    insideEditor: !!wrap,
    scrollable: ta.scrollHeight > ta.clientHeight + 1,
    hScrollPage: document.documentElement.scrollWidth > window.innerWidth + 1,
    toggle: !!document.querySelector('[data-prompt-wrap-toggle]'),
    segButtons: document.querySelectorAll('[data-prompt-wrap-toggle] .ctl-seg__btn').length,
    fullscreen: !!document.fullscreenElement,
  };
}
"""

PROBE_SCOPE = r"""
() => {
  const p = document.querySelector('.scope-panel');
  if (!p) return {open: false};
  const r = p.getBoundingClientRect();
  const vh = (window.visualViewport && window.visualViewport.height)
    || window.innerHeight;
  const opts = Array.from(p.querySelectorAll('.scope-option'));
  const last = opts.length ? opts[opts.length - 1].getBoundingClientRect() : null;
  return {
    open: true,
    placement: p.getAttribute('data-placement'),
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    visibleH: Math.round(vh),
    inside: r.top >= -1 && r.bottom <= vh + 1
            && r.left >= -1 && r.right <= window.innerWidth + 1,
    options: opts.length,
    lastOptionVisible: last ? (last.bottom <= vh + 1 && last.top >= -1) : null,
    scrolls: p.scrollHeight > p.clientHeight + 1,
  };
}
"""

PROBE_KB = r"""
() => {
  const de = document.documentElement;
  const ta = document.activeElement;
  const r = ta && ta.getBoundingClientRect ? ta.getBoundingClientRect() : null;
  const cs = ta ? getComputedStyle(ta) : null;
  const vh = (window.visualViewport && window.visualViewport.height)
    || window.innerHeight;
  const sticky = document.querySelector('.sticky-save');
  return {
    kbOpen: de.classList.contains('kb-open'),
    kbTight: de.classList.contains('kb-tight'),
    offset: de.style.getPropertyValue('--kb-offset'),
    vvH: de.style.getPropertyValue('--vv-h'),
    activeTag: ta ? ta.tagName : null,
    hasEditorArea: ta ? ta.classList.contains('ctl-editor-area') : false,
    fieldBottom: r ? Math.round(r.bottom) : null,
    fieldTop: r ? Math.round(r.top) : null,
    visibleH: Math.round(vh),
    maxHeight: cs ? cs.maxHeight : null,
    stickyBottom: sticky ? Math.round(sticky.getBoundingClientRect().bottom) : null,
    stickyPosition: sticky ? getComputedStyle(sticky).position : null,
    hScrollPage: de.scrollWidth > window.innerWidth + 1,
  };
}
"""

PROBE_MOTION = r"""
() => {
  const host = document.createElement('div');
  host.style.position = 'fixed';
  host.style.left = '-9999px';
  host.innerHTML = '<span class="ctl-dot" data-live="1" data-state="ok"></span>' +
    '<div class="ctl-progress" data-state="running">' +
    '<div class="ctl-progress__track"><div class="ctl-progress__fill" style="width:40%"></div></div></div>';
  document.body.appendChild(host);
  const dot = host.querySelector('.ctl-dot');
  const track = host.querySelector('.ctl-progress__track');
  const after = getComputedStyle(track, '::after');
  const res = {
    dotAnim: getComputedStyle(dot).animationName,
    dotOpacity: getComputedStyle(dot).opacity,
    afterDisplay: after.display,
    trackBg: (getComputedStyle(track).backgroundImage || '').slice(0, 60),
  };
  host.remove();
  return res;
}
"""

PROBE_JOINTS = r"""
() => {
  const sel = '.card, .glass-panel, .module-card, .w10-section, .mem-item, ' +
              '.access-section-row, .dossier-card';
  const els = Array.from(document.querySelectorAll(sel)).filter((el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return r.width > 60 && r.height > 20 && cs.display !== 'none'
      && !el.closest('[aria-hidden="true"]');
  }).map((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      cls: (el.className || '').toString().split(/\s+/).slice(0, 2).join('.'),
      left: Math.round(r.left), right: Math.round(r.right),
      top: Math.round(r.top), bottom: Math.round(r.bottom),
      bw: parseFloat(cs.borderTopWidth) || 0,
      same: el.closest('.ctl-stack') ? 1 : 0,
    };
  });
  // Двойной контур = две поверхности с волосяной рамкой, чьи рамки стоят
  // вплотную (расстояние 0–1 px) и совпадают по горизонтали.
  let doubles = [];
  for (let i = 0; i < els.length; i++) {
    for (let j = 0; j < els.length; j++) {
      if (i === j) continue;
      const a = els[i], b = els[j];
      if (a.bw <= 0 || b.bw <= 0) continue;
      const gap = b.top - a.bottom;
      if (gap >= -1 && gap <= 1 && Math.abs(a.left - b.left) < 2
          && Math.abs(a.right - b.right) < 2) {
        doubles.push(a.cls + ' + ' + b.cls);
      }
    }
  }
  return {surfaces: els.length, doubles: doubles.slice(0, 8), doublesTotal: doubles.length};
}
"""


def run(out_dir, port=PORT):
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    fails = []
    report = {"viewports": {}, "checks": {}}

    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = "http://127.0.0.1:%d/web/index.html" % port

    def open_ctx(browser, w, h):
        phone = w <= 430
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=2 if phone else 1,
            is_mobile=phone, has_touch=phone,
        )
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _routes())
        return ctx

    def check(cond, msg):
        if not cond:
            fails.append(msg)
        return cond

    def shot(page, name):
        try:
            page.screenshot(path=os.path.join(out_dir,
                                             "w11-controls-%s.png" % name))
        except Exception:  # noqa: BLE001
            pass

    def boot(page, hash_route):
        page.goto(base_url + hash_route, wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_selector(".ctl-progress__track", timeout=20000)
        page.wait_for_timeout(600)

    def open_prompt_editor(page):
        """Открыть реальный редактор промпта через его же реестр (без хаков)."""
        page.evaluate(r"""
            () => {
              const vm = window.__adminbotVm;
              const m = (vm.modules || []).find(
                (x) => vm.workspacePromptItems(x).length > 0);
              if (!m) return null;
              const slug = vm.routeSlugOf(m);
              const it = vm.workspacePromptItems(m)[0];
              return {slug: slug, key: it.key, stage: it.stage || ''};
            }
        """)
        target = page.evaluate(r"""
            () => {
              const vm = window.__adminbotVm;
              const m = (vm.modules || []).find(
                (x) => vm.workspacePromptItems(x).length > 0);
              if (!m) return null;
              const slug = vm.routeSlugOf(m);
              const it = vm.workspacePromptItems(m)[0];
              const route = '#/ai/prompts/' + slug + (it.stage ? '/' + it.stage : '')
                + '/' + it.key;
              vm.navigateTo(route);
              return {slug: slug, key: it.key, route: route};
            }
        """)
        if not target:
            return None
        page.wait_for_timeout(1200)
        try:
            page.wait_for_selector("[data-prompt-textarea]", timeout=8000)
        except Exception:  # noqa: BLE001
            return None
        return target

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ═══ 1. 1280×800 — десктоп: прогресс, панель, редактор ══════════════
        ctx = open_ctx(browser, 1280, 800)
        page = ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text[:160])
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page, "#/")
        prog = page.evaluate(PROBE_PROGRESS)
        report["viewports"]["1280x800"] = {"progress": prog}
        shot(page, "1280-progress")

        check(prog["count"] >= 3,
              "1280: системные полосы используют контракт (%d)" % prog["count"])
        cpu = next((t for t in prog["tracks"] if t["state"] == "idle"
                    and t["now"] == "42"), None)
        check(cpu is not None, "1280: CPU 42 %% даёт determinate-полосу")
        if cpu:
            check(38 <= (cpu["widthPct"] or 0) <= 46,
                  "1280: ширина CPU ≈ 42 %% (получено %s)" % cpu["widthPct"])
            check(bool(cpu["label"]) and "%" in (cpu["label"] or ""),
                  "1280: у полосы есть подпись с единицами")
        unknown = [t for t in prog["tracks"] if t["state"] == "unknown"]
        check(bool(unknown), "1280: RAM без данных → state=unknown")
        if unknown:
            check(unknown[0]["hatch"], "1280: unknown помечен штриховкой")
            check((unknown[0]["widthPct"] or 0) == 0,
                  "1280: unknown не заливает «успех»")
        done = [t for t in prog["tracks"] if t["state"] == "done"]
        check(bool(done), "1280: Диск 100 %% → state=done")
        if done:
            check((done[0]["widthPct"] or 0) >= 99,
                  "1280: завершённая полоса действительно полная")
        check(not prog["anomalies"],
              "1280: ложных аномалий нет (%s)" % prog["anomalies"])

        # Панель области на десктопе: внутри вьюпорта, не под краем.
        try:
            page.click(".scope-trigger", timeout=8000)
            page.wait_for_selector(".scope-panel", timeout=8000)
            page.wait_for_timeout(300)
            scope = page.evaluate(PROBE_SCOPE)
            report["viewports"]["1280x800"]["scope"] = scope
            check(scope["open"] and scope["inside"],
                  "1280: панель области целиком во вьюпорте (%s)" % scope)
            check(scope["placement"] in ("bottom", "top"),
                  "1280: панель получила явное размещение (%s)"
                  % scope["placement"])
            check(scope["lastOptionVisible"] is not False,
                  "1280: последний пункт панели достижим")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception as exc:  # noqa: BLE001
            fails.append("1280: панель области не открылась: %s" % str(exc)[:160])

        # Редактор промпта: внутренний скролл + опция «Без переноса».
        target = open_prompt_editor(page)
        if not target:
            fails.append("1280: не удалось открыть реальный редактор промпта")
        else:
            ed = page.evaluate(PROBE_EDITOR)
            report["viewports"]["1280x800"]["editor"] = ed
            shot(page, "1280-editor")
            check(ed["found"], "1280: редактор найден")
            if ed["found"]:
                check(ed["toggle"] and ed["segButtons"] == 2,
                      "1280: у редактора есть переключатель переноса (2 кнопки)")
                check(ed["whiteSpace"].startswith("pre-wrap"),
                      "1280: по умолчанию перенос включён (%s)" % ed["whiteSpace"])
                check(ed["fullscreen"] is False,
                      "1280: редактор не запускает app-fullscreen")
                page.click('[data-prompt-wrap-toggle] .ctl-seg__btn:nth-child(2)',
                          timeout=5000)
                page.wait_for_timeout(250)
                ed2 = page.evaluate(PROBE_EDITOR)
                report["viewports"]["1280x800"]["editor_nowrap"] = ed2
                check(ed2["nowrap"] == "1", "1280: «Без переноса» переключает режим")
                check(ed2["whiteSpace"] == "pre",
                      "1280: без переноса строки не ломаются (%s)"
                      % ed2["whiteSpace"])
                check(ed2["overflowX"] in ("auto", "scroll"),
                      "1280: длинные строки прокручиваются внутри поля")
                page.click('[data-prompt-wrap-toggle] .ctl-seg__btn:nth-child(1)',
                          timeout=5000)
                page.wait_for_timeout(200)
                check(page.evaluate(PROBE_EDITOR)["nowrap"] == "0",
                      "1280: возврат к переносу работает")

        # Стыки карточек: двойных контуров нет (хаб + каталог модулей).
        joints = page.evaluate(PROBE_JOINTS)
        report["checks"]["joints_1280"] = joints
        check(joints["doublesTotal"] == 0,
              "1280: двойные контуры на стыках (%s)" % joints["doubles"])
        page.goto(base_url + "#/modules", wait_until="load")
        page.wait_for_selector(".module-card", timeout=15000)
        page.wait_for_timeout(700)
        joints2 = page.evaluate(PROBE_JOINTS)
        report["checks"]["joints_modules"] = joints2
        check(joints2["surfaces"] >= 8,
              "1280: каталог модулей реально осмотрен (%d поверхностей)"
              % joints2["surfaces"])
        check(joints2["doublesTotal"] == 0,
              "1280: двойные контуры в каталоге (%s)" % joints2["doubles"])

        check(not page.evaluate("() => document.documentElement.scrollWidth"
                                " > window.innerWidth + 1"),
              "1280: нет горизонтального скролла страницы")
        check(not errs, "1280: ошибок консоли нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 2. 390×844 — телефон с открытой клавиатурой ═══════════════════
        ctx = open_ctx(browser, 390, 844)
        page = ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text[:160])
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        page.goto(base_url + "#/", wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(800)
        # Реальный длинный редактор Core/prompt (тот же компонент, что на
        # страницах ИИ и Модулей) — через собственный реестр приложения.
        target = open_prompt_editor(page)
        editor_sel = '[data-prompt-textarea]'
        if not target:
            fails.append("390: длинный редактор промпта не открылся")
        else:
            try:
                page.click(editor_sel, timeout=8000)
                page.fill(editor_sel, "черновик W11\nвторая строка")
            except Exception as exc:  # noqa: BLE001
                fails.append("390: редактор не редактируется: %s" % str(exc)[:160])
        page.evaluate(r"""
            () => {
              const ta = document.querySelector('[data-prompt-textarea]');
              if (ta) ta.setSelectionRange(5, 9);
            }
        """)
        draft_before = page.evaluate(
            "() => (document.querySelector('[data-prompt-textarea]') || {}).value")
        sel_before = page.evaluate(r"""
            () => { const ta = document.querySelector('[data-prompt-textarea]');
                    return ta ? [ta.selectionStart, ta.selectionEnd] : null; }
        """)
        # Клавиатура: подменяем ПЛАТФОРМЕННЫЙ сигнал (visualViewport) и дергаем
        # РЕАЛЬНЫЙ обработчик — продуктовый путь целиком, без обхода кода.
        page.evaluate(r"""
            ([visH]) => {
              const shim = {height: visH, offsetTop: 0,
                            width: window.innerWidth,
                            addEventListener() {}, removeEventListener() {}};
              Object.defineProperty(window, 'visualViewport',
                {configurable: true, get: () => shim});
              window.__adminbotVm._syncKeyboardOffset();
            }
        """, [504])
        page.wait_for_timeout(400)
        kb = page.evaluate(PROBE_KB)
        report["viewports"]["390x844"] = {"keyboard": kb}
        shot(page, "390-keyboard")
        check(kb["kbOpen"], "390: html.kb-open выставлен по сигналу платформы")
        check(kb["offset"] == "340px", "390: --kb-offset = факт. перекрытие")
        check(kb["vvH"] == "504px", "390: --vv-h = реальная видимая высота")
        check(kb["hasEditorArea"],
              "390: длинный редактор использует контракт ctl-editor-area")
        try:
            maxh = float(str(kb["maxHeight"]).replace("px", ""))
        except Exception:  # noqa: BLE001
            maxh = 0
        check(maxh >= 150,
              "390: редактор не схлопывается под клавиатурой (max-height=%s)"
              % kb["maxHeight"])
        check(kb["fieldBottom"] is not None and kb["fieldBottom"] <= 504,
              "390: поле/каретка выше клавиатуры (bottom=%s при 504)"
              % kb["fieldBottom"])
        check(kb["fieldTop"] is not None and kb["fieldTop"] >= 0,
              "390: верх поля не уехал за экран")
        draft_after = page.evaluate(
            "() => (document.querySelector('[data-prompt-textarea]') || {}).value")
        sel_after = page.evaluate(r"""
            () => { const ta = document.querySelector('[data-prompt-textarea]');
                    return ta ? [ta.selectionStart, ta.selectionEnd] : null; }
        """)
        check(draft_after == draft_before,
              "390: черновик сохранён при появлении клавиатуры")
        check(sel_after == sel_before,
              "390: выделение/каретка сохранены (%s → %s)"
              % (sel_before, sel_after))
        check(not kb["hScrollPage"], "390: клавиатура не создаёт h-скролл")

        # Панель области ПРИ открытой клавиатуре: не под клавиатурой.
        try:
            page.click(".scope-trigger", timeout=8000)
            page.wait_for_selector(".scope-panel", timeout=8000)
            page.wait_for_timeout(400)
            scope = page.evaluate(PROBE_SCOPE)
            report["viewports"]["390x844"]["scope"] = scope
            shot(page, "390-scope-keyboard")
            check(scope["open"] and scope["inside"],
                  "390: панель области не уходит за видимую область (%s)" % scope)
            check(scope["placement"] in ("top", "bottom", "sheet"),
                  "390: размещение панели определено (%s)" % scope["placement"])
            check(scope["lastOptionVisible"] is not False,
                  "390: пункты панели достижимы над клавиатурой")
            check(scope["bottom"] <= (scope.get("visibleH") or 0),
                  "390: панель выше клавиатуры (bottom=%s при %s)"
                  % (scope["bottom"], scope.get("visibleH")))
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
            check(page.evaluate("() => !document.querySelector('.scope-panel')"),
                  "390: Esc закрывает панель")
        except Exception as exc:  # noqa: BLE001
            fails.append("390: панель области при клавиатуре: %s" % str(exc)[:160])

        # Клавиатура закрыта: сигнал вернулся, состояние снимается.
        page.evaluate(r"""
            () => {
              const shim = {height: window.innerHeight, offsetTop: 0,
                            width: window.innerWidth,
                            addEventListener() {}, removeEventListener() {}};
              Object.defineProperty(window, 'visualViewport',
                {configurable: true, get: () => shim});
              window.__adminbotVm._syncKeyboardOffset();
            }
        """)
        page.wait_for_timeout(250)
        kb2 = page.evaluate(PROBE_KB)
        check(not kb2["kbOpen"], "390: kb-open снят после закрытия клавиатуры")
        check(kb2["offset"] == "0px", "390: --kb-offset сброшен")
        check(kb2["vvH"] in ("", None),
              "390: --vv-h снят (работает --app-usable-height), получено %r"
              % kb2["vvH"])
        check(not errs, "390: ошибок консоли нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 3. 768×1024 — планшет: прогресс/редактор/панель без поломок ════
        ctx = open_ctx(browser, 768, 1024)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page, "#/")
        prog = page.evaluate(PROBE_PROGRESS)
        report["viewports"]["768x1024"] = {"progress": {"count": prog["count"]}}
        check(prog["count"] >= 3, "768: полосы прогресса на месте")
        try:
            page.click(".scope-trigger", timeout=8000)
            page.wait_for_selector(".scope-panel", timeout=8000)
            page.wait_for_timeout(250)
            scope = page.evaluate(PROBE_SCOPE)
            report["viewports"]["768x1024"]["scope"] = scope
            check(scope["inside"], "768: панель области во вьюпорте")
            page.keyboard.press("Escape")
        except Exception as exc:  # noqa: BLE001
            fails.append("768: панель области: %s" % str(exc)[:160])
        target = open_prompt_editor(page)
        if not target:
            fails.append("768: редактор промпта не открылся")
        else:
            page.evaluate(r"""
                () => {
                  const shim = {height: 640, offsetTop: 0,
                                width: window.innerWidth,
                                addEventListener() {}, removeEventListener() {}};
                  Object.defineProperty(window, 'visualViewport',
                    {configurable: true, get: () => shim});
                  window.__adminbotVm._syncKeyboardOffset();
                }
            """)
            page.wait_for_timeout(300)
            ed = page.evaluate(PROBE_EDITOR)
            report["viewports"]["768x1024"]["editor"] = ed
            shot(page, "768-editor")
            check(ed["bottom"] <= 640,
                  "768: редактор не уходит под клавиатуру (bottom=%s)"
                  % ed["bottom"])
            check(ed["scrollable"] or ed["maxHeight"] != "none",
                  "768: длинный текст скроллится внутри редактора")
        check(not page.evaluate("() => document.documentElement.scrollWidth"
                                " > window.innerWidth + 1"),
              "768: нет горизонтального скролла")
        check(not errs, "768: ошибок консоли нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 4. Reduced motion: движение выключено, смысл остался ═══════════
        ctx = open_ctx(browser, 390, 844)
        page = ctx.new_page()
        page.emulate_media(reduced_motion="reduce")
        boot(page, "#/")
        motion = page.evaluate(PROBE_MOTION)
        report["checks"]["reduced_motion"] = motion
        check(motion["dotAnim"] == "none",
              "reduced-motion: пульс точки выключен (%s)" % motion["dotAnim"])
        check(motion["afterDisplay"] == "none",
              "reduced-motion: бегущая indeterminate-полоса убрана")
        check("repeating-linear-gradient" in (motion["trackBg"] or ""),
              "reduced-motion: вместо движения — статичная штриховка статуса")
        ctx.close()

        # ═══ 5. Обычный режим: пульс есть только у live-точки ══════════════
        ctx = open_ctx(browser, 390, 844)
        page = ctx.new_page()
        boot(page, "#/")
        motion2 = page.evaluate(PROBE_MOTION)
        report["checks"]["motion_default"] = motion2
        check(motion2["dotAnim"] == "ctl-pulse",
              "по умолчанию пульсирует только live-точка (%s)"
              % motion2["dotAnim"])
        ctx.close()

        browser.close()

    httpd.shutdown()

    report["fails"] = fails
    with open(os.path.join(out_dir, "w11-controls-e2e.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    if fails:
        print("EVOL-W11-CONTROLS FAILED (%d):" % len(fails))
        for item in fails:
            print(" -", item)
        return 1
    print("EVOL-W11-CONTROLS OK")
    return 0


def main() -> int:
    out_dir = DEFAULT_SHOTS
    port = PORT
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            out_dir = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1
    os.makedirs(out_dir, exist_ok=True)
    return run(out_dir, port=port)


if __name__ == "__main__":
    sys.exit(main())
