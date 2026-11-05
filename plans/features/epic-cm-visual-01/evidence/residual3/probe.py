"""EPIC-CM-VISUAL-01 — residual evidence batch 3, финальный (evidence-only).

Ветка `cmv/residual-evidence-3` от `df00f178`. Продуктовых правок нет.
Строки пакета 3 (остаток задания пакета 2):

  CMV-ANI-01, CMV-PHY-03, CMV-PHY-04, CMV-AI-01..04, CMV-PERF-05.
  CMV-PERF-06 — отдельный существующий инструмент tools/ui_cmv_e_leaks.py
  (исправленная версия ветки cmv/perf) с --repo на эту ветку.
  CMV-VIS-13 — отдельный скрипт vis13_reshoot.py (пары «до/после» на одном
  узле paradigm:-1001234567890:184, три ревизии на локальных стендах).
  CMV-INV-10 — production-строка (вне локального стенда).
  CMV-GATE-17 — документированные числа/ограничения Reviewer (цитаты в
  отчёте, перемер запрещён заданием).

Метод — как в пакете 2: реальная сборка на локальном стенде
(`ui_round1025_matrix._start_server` + `ui_evol_w15_composition_e2e`),
кадры desktop 1440 / mobile 390, числа из DOM/движка (сцена, fx-канвас,
камера vis, план пульса), реальные события мыши/клавиатуры через
Playwright (тайминг-замеры — через evaluate_handle: сэмплер взводится ДО
реального ввода), отрицательные контроли, консоль без ошибок, ровно один
vis-network инстанс на пробу.

Запуск:
  <venv python> plans/features/epic-cm-visual-01/evidence/residual3/probe.py \
      [--rows ani1,phy3,phy4,ai01,ai02,ai03,ai04,perf05]
Выход: plans/features/epic-cm-visual-01/evidence/residual3/<REQ>/… + manifest.json
"""
import argparse
import hashlib
import json
import os
import statistics
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
TARGET_ID = "paradigm:-1001234567890:184"  # топ по степени в FIX-702 (deg 13)

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
JS_COUNT = r"""
() => {
  const vm = window.__adminbotVm;
  return {
    visNetworks: document.querySelectorAll('.vis-network').length,
    scenes: document.querySelectorAll('.cognition-graph').length,
    selectedId: vm ? (vm._cogSelectedId === undefined
                      ? null : vm._cogSelectedId) : null,
    reducedMotion: !!(vm && vm.reducedMotion),
  };
}
"""

JS_CAMERA = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  if (!net) return { net: false };
  let vp = null;
  try { vp = net.getViewPosition(); } catch (e) { /* уничтожена */ }
  return {
    net: true,
    scale: +net.getScale().toFixed(5),
    vx: vp ? +vp.x.toFixed(2) : null,
    vy: vp ? +vp.y.toFixed(2) : null,
    fitScale: (typeof vm._cogFitScale === 'number')
      ? +vm._cogFitScale.toFixed(5) : null,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    settled: !!(vm._cogScene && vm._cogScene.settled),
    visNetworks: document.querySelectorAll('.vis-network').length,
  };
}
"""

# Экранная проекция узла (та же математика, что в ui_cmv_e_cine.PROJECT);
# радиус — из реального targetDiameter (размер узлов компенсируется, экран
# r = target/2 × scale/fitScale).
JS_PROJECT = r"""
(id) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const el = vm._cogEl || document.querySelector('.cognition-graph');
  const canvas = el ? el.querySelector('canvas') : null;
  if (!canvas) return null;
  const pos = (vm._cogScene && vm._cogScene.pos) || net.getPositions() || {};
  const p = pos[id];
  if (!p) return null;
  const box = canvas.getBoundingClientRect();
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const cam = net.getViewPosition(), sc = net.getScale();
  const sx = (p.x - cam.x) * sc + W / 2;
  const sy = (p.y - cam.y) * sc + H / 2;
  const fit = vm._cogFitScale || 1;
  const info = vm.cognitionGraphData && vm.cognitionGraphData.byId
    ? vm.cognitionGraphData.byId[id] : null;
  const deg = (info && typeof info.degree === 'number') ? info.degree : 0;
  // targetDiameter (как в cog-visual.js §3.4): base + min(8, 2.2·log2(1+d));
  // экранный радиус fx-слоя = target/2 × scale/fitScale (размер
  // компенсируется); ядро vis ограничено потолком 24 px при r=1.
  const BASE_D = { paradigm: 22, belief: 18, fact: 14,
                   evolution_event: 13, entity: 11, observation: 10,
                   other: 9 };
  const base = BASE_D[(info && info.kind) || 'other'] || 9;
  const target = base + Math.min(8,
    2.2 * Math.log(1 + deg) / Math.LN2);
  const ratio = sc / fit;
  const nodeR = Math.max(3, +(target / 2 * ratio).toFixed(1));
  const coreR = Math.max(3, +(Math.min(target, 24) / 2 * ratio).toFixed(1));
  const inVp = box.left + sx >= 0 && box.top + sy >= 0
    && box.left + sx <= window.innerWidth - 2
    && box.top + sy <= window.innerHeight - 2;
  return { x: box.left + sx, y: box.top + sy, sx: sx, sy: sy, w: W, h: H,
           inside: sx > 60 && sy > 60 && sx < W - 60 && sy < H - 60,
           inViewport: inVp,
           scale: sc, fit: fit, ratio: ratio,
           degree: deg, kind: info ? info.kind : null,
           nodeR: nodeR, coreR: coreR };
}
"""

JS_PULSE_PLAN = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene) return { scene: false };
  let motion = null;
  try {
    const V = (typeof cogVis === 'function') ? cogVis() : null;
    motion = (V && V.CONFIG && V.CONFIG.motion) || null;
  } catch (e) { motion = null; }
  const plan = (scene.pulse || []).map((e) => ({
    id: String(e.id), period: e.period, phase: e.phase, amp: e.amp }));
  return { scene: true, plan: plan, motion: motion,
           lod: scene.lod, settled: !!scene.settled,
           hoverId: (scene.hoverId === undefined) ? null : scene.hoverId,
           pulseHit: scene.pulseHit ? {
             id: scene.pulseHit.id, kind: scene.pulseHit.kind,
             duration: scene.pulseHit.duration } : null };
}
"""

JS_SCENE_STATE = r"""
() => {
  const vm = window.__adminbotVm;
  const s = vm && vm._cogScene;
  if (!vm || !s) return { scene: false };
  const labels = vm._cogLabels || {};
  const c = (vm._cogDebugCounters ? vm._cogDebugCounters() : {}) || {};
  return {
    scene: true,
    lod: (typeof s.lod === 'number') ? s.lod : null,
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    hoverId: (s.hoverId === undefined) ? null : s.hoverId,
    cursor: s.el ? s.el.style.cursor : null,
    labelsShown: labels.shown !== undefined ? labels.shown : (c.labelsShown || 0),
    forcedIds: (labels.forced || []).map((l) => String(l.id)),
    labelIds: (labels.labels || []).map((l) => String(l.id)).slice(0, 24),
    neighbors: (typeof vm._cogNeighborIds === 'function')
      ? vm._cogNeighborIds().map(String) : [],
    fxCounters: c,
    frames: s.frames || 0,
    pulseHit: s.pulseHit ? { id: s.pulseHit.id, kind: s.pulseHit.kind,
                             duration: s.pulseHit.duration } : null,
    detail: vm.graphDetail ? { id: vm.graphDetail.id, kind: vm.graphDetail.kind,
                               title: vm.graphDetail.title } : null,
    cardOpen: vm.cogCardOpen === true,
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
    selectedId: (vm._cogSelectedId === undefined) ? null : vm._cogSelectedId,
    detail: vm.graphDetail
      ? { id: vm.graphDetail.id, kind: vm.graphDetail.kind } : null,
  };
}
"""

JS_NODE_INFO = r"""
(id) => {
  const vm = window.__adminbotVm;
  const model = (vm && vm.cognitionGraphData) || {};
  const n = model.byId ? model.byId[String(id)] : null;
  if (!n) return null;
  return { id: n.id, title: n.title, kind: n.kind };
}
"""

# Таймлайн загрузки страницы (PERF-05): события навигации, момент создания
# сети (счётная обёртка vis.Network), long tasks.
INSTRUMENT_TIMELINE = r"""
(() => {
  const P = { longtasks: [], netCreated: [], netCount: 0 };
  window.__perf5 = P;
  try {
    const po = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        P.longtasks.push({ start: Math.round(e.startTime),
                           dur: Math.round(e.duration) });
      }
    });
    po.observe({ entryTypes: ['longtask'] });
  } catch (e) { /* longtask недоступен */ }
  const tryPatch = () => {
    if (!window.vis || !window.vis.Network || window.vis.__cmvPatched) return;
    const Orig = window.vis.Network;
    window.vis.Network = function (el, data, options) {
      P.netCount += 1;
      P.netCreated.push({ at: Math.round(
        performance.now ? performance.now() : 0), n: P.netCount });
      return new Orig(el, data, options);
    };
    window.vis.Network.prototype = Orig.prototype;
    Object.assign(window.vis.Network, Orig);
    window.vis.__cmvPatched = true;
  };
  tryPatch();
  window.addEventListener('load', tryPatch);
})();
"""

JS_PERF_TIMELINE = r"""
() => {
  const nav = (performance.getEntriesByType('navigation') || [])[0] || {};
  const P = window.__perf5 || {};
  const vm = window.__adminbotVm;
  return {
    loadEventEnd: nav.loadEventEnd != null ? +nav.loadEventEnd.toFixed(1) : null,
    domContentLoaded: nav.domContentLoadedEventEnd != null
      ? +nav.domContentLoadedEventEnd.toFixed(1) : null,
    fcp: (() => {
      const paints = performance.getEntriesByType('paint') || [];
      const f = paints.find((p) => p.name === 'first-contentful-paint');
      return f ? +f.startTime.toFixed(1) : null;
    })(),
    longtasksBeforeLoad: (P.longtasks || []).filter(
      (t) => nav.loadEventEnd != null && t.start < nav.loadEventEnd).length,
    longtasks: (P.longtasks || []).slice(0, 20),
    netCreated: P.netCreated || [],
    netCount: P.netCount || 0,
    netNow: !!vm.cognitionNetwork,
    visNetworks: document.querySelectorAll('.vis-network').length,
    settled: !!(vm._cogScene && vm._cogScene.settled),
    frames: vm._cogScene ? (vm._cogScene.frames || 0) : null,
  };
}
"""

