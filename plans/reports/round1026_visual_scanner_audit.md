# Scanner-аудит — EXTRA-визуальный эпик `polygonal-luminescence-round1026` (Step 6, T-3214; финал)

> Дата: 2026-09-23 · Роль: @Scanner (focused diff-based, код не правился).
> Базис: HEAD `9d046e5` (annotated-тег `pre-round1026-visual` → `9d046e5`), правки **НЕ закоммичены**.
> Скоуп: рабочее дерево относительно `9d046e5` — 34 M + 10 ?? (рантайм `web/**`, `config/settings.py`, `web/api/routes.py`, vendor, тесты, планы/отчёты/инструменты).
> Артефакты-вход: `spec.md` (§13–§16), `adr-1026-3-*.md`, `evidence.md`, `tasks.md`, `deployment.md`, `round1026_polygon_background_ui_report.md`, `round1026_polygon_glass_prototype.md`.

## Вердикт

**К деплою — ДА.** Critical 0 / High 0 / **Medium 0** / Low 3 (новые, не блокеры, owned follow-up) / Info 4.
Блокеров для выпуска нет. Все инварианты (Δ DDL=0, Δ каталога=0, CSP/zero-build, один активный рендерер, R17/R18, a11y) выполнены и воспроизведены.

## Таблица severity

| ID | Sev | Статус | Суть |
|---|---|---|---|
| L-POLY1026-1 | Low | OPEN (non-blocking) | `drawFacets`/`drawNodes` аллоцируют массивы/строки на каждую грань/узел каждый кадр (GC-давление на mobile) |
| L-POLY1026-2 | Low | OPEN (non-blocking) | Матрица регресса §71 зафиксирована на `UI_POLYGON_BG_ENABLED=False` → активный (default-ON) путь покрыт только отдельным `tools/ui_round1026_polygon.py` |
| L-POLY1026-3 | Low | OPEN (non-blocking) | В отчёте/спеке CSP записана как `script-src 'self'`, фактический заголовок — `script-src 'self' 'unsafe-eval'` (pre-existing) |
| I-POLY1026-1 | Info | CLOSED | `glass.js::detectMode` (webgl→refraction) без отдельного регресс-теста; влияние — только атрибут `data-lg-mode` |
| I-POLY1026-2 | Info | CLOSED | Фолбэк context-loss/2D-недоступность: нет `contextrestored` → фон off до след. `_syncBgLayer`/reload (по дизайну «честный фолбэк») |
| I-POLY1026-3 | Info | CLOSED | `uiFlag` по умолчанию `true` до `/api/me` (pre-existing) → при auth-фейле soft-OFF не применится (общая семантика env-only флагов) |
| I-POLY1026-4 | Info | CLOSED | `sample()` читает `getImageData` полного DPR-буфера (~2880×1800) — только диагностика, не в rAF |

## Находки с доказательствами

### L-POLY1026-1 [Low, perf/GC, OPEN] — аллокации на грани/узлы каждый кадр
- **Локация:** `web/static/polygon-background.js:425-454` (`drawFacets`), `:488-534` (`drawNodes`).
- **Факт:** на каждый кадр `drawFacets` создаёт `ca`, `cb` (по 3 элемента) и результат `mix(...)` для каждой из ~189 (desktop) / ~93 (mobile) граней основного прохода + двух accent-проходов; `drawNodes` — `mix(...)` для ореолов/центров и `rgba()`-строки. Порядок ~500–1000+ малых объектов/строк за кадр (30–60 FPS).
- **Impact:** GC-давление и микропауза-риск на слабом mobile WebView; headless ~60 FPS (SC-38 для реального устройства — PENDING OWNER). Спека SC-33 запрещает аллокации «все точки каждый кадр» — точки (`computePositions`) действительно не аллоцируют; замечание касается цветовых буферов.
- **Fix (owned follow-up):** переиспользовать скретч-массивы (модульные `_ca/_cb`) вместо литералов + кэшировать `rgba()`-строки по индексу PAL; либо предпосчитать `triPass`-цвета при rebuild.
- **Non-blocking:** функциональность/инварианты не затронуты; замер perf — live-гейт владельца.

