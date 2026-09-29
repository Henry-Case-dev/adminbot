# `mca-13-event-contract` — MCA-13: журналирование и диагностика (round 10.27)

> **Статус:** 🟦 PLANNING — Step 1 @PM. Код НЕ менялся. Secret-дисциплина (R17/R18).
> **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 0** (базовый контракт событий для всей наблюдаемости). **Фича-ID:** `mca-13-event-contract`.
> **Тип:** backend/observability — структурированные события, словарь причин, ошибки/маскировка/ретенция, метрики витрины. **P0-enabler** (все фичи пишут события этого контракта; MCA-17 собирает наблюдаемость поверх).
> **ТЗ-источник (IMMUTABLE):** `plans/current_task.md` v1.8, **§17** «MCA-13 — журналирование и диагностика»: **§17.1** общий контракт события (`:818–828`), **§17.2** словарь причин (`:830–836`), **§17.3** ошибки и объём (`:838–846`), **§17.4** метрики и витрина (`:848–854`); §2.16 (`:36`); §27.1/§27.3/§27.7 — сквозные обязательства; проверки §19 **A27**, **A53**.
> **Приёмочные ориентиры §19:** **A27** (сбой провайдера/БД/парсинга/job — ошибка и terminal outcome видны по trace), **A53** (недоступность телеметрии и исчерпание буфера — видимый degraded/gap, ограниченный рост памяти, нет ложного полного trace).
> **Зависимости:** нет обязательных предшественников. **Потребляется:** `mca-17a` (реестр/span/lifecycle/инциденты), `mca-01` (логи транзакций/задач), `mca-04b`, `mca-06`, `mca-10a/b`, `mca-11`, `mca-15`, `mca-16`, `mca-19`, `mca-20`. **Unblocks:** `mca-17a`. **Мягкие предшественники:** DDL v15 — через механизм `mca-14` (v13); durable-запись `mca_events` (T-3772) — через общий write-механизм `mca-01` (T-3736). Порядок применения Δ DDL волны 0: v13 → v14 → v15.
> **Baseline (Step 0 @Memory, 26.09.2026):** HEAD `7165ff7`; `APP_VERSION` **2.58.31**; SQLite DDL **v12**; каталог **473/430/448/102/100/21**; канон **12**; pytest **9513/0** + JS **47/47** (прошлый verified). **Deploy — `DEFERRED_TO_RELEASE`.**
> **Risk — `R2`** (санкция @Architect ADR-1027-2; триггеры повышения до R3 — spec §Risk): расширение существующего logging/analytics; риск — рост объёма/утечки через логи. При R3-повышении — `threat-failure-analysis.md`.
> **Числа (финал, санкция @Architect — ADR-1027-2 D4/D11):** **Δ DDL = v15** (`mca_events` + `mca_event_aggregates` + 4 индекса; через механизм `mca-14`); **Δ каталога = 0** (F8 NOT_APPLICABLE; ретенция — env-only `ClassVar`); `APP_VERSION` без bump.

