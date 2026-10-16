# -*- coding: utf-8 -*-
"""SOUL-1 / B-MOBILE resume (r2, 2026-10-16): повторный прогон реальной
цепочки «Ещё → ИИ → Промпты» поверх незакоммиченного диффа (каталог +1,
emptyTabReason + честные пустые состояния).

Отличия от первого прогона (mobile_prompts_e2e.py):
- артефакты с префиксом `_r2_` (старые 34 файла не трогаем);
- дамп ключей payload ДО и ПОСЛЕ (`_r2_payload-keys-before/after.json`);
- явная проверка: новый ключ L1 Planner РЕНДЕРИТСЯ на вкладке;
- полное покрытие: каждый `prompts.*` ключ либо generic-карточка, либо
  специальный рендер (mode-табы / fallback-дропдаун) — ничего не скрыто;
- на 320 дополнительно edit→save→reopen для Вербализатора (базовый промпт)
  и для `prompts.verbilizer_mode_casual` (проверка доступности режимов
  Вербализатора под V2 без отдельной карточки группы).
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mobile_prompts_e2e as base  # noqa: E402

M = base.M
PORT = M.PORT + 78

JS_VUE = base.JS_VUE
JS_PROMPT_KEYS = base.JS_PROMPT_KEYS
EMPTY_PROBE = base.EMPTY_PROBE
SET_SEARCH = base.SET_SEARCH
MARKER = base.MARKER
VERB_MARKER = "SOUL1_MARKER_VERBALIZER_BASE"
MODE_MARKER = "SOUL1_MARKER_MODE_CASUAL"
SYNTH_MARKER = "SOUL1_MARKER_SYNTH_BASE"

SPECIAL_RENDER_KEYS = {
    "prompts.verbilizer_default_mode",       # fallback-дропдаун в шапке
    "prompts.verbilizer_mode_casual",        # mode-табы в карточках модулей
    "prompts.verbilizer_mode_serious",
    "prompts.verbilizer_mode_deep_research",
}


def _g_edit_js(key, val):
    return ("""
(() => { const p = %s; if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) { return i.key === %s; });
  if (!it) return { error: 'item missing' };
  it.value = %s;
  return { key: it.key, staged: String(it.value).slice(0, 32),
           canEdit: p.canEditConfig(it.key) };
})()
""" % (JS_VUE, json.dumps(key), json.dumps(val)))


def _g_save_js(key):
    return ("""
(async () => { const p = %s; if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) { return i.key === %s; });
  if (!it) return { error: 'item missing' };
  await p.saveConfigItem(it);
  return { key: it.key, value: String(it.value).slice(0, 32),
           canEdit: p.canEditConfig(it.key) };
})()
""" % (JS_VUE, json.dumps(key)))


def _g_value_js(key):
    return ("""
