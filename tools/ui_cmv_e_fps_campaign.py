"""CMV-E: замер FPS «Когнитивной карты» на фикстурах 10 / 100 / 702 × 2400 (§10.2).

Один прогон = один набор (фикстура × режим × состояние камеры). Инструмент
намеренно НЕ является новым фреймворком: он переиспользует сервер W15,
маршруты-заглушки API и приёмы стендов `ui_cmv_b_scene_fps.py` /
`ui_cmv_d_fullscreen_e2e.py`, добавляя только то, что требует §10.2:

  * три состояния камеры: обзор (`r = 1.0` от fit), рабочий (`r ≈ 1.6`),
    детальный (`r ≈ 2.6`);
  * честные p50/p95/p99 кадра в FPS (перцентиль СЧИТАЕТСЯ по межкадровым
    задержкам и переводится в FPS, а не «средний кадр»);
  * устройство и фактическая растеризация GPU в отчёте (UA, WebGL renderer,
    флаги запуска, размер сцены, DPR).

Сравнение A/B делает `tools/ui_cmv_e_fps_ab.py`: он чередует прогоны кандидата
и базовой ревизии на одном стенде и складывает результаты в один JSON.

Запуск одного прогона:
  .venv/Scripts/python.exe tools/ui_cmv_e_fps_campaign.py \
      --repo <ROOT> --label cand --out <DIR|FILE> [--ms 2000] [--headed]
"""
import argparse
import json
import os
import platform
import statistics
import sys
import time
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DESKTOP = (1536, 960)
FIXTURES = (10, 100, 702)
#: Имя состояния -> кратность масштаба относительно fit.
STATES = (("overview", 1.0), ("working", 1.6), ("detail", 2.6))
MODES = ("embedded", "fullscreen")
#: Для этих наборов меряем ещё и fullscreen: там размер сцены у базовой
#: ревизии и у кандидата одинаков, поэтому сравнение честно «кадр в кадр».
FULL_FIXTURES = {702}

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  const net = vm.cognitionNetwork;
  if (typeof net.getScale !== 'function' || net.getScale() <= 0) return false;
  // Кандидат (CMV-A/B): сцена объявляет готовность сама. Базовая ревизия
  // такого флага не имеет — для неё достаточно сети и положительного масштаба.
  if (vm._cogScene) return vm._cogScene.settled === true;
  return true;
}
"""

GEOMETRY = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const el = vm._cogEl || document.querySelector('.cognition-graph');
  const canvas = el ? el.querySelector('canvas') : null;
  const rows = (vm._cognitionNodesDS && vm._cognitionNodesDS.get)
    ? vm._cognitionNodesDS.get() : [];
  const edgeRows = (vm._cognitionEdgesDS && vm._cognitionEdgesDS.get)
    ? vm._cognitionEdgesDS.get() : [];
  let hidden = 0;
  rows.forEach((r) => { if (r.hidden === true) hidden += 1; });
  const counters = (vm._cogDebugCounters ? vm._cogDebugCounters() : {}) || {};
  return {
    scale: net.getScale(),
    view: net.getViewPosition(),
    canvas: canvas ? [canvas.clientWidth, canvas.clientHeight] : null,
    el: el ? [el.clientWidth, el.clientHeight] : null,
    rows: rows.length,
    edges: edgeRows.length,
    hidden: hidden,
    dpr: window.devicePixelRatio,
    lod: vm._cogScene ? vm._cogScene.lod : null,
    scene: !!vm._cogScene,
    full: !!vm.graphFullVisible,
    labels: counters.labelsShown || 0,
    draws: counters.draws || 0,
    fxPaints: counters.fxPaints || 0,
  };
}
"""

ENV = r"""
() => {
  let renderer = 'n/a';
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'n/a';
  } catch (e) { renderer = 'err: ' + e; }
  return {
    ua: navigator.userAgent,
    renderer: renderer,
    cores: navigator.hardwareConcurrency || 0,
    memory: navigator.deviceMemory || null,
    dpr: window.devicePixelRatio,
    vw: window.innerWidth, vh: window.innerHeight,
  };
}
"""