## Трассируемость (REQ → verbatim §ТЗ → блок → задачи → приёмка)

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC (спека) | ADR-1027-2 (D) | Приёмка |
|---|---|---|---|---|---|---|
| MCA13-R1 | §17.1 «Структурированный JSON event: timestamp UTC, level, event_name, trace_id, operation_id, parent_operation_id, chat_id, trigger/message refs, component, stage, status, reason_code, краткая понятная причина, duration_ms, attempt, config_version, model/provider при наличии, relevant entity IDs, usage/cost и error metadata.» «На каждое принятое в обработку событие есть start и terminal outcome… После crash supervisor помечает незавершённые операции interrupted… Ни одно исключение не исчезает в `except: pass`.» (`:822–824`) | B, C | T-3767, T-3768 | SC-01…SC-04 | D1, D2 | A27, A49 |
| MCA13-R1a | §17.1 «Для решения хранить: рассмотренные действия, оценки с обозначением «оценка модели», выбранное действие, основные источники, роль случайности, результат stale-check и факт доставки. Не требовать и не сохранять скрытую цепочку рассуждений модели.» «Для retrieval… Для контекста… Для архива… Для сна…» (`:826–828`) | B | T-3767 | SC-05 | D3 | A27 |
| MCA13-R2 | §17.2 «Вместо непонятного skip видно конкретно…» + минимальный список reason_code (`:832–834`) «Расширять словарь можно. Не сводить разные исходы к одному `skip`. У каждого WARN/ERROR указать влияние… и выполненный fallback.» (`:836`) | D | T-3769 | SC-06, SC-07 | D5 | A27 |
| MCA13-R3a | §17.3 «ERROR содержит тип исключения, очищенный stack trace, cause chain, стадию, retryability и результат восстановления. Ожидаемый пустой поиск — INFO, повреждение данных — ERROR. Повторяющиеся ошибки можно агрегировать, но сохранять количество, первое/последнее время и первый полный trace; агрегация не должна скрывать факт продолжения сбоя.» (`:842`) | E | T-3770 | SC-08, SC-09 | D6 | A27, A53 |
| MCA13-R3b | §17.3 «Маскировать API keys, Authorization, cookies, proxy credentials, session data, Telegram initData, секретные URL-параметры. Полный сырой контекст не дублировать… Управление доступом распространяется на просмотр и экспорт журналов.» (`:844`) | F | T-3771 | SC-10 | D7 | A53 |
| MCA13-R3c | §17.3 «Логи ротируются… Начальная ретенция подробных диагностических логов — 14 суток, итоговых событий решений/архивных заданий — 90 суток, настраивается; события ручного изменения и происхождение памяти не удаляются этой ротацией… Неограниченный in-memory буфер запрещён.» (`:846`) | F | T-3772 | SC-11, SC-12 | D4 | A53 |
| MCA13-R4 | §17.4 «Показывать active/pending tasks, queue depth/age, DB lock wait/retries, RAM/RSS, cache entries, downloads/bytes, provider latency/errors, долю деградаций, покрытие provenance, истории/эпизоды, archive progress, инициативы/молчание по причинам, результаты отправки, random source/fallback и стоимость по категориям. UNKNOWN отображать как неизвестно, не как ноль/здоровое состояние. Логи остаются в существующем viewer; добавить фильтры по trace/chat/component/reason…» (`:852–854`) | G | T-3773 | SC-13, SC-14 | D8, D9 | A48, A53 |
| MCA13-R5 | §17 преамбула (`:810`) + §17.4: одна система наблюдаемости; ExecutionGraph §82–§92 — REUSE, вторая аналитика/endpoint запрещены | G | T-3773, T-3775 | SC-15 | D8 | A48 |
| MCA13-R6 | §2.16; §20: deploy `DEFERRED_TO_RELEASE`; R17 end-to-end | H | T-3774, T-3775 | SC-16 | D10, D11 | A27, A53 |
| MCA13-ACC | §19 A27/A53 | H | T-3774 | SC-16 | D10, D11 | A27, A53 |

**Соответствие ID:** табличные `MCA13-R1/R1a` ↔ спека `REQ-MCA13-01…03`; `R2` ↔ `-04`; `R3a` ↔ `-05`; `R3b` ↔ `-06`; `R3c` ↔ `-07`; `R4` ↔ `-08`; `R5` ↔ `-09`; `R6`/`ACC` ↔ `-10`.

## Карта решений ADR-1027-2 → задачи (сверка @PM, T-3766)

| Решение ADR-1027-2 | Суть | SC | Задачи |
|---|---|---|---|
| D1 (схема/outcome) | поля §17.1 + терминальные `outcome`; `trace_id=run_id` | SC-01, SC-02 | T-3767, T-3768 |
| D2 (транспорт) | fail-open обёртка; лог-строка + `mca_events` + `RunSnapshotStore` | SC-03, SC-04 | T-3768, T-3775 |
| D3 (поля по типам) | решение/retrieval/контекст/архив/сон; без скрытой CoT | SC-05 | T-3767 |
| D4 (store/retention) | `mca_events`(90d) + структурный лог(14d); row-cap; bounded ring | SC-11, SC-12 | T-3772 |
| D5 (reason_code) | базовые 28 кодов + реестр; `skip` не заменяет | SC-06, SC-07 | T-3769 |
| D6 (ошибки/агрегация) | `error_json` + `fingerprint`-агрегат счётчик/первое-последнее/первый trace | SC-08, SC-09 | T-3770 |
| D7 (маскирование) | единый фильтр до записи во все каналы; RBAC-доступ | SC-10 | T-3771 |
| D8 (ExecutionGraph) | REUSE §82–§92 аддитивно; вторая аналитика запрещена | SC-15 | T-3773, T-3775 |
| D9 (метрики) | §17.4 через один адаптер; `UNKNOWN`≠0; фильтры trace/chat/component/reason | SC-13, SC-14 | T-3773 |
| D10 (kill-switch) | env-only `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` | SC-16 | T-3775 |
| D11 (Δ DDL/границы) | v15; Δ каталога=0; hot env-OFF / cold `git revert` | SC-16 | T-3774, T-3776 |

