# I2 — Experience fresh stream lag (binding evidence)

Стадия I2 (срез `S9-EVENT-PIPELINE`) эпика `SMART-EXECUTION-RELIABILITY-01`.
Реализация и тесты — Builder, независимое ревью/приёмка — Reviewer, далее
PM/Orchestrator. Деплой не выполнялся; production не менялся.

* База: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199, deployed), ancestor HEAD = да.
* Ветка: `smart/i2-stream`; worktree:
  `WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-c809ebc5`.
* Кодовый коммит (CODE_SHA): **`c5e63d9c37612ac3fe1e20f39f98b763ab43726a`**
  (`services/mca_experience_jobs.py` +563/−181, `services/experience_diagnostics.py`,
  `web/api/memory_overview.py`).
* Тестовый коммит: **`21781f8cd4d7bddb389875bec5892e93b869c574`** — кандидат для ревью
  (новый `tests/test_sxr_i2_fresh_stream_drain.py`, 547 строк; +12 строк в двух
  легаси-наборах).
* Требование карты: `SXR-I2-01` (source `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`
  строки 1052–1085; `live_required=true`, `live_when=postdeploy`).
* Границы записи соблюдены: изменения только в трёх перечисленных прод-файлах и трёх
  тестовых файлах. Схема БД, миграции, планировщик (`task_supervisor`), пороги
  warning, `config/settings.py` не менялись.

## 1. Установленная причина (owner §I2 «почему возникло отставание»)

Production recon 14.11.2026 (§7 `production-recon-2026-11-14.md`):

| Факт | Значение |
|---|---|
| `semantic_pending[CHAT_C1]` | 14 399 |
| `semantic_cursor:CHAT_C1` | 12 992 |
| `smart_messages.MAX(id)` CHAT_C1 | 2 405 456 |
| Строк после курсора | **2 059 418** |
| `SEMANTIC_PER_CHAT_MAX` | 50, окно `id > cursor ORDER BY id LIMIT 50` |
| Курсор | двигается ровно +50 за прогон, прогон ~каждые 15 мин |
| Поступление | ~7 200 строк/сутки; потолок дренажа ~4 800 строк/сутки |

Причина: прогон исполнял **ровно один** батч (≤50 строк) при одном отстающем
чате; пропускная способность была ниже поступления, backlog не сходился никогда.
Планировщик исправен (job `completed`), курсор двигался — дефект не в остановке
заданий, а в потолке прогресса за прогон.

Вторая часть дефекта — семантика сигнала: `lag_rows` (14 399) считался как
`semantic_pending` (обнаружено-не-обработано), а не как расстояние курсора до
данных (2 059 418). Сигнал не ложный, но занижал фактическое отставание на два
порядка и не различал «pending-счётчик» и «дистанцию».

## 2. Что изменено

| Точка (`services/mca_experience_jobs.py`) | Было | Стало |
|---|---|---|
| `SEMANTIC_BATCHES_PER_RUN` / `SEMANTIC_RUN_BUDGET_SECONDS` | — | hot-параметры `memory.experience_semantic_batches_per_run` (default **12**, 1..240) и `memory.experience_semantic_run_budget_seconds` (default **180с**, 5..3600); заводской потолок ≤12 батчей × ≤6 чатов × ≤50 строк = ≤3600 строк/прогон |
| `_semantic_pass` | один батч и `return` | цикл до батч-бюджета и wall-clock бюджета; остановка на пустом/отложенном бэклоге, `LLM is None`, `raw is None` или исчерпании бюджета (`semantic_budget_exhausted`) |
| `_semantic_pass` (checkpoint) | payload сохранялся только в `_finish` | durable `_checkpoint(job_id, payload)` **после каждого батча** + `TaskJobStore.heartbeat` (существующий watchdog `recover_stale`, 60с, не примет живую задачу за потерянную) |
| `semantic_backlog` | только `actionable_rows` из счётчика | `max(pending, measured lag)`; статус `interrupted` включён как носитель checkpoint (`COALESCE(finished_at, updated_at, created_at)`) |
| `_semantic_chat_order` | порядок по `semantic_pending` | в порядке участвуют и чаты, чей durable курсор отстаёт от `MAX(id)` (`behind`), даже если счётчик 0 |
| `_semantic_chats_behind` / `_chat_rows_after` / `_measure_semantic_lag` | — | измерение: `MAX(id)` по PK-обратному проходу + `COUNT(*) WHERE chat_id=? AND id > cursor` для ≤16 худших чатов; больше чатов → `partial=True`; ошибка чтения → `available=False` (честный fallback) |
| `semantic_progress_snapshot` | `backlog_rows` = pending | явно различает `pending_rows`/`pending_chats` (счётчик) и `lag_rows`/`lag_chats`/`lag_source`/`lag_measured_at`/`lag_partial` (измеренная дистанция); при недоступном замере `lag_source="pending"` |
| `_note_fresh_lag` | `lag_rows` = худший pending | `lag_rows` = худшая измеренная дистанция, `pending_rows` = счётчик, `lag_source` и `max_id` в `usage_json` события; порог warning **не менялся** (500) |
| `_semantic_extract` / `_semantic_pass` | — | `job_id` пробрасывается для checkpoint; измерение lag выполняется в `finally` после дренажа |
| `_run` (шаг архива) | архив блокировался только по `actionable_rows` | блокируется и по `lag_actionable_rows` — при рассогласованном счётчике архивный шаг не забирает бюджет при реальном свежем backlog |
| `services/experience_diagnostics.py` | `lag_rows = backlog_rows` | `lag_rows`, `pending_rows`, `lag_source` раздельно; legacy-снимок без замера честно падает на pending |
| `web/api/memory_overview.py` | `pending`/`backlog_rows` | + `lag_rows`, `lag_chats`, `pending_rows`, `lag_source` в `memory_intel_funnels` и последней job-сводке |

