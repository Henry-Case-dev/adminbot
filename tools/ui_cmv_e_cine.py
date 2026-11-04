"""CMV-E: кадры анимации (§12.4) и сверка «до/после» на ОДНИХ данных (§12.4, §13).

Две задачи, обе объективные:

1. **Анимация.** Один статичный снимок не доказывает анимацию (§12.4), поэтому
   стенд снимает РЯД кадров во времени вокруг реального узла с наибольшей
   степенью связности: 10 кадров подряд, и на каждом измеряется реальная
   разница пикселей слоя `fx` (мягкая пульсация узла + подсветка выбранных
   связей). Числа разницы — доказательство движения, PNG-кадры — то, что можно
   посмотреть глазами. Дополнительно собирается «полоса кадров» (filmstrip)
   одним PNG: она рисуется в браузере из тех же настоящих кадров.

2. **До/после.** Один и тот же набор (702/2400 из `tests/fixtures/cmv`), тот же
   вьюпорт, тот же DPR, тот же узел и та же камера (`fit`, `r≈2.2`,
   fullscreen, mobile 390/360) на базовой ревизии и на кандидате. Условия
   каждого кадра записываются в JSON, поэтому «одинаковые условия» проверяемы.

Запуск:
  .venv/Scripts/python.exe tools/ui_cmv_e_cine.py \
      --base-repo <pre-CMV worktree> --base-revision 9e238d06 \
      --full-base-repo <A+B+C worktree> --full-base-revision dfba4080 \
      --out plans/features/epic-cm-visual-01/evidence/cmv-e
"""
import argparse
import base64
import json
import os
import sys
import time
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DESKTOP = (1536, 960)
MOBILE = (390, 844)
NARROW = (360, 780)
FIXTURE = 702
FRAMES = 10
FRAME_GAP_MS = 250

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

PROJECT = r"""
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
  return { x: box.left + sx, y: box.top + sy, sx: sx, sy: sy, w: W, h: H,
           inside: sx > 24 && sy > 24 && sx < W - 24 && sy < H - 24,
           scale: sc };
}
"""

CAMERA = r"""
(spec) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  // Базовая ревизия не объявляет `_cogFitScale`: тогда опорный масштаб
  // передаётся снаружи (снят сразу после раскладки), иначе «×2.2 от fit»
  // считалось бы от уже увеличенного масштаба.
  const fit = spec.fit || vm._cogFitScale || net.getScale();
  let pos = spec.center;
  if (spec.id) {
    const cache = (vm._cogScene && vm._cogScene.pos) || net.getPositions() || {};
    if (cache[spec.id]) pos = cache[spec.id];
  }
  if (!pos) pos = net.getViewPosition();
  net.moveTo({ position: { x: pos.x, y: pos.y }, scale: fit * spec.ratio,
               animation: false });
  return { fit: fit, scale: net.getScale(), ratio: net.getScale() / fit };
}
"""

SELECT = r"""
(id) => {
  // Выбор тем же путём, что у пользователя: клик по узлу. Здесь — программный
  // selectNode (нужен для одинакового узла в двух ревизиях, где раскладка
  // разная), карточка открывается тем же обработчиком vis.
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  net.selectNodes([id]);
  return {
    selected: vm._cogSelectedId || null,
    activeEdges: (vm._cogDebugCounters ? vm._cogDebugCounters().fxActiveEdges : null),
    card: !!vm.cogCardOpen,
  };
}
"""