## Приёмочные инварианты MCA-13 (нарушение = НЕ принято)

1. Каждое принятое событие имеет start и terminal outcome (success/silent/skipped/failed/cancelled/pending external); незавершённые после crash → interrupted. **MCA13-R1; T-3768.**
2. Нет `except: pass`; исключение не исчезает. **MCA13-R1; T-3768.**
3. Решение/retrieval/контекст/архив/сон логируются по своим полям; скрытая chain-of-thought не запрашивается/не сохраняется. **MCA13-R1a; T-3767.**
4. reason_code — стабильный расширяемый словарь; разные исходы не сводятся к `skip`; WARN/ERROR с влиянием/fallback. **MCA13-R2; T-3769.**
5. ERROR содержит тип/cause chain/стадию/retryability/результат восстановления; пустой поиск=INFO. **MCA13-R3a; T-3770.**
6. Агрегация повторяющихся ошибок не скрывает продолжение сбоя (счётчик/первое-последнее/первый trace). **MCA13-R3a; T-3770.**
7. Секреты/credentials/initData/URL-параметры маскируются во всех каналах и экспорте. **MCA13-R3b; T-3771.**
8. Ретенция: 14 суток подробные / 90 суток итоговые (настраиваемо); ручные изменения и происхождение не удаляются этой ротацией; нет неограниченного in-memory буфера. **MCA13-R3c; T-3772.**
9. UNKNOWN ≠ 0/здоровье; фильтры по trace/chat/component/reason; логи в существующем viewer. **MCA13-R4; T-3773.**
10. Deploy `DEFERRED_TO_RELEASE`; R17: маскирование до записи во все каналы. **T-3775.**

## Блок 0 — Step 0 / baseline (T-3763) + Step 1 (T-3764)

- [ ] **T-3763 [@Memory/@Orchestrator — подтверждение Step 0]** — **Цель:** зафиксировать baseline (HEAD `7165ff7`, 2.58.31, SQLite v12, каталог, канон 12, pytest/JS). **Выход:** подтверждение в KG/`workflow_state`. **Критерий:** baseline-анкер согласован. **Зависимости:** Step 0 ✅.
- [ ] **T-3764 [@PM — Step 1: `tasks.md`]** — **Цель:** разложить §17, создать этот файл. **Выход:** `plans/features/mca-13-event-contract/tasks.md`. **Критерий:** REQ/инварианты/блоки согласованы; орфанов нет. **Зависимости:** T-3763.

## Блок A — Step 2 spec + ADR / сверка (T-3765…T-3766)

- [ ] **T-3765 [@Architect]** — **Цель:** `spec.md` (REQ-MCA13-01…; границы с `mca-17a`) + **новый ADR**. Решения: (i) финальный JSON-контракт события и поля по типам (решение/retrieval/контекст/архив/сон); (ii) start/terminal outcome + interrupted; (iii) объём словаря reason_code; (iv) агрегация/семплинг; (v) маскирование/R17 (единый фильтр); (vi) ретенция/ротация/хранилище (SQLite vs файл, reuse); (vii) метрики витрины и фильтры; (viii) совместимость с ExecutionGraph §82–§92; (ix) Δ DDL/Δ каталога-санкция; (x) финальный Risk. **Выход:** `spec.md` + ADR (Proposed). **Критерий:** каждый REQ имеет SC; §17 не сужен. **Зависимости:** T-3764.
- [x] **T-3766 [@PM — сверка]** — **Цель:** сверка `tasks.md` ↔ `spec.md` ↔ ADR; SC/ADR-колонки; вердикт. **Выход:** `PLANNING_CONSISTENT` либо список расхождений. **Критерий:** scope/risk/приёмка согласованы. **Зависимости:** T-3765. — **Вердикт Step 2b @PM (26.09.2026): PLANNING_CONSISTENT** (SC/ADR-колонки заполнены и совпадают; scope/исключения/risk R2 с триггерами повышения/приёмки A27+A53/deploy `DEFERRED_TO_RELEASE`/rollback согласованы; неблокирующие ниты — ссылка в таблице на «Блок C», который по тексту отсутствует, и опечатка `retención` в SC-16); детали — `plans/features/mca-wave0-reconciliation.md`.

