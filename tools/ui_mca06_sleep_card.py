"""mca-06 T-4706 (Browser-Verification REQUIRED): карточка состояния сна.

Детерминированный Playwright-прогон на 3 fixture-конфигурациях resolver'а
(off / master-off / resource-limit): существующий UI памяти получает блок
`global_value/chat_override/effective/source` + конкретный диагноз (`detail`)
— текст причины пустоты ленты «Парадигмы» содержит конкретный ключ/лимит,
а не «проверьте настройки».

Запуск: .venv/Scripts/python.exe tools/ui_mca06_sleep_card.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.ui_round1025_matrix as base  # noqa: E402

FIXTURES = {
    "off": {
        "enabled": False, "deep_enabled": False, "master_enabled": True,
        "paradigms_status": "empty", "paradigms_reason": "deep_sleep_off",
        "gate": "deep_sleep", "gate_blocked": True, "global_value": False,
        "chat_override": None, "effective": False, "gate_source": "global",
        "detail": "flags.deep_sleep_enabled=False (source=global)",
        "expect_key": "flags.deep_sleep_enabled",
    },
    "master_off": {
        "enabled": True, "deep_enabled": True, "master_enabled": False,
        "paradigms_status": "empty", "paradigms_reason": "master_sleep_off",
        "gate": "master_sleep", "gate_blocked": True, "global_value": False,
        "chat_override": None, "effective": False, "gate_source": "global",
        "detail": "memory.dream_enabled=False (source=global)",
        "expect_key": "memory.dream_enabled",
    },
    "resource_limit": {
        "enabled": True, "deep_enabled": True, "master_enabled": True,
        "paradigms_status": "empty", "paradigms_reason": "resource_limit",
        "gate": "resource", "gate_blocked": True, "global_value": True,
        "chat_override": None, "effective": False, "gate_source": "runtime",
        "detail": "global daily deep attempts: used=1, limit=1",
        "expect_key": "used=1",
    },
}


def main() -> int:
    from playwright.sync_api import sync_playwright

    httpd = base._start_server()
    current = {"payload": FIXTURES["off"]}
    failures = []
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(base.TMA_STUB)

        def _route(route):
            url = route.request.url.split("?")[0]
            if url.endswith("/api/memory/deep-sleep"):
                payload = current["payload"]
            elif url.endswith("/api/config"):
                payload = base.CONFIG_STUB
            else:
                payload = base._stub_for(route.request.url)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))

        ctx.route("**/api/**", _route)
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200])
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
        url = "http://127.0.0.1:%d/web/index.html" % base.PORT
        for name, payload in FIXTURES.items():
            current["payload"] = payload
            page.goto(url + "?f=" + name + "#/", wait_until="load")
            try:
                page.wait_for_selector(".ribbon-empty__reason", timeout=8000)
                page.wait_for_timeout(400)
                text = page.inner_text(".ribbon-empty__reason")
            except Exception as exc:  # noqa: BLE001
                text = ""
                failures.append("%s: no .ribbon-empty__reason (%s)"
                                % (name, exc))
            results[name] = text
            if payload["expect_key"] not in text:
                failures.append("%s: диагноз без ключа '%s': %r"
                                % (name, payload["expect_key"], text))
            if "проверьте настройки" in text.lower():
                failures.append("%s: безликий диагноз" % name)
        browser.close()
    httpd.shutdown()
    print(json.dumps({"results": results, "console_errors": errors[:10],
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
