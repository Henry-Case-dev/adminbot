/* HOTFIX10 (ADR-1025-18 D1, T-2843…T-2851): ОТКАТ точечного монтирования
 * vendored `@liquidglassjs/core` 0.5.3 с функциональных Vue-компонентов.
 *
 * Hotfix9 монтировал библиотеку напрямую на `.scope-trigger`, `.header-fs-btn`
 * и `.status-block` без настроенного источника преломления → авто-режим →
 * белый frosted-fallback (`.ps-glass__tint`), плюс `disposeAll` не удалял
 * созданные DOM-узлы. Здесь:
 *   * эффект применяется ТОЛЬКО к явно размеченному декоративному контейнеру
 *     `[data-glass-surface]` (без данных/контролов);
 *   * функциональные цели (селектор области / ⛶ / системная карточка) больше
 *     НЕ получают стекло;
 *   * `dispose` удаляет ВСЕ созданные библиотекой узлы `.ps-glass*` и атрибуты
 *     `data-lg-*` — идемпотентно;
 *   * честный режим: если источник преломления не предоставлен — это `frosted`,
 *     а не «рефракция» (определяется по фактическому слою `.ps-glass__refract`).
 *
 * CSP-safe: same-origin, без inline/eval. */
(function () {
  'use strict';
  // Единственная цель — изолированный декоративный контейнер GlassSurface.
  var SELECTOR = '[data-glass-surface]';
  var PS_SELECTOR = '.ps-glass, .ps-glass__surface, .ps-glass__tint,' +
    ' .ps-glass__rim, .ps-glass__refract, .ps-glass__refract-inner,' +
    ' .ps-glass__content, [class*="ps-glass"]';
  var OPTS = {
    strength: 12, edge: 0.8, chroma: 0.18, spec: 0.7, tint: 6, blur: 2,
  };
  var mounted = [];

  function lib() {
    return (window.LiquidGlass && typeof window.LiquidGlass.mountGlass === 'function')
      ? window.LiquidGlass : null;
  }

  function connected(el) {
    if (!el) return false;
    if (typeof el.isConnected === 'boolean') return el.isConnected;
    try { return document.documentElement.contains(el); } catch (e) { return false; }
  }

  /* Идемпотентное удаление ВСЕХ узлов, созданных библиотекой внутри root
   * (T-2845). Не трогает содержимое кнопок/карточек: root — только
   * `[data-glass-surface]`. */
  function purge(root) {
    if (!root || typeof root.querySelectorAll !== 'function') return;
    try {
      var nodes = root.querySelectorAll(PS_SELECTOR);
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (n && n.parentNode) n.parentNode.removeChild(n);
      }
    } catch (e) { /* no-op */ }
  }

  /* L-1 (round1025): библиотека ставит на root не только узлы `.ps-glass*`, но и
   * inline custom-properties `--g-*` (`--g-radius`/`--g-tint`/`--g-margin`/
   * `--g-glint-*`) и атрибуты (`data-glass`/`data-uid`/`data-render`/…).
   * Снимаем их вместе с нашими маркерами `data-lg-*`, иначе после dispose
   * остаётся «грязный» root с чужими стилями. */
  var LIB_ATTRS = [
    'data-lg-mounted', 'data-lg-failed', 'data-lg-mode',
    'data-glass', 'data-uid', 'data-render', 'data-glass-motion',
    'data-ps-loupe',
  ];

  function clearAttrs(root) {
    if (!root || typeof root.removeAttribute !== 'function') return;
    for (var a = 0; a < LIB_ATTRS.length; a++) {
      try { root.removeAttribute(LIB_ATTRS[a]); } catch (e) { /* no-op */ }
    }
    try {
      if (root.classList && root.classList.remove) root.classList.remove('ps-glass');
    } catch (e2) { /* no-op */ }
    try {
      var st = root.style;
      if (st && typeof st.removeProperty === 'function' && st.length != null) {
        var names = [];
        for (var i = 0; i < st.length; i++) {
          var nm = st.item ? st.item(i) : st[i];
          if (nm && nm.indexOf('--g-') === 0) names.push(nm);
        }
        for (var j = 0; j < names.length; j++) {
          if (names[j]) st.removeProperty(names[j]);
        }
      }
    } catch (e3) { /* no-op */ }
  }

  function unmountRec(rec) {
    if (!rec) return;
    try { if (typeof rec.dispose === 'function') rec.dispose(); }
    catch (e) { /* inst.dispose — лишь дополнительный путь */ }
    purge(rec.root);
    clearAttrs(rec.root);
  }

  /* Полное, идемпотентное снятие: снимаем ВСЕ смонтированные инстансы и
   * вычищаем оставшиеся узлы/атрибуты на любой размеченной поверхности. */
  function disposeAll() {
    for (var i = 0; i < mounted.length; i++) unmountRec(mounted[i]);
    mounted = [];
    if (typeof document === 'undefined' || !document.querySelectorAll) return;
    var left = document.querySelectorAll(SELECTOR);
    for (var j = 0; j < left.length; j++) {
      purge(left[j]);
      clearAttrs(left[j]);
    }
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

  /* Честный детект режима (T-2850): источник преломления считается
   * предоставленным только если библиотека реально создала слой преломления
   * (`.ps-glass__refract`). Иначе — `frosted` (никогда не называем рефракцией). */
  function detectMode(root) {
    try {
      if (root && root.querySelector &&
          root.querySelector('.ps-glass__refract, .ps-glass__refract-inner')) {
        return 'refraction';
      }
    } catch (e) { /* no-op */ }
    return 'frosted';
  }

  function sync(enabled) {
    if (typeof document === 'undefined') return;
    if (!enabled) { disposeAll(); return; }
    // 1) Снять стекло с узлов, которых больше нет в DOM (смена вкладки/роута) —
    // корректный unmount без «зависших» инстансов.
    for (var p = mounted.length - 1; p >= 0; p--) {
      var st = mounted[p];
      if (!st || !connected(st.root)) { unmountRec(st); mounted.splice(p, 1); }
    }
    var api = lib();
    if (!api) return;   // честный frost-fallback без библиотеки
    var nodes = document.querySelectorAll(SELECTOR);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.getAttribute('data-lg-mounted') === '1') continue;
      try {
        var inst = api.mountGlass(el, optsFor(el));
        var rec = { root: el, inst: inst };
        if (inst && typeof inst.dispose === 'function') rec.dispose = inst.dispose.bind(inst);
        mounted.push(rec);
        el.setAttribute('data-lg-mounted', '1');
        el.setAttribute('data-lg-mode', detectMode(el));
      } catch (e3) {
        // не прерываем работу других целей; эффект честно отсутствует
        el.setAttribute('data-lg-failed', '1');
      }
    }
  }

  window.__LiquidGlass = {
    sync: sync, dispose: disposeAll,
    mode: function () {
      for (var i = 0; i < mounted.length; i++) {
        try {
          if (mounted[i].root && mounted[i].root.getAttribute('data-lg-mode')) {
            return mounted[i].root.getAttribute('data-lg-mode');
          }
        } catch (e) { /* no-op */ }
      }
      return null;
    },
    targets: function () { return SELECTOR; },
  };
})();
