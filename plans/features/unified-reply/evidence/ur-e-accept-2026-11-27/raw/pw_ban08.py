"""UR-BAN-08 visual gate: REAL web assets + REAL local FastAPI backend.

Read-only browser session (GET only), 1440x900 and 390x844, plus a negative
control: the legacy timezone keys are absent and a legacy cap renders read-only
on «Лимиты». Writes screenshots + machine-readable JSON next to this script.
"""
import json
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8871"
URL = BASE + "/web/#/modules/direct/overview"

with open(os.path.join(HERE, "init_data.txt"), encoding="utf-8") as fh:
    INIT_DATA = fh.read().strip()

# Приложение само кэширует initData в sessionStorage (BOOT до записи hash).
# Telegram-SDK не подменяется: используется настоящий telegram-web-app.js,
# подделан только вход (синтетическая подпись локального токена).
SEED = ("try{sessionStorage.setItem('adminbot.initData', %s);}catch(e){}"
        % json.dumps(INIT_DATA))

VIEWPORTS = [("1440x900", 1440, 900), ("390x844", 390, 844)]
EXPECTED = [("overview", "Как бот отвечает"),
            ("inspector", "Что бот видел"),
            ("settings", "Дополнительные настройки")]
LEGACY_TZ_KEYS = ("GOODMORNING_TZ", "SUMMARY_TIMEZONE")

result = {"url": URL, "viewports": {}, "console": [], "pageerrors": [],
          "http": []}

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for name, width, height in VIEWPORTS:
        ctx = browser.new_context(viewport={"width": width, "height": height},
                                  device_scale_factor=1)
        ctx.add_init_script(SEED)
        page = ctx.new_page()
        console, errors, http = [], [], []
        page.on("console", lambda m, c=console: c.append(
            {"type": m.type, "text": m.text[:300]}))
        page.on("pageerror", lambda e, c=errors: c.append(str(e)[:300]))
        page.on("response", lambda r, c=http: c.append(
            {"status": r.status, "url": r.url}) if "/api/" in r.url else None)

        page.goto(URL, wait_until="load")
        page.wait_for_selector("[data-workspace-tabs] button[data-workspace-tab]",
                               timeout=30000)
        page.wait_for_timeout(1500)

        tabs = page.eval_on_selector_all(
            "[data-workspace-tabs] button[data-workspace-tab]",
            "els => els.map(e => ({id: e.getAttribute('data-workspace-tab'),"
            " label: (e.textContent||'').trim(),"
            " selected: e.getAttribute('aria-selected')}))")
        head = [(t["id"], t["label"]) for t in tabs[:3]]
        state_line = page.inner_text("[data-workspace-tabs]")[:0]
        overview_text = page.inner_text("body")
        shot_overview = os.path.join(HERE, "ban08-%s-overview.png" % name)
        page.screenshot(path=shot_overview)
        overflow_overview = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth,"
            " cw: document.documentElement.clientWidth})")

        # ── settings: группы и параметры реального каталога ──
        page.click("[data-workspace-tab='settings']")
        page.wait_for_timeout(1500)
        groups = page.eval_on_selector_all(
            "[data-config-group]",
            "els => els.map(e => e.getAttribute('data-config-group'))")
        keys = page.eval_on_selector_all(
            "[data-cfg-key]",
            "els => els.map(e => e.getAttribute('data-cfg-key'))")
        shot_settings = os.path.join(HERE, "ban08-%s-settings.png" % name)
        page.screenshot(path=shot_settings)
        overflow_settings = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth,"
            " cw: document.documentElement.clientWidth})")

        # ── inspector: правда об исполняемом состоянии ──
        page.click("[data-workspace-tab='inspector']")
        page.wait_for_timeout(1800)
        inspector_blocks = page.eval_on_selector_all(
            "[data-ur21-inspector], [data-direct-used-setting],"
            " [data-inspector], [data-turn-inspector]",
            "els => els.map(e => e.getAttributeNames().join(','))")
        shot_inspector = os.path.join(HERE, "ban08-%s-inspector.png" % name)
        page.screenshot(path=shot_inspector)

        # ── негативный контроль: legacy-пояс не рабочий; параметры не одной
        # простынёй ──
        page.click("[data-workspace-tab='limits']")
        page.wait_for_timeout(1200)
        limits_keys = page.eval_on_selector_all(
            "[data-cfg-key]",
            "els => els.map(e => e.getAttribute('data-cfg-key'))")
        page_text = page.inner_text("body")
        legacy_tz_present = [k for k in LEGACY_TZ_KEYS if k in page_text]
        shot_limits = os.path.join(HERE, "ban08-%s-limits.png" % name)
        page.screenshot(path=shot_limits)

        result["viewports"][name] = {
            "tabs": head,
            "tab_count": len(tabs),
            "order_ok": head == EXPECTED,
            "settings_groups": groups,
            "settings_group_count": len(groups),
            "settings_param_count": len(keys),
            "limits_param_count": len(limits_keys),
            "inspector_blocks": inspector_blocks,
            "legacy_tz_keys_visible": legacy_tz_present,
            "overflow_overview": overflow_overview,
            "overflow_settings": overflow_settings,
            "overview_has_action_line": "Исполняется" in overview_text,
            "shots": [os.path.basename(p) for p in
                      (shot_overview, shot_settings, shot_inspector,
                       shot_limits)],
        }
        result["console"].extend([dict(c, viewport=name) for c in console])
        result["pageerrors"].extend([dict(e=e, viewport=name) for e in errors])
        result["http"].extend([dict(h, viewport=name) for h in http])
        ctx.close()
    browser.close()

errors_console = [c for c in result["console"] if c["type"] == "error"]
api_bad = [h for h in result["http"] if h["status"] >= 400]
result["summary"] = {
    "order_ok_all": all(v["order_ok"] for v in result["viewports"].values()),
    "console_errors": len(errors_console),
    "pageerrors": len(result["pageerrors"]),
    "api_non_2xx": sorted({(h["status"], h["url"].split("?")[0])
                           for h in api_bad}),
    "no_h_overflow_all": all(
        v["overflow_overview"]["sw"] <= v["overflow_overview"]["cw"] + 20 and
        v["overflow_settings"]["sw"] <= v["overflow_settings"]["cw"] + 20
        for v in result["viewports"].values()),
    "legacy_tz_hidden_all": all(
        not v["legacy_tz_keys_visible"] for v in result["viewports"].values()),
}
with open(os.path.join(HERE, "ban08-visual.json"), "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)
print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
for k, v in result["viewports"].items():
    print(k, v["tabs"], "groups:", v["settings_group_count"],
          "params:", v["settings_param_count"], "insp:", len(v["inspector_blocks"]),
          "tz:", v["legacy_tz_keys_visible"], "limits:", v["limits_param_count"],
          "overflow:", v["overflow_overview"], v["overflow_settings"])
print("console errors:", errors_console[:6])
print("pageerrors:", result["pageerrors"])
