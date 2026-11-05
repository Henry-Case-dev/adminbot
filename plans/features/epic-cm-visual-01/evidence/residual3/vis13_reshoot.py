"""CMV-VIS-13: пересъёмка пар «до/после» на ОДНОМ узле (§13 спеки).

Ревью (cmv-e-review.md, строки 28–29) принял пары fit и mobile, но забраковал
пары selected/zoom/fullscreen: у кандидата они выбрали не тот узел
(ent:569 вместо paradigm:184). Здесь все три пары снимаются заново с
ЖЁСТКО ЗАФИКСИРОВАННЫМ узлом `paradigm:-1001234567890:184` (топ по степени
FIX-702, degree 13) на обеих ревизиях, на тех же условиях, что принятые
пары: FIX-702, desktop 1536×960, DPR 1, камера от fit (r 1.8 / 2.6 / 1.8).
Payload байтово одинаковый (generated_at фиксирован), sha256 записывается.

До/после ревизии — те же, что в cmv-e: «до» для selected/zoom — pre-CMV
(9e238d06), «до» для fullscreen — A+B+C (dfba4080, без D), «после» —
кандидат этой ветки. Сервер поднимается на каждом корне по очереди (тот же
механизм serve_and_run, что в ui_cmv_e_cine.py).

Запуск:
  <venv python> plans/features/epic-cm-visual-01/evidence/residual3/vis13_reshoot.py \
      --base-repo <pre-CMV worktree> --base-revision 9e238d06 \
      --full-base-repo <A+B+C worktree> --full-base-revision dfba4080 \
      [--revision <candidate rev>]
Выход: evidence/residual3/CMV-VIS-13/{before,after}-{selected,zoom,fullscreen}-1536.png
       + vis13-records.json
"""
import argparse
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
OUT = os.path.join(HERE, "CMV-VIS-13")

TARGET_ID = "paradigm:-1001234567890:184"
FIXED_TS = 1750000000
FIXTURE = 702
DESKTOP = (1536, 960)

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

MOVE_TO = r"""
([id, ratio, fit]) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const cache = (vm._cogScene && vm._cogScene.pos) || net.getPositions() || {};
  const pos = cache[id] || net.getViewPosition();
  const f = fit || vm._cogFitScale || net.getScale();
  net.moveTo({ position: { x: pos.x, y: pos.y }, scale: f * ratio,
               animation: false });
  return { scale: +net.getScale().toFixed(5) };
}
"""

SELECT = r"""
(id) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  try { if (net && net.selectNodes) net.selectNodes([id]); } catch (e) { }
  if (typeof vm.graphSelectNode === 'function') vm.graphSelectNode(id);
  if (typeof vm.graphApplySelectionLabels === 'function') {
    vm.graphApplySelectionLabels([id]);
  }
  return vm._cogSelectedId || null;
}
"""

COUNTERS = r"""
() => {
  const vm = window.__adminbotVm;
  const c = (vm._cogDebugCounters ? vm._cogDebugCounters() : {}) || {};
  const card = document.querySelector('#cog-card');
  const detail = vm.graphDetail;
  return {
    selected: vm._cogSelectedId === undefined ? null : vm._cogSelectedId,
    card: !!vm.cogCardOpen,
    detail: detail ? { id: detail.id, title: detail.title,
                       kind: detail.kind } : null,
    labels: c.labelsShown || 0,
    activeEdges: c.fxActiveEdges || 0,
    pulse: c.pulseCount || 0,
    canvases: document.querySelectorAll('canvas').length,
    scenes: document.querySelectorAll('.cognition-graph').length,
    visNetworks: document.querySelectorAll('.vis-network').length,
    dpr: window.devicePixelRatio,
    viewport: [window.innerWidth, window.innerHeight],
    scale: +vm.cognitionNetwork.getScale().toFixed(5),
  };
}
"""


def serve_and_run(root, fn):
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "tools"))
    sys.path.insert(0, os.path.join(root, "tests", "fixtures", "cmv"))
    os.chdir(root)
    global M, W15, FIX
    for mod in ("ui_round1025_matrix", "ui_evol_w15_composition_e2e",
                "cog_map_fixtures"):
        sys.modules.pop(mod, None)
    import ui_round1025_matrix as Mx                  # noqa: E402
    import ui_evol_w15_composition_e2e as Wx          # noqa: E402
    import cog_map_fixtures as Fx                     # noqa: E402
    M, W15, FIX = Mx, Wx, Fx
    M.PORT = 0
    server = M._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
    try:
        from playwright.sync_api import sync_playwright   # noqa: E402
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


