# ADR-1026-3 — Polygonal Background: новый модуль на Canvas 2D + Delaunator 5.0.0, адаптер `__AuroraFlow`, env-only флаг default ON, точечный Liquid Glass через изолированный `GlassSurface`

- **Статус:** Proposed → **Approved** (Step 2 @Architect, 23.09.2026; human gate не требуется — §16/§17 ТЗ, эпик декоративный).
- **Дата:** 2026-09-23
- **Раунд:** 10.26, EXTRA-визуальный эпик `polygonal-luminescence-round1026` (T-3162…T-3219), блоки 0/A–Q.
- **Связано:** `spec.md` этой папки; ТЗ `plans/current_task.md:7485-8755` §0–§17 (прочитано дословно, **не изменялось**, R17/R18); `plans/ARCHITECTURE.md` §63/§64 (hotfix9/10), §71 (S1); **SUPERSEDE ADR-1025-17 D6** (Dark Aurora Flow — активный рендерер), **AMEND ADR-1025-18 D1** (судьба стекла/`GlassSurface`), REUSE ADR-1025-9 D3 (фон §10), ADR-1025-13 D1/D3 (высота/safe-area), ADR-1025-12 D3/D5, ADR-1024-24 (fullscreen-sync), ADR-1024-13/ADR-1016-2 (CSP/zero-build/`ui_flags`), ADR-1025-24 D4 (D4-гейт).
- **Затрагивает:** `web/static/polygon-background.js` (**новый**), `web/static/vendor/delaunator.5.0.0.min.js` (+README/SHA), `tools/vendor/{package.json,package-lock.json,build.mjs,.delaunator-entry.mjs}`, `web/index.html`, `web/app.js`, `web/static/app.css`, `web/static/glass.js` (условно, блок J), `config/settings.py` (env-only `ClassVar` + `APP_VERSION`), `web/api/routes.py` (аддитивно `ui_flags`), `.env.example`, `tools/**` (прототипы, gitignored), `tests/**`, `tests/js/**`, `plans/reports/**`, `plans/ARCHITECTURE.md` (Merge).

## Контекст

ТЗ §0–§17 требует заменить Dark Aurora Flow (§AD 2025/§63–§64) полноценной полигональной светящейся композицией: треугольные полупрозрачные грани, тонкие линии, светящиеся узлы, сине-фиолетовые/сиреневые области, яркие циановые акценты, мягкое переливающееся свечение «из самой геометрии», при сохранении читаемости интерфейса и **без** изменения layout/логики/IA/сердцебиения.

**Внешние факты (перепроверено Step 2):**
- `delaunator@5.0.0` — npm registry: version `5.0.0`, **license ISC**, `main/module: index.js`, зависимость `robust-predicates:^3.0.0`; исходник — ESM `export default class Delaunator { static from(points, getX, getY) … }`. Bare-import `robust-predicates` → без бандла в браузер не подключается (CSP/zero-build) ⇒ обязательна локальная esbuild-сборка в IIFE.
- `@liquidglassjs/core@0.5.3` (`dist/index.d.ts`): `mountGlass(root, opts)`; `GlassOptions` включает `source?: HTMLElement|string`, `refract?`, `behind?`, `mode?:'auto'|'svg'|'webgl'|'frost'`. README/GOTCHAS: авто-выбор `svg → webgl → frost`; для **анимированного** `<canvas>` нужен путь `source` → **WebGL** (SVG-путь над перерисовываемым canvas «выпадает» из фильтра в Safari). Библиотека поднимает собственный WebGL-контекст.
- Существующие артефакты: `web/static/aurora-flow.js` (контракт `__AuroraFlow`, `measure()`/`ResizeObserver`/context-loss→2D/`detachCanvas`); `web/static/glass.js` (только `[data-glass-surface]`, `purge`/`clearAttrs`/`disposeAll`, честный `detectMode`); `app.js::_syncBgLayer/setBgPaused/_auroraResize/_onResize/setFullscreenFromTma`; `web/static/app.css` (`.aurora-flow-canvas`, `html.aurora-flow-v2` гасит legacy); `tools/vendor` (esbuild 0.25.9, IIFE `globalName`); CSP `script-src 'self'`; `web/static/vendor/README.md` (таблица версий/SHA).

