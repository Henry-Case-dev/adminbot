# Отчёт @Reviewer — раунд 10.23, ШАГ 5, фича F7 `token-analytics-dashboard-round1023`

- **HEAD ревью:** `8c46132` (F7), предыдущий `7ade4d6` (F6).
- **Дата:** 19.09.2026.
- **Вердикт:** **Changes Requested** (1×High, 2×Medium, 6×Low).
- **Среда:** `.venv` → `asyncpg 0.31.0`, FastAPI/aiogram из окружения проекта; `node --check web/app.js` — зелёный.
- **Прогон (лично):** полный `pytest -q` → **7322 passed / 0 failed** (96.6 c); целевой `tests/test_token_analytics_round1023.py` → **33 passed**; связанные (`test_pg_db`, `test_tool_loop`, `test_direct_chat`, `test_summary_generator`, `test_image_generation_round1023`, `test_tool_calling_round1015`) → **357 passed**. Заявленные цифры подтверждены.
- **Проверено по коду:** DDL PG (идемпотентность/индексы/сид), сквозной `correlation_id`, расчёт `cost_usd`, fail-open, RBAC-обвязка, UI, инварианты, регресс.

> ⚠️ **Раздел ниже — это ИТЕРАЦИЯ 1 (история, коммит `8c46132`). Актуальный статус после итерации 2 (коммит `902ec25`): ✅ Approved** — см. раздел «Итерация 2 (повторный аудит)» в конце документа.

---

## Итог кратко

Бэкенд-ядро сделано аккуратно и по ADR-1023-7: DDL действительно в **PostgreSQL** (SQLite не тронут, остаётся **v12**), сид цен идемпотентный (`ON CONFLICT (model) DO NOTHING`), корреляция протянута через Stage-1/Stage-2/tool-loop/`generate_image`, цена считается по реальным токенам с честным `price_known=false`, всё fail-open, бюджетный контур (`source='global'`, `chat_usage`/`worker_budget`) не изменён. Но **фича не готова к приёмке**: одна явная недоделка по spec (имя инструмента для tool-раундов вообще не пишется — мёртвая колонка `tool_name`), а также отсутствуют обязательные тесты сквозной корреляции через оркестраторы и RBAC/интеграции API (в проекте для этого есть прямой прецедент). См. findings.

---

## Findings

### [High] `services/tool_loop.py:110-117` (+ `services/llm_client.py:1014`) — `tool_name` для tool-раундов не пишется никогда
`chat_with_tools` вызывает `generate_chat(...)`, передавая `module`/`step`/`correlation_id`, но **не передаёт `tool_name`**, хотя параметр есть (`generate_chat(..., tool_name: str = "")`, `llm_client.py:1014`) и он участвует в записи (`llm_client.py:494`). Имя вызванного инструмента из `result.tool_calls` не извлекается и не пробрасывается.

**Почему это важно:** spec §2.2 прямо требует «`step="tool"` **+ имя тула**», а §2.5 заводит колонку `tool_name` ровно под это; пример ответа `/usage/latest` в spec §2.7 показывает `"tool_name":"query_chat_memory"`. По факту для **всех** `step='tool'` строк `tool_name=''`. То есть бэкенд формально «пишет обогащённую запись», но дашборд никогда не покажет, *какой именно* инструмент сработал — ключевая часть заявленного Flow-node-дерева. Это не fail-open-деталь, это молча непокрытая часть ТЗ, и она не закреплена ни одним тестом (в `tests/test_token_analytics_round1023.py` нет ни одного `assert ... tool_name`).

**Required fix:** в `tool_loop.chat_with_tools` для `round_index >= 1` передавать `tool_name` = имена инструментов из tool_calls предыдущего раунда (например, `",".join(c.name for c in prev_result.tool_calls)` или явное поле в `ToolLoopResult`). Если продуктово решено `tool_name` не заполнять — **убрать колонку/параметр из ADR и spec и зафиксировать это решением**, а не оставлять «мёртвое» поле. Добавить тест: 2 раунда с tool_call `query_chat_memory` → событие `step='tool'` с непустым `tool_name`.

