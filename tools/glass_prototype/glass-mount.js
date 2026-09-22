/* Прототип T-2814/T-2815/T-2816 (ADR-1025-17 D5).
 * Реальный фон — отдельный canvas ПОЗАДИ стекла (не слой внутри .ps-glass).
 * `?bg=A|B` сдвигает паттерн: сравнение кадров доказывает, что стекло читает
 * содержимое ПОЗАДИ, а не фильтрует собственный декоративный слой. */
(function () {
  var p = new URLSearchParams(window.location.search);
  var offset = (p.get('bg') === 'B') ? 60 : 0;
  var cv = document.getElementById('scene');
  function draw() {
    var w = cv.width = window.innerWidth;
    var h = cv.height = window.innerHeight;
    var ctx = cv.getContext('2d');
    var g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, '#090D17');
    g.addColorStop(1, '#0d1424');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    var colors = ['#42D6C4', '#77A8FF', '#A78BFA', '#5C7CFA'];
    var r = 46;
    ctx.globalAlpha = 0.85;
    for (var y = -r; y < h + r; y += r) {
      for (var x = -r; x < w + r; x += r) {
        var i = Math.round(x / r) + Math.round(y / r);
        ctx.beginPath();
        ctx.arc(x + offset, y, r * 0.42, 0, Math.PI * 2);
        ctx.fillStyle = colors[((i % 4) + 4) % 4];
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#ffffff';
    ctx.font = '16px monospace';
    ctx.fillText('BEHIND-' + (offset ? 'B' : 'A'), 24 + offset, 40);
  }
  draw();
  window.addEventListener('resize', draw);
  window.__protoDraw = draw;

  var root = document.querySelector('.ps-glass');
  window.__glassMounted = false;
  window.__glassError = null;
  if (window.LiquidGlass && typeof LiquidGlass.mountGlass === 'function' && root) {
    try {
      var opts = {};
      try { opts = JSON.parse(root.getAttribute('data-lg-opts') || '{}'); }
      catch (e2) { opts = {}; }
      window.__glass = LiquidGlass.mountGlass(root, opts);
      window.__glassMounted = true;
    } catch (e) {
      window.__glassError = String(e);
    }
  } else {
    window.__glassError = 'library-or-root-missing';
  }
})();
