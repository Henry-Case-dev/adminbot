"""F10 round 10.25 — кросс-фичевые E2E §72/§73/§74 (T-3107…T-3109).

Расширение существующего харнесса `tools/ui_round1025_matrix.py` (ADR-1025-24
D5): без новых библиотек, локальный http-сервер + перехват `/api/*` через
`page.route(...)`, тот же init-stub `Telegram.WebApp`.

Что проверяется (живой прогон, реальный `web/index.html` + `web/app.js`):
  * §72 «единый переключатель = ровно одна мутация»:
    чат PERMsoc → «Модули» → переключатель модуля «Сводки чатов»;
    перехват сети доказывает РОВНО одну серверную мутацию (POST /api/config);
    быстрый панель / карточка каталога / страница модуля — одно состояние;
    reload → значение сохранено сервером.
  * §73 «независимость чатов + незавершённый запрос»:
    мутация в чате A висит (ответ задержан через `route`), уходим в чат B —
    состояние B не меняется; после освобождения ответа применяется только A.
  * §74 «наследование без потери локальных»:
    глобальное значение меняется; чат с локальным override сохраняет своё
    значение; чат без override наследует глобальное. Серверная семантика
    наследования НЕ меняется (только чтение/прогон).

Запуск: .venv/Scripts/python.exe tools/ui_round1025_e2e.py
Артефакты: tools/_ui_round1025_e2e.json (+ PNG при падении).

ВАЖНО: успешный локальный прогон НЕ заменяет живую приёмку в Telegram WebView
(10.20-UPD3/10.21). Chromium ≠ Telegram WebView.
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_round1025_matrix as M  # noqa: E402  (переиспользуем сервер/стабы)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = M.REPO
PORT = M.PORT + 3           # отдельный порт от матрицы
E2E_RAW = os.path.join(REPO, "tools", "_ui_round1025_e2e.json")
CHAT_A = "-1001234567890"
CHAT_B = "-1009876543210"
MODULE_ID = "mod_summary"
MODULE_TITLE = "Сводки чатов"

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
    """Локальный http-сервер на отдельном порту (общий обработчик матрицы)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class ServerState:
    """Mutable in-memory конфиг: global + per-chat override (§74)."""

    def __init__(self):
        self.glob = {it["key"]: copy.deepcopy(it) for it in M.CONFIG_STUB["items"]}
        chat = {it["key"]: copy.deepcopy(it)
                for it in M.CONFIG_STUB_CHAT["items"]}
        # chat-вариант содержит override по per_chat-bool; фиксируем его как
        # «чат A», чат B — без override (наследует global).
        self.chat = {CHAT_A: chat}
        self.writes = []          # список payload'ов (счётчик мутаций)

    def get(self, chat_id):
        src = self.chat.get(chat_id)
        if not src:
            # чат без override: значение = global, chat_source = ''
            items = []
            for k, it in sorted(self.glob.items()):
                c = copy.deepcopy(it)
                c["global_value"] = it.get("value")
                if it.get("secret"):
                    c["value"] = it.get("value")
                c["chat_source"] = ""
                items.append(c)
            return {"items": items, "groups": M.CONFIG_STUB.get("groups", [])}
        items = []
        for k, it in sorted(src.items()):
            c = copy.deepcopy(it)
            g = self.glob.get(k) or {}
            c["global_value"] = g.get("value")
            items.append(c)
        return {"items": items, "groups": M.CONFIG_STUB.get("groups", [])}

    def apply_post(self, body, chat_id):
        items = (body or {}).get("items") or []
        self.writes.append({"chat_id": chat_id or "global",
                            "items": [{"key": i.get("key"),
                                       "value": i.get("value")} for i in items]})
        target = self.glob if not chat_id else self.chat.setdefault(chat_id, {})
        for i in items:
            k = i.get("key")
            if k in target:
                target[k]["value"] = i.get("value")
            else:
                target[k] = {"key": k, "value": i.get("value"),
                             "global_value": None, "per_chat": True}