### L-POLY1026-2 [Low, gate-coverage, OPEN] — матрица §71 не покрывает активный путь
- **Локация:** `tools/ui_round1025_matrix.py:133-142` (`ME_JSON["ui_flags"]["UI_POLYGON_BG_ENABLED"] = False`).
- **Факт:** регресс-матрица §71 явно зафиксирована на откатном пути Aurora (проверяет `#aurora-flow-canvas`, WebGL context-loss). Default-ON полигональный путь проверяется только прогоном `tools/ui_round1026_polygon.py`.
- **Impact:** будущая регрессия в `_syncBgLayer`/`.polygon-background-canvas`/`html.polygon-bg` не будет поймана основной матрицей (нужен явный прогон). Это осознанное решение (задокументировано в комментарии тула и отчёте §6), не дефект текущей поставки.
- **Fix (owned follow-up):** добавить в матрицу второй режим `UI_POLYGON_BG_ENABLED=True` (или прогонять полигон-скрипт в общем CI-гейте).

### L-POLY1026-3 [Low, evidence-точность, OPEN] — CSP-формулировка уже факта
- **Локация:** `plans/reports/round1026_polygon_background_ui_report.md:7,80`, `spec.md:272`, `adr-1026-3:16`.
- **Факт:** `web/app.py:50-61` — `_CSP_HTML` содержит `script-src 'self' 'unsafe-eval'`; в отчёте записано `script-src 'self'`. Заголовок pre-existing, эпик его не меняет (diff `web/app.py` пуст).
- **Impact:** инвариант «без CDN/inline/eval в НОВОМ коде» соблюдён (vendored same-origin; `eval(` в `polygon-background.js` отсутствует — проверено grep и JS-тестом D). Расхождение — только в формулировке (сложившийся shorthand прошлых аудитов).
- **Fix:** при желании уточнять `script-src 'self' ['unsafe-eval' pre-existing]`.

## Инварианты (проверено @Scanner)

| Инвариант | Результат | Доказательство (воспроизведено) |
|---|---|---|
| Δ DDL = 0 | ✅ | `git diff HEAD --stat -- services/` пуст; миграции/`db/`/`database` пусты; `sha256(services/pg_db.py)=12a88191…e768` == фикстура `f8_baseline.json` |
| Δ каталога = 0 | ✅ | импорт: `REGISTRY=467`, `GROUPS=100`, `_TAB_BY_GROUP=98`, `TAB_RULES=21`, `fields(Settings)=426`; `UI_POLYGON_BG_ENABLED ∉ pc.REGISTRY`; `param_catalog.py` не тронут (sha совпал) |
| CSP / zero-build | ✅ | `<script src>` — только `/static/**` (тест `test_no_cdn_hosts`); vendored `delaunator` same-origin; в `polygon-background.js` нет `eval`/`new Function`/`innerHTML`/`document.write`; SHA-256 `7707D7FE…C1BE` совпал с vendor README/тестом |
| Ровно один активный рендерер | ✅ | `_syncBgLayer` (`web/app.js:11180-11212`) выбирает по `polygonBgEnabled`; ON → `__PolygonBackground.start()` + `legacy.stop()`; OFF → `__PolygonBackground.stop()` + legacy; CSS `html.polygon-bg` гасит `.aurora-flow-canvas`/`.aurora-bg`/`body::before/::after`; JS-тест C (canvas снят из DOM) |
| `Math.random()` в рендере отсутствует | ✅ | grep `Math.random` — только в комментариях; `SEED=20260923` + `mulberry32`; JS-тест D (`!/Math\.random\s*\(/`) |
| rAF/RO/буферы не текут | ✅ | `stop()` → `caf`+`detachCanvas` (disconnect RO, removeChild, освобождение буферов); `pause`/`resume` идемпотентны (JS-тест B/C); `document.hidden` → снятие rAF; `prefers-reduced-motion` → статичный кадр |
| a11y (фон не мешает) | ✅ | `.polygon-background-canvas { position:fixed; inset:0; z-index:0; pointer-events:none }` (`app.css:278-281`); `aria-hidden="true"`; вне max-width-контейнеров (первый child `body`); `#app { z-index: 1 }` выше |
| R17 (секреты/пути) | ✅ | regex-скан новых/изменённых файлов (polygon/vendor/tools/tests/reports): 0 совпадений `sk-…`/BOT-token/`-----BEGIN`/`password=`; логи в модуле отсутствуют (`console.*` = 0) |
| R18 (тег/бэкапы/stash) | ✅ | tag `pre-round1026-visual` существует; `stash@{0}` цел; бэкап `var/backups/visual-round1026-20260923-142355/` (в gitignored `var/`) |
| D4-гейт (публикация/промпты) | ✅ | diff `services/**` пуст; `summary_*`/`_deliver_*`/`image_generation` не тронуты; S6/S10 не открывались; IA/сердцебиение не переписаны (правки `app.js` — только фон) |
| Стекло (D6/J) | ✅ | `UI_LIQUID_GLASS_LIB` default OFF (`settings.py`); `glass.js SELECTOR='[data-glass-surface]'`; `mountGlass` вызывается без `source` только для изолированного декора; J заблокирован гейтом §13.2; `detectMode` расширен только в части честности |
| Canvas/геометрия | ✅ | `#polygon-background` fixed/inset:0/pointer-events:none; `measure()` по `documentElement` (как `aurora-flow.js`), второй механизм высоты не создан; resize пересчитывает CSS+buffer+scale без сброса seed |
| Гигиена | ✅ | `git diff --check` = 0 (только LF→CRLF warning); в индексе/untracked нет `.env`/`current_task.md`/zip/`tools/_ui_*`/скриншотов/`node_modules`; прототипы `tools/_polygon_glass_prototype/`, `tools/_ui_round1026_shots/`, `tools/_ui_round1026_raw.json` — gitignored (`git check-ignore` подтвердил) |
| `APP_VERSION` 2.58.19 синхронен | ✅ | `config/settings.py`, `README.md` (v2.58.19), строгие пины в 16 тестах, `?v=__APP_VERSION__` в `index.html` |
| Маркер-тесты не ослаблены | ✅ | `git diff tests/` — только бампы версий + re-pin `ROUTES_SHA256_F11`; `sha256(web/api/routes.py)=4b652cb1…551b` == новая константа; ослабленных/удалённых assert, `skip`/`xfail` нет; добавлен новый JS-unit (T-3153-стиль) |

