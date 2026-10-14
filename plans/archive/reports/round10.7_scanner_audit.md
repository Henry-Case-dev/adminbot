# Round 10.7 Scanner Audit (admin-ui-bugfixes-round107: header/nav, stats, logs)

> Аудит 2026-09-11. HEAD `2ccf558` (10.6 docs) + рабочее дерево 10.7.
> `git status -s`: **9 modified + 2 untracked** (`tests/test_webapp_round107_ui.py`,
> `plans/features/admin-ui-bugfixes-round107/`).
> `git diff --shortstat` = **403 insertions / 125 deletions** по отслеживаемым.
> Изменённые: `web/index.html`, `web/app.js`, `services/status_service.py`,
> `plans/backlog.md` + 7 тест-файлов.
>
> **pytest: 5042 passed, 1 warning** (57.39s; база 10.6 = 5023 → **+19**).
> **`node --check web/app.js` / `tests/js/routing_test.js` — clean.**
> **`node tests/js/routing_test.js` — `JS-UNIT-OK`.**
> **`git diff --check` — чист (только LF/CRLF-warnings).**
> Проверены диффы всех изменённых файлов, полный текст `_bucketize`, JS-стабов,
> CSS-правил, независимая проверка каталога/шрифтового cmap и edge-case прогон
> `_bucketize` отдельным скриптом.

## 1. Инварианты — независимая проверка

| Инвариант | Проверка | Вердикт |
|---|---|---|
| Каталог **REGISTRY 392 / GROUPS 91 / Settings 364 / mapped 89** | Независимо: `len(REGISTRY)==392`; `len(GROUPS)==91`; `len(dataclasses.fields(Settings))==364`; `len(TAB_RULES)==19`; `len(CONFIG_TAB_TITLES)==19`; `len(_TAB_BY_GROUP)==89` | ✅ |
| **Ноль новых PG-DDL** | `git diff` по `services/database.py`, `services/pg_db.py` — пусто; grep `CREATE/ALTER/ADD COLUMN/user_version/schema_version` по tracked-диффу — пусто | ✅ |
| **SQLite v8** | `_SCHEMA_VERSION_AGI_MEMORY = 8` (`services/database.py:53`); файл не менялся | ✅ |
| **`bot.py` router order** | `bot.py` не в git-диффе; `git status -s bot.py` пусто | ✅ |
| **`media/` не тронут** | `git status -s media/` пусто | ✅ |
| **`uptime_heartbeat.py` / `key_history.py` не тронуты** | оба файла не в git-диффе и не в `git status`; heartbeat по-прежнему пишет только `'up'` (`:26`) | ✅ |
| **Нет секретов в диффе/untracked** | grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто; untracked — тест + docs-папка | ✅ |
| **R106-5 (мёртвые `ICONS`)** | удалены `account_balance_wallet/stop_circle/theater_comedy/toggle_off/toggle_on/speed`; grep по `web/` — 0 обращений (совпадение только `--grad-speed` CSS); независимо через `fontTools`: **все 20** оставшихся PUA-кодов присутствуют в cmap субсета (26 глифов) | ✅ закрыто |
| **`scope*` — computed, не methods** | `app.js:919-974` (computed) содержит 6 функций; grep `methods` — 0 дублей; все шаблонные привязки — свойства (`{{ scopeLabel }}`, `scopeOptions.length`, `scopeOptions[i]`), вызовов `scopeX()` нет | ✅ |

## 2. Верификация фиксов раунда

