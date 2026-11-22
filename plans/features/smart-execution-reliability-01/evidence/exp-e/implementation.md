# Реализация EXP-E-TRUNC / EXP-E-LAG

Код: `services/mca_experience_jobs.py` @ `819361a71`.
Базовые тесты: `tests/test_exp_e_trunc_lag_amendment.py` (9).
Source-pin обновлён: `tests/test_mca16_experience_block_d_round1039.py`.

## 1. E-TRUNC: бюджет вместо универсальных 1500

Удалён `SEMANTIC_BATCH_MAX_TOKENS = 1500`. Один вызов теперь получает
`semantic_output_budget(rows, capability, attempt, input_chars)`:

```
expected = 512 + 48 * min(rows, 32)
margin   = max(256, 25% * expected)
reserve  = 0, если capability.supports_reasoning is False, иначе 2048
budget   = expected + margin + reserve
if attempt > 1: budget = min(8192, budget * attempt)
if capability.max_output: ceiling = min(8192, max_output)
budget   = max(1024, min(budget, ceiling))
if capability.context_window:
    budget = min(budget, context_window - input_chars/4 - 256)
```

Ключевые свойства:

- 50 строк: `512 + 48*32 + 512 + 2048 = 4608` (не 1500); повтор —
  `8192`; при неизвестной модели расчёт консервативный, без «жёстких 1500».
- `max_output`/`output_token_field` берутся из существующего
  `services/model_capacity.resolve_model_capability`; неизвестность
  fail-open (None) не роняет проход.
- `finish_reason=length|max_tokens` / `response_kind=truncated_reasoning|
  reasoning_only` классифицируются типизированно (атрибуты существующего
  `LLMBadResponseError`), с текстовым fallback.
- До `SEMANTIC_OUTPUT_RETRY_ATTEMPTS=2` повторов (всего ≤3 вызова) с
  растущим бюджетом. Затем durable `semantic_truncation[chat]`
  (`count/last_at/reason/rows`) + уменьшение `row_limit` вдвое +
  существующий bounded backoff `semantic_retry` (900с → 6ч). Курсор стоит.
- Успех снимает backoff, но durable-история отказа остаётся диагностикой.
- Валидный `[]` и валидные кандидаты — единственные успешные исходы;
  reasoning-only в `raw` не попадает по построению (llm_client не
  подставляет reasoning в content).
- Типизированный parse, SourceRef/`record_feedback`, `dedup_key` не
  менялись.

Лимит строк одного вызова: `semantic_batch_rows_max()` = 120 (hot,
1..600, не больше `chats × per_chat`). Это «безопасное деление большого
окна»: прежние 6×50=300 строк в одном вызове — главный источник обрезки.

## 2. E-LAG: конкретные причины и исправление

### 2.1. Подтверждённые причины (recon `a6433095b`)

- 260/261 отказов — `truncated_reasoning`, 488 `finish_reason=length`;
- throughput 0, batches 0: `_semantic_llm_batch` → `None` → `break`,
  `_book_semantic_window` не вызывается;
- у основного чата нет `archive_start`/`archive_cursor`;
- `_semantic_window` всегда читает самые старые 50 строк → head-of-line;
- до 300 строк/вызов при бюджете 1500;
- lag 2 048 762 (COUNT), cursor 43 064, самый старый 2022-12-07.

### 2.2. Fresh-полоса (head-of-line) — в том же job

При измеренном отставании чата > `SEMANTIC_FRESH_LANE_LAG_ROWS` (5000)
включается durable `semantic_fresh[chat] = {boundary, cursor}`:

- `boundary = MAX(id)` на момент включения — **первый** id свежей полосы;
- `cursor = boundary - 1` (курсор хранит последний обработанный id);
- старый хвост читается `id > main AND id < boundary`;
- свежая полоса читается `id > fresh.cursor`;
- fresh-батч исполняется **один раз за проход, до старого хвоста**;
- строки `≥ boundary` не теряются: fresh-окно включает `boundary`;
- когда `main >= boundary - 1`, полосы сливаются:
  `main = max(main, fresh.cursor)`; дублей/пропусков нет (тест 9).