### [Medium] `tests/test_token_analytics_round1023.py:293-316` — сквозной `correlation_id` проверен только на tool-loop, не через оркестраторы
Единственный тест корреляции (`test_stage1_then_tool_share_correlation_id`) дёргает `chat_with_tools` с фейковым LLM. **Ни один тест не проверяет**, что `direct_chat_service`/`factcheck_service`/`summary_generator` действительно создают **один** id на ответ и доводят его до Stage-1 **и** Stage-2 (и что id одинаков у Stage-1 → tool → Stage-2). Аналогично нет теста, что `ToolContext.correlation_id` доходит до `generate_image` (`step='image'`) внутри `tool_router`.

**Почему это важно:** риск R3 (потеря id в цепочке) и есть смысл фичи («связать вызовы одного ответа в дерево»). Регрессия вида «забыли передать `correlation_id` в Stage-2 одного из трёх оркестраторов» пройдёт весь сьют зелёной — тест ловит только один слой из четырёх. `physical-two-call`-дерево на дашборде развалится на две отдельные ветки, и это заметят только в проде.

**Required fix:** добавить тесты на каждый оркестратор: Stage-1 (`stage1`) и Stage-2 (`stage2`) получают **тот же** `correlation_id`; для Direct — плюс tool-раунд; для image-инструмента — `ctx.correlation_id` пробрасывается в `image_generation.generate_and_send`.

### [Medium] `tests/` — нет RBAC/интеграционного теста эндпоинтов аналитики, хотя прецедент в проекте есть
Тесты `TestAnalyticsApi` вызывают **функции-хендлеры напрямую** (`usage_latest(_api_request(pool), user=...)`), подсовывая результат зависимости вручную. Это не проверяет:
- что реально применён `Depends(requires_global_admin())` (не-admin → 403); 
- что роутер вообще зарегистрирован в `web/app.py` и отвечает по `/api/analytics/...`;
- что при невалидном/отсутствующем `initData` — 401.

**Почему это важно:** `requires_global_admin` — это единственное, что закрывает телеметрию (модели/токены/стоимость/цены) от не-админов, и это ровно тот класс кода, где регрессию «случайно ослабили зависимость» тесты-вызовы-функций не поймают. В проекте для соседних рутов есть прямые образцы: `tests/test_webapp_gates_api.py` (403/401 через `TestClient`), `tests/test_webapp_avatars_ui.py` и т.д. F7 этот уровень пропустил.

**Required fix:** добавить интеграционный тест `TestClient(create_app(...))`: `GET /api/analytics/usage/latest|summary|prices`, `PUT /api/analytics/prices` — admin 200/успех, не-admin (moderator/user без гранта) → 403, без `X-Telegram-Init-Data` → 401. Плюс тест, что `PUT` реально инвалидирует кэш цен.

### [Low] `web/api/analytics.py:224-276` — `/analytics/prices` игнорирует `TOKEN_ANALYTICS_ENABLED`
Spec §2.7 явно: «`TOKEN_ANALYTICS_ENABLED=OFF` → эндпоинты возвращают пустой/shape-совместимый ответ без ошибок». `usage/latest`/`usage/summary` это соблюдают, а `GET/PUT /analytics/prices` — нет: они читают/пишут таблицу цен при выключенном мастер-флаге.

**Почему это важно:** формальное расхождение с контрактом OFF-режима. Вреда мало (цены — конфиг, не промпты/секреты), но kill-switch должен быть предсказуемым: оператор, выключивший аналитику, продолжает видеть и мутировать её состояние.

**Required fix:** либо обернуть `prices_list`/`prices_upsert` в `if not usage_events.is_enabled(): return {"prices": []}` / `{"ok": False}`, либо явно зафиксировать в spec/ADR, что управление ценами не подчиняется мастер-флагу (и протестировать).

### [Low] `services/llm_client.py:493, 930-933, 1111-1115` — при работе через fallback-модель стоимость пишется на основную модель
`_record_analytics(..., model=model or self._chat_model)`. В ветке фоллбэка (`_fallback_with_retries`, строки 908/1042) фактический ответ отдаёт `self._fallback_model`, но в событие уходит `self._chat_model`. Цена/`cost_usd` при этом считаются по ставке **основной** модели.

