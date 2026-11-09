# Gate A0 — переаудит объединённой линии перед кодом MEMORY-01

**Дата:** 07.11.2026 · **Роль:** Architect (read-only аудит)
**Контракт:** `plans/features/memory-cognitive-02/contracts.md` (rev3), §0.3/§0.3.1.
**Линия:** `integ/unify-release`, worktree `…/WorkspaceData/worktrees/6f4c07e43141f379/hotfix-meme-publication-initia-d78f499866ee-6ef91e44`.

## 0. Идентификация линии (важно для чтения отчёта)

| Факт | Значение |
|---|---|
| HEAD worktree | `60cd96c0` — **docs-only** коммит поверх `640da3eb` (`git show --stat`: изменён только `contracts.md`, +515/−142) |
| Код линии | = `640da3eb` (последний код-коммит) |
| `git merge-base --is-ancestor release/2.58.161 HEAD` | 0 (true) |
| `git merge-base --is-ancestor evol/impl HEAD` | 0 (true) |
| `_SCHEMA_VERSION_SLOT_CLAIMS` | `42` (`services/database.py:1780`), шаг v43 свободен |
| Файлы-артефакты MEMORY-01+ | `services/memory_contracts.py`, `entity_resolver.py`, `relation_evidence.py`, `memory_communities.py`, `memory_search.py` — **отсутствуют** (не созданы) |
| `mca_entity_canonical` в коде | **0 вхождений** (`git grep -- '*.py'`) — правило 1 C-1 сегодня физически не может сработать |

**Живые прогоны на этой линии (все зелёные):**
`tests/test_mca07_retrieval_context_round1027.py` — 41 passed;
`tests/test_asap8_v63_b03_memory.py` + `tests/test_asap8_v6_d06_isolation.py` — 20 passed;
`tests/test_memory_maintenance.py` + `tests/test_evol_cog_map_api.py` — 36 passed;
`tests/test_ur_c_clock.py` — 28 passed.
Дополнительная проба (in-memory SQLite, схема `nodes` скопирована байт-в-байт):
`EXPLAIN QUERY PLAN SELECT id FROM nodes WHERE chat_id=? AND entity_type=? AND entity_name>=? AND entity_name<? LIMIT 33`
→ `SEARCH nodes USING INDEX sqlite_autoindex_nodes_1 (chat_id=? AND entity_name>? AND entity_name<?)`; интервалы `['П','Р')` → `ПАПАХА`,`Папаха`, `['п','р')` → `папаха`, `Бабаха` не попадает.

---

## 1. `services/summary_memory.py`

