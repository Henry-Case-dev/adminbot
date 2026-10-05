# MCA-11 `mca-11-tools-costs` — evidence (Builder, блоки A+B+C+D, T-4945…T-4958)

**Дата:** 05.10.2026. **Статус:** блоки A+B+C+D реализованы; focused зелёные; OFF-паритет K1–K5 подтверждён; интегрированный пакет — **859 passed / 2 failed** (оба предсуществующие, классифицированы ниже).
**Санкции:** ADR-1028-13 D7/D8 (Δ DDL=0, Δ каталога=0, канон 12 без изменений, reason_code ровно +1 `cost_unknown`, Risk R2).
**Вне этого среза:** T-4959+ (Reviewer/deploy/live); `plans/current_task.md`/`workflow_state.md` не менялись.

## Fingerprint (worktree, без commit)

- HEAD: `a34e1632538840fe36f6d81446ff6b6ad54db7fa` (a34e163).

Блоки C+D (этот срез; `git hash-object`):

- `services/mca_money_limits.py` (новый) `9b0c3f434e3d8b979f6091aee40769b9e1fc7953`
- `services/tool_result.py` `2a0be38788399ae3146bc25d5f8a7209e4aa18fa`
- `services/tool_loop.py` `6588cf581f481208f8f30c2e199a739deaffc9f2`
- `services/mca_process_registry.py` `7b3b8a55a1e1e9dd66a793277f16f46132da097f`
- `services/mca_gates.py` `716085f55a52407c3ea70ce40719229bfb40ca89`
- `config/settings.py` `488c654b2c3bfeb4df73d0810420390a72056e8c`
- `tests/test_mca11_money_limits_round1028.py` (новый) `6e31ec97607a73883c2e079980b4ffd87ac8160f`
- `tests/test_mca11_chain_stages_round1028.py` (новый) `6811d0086d42098642f4665f561084e1a3c89bc3`

Блоки A+B (не менялись в этом срезе, кроме `tool_result.py`/`tool_loop.py` выше):

- `services/tool_router.py` `92dc813088015e72cef91934d7b952c5779dc0f0`
- `services/web_content_extractor.py` `380d25cf3fdc0c4383b9341b92266713c8fd360c`
- `services/media_execution.py` `d6e2894968331bef3b1e697f3525d65a77c03eb6`
- `services/image_generation.py` `1690af09c732946fabc99fca361f654bfc052cbd`
- `services/llm_client.py` `209eecba16d72391334c357b5d861c5c20da6363`
- `services/usage_events.py` `d7e4fc335bd4ba10473e552c83c41c5d8e71607d`
- `services/llm_pricing.py` `7c9942143a8ce4b861b7959ab6c628d106ab3eb0`
- `services/mca_events.py` `615290eb9029766f889b0cc5786e591d2a64596b`
- `tests/test_mca11_tool_result_round1028.py` `87427bacdfbf32f575d6723bf725dc9205791047`
- `tests/test_mca11_costs_round1028.py` `1f6f34130b528d62b081987f58ce178b88ac6a5c`
- `tests/test_tool_chains_round1026.py` `22f3e23d5d0a6d32d0cf20142488b0afb9ab062d`

Не тронуты: `plans/current_task.md`, `plans/workflow_state.md`, каталог (`param_catalog.py`, 489), DDL/миграции (`database.py`/`pg_db.py` вне diff), `tool_schemas.py` (канон 12).

## Блок A (T-4945…T-4949) — сводка

