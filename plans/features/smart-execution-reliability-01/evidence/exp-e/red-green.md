# RED → GREEN: E-TRUNC / E-LAG (22.11.2026)

Harness: `exp_e_repro_final.py` (read-only, локальная SQLite-БД, fake LLM).
Одинаковый harness запускался с `PYTHONPATH`, указывающим на base
`56e2450d2` и на ветку `fix/exp-e-trunc-lag` (`819361a71`). Production не
затрагивался.

## A. reasoning-only / `finish_reason=length`, непустое окно (120 строк)

| Наблюдение | BASE `56e2450d2` | HEAD `819361a71` |
|---|---|---|
| LLM-вызовов | 1 | 3 (initial + 2 bounded retry) |
| `max_output_tokens` | **1500** | **4608 → 8192 → 8192** |
| cursor | 0 | 0 (обрезанный ответ не двигает) |
| throughput_rows | 0 | 0 (валидного контента не было) |
| `semantic_llm_unavailable` | 1 | 0 (это не «провайдер недоступен») |
| `semantic_truncated` | отсутствует | 3 |
| durable `semantic_truncation` | отсутствует | `{count:1, reason:truncated_reasoning, rows:50}` |
| `lag_rows` | 120 | 120 (не подменён нулём) |

RED-смысл: единственный вызов уходил в reasoning, исключение терялось как
«unavailable», курсор не двигался. GREEN-смысл: бюджет растёт, отказ
классифицирован и durable; окно уменьшено/отложено, а не зациклено.

Восстановление при достаточном бюджете — отдельный тест:
`test_reasoning_truncation_recovers_with_contract_budget` — 40 строк,
fake-модель обрезает `<5000`; вызовы `4608 → 8192`, cursor = last id,
`semantic_truncated=1`, `semantic_truncated_recovered=1`, retry пуст.

## B. Строк в одном LLM-вызове (6 чатов × 50)

| BASE | HEAD |
|---|---|
| `[300]` | `[120]` |

120 — `semantic_batch_rows_max` (hot, ≤600, не больше `chats × per_chat`).
Тест `test_one_call_is_row_bounded_across_chats`: 300 строк, 3 вызова,
`max(rows_per_call) ≤ 120`, ни одна строка не потеряна/не повторена,
`throughput_rows=300`.

## C. Head-of-line: новые события при 6k старом хвосте

Production-подобная форма: `_init_chat_stream` ставит cursor=1000
(6 000 − `FRESH_TAIL_ROWS=5000`), затем приходят 3 новых сообщения.

| Наблюдение | BASE | HEAD |
|---|---|---|
| 1-й проход: cursor | 1050 | 1000 |
| 1-й проход: строк в вызове | 50 | 1 (самый новый id через fresh-полосу) |
| 2-й проход: `new_processed` | **False** | **True** |
| 2-й проход: min id | 1051 (старый хвост) | 6001 (новое) |
| cursor после 2-го | 1100 | 1000 (не двигался фиктивно) |
| `semantic_fresh` | нет | `{boundary:6000, cursor:6003}` |
| `lag_rows` | 4903 | 4999 (старый хвост честно измерен) |

RED: новые события недостижимы, пока не пройдёт весь старый хвост.
GREEN: fresh-полоса обрабатывает новые события первым батчем; основной
курсор остаётся на старом хвосте, lag не обнуляется.

## D. Тесты RED→GREEN (файл `tests/test_exp_e_trunc_lag_amendment.py`)

| # | Тест | Что доказывает |
|---|---|---|
| 1 | `test_reasoning_truncation_recovers_with_contract_budget` | 1500 нет; бюджет растёт; только валидный `[]`; cursor двигается |
| 2 | `test_model_capability_caps_budget_and_uses_output_field` | `max_output=2048` — потолок; `max_completion_tokens` выбран каталогом |
| 3 | `test_unrecoverable_truncation_keeps_cursor_and_backs_off` | ≤3 вызова; cursor 0; durable причина/`row_limit`; restart; до `retry_at` нет повторов; меньшее окно восстанавливается; `next_retry_at` виден планировщику |
| 4 | `test_one_call_is_row_bounded_across_chats` | ≤120 строк/вызов; 300 строк без потерь/дублей |
| 5 | `test_new_events_processed_while_old_tail_lags` | fresh-батч новых; старый cursor стоит; lag — COUNT |
| 6 | `test_discovery_catchup_scans_beyond_normal_limit` | watermark не отстаёт на месяцы; catch-up 5k |
| 7 | `test_output_budget_formula_is_contract_and_capability_based` | формула: не 1500, растёт, чтит `max_output`/контекст |
| 8 | `test_measured_lag_converges_with_bounded_catch_up` | 8 000 строк + inflow 20: lag строго падает до 0, все строки обработаны один раз |
| 9 | `test_fresh_lane_merges_without_loss_or_duplicates` | после дренажа полосы сливаются; нет дублей/потерь; lag 0 |

## E. Review B01/N01 (candidate `ece1e1ca9` → `a5049c842`)

| Наблюдение | RED `ece1e1ca9` | GREEN `a5049c842` |
|---|---|---|
| Непрерывный fresh-приток + обрезанный tail | tail `[50,50,50]`, `attempts=1`, `row_limit=25` стирался | tail `[25] → [13] → [7]`, `attempts` 2→3, cursor 1000→1007 |
| Fresh при tail `retry_at` в будущем (restart) | fresh не обработан (`fresh-полоса ошибочно ждёт tail backoff`) | fresh обработан; tail-батчей нет; tail retry не изменён |
| После истечения tail backoff | снова 50 | 25 → 13 (уменьшенное окно) |

Подробно и с точными assertion — `review-fixes-b01-n01.md`.
Тесты: `test_fresh_success_does_not_reset_tail_truncation_state`,
`test_fresh_lane_ignores_tail_backoff_across_restart`.

## F. Review B02 (candidate `1df6fff16` → `161a17059`)

| Наблюдение | RED `1df6fff16` | GREEN `161a17059` |
|---|---|---|
| Наследование fresh lane | `KeyError: 'row_limit'`; attempts/retry/reason теряются | `row_limit=5, attempts=4, retry_at=12345, reason` сохранены; tail не смешан |
| 3 job'а с устойчивой обрезкой fresh | `[50,50,50]` | `50 → 25 → 13 → 7`; attempts `1→2→3`; cursor стоит на отказах, двигается валидным контентом |
| После успеха | — | продолжение с cursor=6007 без повторной отправки 6001–6007; restart durable |

Подробно — `review-fixes-b02.md`.

## G. Pre-existing failure (не candidate)

`tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons`
падает **идентично на base** `56e2450d2`: assertion `"graph_facts" not in
_jobs_src()` противоречит docstring `graph_facts.origin`, существующему в
base (строка 3589). Проверено отдельным запуском на detached worktree
base; к E-TRUNC/E-LAG отношения не имеет, не исправлялось.