| Символ | Строки | Статус | Что фактически на линии | Риск для контракта |
|---|---|---|---|---|
| `_dedup_decide` | 4554–4604 | **PRESENT_AND_VERIFIED (как конфликт)** | Гейт `flags.graph_dedup_enabled` (4564); exact-дубль → `noop` (4567–4572); KNN `_dedup_knn` (4575, 4606–4633); `cosine ≥ HIGH(0.95)` → `noop` (4591–4593); `cosine ≥ LOW(0.85)` → **`supersede`** (4594–4596); ниже → `add`. Защищённые факты пропускаются (4570, 4588). Кандидат проверяется только на подстроки subject/object (4584). | C-3 §3.4: сходство вектора = доказательство, `supersede` = инвалидация по similarity. `noop` не даёт независимому повтору стать CONFIRM. Ровно то, что контракт запрещает; ~п.3 §0.4 подтверждается **на этой линии**. |
| `_enforce_user_quota` | 4536–4552 | **PRESENT_AND_VERIFIED (разрушающая)** | `get_quota_victim` (4544) → `self.db.delete_graph_fact(victim["id"])` (4547) → `log_fact_compression(..., 'quota')` (4548). Вызов в горячем пути записи: 4299–4306. | §3.4.1 подтверждается: квота **физически удаляет** факт (row + FTS + vec). Включена по умолчанию (`GRAPH_USER_QUOTA_ENABLED=True`, `GRAPH_FACTS_PER_USER_QUOTA=50` — `config/settings.py:2977–2978`). |
| `_write_graph_triplets` | 6309–6362 | **PRESENT_AND_VERIFIED (как конфликт)** | Одна транзакция под `serialized()` (6320–6321), `upsert_node`×2 (6332, 6335), `upsert_edge(...)` **без `fact_id`** (6341–6350); комментарий «fact_id остаётся NULL ОСОЗНАННО» (6338–6340). | C-2 §2.5 / R-7: у части рёбер нет ни `fact_id`, ни evidence → `legacy_unknown`, вес ≤ 0.55 обязателен на чтении. |
| Прямой путь записи факта (W1) | 4307–4368 | **PRESENT_AND_VERIFIED** | `upsert_node(subject,'fact')` (4307), `upsert_node(obj,'fact')` (4309), затем ОДНА транзакция `insert_graph_fact(..., subject, object, tg_message_id, forward_from, attribution_method, assertion_kind, commit=False)` (4325–4337) + `upsert_edge(sid,oid,predicate,fact_id=fid,commit=False)` (4338–4341) + commit/rollback (4342–4346), retry 1 раз (4348–4354), `invalidate_graph_fact` при supersede (4355–4362), vec (4364–4367), `_attach_fact_provenance` (4374–4378). | C-1 §1.4.1 W1: здесь появится `resolve_or_create_node`; порядок «факт → ребро» и атомарность пары сохраняются. Конфликт типа (§1.2.3) здесь реализуется без `upsert_node`. |
| `_attach_fact_provenance` | 4459–4503 | **PARTIAL** | Пишет **только факт-уровневый** provenance: `record_fact_provenance` (4496), `update_fact_provenance_columns(subject_ref_id)` (4501–4503). Edge-SourceRef/EvidenceLink не пишет вообще; `revision` для `graph_edge` не задаётся. | C-2 §2.5 требует `graph_edge_source_ref(chat_id, edge_id)` с `revision='stable'` — этого нет; MEMORY-03 пишет новый path, а не расширяет этот. |
| `memorize_self_reply` | 4765–4819 | **PRESENT_AND_VERIFIED** | Гейт `flags.bot_self_awareness_enabled` (4784), `insert_graph_fact(origin='bot_self_reply', status='tentative', target_user=None, importance=2)` (4804–4807), узлы/рёбра НЕ создаются (док. 4781–4782), vec best-effort (4808–4810). | C-8 §8.4/ R-3: self-output уже не «факт о мире» (status tentative) и исключён из всех fusion-чтений (`get_live_graph_facts` 11787, `find_exact_dup_groups` 11805, dedup-источник FTS/KNN). Готово как база. |
| `_canon_fact_name` | 4452–4457 | **PRESENT_AND_VERIFIED** | `self.aliases.canon_name(name)`, без alias — имя как есть. | C-1 §1.2.1: `_canon_fact_name` — валидный источник «исторических написаний» для засева. |
| `_merge_cluster` | **отсутствует в этом файле** | **MISSING (в `summary_memory.py`)** | Живёт в `services/memory_maintenance.py:763–823`. | См. §5 — это не просто «не тот файл», а незакрытый разрушающий путь. |

---

## 2. `services/database.py`

### 2.1. Цепочка миграций до v42

| Версия | Шаг | Что добавил | Идемпотентность |
|---|---|---|---|
| 1–12 | `graphrag_v2` … `graph_facts_metadata_v12` (2824–2847) | база графа, direct-chat, epic60, video origins, `user_memory`(5), `protected_facts`(6), history import(7), AGI memory v8(8), self origin(9), `edges.fact_id`(10), import key scope(11), `tg_message_id`/`forward_from`(12) | `MigrationStep` + книга `schema_migrations`, шаг только при `version > current` (3045–3065) |
| 13–24 | schema book(2848), `task_jobs`(2851), `mca_events`(2854), `message_identity`(2857), `provenance`(2860), `embedding_identity`(2863), `observability`(2866), `dossier_staging`(2869), `episodes_stories`(2872), `bot_outputs`(2875), `embedding_control_plane`(2878), `summary_source_windows`(2881) | как заявлено в контракте §0.2 | каждый шаг self-guarded, повтор — no-op |
| 25–33 | dream_run(2887), style_requests(2893), random_source(2900), experience(2907), intents(2914), random_uses(2923), self_model(2934), media_vision(2943), factcheck_temporal(2952) | v31 добавил **9 nullable-колонок `graph_facts`**, включая `perspective`, `memory_kind`, `scope`, `valid_from`, `valid_to`, `confidence_basis`, `revision INTEGER NOT NULL DEFAULT 1` (1525–1538) | idempotent, PG — no-op |
| 34–37 | embedding_generation_ns(2959), llm_usage_plan_meta(2967), **humor_samples_v36**(2981), humor_samples_v37(2987) | v35 — PG-only; v36/v37 — humor library | PostgreSQL no-op для SQLite-шагов |
| 38–40 | quote_metadata(2996), prompt_journal(3004), **meme_quota_v40**(3013) | v38 — 3 nullable-колонки `smart_messages`; v39 — журнал промптов (SQLite no-op); v40 — DDL у `meme_initiative` | guard `PRAGMA table_info`, `IF NOT EXISTS` |
| 41 | `chat_publish_claim_v41`(3022) | DDL у `publication_coordination.CLAIM_DDL_SQLITE` | шаг только применяет чужой DDL |
| 42 | `slot_claims`(3032) | DDL у `services.slot_claims.SLOT_CLAIMS_DDL_SQLITE`; константа объявлена **выше** 41 (1780/1782), список сортируется по `version` (3064) | idempotent, PG — no-op |

