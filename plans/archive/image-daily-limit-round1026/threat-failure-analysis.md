# A5 `image-daily-limit-round1026` — Threat / Failure Analysis (T-3599, Risk R3)

Формат: **threat → mechanism → code → test (named)**.
All threats are adversarial: expected failure modes under concurrency, crash, TZ
boundaries, config drift and degradation. Tests live in
`tests/test_image_daily_limit_round1026.py` unless noted.

## T1 — Double-spend race (double consumption / quota leakage)
- **Threat:** при остатке 1 квоты два одновременных запроса проходят проверку и оба списывают (check-after-increment).
- **Mechanism:** baseline `consume` делал UPSERT затем сравнение `used <= limit` (без атомарного условия); при гонке оба видели `used=0`.
- **Code:** `services/worker_budget.py:75-82` `RESERVE_INCREMENT_SQL` — условный `... WHERE worker_budget.used < $4 RETURNING used`; `reserve_image` `:667-675`; отказ per-chat откатывает shared `:701-704`.
- **Test:** `TestA2Race::test_two_concurrent_reserves_exactly_one` (asyncio.gather, limit=1 → ровно один `reserved`, второй `denied`, `used ≤ 1`).

## T2 — Fail-open truncation (partial consumption on PG failure)
- **Threat:** сбой PG в середине резерва оставляет частичный расход (shared инкрементирован, chat нет) или «теряет» квоту без честного учёта.
- **Mechanism:** несколько отдельных UPSERT без общей транзакции; исключение между ними.
- **Code:** `services/worker_budget.py:621-716` — весь reserve в `async with conn.transaction()`; исключение → `:710-716` fail-open `ok=True reason='failopen'`, транзакция целиком откатывается.
- **Test:** `TestA7KillSwitchFailOpen::test_pg_error_failopen_no_partial_consumption` (`_BoomConn` падает на shared-инкременте → budget/res пусты, reason='failopen'); `test_hotfix5...` (baseline fail-open паритет).

## T3 — Idempotency conflict / replay double-spend
- **Threat:** повторная обработка того же сообщения (retry/повторная доставка update) списывает квоту второй раз.
- **Mechanism:** нет ключа дедупа; два пути (direct/tool) могли оба дойти до генерации.
- **Code:** `services/worker_budget.py:106-112` `RESERVATION_INSERT_SQL ON CONFLICT DO NOTHING`; replay-ветка `:641-651`; `services/image_generation.py:1098-1109` (`already_ok`/`deny`).
- **Test:** `TestA4Idempotency::test_same_key_no_double_spend`; `test_replay_denied_returns_prior_outcome`; `TestA5DeliveryFailure::test_send_failure_commits_and_no_second_generation` (replay → `already`, `calls==1`).

## T4 — TZ / reset boundary error
- **Threat:** день считается глобальной TZ или «24ч от первого запроса»; `next_reset_at` неверен; смена лимита обнуляет `used`.
- **Mechanism:** baseline день — глобальный `WORKER_BUDGET_TZ`; per-chat TZ не резолвился.
- **Code:** `services/worker_budget.py:506-567` (`_chat_tz_name`/`image_day`/`image_timezone`/`image_next_reset`), reuse `resolve_timezone`; `:791-810` `image_limits`; `:813-874` `image_usage_summary`.
- **Test:** `TestA6Timezone::test_day_and_next_reset_use_chat_tz` (UTC+14: day по TZ чата, reset = следующая полночь); `TestA6Timezone::test_limit_change_does_not_zero_used` (used=1 до и после смены 5→10).

## T5 — Catalog / UI duplicate setting (double source of truth)
- **Threat:** лимит изображений продублирован как независимая настройка в двух формах (§50) или смешан «глобальный дефолт» с «общей квотой всех чатов» (§30).
- **Mechanism:** добавление отдельного env-ключа/второго параметра для shared-квоты либо отдельной UI-панели.
- **Code:** `services/param_catalog.py:1507` `IMAGE_DAILY_LIMIT` (единственный `limits.image_daily_limit`); shared — env-only `WORKER_DAILY_IMAGE_CALLS_GLOBAL` (200) без каталожного ключа (`worker_budget.py:367-374`); UI — врезка в существующий `mod_images` (не отдельная панель).
- **Test:** `tests/test_param_catalog.py` (счётчики 470/427/445/101/99/21); `tests/test_webapp_gates_api.py::TestWorkersBudget::test_image_usage_additive_fields` (per-chat limit=60 vs shared=200, source='env'); `tests/test_webapp_f5_round1025.py::test_workspace_metadata_present`.

