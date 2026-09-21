# Хотфикс-6 `hotfix6-webview-shell-heartbeat-round1025` — локальная спецификация (Шаг 2 @Architect)

> **Статус:** 🟦 **DESIGN (Step 2 @Architect, 22.09.2026)** — гейт перед реализацией A/B/C/D. Создаётся как `spec.md` + **ADR-1025-12** (`adr-1025-12-glass-lens-heartbeat-header-shell.md`). PM эти артефакты не создаёт.
> **Рамка:** `tasks.md` (**T-2581…T-2618, 38 задач**). Настоящая спека **не переписывает** задачи — она задаёт контракты, по которым они реализуются.
> **Базовая линия:** HEAD `441e8f7`, `APP_VERSION` **2.58.6** → **2.58.7**, pytest 8146/5/1 (5 — env), SQLite `user_version` 12, Δ каталога = 0. Волна 1 (§57) — COMPLETED+MERGED+DEPLOYED.
> **Связано:** ТЗ §5/§7/§8/§9/§10/§11–§20/§71/§117; `plans/ARCHITECTURE.md` §56/§57 (+ §604/§642 — шапка/native-safe-area); ADR-1016-2 (CSP/zero-build), ADR-1024-13 (`ui_flags`), ADR-1024-24 (fullscreen-sync), ADR-1025-1 (F1 shell), ADR-1025-8 (hotfix4), ADR-1025-9 (F2 glass), ADR-1025-10 (F3 selector).
> **Отчёты (читать, не перепроверять):** `plans/reports/round1025_package_scanner_audit.md`, `plans/reports/global_map.md`.
> **Ограничение честности:** значительная часть результата **не воспроизводима headless** (реальный Telegram WebView, нативные кнопки-Telegram, фактические `safeAreaInset`/`contentSafeAreaInset`, поведение `filter: url()` в WKWebView, FPS на устройстве, реальный fullscreen). Эти пункты закрываются **только live-гейтом владельца** (T-2617). Playwright подтверждает структурную/геометрическую часть.

## 0. Жёсткие инварианты (не нарушать)

- **Δ DDL = 0**, **Δ каталога `param_catalog` = 0** (новых ключей/таблиц/полей каталога нет; backend — только **аддитивное** расширение `GET /api/status`, если понадобится).
- **CSP / zero-build** (ADR-1016-2 / ADR-1024-13): self-host, **без CDN**, **без inline-скриптов**, **без data-URI-дублей фильтра**; SVG-фильтр — **один inline `<svg>`** в `web/index.html`.
- **Запрет WebGL**; **Canvas 2D разрешён**. Новых JS-библиотек нет.
- **Уровень A не опирается на `backdrop-filter: url()`** (§9). `backdrop-filter: url(...)` должен исчезнуть из `web/**` полностью (grep-доказательство).
- **UI-флаги — только env-only** (`ClassVar` в `config/settings.py`), доставка во фронт через `GET /api/me.ui_flags`; default ON; OFF → прежнее поведение.
- **Нативные кнопки Telegram (⋮/Закрыть/Свернуть) — вне DOM; их CSS не двигать.** Шапка позиционируется только относительно safe-area-зон (ARCHITECTURE §604/§642; §56).
- **R17/R18:** логи/отчёты — только маркеры/числа/`host`, без секретов, без контента пользователя, без URL с ключом. Бэкапы/теги `pre-round1025*`/`stash@{0}` не удалять. `plans/current_task.md` не коммитить.
- **Атомарность:** код + эталон + тест одним коммитом (project.md); маркер-тесты F2/F3/hotfix4 обновляются **атомарно** (T-2612), без ослабления проверок.
- **Ступень общих файлов:** `app.css`/`index.html` — **A → B → C → D**; `telegram-init.js` — только **B**; `app.js` — A → C → D.

## 1. Диагноз (корни «нет преломления» и прод-деградаций)

Проверено по коду на HEAD `441e8f7`:

