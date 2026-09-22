# spec.md — HOTFIX9 `hotfix9-shell-liquidglass-darkaurora-round1025` (Step 2 @Architect)

> **ТЗ:** **UPD3** «HOTFIX — SHELL / LIQUID GLASS / BACKGROUND / RESPONSIVE» в `plans/current_task.md`, **строки 6499–7264** (прочитан дословно; `current_task.md` **не изменялся** и не коммитится, R18). Разделы §0–§17 — обязательный объём.
> **Тип:** UI + shell/geometry/glass/background (web, Vue 3 global zero-build, CSP). **Приоритет:** P0, выше F6 (`memory-analytics-reorg-round1025` — ⏸).
> **Задачи:** T-2790…T-2839 (`tasks.md`). **ADR:** `adr-1025-17-shell-flex-aurora-glass-csp.md`.
> **Baseline (Step 0 @Memory/`tasks.md`):** HEAD `b374c0f`, `APP_VERSION` **2.58.11**, pytest **8272/0**, каталог 459/98/96/21/418, SQLite `user_version=12`.
> **Статус:** Proposed (Step 2). Human gate **не требуется** (UPD3 §16: библиотека/CSS/деплой/отчёт — не основание).

## 1. Scope

Устранение **реальных дефектов существующей реализации** (не редизайн, не смена IA, не бизнес-логика, не переписывание исправных компонентов, UPD3 §0).

**В scope:**
- **Геометрия (A/B):** единый источник высоты + flex-колонка `shell-mobile`/fullscreen; нижняя навигация внутри потока (P0); safe-area ровно один раз; удаление старого fixed/bottom-offset двойного учёта (§3/§4).
- **Header/fullscreen (C):** grid/flex-выравнивание, селектор отдельной строкой, ⛶ в safe-area, `scrollTop` при смене раздела, сохранение виджетов в fullscreen (§5).
- **Modal/SaveBar (D):** `modal-card > modal-head / modal-body / modal-actions`; SaveBar — отдельная нижняя область существующим компонентом; высоты 600–700 px; клавиатура; nav не поверх модалки; логика сохранения F0 **не меняется** (§6).
- **Текстура/shell (E/F):** **полное** удаление `--shell-texture` со всех shell-поверхностей; графитовые токены §8; shell ≠ карточки; без ореола (§7/§8).
- **Стекло (G):** настоящий эффект через объективно выбранный кандидат (`@liquidglassjs/core`) либо честный fallback; локальная vendored-сборка под CSP; точечное применение (§9).
- **Фон (H):** Dark Aurora Flow — один canvas + fragment shader (OGL) либо 2D/SVG-фолбэк; палитра/скорость/перф/reduced-motion/context-loss (§10).
- **Сердцебиение (J):** только устранить исчезновение в fullscreen, дизайн не менять (§11).
- **Проверки/деплой/продолжение (I/K):** Playwright+DOM §12; деплой §14; аудит §15; **немедленное продолжение F6** без human gate (§15/§17).

**Вне scope (excluded):**
- Редизайн с нуля; смена IA/маршрутов/информационной архитектуры; бизнес-логика бота; переписывание исправных компонентов (§0).
- Backend/БД/`services/param_catalog.py`/контракты API: **Δ DDL = 0**, **Δ каталога = 0**.
- Vue→React; переписывание приложения; CDN в production; сборка всего проекта ради одного эффекта (§1).
- Нативные кнопки Telegram (⋮/Закрыть/Свернуть) — CSS не двигать (§4/§5; прецедент §56/§58/§59).
- Переписывание `persistItems` (F0), store-контракта F4 §37–§42, F1/F2/F3/F5 §61, SaveBar-логики F9/F0 (только визуальный footer §6).
- Область Эпиков 2/3 — после завершения Эпика 1 (§17).

## 2. Трассируемость UPD3 → требование → решение → задача

