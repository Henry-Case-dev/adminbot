# EPIC-MEMORY-COGNITIVE-02 — замороженные контракты (MEMORY-01…09, backend MEMORY-08)

**Статус:** решение Архитектора (редакция 4: адресные исправления по gate A0 — точные места символов на объединённой линии, разрушающие пути `memory_maintenance`, семантика `subject_entity_ids`, отсутствие верхнего капа `top_k`, единственный гейт `ENTITY_TYPES`, доказанный план SQLite по индексу). Вход для Builder. Один документ, без второго ADR.
**Источник:** `plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md` (sha256 `316893a9…0ed1`), карта `requirements-map.json` — read-only.
**Заменяет:** только раздел «поисковая панель» в `plans/features/evol/arch/cog-map-contract.md` (санкция §0/§9.4 ТЗ). Остальные части cog-map-contract (типы узлов, окно 800/2400, честные состояния, «нет второго хранилища») остаются в силе.

---

## 0. База реализации и границы

### 0.1. Одна линия реализации: `integ/unify-release` (union `release/2.58.161` ⊕ `evol/impl`)

Реализация эпика — **одна**. Не «release вместо master», не «master плюс патчи».

| Факт (проверено в git 07.11.2026) | Значение |
|---|---|
| Прод | `release/2.58.161` @ `a563ee31`, схема `_SCHEMA_VERSION_SLOT_CLAIMS = 42` |
| Ветка реализации | `integ/unify-release` @ `640da3eb` — **готовая union-ветка**: `release/2.58.161` и `evol/impl` уже её предки (`git merge-base --is-ancestor` = true для обеих), 36 файлов / +10617 строк относительно release |
| База-маркер (не писать) | `evol/impl` @ `2c1af33e`: 14 коммитов сверх release, 23 релизных коммита **отсутствуют** |
| Общие файлы памяти | `services/summary_memory.py`, `services/database.py`, `services/mca_retrieval_context.py` **идентичны** на `evol/impl` и `release/2.58.161` |
| Релизный corrective, отсутствующий на `evol/impl` | `factcheck_service.py` (~189 строк), `summary_l2_writer.py`, `summary_generator.py`, `summary_l1_clusterizer.py`, `summary_l2_review.py`, `turn_payload_events.py`, `summary_stage_events.py`, `chat_clock.py` (39 строк), `web/app.js`, `web/static/cog-visual.js` |
| `master` (локально) | своя линия: нет `web/api/cognitive_map.py`, `web/static/cognitive-map.js`, `services/chat_clock.py`; между `8bb2800f` и локальным HEAD изменён только `requirements-map.json` |

**Решение:** линия реализации — **`integ/unify-release` @ `640da3eb`**. Отдельный union-merge не изобретается: эта ветка уже является надмножеством production (в ней и `release/2.58.161`, и `evol/impl` — предки). `evol/impl` остаётся базой, доказывающей происхождение, но **писать эпик в неё нельзя** — в ней отсутствуют 23 релизных коммита, включая corrective.

- MEMORY-01…09 и MEM-08-S* пишутся **в `integ/unify-release` после подтверждения G0**.
- Запрещено: писать эпик напрямую в `release/2.58.161`; создавать новую ветку «памяти» или четвёртую линию; реализовывать на `master` или на `evol/impl`; повторно мержить release после старта слайсов; выводить релиз эпика из `master`.
- Все символы ниже (`module::symbol`) валидны только после перепроверки на `integ/unify-release` (§0.3, gate A0). Номера строк не используются.

**Barrier G0 (обязателен до первой строки кода эпика):** цель — `integ/unify-release` @ `640da3eb` (или его потомок, если DevOps обновит ту же ветку union-merge). Проверки: `git merge-base --is-ancestor release/2.58.161 integ/unify-release` = true **и** `git merge-base --is-ancestor evol/impl integ/unify-release` = true; тестовый прогон этой ветки зелёный; §0.3 перепроверен на её коде. Обновление линии — только слияние в ту же ветку, без новой ветки-конкурента. Владелец G0 — DevOps + Orchestrator, не Builder.

### 0.2. Reuse-поверхность (адаптируем, не создаём)

| Механизм | Где | Используется контрактом |
|---|---|---|
| `nodes` / `edges`, `UNIQUE(chat_id, entity_name)`, `UNIQUE(source_id,target_id,relation_type)`, `idx_nodes_chat_type` | `services/database.py` | C-1 (точное имя = legacy-путь; ограничение одного слота имени — §0.4.8), C-2 (identity ребра = `edges.id`) |
| `upsert_node` (INSERT OR IGNORE), `upsert_edge` (weight cap 5, `fact_id` COALESCE) | `services/database.py` | C-2, C-3 (идемпотентность, вес ≠ истина), C-1.4.1 (обязательный канонический id) |
| `graph_snapshot` (параметры `max_nodes/max_edges/seed_nodes`) + константы `GRAPH_MAX_NODES=800` / `GRAPH_MAX_EDGES=2400` / `GRAPH_SEED_NODES=150` (**определены в `web/api/memory_agi.py`**, импортируются в `web/api/cognitive_map.py`) | `services/database.py` (метод), `web/api/memory_agi.py` (константы), `web/api/cognitive_map.py` | **только рендер**; поиск их не использует |
| `mca_source_refs` / `mca_evidence_links` / `mca_provenance_status` + `provenance.py` | v17 | C-2: множественные основания ребра, статусы, независимость |
| `graph_facts`: `subject_ref_id`, `attribution_method`, `assertion_kind`, `speaker_author_id`, `perspective`, `memory_kind`, `scope`, `valid_from`, `valid_to`, `confidence_basis`, `revision`, `status`, `supersedes`, `weight`, `last_confirmed_at` | v12/v17/v31 | C-2, C-3 без новых колонок |
| `graphrag_provenance.validate_person_edge_write` / `classify_fact_provenance` / `independent_roots_count` / `plan_correction` | `services/graphrag_provenance.py` | C-2, C-3 (weight cap 0.55, confident/tentative/legacy) |
| `AliasResolver` / `LiveAliasView` / `build_alias_resolver` (каскад chat→global→nickname→username) | `services/summary_aliases.py` | C-1 (display-имена, mutable pointers), C-4 |
| `users_meta(chat_id, user_id)` (+ `touch_user_meta`, `refresh_users_meta`) | v9 | C-1.2.1 (единственный достоверный список uid чата) |
| `mca_retrieval_context`: `RetrievalRequest`/`RetrievalCandidate`/`RetrievalResult`, каналы exact/lexical/vector/reply_graph/episode, `apply_identity_prior`, `EvidenceBundle`, `mode ∈ auto|history|exact`, `scope ∈ auto|time_range|participants|parent|branch` | `services/mca_retrieval_context.py` | C-4, C-7 (расширяем **эту** функцию, а не создаём второй поиск) |
| `mca_episodes` / `mca_stories` / `lore_stories` (`event_start_ts`/`event_end_ts`) | v21 | C-3 (T_event из эпизода), C-4, C-8 |
| `mca_bot_outputs` (>`bot_output_ledger`) | v22 | C-8 (self-output не подтверждает внешний факт) |
| `mca_experience` / `mca_experience_jobs` | существующие сервисы | C-8 (опыт ≠ постоянное правило) |
| `mca_vision` / `postgen_vision` / `mca_media_*` | существующие сервисы | C-8 (мультимодал без повторного vision на поиск) |
| `mca_events` (`emit_mca_event`), `mca_trace` (`trace_id`) | v15 | наблюдаемость (§9) |
| `services/chat_clock.py`: `snapshot(chat_id, at_utc=…)`, `TimeSnapshot`, цепочка IANA-пояса | release (после G0 — в `integ/unify-release`) | C-3, C-7.2 |
| `chat_params.get_chat_param(chat_id, 'flags.x.y')`, `get_chat_param_sourced`, `param_catalog` `ParamSpec(pg_id="flags.…")` | `services/chat_params.py`, `services/param_catalog.py` | C-5 (global/chat inheritance без новых механизмов) |
| `task_jobs` (durable очередь, checkpoint) | v14 | C-5 (resume бэкфилла без новой таблицы) |
| `web/api/cognitive_map.py` + `web/static/cognitive-map.js` (`/api/memory/cognitive-map`, `PAYLOAD_VERSION`, `KINDS`, `computeClusters` — компоненты по рёбрам, `buildAggregates` — экранные LOD-тайлы, `GROUP_NEUTRAL_LABEL`) + `web/app.js` (`_graphSignature`, вызов `buildAggregates`) | release/`evol/impl` | C-4 (владелец map-API и UI-адаптера) |
| `mca_associations` (`analogy/motif/contrast/continuation`, `status='candidate'`) | v30 | C-2 (cooccurrence-гипотезы живут здесь, не в `edges`) |
| `get_user_context` = `ToolRouter::_get_user_context` (`_MEMORY_LOOKUP_PURPOSE_DEFAULTS`: identity 5, appearance 10, speech_style 5, biography 10, **relationships 10**, general 8; `_MEMORY_LOOKUP_PURPOSES` — те же 6 ключей) | `services/tool_router.py` | C-7.5 (ветка `relationships` уже существует и читает `db.get_persona_card.links`) |

### 0.3. Аудит MEMORY-00: что перепроверяем на объединённой линии

Аудит MEMORY-00 выполнен на `8bb2800f` (линия `master`). Между `master` и production-линией различаются (измерено `git diff --stat master release/2.58.161`): `services/summary_memory.py` **+1090/−?**, `services/database.py` **+961**, `services/mca_retrieval_context.py` **+100**, `services/summary_aliases.py` **+23**, новые `services/chat_clock.py` (+451) и `web/api/cognitive_map.py` (+916). Поэтому выводы аудита по этим файлам **не переносятся** — они переустанавливаются на объединённой линии.

Статусы: `verified@evol-impl` — совпадает на `evol/impl@2c1af33e` и `release/2.58.161`; `verified@integ` — проверено прямо на union-ветке `integ/unify-release`; `pending@unified` — требует подтверждения после G0 (в т.ч. после прихода релизного corrective). После gate A0 (07.11.2026) строк со статусом `pending@unified` в таблице не осталось.

| # | Утверждение о текущем состоянии | Статус | Где |
|---|---|---|---|
| 1 | `nodes`: `UNIQUE(chat_id, entity_name)` без `entity_type`; `idx_nodes_chat_type` есть | `verified@evol-impl` | `database.py` DDL |
| 2 | `upsert_node` = `INSERT OR IGNORE` (второй тип под тем же именем молча отбрасывается) | `verified@evol-impl` | `database.py::upsert_node` |
| 3 | `_write_graph_triplets` пишет `fact_id=NULL` **осознанно** (крон/фото-извлечение) | `verified@evol-impl` | `summary_memory.py::_write_graph_triplets` |
| 4 | `_dedup_decide`: exact→`noop`; `cosine ≥ 0.95`→`noop`; `[0.85,0.95)`→`supersede`; ниже→`add` | `verified@evol-impl` | `summary_memory.py::_dedup_decide` |
| 5 | Квота **физически удаляет** факты: `_enforce_user_quota`→`get_quota_victim`→`delete_graph_fact` (FTS+vec+row), `GRAPH_USER_QUOTA_ENABLED=True`, `GRAPH_FACTS_PER_USER_QUOTA=50` | `verified@evol-impl` | `summary_memory.py`, `config/settings.py`, `database.py` |
| 6 | `purge_expired_graph_facts` удаляет истёкшие факты (protect: weight ≥ 0.8, свежее подтверждение 3 дня, `protected_facts`) | `verified@evol-impl` | `database.py::purge_expired_graph_facts` |
| 7 | Caps 800/2400/150 ограничивают кадр карты; константы **определены в `web/api/memory_agi.py`** (не в `database.py`) и импортируются в `cognitive_map.py` | `verified@evol-impl` | `web/api/memory_agi.py`, `web/api/cognitive_map.py` |
| 8 | Toolbar `[input][Найти][Все типы][Все кластеры][Сбросить вид]` есть **и** inline, **и** в fullscreen | `verified@evol-impl` | `web/index.html` (два блока), `cognitive-map.js` |
| 9 | Видимая подпись «Группа · N» — экранный LOD-тайл `buildAggregates`: `label = baseLabel + ' · ' + grp.count`, а `GROUP_NEUTRAL_LABEL='Группа'` берётся, когда нет доминирующего типа. Рядом живёт **другая** функция `computeClusters` — union-find по реальным `model.edges` (компоненты связности для фильтра `Все кластеры`). Это две разные вещи; ни одна не является семантическим сообществом | `verified@integ` | `web/static/cognitive-map.js` (`buildAggregates` ≈717, подпись ≈968; `computeClusters` ≈577; вызов из `web/app.js` ≈31966) |
| 10 | `_graphSignature` — клиентский ключ «данные сцены не изменились» для 15-секундного поллинга (пропуск перерисовки), **не** ревизия графа; живёт в `web/app.js` (≈30529), в `cognitive-map.js` его нет | `verified@integ` | `web/app.js` |
| 11 | `mca_source_refs` дедуп: `(store, entity_type, entity_id, COALESCE(chat_id,-1), COALESCE(revision,''))` | `verified@evol-impl` | DDL v17 |
| 12 | `evidence_independent_count` считает только `derived_from`/`supports` + `verification='verified'` + `independence='independent'`; `mentions` не считается | `verified@evol-impl` | `provenance.py` |
| 13 | `smart_messages.forward_source`; `forward_from` — колонка `graph_facts` | `verified@evol-impl` | `database.py` DDL v11/v12 |
| 14 | `mca_retrieval_context.retrieve()` — один `chat_id`, `top_k` режется **только снизу** (`max(1, request.top_k)`; верхнего капа нет), каналы exact/lexical/vector/reply_graph/episode; курсора, entity- и community-канала нет | `verified@integ` | `mca_retrieval_context.py::retrieve` |
| 15 | `mca_entity_canonical` в коде отсутствует полностью (0 вхождений вне `plans/`) → правило 1 C-1 сегодня не может сработать | `verified@evol-impl` | `git grep` |
| 16 | `chat_params.get_chat_param(None, key)`: chat-слой пуст → `hot.get` → factory; исключения нет | `verified@evol-impl`, тест обязателен (§5.2.1) | `chat_params.py` |
| 17 | `get_user_context` purposes: **6** (включая `relationships`); `_memory_lookup_relationships` читает `db.get_persona_card(...).links`; per-purpose `max_items` = 5/10/5/10/10/8 — кап **выдачи инструмента**, не квота retrieval | `verified@evol-impl` | `tool_router.py` |
| 18 | Релизный corrective **присутствует** на объединённой линии: `factcheck_service.py`, `summary_l2_writer.py`, `summary_generator.py`, `summary_l1_clusterizer.py`, `summary_l2_review.py`, `turn_payload_events.py`, `summary_stage_events.py`, `chat_clock.py`, `web/static/cog-visual.js` | `verified@integ` | файлы на `integ/unify-release` |
| 19 | Обе линии на `_SCHEMA_VERSION_SLOT_CLAIMS = 42`; шаг v43 свободен | `verified@evol-impl` | `database.py` |
| 20 | Union-ветка `integ/unify-release` @ `640da3eb` содержит и `release/2.58.161`, и `evol/impl` как предков; схема там тоже 42 | `verified@integ` | git (`merge-base --is-ancestor` = 0 для обеих) |

#### 0.3.1. Gate A0 — переаудит перед кодом MEMORY-01 (обязательный)

Пункт MEM-00 варианта `master` **не закрыт**. До первой строки кода MEMORY-01 на объединённой линии обязателен переаудит ровно этих мест, с отметкой `PRESENT_AND_VERIFIED / PARTIAL / MISSING / CONFLICT` и ссылкой на символ + живой тест:

1. `summary_memory.py`: `_dedup_decide`, `_enforce_user_quota`/`get_quota_victim` (разрушающая квота), `_write_graph_triplets`, прямой путь записи факта (`insert_graph_fact` + `upsert_node`×2 + `upsert_edge(fact_id=…)`), `_attach_fact_provenance`.
2. **`memory_maintenance.py` (отдельный модуль, не `summary_memory.py`):** `merge_episodes`/`_merge_chat`/`_cluster_facts`/`_cluster_exact`/`_merge_cluster` (≈763: `insert_graph_fact` агрегата + `delete_graph_fact` каждого источника), `review` (≈827: удаление дублей + `purge_expired_graph_facts`/`purge_unconfirmed_graph_facts`), `_glue_vec_dups` (≈856: удаление по cosine ≥ 0.95). Разрушающие пути — §3.4.1.
3. `database.py`: вся цепочка `_migrate_*` до v42, `upsert_node`/`upsert_edge`, `insert_graph_fact`, self-fact путь (`INSERT … graph_facts` для собственных слов бота), `delete_graph_fact`, `purge_expired_graph_facts`, `purge_unconfirmed_graph_facts`, FTS/vec-таблицы, DDL `nodes`/`edges`/`graph_facts`.
4. `mca_retrieval_context.py`: состав каналов, `retrieve`, `apply_identity_prior`, `top_k`/`limit`-поведение, `build_memory_request`, формат `EvidenceBundle`.
5. Пришедшие после G0 релизные модули, которых аудит не видел: `factcheck_service.py`, `summary_l2_writer.py`, `turn_payload_events.py`, `summary_stage_events.py`, `chat_clock.py` — в объёме, нужном C-3/C-7/C-8 (время, evidence summary к Writer, разделение factcheck/память).

