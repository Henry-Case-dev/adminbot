# W1-CHAT-INTEL — отчёт лейна (B01 Initiative + B02 Experience semantic)

База: HEAD bc91b90. LLM — только моки (по брифу). Не коммичено.
Кандидат: рабочее дерево (см. «Файлы»); fingerprint проверяется Orchestrator'ом
по `git diff`/`git status` на момент join.

## Реализовано (файл:функция)

### B01 — `services/initiative_observer.py` (НОВЫЙ, ~950 строк)
- `observe_tick` / `enqueue_observe` / `get_active_observe` — durable-job
  `initiative.observe` (coalesce `initiative.observe:global`, owner asap8b01)
  в СУЩЕСТВУЮЩЕЙ очереди `task_jobs` (прецедент `experience.review`).
- `InitiativeObserverRunner` — реентерабельный исполнитель:
  - `_scan_phase` — durable-курсор по `smart_messages.id`, дешёвая
    квалификация (non_text/forward/empty/command/no_author/not_group) +
    счётчики observed/eligible/scan_skipped. Диагностика «сколько видит» —
    payload-счётчики + событие `initiative_observer_scan` (B01.1, B01.2-диагностика).
  - `_evaluate_phase` — bounded semantic evaluation: НЕ на каждую реплику.
    Per-chat гейт/лимиты → компактное окно (≤14 реплик по монотонному
    rowid) → ОДИН LLM-вызов (`module="initiative"`, `step="opportunity_eval"`,
    ≤300 токенов, ≤45с) с memory-подсказками (`_memory_hints` — серверный
    канон проверенных уроков, B01.6) → `parse_verdict` (whitelist kind/
    action/horizon, канон goal ≤200).
  - `_act_on_opportunity` — разделение B01.2: ephemeral (SAY/REACT сейчас →
    СУЩЕСТВУЮЩИЙ `handle_initiative` mca-09: decide_initiative → L1 →
    Direct L2 Writer → SendRecheck → telegram_send; третьего Writer нет) vs
    durable intent (`horizon=later` и при недоступности Writer →
    `create_intent(origin="unfinished_topic", kind=topic_interest/
    open_dispute)` — повод не теряется).
  - `_diagnose_phase` — «24ч ноль Opportunities при активном observer» →
    событие `initiative_observer_diagnostic` (stage
    `diagnose:no_opportunities_24h`), не чаще 1/сутки (B01.4).
  - `_inherit_state` — рестарт наследует курсор/chats/день/счётчики
    предыдущего терминального прогона (прецедент `_inherit_cursor`).
- `observer_enabled` — K1 (`mca_gates.intents_enabled`) AND
  `flags.initiative_observer_enabled` (hot, fallback
  settings.INITIATIVE_OBSERVER_ENABLED, default ON).
- `chat_observer_enabled` — per-chat `initiative.enabled` (только группы,
  chat_id<0); `frequency_profile` — rare/normal/active + тонкие лимиты
  (min_gap/max_day/day_window/max_per_topic/eval_min_messages/eval_interval/
  eval_llm_budget) через generic-резолв `chat_params.get_chat_param` →
  `hot_config` → дефолт; 0 = «лимит выключен» для gap/interval (B01.4).
- no-spam: min gap по durable ledger bot-выходов, дневной лимит (скользящее
  окно), max replies per topic, дедуп контекста (хэш id-окон, TTL 12ч),
  worker_budget llm_calls global+chat, дневной бюджет LLM-оценок чата.
- Прямое обращение к боту в окне → skip `direct_address_seen` (не
  соревнуемся с Direct). Инъекции из чата не поднимаются в system
  (фиксированный system-промпт; текст — только user-role, bounded).

### B01 — `services/memory_maintenance.py`
- `JOB_INITIATIVE_OBSERVER_ID` + `_tick_initiative_observer` (тик 300с,
  регистрируется ВСЕГДА, gate читается на каждом тике — прецедент
  C06A-симметрии); DI writer_service/llm из DirectChatService-синглтона;
  status-штамп `_initiative_observer_last_tick` для Status UI-волны.
- `_tick_intent_heartbeat`: при недоступности writer-сервиса — явное событие
  `initiative_writer_unavailable` (stage `writer:unavailable`), не молчание
  (B01.5). Жизненный цикл Writer уже не зависит от Direct-trigger-gate
  (синглтон ставится безусловно; триггер-гейт — только на входящем пути).

