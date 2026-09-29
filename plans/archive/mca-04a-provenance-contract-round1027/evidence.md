# `mca-04a-provenance-contract` — evidence (Step 3 @Builder, T-3821…T-3834)

- **Фича:** `mca-04a-provenance-contract` (round 10.27 MCA, Wave 1). **Risk R3.**
- **Baseline:** Reviewed-Commit `05bc870`; `APP_VERSION` **2.58.31**; SQLite DDL
  **v16 → v17**; каталог **473/430/448/102/100/21** (Δ=0); канон 12.
- **Deploy:** `DEFERRED_TO_RELEASE`. **Без коммитов/bump** (рабочее дерево).
- **Recovery-контекст:** предыдущая Builder-сессия успела добавить v17-DDL
  (`services/database.py`) и kill-switch (`services/mca_gates.py`,
  `config/settings.py`), но НЕ обновила целевые версии в существующих тестах
  (после регистрации v17 fresh-БД даёт `user_version=17`, а baseline-тесты
  ждали 16). Частичная работа **сохранена**, доведена до зелёного состояния.

## Изменённые/новые артефакты

| Артефакт | Режим | Суть |
|---|---|---|
| `services/provenance.py` | **NEW** | Контракт SourceRef/EvidenceLink/статусов; резолверы; субъект-атрибуция; восстановление §8.2; row-bound валидатор; локальные evidence→SourceRef; события MCA-13 |
| `services/database.py` | AMEND | v17 (3 таблицы + 6 nullable-колонок `graph_facts` + индексы, backfill только прямых ссылок, guard по колонкам); `insert_graph_fact` +6 provenance-колонок; `get_persona_card`/`get_user_context_facts` subject-scope + исключение world_knowledge/self-referential; `_person_scope_clause`; `person_fact_exists` |
| `services/mca_events.py` | AMEND | +5 `reason_code` (provenance_linked/unresolved/evidence_invalid/reconstructed/conflict) |
| `services/direct_chat_service.py` | AMEND (FIX п.1) | `_apply_fact_attribution`: target=asker → валидируемая субъект-атрибуция (self_report/third_party/world_knowledge), subject_ref, SourceRef; self-report — субъект по `asker_user_id` (B-MCA04A-1); OFF → legacy `_reassign_fact_owners` |
| `services/summary_memory.py` | AMEND (producer) | `_attach_fact_provenance`: новый факт пишет SourceRef/EvidenceLink (кроме bot_direct_reply — там FIX п.1) |
| `services/lore_worker.py` | AMEND (FIX п.3 + п.5-врезка) | `_write_person_facts`: валидированные person_facts Layer A сохраняются `unconfirmed` + subject_ref + object SourceRef независимо от портрета; вызов до Layer B; `row_count` проброшен в `filter_layer_a_candidates` (multilayer + `_extract_chunk`, D-MCA04A-1) |
| `services/dossier_prompts.py` | AMEND (FIX п.5-контракт) | `filter_layer_a_candidates` + `row_count`/`message_lookup` (row-bound/existence) |
| `services/dream_worker.py` | AMEND (producer) | `record_source_ids_provenance` для belief/paradigm (`derived_from` SourceRef) |
| `tests/test_mca04a_provenance_round1027.py` | **NEW** | 34 теста контракта/интеграции (A09/A10/A85/A86/A88/A95; +4 rework B-MCA04A-1/D-4/-5/-1) |
| Существующие тесты | AMEND | 16→17 в 14 файлах (следствие v17); `test_mca01...` allowlist `database.py` 109→116 (санкционированные commit шага v17, `_migrate_*`); `test_multilayer...` приведён к FIX п.3 |

**Protected/вне diff (не тронуты):** `plans/current_task.md`, `services/pg_db.py`,
`tools/gen_param_registry_*/param_catalog.py`, `plans/workflow_state.md`,
`plans/metrics.md`, `plans/MEMORY.md`, `plans/ARCHITECTURE.md` (Merge — @Architect).

## v17 / Δ DDL / Δ каталога / kill-switch

