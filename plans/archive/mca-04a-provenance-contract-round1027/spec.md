# `mca-04a-provenance-contract` — спецификация (Step 2 @Architect, T-3818)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 1** (данные). **Фича-ID:** `mca-04a-provenance-contract`.
- **Тип:** backend/data — типизированные ссылки на источники (SourceRef), связь «утверждение ↔ источник» (EvidenceLink), статусы происхождения, правила восстановления старых записей, единая семантика личного факта, producers/consumers. **P0-предпосылка** для `mca-07` (retrieval/EvidenceBundle) и потребителей `mca-04b`/`05`/`06`/`16`/`18`/`19`/`20`.
- **Источник (IMMUTABLE, R17/R18):** `plans/current_task.md` v1.8 **§8.1** (`:208–226`), **§8.2** (`:228–236`), **§8.3.2** (`:268–280`); §2.3/§4 (`:23`, `:77–101`); §3/§3.1 (`:47`, `:60–75`); §17.1–§17.3 (`:818–844`); §18 (`:856–872`); §19 **A09/A10/A85/A86/A88/A95** (`:890`,`:891`,`:966`,`:967`,`:969`,`:976`); §22 (`:1062–1077`).
- **Задачи:** `tasks.md` T-3816…T-3836. **Приёмки:** A09, A10, A85, A86, A88, A95 (A85/A86/A95 — общая граница с `mca-04b`).
- **ADR:** `adr-1027-6-provenance-contract.md` (D1–D13). **Рамка:** `plans/docs/mca-round1027-arch-frames.md` (§1.2.2, §2, §3, §4).
- **Статус:** Proposed → Accepted по T-3835 (Merge в `plans/ARCHITECTURE.md` **§98+**). **Deploy:** `DEFERRED_TO_RELEASE`.
- **Risk-Level:** **R3** (подтверждено) — provenance и семантика личного факта определяют всю память: ошибка ведёт к ложному подтверждению, чужому субъекту, необратимому «переименованию» позднего подтверждения в оригинал или к удалению памяти. Каскад затрагивает досье, RAG, retrieval, убеждения/парадигмы. Обязателен `threat-failure-analysis.md` (T-3835). Что может поднять риск: если понадобится **несовместимое** изменение `graph_facts` (rebuild таблицы) или потребуется массовый backfill в hot-path. Триггеры понижения до R2: подтверждённая изоляция write-пути, отсутствие переписывания/удаления legacy-строк, A09/A10/A85/A86/A88/A95 на фактическом diff.
- **Baseline (Step 0, используется как данность):** Reviewed-Commit `05bc870`; `APP_VERSION` 2.58.31; SQLite DDL **v16** после волны 1 (`mca-03`); каталог `473/430/448/102/100/21`; канон 12; pytest 9678/0 + JS 47/47; откат `7165ff7`.
- **Зависимости (✅ закрыты):** `mca-14` (реестр `MigrationStep` + книга `schema_migrations`; механизм Δ DDL — `ARCHITECTURE.md` §93), `mca-01` (единый write-механизм `write_transaction`/`serialized()`/`@_serialized_write` — §95), `mca-13` (event-контракт §17.1, `mca_events` — единый durable-стор; вторая телеметрия запрещена — §94), `mca-03` (канон `(chat_id, tg_message_id)`, namespace `import:<export_id>:<fingerprint>`, `source_record_id`, `message_revisions`, роли — §96), `mca-02` (SafeFetcher для внешних материалов — §97).

## 1. Область и исключения

**Входит:**
- Контракт **SourceRef** (`store`/`entity_type`/`entity_id`/`chat_id`/`revision`; для оригинала-сообщения — `tg_message_id`/`dataset_id`); запрет смешения SQLite fact ID / PG row ID / Telegram message ID; связь с контрактом MCA-03 (ссылается, не дублирует).
- Контракт **EvidenceLink** (объект+версия, источник+версия, 5 типов, способ установления, статус проверки, время, версия экстрактора, проверяемое основание, независимость, ключ утверждения).
- **Статусы происхождения** `original`/`reconstructed_support`/`tentative`/`unknown` + **отдельные** поля конфликтности/актуальности/покрытия; запрет самоподтверждения бота; отделение предпочтений персонажа от фактов.
- **Правила восстановления §8.2** (прямое → точный/смысловой поиск; reply/контекст; проверки автора/объекта/времени/отрицания/цитаты/шутки/пересказа/актуальности; вектор — кандидат; покрытие по каждому утверждению; ambiguous → `tentative`; неподтверждённое не удалять; `reconstructed_support` не переименовывать в `original`).
- **Единая семантика личного факта §8.3.2** (speaker/author, subject, упомянутые, источник; устойчивый ID; unresolved для импорта без TG ID; self-report; третье лицо — атрибутированное утверждение).
- **FIX-точки 04a** из §8.3.1: п.1 (`_memorize_direct_reply`: target=asker → субъект-атрибуция), п.2 (`get_persona_card`/`get_user_context_facts`: subject-scope), п.3 (Layer B `person_facts` сохраняются независимо от портрета), контрактная часть п.5 (локальные номера evidence → постоянные SourceRef + валидатор `filter_layer_a_candidates`).
- Producer/consumer-пути на едином контракте; Δ DDL **v17** через реестр `mca-14`; события MCA-13/стадии MCA-17a; R17-маскирование; kill-switch; тесты/деплой/откат.

