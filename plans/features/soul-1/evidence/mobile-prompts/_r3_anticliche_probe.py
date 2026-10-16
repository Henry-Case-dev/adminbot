"""SOUL-1 r3: точечная проба вкладки «Промпты» @320 — группа limits_anticliche
(generic-карточка намеренно не рендерится; ключ живёт в карточке
`data-block="anticliche-monitor"`). Пишет _r3_anticliche-probe.json.

Запуск: .venv\\Scripts\\python.exe <этот файл>
"""
import importlib.util
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load("r3_harness", os.path.join(HERE, "_r3_mobile_prompts_e2e.py"))

JS = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const block = document.querySelector('[data-block="anticliche-monitor"]');
  const r = block ? block.getBoundingClientRect() : null;
  const key = Array.from((p.configItems || []).map(function (i) { return i.key; }))
    .filter(function (k) { return k.indexOf('limits.anticliche') === 0; });
  const input = block
    ? block.querySelector('input[type="number"], input')
    : null;
  return {
    groupInTab: (p.currentTabGroups || []).map(function (g) { return g.id; })
      .indexOf('limits_anticliche') >= 0,
    monitorVisible: !!block && r.width > 0 && r.height > 0,
    anticlicheKeys: key,
    canEdit: key.length ? !!p.canEditConfig(key[0]) : null,
    inputValue: input ? input.value : null,
    inputDisabled: input ? !!input.disabled : null,
  };
})()
"""


def main():
    from playwright.sync_api import sync_playwright
    payload = H.build_payload()
    httpd = ThreadingHTTPServer(("127.0.0.1", H.PORT), H.M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store = H.Store(payload)

    def _api(route, request=None, *, me=None, cfg=None):
        url = route.request.url
        path = url.split("?")[0]
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(store.get()))
            return
        if path.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(H.M.ME_JSON))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(H.M._stub_for(url)))

    out = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 320, "height": 640})
            ctx.add_init_script(H.M.TMA_STUB)
            ctx.route("**/api/**", _api)
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/web/index.html#/ai/prompts" % H.PORT,
                      wait_until="load")
            page.wait_for_timeout(2200)
            out = page.evaluate(JS % H.JS_VUE)
            page.screenshot(path=os.path.join(
                HERE, "_r3_anticliche-monitor-320.png"), full_page=False)
            browser.close()
    finally:
        httpd.shutdown()
    with open(os.path.join(HERE, "_r3_anticliche-probe.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ok = (out.get("groupInTab") and out.get("monitorVisible")
          and out.get("anticlicheKeys"))
    print("ANTICLICHE PROBE:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
