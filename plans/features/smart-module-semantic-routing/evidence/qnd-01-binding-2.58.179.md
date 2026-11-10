# QND-NONDET — привязка строк к выкату 2.58.179 (10.11.2026)

**Срез:** `QND-NONDET` (умная маршрутизация / смарт-модуль, квантовая недетерминированность).
**Карта:** `plans/features/smart-module-semantic-routing/requirements-map-qnd.json` (строки `QND-01`…`QND-26`).
**Контракт (заморожен, 139 строк):** `plans/features/smart-module-semantic-routing/quantum-nondeterminism-contract.md`
(sha256 `dbf36b2f43037f93adf66dffb9b1c48ffbf62139f27240acc9d95614496c7720`).
**Исходник владельца:** `plans/owner_inputs/2026-11-10-quantum-nondeterminism-correction.md`
(sha256 `11118D955CB8FA5AC172C0D09D51BB9BBE6811A3A309FE7AC474B965679441AA`; `OI-2026-11-10-QUANTUM-NONDETERMINISM`).
**Роль файла:** единственный repo-артефакт привязки для гейта; сами отчёты выклада и ревью лежат на релизной
линии и цитируются по SHA (см. §1), а не копируются сюда, чтобы не держать две расходящиеся копии.

---

## 1. Идентичность выклада

| Поле | Значение |
|---|---|
| Версия | **2.58.179** |
| Артефакт выклада | `32e018b939cd8ec453b23e07863fae3be4b683f6`, ветка `release/2.58.179` |
| Верхушка origin | `04b0713a` — добавляет **только** релизную запись (`plans/features/vmq-onto-01/evidence/vmq-q1/release-2.58.179.md`), продуктовых файлов не касается |
| Одобренный кандидат | `629743f9` (Review: Approved; носитель — ветка базы `6674811f`) |
| Предыдущий прод | `af84b6c6` (2.58.178, точка отката, схема 46) |
| Схема | 46 → **47** (аддитивная таблица `semantic_schedule`) |
| Запись выклада (релизная линия) | `release/2.58.179:plans/features/vmq-onto-01/evidence/vmq-q1/release-2.58.179.md` @ `04b0713a` |
| Запись ревью/прогонов (релизная линия) | `release/2.58.179:plans/features/vmq-onto-01/evidence/vmq-q1/qnd-nondet-2026-11-10.md` @ `dd47d81e` |

### 1.1 Cherry-pick на прод-линию и CRLF

Срез переносился на прод-линию (`af84b6c6`), а не выкатывался с ветки базы кандидата (`6674811f`):
`bc62da05→b29a4a5b`, `46cb550b→b8f5a689`, `0cebea92→3bce90e5`, `629743f9→0355ac5a`,
`c99d64c7→dd47d81e` (только evidence-документ, продуктовых файлов не добавляет).

Конфликты были ровно в 21 файле и **только из-за CRLF/LF**: прод-линия держит CRLF в
`plans/docs/param-registry-round1025.meta.md` и 20 тестах, ветка кандидата — LF. Разрешены
трёхсторонним слиянием по содержимому с сохранением CRLF прод-линии.

**Проверено независимо при этой привязке** (не по отчёту, а `git diff` в этом репозитории):

```
git diff 629743f9 32e018b9 -- services/semantic_schedule.py services/quantum_publication.py \
  services/qnd_diagnostics.py services/nostalgia_worker.py services/initiative_observer.py \
  services/memory_maintenance.py services/mca_events.py services/mca_random_source.py \
  services/param_catalog.py services/prompt_registry.py services/status_service.py \
  services/database.py handlers/summary.py web/api/initiative_vitality.py web/app.js web/index.html
→ пусто
```

То есть **все продуктовые модули среза в выкаченном артефакте байт-идентичны одобренному кандидату**;
различия между линиями — только переводы строк в планах/тестах плюс версионные литералы релизной обвязки
(`config/settings.py`, 25 тестов, мета-документ каталога), которых не было в кандидате.

### 1.2 Сравнение полного набора тестов с базой

