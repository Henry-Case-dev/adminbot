# `mca-07-retrieval-context` — evidence (Step 3 @Builder, T-3842…T-3856)

- **Фича:** `mca-07-retrieval-context` (round 10.27, Wave 1). **Risk R3**.
- **Роль сессии:** @Builder (без emergency-fallback).
- **Baseline (Reviewed-Commit):** `05bc870` (origin/master); `APP_VERSION` 2.58.31;
  DDL **v17**; pytest 9712/0 + JS 47/47; откат anchor `7165ff7`.
- **Current (рабочее дерево):** HEAD = `05bc870` (коммитов НЕ создавалось);
  незакоммиченное рабочее дерево (волны 0/1a/04a + mca-07); DDL **v18**;
  `Deploy = DEFERRED_TO_RELEASE`.
- **Итог прогона (после rework по `review.md`):** pytest **9758 passed / 0 failed**
  (0:03:40); JS node **47/47 exit 0**; `git diff --check` exit 0.
- **Обновление session-resume:** T-3852 закрыта — единый `EvidenceBundle`
  подключён в живой конвейер (см. §4a).
- **Rework (review `Needs Fixes`, 27.09.2026):** B-MCA07-1/B-MCA07-2 (High)
  исправлены; M-MCA07-1 исправлена; M-MCA07-2 частично (carry-over
  зарегистрирован); Lows закрыты/зарегистрированы — см. §0.

## 0. Rework по `review.md` (Needs Fixes → повторный gate)

### B-MCA07-1 (High) — A06/mismatch-политика поколений — **ИСПРАВЛЕНО**
- **Причина:** `_register_index_generations()` на старте вызывал
  `ensure_embedding_generation`, который помечал активное поколение
  `superseded` и регистрировал текущий конфиг `active` **без перестройки
  векторов** → `_index_generation_ok` давал ложное совпадение.
- **Фикс:**
  - `database.ensure_embedding_generation(..., activate=True)` **больше не
    затирает активное поколение**: при наличии активного с другим fingerprint
    возвращает его как есть (не supersede); новое регистрируется `active`
    только при `activate=True` (векторы построены текущим конфигом), иначе —
    `building` (карантин).
  - `database.get_latest_embedding_generation` (любой статус) +
    `database.get_generation_by_fingerprint` (использует
    `idx_mca_eig_fingerprint` — L-MCA07-1).
  - `summary_memory._register_index_generations(activate=)` — активация
    только когда таблицы свежие или пересозданы (`dim`/schema-rebuild);
    персистентные векторы неизвестного происхождения → `building`.
  - `summary_memory._index_generation_ok` — обслуживает vec только если
    **последнее** поколение `status='active'` И fingerprint == текущего
    конфига; иначе FTS-only (`embedding_generation_changed`).
  - `_vec_tables_preexisting()` + `_rebuild_vec_tables_if_needed()` →
    возвращает `dropped`.
- **Тесты:** `test_generation_registry_no_supersede_on_model_change`,
  `test_generation_registry_quarantine_building`,
  `test_register_generations_does_not_overwrite_active` (repro из review:
  смена конфига/рестарт → guard **False**; повторный старт без изменений →
  **True**), `test_fingerprint_lookup_and_idempotent_quarantine`.

### B-MCA07-2 (High) — полный учёт payload (A24) в живом пути — **ИСПРАВЛЕНО**
- **Причина:** production call-site (`_build_user_content`) не передавал
  `external_tokens`/`reserve_tokens`/`estimation_method` → pre-flight
  `context_overflow`/лог не выполнялись (A24 только unit).
- **Фикс:** добавлен `_estimate_external_payload_tokens(chat_id, budget)` —
  консервативная оценка system/developer-промпта + personality-блока + tools
  schemas (JSON) → `external_tokens`; `reserve_tokens` = доля
  `CHAT_BUDGET_RESERVE_RATIO`; метод — `token_counter.estimation_method()`
  (`tiktoken`/`chars*0.3`). `_build_user_content` вызывает его при
  `budgets_enabled AND MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` и передаёт в
  `_apply_context_budget`. Pre-flight при переполнении обязательной части —
  WARN `context overflow` + событие `context_overflow` + деградация (полный
  сброс остаточных cuttable-блоков). Fail-open → legacy (паритет).