##### Итог gate A0 (07.11.2026, `integ/unify-release`)

- **MEMORY-01 — GO.** Минимальный набор касаний: новый `services/memory_contracts.py` + новый `tests/test_memory_contracts.py` (только эти два файла, ничего существующего не правится).
- **MEMORY-03 — GO** после однострочного изменения: добавить `"graph_edge"` и `"entity"` в `services/provenance.py::ENTITY_TYPES` (единственный гейт типа, см. §2.5).
- **MEMORY-04 — NO-GO** до этой редакции: разрушающие пути `memory_maintenance` (§3.4.1) противоречили R-8/R-10/MEM-02.6.
- **MEM-08-S3 — NO-GO** до исправлений 1–2 этой редакции: неверная атрибуция «Группа · N» и `_graphSignature` увела бы Builder к неверной структуре клиентского кода.

**Правило:** расхождение с этим документом на объединённой линии → не «додумать», а `ARCHITECT_ADJUSTMENT_REQUIRED` от Builder; документ обновляется один раз, без второго ADR.

### 0.4. Подтверждённые конфликты (что именно исправляем)

1. **`UNIQUE(chat_id, entity_name)` + точное сравнение** (`database::upsert_node`) → `Папаха`/`папаха` раздваиваются; типизированной канонической идентичности нет.
2. **`edges.fact_id` — одно основание**; путь `summary_memory::_write_graph_triplets` (крон-извлечение) пишет `fact_id=NULL` осознанно → у части рёбер обоснования нет вовсе, и это невидимо в UI.
3. **`summary_memory::_dedup_decide`**: cosine ≥ 0.95 → `noop`, `[0.85, 0.95)` → **`supersede`** (инвалидация старого факта по сходству векторов), ниже → `add`. Прямое нарушение MEM-02.5/MEM-04.4/INV-06: сходство вектора не доказательство, а `noop` не даёт независимому повтору стать подтверждением.
4. **Caps 800/2400/150** — ограничения кадра; поиск по ним невозможен (`_graphSignature` + client-side `searchNodes` ищут только в загруженной сцене).
5. **Видимый toolbar**: в `web/index.html` inline и fullscreen содержат `[input][Найти][Все типы][Все кластеры][Сбросить вид]`; клиентские фильтры `{kinds, scopes, chats, statuses, search, cluster}` живут в `cognitive-map.js`. Поиск — подстрока по `search`-блобу 800 узлов.
6. **«Группа · N»** — подпись **экранного LOD-тайла** в `web/static/cognitive-map.js::buildAggregates` (`label = baseLabel + ' · ' + count`; `GROUP_NEUTRAL_LABEL='Группа'` при отсутствии доминирующего типа), рендерится из `web/app.js` (≈31977). Рядом существует **другая** клиентская функция `computeClusters` — union-find по реальным `model.edges`, то есть компоненты связности для фильтра `Все кластеры`. Ни тайл, ни компонент не являются семантическим сообществом, и путать их нельзя: «Группа · N» — про раскладку на экране, `computeClusters` — про рёбра данных.
7. **Квота и обслуживание уничтожают память.** (а) `summary_memory::_enforce_user_quota` → `database::get_quota_victim` → `database::delete_graph_fact` физически удаляет строку `graph_facts` + FTS + vec; включено по умолчанию (`GRAPH_USER_QUOTA_ENABLED=True`, `GRAPH_FACTS_PER_USER_QUOTA=50`). (б) `memory_maintenance::merge_episodes`/`_merge_cluster` (≈763) вставляет агрегированный факт, затем вызывает `delete_graph_fact` **для каждого** исходного факта кластера; `memory_maintenance::review` (≈827) удаляет дубли exact-групп, а `memory_maintenance::_glue_vec_dups` (≈856) удаляет пары по cosine ≥ 0.95; всё это включено по умолчанию (`GRAPH_EPISODE_MERGE_ENABLED=True`, интервал 7 дней, батч 20, до 5 фактов в кластере). Это нарушает MEM-04.6/INV-01/INV-08, а для слияния — ещё и R-8/R-10/MEM-02.6 (доказательства источника исчезают вместе с фактом). Решение — §3.4.1 (квота) и §3.4.1.1 (обслуживание).
8. **Один слот имени на чат.** `UNIQUE(chat_id, entity_name)` без `entity_type`: два узла с **одинаковым написанием** и разными типами (человек и головной убор, тема и человек) технически невозможны, а `upsert_node` во втором случае молча оставляет первый тип. Решение — §1.2.3.
9. **Ревизий графа не существует.** `graph_revision`/`alias_revision` — не колонки и не переменные (0 вхождений в коде); `_graphSignature` (в `web/app.js`, ≈30529) — клиентский ключ «данные сцены не изменились» для 15-секундного поллинга, к ревизии графа отношения не имеет. При этом дедуп `mca_source_refs` включает `revision`: «свежая ревизия на каждое изменение» порождает дубли SourceRef и прячет связи. Решение — §2.4.
10. **`mentions` не подтверждает.** `evidence_independent_count` учитывает только `derived_from`/`supports`; персональное ребро, поддержанное явными сообщениями через `mentions`, имеет `independent_support=0`, а правило «`origin_class = weakest`» ещё и понижает ребро с несколькими проверенными источниками. Решение — §2.3.

### 0.5. Запрещено создавать (проверяется ревью)

Neo4j / managed memory / второй граф / второе векторное пространство / вторая embedding-модель / второй identity-resolver / отдельная система доказательств / **вторая функция поиска** (включая любую «сборку пула кандидатов» вне `mca_retrieval_context`) / ещё одна LLM-генерация на сообщение / второй search-движок / новые колонки в `nodes`/`edges`/`graph_facts` / `DROP`/`CREATE` существующих таблиц / mass re-embed / переписывание prompt registry / hardcode имён, chat_id, alias, путей, версий ОС.

Аддитивная схема этого эпика — **ровно один шаг `v43`** (§5.1). Больше ничего.

---

## 1. C-1. Каноническая идентичность и `resolve_entity`

### 1.1. Структура

```python
EntityRef = {
  "chat_id": int,                  # обязателен: идентичность чат-квалифицирована
  "node_id": int,                  # nodes.id (стабильный, legacy-совместимый)
  "entity_type": "user"|"topic"|"event"|"fact",   # только существующий CHECK
  "display_name": str,             # текущее видимое имя (не переименовывает историю)
  "legacy_ids": [int],             # node_id, сведённые в этот канонический (аддитивно)
  "aliases": [str],                # все орфографии из member-узлов + alias-карты
}

EntityResolution = {
  "status": "resolved"|"ambiguous"|"new"|"rejected",
  "canonical": EntityRef|None,
  "candidates": [{"ref": EntityRef, "reason": str, "discriminator": str}],  # ≥2 при ambiguous
  "reason_code": str,
  "normalized_mention": str,       # диагностика, НЕ ключ
  "scope": {"chat_id": int, "entity_type": str},
  "degraded": ["identity_not_seeded"|"casefold_prefix_overflow"|None],
}

async def resolve_entity(
    *, scope: {"chat_id": int, "entity_type": str},
       mention: str,
       stable_identity: {"kind": "tg_user", "value": int} | None = None,
       evidence: {"source_ref_ids": tuple[int, ...],
                  "episode_id": str | None} | None = None,
       allow_create: bool = False,
) -> EntityResolution
```

Вызов доступен извлечению, retrieval и UI. `allow_create=False` для всех read-путей (UI/поиск/карточки): «новой» сущности не создаётся, `new` означает «ничего не найдено, было бы новой». Резолвер **никогда не пишет** (§1.3 ID-1); создание — только через wrapper `resolve_or_create_node` (§1.4.1).

### 1.2. Порядок разрешения (первое решающее правило выигрывает)

1. `stable_identity.kind='tg_user'` → активная строка `mca_entity_canonical` (`resolution='self'`, `stable_kind='tg_user'`, `stable_value=str(value)`) в этом чате → `resolved`. Две активные строки для одного uid → `ambiguous` (дефект данных, честно). Если строка не засеяна — см. §1.2.1 (`degraded=['identity_not_seeded']`), и правило 1 считается **не сработавшим**, а не «сработавшим по имени».
2. Подтверждённый alias: mention совпадает с alias-картой (`limits.summary_aliases`: chat → global) для `user_id` U, и в чате есть узел `Canon(U)` → `resolved` (действующий каскад `AliasResolver`).
3. **Точное имя в пределах запрошенного типа**: `nodes(chat_id, entity_name = mention, entity_type = scope.entity_type)` → `resolved` (legacy-путь байт-в-байт как `upsert_node`). Фильтр `entity_type` обязателен (§1.2.3). **Защита от подмены личности:** если найденный узел уже имеет активную self-строку `mca_entity_canonical` с **другим** `stable_value`, а `stable_identity` был передан → `ambiguous` (`reason_code='identity_node_conflict'`, оба uid в `candidates`), **никогда не `resolved`** (§1.2.1, ID-11).
4. **Кандидаты по casefold — ограниченная генерация** (§1.2.2). Ровно один → `resolved`, `reason_code='casefold_unique'`, `confidence='tentative'`. Больше одного или переполнение префикса → `ambiguous`.
5. Redirect: у найденного кандидата есть активная строка `mca_entity_canonical` → `resolved` в канонический; цепочка не длиннее одного шага (§1.4.2), legacy-id продолжает резолвиться.
6. Иначе → `new` (`allow_create` не пишет; создание — только через §1.4.1).
7. `rejected`: `entity_type` вне четырёх; пустой/пробельный mention; mention > 200 символов; scope без прав (ACL) — **не** `new`.

#### 1.2.1. Засев `mca_entity_canonical` (без него правило 1 мертво)

Сегодня связи «узел ↔ tg_user_id» нет, а self-строки никем не создаются (0 вхождений `mca_entity_canonical` в коде). Без засева разрешение молча деградирует до сопоставления имён — это запрещённая политика. Поэтому засев — часть контракта, а не «потом».

**Источники (только существующие данные, без новых таблиц):**
- `users_meta(chat_id, user_id)` — авторитетный список uid чата (заполняется `touch_user_meta` на каждом сохранённом сообщении);
- `AliasResolver.resolve(uid, nickname, username)` через `build_alias_resolver(chat_id)` — текущее каскадное display-имя (chat alias → global alias → nickname → username);
- `smart_messages.author_name` при известном `user_id` и `smart_messages.user_id` — исторические написания, из которых реально создавались узлы (`summary_memory::_canon_fact_name`).

**Кандидаты для uid U:** узлы `nodes(chat_id, entity_type='user')`, чей `entity_name` **точно строково равен** одному из: `resolve(U)`, `canon_name(resolve(U))`, любого `author_name`, наблюдавшегося у U. Никакого casefold, никакой похожести, никакой транслитерации на этом шаге.

**Инвариант засева (устраняет ложное слияние двух Telegram-личностей):** **один узел ↔ не более одной активной стабильной идентичности**, и один `stable_value` ↔ ровно один узел. Обеспечивается PK `(chat_id, entity_type, member_node_id)` и `UNIQUE (chat_id, entity_type, stable_kind, stable_value) WHERE status='active' AND stable_kind IS NOT NULL` (§5.1). Засев **никогда не использует `INSERT OR REPLACE`**: существующая self-строка проверяется явно, иначе два uid с одинаковым display-именем перехватывают один узел и правило 3 сливает двух людей (EVAL-04).

**Исходы (детерминированно, идемпотентно по PK):**
| Кандидатов | Действие | Следствие для `resolve_entity` |
|---|---|---|
| ровно 1, узел ещё ни за кем не закреплён | `INSERT` self-строки: `resolution='self'`, `canonical_node_id=member_node_id`, `stable_kind='tg_user'`, `stable_value=str(U)`, `method='alias_map'`, `confidence='confirmed'`, `status='active'` | правило 1 работает |
| ровно 1, но узел **уже закреплён за другим uid** | вставки нет; событие `identity_seed_node_conflict` | `resolve_entity(stable_identity=U)` → `ambiguous`, **оба** uid `ambiguous`; автовыбор и перезапись `stable_value` запрещены |
| 0 | строки нет; событие `identity_seed_missing` | `degraded=['identity_not_seeded']`; падение в правила 2–7 **не выдаётся** за identity-resolve |
| >1 | строки нет; событие `identity_seed_ambiguous` | `resolve_entity(stable_identity=U)` → `ambiguous` (дефект данных), автовыбор запрещён |

**Запуск:** шаг бэкфилла `B2-0` (§5.3) и ленивая попытка при первом `resolve_entity` с `stable_identity`, если self-строки нет и `MCA_MEMORY_IDENTITY_ENABLED=ON` (запись только в очередь бэкфилла, не в read-путь). Резолвер остаётся read-only.

**Смена ника:** засев ключуется uid; имена — изменяемые указатели. После переименования `AliasResolver` отдаёт новое имя, извлечение создаёт узел в новом написании, а связь старый→новый появляется только как alias/redirect на явном основании. `stable_value` не меняется, старая evidence сохраняет `author_id`, старые узлы и `edges.source_id` не переписываются.

#### 1.2.2. Ограниченная генерация casefold-кандидатов (без полного скана)

Правило 4 не может быть `SELECT * FROM nodes WHERE chat_id=? AND entity_type=?` — это полный скан на каждый запрос и нарушение §4.8 (p95 ≤ 500 мс).

- Диапазонный поиск по индексу `UNIQUE(chat_id, entity_name)`: для первого графемного кластера mention берутся варианты (`upper`, `lower`, `casefold`); для **каждого** варианта `C` интервал — **ровно `[C, C + 1 codepoint)`**, то есть `entity_name >= C AND entity_name < chr(ord(C)+1)`, `LIMIT 33` (32 + 1 для детекта переполнения). Это семантика «начинается с `C`» в BINARY-сравнении SQLite. Проверено на живой SQLite (07.11.2026, gate A0) при сохранённых `ПАПАХА`, `Папаха`, `папаха`, `Бабаха`: интервал `['П','Р')` возвращает `ПАПАХА`, `Папаха`; интервал `['п','р')` возвращает `папаха`; `Бабаха` не возвращается ни одним из них, а интервал «от самого написания» (`['Папаха','Папахб')`) теряет верхний регистр и потому запрещён. `EXPLAIN QUERY PLAN` для запроса правила 4 даёт `SEARCH nodes USING COVERING INDEX sqlite_autoindex_nodes_1 (chat_id=? AND entity_name>? AND entity_name<?)` — то есть индексный поиск, не `SCAN nodes`. `LIKE` не используется: SQLite `NOCASE` не сворачивает кириллицу.
- Сравнение — в Python: `casefold(trim(NFC(name))) == casefold(trim(NFC(mention)))`.
- Переполнение (>32 строк в префиксе) → `ambiguous`, `reason_code='casefold_prefix_overflow'`, до 8 вариантов с различающим признаком, `degraded=['casefold_prefix_overflow']`, событие с `counts.prefix_rows`. «Дочитать всё» запрещено.
- Константы централизуются: `ENTITY_CASEFOLD_MAX_ROWS = 32`, `ENTITY_CASEFOLD_MIN_PREFIX = 1` (в `services/memory_contracts.py`). `ENTITY_CASEFOLD_MIN_PREFIX=1` на реальном объёме (**≈53 тыс. узлов**) даёт широкие интервалы, поэтому значение фиксируется как константа **только после замера на реальной БД** (селективность и p95 §4.8); до замера это параметр, а не «доказанный оптимум». Транслитерация/лемматизация/падежи **не** участвуют (ID-4).
- Тест обязан проверять `EXPLAIN QUERY PLAN` (ожидается `SEARCH nodes USING COVERING INDEX sqlite_autoindex_nodes_1`, не `SCAN nodes`) и сценарий переполнения; мутация «убрать LIMIT» валит тест. Отдельный обязательный тест диапазона: при сохранённых `ПАПАХА`, `Папаха`, `папаха` **все три** находятся (верхний вариант даёт `ПАПАХА`/`Папаха`, строчный — `папаха`), а узел с другой первой буквой (например `Бабаха`) — **нет**.

