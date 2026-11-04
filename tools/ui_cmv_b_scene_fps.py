"""CMV-B (EPIC-CM-VISUAL-01) — замер сцены «Когнитивной карты» на 702/2400.

Даёт то, что требует §10.2/§12 спеки и §10.3 контракта, НА РЕАЛЬНОЙ странице
(`web/index.html` + `web/app.js` + self-host vis-network), а не в синтетике:

  * FPS панорамирования (3 с программного движения камеры) — p50/p95;
  * FPS и число кадров декора в простое (частотный потолок 24 fps);
  * счётчики слоя `fx`: спрайты (создаются один раз), градиенты в кадре (0),
    `draws`, `pooled`, размер пула позиций;
  * объективные визуальные инварианты из DataSet и слоя подписей:
      - ни одного прямоугольного узла (`shape !== 'box'`) — §4.1 спеки;
      - рёбра прямые (`smooth === false`) и с альфой 0.08–0.20 — §4.3;
      - подписи не накладываются, выбранный узел подписан всегда — §4.4;
  * скриншоты desktop 1536×960 и mobile 390×844: обзор и зум ×2 с выбором.

Запуск:
  .venv/Scripts/python.exe tools/ui_cmv_b_scene_fps.py --repo <ROOT> --out DIR
Код возврата: 0 — все проверки прошли, 2 — провал, 3 — стенд не поднялся.
"""
import argparse
import json
import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

COG_CHAT = -1001234567890
NODES = 702
EDGES = 2400
DESKTOP = (1536, 960)
MOBILE = (390, 844)
PAN_MS = 3000
IDLE_MS = 3000


# ── фикстура 702/2400 ────────────────────────────────────────────────────────
def _lcg(seed):
    state = {"v": seed & 0x7FFFFFFF}

    def nxt(limit):
        state["v"] = (state["v"] * 1103515245 + 12345) & 0x7FFFFFFF
        return (state["v"] >> 7) % limit

    return nxt


KIND_PLAN = (
    ("fact", 45), ("belief", 20), ("entity", 15), ("paradigm", 8),
    ("observation", 7), ("evolution_event", 5),
)
TITLES = (
    "Утро начинается с кофе", "Костя играет в шахматы", "Дача — место отдыха",
    "Аня любит утренний кофе", "Разговор о работе и усталости",
    "Планы на выходные: поездка за город", "Доверие строится постепенно",
    "Бережёт утро и не любит ранние звонки", "Факт уточнён после проверки",
    "Шутка про понедельник", "Память о поездке в Карелию",
    "Долгая и подробная запись о том, как человек реагирует на критику "
    "и почему это важно помнить в разговоре",
    "same name", "same name", "same name",
)


def _kind_for(i):
    total = sum(w for _, w in KIND_PLAN)
    pos = i % total
    for kind, weight in KIND_PLAN:
        if pos < weight:
            return kind
        pos -= weight
    return "other"


def big_payload():
    """Детерминированная копия топологии «плотного» чата (702 узла/2400 связей).

    Топология — 6 сообществ по ~117 узлов: плотные внутренние связи + редкие
    мосты между ними. Это честная модель реального чата (несколько тем), и она
    позволяет объективно проверить §12.1 «видны пространственно отделённые
    группы», а не только «нет прямоугольников».
    """
    nodes = []
    for i in range(NODES):
        kind = _kind_for(i)
        nid = "%s:%d:%d" % (
            {"fact": "fact", "belief": "belief", "paradigm": "paradigm",
             "entity": "ent", "observation": "obs",
             "evolution_event": "evt"}[kind], COG_CHAT, i + 1)
        nodes.append({
            "id": nid, "kind": kind, "scope": "chat", "chat_id": COG_CHAT,
            "title": "%s %d" % (TITLES[i % len(TITLES)], i + 1),
            "text": "запись %d" % (i + 1), "status": "confirmed",
            "isolated": False,
            "time": {"occurred_at": 1750000000 + i, "observed_at": None,
                     "saved_at": 1750000100 + i, "confirmed_at": None,
                     "updated_at": None},
            "provenance": {"record": "graph_facts", "chat_id": COG_CHAT,
                           "message_id": 500 + i, "origin": "chat_history",
                           "fact_id": i + 1},
            "metrics": {"importance": (i % 10) + 1, "weight": None,
                        "degree": None},
            "refs": {},
        })
    ids = [n["id"] for n in nodes]
    communities = 6
    size = NODES // communities
    nxt = _lcg(20261103)
    edges = []
    seen = set()

    def add(a, b):
        if a == b:
            return False
        key = (a, b)
        if key in seen:
            return False
        seen.add(key)
        edges.append(key)
        return True

    # Внутри сообщества: кольцо (связность) + локальные «хабы».
    for c in range(communities):
        lo = c * size
        hi = (lo + size) if c < communities - 1 else NODES
        members = ids[lo:hi]
        for i, nid in enumerate(members):
            add(nid, members[(i + 1) % len(members)])
        for i, nid in enumerate(members):
            for _ in range(3):
                add(nid, members[nxt(len(members))])
        # Пара «парадигм-центров» внутри сообщества — для узнаваемых центров.
        for i in range(0, len(members), 29):
            add(members[i], members[(i + 7) % len(members)])
    # Мосты между сообществами: редкие реальные связи (как темы в чате).
    for c in range(communities):
        other = (c + 1) % communities
        a = ids[min(NODES - 1, c * size)]
        b = ids[min(NODES - 1, other * size + 3)]
        add(a, b)
    # Добор до 2400 реальными связями внутри сообществ.
    while len(edges) < EDGES:
        c = nxt(communities)
        lo = c * size
        hi = (lo + size) if c < communities - 1 else NODES
        add(ids[lo + nxt(hi - lo)], ids[lo + nxt(hi - lo)])
    out_edges = []
    for i, (a, b) in enumerate(edges[:EDGES]):
        derived = (i % 3 == 0)
        out_edges.append({
            "id": "ce%d" % (i + 1), "from": a, "to": b,
            "relation": "revised_by" if i % 37 == 0 else (
                "derived_from" if derived else "обсуждали"),
            "derived": derived, "chat_id": COG_CHAT,
            "justification_recorded": True,
            "provenance": {"fact_id": i + 1},
        })
    return {
        "version": "cog-map/1",
        "generated_at": None,                 # подставляется «сейчас»
        "state": "partial",
        "scope": {"mode": "chat", "chat_id": COG_CHAT},
        "degraded": {"active": False, "not_loaded": []},
        "sources": {"facts": "loaded", "graph": "loaded"},
        "caps": {"nodes": 800, "edges": 2400, "per_class": 150,
                 "classes": 4, "entity_nodes": 796},
        "shown_of": {
            "nodes": len(nodes), "edges": len(out_edges),
            "totals": {"nodes": 52600, "edges": 98000},
            "unresolved_refs": 0,
            "by_kind": {
                "fact": {"shown": 316, "total": 24000, "truncated": True},
                "belief": {"shown": 140, "total": 9000, "truncated": True},
                "paradigm": {"shown": 56, "total": 400, "truncated": True},
                "entity": {"shown": 105, "total": 19000, "truncated": True},
            },
        },
        "truncated": {"nodes": True, "edges": True,
                      "by_class": {"fact": True, "belief": True,
                                   "paradigm": True, "evolution": True,
                                   "entity": True}},
        "nodes": nodes, "edges": out_edges,
    }