**Не входит (границы):**
- **Полная пересборка досье, job-состояния, `_WINDOW_SQL` LIMIT, budget-exhaustion→done, `upsert_generated_dossier`** — `mca-04b` (п.4/6/7 §8.3.1 и врезка п.5 в chunk-пайплайн; §8.3.3–8.3.4).
- **EvidenceBundle, retrieval, reranker, бюджет контекста, embedding fingerprint** — `mca-07` (потребляет SourceRef).
- **Episode/Story модель и `lore_stories`** — `mca-05` (расширяет SourceRef/EvidenceLink).
- **Парадигмы/сон, возраст/актуальность исторических кандидатов** — `mca-06` (потребляет типизированные ссылки/версии).
- **ExperienceEpisode/Lesson** — `mca-16` (отдельный контракт, не смешивается с фактами/парадигмами).
- **SelfModel/TraitObservation/BehaviorRule/BehaviorFrame, `subject_entity_id`/`speaker_entity_id`/perspective/`memory_kind`** — `mca-18` (расширяет MCA-04a; второй контракт субъекта запрещён).
- **MediaAsset/MediaAnalysis, bytes/MIME, vision, «так написано ≠ верно»** — `mca-19`.
- **ClaimEnvelope/TemporalVerdict, режимы времени, freshness-кеш** — `mca-20`.
- **UI-витрина источников, полная матрица процессов, виджет** — `mca-17a`/`mca-17c`/`mca-12`; MCA-04a только регистрирует стадии/виджет-ID и эмитирует события.
- **Изменение `pg_db.py`** — вне diff (GEN-R4; SQLite и PG сохраняются, PG — no-op).
- **Исправление отпечатка namespace `abspath|size` (L-MCA03-8)** — не в 04a (см. §8).

### 1.1. Фактическое состояние baseline (сверено с рабочей веткой; REUSE §3)

- `graph_facts` (`services/database.py:607–624`) хранит `id/chat_id/fact/origin/expires_at/created_at/target_user/tg_message_id/forward_from` (+ v8-колонки `subject/object/message_timestamp/importance/kind/source_ids/belief_meta/supersedes/weight/status/last_confirmed_at`). `origin` — **CHECK-ограниченный** набор (`chat_history|search_fact|youtube_content|web_content|bot_direct_reply|voice_transcript|video_transcript`). `target_user` — **канон-имя**, не устойчивый ID. Provenance-поля/ссылки отсутствуют. **Разрыв §8.1/§8.3.2 присутствует.**
- `_memorize_direct_reply` (`services/direct_chat_service.py:2168–2240`) передаёт `target_user=asker_canon` (обе ветки self-awareness), затем `_reassign_fact_owners` (`:2242–2286`) переназначает владельца по эвристике subject/object-имени (`_fact_owner_canon`). Это **не** проверка того, о ком утверждение. **Разрыв §8.3.1 п.1 присутствует.**
  - ⚠️ **Расхождение ТЗ↔код:** задачи называют функцию `_memorize_direct_facts`; фактическое имя — `_memorize_direct_reply` (факты пишутся через `memory.memorize_facts` → `summary_memory._memorize_facts_inner`). Объём требования не меняется.
- `_memorize_facts_inner` (`services/summary_memory.py:2037–2241`) пишет переданный `target_user` каждой извлечённой паре subject/predicate/object. **Разрыв §8.3.1 п.1 присутствует.**
- `get_persona_card` (`services/database.py:5769–5796`) и `get_user_context_facts` (`:5798–5820`) отдают все `confirmed` по `target_user` (имя) без доказанной персональной принадлежности. **Разрыв §8.3.1 п.2 присутствует.** Потребители: `direct_chat_service.py:2791`, `tool_router.py:1423/1444/1470/1497`, `image_context_memory.py:533`, `web/api/chat_lore.py:865` (UI) — то же загрязнение в RAG/UI/`get_user_context` (A85).
- `_classify_dossier_multilayer` (`services/lore_worker.py:636–716`) и `_classify_chunked_user` (`:808–875`) передают `person_facts` в Layer B-промпт, но пишут только портреты (`_write_generated_portraits`) и мемы (`_write_chat_memes`); **отдельного сохранения `person_facts` нет**. **Разрыв §8.3.1 п.3 присутствует.** Прецедент хранения: мемы пишутся как `graph_facts` c `origin='chat_history'` + `status='chat_meme'` + `belief_meta.source='dossier'` (нулевой DDL) — REUSE-паттерн для person_facts.
- `_extract_chunk` (`:877–903`) возвращает `person_facts` с локальными номерами `evidence` (нормализованы в `1..N` в `parse_layer_a`, `services/dossier_prompts.py:277/309`), без перевода в постоянные SourceRef; `filter_layer_a_candidates` (`services/dossier_prompts.py:335–379`) проверяет только непустой `evidence` и `target` в ростере — **не** проверяет соответствие утверждения источнику и верхнюю границу номера строки. **Разрыв §8.3.1 п.5 (контрактная часть) присутствует.**
  - ⚠️ **Расхождение ТЗ↔код:** `filter_layer_a_candidates` живёт в `services/dossier_prompts.py`, а не в `lore_worker.py` (задача T-3826 называет его в контексте `lore_worker`).
