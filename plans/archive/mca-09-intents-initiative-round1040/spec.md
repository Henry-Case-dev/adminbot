# MCA-09 `mca-09-intents-initiative` — spec (design-freeze, Step 2 @Architect, 05.10.2026)

**Фича:** `mca-09-intents-initiative` (эпик `memory-context-autonomy`, Wave 3; цепочка `10a ∥ 16 → 09 → 10b`; критпуть `:250`). ТЗ — `plans/current_task.md:464–512` §13.1–§13.4 (файл не изменялся, R17); приёмки A15–A17 `:896–898`; §20.2 `:1015`; §20.3 `:1038`; §21 `:1055`; §27.1 `:1354`; §16.3 `:800–804`; §14.5 `:602–614`; §14.10 `:690–696`; no-false-acceptance `:15167+`. Решения — `adr-1028-16-intents-initiative.md` (ADR-1028-16). Санкции — §11. Трассировка — `requirements-map.md` (MCA09-R1…R4, CA-09-1…10). **Статус: `DESIGN_FROZEN`** — @Builder T-5020+ не выбирает решений сам.

**База (проверено на дереве 05.10.2026, HEAD `7b9cd85` — mca-16 deploy-doc):** прод **2.58.59** (mca-16 VERIFIED: миграция v27→v28 идемпотентна, backup-guard, F8 504, K1–K4 ON), SQLite **v28** (`_SCHEMA_VERSION_EXPERIENCE = 28`, `services/database.py:1072`; v29 свободна), каталог **504/108/106/21** (F8 `--check` OK 504, запущено 05.10.2026; Settings 441, delta 93), канон инструментов **12**, `REASON_CODES` **231** (`services/mca_events.py:60–261`, импорт-счёт), `KILL_SWITCHES` **68** (`services/mca_gates.py:29–365`, импорт-счёт), `APP_VERSION` `2.58.59` (`config/settings.py:3044`). **ADR-1028-16 свободен** (grep `plans/**` 05.10.2026: только плановые упоминания в mca-09; последний занятый — ADR-1028-15 mca-16); merge-цель — **§120+** (последний занятый §119 mca-16, `ARCHITECTURE.md:4466`; §118 mca-10a `:4449`).

**mca-16 контракт решения не трогал (проверено):** `git show --stat f97e641` — правки `services/direct_chat_service.py` в хунках 353/436/1947/2001/3979/4155/4166 (bundle/scoped-срез), `CoordinatorDecision` (`:906–940`) не изменён (сверено чтением текущего дерева); `nostalgia_worker.py`, `direct_llm_react.py`, `tool_result.py`, `mca_random_source.py`, `mca_money_limits.py` в diff mca-16 отсутствуют. mca-16 аддитивно добавил +10 reason_code (`mca_events.py:249–257`), K1–K4 (`mca_gates.py:341–365`), `self_learning.run` v1 (`mca_process_registry.py:899–940`), тик review (`memory_maintenance.py:45–46,101–117`), каталог +2 (F8 504).

---

## 1. D1 — Единый контур инициативы: модули, точки входа, heartbeat-хост

**Дом Intent-контура — новый модуль `services/mca_intents.py`:** `IntentStore` (durable v29, §9), `IntentService` (жизненный цикл/дедуп/архив/дисциплина/due-скан), `InitiativeCandidate` (структура кандидата), `SendRecheck` (§5), фасад `get_service()`. Записи — только через `write_transaction`/`serialized()` (mca-01, ADR-1027-3); refs — mca-04a; события — `emit_mca_event` (mca-13); retrieval — только `retrieve()` (mca-07); случайность — только `RandomSourceService`/`ExplorationPolicy` (mca-10a). **Вторые: сервис/стор/контур отправки/движок решений/очередь/словарь/bundle/RandomSource запрещены.**

**Контракт решения — существующий `CoordinatorDecision`** (`services/direct_chat_service.py:906–940`; A1/ADR-1026-14 + A7/ADR-1026-20) — **аддитивные поля §4**; `DecisionCandidate` живёт в том же модуле (дом контракта; второй контракт не вводится; без цикла импортов). `__post_init__`-инварианты A7 сохраняются.

