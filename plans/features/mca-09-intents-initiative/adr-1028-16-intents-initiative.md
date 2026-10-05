# ADR-1028-16 — mca-09-intents-initiative: память незавершённых намерений (Intent), единый инициативный Decision (defer = silent + серверное планирование), проверка перед отправкой и один контур инициативы

**Статус:** **Proposed** (Step 2 @Architect, design-freeze, 05.10.2026; T-5018/T-5019) → Accepted по merge `plans/ARCHITECTURE.md` §120+ (последний занятый — §119 mca-16, `ARCHITECTURE.md:4466`; §118 mca-10a `:4449`) + прод-валидация.
**Дата:** 05.10.2026 (Step 2 @Architect, T-5018/T-5019)
**Номер проверен:** `ADR-1028-16` нигде не занят (grep по `plans/**` 05.10.2026: только плановые упоминания в `plans/features/mca-09-intents-initiative/`; последний фактический — ADR-1028-15 mca-16; `ADR-1028-16` как файл отсутствует). Merge-цель — следующий фактически свободный **§120+**.
**Фича:** `mca-09-intents-initiative` (Wave 3 эпика `memory-context-autonomy`; цепочка `10a ∥ 16 → 09 → 10b`; критпуть `:250`); ТЗ `plans/current_task.md:464–512` §13.1–§13.4; приёмки A15–A17 `:896–898`; §20.2 `:1015`; §20.3 `:1038`; §21 `:1055`; §27.1 `:1354`; §16.3 `:800–804`. Артефакты — `plans/features/mca-09-intents-initiative/` (spec, threat-failure-analysis, tasks, requirements-map). База (проверено 05.10.2026, HEAD `7b9cd85`): прод **2.58.59** (mca-16 VERIFIED; v28; F8 504; K1–K4 ON), SQLite v28 (`database.py:1072`; v29 свободна), каталог 504/108/106/21 (F8 `--check` OK), канон 12, `REASON_CODES` 231, `KILL_SWITCHES` 68. mca-16 не трогал `CoordinatorDecision` (`direct_chat_service.py:906–940`), `nostalgia_worker.py`, `direct_llm_react.py`, `tool_result.py`, `mca_random_source.py` (проверено `git show --stat f97e641` + чтение дерева).

---

## Контекст

Владелец требует инженерную «свободу воли»: бот помнит незавершённые намерения, сам замечает поводы для участия, выбирает `reply/react/silent/tool`, молчание — нормальный исход, повторного вопроса после закрытия нет, stale-check ловит «уже разобрались без нас» (§13.1–§13.4). Это не симуляция сознания и не второй контур инициативы: один координатор (GEN-R3 `:22`), REUSE существующего контура/транспорта, R17. Зависимости закрыты: mca-07 (§99), mca-08 (2.58.55), mca-11 (2.58.57), mca-10a (2.58.58); mca-16 (2.58.59) — смежный handoff (outcome-сигналы). AMEND `CoordinatorDecision`/decision-making A7 (ADR-1026-20) обязателен — контракт решения расширяется аддитивно.

---

## Решения

### D1. Один контур инициативы: `mca_intents.py` + существующий координатор + heartbeat на существующем планировщике

Дом Intent-контура — `services/mca_intents.py` (`IntentStore`/`IntentService`/`InitiativeCandidate`/`SendRecheck`, фасад `get_service()`); записи — `write_transaction` (mca-01), refs — mca-04a, события — `emit_mca_event` (mca-13), retrieval — `retrieve()` (mca-07), случайность — `RandomSourceService`/`ExplorationPolicy` (mca-10a). Контракт решения — существующий `CoordinatorDecision` (`direct_chat_service.py:906–940`; `DecisionCandidate` — там же); аддитивный вход координатора для решений **без входящего сообщения** (heartbeat/nostalgia/search/significant event), тот же слой A7, **единственный транспорт** `services/telegram_send.py`. Heartbeat — джоб `intent_heartbeat_tick` на существующем APScheduler `MemoryMaintenanceService` (прецедент mca-16 `memory_maintenance.py:66,101–117`), код-константа 300 с, без LLM на тике, без per-intent `task_jobs` (due-скан по durable-намерениям; пропущенные тики догоняются). Вторые: сервис/стор/контур отправки/движок решений/очередь/словарь/bundle/RandomSource запрещены. **OFF (K1) = бит-в-бит 2.58.59.** (spec §1)

### D2. Intent — контракт, жизненный цикл, гигиена, дисциплина обязательств (§13.2)

