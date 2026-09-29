# tasks.md — `mca-asap3-direct-context-reply-reliability` (ASAP-3, P0 владельца)

**Эпик:** memory-context-autonomy (MCA), ASAP-трек. **Очередь:** строго после ASAP-2.1 (DONE, прод 2.58.34, HEAD `8a0fa6c`).
**Источник требований (единственный):** `plans/current_task.md`, блок «ASAP-3 / P0 — Direct Context Reliability + Autonomous Direct Decision Making», **строки 4062–6063 (§0–§62)** — прочитан полностью. Файл владельцем не менялся (R17/R18), PM-планирование содержимое не трогало.
**Нумерация:** **T-3999…T-4041 (43 задачи)**; T-3964…T-3998 заняты ASAP-2.1 (`plans/archive/mca-asap21-summary-quality-ui-cleanup-round1028/`).
**Версия:** 2.58.34 → **2.58.35** (bump по ASAP-конвенции; финальное подтверждение за @Architect).
**Базлайн:** прод 2.58.34; master kill-switch'и `DIRECT_COORDINATOR_ENABLED` (settings.py:552) и `DIRECT_DECISION_MAKING_ENABLED` (settings.py:560), default ON — REUSE; композер получит независимый env `DIRECT_CONTEXT_COMPOSER_ENABLED` — три независимых master (D-PM-1, spec §5.1); decision layer A7 round1026 — `CoordinatorDecision` reply/react/silent + `reason_code` 15 кодов (`services/direct_chat_service.py:722`, ARCHITECTURE.md §83); каталог F8 **481/422/456/105/103/21**.

## 0. Рамки и границы (§0, §59, §62)

- **НЕ перепроектировать (§0):** Summary L1 semantic graph / L2 storyteller / Hybrid / Legacy / MAX_SUMMARY_PARTS / article formatter / sendRichMessage; free-will/observer policy фона (§19C). Единственная допустимая связь с Summary — running summary как **consumer-side источник** контекста Direct Chat.
- **§93–§100 — смерженные слои MCA** (round 10.27, deploy DEFERRED_TO_RELEASE), НЕ «WIP-волны» (D-PM-5): REUSE **обязателен** — `mca_retrieval_context` (mca-07, вкл. episode-канал, `EvidenceBundle`), `thread_chain` (ADR-1023-2), канонический рендер яруса A, protected spans `_truncate_block`, `_estimate_external_payload_tokens`, `react_moai`/`_REACTION_BY_REASON` (A8), `emit_agentic_event` (A9, гейт `AGENTIC_EVENTS_ENABLED`), `get_running_summary`, `bot_replies`/`bot_reply_parents`. **Второй архив/движок истории запрещён** (§10); не-смерженные WIP-волны — вне скоупа (PM-Q4 закрыт ADR D14).
- **Workflow-гейт (§59):** Orchestrator не продолжает другие current_task-задачи до полного закрытия ASAP-3 (build → review → **PROD DEPLOY** → **LIVE ACCEPTANCE** → post-deploy → §61-отчёт). feature_status ≠ DONE до §58-гейта.
- **Статус плана:** `spec.md` (sha256 83E7B028…) + ADR-1028-2 (Accepted, D1–D17, sha256 77C2F12A…) готовы; PM-reconcile выполнен — все 8 расхождений §13 spec (D-PM-1…D-PM-8) закрыты в пользу spec, правки внесены в этот файл → handoff `PLANNING_CONSISTENT`.

---

## Группа A — аудит (read-only, до/параллельно с решениями @Architect)

- [x] **T-3999** [MECH] **Аудит §1: воспроизводимый разбор корня prod-инцидента (Context Truncation).**
  *Сделать:* подтвердить по текущему коду цепочку `resolve_context_tokens(-1)` → `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000` (settings.py:517) → `safe_budget()` / `TOKEN_SAFETY_MULTIPLIER=1.15` (settings.py:1641, token_counter.py:229-230) → ≈27826; воспроизвести расчётно prod-WARN `39371 -> 27826`; найти место эмиссии WARN в `direct_chat_service.py` (gcap/tcap :2234-2236, `_apply_context_budget` :2762).
  *Acceptance:* аудит-заметка в evidence с точными файлами/строками и числовым расчётом, совпадающим с §1. **(§1)**
  *Риски:* низкий; read-only.
  *Тест:* расчётная таблица + ссылка на прод-лог WARN.

- [x] **T-4000** [MECH] **Инвентарь ВСЕХ старых caps Direct Context (где режется: settings / коды / промпты / UI).**
  *Сделать:* полная таблица мест усечения: `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`, `TOKEN_SAFETY_MULTIPLIER`, `CHAT_THREAD_MAX_DEPTH=6` (settings.py:1304), per-chat `limits.chat_global_context_max_tokens/-thread/-context_budget`, внутренние caps `_apply_context_budget`/`_truncate_block`, aggregate-усечение; записи в `param_catalog.py` (TOKEN_SAFETY_MULTIPLIER :742, CHAT_THREAD_MAX_DEPTH :1275, limits_chat); упоминания лимитов в промптах и miniapp-описаниях. Классифицировать каждое: скрытый cap при -1 / явный admin override (>0) / soft target (§7).
  *Acceptance:* таблица «место → ключ → семантика сегодня → целевая семантика по §7 → [удалить/изменить/оставить]»; ничего не пропущено (проверка grep-ом по всем `truncat|cap|ceil|budget` в direct-пути). **(§2, §3, §5, §6, §7)**
  *Риски:* пропуск неочевидного cap → живучесть «fake unlimited» (§52.A).
  *Тест:* чек-лист инвентаря (основа для Reviewer-проверки §52.A/B).

- [x] **T-4001** [MECH] **Аудит текущей семантики decision layer (A7) и триггеров адресации.**
  *Сделать:* карта «trigger → путь кода → возможные исходы»: где сегодня детектируется force-keyword («бот,» + configured aliases), где reply_to_bot; полный список `reason_code` (REASON_CODES, A8-карта reason_code→action :612) и программных шорт-катов (recent_reply, ignore_trivial, low_information); места, где `reply_to_bot` смешивается с `bot_replied_recently` (§23); текущее обращение с REACT/SILENT.
  *Acceptance:* карта с файлами/строками; явный список расхождений с §19–§29 (что уже соответствует, что нет). **(§18, §19, §20, §22, §23, §27, §29)**
  *Риски:* низкий.
  *Тест:* раздел аудита в evidence; вход для T-4018…T-4025.

- [x] **T-4002** [MECH] **Аудит интеграции running summary в Direct Chat сегодня.**
  *Сделать:* где/как summary подмешивается в direct-контекст (smoke-источник доступен после ASAP-2.1 §43); схема `running summary + messages > summary.window_end_ts`; что происходит при stale watermark (сотни raw сообщений → head/keep-tail truncation — подтвердить код); доступность raw messages DB / message_id / reply_to_id / timestamps / author / существующего semantic retrieval и thread_chain (вход для episode retrieval).
  *Acceptance:* схема текущего контекст-пайплайна Direct Chat с точками перерезания + перечень переиспользуемых источников (без второго архива истории, §10). **(§9, §13, §14, §10)**
  *Риски:* низкий.
  *Тест:* схема + grep-доказательства.

- [ ] **T-4003** [MECH] **Prod-log research ДО изменений (§45).** *(BLOCKED для Builder: прод-логи недоступны из dev-среды — рецепт grep-команд передан в evidence.md §T-4003, собирается DevOps в preflight T-4038 до деплоя 2.58.35.)*
  *Сделать:* по доступным production logs посчитать базлайн: warnings `global context truncated` / `thread truncated`; decision-события `reason=recent_reply`, `action=silent`, `action=react`, `MESSAGE_IGNORED`; фактическое распределение force keyword / reply_to_bot / silent / react / reply. Отсутствие ERROR/WARNING не считать признаком текстового ответа (§45).
  *Acceptance:* отчёт с числами за фиксированный период — база сравнения для §57 post-deploy. **(§45, §57)**
  *Риски:* логи могут быть неполны (retention) — зафиксировать период и ограничения.
  *Тест:* отчёт в evidence.

---

## Группа B — архитектура (@Architect: spec + ADR; §49 Q1–Q10)

