# ADR-1025-13 — Стабильная геометрия shell/fullscreen, отдельный серо-графитовый стеклянный shell-слой, premium-визуал Canvas-2D сердцебиения

- **Статус:** Proposed → **Approved** (Step 2 @Architect, 22.09.2026; human gate отключён — решения приняты и обоснованы).
- **Дата:** 2026-09-22
- **Раунд:** 10.25, внеплановый хотфикс-7 `hotfix7-shell-glass-heartbeat-round1025` (T-2658…T-2694)
- **Связано:** `spec.md` этой папки; ТЗ UPD 1–7 (`plans/current_task.md:6073-6154`); `plans/ARCHITECTURE.md` §54/§56/§57/§58; ADR-1025-12 (D1/D2/D3/D4/D5), ADR-1025-9 (D2/D3/D4), ADR-1025-8/hotfix4, ADR-1025-10 (F3), ADR-1025-1 (F1), ADR-1024-24 (fullscreen-sync), ADR-1024-13 (`ui_flags`), ADR-1016-2 (CSP/zero-build), ADR-1025-2 (F0 save-path)
- **Затрагивает:** `web/static/app.css`, `web/index.html`, `web/app.js`, `web/static/telegram-init.js`, `config/settings.py` (env-only `ClassVar` + `APP_VERSION`), `web/api/routes.py` (аддитивно `ui_flags`), `tools/ui_round1025_matrix.py`, тесты (`tests/**`, `tests/js/**`), отчёты `plans/reports/round1025_hotfix7_*.md`

## Контекст

После hotfix6 (§58, deploy `ba75751`, `APP_VERSION` 2.58.7) живая приёмка владельца выявила три прод-деградации, оформленные как UPD «Срочный фикс текущего фронта» (UPD 1–6):

- **Shell слился с карточками.** `.app-sidebar` (`app.css:1570`), `.app-drawer` (`:1593`), `.bottom-nav` (`:1618`), `.more-sheet` (`:1668`) и `header` (`:751`) используют **тот же контентный токен**, что карточки `.card/.module-card/.hub-card` (`:1037`, `--glass-bg = rgba(21,27,42,.5)`), с одинаковым blur/бордером/тенью. Требование «сохранить панели серыми и визуально отличимыми» не выполнено: shell — отдельный слой интерфейса, а не «ещё одна карточка».
- **«Дешёвый» виджет §15.** `_hbDraw` (`app.js:6635-6678`) рисует бегущую синусоиду плюс сдвигающийся вбок отрезок-импульс (`pulseX`) — «линия + плавающая точка», без мониторингового языка.
- **«Грязный» вид.** Тяжёлая `--glass-shadow rgba(3,7,18,.75)` (`:60`), плотный `body::before opacity .42` (`:126-138`), плотная подложка `.85` дают ощущение виньетки/грязного затемнения, а не премиального стекла.
- **Нестабильная геометрия/fullscreen.** `.app-shell` одновременно `min-height: var(--tg-viewport-stable-height,100vh)` (`:805-810`) и `.fullscreen-mode { height:100dvh; overflow:hidden }` (`:819-828`): два конкурирующих источника высоты. При расхождении `stable-height` и `dvh` flex-колонка переполняет shell, `overflow:hidden` обрезает низ; в старых WKWebView без `dvh` — скачок. Виджет «Сердцебиение» в fullscreen исчезает/обрезается. **Точный сценарий не воспроизводится headless — только реальный WebView.**

**Инварианты:** Δ DDL = 0, Δ каталога = 0, CSP/zero-build, запрет WebGL (Canvas 2D разрешён), env-only UI-флаги, нативные кнопки Telegram CSS не двигать, IA F1 и store-контракт F4 §37–§42 не ломать, write-path F0 `persistItems` не переписывать, R17/R18.

## Решение

### D1. Единый источник высоты shell + два явных режима (UPD 1)

