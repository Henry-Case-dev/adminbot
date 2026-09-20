# spec.md — F0 `f0-config-bugfixes-round1025` (P0, Wave 0)

> **Раунд 10.25 · Эпик 1 · Приоритет P0 · Wave 0 (обязательна ДО F1)**
> **ТЗ:** `plans/current_task.md` ЧАСТЬ I §1–§6 + §10 + «КРИТИЧЕСКОЕ ОБНОВЛЕНИЕ» (F0.5), результаты §54.
> **Задачи:** T-2410…T-2455 (`tasks.md`). **ADR:** `adr-1025-2-save-state-machine.md` (F0.1/F0.2),
> `adr-1025-3-anticliche-semantics.md` (F0.3), `adr-1025-4-toasts-savebar.md` (F0.4),
> `adr-1025-5-db-lock-resilience.md` (F0.5, AMEND ADR-1024-18).
> **Baseline:** HEAD `da561bc`; pytest **7911/0**; SQLite `user_version=12`; APP_VERSION **2.58.0**;
> каталог REGISTRY **459** / GROUPS **98** / `_TAB_BY_GROUP` **96**.
> **R17/R18:** секретов в документах нет; `plans/current_task.md` untracked — **не коммитить и не цитировать**.
> **Секреты наружу** — только `{configured,last4}` (`web/api/routes.py:265-274`).

## 0. Цель, скоуп, инварианты

**Цель.** До начала каркасных работ (F1) устранить 4 P0-дефекта конфигурации и 1 прод-деградацию БД:

- **F0.1** — честная диагностика и устранение первопричины 409 при сохранении Fallback; единая state-machine формы; контракт честного 409 (§2).
- **F0.2** — аудит **всех** механизмов сохранения циклом `load→edit→save→re-read→compare`; единый канонический write-path (§3).
- **F0.3** — исправление «20 вместо 200» + ложной «Ошибка модели»; разведение семантики capacity vs per-run; пакетное пополнение; события (§4).
- **F0.4** — одно итоговое уведомление на операцию; безопасные тосты (safe area, очередь); SaveBar (§5).
- **F0.5** — распространение контракта ADR-1024-18 (PRAGMA-паритет + bounded retry + явный лог исчерпания) на main write-path `database.py` и `self.db.db` (прод-лог 20.09.2026, §5 «КРИТИЧЕСКОГО ОБНОВЛЕНИЯ»).

**Жёсткие инварианты F0.**

| Инвариант | Требование |
|---|---|
| **Δ DDL = 0** | SQLite остаётся `user_version=12`; нет миграций/новых таблиц (в т.ч. F0.5) |
| **Δ каталога = 0** | REGISTRY/GROUPS/`_TAB_BY_GROUP` не меняются; kill-switch'и — env-only `ClassVar` |
| **Сохранность значений** | все параметры/промпты/модели/ключи сохраняются; тексты промптов не менять |
| **Дефолты** | не подставлять новые дефолты при открытии формы |
| **Scope** | локальное не перезаписывается глобальным и наоборот |
| **Fail-open — последний рубеж** | и только с обязательным структурированным логом/счётчиком |
| **Порядок роутеров** | `bot.py` не трогать |
| **CSP/zero-build** | Vue 3 global, без новых state-библиотек и inline-скриптов |
| **R17/R18** | секреты не логировать/не коммитить; `plans/current_task.md` не коммитить |

## 1. F0.1 — первопричина 409 и единая state-machine сохранения

### 1.1. Установленная первопричина (по коду, не гипотеза)

**Детерминированная первопричина: одно пользовательское действие порождает ДВЕ мутации одного профиля с одним и тем же optimistic-токеном.**

Механика (координаты):

