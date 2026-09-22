# ADR-1025-18 — Контракт `GlassSurface` (откат точечного монтирования), единая рабочая поверхность Main, единая модель высоты без двойного safe-area, явный `resize` OGL-фона

- **Статус:** Proposed → **Approved** (Step 2 @Architect, 22.09.2026; human gate не требуется — UPD4 §8).
- **Дата:** 2026-09-22
- **Раунд:** 10.25, внеплановый приоритетный пакет **hotfix10** `hotfix10-liquidglass-rollback-shell-geometry-round1025` (T-2840…T-2869), Волна 1.9.
- **Связано:** `spec.md` этой папки; **UPD4** `plans/current_task.md:7267-7482`; `plans/ARCHITECTURE.md` §63; **AMEND ADR-1025-17 (D5, D6)**; **уточнение ADR-1025-16, ADR-1025-13, ADR-1025-9**; сохранить ADR-1025-12 (D3 `computeBottomOffset`, D5), ADR-1024-24 (fullscreen-sync), ADR-1025-2 (F0), ADR-1025-1 (F1), ADR-1016-2/ADR-1024-13 (CSP/zero-build/`ui_flags`).
- **Затрагивает:** `web/static/glass.js`, `web/app.js`, `web/static/app.css`, `web/static/aurora-flow.js`, `web/static/telegram-init.js`, `web/index.html`, `config/settings.py` (env-only `ClassVar` + `APP_VERSION`), `web/api/routes.py` (аддитивно, без смены контракта), `tools/ui_round1025_matrix.py`, тесты `tests/**`, отчёты `plans/reports/`.

## Контекст

UPD4 фиксирует, что интеграция Liquid Glass (hotfix9/ADR-1025-17 D5) и геометрия AppShell дали видимые прод-дефекты: белые непрозрачные прямоугольники на функциональных Vue-компонентах (`.scope-trigger`/`.header-fs-btn`/`.status-block`) из-за `mountGlass()` без источника преломления (авторежим → frosted-fallback), неполный `disposeAll` (`.ps-glass*` не удаляются), широкая яркая вертикальная полоса между Sidebar и рабочей областью (сочетание `padding-left:216px` + центрирование `max-width:1440px` без подложки), обрезание нижней навигации при двойном учёте safe-area, а в fullscreen — фон со смещённой влево цветной полосой, статичной заливкой и без анимации (`resize` фона не экспортируется и не вызывается при fullscreen/viewport-смене).

**Перепроверка по коду (Step 2 @Architect, актуальный рабочий tree):** `glass.js:15,26-34,56`; `app.js` `_syncGlassLib:10132-10138`, `_syncBgLayer:10113-10128`, `_lgSchedule:10031-10047`, `_lgObserver:10054-10067`, `$nextTick:2775-2778`, `_onResize:2829-2836`, `setFullscreenFromTma:6080-6099`, `onVisibilityChange:10139-10148`; `settings.py:757-763` (`UI_SHELL_FLEX_V3`/`UI_LIQUID_GLASS_LIB`/`UI_AURORA_FLOW_V2` default True), `APP_VERSION=2.58.12` (`:1734`); `app.css` `.app-shell.ia-v2:1910`, `main.scroll-area:1932-1934`, `.module-list:493-498/2137-2138`, `.module-quick-wrap:2168-2170`, `.module-toolbar:2198-2201`, `.fullscreen-mode .scroll-area:1038-1043`, `.more-sheet:2033-2053`, `.bottom-nav:1971-1995`, `.status-block:1116`, `.aurora-flow-canvas:256-259`; `telegram-init.js:36-49,51-85`; `aurora-flow.js` `resize:74-89`, `initGL:91-140`, `start:249-267`, `loop:236-247`, экспорт `:312-323` (без `resize`).

**Инварианты:** Δ DDL = 0; Δ каталога = 0 (459/98/96/21/418); CSP `script-src 'self'`; R17/R18; сохранить flex-геометрию shell/§63, графит-токены §8, удаление `--shell-texture`, дизайн сердцебиения, `computeBottomOffset`, F0/F1/F3/F4 §60/F5 §61/F9, ADR-1024-24.