Поля §13.2 (id/chat_id/kind/subject IDs/topic-event refs/цель/причина/origin/source refs/created_at/not_before/expires_at/activation_condition/status/attempts/last_evaluated_context_version/priority/linked_action_id) + гигиена (`dedup_key` UNIQUE, `merged_into_id`, `archived_at`, `next_check_at`). Kinds — закрытый набор `follow_up|answer_extension|topic_interest|open_dispute`; conditions — `time_due|new_reply|topic_resume|event_change|search_completed`; origin — `unanswered_question|explicit_request|unfinished_topic|search_result`. Состояния: `pending → deferred → fulfilled/abandoned/expired`; `deferred → pending` по событию/условию; **завершённое не активируется повторно без нового события и новой записи**. A15: результат сообщён → закрыть без вопроса; игнор → deferred по событию (без таймерного повтора); `attempts` ограничены (max 3) — не домогаться ответа. Не каждая фраза → обязательство; дедуп/слияние/пересмотр/архивация; 5–10 — не жёсткий предел. **OFF (K1) — записей/чтений нет.** (spec §2)

### D3. Decision — аддитивные поля, enum не ломается, defer = silent + серверное планирование (§13.3)

`action` ∈ {`reply`,`react`,`silent`,`tool`} остаётся; `defer` — **не значение enum** (отложенное = `silent` + `next_check_at`/статус `deferred`); wire-`action` не вводится. Аддитивные поля: `trigger_kind`, `intent_id`, `reply_target`, `candidate_actions` (`DecisionCandidate`: candidate_id/action/communicative_intent(14.10-структура)/source/reason_code/source_refs/prepared_text_ref/random_meta/admissible, ≤8), `selected_candidate`, `reason_codes`, `source_refs`, `context_version`, `recheck_conditions`, `next_check_at`, `random_metadata` (mca-10a), `tool_outcome` (ToolResult). `__post_init__`-инварианты A7 сохраняются и дополняются нормализациями (незнакомое — отбрасывается, не бросает). Silent — без Вербализатора и **без отправки** (инициативный/отложенный путь, tool→silent); legacy silent-ack direct-autonomous (🗿, ASAP-3.2 §50) не трогается. Tool→silent разрешён (инструмент не обязывает публиковать), A7 §43 (explicit/вопрос — не silent) сохраняется. Уместность — аддитивные сигналы детерминированного слоя; третий LLM-вызов не вводится. Запрещены таймер «раз в 10 минут» и рост «желания» от тишины; direct приоритет; дедуп только того же события. **OFF (K1/K3) — поля инертны; A7 байт-идентичен 2.58.59.** (spec §3)

### D4. Проверка перед отправкой — `SendRecheck`, одна повторная оценка, без цепочек (§13.4)

Единый `SendRecheck` на границе отправки для решений с `recheck_conditions` и всех инициативных/отложенных отправок: включённость → адресат/родитель → состояние намерения → новые ответы в релевантной ветке → разрешения инструмента; посторонняя ветка не отменяет готовый ответ. Смысловая смена условий — **ровно одна** повторная оценка с новым `context_version`; повторная смена → defer (`recheck_deferred`). Логи: `stale_context`/`already_answered`/`intent_closed` + точные причины. Нет цепочки собственных сообщений без нового человеческого события/реального результата; chunks = одна логическая отправка (recheck один раз, до первого chunk). Обычный direct-ответ не меняется (пустые `recheck_conditions`). **OFF (K1/K4) — слой неактивен (документированное подмножество при K4 OFF).** (spec §4)

### D5. Триггеры и лёгкий heartbeat (§13.1)

Закрытый `trigger_kind`: `new_message|direct_address|significant_event|intent_due|search_completed|nostalgia_due`; каждый триггер → кандидат решения, не автоотправка; тишина не порождает отправку. Heartbeat: due-скан SQL, дешёвые гейты, bounded-батч (≤20), coalesce ≤1 кандидат/чат/тик, без LLM, без чтения большого окна; retrieval — только `retrieve()` (mca-07, бюджет §11.3); «500 сообщений на реплику» запрещено. **OFF (K1/K2) — тик инертен.** (spec §5)

### D6. `NostalgiaWorker` — делегирование в единый Decision (не второй контур)

Существующий проактивный контур («кстати…»; `nostalgia_worker.py:1–40`) переклассифицируется в **источник кандидатов**: при K1+K3 ON его готовый кандидат (текст уже сформирован, 1 LLM-вызов внутри, без изменений) подаётся в координатор (`source=nostalgia`, `prepared_text_ref`, `trigger_kind=nostalgia_due`), проходит уместность + recheck, отправляется единственным транспортом; может завершиться silent (честный статус, без ложного `sent`). Собственные гейты nostalgia сохраняются и не обходятся. **OFF (K1/K3) — legacy direct-send бит-в-бит 2.58.59.** (spec §6)

### D7. Границы интеграций (REUSE, без вторых механизмов)