1. `prompts.verbilizer_default_mode` — `per_chat=True` (категория `prompts`, не secret; `services/param_catalog.py:118-127`), т.е. сохраняется в `chat_profiles.chat_params` per-chat.
2. Дропдаун «Резервный режим (Fallback)» в шапке вкладки «Промпты» (V2): `web/index.html:479-487` `v-model="promptDefaultModeItem().value"` + `@change="savePromptFallbackMode()"`.
3. `savePromptFallbackMode` вызывает `this.saveConfigItem(item)` **без `await` и без guard на in-flight** — `web/app.js:4420-4427`.
4. Тот же `v-model` меняет `item.value` → элемент попадает в `dirtyItems` (`web/app.js:1616-1628`) → sticky SaveBar (`web/app.js:3164-3197`) отправит **тот же ключ повторно**.
5. Оба POST несут **один** токен `this.configChatUpdatedAt` (`web/app.js:5032`), который обновляется только после завершения первого POST внутри `saveConfigItem` (`web/app.js:5037`). Пока первый в полёте — второй берёт **устаревший** токен.
6. Сервер: `UPDATE ... WHERE chat_id=$1 AND updated_at=$3 RETURNING *` (`services/chat_params.py:UPDATE_PARAMS_LOCKED_SQL`, `set_chat_params`), 0 строк → `ChatParamsConflict` → HTTP **409** `{code:'conflict', current_updated_at}` (`web/api/routes.py:612-621`).
7. Три противоречивых сообщения в одном действии: `saveConfigItem` успех → `toast('Сохранено: …','ok')` (`web/app.js:5036`); обработчик 409 → `toast('Конфликт версии (409) — конфигурация обновлена','warn')` (`web/app.js:5040-5042`); `saveModalEdits` считает ключ провалом → `toast('Не сохранено (1): …','err')` (`web/app.js:3185-3188`).

**Вторичные причины (усиливают класс):**

- **RC-4 (ложный 409 на чужие ключи):** `updated_at` живёт на уровне **профиля** (`chat_profiles.updated_at`), поэтому конкурентная запись **любого** другого ключа того же чата инвалидирует токен (T-2413).
- **RC-5 (глобальный путь без версии и не атомарный):** `_post_config_global` (`web/api/routes.py:890-931`) пишет `cache.set` **по одному ключу в цикле** без optimistic-проверки → сбой в середине = частичная запись, конфликты не детектируются (T-2414).
- **RC-6 (слепая запись при null-токене):** `setActiveChat` обнуляет `configChatUpdatedAt=null` (`web/app.js:2220`) до завершения `loadConfig`; POST в этом окне уходит с `updated_at=null` → `set_chat_params` идёт по **не заблокированному** SQL (`chat_params.py:UPDATE_PARAMS_SQL`) → перезапись вслепую (потеря чужого изменения).
- **RC-7 (нет защиты от двойного тапа):** `saveConfigItem` делает `this.saving.add(key)`, но **не проверяет** наличие ключа; `saveModalEdits` защищён `stickySaving`, автосейв — нет (T-2417).

### 1.2. Контракт честного 409 (сервер)

`POST /api/config` (chat-scope, X-Chat-Id) и `POST /api/config` (global) — единый контракт исходов:

| Код | Тело | Когда |
|---|---|---|
| **200** | `{updated:[k…], revalidated:false, updated_at}` | обычный успех |
| **200** | `{updated:[k…], revalidated:true, updated_at}` | токен устарел, но на сервере **уже** запрошенное значение → операция признана выполненной (§2.3 п.5) |
| **409** | `{code:'conflict', current_updated_at, conflicting:[{key, your_value, server_value}], applied:[]}` | реальный конфликт: значения отличаются |
| **403/422/503** | без изменений | права/валидация/PG |

Правила сервера:

- **D-409-1 (idempotent short-circuit).** В `set_chat_params` при `expected_updated_at != None` и 0 строк UPDATE: прочитать текущий root; если по каждому ключу патча значение совпадает с запрошенным → вернуть **успех** (`revalidated=true`) с актуальным `updated_at`, **не** бросать `ChatParamsConflict`.
- **D-409-2 (serialize).** Мутации профиля сериализуются: in-process `asyncio.Lock` по `chat_id`; при нескольких воркерах — PG advisory-lock на `chat_id` (эквивалент). Одна операция = одна мутация.
- **D-409-3 (global atomic + version).** `_post_config_global` валидирует весь пакет **до** записи, затем пишет атомарно; optimistic — аддитивно (если клиент прислал `updated_at` для ключа, при несовпадении и совпадении значения → `revalidated`, иначе 409 `conflicting`). Глобальный ключ несовпадения версии без значения — 409.
- **D-409-4 (без бесконечных retry).** Клиент НЕ повторяет автоматически; после 409 один раз перечитывает и сравнивает.

