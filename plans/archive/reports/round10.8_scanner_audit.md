# Round 10.8 Scanner Audit (admin-ui-round108: renames, emoji→icons, Android logs, access windows, README)

> Аудит 2026-09-11. HEAD `636a75d` (10.7 docs) + рабочее дерево 10.8.
> `git status -s`: **18 modified + 2 untracked** (`tests/test_webapp_round108_ui.py`,
> `plans/features/admin-ui-round108/`).
> `git diff --stat`: **+610/−224** по 18 отслеживаемым (включая бинарный WOFF2 13 428→18 388 B).
> Изменённые исходники: `web/app.js`, `web/index.html`, `scripts/build_font_subset.py`,
> `web/static/fonts/material-symbols-rounded.woff2`, `README.md` + 13 тест-файлов.
>
> **pytest: 5073 passed, 1 warning** (54.87s; база 10.7 = 5042 → **+31**).
> **`node --check web/app.js` — clean.**
> **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, парный анализ `ICONS`↔`ICON_NAMES`↔cmap
> (независимым скриптом и `fontTools`), сверка идемпотентного маркера, ревизия разметки
> модалок, поиск утечек/секретов/DDL, независимый прогон новых тестов.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 392 / GROUPS 91 / Settings 364 / mapped 89 / TAB_RULES 19 / CONFIG_TAB_TITLES 19** | Независимо: `len(REGISTRY)==392`; `len(GROUPS)==91`; `len(dataclasses.fields(Settings))==364`; `len(TAB_RULES)==19`; `len(CONFIG_TAB_TITLES)==19`; `len(_TAB_BY_GROUP)==89` | ✅ |
| **Ноль новых PG-DDL** | `git diff --name-only` не содержит `services/database.py`/`services/pg_db.py`; `git diff -G "CREATE TABLE\|ALTER TABLE\|ADD COLUMN\|user_version\|schema_version" -- services/` — пусто | ✅ |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY == 8`; файл не менялся | ✅ |
| **`bot.py` router order не тронут** | нет в `git diff`/`git status` | ✅ |
| **`media/` не тронут** | `git status -s media/` пусто | ✅ |
| **Нет секретов** | grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто; untracked — тест + docs | ✅ |
| **Каталог-группа «Функции PERMsoc: рубильники» не переименована** | `param_catalog.by_id["flags_permsoc"].title_ru` не изменён (пинится тестом) | ✅ |
| **`fontTools` — build-time only** | в runtime `requirements.txt` нет; `test_fonttools_not_runtime_dep` зелёный | ✅ |

## 2. Паритет иконок и целостность субсета (п.2, R10.7-4 закрыт)

| Проверка | Метод | Результат |
|---|---|---|
| `ICONS` (JS) == `ICON_NAMES` (билд-скрипт) | независимый regex-парсер обоих | **37 == 37**, `ICONS\NAMES=[]`, `NAMES\ICONS=[]` ✅ |
| Каждый PUA-код `ICONS` присутствует в cmap WOFF2 | `fontTools.TTFont(...).getBestCmap()` | **37/37**, `missing=[]` ✅ |
| Нет лишних PUA-глифов в субсете | cmap ∩ PUA − `ICONS` | **[]** (субсет ровно 37 кодпоинтов) ✅ |
| Все иконки реально используются (нет мёртвых) | static `iconGlyph('…')`/`icon:` + dynamic пары | 33 static + 4 dynamic = **37** ✅ |
| 6 мёртвых имён 10.7 не вернулись | `DEAD_ICONS ∩ ICON_NAMES` | пусто ✅ |
| Размер субсета `< 60_000` | 18 388 B, магия `wOF2` | ✅ |
| Маркер идемпотентности учитывает `ICON_NAMES` | `sha256(src_sha + "|" + ",".join(ICON_NAMES))` == `build/font_source.sha256` | **совпал** ✅ (исходник 5 360 840 B на месте, gitignored) |
| `build/icon_codepoints.json` экспортируется | файл существует (`{name: "U+XXXX"}`, сортировка) | ✅ |
| Спецсимволы §2.3 сохранены | `✕ ⛶ ↪ ⟳ ← → ▶` присутствуют; `▶` ровно 3 (disclosure `<summary>`) | ✅ |
| Нет pictographic-emoji в `web/` | скан кодпоинтов ≥0x1F000 — **0**; только стрелки/бокс-графика | ✅ |
| Названия из `iconGlyph`/`icon:` есть в `ICONS` | все 34 static + 4 dynamic | ✅ |

## 3. Верификация фиксов раунда

| # | Фикс | Проверка | Вердикт |
|---|---|---|---|
| 1 | Переименования (Доступы/PERMsoc/ИИ/Справка/Сводка) | `NAV_ITEMS`/`TABS`/`HUBS`/`index.html` обновлены; старые `label:`/`«…»` отсутствуют в `web/`; route-ключи `#/how|ai|permsoc|access|oversight` не изменены | ✅ |
| 2 | Emoji→Material (subset 20→37) | 17 новых имён в `ICONS`/`ICON_NAMES`; паритет+cmap (см. §2); новые имена используются в шаблоне | ✅ |
| 3a | Шеврон лога вместо `▸`/`▾` | `v-if="log.exc_text"` → `iconGlyph(log.expanded?'expand_more':'chevron_right')`; иначе `log-toggle-spacer` (неинтерактивный, та же ширина) | ✅ |
| 3b | Дата возвращена | `fmtLogTime` = `DD.MM HH:MM:SS` (getDate/getMonth); `:title` = `fmtLogTs` цел; fallback для невалидного ts | ✅ |
| 3c | Блочная раскладка | `<div class="log-code">`/`.log-row`/`.log-head`/`.log-msg`; жёсткие `4.5rem`/`8ch`/`8rem` удалены; `break-all` убран; `.log-msg` `width:100%`+`overflow-wrap:anywhere`; `.log-exc` block; `@media≤479 .log-logger{display:none}` сохранён | ✅ |
| 3d | Копирование/стек | `@click="copyLogRow(log,i)"`, `@click.stop` на toggle, `log-copied`, `logText`/`copyAllLogs` не изменены | ✅ |
| 3e | R10.7-3 `copiedTimer` | `setTab` в начале: `clearTimeout(this.copiedTimer)`, `copiedTimer=null`, `copiedIndex=null` (`:2198-2202`) | ✅ |
| 4a | Три окна (взаимоисключающие) | `accessOpen ∈ {null,'roles','local','admins'}`; ровно 3 `modal-backdrop` с `v-if="isAccessOpen(...)"`; `sec-roles/sec-matrix/sec-local/sec-admins` сохранены | ✅ |
| 4b | «Администраторы»→«Роли» | hub-card title, заголовок окна и внутренний заголовок `sec-admins` = «Роли»; `title: 'Администраторы'` в JS нет | ✅ |
| 4c | `setAccess` удалён | grep `setAccess` в `web/` — 0; `openAccessWindow`/`closeAccessWindow` добавлены; `isAccessOpen` сохранён | ✅ |
| 4d | Deep-link / stale-window | `applyRoute`: `accessOpen = route.indexOf('#/access/')===0 ? substring : null` — не-access маршрут обнуляет; `ROUTE_PARENT` `#/access/*`→`#/access`; BackButton/in-app `←` через `goBack` | ✅ |
| 4e | `#/access` hub | hub-карточки без `section` (якорь не нужен, окно открывается по hash); всегда-видимые «Мой доступ»/«Промпты»/«Telegram ID админа» вне окон | ✅ |
| 5 | Внешний GLOBAL-бейдж | `{{ scopeLabel }}` встречается ровно 1 раз (внутри trigger); внешний `badge-muted shrink-0` удалён; `#id`-бейдж и computed `scopeLabel`/`isChatContext()` сохранены | ✅ |
| F | README | шапка v2.52.0 / 5073 / раунд 10.8; «Самое важное» наверх; гайд «Управление и деплой»; changelog под единственным `<details>` (открыт `:370`, закрыт `:456` — баланс); секретов нет | ✅ |
| — | RBAC не ослаблен | `sec-matrix v-if="isGlobalAdmin"`; role CRUD `:disabled="!canEditRole(role)"`; `openAccessWindow` гейтит `canViewTab('access')`; `applyRoute` hub/tab-RBAC сохранён | ✅ |