- Вводится токен-сток `--shell-h`: базовое значение — **всегда валидный `100vh`**; апгрейд до `min(100dvh, var(--tg-viewport-stable-height, 100dvh))` — **только внутри `@supports (height: 100dvh) and (height: min(100dvh, 100dvh))`**. Причина (ред. review F-2): значения custom properties не валидируются при разборе, и прежняя цепочка `100vh → 100dvh → min(…)` в WebView без `dvh`/`min()` давала invalid at computed-value time → initial `auto` (а в fullscreen — `height:auto`), а не `100vh`. Теперь старый движок не заходит в `@supports` и остаётся на `100vh`. В TMA берётся **минимум** из `dvh` и видимой высоты → shell не выше видимой области (устраняет обрезку низа).
- **Normal** (`.app-shell:not(.fullscreen-mode)`): `min-height: var(--shell-h); height:auto; overflow:visible` — нативный скролл страницы, header `sticky`.
- **Fullscreen** (`.fullscreen-mode`): `height/max-height: var(--shell-h); min-height:0; overflow:hidden`; единственный скроллер — `.scroll-area` (`overflow-y:auto; min-height:0`). Конкурирующие `min-height`/`height` с разными значениями **запрещены**.
- Зафиксирован stacking/z-index: фон < контент < shell (30) < sticky-header (40) < bottom-nav/drawer (40) < more-sheet (50) < модалки. Heartbeat — в слое контента, без собственного z-index и без клиппинга контейнера.
- **Явная гарантия:** heartbeat виден во всех режимах, включая fullscreen; `.status-block__pulse/.hb-wrap/.hb-canvas` не схлопываются. Проверка — Playwright 5 режимов + реальный WebView (live-гейт).

### D2. Premium-визуал сердцебиения: ECG sweep-wipe на Canvas 2D (UPD 2, AMEND ADR-1025-12 D4)

- **Стек сохраняется:** Canvas 2D + один rAF (`startHeartbeatCanvas/_hbFrame/_hbDraw`), DPR-масштабирование, пауза по `document.hidden` и вне вкладки «Статус». Меняется **только рендер** `_hbDraw`.
- **Форма сигнала** — реалистичный кардиокомплекс (зубцы P/Q/R/S/T как сумма гауссиан), не синусоида.
- **Развёртка sweep-wipe** (как на реальном мониторе): «луч» идёт слева-вправо за `sweepPeriod`, позади луча трасса яркая, впереди — приглушённая изолиния. **Нет** горизонтального переноса всей линии и «плавающей точки» (устраняет `pulseX`). Число комплексов на проход и период зависят от состояния (норма/warning/critical), а не от выдуманного BPM.
- **Свечение/пульс:** `shadowBlur` (с ограничением) для трассы и «головы луча»; вспышка-взрыв на R-пике при проходе лучом; медленное «дыхание» яркости. Бледная сетка монитора (опционально кэш).
- **Цвет/интенсивность** (статус-токены §8, читаются из CSS-переменных, кэш на смену состояния): HEALTHY — green `#3DD68C` (`--ok`, тот же источник, что бейдж `.hb-healthy`; ред. review F-3); WARNING — amber `#F6C56F` (`--warn`); CRITICAL — red-pink `#F07178` (`--err`); UNKNOWN — muted `#A2B0C6` (`--text-3`) без glow. Альфа свечения — **лестница по состоянию** (`.45/.60/.85/0`) плюс множитель `shadowBlur` (`×0.9/×1.1/×1.5`), CRITICAL заметно сильнее (ред. review F-4). Интенсивность — производная от `hbState`/`hbEma`.
- **Семантика ADR-1025-12 D4 сохраняется полностью:** `_heartbeatTransition`/`heartbeatSample`, EMA/гистерезис/dwell, `missing ≠ bad`, UNKNOWN, тултип, поллинг 30 с (`/api/status`, без нового поллера), `UI_HEARTBEAT_CANVAS_ENABLED` OFF → legacy SVG байт-в-байт, lifecycle, reduced-motion-статика, отсутствие общего overflow (C1).
- **Бюджет:** один rAF, кламп `dt`, DPR cap = 2, ограниченный glow, пауза в фоне. Замер FPS — live-гейт.
- **Флаг:** `UI_HEARTBEAT_PREMIUM` (default ON) — OFF → текущий canvas-рендер (синусоида+импульс).