1. **A не дефолт:** уровень A — opt-in `[data-glass="a"]`, всего **3 узла** (`index.html:1420`, `:2762`, `:2930`). Панели/шапка — вне стекла.
2. **Опора на `backdrop-filter: url()`** — `app.css:967-968/1057-1062`. ТЗ §9 прямо запрещает «полагаться исключительно» на это; в WebKit `backdrop-filter: url()` не реализован, в Chromium нестабилен.
3. **UA-gate Blink-only** (`app.js:8109-8110`) отсекает **все** WKWebView (и нишу iOS Edge `EdgiOS` не гейтит — NEW-L1).
4. **min-240** (`app.js:8134`) не пускает A на `header`/`bottom-nav` (низкие элементы) → «панели без стекла».
5. **Карта — равномерный `feTurbulence`** (`index.html:39-43`), а §9 требует «сильнее у краёв, слабее в центре»; сейчас edge-эффект даёт только CSS-кромка (`box-shadow inset`), не карта.
6. **Панели — непрозрачный `--surface-1`:** `.app-sidebar` (`app.css:1457`), `.app-drawer` (`:1477`), `.bottom-nav` (`:1499`), `.more-sheet` (`:1546`); `header.header-sticky` (`:745-752`) — `--glass-bg-strong` **без blur** (F2 L10.25F2-1).
7. **B (нижняя панель):** `--tg-viewport-bottom-offset = max(0, innerHeight − viewportStableHeight)` (`telegram-init.js:52-60`); `contentSafeAreaInset.bottom` отдельно не учитывается.
8. **C (сердцебиение):** `index.html:2770-2779` — статичный SVG + CSS-циклическая подсветка (`.ekg-trace`, `app.css:813-823`); ТЗ §15 требует Canvas 2D + rAF и реальные источники. Overflow на мобильном — `.ekg`/`.status-block` без ограничения ширины.
9. **D (шапка):** один `flex-wrap`-ряд `index.html:89-213`; ⛶ внутри `.ml-auto`-группы (`:182-198`) — на уровне native-кнопок не гарантирован; группа селектор/бейдж/аватар/роль плотная; `main.scroll-area` (`app.css:763-765`) без резерва под sticky-шапку.

## 2. D1 (A1) — реальное преломление БЕЗ `backdrop-filter: url()`

### 2.1. Механизм: «линза-слой» (foreground `filter: url()`), а не `backdrop-filter: url()`

Ключевое наблюдение: **`filter: url(#…)` на foreground-элементе реализован и в Blink, и в WebKit** — в отличие от `backdrop-filter: url(#…)`, который в WebKit отсутствует. Поэтому преломление переносится с backdrop на **отдельный декоративный слой внутри панели**:

Контракт узла уровня A (обязателен для всех glass-узлов tier A). **Реализация (факт, ADR-1025-12 D1): линза — это псевдо-элемент `[data-glass="a"]::before`, отдельного класса `.lg-lens` нет.**

- Панель = stacking-context (`position:relative; isolation:isolate`); линза — **`[data-glass="a"]::before`** `position:absolute; inset:0; z-index:-1; pointer-events:none; border-radius:inherit`.
- **Контент панели** (текст/кнопки/иконки) не оборачивается и не искажается: линза лежит под контентом (`z-index:-1` в изолированном stacking-context) — так **текст и кнопки не искажаются** (обязательное требование §9). Никакой `filter` не применяется к контенту.
- Линза несёт **градиент-реплику фона** (те же токены `--grad-*`, что и атмосферный фон §10) и получает `filter: url(#lg-lens)` (id inline-SVG-фильтра; `--glass-displace`).
- Поверх линзы — `backdrop-filter: blur() saturate()` **blur-уровня B** (blur безопасен и кросс-движков) + кромка/блик (`box-shadow inset`/`border`). То есть A = «настоящая прозрачность (blur) + оптическое искажение на линзе», а не «url-фильтр на backdrop».

Итог: **A перестаёт зависеть от `backdrop-filter: url()`**. `backdrop-filter: url(...)` удаляется из CSS и JS.

### 2.2. Edge-weighted карта (не равномерный шум)

- **Основная edge-весовка — CSS radial-mask на линзе** (не `feImage`): `mask-image: radial-gradient(ellipse at center, transparent 0% … 52%, #000 78% … 100%)`. Центр прозрачен → в центре **нет** искажения; к краям маска плотная → преломление сильнее у краёв. Это буквально §9 («сильнее у краёв, слабее в центре») и одновременно снимает «размазанный шум».
- **Вектор смещения** даёт SVG `feDisplacementMap` малой амплитуды (`scale` ≈ 8…12, не 14) поверх **сглаженной низкочастотной** карты (`feTurbulence baseFrequency ≈ 0.008 0.012`, `feGaussianBlur`), чтобы эффект читался как «стекло», а не «песок». `feImage`/data-URI-градиент **не используем** (CSP-риск, нестабильность движков).
- **Кромка/блик** (`--glass-highlight`, `--glass-highlight-soft`) усиливают оптику по границе.
- Документируется честно: это **приближение оптического преломления** (векторное поле + радиальная весовка), **не** физическая рефракция и **не** равномерный шум.

**Альтернативы (рассмотрены, отклонены):**
- Отдельный WebGL-рендерер на карточку — запрещён инвариантом.
- Canvas-2D-рефракция на каждую панель — дорого, «не на каждой карточке».
- `feImage` + внешний градиент — CSP/нестабильность.
- Оставить `backdrop-filter: url()` + расширить UA-gate — прямо нарушает §9.

### 2.3. Кросс-движковая лестница A → B → C (по feature-detect, не по UA)