## 4. Новые находки раунда 10.8

### [R10.8-1] severity: minor — Esc не закрывает окна «Доступов» при фокусе вне модалки
**Файл**: `web/app.js:1023-1027` (глобальный `_onKeydown`), `web/index.html:1620,1663,1797`
(`tabindex="-1" @keydown.esc`).
**Суть**: `@keydown.esc` навешан на `.modal-card` с `tabindex="-1"`, но модалка **не
автофокусируется** (в `app.js` единственный `.focus()` — ghost-textarea `:3358`). При открытии
окна кликом по плитке фокус остаётся на кнопке-плитке (вне модалки), `keydown` до `.modal-card`
не доходит. Глобальный `_onKeydown` закрывает **только** окно модуля (`openModuleId != null`),
`accessOpen` не обрабатывает. Итог: Esc не закрывает окно «Доступов», пока пользователь не
сфокусируется внутри (клик по инпуту/таблице). Работают ✕, backdrop-click, нативный Back и
in-app `←` (через hash) — поэтому minor, а не major. AC-4 спеки прямо требует «✕ / backdrop / Esc».
**Ремендация** (1 строка): в `_onKeydown` добавить ветку
`if (e.key === 'Escape' && _appVm && _appVm.accessOpen != null) { _appVm.closeAccessWindow(); }`
(порядок: сначала модуль, затем access). Замечено: другие модалки (`roleEditor`/`permPicker`/
`oversightDetail`) имеют ту же унаследованную особенность — глобальный handler их тоже не знает.

