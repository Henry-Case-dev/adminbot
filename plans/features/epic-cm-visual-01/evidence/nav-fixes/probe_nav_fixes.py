"""CMV nav-fixes probe (branch cmv/nav-fixes) — NAV-02/03/04 new behaviour.

Approach of residual-evidence batch 2: real local stand
(`ui_round1025_matrix._start_server` + `ui_evol_w15_composition_e2e`),
real `web/index.html` + `app.js` + `app.css` of THIS branch, random port,
API stubs of epic fixtures. Desktop 1440. Negative controls, clean console,
exactly one vis-network instance per section.

Run:  <python> probe_nav_fixes.py <worktree-repo-root> <out-dir>
"""
import hashlib
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2])
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tests", "fixtures", "cmv"))

import ui_round1025_matrix as M            # noqa: E402
import ui_evol_w15_composition_e2e as W15  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

DESKTOP = (1440, 900)
C = W15.COG_CHAT

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  const net = vm.cognitionNetwork;
  if (typeof net.getScale !== 'function' || net.getScale() <= 0) return false;
  if (vm._cogScene) return vm._cogScene.settled === true;
  return true;
}
"""

JS_NET_COUNTERS = r"""
() => {
  const vm = window.__adminbotVm;
  return {
    visNetworks: document.querySelectorAll('.vis-network').length,
    scenes: document.querySelectorAll('.cognition-graph').length,
    selectedId: vm ? (vm._cogSelectedId || null) : null,
  };
}
"""

JS_SEARCH_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm) return { vm: false };
  const w = document.querySelector('[data-cog-map]');
  const list = w ? w.querySelector('[data-cog-search-list]') : null;
  const items = list
    ? Array.from(list.querySelectorAll('[data-cog-search-item]'))
        .map((b) => ({ id: b.getAttribute('data-cog-search-item'),
                       text: (b.textContent || '').replace(/\s+/g, ' ').trim() }))
    : [];
  const conflict = w ? w.querySelector('[data-cog-search-conflict]') : null;
  const showBtn = w ? w.querySelector('[data-cog-search-show]') : null;
  return {
    vm: true,
    query: vm.graphSearchQuery || '',
    status: vm.graphSearchStatus || '',
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    detail: vm.graphDetail ? { id: vm.graphDetail.id } : null,
    listPresent: !!list,
    items: items,
    conflictPresent: !!conflict,
    conflictText: conflict
      ? (conflict.textContent || '').replace(/\s+/g, ' ').trim() : null,
    showBtnText: showBtn ? (showBtn.textContent || '').trim() : null,
  };
}
"""

JS_FILTER_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm) return { vm: false };
  const view = vm._cogView || { nodes: [], edges: [] };
  return {
    vm: true,
    group: vm.graphFilterGroup,
    cluster: vm.cognitionMapCluster,
    hideDerived: vm.cogHideDerived === true,
    viewNodes: (view.nodes || []).length,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    detail: vm.graphDetail ? { id: vm.graphDetail.id } : null,
    cardOpen: vm.cogCardOpen === true,
  };
}
"""

JS_CAMERA = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  if (!net) return { net: false };
  let vp = null;
  try { vp = net.getViewPosition(); } catch (e) { /* сеть уничтожена */ }
  return {
    net: true,
    scale: +net.getScale().toFixed(5),
    vx: vp ? +vp.x.toFixed(2) : null,
    vy: vp ? +vp.y.toFixed(2) : null,
    netSelected: (typeof net.getSelectedNodes === 'function')
      ? net.getSelectedNodes().map(String) : null,
  };
}
"""

JS_SELECT = r"""
(id) => {
  const vm = window.__adminbotVm;
  if (!vm) return null;
  try { if (vm.cognitionNetwork) vm.cognitionNetwork.selectNodes([id]); }
  catch (e) { /* узел может быть скрыт — выбор всё равно делается ниже */ }
  vm.graphSelectNode(id);
  vm.graphApplySelectionLabels([id]);
  return vm._cogSelectedId || null;
}
"""