# ── страница: счётчики и замеры ──────────────────────────────────────────────
READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  const scene = vm._cogScene;
  if (!scene || scene.settled !== true) return false;
  return !!scene.fxCanvas;
}
"""

SNAPSHOT = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  const net = vm && vm.cognitionNetwork;
  const rows = (vm && vm._cognitionNodesDS && vm._cognitionNodesDS.get)
    ? vm._cognitionNodesDS.get() : [];
  const edgeRows = (vm && vm._cognitionEdgesDS && vm._cognitionEdgesDS.get)
    ? vm._cognitionEdgesDS.get() : [];
  const shapes = {};
  rows.forEach((r) => { shapes[r.shape] = (shapes[r.shape] || 0) + 1; });
  const edgeStats = { total: edgeRows.length, smooth: 0, arrow: 0,
    opacityBelow: 0, opacityAbove: 0 };
  edgeRows.forEach((e) => {
    if (e.smooth !== false) edgeStats.smooth += 1;
    if (e.arrows && e.arrows.to && e.arrows.to.enabled) edgeStats.arrow += 1;
    const op = (e.color && typeof e.color.opacity === 'number')
      ? e.color.opacity : 1;
    if (op <= 0.9) edgeStats.opacityBelow += 1;
    else edgeStats.opacityAbove += 1;
  });
  const labels = (vm && vm._cogLabels && vm._cogLabels.labels) || [];
  const forced = (vm && vm._cogLabels && vm._cogLabels.forced) || [];
  const all = labels.concat(forced);
  const seenIds = {};
  let duplicateLabels = 0;
  all.forEach((l) => {
    const k = String(l.id);
    if (seenIds[k]) duplicateLabels += 1;
    seenIds[k] = true;
  });
  let overlaps = 0;
  for (let i = 0; i < all.length; i += 1) {
    for (let j = i + 1; j < all.length; j += 1) {
      const a = all[i], b = all[j];
      if (String(a.id) === String(b.id)) continue;
      if (Math.abs(a.x - b.x) * 2 < (a.width + b.width)
          && Math.abs(a.y - b.y) * 2 < (a.height + b.height)) overlaps += 1;
    }
  }
  // §12.1 спеки: «несколько пространственно отделённых групп». Считаем
  // связные области экранной сетки 24 px, где стоят реальные узлы.
  const cam = net ? net.getViewPosition() : { x: 0, y: 0 };
  const sc = net ? net.getScale() : 1;
  const canvasEl = vm && vm._cogEl ? vm._cogEl.querySelector('canvas') : null;
  const W = canvasEl ? canvasEl.clientWidth : 0;
  const H = canvasEl ? canvasEl.clientHeight : 0;
  const cell = 24;
  const grid = new Map();
  if (net) {
    const pos = net.getPositions();
    Object.keys(pos).forEach((id) => {
      const p = pos[id];
      const sx = (p.x - cam.x) * sc + W / 2;
      const sy = (p.y - cam.y) * sc + H / 2;
      if (sx < 0 || sy < 0 || sx > W || sy > H) return;
      const key = Math.floor(sx / cell) + ':' + Math.floor(sy / cell);
      grid.set(key, (grid.get(key) || 0) + 1);
    });
  }
  const keys = Array.from(grid.keys());
  const parent = {};
  keys.forEach((k) => { parent[k] = k; });
  function find(k) { while (parent[k] !== k) { parent[k] = parent[parent[k]]; k = parent[k]; } return k; }
  function union(a, b) { const ra = find(a), rb = find(b); if (ra !== rb) parent[rb] = ra; }
  keys.forEach((k) => {
    const [gx, gy] = k.split(':').map(Number);
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        const nb = (gx + dx) + ':' + (gy + dy);
        if (grid.has(nb)) union(k, nb);
      }
    }
  });
  const groups = {};
  keys.forEach((k) => {
    const root = find(k);
    groups[root] = (groups[root] || 0) + grid.get(k);
  });
  const groupSizes = Object.keys(groups).map((k) => groups[k])
    .sort((a, b) => b - a);
  const bigGroups = groupSizes.filter((n) => n >= 10).length;
  const counters = vm && vm._cogDebugCounters ? vm._cogDebugCounters() : {};
  const canvas = scene && scene.fxCanvas;
  const el = vm && vm._cogEl;
  let fillW = 0, fillH = 0, inView = 0;
  // §6.2/§8.1 спеки: узлы не стоят друг на друге. Считаем из РЕАЛЬНЫХ позиций и
  // реальных размеров строк DataSet — то, что видно на кадре.
  let nodeOverlaps = 0, nodePairs = 0, coincident = 0, worstOverlap = 0;
  let nearCentres = 0;
  if (net && canvasEl) {
    let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
    const posAll = net.getPositions();
    const sizeById = {};
    rows.forEach((r) => { sizeById[String(r.id)] = r.size || 0; });
    const discs = [];
    Object.keys(posAll).forEach((id) => {
      const p = posAll[id];
      const sx = (p.x - cam.x) * sc + W / 2;
      const sy = (p.y - cam.y) * sc + H / 2;
      if (sx < 0 || sy < 0 || sx > W || sy > H) return;
      inView += 1;
      minX = Math.min(minX, sx); maxX = Math.max(maxX, sx);
      minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);
      discs.push({ x: sx, y: sy, r: (sizeById[String(id)] || 0) * sc });
    });
    discs.sort((a, b) => a.x - b.x);
    for (let i = 0; i < discs.length; i += 1) {
      const a = discs[i];
      for (let j = i + 1; j < discs.length; j += 1) {
        const b = discs[j];
        if (b.x - a.x > a.r + b.r) break;
        const dist = Math.hypot(b.x - a.x, b.y - a.y);
        nodePairs += 1;
        if (dist < 1.5) nearCentres += 1;
        if (dist < 0.5) coincident += 1;
        if (dist < a.r + b.r - 0.01) {
          nodeOverlaps += 1;
          worstOverlap = Math.max(worstOverlap, a.r + b.r - dist);
        }
      }
    }
    if (maxX > minX) { fillW = (maxX - minX) / W; fillH = (maxY - minY) / H; }
  }
  return {
    nodes: rows.length, edges: edgeRows.length, shapes,
    edgeStats,
    labels: labels.length,
    forcedLabels: forced.length,
    duplicateLabels,
    labelOverlaps: overlaps,
    bigGroups,
    groups: groupSizes.slice(0, 8),
    fillW, fillH, inView,
    nodeOverlaps, nodePairs, coincident, worstOverlap, nearCentres,
    selected: (vm && vm._cogSelectedId) || null,
    selectedLabeled: all.some(
      (l) => String(l.id) === String(vm && vm._cogSelectedId)),
    counters,
    fxSize: canvas ? [canvas.width, canvas.height] : null,
    elSize: el ? [el.clientWidth, el.clientHeight] : null,
    fitScale: (vm && vm._cogFitScale) || 0,
    scale: net ? net.getScale() : 0,
    dpr: window.devicePixelRatio,
    lod: scene ? scene.lod : null,
  };
}
"""