- `_WINDOW_SQL ... LIMIT` и `start_dossier_rebuild` (bounded window), budget-exhaustion→`done`, `upsert_generated_dossier` (затирание портрета) — **зона `mca-04b`** (п.4/6/7), подтверждается, но в 04a не чинится.
- REUSE-контракты уже на месте: `source_ids` (JSON id-источников на belief/paradigm — `dream_worker.py:768/954/...`), `graph_facts.tg_message_id` (`insert_graph_fact` — `database.py:3868`), `message_source_records.source_record_id`/`message_revisions` (`mca-03`, §96), `write_transaction`/`serialized()` (`mca-01`), `emit_mca_event`/`mca_events` (`mca-13`), `MigrationStep` (`mca-14`), `reply`-цепочки `services/thread_chain.py`.

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA04-01 — типизированный SourceRef; запрет смешения SQLite fact ID / PG row ID / TG message ID | §8.1 `:212` | SC-01, SC-02, SC-03 | T-3821, T-3822 |
| REQ-MCA04-02 — EvidenceLink: объект+версия, источник+версия, 5 типов, способ, статус, время, версия экстрактора, основание | §8.1 `:214–222` | SC-04, SC-05 | T-3822, T-3823, T-3826 |
| REQ-MCA04-03 — статусы `original/reconstructed_support/tentative/unknown` + отдельные поля; запрет самоподтверждения бота; предпочтения отделены | §8.1 `:224–226` | SC-06, SC-07 | T-3822, T-3826, T-3827 |
| REQ-MCA04-04 — правила восстановления §8.2 (direct→search, reply, проверки, вектор=кандидат, coverage per assertion, ambiguous→tentative, no-rename, no-delete) | §8.2 `:232–236` | SC-08, SC-09, SC-10 | T-3828, T-3829 |
| REQ-MCA04-05 — единая семантика личного факта §8.3.2; FIX 04a; граница с `mca-04b`; второй контракт запрещён | §8.3.2 `:270–278` | SC-11, SC-12, SC-13 | T-3823, T-3824, T-3825, T-3826 |
| REQ-MCA04-06 — SQLite и PG сохраняются; межбазовые ссылки типизированы; PG no-op | §2.3/§4 `:23`,`:77` | SC-02, SC-14 | T-3819, T-3821, T-3822 |
| REQ-MCA04-07 — REUSE `source_ids`/`graph_facts`/`source_record_id`/`message_revisions`; не вторая реализация/контракт | §3/§3.1 `:47`,`:60–75` | SC-13, SC-14 | T-3823, T-3824, T-3828 |
| REQ-MCA04-08 — собрать фактические ориентиры заполненности ID/пересечений импорт↔live | §3 `:49–53` | SC-14 | T-3816, T-3823 |
| REQ-MCA04-09 — аддитивная идемпотентная Δ DDL через реестр `mca-14`; старые ID/таблицы сохранены; nullable=unknown | §18 `:864–866` | SC-15 | T-3821, T-3829 |
| REQ-MCA04-10 — события MCA-13 (`start`+`outcome`, `reason_code`), стадии/виджет-ID MCA-17a; R17 | §17.1–§17.3 `:818–844`; §27.1 | SC-16, SC-17 | T-3832, T-3833 |
| REQ-MCA04-11 — kill-switch env-only default ON, OFF=паритет baseline; тесты; deploy `DEFERRED_TO_RELEASE` | §18 `:872`; §2.4–2.5 | SC-18 | T-3830, T-3831, T-3833, T-3834 |

**Орфан-REQ нет;** T-3816/3817/3820/3835/3836 — процессные (baseline/PM/сверка/ревью-merge/архив). Каждый `REQ-MCA04-01…11` покрыт ≥1 задачей; каждая задача — REQ/SC либо процессная.

## 3. Наблюдаемое поведение и отказы

- У производного утверждения (факт/эпизод/убеждение/парадигма/вывод досье) видно, из чего оно получено: список типизированных SourceRef; либо честный `unknown` — без выдуманной ссылки.
- Оригинальный источник, найденное **позже** подтверждение, упоминание и противоречие различимы (по `link_type`), и позднее подтверждение **никогда** не отображается как оригинал.
- Одно утверждение может одновременно иметь сохранённый источник и быть **устаревшим**: «есть источник», «есть конфликт», «актуально/устарело» и «покрытие» — **разные** наблюдаемые поля.
- Собственный ответ бота **не** подтверждает факт о человеке; личное предпочтение персонажа **не** смешивается с фактом о человеке.
- Личный факт относится к **субъекту** (устойчивый ID), а не к спрашивающему; общие новости/знания/этимология/шутка/мем/цитата/пересылка/ответ бота не становятся личным фактом; третье лицо — атрибутированное утверждение; самоотчёт помечен «по собственным словам».
- При восстановлении: прямое сохранённое происхождение имеет приоритет; поиск/контекст дают `reconstructed_support`/`tentative`; вектор — **кандидат**, не доказательство; при неоднозначности запись остаётся `tentative`; не найденный источник **не** удаляет память.
- FAILURE-семантика: ошибка резолва/валидации evidence → кандидат сохраняется `tentative` с диагностируемой причиной; ошибка БД → fail-open без ложного `original`; OFF kill-switch → точный legacy-путь.

## 4. Интерфейсы и контракты

### 4.1. SourceRef (D1/D2)
- **Поля:** `store` ∈ {`sqlite`,`postgres`,`telegram`,`external`,`legacy`}; `entity_type` (напр. `message`,`graph_fact`,`belief`,`paradigm`,`episode`,`story`,`dossier`,`user`,`media_asset`,`unknown`); `entity_id` — **непрозрачная** строка в пространстве (`store`,`entity_type`); `chat_id` (логическая область; `NULL`=глобально/неизвестно); `revision` (версия сущности; `NULL`=честный unknown).
- **Для оригинала-сообщения дополнительно:** `tg_message_id` (заполняется **только** когда сущность — Telegram-сообщение) и `dataset_id`/`source_record_id` (namespace/occurrence, когда существуют) — из контракта MCA-03. `resolution` ∈ {`resolved`,`unresolved`,`unknown`}: импорт без TG ID → `unresolved` (**стабильный `entity_id` источника**, не выдуманный Telegram ID).
- **Запрет смешения:** `entity_id` — локальный ID **внутри** (`store`,`entity_type`); SQLite fact ID, PG row ID и Telegram message ID **не** взаимозаменяемы и **не** сравниваются между собой. Для сообщения канонический адрес — пара `(chat_id, tg_message_id)` (MCA-03), внутренний `smart_messages.id` — `entity_id` при `store='sqlite'`,`entity_type='message'`; `tg_message_id` — отдельное поле, никогда не подменяется внутренним ID.
- **Хранение:** реестр `mca_source_refs` (дедуп по `(store, entity_type, entity_id, chat_id, revision)`), ссылка — по `source_ref_id`. SourceRef **ссылается** на контракты MCA-03/Epic 1–3, не копирует их.
- **Типизация межбазовых ссылок (GEN-R4):** ссылка на PG-сущность — `store='postgres'`; `pg_db.py` не меняется (PG — no-op, только адрес).