**Статус: PRESENT_AND_VERIFIED.** Все 42 шага существуют, шаг v43 свободен; добавление v43 аддитивно (`MigrationStep(43, …)` в конце списка + `CREATE … IF NOT EXISTS`).
Замечание: `_SCHEMA_VERSION_PUBLISH_CLAIM = 41` объявлен **после** `_SCHEMA_VERSION_SLOT_CLAIMS = 42` (1780/1782) — косметика, но при добавлении v43 константу надо ставить рядом с остальными, не менять существующие значения.

### 2.2. Узлы/рёбра/факты

| Объект | Строки | Статус | Факт |
|---|---|---|---|
| DDL `nodes` | 2293–2302 | PRESENT_AND_VERIFIED | `UNIQUE (chat_id, entity_name)`, `CHECK entity_type IN ('user','topic','event','fact')`, `idx_nodes_chat_type(chat_id, entity_type)` |
| DDL `edges` | 2304–2324 | PRESENT_AND_VERIFIED | `UNIQUE (source_id, target_id, relation_type)`, `fact_id INTEGER` nullable, индексы source/target/chat-weight |
| DDL `graph_facts` база | 2332–2355 | PARTIAL (по дизайну) | база содержит только v1-колонки + `tg_message_id`/`forward_from`; остальные (`weight`,`status`,`supersedes`,`last_confirmed_at` — 7045–7048; 6 provenance — 453–460; 9 self-model — 1525–1538) приходят миграциями. Код читает их как существующие → на линии они есть, но **DDL в одном месте неполный** (legacy-путь бэкапа: восстанавливать только через миграции). |
| `graph_facts_fts` | 2353–2355 | PRESENT_AND_VERIFIED | `fts5(fact, content='graph_facts', content_rowid='id', tokenize='unicode61')`; FTS-строка пишется **вручную** в `insert_graph_fact` (9689–9691) |
| `graph_facts_vec` | `summary_memory.py:103,118` | PRESENT_AND_VERIFIED | vec0 создаётся лениво в MemoryManager; vec-строка пишется `_save_graph_fact_embedding` (4635+), удаляется `delete_graph_fact`/`invalidate_graph_fact` |
| `upsert_node` | 9420–9451 | PRESENT_AND_VERIFIED | `INSERT OR IGNORE` (9437) + `SELECT id ... WHERE chat_id=? AND entity_name=?` (9442); второй тип под тем же именем молча игнорируется → §1.2.3 |
| `upsert_edge` | 9454–9511 | **PARTIAL** | `INSERT … SELECT chat_id FROM nodes WHERE id=?` + `ON CONFLICT(source_id,target_id,relation_type) DO UPDATE SET weight=MIN(weight+excluded.weight,5), last_updated=CURRENT_TIMESTAMP, fact_id=COALESCE(excluded.fact_id, edges.fact_id)` (9486–9497), cap `_EDGE_WEIGHT_CAP=5` (1951). **Нет параметра `touch_recency`** и нет перевода member→canonical. |
| `insert_graph_fact` | 9583–9700 | PRESENT_AND_VERIFIED | 24 колонки, `weight` clamp 0..1 (9642–9645), метафакт-срез (9655–9656), `INSERT OR IGNORE` только при `or_ignore=True` (9660–9662), FTS-строка (9689), `commit=False` для пары fact+edge (9694–9697), `write_transaction` иначе (9699) |
| self-fact путь | `summary_memory.py:4804` | PRESENT_AND_VERIFIED | отдельного `INSERT` в `database.py` нет: self-факт = `insert_graph_fact(origin='bot_self_reply')`; в `database.py` origin разрешён CHECK-ом после rebuild (1908–1915, 7380–7425), self-факты исключены из чтений (10047, 10578, 10641, 11787, 11805, 11958) |
| `delete_graph_fact` | 11714–11726 | PRESENT_AND_VERIFIED (разрушающий) | `DELETE graph_facts_fts` → `DELETE graph_facts_vec` (fail-soft) → `DELETE graph_facts` |
| `get_quota_victim` | 11736–11774 | PRESENT_AND_VERIFIED | счёт живых (`expires_at IS NULL OR > now`, 11754–11759), фильтр protect (weight ≥ 0.8 / confirm < 3 дней / `protected_facts`) (11764–11769), `ORDER BY weight/(age_days+1) ASC` (11770) |
| `purge_expired_graph_facts` | 10674–10783 | PRESENT_AND_VERIFIED | Глобальный `_infinite_retention_on()` → return 0 без SQL (10697–10701); per-chat override (10718–10722); protect: weight ≥ `limits.graph_purge_protect_weight` (0.8), `last_confirmed_at ≥ now−protect_days` (3 дня), `protected_facts` (10750–10756); FTS удаляется тем же предикатом (10775–10778); nodes/edges — по собственному `expires_at` (10757–10770) |
| `invalidate_graph_fact` | 11488–11510 | PRESENT_AND_VERIFIED | `expires_at=now` (не DELETE); vec: при infinite_retention — UPDATE `expires_at`, иначе DELETE (11501–11507) |
| `evidence_independent_count` | `provenance.py:268–283` | PRESENT_AND_VERIFIED | только `derived_from`/`supports` + `verified` + `independent`, дедуп по `source_ref_id`; `mentions` не считается → §2.3 подтверждён |
| `mca_source_refs` дедуп | 390–412 | PRESENT_AND_VERIFIED | `UNIQUE(store, entity_type, entity_id, COALESCE(chat_id,-1), COALESCE(revision,''))` (406–408); **CHECK на `entity_type` нет** |
| `mca_evidence_links` | 413–439 | PRESENT_AND_VERIFIED | `UNIQUE(subject_ref_id, source_ref_id, link_type, COALESCE(claim_key,''))` (430–432) |
| `provenance.ENTITY_TYPES` | `provenance.py:42–45` | **PARTIAL / блокер для C-2** | whitelist: `message, graph_fact, belief, paradigm, episode, story, dossier, user, media_asset, lesson, intent, unknown`. `graph_edge`/`entity` **отсутствуют**, а `SourceRef.validate()` бросает `ValueError` (139–141) → без расширения набора запись edge-evidence невозможна. `graph_fact_source_ref`/`user_source_ref` существуют (182/170), `graph_edge_source_ref`/`node_source_ref` — нет |
| `graph_facts.revision` | 1537 | PRESENT_AND_VERIFIED | колонка **уже есть** (`INTEGER NOT NULL DEFAULT 1`, v31) — «технически не поддерживает» для ревизии факта не наступает |

