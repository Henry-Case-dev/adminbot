# Scanner-аудит F2 `design-tokens-liquidglass-v2-round1025` (раунд 10.25, 21.09.2026)

- **Дифф:** `f2328fb..HEAD` (коммит `e895726`). Область: `web/static/app.css`, `web/index.html`
  (inline SVG `#lg-displace`), `web/app.js` (палитра §8, hidden-пауза §10, glass-страховка),
  `web/static/telegram-init.js`, `tools/ui_round1025_matrix.py`, `tools/ui_audit_round1021.py`,
  `config/settings.py`, `README.md`, новые тесты (`tests/test_webapp_design_tokens_round1025.py`,
  `tests/js/round1025_design_tokens_test.js`) + правки старых UI-тестов.
- **Вердикт: к деплою — ДА** (Critical 0 / High 0; Medium 3 — не блокеры, закрыть в следующем заходе).

## Цифры (факт)
- `python -m pytest -q`: **8096 passed / 0 failed** (106.03 s, 1 Starlette-warning).
- `tests/js/*`: **24/24 файла OK** (включая `round1025_design_tokens_test.js` → `JS-UNIT-OK`).
- Playwright-матрица `tools/ui_round1025_matrix.py` в этом аудите **не запускалась** (статический разбор F2-проб).
- Инварианты: Δ DDL=0, Δ каталога=0 (`tools/*.json|toml` не тронуты), `stash@{0}` (F1-WIP) цел,
  `git diff --check` = 0 (только LF/CRLF-предупреждения по незакоммиченным `plans/**`), zip/архивов в диффе нет.

## Medium
- **[M10.25F2-1] `web/app.js:8011-8027` — страховка уровня A необратима и не покрывает route-узлы.**
  `reconcileLiquidGlass` умеет только понижать `data-glass="a"` → `b` (`setAttribute`), апгрейд назад
  нигде не предусмотрен. `_onResize` (`app.js:2082-2084`) вызывает её на каждый resize, но после первого
  понижения элемент больше не матчится `[data-glass="a"]` → пересчёт мёртв. Плюс `reconcile` вызывается
  только в `mounted()` (`app.js:2107`) и на resize: `[data-glass="a"]` вкладки Сводка (`index.html:1375`,
  `activeTab==='oversight'`) в DOM на старте нет (default `activeTab:'status'`, `app.js:952`) → min-сторона
  ≥240px для неё не проверяется вовсе до случайного resize.
  *Сценарий:* открыть TMA на ~320px, свернуть/открыть Сводку, растянуть окно — элемент навсегда B.
  *Фикс:* хранить исходное намерение (класс `glass-a` или `data-glass-intent="a"`), переключать A↔B в обе
  стороны; вызывать reconcile после смены вкладки/route (watch на `activeTab`).
- **[M10.25F2-2] `web/app.js:7998-8009` — `_liquidGlassSupported` оптимистичен на WebKit (риск потери blur на iOS).**
  Проверка `CSS.supports('backdrop-filter','url(#lg-displace)')` на WebKit парсит значение, но reference-backdrop-filter
  при рендере отбрасывается целиком (WebKit PR #68614: `updateBackdropFilters()` short-circuit на `hasReferenceFilter()`,
  без fallback). Тогда `[data-glass="a"]` останется A, `@supports not(...url...)`-фолбэк (`app.css:999+`) не сработает,
  и панели `#lg-displace` (Сводка/Статус/граф познания) на iOS-Telegram (WKWebView) потеряют blur, который у уровня B есть.
  *Сценарий:* iOS Telegram → «Статус»/«Сводка» без стекла (плотность 0.5, читаемость падает).
  *Фикс:* gate по Blink/Chromium-UA (как в общепринятой практике детекта `backdropFilterUrl`) или иной детект
  реального рендера; на не-Blink оставлять B. Проверить на устройстве.
