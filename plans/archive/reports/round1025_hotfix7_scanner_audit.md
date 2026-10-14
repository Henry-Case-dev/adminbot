# round1025 / hotfix7 — @Scanner audit (Step 6, T-2687)

- **Пакет:** `hotfix7-shell-glass-heartbeat-round1025` (ADR-1025-13, T-2658…T-2694)
- **Аудитор:** @Scanner, 22.09.2026
- **База:** HEAD `5a5465c` (`pre-round1025-hotfix7`, совпадает с `origin/master`); **правки НЕ закоммичены** — аудит рабочего дерева.
- **Вход:** spec.md, tasks.md, ADR-1025-13, `evidence.md` (@Builder), `review.md` (итер.2 **Approved**), AA `round1025_hotfix7_contrast.md`, `round1025_hotfix7_ui_report.md`.
- **Режим:** focused diff-based. Код не правился; `ARCHITECTURE.md`/`backlog.md`/`MEMORY.md`/`metrics.md` не трогались.

## 1. Вердикт

> **К деплою — ДА.** Обязательных возвратов @Builder нет.
> **Critical 0 / High 0 / Medium 0 / Low 3 / Info 3.** Все Low — не блокеры, bounded follow-up. Live-гейт владельца T-2682 (реальный Telegram WebView + FPS) остаётся открытым.

## 2. Диапазон и изменённые файлы

Рабочее дерево относительно `5a5465c` (17 tracked + 10 untracked):

**Реализация:** `web/static/app.css`, `web/app.js`, `web/index.html`, `config/settings.py` (3 `ClassVar` + bump), `web/api/routes.py` (аддитивно 3 bool в `ui_flags`), `.env.example`, `README.md`.
**Тесты/инструмент:** `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` (+3), `tests/test_webapp_hotfix7_round1025.py` (+новый), `tests/test_webapp_js_unit.py` (регистрация), `tests/test_webapp_hotfix6_round1025.py`/`tests/test_webapp_design_tokens_round1025.py`/`tests/test_scope_selector_round1025.py` (пин версии), `tests/test_webapp_ui_rework_round1020.py` (wash `.42→.30`), `tools/ui_round1025_matrix.py` (5 режимов, `F7_PROBE_JS`, `_hotfix7_failures`).
**Отчёты:** `plans/reports/round1025_hotfix7_contrast.md`, `round1025_hotfix7_ui_report.md`, `round1025_tz_remaining_audit.md`, папка фичи `plans/features/hotfix7-shell-glass-heartbeat-round1025/`.
**Док-статус (не код, pre-existing worktree):** `plans/workflow_state.md`, `plans/MEMORY.md`, `plans/backlog.md`, `plans/features/module-catalog-quickpanel-store-round1025/tasks.md` — правки Step 0/1, не связаны с кодом hotfix7, не трогались.

## 3. Таблица severity

| Severity | Кол-во | ID |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 0 | — |
| Low | 3 | L-H7-1, L-H7-2, L-H7-3 |
| Info | 3 | I-H7-1, I-H7-2, I-H7-3 |

## 4. Находки

### L-H7-1 (Low, pre-existing, не блокер) — `@supports not (backdrop-filter)` фолбэк shell-панелей перекрыт каскадом

- **Где:** `web/static/app.css:1245-1250` (фолбэк `background-color: var(--shell-bg-strong)`) vs основные правила `.app-sidebar` `:1669`, `.app-drawer` `:1699`, `.bottom-nav` `:1730`, `.more-sheet` `:1785` (`background-color: var(--shell-bg)`).
- **Доказательство:** фолбэк и основные правила имеют одинаковую специфичность (0,1,0) и задают одно свойство; основные правила идут **позже** в файле → побеждают. Значит при отсутствии `backdrop-filter` реальный фон панелей = `--shell-bg` (α .62), а не заявленный `--shell-bg-strong` (α .90). Заявленный фолбэк остаётся «мёртвым» для 4 из 5 панелей (для `header.header-sticky` фолбэк идёт после основного правила → работает). В HEAD была та же картина с `background: var(--glass-bg)` (α .5) — **не регрессия**, hotfix7 лишь сменил токен.
- **Impact:** низкий. AA сохраняется и на фактическом α .62 (independent recompute: `--text-2` на `--shell-bg` поверх худшей фазы §10 = **6.46:1**). Расхождение — декларация vs поведение, не читаемость.
- **Remediation (bounded):** перенести `@supports`-блок ниже основных правил панелей или продублировать `background-color: var(--shell-bg-strong)` внутри правил `.app-sidebar`/`.app-drawer`/`.bottom-nav`/`.more-sheet`.
- **Статус:** open (Low, follow-up).

