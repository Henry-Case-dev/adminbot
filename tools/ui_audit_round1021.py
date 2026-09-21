"""F6 round 10.21 — автономный UI/UX-аудит реальным браузером (Playwright+Chromium).

Поднимает РЕАЛЬНЫЙ `web/index.html` + `web/static/*` на локальном uvicorn-сервере
с in-memory стабом `ConfigCache` (фейковый PG, без реальных секретов) и прогоняет
DOM/CSSOM-зонды по всем разделам и модалкам.

Инструмент №1 (Puppeteer MCP) в этом окружении недоступен (нет соответствующего
MCP-сервера) — см. `UI_AUDIT_REPORT.md`. Этот скрипт — fallback (Playwright ≥1.40).

R17/R18: только фейковые плейсхолдеры (`sk_FAKE…`) и маска `••••…`.
Запуск:  .venv/Scripts/python.exe tools/ui_audit_round1021.py
Артефакты: tools/_ui_audit_raw.json + tools/_ui_audit_shots/*.png
"""
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import types
import urllib.parse

try:  # Windows-консоль (cp1251) — не падать на юникоде
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

AUDIT_TOKEN = "000000:UI_AUDIT_PLACEHOLDER_TOKEN"   # фейковый, не секрет (R17)
ADMIN_ID = 5885953495
PORT = 8765
SHOTS = os.path.join(REPO, "tools", "_ui_audit_shots")


def make_init_data(user_id=ADMIN_ID):
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "Audit",
                            "username": "audit"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", AUDIT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return self

            async def __aexit__(self_inner, *exc):
                return False
        return _Tx()

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _CM()

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)
        self.closed = False

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        self.closed = True


def _settings_rows():
    """Фейковые значения для ВСЕХ pg-ключей каталога (плейсхолдеры, R17)."""
    from services import param_catalog as pc
    rows = []
    n = 0
    for key, spec in sorted(pc._BY_PG_KEY.items()):
        if spec.category is None:
            continue
        t = spec.type
        if spec.secret:
            val = "sk_FAKE_%04d" % n
        elif t == "bool":
            val = False
        elif t == "int":
            val = 1
        elif t == "float":
            val = 1.0
        elif t == "json":
            val = {}
        elif spec.widget == "select" and spec.select_options:
            val = spec.select_options[0]
        else:
            val = "demo"
        rows.append({"key": key, "value": val,
                     "category": spec.category or "", "updated_at": None})
        n += 1
    return rows