## Блок B — контракт события и start/terminal outcome (T-3767…T-3768)

- [x] **T-3767 [@Builder — схема события]** — **Цель:** реализовать структурированный JSON event (поля §17.1) + поля по типам (решение/retrieval/контекст/архив/сон; §17.1a). **Выход:** правки + тесты. **Критерий:** MCA13-R1/-R1a → SC; инвариант 3; A27/A49. **Зависимости:** T-3766. — **✅ Выполнено 26.09.2026:** `services/mca_events.py::build_event` (контракт §17.1, R17-safe через общий `_safe_value`; JSON-поля `entity_ids`/`usage_json`/`error_json`/`source_ref_json`); v15 `mca_events`/`mca_event_aggregates`. Тесты: `test_build_event_contract_fields`, `test_per_type_fields_present`.
- [x] **T-3768 [@Builder — terminal outcome / interrupted / no except:pass]** — **Цель:** start+terminal outcome на каждое событие; supervisor помечает незавершённые interrupted; устранить `except: pass`. **Выход:** правки + тесты. **Критерий:** MCA13-R1 → SC; инварианты 1, 2; A27. **Зависимости:** T-3767. — **✅ Выполнено 26.09.2026:** `emit_mca_event` (start + терминальные исходы); `TaskSupervisor.recover_stale` → `interrupted`; fail-open без `except: pass`. Тесты: `test_emit_start_and_terminal`, `test_a51_takeover_no_duplicate`.

## Блок C — отсутствует (объединён с B)

> Стадии start/outcome реализуются в T-3768; отдельный блок C не вводится.

## Блок D — словарь reason_code (T-3769)

- [x] **T-3769 [@Builder — reason_code-словарь]** — **Цель:** стабильный расширяемый словарь (минимум §17.2); не сводить к `skip`; WARN/ERROR с влиянием/fallback. **Выход:** правки + тесты. **Критерий:** MCA13-R2 → SC; инвариант 4; A27. **Зависимости:** T-3767. — **✅ Выполнено 26.09.2026:** `REASON_CODES` (27 базовых §17.2 + расширения волны 0); неизвестный код отбрасывается, не подменяется `skip`. Тесты: `test_reason_dictionary_has_minimum`, `test_unknown_reason_code_dropped_not_skip`.

## Блок E — ошибки/агрегация (T-3770)

- [x] **T-3770 [@Builder — error metadata + агрегация]** — **Цель:** тип/cause chain/стадия/retryability/результат восстановления; пустой поиск=INFO; агрегация с сохранением счётчика/первого-последнего/первого полного trace. **Выход:** правки + тесты. **Критерий:** MCA13-R3a → SC; инварианты 5, 6; A27/A53. **Зависимости:** T-3768. — **✅ Выполнено 26.09.2026:** `build_error_metadata` (тип/очищенный stack/cause/стадия/retryability/восстановление) + `_upsert_aggregate` (fingerprint/count/first-last/first_trace). Тесты: `test_error_aggregate_keeps_count_and_first_trace`, `test_error_metadata_has_cause_and_masked_stack`.

## Блок F — маскирование и ретенция (T-3771…T-3772)

- [x] **T-3771 [@Builder — маскирование/R17]** — **Цель:** маскировать API keys/Authorization/cookies/proxy/session/initData/секретные URL-параметры во всех каналах и экспорте; не дублировать полный контекст; доступ к журналам по ролям. **Выход:** правки + тесты. **Критерий:** MCA13-R3b → SC; инвариант 7; A53. **Зависимости:** T-3770. — **✅ Выполнено 26.09.2026:** маскирование через `log_ring.sanitize` до записи (лог/стор); сырой контекст не дублируется (`source_ref_json`/SourceRef). Тест: `test_masking_of_secrets`.
- [x] **T-3772 [@Builder — ротация/ретенция/буфер]** — **Цель:** ротация логов; ретенция 14/90 суток (настраиваемо); ручные изменения/происхождение вне этой ротации; запрет неограниченного in-memory буфера. **Выход:** правки + тесты. **Критерий:** MCA13-R3c → SC; инвариант 8; A53. **Зависимости:** T-3771. — **✅ Выполнено 26.09.2026:** `prune_events` (90d; protected `component` = `memory_manual`/`memory_provenance` не удаляются), bounded `_pending` deque (256) + `dropped_total`. Env `MCA_DETAILED_LOG_RETENTION_DAYS`=14 / `MCA_TERMINAL_EVENT_RETENTION_DAYS`=90. Тесты: `test_retention_prune`, `test_buffer_bounded_with_visible_gap`.

