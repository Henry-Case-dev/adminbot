# Postdeploy fix B03 — heartbeat/lease, per-attempt counters, bounded retry

Стабильный ID: **B03** (blocking postdeploy 2.58.235). Scope: только
`services/mca_experience_jobs.py`, тесты, evidence; DDL/ACL/UI/embedding не
затронуты. `progress_scope.json`/`workflow_state.md` не изменялись.
Deploy/SSH/LLM/prod не выполнялись.

- RED candidate: `066909923b1366e84e544b3aa5dfb3c7eb8fa18a`
  (behavior 2.58.235).
- Postdeploy evidence: `deploy-2.58.235.md` §7–§8,
  `postdeploy-attempts-2.58.235.md` (`161d81537`), recon `a6433095b`.
- Fix commit: `2b5347af46fd0a1520a2c7e5c51dbb05f6cad967`
  (поверх `066909923`).

## Факты 2.58.235

- Attempt 1 ~17.5 мин: watchdog `queued/attempt=2/reason_code=worker_lost`;
  heartbeat только на старте/редко (последний 11:27:13Z).
- Attempt 2 тоже `worker_lost`; attempt 3 — **failed /
  attempts_exhausted (3/3)** в 11:43:29Z, lifetime **1923 s** (32 мин);
  один `WATCHDOG_TAKEOVER outcome=failed`.
- **`COUNTERS={}`** — terminal payload без `semantic_*`; job ни разу не
  дошёл до персиста счётчиков. Приёмка счётчиков не доказана; прогресс
  только по курсорам (+465/+875), lag −489.
- Truncation: 4 события `rows=116/119 | budget=4608→8192 | attempt=1..3 |
  finish_reason=length`; на 8192 обрезка сохраняется.
  `fresh_lanes=2`, `deferred/truncated_chats=2`, `next_retry_at=11:41:27Z`.
- Heartbeat: у failed-строки `hb=updated` (gap 0), у завершённых
  `hb_gap_s == duration` (9–19 s) — периодического heartbeat нет.
  Точный триггер `worker_lost` (потеря worker в registry/watchdog или
  heartbeat-таймаут) остаётся **RFL**.
- Данные целы: `smart_messages +48` только приток, schema 48,
  ACL 4/0/3/1, positive writes 0, service health 2.58.235.

## Причины и исправление

1. **Heartbeat/lease.** `run()` делал heartbeat только на старте, а
   `_semantic_checkpoint` — после батча; один LLM-вызов/retry до 90с >
   watchdog lease. Добавлен периодический heartbeat (existing
   `heartbeat_period_seconds()`, clamp 0.2–60с) с
   `fencing_token=self._fence` на всё время `_semantic_extract`. `False`
   (fenced) → `_fence_lost`, `_FencedJob`, никаких checkpoint/finish;
   `_checkpoint`/`_finish` после fence не пишут.
2. **Counters/checkpoint.** После взятия lease сразу пишется базовый
   payload (counters/defaults), затем checkpoint после **каждой** LLM-
   попытки (`on_attempt`), а не только после батча. Terminal
   `failed`/`worker_lost` больше не оставляет `COUNTERS={}`.
3. **Bounded retry.** `SEMANTIC_OUTPUT_RETRY_ATTEMPTS=1` — максимум
   initial + 1 повтор (2 вызова), а не 3 попытки на одно 119-row окно.
   После первого отказа durable `semantic_truncation`/`row_limit`
   (половина) и retry_at пишутся до второго вызова; второй отказ не
   дробит окно повторно. `deadline` проверяется **до** первого батча,
   перед повтором и после батча; split/уменьшение окна применяется в
   следующем проходе/job с durable checkpoint.
4. **Tail `semantic_retry` inheritance.** `_inherit_cursor` теперь мержит
   tail: `max(attempts)`, `max(retry_at)`, `min(positive row_limit)`,
   reason сохраняется. 119-row окно после `attempts_exhausted` начинается
   с уменьшенного предела, а не с полного. Fresh B02-merge не изменён.
5. **Per-attempt truncation state.** `on_truncated` фиксирует
   `semantic_truncation[chat]`/row_limit до следующей попытки; второй
   повтор того же окна не удваивает backoff и не уменьшает окно ещё раз
   (attempts/row_limit — на логическое окно).

## RED на `066909923`

4 детерминированных теста падают:

- `test_periodic_heartbeat_during_slow_semantic_call`: `mid_call_beat is
  False` — heartbeat не идёт во время LLM-вызова.
- `test_fenced_heartbeat_stops_without_writes_and_keeps_counters`:
  `completed` вместо `interrupted` — False heartbeat игнорируется; нет
  per-attempt counters к началу 2-го вызова.
- `test_budget_checked_before_first_batch`: `llm.calls == 1` — бюджет
  проверялся только после батча.
- `test_inherit_cursor_merges_tail_retry_state`: `row_limit == 120` вместо
  `30` — tail retry не мержится.

Итог RED: **4 failed, 13 deselected in 26.35s**.

## GREEN

- `test_periodic_heartbeat_during_slow_semantic_call`: heartbeat во время
  вызова, ≥2 beats.
- `test_fenced_heartbeat_stops_without_writes_and_keeps_counters`:
  `interrupted`, cursor 0, `semantic_truncated>=1` durable к началу 2-го
  вызова, кандидатов 0.
- `test_budget_checked_before_first_batch`: `llm.calls == 0`,
  `semantic_budget_exhausted>=1`, cursor 0.
- `test_inherit_cursor_merges_tail_retry_state`: `row_limit=30`,
  `attempts=3`, `retry_at=5000`, reason.
- B01/B02 тесты (fresh/tail раздельно, 50→25→13, fresh 50→25→13→7,
  restart/merge) проходят.
- SXR-I2 `test_run_bounded_by_wall_clock_budget` адаптирован к pre-batch
  gate: fake clock даёт один батч, затем budget exhausted (assertions не
  ослаблены; отдельный B03-тест покрывает 0 вызовов при бюджете до старта).

Команды/результаты:

```
python -m pytest tests/test_exp_e_trunc_lag_amendment.py -q
17 passed in 12.94s

python -m pytest <18 related experience files> -q \
  -k "not deep_sleep_not_mixed_with_lessons"
296 passed, 1 deselected, 1 warning in 53.53s

py_compile: 0
git diff --check: 0
plan gate: stage=plan inventory=15 manual=2 scoped=0 errors=0
```

## Diff / scope

- `services/mca_experience_jobs.py`: heartbeat loop + fencing, per-attempt
  checkpoint, pre-batch budget gate, retry=1 + durable truncation callback,
  tail retry merge.
- `tests/test_exp_e_trunc_lag_amendment.py`: +4 B03-теста (17 всего).
- `tests/test_sxr_i2_fresh_stream_drain.py`: fake-clock sequence под
  pre-batch gate; assertions сохранены.
- Нет DDL/ACL/UI/embedding/новых job/очередей.

## Осталось / RFL

- Точный триггер `worker_lost` в 2.58.235 (registry/watchdog vs heartbeat)
  остаётся RFL: фикс закрывает heartbeat-механизм и durable counters, но
  сам watchdog-инцидент не воспроизводился.
- Реальный production-спад lag/throughput и поведение модели на 8192
  проверяются только после следующего деплоя (bounded 2–3 прохода).
- Archive re-anchor не выполнялся.
