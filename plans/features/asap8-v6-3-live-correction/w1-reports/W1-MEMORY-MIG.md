# W1-MEMORY-MIG — B03 (просроченная/бессрочная память + D06-остаток) и B09 (supergroup ≠ потеря памяти)

Лена: W1-MEMORY-MIG · HEAD на старте `bc91b90` · ветка master (не коммитила — по брифу).

## 1. Реализации (файл:функция)

### B03.4 — D06-остаток: chat-scope ДО effective top-K в GraphRAG KNN (критичный фикс)
- `services/summary_memory.py::MemoryManager._vec_candidates` — переписан: глобальный KNN с фиксированным `k=fetch_k×4/×2` → фильтр после (анти-паттерн D06) заменён на доказанный staged overfetch через существующий `_staged_knn_scope` (k растёт ×4 до cap 512, пока не наберётся `fetch_k` фактов СВОЕГО чата; исчерпание — честное «в чате меньше», cap при заполненном K — partial + WARNING-телеметрия). Мёртвые `_vec_int8_rows`/`_vec_float_rows` удалены; `_filter_vec_rows` сохранён (используется тестами).
- Новая семантика keep — `MemoryManager._vec_row_keep(chat_id, …, expired_only)`: свой чат + origin-фильтры + (expired_only ? TTL истёк : TTL жив).
- Surfaces, где живёт vector path (перечень по брифу): `services/summary_memory.py` — RAG-KNN `graph_facts_vec` (исправлен), archive-KNN `smart_archive` (`_search_archive_knn_scoped`, уже scoped с v6), dedup-KNN (`_dedup_knn`, уже scoped); FTS-пути — `services/database.py::search_graph_facts_fts` / `search_archive_fts` / `search_messages_fts` (SQL фильтрует chat_id в WHERE — вне KNN, scope до LIMIT). Partition key DDL для vec0 остаётся опцией будущего апгрейда (f10 §72–73) — вне слайса.

### B03.1 — retention ≠ temporal truth ≠ retrieval eligibility
- `services/database.py::search_graph_facts_fts` — новый kwarg `include_expired=None` (None → наследует `include_archived`: dig_into_lore видит expired полноценно; False — обычный RAG; True — всегда). SELECT аддитивно несёт `f.expires_at`. TTL-предикат отделён от retention.
- `services/database.py::invalidate_graph_fact` — при `memory.infinite_retention` vec-строка НЕ удаляется: `UPDATE graph_facts_vec SET expires_at=now` (embeddings/версии сохраняются; свежий KNN её не выдаёт, архивная стадия находит). Не-infinite поведение (DELETE vec-копии) без изменений. Поддержка UPDATE aux-колонок sqlite-vec 0.1.9 проверена пробником (OPENCODE_WORKFLOW_SCRATCH/w1_vec_probe.py: UPDATE aux OK, KNN k>rows OK).
- `purge_expired_graph_facts` / `purge_unconfirmed_graph_facts` / `trim_compression_log` — гейты G3–G5 переведены на async `_infinite_retention_on()`; удалений в infinite mode по-прежнему ноль (тесты).

### B03.2 — fresh-first + архивный top-up с trust/as-of; версии
- `services/summary_memory.py::MemoryManager._knn_graph_facts` — если свежих (confirmed/archived_belief после status-фильтра) < limit и `flags.memory_archive_retrieval` (default ON) → вторая expired-only стадия `_vec_candidates(expired_only=True)` (chat-scope сохранён); истёканность верифицируется по `graph_facts` (истина), не по aux-копии vec; пенальти `limits.expired_retrieval_penalty` (default 0.25) к score — свежие всегда впереди; **expired не участвуют в touch и в молчаливом воскрешении** (нет немого продления TTL).
- `MemoryManager._search_graph_facts` (FTS-фолбек) — тот же fresh-first + top-up `include_expired=True` с пенальти в ранге; touch — только свежие.
- Пометка выдачи: `with_meta` + ключи `expired`/`expires_at`; 6-кортеж → 7-элементный (7-й — expired-флаг, R16-аддитивно, потребители читают по индексу — аудит consumers: direct_chat/dream/tool_router/rerank/dedup — все индексные).
- Рендер: `summary_memory::_expired_suffix` + `build_rag_context` / `_format_origin_labeled_line` — архивный факт получает «(Внимание: срок актуальности истёк; может быть неактуально)» + дату/ID (as-of; не выдаётся за актуальное).
- Supersede/подтверждение (базис уже был, покрыт тестами): dedup-noop → `confirm_graph_fact` (dated re-confirmation), supersede → новая версия `supersedes=old` + `invalidate_graph_fact` (не delete) + журнал `graph_fact_compression`. В infinite mode старая версия остаётся и в vec-индексе.

