# Задачи: admin-ui-bugfixes-round107 (Раунд 10.7)

> **✅ СТАТУС: ЗАВЕРШЕНО И ЗААРХИВИРОВАНО (11.09.2026, @PM Step 8 Archive Phase).**
> Фича перенесена из `plans/features/admin-ui-bugfixes-round107/` в
> **`plans/archive/admin-ui-bugfixes-round107/`** (плоский kebab-case, как существующие архивы).
> Итог: полный pytest — **5042 passed / 0 failed**; @Reviewer — **APPROVED WITH MINOR ISSUES**
> (doc-nit исправлен); @Scanner — **0 blocker / 0 major** (1 minor R10.7-1 — задокументированный
> spec-trade-off; 3 info R10.7-2…R10.7-4; R10.7-5 — точность формулировки, не код)
> (`plans/reports/round10.7_scanner_audit.md`); @Architect — архитектура влита в
> `plans/ARCHITECTURE.md` (**§28** + связанные §9/§25). Каталог-инвариант: **REGISTRY 392 /
> GROUPS 91 / Settings 364** (mapped 89). Артефакты сохранены: `spec.md`, `tasks.md`.
> Ниже — исторический документ планирования.
> **ВНИМАНИЕ:** пост-архивная фаза @DevOps (commit/push/деплой/live-smoke 1b/1c/1d/2a/3b)
> выполняется ПОСЛЕ архива; статусы `[ ]` в секции @DevOps отражают состояние на момент архивации.

> **FEATURE:** `plans/archive/admin-ui-bugfixes-round107/` (kebab-case, изолированная папка).
> **РАУНД:** **10.7** (follow-up после 10.6 `tma-ia-modules-rework`, задеплоен 11.09.2026,
> архив `plans/archive/tma-ia-modules-rework/`).
> **НУМЕРАЦИЯ ЗАДАЧ:** **T-1224…T-1242** (продолжает T-1223 — Scanner-миноры 10.6).
> **Статус (исторический):** ✅ реализация @Builder завершена (T-1225…T-1233 + R106-5);
> ✅ QA-прогон @DevOps выполнен (T-1236): полный pytest **5042 passed / 0 failed**;
> ✅ @Reviewer — **APPROVED WITH MINOR ISSUES** (doc-nit закрыт); ✅ @Scanner — **0 blocker / 0 major**.
> T-1234 (опц. P2) и T-1235 (README) не выполнялись. Финальная сводка — в статус-хедере выше.
> **Ревью @Reviewer (10.7):** DEF-1 (снят `visibility:hidden` у `.clipboard-ghost` —
> фокусируемость/execCommand-fallback), DEF-2 (`execCommand` boolean → честный тост),
> DEF-3 (selector-scoped маркеры) — ✅ исправлены и перепроверены.
> **@PM не пишет код** — только декомпозиция, AC, QA-план и рекогносцировка.

---

## 0. Контекст и вход

- **Преемник:** 10.6 `tma-ia-modules-rework` (единый navbar, 11 модулей, Настройки AI (7),
  PERMsoc, блоки провайдеров). Статус: ✅ задеплоен; commit `6f91e8b`, push `be7b85b..6f91e8b`,
  docs-синхронизация `2ccf558`; прод `pull` fast-forward, restart active, `/api/health` 200.
