"""EPIC-CM-VISUAL-01 — residual evidence batch 1 (evidence-only, no product changes).

Поднимает локальный стенд epic-инструментами (`ui_round1025_matrix._start_server`
+ `ui_evol_w15_composition_e2e`), раздаёт РЕАЛЬНУЮ сборку этой ветки и собирает
кадры/измерения для pending-строк карты требований, оставшихся без артефактов:

  CMV-CARD-02, CMV-CARD-03, CMV-CARD-07, CMV-CARD-08,
  CMV-FS-04, CMV-RESP-01, CMV-RESP-02, CMV-VIS-05,
  CMV-EMB-01, CMV-EMB-03, CMV-EMB-04, CMV-LBL-03.

Для каждой строки: снимки desktop 1440 / mobile 390 (или оговорённые в
требовании), отрицательный контроль (снимок состояния, где элемента нет или он
сломан), факты из DOM (rect'ы, вычисленные стили, счётчики), ошибки консоли и
число vis-network инстансов на пробу.

Запуск (из корняcanonical-репо или worktree):
  <venv python> plans/features/epic-cm-visual-01/evidence/residual/probe.py
Выход: plans/features/epic-cm-visual-01/evidence/residual/<REQ>/… + manifest.json
"""
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
OUT = HERE
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tests", "fixtures", "cmv"))

import ui_round1025_matrix as M            # noqa: E402  (os.chdir(REPO) внутри)
import ui_evol_w15_composition_e2e as W15  # noqa: E402
import cog_map_fixtures as FIX             # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

DESKTOP = (1440, 900)
MOBILE = (390, 844)

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

# ── JS-пробы ────────────────────────────────────────────────────────────────
JS_HELPERS = r"""
() => {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: +r.x.toFixed(1), y: +r.y.toFixed(1),
             w: +r.width.toFixed(1), h: +r.height.toFixed(1),
             right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1) };
  };
  const css = (el, prop) => el ? getComputedStyle(el)[prop] : null;
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden'
      && r.width > 0 && r.height > 0;
  };
  const inViewport = (r) => !!r && r.x >= -1 && r.y >= -1
    && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1;
  return { rect, css, vis, inViewport };
}
"""

JS_SCENE_FACTS = r"""
() => {
  const H = ({}); // placeholder, helpers injected via arguments
  return null;
}
"""

JS_NET_COUNTERS = r"""
() => {
  const vm = window.__adminbotVm;
  return {
    visNetworks: document.querySelectorAll('.vis-network').length,
    scenes: document.querySelectorAll('.cognition-graph').length,
    canvases: document.querySelectorAll('.cognition-graph canvas').length,
    selectedId: vm ? (vm._cogSelectedId || null) : null,
  };
}
"""

JS_SELECT = r"""
(id) => {
  const vm = window.__adminbotVm;
  if (!vm) return null;
  try { if (vm.cognitionNetwork) vm.cognitionNetwork.selectNodes([id]); }
  catch (e) { /* узел может быть скрыт LOD — выбор всё равно делается ниже */ }
  vm.graphSelectNode(id);
  vm.graphApplySelectionLabels([id]);
  return vm._cogSelectedId || null;
}
"""

JS_CLEAR = r"""
() => {
  const vm = window.__adminbotVm;
  if (vm && typeof vm.clearCogSelection === 'function') vm.clearCogSelection();
  return true;
}
"""

JS_CARD_FACTS = r"""
([titlePart]) => {
  const rect = (el) => { if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1),
             h:+r.height.toFixed(1), right:+r.right.toFixed(1),
             bottom:+r.bottom.toFixed(1) }; };
  const vm = window.__adminbotVm;
  const card = document.querySelector('#cog-card');
  if (!card) return { card: null };
  const q = (s) => card.querySelector(s);
  const metricsRows = Array.from(card.querySelectorAll('[data-cog-metric]'))
    .map((el) => ({ key: el.getAttribute('data-cog-metric'),
                    text: el.textContent.replace(/\s+/g, ' ').trim() }));
  const textEl = q('[data-cog-card-text]');
  const titleEl = q('[data-cog-card-title]');
  const closeBtn = q('[data-cog-card-close]');
  const id = card.getAttribute('data-cog-card-id') || '';
  return {
    placement: card.getAttribute('data-cog-placement'),
    cardRect: rect(card),
    titleText: titleEl ? titleEl.textContent.replace(/\s+/g, ' ').trim() : null,
    titleFullNoClip: titleEl ? titleEl.scrollWidth <= titleEl.clientWidth + 1 : null,
    textPresent: !!(textEl && !textEl.classList.contains('is-absent')),
    textClassAbsent: !!(textEl && textEl.classList.contains('is-absent')),
    textSnippet: textEl ? textEl.textContent.replace(/\s+/g, ' ').trim().slice(0, 160) : null,
    metricsRows,
    idInAttribute: id,
    idVisibleInCardText: id !== '' && titlePart !== null
      && card.textContent.indexOf(id) !== -1,
    closeBtnRect: rect(closeBtn),
    closeVisible: (() => { const r = rect(closeBtn); if (!r) return false;
      return r.x >= -1 && r.y >= -1 && r.right <= window.innerWidth + 1
        && r.bottom <= window.innerHeight + 1; })(),
    headPosition: (() => { const h = q('.cog-card__head');
      return h ? getComputedStyle(h).position : null; })(),
    cardScroll: { scrollHeight: card.scrollHeight, clientHeight: card.clientHeight,
                  overflowY: getComputedStyle(card).overflowY },
    placementValue: vm && vm.cogCardPlacement,
  };
}
"""

