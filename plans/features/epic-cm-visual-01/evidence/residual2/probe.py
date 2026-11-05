"""EPIC-CM-VISUAL-01 — residual evidence batch 2 (evidence-only, no product changes).

Ветка `cmv/residual-evidence-2` от `df00f178`. Продуктовых правок нет.
Строки пакета (первые 12 из задания, проверяемые UI/пробой):

  CMV-LOD1-03, CMV-LODB-04, CMV-NAV-01, CMV-NAV-02, CMV-NAV-03, CMV-NAV-04,
  CMV-NAV-06, CMV-INT-07, CMV-ERR-02, CMV-ERR-03, CMV-FSM-01, CMV-FSM-02.

Остальные (ANI-01, PHY-03/04, AI-01..04, INV-10, PERF-05/06, VIS-13, GATE-17)
— пакет 3. Метод — как в пакете 1: реальная сборка на локальном стенде
(`ui_round1025_matrix._start_server` + `ui_evol_w15_composition_e2e`),
кадры desktop 1440 / mobile 390, факты из DOM/движка, отрицательные контроли,
консоль без ошибок, ровно один vis-network инстанс на пробу.

Запуск:
  <venv python> plans/features/epic-cm-visual-01/evidence/residual2/probe.py
Выход: plans/features/epic-cm-visual-01/evidence/residual2/<REQ>/… + manifest.json
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

import ui_round1025_matrix as M            # noqa: E402  (os.chdir(REPO) внутри)
import ui_evol_w15_composition_e2e as W15  # noqa: E402
import cog_map_fixtures as FIX             # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

DESKTOP = (1440, 900)
MOBILE = (390, 844)

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

# ── JS-пробы ────────────────────────────────────────────────────────────────
JS_NET_COUNTERS = r"""
() => {
  const vm = window.__adminbotVm;
  return {
    visNetworks: document.querySelectorAll('.vis-network').length,
    scenes: document.querySelectorAll('.cognition-graph').length,
    canvases: document.querySelectorAll('.cognition-graph canvas').length,
    selectedId: vm ? (vm._cogSelectedId || null) : null,
  };
}
"""

JS_SELECT = r"""
(id) => {
  const vm = window.__adminbotVm;
  if (!vm) return null;
  try { if (vm.cognitionNetwork) vm.cognitionNetwork.selectNodes([id]); }
  catch (e) { /* узел может быть скрыт LOD — выбор всё равно делается ниже */ }
  vm.graphSelectNode(id);
  vm.graphApplySelectionLabels([id]);
  return vm._cogSelectedId || null;
}
"""

JS_CLEAR = r"""
() => {
  const vm = window.__adminbotVm;
  if (vm && typeof vm.clearCogSelection === 'function') vm.clearCogSelection();
  return true;
}
"""

JS_SCENE_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  const s = vm && vm._cogScene;
  if (!vm || !s) return { scene: false };
  const view = vm._cogView || { nodes: [], edges: [] };
  const hidden = s.hiddenSet || {};
  const hiddenIds = Object.keys(hidden);
  const labels = vm._cogLabels || {};
  return {
    scene: true,
    lod: (typeof s.lod === 'number') ? s.lod : null,
    aggregates: (s.aggregates || []).length,
    hiddenCount: hiddenIds.length,
    hiddenSample: hiddenIds.slice(0, 8),
    viewNodes: (view.nodes || []).length,
    viewEdges: (view.edges || []).length,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    neighbors: (typeof vm._cogNeighborIds === 'function')
      ? vm._cogNeighborIds().map(String) : [],
    labelsShown: labels.shown,
    labelIds: (labels.labels || []).map((l) => String(l.id)),
    forcedIds: (labels.forced || []).map((l) => String(l.id)),
    zoomMode: vm._graphZoomMode || null,
    fx: (s.fx && typeof s.fx.counters === 'function') ? s.fx.counters() : null,
  };
}
"""

JS_HIDDEN_HAS = r"""
(ids) => {
  const vm = window.__adminbotVm;
  const s = vm && vm._cogScene;
  const hidden = (s && s.hiddenSet) || {};
  const out = {};
  for (const id of ids) out[String(id)] = !!hidden[String(id)];
  return out;
}
"""

JS_DS_FACTS = r"""
() => {
  const vm = window.__adminbotVm;
  const ds = vm && vm._cognitionNodesDS;
  const eds = vm && vm._cognitionEdgesDS;
  const net = vm && vm.cognitionNetwork;
  const model = (vm && vm.cognitionGraphData) || {};
  const out = { hasNet: !!net };
  if (ds) {
    const rows = ds.get({ fields: ['id'] });
    out.dsCount = rows.length;
    out.clusterPrefixed = rows.filter(
      (r) => String(r.id).indexOf('cluster:') === 0).length;
    out.dsSample = rows.slice(0, 3).map((r) => String(r.id));
  }
  if (eds) out.edgeDsCount = eds.length;
  if (net && typeof net.getBody === 'function') {
    try {
      const body = net.getBody();
      out.bodyNodes = body.nodes.length;
      out.bodyEdges = body.edges.length;
    } catch (e) { /* сеть уничтожена */ }
  }
  out.modelNodes = (model.nodes || []).length;
  out.byIdCount = Object.keys(model.byId || {}).length;
  out.viewNodes = (vm && vm._cogView) ? vm._cogView.nodes.length : null;
  return out;
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
    fitScale: (typeof vm._cogFitScale === 'number')
      ? +vm._cogFitScale.toFixed(5) : null,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    netSelected: (typeof net.getSelectedNodes === 'function')
      ? net.getSelectedNodes().map(String) : null,
    visNetworks: document.querySelectorAll('.vis-network').length,
  };
}
"""