#### 1.2.3. Один слот имени и разные типы (ограничение схемы, честное поведение)

`UNIQUE(chat_id, entity_name)` не даёт двум узлам одного чата иметь одинаковое написание даже при разных `entity_type`. Поэтому:

- два узла «человек Папаха» и «тема Папаха» с **идентичным** написанием невозможны без изменения схемы, а изменение схемы запрещено (§0.5). Ограничение фиксируется как известное, а не обходится новой таблицей;
- `resolve_entity` при точном имени, найденном с **другим** типом, возвращает `rejected`, `reason_code='type_conflict_single_slot'`, `candidates=[{ref, discriminator:"другой тип: <type>"}]`; **никогда** не резолвит в чужой тип и не пишет;
- writer (§1.4.1) при конфликте типа не вызывает `upsert_node` (иначе `INSERT OR IGNORE` молча оставит чужой тип): запись отменяется, событие `entity_type_conflict`, факт сохраняется без ребра (честная деградация, не выдуманная связь);
- различие регистра/написания (`Папаха`/`папаха`) — по-прежнему два узла и путь через casefold/alias (§1.2.2), где неоднозначность видима;
- тип в правиле 3 — обязательная часть ключа поиска; тест T7 отражает именно это поведение (см. §1.9);
- конфликт типа **не выглядит потерей данных**: сам факт сохраняется в `graph_facts` и остаётся доступным через FTS/историю, а конфликт виден администратору событием `entity_type_conflict`.

### 1.3. Инварианты

- **ID-1. Только чтение.** Резолвер ничего не пишет: ни узлов, ни redirect-строк, ни evidence; засев — отдельный шаг бэкфилла.
- **ID-2. Чат-квалификация.** Никогда не возвращает узел другого чата. Общий (админский) обзор возвращает **сгруппированные по чату** результаты, никогда не одну слитую личность (INV-05).
- **ID-3. Никогда не сливает.** `MERGE` — отдельная явная операция (админ/бэкфилл, §5), не следствие резолва.
- **ID-4. Casefold — только кандидаты.** Unicode-нормализация, trim, casefold, варианты кавычек, падежи, транслитерация **не** доказывают тождество и не выполняют слияние. Оригинальное написание и видимые алиасы сохраняются.
- **ID-5. Никакого возвышения типа.** Термин из текста не становится Telegram-пользователем; `entity_type='user'` — только при реальной identity (ID/алиас-карта/evidence).
- **ID-6. Якорь пользователя — Telegram user ID**, alias/nickname — изменяемые указатели. Смена ника не переписывает evidence (source refs хранят author id, не имя). Засев — §1.2.1; отсутствие засева видно как `degraded`, а не как успешный identity-resolve.
- **ID-7. Детерминизм.** Ответ зависит только от `(scope, entity_type, mention, stable_identity, graph_revision, alias_revision)`; кэш обязан включать обе ревизии (§2.4.3).
- **ID-8. Неоднозначность — данные, не выбор.** При `ambiguous` — ≥2 реальных варианта с различающим признаком (тип/чат/период/источник/degree). Автовыбор «самого популярного» запрещён.
- **ID-9. Один слот имени признаётся честно.** Конфликт типа не разрешается обходом UNIQUE; результат — `rejected`/отсутствие ребра, не «тихая» подмена типа.
- **ID-10. Писатели пишут в канонический id.** После слияния ни один писатель не создаёт второй узел под тем же именем (§1.4.1).
- **ID-11. Один узел — максимум одна активная стабильная идентичность.** PK `(chat_id, entity_type, member_node_id)` + `UNIQUE (chat_id, entity_type, stable_kind, stable_value) WHERE status='active' AND stable_kind IS NOT NULL`: ни один узел не обслуживает двух `tg_user`, ни один uid не закреплён за двумя узлами. Нарушение при засеве → `identity_seed_node_conflict`, оба uid `ambiguous`; правило 3 при активной self-строке с другим `stable_value` → `ambiguous`, не `resolved` (§1.2.1).

### 1.4. Как legacy-узлы продолжают резолвиться

`nodes` не переписываются и не удаляются. Слияние = **добавление строки** `mca_entity_canonical` (`member_node_id` → `canonical_node_id`, `status='active'`), после чего:
- чтение и запись отношений резолвят `node_id` → канонический через одну таблицу;
- member-узел остаётся в БД со своим `id` и написанием → старые `edges.source_id/target_id`, `graph_facts.subject_ref_id`, `mca_source_refs.entity_id` остаются валидны;
- откат = `status='revoked'` (или удаление строк) — данные не теряются;
- `graph_snapshot`/`build_cognitive_map` схлопывают member→canonical **на чтении** и суммируют рёбра по `(canonical_source, canonical_target, relation_type)`; дубли в выдаче не появляются, история не теряется (детали агрегированного ребра — §2.5).

#### 1.4.1. Все шесть путей записи пишут канонический id

Инвентаризация писателей узлов/рёбер/фактов (проверено по коду, gate A0 подтверждает после G0):

| # | Путь | Где | Особенность |
|---|---|---|---|
| W1 | real-time извлечение факта | `summary_memory` (путь `insert_graph_fact` + `upsert_node`×2 + `upsert_edge(fact_id=…)`) | пишет `fact_id` |
| W2 | крон/фото-триплеты | `summary_memory::_write_graph_triplets` | осознанно `fact_id=NULL` |
| W3 | сон/убеждения | `dream_worker` (`insert_graph_fact(origin='derived_belief')`) | derived lineage |
| W4 | лор/летопись | `lore_worker`, `lore_compiler_service` | истории/факты |
| W5 | `user_memory` + собственные слова бота | `chat_lore`, self-fact путь `database` | self_output ≠ доказательство |
| W6 | импорт/пересборка/обслуживание | `memory_maintenance`, `graphrag_rebuild`, `chat_migration` | батч, чекпоинты |

**Правило:** каждый из W1–W6 получает объекты через `services/entity_resolver.py::resolve_or_create_node(db, chat_id, name, entity_type)` (единственная точка создания), которая: резолвит через §1.2 → при `new` и `allow_create` создаёт узел существующим `upsert_node` **внутри транзакции писателя** → при `type_conflict_single_slot` не создаёт и возвращает конфликт (писатель фиксирует факт без ребра, событие `entity_type_conflict`). Прямой вызов `upsert_node` вне этой функции — дефект; тест `test_no_direct_upsert_node_outside_resolver` (AST/grep) валит сборку. **Тест исключает внутренние/миграционные вызовы внутри `services/database.py`** (собственные методы класса, `_migrate_*`, служебные пути): проверяются только внешние модули-писатели W1–W6.

Гейт `MCA_MEMORY_IDENTITY_ENABLED=OFF` → писатели вызывают `upsert_node` как сегодня (байт-в-байт паритет).

#### 1.4.2. Циклы и глубина redirect

- `canonical_node_id` не может сам быть member другого активного правила (глубина 1 — терминальна); при записи слияние валидируется: `canonical` не должен резолвиться в `member`.
- Чтение: один шаг; если данные (legacy/ручная правка) дают цепочку — возвращается последний достижимый узел с `reason_code='redirect_chain_flattened'`, событие `redirect_cycle_detected` при цикле, и результат помечается `degraded`.
- Ремонт — только явный админский шаг `status='revoked'` + повторное слияние; автоматическое «выпрямление» данных запрещено.

### 1.5. Адаптер

Новый тонкий модуль `services/entity_resolver.py` (**read-only фасад** для чтения + единственная точка создания для писателей, §1.4.1): делегирует `summary_aliases.AliasResolver`/`current_alias_resolver` за display-именами, `nodes`/`mca_entity_canonical` за идентичностью. Собственных таблиц, кэшей идентичности и правил приоритета нет (INV-03).

### 1.6. Запрещено

Второй словарь алиасов; `entities`-таблица, дублирующая `nodes`; UUID-идентичность; `UNIQUE`-индекс по casefold(name); автоматическая транслитерация/лемматизация как доказательство; векторная кластеризация как identity; «канонизация» через `lower()` всех имён; полный скан `nodes` в резолве.

### 1.7. Dual-read / rollback

Гейт `MCA_MEMORY_IDENTITY_ENABLED` + `flags.memory_identity_enabled` (per chat). OFF → вызывающие используют сегодняшний точный путь (эквивалент правила 3, без фильтра типа — паритет). ON → правила 1–7. Обе ветки читают одни таблицы; новые таблицы OFF-ветка не читает. Откат: гейт OFF; затем `status='revoked'` для слияний.

### 1.8. Идемпотентность

Резолвер — чистая функция. Слияние: PK `(chat_id, entity_type, member_node_id)`; повторный dry-run даёт тот же список кандидатов; повторное применение — no-op. Засев: PK по `(chat_id,'user',member_node_id)`, повторный прогон не создаёт вторую self-строку и **не перезаписывает** `stable_value` существующей строки (никакого `INSERT OR REPLACE`; конфликт → `identity_seed_node_conflict`).

### 1.9. Обязательные тесты (негативные/мутационные)

| # | Сценарий | Ожидание |
|---|---|---|
| T1 | `Папаха`/`папаха` — один человек, есть evidence | один канонический узел, обе формы резолвятся, legacy node_id валиден |
| T2 | `папаха` (предмет) и `Папаха` (человек), 2 узла, нет redirect | `ambiguous`, 2 варианта, **никакого** автослияния |
| T3 | Ник «Саша» у двух людей | `ambiguous` |
| T3b | Два uid (`428494`, `777`) с одинаковым display-именем | две self-строки на один узел технически невозможны (PK + `UNIQUE(stable_value)`); второй uid → `identity_seed_node_conflict` и `ambiguous`; **ноль ложных слияний** двух Telegram-личностей (EVAL-04) |
| T4 | Один алиас в двух чатах | два независимых результата, кросс-чат не резолвится |
| T5 | Смена ника `Саша`→`Александр` | резолв по новому алиасу; старые source refs/узлы не изменены; ровно одна self-строка, `stable_value` не изменён |
| T5b | Повторный засев после смены ника | второй self-строки нет, старый узел жив, новый узел достижим через alias/redirect |
| T6 | Упоминание в цитате | резолвится объект цитаты, не пересылающий (атрибуция в C-2) |
| T7 | Имя темы = имя человека (одинаковое написание) | `rejected`/`type_conflict_single_slot`; чужой тип не возвращается, второй узел не создаётся, ребро не пишется |
| T8 | `bot_self_reply` | имя бота не становится `user`-узлом |
| T9 | Редактированный/удалённый исходник | резолв не падает, evidence помечается как недоступный |
| T10 | 100 повторов одного запроса | идентичный результат; 0 ложных персональных слияний в полном прогоне (нулевая терпимость); 0 записей в БД |
| T11 | Засев при 0 узлах-кандидатах | self-строки нет, `degraded=['identity_not_seeded']`, rule-1 не срабатывает |
| T12 | Засев при >1 узлах-кандидатах | self-строки нет, `identity_seed_ambiguous`, `resolve_entity(stable_identity=…)` → `ambiguous` |
| T12b | Узел-кандидат уже закреплён за другим uid, засев для второго uid | вставки нет, событие `identity_seed_node_conflict`, оба uid `ambiguous`; правило 3 при `stable_identity` и чужой активной self-строке не отдаёт `resolved` |
| T13 | 33 узла с одним префиксом | `ambiguous`/`casefold_prefix_overflow`, нет «дочитывания всего» |
| T14 | `EXPLAIN QUERY PLAN` правила 4 | `SEARCH nodes USING COVERING INDEX sqlite_autoindex_nodes_1`, никогда `SCAN nodes` |
| T14b | Сохранены `ПАПАХА`, `Папаха`, `папаха` (BINARY-коллация) | `['П','Р')` → `ПАПАХА`, `Папаха`; `['п','р')` → `папаха`; `Бабаха` (другая первая буква) — не найдена; интервал «от написания» запрещён |
| M1 | Мутация: убрать проверку уникальности casefold-кандидатов | T2/T3/T13 обязаны упасть |
| M2 | Мутация: убрать `LIMIT`/фильтр типа | T7/T14 обязаны упасть |
| M3 | Мутация: заменить проверку закрепления узла на `INSERT OR REPLACE` | T3b/T12b обязаны упасть (появляется ложное слияние uid) |

---

## 2. C-2. Ребро, подтверждённое несколькими независимыми источниками

### 2.1. Логическое представление (всё выводится, ничего не дублируется в БД)

```python
RelationView = {
  "edge_id": int, "chat_id": int,
  "source_entity_id": int, "target_entity_id": int,   # канонические после C-1
  "legacy_ids": [int],                                # свёрнутые edges.id (§2.5)
  "relation_type": str, "relation_label": str,        # русское человеческое имя
  "direction": "directed",                            # edges всегда направлены
  "origin_class": str,          # класс САМОГО СИЛЬНОГО проверенного корня (§2.3)
  "has_unsupported_sources": bool,  # есть legacy/mentions-only основания (риск, не понижение)
  "sources": [{
      "source_ref_id": int, "fact_id": int|None,
      "kind": "message"|"graph_fact"|"episode"|"bot_output",
      "origin_class": str, "assertion_mode": str,     # asserted/quoted/reported/inferred/denied/hypothetical/joking/unknown
      "link_type": str,                               # derived_from|supports|contradicts|mentions|supersedes
      "counts_as_independent": bool,
      "speaker": str|None, "subject": str|None,        # раздельны (INV-07)
      "event_ts": int|None, "observed_ts": int|None,
      "verification": str, "independence": str, "method": str,
      "established_at": int,
  }],
  "independent_support": int,   # provenance.evidence_independent_count(union of links) — §2.4.2
  "legacy_sources_count": int,  # отдельно: без подтверждения
  "frequency": int,             # edges.weight — частота, НЕ истина
  "status": "confirmed"|"tentative"|"unverified"|"contradicted"|"superseded"|"rejected",
  "valid_from": int|None, "valid_to": int|None, "last_confirmed": int|None,
  "confidence_basis": str|None,
  "explanation": str,           # «А упомянул Б в сообщении X (дата)», «А утверждал о связи с Б»,
                                # «гипотеза из N совпадений», «Происхождение не установлено»
  "revision": {"graph": str, "edge_updated_at": int},
}
```

### 2.2. Классы происхождения — выводятся из существующих полей

| Класс | Правило вывода (первое совпадение) |
|---|---|
| `quote_forward` | `smart_messages`: `is_forward=1` **или** `COALESCE(forward_source,'')<>''`; `graph_facts`: `COALESCE(forward_from,'')<>''` **или** `perspective='quoted'` |
| `reported_third_party` | `perspective='third_party'` **или** `attribution_method='third_party'` |
| `explicit_direct` | **подтверждённое авторство** (§2.2.0): `perspective='self'` **или** (`perspective IS NULL` **и** сохранённое авторское сообщение факта не переслано, а его автор совпадает с субъектом/говорящим) **и при этом** `attribution_method IN ('self_report','direct_evidence')` |
| `derived_with_lineage` | `provenance_channel IN ('dream','dossier_layer_a','dossier_layer_b')` **или** evidence-link `derived_from` (обязателен `basis`/`method` с правилом вывода) |
| `cooccurrence` | только `mca_associations` (в `edges` не пишется вовсе) |
| `legacy_unknown` | `edges.fact_id IS NULL` и нет ни одной evidence-связи, либо сигналов нет |

**Колонки не путать:** `smart_messages.forward_source` — display-строка пересылки, `smart_messages.forward_from` **не существует**; `graph_facts.forward_from` — строка provenance факта, `graph_facts.forward_source` **не существует**. Перекрёстное чтение даёт молчаливый `''`/ошибку, поэтому условие всегда пишется per-table, как в таблице выше.

#### 2.2.1. `explicit_direct` = подтверждённое авторство, а не заявленный метод

`attribution_method` пишет сам вызывающий код (`provenance.classify_attribution_method`, `summary_memory._attach_fact_provenance`, `direct_chat_service._apply_fact_attribution`, `lore_worker._write_person_facts`). Поле описывает **чьё это утверждение по мнению писателя**, а не подтверждает, что утверждение действительно произнесено субъектом. Поэтому `explicit_direct` требует **второго реального сигнала авторства**, независимого от `attribution_method`:

1. **`graph_facts.perspective='self'`** — автор явно помечен субъектом типизированной записи (`mca_self_model.store_typed_memory` → `database.save_typed_fact` — единственный INSERT, вообще заполняющий `perspective`); **или**
2. **`graph_facts.perspective IS NULL` и у факта есть сохранённое авторское сообщение**: `graph_facts.tg_message_id` резолвится в строку `smart_messages` того же `chat_id`, где `is_forward=0` и `COALESCE(forward_source,'')=''`, и `smart_messages.user_id` совпадает с идентичностью субъекта/говорящего факта — `graph_facts.subject_ref_id` → `mca_source_refs(entity_type='user', entity_id=<uid>)`, либо `graph_facts.speaker_author_id`, либо `target_user`, резолвленный ровно в один `user_id` (`provenance.resolve_subject_ref`; при ≥2 одноимённых — **не** совпадение).