## Решение

### D1. Немедленный откат стекла; `GlassSurface` как единственный путь
- `UI_LIQUID_GLASS_LIB` **default → OFF**; флаг **сохраняется** (env-only kill-switch), vendored-бандл и модуль не удаляются.
- `TARGETS` не содержит функциональных целей; `mountGlass` вызывается только для `[data-glass-surface]`.
- `disposeAll` удаляет **все** `.ps-glass*` и `data-lg-mounted`/`data-lg-failed`; идемпотентен.
- Full reload (cache-bust через bump `APP_VERSION`) + точечная чистка остатков **только** экспериментальной интеграции.
- Контракт `GlassSurface`: контейнер задаёт геометрию; декор — `position:absolute; inset:0; pointer-events:none; aria-hidden`; контент `position:relative; z-index:1`; `isolation:isolate`; `contain:layout paint`. Гарантии: геометрия неизменна, клики не перехвачены, mount/unmount идемпотентны, после unmount нет `.ps-glass*`.
- Применение — **на одном изолированном декоративном элементе** (новый презентационный `[data-glass-surface]` на странице «Статус», без данных/контролов). Режим честно маркируется: `refraction` только при живом источнике позади, иначе `frosted`.

### D2. Единая рабочая поверхность Main
- `max-width:1440px; margin-inline:auto` снимается с `main.scroll-area`; подложка (`--work-surface-bg`) — на `main.scroll-area`, от края sidebar (216 px) до правого края вьюпорта. Полоса исчезает без отрицательных отступов.
- Лимит карточек 1100 px сохраняется на `.module-list`/`.module-quick-wrap`/`.module-toolbar`/`.module-catalog .module-list`.
- Фиксированный canvas остаётся за контентом и не ограничен `max-width` контентных колонок. Порядок слоёв: фон → графит sidebar/header → рабочая поверхность → карточки → модалки.

### D3. Единая модель высоты; safe-area ровно один раз
- Единственный источник — `--app-usable-height`; формула `computeBottomOffset` сохраняется; входные метрики берутся из фактически измеренных значений (без допущения о `innerHeight`).
- Снимается второй вычет: `.fullscreen-mode .scroll-area` `padding-bottom` без `env(safe-area-inset-bottom)`.
- Legacy-правила выводятся из активного режима: `.bottom-nav`-fixed остаётся только под `.shell-layout-legacy`; `.more-sheet` перестаёт складывать `max(safe-area…)` + `--tg-viewport-bottom-offset`.
- Приёмка: 4 пункта nav с подписями видны и нажимаемы. Живые значения инсетов — PENDING OWNER VERIFICATION.

### D4. `.status-block` без стекла
Стеклянный слой убирается (следствие D1); дизайн сердцебиения не меняется; проверяются высоты родителей/`overflow` и полная видимость данных.

### D5. OGL-фон: `resize` + пересчёт buffer/viewport/uniforms + анимация
- `__AuroraFlow` экспортирует `resize`; вызов из `_onResize`, `setFullscreenFromTma`, на `visualViewport`/`viewportChanged` и (опц.) `ResizeObserver`.
- `setSize` + drawing buffer + `gl.viewport` + `uRes` считаются по фактическому размеру контейнера, единицы согласованы; старые размеры не остаются.
- rAF продолжает работу после fullscreen; `uTime` обновляется; canvas не замирает на 1-м кадре; рендер не остановлен ошибочно hidden/reduced-motion; возобновляется после скрытия. Реализация OGL сохраняется; CSS-градиенты поверх WebGL не добавляются.