### L-H7-2 (Low, не блокер) — OFF-путь флагов не «байт-в-байт» прежний

- **Где:** `web/static/app.css:1270-1277` (`shell-glass-legacy header.header-sticky`); `web/app.js:6852` (DPR-cap в общем `_hbDraw`).
- **Доказательство:** (а) при `UI_SHELL_GLASS_V2=false` legacy-правило шапки меняет только `background-color`/`border-bottom-color`/тень, но наследует от основного правила `border-bottom: 1px solid var(--shell-border)` (`:794`); в `HEAD` у `header.header-sticky` не было ни рамки, ни `box-shadow` — legacy добавляет и рамку, и `--glass-shadow`. (б) при `UI_HEARTBEAT_PREMIUM=false` legacy-рендер остаётся, но общий `_hbDraw` теперь применяет `dpr>2 → 2` (`:6852`) — на 3×-устройствах прежняя картинка была чуть резче.
- **Impact:** косметический; функциональный откат (токены, высоты, рендер-режим) полностью сохранён, `UI_HEARTBEAT_CANVAS_ENABLED=false` → SVG по-прежнему.
- **Remediation:** в legacy-правиле шапки явно `border-bottom: 0; box-shadow: none;`; при желании — не капать DPR в legacy-ветке.
- **Статус:** open (Low, follow-up).

### L-H7-3 (Low, не блокер) — AA worst-case по комбинированному specular+texture на 0.06 ниже 4.5

- **Где:** `web/static/app.css:87-88` (`--shell-specular` старт α .10, `--shell-texture` α .020), `plans/reports/round1025_hotfix7_contrast.md` п. «Метод».
- **Доказательство (independent recompute):** худшая фаза §10 wash = `rgb(26.1,73.3,74.9)`; `--text-2 #AAB6C8`:
  - на `--shell-bg` α .62 → `rgb(30.4,50.8,56.4)` = **6.46:1** PASS;
  - + specular α .10 → `rgb(52.8,71.2,76.2)` = **4.73:1** PASS;
  - + specular .10 ∩ texture .020 (эффективно α .12) → `rgb(57.3,75.3,80.2)` = **4.44:1** — на 0.06 ниже порога 4.5.
  - Контроль: `--text-1 #F4F7FB` на `--shell-bg-strong` .90 = **15.26:1**, +specular = **11.29:1** PASS.
- **Impact:** практически нулевой: превышение даёт 1px-полоса faux-noise в верхнем левом углу (первая строка меню с отступом `.5rem`); отчёт честно помечает specular/texture как пессимистичную оценку с допуском ±.1.
- **Remediation (bounded):** либо зафиксировать допуск в AA-таблице, либо слегка ослабить `--shell-specular` (.10→.08) / `--shell-texture` (.020→.015), чтобы пессимистичный композит держал ≥4.5.
- **Статус:** open (Low, follow-up).

### Info

- **I-H7-1:** файловый бэкап `var/backups/hotfix7-round1025-20260922-052812/` — это снимок **рабочего дерева итерации 1**, не pre-hotfix7 baseline: SHA256 `web/static/app.css` в бэкапе `5826C6ED…` ≠ текущему рабочему `C07DE095…` (F-2 менял `--shell-h` после снятия) и ≠ `HEAD`. Подтверждает Low-оговорку @Reviewer к F-1. Hard-rollback надёжен через tag `pre-round1025-hotfix7` → `5a5465c` (запушен: `git ls-remote` = `5a5465ca…`).
- **I-H7-2:** `README.md:5` «Тестов: 5936» устарело (pre-existing `L10.25F2-4`); в этом пакете правилась только версия `2.58.7→2.58.8`.
- **I-H7-3:** `plans/workflow_state.md` показывает Step 4/5/6 как pending (док-статус ещё не обновлён оркестратором); на код/инварианты не влияет.