**Почему это важно:** при активном фоллбэке дашборд завышает/занижает стоимость и атрибуцирует токены не той модели. Не блокер, но это телеметрия, которую будут использовать для решений о расходах.

**Required fix:** записывать фактически использованную модель (пробросить `self._fallback_model`, когда сработал фоллбэк).

### [Low] `services/usage_events.py:166-178` — метка дедупа очистки проставляется ДО `DELETE`
`_last_cleanup = now` выставляется до `pool.acquire()`/`execute`. Если `DELETE` упадёт (transient PG-ошибка), дедуп подавит повторную попытку на час.

**Почему это важно:** retention — best-effort, но при частых сбоях таблица может «залипнуть» без очистки заметно дольше 90 дней, раздувая PG.

**Required fix:** выставлять `_last_cleanup` только после успешного `execute` (или использовать backoff вместо фиксированного интервала).

### [Low] Документационный дрейф контракта `DLD`/файлов
- `plans/features/round1023-architecture.md:37` и `:133` по-прежнему утверждают «F7 `v12 → v13` (SQLite)», хотя ADR-1023-7 AMEND перевёл DDL в PG (реализация верна — PG, SQLite v12). Строку архитектурного канона стоило синхронизировать в этом же контуре.
- spec §3 (таблица изменений по файлам) и tasks T-2160 называют `services/system2_handoff.py` как точку аддитивного проброса `correlation_id`; в коде `system2_handoff.py` не менялся. По факту id идёт kwargs-ами оркестратор → `generate/generate_chat` — решение корректное, но контракт-документ это не отражает.

**Required fix:** синхронизировать `round1023-architecture.md` §3.4 с AMEND ADR-1023-7 и поправить spec §3/T-2160 (проброс id kwargs-ами, `system2_handoff` no-op).

### [Low] `tests/test_token_analytics_round1023.py:88-115, 389-397` — часть тестов тавтологичны/слабы
- `test_chat_usage_report_call_source_global_unchanged` проверяет строку исходника (`inspect.getsource`) вместо поведения.
- DDL-тесты — это `assert "строка" in DDL` (плюс счётчик `18*2` в `test_pg_db.py`). Настоящей идемпотентности PG (повторный `init` без дублей) в рамках F7 не проверяется, только отсутствие ошибок на fake-pool.

**Почему это важно:** такие тесты фиксируют текст, а не контракт, и не защищают от регрессии (`DROP TABLE` → `CREATE` с другим именем колонки пройдёт).

**Required fix:** заменить проверку исходника на поведенческий тест (например, что `generate` с `source='chat'` **не** вызывает `chat_usage.report_call`, а с `source='global'` — вызывает), а для DDL добавить проверку «дважды один и тот же набор executed-запросов → нет дублей CREATE без IF NOT EXISTS».

### [Low] `web/index.html:1068-1076` / `web/app.js:2234-2247` — Flow-node показывает сырые коды шагов и лишнюю стрелку
Метка узла — `s.step` как есть (`stage1`, `tool`, `stage2`), тогда как spec/ТЗ ожидают человекочитаемый вид («Слой 1», «Слой 2»). Также стрелка `→` рендерится **после каждого** узла, включая последний, перед бейджем «Итого». XSS нет (везде `{{ }}`/`:title`, без `v-html`).

**Required fix:** маппинг `stage1→Слой 1`, `stage2→Слой 2`, `tool→Инструмент(:name)`; стрелку выводить только между узлами (`v-if="i < tokenFlowNodes().length - 1"`).

---

## Контракт (чекбоксы)