### 4.2. EvidenceLink (D3/D4)
- **Поля:** `subject_ref_id` (объект-утверждение) + его `revision`; `source_ref_id` (источник) + его `revision`; `link_type` ∈ {`derived_from`,`supports`,`contradicts`,`mentions`,`supersedes`}; `method` (способ установления) ∈ {`direct_reference`,`metadata`,`exact_search`,`semantic_search`,`reply_context`,`thread_context`,`migration_backfill`,`manual`,`unknown`}; `verification` (статус проверки) ∈ {`verified`,`rejected`,`tentative`,`unknown`}; `independence` ∈ {`independent`,`self_referential`,`unknown`}; `claim_key` (ключ утверждения внутри объекта; `NULL`=всё утверждение); `extractor_version`; `basis` (краткое проверяемое основание, R17-safe, без скрытого CoT); `checks_json` (результаты проверок автора/объекта/времени/отрицания/цитаты/шутки/пересказа/актуальности; коды/enum); `established_at`; `created_at`.
- **Семантика типов:** `derived_from` — сохранённое происхождение при создании; `supports` — подтверждение (в т.ч. найденное позже); `contradicts` — противоречие конкретному утверждению; `mentions` — тематическая связь, **не** доказательство; `supersedes` — новая версия/состояние заменяет актуальность предыдущего.
- **Независимость (D4):** только `independence='independent'` + `verification='verified'` связи `derived_from`/`supports` участвуют в подтверждении. Ответы бота (origin `bot_self_reply`/`bot_direct_reply`) дают `independence='self_referential'` и **не** могут подтверждать факты о людях. Два вывода из одного события → общий SourceRef, **не** два независимых доказательства (A10).
- **Покрытие по утверждению:** `claim_key` различает утверждения внутри многосоставного воспоминания; одна подходящая фраза **не** подтверждает весь абзац.

### 4.3. Статусы происхождения и отдельные поля (D5)
- `origin_status` ∈ {`original`,`reconstructed_support`,`tentative`,`unknown`} — **только** про происхождение; `original` присваивается **только** из сохранённого при создании прямого источника; восстановление даёт `reconstructed_support`; неоднозначность — `tentative`; нет материала — `unknown`.
- **Отдельные поля (не взаимоисключающие значения статуса):** `conflict_status` ∈ {`none`,`conflicting`,`resolved`,`unknown`}; `freshness_status` ∈ {`current`,`superseded`,`stale`,`unknown`}; `coverage_status` ∈ {`full`,`partial`,`none`,`unknown`} + `coverage_covered`/`coverage_total` (nullable=unknown). Одно утверждение может иметь сохранённый источник **и** быть устаревшим.
- **Запрет самоподтверждения:** собственные ответы бота не становятся независимым подтверждением; `self_referential`-связи не поднимают `origin_status` и не снимают `tentative`.
- **Предпочтения персонажа:** личные предпочтения (subject = бот) маркируются `assertion_kind='preference'` + `attribution_method` self-report/`bot_self_reply` и **не** попадают в личные факты участников; subject-scope-читатели исключают субъект-бота.
- **Хранение:** `mca_provenance_status` (1:1 с объектным SourceRef).

### 4.4. Правила восстановления старого (§8.2) (D6)
- **Сохранить все старые записи и их ID**; восстановление аддитивно и идемпотентно.
- **Порядок:** (1) прямые ссылки/метаданные → `original` (если сохранены при создании) или `derived_from`; (2) точный поиск → `exact_search`; (3) смысловой поиск → `semantic_search`; (4) подъём окружающей переписки и reply-цепочки → `reply_context`/`thread_context` (REUSE `services/thread_chain.py`, вторую цепочку не плодить).
- **Проверки (fail-closed для `original`):** автор, объект высказывания, время, отрицание, цитирование, шутка/сарказм, пересказ, актуальность. Результат фиксируется в `checks_json`; непройденная обязательная проверка → `verification='rejected'` или `tentative`, но **не** `original`.
- **Вектор — кандидат, не доказательство:** векторный поиск даёт лишь candidate-связь `tentative` до текстовой/структурной проверки.
- **Покрытие по каждому утверждению:** нельзя одной подходящей фразой подтверждать весь абзац; `coverage_status='partial'` при покрытии не всех `claim_key`.
- **ambiguous → tentative**, не выдумывать оригинальные ID.
- **`reconstructed_support` не переименовывать в `original`**; не найденный источник ≠ ложная запись; **не удалять** автоматически неподтверждённую память. Ложный `original` не создаётся (A09).