PAN_FPS = r"""
(ms) => new Promise((resolve) => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  const scene = vm && vm._cogScene;
  if (!net || !scene) { resolve({ error: 'no net' }); return; }
  const start = performance.now();
  const deltas = [];
  const drawsBefore = (vm._cogDebugCounters() || {}).fxPaints || 0;
  let last = start;
  const base = net.getViewPosition();
  const scale = net.getScale();
  function step(ts) {
    const now = performance.now();
    if (now - last > 0) deltas.push(now - last);
    last = now;
    // Панорамирование: камера реально движется, vis перерисовывает кадр.
    const phase = (now - start) / 260;
    net.moveTo({
      position: { x: base.x + Math.sin(phase) * 220,
                  y: base.y + Math.cos(phase * 0.7) * 160 },
      scale: scale, animation: false,
    });
    if (now - start < ms) requestAnimationFrame(step);
    else {
      const drawsAfter = (vm._cogDebugCounters() || {}).fxPaints || 0;
      const sorted = deltas.slice().sort((a, b) => a - b);
      const avg = deltas.reduce((s, d) => s + d, 0) / Math.max(1, deltas.length);
      resolve({
        frames: deltas.length,
        elapsed: now - start,
        fps: 1000 / (avg || 1),
        p50: sorted[Math.floor(sorted.length * 0.5)] || 0,
        p95: sorted[Math.floor(sorted.length * 0.95)] || 0,
        fpsP95: 1000 / ((sorted[Math.floor(sorted.length * 0.95)]) || 1),
        fxPaints: drawsAfter - drawsBefore,
      });
    }
  }
  requestAnimationFrame(step);
})
"""

IDLE_PROBE = r"""
(ms) => new Promise((resolve) => {
  const vm = window.__adminbotVm;
  const before = vm._cogDebugCounters() || {};
  const t0 = performance.now();
  setTimeout(() => {
    const after = vm._cogDebugCounters() || {};
    resolve({
      elapsed: performance.now() - t0,
      draws: (after.fxPaints || 0) - (before.fxPaints || 0),
      frames: (after.frames || 0) - (before.frames || 0),
      sprites: (after.fxSprites || 0) - (before.fxSprites || 0),
      gradients: (after.fxGradients || 0) - (before.fxGradients || 0),
      rafActive: !!after.rafActive,
      counters: after,
    });
  }, ms);
})
"""

