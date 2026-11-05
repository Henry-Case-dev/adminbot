"""Адресная допроба батча 3 (не артефакт приёмки сама по себе — пишет в
residual3/{CMV-PHY-04,CMV-AI-02,CMV-AI-03} поверх основного прогона):

1. CMV-PHY-04/wheel_timeline: разворачивает зум колеса во времени — мгновенный
   ли сдвиг мировой точки под курсором (поведение vis) или камера доезжает
   потом; 3 шага колеса.
2. CMV-PHY-04/gesture_poll: поллинг камеры из Python во время анимации фокуса
   поиска + wheel на 180 мс: длительность/сглаженность анимации и немедленный
   перехват управления жестом.
3. CMV-PHY-04/pinch_center: pinch (CDP touch) вокруг мировой точки — якорится
   ли жест в центре щипка.
4. CMV-AI-02/click_fresh: документирует сдвиг раскладки после клика
   (positions до/после) и снимает серию импульса по СВЕЖЕЙ проекции узла
   (+300 мс после клика, окно импульса 600 мс).
5. CMV-AI-03/focus_duration: длительность плавного фокуса камеры после
   успешного поиска (поллинг 80 мс, desktop).

Запуск: <venv python> plans/features/epic-cm-visual-01/evidence/residual3/addendum.py
"""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tests", "fixtures", "cmv"))

import ui_round1025_matrix as M            # noqa: E402
import ui_evol_w15_composition_e2e as W15  # noqa: E402
import cog_map_fixtures as FIX             # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = HERE
TARGET_ID = "paradigm:-1001234567890:184"
DESKTOP = (1440, 900)

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  const net = vm.cognitionNetwork;
  if (net.getScale() <= 0) return false;
  return !vm._cogScene || vm._cogScene.settled === true;
}
"""

JS_CAM = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const vp = net.getViewPosition();
  return { t: 0, scale: +net.getScale().toFixed(5),
           vx: +vp.x.toFixed(2), vy: +vp.y.toFixed(2) };
}
"""

JS_PROJ = r"""
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
  const cam = net.getViewPosition(), sc = net.getScale();
  const sx = (p.x - cam.x) * sc + canvas.clientWidth / 2;
  const sy = (p.y - cam.y) * sc + canvas.clientHeight / 2;
  return { x: box.left + sx, y: box.top + sy, sx: sx, sy: sy,
           scale: sc,
           nodeR: 24, inside: sx > 60 && sy > 60
             && sx < canvas.clientWidth - 60
             && sy < canvas.clientHeight - 60 };
}
"""

JS_WORLD_AT = r"""
([sx, sy]) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const el = vm._cogEl || document.querySelector('.cognition-graph');
  const canvas = el.querySelector('canvas');
  const box = canvas.getBoundingClientRect();
  const cam = net.getViewPosition(), sc = net.getScale();
  return { wx: cam.x + (sx - canvas.clientWidth / 2) / sc,
           wy: cam.y + (sy - canvas.clientHeight / 2) / sc,
           scale: sc };
}
"""

JS_SCENE_POS_KEYS = r"""
(ids) => {
  const vm = window.__adminbotVm;
  const scene = vm._cogScene;
  const pos = scene ? (scene.pos || {}) : {};
  const out = {};
  for (const k of ids) {
    const p = pos[k];
    if (p) out[k] = [+p.x.toFixed(2), +p.y.toFixed(2)];
  }
  return out;
}
"""