- **T-4945 ToolResult:** единый модуль `services/tool_result.py` — 7 статусов, категории канона 12 (`memory_read/external_read/paid_media/admin`; неизвестный → `external_read`, никогда `admin`), правила `retryable`, каноническая envelope (legacy-ключи + `category/retryable/duration_ms/usage/external_operation_id/evidence_refs/partial`), A20-инвариант («ОШИБКА …»/JSON `status:error` ≠ ok), legacy `skipped→denied`, `not_found`/`unsupported→empty`, `partial` сохраняется, отказ политикой → `denied/disabled`. Права не расширены.
- **T-4946 Лимиты:** env-only ClassVar'ы `MCA_TOOL_MAX_TOTAL_CALLS=6`/`MCA_TOOL_MAX_METERED_CALLS=4`/`MCA_TOOL_MAX_SAME_CALL=2`/`MCA_TOOL_CHAIN_TIMEOUT_SECONDS=360`/`MCA_TOOL_TRANSIENT_RETRIES_MAX=2` поверх master `TOOL_CHAIN_LIMITS_ENABLED` (не дублируется); на пределе — `denied` + `data={kind,unit,scope,value,reason}` + прежняя graceful-деградация `chain_*`; media async deadline независим от chain 360 c.
- **T-4947 Идемпотентность:** `idempotency_key()` = sha1-16(chat|corr|tool|args_fp|op_kind); K2-gated передача в durable `begin_media_job` (coalesce); `delivery_unknown` для неясной Telegram-доставки; слепой повтор после `ok`/`delivery_unknown` не диспатчится; exactly-once не обещается.
- **T-4948 Потребители:** tool_loop/tool_router/ToolContext, `fetch_article` поверх SafeFetcher (`code/stage/retryable` → ToolResult), платные медиа (status/delivery_unknown/usage), mca-15 (маппинг MetricResult без подмены payload).
- **T-4949 Тесты:** `tests/test_mca11_tool_result_round1028.py` — 38 passed.

## Блок B (T-4950…T-4952) — сводка

- **T-4950 Учёт:** `usage_events.SOURCES += ("embedding","media")`; новая K3-gated точка записи — успешный `llm_client.embed` (токены из usage иначе честная оценка; нет цены → `price_known=false`); `usage_detail()`/`price_version()` — контракт `mca_events.usage_json` (cost_usd=null при unknown).
- **T-4951 Аналитика/единицы:** второй сборщик не создан — REUSE `web/api/analytics.py` + `execution_graph_source` (unknown → `cost=None`, не 0); единицы/область/значение/причина — `tool_result.LIMIT_KINDS`/`limit_record` (money=usd/operation, context_tokens=tokens, concurrency=slots, payload_size=bytes, deadline=seconds, antispam=events, freshness=seconds).
- **T-4952 Тесты:** `tests/test_mca11_costs_round1028.py` — 18 passed.
- reason_code `cost_unknown` добавлен ровно +1 в `mca_events.REASON_CODES` (итог по фиче: **+1**; больше не добавлялось).

## Блок C (T-4953…T-4955) — денежные лимиты OFF

- **T-4953 Механизм:** новый `services/mca_money_limits.py` — единственный денежный лимит-контур; master K5 `MCA_MONEY_LIMITS_ENABLED` (**default OFF**, owner §20.2) + per-scope `MCA_MONEY_LIMIT_{DIRECT,AUTONOMOUS,MAINTENANCE}_USD` (env-only, БЕЗ числовых дефолтов — скрытого «рекомендованного бюджета» нет). Sentinel-семантика REUSE `budget_limits.budget_state`: не задан → лимита нет; `0` → запрет; `<0` → безлимит; `>0` → cap USD. Не смешивается с token/context-бюджетами. Существующие настройки владельца (`IMAGE_DAILY_LIMIT_ENABLED`, `WORKER_DAILY_IMAGE_CALLS_*`, `CHAT_GLOBAL_KEY_BUDGET_*`, `WORKER_DAILY_LLM_*`) не тронуты и показаны в `effective_state()` как unit/вызовные/токенные лимиты (≠ USD; UI — mca-17c). K5 зарегистрирован в `mca_gates.KILL_SWITCHES` (default False).
- **T-4954 Семантика будущего включения:** `check_and_reserve(scope, estimate_usd, price_known)` (in-process резерв конкурентных операций; при неизвестной цене резерв не делается, `ceiling_exact=false`, абсолютный потолок не обещается; deny только при известных `spent+reserved ≥ cap`); `reconcile(actual_usd, price_known, *, scope=direct)` (снятие резерва FIFO + факт в spent; overshoot неточной оценки виден); `degradation_order()` = maintenance → autonomous → direct (сначала необязательная инициатива/фон, приоритет direct); deny = `allowed=False` + `financial_limit_reached` (контракт ToolResult `denied`); intake/сохранение сообщений не гейтятся (модуль не вызывается intake-путями; runtime-вызовов нет — инертен, потребители mca-09/10b).
- **T-4955 Тесты:** `tests/test_mca11_money_limits_round1028.py` — **24 passed** (A28 default-OFF/inert, sentinel-семантика и reuse `budget_limits`, конкурентный резерв, overshoot/reconcile, unknown≠потолок, приоритеты, fixture «лимит исчерпан → платные вызовы стоп, intake жив», настройки владельца не тронуты, no-runtime-callers OFF-паритет).