| Tier | Условие выбора | Визуал |
|---|---|---|
| **A** | `CSS.supports('filter','url(#lg-lens)')` **и** элемент в allow-list панелей/крупных виджетов **и** не deny-list **и** не превышен перф-бюджет **и** не `prefers-reduced-motion` | blur + кромка + блик + линза-слой с edge-weighted преломлением |
| **B** | карточки/модули/модалки/`glass-panel` (default glass-set); либо A недоступен (нет поддержки / бюджет / reduced-motion) | blur + saturate + кромка + блик + мягкая тень, **без** преломления |
| **C** | deny-list (§9) **или** `@supports not (backdrop-filter: blur)` | непрозрачная плотная подложка `--glass-bg-strong`, без blur/преломления |

- **UA-gate Blink-only снимается.** `_liquidGlassSupported` становится чистой feature-detect `CSS.supports('filter','url(#lg-lens)')` (guard `try/catch`, вне DOM → `false`). Это закрывает и F2 M-2 (WebKit терял blur), и NEW-L1 (iOS Edge).
- **min-240 пересматривается:** старое правило отсекало низкие панели (header/bottom-nav). Новое правило — **не min-сторона, а перф-бюджет применения**:
  - A разрешён для **allow-list панелей** (`.app-sidebar`, `.app-drawer`, `header.header-sticky`, `.bottom-nav`, `.more-sheet`, hero Статуса `.status-block`) и крупных виджетов;
  - **кап применений A**: `UI_LENS_MAX_NODES` (env-only, default **6**); сверх капа — B;
  - **deny-list** §9 (textarea, таблицы прав, логи, длинные формы, редакторы промптов, `.keys-avail`, `.matrix-table`, `.log-panel`, `.prompt-editor`) — всегда **C**;
  - понижение **обратимо и транзитивно** через `data-glass-downgraded` (как сейчас), без перезаписи opt-in `data-glass`.
- **`prefers-reduced-motion: reduce` → tier B** (осознанное решение реализации, ADR-1025-12 D1): дорогое `filter: url()`-преломление не применяется вовсе, остаётся статичный blur-подложка B с кромкой/бликом; состояние/подписи корректны. Это согласовано с условием выбора A («не reduced-motion») выше.

### 2.4. Перф- и motion-бюджет

- Линза-слой — **один** на панель; фильтр инлайновый, считается GPU-композитором; анимация градиента линзы не быстрее фоновой (§10: 60–90 с / 90–120 с).
- Кап `UI_LENS_MAX_NODES = 6`; сверх — B.
- Пауза дорогих эффектов при `document.hidden` (интегрировать в существующий `onVisibilityChange`/`setBgPaused`, **не** вводить второй обработчик).
- Бюджет: отсутствие измеримой просадки ниже ~50 FPS на контрольных размерах §71 (мобильные) и в реальном WebView (live-гейт).
- Отказ-путь: `UI_GLASS_TIER_OVERRIDE=b` принудительно уводит все узлы на B (диагностика/откат без редеплоя).

### 2.5. Размещение SVG-фильтра, число применений

- **Один inline `<svg class="lg-filter-defs">` в `web/index.html`** (CSP-safe, без data-URI, без внешних ресурсов). Фильтр `#lg-lens` (edge-weighted displacement) — foreground-фильтр для линзы.
- **Число применений:** A — только allow-list панелей + крупные виджеты, не более `UI_LENS_MAX_NODES` (default 6); B — glass-set `.card`/`.module-card`/`.hub-card`/… (как сейчас, ~94 узла); C — deny-list. На панелях одновременно A ограничено, чтобы `filter: url()` не «съел» FPS.
- Тест-инвариант: в `web/**` **нет** подстроки `backdrop-filter: url(` / `-webkit-backdrop-filter: url(`.

### 2.6. Наблюдаемость (R17-safe)

- Диагностика выбранного tier: маркер `glass_tier=a|b|c`, `glass_reason` (feature-undetected / deny-list / budget / reduced-motion / override) — без контента и секретов. Используется T-2583 и live-гейтом.

## 3. D2 (A2) — стекло на панелях + контраст ≥ AA 4.5:1 + fallback

### 3.1. Панели получают стекло

Перечень и контракт (tier по §2.3, уровень B-подложка обязателен всегда):

| Узел | Файл:строка | Сейчас | Станет |
|---|---|---|---|
| `.app-sidebar` | `app.css:1457` | `--surface-1` (непрозрачно) | glass (tier A/B) + кромка; внутренний скролл сохранён |
| `.app-drawer` | `app.css:1477` | `--surface-1` | glass (tier A/B) |
| `header.header-sticky` | `app.css:745-752` | `--glass-bg-strong` без blur | glass + **blur** (закрывает F2 L10.25F2-1); плотный `--glass-bg-strong` для читаемости поверх скролла |
| `.bottom-nav` | `app.css:1491-1502` | `--surface-1` | glass (tier A/B) |
| `.more-sheet` | `app.css:1538-1550` | `--surface-1` | glass (tier A/B) |