### B03.3 — bounded recency-классификация (данные для «Просрочено N»)
- `services/database.py::DatabaseService.expired_graph_facts_overview(chat_id)` — bounded COUNT-агрегаты: `expired_total / expired_searchable (FTS жив) / needs_recheck (confirmed expired) / superseded_total / infinite_retention`.
- `services/summary_memory.py::MemoryManager.expired_memory_overview(chat_id)` — fail-open обёртка.
- Периодический цикл — существующий `memory_maintenance.review` (чужой scope): его фазы срабатывают через гейты G3–G5 как раньше; приоритет по спросу реализован on-demand (RAG-hit touch свежих; expired поднимается только по релевантности, без re-embedding).

### B03.5 — per-chat независимость infinite-режима
- `services/database.py::_infinite_retention_on(chat_id)` — global `memory.infinite_retention` ИЛИ явный per-chat override `chat_params.overrides['memory.infinite_retention']=true` (fail-open → global). Global-проход purge исключает бессрочные чаты (bounded: DISTINCT chat_id по кандидатам + кэш overrides); точечный `purge(chat_id=…)` для override-чата → 0.

### B09 — сквозной перенос памяти supergroup
- НОВЫЙ `services/chat_migration.py`:
  - `migrate_chat_memory(db, old, new)` — идемпотентный UPDATE `chat_id` old→new по носителям: `smart_messages` (L1/dig), `smart_archive_facts` (Summary+FTS), `graph_facts` (Memory+FTS), `edges`, `graph_fact_compressions`, guard-таблицы `nodes`/`protected_facts`/`mca_episodes`/`chat_summary_levels`/`chat_running_summary` (per-row guard по конфликтным колонкам: занятая цель пропускается, abort-а нет), vec0 `graph_facts_vec`/`smart_archive` (aux chat_id). **0 DELETE**; FTS external-content переезжает сам по rowid.
  - **safe backup ДО записи**: `chat_migration_backup(migration_id, table_name, rowid_value, row_json…)` — полные строки row-таблиц, aux-метаданные vec (embedding восстановим штатным backfill); неполный backup → перенос не начинается; cap 200k строк/таблица с WARNING.
  - Цепочка миграций: new резолвится `resolve_canonical_chat_id` до канонического конца; повторный вызов → 0 строк.
  - `verify_chat_memory_integrity(db, old, new)` — «остатков под old нет» + размер backup; конфликтные остатки репортятся честно (ok=False).
- Проводка резолвера: `handlers/chat_lifecycle.py::on_chat_migrated` — после `migrate_profile` fail-open вызов `migrate_chat_memory(_db, old, new)` (закрытие wa3-остатка «Summary/Memory вне доказанного переноса»; link≠proof — пишет реальный перенос, не только link).
- Overrides (chat_params) переезжают с профилем PG-store — доказано wa3 (D02), в эту лену не входит.

## 2. Acceptance ledger

