"""CMV-A (EPIC-CM-VISUAL-01) — инструментальный счётчик жизненного цикла карты.

Требование владельца (§10.2 спеки) и контракта (§1, §7.3, §10.3):

  «После 20 циклов embedded/fullscreen не растёт число обработчиков, активных
   RAF, Network instances или наблюдателей. Это проверяется инструментально.»

Стенд: реальный `web/index.html` + `web/app.js` + self-host vis-network на
локальном http-сервере; `/api/*` — детерминированные стабы существующей
матрицы (`ui_round1025_matrix`) и фикстура карты (`ui_evol_w15_composition_e2e`).
Ничего не подменяется в самом приложении: инструментация живёт в init-script
Playwright'а и считает то, что приложение реально создаёт.

Счётчики (одинаковы для ЛЮБОЙ ревизии `web/**`, поэтому «до/после» сравнимы):

  netsMade      — сколько РАЗНЫХ `vis.Network` видел стенд (по идентичности
                  `vm.cognitionNetwork`); контракт §1.4 пересоздаёт сеть в
                  новом контейнере, поэтому +2 за цикл — ожидаемо;
  netsLive      — сколько из них ещё не вызывало `destroy()` → обязано быть 1;
  listenersLive — обработчики на живых сетях (`on`/`once` без снятия);
  rafPending    — запланированные и ещё не исполненные кадры;
  winListeners  — Δ(добавлено − снято) слушателей `window`;
  docListeners  — то же для `document`;
  canvases      — canvas'ы внутри `.cognition-graph` (после сноса не висят).

Запуск:
  .venv/Scripts/python.exe ui_cmv_a_scene_counters.py --repo <ROOT> --out DIR
Выход: `<out>/cmv-a-scene-counters.json` + сводка в stdout.
Код возврата 0 — инварианты выполнены, 2 — нарушены, 3 — стенд не поднялся.
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

VIEWPORT = (1280, 800)
CYCLES = 20

INSTRUMENT = r"""
(() => {
  const S = {
    netsMade: 0, netsLive: 0, listenersMade: 0, listenersLive: 0,
    rafMade: 0, rafPending: 0, winListeners: 0, docListeners: 0,
    errors: [], patched: false,
  };
  window.__cmvStats = S;

  /* RAF: считаем запланированные и реально исполненные кадры. */
  const pending = new Set();
  const raf = window.requestAnimationFrame.bind(window);
  const caf = window.cancelAnimationFrame.bind(window);
  window.requestAnimationFrame = function (cb) {
    let id;
    id = raf(function (t) {
      pending.delete(id);
      S.rafPending = pending.size;
      try { cb(t); } catch (e) { S.errors.push('raf:' + (e && e.message)); }
    });
    S.rafMade += 1;
    pending.add(id);
    S.rafPending = pending.size;
    return id;
  };
  window.cancelAnimationFrame = function (id) {
    pending.delete(id);
    S.rafPending = pending.size;
    return caf(id);
  };

  /* Слушатели window/document: Δ(добавлено − снято) по типу. */
  function wrapAddRemove(target, key) {
    const add = target.addEventListener.bind(target);
    const rem = target.removeEventListener.bind(target);
    const live = Object.create(null);
    const total = () => Object.keys(live).reduce((a, k) => a + live[k], 0);
    target.addEventListener = function (type, fn, opts) {
      live[type] = (live[type] || 0) + 1;
      S[key] = total();
      return add(type, fn, opts);
    };
    target.removeEventListener = function (type, fn, opts) {
      if (live[type]) { live[type] -= 1; S[key] = total(); }
      return rem(type, fn, opts);
    };
  }
  wrapAddRemove(window, 'winListeners');
  wrapAddRemove(document, 'docListeners');

  /* vis.Network: обработчики и жизни экземпляров.
   *
   * Конструктор подменять нельзя: витрина библиотеки отдаёт свои члены через
   * accessor'ы бандла. Поэтому патчится ПРОТОТИП (методы ищутся в нём при
   * каждом вызове — порядок загрузки vis не важен), а число созданных сетей
   * восстанавливается по идентичности `vm.cognitionNetwork` (`seeNet`) и по
   * факту вызова `destroy()`. «Создано минус снесено» — и есть утечка. */
  const netIds = new WeakMap();
  const nets = new Map();
  let nextNetId = 0;

  function seeNet(net) {
    if (!net) return 0;
    let id = netIds.get(net);
    if (!id) {
      id = ++nextNetId;
      netIds.set(net, id);
      nets.set(id, net);
      S.netsMade += 1;
    }
    let live = 0;
    nets.forEach(function (n) { if (!n.__cmvDead) live += 1; });
    S.netsLive = live;
    return id;
  }
  window.__cmvSeeNet = seeNet;

  function patch(vis) {
    if (!vis || !vis.Network || !vis.Network.prototype) return;
    const proto = vis.Network.prototype;
    if (proto.__cmvPatched) return;
    proto.__cmvPatched = true;
    ['on', 'once'].forEach(function (name) {
      const orig = proto[name];
      if (typeof orig !== 'function') return;
      proto[name] = function () {
        this.__cmvN = (this.__cmvN || 0) + 1;
        S.listenersLive += 1;
        S.listenersMade += 1;
        return orig.apply(this, arguments);
      };
    });
    const off = proto.off;
    if (typeof off === 'function') {
      proto.off = function () {
        if (this.__cmvN > 0) { this.__cmvN -= 1; S.listenersLive -= 1; }
        return off.apply(this, arguments);
      };
    }
    const destroy = proto.destroy;
    if (typeof destroy === 'function') {
      proto.destroy = function () {
        if (!this.__cmvDead) {
          this.__cmvDead = true;
          S.listenersLive -= (this.__cmvN || 0);
          this.__cmvN = 0;
        }
        return destroy.apply(this, arguments);
      };
    }
  }

  /* Init-script исполняется ДО появления <head>, поэтому перехват ставится на
   * прототип узла (доступен сразу), а не на конкретный `document.head`. */
  const appendChild = Node.prototype.appendChild;
  Node.prototype.appendChild = function (node) {
    try {
      if (node && node.tagName === 'SCRIPT'
          && String(node.src || '').indexOf('vis-network') >= 0) {
        node.addEventListener('load', function () { patch(window.vis); });
      }
    } catch (e) { S.errors.push('append:' + (e && e.message)); }
    return appendChild.call(this, node);
  };
  let visVal;
  try {
    Object.defineProperty(window, 'vis', {
      configurable: true,
      get() { return visVal; },
      set(v) { visVal = v; patch(v); },
    });
  } catch (e) { S.errors.push('visdef:' + (e && e.message)); }
})();
"""

PROBE = r"""
() => {
  const S = window.__cmvStats || {};
  const vm = window.__adminbotVm || null;
  const qa = (s) => Array.from(document.querySelectorAll(s));
  const net = (vm && vm.cognitionNetwork) || null;
  const netId = (net && window.__cmvSeeNet) ? window.__cmvSeeNet(net) : 0;
  let scene = null;
  try {
    scene = (vm && typeof vm._cogDebugCounters === 'function')
      ? vm._cogDebugCounters() : null;
  } catch (e) { scene = 'error'; }
  return {
    netsMade: S.netsMade | 0,
    netsLive: S.netsLive | 0,
    listenersLive: S.listenersLive | 0,
    listenersMade: S.listenersMade | 0,
    rafMade: S.rafMade | 0,
    rafPending: S.rafPending | 0,
    winListeners: S.winListeners | 0,
    docListeners: S.docListeners | 0,
    errors: (S.errors || []).slice(0, 5),
    netId: netId,
    containers: qa('.cognition-graph').length,
    visContainers: qa('.vis-network').length,
    canvases: qa('.cognition-graph canvas').length,
    bodyCanvases: qa('canvas').length,
    net: !!net,
    route: String(location.hash || '#/'),
    scene: scene,
  };
}
"""

NET_ID = r"""
() => {
  const vm = window.__adminbotVm;
  const net = vm && vm.cognitionNetwork;
  return (net && window.__cmvSeeNet) ? window.__cmvSeeNet(net) : 0;
}
"""

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  if (vm._cogInitializing) return false;
  const scene = vm._cogScene;
  if (scene && scene.settled === false) return false;
  return true;
}
"""