## 5. Инварианты (проверено)

| Инвариант | Результат | Доказательство |
|---|---|---|
| Δ DDL = 0 | PASS | `git status`/`git diff` по `services/`, `migrations/` — пусто |
| Δ каталога = 0 | PASS | `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418`; `UI_*` hotfix7 отсутствуют в `REGISTRY` |
| Флаги вне `param_catalog` | PASS | 3 `ClassVar` в `config/settings.py:715-732`, доставка `web/api/routes.py:395-397`, doc `.env.example` |
| Нет `backdrop-filter: url(` | PASS | grep по `web/**` = 0 |
| Нет WebGL | PASS | только `getContext('2d')` (`app.js:1816`, `:6860`) |
| CSP/zero-build | PASS | нет CDN/внешних URL/`data:image`/новых inline-скриптов; specular/texture — CSS-градиенты (`app.css:87-88`) |
| `APP_VERSION` 2.58.8 синхронен | PASS | `settings.py:1702`; `README.md:5`; `?v=__APP_VERSION__` (`index.html:21/24/3906/3909`); пины тестов; остатков `2.58.7` вне `plans/` нет |
| Маркер-тесты атомарны | PASS | новый JS-тест + новый pytest + регистрация в `test_webapp_js_unit.py` — в том же рабочем дереве, что код |
| R17 (секреты/сырые пути) | PASS | в диффах/отчётах только bool/токены/rgba/вьюпорты; секретов нет |
| R18 (теги/бэкапы/stash) | PASS | `pre-round1025-hotfix7`→`5a5465c` (запушен), `pre-round1025*` (12) целы, `.env.bak.round1025-hotfix7` есть, `stash@{0}` на месте |
| `.env`/zip/скриншоты в индекс | PASS | untracked — только план/отчёты/тесты; `.env` и `current_task.md` gitignored |

## 6. Совместимость (не сломано)

- **IA F1 / порядок навигации hotfix4:** `bottomNavItems`/`sidebarGroups` не в диффе; `tests/test_hotfix4_cover_nav_shell_round1025.py` 28 passed.
- **write-path F0 `persistItems` / store-контракт F4 §37–§42:** вне диффа; полный pytest зелёный.
- **fullscreen-sync ADR-1024-24:** `initFullscreen`/`setFullscreenFromTma`/`toggleFullscreen` не менялись; матрица форсирует `fullscreen_changed` через ту же шину событий.
- **deny-list tier C / линза:** `[data-glass="c"]`, `[data-glass="a"]::before`, `UI_LENS_MAX_NODES`, `UI_GLASS_TIER_OVERRIDE` не тронуты.
- **Палитра §8 / фон §10:** значения `--surface-*`/`--text-*`/`--teal-*`/`--warn`/`--err`/`--grad-*` не менялись; изменены только `body::before` opacity `.42→.30` (reduced-motion `.35→.26`) и `--glass-shadow` α `.75→.55` — механика/цвета/длительности §10 сохранены.

## 7. Качество и OFF-пути

