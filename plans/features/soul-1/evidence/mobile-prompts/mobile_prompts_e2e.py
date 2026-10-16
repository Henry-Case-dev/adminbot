"""SOUL-1 / lane B-MOBILE - реальный прогон цепочки «Ещё → ИИ → Промпты»
на настоящем `web/index.html` + реальном payload `/api/config`
(строится из `services.param_catalog.REGISTRY`, не фикстура) + серверный
store, который переживает reload (save -> reopen).

Никаких моков значений: значения приходят из каталога/стора, POST
/api/config пишет в стор, GET /api/config отдаёт стор.

Запуск:
  .venv\\Scripts\\python plans\\features\\soul-1\\evidence\\mobile-prompts\\mobile_prompts_e2e.py
Артефакты: plans/features/soul-1/evidence/mobile-prompts/
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "tools"))
import importlib.util  # noqa: E402


def _load_matrix():
    spec = importlib.util.spec_from_file_location(
        "ui_round1025_matrix", os.path.join(REPO, "tools",
                                            "ui_round1025_matrix.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_matrix()
PORT = M.PORT + 77

CONFIG_PATH = os.path.join(HERE, "config-payload-before.json")


# -- payload: реальный каталог, без ручной выдумки ---------------------------
def build_payload():
    """Payload `/api/config`, построенный из `services.param_catalog.REGISTRY`
    теми же полями, что отдаёт `web/api/routes.py::get_config` (category,
    group, description, title, type, secret, widget, select_*, per_chat,
    progressive_level из `resolve_progressive_level`, stage). Значения —
    код-каноны (`resolve_code_source`) для prompts и нейтральные плейсхолдеры
    для прочих; секретов нет."""
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
            "key": spec.pg_key,
            "value": value, "category": spec.category,
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


class Store(object):
    """Серверное состояние конфига: global-слой + журнал записей."""

    def __init__(self, payload):
        self.items = {it["key"]: json.loads(json.dumps(it))
                      for it in payload["items"]}
        self.groups = payload["groups"]
        self.writes = []

    def get(self):
        items = [json.loads(json.dumps(self.items[k]))
                 for k in sorted(self.items)]
        return {"items": items, "groups": self.groups}

    def apply_post(self, body):
        items = (body or {}).get("items") or []
        self.writes.append([{"key": i.get("key"), "value": i.get("value")}
                            for i in items])
        for i in items:
            k = i.get("key")
            if k in self.items:
                self.items[k]["value"] = i.get("value")


# -- Playwright-пробы --------------------------------------------------------
JS_VUE = r"""
(() => {
  const el = document.querySelector('#app');
  let inst = el && (el.__vue_app__ && el.__vue_app__._instance
    || el.__vue__ || (el._vnode && el._vnode.component));
  return inst && (inst.proxy || inst.ctx) || null;
})()
"""

JS_PROMPT_KEYS = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const keys = (p.configItems || []).map(function (i) { return i.key; })
    .filter(function (k) { return k.indexOf('prompts.') === 0; });
  const rendered = [];
  document.querySelectorAll('.card .font-mono.truncate').forEach(function (el) {
    const t = (el.textContent || '').trim();
    if (t.indexOf('prompts.') === 0) rendered.push(t);
  });
  const modeBlocks = Array.from(
    document.querySelectorAll('[data-block="prompt-mode-tabs"]'));
  const fallback = document.querySelector('[data-block="prompts-fallback-mode"]');
  const library = Array.from(
    document.querySelectorAll('[data-prompt-library]')).map(function (b) {
      return b.getAttribute('data-prompt-library');
    });
  return {
    activeTab: p.activeTab,
    route: p.route,
    shellMode: p.shellMode,
    configItemsPromptKeys: keys,
    renderedPromptKeys: rendered,
    tabGroups: (p.currentTabGroups || []).map(function (g) { return g.id; }),
    itemCount: p.currentTabItemCount,
    groupsLen: (p.currentTabGroups || []).length,
    configSearch: p.configSearch,
    libraryEntries: (p.promptLibraryEntries || []).map(function (e) {
      return { slug: e.slug, count: e.count, stages: e.stages };
    }),
    libraryButtons: library,
    modeTabsBlocks: modeBlocks.length,
    modeTabLabels: modeBlocks.map(function (b) {
      return Array.from(b.querySelectorAll('button')).map(
        function (x) { return x.textContent.trim(); });
    }),
    modeTextareas: modeBlocks.reduce(function (n, b) {
      return n + b.querySelectorAll('textarea').length; }, 0),
    fallbackModeBlock: !!fallback,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    bodyOverflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()
"""