**Инварианты:** Δ DDL = 0; **Δ каталога = 0**; CSP `script-src 'self'`/zero-build; R17/R18; не ломать §57–§71/F0–F11/S1, IA, сердцебиение, настройки, публикацию; D4-гейт (S6/S10 закрыты до live-приёмки Эпика 1).

## Решение

### D1. Новый модуль `polygon-background.js` (не замена `aurora-flow.js`)
Создаётся **отдельный** модуль `web/static/polygon-background.js`. `aurora-flow.js` **не переписывается** и **не удаляется** (SUPERSEDE как активный рендерер, сохранён для отката). Причины: (1) **риск/откат** — большой новый алгоритм (сеть/bloom/свет/топология) не должен вытеснять проверенную реализацию; kill-switch OFF должен возвращать Aurora без правок кода; (2) **чистота** — разные рендереры/палитры/контракты, смешение усложняет сопровождение; (3) **диагностика** — независимый `getDiagnostics()`.
**Адаптер совместимости:** модуль сохраняет `window.__AuroraFlowLegacy` и подменяет `window.__AuroraFlow` на совместимый фасад (`start/stop/resize/setPaused/sample/mode`) → вызовы `app.js` **не переписываются** (§3.2 ТЗ, T-3171).

### D2. Флаг env-only `UI_POLYGON_BG_ENABLED` (default ON); Δ каталога = 0
`config/settings.py`: `UI_POLYGON_BG_ENABLED: ClassVar[bool] = _env_bool("UI_POLYGON_BG_ENABLED", True)`; аддитивный проброс в `web/api/routes.py::ui_flags`; computed `polygonBgEnabled` в `app.js`. **Каталог не меняется** — прецедент `UI_AURORA_FLOW_V2`/`UI_LIQUID_GLASS_LIB` (env-only `ClassVar`, ∉ `pc.REGISTRY`); OFF → мягкий откат к Aurora без редеплоя. `param_catalog.py`/REGISTRY/GROUPS/TAB_RULES не трогаются.

### D3. Стек: Delaunator 5.0.0 (vendored) + **Canvas 2D — единственный активный рендерер**; OGL — только откат
- **Delaunator 5.0.0** фиксируется `--save-exact`; локальная esbuild-сборка → `web/static/vendor/delaunator.5.0.0.min.js` (IIFE; entry-шим от default-export; проверка `typeof Delaunator.from === 'function'`); SHA-256 + строка лицензии **ISC** в `web/static/vendor/README.md`; подключение same-origin до `polygon-background.js`/`app.js`; **0 CDN**.
- **Canvas 2D — основной и единственный рендерер** (§2.2). `ogl 1.0.11` **остаётся vendored** и доступен **только как откатный путь Aurora** (когда `UI_POLYGON_BG_ENABLED=false`); в активном режиме Polygon OGL **не** запускает. **Никаких двух активных рендереров.**
- Если реальное тестирование Canvas 2D окажется недостаточно производительным — перенос в OGL оформляется **отдельным ADR** (усложнение требует обоснования, §2.3); в рамках этого эпика не делается.
- **`@liquidglassjs/core 0.5.3`** — используется существующая; вторая библиотека стекла **не** добавляется (§2.4/§12.1).

### D4. Контракт модуля и детерминизм
Публичный `window.__PolygonBackground` (§5 spec): `start/stop/pause/resume/resize/getDiagnostics/mode`; совместимый `window.__AuroraFlow`. **Ровно один активный фоновый рендерер** — `app.js::_syncBgLayer` выбирает по матрице режимов; `stop()` снимает canvas и отменяет `rAF` (никаких «невидимо анимирующихся» сцен, §3.3). **Детерминизм** — фикс. seed + собственный ГПСЧ; `Math.random()` в построении сцены/топологии запрещён; `resize()` seed не сбрасывает (нормализованные координаты).