- [x] **T-4004** [ARCH] **spec+ADR: Context Composer (§49 Q1–Q7).**
  *Сделать:* `spec.md` + ADR по: Q1 источник physical context-window per-model (карта/конфиг/env; поведение при неизвестной модели); Q2 формула full payload budget (model_window − system − personality − tool schemas − metadata − output reserve − tokenizer uncertainty; повторный safety multiplier НЕ применять, §4); Q3 единый composer для Dynamic/Unlimited (разница — только наличие user/project artificial cap, §5); Q4 определение relevant old episode и его boundaries (детерминированный/explainable алгоритм: reply graph / temporal / participants / semantic-topic continuity, §11); Q5 поведение при stale running summary (§14); Q6 гарантия fresh verbatim tail (minimum/target от available budget, §12); Q7 long reply chain > CHAT_THREAD_MAX_DEPTH (dynamic expansion / episode retrieval / configurable depth, §15). Обязательные контракты: priority model P0–P3 (§8), физический overflow (§17), семантика настроек -1/0/>0 (§7), перечень удаляемых/изменяемых caps из T-4000.
  *Acceptance:* ADR Accepted с прямыми ответами Q1–Q7; контракты достаточны для Builder без чтения current_task; санкция Δ каталога/DDL (ожидаем Δ DDL=0). **(§4, §5, §6, §7, §8, §9, §10, §11, §12, §14, §15, §16, §17; §49)**
  *Риски:* спекулятивный over-design запрещён самим ТЗ (§49) — spec точный, но не копия current_task.
  *Тест:* приёмки — SC-блок spec (направить в Group G).

- [x] **T-4005** [ARCH] **spec+ADR: Decision Making (§49 Q8–Q9).**
  *Сделать:* Q8 точная trigger priority: FORCE DIRECT (force_keyword → гарантированный ACTION_REPLY, исключения только техническая невозможность/safety) → DIRECT AUTONOMOUS (reply_to_bot → Decision Making REPLY/REACT/SILENT) → BACKGROUND (существующий free-will, не трогать) (§19, §29); явная модель полей `trigger_type` / `force_reply_required` / `reply_to_bot` вместо одного boolean (§20); Q9 контракт REACT и SILENT+🗿 в contract/metrics: REACT = полноценный outcome с выбором реакции (message class / emotion / personality / tone, без одной hardcode-реакции, §24, §36), SILENT+🗿 = отдельное состояние, только direct autonomous + decision executed + final SILENT (§25–§27), ack failure semantics (§28); контракты CoordinatorDecision (A7) — только аддитивно: поля `trigger_type`/`force_reply_required` + аддитивный код `force_direct` в REASON_CODES (15→16; существующие 15 кодов не переименовываются); master-флаги `DIRECT_COORDINATOR_ENABLED` (settings.py:552) и `DIRECT_DECISION_MAKING_ENABLED` (settings.py:560) работают как прежде (D-PM-1); `bot_replied_recently` — независимый сигнал (окно env `CHAT_BOT_REPLIED_RECENTLY_SECONDS`, default 600 — D-PM-8), не отменяет force (§23).
  *Acceptance:* ADR Accepted: ответы Q8–Q9 + расширенный словарь reason_code + матрица «trigger × исход» + подтверждение, что force не может закончиться SILENT/REACT (§52.F). **(§18–§29, §36; §49)**
  *Риски:* смешение ack с SILENT-статистикой (§27) — контракт обязан различать outcomes.
  *Тест:* приёмки — SC-блок spec.

- [x] **T-4006** [ARCH] **spec+ADR: флаги/rollback, observability-контракт, miniapp-контракт (§49 Q10).**
  *Сделать:* Q10 флаги/rollback — финальный реестр (spec §5.1, ADR D10): ровно 2 новых env ClassVar — `DIRECT_CONTEXT_COMPOSER_ENABLED` (default ON; имя — проектная конвенция SCREAMING_SNAKE, D-PM-2; OFF → прежний direct behavior байт-в-байт, без новых событий/счётчиков) и `DIRECT_SILENT_ACK_ENABLED` (default ON; OFF → тишина без 🗿) — плюс 2 новых per-chat ключа: `flags.chat_silent_ack_enabled` (env-дефолт от env-флага) и `flags.chat_autonomous_reply_enabled` (default ON); реакции — РЕЮС существующих `flags.chat_decision_reactions_enabled`/`CHAT_DECISION_REACTIONS_ENABLED` (не дублировать); force-toggle НЕ вводится (force keywords — read-only display, D-PM-4); env `CHAT_BOT_REPLIED_RECENTLY_SECONDS` (default 600, D-PM-8) и `CHAT_MODEL_CONTEXT_WINDOW`/`CHAT_UNKNOWN_MODEL_WINDOW` (default 16384) — ClassVar, Δ каталога = 0; observability-контракт — финальный реестр (spec §5.2/§5.3, ADR D15): +7 событий аддитивно к закрытому enum A9 — `DIRECT_TRIGGER` / `DIRECT_SILENT_ACK` / `DIRECT_SILENT_ACK_FAILED` / `CONTEXT_CAPACITY` / `CONTEXT_SELECT` / `CONTEXT_PRESSURE` / `CONTEXT_PHYSICAL_OVERFLOW` — через РЕЮС `emit_agentic_event` (гейт `AGENTIC_EVENTS_ENABLED`); РЕЮС `DECISION_START`/`DECISION_COMPLETE` (аддитивные поля trigger_type/force_reply_required/message_class)/`MESSAGE_IGNORED`/`REACTION_SENT`; summary-поля `summary_revision/watermark/lag_messages/age/unsummarized_tail_*` (§33); 9 счётчиков с финальными именами spec §5.3 (нормализация опечатки §46 — D-PM-3; механика `get_process_accounting()` + grep-able строка `direct_metric name=… count=…`; R17-safe, без raw user text/content); miniapp-контракт (ADR D17): Context Mode [Dynamic]/[Unlimited] в существующей карточке `limits_chat` (param_catalog.py:251), секция DIRECT ADDRESSING / DECISION MAKING в существующей группе `flags_decision_making` («Принятие решений», param_catalog.py:369) — force keywords read-only + ровно 3 тумблера defaults ON (§35, D-PM-4), диагностические поля без private raw messages; **санкция каталога (ADR D12): +2 ключа в существующую группу «Принятие решений», +0 групп, +0 вкладок → F8 481/422/456/105/103/21 → 482/423/457/105/103/21**, переиздание F8 атомарно с коммитом (прецедент ADR-1026-2), `test_param_catalog.py` (assert 422) обновляется; план §53 browser verification.
  *Acceptance:* ADR-1028-2 Accepted (D10/D15/D17): финальный перечень флагов + семантика OFF; события/поля/счётчики — финальные имена (9 счётчиков spec §5.3); miniapp-схема; санкция каталога: F8 → **482/423/457/105/103/21** (+2 ключа `flags.chat_autonomous_reply_enabled`, `flags.chat_silent_ack_enabled` в существующую группу «Принятие решений»; +0 групп/вкладок). **(§30, §31, §32, §33, §34, §35, §46, §47, §53; §49 Q10)**
  *Риски:* лишние флаги усложняют rollback-матрицу — минимизировать по §47.
  *Тест:* приёмки — SC-блок spec.

---

## Группа C — реализация: Direct Context composer [после T-4004]

- [x] **T-4007** [MECH] **Model-aware capacity: расчёт full payload budget (§4).**
  *Сделать:* новый нейтральный модуль `services/model_capacity.py` (consumer-side Direct; Summary НЕ импортирует — ADR D1/D11): `resolve_model_context_window(model_name) → (window, window_source ∈ {model_map, env_override, unknown_fallback})`; карта известных моделей + env `CHAT_MODEL_CONTEXT_WINDOW` (override, приоритет выше карты) + `CHAT_UNKNOWN_MODEL_WINDOW` (default 16384, консервативный fallback для неизвестной модели + однократный WARN — не «тихий скрытый cap»: источник решения логируется); для LLM-fallback-модели — min(primary, fallback). Формула (ADR D2): `external = _estimate_external_payload_tokens(chat_id)` (РЕЮС mca-07); `output_reserve = max(1024, int(window × limits.chat_budget_reserve_ratio))` (РЕЮС hot-ключ, default 0.10); `available = safe_budget(window − external − output_reserve)` — **TOKEN_SAFETY_MULTIPLIER (1.15) применяется РОВНО ОДИН РАЗ** на весь расчёт (это и есть tokenizer uncertainty reserve §4; повторно нигде); `budget = policy(available, limits.chat_context_budget_tokens)`: -1 → available (Unlimited), 0/None → min(available, 16000) (Dynamic, дефолт), >0 → min(available, cap). Fail-open: ошибка оценки → external=0, method=unknown, фиксация в `CONTEXT_CAPACITY` (ответ не блокируется).
  *Acceptance:* unit-тесты формулы; window_source фиксируется в `CONTEXT_CAPACITY`; при росте system/tools/personality available автоматически уменьшается (§37 TEST 4); рост окна модели → Unlimited больше без правки констант (TEST 5); ровно одно применение множителя — проверка тестом. **(§4)**
  *Риски:* неверное окно модели → недо/переоценка бюджета (mitigation: консервативный reserve + CONTEXT_CAPACITY лог).
  *Тест:* `tests/test_direct_context_capacity_*.py` (новый).