`attribution_method IN ('self_report','direct_evidence')` остаётся **необходимым, но недостаточным** условием. Во всех остальных случаях класс не `explicit_direct`: `perspective='third_party'`/`attribution_method='third_party'` → `reported_third_party`, иначе `legacy_unknown` (тогда нет `supports`-связи, `independent_support` не растёт, `status` не может стать `confirmed`). «Мягкий» вариант `(perspective IS NULL OR perspective='self')` запрещён: он превращает в подтверждённое ребро факт, у которого модальность одновременно `unknown` — карточка заявляла бы «прямое утверждение автора» и «модальность неизвестна» разом.

**Фактическая доступность сигналов (код линии, проверено):** `perspective` заполняет только `save_typed_fact`, а его единственный вызывающий `store_typed_memory` **не имеет продовых вызовов** (только тесты) — значит ветвь 1 сегодня практически не срабатывает. Ветвь 2 реализуема для `bot_direct_reply`-фактов direct-чата (`tg_message_id` + `speaker_author_id` пишутся), но не для массового `chat_history`: `summary_generator` вызывает `memorize_facts` **без** `tg_message_id`, `lore_worker` пишет `save_message_link=False` и без `tg_message_id`, `remember_user_fact` (`user_memory`) не принимает `tg_message_id` вовсе. Следствие принимается честно: `confirmed` по `explicit_direct` будет **редким**, пока писатель реально не начнёт фиксировать авторство. Редкий `confirmed` — корректный результат, а не повод ослабить правило.

### 2.3. Класс → `link_type` и что считается подтверждением

Маппинг обязателен: без него (`mentions` для всего) `evidence_independent_count` возвращает 0 и ребро навсегда остаётся недоказанным.

| Класс | `link_type` | `counts_as_independent` | Примечание |
|---|---|---|---|
| `explicit_direct` | `supports` (`method='direct_reference'` \| `reply_context` \| `thread_context`, `basis` обязателен) | да | прямое утверждение автора при **подтверждённом авторстве** (§2.2.1) — это и есть основание связи |
| `reported_third_party` | `supports` только если корень ≠ автор пересказа; иначе `derived_from` | да (независимый корень) | пересказ автора не создаёт новый корень |
| `quote_forward` | `derived_from` (`basis='quote'`/`'forward'`) | да, но корень — первоисточник | репост не приписывается переславшему (R-9) |
| `derived_with_lineage` | `derived_from` + `basis` + `method` | да (уникальные корни) | без lineage не пишется |
| `cooccurrence` | `mentions` (или только `mca_associations`) | **нет** | соседство в реплике ≠ утверждение |
| `legacy_unknown` | связи нет (bare edge) | **нет** | «Происхождение не установлено» |
| `contradicts` | `contradicts` | нет (отдельное измерение) | не повышает и не понижает support |
| `supersedes` | `supersedes` | нет | замещение, не подтверждение |

Правила:
- `mentions` **никогда** не входит в `independent_support`; ребро, у которого есть только `mentions`, обязано иметь `status != 'confirmed'` и в карточке показывать «только упоминание, не утверждение» (R-11).
- `status`/`weight` ребра определяются **самым сильным проверенным корнем**: если есть хотя бы один `supports`/`derived_from` с `verification='verified'` и `independence='independent'`, ребро `confirmed`/`tentative` по правилам §3.4 и **не понижается** наличием legacy/`mentions`-источников. Прежнее правило «`origin_class = weakest`» отменено: оно понижало ребро с несколькими проверенными источниками, что противоречит MEM-03.6/R-1.
- Слабые основания видны отдельно: `has_unsupported_sources=true`, `legacy_sources_count`, источник со своим `origin_class` в списке `sources`. Диагностика и ранжирование могут учитывать слабость как **риск**, но не как понижение статуса.
- Вес (`frequency`) остаётся частотой и никогда не меняет `status`/`origin_class` (R-2).

### 2.4. Ревизии и адресация ребра (без выдуманных колонок)

#### 2.4.1. Write-time: SourceRef ребра имеет стабильную ревизию

`mca_source_refs` дедупит по `(store, entity_type, entity_id, COALESCE(chat_id,-1), COALESCE(revision,''))`. Если ревизия ребра выводится из изменяемого состояния графа, то после каждого изменения веса/подтверждения появляется **новый** SourceRef для того же `edge_id`; уникальный индекс `mca_evidence_links(subject_ref_id, source_ref_id, link_type, COALESCE(claim_key,''))` перестаёт блокировать повторную привязку → дубли связей, завышенный `independent_support`, а читатель, смотрящий только на «свежий» ref, теряет связи (они «прячутся»).

**Решение:** для `entity_type='graph_edge'` и `'entity'` `revision` — **константа** `'stable'`. Один SourceRef на ребро/узел, append-only evidence-links. Ревизия — свойство источника (сообщения/факта), а не ребра.

#### 2.4.2. Read-time: объединение по всем ревизиям

Чтение ребра/узла обязано **объединять** все `mca_source_refs` строки с `entity_type IN ('graph_edge','entity')` и `entity_id=str(id)` по всем ревизиям (включая legacy-строки с непустой ревизией), затем дедуплицировать links по `(source_ref_id, link_type, COALESCE(claim_key,''))`, отсортировать по `established_at` и только потом считать `independent_support`/`legacy_sources_count`. Чтение «только самой новой ревизии» запрещено.

#### 2.4.3. Откуда берутся `graph_revision` / `alias_revision`

Колонок и переменных с такими именами в коде нет (0 вхождений `graph_revision`/`alias_revision` вне `plans/`); `_graphSignature` в `web/app.js` (≈30529) — клиентская подпись состава сцены для 15-секундного поллинга, к ревизии графа отношения не имеет. Поэтому:

- `graph_revision(chat_id)` — **вычисляемый** дешёвый дайджест по индексам: `sha1(f"{nodes_count}:{max_node_id}:{edges_count}:{max_edge_id}:{max_edges_last_updated}")` для чата; нигде не хранится.
- `alias_revision(chat_id)` — `chat_params` профиль `updated_at` (уже отдаётся `get_chat_params_full`) + версия global hot-слоя того же ключа.
- Композитная ревизия для курсора/кэша: `rev = (graph_revision, alias_revision, index_fingerprint)`. Это **токен консистентности чтения**, никогда не ключ записи.

### 2.5. Одно ребро, много источников, и агрегирование после слияния

Одна строка `edges` + N строк `mca_evidence_links`, где `subject_ref_id` указывает на **SourceRef самого ребра**:

```
mca_source_refs(store='sqlite', entity_type='graph_edge', entity_id=str(edges.id), chat_id, revision='stable')
   ↑ subject_ref_id
mca_evidence_links(source_ref_id = SourceRef сообщения / факта / эпизода,
                   link_type ∈ derived_from|supports|contradicts|mentions|supersedes,
                   verification ∈ verified|tentative|rejected|unknown,
                   independence ∈ independent|self_referential|unknown,
                   claim_key, method, basis, checks_json, established_at)
```

Требуемое изменение кода (без схемы и без новых колонок): `services/provenance.py::ENTITY_TYPES` — **единственный** гейт типа источника. `SourceRef.validate()` бросает `ValueError` при `entity_type` вне этого множества; никаких других проверок типа/ревизии в модели нет, `SourceRef.revision` — свободное `str | None`, участвующее только в `dedup_key`. Поэтому достаточно добавить `"graph_edge"` и `"entity"` в `ENTITY_TYPES` и конструкторы `graph_edge_source_ref(chat_id, edge_id)` / `node_source_ref(chat_id, node_id)`, всегда ставящие `revision='stable'`. Полей `graph_revision`/`alias_revision` в `SourceRef` не существует и вводить их не нужно. Существующий `graph_fact_source_ref(chat_id, fact_id)` **уже стабилен**: он не передаёт `revision` (`None` → `COALESCE(revision,'')` в дедуп-индексе), поэтому один SourceRef на факт уже обеспечен и менять его не требуется.

**`edges.fact_id` сохраняется как совместимое поле** (одиночное основание для скоринга `COALESCE(importance, weight)` в `graph_snapshot`); новые писатели продолжают его заполнять, дополнительные основания идут в `mca_evidence_links`.

**Агрегированное ребро после слияния узлов:**
- строки `edges` не удаляются и не переписываются; агрегация — только на чтении по `(canonical_source, canonical_target, relation_type)`;
- `edge_id` агрегата = **минимальный** `edges.id` в группе (детерминированно, стабильно между запросами); остальные id — в `legacy_ids`; карточка открывается по агрегатному id и показывает все основания группы;
- `independent_support` агрегата = объединение links всех членов группы по §2.4.2 (один и тот же источник в двух членах = один корень);
- запись после слияния всегда идёт в каноническую пару (§1.4.1), поэтому новые дубли не появляются; существующие остаются (без `DELETE`) и схлопываются только на чтении;
- `upsert_edge` по паре, где один из концов — member, обязан сначала перевести id в канонический (иначе создаётся третья строка `edges` с тем же смыслом).

**Минимальная аддитивная связка `edge_id` НЕ создаётся:** существующая схема адресует ребро (SourceRef с `entity_type='graph_edge'`), значит условие MEM-03.2 «если технически не поддерживает» не наступило. Второй таблицы доказательств нет.

### 2.6. Инварианты

- **R-1.** `status='confirmed'` ⟹ ≥1 evidence-link с `verification='verified'` и разрешимым источником, чей `link_type ∈ {supports, derived_from}`. `mentions` не удовлетворяет R-1. Проверяется на чтении API и на записи.
- **R-2.** Вес/частота никогда не меняют `status` и `origin_class`. `weight` = подтверждения с cap 5 (существующий `_EDGE_WEIGHT_CAP`), отображается как «частота».
- **R-3.** Собственный вывод бота не corroborates сам себя: `provenance.is_self_referential_origin`, `origin='bot_direct_reply'`, `mca_bot_outputs` → `independence='self_referential'`; в `independent_support` не входит.
- **R-4.** Повторный репост/пересказ того же корня не добавляет независимости (тот же `source_ref_id`).
- **R-5.** Ложная транзитивность запрещена: `A–B` и `B–C` **никогда** не дают `A–C`. `derived_with_lineage` — только с явной семантикой предиката и цепочкой ссылок.
- **R-6.** Cooccurrence/соседство на экране/сходство эмбеддингов не создают типизированное ребро.
- **R-7.** Legacy bare-edge не удаляется и не скрывается, показывается как «Происхождение не установлено», не попадает в confident-контекст, вес ограничен 0.55 (`validate_person_edge_write`).
- **R-8.** Противоречие/устаревание/сжатие — только аддитивно (evidence-link + `mca_provenance_status`); в нормальном цикле памяти физического удаления и `DELETE` нет. Единственные разрешённые исключения перечислены в §3.4.1 (явный пользовательский `delete`/`forget`, security retention).
- **R-9.** Направление и авторство сохраняются: содержание пересылки приписывается первоисточнику, не переславшему (`quote_forward`).
- **R-10.** Merge узлов переносит **наборы доказательств** без потери ни одного `fact_id`, веса, периода, авторства, оспоренного статуса (MEM-02.6).
- **R-11.** `mentions`-only ребро не становится `confirmed` ни по весу, ни по частоте, ни по анимации.
- **R-12.** Статус агрегата определяется сильнейшим проверенным корнем; слабые основания показываются отдельно и не понижают агрегат.
- **R-13.** Адресация ребра стабильна: одна строка `mca_source_refs` на ребро (`revision='stable'`), связи не дублируются при повторной привязке.

### 2.7. Dual-read / rollback / идемпотентность

- OFF (`MCA_RELATION_EVIDENCE_ENABLED` + `flags.relation_evidence_enabled`) → пишем как сегодня (`fact_id`, без edge-refs), читаем как сегодня. ON → дополнительно пишем/читаем edge-evidence; старые читатели (`graph_snapshot`, legacy API) не меняются.
- Откат: гейт OFF; edge-ref строки остаются инертными (старый код их не читает); удаление не требуется.
- Идемпотентность: перед `upsert_edge` проверяется наличие link `(edge_ref, source_ref, link_type, claim_key)`; если есть — `weight_increment=0` и **без** сброса `last_updated` (новый аддитивный параметр `touch_recency: bool = True` у `upsert_edge`). Повторная экстракция того же сообщения не накачивает вес (SC-08).

### 2.8. Обязательные тесты

Ребро с 3 независимыми источниками показывает все 3 и `independent_support=3`; тот же источник дважды → 1; self-output не подтверждает; репост не подтверждает; legacy-ребро (`fact_id NULL`) — «происхождение не установлено» + вес ≤0.55; ребро с одним `verified supports` и двумя legacy — `confirmed`, `legacy_sources_count=2`, статус не понижен (мутация: вернуть `weakest` → тест падает); `mentions`-only ребро не `confirmed` и `independent_support=0`; `A–B`,`B–C` не дают `A–C` (негатив); cooccurrence не появляется в `edges`; противоречивое ребро показывает обе стороны; карточка ребра открывается по агрегатному `edge_id` и содержит кликабельные исходники всех членов группы; повторная привязка того же источника после `upsert_edge`-инкремента веса не создаёт второй SourceRef и не меняет `independent_support` (идемпотентность §2.4.1); повторный прогон извлечения не меняет вес.

**`explicit_direct` (§2.2.1) — обязательные случаи:** (а) `perspective='self'` + `attribution_method='self_report'` → `explicit_direct`, `assertion_mode='asserted'`; (б) `perspective IS NULL`, `attribution_method='self_report'`, `tg_message_id` резолвится в непрессланное `smart_messages` сообщение того же автора, что субъект/говорящий → `explicit_direct`; (в) **негатив**: `attribution_method='self_report'` без `perspective` и без сохранённого авторского сообщения → `legacy_unknown`, `assertion_mode='unknown'`, нет `supports`, `status != 'confirmed'`; (г) **негатив**: авторское сообщение найдено, но `is_forward=1`/`forward_source<>''` → `quote_forward`, не `explicit_direct`; (д) **негатив**: `smart_messages.user_id` не совпадает с субъектом (пересказ) → `reported_third_party`/`legacy_unknown`; (е) **негатив**: одноимённые ≥2 `user_id` → авторство не подтверждено. Мутации: вернуть мягкое `(perspective IS NULL OR perspective='self')` → падает (в); доверять `attribution_method` без второго сигнала → падает (в); игнорировать `is_forward` → падает (г); заполнять `explicit_direct` при `assertion_mode='unknown'` → падает (в).

---

## 3. C-3. Время, эволюция и политика обслуживания

### 3.1. Три различных мгновения (не смешивать)

| Понятие | Источник | Правило |
|---|---|---|
| **T_assertion** — когда утверждение произнесено | `smart_messages.sent_at`/`timestamp`, `mca_source_refs.tg_message_id` → сообщение | используется для разрешения относительных дат |
| **T_event** — время утверждаемой действительности | `graph_facts.valid_from/valid_to`; иначе `mca_episodes.event_start_ts/event_end_ts` связанного эпизода | только если источник это поддерживает; иначе `NULL` |
| **T_observed** — когда записано в память | `graph_facts.created_at`, `mca_source_refs.created_at`, `mca_evidence_links.established_at`, `edges.last_updated` | никогда не выдаётся за T_event |

Жёстко: **отсутствующая дата ≠ timestamp сообщения ≠ `time.time()`**.

### 3.2. Относительные даты

«вчера», «сегодня», «через неделю» разрешаются **от T_assertion** через `services/chat_clock.py::snapshot(chat_id, at_utc=T_assertion)` (per-chat IANA, DST/fold-корректно, цепочка `limits.chat_timezone` → legacy → global → factory). Глобального фиксированного пояса нет. Историческое сообщение, переработанное позже, интерпретируется по своему мгновению, не по времени запуска воркера. Неизвестный пояс → `timezone_source='utc_fallback'` и это **видно** в карточке («часовой пояс неизвестен, UTC»). `chat_clock.py` приходит на линию реализации только после G0 — до этого C-3 §3.2 не считается реализуемым.

### 3.3. `supersedes`, модальность и статус

`graph_facts.supersedes` + `database::invalidate_graph_fact` + `database::log_fact_compression` + `mca_provenance_status.freshness_status='superseded'`. Старая строка сохраняется целиком вместе с источниками; закрытие `valid_to` ставится по T_assertion новой поправки, **не** по «сейчас»; если противоречие объяснимо разными периодами/сферами — хранятся обе версии (пример: «раньше работал там, теперь здесь» — не ошибка).