### D5. Canvas/geometry/resize: один `#polygon-background` и существующий viewport-адаптер
Один `#polygon-background` (`fixed; inset:0; width/height:100%; pointer-events:none; z-index:0`), прямой потомок `document.body`, **вне** max-width/scroll-контейнеров; отрицательный z-index не используется. `resize` = CSS-размер + drawing buffer (`w*dpr`,`h*dpr`) + `ctx.setTransform(dpr,…)` + пересчёт композиции **без скачка** и **без сброса seed**. `polygon.resize()` встраивается в **существующие** точки (`_onResize`/`setFullscreenFromTma`/`visualViewport`/`ResizeObserver(documentElement)`) — **второй** механизм высоты/`--app-usable-height` не создаётся; `telegram-init.js`/AppShell не переписываются. Sidebar-ширина не вычитается → нет левой полосы/сдвига.

### D6. Liquid Glass: гейт-прототип (7 проверок) → точечно, с честным источником
До интеграции — изолированный прототип в gitignored `tools/` и **7 проверок** (§12.2). Только после успеха — точечно (селектор области, ⛶, декор Статуса) на изолированный `[data-glass-surface]` с **явным источником**: `mountGlass(root, { source: <#polygon-background>, mode:'webgl' })`. **Запрет повтора hotfix10/ADR-1025-18 D1:** никакого `mountGlass` без источника (иначе авто-режим → frosted → белые прямоугольники). Без источника — честный `frosted`, **не** «рефракция». `blur ≠ рефракция`. Sidebar/Header — графитовые; вся карточная прозрачность не снижается. При провале прототипа эпик поставляет только фон (интеграция не выполняется).

### D7. Обязательные численные параметры (§6/§7/§8/§13)
Узлы: **desktop 90–140 / mobile 45–75**; фикс. seed; фильтр треугольников (ребро/площадь/кластер/расстояние до света); топология **≤ 4 Гц** + плавное смешивание; bloom через **offscreen уменьшенного разрешения** (не `filter:blur` на полноэкранном canvas); амплитуда узлов **4–18 CSS px**, различимо за **5–10 с**; mobile **~30 FPS**; DPR-кап desktop ≤2 / mobile ≤1.5; `document.hidden` → stop `rAF`; `prefers-reduced-motion` → качественная **статика**; context-loss/2D-недоступность → честный фолбэк.

### D8. Диагностика, приёмка, деплой
`getDiagnostics()` — 11 полей (не в UI). Playwright: **0/5/10/20 с** (меняется **положение**, не только яркость) + проверка композиции (узлы/полигоны/линии/сиреневая+циановая области/локальные яркие) + материалы (Desktop/Mobile × Статус/Модули × normal/fullscreen + запись) + сравнение с Aurora; чек-лист §15 «НЕ завершено, если…». **Deploy = VERIFIED (да):** меняются ассеты `web/**` и `config/settings.py` → **bump `APP_VERSION` 2.58.18 → 2.58.19** + `README.md` + cache-bust `?v=2.58.19`. Прототипы — в gitignored `tools/`. Форма приёмочного отчёта — §19 spec.

### D9. Инварианты и совместимость
Δ DDL = 0; **Δ каталога = 0**; CSP/zero-build; R17/R18; не ломать §57–§71/F0–F11/S1, IA, сердцебиение (§11/§15), настройки, публикацию; **D4-гейт** (S6/S10 закрыты до live-приёмки Эпика 1) не открывается; live-гейты — PENDING OWNER VERIFICATION; §17 — после деплоя workflow продолжается **без** human gate.

## AMEND / SUPERSEDE / сохранить

