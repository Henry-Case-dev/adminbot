# ADR-1025-17 — Flex-колонка shell с единым источником высоты, графитовый shell без текстуры, vendored Liquid Glass под CSP, Dark Aurora Flow (OGL) и объективная граница «преломление ≠ фильтрация своего слоя»

- **Статус:** Proposed → **Approved** (Step 2 @Architect, 22.09.2026; человеческий gate отключён — UPD3 §16: выбор библиотеки/CSS/деплой не являются основанием для остановки).
- **Дата:** 2026-09-22
- **Раунд:** 10.25, внеплановый приоритетный пакет **hotfix9** `hotfix9-shell-liquidglass-darkaurora-round1025` (T-2790…T-2839), Волна 1.8.
- **Связано:** `spec.md` этой папки; **UPD3** `plans/current_task.md:6499-7264`; `plans/ARCHITECTURE.md` §57/§58/§59/§60/§61/§62; **AMEND ADR-1025-16** (D1/D2/D3), **AMEND ADR-1025-13**, **AMEND ADR-1025-9**; сохранить ADR-1025-12 (D3 `computeBottomOffset`, D5 нативные кнопки/`--header-h`), ADR-1024-24 (fullscreen-sync), ADR-1025-2 (F0 `persistItems`), ADR-1025-1 (F1), ADR-1016-2/ADR-1024-13 (CSP/zero-build/`ui_flags`).
- **Затрагивает:** `web/static/app.css`, `web/index.html`, `web/app.js`, `web/static/telegram-init.js`, `web/static/vendor/**` (новые), `tools/vendor/**` (build), `config/settings.py` (env-only `ClassVar` + `APP_VERSION`), `web/api/routes.py` (аддитивно `ui_flags`), `tools/ui_round1025_matrix.py`, тесты (`tests/**`, `tests/js/**`), отчёты `plans/reports/round1025_hotfix9_*.md`.

## Контекст

Живая приёмка после hotfix8 (§62, `APP_VERSION` 2.58.11) показала, что дефекты не устранены: нижняя навигация всё ещё выходит за экран; шапка конфликтует с контентом; в fullscreen исчезают элементы; модалка/SaveBar перекрывают настройки; shell потерял графитовость и несёт диагональную текстуру `--shell-texture` (`app.css:92`, `:1436`; применение `:1298/:1864/:1894/:1926/:1982`); остаются цветные ореолы; «Liquid Glass» фильтрует собственный декоративный градиент, а не содержимое позади (`[data-glass="a"]::before` + `filter:url(#lg-lens)`); фон практически неподвижен. UPD3 §1 **снимает прежний запрет внешних библиотек** (фикс-версии, локальная сборка, раздача с сервера, CSP/WebView-проверка; без Vue→React/переписывания/CDN) и **явно называет** кандидатов `@liquidglassjs/core` (§9) и **OGL** (§10).

**Перепроверка по коду (Step 2 @Architect):** `--shell-h` (`app.css:75` base + `@supports :104-108`); `.app-shell :981-989`; `.fullscreen-mode :1001-1026`; `.bottom-nav :1915` — `position:fixed; bottom:var(--tg-viewport-bottom-offset,…)`; `.sticky-save :1469-1486` (sticky **внутри** `.modal-body :1495`), `.modal-card :1488`; `telegram-init.js:36-50/51-88` (`computeBottomOffset`, `applyInsets`); `web/app.py:50-61` — CSP `script-src 'self' 'unsafe-eval'`, `connect-src 'self'`; `web/static/vendor/` уже содержит vendored-прецеденты (`vue.global.prod.min.js`, `chart.umd.min.js`, `vis-network`, `dompurify`, `telegram-web-app.js`); `package.json` в корне **нет**.
**Внешние факты:** `@liquidglassjs/core` — **0.5.3** (2026-09-19), MIT, ESM; основной путь — SVG `feDisplacementMap` по живому DOM; README-gotchas: `backdrop-filter: url(#…)` «parses everywhere and paints only in Chromium» → frost-путь проверяет движок и падает на `blur()`. `ogl` — **1.0.11**, Unlicense, zero-dependency ESM.