---

## 3. `services/mca_retrieval_context.py`

| Элемент | Строки | Статус | Факт |
|---|---|---|---|
| Каналы | 298–305 | PRESENT_AND_VERIFIED | `exact 100`, `lexical 80`, `vector 60`, `reply_graph 40`, `episode 20`; `_CHANNEL_ORDER` — тот же список. Каналов `entity`, `community`, `bot_self_history` **нет** |
| `RetrievalRequest` | 314–334 | PARTIAL | поля: `chat_id:int` (обязателен, один), `query`, `trigger_ref`, `scope`, `mode`, `top_k=12`, `time_from/to`, `participants`, `reply_depth`, `subject_entity_ids`, `speaker_entity_id`, `reply_target_entity_id`, `quote_source_ref`. Нет `chat_ids`, `channels`, `purpose`, `cursor`, `limit`, `offset_bucket` |
| `subject_entity_ids` семантика | 331, 368–397, 835–857 | **CONFLICT** | prior сравнивает с `RetrievalCandidate.speaker_entity_id` (= `smart_messages.user_id`, 831) и `subject_entity_id` (= `int(graph_facts.target_user)`, 839–846). `target_user` — это **имя-канон**, а не id, поэтому `subject_entity_id` почти всегда `None`, а `subject_entity_ids` фактически = **Telegram uid**. Контракт §7.1 называет их «subject_entity_ids (из C-1)» (node id) — на линии туда придут uid. |
| `apply_identity_prior` | 368–397 | PRESENT_AND_VERIFIED | детерминированные бусты +150 (exact subject) / −80 (другой человек) / +15 (участник) / −10 (`provenance_backed=False`); вызов в `retrieve` только при `_canonical_enabled()` (764–774); эпизоды при `mode='history'` не штрафуются (766–771) |
| `retrieve()` | 639–811 | PARTIAL | Один `chat_id` во всех каналах (684, 697, 707, 720, 734); `scope ∈ auto|time_range|participants|parent|branch`, `mode ∈ auto|history|exact`; `top_k` только снизу (`max(1, top_k)`, 776–782) — **верхнего капа нет**; курсора/лимита/смещения нет; `apply_retrieval_rerank` — отдельная функция 971 (в `retrieve` не вызывается) |
| `build_memory_request` | 479–518 | PRESENT_AND_VERIFIED | собирает `RetrievalRequest(mode='auto', top_k, participants=uids, subject_entity_ids=uids)`; адресат/reply-parent → subject, участники → participants |
| `EvidenceBundle` | 198–239 | PARTIAL | 20 полей + v2-слоты (`direct_addressee`, `reply_addressee`, `quoted_speaker`, `subjects`, `structured`, `lessons`). **Нет `summary_text`** (C-7 §7.2) |
| `EvidenceItem` | 161–169 | PARTIAL | `source_ref_id, entity_type, entity_id, sent_at, revision, label` — нет `speaker/subject`, `assertion_mode`, `link_type`, `counts_as_independent` (§2.1 `sources[]`) |
| Расширяемость | — | **аддитивно** | `RetrievalRequest`/`EvidenceBundle` — `@dataclass(frozen=True)` без `__post_init__`-контрактов; все вызовы — keyword-конструкторы (`build_memory_request:509`, `chat_statistics:716`, `direct_chat_service:8830`, `mca_exploration:1600,2093`). Новые поля **с дефолтами** не ломают ни один вызов. Но: `chat_ids` потребует правки **каждого** канального вызова (`search_messages_fts`, `search_graph_facts_fts`, `retrieve_fact_candidates`, `collect_thread_chain`, `_episode_candidates(912)`) — все принимают один `chat_id`; `limit`/`cursor` — новая keyset-пагинация в каналах, а не «поле в запросе» |

