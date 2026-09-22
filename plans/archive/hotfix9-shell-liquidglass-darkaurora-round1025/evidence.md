# Evidence — HOTFIX9 `hotfix9-shell-liquidglass-darkaurora-round1025` (Step 4 @Builder)

> **Fix-раунд (после review.md/round1025_hotfix9_scanner_audit.md):** H-H9S-1
> (High, блокер) и M-H9R-1 (Medium) закрыты; L-H9S-1/L-H9S-2/L-H9S-3 и
> ревьюer-Low (`scrollIntoView` + ненулевой `scale` feDisplacementMap) —
> см. раздел «Fix-раунд» ниже. Деплой/мерж не выполнялись.

- **HEAD:** `b374c0f` (working tree; изменения не закоммичены — Step 4 Builder, деплой/мерж не выполнялись).
- **`APP_VERSION`:** 2.58.11 → **2.58.12**.
- **Инварианты:** Δ DDL = 0 (миграций/ALTER нет), Δ каталога = 0 (`REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` — тесты зелёные).

## Изменённые / новые файлы

**Runtime:**
- `web/static/app.css` — единый `--app-usable-height` (+ алиас `--shell-h`), flex-колонка `shell-mobile`/fullscreen, `main.scroll-area` — единственный скроллер, `.bottom-nav` в потоке, safe-area один раз; header `flex:0 0 auto`; модалка `modal-actions`/`modal-head`; полное удаление `--shell-texture`; графитовые токены §8; слой Dark Aurora Flow.
- `web/static/telegram-init.js` — `--app-usable-height = max(0, innerHeight − computeBottomOffset(...))` (формула D3 ADR-1025-12 не менялась), пересчёт по `visualViewport`/resize.
- `web/app.js` — флаги `shellFlexV3/shellGraphiteV3/liquidGlassLib/auroraFlowV2`; `scrollTop=0` для `.scroll-area` при смене раздела; `_hbResize()` (fullscreen/viewport); `_syncBgLayer`→Aurora Flow; `_syncGlassLib`; class-binding flex.
- `web/index.html` — flex-класс, footer `.modal-actions` (+ SaveBar из `.modal-body`), vendored `<script>`/`<link>` (same-origin, `?v=`).
- `config/settings.py` — 4 env-only `ClassVar` флага + bump.
- `web/api/routes.py` — аддитивно 4 флага в `GET /api/me.ui_flags`.
- `.env.example`, `README.md`, `.gitignore`.

**Новое (vendored/модули/прототип/инструменты):**
- `web/static/vendor/ogl.1.0.11.min.js`, `liquidglass.core.0.5.3.min.js`, `liquidglass.core.0.5.3.css`, `README.md` (версия/license/sha256/сборка).
- `tools/vendor/{package.json,package-lock.json,build.mjs}` — локальная сборка IIFE (npm — только инструмент; `node_modules` в `.gitignore`).
- `web/static/aurora-flow.js` — `window.__AuroraFlow` (OGL shader + Canvas2D fallback, DPR-кап, hidden/reduced-motion/context-loss, `sample()`).
- `web/static/glass.js` — `window.__LiquidGlass.sync()` (mountGlass на `.scope-trigger`, `.header-fs-btn`, `.status-block`).
- `tools/glass_prototype/{index.html,glass-mount.js}`, `tools/glass_prototype_probe.py` — гейт настоящего преломления.
- `tools/ui_round1025_matrix.py` — H9-пробы, кадры фона, modal-проба, симуляция `--app-usable-height`.
- `tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js`, `tests/test_webapp_hotfix9_round1025.py` (+ атомарные правки маркеров hotfix4/6/7/8, `ui_rework_round1020`, `js_unit`, версии).

## Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| JS-синтаксис | `node --check web/app.js` / `telegram-init.js` / `aurora-flow.js` / `glass.js` / vendored бандлы | OK |
| Python-синтаксис | `py -m py_compile tools/ui_round1025_matrix.py`, `node --check tools/vendor/build.mjs` | OK |
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **8291 passed**, 0 failed (baseline 8272; +18 hotfix9, +1 fix-раунд: парсерный маркер вложенности `.modal-actions`) |
| Матрица §12 | `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов × 5 режимов); модалка модуля и context-loss — зелёные |
| Прототип стекла | `.venv\Scripts\python.exe tools/glass_prototype_probe.py` | **failures: 0**: `mounted=true`, `hasDisplacement=true`, `displacementScale=14.56`, `diffGlass=15.97`, `diffHole=63.817`, console=[] |
| `git diff --check` | `git diff --check` | OK (только CRLF-предупреждения) |
| Δ каталога | `tests/test_webapp_hotfix9_round1025.py::TestFlagsAcceptance::test_catalog_invariants` | 459/98/96/21/418 — PASS |
| Δ DDL | миграции не добавлялись/не менялись (`git status`) | 0 |

### Ключевые данные матрицы (факт из `tools/_ui_round1025_raw.json`)
- `auroraMode = 'webgl'` (OGL-путь) на 390×844 и 1280×800.
- Фон 0/5/10/20 с: `diffs = [16.484, 17.781, 11.604]` (390×844), `[16.542, 18.51, 23.01]` (1280×800) → движение реально и не «пара пикселей».
- `glassMounted = 3` (`.scope-trigger`, `.header-fs-btn`, `.status-block`), `glassFailed = 0` на всех вьюпортах; `tokenShellTexture = ''` (текстура удалена).
- Точечная проверка: `ps-glass`-класс и `feDisplacementMap`-путь добавляются библиотекой; селектор области остаётся нажимаемым (`elementFromPoint`), выпадающий список открывается, console/pageerror = 0.
- `headerOverlapsCard = false`; `navLinks = 4`, все `hitSelf = true`, hit ≥ 44px; `scopeClickable = true`.
- Fullscreen: `hbVisible = true`, `headerOverlapsCard = false`, `glassFailed = 0`, console/pageerror = 0.
- Модалка (`#/access/roles`): `actionsBottom = 680 (< 844)` и `650 (< 800)` → footer/SaveBar целиком в экране; `modal-body` не перекрывает footer.