По отчёту DevOps на релизном дереве `32e018b9`: 68 файлов, падающих на базе `af84b6c6`, дают **ровно тот же
набор падений** и на релизе — **107 = 107**, разница в обе стороны пустая. Остальные падения полного прогона
признаны предсуществующими дефектами тестов/окружения прод-базы 2.58.178 (summary golden, webapp UI/JS,
youtube-загрузка, budget-меню, `flags.dig_pre_gate_enabled` в аудите «мёртвых ручек»), срез их не вносил.
Цифра принимается как **заявление DevOps, привязанное к `32e018b9`**, а не как мой повторный прогон:
полный набор на релизном дереве в этой сессии не перезапускался.

---

## 2. Миграция на проде — факты

| Показатель | До | После |
|---|---|---|
| `PRAGMA user_version` | 46 | **47** |
| `schema_migrations` (строк) | 35 | **36** (+`47 semantic_schedule_v47`) |
| `semantic_schedule` | нет | **19 колонок**, PK `(chat_id, mechanism)`, индекс `(mechanism, next_due_ts)` |
| Строк в таблице | — | **2**, обе `nostalgia`; backfill не выполнялся, строки созданы первым draw |
| `PRAGMA quick_check` | ok | **ok** |
| `smart_messages` | 2 077 014 | 2 077 014 |
| `nodes` | 33 755 | 33 755 |
| `edges` | 65 946 | 65 946 |
| `graph_facts` | 24 202 | 24 202 |

Дрейф по четырём таблицам: **none**. Снапшот до выклада: `/root/deploy-258179/predeploy-258179.db`
(sha256 `747da798df6f95190e65c256dd326336359e8d154542ffd41ed8e127ce0a70dc`).

---

## 3. Живые наблюдения (связаны ниже со строками)

1. **Расписание пер-чатово и реально.** `nostalgia`: чат `-1004482340693` → `next_due_ts 1794283692`
   (интервал 13 781 с), чат `-1002661910336` → `next_due_ts 1794289072` (19 161 с). Интервалы различаются.
2. **Первые розыгрыши — действительно квантовые.** `source="quantum"`, `provider="ANU Quantum Numbers"`,
   `u=0.45703125` и `u=0.830596924`, `fallback_reason=null`, draw_id `1944ed27…` и `e0178092…`.
   Fallback не понадобился.
3. **Правило честности работает.** `nostalgia`: `draws_quantum=1` → `status_word_allowed=true`,
   headline «квантовый источник используется»; `initiative`: `draws_quantum=0` →
   `status_word_allowed=false`, headline «нет данных: розыгрышей в окне не было». Слово «работает»
   не появляется ни в одном из случаев.
4. **Событийный путь — только для своего чата + три гейта по порядку.** На копии прод-данных
   `request_event` создал строку `initiative` **только** для целевого чата (`scan_requested_at=1794271197`),
   второй чат не тронут; `due_chats(initiative)=[-1004482340693]`, `due(target)=true`. Границы:
   `event_dropped_debounce` → `event_deferred_floor` → allowed.
5. **Шов ностальгии цел, разыгранный интервал не сбрасывается живыми сообщениями**
   (`nostalgia_interval_preserved=true`, `request_event` метит только механизм инициативы).
6. **Канон чекапа v10**, `INFO_CANON_VERSION = 10` на работающей сборке.
7. **DIG pre-gate без читателей**: `grep -rn DIG_PRE_GATE_ENABLED services handlers` → 1 совпадение и это
   метаданные каталога (`services/param_catalog.py:1798`).
8. **Health:** 2.58.179 публично и на loopback, `NRestarts=0`, traceback/CRITICAL за окно выклада нет.

---

## 4. Что доказано по строкам (VERIFIED)

