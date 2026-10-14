# Scanner audit — round1025 hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (T-2866, Step 6)

- **Границы:** рабочее дерево относительно HEAD `5184584` (`pre-round1025-hotfix10`), правки НЕ закоммичены. Вход: `spec.md`/`adr-1025-18`/`evidence.md`/`tasks.md`/UI-отчёт.
- **Вердикт (повторный аудит, после фиксов): Critical 0 / High 0 / Medium 0 / Low 0 / Info 1 — к деплою ГОТОВО** (блокеров нет). Live Telegram WebView — по-прежнему **PENDING OWNER VERIFICATION**, дефект не объявляется закрытым по сборке.

## 0. Повторный аудит (после H-1 + L-H10-1 + L-1 + L-2) — все закрыты
- **H-1 (High, @Reviewer) CLOSED.** `web/static/app.css` `main.scroll-area { grid-auto-rows: max-content; }` — auto-строка grid с `overflow:hidden`-карточкой больше не сжимается. Прогон матрицы **@Scanner** (`tools/ui_round1025_matrix.py`, независимо): `failures: 0`; `.status-block` **scrollH == clientH** на 320/360/390/430 (567/567, 532/532, 508/508, 508/508), 768/1024/1280/1440/1920/2560 и в **fullscreen**; `elementFromPoint` по `.hb-canvas`/`.status-block__bot`/`.status-block__server` — `self=true` во всех режимах. Дизайн сердцебиения не тронут (`.hb-wrap min-height:56px`/`.hb-canvas height:56px` без изменений). Гейт §5 не вакуумный: `_h10_status_card_failures` фейлит отсутствие карточки, `scrollH>clientH+1`, выход центра за бокс и перекрытие чужим элементом.
- **L-H10-1 (Low, @Scanner) CLOSED.** `web/index.html` — `<div v-if="liquidGlassLib" … data-glass-surface>`; офф-проба (`_h10_glass_off_failures`) требует `surfaceCount==0` на 320/360/390/430/1280; фактически `offSurf=0` везде.
- **L-1 (Low) CLOSED.** `glass.js::clearAttrs` снимает `data-glass`/`data-uid`/`data-render`/`data-glass-motion`/`data-ps-loupe` + inline `--g-*` (`removeProperty`); node-юнит наполняет fake-DOM этими атрибутами/пропами и ассертит их отсутствие после `dispose` (`HOTFIX10-GLASS-GEOMETRY-BG-OK`).
- **L-2 (Low) CLOSED.** `.env.example` обновлён: `UI_LIQUID_GLASS_LIB (default OFF)` + описание `[data-glass-surface]`, устаревшая формулировка «только frost-fallback» убрана (`test_l2_env_example_actual`).
- **Прогоны @Scanner (повтор):** `node --check` OK; JS `HOTFIX10-GLASS-GEOMETRY-BG-OK`; `pytest -q` **8319 passed / 0 failed**; матрица **failures: 0**; `git diff --check`=0.

## 1. Прод-дефект белых прямоугольников — устранён (не «лечением opacity»)
- `web/static/glass.js`: `SELECTOR = '[data-glass-surface]'` — единственная цель; `TARGETS` (`.scope-trigger, .header-fs-btn, .status-block`) удалён. В исполняемом коде (без комментариев) функциональных целей НЕТ.
- `config/settings.py`: `UI_LIQUID_GLASS_LIB` default → **OFF** (env-only kill-switch). При OFF `sync(false)` → `disposeAll()`.
- `mountGlass` не вызывается на `.scope-trigger`/`.header-fs-btn`/`.status-block` — в `web/index.html` у них нет `data-glass-surface`.
- `--glass-paper:#fff` (белый) — только дефолт vendored CSS; в авторском CSS тема задана ТОЛЬКО на `.glass-surface` (`--glass-paper: var(--surface-1)` = `#151B2A`, `--glass-ink:#000`). `color-mix(--glass-paper …)` на функциональных элементах не применяется.
- `backdrop-filter: url(` в авторском CSS = 0; внешних CDN/инлайна нет (vendored same-origin, `CSP script-src 'self'` + унаследованный `'unsafe-eval'` для in-DOM Vue).