| UPD3 | Наблюдаемое требование | Решение | Задачи |
|---|---|---|---|
| §3 (6580–6617) | Аудит источников высоты; flex-колонка; без новых компенсационных отступов | ADR-17 D1 | T-2793…T-2797 |
| §4 (6619–6689) | **P0** nav внутри flex; safe-area один раз; удалить fixed/offset; клавиатура | ADR-17 D1 | T-2798…T-2801 |
| §5 (6692–6726) | Header/fullscreen: grid/flex, селектор строкой, ⛶ safe-area, `scrollTop`, виджеты | ADR-17 D2 | T-2802…T-2805 |
| §6 (6729–6779) | Modal/drawer/SaveBar: footer, 600–700 px, последнее поле, клавиатура, nav не поверх | ADR-17 D3 | T-2806…T-2809 |
| §7 (6782–6807) | **Полное** удаление диагональной текстуры (без замены/шума/сетки) | ADR-17 D4 | T-2810…T-2811 |
| §8 (6810–6851) | Графитовый shell; shell ≠ карточки; без ореола; AA | ADR-17 D4 | T-2812…T-2813 |
| §9 (6854–6925) | Настоящее преломление/прототип/точечно/fallback/deny-list | ADR-17 D5 | T-2814…T-2819 |
| §10 (6928–7009) | Dark Aurora Flow (OGL/2D/SVG): палитра, 5–10 с, перф, reduced-motion, context-loss | ADR-17 D6 | T-2820…T-2825 |
| §11 (7012–7037) | Сердцебиение: только fullscreen-исчезновение, дизайн не менять | ADR-17 D7 | T-2831…T-2832 |
| §12 (7040–7101) | Playwright+DOM, rects, `elementFromPoint`, кадры 0/5/10/20 с, прототип стекла | ADR-17 D8/§6 | T-2826…T-2830 |
| §13 (7104–7128) | 10 «не принято» + доказательная планка (токен/библиотека/сборка/Approved ≠ выполнение) | ADR-17 D8 | T-2833…T-2836 |
| §14/§15/§17 | Деплой, аудит остатка, **немедленное продолжение F6** без human gate | ADR-17 D8 | T-2833…T-2839 |
| §1 (6532–6557) | **AMEND** «no-libraries»: библиотеки разрешены; фикс-версии; локальная сборка; CSP/WebView | ADR-17 D5/D6 | T-2815, T-2818, T-2820 |

## 3. Решения (полное обоснование — ADR-1025-17)

### D1 — Геометрия (a): единый источник высоты + flex-колонка
- **Единственный источник высоты — `--app-usable-height`.** JS `telegram-init.js::computeBottomOffset(innerHeight, viewportStableHeight, contentSafeAreaInset.bottom, safeAreaInset.bottom)` = `max` трёх инсетов (формула **не меняется**, ADR-1025-12 D3) теперь задаёт `--app-usable-height = max(0, innerHeight − offset)` (px, inline на `documentElement`); `--tg-viewport-bottom-offset` **сохраняется** (диагностика + отдельный fixed-overlay `.more-sheet`), но **снимается** с `.bottom-nav`.
- **CSS-фолбэк:** `--app-usable-height: 100vh` (всегда валидно); апгрейд до `100dvh` — строго в `@supports (height:100dvh)`. Старый WebView без `dvh` гарантированно получает `100vh`. `--shell-h: var(--app-usable-height)` — **алиас** (совместимость маркеров/тестов), второй независимой величины высоты нет.
- **Flex-колонка** (`.app-shell.shell-mobile`, `.app-shell.fullscreen-mode`): `display:flex; flex-direction:column; height/max-height:var(--app-usable-height); min-height:0; overflow:hidden`. `main.scroll-area`: `flex:1 1 auto; min-height:0; overflow-y:auto; overflow-x:hidden` — скроллится только центр. `.bottom-nav`: `position:relative; inset:auto; flex:0 0 auto; width:100%` — последний flex-child.
- **Safe-area ровно один раз.** Нижние инсеты учитываются **только** внутри `computeBottomOffset` (→ `--app-usable-height`); на `.bottom-nav` **не** добавляется дублирующий `padding-bottom`/`bottom:`. Верхние — одним резервом header. `.more-sheet` как отдельный fixed-overlay сохраняет `bottom: var(--tg-viewport-bottom-offset)` (учёт один для своей поверхности, не вложено в колонку shell).
- **Удаляются** конфликтующие правила старого fixed-позиционирования nav и «второй» высоты; одновременное использование flex и системы bottom-offset запрещено.
- **Desktop** — sidebar **216px** (∈208–224), gap header↔первая карточка **16px** (∈16–20): без регрессии (§62.1).
- **Флаг `UI_SHELL_FLEX_V3`** (env-only `ClassVar[bool]`, default ON) → OFF = `.shell-layout-legacy` (прежние высоты/fixed nav), мягкий откат без редеплоя.

