# SPEC — hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (Волна 1.9, P0)

- **ТЗ:** **UPD4** `plans/current_task.md:7267-7482` (прочитан дословно на Step 1/Step 2; файл **не изменялся**, untracked — R17/R18). Обязательный объём: §1–§8 + «Дополнительный P0-багфикс: фон в полноэкранном режиме».
- **Задачи:** T-2840…T-2869 (`tasks.md` этой папки). Step 2 = T-2841/T-2842 (этот spec + ADR-1025-18 + AMEND-карта).
- **Baseline:** HEAD `5184584` (== `origin/master`), `APP_VERSION` **2.58.12**, pytest **8291/0**, **Δ DDL=0**, **Δ каталога=0** (459/98/96/21/418). Живой Telegram WebView — **не проводился** (**PENDING OWNER VERIFICATION**).
- **Статус:** design (Step 2 @Architect), human gate **не требуется** (UPD4 §8: «не создавать Human Gate ради завершения хотфикса»).
- **Связано:** `plans/ARCHITECTURE.md` §63; `ADR-1025-17` (D5/D6 — AMEND), `ADR-1025-16`/`ADR-1025-13`/`ADR-1025-9` (уточнение), `ADR-1025-12` (D3/D5 — сохранить), `ADR-1024-24` (сохранить), `ADR-1016-2`/`ADR-1024-13` (CSP/zero-build/`ui_flags`); новый **ADR-1025-18**.

## 1. Проблема (по факту кода, перепроверено Step 2)

| # | Дефект | Корень (файл:строка) |
|---|---|---|
| P1 | Непрозрачные светлые прямоугольники на `.scope-trigger`/`.header-fs-btn`/`.status-block` | `web/static/glass.js:15` `TARGETS` = `.scope-trigger, .header-fs-btn, .status-block`; `mountGlass(el, optsFor(el))` (`:56`) **без `refract`/`source`** → авторежим → белый frosted-fallback (`.ps-glass__tint`, `color-mix(--glass-paper #fff)`). `disposeAll` (`:26-34`) делает только `inst.dispose()` + снятие `data-lg-mounted`, **`.ps-glass*` не удаляет** |
| P2 | Библиотека монтируется на функциональные Vue-компоненты | `web/app.js` `_syncGlassLib` (`:10132-10138`) → `__LiquidGlass.sync()`; `_syncBgLayer` (`:10127`); `$nextTick` (`:2775-2778`); `_lgSchedule` (`:10031-10047`); `MutationObserver` (`:10054-10067`); флаг `config/settings.py:760-761` `UI_LIQUID_GLASS_LIB` **default True** |
| P3 | Широкая яркая вертикальная полоса между Sidebar и рабочей областью | `.app-shell.ia-v2 { padding-left:216px }` (`app.css:1910`) + `main.scroll-area { max-width:1440px; margin-inline:auto }` (`:1932-1934`): при широком вьюпорте контент центрируется, между sidebar (216 px) и контентом остаётся полоса, где просвечивает фиксированный canvas; собственной подложки у `.app-shell`/`main` нет. Вложенные лимиты 1100 px: `.module-list` (`:493-498`,`:2137-2138`), `.module-quick-wrap` (`:2168-2170`), `.module-toolbar` (`:2198-2201`) |
| P4 | Обрезание нижней навигации / двойной safe-area | `telegram-init.js` `computeBottomOffset` (`:36-49`) = `max(...)`; `applyInsets` (`:51-85`); `--app-usable-height` (`:82-84`). **Второй вычет:** `.fullscreen-mode .scroll-area { padding-bottom: calc(1rem + env(safe-area-inset-bottom)) }` (`app.css:1042`) и `padding-bottom: max(env(safe-area-inset-bottom), …)` на sidebar/drawer (`:1914`,`:1945`). `.more-sheet` (`:2033-2053`) всё ещё `position:fixed` и складывает `max(safe-area…) **+** var(--tg-viewport-bottom-offset)` (`:2036-2038`) — та же зона дважды. Legacy `.bottom-nav` (`:1989-1995`) — вне активного пути (`.shell-layout-legacy`), но требует подтверждения |
| P5 | Экспериментальный стеклянный слой на `.status-block` | на HEAD `data-glass` у карточки нет (`index.html:3276`), но `mountGlass` добавляет `.ps-glass*` внутрь `.status-block`; CSS `.status-block { max-width:100%; overflow:hidden }` (`app.css:1116`) |
| P6 | Фон в fullscreen: полоса слева / статичная заливка / нет анимации | `aurora-flow.js` `resize` (`:74-89`) считает по `window.innerWidth/innerHeight` (не по фактическому контейнеру/`visualViewport`), `setSize(w,h)` + `uRes=[pw,ph]` — разные единицы; **`__AuroraFlow` (`:312-323`) не экспортирует `resize`**; `app.js` `_onResize` (`:2829-2836`) и `setFullscreenFromTma` (`:6080-6099`) **не вызывают** resize фона → после fullscreen остаются старые размеры drawing buffer/viewport/uniforms |

