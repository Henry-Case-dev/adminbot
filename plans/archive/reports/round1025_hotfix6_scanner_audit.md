# Round 10.25 hotfix6 — Scanner-аудит `hotfix6-webview-shell-heartbeat-round1025` (Шаг 6, 22.09.2026)

- **База:** HEAD `441e8f7` (правки НЕ закоммичены — аудит рабочего дерева, `git status`/`git diff` + untracked).
- **Области пакета:** A — foreground-линза `[data-glass="a"]::before` + `filter:url(#lg-lens)` (SVG edge-weighted radial-mask, `backdrop-filter:url()` удалён, UA-gate снят, перф-кап `UI_LENS_MAX_NODES=6`, стекло на sidebar/drawer/header/bottom-nav/more-sheet); B — `computeBottomOffset()=max(innerHeight−stableHeight, contentSafeAreaInset.bottom, safeAreaInset.bottom)`; C — Canvas 2D+rAF heartbeat §15 (HEALTHY/WARNING/CRITICAL/UNKNOWN, гистерезис+EMA+dwell, `missing≠bad`, телеметрия из `/api/status`, legacy-OFF `heartbeatLegacy`); D — двухстрочная шапка + ⛶ + резерв `--header-h`. Флаги env-only. `APP_VERSION` 2.58.7.
- **Инструментарий:** `git status -s`, `git diff`, `git diff --check`, `node --check`, JS-юнит-прогон, целевой pytest, `rg`-инварианты.
- **@Reviewer:** Approved (12/12 замечаний закрыто). Данный отчёт — независимая проверка на Critical/High + обновление отчётности.

## Вердикт

**К деплою — ДА.** Новых **Critical/High нет** (0/0). Остаются 1 Medium (перф-риск линзы на реальном устройстве, не блокер) и 3 Low/3 Info.

| Severity | Кол-во | Гейт |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 1 | не блокирует деплой |
| Low | 3 | не блокирует |
| Info | 3 | — |

## Находки

### Medium

- **[M-H6-1] Перф-цена foreground SVG-линзы на реальных WebKit/iOS не измерена.**
  `web/static/app.css:1064-1082` (`[data-glass="a"]::before` c `feTurbulence`+`feDisplacementMap` через `filter:var(--glass-displace)`); `web/app.js:8449-8456` (`_liquidGlassSupported` → `CSS.supports('filter','url(#lg-lens)')`, UA-gate снят).
  Теперь tier A получают и WebView-клиенты (iOS/WebKit), а не только Blink. Каждый A-узел вешает SVG-фильтр `feTurbulence`+`feDisplacementMap` поверх анимированного градиента фона §10. Кап `UI_LENS_MAX_NODES=6` (`app.js:8465`, `config/settings.py:711`) ограничивает число узлов, но абсолютная цена на кадр на слабом устройстве не измерена. Это преемник прежнего `M10.25F2-3` (перф-цена не измерена) — риск **не блокирующий**, но подтверждается живым гейтом владельца (матрица/`docs`, как заявлено в `round1025_hotfix6_contrast.md`).
  *Рекомендация:* замер FPS на низком Android + iOS в рамках T-2617; при деградации — снизить `UI_LENS_MAX_NODES` (env-only, без редеплоя).

### Low

- **[L-H6-1] Canvas-heartbeat: `role="img"` — интерактивному элементу.**
  `web/index.html:2793-2801` — `<canvas class="hb-canvas" role="img" tabindex="0" aria-describedby="hb-tip" @click/@keydown>`. Элемент фокусируем и кликабелен, но роль объявлена как изображение (скринридер не анонсирует как кнопку). Плюс `aria-describedby="hb-tip"` ссылается на `#hb-tip`, который существует в DOM только при `hbTipOpen` (`index.html:2803`) → при закрытом тултипе ссылка «висячая». Функционально не ломает, доступность частично снижена.
  *Рекомендация:* `role="button"` (или `aria-haspopup`) + держать `#hb-tip` в DOM с `v-show`/`hidden` вместо `v-if`.

- **[L-H6-2] Линза на скролл-контейнерах прокручивается вместе с контентом.**
  `web/static/app.css:1064-1066` — псевдо-линза `position:absolute; inset:0` на `.app-sidebar`/`.app-drawer`, у которых `overflow-y:auto`. Абсолютный потомок скролл-контейнера позиционируется по padding-box, но **скроллится** вместе с содержимым ⇒ при длинном меню нижняя часть панели останется без edge-линзы. Чисто декоративный эффект (`pointer-events:none`, `opacity .14`), контент/контраст не затронуты.
  *Рекомендация:* `background-attachment`-приём не поможет для псевдо-элемента; при желании — вынести линзу в отдельный fixed-слой панели.

