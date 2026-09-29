# `mca-07-retrieval-context` — спецификация (Step 2 @Architect, T-3839)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 1** (данные). **Фича-ID:** `mca-07-retrieval-context`.
- **Тип:** backend/LLM/data — сочетание retrieval (lexical/FTS + vector + фильтры + reply-граф + эпизоды), типизированный reranker, embedding identity/fingerprint/поколения, единый `EvidenceBundle`, адаптивный бюджет контекста, singleflight/high-watermark/CAS сводок и отключение прежнего ответного кеша. **Потребитель контрактов** `mca-03` (§96) и `mca-04a` (§98); **предпосылка** для `mca-09` (Intent/Decision), `mca-15` (статистика), `mca-16` (Experience), `mca-20` (temporal factcheck), `mca-10b`.
- **Источник (IMMUTABLE, R17/R18):** `plans/current_task.md` v1.8 **§11.1** (`:395–399`), **§11.2** (`:407–416`), **§11.3** (`:422–426`), **§11.4** (`:432–434`); §2.3/§2.10/§3/§3.1/§4 (`:23`,`:34`,`:47`,`:60–75`,`:77–101`); §17.1–§17.3 (`:818–844`); §18 (`:856–872`); §19 **A03/A04/A05/A06/A24** (`:884–887`,`:905`); §22; R17/R18.
- **Задачи:** `tasks.md` T-3837…T-3858 (T-3839…T-3853 — поставки фичи). **Приёмки:** A03, A04, A05, A06, A24.
- **ADR:** `adr-1027-7-retrieval-context.md` (D1–D12). **Рамка:** `plans/docs/mca-round1027-arch-frames.md` (§1.2.3, §2, §3, §4).
- **Статус:** Proposed → Accepted по T-3857 (Merge в `plans/ARCHITECTURE.md` **§99+**). **Deploy:** `DEFERRED_TO_RELEASE`.
- **Risk-Level:** **R3** (подтверждено) — retrieval/EvidenceBundle/бюджет лежат на критическом пути контекста ответа: ошибка теряет адресата/ветку/ограничения, смешивает несовместимые векторы, раздувает/переполняет полный запрос или отдаёт устаревшую сводку/старый ответный кеш. Обязателен `threat-failure-analysis.md`. Что может поднять риск: если потребуется несовместимая перестройка vec-индексов в hot-path или полнота учёта бюджета окажется недостижимой без блокирующего вызова tokenizer. Триггеры понижения до R2: доказанная изоляция retrieval/бюджета от hot-path записи, A03/A04/A05/A06/A24 на фактическом diff, отсутствие перезаписи/удаления legacy-строк.
- **Baseline (Step 0, используется как данность):** Reviewed-Commit `05bc870`; `APP_VERSION` 2.58.31; SQLite DDL **v17** (после `mca-04a`); каталог `473/430/448/102/100/21`; канон инструментов 12; pytest 9712/0 + JS 47/47; откат anchor `7165ff7`.
- **Зависимости (✅ закрыты):** `mca-03` (канон `(chat_id, tg_message_id)`, `sent_at`/`ingested_at`, namespace/source record/revision — §96), `mca-04a` (типизированный SourceRef/EvidenceLink/статусы: bundle **ссылается**, не копирует — §98), `mca-01` (единый write-механизм `write_transaction`/`serialized()`, `TaskSupervisor`/`coalescing`/`task_jobs` — §95), `mca-13` (`emit_mca_event`/`mca_events` — единый durable-стор событий; второй запрещён — §94), `mca-14` (реестр `MigrationStep`/`schema_migrations` — §93), `lore_cache.generation` (прецедент invalidation/CAS).

## 1. Область и исключения

**Входит:**
- **Единый retrieval-контракт** — одна точка запроса, **оборачивающая** существующие каналы (lexical/FTS + exact, vector, фильтры по времени/участникам, reply-граф, эпизоды); для запроса об истории — **сначала эпизоды**, при необходимости спуск к сообщениям; сохранение точной фразы/имени/даты.
- **Типизированный reranker**: типизированный список выбранных ID; **валидный пустой список ≠ все кандидаты**; `invalid`/`timeout` — **отдельный статус** с явной политикой fallback; порядок = оценке.
- **Embedding identity/fingerprint/поколения**: cache key = текст + provider/model + dimensions + preprocessing/version (+ endpoint там, где он меняет модель); **один dimension ≠ совместимость**; у индексов — **fingerprint и поколение**; смена модели при той же размерности не смешивает векторы.
- **EvidenceBundle §11.2** — полный логический контракт (trigger/current revision; адресат/автор/упоминаемые/неоднозначности; ветка/локальный контекст; факты/эпизоды с SourceRef и временем; ограничения/неизвестное/противоречия; профиль/интересы/отношения; выбранное намерение/недавние действия; `context_version`/исключённые материалы и причины) + **решение по материализации** (in-memory vs персистентный).
- **Один согласованный bundle** для решения, инструментов, синтеза и формулировки; **System2 после tool loop не теряет адресата/ветку/ограничения** (не получает только исходный вопрос + tool output); архив на каждом этапе не дублируется.
- **Бюджет контекста §11.3** — полный учёт payload (system/developer/personality, user context, tools schemas, tool results, output reserve, служебный overhead с учётом реального API); консервативная оценка + метод при неизвестном tokenizer; адаптивный объём; сохранение отрицаний/ID/дат; логирование размера/резерва/исключений.
- **Сводки §11.4** — singleflight/coalescing + high-watermark/CAS (поздний старый запрос не перезаписывает новую версию); обновление источников — отдельной revision.
- **Ответный кеш §11.4** — для контекстных диалоговых ответов отключить прежний кеш по одному нормализованному query/chat/user; **дедупликацию одного Telegram update сохранить**; повторное «почему?» под другим родителем — заново; «иной ответный кеш» — не обязательная оптимизация (если есть — ключ с зависимыми версиями + родителем).
- Δ DDL **v18** через реестр `mca-14`; события MCA-13/стадии MCA-17a; R17-маскирование; kill-switch; тесты/деплой/откат.