1. **DDL PG (AMEND ADR-1023-7), идемпотентность/индексы/сид** — ✅. `CREATE TABLE IF NOT EXISTS` ×2, `CREATE INDEX IF NOT EXISTS` ×3, сид 4 цен с `ON CONFLICT (model) DO NOTHING`. **SQLite = v12, не тронут**, Δ SQLite = 0. Повторный `init()` — no-op (fake-pool `test_init_twice_no_errors`, счёт 18×2).
2. **Сквозной `correlation_id`** — ⚠️ **ЧАСТИЧНО**. Создаётся в Direct/Factcheck/Summary, доходит до Stage-1/Stage-2/tool-loop/`generate_image`; kwargs аддитивны (обратная совместимость: фейки обновлены, полный сьют зелёный). ❌ Нет e2e-теста через оркестраторы (Medium).
3. **`cost_usd` по реальным токенам / fail-safe / бюджет/BYOK** — ✅ по коду. Реальные `prompt_tokens/completion_tokens` → `cost = in/1e6*in_price + out/1e6*out_price`; нет usage → `count_tokens` + `tokens_estimated=true`; нет цены → `0` + `price_known=false`. `source='chat'` → `'byok'`. Бюджетный контур не тронут (`chat_usage.py`/`worker_budget.py` не в диффе; `_record_global_usage` по-прежнему только `source='global'`). ⚠️ атрибуция модели при фоллбэке (Low).
4. **Fail-open** — ✅. PG нет/ошибка записи/ошибка чтения API → `_empty_*` (shape-совместимо), `record` ловит всё и логирует WARNING без падения LLM-пути. OFF → no-op записи. ⚠️ `/analytics/prices` не гейтится OFF (Low).
5. **API RBAC + ответы + ретенция** — ✅ RBAC применён (`Depends(requires_global_admin())`, тот же паттерн, что у `/api/workers/budget`), latest/summary/prices корректны, `period` — whitelist (SQL-литерал `hour|day` безопасен), ретенция `DELETE ... interval` + дедуп. ❌ Нет RBAC/интеграционного теста (Medium).
6. **UI** — ✅. Блок «Token Metrics» внутри существующей вкладки «Сводка», меню не менялось (`tma-menu-freeze`); `node --check` зелёный; XSS не найден. ⚠️ косметика Flow-node (Low).
7. **Инварианты** — ✅. `physical-two-call-pipeline` не нарушен (аналитика **не** добавляет LLM-вызовов, только пишет событие после вызова); R16 (аддитивный рутер) ✅; R17/R18 — пишутся/логируются только коды/числа/модель, промптов/сырья/секретов нет, секретов в диффе не найдено; egress не затронут; `parse_mode=None` не тронут; `bot.py` не изменён (порядок роутеров цел); F1–F6 зелёные; Δ каталога = 0; Δ SQLite = 0.
8. **Тесты** — ⚠️ **ЧАСТИЧНО**. Запись/чтение, cost (known/unknown), fail-open PG, OFF-switch, ретенция/дедуп, tool-loop-корреляция — есть. ❌ нет e2e-корреляции через оркестраторы, RBAC/интеграции API, `tool_name`; часть DDL/бюджет-тестов тавтологичны (Low).
9. **Полный pytest** — ✅ **7322 passed / 0 failed** (проверено лично). `node --check web/app.js` — OK.
10. **Секреты/дифф** — ✅. Ключей/токенов в `git show 8c46132` нет; `.env`/`.env.example` не затронуты.

**Δ PG:** +2 таблицы (`llm_usage_events`, `llm_model_prices`), +3 индекса, +1 идемпотентный сид (4 модели). **Δ SQLite:** 0 (**v12**). **Δ каталога:** 0 (оба рубильника — env-only `ClassVar`).

---

## Список для @Builder (Changes Requested)

1. **`services/tool_loop.py:110-117`** — заполнять `tool_name` для `step='tool'` (имена из tool_calls), пробросить в `generate_chat`; убрать «мёртвую» колонку из контракта, если решено не заполнять. Тест: `step='tool'` + непустой `tool_name`.
2. **`tests/test_token_analytics_round1023.py`** — добавить e2e-тесты корреляции для **всех трёх** оркестраторов (Stage-1 и Stage-2 с одним `correlation_id`), плюс проброс `ctx.correlation_id` в `generate_image`.
3. **`tests/` (новый интеграционный файл, по образцу `tests/test_webapp_gates_api.py`)** — `/api/analytics/usage/latest|summary|prices` и `PUT /analytics/prices`: admin 200, не-admin 403, без initData 401; проверка инвалидации кэша цен на PUT.
4. **`web/api/analytics.py:224-276`** — гейтить `prices` мастер-флагом `TOKEN_ANALYTICS_ENABLED` **либо** явно закрепить обратное в spec/ADR + тест.
5. **`services/llm_client.py:493`** — писать фактически использованную модель при срабатывании фоллбэка.
6. **`services/usage_events.py:166-178`** — ставить метку дедупа только после успешного `DELETE`.
7. **Doc-sync:** `plans/features/round1023-architecture.md:37,133` (убрать «SQLite v12→v13», зафиксировать PG по AMEND ADR-1023-7); spec §3/T-2160 (`system2_handoff` — no-op, id идёт kwargs-ами).
8. **`tests/test_token_analytics_round1023.py:88-115,389-397`** — заменить тавтологичные проверки исходника на поведенческие; усилить DDL-проверку на дубли.
9. **`web/app.js:2234-2247` / `web/index.html:1068-1076`** — человекочитаемые метки шагов («Слой 1/2», «Инструмент: name») и стрелка только между узлами.