### [R10.8-2] severity: info — устаревший комментарий про `section` и осиротевшая ветка `openHubCard`
**Файл**: `web/app.js:275-277` (комментарий «optional `section` … для `#/access/*`»),
`web/app.js:2085-2093` (`openHubCard`: `if (card.section) scrollToId(...)`).
**Суть**: 10.8 убрал `section` у всех трёх access-карточек (`HUBS['#/access']`), и больше ни
одна hub-карточка `section` не задаёт (grep `section:` вне HUBS — только role-editor items
`:3015/:3018`). Ветка `card.section` стала недостижимой в текущем дереве, комментарий вводит в
заблуждение. Функциональной потери нет (ветка безопасна/fallback).
**Ремендация** (doc-level): обновить комментарий (указать, что `section`-якоря выведены в 10.8
в пользу route-driven модалок) либо оставить `openHubCard` как generic-каркас.

### [R10.8-3] severity: info — `TABS[].icon`/`visibleTabs`/`tabMat` — мёртвый путь (pre-existing, не регресс)
**Файл**: `web/app.js:43,184,189` (`TABS.prompts/status/oversight.icon` теперь Material-имена),
`web/app.js:895-905` (`visibleTabs`), `web/app.js:2191-2194` (`tabMat`).
**Суть**: поле `TABS[].icon`, computed `visibleTabs` и метод `tabMat` не используются ни в
`web/index.html`, ни в `web/app.js` (таб-бар удалён ещё в 10.6, осталась одна навигация).
Поэтому замена `TABS.icon` emoji→Material (§1.2/§2.2) фактически инертна: визуально её видит
только `NAV_ITEMS`/`HUBS`/шаблон. Это pre-existing dead code (не внесён 10.8), но 10.8 правил
эти поля — фиксирую для трассируемости; `test_font_subset` по-прежнему пинит `tabMat`.
**Ремендация**: кандидат на удаление `visibleTabs`/`tabMat`/`TABS.icon` отдельным housekeeping
(с обновлением теста), либо оставить как задел.

### [R10.8-4] severity: info — `plans/backlog.md` показывает «🟡 ПЛАНИРОВАНИЕ» при завершённой реализации
**Файл**: `plans/backlog.md` (заголовок раздела 10.8).
**Суть**: в `tasks.md` §«Статус» уже зафиксирована выполненная реализация (pytest 5073/0),
а backlog-запись осталась в статусе планирования. Doc-drift; закрывается на Step 8 (@PM:
архив + статус ✅). Кода не касается.

### [R10.8-5] severity: minor — релизная версия не поднята: `APP_VERSION` 2.51.0 vs README v2.52.0; кэш старого субсета шрифта
**Файл**: `config/settings.py:1069` (`APP_VERSION = "2.51.0"`), `README.md` (шапка «Версия: v2.52.0»),
`web/app.py:43-64,67-72` (`CacheControlStaticFiles`/`_render_index`), `web/index.html:69`
(`@font-face src: url('/static/fonts/material-symbols-rounded.woff2')` без `?v=`).
**Суть**: (а) README поднят до **v2.52.0**, но `APP_VERSION` остался **2.51.0** (в 10.7 они
совпадали); версия отдаётся в `/api/status` (`services/status_service.py:365`), т.е. админка
после деплоя покажет 2.51.0 при README 2.52.0. (б) `/web/app.js?v=__APP_VERSION__` при этом
безопасен: `.js/.html/.css` отдаются `no-cache, no-store, must-revalidate` (`web/app.py:50,60-63`)
→ app.js всё равно ре-валидируется. НО `@font-face`-URL **не версионирован**, а `.woff2` отдаётся
`public, max-age=86400` (`:62`) → у клиентов с прогретым кэшем до 24 ч сохранится **старый**
субсет 10.7 (20 иконок) → 17 новых иконок дадут tofu до истечения кэша. Для раунда, чей ключевой
визуальный результат — новые иконки, это заметный (хоть и временный, само-лечащийся) риск.
**Ремендация**: поднять `APP_VERSION` до `2.52.0` (синхронно с README/`/api/status`) и
версионировать шрифт: `src: url('/static/fonts/material-symbols-rounded.woff2?v=__APP_VERSION__')`
и/или добавить `.woff2` в no-cache-суффиксы статики.

