# MCA-11 `mca-11-tools-costs` — spec (design-freeze, Step 2 @Architect, 05.10.2026)

Фича: **`mca-11-tools-costs`** — ToolResult и доставка, учёт расходов, денежные лимиты OFF (эпик `memory-context-autonomy`, Wave 2 — последний хвост; после него Wave 3).
Источник: `plans/current_task.md:730–761` §15 (файл не изменялся, R17); приёмки A20/A21 `:901–902`, A28 `:909`; §20.2 `:1006–1030` (денежные ограничения OFF `:1026`, инструменты автономно ON `:1022`); планирование `plans/docs/mca-round1027-plan.md:119–121, :203 (R2), :235, :415 (Q14)`.
Архитектурное решение: **ADR-1028-13** (`adr-1028-13-tools-costs.md`; номер проверен grep'ом — свободен; latest = ADR-1028-12). Merge-цель — `plans/ARCHITECTURE.md` **§117** (последний фактический §116; присваивается по merge).
База (проверено @Architect): HEAD `3b5bdfd`; прод 2.58.56 (`settings.py:2861`); SQLite **v26**; каталог **489**; канон инструментов **12** (`tool_schemas.py:547`); `mca-15` не трогала контуры §15 (её AM-9 уже предусматривает совместимость — `adr-1028-12-chat-statistics.md:46`).

Статус: **Proposed → Accepted по merge**; санкции T-4944 — §9 (обязательны для Builder T-4945+).

---

## 1. Scope

**В scope:** (a) единый типизированный ToolResult-контракт и интеграция потребителей; (b) пределы исполнения §15.1 поверх существующих cap'ов без ослабления A2; (c) idempotency/operation state + `delivery_unknown` (REUSE mca-01/22); (d) учёт расходов (REUSE `llm_usage_events`/`llm_pricing`/`execution_graph_source`; unknown ≠ 0); (e) новый механизм денежных лимитов `enabled=false` (direct/autonomous/maintenance, семантика будущего включения); (f) стадии `tools.chain` + reason_code-аддитив; (g) санкции Δ DDL/каталога/kill-switches/risk/deploy.

**Явно вне scope (границы D9):** Intent/Decision lifecycle и action-schema — mca-09; применения случайности — mca-10a/10b; опыт/уроки (расходы не reward) — mca-16; UI/рендер/диагностические действия — mca-17c; гайды — mca-21; SelfModel/vision/фактчек — mca-18/19/20; истории — mca-12; единый релиз/effective state — mca-release.
**Вторые механизмы запрещены:** статус-словарь, леджер доставки, очередь операций, словарь событий, сборщик аналитики, постпроцессор, координатор, LLM-провайдер, второй леджер расходов.

---

## 2. D1 — ToolResult: единственный структурированный контракт результата

**Дом контракта:** новый модуль **`services/tool_result.py`** — константы статусов/категорий, маппинг категорий канона 12, правила деривации статуса/retryable, сборка envelope-записи. `tool_loop`/`tool_router` используют его; envelope-журнал (`ToolLoopResult.tool_results`/`ToolContext.tool_results`, `tool_loop.py:74–105, :613–617`) остаётся **единственной** формой записи (dict-ключи, совместимые с существующими тестами/потребителями). Второго контракта/словаря нет.

### 2.1. Статусы (закрытый набор — 7)

`ok | empty | error | timeout | cancelled | denied | delivery_unknown`.

Правила деривации (детерминированные, из модельно-видимого вывода и сигналов обвязки):

| Наблюдаемая форма | status | error_code | retryable |
|---|---|---|---|
| JSON payload `status:"ok"` / обычный успешный текст | `ok` | `""` | false |
| JSON payload `status:"partial"` (mca-15) | `ok` + `partial=true` (payload `status` сохраняется) | `""` | false |
| JSON payload `status:"not_found"` (напр. `lore_compiler_service.py:149`) | `empty` | `not_found` | false |
| JSON payload `status:"unsupported"` (mca-15) | `empty` (payload `status` сохраняется) | `stats_unsupported` | false |
| JSON payload `status:"error"`; текст `ОШИБКА …` (`tool_loop.py:155–185`) | `error` | из payload/текста (`invalid_arguments`, `unknown_tool`, `no_url`, `extract_failed`, …) | false (кроме 2.3) |
| Исполненный вызов с таймаутом (текст/payload `error ∈ {timeout, safe_fetch_timeout}`, `asyncio.TimeoutError`-ветки инструментов) | `timeout` | `timeout`/`safe_fetch_timeout` | **true** (идемпотентные) |
| Отказ до исполнения: chain-лимиты (`tool_loop.py:421–450`: `chain_timeout`/`chain_call_limit`/`chain_cost_limit`) | `denied` (канонизация legacy-`skipped`) | существующий код лимита | false |
| Отказ политикой/флагом/правами (напр. «Инструмент X отключен», admin-гейт) | `denied` | `disabled`/`job_not_allowed` | false |
| Отмена, сообщённая инструментом (маркер отмены; не `asyncio.CancelledError`) | `cancelled` | `cancelled` | false |
| Неясный исход side effect (Telegram/платный провайдер; `mca_watchdog.mark_delivery_unknown`, media `unknown_after_disconnect`) | `delivery_unknown` | `delivery_unknown` | **false — слепой повтор запрещён** |
| Исключение инструмента (`except Exception`, `tool_loop.py:460–464`) | `error` | `tool_error`/класс | false |

`asyncio.CancelledError` **не** перехватывается (текущее поведение сохраняется). «Строка с текстом ошибки ≠ ok» — A20-инвариант: любой текст, начинающийся с `ОШИБКА`, и JSON `status:"error"` дают `error`/`timeout`, никогда `ok`.

### 2.2. Поля envelope (существующие + аддитивные)

Существующие (байт-совместимы): `round, tool, args_fingerprint, status, data, error_code, error_type, truncated, metered, duplicate, attempt, out_chars` (`tool_loop.py:202–222`).
Аддитивные: `category`, `retryable` (bool), `duration_ms` (int, monotonic-замер вокруг `router.dispatch`), `usage`, `external_operation_id` (str|null, R17-safe id/короткий хэш), `evidence_refs` (list[str], R17-safe id: message/source/metric_id; новый provenance-механизм не создаётся), `partial` (bool).
`usage` (числа/коды, при отсутствии — `{}`): `{input_tokens, output_tokens, cached_tokens|null, cost_usd|null, price_known, currency:"USD", price_version|null, source}`.
**R17:** сырой `output`-текст в envelope **не** персистится (модельно-видимый канал не меняется; журнал — только `data`/числа/коды/длины). Аргументы — только `args_fingerprint`.

### 2.3. Retryable (закрытые правила)

`retryable=true` только для транзиентных причин: `timeout`/`safe_fetch_timeout` (идемпотентный вызов), `provider_unavailable`, `provider_stalled`, `rate_limit`. Всё остальное — `false` (по умолчанию), в т.ч. `empty`, `denied`, `cancelled`, `delivery_unknown`, валидация/аргументы. Повтор допустим только если `retryable=true` **и** операция идемпотентна **и** нет `delivery_unknown`/подтверждённого успеха (D3). Верхняя граница повторов — §3.

### 2.4. Категории канона 12 (закрытый маппинг; права не расширяются)

| Категория | Инструменты |
|---|---|
| `memory_read` | `query_chat_memory`, `dig_into_lore`, `get_recent_history`, `get_user_context` |
| `external_read` | `execute_web_search`, `fetch_article`, `summarize_video`, `transcribe_video`, `download_media` |
| `paid_media` | `generate_image`, `compile_lore_story` (платное создание контента; `METERED_TOOLS`, `tool_loop.py:56–59`) |
| `admin` | `get_bot_health` (диагностика, read-only; мутаций прав нет) |

Неизвестный инструмент → `external_read` + `metered=true` (консервативно), **никогда** `admin`. Категория — метка/вход будущих лимитов, не гейт прав; существующие гейты (`flags.lore_compiler_enabled`, `IMAGE_GENERATION_ENABLED`, `DOWNLOAD_ENABLED`, admin-права) не меняются. Инициатива использует те же инструменты/защиту, что direct (`:744`).

### 2.5. Совместимость с mca-15 (handoff T-4941, CA-11-1, AM-9 ADR-1028-12)

`MetricResult.status (ok|partial|unsupported|error)` — **авторитетен внутри payload**; ToolResult его не подменяет и не переписывает. Маппинг: `ok→ok`, `partial→ok (+partial=true)`, `unsupported→empty`, `error→error` (`error_code` из `stats_count_error`/`insufficient_output_budget`). `metric_id`/`NumericClaim`/`ctx.metric_results` и numeric-гард mca-15 не трогаются; второго словаря статусов нет.

### 2.6. Потребители

`tool_loop` (деривация/envelope), `tool_router`/`ToolContext` (передача), `direct_chat_service` (результаты/`tool_context`), `fetch_article` поверх SafeFetcher (M-MCA02-3: `SafeFetchError.code/stage/reason/retryable` → ToolResult `error_code`/`retryable`, stage в `data`), платные медиа (`media_execution`/`image_generation` — статусы/`delivery_unknown`), stats-режим mca-15.

### 2.7. OFF-parity

K1 `MCA_TOOL_RESULT_ENABLED=false` → envelope 2.58.56 байт-в-байт: legacy `_classify_output` (`ok/error`+legacy-`skipped`), без новых ключей/статусов; модельно-видимый канал и `tool_trace` не менялись никогда.
**Builder-примечание:** существующие проверки legacy-`skipped` (`tests/test_tool_chains_round1026.py:306, :411`) при K1 ON переводятся на канонический `denied`; обязателен OFF-паритетный тест (K1=false → `skipped`/прежние ключи байт-в-байт).

---

## 3. D2 — Пределы исполнения (поверх существующих cap'ов, без ослабления A2)

**Числа — env-only ClassVar'ы с текущими значениями по умолчанию** (Δ каталога=0; байт-паритет при дефолтах): `MCA_TOOL_MAX_TOTAL_CALLS=6`, `MCA_TOOL_MAX_METERED_CALLS=4`, `MCA_TOOL_MAX_SAME_CALL=2`, `MCA_TOOL_CHAIN_TIMEOUT_SECONDS=360`, `MCA_TOOL_TRANSIENT_RETRIES_MAX=2`. Enforcement остаётся в `tool_loop` (`tool_loop.py:43–52, :121–127, :396–450`); существующий master `TOOL_CHAIN_LIMITS_ENABLED` (ON) не дублируется; числа видны в настройках (env/config), UI-рендер — mca-17c.

**Transient retries:** стартовая политика «≤2 transient retries на один идемпотентный вызов» — верхняя граница для любого retry-слоя (внутренние bounded-retry инструментов — только идемпотентные операции, ≤2; `attempt`/`retryable` видны в ToolResult). **mca-11 не добавляет автоматических chain-level повторов в direct loop** — новых платных вызовов/ослабления A2 нет; те же константы потребляет будущий autonomous loop (mca-09).

**Media async:** REUSE `media_execution` policy + durable `task_jobs` (профильный deadline, сохранённый статус, `unknown_after_disconnect`, `media_execution.py:24–58`); profile-deadline отделён от HTML/chain 360 c; рабочий video pipeline не урезается (окна/`MEDIA_EXECUTION_POLICY_ENABLED` не трогаются).

**На пределе — явный результат и причина:** существующая graceful-деградация (`chain_timeout`/`chain_call_limit`/`chain_cost_limit`) + канонический `denied`-статус; коды `tool_step_limit`/`deadline_exceeded`/`financial_limit_reached` уже в словаре; бесконечного продолжения нет.

**OFF-parity:** `TOOL_CHAIN_LIMITS_ENABLED=false` → baseline цикла; новые env-числа при дефолтах — no-op.

---

## 4. D3 — Идемпотентность side effects и `delivery_unknown`

**Operation state — REUSE, второй очереди/леджера нет:** `task_jobs` (mca-01: `job_id` = operation id; `coalesce_key` = idempotency key; `status`/`reason_code`/`attempt`; `task_supervisor.py:407–457`), durable `mca_bot_outputs` + content-hash барьер (mca-22; `bot_output_ledger.py:1–18`, `database.py:806–844`), `mca_watchdog.mark_delivery_unknown` (`:239–253`), `mca_trace` guard (`:512–517`: `delivery_unknown` → `reconcile_required`, слепой retry запрещён).

**Idempotency key:** детерминированный `sha1-16(chat_id|correlation_id|tool|args_fingerprint|op_kind)` — R17-safe, стабилен в пределах хода; передаётся в durable side-effect ops как `coalesce_key`/correlation; в события/envelope — только хэш.

**Провайдерская идемпотентность:** использовать там, где API её поддерживает (ключ/заголовок из адаптера); где не поддерживается — не изобретать; **exactly-once не обещать** (`:748`).

**Правило повтора:** повтор запрещён при `delivery_unknown` и при подтверждённом успехе; разрешён только `retryable=true` + идемпотентная операция + отсутствие неясного состояния; граница — §3.

**`delivery_unknown`:** неясный исход Telegram-отправки или платного провайдера (в т.ч. media disconnect после submit) → статус `delivery_unknown`, reason_code `delivery_unknown` (существующий), без слепого повторной отправки/генерации (A21: ровно один внешний вызов).

**OFF-parity:** K2 `MCA_TOOL_DELIVERY_GUARD_ENABLED=false` → без новой деривации ключа/маркировки из этого контура; существующие mca-22/mca_trace-гарды не меняются.

---

## 5. D4 — Учёт расходов (unknown ≠ 0)

**Единственный денежный леджер — `llm_usage_events` (PG)** (`usage_events.py:29–146`); второй леджер запрещён. Расширение **код-only**: `SOURCES += "embedding"` (и `"media"` при записи медиа-провайдеров). Точки записи: LLM-чат — существующая (`llm_client.py:517–546`); image — существующая (`image_generation.py:1073`); **новые**: embeddings — успешный `llm_client.embed` (model; токены из usage ответа, иначе честная оценка; цена через `llm_pricing`; нет цены → `price_known=false`); медиа/STT-провайдеры — где есть model/usage (иначе честный unknown в событии). Fail-open — как сейчас.

**Детализация по операции — `mca_events.usage_json`** (существующая колонка, `mca_events.py:539–548`; R17-safe): `{input_tokens, output_tokens, cached_tokens, tokens_estimated, cost_usd|null, price_known, currency:"USD", price_version, source}`; provider/trigger/stage — существующие колонки `mca_events` (`provider`, `stage`, `model`, `operation_id`). Единственный сборщик агрегатов — `execution_graph_source` (`:26–27, :500–511`; второй запрещён).

**unknown ≠ 0:** нет цены/ошибка тарифов → `price_known=false`, стоимость = **unknown** (в леджере placeholder `0` + `price_known=false` — не заявление; в envelope/отчётности — `cost_usd=null`); агрегаты не показывают 0 при unknown (существующее правило сохраняется для новых источников). Валюта — USD (существующий контракт); `price_version = "price:<sha1-12(model|in|out)>"` либо `"unknown"`; мультивалютность не изобретается.

**Разрез** чат/операция/trigger/модель/provider — из существующих строк+событий; единицы/область/значение/причина и различение финансов/токенов/concurrency/размер/deadline/антиспам — контракт полей (UI — mca-17c).

**OFF-parity:** K3 `MCA_COST_ACCOUNTING_ENABLED=false` → без новых точек записи/полей usage_json; существующая аналитика не меняется.

---

## 6. D5 — Денежные лимиты нового механизма: `enabled=false`

**Модуль:** `services/mca_money_limits.py` (единственный механизм; не смешивать с token/context-бюджетами).
**Конфиг (env-only):** master `MCA_MONEY_LIMITS_ENABLED=false` (санкционированное исключение из default-ON: owner §20.2 `:1026`, §2.7); per-scope `MCA_MONEY_LIMIT_DIRECT_USD`, `MCA_MONEY_LIMIT_AUTONOMOUS_USD`, `MCA_MONEY_LIMIT_MAINTENANCE_USD` — sentinel-семантика REUSE `budget_limits.py:1–24` (**не задан** → лимита нет; `0` → запрет; `<0` → безлимит; `>0` → cap USD). Скрытого «рекомендованного бюджета» нет: числовых дефолтов не существует.

**API (инертный при OFF):** `check_and_reserve(scope, estimate_usd, price_known)` / `reconcile(actual_usd, price_known)` / `effective_state()`. Резервирование ожидаемой стоимости конкурентных операций — in-process (один процесс); при неизвестной цене — резерв не делается, абсолютный потолок не обещается; deny только при известных spent+reserved ≥ cap. При исчерпании: платные вызовы стоп (ToolResult `denied` + `financial_limit_reached`), приём/сохранение исходных сообщений не блокируются; приоритет direct > autonomous > maintenance, сначала уменьшается необязательная инициатива/фон (потребление — mca-09/10b; mca-11 даёт гейт+семантику). Overshoot неточной оценки согласуется после ответа (`reconcile`).

**Существующие явные финансовые настройки владельца не стираются:** `IMAGE_DAILY_LIMIT_ENABLED`/`WORKER_DAILY_IMAGE_CALLS_*` (`settings.py:1413–1416`), `chat_usage`, `worker_budget`, `auto_budget` — как есть; отличие задокументировано: это unit/вызовные лимиты, а не валютные бюджеты; показ различия — через `effective_state()` + существующие настройки (UI — mca-17c).

**OFF-parity:** master=false (дефолт) → модуль не влияет ни на один вызов; поведение 2.58.56 байт-в-байт; без per-call шума телеметрии.

---

## 7. D6 — `tools.chain`: стадии исполнения/доставки/учёта

**AMEND реестра (mca-17a):** `ProcessDefinition tools.chain` v1→**v2** (`mca_process_registry.py:564–577`): `stages=("route","execute","deliver","account")`; `stages_to_events={"execute":"tool_call","deliver":"tool_delivery","account":"tool_accounting"}`; `instrumentation=("execute","deliver","account")`; `enabled_gate="MCA_TOOL_CHAIN_STAGES_ENABLED"`; `widget_id="Tool chain"` (сохраняется; контракт для mca-17c) + `event_names`; `settings_ref += (MCA_TOOL_RESULT_ENABLED, MCA_COST_ACCOUNTING_ENABLED)`; note обновляется.
**События** — через `emit_mca_event` (единственное durable-хранилище `mca_events`, `mca_events.py:508–536`), `component="tools"`, стадия в `stage`, reason_code из единого словаря, R17-safe (id/числа/коды/`args_fingerprint`; без текстов/аргументов). Без нового шума: notable-only (терминал вызова, `delivery_unknown`, accounting-unknown).
**OFF:** `MCA_TOOL_CHAIN_STAGES_ENABLED=false` → новых стадийных событий нет; реестр отдаёт честный `not_run` (конвенция mca-17a). UI не делается (mca-17c).

---

## 8. D7 — Kill-switches (точный список; env-only, Δ каталога=0)

| # | Имя | Default | OFF-паритет (2.58.56) |
|---|---|---|---|
| K1 | `MCA_TOOL_RESULT_ENABLED` | ON | envelope байт-в-байт legacy (`ok/error/skipped`, без новых ключей) |
| K2 | `MCA_TOOL_DELIVERY_GUARD_ENABLED` | ON | без новой деривации idempotency-key/маркировки; mca-22/mca_trace как есть |
| K3 | `MCA_COST_ACCOUNTING_ENABLED` | ON | без новых точек записи/usage_json; существующая аналитика как есть |
| K4 | `MCA_TOOL_CHAIN_STAGES_ENABLED` | ON | без стадийных событий; registry `not_run` |
| K5 | `MCA_MONEY_LIMITS_ENABLED` | **OFF** | денежные лимиты отключены — поведение baseline (это feature-гейт, не kill-switch) |

Все — `ClassVar` в `config/settings.py`, per-call resolve, не бросают; регистрируются в `mca_gates.KILL_SWITCHES` (`mca_gates.py:29+`; прецедент mca-08/15 `:280–291`). **Переиспользуются, не дублируются:** `TOOL_CHAIN_LIMITS_ENABLED`, `TOKEN_ANALYTICS_ENABLED`, `MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED`, `MCA_BOT_OUTPUT_LEDGER_ENABLED`. Env-only числа §3 — не каталог.

---

## 9. D8 — Санкции T-4944 (поимённо)

1. **Δ DDL = 0.** Новых таблиц/колонок/версий нет: SQLite остаётся **v26**, миграции нет, backup-guard N/A; PG — **no-op** (`pg_db.py` вне diff). Обоснование: idempotency key живёт в `coalesce_key` `task_jobs`; usage-детализация — в существующем `mca_events.usage_json`; деньги-лимиты — env+in-memory; новой durable-потребности нет. REUSE: `task_jobs`, `mca_bot_outputs`, `mca_events`, `llm_usage_events`.
2. **Δ каталога = 0** (env-only `ClassVar`; `param_catalog.py`/TSV не трогаются; F8 **NOT_APPLICABLE**; 489 без изменений).
3. **Tool-поверхность: канон 12 не меняется** (`tool_schemas.py:547`); новых инструментов/схем нет; active-tools гейты не меняются.
4. **reason_code: ровно +1** — `cost_unknown` (аддитивно в единственный `mca_events.REASON_CODES`, `mca_events.py:60–240`). Все прочие причины переиспользуются: `delivery_unknown`, `financial_limit_disabled`, `financial_limit_reached`, `tool_step_limit`, `deadline_exceeded`, `provider_unavailable`, `timeout`, `disabled`, `job_not_allowed`, `rate_limit`. Второго словаря нет.
5. **Risk: R2** (подтверждение планового `mca-round1027-plan.md:203`): нет DDL/миграций, нет изменений auth/прав и публичных контрактов; контракт аддитивен, денежные лимиты OFF; `threat-failure-analysis.md` не требуется.
6. **Deploy: CA-11 per-feature bump** — `APP_VERSION 2.58.56 → 2.58.57` (`settings.py:2861`; прецедент mca-06/08/15), пер-фичевый деплой; проверки: health/версия, **0 env-оверрайдов** (K1–K4 ON, K5 OFF), focused-повтор, R17=0, F8 n/a; **rollback-контур:** soft — K1–K4=false (K5 остаётся OFF), cold — git revert (v26 мультивалидна, миграций нет).
7. **Merge:** `ARCHITECTURE.md` **§117** + ADR-1028-13 → Accepted (по merge); live-часть — `PENDING OWNER` (no-false-acceptance `:15167`).

---

## 10. D9 — Границы и handoff

mca-09: Decision/action-schema не тронуты; ToolResult/числа §3 — вход её loop'а. mca-10b: те же инструменты/лимиты, без второго контура. mca-16: расходы — не reward. mca-17c: widget-ID `"Tool chain"`, стадии и единицы (calls/ms/USD/tokens) — контракт; UI не делается. mca-release: effective state §20.2 — деньги OFF. mca-15: маппинг §2.5; контракт mca-15 не подменяется.

---

## 11. REQ → приёмки → задачи

| REQ | Решения spec | Приёмки | Задачи |
|---|---|---|---|
| MCA11-R1 | D1, D2, D3 | A20 `:901`, A21 `:902` | T-4945–T-4949 |
| MCA11-R2 | D4 | A21 `:902` | T-4950–T-4952 |
| MCA11-R3 / GEN-R7 | D5, D7-K5 | A28 `:909`, §20.2 `:1026` | T-4953–T-4955 |
| GEN-R17 | D6 | A48/A73 (частично) | T-4956–T-4957 |
| Санкции/сводка/ревью | §9 | §19 `:874–976` | T-4958–T-4959 |
| Deploy/live/reconcile | §9.6 | §20 `:986–1045` | T-4960–T-4962 |

## 12. OFF-паритет по решениям

D1→K1, D2→`TOOL_CHAIN_LIMITS_ENABLED` (существующий), D3→K2, D4→K3, D5→K5 (OFF по умолчанию — сам baseline), D6→K4. Каждый OFF = поведение 2.58.56; дефолты K1–K4 не меняют поведение (аддитивность), K5 — off по owner-требованию.

**Статус документа:** `DESIGN_FROZEN` — санкции §9 обязательны для T-4945+; `plans/current_task.md` не изменялся (R17).
