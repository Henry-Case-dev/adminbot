# EVIDENCE — hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (T-2843…T-2864)

> Заполнил @Builder (Step 4). Baseline: HEAD `5184584`, `APP_VERSION` 2.58.12 → **2.58.13**.
> Δ DDL = 0, Δ каталога = 0 (459/98/96/21/418). `plans/current_task.md` не изменялся (R17/R18).
> Живой Telegram WebView **НЕ проверялся** — **PENDING OWNER VERIFICATION** (UPD4 §7/§8).

## Изменённые файлы (код)

| Файл | Что |
|---|---|
| `config/settings.py` | `UI_LIQUID_GLASS_LIB` default → **False** (env-only kill-switch); `APP_VERSION = "2.58.13"` |
| `web/static/glass.js` | `SELECTOR='[data-glass-surface]'` (единственная цель); `purge()` удаляет все `.ps-glass*`; `clearAttrs()` — `data-lg-*`; `disposeAll`/`sync` идемпотентны + prune отсоединённых; `detectMode()` = `frosted`/`refraction` |
| `web/app.js` | `_syncGlassLib` — только `[data-glass-surface]`; `_auroraResize()`; вызовы resize из `_onResize`, `setFullscreenFromTma`, `visualViewport` (`_onVV` + cleanup) |
| `web/static/aurora-flow.js` | `measure()` по фактическому контейнеру (`documentElement.clientWidth/Height`, не per-canvas 300×150 от OGL); `gl.viewport` + `uRes` из drawing buffer; экспорт `__AuroraFlow.resize`; `ResizeObserver` по `documentElement` |
| `web/static/app.css` | токен `--work-surface-bg`; `.glass-surface` контракт (isolation/contain/pointer-events/paper); снят `max-width:1440px`+центрирование с `main.scroll-area` (desktop), подложка; `.fullscreen-mode .scroll-area` без второго safe-area; `.more-sheet` — один offset |
| `web/index.html` | изолированный `<div class="glass-surface" data-glass-surface aria-hidden>` на «Статусе» |
| `README.md` | версия 2.58.13 |
| `.env.example` | L-2: doc `UI_LIQUID_GLASS_LIB` (default OFF, монтирование только на `[data-glass-surface]`) |
| `tools/ui_round1025_matrix.py` | `H10_PROBE_JS`, `H10_GLASS_ISOLATION_JS`, `_h10_failures`, `_h10_glass_failures`, `ME_GLASS_OFF`, `_h10_glass_off_failures` + интеграция (normal/fullscreen/glass-off); **review-fix:** `_h10_status_card_failures` (обрезка + hit-test), OFF-проба на 320/360/390/430/1280 |
| `tests/js/round1025_hotfix10_glass_geometry_bg_test.js` | новый node-юнит (функциональный fake-DOM для glass.js) |
| `tests/test_webapp_hotfix10_round1025.py` | новый pytest-маркер-гейт |
| `tests/test_webapp_js_unit.py` | регистрация нового JS-теста |

**Маркер-тесты (атомарно обновлены под 2.58.13/новые токены):** `tests/js/round1025_hotfix7..9` (version), `tests/js/round1025_design_tokens_test.js` (`--glass-paper`/`--glass-ink` в инвентарь), `tests/js/round1025_hotfix4_shell_test.js` (safe-reserve `.more-sheet` = один `env`, без суммы), `tests/test_scope_selector_round1025.py`, `tests/test_webapp_design_tokens_round1025.py`, `tests/test_webapp_hotfix6..9_round1025.py` (version).

## Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| `node --check` | `web/static/glass.js`, `web/static/aurora-flow.js`, `web/app.js` | OK |
| JS-юниты | `node tests/js/*.js` (35 файлов) | **ALL-JS-OK** (0 fail) |
| pytest (полный) | `.venv\Scripts\python.exe -m pytest -q` | **8319 passed** (после review-fixes; baseline 8291 + hotfix10 + 5 review-fix тестов) |
| Матрица UI (Chromium) | `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов, normal+fullscreen; усиленный §5-гейт + OFF-проба на 320/360/390/430/1280) |
| инварианты | pytest `test_webapp_hotfix10_round1025.py` | Δ каталога 459/98/96/21/418; CSP без CDN/url-backdrop |

## Acceptance (UPD4) — фактические пробы

- **§1 стекло снято.** OFF: `mountedCount=0`, `psTotal=0`; функциональные цели геометрия/нажимаемость сохранены (`hotfix10_glass_off` на 390×844 и 1280×800). Прозрачность НЕ использовалась.
- **§2 изолированное стекло.** ON: `surfaceCount=1`, `surfaceMode=frosted` (честно), `psFunctional=[0,0,0]`; OFF↔ON rects и `elementFromPoint` идентичны; после `dispose()` `psTotal=0` (`hotfix10_glass_isolation.ok=true`).
- **§3 Main.** desktop: `main.x=216` (край sidebar), `right=innerW`, `background=rgba(9,13,23,0.62)` (нет яркой полосы); лимит 1100px на `.module-list/.module-quick-wrap/.module-toolbar`; отрицательных отступов нет.
- **§4 высота.** Второй вычет снят (`.fullscreen-mode .scroll-area` → `padding-bottom:1rem`); `.more-sheet` — один offset; nav: 4 пункта, hit ≥44px, `elementFromPoint` (H9-проба, failures 0).
- **§5 карточка (review H-1 исправлен).** Изначально `[x]` был проставлен преждевременно: на mobile (320/360/390/430) `.status-block` схлопывался до **34px** (`scrollH=500…567 > clientH=32`), `overflow:hidden` резал контент, а следующая карточка (`intel`) наезжала на сердцебиение (`elementFromPoint` центра canvas → `intel-title`). Причина — auto-строка `main.scroll-area` (grid с определённой высотой) с item `overflow:hidden` давала нулевой вклад. **Fix:** `main.scroll-area { grid-auto-rows: max-content; }` (дизайн сердцебиения и `.status-block { max-width:100%; overflow:hidden }` не тронуты). После: mobile `scrollH == clientH` (567/532/508/508) и `elementFromPoint` центра `.hb-canvas`/`__bot`/`__server` → сам элемент (normal **и** fullscreen); desktop fullscreen (`768…2560`) также `scrollH == clientH` (ранее схлопывался до 32).
- **§5 гейт усилен.** `_h10_failures`/`_h10_glass_off_failures` теперь проверяют `scrollHeight==clientHeight` и hit-test центра `.hb-canvas`/`__bot`/`__server` (+ центр внутри бокса карточки), не только `height>0`/innerText; OFF-проба расширена на 320/360/390/430/1280 и ассертит `surfaceCount==0`. **Гейт не вакуумный:** при откате фикса (`grid-auto-rows:auto`) он даёт `failures=1` на 390×844 и 430×932 (`scrollH=508 > clientH=32`).
- **L-H10-1.** Пустой декоративный `[data-glass-surface]` при `UI_LIQUID_GLASS_LIB=OFF` больше не рендерится (`v-if="liquidGlassLib"`) — нет ~44px+gap пустоты; при ON место резервируется. Проба OFF: `surfaceCount=0, mountedCount=0, psTotal=0` на всех ширинах.
- **L-1.** `glass.js::clearAttrs` снимает с root библиотечные `data-glass`/`data-uid`/`data-render`/`data-glass-motion`/`data-ps-loupe` и inline `--g-*` (`removeProperty`) — полный сброс после dispose (покрыто fake-DOM юнитом).
- **L-2.** `.env.example` актуализирован: `UI_LIQUID_GLASS_LIB` **default OFF**, монтирование только на `[data-glass-surface]`, функциональные цели стекло не получают.
- **§6/Доп.P0 фон.** `canvasRect` = viewport в normal и fullscreen (390×844, 1280×800). Кадры 0/5/10/20 с: diffs `[16.5, 17.9, 11.6]` (390×844) и `[16.1, 18.8, 23.3]` (1280×800) — движение заметно. CSS-градиенты поверх WebGL не добавлялись.
- **§7 честность.** Результаты получены в **Chromium/headless**; живой Telegram WebView — **PENDING OWNER VERIFICATION**.

## Не удалось / ограничения

- **Живой Telegram WebView (WebKit/Android/iOS) не воспроизводим headless** — фактические `innerHeight`/`visualViewport.height`/`viewportHeight`/`viewportStableHeight`/`safeAreaInset.bottom`/`contentSafeAreaInset.bottom`, FPS и поведение нативной полноэкранной области остаются за владельцем. Не выдаётся за пройденное.
- `ConnectionAbortedError [WinError 10053]` в хвосте вывода матрицы — фоновый поток тестового HTTP-сервера после `shutdown()`, к результату (`failures: 0`) отношения не имеет.
- `.bottom-nav`-legacy (`position:fixed`) оставлен **только** под `.shell-layout-legacy` (вне активного режима); удаление не выполнялось, т.к. конфликт снят.