**Точка входа инициативы — та же координатор-машина:** аддитивный вход `DirectChatService` для решения **без входящего сообщения** (кандидат: heartbeat/nostalgia/search/significant event), использующий тот же `CoordinatorDecision`, тот же слой A7 (Phase P/T семантика, §4) и **единственный транспорт** `services/telegram_send.py` (`send_text:98`). Wire-`action`/Stage-1/2 JSON не меняются. Второго send-path нет; `direct_output_kind` (`:790–795`) расширяется для нового kind (например, `initiative_reply`) аддитивно (mca-22 ledger — существующий).

**Heartbeat-хост — существующий APScheduler обслуживания:** джоб `intent_heartbeat_tick` в `MemoryMaintenanceService` (прецедент mca-16: `JOB_EXPERIENCE_REVIEW_ID` `memory_maintenance.py:66`, регистрация `:101–117`, `IntervalTrigger` + `max_instances=1, coalesce=True`; второй планировщик/очередь не вводится). Интервал — код-константа `_INTENT_HEARTBEAT_TICK_SECONDS = 300` (Δ каталога = 0; НЕ «таймер обязательной речи» — тик только ищет due-намерения и порождает кандидатов). Тик **не вызывает LLM** и не читает большое окно сообщений; per-intent `task_jobs` не создаются (durable-намерения + due-скан по timestamp; пропущенные тики догоняются следующим сканом; очередь не засоряется). Батч ограничен (§10).

**OFF (K1):** контур инертен: v29 не читается, джоб не регистрируется, кандидатов/событий нет, nostalgia — legacy (§7). Бит-в-бит 2.58.59.

---

## 2. D2 — Intent: поля, состояния, гигиена, дисциплина (§13.2 `:480–490`)

**Поля (таблица `mca_intents`, v29; §9):**

| Поле | Тип | Семантика |
|---|---|---|
| `intent_id` | TEXT PK | стабильный ID (`intent:<chat>:<kind>:<hash>`; идемпотентность — `dedup_key`) |
| `chat_id` | INTEGER NOT NULL | чат намерения |
| `kind` | TEXT NOT NULL | закрытый: `follow_up` (спросить о собеседовании) / `answer_extension` (дополнить прежний ответ) / `topic_interest` (обсудить заинтересовавшую тему) / `open_dispute` (вернуться к незавершённому спору) |
| `subject_ids_json` | TEXT | устойчивые ID участников (mca-03); R17-safe |
| `topic_refs_json` | TEXT | topic/event refs (эпизод/история/сообщение; R17-safe refs, не текст) |
| `goal` | TEXT | краткая каноническая цель (серверная, R17-safe, ≤200; сырые цитаты/секреты запрещены) |
| `reason` | TEXT | краткая каноническая причина (код+refs, R17-safe, ≤200) |
| `origin` | TEXT NOT NULL | закрытый: `unanswered_question` / `explicit_request` / `unfinished_topic` / `search_result` |
| `source_refs_json` | TEXT | типизированные refs через mca-04a (`source_ref_id`; durable-связи — существующие `mca_evidence_links`) |
| `created_at` / `updated_at` | INTEGER | unix-время |
| `not_before` | INTEGER NULL | «не раньше» |
| `expires_at` | INTEGER NULL | срок (или условие пересмотра) |
| `activation_condition` | TEXT NULL | закрытый: `time_due` / `new_reply` / `topic_resume` / `event_change` / `search_completed` |
| `status` | TEXT NOT NULL | `pending` / `deferred` / `fulfilled` / `abandoned` / `expired` |
| `attempts` | INTEGER DEFAULT 0 | число фактических попыток (не «домогательство») |
| `last_evaluated_context_version` | TEXT NULL | версия контекста последней оценки |
| `priority` | INTEGER DEFAULT 0 | bounded; порядок кандидатов |
| `linked_action_id` | TEXT NULL | ref действия/ledger (mca-22) |
| `dedup_key` | TEXT UNIQUE | дедуп/слияние (chat+kind+subject+topic-канон) |
| `merged_into_id` | TEXT NULL | слияние дублей |
| `archived_at` | INTEGER NULL | архивация завершённых (retention/prune) |
| `next_check_at` | INTEGER NULL | серверное планирование due-проверки (deferred/silent) |