# Панорамирование с реальным движением камеры: vis перерисовывает кадр сам,
# поэтому задержки rAF отражают стоимость кадра, а не «сон» таймера.
PAN = r"""
(spec) => new Promise((resolve) => {
  const ms = spec.ms;
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  if (!net) { resolve({ error: 'no net' }); return; }
  const start = performance.now();
  const deltas = [];
  let last = start;
  const base = net.getViewPosition();
  const scale = net.getScale();
  let painted = 0;
  // Честный счётчик ОТРИСОВАННЫХ кадров: cadence rAF сама по себе не доказывает,
  // что vis перерисовал сцену. `afterDrawing` — единственный сигнал кадра vis.
  const onDraw = function () { painted += 1; };
  if (typeof net.on === 'function') net.on('afterDrawing', onDraw);
  let moved = 0;
  const ampX = spec.ampX || 220;
  const ampY = spec.ampY || 160;
  function step() {
    const now = performance.now();
    deltas.push(now - last);
    last = now;
    const phase = (now - start) / 260;
    net.moveTo({ position: { x: base.x + Math.sin(phase) * ampX,
                             y: base.y + Math.cos(phase * 0.7) * ampY },
                 scale: scale, animation: false });
    moved += 1;
    if (now - start < ms) requestAnimationFrame(step);
    else {
      if (typeof net.off === 'function') net.off('afterDrawing', onDraw);
      const pos = net.getViewPosition();
      resolve({ deltas: deltas, elapsed: now - start, painted: painted,
                moves: moved,
                drift: Math.abs(pos.x - base.x) + Math.abs(pos.y - base.y) });
    }
  }
  requestAnimationFrame(step);
})
"""


def _stats(deltas):
    """FPS-перцентили из межкадровых задержек (мс)."""
    clean = [d for d in deltas if d > 0]
    if not clean:
        return {}
    ordered = sorted(clean)

    def at(q):
        idx = min(len(ordered) - 1, max(0, int(round(len(ordered) * q)) - 1))
        return ordered[idx]

    def fps(ms):
        return 1000.0 / ms if ms > 0 else 0.0

    return {
        "frames": len(clean),
        "median": round(fps(statistics.median(clean)), 1),
        "p95": round(fps(at(0.95)), 1),
        "p99": round(fps(at(0.99)), 1),
        "worst": round(fps(ordered[-1]), 1),
        "p50ms": round(statistics.median(clean), 2),
        "p95ms": round(at(0.95), 2),
        "p99ms": round(at(0.99), 2),
        "jank": sum(1 for d in clean if d > 1000.0 / 30),
    }