### B02 — `services/mca_experience_jobs.py`
- Основной extractor — СЕМАНТИЧЕСКИЙ (B02.1): `_semantic_extract` +
  `_semantic_discover` (watermark) + `_semantic_window` (per-chat durable
  курсоры; справедливость: ≤4 чата × ≤10 строк за проход, ≈5.7k сообщений/
  сутки ёмкости ≥ 2k–5k; порядок «дольше всех без обработки — первым») +
  `_semantic_llm_batch` (ОДИН LLM-вызов на батч, `step="semantic_extract"`).
- Regex остаётся ТОЛЬКО фильтром структурного мусора (media/forward/command/
  empty) — сомнительное (шутка/спор/третье лицо) идёт в семантику; прежний
  детектор сохранён как дешёвый high-confidence hybrid-вход (D05).
- Типизированные кандидаты (B02.2): `parse_semantic_candidates` (whitelist
  8 kind, msg_ids, subject/author, confidence, ЭПИСТЕМИКА fact/opinion/
  humor/rumor/dispute) + `semantic_rejection` (слух/шутка/спор/мнение/
  low confidence никогда не истина) + `_write_semantic_candidate`:
  preference/style_request/dont_repeat → preference-сигнал (P3-урок,
  normalize_pref_token: известные формы + custom.<token>);
  correction/fact_user/strategy_failure → correction-сигнал (эпизод →
  P2 failure_pattern); strategy_success/topic_pattern → durable candidate
  `llm_hypothesis` (класс observation) — БЕЗ ложного успеха/урока.
- Дедуп: явная проверка dedup_key (`me._sha1_16(source, chat, ref_type,
  ref_id)`) до записи → `semantic_duplicates`, кандидат не плодится.
- Provenance: durable source IDs (`msg` + `msg_ids` в signal_json);
  preference-кандидаты связываются с сообщением существующим
  `_link_message_provenance`; X1-семантика курсоров (сдвиг только после
  durable обработки; LLM-сбой → курсор на месте, retry).
- Воронка (B02.3/DoD): counters `semantic_scanned/semantic_selected/
  semantic_extracted/semantic_candidates/semantic_rejected(+reasons)/
  semantic_duplicates/semantic_llm_unavailable` + события `semantic_extract`,
  `detector_signal` (stage `semantic:<kind>`); applied/outcomes —
  существующие `record_applications`/`link_application_outcome`.
- `tick_experience_review(db, llm=None)`, `ExperienceReviewRunner(db, llm)`
  — DI существующего клиента; LLM None → честный
  `semantic_llm_unavailable`, курсор стоит, детерминированный контур работает.
- `run_semantic_backfill(db, llm, start_rowid, end_rowid, max_batches)`
  (B02.3) — bounded backfill ТОЛЬКО явным вызовом (не расписание).
- Инъекции (B02.5): system-промпт — константа `SEMANTIC_SYSTEM_PROMPT`;
  текст чата только в user-role; kind whitelist не содержит
  personality/trait — «перепиши личность» кандидатом не становится; уроки —
  только серверный канон рекомендаций (свободный текст не попадает в
  рекомендации; traits-пайплайн не трогается).

