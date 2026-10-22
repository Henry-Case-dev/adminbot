/* ═══ WIN-GLASS-P0 (18.10.2026): СОВМЕСТИМОЕ ПРЕЛОМЛЕНИЕ КОНТРОЛИРУЕМОГО
 * ФОНОВОГО СЛОЯ — видимое смещение фоновых пикселей там, где клиент НЕ
 * рендерит SVG-ссылку внутри `backdrop-filter` ═══
 *
 * Проблема (директива владельца, п.2; evidence: WebKit bug 245510,
 * mdn/browser-compat-data#24110, Fyrd/caniuse#7354): `backdrop-filter: …
 * url(#lg-lens)` рендерится в Chromium desktop, но не гарантирован в
 * Android WebView/WebKit. На таких клиентах стекло показывает только blur
 * либо вовсе без преломления — «оптики» нет.
 *
 * Решение: слой преломления рисует ТОЛЬКО контролируемый фон
 * (polygon-canvas `#polygon-background`; `?bgseed=` — детерминированный
 * тест-режим, `__PolygonBackground.pause()` — стоп rAF) в собственный
 * decorative `<canvas>` внутри стеклянной поверхности и применяет к нему
 * существующий SVG-фильтр линзы `url(#lg-lens)`. Живой DOM с текстом/данными
 * НЕ клонируется, текст/контролы не искажаются, фон production
 * (`polygon-background.js`, карта `#lg-lens`) не меняется.
 *
 * Инварианты:
 *   • слой — чистая декорация: `pointer-events:none`, `aria-hidden`,
 *     без текста/данных, клип по border-radius поверхности;
 *   • включается ТОЛЬКО для подтверждённого Tier A
 *     ([data-glass-tier="a"], решает app.js::reconcileLiquidGlass) и только
 *     когда источник фона реально доступен; иначе — честный фолбэк (blur),
 *     без ложного заявления «рефракция есть»;
 *   • Tier B/C и вложенное стекло не трогаются;
 *   • перф: ≤ maxLayers поверхностей, кап DPR 1.5, троттлинг обновления
 *     (~25 FPS), `document.hidden` → пауза, `prefers-reduced-motion` →
 *     редкие обновления, страница остаётся отзывчивой;
 *   • идемпотентность: повторный sync() не плодит слои/фильтры, dispose()
 *     возвращает DOM и стили как было.
 *
 * Публичное API (заморожено для тестов и app.js):
 *   window.__GlassRefraction = {
 *     start(), stop(), sync(), invalidate(),
 *     setEnabled(bool), enabled(), diagnostics(), stats()
 *   }
 * Чистые функции доступны в Node через module.exports (`_test`).
 * CSP-safe: без inline-скриптов/eval; только same-origin/data-URI карта линзы.
 */