### 1.3. Единая state-machine формы (§2.4)

Одно вычисляемое состояние формы (не набор независимых флагов):

```
saveState ∈ { loading | clean | dirty | saving | saved | error | conflict }
```

Правила перехода:

- `loading` — `configLoading`.
- `clean` — загружено, `dirtyItems+dirtyKeyItems == 0`, нет ошибок.
- `dirty` — есть локальные отличия от `configSnapshot`.
- `saving` — идёт операция (`stickySaving` ИЛИ любой `saving` ключ).
- `saved` — операция завершена, всё сохранено (переходит в `clean` после snapshot).
- `error` — операция завершилась ошибкой и **ничего** не сохранено.
- `conflict` — реальный 409 с непустым `conflicting[]`.
- **Частичный успех** — `saved`/`error` с обязательным результатом операции `{saved:[keys], failed:[{key, reason}]}`; запрещён одновременный «успех+ошибка» без объяснения частичного результата.

**Инварианты формы:**

- при `error`/`conflict` введённые значения **не сбрасываются** (черновик сохраняется; §2.3 п.2);
- `saveState` выводится из данных, а не выставляется вручную в разных местах;
- после успеха baseline (`configSnapshot`) сдвигается **только** если всё сохранено (S10.20-6).

### 1.4. Единый клиентский write-path (F0.1/F0.2, T-2417/T-2424)

Ввести **одну** точку сохранения:

```
persistItems(items, {reason}) -> OperationResult {saved:[], failed:[{key,reason}], state, revalidated}
```

- Все писатели (`saveConfigItem`, `saveBlock`, `saveKeyItem`, `saveModalEdits`, автосейв `selectPromptMode`/`savePromptFallbackMode`) ходят **только** через `persistItems`.
- **Guard in-flight по ключу:** `if (this.saving.has(key)) skip/queue` — двойной тап/idempotent.
- **Scope-split:** chat-элементы → один POST (X-Chat-Id, один токен); global-элементы → один POST без X-Chat-Id. Смешанный случай = 2 запроса, результат агрегируется в `OperationResult` (частичный успех отображается честно).
- **Токен:** перед chat-записью, если `configChatUpdatedAt == null` (только что сменили scope) — сначала дождаться/выполнить `loadConfig`, затем писать; null-токен в POST для chat-scope запрещён (закрывает RC-6).
- **409-recovery (§2.3):** при 409 не показывать успех; сохранить черновик; `GET /api/config`; сравнить `conflicting[]`; если сервер уже содержит запрошенное — операция «выполнена после проверки»; иначе показать конфликтующие поля; **без слепой перезаписи** и **без авто-цикла retry**.
- **Устаревшие ответы:** каждый запрос несёт `scopeEpoch` (`_scopeGuard`, `web/app.js:4675/4709`) — ответ старого scope игнорируется.

## 2. F0.2 — аудит всех механизмов сохранения (§3)

### 2.1. Инвентарь (обязательная таблица T-2420)

Для **каждого** механизма: `экран → ключ(и) → read API → write API → scope (global/chat/ЛС)`.

Механизмы: тумблеры модулей; системные промпты; промпты Синтезаторов; промпты Вербализаторов; модели; провайдеры; резервные подключения; API-ключи; числовые лимиты; память; анти-клише; PERMsoc; глобальные настройки; локальные переопределения. «Сирот» быть не должно.

### 2.2. Прогон `load → edit → save → re-read → compare` (T-2421)

**HTTP 200 — не доказательство.** Для каждого механизма: прочитать значение, изменить, сохранить, **повторно прочитать с сервера** и сравнить. Расхождения — явно (матрица результатов).