### D3. Отдельный серо-графитовый glass-shell + рецепт liquid glass (UPD 3–4, уточнение ADR-1025-9 D2)

- Вводятся **новые shell-токены**, не совпадающие с карточными: `--shell-bg rgba(33,37,45,.62)`, `--shell-bg-strong rgba(24,28,35,.90)`, `--shell-border-color`, `--shell-highlight`/`-soft`, `--shell-shadow` (мягче карточной), `--shell-blur blur(18px) saturate(120%)`, `--shell-specular`, `--shell-texture`, `--card-shadow` (карточки — тоньше/ближе к фону). Значения — в `spec.md` D3.1.
- Shell-панели (`.app-sidebar`, `.app-drawer`, `header`, `.bottom-nav`, `.more-sheet`) переходят на `--shell-*`; header — `--shell-bg-strong`. Карточки остаются на `--glass-bg` с лёгкой `--card-shadow`. `@supports not (backdrop-filter)` даёт плотные фолбэки (shell → `--shell-bg-strong`, карточки → `--glass-bg-strong`).
- **Рецепт glass:** base + backdrop blur + мягкая внутренняя подсветка (два inset) + тонкая светлая обводка + слабый specular (≤.12) + аккуратная faux-noise текстура (CSS-градиенты, alpha ≤.02, **без data-URI/ассетов/WebGL**) + разделение глубин «фон → карточки → shell».
- **Удаление «грязи»:** `--glass-shadow` alpha `.75 → ~.55`; карточкам `--card-shadow`; `body::before opacity .42 → .30` (reduced-motion `.26`). Механика/цвета/длительности §10 **сохраняются** (нет оранжевого, 60–90 с / 90–120 с).
- **Контраст AA ≥ 4.5:1** — обязательная пересчитанная таблица (метод ADR-1025-9 D4 / hotfix6) в `round1025_hotfix7_contrast.md`; при провале повышается плотность токена, **не** палитра §8.
- **Панели остаются в glass-set** (blur), deny-list tier C и foreground-линза ADR-1025-12 D1 не затрагиваются.
- **Флаг:** `UI_SHELL_GLASS_V2` (default ON) — OFF → shell на общих карточных токенах.

### D4. Выравнивание shell: header / sidebar / mobile (UPD 5)

- Header — двухстрочный компактный (hotfix6 D5, `UI_HEADER_COMPACT_V2`) поверх `--shell-bg-strong`; `--header-h` (ResizeObserver) — единственный источник резерва; без наезда на контент и нативные кнопки; переполнение — `ellipsis`/перенос без горизонтального скролла.
- `.app-sidebar`/`.app-drawer`/`.bottom-nav`/`.more-sheet` — единый shell-слой (общие тон/граница/радиус/глубина/blur), drawer 768–1199 корректен.
- Mobile: `env(safe-area-inset-*)` + `--tg-safe-area-inset-*` + `--tg-content-safe-area-inset-*`, `viewport-fit=cover`; `--tg-viewport-bottom-offset` = `computeBottomOffset()` = **max** трёх инсетов (ADR-1025-12 D3, сохраняется); порядок навигации hotfix4/F1 и fullscreen-sync ADR-1024-24 сохраняются. `rect.bottom <= innerHeight+1`.
- **Флаг:** `UI_SHELL_LAYOUT_V2` (default ON) — OFF → прежние высоты/выравнивание (независимый откат самого рискованного, не воспроизводимого headless изменения).

### D5. Инварианты и совместимость (UPD 6)

- Сохраняются без изменений: Δ DDL = 0; Δ каталога = 0; CSP/zero-build; запрет WebGL; R17/R18; IA F1; write-path F0 `persistItems`; store-контракт F4 §37–§42; deny-list tier C; fullscreen-sync ADR-1024-24; нативные кнопки + `--header-h`; палитра §8 и фон §10.
- Добавляются аддитивно три env-only флага в `config/settings.py` и `GET /api/me.ui_flags` (каталог не трогается).

## SUPERSEDE / AMEND

