# evidence.md — `polygonal-luminescence-round1026` (Step 4 @Builder)

> Маркер: `POLYGON-LUMINESCENCE-OK`. Базис HEAD `9d046e5` (== origin/master).
> `APP_VERSION` **2.58.18 → 2.58.19**. Все команды — из корня репозитория.

## Изменённые / новые файлы (irrefutable)

**Новые:**
- `web/static/polygon-background.js` — фоновый рендерер (Canvas 2D, Delaunator, bloom, свет, движение). Контракт `__PolygonBackground` + адаптер `__AuroraFlow`.
- `web/static/vendor/delaunator.5.0.0.min.js` — vendored IIFE (SHA-256 `7707D7FE750559D4D31DBDEBEA5E41024487520BC1CC9967AC9795B4A682C1BE`, ISC).
- `tools/vendor/.delaunator-entry.mjs`; `tests/js/round1026_polygon_background_test.js`; `tests/test_webapp_round1026_polygon.py`; `tools/ui_round1026_polygon.py`; `tools/polygon_glass_probe.py`; `plans/reports/round1026_polygon_background_ui_report.md`; `plans/reports/round1026_polygon_glass_prototype.md`.
- gitignored: `tools/_polygon_glass_prototype/**`, `tools/_ui_round1026_shots/**`, `tools/_ui_round1026_raw.json`.

**Изменённые:**
- `web/index.html` (script delaunator + polygon-background), `web/app.js` (`polygonBgEnabled`, `_syncBgLayer`, `_legacyAuroraFlow`), `web/static/app.css` (`.polygon-background-canvas`, `html.polygon-bg`), `web/static/glass.js` (`detectMode` — WebGL-путь).
- `config/settings.py` (`UI_POLYGON_BG_ENABLED` ClassVar + `APP_VERSION`), `web/api/routes.py` (аддитивно `ui_flags`), `.env.example`.
- `tools/vendor/{package.json,package-lock.json,build.mjs}`, `web/static/vendor/README.md`, `tools/ui_round1025_matrix.py` (polygon OFF для §71), `README.md` (v2.58.19), `plans/docs/param-registry-round1025.meta.md`.
- версии в тестах: `tests/test_webapp_hotfix{6,7,8,9,10}_round1025.py`, `tests/test_webapp_{f6,f7,f9,f11}_round1025.py`, `tests/test_webapp_design_tokens_round1025.py`, `tests/test_scope_selector_round1025.py`, `tests/test_round1025_f8_registry.py` (+ SHA routes), `tests/js/round1025_hotfix{7,8,9,10}_*.js`, `tests/test_webapp_js_unit.py`.

## Прогоны (факт)

| Команда | Результат |
|---|---|
| `node --check web/static/polygon-background.js` (+ aurora-flow.js, app.js) | OK |
| `node tests/js/round1026_polygon_background_test.js` | `POLYGON-LUMINESCENCE-OK` |
| все `node tests/js/*.js` | **43 файла, 0 failing** |
| `.venv/Scripts/python.exe -m pytest -q` | **8520 passed, 0 failed** (baseline 8501; +19) |
| `.venv/Scripts/python.exe tools/ui_round1026_polygon.py` | **0 failures** (desktop+mobile × status/modules; motion 0/5/10/20 с) |
| `.venv/Scripts/python.exe tools/ui_round1025_matrix.py` (§71, polygon OFF) | **0 failures** (низкий TG 0; 10 вьюпортов) |
| `.venv/Scripts/python.exe tools/polygon_glass_probe.py` | **0 failures**, 3 PENDING_OWNER |
| `node -e` проверка vendor | `typeof Delaunator === 'function'`, `typeof Delaunator.from === 'function'` |
| `git diff --check` | чисто (только warning LF→CRLF) |
| Δ DDL | 0 (`services/pg_db.py` не менялся; `test_param_catalog_unchanged`/`test_ddl_source_unchanged` зелёные) |
| Δ каталога | 0 (`UI_POLYGON_BG_ENABLED` ∉ `pc.REGISTRY`; 467/426/442/100/98/21) |

## Фактические метрики (Playwright, `tools/_ui_round1026_raw.json`)

- desktop: nodeCount **110**, triangleCount **189**; mobile: **55 / 93**.
- motion 0/5/10/20 с: median_shifts **1.41** ячейки/шаг, corr(0,20с) **0.943** (desktop) / **0.893** (mobile) → меняется **положение**, не только яркость.
- композиция: сиреневые **6.7 % / 3.8 %**, циановые **8.2 % / 4.4 %**, edge-density **0.306 / 0.274**, local_ratio **2.19 / 2.28**.
- fullscreen: `frameCount` растёт, `nodeCount` не меняется, `rect.x=0`, `rect.w==innerWidth`.
- один рендерер: `visibleBgCanvases=1`, `#aurora-flow-canvas` отсутствует.
- стекло-прототип: `mode=refraction` (явный `source`), white_frac **0.0046**, mobile **~60 FPS**, конфликта WebGL нет.

## Покрытые сценарии приёмки (spec §16)

SC-01…SC-08 (замена/адаптер/один рендерер), SC-09…SC-11 и SC-16…SC-19 (композиция/палитра/свет/bloom), SC-12…SC-15 (seed/узлы/фильтр/топология), SC-20…SC-23 (morph/дрейф/импульсы/движение), SC-24/SC-25/SC-26/SC-27 (canvas/resize/fullscreen/без полосы), SC-28…SC-30 (glass-прототип/честность — интеграция не выполнена), SC-31 (нет WebGL-конфликта), SC-32…SC-34 (перф/hidden/reduced), SC-35…SC-39 (диагностика/движение/композиция/материалы/сравнение), SC-40 (§15-чеклист), SC-41 (PENDING §17).

## Не проверено / ограничения (честно)

- **PENDING OWNER VERIFICATION:** реальная оптическая рефракция стекла, внешний ореол, перф/плавность/читаемость в реальном Telegram WebView; видеозапись анимации.
- Блок **J** (glass-интеграция) — **заблокирован** гейтом §13.2 (см. отчёт).
- `prefers-reduced-motion` статика и `document.hidden` pause/resume покрыты кодом и unit-тестом, но **не** измерены в headless-прогоне (нет эмуляции reduced-motion/hidden с пиксельной пробой).
- Δ DDL подтверждён отсутствием правок `services/pg_db.py`/`db/**` и зелёными заморозками; `user_version=12` не перечитывался отдельно (не менялся).