### 2.3. Спец-кейсы (T-2422)

Несколько полей; двойной тап; переключение чата во время запроса; две сессии; сохранение рядом с API-ключом; частичные ошибки; устаревшие ответы. Каждый — тест/репро с результатом.

### 2.4. Scope-изоляция (T-2423)

Чат A ≠ чат B; `global → local → global` не теряет и не подменяет; локальное не перезаписывается глобальным; «не создавать копию конфигурации под каждый визуальный экземпляр параметра».

### 2.5. Единый канонический write-path (T-2424)

- **Канон** = `persistItems` (клиент) → `POST /api/config` (chat/global) → атомарная серверная запись (`set_chat_params` для chat; атомарный `ConfigCache`-пакет для global).
- Устранить дублирующие локальные «источники истины» и обходные записи для тех же ключей (кроме BYOK-путей `/api/config/keys/own` — секреты остаются там; §50 — F9).
- Тест паритета источников: после записи любым механизмом `GET` отдаёт то же значение.

## 3. F0.3 — анти-клише: «20 вместо 200» и ложная «Ошибка модели» (§4)

### 3.1. Истинная причина (по коду)

1. **Conflation семантик.** `limits.anticliche_max_patterns` (дефолт 200, `services/param_catalog.py:1441-1447`, `services/anticliche_cache.py:36-52`) используется **одновременно** как (а) вместимость БД-кэша и (б) число фраз, запрашиваемых у LLM **за один вызов**: `EXTRACT_SYSTEM_PROMPT.format(max=anticliche_cache.max_patterns())` (`services/anticliche_worker.py:468-477`). Один запрос «дай 200 фраз» превышает выходной лимит модели → ответ обрезан/ошибка.
2. **Ошибка → кэш сохраняется.** `parse_patterns` при усечённом JSON возвращает `None` → `mark_status('parse_error')`, старый кэш не трогается (`anticliche_worker.py:425-434`); исключение LLM → `mark_status('llm_error')`, кэш не трогается (`:402-413`). В БД остаётся прежний список (**20**, сгенерированный при старом потолке 20), UI показывает `20 / 200`.
3. **Freshness-skip блокирует пополнение.** `_is_fresh(fetched_at)` < 7 дней → `refresh(force=False)` возвращает `fresh` **без** LLM (`anticliche_worker.py:361-372`). Повышение лимита само по себе не запускает пересборку.
4. **Нет дедупликации против БД и нет пакетного добора.** `build_patterns` дедупит только **внутри** одного прогона (`:174-197`), не против уже сохранённых; база не «добирается» до вместимости — один прогон = одна партия.
5. **Ложная «Ошибка модели».** UI безусловно маппит `last_status` (`llm_error → 'ошибка модели'`, `web/app.js:4524-4530`), а «0 новых/пусто» не отличается от сбоя провайдера; stale `llm_error` может оставаться на экране.
6. **Per-chat trap.** Воркер читает лимит только из глобального слоя (`hot.get`), а ключ категории `limits` формально `per_chat=True` (`param_catalog.py:118-127`) — per-chat-переопределение (если бы появилось) воркером игнорировалось бы. UI сейчас форсит global (`web/app.js:4583` `per_chat:false`).

### 3.2. Разведение семантики (§4.3)

- **Вместимость** (`limits.anticliche_max_patterns`, 1…1000) — сколько хранить в БД и питать детектор.
- **Размер партии за обновление** (`ANTICLICHE_MAX_PATTERNS_PER_RUN`, env-only `ClassVar`, default ≤ 40) — сколько просить у LLM за один вызов (в пределах выходного лимита).
- UI отражает: `сохранено N / вместимость M`, `за обновление ≤ K`.

### 3.3. Пакетное пополнение (T-2429)