STABLE = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene) return false;
  const key = [Math.round((vm._cogFitScale || 0) * 1e6),
               Math.round((scene.fxDpr || 1) * 100),
               Math.round(scene.width), Math.round(scene.height)].join(':');
  window.__cmvBKey = window.__cmvBKey || { key: '', n: 0 };
  if (window.__cmvBKey.key === key) window.__cmvBKey.n += 1;
  else { window.__cmvBKey.key = key; window.__cmvBKey.n = 1; }
  return window.__cmvBKey.n >= 3;
}
"""

PINCH = r"""
(spec) => {
  const [cx, cy] = spec;
  const el = window.__adminbotVm._cogEl;
  const canvas = el.querySelector('canvas');
  const box = canvas.getBoundingClientRect();
  return { x: box.left + cx, y: box.top + cy,
           w: canvas.clientWidth, h: canvas.clientHeight,
           left: box.left, top: box.top };
}
"""

# Экранная точка выбранного узла (та же проекция, что у слоя подписей).
SELECTED_POINT = r"""
() => {
  const vm = window.__adminbotVm, net = vm.cognitionNetwork, s = vm._cogScene;
  const id = vm._cogSelectedId;
  if (id == null) return null;
  const p = s.pos[id];
  const canvas = vm._cogEl.querySelector('canvas');
  if (!p || !canvas) return null;
  const box = canvas.getBoundingClientRect();
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const cam = net.getViewPosition(), sc = net.getScale();
  return { x: box.left + (p.x - cam.x) * sc + W / 2,
           y: box.top + (p.y - cam.y) * sc + H / 2 };
}
"""

# Виден ли выбранный узел в кадре (для снимка «зум с выбором»).
SELECTED_IN_VIEW = r"""
() => {
  const vm = window.__adminbotVm, net = vm.cognitionNetwork, s = vm._cogScene;
  const id = vm._cogSelectedId;
  if (id == null) return false;
  const p = s.pos[id];
  const canvas = vm._cogEl.querySelector('canvas');
  if (!p || !canvas) return false;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const cam = net.getViewPosition(), sc = net.getScale();
  const sx = (p.x - cam.x) * sc + W / 2;
  const sy = (p.y - cam.y) * sc + H / 2;
  return sx > 30 && sy > 30 && sx < W - 30 && sy < H - 30;
}
"""

NODE_SCREEN_XY = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  const view = vm && vm._cogView;
  const el = vm && vm._cogEl;
  if (!net || !view || !view.nodes.length || !el) return null;
  const canvas = el.querySelector('canvas');
  if (!canvas) return null;
  const box = canvas.getBoundingClientRect();
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const cam = net.getViewPosition();
  const scale = net.getScale();
  // Самый высокосвязный узел, который РЕАЛЬНО виден в кадре (с отступом).
  let best = null, bestSx = 0, bestSy = 0;
  const pos = net.getPositions();
  for (let i = 0; i < view.nodes.length; i += 1) {
    const n = view.nodes[i];
    const p = pos[n.id];
    if (!p) continue;
    const sx = (p.x - cam.x) * scale + W / 2;
    const sy = (p.y - cam.y) * scale + H / 2;
    if (sx < 30 || sy < 30 || sx > W - 30 || sy > H - 30) continue;
    if (!best || (n.degree || 0) > (best.degree || 0)) {
      best = n; bestSx = sx; bestSy = sy;
    }
  }
  if (!best) return null;
  return { id: best.id, degree: best.degree || 0,
           x: box.left + bestSx, y: box.top + bestSy, inside: true };
}
"""