### 4.5. Единая семантика личного факта (§8.3.2) (D7)
- Разделяются: `speaker`/author (автор сообщения — `user_id`/`speaker_author_id` из MCA-03), `subject` (о ком — субъектный SourceRef), упомянутые участники, источник утверждения.
- Субъект — **устойчивый ID** в области чата (SourceRef `entity_type='user'`, `store='telegram'`, `entity_id=user_id`); имя/алиас — только отображение/резолв. Импорт без TG ID → стабильный источник + `resolution='unresolved'`, **без выдуманного** Telegram ID. Одноимённые **не** объединяются; упоминание имени — **не** доказательство.
- Личный факт хранит: структурированное утверждение, `subject_ref_id`, `assertion_kind` (тип), source refs с версиями, автора сообщения (`speaker_author_id`), раздельно время события/сообщения/извлечения (`message_timestamp`/`tg_message_id`/`created_at` из MCA-03), `attribution_method` (способ атрибуции), статус подтверждения (`graph_facts.status`), `extractor_version`.
- **Типы:** `assertion_kind` ∈ {`biographical`,`preference`,`event`,`relation`,`opinion`,`world_knowledge`,`unknown`}; `attribution_method` ∈ {`self_report`,`third_party`,`direct_evidence`,`bot_self_reply`,`world_knowledge`,`unknown`}.
- **Self-report** («по собственным словам») — допустим как факт с пометкой (`attribution_method='self_report'`), одно свидетельство допустимо для личного предпочтения; двух независимых свидетелей не требовать.
- **Третье лицо** — `third_party` атрибутированное утверждение со статусом, **не** безусловная биография.
- Общие новости/знания (`world_knowledge`), запрос, шутка, мем, цитата, пересылка, предположение и ответ бота **не** становятся подтверждённым личным фактом спрашивающего (A85). Местоимения разрешать по автору/reply/локальному контексту; при неоднозначности — `unresolved`, не назначать автора субъектом по умолчанию.
- **Контракт един:** используется SourceRef/EvidenceLink MCA-04, не параллельный контракт личного факта (`mca-18` расширяет, не заменяет).

### 4.6. FIX-точки 04a (§8.3.1 п.1/2/3 + контракт п.5) (D8)
- **п.1 — `_memorize_direct_reply`:** убрать безусловный `target_user=asker_canon`; факт получает `subject_ref` из разобранного утверждения + reply/автора/локального контекста; `attribution_method`/`assertion_kind`; `asker` — только **speaker/владелец-по-умолчанию** при отсутствии доказанного субъекта, но **не** субъект (и не помечается `original`). Эвристика `_fact_owner_canon`/`_reassign_fact_owners` заменяется валидируемой субъект-атрибуцией (fail-open → `unresolved`). Гейт `MCA_FACT_ATTRIBUTION_ENABLED`.
- **п.2 — `get_persona_card`/`get_user_context_facts`:** subject-scope по `subject_ref_id` (устойчивый ID) вместо `target_user`-имени; исключить `world_knowledge` и `self_referential`/бот-подтверждения. **Одинаково** в UI (`web/api/chat_lore.py`), `get_user_context` (`tool_router.py`/`image_context_memory.py`) и RAG (A85). Legacy строки без `subject_ref_id` — честный unknown, не «все confirmed по имени».
- **п.3 — Layer B `person_facts`:** `_classify_dossier_multilayer`/`_classify_chunked_user` сохраняют **валидированные** person_facts как личные факты (`subject_ref_id` + SourceRef) **независимо** от успеха синтеза портрета (A86). Прецедент хранения — REUSE-паттерн мемов (`origin='chat_history'`, маркер в новых полях/`belief_meta`); **`origin` CHECK не расширяется** (аддитивность). Невалидированные кандидаты сохраняются `tentative`/`unconfirmed`, **не** удаляются и **не** повышаются до `confirmed`.
- **п.5 (контрактная часть) — local evidence → постоянные SourceRef:** сразу после каждого чанка локальные номера `evidence` преобразуются в постоянные SourceRef (окно → `(chat_id, tg_message_id)`/`smart_messages.id` + `revision`); одинаковый номер в разных чанках **не** обозначает один источник. `filter_layer_a_candidates` усиливается до проверки: существование сообщения и версии, чат, **диапазон номера строки в пределах окна чанка**, соответствие субъекта и утверждения (subject/источник/row-bound). Ошибки → `evidence_invalid`. **Фактическая врезка в chunk-пайплайн** — `mca-04b`.
- Все исправления — через существующие пути (`insert_graph_fact`/`serialized()`/`write_transaction`), без второй реализации; если дефект уже устранён в рабочей ветке — подтверждается тестом (GEN-R19). По факту сверки **все четыре разрыва присутствуют** (см. §1.1).

### 4.7. Producers / consumers / REUSE (D9)
- **Producers:** `summary_memory._memorize_facts_inner`, `direct_chat_service._memorize_direct_reply`, `lore_worker` (Layer A/B, мемы/портреты), `dream_worker` (belief/paradigm `source_ids`), импорт/backfill. Каждый новый факт/эпизод/убеждение/парадигма/вывод досье пишет SourceRef/EvidenceLink через **существующие** пути; при отсутствии материала — явный `unknown`; внешние загруженные материалы — через SafeFetcher (`mca-02`) и SourceRef `store='external'`.
- **Consumers:** `get_persona_card`/`get_user_context_facts`, `tool_router` (RAG/retrieval), `image_context_memory`, `web/api/chat_lore.py` (UI), `direct_chat_service` — читают SourceRef/статусы, субъект-ориентированно; legacy/unknown корректны.
- **REUSE (не дублировать):** `source_ids` → типизируются в SourceRef (`derived_from`), не второй store; `graph_facts` origin/`tg_message_id`/`subject`/`object`; `message_source_records.source_record_id`/`message_revisions` (MCA-03); `thread_chain`; `MigrationStep`; `write_transaction`; `emit_mca_event`/`mca_events`. Новый параллельный контракт идентичности/provenance **запрещён**.

### 4.8. Наблюдаемость и R17 (D12)
- События `start`+терминальный `outcome` через REUSE `emit_mca_event`/`mca_events` (второй store запрещён); стадия `provenance`; регистрация стадий/виджет-ID для `mca-17a`.
- **Расширение словаря `reason_code`:** `provenance_linked`, `provenance_unresolved`, `evidence_invalid`, `provenance_reconstructed`, `provenance_conflict` (реестр MCA-13, расширяемый).
- R17: в логи/события — только id/коды/`error_type`; `basis` — краткое проверяемое основание (без скрытого CoT); `checks_json` — коды/enum; `sanitize()` до записи во все каналы; SourceRef вместо сырого контекста; секреты/сырые сообщения не логируются.

## 5. Δ DDL (санкция) / Δ каталога / kill-switch