- **Тесты:** `test_live_call_site_passes_external_payload` (production-точка
  передаёт external/reserve/method), `test_estimate_external_payload_tokens_positive`,
  `test_live_preflight_overflow_on_mandatory`.

### M-MCA07-1 (Medium) — `context_version` в живом bundle — **ИСПРАВЛЕНО**
- Live-builder теперь кладёт `current_revision = current_ref`, включает
  `current_ref` в `selected_refs` и `summary_revision` (derived
  `window_end_ts:raw_count` из `get_running_summary`, fail-open).
- **Тест:** `test_context_version_includes_current_and_summary` (разные
  current-ходы → разная версия; summary_revision меняет версию).

### M-MCA07-2 (Medium) — полнота полей §11.2 живого bundle — **ЧАСТИЧНО**
- **Наполнено (из уже построенных блоков, без нового I/O):** `mentioned`
  (`<UserResolutionMap>`), `relations` (`<user_relations>`), `recent_actions`
  (= `chosen_intent`), плюс ранее — `addressee`/`author`/`branch`/`evidence`/
  `constraints`/`chosen_intent`/`context_version`/`excluded`.
- **Carry-over (регистрируется; решение @Architect — см. ниже):**
  `ambiguities`, `local_context`, `persona`, `interests`, `unknown`,
  `contradictions` остаются пустыми. Обоснование: (а) требуют семантического
  извлечения/дедупа, которое в mca-07 не выполнялось (границы spec §1:
  Intent/Decision — `mca-09`, Experience/Lesson — `mca-16`, эпизоды —
  `mca-05`); (б) `local_context`/`persona` строятся на иных стадиях
  (`global`/persona после builder) — дублирование нарушило бы §11.2
  «не дублировать архив»; (в) GEN-R19 REUSE — источник этих полей у
  потребителей. **Требуется подтверждение @Architect** (review.md §Handoff).
- **Тест:** `test_bundle_relations_and_mentioned_populated`.

### Lows (закрыто / зарегистрировано)
- **L-MCA07-1 — ЗАКРЫТО:** `idx_mca_eig_fingerprint` используется
  `get_generation_by_fingerprint` (guard/идемпотентность карантина).
- **L-MCA07-3 — ЗАКРЫТО:** `retrieve()` эмитит `exact_match_used` при exact-канале.
- **L-MCA07-4 — ЗАКРЫТО:** `answer_cache_disabled` эмитится со стадией
  `answer_cache` (была `summary`).
- **L-MCA07-2 — ЗАРЕГИСТРИРОВАНО (принято):** `search_service._rerank_results`
  — задокументированный адаптер (текст-компрессия, не выбор ID-кандидатов);
  статус-событие через единое ядро. Соответствует spec §4.2 (адаптер).
- **L-MCA07-5 — CARRY-OVER:** `retrieve()` пока без живого caller —
  consumer-зона `mca-09`/`mca-10b`/`mca-15` (SC-01/SC-02 покрыты unit+smoke).
- **L-MCA07-6 — ЗАРЕГИСТРИРОВАНО:** update-дедуп `(chat_id, tg_message_id)` —
  контракт `mca-03` (idempotent `save_live_message`); отдельный processing-gate
  в mca-07 не создаётся (граница).
- **L-MCA07-7 — WATCH:** единичный timeout teardown `test_summary_memory.py`
  (повторный прогон 9758/0); не подтверждён как дефект.

## 1. Изменённые файлы (только mca-07; чужие фичи не трогались)

### Product code (8)
| Файл | Роль |
|---|---|
| `config/settings.py` | +6 kill-switch `ClassVar` (env-only, default ON, Δ каталога=0) |
| `services/mca_gates.py` | +6 резолверов + регистрация в `KILL_SWITCHES` |
| `services/mca_events.py` | +10 `reason_code` (реестр MCA-13, §4.9) |
| `services/database.py` | **v18**: `mca_embedding_index_generations` +3 индекса + 5 nullable-колонок `embedding_cache`; `upsert_running_summary` HWM/CAS; `list_lore_stories`; `get_active_embedding_generation`/`ensure_embedding_generation` |
| `services/summary_memory.py` | embedding identity/key/lookup/store; generation-gate vec; `retrieve_fact_candidates`; `_with_meta`; типизированный `rerank_rag_facts` + адаптеры; singleflight сводки |
| `services/direct_chat_service.py` | `_apply_context_budget` полный payload + protected spans + pre-flight; ответный кеш ON/OFF |
| `services/token_counter.py` | `protected_spans`/`has_protected_spans`/`append_protected_spans` (+регэкспы) |
| `services/search_service.py` | `_rerank_results` — адаптер к единому ядру (статус-событие) |