---

## 4. Файлы, пришедшие после аудита MEMORY-00

| Модуль | Строки | Статус | Что важно для контракта |
|---|---|---|---|
| `services/chat_clock.py` | 427 | **PRESENT_AND_VERIFIED** | `snapshot(chat_id, *, at_utc=None, clock=None)` (237), `TimeSnapshot` (60) с `timezone_source ∈ chat|chat_legacy|global|global_legacy|legacy_goodmorning|factory|utc_fallback` (67–68), `resolve_chat_timezone` (125), `utc_fallback` (206, 274), `zoneinfo` + DST/fold (267), `outbound_clock_meta` (414), `render_chat_time_context` (328). C-3 §3.2 реализуем **как написано** (тесты: 28 passed) |
| `services/summary_stage_events.py` | 126 | **PRESENT_AND_VERIFIED** | `build_event` (91), `record(ctx, event)` (127) append-only, `clock_meta(messages, chat_id)` (72), `document_plain_digest` (54); R17-safe (digest, без текста) |
| `services/turn_payload_events.py` | 157 | **PRESENT_AND_VERIFIED** | `emit_stage` (124) с `clock`/`decision`/`usage`, зеркало в `mca_events.emit_mca_event`; `clock_meta_messages/text` (88/99) |
| `services/factcheck_service.py` | 3173 | **PRESENT_AND_VERIFIED (как основа C-7.3)** | `grep 'graph_facts|invalidate_graph_fact|mca_provenance_status|edges'` → **0 совпадений**: factcheck не пишет в память вообще. Значит требование §7.3 «вердикт не меняет `graph_facts.status`» сегодня выполняется по построению; не хватает только **поля** `external_verification` в выдаче (новый код MEMORY-06) |
| `services/summary_l2_writer.py` | 1708 | **PRESENT_AND_VERIFIED (шов найден)** | `build_l2_input(package)` (489), `build_l2_source_input(payload_items, semantic_map, *, package)` (609), `validate_l2_document` (751). `EvidenceBundle`/`summary_text` не упоминаются → §7.2 входит через `build_l2_source_input`/`package`, промпты не трогаются (INV-09). Write scope MEMORY-06 подтверждён |
| `web/api/cognitive_map.py` | 808 | **PRESENT_AND_VERIFIED** | `cognitive_map_router` (88), `PAYLOAD_VERSION="cog-map/1"` (92), импорт `GRAPH_MAX_*`/`_db_or_503`/`_require_global_admin` из `web/api/memory_agi.py` (78–84), единственный эндпоинт `GET /memory/cognitive-map` (902–916) с `chat_id: int|None` и `_require_global_admin`. Ручки `/api/memory/search`, `/entity/{id}`, `/edge/{id}`, `/community/...` **отсутствуют** → §4.1 полностью новый код в этом же файле (аддитивно). Внутренние SQL — только рендер карты, не поиск (S-1 не нарушен) |
| `web/static/cognitive-map.js` | 2084 | **PARTIAL / расхождение по смыслу символов** | `searchNodes(model, query)` (449) — подстрока по `node.search` в загруженной сцене; `applyFilters` (500) с `{kinds, scopes, chats, statuses, search, cluster, hideIsolated, hideDerived}`; **`computeClusters` (577–682) = связные компоненты по РЕАЛЬНЫМ рёбрам** (union-find, корень = min id), подпись «`KIND_LABEL · size`» (664–666); `GROUP_NEUTRAL_LABEL='Группа'` (684) используется в `buildAggregates` (≈688+) — **пространственные тайлы LOD**, а не `computeClusters` |
| `web/static/…` `_graphSignature` | — | **CONFLICT (не тот файл)** | `_graphSignature` живёт в `web/app.js:30529` (использование 30649), **не** в `cognitive-map.js` |
| `web/index.html` | — | PRESENT_AND_VERIFIED | Два тулбара: inline (13545–13568) и fullscreen (15034–15057): input с `placeholder="Поиск по имени или алиасу…"`, `Все типы`, `Все кластеры`, `Сбросить вид` |
| `web/api/memory_agi.py` | — | PRESENT_AND_VERIFIED | `GRAPH_MAX_NODES=800` (94), `GRAPH_MAX_EDGES=2400` (95), `GRAPH_SEED_NODES=150` (98), `GET /memory/graph` (1022) |