JS_HEADER_FACTS = r"""
() => {
  const rect = (el) => { if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1),
             h:+r.height.toFixed(1), right:+r.right.toFixed(1),
             bottom:+r.bottom.toFixed(1) }; };
  const widget = document.querySelector('[data-cog-map]');
  if (!widget) return { widget: null };
  const q = (s) => widget.querySelector(s);
  const qa = (s) => Array.from(widget.querySelectorAll(s));
  const title = q('.cog-head__row .font-bold');
  const fullBtn = q('[data-cog-open-full]');
  const input = q('.graph-search__input');
  const selects = qa('.graph-search select.field');
  const resetBtn = qa('.graph-search .btn-ghost')
    .filter((b) => (b.textContent || '').indexOf('Сбросить') !== -1)[0] || null;
  const controls = [input].concat(selects).concat(resetBtn ? [resetBtn] : [])
    .filter(Boolean).map((el) => ({ tag: el.tagName, rect: rect(el),
      minSide: Math.min(el.getBoundingClientRect().width,
                        el.getBoundingClientRect().height),
      text: (el.textContent || el.value || '').replace(/\s+/g, ' ').trim()
        .slice(0, 40) }));
  // наложения: попарные пересечения контролов
  const overlaps = [];
  for (let i = 0; i < controls.length; i += 1) {
    for (let j = i + 1; j < controls.length; j += 1) {
      const a = controls[i].rect, b = controls[j].rect;
      if (!a || !b) continue;
      const ox = Math.min(a.right, b.right) - Math.max(a.x, b.x);
      const oy = Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y);
      if (ox > 2 && oy > 2) overlaps.push([controls[i].tag + i,
                                           controls[j].tag + j,
                                           +ox.toFixed(1), +oy.toFixed(1)]);
    }
  }
  // строки: группировка по y
  const rowsMap = {};
  controls.forEach((c, i) => {
    const key = Math.round(c.rect.y / 20);
    rowsMap[key] = rowsMap[key] || [];
    rowsMap[key].push(i);
  });
  const selectClip = selects.map((s) => ({
    scrollW: s.scrollWidth, clientW: s.clientWidth,
    truncated: s.scrollWidth > s.clientWidth + 2,
    text: (s.options && s.selectedIndex >= 0)
      ? s.options[s.selectedIndex].textContent.trim() : null }));
  return {
    widgetClass: widget.className,
    cardRect: rect(widget),
    innerW: window.innerWidth,
    titleRect: rect(title), fullBtnRect: rect(fullBtn),
    inputRect: rect(input), resetText: resetBtn ? resetBtn.textContent.trim() : null,
    controls, overlaps, selectClip,
    rows: Object.keys(rowsMap).sort((a, b) => a - b)
      .map((k) => rowsMap[k].map((i) => i)),
  };
}
"""

JS_GRID_FACTS = r"""
() => {
  const card = document.querySelector('[data-cog-map]');
  if (!card) return { card: null };
  const scene = card.querySelector('.cognition-graph');
  const cr = card.getBoundingClientRect();
  const sr = scene ? scene.getBoundingClientRect() : null;
  const parent = card.parentElement;
  const siblings = parent ? Array.from(parent.children).map((el) => {
    const sg = (el.className || '').split(' ').filter((c) => c.indexOf('sg-') === 0)[0];
    return sg || (el.tagName + '.' + (el.className || '').split(' ')[0]);
  }) : [];
  const st = getComputedStyle(card);
  const scSt = scene ? getComputedStyle(scene) : null;
  return {
    present: true,
    cardClass: card.className,
    dataCogState: card.getAttribute('data-cog-state'),
    glassAttr: card.getAttribute('data-glass'),
    backdropFilter: st.backdropFilter || st.webkitBackdropFilter || null,
    positionInGrid: parent ? Array.from(parent.children).indexOf(card) : null,
    siblings,
    cardRect: { w: +cr.width.toFixed(1), h: +cr.height.toFixed(1) },
    sceneRect: sr ? { x: +sr.x.toFixed(1), y: +sr.y.toFixed(1),
                      w: +sr.width.toFixed(1), h: +sr.height.toFixed(1),
                      bottom: +sr.bottom.toFixed(1) } : null,
    gapCardBottomSceneBottom: (sr && cr) ? +(cr.bottom - sr.bottom).toFixed(1) : null,
    sceneBg: scSt ? scSt.backgroundColor : null,
    sceneBorderTop: scSt ? scSt.borderTopWidth + ' ' + scSt.borderTopStyle
      + ' ' + scSt.borderTopColor : null,
    sceneRadius: scSt ? scSt.borderRadius : null,
    scenePosition: scSt ? scSt.position : null,
  };
}
"""