(() => { const p = %s; if (!p) return { error: 'no vue instance' };
  const it = (p.configItems || []).find(function (i) { return i.key === %s; });
  return { storeValue: it
             ? String(it.value == null ? '' : it.value).slice(0, 48) : null };
})()
""" % (JS_VUE, json.dumps(key)))


def _goto_prompts(page, shot):
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
    return page.evaluate(JS_PROMPT_KEYS % JS_VUE)


def _probe_library(page, slug, stage, shot):
    url = ("http://127.0.0.1:%d/web/index.html#/ai/prompts/%s%s"
           % (PORT, slug, stage))
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1800)
    page.screenshot(path=os.path.join(HERE, shot), full_page=True)
    return page.evaluate(base.JS_LIBRARY % JS_VUE)


def run():
    from playwright.sync_api import sync_playwright

    payload = base.build_payload()
    prompt_keys = sorted(it["key"] for it in payload["items"]
                         if it["key"].startswith("prompts."))
    with open(os.path.join(HERE, "_r2_payload-keys-before.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"meta": {"source": "param_catalog.REGISTRY"},
                   "total_items": len(payload["items"]),
                   "prompt_keys": prompt_keys}, fh,
                  ensure_ascii=False, indent=1)
    print("[r2] payload items=%d prompt_keys=%d"
          % (len(payload["items"]), len(prompt_keys)))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store = base.Store(payload)

    result = {"meta": {"port": PORT,
                       "payload_items": len(payload["items"])},
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

    def check(state, label):
        keys = set(state["configItemsPromptKeys"])
        rendered = set(state["renderedPromptKeys"])
        special_covered = (state.get("modeTabsBlocks", 0) >= 1
                           and state.get("fallbackModeBlock"))
        covered = rendered | (SPECIAL_RENDER_KEYS if special_covered
                              else set())
        missing = {k for k in prompt_keys
                   if k.startswith("prompts.") and k not in covered}
        if missing:
            result["failures"].append(
                "%s: prompt-ключи не видны: %s" % (label, sorted(missing)))
        if "prompts.direct_l1_planner_system_prompt" not in rendered:
            result["failures"].append(
                "%s: L1 Planner не рендерится на вкладке" % label)
        if state.get("bodyOverflowX"):
            result["failures"].append(
                "%s: горизонтальный overflow" % label)

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

                state = _goto_prompts(
                    page, "_r2_chain-%s.png" % label)
                state["screenshot"] = "_r2_chain-%s.png" % label
                state["page_errors"] = [e for e in errs
                                        if "favicon" not in e][:3]
                state["store_writes"] = store.writes

                edit = page.evaluate(
                    base.JS_EDIT % (JS_VUE, json.dumps(MARKER)))
                state["edit"] = edit
                if "error" in edit:
                    result["failures"].append(
                        "%s: L1 Planner недоступен (%s)"
                        % (label, edit["error"]))
                else:
                    saved = page.evaluate(base.JS_SAVE % JS_VUE)
                    state["save"] = saved
                    page.wait_for_timeout(1200)
                    state["after_save"] = page.evaluate(base.JS_VALUE
                                                        % JS_VUE)
                    page.goto(
                        "http://127.0.0.1:%d/web/index.html#/ai/prompts"
                        % PORT, wait_until="load")
                    page.wait_for_timeout(2000)
                    reopened = page.evaluate(JS_PROMPT_KEYS % JS_VUE)
                    state["reopen"] = {
                        "configItemsPromptKeys":
                            reopened["configItemsPromptKeys"],
                        "renderedPromptKeys": reopened["renderedPromptKeys"],
                        "itemCount": reopened["itemCount"],
                        "modeTabsBlocks": reopened["modeTabsBlocks"],
                        "fallbackModeBlock": reopened["fallbackModeBlock"],
                    }
                    state["reopen_value"] = page.evaluate(base.JS_VALUE
                                                          % JS_VUE)
                    if (state.get("reopen_value") or {}).get("storeValue") \
                            != MARKER:
                        result["failures"].append(
                            "%s: L1 значение не пережило reopen" % label)
                    page.screenshot(path=os.path.join(
                        HERE, "_r2_chain-%s-reopen.png" % label),
                        full_page=True)

                # Доп. проверки на 320: Вербализатор (базовый) и режим
                # casual — оба должны редактироваться/сохраняться под V2.
                if label == "320":
                    page.goto("http://127.0.0.1:%d/web/index.html#/ai/prompts"
                              % PORT, wait_until="load")
                    page.wait_for_timeout(1800)
                    state["extra"] = {}
                    for name, key, marker in (
                            ("synthesizer_base",
                             "prompts.direct_chat_synthesizer_system_prompt",
                             SYNTH_MARKER),
                            ("verbalizer_base",
                             "prompts.direct_chat_verbalizer_system_prompt",
                             VERB_MARKER),
                            ("mode_casual", "prompts.verbilizer_mode_casual",
                             MODE_MARKER)):
                        e = page.evaluate(_g_edit_js(key, marker))
                        if "error" in e:
                            result["failures"].append(
                                "320: %s edit error %s" % (name, e))
                            state["extra"][name] = e
                            continue
                        s = page.evaluate(_g_save_js(key))
                        page.wait_for_timeout(1000)
                        v = page.evaluate(_g_value_js(key))
                        state["extra"][name] = {"edit": e, "save": s,
                                                "after_save": v}
                        if v.get("storeValue") != marker:
                            result["failures"].append(
                                "320: %s не сохранился (%r)"
                                % (name, v.get("storeValue")))
                    page.goto("http://127.0.0.1:%d/web/index.html#/ai/prompts"
                              % PORT, wait_until="load")
                    page.wait_for_timeout(2000)
                    for name, key, marker in (
                            ("synthesizer_base",
                             "prompts.direct_chat_synthesizer_system_prompt",
                             SYNTH_MARKER),
                            ("verbalizer_base",
                             "prompts.direct_chat_verbalizer_system_prompt",
                             VERB_MARKER),
                            ("mode_casual", "prompts.verbilizer_mode_casual",
                             MODE_MARKER)):
                        rv = page.evaluate(_g_value_js(key))
                        state["extra"][name]["reopen"] = rv
                        if rv.get("storeValue") != marker:
                            result["failures"].append(
                                "320: %s не пережил reopen (%r)"
                                % (name, rv.get("storeValue")))
                    page.screenshot(path=os.path.join(
                        HERE, "_r2_extra-320.png"), full_page=True)

                state["library"] = {
                    "direct": _probe_library(
                        page, "direct", "", "_r2_library-%s-direct.png"
                        % label),
                    "synthesizer": _probe_library(
                        page, "direct", "/synthesizer",
                        "_r2_library-%s-direct-synth.png" % label),
                    "verbalizer": _probe_library(
                        page, "direct", "/verbalizer",
                        "_r2_library-%s-direct-verb.png" % label),
                }
                check(state, label)
                result["viewports"][label] = state
                ctx.close()

            for label2, cfg2, script, shot2 in (
                ("no_prompt_items_320", restricted_payload, None,
                 "_r2_empty-state-320.png"),
                ("search_no_match_320", payload,
                 "p.configSearch = 'zzzz';", "_r2_empty-state-search-320.png"),
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
                            "empty-state: причина нечестная (%r)" % res["tab"])
                else:
                    if not res["srch"] or "по запросу" not in res["srch"]:
                        result["failures"].append(
                            "empty-state: поисковая причина нечестная (%r)"
                            % res["srch"])
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    with open(os.path.join(HERE, "_r2_payload-keys-after.json"), "w",
              encoding="utf-8") as fh:
        final = store.get()
        fkeys = sorted(it["key"] for it in final["items"]
                       if it["key"].startswith("prompts."))
        edited = {}
        for it in final["items"]:
            if it["key"] in ("prompts.direct_l1_planner_system_prompt",
                             "prompts.direct_chat_synthesizer_system_prompt",
                             "prompts.direct_chat_verbalizer_system_prompt",
                             "prompts.verbilizer_mode_casual"):
                edited[it["key"]] = str(it["value"])[:48]
        json.dump({"prompt_keys": fkeys,
                   "edited_values": edited}, fh,
                  ensure_ascii=False, indent=1)

    with open(os.path.join(HERE, "_r2_result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)

    for label, st in result["viewports"].items():
        print("[r2] %s items=%s rendered=%s modeTabsBlocks=%s "
              "fallbackBlock=%s overflowX=%s"
              % (label, st.get("itemCount"),
                 len(st.get("renderedPromptKeys") or []),
                 st.get("modeTabsBlocks"), st.get("fallbackModeBlock"),
                 st.get("bodyOverflowX")))
        print("      edit=%s save=%s reopen=%s"
              % (st.get("edit"), st.get("save"), st.get("reopen_value")))
        ex = st.get("extra")
        if ex:
            for k, v in ex.items():
                print("      extra/%s reopen=%s" % (k, v.get("reopen")))
        print("      page_errors=%s" % (st.get("page_errors"),))
    for k, v in result["empty_states"].items():
        print("[r2 empty] %s itemCount=%s tab=%r search=%r"
              % (k, v.get("itemCount"), v.get("tab"), v.get("search")))
    if result["failures"]:
        print("FAILURES: %d" % len(result["failures"]))
        for f in result["failures"]:
            print(" -", f)
        return 1
    print("R2 MOBILE PROMPTS E2E: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