### NEW-контракт (1)
- `services/mca_retrieval_context.py` — **новый контрактный слой** (не второй
  движок): `RetrievalRequest/Result/Candidate`, `RerankResult`, `EvidenceBundle`,
  `compute_context_version`, `retrieve()`, `apply_retrieval_rerank`,
  `classify_rerank_*`, `emit_stage_event`.

### Tests (mine / touched)
- **NEW:** `tests/test_mca07_retrieval_context_round1027.py` (34 теста;
  включая 7 T-3852 SC-09/SC-10/A04/OFF).
- **AMEND (T-3852, контракт-заглушка):** `test_budget_global_toggle_round1024.py`
  — `_apply_context_budget`-двойник принимает `**kwargs` (новая реальная
  сигнатура с `out_excluded`; паритет).
- **AMEND (типизированный reranker, D3):** `tests/test_graphrag_memory.py`
  (`TestChatRagRerankF4` — evaluation-order; valid-empty ≠ кандидаты; bounded
  fallback; OFF-паритет).
- **AMEND (text-replay OFF, D9):** `tests/test_direct_chat.py::TestHandleDedup`
  — autouse-гейт OFF (baseline-паритет) + новый ON-тест «нет text-replay».
- **AMEND (head DDL 17→18, T-3842):** version-head ассерты в
  `test_database.py`, `test_graphrag_database.py`, `test_graph_facts_origin_v9.py`,
  `test_graph_scoring_round1018.py`, `test_history_migration_v7.py`,
  `test_memory_commands.py`, `test_memory_retention_round1019.py`,
  `test_migrate_direct_chat_v2_script.py`, `test_migrate_epic60_v3_script.py`,
  `test_multilayer_extraction_round1021.py`, `test_lore_compiler_round1020.py`,
  `test_agentic_ai_round1020.py`, `test_webapp_round1020_ui.py`,
  `test_mca03_message_identity_round1027.py`,
  `test_mca04a_provenance_round1027.py`,
  `test_mca01_tx_task_supervisor_round1027.py` (allowlist write-точек
  `database.py`: 116→122 — санкционированные commit v18, L-MCA14-3).

### Docs
- `plans/features/mca-07-retrieval-context/evidence.md` (этот файл)
- `plans/features/mca-07-retrieval-context/threat-failure-analysis.md` (R3, T-3857-вход)
- `plans/features/mca-07-retrieval-context/tasks.md` (чекбоксы T-3842…T-3856)

## 2. Verification (команды + фактический результат)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9742 passed / 0 failed** |
| mca-07 контракт | `pytest tests/test_mca07_retrieval_context_round1027.py` | **27 passed** |
| v18/mca-14 | `pytest tests/test_mca14_schema_additive_round1027.py` | passed |
| mca-03/mca-04a/13/01/02 | соответствующие файлы | passed |
| JS vm-харнесс | `node tests/js/*.js` (47 файлов) | **47/47 exit 0** |
| Whitespace | `git diff --check` | exit 0 (только LF→CRLF warnings) |

## 3. Δ DDL v18 — идемпотентность и границы

- Реестр `MigrationStep(v18, "embedding_identity", _migrate_embedding_identity_v18)`
  через механизм `mca-14`; `PRAGMA user_version` 17→18.
- **fresh:** user_version=18; таблица + 3 индекса (`idx_mca_eig_name_gen`,
  `idx_mca_eig_active` partial-UNIQUE, `idx_mca_eig_fingerprint`); 5 nullable-
  колонок `embedding_cache` — есть.
- **legacy v17 → 18:** аддитивно; `mca_source_refs`/`mca_evidence_links`/
  `mca_provenance_status` сохранены (тест `test_v18_from_v17_legacy_preserves_provenance`).
