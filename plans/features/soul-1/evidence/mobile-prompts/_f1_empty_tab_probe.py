# -*- coding: utf-8 -*-
"""SOUL-1, fix F1 (review-ui-fixes.md, блокирующая находка): честность
пустых состояний конфиг-вкладки после правки `emptyTabReason()`.

Прогон — на РЕАЛЬНЫХ `web/index.html` + `web/app.js` + реальном payload
`/api/config` (строится из `services.param_catalog.REGISTRY`, тот же
build_payload, что в `serve_for_visual.py`/`_r3_mobile_prompts_e2e.py`),
Chromium (Playwright), вьюпорты 320x700 и 390x844.

Два сервера (payload переключается портом — так же видно MCP-браузерам):
  * PORT_FULL       — полный реальный payload;
  * PORT_RESTRICTED — payload только с `category == 'prompts'`
    (сценарий ревьюера: «configItems = только prompts»).

Случаи:
  a1) пустая вкладка (`smart_cache`, 0 элементов) БЕЗ запроса →
      честная причина по роли/правам;
  b)  та же пустая вкладка + запрос, введённый в реальный input →
      причина НЕ приписывается поиску (контрпример F1);
  a2) тот же запрос + реальная смена области через `setActiveChat('-1')`
      (тот же код-путь, что у дропдауна `pickScope`) → честная scope-причина;
  c)  вкладка «Промпты» (элементы есть) + запрос без совпадений →
      сестринская карточка `[data-empty-search]` с запросным текстом;
      после очистки поиска группы возвращаются (запрос — настоящая причина);
  d)  библиотека промптов модуля Direct: дерево содержит ВСЕ ключи модели
      промптов, включая новый `prompts.direct_l1_planner_system_prompt`.

Артефакты: `_f1_*` рядом с этим файлом.
Запуск: .venv\\Scripts\\python.exe <этот файл> [--expect-red]
"""
import importlib.util
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "tools"))