- **[L-H6-3] Комментарий о stale-пороге расходится с кодом.**
  `web/app.js:6534-6535` — комментарий «старше 2× интервала поллинга (30 с)», фактический порог в коде `> 120000` мс (= 120 с, т.е. 4× интервала). Формула безопасна (консервативнее), но текст вводит в заблуждение при сопровождении.
  *Рекомендация:* поправить комментарий (или вынести порог в константу).

### Info

- **[I-H6-1]** `heartbeatCanvasEnabled` (`app.js:1806-1813`) при каждом вычислении создаёт одноразовый `<canvas>` и зовёт `getContext('2d')` для feature-detect. Vue-2 кэширует computed, так что дёшево; отмечено для чистоты.
- **[I-H6-2]** UI-матрица (`tools/ui_round1025_matrix.py`) не воспроизведена — в окружении нет playwright (как и в прошлых раундах). Аналитическая AA-таблица `round1025_hotfix6_contrast.md` корректна и покрыта Python-проверкой матрицы, но live-гейт за владельцем.
- **[I-H6-3]** `README.md:5` «Тестов: 5936» устарело (факт больше) — предсуществующий `L10.25F2-4`, не относится к коду пакета.

## Что проверено чисто (доказательства)

### 1. Critical/High — не появились

- **CSP / zero-build:** в `web/index.html` ровно один inline SVG-фильтр `id="lg-lens"` (`index.html:37`), без `feImage`/data-URI/внешних ссылок; `rg -i 'webgl|three\.js|https?://'` в `web/index.html`/`web/app.js` — только упоминание «WebGL запрещён» в комментарии. Новых зависимостей нет (`package.json`/локи не в диффе).
- **`backdrop-filter:url(` нигде в `web/**`:** `rg` по `web/` → 0 совпадений (в т.ч. vendor исключён по смыслу — там нет). Подтверждается JS-тестом (`HOTFIX6-LENS-HEARTBEAT-SHELL-OK`) и Python-инвариантом.
- **XSS/injection:** в новых computed/render нет `innerHTML`/`v-html`; `{{ heartbeat.* }}` и `{{ heartbeatTip.* }}` экранируются; `data-glass-tier`/`data-glass-reason` заполняются только из фиксированного множества строк (`app.js:8481-8520`), `_glassTierOverride` санитизирует в `a|b|c|auto` (`app.js:8458-8463`), `_lensMaxNodes` — `parseInt` (`app.js:8465-8469`). Существующие `v-html` (`guideHtml`, `sanitizedGuidePreviewHtml`) — не из пакета и всегда через санитайз.
- **Утечки rAF/observer:** единственный rAF-цикл (`app.js:6589-6633`) останавливается по `document.hidden` (`app.js:8598`), по уходу с вкладки (`watch activeTab` → `stopHeartbeatCanvas`, `app.js:2125`), и в `beforeUnmount` (`app.js:8832`). `ResizeObserver` шапки снимается в `beforeUnmount` (`app.js:8835`), `_lgObserver`/`_lgResizeObserver` — как и прежде (`app.js:8824-8829`).
- **R17 (секреты/пути):** `glassTierDiag` (`{supported, override, maxNodes, active, reducedMotion}`) — только bool/строки-флаги/числа; атрибуты `data-glass-*` — статические строки. Новых логов с сырыми путями/токенами нет (диффы `app.js`/`telegram-init.js` логов не добавляют).
- **R18 (бэкапы/теги/stash):** `git stash list` → `stash@{0}` цел; теги `pre-round1025-*` на месте; файлов-бэкапов в статусе нет.
- **Доступность/фокус:** ⛶ — нативная `<button type="button">` с `:aria-pressed` (`index.html:131-135`) и тач-целью ≥44×44 в compact (`app.css:787-791`); canvas фокусируем с `@keydown.enter`/`@keydown.esc` (см. L-H6-1 по роли).

### 2. Инварианты