**Не входит (границы):**
- **Episode/Story модель, сборка/продолжения, `lore_stories`/`lore_compiler_service` как источник эпизодов** — `mca-05` (mca-07 использует существующий фасад, второй каталог запрещён).
- **Архивный backfill/досье, full rebuild, `_WINDOW_SQL` LIMIT, budget-exhaustion→done, `upsert_generated_dossier`, фактическая перестройка несовместимого vec-индекса как отдельный resumable job** — `mca-04b` (mca-07 **определяет** механизм поколений/fingerprint, но перестройку не выполняет).
- **Intent/Decision-модель, `defer`, отправка/инициатива** — `mca-09` (mca-07 отдаёт `context_version` и bundle).
- **Случайность/exploration** — `mca-10a`/`mca-10b` (mca-10b использует retrieval через контракт, второго retrieval нет).
- **ChatStatistics/MetricResult/NumericClaim** — `mca-15` (потребляет FTS/exact retrieval).
- **ExperienceEpisode/Lesson** — `mca-16` (bundle как отдельный тип, не смешивается).
- **ClaimEnvelope/TemporalVerdict** — `mca-20` (потребляет retrieval/bundle).
- **ToolResult-контракт/лимиты цепочек/учёт расходов** — `mca-11` (mca-07 учитывает tool results в бюджете, но не определяет ToolResult).
- **UI-виджеты/матрица процессов** — `mca-17a`/`mca-17c`/`mca-12` (mca-07 только регистрирует стадии/виджет-ID и эмитирует события).
- **Изменение `pg_db.py`** — вне diff (GEN-R4; SQLite и PG сохраняются, PG — no-op).
- **«Иной ответный кеш»** — не обязательная оптимизация; контракт ключа задан, реализация опциональна.

### 1.1. Фактическое состояние baseline (сверено с рабочей веткой; REUSE §3)

- **Reranker нарушает §11.1/A05.** `services/summary_memory.py::rerank_rag_facts` (`:2612–2646`): при LLM-ошибке (`:2637`) и при «распарсили ноль номеров» (`:2640–2643`) возвращает **исходный список кандидатов** — это ровно анти-паттерн «пустой/битый ответ → все кандидаты». `services/search_service.py::_rerank_results` (`:105–128`): fail-open возвращает исходные результаты (`:119–120`,`:127–128`); формат — текст, не типизированные ID. **Разрыв §11.1 присутствует.**
- **Embedding compatibility не защищена от смены модели при той же размерности.** `_embed_cache_key` (`summary_memory.py:294–296`) = `sha256(casefold+strip)` — **без** provider/model/preprocessing. `embedding_cache` (`database.py:1958–1961`): `text_hash` PK, колонки `text/vector/dim/created_at/last_used_at`; lookup пропускает только по `row["dim"] != expected_dim` (`:1418–1423`) → **один dimension считается доказательством совместимости**. Vec-индексы (`smart_archive`/`graph_facts_vec`, `summary_memory.py:93–117`) хранят только `float[N]`; при смене **размерности** таблицы DROP+пересоздаются (`:1276–1283`), но при смене **модели с той же размерностью** старые векторы остаются и обслуживаются → **смешивание**. **Разрыв §11.1/A06 присутствует.**
- **Сводка перезаписывается без high-watermark/CAS.** `get_window_messages` (`summary_memory.py:1692–1731`) триггерит `fire_and_forget(_build_running_summary)`; `_build_running_summary` (`:1733–1782`) строит конспект и делает **слепой** `upsert_running_summary` (`database.py:5842–5862`, `ON CONFLICT(chat_id) DO UPDATE` без guard). `chat_summary_levels` уже имеет `msg_count_highwater` (`:791`, guard `:1802–1804`), но у `chat_running_summary` guard нет → **поздно завершившийся старый запрос перезаписывает новую версию**. **Разрыв §11.4/A03 присутствует.** Прецедент CAS/generation — `services/lore_cache.py::ChatLoreCache.generation` (`:76–80`,`:174–176`).
- **Ответный кеш ключуется по тексту.** `direct_chat_service.py:1233–1256`: `dedup_key = md5("direct_dedup\x00{chat_id}\x00{user_id}\x00" + normalize_text(query))`; реплей сохранённого ответа/молчания. Это **ровно** прежний кеш по одному нормализованному query/chat/user, подлежащий отключению для контекстных ответов. Параметры `CHAT_DEDUP_ENABLED`/`CHAT_DEDUP_TTL_SECONDS` — в `param_catalog` (`:872`,`:1345`), **не удаляются** (Δ каталога 0). **Разрыв §11.4 присутствует.**
- **Бюджет считает не весь запрос.** `_apply_context_budget` (`direct_chat_service.py:2443–2594`) учитывает только тексты блоков; `fixed_tokens` — лишь неприкосновенные *kinds* (`target/relations/protected/lore/current/sandwich`). System/developer/personality, tools schemas, tool results, output reserve и служебный overhead в учёт **не входят**; обрезка — `_truncate_block`/`truncate_keep_header`/`truncate_to_tokens` (`token_counter.py:74–128`) **не защищает** отрицания/ID/даты. **Разрыв §11.3/A24 присутствует.**
- **Единого bundle нет.** Контекст собирается постадийно (`_build_user_content`/`_build_global_context`/`_render_thread` + System2/tool loop в `direct_chat_service`); согласованного объекта `EvidenceBundle` с адресатом/веткой/ограничениями, переживающего tool loop, нет. **Разрыв §11.2 присутствует.**
- **REUSE-предпосылки на месте:** `search_messages_fts`/`search_graph_facts_fts` (`database.py:3654`/`:5055`), `thread_chain.collect_thread_chain` (`:94`), `lore_stories`/`lore_compiler_service.compile` (`database.py:846`,`:3749`), `token_counter` (`count_tokens`/`resolve_context_tokens`/`resolve_chat_limit`/`safe_budget`), `TaskSupervisor`+`task_jobs` coalescing (`mca-01`), `provenance.py` SourceRef/EvidenceLink (`mca-04a`), `emit_mca_event`/`mca_events` (`mca-13`), `MigrationStep` (`mca-14`), `lore_cache.generation` (прецедент CAS).
- ⚠️ **Расхождение ТЗ↔план:** исходная ссылка задачи «`plans/docs/mca-round1027-plan.md` §11» не существует (документ содержит §0–§7); релевантные пункты — план **§3.5** (закрытие `mca-04a`) и **§6 п.5** (открытый вопрос EvidenceBundle). Учтено как §6 п.5.

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA07-01 — единый retrieval-контракт (FTS/exact + vector + фильтры + reply-граф + эпизоды; эпизоды-первыми для истории; точная фраза/имя/дата) | §11.1 `:395` | SC-01, SC-02 | T-3843, T-3844, T-3845 |
| REQ-MCA07-02 — типизированный reranker (список ID; пустой валидный ≠ кандидаты; отдельный статус `error/timeout` + fallback; порядок = оценке) | §11.1 `:397` | SC-03, SC-04 | T-3846 |
| REQ-MCA07-03 — embedding identity/fingerprint/поколения (cache key = текст+provider/model+dims+preprocessing/version(+endpoint); dimension ≠ совместимость) | §11.1 `:399` | SC-05, SC-06 | T-3847 |
| REQ-MCA07-04 — EvidenceBundle: полный логический контракт §11.2 (все поля; SourceRef не копируется; `context_version`/исключения+причины) | §11.2 `:407–416` | SC-07, SC-08, SC-10 | T-3848 |
| REQ-MCA07-05 — один bundle для решения/инструментов/синтеза/формулировки; System2 не теряет адресата/ветку/ограничения; архив не дублируется; GEN-R21 | §11.2 `:416` | SC-09, SC-11 | T-3852 |
| REQ-MCA07-06 — адаптивный бюджет: полный учёт payload + консервативная оценка/метод + сохранение отрицаний/ID/дат + логирование | §11.3 `:422–426` | SC-12, SC-13 | T-3849 |
| REQ-MCA07-07 — сводки singleflight/HWM/CAS + source revision; ответный кеш query/chat/user отключён, update-дедуп сохранён; «иной кеш» с зависимыми версиями/родителем | §11.4 `:432–434` | SC-14, SC-15 | T-3850, T-3851 |
| GEN-R19 — REUSE; второй retrieval/EvidenceBundle запрещён | §3/§3.1 `:47`,`:60–75` | SC-16 | T-3843, T-3844, T-3846, T-3848, T-3852 |
| MCA13-R1/R2 + GEN-R17 + GEN-R14 — события `start`+`outcome`/`reason_code`, стадии/виджет-ID, R17-маскирование | §17.1–§17.3; §27.1; §2.16 | SC-17 | T-3853 |
| MCA14-R1/R2/R5 — аддитивная идемпотентная Δ DDL через реестр; kill-switch env-only default ON; deploy | §18 `:864–872`; §2.4–2.5 | SC-18 | T-3840, T-3842, T-3856 |