---

## 5. Незакрытый разрушающий путь, которого нет в контракте (главная находка)

`services/memory_maintenance.py` — **второй консолидатор памяти, работающий по умолчанию**:

| Место | Строки | Поведение |
|---|---|---|
| `_tick_merge` → `merge_episodes` → `_merge_chat` | 255–256, 665–678, 680–699 | каждые `GRAPH_EPISODE_MERGE_INTERVAL_DAYS=7`, бюджет 20 кластеров |
| `_cluster_facts` | 701–726 | кластеры по cosine ≥ `_MERGE_CLUSTER_SIM` (`_dedup_knn`) или FTS-фолбэк «первые два слова» |
| `_merge_cluster` | 763–823 | LLM `COMPRESS_PROMPT` → проверка покрытия токенов → `insert_graph_fact(...)` (810) **→ `delete_graph_fact(row["id"])` для КАЖДОГО исходного факта (816–817)** + журнал `reason='episode_merge'` |
| `review` / `_glue_vec_dups` | 827–854, 856–891 | exact-dup склейка с удалением (841); vec-дубли cosine ≥ 0.95 → удаление (889); `purge_unconfirmed_graph_facts` (848) |
| Гейты | `config/settings.py:2961` `GRAPH_EPISODE_MERGE_ENABLED=True` | **включено по умолчанию** |
| Тест, закрепляющий удаление | `tests/test_memory_maintenance.py:54–76` | `assert "вася спорил с петей" not in facts` — тест **требует** физического удаления источников; прогон зелёный |

**Почему это блокер для контракта:** §0.4 п.7 и §3.4.1 фиксируют как конфликт только квоту. Но даже после перевода квоты в наблюдение память продолжает уничтожаться (`INSERT` слитой строки + `DELETE` исходных), теряя `fact_id`, авторство, `supersede`-статус, evidence-links и `target_user` (при разных авторах `target_user=None`, 808–809). Это прямо противоречит R-8 («физического удаления и DELETE нет»), R-10 / MEM-02.6 («merge переносит наборы доказательств без потери ни одного fact_id»), INV-01/INV-08 и §3.4.1 («`delete_graph_fact` остаётся только для user delete/forget и security retention»). Плюс `review()` удаляет «слабые» факты вне квоты и вне TTL-пуржа.