**Δ DDL = v17** (аддитивно, идемпотентно, через реестр `mca-14`; PG — no-op; старые таблицы/ID не переименовываются и не удаляются). Точные объекты:

```sql
-- Реестр типизированных SourceRef
CREATE TABLE IF NOT EXISTS mca_source_refs (
    source_ref_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    store            TEXT NOT NULL,     -- sqlite|postgres|telegram|external|legacy
    entity_type      TEXT NOT NULL,     -- message|graph_fact|belief|paradigm|episode|story|dossier|user|media_asset|unknown
    entity_id        TEXT NOT NULL,     -- OPAQUE id в (store, entity_type); НЕ сравнивать между store
    chat_id          INTEGER,           -- логическая область чата; NULL = глобально/неизвестно
    revision         TEXT,              -- версия сущности (mca-03 revision_no и т.п.); NULL = unknown
    tg_message_id    INTEGER,           -- ТОЛЬКО для оригинала-сообщения
    dataset_id       TEXT,              -- namespace/export id (mca-03)
    source_record_id TEXT,              -- occurrence id (mca-03)
    resolution       TEXT,              -- resolved|unresolved|unknown
    created_at       INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_source_refs_dedup
    ON mca_source_refs(store, entity_type, entity_id,
                       COALESCE(chat_id, -1), COALESCE(revision, ''));
CREATE INDEX IF NOT EXISTS idx_mca_source_refs_chat_type
    ON mca_source_refs(chat_id, entity_type);

-- Связь «объект ↔ источник»
CREATE TABLE IF NOT EXISTS mca_evidence_links (
    link_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_ref_id    INTEGER NOT NULL,  -- объект (производное) → mca_source_refs
    source_ref_id     INTEGER NOT NULL,  -- источник → mca_source_refs
    link_type         TEXT NOT NULL,     -- derived_from|supports|contradicts|mentions|supersedes
    method            TEXT NOT NULL,     -- direct_reference|metadata|exact_search|semantic_search|reply_context|thread_context|migration_backfill|manual|unknown
    verification      TEXT NOT NULL,     -- verified|rejected|tentative|unknown
    independence      TEXT NOT NULL,     -- independent|self_referential|unknown
    claim_key         TEXT,              -- ключ утверждения внутри объекта; NULL = всё утверждение
    extractor_version TEXT,
    basis             TEXT,              -- краткое проверяемое основание (R17-safe; без CoT)
    checks_json       TEXT,              -- author/object/time/negation/quote/joke/retelling/actuality (коды/enum)
    established_at    INTEGER NOT NULL,
    created_at        INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_evidence_links_dedup
    ON mca_evidence_links(subject_ref_id, source_ref_id, link_type,
                          COALESCE(claim_key, ''));
CREATE INDEX IF NOT EXISTS idx_mca_evidence_links_subject
    ON mca_evidence_links(subject_ref_id, link_type);
CREATE INDEX IF NOT EXISTS idx_mca_evidence_links_source
    ON mca_evidence_links(source_ref_id);

-- Происхождение/конфликтность/актуальность/покрытие объекта (1:1 с объектным SourceRef)
CREATE TABLE IF NOT EXISTS mca_provenance_status (
    object_ref_id     INTEGER PRIMARY KEY,
    origin_status     TEXT NOT NULL,     -- original|reconstructed_support|tentative|unknown
    conflict_status   TEXT NOT NULL,     -- none|conflicting|resolved|unknown
    freshness_status  TEXT NOT NULL,     -- current|superseded|stale|unknown
    coverage_status   TEXT NOT NULL,     -- full|partial|none|unknown
    coverage_covered  INTEGER,           -- NULL = unknown
    coverage_total    INTEGER,           -- NULL = unknown
    extractor_version TEXT,
    updated_at        INTEGER NOT NULL
);

-- Личный факт: субъект/атрибуция/тип/экстрактор (аддитивные nullable)
ALTER TABLE graph_facts ADD COLUMN subject_ref_id INTEGER;      -- → mca_source_refs (субъект); NULL = unresolved/unknown
ALTER TABLE graph_facts ADD COLUMN attribution_method TEXT;     -- self_report|third_party|direct_evidence|bot_self_reply|world_knowledge|unknown
ALTER TABLE graph_facts ADD COLUMN assertion_kind TEXT;         -- biographical|preference|event|relation|opinion|world_knowledge|unknown
ALTER TABLE graph_facts ADD COLUMN speaker_author_id INTEGER;   -- автор сообщения-источника (mca-03 user_id)
ALTER TABLE graph_facts ADD COLUMN extractor_version TEXT;
ALTER TABLE graph_facts ADD COLUMN provenance_channel TEXT;     -- live|dossier_layer_a|dossier_layer_b|dream|import|unknown

CREATE INDEX IF NOT EXISTS idx_graph_facts_subject_ref
    ON graph_facts(subject_ref_id, status);
```

**Legacy/совместимость:**
- `graph_facts` `origin` CHECK **не расширяется**; dossier person_facts пишутся `origin='chat_history'` + `provenance_channel='dossier_layer_a'`/`attribution_method` (нулевой риск rebuild). Все новые колонки — nullable (честный unknown).
- Старые `id`/`timestamp`/FTS/`source_ids`/`tg_message_id` сохраняются; повторный прогон шага — no-op (guard `sqlite_master`/`PRAGMA table_info`).
- **Backfill v17 (bounded/resumable, только прямые ссылки):** для существующих `graph_facts` создаётся объектный SourceRef (`store='sqlite'`,`entity_type='graph_fact'`,`entity_id=CAST(id AS TEXT)`); `origin_status='unknown'` по умолчанию; `original` **только** при сохранённом прямом источнике (`tg_message_id IS NOT NULL` → SourceRef `store='sqlite'`,`entity_type='message'`,`chat_id`,`tg_message_id` + `derived_from` + `verification='verified'`); при иных/отсутствующих метаданных — `unknown`. Существующие `source_ids` belief/paradigm → `derived_from` SourceRefs. **Семантический поиск в backfill не выполняется** (иначе ложный `original` — A09). Guard повторного прогона — отсутствие объектного SourceRef.
- **Индексы — только под подтверждённый `EXPLAIN QUERY PLAN`** (реальные запросы: субъект-скоуп `graph_facts(subject_ref_id,status)`; сбор evidence по объекту `mca_evidence_links(subject_ref_id,link_type)`; «что выведено из источника» `(source_ref_id)`; резолв/дедуп `mca_source_refs`). «Все комбинации» запрещены.

