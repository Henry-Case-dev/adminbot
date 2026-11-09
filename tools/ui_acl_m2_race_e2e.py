"""MOD-ACL-UX-01 M2 — гонки UI-клиента: смена чата и двойной клик (§10 п.3/п.4).

Детерминированный Playwright-прогон НАСТОЯЩЕГО `web/index.html` + `web/app.js`
на локальном http-сервере; `/api/*` перехватываются (секретов нет, Telegram не
трогается). Проверяются два наблюдаемых контракта:

* **MAC-S10-04** — три последовательные смены чата: поздний ответ
  `/api/config` для более старого чата НЕ перезаписывает карточки нового чата
  (`scopeEpoch`-гвард). Доказательство: `A` отвечает медленно и позже, чем
  `C`; итоговое значение в состоянии — значение `C`, «позднее A» не проявилось.
* **MAC-S10-03 (UI-половина)** — двойной клик по сохранению НЕ порождает два
  сетевых POST: второй вызов `saveConfigItem` по тому же ключу блокируется
  in-flight набором `saving`, а на сервер уходит ровно один POST с
  `operation_id`.

Запуск: py -3 tools\\ui_acl_m2_race_e2e.py [--out DIR]
Артефакты по умолчанию: docs/evidence/mod-acl-ux-01-m2/
Маркер успеха: MOD-ACL-M2-RACE OK
"""
import json
import os
import sys
import threading
import time
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

import ui_round1025_matrix as M  # noqa: E402  (TMA_STUB/ME_JSON/стабы)

PORT = 8861
TARGET_KEY = "flags.dream_enabled"
SLOW_CHAT = -1007000001
MID_CHAT = -1007000002
NEW_CHAT = -1007000003


class _Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[1:]
        elif p in ("/", "", "/index.html"):
            rel = "web/index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(REPO, rel.replace("/", os.sep))

    def log_message(self, *args):
        pass


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _config_payload(value, chat_id=None, updated_at="2026-11-09T10:00:00Z"):
    item = {
        "key": TARGET_KEY, "title": "Dream", "category": "flags",
        "group": "flags_memory", "type": "bool", "value": value,
        "per_chat": True, "chat_source": "chat" if chat_id else "global",
        "global_value": False, "chat_state": "on" if value else "off",
    }
    return {"items": [item], "groups": [], "modules": [],
            "chat_id": chat_id, "updated_at": updated_at}