- [x] **T-4008** [MECH] **Семантика -1 / 0 / >0 без скрытого cap (§2, §7).**
  *Сделать:* семантика на direct ON-пути — граница consumer-side (ADR D11): `services/token_counter.py` НЕ меняется вовсе; `resolve_context_tokens`/`safe_budget`/`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` сохраняют семантику ADR-1019-8 для Summary и всех не-direct потребителей (композер на ON-пути НЕ вызывает `resolve_context_tokens` для -1 — sentinel разбирается политикой T-4007/D2). `-1` = no artificial project cap (весь available из T-4007); `0` = inherit/dynamic default (дефолт 16000); `>0` = explicit user/admin cap; physical model window — всегда верхняя граница; backend и miniapp — одинаковая семантика (Context Mode = derive от `limits.chat_context_budget_tokens`, ADR D12). Legacy-тесты Summary/token_counter НЕ трогаются; обновляются только direct-тесты (в T-4031).
  *Acceptance:* §37 TEST 1/2 (39k global и 35k thread при -1 не режутся к 27826/32000 при достаточном окне); §37 TEST 5 (рост окна модели → Unlimited автоматически больше без правки констант). **(§2, §7)**
  *Риски:* **общая точка с Summary** (`resolve_context_tokens` используют summary-генератор и его тесты) — границу изменения определяет @Architect (PM-Q1); регресс Summary недопустим (§0).
  *Тест:* обновлённые + новые unit; регресс summary-тестов зелёный.

- [x] **T-4009** [MECH] **Единый composer Dynamic/Unlimited, устранение двойного независимого truncation (§5, §6).**
  *Сделать:* единый композер `services/direct_context_composer.py` (ADR D3), конвейер spec §3.3: собрать candidates существующими билдерами (global/thread при ON — в режиме «без self-усечения», без WARN `truncated`) → классифицировать приоритет (T-4010) → посчитать фактический full payload → получить available (T-4007) → распределить (eviction P3→P2→P1) → materialize (порядок блоков в payload НЕ меняется); убрать сценарий «Global режется своим cap → Thread отдельно своим → aggregate ещё раз»; adaptive accounting работает и при Unlimited (§5 — устранение раннего return `:2802-2811`); rigid ratio-доли `chat_budget_*_ratio` на ON-пути не применяются (место — по фактическим потребностям кандидатов; empty-секции не съедают бюджет; «всё влезает — не режем» §16); per-block `limits.chat_global_context_max_tokens`/`chat_thread_max_tokens`: >0 — явный admin hard-cap (min с распределением), -1 — без капа, 0 — inherit (дефолты 5000/3000 — soft-target классификации P2/P1); никаких скрытых caps при -1.
  *Acceptance:* интеграционные тесты: ровно одна точка распределения бюджета; при -1/-1/-1 accounting выполняется (§37 TEST 3); WARN «truncated» при -1 отсутствует. **(§5, §6)**
  *Риски:* регресс существующих per-chat admin caps (>0) — сохранить поведение.
  *Тест:* `tests/test_direct_context_composer_*.py` (новый) + регресс `test_direct_chat.py`.

- [x] **T-4010** [MECH] **Priority model P0–P3 + eviction и перераспределение бюджета (§8, §16).**
  *Сделать:* явная priority-разметка: P0 (current message; сообщение, на которое отвечают; reply-chain; Target_User/attribution; старый exact dialogue, релевантный запросу; protected mandatory facts), P1 (recent verbatim tail; strong old episodes; нужные relations), P2 (running summary; broad background; RAG facts; conversation map), P3 (слабый фон; redundant facts; style/context duplicates; уже представленная информация); eviction строго P3→P2→P1; **P0 обычный budgeter молча не удаляет** (при невозможности — путь §17); Dynamic без rigid ratio (Global=30%…): unused budget перераспределяется, пустые секции не съедают бюджет; «всё помещается — не резать из-за ratio». Сквозная карта уровней §12 → классы P0–P3 (spec §3.4, D-PM-7): уровни 1–2 + релевантный old episode → P0; уровни 3–4 (fresh tail, thread) → P1; уровни 5–6 (summary, global/RAG/nostalgia) → P2; шум/дубликаты → P3. Eviction внутри блока — существующими механиками (`trim_verbatim_lines` с importance-удержанием, `_truncate_block` с protected spans), без `text[:N]`; каждое решение → `CONTEXT_SELECT`.
  *Acceptance:* тесты eviction-порядка; P0 не удаляется при обычном pressure; irrelevant middle сокращается раньше P0/P1 (§38). **(§8, §16)**
  *Риски:* misclassification приоритетов — детерминированные правила + лог CONTEXT_SELECT.
  *Тест:* `tests/test_direct_context_priority_*.py`.

- [x] **T-4011** [MECH] **Old verbatim episode retrieval: hit → coherent dialogue episode (§9, §10, §11).**
  *Сделать:* реализация по ADR D4: вход = retrieval-хит единого контракта `mca_retrieval_context` в режиме `mode="history"` (каналы exact/lexical/vector/episode — смерженный mca-07, REUSE обязателен, D-PM-5); границы эпизода — детерминированная чистая функция БЕЗ LLM (0 LLM-вызовов, идемпотентная): (1) расширение назад/вперёд по (chat_id, timestamp ASC), пока межсообщенный gap ≤ `CHAT_EPISODE_GAP_SECONDS` (env, default 300; участники span — приоритет чтения, не фильтр) → (2) reply-graph closure по `thread_chain` (предки/потомки по reply_to, depth cap 6, cycle-safe) → (3) склейка непрерывного [start..end] по message_id («дырки» > gap → split, берётся эпизод, содержащий хит) → (4) caps `CHAT_EPISODE_MAX_MESSAGES` (env, default 40) и `CHAT_EPISODE_MAX_COUNT` (env, default 2 на run) → (5) дедуп vs fresh tail (пересечение → клип до tail_start) → (6) рендер каноническими строками яруса A (`_context_row_line`) в блок `<Old_Episode>`, класс P0. Идемпотентность: те же данные+константы → тот же span; повторный хит в уже выбранном эпизоде не дублирует блок. Explainability: лог/событие hit_id → span(start,end) → причина (gap_steps/reply_links/cap_applied) + счётчик `direct_old_episode_retrieval_total`. Источники — только существующие: `smart_messages` (tg_message_id, timestamp, user_id, text — raw source of truth), `bot_replies`/`bot_reply_parents`, `thread_chain`; **второй архив/движок запрещён** (§10), Δ DDL = 0, никаких destructive миграций raw history (§9: raw = source of truth, summary/RAG/facts = derived).
  *Acceptance:* fixture §38 (500 сообщений, запрос к разговору ~200 назад, 20–40 сообщений): episode попадает verbatim, recent остаётся verbatim, summary как background, exact wording доступен модели. **(§9, §10, §11, §38)**
  *Риски:* High — качество границ эпизода; SLO объяснимости (лог: hit_id → span → причина).
  *Тест:* `tests/test_direct_episode_retrieval_*.py`.

- [x] **T-4012** [MECH] **Recent context всегда verbatim (§12).**
  *Сделать:* свежий разговор сохраняется дословно; не заменять recent на running summary ради экономии; никакого одного магического N независимо от модели/payload — target = весь остаток available после P0, фактический размер фиксируется в `CONTEXT_SELECT`; гарантия минимума (ADR D6): `CHAT_FRESH_TAIL_MIN_MESSAGES` (env, default **20**) — P1-пол, tail не режется ниже минимума, пока не исчерпаны P2/P3; ниже — только путём §17 (сначала полное снятие P2, потом episodes); P2 (summary) не может вытеснить P1 (tail). Порядок приоритета §12 (current → reply thread → recent verbatim → old episodes → compressed background → secondary) — в классах P0–P3 по карте spec §3.4 (D-PM-7).
  *Acceptance:* тест: recent tail не замещается summary при любом режиме; размер tail масштабируется с бюджетом (§37 TEST 4/5). **(§12)**
  *Риски:* низкий.
  *Тест:* в composer-тестах T-4009/T-4010.

- [x] **T-4013** [MECH] **Running summary = сжатый фон: финальная композиция consumer-side (§13).**
  *Сделать:* заменить схему «summary + все messages > watermark → ножницы» на композицию §13: running summary (background) + relevant old verbatim episodes (T-4011) + relevant unsummarized middle episodes (importance-aware bounded selection: top-K ≤ `CHAT_MIDDLE_MAX_MESSAGES`, env, default 60 — spec §3.7; / episode extraction) + fresh verbatim tail (T-4012); только consumer-side семантика Direct Chat — Summary pipeline (L1/L2/Hybrid/watermark writer) не меняется (§0).
  *Acceptance:* интеграционный тест композиции на моках summary-слоя; §38 expectations полностью; Summary-регресс зелёный. **(§13, §0)**
  *Риски:* Medium — зависимость от качества unsummarized-middle selection; border с Summary pipeline — только чтение.
  *Тест:* `tests/test_direct_context_composition_*.py`.