- **v17** зарегистрирован в реестре `mca-14` (`MigrationStep(17, "provenance_contract")`).
  `mca_source_refs` (+`idx_mca_source_refs_dedup`, `idx_mca_source_refs_chat_type`),
  `mca_evidence_links` (+`idx_mca_evidence_links_dedup`/`_subject`/`_source`),
  `mca_provenance_status`, 6 nullable-колонок `graph_facts`
  (`subject_ref_id`/`attribution_method`/`assertion_kind`/`speaker_author_id`/
  `extractor_version`/`provenance_channel`) + `idx_graph_facts_subject_ref`.
- **Backfill — только прямые ссылки:** объектный SourceRef на каждый `graph_facts`
  (guard — отсутствие объектного), `origin_status='original'` **только** при
  сохранённом `tg_message_id`; иначе `unknown`. Существующие `source_ids`
  belief/paradigm → `derived_from`. Семантический поиск НЕ выполняется (A09).
- **Идемпотентность:** повторный `initialize()` → 0 дублей/изменений,
  `user_version=17` (тест `test_v17_idempotent_noop`).
- **Legacy/U-сечения:** старые `id`/`timestamp`/FTS/`origin` CHECK сохранены;
  шаг self-guard по `sqlite_master`/`PRAGMA table_info`; на усечённой legacy-БД
  без `status`/`source_ids` индекс/часть backfill деградируют (не падают).
- **Δ каталога = 0** (`param_catalog.py` вне diff; F8 NOT_APPLICABLE).
- **Kill-switch (env-only, default ON, per-call):** `MCA_PROVENANCE_ENABLED`,
  `MCA_FACT_ATTRIBUTION_ENABLED`, `MCA_EVIDENCE_RECONSTRUCTION_ENABLED`;
  reconstruction/attribution инертны при provenance=OFF (тест
  `test_kill_switch_off_parity`).
- **PG — no-op** (`pg_db.py` вне diff).

## Тесты (факт)

- **pytest `.venv`: 9712 passed / 0 failed** (baseline 9708/0 на ревью; +4 новых
  теста rework). **JS: 47/47** (`node tests/js/*.js`, exit 0).
- **Focused mca-04a: 34 passed** (30 на ревью + 4 rework).
- `git diff --check`: exit 0 (только LF→CRLF warnings git).
- Покрытые сценарии: v17 (fresh/идемпотентность/backfill прямой-only/legacy-сохранность);
  SourceRef типизация/opaque/валидация; EvidenceLink 5 типов + поля + дедуп;
  A10 (один SourceRef → одно доказательство), bot self-referential ≠ подтверждение;
  статусы + отдельные поля (+ сохранение conflict/freshness/coverage при повторной
  записи origin); A85 (world_knowledge/бот исключены в
  `get_user_context_facts`/`get_persona_card`); subject устойчивый ID / unresolved /
  одноимённые **не** сливаются (≥2 id → `unresolved`, читатели изолированы);
  self-report по `user_id` говорящего; FIX п.1 (субъект-атрибуция); FIX п.3
  (person_facts при отсутствии портрета, `unconfirmed`, object SourceRef,
  идемпотентность); FIX п.5 (row-bound/validity/локальные evidence двух чанков —
  разные SourceRef; `sqlite3.Row`-вход; row-bound подключён в `_extract_chunk`);
  A09 (нет ложного `original`, recon не переименовывает `original`, факт сохранён);
  producer `source_ids`→`derived_from`; R17 (`basis`≤160, `checks_json` коды);
  события MCA-13.

### Точность покрытия приёмок (без завышения)

- **A86** — покрыт на **helper-level** (`_write_person_facts` сохраняет
  `person_facts` независимо от портрета, `unconfirmed` + SourceRef); полный
  Layer-B-e2e со сбоем синтеза портрета — реальный прогон в `mca-04b`.
- **A95** — покрыт **синтетическим** `claim_key`-тестом (coverage per assertion);
  реальная выборка досье (Леха/Вася/Ярик, разные периоды, precision/recall) —
  граница `mca-04b` (см. carry-over ниже).
