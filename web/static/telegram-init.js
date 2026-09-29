/* F4 10.16 (ADR-1016-2 §2, T-1653): Telegram WebApp init вынесен из inline
 * <script> в index.html → CSP `script-src 'self'` без 'unsafe-inline'/nonce.
 * Загружается ПОСЛЕ /static/vendor/telegram-web-app.js и /web/app.js
 * (порядок как у прежнего inline-блока; app.mount уже выполнен).
 * Задание B (2026-09-03): тема миниаппа согласуется с тёмной темой админки;
 * setBottomBarColor — Bot API 7.10+ (guard). Саму инлайн-кнопку бота клиент
 * рисует по своей теме — из бота её цвет/форму изменить нельзя. */
(function () {
  if (!(window.Telegram && Telegram.WebApp)) return;
  var wa = Telegram.WebApp;
  var _tp = wa.themeParams || {};
  wa.ready();
  wa.expand();
  // F2 round 10.25 (ADR-1025-9 D1/T-2536): фолбэки темы → палитра §8
  // (Background #090D17 / Surface #151B2A) вместо прежних OD4-фолбэков.
  wa.setHeaderColor(_tp.header_bg_color || '#151B2A');
  wa.setBackgroundColor(_tp.bg_color || '#090D17');
  if (typeof wa.setBottomBarColor === 'function') {
    wa.setBottomBarColor(_tp.bottom_bar_bg_color || '#151B2A');
  }

  /* F1 round 10.25 (ADR-1025-1 D7/T-2399): прокидываем safe-area и стабильную
   * высоту вьюпорта в CSS-переменные (CSP-safe, без inline). CSS читает
   * max(env(safe-area-inset-*), var(--tg-*)) — значения Telegram точнее env. */
  var root = document.documentElement;
  function setVar(name, value) {
    if (value === undefined || value === null || value === '') return;
    root.style.setProperty(name, value + 'px');
  }
  /* hotfix6 (T-2593, AMEND ADR-1025-12 D3): нижний offset — МАКСИМУМ трёх
   * кандидатов (все описывают одну нижнюю «занятую» зону; сумма дала бы ложный
   * «задир» панели). A — разница layout/stable (hotfix4); B — Telegram UI снизу
   * (contentSafeAreaInset.bottom); C — системная зона (safeAreaInset.bottom).
   * Guard hotfix4 (stableH>0) сохранён. Клиенты без инсетов → 0 (панель на
   * bottom:0). Чистая функция — юнит-тестируема (window.__computeTgBottomOffset). */
  function computeBottomOffset(innerHeight, viewportStableHeight,
                               contentSafeAreaInsetBottom, safeAreaInsetBottom) {
    var a = 0;
    var ih = (typeof innerHeight === 'number' && innerHeight > 0) ? innerHeight : 0;
    if (ih > 0 && typeof viewportStableHeight === 'number' &&
        viewportStableHeight > 0) {
      a = Math.max(0, Math.min(ih, ih - viewportStableHeight));
    }
    var b = (typeof contentSafeAreaInsetBottom === 'number' &&
             contentSafeAreaInsetBottom > 0) ? contentSafeAreaInsetBottom : 0;
    var c = (typeof safeAreaInsetBottom === 'number' &&
             safeAreaInsetBottom > 0) ? safeAreaInsetBottom : 0;
    return Math.max(a, b, c);
  }
  window.__computeTgBottomOffset = computeBottomOffset;
  function applyInsets() {
    var sa = wa.safeAreaInset;
    if (sa) {
      setVar('--tg-safe-area-inset-top', sa.top);
      setVar('--tg-safe-area-inset-bottom', sa.bottom);
      setVar('--tg-safe-area-inset-left', sa.left);
      setVar('--tg-safe-area-inset-right', sa.right);
    }
    var csa = wa.contentSafeAreaInset;
    if (csa) {
      setVar('--tg-content-safe-area-inset-top', csa.top);
      setVar('--tg-content-safe-area-inset-bottom', csa.bottom);
      setVar('--tg-content-safe-area-inset-left', csa.left);
      setVar('--tg-content-safe-area-inset-right', csa.right);
    }
    if (typeof wa.viewportStableHeight === 'number') {
      setVar('--tg-viewport-stable-height', wa.viewportStableHeight);
    }
    /* hotfix6 (T-2593): offset = max(hotfix4-разница, contentSafeAreaInset.bottom,
     * safeAreaInset.bottom) — учитываем Telegram UI снизу, а не только системный
     * бар. Пересчёт на всех ниже-подписках + resize (страховка от «залипания»). */
    var offset = computeBottomOffset(
      window.innerHeight || 0,
      wa.viewportStableHeight,
      csa ? csa.bottom : 0,
      sa ? sa.bottom : 0);
    setVar('--tg-viewport-bottom-offset', offset);
    /* HOTFIX9 (ADR-1025-17 D1, T-2794/T-2796): ЕДИНЫЙ источник высоты shell.
     * ── ASAP-3.1 (T-4083, §92/§93, ADR-1028-3 D8/Q6): ОДНА модель геометрии ──
     * Паттерн «innerHeight минус guessed bottom offset» УХОДИТ (он и давал
     * clipping, переживший несколько hotfix'ов: innerHeight ≠ реально видимая
     * область на части Telegram/WebView). Новая модель:
     *   shell height = ФАКТИЧЕСКИ видимая высота вьюпорта
     *     (в Telegram: viewportStableHeight в покое; при открытой клавиатуре —
     *      viewportHeight; вне Telegram: visualViewport.height + offsetTop;
     *      fallback innerHeight),
     *   нижний inset применяется РОВНО ОДИН РАЗ — на самом `.bottom-nav`
     *     (padding-bottom в CSS), main — flex-1, единственный scroll
     *     container. Инварианты §94 (nav полностью видима, labels не
     *     перекрыты, main не под nav) выполняются структурно. */
    var stableH = (typeof wa.viewportStableHeight === 'number' &&
                   wa.viewportStableHeight > 0) ? wa.viewportStableHeight : 0;
    var curH = (typeof wa.viewportHeight === 'number' && wa.viewportHeight > 0)
      ? wa.viewportHeight : 0;
    var tgVisible = 0;
    if (stableH > 0) {
      // Клавиатура/сжатие: текущая высота заметно меньше стабильной →
      // видимая = текущая (панель остаётся на экране над клавиатурой).
      tgVisible = (curH > 0 && curH < stableH - 40) ? curH : stableH;
    } else {
      tgVisible = curH;
    }
    var vv = window.visualViewport;
    var vvVisible = (vv && typeof vv.height === 'number' && vv.height > 0)
      ? (vv.height + (typeof vv.offsetTop === 'number' ? vv.offsetTop : 0))
      : 0;
    var innerH = window.innerHeight || 0;
    // Источник: Telegram (есть viewport-переменные) → вне Telegram
    // visualViewport → innerHeight (§92).
    var visible = (stableH > 0 || curH > 0)
      ? (tgVisible || vvVisible || innerH)
      : (vvVisible || innerH);
    if (!(visible > 0)) visible = innerH;
    setVar('--app-usable-height', Math.max(0, visible));
    /* hotfix6-переменная сохранена ТОЛЬКО для legacy-отката
     * (UI_SHELL_FLEX_V3=OFF: fixed-панель с компенсацией offset). Новая
     * модель её НЕ читает (второго вычета нет, §92/§115). */
    var offset = computeBottomOffset(
      window.innerHeight || 0,
      wa.viewportStableHeight,
      csa ? csa.bottom : 0,
      sa ? sa.bottom : 0);
    setVar('--tg-viewport-bottom-offset', offset);
  }
  /* HOTFIX9 (T-2800/T-2808/Low): клавиатура/визуальный вьюпорт меняет видимую
   * высоту — пересчитываем `--app-usable-height`, чтобы активное поле и
   * SaveBar оставались в экране. Только пересчёт единого источника. */
  function scrollActiveModalField() {
    /* D3 spec: активное поле внутри модалки приводится в видимость
       (`scrollIntoView({block:'nearest'})`); логика сохранения не затрагивается. */
    try {
      var el = document.activeElement;
      if (!el || typeof el.closest !== 'function') return;
      var tag = (el.tagName || '').toLowerCase();
      if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') return;
      if (!el.closest('.modal-body')) return;
      if (typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ block: 'nearest' });
      }
    } catch (e) { /* no-op */ }
  }
  function applyInsetSafe() {
    try { applyInsets(); } catch (e) { /* no-op */ }
    scrollActiveModalField();
  }
  applyInsets();
  if (typeof wa.onEvent === 'function') {
    wa.onEvent('viewportChanged', applyInsetSafe);
    wa.onEvent('safeAreaChanged', applyInsetSafe);
    wa.onEvent('contentSafeAreaChanged', applyInsetSafe);
  }
  /* hotfix4 (T-2516): пересчёт на resize окна/повороте — страховка, если
   * клиент не прислал Telegram-событие (offset не должен «залипать»). */
  if (typeof window.addEventListener === 'function') {
    window.addEventListener('resize', applyInsetSafe);
  }
  /* HOTFIX9 (T-2800): изменение visualViewport (экранная клавиатура) —
   * пересчёт единого `--app-usable-height`; layout не «уезжает». */
  if (window.visualViewport && typeof window.visualViewport.addEventListener === 'function') {
    window.visualViewport.addEventListener('resize', applyInsetSafe);
    window.visualViewport.addEventListener('scroll', applyInsetSafe);
  }

  /* F1 (UPD §8.4): BackButton show/hide управляет app.js (syncBackButton);
   * здесь только гарантируем корректный старт состояния — скрыт на корне. */
  if (wa.BackButton && typeof wa.BackButton.hide === 'function') {
    wa.BackButton.hide();
  }
})();
