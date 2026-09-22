"""F10 round 10.25 — UI-прогон секретов §78 (T-3113).

Переиспользует локальный сервер/стабы `tools/ui_round1025_matrix.py` (ADR-1025-24
D5, без новых библиотек). Проверяет на реальном `web/index.html` + `web/app.js`:

  * при наличии секрета отображается МАСКА (display-индикатор), а НЕ значение:
    поле ввода пустое, маска — отдельный бейдж (F9/ADR-1025-22 §50);
  * строка маски НЕ уходит в API как новый секрет: реальный путь сохранения
    `saveKeyItem` отклоняет маску/композит (guard `hasSecretMask`) — 0 write;
  * при замене ключа реальным значением выполняется ровно 1 write и в payload
    уходит именно новое значение (не маска).

Запуск: .venv/Scripts/python.exe tools/ui_round1025_secrets_ui.py
Артефакт: tools/_ui_round1025_secrets_ui.json

R17: реальные секреты не выводятся; в отчёте только маска/предикат.
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_round1025_matrix as M  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
PORT = M.PORT + 5
OUT = os.path.join(REPO, "tools", "_ui_round1025_secrets_ui.json")
NEW_KEY = "sk-ui-round1025-f10-probe"

PROXY_JS = """
(() => {
  const el = document.querySelector('#app');
  const app = el && el.__vue_app__;
  const inst = (app && app._instance)
    || (el && el._vnode && el._vnode.component);
  return inst && (inst.proxy || inst.ctx) || null;
})()
"""


def _start_server_on(port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _run():
    from playwright.sync_api import sync_playwright

    httpd = _start_server_on(PORT)
    writes = []

    def _api(route):
        req = route.request
        path = req.url.split("?")[0]
        if path.endswith("/api/config") and req.method == "POST":
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:  # noqa: BLE001
                body = {}
            writes.append(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True}))
            return
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(M.CONFIG_STUB))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url)))

    res = {"dom": {}, "guard": {}, "failures": []}
    failures = res["failures"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))
        url = "http://127.0.0.1:%d/web/index.html" % PORT
        page.goto(url + "#/ai/llm", wait_until="load")
        try:
            page.wait_for_selector(".app-shell", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(900)
        page.evaluate("() => { window.location.hash = '#/ai/llm'; }")
        page.wait_for_timeout(900)

        dom = page.evaluate(
            "() => {"
            " const f = document.querySelector("
            "'.secret-field[data-secret-configured=\"1\"]');"
            " if (!f) return { found: false };"
            " const mask = f.querySelector('.secret-field__mask');"
            " const inp = f.querySelector('.secret-field__input');"
            " return { found: true,"
            "   maskText: mask ? (mask.textContent || '').trim() : '',"
            "   inputValue: inp ? inp.value : null,"
            "   scope: f.getAttribute('data-secret-scope'),"
            "   maskHasDots: mask ? /[•*]/.test(mask.textContent || '') : false };"
            " }")
        res["dom"] = dom
        if not dom.get("found"):
            failures.append("§78: секрет-поле с configured=1 не найдено на #/ai/llm")
        else:
            if not dom.get("maskText"):
                failures.append("§78: маска не отображается при наличии секрета")
            if dom.get("inputValue"):
                failures.append("§78: значение секрета попало в input "
                                "(должно быть пусто) value=%r"
                                % dom.get("inputValue"))

        # Реальный путь сохранения секрета: маска/композит не уходят в API.
        # Сентинел маски (R31/UPD3) = 12 символов '•' (U+2022); композит —
        # сентинел + ввод. Display-бейдж (8 '•' + last4) — отдельный текст.
        guard = page.evaluate(
            "() => { const p = %s;"
            " const item = (p.configItems || []).find(i => i.secret);"
            " if (!item) return { ok: false, reason: 'no-secret-item' };"
            " const sentinel = '\\u2022'.repeat(12);"
            " const composite = sentinel + '0000';"
            " p.keyDrafts = p.keyDrafts || {};"
            " return { ok: true, key: item.key,"
            "   sentinelHasMask: p.hasSecretMask(sentinel),"
            "   compositeHasMask: p.hasSecretMask(composite),"
            "   plainIsMask: p.isSecretMask(sentinel) }; }"
            % PROXY_JS)
        res["guard"]["precheck"] = guard
        if not guard.get("ok"):
            failures.append("§78: секретный config-элемент не найден (%s)"
                            % guard.get("reason"))
        else:
            if not guard.get("sentinelHasMask"):
                failures.append("§78: guard hasSecretMask не распознал сентинел")
            if not guard.get("compositeHasMask"):
                failures.append("§78: guard hasSecretMask не распознал композит")
            before = len(writes)
            page.evaluate(
                "async () => { const p = %s;"
                " const item = (p.configItems || []).find(i => i.secret);"
                " const sentinel = '\\u2022'.repeat(12);"
                " const composite = sentinel + '0000';"
                " p.keyDrafts[item.key] = sentinel;"
                " window.__m1 = await p.saveKeyItem(item, true);"
                " p.keyDrafts[item.key] = composite;"
                " window.__m2 = await p.saveKeyItem(item, true); }"
                % PROXY_JS)
            page.wait_for_timeout(700)
            res["guard"]["mask_writes"] = len(writes) - before
            if res["guard"]["mask_writes"] != 0:
                failures.append("§78: маска/композит ушли в API как секрет "
                                "(%d write)" % res["guard"]["mask_writes"])
            # Замена реальным ключом → ровно один write с новым значением.
            before = len(writes)
            page.evaluate(
                ("async (nk) => { const p = %s;"
                 " const item = (p.configItems || []).find(i => i.secret);"
                 " p.keyDrafts[item.key] = nk;"
                 " window.__keySave = await p.saveKeyItem(item, true); }")
                % PROXY_JS,
                NEW_KEY)
            page.wait_for_timeout(700)
            res["guard"]["replace_writes"] = len(writes) - before
            if res["guard"]["replace_writes"] != 1:
                failures.append("§78: замена ключа дала %d write (ожидалось 1)"
                                % res["guard"]["replace_writes"])
            sent = [i.get("value") for w in writes
                    for i in (w.get("items") or [])]
            res["guard"]["sent_values"] = ["<new-key>" if v == NEW_KEY
                                           else ("<mask>" if v and "•" in str(v)
                                                 else v) for v in sent]
            if any(v and "•" in str(v) for v in sent):
                failures.append("§78: среди payload'ов есть строка маски")

        for e in errs:
            failures.append("pageerror: %s" % e)
        ctx.close()
        browser.close()
    httpd.shutdown()
    res["failures"] = failures
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("[secrets-ui] failures:", len(failures))
    for x in failures:
        print("  !", x)
    print("[secrets-ui] dom:", res.get("dom"))
    print("[secrets-ui] guard:", {k: v for k, v in res.get("guard", {}).items()
                                  if k != "precheck"})
    print("[secrets-ui] артефакт:", OUT)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