ROUTE_FULL = "() => String(location.hash || '') === '#/status/graph'"
ROUTE_EMBEDDED = "() => String(location.hash || '') !== '#/status/graph'"


def settle(pg, timeout_ms=20000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    pg.wait_for_timeout(220)


def snapshot(pg):
    return pg.evaluate(PROBE)


# ── живые инварианты, которые счётчиками не проверяются ──────────────────────
# 1) камера обзора = формула §4.1 (от ПОЗИЦИЙ), а не vis.fit() от размеров узлов;
# 2) исходный payload не переписан визуальными полями;
# 3) выбор переживает смену режима (§6.6), выбранный узел тот же;
# 4) скрытая вкладка останавливает кадры и не заводит вторую копию.

CHECK_JS = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = vm && vm._cogScene;
  const net = vm && vm.cognitionNetwork;
  const el = vm && vm._cogEl;
  const V = window.CogVisual;
  if (!net || !el || !V) return { error: 'нет сцены' };
  const pos = net.getPositions();
  const ids = (vm._cogView && vm._cogView.nodes || []).map((n) => n.id);
  const bbox = V.bboxOf(pos, ids);
  const formula = V.fitScaleFor(bbox, el.clientWidth, el.clientHeight);
  // модель: визуальные поля не должны просочиться в данные
  const model = (vm.cognitionGraphData && vm.cognitionGraphData.nodes) || [];
  const banned = ['size', 'shape', 'color', 'x', 'y', 'opacity', 'font',
                  'borderWidth', 'dashes', 'width', 'smooth'];
  let leaked = 0;
  const sample = {};
  model.forEach((n) => {
    banned.forEach((k) => { if (n[k] !== undefined) leaked += 1; });
  });
  model.slice(0, 3).forEach((n) => {
    sample[n.id] = { title: n.title, kind: n.kind, degree: n.degree };
  });
  return {
    formula: formula,
    sceneFitScale: scene ? scene.fitScale : null,
    viewScale: net.getScale(),
    width: el.clientWidth, height: el.clientHeight,
    spanX: bbox ? bbox.spanX : null, spanY: bbox ? bbox.spanY : null,
    leakedFields: leaked,
    modelCount: model.length,
    sample: sample,
    selected: vm._cogSelectedId || null,
    route: String(location.hash || ''),
    rafActive: scene ? scene.raf != null : null,
    paused: scene ? scene.paused : null,
    frames: scene ? scene.frames : null,
    observers: scene ? ((scene.ro ? 1 : 0) + (scene.io ? 1 : 0)) : null,
  };
}
"""

HIDDEN_ON = r"""
() => {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
  document.dispatchEvent(new Event('visibilitychange'));
  return true;
}
"""

HIDDEN_OFF = r"""
() => {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
  document.dispatchEvent(new Event('visibilitychange'));
  return true;
}
"""


def live_checks(pg, payload):
    """Проверки §4.1/§6.6/§7.3 и неизменности исходных данных."""
    out = {"fails": []}

    def expect(cond, message):
        if not cond:
            out["fails"].append(message)

    first = pg.evaluate(CHECK_JS)
    out["overview"] = first
    expect(first.get("formula", 0) > 0, "формула обзора не посчиталась")
    expect(abs((first.get("viewScale") or 0) - (first.get("formula") or -1)) < 1e-3,
           "камера обзора не по формуле: viewScale=%r formula=%r"
           % (first.get("viewScale"), first.get("formula")))
    if first.get("sceneFitScale"):
        expect(abs(first["sceneFitScale"] - first["formula"]) < 1e-6,
               "fitScaleRef сцены расходится с формулой %r vs %r"
               % (first["sceneFitScale"], first["formula"]))
    expect(first.get("leakedFields") == 0,
           "визуальные поля просочились в модель: %d" % first.get("leakedFields"))
    # Значения модели совпадают с payload (данные не переписаны).
    src = {n["id"]: n for n in payload["nodes"]}
    for nid, vals in (first.get("sample") or {}).items():
        exp = src.get(nid) or {}
        expect(vals.get("title") == exp.get("title"),
               "заголовок узла %s переписан: %r != %r"
               % (nid, vals.get("title"), exp.get("title")))
        expect(vals.get("kind") == exp.get("kind"),
               "тип узла %s переписан" % nid)

    # Выбор переживает переход embedded → fullscreen → embedded.
    node_id = pg.evaluate("() => { const v = window.__adminbotVm._cogView;"
                          " return v && v.nodes.length ? v.nodes[0].id : null; }")
    pg.evaluate("(id) => { const vm = window.__adminbotVm;"
                " if (typeof vm._cogSelectNode === 'function')"
                " vm._cogSelectNode(id); }", node_id)
    pg.wait_for_timeout(500)
    before = pg.evaluate(CHECK_JS)
    expect(before.get("selected") == node_id,
           "выбор не установился (%r)" % before.get("selected"))
    out["selected"] = node_id

    # §6.6: переход embedded → fullscreen → embedded сохраняет выбор.
    pg.evaluate("() => window.__adminbotVm.openGraphFull()")
    pg.wait_for_function(ROUTE_FULL, timeout=15000)
    settle(pg)
    in_full = pg.evaluate("() => window.__adminbotVm._cogSelectedId || null")
    pg.evaluate("() => window.__adminbotVm.closeGraphFull()")
    pg.wait_for_function(ROUTE_EMBEDDED, timeout=15000)
    settle(pg)
    back = pg.evaluate("() => window.__adminbotVm._cogSelectedId || null")
    out["selection"] = {"full": in_full, "embedded": back}
    expect(in_full == node_id and back == node_id,
           "выбор потерян при смене режима: %r → %r → %r"
           % (node_id, in_full, back))

    # Скрытая вкладка: кадры стоят, слушатели не дублируются.
    pg.evaluate(HIDDEN_ON)
    pg.wait_for_timeout(700)
    hidden = pg.evaluate(CHECK_JS)
    out["hidden"] = hidden
    expect(hidden.get("frames") == before.get("frames"),
           "в скрытой вкладке кадры шли: %r → %r"
           % (before.get("frames"), hidden.get("frames")))
    pg.evaluate(HIDDEN_OFF)
    pg.wait_for_timeout(700)
    shown = pg.evaluate(CHECK_JS)
    out["shown"] = shown
    expect(shown.get("observers") == 2,
           "наблюдатели после возврата: %r" % shown.get("observers"))
    expect((shown.get("frames") or 0) - (hidden.get("frames") or 0) <= 1,
           "после возврата больше одного кадра: %r"
           % ((shown.get("frames") or 0) - (hidden.get("frames") or 0)))
    expect(shown.get("rafActive") is False,
           "после возврата остался активный кадр")
    return out


def run(browser, base, cycles):
    ctx = browser.new_context(
        viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]},
        device_scale_factor=1)
    ctx.add_init_script(INSTRUMENT)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes())
    pg = ctx.new_page()
    console_errors = []
    page_errors = []
    pg.on("console", lambda m: console_errors.append(m.text[:200])
          if m.type == "error" else None)
    pg.on("pageerror", lambda e: page_errors.append("pageerror: " + str(e)[:200]))

    W15.set_cog_payload(W15.cog_payload())
    pg.goto(base + "#/", wait_until="load")
    pg.wait_for_selector(".app-shell", timeout=25000)
    pg.wait_for_selector("[data-cog-map]", timeout=25000)
    settle(pg)

    record = {"viewport": list(VIEWPORT), "cycles": []}
    payload = W15.cog_payload()
    W15.set_cog_payload(payload)
    record["before"] = snapshot(pg)
    record["payload_sha"] = __import__("hashlib").sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()

    for i in range(1, cycles + 1):
        prev_id = pg.evaluate(NET_ID)
        pg.evaluate("() => window.__adminbotVm.openGraphFull()")
        pg.wait_for_function(ROUTE_FULL, timeout=15000)
        pg.wait_for_function("(n) => { const id = (" + NET_ID + ")();"
                             " return id !== 0 && id !== n; }",
                             arg=prev_id, timeout=15000)
        settle(pg)
        full = snapshot(pg)

        prev_id = full["netId"]
        pg.evaluate("() => window.__adminbotVm.closeGraphFull()")
        pg.wait_for_function(ROUTE_EMBEDDED, timeout=15000)
        pg.wait_for_function("(n) => { const id = (" + NET_ID + ")();"
                             " return id !== 0 && id !== n; }",
                             arg=prev_id, timeout=15000)
        settle(pg)
        emb = snapshot(pg)

        record["cycles"].append({"cycle": i, "full": full, "embedded": emb})

    record["after"] = record["cycles"][-1]["embedded"] if record["cycles"] \
        else record["before"]
    # Живые инварианты (камера/данные/выбор/скрытая вкладка) — только там, где
    # приложение отдаёт счётчики сцены (CMV-A+); на ревизии «до» они не
    # существуют, и подменять их догадками нельзя.
    if isinstance(record["before"].get("scene"), dict):
        record["live"] = live_checks(pg, payload)
    else:
        record["live"] = {"skipped": "у ревизии нет счётчиков сцены"}
    record["consoleErrors"] = console_errors
    record["pageErrors"] = page_errors
    ctx.close()
    return record


def evaluate(record, cycles):
    """Инварианты §10.2: счётчики не растут, сцена одна."""
    fails = []
    cycles_data = record["cycles"]
    if not cycles_data:
        return ["ни одного цикла не выполнено"]
    first = cycles_data[0]["embedded"]
    last = record["after"]
    base_raf = first["rafPending"]

    def expect(cond, message):
        if not cond:
            fails.append(message)

    expect(len(cycles_data) == cycles, "прогонов %d вместо %d"
           % (len(cycles_data), cycles))

    for row in cycles_data:
        for mode in ("full", "embedded"):
            snap = row[mode]
            expect(snap["netsLive"] == 1,
                   "цикл %d/%s: живых сетей %d (ожидалось 1)"
                   % (row["cycle"], mode, snap["netsLive"]))
            expect(snap["canvases"] <= 1,
                   "цикл %d/%s: canvas'ов в сцене %d (ожидалось ≤1)"
                   % (row["cycle"], mode, snap["canvases"]))
            expect(snap["visContainers"] <= 1,
                   "цикл %d/%s: контейнеров vis %d (ожидалось ≤1)"
                   % (row["cycle"], mode, snap["visContainers"]))
            expect(snap["rafPending"] <= base_raf + 2,
                   "цикл %d/%s: висящих RAF %d (база %d)"
                   % (row["cycle"], mode, snap["rafPending"], base_raf))
            expect(snap["net"], "цикл %d/%s: cognitionNetwork отсутствует"
                   % (row["cycle"], mode))

    expect(last["listenersLive"] <= first["listenersLive"],
           "обработчики vis выросли: %d → %d"
           % (first["listenersLive"], last["listenersLive"]))
    expect(last["winListeners"] <= first["winListeners"],
           "слушатели window выросли: %d → %d"
           % (first["winListeners"], last["winListeners"]))
    expect(last["docListeners"] <= first["docListeners"],
           "слушатели document выросли: %d → %d"
           % (first["docListeners"], last["docListeners"]))
    expect(last["netsMade"] == first["netsMade"] + 2 * (len(cycles_data) - 1),
           "сеть пересоздаётся не по одному разу на переход: %d → %d"
           % (first["netsMade"], last["netsMade"]))
    expect(not record["pageErrors"], "ошибки страницы: %r"
           % (record["pageErrors"][:3],))
    hard = [e for e in record["consoleErrors"] if "favicon" not in e.lower()]
    expect(not hard, "ошибки консоли: %r" % (hard[:3],))
    live = record.get("live") or {}
    if not live.get("skipped"):
        for f in live.get("fails", []):
            fails.append("живая проверка: " + f)
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None,
                    help="корень проверяемой ревизии (по умолчанию — свой)")
    ap.add_argument("--out", default=None,
                    help="каталог отчёта (по умолчанию evidence/cmv-a)")
    ap.add_argument("--cycles", type=int, default=CYCLES)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        repo, "plans", "features", "epic-cm-visual-01", "evidence", "cmv-a")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    os.chdir(repo)
    global M, W15
    import ui_round1025_matrix as M            # noqa: E402
    import ui_evol_w15_composition_e2e as W15  # noqa: E402

    # Порт 0 = свободный: на Windows второй bind с SO_REUSEADDR
    # разрешён, и на фиксированный порт может ответить чужой стенд.
    M.PORT = 0
    server = M._start_server()
    # Порт берём из фактически поднятого сервера: жёсткий номер мог быть занят
    # другим стендом (Windows разрешает второй bind с SO_REUSEADDR).
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    # Санитарная проверка: сервер обязан отдавать ИМЕННО этот репозиторий
    # (иначе «до/после» молча сравнивает одну и ту же ревизию).
    import hashlib
    import urllib.request
    served = urllib.request.urlopen(
        "http://127.0.0.1:%d/web/app.js" % port, timeout=10).read()
    local = open(os.path.join(repo, "web", "app.js"), "rb").read()
    sha_served = hashlib.sha256(served).hexdigest()
    sha_local = hashlib.sha256(local).hexdigest()
    from playwright.sync_api import sync_playwright
    report = {"repo": repo, "cycles": args.cycles, "viewport": list(VIEWPORT),
              "served_app_sha256": sha_served, "local_app_sha256": sha_local}
    if sha_served != sha_local:
        with open(os.path.join(out_dir, "cmv-a-scene-counters.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("FAIL: сервер отдаёт не тот app.js (%s != %s)"
              % (sha_served[:12], sha_local[:12]))
        return 3
    record = None
    fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            record = run(browser, base, args.cycles)
        except Exception:                       # noqa: BLE001
            traceback.print_exc()
            report["fatal"] = traceback.format_exc()[-1600:]
        finally:
            browser.close()
            server.shutdown()
    if record:
        report.update(record)
        fails = evaluate(record, args.cycles)
    else:
        fails = ["стенд не отработал"]

    report["fails"] = fails
    report["verdict"] = "OK" if not fails else "FAIL"
    path = os.path.join(out_dir, "cmv-a-scene-counters.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    if record:
        first = record["cycles"][0]["embedded"] if record["cycles"] else {}
        last = record["after"]
        print("cycles=%d" % len(record["cycles"]))
        for key in ("netsMade", "netsLive", "listenersLive", "rafPending",
                    "winListeners", "docListeners", "canvases",
                    "visContainers"):
            print("  %-13s %s -> %s" % (key, first.get(key), last.get(key)))
        scene = last.get("scene")
        if isinstance(scene, dict):
            print("  scene: " + json.dumps(scene, ensure_ascii=False))
    for f in fails:
        print("FAIL: " + f)
    print("report: " + path)
    print("CMV-A-SCENE-COUNTERS " + report["verdict"])
    if report["verdict"] == "OK":
        return 0
    return 2 if record else 3


if __name__ == "__main__":
    sys.exit(main())