| Строка | Чем доказано |
|---|---|
| `QND-01` durable-состояние по чату | §2: v47, `semantic_schedule` 19 колонок, PK `(chat_id, mechanism)`, 2 строки без backfill, `quick_check ok`, счётчики неизменны |
| `QND-02` момент проверки = один квантовый draw на чат | §3.2–3.3 + два разных `next_due_ts` из §3.1 |
| `QND-03` адаптивное ограниченное распределение без хардкода | 32 записи `limits.qnd_*`; `test_long_run_200_cycles…` (каждый delay внутри `[lo_adj,hi_adj]`, нет двух равных подряд), `test_inactive_chat_intervals_longer_within_bounds`; 25/25 стабильных итераций набора B1/B4 |
| `QND-04` рестарт: строка авторитетна | §2 (строки созданы первым draw после рестарта, backfill нет) + `test_restart_keeps_next_due_and_executes_once` + §3.5 |
| `QND-05` пропущенный дедлайн — максимум одно исполнение | `test_missed_deadline_executes_once_then_redraws` (одно исполнение, `missed_count=1`), затем обязательный `draw_next` |
| `QND-06` просроченный дедлайн — только перерозыгрыш | `test_stale_deadline_redraws_without_mass_send` (ноль отправок, `executed=false`, `reason_code=stale_deadline`) |
| `QND-07` единственное исполнение при конкуренции | `test_concurrent_claim_yields_single_execution` (второй claim → `lease_held`, одна отправка); аренда — условный `UPDATE` c TTL `limits.qnd_lease_seconds` |
| `QND-08` heartbeat — только исполнитель | `limits.qnd_heartbeat_seconds`-поллер, PRNG-jitter (`random.randint`/`jitter_safe`) удалён; регрессия B2: 4 живых сообщения за 90 с → 0 вызовов модели, `next_due_ts` не изменён; §3.5 |
| `QND-09` событийное пробуждение без второго Observer | `handlers/summary.py::summary_observer` → `request_event` после `save_live_message` → `TaskSupervisor` → `observe_tick(trigger="event", only_chat=…)`; §3.4 (строка только своему чату); `test_live_message_signal_starts_evaluation_with_trigger_event` |
| `QND-10` границы события (single-flight/дебаунс/пол) | §3.4 (порядок `event_dropped_debounce` → `event_deferred_floor` → allowed) + `test_event_dropped_when_chat_busy_and_per_chat_debounce`, `test_event_path_respects_eval_budget_and_floor` |
| `QND-11` провенанс `trigger=event\|schedule` | durable-событие несёт `trigger`; `test_live_message_signal_starts_evaluation_with_trigger_event` утверждает `trigger="event"` |
| `QND-12` вероятность публикации вместо двойного гейта | `services/quantum_publication.py::decide` — один draw, `publish iff not deferred and u < p`; `random_trigger` на гейте оценки удалён; пост-розыгрышного SILENT-пересмотра нет; `p` записан в каждой строке решения (`p=0.266404` в обеих строках решающего теста) |
| `QND-13` жёсткие лимиты до розыгрыша, свежесть после | `test_hard_limits_and_dedup_precede_the_draw` (нет draw при лимите), `test_sendrecheck_never_redraws_or_redecides`, `test_llm_veto_without_veto_reason_is_semantic_parse_error`; порядок зафиксирован в `decide()` |
| `QND-14` единственный RandomSource, без подмешивания PRNG | 4 добавленных purpose, `initiative_trigger` выведен, `test_no_pseudorandom_in_semantic_paths` (`random`/`numpy.random`/`secrets` патчатся в исключение), `test_provider_failure_is_honest_not_quantum`; §3.2 — фактический `source=quantum`, провайдер и draw_id в журнале |
| `QND-15` `_direction_pick` — взвешенный выбор по ВСЕМ кандидатам | inverse-CDF по одному `u` с весами `0.65*relevance + 0.2*coverage + 0.1*usage`, запись `info["direction"]{source,draw_id}`; равновесная полоса `_DIRECTION_BAND=0.999` удалена |
| `QND-16` админ-редактируемые `limits.qnd_*` | 31 `limits.qnd_*` + compat `initiative.trigger_probability`; каталог 638/121/119/22; группы `limits_qnd`/`limits_qnd_nostalgia`, вкладки `mod_initiative`/`mod_nostalgia`; пины каталога переизданы под фактический артефакт |
| `QND-17` durable-метрики и правило честности | 5 типов событий (`quantum_schedule_draw/due/evaluation/publication_decision/result`), `services/qnd_diagnostics.py`, блок `quantum` в `/api/status`; §3.3 — живые headline и `status_word_allowed` на обоих механизмах, слово «работает» не печатается |
| `QND-18` изоляция промптов и сохранение рамок | пользовательские промпты не переписаны; ревизия только внутреннего промпта Observer `initiative-observer-qnd-veto` (sha12 `4bb33535bad5`), factory-отпечаток переутверждён осознанно (`FACTORY_SET_SHA256_12=1532c9480cd5`); новых агентов/пайплайнов/OFF-SHADOW нет; канон v10; human gate не создавался |
| `QND-19` решающая приёмка «та же ситуация — разные `u`» | `test_same_semantic_situation_different_quantum_values_differ`: одинаковые факторы и гейты, `u=0.02` → `delivered`, `u=0.98` → `silent`/`random_miss`, одинаковый `p`. Ревью подтвердило отдельно |
| `QND-25` существующие связки QRNG со снами и памятью сохранены | дельта `af84b6c6→32e018b9` не содержит ни одного модуля снов/памяти-консьюмера (`services/dream_worker.py`, `services/mca_dream_random.py`, `services/mca_dream_history.py` не изменялись); правка `services/mca_random_source.py` — только константы purpose и санкционированный набор |
| `QND-26` политика провайдеров не тронута | по диффу `services/mca_random_source.py` изменены только объявления purpose и `SANCTIONED_DRAW_PURPOSES`; `selected_mode`/`resolve_effective`/`fallback_enabled`/реестр ANU-LfDR-Lizaonair/таймауты/квоты и `AnuClient` не правились, других провайдерских файлов в дельте нет |