**Жизненный цикл:** `pending → deferred → fulfilled/abandoned/expired`; `deferred → pending` (при наступлении `activation_condition`/`not_before`/новом событии). **Завершённое намерение не активируется повторно без нового события и новой записи** (терминальный статус не флипается; повторный интерес — новая строка со ссылкой на предшественника через `merged_into_id`/refs). Переходы журналируются notable-событиями (§10).

**Закрытие (A15):** если результат уже сообщили (`already_answered`) или тема закрыта — `fulfilled`/`abandoned` **без повторного вопроса**; если вопрос проигнорировали — `deferred` с `activation_condition=new_reply|topic_resume` (event-based, **без таймерного повтора**); истечение — `expired`. Молчание — нормальный исход.

**Гигиена:** дедуп/слияние одинаковых (chat+kind+subject+topic) — `intent_merged`; пересмотр актуальности (expires/conditions); архивация завершённых (`archived_at`, retention §11); **5–10 — не жёсткий продуктовый предел** (bounded только гигиеной + батчем тика + priority). Монотонного роста нет.

**Дисциплина обязательств:** **не каждая фраза → обязательство.** Создание только при явном сигнале: (a) неотвеченный вопрос к боту/человеку с будущей релевантностью; (b) явная просьба вернуться; (c) явно помеченная незавершённая тема; (d) завершение полезного поиска с непустым результатом, предназначенным чату. Намерение связано с `reason` и **не является разрешением домогаться ответа**: `attempts` растёт, после `MCA_INTENT_MAX_ATTEMPTS` без результата и без нового повода → `abandoned` (честное закрытие).

**OFF (K1):** записей/чтений нет; v29 инертна.

---

## 3. D3 — Decision: аддитивный контракт, silent/defer, уместность (§13.3 `:492–502`)

**Enum не ломается:** `action` ∈ {`reply`,`react`,`silent`,`tool`} (`direct_chat_service.py:648–651`) остаётся; **`defer` — не значение enum**: отложенное = `silent` + серверное планирование (`next_check_at`/статус намерения `deferred`). Если передан незнакомый action — существующая нормализация в `reply` (R3-инвариант сохраняется); спецификация запрещает вводить `defer`.

**Аддитивные поля `CoordinatorDecision` (все с default; A7-инварианты сохраняются):**

| Поле | Тип | Семантика |
|---|---|---|
| `trigger_kind` | str = "" | закрытый: `new_message` / `direct_address` / `significant_event` / `intent_due` / `search_completed` / `nostalgia_due` (делегированный тик §7); незнакомое → "" |
| `intent_id` | str\|None | намерение-источник (не путать с A1-полем `intent` — классификация) |
| `reply_target` | str\|None | стабильный ref адресата/ветки инициативного ответа (R17-safe); `target_message_id` (int) остаётся для реакций |
| `candidate_actions` | tuple[DecisionCandidate, …] = () | структура кандидатов (≤ `MCA_INTENT_CANDIDATES_MAX`=8) |
| `selected_candidate` | str\|None | id выбранного кандидата (обязан ∈ `candidate_actions`, иначе None) |
| `reason_codes` | tuple[str, …] = () | доп. коды (каждый ∈ `REASON_CODES`; незнакомые отбрасываются); `reason_code` (A7) остаётся основным |
| `source_refs` | tuple[str, …] = () | refs триггера/доказательств (R17-safe) |
| `context_version` | str\|None | версия контекста решения (mca-07) |
| `recheck_conditions` | tuple[str, …] = () | закрытый: `addressee_changed` / `parent_changed` / `intent_state_changed` / `new_replies` / `enabled_changed` / `tool_permission_changed`; незнакомые отбрасываются |
| `next_check_at` | int\|None | серверное планирование отложенного (≥0) |
| `random_metadata` | dict\|None | read-only копия из mca-10a: `policy_version`/`requested_source`/`actual_source`/`draw_ids`/`probability`/`fallback_reason`/`deferred` (незнакомые ключи отбрасываются; второй draw не делается) |
| `tool_outcome` | str\|None | статус ToolResult (7, `tool_result.py:37–48`) при фактическом tool-ходе; ref, не сырой вывод |