- **A85/A88/A09/A10** — покрыты на обновлённых путях с включёнными функциями.

## Rework по ревью T-3835 (`Needs Fixes`)

- **B-MCA04A-1 (High), fixed:** `services/provenance.py`
  (`_lookup_user_ids_by_names`, `resolve_subject_ref`) + `services/direct_chat_service.py`
  (`_apply_fact_attribution` self-report по `asker_user_id`). Одноимённые при ≥2
  различных `user_id` → `unresolved` со стабильным канон-именем (без выдуманного
  TG ID); self-report — субъект = говорящий. Тесты: усилен `test_same_name_not_merged`,
  новый `test_self_report_uses_speaker_user_id`.
- **D-MCA04A-1 (Medium), fixed:** `services/lore_worker.py` — `row_count` проброшен
  в `filter_layer_a_candidates` (multilayer + `_extract_chunk`). Тест
  `test_fix_p5_extract_chunk_row_bound_wired`; `test_multilayer_extraction_round1021`
  приведён к валидному окну.
- **D-MCA04A-4 (Low), fixed:** `set_provenance_status` сохраняет
  conflict/freshness/coverage при повторной записи origin.
  Тест `test_status_repeat_preserves_separate_fields`.
- **D-MCA04A-5 (Low), fixed:** `_row_field` + `local_evidence_to_source_refs`
  принимает `sqlite3.Row`; пустой id → `valid=False`.
  Тест `test_fix_p5_local_evidence_accepts_sqlite_row`.
- **D-MCA04A-6 (Low), fixed:** `guess_subject` — детерминированный порядок
  (длиннейшее имя → алфавит), без зависимости от порядка `set`.
- **D-MCA04A-7 (Low, perf), note исправлен:** один bounded-скан на резолв;
  остаточная стоимость зарегистрирована как вход `mca-04b`/`mca-release`.
- **D-MCA04A-2/-3, registered (вход `mca-04b`):** прод-вызов
  `reconstruct_fact_provenance`; реальная выборка досье A95 — см. `tasks.md`
  «Carry-over». Покрытие A86/A95 в этом файле приведено к фактическому
  (helper-level / synthetic `claim_key`), без завышения.
- **Δ DDL/каталог не менялись:** v17, Δ каталога 0; `APP_VERSION` без bump;
  коммитов/тегов нет. Invariants 1–10 сохраняются.

## Не проверено / ограничения

- **Реальная прод/рабочая БД** (GEN-R20 заполненность ID, пересечения импорт↔live) —
  недоступна локально; вход `mca-release`/@Memory (как и §96.4).
- **PG-путь** — no-op по дизайну (кода нет); e2e PG не запускался.
- **DreamWorker e2e**: `_write_belief`/`_write_paradigm` вызывают
  `record_source_ids_provenance` (fail-open), helper покрыт unit-тестом;
  отдельный e2e-прогон сна с typed-линками не выполнялся (LLM-мок).
- **Chunked-пайплайн** (`_classify_chunked_user`) фактическая врезка
  локальный→SourceRef — граница `mca-04b` (в 04a — валидатор + конвертер).
- `L-MCA03-8` (отпечаток namespace) — не в 04a; обязательный вход `mca-04b`.
- Веб-браузерная проверка не требуется (backend/data; `Browser-Verification`
  не помечен REQUIRED).

## Deploy / откат (T-3834, `DEFERRED_TO_RELEASE`)

- **Hot:** `MCA_PROVENANCE_ENABLED=false` (и/или `MCA_FACT_ATTRIBUTION_ENABLED=false`,
  `MCA_EVIDENCE_RECONSTRUCTION_ENABLED=false`) → паритет baseline.
- **Cold:** `git revert` → `05bc870` (анкер `7165ff7`); v17 аддитивна (новые
  таблицы/колонки безвредны). Restore БД — только аварийный (R18).
- **На `mca-release`:** backup+read-back, migration smoke v17 (fresh+legacy,
  идемпотентность/backfill), manifest (`config changes`: имена kill-switch).