## Блок D (T-4956…T-4957) — стадии tools.chain

- **T-4956 Реестр/стадии/события:** AMEND `tools.chain` v1→**v2** (`mca_process_registry.py`): `stages=("route","execute","deliver","account")`, `stages_to_events={"execute":"tool_call","deliver":"tool_delivery","account":"tool_accounting"}`, `instrumentation=("execute","deliver","account")`, `enabled_gate="MCA_TOOL_CHAIN_STAGES_ENABLED"` (K4, default ON; резолвер в `_GATE_RESOLVERS`), `widget_id="Tool Chain"` сохранён (контракт mca-17c), `event_names`, `settings_ref += (MCA_TOOL_RESULT_ENABLED, MCA_COST_ACCOUNTING_ENABLED)`. Эмиссия — только через `emit_mca_event` (единственный durable-store `mca_events`), `component="tools"`, стадия в `stage`, notable-only: `tool_call` при notable-терминале (error/timeout/cancelled/denied; chain-лимиты → mapped `deadline_exceeded`/`tool_step_limit`/`financial_limit_reached` из единого словаря), `tool_delivery` при `delivery_unknown`, `tool_accounting` при accounting-unknown (`cost_unknown`, `usage_json` = `tool_result.usage_detail`). R17-safe: `entity_ids={"tool","args_fingerprint"}` + коды/числа (`chat_id`/`trace_id`/`duration_ms`/`attempt`); без текстов/аргументов/URL. K4 OFF → стадийных событий нет; реестр честно `disabled` (гейт) / `not_run` (нет событий) — конвенция mca-17a.
- **T-4957 Тесты:** `tests/test_mca11_chain_stages_round1028.py` — **13 passed** (контракт v2, runtime-статусы, notable-only успех/ошибка/отказ, delivery+account unknown, маппинг chain-кодов, K4 OFF, R17-скан: секрет в args/output не попадает в события, `usage_json` — только числа/коды, `entity_ids` — ровно tool+fingerprint).

## Команды и результаты (focused)

1. `pytest tests/test_mca11_money_limits_round1028.py tests/test_mca11_chain_stages_round1028.py -q` → **37 passed** (24+13).
2. `pytest tests/test_mca11_tool_result_round1028.py tests/test_mca11_costs_round1028.py tests/test_tool_chains_round1026.py tests/test_mca17a_observability_core_round1027.py -q` → **171 passed** (A+B + реестр/скан имён событий).
3. **T-4958 интегрированный пакет:** `pytest tests/test_mca11_money_limits_round1028.py tests/test_mca11_chain_stages_round1028.py tests/test_mca11_tool_result_round1028.py tests/test_mca11_costs_round1028.py tests/test_tool_chains_round1026.py tests/test_tool_loop.py tests/test_tool_router.py tests/test_tool_schemas.py tests/test_direct_chat.py tests/test_direct_two_call_round1022.py tests/test_negative_constraints_round1022.py tests/test_media_execution_asap32.py tests/test_image_generation_round1023.py tests/test_unified_image_request_round1026.py tests/test_image_daily_limit_round1026.py tests/test_token_analytics_round1023.py tests/test_webapp_analytics_api.py tests/test_summary_execution_graph_round1026.py tests/test_mca15_chat_statistics_round1028.py tests/test_mca22_core_round1027.py tests/test_mca02_safe_fetch_round1027.py tests/test_migrate_env_to_pg.py -q` → **859 passed, 2 failed** (оба предсуществующие — ниже).
4. K4-OFF-паритет: `MCA_TOOL_CHAIN_STAGES_ENABLED=false pytest tests/test_tool_chains_round1026.py tests/test_mca11_tool_result_round1028.py tests/test_mca11_costs_round1028.py -q` → **101 passed** (как baseline A+B; стадийных событий нет — unit-тест `test_k4_off_no_stage_events` с перехватом эмиттера).
5. R17-скан: добавленные log/emit-сайты ревизованы (только коды/числа/fingerprint/scope); тесты `TestR17` (2) + `test_no_payload_in_logs`/`test_fetch_article_url_not_logged` зелёные; сырых args/output/URL в событиях нет.

