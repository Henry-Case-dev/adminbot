"""SOUL-1 / lane B-MOBILE, попытка 3 (`_r3_`): реальная цепочка
«Ещё → ИИ → Промпты» на настоящем `web/index.html` + реальном payload
`/api/config` (строится из `services.param_catalog.REGISTRY`) + серверный
store, переживающий reload (save -> reopen).

Дополнительно к прогону попыток 1-2:
  * классификация КАЖДОГО ключа `prompts.*`: где он рендерится
      (item_card | mode_tabs | fallback_select | MISSING) на каждом вьюпорте;
  * реальный пользовательский путь сохранения (ввод в textarea -> sticky-save
      «Сохранить изменения» -> POST /api/config -> reload) для:
      - `prompts.direct_l1_planner_system_prompt` (новый ключ каталога),
      - `prompts.verbilizer_mode_casual` (режим Вербализатора под V2),
      - `prompts.verbilizer_default_mode` (шапочный fallback-дропдаун);
  * проверка, что ВСЕ группы вкладки «Промпты» представлены в DOM
      (`prompts_verbilizer` под V2 — через mode-tabs/fallback, не карточкой).

Артефакты: префикс `_r3_` в plans/features/soul-1/evidence/mobile-prompts/.
Запуск: .venv\\Scripts\\python.exe <этот файл> [--red]
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
PORT = M.PORT + 78  # 8869 — не пересекается с попытками 1-2 (8868)

PREFIX = "_r3_"
RED_PREFIX = "_r3r_"

CONFIG_PATH = os.path.join(HERE, PREFIX + "config-payload-after.json")

L1_KEY = "prompts.direct_l1_planner_system_prompt"
MODE_KEYS = ("prompts.verbilizer_mode_casual",
             "prompts.verbilizer_mode_serious",
             "prompts.verbilizer_mode_deep_research")
DEFAULT_MODE_KEY = "prompts.verbilizer_default_mode"
MODE_MARKER = "SOUL1R3_MARKER_MODE_CASUAL"
L1_MARKER = "SOUL1R3_MARKER_DIRECT_L1"


def build_payload():
    """Payload `/api/config`, построенный из `services.param_catalog.REGISTRY`
    теми же полями, что отдаёт `web/api/routes.py::get_config`. Значения —
    код-каноны (`resolve_code_source`); секретов нет."""
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


JS_VUE = r"""
(() => {
  const el = document.querySelector('#app');
  let inst = el && (el.__vue_app__ && el.__vue_app__._instance
    || el.__vue__ || (el._vnode && el._vnode.component));
  return inst && (inst.proxy || inst.ctx) || null;
})()
"""

JS_CLASSIFY = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const keys = (p.configItems || []).map(function (i) { return i.key; })
    .filter(function (k) { return k.indexOf('prompts.') === 0; });
  const cardKeys = {};
  document.querySelectorAll('.card .font-mono.truncate').forEach(function (el) {
    const t = (el.textContent || '').trim();
    if (t.indexOf('prompts.') === 0) cardKeys[t] = true;
  });
  const modeKeys = ['prompts.verbilizer_mode_casual',
                    'prompts.verbilizer_mode_serious',
                    'prompts.verbilizer_mode_deep_research'];
  const blocks = Array.from(
    document.querySelectorAll('[data-block="prompt-mode-tabs"]'));
  const visible = function (el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const modeBlocksVisible = blocks.filter(visible).length;
  const fallback = document.querySelector('[data-block="prompts-fallback-mode"]');
  const fallbackVisible = visible(fallback);
  const classify = {};
  keys.forEach(function (k) {
    if (cardKeys[k]) classify[k] = 'item_card';
    else if (modeKeys.indexOf(k) >= 0 && modeBlocksVisible > 0)
      classify[k] = 'mode_tabs';
    else if (k === 'prompts.verbilizer_default_mode' && fallbackVisible)
      classify[k] = 'fallback_select';
    else classify[k] = 'MISSING';
  });
  const missing = keys.filter(function (k) { return classify[k] === 'MISSING'; });
  const canEdit = {};
  keys.forEach(function (k) { canEdit[k] = !!p.canEditConfig(k); });
  const text = document.body.textContent || '';
  const groups = (p.currentTabGroups || []).map(function (g) {
    const title = (g.meta && g.meta.title) || '';
    return { id: g.id, title: title,
             titleInDom: !!title && text.indexOf(title) >= 0 };
  });
  return {
    route: p.route, activeTab: p.activeTab, promptKeys: keys,
    classify: classify, missing: missing, canEdit: canEdit,
    modeBlocks: blocks.length, modeBlocksVisible: modeBlocksVisible,
    modeTextareas: blocks.reduce(function (n, b) {
      return n + b.querySelectorAll('textarea').length; }, 0),
    fallbackVisible: fallbackVisible,
    fallbackHasSelect: !!(fallback && fallback.querySelector('select')),
    groupIds: (p.currentTabGroups || []).map(function (g) { return g.id; }),
    groups: groups,
    itemCount: p.currentTabItemCount,
    libraryEntries: (p.promptLibraryEntries || []).map(function (e) {
      return { slug: e.slug, count: e.count, stages: e.stages }; }),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()
"""

