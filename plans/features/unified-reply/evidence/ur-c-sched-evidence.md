# UR-C-SCHED — evidence (per-chat scheduling, arch contract §4)

Кандидат: `ur/c-sched` @ **5d8c8598** (base: evol/impl a9c5b0b0, UR-C-CLOCK влит).
Дата: 06.11.2026. Статус: Builder-доказательства до независимого Review.

## Что изменилось (runtime)

- `services/slot_claims.py` (**новый**): ОДИН механизм claim слотов
  (kind=summary|goodmorning) + чистая математика локальных слотов
  (ZoneInfo на конкретный UTC-instant; spring gap → первый валидный
  instant того же дня; fold → раннее появление = один запуск на слот).
- `services/summary_scheduler.py`: глобальный cron `0,6,12,18` в
  `limits.summary_timezone` → ОДИН тикер APScheduler (interval 60 c,
  `max_instances=1`, `coalesce=True`) + per-chat слот каждого чата через
  `chat_clock.resolve_chat_timezone` (единственный резолвер пояса,
  UR-24.3) + атомарный claim перед запуском. Gates/DM-skip/targets/
  bounds/shutdown не изменены (B06.1/F-14/INC-01 сохранены).
- `services/goodmorning_scheduler.py`: `GOODMORNING_TIME` остался часом
  рассылки; CronTrigger по глобальному `GOODMORNING_TZ` убран — пояс
  КАЖДОГО чата из ChatClock; тот же claim-механизм (kind=goodmorning);
  `target_chat_ids`, per-chat gate permsoc («Расписания»), «нет target →
  start False», дедуп сохранены; медиа-релей не переписан.
- `services/database.py`: миграция **v42** `slot_claims` (DDL у владельца
  механизма; паттерн v41 `publication_coordination`; PG no-op;
  повтор — no-op).
- `bot.py`: wiring — goodmorning получает `db=db`; tz-аргумент снят.

## Наблюдаемость

`[sched_slot] kind=… chat_id=… tz=… tz_source=… local_date=… slot=…
slot_utc=… mode=… config=… action=fire|skip_expired` — решение тика
логируется с резолвнутым поясом/источником/слотом; текстов чата нет
(R17). Пример ассерта: `TestSchedSlotObservability`.

## Семантика due-окна / коalescing (§4.4, UR-28.3)

Слот запускается только в окне `[slot_utc, slot_utc+120 c)`
(SUMMARY_DUE_WINDOW_SECONDS = GOODMORNING_DUE_WINDOW_SECONDS = 120):
просроченный слот — честный skip (`fired=0`,
`reason_code='missed_slot_expired'`) РОВНО один раз; слоты старше
текущего не оцениваются → «пачка просроченных» невозможна; уже
опубликованный период не пересказывается (окно считает генератор —
неизменный coverage-контур, см. test_hotfix5/test_summary_run_store).
Смена пояса пересчитывает будущие слоты: due-путь делает CAS-перебронь
`WHERE fired=0 AND slot_utc_instant<>?` (fired=1 строки неизменяемы —
двойной публикации нет); проверено
`TestSameDateDedup::test_timezone_change_recomputes_future_slots_only`.

## Команды и результат (кандидат 5d8c8598)

```
pytest tests/test_ur_c_sched.py tests/test_summary_scheduler.py \
  tests/test_goodmorning.py tests/test_mca17_perimeter_events.py \
  tests/test_asap8_v63_b06_summary_scope.py \
  tests/test_hotfix5_summary_cover_window_round1025.py \
  tests/test_ur_c_clock.py tests/test_summary_inc01_pregen_bounds.py \
  tests/test_summary_inc01_shutdown.py tests/test_database.py -q
→ 276 passed
```
Дополнительно (ранее, тот же кандидат): tests/test_t5150_startup_
migrations_round1046.py + test_mca14_schema_additive_round1027.py +
test_asap8_f5_module_truth.py + test_asap7_direct_settings.py +
test_ur_g_acceptance.py → 195 passed (суммарно два прогона).

## Мутационные проверки (красные до фикса, зелёные после)

1. **Wall-clock UTC вместо пояса чата** (мутация
   `resolve_chat_zone` → всегда UTC): RED 8/15
   (TestPerChatTimezones×2, DST-spring, dedup-restart, expired-skip,
   goodmorning-tz, observability, next_due) → восстановлено
   `git checkout -- services/slot_claims.py` → 15 passed.
2. **Claim всегда выигран** (`try_claim` → return True): RED 3
   (dedup-across-restart, atomic-single-winner, expired-once) →
   восстановлено.

## Покрытие строк карты (candidate 5d8c8598)

