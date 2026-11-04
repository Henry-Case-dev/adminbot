"""CMV-PERF: снимки сцены карты для сравнения «до/после» (pixel parity).

Снимает ТОЛЬКО контейнер карты (`.cognition-graph`) в трёх состояниях камеры на
двух устройствах, при фиксированной фикстуре. Отдельный инструмент сравнения
(`ui_cmv_perf_parity.py`) считает по парам снимков долю различающихся пикселей:
правки производительности не должны менять картинку.

Запуск:
  python tools/ui_cmv_perf_shots.py --repo <ROOT> --out <DIR> --label cand
"""
import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  return vm._cogScene ? vm._cogScene.settled === true : true;
}
"""

SETTLE = r"""
() => {
  const vm = window.__adminbotVm;
  const el = vm._cogEl;
  if (!el) return 'no-el';
  const c = el.querySelector('canvas');
  if (!c) return 'no-canvas';
  return c.clientWidth + 'x' + c.clientHeight + '@'
    + Math.round(vm.cognitionNetwork.getScale() * 1e4);
}
"""

CAMERA = r"""
(spec) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const fit = vm._cogFitScale || net.getScale();
  net.moveTo({ position: spec.pos || net.getViewPosition(),
               scale: fit * spec.ratio, animation: false });
  return net.getScale();
}
"""

CENTER = r"""
() => {
  const vm = window.__adminbotVm;
  const s = vm._cogScene || {};
  const net = vm.cognitionNetwork;
  const fit = vm._cogFitScale || 1;
  const bbox = s.bbox;
  if (!bbox) return null;
  net.moveTo({ position: { x: bbox.cx, y: bbox.cy }, scale: fit, animation: false });
  return true;
}
"""

STATES = (("overview", 1.0), ("working", 1.6), ("detail", 2.6))
DEVICES = (("desktop", 1536, 960, 1, False), ("phone", 390, 844, 2, True))

# Детерминированный кадр для пиксельного сравнения: раскладка vis зависит от
# времени стабилизации (adaptiveTimestep), поэтому позиции ставятся ЯВНО
# (окружность), движение отключается (reduced-motion), камера — фиксированная.
FREEZE = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const nodes = (vm._cogView || {}).nodes || [];
  const ds = vm._cognitionNodesDS;
  const rows = [];
  const R = 600;
  for (let i = 0; i < nodes.length; i += 1) {
    const a = (2 * Math.PI * i) / Math.max(1, nodes.length);
    const ring = 1 + (i % 3) * 0.18;
    rows.push({ id: nodes[i].id, x: Math.cos(a) * R * ring,
                y: Math.sin(a) * R * ring });
  }
  try { net.setOptions({ physics: { enabled: false } }); } catch (e) { /* noop */ }
  ds.update(rows);
  vm._cogSyncPositions();
  vm.reducedMotion = true;
  // Фиксированный обзор: масштаб узлов/LOD/агрегаты зависят от fitScaleRef,
  // поэтому он тоже фиксируется (иначе раскладка двух прогонов даёт разный кадр).
  vm._cogFitScale = 0.35;
  vm._cogFitBBox = null;
  // Обзор заморожен: наблюдатель размера/события не должны его пересчитать.
  vm._cogRefreshFitScale = function () { return vm._cogFitScale; };
  vm._cogScene.labelKey = null;      // план подписей — по новой геометрии
  vm._cogScene.labelAnchor = null;
  vm._cogApplyNodeSizes();
  if (typeof vm._cogBuildAggregates === 'function') vm._cogBuildAggregates(true);
  return rows.length;
}
"""

FIXED_CAMERA = r"""
(spec) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  net.moveTo({ position: { x: 0, y: 0 }, scale: 0.35 * spec.ratio,
               animation: false });
  vm._cogApplyNodeSizes();
  if (typeof vm._cogBuildAggregates === 'function') vm._cogBuildAggregates(true);
  if (typeof vm._cogApplyLodVisibility === 'function') vm._cogApplyLodVisibility();
  vm._cogPaintStatic();
  return net.getScale();
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--label", default="cand")
    ap.add_argument("--fixture", type=int, default=702)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        repo, "plans", "features", "evol", "evidence", "cmv-perf")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    sys.path.insert(0, os.path.join(os.path.dirname(here), "tests",
                                    "fixtures", "cmv"))
    os.chdir(repo)
    import ui_round1025_matrix as M                       # noqa: E402
    import ui_evol_w15_composition_e2e as W15             # noqa: E402
    import cog_map_fixtures as FIX                        # noqa: E402
    from playwright.sync_api import sync_playwright

    payload = FIX.load(args.fixture)
    payload["generated_at"] = int(time.time())
    W15.set_cog_payload(payload)
    M.PORT = 0
    server = M._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
    report = {"repo": repo, "label": args.label, "shots": []}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--enable-gpu", "--enable-gpu-rasterization",
                      "--ignore-gpu-blocklist", "--use-angle=d3d11"])
            for name, w, h, dpr, mobile in DEVICES:
                ctx = browser.new_context(viewport={"width": w, "height": h},
                                          device_scale_factor=dpr,
                                          is_mobile=mobile, has_touch=mobile)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                pg.goto(base + "#/", wait_until="load")
                pg.wait_for_function(READY, timeout=120000)
                pg.wait_for_timeout(500)
                # Детерминированная геометрия + статичный кадр.
                frozen = pg.evaluate(FREEZE)
                report.setdefault("frozen_nodes", frozen)
                pg.wait_for_timeout(500)
                for state, ratio in STATES:
                    pg.evaluate(FIXED_CAMERA, {"ratio": ratio})
                    pg.wait_for_timeout(500)
                    el = pg.query_selector('.cognition-graph')
                    if el is None:
                        continue
                    path = os.path.join(
                        out_dir, "%s-%s-%s.png" % (args.label, name, state))
                    el.screenshot(path=path)
                    report["shots"].append({
                        "device": name, "state": state, "ratio": ratio,
                        "path": os.path.basename(path),
                        "box": el.bounding_box(),
                    })
                    print("  %-8s %-9s -> %s" % (name, state,
                                                 os.path.basename(path)))
                # Вспышка hover/выбора: подпись выбранного видна всегда.
                pg.evaluate("""() => {
                  const vm = window.__adminbotVm;
                  const id = (vm._cogView.nodes[0] || {}).id;
                  if (id == null) return;
                  vm._cogSetHover(id);
                  vm._cogPaintStatic();
                }""")
                pg.wait_for_timeout(400)
                el = pg.query_selector('.cognition-graph')
                path = os.path.join(out_dir,
                                    "%s-%s-hover.png" % (args.label, name))
                el.screenshot(path=path)
                report["shots"].append({"device": name, "state": "hover",
                                        "path": os.path.basename(path)})
                print("  %-8s %-9s -> %s" % (name, "hover",
                                             os.path.basename(path)))
                pg.close()
                ctx.close()
            browser.close()
    finally:
        server.shutdown()
    with open(os.path.join(out_dir, "%s-shots.json" % args.label), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("shots:", len(report["shots"]), "->", out_dir)


if __name__ == "__main__":
    main()