## 2. Scope / Out of scope

**In scope:** откат стеклянной интеграции с функциональных целей и корректный `disposeAll`; контракт `GlassSurface` и применение на **одном** изолированном декоративном элементе; единая рабочая поверхность Main без полосы; единая модель высоты и устранение двойного вычета + вывод legacy-правил из активного режима; восстановление `.status-block`; экспорт/вызов `resize` OGL-фона, пересчёт buffer/viewport/uniforms, реальная анимация и цельная композиция; два раздельных набора проверок.

**Out of scope (запрещено):** редизайн с нуля; изменение IA (F1)/маршрутов; бизнес-логика бота; «лечение» белых прямоугольников снижением `opacity` (UPD4 §1); маскировка фона CSS-градиентами (UPD4 Доп.P0); компенсация геометрии отрицательными отступами (UPD4 §3); изменение содержимого кнопок/карточек и дизайна сердцебиения (UPD4 §1.6/§5); замена OGL-фона; добавление новых библиотек/CDN/инлайна; удаление vendored-ассетов и тегов/бэкапов.

## 3. Трассируемость UPD4 → spec → задачи

| UPD4 | Требование | Решение | Задачи |
|---|---|---|---|
| §1 (7273–7294) | отключить флаг, снять `mountGlass()` с 3 целей, full reload, точечная чистка `.ps-glass*`, не лечить opacity | **D1** | T-2843…T-2847 |
| §2 (7296–7316) | `GlassSurface`-контракт: декор ниже контента, клики не перехвачены, геометрия не меняется, идемпотентный unmount; 1 изолированный элемент; frosted ≠ рефракция | **D1** | T-2848…T-2851 |
| §3 (7318–7339) | единая рабочая поверхность Main, без отрицательных отступов, лимит 1100 px внутри, нет полосы | **D2** | T-2852 |
| §4 (7341–7368) | единая модель высоты, двойной вычет, legacy-правила, 4 пункта nav видны/нажимаемы | **D3** | T-2853…T-2854 |
| §5 (7370–7387) | убрать стекло с `.status-block`, дизайн сердцебиения не менять, полная видимость данных | **D4** | T-2855 |
| §6 (7389–7397) | сохранить OGL, не добавлять градиенты | **D5** | T-2856…T-2858 |
| Доп.P0 §1 (7421–7433) | геометрия canvas, `max-width`-контейнер, пересчёт buffer/viewport/uniforms при fullscreen/resize | **D5** | T-2856…T-2858 |
| Доп.P0 §2 (7435–7447) | rAF после fullscreen, время шейдера, не 1-й кадр, hidden/reduced-motion, возобновление | **D5** | T-2858 |
| Доп.P0 §3 (7449–7465) | цельная Aurora, порядок слоёв 1–5, без полосы/заливки | **D2+D5** | T-2857…T-2858 |
| §7 (7399–7413) | 2 набора тестов; mobile nav/fullscreen/селектор/карточка; WebView ≠ Chromium | **D7** | T-2859…T-2862 |
| §8 (7470–7482) | без Human Gate, PENDING OWNER VERIFICATION не блокирует, дефект не закрывать по сборке/Reviewer | **D6/D7** | T-2863…T-2869 |

