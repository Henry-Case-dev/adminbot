"""P0 HOTFIX (18.10.2026) — админ-статус инициативы: «нет разрешённого чата».

Симптом владельца (скриншот): выбранный чат PERMsoc показывался как
`restricted` / «Нет разрешённого чата — данные инициативы не раскрываются».

Реальный сервер (`web/api/routes.py::get_status` + `services/status_service.
intent_snapshot`) отдаёт `restricted` в двух РАЗНЫХ случаях: «чат не выбран»
(`X-Chat-Id` отсутствует → chat_id = None) и «нет доступа к выбранному чату»
(RBAC). До фикса оба показывались как отказ доступа — это и читалось как
«PERMsoc restricted».

Проба (детерминированная, реальные `web/index.html` + `web/app.js`; /api/* —
стабы, повторяющие серверную логику scope):
  1. global-вид (X-Chat-Id нет) → сервер отвечает state="no_chat" → UI обязан
     сказать «чат не выбран» и НЕ показывать «нет разрешённого чата»;
  2. выбран доступный чат (X-Chat-Id = -1002661910336) → state="ok" → видны
     намерения/воронка, «restricted» отсутствует;
  3. выбран недоступный чат (RBAC-запрет) → state="restricted" → честная
     строка про доступ (не про «выбор чата»);
  4. переключение чата в контексте «Статус» обновляет блок инициативы
     (нет чужого/старого состояния); горизонтального переполнения нет.

Запуск: .venv\\Scripts\\python.exe tools\\_p0_initfix_scope_ui_probe.py [--phase before|after]
Артефакты: plans/features/p0-save-init-ux/evidence/initiatives/ui-<phase>/ + scratch JSON.
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402

PORT = 8859
NOW = 1792312000
CHAT_OK = -1002661910336          # PERMsoc-чат: доступ есть (global admin)
CHAT_DENIED = -1009999999999      # RBAC-запрет

PHASE = "before"
if "--phase" in sys.argv:
    PHASE = sys.argv[sys.argv.index("--phase") + 1]
#: Фаза before моделирует и СТАРЫЙ сервер (`intent_snapshot` отдавал
#: `restricted` и когда чат просто не выбран), и старый UI.
OLD_SERVER = (PHASE == "before")

SHOTS = os.path.join(REPO, "plans", "features", "p0-save-init-ux", "evidence",
                     "initiatives", "ui-%s" % PHASE)
RAW = os.path.join(os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                                  os.path.join(REPO, "tools")),
                   "_p0_initfix_scope_ui.json")

MODULE_BLOCK = {
    "id": "initiative", "requested": True, "effective": True,
    "source": "both", "master_param": "flags.initiative_enabled",
    "env_param": "MCA_INTENTS_ENABLED",
    "state_label": "Инициатива работает: решения принимаются",
    "top_block_reason": "",
    "heartbeat": {"job": "intent_heartbeat_tick", "tick_seconds": 300,
                  "enabled": True, "registered": True,
                  "restart_required_env": True, "next_tick": NOW + 120,
                  "last_tick": {"ts": NOW - 180, "due": 0, "enabled": True}},
    "funnel": {"producers_24h": {"observer": 12}, "intents_created_24h": 1,
               "due": 0, "decisions_24h": 1, "writer_generated_24h": 0,
               "sent_24h": 0, "recheck_passed_24h": 0},
}

INTENTS_OK = {
    "enabled": True, "state": "ok", "active": 2,
    "top": [{"intent_id": "in-1", "kind": "topic_interest",
             "goal": "вернуться к разговору про поездку", "status": "pending",
             "next_check_at": NOW + 900, "priority": 1},
            {"intent_id": "in-2", "kind": "open_dispute",
             "goal": "спор про консоли", "status": "deferred",
             "next_check_at": NOW + 1800, "priority": 1}],
    "last_action": {"ts": NOW - 3600, "event": "initiative_decided",
                    "outcome": "silent", "reason_code": "l1_silent",
                    "trigger_kind": "new_message", "action": "reply"},
    "module": MODULE_BLOCK,
}
INTENTS_NO_CHAT = {
    "enabled": True, "state": "no_chat", "active": 0, "top": [],
    "last_action": None, "module": MODULE_BLOCK,
}
INTENTS_RESTRICTED = {
    "enabled": True, "state": "restricted", "active": 0, "top": [],
    "last_action": None, "module": MODULE_BLOCK,
}

INTEL_FUNNELS = {
    "available": True, "now_ts": NOW, "chat_scoped_events": False,
    "initiative": {
        "available": True,
        "job": {"status": "completed", "updated_at": NOW - 300,
                "counters": {"passes": 12, "observed": 30, "eligible": 30,
                             "scan_skipped": 4, "evals": 2,
                             "opportunities": 1, "silent_decisions": 1,
                             "intents_created": 1, "sent": 0,
                             "react_decisions": 0, "writer_unavailable": 0,
                             "eval_unavailable": 0, "errors": 0,
                             "eval_skips": {"min_gap": 1}}},
        "liveness": {"ts": NOW - 300, "status": "completed", "observed": 30,
                     "opportunities": 1},
        "events": {"24h": {"initiative_observer_scan": 12,
                           "initiative_opportunity": 1,
                           "initiative_decided": 1},
                   "7d": {"initiative_observer_scan": 80,
                          "initiative_opportunity": 2,
                          "initiative_decided": 2}},
    },
}

VITALITY = {
    "available": True, "chat_id": CHAT_OK, "window_hours": 24,
    # контракт `activity_verdict`: level/title/warning/recommendation/reasons —
    # плоские поля самого verdict (не вложенный объект).
    "activity": {
        "state": "opportunities_silent", "level": "warn",
        "title": "Возможности есть — сообщений нет",
        "warning": "За окно найдена 1 возможность, отправок нет.",
        "recommendation": "Проверьте причины ворот и безопасную проверку.",
        "reasons": [{"reason_code": "min_gap", "label": "пауза", "count": 1}],
        "decisions": [{"action": "reply", "reason_label": "L1 промолчал",
                       "reason_code": "l1_silent", "stage": "new_message"}],
        "refusals": [], "sends": []},
    "gates": {"blocked_now": False, "items": [
        {"gate": "master", "status": "pass", "label": "Наблюдатель включён",
         "reason_code": "", "value": None, "limit": None, "unit": "none"}],
        "soft_targets": {"active": False}, "state": {}},
    "engine": {"writer": "direct_l2", "llm_available": True,
               "writer_available": True},
}


class _Handler(M._Handler):
    pass


def _stub_body(path_with_query: str, header_chat: str | None):
    """JSON-ответ стаб-сервера для Browser Use (тот же маппинг, что в
    Playwright-пробе; /api/status учитывает X-Chat-Id)."""
    url = path_with_query.split("?")[0]
    if url.endswith("/api/status") and not url.endswith("/api/status/logs"):
        return _status_for(header_chat)
    if url.endswith("/api/memory/intel-funnels"):
        return INTEL_FUNNELS
    if url.endswith("/api/memory/initiative-vitality"):
        return VITALITY
    if url.endswith("/api/status/logs"):
        return {"logs": [], "levels": [], "counts": {}, "count": 0}
    if url.endswith("/api/config"):
        return M.CONFIG_STUB
    return M._stub_for(path_with_query)


def _serve() -> int:
    """Стаб-сервер (реальные web/* + заглушки /api/*) для осмотра в браузере."""
    class _ServeHandler(M._Handler):
        def do_GET(self):  # noqa: N802
            p = self.path.split("?")[0]
            if p.startswith("/api/"):
                body = json.dumps(
                    _stub_body(self.path, self.headers.get("X-Chat-Id")),
                    ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _ServeHandler)
    print("[p0-initfix] serving on http://127.0.0.1:%d/web/index.html#/"
          % PORT, flush=True)
    httpd.serve_forever()
    return 0


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _status_for(chat_header: str | None) -> dict:
    """Повторяет серверную семантику: нет заголовка → no_chat; доступный чат →
    ok; недоступный чат → restricted (RBAC)."""
    st = copy.deepcopy(M.STATUS_STUB)
    if chat_header is None:
        intents = dict(INTENTS_RESTRICTED if OLD_SERVER
                       else INTENTS_NO_CHAT)
    elif chat_header == str(CHAT_OK):
        intents = dict(INTENTS_OK)
    else:
        intents = dict(INTENTS_RESTRICTED)
    st["intents"] = intents
    st["experience"] = {"enabled": True, "state": "not_run", "items": [],
                        "counters": {"lessons": 0, "active": 0,
                                     "suspended": 0, "applications": 0,
                                     "success": 0, "failure": 0,
                                     "unknown": 0}}
    st["random"] = {"ready": True, "enabled": False}
    return st


def main() -> int:
    httpd = _start_server()
    base = "http://127.0.0.1:%d/web/index.html#/" % PORT
    os.makedirs(SHOTS, exist_ok=True)
    config_payload = copy.deepcopy(M.CONFIG_STUB)

    def _api_handler(route):
        req = route.request
        url = req.url.split("?")[0]
        header = req.headers.get("x-chat-id")
        if url.endswith("/api/status") and not url.endswith("/api/status/logs"):
            body = _status_for(header)
        elif url.endswith("/api/memory/intel-funnels"):
            body = INTEL_FUNNELS
        elif url.endswith("/api/memory/initiative-vitality"):
            body = VITALITY
        elif url.endswith("/api/status/logs"):
            body = {"logs": [], "levels": [], "counts": {},
                    "count": 0}
        elif url.endswith("/api/config"):
            body = config_payload
        else:
            body = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))

    from playwright.sync_api import sync_playwright
    result = {"phase": PHASE, "console_errors": [], "checks": {},
              "shots": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                                  reduced_motion="reduce")
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(base, wait_until="load")
        page.wait_for_timeout(2500)
        checks = result["checks"]

        def _shot(name: str) -> None:
            """Снимок БЛОКА «Инициатива» (не пустой верх страницы): именно
            его состояние — предмет пробы, поэтому кадрируем элемент."""
            path = os.path.join(SHOTS, name)
            try:
                page.locator("[data-intents]").screenshot(path=path)
            except Exception:  # noqa: BLE001 — блок мог не отрендериться
                page.screenshot(path=path, full_page=False)
            result["shots"].append(name)

        def _block_text() -> str:
            return page.evaluate(
                "(() => { const el = document.querySelector('[data-intents]');"
                " return el ? el.innerText : ''; })()")

        # global-вид: активный чат выключен явно (как у владельца при старте
        # админки в области «Весь бот»)
        page.evaluate("window.__adminbotVm.setActiveChat(null)")
        page.wait_for_timeout(1800)
        global_text = _block_text()
        checks["global_state"] = page.evaluate(
            "window.__adminbotVm.statusData && "
            "window.__adminbotVm.statusData.intents && "
            "window.__adminbotVm.statusData.intents.state")
        checks["global_honest_no_chat"] = "чат не выбран" in global_text.lower()
        checks["global_no_false_restricted"] = \
            "нет разрешённого чата" not in global_text.lower()
        checks["global_funnel_hidden"] = page.evaluate(
            "!document.querySelector('[data-initiative-independent]')")
        page.evaluate("(function(){var el=document.querySelector"
                      "('[data-intents]');if(el){el.scrollIntoView("
                      "{block:'center'})}})()")
        page.wait_for_timeout(600)
        _shot("01_global_no_chat.png")

        # доступный чат: данные инициативы видны
        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % CHAT_OK)
        page.wait_for_timeout(2500)
        chat_text = _block_text()
        checks["chat_state"] = page.evaluate(
            "window.__adminbotVm.statusData && "
            "window.__adminbotVm.statusData.intents && "
            "window.__adminbotVm.statusData.intents.state")
        checks["chat_shows_intents"] = "вернуться к разговору про поездку" \
            in chat_text
        checks["chat_no_restricted_line"] = \
            "нет разрешённого чата" not in chat_text.lower()
        clock = page.evaluate(
            "!document.querySelector('[data-initiative-independent]')")
        page.wait_for_timeout(1200)
        checks["chat_funnel_or_absent"] = True
        checks["chat_funnel_visible"] = page.evaluate(
            "!!document.querySelector('[data-initiative-independent]')")
        page.evaluate("(function(){var el=document.querySelector"
                      "('[data-intents]');if(el){el.scrollIntoView("
                      "{block:'center'})}})()")
        page.wait_for_timeout(600)
        _shot("02_chat_ok.png")

        # недоступный чат (RBAC) → честная строка про доступ
        page.evaluate("window.__adminbotVm.setActiveChat(%d)" % CHAT_DENIED)
        page.wait_for_timeout(2500)
        denied_text = _block_text()
        checks["denied_state_label"] = "нет доступа к выбранному чату" in \
            denied_text.lower()
        checks["denied_no_no_chat_label"] = "чат не выбран" not in \
            denied_text.lower()
        page.evaluate("(function(){var el=document.querySelector"
                      "('[data-intents]');if(el){el.scrollIntoView("
                      "{block:'center'})}})()")
        page.wait_for_timeout(600)
        _shot("03_denied_restricted.png")

        # переполнение/ошибки консоли
        checks["no_h_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1")
        checks["console_errors"] = result["console_errors"]
        ctx.close()
        browser.close()
    httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result["checks"].items()},
                     ensure_ascii=False, indent=2))
    failed = [k for k, v in result["checks"].items()
              if v is False or (k == "console_errors" and v)]
    if PHASE == "before":
        red = [k for k in ("global_honest_no_chat",
                           "global_no_false_restricted")
               if result["checks"].get(k) is not True]
        print("\n[probe] phase=before RED witness:",
              red or "NOT REPRODUCED (дефект не подтверждён)")
        print("[probe] raw:", RAW)
        print("[probe] shots:", SHOTS)
        return 0
    print("\n[probe] phase=%s failed=%s" % (PHASE, failed or "none"))
    print("[probe] raw:", RAW)
    print("[probe] shots:", SHOTS)
    return 1 if failed else 0


if __name__ == "__main__":
    if "--serve" in sys.argv:
        raise SystemExit(_serve())
    raise SystemExit(main())