## Изменённые файлы (аудит-скоуп)

- **Рантайм:** `web/static/polygon-background.js` (новый, 814 стр.), `web/static/vendor/delaunator.5.0.0.min.js` (новый, IIFE, SHA совпал), `web/index.html` (order: delaunator → aurora-flow → polygon → app.js), `web/app.js` (`polygonBgEnabled`, `_legacyAuroraFlow`, `_syncBgLayer`), `web/static/app.css` (`.polygon-background-canvas`, `html.polygon-bg`), `web/static/glass.js` (`detectMode` + webgl), `config/settings.py` (env-only флаг + bump), `web/api/routes.py` (аддитивно `ui_flags`), `.env.example`, `.gitignore`, `README.md`.
- **Vendor/build:** `tools/vendor/{package.json,package-lock.json,build.mjs,.delaunator-entry.mjs}`, `web/static/vendor/README.md` (версия/лицензия ISC/SHA).
- **Тесты:** `tests/js/round1026_polygon_background_test.js` (новый), `tests/test_webapp_round1026_polygon.py` (новый, 18), `tests/test_webapp_js_unit.py` (+1), 16 файлов — бампы версий/`ROUTES_SHA256_F11`.
- **Планы/инструменты:** `plans/features/polygonal-luminescence-round1026/**`, `plans/reports/round1026_polygon_*.md`, `tools/{ui_round1026_polygon.py,polygon_glass_probe.py,ui_round1025_matrix.py}`, `plans/{backlog.md,workflow_state.md}`, `plans/docs/param-registry-round1025.meta.md`.

## Прогоны @Scanner (воспроизведено независимо)

- `node tests/js/round1026_polygon_background_test.js` → `POLYGON-LUMINESCENCE-OK` (exit 0)
- `node tests/js/round1025_hotfix{7,8,9,10}_*.js` → OK (бампы версий не сломали)
- `.venv\Scripts\python.exe -m pytest tests/test_webapp_round1026_polygon.py -q` → **18 passed**
- `.venv\Scripts\python.exe -m pytest tests/test_webapp_js_unit.py tests/test_round1025_f8_registry.py -q` → **59 passed**
- импорт каталога → 467/426/442/100/98/21 (реально: 467/426/100/98/21 + 442 categorized); `flag_in_registry=False`
- `git diff --check` → 0 (только предупреждения LF→CRLF)
- `git check-ignore` → прототипы/шоты/raw gitignored; `delaunator`/`polygon-background.js` тракабельны
- Документированные прогоны @Builder (не переигрывались из-за объёма, согласованы с артефактами): полный pytest 8520/0, JS 43/43, `ui_round1026_polygon.py` 0 failures, matrix §71 0 failures.