**Инварианты:** Δ DDL = 0, Δ каталога = 0; CSP; фикс-версии; нативные кнопки Telegram/`--header-h`; IA F1; store F4 §37–§42; `persistItems` F0; SaveBar F9; `computeBottomOffset`; fullscreen-sync ADR-1024-24; R17/R18.

## Решение

### D1 (a). Единый источник высоты `--app-usable-height` + flex-колонка `shell-mobile`/fullscreen
- **Единственный источник.** `telegram-init.js::computeBottomOffset` (формула `max` трёх нижних зон — **не меняется**, ADR-1025-12 D3) подаёт `--app-usable-height = max(0, innerHeight − offset)`. CSS-фолбэк: `100vh` (всегда валидно) → `@supports (height:100dvh)` → `100dvh`. `--shell-h: var(--app-usable-height)` — только алиас. `--tg-viewport-bottom-offset` сохраняется (диагностика/`.more-sheet`), но **снимается с `.bottom-nav`**.
- **Flex-колонка.** `.app-shell.shell-mobile` и `.app-shell.fullscreen-mode`: `display:flex; flex-direction:column; height/max-height:var(--app-usable-height); min-height:0; overflow:hidden`. `main.scroll-area`: `flex:1 1 auto; min-height:0; overflow-y:auto; overflow-x:hidden`. `.bottom-nav`: `position:relative; inset:auto; flex:0 0 auto; width:100%`. Старые fixed-правила nav **удаляются**.
- **Safe-area ровно один раз** — внутри `computeBottomOffset`; на nav нет дублирующего `padding-bottom`/`bottom:`. `.more-sheet` сохраняет собственный `bottom:var(--tg-viewport-bottom-offset)`.
- Desktop: sidebar 216px, gap 16px — без регрессии. Флаг `UI_SHELL_FLEX_V3` (default ON) → `.shell-layout-legacy`.

### D2 (b). Header/fullscreen через grid/flex
- Header — `flex:0 0 auto`: контент структурно не может оказаться под шапкой. Селектор области — своя строка; аватар/роль без пересечений (`min-w-0`+`truncate`); ⛶ — резервом safe-area (`max(env, --tg-safe-area-inset-top, --tg-content-safe-area-inset-top)`), тач-цель ≥44×44; нативные кнопки не двигаются.
- `--header-h` + `scroll-padding-top` — единственный верхний резерв. Смена основного раздела → `scroll-area.scrollTop = 0` (новый раздел с начала). Fullscreen: те же header/селектор/виджеты, без клиппинга; ADR-1024-24 — источник истины TMA.

### D3 (c). SaveBar — footer `.modal-actions`, а не sticky поверх полей
- `.modal-card` — flex-колонка (`max-height: min(var(--app-usable-height) − 24px, 720px)`) > `.modal-head` / `.modal-body` (единственный скроллер) / `footer.modal-actions`.
- **Переиспользуется существующий `<sticky-save>`**, переносится из `.modal-body` в footer; **вторая SaveBar не создаётся**; логика F0/F9 не меняется.
- Высоты 600–700 px: последнее поле достигается скроллом, footer целиком в экране; клавиатура — пересчёт `--app-usable-height` + `scrollIntoView({block:'nearest'})`; nav структурно не поверх модалки.

### D4 (d). Полное удаление `--shell-texture`; графитовый shell
- **`--shell-texture` удаляется из всех носителей** (`:92`, `:1436`, `:1298`, `:1864`, `:1894`, `:1926`, `:1982`) без ослабления/замены/шума/сетки; `--shell-specular` (не-repeating блик) сохраняется.
- **Токены §8:** `--shell-bg rgba(27,29,34,.94)` (mobile ≤767 `.96`), border `.09`, highlight `.055`, shadow `0 4px 16px rgba(0,0,0,.16)`, blur `blur(14px) saturate(105%)` (+`-webkit-`). Shell ≠ карточки; ореол не возвращается; карточная прозрачность не меняется; AA пересчитывается. Флаг `UI_SHELL_GRAPHITE_V3` (default ON).