**Примечание:** живая приёмка T-2166 не выполнена — до устранения п.1 (имя инструмента) и п.3 (RBAC-тесты) считать F7 непринятой; при этом backend-P0 (DDL/корреляция/цены/fail-open) реализован верно.

`Верни исправленную версию. Текущий код отклонён.`

---

# Итерация 2 (повторный аудит)

- **HEAD ревью:** `902ec25` (`fix(services,web,tests): раунд 10.23 F7 — tool_name, e2e-корреляция, RBAC-тесты, Low-чистка (review iter1)`).
- **Учтено:** поверх F7 влиты **отдельные** F6-фиксы `1ffb066` и `92885cd` — они F7 не приписываются. `902ec25` трогает только F7-контур: `services/{llm_client,tool_loop,usage_events}.py`, `web/api/analytics.py`, `web/app.js`, `web/index.html`, `tests/test_token_analytics_round1023.py`, новый `tests/test_webapp_analytics_api.py` (8 файлов).
- **Вердикт:** ✅ **Approved** (0×Critical/High, 0×Medium; 1×Low residual — doc-дрейф ADR, некритично).
- **Прогон (лично):** полный `pytest -q` → **7352 passed / 0 failed** (102.97 c); целевой `tests/test_token_analytics_round1023.py` + новый `tests/test_webapp_analytics_api.py` → **54 passed**; `node --check web/app.js` — OK. Скан секретов в `git show 902ec25` — чисто.

## Что проверено по существу (все 9 пунктов iter1)