### B02 — `services/memory_maintenance.py`
- `_tick_experience_review` резолвит существующий LLM-клиент
  (DirectChatService-синглтон) и передаёт в review-job.

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| B01.1 observer в существующем контуре, сигналы без вопроса/«бота», дедуп/thread/identity, диагностика видимости | VERIFIED тестами | `test_b01_fixture_without_botword_produces_opportunities` (120 реплик без «бота» → opportunity + отправка; llm.calls≤3 при observed≥100); cursor/dedup в payload; `initiative_observer_scan` |
| B01.2 ephemeral/durable intent/Direct request; НЕ LLM на каждую реплику; bounded evaluation с бюджетом и reason codes | VERIFIED тестами | `test_b01_variety_...` (horizon=later → durable intent origin=unfinished_topic); дневной бюджет оценок/worker_budget в коде; reason codes в `eval_skips`/stage |
| B01.3 Decision SAY/REACT/SILENT, адресат/тема; no-spam/cooldown; инъекции не управляют настройками | VERIFIED тестами | SAY→sent; REACT→`react_decisions`+`l1_react`; SILENT легален; `test_b01_negatives_...`/`test_b01_day_cap_and_min_gap...` (topic_cap/min_gap/day_cap отсекают); системные ключи читаются только из каталога/hot, чат-текст в гейты не попадает |
| B01.4 per-chat профиль редко/нормально/активно + тонкие лимиты (runtime); «24ч ноль Opportunities» = диагностическое событие; без гарантийной отправки по таймеру | VERIFIED тестами (runtime-механика) / PENDING-live (canary 24–48h) | `test_b01_frequency_profiles_and_thin_limits`; `test_b01_zero_opportunities_24h_is_diagnostic_event`; SILENT-пути в тестах; таймерной отправки нет (отправка только из evaluated opportunity) |
| B01.5 Независимость от Direct entrypoint; writer lifecycle отвязан; `initiative_writer_unavailable` вместо молчания | VERIFIED тестами | `test_b01_independent_of_direct_entrypoint_gate` (Direct master OFF → observer работает); `test_b01_writer_unavailable_is_explicit_not_silent` (событие + durable intent, не тишина); `test_b01_heartbeat_tick_writer_unavailable_event` |
| B01.6 Связь с памятью/характером без выдуманных «мыслей» | VERIFIED тестами (подсказки)/PENDING-live (качество речи) | `_memory_hints` → только проверенные уроки (серверный канон) в `<Memory_Hints>`; персона/характер — существующий L2 Writer-контур |
| B01 DoD fixture 100–300 / негативы / two-chat / reboots / chat OFF / воронка | VERIFIED тестами / PENDING-live (canary ≥1 SEND, мониторинг 7d) | `test_b01_two_chat_isolation`, `test_b01_reboot_keeps_cursor_and_context_dedup`, `test_b01_chat_off_cuts_proactive_path`, `test_b01_funnel_events_chain_with_reason_codes` (scan→opportunity→decided→writer_generated→sent) |
| B02.1 Regex только фильтр; семантический extractor батчами; разговорный русский; без требования обращения к боту | VERIFIED тестами | `test_b02_unpredictable_preference_multi_message_to_applied`, `test_b02_explicit_correction_unpredictable_becomes_lesson` (формулировки мимо всех regex детектора); батчи/курсоры в `_semantic_*` |
| B02.2 Типизированные кандидаты; само/чужое; слух/шутка не факт; отделение от factual memory/личности | VERIFIED тестами | 16 тестов: humor/rumor/opinion/dispute/low_confidence → reject; subject vs author; personality_rewrite → parse-drop; уроки только CANONICAL_RECOMMENDATIONS |
| B02.3 Cursor lag + покрытие 2k–5k/сутки; справедливые батчи; per-chat/master (не глобальный no-op); durable source IDs; dedup; bounded backfill | VERIFIED тестами (механика+ёмкость константами) / PENDING-live (прод-лаг) | `test_b02_chat_learning_off_skips_semantic_batch`; `test_b02_correction_after_restart_no_duplicates`; `test_b02_backfill_bounded_explicit_only`; ёмкость: 900с×4×10≈5.8k/сут в константах; lag — watermark/курсоры в payload |
| B02.4 Lifecycle candidate→review→validated→retrieved→applied→outcome→reinforce/suspend; противоречия/FP/устаревание; unknown не полезен | VERIFIED тестами (на существующем контуре) | `test_b02_unpredictable_...` полный E2E до counters_success==1; suspend по verified-contradiction/outcomes — существующие шаги (`_suspend_contradicted`, `link_application_outcome` unknown/weak не считаются), покрыты baseline-тестами mca16 |
| B02.5 Поправки сохраняют смысл/связь с сообщениями; инъекции не в system/developer; traits не переписываются фразой | VERIFIED тестами | `test_b02_injection_and_unknown_kind_rejected_system_fixed` (system==константа, инъекция только в user-role, kind drop); provenance msg_ids в signal; traits-пайплайн не затронут кодово |
| B02 DoD ≥10 сценариев E2E; счётчики воронки; honest «недостаточно данных» на проде | VERIFIED тестами (16 тестов, 12 смысловых сценариев) / PENDING-live (прод-метрики + 1 доказанный lesson) | см. список тестов ниже |

`PENDING-live` — только то, что по брифу/DoD требует canary/прода (24–48h
воронка, ≥1 SEND, прод-счётчики, мониторинг 7d) и выполняется владельцем
после деплоя; agent-часть (fixture/negatives/E2E) — VERIFIED.

## Тесты

- НОВЫЙ `tests/test_asap8_v63_b01_initiative_observer.py` — 13 тестов,
  TEST-LIFECYCLE: CONTRACT owner=REQ-B01.