def settle(pg, timeout_ms=90000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    # Геометрия перестаёт меняться (ResizeObserver карточки/панели).
    pg.wait_for_function(r"""
      () => {
        const vm = window.__adminbotVm;
        const el = vm._cogEl;
        if (!el) return true;
        const c = el.querySelector('canvas');
        if (!c) return false;
        const key = c.clientWidth + 'x' + c.clientHeight + '@'
          + Math.round(vm.cognitionNetwork.getScale() * 1e4);
        window.__cmvEKey = window.__cmvEKey || { key: '', n: 0 };
        if (window.__cmvEKey.key === key) window.__cmvEKey.n += 1;
        else { window.__cmvEKey.key = key; window.__cmvEKey.n = 1; }
        return window.__cmvEKey.n >= 3;
      }
    """, timeout=timeout_ms)
    pg.wait_for_timeout(250)


def set_camera(pg, ratio):
    """Поставить камеру ровно в `fit * ratio` и дождаться кадра."""
    return pg.evaluate("""(ratio) => {
      const vm = window.__adminbotVm;
      const net = vm.cognitionNetwork;
      const fit = vm._cogFitScale || net.getScale();
      const pos = net.getViewPosition();
      net.moveTo({ position: pos, scale: fit * ratio, animation: false });
      return { fit: fit, want: fit * ratio };
    }""", ratio)


def trim_edges(payload, cap):
    """Контроль реалистичной плотности: оставить структурные рёбра (кольца,
    хабы, мосты идут первыми), а не «добор» случайных пар. Нужен, чтобы
    отделить стоимость визуала от искусственной плотности фикстуры §10.2."""
    if len(payload["edges"]) <= cap:
        return payload, False
    payload = dict(payload)
    payload["edges"] = payload["edges"][:cap]
    shown = dict(payload["shown_of"])
    shown["edges"] = len(payload["edges"])
    payload["shown_of"] = shown
    return payload, True


def measure(browser, base, fixtures, ms, modes, out_dir, diag=False,
            android=False, realistic=0):
    report = {"cases": [], "env": None}
    for n in fixtures:
        payload = FIX.load(n)
        payload["generated_at"] = int(time.time())
        trimmed = False
        if realistic:
            payload, trimmed = trim_edges(payload, realistic * n)
        W15.set_cog_payload(payload)
        fx_modes = modes if n in FULL_FIXTURES else ("embedded",)
        for mode in fx_modes:
            ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                                "height": DESKTOP[1]},
                                      device_scale_factor=1)
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", W15._routes())
            pg = ctx.new_page()
            errors = []
            pg.on("console", lambda m: errors.append(m.text)
                  if m.type == "error" else None)
            pg.goto(base + "#/", wait_until="load")
            settle(pg)
            if report["env"] is None:
                report["env"] = pg.evaluate(ENV)
            if mode == "fullscreen":
                pg.evaluate("() => window.__adminbotVm.openGraphFull()")
                settle(pg)
            pg.evaluate("() => { const el = window.__adminbotVm._cogEl;"
                        " if (el && el.scrollIntoView)"
                        " el.scrollIntoView({ block: 'center' }); }")
            pg.wait_for_timeout(320)
            fit = pg.evaluate("""() => {
              const vm = window.__adminbotVm;
              const net = vm.cognitionNetwork;
              // fit-масштаб базовой ревизии не объявлен: он равен текущему
              // масштабу сразу после раскладки — тот же смысл, что у кандидата.
              return vm._cogFitScale || net.getScale();
            }""")
            for name, ratio in STATES:
                set_camera(pg, ratio)
                pg.wait_for_timeout(450)
                geom = pg.evaluate(GEOMETRY)
                runs, raw = [], []
                for _ in range(2):
                    res = pg.evaluate(PAN, {"ms": ms})
                    stat = _stats(res.get("deltas") or [])
                    stat["paintedFps"] = round(
                        (res.get("painted", 0) * 1000.0)
                        / max(1.0, res.get("elapsed", 1)), 1)
                    stat["moves"] = res.get("moves", 0)
                    stat["drift"] = round(res.get("drift", 0), 1)
                    runs.append(stat)
                best = max(runs, key=lambda r: r.get("median", 0))
                case = {
                    "fixture": n, "mode": mode, "state": name,
                    "ratio_want": ratio,
                    "ratio_got": round(geom["scale"] / fit, 3) if fit else 0,
                    "fit": round(fit, 5),
                    "canvas": geom["canvas"], "el": geom["el"],
                    "rows": geom["rows"], "edges": geom["edges"],
                    "trimmed": trimmed,
                    "hidden": geom["hidden"],
                    "lod": geom["lod"], "labels": geom["labels"],
                    "stats": best, "runs": runs,
                }
                report["cases"].append(case)
                print("  %-9s %-10s %-9s median %5.1f  p95 %5.1f  p99 %5.1f  "
                      "painted %5.1f  (canvas %s, hidden %d, lod %r)" % (
                          "%d узлов" % n, mode, name,
                          best.get("median", 0), best.get("p95", 0),
                          best.get("p99", 0), best.get("paintedFps", 0),
                          geom["canvas"], geom["hidden"], geom["lod"]))
                # Диагностика стоимости именно нашего слоя `fx` (как в стенде
                # CMV-B): тот же кадр без декора. Только для рабочего состояния
                # во встроенной карте — там измеренный запас самый тонкий.
                if diag and mode == "embedded" and name == "working":
                    pg.evaluate("() => { const s = window.__adminbotVm"
                                "._cogScene; if (s) { s._fxKeep = s.fx;"
                                " s.fx = null; } }")
                    pg.wait_for_timeout(300)
                    res = pg.evaluate(PAN, {"ms": ms})
                    stat = _stats(res.get("deltas") or [])
                    stat["paintedFps"] = round(
                        (res.get("painted", 0) * 1000.0)
                        / max(1.0, res.get("elapsed", 1)), 1)
                    pg.evaluate("() => { const s = window.__adminbotVm"
                                "._cogScene; if (s) { s.fx = s._fxKeep; } }")
                    report["cases"].append({
                        "fixture": n, "mode": mode, "state": name,
                        "variant": "no-fx", "stats": stat,
                        "canvas": geom["canvas"], "hidden": geom["hidden"],
                        "lod": geom["lod"], "runs": [stat],
                    })
                    print("      диагностика без слоя fx: median %5.1f  "
                          "p95 %5.1f  p99 %5.1f  painted %5.1f" % (
                              stat.get("median", 0), stat.get("p95", 0),
                              stat.get("p99", 0), stat.get("paintedFps", 0)))
            if errors:
                report.setdefault("console_errors", []).extend(
                    {"fixture": n, "mode": mode, "text": e[:300]}
                    for e in errors[:5])
            pg.close()
            ctx.close()
    if android:
        for case in run_android(browser, base, fixtures, ms, realistic):
            report["cases"].append(case)
    return report