COUNTERS = r"""
() => {
  const vm = window.__adminbotVm;
  const c = (vm._cogDebugCounters ? vm._cogDebugCounters() : {}) || {};
  const qa = (sel) => document.querySelectorAll(sel).length;
  const el = vm._cogEl || document.querySelector('.cognition-graph');
  const canvas = el ? el.querySelector('canvas') : null;
  const card = document.querySelector('#cog-card');
  return {
    selected: vm._cogSelectedId || null,
    card: !!vm.cogCardOpen,
    full: !!vm.graphFullVisible,
    lod: vm._cogScene ? vm._cogScene.lod : null,
    hidden: ((vm._cognitionNodesDS && vm._cognitionNodesDS.get)
      ? vm._cognitionNodesDS.get() : []).filter((r) => r.hidden === true).length,
    labels: c.labelsShown || 0,
    activeEdges: c.fxActiveEdges || 0,
    edgeDraws: c.fxEdgeDraws || 0,
    fxPaints: c.fxPaints || 0,
    pulse: c.pulseCount || 0,
    canvases: qa('canvas'),
    scenes: qa('.cognition-graph'),
    visNetworks: qa('.vis-network'),
    hScroll: Math.max(0, document.documentElement.scrollWidth
                        - window.innerWidth),
    canvasSize: canvas ? [canvas.clientWidth, canvas.clientHeight] : null,
    cardRect: card ? (() => {
      const r = card.getBoundingClientRect();
      return [Math.round(r.x), Math.round(r.y), Math.round(r.width),
              Math.round(r.height)];
    })() : null,
    dpr: window.devicePixelRatio,
    viewport: [window.innerWidth, window.innerHeight],
  };
}
"""

# Разница пикселей слоя `fx` в прямоугольнике вокруг интересующей области.
FX_DIFF = r"""
(spec) => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene || !scene.fxCanvas || !scene.fxCtx) return null;
  const dpr = scene.fxDpr || 1;
  const box = spec.box || [0, 0, scene.width, scene.height];
  const x = Math.max(0, Math.round((box[0] - spec.pad) * dpr));
  const y = Math.max(0, Math.round((box[1] - spec.pad) * dpr));
  const w = Math.min(scene.fxCanvas.width - x,
                     Math.round((box[2] + spec.pad * 2) * dpr));
  const h = Math.min(scene.fxCanvas.height - y,
                     Math.round((box[3] + spec.pad * 2) * dpr));
  if (w <= 0 || h <= 0) return null;
  const data = scene.fxCtx.getImageData(x, y, w, h).data;
  window.__cmvFxPrev = window.__cmvFxPrev || {};
  const key = spec.key || 'main';
  const prev = window.__cmvFxPrev[key];
  window.__cmvFxPrev[key] = data;
  let delta = null, changed = null, energy = 0;
  for (let i = 0; i < data.length; i += 4) energy += data[i] + data[i + 1] + data[i + 2];
  if (prev && prev.length === data.length) {
    let sum = 0, n = 0;
    for (let i = 0; i < data.length; i += 4) {
      const d = Math.abs(data[i] - prev[i]) + Math.abs(data[i + 1] - prev[i + 1])
        + Math.abs(data[i + 2] - prev[i + 2]);
      if (d > 6) n += 1;
      sum += d;
    }
    delta = sum / (data.length / 4 * 3);
    changed = n / (data.length / 4);
  }
  return { w, h, delta: delta === null ? null : Math.round(delta * 1000) / 1000,
           changedShare: changed === null ? null : Math.round(changed * 10000) / 10000,
           meanLuma: Math.round(energy / (data.length / 4) / 3 * 10) / 10 };
}
"""

# Полоса кадров: рисуется в браузере из НАСТОЯЩИХ кадров слоя `fx`.
FILMSTRIP = r"""
(spec) => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  if (!scene || !scene.fxCanvas) return null;
  const dpr = scene.fxDpr || 1;
  const sw = Math.round(spec.w * dpr), sh = Math.round(spec.h * dpr);
  const sx = Math.round(spec.x * dpr), sy = Math.round(spec.y * dpr);
  const strip = document.createElement('canvas');
  strip.width = sw * spec.frames;
  strip.height = sh;
  const ctx = strip.getContext('2d');
  ctx.fillStyle = '#05070d';
  ctx.fillRect(0, 0, strip.width, strip.height);
  for (let i = 0; i < spec.frames; i += 1) {
    ctx.drawImage(scene.fxCanvas, sx, sy, sw, sh, i * sw, 0, sw, sh);
    ctx.strokeStyle = 'rgba(120,170,255,0.35)';
    ctx.strokeRect(i * sw + 0.5, 0.5, sw - 1, sh - 1);
  }
  return strip.toDataURL('image/png');
}
"""


