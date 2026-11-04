"""CMV-C (EPIC-CM-VISUAL-01) — проверка LOD, агрегатов L0 и подписей.

Живой прогон на реальной странице (`web/index.html` + `web/app.js` + self-host
vis-network) с той же детерминированной копией топологии 702/2400, что у
`tools/ui_cmv_b_scene_fps.py` (импортируется, а не копируется).

Проверяет именно требования CMV-C:
  * LOD с гистерезисом: уровень не мигает у порогов T1=0.85 / T2=1.80;
  * агрегаты уровня 0: центры реальных групп, честные числа, обратимость к
    реальным id, раскрытие кликом;
  * подписи в экранных координатах: приоритет, отсутствие наложений,
    выбранный/найденный подписаны ВСЕГДА;
  * мобильный кадр 390×844: различимые центры вместо комка совпавших узлов;
  * счётчики §9.9: в БД / из API / после фильтра / на экране не смешаны;
  * FPS панорамирования (медиана трёх прогонов).

Запуск:
  .venv/Scripts/python.exe plans/features/epic-cm-visual-01/evidence/cmv-c/probe.py \
      --repo <ROOT> --out <DIR>
Код возврата: 0 — все проверки прошли, 2 — провал, 3 — стенд не поднялся.
"""
import argparse
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
PAN_MS = 3000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-gpu", action="store_true")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo) if args.repo else os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(
        os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    os.chdir(repo)
    import ui_round1025_matrix as M            # noqa: E402
    import ui_evol_w15_composition_e2e as W15  # noqa: E402
    import ui_cmv_b_scene_fps as B             # noqa: E402
    from playwright.sync_api import sync_playwright
    globals()["M"] = M
    globals()["W15"] = W15
    globals()["B"] = B
    globals()["B_READY"] = B.READY
    globals()["B_STABLE"] = B.STABLE

    payload = B.big_payload()
    payload["generated_at"] = int(time.time())
    W15.set_cog_payload(payload)

    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    report = {
        "repo": repo, "nodes": B.NODES, "edges": B.EDGES,
        "render_mode": "headless-swiftshader" if args.no_gpu else "headless-gpu(ANGLE d3d11)",
        "checks": [], "fails": [], "shots": [],
    }
    try:
        with sync_playwright() as pw:
            launch = {"headless": True}
            if not args.no_gpu:
                launch["args"] = [
                    "--enable-gpu", "--enable-gpu-rasterization",
                    "--ignore-gpu-blocklist", "--use-angle=d3d11",
                ]
            browser = pw.chromium.launch(**launch)
            try:
                report.update(run(browser, base, out_dir))
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    finally:
        server.shutdown()

    out = os.path.join(out_dir, "cmv-c-lod.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if report.get("error"):
        print("ERROR:\n" + report["error"][-3000:])
        return 3
    for f in report["fails"]:
        print("FAIL: " + f)
    print("checks=%d fails=%d" % (len(report["checks"]), len(report["fails"])))
    for key in ("desktop", "mobile"):
        d = report.get(key) or {}
        print("%s: %s" % (key, json.dumps(d.get("fit") or {}, ensure_ascii=False)))
    pan = report.get("fps_pan") or {}
    print("FPS pan median: %.1f (runs %r, p95 %.1f)"
          % (pan.get("median", 0), pan.get("runs"), pan.get("fpsP95", 0)))
    return 0 if not report["fails"] else 2


SNAPSHOT = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  const net = vm && vm.cognitionNetwork;
  if (!net) return null;
  const rows = (vm._cognitionNodesDS && vm._cognitionNodesDS.get)
    ? vm._cognitionNodesDS.get() : [];
  const hidden = {};
  rows.forEach((r) => { if (r.hidden === true) hidden[String(r.id)] = true; });
  const labels = ((vm._cogLabels && vm._cogLabels.labels) || [])
    .concat((vm._cogLabels && vm._cogLabels.forced) || []);
  let overlaps = [];
  for (let i = 0; i < labels.length; i += 1) {
    for (let j = i + 1; j < labels.length; j += 1) {
      const a = labels[i], b = labels[j];
      if (String(a.id) === String(b.id)) continue;
      if (Math.abs(a.x - b.x) * 2 < (a.width + b.width)
          && Math.abs(a.y - b.y) * 2 < (a.height + b.height)) {
        overlaps.push([String(a.id), a.text, String(b.id), b.text,
                       Math.round(a.x), Math.round(a.y),
                       Math.round(b.x), Math.round(b.y)]);
      }
    }
  }
  const cam = net.getViewPosition();
  const sc = net.getScale();
  const canvasEl = vm._cogEl.querySelector('canvas');
  const W = canvasEl.clientWidth, H = canvasEl.clientHeight;
  const pos = net.getPositions();
  const sizeById = {};
  rows.forEach((r) => { sizeById[String(r.id)] = r.size || 0; });
  // Совпавшие центры считаем ТОЛЬКО по РЕАЛЬНО НАРИСОВАННЫМ узлам: скрытые
  // LOD-ом узлы на кадре не видны, и их координаты ничего не говорят о картинке.
  const drawn = [];
  Object.keys(pos).forEach((id) => {
    if (hidden[id]) return;
    const p = pos[id];
    const sx = (p.x - cam.x) * sc + W / 2;
    const sy = (p.y - cam.y) * sc + H / 2;
    if (sx < 0 || sy < 0 || sx > W || sy > H) return;
    drawn.push({ x: sx, y: sy, r: (sizeById[id] || 0) * sc });
  });
  drawn.sort((a, b) => a.x - b.x);
  let overlapsN = 0, coincident = 0, nearC = 0, worst = 0;
  let hiddenFlagged = 0;
  rows.forEach((r) => { if (r.hidden === true) hiddenFlagged += 1; });
  for (let i = 0; i < drawn.length; i += 1) {
    const a = drawn[i];
    for (let j = i + 1; j < drawn.length; j += 1) {
      const b = drawn[j];
      if (b.x - a.x > a.r + b.r) break;
      const d = Math.hypot(b.x - a.x, b.y - a.y);
      if (d < 0.5) coincident += 1;
      if (d < 1.5) nearC += 1;
      if (d < a.r + b.r - 0.01) { overlapsN += 1; worst = Math.max(worst, a.r + b.r - d); }
    }
  }
  const counts = (typeof vm._cogCounts === 'function') ? vm._cogCounts() : null;
  const aggs = (scene && scene.aggregates) || [];
  const aggIds = new Set(aggs.map((g) => g.id));
  const memberIds = [];
  aggs.forEach((g) => { (g.memberIds || []).forEach((m) => memberIds.push(String(m))); });
  const realIds = new Set(rows.map((r) => String(r.id)));
  const counters = vm._cogDebugCounters ? vm._cogDebugCounters() : {};
  return {
    lod: scene ? scene.lod : null,
    scale: sc, fitScale: vm._cogFitScale || 0,
    ratio: (vm._cogFitScale ? sc / vm._cogFitScale : 0),
    dense: scene ? scene.lodDensity : null,
    aggregates: aggs.map((g) => ({
      id: g.id, apexId: g.apexId, count: g.count, label: g.label,
      kinds: g.kinds, hideMembers: g.hideMembers,
      membersReal: (g.memberIds || []).every((m) => realIds.has(String(m))),
    })),
    aggTotal: memberIds.length,
    aggUnique: new Set(memberIds).size,
    aggIds: Array.from(aggIds),
    flows: (scene && scene.aggFlows ? scene.aggFlows.length : 0),
    rendered: drawn.length,
    hidden: rows.length - drawn.length,
    hiddenFlagged: hiddenFlagged,
    renderedOverlaps: overlapsN,
    renderedCoincident: coincident,
    renderedNear: nearC,
    renderedWorst: worst,
    labels: labels.length,
    labelGroups: labels.filter((l) => String(l.id).indexOf('agg:') === 0).length,
    labelOverlaps: overlaps,
    selectedLabeled: labels.some((l) => String(l.id) === String(vm._cogSelectedId)),
    counts: counts,
    counters: {
      aggDraws: counters.aggDraws, aggFlowDraws: counters.aggFlowDraws,
      visibleNodes: counters.visibleNodes, hiddenByLod: counters.hiddenByLod,
      fxSprites: counters.fxSprites, fxGradients: counters.fxGradients,
      labelsShown: counters.labelsShown,
    },
  };
}
"""

# Плавный «колесом» вокруг центра сцены и чтение уровня после каждого шага:
# пороги не должны мигать (уровень не ходит вперёд-назад на одном r).
ZOOM_SWEEP = r"""
(steps) => {
  const vm = window.__adminbotVm;
  const net = vm.cognitionNetwork;
  const el = vm._cogEl;
  const canvas = el.querySelector('canvas');
  const box = canvas.getBoundingClientRect();
  const out = [];
  const cx = box.left + box.width / 2;
  const cy = box.top + box.height / 2;
  return { cx, cy, out };
}
"""


def settle(pg, timeout_ms=60000):
    pg.wait_for_function(B_READY, timeout=timeout_ms)
    pg.wait_for_function(B_STABLE, timeout=timeout_ms)
    pg.wait_for_timeout(220)


def shot(pg, out_dir, name):
    path = os.path.join(out_dir, name)
    pg.screenshot(path=path)
    return path


def zoom_to(pg, target_ratio):
    """Ставит камеру так, чтобы r = scale/fitScale ≈ target (мимо жестов:
    проверяем LOD, а не парсер жестов)."""
    pg.evaluate(
        """(r) => {
          const vm = window.__adminbotVm;
          const net = vm.cognitionNetwork;
          const cam = net.getViewPosition();
          net.moveTo({ position: cam, scale: (vm._cogFitScale || 1) * r,
                       animation: false });
          vm._cogPaintStatic();
        }""", target_ratio)
    pg.wait_for_timeout(180)


def lod_state(pg):
    return pg.evaluate(
        """() => {
          const vm = window.__adminbotVm;
          const s = vm._cogScene;
          return { lod: s ? s.lod : null, r: (vm._cogFitScale
            ? vm.cognitionNetwork.getScale() / vm._cogFitScale : 0),
            aggs: (s && s.aggregates ? s.aggregates.length : 0),
            hidden: (vm._cogDebugCounters() || {}).hiddenByLod || 0 };
        }""")


def run(browser, base, out_dir):
    report = {"checks": [], "fails": [], "shots": [], "sweeps": {}}

    def check(cond, message):
        report["checks"].append({"ok": bool(cond), "message": message})
        if not cond:
            report["fails"].append(message)

    for label, (w, h), dpr, mobile in (
            ("desktop", DESKTOP, 1, False), ("mobile", MOBILE, 2, True)):
        ctx = browser.new_context(
            viewport={"width": w, "height": h}, device_scale_factor=dpr,
            is_mobile=mobile, has_touch=mobile)
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", W15._routes())
        pg = ctx.new_page()
        pg.goto(base + "#/", wait_until="load")
        settle(pg)
        pg.evaluate("() => window.__adminbotVm._cogEl"
                    ".scrollIntoView({ block: 'center', inline: 'center' })")
        pg.wait_for_timeout(320)
        data = pg.evaluate(SNAPSHOT)
        report[label] = {"viewport": [w, h], "dpr": dpr, "fit": data}

        # ── LOD: обзор = уровень 0, честная плотность, агрегаты ─────────────
        check(data["lod"] == 0,
              "%s: кадр обзора на плотном наборе — уровень 0 (%r при r=%.2f, "
              "плотность %.0f/100k)" % (label, data["lod"], data["ratio"],
                                        data["dense"] or 0))
        check(len(data["aggregates"]) >= 3,
              "%s: на обзоре видны центры групп (%d агрегатов)"
              % (label, len(data["aggregates"])))
        check(all(g["membersReal"] for g in data["aggregates"]),
              "%s: все агрегаты состоят из РЕАЛЬНЫХ id" % label)
        check(data["aggTotal"] == data["aggUnique"]
              and data["aggTotal"] == data["counts"]["filter"]["nodes"],
              "%s: агрегаты покрывают набор без потерь и повторов "
              "(%d / уникальных %d / в витрине %d)"
              % (label, data["aggTotal"], data["aggUnique"],
                 data["counts"]["filter"]["nodes"]))
        check(data["flows"] >= 1,
              "%s: между центрами есть потоки по реальным рёбрам (%d пар)"
              % (label, data["flows"]))
        check(all(g["count"] >= 1 and g["label"] for g in data["aggregates"]),
              "%s: каждый агрегат подписан реальным числом элементов" % label)
        # §12.1: с первого взгляда — несколько пространственно разделённых
        # центров, различимых по цвету.
        kinds = set()
        for g in data["aggregates"]:
            kinds.update(g["kinds"].keys())
        check(len(kinds) >= 2,
              "%s: центры групп различимы по типам (%d типов)" % (label, len(kinds)))

        # ── узлы не стоят стеной; мобильный кадр больше не «комок» ──────────
        per_node = (data["renderedOverlaps"] / data["rendered"]
                    if data["rendered"] else 0)
        check(per_node <= 0.6,
              "%s: различимые узлы не стоят стеной (%.0f пересечений = %.2f "
              "на узел, макс. %.1f px)"
              % (label, data["renderedOverlaps"], per_node,
                 data["renderedWorst"]))
        check(data["renderedCoincident"] <= 4,
              "%s: совпавших центров на кадре почти нет (%d; было 258/290 на "
              "мобильном)" % (label, data["renderedCoincident"]))

        # ── подписи: без наложений, центры групп подписаны ──────────────────
        check(not data["labelOverlaps"],
              "%s: подписи не накладываются (%d пар: %r)"
              % (label, len(data["labelOverlaps"]),
                 data["labelOverlaps"][:3]))
        check(data["labelGroups"] >= 3,
              "%s: подписаны центры групп (%d из %d подписей)"
              % (label, data["labelGroups"], data["labels"]))

        # ── счётчики §9.9 не смешаны ────────────────────────────────────────
        counts = data["counts"] or {}
        check(counts.get("api", {}).get("nodes") == B.NODES,
              "%s: «из API» = %r" % (label, counts.get("api", {}).get("nodes")))
        check(counts.get("api", {}).get("nodes")
              == counts.get("filter", {}).get("nodes"),
              "%s: без фильтра витрина равна API-набору" % label)
        check(counts.get("screen", {}).get("aggregated", 0) > 0
              and counts.get("screen", {}).get("aggregates", 0)
              == len(data["aggregates"]),
              "%s: «на экране» различает агрегаты (%r)"
              % (label, counts.get("screen")))
        check(counts.get("db", {}).get("known") is False
              or (counts.get("db", {}).get("nodes") or 0)
              >= (counts.get("api", {}).get("nodes") or 0),
              "%s: «всего в БД» либо неизвестно, либо не меньше API-набора (%r)"
              % (label, counts.get("db")))

        report["shots"].append(shot(pg, out_dir, "cmv-c-%s-overview.png" % label))

        # ── LOD-гистерезис: обход порогов вверх/вниз ────────────────────────
        sweep_up = [0.50, 0.70, 0.74, 0.76, 0.90, 0.94, 0.96, 1.00,
                    1.30, 1.55, 1.60, 1.70, 2.00, 2.10, 2.40]
        sweep_dn = [2.40, 2.10, 2.00, 1.70, 1.60, 1.55, 1.30, 1.00,
                    0.96, 0.94, 0.90, 0.76, 0.74, 0.70, 0.50]
        trace_up = []
        for r in sweep_up:
            zoom_to(pg, r)
            trace_up.append(lod_state(pg))
        trace_dn = []
        for r in sweep_dn:
            zoom_to(pg, r)
            trace_dn.append(lod_state(pg))
        report["sweeps"][label] = {"up": trace_up, "down": trace_dn}

        def flicker(trace):
            """Никаких возвратов уровня на монотонном проходе r."""
            bad = []
            for i in range(1, len(trace)):
                prev, cur = trace[i - 1]["lod"], trace[i]["lod"]
                if trace[i]["r"] > trace[i - 1]["r"] and cur < prev:
                    bad.append((trace[i - 1]["r"], cur, trace[i]["r"], prev))
                if trace[i]["r"] < trace[i - 1]["r"] and cur > prev:
                    bad.append((trace[i - 1]["r"], cur, trace[i]["r"], prev))
            return bad
        bad_up = flicker(trace_up)
        bad_dn = flicker(trace_dn)
        check(not bad_up, "%s: на увеличении уровень не откатывается назад %r"
              % (label, bad_up))
        check(not bad_dn, "%s: на уменьшении уровень не прыгает вверх %r"
              % (label, bad_dn))
        # Зона нечувствительности: у порога T1 уровень не меняется при ±5 % r.
        zoom_to(pg, 0.93)
        a = lod_state(pg)["lod"]
        zoom_to(pg, 0.98)
        b = lod_state(pg)["lod"]
        zoom_to(pg, 0.93)
        c = lod_state(pg)["lod"]
        check(a == b == c,
              "%s: около порога T1 уровень стабилен (%r/%r/%r при r 0.93/0.98)"
              % (label, a, b, c))
        zoom_to(pg, 1.00)
        back = lod_state(pg)
        report["back_to_fit"] = back
        check(back["lod"] == 0 and back["aggs"] >= 3,
              "%s: возврат к обзору восстанавливает агрегаты (lod=%r, %d)"
              % (label, back["lod"], back["aggs"]))

        # ── раскрытие агрегата кликом по его центру ─────────────────────────
        agg = pg.evaluate(
            """() => {
              const vm = window.__adminbotVm;
              const s = vm._cogScene;
              const el = vm._cogEl;
              const canvas = el.querySelector('canvas');
              const box = canvas.getBoundingClientRect();
              const g = (s.aggregates || []).filter((x) => x.count >= 20)[0]
                || (s.aggregates || [])[0];
              if (!g) return null;
              return { id: g.id, apexId: g.apexId, count: g.count,
                       x: box.left + g.sx, y: box.top + g.sy };
            }""")
        if agg:
            pg.mouse.click(agg["x"], agg["y"])
            pg.wait_for_timeout(700)
            after = pg.evaluate(
                """() => {
                  const vm = window.__adminbotVm;
                  const s = vm._cogScene;
                  return { lod: s ? s.lod : null, aggs: (s && s.aggregates)
                    ? s.aggregates.length : 0,
                    selected: vm._cogSelectedId,
                    r: (vm._cogFitScale ? vm.cognitionNetwork.getScale()
                      / vm._cogFitScale : 0) };
                }""")
            report[label]["expand"] = {"agg": agg, "after": after}
            check(after["selected"] is not None,
                  "%s: клик по центру группы выбрал РЕАЛЬНЫЙ узел (%r)"
                  % (label, after["selected"]))
            check(after["lod"] != 0,
                  "%s: раскрытие группы уводит с уровня 0 (lod=%r, r=%.2f)"
                  % (label, after["lod"], after["r"]))
            report["shots"].append(shot(
                pg, out_dir, "cmv-c-%s-expanded.png" % label))

        # ── средний вид (L1): узлы по отдельности, подписи по приоритету ────
        zoom_to(pg, 1.45)
        mid = pg.evaluate(SNAPSHOT)
        report[label]["mid"] = mid
        check(mid["lod"] in (0, 1),
              "%s: рабочий/средний вид — уровень 1 (%r)" % (label, mid["lod"]))
        check(not mid["labelOverlaps"],
              "%s: на среднем виде подписи не накладываются (%d)"
              % (label, len(mid["labelOverlaps"])))
        check(mid["selectedLabeled"],
              "%s: выбранный узел подписан и на среднем виде" % label)
        report["shots"].append(shot(pg, out_dir, "cmv-c-%s-mid.png" % label))

        # ── детальный вид (L2): r ≥ 2.016 ───────────────────────────────────
        zoom_to(pg, 2.60)
        detail = pg.evaluate(SNAPSHOT)
        report[label]["detail"] = detail
        check(detail["lod"] == 2,
              "%s: детальный вид — уровень 2 (%r при r=%.2f)"
              % (label, detail["lod"], detail["ratio"]))
        check(not detail["labelOverlaps"],
              "%s: в детальном виде подписи не накладываются (%d)"
              % (label, len(detail["labelOverlaps"])))
        check(detail["selectedLabeled"],
              "%s: выбранный узел подписан и в детальном виде" % label)
        check(detail["hiddenFlagged"] == 0,
              "%s: детальный вид не скрывает узлы (%d скрыто LOD-ом)"
              % (label, detail["hiddenFlagged"]))
        report["shots"].append(shot(pg, out_dir, "cmv-c-%s-detail.png" % label))

        # ── выбор + hover на детальном виде: подписи не налезают ────────────
        target = pg.evaluate(
            """() => {
              const vm = window.__adminbotVm;
              const net = vm.cognitionNetwork, s = vm._cogScene;
              const el = vm._cogEl;
              const canvas = el.querySelector('canvas');
              const box = canvas.getBoundingClientRect();
              const W = canvas.clientWidth, H = canvas.clientHeight;
              const cam = net.getViewPosition(), sc = net.getScale();
              const view = vm._cogView;
              let best = null;
              for (const n of view.nodes) {
                if (String(n.id) === String(vm._cogSelectedId)) continue;
                const p = s.pos[n.id];
                if (!p) continue;
                const sx = (p.x - cam.x) * sc + W / 2;
                const sy = (p.y - cam.y) * sc + H / 2;
                if (sx < 40 || sy < 40 || sx > W - 40 || sy > H - 40) continue;
                if (!best || (n.degree || 0) > (best.degree || 0)) {
                  best = { id: n.id, degree: n.degree || 0,
                           x: box.left + sx, y: box.top + sy };
                }
              }
              return best;
            }""")
        if target:
            pg.mouse.move(target["x"], target["y"])
            pg.wait_for_timeout(240)
            pg.mouse.click(target["x"], target["y"])
            pg.wait_for_timeout(320)
            sel = pg.evaluate(SNAPSHOT)
            report[label]["detailSelected"] = {
                "labels": sel["labels"], "overlaps": sel["labelOverlaps"],
                "selectedLabeled": sel["selectedLabeled"],
                "groups": sel["labelGroups"], "hidden": sel["hiddenFlagged"],
            }
            check(not sel["labelOverlaps"],
                  "%s: с выбранным и hover подписи не накладываются (%r)"
                  % (label, sel["labelOverlaps"][:3]))
            check(sel["selectedLabeled"],
                  "%s: подпись выбранного видна в детальном виде" % label)
            report["shots"].append(shot(
                pg, out_dir, "cmv-c-%s-detail-selected.png" % label))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)

        if label == "desktop":
            # ── FPS: панорамирование 3 с, три прогона ───────────────────────
            # Одинаковое состояние для сравнения «до/после»: (1) обзор r=1,
            # (2) детальный вид r≈2.6 — там, где рисуются ВСЕ узлы.
            detail_runs = []
            zoom_to(pg, 2.6)
            pg.wait_for_timeout(250)
            for _ in range(3):
                detail_runs.append(pg.evaluate(B.PAN_FPS, PAN_MS))
            dpans = sorted(r["fps"] for r in detail_runs if "fps" in r)
            report["fps_pan_detail"] = {
                "runs": [round(r.get("fps", 0), 1) for r in detail_runs],
                "median": dpans[len(dpans) // 2] if dpans else 0,
                "lod": lod_state(pg)["lod"],
                "ratio": lod_state(pg)["r"],
            }
            check(report["fps_pan_detail"]["median"] >= 45,
                  "desktop: FPS панорамирования В ДЕТАЛЬНОМ ВИДЕ ≥ 45 (медиана %.1f, %r)"
                  % (report["fps_pan_detail"]["median"],
                     report["fps_pan_detail"]["runs"]))
            zoom_to(pg, 1.0)
            pg.wait_for_timeout(250)
            runs = [pg.evaluate(B.PAN_FPS, PAN_MS) for _ in range(3)]
            pans = sorted(r["fps"] for r in runs if "fps" in r)
            pan = runs[len(runs) // 2]
            pan["runs"] = [round(r.get("fps", 0), 1) for r in runs]
            pan["median"] = pans[len(pans) // 2] if pans else 0
            report["fps_pan"] = pan
            pg.evaluate("() => { const s = window.__adminbotVm._cogScene;"
                        " s._fxKeep = s.fx; s.fx = null; }")
            report["fps_pan_vis_only"] = pg.evaluate(B.PAN_FPS, PAN_MS)
            pg.evaluate("() => { const s = window.__adminbotVm._cogScene;"
                        " s.fx = s._fxKeep; }")
            check(pan["median"] >= 45,
                  "desktop: FPS панорамирования ≥ 45 (медиана %.1f, %r)"
                  % (pan["median"], pan["runs"]))
        pg.close()
        ctx.close()
    return report


B_READY = ""
B_STABLE = ""


if __name__ == "__main__":
    sys.exit(main())