- Панели — фиксированные (`.app-sidebar`/`.app-drawer`/`.bottom-nav`/`.more-sheet`) и sticky (`header`). Линза-слой — только при tier A; B — blur-подложка.
- **Тач-цели ≥44×44** и состояния hover/active/focus панелей сохраняются.

### 3.2. Контраст — гарантия AA 4.5:1 на новых полупрозрачных фонах

- Метод — из ADR-1025-9 D4: считать **композит** `glass-bg` (alpha) поверх худшего (самого светлого) фона за панелью; для панелей фон = анимированный wash §10 (худшая фаза teal) и/или прокручиваемый контент.
- **Обязательное доказательство:** таблица «пара (текст/иконка/состояние) → эффективный фон → ratio → PASS/FAIL» для каждого класса текста на панели (`.sidebar`-пункты, `.bottom-nav-link`/`.bottom-nav-label` 10 px → **нормальный** текст, порог 4.5:1; `.more-sheet`; `header`).
- Если ratio < 4.5 — **не** менять палитру §8 (пин ADR-1025-9): повышать **плотность подложки** панели (alpha) либо брать `*-bg`-тинт/`--err-text`, пока не достигнут AA. Для `header` над произвольным (возможно ярким) контентом — плотный `--glass-bg-strong`.
- **Осознанный fallback без blur:** `@supports not (backdrop-filter: blur(1px))` (и `-webkit-`) → уровень **C** для всех glass-панелей: `--glass-bg-strong`, без blur/преломления — раскладка и контраст сохраняются.
- **Deny-list** §9 остаётся нетронутым (textarea/таблицы прав/логи/длинные формы/редакторы → C).

## 4. D3 (B) — нижняя панель: полная компенсация `contentSafeAreaInset.bottom`

### 4.1. Контракт расчёта нижнего offset

`telegram-init.js` вычисляет **одну** переменную из трёх кандидатов (все описывают нижнюю «занятую» зону; берём **max**, чтобы не считать одно и то же дважды):

```
A = max(0, innerHeight − viewportStableHeight)          // как в hotfix4
B = contentSafeAreaInset.bottom || 0                    // Telegram UI снизу
C = safeAreaInset.bottom || 0                           // системная зона (home indicator)
--tg-viewport-bottom-offset = max(A, B, C)
```

- Дополнительно остаются `--tg-content-safe-area-inset-bottom` и `--tg-safe-area-inset-bottom` (уже прокинуты) — для `padding-bottom` панели (`max(env(...), --tg-safe-area-…, --tg-content-safe-area-…)`).
- Пересчёт на `viewportChanged`/`safeAreaChanged`/`contentSafeAreaChanged` (уже подписаны) + `resize` (страховка от «залипания»).
- Guard `stableH > 0` (review L10.25H4-1) сохраняется.
- `.bottom-nav`/`.more-sheet`: `bottom: var(--tg-viewport-bottom-offset, <CSS-фолбэк>)` (структура hotfix4 сохраняется) — теперь offset включает `contentSafeAreaInset.bottom`.
- **Почему max, а не сумма:** три величины пространственно перекрываются; сумма дала бы ложный «задир» панели вверх на клиентах, отдающих и A, и B/C про одну и ту же зону. Если live-гейт покажет необходимость суммы (разные бары) — переключение одной строкой (эскалация зафиксирована ниже).

### 4.2. Фолбэк и проверяемость

- **Клиенты без Telegram-инсетов** (Android/Desktop, все = 0) → offset = 0, панель на `bottom:0` (корректно, бара нет). Никаких «магических» фикс-высот.
- Чистая функция `computeBottomOffset({innerHeight, viewportStableHeight, contentSafeAreaInset, safeAreaInset})` выносится как тестируемая (JS-юнит: A/B/C/max/guard/нули/мусор) — это headless-проверяемая часть.
- Матрица `tools/ui_round1025_matrix.py` усиливается (T-2595): `rect.bottom <= innerHeight + 1` и `rect.bottom <= stableHeight` при **симулированном** системном нижнем баре для `.bottom-nav`/`.more-sheet`; выход — FAIL. Симуляция задаёт offset детерминированно.
- **Не воспроизводимо headless:** фактические `safeAreaInset`/`contentSafeAreaInset` конкретного клиента → live-гейт владельца (T-2617b).
- **Порядок навигации не ломается:** `bottomNavItems` (F1/hotfix4: `Статус`+`Справка` первыми, ≤4 слота, «Ещё» без дубля) не изменяется — B трогает только позиционирование/offset.

## 5. D4 (C) — сердцебиение §15: Canvas 2D + rAF, источники, состояния, overflow

### 5.1. Компонент