## T6 — R17 leak (content in logs/journal)
- **Threat:** в журнал/логи попадают сырые тексты/промпты/URL/ключи.
- **Mechanism:** генератор логирует промпт/ответ; idem-ключ строится из контента.
- **Code:** `services/pg_db.py:359-379` — таблица `image_reservation` хранит только `reservation_key/chat_id/source/message_id/day/status/error_code/delivery_failed`; `services/worker_budget.py:103-105` (R17-комментарий); `services/image_generation.py:212-230` idem-key только из id/enum (не из текста, §37); логи `:1100-1114` — только `chat/source/status/reason`.
- **Test:** `tests/test_unified_image_request_round1026.py` (source normalization, канон); `tests/test_pg_db.py` (схема `image_reservation`); `TestA7...` (логи fail-open без контента — caplog проверяется в `test_summary_l2_writer`/A3).

## T7 — Quota loss on crash (reserve without outcome)
- **Threat:** процесс падает между reserve и generate/commit → квота навсегда «съедена» без результата.
- **Mechanism:** резерв пишется до платного вызова; без release-пути на краш остаётся `reserved`.
- **Code:** `services/image_generation.py:1164-1196` — `reserve → generate → commit/release`; сбой генерации → release (`:1182-1187`); retention журнала 30 дней (`worker_budget.py:570-594`) убирает «зависшие» строки.
- **Test:** `TestA3DenyRelease::test_generation_failure_release_restores` (release возвращает shared+chat к 0); `TestA3DenyRelease::test_deny_does_not_consume` (denied-строка персистентна для аудита, квота не тронута).

## T8 — Concurrent reserve overshoot (journal vs counter divergence)
- **Threat:** под конкурентным воркером число `committed`+`reserved` в журнале превышает `used` счётчика или наоборот.
- **Mechanism:** журнал и счётчик пишутся не в одной транзакции/условие не атомарно.
- **Code:** `services/worker_budget.py:622-709` — INSERT журнала + оба условных инкремента в одной транзакции; denied/replay не инкрементируют; `image_usage_summary` выводит агрегаты из журнала, `used` — из `worker_budget` (не второй счётчик, D6).
- **Test:** `TestA1HappyPath::test_reserve_commit_once` (used=1, journal committed, commit не реинкрементирует); `TestA2Race::test_two_concurrent_reserves_exactly_one` (used=1 при двух попытках); `TestA4Idempotency::test_replay_denied_returns_prior_outcome`.

## T9 — Delivery failure charged correctly (no auto re-generation)
- **Threat:** успешная генерация не доставлена → лимит не списан ИЛИ запускается повторная платная генерация.
- **Mechanism:** commit до отправки; при сбое доставки нет повторного вызова.
- **Code:** `services/image_generation.py:1195-1218` — commit ДО отправки; сбой → `commit(delivery_failed=True)` + `reason='send_failed'`, повторной генерации нет.
- **Test:** `TestA5DeliveryFailure::test_send_failure_commits_and_no_second_generation` (status=committed, delivery_failed=True, `calls==1`, replay → `already`).

## T10 — Kill-switch / master OFF regression
- **Threat:** OFF kill-switch не даёт байт-в-байт legacy (создаёт журнал/резерв) или master-рубильник обходится.
- **Mechanism:** OFF должен идти через legacy `consume` внутри `generate`.
- **Code:** `services/image_generation.py:202-209` `image_daily_limit_enabled`; `:1069-1076` OFF → `('legacy','','kill_switch_off')`; master OFF → `budgets_off`.
- **Test:** `TestA7KillSwitchFailOpen::test_kill_switch_off_is_legacy`, `::test_kill_switch_off_generate_consumes_like_baseline` (`consume_budget=True`), `::test_master_budget_off_is_legacy`.

## T11 — §104 generator mutation
- **Threat:** обвязка резерва незаметно изменила платный вызов/промпты/порядок публикации.
- **Mechanism:** рефактор `generate_and_send` мог затронуть `generate`/провайдер.
- **Code:** `services/image_generation.py:1140-1196` оборачивает неизменяемый `generate` (`:872+`); A5 не меняет модель/провайдер/ключи/промпты.
- **Test:** `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_104_generator_functions_ast_identical` (`generate`/`generate_image(_verbose)` AST-identical vs `e8646af`; `generate_and_send` санкционированно исключён с A5 NOTE).

## T12 — Master budget gate bypass via content
- **Threat:** контент (URL/LLM-вывод) может отключить лимит/очередь (§37-инвариант).
- **Mechanism:** лимиты/idem-ключ/scope/TZ читаются из admin-конфига, а не из пользовательского текста.
- **Code:** `services/image_generation.py:212-230` (idem-key из служебных полей); `worker_budget.py:506-535` (TZ из `limits.chat_timezone`, не из контента); `_metric_limit` `:358-396` (только каталог/env).
- **Test:** `tests/test_unified_image_request_round1026.py::TestUnifiedContract::test_source_normalization` (source ∈ direct/tool); `TestA7KillSwitchFailOpen::test_master_budget_off_is_legacy`; `tests/test_budget_guardrails_round1024.py` (§37-инвариант бюджета).