- **Δ DDL = 0:** `services/pg_db.py`, `services/database.py`, миграции — не в диффе (`git status -s | rg -i 'pg_db|database.py|alembic|migration'` → пусто).
- **Δ каталога = 0:** `services/param_catalog.py` не в диффе; новые ручки — `ClassVar`-флаги env-only (`config/settings.py:695-712`), отдаются аддитивно в `/api/me.ui_flags` (`web/api/routes.py:383-392`).
- **`backdrop-filter:url(` в `web/**`** — отсутствует.
- **Атомарность маркер-тестов F2/F3/hotfix4:** изменения в тестах — не ослабление, а перевод на новую семантику + усиление: `tests/js/round1025_design_tokens_test.js` (feature-detect вместо UA-gate, tier/кап-проверки вместо min-240), `tests/js/round1025_hotfix4_shell_test.js` (+max(A,B,C)-кейсы), `tests/test_webapp_design_tokens_round1025.py`, `tests/test_scope_selector_round1025.py`, `tests/test_hotfix4_cover_nav_shell_round1025.py` (поиск реального `.more-sheet{` вместо подстроки и т.п.). Прогон: целевые **119 passed**.
- **`APP_VERSION` 2.58.7 синхронен:** `config/settings.py:1685`; `README.md:5` v2.58.7; тесты-пины `2.58.7` (`tests/test_scope_selector_round1025.py:180`, `tests/test_webapp_design_tokens_round1025.py:179`, `tests/test_webapp_hotfix6_round1025.py:232`); версионирование `?v=` через `web/app.py::_VERSION_TAG` заменяет плейсхолдер `__APP_VERSION__` во всех 4 ассетах + `@font-face`.

### 3. Совместимость

- **F0 save-path, F1 IA/shell/порядок навигации, F2 палитра §8/фон §10/контраст, F3 селектор/guard/RBAC, hotfix3/4/5:** backend-модули этих областей — вне диффа (кроме аддитивного блока флагов в `routes.py`); JS/pytest-гейты зелёные.
- **Контраст:** `plans/reports/round1025_hotfix6_contrast.md` — все панельные классы текста ≥4.5:1 на худшей фазе фона §10; палитра §8 не менялась.
- **Каскад CSS (проверено):** `[data-glass="a"]` (специфичность 0,1,0) задаёт `position:relative`, но панели сохраняют `position:fixed` — их правила идут ПОЗЖЕ по источнику (`app.css:1564/1590/1610/1660` против `:1053`), шапка — `position:sticky` за счёт большей специфичности `header.header-sticky` (0,1,1) (`app.css:748`). Ломания раскладки нет.
- **C2-OFF откат:** `heartbeatLegacy` (`app.js:1746`) воспроизводит прежнюю семантику (пороги 0.5/0.8, метки «спокойный/повышен/пик N%», период), `heartbeat` при `heartbeatCanvasEnabled===false` возвращает его байт-в-байт; SVG-разметка сохранена под `v-else`. Проверено юнит-тестом.
- **`computeBottomOffset`:** `csa`/`sa` объявлены внутри `applyInsets()` (`telegram-init.js:52,59`) до использования (`:72-76`); guard `stableH>0` сохранён; чистые функции экспонированы (`__computeTgBottomOffset`).

### 4. Гигиена

- В диффе нет `.env`/`current_task.md`/`.zip`/скриншотов (untracked — только ожидаемые: feature-dir, contrast-отчёт, 2 новых теста).
- `git diff --check` → **exit 0** (только информационные CRLF-предупреждения git, не whitespace-ошибки).
- `node --check web/app.js` и `web/static/telegram-init.js` → OK.
- Идемпотентность/транзитивность tier A: `reconcileLiquidGlass` итерирует `[data-glass="a"]` в детерминированном DOM-порядке, снимает/ставит `data-glass-downgraded` и `data-glass-tier`; opt-in `data-glass` **не переписывается** (b→a обратимо); новые узлы подхватываются `MutationObserver` (`app.js:8542-8559`), resize — `ResizeObserver`.

## Валидатор (по факту)

- `node --check web/app.js` → OK; `node --check web/static/telegram-init.js` → OK.
- JS: `round1025_hotfix6_lens_heartbeat_shell_test.js` → `HOTFIX6-LENS-HEARTBEAT-SHELL-OK`; `round1025_hotfix4_shell_test.js` → `JS-UNIT-OK`; `round1025_design_tokens_test.js` → `JS-UNIT-OK`.
- pytest (целевые): `tests/test_webapp_hotfix6_round1025.py` + `tests/test_scope_selector_round1025.py` + `tests/test_webapp_design_tokens_round1025.py` + `tests/test_hotfix4_cover_nav_shell_round1025.py` → **119 passed** (2.88 s).
- Полный pytest/матрица не перепрогонялись в этом окружении (нет playwright); опора на зелёные JS + целевые pytest + аналитическую контраст-таблицу.

## Итог

**Critical 0 / High 0 / Medium 1 / Low 3 / Info 3 → деплой разрешён.** Блокеров нет; Medium (перф линзы на устройстве) закрывается env-ручкой `UI_LENS_MAX_NODES` без редеплоя и подтверждается живым гейтом.

*Отчёт сгенерирован @Scanner 22.09.2026, Шаг 6.*