def _load_matrix():
    spec = importlib.util.spec_from_file_location(
        "ui_round1025_matrix", os.path.join(REPO, "tools",
                                            "ui_round1025_matrix.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_matrix()
PORT_FULL = M.PORT + 80          # 8871
PORT_RESTRICTED = M.PORT + 81    # 8872

L1_KEY = "prompts.direct_l1_planner_system_prompt"
QUERY = "zzzqqq"
VIEWPORTS = (("320", {"width": 320, "height": 700}),
             ("390", {"width": 390, "height": 844}))


def build_payload():
    """Полный payload `/api/config` из `services.param_catalog.REGISTRY`."""
    from services import param_catalog as pc
    from services.pg_db import resolve_code_source

    items = []
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        secret = bool(getattr(spec, "secret", False))
        widget = getattr(spec, "widget", "") or ""
        stype = getattr(spec, "type", "str") or "str"
        if secret:
            value = {"configured": True, "last4": "0000"}
        elif spec.code_source:
            value = resolve_code_source(spec.code_source)
        elif widget == "keyvalue":
            value = {}
        elif stype == "bool":
            value = False
        elif stype in ("int", "float"):
            value = 1
        elif widget == "select" and getattr(spec, "select_options", None):
            value = list(spec.select_options)[0]
        else:
            value = ""
        items.append({
            "key": spec.pg_key, "value": value, "category": spec.category,
            "secret": secret, "chat_source": "", "global_value": None,
            "title": getattr(spec, "title_ru", key) or key, "type": stype,
            "updated_at": None, "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "widget": widget,
            "select_options": list(spec.select_options)
            if widget == "select" and getattr(spec, "select_options", None)
            else None,
            "select_labels": list(spec.select_labels)
            if widget == "select" and getattr(spec, "select_labels", None)
            else None,
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": pc.resolve_progressive_level(spec),
            "stage": getattr(spec, "stage", None),
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    return {"items": items, "groups": groups}


FULL = build_payload()
RESTRICTED = {"items": [it for it in FULL["items"]
                        if it["category"] == "prompts"],
              "groups": FULL["groups"]}


def _serve(port, payload):
    class H(M._Handler):
        def _send_json(self, obj, status=200):  # noqa: N802
            data = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path.endswith("/api/config"):
                self._send_json(payload)
                return
            if path.endswith("/api/me"):
                self._send_json(M.ME_JSON)
                return
            if path.startswith("/api/"):
                self._send_json(M._stub_for(self.path))
                return
            M._Handler.do_GET(self)

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0].endswith("/api/config"):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                self._send_json({"ok": True, "saved": 0})
                return
            M._Handler.do_POST(self)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


JS_VUE = r"""
(() => {
  const el = document.querySelector('#app');
  let inst = el && (el.__vue_app__ && el.__vue_app__._instance
    || el.__vue__ || (el._vnode && el._vnode.component));
  return inst && (inst.proxy || inst.ctx) || null;
})()
"""

PROBE = r"""
(async () => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  await p.$nextTick();
  const g = function (el) { return el
    ? (el.textContent || '').replace(/\s+/g, ' ').trim() : ''; };
  const vis = function (el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const cardA = document.querySelector('[data-empty-tab]');
  const cardB = document.querySelector('[data-empty-search]');
  const q = document.querySelector('input[placeholder^="Поиск по параметрам"]');
  return {
    route: p.route, activeTab: p.activeTab, scopeKind: p.scopeKind,
    activeChatId: p.activeChatId, search: p.configSearch,
    totalItems: (p.configItems || []).length,
    itemCount: p.currentTabItemCount,
    groupIds: (p.currentTabGroups || []).map(function (x) { return x.id; }),
    cardA: { visible: vis(cardA), text: g(cardA) },
    cardB: { visible: vis(cardB), text: g(cardB) },
    searchInputVisible: vis(q),
    width: window.innerWidth,
  };
})()
"""

LIB_PROBE = r"""
(async () => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  await p.$nextTick();
  const tree = document.querySelector('[data-prompt-tree]');
  const keys = tree ? Array.from(tree.querySelectorAll('[data-prompt-key]'))
    .map(function (b) { return b.getAttribute('data-prompt-key'); }) : [];
  const grp = tree ? Array.from(tree.querySelectorAll('[data-prompt-group]'))
    .map(function (d) { return d.getAttribute('data-prompt-group'); }) : [];
  const cards = document.querySelectorAll('[data-prompt-library-modules]');
  return {
    route: p.route,
    module: p.workspaceModule ? p.workspaceModule.id : null,
    workspaceTab: p.workspaceTab,
    treePresent: !!tree,
    treeVisible: !!(tree && tree.getBoundingClientRect().height > 0),
    domKeys: keys, domGroups: grp,
    modelKeys: (p.workspacePromptList || []).map(function (i) { return i.key; }),
    libraryCards: cards.length,
    entries: (p.promptLibraryEntries || []).map(function (e) {
      return e.slug + '|' + e.count; }),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  };
})()
"""


def set_search(page, value, out):
    """Реальный ввод в поле поиска; fallback — прямое состояние (фиксируем)."""
    loc = page.locator('input[placeholder^="Поиск по параметрам"]').first
    via = "ui"
    try:
        if loc.count() and loc.is_visible():
            loc.fill(value)
        else:  # pragma: no cover - защитный путь
            via = "state"
    except Exception:  # noqa: BLE001
        via = "state"
    if via == "state":  # pragma: no cover
        page.evaluate(
            "(async () => { const p = %s; p.configSearch = %s;"
            " await p.$nextTick(); return p.configSearch; })()"
            % (JS_VUE, json.dumps(value)))
    page.wait_for_timeout(500)
    out["search_via"] = via


def set_scope(page, value, out):
    """Реальная смена области: тот же код-путь, что у дропдауна (`pickScope`
    → `setActiveChat`). '' → «Весь бот» (global), '-1' → чат."""
    page.evaluate(
        "(async () => { const p = %s; p.setActiveChat(%s); await p.$nextTick();"
        " return String(p.activeChatId); })()"
        % (JS_VUE, json.dumps(value)))
    page.wait_for_timeout(1600)
    out.setdefault("scope_calls", []).append(value)


def probe(page):
    return page.evaluate(PROBE % JS_VUE)


def goto(page, port, route):
    page.goto("http://127.0.0.1:%d/web/index.html%s" % (port, route),
              wait_until="load")
    page.wait_for_timeout(2200)


def _case(checks, result, name, ok, detail):
    checks.append({"case": name, "ok": bool(ok), "detail": detail})
    if not ok:
        result["failures"].append("%s: %s" % (name, detail))


def run(expect_red):
    from playwright.sync_api import sync_playwright

    red_prefix = "_f1r_" if expect_red else "_f1_"
    out_name = "_f1_result%s.json" % ("-red" if expect_red else "")
    txt_name = "_f1_run%s.txt" % ("-red" if expect_red else "")

    httpd_full = _serve(PORT_FULL, FULL)
    httpd_restricted = _serve(PORT_RESTRICTED, RESTRICTED)
    result = {
        "meta": {
            "ports": {"full": PORT_FULL, "restricted": PORT_RESTRICTED},
            "payload_full_items": len(FULL["items"]),
            "payload_restricted_items": len(RESTRICTED["items"]),
            "query": QUERY, "expect_red": expect_red,
            "viewports": [v[0] for v in VIEWPORTS],
        },
        "cases": {}, "checks": [], "failures": [],
    }
    lines = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for label, vp in VIEWPORTS:
                ctx = browser.new_context(viewport=vp)
                ctx.add_init_script(M.TMA_STUB)
                page = ctx.new_page()
                errs = []
                page.on("pageerror",
                        lambda e: errs.append("pageerror: %s" % str(e)[:160]))
                page.on("console",
                        lambda m: errs.append("console: %s" % m.text[:160])
                        if m.type == "error" else None)
                vp_cases = {}

                # ---------- (d) библиотека промптов модуля Direct ----------
                goto(page, PORT_FULL, "#/ai/prompts")
                lib_ai = page.evaluate(LIB_PROBE % JS_VUE)
                page.screenshot(path=os.path.join(
                    HERE, red_prefix + "d-library-ai-%s.png" % label),
                    full_page=True)
                goto(page, PORT_FULL, "#/ai/prompts/direct")
                lib = page.evaluate(LIB_PROBE % JS_VUE)
                page.screenshot(path=os.path.join(
                    HERE, red_prefix + "d-library-direct-%s.png" % label),
                    full_page=True)
                dom_keys = set(lib.get("domKeys") or [])
                model_keys = set(lib.get("modelKeys") or [])
                vp_cases["d_library"] = {
                    "ai_entries": lib_ai.get("entries"),
                    "ai_cards": lib_ai.get("libraryCards"),
                    "module": lib.get("module"),
                    "tree_present": lib.get("treePresent"),
                    "tree_visible": lib.get("treeVisible"),
                    "dom_keys": sorted(dom_keys),
                    "dom_groups": lib.get("domGroups"),
                    "model_keys": sorted(model_keys),
                    "missing": sorted(model_keys - dom_keys),
                    "extra": sorted(dom_keys - model_keys),
                    "l1_in_dom": L1_KEY in dom_keys,
                    "overflow_x": lib.get("scrollWidth", 0)
                    > lib.get("innerWidth", 0) + 1,
                }
                _case(result["checks"], result, "d-library-%s/tree-visible"
                      % label, lib.get("treeVisible") is True,
                      "treePresent=%s" % lib.get("treePresent"))
                _case(result["checks"], result, "d-library-%s/all-model-keys"
                      % label,
                      bool(model_keys) and model_keys == dom_keys,
                      "missing=%s extra=%s" % (sorted(model_keys - dom_keys),
                                               sorted(dom_keys - model_keys)))
                _case(result["checks"], result, "d-library-%s/l1-entry" % label,
                      L1_KEY in dom_keys,
                      "L1=%s keys=%d" % (L1_KEY, len(dom_keys)))
                _case(result["checks"], result, "d-library-%s/module-cards"
                      % label,
                      bool(lib_ai.get("libraryCards"))
                      and bool(lib_ai.get("entries")),
                      "cards=%s entries=%s" % (lib_ai.get("libraryCards"),
                                               lib_ai.get("entries")))
                _case(result["checks"], result, "d-library-%s/no-overflow" % label,
                      lib.get("scrollWidth", 0)
                      <= lib.get("innerWidth", 0) + 1,
                      "scrollWidth=%s innerWidth=%s"
                      % (lib.get("scrollWidth"), lib.get("innerWidth")))

                # ---------- (c) вкладка с элементами + запрос ----------
                goto(page, PORT_FULL, "#/ai/prompts")
                set_search(page, QUERY, vp_cases)
                c1 = probe(page)
                page.screenshot(path=os.path.join(
                    HERE, red_prefix + "c-search-nomatch-%s.png" % label),
                    full_page=True)
                vp_cases["c_before_clear"] = c1
                clear = page.locator('button[title="Очистить поиск"]').first
                if clear.count() and clear.is_visible():
                    clear.click()
                else:  # pragma: no cover
                    set_search(page, "", vp_cases)
                page.wait_for_timeout(600)
                c2 = probe(page)
                vp_cases["c_after_clear"] = c2
                _case(result["checks"], result, "c-%s/query-message" % label,
                      c1["cardB"]["visible"]
                      and QUERY in c1["cardB"]["text"]
                      and "ничего не найдено по запросу" in
                      c1["cardB"]["text"].lower()
                      and not c1["cardA"]["visible"],
                      "cardB=%r cardA_visible=%s itemCount=%s groups=%s"
                      % (c1["cardB"]["text"], c1["cardA"]["visible"],
                         c1["itemCount"], c1["groupIds"]))
                _case(result["checks"], result, "c-%s/tab-has-items" % label,
                      c1["itemCount"] > 0 and not c1["groupIds"],
                      "itemCount=%s groups=%s"
                      % (c1["itemCount"], c1["groupIds"]))
                _case(result["checks"], result, "c-%s/clear-restores-groups"
                      % label,
                      bool(c2["groupIds"]) and not c2["cardB"]["visible"]
                      and c2["itemCount"] > 0,
                      "groups=%s cardB_visible=%s"
                      % (c2["groupIds"], c2["cardB"]["visible"]))

                # ---------- (a1)/(b)/(a2) пустая вкладка ----------
                # Явные области: global (ветка роли/прав) и чат (ветка scope).
                # `setActiveChat` — тот же путь, что у дропдауна pickScope.
                goto(page, PORT_RESTRICTED, "#/ai/smart-cache")
                set_scope(page, "", vp_cases)
                a1 = probe(page)
                page.screenshot(path=os.path.join(
                    HERE, red_prefix + "ab-empty-noglobal-%s.png" % label),
                    full_page=True)
                vp_cases["a1_no_query"] = a1
                _case(result["checks"], result, "a1-%s/empty-tab-card" % label,
                      a1["cardA"]["visible"] and a1["itemCount"] == 0
                      and a1["totalItems"] > 0 and a1["scopeKind"] == "global",
                      "itemCount=%s totalItems=%s scope=%s"
                      % (a1["itemCount"], a1["totalItems"], a1["scopeKind"]))
                _case(result["checks"], result, "a1-%s/honest-role-reason"
                      % label,
                      "доступных вашей роли" in a1["cardA"]["text"]
                      and "под запрос" not in a1["cardA"]["text"],
                      "cardA=%r" % a1["cardA"]["text"])

                set_search(page, QUERY, vp_cases)
                b = probe(page)
                page.screenshot(path=os.path.join(
                    HERE, red_prefix + "b-empty-with-query-%s.png" % label),
                    full_page=True)
                vp_cases["b_empty_with_query"] = b
                text = b["cardA"]["text"]
                _case(result["checks"], result,
                      "b-%s/no-query-as-cause" % label,
                      b["cardA"]["visible"]
                      and "под запрос" not in text
                      and "параметры вкладки доступны" not in text
                      and "параметры вкладки доступны, но" not in text,
                      "cardA=%r itemCount=%s" % (text, b["itemCount"]))
                _case(result["checks"], result, "b-%s/real-cause-named" % label,
                      "доступных вашей роли" in text
                      and b["itemCount"] == 0 and b["totalItems"] > 0,
                      "cardA=%r itemCount=%s totalItems=%s"
                      % (text, b["itemCount"], b["totalItems"]))
                if QUERY in text:
                    _case(result["checks"], result,
                          "b-%s/query-only-as-non-cause" % label,
                          "ничего не изменит" in text,
                          "cardA=%r" % text)

                set_scope(page, "-1", vp_cases)
                a2 = probe(page)
                page.screenshot(path=os.path.join(
                    HERE, red_prefix + "a2-empty-chat-scope-%s.png" % label),
                    full_page=True)
                vp_cases["a2_chat_scope_with_query"] = a2
                _case(result["checks"], result, "a2-%s/chat-scope" % label,
                      a2["scopeKind"] == "chat",
                      "scopeKind=%s activeChatId=%s"
                      % (a2["scopeKind"], a2["activeChatId"]))
                _case(result["checks"], result, "a2-%s/honest-scope-reason"
                      % label,
                      "нет применимых" in a2["cardA"]["text"]
                      and "(чат)" in a2["cardA"]["text"]
                      and "под запрос" not in a2["cardA"]["text"],
                      "cardA=%r" % a2["cardA"]["text"])

                vp_cases["page_errors"] = [e for e in errs
                                           if "favicon" not in e][:3]
                if vp_cases["page_errors"]:
                    result["failures"].append(
                        "%s: ошибки страницы: %s"
                        % (label, vp_cases["page_errors"]))
                result["cases"][label] = vp_cases
                lines.append("[f1] vp=%s cardA(a1)=%r"
                             % (label, vp_cases["a1_no_query"]["cardA"]["text"]))
                lines.append("[f1] vp=%s cardA(b)=%r"
                             % (label, vp_cases["b_empty_with_query"]
                                ["cardA"]["text"]))
                lines.append("[f1] vp=%s cardA(a2)=%r"
                             % (label, vp_cases["a2_chat_scope_with_query"]
                                ["cardA"]["text"]))
                lines.append("[f1] vp=%s cardB(c)=%r search_via=%s"
                             % (label, vp_cases["c_before_clear"]
                                ["cardB"]["text"],
                                vp_cases.get("search_via")))
                lines.append("[f1] vp=%s library keys=%d l1=%s"
                             % (label, len(vp_cases["d_library"]["dom_keys"]),
                                vp_cases["d_library"]["l1_in_dom"]))
                ctx.close()
            browser.close()
    finally:
        httpd_full.shutdown()
        httpd_restricted.shutdown()

    passed = [c for c in result["checks"] if c["ok"]]
    result["summary"] = {"checks": len(result["checks"]),
                         "passed": len(passed),
                         "failed": len(result["checks"]) - len(passed)}
    header = ("[f1] expect_red=%s checks=%d passed=%d failed=%d"
              % (expect_red, result["summary"]["checks"],
                 result["summary"]["passed"], result["summary"]["failed"]))
    lines.insert(0, header)
    for c in result["checks"]:
        if not c["ok"]:
            lines.append("[f1][FAIL] %s :: %s" % (c["case"], c["detail"]))
    with open(os.path.join(HERE, out_name), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(HERE, txt_name), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if not expect_red and result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(run("--expect-red" in sys.argv))
