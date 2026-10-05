# MCA-09 `mca-09-intents-initiative` — requirements-map (Step 1 @PM, 05.10.2026)

Feature: **`mca-09-intents-initiative`** — самостоятельные намерения и инициатива: память незавершённых намерений (Intent) + устойчивые интересы + самостоятельный выбор уместного действия (Decision `reply/react/silent/tool`; отложенное = silent + серверное планирование), лёгкий heartbeat due-намерений, проверка перед отправкой (stale-check); без второго контура инициативы (эпик `memory-context-autonomy`, Wave 3 — автономия; цепочка `10a ∥ 16 → 09 → 10b`).

Источник: `plans/current_task.md:464–512` (§13.1–§13.4; файл НЕ изменялся, R17). Приёмки §19: `:896` (A15), `:897` (A16), `:898` (A17). Смежные обязательные: §20.2 `:1015` («Намерения, инициативы, новые темы | ON»), §20.3 `:1038` (создание/закрытие намерения), §21 `:1055` (trace: удачная инициатива / корректное молчание / закрытое намерение), §27.1 `:1354` (строка «Намерения/инициатива/Decision»), §16.3 `:800–804` (наблюдение за инициативой — рендер mca-12), §11.2 `:413` (bundle: выбранное намерение и недавние действия), §14.10 `:690–696` (communicative intent — этап Decision), §14.5 `:602–614` (один выбор/один draw на ситуацию), §14.1 `:522–532` (5% — на ситуацию, не на сообщения), GEN-R3 `:22`, GEN-R9 `:29`, §4 `:89–90` (IntentService/DecisionPolicy), R17 `:36`, no-false-acceptance `:15167+`, MCA-23 HOLD `:20833–20859`.

Планирование: `plans/docs/mca-round1027-plan.md:204` (строка фичи: Wave 3, Risk R3, AMEND `CoordinatorDecision`/decision-making A7 — ADR-1026-20; REUSE существующий контур инициативы/транспорт), `:103–106` (MCA09-R1…R4), `:238–240` (Wave 3), `:250` (критпуть), `:415` (открытый вопрос №14 — ToolExecutor/mca-11, смежная граница); `plans/backlog.md:13`.

Нумерация задач: **T-5017+** (max занятого = **T-5016**, `plans/features/mca-16-experience-lessons/tasks.md`; T-5017… в `plans/**` — 0 хитов, grep 05.10.2026).