# Серия яркости fx (кольцо) — компактная версия сэмплера.
JS_SAMPLE_SERIES = r"""
(spec) => new Promise((resolve) => {
  const vm = window.__adminbotVm;
  const scene = vm._cogScene;
  if (!scene || !scene.fxCanvas || !scene.fxCtx) { resolve(null); return; }
  const dpr = scene.fxDpr || 1;
  const t = spec.target;
  const cx = Math.round(t.sx * dpr), cy = Math.round(t.sy * dpr);
  const rr = Math.max(6, Math.round((t.r || 10) * 1.5 * dpr));
  const x0 = Math.max(0, cx - rr * 2), y0 = Math.max(0, cy - rr * 2);
  const w = Math.min(scene.fxCanvas.width - x0, rr * 4);
  const h = Math.min(scene.fxCanvas.height - y0, rr * 4);
  const pts = [];
  for (let py = 0; py < h; py += 2) {
    const dy = py - (cy - y0);
    for (let px = 0; px < w; px += 2) {
      const dx = px - (cx - x0);
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d >= rr && d <= rr * 2) pts.push((py * w + px) * 4);
    }
  }
  const ref = null;
  const samples = [];
  const t0 = performance.now();
  let slot = 0;
  const step = () => {
    const now = performance.now();
    while (slot < spec.count && now - t0 >= slot * spec.intervalMs) {
      const data = scene.fxCtx.getImageData(x0, y0, w, h).data;
      let sum = 0, dSum = 0;
      for (let k = 0; k < pts.length; k += 1) {
        const j = pts[k]; sum += data[j] + data[j + 1] + data[j + 2];
      }
      samples.push({ t: +(now - t0).toFixed(1),
                     ring: +(sum / (pts.length * 3)).toFixed(2) });
      slot += 1;
    }
    if (slot < spec.count) requestAnimationFrame(step);
    else resolve(samples);
  };
  requestAnimationFrame(step);
})
"""


def save(out, name, data):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("->", name)