Запрещённые owner-способы **не использованы**: `fresh_lag_warn_rows()` = 500
(тест `test_defaults_are_drain_not_threshold`), курсор не перематывается
(нет ни одной записи курсора вперёд без обработки), массовый перепроцессинг
корпуса не запускается (только штатный дренаж постранично).

Скрытые бюджеты: модуль не обращается к `budget_gate`/`flags.budgets_enabled`
(grep: 0 ссылок) — дренаж ограничен только собственными явными параметрами.
Recon подтвердил effective `budgets_enabled=false` во всех трёх чатах, т.е.
дефект возникал и без бюджетов.

## 3. RED → GREEN

RED снят на базе `d20a7f73` теми же тестами (код откачен, тесты оставлены):

```
pytest tests/test_sxr_i2_fresh_stream_drain.py   ->  11 failed  (5.62s)
```

Все 11 падают на базе (нет батч-цикла, нет `semantic_batches_per_run`,
`lag_rows` = pending). После кандидата — **11 passed**.

## 4. Покрытие owner §I2 (строки 1063–1085)

| Пункт owner §I2 | Проверка | Где |
|---|---|---|
| фактический источник fresh stream | `smart_messages` + `semantic_cursor:<chat>`; recon §7 | §1, recon |
| идентичность и scope курсора | per-chat durable `semantic_cursor:<chat_id>` в payload job; тест durable-курсора | `test_cursor_progress_durable_across_restart` |
| почему возникло отставание | один батч/прогон < поступления | §1, RED |
| движется ли курсор | двигался и раньше (+50/прогон); теперь +несколько батчей/прогон | `test_drain_advances_beyond_one_window_per_run` (125 строк за прогон, throughput 125) |
| выполняются ли задания | job завершается `completed`, retry не нужен; длинный дренаж обновляет heartbeat | `test_drain_advances_beyond_one_window_per_run` (heartbeats ≥ 1+3) |
| есть ли необработанный backlog | 2 059 418 строк; дренаж уходит дальше одного окна, бюджеты реальные | `test_drain_advances_beyond_one_window_per_run`, `test_run_bounded_by_batch_budget`, `test_run_bounded_by_wall_clock_budget` |
| корректно ли рассчитывается lag | `lag_rows` = `COUNT(*)` после курсора; pending отдельно | `test_lag_rows_measures_cursor_distance_not_pending` (pending 3 vs lag 120; событие и снимок), `test_scheduler_keeps_draining_when_pending_counter_undercounts` |
| не блокируется ли невалидными событиями | непригодные строки (photo, `/start`) двигают курсор; битый LLM-ответ уходит в retry и не блокирует другие чаты | `test_invalid_row_does_not_stall_drain`, `test_broken_chat_does_not_block_other_chats` |
| скрытые ограничения бюджетов | модуль не читает `budgets_enabled`; дренаж ограничен явными параметрами | §2, grep |
| устранить причину, не порог/не перемотку | multi-batch drain + честный lag; порог 500 и курсор не тронуты | RED/GREEN, `test_defaults_are_drain_not_threshold` |
| нет потери/дублей/систематического пропуска | все строки уходят в LLM ровно один раз, курсор = последняя строка | `test_no_loss_or_duplicates_across_batches` (130 строк, dedup 0) |
| crash-safe / идемпотентность | checkpoint после каждого батча; `interrupted` наследуется; повтор с позиции после checkpoint | `test_crash_between_batches_resumes_without_duplicates` |
| per-chat изоляция | битый чат: курсор стоит + retry; рабочий обработан в том же прогоне; без зацикливания | `test_broken_chat_does_not_block_other_chats` |

