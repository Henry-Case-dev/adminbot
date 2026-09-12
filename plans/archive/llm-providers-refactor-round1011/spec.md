# Spec — llm-providers-refactor-round1011 (раунд 10.11)

> **Фича:** `plans/features/llm-providers-refactor-round1011/` · **Раунд 10.11** ·
> создано @Architect 12.09.2026 (Step 2). **Код не пишется** — только ТЗ.
> **Вход:** `plans/current_task.md` (ТЗ, пп.1–4), `tasks.md` (@PM Step 1, file:line),
> `plans/reports/round10.10_scanner_audit.md`, `plans/reports/audit_backlog.md`,
> `plans/archive/admin-ui-round1010/{spec.md,ADR-1010-2.md}`.
> **Область этого spec:** пп. **1, 2 (2.1–2.5), 3**. П.4 — отчёт без кода (сделан).
> **ADR:** ADR-1011-1 (п.1, R17), ADR-1011-2 (п.2.3, Δ каталога), ADR-1011-3 (п.3, ось X).

---

## 0. Инварианты (проверять на Step 7)

- **Ноль новых PG-DDL** (`CREATE/ALTER/ADD COLUMN/DROP`) — только DML/каталог.
- **SQLite v8** (`_SCHEMA_VERSION_AGI_MEMORY == 8`); `services/database.py` не трогать.
- **`bot.py` router order не тронут** (и `bot.py` вообще не менять).
- **`media/`** и **`.env`** не трогать; секреты не коммитить (R17).
- **Каталог-инвариант счётчиков:** REGISTRY **400** / GROUPS **90** / Settings **372**
  / mapped (`_TAB_BY_GROUP`) **88** / `TAB_RULES` 19 / `CONFIG_TAB_TITLES` 19.
  П.2.3 — **sanctioned Δ без роста счётчиков** (перенос 4 записей, см. §2.3).
- **R17:** реальные секреты не появляются в DOM/сети/логах; в UI только
  `{configured,last4}`.
- **MINOR-3 (`saveBlock`):** `draft == null` = «не трогать», `draft === ''` = «очистить» —
  не менять.
- **ADR-1010-2:** `api_payload` `/api/status/key-history` неизменен; сетка 300с,
  дорожки, окно-от-конца наследуются.