JS_SEARCH_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm) return { vm: false };
  return {
    vm: true,
    query: vm.graphSearchQuery || '',
    status: vm.graphSearchStatus || '',
    matchIds: (vm._graphSearchMatchIds || []).map(String),
    idx: vm._graphSearchIdx,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    detail: vm.graphDetail
      ? { id: vm.graphDetail.id, kind: vm.graphDetail.kind,
          kindLabel: vm.graphDetail.kindLabel } : null,
    aliasesMap: (typeof vm.summaryAliasesMap === 'function')
      ? vm.summaryAliasesMap() : null,
  };
}
"""

JS_SET_QUERY = r"""
(q) => {
  const vm = window.__adminbotVm;
  if (!vm) return null;
  vm.graphSearchQuery = q;
  return vm.graphSearchQuery;
}
"""

JS_NODE_INFO = r"""
(id) => {
  const vm = window.__adminbotVm;
  const model = (vm && vm.cognitionGraphData) || {};
  const n = model.byId ? model.byId[String(id)] : null;
  if (!n) return null;
  return { id: n.id, title: n.title, kind: n.kind,
           search: (n.search || '').slice(0, 80), aliases: n.aliases };
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
    viewEdges: (view.edges || []).length,
    detail: vm.graphDetail ? { id: vm.graphDetail.id } : null,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    cardOpen: vm.cogCardOpen === true,
  };
}
"""

JS_CLIENT_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || typeof vm._cogClientState !== 'function') return null;
  const st = vm._cogClientState();
  return { state: st.state, degraded: st.degraded, empty: st.empty,
           stale: st.stale, noticeKind: st.notice ? st.notice.kind : null };
}
"""

JS_KB_ACTIVE = r"""
() => {
  const el = document.activeElement;
  if (!el) return null;
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    tag: el.tagName,
    cls: String(el.className || '').slice(0, 70),
    text: (el.textContent || el.value || '').replace(/\s+/g, ' ').trim().slice(0, 24),
    outline: cs.outlineStyle + ' ' + cs.outlineWidth + ' ' + cs.outlineColor,
    boxShadow: (cs.boxShadow && cs.boxShadow !== 'none')
      ? cs.boxShadow.slice(0, 90) : '',
    borderColor: cs.borderTopColor,
    rect: { x: +r.x.toFixed(1), y: +r.y.toFixed(1),
            w: +r.width.toFixed(1), h: +r.height.toFixed(1) },
  };
}
"""

JS_FS_GEO = r"""
() => {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: +r.x.toFixed(1), y: +r.y.toFixed(1),
             w: +r.width.toFixed(1), h: +r.height.toFixed(1),
             right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1) };
  };
  const fs = document.querySelector('.status-graph-full');
  const de = document.scrollingElement || document.documentElement;
  const dvhProbe = document.createElement('div');
  dvhProbe.style.cssText =
    'position:absolute;left:-9999px;height:100dvh;visibility:hidden;';
  document.body.appendChild(dvhProbe);
  const dvhPx = dvhProbe.getBoundingClientRect().height;
  dvhProbe.remove();
  const safeProbe = document.createElement('div');
  safeProbe.style.cssText = 'position:absolute;left:-9999px;visibility:hidden;'
    + 'padding-top:env(safe-area-inset-top,0px);'
    + 'padding-bottom:env(safe-area-inset-bottom,0px);';
  document.body.appendChild(safeProbe);
  const csSafe = getComputedStyle(safeProbe);
  const safeEnv = { top: csSafe.paddingTop, bottom: csSafe.paddingBottom };
  safeProbe.remove();
  if (!fs) {
    return { present: false, innerW: window.innerWidth,
             innerH: window.innerHeight, dvhPx: +dvhPx.toFixed(1) };
  }
  const q = (sel) => fs.querySelector(sel);
  const controls = [];
  const push = (el, name) => {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    controls.push({
      name,
      x: +r.x.toFixed(1), y: +r.y.toFixed(1),
      w: +r.width.toFixed(1), h: +r.height.toFixed(1),
      min: +Math.min(r.width, r.height).toFixed(1),
      inVp: r.x >= -1 && r.y >= -1
        && r.right <= window.innerWidth + 1
        && r.bottom <= window.innerHeight + 1,
      clipped: el.scrollWidth > el.clientWidth + 2,
      minHeightCss: cs.minHeight,
    });
  };
  push(q('.graph-search__input'), 'search-input');
  Array.from(fs.querySelectorAll('.graph-search .btn-ghost')).forEach((b) => {
    push(b, 'btn:' + (b.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 14));
  });
  Array.from(fs.querySelectorAll('.graph-search select.field')).forEach((s, i) => {
    const opt = (s.options && s.selectedIndex >= 0)
      ? s.options[s.selectedIndex].textContent.trim().slice(0, 14) : '';
    push(s, 'select' + i + ':' + opt);
  });
  push(q('.cog-fs__close'), 'close');
  const ctr = q('[data-cog-counters]');
  const state = q('.cog-state');
  return {
    present: true,
    fsRect: rect(fs),
    innerW: window.innerWidth, innerH: window.innerHeight,
    dvhPx: +dvhPx.toFixed(1),
    pageScrollHeight: de.scrollHeight, pageClientHeight: de.clientHeight,
    pageScrolls: de.scrollHeight > de.clientHeight + 1,
    pad: {
      t: getComputedStyle(fs).paddingTop,
      b: getComputedStyle(fs).paddingBottom,
      l: getComputedStyle(fs).paddingLeft,
      r: getComputedStyle(fs).paddingRight,
    },
    safeEnv,
    sceneRect: rect(q('.cognition-graph')),
    sheetRect: rect(document.querySelector('#cog-card')),
    countersText: ctr ? ctr.textContent.replace(/\s+/g, ' ').trim() : null,
    stateText: state ? state.textContent.replace(/\s+/g, ' ').trim() : null,
    controls,
  };
}
"""