- [x] **T-4014** [MECH] **Stale running summary не ломает Direct Chat (§14).**
  *Сделать:* composer самостоятельно справляется со stale watermark (timeout / provider problem / queue lag / long activity / worker running); direct-ответ не ждёт background summary job; не допускать «summary + 400 raw messages → head/keep-tail truncation».
  *Acceptance:* §39: lag 50/100/300/400 сообщений — Direct работает, композиция = summary + selected important middle + old episodes + fresh tail (без brutal truncation). **(§14, §39)**
  *Риски:* Medium — рост работы композера при большом lag; bounded selection.
  *Тест:* параметризованный тест lag в T-4032.

- [x] **T-4015** [MECH] **Thread depth: важный тезис глубже CHAT_THREAD_MAX_DEPTH доступен (§15).**
  *Сделать:* решение ADR (Q7/D7): dynamic thread expansion и/или retrieved dialogue episode и/или configurable max-depth; `CHAT_THREAD_MAX_DEPTH` (default 6) остаётся отдельным knob'ом от token budget; при composer ON — `thread_chain.collect_thread_chain` идёт до корня с hard-cap `CHAT_THREAD_WALK_MAX` (env, default 40, cycle-safe), рендерится столько ходов, сколько влезает в P1-бюджет (keep-end); per-chat `limits.chat_thread_max_depth` (>0) = минимальная гарантия глубины рендера: min(guaranteed_depth, budget-capable); acceptance-сценарий >6 hops обязателен.
  *Acceptance:* §40: reply-chain >6 hops, критический тезис глубже дефолта — Direct Chat получает его через expansion/episode retrieval. **(§15, §40)**
  *Риски:* раздутие контекста глубокими цепочками — приоритизация через T-4010.
  *Тест:* `tests/test_direct_thread_depth_*.py`.

- [x] **T-4016** [MECH] **Physical overflow: явная degradation без silent text[:N] (§17).**
  *Сделать:* если P0 + fresh-tail-минимум > available даже после снятия P2/P3 и episodes (spec §3.9) — без silent обрезки: preserve current turn / replied message / `<Current_Question>` / `<Target_User>` / protected facts / essential episode (компактнейшая из релевантных ветвей); secondary — hierarchical reduction (branch→thread→episode шагами, с protected spans); дополнительный LLM compression call НЕ вводить (без отдельного архитектурного обоснования); событие `CONTEXT_PHYSICAL_OVERFLOW` + счётчик `direct_context_physical_overflow_total`; никакого `text[:N]`.
  *Acceptance:* тест overflow-сценария: P0-сохранение + событие CONTEXT_PHYSICAL_OVERFLOW; отсутствие text[:N]-пути. **(§17, §32)**
  *Риски:* редко, но критично — обязательный тест.
  *Тест:* `tests/test_direct_context_overflow_*.py`.

- [x] **T-4017** [MECH] **Врезка composer в Direct Chat за kill-switch `DIRECT_CONTEXT_COMPOSER_ENABLED`.**
  *Сделать:* интеграция нового composer в direct-путь (replace `_apply_context_budget`-цепочки из T-4000) за главный env-флаг §5.1 (финальное имя — проектная конвенция SCREAMING_SNAKE, D-PM-2); OFF → прежний Direct behavior байт-в-байт (паритет входа/выхода, прецедент S1/S5); wire в observability (T-4027); parity-тесты покрывают комбинации трёх независимых master-флагов (координатор / decision / composer — D-PM-1).
  *Acceptance:* dual-mode тесты: OFF — старое поведение (fixture-сравнение), ON — новое; kill-switch возвращает прежний WARN-путь; комбинации трёх master-флагов проверены. **(§47, §51)**
  *Риски:* дрейф OFF-режима — обязательный parity-тест.
  *Тест:* `tests/test_direct_context_flag_*.py`.

---

## Группа D — реализация: Direct Decision Making [после T-4005]

- [x] **T-4018** [MECH] **Trigger model: явные поля адресации вместо одного boolean (§20, §23).**
  *Сделать:* поля `trigger_type` (force_keyword / reply_to_bot / mention / persona_name / free_will), `force_reply_required: bool`, `reply_to_bot: bool` — аддитивно к `DecisionContext`; правило: force → ACTION_REPLY всегда (приоритет 1); reply_to_bot ∧ ¬force → Decision Making; `reply_to_bot` ≠ `bot_replied_recently` — отдельные признаки (фикс `direct_chat_service.py:1233`): второй вычисляется независимо по окну env `CHAT_BOT_REPLIED_RECENTLY_SECONDS` (ClassVar, default **600с**, Δ каталога = 0 — D-PM-8) по `bot_replies`/history и не отменяет force (§23).
  *Acceptance:* unit-тесты классификации триггеров; регресс: фон (free_will) классифицируется как раньше. **(§20, §23)**
  *Риски:* Medium — касание hotspot классификации сообщений; изоляция в новых полях.
  *Тест:* `tests/test_direct_trigger_model_*.py`.

- [x] **T-4019** [MECH] **FORCE DIRECT: «бот, …» = гарантированный REPLY (§19A, §21).**
  *Сделать:* configured force-keywords («бот,» / «бот» + существующие aliases) → USER EXPLICITLY REQUIRES A TEXT RESPONSE → ACTION_REPLY обязателен; force-гейт — приоритет 1 матрицы (ADR D8/spec §4.1), ставится до всех программных шорт-катов `_decision_pre_action` и до LLM; аддитивный reason-код `force_direct` (REASON_CODES 15→16); `ignore_trivial` не может превратить триггер в silent; `recent_reply` не отменяет; `low_information` не отменяет; Decision Maker может задавать только стиль/краткость/тон («бот, ты тут?» — короткий ответ, но ответ); исключения — только техническая невозможность (CB OPEN → фраза; NoApiKey → sandbox-фраза; empty/LLMError → существующие ветки) / safety/system prohibition; существующий `_BOTWORD_EXCLUDED_USER_IDS` (alan/kostik keyword-ветка) сохраняется без изменений.
  *Acceptance:* §41: «бот, почему?» / «бот, ты тут?» / «бот, ок» / reply_to_bot «бот, нет, ответь нормально» → REPLY всегда; ignore_trivial не отменяет. **(§19, §21, §41)**
  *Риски:* High — существующие шорт-каты могут перехватить force (найдено в T-4001) — гейт до всех шорт-катов.
  *Тест:* `tests/test_direct_force_reply_*.py`.

- [x] **T-4020** [MECH] **Direct Autonomous: reply на бота остаётся автономным (§19B, §22).**
  *Сделать:* Telegram reply на сообщение бота = «адресовано боту», но НЕ «обязан ответить текстом»; проходит Decision Making с допустимыми REPLY / REACT / SILENT; examples §22 («ну тут ты по-моему неправ» → REPLY/SILENT; «ахах» → предпочтительно REACT; «ок» → REACT или SILENT).
  *Acceptance:* §42: содержательный reply проходит Decision Making; «ахах» предпочтительно REACT; «ок» — REACT или SILENT+🗿; reply ≠ guaranteed text. **(§19, §22, §42)**
  *Риски:* Medium — недочувствительность/перевозбудимость decision; контракты reason_code обязательны.
  *Тест:* `tests/test_direct_autonomous_*.py`.

- [x] **T-4021** [MECH] **Background без изменений: free-will не трогаем (§19C).**
  *Сделать:* сообщения, не являющиеся force/autonomous, работают по существующей observer/free-will policy; никакой реструктуризации фона; регресс-гейт отсутствия изменений в фоне.
  *Acceptance:* §43: «ахах» между пользователями — бот не обязан реагировать; отсутствие обязательного 🗿 на фоне; reaction-spam тест. **(§19, §43)**
  *Риски:* низкий (инвариант «не трогать»).
  *Тест:* регресс существующих free-will тестов + anti-spam тест.

- [x] **T-4022** [MECH] **ACTION_REACT — полноценный outcome (§24, §36).**
  *Сделать:* активное использование реакций как содержательного ответа; выбор реакции по message class / emotion / personality / conversation tone («ахах» → 😂/🤣; «понял» → 👍/👌; «красавчик» → 👍/🔥/❤️; сомнительная реплика → 🤨); без одной hardcode-реакции; ACK/LAUGHTER/EMOJI могут → REACT, не принуждать к SILENT+🗿. Механика A8 без изменений (РЕЮС, ADR D9): аддитивное расширение карты `_REACTION_BY_REASON` — наборы {😂,🤣} laughter / {👍,👌} ack-emoji / {👍,🔥,❤️} похвала / {🤨,🤔} сомнение; выбор из набора — стабильный hash от message_id (детерминированный, без LLM и без рандома); только standard Telegram reaction enum (ограничение A8 сохраняется); per-chat тумблер — существующий `flags.chat_decision_reactions_enabled` (default ON, РЕЮС).
  *Acceptance:* тесты выбора реакции по классу сообщения; отсутствие единственного hardcode-варианта; §42 preference-кейсы. **(§24, §36, §42)**
  *Риски:* Telegram reaction enum ограничения — использовать доступные setMessageReaction коды.
  *Тест:* `tests/test_direct_react_selection_*.py`.