def main() -> int:
    from playwright.sync_api import sync_playwright

    out_dir = os.path.join(REPO, "docs", "evidence", "mod-acl-ux-01-m2")
    for i, arg in enumerate(sys.argv):
        if arg == "--out" and i + 1 < len(sys.argv):
            out_dir = sys.argv[i + 1]
    os.makedirs(out_dir, exist_ok=True)
    report = {"ok": False, "checks": {}, "requests": [], "console": []}
    httpd = _start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_init_script(M.TMA_STUB)

            config_requests = []
            post_requests = []

            def _route(route):
                url = route.request.url.split("?")[0]
                if url.endswith("/api/config"):
                    hdrs = {k.lower(): v for k, v in
                            (route.request.headers or {}).items()}
                    chat = hdrs.get("x-chat-id")
                    if route.request.method == "POST":
                        post_requests.append(route.request.post_data)
                        route.fulfill(
                            status=200, content_type="application/json",
                            body=json.dumps({"saved": [TARGET_KEY],
                                             "failed": [], "revalidated": False,
                                             "updated_at":
                                                 "2026-11-09T11:00:00Z"}))
                        return
                    config_requests.append(chat)
                    if chat == str(SLOW_CHAT):
                        # Поздний ответ «старого» чата: приходит ПОСЛЕ нового.
                        time.sleep(0.9)
                        payload = _config_payload(True, SLOW_CHAT,
                                                  "2026-11-09T09:00:00Z")
                    elif chat == str(MID_CHAT):
                        payload = _config_payload(False, MID_CHAT,
                                                  "2026-11-09T09:30:00Z")
                    elif chat == str(NEW_CHAT):
                        payload = _config_payload(False, NEW_CHAT,
                                                  "2026-11-09T10:00:00Z")
                    else:
                        payload = _config_payload(False)
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps(payload))
                    return
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(M._stub_for(route.request.url)))

            page = ctx.new_page()
            page.on("console", lambda msg: report["console"].append(
                {"type": msg.type, "text": msg.text[:200]}))
            page.route("**/api/**", _route)
            page.goto("http://127.0.0.1:%d/web/index.html" % PORT,
                      wait_until="load")
            page.wait_for_function(
                "() => { const el = document.querySelector('#app');"
                " const app = el && el.__vue_app__;"
                " const c = app && app._container;"
                " return !!(c && c._vnode && c._vnode.component"
                " && c._vnode.component.proxy); }",
                timeout=15000)
            proxy_js = ("document.querySelector('#app').__vue_app__"
                        "._container._vnode.component.proxy")

            # ── MAC-S10-04: три смены чата, поздний ответ старого чата ─────
            page.evaluate(
                "() => { window.__m2samples = [];"
                " const t0 = Date.now();"
                " const iv = setInterval(() => { const p = %s;"
                "   const it = (p.configItems || []).find("
                "     i => i.key === '%s');"
                "   window.__m2samples.push([Date.now() - t0,"
                "     p.activeChatId, it ? it.value : null]);"
                "   if (Date.now() - t0 > 2000) clearInterval(iv); }, 50);"
                " const q = %s;"
                " q.setActiveChat('%s'); q.setActiveChat('%s');"
                " q.setActiveChat('%s'); }"
                % (proxy_js, TARGET_KEY, proxy_js, SLOW_CHAT, MID_CHAT,
                   NEW_CHAT))
            page.wait_for_timeout(2400)
            state = page.evaluate(
                "() => { const p = %s;"
                "const it = (p.configItems || []).find("
                "  i => i.key === '%s');"
                "return {chat: p.activeChatId,"
                " value: it ? it.value : null,"
                " samples: window.__m2samples || [],"
                " scope: p.scopeKind}; }" % (proxy_js, TARGET_KEY))
            samples = state["samples"]
            # После переключения на новый чат значение старого чата (True)
            # больше НЕ появляется: поздний ответ не перезаписал карточки.
            late_after_new = [s for s in samples
                              if s[1] == NEW_CHAT and s[2] is True]
            report["checks"]["stale_race"] = {
                "active_chat": state["chat"],
                "value": state["value"],
                "samples": len(samples),
                "late_overwrites": len(late_after_new),
                "config_requests": list(config_requests),
            }
            ok_race = (state["chat"] == NEW_CHAT
                       and state["value"] is False
                       and not late_after_new
                       and str(SLOW_CHAT) in config_requests
                       and str(NEW_CHAT) in config_requests)
            report["ok_race"] = ok_race
            page.screenshot(path=os.path.join(out_dir,
                                              "m2-race-stale-config.png"))

            # ── MAC-S10-03 (UI): двойной клик = один POST ─────────────────
            page.evaluate(
                "() => { const p = %s;"
                "p.setActiveChat(null);"
                "p.configItems = [{key: '%s', title: 'Dream',"
                "  category: 'flags', group: 'flags_memory', type: 'bool',"
                "  value: true, per_chat: false, chat_state: null}];"
                "p.configChatUpdatedAt = null; }"
                % (proxy_js, TARGET_KEY))
            page.wait_for_timeout(150)
            page.evaluate(
                "() => { const p = %s;"
                "const it = p.configItems.find(i => i.key === '%s');"
                "p.saveConfigItem(it); p.saveConfigItem(it); }"
                % (proxy_js, TARGET_KEY))
            page.wait_for_timeout(1200)
            report["checks"]["double_click"] = {
                "posts": len(post_requests),
                "bodies": [str(b)[:200] for b in post_requests],
            }
            ok_click = len(post_requests) == 1
            body = post_requests[0] if post_requests else "{}"
            ok_click = ok_click and "operation_id" in body
            report["ok_double_click"] = ok_click

            report["ok"] = bool(ok_race and ok_click)
            browser.close()
    finally:
        httpd.shutdown()

    with open(os.path.join(out_dir, "m2-race-e2e.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": report["ok"],
                      "race": report.get("ok_race"),
                      "double_click": report.get("ok_double_click"),
                      "checks": report["checks"]}, ensure_ascii=False,
                     indent=2))
    print("MOD-ACL-M2-RACE OK" if report["ok"] else "MOD-ACL-M2-RACE FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
