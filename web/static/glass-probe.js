/* ═══ W2-GLASS (U08.3, REQ-U08-1-PROBE): render-probe Liquid Glass ═══
 *
 * Заменяет CSS.supports-детект app.js::_liquidGlassSupported (T-2585), который
 * не является доказательством рендера: WebKit/Telegram-WebKit может
 * игнорировать `filter: url(#…)` / `backdrop-filter: url(#…)`, формально
 * возвращая true (WebKit bug 245510: backdrop-filter с feDisplacementMap
 * НЕ рендерится в Safari при рабочем Chromium).
 *
 * Что делает probe(): РЕАЛЬНЫЙ рендер-тест.
 *   1. В документ добавляется одноразовый скрытый SVG-фильтр #lg-probe-disp:
 *      feFlood (постоянная карта смещения R≈0.7529) + feDisplacementMap
 *      scale=32 → детерминированный сдвиг ≈ 8.09px по X.
 *   2. На offscreen canvas рисуется детерминированная полосатая мишень
 *      (период 8px) — снимок A; затем та же мишень с ctx.filter='url(…)'
 *      — снимок B.
 *   3. Пиксельная сверка: снимок B должен значимо отличаться от A И
 *      совпасть с A, сдвинутым на ожидаемые 8px (cross-check против
 *      «фильтр просто что-то нарисовал»).
 *
 * tierA = svgRender (доказанный рендер displacement) AND backdrop (есть
 * backdrop-filter вообще) AND engine==='chromium' (у Chromium доказанно
 * работает backdrop-filter: url(#feDisplacementMap); у WebKit — нет,
 * bug 245510; у Gecko — не доказано в целевых клиентах). Engine — сигнал
 * семейства по capability-признакам (window.chrome / InstallTrigger), не
 * UA-парсинг. Решение по ТЗ U08.3: «render-probe или поддерживаемый mode
 * based on engine + настоящая проверка screenshot».
 *
 * CSP-safe: без inline-скриптов/eval; canvas и SVG создаются из JS.
 * Без Vue; единственный потребитель — web/app.js (reconcileLiquidGlass)
 * и тестовый стенд glass-teststand.html. Другие лейны не вызывают.
 *
 * Публичное API (заморожено w2-contract.md §3.4):
 *   window.__GlassProbe = {
 *     probe(): Promise<{tierA, reason, engine, svgRender, backdrop, ms}>,
 *     cached(): результат|null, reset(), details(): сырые счётчики
 *   }
 */
