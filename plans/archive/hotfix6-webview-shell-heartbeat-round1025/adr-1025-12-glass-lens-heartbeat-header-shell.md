# ADR-1025-12 — Кросс-движковое преломление без `backdrop-filter: url()`, стекло панелей, компенсация `contentSafeAreaInset.bottom`, Canvas-2D сердцебиение, компоновка шапки

- **Статус:** Proposed → **Approved** (Шаг 5 @Reviewer итер.2, 12/12 закрыто; Шаг 6 @Scanner — Critical 0 / High 0) → **MERGED в карту архитектуры (Шаг 7 @Architect, `plans/ARCHITECTURE.md` §58)** → **Accepted** (MERGED §58 + **DEPLOYED**, Шаг 9 @DevOps, 22.09.2026: коммиты `055525c` + `ba75751`, `APP_VERSION` **2.58.7**, `/api/health`=200, `database is locked`=0; ⏳ live-гейт владельца T-2617 открыт).
- **Дата:** 2026-09-22
- **Раунд:** 10.25, внеплановый **хотфикс-6** `hotfix6-webview-shell-heartbeat-round1025` (T-2581…T-2618)
- **Связано:** `spec.md` этой папки; ТЗ §5/§7/§8/§9/§10/§14/§15/§71/§116/§117; `plans/ARCHITECTURE.md` §56/§57 (+ §604/§642); ADR-1016-2 (CSP/zero-build), ADR-1024-13 (`ui_flags`), ADR-1024-24 (fullscreen-sync), ADR-1025-1 (F1 shell), ADR-1025-8 (hotfix4 viewport), ADR-1025-9 (F2 glass), ADR-1025-10 (F3 selector)
- **Затрагивает:** `web/static/app.css`, `web/index.html`, `web/static/telegram-init.js`, `web/app.js`, `config/settings.py` (`APP_VERSION` + env-only `ClassVar`-флаги), `tools/ui_round1025_matrix.py`, тесты (`tests/**`, `tests/js/**`), опц. аддитивно `services/status_service.py`

## Контекст

Живая приёмка владельца после деплоя Волны 1 (`4cde1bc`, `APP_VERSION` 2.58.6) выявила четыре прод-деградации:

- **A.** Liquid Glass без реального преломления; панели меню (sidebar/drawer) и шапка — без стекла. Корень (проверено по коду): уровень A — это opt-in `[data-glass="a"]` всего на 3 узлах (`index.html:1420/2762/2930`); механизм опирается на `backdrop-filter: url(#lg-displace)` (`app.css:967-968/1057-1062`), который **прямо запрещён ТЗ §9** как единственная опора, в WKWebView не реализован, в Chromium нестабилен; UA-gate Blink-only (`app.js:8109-8110`) отсекает все WKWebView (и пропускает iOS Edge — NEW-L1); min-240 (`app.js:8134`) не пускает A на низкие панели; карта смещения — **равномерный** `feTurbulence` (`index.html:39-43`), тогда как §9 требует «сильнее у краёв, слабее в центре». Панели (`.app-sidebar` `app.css:1457`, `.app-drawer` `:1477`, `.bottom-nav` `:1499`, `.more-sheet` `:1546`) — непрозрачный `--surface-1`; `header.header-sticky` (`:745-752`) — `--glass-bg-strong` без blur (F2 L10.25F2-1).
- **B.** Нижняя панель на мобильном всё ещё уходит за нижний край: `--tg-viewport-bottom-offset = max(0, innerHeight − viewportStableHeight)` (`telegram-init.js:52-60`) не учитывает `contentSafeAreaInset.bottom`.
- **C.** Сердцебиение §15 — статичный SVG с циклической подсветкой (`.ekg-trace`, `app.css:813-823`), а нужен реальный **Canvas 2D + rAF** с состояниями и источниками; на мобильном переполняет экран.
- **D.** Шапка: один `flex-wrap`-ряд; ⛶ (`index.html:195-197`) в `.ml-auto`-группе не гарантированно на уровне нативных кнопок Telegram; плотная группа селектор/бейдж/аватар/роль; `main.scroll-area` (`app.css:763-765`) без резерва под sticky-шапку; fullscreen (ADR-1024-24) не работает.

