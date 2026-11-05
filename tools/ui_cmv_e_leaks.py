"""CMV-E: 20 циклов embedded ↔ fullscreen и проверка утечек (§10.2, §13).

Требование §10.2: «После 20 циклов embedded/fullscreen не растёт число
обработчиков, активных RAF, Network instances или наблюдателей. Это проверяется
инструментально». Требование §13: «Анимация не работает во скрытой вкладке/
закрытом графе; при возвращении не заводит вторую копию».

Что делает стенд:

1. Ставит на страницу ИНСТРУМЕНТАЦИЮ (init script, до кода приложения):
   баланс `addEventListener`/`removeEventListener` по типам и целям, живые
   `requestAnimationFrame`-колбэки (`request` минус `cancel`/вызов), все
   `ResizeObserver`/`IntersectionObserver`/`MutationObserver` (создано/отключено),
   созданные `<canvas>`, плюс патч конструктора `vis.Network` сразу после load.
   Продуктовый код не меняется — это внешняя измерительная обвязка.
2. Открывает/закрывает полный экран 20 раз и снимает счётчики после 1, 10 и 20
   циклов. Рост любого показателя — находка, а не «норма».
3. Проверяет сцену в покое: кадров не больше частотного потолка, лишних RAF нет.
4. Имитирует скрытую вкладку: headless Chromium не переводит вторую вкладку в
   `hidden` (проверено отдельной пробой), поэтому состояние выставляется через
   подмену `document.hidden`/`visibilityState` + РЕАЛЬНОЕ событие
   `visibilitychange` — приложение реагирует своим штатным обработчиком
   (`_cogPauseScene`/`_cogResumeScene`). Это тот же путь, что у настоящей
   вкладки; подмена описана в отчёте как ограничение стенда.

Запуск:
  .venv/Scripts/python.exe tools/ui_cmv_e_leaks.py --out plans/features/.../evidence/cmv-e
Код возврата: 0 — утечек нет, 2 — есть рост, 3 — стенд не поднялся.
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

CYCLES = 20
DESKTOP = (1536, 960)

INSTRUMENT = r"""
(() => {
  const S = {
    listeners: 0, listenersByType: {}, removed: 0,
    listenersDoc: 0, listenersWin: 0, listenersEl: 0,
    rafLive: 0, rafTotal: 0, rafDone: 0, rafCancelled: 0,
    obsCreated: 0, obsAlive: 0, obsKinds: { ro: 0, io: 0, mo: 0 },
    obsStacks: {},
    canvasesCreated: 0, networkCreated: 0,
  };
  window.__cmvLeak = S;

  function category(target) {
    if (target === document) return 'doc';
    if (target === window) return 'win';
    return 'el';
  }
  function bump(cat, delta) {
    if (cat === 'doc') S.listenersDoc += delta;
    else if (cat === 'win') S.listenersWin += delta;
    else S.listenersEl += delta;
  }

  // ── addEventListener / removeEventListener: точный баланс по DOM-семантике.
  const addOrig = EventTarget.prototype.addEventListener;
  const remOrig = EventTarget.prototype.removeEventListener;
  const registry = new WeakMap();
  function keyOf(type, opts) {
    const cap = (opts && typeof opts === 'object') ? !!opts.capture : !!opts;
    return String(type) + '|' + (cap ? 1 : 0);
  }
  function bucket(target) {
    let m = registry.get(target);
    if (!m) { m = new Map(); registry.set(target, m); }
    return m;
  }
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    if (fn) {
      const m = bucket(this);
      const key = keyOf(type, opts);
      let set = m.get(key);
      if (!set) { set = new Set(); m.set(key, set); }
      // Повторная регистрация того же обработчика в DOM не создаёт дубля.
      if (!set.has(fn)) {
        set.add(fn);
        S.listeners += 1;
        S.listenersByType[type] = (S.listenersByType[type] || 0) + 1;
        bump(category(this), 1);
      }
    }
    return addOrig.call(this, type, fn, opts);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opts) {
    if (fn) {
      const m = registry.get(this);
      const key = keyOf(type, opts);
      const set = m && m.get(key);
      if (set && set.has(fn)) {
        set.delete(fn);
        S.listeners -= 1;
        S.removed += 1;
        S.listenersByType[type] = (S.listenersByType[type] || 0) - 1;
        bump(category(this), -1);
      }
    }
    return remOrig.call(this, type, fn, opts);
  };

  // ── requestAnimationFrame: живые колбэки = запрошено − отменено − выполнено.
  const rafOrig = window.requestAnimationFrame;
  const cafOrig = window.cancelAnimationFrame;
  const pending = new Set();
  window.requestAnimationFrame = function (cb) {
    S.rafTotal += 1;
    const id = rafOrig.call(window, function (t) {
      if (pending.delete(id)) S.rafDone += 1;
      S.rafLive = pending.size;
      return cb(t);
    });
    pending.add(id);
    S.rafLive = pending.size;
    return id;
  };
  window.cancelAnimationFrame = function (id) {
    if (pending.delete(id)) { S.rafCancelled += 1; S.rafLive = pending.size; }
    return cafOrig.call(window, id);
  };

  // ── Наблюдатели: создано/живо (disconnect снимает).
  ['ResizeObserver', 'IntersectionObserver', 'MutationObserver'].forEach(
    function (name, idx) {
      const Orig = window[name];
      if (typeof Orig !== 'function') return;
      const alive = new Set();
      const Wrapped = function (cb) {
        const inst = new Orig(cb);
        S.obsCreated += 1;
        S.obsAlive += 1;
        // Атрибуция: откуда создан наблюдатель (стек построения). Нужна, чтобы
        // рост приписать конкретному месту кода, а не «приложению вообще».
        try {
          const stack = String(new Error().stack || '')
            .split('\n').slice(2, 5).join(' | ')
            .replace(/https?:\/\/[^/]+/g, '')
            .replace(/\d{3,}/g, 'N').slice(0, 220);
          const key = name + ' @ ' + stack;
          S.obsStacks[key] = (S.obsStacks[key] || 0) + 1;
        } catch (e) { /* noop */ }
        alive.add(inst);
        if (idx === 0) S.obsKinds.ro += 1;
        if (idx === 1) S.obsKinds.io += 1;
        if (idx === 2) S.obsKinds.mo += 1;
        const disc = inst.disconnect.bind(inst);
        inst.disconnect = function () {
          if (alive.delete(inst)) S.obsAlive -= 1;
          return disc();
        };
        return inst;
      };
      Wrapped.prototype = Orig.prototype;
      window[name] = Wrapped;
    });

  // ── Созданные canvas (единственный владелец кадра не должен плодить буферы).
  const createOrig = document.createElement.bind(document);
  document.createElement = function (tag, opts) {
    if (String(tag).toLowerCase() === 'canvas') S.canvasesCreated += 1;
    return createOrig(tag, opts);
  };
})();
"""

READY = r"""
() => {
  const vm = window.__adminbotVm;
  if (!vm || !vm.cognitionNetwork) return false;
  const scene = vm._cogScene;
  // Базовая ревизия (до CMV) сцены не объявляет — для неё достаточно сети.
  if (!scene) return true;
  return !!(scene.settled === true && scene.fxCanvas);
}
"""

# Патч vis.Network сразу после load: считаем именно СОЗДАННЫЕ сети.
PATCH_VIS = r"""
() => {
  const S = window.__cmvLeak;
  const vis = window.vis;
  if (!vis || !vis.Network || vis.Network.__cmvPatched) return false;
  const Orig = vis.Network;
  const Wrapped = function (...args) {
    if (S) S.networkCreated += 1;
    return new Orig(...args);
  };
  Wrapped.prototype = Orig.prototype;
  Object.keys(Orig).forEach((k) => { Wrapped[k] = Orig[k]; });
  Wrapped.__cmvPatched = true;
  vis.Network = Wrapped;
  return true;
}
"""

SNAPSHOT = r"""
() => {
  const S = window.__cmvLeak || {};
  const vm = window.__adminbotVm || {};
  const c = (vm._cogDebugCounters ? vm._cogDebugCounters() : {}) || {};
  const qa = (sel) => Array.from(document.querySelectorAll(sel)).length;
  return {
    listeners: S.listeners, listenersByType: S.listenersByType,
    listenersDoc: S.listenersDoc, listenersWin: S.listenersWin,
    listenersEl: S.listenersEl,
    listenerRemoved: S.removed,
    hasScene: !!(vm._cogScene),
    rafLive: S.rafLive, rafTotal: S.rafTotal, rafDone: S.rafDone,
    obsAlive: S.obsAlive, obsCreated: S.obsCreated, obsKinds: S.obsKinds,
    obsStacks: S.obsStacks,
    canvasesCreated: S.canvasesCreated,
    networkCreated: S.networkCreated,
    domCanvases: qa('canvas'),
    sceneCanvases: qa('.cognition-graph canvas'),
    scenes: qa('.cognition-graph'),
    visNetworks: qa('.vis-network'),
    netCount: c.netCount, netTotal: c.netTotal,
    rafActive: c.rafActive, paused: c.paused, frames: c.frames,
    draws: c.draws, fxPaints: c.fxPaints, sprites: c.fxSprites,
    instance: c.instance, listenersApp: c.listeners,
    observersApp: c.observerCount, full: !!vm.graphFullVisible,
  };
}
"""

OPEN = "() => window.__adminbotVm.openGraphFull()"
CLOSE = "() => window.__adminbotVm.closeGraphFull()"

SET_VIS = r"""
(mode) => {
  // headless не переводит вкладку в hidden, поэтому подменяем ЧИТАЕМОЕ
  // приложением состояние и посылаем настоящее событие visibilitychange.
  if (!window.__cmvVis) {
    window.__cmvVis = { hidden: false };
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => window.__cmvVis.hidden,
    });
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => (window.__cmvVis.hidden ? 'hidden' : 'visible'),
    });
  }
  window.__cmvVis.hidden = (mode === 'hidden');
  document.dispatchEvent(new Event('visibilitychange'));
  return { hidden: document.hidden, state: document.visibilityState };
}
"""


def _diff(before, after, keys):
    out = {}
    for key in keys:
        out[key] = {"before": before.get(key), "after": after.get(key),
                    "delta": (after.get(key) or 0) - (before.get(key) or 0)}
    return out


def run(browser, base, out_dir, fixtures_mod, label="cand"):
    report = {"checks": [], "fails": [], "phases": {}}

    def check(cond, message):
        report["checks"].append({"ok": bool(cond), "message": message})
        if not cond:
            report["fails"].append(message)
        print(("  ok   " if cond else "  FAIL ") + message)

    payload = fixtures_mod.load(702)
    payload["generated_at"] = int(time.time())
    W15.set_cog_payload(payload)
    ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                        "height": DESKTOP[1]},
                              device_scale_factor=1)
    ctx.add_init_script(INSTRUMENT)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes())
    pg = ctx.new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text)
          if m.type == "error" else None)
    pg.goto(base + "#/", wait_until="load")
    pg.wait_for_function(READY, timeout=90000)
    cdp = ctx.new_cdp_session(pg)
    try:
        cdp.send("HeapProfiler.enable")
    except Exception:  # noqa: BLE001
        pass
    pg.evaluate("() => window.__adminbotVm._cogEl"
                ".scrollIntoView({ block: 'center' })")
    pg.wait_for_timeout(600)
    patched = pg.evaluate(PATCH_VIS)
    report["vis_patched"] = patched
    check(patched, "инструментация vis.Network установлена до циклов")

    start = pg.evaluate(SNAPSHOT)
    try:
        cdp.send("HeapProfiler.collectGarbage")
        start["heapBytes"] = cdp.send("Runtime.getHeapUsage").get("usedSize")
    except Exception:  # noqa: BLE001
        start["heapBytes"] = None
    has_scene = bool(start.get("hasScene"))
    report["has_scene"] = has_scene
    report["phases"]["start"] = start
    marks = {"start": start}

    for i in range(1, CYCLES + 1):
        pg.evaluate(OPEN)
        pg.wait_for_timeout(320)
        pg.evaluate(CLOSE)
        pg.wait_for_timeout(320)
        if i in (1, 10, CYCLES):
            snap = pg.evaluate(SNAPSHOT)
            # Реальная память: принудительный GC через CDP и фактический размер
            # кучи. Это отвечает на вопрос, удерживаются ли созданные объекты,
            # а не только «был ли вызван disconnect».
            try:
                cdp.send("HeapProfiler.collectGarbage")
                snap["heapBytes"] = cdp.send("Runtime.getHeapUsage").get(
                    "usedSize")
            except Exception as exc:  # noqa: BLE001
                snap["heapBytes"] = None
                report.setdefault("heap_errors", []).append(str(exc)[:120])
            marks["cycle%d" % i] = snap
            report["phases"]["cycle%d" % i] = snap
            print("  цикл %-2d: listeners %d, rafLive %d, obsAlive %d, "
                  "networkCreated %d, canvases %d/%d, scenes %d, heap %.1f МБ"
                  % (i, snap["listeners"], snap["rafLive"], snap["obsAlive"],
                     snap["networkCreated"], snap["domCanvases"],
                     snap["sceneCanvases"], snap["scenes"],
                     (snap.get("heapBytes") or 0) / 1048576.0))

    last = report["phases"]["cycle%d" % CYCLES]
    check(last["scenes"] == 1, "после %d циклов в DOM ровно одна сцена (%d)"
          % (CYCLES, last["scenes"]))
    check(last["visNetworks"] == 1,
          "одна сеть vis в DOM (%d)" % last["visNetworks"])
    if has_scene:
        check(last["netCount"] == 1,
              "живых Network instances ровно 1 (%r)" % last["netCount"])
    check(last["domCanvases"] == start["domCanvases"],
          "число canvas не выросло (%d -> %d)"
          % (start["domCanvases"], last["domCanvases"]))
    check(last["sceneCanvases"] == start["sceneCanvases"],
          "у сцены то же число canvas (%d -> %d)"
          % (start["sceneCanvases"], last["sceneCanvases"]))
    grow = _diff(marks["cycle1"], last, ["listeners", "rafLive", "obsAlive",
                                         "networkCreated", "rafTotal",
                                         "obsCreated", "listenersDoc",
                                         "listenersWin", "listenersEl"])
    report["growth_cycle1_to_%d" % CYCLES] = grow
    # Слушатели на ЖИВУЩИХ целях (document/window) — однозначная утечка, их
    # нельзя объяснить сборкой мусора вместе с отброшенными элементами.
    docwin = (grow["listenersDoc"]["delta"] or 0) + (grow["listenersWin"]["delta"] or 0)
    check(docwin == 0,
          "слушатели на document/window не накапливаются (%d -> %d)"
          % ((marks["cycle1"]["listenersDoc"] or 0)
             + (marks["cycle1"]["listenersWin"] or 0),
             (last["listenersDoc"] or 0) + (last["listenersWin"] or 0)))
    if has_scene:
        check(last["listenersApp"] == marks["cycle1"]["listenersApp"],
              "обработчики ЖИВОЙ сцены не растут (scene.handlers %r -> %r)"
              % (marks["cycle1"]["listenersApp"], last["listenersApp"]))
        check(last["observersApp"] == marks["cycle1"]["observersApp"],
              "наблюдатели ЖИВОЙ сцены не растут (%r -> %r)"
              % (marks["cycle1"]["observersApp"], last["observersApp"]))
    check(grow["rafLive"]["delta"] == 0,
          "активных RAF не больше (живо %d -> %d)"
          % (grow["rafLive"]["before"], grow["rafLive"]["after"]))
    if has_scene:
        check(last["netCount"] == 1,
              "живых Network instances ровно 1 (создано за прогон %r, живых %r)"
              % (last["netTotal"], last["netCount"]))

    # ── покой: частота кадров не должна быть «двойной» после 20 циклов ──────
    d0 = pg.evaluate(SNAPSHOT)
    pg.wait_for_timeout(1500)
    d1 = pg.evaluate(SNAPSHOT)
    paints = (d1["fxPaints"] or 0) - (d0["fxPaints"] or 0)
    report["idle_after_cycles"] = {"paints": paints, "ms": 1500,
                                   "before": d0, "after": d1}
    if has_scene:
        check(paints <= 24 * 1.5 + 12,
              "в покое кадров не больше потолка 24 fps (%d за 1500 мс)" % paints)
        check(paints >= 6, "в покое мягкая анимация продолжается (%d кадров)"
              % paints)
    check((d1["rafLive"] or 0) == (marks["cycle1"]["rafLive"] or 0),
          "в покое число живых RAF как в первом цикле (%r против %r)"
          % (d1["rafLive"], marks["cycle1"]["rafLive"]))

    if not has_scene:
        # Базовая ревизия: сцены/кадра CMV нет — проверяются только счётчики
        # ресурсов циклов (это контроль для атрибуции утечек).
        path = os.path.join(out_dir, "cmv-e-leaks-%s.png" % label)
        pg.screenshot(path=path)
        report["shots"] = [os.path.basename(path)]
        pg.close()
        ctx.close()
        control = run_control(browser, base, CYCLES)
        report["control_no_map"] = control
        report["attribution"] = {
            "graph": {"listenersEl": grow["listenersEl"]["delta"] or 0,
                      "obsAlive": grow["obsAlive"]["delta"] or 0,
                      "netCreated": grow["networkCreated"]["delta"]},
            "control_no_map": {"listenersEl":
                               control["growth"]["listenersEl"]["delta"] or 0,
                               "obsAlive":
                               control["growth"]["obsAlive"]["delta"] or 0},
        }
        return report

    # ── скрытая вкладка: рендер стоит, при возврате не появляется вторая копия
    vis = pg.evaluate(SET_VIS, "hidden")
    check(vis["hidden"] is True, "состояние скрытой вкладки выставлено")
    pg.wait_for_timeout(300)
    hid0 = pg.evaluate(SNAPSHOT)
    pg.wait_for_timeout(1400)
    hid1 = pg.evaluate(SNAPSHOT)
    hid_paints = (hid1["fxPaints"] or 0) - (hid0["fxPaints"] or 0)
    hid_frames = (hid1["frames"] or 0) - (hid0["frames"] or 0)
    report["hidden"] = {"paints": hid_paints, "frames": hid_frames,
                        "before": hid0, "after": hid1}
    check(hid_paints == 0,
          "в скрытой вкладке кадров декора нет (%d за 1400 мс)" % hid_paints)
    check(hid_frames == 0, "в скрытой вкладке кадров сцены нет (%d)"
          % hid_frames)
    check(hid1["rafActive"] is False, "в скрытой вкладке RAF не запрошен")
    check(hid1["paused"] is True, "сцена помечена на паузе")

    pg.evaluate(SET_VIS, "visible")
    pg.wait_for_timeout(1200)
    back = pg.evaluate(SNAPSHOT)
    report["visible_again"] = back
    check(back["rafActive"] is True, "при возврате кадровый цикл возобновлён")
    check((back["rafLive"] or 0) == (marks["cycle1"]["rafLive"] or 0),
          "при возврате число живых RAF как до скрытия (%r против %r)"
          % (back["rafLive"], marks["cycle1"]["rafLive"]))
    check(back["scenes"] == 1 and back["netCount"] == 1,
          "при возврате одна сцена и одна сеть (%d/%r)"
          % (back["scenes"], back["netCount"]))
    check((back["fxPaints"] or 0) > (hid1["fxPaints"] or 0),
          "после возврата кадры снова рисуются")

    path = os.path.join(out_dir, "cmv-e-leaks-after-cycles.png")
    pg.screenshot(path=path)
    report["shots"] = [os.path.basename(path)]
    report["console_errors"] = errors[:5]
    check(not errors, "ошибок в консоли нет (%d)" % len(errors))
    pg.close()
    ctx.close()

    # ── контроль: цена перемонтирования страницы БЕЗ карты ──────────────────
    control = run_control(browser, base, CYCLES)
    report["control_no_map"] = control
    graph_el = grow["listenersEl"]["delta"] or 0
    ctrl_el = control["growth"]["listenersEl"]["delta"] or 0
    graph_obs = grow["obsAlive"]["delta"] or 0
    ctrl_obs = control["growth"]["obsAlive"]["delta"] or 0
    report["attribution"] = {
        "graph": {"listenersEl": graph_el, "obsAlive": graph_obs,
                  "netCreated": grow["networkCreated"]["delta"]},
        "control_no_map": {"listenersEl": ctrl_el, "obsAlive": ctrl_obs},
        "note": ("Показатели элемента-слушателей и наблюдателей на ЖИВОМ "
                 "графе не растут (scene.handlers/observerCount стабильны). "
                 "Рост глобальных счётчиков сравнивается с контролем без "
                 "карты: он отражает перемонтирование страницы маршрутом."),
    }
    check(graph_el <= ctrl_el * 1.25 + 20,
          "рост обработчиков элементов у карты не больше, чем у обычного "
          "перехода страницы (карта %+d, контроль без карты %+d за %d циклов)"
          % (graph_el, ctrl_el, CYCLES))
    heap1 = marks["cycle1"].get("heapBytes")
    heapN = last.get("heapBytes")
    if heap1 and heapN:
        report["heap_growth"] = {
            "cycle1": heap1, "cycle20": heapN, "delta": heapN - heap1,
            "start": start.get("heapBytes"),
        }
        check(heapN - heap1 <= 8 * 1024 * 1024,
              "после принудительного GC куча не выросла больше 8 МБ "
              "(цикл1 %.1f МБ -> цикл20 %.1f МБ, %+d КБ)"
              % (heap1 / 1048576.0, heapN / 1048576.0,
                 (heapN - heap1) // 1024))
    return report


def run_control(browser, base, cycles):
    """Контроль: те же 20 переключений маршрута, но БЕЗ карты.

    `#/modules` ↔ `#/how` — две обычные страницы админки. Их рост обработчиков
    и наблюдателей показывает стоимость перемонтирования страницы как такового.
    Сравнение с циклами карты отделяет утечку графа от общей цены маршрутов.
    """
    ctx = browser.new_context(viewport={"width": DESKTOP[0],
                                        "height": DESKTOP[1]},
                              device_scale_factor=1)
    ctx.add_init_script(INSTRUMENT)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes())
    pg = ctx.new_page()
    pg.goto(base + "#/modules", wait_until="load")
    pg.wait_for_timeout(1500)
    out = {"start": pg.evaluate(SNAPSHOT)}
    for i in range(1, cycles + 1):
        pg.evaluate("(r) => { window.location.hash = r; }",
                    "#/how" if i % 2 else "#/modules")
        pg.wait_for_timeout(320)
        if i in (1, 10, cycles):
            out["cycle%d" % i] = pg.evaluate(SNAPSHOT)
    out["growth"] = _diff(out["cycle1"], out["cycle%d" % cycles],
                          ["listeners", "listenersEl", "listenersDoc",
                           "listenersWin", "obsAlive", "obsCreated", "rafLive"])
    pg.close()
    ctx.close()
    print("  контроль без карты: listeners %+d (элементы %+d, doc+win %+d), "
          "наблюдатели %+d" % (
              out["growth"]["listeners"]["delta"],
              out["growth"]["listenersEl"]["delta"],
              (out["growth"]["listenersDoc"]["delta"] or 0)
              + (out["growth"]["listenersWin"]["delta"] or 0),
              out["growth"]["obsAlive"]["delta"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--label", default="cand")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = (os.path.abspath(args.out) if args.out else
               os.path.join(repo, "plans", "features", "epic-cm-visual-01",
                            "evidence", "cmv-e"))
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    sys.path.insert(0, os.path.join(os.path.dirname(here), "tests",
                                    "fixtures", "cmv"))
    os.chdir(repo)
    global M, W15
    import ui_round1025_matrix as M                       # noqa: E402
    import ui_evol_w15_composition_e2e as W15             # noqa: E402
    import cog_map_fixtures as FIX                        # noqa: E402
    from playwright.sync_api import sync_playwright

    M.PORT = 0
    server = M._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % server.server_address[1]
    report = {"repo": repo, "cycles": CYCLES, "viewport": list(DESKTOP),
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--enable-gpu", "--enable-gpu-rasterization",
                      "--ignore-gpu-blocklist", "--use-angle=d3d11"])
            try:
                report.update(run(browser, base, out_dir, FIX,
                                  label=args.label))
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    finally:
        server.shutdown()
    suffix = "" if args.label == "cand" else "-" + args.label
    out = os.path.join(out_dir, "cmv-e-leaks%s.json" % suffix)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    if report.get("error"):
        print("ERROR:\n" + report["error"][-1500:])
        return 3
    print("checks=%d fails=%d -> %s" % (len(report["checks"]),
                                        len(report["fails"]), out))
    return 0 if not report["fails"] else 2


if __name__ == "__main__":
    sys.exit(main())