- **Canvas 2D + `requestAnimationFrame`** заменяет SVG-заглушку. WebGL запрещён; используется `getContext('2d')`.
- **Рендер отделён от сети:** цикл rAF только **рисует** готовый снимок; сеть в кадре отсутствует.
- Линза/растр: `canvas.width/height = CSS-размер × devicePixelRatio`; CSS `width:100%; max-width:100%` — при DPR-масштабировании overflow не возникает.
- Жизненный цикл: старт при наличии данных и видимости; пауза по `document.hidden` (интеграция в существующий `onVisibilityChange`); останов в `beforeUnmount`. Вне Canvas-окружения (тесты/старый движок) — деградация на SVG-виджет (флаг ниже).

### 5.2. Телеметрия ОТДЕЛЬНО от рендеринга; без роста нагрузки

- Источник — **существующий** `GET /api/status` (`services/status_service.py::_server_metrics`, `:396-411`; `build_snapshot` `:580-608`), уже опрашиваемый `startStatusPolling` каждые **30 с** (`app.js:6364-6368`).
- **Новый polling НЕ вводим:** компонент подписывается на изменение `statusData` (Vue watch/computed) и кэширует последний снимок + `last_updated`. 30 с — верхняя граница диапазона §15 (10–30 с) → нагрузка **не растёт**.
- Если позже потребуется 10–15 с — использовать **существующий** интервал-гейт (`UI_HEARTBEAT_POLL_SECONDS`), обновляющий тот же `statusTimer`, с паузой по `document.hidden`; отдельный поллер не заводить (зафиксировано как возможное расширение, не в этом пакете).

### 5.3. Источники → состояния (без выдуманных метрик)

| Источник §15 | Поле (существующее) | Отсутствие → |
|---|---|---|
| доступность бота | `bot.state`, `bot.uptime_seconds` (`:581-591`) | UNKNOWN |
| CPU | `server.cpu_percent`; `loadavg[0]/cpu_count` (`:397-401`) | UNKNOWN (не 0) |
| RAM | `server.memory.percent` (`:402-403`) | UNKNOWN |
| диск | `server.disk.percent` (`:404-405`) | UNKNOWN |
| крит. процессы | `bot.state` + `server.process` (`rss_mb`/`threads`, `:407-410`) | UNKNOWN-причина |
| актуальность телеметрии | `statusData.generated_at` (`:608`) vs now | stale → UNKNOWN |

- **Никаких выдуманных BPM/производных.** Если поля нет — **UNKNOWN**, а не подстановка нуля (§14/§15).
- `server.*` относятся ко **всему серверу** (§14): при выбранном чате — явная пометка (§14).

### 5.4. Состояния, сглаживание, гистерезис

- Состояния: **HEALTHY / WARNING / CRITICAL / UNKNOWN**; различаются цветом, интенсивностью свечения, частотой, амплитудой и характером импульса (не «одна и та же пульсация другого цвета»).
- Пороги (фронт-константы, Δ каталога=0): WARNING — max(cpu, mem, disk) ≥ 0.70; CRITICAL — ≥ 0.90 либо `bot.state ≠ running`; свежесть: `now − generated_at`.
- **Гистерезис** (вход ≠ выход): WARNING enter 0.70 / exit 0.65; CRITICAL enter 0.90 / exit 0.85; плюс dwell/счётчик последовательных сэмплов — без «дребезга» на границе.
- **Сглаживание:** EMA по сэмплам телеметрии + render-side амплитудное сглаживание; на 30-с интервале — по накопленной истории.
- Переходы детерминированы и **покрыты тестом** (гистерезис доказывается поведенчески).

### 5.5. UNKNOWN, тултип, reduced-motion, мобильная область (C1)

- **UNKNOWN:** нет `statusData`, устаревшая телеметрия, отсутствуют ключевые поля, либо ошибка `/api/status` → серо-синий «плоский/пунктирный» характер; подпись + причина, без фиктивных чисел.
- **Тултип hover/tap:** CPU, RAM, диск, статус, **время обновления**, **причина** (почему WARNING/CRITICAL/UNKNOWN). Доступен на desktop (hover) и mobile (tap). Позиционируется внутри карточки/вьюпорта, **не перекрывает** системные элементы Telegram. Доступность: `aria-label`/`aria-describedby`, фокусируемость.
- **`prefers-reduced-motion: reduce`:** статичный кадр — без пульсации/анимации движения; состояние при этом корректно отражено цветом/подписью.
- **C1 (overflow мобильного)** — обязательное условие:
  - `.status-block { max-width:100%; overflow:hidden }`; канвас — `width:100%; max-width:100%; height:56px; display:block`.
  - На мобильном сердцебиение занимает **отдельную горизонтальную область** под системными метриками (§15): `.status-block__pulse` — полноширинный блок, `.status-block__grid` в одну колонку.
  - Инвариант: `scrollWidth <= clientWidth` для блока и отсутствие влияния на общий overflow страницы (Playwright на 320/360/390/414).

### 5.6. Флаг отката

- `UI_HEARTBEAT_CANVAS_ENABLED` (env-only `ClassVar`, default **ON**): OFF → прежний SVG-виджет **байт-в-байт** (SVG-разметка сохраняется под `v-if`). Мягкий откат C2 без редеплоя.