## 4. Решения (a)–(e)

### D1 (a, b). Стекло: немедленный откат, затем корректный `GlassSurface`
- **Флаг:** `UI_LIQUID_GLASS_LIB` **default → OFF** (безопасное состояние). Флаг **сохраняется** как env-only kill-switch (инфраструктура: vendored-бандл и `web/static/glass.js` не удаляются, но `mountGlass` не вызывается на функциональных целях). Удаление флага отклонено: оно потребовало бы редеплоя для контролируемого повторного включения и ломало бы мягкий откат.
- **Снятие:** `TARGETS` больше **не** содержит `.scope-trigger`, `.header-fs-btn`, `.status-block`; `mountGlass` вызывается только для назначенного декоративного `GlassSurface`.
- **`disposeAll`:** удаляет **все** созданные узлы `.ps-glass*` (и `data-lg-mounted`/`data-lg-failed`), идемпотентен; `inst.dispose()` — лишь дополнительный путь.
- **Full reload + точечная чистка:** hard-reload (cache-bust, bump `APP_VERSION`) убирает ранее созданные DOM-слои; чистка `.ps-glass__surface/.ps-glass__tint/.ps-glass__rim/.ps-glass` — **только** там, где добавлено экспериментом (§1.5), содержимое кнопок/карточек не меняется (§1.6).
- **Кандидат (1 изолированный декоративный элемент):** **новый минимальный презентационный блок** `<div class="glass-surface" data-glass-surface aria-hidden="true">` в сетке страницы «Статус» — без данных, без контролов, без ссылок. Отклонённые кандидаты: `.scope-trigger`/`.header-fs-btn`/`.status-block` (прямо исключены UPD4 §2); существующая карточка `data-glass="a"` `index.html:1934` (несёт живые метрики — нарушила бы «не менять содержимое»); shell-панели (shell остаётся графитовым, ADR-1025-17 D4).
- **DOM/контракт `GlassSurface`:** контейнер задаёт геометрию заранее; декоративные слои — абсолютные, `inset:0`, `pointer-events:none`, `aria-hidden`, **ниже** контента (контент — `position:relative; z-index:1`); `isolation:isolate` на контейнере; `contain:layout paint`. Требования: не менять исходные размеры/положение (сравнение rects до/после), не перехватывать клики (`elementFromPoint`), идемпотентные mount/unmount, отсутствие `.ps-glass*` после unmount.
- **Честный режим:** если источник преломления не предоставлен (нет живого содержимого позади) — режим называется **frosted**, а не «рефракция»; определяется объективно (feature/режим-детект + пиксельная проба «меняется ли содержимое ПОЗАДИ»).

### D2 (c). Единая рабочая поверхность Main
- С `main.scroll-area` снимается `max-width:1440px; margin-inline:auto` (`app.css:1932-1934`). Рабочая подложка — **на `main.scroll-area`** (не на `.app-shell`), поэтому она начинается ровно за sidebar (x=216) и тянется до правого края: полосы между sidebar и рабочей областью не остаётся.
- Внутренний лимит карточек **1100 px сохраняется** штатными `max-width:1100px; margin-inline:auto/justify-self:center` на `.module-list`/`.module-quick-wrap`/`.module-toolbar`/`.module-catalog .module-list`. **Никаких отрицательных отступов.**
- Подложка вводится отдельным токеном (`--work-surface-bg`), согласованным с `--surface-0`; она не должна обрезать canvas. Фиксированный canvas (`position:fixed; inset:0`) остаётся за всем контентом и **не** подчиняется `max-width` контентных колонок.
- Порядок слоёв (UPD4 Доп.P0 §3): **1) фон → 2) графитовые sidebar/header → 3) рабочая поверхность → 4) карточки → 5) модалки/служебные**.

