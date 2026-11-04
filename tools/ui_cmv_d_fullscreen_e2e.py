"""CMV-D (EPIC-CM-VISUAL-01) — живой стенд fullscreen/инспектор/мобильный.

Проверяется РЕАЛЬНЫЙ интерфейс (`web/index.html` + `web/app.js` + `web/static/*`)
на детерминированной фикстуре карты (`ui_evol_w15_composition_e2e.cog_payload`),
без подмены приложения: измеряются фактические rect'ы, вычисленные стили,
состояния vue-экземпляра и камера vis-network.

Пункты спеки (`plans/current_task.md` §3, §8, §9, §11, §12.3):
  * §3.1 — панель 56–64 px с порядком «название → счётчики → поиск → фильтры →
    Сбросить вид → Закрыть»; инспектор ОТДЕЛЬНОЙ колонкой 300–360 px справа,
    сцена сужается, перекрытия нет; закрытие сохраняет выбор/фильтр/поиск;
  * §3.2 — телефон: лист 35–45 % высоты, раскрытие 75–85 %, свайп вниз
    закрывает карточку и не двигает страницу; контролы ≥44 px; полный экран
    занимает видимую высоту Mini App;
  * §8 — карточка узла: те же поля из payload, «Перейти» у соседей;
  * §9 — «перейти к соседу» переводит камеру; Esc закрывает РОВНО один уровень;
    фокус возвращается на кнопку открытия; счётчики различают БД/API/фильтр/экран;
  * §11 — пусто, ошибка API с повтором и сохранением last-known-good, смена чата
    без чужого графа;
  * §12.3 — мобильный fullscreen: доступность, отсутствие горизонтального скролла.

Запуск:
  .venv/Scripts/python.exe tools/ui_cmv_d_fullscreen_e2e.py [--out DIR]
Выход: <out>/cmv-d-fullscreen.json + PNG-кадры.
Код возврата 0 — все проверки прошли, 2 — есть отказы, 3 — стенд не поднялся.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# (ширина, высота) — опорные и обязательные §13: 1536×960, 1366×768, 768×1024,
# 390×844, 360×780.
VIEWPORTS = (
    (1536, 960),
    (1366, 768),
    (768, 1024),
    (390, 844),
    (360, 780),
)

DESKTOP_MIN = 768


PROBE = r"""
() => {
  const vm = window.__adminbotVm;
  const q = (sel) => document.querySelector(sel);
  const qa = (sel) => Array.from(document.querySelectorAll(sel));
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10,
             w: Math.round(r.width * 10) / 10,
             h: Math.round(r.height * 10) / 10,
             right: Math.round(r.right * 10) / 10,
             bottom: Math.round(r.bottom * 10) / 10 };
  };
  const css = (el, prop) => el ? getComputedStyle(el)[prop] : null;
  const bar = q('.cog-fs__bar');
  const body = q('.cog-fs__body');
  const slotFull = q('#cog-inspector-slot');
  const slotEmbed = q('#cog-embed-inspector');
  const card = q('#cog-card');
  const canvas = q('.cognition-graph canvas');
  const scene = q('.cognition-graph');
  const widget = q('[data-cog-map]');
  const titleEl = widget ? widget.querySelector('.cog-head__row .font-bold') : null;
  const fullBtn = q('[data-cog-open-full]');
  const input = (widget || document).querySelector('.graph-search__input');
  const selects = qa('.graph-search select.field');
  const resetBtn = qa('.graph-search .btn-ghost').filter(
    (b) => (b.textContent || '').indexOf('Сбросить') >= 0)[0];
  const closeBtn = q('[data-cog-close]');
  const brand = q('.cog-fs__brand');
  const counters = q('.cog-fs__bar [data-cog-counters]')
    || q('[data-cog-map] [data-cog-counters]');
  const parts = qa('[data-cog-count]').map((el) => ({
    key: el.getAttribute('data-cog-count'),
    text: (el.textContent || '').trim(),
  }));
  const hitBoxes = qa('[data-cog-map] .cog-head button, [data-cog-map] .cog-head select,'
    + ' [data-cog-map] .graph-search button, [data-cog-map] .graph-search select,'
    + ' [data-cog-map] .graph-search input, [data-cog-map] [data-cog-card-close],'
    + ' [data-cog-map] [data-cog-card-expand]')
    .map((el) => {
      const r = el.getBoundingClientRect();
      return { tag: el.tagName.toLowerCase(),
               label: (el.textContent || el.getAttribute('aria-label') || '')
                 .trim().slice(0, 24),
               w: Math.round(r.width), h: Math.round(r.height) };
    }).filter((b) => b.w > 0 && b.h > 0);
  const active = document.activeElement;
  const cardTitle = q('[data-cog-card-title]');
  const pos = {};
  try {
    const net = vm && vm.cognitionNetwork;
    if (net) {
      const p = net.getViewPosition();
      pos.x = p.x; pos.y = p.y; pos.scale = net.getScale();
    }
  } catch (e) { /* сеть уничтожена */ }
  // Пары узлов, стоящих практически в одной точке (наблюдаемый «комок»).
  let minDist = null;
  try {
    const cache = (vm && vm._cogScene && vm._cogScene.pos) || {};
    const pts = Object.keys(cache).map((k) => cache[k])
      .filter((p) => p && typeof p.x === 'number');
    for (let i = 0; i < pts.length; i += 1) {
      for (let j = i + 1; j < pts.length; j += 1) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
        if (minDist === null || d < minDist) minDist = Math.round(d * 10) / 10;
      }
    }
  } catch (e) { /* нет кэша позиций */ }
  return {
    hasVm: !!vm,
    route: String(location.hash || '#/'),
    fullscreen: !!q('.status-graph-full'),
    embedded: !!widget,
    innerW: window.innerWidth,
    hScroll: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
    bar: rect(bar),
    body: rect(body),
    scene: rect(scene),
    canvas: rect(canvas),
    slotFull: rect(slotFull),
    slotFullDisplay: css(slotFull, 'display'),
    slotEmbed: rect(slotEmbed),
    card: rect(card),
    cardPos: css(card, 'position'),
    cardPlacement: card ? card.getAttribute('data-cog-placement') : null,
    cardId: card ? card.getAttribute('data-cog-card-id') : null,
    cardKind: card ? card.getAttribute('data-cog-card') : null,
    cardDockInSlot: !!(card && slotFull && slotFull.contains(card)),
    cardEmbedInSlot: !!(card && slotEmbed && slotEmbed.contains(card)),
    headRow: rect(titleEl ? titleEl.parentElement : null),
    title: rect(titleEl),
    fullBtn: rect(fullBtn),
    input: rect(input),
    select1: rect(selects[0]),
    select2: rect(selects[1]),
    reset: rect(resetBtn),
    close: rect(closeBtn),
    brand: rect(brand),
    search: rect(q('.cog-fs__bar .graph-search')),
    countersText: counters ? (counters.textContent || '').replace(/\s+/g, ' ')
      .trim() : '',
    counterParts: parts,
    truncated: (q('[data-cog-truncated]') || {}).textContent || '',
    truncatedHint: q('[data-cog-truncated]')
      ? q('[data-cog-truncated]').getAttribute('title') : '',
    completeness: (q('[data-cog-completeness]') || {}).textContent || '',
    viewCounters: (q('[data-cog-view-counters]') || {}).textContent || '',
    state: (q('[data-cog-state]') || {}).getAttribute
      ? q('[data-cog-state]').getAttribute('data-cog-state') : null,
    stateText: (q('[data-cog-state]') || {}).textContent || '',
    loadError: (q('[data-cog-load-error]') || {}).textContent || '',
    emptyAction: qa('button').some(
      (b) => (b.textContent || '').indexOf('Открыть в Памяти') >= 0
        && !!b.offsetParent),
    retryAction: qa('button').some(
      (b) => /Повторить|Обновить/.test(b.textContent || '') && !!b.offsetParent),
    hitBoxes: hitBoxes,
    hitTooSmall: hitBoxes.filter((b) => b.h < 44 || b.w < 44),
    activeIsFullBtn: !!(active && fullBtn
      && (active === fullBtn || fullBtn.contains(active))),
    activeTag: active ? (active.tagName || '').toLowerCase() : '',
    selected: vm ? (vm._cogSelectedId || null) : null,
    cardNeighbors: qa('[data-cog-neighbor]').length,
    cardNeighborsGo: qa('[data-cog-neighbor-go]').length,
    cardTitleText: cardTitle ? (cardTitle.textContent || '').trim() : '',
    cardTitleClipped: cardTitle
      ? (cardTitle.scrollWidth - cardTitle.clientWidth > 1) : null,
    cardTitleModel: (vm && vm.cogCard && vm.cogCard.kind === 'node')
      ? (vm.cogCard.title || '') : null,
    cardActions: qa('[data-cog-map] #cog-card button, #cog-card button')
      .filter((b) => !!b.offsetParent)
      .map((b) => (b.textContent || b.getAttribute('aria-label') || '').trim()),
    nets: qa('.vis-network').length,
    scenes: qa('.cognition-graph').length,
    sceneInCard: !!(vm && vm._cogScene && vm._cogScene.el
      && q('.cog-card') && q('.cog-card').contains(vm._cogScene.el)),
    chatId: vm ? vm.activeChatId : null,
    query: vm ? vm.graphSearchQuery : null,
    sheetExpanded: card ? card.classList.contains('cog-card--expanded') : null,
    pos: pos,
    minDist: minDist,
    modelNodes: vm && vm.cognitionGraphData
      ? (vm.cognitionGraphData.nodes || []).length : 0,
    model: !!vm && !!vm.cognitionGraphData,
    net: !!vm && !!vm.cognitionNetwork,
    sceneLod: vm && vm._cogScene ? vm._cogScene.lod : null,
    simple: vm ? vm.isMobileShell === true : null,
  };
}
"""


def _route_error(pg):
    """Отказ API карты: последующие запросы падают, прежний кадр не стирается."""
    pg.route("**/api/memory/cognitive-map*",
             lambda route: route.fulfill(status=500, content_type="application/json",
                                         body=json.dumps({"detail": "stand: fail"})))


def _route_ok(pg):
    try:
        pg.unroute("**/api/memory/cognitive-map*")
    except Exception:  # noqa: BLE001
        pass


def touch_swipe(pg, selector, dy, steps=6, y_frac=0.5, dx=0):
    """Настоящий touch-жест по элементу (Chromium TouchEvent, не «JS-вызов»)."""
    pg.evaluate("""([sel, dy, steps, yFrac, dx]) => {
      const host = document.querySelector(sel);
      if (!host) return false;
      // Жест идёт по ХОЛСТУ сцены (vis слушает касания на canvas), но
      // координаты берём от контейнера — холст лежит внутри него.
      const el = host.tagName === 'CANVAS' ? host : (host.querySelector('canvas') || host);
      const r = host.getBoundingClientRect();
      const x = r.left + r.width / 2;
      const y0 = r.top + r.height * yFrac;
      const mk = (type, x2, y) => {
        const t = new Touch({ identifier: 1, target: el, clientX: x2, clientY: y });
        const ev = new TouchEvent(type, { bubbles: true, cancelable: true,
                                         touches: type === 'touchend' ? [] : [t],
                                         targetTouches: [t], changedTouches: [t] });
        el.dispatchEvent(ev);
      };
      mk('touchstart', x, y0);
      for (let i = 1; i <= steps; i += 1) {
        mk('touchmove', x + (dx * i) / steps, y0 + (dy * i) / steps);
      }
      mk('touchend', x + dx, y0 + dy);
      return true;
    }""", [selector, dy, steps, y_frac, dx])


def select_node(pg, node_id):
    """Выбор узла ТЕМ ЖЕ путём, что поиск/переход: `graphSelectNode`.

    Возвращает id, который приложение реально считает выбранным.
    """
    return pg.evaluate("""(id) => {
      const vm = window.__adminbotVm;
      if (!vm) return null;
      try { if (vm.cognitionNetwork) vm.cognitionNetwork.selectNodes([id]); }
      catch (e) { /* узел скрыт LOD — выбор всё равно делается ниже */ }
      vm.graphSelectNode(id);
      vm.graphApplySelectionLabels([id]);
      return vm._cogSelectedId || null;
    }""", node_id)


def open_card_by_keyboard(pg):
    """Enter на сцене открывает карточку ВЫБРАННОГО узла (спека §9)."""
    pg.focus(".cognition-graph")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(500)


def pinch(pg, selector, start_gap=90, end_gap=220, y_frac=0.18):
    """Настоящий двухпальцевый пинч через CDP (Input.dispatchTouchEvent)."""
    box = pg.locator(selector).first.bounding_box()
    if not box:
        return None
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] * y_frac
    cdp = pg.context.new_cdp_session(pg)

    def pts(gap):
        return [{"x": cx - gap / 2, "y": cy, "id": 1},
                {"x": cx + gap / 2, "y": cy, "id": 2}]

    cdp.send("Input.dispatchTouchEvent",
             {"type": "touchStart", "touchPoints": pts(start_gap)})
    steps = 6
    for i in range(1, steps + 1):
        gap = start_gap + (end_gap - start_gap) * i / steps
        cdp.send("Input.dispatchTouchEvent",
                 {"type": "touchMove", "touchPoints": pts(gap)})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()


def touch_pan(pg, selector, dx=140, y_frac=0.15, x_frac=0.15, steps=8):
    """Панорама одним пальцем через CDP: реальный ввод, а не синтетика."""
    box = pg.locator(selector).first.bounding_box()
    if not box:
        return None
    x0 = box["x"] + box["width"] * x_frac
    y0 = box["y"] + box["height"] * y_frac
    cdp = pg.context.new_cdp_session(pg)

    def at(dx_now):
        return [{"x": x0 + dx_now, "y": y0, "id": 1}]

    cdp.send("Input.dispatchTouchEvent",
             {"type": "touchStart", "touchPoints": at(0)})
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent",
                 {"type": "touchMove", "touchPoints": at(dx * i / steps)})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()


def run(browser, base, out_dir):
    W15 = sys.modules["ui_evol_w15_composition_e2e"]
    W15.set_cog_payload(W15.cog_payload())
    checks = []

    def ok(cond, name, detail=None):
        checks.append({"name": name, "ok": bool(cond),
                       "detail": None if cond else detail})
        return bool(cond)

    def shot(pg, name, selector=None):
        path = os.path.join(out_dir, name + ".png")
        try:
            if selector:
                pg.locator(selector).first.screenshot(path=path)
            else:
                pg.screenshot(path=path, full_page=False)
            return name + ".png"
        except Exception:  # noqa: BLE001
            return None

    shots = []
    per_vp = {}
    for (w, h) in VIEWPORTS:
        label = "%dx%d" % (w, h)
        ctx = W15._ctx(browser, w, h)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
        pg.on("console", lambda m: errs.append("console: " + m.text[:160])
              if m.type == "error" else None)
        W15.set_cog_payload(W15.cog_payload())
        pg.goto(base + "?cog=d-%d#/" % w, wait_until="load")
        pg.wait_for_selector("[data-cog-map]", timeout=30000)
        pg.wait_for_selector("[data-cog-map] canvas", timeout=30000)
        pg.wait_for_timeout(2600)
        emb = pg.evaluate(PROBE)

        # ── §2.1 CMV-EMB-02: высота области графа ──────────────────────────
        min_scene = 400 if w >= DESKTOP_MIN else 340
        ok(emb["scene"] and emb["scene"]["h"] >= min_scene,
           "сцена встроенной карты >= %d px @%s" % (min_scene, label),
           emb["scene"])
        ok(emb["hScroll"] <= 1, "нет горизонтального скролла @%s" % label,
           emb["hScroll"])

        # ── §2.2/§9.9: счётчики различают величины ─────────────────────────
        keys = [p["key"] for p in emb["counterParts"]]
        ok("api" in keys, "счётчики: «из API» отмечено отдельно @%s" % label, keys)
        api_part = [p["text"] for p in emb["counterParts"] if p["key"] == "api"]
        ok(api_part and "11 узлов" in api_part[0],
           "счётчики: реальное число из API @%s" % label, api_part)
        ok("в базе" in emb["countersText"],
           "счётчики: «в базе» показано, когда сервер его прислал @%s" % label,
           emb["countersText"])
        ok(bool(emb["truncated"]),
           "усечённый ответ помечен «Показана часть графа» @%s" % label,
           emb["truncated"])
        ok("сервер не отдал" in (emb["truncatedHint"] or ""),
           "усечение объяснено по hover @%s" % label, emb["truncatedHint"])
        # ── §2.2 строка 4 (CMV-HDR-04): подсказка жестов ─────────────────────
        hint = pg.evaluate("""() => {
          const el = document.querySelector('[data-cog-hint]');
          const scene = document.querySelector('[data-cog-scene]');
          return { shown: !!el, text: el ? el.textContent.trim() : '',
                   label: scene ? scene.getAttribute('aria-label') : null,
                   title: scene ? scene.getAttribute('title') : null };
        }""")
        ok(hint["shown"] and "Колесо/щипок" in hint["text"]
           and "Перетаскивание" in hint["text"] and "Нажатие" in hint["text"],
           "шапка: подсказка жестов показана при входе @%s" % label, hint["text"])
        ok(hint["title"] and "Колесо/щипок" in hint["title"]
           and hint["label"] and "перетаскивание — перемещение" in hint["label"],
           "подсказка жестов остаётся доступной подсказкой сцены @%s" % label,
           {"title": hint["title"], "label": hint["label"]})

        if w <= 430:
            # ── §2.3 CMV-RESP-02: строки шапки на 390/360 ──────────────────
            ok(emb["title"] and emb["fullBtn"]
               and abs(emb["title"]["y"] - emb["fullBtn"]["y"]) < 26
               and emb["fullBtn"]["right"] <= emb["innerW"] + 1,
               "390/360: заголовок и «Полный экран» в первой строке @%s" % label,
               {"title": emb["title"], "full": emb["fullBtn"]})
            ok(emb["input"] and emb["title"]
               and emb["input"]["y"] >= emb["title"]["y"] + 20,
               "390/360: поиск ниже первой строки @%s" % label,
               {"input": emb["input"], "title": emb["title"]})
            ok(emb["select1"] and emb["input"]
               and emb["select1"]["y"] >= emb["input"]["y"] + 10,
               "390/360: фильтр ниже поиска @%s" % label,
               {"sel": emb["select1"], "input": emb["input"]})
            ok(len(emb["hitBoxes"]) >= 6 and not emb["hitTooSmall"],
               "390/360: все тач-цели >= 44 px (измерено %d) @%s"
               % (len(emb["hitBoxes"]), label),
               emb["hitTooSmall"][:6])
            # ── §12.3 CMV-VIS-12: клавиатура в поиске не обрывает сессию ───
            pg.click("[data-cog-map] .graph-search__input")
            pg.keyboard.type("Audit")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(700)
            typed = pg.evaluate(PROBE)
            ok(typed["route"] == emb["route"] and typed["chatId"] == emb["chatId"]
               and typed["model"] and typed["hScroll"] == 0,
               "телефон: поиск с клавиатуры не меняет чат и не рвёт сессию @%s"
               % label,
               {"route": typed["route"], "chat": typed["chatId"],
                "model": typed["model"], "hScroll": typed["hScroll"]})
            pg.fill("[data-cog-map] .graph-search__input", "")
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)

        # ── §9: соседи в карточке кликабельны, «Перейти» есть ──────────────
        # Выбор — тот же путь, что у поиска/перехода, а открытие карточки —
        # клавиатурой (Enter на сцене): так проверяется и §9 CMV-NAV-06.
        picked = select_node(pg, "fact:%d:11" % W15.COG_CHAT)
        open_card_by_keyboard(pg)
        card = pg.evaluate(PROBE)
        ok(picked == "fact:%d:11" % W15.COG_CHAT,
           "выбор узла ставит его выбранным @%s" % label, picked)
        ok(card["cardKind"] == "node" and card["cardId"],
           "карточка узла открылась @%s" % label, card["cardKind"])
        ok(bool(card["cardTitleText"])
           and card["cardTitleText"] == (card["cardTitleModel"] or "").strip()
           and card["cardTitleClipped"] is False,
           "инспектор: подпись выбранного объекта видна полностью @%s" % label,
           {"shown": card["cardTitleText"], "model": card["cardTitleModel"],
            "clipped": card["cardTitleClipped"]})
        ok(card["nets"] == 1 and card["scenes"] == 1,
           "один логический граф: одна сцена и одна сеть @%s" % label,
           {"nets": card["nets"], "scenes": card["scenes"]})
        ok(any("Памяти" in a for a in card["cardActions"]),
           "инспектор: действие «Открыть в Памяти» на месте @%s" % label,
           card["cardActions"])
        ok(any("Снять выбор" in a for a in card["cardActions"]),
           "инспектор: действие «Снять выбор» доступно @%s" % label,
           card["cardActions"])
        after_hint = pg.evaluate(
            "() => !document.querySelector('[data-cog-hint]')")
        ok(after_hint,
           "подсказка жестов ушла после первого действия (не висит плашкой) @%s"
           % label, None)
        pg.click('[data-cog-action="clear"]')
        pg.wait_for_timeout(500)
        cleared = pg.evaluate(PROBE)
        ok(not cleared["card"] and not cleared["selected"],
           "«Снять выбор» закрывает карточку и снимает выбор @%s" % label,
           {"card": cleared["cardKind"], "sel": cleared["selected"]})
        ok(card["cardNeighbors"] > 0 and card["cardNeighborsGo"] == card["cardNeighbors"],
           "у каждого соседа есть «Перейти» @%s" % label,
           {"nb": card["cardNeighbors"], "go": card["cardNeighborsGo"]})
        if w >= DESKTOP_MIN:
            ok(card["cardEmbedInSlot"] and card["cardPos"] == "static",
               "desktop: инспектор встроенной карты — панель под сценой @%s" % label,
               {"inSlot": card["cardEmbedInSlot"], "pos": card["cardPos"]})
            ok(card["card"]["y"] >= card["scene"]["bottom"] - 2,
               "desktop: панель не перекрывает сцену @%s" % label,
               {"card": card["card"], "scene": card["scene"]})

        if w <= 430:
            # CMV-CARD-08: во ВСТРОЕННОЙ карте инспектор — панель под сценой
            # (не «плавающая» карточка поверх узлов) и на телефоне тоже.
            ok(card["cardPos"] == "static" and card["cardEmbedInSlot"],
               "телефон: панель инспектора под сценой @%s" % label,
               {"pos": card["cardPos"], "inSlot": card["cardEmbedInSlot"]})
            ok(card["card"]["y"] >= card["scene"]["bottom"] - 2,
               "телефон: панель не перекрывает сцену @%s" % label,
               {"card": card["card"], "scene": card["scene"]})

        # ── §9 CMV-NAV-05: «Перейти» переводит камеру и выбор ──────────────
        select_node(pg, "fact:%d:11" % W15.COG_CHAT)
        open_card_by_keyboard(pg)
        pg.wait_for_timeout(300)
        before = pg.evaluate(PROBE)
        nb = pg.evaluate("() => { const b = document.querySelector"
                         "('[data-cog-neighbor-go]'); return b ?"
                         " b.getAttribute('data-cog-neighbor-go') : null; }")
        if nb:
            pg.evaluate("() => document.querySelector"
                        "('[data-cog-neighbor-go]').click()")
            pg.wait_for_timeout(1400)
            after = pg.evaluate(PROBE)
            ok(after["selected"] == nb,
               "«Перейти» выбирает соседа @%s" % label,
               {"want": nb, "got": after["selected"]})
            ok(after["cardId"] == nb,
               "«Перейти» обновляет карточку на соседа @%s" % label,
               {"want": nb, "got": after["cardId"]})
            moved = (before["pos"] and after["pos"]
                     and (abs(before["pos"]["x"] - after["pos"]["x"]) > 0.5
                          or abs(before["pos"]["y"] - after["pos"]["y"]) > 0.5
                          or abs(before["pos"]["scale"] - after["pos"]["scale"])
                          > 0.001))
            ok(bool(moved), "«Перейти» переводит камеру @%s" % label,
               {"before": before["pos"], "after": after["pos"]})
        else:
            ok(False, "«Перейти» отсутствует @%s" % label)

        # ── §3.1: полный экран — панель, колонка инспектора, Esc-уровни ────
        pg.evaluate("() => window.__adminbotVm.openGraphFull()")
        pg.wait_for_timeout(2200)
        full = pg.evaluate(PROBE)
        ok(full["fullscreen"], "полный экран открылся @%s" % label, full["route"])
        ok(full["canvas"] and full["canvas"]["h"] >= (200 if w >= DESKTOP_MIN else 160),
           "полный экран: сцена видна @%s" % label, full["canvas"])
        # Кадры приёмки — СРАЗУ после открытия полного экрана (до жестов и
        # свайпов), иначе на снимке был бы уже увеличенный/сдвинутый кадр.
        if w < DESKTOP_MIN:
            shots.append(shot(pg, "cmv-d-mobile-sheet-%d" % w,
                              ".status-graph-full"))
        if w == 390:
            shots.append(shot(pg, "cmv-d-fullscreen-390",
                              ".status-graph-full"))
        ok(full["nets"] == 1 and full["scenes"] == 1 and full["card"] and
           full["scenes"] == 1,
           "полный экран: та же ОДНА сцена и сеть, второго графа нет @%s" % label,
           {"nets": full["nets"], "scenes": full["scenes"], "card": bool(full["card"])})
        if w >= 1280:
            ok(full["bar"] and 54 <= full["bar"]["h"] <= 64,
               "панель 56–64 px @%s" % label, full["bar"])
        if w >= 1100:
            # Порядок §3.1 проверяется там, где панель действительно одна строка.
            order = [full["brand"], full["input"], full["reset"], full["close"]]
            good = all(order[i] and order[i + 1]
                       and order[i]["x"] < order[i + 1]["x"] for i in range(3))
            ok(good, "порядок панели: название → поиск → сброс → закрыть @%s"
               % label, [o and o["x"] for o in order])
        if w >= DESKTOP_MIN:
            controls = [full["brand"], full["search"], full["reset"],
                        full["close"], full["input"], full["select1"],
                        full["select2"]]
            ok(all(o and o["right"] <= full["innerW"] + 1 for o in controls),
               "панель не выходит за экран (нет обрезки кнопок) @%s" % label,
               [o and o["right"] for o in controls])
        if w >= DESKTOP_MIN:
            slot = full["slotFull"]
            ok(slot and full["canvas"]
               and slot["w"] >= 300 - 1 and slot["w"] <= 360 + 1,
               "инспектор — колонка 300–360 px @%s" % label, slot)
            ok(full["cardDockInSlot"] and full["cardPos"] == "static",
               "полный экран: карточка В колонке, а не поверх сцены @%s" % label,
               {"inSlot": full["cardDockInSlot"], "pos": full["cardPos"]})
            ok(full["canvas"] and slot
               and full["canvas"]["right"] <= slot["x"] + 1,
               "инспектор не перекрывает сцену @%s" % label,
               {"canvas": full["canvas"], "slot": slot})
            ok(full["body"]["w"] >= full["canvas"]["w"] + slot["w"] - 2,
               "сцена сужена под колонку @%s" % label,
               {"body": full["body"], "canvas": full["canvas"], "slot": slot})
        else:
            # ── §3.2 CMV-FSM-04 / §12.3: пинч и панорама РЕАЛЬНЫМИ касаниями ─
            # Жесты — по ВИДИМОЙ полосе сцены над листом (сам лист перекрывает
            # нижнюю часть холста): иначе касания попадали бы в карточку.
            before_g = pg.evaluate(PROBE)["pos"]
            pinch(pg, ".status-graph-full .cognition-graph")
            pg.wait_for_timeout(600)
            after_g = pg.evaluate(PROBE)["pos"]
            ok(before_g and after_g
               and abs(after_g["scale"] - before_g["scale"]) > 0.02,
               "телефон: пинч двумя пальцами меняет масштаб @%s" % label,
               {"before": before_g, "after": after_g})
            panned = None
            base_pos = None
            for (now_x, now_y) in ((0.15, 0.15), (0.5, 0.1), (0.15, 0.6)):
                base_pos = pg.evaluate(PROBE)["pos"]
                touch_pan(pg, ".status-graph-full .cognition-graph",
                          dx=140, x_frac=now_x, y_frac=now_y)
                pg.wait_for_timeout(450)
                panned = pg.evaluate(PROBE)
                if (panned["pos"] and base_pos
                        and (abs(panned["pos"]["x"] - base_pos["x"]) > 0.5
                             or abs(panned["pos"]["y"] - base_pos["y"]) > 0.5)):
                    break
            ok(bool(panned and panned["pos"] and base_pos
                    and (abs(panned["pos"]["x"] - base_pos["x"]) > 0.5
                         or abs(panned["pos"]["y"] - base_pos["y"]) > 0.5)),
               "телефон: панорама одним пальцем по пустому полю @%s" % label,
               {"before": base_pos, "after": panned and panned["pos"]})
            ok(panned and panned["hScroll"] == 0,
               "телефон: жесты не создают горизонтальный скролл @%s" % label,
               panned and panned["hScroll"])
            # ── §3.2 CMV-FSM-03: лист 35–45 % → раскрытие 75–85 % → свайп вниз
            ok(full["cardPos"] == "fixed",
               "телефон в полном экране: инспектор — нижний лист @%s" % label,
               full["cardPos"])
            ratio = (full["card"]["h"] or 0) / h
            ok(0.34 <= ratio <= 0.46,
               "телефон: лист стартует на 35–45 %% высоты @%s" % label,
               round(ratio, 3))
            # §3.2: лист — нижняя карточка, граф остаётся ВИДИМЫМ сверху.
            # Холст уходит под лист (это нормально для нижнего листа), поэтому
            # проверяется реальная видимая полоса, а не «холст целиком выше».
            strip = (full["card"]["y"] - full["canvas"]["y"]
                     if full["canvas"] and full["card"] else 0)
            ok(strip >= 120,
               "телефон: над листом видна полоса графа (%.0f px) @%s"
               % (strip, label),
               {"canvas": full["canvas"], "card": full["card"]})
            # Полоса не должна быть пустой: в ней обязаны быть РЕАЛЬНЫЕ узлы
            # (координаты считаются по камере vis, а не «на глаз»). Порог — 1:
            # камера к этому моменту может быть уже сфокусирована на соседе
            # («Перейти»), и в полосе честно остаётся только его окрестность.
            in_strip = pg.evaluate("""() => {
              const vm = window.__adminbotVm;
              const net = vm && vm.cognitionNetwork;
              const scene = document.querySelector('.status-graph-full .cognition-graph');
              const card = document.querySelector('#cog-card');
              if (!net || !scene || !card) return -1;
              const r = scene.getBoundingClientRect();
              const c = card.getBoundingClientRect();
              const pos = net.getPositions();
              const view = net.getViewPosition();
              const scale = net.getScale();
              let n = 0;
              for (const id of Object.keys(pos)) {
                const sx = (pos[id].x - view.x) * scale + r.width / 2 + r.left;
                const sy = (pos[id].y - view.y) * scale + r.height / 2 + r.top;
                if (sx > r.left && sx < r.right && sy > r.top && sy < c.top) n += 1;
              }
              return n;
            }""")
            ok(in_strip >= 1,
               "телефон: над листом видны реальные узлы (%s) @%s"
               % (in_strip, label), in_strip)
            touch_swipe(pg, "[data-cog-sheet-grip]", -160)
            pg.wait_for_timeout(400)
            exp = pg.evaluate(PROBE)
            ok(exp["sheetExpanded"] is True
               and 0.74 <= ((exp["card"] or {}).get("h") or 0) / h <= 0.86,
               "телефон: свайп вверх раскрывает лист до 75–85 %% @%s" % label,
               {"expanded": exp["sheetExpanded"],
                "ratio": round(((exp["card"] or {}).get("h") or 0) / h, 3)})
            touch_swipe(pg, "[data-cog-sheet-grip]", 200)
            pg.wait_for_timeout(400)
            down = pg.evaluate(PROBE)
            ok(down["sheetExpanded"] is False and down["cardKind"] == "node",
               "телефон: свайп вниз сворачивает раскрытый лист @%s" % label,
               {"expanded": down["sheetExpanded"]})
            touch_swipe(pg, "[data-cog-sheet-grip]", 220)
            pg.wait_for_timeout(500)
            closed = pg.evaluate(PROBE)
            ok(not closed["card"],
               "телефон: свайп вниз закрывает свёрнутый лист @%s" % label,
               closed["cardKind"])
            # вернуть карточку: следующие проверки ждут открытый инспектор
            select_node(pg, "fact:%d:11" % W15.COG_CHAT)
            open_card_by_keyboard(pg)
            pg.wait_for_timeout(300)
        if w >= DESKTOP_MIN:
            # Кадр приёмки (см. §12.1): камера обзора + открытый инспектор.
            # «Сбросить вид» карточку закрывает (сброс = снятие выбора), поэтому
            # узел выбирается заново тем же путём, что поиск, и карточка
            # открывается клавиатурой — ровно как это делает пользователь.
            pg.click("text=Сбросить вид")
            pg.wait_for_timeout(900)
            reset = pg.evaluate(PROBE)
            ok(not reset["card"] and not reset["selected"],
               "«Сбросить вид» снимает выбор и закрывает карточку @%s" % label,
               {"card": reset["cardKind"], "sel": reset["selected"]})
            select_node(pg, "fact:%d:11" % W15.COG_CHAT)
            open_card_by_keyboard(pg)
            pg.wait_for_timeout(400)
            overview = pg.evaluate(PROBE)
            ok(overview["card"] and overview["canvas"]
               and overview["canvas"]["right"] <= overview["slotFull"]["x"] + 1,
               "обзор + инспектор: сцена не перекрыта @%s" % label,
               {"canvas": overview["canvas"], "slot": overview["slotFull"]})
        if w == 1536:
            shots.append(shot(pg, "cmv-d-fullscreen-inspector-1536",
                              ".status-graph-full"))
        if w == 1366:
            shots.append(shot(pg, "cmv-d-fullscreen-1366", ".status-graph-full"))

        # Esc #1 — закрывает ТОЛЬКО карточку, полный экран остаётся.
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(700)
        esc1 = pg.evaluate(PROBE)
        ok(esc1["fullscreen"] and not esc1["card"],
           "Esc №1 закрывает только инспектор @%s" % label,
           {"full": esc1["fullscreen"], "card": esc1["cardKind"]})
        ok((esc1["slotFull"] is None)
           or (w >= DESKTOP_MIN and esc1["slotFullDisplay"] == "none")
           or (w < DESKTOP_MIN and esc1["slotFull"]["h"] <= 1),
           "пустая колонка не занимает места @%s" % label,
           {"slot": esc1["slotFull"], "display": esc1["slotFullDisplay"]})
        ok(bool(esc1["selected"]),
           "закрытие инспектора сохраняет выбор @%s" % label, esc1["selected"])

        # Esc #2 — закрывает полный экран и возвращает фокус на кнопку.
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(1600)
        esc2 = pg.evaluate(PROBE)
        ok(not esc2["fullscreen"] and esc2["embedded"],
           "Esc №2 закрывает только полный экран @%s" % label, esc2["route"])
        ok(esc2["selected"] == esc1["selected"],
           "выход сохраняет выбранный узел @%s" % label,
           {"before": esc1["selected"], "after": esc2["selected"]})
        ok(esc2["activeIsFullBtn"],
           "фокус вернулся на кнопку «Полный экран» @%s" % label,
           esc2["activeTag"])

        per_vp[label] = {
            "embedded": emb, "card": card, "full": full,
            "esc1": esc1, "esc2": esc2, "errors": errs[:4],
        }
        ok(not errs, "консоль без ошибок @%s" % label, errs[:2])
        ctx.close()

    # ── §9 CMV-NAV-07 + §11: фильтр/счётчики/смена чата/ошибка/пусто ──────
    ctx = W15._ctx(browser, 1280, 900)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    W15.set_cog_payload(W15.cog_payload())
    pg.goto(base + "?cog=d-states#/", wait_until="load")
    pg.wait_for_selector("[data-cog-map] canvas", timeout=30000)
    pg.wait_for_timeout(2400)

    # фильтр: числа «в фильтре/на экране» отличаются от «из API»
    pg.select_option('[data-cog-map] select[aria-label="Фильтр по типу узла"]', "fact")
    pg.wait_for_timeout(900)
    filt = pg.evaluate(PROBE)
    ok("видно" in filt["viewCounters"] or "на экране"
       in [p["key"] for p in filt["counterParts"]],
       "фильтр: видимый набор показан отдельной величиной", filt["viewCounters"])
    shots.append(shot(pg, "cmv-d-counters-filter-1280", "[data-cog-map]"))
    pg.select_option('[data-cog-map] select[aria-label="Фильтр по типу узла"]', "")
    pg.wait_for_timeout(700)

    # ── смена чата: чужой граф не остаётся ни кадра ────────────────────────
    # Ответ для НОВОГО чата искусственно задерживается, иначе стенд не отличил
    # бы «мгновенно перезагрузили» от «показали чужой чат».
    other = W15.cog_payload()
    other["scope"] = {"mode": "chat", "chat_id": -1009999999999}

    def _slow(route):
        import time as _t
        _t.sleep(0.9)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(other))

    pg.route("**/api/memory/cognitive-map*", _slow)
    switch = pg.evaluate("""() => new Promise((resolve) => {
      const vm = window.__adminbotVm;
      const before = vm.cognitionGraphData ? vm.cognitionGraphData.nodes.length : 0;
      vm.activeChatId = -1009999999999;
      setTimeout(() => {
        resolve({ before: before,
                  after: !!vm.cognitionGraphData,
                  state: vm.cogStatus.kind,
                  canvas: document.querySelectorAll('.cognition-graph canvas').length,
                  counters: (document.querySelector('[data-cog-counters]') || {})
                    .textContent || '' });
      }, 250);
    })""")
    ok(switch["after"] is False,
       "смена чата: модель прежнего чата сброшена сразу", switch)
    ok(switch["canvas"] == 0,
       "смена чата: прежний граф исчез с экрана, пока грузится новый", switch)
    pg.wait_for_timeout(1600)
    loaded = pg.evaluate(PROBE)
    ok(loaded["model"] and loaded["net"],
       "смена чата: карта нового чата загрузилась", loaded["model"])
    _route_ok(pg)

    # ошибка API: сообщение + повтор, исправный граф не стирается
    W15.set_cog_payload(W15.cog_payload())
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    pg.wait_for_timeout(1200)
    good = pg.evaluate(PROBE)
    ok(good["model"] and good["net"], "повторная загрузка вернула граф", good["model"])
    _route_error(pg)
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    pg.wait_for_timeout(1500)
    failed = pg.evaluate(PROBE)
    ok(bool(failed["loadError"]), "ошибка API названа в интерфейсе",
       failed["loadError"])
    ok(failed["retryAction"], "у ошибки есть действие «Повторить»", None)
    ok(failed["net"] and failed["model"],
       "ошибка API не стирает исправный last-known-good граф",
       {"net": failed["net"], "model": failed["model"]})
    shots.append(shot(pg, "cmv-d-state-error-1280", "[data-cog-map]"))
    _route_ok(pg)
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    pg.wait_for_timeout(1500)
    healed = pg.evaluate(PROBE)
    ok(not healed["loadError"], "после успешного повтора ошибка снята",
       healed["loadError"])

    # пусто: честное состояние + переход в «Память»
    W15.set_cog_payload(W15.cog_payload(state="empty", with_nodes=False))
    pg.evaluate("() => window.__adminbotVm.loadCognitionGraph()")
    pg.wait_for_timeout(1500)
    empty = pg.evaluate(PROBE)
    ok(empty["state"] == "empty", "пустой ответ — состояние empty", empty["state"])
    ok("пусто" in (empty["stateText"] or "").lower()
       or bool(empty["stateText"]),
       "пустое состояние объяснено словами", empty["stateText"])
    ok(empty["emptyAction"], "пустое состояние ведёт в «Память»", None)
    shots.append(shot(pg, "cmv-d-state-empty-1280", "[data-cog-map]"))
    ok(not errs, "состояния: консоль без ошибок", errs[:2])
    ctx.close()

    # ── §11: мобильный `simple` — раскладка без «комка» ───────────────────
    ctx = W15._ctx(browser, 390, 844)
    pg = ctx.new_page()
    W15.set_cog_payload(W15.cog_payload())
    pg.goto(base + "?cog=d-clump#/", wait_until="load")
    pg.wait_for_selector("[data-cog-map] canvas", timeout=30000)
    pg.wait_for_timeout(2400)
    mobile_first = pg.evaluate(PROBE)
    ok(mobile_first["simple"] is True,
       "телефон: сцена в упрощённом режиме", mobile_first["simple"])
    # фильтр → часть узлов исчезает, затем возвращаются (путь `_cogApplyData`).
    pg.select_option('[data-cog-map] select[aria-label="Фильтр по типу узла"]', "fact")
    pg.wait_for_timeout(900)
    pg.select_option('[data-cog-map] select[aria-label="Фильтр по типу узла"]', "")
    pg.wait_for_timeout(1200)
    clump = pg.evaluate(PROBE)
    ok(clump["minDist"] is None or clump["minDist"] > 12,
       "после возврата фильтра узлы не сходятся в одну точку (был «комок»)",
       {"minDist": clump["minDist"]})
    # прямой вызов раскладки: совпадающие соседи не дают одинаковых центров
    spread = pg.evaluate("""() => {
      const vm = window.__adminbotVm;
      const out = [];
      let i = 0;
      const nodes = (vm._cogView && vm._cogView.nodes) || [];
      const positions = {};
      for (const n of nodes) {
        const p = vm._cogFallbackPosition(n, positions);
        positions[n.id] = p;
        out.push([Math.round(p.x), Math.round(p.y)]);
      }
      let min = null;
      for (i = 0; i < out.length; i += 1) {
        for (let j = i + 1; j < out.length; j += 1) {
          const d = Math.hypot(out[i][0] - out[j][0], out[i][1] - out[j][1]);
          if (min === null || d < min) min = d;
        }
      }
      return { count: out.length, min: min === null ? null : Math.round(min) };
    }""")
    ok(spread["count"] > 2 and (spread["min"] or 0) >= 30,
       "раскладка заглушек: минимальная дистанция вместо «+22/+22»", spread)
    shots.append(shot(pg, "cmv-d-embedded-390", "[data-cog-map]"))
    ctx.close()

    return {"checks": checks, "screenshots": [s for s in shots if s],
            "viewports": per_vp}


def evaluate(record):
    fails = [c["name"] + (" :: " + json.dumps(c["detail"], ensure_ascii=False)
                          if c["detail"] is not None else "")
             for c in record.get("checks", []) if not c["ok"]]
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        repo, "plans", "features", "epic-cm-visual-01", "evidence", "cmv-d")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    os.chdir(repo)
    import ui_round1025_matrix as M             # noqa: E402
    global W15
    import ui_evol_w15_composition_e2e as W15   # noqa: E402

    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    import urllib.request
    served = urllib.request.urlopen(
        "http://127.0.0.1:%d/web/app.js" % port, timeout=10).read()
    local = open(os.path.join(repo, "web", "app.js"), "rb").read()
    sha_served = hashlib.sha256(served).hexdigest()
    sha_local = hashlib.sha256(local).hexdigest()
    report = {"repo": repo, "viewports": [list(v) for v in VIEWPORTS],
              "served_app_sha256": sha_served, "local_app_sha256": sha_local}
    if sha_served != sha_local:
        print("FAIL: сервер отдаёт не тот app.js")
        return 3
    from playwright.sync_api import sync_playwright
    record = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            record = run(browser, base, out_dir)
        except Exception:                        # noqa: BLE001
            traceback.print_exc()
            report["fatal"] = traceback.format_exc()[-1600:]
        finally:
            browser.close()
            server.shutdown()
    fails = evaluate(record) if record else ["стенд не отработал"]
    if record:
        report.update(record)
    report["fails"] = fails
    report["verdict"] = "OK" if not fails else "FAIL"
    with open(os.path.join(out_dir, "cmv-d-fullscreen.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    total = len(record["checks"]) if record else 0
    passed = total - len(fails)
    print("CMV-D checks %d/%d, screenshots=%d" %
          (passed, total, len(record.get("screenshots", []) if record else [])))
    for f in fails:
        print("FAIL: " + f)
    print("CMV-D-FULLSCREEN %s" % ("OK" if not fails else "FAIL"))
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())