Инварианты: **Δ DDL=0, Δ каталога=0, CSP/zero-build, запрет WebGL (Canvas 2D разрешён), env-only UI-флаги, нативные кнопки Telegram CSS не двигать, R17/R18.** Значительная часть эффекта **не воспроизводима headless**.

Ключевое техническое наблюдение, определяющее D1: **`filter: url(#…)` на foreground-элементе реализован и в Blink, и в WebKit**, в отличие от `backdrop-filter: url(#…)` (WebKit не поддерживает). Значит, преломление надо выполнять на **отдельном слое**, а не на backdrop.

## Решение

### D1 (A1). Преломление через «линза-слой» (foreground `filter: url()`), edge-weighted, без `backdrop-filter: url()`

- **Механизм.** Узел уровня A = stacking-context (`position:relative; isolation:isolate`); линза — декоративный **псевдо-элемент `[data-glass="a"]::before`** (`position:absolute; inset:0; z-index:-1; pointer-events:none; border-radius:inherit`; отдельного класса `.lg-lens` в реализации НЕТ), несущий градиент-реплику фона (токены `--grad-*`) и `filter: url(#lg-lens)` (id inline-SVG-фильтра, `--glass-displace`). Контент — `z-index:1` относительно линзы → **текст и кнопки не искажаются**. Реальная «прозрачность» панели — от `backdrop-filter: blur() saturate()` (**blur**, не url) + кромка/блик/тень. A перестаёт зависеть от `backdrop-filter: url()`.
- **Edge-weighted карта.** Основная весовка — **CSS radial-mask на линзе** (`radial-gradient`: центр прозрачен 0–52 %, плотно к краям 78–100 %) → в центре искажения нет, у краёв — максимум (буквально §9), равномерный «шум» исчезает. Вектор смещения даёт SVG `feDisplacementMap` малой амплитуды (`scale` ≈ 8…12) поверх сглаженной низкочастотной `feTurbulence`. `feImage`/data-URI-градиент **не используем** (CSP/нестабильность).
- **Лестница A→B→C по feature-detect (не по UA).** A: `CSS.supports('filter','url(#lg-lens)')` ∧ allow-list панелей/крупных виджетов ∧ не deny-list ∧ бюджет ∧ не reduced-motion. B: glass-set карточек/модалок или A недоступен → blur+кромка+блик. C: deny-list §9 или `@supports not (backdrop-filter: blur)` → плотная подложка. **UA-gate Blink-only снимается** (закрывает F2 M-2 и NEW-L1). **min-240 заменяется перф-капом**: allow-list панелей + `UI_LENS_MAX_NODES` (default 6), deny-list неизменен; понижение обратимо/транзитивно через `data-glass-downgraded` без перезаписи opt-in.
- **SVG-фильтр — один inline** `<svg>` в `web/index.html` (CSP-safe, без data-URI/внешних ресурсов). `backdrop-filter: url(...)` удаляется из `web/**` (grep-инвариант).
- **Перф/motion:** один линза-слой на панель; пауза по `document.hidden` (в существующий `onVisibilityChange`/`setBgPaused`, без второго обработчика); **`prefers-reduced-motion: reduce` → tier B** (осознанное решение: дорогое `filter: url()`-преломление не применяется, `reconcileLiquidGlass` ставит `data-glass-downgraded`/`reason=reduced-motion`; остаётся статичная blur-подложка B — линза отключена, состояние отражено цветом/подписью); `UI_GLASS_TIER_OVERRIDE=b` как ручной откат.
- **Честность:** это **приближение** оптического преломления (векторное поле + радиальная весовка), а не физическая рефракция; документируется в коде/ADR.

**Почему:** единственный способ дать видимое преломление кросс-движково и без запрещённой опоры; сохраняет §9 (выборочность, не искажать текст, не шум); обратим и управляем перфом.

### D2 (A2). Стекло на панелях + контраст ≥ AA 4.5:1 + осознанный fallback

- Панели `.app-sidebar`/`.app-drawer`/`header.header-sticky`/`.bottom-nav`/`.more-sheet` входят в glass-set: подложка `--glass-bg` + blur (tier A/B), кромка/блик/тень. Шапка получает **blur** (закрывает L10.25F2-1) и держит плотный `--glass-bg-strong` для читаемости поверх произвольного прокручиваемого контента.
- **Контраст:** метод ADR-1025-9 D4 — считать композит `glass-bg` поверх худшего фона; обязательна таблица «пара → эффективный фон → ratio → PASS/FAIL» для каждого класса текста панели (`.75rem`/10 px — нормальный текст, порог 4.5:1). При провале — повышать **плотность подложки**, **не** менять палитру §8.
- **Fallback:** `@supports not ((backdrop-filter: blur(1px)))` (и `-webkit-`) → tier C (`--glass-bg-strong`, без blur) для всех панелей; контраст/раскладка сохраняются. Deny-list §9 нетронут. Тач-цели ≥44×44 сохранены.