## 5. Что НЕ доказано и остаётся PENDING (точные условия)

| Строка | Условие снятия |
|---|---|
| `QND-20` строки `initiative` в проде под живыми сообщениями | первое живое сообщение в чате после рестарта → строка `initiative` и первый draw. На копии прод-данных получено `u=0.768508911`, delay 5 672 с, `source=quantum`; в проде с 00:21 UTC сообщений не было |
| `QND-21` суточный ритм, независимость чатов во времени, отсутствие «одновременных» проверок | ≥1 суток живых строк: сравнить распределение `next_due_ts`/`last_draw_ts` по чатам, убедиться, что проверки не совпадают и не копятся |
| `QND-22` живой событийный путь в проде | реальное сообщение → durable `quantum_evaluation` с `trigger="event"` на проде (сейчас доказано только на копии данных и тестами) |
| `QND-23` визуальная проверка новых блоков «Статус»/«Аналитика» | браузерная проверка (Playwright + Browser Use) на реальных данных: числа из событий, подписи честности, отсутствие «работает» при `draws_quantum=0`. В браузере ни разу не проверялось |
| `QND-24` продуктовое ощущение частоты/доли публикаций | ≥1 суток реальных решений: соотношение delivered/отложено/молчание при текущих `limits.qnd_*`; при необходимости — правка настроек, не кода |

---

## 6. Известные ограничения (в бэклоге, не блокируют строки)

1. `sched.release()` не вызывается на тиковом пути инициативы: аренда снимается только
   `mark_executed`/`mark_missed`, поэтому холостой тик держит аренду до `limits.qnd_lease_seconds`
   (300 с при heartbeat 300 с — в проде безопасно, ограничит частоту при уменьшении периода).
2. Предсуществующее падение `test_cfg03_param_audit::test_visible_dead_knobs_are_exactly_documented`
   по `flags.dig_pre_gate_enabled` — не внесено этим срезом (падает и на базе 2.58.178).

## 7. Что осталось до полного VERIFIED среза

Пять строк `QND-20`…`QND-24` (живой трафик, сутки ритма, живое событие, браузерная витрина, ощущение
частоты). Инженерная часть среза (21 строка, включая `QND-25`/`QND-26`) закрыта выкатом `32e018b9` и
одобренным кандидатом `629743f9`.