### D5 (e). Liquid Glass: `@liquidglassjs/core` 0.5.3, vendored под CSP, с честным гейтом
- **Опора на `backdrop-filter: url()` отсутствует** (библиотека сама объявляет его Chromium-only и падает на `blur()`), основной путь — SVG `feDisplacementMap` по живому DOM → кросс-движково. Прецедент hotfix6 (запрет опоры на `backdrop-filter: url()`) **не нарушается**; авторский grep-инвариант `backdrop-filter: url(` = 0 сохраняется.
- **Локальная сборка:** npm — инструмент (фикс `0.5.3` + lock), esbuild → IIFE `web/static/vendor/liquidglass.core.0.5.3.min.js` + `.css`; same-origin `<script src="/static/vendor/…?v=__APP_VERSION__">`; без CDN/инлайна. Версия/лицензия/`sha256`/команда — в `web/static/vendor/README.md`.
- **Гейт:** изолированный прототип (реальный фон + карточка/кнопка/селектор/текст) обязан доказать изменение содержимого **позади**; фильтрация декоративного слоя/клона **не** считается преломлением. Точечно: селектор области, fullscreen-кнопка, 1–2 декоративные карточки Статуса; sidebar/header — графит + слабый frosted; deny-list не расширяется; запреты §9 (толстая рамка/неон/размытие текста/желе/случайная текстура/«линза вместо sidebar»).
- **Если прототип объективно отклоняет библиотеку** — задокументировать альтернативу и применить качественный frost-fallback; «фильтрацию своего слоя» за преломление **не выдавать**. Флаг `UI_LIQUID_GLASS_LIB` (default ON) → OFF = frost-only.

### D6 (e). Dark Aurora Flow: один canvas + fragment shader (OGL `1.0.11`)
- **OGL 1.0.11** (Unlicense, zero-dependency), vendored IIFE; один полноэкранный canvas + лёгкий fragment shader: 2–3 широкие мягкокрайние ленты, morphing. Палитра §10 (bg `#090D17`; teal `#42D6C4`; blue `#77A8FF`; violet `#A78BFA`; indigo `#5C7CFA`).
- Слой: canvas за `#app` (`z-index:0`, `pointer-events:none`); legacy `.aurora-bg`/`body::before/::after`-анимации выводятся из активного пути (не «пятна поверх пятен»); `lg-bg-paused`/`bg-wash-legacy` переиспользуются.
- Скорость: заметно за **5–10 с**. Перф: mobile — облегчённый (~30 FPS ориентир); DPR-кап (desktop ≤2, mobile ≤1.5); стоп при `document.hidden`; `prefers-reduced-motion` → качественный статичный кадр; `webglcontextlost` → CSS-статик. Без ореола вокруг sidebar, без ухудшения контраста.
- **AMEND:** WebGL-запрет снимается **только** для фонового canvas; `getContext('2d')`-сердцебиение и отсутствие Three.js сохраняются. Флаг `UI_AURORA_FLOW_V2` (default ON) → OFF = legacy CSS-aurora.

### D7. Сердцебиение — только устранение исчезновения в fullscreen
- Дизайн/форма/анимация/цвета/пороги/источники/алгоритм не меняются. Бounded-фикс: canvas/контейнер не схлопываются; сохранение после Vue-render (`v-show`); `_hbResize()`/перезапуск rAF после `viewportChanged`/`fullscreenChanged`/смены `--app-usable-height`; отсутствие `overflow:hidden`-клиппинга родителями. Если решает D1 — компонент не трогать.

### D8. Инварианты, флаги, доказательность
- Флаги (env-only `ClassVar`, default ON, Δ каталога = 0): `UI_SHELL_FLEX_V3`, `UI_SHELL_GRAPHITE_V3`, `UI_LIQUID_GLASS_LIB`, `UI_AURORA_FLOW_V2`; наследуемые hotfix6/7/8-флаги продолжают работать.
- Новый токен/библиотека/сборка/Approved **не доказывают** выполнение (§13); нужны воспроизводимые проверки §12.

## AMEND / SUPERSEDE / сохранить