JS_LAYERS_FACTS = r"""
() => {
  const vm = window.__adminbotVm;
  const scene = document.querySelector('.cognition-graph');
  if (!scene) return { scene: null };
  const canvases = Array.from(scene.querySelectorAll('canvas')).map((cv, i) => ({
    index: i, cls: cv.className, pe: getComputedStyle(cv).pointerEvents,
    z: getComputedStyle(cv).zIndex,
    rect: (() => { const r = cv.getBoundingClientRect();
      return { x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1),
               h:+r.height.toFixed(1) }; })(),
  }));
  const fx = (vm && vm._cogScene && vm._cogScene.fx
              && typeof vm._cogScene.fx.counters === 'function')
    ? vm._cogScene.fx.counters() : null;
  const pixel = (cv, fxr, fy) => {
    try {
      const ctx = cv.getContext('2d');
      const x = Math.round(cv.clientWidth * fxr), y = Math.round(cv.clientHeight * fy);
      const d = ctx.getImageData(x, y, 1, 1).data;
      return [d[0], d[1], d[2], d[3]];
    } catch (e) { return null; }
  };
  const samples = {};
  canvases.forEach((c, i) => {
    const cv = scene.querySelectorAll('canvas')[i];
    samples['canvas' + i + '_cornerTL'] = pixel(cv, 0.04, 0.06);
    samples['canvas' + i + '_center'] = pixel(cv, 0.5, 0.5);
    samples['canvas' + i + '_cornerBR'] = pixel(cv, 0.96, 0.94);
  });
  const bodyBg = getComputedStyle(document.body).backgroundColor;
  return { canvases, fxCounters: fx, samples, bodyBg,
           sceneBg: getComputedStyle(scene).backgroundColor,
           sceneBorder: getComputedStyle(scene).borderTopWidth + ' '
             + getComputedStyle(scene).borderTopStyle,
           sceneRadius: getComputedStyle(scene).borderRadius };
}
"""

JS_LABEL_FACTS = r"""
(targetId) => {
  const vm = window.__adminbotVm;
  const alloc = vm._cogLabels;
  const byId = (vm.cognitionGraphData || {}).byId || {};
  const fmt = (l) => ({ id: String(l.id), text: l.text,
    len: (l.text || '').length,
    endsEllipsis: /\u2026$/.test(l.text || '') });
  const labels = alloc && alloc.labels ? alloc.labels.map(fmt) : [];
  const forced = alloc && alloc.forced ? alloc.forced.map(fmt) : [];
  const target = String(targetId);
  const node = byId[target] || null;
  const inPlan = labels.filter((l) => l.id === target);
  const inForced = forced.filter((l) => l.id === target);
  return {
    allocKeys: alloc ? Object.keys(alloc) : [],
    labelsShown: alloc ? alloc.shown : null,
    labelForTarget: inPlan[0] || inForced[0] || null,
    forced: forced,
    dataTitle: node ? node.title : null,
    dataTitleLen: node && node.title ? node.title.length : null,
    labelsSample: labels.slice(0, 8),
  };
}
"""

JS_FS_FACTS = r"""
() => {
  const vm = window.__adminbotVm;
  const fs = document.querySelector('.status-graph-full');
  const card = document.querySelector('#cog-card');
  const de = document.scrollingElement || document.documentElement;
  const rect = (el) => { if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1),
             h:+r.height.toFixed(1), right:+r.right.toFixed(1),
             bottom:+r.bottom.toFixed(1) }; };
  const closeBtn = card ? card.querySelector('[data-cog-card-close]') : null;
  const before = closeBtn ? rect(closeBtn) : null;
  const pageTopBefore = de.scrollTop;
  let cardScroll = null;
  if (card) {
    const topBefore = card.scrollTop;
    card.scrollTop = card.scrollHeight; // прокрутить содержимое инспектора вниз
    cardScroll = { scrollHeight: card.scrollHeight,
                   clientHeight: card.clientHeight,
                   scrollTopBefore: +topBefore.toFixed(1),
                   scrollTopAfter: +card.scrollTop.toFixed(1),
                   overflowY: getComputedStyle(card).overflowY };
  }
  const after = closeBtn ? rect(closeBtn) : null;
  const inVp = (r) => !!r && r.x >= -1 && r.y >= -1
    && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1;
  return {
    fsPresent: !!fs,
    fsRect: rect(fs),
    pageScrollHeight: de.scrollHeight, pageClientHeight: de.clientHeight,
    pageScrollsAtAll: de.scrollHeight > de.clientHeight + 1,
    pageScrollTopBefore: +pageTopBefore.toFixed(1),
    pageScrollTopAfterCardScroll: +de.scrollTop.toFixed(1),
    pageMovedByCardScroll: Math.abs(de.scrollTop - pageTopBefore) > 1,
    cardScroll,
    closeBefore: before, closeAfterScroll: after,
    closeStillVisibleAfterScroll: inVp(after),
    headPosition: card && card.querySelector('.cog-card__head')
      ? getComputedStyle(card.querySelector('.cog-card__head')).position : null,
  };
}
"""