| Ранее | Действие | Что именно / почему |
|---|---|---|
| **ADR-1025-17 D6** (Dark Aurora Flow OGL — активный фон) | **SUPERSEDE (активный рендерер)** | Активный фон → Polygon Canvas 2D. `aurora-flow.js`/OGL **сохраняются** как откат (`UI_POLYGON_BG_ENABLED=false`); в DOM не поднимаются при ON. WebGL-разрешение области фона — сохраняется |
| **ADR-1025-18 D6** (`UI_AURORA_FLOW_V2`, flags default-матрица) | **AMEND** | Добавляется `UI_POLYGON_BG_ENABLED` (default ON); Aurora-флаг сохраняется как второй уровень отката |
| **ADR-1025-18 D1** (стекло: точечно только `[data-glass-surface]`, default OFF, frosted честно) | **AMEND (без отката)** | Контракт сохраняется; **добавляется** путь настоящей рефракции анимированного canvas через `source`+`mode:'webgl'` при обязательном прохождении 7 проверок и явном источнике; белые прямоугольники не повторяются |
| **ADR-1025-9 D3** (фон §10: механика/цвета/длительности) | **AMEND → D3/D7** | Фон → Polygon; палитра §5 ТЗ; legacy-механика — фолбэк |
| **ADR-1025-13 D1** (единый источник высоты `--app-usable-height`, flex normal/fullscreen) | **REUSE** | Источник и формула не меняются; canvas получает `resize()` из существующих точек |
| **ADR-1025-13 D3/D4, ADR-1025-16 D1–D4, ADR-1025-12 D3/D5, ADR-1024-24** | **НЕ отменяются** | Геометрия shell/safe-area/header/fullscreen-sync, нативные кнопки, `computeBottomOffset` — без изменений |
| **ADR-1025-9 D2** (Liquid Glass deny-list/тиры/палитра §8) | **Сохранить** | Deny-list/тиры/палитра не расширяются; графитовый shell сохраняется |
| **F0 `persistItems`, F1 IA, F3 селектор/scope, F4 §60 store, F5 §61, F9 SaveBar** | **НЕ отменяются** | Логика не переписывается |
| **ADR-1025-24 D4** (S6/S10 — только после live-приёмки Эпика 1) | **governed-by** | Эпик не открывает D4-гейт |
| **Δ DDL = 0, Δ каталога = 0, CSP/zero-build, R17/R18** | **НЕ отменяются** | Инварианты |
| **ADR-1026-3** | **НОВЫЙ, Approved** | Этот документ (Step 2 @Architect) |

## Последствия

**Positive:** требование ТЗ §0–§17 выполняется отдельным, изолированным рендерером на Canvas 2D без риска для проверенной Aurora; мягкий и жёсткий откат прозрачны (env-only флаг + сохранённый `aurora-flow.js`); адаптер `__AuroraFlow` не трогает существующие вызовы; единственный активный рендерер и отсутствие конкурирующих `rAF`; детерминизм (воспроизводимые тесты); vendored-зависимость по существующему паттерну (CSP/zero-build); честная (реально проверяемая) рефракция стекла **только** после гейта прототипа; инварианты и IA сохранены.

**Negative/издержки:** новая внешняя зависимость (`delaunator`, пусть маленькая и ISC) + build-шаг и `lock`; субъективное качество дизайна **не воспроизводимо headless** → обязательны материалы §14.4 и **PENDING OWNER VERIFICATION**; Canvas 2D + анимированный canvas под стеклом может потребовать WebGL-путь библиотеки (свой контекст) — при этом OGL-Aurora в активном режиме не запущен, конфликта нет; ручная AA-таблица/маркеры тестов требуют атомарных правок; bloom/свет — риск перф-затрат на mobile → mobile-бюджет обязателен.

**Ограничения:** Δ DDL = 0; Δ каталога = 0; CSP `script-src 'self'`/zero-build; один активный фоновый рендерер; WebGL — не для фонового Polygon (Canvas 2D); `backdrop-filter: url()` как опора запрещён; `plans/current_task.md` не изменяется (R17/R18).