# Замер кадра: afterDrawing vis + покадровые счётчики сцены за окно.
JS_FRAME_RATE = r"""
(spec) => new Promise((resolve) => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  const scene = vm && vm._cogScene;
  if (!net || !scene) { resolve(null); return; }
  let drawn = 0;
  const onDraw = () => { drawn += 1; };
  if (typeof net.on === 'function') net.on('afterDrawing', onDraw);
  const f0 = scene.frames || 0;
  const p0 = (scene.fx && scene.fx.counters) ? scene.fx.counters().paints : 0;
  const t0 = performance.now();
  setTimeout(() => {
    if (typeof net.off === 'function') net.off('afterDrawing', onDraw);
    const f1 = scene.frames || 0;
    const p1 = (scene.fx && scene.fx.counters)
      ? scene.fx.counters().paints : 0;
    resolve({ ms: Math.round(performance.now() - t0), visFrames: drawn,
              sceneFrames: f1 - f0, fxPaints: p1 - p0,
              longtasksInWindow: ((window.__perf5 || {}).longtasks || [])
                .filter((t) => t.start >= t0 - performance.timeOrigin
                          ? false : false).length });
  }, spec.ms);
})
"""

JS_CAMERA_TIMELINE = r"""
(spec) => new Promise((resolve) => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  if (!net) { resolve(null); return; }
  const out = [];
  const t0 = performance.now();
  let last = null;
  const step = () => {
    const now = performance.now() - t0;
    let s = null, vx = null, vy = null;
    try {
      s = +net.getScale().toFixed(4);
      const vp = net.getViewPosition();
      vx = +vp.x.toFixed(1); vy = +vp.y.toFixed(1);
    } catch (e) { /* уничтожена */ }
    const cur = s + '|' + vx + '|' + vy;
    if (cur !== last) { out.push({ t: +now.toFixed(0), scale: s,
                                   vx: vx, vy: vy }); last = cur; }
    if (now < spec.ms) requestAnimationFrame(step);
    else resolve(out);
  };
  requestAnimationFrame(step);
})
"""

# Серия замеров яркости fx-канваса в кольце вокруг узлов (rAF-темп).
# Для каждой цели: ring — средняя яркость кольца [1.5r, 3r] (r задаёт полосу),
# diff — средний |Δ| против опорного кадра (первого замера): статичный фон
# (туман ореолов, подписи) сокращается, остаётся только меняющийся сигнал.
JS_SAMPLE_SERIES = r"""
(spec) => new Promise((resolve) => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene || !scene.fxCanvas || !scene.fxCtx) { resolve(null); return; }
  const dpr = scene.fxDpr || 1;
  const targets = (spec.targets || []).map((t) => {
    const cx = Math.round(t.sx * dpr), cy = Math.round(t.sy * dpr);
    const rr = Math.max(6, Math.round((t.r || 10) * 1.5 * dpr));
    const x0 = Math.max(0, cx - rr * 2), y0 = Math.max(0, cy - rr * 2);
    const w = Math.min(scene.fxCanvas.width - x0, rr * 4);
    const h = Math.min(scene.fxCanvas.height - y0, rr * 4);
    const pts = [], core = [];
    for (let py = 0; py < h; py += 2) {
      const dy = py - (cy - y0);
      for (let px = 0; px < w; px += 2) {
        const dx = px - (cx - x0);
        const d = Math.sqrt(dx * dx + dy * dy);
        const idx = (py * w + px) * 4;
        if (d >= rr && d <= rr * 2) pts.push(idx);
        else if (d <= rr * 0.8) core.push(idx);
      }
    }
    return { id: t.id, x0: x0, y0: y0, w: w, h: h, pts: pts, core: core,
             ref: null };
  });
  const series = targets.map((t) => ({ id: t.id, samples: [] }));
  const t0 = performance.now();
  let slot = 0;
  const step = () => {
    const now = performance.now();
    while (slot < spec.count && now - t0 >= slot * spec.intervalMs) {
      for (let i = 0; i < targets.length; i += 1) {
        const t = targets[i];
        if (t.w <= 4 || t.h <= 4) { series[i].samples.push(null); continue; }
        const data = scene.fxCtx.getImageData(t.x0, t.y0, t.w, t.h).data;
        let sum = 0, cSum = 0, dSum = 0;
        for (let k = 0; k < t.pts.length; k += 1) {
          const j = t.pts[k]; sum += data[j] + data[j + 1] + data[j + 2];
        }
        for (let k = 0; k < t.core.length; k += 1) {
          const j = t.core[k]; cSum += data[j] + data[j + 1] + data[j + 2];
        }
        if (t.ref && t.ref.length === data.length) {
          for (let k = 0; k < t.pts.length; k += 1) {
            const j = t.pts[k];
            dSum += Math.abs(data[j] - t.ref[j])
                  + Math.abs(data[j + 1] - t.ref[j + 1])
                  + Math.abs(data[j + 2] - t.ref[j + 2]);
          }
        } else {
          t.ref = new Uint8ClampedArray(data);
        }
        series[i].samples.push({
          t: +(now - t0).toFixed(1),
          ring: t.pts.length ? +(sum / (t.pts.length * 3)).toFixed(2) : null,
          core: t.core.length ? +(cSum / (t.core.length * 3)).toFixed(2) : null,
          diff: (t.ref && slot > 0 && t.pts.length)
            ? +(dSum / (t.pts.length * 3)).toFixed(2) : null,
        });
      }
      slot += 1;
    }
    if (slot < spec.count) requestAnimationFrame(step);
    else resolve({ t0: t0, series: series });
  };
  requestAnimationFrame(step);
})
"""

JS_SCENE_POS = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene) return {};
  const out = {};
  const pos = scene.pos || {};
  for (const k in pos) {
    if (Object.prototype.hasOwnProperty.call(pos, k)) {
      out[k] = { x: +pos[k].x.toFixed(2), y: +pos[k].y.toFixed(2) };
    }
  }
  return out;
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

JS_CLEAR_SEL = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm) return true;
  try {
    if (vm.cognitionNetwork && vm.cognitionNetwork.unselectAll) {
      vm.cognitionNetwork.unselectAll();
    }
    if (typeof vm.graphClearDetail === 'function') vm.graphClearDetail();
    else vm.cogCardOpen = false;
  } catch (e) { /* noop */ }
  return true;
}
"""

JS_FX_SNAPSHOT = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene || !scene.fxCanvas || !scene.fxCtx) return null;
  const dpr = scene.fxDpr || 1;
  const w = Math.min(scene.fxCanvas.width, Math.round(scene.width * dpr));
  const h = Math.min(scene.fxCanvas.height, Math.round(scene.height * dpr));
  const data = scene.fxCtx.getImageData(0, 0, w, h).data;
  window.__cmvFxShot = window.__cmvFxShot || {};
  const old = window.__cmvFxShot.main;
  window.__cmvFxShot.main = data;
  let sum = 0, n = 0, energy = 0;
  if (old && old.length === data.length) {
    for (let i = 0; i < data.length; i += 4) {
      const d = Math.abs(data[i] - old[i]) + Math.abs(data[i + 1] - old[i + 1])
        + Math.abs(data[i + 2] - old[i + 2]);
      if (d > 6) n += 1;
      sum += d;
    }
  }
  const px = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    energy += data[i] + data[i + 1] + data[i + 2];
  }
  return { px: px,
           meanLuma: +(energy / px / 3).toFixed(2),
           changedShare: old ? +(n / px).toFixed(5) : null,
           meanDelta: old ? +(sum / (px * 3)).toFixed(3) : null };
}
"""

# ── фикстуры ────────────────────────────────────────────────────────────────
FIXED_TS = 1750000000  # фиксированный generated_at: детерминированный payload


def fx702_payload():
    p = FIX.load(702)
    p["generated_at"] = FIXED_TS
    return p


def fx702_plus_payload():
    """FIX-702 + один новый узел с ребром к первому (AI-04: обновление данных)."""
    p = fx702_payload()
    anchor = p["nodes"][0]["id"]
    chat = W15.COG_CHAT
    prov = {"record": "graph_facts", "chat_id": chat, "message_id": 556,
            "origin": "chat_history", "fact_id": 92}
    p["nodes"].append({
        "id": "ent:%d:901" % chat, "kind": "entity", "scope": "chat",
        "chat_id": chat, "title": "Узел обновления R3",
        "text": "Узел обновления R3", "status": None, "isolated": False,
        "time": {"occurred_at": 1750000001, "observed_at": None,
                 "saved_at": 1750000101, "confirmed_at": None,
                 "updated_at": None},
        "provenance": prov,
        "metrics": {"importance": 5, "weight": None, "degree": None},
        "refs": {},
    })
    p["edges"].append({"id": "r3e1", "from": anchor, "to": "ent:%d:901" % chat,
                       "relation": "обсуждали", "derived": False,
                       "chat_id": chat, "justification_recorded": True,
                       "provenance": {"fact_id": 92}})
    p["shown_of"]["nodes"] = len(p["nodes"])
    p["shown_of"]["edges"] = len(p["edges"])
    p["generated_at"] = FIXED_TS + 1
    return p


def make_routes(stats):
    base_route = W15._routes()

    def handler(route):
        url = route.request.url.split("?")[0]
        stats["count"] += 1
        stats["last"] = url[-70:]
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

    def save_manifest(self, batch, branch, base_commit):
        manifest = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "branch": branch, "base_commit": base_commit,
                    "batch": batch, "rows": {}}
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


