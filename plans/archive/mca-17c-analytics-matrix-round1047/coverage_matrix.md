# MCA-17c — матрица покрытия (T-5191, §27.1 `plans/current_task.md:1331–1364`)

**Дата:** 07.10.2026. **Метод:** сверка code-declared реестра `PROCESS_REGISTRY` (47 `ProcessDefinition`, `services/mca_process_registry.py:219`) с фактическими handlers/workers/расписаниями/путями отправки: для каждого процесса указаны handler-факт (file:line на рабочем дереве round 10.47), источник событий/состояния, drill-down в «Аналитике» (mca-17c UI) и честная причина пробела. Mapping стадий на события — колонка «события»; число карточек покрытием не считается (`:1337`).

**Синхронизация (замер `coverage_report()` без живой БД, 07.10.2026):** 47 = implemented 20 + disabled 1 + not_run 4 + not_instrumented 22. Замер на живом проде (события за ретенцию) — T-5199/live-приёмка; здесь статус-классы реестра, факт — handlers.

**Правило чтения:** `not_instrumented` — это **не** пробел mca-17c (read-side отражает контракт mca-17a, CA-17C-1): это процессы, чьи handler-ы не эмитят `mca_events` — состояние видно через `state_source`-таблицы/настройки, а не через run-trace. По §27.10 (`:1480`) они отображаются честно; их инструментирование — вопрос эскалации @Architect (+mca-17a), НЕ self-serve 17c (CA-17C-7).

## 1. Сверка реестра ↔ handlers (47/47)