# ── фикстуры ────────────────────────────────────────────────────────────────
def _base_node(c, nid, kind, title, text, status=None):
    prov = {"record": "graph_facts", "chat_id": c, "message_id": 555,
            "origin": "chat_history", "fact_id": 91}
    return {
        "id": nid, "kind": kind, "scope": "chat", "chat_id": c,
        "title": title, "text": text, "status": status,
        "isolated": False,
        "time": {"occurred_at": 1750000000, "observed_at": None,
                 "saved_at": 1750000100, "confirmed_at": None,
                 "updated_at": None},
        "provenance": dict(prov),
        "metrics": {"importance": 5, "weight": None, "degree": None},
        "refs": {},
    }


def _edge(c, eid, src, dst):
    return {"id": eid, "from": src, "to": dst, "relation": "обсуждали",
            "derived": False, "chat_id": c, "justification_recorded": True,
            "provenance": {"fact_id": 91}}


def base_payload():
    p = W15.cog_payload()
    p["generated_at"] = int(time.time())
    return p


def rich2_payload():
    """BASE + длинный текст/без заголовка/длинное название (как в пакете 1)
    + три одноимённых узла «Дубль показателя» разных типов (NAV-02)."""
    p = W15.cog_payload()
    c = W15.COG_CHAT
    long_text = ("Наблюдение зафиксировано в чате: существо без имени появлялось "
                 "неоднократно, реакции противоречивые, источник сообщения не "
                 "указан. ") * 18
    p["nodes"].append(_base_node(c, "fact:%d:91" % c, "fact",
                                 "nameless creature", long_text, "confirmed"))
    untitled = _base_node(c, "ent:%d:92" % c, "entity", "", None)
    untitled["isolated"] = True
    p["nodes"].append(untitled)
    long_title = ("Узел с исключительно длинным названием, которое заведомо не "
                  "помещается в одну строку подписи на канве и должно "
                  "сокращаться с многоточием при отрисовке")
    p["nodes"].append(_base_node(c, "ent:%d:93" % c, "entity", long_title,
                                 long_title))
    p["nodes"].append(_base_node(c, "ent:%d:94" % c, "entity",
                                 "Дубль показателя", "Дубль показателя"))
    p["nodes"].append(_base_node(c, "fact:%d:95" % c, "fact",
                                 "Дубль показателя", "Дубль показателя",
                                 "confirmed"))
    p["nodes"].append(_base_node(c, "obs:%d:96" % c, "observation",
                                 "Дубль показателя", "Дубль показателя"))
    p["edges"].append(_edge(c, "ce91", "ent:%d:1" % c, "fact:%d:91" % c))
    p["edges"].append(_edge(c, "ce93", "ent:%d:2" % c, "ent:%d:93" % c))
    p["edges"].append(_edge(c, "ce94", "ent:%d:1" % c, "ent:%d:94" % c))
    p["edges"].append(_edge(c, "ce95", "ent:%d:2" % c, "fact:%d:95" % c))
    p["edges"].append(_edge(c, "ce96", "ent:%d:3" % c, "obs:%d:96" % c))
    p["generated_at"] = int(time.time())
    return p


def single_payload():
    """ERR-02: ровно один узел, без рёбер."""
    p = W15.cog_payload(with_nodes=False)
    c = W15.COG_CHAT
    p["nodes"] = [_base_node(c, "ent:%d:1" % c, "entity", "Одинокий узел",
                             "Одинокий узел")]
    p["edges"] = []
    p["shown_of"]["nodes"] = 1
    p["shown_of"]["edges"] = 0
    p["shown_of"]["totals"] = {"nodes": 1, "edges": 0, "unresolved_refs": 0}
    p["truncated"] = {"nodes": False, "edges": False, "by_class": {}}
    p["generated_at"] = int(time.time())
    return p


def plus_payload():
    """LODB-04: BASE + один новый узел и ребро к существующему ent:1."""
    p = base_payload()
    c = W15.COG_CHAT
    p["nodes"].append(_base_node(c, "ent:%d:97" % c, "entity",
                                 "Новый узел обновления",
                                 "Новый узел обновления"))
    p["edges"].append(_edge(c, "ce97", "ent:%d:1" % c, "ent:%d:97" % c))
    p["shown_of"]["nodes"] = len(p["nodes"])
    p["shown_of"]["edges"] = len(p["edges"])
    return p


def weird702_payload():
    """ERR-03: FIX-702 + одинаковые имена, длинная русская подпись, латиница,
    эмодзи, узел без типа и без метаданных."""
    p = FIX.load(702)
    c = W15.COG_CHAT
    anchor = p["nodes"][0]["id"]
    p["nodes"].append(_base_node(c, "ent:%d:201" % c, "entity",
                                 "Дубль норм", "Дубль норм"))
    p["nodes"].append(_base_node(c, "fact:%d:202" % c, "fact",
                                 "Дубль норм", "Дубль норм", "confirmed"))
    p["nodes"].append(_base_node(c, "ent:%d:203" % c, "entity",
                                 "Терминатор в системе распределённых вычислений "
                                 "— очень длинная русская подпись узла "
                                 "когнитивной карты для проверки переноса",
                                 "Терминатор"))
    p["nodes"].append(_base_node(c, "ent:%d:204" % c, "entity",
                                 "Quantum Flux Node", "Quantum Flux Node"))
    p["nodes"].append(_base_node(c, "ent:%d:205" % c, "entity",
                                 "🚀 Ракета Эмодзи 🎉", "🚀 Ракета Эмодзи 🎉"))
    raw = {
        "id": "ent:%d:206" % c, "scope": "chat", "chat_id": c,
        "title": "Узел без типа", "text": "Метаданные отсутствуют",
        "isolated": False,
    }
    p["nodes"].append(raw)
    for i, nid in enumerate(("ent:%d:201" % c, "fact:%d:202" % c,
                             "ent:%d:203" % c, "ent:%d:204" % c,
                             "ent:%d:205" % c, "ent:%d:206" % c)):
        p["edges"].append(_edge(c, "wx%d" % i, anchor, nid))
    p["shown_of"]["nodes"] = len(p["nodes"])
    p["shown_of"]["edges"] = len(p["edges"])
    p["generated_at"] = int(time.time())
    return p