def settle(pg, timeout_ms=120000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    # карта целиком в вьюпорте (как в ui_cmv_e_cine) — иначе клики/жесты
    # по экранным координатам уходят мимо окна
    pg.evaluate("""() => { const vm = window.__adminbotVm;
      const el = vm._cogEl || document.querySelector('.cognition-graph');
      if (el) el.scrollIntoView({ block: 'center' }); }""")
    pg.wait_for_timeout(500)


def wait_positions_stable(pg, timeout_ms=15000, tol=0.5):
    """Ждать, пока позиции узлов перестанут меняться (после смены зума vis
    пересчитывает размеры через ds.update и физика дотягивает раскладку —
    координаты для кликов/замеров можно снимать только в стазисе)."""
    t0 = time.time()
    prev = pg.evaluate(JS_SCENE_POS)
    while time.time() - t0 < timeout_ms / 1000.0:
        pg.wait_for_timeout(600)
        cur = pg.evaluate(JS_SCENE_POS)
        dmax = 0.0
        for k, p in cur.items():
            p0 = prev.get(k)
            if not p0:
                continue
            d = abs(p["x"] - p0["x"]) + abs(p["y"] - p0["y"])
            if d > dmax:
                dmax = d
        prev = cur
        if dmax <= tol:
            return True
    return False


def camera_to(pg, node_id, ratio=1.8):
    """Камера на узел с масштабом ratio×fit (без анимации) + стазис позиций."""
    pg.evaluate("""([id, ratio]) => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      const cache = (vm._cogScene && vm._cogScene.pos)
        || net.getPositions() || {};
      const pos = cache[id] || net.getViewPosition();
      const fit = vm._cogFitScale || net.getScale();
      net.moveTo({ position: { x: pos.x, y: pos.y },
                   scale: fit * ratio, animation: false });
      return { fit: fit, scale: net.getScale() };
    }""", [node_id, ratio])
    pg.wait_for_timeout(500)
    wait_positions_stable(pg)


def world_at_screen(pg, sx, sy):
    return pg.evaluate("""([sx, sy]) => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      const el = vm._cogEl || document.querySelector('.cognition-graph');
      const canvas = el ? el.querySelector('canvas') : null;
      if (!canvas) return null;
      const box = canvas.getBoundingClientRect();
      const cam = net.getViewPosition(), sc = net.getScale();
      return { wx: +(cam.x + (sx - canvas.clientWidth / 2) / sc).toFixed(2),
               wy: +(cam.y + (sy - canvas.clientHeight / 2) / sc).toFixed(2),
               scale: +sc.toFixed(5) };
    }""", [sx, sy])


def empty_spot(pg):
    """Точка канваса с максимальным расстоянием до узлов (пустота)."""
    return pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      const el = vm._cogEl || document.querySelector('.cognition-graph');
      const canvas = el ? el.querySelector('canvas') : null;
      if (!canvas) return null;
      const box = canvas.getBoundingClientRect();
      const W = canvas.clientWidth, H = canvas.clientHeight;
      const cam = net.getViewPosition(), sc = net.getScale();
      const pos = (vm._cogScene && vm._cogScene.pos) || net.getPositions() || {};
      let best = null;
      for (let gx = 90; gx < W - 90; gx += 55) {
        for (let gy = 90; gy < H - 90; gy += 55) {
          let dmin = 1e9;
          for (const k in pos) {
            const p = pos[k];
            const dx = (p.x - cam.x) * sc + W / 2 - gx;
            const dy = (p.y - cam.y) * sc + H / 2 - gy;
            const d = Math.sqrt(dx * dx + dy * dy);
            if (d < dmin) dmin = d;
          }
          if (!best || dmin > best.dmin) {
            best = { x: +(box.left + gx).toFixed(1),
                     y: +(box.top + gy).toFixed(1), dmin: +dmin.toFixed(1) };
          }
        }
      }
      return best;
    }""")


def node_screen(pg, node_id):
    p = pg.evaluate(JS_PROJECT, node_id)
    if p and p["inside"] and p.get("inViewport"):
        return {"x": p["x"], "y": p["y"], "sx": p["sx"], "sy": p["sy"],
                "nodeR": p["nodeR"], "coreR": p.get("coreR"),
                "degree": p["degree"], "kind": p.get("kind")}
    return None


def spaced_visible_nodes(pg, plan_ids, need, min_fill=2.2, thr_px=None):
    """Видимые узлы в вьюпорте, у центра которых нет чужого ядра в радиусе
    клика/наведения (dmin ≥ min_fill×coreR + 4 px) — чистые замеры яркости
    по fx-кольцу и надёжные click/hover по vis- hit-test. thr_px задаёт
    порог напрямую (например, радиус дальнего ореола)."""
    out = []
    for nid in plan_ids:
        p = pg.evaluate(JS_PROJECT, nid)
        if not (p and p["inside"] and p.get("inViewport")):
            continue
        d = pg.evaluate("""(me) => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const canvas = (vm._cogEl
            || document.querySelector('.cognition-graph'))
            .querySelector('canvas');
          const box = canvas.getBoundingClientRect();
          const W = canvas.clientWidth, H = canvas.clientHeight;
          const cam = net.getViewPosition(), sc = net.getScale();
          const pos = (vm._cogScene && vm._cogScene.pos)
            || net.getPositions() || {};
          let dmin = 1e9;
          for (const k in pos) {
            if (k === me.id) continue;
            const p = pos[k];
            const dx = (p.x - cam.x) * sc + W / 2 - me.sx;
            const dy = (p.y - cam.y) * sc + H / 2 - me.sy;
            const d = Math.sqrt(dx * dx + dy * dy);
            if (d < dmin) dmin = d;
          }
          return +dmin.toFixed(1);
        }""", {"id": nid, "sx": p["sx"], "sy": p["sy"]})
        thr = thr_px if thr_px is not None \
            else min_fill * (p.get("coreR") or p["nodeR"]) + 4
        if d >= thr:
            out.append({"id": nid, "sx": p["sx"], "sy": p["sy"],
                        "r": p["nodeR"], "coreR": p.get("coreR"),
                        "dmin": d, "thr": +thr})
        if len(out) >= need:
            break
    return out


def positions_timeline(pg, count=14, interval=200):
    return pg.evaluate("""(spec) => new Promise((resolve) => {
      const vm = window.__adminbotVm;
      const scene = vm && vm._cogScene;
      if (!scene) { resolve(null); return; }
      const out = [];
      const t0 = performance.now();
      let slot = 0;
      const step = () => {
        const now = performance.now();
        while (slot < spec.count && now - t0 >= slot * spec.intervalMs) {
          const pos = scene.pos || {};
          const snap = {};
          for (const k in pos) {
            if (Object.prototype.hasOwnProperty.call(pos, k)) {
              snap[k] = [+pos[k].x.toFixed(2), +pos[k].y.toFixed(2)];
            }
          }
          out.push({ t: +(now - t0).toFixed(0), pos: snap });
          slot += 1;
        }
        if (slot < spec.count) requestAnimationFrame(step);
        else resolve(out);
      };
      requestAnimationFrame(step);
    })""", {"count": count, "intervalMs": interval})


def plan_spaced_targets(pg, plan, need, ratio_hint=None):
    """Узлы плана пульса, разнесённые с ДРУГИМИ УЗЛАМИ ПЛАНА (их ореолы
    осциллируют; статичное соседнее окружение сокращается в diff-ряде).
    Порог — радиус дальнего ореола 2.65×g + запас."""
    ids = [e["id"] for e in plan.get("plan") or []]
    by_id = {e["id"]: e for e in plan.get("plan") or []}
    proj = {}
    for nid in ids:
        p = pg.evaluate(JS_PROJECT, nid)
        if p and p["inside"] and p.get("inViewport"):
            proj[nid] = p
    out = []
    for nid, p in proj.items():
        g = min(p["nodeR"], 16.0)
        thr = 2.65 * g + 14
        dmin = 1e9
        for oid, op in proj.items():
            if oid == nid:
                continue
            d = ((op["sx"] - p["sx"]) ** 2 + (op["sy"] - p["sy"]) ** 2) ** 0.5
            if d < dmin:
                dmin = d
        out.append({"id": nid, "sx": p["sx"], "sy": p["sy"],
                    "r": p["nodeR"], "g": g, "dmin": round(dmin, 1),
                    "thr": round(thr, 1), "ok": dmin >= thr})
    out.sort(key=lambda c: (-c["dmin"], c["id"]))
    return out, by_id


def autocorr_period(xs, lo=2800, hi=5300, step=100):
    """Период по автокорреляции ряда (устойчиво к широкополосному дрейфу
    соседей): ряд ресемплируется на сетку 100 ms, максимум ACF в [lo, hi]."""
    if len(xs) < 30:
        return {"error": "мало точек"}
    t_min, t_max = xs[0][0], xs[-1][0]
    grid_t = list(range(int(t_min), int(t_max) + 1, step))
    grid_v = []
    j = 0
    for gt in grid_t:
        while j + 1 < len(xs) and abs(xs[j + 1][0] - gt) <= abs(xs[j][0] - gt):
            j += 1
        grid_v.append(xs[j][1])
    n = len(grid_v)
    mean = statistics.mean(grid_v)
    x = [v - mean for v in grid_v]
    denom = sum(v * v for v in x) or 1e-9
    best = None
    curve = []
    for lag_ms in range(lo, min(hi, (n - 3) * step) + 1, 50):
        k = lag_ms // step
        if k <= 0 or k >= n - 1:
            continue
        num = sum(x[i] * x[i + k] for i in range(n - k))
        r = num / denom
        curve.append({"lag": lag_ms, "r": round(r, 4)})
        if best is None or r > best["r"]:
            best = {"lag": lag_ms, "r": round(r, 4)}
    rs = [c["r"] for c in curve] or [0]
    return {"period": best["lag"] if best else None,
            "acfPeak": best["r"] if best else None,
            "acfMean": round(statistics.mean(rs), 4),
            "acfMax": round(max(rs), 4),
            "significance": round((best["r"] - statistics.mean(rs))
                                  / (statistics.pstdev(rs) or 1e-9), 1)
            if best else None,
            "curve": curve}


def analyze_pulse(samples, t_exp, phase_exp):
    """Фолдинг ряда яркости по ожидаемому периоду плана пульса.

    Возвращает: амплитуду волны, значимость (A/σ_residual), корреляцию
    циклов 1↔2, измеренную фазу (из положения максимума свёрнутой волны:
    максимум при t = T/4 − φ) и её отклонение от план-фазы."""
    xs = [(s["t"], s["ring"]) for s in samples
          if s and s.get("ring") is not None]
    if len(xs) < 20 or not t_exp:
        return {"error": "мало точек", "n": len(xs)}
    n_bins = 20
    cycles = {}
    for t, v in xs:
        c = int(t // t_exp)
        cycles.setdefault(c, []).append(v)
    n_cycles = len(cycles)
    bins = [[] for _ in range(n_bins)]
    for t, v in xs:
        b = int((t % t_exp) / t_exp * n_bins)
        if 0 <= b < n_bins:
            bins[b].append(v)
    wave = [statistics.mean(b) if b else None for b in bins]
    vals = [v for _, v in xs]
    resid = []
    for t, v in xs:
        b = int((t % t_exp) / t_exp * n_bins)
        w = wave[b]
        if w is not None:
            resid.append(v - w)
    sigma = statistics.pstdev(resid) or 1e-9
    wv = [w if w is not None else statistics.mean(vals) for w in wave]
    amp = (max(wv) - min(wv)) / 2.0
    snr = amp / sigma
    # корреляция циклов 1 и 2 (выровненные бины)
    r12 = None
    c1 = cycles.get(1)
    c2 = cycles.get(2)
    if c1 and c2 and len(c1) >= 5 and len(c2) >= 5:
        m = min(len(c1), len(c2))
        a = c1[:m]
        b2 = c2[:m]
        ma, mb = statistics.mean(a), statistics.mean(b2)
        da = [x - ma for x in a]
        db = [x - mb for x in b2]
        num = sum(x * y for x, y in zip(da, db))
        den = (sum(x * x for x in da) * sum(y * y for y in db)) ** 0.5
        r12 = round(num / den, 3) if den else None
    # фаза: бин максимума свёрнутой волны
    i_max = max(range(n_bins), key=lambda i: wv[i])
    bin_w = t_exp / n_bins
    tau = i_max * bin_w + bin_w / 2
    phase_meas = (t_exp / 4.0 - tau) % t_exp
    d_phase = min(abs(phase_meas - phase_exp),
                  t_exp - abs(phase_meas - phase_exp))
    return {
        "n": len(xs), "cycles": n_cycles, "ampLuma": round(amp, 3),
        "residSigma": round(sigma, 3), "snr": round(snr, 1),
        "corrCycle12": r12,
        "periodic": bool(snr >= 3.0 and (r12 is None or r12 >= 0.5)),
        "waveform": [round(w, 3) for w in wv],
        "phaseMeasured": round(phase_meas, 1),
        "phaseExpected": phase_exp,
        "phaseDelta": round(d_phase, 1),
    }


def estimate_period_phase(samples, key="ring",
                          expect_min=2800, expect_max=5300):
    """Период/фаза из ряда {t, <key>}: локальные максимумы → интервалы."""
    xs = [(s["t"], s.get(key)) for s in samples
          if s and s.get(key) is not None]
    if len(xs) < 10:
        return {"error": "слишком мало точек", "n": len(xs)}
    vals = [v for _, v in xs]
    base = statistics.mean(vals)
    sigma = statistics.pstdev(vals) or 1.0
    thr_add = 0.5 * sigma if key == "ring" else 0.4 * max(
        1.0, max(vals) - base)
    peaks = []
    for i in range(1, len(xs) - 1):
        if (xs[i][1] > xs[i - 1][1] and xs[i][1] >= xs[i + 1][1]
                and xs[i][1] > base + thr_add):
            if peaks and xs[i][0] - peaks[-1][0] < 800:
                if xs[i][1] > peaks[-1][1]:
                    peaks[-1] = xs[i]
                continue
            peaks.append(xs[i])
    period = None
    if len(peaks) >= 3:
        gaps = [peaks[i + 1][0] - peaks[i][0] for i in range(len(peaks) - 1)]
        period = statistics.median(gaps)
    elif len(peaks) == 2:
        period = peaks[1][0] - peaks[0][0]
        out_single = True
    cores = [s["core"] for s in samples if s and s.get("core") is not None]
    out = {"n": len(xs), "base": round(base, 2),
           "sigma": round(sigma, 2), "peaks": [p[0] for p in peaks],
           "period": round(period, 1) if period else None,
           "inRange": (period is not None
                       and expect_min <= period <= expect_max),
           "singleInterval": len(peaks) == 2,
           "min": round(min(vals), 2), "max": round(max(vals), 2),
           "swingPct": round((max(vals) - min(vals))
                             / max(1.0, base) * 100, 1),
           "coreSigma": round(statistics.pstdev(cores), 2)
           if len(cores) > 2 else None}
    return out


# ── строки ──────────────────────────────────────────────────────────────────
def run_ani01(pg, run):
    """CMV-ANI-01: пульсация дальнего ореола — период 3–5 s, разнесённые
    фазы, малая амплитуда, геометрия стабильна. Ряд ≥6 s по fx-канвасу
    + реальные кадры с шагом 1 s."""
    rid = "CMV-ANI-01"
    run.attach_console(pg, rid)
    settle(pg)
    # обзорный зум: у хабов дальний ореол 2.65×g (g = min(nodeR, 16) ≤ 16),
    # полоса замера [1.1g, 2.3g] через r_t = 0.75×g; вокруг цели не должно
    # быть чужого ядра в радиусе ореола (thr_px = 2.65×g + 14)
    camera_to(pg, TARGET_ID, ratio=1.6)
    plan = pg.evaluate(JS_PULSE_PLAN)
    run.fact(rid, "pulse_plan_meta", {
        "planSize": len(plan.get("plan") or []),
        "motion": plan.get("motion"), "lod": plan.get("lod")})
    ids = [e["id"] for e in plan.get("plan") or []]
    cand_all, by_id = plan_spaced_targets(pg, plan, need=5)
    good = [c for c in cand_all if c["ok"]]
    chosen = good if len(good) >= 3 else cand_all[:5]
    targets = []
    for s in chosen:
        e = by_id.get(s["id"])
        if not e:
            continue
        targets.append({"id": s["id"], "period": e["period"],
                        "phase": e["phase"], "amp": e["amp"],
                        "sx": s["sx"], "sy": s["sy"],
                        "r": round(s["r"] * 0.85, 1),
                        "dmin": s["dmin"], "thr": s["thr"],
                        "haloClean": s["ok"]})
        if len(targets) >= 5:
            break
    per_all = [x["period"] for x in (plan.get("plan") or [])]
    ph_all = [x["phase"] for x in (plan.get("plan") or [])]
    dph = max(ph_all) - min(ph_all) if ph_all else 0
    run.fact(rid, "band_meta", {"candidates": len(cand_all),
                                "haloClean": len(good),
                                "planSpread": {
                                    "n": len(per_all),
                                    "periodMin": min(per_all) if per_all else None,
                                    "periodMax": max(per_all) if per_all else None,
                                    "phaseSpreadMs": dph},
                                "note": "diff-ряд сокращает статичных "
                                        "соседей; ok = нет другого "
                                        "пульсирующего узла в радиусе "
                                        "ореола"})
    run.fact(rid, "targets", [{k: t[k] for k in
                               ("id", "period", "phase", "amp")}
                              for t in targets])
    if len(targets) < 3:
        run.err(rid, "видимых узлов пульса < 3: %d" % len(targets))
    series = pg.evaluate(JS_SAMPLE_SERIES, {
        "targets": targets, "intervalMs": 100, "count": 85})
    est = {}
    for i, t in enumerate(targets):
        xds = [(s["t"], s["diff"]) for s in series["series"][i]["samples"]
               if s and s.get("diff") is not None]
        acd = estimate_period_phase(
            [{"t": a, "ring": b} for a, b in xds], key="ring")
        xs = [(s["t"], s["ring"]) for s in series["series"][i]["samples"]
              if s and s.get("ring") is not None]
        ac = autocorr_period(xs)
        per_meas = acd.get("period") or ac.get("period")
        fold_t = per_meas or t["period"]
        e = analyze_pulse(series["series"][i]["samples"],
                          fold_t, t["phase"])
        e["expectedPeriod"] = t["period"]
        e["diffWave"] = acd
        e["autocorr"] = ac
        if per_meas:
            e["periodMeasured"] = per_meas
            e["periodMatch"] = bool(abs(per_meas - t["period"]) <= 600)
        # фаза на план-периоде, если измеренный период сошёлся с планом
        if per_meas and abs(per_meas - t["period"]) <= 600:
            fold2 = analyze_pulse(series["series"][i]["samples"],
                                  t["period"], t["phase"])
            e["phaseMeasured"] = fold2.get("phaseMeasured")
            e["phaseExpected"] = t["phase"]
            e["phaseDelta"] = fold2.get("phaseDelta")
        est[t["id"]] = e
    run.fact(rid, "series_meta", {"count": 85, "intervalMs": 100,
                                  "windowMs": 8500})
    run.fact(rid, "estimates", est)
    with open(os.path.join(OUT, rid, "pulse-series.json"), "w",
              encoding="utf-8") as f:
        json.dump({"targets": targets, "series": series["series"],
                   "estimates": est}, f, ensure_ascii=False, indent=1)
    # filmstrip: 12 кадров fx-канваса вокруг первого узла (шаг 500 ms,
    # окно 6 s ≈ 1.5–2 цикла пульса) — наглядное дыхание ореола
    if targets:
        strip = pg.evaluate("""(spec) => new Promise((resolve) => {
          const vm = window.__adminbotVm;
          const scene = vm._cogScene;
          if (!scene || !scene.fxCanvas) { resolve(null); return; }
          const dpr = scene.fxDpr || 1;
          const cx = Math.round(spec.sx * dpr), cy = Math.round(spec.sy * dpr);
          const rr = Math.round((spec.r || 10) * 1.5 * dpr) * 2;
          const x0 = Math.max(0, cx - rr), y0 = Math.max(0, cy - rr);
          const sw = Math.min(scene.fxCanvas.width - x0, rr * 2);
          const sh = Math.min(scene.fxCanvas.height - y0, rr * 2);
          const strip = document.createElement('canvas');
          strip.width = sw * spec.frames;
          strip.height = sh;
          const ctx = strip.getContext('2d');
          ctx.fillStyle = '#05070d';
          ctx.fillRect(0, 0, strip.width, strip.height);
          let i = 0;
          const step = () => {
            ctx.drawImage(scene.fxCanvas, x0, y0, sw, sh,
                          i * sw, 0, sw, sh);
            ctx.strokeStyle = 'rgba(120,170,255,0.35)';
            ctx.strokeRect(i * sw + 0.5, 0.5, sw - 1, sh - 1);
            i += 1;
            if (i < spec.frames) setTimeout(step, spec.gapMs);
            else resolve(strip.toDataURL('image/png'));
          };
          step();
        })""", {"sx": targets[0]["sx"], "sy": targets[0]["sy"],
                "r": min(targets[0]["r"], 16), "frames": 12,
                "gapMs": 500})
        import base64 as _b64
        if strip and strip.startswith("data:image/png;base64,"):
            with open(os.path.join(OUT, rid, "pulse-filmstrip.png"), "wb") as fh:
                fh.write(_b64.b64decode(strip.split(",", 1)[1]))
            run.fact(rid, "filmstrip", {"node": targets[0]["id"],
                                        "frames": 12, "gapMs": 500,
                                        "file": "pulse-filmstrip.png"})
    for i in range(8):
        run.shot(pg, rid, "pulse-frame-%02d-1440" % i,
                 selector="[data-cog-map]")
        pg.wait_for_timeout(1000)
    run.fact(rid, "counters", pg.evaluate(JS_COUNT))
    # mobile 390: короткая серия 4 s + кадр
    pg.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
    pg.wait_for_timeout(2500)
    settle(pg, 60000)
    camera_to(pg, TARGET_ID, ratio=1.6)
    plan_m = pg.evaluate(JS_PULSE_PLAN)
    cand_m, by_id_m = plan_spaced_targets(pg, plan_m, need=3)
    good_m = [c for c in cand_m if c["ok"]]
    chosen_m = good_m if len(good_m) >= 2 else cand_m[:3]
    targets_m = []
    for s in chosen_m:
        e = by_id_m.get(s["id"])
        if not e:
            continue
        targets_m.append({"id": s["id"], "period": e["period"],
                          "phase": e["phase"], "sx": s["sx"], "sy": s["sy"],
                          "r": round(s["r"] * 0.85, 1)})
        if len(targets_m) >= 3:
            break
    run.fact(rid, "mobile_targets", [{k: t[k] for k in
                                      ("id", "period", "phase")}
                                     for t in targets_m])
    if targets_m:
        sm = pg.evaluate(JS_SAMPLE_SERIES, {
            "targets": targets_m, "intervalMs": 100, "count": 60})
        est_m = {t["id"]: analyze_pulse(sm["series"][i]["samples"],
                                        t["period"], t["phase"])
                 for i, t in enumerate(targets_m)}
        run.fact(rid, "mobile_estimates", est_m)
        with open(os.path.join(OUT, rid, "pulse-series-mobile.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"targets": targets_m, "series": sm["series"],
                       "estimates": est_m}, f, ensure_ascii=False, indent=1)
    run.shot(pg, rid, "pulse-mobile-390", selector="[data-cog-map]")
    run.fact(rid, "counters_mobile", pg.evaluate(JS_COUNT))
    pg.set_viewport_size({"width": DESKTOP[0], "height": DESKTOP[1]})
    pg.wait_for_timeout(2000)


def run_phy03(pg, run, stats):
    """CMV-PHY-03: drag по пустоте — панорама; drag узла — перемещение;
    локальная стабилизация без перезапуска layout; БД не меняется."""
    rid = "CMV-PHY-03"
    run.attach_console(pg, rid)
    settle(pg)
    camera_to(pg, TARGET_ID, ratio=1.8)
    # ── A: drag по пустоте → панорама
    spot = empty_spot(pg)
    run.fact(rid, "empty_spot", spot)
    cam0 = pg.evaluate(JS_CAMERA)
    run.shot(pg, rid, "pan-before-1440", selector="[data-cog-map]")
    stats["count"] = 0
    pg.mouse.move(spot["x"], spot["y"])
    pg.wait_for_timeout(120)
    pg.mouse.down()
    for i in range(1, 9):
        pg.mouse.move(spot["x"] + i * 15, spot["y"] + i * 8)
        pg.wait_for_timeout(40)
    pg.mouse.up()
    pg.wait_for_timeout(800)
    cam1 = pg.evaluate(JS_CAMERA)
    api_pan = stats["count"]
    run.fact(rid, "pan", {"camBefore": cam0, "camAfter": cam1,
                          "apiCalls": api_pan})
    run.shot(pg, rid, "pan-after-1440", selector="[data-cog-map]")
    # ── B: drag узла → перемещение, локальная стабилизация
    pos_before = pg.evaluate(JS_SCENE_POS)
    ns = node_screen(pg, TARGET_ID)
    run.fact(rid, "drag_node", {"id": TARGET_ID, "screen": ns})
    if ns:
        stats["count"] = 0
        pg.mouse.move(ns["x"], ns["y"])
        pg.wait_for_timeout(150)
        pg.mouse.down()
        for i in range(1, 9):
            pg.mouse.move(ns["x"] + i * 10, ns["y"] - i * 6)
            pg.wait_for_timeout(40)
        pg.mouse.up()
        timeline = positions_timeline(pg, 14, 200)
        pg.wait_for_timeout(400)
        pos_after = pg.evaluate(JS_SCENE_POS)
        cam2 = pg.evaluate(JS_CAMERA)
        api_drag = stats["count"]
        deltas_all = []
        for k, p0 in pos_before.items():
            p1 = pos_after.get(k)
            if not p1:
                continue
            d = ((p1["x"] - p0["x"]) ** 2 + (p1["y"] - p0["y"]) ** 2) ** 0.5
            deltas_all.append((k, round(d, 2)))
        deltas_all.sort(key=lambda kv: -kv[1])
        d_node = dict(deltas_all).get(TARGET_ID)
        others = [d for k, d in deltas_all if k != TARGET_ID]
        run.fact(rid, "nodedrag", {
            "camAfter": cam2, "apiCalls": api_drag,
            "draggedDelta": d_node,
            "othersOver10px": sum(1 for d in others if d > 10),
            "othersTotal": len(others),
            "othersMedian": round(statistics.median(others), 2)
            if others else None,
            "topDeltas": deltas_all[:8],
            "fitScaleStable": cam2["fitScale"] == cam0["fitScale"]})
        run.fact(rid, "positions_timeline_meta", {
            "snapshots": len(timeline or []),
            "note": "полный ряд pos в artifact positions-timeline.json"})
        with open(os.path.join(OUT, rid, "positions-timeline.json"), "w",
                  encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False)
        run.shot(pg, rid, "nodedrag-after-1440", selector="[data-cog-map]")
        run.fact(rid, "model_unchanged", {
            "targetTitle": pg.evaluate(JS_NODE_INFO, TARGET_ID),
            "apiCallsTotal": api_pan + api_drag})
    run.fact(rid, "counters", pg.evaluate(JS_COUNT))
    camera_to(pg, TARGET_ID, ratio=1.8)


def run_phy04(pg, run):
    """CMV-PHY-04: wheel-зум к курсору; двойной клик — плавный фокус
    350–500 ms с easing; ручной жест немедленно возвращает управление;
    pinch — попытка CDP touch (честная оговорка, если не воспроизводится)."""
    rid = "CMV-PHY-04"
    run.attach_console(pg, rid)
    settle(pg)
    camera_to(pg, TARGET_ID, ratio=1.4)
    # ── A: wheel к курсору (точка на фиксированных долях канваса, трасса)
    spot = pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      const canvas = (vm._cogEl
        || document.querySelector('.cognition-graph'))
        .querySelector('canvas');
      const box = canvas.getBoundingClientRect();
      return { x: box.left + canvas.clientWidth * 0.72,
               y: box.top + canvas.clientHeight * 0.32 };
    }""")
    world0 = world_at_screen(pg, spot["x"], spot["y"])
    run.shot(pg, rid, "wheel-before-1440", selector="[data-cog-map]")
    pg.mouse.move(spot["x"], spot["y"])
    pg.wait_for_timeout(150)
    trace = [dict(pg.evaluate(JS_CAMERA), t=0)]
    pg.mouse.wheel(0, -240)
    for i in range(1, 6):
        pg.wait_for_timeout(60)
        c = pg.evaluate(JS_CAMERA)
        c["t"] = i * 60
        trace.append(c)
    pg.wait_for_timeout(600)
    trace.append(dict(pg.evaluate(JS_CAMERA), t=960))
    world1 = world_at_screen(pg, spot["x"], spot["y"])
    drift_px = None
    if world1 and world0:
        drift_px = round(((world1["wx"] - world0["wx"]) ** 2
                          + (world1["wy"] - world0["wy"]) ** 2) ** 0.5
                         * world1["scale"], 2)
    scale_step = round(trace[1]["scale"] / trace[0]["scale"], 4) \
        if len(trace) > 1 and trace[0]["scale"] else None
    run.fact(rid, "wheel_zoom_at_cursor", {
        "spot": spot, "worldBefore": world0, "worldAfter": world1,
        "cursorDriftPx": drift_px, "scaleStep1": scale_step,
        "trace": trace})
    run.shot(pg, rid, "wheel-after-1440", selector="[data-cog-map]")
    camera_to(pg, TARGET_ID, ratio=1.4)
    # ── B: двойной клик по узлу → плавный фокус 350–500 ms (замер с rAF-
    #    сэмплером, взведённым ДО реального dblclick)
    ns = node_screen(pg, TARGET_ID)
    if ns:
        cam0 = pg.evaluate(JS_CAMERA)
        handle = pg.evaluate_handle(JS_CAMERA_TIMELINE, {"ms": 1200})
        pg.mouse.dblclick(ns["x"], ns["y"])
        tl = handle.json_value()
        cam1 = pg.evaluate(JS_CAMERA)
        moved = [a for a in (tl or []) if a["t"] > 60]
        run.fact(rid, "dblclick", {
            "camBefore": cam0, "camAfter": cam1,
            "movedFrames": len(moved),
            "firstMoveAt": moved[0]["t"] if moved else None,
            "lastMoveAt": moved[-1]["t"] if moved else None,
            "timeline": (tl or [])[-10:]})
        run.shot(pg, rid, "dblclick-after-1440", selector="[data-cog-map]")
    camera_to(pg, TARGET_ID, ratio=1.6)
    # ── C: поиск-анимация + wheel поверх: управление немедленно у жеста
    # (поллинг камеры из Python — rAF-сэмплер в анимации ненадёжен)
    inp = pg.locator("[data-cog-map] .graph-search__input").first
    inp.fill("")
    inp.fill("кофе 184")
    pg.wait_for_timeout(200)
    trace = []
    t0 = time.time()
    inp.press("Enter")
    for i in range(11):   # 0..1000 ms шаг ~100 ms
        c = pg.evaluate(JS_CAMERA)
        c["t"] = round((time.time() - t0) * 1000)
        trace.append(c)
        if i == 1:
            pg.mouse.move(720, 450)
            pg.mouse.wheel(0, -300)   # ручной жест поверх анимации
        pg.wait_for_timeout(90)
    pg.wait_for_timeout(600)
    trace.append(dict(pg.evaluate(JS_CAMERA),
                      t=round((time.time() - t0) * 1000)))
    st = pg.evaluate(JS_SEARCH_STATE)
    cam_end = pg.evaluate(JS_CAMERA)
    fit = cam_end.get("fitScale") or 0
    target_scale = round(fit * 3, 5) if fit else None
    reached_target = bool(target_scale
                          and abs(cam_end["scale"] - target_scale) < 1e-3)
    run.fact(rid, "gesture_override", {
        "searchState": st, "camEnd": cam_end,
        "animTargetScale": target_scale,
        "reachedAnimTarget": reached_target,
        "trace": trace,
        "note": "wheel на ~180-200 мс поверх анимации фокуса поиска; "
                "если кривая монотонно дошла до цели анимации без ступени "
                "от колеса — жест не перехватывает управление мгновенно"})
    inp.fill("")
    pg.wait_for_timeout(400)
    # ── D: pinch (CDP touch) — честная попытка + якорь жеста
    pinch = {}
    try:
        sess = pg.context.new_cdp_session(pg)
        center = node_screen(pg, TARGET_ID) or spot
        cx, cy = int(center["x"]), int(center["y"])
        cam_p0 = pg.evaluate(JS_CAMERA)
        w_c0 = world_at_screen(pg, cx, cy)
        scale0 = cam_p0["scale"]
        sess.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": cx - 50, "y": cy, "id": 1},
                            {"x": cx + 50, "y": cy, "id": 2}]})
        for i in range(1, 7):
            sess.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": cx - 50 - i * 10, "y": cy, "id": 1},
                                {"x": cx + 50 + i * 10, "y": cy, "id": 2}]})
            pg.wait_for_timeout(30)
        sess.send("Input.dispatchTouchEvent",
                  {"type": "touchEnd", "touchPoints": []})
        pg.wait_for_timeout(800)
        cam_p1 = pg.evaluate(JS_CAMERA)
        w_c1 = world_at_screen(pg, cx, cy)
        scale1 = cam_p1["scale"]
        anchor = round(((w_c1["wx"] - w_c0["wx"]) ** 2
                        + (w_c1["wy"] - w_c0["wy"]) ** 2) ** 0.5
                       * w_c1["scale"], 2) if (w_c0 and w_c1) else None
        pinch = {"scaleBefore": +scale0, "scaleAfter": +scale1,
                 "zoomed": bool(abs(scale1 - scale0) > 1e-4),
                 "camBefore": cam_p0, "camAfter": cam_p1,
                 "worldAtGestureCenterBefore": w_c0,
                 "worldAtGestureCenterAfter": w_c1,
                 "anchorDriftPx": anchor}
    except Exception as e:  # noqa: BLE001
        pinch = {"error": str(e)[:160]}
    run.fact(rid, "pinch_cdp", pinch)
    run.fact(rid, "counters", pg.evaluate(JS_COUNT))
    camera_to(pg, TARGET_ID, ratio=1.8)