JS_VIS05_FACTS = r"""
() => {
  const rect = (el) => { if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x:+r.x.toFixed(1), y:+r.y.toFixed(1), w:+r.width.toFixed(1),
             h:+r.height.toFixed(1), right:+r.right.toFixed(1),
             bottom:+r.bottom.toFixed(1) }; };
  const widget = document.querySelector('[data-cog-map]');
  if (!widget) return { widget: null };
  const input = widget.querySelector('.graph-search__input');
  const selects = Array.from(widget.querySelectorAll('.graph-search select.field'));
  const inVp = (r) => !!r && r.x >= -1 && r.y >= -1
    && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1;
  const counters = widget.querySelector('[data-cog-counters]');
  return {
    innerW: window.innerWidth, innerH: window.innerHeight,
    inputRect: rect(input), inputVisible: inVp(rect(input)),
    selectRects: selects.map(rect), selectsVisible: selects.every((s) => inVp(rect(s))),
    countersText: counters ? counters.textContent.replace(/\s+/g, ' ').trim() : null,
    fitScale: vm_ ? null : null,
  };
}
"""
# vm_ не существует — убираем битую ссылку простым patch ниже.
JS_VIS05_FACTS = JS_VIS05_FACTS.replace("    fitScale: vm_ ? null : null,\n", "")

JS_FIT_SCALE = r"""
() => {
  const vm = window.__adminbotVm;
  return { fitScale: vm ? (vm._cogFitScale || null) : null,
           scale: vm && vm.cognitionNetwork ? vm.cognitionNetwork.getScale() : null };
}
"""

JS_EMPTY_PROBE = r"""
() => ({ ok: true })
"""


# ── фикстуры ────────────────────────────────────────────────────────────────
def rich_payload():
    """Базовый payload + узлы для CARD-02/03/07, FS-04, LBL-03.

    nameless creature (длинный текст), узел без заголовка и без текста,
    узел с очень длинным названием. Только ДАННЫЕ фикстуры, без правок кода.
    """
    p = W15.cog_payload()
    c = W15.COG_CHAT
    long_text = ("Наблюдение зафиксировано в чате: существо без имени появлялось "
                 "неоднократно, реакции противоречивые, источник сообщения не "
                 "указан. ") * 18  # ~1300 символов
    prov = {"record": "graph_facts", "chat_id": c, "message_id": 777,
            "origin": "chat_history", "fact_id": 91}

    def base_node(nid, kind, title, text, status=None, isolated=False):
        return {
            "id": nid, "kind": kind, "scope": "chat", "chat_id": c,
            "title": title, "text": text, "status": status,
            "isolated": isolated,
            "time": {"occurred_at": 1750000000, "observed_at": None,
                     "saved_at": 1750000100, "confirmed_at": None,
                     "updated_at": None},
            "provenance": dict(prov),
            "metrics": {"importance": 5, "weight": None, "degree": None},
            "refs": {},
        }

    p["nodes"].append(base_node("fact:%d:91" % c, "fact",
                                "nameless creature", long_text, "confirmed"))
    p["nodes"].append(base_node("ent:%d:92" % c, "entity", "", None))
    long_title = ("Узел с исключительно длинным названием, которое заведомо не "
                  "помещается в одну строку подписи на канве и должно "
                  "сокращаться с многоточием при отрисовке")
    p["nodes"].append(base_node("ent:%d:93" % c, "entity", long_title,
                                long_title))
    p["edges"].append({"id": "ce91", "from": "ent:%d:1" % c,
                       "to": "fact:%d:91" % c, "relation": "обсуждали",
                       "derived": False, "chat_id": c,
                       "justification_recorded": True,
                       "provenance": {"fact_id": 91}})
    p["edges"].append({"id": "ce93", "from": "ent:%d:2" % c,
                       "to": "ent:%d:93" % c, "relation": "обсуждали",
                       "derived": False, "chat_id": c,
                       "justification_recorded": True,
                       "provenance": {"fact_id": 93}})
    p["generated_at"] = int(time.time())
    return p


def base_payload():
    p = W15.cog_payload()
    p["generated_at"] = int(time.time())
    return p


def fx702_payload():
    p = FIX.load(702)
    p["generated_at"] = int(time.time())
    return p


