"""SOUL-12 (W7) dev-API + FS-HOTFIX 18.10 — e2e «нет заглушек вместо кнопки».

Харнесс: РЕАЛЬНЫЕ web/index.html + web/app.js + web/static/fullscreen-policy.js
на локальном http-сервере (tools/ui_round1025_matrix.py); SDK Telegram
подменяется ROUTE-ом (`/static/vendor/telegram-web-app.js`) — управляемая
матрица platform × capability × launch mode (tools/ui_asap8_w2_fullscreen_e2e.py).
Моки НЕ являются приёмкой реального клиента (SOUL-12.5): живой Telegram
Desktop/Android проверяется владельцем по чек-листу пост-деплой.

FS-HOTFIX 18.10 (директива владельца) — этот прогон фиксирует, что:
  * на Telegram Desktop кнопка ⛶ ВИДИМА и рабочая (прежний honest-disable и
    «поясняющая заглушка» удалены как НЕВЕРНОЕ решение);
  * в UI НЕТ ни диагностического стрипа, ни инструкций BotFather, ни
    технических строк platform/SDK/viewport/launch params, ни новых
    поясняющих блоков; тостов-объяснений при открытии нет;
  * dev-диагностика СОХРАНЕНА в объекте политики
    (window.__FullscreenPolicy.explain()/diagnostics()) — SOUL-12.1/12.3/12.4
    как dev-канал, включая launchParams из sessionStorage/hash (F1 разбора W7)
    и отсутствие секретов;
  * клиент без API (stand-alone/вне Telegram) → кнопка скрыта, и в UI
    по-прежнему нет заглушек.

Запуск: .venv/Scripts/python.exe tools/ui_soul1_w7_fullscreen_explain_e2e.py
Артефакты: plans/features/soul-1/evidence/fs-hotfix/soul12-devapi/**
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_round1025_matrix as M          # noqa: E402
import ui_asap8_w2_fullscreen_e2e as FH  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
PORT = M.PORT + 21
EVIDENCE = os.environ.get(
    "FS_SOUL12_EVIDENCE",
    os.path.join(REPO, "plans", "features", "soul-1", "evidence", "fs-hotfix",
                 "soul12-devapi"))
RAW = os.path.join(EVIDENCE, "_explain_results.json")
BASE_URL = "http://127.0.0.1:%d" % PORT

PROBE = r"""(() => {
  const de = document.documentElement;
  const btn = document.querySelector('.header-fs-btn');
  const header = document.querySelector('header.header-sticky');
  const hr = header ? header.getBoundingClientRect() : null;
  const pol = window.__FullscreenPolicy;
  let diagBlob = '';
  try { diagBlob = JSON.stringify(pol.diagnostics()); } catch (e) { diagBlob = 'ERR'; }
  const bodyText = (document.body.innerText || '');
  return {
    btnPresent: !!btn,
    btnRect: btn ? (() => { const r = btn.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height),
               y: Math.round(r.y) }; })() : null,
    hiddenClass: de.classList.contains('fs-hidden'),
    fsReason: de.getAttribute('data-fs-reason'),
    stripPresent: !!document.querySelector('[data-fs-diagnostics]'),
    diagStubMarkers: {
      header: bodyText.indexOf('Полноэкранный режим недоступен') >= 0,
      botfather: bodyText.indexOf('BotFather') >= 0,
      platformLine: bodyText.indexOf('platform:') >= 0,
      launchLine: bodyText.indexOf('Launch params') >= 0,
      sdkLine: bodyText.indexOf('SDK:') >= 0,
    },
    explain: pol.explain(),
    diagBlobLen: diagBlob.length,
    diagSecrets: ['initData', 'api_key', 'apikey', 'token', 'Bearer']
      .filter((m) => diagBlob.indexOf(m) >= 0),
    diagKeys: Object.keys(pol.diagnostics()).sort(),
    diagLaunch: pol.diagnostics().launchParams,
    toasts: Array.from(document.querySelectorAll('.toast-text'))
      .map((t) => t.textContent.trim()),
    headerRect: hr ? { y: Math.round(hr.y), h: Math.round(hr.height) } : null,
    hOverflow: de.scrollWidth > window.innerWidth + 1,
    scrollWidth: de.scrollWidth,
    innerWidth: window.innerWidth,
  };
})()"""


class Check:
    def __init__(self, name):
        self.name = name
        self.failures = []
        self.count = 0

    def ok(self, cond, msg):
        self.count += 1
        if not cond:
            self.failures.append(msg)
        return bool(cond)


def _server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def open_page(browser, cfg, viewport, sdk_js=None):
    sdk_js = sdk_js if sdk_js is not None else FH.mock_sdk_js(cfg)
    ctx = browser.new_context(viewport=viewport, device_scale_factor=2,
                              locale="ru-RU")
    page = ctx.new_page()
    page.route("**/static/vendor/telegram-web-app.js",
               lambda route: route.fulfill(
                   status=200, content_type="application/javascript", body=sdk_js))
    page.route("**/api/**", FH._api_handler_factory())
    page.set_viewport_size(viewport)
    page.goto(BASE_URL + "/#/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("header.header-sticky", state="visible", timeout=25000)
    return ctx, page


TDESKTOP = dict(platform="tdesktop", hasBoolean=True, isFullscreen=False,
                stableHeight=700, viewportHeight=768,
                safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
                contentSafeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0})
ANDROID = dict(platform="android", hasBoolean=True, isFullscreen=False,
               stableHeight=788, viewportHeight=844,
               safeAreaInset={"top": 0, "bottom": 0, "left": 0, "right": 0},
               contentSafeAreaInset={"top": 36, "bottom": 0, "left": 0, "right": 0})
VIEW_DESKTOP = {"width": 1024, "height": 768}
VIEW_MOBILE = {"width": 390, "height": 844}


def _no_ui_stubs(c, p, tag):
    c.ok(not p["stripPresent"], "%s: диагностического стрипа в UI нет" % tag)
    for key, val in p["diagStubMarkers"].items():
        c.ok(val is False, "%s: технической строки «%s» в UI нет" % (tag, key))
    c.ok(p["toasts"] == [], "%s: тостов-объяснений при открытии нет: %s"
         % (tag, p["toasts"]))


def scenario_tdesktop_working_button(browser, shots):
    """S1: tdesktop — кнопка есть и работает, заглушек нет, dev-API жив."""
    c = Check("S1_tdesktop_working_button")
    ctx, page = open_page(browser, TDESKTOP, VIEW_DESKTOP)
    early = page.evaluate(PROBE)
    page.wait_for_timeout(1200)
    p = page.evaluate(PROBE)
    c.ok(p["btnPresent"], "tdesktop: кнопка ⛶ рендерится (FS-HOTFIX 18.10)")
    c.ok(not p["hiddenClass"], "tdesktop: html.fs-hidden не выставлен")
    c.ok(p["fsReason"] is None, "tdesktop: data-fs-reason отсутствует (нет причины)")
    c.ok(p["explain"]["code"] == "" and p["explain"]["text"] == "",
         "tdesktop: explain() не выдумывает причину")
    _no_ui_stubs(c, p, "tdesktop")
    c.ok(p["btnRect"] and p["btnRect"]["w"] >= 44 and p["btnRect"]["h"] >= 44,
         "tdesktop: hit-target >= 44x44 (%s)" % (p["btnRect"],))
    # dev-API сохранён (SOUL-12.1/12.3/12.4 как dev-канал)
    c.ok(not p["diagSecrets"], "diagnostics() без секретов: %s" % p["diagSecrets"])
    c.ok(p["diagBlobLen"] > 100, "diagnostics() реально отдаёт данные")
    for key in ("platform", "sdkVersion", "launchParams", "isFullscreenSupported",
                "actualFullscreen", "hasRequestFullscreen", "hasExitFullscreen",
                "stableHeight", "safeAreaInset", "contentSafeAreaInset",
                "initCount", "clickResult", "trace", "warnings",
                "reasonText", "nextStep"):
        c.ok(key in p["diagKeys"], "diagnostics(): поле %s" % key)
    # F1: launch params читаются из sessionStorage (пишет официальный SDK)
    c.ok((p["diagLaunch"] or {}).get("tgWebAppPlatform") == "tdesktop",
         "F1: launchParams.tgWebAppPlatform = tdesktop (storage/hash), факт %s"
         % (p["diagLaunch"],))
    c.ok((p["diagLaunch"] or {}).get("tgWebAppData") is None,
         "F1: tgWebAppData не выносится (allowlist)")
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [], "tdesktop: авто-вызовов fullscreen API на старте нет")
    c.ok(early["headerRect"] and p["headerRect"] and
         early["headerRect"]["y"] == p["headerRect"]["y"] and
         early["headerRect"]["h"] == p["headerRect"]["h"],
         "header не «прыгает» между ранним и поздним замером: %s → %s"
         % (early["headerRect"], p["headerRect"]))
    c.ok(not p["hOverflow"], "нет горизонтального overflow (%s<=%s)"
         % (p["scrollWidth"], p["innerWidth"]))
    # кнопка реально дёргает SDK
    page.click(".header-fs-btn")
    page.wait_for_timeout(200)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == ["requestFullscreen"],
         "tdesktop: тап = реальный requestFullscreen (факт %s)" % calls)
    page.screenshot(path=os.path.join(shots, "S1_tdesktop_working_1024.png"))
    ctx.close()
    return c, p


def scenario_tdesktop_launch(browser, shots):
    """S2: tdesktop + Launch Mode=Fullscreen — без авто-exit, кнопка = выход."""
    c = Check("S2_tdesktop_launch_fullscreen")
    cfg = dict(TDESKTOP, isFullscreen=True)
    ctx, page = open_page(browser, cfg, VIEW_DESKTOP)
    page.wait_for_timeout(1200)
    p = page.evaluate(PROBE)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == [], "авто-выхода из стартового fullscreen НЕТ: %s" % calls)
    c.ok(p["btnPresent"], "кнопка видима (не заглушка)")
    title = page.evaluate(
        "document.querySelector('.header-fs-btn').getAttribute('title')")
    c.ok(title == "Выйти из полноэкранного режима",
         "кнопка сразу предлагает ВЫХОД: %s" % title)
    _no_ui_stubs(c, p, "tdesktop-launch")
    page.click(".header-fs-btn")
    page.wait_for_timeout(200)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls == ["exitFullscreen"], "выход по кнопке = exitFullscreen (%s)" % calls)
    page.screenshot(path=os.path.join(shots, "S2_tdesktop_launch_1024.png"))
    ctx.close()
    return c, p


def scenario_supported_unchanged(browser, shots):
    """S3: поддерживаемый клиент (android) — кнопка + ack-цикл, DOM чист."""
    c = Check("S3_supported_unchanged")
    ctx, page = open_page(browser, ANDROID, VIEW_MOBILE)
    page.wait_for_selector(".header-fs-btn", state="attached", timeout=20000)
    page.wait_for_timeout(900)
    p = page.evaluate(PROBE)
    c.ok(p["btnPresent"], "android: кнопка на месте")
    _no_ui_stubs(c, p, "android")
    c.ok(p["btnRect"] and p["btnRect"]["w"] >= 44 and p["btnRect"]["h"] >= 44,
         "android: hit-target >= 44x44 (%s)" % (p["btnRect"],))
    c.ok(p["explain"]["code"] == "", "android: объяснять нечего (code='')")
    page.click(".header-fs-btn")
    page.wait_for_timeout(150)
    calls = page.evaluate("window.__tma.__calls")
    c.ok(calls.count("requestFullscreen") == 1, "android: ровно 1 requestFullscreen")
    page.evaluate("window.__tma.isFullscreen = true; "
                  "window.__tma.__emit('fullscreenChanged')")
    page.wait_for_timeout(250)
    c.ok(page.evaluate("window.__FullscreenPolicy.state().actualFullscreen") is True,
         "android: ack подтвердил фактический fullscreen")
    c.ok(not page.evaluate(PROBE)["stripPresent"],
         "android: после ack стрип не появился")
    page.screenshot(path=os.path.join(shots, "S3_supported_390.png"))
    ctx.close()
    return c, p


def scenario_no_telegram(browser, shots):
    """S4: вне Telegram — кнопка скрыта, заглушек нет, dev-API отвечает фактом."""
    c = Check("S4_no_telegram")
    ctx, page = open_page(browser, TDESKTOP, {"width": 1280, "height": 800},
                          sdk_js=FH.NO_SDK_JS)
    page.wait_for_timeout(1200)
    p = page.evaluate(PROBE)
    c.ok(not p["btnPresent"], "вне TG кнопка не вводит в заблуждение")
    c.ok(p["fsReason"] == "no_telegram_context", "причина зафиксирована")
    _no_ui_stubs(c, p, "stand-alone")
    c.ok(page.evaluate("window.__FullscreenPolicy.diagnostics().platform") == "unknown",
         "dev-API: вне TG platform=unknown")
    ctx.close()
    return c, p


def scenario_narrow_layout(browser, shots):
    """S5: узкие ширины — кнопка/лейаут без изменений, техстрок нет."""
    c = Check("S5_narrow_layout")
    rows = []
    for w, h, tag in ((320, 700, "320"), (390, 844, "390")):
        ctx, page = open_page(browser, TDESKTOP, {"width": w, "height": h})
        page.wait_for_timeout(1100)
        p = page.evaluate(PROBE)
        c.ok(p["btnPresent"], "%s: кнопка видима" % tag)
        _no_ui_stubs(c, p, tag)
        c.ok(not p["hOverflow"], "%s: без h-overflow (%s<=%s)"
             % (tag, p["scrollWidth"], p["innerWidth"]))
        rows.append({"width": w, "height": h, "btn": p["btnRect"],
                     "hOverflow": p["hOverflow"],
                     "header": p["headerRect"]})
        page.screenshot(path=os.path.join(shots, "S5_mobile_%s.png" % tag))
        ctx.close()
    return c, {"rows": rows}


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(EVIDENCE, exist_ok=True)
    httpd = _server()
    print("[fs-hotfix] server on %d" % PORT)
    scenarios = [scenario_tdesktop_working_button, scenario_tdesktop_launch,
                 scenario_supported_unchanged, scenario_no_telegram,
                 scenario_narrow_layout]
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in scenarios:
            try:
                c, extra = fn(browser, EVIDENCE)
                status = "PASS" if not c.failures else "FAIL"
                print("[fs-hotfix] %-32s %s (%d checks)" % (c.name, status, c.count))
                for f in c.failures:
                    print("    FAIL: %s" % f)
                results.append({"scenario": c.name, "status": status,
                                "checks": c.count, "failures": c.failures,
                                "extra": extra})
            except Exception as exc:  # noqa: BLE001
                print("[fs-hotfix] %-32s ERROR: %s" % (fn.__name__, exc))
                results.append({"scenario": fn.__name__, "status": "ERROR",
                                "error": str(exc)[:500]})
        browser.close()
    httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    total = sum(r.get("checks", 0) for r in results)
    failed = [r for r in results if r["status"] != "PASS"]
    print("[fs-hotfix] итог: %d/%d PASS, проверок %d, артефакты: %s"
          % (len(results) - len(failed), len(results), total, EVIDENCE))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