- **идемпотентность:** повторный `initialize()` на новом экземпляре — 0 новых
  строк `schema_migrations` (тест `test_v18_vec_tables_untouched_and_idempotent`).
- **vec-таблицы НЕ ALTER:** `smart_archive`/`graph_facts_vec` шагом не создаются
  и не модифицируются (идентичность — реестр поколений).
- **синтетическая/усечённая legacy-БД без `embedding_cache`:** шаг честно no-op
  (guard `sqlite_master`), ALTER не падает (mca-14 `test_legacy_v12_backfill`).
- **PG — no-op** (SQLite-механизм; `pg_db.py` вне diff — не трогался).
- **nullable = честный unknown:** legacy-строка `embedding_cache` имеет
  `provider`/`identity_fingerprint` = NULL.
- **Индексы — только под подтверждённый запрос:** резолв активного поколения
  `(index_name, status='active')`, lookup по `fingerprint`; запрет «всех
  комбинаций» соблюдён (partial-UNIQUE `idx_mca_eig_active`).

## 4. Фичи — как проверено

**Reranker (D3/A05).** `RerankResult.status ∈ {ok,empty,invalid,timeout,error}`;
`select_by_rerank` даёт порядок = оценке; пустой валидный → ПУСТО (не кандидаты);
invalid/timeout/error → отдельный статус + детерминированный bounded
pre-rerank-fallback (top_k=8); `rerank_rag_facts`/`_rerank_results` — адаптеры.
Тесты: `test_classify_rerank_statuses`, `test_select_by_rerank_valid_empty_and_order`,
`test_valid_empty_does_not_return_all_candidates`, `test_search_service_rerank_adapter_unchanged_text`.

**Embedding identity (D4/A06).** `key = H(identity_fp \x00 casefold(strip(text)))`,
`identity_fp = sha256(provider|model|dims|preproc|endpoint)`; endpoint включается
при непустом значении; lookup требует полный identity **и** `dim` (defense-in-depth);
legacy-ключ без identity — байт-в-байт прежний. Поколения: `ensure_embedding_generation`
помечает старое `superseded`, новое `active`; `_index_generation_ok` → FTS-only
при несовпадении. Тесты: `test_embedding_identity_key_same_dim_different_model`,
`test_generation_registry_supersedes_on_model_change`,
`test_index_generation_mismatch_forces_fts_only`.

**Retrieval (D1/D2).** `retrieve()` комбинирует exact (quoted-FTS) + lexical
(messages+facts FTS) + vector (`MemoryManager.retrieve_fact_candidates`, REUSE)
+ reply-граф (`thread_chain`) + эпизоды (`lore_stories`, фасад); история →
эпизоды первыми; фильтры время/участники; кандидат несёт SourceRef-ссылку/время;
дедуп; bounded top_k; событие стадии с `reason_code`. Тесты:
`test_retrieval_combines_channels_and_refs`, `test_retrieval_history_episodes_first`,
`test_retrieval_exact_phrase_and_filters`, `test_retrieval_reply_graph_channel`,
`test_retrieval_empty_reason`.

**EvidenceBundle (D5).** frozen-dataclass со всеми полями §11.2; ссылается на
SourceRef (не копия); `excluded[]` с reason; `compute_context_version` —
детерминированный fingerprint зависимостей. Тест
`test_evidence_bundle_full_fields_and_context_version`.

**Бюджет (D7/A24).** `_apply_context_budget(..., external_tokens=, reserve_tokens=,
estimation_method=, excluded_categories=)`: при gate ON и переданном external —
бюджет user-блоков = cap − external − reserve; pre-flight помечает заведомое
переполнение обязательной части (`context_overflow`/`budget_exceeded`); логируются
размер/резерв/исключённые категории/метод. protected spans (отрицание/ID/дата)
переносятся при обрезке. Тесты: `test_budget_full_payload_accounting`,
`test_budget_overflow_preflight`, `test_protected_spans_preserved_when_truncating`,
`test_protected_spans_not_preserved_when_gate_off`, `test_budget_off_gate_ignores_external`.