**`DecisionCandidate`** (frozen, там же): `candidate_id`; `action` ∈ enum; `communicative_intent` ∈ {`observation`,`question`,`opinion`,`joke`,`recall`,`silence`} | None — **структура семантики кандидата §14.10 принадлежит mca-09; применения 14.6–14.11 — mca-10b** (`:690–696`; без второго action-schema); `source` ∈ {`intent`,`memory`,`nostalgia`,`random`,`search`}; `reason_code` ∈ `REASON_CODES`; `source_refs`; `prepared_text_ref` (для заранее сформированного текста, напр. nostalgia; сырой текст не логируется); `random_meta`; `admissible` (отклонённые кандидаты сохраняются с причиной — why-why-not).

**Silent:** не проходит Вербализатор и **ничего не отправляет** (ни текста, ни реакции, ни 🗿) на инициативном/отложенном пути и при tool→silent. Граница A7: legacy silent-ack direct-autonomous (🗿 hardcode, ASAP-3.2 §50) не трогается — на том пути mca-09 silent-решений не порождает (паритет). Технический текст о молчании в Telegram не приходит.

**Tool→silent:** инструмент не обязывает публиковать ответ. `action=tool` с неподходящим к публикации результатом завершается `action=silent` + `tool_outcome` + `reason_codes` (`no_new_contribution`/`insufficient_evidence`); инвариант A7 §43 сохраняется: explicit/вопрос/force — никогда silent; tool→silent допустим только на нефорсированном/инициативном пути. `delivery_unknown` — без слепого повтора (mca-11, §8).

**Уместность** учитывает: текущую тему, новизну вклада, отношения, недавние собственные реплики, чувствительность момента, необходимость ответа, незакрытые намерения. Реализация — аддитивные сигналы/правила существующего детерминированного слоя (Phase P, `_decision_pre_action:1117`); **третий LLM-вызов не вводится** (AMEND ADR-1026-20 сохраняет инвариант `physical-two-call-pipeline`); правила §42–§45/§47 не переопределяются.

**Запреты:** таймер «раз в 10 минут обязательно говорить»; повышение «желания» до гарантированной отправки из-за тишины (молчание не увеличивает шанс следующей отправки). **Direct приоритет:** квота фоновой инициативы не подавляет прямой ответ (существующий порядок `mca_money_limits.py:315–318` reuse). **Дедуп только того же события** при незавершённом direct request (существующий dedup по update; дедуп похожих фраз не вводится).

**OFF (K1/K3):** поля пусты/инертны; A7-путь и wire-контракты байт-идентичны 2.58.59.

---

## 4. D4 — Проверка перед отправкой (§13.4 `:504–512`)

**Единый `SendRecheck`** применяется на границе отправки для решений с непустыми `recheck_conditions` и **для всех инициативных/отложенных отправок** (heartbeat/nostalgia/deferred/tool→silent). Обычный direct-ответ (пустые `recheck_conditions`) существующими гейтами и ограничивается — поведение A7 не меняется.

**Проверки (в порядке):**
1. **Включённость:** гейты/флаги/чатовые разрешения — OFF → отмена с точной причиной, отправки нет.
2. **Адресат/родитель:** `reply_target`/родитель разрешимы, ревизия родителя не изменилась (`parent_changed`/`addressee_changed`).
3. **Состояние намерения:** `intent_id` в `pending|deferred`; терминальный → отмена `intent_closed` (повторно не активируется, отправки нет).
4. **Новые ответы в релевантной ветке:** тема уже закрыта/результат сообщён человеком → отмена `already_answered`, намерение → `fulfilled` (A15: закрыть без вопроса).
5. **Разрешения инструмента:** для tool-действия; `denied` → без слепого повтора.
6. **Посторонняя ветка:** активность в другой ветке **не отменяет** готовый ответ (проверка branch-scoped).

**Одна повторная оценка:** при смысловой смене условий — ровно **одна** повторная оценка с новым контекстом (`context_version` обновляется через существующий retrieval). При повторной смене — **отложить** (`status=deferred` + `next_check_at`, событие `recheck_deferred`), бесконечного пересмотра нет.

**Логи причин:** `stale_context` / `already_answered` / `intent_closed` (существуют, `mca_events.py:63–65`) или другая точная причина; `recheck_deferred` — новый (§11).

**Без цепочек:** собственные сообщения не порождают следующее собственное сообщение без нового человеческого события/реального нового результата; после отправки follow-up требует нового события/новой записи. **Chunks = одна логическая отправка:** stale-check выполняется один раз до первого chunk; разбиение на Telegram-chunks не дублирует проверку и не создаёт второй логический send; частичный сбой — существующая delivery-семантика (`delivery_unknown`).