**Орфан-REQ нет;** T-3837/3838/3841/3854/3855/3857/3858 — процессные (baseline/PM-декомпозиция/сверка/тесты/merge/архив). Каждый `REQ-MCA07-01…07` покрыт ≥1 задачей; каждая задача — REQ/SC либо процессная.

## 3. Наблюдаемое поведение и отказы

- На «почему?» бот отвечает про **родительское** сообщение (та же ветка), сохраняя исходный вопрос/участников/ограничения. По запросу об истории сначала поднимаются подходящие **эпизоды**, при необходимости — сообщения.
- По конкретному вопросу бот находит нужный случай **или честно не находит ничего**; похожая тема не считается ответом автоматически — reranker, вернувший **валидный пустой** список, оставляет контекст пустым, а **не** возвращает всех кандидатов.
- При смене embedding-модели **при той же размерности** старые и новые векторы не смешиваются; один dimension не считается доказательством совместимости.
- Поздно завершившийся старый LLM-summary **не** перезаписывает более новую сводку.
- Одинаковое «почему?» под **разными** родителями получает **разные** контексты; старого кеш-ответа по одному query/chat/user нет; при этом один и тот же Telegram update не обрабатывается дважды.
- Для сложного вопроса берётся больше нужного материала, для короткой реплики — меньше; в диагностике видно, что оставлено, что сокращено, какой объём/резерв/исключённые категории. Отрицание/ID источника/дата **не** обрезаются так, что меняется смысл. Заведомо переполненный запрос **не** отправляется.
- **FAILURE-семантика:** reranker `invalid`/`timeout` → отдельный статус + детерминированный fallback по pre-rerank-порядку (bounded), статус виден потребителю; ошибка БД/embed → честная деградация (FTS-only / пустой контекст), без подмены; OFF kill-switch → точный legacy-путь (паритет baseline).

## 4. Интерфейсы и контракты

### 4.1. Единый retrieval-контракт (D1/D2)
- **Вход:** `RetrievalRequest { chat_id, query, trigger_ref, scope(time_range|participants|parent|branch), mode(auto|history|exact), top_k, policy_version }`. **Выход:** `RetrievalResult { status, candidates[], channels_used[], generation_fingerprint, reason_code }`; каждый `candidate` — типизированная ссылка (`SourceRef`-id по `mca-04a` + `sent_at`/`author_id` из `mca-03`) + score/канал; **кандидат ссылается на источник, не копирует сырьё**.
- **Каналы (комбинация, не один):** (1) **lexical/FTS + exact** — REUSE `search_messages_fts`/`search_graph_facts_fts`/`search_archive_facts_fts`; (2) **vector** — REUSE `smart_archive`/`graph_facts_vec` KNN, **ограниченный активным поколением** индекса (D4); (3) **фильтры** по времени (`sent_at`) и участникам (`author_id`); (4) **reply-граф** — REUSE `thread_chain.collect_thread_chain` (вторую цепочку не плодить); (5) **эпизоды** — REUSE `lore_stories`/`lore_compiler_service` (фасад; второй каталог запрещён).
- **История:** при `mode=history` (или классификации запроса как исторического) — **сначала эпизоды**, затем спуск к сообщениям только при недостатке/неоднозначности.
- **Точная фраза/имя/дата сохраняются:** exact/FTS-канал всегда доступен; точная фраза — quoted-FTS; имя — через идентичность/алиасы (только отображение/резолв, не слияние; `mca-03`); дата/период — фильтр по событийному времени (`sent_at`), не по `ingested_at`/`timestamp`-как-дата-записи.
- **Короткие ответы не отбрасываются** (нет порога минимальной длины).
- **Раздельность память↔веб (GEN-R10):** retrieval памяти и самостоятельный веб-поиск сохраняют **разные** выключатели; единый контракт не сливает их.
- **Совместимость:** единая точка **оборачивает** существующие пути (REUSE), а не создаёт второй движок. OFF `MCA_RETRIEVAL_CONTEXT_ENABLED` → legacy-вызовы каналов как сейчас.