| # | Фикс | Проверка | Вердикт |
|---|---|---|---|
| 1a | `scope*` → computed | Перенос из methods (`-web/app.js:1313-1371`) в computed (`:914-974`). Восстановлены property-обращения из шаблона и из `scopeMove`/`scopePickFocused` (`:2097,2103`), которые с method-версией читали `.length`/индекс у функции и ломали клавиатурную навигацию. Vue-строки `function () { [native code] }` устранены | ✅ |
| 1b | safe-area padding шапки | `.header-sticky` → `header.header-sticky` (`index.html:563`, специфичность 0,1,1 перекрывает Tailwind `px-4`); `padding-left/right: calc(1rem + env(safe-area-inset-*,0px))`; sticky/fullscreen не затронуты (второе правило `header.header-sticky:595` — top safe-area mobile) | ✅ |
| 1c | компактный user block | `w-6 h-6`, `gap-1.5 text-xs`, `max-w-[7rem] truncate`, badge `text-[10px]`; сохранены `@error="onMeAvatarError()"`, `@click="toggleFullscreen()"`, `me.role_name` | ✅ |
| 1d | подписи навбара | `.nav-label`: `word-break: keep-all`, `overflow-wrap: break-word`, `-webkit-line-clamp: 2`, `text-overflow: ellipsis`, `0.625rem`; `overflow-wrap: anywhere` удалён; `aria-current`/active не тронуты; `>span:not(.msr){display:none}` отсутствует | ✅ |
| 2a | таблица ключей ellipsis | scoped `.keys-avail` (`index.html:370-385`): `table-layout: fixed` + ширины 34/18/30/8/10%, `td` — `nowrap`+`ellipsis`; `:title` на module/provider/model; матрица ролей (вне `.keys-avail`) не затронута | ✅ |
| 2b | uptime gap-fill | `_bucketize` (`services/status_service.py:286-301`) строит непрерывную сетку от `min(buckets)` до `now_slot`, пустые слоты → `down`; `[]` при пустых rows сохранён; `ts < since` отсекается; `[-288:]` сохранён. `last_heartbeat` = ts последнего `up`-бакета, иначе `None` (`:376-378`). Edge-cases (см. §4) | ⚠️ см. R10.7-1/-2 |
| 3a | ghost focusable + removed | `focus({preventScroll:true})` + `ta.remove()` + обнуление `window.__adminbotClipGhost` в `finally` (`app.js:3335-3340`); CSS `opacity:0` + `contain:strict`, `visibility:hidden` НЕТ (`index.html:462-478`); `execCommand('copy')` проверяется по boolean → нет ложного «Скопировано» (`:3327-3334`) | ✅ |
| 3b | колонки логов | `.log-level 4.5rem`, `.log-ts 8ch`+`tabular-nums`+`fmtLogTime` (`app.js:3285-3292`), `.log-logger` ellipsis (mobile hidden), `.log-msg` `flex-1`+`word-break: break-word`; `.log-panel .log-code` (0,2,0) перекрывает Tailwind `.break-all` (0,1,0); `.log-exc`/разворот стека не тронуты | ✅ |
| 3c | copy + feedback | `copyLogRow(log,i)` ставит `copiedIndex` + `:class log-copied` (`index.html:2570-2584`), таймер 800 мс; `copyAllLogs` — явный `self.logText(l)` | ✅ |

## 3. Проверенные области — вердикты

1. **Структура Vue**: `scope*`-блок действительно внутри `computed: {` (`app.js:761-975`),
   не в `methods`; новых дублей нет; `created()`/`mounted()`-порядок не тронут.
2. **Шаблон↔JS-контракт**: `{{ scopeLabel }}`/`scopeKind`/`scopeOptions`/`scopeTrigger*`
   читаются как свойства; вызовов `()` не осталось (grep пуст).
3. **Секреты/R17**: дифф не трогает `_mask_key`, `blockField*`, `/api/config`,
   `key_history`; новых полей-секретов нет.
4. **RBAC/DM**: изменений в `services/access.py`/`roles.py`/`web/api/*` нет; DM-ветки
   фронта (`canEditConfig`/`isDmCtx`) не затронуты.
5. **Контракт `/api/status`**: ключи `uptime.{buckets,last_heartbeat,since,until,generated_at}`
   сохранены; меняется только наполнение `buckets` (gap-fill) и семантика `last_heartbeat`
   (поле потребителей во фронте не имеет — grep пуст).
6. **Тесты**: стаб `document`/`navigator`/`execCommand` в `tests/js/routing_test.js`
   корректен; `test_webapp_avatars_ui._Static.body` — regex-поиск определения функции
   (устойчив к вложенному `avatarUrl:`); новые gap-fill-тесты устойчивы к границе слота
   (условия `statuses[:4]`/`all(...)` не зависят от лишнего граничного слота).

## 4. Новые находки раунда 10.7

### [R10.7-1] severity: minor — gap-fill помечает «текущий» незавершённый слот как `down`
**Файл**: `services/status_service.py:290-300` (заполнение до `now_slot` включительно),
`:376-378` (`last_heartbeat`).
**Суть**: сетка заполняется до `now_slot` включительно. Heartbeat пишется раз в 60 с
(`services/uptime_heartbeat.py:21,26`), а слот — 300 с. В момент сразу после границы 5-мин
слота строки в новом слоте ещё нет (первый heartbeat новой фазы приходит до 60 с позже) →
**правый край графика на это время помечается `down`, хотя бот жив**, а `last_heartbeat`
откатывается к ts предыдущего слота. Артефакт занимает `0…60` с на каждую 5-мин границу
(в среднем ~10 % времени), визуально — короткий ложный провал в правом краю графика.
Спека (§2b) явно предписывает заполнять «до текущего слота», т.е. это осознанный
trade-off (мгновенно видно реальный простой против ложного провала ~1 мин), поэтому minor,
а не major. Данные не искажаются, контракт не страдает.
**Ремендация**: при желании — заполнять только завершённые слоты
(`while slot <= now_slot - bucket_seconds`), либо считать текущий слот `up`, если в
предыдущем слоте был heartbeat не старше `2 × gap`. Оставлять как есть — допустимо по AC-2b.