### D6. Инварианты, флаги, доказательность
- Флаги env-only `ClassVar` (default ON, кроме стекла → OFF): `UI_SHELL_FLEX_V3`, `UI_SHELL_GRAPHITE_V3`, `UI_AURORA_FLOW_V2`, `UI_LIQUID_GLASS_LIB` = **OFF**. Δ каталога = 0.
- Успешная сборка, наличие `requestAnimationFrame` в исходниках, подключение/отключение библиотеки и вердикт Reviewer **не доказывают** устранение визуального дефекта; принятие — по воспроизводимым проверкам (spec §9/§11).

## AMEND / SUPERSEDE / сохранить

| Ранее | Действие | Что именно / почему |
|---|---|---|
| **ADR-1025-17 D5** (настоящее преломление точечно на `.scope-trigger`/`.header-fs-btn`/`.status-block`) | **AMEND (откат)** | Прямое монтирование на функциональные Vue-компоненты прекращается (UPD4 §1/§2); эффект возвращается только через изолированный `GlassSurface`; frosted не выдаётся за рефракцию |
| **ADR-1025-17 D6** (Dark Aurora Flow, OGL) | **AMEND (без смены реализации)** | Пересматриваются позиционирование/размеры/viewport/uniforms canvas и вызов `resize`; сама реализация OGL сохраняется |
| **ADR-1025-13 D1** (`--app-usable-height` — источник; flex normal/fullscreen) | **Уточнение** | Источник сохраняется; снимается двойной вычет safe-area, выводятся legacy `.more-sheet`/`.fullscreen-mode .scroll-area` |
| **ADR-1025-13 D4** / **ADR-1025-16 D4** (выравнивание shell/mobile) | **Уточнение** | Единая рабочая поверхность Main; без отрицательных отступов; лимит 1100 px сохраняется |
| **ADR-1025-9 D2** (Liquid Glass A/B/C, `data-glass`) | **Уточнение** | Контракт `GlassSurface` заменяет прямое монтирование; deny-list/тиры/палитра §8 не меняются |
| **ADR-1025-9 D3** (фон §10: `@property --grad-angle` + `grad-spin`/`grad-drift`) | **Сохранить** | Механика/цвета §10 сохраняются; Dark Aurora Flow остаётся основным фоном |
| **ADR-1025-12 D3** (`computeBottomOffset` = max трёх инсетов) | **НЕ отменяется** | Формула сохраняется; устраняется **двойной** учёт, а не расчёт |
| **ADR-1025-12 D5** (нативные кнопки, `--header-h`, fullscreen) / **ADR-1024-24** | **НЕ отменяется** | Компоновка шапки; источник истины fullscreen — TMA |
| **flex-геометрия shell/§63, графит-токены §8, удаление `--shell-texture`** | **Сохранить** | Не переписываются; shell остаётся графитовым, sidebar/header — без стекла |
| **Дизайн сердцебиения §11/ADR-1025-13 D2** | **Сохранить** | Меняется только наличие стеклянного слоя на карточке (снят) |
| **F0 `persistItems`, F1 IA, F3 селектор/scope, F4 §60 store §37–§42, F5 §61, F9 SaveBar** | **НЕ отменяются** | Логика не переписывается |
| **Δ DDL = 0, Δ каталога = 0, CSP, R17/R18** | **НЕ отменяются** | Инварианты |
| **ADR-1025-18** | **НОВЫЙ, Approved** | Этот документ (Step 2 @Architect) |

## Последствия

**Positive:** устранён видимый дефект (белые прямоугольники) без «лечения прозрачностью»; стекло получает явный, идемпотентный, проверяемый контракт на изолированном элементе; единая рабочая поверхность Main без яркой полосы и без отрицательных отступов; safe-area учитывается ровно один раз, nav целиком виден; фон пересчитывает геометрию при fullscreen/viewport-смене и реально анимируется; инварианты, IA и прецеденты сохранены.

**Negative/издержки:** реальные значения инсетов, геометрия fullscreen и FPS на живом Telegram WebView **не воспроизводимы headless** → обязательна live-проверка владельца (PENDING OWNER VERIFICATION); визуальные правки требуют атомарного обновления маркеров тестов; честный frosted-режим может не дать «эффекта рефракции» — это осознанное ограничение, а не дефект.