### 4.2. Типизированный reranker (D3)
- **Контракт:** `RerankResult { status: ok|empty|invalid|timeout|error, selected: list[RerankItem{id, score}] }`; `id` — стабильный ID кандидата; порядок `selected` = порядку оценки.
- **`ok` + `selected=[]`** — **валидный пустой** результат: контекст пуст; **не** разворачивается во всех кандидатов.
- **`invalid`** (непарсимый формат)/**`timeout`**/**`error`** — **отдельный статус** с **явной политикой fallback**: детерминированный **pre-rerank-порядок** (retrieval score), ограниченный `top_k`; статус и `reason_code` видимы потребителю. Fallback **не** равен «всем кандидатам» и **не** равен валидному пустому списку — это отдельно наблюдаемое состояние.
- **Порядок = оценке** при заявленном ранжировании (не входному порядку).
- **REUSE/AMEND:** существующие `rerank_rag_facts` и `search_service._rerank_results` приводятся к единому типизированному ядру (один reranker), становясь адаптерами; второй reranker не создаётся. Действующее поведение «ошибка/пустой парс → исходные кандидаты» **устраняется** (A05). OFF `MCA_TYPED_RERANKER_ENABLED` → прежнее поведение.

### 4.3. Embedding identity / fingerprint / поколения (D4)
- **Cache key (verbatim §11.1):** `key = H(identity_fingerprint \x00 casefold(strip(text)))`, где `identity_fingerprint = sha256(provider \x1f model \x1f str(dims) \x1f preprocessing_version \x1f endpoint_fingerprint)`.
- **Endpoint/deployment:** учитывается там, где меняет модель; решение — `endpoint_fingerprint` включается в fingerprint **при непустом значении** (консервативно: надёжно доказать ту же модель за другим endpoint нельзя; over-invalidation безопасна — лишь повторный embed, тогда как under-invalidation смешивает векторы — A06). Это документированное консервативное правило.
- **Один dimension ≠ совместимость:** lookup кэша больше **не** считает совпадение `dim` доказательством; совпадение определяется полным `identity_fingerprint`. Legacy-строки (старый алгоритм ключа) не матчатся и вытесняются TTL/LRU.
- **Индексы имеют fingerprint и поколение:** реестр `mca_embedding_index_generations` хранит для каждого индекса (`smart_archive`/`graph_facts_vec`) его `fingerprint`/`generation`/`provider`/`model`/`dims`/`preprocessing_version`/`endpoint_fingerprint`/`status` (`active|building|superseded|failed`). На старте: вычисляется текущий fingerprint; если он не совпадает с fingerprint активного поколения — старые векторы **не** обслуживаются (FTS-only до перестройки), перестройка как отдельный resumable job — **`mca-04b`** (mca-07 задаёт механизм/gate, не выполняет перестройку).
- **AMEND** `_embed`/`_embed_cache_key`/`embedding_cache` (`summary_memory.py`); второй embedding-путь не создаётся. OFF `MCA_TYPED_RERANKER_ENABLED` не влияет; отдельного gate для identity нет — identity-политика следует за `MCA_RETRIEVAL_CONTEXT_ENABLED` (защита — часть единого контракта; OFF → legacy `sha256(casefold+strip)` + dim-проверка).

### 4.4. EvidenceBundle §11.2 (D5)
- **Логический контракт (frozen dataclass, in-memory):** `trigger` + `current` (message/`revision` из `mca-03`); `addressee`/`author`/`mentioned`/`ambiguities`; `branch`/`local_context` (reply-граф/цепочка); `evidence` (факты/эпизоды с **SourceRef** `mca-04a` + время); `constraints`/`unknown`/`contradictions`; `persona`/`interests`/`relations`; `chosen_intent`/`recent_actions`; `context_version`; `excluded[]` (`{ref, position, reason_code, estimated_tokens}`).
- **Материализация — in-memory (решение).** Bundle **не** персистится как единая таблица: он **ссылается** на уже durable SourceRef/EvidenceLink/`smart_messages`, а не копирует архив (§11.2 «не требуется дублировать весь архив»). В durable/события попадают только `context_version` + `SourceRef`-ссылки (R17). Опциональный bounded debug-снимок — через существующую телеметрию (новый store запрещён).
- **`context_version`** — детерминированная версия над зависимостями bundle: schema-версия bundle + revision текущего сообщения + упорядоченные `(SourceRef-id, revision)` выбранных материалов + `summary_revision` (derived из `window_end_ts`/`raw_count`) + версии persona/config/policy + active embedding `generation`/`fingerprint` (если использован vector) + версия retrieval-политики. Меняется при изменении любой зависимости; используется для консистентности между стадиями, для MCA-09 decision-record, для «иного ответного кеша» и телеметрии. **Не** отдельная таблица (derived).
- **Исключения и причины:** `excluded[]` несёт материал (ссылку) + `reason_code` (`budget_exceeded`/`dedup`/`stale`/`off_scope`/`superseded`/…) + оценку; видимо в диагностике (A24).
- OFF `MCA_EVIDENCE_BUNDLE_ENABLED` → legacy-сборка контекста без единого bundle.
- **Область наполнения живого bundle (AMEND 27.09.2026, T-3857):** контракт хранит **все** поля §11.2 (полный frozen-dataclass, см. `services/mca_retrieval_context.py`). Живой builder mca-07 наполняет детерминированно выводимые поля (без нового I/O, без семантического LLM-извлечения, без дублирования архива): `trigger`/`current_message_ref`/`current_revision`, `addressee`/`author`/`mentioned`, `branch` (reply-граф/цепочка), `evidence` (SourceRef-ссылки + время), `constraints`, `relations`, `chosen_intent`, `recent_actions`, `context_version`, `excluded[]`. Поля `ambiguities`/`unknown`/`contradictions`/`local_context`/`persona`/`interests` — **санкционированный carry-over** к первому потребителю, обладающему семантикой (владельцы — §8.1). **Семантика пустого:** до заполнения пустое значение = «не вычислено на этой стадии» (`not_available`), **не** утверждение «неоднозначностей/неизвестного/противоречий нет». Заполняющий обязан (а) не создавать второй bundle (§11.2/GEN-R19) и (б) при расширении набора влияющих полей учесть это в `context_version` (schema-версия), чтобы версия осталась честным ключом консистентности.