def run_ai01(pg, run):
    """CMV-AI-01: hover — усиление свечения (требование: рампа 150–220 ms),
    соседние связи и подписи, курсор; затухание при уходе."""
    rid = "CMV-AI-01"
    run.attach_console(pg, rid)
    settle(pg)
    camera_to(pg, TARGET_ID, ratio=1.8)
    pg.evaluate(JS_CLEAR_SEL)
    pg.wait_for_timeout(300)
    plan = pg.evaluate(JS_PULSE_PLAN)
    ids = [e["id"] for e in plan.get("plan") or []]
    cand = spaced_visible_nodes(pg, ids, need=2, min_fill=2.2)
    hover_id = cand[0]["id"] if cand else None
    if not hover_id:
        hover_id = TARGET_ID
    ns = node_screen(pg, hover_id)
    if cand:
        run.fact(rid, "hover_spacing", {c["id"]: {"dmin": c["dmin"],
                                                  "thr": c["thr"]}
                                        for c in cand})
    run.fact(rid, "hover_node", {"id": hover_id, "screen": ns})
    st0 = pg.evaluate(JS_SCENE_STATE)
    run.fact(rid, "before", {"cursor": st0.get("cursor"),
                             "hoverId": st0.get("hoverId"),
                             "labelsShown": st0.get("labelsShown"),
                             "activeEdges": (st0.get("fxCounters")
                                             or {}).get("activeEdges")})
    g_h = min(ns["nodeR"], 16.0)
    box_target = [
        {"id": hover_id + "|inner", "sx": ns["sx"], "sy": ns["sy"],
         "r": round(g_h * 0.45, 1)},
        {"id": hover_id + "|outer", "sx": ns["sx"], "sy": ns["sy"],
         "r": round(g_h * 0.9, 1)},
    ]
    run.fact(rid, "band_meta", {"g": g_h,
                                "inner": "[0.68g, 1.35g]",
                                "outer": "[1.35g, 2.7g] — зона активного ореола"})
    base_series = pg.evaluate(JS_SAMPLE_SERIES, {
        "targets": box_target, "intervalMs": 100, "count": 5})
    # сэмплер взводится ДО реального hover (мышь идёт сразу после взвода)
    handle = pg.evaluate_handle(JS_SAMPLE_SERIES, {
        "targets": box_target, "intervalMs": 40, "count": 14})
    pg.mouse.move(ns["x"], ns["y"])
    ramp = handle.json_value()
    pg.wait_for_timeout(150)
    st1 = pg.evaluate(JS_SCENE_STATE)
    st1["hoverHit"] = (st1.get("hoverId") == hover_id)
    run.fact(rid, "hover_state", st1)
    run.shot(pg, rid, "hover-peak-1440", selector="[data-cog-map]")
    spot = empty_spot(pg)
    handle2 = pg.evaluate_handle(JS_SAMPLE_SERIES, {
        "targets": box_target, "intervalMs": 40, "count": 12})
    pg.mouse.move(spot["x"], spot["y"])
    decay = handle2.json_value()
    st2 = pg.evaluate(JS_SCENE_STATE)
    run.fact(rid, "after_leave", {"cursor": st2.get("cursor"),
                                  "hoverId": st2.get("hoverId"),
                                  "labelsShown": st2.get("labelsShown")})
    run.fact(rid, "series", {
        "baseline": base_series["series"],
        "ramp": ramp["series"],
        "decay": decay["series"]})
    # анализ по OUTER-полосе (кольцо активного ореола) + diff против опоры
    def _vals(series_entry, key="ring"):
        return [s.get(key) for s in series_entry["samples"]
                if s and s.get(key) is not None]
    vals = _vals(ramp["series"][1])
    bl = _vals(base_series["series"][1])
    dvals_r = _vals(ramp["series"][1], "diff")
    dvals_d = _vals(decay["series"][1], "diff")
    dvals_b = _vals(base_series["series"][1], "diff")
    # onset: первый момент, когда diff уверенно превышает фоновый уровень
    onset = None
    db_mean = statistics.mean(dvals_b) if dvals_b else 0.0
    for s in ramp["series"][1]["samples"]:
        if s and s.get("diff") is not None \
                and s["diff"] > db_mean + 0.15:
            onset = s["t"]
            break
    if vals and bl:
        b = statistics.mean(bl)
        final = statistics.mean(vals[-4:])
        peak = max(vals)
        t90 = None
        for s in ramp["series"][1]["samples"]:
            if s and s.get("ring") is not None:
                if s["ring"] >= b + 0.9 * (final - b):
                    t90 = s["t"]
                    break
        run.fact(rid, "ramp_numbers", {
            "band": "outer[1.35g,2.7g]", "baseline": round(b, 2),
            "final": round(final, 2), "peak": round(peak, 2),
            "t90ms": t90,
            "deltaPct": round((final - b) / max(1.0, b) * 100, 1),
            "deltaAbs": round(final - b, 2),
            "diffDuringRamp": {
                "max": round(max(dvals_r), 2) if dvals_r else None,
                "last": round(dvals_r[-1], 2) if dvals_r else None},
            "diffBaseline": round(statistics.mean(dvals_b), 2)
            if dvals_b else None,
            "onsetMs": onset,
            "note": "ramp измеряется по плато diff (свечение против "
                    "опорного кадра); ожидание ТЗ — 150-220 ms",
            "diffAfterLeave": {
                "max": round(max(dvals_d), 2) if dvals_d else None,
                "last": round(dvals_d[-1], 2) if dvals_d else None},
            "innerBand": {
                "baseline": round(statistics.mean(_vals(
                    base_series["series"][0]) or [0]), 2),
                "final": round(statistics.mean(_vals(
                    ramp["series"][0])[-4:] or [0]), 2)}})
    dvals = _vals(decay["series"][1])
    if dvals and bl:
        b = statistics.mean(bl)
        run.fact(rid, "decay_numbers", {
            "first": dvals[0], "last": dvals[-1],
            "absLastMinusBase": round(abs(dvals[-1] - b), 2)})
    with open(os.path.join(OUT, rid, "hover-series.json"), "w",
              encoding="utf-8") as f:
        json.dump({"baseline": base_series["series"],
                   "ramp": ramp["series"], "decay": decay["series"]},
                  f, ensure_ascii=False, indent=1)
    run.fact(rid, "counters", pg.evaluate(JS_COUNT))
    pg.wait_for_timeout(300)


