/* HOTFIX9 (ADR-1025-17 D6, T-2820…T-2825): Dark Aurora Flow.
 * ОДИН полноэкранный canvas + лёгкий fragment shader (vendored OGL 1.0.11);
 * если WebGL/OGL недоступны или контекст потерян — честный Canvas2D-фолбэк.
 * Палитра UPD3 §10: bg #090D17, teal #42D6C4, blue #77A8FF, violet #A78BFA,
 * indigo #5C7CFA. 2–3 широкие мягкокрайние ленты; движение заметно за 5–10 с.
 *
 * CSP-safe: same-origin файл, без inline-скриптов/ассетов. Рендер стопается при
 * `document.hidden`, при `prefers-reduced-motion` рисуется один статичный кадр,
 * `webglcontextlost` → Canvas2D. Другие WebGL-сцены не создаются.
 */
(function () {
  'use strict';
  var PAL = {
    bg: [0.035, 0.051, 0.09],
    teal: [0.259, 0.839, 0.769],
    blue: [0.467, 0.659, 1.0],
    violet: [0.655, 0.545, 0.98],
    indigo: [0.361, 0.486, 0.98],
  };
  var state = {
    canvas: null, renderer: null, mesh: null, program: null,
    gl: null, ctx2d: null, raf: 0, running: false, mode: 'none',
    t0: 0, pause: false, reduced: false, lastFrame: 0, lost: false,
    ro: null,
  };

  function isMobile() {
    try { return (window.innerWidth || 9999) < 768; } catch (e) { return false; }
  }
  function dprCap() { return isMobile() ? 1.5 : 2; }
  function reducedMotion() {
    try {
      return !!(window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return false; }
  }

  var FRAG = [
    'precision mediump float;',
    'uniform vec2 uRes;',
    'uniform float uTime;',
    'void main(){',
    '  vec2 uv = gl_FragCoord.xy / uRes;',
    '  float aspect = uRes.x / max(uRes.y, 1.0);',
    '  vec2 p = vec2(uv.x * aspect, uv.y);',
    '  float t = uTime;',
    '  float b1 = exp(-pow((p.y - (0.62 + 0.14*sin(p.x*1.3 + t*0.20) + 0.05*sin(t*0.13))) * 4.2, 2.0));',
    '  float b2 = exp(-pow((p.y - (0.40 + 0.16*sin(p.x*1.05 - t*0.16 + 1.7) + 0.05*cos(t*0.10))) * 5.0, 2.0));',
    '  float b3 = exp(-pow((p.y - (0.76 + 0.10*sin(p.x*1.7 + t*0.11 + 3.1))) * 5.6, 2.0));',
    '  vec3 bg = vec3(0.035, 0.051, 0.09);',
    '  vec3 col = bg;',
    '  col += vec3(0.259, 0.839, 0.769) * b1 * 0.34;',
    '  col += vec3(0.467, 0.659, 1.000) * b2 * 0.30;',
    '  col += mix(vec3(0.655, 0.545, 0.980), vec3(0.361, 0.486, 0.980), 0.5) * b3 * 0.28;',
    '  gl_FragColor = vec4(col, 1.0);',
    '}',
  ].join('\n');
  var VERT = 'attribute vec2 position;\nvoid main(){ gl_Position = vec4(position, 0.0, 1.0); }';

  function ensureCanvas() {
    if (state.canvas && state.canvas.parentNode) return state.canvas;
    var cv = document.createElement('canvas');
    cv.id = 'aurora-flow-canvas';
    cv.className = 'aurora-flow-canvas';
    cv.setAttribute('aria-hidden', 'true');
    if (document.body && document.body.firstChild) {
      document.body.insertBefore(cv, document.body.firstChild);
    } else if (document.body) {
      document.body.appendChild(cv);
    }
    state.canvas = cv;
    return cv;
  }

  /* HOTFIX10 (ADR-1025-18 D5, T-2856/T-2857/T-2858): размер — по ФАКТИЧЕСКОМУ
   * размеру canvas-контейнера (элемент `position:fixed; inset:0`), а не по
   * `window.innerWidth/innerHeight`; при недоступности rect — визуальный
   * viewport, затем окно. Единицы согласованы: CSS-px для `setSize`, пиксели
   * drawing buffer (CSS-px × DPR) для `gl.viewport` и uniform `uRes`. */
  function measure() {
    // Канвас — `position:fixed; inset:0`, т.е. его контейнер = viewport
    // (`<html>`). Берём ФАКТИЧЕСКИЙ размер контейнера, а не canvas: OGL в
    // конструкторе выставляет inline 300×150, поэтому rect самого canvas
    // недостоверен на первом кадре.
    var de = document.documentElement;
    var w = de && de.clientWidth, h = de && de.clientHeight;
    if (!(w >= 1) || !(h >= 1)) {
      try {
        var r = (de && typeof de.getBoundingClientRect === 'function')
          ? de.getBoundingClientRect() : null;
        if (r && r.width >= 1 && r.height >= 1) { w = r.width; h = r.height; }
      } catch (e) { /* fallback ниже */ }
    }
    if (!(w >= 1)) w = window.innerWidth || 1;
    if (!(h >= 1)) h = window.innerHeight || 1;
    return { w: w, h: h };
  }

  function resize() {
    var cv = state.canvas;
    if (!cv) return;
    var m = measure();
    var w = Math.max(1, Math.round(m.w)), h = Math.max(1, Math.round(m.h));
    var dpr = Math.min(window.devicePixelRatio || 1, dprCap());
    var pw = Math.max(1, Math.round(w * dpr)), ph = Math.max(1, Math.round(h * dpr));
    if (state.renderer) {
      state.renderer.setSize(w, h);
      // Фактический drawing buffer после setSize (OGL ставит w*dpr); viewport и
      // uniform разрешения — из него, чтобы не оставалось старых размеров.
      var bw = cv.width || pw, bh = cv.height || ph;
      try {
        if (state.gl) state.gl.viewport(0, 0, bw, bh);
      } catch (e) { /* no-op */ }
      if (state.program && state.program.uniforms.uRes) {
        state.program.uniforms.uRes.value = [bw, bh];
      }
    } else {
      cv.width = pw; cv.height = ph;
      cv.style.width = w + 'px'; cv.style.height = h + 'px';
    }
  }

  /* Опциональный ResizeObserver по фактическому контейнеру: fullscreen/поворот
   * без window-resize (также страховка для TMA viewport). */
  function ensureResizeObserver() {
    if (typeof window.ResizeObserver === 'undefined' || state.ro) return;
    var de = document.documentElement;
    if (!de) return;
    try {
      state.ro = new window.ResizeObserver(function () { resize(); });
      state.ro.observe(de);
    } catch (e) { state.ro = null; }
  }

  function initGL(cv) {
    var OGL = window.OGL;
    if (!OGL || !OGL.Renderer || !OGL.Program || !OGL.Mesh || !OGL.Geometry) return false;
    try {
      var renderer = new OGL.Renderer({
        canvas: cv, dpr: Math.min(window.devicePixelRatio || 1, dprCap()),
        alpha: false, depth: false, stencil: false, antialias: false,
        preserveDrawingBuffer: true, powerPreference: 'low-power',
      });
      var gl = renderer.gl;
      gl.canvas.addEventListener('webglcontextlost', function (e) {
        e.preventDefault();
        state.lost = true; state.renderer = null; state.program = null;
        state.mesh = null; state.gl = null;
        // M-H9R-1: canvas, уже имевший WebGL-контекст, НЕ отдаёт 2D-контекст
        // (`getContext('2d')` → null). Поэтому монтируем СВЕЖИЙ canvas и
        // подменяем его в DOM — фолбэк реально рисует кадр, а не глохнет.
        if (!attach2dFallback()) return;
        resize();
        // Кадр рисуется всегда (в т.ч. на паузе/hidden/reduced-motion), чтобы
        // фон не пропадал; активный rAF-цикл продолжит рисовать сам.
        if (state.running && !state.pause
            && !(typeof document !== 'undefined' && document.hidden)) {
          if (!state.raf) {
            state.lastFrame = 0;
            state.raf = window.requestAnimationFrame(loop);
          }
        } else {
          draw((window.performance && performance.now)
            ? performance.now() : Date.now());
        }
      });
      var geometry = new OGL.Geometry(gl, {
        position: { size: 2, data: new Float32Array([-1, -1, 3, -1, -1, 3]) },
      });
      var program = new OGL.Program(gl, {
        vertex: VERT, fragment: FRAG,
        uniforms: { uTime: { value: 0 }, uRes: { value: [1, 1] } },
      });
      state.renderer = renderer;
      state.gl = gl;
      state.program = program;
      state.mesh = new OGL.Mesh(gl, { geometry: geometry, program: program });
      state.mode = 'webgl';
      return true;
    } catch (e) {
      state.renderer = null; state.gl = null; state.program = null; state.mesh = null;
      return false;
    }
  }

  function init2d(cv) {
    var ctx = cv.getContext('2d');
    if (!ctx) return false;
    state.ctx2d = ctx;
    state.mode = 'canvas2d';
    return true;
  }

  /* M-H9R-1: под 2D-фолбэк нужен СВЕЖИЙ canvas — старый уже владеет
     WebGL-контекстом и `getContext('2d')` на нём вернёт null. Подменяем
     элемент в DOM и получаем настоящий 2D-контекст. */
  function attach2dFallback() {
    var old = state.canvas;
    var cv = old;
    if (old && old.parentNode) {
      cv = document.createElement('canvas');
      cv.id = 'aurora-flow-canvas';
      cv.className = 'aurora-flow-canvas';
      cv.setAttribute('aria-hidden', 'true');
      old.parentNode.replaceChild(cv, old);
    }
    state.canvas = cv;
    state.gl = null;
    state.ctx2d = null;
    ensureResizeObserver();
    return init2d(cv);
  }

  /* L-H9S-1: полное снятие слоя фона (OFF): canvas убирается из DOM, чтобы
     «застывший» кадр не перекрывал legacy-wash; GL/2D-состояние сбрасывается,
     чтобы последующий start() поднял слой заново. */
  function detachCanvas() {
    if (state.ro) {
      try { state.ro.disconnect(); } catch (e0) { /* no-op */ }
      state.ro = null;
    }
    var cv = state.canvas;
    if (cv && cv.parentNode) {
      try { cv.parentNode.removeChild(cv); } catch (e) { /* no-op */ }
    }
    if (state.renderer && typeof state.renderer.destroy === 'function') {
      try { state.renderer.destroy(); } catch (e2) { /* no-op */ }
    }
    state.canvas = null;
    state.renderer = null; state.program = null; state.mesh = null;
    state.gl = null; state.ctx2d = null;
    state.mode = 'none'; state.lost = false;
  }

  function draw2d(t) {
    var cv = state.canvas, ctx = state.ctx2d;
    if (!cv || !ctx) return;
    var w = cv.width, h = cv.height;
    var g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, 'rgb(9,13,23)');
    g.addColorStop(1, 'rgb(13,20,36)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';
    var bands = [
      { y: 0.62, amp: 0.14, f: 1.3, sp: 0.20, ph: 0.0, col: 'rgba(66,214,196,0.34)' },
      { y: 0.40, amp: 0.16, f: 1.05, sp: -0.16, ph: 1.7, col: 'rgba(119,168,255,0.30)' },
      { y: 0.76, amp: 0.10, f: 1.7, sp: 0.11, ph: 3.1, col: 'rgba(140,140,250,0.28)' },
    ];
    for (var i = 0; i < bands.length; i++) {
      var b = bands[i];
      ctx.beginPath();
      var steps = 48;
      for (var s = 0; s <= steps; s++) {
        var x = (s / steps) * w;
        var u = (s / steps) * (w / Math.max(h, 1));
        var yy = (b.y + b.amp * Math.sin(u * b.f + t * b.sp + b.ph)
                  + 0.05 * Math.sin(t * 0.12 + i)) * h;
        if (s === 0) ctx.moveTo(x, yy); else ctx.lineTo(x, yy);
      }
      ctx.lineWidth = Math.max(24, h * 0.16);
      ctx.lineCap = 'round';
      ctx.strokeStyle = b.col;
      ctx.shadowColor = b.col;
      ctx.shadowBlur = Math.max(24, h * 0.08);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    ctx.globalCompositeOperation = 'source-over';
  }

  function draw(now) {
    if (!state.canvas) return;
    var t = (now - state.t0) / 1000;
    if (state.mode === 'webgl' && state.renderer && state.mesh) {
      try {
        state.program.uniforms.uTime.value = t;
        state.renderer.render({ scene: state.mesh });
      } catch (e) { /* если рендер упал — остаётся последний кадр */ }
    } else if (state.mode === 'canvas2d') {
      draw2d(t);
    }
  }

  function loop(now) {
    state.raf = 0;
    if (!state.running) return;
    if (state.pause || (typeof document !== 'undefined' && document.hidden)) return;
    // mobile: ориентир ~30 FPS (лёгкий режим), desktop — по кадру.
    var minDelta = isMobile() ? 33 : 0;
    if (!state.lastFrame || (now - state.lastFrame) >= minDelta) {
      state.lastFrame = now;
      draw(now);
    }
    state.raf = window.requestAnimationFrame(loop);
  }

  function start() {
    if (typeof document === 'undefined' || !document.body) return;
    if (state.running) return;
    var cv = ensureCanvas();
    state.reduced = reducedMotion();
    if (state.mode === 'none' || state.lost) {
      if (!initGL(cv) && !init2d(cv)) return;
    }
    resize();
    ensureResizeObserver();
    state.running = true;
    state.pause = false;
    state.t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    if (state.reduced) {
      draw(state.t0 + 4000);      // один качественный статичный кадр
      state.running = false;      // затем стоп
      return;
    }
    state.raf = window.requestAnimationFrame(loop);
  }

  function stop() {
    state.running = false;
    if (state.raf && window.cancelAnimationFrame) window.cancelAnimationFrame(state.raf);
    state.raf = 0;
    // L-H9S-1: OFF-фон не оставляет в DOM «застывший» кадр.
    detachCanvas();
  }

  /* Пиксельная проба для автопроверки §12 (кадры 0/5/10/20 с): 8×8 RGB-сетка
     из фактического framebuffer/canvas. Не влияет на рендер. */
  function sample() {
    var cv = state.canvas;
    if (!cv) return null;
    var N = 8, out = [];
    try {
      if (state.mode === 'webgl' && state.gl) {
        var gl = state.gl, w = cv.width, h = cv.height;
        var buf = new Uint8Array(w * h * 4);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
        for (var y = 0; y < N; y++) {
          for (var x = 0; x < N; x++) {
            var px = Math.min(w - 1, Math.floor((x + 0.5) * w / N));
            var py = Math.min(h - 1, Math.floor((y + 0.5) * h / N));
            var idx = (py * w + px) * 4;
            out.push([buf[idx], buf[idx + 1], buf[idx + 2]]);
          }
        }
      } else if (state.ctx2d) {
        var iw = cv.width, ih = cv.height;
        var img = state.ctx2d.getImageData(0, 0, iw, ih).data;
        for (var yy = 0; yy < N; yy++) {
          for (var xx = 0; xx < N; xx++) {
            var qx = Math.min(iw - 1, Math.floor((xx + 0.5) * iw / N));
            var qy = Math.min(ih - 1, Math.floor((yy + 0.5) * ih / N));
            var ii = (qy * iw + qx) * 4;
            out.push([img[ii], img[ii + 1], img[ii + 2]]);
          }
        }
      } else { return null; }
    } catch (e) { return null; }
    return out;
  }

  window.__AuroraFlow = {
    start: start, stop: stop,
    // HOTFIX10 (ADR-1025-18 D5, T-2857): публичный resize — пересчёт
    // setSize/buffer/viewport/uRes по фактическому контейнеру (fullscreen/
    // viewport-смена). Безопасен без canvas/renderer (no-op).
    resize: resize,
    setPaused: function (p) {
      state.pause = !!p;
      if (!state.pause && state.running && !state.raf) {
        state.lastFrame = 0;
        state.raf = window.requestAnimationFrame(loop);
      }
    },
    sample: sample,
    mode: function () { return state.mode; },
  };
})();