### D3 (d). Единая модель высоты + двойной safe-area
- **Единственный источник — `--app-usable-height`** (`telegram-init.js:82-84`), вычисляемый из **фактически измеренных** значений, без допущения «`innerHeight` включает нижнюю безопасную область». Формула `computeBottomOffset` (max трёх кандидатов) **сохраняется** (ADR-1025-12 D3) — устраняется **двойной учёт**, а не расчёт.
- **Второй вычет снимается:** `.fullscreen-mode .scroll-area` `padding-bottom` (`app.css:1042`) приводится к обычному отступу без `env(safe-area-inset-bottom)`; нижний safe-area учитывается **ровно один раз** (в `--app-usable-height`).
- **Legacy вне активного режима:** `.bottom-nav`-fixed (`:1989-1995`) остаётся только под `.shell-layout-legacy`; `.more-sheet` (`:2033-2053`) перестаёт складывать `max(safe-area…)` и `--tg-viewport-bottom-offset` — остаётся **один** нижний offset (якорь к nav 52 px + один учтённый offset); `--tg-viewport-bottom-offset` сохраняется для диагностики.
- **Приёмка:** все 4 пункта nav с подписями полностью видны и нажимаемы.
- **Реальные значения в WebView:** инструментируем сбор `innerHeight`/`visualViewport.height`/`viewportHeight`/`viewportStableHeight`/`safeAreaInset.bottom`/`contentSafeAreaInset.bottom` в отчёт матрицы (Chromium + TMA-эмуляция). Фактические значения на живом Telegram WebView — **PENDING OWNER VERIFICATION** (headless невоспроизводимо); не блокирует независимые задачи (UPD4 §8).

### D4 (e-status). Восстановление `.status-block`
- Стеклянный слой с `.status-block` убирается (следствие D1); `data-glass` не добавляется. **Дизайн сердцебиения не меняется.** Проверяются высоты родителей/`overflow` (`.status-block { overflow:hidden }` `app.css:1116`) и полная видимость: сердцебиение, бот, CPU, RAM, диск, аптайм. Декоративные слои не перекрывают данные.

### D5 (e-bg). OGL-фон: геометрия + анимация (реализацию не переделывать)
- `__AuroraFlow` **экспортирует `resize`**; вызов — из `_onResize` (`app.js:2829-2836`), `setFullscreenFromTma` (`:6080-6099`), на изменение `visualViewport`/`viewportChanged` и (опц.) `ResizeObserver` по фактическому контейнеру canvas.
- Пересчёт: `setSize` + WebGL drawing buffer + `gl.viewport` + uniform `uRes` **по фактическому размеру контейнера** (не `window.innerWidth`), согласованные единицы (CSS px vs DPR). Старые размеры после fullscreen/viewport-смены не остаются.
- Анимация: rAF продолжает работу после fullscreen; `uTime` обновляется; canvas не замирает на 1-м кадре; рендер не остановлен ошибочно `document.hidden`/`prefers-reduced-motion`; после возврата из скрытия возобновляется. Наличие `requestAnimationFrame` в исходниках — **не** доказательство (UPD4 Доп.P0 §2).
- Композиция: цельная Dark Aurora Flow без яркой полосы слева и статичной заливки справа; положение Aurora не привязано к ширине sidebar/контентной колонки; **без CSS-градиентов поверх WebGL**.