## Выводы по блокам задачи

1. **Critical/High новых нет.** CSP/zero-build ✅; `Math.random` в рендере ✅ отсутствует; XSS/injection в новых render нет (числительная интерполяция, без HTML-sink); один активный рендерер ✅; утечек rAF/RO/буферов нет ✅; R17/R18 ✅; a11y `pointer-events:none` ✅.
2. **Инварианты** (Δ DDL=0, Δ каталога=0 467/426/442/100/98/21, CSP/zero-build, `APP_VERSION` 2.58.19, флаг env-only вне каталога, маркер-тесты не ослаблены) ✅.
3. **D4-гейт:** публикация/промпты/`summary_*` (S1/S2) не тронуты; S6/S10 не открывались; сердцебиение §11/§15 не переделано; IA не изменена ✅.
4. **Стекло (D6/J):** `UI_LIQUID_GLASS_LIB` default OFF; `[data-glass-surface]` — только изолированный декор; функциональные элементы (селектор/⛶/`.status-block`) не получают `mountGlass`; hotfix10 (белые прямоугольники) не воспроизводится (white_frac 0.0046); Sidebar/Header графитовые ✅; блок J корректно **заблокирован** гейтом §13.2.
5. **Canvas/геометрия:** `#polygon-background` fixed/inset:0/pointer-events:none, вне max-width-контейнеров; resize пересчитывает buffer/scale без полосы; второй механизм высоты не создан ✅.
6. **Гигиена:** запрещённых артефактов в индексе нет; `git diff --check` чист; новые прототипы/материалы — в gitignored `tools/` ✅.
7. Отчёты обновлены: этот файл + `full_audit_results.md` + `audit_backlog.md` + `global_map.md`.

## Handoff

**RESULT: SCANNED @Orchestrator** — Critical 0 / High 0 / Medium 0 / Low 3 (L-POLY1026-1..3, все non-blocking, owned follow-up) / Info 4. К деплою **ДА**. Инварианты ✅. Live-гейты (стекло п.1/5/7, перф/видео, реальный Telegram WebView) — **PENDING OWNER VERIFICATION**; блок J — заблокирован гейтом §13.2.

---

# Addendum — правка владельца v2.58.20 «мерцание свечения ×2» (T-3220…T-3223)

> Дата: 2026-09-23 · Роль: @Scanner (focused diff-based, код не правился).
> Базис: HEAD `1ad98ca` (прод-деплой 2.58.19), правки **НЕ закоммичены** — аудит рабочего дерева относительно `1ad98ca` (25 M / 0 ??).
> Спека правки: `plans/archive/polygonal-luminescence-round1026/tasks.md` (блок **R**), `spec.md`, `evidence.md` (addendum).

## Вердикт

**К деплою — ДА.** Critical 0 / High 0 / **Medium 0** / Low 0 (новых) / Info 1 (pre-existing, non-blocking). Блокеров нет.

## Diff-scope (гигиена)

- Изменён ровно ожидаемый набор: `web/static/polygon-background.js` (ядро), `config/settings.py` + `README.md` + `plans/docs/param-registry-round1025.meta.md` (bump 2.58.20), `plans/archive/polygonal-luminescence-round1026/{spec,tasks,evidence}.md` (блок R), 19 test-файлов (re-pin версии).
- `git diff --name-only 1ad98ca` вне `^(web/static/polygon-background.js|README.md|config/settings.py|plans/|tests/)` → **пусто**. НЕТ правок `services/**`, схемы/миграций, `param_catalog.py`, стекла (J), публикации, сердцебиения, IA (`web/app.js` вне диффа). `plans/current_task.md` не тронут (R17).
- `git diff --check 1ad98ca` → 0 (только LF→CRLF warnings); запрещённых файлов в индексе/untracked нет.

## Существо правки (построчно)