### 4.5. Bundle ↔ Summary Hybrid / System2 / verbalizer (D6)
- **Producers (REUSE):** Summary Hybrid Epic 2 (L1/L2 через `get_window_messages`/`get_running_summary`/`get_summary_level`; токены — через `resolve_context_tokens`/`resolve_chat_limit`/`safe_budget`), retrieval-кандидаты (4.1), факты/эпизоды с SourceRef (`mca-04a`), identity (`mca-03`), профиль/интересы/отношения, intent/recent actions (`mca-09` — позже). Summary Hybrid — **поставщик** блоков в bundle, **не** параллельный контекст.
- **Consumers:** decision (A7), tool loop, synthesis (System2), verbalizer/постпроцессор. **Один и тот же** bundle (или его scoped-срез) проходит через все стадии.
- **System2 после tool loop** получает bundle: адресат/ветка/ограничения/`current` сохраняются; он **не** получает только исходный вопрос + tool output. Полный архив на каждом этапе **не** дублируется (переиспользуются ссылки).
- **GEN-R21:** UI в БД напрямую не ходит; bundle собирается внутри приложения, сеть/LLM — вне транзакции записи.
- OFF `MCA_EVIDENCE_BUNDLE_ENABLED` → прежние стадии.

### 4.6. Бюджет контекста §11.3 (D7)
- **Полный учёт payload:** system/developer/personality + user context (блоки) + **tools schemas** + **tool results** + **output reserve** + **служебный overhead** с учётом реального API. `fixed` (неприкосновенные) и вклад по категориям считаются раздельно.
- **При неизвестном tokenizer** — консервативная оценка с запасом (`safe_budget`/chars-fallback) + **логирование метода** (`reason`/`estimation_method`).
- **Объём адаптивный**; нет универсального обязательного лимита 6000/8; жёсткая граница — окно модели и размер payload.
- **Порядок сжатия:** сначала целые смысловые блоки, затем сжатие менее важных. При обрезке **защищаются** отрицания, ID источника и даты (protected spans) — смысл не меняется.
- **Переполнение:** сокращать/суммировать с сохранением источников, дополнительный retrieval либо уточнение; **не** отправлять заведомо переполненный запрос (pre-flight проверка до вызова).
- **Логирование:** фактический размер, резерв, исключённые категории и причина (R17-safe).
- **AMEND** `_apply_context_budget` + `token_counter` (не второй бюджет). OFF `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` → прежний `_apply_context_budget` (паритет baseline).

### 4.7. Сводки: singleflight/high-watermark/CAS + revision (D8)
- **singleflight/coalescing:** для сводки per chat — единая точка (`TaskSupervisor` coalescing по `coalesce_key` и/или in-process singleflight `mca-01`); одинаковую сводку на каждый read не запускать.
- **high-watermark/CAS:** `upsert_running_summary` становится **CAS**: запись только если новый `window_end_ts` (и/или `raw_count`) ≥ текущего high-watermark (`INSERT ... ON CONFLICT DO UPDATE ... WHERE excluded.window_end_ts >= chat_running_summary.window_end_ts`); поздний старый запрос **не** перезаписывает новую версию (A03). **Δ DDL не требуется** (используются существующие колонки).
- **Обновление источников — отдельной revision:** `summary_revision` (derived из `window_end_ts`/`raw_count`/`current_revision` источника) участвует в `context_version` и в CAS-сравнении.
- **REUSE:** `summary_memory.get_window_messages`/`_build_running_summary`, `chat_running_summary`/`upsert_running_summary`; прецедент CAS/generation — `chat_summary_levels.msg_count_highwater` и `lore_cache.generation`. OFF `MCA_SUMMARY_SINGLEFLIGHT_ENABLED` → прежний fire-and-forget без singleflight/HWM.

### 4.8. Ответный кеш (D9)
- **Отключить прежний кеш** по одному нормализованному `query/chat/user` (`direct_dedup`-ключ) для **контекстных диалоговых ответов**: ответ не реплеится из текстового кеша.
- **Дедупликацию одного Telegram update сохранить:** идемпотентность по идентичности сообщения (`chat_id, tg_message_id` из `mca-03`), **не** по тексту; один и тот же update/сообщение не обрабатывается дважды.
- **Повторное «почему?» под другим родителем** обрабатывается **заново** (у другого родителя иная ветка → иной `context_version`).
- **«Иной ответный кеш»** (опционально): если сохранён — ключ **обязан** включать зависимые версии и ссылку на родителя (напр. `H(context_version + parent_ref)`) и **не** сводиться к нормализованному тексту.
- **Совместимость:** `CHAT_DEDUP_ENABLED`/`CHAT_DEDUP_TTL_SECONDS` из `param_catalog` **не** удаляются (Δ каталога 0) и продолжают действовать на legacy-пути при OFF. ON (default) → MCA-07 политика (legacy text-replay отключён, update-дедуп сохранён); OFF → прежний ответный кеш (паритет baseline). См. §5 (формулировка имени).