## 6. D5 (D) — компоновка шапки: native-safe-area, отдельная строка, резерв высоты, fullscreen

### 6.1. Композиция (две строки)

- **Строка 1 (верхняя):** `[навигация/drawer] [in-app ← fallback] [заголовок/breadcrumb] ……… [⛶]`.
  - **D1:** ⛶ и правая служебная зона — в **правом верхнем углу**, визуально на один уровень с нативными кнопками Telegram (⋮/Закрыть/Свернуть). Так как нативные кнопки **вне DOM**, выравнивание достигается **резервом safe-area-зоны**, а не сдвигом нативных кнопок:
    - верхний паддинг шапки = база + `max(env(safe-area-inset-top), --tg-safe-area-inset-top, --tg-content-safe-area-inset-top)`;
    - ⛶ — тач-цель **≥44×44**, `margin-left:auto`, прижат к правому краю с учётом правой safe-area.
    - **Нативные кнопки CSS не двигать** (ARCHITECTURE §604/§642/§56). Если WebView не даёт одну строку — ⛶ занимает **ближайшее безопасное** положение без наложений.
- **Строка 2 (компактная, под нативными кнопками):** **D2** — селектор области, бейдж `chat_id`, аватар и роль админа в отдельной компактной строке.
  - При нехватке ширины: название чата — `ellipsis`; второстепенное — в `<details class="scope-tech">`; **полный `chat_id` — только в технических подробностях** (согласовано F3/§5).
- **D4 (mobile):** компактная шапка; селектор области **постоянно доступен** (не сворачивается, `min-w-0`+`truncate`); аватар/роль при крайней узости — в «подробности»/компактный элемент. **Без горизонтального скролла** и без перекрытия системных кнопок Telegram.

### 6.2. Резерв высоты под sticky-шапку (D3)

- Устранить наложение контента на sticky-шапку: ввести токен `--header-h` (измеряется ResizeObserver; CSS-фолбэк задаёт разумный минимум) и применять `scroll-padding-top`/резерв у `main.scroll-area` (`.scroll-area`, `app.css:763-765`) на всех размерах.
- **Без «магических» отступов, зависящих от ширины:** резерв выводится из фактической высоты шапки (строка 1 + строка 2), а не из брейкпоинт-констант.
- В fullscreen (`.fullscreen-mode`) sticky-шапка остаётся, `.scroll-area` — собственный скроллер; резерв сохраняется.

### 6.3. Fullscreen должен работать (D5, сохранить ADR-1024-24)

- Источник истины — **TMA** (`wa.isFullscreen` + события `fullscreenChanged`/`viewportChanged`); локальный флаг **не угадывается**. `toggleFullscreen`/`initFullscreen`/`setFullscreenFromTma`/`teardownFullscreen` (`app.js:4631-4713`) сохраняются.
- Диагностировать и починить: доступность `requestFullscreen`/`exitFullscreen` в целевом SDK, фактическое обновление `isFullscreen`, отложенный re-read (microtask+rAF), а также **попадание клика** по ⛶ (в двухстрочной шапке кнопка не должна перекрываться/смещаться).
- Состояние кнопки (иконка/подпись/`title`) синхронизировано с режимом.
- **Не воспроизводимо headless** → live-гейт владельца (T-2617d).

### 6.4. Совместимость с F1/OFF

- При `IA_V2_ENABLED = false` шапка остаётся **байт-в-байт** legacy (navbar 6 пунктов); `UI_HEADER_COMPACT_V2` применяется только в IA v2 (`iaV2 === true`). Композиция не ломает F1 shell/safe-area и F3-селектор/guard.

## 7. Feature flags (env-only, default ON, Δ каталога = 0)

Доставка — через `GET /api/me.ui_flags` (`web/api/routes.py:351-383`), как остальные env-only рубильники (ADR-1024-13/§56).

| Флаг | Тип | Default | Смысл / откат |
|---|---|---|---|
| `UI_GLASS_TIER_OVERRIDE` | `ClassVar[str]` ∈ `auto\|a\|b\|c` | `auto` | Принудительный tier стекла (диагностика/откат A→B/C без редеплоя) |
| `UI_HEARTBEAT_CANVAS_ENABLED` | `ClassVar[bool]` | `ON` | OFF → прежний SVG-виджет байт-в-байт (мягкий откат C2) |
| `UI_HEADER_COMPACT_V2` | `ClassVar[bool]` | `ON` | OFF → прежняя компоновка шапки (откат D), только в IA v2 |
| `UI_LENS_MAX_NODES` | `ClassVar[int]` | `6` (min 1) | Перф-кап числа узлов tier A (сверх — B). Не UI-флаг, диагностический |