def run_ai02(pg, run):
    """CMV-AI-02: клик — один короткий световой импульс, соседи подсвечены,
    остальные ослаблены, инспектор показывает сведения."""
    rid = "CMV-AI-02"
    run.attach_console(pg, rid)
    settle(pg)
    camera_to(pg, TARGET_ID, ratio=1.6)
    pg.evaluate(JS_CLEAR_SEL)
    pg.wait_for_timeout(400)
    plan = pg.evaluate(JS_PULSE_PLAN)
    ids = [e["id"] for e in plan.get("plan") or []]
    cand = spaced_visible_nodes(pg, ids, need=3, min_fill=2.4)
    click_id = cand[0]["id"] if cand else TARGET_ID
    ns = node_screen(pg, click_id)
    if cand:
        run.fact(rid, "click_spacing", {c["id"]: {"dmin": c["dmin"],
                                                  "thr": c["thr"]}
                                        for c in cand})
    run.fact(rid, "click_node", {"id": click_id, "screen": ns})
    # далёкий узел для проверки ослабления (dim) после выбора — из ВИДИМЫХ
    far_id = pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      const scene = vm._cogScene;
      const net = vm.cognitionNetwork;
      const el = vm._cogEl || document.querySelector('.cognition-graph');
      const canvas = el.querySelector('canvas');
      const box = canvas.getBoundingClientRect();
      const cam = net.getViewPosition(), sc = net.getScale();
      const W = canvas.clientWidth, H = canvas.clientHeight;
      const pos = scene ? (scene.pos || {}) : {};
      let best = null, bd = -1;
      for (const k in pos) {
        const p = pos[k];
        const sx = (p.x - cam.x) * sc + W / 2;
        const sy = (p.y - cam.y) * sc + H / 2;
        if (sx < 80 || sy < 80 || sx > W - 80 || sy > H - 80) continue;
        const dx = sx - (%f), dy = sy - (%f);
        const d = dx * dx + dy * dy;
        if (d > bd) { bd = d; best = k; }
      }
      return best;
    }""" % (ns["sx"], ns["sy"]))
    far_proj = pg.evaluate(JS_PROJECT, far_id) if far_id else None
    far_before = None
    if far_proj and far_proj.get("inViewport"):
        far_before = pg.evaluate(JS_SAMPLE_SERIES, {
            "targets": [{"id": far_id, "sx": far_proj["sx"],
                         "sy": far_proj["sy"],
                         "r": round(min(far_proj["nodeR"], 16) * 0.9, 1)}],
            "intervalMs": 100, "count": 3})
    st0 = pg.evaluate(JS_SCENE_STATE)
    run.fact(rid, "before", {"selectedId": st0.get("selectedId"),
                             "activeEdges": (st0.get("fxCounters")
                                             or {}).get("activeEdges"),
                             "cardOpen": st0.get("cardOpen")})
    g_c = min(ns["nodeR"], 16.0)
    box_target = [
        {"id": click_id + "|inner", "sx": ns["sx"], "sy": ns["sy"],
         "r": round(g_c * 0.45, 1)},
        {"id": click_id + "|outer", "sx": ns["sx"], "sy": ns["sy"],
         "r": round(g_c * 0.9, 1)},
    ]
    # сэмплер взводится ДО реального клика (клик мыши сразу после взвода)
    handle = pg.evaluate_handle(JS_SAMPLE_SERIES, {
        "targets": box_target, "intervalMs": 50, "count": 16})
    pg.mouse.click(ns["x"], ns["y"])
    pulse = handle.json_value()
    pg.wait_for_timeout(200)
    st1 = pg.evaluate(JS_SCENE_STATE)
    st1["clickHit"] = (st1.get("selectedId") == click_id)
    # далёкий узел после выбора: ослаблен ли (dim)
    far_after = None
    if far_id:
        far_proj2 = pg.evaluate(JS_PROJECT, far_id)
        if far_proj2 and far_proj2.get("inViewport"):
            far_after = pg.evaluate(JS_SAMPLE_SERIES, {
                "targets": [{"id": far_id, "sx": far_proj2["sx"],
                             "sy": far_proj2["sy"],
                             "r": round(min(far_proj2["nodeR"], 16) * 0.9,
                                        1)}],
                "intervalMs": 100, "count": 3})
    if far_before and far_after:
        lb = [s["ring"] for s in far_before["series"][0]["samples"]
              if s and s.get("ring") is not None]
        la = [s["ring"] for s in far_after["series"][0]["samples"]
              if s and s.get("ring") is not None]
        if lb and la:
            run.fact(rid, "far_node_dim", {
                "farId": far_id,
                "lumaBefore": round(statistics.mean(lb), 2),
                "lumaAfter": round(statistics.mean(la), 2),
                "dimmed": statistics.mean(la) < statistics.mean(lb) - 1.0})
    if not st1["clickHit"]:
        # повтор на втором разреженном кандидате (тот же реальный клик);
        # перед повтором — заново стазис и свежие координаты
        pg.evaluate(JS_CLEAR_SEL)
        pg.wait_for_timeout(400)
        wait_positions_stable(pg)
        if len(cand) > 1:
            click_id2 = cand[1]["id"]
            ns2 = node_screen(pg, click_id2)
        else:
            click_id2 = click_id
            ns2 = node_screen(pg, click_id2)
        if ns2:
            box_target = [
                {"id": click_id2 + "|inner", "sx": ns2["sx"], "sy": ns2["sy"],
                 "r": round(ns2["nodeR"] * 0.5, 1)},
                {"id": click_id2 + "|outer", "sx": ns2["sx"], "sy": ns2["sy"],
                 "r": round(ns2["nodeR"] * 1.0, 1)},
            ]
            handle = pg.evaluate_handle(JS_SAMPLE_SERIES, {
                "targets": box_target, "intervalMs": 50, "count": 16})
            pg.mouse.click(ns2["x"], ns2["y"])
            pulse = handle.json_value()
            pg.wait_for_timeout(200)
            st1 = pg.evaluate(JS_SCENE_STATE)
            st1["clickHit"] = (st1.get("selectedId") == click_id2)
            ns = ns2
            click_id = click_id2
        if not st1.get("clickHit"):
            # честный фолбэк: выбор + пульс продукт-методами без движения
            # камеры (реальный клик не попал — фиксируется в отчёте)
            pg.evaluate(JS_SELECT, click_id)
            pg.evaluate("""(id) => window.__adminbotVm
                           ._cogPulseSelected('click', id)""", click_id)
            pg.wait_for_timeout(150)
            st1 = pg.evaluate(JS_SCENE_STATE)
            st1["clickHit"] = False
            st1["selectionViaApiFallback"] = True
    run.fact(rid, "after_click", {"scene": st1})
    run.shot(pg, rid, "click-pulse-1440", selector="[data-cog-map]")
    vals = [s["ring"] for s in pulse["series"][1]["samples"]
            if s and s.get("ring") is not None]
    if vals:
        base = statistics.mean(vals[:2])
        peak = max(vals)
        thr = base + 0.6 * (peak - base)
        peaks = []
        for i in range(1, len(vals) - 1):
            if vals[i] > vals[i - 1] and vals[i] >= vals[i + 1] \
                    and vals[i] > thr:
                if peaks and (i - peaks[-1]) < 3:
                    continue
                peaks.append(i)
        run.fact(rid, "pulse_numbers", {
            "band": "outer[1.5r,3r]",
            "series": vals, "base": round(base, 2), "peak": round(peak, 2),
            "peaksAbove60": len(peaks),
            "innerBand": [s["ring"] for s in pulse["series"][0]["samples"]
                          if s and s.get("ring") is not None],
            "pulseHit": st1.get("pulseHit")})
    with open(os.path.join(OUT, rid, "click-series.json"), "w",
              encoding="utf-8") as f:
        json.dump(pulse["series"], f, ensure_ascii=False, indent=1)
    run.fact(rid, "counters", pg.evaluate(JS_COUNT))
    pg.evaluate(JS_CLEAR_SEL)
    pg.wait_for_timeout(300)


def run_ai03(pg, run, mobile=False):
    """CMV-AI-03: поиск — плавный фокус камеры, 1–2 мягких пульса найденного
    узла, остаётся выделенным."""
    rid = "CMV-AI-03"
    run.attach_console(pg, rid)
    settle(pg, 90000)
    tag = "mobile390" if mobile else "desktop1440"
    # камеру уводим в сторону, чтобы фокус был заметен
    pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      const cache = (vm._cogScene && vm._cogScene.pos)
        || net.getPositions() || {};
      const keys = Object.keys(cache);
      const far = cache[keys[Math.min(40, keys.length - 1)]];
      net.moveTo({ position: far, scale: vm._cogFitScale * 0.7,
                   animation: false });
    }""")
    pg.wait_for_timeout(400)
    cam0 = pg.evaluate(JS_CAMERA)
    inp = pg.locator("[data-cog-map] .graph-search__input").first
    inp.fill("")
    inp.fill("кофе 184")
    pg.wait_for_timeout(200)
    handle = pg.evaluate_handle(JS_CAMERA_TIMELINE, {"ms": 1500})
    pg.wait_for_timeout(30)
    inp.press("Enter")
    pg.wait_for_timeout(700)
    st1 = pg.evaluate(JS_SEARCH_STATE)
    cam1 = pg.evaluate(JS_CAMERA)
    found = st1.get("matchIds") or []
    pulse_series = None
    pulse_est = None
    if found:
        fid = found[0]
        p = pg.evaluate(JS_PROJECT, fid)
        if p and p["inside"]:
            ser = pg.evaluate(JS_SAMPLE_SERIES, {
                "targets": [{"id": fid, "sx": p["sx"], "sy": p["sy"],
                             "r": round(p["nodeR"] * 0.85, 1)}],
                "intervalMs": 100, "count": 24})
            pulse_series = ser["series"][0]["samples"]
            vals = [s["ring"] for s in pulse_series
                    if s and s.get("ring") is not None]
            if vals:
                b = statistics.mean(vals[:3])
                peak = max(vals)
                thr = b + 0.5 * (peak - b)
                peaks = []
                for i in range(1, len(vals) - 1):
                    if vals[i] > vals[i - 1] and vals[i] >= vals[i + 1] \
                            and vals[i] > thr:
                        if peaks and (i - peaks[-1]) < 4:
                            continue
                        peaks.append(i)
                pulse_est = {"beats": len(peaks), "base": round(b, 2),
                             "peak": round(peak, 2),
                             "peakTimes": [pulse_series[i]["t"]
                                           for i in peaks]}
    pg.wait_for_timeout(2500)
    st_final = pg.evaluate(JS_SEARCH_STATE)
    cam2 = pg.evaluate(JS_CAMERA)
    moves = [a for a in (handle.json_value() or []) if a["t"] > 40]
    dur = (moves[-1]["t"] - moves[0]["t"]) if len(moves) >= 2 else None
    run.fact(rid, "focus_" + tag, {
        "camBefore": cam0, "camAfter": cam1, "camFinal": cam2,
        "animMoves": len(moves), "animDurationMs": dur,
        "animTail": moves[-5:],
        "search": st1, "pulse": pulse_est})
    run.fact(rid, "stays_selected_" + tag, {
        "selectedId": st_final.get("selectedId"),
        "matchIds": st_final.get("matchIds"),
        "detail": st_final.get("detail")})
    run.shot(pg, rid, "search-focused-" + tag, selector="[data-cog-map]")
    if pulse_series:
        with open(os.path.join(OUT, rid, "search-pulse-%s.json" % tag), "w",
                  encoding="utf-8") as f:
            json.dump(pulse_series, f, ensure_ascii=False, indent=1)
    run.fact(rid, "counters_" + tag, pg.evaluate(JS_COUNT))
    inp.fill("")
    pg.wait_for_timeout(400)
    pg.evaluate(JS_CLEAR_SEL)
    pg.wait_for_timeout(300)