### 4.9. Наблюдаемость и R17 (D11)
- События `start`+терминальный `outcome` через REUSE `emit_mca_event`/`mca_events` (второй store запрещён); стадии `retrieval`, `reranker`, `bundle`, `budget`, `summary`; регистрация стадий/виджет-ID для `mca-17a` (новый процесс без наблюдаемости = незавершённая интеграция).
- **Расширение словаря `reason_code`** (реестр MCA-13, расширяемый): `retrieval_empty`, `rerank_invalid`, `rerank_timeout`, `budget_exceeded`, `context_overflow`, `embedding_generation_changed`, `summary_stale_dropped`, `answer_cache_disabled`, `exact_match_used`, `episodes_used`.
- R17: в логи/события — только id/коды/`error_type`; SourceRef вместо сырого контекста; `sanitize()` до записи во все каналы; секреты/сырые сообщения не логируются.

## 5. Δ DDL (санкция) / Δ каталога / kill-switch

**Δ DDL = v18** (аддитивно, идемпотентно, через реестр `mca-14`; PG — no-op; старые таблицы/ID/FTS/vec-данные не переименовываются и не удаляются). Точные объекты:

```sql
-- Реестр поколений/fingerprint векторных индексов (durable identity основа)
CREATE TABLE IF NOT EXISTS mca_embedding_index_generations (
    generation_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name            TEXT NOT NULL,     -- smart_archive|graph_facts_vec
    generation            INTEGER NOT NULL,  -- монотонно per index_name
    fingerprint           TEXT NOT NULL,     -- sha256(provider|model|dims|preprocessing_version|endpoint_fingerprint)
    provider              TEXT,
    model                 TEXT,
    dims                  INTEGER,
    preprocessing_version TEXT,
    endpoint_fingerprint  TEXT,
    status                TEXT NOT NULL,     -- active|building|superseded|failed
    created_at            INTEGER NOT NULL,
    activated_at          INTEGER,
    superseded_at         INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_eig_name_gen
    ON mca_embedding_index_generations(index_name, generation);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_eig_active
    ON mca_embedding_index_generations(index_name) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_mca_eig_fingerprint
    ON mca_embedding_index_generations(fingerprint);

-- Embedding cache: identity-колонки (nullable; диагностика/детерминированный sweep).
-- Lookup-ключ формируется identity-хэшем (см. §4.3), колонки — для аудита/вытеснения.
ALTER TABLE embedding_cache ADD COLUMN provider              TEXT;   -- NULL = legacy/unknown
ALTER TABLE embedding_cache ADD COLUMN model                 TEXT;   -- NULL = legacy/unknown
ALTER TABLE embedding_cache ADD COLUMN preprocessing_version TEXT;   -- NULL = legacy/unknown
ALTER TABLE embedding_cache ADD COLUMN endpoint_fingerprint  TEXT;   -- NULL = не учитывался
ALTER TABLE embedding_cache ADD COLUMN identity_fingerprint  TEXT;   -- NULL = legacy/unknown
```

**Legacy/совместимость:**
- `embedding_cache` продолжает работать: старые строки (ключ по старому алгоритму) не матчатся новым ключом → вытесняются TTL/LRU; `dim`-колонка сохраняется как defense-in-depth. Все новые колонки nullable = честный unknown; backfill не требуется.
- Vec-таблицы (`smart_archive`/`graph_facts_vec`) **не** модифицируются (ALTER у vec0 нет); их идентичность обслуживается реестром поколений. Поколение `active` по умолчанию создаётся лениво при инициализации vec-пути из текущей embedding-конфигурации; при отсутствии записи поведение = честная деградация на FTS (не смешивать неизвестные векторы).
- Повторный прогон шага — no-op (guard `sqlite_master`/`PRAGMA table_info`); `user_version` 17→18. PG — no-op.
- **Индексы — только под подтверждённый `EXPLAIN QUERY PLAN`** (резолв активного поколения по `(index_name, status='active')`, lookup по `fingerprint`). «Все комбинации» запрещены.

**Δ каталога = 0.** Все рубильники — env-only `ClassVar`; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; F8 (ADR-1026-2) **NOT_APPLICABLE**. Существующие `CHAT_DEDUP_ENABLED`/`CHAT_DEDUP_TTL_SECONDS`/`EMBED_CACHE_ENABLED`/`GRAPH_RAG_ENABLED` **уважаются, не дублируются и не удаляются**.

**Kill-switch (утверждены, env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline):**
- `MCA_RETRIEVAL_CONTEXT_ENABLED` — ON: единый retrieval-контракт (комбинация каналов + эпизоды-первыми); OFF: legacy-путь retrieval (без объединённого контракта/эпизодов-фасада).
- `MCA_EVIDENCE_BUNDLE_ENABLED` — ON: единый `EvidenceBundle`; OFF: legacy-сборка контекста без bundle.
- `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` — ON: полный учёт payload + адаптивность + protected spans; OFF: прежний `_apply_context_budget`.
- `MCA_TYPED_RERANKER_ENABLED` — ON: типизированный список ID + отдельный статус/fallback; OFF: прежний reranker.
- `MCA_SUMMARY_SINGLEFLIGHT_ENABLED` — ON: singleflight/coalescing + high-watermark/CAS; OFF: прежний fire-and-forget.
- `MCA_CONTEXT_ANSWER_CACHE_ENABLED` — **ON (default): активна политика MCA-07 для ответного кеша** — прежний кеш по одному нормализованному `query/chat/user` для контекстных ответов **отключён**; **дедупликация Telegram update сохранена**. **OFF: восстановлен прежний ответный кеш** (baseline). **Формулировка инверсии подтверждена и уточнена:** имя гейта обозначает **новую** context-keyed политику (не legacy reuse); ON = новая политика, OFF = паритет baseline. (PM-предупреждение «имя инвертировано относительно функции» снято этой формулировкой.)
- **Совместимость/приоритет:** гейты независимы (OFF одного даёт паритет по своей оси); существующие `MCA_MESSAGE_IDENTITY_ENABLED`/`MCA_MESSAGE_REVISION_TRACKING_ENABLED`/`MCA_PROVENANCE_ENABLED`/`MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED`/`MCA_TASK_SUPERVISOR_ENABLED`/`GRAPH_RAG_ENABLED`/`MULTILAYER_EXTRACTION_ENABLED` **уважаются, не дублируются**. OFF фиксируется в release-manifest/логе (причина/время/план, R17-safe); релиз — со всеми ON.