База на 05.10.2026 (PM-ориентир; перепроверяют @Architect/@DevOps): прод **2.58.58**; mca-16 **2.58.59 в полёте** (Reviewer Approved, reconcile T-5016 pending); HEAD `6b3d421` (docs mca-16); SQLite **v28** (mca-16; следующая свободная доменная — v29+); каталог **504/108/106/21** (REGISTRY/GROUPS/_TAB_BY_GROUP/TAB_RULES; Settings 441, delta 93); канон инструментов **12**; `REASON_CODES` 221, `KILL_SWITCHES` 64; merge-цель **§120+** (после §119 mca-16); ожидаемый ADR — **ADR-1028-16** (последний занятый ADR-1028-15 mca-16; номер проверить grep'ом на Step 2).

---

## 1. Подтверждение: следующая незавершённая MCA-задача

Порядок из плана: Wave 3 открыта парой `10a ∥ 16`; 10a закрыта, 16 — в финале (`mca-round1027-plan.md:238–240`). Остаток Wave 3: `mca-09`, `mca-10b`, `mca-10c`.

| Фича Wave 3 | Статус | Ссылка |
|---|---|---|
| `mca-10a-random-source-anu` | ✅ RELEASED + VERIFIED 2.58.58 + ARCHIVED (T-4987) | `mca-round1027-plan.md:205`; `backlog.md` §10.38 |
| `mca-16-experience-lessons` | ✅ Reviewer Approved; deploy 2.58.59 в полёте; reconcile T-5016 pending | `mca-round1027-plan.md:208`; `workflow_state.md` NOTE 68/69 |
| **`mca-09-intents-initiative`** | ⏭️ **следующая — зависимости закрыты; цепочка волны 09 → 10b** | `mca-round1027-plan.md:204`, `:239` |
| `mca-10b-random-applications` | после 10a+05+06+07 (все ✅), но 14.10 (communicative intent) — этап Decision из mca-09; в цепочке волны после 09 | `mca-round1027-plan.md:206`, `:239`; `:690–696` |
| `mca-10c-game-stub` | после 10a (изолированный stub, малый; вне критпути) | `mca-round1027-plan.md:207` |

**Почему `mca-09` (а не `mca-10b`/`mca-10c`):** (1) T-5016 — последнее документированное указание: «Следующая — `mca-09` (после 10a; Decision для 10b) либо `mca-10c`/`mca-10b` по факту; без ожидания владельца» (`plans/features/mca-16-experience-lessons/tasks.md` T-5016); (2) Wave 3 chain `:239`: `… → mca-09 → mca-10b`; §14.10 «форма участия» строится **на этапе Decision** (`:696`), т.е. 10b опирается на контракт 09; (3) зависимости 09 закрыты: mca-07 ✅ §99, mca-08 ✅ 2.58.55, mca-11 ✅ 2.58.57, mca-10a ✅ 2.58.58; (4) критпуть `:250` (`…mca-10a → mca-10b → mca-release`) требует Decision-контур из 09; 10c — изолированный stub без влияния на критпуть; (5) `workflow_state.md` NOTE 69: «next-task planning dispatched (@PM, expected `mca-09-intents-initiative` per T-5016)»; (6) MCA-23 — `PLANNED / HOLD`, запрещено выбирать до завершения оставшихся MCA (`current_task.md:20833–20859`).

**Проверка расхождений:** plan/backlog/workflow_state согласованы; других указаний «next task» не найдено. Расхождений нет.

## 2. Требования §13.1–§13.4 + приёмки A15–A17

Сквозная рамка: GEN-R3 `:22` (один координатор; не создавать второй контур инициативных сообщений), GEN-R9 `:29` (инициатива/темы/вопросы/юмор/любопытство/несогласие разрешены), GEN-R19 `:47` (REUSE), R17 `:36` (журналировать решения/причины пропуска; секреты не журналировать), §4 `:89–90` (IntentService/DecisionPolicy — логические компоненты внутри приложения).

| REQ | Требование (суть §13) | Якорь | Проверяемый критерий | Приёмки |
|---|---|---|---|---|
| **MCA09-R1** | «Свобода воли» = память незавершённых намерений + устойчивые интересы + самостоятельный выбор уместного действия; триггеры: новые сообщения / прямое обращение / изменение значимого события / наступление условия намерения / завершение полезного поиска; лёгкий heartbeat due-намерений без полного LLM на каждом тике; не читать 500 сообщений на каждую реплику автоматически. | §13.1 `:472–478` | (R1a) heartbeat-тик проверяет due-намерения без полного LLM-запроса и без чтения большого окна (fixture/счётчики); (R1b) тишина сама по себе не порождает отправку (нет таймера «обязательно говорить»); (R1c) каждый триггер ведёт к кандидату решения, а не к автоматической реплике. | A15, A17 `:896`, `:898` |
| **MCA09-R2** | Intent: поля (id/chat_id/kind/subject IDs/topic-event refs/цель/причина/source refs/created_at/not_before/expires_at или условие/activation_condition/status/attempts/last_evaluated_context_version/priority/linked_action_id); состояния `pending → deferred → fulfilled/abandoned/expired`, deferred→pending; завершённое не активируется без нового события; не создавать обязательство из каждой фразы; не накапливать (объединять/архивировать); 5–10 — не жёсткий предел. | §13.2 `:480–490` | (R2a) lifecycle-fixture: все переходы, deferred→pending, повторная активация только с новым событием/новой записью; (R2b) A15: результат уже сообщён → намерение закрыто без повторного вопроса; (R2c) дедуп/слияние + архивация завершённых; (R2d) не каждая фраза → обязательство; игнор без нового повода → без повтора. | A15 `:896` |
| **MCA09-R3** | Decision: продолжить action-schema `reply/react/silent/tool`; аддитивные поля (trigger_kind/intent_id/reply_target/candidate_actions/selected_candidate/reason_codes/source refs/context_version/recheck_conditions/next_check_at/random metadata); enum не ломать ради `defer` (отложенное = silent + серверное планирование); silent без verbalizer и без отправки; tool-result может завершиться silent; оценка уместности (тема/новизна/отношения/недавние реплики/чувствительность/необходимость/незакрытые намерения); без таймера «раз в 10 минут»; direct приоритет; дедуп только того же события. | §13.3 `:492–502` | (R3a) A17: silent/отложенный intent → verbalizer и отправка не вызываются (fixture-шпионы); (R3b) enum `reply/react/silent/tool` не расширяется; `defer` = silent + серверное планирование; (R3c) direct-приоритет: квота фоновой инициативы не подавляет прямой ответ; (R3d) дедуп только того же события при незавершённом direct request; (R3e) молчание не поднимает «желание» до гарантированной отправки. | A15, A17 `:896`, `:898` |
| **MCA09-R4** | Проверка перед отправкой: повторно проверить адресата/родителя/состояние намерения/новые ответы в ветке/включённость функций/разрешения инструмента; постороннее сообщение в другой ветке не отменяет готовый ответ; при смене условий — одна повторная оценка, затем отложить; логи `stale_context`/`already_answered`/`intent_closed` или точная причина; без цепочки своих сообщений без нового человеческого события/результата; chunks = одна логическая отправка. | §13.4 `:504–512` | (R4a) A16: смена темы во время подготовки → stale-check; ровно одна повторная оценка, без бесконечного пересмотра; (R4b) причина (`stale_context`/`already_answered`/`intent_closed`) видна в журнале; (R4c) разбиение на chunks считается одной логической отправкой; (R4d) нет цепочки собственных сообщений без нового события. | A16 `:897` |
| GEN-R3/GEN-R9 (сквозное) | Один координатор; второй контур инициативных сообщений не создаётся; инициатива/новые темы/вопросы/юмор/несогласие разрешены. | `:22`, `:29` | нет второго send-path: новый контур Intent/Decision работает через существующий координатор/транспорт; существующий проактивный контур (`NostalgiaWorker`) — reuse/делегирование, не дублирование (решение @Architect). | A15–A17 |
| GEN-R17/§27.1 (сквозное) | Строка матрицы «Намерения/инициатива/Decision»: условия/кандидаты/адресат/why-why-not/stale-check/исход; процесс/стадии/события/widget-ID для mca-17c. | `:1354`, `:41` | стадии видны на реальном запуске; OFF → честный `disabled/not_run`; R17-safe. | A48/A73 (частично) |

Проверка владельца (§13 преамбула `:470`): на витрине видно намерение и его состояние; причина отправки/ожидания/закрытия раскрывается в журнале.

## 3. Reuse-inventory (переиспользовать; вторых механизмов не создавать)

- **Существующий контур инициативы/транспорт:** `services/direct_chat_service.py` — единственный координатор (`handle()`, Phase P; `TRIGGER_FREE_WILL` `:787–849`; per-chat `flags.chat_autonomous_reply_enabled` `:807–809`; kind `autonomous_reply` `:792–794`); `services/direct_llm_react.py` — LLM-driven Decision ASAP-3.2 D11 (Stage-1 action; kill-switch `DIRECT_LLM_DECISION_ENABLED`); `services/nostalgia_worker.py` — существующий проактивный контур «кстати…» (тик 60 мин; гейты тишины/quiet-hours/cooldown/лимит/анти-спам; отправка `bot.send_message`) — источник/делегирование в единый Decision, не второй контур; `services/telegram_send.py` — текущий транспорт; `services/memory_maintenance.py` — APScheduler-хост фоновых тиков (прецедент mca-16 review-tick) — кандидат для heartbeat due-намерений.
- **CoordinatorDecision/decision-making A7:** `services/direct_chat_service.py:907–940` (`@dataclass CoordinatorDecision`; ADR-1026-14 D2 + ADR-1026-20 D1; `ARCHITECTURE.md:3606–3607`); инварианты `__post_init__` (action ∈ {reply,react,silent,tool}; style=silent недопустим; реакция только при react; reason_code ∈ REASON_CODES). AMEND — аддитивные поля §13.3; wire-`action` не вводится (граница A7); `claim_envelope.py:347–348` — mca-08 action-schema не трогал.
- **mca-11 ToolResult handoff:** `services/tool_result.py` (7 статусов; tool→silent); `services/mca_money_limits.py` (F-3 check→reconcile; K5 OFF); handoff T-4962 (`backlog.md:243/247`): F-1 notable-only `tool_accounting`, F-3 парный check→reconcile, F-4 пин `MCA_TOOL_TRANSIENT_RETRIES_MAX`; без слепого повтора (`delivery_unknown`).
- **mca-15 stats:** `services/chat_statistics.py` — `classify_stats_intent` (banter/historical/stats/mixed); граница intent/action-schema CA-15-8 (`backlog.md:232`); NumericClaim-гард не трогать.
- **mca-10a policy hooks:** `services/mca_random_source.py` (`RandomSourceService`/`ExplorationPolicy`; `draw_probability`/`choose`; durable `mca_random_draws`); handoff T-4987 (`backlog.md:260`): «mca-09 — политика/источник для Decision»; одна probability-проверка на автономную ситуацию (`:610`); fallback-off → необязательная случайная инициатива откладывается, direct живёт (`:550`); истинность/права/идентичность не рандомизируются (`:530`).
- **mca-07 bundle/retrieval:** `services/mca_retrieval_context.py` — единственный `EvidenceBundle`; mca-09 заполняет M-MCA07-2 (`ambiguities`/`unknown`/`contradictions`, §99.4) и маршрутизирует retrieval через `retrieve()` (L-MCA07-5); второй bundle/комбинированный retrieval запрещены.
- **mca-08 speech:** `services/claim_envelope.py` — `SpeechUnderstanding`/clarify (`ask/assume/none`, ≤1 anti-loop); не дублировать классификатор; сигнал читается сборкой промпта, не action-schema.
- **mca-16 outcome-сигналы:** handoff T-5016 — Decision отдаёт outcome-сигналы для банка опыта; lessons — отдельный тип, не смешивать.
- **mca-13/mca-17a:** `services/mca_events.py` — единый `REASON_CODES` (уже содержит `already_answered`/`wrong_moment`/`no_new_contribution`/`intent_not_due`/`intent_expired`/`intent_closed`/`stale_context`/`no_eligible_alternative` `:63–65` — базовый минимум §17.2); аддитивно только lifecycle-коды (список — @Architect); `services/mca_process_registry.py` — `direct.reply` pipeline со стадией `decision` `:121–135`; новый процесс/стадии — регистрация, второй канал запрещён.
- **mca-22:** `mca_bot_outputs`/`services/bot_output_ledger.py` — собственные ответы не независимое подтверждение; `contradicts`-связи.
- **mca-01/14:** `services/database.py::write_transaction` + `MigrationStep`; `task_jobs`/TaskSupervisor — durable состояние due-проверок (если нужно).
- **UI-границы:** §16.3 `:800–804` — компактное состояние инициативы на «Статусе» рендерит **mca-12**; полная матрица/виджеты — **mca-17c**; mca-09 даёт состояние/события/widget-ID, UI не делает.
- **Каталог/kill-switch:** паттерн `services/mca_gates.py` (env-only `ClassVar`, default ON); `services/param_catalog.py` + F8 ADR-1026-2 — только если Step 2 санкционирует UI-настройки.
- **Закрытые зависимости:** mca-07 ✅ §99, mca-08 ✅ 2.58.55, mca-11 ✅ 2.58.57, mca-10a ✅ 2.58.58; дополнительно доступны mca-01 §95, mca-13 §94, mca-14 §93, mca-15 2.58.56, mca-16 2.58.59 (в полёте), mca-05 2.58.42, mca-06 2.58.49, mca-17a §100, mca-22 2.58.44.

## 4. Conflict-audit (CA-09-1…10)

| # | Конфликт-кандидат | Существующий контракт | Действие mca-09 | Правило |
|---|---|---|---|---|
| CA-09-1 | Дублирование понимания речи/clarify (mca-08) | `SpeechUnderstanding`/`clarify_action` (mca-08, ADR-1028-11 D6/D7); `claim_envelope.py:347–348` — поля M-MCA07-2 и CoordinatorDecision/action-schema не тронуты; `test_mca08_style_form.py:867` | mca-09 владеет action-schema/intent_id; mca-08 — сигналы речи; второй классификатор/второй clarify запрещены; границу зафиксировать в spec | ADR-1028-11; §13.3 |
| CA-09-2 | Дублирование/опережение mca-10b (14.5–14.11) | §14.10 communicative intent — **этап Decision** (`:696`); 14.5 — единый выбор/один draw (`:602–614`); результаты exploration → очередь кандидатов, не отправка (`:614`) | mca-09 даёт структуру кандидатов (observation/question/opinion/joke/recall/silence) и точки Decision; выбор/применения 14.6–14.11 — mca-10b; без второго процента/второго draw | `:239`, `:690–696` |
| CA-09-3 | Смешение с банком опыта (mca-16) | handoff T-5016: Decision → outcome-сигналы; lessons — отдельный тип | mca-09 только эмитит outcome/refs; ExperienceEpisode/Lesson не создаёт; не смешивать с парадигмами/фактами | T-5016; §25.6 |
| CA-09-4 | Второй контур случайности | mca-10a: один `RandomSource`, политика 14.5, журнал draw; handoff T-4987 | random metadata Decision — из mca-10a; одна проверка на ситуацию; истинность/идентичность/права/финансы не рандомизируются; fallback-политика `:550` | `:530`, `:610` |
| CA-09-5 | Второй контур инструментов/расходов | mca-11: ToolResult 7 статусов; K5 OFF; handoff T-4962 (F-1/F-3/F-4) | tool-решение возвращает типизированный статус; tool→silent разрешён; account notable-only; check→reconcile парно; без слепого повтора; расходы ≠ reward | `:498`; `backlog.md:243/247` |
| CA-09-6 | Дублирование stats-intent (mca-15) | `classify_stats_intent` (banter/historical/stats/mixed); CA-15-8 | граница: mca-09 — намерения/действия, mca-15 — статистические запросы; второй классификатор запрещён; NumericClaim-гард не трогать | `backlog.md:232` |
| CA-09-7 | Второй bundle/retrieval | mca-07: единый EvidenceBundle; M-MCA07-2; `retrieve()` (L-MCA07-5) | поля ambiguities/unknown/contradictions — mca-09; retrieval только через `retrieve()`; второй bundle запрещён | §99.4 |
| CA-09-8 | Дублирование UI | §16.3 `:800–804` — витрина (mca-12); полная матрица (mca-17c) | mca-09 отдаёт состояние/события/widget-ID; UI-рендер не делает; без нового раздела | §16.3, MCA17-R8 |
| CA-09-9 | Второй контур инициативных сообщений (GEN-R3) | существующие: `TRIGGER_FREE_WILL`-автономия (A7/ASAP-3.2) + `NostalgiaWorker` (проактивные «кстати…») | новый контур не создавать: Intent/Decision — над существующим координатором/транспортом; судьба `NostalgiaWorker` (reuse/делегирование) — решение @Architect; один send-path | `:22`, GEN-R3 |
| CA-09-10 | Второй write/события/реестр | mca-01 write-механизм; mca-13 `REASON_CODES`/события; mca-14 миграции; mca-17a registry/trace | все записи — через единый write-механизм; коды — аддитивно; DDL — через mca-14; стадии — в единый реестр; существующие DECISION-диагностики Epic 3 (`services/agentic_events.py`) не дублировать (маппинг — @Architect) | GEN-R17; §4 |

Сквозные запреты: R17 (секреты/сырой текст не журналировать; без hidden chain-of-thought); не изменять `plans/current_task.md`; не трогать runtime вне санкций; не создавать вторые: контур отправки, IntentService-дубликат, Decision-контракт-дубликат, очередь, write-механизм, словарь событий, bundle, RandomSource, координатор, LLM-провайдер.

## 5. Что уже покрыто / что реально добавляет mca-09

| Область | Уже есть (проверить, не дублировать) | Реально добавить в mca-09 |
|---|---|---|
| Намерения | нет сущности Intent (только R17-коды `INTENT_*` классификации и базовые reason_code `intent_*` в словаре mca-13 `:63–65`) | Intent-модель/поля/жизненный цикл/дедуп/архивация; durable-хранилище |
| Decision | `CoordinatorDecision` (A1/A7), LLM-driven Decision ASAP-3.2 D11, enum `reply/react/silent/tool` | аддитивные поля §13.3 (intent_id/candidate_actions/recheck_conditions/next_check_at/random metadata), отложенное = silent + серверное планирование |
| Триггеры/heartbeat | free_will/reply-to-bot/mention-матрица; APScheduler-хост фоновых тиков | due-намерения по расписанию без полного LLM; триггеры §13.1; без чтения 500 сообщений |
| Проверка перед отправкой | частичные stale-гейты в direct-пути | явный stale-check §13.4 + логи причин + «одна повторная оценка» |
| Инициатива | `NostalgiaWorker` (проактивные «кстати…»), free_will автономия | единый Decision-контур для инициативы; без второго send-path |
| Наблюдаемость | `direct.reply` pipeline (стадия `decision`), `REASON_CODES`, registry | процесс/стадии intent/decision, аддитивные коды, widget-ID для mca-17c; §16.3-данные для mca-12 |

## 6. Зависимости и открытые заявки @Architect (Step 2 обязателен)

**Step 2 обязателен:** AMEND `CoordinatorDecision`/decision-making A7 (ADR-1026-20) — контракт решения расширяется аддитивно; требуются spec + ADR.

**Закрытые зависимости:** mca-07 ✅ §99 (bundle/retrieve), mca-08 ✅ 2.58.55 (speech), mca-11 ✅ 2.58.57 (ToolResult), mca-10a ✅ 2.58.58 (RandomSource/политика). Доступные смежные: mca-01 §95, mca-13 §94, mca-14 §93, mca-15 2.58.56, mca-16 2.58.59 (в полёте), mca-17a §100, mca-22 2.58.44, mca-05 2.58.42, mca-06 2.58.49.

**Заявки на санкции (решение @Architect; PM не решает):**
1. **Контракты:** Intent (поля §13.2, состояния, дедуп/архивация); Decision-аддитивные поля §13.3 (включая `defer` = silent + серверное планирование); структура `candidate_actions` (в т.ч. 14.10 communicative intent); stale-check §13.4; границы с 14.5/14.10 (mca-10b), mca-08 (speech/clarify), mca-15 (stats-intent), mca-16 (outcome-сигналы).
2. **Δ DDL:** intent-хранилище (+ due-проверки/линковка action) — **v29+** через реестр `mca-14` (v28 занята mca-16), либо Δ DDL=0 при переиспользовании существующих таблиц; точный набор — @Architect.
3. **Δ каталога:** ожидается **0** (kill-switch env-only; UI-настройки §13 не требует — наблюдение §16.3 рендерит mca-12); если Step 2 вводит UI-параметры — F8 ADR-1026-2 обязателен; точный Δ — @Architect.
4. **Kill-switches:** env-only имена (default ON; OFF = паритет 2.58.59), напр. master intent/decision + stale-check; точный список @Architect.
5. **reason_code:** базовые коды уже есть (`stale_context`/`already_answered`/`intent_closed`/`intent_not_due`/`intent_expired`/`wrong_moment`/`no_new_contribution` `:63–65`); аддитивно только lifecycle-коды (сверить существующие; вероятно +3…6).
6. **UI-контракт:** §16.3-данные (активные намерения/последний выбор/причина/источник случайности) — контракт для mca-12; widget-ID/стадии — для mca-17c; R17-safe.
7. **Risk:** плановый **R3** (`:204`) — подтвердить; обязателен `threat-failure-analysis.md`.
8. **Deploy:** практика CA-11 (пер-фичевый bump 2.58.59→2.58.60) либо `DEFERRED_TO_RELEASE` — решение @Architect; merge-цель `plans/ARCHITECTURE.md` **§120+** (после §119 mca-16); ADR — следующий свободный (ожидаемо **ADR-1028-16**; номер проверить grep'ом на Step 2).
9. **Существующий проактивный контур:** решение по `NostalgiaWorker` (reuse как источник кандидатов/делегирование в единый Decision vs явная граница) — без второго отправляющего контура (GEN-R3).
10. **Heartbeat-хост:** reuse APScheduler (`memory_maintenance.py`) vs новый job-тип в существующей очереди (`task_jobs`) — @Architect.

**Owner-часть live:** реальный чат (без имитации) — создание/закрытие намерения видно; повторного вопроса после закрытия нет; silent без verbalizer/отправки; stale-check при смене темы; витрина §16.3 — `PENDING OWNER` (no-false-acceptance `:15167+`, прецеденты T-4914/T-4940/T-4961/T-4986/T-5015).

## 7. Out of scope (явно)

- Применения 14.6–14.11 и живая визуализация выбора — **mca-10b**; stub 14.12 — **mca-10c**; RandomSource/ANU 14.1–14.4 — **mca-10a**.
- Полная визуализация/матрица аналитики, диагностические действия — **mca-17c**; рендер §16.3 — **mca-12**; SelfModel — **mca-18**; vision — **mca-19**; временной фактчек — **mca-20**; единый релиз/effective state — **mca-release**; unified response orchestrator — **MCA-23 (HOLD, `:20833–20859`)**.
- Вторые: контур отправки инициативы, IntentService-дубликат, Decision-контракт-дубликат, очередь, write-механизм, словарь событий, bundle, RandomSource, координатор, LLM-провайдер.

## 8. Маппинг «REQ → приёмки → задачи»

| REQ | Приёмки | Задачи tasks.md |
|---|---|---|
| MCA09-R1 | A15, A17 | T-5018/T-5019 (санкции), T-5020…T-5028 (блоки A/B) |
| MCA09-R2 | A15 | T-5020…T-5024 (блок A) |
| MCA09-R3 | A15, A17 | T-5029…T-5034 (блок C) |
| MCA09-R4 | A16 | T-5035…T-5037 (блок D) |
| GEN-R3/GEN-R9 | A15–A17 | T-5038 (единый контур) |
| GEN-R17 (контракт) | A48/A73 (частично) | T-5040 (наблюдаемость/widget-ID) |
| Сводная проверка/ревью | §19 `:874–976`, §21 | T-5041…T-5043 |
| Deploy/live/reconcile | §20 `:986–1045`, no-false-acceptance `:15167+` | T-5044…T-5046 |

**Статус документа:** `PLANNING_CONSISTENT` — при условии санкций @Architect (T-5018/T-5019) по пунктам §6. Код на шаге PM не менялся; `plans/current_task.md` не изменялся (R17).