JS_EDIT = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) {
    return i.key === 'prompts.direct_l1_planner_system_prompt';
  });
  if (!it) return { error: 'item missing' };
  it.value = %s;
  return { key: it.key, staged: String(it.value).slice(0, 40),
           canEdit: p.canEditConfig(it.key) };
})()
"""

JS_SAVE = r"""
(async () => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) {
    return i.key === 'prompts.direct_l1_planner_system_prompt';
  });
  if (!it) return { error: 'item missing' };
  await p.saveConfigItem(it);
  return { key: it.key, value: String(it.value).slice(0, 40),
           canEdit: p.canEditConfig(it.key) };
})()
"""

JS_VALUE = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) {
    return i.key === 'prompts.direct_l1_planner_system_prompt';
  });
  const ta = Array.from(document.querySelectorAll('textarea')).find(
    function (t) { return (t.value || '').indexOf('SOUL1_MARKER') === 0; });
  return {
    storeValue: it ? String(it.value == null ? '' : it.value).slice(0, 40)
                   : null,
    textareaValue: ta ? String(ta.value).slice(0, 40) : null,
  };
})()
"""

JS_LIBRARY = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const tree = Array.from(
    document.querySelectorAll('[data-prompt-key]')).map(function (b) {
      return b.getAttribute('data-prompt-key');
    });
  const textareas = Array.from(document.querySelectorAll('textarea'))
    .filter(function (t) {
      return !(t.closest && t.closest('.prompt-tree'));
    }).map(function (t) { return (t.value || '').length; });
  return {
    route: p.route,
    workspaceTab: p.workspaceTab,
    promptTree: tree,
    focusKey: p.workspacePromptFocus ? p.workspacePromptFocus.key : null,
    editorChars: textareas,
    door: p.workspace ? p.workspace.door : null,
    stage: p.workspace ? p.workspace.stage : null,
    wsTabs: (p.workspaceTabs || []).map(function (t) { return t.id; }),
    wsPromptList: (p.workspacePromptList || []).map(function (i) {
      return i.key + '|' + (i.stage || '-'); }),
  };
})()
"""

EMPTY_PROBE = (
    "(() => { const p = %s;"
    " const tab = document.querySelector('[data-empty-tab]');"
    " const srch = document.querySelector('[data-empty-search]');"
    " const g = function (el) { return el"
    " ? el.textContent.replace(/\\s+/g, ' ').trim() : ''; };"
    " return { tab: g(tab), srch: g(srch),"
    " itemCount: p.currentTabItemCount,"
    " groups: (p.currentTabGroups || []).map("
    "function (x) { return x.id; }) }; })()")

MARKER = "SOUL1_MARKER_DIRECT_L1"

SET_SEARCH = ("(() => { const p = %s; if (!p) return 'no vue';"
              " p.configSearch = 'zzzz'; return p.configSearch; })()")


def build_pre_fix_payload(payload):
    """RED-воспроизведение: payload каталога ДО правки — без ключа
    `prompts.direct_l1_planner_system_prompt` (его не было в `_PROMPTS`,
    поэтому `/api/config` его не отдавал)."""
    import copy
    out = copy.deepcopy(payload)
    out["items"] = [it for it in out["items"]
                    if it["key"] != "prompts.direct_l1_planner_system_prompt"]
    return out


def _probe(page):
    return page.evaluate(JS_PROMPT_KEYS % JS_VUE)


def _edit(page):
    return page.evaluate(JS_EDIT % (JS_VUE, json.dumps(MARKER)))


def _save(page):
    return page.evaluate(JS_SAVE % JS_VUE)


def _value(page):
    return page.evaluate(JS_VALUE % JS_VUE)


def _probe_library(page, slug, stage, shot):
    url = ("http://127.0.0.1:%d/web/index.html#/ai/prompts/%s%s"
           % (PORT, slug, stage))
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1800)
    page.screenshot(path=os.path.join(HERE, shot), full_page=True)
    return page.evaluate(JS_LIBRARY % JS_VUE)


def _goto_prompts(page, shot):
    """Реальная цепочка: «Ещё» -> «ИИ» -> «Промпты»."""
    page.goto("http://127.0.0.1:%d/web/index.html#/ai/prompts" % PORT,
              wait_until="load")
    page.wait_for_timeout(1500)
    more = page.query_selector('.mobile-topnav-more')
    if more:
        more.click()
        page.wait_for_timeout(400)
        ai = page.query_selector('.more-menu-item:has-text("ИИ")')
        if ai:
            ai.click()
            page.wait_for_timeout(900)
        pr = page.query_selector('.hub-card:has-text("Промпты")')
        if pr:
            pr.click()
            page.wait_for_timeout(1400)
    page.screenshot(path=os.path.join(HERE, shot), full_page=True)
    return _probe(page)


def _run(red=False):
    from playwright.sync_api import sync_playwright

    payload = build_payload()
    if red:
        payload = build_pre_fix_payload(payload)
        with open(os.path.join(HERE, "config-payload-before.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        out_name = "result-red.json"
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        out_name = "result.json"
    print("[e2e] payload items=%d groups=%d -> %s"
          % (len(payload["items"]), len(payload["groups"]), CONFIG_PATH))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store = Store(payload)

    result = {"meta": {"port": PORT, "payload_items": len(payload["items"])},
              "viewports": {}, "empty_states": {}, "failures": []}
    restricted_me = {
        "telegram_id": 5885953495, "username": "restricted",
        "first_name": "Restricted", "last_name": None, "photo_url": None,
        "role_name": "user", "permissions": {"sections": []},
        "is_custom": False, "is_global_admin": False,
        "ui_flags": dict(M.ME_JSON["ui_flags"]),
    }
    # RBAC-фильтрованный ответ сервера: роль без прав на вкладку «Промпты»
    # (`routes.py::get_config` отдаёт только видимые `can_view_param` ключи).
    restricted_payload = {
        "items": [it for it in payload["items"]
                  if not (it["category"] == "prompts"
                          or it["group"] == "limits_anticliche")],
        "groups": payload["groups"],
    }

    def _api_handler(route, request=None, *, me=None, cfg=None):
        url = route.request.url
        path = url.split("?")[0]
        if path.endswith("/api/config") and route.request.method == "POST":
            body = {}
            try:
                body = json.loads(route.request.post_data or "{}")
            except Exception:  # noqa: BLE001
                body = {}
            store.apply_post(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True,
                                           "saved": len(
                                               (body or {}).get("items")
                                               or [])}))
            return
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(cfg if cfg is not None
                                          else store.get()))
            return
        if path.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me if me is not None
                                          else M.ME_JSON))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(url)))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for label, vp in (("320", {"width": 320, "height": 640}),
                              ("390", {"width": 390, "height": 844}),
                              ("430", {"width": 430, "height": 932}),
                              ("1024", {"width": 1024, "height": 800})):
                ctx = browser.new_context(viewport=vp)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", _api_handler)
                page = ctx.new_page()
                errs = []
                page.on("pageerror",
                        lambda e: errs.append("pageerror: %s" % str(e)[:160]))
                page.on("console",
                        lambda m: errs.append("console: %s" % m.text[:160])
                        if m.type == "error" else None)

                state = _goto_prompts(page, "chain-%s.png" % label)
                state["screenshot"] = "chain-%s.png" % label
                state["page_errors"] = [e for e in errs
                                        if "favicon" not in e][:3]
                state["store_writes"] = store.writes

                edit = _edit(page)
                state["edit"] = edit
                if "error" in edit:
                    result["failures"].append(
                        "%s: редактируемый ключ prompts.direct_l1_planner_"
                        "system_prompt недоступен (%s)" % (label, edit["error"]))
                else:
                    saved = _save(page)
                    state["save"] = saved
                    page.wait_for_timeout(1200)
                    state["after_save"] = _value(page)
                    page.goto(
                        "http://127.0.0.1:%d/web/index.html#/ai/prompts" % PORT,
                        wait_until="load")
                    page.wait_for_timeout(2000)
                    reopened = _probe(page)
                    state["reopen"] = {
                        "configItemsPromptKeys":
                            reopened["configItemsPromptKeys"],
                        "renderedPromptKeys": reopened["renderedPromptKeys"],
                        "itemCount": reopened["itemCount"],
                        "modeTabsBlocks": reopened["modeTabsBlocks"],
                        "fallbackModeBlock": reopened["fallbackModeBlock"],
                    }
                    state["reopen_value"] = _value(page)
                    if (state.get("reopen_value") or {}).get("storeValue") \
                            != MARKER:
                        result["failures"].append(
                            "%s: сохранённое значение не пережило reopen"
                            % label)
                    page.screenshot(path=os.path.join(
                        HERE, "chain-%s-reopen.png" % label), full_page=True)
                # «вторая дверь»: библиотека промптов модуля Direct
                state["library"] = {
                    "direct": _probe_library(
                        page, "direct", "", "library-%s-direct.png" % label),
                    "synthesizer": _probe_library(
                        page, "direct", "/synthesizer",
                        "library-%s-direct-synth.png" % label),
                    "verbalizer": _probe_library(
                        page, "direct", "/verbalizer",
                        "library-%s-direct-verb.png" % label),
                }
                result["viewports"][label] = state
                ctx.close()

            # -- пустые состояния: честная причина вместо общей лжи ---------
            for label2, cfg2, script, shot2 in (
                ("no_prompt_items_320", restricted_payload, None,
                 "empty-state-320.png"),
                ("search_no_match_320", payload, "p.configSearch = 'zzzz';",
                 "empty-state-search-320.png"),
            ):
                ctx = browser.new_context(
                    viewport={"width": 320, "height": 640})
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**",
                          lambda r, req=None: _api_handler(r, cfg=cfg2))
                page = ctx.new_page()
                page.goto("http://127.0.0.1:%d/web/index.html#/ai/prompts"
                          % PORT, wait_until="load")
                page.wait_for_timeout(2200)
                if script:
                    page.evaluate(SET_SEARCH % JS_VUE)
                    page.wait_for_timeout(900)
                res = page.evaluate(EMPTY_PROBE % JS_VUE)
                page.screenshot(path=os.path.join(HERE, shot2),
                                full_page=True)
                result["empty_states"][label2] = {
                    "tab": res["tab"], "search": res["srch"],
                    "itemCount": res["itemCount"], "groups": res["groups"],
                    "screenshot": shot2}
                if label2 == "no_prompt_items_320":
                    if not res["tab"] or "не загружены" in res["tab"]:
                        result["failures"].append(
                            "empty-state: причина пустой вкладки нечестная (%r)"
                            % res["tab"])
                else:
                    if not res["srch"] or "по запросу" not in res["srch"]:
                        result["failures"].append(
                            "empty-state: поисковое пусто нечестное (%r)"
                            % res["srch"])
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    with open(os.path.join(HERE, out_name), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    for label, st in result["viewports"].items():
        print("[e2e] %s route=%s items=%s groups=%s rendered=%s"
              % (label, st.get("route"), st.get("itemCount"),
                 st.get("groupsLen"), len(st.get("renderedPromptKeys") or [])))
        print("      verbilizer mode blocks=%s modeTabs=%s textareas=%s "
              "fallbackBlock=%s"
              % (st.get("modeTabsBlocks"), st.get("modeTabLabels"),
                 st.get("modeTextareas"), st.get("fallbackModeBlock")))
        print("      overflowX=%s scrollWidth=%s innerWidth=%s"
              % (st.get("bodyOverflowX"), st.get("scrollWidth"),
                 st.get("innerWidth")))
        print("      edit=%s save=%s reopen_value=%s"
              % (st.get("edit"), st.get("save"), st.get("reopen_value")))
        for k, v in (st.get("library") or {}).items():
            print("      library/%s route=%s tab=%s tree=%s editorChars=%s"
                  % (k, v.get("route"), v.get("workspaceTab"),
                     v.get("promptTree"), v.get("editorChars")))
        print("      page_errors=%s" % (st.get("page_errors"),))
    for k, v in result["empty_states"].items():
        print("[empty] %s itemCount=%s tab=%r search=%r"
              % (k, v.get("itemCount"), v.get("tab"), v.get("search")))
    if result["failures"]:
        print("FAILURES: %d" % len(result["failures"]))
        for f in result["failures"]:
            print(" -", f)
        return 1
    print("MOBILE PROMPTS E2E: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(red="--red" in sys.argv))