## Затронутые acceptance-сценарии UPD3

- §3/§4 геометрия+nav (P0): flex-колонка, nav в потоке, safe-area один раз — подтверждено DOM-пробами (failures 0; `bottom ≤ stableHeight`).
- §5 header/fullscreen: `flex:0 0 auto`, `scrollTop`, виджеты/сердцебиение в fullscreen.
- §6 модалка/SaveBar: `modal-card > modal-head/modal-body/modal-actions`, существующий `<sticky-save>` переиспользован, логика F0/F9 не менялась.
- §7/§8 текстура удалена; графитовые токены §8; shell ≠ карточки.
- §9 преломление: vendored `feDisplacementMap`-путь, объективный прототип-гейт (содержимое позади меняет кадр стекла).
- §10 фон: OGL shader, палитра §10, скорость, перф-контроль (DPR-кап/hidden/reduced-motion/context-loss).
- §11 сердцебиение: дизайн/данные не менялись; только `_hbResize()` (перерисовка после viewport/fullscreen).

## НЕ проверено / PENDING OWNER VERIFICATION

- **Живой Telegram WebView** (Android/iOS): реальные insets/клавиатура, «панель целиком в экране», FPS стекла/фона, Safari/WebKit-поведение `feDisplacementMap` — **НЕ воспроизводимо headless**, объявляется **PENDING OWNER VERIFICATION** (не пройдено).
- **`@liquidglassjs/core` на non-Chromium:** библиотека сама падает на `blur()` (frost) — честный fallback; в headless Chromium путь реального преломления подтверждён (`feDisplacementMap`).
- **R17/R18:** секретов/сырых значений в отчётах нет; `plans/current_task.md` не изменялся и не коммитится.

## Fix-раунд (H-H9S-1, M-H9R-1, Lows) — после review.md / scanner audit

**Изменённые файлы fix-раунда:** `web/index.html`, `web/static/aurora-flow.js`,
`web/app.js`, `web/static/telegram-init.js`, `web/static/app.css` (без правок —
подтверждён токен), `config/settings.py` (комментарий), `.env.example`,
`tools/ui_round1025_matrix.py`, `tools/glass_prototype_probe.py`,
`tests/test_webapp_hotfix9_round1025.py`.

- **H-H9S-1 (High, закрыт):** в модалке модуля (`v-if="activeModule"`) добавлен
  пропущенный `</div>` → `footer.modal-actions` снова **сиблинг** `.modal-body`
  внутри `.modal-card`. Доказательство: парсер (`html.parser`) по рабочему дереву
  — 5 `footer.modal-actions`, вложенных в `.modal-body` **0**; при искусственном
  удалении `</div>` тот же парсер даёт `nested_in_modal_body=[1924]` (тест
  `TestModal::test_modal_actions_sibling_of_body` краснеет). Access-модалки и
  модалка досье — сиблинги (парсер), не сломаны.
- **M-H9R-1 (Medium, закрыт):** `aurora-flow.js` — при `webglcontextlost`
  монтируется **свежий** canvas (`attach2dFallback`) и подменяется в DOM (старый,
  занятый WebGL-контекстом, 2D не отдаёт); кадр рисуется даже на паузе/hidden.
  Проба матрицы: `390×844 → mode='canvas2d', sampleCount=64, brightness=46`;
  `1280×800 → mode='canvas2d', sampleCount=64, brightness=50` (0 failures).
- **L-H9S-1 (закрыт):** `stop()` → `detachCanvas()` убирает `#aurora-flow-canvas`
  из DOM (нет «застывшего» кадра при OFF); следующий `start()` поднимает заново.
- **L-H9S-2 (закрыт):** `shellGraphiteV3` = `UI_SHELL_GRAPHITE_V3 && UI_SHELL_V3`
  (legacy-флаг снова действует как алиас soft-отката `.shell-v3-off`); синхронно
  обновлены комментарии `config/settings.py` и `.env.example`.
- **L-H9S-3 (закрыт):** с `.status-block` снят `data-glass="a"` — устранена
  двойная обработка (legacy-линза + vendored Liquid Glass); маркер-тест
  `class="card p-4 status-block"` не затронут.
- **Ревьюer Low (закрыт):** `telegram-init.js::applyInsetSafe` → при
  `visualViewport`/resize активное поле внутри `.modal-body` приводится в
  видимость `scrollIntoView({block:'nearest'})` (логика сохранения не менялась).
- **Ревьюer Low (закрыт, усилен):** `glass_prototype_probe.py` теперь читает
  фактический `scale` живого `feDisplacementMap` (`displacementScale=14.56 > 0`)
  в дополнение к `diffGlass` при сдвиге фона позади.
- **Пробы модалки модуля (§12):** `modalBody.bottom < modalActions.y` на всех
  репрезентативных вьюпортах: 390×844 `675 < 683`; 768×1024 `785 < 793`;
  1280×800 `673 < 681`; `stickyInActions=true`; `actionsBottom` в экране
  (761/851/739 при высотах 844/1024/800).