def settle(pg, timeout_ms=90000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    pg.wait_for_timeout(400)


def search_ui(pg, query, scope_sel="[data-cog-map]"):
    """Реальный путь: ввод в поле поиска + Enter (keydown.enter)."""
    inp = pg.locator(scope_sel + " .graph-search__input").first
    inp.fill("")
    inp.fill(query)
    pg.wait_for_timeout(200)
    inp.press("Enter")
    pg.wait_for_timeout(900)
    return pg.evaluate(JS_SEARCH_STATE)


# ── фикстуры (batch-2) ──────────────────────────────────────────────────────
def _base_node(nid, kind, title, text, status=None):
    return {
        "id": nid, "kind": kind, "scope": "chat", "chat_id": C,
        "title": title, "text": text, "status": status, "isolated": False,
        "time": {"occurred_at": 1750000000, "observed_at": None,
                 "saved_at": 1750000100, "confirmed_at": None,
                 "updated_at": None},
        "provenance": {"record": "graph_facts", "chat_id": C,
                       "message_id": 555, "origin": "chat_history",
                       "fact_id": 91},
        "metrics": {"importance": 5, "weight": None, "degree": None},
        "refs": {},
    }


def _edge(eid, src, dst):
    return {"id": eid, "from": src, "to": dst, "relation": "обсуждали",
            "derived": False, "chat_id": C, "justification_recorded": True,
            "provenance": {"fact_id": 91}}


def base_payload():
    p = W15.cog_payload()
    p["generated_at"] = int(time.time())
    return p


def rich2_payload():
    """BASE + три одноимённых узла «Дубль показателя» (NAV-02) + entity с
    словом «исключительно» в ПОЛНОМ имени (NAV-03 — вне фильтра «Факты»)."""
    p = W15.cog_payload()
    p["nodes"].append(_base_node("ent:%d:93" % C, "entity",
                                 "Узел с исключительно длинным названием",
                                 "Узел с исключительно длинным названием"))
    p["nodes"].append(_base_node("ent:%d:94" % C, "entity",
                                 "Дубль показателя", "Дубль показателя"))
    p["nodes"].append(_base_node("fact:%d:95" % C, "fact",
                                 "Дубль показателя", "Дубль показателя",
                                 "confirmed"))
    p["nodes"].append(_base_node("obs:%d:96" % C, "observation",
                                 "Дубль показателя", "Дубль показателя"))
    p["edges"].append(_edge("ce93", "ent:%d:2" % C, "ent:%d:93" % C))
    p["edges"].append(_edge("ce94", "ent:%d:1" % C, "ent:%d:94" % C))
    p["edges"].append(_edge("ce95", "ent:%d:2" % C, "fact:%d:95" % C))
    p["edges"].append(_edge("ce96", "ent:%d:3" % C, "obs:%d:96" % C))
    p["generated_at"] = int(time.time())
    return p


# ── runner ──────────────────────────────────────────────────────────────────
class Run:
    def __init__(self):
        self.rows = {}

    def row(self, rid):
        d = os.path.join(OUT, rid)
        os.makedirs(d, exist_ok=True)
        return self.rows.setdefault(rid, {"dir": rid, "shots": [], "facts": {},
                                          "console_errors": [], "errors": []})

    def shot(self, pg, rid, name, selector=None):
        rec = self.row(rid)
        path = os.path.join(OUT, rid, name + ".png")
        try:
            if selector:
                pg.locator(selector).first.screenshot(path=path)
            else:
                pg.screenshot(path=path, full_page=False)
            rec["shots"].append(name + ".png")
            return path
        except Exception as e:  # noqa: BLE001
            rec["errors"].append("shot %s: %s" % (name, str(e)[:120]))
            return None

    def fact(self, rid, key, value):
        self.row(rid)["facts"][key] = value

    def err(self, rid, msg):
        self.row(rid)["errors"].append(str(msg)[:200])

    def attach_console(self, pg, rid):
        rec = self.row(rid)

        def on_console(m):
            if m.type == "error":
                rec["console_errors"].append(m.text[:160])

        def on_pageerror(e):
            rec["console_errors"].append("pageerror: " + str(e)[:160])

        pg.on("console", on_console)
        pg.on("pageerror", on_pageerror)

    def save_manifest(self):
        manifest = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "branch": "cmv/nav-fixes",
                    "rows": {}}
        for rid, rec in self.rows.items():
            files = {}
            d = os.path.join(OUT, rid)
            for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    h = hashlib.sha256(open(fp, "rb").read()).hexdigest()
                    files[fn] = h
            manifest["rows"][rid] = {
                "shots": rec["shots"], "facts": rec["facts"],
                "console_errors": rec["console_errors"],
                "errors": rec["errors"], "sha256": files}
        with open(os.path.join(OUT, "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)


def make_routes(stats):
    base_route = W15._routes(me=None)

    def handler(route):
        base_route(route)

    return handler


def run_nav_02(pg, run):
    """NAV-02: несколько одноимённых — список (имя+тип+ID), БЕЗ автофокуса;
    Enter-цикл и выбор из списка сохранены."""
    rid = "NAV-02"
    run.attach_console(pg, rid)
    settle(pg)
    st1 = search_ui(pg, "Дубль показателя")
    cam1 = pg.evaluate(JS_CAMERA)
    run.fact(rid, "first_enter", {"search": st1, "camera": cam1})
    run.shot(pg, rid, "nav02-list-shown-no-focus-1440",
             selector="[data-cog-map]")
    # выбор пользователя из списка
    pick_id = "fact:%d:95" % C
    pg.click('[data-cog-search-item="%s"]' % pick_id)
    pg.wait_for_timeout(900)
    st2 = pg.evaluate(JS_SEARCH_STATE)
    cam2 = pg.evaluate(JS_CAMERA)
    run.fact(rid, "pick_from_list", {"pickId": pick_id, "search": st2,
                                     "camera": cam2})
    run.shot(pg, rid, "nav02-picked-from-list-1440", selector="[data-cog-map]")
    # цикл Enter детерминированный (тот же запрос)
    seq = []
    for i in range(4):
        st = search_ui(pg, "Дубль показателя")
        seq.append({"step": i + 1, "status": st.get("status"),
                    "selectedId": st.get("selectedId")})
    run.fact(rid, "enter_cycle_after_pick", seq)
    # негатив: по-настоящему уникальный запрос — фокус сразу, списка нет
    st_uniq = search_ui(pg, "сарказм")
    run.fact(rid, "unique_hit_focus_immediately", {
        "status": st_uniq.get("status"), "selectedId": st_uniq.get("selectedId"),
        "listPresent": st_uniq.get("listPresent")})
    pg.locator("[data-cog-map] .graph-search__input").first.fill("")
    pg.wait_for_timeout(400)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def run_nav_03(pg, run):
    """NAV-03: результат вне фильтра — конфликт + «Показать результат»,
    фильтры не меняются; негатив — узел в наборе фильтры не трогает."""
    rid = "NAV-03"
    run.attach_console(pg, rid)
    settle(pg)
    # негатив: узел В наборе при фильтре «Факты»
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0",
                     "fact")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    st_in = search_ui(pg, "утренний кофе")
    f_in = pg.evaluate(JS_FILTER_STATE)
    run.fact(rid, "negative_node_in_view", {"search": st_in, "filter": f_in})
    pg.locator("[data-cog-map] .graph-search__input").first.fill("")
    pg.wait_for_timeout(400)
    # конфликт: entity вне набора фактов
    st_out = search_ui(pg, "исключительно")
    f_out = pg.evaluate(JS_FILTER_STATE)
    run.fact(rid, "conflict_state", {"search": st_out, "filter": f_out})
    run.shot(pg, rid, "nav03-conflict-notice-1440", selector="[data-cog-map]")
    # действие «Показать результат»
    pg.click("[data-cog-search-show]")
    pg.wait_for_timeout(1500)
    st_after = pg.evaluate(JS_SEARCH_STATE)
    f_after = pg.evaluate(JS_FILTER_STATE)
    cam_after = pg.evaluate(JS_CAMERA)
    run.fact(rid, "show_result_action", {"search": st_after, "filter": f_after,
                                         "camera": cam_after})
    run.shot(pg, rid, "nav03-after-show-result-1440", selector="[data-cog-map]")
    # вернуть фильтр в «все типы»
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0", "")
    pg.wait_for_timeout(1500)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def run_nav_04(pg, run):
    """NAV-04: выбор снимается, когда узел вышел из набора; камера не
    сбрасывается; узел в наборе — выбор сохранён."""
    rid = "NAV-04"
    run.attach_console(pg, rid)
    settle(pg)
    # случай A: fact остаётся при фильтре «Факты»
    sel_a = pg.evaluate(JS_SELECT, "fact:%d:11" % C)
    pg.wait_for_timeout(500)
    cam_a0 = pg.evaluate(JS_CAMERA)
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0",
                     "fact")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    f_a = pg.evaluate(JS_FILTER_STATE)
    cam_a1 = pg.evaluate(JS_CAMERA)
    run.fact(rid, "case_a_selection_kept", {
        "selectedBefore": sel_a, "filter": f_a,
        "camBefore": cam_a0, "camAfter": cam_a1})
    run.shot(pg, rid, "nav04-selection-kept-1440", selector="[data-cog-map]")
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0", "")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    # случай B: entity «Аня» уходит при фильтре «Факты» → выбор снят
    sel_b = pg.evaluate(JS_SELECT, "ent:%d:1" % C)
    pg.wait_for_timeout(500)
    cam_b0 = pg.evaluate(JS_CAMERA)
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0",
                     "fact")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    f_b = pg.evaluate(JS_FILTER_STATE)
    cam_b1 = pg.evaluate(JS_CAMERA)
    run.fact(rid, "case_b_selection_cleared", {
        "selectedBefore": sel_b, "filter": f_b,
        "camBefore": cam_b0, "camAfter": cam_b1})
    run.shot(pg, rid, "nav04-selection-cleared-1440", selector="[data-cog-map]")
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0", "")
    pg.wait_for_timeout(1500)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def main():
    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    run = Run()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--enable-gpu", "--enable-gpu-rasterization",
                      "--ignore-gpu-blocklist", "--use-angle=d3d11"])
            try:
                # ═══ S1: RICH2, desktop 1440 (NAV-02 + NAV-03) ═════════════
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", make_routes({"count": 0}))
                pg = ctx.new_page()
                W15.set_cog_payload(rich2_payload())
                pg.goto(base + "#/", wait_until="load")
                run_nav_02(pg, run)
                run_nav_03(pg, run)
                pg.close()
                ctx.close()

                # ═══ S2: BASE, desktop 1440 (NAV-04) ═══════════════════════
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", make_routes({"count": 0}))
                pg = ctx.new_page()
                W15.set_cog_payload(base_payload())
                pg.goto(base + "#/", wait_until="load")
                run_nav_04(pg, run)
                pg.close()
                ctx.close()
            finally:
                browser.close()
    except Exception:
        import traceback
        for rid in ("NAV-02", "NAV-03", "NAV-04"):
            run.err(rid, traceback.format_exc()[-400:])
    run.save_manifest()
    print("PROBE-DONE out=" + OUT)


if __name__ == "__main__":
    main()