1. **[High] `tool_name` — ИСПРАВЛЕНО.** `services/tool_loop.py:108-122,163-166`: `pending_tool_name` набирается из `result.tool_calls` **до** исполнения, прокидывается в `generate_chat(tool_name=...)` начиная со 2-го раунда; 1-й (Stage-1) раунд — пусто. `services/llm_client.py:1118` передаёт `tool_name` в `_record_analytics`. Тесты **поведенческие, не тавтологичны**: `test_stage1_then_tool_share_correlation_id` (round-1 `tool_name=''`, round-2 `'query_chat_memory'`) и `test_two_tools_joined_in_tool_name` (join `'query_chat_memory,execute_web_search'`). Колонка больше не мёртвая.
2. **[Medium] e2e-корреляция — ИСПРАВЛЕНО.** Добавлены тесты на все три оркестратора: Direct (`_synthesize_direct_answer`: Stage-1 и Stage-2 с одним `DIR-1`), FactCheck (`check_claim`: Stage-1 и Stage-2 с одним id), Summary (`_run`: один `SUM-1`; `_generate_two_call`: Stage-1/Stage-2 с одним `SUM-2`). Плюс `test_image_tool_receives_ctx_correlation_id` — `ctx.correlation_id` реально доходит до `image_generation.generate_and_send` через `ToolRouter._generate_image`.
3. **[Medium] RBAC/интеграция API — ИСПРАВЛЕНО.** Новый `tests/test_webapp_analytics_api.py` собирает **реальный** `TestClient(create_app(...))` (образец `test_webapp_gates_api.py`): 401 без initData, 403 для moderator/user без гранта, 200 для admin по `latest/summary/prices`, 403 на `PUT` для не-админа. `test_put_ok_and_invalidates_cache` проверяет и запись, и что ключ вылетел из `llm_pricing._CACHE`. Это закрывает и вопрос «роутер реально зарегистрирован».
4. **[Low] `prices` под флагом — ИСПРАВЛЕНО.** `web/api/analytics.py`: `prices_list`/`prices_upsert` гейтятся `usage_events.is_enabled()`; тест `test_off_gates_prices` подтверждает OFF → `{"prices": []}` / `{"ok": False}`.
5. **[Low] `used_model` при фоллбэке — ИСПРАВЛЕНО.** `services/llm_client.py:899,912,934,1037,1049,1118`: при срабатывании фоллбэка `used_model = self._fallback_model` и уходит в аналитику; тест `test_fallback_records_fallback_model` проверяет `model == 'fb-model'`.
6. **[Low] Метка дедупа очистки — ИСПРАВЛЕНО.** `services/usage_events.py:166-181`: `_last_cleanup` выставляется **после** успешного `DELETE`; тест `test_failed_cleanup_does_not_set_dedup_mark` (2 подряд сбоя → 2 попытки).
7. **[Low] Doc-sync — ИСПРАВЛЕНО (в основном).** `round1023-architecture.md:37,133` — F7 DDL переведён на PG, «SQLite v12 — AMEND ADR-1023-7»; spec §3 (строка 154) — `services/system2_handoff.py` помечен «**no-op по коду**» (id идёт kwargs-ами). Residual Low: `ADR-1023-7.md:41,83` сохраняет старую формулировку «только аддитивный проброс id» в `system2_handoff` — формально расходится с уже исправленным spec. Некритично (ADR — исторический артефакт решения), но стоит дописать при Merge.
8. **[Low] Тавтологичные тесты — ИСПРАВЛЕНО.** `inspect.getsource` заменён поведенческими `test_global_source_reports_budget` / `test_non_global_source_does_not_report_budget`; DDL усилен `test_ddl_has_no_duplicate_create_and_is_guarded` (все CREATE — с `IF NOT EXISTS`, нет дублей имён) и `test_repeated_init_creates_each_table_exactly_twice` (реальный `PgDatabase.init()` ×2, каждая таблица ровно 2 раза).
9. **[Low] UI — ИСПРАВЛЕНО.** `web/app.js` маппинг `stage1→Слой 1`, `stage2→Слой 2`, `tool→Инструмент: name`, `single→Один вызов`, `image→Изображение`; `web/index.html` — стрелка `→` только между узлами (`v-if="i < tokenFlowNodes().length - 1"`). XSS по-прежнему нет (`{{ }}`/`:title`, без `v-html`).

## Контракт (итер. 2)

- **Fail-open** — ✅ сохранён (PG/ошибка/OFF → shape-совместимый пустой ответ; запись обёрнута в try/except; ни один LLM-путь не падает).
- **`physical-two-call-pipeline`** — ✅ аналитика не добавляет LLM-вызовов (только событие после ответа); тесты оркестраторов это подтверждают (ровно Stage-1 → Stage-2).
- **R16/R17/R18** — ✅ R16 аддитивен (новый рутер), R17 — только коды/числа/токены, без промптов/секретов, R18 — секретов в диффе нет.
- **egress / `parse_mode=None` / порядок роутеров `bot.py`** — ✅ не затронуты (`bot.py` в `902ec25` нет).
- **Δ каталога = 0** — ✅ (`param_catalog.py` не тронут).
- **Δ SQLite = 0 (v12)** — ✅ (`services/database.py`/миграции не тронуты).
- **Δ PG = +2 таблицы +3 индекса + идемпотентный сид 4 цен** — ✅ без изменений относительно iter1.
- **Бюджетный учёт (`source='global'`, `chat_usage`/`worker_budget`)** — ✅ не изменён, теперь покрыт поведенческими тестами.

## Residual (не блокирует)

- **[Low] `plans/features/token-analytics-dashboard-round1023/ADR-1023-7.md:41,83`** — формулировка про проброс id в `system2_handoff.py` не синхронизирована с уже исправленным spec §3 («no-op по коду»). Дописать при Merge для канон-атомарности.

**Заключение:** все findings итерации 1 закрыты по коду и закреплены не-тавтологичными тестами; регресс полный (7352/0). Замечаний уровня Critical/High/Medium нет.

`**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.`