### D2 — Header/fullscreen (b): grid/flex, селектор строкой, ⛶ safe-area, scrollTop
- Header — `flex:0 0 auto` в колонке; контент физически **не может** оказаться под шапкой (структурное устранение наложения). Никаких случайных `absolute`-сдвигов; выравнивание — Grid/Flex.
- Двухстрочная компоновка (hotfix6 D5) сохраняется: строка 1 — навигация/заголовок/⛶; строка 2 — селектор области / бейдж / аватар / роль. Селектор — в **своей** строке; аватар/роль — `min-w-0`+`truncate`, без пересечений.
- **⛶** выравнивается **резервом safe-area** (`max(env(safe-area-inset-top), --tg-safe-area-inset-top, --tg-content-safe-area-inset-top)` + база), тач-цель ≥44×44; **нативные кнопки Telegram CSS не двигаются**.
- `--header-h` (ResizeObserver) — единственный резерв (`scroll-padding-top`); сохраняется.
- **scrollTop:** переход на новый основной раздел (`activeTab`/route) → `main.scroll-area.scrollTop = 0` (в normal-режиме `window.scrollTo(0,0)`); новый раздел открывается с начала страницы.
- **Fullscreen:** flex-колонка с тем же header/селектором/виджетами; ничего не исчезает и не клипается; новых наложений нет. Fullscreen-sync **ADR-1024-24** — источник истины TMA, не меняется.

### D3 — Modal / Drawer / SaveBar (c, §6)
- **DOM:** `.modal-card` = `display:flex; flex-direction:column; max-height: min(var(--app-usable-height) − 24px, 720px)` > `.modal-head` (`flex:0 0 auto`) / `.modal-body` (`flex:1 1 auto; min-height:0; overflow-y:auto`) / `footer.modal-actions` (`flex:0 0 auto`, **не** sticky/absolute, **не** поверх полей).
- **Переиспользуется существующий компонент `<sticky-save>`**: переносится из-под `.modal-body` в `<footer class="modal-actions">`; **вторая SaveBar не создаётся**. Логика/состояния сохранения (F0/F9) **не меняются** — перемещение разметки/CSS.
- Высоты окна **600–700 px:** последнее поле скроллится в видимость в `.modal-body`; footer целиком в экране.
- **Клавиатура:** при `visualViewport`/`viewportChanged` пересчитывается `--app-usable-height`; active input внутри модалки приводится в видимость (`scrollIntoView({block:'nearest'})`), логика сохранения не затрагивается.
- **Nav не поверх модалки:** `.modal-backdrop`/`.modal-card` — над shell-слоем; после D1 nav в потоке → просвечивание структурно исключено.
- `scroll-padding-bottom`/`.sticky-spacer` сохраняются для прочих in-body носителей (`main.scroll-area:has(> .sticky-save)`).

### D4 — Текстура и графитовый shell (d, §7/§8)
- **`--shell-texture` удаляется полностью** (токен `app.css:92` + legacy-override `:1431-1436` + все `background-image: var(--shell-specular), var(--shell-texture)` в `[data-glass="shell"]:1298`, sidebar `:1864`, drawer `:1894`, `.bottom-nav:1926`, `.more-sheet:1982`). **Не** ослабляется, **не** заменяется шумом/сеткой/иным паттерном. `--shell-specular` **остаётся** (не-repeating мягкий верхний блик, §9), `background-image: var(--shell-specular)`.
- **Графитовые токены §8** (`:root`): `--shell-bg rgba(27,29,34,.94)` (mobile ≤767 `rgba(27,29,34,.96)`), `--shell-border-color rgba(255,255,255,.09)`, `--shell-highlight rgba(255,255,255,.055)`, `--shell-shadow 0 4px 16px rgba(0,0,0,.16)`, `--shell-blur blur(14px) saturate(105%)` (+`-webkit-`).
- `--shell-bg ≠ --glass-bg`; shell-панели ≠ карточки; цветная линза/ореол на shell уже сняты (ADR-1025-16 D2) — не возвращаются; **прозрачность карточек не меняется**.
- **AA ≥ 4.5:1** пересчитывается на худшей фазе фона; при провале повышается плотность shell-токена, **не** палитра §8.
- **Флаг `UI_SHELL_GRAPHITE_V3`** (default ON) → OFF = значения `--shell-*` hotfix8 (текстура **не** возвращается — её удаление есть часть исправления).