Статус Builder: **REVIEW**. `VERIFIED` не заявляю — вердикт Reviewer, а пункт
`live_required/postdeploy` (реальный дренаж на production) остаётся за
контролируемым выкатом.

## 5. Прогоны (venv `C:\Code\Python\adminbot\.venv`, PYTHONPATH=.)

| Прогон | Результат |
|---|---|
| `pytest tests/test_sxr_i2_fresh_stream_drain.py` на базе `d20a7f73` (RED) | **11 failed** |
| `pytest tests/test_sxr_i2_fresh_stream_drain.py` на кандидате | **11 passed** |
| `+ tests/test_lesson_strategy_contract.py tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py tests/test_webapp_memory_overview_api.py` | **51 passed** |
| `test_asap8_f5_module_truth`, `test_asap8_v63_b02_semantic_experience`, `test_asap8_v6_d05_experience`, `test_evidence_grounds_persistence`, `test_evol020_experience_pipeline`, `test_evol020_ui`, `test_mca16_experience_block_{d,e,f}`, `test_mca16_experience_stale_recheck_hotfix`, `test_mod_acl_ux_m2_{resolver,capability_state,consumers}`, `test_soul1_w4_humor_feedback` | **219 passed, 1 failed (предсуществующий, см. §7)** |
| `git diff d20a7f73..HEAD --check` | чисто |

## 6. Effective configuration (acceptance-метаданные)

| Параметр | Default в коде | В тестах | Production (recon 14.11) |
|---|---|---|---|
| `memory.experience_semantic_batches_per_run` | 12 (1..240) | явно задаётся в тестах (1/2/6/8/10) | PG-записи нет → 12 |
| `memory.experience_semantic_run_budget_seconds` | 180 (5..3600) | явно задаётся (5/3600) | PG-записи нет → 180 |
| `memory.experience_drain_chats_per_pass` | 6 | 1/4 в тестах | PG-записи нет → 6 |
| `memory.experience_drain_per_chat_max` | 50 | 3/5/10 в тестах | `SEMANTIC_PER_CHAT_MAX=50` |
| `memory.experience_fresh_stream_lag_warn_threshold` | 500 | 100 только в тесте семантики (эмиссия), дефолт проверяется = 500 | 500 |
| `flags.budgets_enabled` | factory true | не участвует (модуль не читает) | **false** (global + overrides) |

Precedence: hot-параметр из `bot_settings` → default кода; per-chat override на
этот дренаж не заведён (глобальные значения, как и прежние лимиты). Тесты,
исполнявшиеся с «feature off» (порог не поднят, бюджеты выключены), — это и есть
проверяемое заводское поведение, а не форсированный флаг.

## 7. Предсуществующий провал (не связан с кандидатом)

`tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons`
падает и на базе `d20a7f73` (проверено откатом кода: `1 failed in 3.90s`).
Причина: тест утверждает `"graph_facts" not in _jobs_src()`, а строка
`graph_facts.origin` присутствует в docstring модуля уже в базе (строка 3176).
Кандидат эту строку не добавлял. → BACKLOG_ONLY, запись для PM; блокером I2 не является.

## 8. Что НЕ проверено (честно)

* Реальный production-дренаж после выката (`live_required=true`,
  `live_when=postdeploy`): фактическое продвижение курсора на 2M-строках,
  отсутствие роста `database is locked`/load и сходимость backlog — только
  контролируемый выкат + наблюдение из существующих метрик/job payload.
* Стоимость `COUNT(*)` на реальном 2.8 ГБ файле: запрос опирается на PK
  `id > cursor` с фильтром `chat_id`; на синтетике тестов измеряется, на
  production объёме — после выката (наблюдаемое время прохода и `lag_measured_at`).
* Витрина/API Mini App на реальных данных не снималась (не было деплоя);
  проверены только сериализаторы и API-тесты (`test_webapp_memory_overview_api`).
* Пути `discovery`/watermark больших чатов не менялись — они и раньше были
  работоспособны (recon §7: watermark 2 405 380, pending обнаружен).

## 9. Housekeeping

Worktree сохраняется до ревью (нужен Reviewer и интеграции). Промежуточные
откаты кода выполнялись скриптами с `finally`-восстановлением; после каждого
прогона дерево проверено чистым (`git status` пуст). Секреты не печатались,
production не затрагивался.