## 5. Проверенные области — вердикты (логических дыр не найдено)

1. **Логи (п.3)**: контракт `/api/logs`, `logText`, `copyAllLogs`, ghost-fallback `copyText`,
   автоскролл к верху, разворот стека — не изменены; менялись только раскладка/CSS/`fmtLogTime`.
   `log.ts` — ISO-строка (`services/log_ring.py:124-126`), `new Date(iso)` корректен; fallback
   для невалидного ts корректен. `@click.stop` на toggle сохранён.
2. **Доступы (п.4)**: разметка сбалансирована (проверен каждый `modal-backdrop`→`modal-card`→
   `modal-body`→`footer`); модалки взаимоисключающие по единственному `accessOpen`; на `#/access`
   рендерятся hub-карточки (не шаблон access), на `#/access/<id>` — плитки+одна модалка (дублей
   одновременно нет); `sec-*`-id сохранены; `openAccessWindow` → `navigateTo` → hash →
   `applyRoute` (единый применитель).
3. **Deep-link/BackButton**: `#/access/roles|local|admins` в `ROUTE_TO_TAB` (tab=`access`),
   `ROUTE_PARENT` → `#/access`, `routeDepth>0` → show. `applyRoute` при отсутствии прав
   откатывает на `#/` (replaceState), окно не всплывает.
4. **Нет functional loss**: содержимое трёх подразделов 1:1 (матрица `v-if=isGlobalAdmin`,
   role CRUD disabled, локальные админы с `:disabled=!isGlobalAdmin`); always-visible карточки
   вне окон; XSS-периметр (`sanitizeHtml` fail-closed) не затронут; серверные гейты не менялись.
5. **Шрифт/сборка**: `derive_pua_codepoints` — источник PUA; `_write_icon_codepoints` сортирует;
   up-to-date ветка пересоздаёт `icon_codepoints.json` при отсутствии; исходник 5.11 МиБ
   gitignored (`test_source_gitignored_subset_tracked`).
6. **README**: единственный `<details>`-блок корректен; секретов (ключей/DSN/токенов) в диффе нет;
   счётчик тестов (5073) совпадает с фактическим pytest. Замечание по версии `APP_VERSION` —
   см. R10.8-5.

## 6. Итог 10.8

- **Блокеров: 0. Major (High): 0.** Minor: **2** (R10.8-1 — Esc; R10.8-5 — версия/кэш субсета).
  Info: **3** (R10.8-2 stale-комментарий/ветка; R10.8-3 мёртвый TABS-иконочный путь;
  R10.8-4 backlog-статус).
- Для мержа **не обязательны** (нет blocker/major). R10.8-1 (Esc) и R10.8-5 (APP_VERSION+версия
  шрифта) — точечные ремедиации, рекомендуются в follow-up/перед объявлением раунда закрытым.
- **Закрыто:** **R10.7-3** (`copiedTimer`/`copiedIndex` очищаются в `setTab`) и **R10.7-4**
  (тест субсета теперь парсит `ICONS`/`ICON_NAMES` и сверяет cmap WOFF2 через `fontTools` —
  в `.venv` тест **выполняется, не skip**). R10.7-1/-2 (`status_service.py`) и R10.6-1/2/3
  остаются открытыми (вне UI-скоупа 10.8).
- Инварианты соблюдены: каталог **392 / 91 / 364 / mapped 89**, `TAB_RULES` 19; **ноль PG-DDL**;
  SQLite **v8**; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся.
- pytest **5073 passed / 0 failed** (54.87s; 1 pre-existing Starlette-deprecation warning +
  «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение, не регресс).
- `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.

*Round 10.8 report generated by Scanner on 2026-09-11*