- Цикл (bounded): `stored = fetch_cache`; пока `stored < capacity` и `rounds < MAX_ROUNDS` и бюджет позволяет: LLM просит ≤ `per_run`; `parse`; **дедуп против существующих** + внутри партии; merge; при 0 новых — стоп (успех «нет новых»).
- Бюджет попыток/расходов — через `worker_budget.consume` (`anticliche_worker.py:389-423`); лимит раундов — env-only.
- Ошибка провайдера ≠ отказ модели: `llm_error` (реальный сбой) разводится с `empty`/`no_new` (валидный успех без новых уникальных).
- `fetched_at` обновляется только при реальном заборе; при ошибке — старое значение (как сейчас), но `last_status` честный.
- Пустая запись — только через явный ручной `PUT /api/anticliche` (`apply_manual`).

### 3.4. События диагностики (§4.4, T-2431)

`ANTI_CLICHE_UPDATE_START`, `ANTI_CLICHE_MODEL_REQUEST`, `ANTI_CLICHE_MODEL_RESPONSE`, `ANTI_CLICHE_PARSE_ERROR`, `ANTI_CLICHE_DEDUP_COMPLETE`, `ANTI_CLICHE_SAVE_COMPLETE`, `ANTI_CLICHE_UPDATE_COMPLETE`, `ANTI_CLICHE_UPDATE_FAILED`.

Поля: `capacity` (заданный лимит), `per_run`/`applied_limit` (фактически применённый), `initial_count` (исходное количество), `candidates`, `duplicates`, `saved`, `final_count`, `model`, `duration_ms`, `reason`. **Секреты/фразы не логировать** сверх необходимого (R17). «0 новых» ≠ ошибка модели.

## 4. F0.4 — уведомления и SaveBar (§5)

### 4.1. Одно итоговое уведомление на операцию (T-2434)

- Каждая операция имеет `operationId`; `notify(operationId, result)` идемпотентен.
- Тостов на операцию **один**: `ok` если всё сохранено; `warn` при частичном успехе («Сохранено N из M; не сохранено: …»); `err` если ничего. Запрещён «success+error» без частичного результата.
- При пакетном сохранении — **не** тост на каждое поле.
- Дедуп одинаковых уведомлений (одинаковый текст+kind в окне), стабильный `id` (заменить `Date.now()+Math.random()`, `web/app.js:2127`).

### 4.2. Уровни ошибок (T-2435)

- Ошибки **отдельных полей** — **возле полей** (per-field error map, подсветка как `sticky-save__failed`).
- Глобальный тост — только итог операции.
- Длинная ошибка → действие **«Подробнее»** (раскрытие), **без** полного stack trace огромным тостом поверх мобильной страницы.

### 4.3. Safe area и лимит тостов (T-2436)

- Учитывать Telegram safe area: `.toast-wrap` (`web/static/app.css:562-571`) — `top`/`right` через `max(env(safe-area-inset-*), var(--tg-*-safe-area-inset-*))` (по образцу `web/static/app.css:686-689`).
- Не перекрывать header, навигацию и **селектор области** (`.scope-panel`, `app.css:331-332`).
- Ограничить число одновременно показанных (queue, напр. ≤3) + приоритет `err > warn > ok`.
- Mobile-проверка 320/390/768.

### 4.4. SaveBar (T-2437)

- Sticky, safe area, учёт клавиатуры (visualViewport), доступность последнего поля, единое состояние (`saveState` из §1.3).
- **Координация с F9:** серверная логика состояний — F0; визуальный слой — здесь и в F9; блоки не дублировать. F9 читает результат F0 и его не переписывает.

## 5. F0.5 — устойчивость к `database is locked` (AMEND ADR-1024-18)

### 5.1. Карта соединений и write-путей (T-2442)