## 6. Приёмочные сценарии (SC)

- **SC-01:** retrieval — **комбинация** каналов (lexical/FTS + exact + vector + фильтры времени/участников + reply-граф + эпизоды), не один канал; точная фраза/имя/дата сохраняются (A04).
- **SC-02:** для запроса об истории **сначала эпизоды**, затем (при необходимости) сообщения; короткие ответы не отбрасываются; кандидат несёт SourceRef/время (A04).
- **SC-03:** reranker возвращает **типизированный список ID**; **валидный пустой список ≠ все кандидаты** (все кандидаты обратно не возвращаются) (A05).
- **SC-04:** `invalid`/`timeout`/`error` — **отдельный статус** с явной политикой fallback (pre-rerank-порядок, bounded); порядок при заявленном ранжировании = оценке (A05).
- **SC-05:** embedding cache key включает текст + provider/model + dims + preprocessing/version (+endpoint там, где меняет модель); dim-совпадение **не** доказывает совместимость (A06).
- **SC-06:** индексы имеют **fingerprint и поколение** (registry); смена модели при той же размерности не смешивает старые/новые векторы; активное поколение обслуживается, несовпадающее — FTS-only до перестройки (A06).
- **SC-07:** `EvidenceBundle` содержит **все** поля §11.2 (trigger/current revision; адресат/автор/упоминаемые/неоднозначности; ветка/локальный контекст; факты/эпизоды с SourceRef и временем; ограничения/неизвестное/противоречия; персона/интересы/отношения; intent/недавние действия; `context_version`; исключённые + причины) (A04/A24).
- **SC-08:** `context_version` детерминирован над зависимостями; bundle **ссылается** на SourceRef, не копирует и не подменяет контракт `mca-04a`; `excluded[]` с причинами видим в диагностике (A04/A24).
- **SC-09:** System2 после tool loop получает **тот же** bundle: адресат/ветка/ограничения сохранены; не только исходный вопрос + tool output; архив на каждом этапе не дублируется (A04/A24).
- **SC-10:** один согласованный bundle используется для решения, инструментов, синтеза и формулировки; UI не ходит в БД напрямую (GEN-R21) (A04).
- **SC-11:** повторное «почему?» под **разными** родителями → **разные** контексты; прежний кеш по одному query/chat/user **не** отдаёт старый ответ (A04).
- **SC-12:** бюджет учитывает **полный** payload (system/developer/personality, user context, tools schemas, tool results, output reserve, overhead); при неизвестном tokenizer — консервативная оценка + **логирование метода** (A24).
- **SC-13:** объём адаптивный; отрицания/ID источника/даты не обрезаются так, что меняется смысл; заведомо переполненный запрос не отправляется; логируются фактический размер/резерв/исключённые категории/причина (A24).
- **SC-14:** сводка per chat — singleflight/coalescing + **high-watermark/CAS**; поздно завершившийся старый запрос **не** перезаписывает новую версию; обновление источников — отдельной revision (A03).
- **SC-15:** для контекстных ответов прежний кеш по одному нормализованному query/chat/user **отключён**; дедупликация одного Telegram update **сохранена**; «иной ответный кеш» (если есть) — ключ с зависимыми версиями + родителем (A03/A04).
- **SC-16:** REUSE существующих путей (`summary_memory`/`direct_chat_service`/`lore_cache`/`thread_chain`/`search_service`/`lore_stories`/`provenance`/`token_counter`/`TaskSupervisor`); **второй retrieval/EvidenceBundle/reranker/бюджет не создан** (GEN-R19).
- **SC-17:** события `start`+`outcome` через `mca_events` с корректным `reason_code`; стадии/виджет-ID зарегистрированы для `mca-17a`; R17 — без секретов/сырого контекста, `sanitize()` до записи (A27/A48/A53).
- **SC-18:** Δ DDL v18 аддитивна/идемпотентна через реестр `mca-14`; старые ID/таблицы/FTS/vec сохранены; nullable=unknown; повторный прогон no-op; kill-switch env-only default ON, OFF = точный legacy-путь; deploy `DEFERRED_TO_RELEASE` (A28).

## 7. Тесты / деплой / откат / risk

- **Контрактные тесты:** комбинация каналов (каждый канал даёт вклад, не только один); эпизоды-первыми для истории; точная фраза/имя/дата; reranker `ok`-empty ≠ кандидаты; `invalid`/`timeout` → отдельный статус + детерминированный fallback; порядок = оценке; cache key включает provider/model/dims/preprocessing(+endpoint); dim-совпадение при разной identity → miss; active generation mismatch → FTS-only; `upsert_running_summary` CAS (поздняя запись отклонена); отключённый text-replay + сохранённый update-дедуп; полный учёт payload + protected spans (отрицание/ID/дата); `context_version` детерминирован.
- **Интеграционные (end-to-end на обновлённых путях, функции включены; перенос старого unit-теста недостаточен):** **A03** (старый LLM-summary завершается после нового → новая не перезаписана), **A04** (одинаковое «почему?» к разным родителям → разные контексты, нет старого кеш-ответа), **A05** (валидный пустой выбор reranker → все кандидаты **не** вернулись), **A06** (модель embeddings меняется при той же размерности → старые/новые векторы **не** смешаны), **A24** (tools/system + большой обязательный контекст → полный payload помещается, причины сжатия видны).
- **Миграционный smoke v18:** fresh+legacy, идемпотентность, сохранение ID/FTS/vec, `EXPLAIN`-подтверждение индексов.
- **R17/регрессии:** маскирование; retrieval/RAG/identity/dossier Epic 1–3 и `mca-03`/`mca-04a` + Summary Hybrid Epic 2 не регрессируют; kill-switch OFF = точный legacy-путь; pytest ≥ baseline (9712), JS 47/47; `git diff --check`=0. При R3 — `threat-failure-analysis.md` (T-3857).
- **Деплой:** `DEFERRED_TO_RELEASE` (§20). На `mca-release` — backup+read-back, migration smoke v18, effective-state §20.2, manifest (`config changes`: имена kill-switch).
- **Откат:** hot — `MCA_RETRIEVAL_CONTEXT_ENABLED=false`/`MCA_EVIDENCE_BUNDLE_ENABLED=false`/`MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED=false`/`MCA_TYPED_RERANKER_ENABLED=false`/`MCA_SUMMARY_SINGLEFLIGHT_ENABLED=false`/`MCA_CONTEXT_ANSWER_CACHE_ENABLED=false`; cold — `git revert` → `05bc870` (анкер `7165ff7`); DDL v18 аддитивна (новая таблица/колонки безвредны); restore БД — только аварийный сценарий (R18: теги/бэкапы не удаляются).