| Ранее | Действие | Что именно / почему |
|---|---|---|
| **Constraint «no-libraries»** (ADR-1025-16/§62, ADR-1025-13/§59, §58) | **AMEND (снят) → UPD3 §1** | Владелец разрешает внешние библиотеки: фикс-версии, локальная сборка, раздача с сервера, проверка CSP/WebView; без Vue→React/переписывания/CDN |
| **ADR-1025-16 D1** (CSS-эквивалент Framer, WebGL/библиотеки запрещены) | **AMEND → D6/D5** | WebGL для фонового canvas разрешён; библиотеки разрешены; прочие инварианты D1 (CSS-first для микродвижений) сохраняются |
| **ADR-1025-16 D2** (shell-токены `rgba(24,28,38,.72)`, border .08, highlight .06, shadow `0 8px 24px`, `blur(18px) saturate(115%)`; `--shell-texture`) | **AMEND → D4** | Значения → §8 UPD3 (графит `.94/.96/.09/.055/0 4px 16px/.blur(14px) saturate(105%)`); `--shell-texture` **удалён**; цветная линза/ореол не возвращаются; карточные `--glass-*`/палитра §8 не меняются |
| **ADR-1025-16 D3** (CSS-aurora/mesh, Canvas 2D как фолбэк, «без WebGL») | **AMEND → D6** | Dark Aurora Flow через OGL (WebGL) допущен UPD3 §10; CSS-статика остаётся фолбэком; `@property --grad-angle`+`grad-spin/grad-drift` для `.grad-band`/кнопок — сохраняются |
| **ADR-1025-13 D1** (`--shell-h` как единственный источник, два режима normal/fullscreen) | **AMEND → D1** | Источник переносится на `--app-usable-height`; `--shell-h` — алиас; flex-колонка для mobile/fullscreen; fixed nav/bottom-offset удалены |
| **ADR-1025-13 D3** (shell-токены/рецепт; `--shell-texture` как faux-noise) | **AMEND → D4** | Текстура удаляется; токены §8 |
| **ADR-1025-13 D4** (выравнивание header/mobile) | **AMEND → D2/D3** | grid/flex без случайных absolute; SaveBar — footer |
| **ADR-1025-9 D2** (Liquid Glass A/B/C, значения/тиры) | **AMEND/уточнение → D5** | Настоящее преломление через vendored-кандидат; `backdrop-filter: url()` как опора — по-прежнему запрещено; deny-list/тиры сохраняются |
| **ADR-1025-9 D3** (фон §10: механика/цвета/длительности 60–90/90–120 с) | **AMEND → D6** | Фон → Dark Aurora Flow; палитра §10 сохранена; legacy-механика — фолбэк |
| **ADR-1025-12 D1** (foreground-линза `filter:url()`, тир-лестница, `UI_LENS_MAX_NODES`) | **сохранить (уточнить применение)** | Self-градиентная линза больше не выдаётся за «настоящее преломление»; tier-лестница/бюджет сохраняются |
| **ADR-1025-12 D3** (`computeBottomOffset` = max трёх инсетов) | **НЕ отменяется** | Формула сохранена; меняется потребитель (→ `--app-usable-height`) |
| **ADR-1025-12 D5** (нативные кнопки, `--header-h`, fullscreen-sync) / **ADR-1024-24** | **НЕ отменяется** | Компоновка шапки; источник истины fullscreen — TMA |
| **F1 IA, F2 токены/палитра §8, F3 селектор/scope, F4 §60 store §37–§42, F5 §61, F0 `persistItems`, F9 SaveBar, порядок навигации hotfix4** | **НЕ отменяется** | IA/write-path/store/SaveBar-логика не переписываются |
| **R17/R18, Δ DDL = 0, Δ каталога = 0** | **НЕ отменяется** | Инварианты |

## Последствия

**Positive:** структурная (не «заплаточная») геометрия — nav/header/контент не могут перекрываться; safe-area учитывается ровно один раз; чистая гладкая графитовая поверхность без диагональной текстуры/ореола; впервые объективно проверяемое преломление либо честно задокументированный fallback; живой фон в палитре §10 с фолбэками; воспроизводимые DOM-проверки; инварианты, IA и прецеденты не нарушены; библиотеки встроены по уже существующему vendored-паттерну проекта.

**Negative/издержки:** две новые внешние зависимости (пусть маленькие и MIT/Unlicense) + локальный сборочный шаг и `lock` (поверхность сопровождения); real-эффекты стекла/фона и FPS **не воспроизводимы headless** → обязателен live-гейт владельца; `@liquidglassjs/core` молодой (0.5.3), API может меняться → жёсткая фиксация версии; ручная AA-таблица; визуальные правки требуют атомарного обновления маркеров тестов.

