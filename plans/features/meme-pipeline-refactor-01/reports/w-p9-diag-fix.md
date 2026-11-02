**P9 - MEME-INIT-DIAG: исправление F1/F2 после ревью**

Исполнитель: Builder (исправление по ревью `w-p9-review.md`).
Ветка `feat/meme-init-diag`, кандидат **ad4cf460d191b288bf70ae67022024e98b6ad815**, база
**6d09347b** (отклонённый ревьюером кандидат), общая база слайса `a43e366e` (merge P8).
Изменены ровно два файла: `services/initiative_diagnostics.py` (+79/-9),
`tests/test_meme_init_diagnostics.py` (+223/-6). Схема, события, `web/**`, `handlers/**`,
`meme_initiative.py`, `initiative_observer.py`, `publication_coordination.py` не тронуты;
новых таблиц/колонок/кодов/событий нет.

**F1. Настоящие гейты мема теперь в блоке, `ready` не противоречит `skip`.**
1. Тумблер инициативы чата. В `meme.availability(...)` передаётся комбинированный признак
   `_initiative_on(chat)` = `observer_enabled() and chat_observer_enabled(chat)` — ровно те два
   гейта, что проверяет боевой `consider_chat` (:1458-1461); в продакшене проход мема получает
   ту же функцию (`InitiativeObserverRunner._meme_phase` передаёт `chat_observer_enabled`).
   Отказ записи настроек — fail-closed («выключено»), а не «готово». Нового кода причины не
   вводится: используется существующий `initiative_disabled`.
2. Отсутствие таблицы брони. `publication_block` теперь считается ДО причины пропуска, и
   `publication.degraded` даёт `skip = schema_absent` с `origin="publication"` — фактическая
   причина остановки мема (`consider_chat` :1506-1507, `detail="publish_claim_absent"`).
   Деградация остаётся деградацией: `conflict=null`, `conflict_state="unknown"`.
3. `ready` вычисляется ПОСЛЕ `skip`: `ready = доступность_по_настройкам and skip is None`,
   `ready_reason` = код причины (`""` когда готов — как у текстового блока и как объявлено в
   контракте поля). Состояние «готов И причина пропуска» стало невыразимым.

Порядок причин (как в бою): `initiative_disabled`/`disabled_by_setting`/image/журнал
(availability) -> `daily_quota_reached` -> `cooldown_active` -> `quiet_hours` ->
`schema_absent` (нет таблицы брони) -> `publication_conflict`/`publication_in_flight` ->
записанная причина (`skip_recorded`).

Матрица гейтов мем-блока (наблюдаемое, не «по коду»):

| Состояние | `ready` | `skip` | `skip.origin` | прочие поля |
|---|---|---|---|---|
| всё включено, пауз нет | `true` | `null` | — | `ready_reason=""` |
| тумблер чата off | `false` | `initiative_disabled` | `availability` | `conditions.initiative_enabled=false`, `available=true` (данные есть) |
| мастер-флаг off | `false` | `initiative_disabled` | `availability` | то же |
| мем-модуль off | `false` | `disabled_by_setting` | `availability` | `conditions.meme_enabled=false` |
| нет таблицы брони | `false` | `schema_absent` | `publication` | `publication.degraded=true`, `conflict=null` |
| своя пауза | `false` | `cooldown_active` | `cooldown` | `cooldown.remaining_seconds` > 0 |
| квота суток | `false` | `daily_quota_reached` | `quota` | `quota.limit_reached=true` |
| тихие часы | `false` | `quiet_hours` | `quiet_hours` | — |
| чужая публикация | `false` | `publication_conflict` / `publication_in_flight` | `publication` | `publication.conflict=true` |
| ни когда не проверялся, но гейты открыты | `true` | `null` | — | `available=false`, `last_check_ts=null` (нет данных != «не готов») |

**F2. «Следующая проверка» не раньше «последней».**
Правило: оба поля считаются на одном базисе — времени проверки. `last_check_ts` — время
записанного решения (`last_decision.ts`, пишется на каждом проходе), `next_check_ts` —
`last_eval_ts + eval_interval`. Если расчётная дата оценки уже прошла к моменту последней
проверки (`next <= last`), дата не выдаётся: `next_check_ts=null`,
`next_check_basis="every_pass"` — «следующая попытка будет на ближайшем проходе». Значения
`eval_interval`/`every_pass`/`unknown`/`never_checked`/`chat_not_selected` — существующие, новых
нет. Инвариант (`next is None` или `next >= last`) закреплён тестом.

| Состояние | `last_check_ts` | `next_check_ts` | `next_check_basis` |
|---|---|---|---|
| оценка 2 ч назад, решение «сейчас» (min_gap/антифлуд/конфликт/кап/промах draw) | NOW | `null` | `every_pass` |
| оценка и решение в одном проходе | NOW-3600 | NOW-3600+интервал (=NOW-900) | `eval_interval` |
| проверок не было | `null` | `null` | `never_checked` |
| чат не выбран | `null` | `null` | `chat_not_selected` |