| # | Владелец / метод (file:line) | Соединение | PRAGMA | Bounded retry | Реакция на ошибку |
|---|---|---|---|---|---|
| 1 | `Database` основной (`services/database.py:514-520`) | собственное `aiosqlite.connect` | WAL + busy_timeout=5000 + synchronous=NORMAL | **нет** | вызывающий |
| 2 | `SmartCache` (`services/smart_cache.py:150-175`) | собственное | WAL+bt+NORMAL (ADR-1024-18) | **есть** | fail-open |
| 3 | `Database.initialize_existing` (`database.py:589-594`) | собственное (CLI) | WAL+bt+NORMAL | нет | — |
| 4 | `manage.py` CLI (`manage.py:146,197`) | собственное | не подтверждено | нет | — |
| 5 | `memory_rebuild` sqlite3 sync (`memory_rebuild.py:166-168`) | собственное | — | **есть** (своё) | — |
| 6 | `summary_memory._embed_cache_store` (`:1462-1494`) | `self.db.db` (**общее** соединение #1) | наследует #1 | **нет** | fail-open |
| 7 | `summary_memory.memorize_self_reply` (`:2436`) → `database.insert_graph_fact` (`:2688`) | общее #1 | наследует | **нет** | fail-open |
| 8 | `summary_memory._knn_graph_facts` (`:2731`) → `database.touch_graph_facts` (`:4330`) | общее #1 | наследует | **нет** | fail-open |
| 9 | `direct_chat_service.remember_bot_reply` (`:546`) → `database.upsert_bot_reply` (`:3611`) | общее #1 | наследует | **нет** | fail-open |
| 10 | `persistent_throttling.allow` (`:121`), `reset` (`:217`), `bump` (`:187`) | `self._db.db` (общее #1) | наследует | **нет** | fail-open |

### 5.2. Первопричина: почему `busy_timeout=5000` не спасает (T-2443)

1. **Интерливинг корутин на ОБЩЕМ соединении (#1) без `Database._lock`.** Многошаговые последовательности `_embed_cache_store` (`summary_memory.py:1468-1493`), `upsert_bot_reply` (`database.py:3611-3628`), `allow` (`persistent_throttling.py:121-128`), `reset` (`:217-221`), `touch_graph_facts` (`database.py:4330-4338`) выполняются на **одном** соединении: `await` между `execute` и `commit` позволяет другой корутине вклиниться. SQLite при активном стейтменте/транзакции на соединении отдаёт `SQLITE_BUSY` (`database is locked`) **немедленно** — busy-обработчик для собственного соединения не спасает.
2. **Длинные транзакции.** `_embed_cache_store` делает N вставок до одного `commit`; `upsert_bot_reply` — 4 стейтмента; `touch_graph_facts` — 2 UPDATE в цикле. Держат write-лок дольше.
3. **Конкуренция соединений/процессов.** Основное `Database` + `SmartCache` + CLI `manage.py` (retention/rebuild) → реальная конкуренция нескольких соединений за WAL-писателя; превышение 5с даёт `locked`.
4. **Нет bounded retry в main write-path** (#1/#6–#10): даже короткая блокировка сразу поднимается наверх и молча теряется в fail-open (`summary_memory.py:2447-2451`, `direct_chat_service.py:549-552`, `persistent_throttling.py:129-133/223-227`).

### 5.3. Решение (AMEND ADR-1024-18)

- **D1 (единый bounded-retry helper в `database.py`).** Приватный `Database._with_lock_retry(op, *, on_exhausted)` (+ `is_locked(exc)`): только `OperationalError` с `"locked" in str(exc).lower()`, `_LOCK_RETRIES=3`, backoff `0.1/0.2/0.4с`, best-effort `rollback` перед повтором, повтор **всей транзакции**. Значения — зеркало `memory_rebuild.py:69-72` и ADR-1024-18.
- **D2 (single-writer / сериализация).** Ввести публичный `Database.write_transaction()` (или эквивалент), который берёт `self._lock` на всё время логической транзакции, коммитит/роллбэчит и ретраит `locked`. Обернуть: `insert_graph_fact`, `upsert_bot_reply`, `touch_graph_facts`; перевести `_embed_cache_store`, `persistent_throttling.allow/reset/bump` с `self.db.db`/`self._db.db` на новый публичный API (T-2449). Одна логическая операция → одна атомарная транзакция.
- **D3 (PRAGMA-паритет).** Для каждого **собственного** `aiosqlite`-соединения вне `smart_cache` привести настройки к эталону `database.py:514-520` (локальные константы-зеркала). `smart_cache` — **не трогать** (уже ADR-1024-18). Если T-2442 покажет, что других нет — зафиксировать как результат, без фиктивных правок.
- **D4 (исчерпание — не тишина).** Обязательный структурированный WARNING `event=<service>_lock_exhausted` (`exc_info`, `op`, `scope`/`chat_id` при допустимости — без секретов, R17) + in-process счётчик `<service>_lock_exhausted_total()` (по образцу `smart_cache_lock_exhausted_total`). Развести «успех», «успех после retry», «исчерпание → лог+счётчик+fail-open».
- **D5 (fail-open — последний рубеж).** Хендлеры direct-chat/саммари/throttling не падают и не блокируются из-за `locked`; факт возможной потери **наблюдаем** (D4).
- **D6 (kill-switch `DB_LOCK_RESILIENCE_ENABLED`).** env-only `ClassVar`, **default ON**, вне `param_catalog` (Δ каталога = 0). OFF → ровно прежнее поведение (без PRAGMA-эффекта/повторов/счётчика). Граница: F0.5 — **расширение** ADR-1024-18, не новый контракт; `smart_cache` не переделывать.
- **D7 (тест-хук нулевого backoff).** По образцу `services/llm_client.py:604` (`backoff_base==0`) — чтобы тесты не спали.

**Δ DDL = 0** (миграций/таблиц нет), **Δ каталога = 0** (флаг env-only).

## 6. Feature Flags / Progressive Delivery

| Флаг | Тип | Default | Где | Назначение |
|---|---|---|---|---|
| `DB_LOCK_RESILIENCE_ENABLED` | env-only `ClassVar` | **ON** | `config/settings.py`, вне каталога | kill-switch F0.5 |
| `ANTICLICHE_MAX_PATTERNS_PER_RUN` | env-only `ClassVar` | ≤40 | `config/settings.py`, вне каталога | размер партии F0.3 |

F0.1–F0.4 — без продуктовых флагов (обратимы `git revert` + точка отката T-2410). Progressive delivery (internal→10%→50%→100%) не требуется: фичи локальные и обратимы; наблюдение — по логам `event=ANTICLICHE_*` / `event=*_lock_exhausted`.

## 7. План тестов

- **F0.1:** два save подряд; быстрый двойной тап; две сессии; 409-ретрай (idempotent short-circuit → «сохранено»); Fallback save + re-read == ожидаемое; частичный успех; устаревший ответ (scopeEpoch); null-токен не уходит в chat-scope. Тесты зелёные **и падают на старом коде**.
- **F0.2:** матрица `load→edit→save→re-read→compare`; спец-кейсы §2.3; scope A≠B и `global→local→global`; паритет источников; промпты/модели/секреты (наружу только `{configured,last4}`).
- **F0.3:** capacity применяется по семантике; пакетное пополнение; дедуп против БД; «0 новых» ≠ ошибка; ошибка провайдера ≠ отказ модели; per-chat trap закрыт; события присутствуют с полями.
- **F0.4:** «1 операция → 1 тост»; частичный результат; приоритет полевых ошибок; «Подробнее»; safe-area-классы; очередь/дедуп; состояния SaveBar.
- **F0.5 (T-2452):** (a) PRAGMA реально применены на **файловой** БД; (b) имитация `locked` → retry успешен (запись не потеряна); (c) исчерпание → явный WARNING + счётчик; (d) non-lock исключение не ретраится; (e) параллельные записи атомарны; (f) OFF = baseline; (g) fail-open не роняет хендлер. Тесты падают на старом коде; полный pytest без регрессий к базе **7911/0** + JS-гейты (`node --check web/app.js`, `tests/js/routing_test.js`, `tests/js/vue_mount_test.js`).

## 8. Приёмка (§6, 10 пунктов) и отчёт (§54)

§6: (1) причина 409 установлена; (2) Fallback сохраняется; (3) проверены остальные механизмы; (4) local≠global; (5) промпты/модели/секреты; (6) причина ограничения анти-клише; (7) 200 применяется по семантике; (8) противоречивые уведомления исправлены; (9) regression-тесты; (10) сохранность существующих значений. Ни один пункт — не «по отчёту» (10.22-урок).

§54 (п.1–6): первопричина 409; исправление общего сохранения; результаты аудита; причина анти-клише; результаты фикса; regression-тесты. `git diff --check` чист; R18-скан отчёта/диффа; `plans/current_task.md` не коммитить; бэкап удалять только после утверждения владельцем.

## 9. Покрытие задач T-2410…T-2455

| Блок | Задачи | Где решено |
|---|---|---|
| Пре-флайт/репро | T-2410, T-2411 | `tasks.md` §0 (первое действие — точка отката) |
| F0.1 | T-2412–T-2419 | §1 + ADR-1025-2 |
| F0.2 | T-2420–T-2426 | §2 + ADR-1025-2 |
| F0.3 | T-2427–T-2433 | §3 + ADR-1025-3 |
| F0.4 | T-2434–T-2438 | §4 + ADR-1025-4 |
| F0.5 | T-2442–T-2455 | §5 + ADR-1025-5 (AMEND ADR-1024-18) |
| Regression/приёмка/отчёт | T-2439–T-2441 | §7–§8 |

## 10. Риски и митигации

| Риск | Уровень | Митигация |
|---|---|---|
| Фикс 409 «по симптому» (задержки/повтор) | Critical | первопричина §1.1; idempotent short-circuit + serialize (D-409-1/2) |
| Неисправный механизм сохранения перенесён в F1 | Critical | F0 закрывается **до** F1 (T-2440, §10 ТЗ) |
| Потеря значений при правках | Critical | T-2410 (откат), re-read (T-2421), scope (T-2423), §6 п.10 |
| Смешивание local/global в унификации write-path | Critical | scope-split §1.4, тесты §2.4 |
| Ложное закрытие анти-клише | High | §3 (capacity vs per-run, dedup, события), тесты T-2432 |
| Долгий retry подвешивает hot-path | High | bounded retry, fail-open последним рубежом, T-2450/T-2452 |
| Дублирование/регресс ADR-1024-18 (`smart_cache`) | Medium | §5 D6 — только расширение; `smart_cache` не менять |
| Дублирование SaveBar-логики с F9 | Medium | §4.4 — серверная логика в F0, визуальная в F9 |
| Утечка секрета (R17/R18) | Critical | §1.1/§7/§8; `current_task.md` не коммитить |

## 11. Ссылки

- ADR: `adr-1025-2-save-state-machine.md`, `adr-1025-3-anticliche-semantics.md`, `adr-1025-4-toasts-savebar.md`, `adr-1025-5-db-lock-resilience.md`; AMEND **ADR-1024-18** (`plans/archive/sqlite-lock-resilience-round1024/`).
- Задачи: `plans/features/f0-config-bugfixes-round1025/tasks.md` (T-2410…T-2455).
- Код:
  - сохранение — `services/chat_params.py` (`set_chat_params`, `ChatParamsConflict`), `web/api/routes.py:99-102,381-522,525-626,890-931`, `services/param_catalog.py:118-127,479-482`, `web/app.js:1616-1643,1984-2022,2181-2234,3124-3197,3727-3814,4382-4444,4670-4732,4983-5104`, `web/index.html:469-490,3514-3516`, `web/static/app.css:562-586,890-960`;
  - анти-клише — `services/anticliche_cache.py`, `services/anticliche_worker.py:120-197,340-503`, `web/api/anticliche.py`, `web/app.js:4456-4588`, `web/index.html:395-459`;
  - DB lock — `services/database.py:48,507-594,2619-2708,3607-3628,4310-4339`, `services/smart_cache.py:30-232`, `services/memory_rebuild.py:69-72,92-111`, `services/persistent_throttling.py:74-227`, `services/summary_memory.py:1462-1494,2416-2451,2729-2737`, `services/direct_chat_service.py:538-552`, `config/settings.py:966-977`.