**Следствие для плана:** MEMORY-04 обязан покрыть не только `summary_memory::_dedup_decide`/`_enforce_user_quota`, но и `memory_maintenance::{_merge_cluster, review, _glue_vec_dups}`; тест `test_cluster_merged_sources_deleted_logged` должен быть **переписан** на «источники живы, слитая строка добавлена с lineage», иначе мутационный тест «вернуть удаление → тест падает» невыполним.

---

## 6. (a) Что должно быть исправлено в контракте (эта линия отличается)

1. **§0.3 п.9 и §0.4 п.6 — неверная атрибуция LOD.** На этой линии `computeClusters` — связные компоненты по реальным рёбрам (фильтр «Все кластеры»), а «Группа · N» / `GROUP_NEUTRAL_LABEL` выдаёт **`buildAggregates`** (пространственные тайлы). Формулировку «„Группа · N“ = client-side LOD (`computeClusters`)» заменить на: `computeClusters` = компоненты по реальным рёбрам (не сообщество, не семантика); `buildAggregates` = пространственный LOD-тайл с реальным количеством элементов. Правило «сообщество ≠ LOD-тайл» сохраняется, но символы названы верно.
2. **§0.3 п.10 / §0.4 п.9 — `_graphSignature` живёт в `web/app.js` (30529), не в `cognitive-map.js`.**
3. **§0.3.1 п.1 — `_merge_cluster` не в `summary_memory.py`, а в `services/memory_maintenance.py:763`.**
4. **§0.4 п.7 + §3.4.1 — список разрушающих путей неполон.** Добавить `memory_maintenance::{merge_episodes/_merge_cluster, review, _glue_vec_dups}` (удаление исходных фактов при слиянии/склейке, `GRAPH_EPISODE_MERGE_ENABLED=True` по умолчанию) и требование неразрушающего слияния с lineage; переписать §3.4.1-фразу «`delete_graph_fact` остаётся только для user delete/forget и security retention».
5. **§11 write-scope MEMORY-04 — добавить `services/memory_maintenance.py`** (иначе слайс физически не может выполнить R-8/R-10) и указать, что он же `SERIALIZE` с MEMORY-07.
6. **§7.1 `subject_entity_ids` — на линии это Telegram uid, не node id.** Зафиксировать: новые поля `subject_node_ids` (C-1 канонические `nodes.id`) добавляются рядом, существующая uid-семантика `subject_entity_ids`/`speaker_entity_id`/`participants` не меняется (иначе identity-prior молча перестанет работать — `_fact_candidate` кладёт в `subject_entity_id` имя).
7. **§4.4 «`top_k`-кап» — верхнего капа в `retrieve()` нет** (только `max(1, top_k)`). Для `purpose='ui_search'` `limit ≤ 20` должен быть явно введён в MEMORY-06, а не считаться существующим.
8. **§2.5 «расширить `provenance.ENTITY_TYPES`» — уточнить, что это единственный барьер** (`SourceRef.validate()` бросает `ValueError`, `mca_source_refs.entity_type` без CHECK) и что `graph_fact_source_ref` уже стабилен (`revision=None`) — риск §2.4.1 касается только новых edge/node-ref'ов.
9. **§0.3 п.18 — снять `pending@unified`**: corrective-модули (`chat_clock`, `summary_stage_events`, `turn_payload_events`, `factcheck_service`, `summary_l2_writer`, `cognitive_map.py/.js`) на линии **присутствуют и проверены**.
10. **§0.3 п.14 — уточнить, что `retrieve()` не имеет верхнего `top_k`-капа и `limit`**, а `EvidenceItem` не несёт attribution-полей (§2.1 `sources[]` — новое отображение, не «расширение на месте»).
11. **§5.1 — `graph_facts.revision` уже существует** (`INTEGER NOT NULL DEFAULT 1`, v31): в тексте «технически не поддерживает» к ревизии факта не применять; v43 не добавляет ревизию.
12. **§1.2.2 — подтверждено измеримо:** индекс `sqlite_autoindex_nodes_1 (chat_id, entity_name)` даёт `SEARCH nodes USING INDEX` для интервалов `[C, C+1 codepoint)`; `entity_type` остаётся residual-фильтром (в индексе его нет). Требование T14 выполнимо без схемных изменений.