- Baseline: **5145 passed / 1 skipped / 0 failed**; `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Feature flag не требуется** (UI + аддитивные серверные fallback'и; rollback =
  `git revert`, миграция каталога идемпотентна).

### 0.1 Учёт @Scanner (mandatory)

Прочитан `plans/reports/round10.10_scanner_audit.md` (0 blocker/0 major/0 medium;
low: R10.10-1/-2/-3, info: R10.10-4/-5) и `audit_backlog.md`.

- **R10.10-3** (`renderKeyHistoryChart` early-return без `destroy`) — **уже закрыт**
  в 10.10 (`web/app.js:3547-3556`). П.3 обязан **не регрессировать**: во всех ветках
  `renderKeyHistoryChart` старый чарт уничтожается до возможного `return`; добавить
  регресс-тест.
- **R10.10-1/-2** (операторский вывод/noop DM-скрипта) — вне UI-скоупа 10.11;
  follow-up @DevOps, не блокирует.
- **R10.10-4/-5** (аватары/`adminInitial` в «Ролях») — вне скоупа 10.11.
- Иных blocker/major, пересекающихся с пп.1–3, в backlog нет.

---

## 1. Пункт 1 — поле ключа провайдера + «Проверить» (ADR-1011-1)

### 1.1 Root cause (evidence)

- `PROVIDER_BLOCKS` (`web/app.js:369-441`): поля-секреты `secret:true`
  (`:375,383,390,398,406,431-434,438`).
- `blockFieldValue(f)` (`web/app.js:2047-2054`): при отсутствии черновика и
  `configItems[key].value` — объект-маска (`{configured,last4}`) → возвращает `''`
  (условие `:2052` пропускает `typeof object`).
- `blockFieldPlaceholder(f)` (`:2055-2061`) → `configured ••••last4` / `не настроен`.
- `testBlock` (`:2062-2090`): `body.api_key` кладётся только если value truthy
  (`:2071`), поэтому уходит `api_key: ''`.
- `testField` (`:2092-2117`): `api_key: this.blockFieldValue(f)` → тоже `''`.
- Бэкенд: `LlmTestRequest.api_key = ""` (`web/api/routes.py:127-132`);
  `post_llm_test` (`routes.py:1243-1264`) → `probe_block`;
  `probe_openai` при пустом ключе возвращает `not_configured, "ключ не задан"`
  (`services/llm_probe.py:144-145`).
- Секрет на выдаче маскируется: `_mask_secret` (`routes.py:194-203`),
  config-output (`routes.py:300-301`).
- **Root cause подтверждён:** фронт шлёт `''`; бэкенд не подставляет сохранённый ключ.

### 1.2 Точный фикс

**A. Бэкенд-резолв сохранённого ключа (источник истины).**
`services/llm_probe.py`:
- добавить карту `_BLOCK_SAVED_KEY: dict[str,str]`:
  `direct_main→keys.llm_api_key`, `direct_fallback→keys.llm_fallback_api_key`,
  `transcribe_groq→keys.groq_api_key`,
  `transcribe_openrouter|video_summary_openrouter|video_fallback→keys.openrouter_api_key`,
  `embeddings|embeddings_main→keys.llm_api_key`,
  `embeddings_fallback1→keys.embedding_fallback_api_key`,
  `embeddings_fallback2→keys.embedding_fallback_api_key_2`,
  `search_keys:tavily→keys.tavily_api_key`, `search_keys:exa→keys.exa_api_key`,
  `media_share→keys.media_share_secret`;
- helper `_saved_api_key(block)`: ленивый `from services import hot_config` +
  `from services.param_catalog import get_by_pg_key` + `settings`;
  `pg_key = _BLOCK_SAVED_KEY.get(block)`; `default = getattr(settings, spec.settings_field, "")`;
  `return hot_config.get(pg_key, default) or ""`;
- в `probe_block` (`llm_probe.py:178`), сразу после проверки `KNOWN_BLOCKS`
  (`:195-196`) и **до** ветки `media_share`: `if not (api_key or '').strip(): api_key = _saved_api_key(block)`.
- R17: резолв только внутренний; ошибки санитизируются существующим
  `sanitize_error` (`:45-53`); ключ не логируется/не возвращается.

**B. Новые block-id для эмбеддингов/видео** (нужны п.2.3/2.4, но резолв — здесь):
- `_EMBEDDING_BLOCKS` (`:34`) += `embeddings_main`, `embeddings_fallback1`,
  `embeddings_fallback2`; `_LLM_BLOCKS` (`:29-32`) += `video_fallback`;
- `KNOWN_BLOCKS` (`:37-40`) автоматически расширяется через объединения.
- `probe_block` для этих id использует `kind="embeddings"`/`"chat"` как обычно.

**C. UI (R17-безопасно, без сырого ключа).**
- `web/app.js`: новый helper `blockFieldConfigured(f)` → `true`, если
  `configItems[f.key]` — объект с `configured:true`.
- `web/index.html:801-825`: под секретным полем добавить строку-подсказку
  `v-if="f.secret && blockFieldConfigured(f)"`:
  «Ключ сохранён (••••{{ last4ByKey(f.key) }}) — можно проверить без ввода».
  (Новый helper `last4ByKey(key)` или переиспользование `last4(item)`; без новых
  компонентов.)
- `:value="blockFieldValue(f)"` и `placeholder` **не менять** (сырой ключ не в DOM).
- `testBlock`/`testField` можно оставить как есть (шлют `''`) — бэкенд резолвит.
  **Опционально:** не отправлять `api_key`, если он пуст; не обязательно.

**D. `media_share`** — тот же механизм: сохранённый `keys.media_share_secret`
резолвится при пустом `api_key` (`probe_block` ветка `:198-202`).

### 1.3 Acceptance criteria

- При сохранённом ключе нажатие «Проверить» **без ввода** → `ok=true` либо валидный
  ответ провайдера; **не** «ключ не задан».
- При отсутствующем ключе поле пустое, «Проверить» даёт ожидаемую ошибку.
- R17: реальный секрет не появляется в DOM/сети/логах; в UI — маска+hint.
- `saveBlock` MINOR-3 не сломан.
- `media_share` ведёт себя так же.

### 1.4 Тесты

- `tests/test_webapp_api.py::TestLlmTestEndpoint` — новый кейс:
  `POST /api/llm/test` с `api_key:""` и подложенным в `hot_config`/каталог
  сохранённым `keys.llm_api_key` → `probe_block` получает непустой ключ
  (monkeypatch `probe_block`, проверить 4-й аргумент); ключ не в ответе (R17).
- `tests/test_round106_ia_smoke.py` — `probe_block("media_share","","","")` без
  ключа остаётся `not_configured` (в тест-окружении settings пуст).
- `tests/js/routing_test.js` (`testBlock`) — при пустом `blockFieldValue` у секрета
  `body.api_key` остаётся пустым/не задано (бэкенд-резолв), при заданном драфте —
  уходит драфт.
- Маркеры в `test_webapp_round1010_ui.py`: `:value="blockFieldValue(f)"` сохранён;
  hint-строка присутствует.

### 1.5 Parity note

Изменение аддитивное (fallback только при пустом ключе). Серверный контракт
`/api/llm/test` (поля/коды 200/403/429) не меняется. Rollback = `git revert`.

---

## 2. Пункт 2 — рефакторинг «LLM Провайдеры» + навигация

### 2.0 Целевая модель `PROVIDER_BLOCKS` (единый источник)

К существующему массиву (`web/app.js:369-441`) добавляются поля:
- `zone: 'advanced'` (опц.; по умолчанию — зона «Подключения»);
- `note: string` (опц.; человеческий subtext блока);
- `subBlocks: [{id,title,note?,fields[]}]` (опц.; используется `embeddings`).

Итоговый порядок/зоны:

| # | id | Зона | Поля (роли) |
|---|---|---|---|
| 1 | `direct_main` | Подключения | как есть |
| 2 | `direct_fallback` | Подключения | как есть |
| 3 | `transcribe_groq` | Подключения | как есть |
| 4 | `transcribe_openrouter` | Подключения | как есть |
| 5 | `video_summary_openrouter` | Подключения | как есть |
| 6 | `video_fallback` | Подключения (NEW) | Название/URL/Модель/Ключ |
| 7 | `embeddings` | Подключения (RESTRUCTURED) | 3 подблока |
| 8 | `llm_guard` | advanced | как есть |
| 9 | `search_keys` | advanced | как есть |
| 10 | `media_share` | advanced (+`note`) | как есть |

`providerCoveredKeys` (`web/app.js:2663-2669`) обязан **рекурсивно** обходить
`subBlocks[].fields`, чтобы generic-рендер не дублировал поля.

### 2.1 Шапка, навигация, центрирование карточек

**Root cause (evidence):** `.nav-icon` 18px (`web/index.html:215`); плотность
`.navbar-band`/`.nav-link` (`:204-214`); `min-width:72px` (`:229`); профиль
`ml-auto` без `shrink-0` (`:712-727`); hub-сетка `auto-fill minmax(240px,1fr)`
(`:248-251`) не центрируется и тянется на всю ширину `main`
(`:757-758`, `repeat(auto-fill,minmax(320px,1fr))`).

**Точный фикс (`web/index.html`, только CSS/классы):**
- `:215` `.nav-link .nav-icon { font-size: 18px }` → **22px**.
- `:205` `.navbar-band { gap: .25rem }` → **`.15rem`**; `:211`
  `.nav-link { padding: .25rem .1rem }` → **`.15rem 0`**; `:229`
  `@media(min-width:992px) .nav-link { min-width: 72px }` → **60px**.
  **Не трогать** `.nav-label` (`:218-223`, 2-строчный clamp — 10.7-регресс).
- `:712` профильный блок: добавить `shrink-0`; ник `:719` — добавить
  `whitespace-nowrap` (уже `truncate max-w-[7rem]`); аватар `:716-718` — `shrink-0`
  уже есть.
- Центрирование карточек: `.hub-head`/`.hub-grid` (`:245-251`) →
  `width:100%; max-width:64rem; justify-self:center;`; `.hub-grid`
  `minmax(240px,1fr)` → **`minmax(220px,1fr)`**; `@media(max-width:479px)`
  `.hub-grid{1fr}` (`:296`) сохранить. `main`-grid **не менять** (общий для всех
  вкладок; избегаем регрессий).
- `providerBlocks` уже `max-w-3xl mx-auto w-full` (`:795`) — сохранить.

**AC 2.1:** иконки крупнее и плотнее; подписи ≤2 строки без обрезки; профиль не
уезжает ни на одном маршруте и в fullscreen (safe-area 10.10 `:630-634` не
регрессирует); сетка карточек центрирована и адаптивна (desktop fullscreen +
mobile).

### 2.2 Две зоны: «Подключения» и «Расширенные настройки»

**Root cause:** все блоки + generic-группы рендерятся одной простыней
(`web/index.html:794-842` + generic `:879-1143`); техпараметры перемешаны с
подключениями.

**Точный фикс:**
- `web/app.js`: computed `providerConnectionBlocks` (`zone !== 'advanced'`) и
  `providerAdvancedBlocks` (`zone === 'advanced'`).
- `web/index.html:794`: connections-зона рендерит `v-for="b in providerConnectionBlocks"`
  (существующая разметка `:795-841` без изменений).
- **Advanced-зона:** `<details>` (closed по умолчанию, персист через
  `expandOpen(activeTab)`/`toggleExpand`), содержащий:
  1. advanced provider-блоки (`providerAdvancedBlocks`) той же разметкой;
  2. residual generic-группы для `llm_providers` (`currentTabGroups`).
  Реализация без нового компонента: обернуть существующий
  `<template v-for="grp in currentTabGroups">` (`:879`) в
  `<component :is="activeTab==='llm_providers' ? 'details' : 'div'"
  :open="activeTab==='llm_providers' ? expandOpen(activeTab) : null">`
  с `<summary v-if="activeTab==='llm_providers'">▶ Расширенные настройки (N)</summary>`.
  (Тот же приём `:is`, что у owner-блоков `:894`.)
- `web/app.js:32-42`: убрать `sections` у `llm_providers` (заголовок зоны теперь
  summary; избегаем дублей «Расширенные»); `sectionTitle()` уже null-safe
  (`:2815-2817`).

**AC 2.2:** сверху видны только подключения моделей; все техпараметры — внизу под
спойлером; нет дублей полей (`providerCoveredKeys`); каталог не меняется.

### 2.3 «Эмбеддинги»: 1 блок = 3 подблока + фоллбэки с полными инпутами (ADR-1011-2)

**Root cause (evidence):**
- Блок `embeddings` (`web/app.js:408-417`): только display/model/dim,
  `testable:false`, нет `base_url`/`api_key`.
- Реальные фоллбэк-`base_url`/`model`/`keys` лежат в `_INFRA`
  (`services/param_catalog.py:429-436`, `category=None`) → **в UI не приходят**;
  в каталоге только display-name (`:560-563`).
- Runtime `llm_client` читает их напрямую из settings (`services/llm_client.py:292-303`),
  `status_service` — тоже (`:257-278`).

**Точный фикс:**
- **Каталог (sanctioned Δ без роста счётчиков):** перевести из `_INFRA` в каталог:
  - `models.embedding_fallback_base_url` (models / `models_embeddings`)
  - `models.embedding_fallback_model` (models / `models_embeddings`)
  - `keys.embedding_fallback_api_key` (keys / `keys_llm`, secret)
  - `keys.embedding_fallback_api_key_2` (keys / `keys_llm`, secret)
  `EMBEDDING_FALLBACK_TIMEOUT_SECONDS`/`_MAX_RETRIES` остаются infra.
- **Read-path:** `services/llm_client.py:292-299` и `services/status_service.py:257-278`
  → `hot.get(<pg_key>, settings_default)` (дефолт = текущий settings → паритет).
- **UI-модель:** один provider-блок `embeddings` с `subBlocks`:
  - «Основная модель»: `models.embedding_display_name` (Название),
    `models.llm_base_url` (Адрес, shared с `direct_main`),
    `models.embedding_model_name` (Модель), `keys.llm_api_key` (Ключ);
    test id `embeddings_main`.
  - «Фоллбэк 1»: `models.embedding_fallback_display_name`,
    `models.embedding_fallback_base_url`, `models.embedding_fallback_model`,
    `keys.embedding_fallback_api_key`; test id `embeddings_fallback1`.
  - «Фоллбэк 2»: `models.embedding_fallback2_display_name`,
    `models.embedding_fallback_base_url` (shared с Ф1),
    `models.embedding_fallback_model` (shared с Ф1),
    `keys.embedding_fallback_api_key_2`; test id `embeddings_fallback2`;
    `note`: «Адрес и модель общие с „Фоллбэк 1"».
- **Рендер:** в index.html для `b.subBlocks` — заголовок подблока + те же строки
  полей + кнопки «Сохранить»/«Проверить» **на подблок** (`saveBlock(sb)`,
  `testBlock(sb)` уже работают: у `sb` есть `id`+`fields`). `dim` уходит из блока
  в «Расширенные» (см. 2.5).
- **Saving:** `saveBlock` не менять по семантике; вызывается с подблоком.

**AC 2.3:** ровно 3 подблока в одном визуальном блоке; у всех трёх Base URL +
Модель + Ключ + «Проверить»; значения фоллбэков сохранены; generic-дублей нет.

### 2.4 «Видео-модели»: запасная модель наверх, без хардкода

**Root cause (evidence):** основной блок `video_summary_openrouter`
(`web/app.js:400-407`); запасная модель `VIDEO_FALLBACK_MODEL` — уже **каталожный**
параметр (`services/param_catalog.py:544-545`, группа `models_video_summary`,
дефолт `config/settings.py:881` `minimax/minimax-m3:free`), но рендерится
generic-группой ниже, отдельно от блока. «Хардкод» = дефолт в settings, который
редактируется только через далёкую generic-группу. Runtime использует её
(`services/youtube_summarizer_service.py:102-103,255-256`).

**Точный фикс:**
- Новый provider-блок `video_fallback` **сразу после** `video_summary_openrouter`:
  - `models.openrouter_display_name` (Название),
  - `models.openrouter_base_url` (Адрес),
  - `models.video_fallback_model` (Модель),
  - `keys.openrouter_api_key` (Ключ).
- Добавить `video_fallback` в `_LLM_BLOCKS` (`services/llm_probe.py:29-32`).
- **Каталог-Δ нет:** `models.video_fallback_model` уже существует; display/url/key
  переиспользуются у OpenRouter-провайдера. Дефолт в `settings.py:881` сохраняется
  как code-fallback (не «хардкод UI»).
- Generic-группа `models_video_summary` теряет этот ключ (остаётся
  `VIDEO_TIMEOUT_SECONDS`) → «Расширенные».

**AC 2.4:** запасная модель строго под основной, полный набор полей, редактируема
из UI, текущее значение не потеряно; generic-дубля нет.

### 2.5 «Расширенные настройки» + «Медиа-шара»

**Root cause:** `media_share` — provider-блок в основной зоне
(`web/app.js:436-440`); техпараметры (`llm_guard`, `search_keys`) в основной зоне;
generic-группы рендерятся простыней.

**Точный фикс:**
- `media_share` → `zone:'advanced'`, добавить
  `note`: «Секретный токен для авторизации бота при скачивании медиафайлов из
  закрытых источников». Рендерить `b.note` под заголовком блока (мелким серым).
- `llm_guard` → `zone:'advanced'`; `search_keys` → `zone:'advanced'`.
- В advanced-спойлере (2.2) собираются все residual generic-группы:
  `models_llm_timeouts` («Таймауты и повторы»),
  `models_llm_guard` («Бюджет и защита от сбоев» / Circuit Breaker),
  `models_extra_providers` (лимиты Groq/OpenRouter),
  `models_video_summary` (таймаут видео),
  `models_embeddings` («Отпечатки текста»: `EMBEDDING_DIM`, `TOKENIZER_ENCODING`,
  `TOKEN_SAFETY_MULTIPLIER`).
- Из основной зоны подключений техпараметры полностью убираются.

**AC 2.5:** «Медиа-шара» внизу с понятным описанием; весь теххаос строго внизу;
сверху — только подключения.

---

## 3. Пункт 3 — график «История доступности ключей» (ADR-1011-3)

### 3.1 Root cause (evidence)

- `keyHistoryChartModel` (`web/app.js:3473-3545`): сетка `SAMPLE_BUCKET=300`
  (`:196`), `MAX_HISTORY_POINTS=288` (`:194`), `MIN_BUCKETS=12` (`:197`); пропуск =
  `null`; `stepped:true` уже есть (`:3533`), но **`spanGaps:false`** (`:3536`) →
  линия рвётся на разреженных данных (наблюдаемые «чёрточки»).
- `renderKeyHistoryChart` (`:3546-3590`): `type:'line'`; `scales.x` —
  **категориальная** (labels `HH:MM`, `:3509-3513`), не `time`/`linear`.
- Библиотека Chart.js 4 (CDN `web/index.html:3040`), date-adapter не подключён.
- Данные/контракт корректны: `services/key_history.py` (allowlist, ring 288×300с),
  `api_payload` (`:196-203`), роут `web/api/routes.py:1109-1121` — **не менять**
  (ADR-1010-2).
- R10.10-3 уже закрыт: `:3547-3556` уничтожает старый чарт до `return`.

### 3.2 Точный фикс (render-only, `web/app.js` + `web/index.html`)

- **Сетку/окно/дорожки сохранить** (ADR-1010-2): `grid`, `MIN_BUCKETS`,
  окно-от-конца, `lane+0.75`/`lane+0.25`, `height=max(120,44+laneCount*22)`.
- `keyHistoryChartModel`: в датасете `data` — точки `{x: ts*1000, y: value|null}`
  (ms) по каждому бакету сетки; добавить `xMin = grid[0]*1000`,
  `xMax = grid[grid.length-1]*1000`. `steps`/`labels` можно сохранить для
  совместимости, но рендер идёт по точкам.
- `spanGaps: true` вместо `false` (`:3536`), `stepped: true` сохранить.
- `renderKeyHistoryChart` (`:3568-3586`):
  - `options.parsing = false`;
  - `scales.x = { type:'linear', min: model.xMin, max: model.xMax,
    ticks: { color:'#9CA3AF', maxTicksLimit: 6, font:{size:10},
    callback: function(v){ var d=new Date(v); return pad(d.getHours())+':'+pad(d.getMinutes()); } } }`;
  - `scales.y` и `legend`/`maintainAspectRatio:false` — без изменений.
- Если живой QA покажет, что `parsing:false` + `y:null` не даёт разрыва — emit
  только присутствующих точек (шаг всё равно «тянется» до следующей;
  `spanGaps:true` остаётся маркером AC). Решение Builder по итогам QA, зафиксировать
  в отчёте.

### 3.3 AC

- На разреженных данных — непрерывная ступенчатая линия, а не разорванные чёрточки.
- X — реальная временная шкала (пропорциональные интервалы, подписи времени).
- Пустое состояние (`providers==[]`/`samples==[]`) и `destroy` корректны (R10.10-3
  не регрессирует).
- Контракт `/api/status/key-history` (`api_payload`) **не изменён**;
  `maintainAspectRatio:false`/реактивная высота сохранены (Android WebView).

### 3.4 Отклонено

- `type:'time'` + date-adapter (новая CDN-зависимость, offline/TMA-риск).
- Смена серверного `api_payload` (плотная сетка) — запрещено ADR-1010-2.

---

## 4. Δ каталога (сводно)

**Текущие инварианты:** REGISTRY **400** / GROUPS **90** / Settings **372** /
mapped **88**; `TAB_RULES`/`CONFIG_TAB_TITLES` **19**.

**Sanctioned Δ (п.2.3), счётчики НЕ растут — перенос 4 записей `_INFRA` → каталог:**

| PG-ключ | from | to |
|---|---|---|
| `models.embedding_fallback_base_url` | `_INFRA` (category None) | models / `models_embeddings` |
| `models.embedding_fallback_model` | `_INFRA` | models / `models_embeddings` |
| `keys.embedding_fallback_api_key` | `_INFRA` | keys / `keys_llm` (secret) |
| `keys.embedding_fallback_api_key_2` | `_INFRA` | keys / `keys_llm` (secret) |

- НЕ добавляются новые ParamSpec/GroupSpec → **400/90/372/88/19/19 неизменны**.
- Read-path: `llm_client`+`status_service` → `hot.get` (значения по умолчанию = текущие).
- Деплой: идемпотентный `python scripts/migrate_env_to_pg.py --only-category models,keys`
  (без `--force`) — сид .env-значений секретов в PG (R17-mask в выводе). Non-secret
  `base_url`/`model` сидятся авто (`_seed_settings`).
- П.2.4 — **Δ каталога нет** (`models.video_fallback_model` уже существует).

---

## 5. Решения по открытым вопросам tasks.md §7

1. **OPEN-Q1 (2.1):** hub-карточки центрируются контейнером `max-width:64rem`
   (`justify-self:center`), `main`-grid не трогаем; provider-блоки остаются
   `max-w-3xl`. В fullscreen карточки растягиваются до max-width и центрируются;
   mobile — 1 колонка. 2.2-зоны не ломаются.
2. **OPEN-Q2 (2.3):** реальных ключей фоллбэков в каталоге нет — нужен **Δ
   каталога** (ADR-1011-2): 4 записи переводятся из infra в каталог **без роста
   счётчиков**, read-path на `hot.get`, миграция идемпотентна, значения сохраняются.
3. **OPEN-Q3 (2.4):** «хардкод» = дефолт `settings.VIDEO_FALLBACK_MODEL`
   (`config/settings.py:881`), рендерившийся далёкой generic-группой. Значение
   `minimax/minimax-m3:free` сохраняется как code-default; блок `video_fallback`
   использует существующий `models.video_fallback_model` + shared OpenRouter
   URL/ключ. Δ каталога нет.
4. **OPEN-Q4 (3):** X-ось — `type:'linear'` c `ts*1000` + `ticks.callback` (HH:MM);
   `parsing:false`; `spanGaps:true`; `stepped:true`. Без date-adapter (TMA/offline/
   perf). `api_payload` не меняется.
5. **OPEN-Q5 (1):** серверный резолв сохранённого ключа в `probe_block` при пустом
   `api_key`; фронт не раскрывает секрет; UI — маска + hint. Sentinel отвергнут.
6. **OPEN-Q6 (2.2/2.5):** «Поиск: ключи» (`search_keys`) — часть «Расширенных
   настроек» (техпараметр), `zone:'advanced'`.

---

## 6. Тесты / QA

1. **Статика:** `node --check web/app.js`; `git diff --check` (LF/CRLF-warnings — ок).
2. **JS-юниты (`tests/js/routing_test.js`):**
   - `keyHistoryChartModel` (`:586-660`) обновить осознанно: точки `{x,y}`,
     `xMin`/`xMax`, `spanGaps:true` (было `false` — тест `:618`),
     `stepped:true`, дорожки `0.75/1.25`, высота, «окно-от-конца» (сэмпл последний),
     пусто → `null`.
   - `blockFieldValue` (`:662-691`) — сохранить поведение (секрет → `''`).
   - `testBlock`/`testField`: при пустом секрете ключ не подставляется на фронте
     (резолв — бэкенд).
3. **Pytest:**
   - `test_webapp_api.py::TestLlmTestEndpoint` — резолв сохранённого ключа при
     `api_key:""` (monkeypatch `probe_block`), R17.
   - `test_llm_client.py` (embed-fallback `:620-741`) и `test_video_cascade.py`
     (`:560-580`) — зелёные (значения из kwarg/settings без кэша).
   - `test_migrate_env_to_pg.py:246,256` — **осознанно** 13 → **15** (2 ключа
     добавлены в категорию keys).
   - `test_round106_ia_smoke.py:339-351` (`provider_blocks_single_home`) —
     **осознанно** пересчитать `len(keys)`/`len(set(keys))` под новую модель
     (video_fallback + embeddings subBlocks). `:121` (`search_keys`/`media_share`
     в JS) и filter-маркеры сохранить.
   - `test_webapp_round1010_ui.py:180-184`, `test_frontend_tab_mapping.py:73-78`,
     `test_webapp_parity_smoke.py:48-52`, `test_webapp_round109_ui.py:208-212` —
     **каталог-счётчики остаются 400/90/372/88/19** (Δ их не двигает).
   - Новые маркеры (по образцу 10.9/10.10) для: `providerConnectionBlocks`/
     `providerAdvancedBlocks`, `subBlocks`, `zone:'advanced'`, `note`,
     `blockFieldConfigured`, hint-строка, `spanGaps: true`, `type:'linear'`,
     `parsing: false`, отсутствие `type:'time'`.
4. **R17-скан:** `git diff` grep `sk-|gsk_|AIza|xox|bot-token` — пусто.
5. **Live Android/Telegram (владелец/QA):** поле ключа + «Проверить» без ввода;
   nav/профиль/сетка; две зоны; эмбеддинги (3 подблока); видео-фоллбэк; media-share
   внизу; график.
6. **Деплой:** `git pull --ff-only` → при необходимости
   `python scripts/migrate_env_to_pg.py --only-category models,keys` (идемпотентно) →
   `systemctl restart admin_bot` → health 200, 0 ERROR.

---

## 7. Риски

- **R1:** Δ каталога п.2.3 — митигация: счётчики не растут, значения сохраняются,
  миграция идемпотентна (прецедент OD11).
- **R2:** п.1 — риск раскрыть секрет/сломать MINOR-3 — митигация: ADR-1011-1,
  серверный резолв, ревью, R17-скан.
- **R3:** рефакторинг 2.1–2.5 может регрессировать маркеры 10.7–10.10 — митигация:
  сохранять `data-*`-маркеры/селекторы, прогонять маркерные тесты.
- **R4:** `parsing:false`+`y:null` в Chart.js 4 — митигация: fallback на sparse
  points (ADR-1011-3 §Решение/5).

---

## 8. Открытые вопросы к владельцу (owner decisions)

1. **п.1 / R17 (главное):** показ **сырого ключа** в поле противоречит R17 —
   @Architect выбирает безопасный путь (маска + hint + серверный резолв), а не
   буквальный показ. **Нужен явный апрув владельца** именно этого компромисса.
2. **п.2.3 / Δ каталога:** апрув перевода 4 embed-fallback записей из infra
   (category None) в каталог (модели/ключи) — счётчики не растут, значения
   сохраняются, обязателен деплой-шаг идемпотентной миграции.
3. **п.2.3 / shared base_url+model:** согласиться, что «Фоллбэк 1» и «Фоллбэк 2»
   делят адрес/модель (как сейчас в рантайме), а отдельный провайдер на фоллбэк 2 —
   вне скоупа.
4. **п.2.4:** согласиться, что `VIDEO_FALLBACK_MODEL` остаётся code-default
   (`minimax/minimax-m3:free`) при пустом значении в PG (значение не теряется).

---

## 9. Handoff

`@Orchestrator Architecture phase complete, passing the baton.`
Вызовы: @Builder (пп.1–3 по этому spec), @Reviewer, @Scanner, @DevOps.