# ── runner ──────────────────────────────────────────────────────────────────
class Run:
    def __init__(self):
        self.rows = {}
        self.console_errors = []

    def row(self, rid):
        d = os.path.join(OUT, rid)
        os.makedirs(d, exist_ok=True)
        self.rows.setdefault(rid, {"dir": rid, "shots": [], "facts": {},
                                   "console_errors": [], "errors": []})
        return self.rows[rid]

    def shot(self, pg, rid, name, selector=None, clip=None):
        rec = self.row(rid)
        path = os.path.join(OUT, rid, name + ".png")
        try:
            if selector:
                pg.locator(selector).first.screenshot(path=path)
            elif clip:
                pg.screenshot(path=path, clip=clip)
            else:
                pg.screenshot(path=path, full_page=False)
            rec["shots"].append(name + ".png")
            return path
        except Exception as e:  # noqa: BLE001
            rec["errors"].append("shot %s: %s" % (name, str(e)[:120]))
            return None

    def fact(self, rid, key, value):
        self.row(rid)["facts"][key] = value

    def err(self, rid, msg):
        self.row(rid)["errors"].append(msg[:200])

    def attach_console(self, pg, rid):
        rec = self.row(rid)

        def on_console(m):
            if m.type == "error":
                rec["console_errors"].append(m.text[:160])

        def on_pageerror(e):
            rec["console_errors"].append("pageerror: " + str(e)[:160])

        pg.on("console", on_console)
        pg.on("pageerror", on_pageerror)

    def save_manifest(self):
        manifest = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "branch": "cmv/residual-evidence",
                    "base_commit": "df00f178",
                    "rows": {}}
        for rid, rec in self.rows.items():
            files = {}
            d = os.path.join(OUT, rid)
            for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    h = hashlib.sha256(open(fp, "rb").read()).hexdigest()
                    files[fn] = h
            manifest["rows"][rid] = {
                "shots": rec["shots"], "facts": rec["facts"],
                "console_errors": rec["console_errors"],
                "errors": rec["errors"], "sha256": files}
        with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)


def settle(pg, timeout_ms=90000):
    pg.wait_for_function(READY, timeout=timeout_ms)
    pg.wait_for_timeout(400)


def open_fullscreen(pg):
    pg.click("[data-cog-open-full]")
    pg.wait_for_selector(".status-graph-full", state="visible", timeout=15000)
    settle(pg, 30000)


def close_fullscreen(pg):
    """Esc закрывает РОВНО один уровень: сперва инспектор (если открыт),
    затем полноэкранный режим. Ждём фактического закрытия."""
    for _ in range(4):
        vis = False
        try:
            loc = pg.locator(".status-graph-full")
            vis = loc.count() > 0 and loc.first.is_visible()
        except Exception:  # noqa: BLE001
            vis = False
        if not vis:
            break
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(700)
    pg.wait_for_timeout(300)


def select(pg, node_id):
    """Выбор узла + Enter на сцене: карточку открывает РЕАЛЬНЫЙ путь §9
    (программный selectNodes карточку намеренно не открывает)."""
    sel = pg.evaluate(JS_SELECT, node_id)
    try:
        pg.focus(".cognition-graph")
        pg.keyboard.press("Enter")
    except Exception as e:  # noqa: BLE001
        return sel
    pg.wait_for_timeout(600)
    return sel


def run_scenario_base_desktop(pg, run):
    """BASE-фикстура, 1440: EMB-01/03/04, CARD-08, RESP-01, LBL-03 не здесь."""
    c = W15.COG_CHAT
    run.attach_console(pg, "CMV-EMB-01")
    settle(pg)
    run.fact("CMV-EMB-01", "counters", pg.evaluate(JS_NET_COUNTERS))
    grid = pg.evaluate(JS_GRID_FACTS)
    run.fact("CMV-EMB-01", "grid", grid)
    run.shot(pg, "CMV-EMB-01", "status-grid-card-1440")

    # отрицательный контроль: карточки нет в сетке (не-admin) — отдельный ctx
    run.fact("CMV-EMB-01", "note_negative",
             "negative-non-admin-no-card-1440.png собирается отдельным контекстом")

    # EMB-03: сцена — тёмный фон/граница/радиус, без крупных декоративных полигонов
    run.attach_console(pg, "CMV-EMB-03")
    layers = pg.evaluate(JS_LAYERS_FACTS)
    run.fact("CMV-EMB-03", "scene", layers)
    run.shot(pg, "CMV-EMB-03", "scene-area-1440", selector="[data-cog-map]")

    # EMB-04: слои и pointer-events; затем выбор → выделение в fx поверх
    run.attach_console(pg, "CMV-EMB-04")
    run.fact("CMV-EMB-04", "layers_no_selection", layers)
    run.shot(pg, "CMV-EMB-04", "layers-no-selection-1440",
             selector="[data-cog-map]")
    sel = select(pg, "ent:%d:1" % c)
    pg.wait_for_timeout(700)
    run.fact("CMV-EMB-04", "selectedId", sel)
    layers_sel = pg.evaluate(JS_LAYERS_FACTS)
    run.fact("CMV-EMB-04", "layers_selection", layers_sel)
    run.shot(pg, "CMV-EMB-04", "layers-selection-1440",
             selector="[data-cog-map]")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)

    # CARD-08: инспектор встр. карты — ПОД сценой, компактная панель
    run.attach_console(pg, "CMV-CARD-08")
    run.shot(pg, "CMV-CARD-08", "negative-no-card-before-select-1440",
             selector="[data-cog-map]")
    sel = select(pg, "ent:%d:2" % c)
    pg.wait_for_timeout(700)
    run.fact("CMV-CARD-08", "selectedId", sel)
    card = pg.evaluate(JS_CARD_FACTS, [None])
    grid2 = pg.evaluate(JS_GRID_FACTS)
    run.fact("CMV-CARD-08", "card", card)
    run.fact("CMV-CARD-08", "layout", {
        "sceneRect": grid2.get("sceneRect"), "cardRect": grid2.get("cardRect")})
    run.shot(pg, "CMV-CARD-08", "inspector-under-scene-1440",
             selector="[data-cog-map]")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)

    # RESP-01: ширина карточки 1192 (>= 900) на 1440 — контролы в одной строке,
    # без наложений (широкий контраст). Случай < 900 — отдельный контекст 768.
    run.attach_console(pg, "CMV-RESP-01")
    hdr = pg.evaluate(JS_HEADER_FACTS)
    run.fact("CMV-RESP-01", "header_1440_embed_wide_contrast", hdr)
    run.shot(pg, "CMV-RESP-01", "controls-wide-1440")