**Новые тесты (4, все CONTRACT, все могут упасть) и их мутационная проверка.**
Все четыре идут на реальных `DatabaseService`/SQLite, реальном `on_initiative_cycle`/
`_note_decision` и реальной брони; подменяются только внешние швы (`sender`/`image_provider`/
`random_source`/`summarizer`, `chat_observer_enabled`), предмет проверки не мокается. Каждый
тест сравнивает блок с БОЕВЫМ проходом в том же состоянии — «диагностика говорит то же, что
живой путь».

| Тест | Что утверждает |
|---|---|
| `test_chat_toggle_off_is_reported_as_initiative_disabled` | живой проход: `skipped/initiative_disabled`; блок: `ready=false`, `skip.code=initiative_disabled` (тот же код, `origin=availability`), `conditions.initiative_enabled=false`, `ready_reason`=код, `skip_recorded`=тот же код; текстовый блок тоже не готов |
| `test_missing_claim_table_is_reported_as_schema_absent` | живой проход: `skipped/schema_absent`, `detail=publish_claim_absent`; блок: `ready=false`, `skip.code=schema_absent` (тот же код, `origin=publication`), `publication.degraded=true`, `conflict=null`, `conflict_state=unknown`; ни один блок не «готов + причина пропуска» |
| `test_cooldown_state_never_claims_ready_and_skip_together` | свободное состояние: `ready=true`, `skip=null`, `ready_reason=""`; на паузе: `skip=cooldown_active` (`remaining=3540`) и `ready=false`, `ready_reason=cooldown_active`; явная проверка «не оба сразу» |
| `test_next_check_is_never_before_last_check` | устаревшая оценка: `last_check_ts=NOW`, `next_check_ts=null`, `basis=every_pass`; обычное состояние: `basis=eval_interval`, `next > last`; инвариант `next >= last` для любого непустого `next` |

Мутации (правка исходника + прогон целевого теста + восстановление файла из коммита,
`git status` после восстановления пуст):

| Мутация | Упавший тест |
|---|---|
| M1: `initiative_on=None` (гейт чата не спрашивается) | `test_chat_toggle_off_is_reported_as_initiative_disabled` |
| M2: ветка `publication.degraded` отключена | `test_missing_claim_table_is_reported_as_schema_absent` |
| M3: `ready = bool(доступность)` без учёта `skip` | `test_cooldown_state_never_claims_ready_and_skip_together` |
| M4: сверка базиса времени отключена | `test_next_check_is_never_before_last_check` |

**Прогоны (кандидат ad4cf460).**

| Набор | Результат |
|---|---|
| `tests/test_meme_init_diagnostics.py` | **18 passed** (6 с; было 14) |
| файл + `test_soul1_w5_initiative_vitality` + `test_initiative_coordination` + `test_initiative_delivery_telemetry` + `test_round1025_f8_registry` | **137 passed** (19 с) |
| `tests -k "meme or initiative or init_coord"` | **332 passed, 17595 deselected** (35-42 с), exit 0 |

Отдельно: прогон целевого файла и пятёрки файлов повторялся 10+ раз — 18/137 passed каждый раз.

**Побочное наблюдение (не связано с правкой, `unrelated/pre-existing`).** В широком наборе
`-k "meme or initiative or init_coord"` примерно каждый третий-четвёртый прогон падает 1-2
тестами семейства `run_check`/телеметрии доставки
(`test_t4_diagnostics_publish_mode_is_coordinated`,
`test_t4_diagnostics_dry_run_takes_no_claim`,
`test_check_dry_run_carries_live_ephemeral_opportunity_context`,
`test_check_dry_run_goal_fallback_uses_original_verdict_kind`,
`test_mismatch_chosen_reply_sent_chat_keeps_reason`). В изоляции эти тесты зелены (3/3 прогона,
7 passed). Причина — загрязнение процесс-глобальных кэшей настроек между файлами
(`chat_params`/`hot_config`), а не новый код: **на базе 6d09347b** тот же набор упал в 2 из 8
прогонов (`test_mismatch_chosen_reply_sent_chat_keeps_reason` — тест телеметрии, который не
импортирует диагностику). Мой файл в этих прогонах зелёный всегда.

**Что осталось как было (по ревью, объём не расширялся).** O1-O6 из `w-p9-review.md` не
исправлялись (в бэклог слайса): `quota.remaining=0` при `unlimited`, `degraded_reason` при
исключении `precheck`, свободные строки в `_scalar_dict`, `draw_block` без `value`,
`next_check` мема без продления до сброса квоты, разные смыслы `conditions` у двух блоков.

**Гейт.** Это исполнительская часть; связывание строк `MEME-IIC-DIAG-*`, пин слайса и
`candidate_commit` в карте — за PM, после независимого ревью нового кандидата.

Незакоммиченным в рабочем дереве остался только `plans/features/meme-pipeline-refactor-01/
reports/w-p9-review.md` (артефакт ревьюера, не мой и не изменялся).