- **Текущее дерево:** `git status -s` пусто (HEAD `2ccf558`), рекогносцировка ведётся по задеплоенному коду.
- **Baseline (10.6):** pytest **5027 passed / 0 failed**; `node --check web/app.js` — clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` — clean.
- **Инварианты, которые НЕ должны поехать:** REGISTRY 392 / GROUPS 91 / Settings 364 (mapped 89),
  ноль новых PG-DDL, SQLite v8, порядок роутеров `bot.py`, каноны промптов, R16/R17.
- **Характер раунда:** UI/UX bugfix-раунд, бэкенд-логику не трогаем, кроме узкого ремонта
  источника данных графика (2b) в `services/` (при подтверждении root-cause @Architect).

**Затрагиваемые файлы (предварительно):** `web/index.html`, `web/app.js`,
`services/status_service.py`, `services/uptime_heartbeat.py` (только 2b), тесты под `tests/`.

---

## 1. Учёт аудита @Scanner (ОБЯЗАТЕЛЬНО — проверено перед планированием)

Прочитаны свежие отчёты: `plans/reports/round10.6_scanner_audit.md` (11.09.2026, новейший),
`plans/reports/round10.5_scanner_audit.md`, `plans/reports/full_audit_results.md`,
`plans/reports/audit_backlog.md`.

**Вердикт 10.6:** 0 blocker / 0 major; 3 minor (R10.6-1…-3), 3 info (R10.6-4…-6).
Ремедиации 10.5 (R10.5-1 BackButton re-init, R10.5-2 DM `models.*` read-only) — ✅ закрыты.

**Что включаем в план 10.7:**

| Находка | Severity | Решение по 10.7 |
|---|---|---|
| **R10.6-1** — LLM Провайдеры: 21 параметр дублируется (prov-блоки + generic-группы), `web/index.html:701-1053`, `web/app.js:856-859`, `:2517-2563` | minor, **UI** | **ВКЛЮЧАЕМ опционально (P2) → T-1236** (v-if подавление generic-рендера на `activeTab==='llm_providers'`; 16 «generic-only» параметров сохранить). |
| **R10.6-2** — SSRF-периметр `https` в `POST /api/llm/test` (`services/llm_probe.py:58-80`) | minor, backend/security | **ВНЕ UI-скоупа** → кандидат 10.8 (бэкенд-хардненинг). |
| **R10.6-3** — 422-эхо `api_key` в теле (`web/api/routes.py:126-132`, `:1225`) | minor, security/R17 | **ВНЕ UI-скоупа** → кандидат 10.8 (remediation-хендлер). |
| **R10.6-5** — мёртвые записи `ICONS` после удаления вкладок (`web/app.js:228-233`) | info | Низкий приоритет; при касании `ICONS` (1d/навбар) — почистить **осторожно, сверив с `test_font_subset`**. |
| **R10.6-4/-6** | info | Не трогаем (границы/косметика). |
| **R10.4-4…-6** (из ARCHITECTURE §25) | открыты | Вне UI-скоупа, кандидаты следующих раундов. |

> **Примечание @PM:** R10.6-1 и R10.6-5 не конфликтуют с 1a-1d/2a-2b/3a-3c (разные области шаблона),
> но правки `index.html`/`app.js` идут одним документом — поэтому T-1236 ставится в общий QA-прогон.

---

## 2. Запрос владельца (captured EXACTLY, дословно)

**1. Header (top panel) & navigation:**
- a. Render bug: a select shows `function () { [native code] }` — fix the Vue template binding/context loss.
- b. Safe area: right-side elements are overlapped by Telegram native buttons — add padding-right to prevent overlap.
- c. Compact the user block (avatar + name + role badge + fullscreen button): reduce sizes/spacings, do NOT remove elements.
- d. Menu tabs: labels under icons wrap incorrectly (e.g. "Настрой ки AI", "Как это работае т") — reduce font size (text-xs or smaller) and spacing so labels fit one line.

**2. Statistics screen:**
- a. Keys table: long model names (e.g. `whisper-large-v3`) break the container width — apply text-overflow ellipsis or word-break.
- b. Chart: renders as a flat line — fix historical data rendering.

**3. Logs screen:**
- a. Filters layout: find & remove the invisible div/input left of the "INFO" select breaking the grid.
- b. Table columns: fixed width for log-level (ERROR/INFO) and date; last text column `flex:1` + correct text wrapping.
- c. UX: add copy-to-clipboard on log-row click with visual feedback.

**Plus:** README (ironic tone), Russian commit, push, deploy, plain-language report.

---

## 3. Рекогносцировка: карта кода (file:line)

> Рекогносцировка @PM 11.09.2026 по HEAD `2ccf558` (дерево чистое). Это опорные точки для
> @Architect (spec.md) и @Builder; **не** готовые решения.

### 1a. Select показывает `function () { [native code] }`

- **Заголовок/навбар** — `web/index.html:558-655`; в шапке буквального `<select>` НЕТ.
  Единственный select-подобный контрол — кастомный scope-dropdown «Выбор контекста»:
  `web/index.html:576-618` (trigger `576-595`, панель `596-617`),
  computed `scopeTriggerTitle` — `web/app.js:1360`, `scopeLabel` — `:1322`,
  `scopeOptions` — `:1327-1358`, `scopeTriggerInitial` — `:1363`.
- **Все `<select>` в приложении:** `web/index.html:942`, `:1033`, `:1237`
  (widget `select` ← `item.select_options`, источник `web/api/routes.py:308-339`
  и preset `services/param_catalog.py:1464-1475`), `:1445` (oversightSort),
  `:1559` (newAdminRole ← `rolesList`, `web/app.js:2733`; API `web/api/routes.py:773-788`),
  `:1724`, `:1875` (`stageRu`), `:2501` (logLevel).
- **Найденный Vue-антипаттерн «потеря контекста» (подтверждён статически):**
  `web/app.js:3329` — `this.logs.map(this.logText)` (метод передан как callback без `bind(this)`).
  Функция `logText` сейчас не использует `this`, поэтому дефект латентный, но это ровно
  класс «context loss», который просит владелец. **Обязательный sweep** по `.map(this.)`
  / `.filter(this.)` / `.forEach(this.)` — в коде ровно 1 вхождение (это).
- **Требование к @Architect/Buider:** воспроизвести баг на живом TMA (DevTools/эмулятор),
  зафиксировать, **какой именно** `<select>`/контрол печатает native-code, и устранить
  корень (привязка значения/лейбла как функция, а не вызов). Все точки выше —候选 для проверки.

### 1b. Safe area (правые элементы перекрыты нативными кнопками Telegram)

- Header: `web/index.html:558-559`; CSS sticky-шапки `web/index.html:515-522`;
  медиа-правки `:546-550` (`env(safe-area-inset-top)`), `:537-542`
  (`env(safe-area-inset-bottom)`).
- Правый блок (`.ml-auto`): `web/index.html:627-642`. `env(safe-area-inset-right)` сейчас НЕ используется.
- **Цель:** добавить горизонтальный safe-area запас справа, чтобы `⛶`/аватар/бейдж не уходили под
  нативные кнопки WebView; не ломать sticky и fullscreen-скролл (`.app-shell`, `:527-542`).

### 1c. Компактный user block (avatar + name + role badge + fullscreen)

- `web/index.html:627-642`: `<img>` (w-8 h-8), имя (`:634`), `role_name` badge (`:635`), `⛶` (`:639-641`).
- **Цель:** уменьшить размеры/отступы, **не удаляя** элементы; сохранить `@error="onMeAvatarError()"`
  и `aria`/title для доступности.

### 1d. Подписи меню под иконками (перенос по слогам)

- Разметка nav: `web/index.html:646-654` (`.nav-link` → `.nav-icon` + `.nav-label`).
- CSS: `.nav-link` `web/index.html:205-211` (`white-space: normal`),
  `.nav-label` `:213-216` (`font-size: var(--tx-tiny)` = 0.75rem, `overflow-wrap: anywhere`),
  адаптив `:290-298` (`.nav-link { padding: .35rem .15rem; }`).
- Токены типографики: `web/index.html:44` (`--tx-small:.875rem; --tx-tiny:.75rem`).
- Данные подписей: `NAV_ITEMS` — `web/app.js:252-261` («Как это работает», «Настройки AI»,
  «Функции PERMsoc», «Доступы и Роли»).
- **Цель:** подписи в ОДНУ строку, без разрыва внутри слова; уменьшить кегль/трекинг/паддинги,
  сохранить читаемость и active-состояние.

### 2a. Таблица ключей: длинные имена моделей ломают ширину

- Таблица «🔑 Доступность ключей API»: `web/index.html:2459-2495`; строка модели —
  `:2479` (`<td class="mono">{{ p.model || '—' }}</td>`).
- CSS: `.avail-list` `web/index.html:344-354`; ключевое —
  `:349-352` (`td { white-space: nowrap }`) и `:353-354`
  (`td.mono { overflow:hidden; text-overflow:ellipsis }` **без `max-width`/`table-layout:fixed`**).
- Вторая `.avail-list` (матрица ролей) — `web/index.html:1648-1682` (не ломать).
- **Цель:** ellipsis/`max-width`/`table-layout` или `word-break` для 2-й/3-й колонок; проверить,
  что колонка `Модуль` и коды (`ERROR/INFO` нет — здесь `модуль/провайдер/модель/код/статус`)
  не разъезжаются; мобильный адаптив `:294-298`.

### 2b. График — плоская линия (исторические данные)

- Фронт: `renderUptimeChart` — `web/app.js:3130-3166` (маппинг `b.status==='down' ? 0 : 1`, `:3140`);
  `renderKeyHistoryChart` — `web/app.js:3195-3251`; загрузка — `loadStatus` `:3090-3091`,
  `loadKeyHistory` `:3170-3177`.
- Разметка: аптайм-canvas `web/index.html:2448-2454` (ref `uptimeCanvas`);
  key-history-canvas `:2491-2493` (ref `keyHistoryCanvas`).
- Бэкенд uptime: `services/status_service.py:260-281` (`_bucketize`: **одна** запись на 5-мин слот,
  последняя побеждает), `:320-336` (fallback из 2 «down»-бакетов);
  `services/uptime_heartbeat.py:26` — **`INSERT … VALUES ('up')`**; писателя `'down'` в коде НЕТ.
- **Гипотеза root-cause (подтвердить @Architect):** все бакеты `'up'` → график аптайма всегда
  плоский на верхнем уровне; фронт не вычисляет «дырки» heartbeat как downtime.
  Альтернатива — плоский key-history при однородных `ok`/малом числе сэмплов
  (`services/key_history.py:126-149`, `record` раз в 5 мин при `build_snapshot`).
- **Цель:** починить отображение истории (по пропущенным слотам/или иным согласованным способом);
  не менять контракт `allowlist`/leak-safety (`services/key_history.py:38-42`, OD19).

### 3a. Логи: невидимый div/input слева от select «INFO»

- Блок логов: `web/index.html:2497-2537`; фильтр-строка `:2499-2507`
  (заголовок `:2500`, `<select v-model="logLevel">` `:2501-2503`).
  В HEAD буквального скрытого `<input>`/`<div>` перед select НЕТ (проверено скриптом по всему файлу).
- **Кандидаты-источники «фантома»:**
  1. ghost-textarea копирования: `web/app.js:3310-3316`
     (`document.createElement('textarea')` + `document.body.appendChild`, класс `.clipboard-ghost`),
     CSS `web/index.html:426-433` (`position: fixed; left:-9999px; opacity:0`).
     Проверить поведение в Telegram WebView (не игнорируется ли `position:fixed`).
  2. Vue-комментарии/плейсхолдеры `v-if` в flex-строке.
  3. Grid-контейнер `main`: `web/index.html:672-673`
     (`grid-template-columns: repeat(auto-fill, minmax(320px,1fr))`) — призрачный grid-item
     мог бы создавать «пустую колонку».
- **Цель:** найти в живом DOM реальный узел слева от select, удалить/изолировать; grid фильтров
  выровнять.

### 3b. Колонки таблицы логов

- Разметка строки: `web/index.html:2520-2535`; level-badge `:2528`, дата `:2529`,
  logger `:2530`, сообщение `:2531` (`flex-1 min-w-0 break-all`), exc `:2533`.
- CSS: `.log-row` `web/index.html:381-382`, `.log-code` `:404-411` (`word-break: break-all`).
- **Цель:** фиксированная ширина для level (ERROR/INFO) и даты; последняя колонка `flex:1`
  с корректным переносом; не ломать клик-копирование и разворачивание стека (`@click.stop`).

### 3c. Копирование строки лога по клику + визуальный отклик

- Уже есть: клик по строке — `web/index.html:2521-2522` (`@click="copyText(logText(log))"`),
  `copyText` — `web/app.js:3300-3318`, тосты `toast(...)`.
- **Дыры:** `copyAllLogs` — `web/app.js:3328-3330` (`map(this.logText)` без `bind(this)`);
  нет явного transient-подсвета строки при копировании (только toast).
- **Цель:** копирование по клику оставить/усилить, добавить визуальный feedback (подсветка строки),
  язык — русский, title-подсказка; a11y (роль/фокус) не деградировать.

---

## 4. Задачи (декомпозиция для @Builder)

> Формат: `[ ] T-NNNN [@Owner] P<n> — заголовок`. Задачи кода — только @Builder;
> дизайн/root-cause — @Architect; деплой — @DevOps.

### Секция A — Header & navigation

- [x] **T-1224 [@Architect] P0** — spec.md: подтвердить root-cause 1a (воспроизведение на живом
  TMA, точный контрол), зафиксировать решения 1b/1c/1d, риск-границы safe-area/sticky/fullscreen.
  Выход: `plans/features/admin-ui-bugfixes-round107/spec.md`.
- [x] **T-1225 [@Builder] P0** — 1a: устранить показ `function () { [native code] }` в select/контроле;
  прогнать sweep `.map(this.)`/`.filter(this.)`/`.forEach(this.)` (найдено `web/app.js:3329`);
  убедиться, что все привязки значений/лейблов вызывают метод.
  Вход: spec.md T-1224. — ✅ 6 `scope*` перенесены в `computed`; `copyAllLogs` — явный `self`.
- [x] **T-1226 [@Builder] P0** — 1b: safe-area справа — правые элементы шапки (аватар/бейдж/`⛶`)
  не перекрываются нативными кнопками Telegram; добавить горизонтальный safe-area запас;
  проверить sticky/fullscreen-скролл. — ✅ `header.header-sticky` + `env(safe-area-inset-right/left)`.
- [x] **T-1227 [@Builder] P1** — 1c: компактный user block (avatar + name + role badge + fullscreen):
  уменьшить размеры/отступы, **все элементы сохранить**, не ломать `@error` аватара и a11y.
  — ✅ w-6/`gap-1.5`/`text-xs`/`max-w-[7rem]`/`text-[10px]`; обработчики сохранены.
- [x] **T-1228 [@Builder] P1** — 1d: подписи навбара в одну строку без разрыва слов
  («Настройки AI», «Как это работает», «Функции PERMsoc», «Доступы и Роли»);
  уменьшить кегль/отступы; mobile+desktop; active-состояние и `aria-current` сохранить.
  — ✅ `word-break: keep-all` + 2-line clamp + 0.625rem; `aria-current` не тронут.

### Секция B — Statistics screen

- [x] **T-1229 [@Builder] P0** — 2a: таблица ключей — длинные `model` (напр. `whisper-large-v3`)
  не ломают контейнер: ellipsis/`word-break`/`max-width`/`table-layout`; мобильный вид;
  матричную `.avail-list` (index.html:1648) не задеть.
  — ✅ `.keys-avail` scoped: `table-layout: fixed` + ширины + ellipsis + `:title`.
- [x] **T-1230 [@Builder] P0** — 2b: график истории — устранить плоскую линию.
  Согласовать с @Architect (T-1224) источник: пропущенные heartbeat-слоты = downtime
  (`services/uptime_heartbeat.py:26` пишет только `'up'`; `services/status_service.py:260-281`)
  и/или key-history отрисовка (`web/app.js:3195-3251`). Контракт leak-safety (OD19) не менять,
  новых PG-DDL не вводить.
  — ✅ `_bucketize` gap-fill непрерывной сетки (`down` для пустых слотов) + `last_heartbeat`
  = последний `up` либо `None`; `uptime_heartbeat.py` не тронут.

### Секция C — Logs screen

- [x] **T-1231 [@Builder] P0** — 3a: найти в живом DOM и убрать невидимый div/input слева от
  select «INFO», ломающий grid фильтров (`web/index.html:2499-2507`); проверить ghost-textarea
  (`.clipboard-ghost`, `web/app.js:3310-3316`) и grid `main` (`:672-673`).
  — ✅ ghost удаляется в `finally` (+`.remove()`), `focus({preventScroll:true})`,
  CSS `opacity:0; contain:strict` (без `visibility:hidden`); фильтр-строка выровнена (`shrink-0`/`min-w-0`).
- [x] **T-1232 [@Builder] P1** — 3b: фиксированная ширина колонок level (ERROR/INFO) и даты;
  сообщение — `flex:1` + корректный перенос; строки/клик-копирование/разворот стека не ломать.
  — ✅ `.log-level` 4.5rem, `.log-ts` 8ch + `fmtLogTime`, `.log-logger` ellipsis, `.log-msg` flex-1.
- [x] **T-1233 [@Builder] P1** — 3c: копирование по клику на строку лога + визуальный feedback
  (transient-подсветка строки, toast по-русски); починить `copyAllLogs` context-loss (`web/app.js:3329`).
  — ✅ `copyLogRow(log,i)` + `copiedIndex` + `.log-copied`; `copyAllLogs` — явный `self`.

### Секция D — Аудит @Scanner 10.6 (UI-часть, P2)

- [ ] **T-1234 [@Builder] P2** — R10.6-1: подавить дублирующий generic-рендер на
  `activeTab === 'llm_providers'` (21 дубль), 16 «generic-only» параметров сохранить
  (см. `plans/reports/round10.6_scanner_audit.md` §4). **Только если не раздувает риск раунда** —
  иначе вынести в 10.8 и отметить в отчёте.
  — ⏭️ НЕ ВЫПОЛНЕНО в 10.7 (опциональная P2, вне «exact fixes» этого прохода) → кандидат 10.8.

### Секция E — Документация / Коммит / Пуш / Деплой / Отчёт

- [ ] **T-1235 [@Builder] P1** — README (ироничный тон, канон стиля): версия/счётчик тестов/описание
  UI-фиксов 10.7 (`README.md`, шапка «Версия/Тестов/Раунд»).
  — ⏭️ Пропущено осознанно: рамки задачи @Builder для этого прогона — «no README».
- [ ] **T-1236 [@DevOps] P0** — полный прогон pytest (0 регрессий) + `node --check` + JS-тесты;
  русский conventional-commit (эталон + код + тесты одним атомарным коммитом, прецедент D123).
- [ ] **T-1237 [@DevOps] P0** — push в `origin/master`; деплой на прод: `git pull --ff-only`,
  `systemctl restart admin_bot`, проверка `active (running)`, `/api/health` = 200, чистые логи старта.
- [ ] **T-1238 [@DevOps] P1** — live-smoke задеплоенного TMA (по возможности): 1a-1d, 2a-2b, 3a-3c;
  фиксация результатов в отчёте.
- [ ] **T-1239 [@PM] P1** — plain-language отчёт владельцу (что болело → что сделано → как проверить),
  без жаргона.
- [ ] **T-1240 [@Scanner] P0** — пост-билд аудит (см. workflow): `plans/reports/round10.7_scanner_audit.md`.
- [x] **T-1241 [@PM] P1** — ✅ **ВЫПОЛНЕНО 11.09.2026** (Step 8 Archive Phase): перенос
  `plans/features/admin-ui-bugfixes-round107/` → `plans/archive/admin-ui-bugfixes-round107/`
  (spec.md + tasks.md); backlog-эпик 10.7 переведён в ✅ «ЗАВЕРШЁН И ЗААРХИВИРОВАН».
- [ ] **T-1242 [@DevOps] P1** — memory-sync docs-коммит (= `plans/docs/memory-project-overview.md`
  + обновления KG-индекса), проверка на секреты перед коммитом (правило T-725).

---

## 5. Acceptance criteria (AC)

### AC-1a (select native-code)
- Ни один select/контрол в UI не отображает `function () { [native code] }` (проверка на живом TMA).
- Все динамические привязки значений/подписей — вызовы (или корректно связанный контекст);
  sweep context-loss выполнен, `web/app.js:3329` исправлен.

### AC-1b (safe area)
- Правые элементы шапки (аватар, имя, роль, `⛶`) полностью видимы и не перекрываются
  нативными кнопками Telegram на iOS/Android TMA.
- Sticky-шапка и fullscreen-скролл (`.app-shell`/`.scroll-area`) работают как прежде.

### AC-1c (compact user block)
- Размеры/отступы user block уменьшены; **все** элементы (avatar + name + role badge + `⛶`) на месте.
- Аватар-fallback (`onMeAvatarError`) и подписи/title сохранены.

### AC-1d (nav labels)
- Подписи «Как это работает», «Настройки AI», «Функции PERMsoc», «Доступы и Роли» — в одну строку,
  без разрыва внутри слова, на mobile и desktop.
- Иконка + подпись выровнены, active-состояние и `aria-current` работают.

### AC-2a (keys table width)
- `whisper-large-v3` и аналоги длинных `model` не выходят за пределы карточки; ellipsis/перенос
  применены; горизонтальный overflow контейнера отсутствует на ширине TMA (≈360px).
- Матрица ролей (вторая `.avail-list`) не затронута визуально.

### AC-2b (chart history)
- График отображает исторические данные (не константная плоская линия при наличии истории);
  периоды недоступности/пропусков heartbeat видны согласно согласованному решению.
- Leak-safety (OD19 allowlist) и структура `/api/status*` не нарушены; новых PG-DDL нет.

### AC-3a (logs filters)
- В живом DOM перед select «INFO» нет скрытого div/input; фильтр-строка выровнена (grid не разъезжается).

### AC-3b (log columns)
- Колонки level (ERROR/INFO) и даты — фиксированной ширины; последняя текстовая колонка занимает
  остаток (`flex:1`) и переносится корректно; длинные строки не вылезают из панели.

### AC-3c (copy on click)
- Клик по строке лога копирует строку; виден визуальный отклик (подсветка и/или toast).
- «Копировать всё» работает (исправлен context-loss); ошибка копирования даёт понятный тост.

### AC-общие
- pytest — **0 регрессий** (baseline 5027 + новые); `node --check web/app.js` — clean;
  `node tests/js/routing_test.js` — `JS-UNIT-OK`; `git diff --check` — clean.
- Инварианты: REGISTRY 392 / GROUPS 91 / Settings 364; ноль PG-DDL; SQLite v8; `bot.py` не тронут;
  `media/` не тронут; R16/R17 соблюдены; секретов в коммите нет.
- README обновлён (ироничный тон); коммит на русском; push; деплой; plain-language отчёт.

---

## 6. QA / тест-план

**Статические проверки (обязательны на каждой задаче @Builder):**
- `node --check web/app.js` — синтаксис.
- `node tests/js/routing_test.js` — JS-unit (роутинг).
- `git diff --check` — whitespace.
- Ручной рендер-прогон `web/index.html` (эмулятор TMA / DevTools, mobile viewport ≈360×740):
  шапка, навбар, статус, логи; проверка AC-1a…AC-3c.

**Python/тесты:**
- Полный pytest ≤ 300с (`--timeout=120`): ожидание ≥ 5027 passed, 0 failed.
- При правке `services/status_service.py`/`uptime_heartbeat.py` — обновить/добавить тесты
  источника графика (пропуски heartbeat → downtime/key-history).
- Маркер-тесты фронта (прецедент MED-022, 10.2/10.3): проверить и обновить, если затронуты
  `test_frontend_tab_mapping.py`, `test_webapp_nav_disclosure_ui.py`, `test_webapp_*_ui.py`.
- Каталог-эталон `test_param_catalog` — **не менять** (инвариант).

**Smoke/визуальные (по возможности):**
- Live-smoke после деплоя (@DevOps, T-1238): шапка/навбар/статистика/логи на проде.
- Скриншоты «до/после» для 1b/1c/1d/2a/3b — приложить к отчёту.

---

## 7. Риски и пересечения

| Риск | Влияние | Митигация |
|---|---|---|
| 1a root-cause не воспроизводится статически | Можно «починить» не тот select | T-1224: живое воспроизведение до правок; sweep context-loss |
| safe-area (1b) ломает sticky/fullscreen | Регресс скролла шапки | Проверять `.app-shell`/`.scroll-area`/`header-sticky` в fullscreen |
| 2b затрагивает `services/` | Возможен регресс статуса/метрик | Согласование @Architect; тесты на источник; ноль PG-DDL |
| Правки `index.html`/`app.js` пересекают R10.6-1 (T-1234) | Конфликт областей шаблона | T-1234 — P2, после основных 1a-3c; общий QA-прогон |
| Маркер-тесты фронта фиксируют старое поведение | Ложные падения | Обновлять в каждой фронт-задаче (MED-022-прецедент) |
| R10.6-2/-3 (SSRF/422) остаются открытыми | Безопасность | Зафиксировать в backlog как кандидатов 10.8 (вне UI-скоупа) |

**Техдолг/кандидаты следующего раунда:** R10.6-2 (SSRF https allowlist), R10.6-3 (422-хендлер, R17),
R10.6-5 (мёртвые `ICONS`), R10.4-4…-6 (`ARCHITECTURE.md` §25).

---

## 8. Handoff

1. **@Architect** — T-1224: `spec.md` (root-cause 1a + решения 1b/1c/1d + 2b).
2. **@Builder** — секции A/B/C (по приоритетам) → D (P2) → E (README).
3. **@DevOps** — T-1236/T-1237/T-1238/T-1242 (проверки, коммит, push, деплой, live-smoke, memory-sync).
4. **@Scanner** — T-1240 (пост-билд аудит).
5. **@PM** — T-1239 (отчёт), T-1241 (архив) — после GO владельца.

> **@PM не пишет код.** Все исполнительские задачи назначены на @Architect/@Builder/@DevOps.

**Путь:** `plans/features/admin-ui-bugfixes-round107/tasks.md`