## OFF-паритет

- **K1 OFF** (`MCA_TOOL_RESULT_ENABLED=false`): envelope — прежние 12 ключей, статусы `ok/error/skipped`; `TestK1OffParity` + limit/timeout legacy-тесты.
- **K2 OFF**: без маркировки `delivery_unknown`/гарда/idempotency key — `test_k2_off_no_marking_and_no_guard`.
- **K3 OFF**: без новой точки записи embeddings — `test_k3_off_no_new_write_point`.
- **K4 OFF**: без стадийных событий (перехват эмиттера пуст), реестр `disabled`/`not_run`; п. 4 — 101 passed.
- **K5 OFF (default)**: модуль инертен — `check_and_reserve` → `allowed=True/state=off` даже при cap=0, `reconcile` no-op, runtime-вызовов нет (`test_no_runtime_callers_off_parity`), настройки владельца не меняются; поведение 2.58.56.
- **Дефолты чисел** = прежние код-константы (6/4/2/360/2); Δ каталога=0 (`test_env_numbers_not_in_catalog`, `test_catalog_counts_unchanged` 489 — в п. 3).

## REUSE (не дублировано)

- mca-22 ledger/дедуп, `mca_watchdog.mark_delivery_unknown`, `mca_trace` — не менялись; mca-01 `task_jobs.coalesce_key` — единственное durable-состояние операции; mca-02 `SafeFetchError` — единственный error-контракт внешнего чтения; mca-15 `MetricResult`/count status — авторитетен в payload; mca-13 `REASON_CODES`/`mca_events` — единственный словарь/стор (стадии — через `emit_mca_event`); `execution_graph_source`/`web/api/analytics.py` — единственный сборщик; `budget_limits` — sentinel-семантика денежных лимитов (второй механизм не создан).

## Предсуществующие красные (не этот срез; не чинились)

1. `tests/test_tool_loop.py::TestChatWithTools::test_query_chat_memory_count_reaches_model` — ожидает старую фразу mca-15 («Найдено N упоминаний»), получает новый stats-вывод; **зелёный при `MCA_CHAT_STATISTICS_ENABLED=false`** (проверено). Файл не менялся с `8c46132` (19.09.2026); `git diff HEAD` по файлу пуст.
2. `tests/test_migrate_env_to_pg.py::TestRunDryRun::test_run_created_and_idempotent_skip` — ожидает 21 ключ, фактически 22 (`keys.image_style_api_key`/`keys.embedding_quota_group_labels` из более поздних фич); файл не менялся с `cc1b960` (30.09.2026, extra-cover-style-pipeline 2.58.39); `git diff HEAD` по файлу и `services/config_migrations.py`/`pg_db.py`/`database.py` пуст.

## Риски / заметки

- `llm_client.embed_once` (control-plane embeddings, ASAP-4) не покрыт санкционированной точкой записи (`embed` legacy): расходы control-plane остаются невидимыми — открытый вопрос @Architect/Orchestrator (вне санкции).
- `SOURCES += "media"` добавлен по санкции, но писателя нет: медиа-провайдеры (STT) не отдают model/usage; изображение пишет `source='image'` (существующая честная unknown-строка).
- Spec §7 «OFF → реестр отдаёт честный `not_run`»: по конвенции mca-17a при выключенном гейте статус — `disabled`, `not_run` — когда инструментирование есть, но событий в сторе нет; оба статуса покрыты тестами (не расхождение реализации).
- K4/K5 — env-only; в проде дефолты: K1–K4 ON, K5 OFF (0 env-оверрайдов — зона T-4960).