**Сводки (D8/A03).** `upsert_running_summary` — HWM/CAS по
`(window_end_ts, raw_count)`: поздняя старая сводка отклоняется (return False);
singleflight через REUSE `TaskSupervisor` (coalesce_key `running_summary:<chat>`).
Тесты: `test_running_summary_cas_rejects_stale`,
`test_running_summary_cas_off_baseline`.

**Ответный кеш (D9).** ON → `_legacy_text_replay_enabled()` = False (text-replay
по одному нормализованному query/chat/user отключён); update-дедуп
`(chat_id, tg_message_id)` — отдельный механизм идентичности, не затронут.
Тесты: `test_answer_cache_policy_helper`,
`TestHandleDedup::test_context_policy_on_disables_text_replay`, OFF-паритет —
autouse-гейт класса `TestHandleDedup`.

**События (D11).** 10 `reason_code` зарегистрированы (`test_mca07_reason_codes_registered`);
стадии retrieval/reranker/bundle/budget/summary эмитятся через `emit_stage_event`→
`emit_mca_event` (REUSE `mca_events`, второй store не создан).

**Единый bundle в живом конвейере (D6/SC-09/SC-10/A04, T-3852 session-resume).**
Точки подключения (`services/direct_chat_service.py`, REUSE — второго
контракта/бюджета нет):
1. `_build_user_content(..., out_excluded=[])` → `_apply_context_budget(...,
   out_excluded=)` записывает блоки, **целиком вытесненные бюджетом**
   (`{kind, reason_code: budget_exceeded, estimated_tokens}`).
2. `_build_evidence_bundle(...)` (gate `MCA_EVIDENCE_BUNDLE_ENABLED`) — ОДИН
   раз в `handle` **после решения** (`chosen_intent=pre_action`), из уже
   построенных user-блоков, **без нового I/O**: `addressee`/`author` =
   target, `branch` = канонические `tg:/msg:` ссылки reply-графа, `evidence`
   = `fact:/tg:` ссылки RAG + текущий ход, `constraints` = текущий вопрос,
   `excluded[]` из бюджета, `context_version` = `compute_context_version(...)`.
3. **decision**: результат Фазы P вкладывается в `chosen_intent` единственного
   bundle (bundle проносит решение вниз по стадиям).
4. **tools**: `tool_ctx.evidence_bundle = evidence_bundle` (тот же объект).
5. **synthesis/System2**: `_synthesize_direct_answer(..., bundle=)` — scoped-срез
   (`_bundle_scoped_slice`: адресат/автор/ветка/ограничения/`context_version`)
   добавляется в Stage-1 ДО «СООБЩЕНИЕ ЮЗЕРА/ИНСТРУМЕНТЫ/ВЫВОДЫ», поэтому
   System2 после tool loop **не получает только вопрос+tool output**;
   tool-вывод сохранён; R17 — свободный текст маскируется, версия добавляется
   после маскирования.
6. **формулировка/наблюдаемость**: после успешной отправки — событие `bundle`
   с `context_version`.
- **OFF-паритет:** gate OFF → `_build_evidence_bundle` = None, `_bundle_scoped_slice`
  = "", Stage-1 байт-в-байт прежний; `tool_ctx.evidence_bundle=None`.
- Тесты: `test_build_evidence_bundle_fields_and_version`,
  `test_bundle_scoped_slice_for_system2`, `test_builder_gate_off_returns_none`,
  `test_a04_different_branch_different_context_version`,
  `test_system2_receives_bundle_after_tool_loop`,
  `test_system2_without_bundle_unchanged`, `test_excluded_capture_from_budget`.

**OFF-паритет (6 гейтов).** `test_mca07_kill_switches_registered_and_default_on`
(default ON, имена); OFF-пути: reranker legacy (`test_typed_reranker_off_legacy_parity`),
CAS off (`test_running_summary_cas_off_baseline`), budget external игнорируется,
protected spans не переносятся, text-replay восстановлен.

## 5. Невыполненное / ограничения честности

- **T-3852 — ЗАКРЫТА** (см. §4a): единый `EvidenceBundle` подключён в живой
  конвейер decision→tools→synthesis(System2)→формулировка; SC-09/SC-10 и A04
  (разные ветки → разный `context_version`) покрыты тестами.