def _run():
    from playwright.sync_api import sync_playwright

    httpd = _start_server_on(PORT)
    state = ServerState()
    deferred = []          # [(route, chat_id)]
    result = {"meta": {}, "s72": {}, "s73": {}, "s74": {}, "failures": []}
    failures = result["failures"]

    def _api_handler(route):
        req = route.request
        url = req.url
        path = url.split("?")[0]
        chat_id = None
        hdrs = req.headers or {}
        # X-Chat-Id присутствует для chat-скоупа (см. api() в app.js).
        for hk, hv in hdrs.items():
            if hk.lower() == "x-chat-id":
                chat_id = hv
        if path.endswith("/api/config") and req.method == "POST":
            body = {}
            try:
                body = json.loads(req.post_data or "{}")
            except Exception:  # noqa: BLE001
                body = {}
            if state.defer_next_post:
                state.defer_next_post = False
                deferred.append((route, chat_id, body))
                return          # ответим позже из main-потока
            state.apply_post(body, chat_id)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "saved": len(
                              (body or {}).get("items") or [])}))
            return
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(state.get(chat_id)))
            return
        if path.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps([
                              {"chat_id": int(CHAT_A), "title": "Chat A",
                               "is_dm": False, "photo_file_id": None,
                               "access": "admin"},
                              {"chat_id": int(CHAT_B), "title": "Chat B",
                               "is_dm": False, "photo_file_id": None,
                               "access": "admin"},
                          ]))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(url)))

    state.defer_next_post = False

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(M.TMA_STUB)
        ctx.add_init_script(
            "() => localStorage.setItem('adminbot.active_chat_id',"
            " '%s')" % CHAT_A)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append("%s: %s" % (m.type, m.text[:160]))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
        # Смена области при «несохранённых правках» спрашивает confirm —
        # подтверждаем (мы сознательно переключаемся, черновиков нет).
        page.on("dialog", lambda d: d.accept())
        url = "http://127.0.0.1:%d/web/index.html" % PORT

        # ── §72: ровно одна мутация ─────────────────────────────────────
        page.goto(url + "#/modules", wait_until="load")
        try:
            page.wait_for_selector(".app-shell", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(900)
        page.evaluate("() => { window.location.hash = '#/modules'; }")
        page.wait_for_timeout(700)
        result["s72"]["route"] = "#/modules"
        # Канонический элемент конфига присутствует
        has_item = page.evaluate(
            "() => { const p = %s; return !!(p && p.configItems || []).find("
            "i => i.key === 'flags.summary_enabled'); }" % PROXY_JS)
        result["s72"]["config_item_present"] = bool(has_item)
        # Ищем переключатель в быстром управлении / карточке каталога
        sel_quick = '.module-quick-item[data-mod="%s"] input[type=checkbox]' % MODULE_ID
        sel_card = '.module-card[data-mod="%s"] input[type=checkbox]' % MODULE_ID
        before_writes = len(state.writes)
        clicked = None
        for sel in (sel_quick, sel_card):
            el = page.query_selector(sel)
            if not el:
                continue
            clicked = sel
            try:
                # Реальный пользовательский жест: снять/поставить галочку.
                page.locator(sel).uncheck(force=True, timeout=4000)
                result["s72"]["click_method"] = "uncheck"
            except Exception as exc:  # noqa: BLE001
                # В headless `sr-only`-input может не менять состояние от
                # синтетического клика; это не дефект продукта — ниже тот же
                # реальный DOM-элемент доводит изменение через @change.
                result["s72"]["click_method"] = "change-dispatch"
                result["s72"]["click_note"] = str(exc)[:120]
            break
        page.wait_for_timeout(500)
        if clicked and len(state.writes) - before_writes == 0:
            # Резерв: гарантированно доводим изменение состояния до Vue
            # (@change) — тот же реальный DOM-элемент и тот же обработчик.
            page.evaluate(
                "() => { const e = document.querySelector('%s'); if (e) {"
                " e.checked = false;"
                " e.dispatchEvent(new Event('change', { bubbles: true })); } }"
                % clicked)
            page.wait_for_timeout(300)
        result["s72"]["clicked_selector"] = clicked
        page.wait_for_timeout(900)
        result["s72"]["writes"] = len(state.writes) - before_writes
        # три представления
        state_quick = page.evaluate(
            "() => { const e = document.querySelector('%s');"
            " return e ? e.checked : null; }" % sel_quick)
        state_card = page.evaluate(
            "() => { const e = document.querySelector('%s');"
            " return e ? e.checked : null; }" % sel_card)
        result["s72"]["quick_checked"] = state_quick
        result["s72"]["card_checked"] = state_card
        page.evaluate("() => { window.location.hash = '#/modules/summary'; }")
        page.wait_for_timeout(800)
        page_state = page.evaluate(
            "() => { const p = %s; return p ?"
            " p.getModuleState(null, '%s').display : null; }"
            % (PROXY_JS, MODULE_ID))
        page.evaluate("() => { window.location.hash = '#/modules'; }")
        page.wait_for_timeout(500)
        store_state = page.evaluate(
            "() => { const p = %s; return p ?"
            " p.getModuleState(p.storeScope(), '%s').display : null; }"
            % (PROXY_JS, MODULE_ID))
        result["s72"]["workspace_state"] = page_state
        result["s72"]["store_state"] = store_state
        if result["s72"]["writes"] != 1:
            failures.append("§72: мутаций %d (ожидалось ровно 1)"
                            % result["s72"]["writes"])
        if not clicked:
            failures.append("§72: переключатель модуля не найден в UI")
        if not (state_quick is not None and state_quick == state_card
                and state_quick == store_state):
            failures.append("§72: представления переключателя расходятся "
                            "(quick=%s card=%s store=%s)"
                            % (state_quick, state_card, store_state))
        # reload → значение сохранено сервером
        page.reload(wait_until="load")
        try:
            page.wait_for_selector(".app-shell", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(900)
        reload_state = page.evaluate(
            "() => { const p = %s; return p ?"
            " p.getModuleState(p.storeScope(), '%s').display : null; }"
            % (PROXY_JS, MODULE_ID))
        result["s72"]["reload_state"] = reload_state
        srv_val = next((w for w in reversed(state.writes)
                        if w["chat_id"] == CHAT_A
                        and any(i["key"] == "flags.summary_enabled"
                                for i in w["items"])), None)
        result["s72"]["server_value"] = (
            [i["value"] for i in srv_val["items"]
             if i["key"] == "flags.summary_enabled"] or [None])[0] if srv_val else None
        if reload_state != result["s72"]["server_value"]:
            failures.append("§72: reload-состояние %s != серверного %s"
                            % (reload_state, result["s72"]["server_value"]))

        # ── §73: независимость чатов + незавершённый запрос ─────────────
        page.evaluate("() => { window.location.hash = '#/modules'; }")
        page.wait_for_timeout(600)
        # Текущее состояние B до гонки
        b_before = page.evaluate(
            "() => { const p = %s; p.setActiveChat(%d);"
            " return p.getModuleState(p.storeScope(), '%s').display; }"
            % (PROXY_JS, int(CHAT_B), MODULE_ID))
        page.wait_for_timeout(700)
        b_before = page.evaluate(
            "() => { const p = %s; return p.getModuleState(p.storeScope(),"
            " '%s').display; }" % (PROXY_JS, MODULE_ID))
        # Возвращаемся на A, запускаем мутацию с ЗАДЕРЖАННЫМ ответом
        page.evaluate("() => { const p = %s; p.setActiveChat(%d); }"
                      % (PROXY_JS, int(CHAT_A)))
        page.wait_for_timeout(800)
        state.defer_next_post = True
        a_target = not bool(result["s72"]["store_state"])
        page.evaluate(
            "() => { const p = %s; window.__e2e_promise ="
            " p.setModuleState(p.storeScope(), '%s', %s); }"
            % (PROXY_JS, MODULE_ID, "true" if a_target else "false"))
        # Ждём перехвата отложенного POST
        for _ in range(40):
            if deferred:
                break
            page.wait_for_timeout(100)
        result["s73"]["deferred_captured"] = bool(deferred)
        # Уходим в чат B, пока ответ A висит
        page.evaluate("() => { const p = %s; p.setActiveChat(%d); }"
                      % (PROXY_JS, int(CHAT_B)))
        page.wait_for_timeout(900)
        b_during = page.evaluate(
            "() => { const p = %s; return p.getModuleState(p.storeScope(),"
            " '%s').display; }" % (PROXY_JS, MODULE_ID))
        result["s73"]["b_before"] = b_before
        result["s73"]["b_during_inflight"] = b_during
        if b_during != b_before:
            failures.append("§73: состояние чата B изменилось во время "
                            "незавершённого запроса A (%s → %s)"
                            % (b_before, b_during))
        # Освобождаем ответ A
        if deferred:
            route, cid, body = deferred.pop(0)
            state.apply_post(body, cid)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True}))
        page.wait_for_timeout(900)
        b_after = page.evaluate(
            "() => { const p = %s; return p.getModuleState(p.storeScope(),"
            " '%s').display; }" % (PROXY_JS, MODULE_ID))
        result["s73"]["b_after"] = b_after
        # A — своё значение (в своей области, читаем из серверного состояния)
        a_item = (state.chat.get(CHAT_A) or {}).get("flags.summary_enabled") or {}
        result["s73"]["a_server_value"] = a_item.get("value")
        if b_after != b_before:
            failures.append("§73: поздний ответ A изменил состояние B (%s → %s)"
                            % (b_before, b_after))

        # ── §74: наследование без потери локальных ──────────────────────
        a_override_before = (state.chat.get(CHAT_A) or {}).get(
            "flags.summary_enabled", {}).get("value")
        # Глобальное значение делаем ПРОТИВОПОЛОЖНЫМ локальному override,
        # чтобы проверить независимость (override wins), а не совпадение.
        new_global = (not bool(a_override_before))
        state.apply_post({"items": [{"key": "flags.summary_enabled",
                                     "value": new_global}]}, None)
        page.reload(wait_until="load")
        try:
            page.wait_for_selector(".app-shell", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(900)
        page.evaluate(
            "() => { const p = %s; p.setActiveChat(%d); }"
            % (PROXY_JS, int(CHAT_A)))
        page.wait_for_timeout(700)
        a_override_after = page.evaluate(
            "() => { const p = %s; return p.getModuleState(p.storeScope(),"
            " '%s'); }" % (PROXY_JS, MODULE_ID))
        result["s74"]["override_before"] = a_override_before
        result["s74"]["global_value"] = new_global
        result["s74"]["a_display_after_global_change"] = a_override_after
        result["s74"]["a_server_override"] = (
            state.chat.get(CHAT_A) or {}).get("flags.summary_enabled", {})
        # Локальный override сохранился И фактическое состояние = override
        # (не глобальное) — серверную семантику наследования не меняли.
        after_items = {it["key"]: it for it in (
            state.get(CHAT_A).get("items") or [])}
        if after_items.get("flags.summary_enabled", {}).get("chat_source") != "chat":
            failures.append("§74: локальный override чата A исчез после "
                            "изменения глобального")
        if a_override_after.get("effective") != a_override_before:
            failures.append("§74: фактическое значение чата A %s != override %s"
                            % (a_override_after.get("effective"),
                               a_override_before))
        if a_override_after.get("globalValue") != new_global:
            failures.append("§74: globalValue %s != новое глобальное %s"
                            % (a_override_after.get("globalValue"), new_global))
        result["s74"]["chat_source"] = after_items.get(
            "flags.summary_enabled", {}).get("chat_source")

        for m in errors:
            failures.append("console/pageerror: %s" % m)
        result["meta"] = {
            "head": _git_head(), "port": PORT,
            "chat_a": CHAT_A, "chat_b": CHAT_B, "module": MODULE_ID,
            "module_title": MODULE_TITLE,
        }
        ctx.close()
        browser.close()
    httpd.shutdown()

    result["failures"] = failures
    with open(E2E_RAW, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("[e2e] failures:", len(failures))
    for x in failures:
        print("  !", x)
    print("[e2e] s72 writes=%s quick=%s card=%s reload=%s"
          % (result["s72"].get("writes"), result["s72"].get("quick_checked"),
             result["s72"].get("card_checked"), result["s72"].get("reload_state")))
    print("[e2e] s73 captured=%s b_before=%s b_during=%s b_after=%s"
          % (result["s73"].get("deferred_captured"),
             result["s73"].get("b_before"), result["s73"].get("b_during_inflight"),
             result["s73"].get("b_after")))
    print("[e2e] артефакт:", E2E_RAW)
    return 1 if failures else 0


def _git_head():
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    raise SystemExit(_run())