**Δ каталога = 0.** Все рубильники — env-only `ClassVar`; `param_catalog.py` вне diff; F8 (ADR-1026-2) **NOT_APPLICABLE**.

**Kill-switch (утверждены, env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline):**
- `MCA_PROVENANCE_ENABLED` — ON: типизированные SourceRef/EvidenceLink/статусы создаются и читаются; OFF: legacy-путь (новые записи/связи/статусы не создаются; `source_ids`/`tg_message_id` как есть).
- `MCA_FACT_ATTRIBUTION_ENABLED` — ON: субъект-атрибуция личных фактов + subject-scope читателей + сохранение Layer B person_facts; OFF: legacy-атрибуция (`target=asker`, name-scope, person_facts не сохраняются) — паритет §8.3.2-baseline.
- `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` — ON: восстановление старых записей (backfill-recovery/read-time); OFF: восстановление не запускается (прямо сохранённое происхождение по-прежнему фиксируется).
- **Приоритет/совместимость:** `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` и `MCA_FACT_ATTRIBUTION_ENABLED` инертны при `MCA_PROVENANCE_ENABLED=OFF`; существующие `MCA_MESSAGE_IDENTITY_ENABLED`/`MCA_MESSAGE_REVISION_TRACKING_ENABLED`/`MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED`/`MULTILAYER_EXTRACTION_ENABLED`/`GRAPH_RAG_ENABLED` **уважаются, не дублируются**. OFF фиксируется в release-manifest/логе (причина/время/план, R17-safe); релиз — со всеми ON.

## 6. Приёмочные сценарии (SC)

- **SC-01:** SourceRef типизирован (`store`/`entity_type`/`entity_id`/`chat_id`/`revision`); `entity_id` — opaque в (store, entity_type) (A88).
- **SC-02:** оригинал несёт `tg_message_id`/`dataset_id` там, где они существуют; SQLite fact ID, PG row ID и TG message ID не смешиваются и не сравниваются; PG — no-op (A88).
- **SC-03:** SourceRef **ссылается** на контракт MCA-03 (`(chat_id, tg_message_id)`/namespace/`source_record_id`/revision) и не создаёт второй контракт идентичности.
- **SC-04:** EvidenceLink несёт объект+версию, источник+версию, тип, способ, статус проверки, время, версию экстрактора, проверяемое основание (A09/A86).
- **SC-05:** типы `derived_from`/`supports`/`contradicts`/`mentions`/`supersedes` различимы; `mentions` и вектор — не доказательство (A09/A10).
- **SC-06:** статусы `original/reconstructed_support/tentative/unknown` + **отдельные** `conflict_status`/`freshness_status`/`coverage_*`; одно утверждение может иметь источник и быть устаревшим (A09/A10).
- **SC-07:** собственный ответ бота не подтверждает факты о людях (self-referential ≠ подтверждение); предпочтения персонажа маркируются отдельно от фактов (A10/A85).
- **SC-08:** восстановление: direct→exact→semantic, reply/контекст; проверки автора/объекта/времени/отрицания/цитаты/шутки/пересказа/актуальности; вектор — кандидат (A09/A95).
- **SC-09:** покрытие по **каждому** утверждению (`claim_key`); ambiguous → `tentative`; одна фраза не подтверждает абзац (A09/A10/A95).
- **SC-10:** старые записи/ID сохранены; `reconstructed_support` **не** переименовывается в `original`; неподтверждённое не удаляется; ложный `original` не создаётся (A09/A95).
- **SC-11:** разделены speaker/author, subject, упомянутые, источник; субъект — устойчивый ID; импорт без TG ID → stable source ID + `unresolved`; одноимённые не сливаются; упоминание имени — не доказательство (A85/A86/A95).
- **SC-12:** self-report помечен; третье лицо — атрибутированное утверждение, не безусловная биография (A85/A86).
- **SC-13:** FIX 04a — target=asker→субъект; consumers subject-scope; Layer B person_facts сохранены независимо от портрета; локальные evidence→постоянные SourceRef; `filter_layer_a_candidates` валидирует subject/source/row-bound; неподтверждённое не повышено до `confirmed` (A85/A86/A88).
- **SC-14:** REUSE `source_ids`/`graph_facts`/`source_record_id`/`message_revisions`; второй контракт идентичности/provenance **не** создан; собраны ориентиры заполненности ID (A88).
- **SC-15:** Δ DDL v17 аддитивна/идемпотентна через реестр `mca-14`; старые ID/таблицы/FTS сохранены; nullable=unknown; повторный прогон — no-op (A87/A88).
- **SC-16:** события `start`+`outcome` через `mca_events` с корректным `reason_code`; стадии/виджет-ID зарегистрированы для `mca-17a` (A27).
- **SC-17:** R17 — логи/события без секретов/сырого контекста; `basis`/`checks_json` — коды; `sanitize()` до записи (A53).
- **SC-18:** kill-switch env-only default ON; OFF = точный legacy-путь; регрессии identity/dossier/RAG Epic 1–3 и MCA-03 зелёные; deploy `DEFERRED_TO_RELEASE` (A28/A87).

## 7. Тесты / деплой / откат / risk

