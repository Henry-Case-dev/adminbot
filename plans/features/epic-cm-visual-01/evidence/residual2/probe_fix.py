"""EPIC-CM-VISUAL-01 — residual evidence batch 2, focused re-probe (3 строки).

Допроба к probe.py (артефакты и manifest дополняются, не переписываются):
  1. CMV-LOD1-03 — место для подписей соседей на среднем зуме (аллокатор).
  2. CMV-NAV-06  — Esc закрывает ИНСПЕКТОР первым уровнем (cogCardOpen/лoм).
  3. CMV-ERR-03  — пара одноимённых узлов с id вне диапазона фикстуры 702.
"""
import hashlib
import json
import os
import sys
import time
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
OUT = HERE
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tests", "fixtures", "cmv"))

import ui_round1025_matrix as M            # noqa: E402
import ui_evol_w15_composition_e2e as W15  # noqa: E402
import cog_map_fixtures as FIX             # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

DESKTOP = (1440, 900)

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

JS_SELECT = r"""
(id) => {
  const vm = window.__adminbotVm;
  if (!vm) return null;
  try { if (vm.cognitionNetwork) vm.cognitionNetwork.selectNodes([id]); }
  catch (e) { /* узел может быть скрыт LOD */ }
  vm.graphSelectNode(id);
  vm.graphApplySelectionLabels([id]);
  return vm._cogSelectedId || null;
}
"""

JS_LABELS_FULL = r"""
() => {
  const vm = window.__adminbotVm;
  const s = vm && vm._cogScene;
  const alloc = vm && vm._cogLabels;
  const fmt = (l) => ({ id: String(l.id), text: (l.text || '').slice(0, 40) });
  return {
    lod: s ? s.lod : null,
    allocKeys: alloc ? Object.keys(alloc) : [],
    labels: alloc ? (alloc.labels || []).map(fmt) : [],
    forced: alloc ? (alloc.forced || []).map(fmt) : [],
    hidden: alloc ? (alloc.hidden || []).map(fmt) : [],
    shown: alloc ? alloc.shown : null,
    sceneForcedLabels: s ? (s.forcedLabels || []).map(fmt) : [],
    sceneLabelPlanShown: (s && s.labelPlan) ? s.labelPlan.shown : null,
  };
}
"""