def run_ai04(pg, run, stats):
    """CMV-AI-04: обновление данных без мерцания всей сцены и без повторной
    анимации входа всех узлов (реальный путь loadCognitionGraph)."""
    rid = "CMV-AI-04"
    run.attach_console(pg, rid)
    settle(pg)
    camera_to(pg, TARGET_ID, ratio=1.4)
    pos_before = pg.evaluate(JS_SCENE_POS)
    snap0 = pg.evaluate(JS_FX_SNAPSHOT)
    run.shot(pg, rid, "before-update-1440", selector="[data-cog-map]")
    st0 = pg.evaluate(JS_SCENE_STATE)
    stats["count"] = 0
    W15.set_cog_payload(fx702_plus_payload())
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    upd = pg.evaluate("""() => new Promise((resolve) => {
      const vm = window.__adminbotVm;
      const scene = vm && vm._cogScene;
      const out = [];
      const t0 = performance.now();
      let slot = 0;
      const step = () => {
        const now = performance.now() - t0;
        if (slot < 20 && now >= slot * 100) {
          let sc = null, vx = null, vy = null;
          try {
            const net = vm.cognitionNetwork;
            sc = +net.getScale().toFixed(4);
            const vp = net.getViewPosition();
            vx = +vp.x.toFixed(1); vy = +vp.y.toFixed(1);
          } catch (e) { /* уничтожена */ }
          out.push({ t: +now.toFixed(0), scale: sc, vx: vx, vy: vy,
                     frames: scene ? (scene.frames || 0) : null });
          slot += 1;
        }
        if (slot < 20) requestAnimationFrame(step);
        else resolve(out);
      };
      requestAnimationFrame(step);
    })""")
    pg.wait_for_timeout(1200)
    settle(pg, 90000)
    pos_after = pg.evaluate(JS_SCENE_POS)
    snap1 = pg.evaluate(JS_FX_SNAPSHOT)
    st1 = pg.evaluate(JS_SCENE_STATE)
    moved = []
    for k, p0 in pos_before.items():
        p1 = pos_after.get(k)
        if not p1:
            continue
        d = ((p1["x"] - p0["x"]) ** 2 + (p1["y"] - p0["y"]) ** 2) ** 0.5
        if d > 1.0:
            moved.append((k, round(d, 2)))
    new_node = pg.evaluate(JS_NODE_INFO, "ent:%d:901" % W15.COG_CHAT)
    run.fact(rid, "update", {
        "framesDuringUpdate": upd,
        "movedOldNodes": len(moved),
        "movedSample": moved[:6],
        "oldNodesTotal": len(pos_before),
        "newNodePresent": bool(new_node),
        "fxBefore": snap0, "fxAfter": snap1,
        "apiCalls": stats["count"]})
    run.fact(rid, "scene_states", {"before": st0, "after": st1})
    run.shot(pg, rid, "after-update-1440", selector="[data-cog-map]")
    run.fact(rid, "counters", pg.evaluate(JS_COUNT))
    W15.set_cog_payload(fx702_payload())
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    pg.wait_for_timeout(2000)
    settle(pg, 90000)