### D5 — Настоящее преломление (e, §9)
- **Кандидат: `@liquidglassjs/core` 0.5.3** (точная фиксация; MIT; ESM; SLSA-provenance). Основной рендерер — SVG `feDisplacementMap` по **живому DOM** (кросс-движково, Chrome/Safari/Firefox); в README-«gotchas» библиотека сама фиксирует, что `backdrop-filter: url(#…)` «parses everywhere and paints only in Chromium», и её frost-путь проверяет движок и падает на `blur()` → **на `backdrop-filter: url()` опоры нет** (совместимо с прецедентом hotfix6).
- **Локальная vendored-сборка под CSP:** npm — только инструмент сборки (фикс-версия + lock в `tools/vendor/`), esbuild → IIFE `web/static/vendor/liquidglass.core.0.5.3.min.js` + `liquidglass.core.0.5.3.css`; подключение same-origin `<script src="/static/vendor/…?v=__APP_VERSION__">`. CSP `script-src 'self'` (и фактическая `'unsafe-eval'`) соблюдены: без CDN/инлайна. Прецедент vendoring — `vue.global.prod.min.js`/`chart.umd.min.js`/`vis-network`.
- **Гейт-прототип** (T-2814…T-2816): изолированная страница с **реальным** анимированным фоном + стеклянная карточка + кнопка + селектор + текст; сравнение кадра фона **без стекла и через стекло**; только изменение содержимого **позади** считается преломлением. Фильтрация собственного декоративного слоя/клона за результат **не принимается**.
- **Точечное применение:** селектор области, fullscreen-кнопка, 1–2 декоративные карточки Статуса. Sidebar/header — **графитовые + слабый frosted** (только `backdrop-filter: blur`, не «линза»). Deny-list (textarea/таблицы/логи/длинные формы/редакторы) — tier C без изменений.
- **Запреты §9:** толстая белая рамка, неон, сильное размытие текста, желеобразная деформация, случайная цветная текстура, «огромная линза вместо sidebar».
- **Если прототип объективно отклоняет библиотеку** (не преломляет контент позади/артефакты клона, Safari-drop слоёв, WebView-несовместимость) — задокументировать альтернативу и применить **качественный fallback** (frost: blur + тонкая светлая кромка + мягкий верхний блик + глубина); «фильтрацию своего слоя» за преломление **не выдавать**. Human gate не требуется (§16).
- **Флаг `UI_LIQUID_GLASS_LIB`** (default ON) → OFF = только frost-fallback.

### D6 — Dark Aurora Flow (e, §10)
- **Решение: OGL `ogl@1.0.11`** (Unlicense, zero-dependency ESM) — **один** полноэкранный `<canvas>` + лёгкий fragment shader: 2–3 широкие мягкокрайние ленты, плавно изгибаются/пересекаются/morphing. Палитра: bg `#090D17`, teal `#42D6C4`, blue `#77A8FF`, violet `#A78BFA`, indigo `#5C7CFA`. Vendored IIFE `web/static/vendor/ogl.1.0.11.min.js` (та же CSP-схема).
- **Слой:** canvas за `#app` (`z-index:0`, `pointer-events:none`); существующие `.aurora-bg` (5 blob) + `body::before/::after`-анимации **выводятся из активного пути** (не «новые пятна поверх старых»); `html.bg-wash-legacy`/`html.lg-bg-paused` семантика переиспользуется (пауза/статика).
- **Скорость:** движение заметно за **5–10 с**; не статично, не «психоделика».
- **Перф:** desktop — полный эффект; mobile — облегчённый режим (ориентир ~30 FPS); DPR-кап (desktop ≤2, mobile ≤1.5); **стоп рендера** при `document.hidden`; `prefers-reduced-motion` → один качественный статичный кадр, затем стоп; `webglcontextlost` → CSS-статик-фолбэк.
- Фон не перекрыт непрозрачными контейнерами, не создаёт ореол вокруг sidebar, не ухудшает контраст текста.
- **AMEND:** WebGL-запрет снимается **только** для фонового canvas (шader-ленты); `getContext('2d')`-сердцебиение и отсутствие `backdrop-filter: url()` в авторском CSS — сохраняются; Three.js не подключается.
- **Флаг `UI_AURORA_FLOW_V2`** (default ON) → OFF = прежний CSS-aurora.

### D7 — Сердцебиение (только отображение, §11)
- Дизайн/форма/анимация/цвета/пороги/источники/алгоритм **не меняются**. Устраняется **только** исчезновение в fullscreen: (1) canvas/контейнер не схлопываются (`min-height`, `display`); (2) элемент сохраняется после Vue-render (`v-show`, не `v-if`); (3) `_hbResize()`/перезапуск rAF после `viewportChanged`/`fullscreenChanged`/смены `--app-usable-height`; (4) проверка отсутствия `overflow:hidden`-клиппинга родителями (`.hb-wrap`/`.status-block`/`scroll-area`). Если проблему решает D1 — компонент **не трогать**.