- **[M10.25F2-3] `web/app.css:916-924` + `web/index.html:1375/2713/2876` — цена преломления не измерена/M не отсекается.**
  `feTurbulence`+`feGaussianBlur`+`feDisplacementMap` в backdrop-filter пересчитывается каждый кадр, а под ним
  анимируется градиент (`body::before`) → это заметно дороже прежнего `blur(16px)`. Из-за [M-1] 240px-отсечка на
  этих узлах на мобиле фактически не работает. *Фикс:* оставить A максимум на одном узле и/или снять замер FPS
  (в матрицу добавить бюджет), либо включать A после измерения.

## Low
- **[L10.25F2-1] `web/static/app.css:701`** — `header.header-sticky` теперь `background: var(--glass-bg-strong)`
  (alpha 0.85) вместо прежних `rgba(22,22,22,0.96)`; header не входит в glass-set и blur не имеет → контент при
  скролле слегка просвечивает, что противоречит комментарию `app.css:693-694` («непрозрачнее card-solid»).
  *Фикс:* отдельный токен ~0.96 для шапки.
- **[L10.25F2-2] `tests/test_webapp_design_tokens_round1025.py:228`** — `assert "240" in APP_JS` тавтологичен
  (в `app.js` 6 вхождений «240»); ветка min-стороны в JS-тесте не покрыта (проверяется только `!okA`→B).
  *Фикс:* кейс элемент 100×100 при `okA=true` → ожидать `b`.
- **[L10.25F2-3] `tools/ui_round1025_matrix.py:_f2_failures`** — жёстко требует `"75s"`/`"105s"` в computed
  `animationDuration`, хотя токены валидируются диапазоном 60–90/90–120 → легальная смена значения даст ложный failure.
  *Фикс:* парсить секунды и сверять с диапазоном.
- **[L10.25F2-4] `README.md:5`** — «Тестов: 5936» устарело (фактически pytest 8096). *Фикс:* обновить число.

## Что чисто (проверено)
- **Регрессии:** F1 shell/safe-area/навигация, hotfix1–4 (панель/viewport, обложка, медиа, anti-cliche), F0 save-слой,
  Эпик 2 — не задеты (дифф не касается их файлов/листенеров). `IA_V2_ENABLED` в диффе отсутствует. Polling-пауза F8
  цела: `visibilitychange` объявлен ровно один раз, пауза фона — до ранних `return`'ов в `onVisibilityChange`.
- **CSP/zero-build:** только inline SVG, ровно один `id="lg-displace"`, нет внешних ссылок/data-URI/WebGL/библиотек;
  `filter id=` без `href="http..."`. `feDisplacementMap` применён через `backdrop-filter` (фон), а не `filter` —
  текст/кнопки внутри `[data-glass="a"]` не искажаются. `@supports`-фолбэки (уровень C без blur; уровень A → blur) корректны.
- **Производительность/стабильность:** blur viewport не анимируется (анимируются угол/позиция градиента);
  `lg-bg-paused` ставится одной веткой; `prefers-reduced-motion` гасит и фон (`animation:none`), и преломление A (`!important`, blur-only);
  SVG-дефы `width/height=0` + `position:absolute` + `aria-hidden` → нет layout shift; горизонтальный overflow ловится пробой `scrollWidth`.
- **Безопасность/секреты:** новых источников данных/эндпоинтов нет; в логах/скриншотах диффа R17 не затронут; секретов нет.
- **Тест-качество:** inventory-тесты сравнивают множества (потеря токена-маркера и OD4-литералов ловится,
  vendor исключён); маркеры не ослаблены (значения §8 pinned); матрица проверяет реальные computed-токены, диапазоны
  длительностей, allow/deny glass, reduced-motion и hidden-паузу; матрица достоверно ловит регресс `.bottom-nav{bottom:0}`
  (см. hotfix4: 56 failures vs 0).

## Замечания по тест-качеству (уже в Low) и открытые вопросы
- [M-2] требует проверки на реальном iOS-WebView (в CI не воспроизводимо).
- Точные значения 75s/105s в матрице противоречат собственному диапазонному чеку (L-3).