### D3 (B). Полная компенсация `contentSafeAreaInset.bottom`

- `telegram-init.js` вычисляет единую переменную из трёх кандидатов нижней «занятой» зоны: `--tg-viewport-bottom-offset = max(A, B, C)`, где `A = max(0, innerHeight − viewportStableHeight)`, `B = contentSafeAreaInset.bottom`, `C = safeAreaInset.bottom`. Дополнительно сохраняются `--tg-content-safe-area-inset-bottom`/`--tg-safe-area-inset-bottom` для `padding-bottom` панели.
- **Почему max, не сумма:** величины пространственно перекрывают одну зону; сумма давала бы ложный «задир» панели. При подтверждении разных баров на live — переключение на сумму одной строкой (зафиксировано).
- Пересчёт на `viewportChanged`/`safeAreaChanged`/`contentSafeAreaChanged` (уже подписаны) + `resize`; guard `stableH>0` сохранён. Клиенты без инсетов → offset 0 (панель на `bottom:0`, бара нет), без фикс-высот.
- **Проверяемость:** чистая функция `computeBottomOffset(...)` с JS-юнитом; матрица требует `rect.bottom <= innerHeight+1`/`stableHeight` при **симулированном** баре (FAIL иначе). Реальные инсеты — только live-гейт.
- **Порядок навигации F1/hotfix4 не меняется** (`bottomNavItems`: `Статус`+`Справка` первыми, ≤4, «Ещё» без дубля).

### D4 (C2). Сердцебиение §15: Canvas 2D + rAF, телеметрия отдельно, без роста нагрузки