#### 3.3.1. `assertion_mode`: только выводимое, иначе `unknown`

| Сигнал (существующее поле) | `assertion_mode` |
|---|---|
| `smart_messages.is_forward=1`/`forward_source<>''`, `graph_facts.forward_from<>''`, `perspective='quoted'`, `quote_*` указатели | `quoted` |
| `perspective='third_party'` или `attribution_method='third_party'` | `reported` |
| `provenance_channel IN ('dream','dossier_layer_a','dossier_layer_b')`, `origin='derived_belief'` | `inferred` |
| функция `claim_envelope.is_deny_phrase(text)` возвращает true для текста утверждения (это **функция над текстом**, не поле-флаг) | `denied` |
| **подтверждённое авторство** (§2.2.1: `perspective='self'` **или** `perspective IS NULL` + сохранённое непрессланное авторское сообщение, автор = субъект/говорящий) **и** `attribution_method IN ('self_report','direct_evidence')` | `asserted` |
| явный флаг `hypothetical` / `joking` в `claim_envelope`/`checks_json` | `hypothetical` / `joking` |
| нет сигнала | **`unknown`** |

Запрещено выводить `joking`/`hypothetical` по смайлику, кавычкам, восклицательному знаку или длине сообщения; отсутствующее значение остаётся `unknown` (MEM-03.1, MEM-06.4). `assertion_kind` берётся только из существующего `ASSERTION_KINDS`, иначе `unknown`.

Класс происхождения и модальность используют **одно и то же** условие авторства (§2.2.1). Это не косметика: при расхождении карточка одновременно утверждала бы «прямое утверждение автора» (`origin_class='explicit_direct'`) и «модальность неизвестна» (`assertion_mode='unknown'`). Факт с `attribution_method='self_report'`, но без `perspective='self'` и без сохранённого авторского сообщения остаётся `unknown` (и `legacy_unknown` по §2.2).

### 3.4. Единая политика решений

Реализуется в `summary_memory::_dedup_decide` (единственная точка решения) с `graphrag_provenance::plan_correction` для отрицаний/поправок.

| Решение | Условие | Запись |
|---|---|---|
| **ADD** | нет кандидата с тем же `(chat, canonical subject, predicate, object)` и той же identity | новый факт + ребро + evidence-link |
| **ENRICH** | то же утверждение, новые **пустые** метаданные (период/область/база уверенности) | UPDATE только `NULL`-полей + evidence-link; non-NULL не перезаписывается |
| **CONFIRM** | то же утверждение, **независимый корень** (`source_ref_id` новый, не self-output) | +1 evidence-link (`verification='verified'`, `independence='independent'`), `last_confirmed_at=now`, вес ребра +1 (cap 5) |
| **SUPERSEDE** | тот же субъект+предикат, **другое** значение, с собственным источником | новый факт (`supersedes=old`), старый инвалидируется штатным механизмом, `valid_to` = T_assertion новой поправки |
| **CONTRADICT** | явное отрицание/поправка (функции `claim_envelope.is_deny_phrase(text)` / `is_correction_phrase(text)` над текстом, затем `plan_correction`) | link `contradicts`, `verification='tentative'`, `conflict_status='conflicting'`; без переключения истинности до разрешения |
| **NOOP** | тот же корень (`source_ref_id` + revision) повторно | **ноль** записей: ни веса, ни `last_updated`, ни `last_confirmed_at` |

**Изменение поведения (гейтировано):** cosine-полосы `_dedup_decide` перестают быть доказательством.
- `cosine ≥ 0.95` больше **не** даёт `noop` (иначе независимый повтор теряется);
- `cosine ∈ [0.85, 0.95)` больше **не** даёт `supersede` (инвалидация по сходству запрещена);
- при гейте ON сходство даёт только событие `dedupe_candidate` с id ближайшего кандидата; решение остаётся ADD, если не совпали identity+assertion (тогда CONFIRM) или не сменилось значение (тогда SUPERSEDE) или нет отрицания (CONTRADICT).
- Принятое следствие: больше «похожих» фактов в БД вместо уничтожения; митигация — диагностика `dedupe_candidate` + dry-run слияний (MEM-02.6), а не удаление.
- Гейт OFF → точный прежний расчёт (паритет), данные не трогаются.

#### 3.4.1. Квота личных фактов больше не удаляет память

Факт: `summary_memory::_enforce_user_quota` → `database::get_quota_victim` → `database::delete_graph_fact` физически удаляет строку `graph_facts`, её FTS-строку и vec-строку, а `log_fact_compression(reason='quota')` оставляет лишь текст в журнале. Включено по умолчанию (`GRAPH_USER_QUOTA_ENABLED=True`, `GRAPH_FACTS_PER_USER_QUOTA=50`). Это прямое нарушение MEM-04.6 («старое, редкое, забытое **не стирать** ради квот»), INV-01 и INV-08.

**Решение (неразрушающее):**
- **Удаление из квоты убирается из кода полностью**, а не прячется за флаг. `delete_graph_fact` больше не вызывается ни из квоты, ни из слияния/дедупа (§3.4.1.1). Разрешённые вызовы `delete_graph_fact` — **ровно два**: явный пользовательский `delete`/`forget` (`/forget` и родственные команды) и security retention. Ретеншн-пурж (`purge_expired_graph_facts`, `purge_unconfirmed_graph_facts`) реализован собственным SQL, а не `delete_graph_fact`, и подчиняется условиям ниже.
- `_enforce_user_quota` перестаёт быть вытеснением и становится **наблюдением границы**: считает живые факты пользователя (`expires_at IS NULL OR expires_at > now`), сравнивает с квотой и пишет `graph_fact_quota_exceeded` (числа) + метрику для админки. Никаких `UPDATE` веса и никаких `expires_at` — ставить `expires_at=now` **запрещено**: `purge_expired_graph_facts` физически удалит такую строку на следующем проходе (проверено: предикат `fact_candidate` + protect weight 0.8 / 3 дня), то есть «архивация через TTL» была бы удалением с задержкой.
- Семантика флага: `GRAPH_USER_QUOTA_ENABLED` (и `flags.graph_user_quota_enabled`) сохраняет имя для совместимости конфигурации, но означает «включено наблюдение квоты live-пула». `OFF` → наблюдение не считается, ограничения нет; **удаления нет ни в одном состоянии**. `GRAPH_FACTS_PER_USER_QUOTA=50` остаётся порогом отчёта.
- Совместимость/миграция: схемных изменений нет; уже удалённые ранее строки восстановлению не подлежат — `graph_fact_compressions` с `reason='quota'` остаются как честный след прошлых удалений, «восстановление» не инсценируется. Гейт `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED=ON` добавляет в отчёт `memory_maintenance::review` строку «людей сверх квоты: K» и не удаляет ничего.
- `purge_expired_graph_facts` (TTL/retention) остаётся действующей retention-политикой и **не** переиспользуется как квота: квота не выставляет `expires_at` и не вызывает purge. **Пурж условен:** строка с `expires_at <= now` удаляется только когда `memory.infinite_retention=OFF` (глобально **и** для её чата) **и** строка не защищена — вес < 0.8 (`limits.graph_purge_protect_weight`), `last_confirmed_at` старше 3 дней (`limits.graph_purge_protect_days`), текст не входит в `protected_facts`. При `memory.infinite_retention=ON` `purge_expired_graph_facts` возвращает 0 без SQL (существующее поведение `_infinite_retention_on`), контракт это сохраняет.
- **Что увидит владелец в админ-панели:** «Живых фактов у человека: N / порог 50», «Людей сверх порога: K», «Вытеснено/удалено квотой: 0 (механизм отключён)», «Рост: +X фактов за неделю». Объём: каждая запись остаётся строкой `graph_facts` + FTS + vec (`dim × 4` байта) ≈ `text_bytes + fts_bytes + dim*4 + ~120 B`; рост линеен числу новых фактов на человека и **не** ограничен сверху порогом 50 — это осознанная цена INV-01, оценивается замером на реальной БД до релиза (не «примерно»).
- **Рост не попадает в горячий путь (bounded-retrieval):** все читающие каналы ограничены — отсечение по `top_k` для ответа, `LIMIT` FTS, `LIMIT` vec, keyset-пагинация поиска; личный пул пользователя **никогда не сканируется целиком**. Поэтому рост числа строк от отказа от квоты не меняет p95 по построению, а не «по обещанию»; подтверждение — A/B-замер на реальной БД до релиза.
- **Заранее принятое действие при регрессии:** если замер всё же покажет рост p95 сверх бюджета §4.8, снижается **ранг и вероятность вызова** старых/редких фактов в retrieval (частотный приоритет, hot-context), но факты **не удаляются**; возврат к удалению квотой запрещён в любом состоянии.
- **Тест:** 51-й личный факт при квоте 50 → `graph_facts` = 51, `graph_facts_fts` = 51, vec-строка жива, удалённый-бы-факт находится FTS-поиском и историческим retrieval, `expires_at` не изменён, `graph_fact_quota_exceeded` эмитнут, счётчик «вытеснено» = 0. Мутация: вернуть `delete_graph_fact` в путь квоты → тест падает (51 vs 50). Отдельный тест пуржа: при `memory.infinite_retention=ON` факт с истёкшим `expires_at` жив; при OFF защищённый (вес ≥ 0.8 / подтверждение <3 дней / `protected_facts`) — тоже жив.

#### 3.4.1.1. Обслуживание (`memory_maintenance`) — тоже разрушающий путь

Второй источник потери памяти, найденный gate A0 и не покрытый прежней редакцией:

| Путь | Что делает сегодня | Факт (проверено на линии) |
|---|---|---|
| `memory_maintenance::merge_episodes` → `_merge_chat` → `_cluster_facts` → `_merge_cluster` (≈763) | LLM-слияние кластера (`COMPRESS_PROMPT` + проверка покрытия `_MERGE_COVERAGE_MIN`) → `insert_graph_fact` агрегата → `delete_graph_fact` **каждого** источника + `log_fact_compression(reason='episode_merge')` | Кластеризация — KNN по vec при cosine ≥ `_MERGE_CLUSTER_SIM=0.85`, иначе `_cluster_exact` по subject+predicate. Включено по умолчанию: `GRAPH_EPISODE_MERGE_ENABLED=True`, `GRAPH_EPISODE_MERGE_INTERVAL_DAYS=7`, `GRAPH_EPISODE_MERGE_BATCH=20`, `GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER=5` |
| `memory_maintenance::review` (≈827) | exact-дубли: оставляет самый тяжёлый, остальные `delete_graph_fact` (журнал `review_glue`); затем `purge_expired_graph_facts` и `purge_unconfirmed_graph_facts` | Дедуп по точному тексту, факты исчезают из `graph_facts`/FTS/vec |
| `memory_maintenance::_glue_vec_dups` (≈856) | пары с cosine ≥ `_REVIEW_GLUE_SIM` (0.95) → `delete_graph_fact` проигравшего (журнал `review_glue`) | Сходство вектора снова выступает доказательством «это тот же факт» |

Это нарушает R-8 (только аддитивно), R-10/MEM-02.6 (merge обязан переносить **наборы доказательств** без потери ни одного `fact_id`) и MEM-04.6. `tests/test_memory_maintenance.py` **сейчас кодирует именно удаление**: `TestEpisodeMerge::test_cluster_merged_sources_deleted_logged` утверждает, что исходных фактов в таблице больше нет (`len(facts) == 2`), `TestReview::test_exact_dups_glued_keep_heaviest` — что осталась ровно одна строка (`len(rows) == 1`).

**Требование — lineage-preserving merge, источники не удаляются:**

1. Слияние и дедуп **никогда** не вызывают `delete_graph_fact`, не выставляют `expires_at` и не удаляют FTS/vec-строки — ни при каком значении гейта. Разрушающая ветка удаляется из кода, как и квотная в §3.4.1, а не прячется за флагом.
2. Агрегат — **новый** факт (`insert_graph_fact`, origin/период/`target_user` по существующим правилам), а каждый источник остаётся строкой `graph_facts` со своим текстом, FTS- и vec-строкой и продолжает находиться поиском и историей.
3. Lineage обязателен и двусторонний, без новых колонок:
   - вперёд: `mca_evidence_links(subject_ref_id = graph_fact_source_ref(агрегат), source_ref_id = graph_fact_source_ref(источник), link_type='derived_from', method='compression', basis='episode_merge', verification='verified', independence='independent')` — по строке на каждый источник (дедуп держит существующий UNIQUE-индекс);
   - обратно: `mca_evidence_links(subject_ref_id = graph_fact_source_ref(источник), source_ref_id = graph_fact_source_ref(агрегат), link_type='supersedes', method='compression')` + `mca_provenance_status.freshness_status='superseded'` для источника. Источник читается как «замещён агрегатом #N» и остаётся доступным.
4. `log_fact_compression(reason='episode_merge'|'review_glue')` остаётся журналом (аудит), но больше не сопровождает удаление строк.
5. Сходство не даёт права замещать: кластер, собранный **только** по cosine (vec-ветка `_cluster_facts`), даёт агрегат `status='unconfirmed'`/`verification='tentative'` и **не** помечает источники `superseded`; помечать замещение может только кластер по точному subject+predicate (`_cluster_exact`) — тот же принцип, что в §3.4.
6. `_glue_vec_dups` не удаляет: cosine ≥ 0.95 → событие `dedupe_candidate` (id пары, §9) и ноль записей. Дедуп exact-групп в `review` переводится на схему п. 3 (supersede с указателями, обе строки живы).
7. Ретеншн — единственное разрешённое удаление и он не расширяется: `purge_expired_graph_facts` только при `memory.infinite_retention=OFF` и вне защиты; `purge_unconfirmed_graph_facts` остаётся под тем же гейтом и попадает в отчёт `memory_maintenance::review` числом. Ни один из них не используется как квота и не выдаётся за «архивацию».
8. **Существующие тесты переписываются** под новый контракт (на новой реализации обязаны упасть в старом виде): `test_cluster_merged_sources_deleted_logged` → «агрегат создан, все исходные факты живы (число источников не изменилось), FTS/vec живы, `derived_from` на каждый источник, обратные `supersedes`»; `TestReview::test_exact_dups_glued_keep_heaviest` → «обе строки на месте, у проигравшего `freshness_status='superseded'` и указатель на победителя, ни одна строка не удалена». Мутации: вернуть `delete_graph_fact` в `_merge_cluster`, в `review` или в `_glue_vec_dups` → соответствующий тест падает.
9. Откат: схемных изменений нет; при выключенном `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` новые агрегаты/связи не пишутся, но удаления нет ни в одном состоянии. Ранее удалённые строки не восстанавливаются и «восстановление» не инсценируется.

### 3.5. Консолидация (сон/саммари/опыт/досье)

Обобщение допускается только из повторяющихся независимых сигналов, с обязательным lineage (`source_ids`, evidence-links) и разграничением `observation` (оперативное) / `stable_trait` (долговременное) / `bot_belief` (гипотеза). Одна ссора, мем, шутка или роль в ролевой игре не закрепляется как постоянное свойство. Старое/редкое не стирается ради квот (§3.4.1); hot-context управляется вероятностью вызова, архивный поиск сохраняется (кроме штатных delete/forget и политик retention).

### 3.6. Dual-read / rollback / идемпотентность

Гейт `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` + `flags.memory_maintenance_policy_enabled`. OFF → `_dedup_decide` как сегодня (включая cosine-полосы), квотное наблюдение — как в §3.4.1, слияние/дедуп обслуживания — как в §3.4.1.1. Удаления нет ни в одном состоянии в обоих случаях. Откат: гейт OFF. Идемпотентность: NOOP-правило + уникальные индексы evidence-links + проверка «этот корень уже связан».

### 3.7. Обязательные тесты

`valid_from` ставится только при поддержке источником; отсутствующая дата ≠ T_assertion ≠ now; «вчера» через границу DST и после смены пояса чата; историческое сообщение, переработанное позже, сохраняет своё разрешение; поправка сохраняет старую строку и её источники; ENRICH не перезаписывает non-NULL; NOOP не повышает вес; CONFIRM только при независимом корне; cosine-полоса не инвалидирует (мутация: вернуть старый `supersede` → тест падает); противоречие доступно с обеих сторон; `assertion_mode` без сигнала = `unknown` (мутация: подставить `asserted` → тест падает); `assertion_mode='asserted'` только при **подтверждённом авторстве** по §2.2.1 — `self_report` без `perspective='self'` и без сохранённого непрессланного авторского сообщения даёт `unknown` (мутация: трактовать любой `self_report` как `asserted` → тест падает); класс `explicit_direct` и `assertion_mode='asserted'` не расходятся (мутация: мягкое `(perspective IS NULL OR perspective='self')` → тест падает на паре «`explicit_direct` + `unknown`»); квота не удаляет (§3.4.1); слияние/дедуп обслуживания не удаляют источники, агрегат связан `derived_from` с каждым источником и обратными `supersedes`, cosine-кластер не помечает источники `superseded` (§3.4.1.1).