- НОВЫЙ `tests/test_asap8_v63_b02_semantic_experience.py` — 16 тестов
  (12 смысловых сценариев), TEST-LIFECYCLE: CONTRACT owner=REQ-B02.

Прогоны (py -3 -m pytest, Windows):
- Новые: `tests/test_asap8_v63_b01... tests/test_asap8_v63_b02...` → **29 passed**.
- Смежные: d05_experience + f6_initiative + mca16_block_a + c06a_heartbeat +
  memory_maintenance + mca09_off_parity → **114 passed**;
  mca09_blocks A–E + direct_chat → **233 passed**. Регрессий нет.

## Патчи вне scope (для владельца)

1. `services/param_catalog.py` (владелец — другой лейн). Ключи читаются
   generic-механизмом уже сейчас; для UI-редактирования добавить в `_INTENT`
   (или отдельную группу `flags_initiative_observer`/`limits_initiative_observer`)
   по образцу существующих ParamSpec:

```python
ParamSpec("INITIATIVE_OBSERVER_ENABLED", "INITIATIVE_OBSERVER_ENABLED",
          CATEGORY_FLAGS, "Наблюдатель инициативы (обычный чат)", "bool",
          pg_id="flags.initiative_observer_enabled", group="flags_intent",
          description="ASAP8 v6.3 B01: observer opportunities в обычных "
                      "групповых чатах. Аварийный env: "
                      "INITIATIVE_OBSERVER_ENABLED."),
ParamSpec("INITIATIVE_ENABLED", "INITIATIVE_ENABLED",
          CATEGORY_FLAGS, "Инициатива в этом чате", "bool",
          pg_id="initiative.enabled", group="flags_intent",
          description="Per-chat гейт автономной инициативы (B01)."),
ParamSpec("INITIATIVE_FREQUENCY_PROFILE", "INITIATIVE_FREQUENCY_PROFILE",
          CATEGORY_LIMITS, "Профиль частоты инициативы", "str",
          pg_id="initiative.frequency_profile", group="limits_intent",
          description="rare | normal | active — базовые лимиты частоты "
                      "(B01.4); тонкие override'ы сильнее профиля."),
ParamSpec("INITIATIVE_MIN_GAP_SECONDS", "INITIATIVE_MIN_GAP_SECONDS",
          CATEGORY_LIMITS, "Мин. пауза между инициативами, с", "int",
          pg_id="initiative.min_gap_seconds", group="limits_intent",
          description="0 = без ограничения (бюджет остаётся)."),
ParamSpec("INITIATIVE_MAX_REPLIES_PER_DAY", "INITIATIVE_MAX_REPLIES_PER_DAY",
          CATEGORY_LIMITS, "Макс. инициатив в сутки", "int",
          pg_id="initiative.max_replies_per_day", group="limits_intent"),
ParamSpec("INITIATIVE_DAY_WINDOW_SECONDS", "INITIATIVE_DAY_WINDOW_SECONDS",
          CATEGORY_LIMITS, "Окно дневного лимита, с", "int",
          pg_id="initiative.day_window_seconds", group="limits_intent"),
ParamSpec("INITIATIVE_MAX_REPLIES_PER_TOPIC", "INITIATIVE_MAX_REPLIES_PER_TOPIC",
          CATEGORY_LIMITS, "Реплик на одну тему", "int",
          pg_id="initiative.max_replies_per_topic", group="limits_intent"),
ParamSpec("INITIATIVE_EVAL_MIN_MESSAGES", "INITIATIVE_EVAL_MIN_MESSAGES",
          CATEGORY_LIMITS, "Мин. сообщений для оценки", "int",
          pg_id="initiative.eval_min_messages", group="limits_intent"),
ParamSpec("INITIATIVE_EVAL_MIN_INTERVAL_SECONDS",
          "INITIATIVE_EVAL_MIN_INTERVAL_SECONDS",
          CATEGORY_LIMITS, "Мин. интервал оценок, с", "int",
          pg_id="initiative.eval_min_interval_seconds", group="limits_intent",
          description="0 = без ограничения (бюджет оценок остаётся)."),
ParamSpec("INITIATIVE_EVAL_LLM_BUDGET_PER_DAY",
          "INITIATIVE_EVAL_LLM_BUDGET_PER_DAY",
          CATEGORY_LIMITS, "LLM-оценок в сутки на чат", "int",
          pg_id="initiative.eval_llm_budget_per_day", group="limits_intent"),
```

