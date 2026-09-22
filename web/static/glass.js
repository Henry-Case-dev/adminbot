/* HOTFIX9 (ADR-1025-17 D5, T-2817/T-2818/T-2819): точечное применение
 * vendored `@liquidglassjs/core` 0.5.3 (same-origin, CSP `script-src 'self'`).
 *
 * Настоящее преломление: библиотека применяет SVG `feDisplacementMap` к фону
 * позади (собственный inline style САМОЙ библиотеки; в первопартийном CSS
 * проекта url-фильтр отсутствует). Проверено прототипом
 * `tools/glass_prototype_probe.py` (стекло реагирует на содержимое ПОЗАДИ).
 *
 * Применяется ТОЛЬКО к целевым элементам (селектор области, fullscreen-кнопка,
 * декоративный блок «Статуса»); sidebar/header остаются графитовыми. Если
 * библиотека недоступна/бросила исключение — молча остаётся frost-fallback
 * (`backdrop-filter: blur`), без «линзы-виньетки». */
(function () {
  'use strict';
  var TARGETS = '.scope-trigger, .header-fs-btn, .status-block';
  var OPTS = {
    strength: 12, edge: 0.8, chroma: 0.18, spec: 0.7, tint: 6, blur: 2,
  };
  var mounted = [];

  function lib() {
    return (window.LiquidGlass && typeof window.LiquidGlass.mountGlass === 'function')
      ? window.LiquidGlass : null;
  }

  function disposeAll() {
    for (var i = 0; i < mounted.length; i++) {
      try { if (mounted[i] && typeof mounted[i].dispose === 'function') mounted[i].dispose(); }
      catch (e) { /* no-op */ }
      try { mounted[i].root && mounted[i].root.removeAttribute('data-lg-mounted'); }
      catch (e2) { /* no-op */ }
    }
    mounted = [];
  }

  function optsFor(el) {
    var o = {};
    for (var k in OPTS) { if (Object.prototype.hasOwnProperty.call(OPTS, k)) o[k] = OPTS[k]; }
    try {
      var r = parseFloat(getComputedStyle(el).borderTopLeftRadius);
      if (isFinite(r) && r > 0) o.radius = Math.max(6, Math.min(28, r));
    } catch (e) { /* дефолт библиотеки */ }
    return o;
  }

  function sync(enabled) {
    if (typeof document === 'undefined') return;
    if (!enabled) { disposeAll(); return; }
    var api = lib();
    if (!api) return;   // честный frost-fallback (CSS)
    var nodes = document.querySelectorAll(TARGETS);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.getAttribute('data-lg-mounted') === '1') continue;
      try {
        var inst = api.mountGlass(el, optsFor(el));
        var rec = { root: el, inst: inst };
        if (inst && typeof inst.dispose === 'function') rec.dispose = inst.dispose.bind(inst);
        mounted.push(rec);
        el.setAttribute('data-lg-mounted', '1');
      } catch (e3) {
        // не прерываем работу других целей; эффект честно отсутствует
        el.setAttribute('data-lg-failed', '1');
      }
    }
  }

  window.__LiquidGlass = { sync: sync, dispose: disposeAll };
})();