| Пункт | Требование | Статус | Evidence |
|---|---|---|---|
| B03.1 | retention/temporal/eligibility разделены; infinite: 0 удалений (данные/provenance/embeddings/версии); expired = «требует контекста» | DONE (agent) | `test_infinite_mode_never_deletes`, `test_infinite_retention_keeps_vec_row_on_invalidate`, `test_expired_found_by_historical_query_only` (b03-suite) |
| B03.2 | fresh-first, архивный top-up с trust+as-of; исторический запрос — архив полноценно; confirm=dated re-confirmation, supersede=не delete | DONE (agent) | `test_expired_topup_marked_with_trust_flag`, `test_fresh_outranks_expired_when_both_match`, `test_supersede_version_crossing`, `test_archive_flag_off_disables_topup` |
| B03.3 | bounded revalidation/recency-классификация; без тотального re-embedding | DONE (agent) | `expired_graph_facts_overview` + `test_overview_counts_bounded`; re-embedding отсутствует (только COUNT) |
| B03.4 (D06) | scope ДО top-K в `_vec_candidates` (GraphRAG) и archive path; никогда не возвращает чужие; объёмный displacement-тест | DONE (agent) | RED на pre-fix (3/3 fail: displacement float/int8 + historical) → GREEN; `test_foreign_volume_does_not_displace_local` (3500 чужих, latency<5s мягкий порог), `test_scoped_int8_path_never_returns_foreign` |
| B03.5 | per-chat infinite независимо; global/chat override; миграция supergroup при retention ON не удаляет факты/узлы/FTS/vec | DONE (agent) | `test_per_chat_independent_infinite_override`; b09 `test_no_delete_contract`; `chat_migration` содержит 0 DELETE |
| B03 DoD | архивный факт найден историческим запросом и в контексте со ссылкой/датой; устаревшее не за актуальное; conflict/supersede; 3500+ latency | DONE (agent) | b03-тесты (выше) + пометка в `build_rag_context` ( assertions в тестах); latency-ассерт `<5.0s` |
| B09 | old/new chat_id через memory/FTS/GraphRAG/episodes/summary/history; идемпотентная миграция/alias без порчи; RBAC/profil — D02; old-факты находятся после рестарта; backup перед массовыми операциями | DONE (agent, live=postdeploy) | `test_end_to_end_transfer_and_restart` (все пути + рестарт переоткрытием файловой БД), `test_conflict_does_not_abort_and_is_reported`, `test_no_delete_contract`, `TestLifecycleWiring::test_on_chat_migrated_calls_memory_migration` |
| REQ-B03-CLARIFY / REQ-B03-DOD / REQ-B09-BODY | карта | реализация готова; `live_required=true` постдеплой-пункты (preprod) — за Orchestrator/релиз | — |

Live/postdeploy (не в этой лене): preprod-проверка переноса на реальном supergroup и статус-блок «Просрочено» на проде.

## 3. Тесты

Новые (TEST-LIFECYCLE в шапках):
- `tests/test_asap8_v63_b03_memory.py` — 11 тестов (REGRESSION owner=REQ-B03-CLARIFY/REQ-B03-DOD): displacement float/int8 (RED/GREEN доказан: на pre-fix коде 3/3 релевантных падают — git stash прогон), latency 3500+ (<5s мягкий), historical eligibility, top-up+маркеры, fresh>expired, флаг OFF, supersede-версии, infinite no-delete (purge/unconfirmed/trim/invalidate), overview, per-chat override.
- `tests/test_asap8_v63_b09_migration.py` — 4 теста (INTEGRATION owner=REQ-B09-BODY): end-to-end перенос+рестарт (реальная файловая SQLite, все пути чтения: graph FTS/KNN, archive FTS/KNN, messages FTS, конспект, эпизод), конфликт без abort (честный residual), контракт «0 изменений числа строк», wiring хендлера.

Обновлённые (контрактные, обоснование):
- `tests/test_graphrag_memory.py` — 5 тестов: `len==6` → `==7` (R16-аддитивная политика кортежей, B03 7-й элемент); два TTL-теста #15 переписаны под новый контракт владельца B03 («нельзя объявлять мёртвыми только потому, что expires_at < now»): expired присутствует, но помечен и ниже свежего.

Прогоны (финал):
- свои: `b03+b09` — **15 passed**;
- смежные: `graphrag_memory(172) + graphrag_database + d06_isolation + wa3_migration + chat_lifecycle + asap7_chat_lifecycle + belief_decay + database` — **408 passed, EXIT=0**;
- широкие выборки: `-k "mca07 or retrieval or summary_memory or purge or maintenance or mca06 or identity or lifecycle"` — **449 passed**; `-k "direct_chat or direct_context or context_policy or auto_budget or llm_react or fallback_recompose"` — **435 passed**; `-k "dream or sleep or history_import or graphrag or archive or smart_cache or embed"` — **992 passed / 1 pre-existing флейк** (см. §6).
- RED-доказательство: `git stash` сервисов → `TestGraphKnnChatScope::*` и `TestExpiredRetrievalEligibility::*` падают (3 failed) → pop → GREEN.

## 4. Изменённые/новые файлы (только эта лена)