2. `services/mca_events.py` (словарь REASON_CODES, расширение по §17.2 с
   санкцией): сейчас мои машинные коды переносятся в `stage`
   (`opportunity:<kind>:<action>`, `skip:<reason>`, `writer:unavailable`,
   `diagnose:no_opportunities_24h`, `semantic_extract`), т.к. reason_code
   строго валидируется словарём. Для UI-волны желательно добавить коды:
   `initiative_writer_unavailable`, `no_opportunities_24h`,
   `hearsay_or_joke`, `no_canonical_rule`, `semantic_parse_error`.

3. `config/settings.py`: опционально `INITIATIVE_OBSERVER_ENABLED = True`
   и `INITIATIVE_ENABLED = True` (чтение через getattr с default True уже
   работает без них — добавление только для симметрии с каталогом).

## UI-handoff (для UI-волны)

- Профиль частоты: per-chat ключи из патча №1; значения резолвятся
  без рестарта (`chat_params.overrides` → hot → дефолт). «редко/нормально/
  активно» = `initiative.frequency_profile` (rare/normal/active).
- Воронка для Status (chat-scoped, 24ч):
  - observed/eligible/skips: payload durable-job
    `task_jobs WHERE kind='initiative.observe'` (counters: observed,
    eligible, scan_skipped, eval_skips{...}, opportunities, sent,
    silent_decisions, react_decisions, intents_created, writer_unavailable,
    eval_unavailable, errors);
  - события `mca_events`: `initiative_observer_scan` (global),
    `initiative_opportunity` (stage `opportunity:<kind>:<action>` /
    `opportunity:none`), `initiative_decided`, `initiative_writer_generated`,
    `initiative_sent` (stage `observer:<kind>`), 
    `initiative_writer_unavailable`, `initiative_observer_diagnostic`
    (stage `diagnose:no_opportunities_24h`);
  - liveness-штамп: `services.memory_maintenance._initiative_observer_last_tick`
    (ts/status/observed/opportunities);
  - B02-воронка: counters review-job (`semantic_*`) + события
    `semantic_extract`, `detector_signal` (stage `semantic:<kind>`),
    `applied`, `retrieved`; лаг семантики = watermark/pending в payload
    review-job vs MAX(smart_messages.id).
  - Примечание: плечо recheck выполняется для всех инициативных отправок
    (SendRecheck), но отдельное событие `initiative_recheck_passed`
    в mca-09 пишется только при intent_id — ephemeral-кандидаты наблюдателя
    идут без него (существующий контракт mca_intents, не менял).

## Известные ограничения / реальные риски

- REACT доставляется как решение/реакция в decision-слое (delivery_kind
  initiative_react, reason `l1_react`); текстовой реакции (emoji) в
  инициативном контуре нет — существующий контракт mca-09 («react/tool без
  цели — честное молчание»), не расширял.
- Дедуп feedback-кандидатов — один durable-кандидат на
  (источник, чат, сообщение): два разных kind на одном сообщении схлопываются
  (existing record_feedback-контракт; учитывается счётчиком duplicates).
- `strategy_success/topic_pattern` не конвертируются в уроки (нет
  канонического правила в закрытом каталоге mca_experience) — фиксируются
  как durable `llm_hypothesis`-кандидаты; конверсия = отдельная санкция
  каталога (CANONICAL_RECOMMENDATIONS).
- Гарантированную частоту B01.4 («несколько содержательных реплик в сутки
  штатно») доказывает только canary 24–48h — механика (профили/лимиты/
  бюджеты) реализована и покрыта тестами, но живая частота зависит от
  качества LLM-оценок на проде.
- K2 (`experience_feedback_enabled`) OFF закрывает и семантическую запись
  кандидатов (record_feedback-гейт) — существующая политика.

## Изменённые/новые файлы (только этот лейн)

- НОВЫЙ `services/initiative_observer.py`
- `services/mca_experience_jobs.py` (+558 строк: semantic extractor,
  counters, backfill, DI llm)
- `services/memory_maintenance.py` (+89/−8: тик наблюдателя, writer-
  unavailable событие, llm-прокидывание)
- НОВЫЙ `tests/test_asap8_v63_b01_initiative_observer.py`
- НОВЫЙ `tests/test_asap8_v63_b02_semantic_experience.py`

Файлы вне лейна в рабочем дереве (cover_*/database.py/summary_memory.py/
chat_migration.py/b03|b04|b09-тесты и пр.) — работа других лейнов, мной не
трогались. Существующие тесты не изменялись (контракты не устарели).

@Orchestrator — на строгую независимую ревью.