def degrees(fixtures_mod):
    data = fixtures_mod.load(FIXTURE)
    deg = {node["id"]: 0 for node in data["nodes"]}
    for edge in data["edges"]:
        deg[edge["from"]] = deg.get(edge["from"], 0) + 1
        deg[edge["to"]] = deg.get(edge["to"], 0) + 1
    ranked = sorted(deg.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked


def settle(pg, timeout_ms=90000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    pg.wait_for_timeout(400)


def shot(pg, out_dir, name, clip=None):
    path = os.path.join(out_dir, name)
    kwargs = {"path": path}
    if clip:
        kwargs["clip"] = clip
    pg.screenshot(**kwargs)
    return os.path.basename(path)


def select_by_id(pg, nid, fit, ratio=1.8):
    """Поставить камеру на узел и ВЫБРАТЬ его реальным кликом (путь пользователя).

    На уровне обзора узел может быть свёрнут в район, поэтому перед выбором
    камера ставится на `r ≈ 1.8` — там узлы рисуются поштучно у обеих ревизий.
    """
    pg.evaluate(CAMERA, {"ratio": ratio, "fit": fit, "id": nid, "center": None})
    pg.wait_for_timeout(450)
    pos = pg.evaluate(PROJECT, nid)
    clicked = False
    if pos and pos["inside"]:
        pg.mouse.move(pos["x"], pos["y"])
        pg.wait_for_timeout(150)
        pg.mouse.click(pos["x"], pos["y"])
        pg.wait_for_timeout(500)
        clicked = True
    sel = pg.evaluate("() => window.__adminbotVm._cogSelectedId || null")
    if not sel:
        pg.evaluate(SELECT, nid)
        pg.wait_for_timeout(400)
        sel = pg.evaluate("() => window.__adminbotVm._cogSelectedId || null")
    return sel, pos, clicked


def run_animation(pg, out_dir, ranked, revision):
    """Ряд кадров во времени + числа разницы пикселей слоя fx."""
    fit = pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      return vm._cogFitScale || vm.cognitionNetwork.getScale();
    }""")
    target = None
    for nid, deg in ranked[:40]:
        pos = pg.evaluate(PROJECT, nid)
        if pos and pos["inside"]:
            target = {"id": nid, "degree": deg}
            break
    if not target:
        return {"error": "нет видимого узла для кадров анимации"}
    sel, pos, clicked = select_by_id(pg, target["id"], fit, ratio=1.8)
    pg.wait_for_timeout(400)
    pos = pg.evaluate(PROJECT, target["id"])
    if not pos:
        return {"error": "узел не найден после приближения", "selection": sel}
    # Область вокруг выбранного узла (в CSS-px канваса).
    box = [pos["sx"] - 90, pos["sy"] - 70, 180, 140]
    frames = []
    for i in range(FRAMES):
        diff = pg.evaluate(FX_DIFF, {"box": box, "pad": 6, "key": "node"})
        clip = {"x": max(0, pos["x"] - 110), "y": max(0, pos["y"] - 90),
                "width": 220, "height": 180}
        name = "cmv-e-anim-node-%02d.png" % i
        shot(pg, out_dir, name, clip)
        counters = pg.evaluate(COUNTERS)
        frames.append({"i": i, "diff": diff, "activeEdges": counters["activeEdges"],
                       "pulse": counters["pulse"], "fxPaints": counters["fxPaints"],
                       "shot": name})
        pg.wait_for_timeout(FRAME_GAP_MS)
    strip = pg.evaluate(FILMSTRIP, {"x": box[0] - 6, "y": box[1] - 6,
                                    "w": box[2] + 12, "h": box[3] + 12,
                                    "frames": FRAMES})
    strip_name = None
    if strip and strip.startswith("data:image/png;base64,"):
        raw = base64.b64decode(strip.split(",", 1)[1])
        strip_name = "cmv-e-anim-filmstrip.png"
        with open(os.path.join(out_dir, strip_name), "wb") as fh:
            fh.write(raw)
    deltas = [f["diff"]["delta"] for f in frames
              if f["diff"] and f["diff"].get("delta") is not None]
    changed = [f["diff"]["changedShare"] for f in frames
               if f["diff"] and f["diff"].get("changedShare") is not None]
    return {
        "revision": revision,
        "target": {"id": target["id"], "degree": target["degree"]},
        "selection": {"selected": sel, "clicked": clicked},
        "frame_gap_ms": FRAME_GAP_MS,
        "frames": frames,
        "filmstrip": strip_name,
        "stats": {
            "frames": len(frames),
            "deltas": deltas,
            "deltas_after_first": deltas[1:],
            "changed_share": changed,
            "max_delta": max(deltas) if deltas else 0,
            "moving_frames": sum(1 for d in deltas[1:] if d and d > 0.05),
            "pulse": frames[-1]["pulse"] if frames else None,
            "active_edges": frames[-1]["activeEdges"] if frames else None,
        },
    }


def shoot_states(pg, out_dir, prefix, ranked, revision, records):
    """Одинаковые условия съёмки для двух ревизий."""
    fit = pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      return vm._cogFitScale || vm.cognitionNetwork.getScale();
    }""")
    ids = [nid for nid, _ in ranked]

    # 1. fit
    pg.evaluate(CAMERA, {"ratio": 1.0, "fit": fit, "id": None, "center": None})
    pg.wait_for_timeout(500)
    rec = {"rev": revision, "state": "fit", "ratio": 1.0}
    rec.update(pg.evaluate(COUNTERS))
    rec["shot"] = shot(pg, out_dir, "%s-fit.png" % prefix)
    records.append(rec)

    # 2. выбранный узел: камера r ≈ 1.8 (узлы нарисованы поштучно), выбор кликом
    chosen, sel, clicked = None, None, False
    for nid in ids[:12]:
        sel, _pos, clicked = select_by_id(pg, nid, fit, ratio=1.8)
        if sel:
            chosen = nid
            break
    rec = {"rev": revision, "state": "selected", "ratio": 1.8,
           "target": chosen, "selected": sel, "clicked": clicked}
    rec.update(pg.evaluate(COUNTERS))
    rec["shot"] = shot(pg, out_dir, "%s-selected.png" % prefix)
    records.append(rec)

    # 3. зум ×2.6 от fit вокруг того же узла (выбор сохраняется)
    if chosen:
        pg.evaluate(CAMERA, {"ratio": 2.6, "fit": fit, "id": chosen,
                             "center": None})
        pg.wait_for_timeout(550)
    rec = {"rev": revision, "state": "zoom", "ratio": 2.6, "target": chosen}
    rec.update(pg.evaluate(COUNTERS))
    rec["shot"] = shot(pg, out_dir, "%s-zoom.png" % prefix)
    records.append(rec)

    # 4. полный экран (desktop) с тем же узлом и камерой r ≈ 1.8
    pg.evaluate("() => window.__adminbotVm.openGraphFull()")
    pg.wait_for_timeout(800)
    if chosen:
        pg.evaluate(CAMERA, {"ratio": 1.8, "fit": fit, "id": chosen,
                             "center": None})
        pg.wait_for_timeout(600)
    rec = {"rev": revision, "state": "fullscreen", "ratio": 1.8,
           "target": chosen}
    rec.update(pg.evaluate(COUNTERS))
    rec["shot"] = shot(pg, out_dir, "%s-fullscreen.png" % prefix)
    records.append(rec)

    # 4b. тот же полный экран БЕЗ выбора: у кандидата колонка инспектора сужает
    # сцену (§3.1 ТЗ), поэтому «кадр в кадр» по ширине сцены сравнивается здесь.
    pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      if (vm.cognitionNetwork && vm.cognitionNetwork.unselectAll) {
        vm.cognitionNetwork.unselectAll();
      }
      if (typeof vm.graphClearDetail === 'function') vm.graphClearDetail();
    }""")
    pg.wait_for_timeout(600)
    if chosen:
        pg.evaluate(CAMERA, {"ratio": 1.8, "fit": fit, "id": chosen,
                             "center": None})
        pg.wait_for_timeout(500)
    rec = {"rev": revision, "state": "fullscreen-clean", "ratio": 1.8}
    rec.update(pg.evaluate(COUNTERS))
    rec["shot"] = shot(pg, out_dir, "%s-fullscreen-clean.png" % prefix)
    records.append(rec)
    pg.evaluate("() => window.__adminbotVm.closeGraphFull()")
    pg.wait_for_timeout(600)


def run_root(browser, base, out_dir, fixtures_mod, revision, label, mobile_only):
    payload = fixtures_mod.load(FIXTURE)
    payload["generated_at"] = int(time.time())
    W15.set_cog_payload(payload)
    ranked = degrees(fixtures_mod)
    report = {"revision": revision, "records": []}
    if not mobile_only:
        ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                            "height": DESKTOP[1]},
                                  device_scale_factor=1)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        settle(pg)
        pg.evaluate("() => { const vm = window.__adminbotVm;"
                    " const el = vm._cogEl || document.querySelector"
                    "('.cognition-graph'); if (el) el.scrollIntoView"
                    "({ block: 'center' }); }")
        pg.wait_for_timeout(400)
        prefix = "cmv-e-%s" % label
        shoot_states(pg, out_dir, prefix, ranked, revision, report["records"])
        pg.close()
        ctx.close()
    for tag, (w, h) in (("mobile390", MOBILE), ("mobile360", NARROW)):
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  device_scale_factor=2, is_mobile=True,
                                  has_touch=True)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        settle(pg)
        pg.evaluate("() => { const vm = window.__adminbotVm;"
                    " const el = vm._cogEl || document.querySelector"
                    "('.cognition-graph'); if (el) el.scrollIntoView"
                    "({ block: 'center' }); }")
        pg.wait_for_timeout(500)
        fit_mobile = pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          return vm._cogFitScale || vm.cognitionNetwork.getScale();
        }""")
        pg.evaluate(CAMERA, {"ratio": 1.0, "fit": fit_mobile, "id": None,
                             "center": None})
        pg.wait_for_timeout(500)
        rec = {"rev": revision, "state": tag, "viewport": [w, h], "dpr": 2}
        rec.update(pg.evaluate(COUNTERS))
        rec["shot"] = shot(pg, out_dir, "cmv-e-%s-%s.png" % (label, tag))
        report["records"].append(rec)
        pg.close()
        ctx.close()
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--base-repo", default=None,
                    help="базовая ревизия «до» (pre-CMV)")
    ap.add_argument("--base-revision", default=None)
    ap.add_argument("--full-base-repo", default=None,
                    help="ревизия «до» для полного экрана (A+B+C, без D)")
    ap.add_argument("--full-base-revision", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = (os.path.abspath(args.out) if args.out else
               os.path.join(repo, "plans", "features", "epic-cm-visual-01",
                            "evidence", "cmv-e"))
    os.makedirs(out_dir, exist_ok=True)

    # Стенд сам является частью кандидата, поэтому сервер ПОДНИМАЕТСЯ на каждом
    # корне по очереди: сначала кандидат (анимация + «после»), затем базы («до»).
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    sys.path.insert(0, os.path.join(os.path.dirname(here), "tests",
                                    "fixtures", "cmv"))
    import cog_map_fixtures as FIX                        # noqa: E402
    from playwright.sync_api import sync_playwright

    report = {"fixture": FIXTURE,
              "fixture_sha256": FIX.sha256(FIX.load(FIXTURE)),
              "frame_gap_ms": FRAME_GAP_MS,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def serve_and_run(root, fn):
        sys.path.insert(0, root)
        sys.path.insert(0, os.path.join(root, "tools"))
        os.chdir(root)
        global M, W15
        for mod in ("ui_round1025_matrix", "ui_evol_w15_composition_e2e"):
            sys.modules.pop(mod, None)
        import ui_round1025_matrix as Mx                  # noqa: E402
        import ui_evol_w15_composition_e2e as Wx          # noqa: E402
        M, W15 = Mx, Wx
        M.PORT = 0
        server = M._start_server()
        base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--enable-gpu", "--enable-gpu-rasterization",
                          "--ignore-gpu-blocklist", "--use-angle=d3d11"])
                try:
                    return fn(browser, base)
                finally:
                    browser.close()
        finally:
            server.shutdown()

    try:
        def cand(browser, base):
            """Анимация (ряд кадров) и «после» — в одном процессе, чтобы кадры
            сравнивались на одном и том же состоянии машины."""
            payload = FIX.load(FIXTURE)
            payload["generated_at"] = int(time.time())
            W15.set_cog_payload(payload)
            ranked = degrees(FIX)
            ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                                "height": DESKTOP[1]},
                                      device_scale_factor=1)
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", W15._routes())
            pg = ctx.new_page()
            pg.goto(base + "#/", wait_until="load")
            settle(pg)
            pg.evaluate("() => { const vm = window.__adminbotVm;"
                        " if (vm._cogEl) vm._cogEl.scrollIntoView"
                        "({ block: 'center' }); }")
            pg.wait_for_timeout(500)
            anim = run_animation(pg, out_dir, ranked,
                                 args.revision or "candidate")
            pg.close()
            ctx.close()
            records = run_root(browser, base, out_dir, FIX,
                               args.revision or "candidate", "after",
                               False)["records"]
            return {"animation": anim, "records": records}

        candidate = serve_and_run(repo, cand)
        report["candidate"] = {"animation": candidate["animation"]}
        report["after"] = {"records": candidate["records"]}

        if args.base_repo:
            report["before"] = serve_and_run(
                args.base_repo, lambda b, s: {"records": run_root(
                    b, s, out_dir, FIX, args.base_revision or "base",
                    "before", False)["records"]})
        if args.full_base_repo:
            report["before_fullscreen"] = serve_and_run(
                args.full_base_repo, lambda b, s: {"records": run_root(
                    b, s, out_dir, FIX, args.full_base_revision or "fullbase",
                    "beforefull", False)["records"]})
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()

    out = os.path.join(out_dir, "cmv-e-cine.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if report.get("error"):
        print("ERROR:\n" + report["error"][-1800:])
        return 3
    anim = (report.get("candidate") or {}).get("animation") or {}
    stats = anim.get("stats") or {}
    print("анимация: кадров %s, максимальная разница слоя fx %.3f, "
          "движущихся кадров %s, pulse %s, activeEdges %s" % (
              stats.get("frames"), stats.get("max_delta"),
              stats.get("moving_frames"), stats.get("pulse"),
              stats.get("active_edges")))
    print("shots: анимация %s, после %s, до %s, до-fullscreen %s" % (
        len([f for f in (anim.get("frames") or [])]),
        len(((report.get("after") or {}).get("records") or [])),
        len(((report.get("before") or {}).get("records") or [])),
        len(((report.get("before_fullscreen") or {}).get("records") or []))))
    print("-> %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
