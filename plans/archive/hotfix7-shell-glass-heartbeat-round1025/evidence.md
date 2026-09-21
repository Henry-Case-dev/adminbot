# HOTFIX7 — evidence (`hotfix7-shell-glass-heartbeat-round1025`)

> Сжатые доказательства @Builder (Step 4). Полные логи не дублируются; только
> файлы/команды/фактические исходы. `plans/current_task.md` не изменялся (R18).

## База / версия

- Baseline HEAD при старте: `5a5465c` (hotfix6), `APP_VERSION` **2.58.7**.
- Код `055525c`/docs `ba75751` — предыдущий пакет; изменения HOTFIX7 — в рабочем дереве (не закоммичено).
- `APP_VERSION` → **2.58.8** (`config/settings.py`), README-версия, cache-bust `?v=__APP_VERSION__` (index.html) — автообновление.

## Изменённые файлы (Scope)

**Реализация**
- `web/static/app.css` — токены `--shell-h` (цепочка 100vh→100dvh→min(dvh,stable)) и `--shell-*`/`--card-shadow`; два режима высоты normal/fullscreen + `.shell-layout-legacy`; shell-панели (sidebar/drawer/header/bottom-nav/more-sheet) на серо-графитовые токены + specular/texture/обводка/blur; карточки → `--card-shadow`, модалки → `--glass-shadow`; `--glass-shadow` α `.75→.55`; `body::before` α `.42→.30` (reduced-motion `.35→.26`); `@supports`-фолбэк shell → `--shell-bg-strong`; `.shell-glass-legacy`; `.hb-wrap` min-height.
- `web/index.html` — привязка классов `.app-shell`: `shell-layout-v2/legacy`, `shell-glass-v2/legacy`.
- `web/app.js` — computeds `shellGlassV2`/`shellLayoutV2`/`heartbeatPremium`; premium ECG sweep-wipe (`_hbEcg`, `_hbPalette`, `_hbDrawGrid`, `_hbDrawPremium`) + извлечённый canvas-legacy (`_hbDrawLegacy`, без `pulseX`); `_hbDraw` роутит по флагу + DPR-cap 2.
- `config/settings.py` — env-only `ClassVar`: `UI_SHELL_GLASS_V2`, `UI_HEARTBEAT_PREMIUM`, `UI_SHELL_LAYOUT_V2` (default ON, вне каталога); bump версии.
- `web/api/routes.py` — аддитивно 3 флага в `GET /api/me.ui_flags` (bool).
- `.env.example` — документация трёх флагов.

**Тесты / инструмент**
- `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` (новый), `tests/test_webapp_hotfix7_round1025.py` (новый).
- `tests/test_webapp_js_unit.py` — регистрация нового JS-теста.
- `tests/test_webapp_hotfix6_round1025.py`, `tests/test_webapp_design_tokens_round1025.py`, `tests/test_scope_selector_round1025.py` — маркер версии `2.58.7→2.58.8`.
- `tests/test_webapp_ui_rework_round1020.py` — wash-opacity маркер `.42→.30` (ADR-1025-13 D3.5).
- `tools/ui_round1025_matrix.py` — 5 режимов (`MODES`), `F7_PROBE_JS`, `_hotfix7_failures`, stub-шина событий + fullscreen через `Telegram.WebView.receiveEvent`.

**Отчёты**
- `plans/reports/round1025_hotfix7_contrast.md` (AA-таблица), `plans/reports/round1025_hotfix7_ui_report.md` (матрица).

## Прогоны (факт)

| Команда | Результат |
|---|---|
| `node --check web/app.js` / `telegram-init.js` | OK |
| `node tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` | `HOTFIX7-SHELL-GLASS-HEARTBEAT-OK` |
| Все `tests/js/*.js` | ALL PASSED (26 существующих + новый) |
| `.venv/Scripts/python.exe -m pytest -q` | **8206 passed, 0 failed** (1 warning — сторонний StarletteDeprecation) |
| `.venv/Scripts/python.exe tools/ui_round1025_matrix.py` | прогон 2: **failures: 0** (прогон 1: 1 флейк `net::ERR_CONNECTION_TIMED_OUT` внешнего ресурса, не воспроизвёлся) |
| `git diff --check` | чисто (только LF→CRLF warnings) |

## Инварианты

- **Δ DDL = 0:** `services/**`, миграции, БД — не изменялись.
- **Δ каталога = 0:** `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418` — подтверждено `tests/test_webapp_hotfix7_round1025.py`, флаги отсутствуют в `param_catalog.REGISTRY`.
- **CSP/zero-build:** без CDN/новых зависимостей/inline-скриптов; specular/texture — CSS-градиенты (data-URI/ассеты отсутствуют).
- **Запрет WebGL:** `getContext('webgl` отсутствует; Canvas 2D+rAF переиспользован.
- **`computeBottomOffset`=max (ADR-1025-12 D3), нативные кнопки/`--header-h`, fullscreen-sync ADR-1024-24** — не трогали; hotfix4/hotfix6 тесты зелёные.
- **IA F1, store §37–§42, `persistItems` F0** — не изменялись.