def main():
    M.PORT = 0
    server = M._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
    payload = FIX.load(702)
    payload["generated_at"] = 1750000000
    W15.set_cog_payload(payload)
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--enable-gpu", "--enable-gpu-rasterization",
                  "--ignore-gpu-blocklist", "--use-angle=d3d11"])
        ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                            "height": DESKTOP[1]},
                                  device_scale_factor=1)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        pg.wait_for_function(READY, timeout=120000)
        pg.evaluate("""() => { const vm = window.__adminbotVm;
          const el = vm._cogEl || document.querySelector('.cognition-graph');
          if (el) el.scrollIntoView({ block: 'center' }); }""")
        pg.wait_for_timeout(600)

        def cam():
            return pg.evaluate(JS_CAM)

        def stabilize(sec=4.0):
            t0 = time.time()
            prev = None
            while time.time() - t0 < sec:
                cur = pg.evaluate(JS_SCENE_POS_KEYS,
                                  [TARGET_ID, "ent:-1001234567890:379",
                                   "fact:-1001234567890:1"])
                if prev == cur:
                    return True
                prev = cur
                pg.wait_for_timeout(400)
            return False

        # ── 1. PHY-04: wheel-таймлайн (3 шага, поллинг 60 мс)
        pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const cache = (vm._cogScene && vm._cogScene.pos)
            || net.getPositions() || {};
          const pos = cache['%s'];
          net.moveTo({ position: { x: pos.x, y: pos.y },
                       scale: vm._cogFitScale * 1.4, animation: false });
        }""" % TARGET_ID)
        pg.wait_for_timeout(800)
        stabilize()
        spot = pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const canvas = (vm._cogEl
            || document.querySelector('.cognition-graph'))
            .querySelector('canvas');
          const box = canvas.getBoundingClientRect();
          return { x: box.left + canvas.clientWidth * 0.75,
                   y: box.top + canvas.clientHeight * 0.3 };
        }""")
        pg.mouse.move(spot["x"], spot["y"])
        pg.wait_for_timeout(150)
        trace = [dict(cam(), t=0)]
        pg.mouse.wheel(0, -240)
        for i in range(1, 13):
            pg.wait_for_timeout(60)
            c = cam()
            c["t"] = i * 60
            trace.append(c)
        pg.mouse.wheel(0, -240)
        pg.wait_for_timeout(60)
        c = cam(); c["t"] = 780; trace.append(c)
        pg.wait_for_timeout(600)
        c = cam(); c["t"] = 1440; trace.append(c)
        w0 = pg.evaluate(JS_WORLD_AT, [spot["x"], spot["y"]])
        w1 = pg.evaluate(JS_WORLD_AT, [spot["x"], spot["y"]])
        drift = (((w1["wx"] - w0["wx"]) ** 2
                  + (w1["wy"] - w0["wy"]) ** 2) ** 0.5) * w1["scale"]
        results["wheel_timeline"] = {
            "spot": spot, "trace": trace, "worldAt780": w0,
            "worldAt1440": w1, "cursorDriftPx": round(drift, 2)}
        save(results["wheel_timeline"],
             "CMV-PHY-04/wheel-timeline.json", results["wheel_timeline"])
        pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const cache = (vm._cogScene && vm._cogScene.pos)
            || net.getPositions() || {};
          const pos = cache['%s'];
          net.moveTo({ position: { x: pos.x, y: pos.y },
                       scale: vm._cogFitScale * 1.4, animation: false });
        }""" % TARGET_ID)
        pg.wait_for_timeout(800)
        stabilize()

        # ── 2. PHY-04: pinch вокруг центра жеста
        center = pg.evaluate(JS_PROJ, TARGET_ID)
        cx, cy = int(center["x"]), int(center["y"])
        sess = ctx.new_cdp_session(pg)
        w_c0 = pg.evaluate(JS_WORLD_AT, [cx, cy])
        s0 = cam()
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
        pg.wait_for_timeout(700)
        w_c1 = pg.evaluate(JS_WORLD_AT, [cx, cy])
        s1 = cam()
        anchor = (((w_c1["wx"] - w_c0["wx"]) ** 2
                   + (w_c1["wy"] - w_c0["wy"]) ** 2) ** 0.5) * w_c1["scale"]
        results["pinch_center"] = {
            "centerPx": [cx, cy], "worldBefore": w_c0, "worldAfter": w_c1,
            "scaleBefore": s0["scale"], "scaleAfter": s1["scale"],
            "anchorDriftPx": round(anchor, 2)}
        save(results["pinch_center"],
             "CMV-PHY-04/pinch-center.json", results["pinch_center"])
        pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const cache = (vm._cogScene && vm._cogScene.pos)
            || net.getPositions() || {};
          const pos = cache['%s'];
          net.moveTo({ position: { x: pos.x, y: pos.y },
                       scale: vm._cogFitScale * 1.4, animation: false });
        }""" % TARGET_ID)
        pg.wait_for_timeout(800)
        stabilize()

        # ── 3. PHY-04: gesture override (поллинг камеры из Python)
        inp = pg.locator("[data-cog-map] .graph-search__input").first
        inp.fill("")
        inp.fill("кофе 184")
        pg.wait_for_timeout(200)
        trace2 = []
        t0 = time.time()
        inp.press("Enter")
        for i in range(11):   # 0..1000 ms через 100 ms
            c = cam()
            c["t"] = round((time.time() - t0) * 1000)
            trace2.append(c)
            if i == 1:
                pg.mouse.move(720, 450)
                pg.mouse.wheel(0, -300)
            pg.wait_for_timeout(90)
        pg.wait_for_timeout(600)
        trace2.append(dict(cam(), t=round((time.time() - t0) * 1000)))
        st = pg.evaluate("""() => { const vm = window.__adminbotVm;
          return { selected: vm._cogSelectedId,
                   status: vm.graphSearchStatus }; }""")
        results["gesture_poll"] = {"trace": trace2, "search": st,
                                   "note": "wheel на ~180-200 мс поверх "
                                           "анимации фокуса поиска"}
        save(results["gesture_poll"],
             "CMV-PHY-04/gesture-poll.json", results["gesture_poll"])

        # ── 4. AI-02: сдвиг раскладки после клика + свежая серия импульса
        pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const cache = (vm._cogScene && vm._cogScene.pos)
            || net.getPositions() || {};
          const pos = cache['%s'];
          net.moveTo({ position: { x: pos.x, y: pos.y },
                       scale: vm._cogFitScale * 1.6, animation: false });
          if (net.unselectAll) net.unselectAll();
          if (vm.graphClearDetail) vm.graphClearDetail();
        }""" % TARGET_ID)
        pg.wait_for_timeout(800)
        stabilize(5.0)
        ns = pg.evaluate(JS_PROJ, TARGET_ID)
        sample_ids = pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const pos = vm._cogScene.pos || {};
          return Object.keys(pos).slice(0, 60);
        }""")
        pos_before = pg.evaluate(JS_SCENE_POS_KEYS, sample_ids)
        g = 16.0
        band_r = round(g * 0.9, 1)
        # серия 1: с точки ДО клика (начало импульса + сдвиг раскладки)
        series_a = pg.evaluate(JS_SAMPLE_SERIES, {
            "target": {"sx": ns["sx"], "sy": ns["sy"], "r": band_r},
            "intervalMs": 50, "count": 30})
        st_mid = pg.evaluate("""() => { const vm = window.__adminbotVm;
          return { selected: vm._cogSelectedId,
                   pulseHit: vm._cogScene.pulseHit ? {
                     kind: vm._cogScene.pulseHit.kind,
                     duration: vm._cogScene.pulseHit.duration } : null }; }""")
        pg.wait_for_timeout(500)
        pos_after = pg.evaluate(JS_SCENE_POS_KEYS, sample_ids)
        shifted = []
        for k in sample_ids:
            p0 = pos_before.get(k)
            p1 = pos_after.get(k)
            if p0 and p1:
                d = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
                if d > 2.0:
                    shifted.append((k, round(d, 1)))
        ns2 = pg.evaluate(JS_PROJ, TARGET_ID)
        series_b = pg.evaluate(JS_SAMPLE_SERIES, {
            "target": {"sx": ns2["sx"], "sy": ns2["sy"], "r": band_r},
            "intervalMs": 50, "count": 22}) if ns2 else []
        st_final = pg.evaluate("""() => { const vm = window.__adminbotVm;
          return { selected: vm._cogSelectedId,
                   detail: vm.graphDetail ? vm.graphDetail.id : null,
                   card: vm.cogCardOpen === true,
                   activeEdges: (vm._cogDebugCounters
                     ? vm._cogDebugCounters().fxActiveEdges : null) }; }""")
        results["click_fresh"] = {
            "clickNode": TARGET_ID, "prePos": ns, "postPos": ns2,
            "shiftedNodes": sorted(shifted, key=lambda kv: -kv[1])[:12],
            "shiftedCount": len(shifted), "sampledTotal": len(sample_ids),
            "seriesFromPrePos": series_a, "seriesFresh": series_b,
            "stateMid": st_mid, "stateFinal": st_final}
        save(results["click_fresh"],
             "CMV-AI-02/click-fresh.json", results["click_fresh"])
        pg.evaluate("""() => { const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          if (net.unselectAll) net.unselectAll();
          if (vm.graphClearDetail) vm.graphClearDetail(); }""")
        pg.wait_for_timeout(500)

        # ── 5. AI-03: длительность плавного фокуса (поллинг)
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
        pg.wait_for_timeout(600)
        inp = pg.locator("[data-cog-map] .graph-search__input").first
        inp.fill("")
        inp.fill("кофе 184")
        pg.wait_for_timeout(200)
        trace3 = []
        t0 = time.time()
        inp.press("Enter")
        for i in range(14):
            c = cam()
            c["t"] = round((time.time() - t0) * 1000)
            trace3.append(c)
            pg.wait_for_timeout(70)
        pg.wait_for_timeout(500)
        trace3.append(dict(cam(), t=round((time.time() - t0) * 1000)))
        moving = [c for c in trace3[1:]
                  if abs(c["scale"] - trace3[0]["scale"]) > 1e-4
                  or c["t"] < trace3[-1]["t"] - 400]
        results["focus_duration"] = {"trace": trace3}
        save(results["focus_duration"],
             "CMV-AI-03/focus-duration.json", results["focus_duration"])

        browser.close()
    ctx.close()
    server.shutdown()
    print("DONE")


if __name__ == "__main__":
    main()