- Константы: `PULSE_SPEED_MIN 0.05→0.025`, `PULSE_SPEED_MAX 0.15→0.075`, `GLOW_SHIMMER_SPEED 0.06→0.03` — ровно ×0.5 (период ×2).
- Точки применения: `pulseSp: PULSE_SPEED_MIN + rng()*(MAX-MIN)`; `Math.sin(t*GLOW_SHIMMER_SPEED + cl.ph)`. Прежние магические скорости (`pulseSp: 0.05 +`, `sin(t*0.06 …)`) удалены.
- **НЕ тронуты:** движение узлов §9 (`sp1 0.10+0.22`, `sp2 0.08+0.18`), morph §8.1 (`sin(t*0.06+ph)`), дрейф световых центров §8.2 (`sin(t*0.045)`,`cos(t*0.038)`), топология §6.4 (`TOPO_HZ=4`).
- Перф/детерминизм: `Math.random` = 0; `DPR_CAP 2/1.5`, `NODES 110/55`, `TOPO_FADE_MS=320`, `MAX_EDGE_NORM/MAX_TRI_AREA` не изменены; reduced-motion/`document.hidden`/context-loss-код не тронут.

## Тест-гейт (не тавтологичен)

- Python `TestGlowFlickerSlowdown` (5 тестов): `_const(name)*2 == BASE` (BASE=0.05/0.15/0.06) — **возврат старых значений роняет тест**; применение только через константы; отсутствие старых магических скоростей; не-мерцание (§9/§8.1/§8.2/`TOPO_HZ=4`) как неизменные.
- JS блок **F**: `strictEqual(value*2, base)` + `strictEqual(TAU/speed / (TAU/base), 2)` (float-exact), те же негативы/неизменности.
- `getDiagnostics()` = **11 полей** (renderer, canvasWidth, canvasHeight, devicePixelRatio, nodeCount, triangleCount, frameCount, lastFrameTime, isPaused, isReducedMotion, contextLost).

## Инварианты (воспроизведено @Scanner)

| Инвариант | Результат | Доказательство |
|---|---|---|
| Δ DDL = 0 | ✅ | `git diff 1ad98ca -- services/ db/` пусто; схема не тронута |
| Δ каталога = 0 | ✅ | REGISTRY 467 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21 / fields(Settings) 426 (+442 categorized); `param_catalog.py` не тронут |
| CSP/zero-build | ✅ | `polygon-background.js`: `eval(`/`new Function`/`innerHTML`/`document.write` = 0; `index.html` — только `/static/**`, без CDN; `script-src 'self'` (+ pre-existing `'unsafe-eval'` для Vue full — L-POLY1026-3, не new) |
| Один активный рендерер | ✅ | `window.__PolygonBackground` singleton-адаптер; `web/app.js` (`_syncBgLayer`) вне диффа |
| R17 / R18 | ✅ | `current_task.md` не тронут; tag `pre-round1026-visual`→`9d046e5` цел; `stash@{0}` цел (1 шт.); бэкап `var/backups/visual-round1026-20260923-142355/` есть |
| `APP_VERSION` 2.58.20 | ✅ | settings/README/meta синхронны; 28 ссылок `2.58.20`; «висящих» пинов `2.58.19` в тестах нет |
| Маркер-тесты не ослаблены | ✅ | `git diff tests/` — только version re-pin (нет `skip`/`xfail`/удалённых assert); 295 re-pin тестов зелёные |

## Прогоны @Scanner (независимо)

- `node tests/js/round1026_polygon_background_test.js` → `POLYGON-LUMINESCENCE-OK`
- re-pin JS hotfix7/8/9/10 → OK; всего `tests/js/*.js` = 43
- `pytest tests/test_webapp_round1026_polygon.py -q` → **23 passed**
- `pytest` re-pin (12 файлов) → **295 passed**
- `git diff --check` → 0; tag/stash/backup → OK

## Замечания

- **I-POLY1026-5 [Info, pre-existing, non-blocking]:** docstring `tests/test_webapp_round1026_polygon.py:7` (и evidence) упоминают `SQLite user_version=12`, тогда как схема версионируется в `services/database.py` (`_SCHEMA_VERSION*`), а `db/**/*.sql` отсутствует (`test_zero_ddl` проходит вакуумно). Δ DDL=0 для данной правки доказан diff-скоупом (в `services/**`/`db/**` ничего не менялось). Расхождение — evidence-точность, не регрессия.
- L-POLY1026-1..3 — остаются OPEN owned-follow-up (к данной правке не относятся: код рендера/матрицы не менялся).

## Handoff

**RESULT: SCANNED @Orchestrator** — Critical 0 / High 0 / Medium 0 / Low 0 (новых) / Info 1 (I-POLY1026-5, pre-existing). Правка v2.58.20 (мерцание свечения ×2) — **к деплою ДА**, блокеров нет. Инварианты ✅. Live-гейты (перф/стекло/реальный WebView) — PENDING OWNER VERIFICATION.