Миграционная семантика для существующего чата: `_init_chat_stream`
повторно **не применяется** (он сдвинул бы основной курсор через 2M
строк — запрещённый фиктивный сдвиг). Вместо этого fresh-граница ставится
на текущий `MAX(id)`; старый хвост остаётся в основном курсоре, честно
считается в lag и дренируется. Второго экстрактора/очереди/воркера нет.

### 2.3. Bounded catch-up

`semantic_catch_up_active` — только по **измеренному** `semantic_lag.rows`
(при недоступности — pending fallback). При lag > 5000:

| Предел | Обычный | Catch-up |
|---|---|---|
| батчей/проход | 12 | 36 |
| wall-clock | 180с | 600с (< тика 900с) |
| строк одного чата | 50 | 120 |
| строк на LLM-вызов | 120 | 120 |

Курсор/lag не подменяются; меняются только пределы одного прохода.
`max_instances=1/coalesce=True` и heartbeat после каждого батча сохранены.

### 2.4. Консистентность pending/cursor и планировщик

- `_book_semantic_window` уменьшает pending на прочитанное (не ниже 0),
  двигает позицию только вперёд, пишет `last_ts`.
- `_book_semantic_fresh_window` делает то же для fresh-курсора.
- `_measure_semantic_lag` считает `COUNT` по обеим полосам:
  `(main, boundary) + (fresh.cursor, ∞)` — обработанные свежие строки не
  выдаются за lag.
- `semantic_progress_snapshot.next_retry_at` + `semantic_backlog`: когда
  отложенный `retry_at` наступил, планировщик получает ненулевой backlog
  даже при `pending=0`; вечного ожидания суточной каденции нет.
- Discovery: при разрыве `watermark ↔ MAX(id)` выше обычного предела тот
  же SELECT читает bounded catch-up (5k); durable watermark и pending-cap
  backpressure сохранены. В production watermark уже почти догнал MAX —
  это не выдаётся за причину lag.

## 3. Production-арифметика (честная, без подмены)

Исходно: lag 2 048 762; inflow ≈ 77 строк/ч (465 за 6.04ч).

- catch-up: 36 батчей × ≤120 строк = ≤4 320 строк/проход;
- 96 проходов/сутки → ≤414 720 строк/сутки;
- 2 048 762 / 414 720 ≈ **4.94 суток** при полной успешности вызовов;
- inflow 1 848/сутки < throughput, значит хвост сходится, а не растёт;
- fresh-полоса: до 120 строк/проход против ~19 новых/проход (77/ч) —
  новые события не ждут архив.

Если после обрезки устойчивое окно меньше 120, throughput пропорционально
ниже (например, 60 строк → ~10 суток; 1 строка → ~1.6 года при 2M).
Реальный спад на production **не измерен** (нет деплоя) → RFL.

## 4. Что не менялось

- нет DDL/миграций/новых таблиц: всё в существующем payload `task_jobs`;
- нет второго job/экстрактора/очереди/LLM-клиента;
- не менялись `record_feedback`, `dedup_key`, typed candidate/SourceRef;
- не повышались пороги warning, не удалялась история, не обнулялся lag;
- `mod-acl-ux-01`, C3/ACL/UI/embedding/schema не затронуты.

## 5. Откат

- cold: `git revert 819361a71` (код+тесты; evidence отдельным коммитом);
- hot: `memory.experience_semantic_batches_per_run`,
  `..._catchup_batches_per_run`, `..._catchup_run_budget_seconds`,
  `..._batch_rows_max`, `..._fresh_lane_lag_rows`,
  `..._catchup_per_chat_max`, `..._discovery_catchup_limit`;
- OFF-путь обучения/ревью не менялся.