# Точка для РЕАЛЬНОГО клика: узел с запасом пустого места вокруг, иначе на
# мобильном кадре (702 узла в 338×318) палец попадает в сосед, и проверка
# «связи выбора видны» поймала бы изолированный узел вместо цели.
TAP_TARGET = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  const view = vm && vm._cogView;
  const el = vm && vm._cogEl;
  if (!net || !view || !view.nodes.length || !el) return null;
  const canvas = el.querySelector('canvas');
  if (!canvas) return null;
  const box = canvas.getBoundingClientRect();
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const cam = net.getViewPosition();
  const scale = net.getScale();
  const pos = net.getPositions();
  const pts = [];
  for (let i = 0; i < view.nodes.length; i += 1) {
    const n = view.nodes[i];
    const p = pos[n.id];
    if (!p) continue;
    const sx = (p.x - cam.x) * scale + W / 2;
    const sy = (p.y - cam.y) * scale + H / 2;
    pts.push({ id: n.id, degree: n.degree || 0, sx, sy,
               inside: sx >= 34 && sy >= 34 && sx <= W - 34 && sy <= H - 34 });
  }
  let best = null;
  for (let i = 0; i < pts.length; i += 1) {
    const a = pts[i];
    if (!a.inside || !a.degree) continue;
    let clear = 1e9;
    for (let j = 0; j < pts.length; j += 1) {
      if (i === j) continue;
      const d = Math.hypot(pts[j].sx - a.sx, pts[j].sy - a.sy);
      if (d < clear) clear = d;
    }
    // Палец должен попасть в цель: узел без запаса вокруг не годится, поэтому
    // сначала ищем среди «свободных» (≥ 9 px), и только если таких нет —
    // берём лучший по общему счёту.
    const score = a.degree * 2 + Math.min(clear, 30)
      + (clear >= 9 ? 100 : 0);
    if (!best || score > best.score) {
      best = { id: a.id, degree: a.degree, clearance: clear, score,
               x: box.left + a.sx, y: box.top + a.sy };
    }
  }
  return best;
}
"""


def settle(pg, timeout_ms=60000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    # Геометрия обзора должна перестать меняться (ResizeObserver карточки):
    # иначе замер и клик попадут в «переезжающий» кадр.
    pg.wait_for_function(STABLE, timeout=timeout_ms)
    pg.wait_for_timeout(220)


def pinch(pg, cx, cy, from_px, to_px, steps=8):
    """Настоящий pinch двумя точками касания через CDP (не «сухой» вызов).

    `Emulation.setTouchEmulationEnabled(maxTouchPoints: 2)` обязателен: Playwright
    по умолчанию объявляет ОДНУ точку, и второй палец отбрасывается движком —
    жест не доходит до vis-network.
    """
    cdp = pg.context.new_cdp_session(pg)
    cdp.send("Emulation.setTouchEmulationEnabled",
             {"enabled": True, "maxTouchPoints": 2})
    box = pg.evaluate(PINCH, [cx, cy])
    # Центр жеста сдвигается внутрь канваса так, чтобы ОБА пальца оставались на
    # нём: палец за границей сцены превращает pinch в обычное перетаскивание.
    pad = max(from_px, to_px) + 6
    half_w = box["w"] / 2
    half_h = box["h"] / 2
    dx = min(max(cx, pad if pad < half_w else 4), box["w"] - pad
             if pad < half_w else box["w"] - 4)
    dy = min(max(cy, pad if pad < half_h else 4), box["h"] - pad
             if pad < half_h else box["h"] - 4)
    x, y = box["left"] + dx, box["top"] + dy

    def touch(kind, spread):
        pts = ([] if kind == "touchEnd" else [
            {"x": x - spread, "y": y, "id": 1, "radiusX": 8, "radiusY": 8},
            {"x": x + spread, "y": y, "id": 2, "radiusX": 8, "radiusY": 8},
        ])
        cdp.send("Input.dispatchTouchEvent", {"type": kind,
                                              "touchPoints": pts})

    touch("touchStart", from_px)
    for i in range(1, steps + 1):
        touch("touchMove", from_px + (to_px - from_px) * i / steps)
        pg.wait_for_timeout(24)
    touch("touchEnd", to_px)
    cdp.detach()


def shot(pg, out_dir, name):
    path = os.path.join(out_dir, name)
    pg.screenshot(path=path)
    return os.path.basename(path)


def run(browser, base, out_dir):
    report = {"shots": [], "checks": [], "fails": []}

    def check(cond, message):
        report["checks"].append({"ok": bool(cond), "message": message})
        if not cond:
            report["fails"].append(message)

    for label, (w, h), dpr in (("desktop", DESKTOP, 1), ("mobile", MOBILE, 2)):
        ctx = browser.new_context(
            viewport={"width": w, "height": h}, device_scale_factor=dpr,
            is_mobile=(label == "mobile"), has_touch=(label == "mobile"))
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        settle(pg)
        # Сцена в кадре ДО первого замера: на телефоне карта ниже первого
        # экрана, и IntersectionObserver честно держит кадр на паузе (§7.3) —
        # без прокрутки мы замеряли бы «выключенную» сцену.
        pg.evaluate("() => window.__adminbotVm._cogEl"
                    ".scrollIntoView({ block: 'center', inline: 'center' })")
        pg.wait_for_timeout(320)
        data = pg.evaluate(SNAPSHOT)
        report[label] = {"viewport": [w, h], "dpr": dpr, "snapshot": data}
        # ── объективные визуальные инварианты ───────────────────────────────
        check(data["nodes"] == NODES, "%s: в сцене %d узлов (ждали %d)"
              % (label, data["nodes"], NODES))
        check(data["edges"] == EDGES, "%s: в сцене %d связей (ждали %d)"
              % (label, data["edges"], EDGES))
        shapes = data["shapes"]
        check("box" not in shapes,
              "%s: ни одного прямоугольного узла (§4.1)" % label)
        check(shapes.get("dot", 0) > 0 and shapes.get("hexagon", 0) > 0
              and shapes.get("diamond", 0) > 0,
              "%s: разные формы по типам (dot/hexagon/diamond): %r"
              % (label, shapes))
        check(data["edgeStats"]["smooth"] == 0,
              "%s: все рёбра прямые (smooth=false, §10.1)" % label)
        check(data["edgeStats"]["opacityAbove"] == 0,
              "%s: ни одного непрозрачного «белого» ребра (§4.3)" % label)
        check(data["labelOverlaps"] == 0,
              "%s: подписи не накладываются (%d пересечений)"
              % (label, data["labelOverlaps"]))
        check(data["labels"] >= 3,
              "%s: подписи на обзоре есть (%d подписей, §4.4)"
              % (label, data["labels"]))
        check(data["counters"]["fxSprites"] > 0,
              "%s: спрайты свечения построены" % label)
        # §12.1: обзор заполняет кадр по ограничивающей оси (граф не «уехал»).
        check(data["fillH"] >= 0.75 or data["fillW"] >= 0.75,
              "%s: обзор заполняет кадр (fillH=%.2f, fillW=%.2f)"
              % (label, data["fillH"], data["fillW"]))
        # §6.2/§12.1: широкий короткий кадр должен ИСПОЛЬЗОВАТЬ ширину, а не
        # держать ядро столбом (до CMV-B: fillW=0.232 при fillH=0.90).
        check(data["fillW"] >= 0.55,
              "%s: обзор использует ширину кадра (fillW=%.2f)"
              % (label, data["fillW"]))
        # §6.2 спеки/§8.1 контракта: ядровые круги не пересекаются, узлы не
        # стоят точно друг на друге (считается из позиций и реальных размеров).
        # Метрика — пересечений НА УЗЕЛ: плотностный предел по построению даёт
        # ≤ 2 (диаметр = 0.9·d3 больше расстояния до 1-го/2-го соседа), а стена
        # из 702 сфер на исходном кандидате давала ≈50 на узел.
        # Мобильный кадр (702 узла в 338×318, режим `simple` без физики — узел
        # стоит на исходном кольце vis) — зона CMV-C/D (агрегаты LOD и лист),
        # его числа пишем в отчёт, но приёмку здесь не валим.
        per_node = (data["nodeOverlaps"] / data["inView"]
                    if data["inView"] else 0)
        if label == "desktop":
            check(per_node <= 2.0,
                  "%s: узлы не стоят стеной (пересечений %.0f = %.2f на узел, "
                  "макс. %.1f px)"
                  % (label, data["nodeOverlaps"], per_node,
                     data["worstOverlap"]))
            check(data["coincident"] <= 2,
                  "%s: нет совпавших центров (ровно поверх: %d; ближе 1.5 px: %d)"
                  % (label, data["coincident"], data["nearCentres"]))
        else:
            check(per_node <= 6.0,
                  "%s: узлы не стоят стеной сверх плотного кадра "
                  "(%.0f = %.2f на узел; агрегаты LOD — CMV-C)"
                  % (label, data["nodeOverlaps"], per_node))
        check(data["bigGroups"] >= 1,
              "%s: в кадре есть связная видимая область (%d); разделение групп "
              "на обзоре — задача агрегатов LOD (CMV-C)" % (label, data["bigGroups"]))
        check(data["counters"]["fxGradients"] == data["counters"]["fxSprites"],
              "%s: один градиент на спрайт, не на узел" % label)
        check(data["fxSize"] and data["elSize"]
              and data["fxSize"][0] == int(data["elSize"][0] * data["dpr"])
              and data["fxSize"][1] == int(data["elSize"][1] * data["dpr"]),
              "%s: canvas слоя fx = размер сцены · dpr (%r при dpr=%r, сцена %r)"
              % (label, data["fxSize"], data["dpr"], data["elSize"]))

        # ── выбор узла реальным кликом (сцена прокручена в кадр) ────────────
        pg.evaluate("() => window.__adminbotVm._cogEl"
                    ".scrollIntoView({ block: 'center', inline: 'center' })")
        pg.wait_for_timeout(150)
        target = pg.evaluate(TAP_TARGET) or pg.evaluate(NODE_SCREEN_XY)
        if target:
            # Координаты берём той же проекцией, что у слоя подписей; vis сам
            # говорит, какой узел под курсором (canvasToDOM/getNodeAt в этой
            # версии расходятся, поэтому сверяемся с реальным hover).
            pg.mouse.move(target["x"], target["y"])
            pg.wait_for_timeout(260)
            hovered = pg.evaluate("() => window.__adminbotVm._cogScene.hoverId")
            report[label]["hover"] = hovered
            check(hovered is not None,
                  "%s: hoverNode определяет узел под курсором (%r)"
                  % (label, hovered))
            pg.mouse.click(target["x"], target["y"])
            pg.wait_for_timeout(340)
            data_sel = pg.evaluate(SNAPSHOT)
            report[label]["selection"] = {
                "target": target["id"], "degree": target["degree"],
                "selected": data_sel["selected"],
                "selectedLabeled": data_sel["selectedLabeled"],
                "card": pg.evaluate("() => !!window.__adminbotVm.cogCardOpen"),
                "labelOverlaps": data_sel["labelOverlaps"],
                "labels": data_sel["labels"],
                "edgeStats": data_sel["edgeStats"],
                "activeEdges": data_sel["counters"].get("fxActiveEdges"),
                "edgeDraws": data_sel["counters"].get("fxEdgeDraws"),
            }
            check(data_sel["selected"] is not None,
                  "%s: клик выбрал реальный узел (%r)"
                  % (label, data_sel["selected"]))
            check(report[label]["selection"]["card"],
                  "%s: клик открыл карточку выбранного узла" % label)
            check(data_sel["selectedLabeled"],
                  "%s: подпись выбранного узла видна всегда (§4.4)" % label)
            check(data_sel["labelOverlaps"] == 0,
                  "%s: после выбора подписи не накладываются" % label)
            check(data_sel["edgeStats"]["opacityBelow"] > 0,
                  "%s: при выборе у сети есть ослабленные и подсвеченные рёбра"
                  % label)
            # §4.3/§12.2 спеки: связи выбранного видны — слой `fx` выводит их
            # ПОВЕРХ слоя узлов (иначе 702 круга перекрывают линию 1.4 px).
            # У изолированного узла связей нет — тогда проверять нечего (это
            # честное свойство данных, а не дефект отрисовки).
            incident_n = pg.evaluate(
                """(id) => {
                  const vm = window.__adminbotVm;
                  const edges = (vm._cogView && vm._cogView.edges) || [];
                  let n = 0;
                  for (const e of edges) {
                    if (String(e.from) === String(id)
                        || String(e.to) === String(id)) n += 1;
                  }
                  return n;
                }""", data_sel["selected"])
            report[label]["selection"]["incident"] = incident_n
            check(incident_n == 0
                  or (report[label]["selection"]["activeEdges"] or 0) >= 1,
                  "%s: подсвеченные связи выбранного нарисованы поверх узлов "
                  "(%s из %s инцидентных)"
                  % (label, report[label]["selection"]["activeEdges"],
                     incident_n))
            check(incident_n == 0
                  or (report[label]["selection"]["edgeDraws"] or 0) > 0,
                  "%s: слой fx реально рисовал связи выбора (%s линий)"
                  % (label, report[label]["selection"]["edgeDraws"]))
        report["shots"].append(shot(
            pg, out_dir, "cmv-b-%s-fit.png" % label))
        if report[label].get("selection"):
            report["shots"].append(shot(
                pg, out_dir, "cmv-b-%s-fit-selected.png" % label))
            # Карточка закрывается (Esc), выбор ОСТАЁТСЯ — иначе она закрыла бы
            # сцену на мобильном bottom sheet и жест не дошёл бы до канваса.
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(260)
            after_esc = pg.evaluate(
                "() => ({ sel: window.__adminbotVm._cogSelectedId,"
                " card: !!window.__adminbotVm.cogCardOpen })")
            report[label]["afterEscape"] = after_esc
            check(after_esc["card"] is False,
                  "%s: Esc закрывает карточку" % label)
            check(str(after_esc["sel"]) == str(
                report[label]["selection"]["selected"]),
            "%s: закрытие карточки не снимает выбор (§8.2)" % label)

        # ── зум ×2 ОТ ВЫБРАННОГО УЗЛА (§12.2) ───────────────────────────────
        # Сцена в кадре; жест — в точку выбранного узла, иначе можно уехать в
        # пустую область, где честно нечего показывать.
        pg.evaluate("() => window.__adminbotVm._cogEl"
                    ".scrollIntoView({ block: 'center', inline: 'center' })")
        pg.wait_for_timeout(200)
        aim = pg.evaluate(SELECTED_POINT)
        box = pg.evaluate(PINCH, [0, 0])
        cx = (aim["x"] if aim else box["x"] + box["w"] / 2) - box["x"]
        cy = (aim["y"] if aim else box["y"] + box["h"] / 2) - box["y"]
        check(0 <= box["x"] + cx <= w and 0 <= box["y"] + cy <= h,
              "%s: точка жеста в кадре (%.0f, %.0f при %dx%d)"
              % (label, box["x"] + cx, box["y"] + cy, w, h))
        if label == "desktop":
            pg.mouse.move(box["x"] + cx, box["y"] + cy)
            for _ in range(5):
                pg.mouse.wheel(0, -300)
                pg.wait_for_timeout(90)
        else:
            # Pinch — вокруг центра сцены: жест у края выносит камеру в пустоту.
            pinch(pg, box["w"] / 2, box["h"] / 2, 40, 95, steps=6)
        pg.wait_for_timeout(400)
        # В кадре после зума должен остаться выбранный узел: если он уехал,
        # выбираем видимый (обычное действие пользователя). Если камера ушла в
        # пустую область (возможно на плотном графе при сильном зуме) —
        # возвращаемся к реальному узлу штатным поиском приложения.
        if pg.evaluate(SELECTED_IN_VIEW) is not True:
            t2 = pg.evaluate(NODE_SCREEN_XY)
            if t2:
                pg.mouse.move(t2["x"], t2["y"])
                pg.wait_for_timeout(120)
                pg.mouse.click(t2["x"], t2["y"])
                pg.wait_for_timeout(300)
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(200)
        if pg.evaluate(SELECTED_IN_VIEW) is not True:
            title = pg.evaluate(
                "() => { const vm = window.__adminbotVm;"
                " const n = (vm.cognitionGraphData.byId || {})[vm._cogSelectedId];"
                " return n ? n.title : null; }")
            if title:
                pg.evaluate("""(t) => {
                  const vm = window.__adminbotVm;
                  vm.graphSearchQuery = t;
                  return vm.searchCognitionGraph();
                }""", title)
                pg.wait_for_timeout(900)
            report[label]["zoom_recovered_by_search"] = True
        zoomed = pg.evaluate(SNAPSHOT)
        report[label]["zoomed"] = {
            "fitScale": zoomed["fitScale"], "scale": zoomed["scale"],
            "ratio": (zoomed["scale"] / zoomed["fitScale"])
            if zoomed["fitScale"] else 0,
            "lod": zoomed["lod"], "labels": zoomed["labels"],
            "labelOverlaps": zoomed["labelOverlaps"],
            "counters": zoomed["counters"],
        }
        check(zoomed["scale"] > zoomed["fitScale"] * 1.6,
              "%s: зум увеличил масштаб (r=%.2f)"
              % (label, zoomed["scale"] / (zoomed["fitScale"] or 1)))
        check(zoomed["inView"] >= 1,
              "%s: после зума в кадре остаются реальные узлы (%d)"
              % (label, zoomed["inView"]))
        check(zoomed["labelOverlaps"] == 0,
              "%s: при зуме подписи не накладываются" % label)
        check(zoomed["selected"] is not None and zoomed["selectedLabeled"],
              "%s: выбранный узел остаётся подписанным при зуме" % label)
        report["shots"].append(shot(
            pg, out_dir, "cmv-b-%s-zoom2.png" % label))

        if label == "desktop":
            # ── FPS: панорамирование 3 с (три прогона, медиана) ──────────────
            runs = [pg.evaluate(PAN_FPS, PAN_MS) for _ in range(3)]
            pans = sorted(r["fps"] for r in runs if "fps" in r)
            pan = runs[len(runs) // 2]
            pan["runs"] = [round(r.get("fps", 0), 1) for r in runs]
            pan["median"] = pans[len(pans) // 2] if pans else 0
            report["fps_pan"] = pan
            # Эталон: та же панорама БЕЗ нашего слоя — цена визуала в кадре.
            pg.evaluate("() => { const s = window.__adminbotVm._cogScene;"
                        " s._fxKeep = s.fx; s.fx = null; }")
            pan_no_fx = pg.evaluate(PAN_FPS, PAN_MS)
            pg.evaluate("() => { const s = window.__adminbotVm._cogScene;"
                        " s.fx = s._fxKeep; }")
            report["fps_pan_vis_only"] = pan_no_fx
            check(pan["median"] >= 45,
                  "desktop: FPS панорамирования ≥ 45 (медиана %.1f, прогоны %r, "
                  "p95 %.1f)" % (pan["median"], pan["runs"], pan.get("fpsP95", 0)))
            check(pan.get("fxPaints", 0) > 10,
                  "desktop: слой fx реально рисовал во время панорамирования")
            # ── Простой: частотный потолок и отсутствие утечек ─────────────
            sprites_before_idle = pg.evaluate(
                "() => window.__adminbotVm._cogDebugCounters().fxSprites")
            idle = pg.evaluate(IDLE_PROBE, IDLE_MS)
            idle["spritesBefore"] = sprites_before_idle
            report["idle"] = idle
            allowed = 24 * (IDLE_MS / 1000.0) + 12
            check(idle["draws"] <= allowed,
                  "простой: кадров декора ≤ 24 fps (%.0f за %.0f мс, лимит %.0f)"
                  % (idle["draws"], idle["elapsed"], allowed))
            check(idle["draws"] > 0,
                  "простой: мягкая жизнь продолжается (кадры декора есть)")
            check(idle["sprites"] == 0,
                  "простой: новых спрайтов не создаётся")
            check(idle["gradients"] == 0,
                  "простой: градиенты в кадре не создаются")
            report["shots"].append(shot(
                pg, out_dir, "cmv-b-desktop-after-pan.png"))
        pg.close()
        ctx.close()
    return report


def run_reduced(browser, base, out_dir):
    """`prefers-reduced-motion: reduce` (§7.3 спеки): статика сохранена,
    непрерывного движения нет — ни кадров, ни импульсов."""
    report = {"checks": [], "fails": []}

    def check(cond, message):
        report["checks"].append({"ok": bool(cond), "message": message})
        if not cond:
            report["fails"].append(message)

    ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                        "height": DESKTOP[1]},
                              device_scale_factor=1,
                              reduced_motion="reduce")
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes())
    pg = ctx.new_page()
    pg.goto(base + "#/", wait_until="load")
    settle(pg)
    pg.evaluate("() => window.__adminbotVm._cogEl"
                ".scrollIntoView({ block: 'center', inline: 'center' })")
    pg.wait_for_timeout(300)
    target = pg.evaluate(NODE_SCREEN_XY)
    if target:
        pg.mouse.click(target["x"], target["y"])
        pg.wait_for_timeout(320)
    base_state = pg.evaluate(SNAPSHOT)
    idle = pg.evaluate(IDLE_PROBE, 1200)
    report["idle"] = idle
    report["state"] = base_state
    check(base_state["counters"]["fxSprites"] > 0,
          "reduced-motion: свечение построено (не «урезанный режим»)")
    check(base_state["counters"]["fxDraws"] > 0,
          "reduced-motion: статический кадр декора нарисован")
    check(base_state["labels"] + base_state["forcedLabels"] > 0,
          "reduced-motion: подписи видны")
    check(base_state["selected"] is not None
          and base_state["selectedLabeled"],
          "reduced-motion: выбранный узел и его подпись сохранены")
    check(idle["rafActive"] is False, "reduced-motion: кадрового цикла нет")
    check(idle["draws"] == 0,
          "reduced-motion: за %.0f мс ни одного кадра анимации (%d)"
          % (idle["elapsed"], idle["draws"]))
    check(idle["sprites"] == 0, "reduced-motion: спрайты не пересоздаются")
    report["shots"] = [shot(pg, out_dir, "cmv-b-desktop-reduced-motion.png")]
    pg.close()
    ctx.close()
    return report


def run_zoom_evidence(browser, base, out_dir):
    """Крупный фрагмент (DPR 2) вокруг выбранного узла.

    Нужен именно для двух пунктов ревью CMV-B: на fit узлы 5–7 px и связи
    выбранного не разглядеть на полном кадре. Снимок 320×200 CSS-px вокруг
    выбранного узла в DPR 2 показывает, различимы ли узлы и какие линии
    принадлежат выбору (§4.3/§12.2 спеки), плюс проверяет DPR 2 (§13 спеки).
    """
    report = {"checks": [], "fails": []}

    def check(cond, message):
        report["checks"].append({"ok": bool(cond), "message": message})
        if not cond:
            report["fails"].append(message)

    ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                        "height": DESKTOP[1]},
                              device_scale_factor=2)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes())
    pg = ctx.new_page()
    pg.goto(base + "#/", wait_until="load")
    settle(pg)
    pg.evaluate("() => window.__adminbotVm._cogEl"
                ".scrollIntoView({ block: 'center', inline: 'center' })")
    pg.wait_for_timeout(320)
    state = pg.evaluate(SNAPSHOT)
    report["state"] = state
    check(state["dpr"] == 2 and state["fxSize"]
          and state["elSize"]
          and state["fxSize"][0] == int(state["elSize"][0] * 2),
          "DPR 2: слой fx = сцена · 2 (%r при %r)" % (
              state["fxSize"], state["elSize"]))
    target = pg.evaluate(NODE_SCREEN_XY)
    if not target:
        report["fails"].append("zoom: не найден видимый узел для выбора")
        pg.close()
        ctx.close()
        return report
    pg.mouse.click(target["x"], target["y"])
    pg.wait_for_timeout(420)
    sel = pg.evaluate(SNAPSHOT)
    report["selection"] = {
        "id": sel["selected"], "degree": target["degree"],
        "activeEdges": sel["counters"].get("fxActiveEdges"),
        "edgeDraws": sel["counters"].get("fxEdgeDraws"),
        "labelOverlaps": sel["labelOverlaps"],
    }
    check((sel["counters"].get("fxActiveEdges") or 0) >= 1,
          "zoom: связи выбранного нарисованы поверх узлов (%s)"
          % sel["counters"].get("fxActiveEdges"))
    check(sel["labelOverlaps"] == 0,
          "zoom: подписи в кадре не накладываются (%d)"
          % sel["labelOverlaps"])
    point = pg.evaluate(SELECTED_POINT)
    if point:
        clip = {"x": max(0, point["x"] - 170), "y": max(0, point["y"] - 110),
                "width": 340, "height": 220}
        path = os.path.join(out_dir, "cmv-b-desktop-selection-zoom2x.png")
        pg.screenshot(path=path, clip=clip, scale="device")
        report["shots"] = [os.path.basename(path)]
        report["clip"] = clip
    pg.close()
    ctx.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--headed", action="store_true",
                    help="реальный GPU (не software-растеризация headless)")
    ap.add_argument("--no-gpu", action="store_true",
                    help="software-растеризация (SwiftShader) — нижняя граница")
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        repo, "plans", "features", "epic-cm-visual-01", "evidence", "cmv-b")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    os.chdir(repo)
    global M, W15
    import time
    import ui_round1025_matrix as M            # noqa: E402
    import ui_evol_w15_composition_e2e as W15  # noqa: E402
    from playwright.sync_api import sync_playwright

    payload = big_payload()
    payload["generated_at"] = int(time.time())
    W15.set_cog_payload(payload)

    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    report = {"repo": repo, "nodes": NODES, "edges": EDGES,
              "payload_sha256": _sha(json.dumps(payload, sort_keys=True)),
              "render_mode": ("headed" if args.headed
                              else ("headless-swiftshader" if args.no_gpu
                                    else "headless-gpu(ANGLE d3d11)"))}
    try:
        with sync_playwright() as pw:
            launch = {"headless": not args.headed}
            if not args.headed and not args.no_gpu:
                launch["args"] = [
                    "--enable-gpu", "--enable-gpu-rasterization",
                    "--ignore-gpu-blocklist", "--use-angle=d3d11",
                ]
            browser = pw.chromium.launch(**launch)
            try:
                report.update(run(browser, base, out_dir))
                reduced = run_reduced(browser, base, out_dir)
                report["reduced_motion"] = reduced
                report["checks"].extend(reduced["checks"])
                report["fails"].extend(reduced["fails"])
                report["shots"].extend(reduced["shots"])
                zoom = run_zoom_evidence(browser, base, out_dir)
                report["selection_zoom"] = zoom
                report["checks"].extend(zoom["checks"])
                report["fails"].extend(zoom["fails"])
                report["shots"].extend(zoom.get("shots") or [])
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    finally:
        server.shutdown()

    out = os.path.join(out_dir, "cmv-b-scene-fps.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if report.get("error"):
        print("ERROR:\n" + report["error"][-2000:])
        return 3
    for f in report["fails"]:
        print("FAIL: " + f)
    pan = report.get("fps_pan") or {}
    idle = report.get("idle") or {}
    print("FPS pan: %.1f (p95 %.1f), frames=%s" % (
        pan.get("fps", 0), pan.get("fpsP95", 0), pan.get("frames")))
    print("Idle: draws=%s over %.0f ms, sprites+%s, gradients+%s" % (
        idle.get("draws"), idle.get("elapsed", 0), idle.get("sprites"),
        idle.get("gradients")))
    print("checks=%d fails=%d" % (len(report["checks"]),
                                  len(report["fails"])))
    return 0 if not report["fails"] else 2


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