- [x] **T-4023** [MECH] **SILENT + 🗿: только intentional direct silence (§25, §26, §27).**
  *Сделать:* 🗿 на исходное сообщение строго при конъюнкции (spec §4.2 / ADR D9): `trigger_type=reply_to_bot` ∧ `context.addressed` ∧ decision executed ∧ финал `ACTION_SILENT`; гейты: env `DIRECT_SILENT_ACK_ENABLED` (ClassVar, default ON) + per-chat `flags.chat_silent_ack_enabled` (default ON; env-дефолт от env-флага), OFF → сегодняшняя тишина (паритет); НЕ ставить на background chatter / free-will / not_addressed-silent / не-боту / технически потерянные (cooldown/CB/exception-ветки до decision) / rate-limit-drop; force + пустой LLM-ответ → существующий технический 🗿-путь (в `direct_silent_ack_*` НЕ считается, фиксируется как force outcome=failure); вместо нормальной contextual reaction 🗿 не подставлять; REACT и SILENT+🗿 — разные outcomes в коде, событиях и счётчиках.
  *Acceptance:* матричный тест «когда 🗿 ставится / не ставится» (все запреты §26); статистика разделяет react/silent_ack. **(§25, §26, §27, §43)**
  *Риски:* High — спам истуканами при ошибке классификации; жёсткий гейт + счётчики §46.
  *Тест:* `tests/test_direct_silent_ack_*.py`.

- [x] **T-4024** [MECH] **Reaction failure API: fail-soft (§28).**
  *Сделать:* падение Telegram reaction API: SILENT остаётся SILENT (не превращать в REPLY); REACT-failure не генерирует текст, если policy не требует; лог `DIRECT_SILENT_ACK_FAILED` (+аналог для REACT).
  *Acceptance:* §44: SILENT остаётся SILENT; лог DIRECT_SILENT_ACK_FAILED; случайный text reply не генерируется; то же для REACT. **(§28, §44)**
  *Риски:* низкий.
  *Тест:* мок падения API.

- [x] **T-4025** [MECH] **Интеграция decision matrix с CoordinatorDecision (A7) без нарушения контрактов (§18, §29).**
  *Сделать:* расширение существующего decision layer (`CoordinatorDecision`, reason_code-словарь, A8-карта reason_code→action) — только аддитивно: новые trigger-поля (`trigger_type`, `force_reply_required`) и force-гейт приоритета 1 (T-4019) до программных шорт-катов/LLM; аддитивный reason-код `force_direct` (REASON_CODES 15→16; существующие 15 кодов не переименовываются/не удаляются, потребители не ломаются); приоритетная цепочка §29 (FORCE → AUTONOMOUS → BACKGROUND; после решения: REPLY → generate/send; REACT → contextual reaction; SILENT+direct → 🗿 ack; SILENT+background → nothing); master-флаги `DIRECT_COORDINATOR_ENABLED` (settings.py:552) и `DIRECT_DECISION_MAKING_ENABLED` (settings.py:560) работают как прежде, composer — независимый `DIRECT_CONTEXT_COMPOSER_ENABLED` (три независимых master — D-PM-1; parity-тесты комбинаций в T-4017); decision layer сам по себе не бага (§18) — доработка адресации, не переписывание.
  *Acceptance:* интеграционные тесты полной цепочки §29; контракты A7 (reason_code/логирование/kill-switch) сохранены (15 существующих кодов не меняются); ответ на force никогда не silent/react (§52.F/G). **(§18, §29, §51)**
  *Риски:* Medium — расширение контракта ломает существующих потребителей reason_code; только аддитивные коды.
  *Тест:* `tests/test_direct_decision_integration_*.py` + регресс A7-тестов.

---

## Группа E — реализация: observability [после T-4006]

- [x] **T-4026** [MECH] **Decision-side observability + счётчики (§30, §31, §46).**
  *Сделать:* R17-safe события через РЕЮС `emit_agentic_event` (гейт `AGENTIC_EVENTS_ENABLED`): `DIRECT_TRIGGER` (trigger_type / force_reply_required / reply_to_bot / is_private / chat_id / message_id — без raw text), РЕЮС `DECISION_START`/`DECISION_COMPLETE` с аддитивными полями (message_class / action / reason; FORCE: action=reply reason=force_direct; REACT: reaction=<enum> reason=<semantic>; SILENT: reason=<semantic>), `DIRECT_SILENT_ACK` (reaction=🗿, success, chat_id, target_message_id, reason_code), `DIRECT_SILENT_ACK_FAILED` (error_code enum, chat_id, target_message_id); счётчики (финальные имена — spec §5.3 / ADR-1028-2 D15; нормализация опечатки §46 — D-PM-3): `direct_force_reply_total`, `direct_autonomous_reply_total`, `direct_autonomous_react_total`, `direct_autonomous_silent_total`, `direct_silent_ack_success_total`, `direct_silent_ack_failed_total`; механика: process-local аккумуляторы через `get_process_accounting()` + grep-able строка `direct_metric name=… count=…` на каждое инкрементное событие.
  *Acceptance:* событие/счётчик на каждый исход матрицы §29; no raw user text (R17); счётчики grep-аются в логах по `direct_metric name=…` (механика ADR D15). **(§30, §31, §46)**
  *Риски:* утечка raw text в поля — обязательная R17-проверка.
  *Тест:* `tests/test_direct_observability_decision_*.py`.

- [x] **T-4027** [MECH] **Context-side observability + summary-поля (§32, §33, §46).**
  *Сделать:* на каждый relevant Direct run (спека §5.2): `CONTEXT_CAPACITY` (model / window / window_source / external_tokens / output_reserve / available_context / budget / policy_mode: unlimited|dynamic|cap / summary_revision / summary_watermark / summary_lag_messages / summary_age), `CONTEXT_SELECT` (recent_verbatim_messages/tokens, reply_thread_messages, old_episode_count/messages/tokens, middle_selected_messages, compressed_background_tokens, rag_tokens), `CONTEXT_PRESSURE` (excluded_low_priority, compressed_or_dropped, physical_overflow, unsummarized_tail_messages/tokens), `CONTEXT_PHYSICAL_OVERFLOW` (preserved_kinds / available / needed — путь T-4016); summary-поля: summary_revision (= `window_end_ts:raw_count`, РЕЮС `_summary_revision`) / summary_watermark / summary_lag_messages / summary_age / unsummarized_tail_messages / unsummarized_tail_tokens; счётчики `direct_old_episode_retrieval_total`, `direct_context_pressure_total`, `direct_context_physical_overflow_total`; без raw content (R17).
  *Acceptance:* события присутствуют при ON-режиме composer'а; диагностический вопрос «summary worker отстал?» отвечает по логам без raw content; поля сходятся с фактической композицией (сумма частей = payload, без расхождений). **(§32, §33, §46)**
  *Риски:* overhead логирования — bounded/структурные события.
  *Тест:* `tests/test_direct_observability_context_*.py`.

---

## Группа F — miniapp [после T-4006; UI-эффекты]

- [x] **T-4028** [MECH] **Miniapp: Context Mode [Dynamic]/[Unlimited] + диагностика (§34).**
  *Сделать:* per-chat Context Mode переключатель (без hardcoded chat_id, §3), пишет существующий `limits.chat_context_budget_tokens` (derive: -1 → Unlimited, 0/None → Dynamic, >0 → Cap display-only — без новых ключей, ADR D12); описания дословно по §34 (Unlimited: «Не применять искусственные лимиты контекста…»; Dynamic: «Автоматически распределять доступный context window…»); диагностические поля: Model context window / Available for context / Current payload / Recent verbatim / Retrieved old episodes / Compressed background / Excluded low-priority; без private raw messages в панелях; backend/miniapp семантика идентична (T-4008); источник диагностической панели — аддитивный read-only `GET /api/direct/context-diagnostics?chat_id=` (значения последнего ON-прогона, process-local snapshot, R17: только числа, существующий RBAC-слой, Δ каталога = 0) — endpoint входит в scope этой задачи, новой задачи нет (D-PM-6, подтверждено Architect).
  *Acceptance:* переключение/сохранение per-chat; подписи соответствуют §34; диагностика отражает реальные значения T-4027. **(§3, §34)**
  *Риски:* stale значения UI — persistence-тесты; Δ каталога — только по санкции T-4006.
  *Тест:* backend-API тесты + T-4030 browser.

- [x] **T-4029** [MECH] **Miniapp: секция DIRECT ADDRESSING / DECISION MAKING (§35).**
  *Сделать:* секция в существующей группе `flags_decision_making` («Принятие решений», param_catalog.py:369) — без новых групп/вкладок (ADR D17): force keywords — **read-only** отображение configured списка (`reactions.chat_botword_pattern` / persona name) с описанием §35 (гарантия §21 не отключаема — force-toggle НЕ вводится, D-PM-4); ровно **3 тумблера** [✓] default ON: Autonomous replies (`flags.chat_autonomous_reply_enabled`) / Use contextual reactions (РЕЮС `flags.chat_decision_reactions_enabled`) / Silent acknowledgement (`flags.chat_silent_ack_enabled`); связь тумблеров с флагами ADR (§5.1).
  *Acceptance:* секция отображается, дефолты ON, переключения применяются backend-side и переживают reload. **(§35, §47)**
  *Риски:* смешение с существующими decision-настройками — разместить по §35, не дублировать.
  *Тест:* API-тесты + T-4030 browser.