**Ограничения:** Δ DDL = 0, Δ каталога = 0; без CDN/инлайна; WebGL — только фоновый canvas; `backdrop-filter: url()` как опора — запрещён; `current_task.md` не изменяется (R18).

## Альтернативы

| Альтернатива | Почему отклонена |
|---|---|
| Оставить fixed `bottom-nav` + `--tg-viewport-bottom-offset` и «подпереть» отступами | Сохраняет двойной учёт safe-area и корень выхода за экран (UPD3 §4 прямо запрещает) |
| Новый источник высоты рядом с `--shell-h` | Два конкурирующих источника → скачки в fullscreen (прецедент ADR-1025-13 F-2) |
| Ослабить/заменить `--shell-texture` иным паттерном/шумом/сеткой | Прямо запрещено UPD3 §7 |
| Вернуть цветную линзу на shell | Источник ореола; UPD3 §8 запрещает |
| Оставить собственную radial-градиентную линзу как «преломление» | UPD3 §9: фильтрация своего декоративного слоя ≠ преломление содержимого позади |
| Отказаться от библиотеки «из-за стека» | UPD3 §1 запрещает использовать ограничения стека как универсальную причину отказа |
| Собрать через CDN/инлайн | CSP/§1 запрещают |
| Весь проект перевести на bundler ради эффекта | §1: npm — только инструмент, без полной миграции сборки |
| Canvas2D-ленты вместо shader-лент | Допустимы как фолбэк, но UPD3 §10 задаёт fragment shader/OGL основным кандидатом |
| WebGL на каждой карточке / Three.js | §10: не создавать WebGL-сцену на карточке; Three.js не подключать |
| Каталоговые тумблеры shell/фона | Δ каталога ≠ 0; применены env-only `ClassVar` |
| Human gate по выбору библиотеки | §16: выбор технически совместимой библиотеки — не основание для gate |

## Верификация

- **Playwright+DOM** (`tools/ui_round1025_matrix.py`): фиксация viewport/`viewportStableHeight`/`visualViewport`/инсетов; rects Header/селектора/первой карточки/bottom-nav/modal/SaveBar/последнего поля; пересечения/видимость/`elementFromPoint()`; доступность последнего поля после скролла; resize в fullscreen; `scrollWidth ≤ innerWidth+1`; `rect.bottom ≤ innerHeight (+stable)`; отсутствие `--shell-texture`/цветного oреола на shell; `--shell-bg ≠ --glass-bg`; computed shell-токены §8; фон — кадры 0/5/10/20 с и числовое подтверждение движения; прототип стекла (фон без/через стекло).
- **JS/node-юниты:** `computeBottomOffset` без изменения семантики; `--app-usable-height`-потребитель; сохранность `reconcileLiquidGlass`-семантики; heartbeat-репейнт после viewport; `node --check web/app.js`+`telegram-init.js`.
- **Инварианты:** Δ DDL = 0; Δ каталога = 0 (459/98/96/21/418); CSP (`script-src 'self'`, без CDN/инлайна); `backdrop-filter: url(` = 0 в авторском CSS; фикс-версии/`sha256` в `web/static/vendor/README.md`; `persistItems`; store F4 §37–§42; IA/маршруты; нативные кнопки/`--header-h`/fullscreen-sync; `git diff --check`; pytest baseline 8272/0; AA-таблица.
- **Только реальный Telegram WebView (владелец, PENDING OWNER VERIFICATION):** mobile fullscreen — nav целиком в экране, шапка/селектор целы, SaveBar не перекрывает последнее поле, стекло/фон живые и без ореолов, FPS. **Не воспроизводимо headless** — не объявляется пройденным и не останавливает workflow (§12/§15).

## Откат

- **Hard:** тег `pre-round1025-hotfix9` (T-2790) + `git revert` коммитов пакета + возврат `APP_VERSION`/`?v=`.
- **Soft (env-only, без редеплоя):** `UI_SHELL_FLEX_V3=false`; `UI_SHELL_GRAPHITE_V3=false` (значения hotfix8; текстура не возвращается); `UI_LIQUID_GLASS_LIB=false` (frost-only); `UI_AURORA_FLOW_V2=false` (legacy CSS-aurora); наследуемые hotfix6/7/8-флаги — рабочие.
- Бэкапы/теги/`stash@{0}` не удалять (R18).
