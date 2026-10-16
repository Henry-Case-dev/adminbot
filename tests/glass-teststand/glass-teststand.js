/* ═══ W2-GLASS: логика тестового стенда glass-teststand.html ═══
   CSP-safe IIFE: без Vue/inline. Публичные хуки для Playwright —
   window.__STAND = { probe(), setBg(name), toggleTier(), toggleReduced() }. */
(function () {
  'use strict';

  function $(sel) { return document.querySelector(sel); }

  function setBg(name) {
    var bgs = document.querySelectorAll('.stand-bg');
    for (var i = 0; i < bgs.length; i++) {
      bgs[i].classList.toggle('is-active',
        bgs[i].getAttribute('data-bg') === name);
    }
    var stage = document.querySelector('.stand-stage');
    if (stage) stage.setAttribute('data-active-bg', name);
  }

  function toggleTier() {
    var hero = $('#panel-hero');
    if (!hero) return;
    var cur = hero.getAttribute('data-glass-tier');
    hero.setAttribute('data-glass-tier', cur === 'a' ? 'b' : 'a');
  }

  function toggleReduced() {
    document.body.classList.toggle('stand-reduced');
  }

  /* W2-GLASS U08.3a: subregion feImage-карты = фактический размер панели
   * (проценты в скрытом svg = 0). Пул клонов #lg-lens, как в app.js. */
  function syncLensFilters() {
    var base = document.getElementById('lg-lens');
    if (!base) return;
    var heroes = document.querySelectorAll('[data-glass-tier="a"]');
    var pool = [];
    for (var i = 0; i < heroes.length; i++) {
      var el = heroes[i];
      var target = el.classList.contains('lg-panel')
        ? (el.querySelector('.lg-panel__backdrop') || el) : el;
      var r = el.getBoundingClientRect();
      var w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
      var fid = null, fe = null;
      for (var p = 0; p < pool.length; p++) {
        if (Math.abs(pool[p].w - w) <= 2 && Math.abs(pool[p].h - h) <= 2) {
          fid = pool[p].fid; fe = pool[p].fe; break;
        }
      }
      if (!fid) {
        var slot = pool.length;
        if (slot === 0) {
          fid = 'lg-lens'; fe = document.getElementById('lg-lens-map');
        } else {
          var clone = base.cloneNode(true);
          fid = 'lg-lens-stand-p' + slot;
          clone.setAttribute('id', fid);
          var cfe = clone.querySelector('feImage');
          if (cfe) cfe.setAttribute('id', 'lg-lens-map-stand-p' + slot);
          base.parentNode.appendChild(clone);
          fe = cfe;
        }
        pool.push({ fid: fid, fe: fe, w: w, h: h });
      }
      try {
        if (fe) {
          fe.setAttribute('x', '0'); fe.setAttribute('y', '0');
          fe.setAttribute('width', String(w));
          fe.setAttribute('height', String(h));
        }
        target.style.setProperty('-webkit-backdrop-filter',
          'blur(5px) saturate(140%) url(#' + fid + ')');
        target.style.setProperty('backdrop-filter',
          'blur(5px) saturate(140%) url(#' + fid + ')');
      } catch (e) { /* no-op */ }
    }
  }

  function init() {
    var controls = document.querySelectorAll('[data-set-bg]');
    for (var i = 0; i < controls.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          setBg(btn.getAttribute('data-set-bg'));
        });
      })(controls[i]);
    }
    var t = document.querySelector('[data-toggle-tier]');
    if (t) t.addEventListener('click', toggleTier);
    var r = document.querySelector('[data-toggle-reduced]');
    if (r) r.addEventListener('click', toggleReduced);

    setBg('grid');

    syncLensFilters();
    if (typeof ResizeObserver === 'function') {
      try {
        var ro = new ResizeObserver(function () { syncLensFilters(); });
        document.querySelectorAll('[data-glass-tier="a"]').forEach(function (el) {
          ro.observe(el);
        });
      } catch (e) { /* no-op */ }
    }

    // URL-параметры для детерминированных прогонов: ?bg=wave&tier=b&reduced=1
    try {
      var q = new URLSearchParams(window.location.search);
      if (q.get('bg')) setBg(q.get('bg'));
      if (q.get('tier') === 'b') {
        var hero = $('#panel-hero');
        if (hero) hero.setAttribute('data-glass-tier', 'b');
      }
      if (q.get('reduced') === '1') document.body.classList.add('stand-reduced');
    } catch (e) { /* no-op */ }

    var out = $('#stand-probe');
    if (window.__GlassProbe && typeof window.__GlassProbe.probe === 'function') {
      window.__GlassProbe.probe().then(function (res) {
        if (out) {
          out.textContent = 'probe: tierA=' + res.tierA + ' reason=' + res.reason +
            ' engine=' + res.engine + ' svg=' + res.svgRender +
            ' backdrop=' + res.backdrop + ' ' + res.ms + 'ms';
          out.setAttribute('data-tierA', String(res.tierA));
          out.setAttribute('data-reason', res.reason);
        }
      });
    } else if (out) {
      out.textContent = 'probe: __GlassProbe отсутствует';
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.__STAND = {
    setBg: setBg,
    toggleTier: toggleTier,
    toggleReduced: toggleReduced,
  };
})();