---

## 4. C-4. Единый read-only поиск для одного поля карты

### 4.1. Ручка

Одна, на владельце map-API (`web/api/cognitive_map.py`, тот же `_require_global_admin`/`_db_or_503`):

```
GET /api/memory/search?q=<str>&chat_id=<int?>&cursor=<str?>&generation=<int>&limit=<int<=20>
```

- `q`: 1…200 символов, без спецсинтаксиса. **Нет** параметров `kind`/`type`/`cluster`/`status` — клиент не классифицирует заранее.
- `chat_id`: сервер сам определяет допустимый scope из прав (`_require_global_admin` + известный набор чатов); чужой/неразрешённый → `403 scope_forbidden` (не пустой результат). URL/`startapp` права не расширяют.
- `cursor`: opaque base64url `{bucket, score_q, canonical_id, rev}`; `rev = (graph_revision, alias_revision, index_fingerprint)` (§2.4.3); при несовпадении `rev` → `status='cursor_stale'` (поведение — §4.9).
- `generation`: монотонный клиентский счётчик; сервер **эхо**-возвращает; клиент отбрасывает ответы с `generation < max_seen` (SC-26).

Существующие детальные ручки добавляются тем же владельцем, сохраняя старые параметрические фильтры для совместимости:
`GET /api/memory/entity/{node_id}`, `/entity/{node_id}/neighbors?kinds=&depth=&cursor=`, `/edge/{edge_id}`, `/community/{build_id}/{community_id}`, `/diagnostics/missing-link?from=&to=`.
`GET /api/memory/graph` и `/api/memory/cognitive-map` остаются, новые поля аддитивны.

### 4.2. `SearchIntent` (только на сервере)

```python
SearchIntent = {
  "q": str, "scope": {"chat_id": int|None, "mode": "chat"|"scope_all"},
  "intents": [{"kind": "person"|"fact"|"event"|"belief"|"relation"|"topic"|"time"|"unknown", "weight": float}],
  "subjects": [EntityRef], "ambiguous_subjects": [EntityResolution],
  "terms": [str], "quoted": [str],
  "time_hint": {"from": int, "to": int, "tz_source": str} | None,
  "mode": "specific"|"episodic"|"thematic",
}
```
Интент — **подсказка ранжированию, не фильтр**. Низкая уверенность/многозначность → смешанная выдача. Тип результата берётся из данных, не из классификатора. Никакого LLM: интент собирается детерминированно из алиасов/сущностей, FTS-термов, `is_history_query`, `chat_clock` (для «вчера»), явных реляционных маркеров. `mode` использует три режима MEM-06.6 (§7.1), отображённые на существующие `mode`/`scope` retrieval.

### 4.3. `SearchResult`

```python
SearchItem = {
  "ref_kind": "entity"|"fact"|"episode"|"community"|"relation",
  "canonical_id": str,            # ent:<chat>:<node>, fact:<id>, episode:<id>,
                                  # edge:<id>, comm:<build>:<id>
  "legacy_ids": [str],
  "title": str,                   # человеческое название из данных
  "category": "Человек"|"Событие"|"Факт"|"Убеждение"|"Тема"|"Связь",
  "snippet": str|None,            # ≤400 симв. (существующий _PREVIEW_MAX_CHARS), ACL-проверено
  "match_cause": "exact_name"|"alias"|"casefold"|"fts"|"semantic"|"temporal"|"relation_path"|"community",
  "evidence_status": "confirmed"|"tentative"|"legacy"|"contradicted"|"unknown",
  "event_ts": int|None, "observed_ts": int|None,
  "focus": {"chat_id": int, "node_id": int} | None,   # None для факта без узла — честно
  "ambiguity": {"reason": str, "variants": [{"canonical_id": str, "title": str, "discriminator": str}]} | None,
}
SearchResponse = {
  "status": "ok"|"ambiguous"|"empty"|"legacy_only"|"partial"|"forbidden"|"error"|"cursor_stale",
  "reason_code": str|None,        # для cursor_stale: 'cursor_revision_mismatch'
  "query_state": "local_matches"|"server_searching"|"candidates"|"no_matches"|
                 "weak_legacy_only"|"partial"|"error"|"no_rights",
  "items": [SearchItem], "next_cursor": str|None, "has_more": bool, "generation": int,
  "scope": {"chat_id": int|None, "mode": str, "partial": bool},
  "revision": {"graph": str, "alias": str, "community_build": str|None, "index_fingerprint": str},
  "debug": {"channels": [...], "why_ranked": [...]} | None,   # admin-only, без сырого текста
}
```

### 4.4. Ранжирование — внутри существующего `retrieve()`, не рядом с ним

Поиск обязан вызывать **ту же** функцию, что и ответ бота: `services/mca_retrieval_context.py::retrieve(db, memory, request)`. Сейчас она принимает один `chat_id`, режет выдачу по `top_k` **только снизу** (`max(1, request.top_k)`; верхнего капа в `retrieve` нет) и не имеет курсора/entity/community-каналов, поэтому **контракт требует её расширить** (не создать параллельный сборщик пула — это был бы второй поисковый движок, запрещённый §0.5/S-1):

**Верхняя граница `limit ≤ 20` вводится этим эпиком явно (MEMORY-06), а не существует сегодня:** параметр `limit` появляется только в новой ветке `purpose='ui_search'`, и там он валидируется на входе (`1 ≤ limit ≤ 20`, иначе `400`); `top_k` для reply/initiative остаётся как есть, без нового потолка.

```python
RetrievalRequest += {
  "chat_ids": tuple[int, ...] | None,   # None = (chat_id,); scope_all передаёт разрешённый набор
  "channels": tuple[str, ...] | None,   # None = политика по умолчанию
  "purpose": "reply"|"initiative"|"factcheck_context"|"ui_search"|"dossier",
  "cursor": str | None, "limit": int | None,   # только для purpose='ui_search'
  "offset_bucket": str | None,
  "subject_node_ids": tuple[int, ...] | None,  # nodes.id после C-1; НЕ uid (§7.1)
}
```
Контракт расширения:
- `chat_ids` соблюдает ACL: набор приходит только от владельца прав (§4.1), сам `retrieve` ничего не угадывает;
- `cursor`/`limit` активны только при `purpose='ui_search'`; для reply/initiative сохраняется текущее `top_k`-поведение;
- `purpose='ui_search'` запрещает LLM: `apply_retrieval_rerank` не вызывается (§4.6);
- новый канал `entity` (взвешенный вес 90, между exact и lexical) добавляется в существующую детерминированную агрегацию `_CHANNEL_WEIGHTS` + `apply_identity_prior`; `community` читается из `mca_community_members` активной сборки;
- `subject_node_ids` (`nodes.id` после C-1) питает новый `entity`-канал, а существующий `subject_entity_ids` остаётся кортежем **uid** для identity-prior; смешивать их запрещено (§7.1);
- каналы остаются bounded SQL (keyset/LIMIT), без полного скана; `EXPLAIN QUERY PLAN` проверяется тестом.

**Тест связи endpoint↔функция обязателен:** `test_search_endpoint_calls_shared_retrieve` подменяет `mca_retrieval_context.retrieve` счётчиком и утверждает, что `/api/memory/search` вызвал именно её (0 собственных SQL-поисков в `web/api/cognitive_map.py` — проверяется AST/`EXPLAIN`-инвентарём запросов в модуле).

### 4.5. Полный охват, независимый от 800/2400

Поиск и обход используют таблицы целиком (`nodes`, `edges`, `graph_facts`, FTS, vec, эпизоды, community-membership) с `LIMIT`/keyset-пагинацией. `graph_snapshot`/`GRAPH_MAX_*` — **только** начальное окно сцены; константы не меняются. Результат за пределами сцены: `focus` → ego-network 1 hop → вставка в сцену без полной перезагрузки → центрирование → `Назад` возвращает viewport/selection (MEM-08.3/08.21).

### 4.6. Сообщества vs LOD-тайлы (жёсткое разделение)

`community` — backend-сборка по реальным узлам/рёбрам в chat scope (см. C-6), стабильный `build_id`, `member_count`, `label_basis`; API отдаёт `ref_kind='community'`. Пространственные LOD-тайлы (`buildAggregates`, подпись «Группа · N») остаются **клиентской** техникой рендера, никогда не приходят из API как «сообщество» и не дают поисковых результатов. Клиентские компоненты связности (`computeClusters`, union-find по реальным рёбрам) — фильтр `Все кластеры`, а не сообщество и не поиск. `entity_id` никогда не меняется из-за раскладки. **Typed reranker (`apply_retrieval_rerank`) в UI-поиске не вызывается** (может быть LLM-backed): поиск обязан быть без LLM. Диагностика `why_ranked` — вклад каналов, без текста переписки.

### 4.7. Инварианты

- **S-1.** Один backend-вход на один client input; второго поискового движка/endpoint-конкурента нет; UI-поиск вызывает общий `retrieve`.
- **S-2.** Ноль LLM-вызовов на поиск и на символ; ноль re-embed; ноль мутаций памяти (никаких merge/recompute/backfill/extract из запроса).
- **S-3.** ACL проверяется до ответа, включая server-кэш, client-кэш и «недавние запросы»; кэш ключуется scope+revision и не разделяется между чатами.
- **S-4.** `no_rights` ≠ `no_matches` ≠ `error`; «нет совпадений» означает завершённый поиск в разрешённом scope с понятным описанием.
- **S-5.** Неоднозначность показывается вариантами, «самый популярный» не выбирается; отсутствие источника — «Источник не указан».
- **S-6.** Пустой ввод — обычный обзор, без выдуманных подсказок/историй.
- **S-7.** Никаких утечек внутренних ID/score/«кластер 139»/raw-троек в основную выдачу.
- **S-8.** Один state/компонент для inline и fullscreen; второй `input` запрещён.
- **S-9.** `cursor_stale` — отдельный технический исход, не «пустой результат» (§4.9).

### 4.8. Производительность (критерии измерения, не обещания)

Локальная реакция ≤100 мс (desktop, следующий кадр); server p95 ≤500 мс в прогретом прогоне; client p95 ≤800 мс без эмуляции сети; 6–8 первых результатов без скачка layout; debounce 120–180 мс; отдельно cold/Android/real network. Превышение — дефект с профилированием SQLite/индексов/scoring/рендера, а не «спиннер». Правило 4 резолвера (§1.2.2) и все каналы обязаны укладываться в этот бюджет (тесты с `EXPLAIN QUERY PLAN` и замер p95 на gold-set).

### 4.9. `cursor_stale` отдельно от исходов поиска

`cursor_stale` — не «ничего не найдено» и не ошибка пользователя:
- HTTP 200, `status='cursor_stale'`, `reason_code='cursor_revision_mismatch'`, `items=[]`, `next_cursor=null`;
- `query_state` остаётся осмысленным (`local_matches` — локальный отклик уже показан), клиент **молча** начинает с первой страницы и **не** рисует пустое состояние;
- метрика считается отдельным счётчиком и **не** попадает в `no_matches`/`wrong_entity_rate`;
- тест: смена `rev` между страницами → `cursor_stale`, счётчик `no_matches` не вырос, пустой экран не показан; мутация «свернуть `cursor_stale` в `empty`» валит тест.

### 4.10. Dual-read / rollback / идемпотентность

Гейт `MCA_MEMORY_SEARCH_ENABLED` + `flags.memory_search_enabled`. ON → новое поле; OFF → прежний toolbar (`Найти`/`Все типы`/`Все кластеры`) и клиентский поиск по сцене. Поиск read-only → идемпотентен по определению; пагинация детерминирована при неизменной `rev`.

### 4.11. Обязательные тесты

Gold-set ≥60 запросов (EVAL-07) со всеми интентами и `(query, expected typed refs, допустимые альтернативы, scope, evidence, expected ambiguity/none)`; top-1/Recall@5/MRR/precision for relations; узел за пределами 800 находится и фокусируется; пагинация через 2+ страницы без дублей/пропусков; `cursor_stale` при смене rev (§4.9); гонка `Пап`→`Папаха` (ответ в обратном порядке не перетирает); ACL-негатив (чужой чат не возвращается, не-админ 403); отсутствие LLM-вызовов (счётчик не растёт); отсутствие полного скана (план запроса/инструментация); endpoint вызывает общий `retrieve` (§4.4); отсутствие утечек ID/текста; `no_rights`/`no_matches`/`error` различимы (мутация: подменить статус → тест падает).

---

## 5. C-5. Миграция, гейты, бэкфилл, выпуск

### 5.1. Схема — ровно один аддитивный шаг `v43`

**`mca_entity_canonical`** (идентичность/редирект, обратимо):
```
chat_id INTEGER NOT NULL, entity_type TEXT NOT NULL,
member_node_id INTEGER NOT NULL,        -- nodes.id как есть
canonical_node_id INTEGER NOT NULL,     -- = member для resolution='self'
resolution TEXT NOT NULL,               -- 'self'|'alias'|'merged'
stable_kind TEXT,                       -- 'tg_user' | NULL
stable_value TEXT,                      -- '428494' | NULL
method TEXT NOT NULL,                   -- 'alias_map'|'explicit_evidence'|'manual_admin'
evidence_ref_id INTEGER,                -- mca_source_refs.source_ref_id
confidence TEXT NOT NULL,               -- 'confirmed'|'tentative'
status TEXT NOT NULL DEFAULT 'active',  -- 'active'|'revoked'
created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
PRIMARY KEY (chat_id, entity_type, member_node_id)
```
Индексы: **`UNIQUE (chat_id, entity_type, stable_kind, stable_value) WHERE status='active' AND stable_kind IS NOT NULL`** — один узел ↔ не более одной активной стабильной идентичности и один `stable_value` ↔ один узел (§1.2.1, ID-11); `(chat_id, canonical_node_id)`.

**`mca_community_builds`** (реестр сборок сообществ):
```
build_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL,
algorithm TEXT NOT NULL, algorithm_version TEXT NOT NULL,
params_json TEXT NOT NULL DEFAULT '{}',
graph_revision TEXT NOT NULL,
node_count INTEGER NOT NULL, edge_count INTEGER NOT NULL,
prev_build_id TEXT, change_summary_json TEXT NOT NULL DEFAULT '{}',
status TEXT NOT NULL,                   -- 'building'|'active'|'superseded'|'failed'
started_at INTEGER NOT NULL, finished_at INTEGER
```
Индекс: `(chat_id, status, started_at DESC)`.

**`mca_community_members`**:
```
chat_id INTEGER NOT NULL, build_id TEXT NOT NULL,
community_id TEXT NOT NULL, node_id INTEGER NOT NULL,
member_weight REAL NOT NULL DEFAULT 1.0, created_at INTEGER NOT NULL,
PRIMARY KEY (chat_id, build_id, community_id, node_id)
```
Индексы: `(chat_id, build_id, node_id)`, `(chat_id, build_id, community_id)`.

Ничего больше: **никаких** новых колонок в `nodes`/`edges`/`graph_facts`, никакой таблицы доказательств, никакой таблицы чекпоинтов (см. 5.3), никакого кэша поиска в БД. Все три таблицы — `CREATE … IF NOT EXISTS` под self-guard, `ALTER` не нужен, старый код их не читает, `PG` — no-op (memory-контур SQLite-only, как v28/v30). `graph_revision` в `mca_community_builds` — **строковый снимок** вычисленной ревизии (§2.4.3) на момент сборки, а не ссылка на несуществующую колонку.

**`graph_facts.revision` уже существует** — добавлена миграцией **v31** (`_SELF_MODEL_FACT_COLUMNS`, `revision INTEGER NOT NULL DEFAULT 1`) вместе с `subject_entity_id`/`perspective`/`memory_kind`/`valid_from`/`valid_to`/`confidence_basis`. Шаг `v43` её **не добавляет и не меняет**; контракт использует её как существующее поле. Не путать две одноимённые колонки: `graph_facts.revision INTEGER` (v31) и `mca_source_refs.revision TEXT` (v17, только для ключа дедупа).

### 5.2. Гейты (существующий реестр, global/chat inheritance)