**Обоснование набора:** каждый флаг даёт **независимый** откат своей области (A / C / D) без изменения остальных и без редеплоя кода — это оправдано для P0-прод-деградаций. Дополнительные UI-флаги для B (позиционирование) и A2 (панели) **не вводим**: B обратим CSS/JS-функцией, A2 управляется тем же `UI_GLASS_TIER_OVERRIDE`. Progressive delivery (10/50/100%) **не применяется** (§53/§54.1/§55/§56: один прод); «поставка» = bump `APP_VERSION` 2.58.6 → 2.58.7 + cache-bust.

**Кандидаты отклонены:** инлайн/сторонние флаги (запрещены), каталоговые ключи (Δ каталога≠0), `UI_HEARTBEAT_POLL_SECONDS` в этом пакете (потенциальный рост нагрузки — оставлен как будущее расширение).

## 8. SUPERSEDE / AMEND-карта (объявить на Step 2)

| Ранее | Действие | Причина |
|---|---|---|
| **§15 «Живое сердцебиение» в F11 `status-showcase-dashboard-round1025`** | **SUPERSEDE (перенос области)** в этот пакет (C2) | Триггер приёмки владельца; §15 реализуется здесь. В F11 остаются §12/§13/§14/§16–§21 |
| **ADR-1025-9 D2** (уровень A = `backdrop-filter: url()`, UA-gate Blink-only, min-240, равномерный `feTurbulence`) | **AMEND → ADR-1025-12 D1** | §9 прямо запрещает опираться на `backdrop-filter: url()`; нужен кросс-движковый A и edge-weighted карта |
| **ADR-1025-8 / hotfix4 D2** (offset = `innerHeight − viewportStableHeight`) | **AMEND → ADR-1025-12 D3** | Не учтён `contentSafeAreaInset.bottom` → панель за экраном |
| **ADR-1025-10 / F3** (селектор в шапке) и **ADR-1025-1 / F1** (shell/шапка) | **AMEND → ADR-1025-12 D5** | Селектор/бейдж/аватар/роль переносятся в отдельную компактную строку; перекомпоновка шапки |
| **F2 L10.25F2-1** (header alpha без blur) | **ЗАКРЫВАЕТСЯ → D2** | Шапка получает blur |
| **F2 M-3 / M-2 / NEW-L1** (цена A не измерена; WebKit теряет blur; iOS Edge не гейтится) | **ЗАКРЫВАЕТСЯ/ПЕРЕСМОТР → D1** | Перф-кап + feature-detect вместо UA-gate + уход от `url()` на backdrop |
| **ADR-1024-24** (fullscreen-sync, источник истины TMA) | **НЕ отменяется; D5 чинит реализацию** | Поведенческий баг, не смена контракта |
| **НЕ отменяется:** CSP/zero-build; палитра §8 (ADR-1025-9 D1); механика фона §10 (`--grad-*`); порядок навигации F1/hotfix4; семантика F3 (DELETE override ≠ factory-reset, guard, stale-epoch); save-path F0 (ADR-1025-2) | — | инварианты |

## 9. Ступени, совместимость, атомарность

- **Порядок:** T-2581 (откат/baseline) → **T-2582 (эта спека + ADR, гейт)** → A1 → A2 → B → C → D → общее (T-2612…T-2618).
- **Ступень общих файлов:** `app.css`/`index.html` — A→B→C→D; `telegram-init.js` — только B; `app.js` — A→C→D.
- **Маркер-тесты** F2 (glass A/B/C, inventory), F3 (шапка/селектор/`.scope-tech`), hotfix4 (позиционирование `.bottom-nav`) обновляются **атомарно** с кодом (T-2612), без ослабления проверок.
- **Не ломать:** F1 IA/shell, F2 палитра/фон/контраст, F3 селектор/guard, hotfix4; `node --check web/app.js`; `git diff --check`.
- **Cache-bust:** `APP_VERSION` 2.58.6 → 2.58.7 (T-2613), `?v=`-пины в тестах, README синхронен.

## 10. Доказательства и тесты (что проверяется где)

- **Headless (Playwright §71, 10 вьюпортов + низкое окно Desktop):**
  - нет `backdrop-filter: url(` в `web/**` (grep-инвариант);
  - tier выбирается детерминированно (feature-detect/deny-list/override/reduced-motion → A/B/C);
  - панели (`sidebar`/`drawer`/`header`/`bottom-nav`/`more-sheet`) в glass-set; контраст-пробы AA;
  - `rect.bottom <= innerHeight + 1`/`stableHeight` для `.bottom-nav`/`.more-sheet` при симулированном нижнем баре (FAIL иначе);
  - heartbeat: canvas присутствует, `scrollWidth <= clientWidth`, нет общего горизонтального overflow; reduced-motion → статичный кадр;
  - композиция шапки: ⛶ не пересекается с зарезервированной зоной native-кнопок; резерв высоты контента; отсутствие горизонтального скролла.
