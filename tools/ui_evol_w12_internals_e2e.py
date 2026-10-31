"""EVOL-034..042 (W12) - живая проверка внутренних экранов в Chromium.

Что проверяет (реальные файлы web/index.html + web/app.js + web/static/app.css,
API - стенд `tools/ui_round1025_matrix.py`, боевой Telegram не задействован):

  * EVOL-037 - один поиск/command palette: `Ctrl+K` открывает, Esc закрывает,
    ввод текста не перехватывается, результаты сгруппированы, выбор открывает
    нужный маршрут с `?focus=` и фокусирует конкретный элемент; на 390 поиск
    открывается полноэкранным листом из меню «⋯»/drawer, секретов в выдаче нет;
  * EVOL-038 - полноэкранный редактор промпта и поиск в каталоге промптов;
  * EVOL-042 - явные режимы инспектора «последний реальный вызов» vs
    «предпросмотр», у предпросмотра всегда метка «не отправлено»;
  * EVOL-035/040 - семантические группы тумблеров инициативы, master-ключ
    внутри модуля не редактируется, предохранители - в «Дополнительно».

Запуск: py -3 tools\\ui_evol_w12_internals_e2e.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ui_round1025_matrix as M  # noqa: E402

PORT = 8823
DEFAULT_OUT = os.path.join(ROOT, "plans", "features", "evol", "audit", "evidence")

PROBE_PALETTE = r"""
() => {
  const root = document.querySelector('[data-command-palette]');
  if (!root) return {open: false};
  const panel = root.querySelector('.palette-panel');
  const input = root.querySelector('[data-palette-input]');
  const r = panel.getBoundingClientRect();
  const rows = Array.from(root.querySelectorAll('[data-palette-item]'));
  return {
    open: true,
    panelW: Math.round(r.width), panelH: Math.round(r.height),
    panelTop: Math.round(r.top),
    vh: window.visualViewport ? Math.round(window.visualViewport.height)
                              : window.innerHeight,
    inputFocused: document.activeElement === input,
    inputs: root.querySelectorAll('input').length,
    ph: input ? input.placeholder : null,
    bg: panel ? getComputedStyle(panel).backgroundColor : null,
    bf: panel ? (getComputedStyle(panel).backdropFilter || 'none') : null,
    inputValue: input ? input.value : null,
    inputH: input ? Math.round(input.getBoundingClientRect().height) : null,
    rows: rows.length,
    groups: Array.from(root.querySelectorAll('[data-palette-group]'))
      .map((g) => g.getAttribute('data-palette-group')),
    dests: rows.map((b) => b.getAttribute('data-palette-dest')),
    scopeLabel: (root.querySelector('[data-palette-scope]') || {}).textContent,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}
"""

PROBE_INITIATIVE = r"""
() => {
  const root = document.querySelector('[data-initiative-flags]');
  if (!root) return {found: false};
  const groups = Array.from(root.querySelectorAll('[data-initiative-group]'))
    .map((g) => g.getAttribute('data-initiative-group'));
  const adv = root.querySelector('[data-initiative-advanced]');
  return {
    found: true,
    groups: groups,
    perChat: !!root.querySelector('[data-initiative-per-chat]'),
    masterToggle: root.querySelectorAll('[data-cfg-key="flags.initiative_enabled"]').length,
    masterLink: !!root.querySelector('[data-initiative-master-link]'),
    advancedClosed: adv ? !adv.open : null,
    advancedKeys: adv ? Array.from(adv.querySelectorAll('[data-initiative-key]'))
      .map((el) => el.getAttribute('data-initiative-key')) : [],
    primaryKeys: Array.from(root.querySelectorAll('[data-initiative-key]'))
      .filter((el) => !adv || !adv.contains(el))
      .map((el) => el.getAttribute('data-initiative-key')),
  };
}
"""

PROBE_INSPECTOR = r"""
() => {
  const bar = document.querySelector('[data-inspector-modes]');
  if (!bar) return {found: false};
  return {
    found: true,
    modes: Array.from(bar.querySelectorAll('[data-inspector-mode]'))
      .map((b) => b.getAttribute('data-inspector-mode')),
    checked: Array.from(bar.querySelectorAll('[data-inspector-mode]'))
      .filter((b) => b.getAttribute('aria-checked') === 'true')
      .map((b) => b.getAttribute('data-inspector-mode')),
    notSent: !!document.querySelector('[data-inspector-not-sent]'),
    noSnapshot: !!document.querySelector('[data-inspector-no-snapshot]'),
    exact: !!document.querySelector('[data-speech-exact]'),
    preview: !!document.querySelector('[data-speech-preview-payload]'),
    honest: (document.querySelector('[data-inspector-honest-note]') || {})
      .textContent.trim().slice(0, 120),
  };
}
"""

PROBE_PROMPT_EDITOR = r"""
() => {
  const card = document.querySelector('[data-prompt-editor]');
  const ta = document.querySelector('[data-prompt-textarea]');
  const search = document.querySelector('[data-prompt-tree-search]');
  return {
    editor: !!card,
    full: !!(card && card.classList.contains('prompt-editor--full')),
    textarea: !!ta,
    meta: !!document.querySelector('[data-prompt-editor-meta]'),
    fullscreenBtn: !!document.querySelector('[data-prompt-fullscreen]'),
    search: !!search,
    hScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}
"""


SPEECH_INSPECTOR_STUB = {
    "chat_id": None,
    "last_run_present": False,
    "last_run_note": "Снимок реального вызова ещё не записан: ниже — только "
                     "предпросмотр сборки (не отправлено).",
    "sent": {},
    "sent_note": "",
    "sent_writers": ["direct"],
    "preview": {
        "manifest_id": "stub-manifest-1",
        "tokens_total": 128,
        "layer_order": True,
        "versions": {},
        "conflicts": [],
        "preview_note": "сборка локальная",
        "layers": [],
        "system_masked": "system prompt (маскировано)",
        "style": None,
    },
    "core": {"level": "full", "reason": "factory", "active_revision": "r1",
             "chars": 10, "factory_revisions": {}},
    "exact": None,
    "last_call": {},
    "hierarchy": [],
    "skip_reasons": [],
    "conflicts_detail": {"detected_total": 0, "coverage_note": "проверено",
                         "classes": []},
    "masked": True,
    "trace_coverage": [],
    "retention": "in-memory bounded",
    "gates": {},
}


class _Handler(SimpleHTTPRequestHandler):
    root = ROOT

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


def _routes(route):
    url = route.request.url.split("?")[0]
    if url.endswith("/api/speech/inspector"):
        payload = SPEECH_INSPECTOR_STUB
    elif url.endswith("/api/config"):
        hdrs = route.request.headers or {}
        payload = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                   else M.CONFIG_STUB)
    else:
        payload = M._stub_for(route.request.url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(payload))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    fails = []
    report = {"viewports": {}, "checks": {}}

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = "http://127.0.0.1:%d/web/index.html" % PORT

    def check(cond, msg):
        if not cond:
            fails.append(msg)
        return cond

    def shot(page, name):
        try:
            page.screenshot(path=os.path.join(out_dir, "w12-%s.png" % name))
        except Exception:  # noqa: BLE001
            pass

    def open_ctx(browser, w, h):
        phone = w <= 430
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=2 if phone else 1,
            is_mobile=phone, has_touch=phone,
        )
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _routes)
        return ctx

    def boot(page, route="#/"):
        page.goto(base_url + route, wait_until="load")
        page.wait_for_selector(".app-shell", timeout=20000)
        page.wait_for_timeout(500)

    def open_palette(page):
        page.evaluate("() => window.__adminbotVm.openPalette()")
        page.wait_for_selector("[data-command-palette]", timeout=8000)
        page.wait_for_timeout(200)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--disable-lcd-text"])

        # ═══ 1. Desktop 1280: Ctrl+K, поиск, фокус, Esc ═══
        ctx = open_ctx(browser, 1280, 900)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page)
        has_entry = page.evaluate(
            "() => !!document.querySelector('[data-palette-open]')")
        check(has_entry, "1280: точка входа поиска в topbar есть")
        closed = page.evaluate("() => !document.querySelector('[data-command-palette]')")
        check(closed, "1280: палитра закрыта по умолчанию")
        page.keyboard.press("Control+K")
        page.wait_for_selector("[data-command-palette]", timeout=8000)
        page.wait_for_timeout(250)
        st = page.evaluate(PROBE_PALETTE)
        report["viewports"]["1280"] = {"palette": st}
        check(st["inputFocused"], "1280: Ctrl+K фокусирует поле поиска")
        # Ввод текста не перехватывается: обычная буква просто попадает в поле.
        page.keyboard.type("инициатива")
        page.wait_for_timeout(250)
        st = page.evaluate(PROBE_PALETTE)
        report["checks"]["palette_settings"] = st
        check(st["rows"] >= 1, "1280: поиск вернул результаты")
        check("module" in st["groups"] or "setting" in st["groups"],
              "1280: результаты сгруппированы (модуль/настройка)")
        shot(page, "1280-palette")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check(page.evaluate("() => !document.querySelector('[data-command-palette]')"),
              "1280: Esc закрывает палитру")

        # Секреты не индексируются.
        open_palette(page)
        page.keyboard.type("api_key")
        page.wait_for_timeout(250)
        sec = page.evaluate(PROBE_PALETTE)
        report["checks"]["palette_secrets"] = sec
        check(all("keys." not in (d or "") for d in sec["dests"]),
              "1280: ключи/секреты не попадают в выдачу")

        # Выбор результата: маршрут + ?focus= + фокус на реальном элементе.
        page.evaluate("() => window.__adminbotVm.closePalette()")
        open_palette(page)
        page.keyboard.type("heartbeat")
        page.wait_for_timeout(300)
        picked = page.evaluate(r"""
            () => {
              const rows = Array.from(document.querySelectorAll('[data-palette-item]'));
              const row = rows.find((r) => (r.getAttribute('data-palette-dest') || '')
                .indexOf('/modules/') >= 0) || rows[0];
              if (!row) return null;
              const id = row.getAttribute('data-palette-item');
              row.click();
              return id;
            }
        """)
        page.wait_for_timeout(1200)
        href = page.evaluate("() => window.location.hash")
        focused = page.evaluate(r"""
            () => {
              const el = document.activeElement;
              return el ? (el.getAttribute('data-cfg-key')
                || el.getAttribute('data-focus-id') || el.tagName) : null;
            }
        """)
        report["checks"]["palette_navigation"] = {
            "picked": picked, "hash": href, "focused": focused}
        check(picked is not None, "1280: результат выбора найден")
        check("focus=" in href, "1280: маршрут несёт ?focus= (deep-link)")
        check(bool(focused), "1280: после выбора элемент получил фокус")
        shot(page, "1280-palette-target")
        check(not errs, "1280: ошибок консоли нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 2. Мобильный 390: полноэкранный лист из «⋯»/drawer ═══
        ctx = open_ctx(browser, 390, 844)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page)
        check(page.evaluate(
            "() => !document.querySelector('[data-palette-open]')"),
            "390: шапка не раздута кнопкой поиска")
        page.evaluate("() => window.__adminbotVm.toggleDrawer()")
        page.wait_for_timeout(250)
        check(page.evaluate(
            "() => !!document.querySelector('[data-palette-open-drawer]')"),
            "390: вход поиска есть в навигации (drawer)")
        page.evaluate("() => window.__adminbotVm.closeDrawer()")
        open_palette(page)
        page.keyboard.type("юмор")
        page.wait_for_timeout(300)
        mob = page.evaluate(PROBE_PALETTE)
        report["viewports"]["390"] = {"palette": mob}
        check(mob["panelW"] >= 380, "390: лист поиска занимает ширину экрана")
        check(abs(mob["panelH"] - mob["vh"]) <= 3,
              "390: лист поиска полноэкранный (h=%s vh=%s)"
              % (mob["panelH"], mob["vh"]))
        check(mob["inputFocused"], "390: поле поиска в фокусе (клавиатура)")
        check(not mob["hScroll"], "390: нет горизонтального скролла")
        shot(page, "390-palette")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check(page.evaluate("() => !document.querySelector('[data-command-palette]')"),
              "390: Esc закрывает лист поиска")
        check(not errs, "390: ошибок консоли нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 3. EVOL-038: полноэкранный редактор промпта ═══
        ctx = open_ctx(browser, 1280, 900)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page)
        tgt = page.evaluate(r"""
            () => {
              const vm = window.__adminbotVm;
              const m = (vm.modules || []).find((x) => vm.workspacePromptItems(x).length > 0);
              if (!m) return null;
              const it = vm.workspacePromptItems(m)[0];
              const slug = vm.routeSlugOf(m);
              vm.navigateTo('#/ai/prompts/' + slug + '/' + it.key);
              return {slug: slug, key: it.key};
            }
        """)
        page.wait_for_timeout(1200)
        pw_state = page.evaluate(PROBE_PROMPT_EDITOR)
        report["checks"]["prompt_editor"] = pw_state
        check(tgt is not None and pw_state["editor"],
              "1280: редактор промпта открылся")
        check(pw_state["search"], "1280: поиск в каталоге промптов есть")
        check(pw_state["meta"], "1280: у редактора виден prompt_id/потребитель/scope")
        check(pw_state["fullscreenBtn"], "1280: есть полноэкранный режим")
        page.click("[data-prompt-fullscreen]")
        page.wait_for_timeout(300)
        full = page.evaluate(PROBE_PROMPT_EDITOR)
        check(full["full"], "1280: полноэкранный редактор включился")
        check(full["textarea"], "1280: поле промпта доступно в полноэкранном режиме")
        shot(page, "1280-prompt-fullscreen")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check(not page.evaluate(PROBE_PROMPT_EDITOR)["full"],
              "1280: Esc выходит из полноэкранного редактора")
        check(not errs, "1280: ошибок консоли в редакторе нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 4. EVOL-042: режимы инспектора ═══
        ctx = open_ctx(browser, 1280, 900)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page, "#/ai/speech")
        page.wait_for_timeout(600)
        page.evaluate("() => window.__adminbotVm.openSpeechSection('inspector')")
        page.wait_for_timeout(1500)
        insp = page.evaluate(PROBE_INSPECTOR)
        report["checks"]["inspector"] = insp
        if check(insp["found"], "1280: у инспектора есть явные режимы"):
            check(insp["modes"] == ["real", "preview"],
                  "1280: ровно два режима (реальный/предпросмотр)")
            check(insp["checked"] == ["real"], "1280: по умолчанию реальный вызов")
            check(insp["noSnapshot"],
                  "1280: без подтверждённого снимка режим честно пуст")
            check(not insp["exact"],
                  "1280: карточка реального payload не подменяет снимок")
            check(not insp["preview"], "1280: предпросмотр не смешан с реальным вызовом")
            page.click('[data-inspector-mode="preview"]')
            page.wait_for_timeout(400)
            prev = page.evaluate(PROBE_INSPECTOR)
            report["checks"]["inspector_preview"] = prev
            check(prev["notSent"], "1280: предпросмотр помечен «не отправлено»")
            check(prev["preview"], "1280: предпросмотр показывает собранный payload")
            shot(page, "1280-inspector-preview")
            page.click('[data-inspector-mode="real"]')
            page.wait_for_timeout(300)
            check(page.evaluate(PROBE_INSPECTOR)["checked"] == ["real"],
                  "1280: возврат в режим реального вызова")
        check(not errs, "1280: ошибок консоли в инспекторе нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 5. EVOL-035/040: группы тумблеров инициативы ═══
        ctx = open_ctx(browser, 1280, 900)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page, "#/modules/initiative/settings")
        page.wait_for_timeout(1200)
        ini = page.evaluate(PROBE_INITIATIVE)
        report["checks"]["initiative"] = ini
        if check(ini["found"], "1280: секция тумблеров инициативы отрисована"):
            check("auto" in ini["groups"] and "schedule" in ini["groups"],
                  "1280: основные группы на первом плане")
            check(ini["masterToggle"] == 0,
                  "1280: master-ключ не редактируется внутри модуля")
            check(ini["masterLink"], "1280: есть вход в каталог для master-ключа")
            check(ini["advancedClosed"], "1280: предохранители свёрнуты в «Дополнительно»")
            keys = ini["primaryKeys"] + ini["advancedKeys"]
            check(len(keys) == len(set(keys)), "1280: нет дублирующих тумблеров")
            check("flags.send_recheck_enabled" in ini["advancedKeys"],
                  "1280: проверка перед отправкой — в «Дополнительно»")
        shot(page, "1280-initiative-settings")
        # Переключение предохранителя не включает публикацию само по себе:
        # читаем состояние соседних ключей через vm (truth table, без отправки).
        truth = page.evaluate(r"""
            () => {
              const vm = window.__adminbotVm;
              const byKey = {};
              (vm.configItems || []).forEach((it) => { byKey[it.key] = it.value; });
              return {
                recheck: byKey['flags.send_recheck_enabled'],
                publish: byKey['flags.initiative_diagnostics_publish_enabled'],
                master: byKey['flags.initiative_enabled'],
                perChat: byKey['initiative.enabled'],
              };
            }
        """)
        report["checks"]["initiative_truth"] = truth
        check(truth.get("publish") is not None,
              "1280: ключ реальной публикации присутствует (не выдуман)")
        check(not (truth.get("publish") and not truth.get("master")),
              "1280: публикация не может быть активной при выключенном мастере")
        check(not errs, "1280: ошибок консоли в модуле нет (%s)" % errs[:2])
        ctx.close()

        # ═══ 6. EVOL-036: обзор модуля — состояния + последнее действие + 1 действие
        ctx = open_ctx(browser, 1280, 900)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
        boot(page, "#/modules/initiative")
        page.wait_for_selector("[data-workspace-overview]", timeout=20000)
        page.wait_for_timeout(600)
        ov = page.evaluate(r"""
            () => ({
              overview: !!document.querySelector('[data-workspace-overview]'),
              actions: !!document.querySelector('[data-module-overview-actions]'),
              primary: !!document.querySelector('[data-module-primary-action]'),
              last: (document.querySelector('[data-module-last-action]') || {})
                .textContent.trim().slice(0, 80),
              scope: (document.querySelector('[data-workspace-scope]') || {})
                .textContent.trim(),
              tabs: document.querySelectorAll('[data-workspace-tab]').length,
            })
        """)
        report["checks"]["module_overview"] = ov
        check(ov["overview"] and ov["actions"],
              "1280: обзор модуля = состояния + действия")
        check(ov["primary"], "1280: у обзора есть одно основное действие")
        check(bool(ov["last"]), "1280: обзор показывает последнее действие/его отсутствие")
        check(ov["tabs"] >= 2, "1280: подразделы модуля доступны из шапки")
        shot(page, "1280-module-overview")
        check(not errs, "1280: ошибок консоли в обзоре нет (%s)" % errs[:2])
        ctx.close()

        browser.close()

    httpd.shutdown()
    report["fails"] = fails
    with open(os.path.join(out_dir, "w12-internals-e2e.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if fails:
        print("EVOL-W12-INTERNALS FAILED (%d):" % len(fails))
        for f in fails:
            print(" -", f)
        return 1
    print("EVOL-W12-INTERNALS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