- SVG заменяется `<canvas>` + `requestAnimationFrame` (`getContext('2d')`, WebGL запрещён). Рендер только рисует снимок; **сеть в кадре отсутствует**; `canvas.width/height = CSS×DPR`, CSS `width:100%; max-width:100%`.
- **Телеметрия отдельно:** источник — существующий `GET /api/status` (`status_service.py:396-411/580-608`), уже опрашиваемый каждые **30 с** (`app.js:6364-6368`). Компонент подписывается на изменение `statusData`; **новый поллер не вводится** (30 с ∈ §15 10–30 с) → нагрузка не растёт. Возможное 10–15 с — через существующий `statusTimer` (будущее, не в этом пакете).
- **Источники → состояния:** доступность бота (`bot.state`/uptime), CPU (`cpu_percent`/`loadavg[0]/cpu_count`), RAM (`memory.percent`), диск (`disk.percent`), крит. процессы (`bot.state` + `process`), актуальность (`generated_at`). Нет поля/устарело/ошибка → **UNKNOWN** (не 0). `server.*` — «весь сервер» (§14), при выбранном чате с пометкой.
- **Состояния/гистерезис:** HEALTHY/WARNING/CRITICAL/UNKNOWN различаются цветом/интенсивностью/частотой/амплитудой/характером; пороги фронт-константы (WARNING ≥0.70, CRITICAL ≥0.90 или `state≠running`); гистерезис (enter 0.70/exit 0.65; enter 0.90/exit 0.85) + dwell; EMA-сглаживание. **Без выдуманного BPM** — частота/амплитуда выводятся из состояния и измеренных метрик.
- **Тултип hover/tap:** CPU/RAM/диск/статус/время обновления/**причина**; доступен desktop и mobile; не перекрывает системные элементы; a11y (`aria-label`/`aria-describedby`, фокусируемость).
- **reduced-motion:** статичный кадр, состояние корректно. **C1:** `.status-block`/канвас ограничены по ширине, на мобильном — **отдельная горизонтальная область**; `scrollWidth <= clientWidth`, без общего overflow.
- **Жизненный цикл:** старт при данных и видимости; пауза по `document.hidden` (в существующий `onVisibilityChange`); останов в `beforeUnmount`; вне Canvas-окружения — деградация на SVG. `UI_HEARTBEAT_CANVAS_ENABLED` (default ON): OFF → прежний SVG байт-в-байт.

### D5 (D). Компоновка шапки: native-safe-area, отдельная строка, резерв высоты, рабочий fullscreen

- **D1 (⛶):** ⛶ и правая служебная зона — в правом верхнем углу, визуально на уровне нативных кнопок. Так как нативные кнопки **вне DOM**, выравнивание достигается **резервом safe-area-зон** (`max(env(safe-area-inset-top), --tg-safe-area-inset-top, --tg-content-safe-area-inset-top)` + база), а не сдвигом нативных кнопок. Тач-цель ≥44×44; при невозможности одной строки — ближайшее безопасное положение без наложений. **Нативные кнопки CSS не двигать** (§604/§642/§56).
- **D2:** селектор области, бейдж `chat_id`, аватар и роль — в **отдельную компактную строку**; при нехватке ширины — `ellipsis`, второстепенное в `<details class="scope-tech">`, полный `chat_id` — только в техподробностях (паритет F3/§5).
- **D3:** `main.scroll-area` получает корректный резерв высоты через токен `--header-h` (ResizeObserver + CSS-фолбэк) → верх контента не подлезает под sticky-шапку, без «магических» ширинозависимых отступов.
- **D4 (mobile):** компактная шапка; селектор области **постоянно доступен** (`min-w-0`+`truncate`); без горизонтального скролла и перекрытия системных кнопок.
- **D5 (fullscreen):** сохранить контракт **ADR-1024-24** (источник истины — TMA; флаг не угадывается; событийная синхронизация). Починить реализацию (`app.js:4631-4713`): доступность `requestFullscreen`/`exitFullscreen`, фактическое обновление `isFullscreen`, отложенный re-read, попадание клика по ⛶ в двухстрочной шапке. Иконка/состояние синхронизированы. Проверка — реальный WebView.
- **Совместимость:** при `IA_V2_ENABLED=false` шапка байт-в-байт legacy; `UI_HEADER_COMPACT_V2` действует только в IA v2. F1 shell/safe-area и F3-селектор/guard не ломаются.

### D6. Флаги (env-only, default ON, Δ каталога=0) и раскатка

`UI_GLASS_TIER_OVERRIDE ∈ {auto,a,b,c}` (default `auto`); `UI_HEARTBEAT_CANVAS_ENABLED` (bool, ON); `UI_HEADER_COMPACT_V2` (bool, ON); `UI_LENS_MAX_NODES` (int, 6). Доставка — `GET /api/me.ui_flags` (`web/api/routes.py:351-383`). Каждый флаг = независимый откат своей области; лишние UI-флаги не вводим. Progressive delivery (10/50/100 %) не применяется (один прод, §53–§56); «поставка» = bump `APP_VERSION` 2.58.6 → 2.58.7 + cache-bust.

## SUPERSEDE / AMEND

- **SUPERSEDE (перенос области):** §15 «Живое сердцебиение» **исключается из F11** `status-showcase-dashboard-round1025` и реализуется здесь (C2). В F11 остаются §12/§13/§14/§16–§21.
- **AMEND ADR-1025-9 D2:** уровень A — механизм **без `backdrop-filter: url()`** (foreground-линза), кросс-движковый feature-detect вместо UA-gate Blink-only, min-240 → перф-кап, edge-weighted карта (radial-mask). Палитра §8 (D1) и фон §10 (D3) ADR-1025-9 — **не отменяются**.
- **AMEND ADR-1025-8 / hotfix4 D2:** offset = `max(hotfix4-offset, contentSafeAreaInset.bottom, safeAreaInset.bottom)`; порядок навигации и `viewport-fit=cover` сохраняются.
- **AMEND ADR-1025-10 (F3) и ADR-1025-1 (F1):** селектор/бейдж/аватар/роль — в отдельную компактную строку; перекомпоновка шапки. Семантика F3 (DELETE override ≠ factory-reset, guard, stale-epoch) — **не отменяется**.
- **Закрывает:** F2 L10.25F2-1 (header blur — D2); F2 M-3 (перф-кап/бюджет — D1); F2 M-2 + NEW-L1 (WebKit/iOS Edge — D1, feature-detect вместо UA).
- **ADR-1024-24** (fullscreen-sync) — **не отменяется**; D5 чинит реализацию.
- **Не отменяется:** CSP/zero-build; палитра §8; механика фона §10; порядок навигации F1/hotfix4; save-path F0.

## Последствия

**Positive:** кросс-движковое преломление без запрещённой опоры; честная лестница A→B→C; панели становятся стеклянными с гарантией AA; нижняя панель целиком в экране; §15 реализован как реальный Canvas-2D-компонент с честными источниками; шапка — единая композиция без наложения на контент и без сдвига нативных кнопок; сохраняется полный контракт fullscreen-sync.

**Negative/издержки:** преломление — документированное приближение (не физика); `filter: url()` дороже blur → перф-кап и tier-override; ручная AA-таблица на панелях; часть эффектов проверяется только на реальном устройстве; атомарное обновление эталонов F2/F3/hotfix4.

**Ограничения:** Δ DDL=0, Δ каталога=0; без новых зависимостей/WebGL; `services/**` меняется только аддитивно (при необходимости — `/api/status`); CSP/zero-build соблюдены.

## Альтернативы

| Альтернатива | Почему отклонена |
|---|---|
| Оставить `backdrop-filter: url()` и расширить UA-gate | Прямо нарушает §9; WKWebView не поддержит; сохраняет корень бага |
| WebGL-рефракция на карточку | Запрещена инвариантом; «не на каждой карточке» |
| Canvas-2D-рефракция на каждую панель | Дорого, дублирует контент, риск нестабильности |
| `feImage`/data-URI-градиент как карта | CSP-риск, нестабильность ссылок в движках |
| Оставить min-240 и просто расширить allow-список | Низкие панели (`header`/`bottom-nav`) всё равно не получат A |
| Сумма A+B+C для нижнего offset | Двойной учёт одной зоны → ложный «задир» панели; выбран `max` |
| Отдельный поллер heartbeat 10 с | Рост нагрузки без необходимости; 30 с ∈ §15 и уже есть |
| Chart-библиотека для heartbeat | §15 предпочитает Canvas 2D; меньше поверхности/зависимостей |
| Двигать нативные кнопки CSS | Невозможно (вне DOM) и запрещено §604/§642/§56 |

## Верификация

- **Headless (Playwright §71, 10 вьюпортов + низкое окно Desktop):** отсутствие `backdrop-filter: url(` в `web/**`; детерминированный выбор tier; панели в glass-set; контраст-пробы AA; `rect.bottom <= innerHeight+1`/`stableHeight` при симулированном баре; heartbeat — canvas присутствует, `scrollWidth<=clientWidth`, нет общего overflow, reduced-motion → статика; композиция шапки — ⛶ вне зоны native-кнопок, резерв высоты, без горизонтального скролла.
- **JS/node-юниты:** `computeBottomOffset` (A/B/C/max/guard/нули/мусор); state-machine heartbeat (пороги/гистерезис/UNKNOWN-при-отсутствии/reduced-motion/отделение телеметрии); выбор tier.
- **Red→green:** тесты падают на старом коде (SVG-heartbeat, `backdrop-filter: url()`, старый offset).
- **Инварианты:** Δ DDL=0, Δ каталога=0, `node --check web/app.js` OK, `git diff --check` exit 0; полный pytest 8146/5/1 + новые; JS-набор зелёный.
- **Только реальный Telegram WebView (владелец, T-2617):** преломление и стекло панелей/шапки; панель целиком в экране; heartbeat (Canvas 2D/состояния/тултип/перф); ⛶ на уровне native-кнопок и рабочий fullscreen; регрессии F0–F3/hotfix* = 0; консоль TMA без `ReferenceError`.
- **Не воспроизводимо headless (зафиксировать):** WKWebView `filter: url()`, реальные `safeAreaInset`/`contentSafeAreaInset`, геометрия native-кнопок, реальный fullscreen, FPS на устройстве.

## Откат

Тег `pre-round1025-hotfix6` (T-2581) + `git revert` коммитов пакета + возврат `APP_VERSION`/`?v=`; мягкие откаты — env-флаги `UI_GLASS_TIER_OVERRIDE=b`, `UI_HEARTBEAT_CANVAS_ENABLED=false`, `UI_HEADER_COMPACT_V2=false` (без редеплоя кода). Бэкапы/теги/`stash@{0}` не удалять (R18).