**OFF (K1/K4):** слой проверок неактивен; инициативный путь не работает (K1) либо работает с документированным подмножеством (K4 OFF — без нового recheck-слоя, существующие гейты); паритет master-OFF.

---

## 5. D5 — Триггеры и лёгкий heartbeat (§13.1 `:472–478`)

**Триггеры (закрытый `trigger_kind`):** новые сообщения (`new_message`), прямое обращение (`direct_address`), изменение значимого события (`significant_event` — ревизии/статусы mca-03/mca-05), наступление условия намерения (`intent_due` — `not_before`/`next_check_at`/`activation_condition`), завершение полезного поиска (`search_completed` — mca-07/mca-11 refs). **Каждый триггер ведёт к кандидату решения, не к автоматической реплике**; тишина сама по себе не порождает отправку.

**Heartbeat:** due-скан SQL (`status IN ('pending','deferred') AND next_check_at<=now`), дешёвые гейты, bounded-батч (≤`MCA_INTENT_HEARTBEAT_BATCH_MAX`=20), coalesce ≤1 кандидат на чат за тик; **без LLM на тике**, без чтения большого окна; кандидаты идут в существующий координатор (§1). Нет автоматического полного окна «500 сообщений на реплику»: инициативная оценка использует только существующий retrieval через `retrieve()` (mca-07) с бюджетом §11.3 ТЗ. Пропущенные тики догоняются следующим due-сканом; durable-состояние — `mca_intents`.

**OFF (K1/K2):** тик не регистрируется/не работает; намерения могут создаваться/закрываться (K2 OFF), но due-оценки нет; паритет master-OFF.

---

## 6. D6 — `NostalgiaWorker`: делегирование в единый Decision (CA-09-9)

**Решение:** существующий проактивный контур «кстати…» (`services/nostalgia_worker.py:1–40`; тик 60 мин; гейты тишины/quiet-hours/cooldown/лимит/анти-спам; отправка `bot.send_message`) **переклассифицируется в источник кандидатов** единого контура: при K1+K3 ON его готовый кандидат (текст уже сформирован — 1 облачный LLM-вызов внутри nostalgia, без изменений) подаётся в координатор-вход инициативы (`source=nostalgia`, `prepared_text_ref`, `trigger_kind=nostalgia_due`) и проходит **уместность + recheck**; отправка — единственным транспортом; решение может завершиться `silent` (честный статус в `nostalgia_log` — без ложного `sent`). Собственные гейты nostalgia выполняются **до** подачи и не обходятся.

**OFF (K1 или K3):** nostalgia — legacy direct-send, бит-в-бит 2.58.59. Второго контура инициативы не создаётся; один движок решений, один send-path.

---

## 7. D7 — Границы и интеграции (REUSE, без вторых механизмов)

- **mca-10a (`:530`,`:610`; handoff T-4987):** Decision получает `random_metadata` только из существующих `RandomSourceService`/`ExplorationPolicy.choose` (`mca_random_source.py:949–1005`; purposes 10a, `:74–84` — **новые purpose не вводятся**, conversation_variant — mca-10b). **Одна probability-проверка на автономную ситуацию**, один целостный альтернативный кандидат (отдельный draw, при необходимости); истинность/права/идентичность/финансы не рандомизируются; fallback-политика 10a reuse (запас→PRNG→defer необязательной инициативы; direct жив). Второго процента/draw нет.
- **mca-11 (`:498`; handoff T-4962):** tool-решение возвращает типизированный `ToolResult` (7 статусов, `tool_result.py:37–48`); tool→silent (§3); учёт расходов notable-only (F-1), check→reconcile парно (F-3), пин retries (F-4); без слепого повтора (`delivery_unknown`); K5 OFF не трогается; расходы/квота ≠ reward; порядок деградации `maintenance→autonomous→direct` reuse.
- **mca-07 (§11.2; CA-09-7):** единственный `EvidenceBundle`; mca-09 заполняет `chosen_intent` (`mca_retrieval_context.py:221`), `recent_actions` (`:222`) и M-MCA07-2 поля `ambiguities`/`unknown`/`contradictions` (`:211/:216/:217`) из оценки намерений; retrieval — только `retrieve()`; второй bundle/комбинированный retrieval запрещены.
- **mca-08 (CA-09-1):** второй классификатор речи/clarify не вводится; сигналы `SpeechUnderstanding` читаются сборкой промпта; `claim_envelope.py:347–348` не трогается.
- **mca-15 (CA-09-6):** stats-intent не дублируется; mca-09 владеет намерениями/действиями, mca-15 — статистикой; NumericClaim-гард не трогается (CA-15-8).
- **mca-16 (CA-09-3; handoff T-5016):** Decision отдаёт outcome-сигналы/refs (события §10 + refs) для банка опыта; ExperienceEpisode/Lesson создаёт только mca-16; lessons ≠ intent; парадигмы/факты не смешиваются.
- **mca-22:** собственные ответы (`mca_bot_outputs`) — **не независимое подтверждение**; намерение закрывается только по человеческому событию/реальному результату, не по собственному сообщению бота.
- **mca-13/17a (CA-09-10):** единый `emit_mca_event`/`REASON_CODES`/реестр процессов; второй канал/словарь запрещён; существующие DECISION-диагностики Epic 3 не дублируются (маппинг — §10).