Гейт: `requirements_gate.py check --stage review --slice UR-C-SCHED
--candidate 5d8c8598 --strict-evidence` → **errors=1** — единственный
оставшийся `UR-28.4: mandatory not VERIFIED (got PENDING)`: UI-часть
строки («Следующий запуск»/локальное время в UI) — волна UR-F по
slice-graph (W6; arch §4.7), не-UI часть (чатовая зона manual /summary,
без второй настройки tz) доказана UR-C-CLOCK (test_ur_c_clock) и
`next_due_utc` (TestNextDue). Строка честно оставлена PENDING; 7/8
строк среза VERIFIED со strict candidate-bound evidence (артефакты и
sha проверены гейтом). Top-level `candidate_commit` карты поднят на
кандидат среза (5d8c8598).

| Row | Статус | Доказательство |
|---|---|---|
| UR-28.1 | VERIFIED | один механизм: тикер + zoneinfo-слоты каждого чата, без прохода по поясу первого чата (два чата стреляют в разные UTC-instant в одном процессе); существующий scheduler/task-run ledger не менялся (INC-01 наборы на тикере); next_due через zoneinfo (TestNextDue) |
|---|---|---|
| UR-RES-09 | VERIFIED | TestPerChatTimezones (два пояса на одном свипе), TestDstBerlinSpring (DST-день: 5 слотов ровно по разу), TestSameDateDedup (тик+рестарт без дубля), TestMissedSlotExpired (skip ровно один раз) |
| UR-28 | VERIFIED | один тикер вместо глобального cron; per-chat слоты ChatClock; частота/gates не менялись (TestSchedulerConfig + TestPerChatTimezones); второй планировщик отсутствует |
| UR-28.2 | VERIFIED | claim PK (kind,chat,date,slot) атомарен (TestSameDateDedup::test_claim_is_atomic_single_winner); DST gap→первый валидный instant дня, fold→ранний (test_slot_math_gap_and_fold_deterministic); повтор часа = один запуск (DST-spring); смена пояса → только будущие слоты (test_timezone_change_recomputes_future_slots_only) |
| UR-28.3 | VERIFIED | TestMissedSlotExpired (не пачка; честный reason_code; ровно один лог); goodmorning-ночь без догонятора (TestGoodmorningPerChat::test_goodmorning_expired_morning_no_night_catchup); covered-period не пересказывается — неизменный coverage-контур генератора (существующие test_hotfix5_summary_cover_window_round1025, test_summary_run_store_asap41) |
| UR-28.4 | PENDING | не-UI часть (manual /summary в чатовой зоне, «второй настройки tz для саммари нет») покрыта UR-C-CLOCK (test_ur_c_clock); UI «Следующий запуск»/локальное время — волна UR-F; helper `next_due_utc` готов (TestNextDue). Строка не закрывалась |
| UR-28.5 | VERIFIED | GOODMORNING_TIME = час рассылки (test_goodmorning_time_semantics_preserved; TestGoodmorningPerChat::test_goodmorning_time_hour_semantics_per_chat_tz — 07:30 в поясах чатов); gate до claim и не съедает слот (test_goodmorning_gate_preserved_and_slot_not_consumed); дедуп claim'ом; GOODMORNING_TZ из расписания убран (редактор скрыт в каталоге ещё UR-C-CLOCK, param_catalog:3625); targets/start-False/relay не тронуты (test_goodmorning.py) |
| UR-BAN-06 | VERIFIED | нет второго рабочего tz-поля и старого параллельного cron: test_summary_scheduler.py::test_no_parallel_global_cron (нет CronTrigger), конструктор goodmorning без tz; TimeContext не «только Direct» — Factcheck/Initiative/Summary инъекции доказаны test_ur_c_clock (строки UR-26.2/UR-27 карты) |

## Отклонения от write_scope среза (зафиксировано для Orchestrator)

- `services/slot_claims.py` (новый модуль) и `services/database.py`
  (миграция v42) не входят в перечисленный write_scope slice-graph, но
  требуются arch contract §4.2 (аддитивная таблица `slot_claims`).
  Прецедент — v41 (DDL в модуле-владельце + шаг миграции). Параллельные
  W4/W5-срезы (UR-D, UR-E) database.py не пишут — конфликтов нет.
- `bot.py` — двухстрочный wiring (аргумент db, снятие tz-аргумента);
  без него claim-механизм goodmorning не получает БД.
- Имя тест-файла: бриф родителя — `tests/test_ur_c_sched.py`;
  slice-graph write_scope называет `tests/test_ur_per_chat_schedule.py`.
  Использовано имя брифа; slice-graph требует сверки Orchestrator'ом.

## Live-статус

`live_required: false`, `live_when: preprod` — live/preprod-проверка
принадлежит волне приёмки UR-G (B2 preprod, D6); данным срезом не
заявляется.
