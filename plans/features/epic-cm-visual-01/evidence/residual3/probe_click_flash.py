"""Микропроба: клик-пульс (whole-canvas diff + свежая полоса + дампы fx)."""
import base64
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

TARGET_ID = "paradigm:-1001234567890:184"

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  return !vm._cogScene || vm._cogScene.settled === true;
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
           inside: sx > 60 && sy > 60
             && sx < canvas.clientWidth - 60
             && sy < canvas.clientHeight - 60 };
}
"""

# whole-canvas diff против опорного кадра + mean luma
JS_FX_DIFF_ALL = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm._cogScene;
  if (!scene || !scene.fxCanvas || !scene.fxCtx) return null;
  const w = scene.fxCanvas.width, h = scene.fxCanvas.height;
  const data = scene.fxCtx.getImageData(0, 0, w, h).data;
  window.__ref = window.__ref || null;
  const old = window.__ref;
  window.__ref = data;
  if (!old) return { first: true, meanLuma: null };
  let dSum = 0, n = 0, energy = 0;
  const box = scene._probeBox || null;
  for (let i = 0; i < data.length; i += 16) {
    const d = Math.abs(data[i] - old[i]) + Math.abs(data[i + 1] - old[i + 1])
      + Math.abs(data[i + 2] - old[i + 2]);
    dSum += d;
    energy += data[i] + data[i + 1] + data[i + 2];
    n += 3;
  }
  return { meanLuma: +(energy / n).toFixed(2),
           meanDelta: +(dSum / n).toFixed(3) };
}
"""

JS_DUMP = r"""
([sx, sy]) => {
  const vm = window.__adminbotVm;
  const scene = vm._cogScene;
  const dpr = scene.fxDpr || 1;
  const cx = Math.round(sx * dpr), cy = Math.round(sy * dpr);
  const rr = 60;
  const x0 = Math.max(0, cx - rr), y0 = Math.max(0, cy - rr);
  const w = Math.min(scene.fxCanvas.width - x0, rr * 2);
  const h = Math.min(scene.fxCanvas.height - y0, rr * 2);
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d').drawImage(scene.fxCanvas, x0, y0, w, h, 0, 0, w, h);
  return c.toDataURL('image/png');
}
"""


def main():
    M.PORT = 0
    server = M._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
    payload = FIX.load(702)
    payload["generated_at"] = 1750000000
    W15.set_cog_payload(payload)
    out = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--enable-gpu", "--enable-gpu-rasterization",
                  "--ignore-gpu-blocklist", "--use-angle=d3d11"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        pg.wait_for_function(READY, timeout=120000)
        pg.evaluate("""() => { const vm = window.__adminbotVm;
          const el = vm._cogEl || document.querySelector('.cognition-graph');
          if (el) el.scrollIntoView({ block: 'center' }); }""")
        pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const cache = (vm._cogScene && vm._cogScene.pos)
            || net.getPositions() || {};
          const pos = cache['%s'];
          net.moveTo({ position: { x: pos.x, y: pos.y },
                       scale: vm._cogFitScale * 1.6, animation: false });
        }""" % TARGET_ID)
        pg.wait_for_timeout(1000)
        # стабилизация позиций
        prev = None
        for _ in range(10):
            cur = pg.evaluate(
                "() => JSON.stringify(Object.entries("
                "window.__adminbotVm._cogScene.pos).slice(0, 40))")
            if cur == prev:
                break
            prev = cur
            pg.wait_for_timeout(400)
        ns = pg.evaluate(JS_PROJ, TARGET_ID)
        out["prePos"] = ns
        pg.evaluate(JS_FX_DIFF_ALL)   # установить опорный кадр
        timeline = []
        t0 = time.time()
        pg.mouse.click(ns["x"], ns["y"])
        for i in range(16):
            d = pg.evaluate(JS_FX_DIFF_ALL)
            d["t"] = round((time.time() - t0) * 1000)
            timeline.append(d)
            pg.wait_for_timeout(50)
        st = pg.evaluate("""() => { const vm = window.__adminbotVm;
          const s = vm._cogScene;
          return { selected: vm._cogSelectedId,
                   pulseHit: s.pulseHit ? { id: s.pulseHit.id,
                     kind: s.pulseHit.kind,
                     duration: s.pulseHit.duration } : null,
                   fxPaints: (s.fx && s.fx.counters) ? s.fx.counters().paints
                     : null }; }""")
        out["timeline"] = timeline
        out["state"] = st
        with open(os.path.join(HERE, "CMV-AI-02", "flash-diff.json"), "w",
                  encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        # дампы fx вокруг узла: до (текущий кадр) — уже после клика; снимем
        # два: сразу и через 700 мс (после импульса)
        d1 = pg.evaluate(JS_DUMP, [ns["sx"], ns["sy"]])
        pg.wait_for_timeout(900)
        d2 = pg.evaluate(JS_DUMP, [ns["sx"], ns["sy"]])
        for name, d in (("flash-t0.png", d1), ("flash-after.png", d2)):
            if d and d.startswith("data:image/png;base64,"):
                with open(os.path.join(HERE, "CMV-AI-02", name), "wb") as f:
                    f.write(base64.b64decode(d.split(",", 1)[1]))
        browser.close()
    with open(os.path.join(HERE, "CMV-AI-02", "flash-diff.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["timeline"][:8], ensure_ascii=False))
    print("state:", json.dumps(out["state"], ensure_ascii=False))
    server.shutdown()


if __name__ == "__main__":
    main()