- **JS/node-юниты:** `computeBottomOffset` (A/B/C/max/guard/мусор); state-machine heartbeat (пороги/гистерезис/UNKNOWN-при-отсутствии-данных/reduced-motion/отделение телеметрии от рендера); tier-выбор.
- **Red→green:** новые тесты **падают на старом коде** (SVG-heartbeat, `backdrop-filter: url()`, старый offset).
- **Инварианты:** Δ DDL=0, Δ каталога=0, `node --check`, `git diff --check` exit 0; полный pytest 8146/5/1 + новые.
- **Только реальный Telegram WebView (владелец, T-2617):** фактическое преломление и стекло панелей/шапки; панель целиком в экране; heartbeat — Canvas 2D/состояния/тултип/перф; ⛶ на уровне native-кнопок и рабочий fullscreen; отсутствие регрессий и `ReferenceError` в консоли TMA.

## 11. Техдолг / риски

- **A «невидим» и после фикса (Critical):** без реального WebView нельзя гарантировать силу эффекта — митигируется живым гейтом, диагностикой tier и `UI_GLASS_TIER_OVERRIDE`.
- **Перф `filter: url()` на крупных панелях (High→Medium):** митигируется капом `UI_LENS_MAX_NODES`, reduced-motion, паузой по `document.hidden`, опцией override на B.
- **Контраст на новых полупрозрачных панелях (High):** обязательная AA-таблица; при провале — плотность подложки, не смена палитры §8.
- **Панель всё ещё за экраном (High):** max трёх источников + симуляция в матрице + реальный WebView; остаточная неопределённость клиентов без инсетов зафиксирована.
- **Native-кнопки вне DOM (High):** выравнивание только по safe-area-зоне, не по пикселям; вариативность клиентов документируется.
- **Fullscreen не воспроизводим headless (High):** живой гейт; сохранён контракт ADR-1024-24.
- **Выдуманные метрики/BPM (Critical по §15/§116):** запрещены; UNKNOWN-причина вместо нуля; тесты фиксируют.
- **Секреты/контент в логах (Critical, R17/R18):** только маркеры/числа/`host`.
- **Атомарность эталонов:** массовое обновление маркер-тестов F2/F3/hotfix4 одним коммитом (T-2612).
- **Не воспроизводится headless (зафиксировать в отчёте):** WKWebView `filter: url()`, реальные Telegram-инсеты, геометрия native-кнопок, реальный fullscreen, устройство-зависимый FPS.

## 12. Открытые вопросы tasks.md — решения @Architect

1. **A (tier «достаточный»):** приёмка — **A на панелях/крупных виджетах**, где движок поддерживает foreground `filter: url()`; на неподдерживающем движке/бюджете — **честный B** (blur+кромка+блик) как осознанный результат, **не** «пустое стекло»; C — для deny-list/без blur. Довести A «любой ценой» на всех устройствах не требуется (§9 допускает fallback).
2. **B (нет `contentSafeAreaInset`):** используем **max(A,B,C)**; при полном отсутствии инсетов — offset 0 (панель на `bottom:0`), без фикс-высот. Дополнительный CSS-резерв не вводим (магия отступов запрещена).
3. **D1 (не даёт одну строку):** **допустимо** — ⛶ в ближайшем **безопасном** положении без наложений (не строго на уровне native-кнопок).
4. **C2 (polling и библиотека):** дефолт — **30 с**, **переиспользуя** существующий `/api/status`-поллинг (нагрузка не растёт); **чистый Canvas 2D**, self-host `chart` не подключаем (§15 предпочитает Canvas 2D; меньше поверхности).

## 13. Ссылки

- Рамка: `plans/features/hotfix6-webview-shell-heartbeat-round1025/tasks.md`; ADR: `plans/features/hotfix6-webview-shell-heartbeat-round1025/adr-1025-12-glass-lens-heartbeat-header-shell.md`.
- ТЗ: `plans/current_task.md` (§5/§7–§10/§11–§20/§71/§117).
- Архитектура: `plans/ARCHITECTURE.md` §56/§57 (+ §604/§642).
- Предшественники: `plans/archive/design-tokens-liquidglass-v2-round1025/adr-1025-9-*.md`, `plans/archive/hotfix4-cover-nav-shell-round1025/adr-1025-8-*.md`, `plans/archive/global-scope-selector-round1025/adr-1025-10-*.md`, `plans/archive/ia-shell-navigation-round1025/adr-1025-1-ia-v2.md`, `plans/archive/providers-fullscreen-advanced-fix-round1024/ADR-1024-24.md`.
- Код (для реализации): `web/static/app.css:44-64/745-752/763-765/941-981/1046-1062/1457/1477/1491-1550`; `web/index.html:5-7/27-46/89-214/1420/2762/2930`; `web/app.js:8102-8182/4631-4713/6364-6368/1706-1749`; `web/static/telegram-init.js:30-74`; `services/status_service.py:380-411/477-608`.

---

*Шаг 2 @Architect завершён. Реализация — @Builder (после T-2581/T-2582). Код в этом документе не пишется.*