- **A04 на полном `handle`-e2e** не гонялся (тяжёлый скелет handler’а); покрыт
  на уровне точек конвейера: reply-граф-ветка → `context_version`,
  System2-срез, отсутствие text-replay. Для `handle`-e2e используется
  существующий регрессионный набор `direct` (зелёный).
- **`retrieve()` как вызываемая точка живого direct-пути** пока не подключена:
  решение о retrieval-вызове — зона потребителей (`mca-09`/`mca-10b`/`mca-15`);
  контракт+каналы реализованы и протестированы.
- **PG no-op** проверен по коду (SQLite-механизм; `pg_db.py` не вызывается);
  отдельного PG-инстанса в тестах нет.
- **`EXPLAIN QUERY PLAN`** для 3 индексов v18 — обосновано shape запросов
  (резолв `(index_name,status='active')`, lookup `fingerprint`); отдельный
  EXPLAIN-прогон на прод-объёме — вход `mca-04b`/review.
- **Контекст-версия во время rob-цикла:** `constraints` = текст текущего
  вопроса (может быть длинным); в срезе он не обрезается дополнительно (в
  Stage-1 уже присутствует как `СООБЩЕНИЕ ЮЗЕРА`) — bounded по построению
  самого блока.

## 6. Manifest для @Reviewer

- **Baseline:** `05bc870` (HEAD, без новых коммитов).
- **Tracked-diff (мои файлы):** см. §1; полный `git diff --stat` включает
  pre-existing изменения волн 0/1a/04a (не мои — dossier/image/lore/… ).
- **Untracked (NEW):** `services/mca_retrieval_context.py`,
  `tests/test_mca07_retrieval_context_round1027.py`,
  `plans/features/mca-07-retrieval-context/{evidence,threat-failure-analysis}.md`
  (+ уже существовавшие untracked волны).
- **Не трогал:** `plans/current_task.md`, `workflow_state.md`, `metrics.md`,
  `MEMORY.md`, `pg_db.py`, `param_catalog.py`, чужие фичи, коммитов/тегов/bump нет.
- **Working-tree hash:** не фиксировался (Orchestrator — единственный writer
  `workflow_state`); Reviewer строит свой манифест по `git status`/`git diff`.

## 7. Deploy/rollback (T-3856, `DEFERRED_TO_RELEASE`)

- Пер-фичевого деплоя/тега/bump нет. Вход в `mca-release`: migration smoke v18
  (fresh+legacy), effective-state §20.2, manifest `config changes` — имена 6
  kill-switch.
- **Hot-откат:** env-OFF 6 гейтов (`MCA_RETRIEVAL_CONTEXT_ENABLED`,
  `MCA_EVIDENCE_BUNDLE_ENABLED`, `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED`,
  `MCA_TYPED_RERANKER_ENABLED`, `MCA_SUMMARY_SINGLEFLIGHT_ENABLED`,
  `MCA_CONTEXT_ANSWER_CACHE_ENABLED`) → паритет baseline.
- **Cold-откат:** `git revert` → `05bc870` (anchor `7165ff7`); DDL v18 аддитивна
  (новая таблица/колонки безвредны; restore БД — только аварийный сценарий).

## 8. Rework-манифест (для повторного gate)

- **Изменённые в rework файлы:** `services/database.py` (ensure/latest/fingerprint),
  `services/summary_memory.py` (регистрация/guard/preexisting), `services/token_counter.py`
  (`estimation_method`), `services/direct_chat_service.py` (external-estimate,
  pre-flight, bundle current/summary/mentioned/relations, answer_cache stage),
  `services/mca_retrieval_context.py` (`exact_match_used`),
  `tests/test_mca07_retrieval_context_round1027.py` (+9 тестов),
  `plans/features/mca-07-retrieval-context/{evidence,threat-failure-analysis,tasks}.md`.
- **Числа rework:** pytest **9758/0**; JS **47/47**; `git diff --check` 0.
- **Пометить (решение @Architect):** M-MCA07-2 carry-over (поля
  `ambiguities/local_context/persona/interests/unknown/contradictions`) и
  L-MCA07-5 (`retrieve()` без живого caller). ADR-1027-7 остаётся **Proposed**
  до успешного повторного gate.

_Конец. @Builder Step 3 + rework по `review.md` (B/M/L). Готово к повторной
независимой проверке @Reviewer._