def fx702_payload():
    p = FIX.load(702)
    p["generated_at"] = int(time.time())
    return p


# ── маршруты: счётчик запросов + инъекция алиасов в /api/config ─────────────
def make_routes(stats, me=None):
    """Обёртка над W15._routes(): считает запросы (NAV-01: поиск локален)
    и добавляет в /api/config реальный параметр limits.summary_aliases
    (NAV-01: поиск по алиасу). Формат item повторяет _config_stub()."""
    base_route = W15._routes(me=me)
    aliases_value = {"Костя": "Тень"}

    def _injected_config():
        try:
            data = json.loads(json.dumps(M.CONFIG_STUB))
        except Exception:  # noqa: BLE001
            data = {"items": [], "groups": []}
        items = [it for it in data.get("items", [])
                 if it.get("key") != "limits.summary_aliases"]
        items.append({
            "key": "limits.summary_aliases", "value": dict(aliases_value),
            "category": "limits", "secret": False, "chat_source": "",
            "global_value": None, "title": "Алиасы выжимки", "type": "dict",
            "updated_at": None, "group": "", "description": "",
            "widget": "keyvalue", "select_options": None,
            "select_labels": None, "per_chat": False,
            "progressive_level": "basic", "stage": None, "view_roles": [],
            "edit_roles": [], "chat_updated_at": None,
        })
        data["items"] = items
        return data

    def handler(route):
        url = route.request.url.split("?")[0]
        stats["count"] += 1
        stats["last"] = url[-70:]
        if url.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_injected_config()))
            return
        base_route(route)

    return handler


# ── runner ──────────────────────────────────────────────────────────────────
class Run:
    def __init__(self):
        self.rows = {}

    def row(self, rid):
        d = os.path.join(OUT, rid)
        os.makedirs(d, exist_ok=True)
        self.rows.setdefault(rid, {"dir": rid, "shots": [], "facts": {},
                                   "console_errors": [], "errors": []})
        return self.rows[rid]

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
                    "branch": "cmv/residual-evidence-2",
                    "base_commit": "df00f178",
                    "batch": 2,
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
        with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)


def settle(pg, timeout_ms=90000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    pg.wait_for_timeout(400)


def wait_lod0(pg, timeout_ms=15000):
    """Ждать фактического LOD0 (зум наружу → резолв по кадру)."""
    try:
        pg.wait_for_function(
            "() => { const vm = window.__adminbotVm; const s = vm && vm._cogScene;"
            " return !!s && s.lod === 0 && (s.aggregates || []).length > 0; }",
            timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def zoom_fit(pg, factor=0.25):
    pg.evaluate(
        """(f) => {
          const vm = window.__adminbotVm;
          const net = vm && vm.cognitionNetwork;
          if (!net || !vm._cogFitScale) return null;
          net.moveTo({ scale: vm._cogFitScale * f, animation: false });
          return net.getScale();
        }""", factor)
    pg.wait_for_timeout(600)


def open_fullscreen(pg):
    pg.click("[data-cog-open-full]")
    pg.wait_for_selector(".status-graph-full", state="visible", timeout=15000)
    settle(pg, 30000)


def close_fullscreen(pg):
    """Esc закрывает РОВНО один уровень: сперва инспектор, затем fullscreen."""
    for _ in range(4):
        vis = False
        try:
            loc = pg.locator(".status-graph-full")
            vis = loc.count() > 0 and loc.first.is_visible()
        except Exception:  # noqa: BLE001
            vis = False
        if not vis:
            break
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(700)
    pg.wait_for_timeout(300)


def select(pg, node_id):
    """Выбор узла + Enter на сцене: карточку открывает РЕАЛЬНЫЙ путь §9."""
    sel = pg.evaluate(JS_SELECT, node_id)
    try:
        pg.focus(".cognition-graph")
        pg.keyboard.press("Enter")
    except Exception:  # noqa: BLE001
        return sel
    pg.wait_for_timeout(600)
    return sel


def search_ui(pg, rid, query, scope_sel="[data-cog-map]"):
    """Реальный путь: ввод в поле поиска + Enter (keydown.enter)."""
    inp = pg.locator(scope_sel + " .graph-search__input").first
    inp.fill("")
    inp.fill(query)
    pg.wait_for_timeout(200)
    inp.press("Enter")
    pg.wait_for_timeout(900)
    st = pg.evaluate(JS_SEARCH_STATE)
    return st


def run_lod1_03(pg, run):
    """CMV-LOD1-03: соседи выбранного видны независимо от LOD-свёртки,
    подписям соседей отводится место (forced). Негатив: посторонние узлы
    при этом скрыты (проверка различает состояния)."""
    c = W15.COG_CHAT
    rid = "CMV-LOD1-03"
    run.attach_console(pg, rid)
    settle(pg)
    # Шаг A: LOD0 без выбора — соседи не «закреплены»
    zoom_fit(pg, 0.25)
    lod0_before = wait_lod0(pg)
    st_a = pg.evaluate(JS_SCENE_STATE)
    hidden_before = pg.evaluate(JS_HIDDEN_HAS, ["ent:%d:2" % c, "fact:%d:11" % c])
    run.fact(rid, "lod0_before_selection", {
        "lod0Reached": lod0_before, "state": st_a,
        "neighborsHiddenBefore": hidden_before})
    run.shot(pg, rid, "lod0-no-selection-1440", selector="[data-cog-map]")
    # Шаг B: выбор ent:1 → соседи (ent:2, fact:11, fact:12 через ent:2?) —
    # adjacency ent:1 = fact:11, ent:94 (в RICH), ent:97…; здесь BASE:
    # соседи ent:1 = fact:11 (+ всё, что связано).
    sel = select(pg, "ent:%d:1" % c)
    pg.wait_for_timeout(900)
    st_b = pg.evaluate(JS_SCENE_STATE)
    hidden_after = pg.evaluate(JS_HIDDEN_HAS, ["ent:%d:2" % c, "fact:%d:11" % c])
    run.fact(rid, "selection", {"selectedId": sel})
    run.fact(rid, "lod0_with_selection", {
        "state": st_b, "neighborsHiddenAfter": hidden_after})
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, rid, "lod0-selected-neighbors-1440", selector="[data-cog-map]")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)
    zoom_fit(pg, 1.0)
    pg.wait_for_timeout(600)