mca-10a: `random_metadata` из существующих `ExplorationPolicy.choose`/журнала draw; одна probability-проверка на автономную ситуацию; новые purpose не вводятся (conversation_variant — mca-10b); истинность/права/идентичность не рандомизируются; fallback-политика reuse. mca-11: ToolResult-статусы; tool→silent; notable-only учёт (F-1), check→reconcile (F-3), пин retries (F-4); без слепого повтора (`delivery_unknown`); K5 OFF не трогается; порядок деградации `maintenance→autonomous→direct` reuse. mca-07: единственный EvidenceBundle; заполняются `chosen_intent`/`recent_actions`/`ambiguities`/`unknown`/`contradictions` (M-MCA07-2); второй bundle запрещён. mca-08: второй классификатор речи/clarify запрещён. mca-15: stats-intent не дублируется. mca-16: Decision отдаёт outcome-сигналы/refs; ExperienceEpisode/Lesson создаёт только mca-16; lessons ≠ intent. mca-22: собственные ответы — не независимое подтверждение; намерение закрывается только человеческим событием/реальным результатом. mca-13/17a: единый emitter/словарь/реестр. **OFF (K1).** (spec §7)

### D8. Хранение — additive v29 через mca-14

**v29** (`MigrationStep(29)`): 1 таблица `mca_intents` (колонки D2) + 4 индекса (UNIQUE `dedup_key`; `(chat_id,status,next_check_at)`; `(status,next_check_at)`; `(chat_id,kind,status)`). Идемпотентно (повтор no-op), PG — no-op, backup-guard fail-closed pre-DDL + read-back; старый код v29 не читает (cold-совместимо); backfill нет. Retention env-only (терминальные 180 дней; активные не прунятся). Обоснование против Δ0: queryable durable-состояние (status/chat/due/дедуп/слияние/retention) нужно для A15/heartbeat/наблюдаемости; task_jobs/JSON-блоб и файловый store отклонены (не второй write-механизм; прецедент mca-10a). **OFF (K1) — таблица инертна.** (spec §8)

### D9. Наблюдаемость и UI-контракт (один реестр, один словарь)

Новый процесс `intent.initiative` v1 (`mca_process_registry.py`; stages trigger/candidate/decide/recheck/deliver/close; `widget_id="Намерения и инициатива"` — контракт mca-17c; OFF → `disabled/not_run`). События notable-only через единственный `emit_mca_event` (`mca_events.py:529–557`): `intent_created`, `intent_merged`, `intent_fulfilled`, `intent_abandoned`, `intent_archived`, `initiative_decided` (≤1/ситуацию), `recheck_deferred`; группа метрик — существующая `initiatives` (`:1014–1026`). UI-контракт §16.3 для mca-12: активные намерения + последнее действие/пропуск + причина + источник случайности/fallback; расширение существующего status-снимка (прецедент `status_service.random_source_snapshot:410–474`); новых маршрутов нет; R17-safe; без выдуманных «мыслей». Плейсхолдер `context.compress` (`mca_process_registry.py:845–851`) — не наш процесс (инцидентал-наблюдение; пере-метка на reconcile). **OFF (K1) — событий нет.** (spec §9)

### D10. Kill-switches и env-only лимиты

K1 `MCA_INTENTS_ENABLED` (master), K2 `MCA_INTENT_HEARTBEAT_ENABLED`, K3 `MCA_INTENT_DECISION_ENABLED`, K4 `MCA_SEND_RECHECK_ENABLED` — env-only `ClassVar`, default ON, per-call, не бросают; OFF = паритет 2.58.59 (K1) / документированные подмножества. Переиспользуются `DIRECT_*`, `MCA_EVENT_*`, `MCA_OBSERVABILITY_ENABLED`, `MCA_RETRIEVAL_*`, `MCA_RANDOM_*`, `MCA_TOOL_*`/`MCA_MONEY_LIMITS_ENABLED` (K5 OFF не трогается), `MCA_EXPERIENCE_*`. Env-only лимиты: `MCA_INTENT_HEARTBEAT_BATCH_MAX`=20, `MCA_INTENT_MAX_ATTEMPTS`=3, `MCA_INTENT_CANDIDATES_MAX`=8, `MCA_INTENT_RETENTION_DAYS`=180, `MCA_INTENT_DEFER_BACKOFF_SECONDS`=1800; тик — код-константа 300 с. **Δ каталога = 0.** (spec §10)

### D11. Санкции T-5019 (сводно)