---

## 7. (b) Минимальный набор кода для MEMORY-01 на этой линии

MEMORY-01 по §11 — только новый модуль типов/констант. Точный touch-set:

1. **Создать `services/memory_contracts.py`** (единственный файл):
   - dataclasses/TypedDict: `EntityRef`, `EntityResolution`, `RelationSourceView`, `RelationView`, `SearchIntent`, `SearchItem`, `SearchResponse` — строго по §1.1/§2.1/§4.2/§4.3;
   - константы: `ENTITY_CASEFOLD_MAX_ROWS=32`, `ENTITY_CASEFOLD_MIN_PREFIX=1`, `GRAPH_EDGE_WEIGHT_CAP=5`, `LEGACY_EDGE_WEIGHT_CAP=0.55` (импортировать/переиспользовать `graphrag_provenance._BARE_EDGE_WEIGHT_CAP` и `database._EDGE_WEIGHT_CAP`, а не дублировать значения), `SEARCH_LIMIT_MAX=20`, `PREVIEW_MAX_CHARS=400` (взять из `mca_retrieval_context._PREVIEW_MAX_CHARS`, не копировать), `ASSERTION_MODES`, `ORIGIN_CLASSES`, `LINK_TYPES` (импорт `provenance.LINK_TYPES`), `ENTITY_TYPES_ALLOWED=('user','topic','event','fact')`;
   - **не** импортировать `database`/`summary_memory` на уровне модуля (циклы): только `services.provenance` (без БД-импортов) и литералы.
2. **Никаких правок** в `database.py`, `summary_memory.py`, `mca_retrieval_context.py`, `provenance.py`, `web/*` в этом слайсе — иначе рушится `PARALLEL_SAFE` и обгоняется MEMORY-02/03.
3. **Тест** `tests/test_memory_contracts.py`: сериализация/дефолты, отсутствие дублирующих констант (`GRAPH_EDGE_WEIGHT_CAP == database._EDGE_WEIGHT_CAP`), AST-проверка «в модуле нет SQL-строк/сетевых импортов».

Зависимостей от G0/A0-расхождений у MEMORY-01 нет: типы описывают контракт, а не текущее поведение. Правки §6 обязаны быть внесены до **MEMORY-04** (разрушающие пути), **MEMORY-06** (uid/node-id и `limit`), **MEM-08-S3** (`computeClusters`/`buildAggregates`/`_graphSignature`), **MEMORY-03** (`ENTITY_TYPES`).

---

## 8. (c) Решение по старту

**MEMORY-01: GO.**
Обоснование: A0 выполнен по всем четырём пунктам §0.3.1; живая линия подтверждена (`release/2.58.161` и `evol/impl` — предки; схема 42); все символы, на которые опирается MEMORY-01, существуют; слайс — изолированный новый модуль без записи в БД и без правок существующих файлов, поэтому выявленные расхождения его не затрагивают.

**MEMORY-04 (temporal/политика/квота): NO-GO до исправления §6 п.4/5.**
Причина: помимо квоты и cosine-полосы память уничтожается `memory_maintenance._merge_cluster`/`review`/`_glue_vec_dups` (включено по умолчанию), а существующий тест закрепляет удаление. Без правки контракта и write-scope слайс заведомо не выполнит R-8/R-10 и не сможет пройти мутационное требование §3.4.1.

**MEMORY-03 (edge-evidence): GO после одной строки правки контракта (§6 п.8)** — `provenance.ENTITY_TYPES` не содержит `graph_edge`/`entity`, `SourceRef.validate()` бросает `ValueError`; сама правка — 1 строка в существующем frozenset, аддитивно и обратимо.

**MEM-08-S3 (UI-омнибокс): NO-GO до исправления §6 п.1/2.**
Причина: контракт неверно называет `computeClusters` LOD-тайлами и `_graphSignature` файлом `cognitive-map.js`; Builder иначе сломает фильтр «Все кластеры» или будет искать несуществующий символ. Visual Preservation Map §10 при этом остаётся в силе (тулбары в `web/index.html` подтверждены в двух местах, `searchNodes` — клиентская подстрока по сцене).

**Общий риск:** R1 — все расхождения локальны и аддитивны; ни одно не требует схемных изменений (v43 остаётся одним шагом) и ни одно не блокирует MEMORY-01.