def run_int_07(pg, run):
    """CMV-INT-07: без нативной vis-кластеризации — DataSet держит все
    исходные id (нет 'cluster:'), данные не режутся; агрегаты L0 — визуальный
    LOD (fx-слой). Негатив: агрегаты > 0 — состояние, где кластеры были бы."""
    rid = "CMV-INT-07"
    run.attach_console(pg, rid)
    settle(pg)
    ds_full = pg.evaluate(JS_DS_FACTS)
    run.fact(rid, "dataset_full_view", ds_full)
    zoom_fit(pg, 0.22)
    lod0 = wait_lod0(pg)
    ds_lod0 = pg.evaluate(JS_DS_FACTS)
    st = pg.evaluate(JS_SCENE_STATE)
    run.fact(rid, "lod0_reached", lod0)
    run.fact(rid, "dataset_lod0", ds_lod0)
    run.fact(rid, "scene_lod0", {k: st[k] for k in
                                 ("lod", "aggregates", "hiddenCount",
                                  "viewNodes", "viewEdges")})
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, rid, "aggregates-visual-lod-1440", selector="[data-cog-map]")
    zoom_fit(pg, 1.0)
    pg.wait_for_timeout(600)


def run_lodb_04(pg, run, stats):
    """CMV-LODB-04: обновление данных — камера и выбор сохраняются по ID,
    пользователь не улетает в центр; экземпляр сети тот же."""
    c = W15.COG_CHAT
    rid = "CMV-LODB-04"
    run.attach_console(pg, rid)
    settle(pg)
    select(pg, "ent:%d:1" % c)
    pg.wait_for_timeout(500)
    # ручной жест: зум + панорама (НЕ fit)
    pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      net.moveTo({ scale: 1.15, animation: false });
    }""")
    pg.wait_for_timeout(400)
    cam_before = pg.evaluate(JS_CAMERA)
    run.fact(rid, "camera_before_update", cam_before)
    run.fact(rid, "counters_before", pg.evaluate(JS_NET_COUNTERS))
    # обновление данных: новый payload + реальная перезагрузка карты
    stats["count"] = 0
    W15.set_cog_payload(plus_payload())
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    pg.wait_for_timeout(2500)
    settle(pg, 30000)
    cam_after = pg.evaluate(JS_CAMERA)
    ds = pg.evaluate(JS_DS_FACTS)
    new_node = pg.evaluate(JS_NODE_INFO, "ent:%d:97" % c)
    run.fact(rid, "api_calls_during_refresh", stats["count"])
    run.fact(rid, "camera_after_update", cam_after)
    run.fact(rid, "dataset_after", ds)
    run.fact(rid, "new_node_present", new_node)
    run.fact(rid, "counters_after", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, rid, "after-data-update-1440", selector="[data-cog-map]")


def run_nav_04(pg, run):
    """CMV-NAV-04: смена фильтра не сбрасывает камеру; выбор снимается,
    только если элемент вышел из набора. Негатив: элемент в наборе —
    выбор остаётся."""
    c = W15.COG_CHAT
    rid = "CMV-NAV-04"
    run.attach_console(pg, rid)
    # случай A: выбор ВХОДИТ в новый набор → выбор остаётся
    sel_a = select(pg, "fact:%d:11" % c)   # fact — останется при фильтре fact
    pg.wait_for_timeout(500)
    cam_a0 = pg.evaluate(JS_CAMERA)
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0",
                     "fact")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    f_a = pg.evaluate(JS_FILTER_STATE)
    cam_a1 = pg.evaluate(JS_CAMERA)
    run.fact(rid, "case_a_selection_kept", {
        "selectedId": sel_a, "filterState": f_a,
        "camBefore": cam_a0, "camAfter": cam_a1})
    run.shot(pg, rid, "filter-fact-selection-kept-1440", selector="[data-cog-map]")
    # случай B: выбор ВЫХОДИТ из набора → снят, камера не прыгает
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0", "")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    sel_b = select(pg, "ent:%d:1" % c)     # entity — уйдёт при фильтре fact
    pg.wait_for_timeout(500)
    cam_b0 = pg.evaluate(JS_CAMERA)
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0",
                     "fact")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    f_b = pg.evaluate(JS_FILTER_STATE)
    cam_b1 = pg.evaluate(JS_CAMERA)
    run.fact(rid, "case_b_selection_cleared", {
        "selectedId": sel_b, "filterState": f_b,
        "camBefore": cam_b0, "camAfter": cam_b1})
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, rid, "filter-fact-selection-cleared-1440",
             selector="[data-cog-map]")
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0", "")
    pg.wait_for_timeout(1500)


def run_nav_06(pg, run):
    """CMV-NAV-06: Enter запускает поиск; Esc закрывает по уровням
    (инспектор → fullscreen); Tab проходит контролы с видимым фокусом;
    после закрытия fullscreen фокус на кнопке открытия."""
    c = W15.COG_CHAT
    rid = "CMV-NAV-06"
    run.attach_console(pg, rid)
    settle(pg)
    # Tab: от поля поиска вперёд по контролам
    pg.focus("[data-cog-map] .graph-search__input")
    pg.wait_for_timeout(200)
    seq = [pg.evaluate(JS_KB_ACTIVE)]
    for _ in range(3):
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(250)
        seq.append(pg.evaluate(JS_KB_ACTIVE))
    run.fact(rid, "tab_sequence", seq)
    run.shot(pg, rid, "tab-focus-visible-1440")
    # Enter запускает поиск (негатив-контроль «ничего не найдено» отдельно)
    st_found = search_ui(pg, rid, "Дача")
    run.fact(rid, "enter_search_found", st_found)
    run.shot(pg, rid, "enter-search-result-1440", selector="[data-cog-map]")
    st_none = search_ui(pg, rid, "запросбезрезультатов")
    run.fact(rid, "enter_search_negative", {
        "status": st_none.get("status"), "matchIds": st_none.get("matchIds")})
    pg.locator("[data-cog-map] .graph-search__input").first.fill("")
    pg.wait_for_timeout(400)
    # Esc по уровням: fullscreen + инспектор
    open_fullscreen(pg)
    sel = select(pg, "ent:%d:2" % c)
    pg.wait_for_timeout(700)
    fs_open1 = pg.evaluate(
        "() => !!document.querySelector('.status-graph-full')")
    card_open1 = pg.evaluate(
        "() => { const vm = window.__adminbotVm; return !!vm._cogSelectedId; }")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(800)
    sel_after1 = pg.evaluate(
        "() => window.__adminbotVm._cogSelectedId")
    fs_after1 = pg.evaluate(
        "() => !!document.querySelector('.status-graph-full')")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(900)
    fs_after2 = pg.evaluate(
        "() => !!document.querySelector('.status-graph-full')")
    focus_now = pg.evaluate(
        """() => {
          const el = document.activeElement;
          const btn = document.querySelector('[data-cog-map] [data-cog-open-full]');
          return { active: el ? el.tagName + '.' + String(el.className).slice(0, 40) : null,
                   isFullBtn: el === btn,
                   btnExists: !!btn };
        }""")
    run.fact(rid, "esc_layers", {
        "selectedBefore": sel, "fullscreenBefore": fs_open1,
        "selectionBeforeEsc": card_open1,
        "afterEsc1": {"selection": sel_after1, "fullscreen": fs_after1},
        "afterEsc2": {"fullscreen": fs_after2},
        "focusAfterClose": focus_now})
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, rid, "focus-returned-after-fullscreen-1440")
    # негатив: без открытых слоёв Esc ничего не закрывает (маршрут не меняется)
    route_before = pg.evaluate("() => window.__adminbotVm.route")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(600)
    route_after = pg.evaluate("() => window.__adminbotVm.route")
    run.fact(rid, "esc_negative_no_layers", {
        "routeBefore": route_before, "routeAfter": route_after})


def run_nav_01(pg, run, stats):
    """CMV-NAV-01: поиск по алиасу и по ПОЛНОМУ имени (не по короткой
    видимой подписи); без новых API-запросов на сам поиск."""
    rid = "CMV-NAV-01"
    run.attach_console(pg, rid)
    settle(pg)
    alias_map = pg.evaluate(JS_SEARCH_STATE)
    run.fact(rid, "aliases_map", alias_map.get("aliasesMap"))
    node_alias = pg.evaluate(JS_NODE_INFO, "ent:%d:2" % W15.COG_CHAT)
    run.fact(rid, "node_search_blob", node_alias)
    stats["count"] = 0
    st_alias = search_ui(pg, rid, "Тень")
    run.fact(rid, "search_by_alias", st_alias)
    run.fact(rid, "api_calls_during_alias_search", stats["count"])
    run.shot(pg, rid, "search-by-alias-1440", selector="[data-cog-map]")
    # поиск по полному имени за пределами усечённой подписи
    st_full = search_ui(pg, rid, "заведомо")
    run.fact(rid, "search_beyond_truncated_label", st_full)
    run.shot(pg, rid, "search-full-name-beyond-label-1440",
             selector="[data-cog-map]")
    # негатив: бессмысленный запрос
    st_none = search_ui(pg, rid, "qqqqzzzz")
    run.fact(rid, "negative_no_match", {
        "status": st_none.get("status"), "matchIds": st_none.get("matchIds")})
    pg.locator("[data-cog-map] .graph-search__input").first.fill("")
    pg.wait_for_timeout(400)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def run_nav_02(pg, run):
    """CMV-NAV-02: несколько одноимённых совпадений — различимые результаты,
    фокус не ставится на случайный объект без выбора пользователя."""
    rid = "CMV-NAV-02"
    run.attach_console(pg, rid)
    settle(pg)
    states = []
    for i in range(3):
        st = search_ui(pg, rid, "Дубль показателя")
        states.append({
            "step": i + 1, "status": st.get("status"),
            "matchIds": st.get("matchIds"), "idx": st.get("idx"),
            "selectedId": st.get("selectedId"),
            "detail": st.get("detail")})
        run.shot(pg, rid, "dup-hits-step%d-1440" % (i + 1),
                 selector="[data-cog-map]")
    run.fact(rid, "duplicate_hits_cycle", states)
    # негатив: уникальный запрос без счётчика (1/1 не показывается)
    st_uniq = search_ui(pg, rid, "Дача")
    run.fact(rid, "unique_hit_no_counter", {
        "status": st_uniq.get("status"), "matchIds": st_uniq.get("matchIds")})
    pg.locator("[data-cog-map] .graph-search__input").first.fill("")
    pg.wait_for_timeout(400)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def run_nav_03_conflict(pg, run):
    """CMV-NAV-03 (часть 2, фильтр): узел исключён пользовательским фильтром.
    Требование: честный конфликт + действие «Показать результат», снимающее
    только нужное ограничение. Фиксируется фактическое поведение."""
    c = W15.COG_CHAT
    rid = "CMV-NAV-03"
    run.attach_console(pg, rid)
    settle(pg)
    # негатив-контроль: узел В наборе — фильтр не трогается
    st_in = search_ui(pg, rid, "утренний кофе")
    f_in = pg.evaluate(JS_FILTER_STATE)
    run.fact(rid, "negative_node_in_view", {
        "status": st_in.get("status"), "filterAfter": {
            k: f_in[k] for k in ("group", "cluster", "hideDerived")}})
    pg.locator("[data-cog-map] .graph-search__input").first.fill("")
    pg.wait_for_timeout(400)
    # узел ВНЕ набора: фильтр fact, ищем entity по слову из полного имени
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0",
                     "fact")
    pg.wait_for_timeout(2000)
    settle(pg, 30000)
    f_before = pg.evaluate(JS_FILTER_STATE)
    st_out = search_ui(pg, rid, "исключительно")
    pg.wait_for_timeout(600)
    f_after = pg.evaluate(JS_FILTER_STATE)
    run.fact(rid, "filtered_out_search", {
        "filterBefore": {k: f_before[k] for k in ("group", "viewNodes")},
        "searchState": st_out,
        "filterAfter": {k: f_after[k] for k in
                        ("group", "cluster", "hideDerived", "viewNodes")}})
    run.fact(rid, "conflict_ui_texts", {
        "statusLine": pg.evaluate(
            """() => { const w = document.querySelector('[data-cog-map]');
                       if (!w) return null;
                       const el = Array.from(w.querySelectorAll('span'))
                         .find((s) => (s.textContent || '').indexOf('Найден') !== -1
                              || (s.textContent || '').indexOf('Не найдено') !== -1
                              || (s.textContent || '').indexOf('конфликт') !== -1);
                       const btn = Array.from(w.querySelectorAll('button'))
                         .find((b) => (b.textContent || '').indexOf('Показать результат') !== -1);
                       return { status: el ? el.textContent.trim().slice(0, 80) : null,
                                showResultBtn: btn ? btn.textContent.trim() : null }; }""")})
    run.shot(pg, rid, "search-filtered-out-1440", selector="[data-cog-map]")
    pg.select_option("[data-cog-map] .graph-search select.field >> nth=0", "")
    pg.wait_for_timeout(1500)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def run_err_02(pg, run):
    """CMV-ERR-02: один узел — нормальный фокус и карточка без ложных соседей."""
    c = W15.COG_CHAT
    rid = "CMV-ERR-02"
    run.attach_console(pg, rid)
    settle(pg)
    ds = pg.evaluate(JS_DS_FACTS)
    st0 = pg.evaluate(JS_SCENE_STATE)
    run.fact(rid, "dataset", ds)
    run.fact(rid, "scene_before", {k: st0[k] for k in
                                   ("viewNodes", "viewEdges", "neighbors")})
    sel = select(pg, "ent:%d:1" % c)
    pg.wait_for_timeout(700)
    st1 = pg.evaluate(JS_SCENE_STATE)
    cam = pg.evaluate(JS_CAMERA)
    run.fact(rid, "selected", sel)
    run.fact(rid, "scene_selected", {
        "neighbors": st1.get("neighbors"), "viewEdges": st1.get("viewEdges"),
        "labelsShown": st1.get("labelsShown"),
        "forcedIds": st1.get("forcedIds")})
    run.fact(rid, "camera", cam)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, rid, "single-node-card-1440", selector="[data-cog-map]")


def run_err_03(pg, run):
    """CMV-ERR-03: 702/2400 + одинаковые имена, длинная русская подпись,
    латиница, эмодзи, узел без типа/метаданных."""
    c = W15.COG_CHAT
    rid = "CMV-ERR-03"
    run.attach_console(pg, rid)
    settle(pg)
    ids = ["ent:%d:201" % c, "fact:%d:202" % c, "ent:%d:203" % c,
           "ent:%d:204" % c, "ent:%d:205" % c, "ent:%d:206" % c]
    infos = {i: pg.evaluate(JS_NODE_INFO, i) for i in ids}
    run.fact(rid, "weird_nodes_in_model", infos)
    ds = pg.evaluate(JS_DS_FACTS)
    cs = pg.evaluate(JS_CLIENT_STATE)
    run.fact(rid, "dataset", ds)
    run.fact(rid, "client_state", cs)
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))
    # карточка на эмодзи-узле
    select(pg, "ent:%d:205" % c)
    pg.wait_for_timeout(700)
    card_emoji = pg.evaluate(
        """() => { const vm = window.__adminbotVm;
                   const d = vm.graphDetail;
                   return d ? { id: d.id, title: d.title, kind: d.kind } : null; }""")
    run.fact(rid, "card_emoji_node", card_emoji)
    run.shot(pg, rid, "emoji-node-card-1440", selector="[data-cog-map]")
    # карточка на узле без типа
    select(pg, "ent:%d:206" % c)
    pg.wait_for_timeout(700)
    card_nokind = pg.evaluate(
        """() => { const vm = window.__adminbotVm;
                   const d = vm.graphDetail;
                   return d ? { id: d.id, title: d.title, kind: d.kind,
                                kindLabel: d.kindLabel } : null; }""")
    run.fact(rid, "card_no_kind_node", card_nokind)
    run.shot(pg, rid, "no-kind-node-card-1440", selector="[data-cog-map]")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)


def run_nav_03_reveal(pg, run):
    """CMV-NAV-03 (часть 1): результат, скрытый LOD-агрегатом, раскрывается
    и фокусируется поиском (закрепление). FIX-702, fit → LOD0."""
    rid = "CMV-NAV-03"
    run.attach_console(pg, rid)
    settle(pg)
    zoom_fit(pg, 0.25)
    lod0 = wait_lod0(pg)
    hidden_ids = pg.evaluate(
        "() => { const vm = window.__adminbotVm; const s = vm && vm._cogScene;"
        " return Object.keys((s && s.hiddenSet) || {}).slice(0, 20); }")
    run.fact(rid, "lod0_reached", lod0)
    run.fact(rid, "hidden_sample_before", hidden_ids)
    if not hidden_ids:
        run.err(rid, "no hidden nodes at LOD0 — precondition failed")
        return
    target = hidden_ids[0]
    info = pg.evaluate(JS_NODE_INFO, target)
    run.fact(rid, "target", info)
    hidden_before = pg.evaluate(JS_HIDDEN_HAS, [target])
    title = (info or {}).get("title") or ""
    st = search_ui(pg, rid, title) if title else None
    pg.wait_for_timeout(600)
    hidden_after = pg.evaluate(JS_HIDDEN_HAS, [target])
    cam = pg.evaluate(JS_CAMERA)
    run.fact(rid, "reveal", {
        "target": target,
        "hiddenBefore": hidden_before, "hiddenAfter": hidden_after,
        "search": st, "camera": cam})
    run.shot(pg, rid, "hidden-result-revealed-1440")
    run.fact(rid, "counters", pg.evaluate(JS_NET_COUNTERS))


def run_fsm_mobile(pg, run):
    """CMV-FSM-01/02: мобильный fullscreen — высота видимой области Mini App
    (100dvh + safe-area паддинги), страница не прокручивается; контролы
    ≥ 44 px, селекторы в видимой области, подписи без обрезки."""
    rid = "CMV-FSM-01"
    run.attach_console(pg, rid)
    settle(pg)
    neg = pg.evaluate(JS_FS_GEO)
    run.fact("CMV-FSM-01", "negative_closed", neg)
    run.shot(pg, "CMV-FSM-01", "negative-no-fullscreen-390")
    pg.click("[data-cog-open-full]")
    pg.wait_for_selector(".status-graph-full", state="visible", timeout=15000)
    settle(pg, 30000)
    geo = pg.evaluate(JS_FS_GEO)
    run.fact("CMV-FSM-01", "fullscreen_geometry", geo)
    run.fact("CMV-FSM-01", "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, "CMV-FSM-01", "fullscreen-390")
    # FSM-02: те же контролы, порог 44 px
    run.attach_console(pg, "CMV-FSM-02")
    run.fact("CMV-FSM-02", "controls", geo.get("controls"))
    run.fact("CMV-FSM-02", "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, "CMV-FSM-02", "fullscreen-controls-390",
             selector=".status-graph-full .cog-fs__bar")
    close_fullscreen(pg)
    closed = pg.evaluate(
        "() => !!document.querySelector('.status-graph-full')")
    run.fact("CMV-FSM-01", "closed_after_esc", {"present": closed})


def main():
    M.PORT = 0  # случайный свободный порт — один инстанс сервера на прогон
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
                # ═══ S1: BASE, desktop 1440 (embed) ════════════════════════
                stats = {"count": 0, "last": ""}
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", make_routes(stats))
                pg = ctx.new_page()
                W15.set_cog_payload(base_payload())
                pg.goto(base + "#/", wait_until="load")
                run_lod1_03(pg, run)
                run_int_07(pg, run)
                run_lodb_04(pg, run, stats)
                run_nav_04(pg, run)
                run_nav_06(pg, run)
                # вернуть BASE после обновления из LODB-04
                W15.set_cog_payload(base_payload())
                pg.close()
                ctx.close()

                # ═══ S2: RICH2, desktop 1440 (NAV-01/02/03-фильтр) ═════════
                stats2 = {"count": 0, "last": ""}
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", make_routes(stats2))
                pg = ctx.new_page()
                W15.set_cog_payload(rich2_payload())
                pg.goto(base + "#/", wait_until="load")
                run_nav_01(pg, run, stats2)
                run_nav_02(pg, run)
                run_nav_03_conflict(pg, run)
                pg.close()
                ctx.close()

                # ═══ S3: single, desktop 1440 (ERR-02) ═════════════════════
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", make_routes({"count": 0, "last": ""}))
                pg = ctx.new_page()
                W15.set_cog_payload(single_payload())
                pg.goto(base + "#/", wait_until="load")
                run_err_02(pg, run)
                pg.close()
                ctx.close()

                # ═══ S4: FIX-702, desktop 1440 (NAV-03-раскрытие) ══════════
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**",
                          make_routes({"count": 0, "last": ""}))
                pg = ctx.new_page()
                W15.set_cog_payload(fx702_payload())
                pg.goto(base + "#/", wait_until="load")
                run_nav_03_reveal(pg, run)
                pg.close()
                ctx.close()

                # ═══ S5: weird 702, desktop 1440 + mobile 390 (ERR-03) ═════
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**",
                          make_routes({"count": 0, "last": ""}))
                pg = ctx.new_page()
                W15.set_cog_payload(weird702_payload())
                pg.goto(base + "#/", wait_until="load")
                run_err_03(pg, run)
                pg.close()
                ctx.close()

                ctx = browser.new_context(
                    viewport={"width": MOBILE[0], "height": MOBILE[1]},
                    device_scale_factor=2, is_mobile=True, has_touch=True)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**",
                          make_routes({"count": 0, "last": ""}))
                pg = ctx.new_page()
                W15.set_cog_payload(weird702_payload())
                pg.goto(base + "#/", wait_until="load")
                run.attach_console(pg, "CMV-ERR-03")
                settle(pg, 60000)
                pg.click("[data-cog-open-full]")
                pg.wait_for_selector(".status-graph-full", state="visible",
                                     timeout=15000)
                settle(pg, 30000)
                run.shot(pg, "CMV-ERR-03", "weird-nodes-fullscreen-390")
                pg.close()
                ctx.close()

                # ═══ S6: BASE, mobile 390 (FSM-01/02) ══════════════════════
                ctx = browser.new_context(
                    viewport={"width": MOBILE[0], "height": MOBILE[1]},
                    device_scale_factor=2, is_mobile=True, has_touch=True)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**",
                          make_routes({"count": 0, "last": ""}))
                pg = ctx.new_page()
                W15.set_cog_payload(base_payload())
                pg.goto(base + "#/", wait_until="load")
                run_fsm_mobile(pg, run)
                pg.close()
                ctx.close()
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        for rid in run.rows:
            run.err(rid, "runner: " + traceback.format_exc()[-300:])
    finally:
        run.save_manifest()
        server.shutdown()
    print(json.dumps({rid: {"shots": len(rec["shots"]),
                            "facts": sorted(rec["facts"].keys()),
                            "console_errors": rec["console_errors"],
                            "errors": rec["errors"]}
                      for rid, rec in run.rows.items()},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