Δ DDL = v29 (1 таблица + 4 idx; backup-guard; PG no-op; v29 свободна). Δ каталога = **0** (F8 NOT_APPLICABLE; счётчики 504/108/106/21 не меняются; routes не меняются → `ROUTES_SHA256_F11` без изменений). Канон 12 без изменений. reason_code — **ровно +6** (`intent_created`, `intent_merged`, `intent_fulfilled`, `intent_abandoned`, `intent_archived`, `recheck_deferred`) в единственный `REASON_CODES`; существующие `stale_context`/`already_answered`/`intent_closed`/`intent_not_due`/`intent_expired`/`wrong_moment`/`no_new_contribution` переиспользуются. Risk **R3** + `threat-failure-analysis.md` (THR-1…THR-15). Deploy **CA-11** bump 2.58.59→**2.58.60**; rollback soft (K1–K4=false) / cold (git revert; v29 инертна). Merge **§120+**; ADR-1028-16 → Accepted по merge. Live — `PENDING OWNER` (T-5045, без имитации). (spec §11)

---

## Реестр amend/supersede

| # | Отношение | Предмет | Что именно |
|---|---|---|---|
| **AM-1** | **AMEND ADR-1026-20 (A7 `decision-making`)** | `CoordinatorDecision` + decision-слой | Аддитивные поля D3 (trigger_kind/intent_id/reply_target/candidate_actions/selected_candidate/reason_codes/source_refs/context_version/recheck_conditions/next_check_at/random_metadata/tool_outcome); enum {reply,react,silent,tool} не расширяется; `defer` = silent + серверное планирование; silent-семантика без Вербализатора/отправки (новый путь), legacy silent-ack не трогается; tool→silent; инвариант «без 3-го LLM-вызова» и правила §42–§45/§46/§47 сохраняются (не переопределяются) |
| **AM-2** | REUSE/CONFIRM ADR-1026-14 (A1) | `CoordinatorDecision` | Второй контракт/координатор не вводится; A1-поля сохранены |
| **AM-3** | REUSE ADR-1027-2 (mca-13) | события/словарь | Единый `emit_mca_event` + `REASON_CODES` (+6); группа `initiatives`; второго канала нет |
| **AM-4** | REUSE ADR-1027-3 (mca-01) | запись/очереди | `write_transaction`/`serialized()`; per-intent `task_jobs` не создаются; durable-состояние — v29 |
| **AM-5** | REUSE ADR-1027-7 (mca-07) | bundle/retrieval | Единственный EvidenceBundle; заполняются `chosen_intent`/`recent_actions`/M-MCA07-2; только `retrieve()` |
| **AM-6** | REUSE ADR-1027-8 (mca-17a) | реестр/наблюдаемость | Новый процесс `intent.initiative`; второй канал/реестр нет |
| **AM-7** | REUSE ADR-1028-11 (mca-08) | речь/clarify | Второй классификатор/clarify запрещён; граница сигналов речи |
| **AM-8** | REUSE ADR-1028-12 (mca-15) | stats-intent | Не дублируется; NumericClaim-гард не трогается |
| **AM-9** | REUSE ADR-1028-13 (mca-11) | ToolResult/расходы | 7 статусов; tool→silent; notable-only; K5 OFF не трогается; расходы ≠ reward |
| **AM-10** | REUSE ADR-1028-14 (mca-10a) | случайность | `random_metadata`/одна probability-проверка; второй процент/draw нет; fallback-политика reuse; новые purpose не вводятся |
| **AM-11** | REUSE ADR-1028-15 (mca-16) | outcome/опыт | Decision отдаёт outcome-сигналы/refs; lessons/эпизоды создаёт только mca-16; lessons ≠ intent |
| **AM-12** | **Граница mca-10b** | 14.5/14.10 | mca-09 владеет структурой кандидатов (в т.ч. `communicative_intent`) и точками Decision; mca-10b — применения 14.6–14.11 и ExplorationRequest/Result; без второго процента/draw и второго action-schema |
| **AM-13** | REUSE mca-22 (ledger) | собственные ответы | Не независимое подтверждение; закрытие намерения — только по человеческому событию/реальному результату |
| **AM-14** | **Граница `NostalgiaWorker`** | проактивный контур | Делегирование кандидатов в единый Decision (D6); legacy direct-send только при K1/K3 OFF; второго контура нет |

---

## Последствия

**Плюсы:** одна точка выбора действия для инициативы; defer без ломки enum; stale-check закрывает A15/A16; намерения — queryable durable-состояние (витрина/журнал честные); нет второго send-path; OFF-паритет конструктивен (K1).

**Минусы/риски:** новый durable-контур и подгейты увеличивают поверхность (митигации — R3 threat-файл, THR-1…THR-15); делегирование nostalgia меняет её delivery-путь при ON (границы сохранены, OFF = legacy); heartbeat требует дисциплины «без LLM на тике» (проверяется счётчиками/fixture). Риск **R3** подтверждён; обработка — `threat-failure-analysis.md`.

**Связанные артефакты:** `spec.md` (design-freeze), `threat-failure-analysis.md`, `tasks.md` (T-5018/T-5019 ✅; T-5020+ для @Builder).