def shoot_side(browser, base, label, revision, records):
    W15.set_cog_payload(_payload_with_ts())
    ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                        "height": DESKTOP[1]},
                              device_scale_factor=1)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes())
    pg = ctx.new_page()
    pg.goto(base + "#/", wait_until="load")
    pg.wait_for_function(READY, timeout=120000)
    pg.wait_for_timeout(400)
    pg.evaluate("""() => { const vm = window.__adminbotVm;
      const el = vm._cogEl || document.querySelector('.cognition-graph');
      if (el) el.scrollIntoView({ block: 'center' }); }""")
    pg.wait_for_timeout(400)
    fit = pg.evaluate("""() => { const vm = window.__adminbotVm;
      return vm._cogFitScale || vm.cognitionNetwork.getScale(); }""")
    # 1. selected: камера r=1.8 на ЦЕЛЕВОЙ узел, выбор программный
    #    (одинаковый путь на обеих ревизиях — раскладки разные)
    pg.evaluate(MOVE_TO, [TARGET_ID, 1.8, fit])
    pg.wait_for_timeout(450)
    sel = pg.evaluate(SELECT, TARGET_ID)
    pg.wait_for_timeout(500)
    rec = {"rev": revision, "side": label, "state": "selected",
           "ratio": 1.8, "target": TARGET_ID, "selected": sel, "fit": fit}
    rec.update(pg.evaluate(COUNTERS))
    name = "%s-selected-1536.png" % label
    pg.screenshot(path=os.path.join(OUT, name))
    rec["shot"] = name
    records.append(rec)
    # 2. zoom r=2.6 вокруг того же узла (выбор сохранён)
    pg.evaluate(MOVE_TO, [TARGET_ID, 2.6, fit])
    pg.wait_for_timeout(550)
    rec = {"rev": revision, "side": label, "state": "zoom",
           "ratio": 2.6, "target": TARGET_ID, "selected": sel, "fit": fit}
    rec.update(pg.evaluate(COUNTERS))
    name = "%s-zoom-1536.png" % label
    pg.screenshot(path=os.path.join(OUT, name))
    rec["shot"] = name
    records.append(rec)
    # 3. fullscreen desktop, тот же узел, r=1.8
    pg.evaluate("() => window.__adminbotVm.openGraphFull()")
    pg.wait_for_timeout(900)
    pg.evaluate(MOVE_TO, [TARGET_ID, 1.8, fit])
    pg.wait_for_timeout(700)
    rec = {"rev": revision, "side": label, "state": "fullscreen",
           "ratio": 1.8, "target": TARGET_ID, "selected": sel, "fit": fit}
    rec.update(pg.evaluate(COUNTERS))
    name = "%s-fullscreen-1536.png" % label
    pg.screenshot(path=os.path.join(OUT, name))
    rec["shot"] = name
    records.append(rec)
    pg.evaluate("() => window.__adminbotVm.closeGraphFull()")
    pg.wait_for_timeout(600)
    pg.close()
    ctx.close()


_PAYLOAD = {}


def _payload_with_ts():
    p = FIX.load(FIXTURE)
    p["generated_at"] = FIXED_TS
    _PAYLOAD["sha256"] = hashlib.sha256(
        json.dumps(p, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--base-repo", required=True)
    ap.add_argument("--base-revision", default="base")
    ap.add_argument("--full-base-repo", required=True)
    ap.add_argument("--full-base-revision", default="fullbase")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo) if args.repo else REPO
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    sys.path.insert(0, os.path.join(repo, "tests", "fixtures", "cmv"))
    global FIX
    import cog_map_fixtures as _FIX0                   # noqa: E402
    FIX = _FIX0
    report = {"fixture": FIXTURE, "target": TARGET_ID,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "payload_sha256": None, "records": []}
    _payload_with_ts()
    report["payload_sha256"] = _PAYLOAD.get("sha256")
    try:
        # кандидат — из ЭТОГО корня (сервер поднимается здесь же)
        serve_and_run(repo, lambda b, s: shoot_side(
            b, s, "after", args.revision or "candidate",
            report["records"]))
        serve_and_run(args.base_repo, lambda b, s: shoot_side(
            b, s, "before", args.base_revision, report["records"]))
        serve_and_run(args.full_base_repo, lambda b, s: shoot_side(
            b, s, "beforefull", args.full_base_revision,
            report["records"]))
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    out = os.path.join(OUT, "vis13-records.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    if report.get("error"):
        print("ERROR:\n" + report["error"][-1500:])
        return 3
    bad = [r for r in report["records"]
           if r.get("selected") != TARGET_ID]
    print("records: %d, узел зафиксирован: %s" % (
        len(report["records"]),
        "ДА" if not bad else "НЕТ (%s)" % [r["state"] for r in bad]))
    print("-> %s" % out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