- [ ] **T-4030** [MECH] **Browser verification miniapp (§53).** *(Implementation-side smoke выполнен Builder'ом: Playwright против локального dev-сервера (R6 fail-open, PG на dev-машине недоступен) с мок-/api-контуром — переключение Dynamic/Unlimited (POST −1), описания §34, diagnostics-панель (7 полей), force-keywords read-only, тумблеры, persistence after reload, console errors=0, скриншоты desktop/mobile в artifacts/; реальный контур (seeded PG, per-chat переключение живых значений, Telegram WebView) — повтор Reviewer/DevOps + владелец §56-G.)*
  *Сделать:* Playwright/browser-harness проверки: Dynamic/Unlimited переключение; descriptions; per-chat switching; persistence after reload; direct Decision Making settings; silent acknowledgement toggle; reactions toggle; no mixed/stale values. Evidence (скриншоты/логи) — в feature artifacts.
  *Acceptance:* все 8 проверок §53 пройдены, evidence сохранён; console/pageerror — 0. **(§53)**
  *Риски:* Telegram WebView отличия — headless + реальная проверка владельцем на проде (§56 Сценарий G).
  *Тест:* `tests/js/*` + harness-прогоны.

---

## Группа G — тесты: приёмочные сценарии владельца (все из ТЗ)

- [x] **T-4031** [MECH] **Context tests: Unlimited / capacity (§37, TEST 1–5).**
  *Сделать:* TEST 1: global 39k при -1 и достаточном окне — нет `39371 -> 27826`; TEST 2: thread 35k при -1 — нет скрытого cap 32000; TEST 3: aggregate -1 — full-payload adaptive accounting всё равно выполняется; TEST 4: рост system/tools/personality → available уменьшился; TEST 5: рост окна модели → Unlimited больше места без правки констант.
  *Acceptance:* 5/5 зелёные; регресс legacy-тестов обновлён (T-4008). **(§37)**
  *Риски:* тест-окружение подмены окна модели — фикстура per-model config.
  *Тест:* `tests/test_direct_context_unlimited_*.py`.

- [x] **T-4032** [MECH] **Context tests: old episode / stale summary / long chain (§38, §39, §40).**
  *Сделать:* §38 fixture 500 сообщений + запрос к разговору ~200 назад (20–40 сообщений): recent verbatim; old episode verbatim; summary как background; irrelevant middle сокращается раньше; exact wording доступен. §39: summary lag 50/100/300/400 — Direct работает, композиция без hard truncation. §40: reply-chain >6 hops — критический тезис доступен.
  *Acceptance:* все три блока expectations выполнены. **(§38, §39, §40)**
  *Риски:* High — интеграционная сложность fixture; изолировать от прод-БД.
  *Тест:* `tests/test_direct_context_scenarios_*.py`.

- [x] **T-4033** [MECH] **Decision tests: FORCE (§41).**
  *Сделать:* «бот, почему?» / «бот, ты тут?» / «бот, ок» → REPLY; reply_to_bot «бот, нет, ответь нормально» → REPLY; ignore_trivial/recent_reply/low_information не отменяют force; стиль может быть кратким.
  *Acceptance:* все кейсы §41 → ACTION_REPLY. **(§41, §21)**
  *Риски:* низкий при гейте T-4019.
  *Тест:* `tests/test_direct_force_matrix_*.py`.

- [x] **T-4034** [MECH] **Decision tests: autonomous / background / reaction failure (§42, §43, §44).**
  *Сделать:* §42: reply_to_bot «а почему?» → проходит Decision Making; «ну тут я с тобой вообще не согласен» → REPLY/SILENT допустимы, при SILENT → 🗿; «ахах» → предпочтительно REACT; «ок» → REACT или SILENT+🗿. §43: «ахах» между пользователями — бот не обязан реагировать; unrelated background — никакого обязательного 🗿; anti-spam. §44: SILENT + reaction API fail → остаётся SILENT, лог DIRECT_SILENT_ACK_FAILED, без текста; то же для REACT.
  *Acceptance:* все кейсы §42/§43/§44 выполнены. **(§42, §43, §44)**
  *Риски:* nondeterminism decision — детерминируемые reason_code в тестах.
  *Тест:* `tests/test_direct_decision_scenarios_*.py`.

- [x] **T-4035** [MECH] **Полный регресс: pytest + JS, evidence для Reviewer.**
  *Сделать:* полный прогон pytest (правило проекта: перед каждым коммитом, 0 регрессий, таймаут ≤300с) + JS suite; подсчёт новых тестов; sanity: kill-switch OFF — паритет (T-4017), флаги дефолты ON (T-4029).
  *Acceptance:* 0 failed; число новых тестов зафиксировано в evidence; это вход единого Reviewer gate (обе линзы §52.A–J). **(§51, §52, §54 п.22)**
  *Риски:* регресс legacy cap-тестов — все правки атомарно в T-4008.
  *Тест:* полный suite.

---

## Группа H — релиз, деплой, live acceptance, закрытие

- [x] **T-4036** [MECH] **DoD-матрица §54 (22 пункта) + чек-лист запретов §48 — передача Reviewer.**
  *Сделать:* сопоставить каждый пункт DoD §54 (1–22) с задачей/тестом этого файла (карта ниже); оформить чек-лист запретов §48 для Builder/Reviewer (проверять grep'ом по реестру caps D13 — инвентарь T-4000 = надмножество); прогнать матрицу Reviewer-линз §52.A–J перед финальным вердиктом.
  *Acceptance:* 22/22 DoD пункта покрыты задачами+тестами с прямыми ссылками; чек-лист §48 приложен к review. **(§54, §48, §52)**
  *Риски:* непокрытый пункт DoD = hidden gap; маппинг вести с момента старта Build.
  *Тест:* DoD-матрица (в этом файле, ниже).

- [x] **T-4037** [MECH] **Флаги decision-side + rollback-документация (§47, §60).**
  *Сделать:* финальный реестр флагов (spec §5.1 / ADR D10 — ровно 2 новых env + 2 новых per-chat): env `DIRECT_CONTEXT_COMPOSER_ENABLED` (OFF → байт-в-байт прежний контекст-путь, без новых событий/счётчиков) и `DIRECT_SILENT_ACK_ENABLED` (OFF → тишина без 🗿); per-chat `flags.chat_silent_ack_enabled` (env-дефолт от env-флага) и `flags.chat_autonomous_reply_enabled` (OFF → reply-to-bot этого чата всегда текстовый ответ); реакции — РЕЮС существующих `flags.chat_decision_reactions_enabled`/`CHAT_DECISION_REACTIONS_ENABLED` (не дублировать); force-toggle НЕ вводится (D-PM-4). Rollback: **soft = 2 env-флага** (и/или per-chat `flags.chat_autonomous_reply_enabled=false`) — прежний Direct behavior без отката версии; **cold = git revert фича-коммита до 2.58.34** (annotated-тег отката — T-4038); runbook §60 при проблемах на проде (direct messages пропадают / composer теряет контекст / reaction spam / force иногда silent / latency regression / provider overflow → флаг → fix → review → deploy → live acceptance повторно). Каждый флаг — parity-тест OFF (T-4017).
  *Acceptance:* каждый флаг проверен тестом OFF-паритета; rollback-runbook в feature docs; §60-процедура описана. **(§47, §60)**
  *Риски:* «десятки флагов» запрещены — только перечень ADR.
  *Тест:* parity-тесты флагов.

- [ ] **T-4038** [DevOps] [MECH] **Bump 2.58.34 → 2.58.35 + деплой-ранбук (§55).** *(Builder-часть готова: APP_VERSION=2.58.35, README v2.58.35, F8 переиздан, полный pytest/JS-регресс прогнан; rework round 1 выполнен (H1/H2/M1 — код+тесты; H3 — DevOps-SQL сид в evidence.md §Rework, включить в preflight). Деплой-шаги (preflight/сид ключей/checkpoint/annotated-тег от HEAD 8a0fa6c/прод-ff/рестарт/health/live-acceptance T-4039/T-4040) — DevOps.)*
  *Сделать:* preflight; annotated-тег отката (baseline HEAD `8a0fa6c`); бэкапы по конвенции; bump `APP_VERSION` 2.58.34 → **2.58.35** (settings.py:2172 — ADR D16); единый релиз ASAP-3: коммит(ы) код+тесты+каталог+F8 атомарно, push без force, прод ff, restart `admin_bot`, health 200, `/healthz` 2.58.35, `database is locked`=0; проверка логов старта; deployment evidence в `deployment.md`; далее — live acceptance T-4039 (§56–§58) и post-deploy gate T-4040.
  *Acceptance:* прод на 2.58.35, health/логи чистые, evidence зафиксирован; точка отката задокументирована. **(§55, §58)**
  *Риски:* стандартные деплой-риски; таймауты ssh ≤60с/команда.
  *Тест:* деплой-чеклист + health-пробы.

- [ ] **T-4039** [DevOps+Owner] [MECH] **Live acceptance на проде — сценарии A–G (§56).**
  *Сделать:* A FORCE: «бот, ты тут?» → текстовый ответ; B AUTONOMOUS REPLY: содержательный reply на бота без force → Decision Making реально выполняется (REPLY/REACT/SILENT допустимо; SILENT → 🗿); C REACTION: reply «ахах» → contextual reaction предпочтительнее текста; D BACKGROUND: обычная беседа → нет массовых 🗿; E UNLIMITED: Global Context больше старых 27826 tokens при достаточном окне → нет hidden truncation `-> 27826`; F OLD EPISODE: обращение к теме старого длинного разговора → trace показывает relevant old verbatim episode retrieved; G MINIAPP: Dynamic/Unlimited переключаются, сохраняются, соответствуют backend behavior.
  *Acceptance:* A–G пройдены против production, результаты с evidence (скриншоты/trace/логи) в deployment/live-acceptance отчёте. **(§56)**
  *Риски:* ручные шаги владельца (Telegram) — заранее заготовить чек-лист и trace-команды.
  *Тест:* live-acceptance чек-лист A–G.

- [ ] **T-4040** [DevOps] [MECH] **Post-deploy observation + acceptance gate (§57, §58, §60).**
  *Сделать:* по прод-метрикам/логам: прямые счётчики §46 (force/autonomous reply/react/silent, silent ack success/fail, context pressure, physical overflow, old episode retrieval, summary lag); отсутствие: нового ERROR-spike, reaction spam, постоянного physical overflow, silent force-direct, скрытых 27826-truncations; фиксация PROD ACCEPTANCE GATE §58 (Reviewer Approved + deploy + live acceptance + post-deploy = feature DONE); при проблемах — процедура §60 (ACTIVE + kill-switch + fix + повтор).
  *Acceptance:* отчёт post-deploy с числами против базлайна T-4003; гейт §58 зафиксирован; feature_status DONE только после всех четырёх условий. **(§57, §58, §60, §45)**
  *Риски:* короткое окно наблюдения — зафиксировать период и пороги.
  *Тест:* post-deploy отчёт.

- [ ] **T-4041** [PM] [MECH] **Финальный отчёт §61 — задача-шаблон (18 пунктов).**
  *Сделать:* собрать отчёт по обязательной структуре: 1 Root causes; 2 Architect decisions; 3 основной diff; 4 какие старые caps удалены/изменены; 5 как работает Dynamic; 6 как работает Unlimited; 7 как реализован old verbatim episode retrieval; 8 как работает Force Direct; 9 как работает autonomous reply; 10 как выбирается REACT; 11 как работает SILENT+🗿; 12 Test results; 13 Browser verification; 14 Production deployment evidence; 15 Live acceptance results; 16 Post-deploy logs/metrics; 17 Rollback state; 18 подтверждение «ASAP-3 production acceptance complete; current_task continuation unblocked».
  *Acceptance:* отчёт показан владельцу/Orchestrator'у до возобновления current_task; до п.18 — continuation BLOCKED. **(§61, §59)**
  *Риски:* неполный отчёт блокирует эпик — собирать evidence по ходу (T-3999…T-4040).
  *Тест:* 18/18 пунктов заполнены фактами (не заглушками).

---

## DoD-матрица §54 → задачи/тесты (карта для T-4036)

| # | DoD §54 | Задачи | Тесты |
|---|---|---|---|
| 1 | -1 не превращается в 32000 | T-4008, T-4009 | T-4031 TEST 1/2 |
| 2 | Unlimited = no artificial cap | T-4007, T-4008 | T-4031 TEST 1/2/5 |
| 3 | Physical model window учитывается | T-4007 | T-4031 TEST 4/5 |
| 4 | Full payload accounting для Unlimited | T-4007, T-4009 | T-4031 TEST 3 |
| 5 | Dynamic mode работает | T-4009, T-4010 | T-4032 (§38) |
| 6 | Любой чат получает Unlimited через miniapp | T-4028 | T-4030, §56-G |
| 7 | Important context удаляется позже слабого | T-4010 | T-4032 (§38) |
| 8 | Recent conversation verbatim | T-4012 | T-4032 (§38) |
| 9 | Old dialogue 200+ msgs verbatim episode | T-4011 | T-4032 (§38), §56-F |
| 10 | Running summary = background | T-4013 | T-4032 (§38/§39) |
| 11 | Stale summary без massive-tail cut | T-4014 | T-4032 (§39) |
| 12 | Long reply chain — доступ к тезису | T-4015 | T-4032 (§40) |
| 13 | Force keyword → ACTION_REPLY всегда | T-4019 | T-4033 (§41) |
| 14 | Reply-to-bot остаётся autonomous | T-4020, T-4025 | T-4034 (§42) |
| 15 | Decision REPLY/REACT/SILENT | T-4022, T-4023, T-4025 | T-4034 (§42) |
| 16 | Intentional direct SILENT → 🗿 | T-4023 | T-4034 (§42), §56-B |
| 17 | Background silence без 🗿 spam | T-4021, T-4023 | T-4034 (§43), §56-D |
| 18 | Contextual reactions реально используются | T-4022 | T-4034 (§42), §56-C |
| 19 | reply_to_bot ≠ bot_replied_recently | T-4018 | T-4018 unit |
| 20 | Miniapp соответствует backend semantics | T-4028, T-4029 | T-4030, §56-G |
| 21 | Observability диагностирует context + decisions | T-4026, T-4027 | observability-тесты |
| 22 | Unit/integration/browser suite green | все | T-4035 |

## Запреты «НЕ считается fix» (§48) — чек-лист Reviewer

Ни одно из этих «решений» не принимается как выполнение ASAP-3: 32000→64000; убрать TOKEN_SAFETY_MULTIPLIER без переосмысления; просто увеличить CHAT_GLOBAL_CONTEXT_LIMIT; просто увеличить CHAT_THREAD_MAX_DEPTH; всегда отправлять все 500 сообщений; `text[:N]`; keep_head/keep_tail как единственная стратегия; отключить running summary; заставить reply всегда отвечать текстом; отключить Decision Making; заставить пользователя всегда писать «бот»; 🗿 на весь ignored background; 🗿 как единственная реакция вообще; LLM retries вместо исправления context pipeline; переписывание ASAP-2 Summary.

## Трассировка: раздел ТЗ → задача → тест (компакт)

| § ТЗ | Требование (кратко) | Задачи | Тесты |
|---|---|---|---|
| §0 | Граница эпика (Summary не трогать; consumer-side) | T-4013, T-4036 | регресс Summary (T-4035) |
| §1 | Root cause truncation 39371→27826 | T-3999 | T-4031 TEST 1 |
| §2, §7 | -1 = no artificial cap; семантика -1/0/>0 | T-4000, T-4008 | T-4031 TEST 1/2 |
| §3 | Per-chat Unlimited, без hardcoded chat_id | T-4028 | T-4030, §56-G |
| §4 | Model-aware full payload budget | T-4007 | T-4031 TEST 3/4 |
| §5 | Adaptive accounting и для Unlimited | T-4009 | T-4031 TEST 3 |
| §6 | Убрать двойное truncation | T-4000, T-4009 | T-4031 TEST 1/2 |
| §8 | Priority P0–P3, eviction, P0 не терять | T-4010 | T-4032 (§38) |
| §9 | Raw history = source of truth | T-4002, T-4011 | T-4032 (§38) |
| §10 | Old verbatim episodes из существующих источников | T-4011 | T-4032 (§38) |
| §11 | Episode boundary (design + impl) | T-4004, T-4011 | T-4032 (§38) |
| §12 | Recent context всегда verbatim | T-4012 | T-4032 (§38) |
| §13 | Summary = background, финальная композиция | T-4013 | T-4032 (§38/§39) |
| §14 | Stale summary resilience | T-4014 | T-4032 (§39) |
| §15 | Thread depth >6 | T-4015 | T-4032 (§40) |
| §16 | Dynamic без rigid ratio, перераспределение | T-4010 | T-4031 TEST 5, T-4032 |
| §17 | Physical overflow degradation | T-4016 | overflow-тест |
| §18 | Decision Making сам по себе не бага | T-4025 | T-4034 (§42) |
| §19 | Три уровня адресации A/B/C | T-4019, T-4020, T-4021 | T-4033/T-4034 |
| §20, §23 | Trigger-поля; reply_to_bot ≠ bot_replied_recently | T-4018 | unit T-4018 |
| §21 | «бот, …» всегда REPLY | T-4019 | T-4033 |
| §22 | Reply на бота autonomous | T-4020 | T-4034 |
| §24, §36 | REACT полноценный; ACK→REACT | T-4022 | T-4034 |
| §25–§27 | SILENT+🗿; не на фон; разные outcomes | T-4023 | T-4034 |
| §28 | Reaction failure fail-soft | T-4024 | T-4034 |
| §29 | Decision priority цепочка | T-4025 | интеграционные |
| §30, §31 | DIRECT_TRIGGER / DECISION события | T-4026 | obs-тесты |
| §32, §33 | CONTEXT_* события; summary-поля | T-4027 | obs-тесты |
| §34 | Miniapp Context Mode + диагностика | T-4028 | T-4030 |
| §35 | Miniapp Decision секция, defaults ON | T-4029 | T-4030 |
| §37 | Context tests Unlimited TEST 1–5 | T-4031 | одноимённые |
| §38–§40 | Episode/stale/thread tests | T-4032 | одноимённые |
| §41–§44 | Decision tests force/autonomous/background/failure | T-4033, T-4034 | одноимённые |
| §45 | Prod log research до изменений | T-4003 | базлайн-отчёт |
| §46 | Метрики-счётчики | T-4026, T-4027 | obs-тесты |
| §47 | Флаги / rollback | T-4017, T-4037, T-4006 | parity-тесты |
| §48 | Запреты «не fix» | T-4036 | чек-лист |
| §49 | Вопросы Architect Q1–Q10 | T-4004, T-4005, T-4006 | ADR |
| §50 | PM: reconcile → PLANNING_CONSISTENT | этот файл, следующий шаг PM | — |
| §51 | Builder invariants | все MECH-задачи | T-4035 |
| §52 | Reviewer линзы A–J | T-4036 | review |
| §53 | Browser verification | T-4030 | harness |
| §54 | DoD 22 пункта | T-4036 | DoD-матрица |
| §55 | Prod deploy | T-4038 | deployment.md |
| §56 | Live acceptance A–G | T-4039 | live-чеклист |
| §57, §58 | Post-deploy + gate | T-4040 | post-deploy отчёт |
| §59 | Workflow gate (последовательность) | рамки блока 0 | — |
| §60 | При проблеме на проде | T-4037, T-4040 | rollback-runbook |
| §61 | Финальный отчёт 18 пунктов | T-4041 | отчёт |
| §62 | Архитектурный инвариант | T-4036 (финальная сверка) | DoD-матрица |

## Вопросы @Architect — ЗАКРЫТЫ ADR-1028-2 (Accepted)

**Все вопросы закрыты ADR-1028-2 (D1–D17):** Q1→D1 (`services/model_capacity.py`; unknown → fallback 16384 + WARN); Q2→D2 (формула бюджета, множитель ровно 1 раз); Q3→D3 (единый композер, OFF — байт-в-байт); Q4→D4 (детерминированные границы эпизода, 0 LLM, второй движок запрещён); Q5→D5 (stale summary — композицией, не ножницами); Q6→D6 (fresh tail ≥ `CHAT_FRESH_TAIL_MIN_MESSAGES` = 20); Q7→D7 (dynamic expansion + episode retrieval, walk до 40); Q8→D8 (матрица trigger × исход; `bot_replied_recently` независим, окно 600с); Q9→D9 (словарь REACT + строгая конъюнкция 🗿); Q10→D10 (2 новых env + 2 per-chat; force-toggle НЕ вводится); PM-Q1→D11 (`token_counter.py` не меняется, consumer-side граница); PM-Q2→D12 (Context Mode = derive от `limits.chat_context_budget_tokens`; Δ каталога +2 ключа → F8 482/423/457/105/103/21); PM-Q3→D13 (реестр скрытых/явных caps); PM-Q4→D14 (REUSE смерженных §93–§100 обязателен, второй движок запрещён); PM-Q5→D15 (финальные имена событий/счётчиков); PM-Q6→D16 (bump 2.58.35 подтверждён); PM-Q7→D17 (размещение в существующих группах `limits_chat`/`flags_decision_making`).

Исторические формулировки вопросов (до ADR) сохранены ниже для трассировки.

**Из самого ТЗ (§49, обязательные Q1–Q10):**
1. **Q1.** Где брать physical context-window capability для каждой модели (карта/конфиг/env; поведение при неизвестной модели)?
2. **Q2.** Как рассчитывается full payload budget (формула, source of tokens для каждого слагаемого)?
3. **Q3.** Как Dynamic и Unlimited используют один composer?
4. **Q4.** Как определить relevant old episode и его boundaries (детерминированный/explainable алгоритм)?
5. **Q5.** Как composer ведёт себя при stale running summary?
6. **Q6.** Как гарантируется fresh verbatim tail?
7. **Q7.** Как проходит long reply chain (>CHAT_THREAD_MAX_DEPTH)?
8. **Q8.** Точная trigger priority: force / autonomous / background?
9. **Q9.** Как REACT и SILENT+🗿 представлены в contract/metrics?
10. **Q10.** Как выполняется rollback?

**Добавлено @PM (пересечения и границы, требуется явное решение):**
- **PM-Q1 (важный).** `resolve_context_tokens`/`safe_budget` — общий utility: его потребляют Summary-генератор и его тесты (`summary_generator.py`, `test_summary_fact_package`, `test_summary_l1_clusterizer`). Менять семантику -1 глобально или только consumer-side в Direct-пути (граница §0)? От этого зависит объём регресса.
- **PM-Q2.** Хранение Context Mode: derive из существующих per-chat `limits.chat_*=-1` vs новая явная per-chat настройка; новые ключи в param_catalog → Δ каталога>0 требует санкции и переиздания frozen F8 (прецедент ADR-1026-2).
- **PM-Q3.** Инвентарь T-4000: полный перечень caps, признанных «скрытыми» (удаляются) vs «explicit override» (сохраняются) — утвердить списком в ADR, чтобы Reviewer проверял по нему (§52.A).
- **PM-Q4.** Episode retrieval: допустимые к переиспользованию существующие слои (thread_chain F6/ADR-1023-2, смерженные retrieval-слои) при том, что WIP MCA-волны (ARCHITECTURE.md §93–§100) вне скоупа — граница REUSE.
- **PM-Q5.** Имена новых флагов (§47) и имён событий/счётчиков (§30–§33, §46) — финальный реестр в ADR (в ТЗ имена примерные).
- **PM-Q6.** Deploy: подтвердить bump 2.58.34→2.58.35 и per-feature деплой по ASAP-конвенции (MCA §20 «единый релиз» на MCA-фичи не распространяется; прецеденты ASAP-2/2.1).
- **PM-Q7.** Miniapp: место секций §34/§35 в существующей IA (раздел чат-настроек), без редизайна IA.

## Зависимости [ARCH]

- **T-4004** (composer ADR) блокирует: T-4007…T-4017 (вся группа C), тесты T-4031/T-4032.
- **T-4005** (decision ADR) блокирует: T-4018…T-4025 (вся группа D), тесты T-4033/T-4034.
- **T-4006** (flags/observability/miniapp ADR) блокирует: T-4026–T-4029, T-4037.
- Группа A (T-3999…T-4003) — без блокировок, вход для ARCH и реализации; T-4003 желателен до финала ADR (базлайн распределений).
- T-4030 ← T-4028/T-4029; T-4035 ← все реализационные; T-4038 ← T-4035 + T-4036; T-4039 ← T-4038; T-4040 ← T-4039; T-4041 ← T-4040 (все предыдущие).
- **Порядок волн:** A (параллельно с B) → B → C ∥ D ∥ E∥F → G → H. Внутри C: T-4007→T-4008→T-4009→T-4010→(T-4011→T-4012→T-4013→T-4014)→T-4015→T-4016→T-4017.

## Риски фичи (top)

1. **Общий utility с Summary** (PM-Q1) — изменение семантики -1 может задеть Summary-пайплайн (§0 запрещает). Mitigation: решение ADR + полный регресс.
2. **Скрытые caps** — неполный инвентарь T-4000 оставит «fake unlimited» (прямая антицель §52.A). Mitigation: grep-инвентарь + Reviewer-линза A.
3. **🗿-спам** — ошибка классификации фона как direct (§26). Mitigation: жёсткий гейт T-4023 + анти-спам тест §43 + prod-метрики §57.
4. **Force перехвачен шорт-катами** — ignore_trivial/recent_reply отменяют гарантированный ответ (§21). Mitigation: force-гейт до шорт-катов + матрица §41.
5. **Качество границ эпизодов** — retrieval возвращает обрывок вместо диалога (§11). Mitigation: explainable алгоритм + лог hit→span + fixture §38.
6. **Каталог/флаги** — Δ каталога>0 без санкции нарушает frozen-F8 дисциплину. Mitigation: PM-Q2 в ADR до Build.