def run_android(browser, base, fixtures, ms, realistic=0):
    """Средний Android (§10.2: ≥30 FPS на активной сцене) — эмуляция, а не
    реальное устройство: телефонный вьюпорт 390×844 при DPR 2 плюс торможение
    CPU в 4 раза через CDP. Так проверяется именно СТОИМОСТЬ кадра, а не
    скорость конкретной модели; в отчёте это указано честно.
    """
    cases = []
    for n in fixtures:
        payload = FIX.load(n)
        payload["generated_at"] = int(time.time())
        trimmed = False
        if realistic:
            payload, trimmed = trim_edges(payload, realistic * n)
        W15.set_cog_payload(payload)
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  device_scale_factor=2, is_mobile=True,
                                  has_touch=True)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        settle(pg)
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        pg.evaluate("""() => { const vm = window.__adminbotVm;
          const el = vm._cogEl || document.querySelector('.cognition-graph');
          if (el) el.scrollIntoView({ block: 'center' }); }""")
        pg.wait_for_timeout(500)
        fit = pg.evaluate("""() => {
          const vm = window.__adminbotVm;
          return vm._cogFitScale || vm.cognitionNetwork.getScale();
        }""")
        for name, ratio in STATES:
            pg.evaluate("""(spec) => {
              const vm = window.__adminbotVm;
              const net = vm.cognitionNetwork;
              net.moveTo({ position: net.getViewPosition(),
                           scale: spec.fit * spec.ratio, animation: false });
            }""", {"fit": fit, "ratio": ratio})
            pg.wait_for_timeout(450)
            geom = pg.evaluate(GEOMETRY)
            res = pg.evaluate(PAN, {"ms": ms, "ampX": 70, "ampY": 50})
            stat = _stats(res.get("deltas") or [])
            stat["paintedFps"] = round(
                (res.get("painted", 0) * 1000.0)
                / max(1.0, res.get("elapsed", 1)), 1)
            case = {"fixture": n, "mode": "android", "state": name,
                    "ratio_got": round(geom["scale"] / fit, 3) if fit else 0,
                    "canvas": geom["canvas"], "hidden": geom["hidden"],
                    "edges": geom["edges"], "trimmed": trimmed,
                    "lod": geom["lod"], "cpu_throttle": 4,
                    "stats": stat}
            cases.append(case)
            print("  %-9s android    %-9s median %5.1f  p95 %5.1f  p99 %5.1f  "
                  "painted %5.1f  (cpu ×4)" % (
                      "%d узлов" % n, name, stat.get("median", 0),
                      stat.get("p95", 0), stat.get("p99", 0),
                      stat.get("paintedFps", 0)))
        cdp.detach()
        pg.close()
        ctx.close()
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--label", default="cand")
    ap.add_argument("--revision", default=None)
    ap.add_argument("--out", default=None, help="файл JSON результата")
    ap.add_argument("--ms", type=int, default=1500)
    ap.add_argument("--fixtures", default="10,100,702")
    ap.add_argument("--modes", default="embedded,fullscreen")
    ap.add_argument("--fullscreen-fixtures", default="702")
    ap.add_argument("--diag", action="store_true",
                    help="доп. замер рабочего состояния без слоя fx (только кандидат)")
    ap.add_argument("--android", action="store_true",
                    help="доп. замер телефонного вьюпорта с торможением CPU ×4")
    ap.add_argument("--realistic", type=int, default=0,
                    help="контроль: обрезать рёбра до N на узел (0 — не обрезать)")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    # Фикстуры берутся из каталога САМОГО инструмента: они общие для кандидата
    # и для базовой ревизии (--repo), иначе сравнение A/B шло бы на разных данных.
    sys.path.insert(0, os.path.join(os.path.dirname(here), "tests",
                                    "fixtures", "cmv"))
    os.chdir(repo)
    global M, W15, FIX, FULL_FIXTURES
    import ui_round1025_matrix as M                       # noqa: E402
    import ui_evol_w15_composition_e2e as W15             # noqa: E402
    import cog_map_fixtures as FIX                        # noqa: E402
    from playwright.sync_api import sync_playwright

    fixtures = tuple(int(x) for x in args.fixtures.split(",") if x)
    FULL_FIXTURES = {int(x) for x in args.fullscreen_fixtures.split(",")
                     if x.strip().isdigit()}
    modes = tuple(m for m in args.modes.split(",") if m)
    M.PORT = 0
    server = M._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
    out = (os.path.abspath(args.out) if args.out
           else os.path.join(repo, "plans", "features", "epic-cm-visual-01",
                             "evidence", "cmv-e",
                             "fps-%s.json" % args.label))
    report = {
        "label": args.label,
        "revision": args.revision,
        "repo": repo,
        "ms": args.ms,
        "fixtures": list(fixtures),
        "fixture_sha256": {str(n): FIX.sha256(FIX.load(n)) for n in fixtures},
        "states": [{"name": s, "ratio": r} for s, r in STATES],
        "modes": list(modes),
        "host": {"platform": platform.platform(),
                 "python": platform.python_version()},
        "render_mode": ("headed" if args.headed else "headless-gpu"),
        "launch_args": ([] if args.headed else
                        ["--enable-gpu", "--enable-gpu-rasterization",
                         "--ignore-gpu-blocklist", "--use-angle=d3d11"]),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        with sync_playwright() as pw:
            launch = {"headless": not args.headed}
            if not args.headed:
                launch["args"] = report["launch_args"]
            browser = pw.chromium.launch(**launch)
            try:
                report.update(measure(browser, base, fixtures, args.ms, modes,
                                      os.path.dirname(out), diag=args.diag,
                                      android=args.android,
                                      realistic=args.realistic))
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    finally:
        server.shutdown()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if report.get("error"):
        print("ERROR:\n" + report["error"][-1500:])
        return 3
    print("%s: %d случаев -> %s" % (args.label, len(report["cases"]), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