| Ранее | Действие | Что именно / почему |
|---|---|---|
| **ADR-1025-12 D2** (стекло панелей = `--glass-bg`) | **AMEND → D3** | Shell получает отдельные `--shell-*` (серо-графитовые), header — `--shell-bg-strong`; blur/saturate/тень панели отличаются от карточек. Сохраняются: панели в glass-set (blur), AA-гарантия, `@supports`-фолбэк, deny-list |
| **ADR-1025-12 D4** (визуал heartbeat) | **AMEND → D2** | Меняется **только рендер** (ECG sweep-wipe + glow). Сохраняются: Canvas 2D+rAF, телеметрия 30 с без нового поллера, state-machine/EMA/гистерезис/dwell, `missing≠bad`, UNKNOWN, «без выдуманного BPM», тултип, `UI_HEARTBEAT_CANVAS_ENABLED` OFF → legacy SVG, lifecycle, reduced-motion, C1 |
| **ADR-1025-9 D2** (значения токенов/уровни glass) | **Уточнение → D3** | Добавлен shell-слой `--shell-*`; карточный `--glass-bg` и палитра §8 не меняются; фон §10 (ADR-1025-9 D3) не отменяется |
| **ADR-1025-12 D1** (foreground-линза/feature-detect) | **НЕ отменяется** | Механизм преломления, tier-лестница, `UI_GLASS_TIER_OVERRIDE`, `UI_LENS_MAX_NODES` — без изменений |
| **ADR-1025-12 D3** (`computeBottomOffset` = max) | **НЕ отменяется** | Нижняя панель/шторка — прежняя компенсация |
| **ADR-1025-12 D5** (нативные кнопки, `--header-h`, fullscreen) | **НЕ отменяется** | Компоновка шапки сохраняется; fullscreen-sync ADR-1024-24 не переписывается |
| **ADR-1024-24** (fullscreen-sync) | **НЕ отменяется** | Источник истины — TMA |
| **ADR-1025-8/hotfix4, ADR-1025-10/F3, ADR-1025-1/F1** | **НЕ отменяются** (пока геометрия нижнего bar не меняется) | Порядок навигации, `viewport-fit=cover`, семантика селектора, IA |

## Последствия

**Positive:** предсказуемая геометрия shell в normal и fullscreen с единственным источником высоты; heartbeat виден во всех режимах; визуально отделённый серо-графитовый стеклянный shell (не «ещё одна карточка») с премиальным рецептом (base/blur/подсветка/обводка/specular/текстура/глубина); мониторинговый ECG-индикатор вместо «линии+точки»; контраст AA ≥ 4.5:1 доказан отдельной таблицей; три независимых env-отката; инварианты и IA не нарушены.

**Negative/издержки:** полная геометрия fullscreen и FPS glow/specular на слабом устройстве **не воспроизводимы headless** — обязателен live-гейт; ручная пересборка AA-таблицы; глазами владельца оценивается «премиальность» (риск приёмки); визуальные правки требуют атомарного обновления маркеров тестов.

**Ограничения:** Δ DDL = 0, Δ каталога = 0; без новых зависимостей/WebGL/data-URI/внешних ассетов; `services/**` не меняется; фон §10 (механика/цвета/длительности) и палитра §8 не переписываются.

## Альтернативы