- **Контрактные тесты:** SourceRef типизирован; SQLite/PG/TG ID не смешиваются; EvidenceLink 5 типов + полный набор полей; статусы + раздельные поля; невозможность смешения источников двух чанков (одинаковый локальный номер в разных чанках); отклонение несуществующей строки/out-of-range; subject по устойчивому ID; bot-self-response ≠ подтверждение; `reconstructed_support` не становится `original`; `off` kill-switch = legacy.
- **Интеграционные (end-to-end на обновлённых путях, функции включены):** A09 (старый факт + похожий текст → нет ложного `original`, окружение проверено), A10 (два вывода из одного события ≠ два доказательства), A85 (общие знания/новости/этимология/запрос-ответ бота → не в личные факты; одинаково в UI/`get_user_context`/RAG), A86 (валидированный факт с subject ID + SourceRef сохранён при сбое Layer B), A88 (Evidence=1 в двух чанках / несуществующая строка / одноимённые), A95 (досье Лехи/Васи/Ярика на проверяемой выборке разных периодов; пропуски и precision/recall; длина текста — не критерий). **Перенос старого unit-теста недостаточен.**
- **Миграционный smoke v17:** fresh+legacy, идемпотентность, сохранение ID/FTS, backfill no-op при повторе, `EXPLAIN`-подтверждение индексов.
- **R17/регрессии:** маскирование; identity/dossier/RAG Epic 1–3 и MCA-03 не регрессируют; pytest ≥ baseline; `git diff --check`=0. При R3 — `threat-failure-analysis.md` (Blocks G/H, T-3835).
- **Деплой:** `DEFERRED_TO_RELEASE` (§20). На `mca-release` — backup+read-back, migration smoke v17, effective-state §20.2, manifest (`config changes`: имена kill-switch).
- **Откат:** hot — `MCA_PROVENANCE_ENABLED=false`/`MCA_FACT_ATTRIBUTION_ENABLED=false`/`MCA_EVIDENCE_RECONSTRUCTION_ENABLED=false`; cold — `git revert` → `05bc870` (анкер `7165ff7`); DDL v17 аддитивна (новые таблицы/колонки безвредны); restore БД — только аварийный сценарий (R18: теги/бэкапы не удаляются).

## 8. Границы и carry-over

### 8.1. Нарезка 04a ↔ 04b (§8.3.1) — санкция

| № | Разрыв | Фича | Комментарий @Architect |
|---|---|---|---|
| 1 | `_memorize_direct_reply` target=asker | **04a** | контракт личного факта §8.3.2 (T-3826) |
| 2 | `get_persona_card`/`get_user_context_facts` name-scope | **04a** | subject-scope потребителей (T-3826) |
| 3 | Layer B `person_facts` не сохраняются | **04a** | сохранение независимо от портрета (A86) |
| 5-контракт | локальные evidence → SourceRef + валидатор | **04a** | контракт + `filter_layer_a_candidates` (T-3826) |
| 4 | `_WINDOW_SQL ... LIMIT`, прогресс от bounded window | **04b** | полная пересборка/диапазон §8.3.3 |
| 6 | budget-exhaustion → `run_dossier_rebuild` done/processed=total | **04b** | состояния job/честные счётчики |
| 7 | `upsert_generated_dossier` затирает портрет | **04b** | накопление/замена портрета §8.3.3–8.3.4 |
| 5-врезка | фактический chunk-пайплайн преобразования | **04b** | применяет контракт 04a в chunked-проходе |

### 8.2. Границы с потребителями
- **`mca-04b`** — full rebuild/job-состояния/полнота (см. §8.1); расширяет MCA-04a.
- **`mca-07`** — EvidenceBundle читает SourceRef (trigger/current revision/факты с SourceRef/ограничения); MCA-04a даёт контракт ссылок.
- **`mca-05`** — Episode/Story source links поверх SourceRef; **`mca-06`** — парадигмы с типизированными ссылками/версиями; **`mca-16`** — Lesson/ExperienceEpisode отдельным контрактом (не смешивать с фактами/парадигмами); **`mca-18`** — `subject_entity_id`/`speaker_entity_id`/perspective/`memory_kind`/scope/valid_from-valid_to **расширяют** MCA-04a; **`mca-19`** — Message/SourceRef расширение (media), «так написано ≠ верно»; **`mca-20`** — ClaimEnvelope/TemporalVerdict (origin fingerprint/время). Второй контракт идентичности/provenance/субъекта **запрещён** — только расширение.

### 8.3. Carry-over `L-MCA03-8` (решение)
Отпечаток namespace `abspath|size` (`mca-03`) совпадёт при in-place регенерации файла того же размера → возможен пропуск source record. **Решение:** в 04a **не** исправлять (не в предмете provenance; фикс в механизме namespace MCA-03; не блокирует). Передать **обязательным входом `mca-04b`** (касается импорта/backfill): при добавлении mtime/content-хэша — **версионировать алгоритм отпечатка** (`import:<export_id>:<v2>`), чтобы не создавать коллизий с уже импортированными namespace'ами; `legacy_import_v1` не переприсваивается; строка `L-MCA03-8` остаётся в `ARCHITECTURE.md` §96.4. Если loader в 04b не трогается — фикс уходит в `mca-release`.

## 9. Документация / MEMORY

- Merge-раздел `plans/ARCHITECTURE.md` **§98+** — по T-3835 (@Architect, только по Accepted).
- Рамка: `plans/docs/mca-round1027-arch-frames.md` §1.2.2 (бронь v17), §2 (Δ каталога=0 для 04a), §3 (kill-switch), §4 (ADR-1027-6).
- План: `plans/docs/mca-round1027-plan.md` §3.4 (старт `mca-04a`).
- KG/индекс — на @Memory (Step 10); `MEMORY_DELTA` — в handoff.
- `plans/current_task.md` не изменялся; секреты источника не цитируются (R17/R18).