JS_FS_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  const fs = document.querySelector('.status-graph-full');
  const card = document.querySelector('#cog-card');
  const cardVisible = !!card && card.offsetParent !== null
    && getComputedStyle(card).display !== 'none';
  return {
    fullscreen: !!fs,
    cogCardOpen: vm ? vm.cogCardOpen === true : null,
    cardInDom: !!card,
    cardVisible,
    selectedId: vm ? (vm._cogSelectedId || null) : null,
    active: document.activeElement
      ? document.activeElement.tagName + '.'
        + String(document.activeElement.className || '').slice(0, 40) : null,
  };
}
"""

JS_NET_COUNTERS = r"""
() => ({
  visNetworks: document.querySelectorAll('.vis-network').length,
  scenes: document.querySelectorAll('.cognition-graph').length,
})
"""


def settle(pg, timeout_ms=90000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    pg.wait_for_timeout(400)


def zoom_fit(pg, factor):
    pg.evaluate(
        """(f) => {
          const vm = window.__adminbotVm;
          const net = vm && vm.cognitionNetwork;
          if (!net || !vm._cogFitScale) return null;
          net.moveTo({ scale: vm._cogFitScale * f, animation: false });
          return net.getScale();
        }""", factor)
    pg.wait_for_timeout(600)


def wait_lod0(pg, timeout_ms=15000):
    try:
        pg.wait_for_function(
            "() => { const vm = window.__adminbotVm; const s = vm && vm._cogScene;"
            " return !!s && s.lod === 0 && (s.aggregates || []).length > 0; }",
            timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def weird702_fixed():
    """FIX-702 + странности; id вне диапазонов фикстуры (без коллизий)."""
    p = FIX.load(702)
    c = W15.COG_CHAT
    anchor = p["nodes"][0]["id"]
    base = 9200

    def node(nid, kind, title, text, status=None):
        return {
            "id": nid, "kind": kind, "scope": "chat", "chat_id": c,
            "title": title, "text": text, "status": status,
            "isolated": False,
            "time": {"occurred_at": 1750000000, "observed_at": None,
                     "saved_at": 1750000100, "confirmed_at": None,
                     "updated_at": None},
            "provenance": {"record": "graph_facts", "chat_id": c,
                           "message_id": 555, "origin": "chat_history",
                           "fact_id": 91},
            "metrics": {"importance": 5, "weight": None, "degree": None},
            "refs": {},
        }

    p["nodes"].append(node("ent:%d:%d" % (c, base + 1), "entity",
                           "Дубль норм", "Дубль норм"))
    p["nodes"].append(node("fact:%d:%d" % (c, base + 2), "fact",
                           "Дубль норм", "Дубль норм", "confirmed"))
    p["nodes"].append(node("ent:%d:%d" % (c, base + 3), "entity",
                           "Терминатор в системе распределённых вычислений "
                           "— очень длинная русская подпись узла "
                           "когнитивной карты для проверки переноса",
                           "Терминатор"))
    p["nodes"].append(node("ent:%d:%d" % (c, base + 4), "entity",
                           "Quantum Flux Node", "Quantum Flux Node"))
    p["nodes"].append(node("ent:%d:%d" % (c, base + 5), "entity",
                           "🚀 Ракета Эмодзи 🎉", "🚀 Ракета Эмодзи 🎉"))
    p["nodes"].append({
        "id": "ent:%d:%d" % (c, base + 6), "scope": "chat", "chat_id": c,
        "title": "Узел без типа", "text": "Метаданные отсутствуют",
        "isolated": False,
    })
    for i, nid in enumerate(("ent:%d:%d" % (c, base + 1),
                             "fact:%d:%d" % (c, base + 2),
                             "ent:%d:%d" % (c, base + 3),
                             "ent:%d:%d" % (c, base + 4),
                             "ent:%d:%d" % (c, base + 5),
                             "ent:%d:%d" % (c, base + 6))):
        p["edges"].append({"id": "wx%d" % i, "from": anchor, "to": nid,
                           "relation": "обсуждали", "derived": False,
                           "chat_id": c, "justification_recorded": True,
                           "provenance": {"fact_id": 91}})
    p["shown_of"]["nodes"] = len(p["nodes"])
    p["shown_of"]["edges"] = len(p["edges"])
    p["generated_at"] = int(time.time())
    return p


def merge_manifest(row_updates):
    path = os.path.join(OUT, "manifest.json")
    m = json.load(open(path, encoding="utf-8"))
    for rid, upd in row_updates.items():
        rec = m["rows"].setdefault(
            rid, {"shots": [], "facts": {}, "console_errors": [],
                  "errors": [], "sha256": {}})
        rec["shots"] = sorted(set(rec.get("shots", []))
                              | set(upd.get("shots", [])))
        rec["facts"].update(upd.get("facts", {}))
        rec["console_errors"] = (rec.get("console_errors", [])
                                 + upd.get("console_errors", []))
        rec["errors"] = rec.get("errors", []) + upd.get("errors", [])
        d = os.path.join(OUT, rid)
        files = {}
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            fp = os.path.join(d, fn)
            if os.path.isfile(fp):
                files[fn] = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        rec["sha256"] = files
    m["focused_reprobe_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def main():
    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    updates = {}

    def row(rid):
        return updates.setdefault(rid, {"shots": [], "facts": {},
                                        "console_errors": [], "errors": []})

    def shot(pg, rid, name, rec, selector=None):
        path = os.path.join(OUT, rid, name + ".png")
        try:
            if selector:
                pg.locator(selector).first.screenshot(path=path)
            else:
                pg.screenshot(path=path, full_page=False)
            rec["shots"].append(name + ".png")
        except Exception as e:  # noqa: BLE001
            rec["errors"].append("shot %s: %s" % (name, str(e)[:120]))

    def attach(pg, rid, rec):
        def on_console(m):
            if m.type == "error":
                rec["console_errors"].append(m.text[:160])
        pg.on("console", on_console)
        pg.on("pageerror", lambda e: rec["console_errors"].append(
            "pageerror: " + str(e)[:160]))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--enable-gpu", "--enable-gpu-rasterization",
                      "--ignore-gpu-blocklist", "--use-angle=d3d11"])
            try:
                # ── 1: LOD1-03 label space ─────────────────────────────────
                rid = "CMV-LOD1-03"
                rec = row(rid)
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                attach(pg, rid, rec)
                W15.set_cog_payload(W15.cog_payload())
                pg.goto(base + "#/", wait_until="load")
                settle(pg)
                select_id = "ent:%d:1" % W15.COG_CHAT
                neighbor_id = "fact:%d:11" % W15.COG_CHAT
                # средний зум: LOD0 без крайнего отдаления
                zoom_fit(pg, 0.45)
                lod0 = wait_lod0(pg)
                pg.evaluate(JS_SELECT, select_id)
                pg.wait_for_timeout(500)
                pg.focus(".cognition-graph")
                pg.keyboard.press("Enter")
                pg.wait_for_timeout(1500)
                labels = pg.evaluate(JS_LABELS_FULL)
                rec["facts"]["label_space_mid_zoom"] = {
                    "lod0Reached": lod0, "zoomFactor": 0.45, "labels": labels}
                shot(pg, rid, "label-space-mid-zoom-1440", rec,
                     selector="[data-cog-map]")
                pg.close()
                ctx.close()

                # ── 2: NAV-06 Esc уровня инспектора ────────────────────────
                rid = "CMV-NAV-06"
                rec = row(rid)
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                attach(pg, rid, rec)
                W15.set_cog_payload(W15.cog_payload())
                pg.goto(base + "#/", wait_until="load")
                settle(pg)
                pg.click("[data-cog-open-full]")
                pg.wait_for_selector(".status-graph-full", state="visible",
                                     timeout=15000)
                settle(pg, 30000)
                pg.evaluate(JS_SELECT, "ent:%d:2" % W15.COG_CHAT)
                pg.focus(".cognition-graph")
                pg.keyboard.press("Enter")
                pg.wait_for_timeout(900)
                before = pg.evaluate(JS_FS_STATE)
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(900)
                after1 = pg.evaluate(JS_FS_STATE)
                shot(pg, rid, "esc1-inspector-closed-fullscreen-open-1440", rec)
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(1000)
                after2 = pg.evaluate(JS_FS_STATE)
                focus_btn = pg.evaluate(
                    """() => {
                      const el = document.activeElement;
                      const btn = document.querySelector(
                        '[data-cog-map] [data-cog-open-full]');
                      return { isFullBtn: el === btn };
                    }""")
                rec["facts"]["esc_levels_precise"] = {
                    "beforeEsc": before, "afterEsc1": after1,
                    "afterEsc2": after2, "focusAfterClose": focus_btn}
                rec["facts"]["counters_reprobe"] = pg.evaluate(JS_NET_COUNTERS)
                pg.close()
                ctx.close()

                # ── 3: ERR-03 fixed duplicate ids ──────────────────────────
                rid = "CMV-ERR-03"
                rec = row(rid)
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                attach(pg, rid, rec)
                W15.set_cog_payload(weird702_fixed())
                pg.goto(base + "#/", wait_until="load")
                settle(pg)
                c = W15.COG_CHAT
                b = 9200
                ids = ["ent:%d:%d" % (c, b + 1), "fact:%d:%d" % (c, b + 2),
                       "ent:%d:%d" % (c, b + 6)]
                node_info = pg.evaluate(
                    """(ids) => {
                      const vm = window.__adminbotVm;
                      const byId = vm.cognitionGraphData.byId;
                      const out = {};
                      for (const id of ids) {
                        const n = byId[String(id)];
                        out[id] = n ? { id: n.id, title: n.title, kind: n.kind }
                                    : null;
                      }
                      return out;
                    }""", ids)
                rec["facts"]["same_name_pair_fixed_ids"] = node_info
                ds = pg.evaluate(
                    """() => {
                      const vm = window.__adminbotVm;
                      const ds = vm._cognitionNodesDS;
                      const eds = vm._cognitionEdgesDS;
                      return { nodes: ds ? ds.length : null,
                               edges: eds ? eds.length : null };
                    }""")
                rec["facts"]["dataset_fixed"] = ds
                rec["facts"]["client_state_fixed"] = pg.evaluate(
                    "() => { const vm = window.__adminbotVm;"
                    " const st = vm._cogClientState();"
                    " return { state: st.state, degraded: st.degraded }; }")
                shot(pg, rid, "same-name-pair-1440", rec,
                     selector="[data-cog-map]")
                pg.close()
                ctx.close()
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        for rid, rec in updates.items():
            rec["errors"].append("runner: " + traceback.format_exc()[-300:])
    finally:
        merge_manifest(updates)
        server.shutdown()
    print(json.dumps(updates, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