### D6 — инварианты и AMEND
- **Инварианты:** **Δ DDL=0** (SQLite `user_version=12`); **Δ каталога=0** (459/98/96/21/418; `services/param_catalog.py` не трогается); **CSP `script-src 'self'`** (vendored same-origin, без CDN/инлайна); **R17/R18** (`current_task.md` не изменять/не коммитить; теги/бэкапы/`stash@{0}` не удалять).
- **AMEND ADR-1025-17 D5** (точечное монтирование на `.scope-trigger`/`.header-fs-btn`/`.status-block`) — **откат**; применимо только через изолированный `GlassSurface` (D1).
- **AMEND ADR-1025-17 D6** (Dark Aurora Flow) — **без изменения реализации**; пересматриваются **позиционирование/размеры/viewport/uniforms** canvas (D5).
- **Уточнение ADR-1025-13 D1/D4 и ADR-1025-16 D4** — единая модель высоты, устранение двойного safe-area, вывод legacy `.more-sheet`/`.fullscreen-mode .scroll-area` из активного режима (D3).
- **Уточнение ADR-1025-9 D2/D3** — контракт `GlassSurface` заменяет прямое монтирование; палитра §8 и механика `--grad-angle`/`grad-spin`/`grad-drift` сохраняются.
- **Сохранить:** flex-геометрия shell и `--app-usable-height` (§63), графит-токены §8, удаление `--shell-texture` (§7), дизайн сердцебиения, F0 `persistItems`/F1/F3/F4 §60/F5 §61/F9, `ADR-1024-24` (fullscreen-sync), формула `computeBottomOffset`. Полная карта — ADR-1025-18.

### D7 — приёмка (UPD4 §7)
- **Набор 1 — без библиотеки стекла:** интерфейс исправен и полностью читаем; отдельно — мобильная нижняя навигация (4 пункта с подписями, hit ≥44×44), fullscreen, селектор области, системная карточка.
- **Набор 2 — с библиотекой на 1 изолированном элементе:** включение эффекта **не меняет** размеры/положение/доступность (rects + `elementFromPoint`), unmount не оставляет `.ps-glass*`.
- **Фон:** кадры **0/5/10/20 с**, числовое подтверждение движения (заметно за 5–10 с); normal/fullscreen и resize; отсутствие полосы слева и статичной заливки.
- **Честность:** результаты Chromium/headless **не** выдаются за Telegram WebView; live-проверка — **PENDING OWNER VERIFICATION**; дефект не закрывается по зелёной сборке или вердикту Reviewer (UPD4 §8).

## 5. Интерфейсы и контракты

| Контракт | Вход/выход | Гарантии |
|---|---|---|
| `__LiquidGlass.sync(enabled)` | `enabled: boolean` | `true` → mount только на `[data-glass-surface]`; `false` → полный cleanup |
| `__LiquidGlass.dispose()` | — | идемпотентно; `.ps-glass*`/`data-lg-*` отсутствуют |
| `GlassSurface` DOM | контейнер `[data-glass-surface]` | декор `inset:0; pointer-events:none; aria-hidden; z-index<контента`; контент выше; геометрия неизменна |
| Режим стекла | `refraction` \| `frosted` | честная маркировка; frosted не называется рефракцией |
| `__AuroraFlow.resize()` | — | `setSize`+buffer+viewport+`uRes` по фактическому размеру; безопасен при null-контейнере |
| `--app-usable-height` | `max(0, innerHeight − offset)` | единственный источник; safe-area вычтен один раз |
| `--work-surface-bg` | token | подложка Main от края sidebar до правого края; без обрезки canvas |

## 6. Поведение при ошибках

Библиотека недоступна/бросила исключение → тихий `frosted`-fallback (существующий путь `glass.js:61-64`), без белых непрозрачных слоёв. WebGL context lost → существующий 2D-фолбэк (не трогается). `resize` при отсутствии canvas/renderer → безопасный no-op. `visualViewport`/TMA-инсеты отсутствуют → значения 0, высота не «задирается». Unmount при отсутствии узлов → безопасен и идемпотентен.