| Гейт (env-аварийный) | Каталог (product) | Что включает |
|---|---|---|
| `MCA_MEMORY_IDENTITY_ENABLED` | `flags.memory_identity_enabled` | C-1 read-резолвер, чтение redirect'ов, единая точка создания узлов (§1.4.1) |
| `MCA_RELATION_EVIDENCE_ENABLED` | `flags.relation_evidence_enabled` | C-2 запись/чтение edge-evidence |
| `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` | `flags.memory_maintenance_policy_enabled` | C-3 политика решений + отчёт по квоте (без удаления) |
| `MCA_MEMORY_SEARCH_ENABLED` | `flags.memory_search_enabled` | C-4 ручка + новое поле карты |
| `MCA_MEMORY_COMMUNITIES_ENABLED` | `flags.memory_communities_enabled` | C-6 сборка/чтение сообществ |
| `MCA_MEMORY_BACKFILL_ENABLED` | `flags.memory_backfill_enabled` | бэкфилл (default OFF до замеров) |
| `MCA_MEMORY_REPLY_CONTEXT_ENABLED` | `flags.memory_reply_context_enabled` | C-7 evidence summary к Writer, режимы retrieval для ответа |
| `MCA_MEMORY_ATTRIBUTION_ENABLED` | `flags.memory_attribution_enabled` | C-8 соц/эпизод/мультимодал-атрибуция |

Эффективность: `settings`-атрибут (per-call, аварийный) **AND** `await chat_params.get_chat_param(chat_id, "flags.…")` (chat override → global hot → default). Дефолт у всех — **OFF до приёмки**, включение штатным релизом по PET_PROJECT (никаких канареек по чатам). Скрытых «включено по умолчанию» нет. `MCA_MEMORY_*` регистрируются тем же способом, что существующие `mca_gates` (имя → (default, OFF-паритет)) и попадают в `param_catalog` как `ParamSpec(pg_id="flags.…")`.

#### 5.2.1. `chat_id=None` и смешанные scope

- **Глобальный/владельческий вызов без чата** (`chat_id=None`, например owner-scope диагностика, глобальный бэкфилл, `/api/memory/search` без `chat_id`): chat-слой **читается с ключом `None` и возвращает пустой словарь** — per-chat override не применяется, но вызов не пропускается и не бросает исключение; значение берётся `hot.get` → `settings`-дефолт. Фактический код уже ведёт себя так (`get_chat_param` → `get_chat_params(None)` → `{}` → `hot.get`), поэтому контракт это фиксирует и требует явного поведения через `get_chat_param_sourced(...)` с возвратом источника `global`/`factory`; исключение недопустимо.
- **`scope_all` (несколько чатов):** гейт вычисляется **на каждый чат**; в выдачу попадают только чаты, где effective-значение ON. Чат, у которого chat-override выключает гейт при global ON, **исключается** (chat побеждает global — существующая семантика наследования) и отражается в `scope.partial=true` + `debug.channels[].excluded_chats=N`; «global ON перебивает chat OFF» запрещено.
- **События/диагностика:** запись с `chat_id=None` не приписывается ни одному чату; метрики scope_all не попадают в per-chat знаменатели.
- **Тесты:** `test_gate_resolution_chat_none` (источник = global/factory, chat-override того же ключа не читается, исключения нет); `test_gate_resolution_scope_all_mixed` (2 чата ON, 1 OFF → 2 чата в выдаче, `partial=true`, excluded=1); `test_gate_chat_beats_global` (global ON + chat OFF → OFF для этого чата); бэкфилл с `chat_id=None` не пишет per-chat checkpoint другому чату.

### 5.3. Бэкфилл (ограниченный, с чекпоинтами)

Baseline ДО миграции: `VACUUM INTO`-бэкап, `PRAGMA integrity_check`, версия схемы, `COUNT(*)` по ключевым таблицам, fingerprint/поколение embedding-индекса, hash-паритет активных промптов. Тест миграции — на копии.

| Шаг | Объём | Запись | Чекпоинт/resume |
|---|---|---|---|
| B1 | dry-run кандидатов дублей по чату/типу/алиасу/источнику; отчёт: кандидатов/подтверждено/сомнительно/влияние на ссылки | **никакой** | `task_jobs.payload` |
| B2 | только безопасно подтверждённые слияния (явный evidence), по чату, в транзакции | `mca_entity_canonical` | per-chat checkpoint, idempotent rerun |
| B2-0 | засев self-строк `tg_user` по §1.2.1 (uid → ровно один узел, ноль перезаписей); конфликт закрепления → пропуск + `identity_seed_node_conflict`, идемпотентно | `mca_entity_canonical` | per-chat checkpoint |
| B3 | evidence для **изменённых/конфликтных** рёбер (см. ниже), копия `(source_ref_id, verification, independence)` из связей факта, `method='metadata'`, `claim_key='edge_from_fact'` | `mca_source_refs`+`mca_evidence_links` | per-chat/dataset курсор |
| B4 | сборка сообществ по чатам, батчами | `mca_community_*` | per-chat build_id |
| B5 | ничего не делает с: текстами фактов, `vec0`/`graph_facts_vec`, embeddings, старыми ID, промптами | — | — |

**B3 — узкий охват вместо «всех рёбер»** (иначе объём неконтролируем):
- только (а) ребра с `fact_id IS NOT NULL`, у которых ещё нет ни одного edge-evidence-link; (б) рёбра, затронутые слияниями B2 (их `source_id`/`target_id` переведены в канонический); (в) рёбра, чей `origin_class` = `legacy_unknown`, но `fact_id IS NOT NULL` (внутреннее противоречие);
- оценка объёма до запуска: `SELECT COUNT(*)` по каждому из трёх классов на чат → в отчёт; вставок ≈ `edges × (1 + avg_fact_links)`; лимит на прогон — `limits.memory_backfill_max_rows` (централизованная константа, `ParamSpec`), остановка с чекпоинтом, пауза/возобновление существующим supervisor;
- dry-run количество обязательно до применения; расхождение с фактическим применением >5% → остановка и отчёт, а не «догоняем».

Правила: отсутствующее обоснование **нельзя** доделать выдуманным LLM-источником — остаётся `legacy_unknown`; изоляция сбоев по чатам; тяжёлая операция никогда не запускается из UI-запроса; повтор не удваивает вес.

### 5.4. Откат

Флаги OFF (поведение baseline, прежний UI) → при необходимости предыдущий релиз по SHA. Схема деструктивно не откатывается: новые таблицы инертны для старого кода. Слияния отменяются `status='revoked'`. Данные не удаляются (в т.ч. квота — §3.4.1).

### 5.5. Добавочная нагрузка

Ноль обязательных LLM-вызовов на сообщение (все новые решения детерминированы); ноль новых LLM на поиск; запись — только там, где уже идёт извлечение/обслуживание. Скрытая цена §3.4.1 (память не удаляется) — рост числа строк, оценивается замером и показывается в админке. Рост **не** попадает в горячий путь: каналы retrieval bounded (`top_k`, FTS/vec `LIMIT`, keyset-пагинация), личный пул пользователя никогда не сканируется целиком, поэтому p95 не должен зависеть от числа строк; это проверяется A/B-замером на реальной БД, а не принимается на веру. При подтверждённой регрессии заранее принято снижать ранг/вероятность вызова старых фактов, а не удалять их (§3.4.1).

---

## 6. C-6. Семантические сообщества (backend, версионируемые)

- Считаются по реальным узлам/рёбрам в chat scope, вход не ограничен экранными 697/800/150.
- Веса рёбер: `confirmed` = 1.0, `tentative` = 0.5, `legacy_unknown` = 0.25, `cooccurrence` (из `mca_associations`) = 0.1; параметры — централизованные константы с тестами, algorithm/version пишутся в `mca_community_builds`.
- Запуск асинхронный/пакетный (по изменениям + периодическое восстановление drift), никогда на `/status`, `/menu`, ответ, zoom/pan. Планировщик — существующий `memory_maintenance` (не новый воркер).
- Подпись: из реально доминирующих сущностей/тем с источниками; иначе нейтральное `Сообщество N` + «как сформировано». LLM-наименования на горячем пути нет.
- `community_id` стабилен, пока сборка активна (перезагрузка/мелкие изменения не меняют ID); split/merge фиксируются в `change_summary_json`; `entity_id` от раскладки не меняется никогда.
- API отличает community от render-tile; `member_count`, `confirmed/tentative` доли, `last_activity`, `density` — из настоящих метрик, неизвестное = «Неизвестно».

Тесты: сборка по реальным данным (не по совпадению имён/близости), устойчивость ID при повторной сборке без изменений, split/merge описан, отсутствие сборки на горячем пути (счётчик запусков), `cooccurrence` не повышает плотность как подтверждённое ребро.

---

## 7. C-7. Память на стороне ответа (MEM-05.4, MEM-06.1…06.10)

Контракт ответного пути отсутствовал в первой редакции — это дыра в покрытии эпика, а не «опция». Всё ниже опирается на существующий контур (retrieval + Writer + tool loop), без новых LLM-вызовов на ход (INV-10) и без второго поиска.

### 7.1. Запрос retrieval для ответа: схема и три режима

Запрос — расширение `RetrievalRequest` (§4.4), не новый тип. Поля (MEM-06.2): `query`, `chat_id`/`chat_ids`, `trigger_ref` (реальный `tg_message_id`/SourceRef), `intent ∈ fact|who|what-happened|history|relationship|current|follow-up|broad-theme`, `subject_ids` (см. ниже), `ambiguous_subjects` (из C-1), `time_from/time_to`, `purpose`, `access` (ACL scope).

**Семантика существующего `subject_entity_ids` — это Telegram `user id`, а не `nodes.id`.** Факт (проверено на линии): `build_memory_request` кладёт туда `int(addressee_uid)`/`int(reply_parent_uid)`, а `apply_identity_prior` сравнивает их с `RetrievalCandidate.subject_entity_id`, который выводится из `graph_facts.target_user` (`int(row["target_user"])`). Поэтому:

- **`subject_entity_ids` не перегружается** — остаётся кортежем uid и обслуживает только identity-prior;
- для канонических узлов из C-1 вводится **отдельное поле** `subject_node_ids: tuple[int, ...]` (`nodes.id` после redirect-схлопывания). Ветка `entity`-канала (§4.4) и карточки читают его; смешивать uid и node id в одном кортеже **запрещено** (это уже приводило бы к ложному exact-subject prior, когда uid случайно совпадает с `nodes.id`);
- если у канонического узла есть активная self-строка `mca_entity_canonical` с `stable_kind='tg_user'`, оба поля заполняются согласованно (uid + node id); если uid неизвестен — заполняется только `subject_node_ids`;
- ключи кэша/ревью (§2.4.3) включают оба поля, чтобы запрос с uid и запрос с node id не считались одним и тем же при разных смыслах.

Три режима (MEM-06.6) отображаются на существующие `mode`/`scope`, без нового маршрутизатора и без LLM:

| Режим | Что делает | Механика |
|---|---|---|
| `specific` | точный субъект/факт | exact/alias канал + identity prior + FTS фактов; эпизоды только если reply-linked |
| `episodic` | восстановление последовательности | эпизоды-первыми (существующий `mode='history'` bias) + reply-граф цепочка + хронология |
| `thematic` | широкий обзор | `community`/membership + FTS по всей доступной scoped истории |

Выбор режима — существующая planner/tool логика с явным fallback `auto`; неизвестный/неуверенный интент → `auto` (существующие `_HISTORY_MARKERS`), не «угаданный» режим. Тест: детерминированный выбор на 20 фиксированных входах, счётчик LLM на пути выбора = 0.

### 7.2. Человеческое evidence summary для Writer (MEM-06.8)

`EvidenceBundle` получает поле `summary_text` — человекочитаемые строки с временными и источниковыми маркерами:
`«А сказал(а) 12.10.2026: …»`, `«пересланное сообщение, первоисточник: …»`, `«предположение / гипотеза из N совпадений»`, `«эпизод: начало/конец …»`.

Жёстко:
- никаких `node_id`, `edge_id`, `source_ref_id`, `cosine`, `channel=`, `ent:`/`fact:` в `summary_text` (проверяется регэкспом в тесте);
- время — через `chat_clock.snapshot(chat_id)` (per-chat IANA), не UTC-числом;
- это **дополнение к существующему bundle**, а не изменение активных промптов (INV-09): hash активных промптов до/после обязан совпасть;
- никакого скрытого post-writer rewriting и второй Writer-стадии (MEM-06.8/INV-10);
- `summary_text` уходит только Writer; в Telegram не выводится, в логи — без текста (R17).

### 7.3. Factcheck ≠ память (MEM-06.9)

- Память может утверждать только «N утверждал X в момент T». В `RelationView`/`SearchItem`/`EvidenceBundle` статус истинности — `asserted_by_source`, никогда `true`.
- Внешняя истинность — только существующие `factcheck_service`/search tools; их результат пишется в отдельное поле `external_verification` (verdict/источник/дата) и **не** меняет `graph_facts.status`, `mca_provenance_status` и `edges.status` автоматически.
- Тест: заведомо ложное, но сказанное утверждение возвращается как «сказано» (не «подтверждено»), factcheck даёт `refuted`, статус факта не изменился; мутация «писать `confirmed` из вердикта factcheck» валит тест.

### 7.4. Никаких слепых квот по классам (MEM-06.5, INV-12)

- Бюджет контекста определяется **реальной** ёмкостью модели (`adaptive_context_budget_enabled`, `model_capacity`, суммарный payload) и доказательной полезностью; фиксированное число сниппетов на класс, «топ-697 для UI» и подобные квоты в памяти/контексте запрещены.
- Существующие `_MEMORY_LOOKUP_PURPOSE_DEFAULTS` (`max_items` **5/10/5/10/10/8** — identity 5, appearance 10, speech_style 5, biography 10, relationships 10, general 8) остаются **капом выдачи инструмента** `get_user_context`, а не квотой retrieval; протаскивать их в бюджет контекста запрещено (тест: изменение `max_items` не меняет число фактов в payload Writer).
- Если payload не помещается — отбрасываются наименее обоснованные повторения, сохраняются инструкции/непосредственный вопрос/нужные доказательства, и `context_partial=true` + причины отражаются в debug (§9).

### 7.5. `get_user_context` (MEM-06.10)

- Переиспользует новый resolver (§1) и общий retrieval (§4.4) через существующий `ToolRouter::_get_user_context`; схема инструмента и имена аргументов сохраняются.
- Purposes **уже шесть** в `_MEMORY_LOOKUP_PURPOSE_DEFAULTS` (`identity 5, appearance 10, speech_style 5, biography 10, relationships 10, general 8`), `_MEMORY_LOOKUP_PURPOSES` — кортеж тех же ключей. Ветка `relationships` **существует и диспатчится уже сегодня**: `_memory_lookup_relationships` читает `db.get_persona_card(chat_id, name, max_items, now).links` и возвращает штатный payload с `facts`/`sources`/`empty_reason`. Добавлять её не нужно.
- Контракт эту ветку **не создаёт и не переименовывает**: требуется только провести её чтения через C-2/common retrieval (основания ребра, `legacy_ids`, `has_unsupported_sources`) **без изменения схемы** и без второго поиска; собственный SQL-поиск в ветке не появляется.
- `relationships` никогда не деградирует до `general` и не может вернуть `invalid_purpose` — он входит в словарь purposes. `invalid_purpose` остаётся только для действительно неизвестной строки purpose (существующее поведение кода).
- Тест: все 6 purposes работают; `purpose='relationships'` возвращает рёбра и **не деградирует** (`invalid_purpose`/`general` не наблюдаются); у ребра без основания — «источник не указан»; число вызовов LLM = 0; второй резолвер/поиск не появился (AST-проверка импортов).

### 7.6. Тесты C-7

Режимы `specific`/`episodic`/`thematic` детерминированы и дают различимую выдачу на одном запросе; `episodic` восстанавливает порядок; `thematic` не режется по классам; 0 LLM-вызовов на поиск/выбор режима; `summary_text` без внутренних id и с датой/автором; hash активных промптов неизменен; factcheck не переписывает статус памяти; `max_items` не влияет на контекст; `context_partial` честен; `get_user_context` со всеми 6 purposes, `relationships` не деградирует до `general`/`invalid_purpose`.

---

## 8. C-8. Социальная, эпизодическая и мультимодальная атрибуция (MEM-05.1…05.7)

### 8.1. Слои — представления, не хранилища

| Слой | Источник (существующий) |
|---|---|
| оперативный локальный контекст | `smart_messages` (tail) |
| точные эпизоды/последовательность | `mca_episodes`, `mca_stories`, `lore_stories`, `thread_chain` |
| устойчивые знания/факты | `graph_facts`, `edges`, `mca_source_refs` |
| досье/социальный контекст | `get_user_context`, `users_meta`, досье-таблицы |
| собственные сообщения/обещания бота | `mca_bot_outputs` |
| опыт решения задач | `mca_experience`, `mca_experience_jobs` |

Ни одного нового durable-store на слой (MEM-05.1). Все чтения — через общий retrieval (§4.4) и C-1 resolver.

### 8.2. Адресат и reply/quote/forward