def run_perf05(pg, run, stats, mobile=False):
    """CMV-PERF-05: инициализация по фактическому открытию виджета без
    блокировки загрузки; тяжёлые эффекты не запускаются на polling-тиках
    (реальные таймеры 15 s / 30 s); стабилизация завершается; CPU в покое
    не остаётся загруженным физикой."""
    rid = "CMV-PERF-05"
    run.attach_console(pg, rid)
    tag = "mobile390" if mobile else "desktop1440"
    tl = pg.evaluate(JS_PERF_TIMELINE)
    run.fact(rid, "load_timeline_" + tag, tl)
    settle(pg, 120000)
    st = pg.evaluate(JS_PERF_TIMELINE)
    run.fact(rid, "settled_" + tag, {"settled": st["settled"],
                                     "frames": st["frames"],
                                     "netCount": st["netCount"]})
    # покой 5 s
    rest1 = pg.evaluate(JS_FRAME_RATE, {"ms": 5000})
    run.fact(rid, "rest_5s_" + tag, rest1)
    # окно 17 s: содержит ровно один тик cognitionTimer (интервал 15 s)
    tick17 = pg.evaluate(JS_FRAME_RATE, {"ms": 17000})
    run.fact(rid, "window17s_" + tag, tick17)
    # окно 34 s: содержит тик statusTimer (30 s) и два тика cognition
    api0 = stats["count"]
    tick34 = pg.evaluate(JS_FRAME_RATE, {"ms": 34000})
    run.fact(rid, "window34s_" + tag, dict(tick34,
                                           apiCalls=stats["count"] - api0))
    # финальный покой 4 s
    rest2 = pg.evaluate(JS_FRAME_RATE, {"ms": 4000})
    run.fact(rid, "rest_after_polls_" + tag, rest2)
    run.fact(rid, "counters_" + tag, pg.evaluate(JS_COUNT))
    run.shot(pg, rid, "perf05-" + tag)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="ani1,phy3,phy4,ai01,ai02,ai03,ai04,"
                                      "perf05")
    args = ap.parse_args()
    rows = [r.strip().lower() for r in args.rows.split(",") if r.strip()]

    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    run = Run()
    exit_code = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--enable-gpu", "--enable-gpu-rasterization",
                      "--ignore-gpu-blocklist", "--use-angle=d3d11"])
            try:
                stats = {"count": 0, "last": ""}

                def new_page(viewport, dpr=1, touch=False):
                    ctx = browser.new_context(
                        viewport={"width": viewport[0],
                                  "height": viewport[1]},
                        device_scale_factor=dpr, is_mobile=touch,
                        has_touch=touch)
                    ctx.add_init_script(M.TMA_STUB)
                    ctx.add_init_script(INSTRUMENT_TIMELINE)
                    ctx.route("**/api/**", make_routes(stats))
                    page = ctx.new_page()
                    W15.set_cog_payload(fx702_payload())
                    page.goto(base + "#/", wait_until="load")
                    return page, ctx

                if "ani1" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_ani01(pg, run)
                    pg.close(); ctx.close()
                if "phy3" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_phy03(pg, run, stats)
                    pg.close(); ctx.close()
                if "phy4" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_phy04(pg, run)
                    pg.close(); ctx.close()
                if "ai01" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_ai01(pg, run)
                    pg.close(); ctx.close()
                if "ai02" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_ai02(pg, run)
                    pg.close(); ctx.close()
                if "ai03" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_ai03(pg, run, mobile=False)
                    pg.close(); ctx.close()
                    pg, ctx = new_page(MOBILE, dpr=2, touch=True)
                    run_ai03(pg, run, mobile=True)
                    pg.close(); ctx.close()
                if "ai04" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_ai04(pg, run, stats)
                    pg.close(); ctx.close()
                if "perf05" in rows:
                    pg, ctx = new_page(DESKTOP)
                    run_perf05(pg, run, stats, mobile=False)
                    pg.close(); ctx.close()
                    pg, ctx = new_page(MOBILE, dpr=2, touch=True)
                    run_perf05(pg, run, stats, mobile=True)
                    pg.close(); ctx.close()
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        exit_code = 3
    run.save_manifest(batch=3, branch="cmv/residual-evidence-3",
                      base_commit="df00f178")
    print("-> %s" % os.path.join(OUT, "manifest.json"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