(function () {
  'use strict';

  var SHIFT_PX = 8;          // ожидаемый сдвиг: 32 * (191/255 - 0.5) ≈ 8.09
  var DIFF_MIN = 2.0;        // средняя |Δ| между A и B, 0..255
  var SHIFT_MATCH_MIN = 0.6; // доля совпадения B с A, сдвинутым на SHIFT_PX

  var _cached = null;   // Promise<result> | null
  var _result = null;   // последний завершённый результат
  var _details = null;

  function hasDom() {
    return typeof document !== 'undefined' && typeof window !== 'undefined';
  }

  /* Engine-сигнал семейства по capability-признакам (без UA-строк). */
  function detectEngine() {
    if (!hasDom()) return 'unknown';
    try {
      var w = window;
      // Chromium: window.chrome присутствует (Chrome/Edge/WebView/TMA-Android).
      if (w.chrome && typeof w.chrome === 'object' && w.chrome.runtime) return 'chromium';
      if (w.chrome) return 'chromium';
      // Gecko: InstallTrigger — исторический Firefox-эксклюзив.
      if (typeof w.InstallTrigger !== 'undefined') return 'gecko';
      // WebKit/Safari: без chrome/InstallTrigger, но с webkit-префиксами.
      if (w.CSS && typeof w.CSS.supports === 'function' &&
          w.CSS.supports('-webkit-touch-callout', 'none')) return 'webkit';
    } catch (e) { /* no-op */ }
    return 'unknown';
  }

  function backdropSupported() {
    if (!hasDom() || !window.CSS || typeof window.CSS.supports !== 'function') return false;
    try {
      return window.CSS.supports('backdrop-filter', 'blur(2px)') ||
             window.CSS.supports('-webkit-backdrop-filter', 'blur(2px)');
    } catch (e) { return false; }
  }

  /* Одноразовый SVG с фильтром-пробой. Карта смещения — feFlood R=191/255
   * (G=128/255 → dy≈0), scale=32 → сдвиг вправо ≈ 8.09px. */
  function ensureProbeFilter() {
    var SVG_NS = 'http://www.w3.org/2000/svg';
    var existing = document.getElementById('lg-probe-defs');
    if (existing) return existing;
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('id', 'lg-probe-defs');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.style.position = 'absolute';
    svg.style.width = '0';
    svg.style.height = '0';
    svg.style.overflow = 'hidden';
    var defs = document.createElementNS(SVG_NS, 'defs');
    var filter = document.createElementNS(SVG_NS, 'filter');
    filter.setAttribute('id', 'lg-probe-disp');
    filter.setAttribute('x', '0'); filter.setAttribute('y', '0');
    filter.setAttribute('width', '100%'); filter.setAttribute('height', '100%');
    filter.setAttribute('color-interpolation-filters', 'sRGB');
    var flood = document.createElementNS(SVG_NS, 'feFlood');
    flood.setAttribute('flood-color', 'rgb(191,128,128)');
    flood.setAttribute('result', 'map');
    var disp = document.createElementNS(SVG_NS, 'feDisplacementMap');
    disp.setAttribute('in', 'SourceGraphic');
    disp.setAttribute('in2', 'map');
    disp.setAttribute('scale', '32');
    disp.setAttribute('xChannelSelector', 'R');
    disp.setAttribute('yChannelSelector', 'G');
    filter.appendChild(flood);
    filter.appendChild(disp);
    defs.appendChild(filter);
    svg.appendChild(defs);
    document.documentElement.appendChild(svg);
    return svg;
  }

  /* Детерминированная полосатая мишень: вертикальные полосы периода 7px.
   * Период 7 выбран НЕ кратным ожидаемому сдвигу 8px, иначе сдвиг на полный
   * период дал бы визуально идентичный узор (diff≈0 → ложный «нет рендера»). */
  function drawTarget(ctx, w, h) {
    ctx.clearRect(0, 0, w, h);
    for (var x = 0; x < w; x++) {
      var on = Math.floor(x / 7) % 2 === 0;
      ctx.fillStyle = on ? 'rgb(250,252,255)' : 'rgb(8,12,20)';
      ctx.fillRect(x, 0, 1, h);
    }
  }

  function rowAvgDiff(a, b, w, h) {
    var ad = a.data, bd = b.data, sum = 0, n = 0;
    for (var i = 0; i < ad.length; i += 4) {
      sum += Math.abs(ad[i] - bd[i]) + Math.abs(ad[i + 1] - bd[i + 1]) +
             Math.abs(ad[i + 2] - bd[i + 2]);
      n += 3;
    }
    return sum / Math.max(1, n);
  }

  /* Доля совпадения B со сдвинутым A по X на shift px (0..1). */
  function shiftMatch(a, b, w, h, shift) {
    var ad = a.data, bd = b.data;
    var ok = 0, total = 0;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        var sx = x - shift;
        if (sx < 0 || sx >= w) continue;
        var bi = (y * w + x) * 4, ai = (y * w + sx) * 4;
        var d = Math.abs(ad[ai] - bd[bi]) + Math.abs(ad[ai + 1] - bd[bi + 1]) +
                Math.abs(ad[ai + 2] - bd[bi + 2]);
        if (d < 24) ok++;
        total++;
      }
    }
    return total ? ok / total : 0;
  }

  /* Чистая функция решения (для Node-тестов): exp = {svgRender, backdrop,
   * engine} → {tierA, reason}. */
  function decide(exp) {
    if (!exp.svgRender) {
      return { tierA: false, reason: 'svg-render-failed' };
    }
    if (!exp.backdrop) {
      return { tierA: false, reason: 'no-backdrop-filter' };
    }
    if (exp.engine === 'chromium') {
      return { tierA: true, reason: 'probe-chromium' };
    }
    if (exp.engine === 'webkit') {
      // bug 245510: WebKit игнорирует url() в backdrop-filter — честный Tier B.
      return { tierA: false, reason: 'engine-webkit-backdrop-url-no' };
    }
    return { tierA: false, reason: 'engine-unproven-backdrop-url' };
  }

  function runCanvasProbe() {
    var cv = document.createElement('canvas');
    cv.width = 72; cv.height = 40;
    var ctx = cv.getContext('2d', { willReadFrequently: true });
    if (!ctx) return { svgRender: false, diff: 0, match: 0 };
    var probeFilterUrl = 'url(#lg-probe-disp)';
    // A: без фильтра
    drawTarget(ctx, cv.width, cv.height);
    var a = ctx.getImageData(0, 0, cv.width, cv.height);
    // B: с SVG-фильтром смещения
    drawTarget(ctx, cv.width, cv.height);
    var applied = false;
    try {
      ctx.filter = probeFilterUrl;
      applied = String(ctx.filter).indexOf('url(') !== -1;
    } catch (e) { applied = false; }
    var out = { svgRender: false, diff: 0, match: 0, ctxFilterApplied: applied };
    if (!applied) return out;
    // Перерисовать мишень ПОД фильтром (filter применяется к операциям рисования).
    drawTarget(ctx, cv.width, cv.height);
    var b = ctx.getImageData(0, 0, cv.width, cv.height);
    var diff = rowAvgDiff(a, b, cv.width, cv.height);
    var match = shiftMatch(a, b, cv.width, cv.height, SHIFT_PX);
    out.diff = Math.round(diff * 10) / 10;
    out.match = Math.round(match * 1000) / 1000;
    out.svgRender = diff >= DIFF_MIN && match >= SHIFT_MATCH_MIN;
    return out;
  }

  function probe() {
    if (_cached) return _cached;
    _cached = new Promise(function (resolve) {
      var t0 = (typeof performance !== 'undefined' && performance.now) ?
        performance.now() : Date.now();
      var engine = detectEngine();
      var backdrop = backdropSupported();
      var canvasRes = { svgRender: false, diff: 0, match: 0 };
      var reason = 'no-dom';
      if (hasDom()) {
        try {
          ensureProbeFilter();
          canvasRes = runCanvasProbe();
        } catch (e) {
          canvasRes = { svgRender: false, diff: 0, match: 0, error: String(e) };
        }
        var dec = decide({
          svgRender: canvasRes.svgRender,
          backdrop: backdrop,
          engine: engine,
        });
        reason = dec.reason;
        // На не-Chromium: probe всё равно зафиксируем как провал tierA,
        // но сохраним честную причину из decide().
      }
      var ms = Math.round(((typeof performance !== 'undefined' && performance.now) ?
        performance.now() : Date.now()) - t0);
      _result = {
        tierA: !!(hasDom() && canvasRes.svgRender && backdrop && engine === 'chromium'),
        reason: reason,
        engine: engine,
        svgRender: !!canvasRes.svgRender,
        backdrop: backdrop,
        ms: ms,
      };
      _details = canvasRes;
      resolve(_result);
    });
    return _cached;
  }

  window.__GlassProbe = {
    probe: probe,
    cached: function () { return _result; },
    reset: function () { _cached = null; _result = null; _details = null; },
    details: function () { return _details; },
    // test-hooks (Node): чистые функции без DOM
    _test: { decide: decide, detectEngine: detectEngine },
  };
})();
