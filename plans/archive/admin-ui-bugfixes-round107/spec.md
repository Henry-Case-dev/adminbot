# spec.md — admin-ui-bugfixes-round107 (Раунд 10.7)

> **FEATURE:** `plans/features/admin-ui-bugfixes-round107/`
> **РАУНД:** 10.7 (UI/UX bugfix после 10.6 `tma-ia-modules-rework`, HEAD `2ccf558`).
> **Автор спеки:** @Architect (Step 2, T-1224). **НЕ реализация** — только диагноз, точный фикс-план, AC, тесты.
> **Вход:** `tasks.md` (рекогносцировка @PM), `web/index.html`, `web/app.js`,
> `services/status_service.py`, `services/uptime_heartbeat.py`, `services/key_history.py`,
> `web/api/routes.py`.
> **Baseline:** pytest **5027 passed / 0 failed**; `node --check web/app.js` — clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` — clean.

---

## 0. Учёт аудита @Scanner (ОБЯЗАТЕЛЬНО — проверено перед проектированием)

Прочитаны свежие отчёты: `plans/reports/round10.6_scanner_audit.md` (11.09.2026, новейший),
`plans/reports/round10.5_scanner_audit.md`, `plans/reports/full_audit_results.md` (вкл. §10.3/10.4),
`plans/reports/global_map.md`, `plans/reports/audit_backlog.md`.

| Находка 10.6 | Применимость к 10.7 | Учёт |
|---|---|---|
| **R10.6-1** — 21 дубль LLM-редакторов | P2, UI | Вне ядра 10.7; оставлен как **T-1234** (optional, только после 1a–3c). |
| **R10.6-2** — SSRF `https` в `/api/llm/test` | backend/security | Вне UI-скоупа → 10.8 (не трогаем). |
| **R10.6-3** — 422-эхо `api_key` (R17) | backend/security | Вне UI-скоупа → 10.8 (не трогаем). |
| **R10.6-4** — контракт блоков `llm/test` | info | Не трогаем. |
| **R10.6-5** — мёртвые `ICONS` (`web/app.js:228-233`) | info | **ВКЛЮЧАЕМ** как дешёвый P2 (§R106-5): удалить 6 мёртвых ключей + поправить 1 тест. |
| **R10.6-6** — rate-limit до валидации блока | info | Вне UI-скоупа. |

**Scanner-контроль, релевантный нашему периметру:**
- Ноль новых PG-DDL / SQLite v8 — держит и 10.7 (2b правит только `status_service`/тесты).
- Leak-safety OD19 (`key_history`) — **не менять** allowlist/эмиссию; 2b его не касается.
- Маркер-тесты фронта (MED-022-прецедент) фиксируют старое поведение (см. §T); в 10.7
  часть из них обновляется осознанно и перечислена явно.
- R16/R17, `bot.py`, `media/` — не трогаются.

---

## 1. Итоговая карта фиксов (сводка для @Builder)

| # | Баг | Root cause (кратко) | Файлы | Приоритет |
|---|---|---|---|---|
| 1a | `function () { [native code] }` в scope-контроле | 6 `scope*` объявлены в `methods`, а потребляются как computed-свойства | `web/app.js` | **P0** |
| 1b | Перекрытие правой шапки кнопками Telegram | нет `env(safe-area-inset-right)` | `web/index.html` (CSS) | P0 |
| 1c | Раздутый user block | крупные размеры/отступы | `web/index.html` | P1 |
| 1d | Переносы подписей по слогам | `overflow-wrap:anywhere` + крупный кегль | `web/index.html` (CSS) | P1 |
| 2a | Длинные `model` ломают таблицу | нет `table-layout:fixed`/`max-width` | `web/index.html` (CSS) | P0 |
| 2b | График — плоская линия | uptime-бакеты не заполняют пропуски heartbeat | `services/status_service.py` | **P0** |
| 3a | Невидимый узел слева от «INFO» | персистентный `.clipboard-ghost` (единственный runtime-inject) | `web/app.js` (+CSS) | P0 |
| 3b | Колонки логов «плывут» | нет фикс-ширин level/date, строка flex-wrap | `web/index.html` (+CSS) | P1 |
| 3c | Нет визуального отклика при копировании | копирование есть, подсветки нет; `copyAllLogs` latent-context | `web/app.js`, `web/index.html` | P1 |
| R106-5 | Мёртвые `ICONS` | 6 неиспользуемых Material-ключей | `web/app.js`, `tests/test_font_subset.py` | P2 |

---

## 2. ДИАГНОСТИКА И ФИКСЫ ПО БАГАМ

### 1a. `function () { [native code] }` в select-подобном контроле — **ROOT CAUSE НАЙДЕН**

**Симптом:** «select» в шапке печатает `function () { [native code] }`.

**Улика (верифицировано прогоном `web/app.js` под Vue-стабом, как в `tests/js/routing_test.js`):**

```
scopeKind         => computed:false methods:true
scopeLabel        => computed:false methods:true
scopeOptions      => computed:false methods:true
scopeTriggerTitle => computed:false methods:true
scopeTriggerInitial => computed:false methods:true
scopeTriggerAvatar  => computed:false methods:true
```

**Механизм (точная причина):**
- В `web/app.js` блок `computed:` открывается на строке **764** и **закрывается на 917**.
  Блок `methods:` открывается на **1004**. Следовательно, `scopeKind` (`:1318`), `scopeLabel`
  (`:1322`), `scopeOptions` (`:1327`), `scopeTriggerTitle` (`:1360`), `scopeTriggerInitial`
  (`:1363`), `scopeTriggerAvatar` (`:1366`) лежат **в `methods`**, хотя задуманы как
  производные (компьюторы) — @PM/@Memory-рекогносцировка ошибочно отнесла их к `computed`
  (одинаковый отступ 6 пробелов + тест `test_webapp_back_button.py:181` проверяет лишь
  подстроку `"scopeKind: function ()"`, не блок).
- Шаблон использует их **как свойства без вызова**: `index.html:583` `:title="scopeTriggerTitle"`,
  `:589` `{{ scopeTriggerTitle }}`, `:592`/`:626` `{{ scopeLabel }}`, `:588` `{{ scopeTriggerInitial }}`,
  `:586` `:src="scopeTriggerAvatar"`, `:590` `:class="... scopeKind === 'global' ..."`,
  `:600` `v-for="(o, idx) in scopeOptions"`.
- Vue 3 в Options API **биндит каждый метод** к инстансу (`ctx[key] = method.bind(publicThis)`),
  а `Function.prototype.toString()` у bound-функции всегда возвращает
  ровно `function () { [native code] }`. Поэтому интерполяция/атрибут рендерит эту строку.
- Побочно: `v-for` по функции (`scopeOptions`) даёт пустой список → выпадающий список scope
  не наполняется.

**Почему это и есть «select-like control»:** в шапке нет литерального `<select>`
(`index.html:576-618` — кастомный scope-dropdown, стилизованный классом `field`; визуально
неотличим от select). Именно его trigger и badge и печатают native-code.

**Кандидаты из рекогносцировки — вердикт:**
- (i) `scope*` в `methods`, но используются как computed → **ЭТО И ЕСТЬ ROOT CAUSE** (подтверждено).
- (ii) `this.logs.map(this.logText)` (`web/app.js:3329`) → **НЕ даёт этого симптома**: Vue уже
  биндит методы, а `logText` (`:3296-3299`) не использует `this`. Дефект **латентный** —
  фиксируем защитно (см. 3c), но не он печатает native-code.

**Точный фикс (без нового кода в спеке — что именно сделать):**
- **Перенести** определения `scopeKind`, `scopeLabel`, `scopeOptions`, `scopeTriggerTitle`,
  `scopeTriggerInitial`, `scopeTriggerAvatar` из блока `methods` (диапазон `web/app.js:1316-1373`)
  в блок `computed` (до его закрывающей `}` на `web/app.js:917`).
- **Удалить** эти 6 определений из `methods` (не дублировать).
- Сигнатуры/тела не менять: они уже корректны как чистые производные
  (`scopeTriggerInitial` вызывает `scopeTriggerTitle`; `scopeLabel` — `scopeKind`;
  `scopeKind` — `isDmCtx()`; `scopeOptions`/`scopeTriggerAvatar` читают `accessChats`).
  Реактивность Vue 3 захватит зависимости и через вызываемые методы (`isDmCtx`).
- Данные остаются в `data()` без изменений (`scopeOpen`/`scopeSearch`/`scopeFocus`/`scopeEpoch`,
  `web/app.js:613-617`).

**Sweep context-loss (обязательный):** пройти по `web/app.js`/`web/index.html` для
`.map(this.`/`.filter(this.`/`.forEach(this.`/`.find(this.`/`.some(this.`/`.reduce(this.` —
в кодовой базе ровно **1** вхождение (`web/app.js:3329`), плюс проверить, что ни один
шаблон не ссылается на метод без вызова (после фикса — ноль; регрессионный JS-тест ниже).

**Acceptance criteria (AC-1a):**
- Ни в шапке, ни в любом `<select>`/контроле не отображается `function () { [native code] }`.
- Scope-trigger показывает `scopeTriggerTitle` (строку) и `scopeLabel` (GLOBAL/ЧАТ/ЛС);
  dropdown наполняется опциями; `v-for` работает.
- `scopeKind`, `scopeLabel`, `scopeOptions`, `scopeTriggerTitle`, `scopeTriggerInitial`,
  `scopeTriggerAvatar` присутствуют в `captured.computed` и отсутствуют в `captured.methods`.

**Тест-подход (AC-1a):**
- **JS (главный, реальный):** в `tests/js/routing_test.js` (блок после `const methods = captured.methods;`)
  добавить проверки:
  - `captured.computed.scopeTriggerTitle` и `captured.computed.scopeLabel` — функции;
  - `!captured.methods.scopeTriggerTitle` и т.д. для всех 6;
  - вызов `captured.computed.scopeOptions.call({isGlobalAdmin:true, scopeSearch:'', accessChats:[]})`
    возвращает массив с элементом `{key:'global'}`.
- **Python-маркер (усилить существующий):** в `tests/test_webapp_back_button.py::TestScopeSwitcherT1127`
  добавить проверку, что все 6 имён присутствуют **внутри** среза JS между `computed: {` и `methods: {`
  (а не только как подстроки где угодно). Это ловит регресс «положили обратно в methods».
- Ручной live-чек (T-1238): открыть TMA → scope-trigger печатает имя скоупа, список непустой.

---

### 1b. Safe area: правые элементы шапки под нативными кнопками Telegram

**Root cause:** в CSS есть только `env(safe-area-inset-top)` (мобильная медиа, `index.html:548`)
и `env(safe-area-inset-bottom)` (`:541`); `env(safe-area-inset-right)` отсутствует. Шапка
(`header.main-header.header-sticky`, `index.html:558-559`) задаёт `px-4` (1 rem по обе стороны),
чего недостаточно под нативными кнопками WebView справа (закрытие/сворачивание, «⋯»).

**Точный фикс (`web/index.html`, CSS):**
- В базовое правило `header.header-sticky` (`:517-522`) добавить:
  `padding-right: calc(1rem + env(safe-area-inset-right, 0px));`
  (и симметрично `padding-left: calc(1rem + env(safe-area-inset-left, 0px));` — для вырезов;
  обе с fallback `0px`).
- Сохранить мобильную ветку `@media (max-width:768px) header.header-sticky { padding-top: … }`
  (`:546-550`) без изменений.
- Убедиться, что `.ml-auto` user-block (`:627`) остаётся в пределах padding; при необходимости
  добавить `padding-right` не нужно — правый padding шапки достаточно.
- Проверить, что `sticky`/`fullscreen`-скролл (`.app-shell`, `.scroll-area`, `.fullscreen-mode`,
  `:527-544`) не затронуты (safe-area только горизонтальный отступ, не `height`/`overflow`).

**AC-1b:** аватар, имя, role-badge и `⛶` полностью видимы и не под нативными кнопками на iOS/Android;
sticky-шапка и fullscreen-скролл работают как прежде.

**Тест-подход:** Python-маркер в `tests/test_frontend_tab_mapping.py`/`test_webapp_nav_disclosure_ui.py`:
`assert "env(safe-area-inset-right" in html` и `"calc(1rem + env(safe-area-inset-right, 0px))" in html`.
Ручной live-скриншот «до/после» (T-1238). Регресс `node --check` + JS-тесты.

---

### 1c. Компактный user block (avatar + name + role badge + fullscreen)

**Root cause:** размеры/отступы блока не уменьшались после редизайна: avatar `w-8 h-8` (32 px),
родитель `gap-2 text-sm`, badge — общий `.badge`, кнопка `⛶` — `btn-ghost text-sm px-2`
(`web/index.html:627-642`).

**Точный фикс (`web/index.html:627-642`) — только сжатие, элементы СОХРАНИТЬ:**
- контейнер: `gap-2 text-sm` → `gap-1.5 text-xs`;
- `<img>`: `w-8 h-8` → `w-6 h-6` (сохранить `@error="onMeAvatarError()"`, `rounded-full`, `shrink-0`);
- имя: добавить `text-xs truncate max-w-[7rem]` (оставить fallback-цепочку имён);
- badge (`me.role_name`): добавить компактные утилиты `text-[10px] px-1.5 py-0`;
- кнопка `⛶`: `btn-ghost text-sm px-2` → `btn-ghost text-xs px-1.5 py-1`; сохранить
  `:title` (динамический) и `@click="toggleFullscreen()"`.

**AC-1c:** все 4 элемента на месте; аватар-fallback (`onMeAvatarError`) и `title` живы;
блок заметно компактнее, не увеличивает высоту шапки.

**Тест-подход:** Python-маркеры: сохранены `onMeAvatarError`, `toggleFullscreen`,
`me.role_name`; присутствует `w-6 h-6` и `max-w-[7rem]`. Визуальный «до/после» (T-1238).

---

### 1d. Подписи навбара — одна строка без разрыва внутри слова

**Root cause:** `.nav-label` (`web/index.html:213-216`) имеет `overflow-wrap: anywhere`, из-за
чего браузер ломает слова в любом месте («Настрой ки AI», «Как это работае т»); кегль
`var(--tx-tiny)` = 0.75 rem, `gap: 2px`, `.nav-link` `padding: .3rem .25rem`
(`:205-211`). На 6 пунктов при ширине TMA ≈360 px места мало.

**Точный фикс (`web/index.html`, CSS `:205-222`; данные `NAV_ITEMS` не менять):**
- `.nav-link`: `gap: 2px` → `1px`; `padding: .3rem .25rem` → `.25rem .1rem`.
- `.nav-link .nav-icon`: `font-size: 20px` → `18px`.
- `.nav-label`: уменьшить кегль до **0.625rem**; `line-height: 1.05`; `letter-spacing: -0.01em`;
  `word-break: keep-all`; `overflow-wrap: break-word` (НЕ `anywhere` — ломать слово только
  если оно не влезает целиком); `hyphens: none`; контролируемые **2 строки**:
  `display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden`.
- Правило поведение при слишком длинной подписи (единое mobile+desktop): до 2 строк с переносом
  **по словам**; если и это не влезает — клампится с ellipsis. Полная подпись остаётся в
  `:title="n.label"` на кнопке (`index.html:650`).
- `@media (min-width:992px) { .nav-link { min-width:72px; } }` (`:222`) и адаптив
  `@media (max-width:479px) .nav-link { padding:.35rem .15rem }` (`:296`) сохранить/согласовать.
- **Не возвращать** правило `.nav-link > span:not(.msr) { display:none }` (запрещено тестами).

**AC-1d:** подписи «Как это работает», «Настройки AI», «Функции PERMsoc», «Доступы и Роли»
переносятся (при необходимости) **по словам**, без разрыва внутри слова, на mobile и desktop;
иконка+подпись выровнены; `active`/`aria-current` (`:648-649`) работают.

**Тест-подход:** существующие маркеры (`test_frontend_tab_mapping.py:185-187`,
`test_round106_ia_smoke.py:79-80`, `test_webapp_hubs_matrix_ui.py:160-161`) должны остаться
зелёными; добавить `assert "word-break: keep-all" in html` и `assert "text-overflow: ellipsis" in html`
(кламп-стиль) — как регресс на «не anywhere». Визуальный чек.

---

### 2a. Таблица ключей: длинные имена моделей ломают ширину

**Root cause:** `.avail-list td { white-space: nowrap }` (`web/index.html:349-352`) +
`.avail-list td.mono { overflow:hidden; text-overflow:ellipsis }` **без `max-width`/`table-layout`**
(`:353-354`). В auto-layout таблице `ellipsis` не срабатывает (ячейка расширяется под контент),
поэтому `whisper-large-v3` и длинные `module_title` раздувают/ломают карточку. Это CSS применяется
к **двум** таблицам `.avail-list`: ключи (`:2470-2490`) и матрица ролей (`:1648-1682`) — матрицу
задевать нельзя.

**Точный фикс (`web/index.html`, только для таблицы ключей):**
- Дать контейнеру таблицы ключей (`<div class="card p-4" style="grid-column:1/-1;">`, `:2459`)
  доп. класс `keys-avail` — так `class="avail-list"` на самой таблице (`:2470`) останется
  дословным (не ломает маркер `test_webapp_key_availability_ui.py:22`), а CSS скоупится.
- Добавить CSS (scoped, не влияет на матрицу):
  - `.keys-avail .avail-list { table-layout: fixed; }`
  - ширины колонок (5 колонок) через `nth-child(1..5)` (Модуль ~34%, Провайдер ~18%,
    Модель ~30%, Код ~8%, Статус ~10%);
  - `.keys-avail .avail-list td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }`
    (ячейки Модуль/Провайдер/Модель не выходят за карточку; `.mono` уже имеет ellipsis).
- В разметке строки (`:2476-2488`) добавить `:title` к Модулю/Провайдеру/Модели
  (`p.module_title`, `p.provider`, `p.model`) — полное значение по hover (доступность).
- **Матрицу** (`:1648-1682`) и другие таблицы (`:1460`, `:2470` не в `.keys-avail`) — не менять.
  Существующее мобильное правило `:297` (скрытие 2-й колонки `.avail-list`) оставить как есть,
  чтобы не менять вид матрицы.

**AC-2a:** `whisper-large-v3` и аналоги не выходят за карточку; ellipsis/`max-width` применены;
горизонтального overflow на ≈360 px нет; матрица ролей визуально не затронута.

**Тест-подход:** Python-маркеры: `"keys-avail"` + `"table-layout: fixed"` + `"text-overflow: ellipsis"`
в HTML; существующие маркеры `.avail-list`/`--tx-tiny`/`line-height: 1.25` зелёные. Ручной
mobile-viewport чек (360×740) + скриншот.

---

### 2b. График — плоская линия. **ЭТО UPTIME-ГРАФИК** (не key-history)

**Вердикт:** плоская линия — **график аптайма** (`index.html:2448-2454`, `renderUptimeChart`,
`web/app.js:3130-3167`). Key-history-график (`:3195-3251`) **отрисовывает корректно** и в норме
плоский только если все ключи здоровы (записывает реальные `ok/http_status` через
`_build_llm_card` → `key_history.record(...)`, `services/status_service.py:344-352`).

**Root cause (по уликам):**
1. `services/uptime_heartbeat.py:26` — `_INSERT_SQL = "INSERT INTO uptime_events (status) VALUES ('up')"`.
   Писателя `'down'` в коде **НЕТ** (проверено grep по репо). Когда процесс бота не работает,
   строк вообще не появляется (down-процесс не может вставить строку).
2. `StatusService._bucketize` (`services/status_service.py:260-281`) строит бакеты **только по
   существующим строкам** («последняя побеждает»), **не заполняя пропущенные 5-мин слоты**.
   Фронт же берёт `labels` из тех же бакетов (категориальная ось, `web/app.js:3135-3140`),
   поэтому отсутствие слотов не превращается в разрыв — линия непрерывна.
3. Итог: при наличии данных линия всегда `1` (up) и не показывает периоды простоя →
   «плоская линия».

**Точный фикс (recording + rendering, без новых PG-DDL / SQLite v8):**
- **`services/status_service.py::_bucketize` (`:260-281`) — синтез пропусков:**
  - если `rows` пуст → по-прежнему вернуть `[]` (сохраняет `build_snapshot`-fallback и
    `test_empty_rows`);
  - иначе: собрать множество слотов с данными; построить **непрерывную 5-мин сетку**
    от минимального слота (в пределах окна 24ч) до текущего слота (`now // 300 * 300`);
    слот с данными → статус последней строки (как сейчас); слот **без** строк → `status="down"`
    (нет heartbeat ⇒ простой);
  - наивные `ts` локализовать как сейчас (`:271-273`); отсечь `ts < since`;
  - ограничить `[-288:]` (≤288 точек) — как сейчас.
- **`last_heartbeat` (`:354`)** — исправить семантику: это `ts` **последнего бакета со
  `status=="up"`**, иначе `None` (сейчас `buckets[-1]["ts"]`, что после gap-fill показывал бы
  «сейчас» при простое). Фронт это поле не использует (grep пуст) — безопасно.
- **`services/uptime_heartbeat.py:26` — НЕ менять**: запись `'up'` корректна; down корректно
  **деривится из отсутствия** heartbeat (down-процесс физически не сможет записать `'down'`).
  Опционально (вне обязательного объёма): best-effort `'down'`-маркер в graceful-shutdown —
  не требуется для AC и не вводится.
- **Фронт `renderUptimeChart` (`web/app.js:3130-3167`) — не менять**: он уже маппит
  `down→0`, `up→1`, `spanGaps:false`, `y.min=0..max=1.2`; при появлении явных `down`-бакетов
  график покажет провалы. (Дополнительно можно подписать ось `up/down`, но не обязательно.)
- **Контракт не меняется:** `_ALLOWED_*`, leak-safety OD19, `key_history` — не трогаем;
  новых таблиц/колонок нет.

**AC-2b:** при наличии истории график аптайма не константен: периоды без heartbeat видны
как провалы (down); структура `/api/status*` совместима; новых PG-DDL нет; SQLite v8.

**Тест-подход (Python, обязателен):**
- Новый/расширенный `tests/test_status_service.py::TestUptimeBuckets`:
  - gap-fill: строки в `t0` и `t0+15мин` → 4 бакета `up, down, down, up` (порядок/статусы);
  - trailing downtime: последняя строка 20 мин назад → последние бакеты `down`;
  - `_bucketize([]) == []` сохраняется; `≤288`; naive-ts → 1 бакет (существующие тесты);
  - `test_bucket_count_within_288` остаётся зелёным (сетка упирается в `[-288:]`).
- Обновить семантику `last_heartbeat`:
  - `test_uptime_empty_rows_minimal_buckets` — ожидать `up["last_heartbeat"] is None`
    (бакеты-fallback все `down`); `test_uptime_from_pg` — остаётся truthy (есть up-бакет).
- (`test_uptime_heartbeat.py` не меняется — heartbeat по-прежнему пишет `'up'`.)

---

### 3a. Невидимый div/input слева от select «INFO», ломающий grid

**Root cause / сужение:** в **статическом** шаблоне фильтр-строки (`web/index.html:2499-2507`)
скрытого `<input>`/`<div>` **нет** (проверено по всему файлу). Единственный узел, инжектируемый
в DOM в runtime — `textarea.clipboard-ghost` в fallback-копировании
(`web/app.js:3310-3316`: `document.createElement('textarea')` + `document.body.appendChild`),
CSS — `web/index.html:426-437`. Он персистентно живёт в `document.body` (`window.__adminbotClipGhost`)
и при неудачном позиционировании/фокусе в WebView (focus-scroll) проявляется у фильтр-строки
логов. Grid-контейнер `main` (`index.html:672-673`) как источник «пустой колонки» отклонён:
карточка логов имеет `grid-column: 1 / -1`.

**Точный фикс (детерминированный, с сохранением маркеров `test_webapp_tma_fixes_ui.py:59-71`):**
- **`web/app.js::copyText` (`:3300-3326`):**
  - focus без автоскролла: `ta.focus({ preventScroll: true })` (и `ta.select()`);
  - после копирования **убрать узел из DOM** в `finally`
    (`ta.remove()` / `ta.parentNode.removeChild(ta)`), обнулить `window.__adminbotClipGhost`;
  - `.clipboard-ghost` CSS и `window.__adminbotClipGhost`-маркеры при этом сохраняются
    (тест проверяет их наличие, а не персистентность).
  - первичный путь `navigator.clipboard.writeText` — без изменений.
- **CSS `web/index.html:426-437`:** усилить изоляцию от раскладки: добавить `contain: strict;`
  (оставить `position:fixed; left:-9999px; top:0; width:1px; height:1px; opacity:0;
  pointer-events:none; background:transparent !important`). **НЕ добавлять `visibility:hidden`** —
  скрытый таким образом элемент не фокусируется, и `document.execCommand('copy')`-fallback
  ломается (Telegram WebView, где `navigator.clipboard` часто недоступен).
- **Фильтр-строка логов (`index.html:2499-2507`):** явно зафиксировать flex-выравнивание:
  держать `flex items-center gap-2 flex-wrap`; `select` — `shrink-0`; счётчик — `min-w-0`.
- Обязательная **live-процедура диагностики** (T-1224/Builder): DevTools → Elements, найти узел
  слева от `<select>`; убедиться, что это `textarea.clipboard-ghost`, и что после фикса он не
  остаётся в DOM. Если live-DOM покажет иной узел — зафиксировать в отчёте и удалить точечно.

**AC-3a:** в живом DOM перед select «INFO» нет скрытого div/input; фильтр-строка выровнена;
`document.body` не накапливает `textarea.clipboard-ghost`.

**Тест-подход:**
- JS (расширить стаб в `tests/js/routing_test.js`: `document.body`, `createElement`,
  `appendChild`, `execCommand`): вызвать `copyText.call(stub, 'x')` и проверить, что после
  завершения в `document.body` нет дочерних `textarea.clipboard-ghost` (или что вызван `remove`).
- Python-маркер: `assert "preventScroll" in js` и `assert ".remove()" in js` в блоке copyText.

---

### 3b. Колонки таблицы логов: фикс-ширины level/date + `flex:1` у сообщения

**Root cause:** строки логов (`web/index.html:2520-2535`) — `<span class="flex items-start
gap-2 flex-wrap">`; level-badge/дата/logger — `shrink-0` по контенту (без фикс-ширины), дата —
полный `fmtLogTs` (`toLocaleString('ru-RU')`, длинная), сообщение — `flex-1 min-w-0 break-all`.
Из-за `flex-wrap` и отсутствия фикс-ширин колонки «плывут», сообщение уезжает на новую строку.

**Точный фикс (`web/index.html` шаблон `:2520-2535` + CSS `:381-411`):**
- Убрать `flex-wrap` у внутреннего контейнера строки; оставить
  `class="flex items-start gap-2"`.
- **level:** обернуть badge в `<span class="log-level shrink-0">`; CSS
  `.log-level { min-width: 4.5rem; text-align: center; }` (ERROR/INFO/CRITICAL выровнены).
- **дата:** `<span class="log-ts shrink-0">`; ввести компактный хелпер `fmtLogTime(ts)`
  (`HH:MM:SS`, `title` — полный `fmtLogTs`); CSS `.log-ts { width: 8ch; white-space: nowrap;
  font-variant-numeric: tabular-nums; }`.
- **logger:** `.log-logger shrink-0` с `max-width: 8rem; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap;` (на узких экранах можно скрыть через media ≤479px).
- **сообщение:** оставить `flex-1 min-w-0`, добавить класс `log-msg`;
  CSS `.keys`-независимо: `.log-msg { word-break: break-word; overflow-wrap: anywhere;
  white-space: normal; }`.
- **обёртка `<pre class="log-code break-all"><code>` (`:2520`) — СОХРАНИТЬ дословно**
  (маркер `test_webapp_tma_fixes_ui.py:26`); переопределить перенос точечно:
  `.log-panel .log-code { word-break: break-word; }` (специфичность 0,2,0 перекрывает Tailwind
  `.break-all` 0,1,0).
- exc-трейс (`:2533`, `.log-exc`) и `@click.stop` expander (`:2524-2526`) — не ломать.

**AC-3b:** level и дата фиксированной ширины (не «прыгают»); последняя текстовая колонка
`flex:1` и корректно переносится; длинные строки не выходят за панель; клик-копирование и
разворот стека работают.

**Тест-подход:** Python-маркеры: `"log-level"`, `"log-ts"`, `"log-msg"`, `"word-break: break-word"`
в HTML; существующий маркер `'<pre v-else class="log-code break-all"><code>'` зелёный.
Ручной чек long-line на 360 px.

---

### 3c. Копирование лога по клику + визуальный отклик

**Root cause:** копирование по клику уже есть (`index.html:2521-2522`
`@click="copyText(logText(log))"`), но нет transient-подсветки строки (только toast).
`copyAllLogs` (`web/app.js:3329`) использует `this.logs.map(this.logText)` — latent context-loss
(Vue биндит методы, `logText` не использует `this`, поэтому не ломается; но хрупко).

**Точный фикс:**
- **`web/app.js` data:** добавить `copiedIndex: null`, `copiedTimer: null`.
- **`web/app.js` methods:** добавить `copyLogRow(log, i)`: формирует `logText(log)`,
  вызывает `copyText(...)`, ставит `this.copiedIndex = i`, сбрасывает через `setTimeout(..., 800)`
  (очищать предыдущий таймер); по успеху — toast «Скопировано» (уже в `copyText`).
- **`web/app.js::copyAllLogs` (`:3328-3330`):** заменить на явную привязку:
  `var self = this; this.copyText(this.logs.map(function (l) { return self.logText(l); }).join('\n\n'));`
- **`web/index.html:2521-2522`:** `@click="copyText(logText(log))"` →
  `@click="copyLogRow(log, i)"`; `:class="{ 'log-copied': copiedIndex === i }"`.
  → **обновить маркер** `tests/test_webapp_tma_fixes_ui.py::test_log_row_click_copies`
  на `@click="copyLogRow(log, i)"` (осознанное обновление, MED-022).
- **CSS:** `.log-copied { background: rgba(20,203,182,.18); transition: background .15s ease; }`
  (+ `prefers-reduced-motion` не критично).
- Оставить `title="Клик — копировать строку"`; тост при ошибке — «Не удалось скопировать».

**AC-3c:** клик по строке копирует и даёт видимый отклик (подсветка строки + toast);
«Копировать всё» работает без context-loss; ошибка копирования → понятный тост; expander
(`@click.stop`) не конфликтует.

**Тест-подход:**
- JS: в `routing_test.js` вызвать `methods.copyLogRow.call(stub, log, 2)` и проверить
  `stub.copiedIndex === 2` (стаб с `copyText`).
- Python-маркеры: `"copyLogRow(log, i)"`, `"log-copied"` в HTML; `copyAllLogs` содержит
  `self.logText` или явный `function`.
- Обновить `test_log_row_click_copies` (см. выше).

---

### R106-5. Мёртвые записи `ICONS` (дешёвое закрытие, P2)

**Root cause:** после удаления вкладок остались Material-ключи без вызовов:
`speed` (`web/app.js:228`), `theater_comedy` (`:231`), `toggle_off` (`:232`),
`toggle_on` (`:233`), `stop_circle` (`:229`), `account_balance_wallet` (`:208`).
Проверено grep: строк `'<key>'`/`iconGlyph('<key>')` — 0; в `TAB_ICON`/`NAV_ITEMS` они не
используются. Шрифт-субсет/PUA-канон не пересобирается (это карта в JS, не cmap).

**Точный фикс:**
- Удалить 6 мёртвых записей из `var ICONS = { ... }` (`web/app.js:207-234`).
- **`tests/test_font_subset.py:73`** (`assert "'\\ue850'" in js` для `account_balance_wallet`)
  перевести на существующую иконку, оставшуюся в `ICONS`, — например `help` (`'\ue887'`),
  чтобы проверка PUA-рендера сохранилась.
- Никаких иных правок `ICONS`/`TAB_ICON`/`NAV_ITEMS` (26→20 ключей; тест `var ICONS = {` жив).

**AC-R106-5:** в `ICONS` нет ключей без использования; `test_font_subset` зелёный; визуально
иконки не изменились.

**Тест-подход:** `pytest tests/test_font_subset.py`; grep-проверка отсутствия 6 ключей.

---

## 3. Parity / no-functional-loss (обязательно)

- **1a:** семантика scope не меняется — те же вычисления, но реактивные; RBAC-фильтр
  `accessChats` (серверный) не ослабляется; «Весь бот» остаётся только у global admin.
- **1b/1c/1d/3b:** чисто визуальные/CSS-правки; ни один элемент/обработчик/a11y-атрибут не удаляется.
- **2a:** меняется только таблица ключей (`.keys-avail`); матрица ролей и прочие таблицы — байт-в-байт поведение.
- **2b:** контракт `/api/status` (ключи `buckets/ts/status/last_heartbeat/since/until/generated_at`)
  сохраняется; меняется **наполнение** `buckets` (gap-fill) и точнее `last_heartbeat`; leak-safety
  OD19/`key_history` не затронуты; ноль PG-DDL; SQLite остаётся v8; `uptime_heartbeat` не дифается.
- **3a/3c:** копирование продолжает работать в обоих путях (Clipboard API / execCommand-fallback);
  ghost больше не персистится.
- **R106-5:** удаление только мёртвых ключей; ни один используемый глиф не удаляется.

---

## 4. Инварианты и гейты (QA)

- **pytest:** baseline **5027 passed / 0 failed**; допустимы **осознанные обновления** тестов,
  перечисленные выше (2b `last_heartbeat`; 3c `test_log_row_click_copies`; R106-5 `test_font_subset`).
  Дополнительно (10.7, ревью): `tests/test_webapp_avatars_ui.py::_Static.body` — хелпер теперь
  матчит определение `<name>:[ \t]*(async )?function` вместо первого `<name>:` (после переноса
  `scope*` в `computed` поле `avatarUrl:` встречается внутри `scopeOptions` раньше метода
  `avatarUrl`); `tests/test_webapp_round107_ui.py::test_ghost_focusable_and_isolated` фиксирует
  **отсутствие** `visibility:hidden` у `.clipboard-ghost` (DEF-1).
  Любое иное падение — регресс.
- `node --check web/app.js` — clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`
  (+ новые ассерты 1a/3a/3c); `git diff --check` — clean.
- Каталог-эталон не меняется: **REGISTRY 392 / GROUPS 91 / Settings 364** (10.7 каталог не трогает).
- Ноль новых PG-DDL; SQLite v8; `bot.py` не тронут; `media/` не тронут; R16/R17; секретов в коммите нет.
- Маркер-тесты фронта, которые могут смотреть в затронутые строки, проверить и при необходимости
  аккуратно обновить: `test_frontend_tab_mapping.py`, `test_round106_ia_smoke.py`,
  `test_webapp_nav_disclosure_ui.py`, `test_webapp_hubs_matrix_ui.py`,
  `test_webapp_key_availability_ui.py`, `test_webapp_tma_fixes_ui.py`,
  `test_webapp_status_control.py`, `test_webapp_back_button.py`.

---

## 5. Открытые вопросы / неопределённость (owner input)

1. **3a — идентификация фантомного узла на живом устройстве.** Статически единственный
   runtime-inject — `.clipboard-ghost`; просим @Builder подтвердить в DevTools Elements и
   зафиксировать в отчёте. Если узел иной — дефект всё равно чинится через изоляцию ghost,
   но отчёт должен содержать идентификацию.
2. **2b — семантика `last_heartbeat`.** Предлагаем «ts последнего `up`-бакета, иначе `None`»
   (точнее), с обновлением 1 теста. Если владелец хочет строго обратную совместимость —
   оставить `buckets[-1].ts` и не менять тесты (тогда поле будет означать «последний слот окна»).
3. **1d — выбор поведения для слишком длинных подписей.** Спека выбирает **контролируемые 2 строки
   с переносом по словам** (а не nowrap+ellipsis), т.к. 6 пунктов на ≈360 px иначе обрежутся.
   Если владелец предпочитает строго одну строку с ellipsis — заменить клампп на
   `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` (поведение единое mobile+desktop).
4. **R106-5 — `account_balance_wallet`** завязан на `test_font_subset`; спека переводит
   PNG-проверку на `help`. Если удаление всех 6 ключей признано нежелательным — можно оставить
   `account_balance_wallet` и удалить только 5 (минимальный риск-нулём тест-правок).

---

## 6. Handoff

1. **@Builder** — P0: 1a, 1b, 2a, 2b, 3a → P1: 1c, 1d, 3b, 3c → P2: R106-5 (и опц. T-1234).
2. **@DevOps** — T-1236/T-1237/T-1238: полный pytest (0 регрессий) + `node --check` + JS-тесты,
   русский conventional-commit, push, деплой, live-smoke (скриншоты «до/после» 1b/1c/1d/2a/3b).
3. **@Scanner** — T-1240: пост-билд аудит (`plans/reports/round10.7_scanner_audit.md`).

> Root-cause 1a и 2b подтверждены уликами; 1a верифицирован прогоном под Vue-стабом.
> Спека не содержит реализации — только точный фикс-план, AC и тесты.
