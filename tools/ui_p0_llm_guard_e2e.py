# -*- coding: utf-8 -*-
"""P0 SMART transport (2.58.206) — Playwright-проверка админки LLM.

Реальные `web/index.html` + `web/app.js` на локальном http-сервере, `/api/*`
перехватываются (без бэкенда/БД, R17: без секретов). Проверяет:

  * `#/ai/llm`: первая видимая группа — `prov_policy` «Время ответа и защита»;
  * блок `llm_guard` ВИДЕН (не внутри свёрнутых «Расширенных настроек»);
  * «Расширенные системные» (`details.advanced`) закрыты по умолчанию
    (`details.open === false`);
  * поля видны: «Таймаут одного запроса, сек», «Повторов при сбое»,
    «Предел одной основной попытки, сек»;
  * note сообщает «Весь бот», «без перезапуска» и «не ограничивает всё
    исследование»;
  * нет горизонтального overflow.

Запуск: .venv\\Scripts\\python.exe tools\\ui_p0_llm_guard_e2e.py
Артефакт: plans/features/smart-corrective-01/evidence/p0-2026-11-16/
          llm-guard-ui-e2e.json
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

VIEWPORTS = [(1280, 800), (390, 844)]
RAW = os.path.join(REPO, "plans", "features", "smart-corrective-01",
                   "evidence", "p0-2026-11-16", "llm-guard-ui-e2e.json")

PROBE_JS = """
() => {
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && cs.display !== 'none'
      && cs.visibility !== 'hidden';
  };
  const groups = Array.from(document.querySelectorAll('[data-provider-group]'));
  const groupEl = document.querySelector('[data-provider-group="prov_policy"]');
  const block = document.querySelector('[data-block="llm_guard"]');
  const advanced = document.querySelector('details.advanced');
  const labels = block
    ? Array.from(block.querySelectorAll('.prov-label')).map(
        (e) => (e.textContent || '').trim())
    : [];
  const fields = block
    ? Array.from(block.querySelectorAll('input.field'))
        .filter(vis).length
    : 0;
  return {
    href: window.location.hash,
    viewport: { w: window.innerWidth, h: window.innerHeight },
    groupOrder: groups.map((e) => e.getAttribute('data-provider-group')),
    policyGroup: {
      visible: vis(groupEl),
      text: groupEl ? (groupEl.textContent || '').trim() : '',
    },
    guard: {
      visible: vis(block),
      inAdvanced: !!(advanced && block && advanced.contains(block)),
      labels: labels,
      visibleFields: fields,
      text: block ? (block.textContent || '') : '',
    },
    advancedOpen: advanced ? advanced.open : null,
    overflow: document.documentElement.scrollWidth
      > window.innerWidth + 1,
  };
}
"""


def _api_handler(route):
    url = route.request.url
    if url.split("?")[0].endswith("/api/config"):
        payload = M.CONFIG_STUB
    else:
        payload = M._stub_for(url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(payload))


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    httpd = M._start_server()
    out = {"meta": {
        "purpose": "P0 SMART transport admin visibility (llm_guard)",
        "release": "2.58.206-slice",
        "views": VIEWPORTS,
        "checks": ["prov_policy first", "llm_guard visible",
                   "advanced closed (details.open=false)",
                   "labels", "note semantics", "no h-overflow"],
        "note": "Playwright headless Chromium; /api/* stubbed; no secrets",
    }, "viewports": {}, "failures": []}
    failures = out["failures"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (w, h) in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _api_handler)
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e, b=errors: b.append(str(e)[:300]))
            page.on("console", lambda m, b=errors: (
                b.append(m.text[:200]) if m.type == "error" else None))
            page.goto("http://127.0.0.1:%d/web/index.html" % M.PORT + "#/ai/llm",
                      wait_until="load")
            try:
                page.wait_for_selector(".app-shell", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(700)
            page.evaluate("() => { window.location.hash = '#/ai/llm'; }")
            page.wait_for_timeout(500)
            probe = page.evaluate(PROBE_JS)
            key = "%dx%d" % (w, h)
            out["viewports"][key] = {"probe": probe, "console_errors": errors}

            if errors:
                failures.append("%s: console/page errors %s" % (key, errors))
            if not probe["policyGroup"]["visible"]:
                failures.append("%s: группа prov_policy не видна" % key)
            if "Время ответа и защита" not in probe["policyGroup"]["text"]:
                failures.append("%s: нет заголовка группы политики" % key)
            order = probe["groupOrder"]
            if not order or order[0] != "prov_policy":
                failures.append("%s: prov_policy не первая (%s)" % (key, order))
            guard = probe["guard"]
            if not guard["visible"]:
                failures.append("%s: блок llm_guard не виден" % key)
            if guard["inAdvanced"]:
                failures.append("%s: llm_guard спрятан в advanced" % key)
            if probe["advancedOpen"] is not False:
                failures.append("%s: advanced details.open=%r (не false)"
                                % (key, probe["advancedOpen"]))
            expected = ["Таймаут одного запроса, сек", "Повторов при сбое",
                        "Предел одной основной попытки, сек"]
            if guard["labels"] != expected:
                failures.append("%s: подписи полей %s != %s"
                                % (key, guard["labels"], expected))
            if guard["visibleFields"] != 3:
                failures.append("%s: видимых полей %d != 3"
                                % (key, guard["visibleFields"]))
            for phrase in ("Весь бот", "без перезапуска",
                           "не ограничивает всё исследование"):
                if phrase not in guard["text"]:
                    failures.append("%s: note без «%s»" % (key, phrase))
            if probe["overflow"]:
                failures.append("%s: horizontal overflow" % key)
            page.screenshot(path=os.path.join(
                os.path.dirname(RAW), "llm-guard-%s.png" % key),
                full_page=False)
            ctx.close()
        browser.close()
    httpd.shutdown()
    out["ok"] = not failures
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": out["ok"], "failures": failures},
                     ensure_ascii=False))
    print("evidence:", RAW)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