## Блок G — метрики и витрина (T-3773)

- [~] **T-3773 [@Builder — метрики/filters/UNKNOWN]** — **Цель:** метрики витрины (§17.4); UNKNOWN ≠ 0/здоровье; фильтры по trace/chat/component/reason; логи в существующем viewer; переходы из карточек. **Выход:** правки + тесты. **Критерий:** MCA13-R4 → SC; инвариант 9; A48/A53. **Зависимости:** T-3770. — **◐ Частично (rework 26.09.2026, B-MCA13-2):** реализован единый адаптер `mca_events.metrics()` — все группы §17.4 (`tasks` active/pending/queue/age/archive, `lock` exhausted/retry, `providers` latency/errors, `degradations`, `initiatives`/silence, `delivery`, `random` fallback, `cost` по категориям, `provenance`/`memory`/`cache`/`downloads`/`runtime` — из runtime-контура); источники без продюсера → `None` + `available=False` (UNKNOWN≠0); `query_events` — фильтры trace/chat/component/reason + bounded LIMIT. Тесты: `test_metrics_covers_17_4_groups_with_unknown`, `test_metrics_computes_real_groups_from_store`, `test_metrics_unknown_not_zero_when_unavailable`, `test_query_events_reason_filter_and_limit`. **Перенос санкционирован @Architect (26.09.2026, spec §1.1; ADR-1027-2 AMEND-1/2):** UI-часть SC-13 («метрики на витрине») и SC-14 (переходы из карточек, логи в существующем viewer) + живые продюсеры (flush/prune scheduler-wiring, RSS/cache/provenance) — в `mca-17a` (наблюдаемость поверх того же store; D8 запрещает новые endpoint/панели). Carry-over register — `spec.md` §1.1; обязателен к включению в spec/tasks `mca-17a`. Evidence — `evidence.md` §6.

## Блок H — тесты/интеграция/ревью (T-3774…T-3776)

- [x] **T-3774 [@Builder/@Tester — тесты A27/A53]** — **Цель:** сбой провайдера/БД/парсинга/job → видимый terminal outcome (A27); недоступность телеметрии/исчерпание буфера → degraded/gap, ограниченный рост памяти (A53). **Выход:** тесты + evidence. **Критерий:** A27/A53. **Зависимости:** T-3767…T-3773. — **✅ Выполнено 26.09.2026:** `tests/test_mca13_event_contract_round1027.py` (18 тестов: contract/reason/errors/masking/retention/bounded/metrics).
- [~] **T-3775 [@Builder — интеграция MCA-17/R17]** — **Цель:** хуки для `mca-17a` (process/span/heartbeat поля), R17-проверка маскирования end-to-end. **Выход:** правки + тесты. **Критерий:** инвариант 10. **Зависимости:** T-3774. — **◐ Частично 26.09.2026:** контракт несёт `trace_id`/`operation_id`/`parent_operation_id` (hooks для `mca-17a`); durable-store читается тем же API. Полная интеграция MCA-17a — следующая фича (вне scope волны 0).
- [ ] **T-3776 [@Reviewer/@Architect — ревью/merge]** — **Цель:** ревью (обе линзы), Merge в `plans/ARCHITECTURE.md` (**§93+**), ADR Accepted. **Выход:** `review.md`, Merge. **Критерий:** release-blocking findings закрыты; deploy `DEFERRED_TO_RELEASE`. **Зависимости:** T-3774, T-3775.

## Критерий готовности фичи

Контракт события + terminal outcome + reason_code-словарь + ошибки/агрегация + маскирование/ретенция + backend-метрики/фильтры реализованы; UI-часть SC-13/SC-14 и фоновый контур телеметрии — carry-over `mca-17a` (spec §1.1); тесты A27/A53 проходят; интеграционные хуки для MCA-17 готовы; @Reviewer Approved; Merge (§93+) — @Architect. **Deploy — `DEFERRED_TO_RELEASE`.**