---

## 8. D8 — Хранение: additive v29 через mca-14 (Δ DDL)

**Δ DDL = v29** (`MigrationStep(29)`, реестр mca-14; v29 свободна — прод v28/mca-16, `database.py:1072`): **1 аддитивная таблица + 4 индекса**:

- `mca_intents` — колонки §2; индексы: UNIQUE `dedup_key`; `(chat_id, status, next_check_at)`; `(status, next_check_at)`; `(chat_id, kind, status)`.

Аддитивно, идемпотентно (повтор — no-op), **PG — no-op**; backup-guard fail-closed до DDL + read-back (mca-14); старый код v29 не читает (cold-совместимо); backfill нет (новая таблица пустая — честный unknown).

**Обоснование против Δ DDL = 0:** `task_jobs.payload`/JSON-блобы не дают запросов по `status/chat/next_check_at`, UNIQUE-дедупа, слияния и retention; использование очереди как хранилища противоречит её назначению (mca-01); файловый store — второй write-механизм (отклонён прецедентом mca-10a). Queryable durable-состояние намерений нужно для A15 (закрытие видно), heartbeat-скана, дедупа/архивации и наблюдаемости §16.3; прецедент — каждая durable-фича эпика получила аддитивные таблицы (v21–v28).

**Retention/восстановимость:** терминальные/архивные строки прунятся по `MCA_INTENT_RETENTION_DAYS`=180 (env-only); активные — не прунятся; `merged_into_id`/refs сохраняют происхождение; ошибка записи не блокирует рабочий ответ (fail-open, честная причина).

**OFF (K1):** таблица инертна; миграция v29 безопасна (аддитивна).

---

## 9. D9 — Наблюдаемость и UI-контракт (GEN-R17/§27.1/§16.3)

**Реестр:** новый `ProcessDefinition(process_id="intent.initiative", version="1")` (owner mca-09; `mca_process_registry.py`): purpose «Намерения и инициатива: триггер → кандидат → решение → проверка → доставка/отсрочка/закрытие»; stages `("trigger","candidate","decide","recheck","deliver","close")`; `trigger_kind="event"`, `schedule="heartbeat 300s + события"`; `state_source=("mca_intents","mca_events","task_jobs")`; `recovery_ops=("intent_rescan","deferred_resume")`; `enabled_gate="MCA_INTENTS_ENABLED"`; `widget_id="Намерения и инициатива"` (контракт mca-17c; рендер не здесь); `stages_to_events={"trigger":"intent_created","decide":"initiative_decided","recheck":"recheck_deferred","close":"intent_fulfilled"}`; `instrumentation=("trigger","decide","recheck","close")` (notable-only). Плейсхолдер `context.compress` v0 (`:845–851`, owner mca-09) — **не наш процесс** (устаревшая метка); не амendится; инцидентал-наблюдение для Orchestrator/PM (пере-метка при reconcile).