| Альтернатива | Почему отклонена |
|---|---|
| Оставить `--glass-bg` для shell, лишь усилить контраст | Не решает корень («слияние» слоёв); shell неотличим от карточек по тону |
| Перекрасить shell в акцент/цвет карточек | Прямо нарушает UPD 3 («остаться серо-графитовыми», «не перекрашивать в цвет карточек») |
| Вернуть shell непрозрачным (tier C) | Убирает стекло, которое явно требуется UPD 4 |
| WebGL/шейдеры для «оптического» стекла | Запрещены инвариантом; Canvas 2D/CSS достаточно |
| Data-URI/SVG-шум для текстуры | CSP-риск и прецедент отказа (ADR-1025-9 D2, ADR-1025-12 D1); используем CSS-градиенты |
| Продолжать canvas-анимацию «линией+точкой», лишь перекрасить | Не решает UPD 2; остаётся «дешёвый» вид |
| Эквалайзер/столбики вместо ECG | Не отражает семантику «пульс/мониторинг состояния» (§15), менее читаемо с первого взгляда |
| Отдельный поллер/новая библиотека графиков | Рост нагрузки/зависимостей; секвенция §15 уже покрыта `/api/status` 30 с |
| Оставить `min-height`+`height:100dvh` и «подпереть» `!important` | Сохраняет конфликт двух источников высоты; корень не устранён |
| Фиксировать `.app-shell` высоту и в normal-режиме | Ломает нативный скролл страницы и IA (прецедент F1) |
| Ввести каталоговые тумблеры shell/heartbeat | Δ каталога ≠ 0 — нарушение инварианта; env-only `ClassVar` сохраняет нулевую дельту |
| Обойтись без флага для layout | Самое рискованное (не воспроизводимое headless) изменение осталось бы без мягкого отката |

## Верификация

- **Playwright (5 режимов: desktop normal, desktop fullscreen, tablet, mobile regular, mobile fullscreen; + 10 вьюпортов §71):** `.app-shell.fullscreen-mode` активен в fullscreen-режимах; `.hb-canvas` присутствует, `visible`, `rect.h ≥ 1`, внутри вьюпорта; heartbeat не обрезан; computed `background-color`/`border-color`/`box-shadow` shell-панелей **≠** карточных; `--shell-bg` существует и `≠ --glass-bg`; `body::before` opacity ≤ 0.32; alpha теней ≤ порога; `backdrop-filter: url(` — 0 совпадений; `scrollWidth <= innerWidth+1`; `rect.bottom <= innerHeight+1`; glass allow/deny и reduced-motion сохранены. **Фолбэк `--shell-h` (review F-2):** проба `f2ShellH` повторяет prod-структуру и на синтетическом стенде эмулирует отсутствие `dvh` (заведомо неподдерживаемая единица в `@supports`-условии) — базовый `100vh` обязан дать высоту вьюпорта, а прежняя цепочка объявлений — схлопнуться; `.app-shell` не должен получить `min-height:auto`.
- **JS/node-юниты:** `_heartbeatTransition`/`heartbeatSample` (пороги/гистерезис/UNKNOWN/reduced-motion) — без изменения семантики; `computeBottomOffset` (max/guard/нули); рендер — наличие ECG-формы/`sweep` и отсутствие `pulseX`-паттерна; `node --check web/app.js` + `telegram-init.js`.
- **AA:** обязательная таблица «пара → эффективный фон → ratio → PASS/FAIL» в `plans/reports/round1025_hotfix7_contrast.md` (worst-phase §10).
- **Инварианты:** Δ DDL = 0; Δ каталога = 0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418); CSP/zero-build; отсутствие WebGL; нативные кнопки/`--header-h`/fullscreen-sync; IA/маршруты; `persistItems`; store-контракт F4 §37–§42; `git diff --check`.
- **Только реальный Telegram WebView (владелец, T-2682/live-гейт):** mobile fullscreen — heartbeat виден, header цел, glass качественный, sidebar/topbar серые и отделены, ничего не съезжает; FPS glow/specular на слабом устройстве.
- **Не воспроизводимо headless (зафиксировать):** точное поведение fullscreen внутри TMA, реальные `safeAreaInset`/`contentSafeAreaInset`, геометрия нативных кнопок, устройство-зависимый FPS.

## Откат

- **Hard:** тег `pre-round1025-hotfix7` (T-2658) + `git revert` коммитов пакета + возврат `APP_VERSION`/`?v=`.
- **Soft (env-only, без редеплоя):** `UI_SHELL_GLASS_V2=false` (shell → карточные токены); `UI_HEARTBEAT_PREMIUM=false` (canvas → синусоида+импульс) и/или `UI_HEARTBEAT_CANVAS_ENABLED=false` (legacy SVG); `UI_SHELL_LAYOUT_V2=false` (прежние высоты/выравнивание).
- Бэкапы/теги/`stash@{0}` не удалять (R18).