## 2. Находки
| ID | Severity | Статус | Локация | Суть / доказательство | Ремедиация |
|---|---|---|---|---|---|
| L-H10-1 | Low (визуальный) | **CLOSED** (повторный аудит) | `web/index.html` | Статичный `.glass-surface` при OFF давал ~44 px пустоты. Исправлено `v-if="liquidGlassLib"`; OFF-проба матрицы `surfaceCount==0` (320/360/390/430/1280 — факт `offSurf=0`), `test_lh101_placeholder_hidden_when_off` | — |
| I-H10-1 | Info | **RESOLVED** | `tools/ui_round1025_matrix.py` | OFF-проба теперь ассертит скрытие placeholder (`surfaceCount` = 0) | — |
| I-H10-2 | Info | **RESOLVED** | — | Playwright-матрица перезапущена @Scanner независимо: `failures: 0` (10 вьюпортов, normal+fullscreen, OFF на 5 ширинах); live WebView не воспроизводим headless | — |
| H-1 | High (был @Reviewer) | **CLOSED** (повторный аудит) | `web/static/app.css` `main.scroll-area { grid-auto-rows:max-content }` | Мобильная/полноэкранная карточка «Статус» схлопывалась (`scrollH 567 > clientH 34`). Факт @Scanner: `scrollH==clientH` (567/567, 532/532, 508/508, 508/508 на 320/360/390/430) + fullscreen, `elementFromPoint` по `.hb-canvas`/`__bot`/`__server` — `self=true`; сердцебиение не тронуто | — |
| L-1 | Low | **CLOSED** | `web/static/glass.js` `clearAttrs` | Снимает `data-uid`/`data-glass`/`--g-*` (node-юнит: fake-DOM → dispose → атрибуты/пропы пусты) | — |
| L-2 | Low | **CLOSED** | `.env.example` | `UI_LIQUID_GLASS_LIB (default OFF)` + `[data-glass-surface]`; устаревший текст убран (`test_l2_env_example_actual`) | — |
| I-H10-3 | Info | OPEN (наблюдение) | `web/static/app.css` `main.scroll-area { grid-auto-rows:max-content }` | Правило глобальное (все вкладки, не только «Статус»): строки теперь по контенту и не растягиваются/не сжимаются. Матрица 10 вьюпортов — без регрессий; риск для «пустых» вкладок минимален | Наблюдать «пустые» вкладки на live |

## 3. Инварианты — OK
- **Δ DDL=0:** изменены только `web/**` + `tests/**` + `tools/ui_round1025_matrix.py` + `config/settings.py` + `README.md` + `plans/**`; `services/`/`web/api/`/`bot.py`/`handlers/`/миграции — вне диффа.
- **Δ каталога=0:** 459/98/96/21/418 (pytest `test_webapp_hotfix10_round1025.py` GREEN); `services/param_catalog.py` не тронут; флаги env-only, ∉ `pc.REGISTRY`.
- **`APP_VERSION` 2.58.13 синхронен:** `config/settings.py` + `README.md` + `?v=__APP_VERSION__`-пины; маркер-тесты hotfix6/7/8/9/scope/design/tokens обновлены атомарно (не ослаблены).
- **`--shell-texture`=0** в `web/**` (только doc-комментарии); `backdrop-filter:url(`=0; CSP без CDN/инлайна.
- **R17/R18:** секретов нет; `plans/current_task.md` не изменён/не в индексе; тег `pre-round1025-hotfix10` и `stash@{0}` целы.
- **Гигиена:** в индексе нет `.env`/zip/скриншотов/`tools/_ui_*`; `git diff --check`=0 (только LF→CRLF warning).

## 4. Совместимость / логика — OK
- IA F1/роуты, F4 §60 store, F5 §61 workspace, F0 `persistItems`, F9 SaveBar, F3 guard, ADR-1024-24, flex-геометрия/графит §63, дизайн сердцебиения — не тронуты (`app.js`-правки локальны: `_auroraResize`/`_onVV`/`_syncGlassLib`-комментарий + вызовы resize).
- **Высота:** второй вычет снят (`.fullscreen-mode .scroll-area` → `padding-bottom:1rem`); `.more-sheet` — один offset (`--tg-viewport-bottom-offset`, fallback `env` для старого WebKit) — двойного учёта нет.
- **Main:** `max-width:1440px`/центрирование сняты, подложка `--work-surface-bg` (rgba(9,13,23,.62)) от края sidebar до правого края — полосы нет; лимит 1100 px сохранён.
- **OGL-фон:** `__AuroraFlow.resize` экспортирован; вызовы из `_onResize`, `setFullscreenFromTma` (rAF), `visualViewport` (+ cleanup) и `ResizeObserver(documentElement)`; `gl.viewport`/`uRes` — из фактического drawing buffer; no-op без canvas.
- **Стекло:** честный `detectMode()` (`frosted` без `.ps-glass__refract`); `disposeAll` идемпотентен (`purge` всех `.ps-glass*` + `data-lg-*` + prune отсоединённых).

## 5. Прогоны @Scanner (independent)
- `node --check` glass.js/aurora-flow.js/app.js — OK; `node tests/js/round1025_hotfix10_glass_geometry_bg_test.js` → `HOTFIX10-GLASS-GEOMETRY-BG-OK`.
- Полный `pytest -q` — **8319 passed / 0 failed** (baseline 8291 + новые).
- Матрица UI (независимо, Chromium) — **failures: 0**; разбор `tools/_ui_round1025_raw.json` подтвердил `scrollH==clientH`/hit-тесты.
- JSON/секреты/сырые значения не цитировались (R17).

## Handoff
- **RESULT: SCANNED — Critical 0 / High 0 / Medium 0 / Low 0 / Info 1 → к деплою ГОТОВО @Orchestrator.** H-1 + L-H10-1 + L-1 + L-2 закрыты с доказательствами; новых блокеров нет. Live WebView — PENDING OWNER VERIFICATION (не закрываем по сборке).