- M `services/database.py` — `_infinite_retention_on(chat_id)`/`_infinite_retention_chat_ids`, гейты G3–G5 async+per-chat, `purge_expired_graph_facts` (исключение override-чатов), `search_graph_facts_fts(include_expired)` + `expires_at` в SELECT, `invalidate_graph_fact` (infinite: UPDATE vec вместо DELETE), `get_graph_fact_records` +`expires_at`, новый `expired_graph_facts_overview`.
- M `services/summary_memory.py` — `_vec_candidates` staged-scope (+`expired_only`), `_vec_row_keep`, `_knn_graph_facts`/`_search_graph_facts` top-up+маркеры, `_expired_suffix`, рендер, `expired_memory_overview`.
- N `services/chat_migration.py` — перенос/backup/verify (см. §1).
- M `handlers/chat_lifecycle.py` — проводка вызова переноса (fail-open, ~19 строк) — это и есть supergroup migration resolver по брифу.
- M `tests/test_graphrag_memory.py` — 5 контрактных апдейтов.
- N `tests/test_asap8_v63_b03_memory.py`, N `tests/test_asap8_v63_b09_migration.py`.

Пробники (scratch, не в репо-корне): `OPENCODE_WORKFLOW_SCRATCH/w1_vec_probe.py`, `w1_purge_probe*.py`, `w1_tables.py`.

## 5. Патчи вне scope (рекомендации, НЕ применялись)

1. `config/settings.py` / `services/param_catalog.py` (для UI-волны и админки): зарегистрировать `flags.memory_archive_retrieval` (bool, default True, категория flags_memory), `limits.expired_retrieval_penalty` (float, 0.25, limits_memory) и per-chat override `memory.infinite_retention` (chat_params.overrides; в каталоге глобальный уже есть). До регистрации ключи работают через `hot.get(key, default)` (проверено тестом), UI-рубильников не появится.
2. `services/memory_maintenance.py` (чужой scope): в фазу отчёта review можно добавить сбор `expired_memory_overview` для статус-блока; текущее поведение G6 не требовало правки.
3. `services/tool_router.py` — изменений НЕ потребовалось: `include_archived=True` (dig_into_lore) теперь автоматически влечёт expired-eligibility внутри `search_graph_facts_fts` (наследование None→include_archived).

## 6. Incidental findings

- `unrelated/pre-existing`: межфайловая утечка `services/mca_events._pending` — `tests/test_asap8_v6_p1_d09_memory.py::test_all_duplicates_neutral_success` падает, если перед ним в одном pytest-процессе шли файлы, писавшие FACTS_EXTRACT (воспроизведено на pristine HEAD: `graphrag_memory + d09_memory` → 1 failed). Тест читает глобальный буфер без очистки. Не влияет на B03/B09; предложить owned-fix (очистка `_pending` в фикстуре) отдельным мини-слайсом.
- `related-nonblocking`: `touch_graph_facts` не синхронизирует aux `expires_at` vec-копии (обновляет только graph_facts) — расхождение компенсируется тем, что expired-стадия верифицирует по graph_facts; свежий путь читает vec-копию (базисное поведение 66.5, не трогал).
- `uncertain`: per-chat override читается через кэш `chat_params` (PG) — при недоступном PG fail-open к global; в проде PG-пул живёт рядом с ботом (ok).

## 7. UI-handoff (для UI-волны)

Данные для блока «Просрочено N»: `MemoryManager.expired_memory_overview(chat_id=None)` →
`{now_ts, expired_total, expired_searchable, needs_recheck, superseded_total, infinite_retention}`.
Раскладка блока: «всего N · доступно поиску: expired_searchable · требует перепроверки: needs_recheck · вытеснено новыми версиями: superseded_total · режим: бессрочный/обычный». Endpoint в `web/api/*` — вне моего WRITE_SCOPE (web/* запрещён): UI-волне достаточно обернуть метод. Рендер-факт в контексте уже несёт as-of: дата + «(Внимание: срок актуальности истёк; может быть неактуально)».

## 8. Ограничения

- vec0 partition key (per-chat) — не делал: sqlite-vec 0.1.9 не умеет auxiliary-WHERE в KNN; staged overfetch с cap 512 — доказанная стратегия v6 (f10). Экстремальный случай «>512 чужих фактов ВСЕ ближе любого своего» честно деградирует до partial+WARNING (телеметрия), не молчаливо.
- `chat_running_summary` при занятом PK цели остаётся под old (guard) — честно репортится `verify_chat_memory_integrity` (тест); merge конспектов — осознанно не делал (потеря/склейка текста хуже честного residual).
- Backup vec0 хранит aux-метаданные без embedding-блобов (объём); восстановление embedding — штатный backfill из текстов.
- Объёмный displacement-тест использует синтетические vec-строки с фиктивными fact_id для чужого чата (KNN-слой читает только vec; records-fetch идёт лишь по возвращённым своим id).
- Не коммитил (запрет брифа); рабочий коммит — за Orchestrator после ревью.