Приоритет (MEM-05.2): точный `reply_to_id` → существующий `thread_chain` target → достоверный alias/uid в chat scope (C-1) → ближайший семантический контекст. Несколько возможных адресатов → `ambiguous` в выдаче и в карточке; новый адресат при бессвязном чате не выдумывается. Цитата/пересылка приписываются первоисточнику (R-9), тест T6 в C-1.

### 8.3. Тон и намерение — из последовательности, не из словаря

Отличие подкола/спора/цитаты/мема/серьёзного вопроса определяется последовательностью сообщений и существующими сигналами (`claim_envelope`, `mca_humor_*`, `mca_intents`), не списком русских стоп-слов (INV-13). Классификация остаётся **совещательной**: без сигнала — `assertion_mode='unknown'` (§3.3.1), и одиночный эпизод не становится `stable_trait` (§3.5). Стиль — по существующей «Речь и характер»; обязательной «морализации» нет.

### 8.4. Собственные сообщения бота

`mca_bot_outputs` → `independence='self_referential'`, `origin='bot_direct_reply'`. Разрешено отвечать «что я обещал/говорил», запрещено подтверждать внешний факт (R-3) и запрещено использовать для самоподражания. В retrieval попадает отдельным каналом `bot_self_history` с весом ниже подтверждённого внешнего основания; в реальном ответе не цитируется «граф показал» (MEM-05.4).

### 8.5. Мультимодальная память

- Из фото/GIF/sticker/video/voice/альбомов переносится **фактически выполненная** выжимка: `mca_media_asset_id` + SourceRef сообщения + `timestamp` + `vision_status ∈ processed|not_processed|unavailable` + описание + область видимости.
- `not_processed`/`unavailable` никогда не выдаются за понимание изображения (в UI — «не обработано»/«недоступно»).
- Повторный тяжёлый vision на поиск/просмотр графа запрещён (тест: счётчик vision-вызовов на поиск = 0).
- Репост + «посмотри видео» связываются контекстом соседних сообщений/reply через существующий universal vision; новый ingest/action не дублируется (MEM-05.6), обработка альбомов не отменяется.

### 8.6. Опыт

`mca_experience` lesson/retrieval + доказанные feedback outcomes; выводы помечаются `experimental`/`stable`; одна неудача не создаёт постоянное правило; автоматическое повышение в personality core запрещено (INV-09).

### 8.7. Тесты C-8

Адресат при нескольких кандидатах → `ambiguous`; self-output не независим и не подтверждает внешний факт; `not_processed`/`unavailable` отображаются честно; vision-вызовов на поиск = 0; одна неудача не даёт правила; слои читают только существующие таблицы (AST/список SELECT-источников); репост+«посмотри видео» связаны без дубля ingest.

---

## 9. Наблюдаемость

События — только `emit_mca_event` (`mca_events`), поля `trace_id, chat_id, kind, outcome, reason_code, duration_ms, counts, config_version`; **без** сырого текста, токенов, `initData`, ПДн (R17).

`entity_resolution`, `identity_seed_missing`, `identity_seed_ambiguous`, `identity_seed_node_conflict`, `entity_type_conflict`, `redirect_cycle_detected`, `merge_decision`, `assertion_recorded`, `edge_evidence_attached`, `edge_legacy`, `conflict_detected`, `dedupe_candidate`, `graph_fact_quota_exceeded`, `memory_retrieved`, `memory_rejected`, `context_selected`, `community_refresh`, `map_search`, `map_neighbors`, `cursor_revision_mismatch`, `backfill_checkpoint`.

Метрики с знаменателем: доля рёбер с источником; доля `legacy/unverified`; `mentions_only_edges`; merge candidates/confirmed/false merges; ambiguities; `identity_not_seeded_chats`; search `query_to_first_local`, `query_to_first_server`, `p50/p95`, `top1/Recall@5/MRR`, `wrong_entity_rate`, `ambiguity_coverage`, `stale_result_suppression`, `cursor_stale_rate` (отдельно от `no_matches`), `offscene_hit_rate`, `search_unauthorized_leaks` (обязан быть 0), DB query plan, фоновые LLM-вызовы (обязаны быть 0 на поиск/сообщение), живые факты сверх квоты (числа, §3.4.1), **`deleted_by_merge_or_dedupe` (обязан быть 0: слияние и дедуп обслуживания только аддитивны, §3.4.1.1)**. Нет данных → «Не измерялось», не 0/OK.

Трасса одного ответа (для админа): запрос → разрешённая личность → кандидаты → почему выбраны/исключены → подтверждающие SourceRef → что ушло в L2 (`context_partial`) → что доставлено. Внутренние ID в текст бота не попадают.

---

## 10. Visual Preservation Map (только то, что меняется)

Сцена проверяется реальным рендером (Playwright + Browser Use) до и после; ниже — контракт для Builder. Toolbar подтверждён в двух местах `web/index.html` (inline и fullscreen).

| BLOCK | Сейчас | ACTION | MUST PRESERVE | ALLOWED CHANGE | WHY |
|---|---|---|---|---|---|
| Inline-карта в «Статусе» (`status-graph`), строка поиска | `[input «Поиск по имени или алиасу…»][Найти][Все типы][Все кластеры][Сбросить вид][статус]` | **REDESIGN** (санкция §9.4) | рамка карточки, glass, строка счётчиков, кнопка `Полный экран`, сам canvas | один input `Найти в памяти` / плейсхолдер `Человек, событие, факт или вопрос…`, иконка+`×`+индикатор внутри поля, панель до 6–8 результатов; `Сбросить вид` → иконка/контекст сцены; типы/кластеры → контекстные действия инспектора | владелец требует ровно одно поле, без обязательной кнопки |
| Fullscreen-панель (`graphFullPanel`) | тот же toolbar целиком | **REFINE** | полноэкранный режим, back-stack, safe-area, один state с inline | тот же компонент/состояние, без второго `input` и без дублирующих контролов | SC-21/SC-28 |
| Сцена/физика/LOD (`cognitive-map.js`, `lodFor`, гистерезис, `reducedMotion`, mobile simple; тайлы `buildAggregates` с подписью «Группа · N», фильтр `computeClusters` по рёбрам) | витрина 800/2400, тайлы «Группа · N» | **KEEP** | пороги, гистерезис, физика после стабилизации, mobile-упрощение, dispose RAF/listeners, смысл тайлов как раскладки | только подсветка выбранного/пути; никакой смены семантики; тайлы остаются раскладкой и **не** становятся сообществами | INV-15, MEM-08.7/08.8 |
| Инспектор узла/ребра | name/type/group/degree, соседи | **REFINE** | существующие бейджи, кнопки, карточка источника | + алиасы, статус идентификации, эпизоды, «Источник/Происхождение не установлено», для ребра — sources/validity/independent_support/`legacy_ids`/`has_unsupported_sources` | MEM-08.9, C-2 |
| Счётчики | «N узлов · M рёбер · показаны не все» | **REFINE** | вторичный тон, компактность, честное `truncated` | `В памяти: N сущностей и M связей` / `Показано: n и m` / `Область` / `Сообщества` / `Данные обновлены`; неизвестное = «Неизвестно» | MEM-08.5 |
| Легенда типов | `groups` vis-network | **KEEP** | категории, доступность в карточках | сворачиваемая/контекстная | MEM-08.24 |
| Четыре ленты ниже карты (убеждения/цепочка/таймлайн/уроки) | работают | **KEEP** | порядок, данные, карточки, источники | ничего | INV-15 |

Жёстко запрещено: второй поисковый `input` (в т.ч. в fullscreen); прежняя многопольная форма под иконкой «расширенный поиск»; превращение «Группа · N» в «сообщество»; выдуманные узлы/рёбра; «красивое» переупорядочивание лент; donut/radial для категорий без знаменателя.

Ответственность saga-состояний (MEM-08.23) в UI: `empty_input`(обзор) → `local_matches` → `server_searching` → `candidates` | `ambiguous` | `no_matches` | `weak_legacy_only` | `partial` | `error/offline` | `no_rights`; `cursor_stale` — не экран, а тихий перезапуск с первой страницы (§4.9). Локальный отклик показывается сразу и никогда не выдаётся за полный серверный поиск.

---

## 11. Параллелизация и write-scopes

**Порядок барьеров:** G0 (подтвердить union-ветку `integ/unify-release` @ `640da3eb`) → A0 (переаудит §0.3.1) → код. До G0 — только чтение и этот документ. **A0 выполнен 07.11.2026** (итог — §0.3.1): MEMORY-01 и MEMORY-03 разблокированы, MEMORY-04 — этой редакцией, MEM-08-S3 — исправлениями 1–2.

| Срез | Можно начинать | Зависит | Файлы (write scope) | Класс |
|---|---|---|---|---|
| G0 подтверждение union-ветки | сразу | — | Git-ветка `integ/unify-release` (владелец DevOps/Orchestrator) | `SERIALIZE` |
| A0 переаудит | после G0 | G0 | отчёт в feature-артефакте (без кода) | `READ_ONLY_PARALLEL` |
| MEMORY-00b (закрытие аудита) | после A0 | A0 | `plans/features/memory-cognitive-02/*` | `PARALLEL_SAFE` |
| MEMORY-01 (типы/контракт в коде: `EntityRef`, `RelationView`, `SearchItem`, константы §1.2.2/§2.3) | после A0 | A0 | `services/memory_contracts.py` (новый) | `PARALLEL_SAFE` |
| MEMORY-02 (identity, resolver, засев, слияния, единая точка создания) | после 01 | C-1, A0 | `services/entity_resolver.py` (новый), `services/summary_aliases.py` (read-extension) | `BLOCKED_BY:schema_v43_part_A` |
| MEMORY-03 (edge-evidence) | после 01 | C-2 | `services/provenance.py`, `services/graphrag_provenance.py`, `services/relation_evidence.py` (новый) | `PARALLEL_SAFE` |
| MEMORY-04 (temporal/политика/квота/lineage-merge обслуживания) | после 01 | C-3, C-1 | `services/summary_memory.py`, `services/graphrag_provenance.py`, `services/memory_maintenance.py` | `SERIALIZE` (`summary_memory.py` + `memory_maintenance.py`; **сериализовано с MEMORY-07**) |
| MEMORY-05 (C-8: соц/эпизод/мультимодал) | после 03+04 | C-2/C-3/C-8 | `services/summary_memory.py`, `services/mca_episodes.py`, `services/mca_vision.py`, `services/tool_router.py` (`_get_user_context`) | `SERIALIZE` (`summary_memory.py`) |
| MEMORY-06 (C-7: единый retrieval + evidence summary) | после 02+03+04 | C-4/C-7 | `services/mca_retrieval_context.py`, `services/direct_context_composer.py`, `services/summary_l2_writer.py`, `services/turn_payload_events.py` | `SERIALIZE` (`mca_retrieval_context.py`) |
| MEMORY-07 (сообщества) | после 02+03 | C-6 | `services/memory_communities.py` (новый), `services/memory_maintenance.py` (регистрация job) | `BLOCKED_BY:schema_v43_part_B` |
| MEM-08-S2 (backend поиск) | после 06 | C-4 | `web/api/cognitive_map.py`, `services/memory_search.py` (тонкий адаптер, без своего поиска) | `SERIALIZE` (`cognitive_map.py`) |
| MEM-08-S3 (omnibox UI) | после согласования формы ответа S2 | C-4 | `web/app.js`, `web/index.html`, `web/static/cognitive-map.js` | `SERIALIZE` (один UI-писатель) |
| MEM-08-S4 (focus/expand/offscreen) | после S2+S3 | C-4 | `web/app.js`, `web/static/cognitive-map.js` | `SERIALIZE` |
| MEM-08-S5 (EVAL-07) | после S1–S4 | — | `tests/`, evidence | `READ_ONLY_PARALLEL` |
| MEMORY-09 (телеметрия/бэкфилл/выпуск) | параллельно с 02 | C-5 | `services/mca_events.py` (только новые имена), backfill-модуль | `PARALLEL_SAFE` |
| MENU-01 | уже идёт независимо | — | `handlers/menu.py` | `READ_ONLY_PARALLEL` к памяти; **не** писать `web/index.html` одновременно с UI-лейном |

**Сериализуемые точки (ровно по одному владельцу в момент времени):**
`services/database.py` (вся схема v43 + `upsert_edge(touch_recency)` + `resolve_or_create_node`-хук), `services/summary_memory.py`, `services/memory_maintenance.py` (MEMORY-04 меняет `merge_episodes`/`_merge_cluster`/`review`/`_glue_vec_dups`, MEMORY-07 добавляет только регистрацию job — оба пишут один файл, поэтому строго последовательно), `services/summary_aliases.py`, `services/mca_retrieval_context.py`, `services/summary_l2_writer.py`, `services/turn_payload_events.py`, `web/api/memory_agi.py`, `web/api/cognitive_map.py`, `web/app.js`, `web/index.html`, `web/static/cognitive-map.js`.

**Порядок слияния:** `database.py` (v43 part A/B) → identity/засев/evidence (02/03) → retrieval+evidence summary (06) → API поиск (S2) → UI (S3/S4) → сообщества/EVAL (S5). Максимум 3 одновременных писателя, у каждого — непересекающийся scope. `services/summary_l2_writer.py`/`turn_payload_events.py` приходят из релизного corrective на G0 — их правки только в MEMORY-06, не параллельно.

---

## 12. Приёмочные обязательства (сводно)

Нулевая терпимость (release blocker, EVAL-04): одно подтверждённое ложное автослияние двух Telegram user ID в gold; утечка памяти чужого чата; «подтверждённая» связь без источника (`mentions`-only в т.ч.); потеря исходного SourceRef/legacy-id; выдуманная связь в UI; полная перестройка embeddings без смены модели; изменение сохранённых промптов; скрытое удаление фактов квотой; новый обязательный LLM-вызов на ход; вторая поисковая форма/строка; второе определение поиска (не общий `retrieve`).

Обязательные доказательства: gold-set ≥200 размеченных проверок (EVAL-01/02), отдельный search-gold ≥60 (EVAL-07), A/B baseline vs кандидат с зафиксированными SHA/настройками/индексами, реальные p50/p95 и скриншоты/запись desktop+Android, мутационные тесты по каждому контракту, независимая проверка Reviewer на реальных SQL/данных, а не на заглушках. Плюс специфические доказательства этой редакции: `EXPLAIN QUERY PLAN` для правила 4 и всех каналов; тест диапазона `ПАПАХА`/`Папаха`/`папаха` + негатив другой буквы (T14b); тест отсутствия ложного слияния двух uid (T3b/T12b, `identity_seed_node_conflict`); тест идемпотентности SourceRef ребра (§2.4.1); тест «квота не удаляет» (§3.4.1); **тест lineage-merge обслуживания: источники живы, FTS/vec живы, `derived_from`+обратные `supersedes` на каждый источник, `deleted_by_merge_or_dedupe=0`, переписанные тесты `tests/test_memory_maintenance.py` (§3.4.1.1)**; тест условного пуржа при `memory.infinite_retention` (§3.4.1); тест недеградации `purpose='relationships'` (§7.5); тест связи endpoint↔`retrieve` (§4.4); тесты `chat_id=None`/`scope_all` (§5.2.1); тест `cursor_stale` (§4.9); тесты C-7/C-8 (§7.6/§8.7).

---

## 13. Продуктовые решения владельцу и follow-up

**Остались ли продуктовые решения владельцу: нет.** Проверено по правилу Human Gate:

1. Единственное поле поиска уже выбрано владельцем (MEM-08.14/SC-21) — это не развилка.
2. Выпуск без канареек и разрешений на флаг — стоячее решение PET_PROJECT; отдельное согласие не требуется.
3. Смена семантики `_dedup_decide` (сходство вектора перестаёт инвалидировать факты) — не новый выбор, а прямое следствие требований MEM-02.5/MEM-04.4/INV-06 («не уничтожать по сходству»).
4. Отказ от удаления фактов квотой (§3.4.1) — тоже не новый выбор: это прямое требование MEM-04.6/INV-01/INV-08. Цена (память растёт вместо удаления, в админке видны числа сверх порога) следует из уже принятого инварианта, а не из нового решения владельца.
5. Линия реализации (`integ/unify-release` @ `640da3eb`, надмножество production) — техническое следствие требования «одна память, один контур», а не продуктовый выбор; закрыто этим документом и G0.
6. Никаких новых затрат, хранения ПДн, необратимых операций или интероп-решений контракт не вводит; единственная внешняя зависимость эпика (BotFather для MENU-01) к памяти не относится и уже учтена.

**PM follow-up (одна строка, карту не переписываем):** acceptance-тексты в `requirements-map.json` сгенерированы по шаблону и не проверяемы как есть — PM должен заменить их на проверяемые (условие проверки + артефакт-доказательство) отдельной задачей, без изменения идентификаторов требований.