JS_GET = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) { return i.key === %s; });
  return {
    exists: !!it,
    value: it ? String(it.value == null ? '' : it.value).slice(0, 60) : null,
    canEdit: it ? !!p.canEditConfig(it.key) : false,
  };
})()
"""

JS_MODE_SYNC = r"""
(() => {
  const p = %s;
  if (!p) return { error: 'no vue instance' };
  const info = {};
  ['casual', 'serious', 'deep_research'].forEach(function (m) {
    const it = p.promptModeItem(m);
    info[m] = it ? String(it.value == null ? '' : it.value).slice(0, 60) : null;
  });
  return { promptMode: p.promptMode, modes: info,
           defaultMode: (p.promptDefaultModeItem()
             ? String(p.promptDefaultModeItem().value).slice(0, 60) : null) };
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

SET_SEARCH = ("(() => { const p = %s; if (!p) return 'no vue';"
              " p.configSearch = 'zzzz'; return p.configSearch; })()")


def _snapshot_marker(store, key, since=0):
    vals = []
    for batch in store.writes[since:]:
        for w in batch:
            if w.get("key") == key:
                vals.append(w.get("value"))
    return vals


def _save_via_sticky(page, label, result):
    """Реальный путь пользователя: появляется sticky-save -> клик Save."""
    ok = True
    try:
        page.wait_for_selector(".sticky-save button.btn-accent",
                               state="visible", timeout=6000)
    except Exception:  # noqa: BLE001
        result["failures"].append("%s: sticky-save не появился после правки"
                                  % label)
        return False
    page.screenshot(path=os.path.join(HERE, PREFIX + "sticky-%s.png" % label))
    try:
        page.locator(".sticky-save:visible button.btn-accent").first.click()
        page.wait_for_selector(".sticky-save", state="detached", timeout=9000)
    except Exception:  # noqa: BLE001
        # Панель могла остаться из-за провала записи — фиксируем честно.
        ok = False
        result["failures"].append("%s: sticky-save не закрылся после Save"
                                  % label)
    page.wait_for_timeout(600)
    return ok


def _l1_flow(page, vp, store, result):
    """Новый ключ: реальный ввод -> sticky Save -> POST -> reload.

    Маркер уникален на каждый вьюпорт: store переживает прогоны, повторный
    ввод того же значения не создаёт dirty (и честно не должен).
    """
    marker = L1_MARKER + "_" + vp
    out = {"marker": marker}
    card_key = ('div.card.p-4:has(> div.font-mono.truncate:text-is("%s"))'
                % L1_KEY)
    ta = page.locator(card_key + " textarea").first
    if ta.count() == 0:
        result["failures"].append(
            "%s: карточка %s отсутствует на вкладке" % (vp, L1_KEY))
        return out
    ta.fill(marker)
    page.wait_for_timeout(300)
    after_typing = page.evaluate(JS_GET % (JS_VUE, json.dumps(L1_KEY)))
    out["after_typing_item"] = after_typing
    if not after_typing.get("exists") or marker not in \
            (after_typing.get("value") or ""):
        result["failures"].append(
            "%s: v-model не принял ввод в textarea L1" % vp)
    page.screenshot(path=os.path.join(HERE, PREFIX + "l1-edit-%s.png" % vp))
    w0 = len(store.writes)
    saved = _save_via_sticky(page, "l1-%s" % vp, result)
    out["saved_ok"] = saved
    posted = [v for v in _snapshot_marker(store, L1_KEY, since=w0)
              if isinstance(v, str) and v.startswith(marker)]
    out["posted_values"] = posted[:2]
    if not posted:
        result["failures"].append(
            "%s: POST /api/config не донёс значение L1" % vp)
    page.reload(wait_until="load")
    page.wait_for_timeout(1800)
    reopened = page.evaluate(JS_GET % (JS_VUE, json.dumps(L1_KEY)))
    out["reopened_item"] = reopened
    ta2 = page.locator(card_key + " textarea").first
    out["reopened_textarea"] = ta2.input_value()[:60] if ta2.count() else None
    if marker not in (reopened.get("value") or ""):
        result["failures"].append(
            "%s: значение L1 не пережило reopen" % vp)
    if out["reopened_textarea"] is None or \
            marker not in out["reopened_textarea"]:
        result["failures"].append(
            "%s: textarea L1 после reopen пуста/старая" % vp)
    page.screenshot(path=os.path.join(HERE, PREFIX + "l1-reopen-%s.png" % vp),
                    full_page=True)
    return out


def _mode_flow(page, vp, store, result):
    """Режим Вербализатора под V2: таб Casual -> ввод -> sticky Save -> reload."""
    marker = MODE_MARKER + "_" + vp
    out = {"marker": marker}
    block = page.locator('[data-block="prompt-mode-tabs"]:visible').first
    if block.count() == 0:
        result["failures"].append(
            "%s: ни одного видимого блока mode-tabs под V2" % vp)
        return out
    block.locator('button:text-is("Casual")').first.click()
    page.wait_for_timeout(250)
    ta = block.locator("textarea:visible").first
    ta.fill(marker)
    page.wait_for_timeout(300)
    staged = page.evaluate(JS_MODE_SYNC % JS_VUE)
    out["after_typing"] = staged
    if marker not in (staged.get("modes", {}).get("casual") or ""):
        result["failures"].append(
            "%s: v-model не принял ввод в режим Casual" % vp)
    w0 = len(store.writes)
    saved = _save_via_sticky(page, "mode-%s" % vp, result)
    out["saved_ok"] = saved
    posted = [v for v in _snapshot_marker(store, MODE_KEYS[0], since=w0)
              if isinstance(v, str) and v.startswith(marker)]
    out["posted_values"] = posted[:2]
    if not posted:
        result["failures"].append(
            "%s: POST /api/config не донёс режим Casual" % vp)
    page.reload(wait_until="load")
    page.wait_for_timeout(1800)
    reopened = page.evaluate(JS_MODE_SYNC % JS_VUE)
    out["reopened"] = reopened
    if marker not in (reopened.get("modes", {}).get("casual") or ""):
        result["failures"].append(
            "%s: значение режима Casual не пережило reopen" % vp)
    # после reload активен default-режим (может быть не Casual) — вернёмся на
    # таб Casual и прочитаем визуально показанное значение
    block2 = page.locator('[data-block="prompt-mode-tabs"]:visible').first
    block2.locator('button:text-is("Casual")').first.click()
    page.wait_for_timeout(250)
    ta2 = block2.locator("textarea:visible").first
    out["reopened_textarea"] = ta2.input_value()[:60] if ta2.count() else None
    if out["reopened_textarea"] is None or \
            marker not in out["reopened_textarea"]:
        result["failures"].append(
            "%s: textarea режима Casual после reopen пуста/старая" % vp)
    page.screenshot(path=os.path.join(HERE, PREFIX + "mode-reopen-%s.png" % vp))
    return out


def _fallback_flow(page, vp, store, result):
    """Fallback-дропдаун в шапке: смена -> автосейв -> reload."""
    out = {}
    sel = page.locator('[data-block="prompts-fallback-mode"] select')
    if sel.count() == 0:
        result["failures"].append(
            "%s: шапочный fallback-дропдаун не отрендерился под V2" % vp)
        return out
    current = sel.first.input_value()
    target = next(o for o in ("deep_research", "serious", "casual")
                  if o != current)
    out["from"], out["to"] = current, target
    w0 = len(store.writes)
    sel.first.select_option(target)
    page.wait_for_timeout(1300)
    posted = [v for v in _snapshot_marker(store, DEFAULT_MODE_KEY, since=w0)]
    out["posted_values"] = posted[:3]
    if target not in posted:
        result["failures"].append(
            "%s: смена fallback-режима не сохранилась (POST)" % vp)
    page.reload(wait_until="load")
    page.wait_for_timeout(1800)
    reopened = page.evaluate(JS_MODE_SYNC % JS_VUE)
    out["reopened"] = reopened
    sel2 = page.locator('[data-block="prompts-fallback-mode"] select')
    out["reopened_select"] = sel2.first.input_value() if sel2.count() else None
    if out["reopened_select"] != target:
        result["failures"].append(
            "%s: fallback-режим не пережил reopen (%r, ждали %s)"
            % (vp, out["reopened_select"], target))
    page.screenshot(path=os.path.join(HERE, PREFIX
                                      + "fallback-reopen-%s.png" % vp))
    return out


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
    return page.evaluate(JS_CLASSIFY % JS_VUE)


def _dump(result, out_name):
    with open(os.path.join(HERE, out_name), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)


def _print_summary(result, red):
    for label, st in result["viewports"].items():
        print("[r3] %s route=%s keys=%s missing=%s itemCount=%s"
              % (label, st.get("route"), len(st.get("promptKeys") or []),
                 st.get("missing"), st.get("itemCount")))
        print("      modes(visible/blocks)=%s/%s textareas=%s fallback=%s "
              "overflowX=%s"
              % (st.get("modeBlocksVisible"), st.get("modeBlocks"),
                 st.get("modeTextareas"), st.get("fallbackVisible"),
                 st.get("overflowX")))
        print("      groups: %s"
              % [(g["id"], g["titleInDom"])
                 for g in (st.get("groups") or [])])
        if not red:
            l1 = st.get("l1_flow") or {}
            print("      l1: typing_item=%s saved=%s posted=%s "
                  "reopened_item=%s reopened_ta=%s"
                  % (l1.get("after_typing_item"), l1.get("saved_ok"),
                     l1.get("posted_values"), l1.get("reopened_item"),
                     l1.get("reopened_textarea")))
            mf = st.get("mode_flow") or {}
            print("      mode: saved=%s posted=%s reopened=%s reopened_ta=%s"
                  % (mf.get("saved_ok"), mf.get("posted_values"),
                     mf.get("reopened"), mf.get("reopened_textarea")))
            fb = st.get("fallback_flow") or {}
            print("      fallback: posted=%s reopened_select=%s"
                  % (fb.get("posted_values"), fb.get("reopened_select")))
            for k, v in (st.get("library") or {}).items():
                print("      library/%s route=%s tab=%s tree=%s editorChars=%s"
                      % (k, v.get("route"), v.get("workspaceTab"),
                         v.get("promptTree"), v.get("editorChars")))
        print("      page_errors=%s" % (st.get("page_errors"),))
    if not red:
        for k, v in result["empty_states"].items():
            print("[r3] empty %s itemCount=%s tab=%r search=%r"
                  % (k, v.get("itemCount"), v.get("tab"), v.get("search")))


def _run(red=False):
    from playwright.sync_api import sync_playwright

    payload = build_payload()
    if red:
        payload = {"items": [it for it in payload["items"]
                             if it["key"] != L1_KEY],
                   "groups": payload["groups"]}
        out_name = PREFIX + "result-red.json"
        prefix = RED_PREFIX
        with open(os.path.join(HERE, prefix + "config-payload-red.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    else:
        out_name = PREFIX + "result.json"
        prefix = PREFIX
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    prompt_keys = sorted(it["key"] for it in payload["items"]
                         if it["key"].startswith("prompts."))
    l1_present = L1_KEY in prompt_keys
    print("[r3] payload items=%d groups=%d prompts_keys=%d l1_present=%s -> %s"
          % (len(payload["items"]), len(payload["groups"]), len(prompt_keys),
             l1_present, out_name))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store = Store(payload)

    result = {"meta": {"port": PORT, "payload_items": len(payload["items"]),
                       "prompts_keys": prompt_keys, "l1_present": l1_present,
                       "red": red},
              "viewports": {}, "empty_states": {}, "failures": []}
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
                                               (body or {}).get("items") or [])}))
            return
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(cfg if cfg is not None
                                          else store.get()))
            return
        if path.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(me if me is not None else M.ME_JSON))
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

                state = _goto_prompts(page, prefix + "chain-%s.png" % label)
                state["page_errors"] = [e for e in errs
                                        if "favicon" not in e][:3]
                if not red and not l1_present:
                    pass
                if red:
                    if L1_KEY not in (state.get("promptKeys") or []):
                        result["failures"].append(
                            "%s: RED подтверждён — %s отсутствует в /api/config"
                            % (label, L1_KEY))
                    result["viewports"][label] = state
                    _dump(result, out_name)
                    ctx.close()
                    continue

                # --- полнота вкладки: ключи, группы, рендер -----------------
                keys = state.get("promptKeys") or []
                if L1_KEY not in keys:
                    result["failures"].append(
                        "%s: %s отсутствует в configItems /api/config"
                        % (label, L1_KEY))
                if state.get("missing"):
                    result["failures"].append(
                        "%s: ключи без места рендера: %s"
                        % (label, state["missing"]))
                if state.get("overflowX"):
                    result["failures"].append(
                        "%s: горизонтальный оверфлоу (scrollWidth=%s)"
                        % (label, state.get("scrollWidth")))
                if state.get("modeBlocksVisible", 0) < 6:
                    result["failures"].append(
                        "%s: видимых блоков режимов Вербализатора %s (ждём 6)"
                        % (label, state.get("modeBlocksVisible")))
                if not state.get("fallbackVisible"):
                    result["failures"].append(
                        "%s: шапочный fallback-режим не виден под V2" % label)
                # группы: все, кроме prompts_verbilizer (её ключи живут в
                # mode-tabs/fallback), должны быть представлены в DOM
                for g in state.get("groups") or []:
                    if g["id"] == "prompts_verbilizer":
                        continue
                    if g["id"].startswith("prompts") and not g["titleInDom"]:
                        result["failures"].append(
                            "%s: группа %s не представлена в DOM"
                            % (label, g["id"]))

                # --- реальные пользовательские пути записи ------------------
                state["l1_flow"] = _l1_flow(page, label, store, result)
                state["mode_flow"] = _mode_flow(page, label, store, result)
                state["fallback_flow"] = _fallback_flow(page, label, store,
                                                        result)

                # --- вторая дверь: библиотека промптов модуля Direct -------
                state["library"] = {
                    "direct": _probe_library(
                        page, "direct", "", prefix + "library-%s-direct.png"
                        % label),
                    "synthesizer": _probe_library(
                        page, "direct", "/synthesizer",
                        prefix + "library-%s-direct-synth.png" % label),
                    "verbalizer": _probe_library(
                        page, "direct", "/verbalizer",
                        prefix + "library-%s-direct-verb.png" % label),
                }
                lib_d = state["library"]["direct"].get("promptTree") or []
                if L1_KEY not in lib_d:
                    result["failures"].append(
                        "%s: библиотека direct не содержит %s" % (label, L1_KEY))
                verb = state["library"]["verbalizer"].get("promptTree") or []
                if "prompts.direct_chat_verbalizer_system_prompt" not in verb:
                    result["failures"].append(
                        "%s: библиотека direct/verbalizer не содержит "
                        "ключа Вербализатора" % label)
                result["viewports"][label] = state
                _dump(result, out_name)
                print("[r3] %s: keys=%s missing=%s" % (label, len(keys),
                                                       state.get("missing")))
                ctx.close()

            # -- пустые состояния: честная причина вместо общей лжи ---------
            if not red:
                try:
                    for label2, cfg2, do_search, shot2 in (
                        ("no_prompt_items_320", restricted_payload, False,
                         prefix + "empty-state-320.png"),
                        ("search_no_match_320", payload, True,
                         prefix + "empty-state-search-320.png"),
                    ):
                        ctx = browser.new_context(
                            viewport={"width": 320, "height": 640})
                        ctx.add_init_script(M.TMA_STUB)
                        ctx.route("**/api/**",
                                  lambda r, req=None: _api_handler(r, cfg=cfg2))
                        page = ctx.new_page()
                        page.goto("http://127.0.0.1:%d/web/index.html"
                                  "#/ai/prompts" % PORT, wait_until="load")
                        page.wait_for_timeout(2200)
                        if do_search:
                            page.evaluate(SET_SEARCH % JS_VUE)
                            page.wait_for_timeout(900)
                        res = page.evaluate(EMPTY_PROBE % JS_VUE)
                        page.screenshot(path=os.path.join(HERE, shot2),
                                        full_page=True)
                        result["empty_states"][label2] = {
                            "tab": res["tab"], "search": res["srch"],
                            "itemCount": res["itemCount"],
                            "groups": res["groups"], "screenshot": shot2}
                        if label2 == "no_prompt_items_320":
                            if not res["tab"] or "не загружены" in res["tab"]:
                                result["failures"].append(
                                    "empty-state: причина пустой вкладки "
                                    "нечестная (%r)" % res["tab"])
                        else:
                            if not res["srch"] or "по запросу" not in \
                                    res["srch"]:
                                result["failures"].append(
                                    "empty-state: поисковое пусто нечестное"
                                    " (%r)" % res["srch"])
                        ctx.close()
                except Exception as exc:  # noqa: BLE001
                    result["failures"].append(
                        "empty-states probe crashed: %s" % str(exc)[:200])
            browser.close()
    finally:
        httpd.shutdown()
        _dump(result, out_name)
    _dump(result, out_name)
    _print_summary(result, red)
    if result["failures"]:
        expected_red = red and all("RED подтверждён" in f
                                   or "отсутствует" in f
                                   for f in result["failures"])
        print("FAILURES: %d%s" % (len(result["failures"]),
                                  " (RED reproduced — expected)"
                                  if expected_red else ""))
        for f in result["failures"][:20]:
            print(" -", f)
        if expected_red:
            print("RED RUN: OK (жалобы — ожидаемое отсутствие ключа)")
            return 0
        return 1
    print("MOBILE PROMPTS E2E (_r3_): OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(red="--red" in sys.argv))