def run_scenario_rich_desktop(pg, run):
    """RICH-фикстура, 1440: CARD-02/03/07, FS-04, LBL-03."""
    c = W15.COG_CHAT
    nc_id = "fact:%d:91" % c      # nameless creature, длинный текст
    no_id = "ent:%d:92" % c       # без заголовка и текста
    lt_id = "ent:%d:93" % c       # длинное название

    # LBL-03: длинная подпись на канве + полный текст в инспекторе
    run.attach_console(pg, "CMV-LBL-03")
    settle(pg)
    select(pg, lt_id)
    pg.wait_for_timeout(700)
    lbl = pg.evaluate(JS_LABEL_FACTS, lt_id)
    run.fact("CMV-LBL-03", "labels", lbl)
    card = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-LBL-03", "card_title", {
        "titleText": card.get("titleText"),
        "titleFullNoClip": card.get("titleFullNoClip"),
        "dataTitleLen": lbl.get("dataTitleLen")})
    run.shot(pg, "CMV-LBL-03", "canvas-truncated-label-1440",
             selector="[data-cog-map]")
    run.shot(pg, "CMV-LBL-03", "inspector-full-title-1440", selector="#cog-card")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)

    # FS-04: длинный текст прокручивается внутри инспектора
    run.attach_console(pg, "CMV-FS-04")
    open_fullscreen(pg)
    select(pg, nc_id)
    pg.wait_for_timeout(700)
    run.shot(pg, "CMV-FS-04", "inspector-longtext-top-1440")
    fs = pg.evaluate(JS_FS_FACTS)  # прокручивает содержимое инспектора вниз
    run.fact("CMV-FS-04", "fullscreen", fs)
    run.shot(pg, "CMV-FS-04", "inspector-longtext-scrolled-1440",
             selector="#cog-card")
    # отрицательный контроль: короткий текст — прокрутки нет
    select(pg, "ent:%d:2" % c)
    pg.wait_for_timeout(500)
    fs_short = pg.evaluate(JS_FS_FACTS)
    run.fact("CMV-FS-04", "short_text_control", {
        "cardScroll": fs_short.get("cardScroll"),
        "pageScrolls": fs_short.get("pageScrolls")})
    run.shot(pg, "CMV-FS-04", "negative-shorttext-noscroll-1440")
    close_fullscreen(pg)

    # CARD-02: показатели в карточке, ID не в краткой строке
    run.attach_console(pg, "CMV-CARD-02")
    open_fullscreen(pg)
    select(pg, nc_id)
    pg.wait_for_timeout(700)
    card = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-02", "card_fullscreen", card)
    run.shot(pg, "CMV-CARD-02", "card-metrics-1440", selector="#cog-card")
    close_fullscreen(pg)
    # отрицательный контроль: свёрнутая встраиваемая панель — секций нет
    select(pg, nc_id)
    pg.wait_for_timeout(700)
    # новая запись открывается раскрытой — свернуть кнопкой «Свернуть»
    pg.evaluate("""() => { const b = document.querySelector('[data-cog-card-expand]');
                           if (b && b.getAttribute('aria-expanded') === 'true') b.click(); }""")
    pg.wait_for_timeout(400)
    card_emb = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-02", "card_embed_collapsed", card_emb)
    run.shot(pg, "CMV-CARD-02", "negative-embed-collapsed-1440",
             selector="#cog-card")
    pg.evaluate("""() => { const b = document.querySelector('[data-cog-card-expand]');
                           if (b && b.getAttribute('aria-expanded') === 'false') b.click(); }""")
    pg.wait_for_timeout(400)
    card_exp = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-02", "card_embed_expanded", card_exp)
    run.shot(pg, "CMV-CARD-02", "embed-expanded-tech-1440", selector="#cog-card")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)

    # CARD-03: текст есть / текста нет
    run.attach_console(pg, "CMV-CARD-03")
    open_fullscreen(pg)
    select(pg, nc_id)
    pg.wait_for_timeout(700)
    card = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-03", "text_present", card)
    run.shot(pg, "CMV-CARD-03", "card-text-present-1440", selector="#cog-card")
    select(pg, no_id)
    pg.wait_for_timeout(700)
    card_abs = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-03", "text_absent", card_abs)
    run.shot(pg, "CMV-CARD-03", "card-text-absent-negative-1440",
             selector="#cog-card")

    # CARD-07: nameless creature показывает фактическое имя; без заголовка — «Без названия»
    run.attach_console(pg, "CMV-CARD-07")
    select(pg, nc_id)
    pg.wait_for_timeout(700)
    card = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-07", "nameless_creature", card)
    run.shot(pg, "CMV-CARD-07", "card-nameless-creature-1440", selector="#cog-card")
    select(pg, no_id)
    pg.wait_for_timeout(700)
    card_no = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-07", "untitled_node", card_no)
    run.shot(pg, "CMV-CARD-07", "card-untitled-negative-1440", selector="#cog-card")
    close_fullscreen(pg)


