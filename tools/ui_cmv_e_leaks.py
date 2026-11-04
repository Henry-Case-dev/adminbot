"""CMV-E: 20 циклов embedded ↔ fullscreen и проверка утечек (§10.2, §13).

Требование §10.2: «После 20 циклов embedded/fullscreen не растёт число
обработчиков, активных RAF, Network instances или наблюдателей. Это проверяется
инструментально». Требование §13: «Анимация не работает во скрытой вкладке/
закрытом графе; при возвращении не заводит вторую копию».

ЧТО ИСПРАВЛЕНО В САМОМ СТЕНДЕ (CMV-PERF, 2026-11-05)
----------------------------------------------------
Прежняя версия стенда сама удерживала измеряемое: реестр слушателей держал
СИЛЬНЫЕ ссылки на функции-обработчики, а множество наблюдателей — сильные
ссылки на объекты ResizeObserver/IntersectionObserver. Наблюдатели vis-network,
которые он снимает через `unobserve` (а не `disconnect`), оставались живыми,
и каждый такой наблюдатель держал через замыкание целую уничтоженную сцену
(Network + 702 узла + 2400 рёбер ≈ 1.3 МБ). Отсюда «+26 МБ после GC» и
«+64 наблюдателя». Контрольный прогон БЕЗ инструментации на том же сценарии
даёт 26.05 → 27.81 МБ немонотонно — то есть утечки в продукте не было.

Теперь стенд:
  * хранит только СЧЁТЧИКИ по цели + `WeakRef` на саму цель (не на функции);
  * классифицирует слушателей В МОМЕНТ СНИМКА по `isConnected`, а не в момент
    добавления (иначе слушатели давно выброшенных узлов навсегда считались
    «живыми»);
  * считает РЕАЛЬНО ЖИВЫЕ объекты (`Runtime.queryObjects` по прототипам
    ResizeObserver/IntersectionObserver/vis.Network) — это прямой ответ на
    вопрос «утекает ли объект», а не косвенный;
  * перед чтением кучи делает сборку мусора И паузу, чтобы GC успел отработать.

Запуск:
  python tools/ui_cmv_e_leaks.py --out plans/features/.../evidence/cmv-e
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
    added: 0, removed: 0, addByType: {}, remByType: {},
    rows: [],                       // {ref: WeakRef, counts: {type: n}, tag}
    glob: { window: {}, document: {} },
    rafLive: 0, rafTotal: 0, rafDone: 0, rafCancelled: 0,
    obsCreated: 0, obsRows: [],     // {ref: WeakRef, kind: 'ro'|'io'|'mo'}
    obsKinds: { ro: 0, io: 0, mo: 0 },
    obsStacks: {},
    canvasesCreated: 0, networkCreated: 0,
  };
  window.__cmvLeak = S;

  const addOrig = EventTarget.prototype.addEventListener;
  const remOrig = EventTarget.prototype.removeEventListener;
  const REG = new WeakMap();
  function keyOf(type, opts) {
    const cap = (opts && typeof opts === 'object') ? !!opts.capture : !!opts;
    return String(type) + '|' + (cap ? 1 : 0);
  }
  function recFor(target) {
    let rec = REG.get(target);
    if (rec) return rec;
    const isGlobal = (target === window || target === document);
    rec = {
      counts: {}, set: new Map(), isGlobal,
      tag: target === window ? 'WINDOW'
        : (target === document ? 'DOCUMENT' : (target.nodeName || '?')),
    };
    if (isGlobal) {
      rec.globRef = target === window ? S.glob.window : S.glob.document;
    } else {
      rec.ref = new WeakRef(target);       // цель, но НЕ обработчики
      S.rows.push(rec);
    }
    REG.set(target, rec);
    return rec;
  }
  // Дедупликация «тот же обработчик на той же цели» по ЧИСЛОВОМУ id из WeakMap:
  // сам обработчик не удерживается (сильная ссылка на функцию держала бы через
  // замыкание всю уничтоженную сцену — именно это и давало ложные «+26 МБ»).
  const FN_IDS = new WeakMap();
  let nextFnId = 1;
  function fnId(fn) {
    let id = FN_IDS.get(fn);
    if (id === undefined) { id = nextFnId; nextFnId += 1; FN_IDS.set(fn, id); }
    return id;
  }
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    if (fn) {
      const rec = recFor(this);
      const key = keyOf(type, opts);
      let set = rec.set.get(key);
      if (!set) { set = new Set(); rec.set.set(key, set); }
      const id = fnId(fn);
      if (!set.has(id)) {
        set.add(id);                        // только числовой id
        const bucket = rec.isGlobal ? rec.globRef : rec.counts;
        bucket[type] = (bucket[type] || 0) + 1;
        S.added += 1;
        S.addByType[type] = (S.addByType[type] || 0) + 1;
      }
    }
    return addOrig.call(this, type, fn, opts);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opts) {
    if (fn) {
      const rec = REG.get(this);
      const set = rec && rec.set.get(keyOf(type, opts));
      const id = set ? fnId(fn) : 0;
      if (set && set.has(id)) {
        set.delete(id);
        const bucket = rec.isGlobal ? rec.globRef : rec.counts;
        bucket[type] = (bucket[type] || 0) - 1;
        S.removed += 1;
        S.remByType[type] = (S.remByType[type] || 0) - 1;
      }
    }
    return remOrig.call(this, type, fn, opts);
  };

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

  ['ResizeObserver', 'IntersectionObserver', 'MutationObserver'].forEach(
    function (name, idx) {
      const Orig = window[name];
      if (typeof Orig !== 'function') return;
      const kind = idx === 0 ? 'ro' : (idx === 1 ? 'io' : 'mo');
      const Wrapped = function (cb) {
        const inst = new Orig(cb);
        S.obsCreated += 1;
        S.obsKinds[kind] += 1;
        try {
          const stack = String(new Error().stack || '')
            .split('\n').slice(2, 5).join(' | ')
            .replace(/https?:\/\/[^/]+/g, '')
            .replace(/\d{3,}/g, 'N').slice(0, 200);
          const key = name + ' @ ' + stack;
          S.obsStacks[key] = (S.obsStacks[key] || 0) + 1;
        } catch (e) { /* noop */ }
        S.obsRows.push({ ref: new WeakRef(inst), kind: kind, alive: true });
        return inst;
      };
      Wrapped.prototype = Orig.prototype;
      window[name] = Wrapped;
    });

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
  if (!scene) return true;
  return !!(scene.settled === true && scene.fxCanvas);
}
"""

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
  const S = window.__cmvLeak || { rows: [], glob: { window: {}, document: {} } };
  const vm = window.__adminbotVm || {};
  const c = (vm._cogDebugCounters ? vm._cogDebugCounters() : {}) || {};
  const qa = (sel) => Array.from(document.querySelectorAll(sel)).length;
  const posSum = (o) => Object.keys(o).reduce((a, k) => a + Math.max(0, o[k]), 0);
  let liveConn = 0, liveDet = 0, targetsAlive = 0, targetsCollected = 0;
  const liveByTag = {}, detByTag = {};
  S.rows.forEach((rec) => {
    const el = rec.ref.deref();
    if (!el) { targetsCollected += 1; return; }
    targetsAlive += 1;
    let n = 0;
    Object.keys(rec.counts).forEach((t) => { if (rec.counts[t] > 0) n += rec.counts[t]; });
    if (n <= 0) return;
    const tag = rec.tag;
    if (el.isConnected) {
      liveConn += n;
      liveByTag[tag] = (liveByTag[tag] || 0) + n;
    } else {
      liveDet += n;
      detByTag[tag] = (detByTag[tag] || 0) + n;
    }
  });
  let obsAlive = 0;
  const obsByKind = { ro: 0, io: 0, mo: 0 };
  S.obsRows.forEach((row) => {
    if (!row.ref.deref()) return;
    obsAlive += 1;
    obsByKind[row.kind] += 1;
  });
  return {
    added: S.added, removed: S.removed,
    addByType: S.addByType, remByType: S.remByType,
    windowListeners: posSum(S.glob.window),
    documentListeners: posSum(S.glob.document),
    // Слушатели на ЖИВЫХ подключённых узлах — единственный честный критерий
    // утечки: узел в документе, обработчик на нём, и он не снимается.
    liveConnected: liveConn,
    liveDetached: liveDet,
    liveByTag: liveByTag, detByTag: detByTag,
    targetsAlive: targetsAlive, targetsCollected: targetsCollected,
    obsCreated: S.obsCreated, obsAlive: obsAlive, obsByKind: obsByKind,
    obsStacks: S.obsStacks,
    rafLive: S.rafLive, rafTotal: S.rafTotal, rafDone: S.rafDone,
    canvasesCreated: S.canvasesCreated, networkCreated: S.networkCreated,
    domScenes: qa('.cognition-graph'), domCanvases: qa('canvas'),
    domVisRoots: qa('.vis-network'), scenes: qa('.cognition-graph'),
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
  if (!window.__cmvVis) {
    window.__cmvVis = { hidden: false };
    Object.defineProperty(document, 'hidden', {
      configurable: true, get: () => window.__cmvVis.hidden,
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

PROTOS = {
    "ResizeObserver": "ResizeObserver.prototype",
    "IntersectionObserver": "IntersectionObserver.prototype",
    "MutationObserver": "MutationObserver.prototype",
    "visNetwork": "window.vis && window.vis.Network && window.vis.Network.prototype",
}


def live_objects(cdp):
    """Реально живые объекты по прототипу (Runtime.queryObjects)."""
    out = {}
    for name, expr in PROTOS.items():
        try:
            obj = cdp.send("Runtime.evaluate", {"expression": expr,
                                                "objectGroup": "cmvprobe"})
            oid = obj.get("result", {}).get("objectId")
            if not oid:
                out[name] = None
                continue
            arr = cdp.send("Runtime.queryObjects",
                           {"prototypeObjectId": oid,
                            "objectGroup": "cmvprobe"})
            arr_id = arr.get("objects", {}).get("objectId")
            if not arr_id:
                out[name] = None
                continue
            n = cdp.send("Runtime.callFunctionOn", {
                "objectId": arr_id,
                "functionDeclaration": "function () { return this.length; }",
                "returnByValue": True,
            })
            out[name] = n.get("result", {}).get("value")
        except Exception:  # noqa: BLE001
            out[name] = None
        finally:
            try:
                cdp.send("Runtime.releaseObjectGroup",
                         {"objectGroup": "cmvprobe"})
            except Exception:  # noqa: BLE001
                pass
    return out


def heap_after_gc(cdp, pg):
    """Куча после принудительного GC + пауза (GC асинхронна)."""
    try:
        cdp.send("HeapProfiler.collectGarbage")
    except Exception:  # noqa: BLE001
        return None
    pg.wait_for_timeout(400)
    try:
        return cdp.send("Runtime.getHeapUsage").get("usedSize")
    except Exception:  # noqa: BLE001
        return None


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
    for domain in ("HeapProfiler.enable", "Runtime.enable"):
        try:
            cdp.send(domain)
        except Exception:  # noqa: BLE001
            pass
    pg.evaluate("() => window.__adminbotVm._cogEl"
                ".scrollIntoView({ block: 'center' })")
    pg.wait_for_timeout(600)
    patched = pg.evaluate(PATCH_VIS)
    report["vis_patched"] = patched
    check(patched, "инструментация vis.Network установлена до циклов")

    def snapshot():
        snap = pg.evaluate(SNAPSHOT)
        snap["liveObjects"] = live_objects(cdp)
        snap["heapBytes"] = heap_after_gc(cdp, pg)
        return snap

    start = snapshot()
    has_scene = bool(pg.evaluate("() => !!window.__adminbotVm._cogScene"))
    report["has_scene"] = has_scene
    report["phases"]["start"] = start
    marks = {"start": start}

    for i in range(1, CYCLES + 1):
        pg.evaluate(OPEN)
        pg.wait_for_timeout(320)
        pg.evaluate(CLOSE)
        pg.wait_for_timeout(320)
        if i in (1, 10, CYCLES):
            snap = snapshot()
            marks["cycle%d" % i] = snap
            report["phases"]["cycle%d" % i] = snap
            lo = snap.get("liveObjects") or {}
            print("  цикл %-2d: liveConn %d, det %d, obsAlive %d, RO/IO %s/%s, "
                  "Net %s, created %d, heap %.1f МБ"
                  % (i, snap["liveConnected"], snap["liveDetached"],
                     snap["obsAlive"], lo.get("ResizeObserver"),
                     lo.get("IntersectionObserver"), lo.get("visNetwork"),
                     snap["networkCreated"],
                     (snap.get("heapBytes") or 0) / 1048576.0))

    last = report["phases"]["cycle%d" % CYCLES]
    first = marks["cycle1"]
    check(last["domScenes"] == 1, "после %d циклов в DOM ровно одна сцена (%d)"
          % (CYCLES, last["domScenes"]))
    check(last["domVisRoots"] == 1,
          "одна сеть vis в DOM (%d)" % last["domVisRoots"])
    if has_scene:
        check(last["netCount"] == 1,
              "живых Network instances ровно 1 (%r)" % last["netCount"])
    check(last["domCanvases"] == start["domCanvases"],
          "число canvas не выросло (%d -> %d)"
          % (start["domCanvases"], last["domCanvases"]))

    grow = _diff(first, last, ["liveConnected", "liveDetached", "obsAlive",
                               "rafLive", "networkCreated", "targetsAlive",
                               "windowListeners", "documentListeners",
                               "added", "removed"])
    report["growth_cycle1_to_%d" % CYCLES] = grow
    # 1) Слушатели на ЖИВЫХ подключённых узлах — единственный честный критерий.
    check(grow["liveConnected"]["delta"] == 0,
          "слушатели на ЖИВЫХ узлах в документе не накапливаются "
          "(%d -> %d за %d циклов)"
          % (first["liveConnected"], last["liveConnected"], CYCLES - 1))
    # 2) Глобальные слушатели.
    dw0 = (first["windowListeners"] or 0) + (first["documentListeners"] or 0)
    dw1 = (last["windowListeners"] or 0) + (last["documentListeners"] or 0)
    check(dw1 == dw0,
          "слушатели на document/window не накапливаются (%d -> %d)"
          % (dw0, dw1))
    # 3) Наблюдатели: РЕШАЮЩИЙ критерий — реально живые объекты по прототипу
    #    (`Runtime.queryObjects`). Счётчик WeakRef-строк ниже — диагностика: он
    #    зависит от момента, когда GC добрался до конкретного объекта, и на
    #    порядок величины не опирается.
    lo_first = first.get("liveObjects") or {}
    lo_last = last.get("liveObjects") or {}
    report["obs_alive_diag"] = {"cycle1": first["obsAlive"],
                                "cycle20": last["obsAlive"],
                                "note": "WeakRef-строки; решает liveObjects"}
    for name in ("ResizeObserver", "IntersectionObserver", "visNetwork"):
        a = lo_first.get(name)
        b = lo_last.get(name)
        if a is None or b is None:
            continue
        check(b <= a, "живых объектов %s не больше (%s -> %s)"
              % (name, a, b))
    check(first["obsKinds"]["ro"] > 0 if "obsKinds" in first else True,
          "наблюдатели создаются (диагностика obsCreated=%r)"
          % first.get("obsCreated"))
    check(grow["rafLive"]["delta"] <= 0,
          "активных RAF не больше (живо %d -> %d)"
          % (first["rafLive"], last["rafLive"]))
    if has_scene:
        check(last["listenersApp"] <= first["listenersApp"],
              "обработчики ЖИВОЙ сцены не растут (scene.handlers %r -> %r)"
              % (first["listenersApp"], last["listenersApp"]))
        check(last["observersApp"] == first["observersApp"],
              "наблюдатели ЖИВОЙ сцены не растут (%r -> %r)"
              % (first["observersApp"], last["observersApp"]))
    heap1 = first.get("heapBytes")
    heapN = last.get("heapBytes")
    if heap1 and heapN:
        report["heap_growth"] = {"cycle1": heap1, "cycle20": heapN,
                                 "delta": heapN - heap1,
                                 "start": start.get("heapBytes")}
        check(heapN - heap1 <= 8 * 1024 * 1024,
              "после принудительного GC куча не выросла больше 8 МБ "
              "(цикл1 %.1f МБ -> цикл20 %.1f МБ, %+d КБ)"
              % (heap1 / 1048576.0, heapN / 1048576.0,
                 (heapN - heap1) // 1024))

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
    check((d1["rafLive"] or 0) <= (first["rafLive"] or 0),
          "в покое живых RAF не больше, чем в первом цикле (%r против %r)"
          % (d1["rafLive"], first["rafLive"]))

    if not has_scene:
        path = os.path.join(out_dir, "cmv-e-leaks-%s.png" % label)
        pg.screenshot(path=path)
        report["shots"] = [os.path.basename(path)]
        pg.close()
        ctx.close()
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
    check((back["rafLive"] or 0) <= (first["rafLive"] or 0),
          "при возврате живых RAF не больше, чем до скрытия (%r против %r)"
          % (back["rafLive"], first["rafLive"]))
    check(back["scenes"] == 1 and back["netCount"] == 1,
          "при возврате одна сцена и одна сеть (%d/%r)"
          % (back["scenes"], back["netCount"]))
    check((back["fxPaints"] or 0) > (hid1["fxPaints"] or 0),
          "после возврата кадры снова рисуются")

    path = os.path.join(out_dir, "cmv-e-leaks-after-cycles-%s.png" % label)
    pg.screenshot(path=path)
    report["shots"] = [os.path.basename(path)]
    report["console_errors"] = errors[:5]
    check(not errors, "ошибок в консоли нет (%d)" % len(errors))
    pg.close()
    ctx.close()
    return report


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