## 8. Границы и carry-over

- **`mca-04b` (v19+ после брони v18):** фактическая перестройка несовместимого vec-индекса как отдельный resumable job; чтение реестра поколений как вход; `_WINDOW_SQL LIMIT`/full rebuild/dossier — вне mca-07.
- **`mca-05` (Wave 2):** Episode/Story модель расширяет `lore_stories`/`lore_compiler_service`; mca-07 использует фасад, второй каталог запрещён.
- **`mca-09` (Wave 3):** Intent/Decision читают bundle и `context_version`; defer/enum/отправка — не в mca-07.
- **`mca-10b` (Wave 3):** применения случайности через MemoryRetrieval (единый retrieval-контракт); второго retrieval нет.
- **`mca-15` (Wave 2):** ChatStatistics потребляет FTS/exact retrieval; MetricResult/StatsQuery — не в mca-07.
- **`mca-16` (Wave 3):** ExperienceService использует EvidenceBundle **отдельным типом**; lessons не смешиваются с фактами/эпизодами.
- **`mca-20` (Wave 4):** TemporalVerdict зависит от retrieval/EvidenceBundle; freshness-кеш вердиктов — не в mca-07.
- **`mca-11` (Wave 2):** ToolResult/лимиты/расходы; mca-07 только учитывает tool results в бюджете.
- **Carry-over (входы следующих фич):** (1) `mca-04b` — перестройка по generation registry; (2) `mca-17a` — регистрация 5 стадий/виджет-ID, чтение того же `mca_events`; (3) `mca-release` — migration smoke v18, manifest kill-switch.
- **Открытые пункты @Architect (закрыты в этом spec/ADR):** материализация bundle (in-memory), семантика `context_version`, связь с Summary Hybrid/System2, место fingerprint/generation (реестр v18), связь типизированного reranker с существующими функциями (единое ядро + адаптеры).

### 8.1. AMEND 27.09.2026 — адъюдикация carry-over T-3857 (только `plans/**`, R17)

> Триггер: повторный gate T-3857 после rework B-MCA07-1/-2 (High закрыты; pytest 9758/0). Решения ниже **не переписывают** содержание §4/§6 — они фиксируют **границу наполнения** и **зону потребителей**, не расширяя scope.

1. **M-MCA07-2 — ПРИНЯТО как carry-over (наполнение, а не контракт).** Контракт `EvidenceBundle` §11.2 сохраняется **полным** (все поля §4.4). Живой builder mca-07 наполняет подмножество, выводимое без нового I/O, семантического LLM-извлечения и дублирования архива. Владельцы carry-over-полей — первый потребитель, обладающий семантикой:

   | Поле §11.2 | Владелец (первый заполняющий) | Обоснование границы |
   |---|---|---|
   | `ambiguities`, `unknown`, `contradictions` | **`mca-09`** (Intent/Decision, §13; Wave 3) | классификация неоднозначностей/пробелов/противоречий — семантика времени решения; в mca-07 нет без нового LLM-пути |
   | `local_context` | **`mca-05`** (Episode/Story, §9; Wave 2) | «важный локальный контекст» — эпизодный отбор; структурная часть ветки уже несётся в `branch` |
   | `persona`, `interests` | **`mca-18`** (SelfModel/persona, §28; Wave 4) | профиль/интересы персонажа собирает SelfModel/`bot_persona`; в `handle` persona-блок строится **после** bundle → заполнение сейчас означало бы дублирование/новый I/O |

   Дополнительно: `mca-16` (Experience, §25) и `mca-20` (Temporal factcheck, §30) **могут** вкладывать `contradictions`/`interests` при наличии валидированного свидетельства — но как расширение того же единственного bundle, не второй контракт. Инвариант пустого (`not_available`) и требование учитывать новые влияющие поля в `context_version` — §4.4.

2. **L-MCA07-5 — ПРИНЯТО как carry-over (зона потребителей).** `retrieve()` — реализованная единая точка комбинированного retrieval (контракт + каналы + тесты); живой caller в mca-07 отсутствует **осознанно** (R3: не переписывать hot-path сборки контекста в волне данных). Закрепляется как **обязательство потребителей** `mca-09` (primary — retrieval для decision, §13), `mca-10b` (§14.5–14.11), `mca-15` (ChatStatistics, §24):
   - первый потребитель, которому нужен живой retrieval, **обязан** маршрутизировать его через `retrieve()` (или расширить `RetrievalRequest`), а не обходить её;
   - **второй комбинированный retrieval запрещён** (GEN-R19): существующие live-каналы остаются под своими гейтами и не наращиваются новой комбинацией;
   - до подключения `retrieve()` остаётся **поддерживаемым контрактом** (focused unit + real-DB smoke), а не мёртвым кодом;
   - SC-01/SC-02 сохраняют unit+smoke-покрытие; их live-подтверждение переносится в приёмку фич-потребителей (PM фиксирует в их `tasks.md`).

3. **Статус ADR.** `ADR-1027-7` остаётся **Proposed** до успешного повторного gate T-3857 и Merge в `plans/ARCHITECTURE.md` **§99+**; этот AMEND **не** переводит ADR в Accepted.

4. **Binding.** AMEND изменяет `spec.md` и ADR → Spec-Hash/ADR-Hash из review T-3857 (`ACE242D0…`/`7420FBE9…`) **устаревают**; повторный gate обязан пересобрать binding. Код/тесты не менялись; `plans/current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не трогались; R17/R18 соблюдены.