def run_scenario_fx702_desktop(pg, run):
    """FIX-702, 1440, fit: CMV-VIS-05 — поиск и фильтры полностью видимы."""
    run.attach_console(pg, "CMV-VIS-05")
    settle(pg)
    fit = pg.evaluate(JS_FIT_SCALE)
    run.fact("CMV-VIS-05", "fit", fit)
    facts = pg.evaluate(JS_VIS05_FACTS)
    run.fact("CMV-VIS-05", "visible", facts)
    run.fact("CMV-VIS-05", "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, "CMV-VIS-05", "search-filters-702fit-1440")
    # отрицательный контроль: карточка прокручена за верх вьюпорта — контролы
    # НЕ видны (проверка различает состояние)
    pg.evaluate("""() => {
      const w = document.querySelector('[data-cog-map]');
      const b = w.getBoundingClientRect();
      window.scrollTo(0, window.scrollY + b.top + 320);
    }""")
    pg.wait_for_timeout(400)
    hidden = pg.evaluate(JS_VIS05_FACTS)
    run.fact("CMV-VIS-05", "negative_scrolled_away", {
        "inputRect": hidden.get("inputRect"),
        "inputVisible": hidden.get("inputVisible"),
        "selectsVisible": hidden.get("selectsVisible")})
    run.shot(pg, "CMV-VIS-05", "negative-scrolled-away-1440")
    pg.evaluate("""() => {
      const w = document.querySelector('[data-cog-map]');
      w.scrollIntoView({ block: 'center' });
    }""")
    pg.wait_for_timeout(400)


def run_scenario_resp01_768(pg, run):
    """BASE-фикстура, 768×1024: карточка < 900 px — контролы переносятся
    на следующую строку без наложений, названия полные (CMV-RESP-01)."""
    run.attach_console(pg, "CMV-RESP-01")
    settle(pg)
    hdr = pg.evaluate(JS_HEADER_FACTS)
    run.fact("CMV-RESP-01", "header_768_card_below_900", hdr)
    run.fact("CMV-RESP-01", "counters_768", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, "CMV-RESP-01", "controls-wrapped-768", selector="[data-cog-map]")


def run_scenario_base_mobile(pg, run):
    """BASE-фикстура, 390: EMB-01/03/04, CARD-08, RESP-02."""
    c = W15.COG_CHAT
    run.attach_console(pg, "CMV-RESP-02")
    settle(pg)
    hdr = pg.evaluate(JS_HEADER_FACTS)
    run.fact("CMV-RESP-02", "header_390", hdr)
    run.fact("CMV-RESP-02", "counters", pg.evaluate(JS_NET_COUNTERS))
    run.shot(pg, "CMV-RESP-02", "header-390", selector="[data-cog-map]")

    run.attach_console(pg, "CMV-EMB-01")
    grid = pg.evaluate(JS_GRID_FACTS)
    run.fact("CMV-EMB-01", "grid_390", grid)
    run.shot(pg, "CMV-EMB-01", "status-grid-card-390")

    run.attach_console(pg, "CMV-EMB-03")
    layers = pg.evaluate(JS_LAYERS_FACTS)
    run.fact("CMV-EMB-03", "scene_390", layers)
    run.shot(pg, "CMV-EMB-03", "scene-area-390", selector="[data-cog-map]")

    run.attach_console(pg, "CMV-EMB-04")
    run.fact("CMV-EMB-04", "layers_no_selection_390", layers)
    sel = select(pg, "ent:%d:1" % c)
    pg.wait_for_timeout(700)
    run.fact("CMV-EMB-04", "selectedId_390", sel)
    layers_sel = pg.evaluate(JS_LAYERS_FACTS)
    run.fact("CMV-EMB-04", "layers_selection_390", layers_sel)
    run.shot(pg, "CMV-EMB-04", "layers-selection-390", selector="[data-cog-map]")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)

    run.attach_console(pg, "CMV-CARD-08")
    sel = select(pg, "ent:%d:2" % c)
    pg.wait_for_timeout(700)
    run.fact("CMV-CARD-08", "selectedId_390", sel)
    card = pg.evaluate(JS_CARD_FACTS, [None])
    run.fact("CMV-CARD-08", "card_390", card)
    run.shot(pg, "CMV-CARD-08", "inspector-sheet-390")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)