## 7. Данные / обратная совместимость

Δ DDL=0 (миграции не трогаются), Δ каталога=0 (флаги остаются env-only `ClassVar`, в `pc.REGISTRY` не входят). Никаких изменений API-контрактов `/api/me.ui_flags` (аддитивность сохраняется). `UI_LIQUID_GLASS_LIB` меняет только default → OFF.

## 8. Безопасность / приватность

CSP `script-src 'self'` соблюдён: новые внешние ресурсы/инлайн/eval не добавляются, vendored-бандлы раздаются same-origin. R17/R18: без секретов/сырых значений в логах и отчётах; `plans/current_task.md` не изменяется и не коммитится.

## 9. Сценарии приёмки (Given/When/Then)

1. **Стекло снято:** Given `UI_LIQUID_GLASS_LIB=OFF`; When hard-reload; Then нет `.ps-glass*`, нет белых прямоугольников, содержимое 3 целей штатно, прозрачность не использовалась как «лечение».
2. **Стекло изолировано:** Given `UI_LIQUID_GLASS_LIB=ON`; When mount на `[data-glass-surface]`; Then rects/`elementFromPoint` идентичны состоянию без эффекта, `.ps-glass*` исчезают после unmount, режим назван честно.
3. **Main:** Given desktop ≥1200; When открыт модуль; Then между sidebar и рабочей областью нет яркой полосы, карточки ≤1100 px центрированы, отрицательных отступов нет.
4. **Высота:** Given mobile TMA-эмуляция; When normal/fullscreen; Then 4 пункта nav с подписями видны и нажимаемы, safe-area вычтен один раз.
5. **Карточка:** Then сердцебиение/бот/CPU/RAM/диск/аптайм видны полностью; стеклянного слоя нет.
6. **Фон:** Then кадры 0/5/10/20 с различаются (заметно за 5–10 с), композиция цельная, слои 1–5, без градиентной маскировки.
7. **Честность:** Then live WebView помечен PENDING OWNER VERIFICATION, если проверка шла только в Chromium.

## 10. Зависимости

Step 0 baseline/тег `pre-round1025-hotfix10` (T-2840, @DevOps) до кода. Порядок: откат/стабилизация стекла (A) → `GlassSurface` (B) → Main (C) → высота (D) → карточка (E) → фон (F) → проверки (G) → регресс/ревью/деплой (H) → немедленное продолжение F6 (T-2869). F6 `memory-analytics-reorg-round1025` — ⏸ возобновляется сразу после деплоя (UPD4 §8).

## 11. Тест / деплой / откат

- **Тесты:** pytest baseline **8291/0**; `node --check`; матрица UI (`tools/ui_round1025_matrix.py`) failures 0; новые DOM-пробы rects/`elementFromPoint`/`.ps-glass*`-absence; фон-пробы 0/5/10/20 с; инварианты Δ DDL=0 / Δ каталога=0 / CSP.
- **Деплой:** bump `APP_VERSION` (cache-bust обязателен из-за §1.3 full reload), прогон тестов, деплой, проверка доступности/статики (HTTP 200 ≠ корректный layout).
- **Откат:** hard — тег `pre-round1025-hotfix10` + `git revert`; soft — env-only `UI_LIQUID_GLASS_LIB=false` (default уже OFF), `UI_AURORA_FLOW_V2=false`, `UI_SHELL_FLEX_V3=false`. Поэтапная раскатка не требуется (один прод).

## 12. Открытые вопросы / эскалация

Блокирующих выборов владельца нет: все (a)–(e) разрешены существующими constraints UPD4. Кандидат декоративного элемента (D1) — инженерное решение в рамках §2, не user-owned tradeoff → `ARCHITECT_DECISION_REQUIRED` **не заявляется**. Live-значения инсетов — **PENDING OWNER VERIFICATION**, workflow не останавливает.