## Покрытые acceptance-сценарии

- UPD 1: единый `--shell-h`; normal/fullscreen без конкурирующих высот; heartbeat виден в normal+fullscreen (матрица, 10 вьюпортов).
- UPD 2: ECG-форма (P/Q/R/S/T), sweep-wipe без `pulseX`; цвет/интенсивность по состояниям; reduced-motion статичный кадр; OFF → canvas-legacy; семантика `_heartbeatTransition`/`heartbeatSample` не менялась.
- UPD 3–4: `--shell-*` ≠ `--glass-*` (computed), shell-панели отделены; виньетка убрана (opacity .30); AA-таблица PASS (в т.ч. worst-case specular).
- UPD 5: header без наезда, цельные shell-панели, mobile safe-area сохранена.
- UPD 6: Playwright 5 режимов — PASS.

## Round 2 — правки по ревью (F-2/F-3/F-4, 22.09.2026)

Исходное ревью: `review.md`, вердикт Changes requested. F-2 (Medium, блокер), F-3/F-4 (Low). F-1 (тег/бэкап) — зона @DevOps, не трогался.

**F-2 — реальный фолбэк `--shell-h`.** Было: цепочка `100vh; 100dvh; min(100dvh,…)` в одной `:root` — custom properties не валидируются при разборе, поэтому в WebView без `dvh`/`min()` `min-height: var(--shell-h)` становился invalid at computed-value time → initial `auto`, а не `100vh`. Стало (`web/static/app.css`): базовое `--shell-h: 100vh;` объявляется всегда, а апгрейд `min(100dvh, var(--tg-viewport-stable-height, 100dvh))` живёт **только внутри** `@supports (height: 100dvh) and (height: min(100dvh, 100dvh)) { :root { … } }`. Висячий `--shell-h: 100dvh;` удалён.

**F-3 — единый источник цвета HEALTHY.** Premium-трасса HEALTHY читала `--teal-500 #42D6C4`, а бейдж `.hb-healthy` — `--ok #3DD68C`. Приведено к **статус-токену** `--ok` (`app.js:_hbPalette`: fallback `#3DD68C`, token `--ok`), т.е. трасса, бейдж и legacy-рендер HEALTHY согласованы; WARNING/CRITICAL уже были `--warn`/`--err`.

**F-4 — свечение зависит от состояния.** Было `rgba(core,.55)` для всех. Стало: `glowAlpha` = `.45/.60/.85/0` (healthy/warning/critical/unknown), `glowScale` (множитель `shadowBlur`) = `×0.9/×1.1/×1.5/0`; вспышка R-пика масштабируется `pal.glowAlpha`. CRITICAL заметно сильнее, UNKNOWN без свечения.

**Изменённые файлы (Round 2):** `web/static/app.css` (`--shell-h` base + `@supports`), `web/app.js` (`_hbPalette`, `_hbDrawPremium`), `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js`, `tests/test_webapp_hotfix7_round1025.py`, `tools/ui_round1025_matrix.py` (`F7_PROBE_JS`/`f2ShellH` + проверки `_hotfix7_failures`), `spec.md` (D1.1/D2.2/§5/§7.3), `adr-1025-13-*.md` (D1/D2/Верификация), этот `evidence.md`, `plans/reports/round1025_hotfix7_ui_report.md`.

**Прогоны (Round 2, факт):**

| Команда | Результат |
|---|---|
| `node --check web/app.js` + `telegram-init.js` | OK |
| `node tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` | `HOTFIX7-SHELL-GLASS-HEARTBEAT-OK` |
| Все `tests/js/*.js` (27) | 27/27 PASS (`$LASTEXITCODE`) |
| `.venv/Scripts/python.exe -m pytest -q` | **8207 passed, 0 failed** (1 warning — сторонний Starlette) |
| `.venv/Scripts/python.exe tools/ui_round1025_matrix.py` | прогон 3: **failures: 0** (10 вьюпортов × normal/fullscreen) |
| `F-2` эмуляция (1280×800) | база `100vh` → `800px = innerH`; прежняя цепочка → `0px` (баг воспроизведён); `.app-shell` normal `800px`, fullscreen `0px` |
| `git diff --check` | чисто (LF→CRLF warnings) |

Инварианты Round 2 не затронуты: Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build, WebGL 0, `--teal-500` в `app.css`/design-tokens сохранён (`#42D6C4` по-прежнему присутствует в `app.js:6983`), семантика `_heartbeatTransition`/`heartbeatSample` не менялась.

## Не выполнено / открыто (честно)

- **T-2682 live-гейт** — реальный Telegram WebView (владелец): фактический fullscreen, FPS glow/specular, «премиальность». Автоматизации недоступно.
- Коммит/деплой/merge — не выполнялись (Step 4 @Builder).
- Первый прогон матрицы дал флейк внешнего ресурса (см. таблицу) — не связан с изменениями.