(function () {
  'use strict';

  /* ── Константы ───────────────────────────────────────────────────────── */
  var LAYER_CLASS = 'lg-refract';
  var LAYER_ATTR = 'data-lg-refract';
  var FAIL_ATTR = 'data-lg-refract-failed';
  var FILTER_PREFIX = 'lg-refract-lens-';
  var MAP_ID = 'lg-lens-map';
  var BASE_FILTER_ID = 'lg-lens';

  var DEFAULT_MAX_LAYERS = 3;      // = hero-бюджет U08.3d (1–3); override env-флагом
  var DPR_CAP = 1.5;               // Android-бюджет (как DPR_CAP_MOBILE фона)
  var RENDER_INTERVAL_MS = 40;     // ~25 FPS — фон «дышит», не дёргается
  var REFRESH_MS = 700;            // reduced-motion: редкие обновления
  var REBUILD_MS = 1500;           // пересборка набора поверхностей
  var MIN_SURFACE_PX = 24;         // ниже — не линза, а артефакт
  var MIN_AREA_PX = 1200;
  // Рецепт стекла Tier A на слое (совпадает с --lg-frost-hero + линза):
  // подложка поверхности воспроизводится поверх копии фона (surfaceTint),
  // поэтому слой не «съедает» затемнение подложки.
  var LAYER_FILTER_MID = 'blur(5px) saturate(140%) url(#';
  // Маска-рамка слоя: solid → затухание; смещение линзы начинается ≈ с 19%
  // от кромки (карта: smoothstep 0.62…0.85 нормированной полуоси), поэтому
  // полоса 20+46 px покрывает рабочую зону кромки без перекрытия контента.
  var RING_SOLID_PX = 20;
  var RING_FADE_PX = 46;

  /* Селектор стеклянных поверхностей — зеркало app.js::_lgGlassSelector
   * (шов «готовая поверхность → слой преломления»). */
  var SURFACE_SELECTOR = '[data-glass], .card, .module-card, .hub-card,' +
    ' .prov-block, .glass-panel, .oversight-panel, .scope-panel, .modal-card,' +
    ' details.advanced, .lg-panel, .lg-mini-lens, .sticky-save';

  /* ── Состояние ───────────────────────────────────────────────────────── */
  var st = {
    enabled: true,
    running: false,
    raf: 0,
    lastPaint: 0,
    lastRebuild: 0,
    src: null,          // {el, kind, w, h, k, offX, offY}
    layers: [],         // активные слои
    filters: [],        // клоны SVG-фильтра линзы
    painted: 0,
    errors: 0,
    reason: 'not-started',
    visible: 0,
    maxLayers: DEFAULT_MAX_LAYERS,
    filterSeq: 0,
  };

  function hasDom() {
    return typeof document !== 'undefined' && typeof window !== 'undefined';
  }

  function nowMs() {
    try { return Date.now(); } catch (e) { return 0; }
  }

  function reducedMotion() {
    try {
      return !!(window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return false; }
  }

  /* Опциональный оверрайд из URL (детерминированные тесты/e2e):
   *   ?glassrefract=off — выключить слой целиком;
   *   ?glassrefract=on  — включён (дефолт);
   *   ?glassrefractmax=N — бюджет поверхностей (1..8). */
  function readUrlOverride() {
    if (!hasDom() || !window.location) return;
    try {
      var q = new URLSearchParams(window.location.search || '');
      var v = String(q.get('glassrefract') || '').toLowerCase();
      if (v === 'off' || v === '0' || v === 'false' || v === 'no') {
        st.enabled = false;
      }
      var n = parseInt(q.get('glassrefractmax'), 10);
      if (isFinite(n) && n > 0) st.maxLayers = Math.min(8, n);
    } catch (e) { /* нет URLSearchParams — дефолты */ }
  }
  readUrlOverride();

  /* ── Чистые функции (Node-тесты) ─────────────────────────────────────── */

  /* Выбор поверхностей для слоя преломления. Кандидаты уже отфильтрованы по
   * tier='a'; здесь — приоритет (hero → sticky → площадь → верх экрана) и
   * бюджет. Чистая функция — без DOM. */
  function pickSurfaces(candidates, max) {
    var out = [];
    if (!candidates || !candidates.length) return out;
    var cap = (typeof max === 'number' && max > 0) ? max : DEFAULT_MAX_LAYERS;
    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      if (!c || !c.el) continue;
      if (c.tier !== 'a') continue;        // только подтверждённый Tier A
      if (c.nested || c.dense) continue;   // вложенное/плотное — не линза
      if (c.area < MIN_AREA_PX) continue;
      if (c.minSide < MIN_SURFACE_PX) continue;
      if (c.offscreen) continue;
      out.push(c);
    }
    out.sort(function (a, b) {
      var ah = a.declared === 'a' ? 0 : 1, bh = b.declared === 'a' ? 0 : 1;
      if (ah !== bh) return ah - bh;
      if (!!a.sticky !== !!b.sticky) return a.sticky ? -1 : 1;
      if (b.area !== a.area) return b.area - a.area;
      return (a.top || 0) - (b.top || 0);
    });
    return out.slice(0, cap);
  }

  /* Параметры выборки фона для слоя: регион источника (в пикселях canvas),
   * соответствующий кромке поверхности, и размер вывода (CSS px).
   * src {k} — отношение пикселей canvas к CSS px; off {x,y} — смещение
   * источника (visual viewport Android). */
  function sourceFrame(src, rect, off) {
    if (!src || !rect) return null;
    var k = src.k || 1;
    var ox = (off && off.x) || 0, oy = (off && off.y) || 0;
    var sx = (rect.x + ox) * k;
    var sy = (rect.y + oy) * k;
    var sw = rect.w * k, sh = rect.h * k;
    if (!(sw > 0) || !(sh > 0)) return null;
    return { sx: sx, sy: sy, sw: sw, sh: sh, dw: rect.w, dh: rect.h };
  }

  /* ── Источник контролируемого фона ───────────────────────────────────── */

  /* Основной источник — polygon-canvas (fixed, z-index:0, за #app).
   * Fallback: canvas-совместимый `__AuroraFlow` (soft-откат
   * UI_POLYGON_BG_ENABLED=false). Иначе — честный отказ. */
  function findSource(force) {
    if (!hasDom()) return null;
    if (!force && st.src && st.src.el && st.src.el.parentNode) return st.src;
    var el = document.getElementById('polygon-background');
    var kind = 'polygon';
    if (!el || !el.getContext) {
      el = document.querySelector('.aurora-flow-canvas');
      kind = 'aurora-flow';
      if (el && !el.getContext) el = null;
    }
    if (!el) { st.src = null; return null; }
    var k = 1, offX = 0, offY = 0;
    try {
      var r = el.getBoundingClientRect();
      if (r && r.width >= 1 && el.width >= 1) {
        k = el.width / r.width;
        offX = r.left; offY = r.top;
      }
    } catch (e) { /* дефолт k=1, off=0 */ }
    st.src = { el: el, kind: kind, w: el.width, h: el.height,
               k: k, offX: offX, offY: offY };
    return st.src;
  }

  /* ── Фильтры линзы (клоны #lg-lens с уникальными id) ──────────────────── */

  function ensureFilter(slot) {
    if (!hasDom()) return null;
    var id = FILTER_PREFIX + slot;
    if (document.getElementById(id)) return id;
    // Клонируется ТОЛЬКО узел SVG-фильтра линзы (декоративная карта смещения),
    // не DOM поверхности: живой контент/текст в слой не попадает.
    var base = document.getElementById(BASE_FILTER_ID);
    if (!base || !base.parentNode) return null;
    var clone = base.cloneNode(true);
    clone.setAttribute('id', id);
    var map = clone.querySelector('feImage');
    if (map) map.setAttribute('id', id + '-map');
    base.parentNode.appendChild(clone);
    st.filters.push(id);
    return id;
  }

  /* Уникальный номер слота фильтра на весь lifetime модуля: один слой — один
   * SVG-фильтр (без переиспользования id между поверхностями). */
  function nextFilterSlot() {
    st.filterSeq = (st.filterSeq || 0) + 1;
    return st.filterSeq;
  }

  function dropFilter(id) {
    if (!hasDom() || !id) return;
    try {
      var n = document.getElementById(id);
      if (n && n.parentNode) n.parentNode.removeChild(n);
    } catch (e) { /* no-op */ }
    var i = st.filters.indexOf(id);
    if (i >= 0) st.filters.splice(i, 1);
  }

  /* Карта смещения линзы должна существовать: без неё слой не даст
   * преломления (честный отказ, а не «псевдо-оптика»). */
  function lensMapAvailable() {
    if (!hasDom()) return false;
    return !!(document.getElementById(BASE_FILTER_ID) ||
              document.getElementById(MAP_ID));
  }

  /* ── Слои ────────────────────────────────────────────────────────────── */

  function radiusOf(el) {
    var r = 0;
    try {
      var cs = getComputedStyle(el);
      r = parseFloat(cs.borderTopLeftRadius) || 0;
      if (r > 64) r = 64;
    } catch (e) { r = 0; }
    return r;
  }

  /* Собственная подложка поверхности (цвет + alpha): слой обязан её
   * воспроизвести, иначе он «съел» бы затемнение подложки и кромки стали бы
   * ярче (замер: +23% luma в рамке). Возвращает {color, alpha}. */
  function surfaceTint(el) {
    var out = { color: 'rgb(0,0,0)', alpha: 0 };
    try {
      var bg = getComputedStyle(el).backgroundColor || '';
      var m = bg.match(/rgba?\(([^)]+)\)/);
      if (!m) return out;
      var parts = m[1].split(',').map(function (s) { return s.trim(); });
      var r = parseFloat(parts[0]), g = parseFloat(parts[1]), b = parseFloat(parts[2]);
      var a = (parts.length > 3) ? parseFloat(parts[3]) : 1;
      if (!isFinite(r) || !isFinite(g) || !isFinite(b)) return out;
      out.color = 'rgb(' + Math.round(r) + ',' + Math.round(g) + ',' +
                  Math.round(b) + ')';
      // Кап alpha: слой обязан оставаться видимым (для непрозрачных подложек
      // он всё равно отбраковывается в opaqueSurface()).
      out.alpha = (isFinite(a) && a > 0) ? Math.min(0.8, a) : 0;
    } catch (e) { /* без подложки — как есть */ }
    return out;
  }

  function makeLayer(surface, filterId) {
    var cv = document.createElement('canvas');
    cv.className = LAYER_CLASS;
    cv.setAttribute(LAYER_ATTR, '1');
    cv.setAttribute('aria-hidden', 'true');
    cv.setAttribute('tabindex', '-1');
    var stp = cv.style;
    stp.position = 'absolute';
    stp.left = '0'; stp.top = '0';
    stp.zIndex = '-1';          // под tint/контентом, над фоном поверхности
    stp.pointerEvents = 'none';
    var rad = radiusOf(surface);
    stp.borderRadius = rad ? rad + 'px' : 'inherit';
    // Собственный backdrop-filter не нужен (blur входит в filter ниже).
    stp.webkitBackdropFilter = 'none';
    stp.backdropFilter = 'none';
    // Рецепт тот же, что у Tier A на desktop (--lg-frost-hero) + SVG-линза:
    // blur(5px) saturate(140%) url(#lg-refract-lens-N) — слой выглядит как
    // подложка поверхности, но с реальным смещением геометрии у кромки.
    stp.filter = LAYER_FILTER_MID + filterId + ')';
    stp.webkitFilter = LAYER_FILTER_MID + filterId + ')';
    // Маска-рамка: преломление видно у кромок (там, где карта линзы даёт
    // смещение), центр панели остаётся спокойным/читаемым и не перекрывает
    // контент под стеклом (SOUL-17.3). Ширина полос зависит от стороны
    // поверхности — иначе у компактной карточки рамка покрывает её целиком.
    applyRingMask(cv, radiusRectW(surface), radiusRectH(surface));
    surface.appendChild(cv);
    return cv;
  }

  /* Фактический CSS-размер поверхности (для пересчёта маски при resize). */
  function radiusRectW(el) {
    try { return Math.round(el.getBoundingClientRect().width) || 0; }
    catch (e) { return 0; }
  }
  function radiusRectH(el) {
    try { return Math.round(el.getBoundingClientRect().height) || 0; }
    catch (e) { return 0; }
  }

  /* Ширина полосы рамки ОТ КАЖДОЙ СТОРОНЫ (U-01/U-02).
   Абсолютные 20+46 px годятся только для высоких панелей: у компактной
   карточки (78–100 px) верхняя и нижняя полосы смыкаются, union-маска
   покрывает ВСЮ поверхность — и слой показывает прямоугольную копию фона
   поверх подложки («карточка разрезана цветным блоком», швы по кромкам).
   Поэтому полоса пропорциональна стороне и не выходит за капы 20/46 px;
   на любой стороне остаётся спокойный центр (не меньше ~52% стороны). */
  function ringBand(side) {
    var s = (side > 0) ? side : 0;
    var solid = Math.max(6, Math.min(RING_SOLID_PX, Math.round(s * 0.10)));
    var fade = Math.max(8, Math.min(RING_FADE_PX, Math.round(s * 0.14)));
    return { solid: solid, fade: fade };
  }

  /* CSS-рамка через четыре линейных градиента (без URL/data-URI — CSP-safe):
   * union = рамка с мягким затуханием внутрь поверхности. Горизонтальные
   * полосы считаются по ширине, вертикальные — по высоте (см. ringBand). */
  function applyRingMask(cv, w, h) {
    var bx = ringBand(w);
    var by = ringBand(h);
    var sx = bx.solid + bx.fade;
    var sy = by.solid + by.fade;
    var s = 'linear-gradient(to right, #fff 0 ' + bx.solid + 'px, transparent ' +
      sx + 'px)';
    var sl = 'linear-gradient(to left, #fff 0 ' + bx.solid + 'px, transparent ' +
      sx + 'px)';
    var st = 'linear-gradient(to bottom, #fff 0 ' + by.solid + 'px, transparent ' +
      sy + 'px)';
    var sb = 'linear-gradient(to top, #fff 0 ' + by.solid + 'px, transparent ' +
      sy + 'px)';
    var val = s + ', ' + sl + ', ' + st + ', ' + sb;
    try {
      cv.style.webkitMaskImage = val;
      cv.style.maskImage = val;
      cv.style.webkitMaskRepeat = 'no-repeat';
      cv.style.maskRepeat = 'no-repeat';
    } catch (e) { /* без маски слой честно остаётся полным (не ломаем вид) */ }
  }

  /* Подложки предков между контролируемым фоном и поверхностью (U-01/U-02).
   * Слой рисует копию фона, но НЕ знал о затемняющих слоях-контейнерах
   * (desktop `.scroll-area` = rgba(9,13,23,.62)): копия выходила ярче реальной
   * подложки и на кромке карточки появлялся прямоугольный шов. Здесь
   * собираем ровно те alpha-заливки, которые лежат над canvas и под
   * поверхностью; красим их в слой в том же порядке (снаружи → внутрь).
   * body не берём: его фон рисуется ПОД фоновым canvas. */
  function ancestorVeil(el) {
    var out = [];
    if (!el) return out;
    var p = el.parentElement;
    var guard = 0;
    while (p && p !== document.documentElement && guard < 24) {
      guard++;
      if (p === document.body) break;
      try {
        var bg = getComputedStyle(p).backgroundColor || '';
        var m = bg.match(/rgba?\(([^)]+)\)/);
        if (m) {
          var parts = m[1].split(',').map(function (x) { return x.trim(); });
          var a = (parts.length > 3) ? parseFloat(parts[3]) : 1;
          var cr = parseFloat(parts[0]), cg = parseFloat(parts[1]),
              cb = parseFloat(parts[2]);
          if (isFinite(a) && a > 0.02 && isFinite(cr) && isFinite(cg) &&
              isFinite(cb)) {
            out.push({
              color: 'rgb(' + Math.round(cr) + ',' + Math.round(cg) + ',' +
                     Math.round(cb) + ')',
              alpha: Math.min(1, a),
            });
          }
        }
      } catch (e) { /* без подложки предка — как было */ }
      p = p.parentElement;
    }
    out.reverse();
    return out;
  }

  function removeLayer(rec) {
    if (!rec) return;
    try {
      if (rec.canvas && rec.canvas.parentNode) {
        rec.canvas.parentNode.removeChild(rec.canvas);
      }
    } catch (e) { /* no-op */ }
    try {
      if (rec.surface) {
        if (rec.prevOverflow === null) rec.surface.style.removeProperty('overflow');
        else if (rec.prevOverflow !== undefined) {
          rec.surface.style.overflow = rec.prevOverflow;
        }
        if (rec.prevIsolation === null) rec.surface.style.removeProperty('isolation');
        else if (rec.prevIsolation !== undefined) {
          rec.surface.style.isolation = rec.prevIsolation;
        }
        if (rec.prevPosition === null) rec.surface.style.removeProperty('position');
        else if (rec.prevPosition !== undefined && rec.prevPosition !== 'unchanged') {
          rec.surface.style.position = rec.prevPosition;
        }
        rec.surface.removeAttribute(LAYER_ATTR);
      }
    } catch (e2) { /* no-op */ }
  }

  function disposeAll() {
    for (var i = 0; i < st.layers.length; i++) removeLayer(st.layers[i]);
    st.layers = [];
    var f;
    while ((f = st.filters.pop())) dropFilter(f);
    if (hasDom()) {
      var left = document.querySelectorAll('.' + LAYER_CLASS);
      for (var j = 0; j < left.length; j++) {
        if (left[j].parentNode) left[j].parentNode.removeChild(left[j]);
      }
    }
    st.visible = 0;
  }

  /* Поверхность физически не покажет слой, если её собственная подложка почти
   * непрозрачна (shell-панели §8: alpha .72…/.78 + specular-градиент) —
   * линза под ней не видна, GPU не тратим. Порог 0.7: у стеклянных карточек
   * alpha .5…0.62, у плотных поверхностей — ≥ .85. */
  function opaqueSurface(el) {
    try {
      var cs = getComputedStyle(el);
      var bg = cs.backgroundColor || '';
      var m = bg.match(/rgba?\(([^)]+)\)/);
      if (!m) return false;
      var parts = m[1].split(',');
      // rgb(...) без alpha = непрозрачный фон: слой под ним не виден.
      if (parts.length < 4) return true;
      var a = parseFloat(parts[3]);
      return isFinite(a) && a >= 0.7;
    } catch (e) { return false; }
  }

  /* ── Синхронизация с разметкой app.js::reconcileLiquidGlass ──────────── */

  function collectCandidates() {
    var nodes = document.querySelectorAll(SURFACE_SELECTOR);
    var vw = window.innerWidth || 1, vh = window.innerHeight || 1;
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.getAttribute('data-glass-tier') !== 'a') continue;
      if (opaqueSurface(el)) continue;             // слой всё равно не виден
      var r;
      try { r = el.getBoundingClientRect(); } catch (e) { continue; }
      if (!r || !(r.width > 0) || !(r.height > 0)) continue;
      var sticky = false;
      try {
        var pos = getComputedStyle(el).position;
        sticky = (pos === 'sticky' || pos === 'fixed');
      } catch (e2) { sticky = false; }
      out.push({
        el: el,
        tier: 'a',
        declared: (el.getAttribute('data-glass') || '').toLowerCase(),
        nested: el.getAttribute('data-glass-nested') === '1',
        dense: false,
        area: r.width * r.height,
        minSide: Math.min(r.width, r.height),
        top: r.top,
        sticky: sticky,
        offscreen: (r.bottom <= 0) || (r.top >= vh) ||
                   (r.right <= 0) || (r.left >= vw),
      });
    }
    return out;
  }

  /* Геометрия + отрисовка. force=true — немедленный кадр (после rebuild). */
  function paintLayers(force) {
    if (!hasDom()) return;
    var src = findSource(false);
    if (!src) { st.reason = 'no-background-source'; return; }
    if (!st.layers.length) { st.visible = 0; return; }
    var t0 = (typeof performance !== 'undefined' && performance.now)
      ? performance.now() : 0;
    var dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
    var off = { x: src.offX || 0, y: src.offY || 0 };
    var painted = 0;
    for (var i = 0; i < st.layers.length; i++) {
      var rec = st.layers[i];
      var el = rec.surface;
      if (!el || !el.parentNode) continue;
      var r;
      try { r = el.getBoundingClientRect(); } catch (e) { continue; }
      if (!(r.width > 0) || !(r.height > 0)) continue;
      if (r.bottom <= 0 || r.top >= (window.innerHeight || 1)) continue;
      var cw = Math.max(1, Math.round(r.width * dpr));
      var ch = Math.max(1, Math.round(r.height * dpr));
      if (rec.canvas.width !== cw || rec.canvas.height !== ch) {
        rec.canvas.width = cw;
        rec.canvas.height = ch;
      }
      var cst = rec.canvas.style;
      if (cst.width !== Math.round(r.width) + 'px') {
        cst.width = Math.round(r.width) + 'px';
      }
      if (cst.height !== Math.round(r.height) + 'px') {
        cst.height = Math.round(r.height) + 'px';
      }
      var rad = radiusOf(el);
      var radCss = rad ? rad + 'px' : 'inherit';
      if (cst.borderRadius !== radCss) cst.borderRadius = radCss;
      // Resize/refold: полосы рамки зависят от фактической стороны —
      // пересчитываем маску, когда геометрия изменилась (U-01/U-02).
      var mw = Math.round(r.width), mh = Math.round(r.height);
      if (rec.maskW !== mw || rec.maskH !== mh) {
        applyRingMask(rec.canvas, mw, mh);
        rec.maskW = mw;
        rec.maskH = mh;
      }
      var ctx = rec.ctx;
      if (!ctx) continue;
      var fr = sourceFrame({ k: src.k || 1 },
                           { x: r.left, y: r.top, w: r.width, h: r.height },
                           off);
      if (!fr) continue;
      try {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.globalAlpha = 1;
        ctx.globalCompositeOperation = 'source-over';
        ctx.clearRect(0, 0, cw, ch);
        ctx.drawImage(src.el, fr.sx, fr.sy, fr.sw, fr.sh, 0, 0, cw, ch);
        // Затемняющие подложки контейнеров над фоном (desktop `.scroll-area`
        // и т.п.) — иначе копия ярче реальной подложки и на кромке виден шов.
        var veil = rec.veil || [];
        for (var vi = 0; vi < veil.length; vi++) {
          var v = veil[vi];
          if (!v || !(v.alpha > 0)) continue;
          ctx.globalAlpha = v.alpha;
          ctx.fillStyle = v.color;
          ctx.fillRect(0, 0, cw, ch);
        }
        // Собственная подложка поверхности: слой (z-index:-1) рисуется ПОВЕРХ
        // background родителя, поэтому без неё полоса кромки выходила на
        // треть ярче интерьера (U-01/U-02). Порядок = фактический стек.
        var tint = rec.tint;
        if (tint && tint.alpha > 0) {
          ctx.globalAlpha = tint.alpha;
          ctx.fillStyle = tint.color;
          ctx.fillRect(0, 0, cw, ch);
        }
        ctx.globalAlpha = 1;
        painted++;
      } catch (e2) {
        st.errors++;
        try { el.setAttribute(FAIL_ATTR, '1'); } catch (e3) { /* no-op */ }
      }
    }
    st.painted = painted;
    st.visible = painted;
    st.reason = painted > 0 ? 'active' : 'paint-empty';
    st.lastPaint = nowMs();
    // Перф-бюджет: стоимость кадра слоя (копия фона + подложка в canvas).
    if (t0) {
      try {
        var dt = performance.now() - t0;
        st.paintMs = st.paintMs ? (st.paintMs * 0.8 + dt * 0.2) : dt;
        if (!st.paintMsMax || dt > st.paintMsMax) st.paintMsMax = dt;
        st.paintCount = (st.paintCount || 0) + 1;
      } catch (e3) { /* perf-API нет — без метрики */ }
    }
  }

  /* Пересборка состава поверхностей (троттлинг) + фильтры под новые слои. */
  function rebuild() {
    if (!hasDom()) return;
    if (!st.enabled) { disposeAll(); st.reason = 'disabled'; return; }
    if (!lensMapAvailable()) { disposeAll(); st.reason = 'no-lens-map'; return; }
    var src = findSource(true);
    if (!src) { disposeAll(); st.reason = 'no-background-source'; return; }
    if (document.hidden) { st.reason = 'hidden'; return; }
    var picked = pickSurfaces(collectCandidates(), st.maxLayers);
    var keep = [];
    for (var i = 0; i < picked.length; i++) {
      var surface = picked[i].el;
      var found = null;
      for (var j = 0; j < st.layers.length; j++) {
        if (st.layers[j].surface === surface) { found = st.layers[j]; break; }
      }
      if (found && found.canvas && found.canvas.parentNode) {
        // Пересобрали состав — обновляем и подложку/veil: тема/флаги/роут
        // могли смениться (light/dark, другой контейнер), копия фона обязана
        // совпадать с фактическим стеком подложек (U-01/U-02).
        try { found.tint = surfaceTint(surface); } catch (eT) { /* как было */ }
        try { found.veil = ancestorVeil(surface); } catch (eV) { /* как было */ }
        keep.push(found);
        continue;
      }
      var fid = ensureFilter(nextFilterSlot());
      if (!fid) continue;
      var rec = { surface: surface, canvas: null, ctx: null, fid: fid,
                  tint: surfaceTint(surface), veil: ancestorVeil(surface),
                  maskW: -1, maskH: -1 };
      // Контейнер: нужен контекст/клип; инлайновые стили возвращаем при снятии.
      try {
        rec.prevOverflow = surface.style.overflow || null;
        rec.prevIsolation = surface.style.isolation || null;
        rec.prevPosition = surface.style.position || null;
        surface.style.overflow = 'clip';
        if (!rec.prevIsolation) surface.style.isolation = 'isolate';
        // Абсолютный слой требует позиционированного контейнера — иначе он
        // уедет к ближайшему positioned-предку (класс поверхностей `static`).
        var pos = getComputedStyle(surface).position;
        if (pos === 'static') surface.style.position = 'relative';
        else rec.prevPosition = 'unchanged';
      } catch (e0) { /* no-op */ }
      var cv = makeLayer(surface, fid);
      try { rec.ctx = cv.getContext('2d'); } catch (e1) { rec.ctx = null; }
      if (!rec.ctx) { removeLayer(rec); dropFilter(fid); continue; }
      rec.canvas = cv;
      surface.setAttribute(LAYER_ATTR, '1');
      keep.push(rec);
    }
    // Снять то, что выпало из набора (смена роута/тира/бюджета).
    for (var k = 0; k < st.layers.length; k++) {
      var old = st.layers[k];
      if (keep.indexOf(old) < 0) {
        removeLayer(old);
        dropFilter(old.fid);
      }
    }
    st.layers = keep;
    st.lastRebuild = nowMs();
    paintLayers(true);
  }

  /* ── Цикл ────────────────────────────────────────────────────────────── */

  function loop(ts) {
    st.raf = 0;
    if (!st.running) return;
    if (hasDom() && document.hidden) {
      st.reason = 'hidden';
      schedule();
      return;
    }
    // Один тайм-базис: rAF-таймстамп и Date.now() несравнимы — интервал
    // считаем по nowMs() (иначе после первого кадра перерисовок не было бы).
    var t = nowMs();
    var interval = reducedMotion() ? REFRESH_MS : RENDER_INTERVAL_MS;
    if (!st.lastPaint || (t - st.lastPaint) >= interval) {
      if (t - st.lastRebuild >= REBUILD_MS) rebuild();
      paintLayers(false);
    }
    schedule();
  }

  function schedule() {
    if (!st.running || st.raf) return;
    try { st.raf = window.requestAnimationFrame(loop); }
    catch (e) { st.raf = 0; }
  }

  /* ── Публичное API ───────────────────────────────────────────────────── */

  function sync() {
    st.reason = st.enabled ? 'syncing' : 'disabled';
    st.lastRebuild = 0;              // следующий кадр пересоберёт состав
    st.lastPaint = 0;                // и отрисует немедленно (без ожидания интервала)
    schedule();
  }

  function invalidate() {
    findSource(true);
    sync();
  }

  function start(opts) {
    opts = opts || {};
    if (typeof opts.maxLayers === 'number' && opts.maxLayers > 0) {
      st.maxLayers = Math.min(8, Math.floor(opts.maxLayers));
    }
    st.running = true;
    if (!st.reason || st.reason === 'not-started') st.reason = 'starting';
    sync();
    return true;
  }

  function stop() {
    st.running = false;
    if (st.raf) {
      try { window.cancelAnimationFrame(st.raf); } catch (e) { /* no-op */ }
      st.raf = 0;
    }
    disposeAll();
    st.reason = 'stopped';
  }

  function setEnabled(v) {
    st.enabled = !!v;
    if (!st.enabled) disposeAll();
    else sync();
    return st.enabled;
  }

  function diagnostics() {
    var src = st.src;
    var layers = [];
    for (var i = 0; i < st.layers.length; i++) {
      var rec = st.layers[i];
      var el = rec.surface;
      var tag = (el && el.tagName) ? el.tagName.toLowerCase() : '?';
      var cls = (el && typeof el.className === 'string')
        ? el.className.split(/\s+/).slice(0, 3).join('.') : '';
      layers.push({
        el: tag + (cls ? '.' + cls : ''),
        tier: el ? el.getAttribute('data-glass-tier') : null,
        filter: rec.fid || null,
        w: rec.canvas ? rec.canvas.width : 0,
        h: rec.canvas ? rec.canvas.height : 0,
      });
    }
    return {
      version: 1,
      enabled: st.enabled,
      running: st.running,
      reason: st.reason,
      backgroundSource: src ? src.kind : null,
      backgroundSize: src ? [src.w, src.h] : null,
      layers: layers,
      painted: st.painted,
      errors: st.errors,
      reducedMotion: reducedMotion(),
      dprCap: DPR_CAP,
      /* Перф-бюджет слоя: средняя (EMA) и максимальная стоимость кадра,
       * число кадров — замер только при наличии performance.now(). */
      paintMs: st.paintMs ? Math.round(st.paintMs * 100) / 100 : null,
      paintMsMax: st.paintMsMax ? Math.round(st.paintMsMax * 100) / 100 : null,
      paintCount: st.paintCount || 0,
      renderIntervalMs: RENDER_INTERVAL_MS,
      layerClass: LAYER_CLASS,
      filterBase: BASE_FILTER_ID,
      maxLayers: st.maxLayers || DEFAULT_MAX_LAYERS,
    };
  }

  var api = {
    start: start, stop: stop, sync: sync, invalidate: invalidate,
    setEnabled: setEnabled,
    enabled: function () { return st.enabled; },
    diagnostics: diagnostics,
    stats: function () {
      return { painted: st.painted, errors: st.errors, visible: st.visible };
    },
    _test: {
      pickSurfaces: pickSurfaces,
      sourceFrame: sourceFrame,
      constants: {
        LAYER_CLASS: LAYER_CLASS, FILTER_PREFIX: FILTER_PREFIX,
        DEFAULT_MAX_LAYERS: DEFAULT_MAX_LAYERS, DPR_CAP: DPR_CAP,
        RENDER_INTERVAL_MS: RENDER_INTERVAL_MS,
        RING_SOLID_PX: RING_SOLID_PX, RING_FADE_PX: RING_FADE_PX,
      },
    },
  };

  if (hasDom()) window.__GlassRefraction = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