## Альтернативы

| Альтернатива | Почему отклонена |
|---|---|
| Заменить содержимое `aurora-flow.js` | Теряется проверенный откат; риск для активного фона; смешение двух алгоритмов; сложный soft-off |
| Отдельный CDN/`<script type=module>` для Delaunator | CSP/§2.1: без CDN; zero-build рантайма → только локальная сборка IIFE |
| OGL как основной рендерер полигонов | §2.2 задаёт Canvas 2D основным; §2.3 — WebGL только при обоснованной необходимости/откате; «один активный рендерер» |
| Оставить два рендерера (Polygon + Aurora) одновременно | §3.3 прямо запрещает конкурирующие сцены/rAF |
| Каталоговый тумблер фона | Δ каталога ≠ 0; применяются env-only `ClassVar` |
| Вторая библиотека стекла / Three.js | §2.4/§2.3 прямо запрещают |
| `mountGlass` без источника (как hotfix9) | Породило белые прямоугольники (hotfix10/ADR-1025-18 D1) |
| SVG-фильтр над анимированным canvas ради «рефракции» | Safari убирает перерисовываемый canvas из фильтра → не рефракция (GOTCHAS 0.5.3) |
| Монтировать стекло на селектор/⛶/карточку без прототипа | §12.2: прототип с 7 проверками обязателен до интеграции |
| Human gate по выбору библиотеки/дизайна | §16/§17: технический выбор — не user-owned tradeoff; gate не требуется |
| Второй источник высоты/`viewport`-механизм | Прецедент ADR-1025-13 F-2 (конкурирующие источники → скачки) |

## Верификация

- **Playwright/DOM** (расширение матрицы): наличие `#polygon-background` (fixed/inset:0/pointer-events:none, вне контейнеров), `getDiagnostics()` по вьюпортам/режимам; кадры **0/5/10/20 с** с числовым подтверждением **смещения положения** (не только яркости); композиция (узлы/полигоны/линии/сиреневая+циановая/локальные яркие); fullscreen/TMA (seed не сброшен, анимация жива, нет левой полосы); `renderer`/`contextLost` при фолбэке; отсутствие второй анимирующейся сцены при ON/OFF.
- **JS/node-юниты:** контракт `__PolygonBackground`/адаптер `__AuroraFlow`; идемпотентность `start/stop/pause/resume`; детерминизм (двойной прогон → идентичная сцена); отсутствие `Math.random()` в построении; отсутствие `filter:blur` на полноэкранном canvas; `node --check` для `polygon-background.js`/`app.js`.
- **Инварианты:** Δ DDL = 0; **Δ каталога = 0** (467/426/442/100/98/21); CSP/no-CDN; `delaunator` SHA/лицензия в vendor README; `git diff --check` = 0; pytest ≥ 8501/0; JS 42/42; маркер `POLYGON-LUMINESCENCE-OK`; `glass.js` OFF → `.ps-glass*` = 0.
- **Только реальный Telegram WebView (владелец, PENDING OWNER VERIFICATION):** живые `innerHeight`/`visualViewport`/fullscreen, FPS, поведение стекла/фона в WebKit/Safari, читаемость. **Не воспроизводимо headless** — не объявляется пройденным и **не останавливает workflow** (§17).

## Откат

- **Soft (env-only, без редеплоя):** `UI_POLYGON_BG_ENABLED=false` → Aurora (`UI_AURORA_FLOW_V2`); далее `UI_AURORA_FLOW_V2=false` → legacy CSS-aurora; `UI_AURORA_BG_ENABLED=false` → page-wash. Стекло — `UI_LIQUID_GLASS_LIB=false` (default OFF).
- **Hard:** annotated-тег `pre-round1026-visual` (T-3162) + `git revert` коммитов пакета + возврат `APP_VERSION`/`?v=`.
- Бэкапы/теги/`stash@{0}` не удалять (R18).
