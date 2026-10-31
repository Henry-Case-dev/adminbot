# -*- coding: utf-8 -*-
"""ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 — живой UI-прогон (desktop+mobile).

Детерминированный Playwright-прогон НАСТОЯЩИХ `web/index.html` + `web/app.js`
+ `web/static/app.css` (сервер/стабы API — из `tools/ui_round1025_matrix.py`,
секретов нет, в Telegram ничего не отправляется).

Проверяется (§4.2/§5/§6/§7 v2.1):

  * Модули: РОВНО ОДИН scoped-переключатель на карточку; при `GLOBAL` он
    пишет глобально (POST без X-Chat-Id), при выбранном чате — только этот чат
    (POST с X-Chat-Id); второго (global+chat) тумблера нет;
  * «Речь и характер»: пять вкладок, «Мат» — отдельная вкладка;
  * «ИИ»: компактный хаб, deep-links ведут в конкретную вкладку;
  * Статус: ОДИН блок здоровья с тремя сегментами;
  * мобильный 390 и ландшафт 667: нет «…», одна кнопка ⛶, drawer начинается
    ниже системной области, нет горизонтального скролла;
  * «Избранное» отсутствует во всём интерфейсе.

Запуск: py -3 tools\\ui_asap_cover_ui_v21_e2e.py [--out DIR]
Маркер успеха: ASAP-UI-V21-OK
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

import ui_round1025_matrix as M  # noqa: E402

PORT = 8863
DEFAULT_SHOTS = os.path.join(REPO, "plans", "features", "evol", "audit",
                             "evidence")


class _Handler(SimpleHTTPRequestHandler):
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
    """Стабы API + отсутствующие в общей матрице ответы.

    `/api/persona` нужен, чтобы baseline личности был известен: иначе
    `hasUnsavedEdits()` считает черновик изменённым (фикстура без baseline) и
    штатный leave-guard отменяет навигацию — это артефакт стенда, не продукта.
    """
    persona = {"scope": "chat", "chat_id": -1001234567890, "is_global": True,
               "updated_at": "2026-11-01T10:00:00+00:00",
               "values": {"name": "Бот", "biography": "Тестовая биография",
                          "system_prompt_overrides": "", "is_aware_ai": True}}

    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/config"):
            hdrs = route.request.headers or {}
            payload = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                       else M.CONFIG_STUB)
        elif url.endswith("/api/persona"):
            payload = persona
        elif url.endswith("/api/persona/self-model"):
            payload = {"enabled": True, "version": "1", "frame_version": 1,
                       "rules_status": "on", "widget_id": "self-model-1",
                       "explanations": {}, "switches": {},
                       "composition": {"base": True, "dynamics": 0,
                                       "mood": False},
                       "positions_count": 0, "applied_now": [],
                       "rejected_now": [], "active_rules": []}
        else:
            payload = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
    return _route


PROBE_SCOPE = r"""
() => {
  const cards = Array.from(document.querySelectorAll('[data-mod]'));
  const per = cards.map((c) => c.querySelectorAll('[data-module-scope-toggle]').length);
  const labels = Array.from(document.querySelectorAll(
    '.module-card .module-control-row__label')).slice(0, 3)
    .map((el) => (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60));
  const scopes = Array.from(document.querySelectorAll('[data-module-scope-toggle]'))
    .slice(0, 3).map((el) => el.getAttribute('data-module-scope'));
  const ro = document.querySelectorAll('[data-module-scope-readonly]').length;
  const legacy = document.querySelectorAll(
    '[data-module-global-toggle],[data-module-chat-toggle]').length;
  const pins = document.querySelectorAll(
    '.module-pin-btn,[data-module-favorite],[data-favorites]').length;
  return {cards: cards.length, maxToggles: Math.max(0, ...per),
          labels: labels, scopes: scopes, readonly: ro, legacy: legacy,
          pins: pins,
          favoritesText: (document.body.innerText || '').includes('В избранно'),
          width: window.innerWidth,
          hScroll: document.documentElement.scrollWidth > window.innerWidth + 1};
}
"""

PROBE_SPEECH = r"""
() => ({
  tabs: Array.from(document.querySelectorAll('[data-speech-area]'))
    .map((b) => (b.innerText || '').replace(/\s+/g, ' ').trim()),
  active: (document.querySelector('[data-speech-area][aria-current="true"]')
    || {getAttribute: () => null}).getAttribute('data-speech-area'),
  persona: !!document.querySelector('#speech-persona'),
  profanity: !!document.querySelector('[data-speech-profanity]'),
  rules: !!document.querySelector('[data-speech-rules]'),
  dirtyDots: document.querySelectorAll(
    '[data-speech-area-dirty="true"]').length,
})
"""

PROBE_HUB = r"""
() => {
  const cards = Array.from(document.querySelectorAll('.w10-section'));
  const heights = cards.map((c) => Math.round(c.getBoundingClientRect().height));
  return {
    tiles: cards.length, heights: heights,
    chips: document.querySelectorAll('[data-ai-speech-tab]').length,
    sameHeight: heights.length > 1 &&
      heights.every((h) => Math.abs(h - heights[0]) <= 2),
  };
}
"""

PROBE_STATUS = r"""
() => {
  const block = document.querySelector('[data-status-health]');
  if (!block) return {present: false};
  const segs = Array.from(block.querySelectorAll('[data-status-seg]'))
    .map((s) => s.getAttribute('data-status-seg'));
  const cards = block.querySelectorAll('.card').length;
  const line = block.querySelector('[data-status-counts]');
  const analytics = block.querySelector('[data-status-health-analytics]');
  const okLine = block.querySelector('[data-status-health-ok]');
  const segBoxes = Array.from(block.querySelectorAll('[data-status-seg]'))
    .map((s) => { const r = s.getBoundingClientRect();
                  return {w: Math.round(r.width), h: Math.round(r.height)}; });
  return {
    present: true, segs: segs, innerCards: cards,
    line: !!line, analytics: !!analytics, okLine: !!okLine,
    segBoxes: segBoxes,
  };
}
"""

PROBE_SHELL = r"""
() => {
  const header = document.querySelector('header.header-sticky');
  const fs = document.querySelectorAll('.header-fs-btn');
  const fsBox = fs[0] ? fs[0].getBoundingClientRect() : null;
  return {
    moreTrigger: document.querySelectorAll('[data-more-trigger]').length,
    moreMenu: document.querySelectorAll('.more-menu-root').length,
    geomEntry: document.querySelectorAll('[data-fs-geom-diag-entry]').length,
    identityInMenu: document.querySelectorAll('.more-menu-profile').length,
    fsCount: fs.length,
    fsTap: fsBox ? {w: Math.round(fsBox.width), h: Math.round(fsBox.height)}
                 : null,
    fsLabel: fs[0] ? (fs[0].getAttribute('aria-label') || '') : '',
    headerH: header ? Math.round(header.getBoundingClientRect().height) : null,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
    avatar: document.querySelectorAll('.header-user img,'
      + ' .header-user-initial').length,
    role: document.querySelectorAll('.header-user-role').length,
  };
}
"""

PROBE_DRAWER = r"""
() => {
  const d = document.querySelector('.app-drawer');
  if (!d) return {present: false};
  const r = d.getBoundingClientRect();
  return {present: true, top: Math.round(r.top), left: Math.round(r.left),
          visible: getComputedStyle(d).visibility,
          inView: r.top >= 0 && r.bottom <= window.innerHeight + 2};
}
"""


def run(out_dir: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        print("playwright недоступен:", exc)
        return 2

    fails = []
    report = {"checks": {}}

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT

    def check(cond, msg):
        if not cond:
            fails.append(msg)
        return cond

    def shot(page, name):
        try:
            page.screenshot(path=os.path.join(out_dir, name + ".png"),
                            full_page=False)
        except Exception:  # noqa: BLE001
            pass

    def open_ctx(browser, w, h):
        phone = w <= 430
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  device_scale_factor=2 if phone else 1,
                                  is_mobile=phone, has_touch=phone)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _routes())
        return ctx

    def new_page(ctx):
        page = ctx.new_page()
        # Штатный leave-guard (confirm) подтверждаем: переходы в прогоне —
        # это навигация теста, а не отказ владельца.
        page.on("dialog", lambda d: d.accept())
        return page

    def pick_scope(page, want_global: bool):
        page.click(".scope-trigger", timeout=8000)
        page.wait_for_timeout(250)
        opts = page.query_selector_all(".scope-option")
        target = None
        for o in opts:
            text = (o.inner_text() or "").strip()
            if want_global and ("Весь бот" in text or "GLOBAL" in text
                                or "Глобаль" in text):
                target = o
                break
            if not want_global and "Audit Chat" in text:
                target = o
                break
        if target is None and opts:
            target = opts[0] if want_global else opts[-1]
        if target is None:
            return False
        target.click()
        page.wait_for_timeout(900)
        return True

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ═══ 1. Desktop 1280 — Модули: один переключатель, scope селектора ══
        ctx = open_ctx(browser, 1280, 900)
        page = new_page(ctx)
        errs = []
        page.on("console", lambda m: errs.append(m.text[:160])
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        page.goto(base + "#/modules", wait_until="load")
        page.wait_for_selector(".module-card", timeout=20000)
        page.wait_for_timeout(900)
        probe = page.evaluate(PROBE_SCOPE)
        report["checks"]["modules_initial"] = probe
        check(probe["cards"] >= 5,
              "модули: каталог не отрисован (%d)" % probe["cards"])
        check(probe["maxToggles"] <= 1,
              "модули: на карточке больше одного переключателя (%d)"
              % probe["maxToggles"])
        check(probe["legacy"] == 0,
              "модули: вернулся второй (global/chat) тумблер (%d)"
              % probe["legacy"])
        check(not probe["pins"] and not probe["favoritesText"],
              "«Избранное» осталось в UI (%d)" % probe["pins"])
        shot(page, "v21-1280-modules")

        # Scope → GLOBAL: единственный тумблер пишет глобально (без X-Chat-Id).
        posts = []
        page.on("request", lambda r: posts.append(
            {"url": r.url, "chat": r.headers.get("x-chat-id")})
            if r.method == "POST" and "/api/config" in r.url else None)
        check(pick_scope(page, True), "селектор области: не удалось выбрать GLOBAL")
        probe_g = page.evaluate(PROBE_SCOPE)
        report["checks"]["modules_global"] = probe_g
        check(probe_g["maxToggles"] <= 1,
              "GLOBAL: второй переключатель на карточке (%d)"
              % probe_g["maxToggles"])
        posts.clear()
        page.evaluate("() => { const t = document.querySelector"
                      "('[data-module-scope-toggle]'); if (t) t.click(); }")
        page.wait_for_timeout(1100)
        report["checks"]["posts_global"] = posts
        check(bool(posts), "GLOBAL: переключатель не выполнил серверную операцию")
        check(all(not x["chat"] for x in posts),
              "GLOBAL: ушёл чатовый X-Chat-Id в глобальной записи (%s)" % posts)

        # Scope → чат A: тот же контрол, запись только этого чата.
        check(pick_scope(page, False), "селектор области: не удалось выбрать чат")
        probe_c = page.evaluate(PROBE_SCOPE)
        report["checks"]["modules_chat"] = probe_c
        check(probe_c["maxToggles"] <= 1,
              "чат: второй переключатель на карточке (%d)"
              % probe_c["maxToggles"])
        check(probe_c["legacy"] == 0, "чат: вернулся второй тумблер")
        check(any(s == "chat" for s in probe_c["scopes"]),
              "чат: единственный контрол не в chat-области (%s)"
              % probe_c["scopes"])
        check(probe_c["readonly"] >= 1,
              "чат: модуль без chat-scope не показан read-only (%d)"
              % probe_c["readonly"])
        posts.clear()
        page.evaluate("() => { const t = document.querySelector"
                      "('[data-module-scope-toggle]'); if (t) t.click(); }")
        page.wait_for_timeout(1100)
        report["checks"]["posts_chat"] = posts
        check(bool(posts), "чат: переключатель не выполнил серверную операцию")
        check(all(bool(x["chat"]) for x in posts),
              "чат: запись ушла без X-Chat-Id (%s)" % posts)
        shot(page, "v21-1280-modules-chat")

        # ═══ 2. Desktop — «Речь и характер»: пять вкладок, «Мат» отдельно ══
        page.goto(base + "#/ai/speech", wait_until="load")
        page.wait_for_selector("[data-speech-area-nav]", timeout=20000)
        page.wait_for_timeout(900)
        sp = page.evaluate(PROBE_SPEECH)
        report["checks"]["speech"] = sp
        check(len(sp["tabs"]) == 5,
              "«Речь и характер»: вкладок %d, нужно 5 (%s)"
              % (len(sp["tabs"]), sp["tabs"]))
        for title in ("Личность", "Речь и стиль", "Мат", "Примеры",
                      "Правила и источники"):
            check(any(title in t for t in sp["tabs"]),
                  "нет вкладки «%s» (%s)" % (title, sp["tabs"]))
        check(sp["persona"], "по умолчанию не показан рабочий блок «Личность»")
        page.click('[data-speech-area="profanity"]')
        page.wait_for_timeout(900)
        sp2 = page.evaluate(PROBE_SPEECH)
        report["checks"]["speech_profanity"] = sp2
        check(sp2["profanity"], "«Мат»: вкладка не открывает редактор мата")
        check(sp2["active"] == "profanity", "«Мат»: вкладка не активна")
        page.click('[data-speech-area="rules"]')
        page.wait_for_timeout(900)
        sp3 = page.evaluate(PROBE_SPEECH)
        check(sp3["rules"], "«Правила и источники»: секция не отрисована")
        shot(page, "v21-1280-speech-rules")

        # ═══ 3. Desktop — «ИИ»: компактный хаб и deep-links ═══════════════
        page.goto(base + "#/ai", wait_until="load")
        page.wait_for_selector("[data-ai-hub]", timeout=20000)
        page.wait_for_timeout(900)
        hub = page.evaluate(PROBE_HUB)
        report["checks"]["ai_hub"] = hub
        check(hub["tiles"] >= 4, "«ИИ»: карточек хаба %d" % hub["tiles"])
        check(not hub["sameHeight"],
              "«ИИ»: карточки вытянуты в одинаковые пустые колонки (%s)"
              % hub["heights"])
        check(hub["chips"] >= 4,
              "«ИИ»: нет deep-links по вкладкам (%d)" % hub["chips"])
        page.click('[data-ai-speech-tab="profanity"]')
        page.wait_for_timeout(1300)
        sp4 = page.evaluate(PROBE_SPEECH)
        check(sp4["profanity"], "«ИИ»: deep-link не открыл вкладку «Мат»")
        shot(page, "v21-1280-ai-hub")

        # ═══ 4. Desktop — «Статус»: один блок здоровья, три сегмента ═════
        page.goto(base + "#/", wait_until="load")
        page.wait_for_selector("[data-status-health]", timeout=20000)
        page.wait_for_timeout(1100)
        st = page.evaluate(PROBE_STATUS)
        report["checks"]["status"] = st
        check(st["present"], "«Статус»: блока здоровья нет")
        check(st["segs"] == ["bot", "heartbeat", "server"],
              "«Статус»: сегменты %s" % st["segs"])
        check(st["innerCards"] <= 1,
              "«Статус»: внутри блока %d отдельных рамок" % st["innerCards"])
        check(st["line"], "«Статус»: нет компактной строки ошибок")
        # Адресный переход показывается при РЕАЛЬНЫХ проблемах; когда их нет —
        # честная строка «Новых ошибок нет» (никакой ложной ссылки).
        check(st["analytics"] or st["okLine"],
              "«Статус»: нет ни перехода в «Аналитику», ни честной строки «нет "
              "проблем» (%s)" % st)
        shot(page, "v21-1280-status")
        check(not errs, "1280: ошибок консоли нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 5. Мобильный 390 — нет «…», одна ⛶, drawer ниже системной зоны ═
        ctx = open_ctx(browser, 390, 844)
        page = new_page(ctx)
        merrs = []
        page.on("console", lambda m: merrs.append(m.text[:160])
                if m.type == "error" else None)
        page.goto(base + "#/", wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(1000)
        shell = page.evaluate(PROBE_SHELL)
        report["checks"]["shell_390"] = shell
        check(shell["moreTrigger"] == 0 and shell["moreMenu"] == 0,
              "390: «…» остался в шапке (%d/%d)"
              % (shell["moreTrigger"], shell["moreMenu"]))
        check(shell["geomEntry"] == 0,
              "390: «Диагностика геометрии» доступна обычному пользователю")
        check(shell["identityInMenu"] == 0, "390: дубль идентичности в меню")
        check(shell["fsCount"] == 1, "390: кнопок ⛶ %d" % shell["fsCount"])
        check(bool(shell["fsTap"]) and shell["fsTap"]["w"] >= 44
              and shell["fsTap"]["h"] >= 44,
              "390: tap-target ⛶ < 44px (%s)" % (shell["fsTap"],))
        check(shell["avatar"] >= 1 and shell["role"] >= 1,
              "390: аватар/роль исчезли из шапки")
        check(not shell["hScroll"], "390: горизонтальный скролл страницы")

        # Мобильный Статус: сегменты столбиком в одной панели.
        page.wait_for_selector("[data-status-health]", timeout=20000)
        page.wait_for_timeout(900)
        st390 = page.evaluate(PROBE_STATUS)
        report["checks"]["status_390"] = st390
        check(st390["segs"] == ["bot", "heartbeat", "server"],
              "390: сегменты %s" % st390["segs"])
        widths = [b["w"] for b in st390["segBoxes"]]
        check(len(widths) == 3 and max(widths) - min(widths) <= 2,
              "390: сегменты не в одной панели (%s)" % widths)
        shot(page, "v21-390-status")

        # Drawer: старт ниже фактической системной области (платформенные
        # инсеты — ТОЛЬКО реальные переменные, без «магических» пикселей).
        page.evaluate("""() => {
          const de = document.documentElement;
          de.style.setProperty('--tg-safe-area-inset-top', '44px');
          de.style.setProperty('--tg-content-safe-area-inset-top', '26px');
        }""")
        page.click("[data-drawer-trigger]")
        page.wait_for_timeout(600)
        drawer = page.evaluate(PROBE_DRAWER)
        report["checks"]["drawer_390"] = drawer
        check(drawer["present"] and drawer["visible"] == "visible",
              "390: drawer не открылся")
        check(drawer["top"] >= 69,
              "390: drawer налезает на Telegram chrome (top=%s при 70)"
              % drawer["top"])
        check(drawer["inView"], "390: drawer не помещается в видимую область")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        after = page.evaluate(
            "() => ({drawer: !!document.querySelector('.app-shell.drawer-open'),"
            " mask: !!document.querySelector('.drawer-backdrop')})")
        report["checks"]["drawer_closed_390"] = after
        check(not after["drawer"] and not after["mask"],
              "390: закрытый drawer оставил состояние/маску (%s)" % after)
        check(not merrs, "390: ошибок консоли нет (%s)" % merrs[:2])
        shot(page, "v21-390-drawer")
        ctx.close()

        # ═══ 6. Ландшафт 667×375 — одна строка шапки, ⛶ на месте ═════════
        ctx = open_ctx(browser, 667, 375)
        page = new_page(ctx)
        page.goto(base + "#/", wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(900)
        land = page.evaluate(PROBE_SHELL)
        report["checks"]["shell_667"] = land
        check(land["fsCount"] == 1, "667: кнопок ⛶ %d" % land["fsCount"])
        check(land["moreTrigger"] == 0, "667: «…» остался в шапке")
        check(not land["hScroll"], "667: горизонтальный скролл страницы")
        shot(page, "v21-667-landscape")
        ctx.close()

        browser.close()

    httpd.shutdown()
    report["fails"] = fails
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "asap-ui-v21-e2e.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    if fails:
        print("ASAP-UI-V21 FAILED (%d):" % len(fails))
        for f in fails:
            print(" -", f)
        return 1
    print("ASAP-UI-V21-OK")
    return 0


def main() -> int:
    out = DEFAULT_SHOTS
    argv = sys.argv[1:]
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    os.makedirs(out, exist_ok=True)
    return run(out)


if __name__ == "__main__":
    sys.exit(main())