**События — notable-only через единственный `emit_mca_event` (`mca_events.py:529–557`):** `intent_created`, `intent_merged`, `intent_fulfilled`, `intent_abandoned`, `intent_archived`, `initiative_decided` (≤1 на ситуацию; trigger_kind/source/action/selected_candidate/reason_codes/context_version/intent_id), `recheck_deferred`. Группа метрик — существующая `initiatives` (`mca_events.py:1014–1026`); второй группы/канала нет. Версии/причины/refs обязательны; **R17: только ID/коды/enum/числа/refs** — без сырого текста, секретов, hidden CoT.

**UI-контракт для mca-12 (§16.3 `:800–804`; рендер — не здесь):** компактное фактическое состояние на существующем «Статусе»: активные намерения (число + top: kind/goal/status/next_check_at/priority), последнее инициативное действие/пропуск + краткая причина, источник случайности/fallback (уже mca-10a); раскрытие — существующий журнал/trace. Данные — из `mca_intents` + `mca_events` через существующий status-снимок (прецедент `status_service.random_source_snapshot:410–474`); **новых маршрутов нет** (`ROUTES_SHA256_F11` без изменений); никаких выдуманных «мыслей»/псевдоизмерений; RBAC/чат-скоуп (прецедент mca-10a/mca-16); OFF → честный `disabled/not_run`.

**§27.1 (`:1354`) строка «Намерения/инициатива/Decision»:** условия, кандидаты, адресат, why/why-not (`reason_codes`/отклонённые кандидаты), stale-check, исход — раскрываются событиями/журналом; trace не рвётся (intent↔trigger refs↔decision↔action↔delivery).

---

## 10. D10 — Kill-switches и env-only лимиты

Kill-switches — env-only `ClassVar[bool]` (`config/settings.py`; прецедент `:1459–1466`), реестр `mca_gates.KILL_SWITCHES` (`:29–365`) + резолверы (per-call, не бросают):

| # | Имя | Default | OFF-паритет |
|---|---|---|---|
| K1 | `MCA_INTENTS_ENABLED` (master) | ON | бит-в-бит 2.58.59: нет записей/чтений v29, нет heartbeat, нет кандидатов/событий; nostalgia legacy; UI `disabled/not_run` |
| K2 | `MCA_INTENT_HEARTBEAT_ENABLED` | ON | due-тик не работает; создание/закрытие намерений возможно; нет due-кандидатов |
| K3 | `MCA_INTENT_DECISION_ENABLED` | ON | инициативные решения/делегирование nostalgia не выполняются (nostalgia legacy); recheck-путь инертен |
| K4 | `MCA_SEND_RECHECK_ENABLED` | ON | новый recheck-слой не выполняется (документированное подмножество: существующие гейты остаются) |

Переиспользуются и **не дублируются:** `DIRECT_DECISION_MAKING_ENABLED`/`DIRECT_LLM_DECISION_ENABLED` (A7/ASAP-3.2), `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` (mca-13), `MCA_OBSERVABILITY_ENABLED` (mca-17a), `MCA_RETRIEVAL_CONTEXT_ENABLED`/`MCA_EVIDENCE_BUNDLE_ENABLED` (mca-07), `MCA_RANDOM_*` (mca-10a), `MCA_TOOL_*`/`MCA_MONEY_LIMITS_ENABLED` (mca-11; K5 OFF не трогается), `MCA_EXPERIENCE_*` (mca-16).

Env-only лимиты (не каталог): `MCA_INTENT_HEARTBEAT_BATCH_MAX`=20 (≥1), `MCA_INTENT_MAX_ATTEMPTS`=3 (≥1), `MCA_INTENT_CANDIDATES_MAX`=8 (≥1), `MCA_INTENT_RETENTION_DAYS`=180 (≥1), `MCA_INTENT_DEFER_BACKOFF_SECONDS`=1800 (≥60; bounded backoff «не тот момент», не nag-таймер). Тик — код-константа 300 с.

---

## 11. D11 — Санкции T-5019 (поимённо)