### D8 — Инварианты и доказательность
- **Δ DDL = 0, Δ каталога = 0**; без миграций/ALTER. **CSP** (`script-src 'self'`), без CDN/инлайна; фикс-версии; локальная сборка/раздача. **R17/R18** (без секретов/сырых значений; `current_task.md` не изменять/не коммитить; теги/`stash@{0}` не удалять).
- **Сохранить:** F1 IA, F2 токены/палитра §8, F3 селектор/scope, F4 §60 store §37–§42, F5 §61, F0 `persistItems`, F9 SaveBar, ADR-1025-12 D3 (`computeBottomOffset`), ADR-1025-12 D5 (нативные кнопки/`--header-h`), ADR-1024-24 (fullscreen-sync).
- **Явно:** новый токен/библиотека/сборка/Approved **не доказывают** выполнение — нужны воспроизводимые проверки фактического поведения (§12/§13).
- Флаги — env-only `ClassVar` (default ON), аддитивно в `GET /api/me.ui_flags`, **Δ каталога = 0**.

## 4. Интерфейсы и контракты (что Builder обязан соблюсти)

| Контракт | Тип | Требование |
|---|---|---|
| `--app-usable-height` | новая CSS-переменная | **единственный** источник высоты; JS-inline в TMA, CSS-фолбэк `100vh`/`100dvh` |
| `--shell-h` | алиас | `var(--app-usable-height)`; маркеры/тесты не ломать |
| `--tg-viewport-bottom-offset` | сохранён | задаётся `computeBottomOffset`; **не** применяется к `.bottom-nav` |
| `--header-h` | сохранён | ResizeObserver; единственный верхний резерв |
| `--shell-*` | AMEND значений | §8 (графит); `--shell-texture` удалён |
| `window.__computeTgBottomOffset` | сохранён | юнит-тесты/матрица |
| `web/static/vendor/*` | новые файлы | фикс-версия + лицензия + sha256 + команда сборки в `README.md` |
| `GET /api/me.ui_flags` | аддитивно | новые флаги; каталог не трогается |
| `#lg-lens`, `[data-glass]` | сохранены | deny-list/тиры не расширяются |

## 5. Совместимость и откат

- **Backward compatibility:** старый WebView без `dvh`/`min()` → `--app-usable-height: 100vh`; без JS → CSS-фолбэк; `.more-sheet` сохраняет собственную компенсацию; существующие `#/modules/*`-маршруты F5 не затрагиваются.
- **Кеш:** bump `APP_VERSION` 2.58.11 → 2.58.12; `?v=__APP_VERSION__` для новых vendor-бандлов.
- **Hard-откат:** тег `pre-round1025-hotfix9` (T-2790) + `git revert` коммитов пакета + возврат версии/`?v=`.
- **Soft-откат (env-only, без редеплоя):** `UI_SHELL_FLEX_V3`, `UI_SHELL_GRAPHITE_V3`, `UI_LIQUID_GLASS_LIB`, `UI_AURORA_FLOW_V2` (+ наследуемые hotfix6/7/8-флаги).
- Поэтапная раскатка 10/50/100 % **не применяется** (один прод; §53–§62).

## 6. Верификация (§12, обязательная)

- **Playwright+DOM** (`tools/ui_round1025_matrix.py`, 10 вьюпортов × 5 режимов): фиксация `viewport width/height`, Telegram `viewportHeight`/`viewportStableHeight`, `visualViewport.height`, `safeAreaInset`, `contentSafeAreaInset`; `BoundingClientRect` для Header/селектора/первой карточки/bottom-nav/modal/SaveBar/последнего поля; отсутствие недопустимых пересечений; видимость; нажатие через `elementFromPoint()`; доступность последнего поля после прокрутки; корректный resize в fullscreen; `scrollWidth ≤ innerWidth+1`; `rect.bottom ≤ innerHeight (+stable)`.
- **Фон:** кадры **0/5/10/20 с** + программное сравнение пикселей фоновой области (движение существует и не микроскопично).
- **Стекло:** отдельный прототип на контрастном/реальном фоне; сопоставление фона без стекла и через стекло (меняется ли содержимое **позади**).
- **pytest** (baseline 8272/0), JS-маркеры, `node --check web/app.js`+`telegram-init.js`, `git diff --check`; red→green для новых проб; AA-таблица §8/§9.
- **Живой Telegram WebView** — **PENDING OWNER VERIFICATION**; не воспроизводимо headless, **не** объявляется пройденным и **не** останавливает workflow (§12/§15).

## 7. Зависимости

- T-2790 (baseline/тег) → T-2791/T-2792 (этот spec/ADR) → блоки A→B→C→D→E→F→G→H (порядок §2 UPD3: геометрия раньше визуальных эффектов) → I (проверки) → J (сердцебиение) → K (деплой/аудит/продолжение F6).
- F6 `memory-analytics-reorg-round1025` — ⏸ до завершения HOTFIX9 (T-2839).