def run_scenario_rich_mobile(pg, run):
    """RICH-фикстура, 390: FS-04 (мобильный лист), LBL-03 (канва 390)."""
    c = W15.COG_CHAT
    nc_id = "fact:%d:91" % c
    lt_id = "ent:%d:93" % c

    run.attach_console(pg, "CMV-LBL-03")
    settle(pg)
    select(pg, lt_id)
    pg.wait_for_timeout(700)
    lbl = pg.evaluate(JS_LABEL_FACTS, lt_id)
    run.fact("CMV-LBL-03", "labels_390", lbl)
    run.shot(pg, "CMV-LBL-03", "canvas-truncated-label-390",
             selector="[data-cog-map]")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)

    run.attach_console(pg, "CMV-FS-04")
    select(pg, nc_id)
    pg.wait_for_timeout(700)
    # раскрыть лист до 80dvh
    pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      if (vm && typeof vm.toggleCogCardSheet === 'function') vm.toggleCogCardSheet();
    }""")
    pg.wait_for_timeout(500)
    fs = pg.evaluate(JS_FS_FACTS)
    run.fact("CMV-FS-04", "mobile_sheet", fs)
    run.shot(pg, "CMV-FS-04", "inspector-longtext-sheet-390")
    pg.evaluate(JS_CLEAR)
    pg.wait_for_timeout(300)


def run_non_admin_negative(browser, base, run):
    """Отрицательный контроль EMB-01: без прав администратора карточки нет."""
    rid = "CMV-EMB-01"
    run.attach_console(0, rid) if False else None
    me = dict(M.ME_JSON)
    me["role_name"] = "user"
    me["is_global_admin"] = False
    me["permissions"] = {}
    me["ui_flags"] = {}
    ctx = browser.new_context(viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                              device_scale_factor=1)
    ctx.add_init_script(M.TMA_STUB)
    ctx.route("**/api/**", W15._routes(me=me))
    pg = ctx.new_page()
    rec = run.row(rid)

    def on_console(m):
        if m.type == "error":
            rec["console_errors"].append("neg: " + m.text[:160])

    pg.on("console", on_console)
    pg.on("pageerror", lambda e: rec["console_errors"].append(
        "neg pageerror: " + str(e)[:160]))
    W15.set_cog_payload(base_payload())
    pg.goto(base + "#/", wait_until="load")
    pg.wait_for_timeout(3500)
    has_card = pg.evaluate("() => !!document.querySelector('[data-cog-map]')")
    run.fact(rid, "negative_non_admin", {"cardPresent": has_card})
    run.shot(pg, rid, "negative-non-admin-no-card-1440")
    ctx.close()


def main():
    M.PORT = 0  # случайный свободный порт — один инстанс сервера на прогон
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    run = Run()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--enable-gpu", "--enable-gpu-rasterization",
                      "--ignore-gpu-blocklist", "--use-angle=d3d11"])
            try:
                # ── desktop 1440 ────────────────────────────────────────────
                ctx = browser.new_context(
                    viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                W15.set_cog_payload(rich_payload())
                pg.goto(base + "#/", wait_until="load")
                run_scenario_rich_desktop(pg, run)
                W15.set_cog_payload(base_payload())
                pg.reload(wait_until="load")
                run_scenario_base_desktop(pg, run)
                W15.set_cog_payload(fx702_payload())
                pg.reload(wait_until="load")
                run_scenario_fx702_desktop(pg, run)
                pg.close()
                ctx.close()

                # ── планшет 768 (RESP-01: карточка < 900) ───────────────────
                ctx = browser.new_context(
                    viewport={"width": 768, "height": 1024},
                    device_scale_factor=1)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                W15.set_cog_payload(base_payload())
                pg.goto(base + "#/", wait_until="load")
                run_scenario_resp01_768(pg, run)
                pg.close()
                ctx.close()

                # ── mobile 390 ──────────────────────────────────────────────
                ctx = browser.new_context(
                    viewport={"width": MOBILE[0], "height": MOBILE[1]},
                    device_scale_factor=2, is_mobile=True, has_touch=True)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", W15._routes())
                pg = ctx.new_page()
                W15.set_cog_payload(base_payload())
                pg.goto(base + "#/", wait_until="load")
                run_scenario_base_mobile(pg, run)
                W15.set_cog_payload(rich_payload())
                pg.reload(wait_until="load")
                run_scenario_rich_mobile(pg, run)
                pg.close()
                ctx.close()

                # ── отрицательный контроль EMB-01 (не-admin) ────────────────
                run_non_admin_negative(browser, base, run)
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        for rid in run.rows:
            run.err(rid, "runner: " + traceback.format_exc()[-300:])
    finally:
        run.save_manifest()
        server.shutdown()
    print(json.dumps({rid: {"shots": len(rec["shots"]),
                            "facts": sorted(rec["facts"].keys()),
                            "console_errors": rec["console_errors"],
                            "errors": rec["errors"]}
                      for rid, rec in run.rows.items()},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