| № | process_id | widget-группа | owner | handler (факт file:line) | события / состояние (факт) | drill-down в «Аналитике» |
|---|---|---|---|---|---|---|
| 1 | ingestion.live | Приём/импорт/редакции | mca-03 | `services/canonical_messages.py` (запись `smart_messages`); identity-события — у №3 | state: `smart_messages` (`services/database.py:307`); note реестра: handler не эмитит mca_events | «Процессы»: карточка группы «Приём/импорт/редакции» (статус not_instrumented — честно) |
| 2 | ingestion.import | Приём/импорт/редакции | mca-03 | `services/summary_memory.py:4039` (`IMPORT_RETENTION_ENABLED`) | state: `import_checkpoints` (`services/database.py:136`); инструментирования нет | там же (группа) |
| 3 | identity.resolve | Идентичность и адресаты | mca-03 | `services/message_identity.py` (разрешение автора; события `message_revision`) | события `message_revision`/`message_identity_migration` (`services/database.py:291/:320` — колонки контракта) | карточка группы; runs по run_id, где события присутствуют |
| 4 | chat.lifecycle | Приём/импорт | mca-03 | миграции chat_id: `services/database.py:3021/:7298` (`chat_id_migrations`) | state: `chat_id_migrations`; инструментирования нет | карточка группы (not_instrumented) |
| 5 | summary.window | Окно/summary | summary | `services/summary_scheduler.py` + `services/summary_run_store.py` (гейт `CHAT_RUNNING_SUMMARY_ENABLED`, `services/chat_params.py:519`) | span-события стадии summary: `services/pipeline_events.py:127` (`component="summary"`); state `chat_running_summary` | «Запуски» `component=summary` / `pipeline_type=summary.window`; drill с карточки |
| 6 | summary.hybrid | Summary Hybrid | summary | L1/L2 контур: `services/summary_l1_capacity.py`, `summary_l2_writer.py`, `services/database.py:2169` (`chat_summary_levels`) | стадии L1/L2 — часть summary-пайплайна (span'ы `component="summary"`); отдельного словаря событий нет | «Запуски» `component=summary` |
| 7 | facts.extract | Факты/граф | factext | `services/graphrag_rebuild.py` (`GRAPH_RAG_ENABLED`, `services/direct_chat_service.py:5905`) | state: `graph_facts` (`services/canonical_context.py:137`); mca_events-инструментирования нет | карточка группы «Факты/граф» |
| 8 | dossier.rebuild | Досье/архив | dossier | `services/dossier_rebuild_jobs.py:5/:61` (`DossierRebuildJobStore`) | события `dossier_rebuild*` (`services/database.py:2337`; reason-коды `services/mca_events.py:113–122`) | «Запуски» (runs dossier), карточка группы |
| 9 | provenance.record | Provenance | mca-04a | `services/provenance.py` | события `memory_provenance` (protected component, `services/mca_events.py:756–763`); state `mca_source_refs` (`services/database.py:343`) | карточка группы «Provenance» |
| 10 | embeddings.index | Embeddings/индексы | mca-07 | `services/embedding_control_plane.py` | state: `embedding_cache`, `mca_embedding_index_generations` (`services/database.py:433/:472`); события не подключены (mca07_* — retrieval-контур) | карточка группы; Embeddings-панель существующая |
| 11 | retrieval.query | Retrieval/RAG | mca-07 | `services/mca_retrieval_context.py` | события `mca07_retrieval/mca07_reranker/mca07_bundle/mca07_budget` (объявлены `services/mca_process_registry.py:399–406`) | карточка группы «Retrieval/RAG»; runs, где события есть |
| 12 | nostalgia.run | Ностальгия | nostalgia | `services/nostalgia_worker.py:84–101` (`NOSTALGIA_ENABLED`) | state: `task_jobs`, `graph_facts`; инструментирования нет | карточка группы «Ностальгия» |
| 13 | lore.compile | Эпизоды/lore | lore | `services/lore_worker.py:78–120` + `services/lore_compiler_service.py` (`LORE_COMPILER_ENABLED`) | state: `lore_stories` (`services/database.py:680`); инструментирования нет | карточка группы «Эпизоды/lore» |
| 14 | sleep.dream | Сон/убеждения | dream | `services/dream_worker.py:373` (`DREAM_ENABLED`) | state: `task_jobs`; run-событий нет | карточка группы «Сон/убеждения» |
| 15 | sleep.deep | Глубокий сон/парадигмы | dream | `services/dream_worker.py:1728/:1751` (`DREAM_DEEP_RUN` emit) | события `DREAM_DEEP_RUN` + span-стадии; state `mca_pipeline_runs`, `memory_dream_log` | «Запуски» `component=dream`; L-3-метка причин (`oversightDeepReasonLabel`) |
| 16 | persona.traits | Личность/интересы | persona | `services/bot_persona.py:250–259` (`PERSONA_ENABLED`) | state: `persona_*`; инструментирования нет (компакт — виджет «Статуса») | карточка группы «Личность/интересы» |
| 17 | anticliche.run | Анти-клише | anticliche | `services/anticliche_cache.py:3/:61` + `anticliche_worker.py` | state: `anticliche_cache`; agentic_events — отдельный контракт (не mca_events) | карточка группы «Анти-клише» |
| 18 | goodmorning.run | Планировщики | goodmorning | `services/goodmorning_scheduler.py` (подключён `bot.py:69–70/:243`) | state: `task_jobs`; инструментирования нет | карточка группы «Планировщики» |
| 19 | scheduler.reactions | Планировщики | scheduler | reaction-mechanics: `services/direct_chat_service.py:154/:706` (`REACTION_MECHANICS_ENABLED`) | state: `task_jobs`; инструментирования нет | карточка группы «Планировщики» |
| 20 | direct.reply | Ответы (decision/System2) | direct_chat | `services/direct_chat_service.py` (гейт `:154`-зона; `DIRECT_DECISION_MAKING_ENABLED`) | события `mca07_answer_cache`, `speech_understanding`, `postprocess_form`, `numeric_claim_guard` (объявлены `services/mca_process_registry.py:522–539`); state `task_jobs`,`mca_events` | «Запуски» `pipeline_type=direct.reply`; contract required_stages в detail |
| 21 | style.scope | Личность/интересы | mca-08 | `services/mca_style_scope.py:515` | события `style_scope` (`services/direct_chat_service.py:100/:1907`); state `mca_style_requests` | карточка группы; runs по событиям style_scope |
| 22 | tools.chain | Tool chain | tools | `services/tool_loop.py:49/:133` (`"tool_call"`-события; `TOOL_CHAIN_LIMITS_ENABLED`) | события `tool_call/tool_delivery/tool_accounting` (`services/direct_chat_service.py:1062/:1276`); M-2 delta — счётчики в раскрытии шага | «Запуски» (runs с tool-событиями), M-2 delta в run-детали |
| 23 | random.source | Источник случайности | mca-10a | `services/mca_random_source.py` (`MCA_RANDOM_SOURCE_ENABLED`) | события `random_activation/random_batch/random_fallback` (`services/mca_process_registry.py:608–629`); durable-журнал `mca_random_batches/draws` (`services/database.py:1014`) | карточка группы «Источник случайности»; runs по событиям random |
| 24 | web.fetch | Web/видео/медиа | mca-02 | `services/safe_fetch.py:88/:504` (`SafeFetcher`) | события `safe_fetch` (emit `services/image_generation.py:52/:65` и вызовы fetch-контура); state `mca_events` | карточка группы «Web/видео/медиа» |
| 25 | media.download | Web/видео/медиа | media | `services/media_download.py:8` + `services/media_execution.py` (`DOWNLOAD_ENABLED`) | state: `task_jobs`, filesystem; инструментирования нет | карточка группы |
| 26 | image.generate | Tool chain | image | `services/image_generation.py:191` (`IMAGE_GENERATION_ENABLED`) | state: `mca_events` (reservation), tool-события tools.chain; собственного словаря нет | карточка «Tool chain» (через tool-события) |
| 27 | summary.publish | Публикация | summary | публикация summary: `services/summary_memory.py` (гейт `SUMMARY_ENABLED`, `services/chat_params.py:518–519`) | state: `mca_events` (терминальные отправки через ToolResult/ledger `services/bot_output_ledger.py:127`); отдельного словаря нет | «Запуски» `component=summary` (publish-стадия в contract `summary.window`) |
| 28 | factcheck.run | Фактчек | factcheck | `services/factcheck_service.py:77–125` (`FACTCHECK_ENABLED`) | state: in-memory + `mca_events` (терминальные); run-словаря нет | карточка группы «Фактчек» |
| 29 | maintenance.retention | Сохранение/ресурсы | maintenance | `services/disk_retention.py:95` (`DISK_RETENTION_ENABLED`) | state: `task_jobs`, filesystem; инструментирования нет | карточка группы «Сохранение/ресурсы» |
| 30 | backup.memory | Сохранение/ресурсы | backup | `services/memory_backup.py:33–43` (`MEMORY_BACKUP_ENABLED`) | state: filesystem, `task_jobs`; инструментирования нет | карточка группы |
| 31 | uptime.heartbeat | Сохранение/ресурсы | uptime | `services/uptime_heartbeat.py:29–47` | state: filesystem, `task_jobs`; инструментирования нет | карточка группы |
| 32 | telemetry.events | Сохранение/ресурсы | mca-17a | `services/mca_events.py:599` (flush) / `:751` (prune) — сам контракт | НЕ эмитит mca_events (структурный лог + bounded-буфер/spool/gaps-счётчики — метрики видны в mca-metrics-блоке) | mca-metrics-блок «Аналитики» (gaps/spool/degraded — F15) |
| 33 | watchdog.jobs | Сохранение/ресурсы | mca-17a | `services/mca_watchdog.py:42–59` (`recover_stale` — `services/task_supervisor.py:547`) | события `WATCHDOG_SWEEP/WATCHDOG_TAKEOVER` (объявлены `services/mca_process_registry.py:779–784`) | карточка группы; runs interrupted — видны в «Запусках» |
| 34 | incidents.delivery | Инциденты | mca-17a | `services/mca_incidents.py` (`open_or_update/acknowledge/resolve/incident_changes`) | события `INCIDENT_*` (`incident_opened/acknowledged/resolved/reopened`, `services/mca_events.py:99–100`); state `mca_incidents` (`services/database.py:519`) | представление «Инциденты» (read-only ack; F14-сортировка) |
| 35 | episodes.build | Эпизоды/lore | mca-05 | `services/mca_episode_jobs.py` + emit `services/mca_episodes.py:1413` | события `episodes_build/story_*` (`services/database.py:687/:784` — `mca_episodes/mca_stories`) | карточка группы «Эпизоды/lore»; runs по событиям episodes |
| 36 | episodes.backfill | Эпизоды/lore | mca-05 | `services/mca_episode_jobs.py` (unique `episodes.backfill:<chat_id>`) | те же события; state `task_jobs` | там же |
| 37 | context.compress | — (v0) | mca-09 | **не реализовано** (note реестра; `services/mca_process_registry.py:959–960` — устаревшая метка-плейсхолдер) | — | не рендерится как активный; честная заготовка |
| 38 | context.selective | — (v0) | mca-10a | **не реализовано** (note реестра) | — | там же |
| 39 | memory.lifecycle | — (v0) | mca-10b | **не реализовано** (note реестра) | — | там же |
| 40 | relations.semantic | — (v0) | mca-11 | **не реализовано** (note реестра) | — | там же |
| 41 | chat.statistics | Измерения, проверки и отказы | mca-15 | `services/chat_statistics.py:112/:655` (`MCA_CHAT_STATISTICS_ENABLED`) | события `stats_intent/chat_statistics/numeric_claim_guard` (`services/chat_statistics.py` emit-ы) | карточка группы «Измерения…»; runs по событиям stats |
| 42 | self_learning.run | Опыт и уроки | mca-16 | `services/mca_experience_jobs.py` + `services/mca_experience.py:1588` (`MCA_EXPERIENCE_LESSONS_ENABLED`) | события `experience_recorded/lesson_proposed/validation_*/activated/retrieved/applied/feedback_linked/utility_updated/suspended/superseded` (`services/mca_events.py:263` зона объявлений; state `services/database.py:1087/:1152/:1196`) | «Самообучение»: воронка (funnel-API) + граф урока (существующий `/api/memory/lessons`) |
| 43 | intent.initiative | Намерения и инициатива | mca-09 | `services/mca_intents.py:1056` (`MCA_INTENTS_ENABLED`) | события `intent_created/…/initiative_decided/recheck_deferred` (`services/mca_events.py:272` зона); state `mca_intents` (`services/database.py:1221`) | карточка группы «Намерения и инициатива»; runs по intent-событиям |
| 44 | random.uses | Случайность и её применения | mca-10b | `services/mca_exploration.py` (`MCA_RANDOM_USES_ENABLED`) | события `random_uses/random_uses_lifecycle/random_uses_background` (`services/database.py:2689`); state `task_jobs`,`mca_events` | карточка группы «Случайность и её применения» |
| 45 | self.model | Что сейчас формирует характер | mca-18 | `services/mca_self_model.py` + snapshot `services/bot_persona.py:265–289` (`MCA_SELF_MODEL_ENABLED`) | события `self_model` (стадии `prompt_render/observation_read` — `services/bot_persona.py:289/:403`); state `mca_trait_observations/mca_behavior_rules` (`services/database.py:1365`) | «Самообучение» → фуннель личности (3 статуса, D12); существующий компакт на «Статусе» не дублируется |
| 46 | vision.media | Распознавание изображений | mca-19 | `services/mca_vision.py:512/:1243` (стадии, `MCA_VISION_ENABLED`) | события `vision_media/vision_capability_probe`; state `mca_media_assets/mca_media_analyses` (`services/database.py:1497`) | карточка A73-группы; runs `component=vision.media` |
| 47 | temporal.factcheck | Временной фактчек | mca-20 | `services/temporal_factcheck.py:256` (стадии) | события `factcheck_temporal`; state `mca_factcheck_runs/evidence` (`services/database.py:1601`) | A73-карточка; существующий виджет «Временной фактчек» + runs `component=factcheck.temporal` |

**Итог сверки:** 47/47 `ProcessDefinition` имеют фактический handler/источник состояния либо честную пометку «не реализовано» (v0-заготовки №37–40 — deliberate, note реестра). Незарегистрированных активных процессов сверх реестра при сверке не выявлено; дополнительная проверка при деплой-окне — T-5198/T-5199 (spec R-a).

## 2. Минимальная матрица §27.1 (`:1341–1360`) → widget/drill-down/trace

| Строка §27.1 | Виджет в «Аналитике» (что показывает) | Что раскрывается в запуске | Покрытие |
|---|---|---|---|
| Приём/импорт/редакции | Карточка группы «Приём/импорт/редакции»: статусы 4 процессов группы (not_instrumented честно) | runs по identity-событиям (Message ID, версия, dedup — события №3) | частично: trace только у identity.resolve — причина в колонке №1/№2/№4 |
| Идентичность и адресаты | Карточка «Идентичность и адресаты» | runs: автор/роль/метод — события `message_revision` | да |
| Окно/running summary/Hybrid | Карточки «Окно/summary», «Summary Hybrid»; «Запуски» `component=summary` | span-стадии filter/cluster/synthesize (`pipeline_events.py:127`), counts ok/fail | да (read-render span-контракта) |
| Факты, досье, protected facts, граф | Карточки «Факты/граф», «Досье/архив», «Provenance» | dossier-rebuild runs с reason-кодами; provenance-события | частично: facts.extract без run-событий (эскалация) |
| Embeddings и индексы | Карточка + существующая Embeddings-панель | очередь/версии — state-таблицы; run-trace отсутствует | частично (эскалация) |
| Retrieval/RAG/ностальгия/dig | Карточки «Retrieval/RAG», «Ностальгия» | retrieval-runs с `mca07_*`-событиями | частично: nostalgia без trace |
| Provenance и архивный backfill | Карточка «Provenance» + dossier/backfill runs | диапазон/checkpoint — `task_jobs` + dossier-события | да (через №8/№36) |
| Эпизоды, истории, lore compiler | Карточки «Эпизоды/lore» | episodes-runs: `story_*`-события, merge/split | да (№35/36); lore.compile без trace (эскалация) |
| Сон/убеждения | Карточка «Сон/убеждения» | runs нет — state `task_jobs` | частично (эскалация) |
| Глубокий сон/парадигмы | Карточка «Глубокий сон/парадигмы»; «Запуски» `component=dream` | стадии DREAM_DEEP_RUN + L-3-причины | да |
| Личность/интересы/анализаторы | Карточки «Личность/интересы», «Анти-клише» | runs нет; компакты на «Статусе» | частично (эскалация) |
| Намерения/инициатива/Decision | Карточка «Намерения и инициатива»; runs intent-событий | candidates/why-not/исход — события №43 + direct.reply contract | да |
| Случайность и применения | Карточки «Источник случайности», «Случайность и её применения» | партия/draw/выбор/fallback — события №23/44 | да |
| EvidenceBundle/контекст/карта LLM | mca07_bundle/budget события — runs retrieval-контура; карта LLM — существующая «Аналитика токенов» | состав/сжатие/versions | да (существующие витрины + runs) |
| Tool chain, web/video/media, System2, verbalizer | Карточки «Tool chain», «Web/видео/медиа» | args/result refs, retries, fallback — `tool_call/tool_delivery/tool_accounting` | да; media.download/image.generate без собственного trace (через tool-события) |
| ChatStatistics/NumericClaim | Карточка «Измерения, проверки и отказы» | метод/итог — события №41 | да |
| Самообучение/опыт/lessons | «Самообучение»: воронка + граф урока + «Эффект» | источник/проверка/scope/версии/применение/feedback — funnel-API + `/api/memory/lessons` | да (unknown ≠ провал/успех) |
| Сохранение/кеши/очереди/доставка | Карточка группы «Сохранение/ресурсы»; mca-metrics (gaps/spool) | `task_jobs`-состояния, delivery_unknown — reason в событиях | частично: run-trace только у watchdog/incidents/telemetry (эскалация) |

**Дополнение `:1364` (MCA-18/19/20):** самостоятельные A73-карточки «Что сейчас формирует характер» (фуннель D12 + runs `self_model`), «Распознавание изображений» (runs `vision.media`, стадии `:1699`-контракта), «Временной фактчек» (runs `factcheck.temporal` + существующий виджет) — все три на реальных запусках, версии/ошибки раскрываются; компакт-витрины mca-12 не дублируются (CA-17C-4).

## 3. Пробелы и эскалации (честно, CA-17C-7)

1. **22 процесса not_instrumented** (список в шапке) — handler-ы не пишут `mca_events`; для них drill-down до run-trace невозможен, состояние отражается через state-таблицы/настройки. Это бэкенд-пробел наблюдаемости, унаследованный от mca-17a (note-поля реестра задокументированы в коде). **Эскалация @Architect** (+mca-17a): построчное инструментирование — отдельные санкции; 17c не само-сервится (CA-17C-1/7). В UI все 22 видны с честной причиной.
2. **4 v0-заготовки** (№37–40) — не реализованы владельцами-фичами; рендерятся как «заготовка (запусков нет)», не имитируют активность (`:1480`).
3. **Новых widget-ID не требуется** (47=47); расхождений «активный процесс вне реестра» не найдено на рабочем дереве — повторная сверка на проде в деплой-окне (spec R-a).

## 4. Тест синхронизации

`tests/test_mca17c_invariants_round1047.py::test_registry_47_no_new_widgets` (count==47) расширен проверкой обязательных полей каждой definition (см. `test_coverage_matrix_sync`): process_id/version/purpose/stages/trigger_kind/settings_ref/state_source/widget_id/event_names — непустые где ожидается; v0-заготовки — явный маркер `WIDGET_NONE`. Overfit-защита: тест проверяет структуру контракта, не конкретные file:line.
