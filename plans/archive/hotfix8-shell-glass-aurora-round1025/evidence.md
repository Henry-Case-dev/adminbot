# evidence.md — HOTFIX8 `hotfix8-shell-glass-aurora-round1025` (Step 4 @Builder)

> **Baseline:** HEAD `a1e6db3`, `APP_VERSION` **2.58.10**, JS 32 файла, каталог 459/98/96/21/418.
> **ТЗ:** UPD2 `plans/current_task.md:6156-6496`; `spec.md` + `adr-1025-16` (Step 2). Bump T-2786 — **не выполнялся** (Block G, предшествует deploy T-2787).
> **R17/R18:** без секретов; `plans/current_task.md` не изменялся/не коммитился; теги/бэкапы/`stash@{0}` не трогались.

## Изменённые файлы (реализация)

| Файл | Что |
|---|---|
| `web/static/app.css` | shell §4 токены (`--shell-bg .72`, `--shell-bg-mobile .78`, border `.08`, highlight `.06`, shadow, `blur(18px) saturate(115%)`), `[data-glass="shell"]` рецепт + нейтральный sheen `::after` (≤.05, `#lg-lens`), `.shell-v3-off`-откат; aurora/mesh (`body::before`/`body::after`/`.aurora-bg` 5 blob + grain, keyframes, pause, reduced-motion, `html.bg-wash-legacy` conic-фолбэк); sidebar 216px, радиусы 18px, `.scope-trigger` 16px |
| `web/index.html` | `.aurora-bg` слой (5 blob + grain); `data-glass="a"` → `data-glass="shell"` (sidebar/header/drawer/bottom-nav/more-sheet); класс `shell-v3`/`shell-v3-off` на `.app-shell` |
| `web/app.js` | computed `shellV3`, `auroraBgEnabled`; `_syncBgLayer()` (html.bg-wash-legacy); вызовы в `mounted`/`loadMe` |
| `config/settings.py` | env-only `ClassVar` `UI_SHELL_V3`, `UI_AURORA_BG_ENABLED` (default ON) |
| `web/api/routes.py` | доставка обоих флагов в `GET /api/me.ui_flags` |
| `.env.example` | документирование двух флагов |
| `tools/ui_round1025_matrix.py` | HOTFIX8-пробы (`shellGlass`, `shellA`, `sidebarW`, `headerCardGap`, `auroraBlobs/auroraAnim`, `shellBg/Blur`), `_hotfix8_failures`, F2-чекер «фон живой» (static → FAIL) |
| `tests/js/round1025_hotfix8_shell_aurora_test.js` | **новый** JS-маркер (shell/aurora/флаги/matrix) |
| `tests/test_webapp_hotfix8_round1025.py` | **новый** Python-маркер + AA |
| `tests/test_webapp_js_unit.py` | регистрация нового JS-маркера |
| `tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js` | панели → `data-glass="shell"` (атомарно) |
| `tests/test_webapp_hotfix6_round1025.py` | панели → `data-glass="shell"` |
| `tests/test_webapp_ui_rework_round1020.py` | wash → aurora + legacy conic |
| `plans/reports/round1025_hotfix8_contrast.md` | AA-таблица §4 | 
| `plans/reports/round1025_hotfix8_ui_report.md` | отчёт матрицы 5 режимов |

## Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Syntax | `node --check web/app.js` + `telegram-init.js` | **OK** |
| JS-маркеры (hotfix6/7/8, F2-design-tokens, hotfix4, round1021) | `node tests/js/*.js` | **OK** (`HOTFIX8-SHELL-AURORA-OK`, `HOTFIX7-…-OK`, `HOTFIX6-…-OK`, `JS-UNIT-OK`) |
| Pytest (полный) | `py -3 -m pytest -q` | **8266 passed, 1 skipped, 5 failed**; 5 failed — **предexisting/средовые** (`test_outgoing_guard_round1022`, `test_summary_cover_round1023`, `rich`-ImportError), воспроизводятся на baseline без HOTFIX8-правок (проверено `git stash`) |
| Playwright-матрица 5 режимов/10 вьюпортов | `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` | **failures: 0** (40 скриншотов, `tools/_ui_round1025_raw.json`) |
| `git diff --check` | `git diff --check` | **whitespace errors: 0** |
| Δ DDL | нет изменений в `services/**`/схеме | **0** (SQLite v12) |
| Δ каталога | `test_webapp_hotfix8_round1025.py::test_catalog_invariants` | **0** (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418) |

## Живые пробы матрицы (из `tools/_ui_round1025_raw.json`)

- `shellA = False` (ни одна shell-панель не несёт `data-glass="a"` → цветной ореол снят); `shellGlass` = `shell` для sidebar/header/drawer/bottom-nav/more-sheet.
- `320x700`: header/bottomNav/moreSheet `background-color = rgba(24,28,38,0.78)`; `1280x800`: sidebar/header `rgba(24,28,38,0.72)`; карточки `rgba(21,27,42,0.5)` → слои разделены.
- `backdrop-filter = blur(18px) saturate(1.15)`; `headerCardGap = 16px` (normal и fullscreen); `sidebarW = 216px`; `auroraBlobs = 5`, `auroraAnim = aurora-blob-1` (не static).
- `failures: 0` по всем 10 вьюпортам (h-scroll/bottom-nav/vertical/safe-area/hit-area/scope/workspace/AA).

## Покрытые acceptance-сценарии (UPD2 §9)

1. shell — тёмно-серый glass-слой ≠ карточка — computed bg shell ≠ card (raw.json), AA-таблица. 2. subtle-стекло — §4 токены + blur 18/115. 3. фон живой — `auroraAnim` активен, 5 blob. 4. desktop/mobile/fullscreen стабильны — матрица 5 режимов, 0 fail. 5. нет яркого ореола — `shellA=False`, `shellLensPaint` без цветной radial. 6. mobile не перекрывает — `_vertical_failures`/h-scroll 0. 7. SaveBar/scroll — структурные инварианты round1020 sticky + matrix more-sheet (детали см. риски).

## Не подтверждено / риски

- **T-2754/T-2755 (modal/drawer/settings scroll, SaveBar на малой высоте/клавиатуре):** изменений не потребовалось; структурные инварианты (`.modal-body` единственный скроллер, `overscroll-behavior: contain`, `.sticky-spacer`, `scroll-padding-bottom`) покрыты `tests/test_webapp_ui_rework_round1020.py`/`test_save_state_machine_round1025.py` и матрицей (more-sheet vertical). Поведение на малой высоте/клавиатуре — **live-гейт T-2776**.
- **T-2776 (реальный Telegram WebView):** не воспроизводим headless (viewport/safeArea/нативные кнопки/FPS). Остаётся открытым live-гейтом владельца.
- **5 pytest-failed:** предexisting (среда без `rich`-media aiogram API), не HOTFIX8; baseline-репро зафиксировано.
- **Bump T-2786 (`2.58.10 → 2.58.11`):** не выполнялся (Block G, до deploy T-2787).