- **`--shell-h` (A):** базовый `--shell-h: 100vh` объявлен всегда (`app.css:75`); апгрейд `min(100dvh, var(--tg-viewport-stable-height,100dvh))` — строго внутри `@supports (height:100dvh) and (height:min(100dvh,100dvh))` (`:99-103`); висячего `--shell-h:100dvh` нет. Фолбэк **корректен** (custom properties не валидируются при разборе — обоснование верное). Матрица `f2ShellH`: base → `innerH`, эмуляция старого WebView → 0.
- **Два режима:** normal `min-height/height:auto/overflow:visible`; fullscreen `height=max-height=var(--shell-h); min-height:0; overflow:hidden` — конкурирующих высот нет; legacy-класс возвращает прежнюю геометрию (кроме L-H7-2).
- **heartbeat (B):** ECG P/Q/R/S/T (сумма гауссан), sweep-wipe без `pulseX`; цвет — из `--ok/--warn/--err/--text-3` (единство с бейджем, F-3); glow-лестница `.45/.60/.85/0`, `glowScale ×0.9/1.1/1.5/0` (F-4); reduced-motion — статичный кадр без луча/вспышки; `shadowBlur` ограничен, DPR-cap 2; сетка бледная. Семантика `_heartbeatTransition`/`heartbeatSample`/EMA/гистерезис/dwell/UNKNOWN **не менялась**; «без BPM» сохранено.
- **glass-shell (C/D):** computed `--shell-bg rgba(33,37,45,.62) ≠ --glass-bg rgba(21,27,42,.5)`; панели ≠ карточки; виньетка убрана (opacity .30 ≤ .32); 6 составляющих рецепта (base/blur/2×inset/обводка/specular/texture) — CSS-only.
- **OFF-пути:** `UI_SHELL_LAYOUT_V2=false` — faithful; `UI_SHELL_GLASS_V2=false` — функционально faithful (см. L-H7-2); `UI_HEARTBEAT_PREMIUM=false` — canvas-legacy; `UI_HEARTBEAT_CANVAS_ENABLED=false` → SVG.
- **XSS/injection:** новых `innerHTML`/`v-html` нет; рендер — canvas + `getComputedStyle`; классы `shell-*` — статические строки.
- **Утечки rAF/observer:** новых циклов/обсерверов нет; lifecycle heartbeat не менялся.

## 8. Прогоны (факт, independent)

| Проверка | Команда | Результат |
|---|---|---|
| JS-синтаксис | `node --check web/app.js` / `telegram-init.js` | OK |
| Новый JS-регресс | `node tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` | `HOTFIX7-SHELL-GLASS-HEARTBEAT-OK` |
| Все JS-тесты | `tests/js/*.js` | все PASS |
| Полный pytest | `python -m pytest -q` | **8207 passed, 1 warning** (сторонний Starlette) |
| Точечный pytest | 6 файлов (hotfix7/js_unit/hotfix6/design_tokens/scope_selector/ui_rework) | **156 passed** |
| hotfix4-навигация | `test_hotfix4_cover_nav_shell_round1025.py` | **28 passed** |
| Каталог/DDL | import `param_catalog`/`Settings`; `git status services migrations` | 459/98/96/21/418; пусто |
| Гигиена | `git diff --check` | exit 0 (только LF→CRLF warnings) |
| AA | independent recompute | 6.46 / 4.73 / 15.26 / 11.29 — совпало |

**Playwright-матрица** (5 режимов × 10 вьюпортов × normal/fullscreen) в среде @Scanner не перезапускалась; опора на прогон @Builder (`failures: 0`, `round1025_hotfix7_ui_report.md`) — Info, не блокер (прецедент §57/§58).

## 9. Handoff

`RESULT: SCANNED — hotfix7-shell-glass-heartbeat-round1025 (T-2687). @Orchestrator — Critical 0 / High 0 / Medium 0 / Low 3 / Info 3; к деплою ДА, обязательных возвратов @Builder нет. Проверено независимо: `node --check` OK, JS hotfix7 + полный набор OK, pytest 8207/0, целевые 156 + nav 28 passed, Δ DDL=0, Δ каталога=0 (459/98/96/21/418), `backdrop-filter:url(`=0, WebGL=0, CSP/zero-build чист, APP_VERSION 2.58.8 синхронен (`?v=`/README/пины), тег `pre-round1025-hotfix7`→`5a5465c` запушен, бэкапы/`stash@{0}` целы, `.env`/zip/скриншотов в индексе нет, `git diff --check`=0. Low: L-H7-1 (мёртвый @supports-фолбэк shell из-за порядка каскада, pre-existing, AA-безопасно 6.46:1), L-H7-2 (OFF-путь: рамка+тень header, DPR-cap в legacy), L-H7-3 (specular+texture worst-case 4.44:1). Live-гейт T-2682 (реальный Telegram WebView + FPS) — открыт за владельцем.`