### [R10.7-2] severity: info — `[-288:]` может отбросить единственный ранний `up`-бакет
**Файл**: `services/status_service.py:291-301`.
**Суть**: `first_slot = min(buckets)` получается `floor()` от ts, и может оказаться до
`since = now − 24ч` на ≤299 с. Тогда непрерывная сетка содержит 289 слотов и `[-288:]`
отбрасывает самый ранний. Если он был единственным `up` (далее — всё `down`), то
`last_heartbeat` станет `None` при формально имевшемся heartbeat. Очень узкий крайний случай
(требует, чтобы 24-часовое окно содержало ровно один heartbeat и он лёг в отсекаемый слот).
**Ремендация**: не критично; при желании ограничивать `first_slot` снизу `now_slot − 287·bucket`.

### [R10.7-3] severity: info — таймер подсветки `copiedTimer` не очищается при смене вкладки
**Файл**: `web/app.js:741-742` (data), `:3344-3352` (`copyLogRow`).
**Суть**: `setTimeout(...,800)` сохраняется в `copiedTimer` и очищается только при следующем
клике. При уходе со вкладки/роута в течение 800 мс таймер всё равно сработает и сбросит
`copiedIndex`. Корневой Vue-инстанс не размонтируется, поэтому утечки/ошибок нет —
чисто косметический отложенный сброс.
**Ремендация (необязательно)**: `clearTimeout` в `setTab`/`beforeUnmount`.

### [R10.7-4] severity: info — `test_font_subset` проверяет JS, а не cmap субсета
**Файл**: `tests/test_font_subset.py:73`.
**Суть**: изменённая проверка `assert "'\\ue887'" in js` гарантирует наличие PUA-кода в
`app.js`, но **не** наличие глифа в `var/fonts`/субсете. Независимо проверено `fontTools`:
cmap субсета (26 глифов) содержит **все 20** используемых `ICONS`-кодов (в т.ч. `\ue887`
`help`), поэтому R106-5 безопасен. Это пробел тест-покрытия (pre-existing), не дефект раунда.
**Ремендация (необязательно, 10.8)**: в тесте открывать WOFF2 и сверять `cmap` с
распарсенными `ICONS`.

### [R10.7-5] severity: info — заявленный «context-loss» `copyAllLogs` фактически отсутствовал
**Файл**: `web/app.js:3354-3360`; `logText` (`:3305-3308`).
**Суть**: T-1233/спека мотивировали правку «потерей `this` в `this.logs.map(this.logText)`»,
но `logText` не использует `this` (только аргумент `log`), поэтому старый код был
функционально корректен. Правка на `self.logText(l)` безвредна и стилистически лучше, но
описание причины неточно. Функциональных потерь нет.
**Ремендация**: скорректировать формулировку в tasks/отчёте (не код).

## 5. Итог 10.7

- **Блокеров: 0. Major: 0.** Minor: **1** (R10.7-1 — граничный ложный `down`).
  Info: **3** (R10.7-2…R10.7-4). Отдельно — точность формулировки (R10.7-5).
- Для мержа **не обязательны**. R10.7-1 — задокументированный спекой trade-off;
  R10.7-2…R10.7-4 — кандидаты 10.8.
- **Закрыто:** R10.6-5 (мёртвые `ICONS`) — удалены 6 неиспользуемых ключей,
  все оставшиеся 20 PUA-кодов присутствуют в cmap субсета. R10.6-1/2/3 остаются
  открытыми (вне UI-скоупа 10.7; кандидаты 10.8).
- **Ремедиации:** R10.5-1/-2 закрыты ранее (10.6), в 10.7 не регрессировали.
- Инварианты соблюдены: каталог **392 / 91 / 364 / mapped 89**; `TAB_RULES` 19;
  **ноль PG-DDL**; SQLite **v8**; `bot.py` не тронут; `media/` не тронут;
  `uptime_heartbeat.py`/`key_history.py` не тронуты; секреты не коммитятся.
- pytest **5042 passed / 0 failed** (1 pre-existing Starlette-deprecation warning +
  «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение, не регресс).
- `node --check` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.

*Round 10.7 report generated by Scanner on 2026-09-11*