def _role_rows():
    return [{"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False, "role_type": "global_admin"}]


def _admin_rows():
    return [{"telegram_id": ADMIN_ID, "role_name": "admin", "added_by": None,
             "created_at": "2026-09-01T00:00:00+00:00"}]


def build_app():
    from services.config_cache import ConfigCache
    from web.app import create_app
    from web.api import deps as deps_mod

    deps_mod.settings = types.SimpleNamespace(API_TOKEN=AUDIT_TOKEN)
    conn = _FakeConn(_settings_rows(), _role_rows(), _admin_rows())
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    return create_app(cache)


def start_server():
    import uvicorn
    app = build_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT,
                            log_level="error", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("uvicorn не стартовал")


# ── Зонд (выполняется в браузере) ────────────────────────────────────────────
JS_PROBE = r"""
() => {
  const cs = (el) => el ? getComputedStyle(el) : null;
  const rc = (r) => ({x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1),
                      h:+r.height.toFixed(1), bottom:+r.bottom.toFixed(1)});
  const rect = (el) => el ? rc(el.getBoundingClientRect()) : null;
  const vis = (el) => {
    try { return el.checkVisibility({contentVisibilityAuto:true, opacityProperty:true});
    } catch (e) { return el.offsetWidth > 0 || el.offsetHeight > 0; }
  };
  const q = (s) => document.querySelector(s);
  const info = (el) => { const s = cs(el); return el ? {
      bg: s.backgroundColor, bf: s.backdropFilter || s.webkitBackdropFilter,
      border: s.borderColor, rect: rect(el) } : null; };
  const trackCount = (s) => {
    const el = q(s); if (!el) return null;
    const t = cs(el).gridTemplateColumns;
    return { raw: t, tracks: t && t !== 'none' ? t.split(' ').filter(Boolean).length : 0 };
  };
  const glassSelectors = ['.modal-card', '.card', '.module-card', '.hub-card',
    '.prov-block', '.glass-panel', 'details.advanced', '.sticky-save',
    '.scope-panel', '.oversight-panel'];
  const glass = {};
  glassSelectors.forEach((s) => {
    const el = q(s);
    if (el) { const i = info(el); glass[s] = { bg: i.bg, bf: i.bf, border: i.border }; }
  });
  // видимые пересечения карточек/панелей (без закрытых details и вложенных)
  const overlaps = [];
  const shortPath = (el) => { const c = el.className;
    return typeof c === 'string' ? c.trim().split(/\s+/).slice(0, 3).join('.') : el.tagName; };
  const boxes = [...document.querySelectorAll(
      '.card, .module-card, .hub-card, .prov-block')]
    .filter((e) => vis(e) && e.getBoundingClientRect().width > 0)
    .map((e) => ({ e, r: e.getBoundingClientRect() }));
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.r.right <= b.r.left || b.r.right <= a.r.left ||
          a.r.bottom <= b.r.top || b.r.bottom <= a.r.top) continue;
      if (a.e.contains(b.e) || b.e.contains(a.e)) continue;
      overlaps.push({ a: shortPath(a.e), b: shortPath(b.e),
                      ra: rc(a.r), rb: rc(b.r) });
    }
  }
  // sticky-зазор: panel.bottom vs низ скролл-порта (fullscreen-скроллер)
  let sticky = null;
  const panel = q('.scroll-area > .sticky-save') || q('sticky-save .sticky-save') ||
                q('.sticky-save');
  if (panel && vis(panel)) {
    const pr = panel.getBoundingClientRect();
    let sc = q('.fullscreen-mode .scroll-area') ||
             panel.closest('.modal-body') || panel.closest('.scroll-area');
    const sr = sc ? sc.getBoundingClientRect() : null;
    sticky = { panelBottom: +pr.bottom.toFixed(1), panelH: +pr.height.toFixed(1),
      scroller: sc ? (sc.className || sc.tagName) : null,
      scrollerBottom: sr ? +sr.bottom.toFixed(1) : null,
      gap: sr ? +(sr.bottom - pr.bottom).toFixed(1) : null,
      fullscreen: !!q('.fullscreen-mode'),
      scrollAreaPaddingBottom: sc ? cs(sc).paddingBottom : null,
      hasSpacer: !!q('.scroll-area > .sticky-spacer') };
  }
  const secrets = [...document.querySelectorAll('input[type=password]')]
    .slice(0, 30).map((el) => ({ value: el.value, len: el.value.length,
      masked: el.value === '\u2022'.repeat(12) }));
  const root = cs(document.documentElement);
  const before = getComputedStyle(document.body, '::before');
  // F2/T-2544: основной цикл 60–90 c (--grad-speed), вторичный 90–120 c.
  const grad = { speed: root.getPropertyValue('--grad-speed').trim(),
    slow: root.getPropertyValue('--grad-speed-slow').trim(),
    d: root.getPropertyValue('--grad-d').trim(),
    animName: before.animationName, animDur: before.animationDuration,
    opacity: before.opacity,
    bg: (before.backgroundImage || '').slice(0, 140) };
  const sa = q('.scroll-area');
  return {
    glass,
    grid: { prov: trackCount('.prov-grid'), module: trackCount('.module-list'),
            hub: trackCount('.hub-grid') },
    overlaps: overlaps.slice(0, 10), sticky, secrets, grad,
    hOverflow: { doc: document.documentElement.scrollWidth -
                      document.documentElement.clientWidth,
                 area: sa ? sa.scrollWidth - sa.clientWidth : null },
    counts: { nav: document.querySelectorAll('.navbar-band .nav-link').length,
              cards: document.querySelectorAll('.card').length,
              moduleCards: document.querySelectorAll('.module-card').length,
              provBlocks: document.querySelectorAll('.prov-block').length,
              modals: document.querySelectorAll('.modal-backdrop').length,
              advanced: document.querySelectorAll('details.advanced').length,
              advancedOpen: document.querySelectorAll('details.advanced[open]').length,
              passwordFields: document.querySelectorAll('input[type=password]').length },
  };
}
"""


def probe(page):
    return page.evaluate(JS_PROBE)


def snap(page, name):
    try:
        page.screenshot(path=os.path.join(SHOTS, name + ".png"))
    except Exception as e:
        print("[audit] screenshot fail", name, e)


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)

    server = start_server()
    init_data = make_init_data()
    print(f"[audit] server http://127.0.0.1:{PORT}")

    routes = [
        ("Статус", "#/"), ("Справка", "#/how"), ("Модули", "#/modules"),
        ("ИИ", "#/ai"), ("ИИ-LLM-Провайдеры", "#/ai/llm"),
        ("ИИ-Промпты", "#/ai/prompts"), ("ИИ-Память", "#/ai/memory"),
        ("ИИ-Умный-кэш", "#/ai/smart-cache"), ("ИИ-Имена", "#/ai/names"),
        ("ИИ-Отношения", "#/ai/relations"), ("ИИ-Лор", "#/ai/lore"),
        ("ИИ-Личность", "#/ai/persona"), ("PERMsoc", "#/permsoc"),
        ("Доступы", "#/access"), ("Сводка", "#/oversight"),
    ]

    out = {"routes": {}, "modals": {}, "viewports": {}, "console": [],
           "http_errors": []}
    console = out["console"]
    http_errors = out["http_errors"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        ctx.add_init_script(
            "sessionStorage.setItem('adminbot.initData', %s);" % json.dumps(init_data))
        ctx.add_init_script(
            "window.addEventListener('DOMContentLoaded',()=>{try{"
            "if(window.Telegram&&Telegram.WebApp){"
            "Telegram.WebApp.requestFullscreen=function(){};"
            "Telegram.WebApp.exitFullscreen=function(){};}}catch(e){}});")
        page = ctx.new_page()
        page.on("console", lambda m: console.append([m.type, m.text]))
        page.on("pageerror", lambda e: console.append(["pageerror", str(e)]))
        page.on("requestfailed",
                lambda r: console.append(["requestfailed",
                                          r.url + " :: " + str(r.failure)]))
        page.on("response", lambda r: (
            http_errors.append([r.status, r.url]) if r.status >= 400 else None))
        page.goto(f"http://127.0.0.1:{PORT}/web/", wait_until="networkidle")
        page.wait_for_selector(".navbar-band", timeout=20000)
        page.evaluate("()=>{document.querySelectorAll('details').forEach(d=>d.open=false)}")
        time.sleep(1.0)
        out["routes"]["__boot__"] = probe(page)

        for label, route in routes:
            page.evaluate("(r) => { window.location.hash = r; }", route)
            page.evaluate("()=>{document.querySelectorAll('details').forEach(d=>d.open=false)}")
            time.sleep(0.9)
            out["routes"][label] = probe(page)
            snap(page, "route_" + label)
            print(f"[audit] {label:20s} cards={out['routes'][label]['counts']['cards']:4d} "
                  f"overflow={out['routes'][label]['hOverflow']}")

        # ── L-4: панель выбора контекста — коллизионная коррекция ──────────
        try:
            page.evaluate("() => { window.location.hash = '#/ai/persona'; }")
            time.sleep(0.8)
            panel_info = []
            for _ in range(2):
                page.locator(".scope-trigger").first.click()
                time.sleep(0.5)
                panel_info.append(page.evaluate("""() => {
                    const p = document.querySelector('.scope-panel');
                    if (!p) return null;
                    const r = p.getBoundingClientRect();
                    return { x: +r.x.toFixed(1), right: +r.right.toFixed(1),
                             vw: document.documentElement.clientWidth,
                             style: p.getAttribute('style'),
                             leftClip: r.x < 0,
                             rightClip: r.right > document.documentElement.clientWidth };
                }"""))
                snap(page, "scope_panel_persona")
                page.keyboard.press("Escape")
                time.sleep(0.3)
            out["scope_panel"] = panel_info
            print("[audit] scope-panel:", json.dumps(panel_info, ensure_ascii=False))
        except Exception as e:
            console.append(["audit-error", f"scope panel: {e}"])

        # ── Grid: матрица вьюпортов на «ИИ» ────────────────────────────────
        page.evaluate("() => { window.location.hash = '#/ai/llm'; }")
        for w, h in [(1440, 1000), (1000, 900), (999, 900), (400, 850)]:
            page.set_viewport_size({"width": w, "height": h})
            time.sleep(0.7)
            out["viewports"][str(w)] = {
                "prov": probe(page)["grid"]["prov"],
                "module": probe(page)["grid"]["module"]}
            print(f"[audit] viewport {w} -> prov={out['viewports'][str(w)]['prov']}")
        page.set_viewport_size({"width": 1440, "height": 1000})

        # ── Модалки модулей (все 12) ───────────────────────────────────────
        page.evaluate("() => { window.location.hash = '#/modules'; }")
        page.evaluate("()=>{document.querySelectorAll('details').forEach(d=>d.open=false)}")
        time.sleep(0.9)
        n = page.locator(".module-params-btn").count()
        print(f"[audit] module buttons: {n}")
        for i in range(n):
            try:
                page.locator(".module-params-btn").nth(i).click()
                time.sleep(0.6)
                # раскрыть все advanced/details внутри модалки
                page.evaluate(
                    "()=>{document.querySelectorAll('.modal-backdrop details')"
                    ".forEach(d=>{d.open=true;d.dispatchEvent(new Event('toggle'))})}")
                time.sleep(0.5)
                key = "module_%d" % i
                out["modals"][key] = probe(page)
                snap(page, "modal_module_%d" % i)
                try:
                    page.locator(".modal-card .modal-close").first.click(timeout=4000)
                except Exception:
                    page.keyboard.press("Escape")
                time.sleep(0.4)
            except Exception as e:
                console.append(["audit-error", f"module modal {i}: {e}"])
                try:
                    page.keyboard.press("Escape")
                    time.sleep(0.3)
                except Exception:
                    pass
        print(f"[audit] module modals captured: {len(out['modals'])}")

        # ── Доступы: матрица ролей / локальные / роли ──────────────────────
        for label, route in [("Доступы-Роли", "#/access/admins"),
                             ("Доступы-Матрица", "#/access/roles"),
                             ("Доступы-Локальные", "#/access/local")]:
            page.evaluate("(r) => { window.location.hash = r; }", route)
            time.sleep(1.0)
            out["modals"][label] = probe(page)
            snap(page, "access_" + label)
        # модалка роли (редактор)
        try:
            page.evaluate("() => { window.location.hash = '#/access/admins'; }")
            time.sleep(0.9)
            if page.locator(".modal-backdrop button").count():
                pass
        except Exception as e:
            console.append(["audit-error", f"role editor: {e}"])

        # ── Fullscreen sticky (M-1) ────────────────────────────────────────
        for label, route in [("sticky-fullscreen-prompts", "#/ai/prompts"),
                             ("sticky-fullscreen-llm", "#/ai/llm")]:
            page.evaluate("(r) => { window.location.hash = r; }", route)
            time.sleep(0.8)
            try:
                page.locator("button[title*='олноэкран']").first.click()
            except Exception as e:
                console.append(["audit-error", f"fullscreen click: {e}"])
            time.sleep(0.6)
            # прокрутить скроллер в самый низ
            page.evaluate("""() => {
                const sc = document.querySelector('.fullscreen-mode .scroll-area');
                if (sc) sc.scrollTop = sc.scrollHeight;
            }""")
            time.sleep(0.6)
            out["modals"][label] = probe(page)
            snap(page, label)
            st = out["modals"][label].get("sticky")
            print(f"[audit] {label}: sticky={st}")
            try:
                page.locator("button[title*='олноэкран']").first.click()
            except Exception:
                pass
            time.sleep(0.4)

        page.evaluate("() => { window.location.hash = '#/ai/llm'; }")
        time.sleep(0.8)
        page.evaluate("()=>{document.querySelectorAll('details').forEach(d=>d.open=true)}")
        time.sleep(0.5)
        out["modals"]["llm-advanced-open"] = probe(page)
        snap(page, "llm_advanced_open")

        browser.close()

        # ── reduced-motion ────────────────────────────────────────────────
        ctx2 = browser2 = None
        try:
            browser2 = p.chromium.launch()
            ctx2 = browser2.new_context(viewport={"width": 1440, "height": 900},
                                        reduced_motion="reduce")
            ctx2.add_init_script(
                "sessionStorage.setItem('adminbot.initData', %s);"
                % json.dumps(init_data))
            pg2 = ctx2.new_page()
            pg2.goto(f"http://127.0.0.1:{PORT}/web/", wait_until="networkidle")
            pg2.wait_for_selector(".navbar-band", timeout=20000)
            time.sleep(1.0)
            out["reduced_motion"] = probe(pg2)["grad"]
            print("[audit] reduced-motion grad:", out["reduced_motion"])
        except Exception as e:
            out["reduced_motion_error"] = str(e)
        finally:
            if ctx2:
                ctx2.close()
            if browser2:
                browser2.close()

    server.should_exit = True

    with open(os.path.join(REPO, "tools", "_ui_audit_raw.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    errs = [c for c in console
            if c[0] in ("error", "pageerror", "requestfailed", "audit-error")]
    print("[audit] raw -> tools/_ui_audit_raw.json ; shots -> tools/_ui_audit_shots/")
    print("[audit] errors:", json.dumps(errs[:20], ensure_ascii=False))


if __name__ == "__main__":
    main()