1. **Δ DDL = additive v29** (`MigrationStep(29)`, mca-14): 1 таблица `mca_intents` + 4 индекса (§8), backup-guard fail-closed + read-back, идемпотентно (повтор no-op), PG no-op, v29 свободна. Обоснование против 0 — §8.
2. **Δ каталога = 0:** kill-switches/лимиты — env-only; §13 не требует UI-настройки; наблюдение §16.3 рендерит mca-12; **F8 ADR-1026-2 NOT_APPLICABLE**; счётчики `504/108/106/21` (Settings 441, delta 93) не меняются; новых маршрутов нет → `ROUTES_SHA256_F11` без изменений. Если Builder обнаружит реальную потребность UI-параметра — отдельная заявка @Architect (не в этом design-freeze).
3. **Канон инструментов 12** — без изменений; новых tools/handlers нет.
4. **reason_code: ровно +6** в единственный `REASON_CODES`: `intent_created`, `intent_merged`, `intent_fulfilled`, `intent_abandoned`, `intent_archived`, `recheck_deferred`; переиспользуются `stale_context`/`already_answered`/`intent_closed`/`intent_not_due`/`intent_expired`/`wrong_moment`/`no_new_contribution` (`:63–65`); второй словарь запрещён.
5. **Risk: R3** (подтверждение планового `mca-round1027-plan.md:204`) — `threat-failure-analysis.md` обязателен (THR-1…THR-15).
6. **Deploy: CA-11 per-feature bump** `APP_VERSION 2.58.59 → 2.58.60` (прецедент mca-06/08/11/15/10a/16), пер-фичевый; проверки: health/версия, backup-guard + миграция v28→v29 идемпотентно (повтор no-op), PG no-op, kill-switches default ON 0 env-оверрайдов, R17=0, F8 `--check` OK 504 (Δ=0), focused-повтор; **rollback:** soft — K1–K4=false + рестарт (v29 аддитивна/инертна), cold — git revert feat-коммита (checkout 2.58.59; restore не требуется).
7. **Merge:** `plans/ARCHITECTURE.md` **§120+** + **ADR-1028-16** → Accepted (по merge). Клейм v29 фиксируется здесь и в ADR-1028-16 D8; AMEND `arch-frames.md` §1.2 — на reconcile (не в этом шаге).
8. **Live (PENDING OWNER, no-false-acceptance `:15167+`):** реальный чат без имитации — создание/закрытие намерения видно; повторного вопроса после закрытия нет; silent без verbalizer/отправки; stale-check при смене темы; витрина §16.3 (T-5045).
9. **UI-контракт:** §16.3-данные + widget-ID «Намерения и инициатива» — контракт mca-12/mca-17c; рендер не здесь; верхнеуровневых разделов нет.

---

## 12. REQ → приёмки → задачи

| REQ | Решения | Приёмки | Задачи |
|---|---|---|---|
| MCA09-R1 | D1, D5 | A15, A17 `:896`, `:898` | T-5018/T-5019 (санкции), T-5025–T-5028 |
| MCA09-R2 | D2, D8 | A15 `:896` | T-5020–T-5024 |
| MCA09-R3 | D3, D7 | A15, A17 | T-5029–T-5034 |
| MCA09-R4 | D4 | A16 `:897` | T-5035–T-5037 |
| GEN-R3/GEN-R9 | D1, D6 | A15–A17 | T-5038 |
| GEN-R17/§27.1 | D9 | A48/A73 (частично) | T-5040 |
| Сводная проверка/ревью | §11 | §19 `:874–976`, §21 | T-5041–T-5043 |
| Deploy/live/reconcile | §11.6–11.8 | §20 `:986–1045`, `:15167+` | T-5044–T-5046 |

## 13. OFF-паритет по решениям

D1→K1; D2→K1; D3→K1 (подгейт K3 — инициативные решения; silent/defer поля инертны); D4→K1/K4; D5→K1/K2; D6→K1/K3 (иначе nostalgia legacy); D7→K1; D8→K1 (v29 инертна); D9→K1 (событий нет; UI `disabled/not_run`); D10→K1–K4; D11→K1. **K1 OFF = бит-в-бит 2.58.59** для всего пути; каждый под-гейт OFF — документированное подмножество (таблица §10). Дефолты ON аддитивны и не меняют baseline без новых записей/отправок.

---

**Статус документа:** `DESIGN_FROZEN` — санкции §11 обязательны для T-5020+; `plans/current_task.md` не изменялся (R17); runtime/test-код на Step 2 не менялся; ADR-1028-16 — Proposed (merge §120+ по reconcile). Следующий шаг — @Builder T-5020+ без дополнительных решений; live-часть — PENDING OWNER.