**Ограничения:** Δ DDL = 0; Δ каталога = 0; CSP/zero-build; WebGL — только фоновый canvas; `backdrop-filter: url()` как опора запрещён; `current_task.md` не изменяется (R18).

## Альтернативы

| Альтернатива | Почему отклонена |
|---|---|
| Оставить монтирование на 3 функциональные цели и «подкрутить» режим | UPD4 §1/§2 прямо прекращают монтирование на функциональные компоненты |
| Удалить `UI_LIQUID_GLASS_LIB` и vendored-бандл | Лишает мягкого отката и требует редеплоя для контролируемого повторного включения; «не удалять ассеты» |
| Снизить `opacity`/ослабить `--glass-paper` белых слоёв | Прямо запрещено UPD4 §1 |
| Добавить отрицательный `margin-left`/`pull` для устранения полосы | Прямо запрещено UPD4 §3 |
| Компенсировать полосу дополнительным CSS-градиентом | Прямо запрещено UPD4 Доп.P0 |
| Переписать фон (новые эффекты/шейдеры) | UPD4 §6: сохранить OGL, чинить геометрию/анимацию |
| Второй источник высоты рядом с `--app-usable-height` | Прецедент ADR-1025-13 F-2: конкурирующие источники → скачки в fullscreen |
| Оставить `.more-sheet`/`.scroll-area` с прежним двойным offset | Сохраняет двойной учёт safe-area (UPD4 §4) |
| Применять `GlassSurface` на селекторе/⛶/карточке | Прямо исключено UPD4 §2 на этом этапе |
| Каталоговые тумблеры | Δ каталога ≠ 0; только env-only `ClassVar` |
| Human gate по выбору декоративного элемента | Не user-owned tradeoff; UPD4 §8 не требует gate |

## Верификация

- **DOM/Playwright** (`tools/ui_round1025_matrix.py`): отсутствие `.ps-glass*` при OFF и после unmount; rects/`elementFromPoint` без изменений при ON на одном элементе; нет яркой полосы между sidebar и рабочей областью; карточки ≤1100 px; 4 пункта nav с подписями (hit ≥44×44); `rect.bottom ≤ innerHeight`; инсеты в отчёте; кадры фона 0/5/10/20 с (числовое движение, заметно за 5–10 с); normal/fullscreen/resize.
- **JS/node-юниты:** `computeBottomOffset` без смены семантики; `disposeAll`/`sync` идемпотентны; `__AuroraFlow.resize` экспортирован и безопасен; `node --check web/app.js`+`web/static/*.js`.
- **Инварианты:** Δ DDL = 0; Δ каталога = 0 (459/98/96/21/418); CSP (`script-src 'self'`, без CDN/инлайна); `backdrop-filter: url(` = 0 в авторском CSS; `--shell-texture` = 0; `persistItems`; F1/F3/F4/F5/F9; `git diff --check`; pytest baseline 8291/0.
- **Только реальный Telegram WebView (владелец, PENDING OWNER VERIFICATION):** фактические `innerHeight`/`visualViewport.height`/`viewportHeight`/`viewportStableHeight`/`safeAreaInset.bottom`/`contentSafeAreaInset.bottom`; nav целиком в экране; fullscreen-фон анимирован и целен; FPS. **Не воспроизводимо headless** — не объявляется пройденным и не останавливает workflow (UPD4 §7/§8).

## Откат

- **Hard:** тег `pre-round1025-hotfix10` (T-2840) + `git revert` коммитов пакета + возврат `APP_VERSION`/`?v=`.
- **Soft (env-only, без редеплоя):** `UI_LIQUID_GLASS_LIB=false` (default уже OFF), `UI_AURORA_FLOW_V2=false` (legacy CSS-aurora), `UI_SHELL_FLEX_V3=false` (`.shell-layout-legacy`), `UI_SHELL_GRAPHITE_V3=false`.
- Бэкапы/теги/`stash@{0}` не удалять (R18).
