# ASAP 4.1 — evidence.md

> Папка фабрики поднятых planning-артефактов (`requirements-map.md`,
> `conflict-audit.md`, `reuse-inventory.md`, `spec.md`, `adr-1028-8-…`,
> `tasks.md`) — см. соответствующие файлы рядом; этот файл —
> implementation/verification evidence по волнам Builder.

---

## Wave 2 — Блок B: T-4603 / T-4604 / T-4605 / T-4606 (03.10.2026)

**Role:** Builder (windа 2: «Source/Capacity»). База — worktree 2.58.46
(commit `fe6b5db`, prod SQLite user_version=23). Режим: без коммитов,
без деплоя; единственный writer — Builder; Reviewer отдельно.

### Базис и файл-манифест (для детерминированной ревизии Reviewer)

Изменённые/новые исходники (всякая правка — additive в пределах зоны A):

| Файл | Статус | Якоря |
|---|---|---|
| `services/summary_source_window.py` | **new** (T-4603) | SummarySourceWindow dataclass frozen :116; build :156; durable_enabled :47; retention_days :58; store :221; load :242; purge :253 |
| `services/database.py` | *modified* (T-4603) | v24-константа :866; DDL `_SUMMARY_SOURCE_WINDOWS_DDL` :868-877; write-once guard `_summary_window_unique_violation` :880-892; MigrationStep :1773-1776; `_migrate_summary_source_window_v24` :2477-2495; save :2615; get :2649; purge :2672 (все write через `write_transaction`, L-MCA14-3-совместимо, без прямых commit) |
| `services/summary_generator.py` | *modified* (T-4603) | Единая точка snapshot'а сразу после SOURCE_WINDOW/empty-check :522-537 (вызов `_establish_source_window`), метод :603-649 (событие+лог R17, fail-open, TTL-purge) |
| `services/pipeline_events.py` | *modified* (T-4603/04/06) | EV_* :36-41 (SUMMARY_SOURCE_WINDOW_READY/CAPACITY_RESOLVED/EXECUTION_MODE_SELECTED/SEGMENT_PLAN/_RESULT/_LEDGER); emitters :134-196 (R17, fail-open) |
| `services/mca_events.py` | *modified* | REASON_CODES: +8 кодов зоны A (fits_effective_context / serialized_payload_exceeds_effective_context / capacity_cache_invalidated / capacity_overflow / fits_after_fallback / segment_artifacts_exist / segment_restored / segment_failed_after_restore / coverage_ledger_missing) |
| `services/model_capacity.py` | *modified* (T-4604/05) | AMEND AM-2 (override → уровень 4) `_resolve_uncached` :770-856; fingerprint :641; selective invalidate_runtime_capacity :665; MODE_* :327-328; SummaryCapacityPlan :906; decide_summary_mode :935; replan_summary_capacity :974 |
| `services/summary_l1_clusterizer.py` | *modified* (T-4604/05/06) | kill-switches :1206-1234; capacity-снапшот :1235-1257; _emit_capacity_events :1259-1301; run_l1_capacity_first :1297-1460; branch в run_l1 :1504-1511; _run_l1_lossless extend (ledger/restore/events, аддитивно) :812-1014; честный degraded-gate :989-1014 |
| `services/summary_coverage_ledger.py` | **new** (T-4606) | CoverageLedger :78; stable_message_id :42; verify :127; require_full_coverage :151; snapshot_dict :165 |
| `config/settings.py` | *modified* | kill-switches + retention (env-only ClassVar, Δ каталога = 0) :908-927 |
| `pytest.ini` | *modified* | маркер `asap41` (изоляция conftest) |
| `tests/conftest.py` | *modified* | _asap41_flags_off_by_default (OFF-паритет для не-маркированных; ON-блок помечен для маркированных) |

Тесты-файлы (новые, все `@pytest.mark.asap41`):

* `tests/test_summary_source_window_asap41.py` — 16 тестов (T-4603):
  §2-схема/полное окно без срезов/forward+media; frozen+deep-copy;
  readback байт-идентичен; write-once без overwrite; UPDATE-surface
  guard (строка-скан: "UPDATE summary_source_windows" отсутствует);
  миграция v24 fresh + идемпотентный повтор; PG no-op (SQLite-scan);
  TTL purge; retention env; kill-switch OFF (0 записей); единая точка
  + событие R17 (тексты сообщений не утекают).
* `tests/test_summary_capacity_asap41.py` — 19 тестов (T-4604/05):
  цепочка §5 (runtime/catalog/registry выше override; override
  применяется только над fallback); serialized-учёт (контрпример «только
  message.text»); decide-формула + Inspector-поля; §44-A WHOLE_WINDOW
  (1 запрос, без эвикций); §44-B/C/D/D2/E; fingerprint/invalidation;
  never-raises; events (R17-scan); master OFF (байт-в-бит);
  ledger OFF (текущий lossless-контур).
* `tests/test_summary_coverage_ledger_asap41.py` — 10 тестов (T-4606):
  Ledger-инварианты (XOR coverage, overlap dedup, stranger-ids, fail-
  closed missing), снапшот R17; §44-B интеграция (300 → N сегментов →
  все covered, no truncation, L1-запросов == сегментам); restore
  (ровно 1 повторный run только проблемного сегмента — «сегмент упал»);
  честный degraded («сегмент упал навсегда» → error_result, НЕ
  success; события RESULT/LEDGER); «потеря невозможна по построению»
  (auto-unassigned инвариант §95-v2 + ledger).

Обновлённые существующие тесты (контрактные пины, аменды под ADR-1028-8):

* `tests/test_capacity_resolver_asap31.py` — §40.4 переименован
  (test_developer_override_below_registry / _applies_above_fallback)
  по AMEND AM-2.
* `tests/test_capacity_nanogpt_asap32.py` — test_developer_override_
  applies_below_registry (аналог).
* `tests/test_summary_coverage_asap31.py` — two off-parity тесты
  (`test_off_chunking_keeps_legacy_truncation`,
  `test_off_auto_budget_keeps_legacy_static`) получили pin master
  `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED=False` (их семантика — прежний
  контур, теперь закреплён как OFF-паритет spec §11.1).
* `tests/test_embedding_control_plane_asap4.py` — user_version==23 → >=23
  (`test_v23_migration_additive_idempotent`; v24 аддитивен).
* `tests/test_mca05_episodes_stories_round1027.py` — mark хвоста реестра
  v23→v24 (`_SCHEMA_VERSION_STORIES_MARK = _SCHEMA_VERSION_TAIL_V24`,
  конвенция волн).
* `tests/test_mca22_core_round1027.py` — 2 пина user_version: >=23.
* `tests/test_mca01_tx_task_supervisor_round1027.py` — allowlist
  database.py 147→149 прямых commit (санкция L-MCA14-3: v24-step DDL;
  runtime-save/purge идут через write_transaction, прямых commit нет).
* `tests/test_tool_coordinator_round1026.py` — summary_changed
  allowlist + `services/summary_source_window.py`,
  `services/summary_coverage_ledger.py` (новые модули зоны A; см.
  known-failures ниже — этот тест остаётся в известном состоянии).

### DDL-факт

* SQLite: `user_version 23 → 24`; строка MigrationStep(24,
  "summary_source_windows") в реестре (database.py:1773); шаг —
  `CREATE TABLE IF NOT EXISTS summary_source_windows (run_id TEXT
  PRIMARY KEY, chat_id INTEGER NOT NULL, window_from INTEGER,
  window_to INTEGER, source_message_count INTEGER NOT NULL,
  messages_json TEXT NOT NULL, created_at INTEGER NOT NULL)`;
  `NI ОДНОГО UPDATE/DELETE` существующих строк при миграции;
  повторный прогон — no-op; книга `schema_migrations` дописывает v24
  row; идея тести pин `user_version == 24` (fresh) и идемпотентность
  повторного шага.
* **PostgreSQL: no-op** — SQL-слой фичи только в SQLite
  (DatabaseService); PG-DDL/asyncpg в новом коде отсутствуют
  (scan-тест). Cover style PG-таблицы не тронуты.

### Kill-switches зоны A (spec §11.1, env-only, default ON, Δ каталога = 0)

* `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED` (settings.py:918) — OFF →
  snapshot не пишется (0 записей, зафиксировано тестом), in-memory
  rows, бит-в-бит 2.58.46.
* `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED` (settings.py:920) — OFF →
  планировочно-оценочный шардинг волны C + статические бюджеты как
  сегодня (capacity-снапшот не пишется; тест), вся ветка min-в-cycles
  (см. branch run_l1:1505).
* `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED` (settings.py:922) — OFF →
  прежний lossless-chunking `_run_l1_lossless` без
  ledger/restore-семантики (тест).
* Resolves per-call, никогда не бросает (паттерн `_env_bool` ClassVar +
  getattr-guard в каждом модуле зоны).

### Наблюдаемость (R17)

* События (единый transport mca_trace→mca_events):
  `SUMMARY_SOURCE_WINDOW_READY` (messages/window_from/window_to/
  durable), `SUMMARY_CAPACITY_RESOLVED` (effective/required/reserve/
  margin/window_source/confidence/fallback_used/mode/reason/budget_
  mode/segments), `SUMMARY_EXECUTION_MODE_SELECTED` (mode+reason,
  human причина), `SUMMARY_SEGMENT_PLAN` (segments), `SUMMARY_SEGMENT_
  RESULT` (attempt, reason), `SUMMARY_SEGMENT_LEDGER` (counts/percent/
  lossless; missing>0 или fallback>0 → WARN degraded, НИКОГДА не
  маскируется успехом).
* Provider — только host (provider_host), model, числа, enum; пустой
  payload-текст/ключи/полнotext сообщений НЕ попадают (fixture-тест
  R17 в каждом файле).
* Reason-коды через `mca_events.REASON_CODES` (+9 новых, расширяемый
  словарь §17.2).

### Команды и результаты

* Точечные: `pytest tests/test_summary_source_window_asap41.py
  tests/test_summary_capacity_asap41.py
  tests/test_summary_coverage_ledger_asap41.py` — **45 passed**.
* Соседи: `pytest -k summary` — **1329 passed** (0 failed);
  `pytest test_database/test_mca14/test_embedding_control_plane` —
  184 passed; `test_mca05/test_mca22/test_mca01` — 91 passed;
  capacity-набор (asap31/asap32/auto-budget/context-policy) — passed.
* **Полный pytest: 10884 passed, 2 failed, ~5 м 16 с**
  (`pytest tests -q --timeout 180`).
* F8-чек (каталог): `python tools/gen_param_registry_round1025.py
  --check` → **EXIT=0** («CHECK OK: реестр 488 == REGISTRY, карта
  полна, R17-чисто, TSV/map идемпотентны»). Каталог/версия не менялись
  (Δ каталога = 0 — by design зоны A).
* Гигиена: все изменённые/новые файлы без BOM, UTF-8; EOL соответствуют
  собственному статусу (LF — многие, CRLF — только settings.py/conftest,
  соответствование их pre-стилия); compile-check EXIT=0.
* Смок-прогоны: WHOLE_WINDOW single-call на registry 131072 (snapshot:
  required 1281/reserve 4000/margin 108694) и CAPACITY_OVERFLOW на
  manual-cap 700 (40 сегментов, 40 ids covered, coverage 100%).

### 2 known failures (pre-existing, вне зоны A; РЕПОРТ честно)

1. `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_
   paths_out_of_diff` — bounds-тест diff-vs-`pre-round1026-a1` падает на
   web/-файлах, изменённых прошлыми САНКЦИОНИРОВАННЫМИ волнами
   (web/api/analytics.py — ASAP-4 волна E; web/api/cover_styles.py —
   EXTRA D12; web/static/polygon-background.js / telegram-init.js —
   ранние волны) и НЕ внесённых в allowlist-набор того теста; плюс
   позволяет-список summary_* не содержал модули прошлых волн
   (summary_budget_auto/l1_capacity/l2_review/legacy_fullwindow/
   quote_repair/semantic_reduction).    В рамках волны 2 добавлены ТОЛЬКО мои новые модули в allowlist
   (summary_source_window.py, summary_coverage_ledger.py); сам тест
   остаётся failed на pre-existing web/-части — отдельная санкция/фикса
   вне зоны A (web/-файлы в скоуп волны 2 не входят).
2. `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_
   forbidden_paths_out_of_dif_f_vs_baseline` — та же природа
   (web/-часть pre-existing; `db/`, `web/` не тронуты волной 2).

Оба падения воспроизводятся на чистой базе 2.58.46 (файлы web/*
изменены коммитами ранее; волна 2 их не затрагивала) — «2 known» из
директивы.

### Честные остатки / границы волны 2 (на приёмку Reviewer)

1. **Partial-success deterministic minimal maps** (T-4608, зона B):
   волна 2 при невосстановимом сегменте возвращает честный degraded
   (error_result; LEVEL-2 ladder от ПОЛНОГО набора), а не сохранение
   3/4 maps + minimal map — явно зона B.
2. **Hierarchical Writer/Reviewer** по сегментам с ledger-покрытием —
   зона B/C (T-4609/T-4610).
3. **Гейт purge «после DONE/FAILED»** — полный вариант встанет с
   durable `summary_runs` (зона F, T-4616/4617); волна 2 удаляет только
   окна старше TTL-горизонта (default 7 дней) fail-open при старте
   прогона.
4. **Supervisor-врезка re-plan** в реальный provider-fallback каскад —
   зона D (T-4612/T-4613); волна 2 даёт API `replan_summary_capacity`
   + контракт + тесты §44-D/E. В туда же входит wiring «runtime
   400/context-length → инвалидация + переоценка в рамках run»:
   механика готова (`invalidate_runtime_capacity`, R17-события), точка
   вызова — единая orchestration-политика Supervisor'а (no-retry-
   multiplication ADR-1028-8 D5.3 запрещает второй retry-контур в волне 2).
5. Inspector-карты читают structured state (`_capacity_plan_snapshot`,
   `last_run_coverage`, ledger events) при врезке зоны G (T-4621/4622).
6. external verification: новых зависимостей/сетевых протоколов в
    волне 2 не появилось (только stdlib + существующие httpx-fallback
    адаптеры ADR-1028-3) — Context7/Exa-проверка не требовалась;
    все вызываемые API — существующие контурные контракты проекта.

MEMORY_DELTA: (оркестратору, волна 2) — durable-факт зоны A: SQLite v24
таблица summary_source_windows write-once; kill-switches
SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED / SUMMARY_WHOLE_WINDOW_FIRST_ENABLED
/ SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED (env-only, default ON); AMEND
ADR-1028-3 (override → уровень 4) реализован и закреплён тестами.

---

## Wave 3 — Зоны B/C: T-4607 / T-4608 / T-4609 / T-4610 / T-4611 (03.10.2026)

**Role:** Builder (волна 3: «L1/W/R/Legacy»). База — worktree волны 2
(те же непрокоммиченные файлы в дереве; режим: без коммитов, без деплоя;
kill-switches зон A остаются in-tree от волны 2). Спека: spec.md §2/§3 +
ADR-1028-8 D3/D4/D5-сохранение bounded revision.

### Файл-манифест волны 3 (для детерминированной ревизии Reviewer)

Новые модули/tests:

| Файл | Статус | Якоря |
|---|---|---|
| `services/summary_l1_semantic_map.py` | **new** (T-4607) | MapResult :144; semantic_map_enabled :111; validate_semantic_map :260; compact_semantic_map :513; merge_map_payloads :685; minimal_map_for_rows :825; map_correction_block :654; resolve_map_budgets :120 |
| `services/summary_fact_view.py` | **new** (T-4609) | FactViewResult :47; build_fact_view_from_map :114; fallback_view_for_items :250; ensure_full_id_space :302; slice_map_for_ids :334; slice_package_threads :378 |
| `tests/test_summary_semantic_map_asap41.py` | **new** | 27 тестов (контракты map/compaction/correction/minimal-map/overflow-partial/§46 L1-fail) |
| `tests/test_summary_writer_source_asap41.py` | **new** | 18 тестов (WriterInput contract/full-window w/ absent или урезанный fact view/синтез/иерархический Writer/OFF-канон) |
| `tests/test_summary_reviewer_source_asap41.py` | **new** | 12 тестов (Reviewer против окна/R6-B-007/evidence-slices/§50.11 тех же контрактов/gate OFF) |
| `tests/test_summary_legacy_source_window_asap41.py` | **new** | 11 тестов (snapshot-вход/капы/dead-path/hierarchical/split delivery/OFF-parity) |
| `tests/test_summary_golden_839_asap41.py` | **new** | golden: 839 synthetic → WHOLE_WINDOW 1 L1-запрос, coverage 100%, 420+ сообщений в теме (too_many_facts-класс невозможен), Writer/Reviewer от окна, run жив до публикации |

Изменённые исходники (аддитивно):

| Файл | Изменение | Якоря |
|---|---|---|
| `config/settings.py` | +5 env-only ключей зоны B/C (Δ каталога = 0, все ClassVar) | :931–948 (SUMMARY_L1_SEMANTIC_MAP_ENABLED / SUMMARY_WRITER_SOURCE_INPUT_ENABLED / SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED / SUMMARY_L1_HINT_MAX_CHARS / SUMMARY_L1_MAP_MAX_TOKENS; SUMMARY_L1_MAP_MAX_TOKENS/HINT — `_env_int_min(..., min 1)`) |
| `services/summary_l1_contract.py` | L1Result аддитивен: map_degraded/map_reason/map_stats + as_metrics | :191–232 |
| `services/summary_l1_clusterizer.py` | map-режим run_l1 (`_map_mode` — через capacity-first), map-парc/validation/compaction/correction; overflow: minimal-карты + honest `SUMMARY_SEGMENT_RESULT` до minimal / `SUMMARY_SEGMENT_MINIMAL_MAP` (WARN) / map-merge | :109–124 импорты; :1377 `_map_result_to_l1`;:1840 map-ветка; :1906–1962 retry/«§95 остаётся OFF»-gates; :914–952 `_run_l1_lossless` partial-success; merge by mode :1005+; L1_COMPLETE `map_degraded=` (аддитивное поле логов) |
| `services/summary_l2_writer.py` | `_length_block` (тот же текст length-блока, извлечён), `build_l2_source_input`, `build_writer_merge_input`, `writer_source_input_enabled()`, run_l2(source_input=, length=), канон-фон = PREV/новый по флагу | :554/:579/:614/:1234 |
| `services/summary_l2_review.py` | run_l2_with_review аддитивные параметры (writer_source_input/writer_length/semantic_map/source_window_content/evidence_slices/review_full_window/review_payload_items/source_message_ids); build_review_content/build_revision_content + секции; build_review_evidence_slices; ReviewResult id-space = пакет ∪ окно (`ensure_full_id_space`) | :632 run_l2_with_review; :425 slices; :400–470 content-builders (system prompt + блок ИСТОЧНИК); :786 parse_review_verdict / :889/:893 revision-validate через run_package |
| `services/summary_generator.py` | writer-source ветка, честный L1_STAGE counts (map_degraded), derived-view branch, coverage=100% от окна при writer_source, иерархический Writer + merge-pass, зона C (Legacy отом snapshot/капы/screening out hierarchical/split delivery) | импорты/хелперы :188–260; `_source_window_ids` :188; `_writer_capacity_fits` :700; `_reviewer_capacity_fits` :735; `_merge_writer_documents` :760; `_run_writer_source_stage` :800; `_hybrid_l2` rewiring :1430–1720; `_run_legacy_pipeline` зона C :1113–1230; `_legacy_capacity_fits` :1765; `_run_legacy_hierarchical` :1795; `_deliver_plain(split_delivery=)` :2900 |
| `services/summary_xml.py` | build(window_caps=...) — аддитивный параметр; None → прежние капы (байт-в-байт), (None,None) → капы отпущены (ON-ветка; dead-path «XML context: hard cap» в ON) | :54–101 |
| `services/summary_legacy_fullwindow.py` | legacy_source_window_enabled / snapshot_rows / load_legacy_rows | :42–78 |
| `services/pipeline_events.py` | l1_stage(counts=) — аддитивный честный срез map_degraded (R6-G-001; «ok»-маска невозможна — counts рядом с результатом) | :207–226 |
| `services/mca_events.py` | +4 reason-кода: map_compacted / map_degraded / semantic_map_unavailable / minimal_map_synthesized | :191–196 |
| `services/summary_prompts.py` | канон L1 «semantic map v1» (литерал; байт-идентичен эталону канона); канон L2 R1030 (блок ИСТОЧНИК, литерал); PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41 (superseded-слепок 2.58.46); PREV_SUMMARY_L2_WRITER_R1029_ASAP41; блок канона Reviewer SUMMARY_L2_REVIEWER_SOURCE_BLOCK (не-мигрируемый, append при source) | L1 :390–422; L2 :681–708; reviewer-block :745–760 |
| `services/prompt_migrations.py` | FORWARD + (PREV_L1_R1027_ASAP41 → L1-канон) / (PREV_L2_R1029_ASAP41 → L2-канон); ROLLBACK → прежние прод-каноны | :73–82, :178–191, :196–202, :258–270 |
| `tests/conftest.py` | `_asap41_flags_off_by_default`: +3 флага зоны B/C (не-asap41 → OFF = бит-в-бит; asap41 → ON) | :208–260 |
| `plans/docs/canon/architecture.md` | эталон канона: L1 new map v1 (литерал) + блок источника L2 (литерал) — байт-идентично коду (пин-тесты canon_doc_byte_identical) | :565–600, :602–725 |
| `tests/test_summary_l1_clusterizer.py` / `test_summary_l2_writer.py` / `test_prompt_migrations.py` / `test_summary_asap21_prompt_migrations.py` | аменды пинов под миграцию канонов (код+эталон+тесты одним изменением — прецедент R4-D-003); пины waves честно: старые каноны в PREV, новые токены map-v1/блок источника | тесты :536–553 (canon), :973–981 (rollback); :507–560; :185–190/205–220; :52–61 |
| `tests/test_summary_capacity_asap41.py` / `test_summary_coverage_ledger_asap41.py` | L1-моки map v1 (выход по умолчанию — map), пин master-OFF через §95-mock; «segment упал навсегда» — аменд под T-4608 (minimal-map вместо error; map_degraded честно, события honest) | :92–99; :492–530; ledger :205–215, :255–278 |
| `tests/test_summary_execution_graph_round1026.py` / `test_tool_coordinator_round1026.py` / `test_unified_image_request_round1026.py` | allowlist-расширения: санкция зоны C (summary_xml window_caps) + новые summary_ модули; ***web/-падение остаётся pre-existing (вне волны)*** | :438–446; :710–730 |

### Контракты и kill-switches зоны B/C (spec §2/§3 + §11.1)

* `SUMMARY_L1_SEMANTIC_MAP_ENABLED` (settings.py:937, default ON): ON →
  только capacity-first ветка run_l1 (master SUMMARY_WHOLE_WINDOW_FIRST_
  ENABLED) переключает L1 на map v1 (validate/compact/merge; correction
  retry с map-коррекцией); OFF → parse_l1_response/repair_l1/
  validate_l1_response + too_many_facts (тест test_run_l1_kill_switch_
  off_keeps_v2; планируемая опора planning estimate на OFF как в 2.58.46 —
  unchanged, map врезается только в capacity-first ветке).
* `SUMMARY_WRITER_SOURCE_INPUT_ENABLED` (settings.py:940, default ON):
  OFF → генератор не строит source-вход, run_l2 получает FactPackage-
  центричный вход (build_l2_input), канон fallback = PREV_SUMMARY_L2_
  WRITER_R1029_ASAP41 (байт-в-байт). Тесты: test_off_run_l2_content_is_
  package_input + существующие не-asap41 тесты (conftest OFF-изоляция)
  остались зелёными — бит-в-бит путь сохранён.
* `SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED` (settings.py:941, default ON):
  OFF → xml.build с прежними капами (50k-stop живой, байт-в-байт):
  test_off_caps_stop_byte_identical; ON → caps=(None,None) → dead-path
  (test_caps_no_longer_stop_on_zone_c_on не находит «hard cap» warning,
  полный окно в flat XML при вмещении). Split delivery отсутствует
  только при OFF (`_cap_legacy_chunks`) / присутствует при ON (без
  потери хвоста).
* `SUMMARY_L2_REVIEW_ENABLED=false` (существующий): single-call L2 →
  Legacy — test_review_off_generator_single_call.
* §8.2 contract: новые env-ключи не в каталоге (F8 CHECK OK, каталог 488;
  не-asap41 тесты с git-scan settings-полями прошли: fields(Settings)
  записи не изменились — ClassVar вне dataclass-полей).

### Prompt-миграция (один «коммит» код+эталон+тесты)

* Канон L1: map v1 — init в summary_prompts.py литералом; эталон канона
  (plans/docs/canon/architecture.md) обновлён байт-идентично; migrate/
  rollback ступени добавлены (FORWARD: PREV_*_R1027_ASAP41 → new canon;
  ROLLBACK: new canon → PREV_*_R1027_ASAP41; юзер-кастом не трогается).
* Канон L2: PREV R1029 (2.58.46) + блок ИСТОЧНИК (новый integer-канон);
  миграции аналогично; Reviewer-канон не мигрирует (внутренний,
  append-блок при переданном source).
* «Старый промпт помечен superseded»: слепки PREV_* сохранены байт-в-байт;
  пин-тесты waves (canon pins) аменжены (двух активных канонов нет).

### Команды и результаты

* Точечные: `pytest tests/test_summary_semantic_map_asap41.py
  tests/test_summary_writer_source_asap41.py
  tests/test_summary_reviewer_source_asap41.py
  tests/test_summary_legacy_source_window_asap41.py
  tests/test_summary_golden_839_asap41.py` — **69 passed** (27+18+12+11+1
  golden).
* Соседи: `pytest -k summary` — **1399 passed, 1 failed → 0 failed после
  аменда allowlist** (execution_graph boundaries; полный web/-падение
  ниже); суммарно (≤последний full run) см. ниже.
* **Полный pytest: 10953 passed, 2 failed (те же 2 known pre-existing
  web/-bounds), ~5:19** (`pytest tests -q --timeout 180`):
  * `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_
    paths_out_of_diff` и `tests/test_unified_image_request_round1026.py::
    TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` — падают
    ТОЛЬКО на `web/`-части (файлы прошлых санкционированных волн,
    вне allowlist'ов; эквивалент волны 2: не тронуты волной 3, воспроизвод-
    ятся на чистом diff; отдельная санкция/фикса вне зоны B/C).
* Wave-2 тесты (45): passed; capacity/ledger пины аменжены честно (map-выход
  L1 и T-4608 partial-success — задокументировано выше, не «молчаливое» изменение).
* F8: `python tools/gen_param_registry_round1025.py --check` → EXIT 0,
  «CHECK OK: реестр 488 == REGISTRY…».
* compile-check всех затронутых `py_compile` — EXIT 0.

### Гигиена

* Новые/изменённые файлы волны 3: UTF-8 без BOM; EOL: LF для новых,
  CRLF-стайл сохранён для pre-existing (settings.py/conftest/чужие тест-стайл);
  канон-файл — байт-идентичность (пин ✓); compile-check EXIT 0.

### Честные остатки / границы волны 3 (на приёмку Reviewer)

1. **Reviewer-канон не мигрирован** (append-блок по наличию source —
   spec не требует миграции внутреннего канона; слепок не создавался).
2. **Иерархический Writer пропускает semantic review** (прецедент paged-L2:
   review на мульти-вызовном пути не применяется; ctx.health=degraded +
   L2_REVIEW_SKIPPED причина writer_hierarchical; evidence-slices reviewer
   работает в fits-ветке).
3. **Reviewer capacity-fits** — предоценка по length-цели (draft-токенов ещё
   нет до вызова); консервативный fail-open → slices; честность — не
   «oversized вслепую».
4. **Minimal map title** — тех-метка («Сегмент N (структурная заготовка)»);
   не LLM-семантика; честный degraded-маркер виден (map_degraded).
5. **2 known pre-existing failures** (web/-bounds) — вне волны 3, см.
   волна 2 evidence §репорт (тот же механизм).
6. **Merge-pass LLM**: если merge-LLM вернул невалидный документ —
   deterministic concat fallback (никогда не выбрасывает абзацы); тест —
   для «detail» ветки coverage покрыт сценариями с валидным merge.
7. **Бюджеты env** (map tokens 6000/hint 160) — developer-deep, Δ каталога
   = 0 (F8 pass; непоявление в каталоге coverage не редактировал
   существующие тесты; штатный F8-CHECK).
8. external verification: новые модули не добавляют зависимостей и сетевых
   протоколов (stdlib + существующий llm-канал/token counter); Context7/
   Exa-проверка не требовалась. Реиспользованные API (repair_capacity_
   overflow, reduce_threads, paged-контракт package.pages, partition_
   lossless, patch-контракт replace_paragraphs, budget ≤6) — без изменений.

MEMORY_DELTA: (оркестратору, волна 3) — зоны B/C реализованы: L1 semantic map v1
(map_degraded по построению; kill-switch SUMMARY_L1_SEMANTIC_MAP_ENABLED;
map-режим активен только в capacity-first ветке, OFF/legacy контуры байт-в-байт
2.58.46); Writer/Reviewer от Full SourceWindow (kill-switches
SUMMARY_WRITER_SOURCE_INPUT_ENABLED / SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED;
FactPackage = derived view — summary_fact_view; иерархический Writer =
per-segment + merge-pass, review-skip не тихо); bounded revision ×2/budget≤6
сохранены; критические пины prompt-миграций (каноны map/источника в эталоне
canon/architecture.md байт-идентичны коду; PREV_*_ASAP41 superseded-слепки для
OFF/rollback). 2 known pre-existing failures — web/-bounds, не волны 3.

---

## Wave 4 — Зона D: T-4612 / T-4613 / T-4614 / T-4615 (03.10.2026)

**Role:** Builder (волна 4: «Supervisor»). База — worktree волн 2–3 (те же
непрокоммиченные файлы в дереве; режим: без коммитов, без деплоя; kill-
switches зон A/B/C остаются in-tree). Спека: spec.md §4 (зона D) +
ADR-1028-8 D5; якоря владельца §22–§30 (22979–23199).

### Файл-манифест волны 4 (для детерминированной ревизии Reviewer)

| Файл | Статус | Якоря |
|---|---|---|
| `services/summary_llm_supervisor.py` | **new** (T-4612/13/14/15) | attempt-потолок ATTEMPT_CEILING_HTTP=4 :72 (PRIMARY/FALLBACK ≤2+≤2, TRANSPORT_MAX_RETRIES=1, RETRY_STATUSES=()); ProviderCapabilities :103; declare_execution_capabilities :108 (честная декларация из реального транспорта); select_execution_mode :134; hard_deadline_seconds :163 (clamp [600,7200]); inactivity_threshold_seconds :170 (clamp [60,900]); _cold_defaults :180 (per mode); _token_bucket :196; record_outcome :223 (оценщик обучается ТОЛЬКО успешными); resolve_attempt_deadline :260 (p95×safety REUSE media_execution паттерна, never-raises); telemetry_snapshot :288; SupervisedCallState :367; evaluate_watchdog :389 (streaming-stall / sync attempt-дедлайн); transport_contract :413; supervisor_enabled :450; _primary_attempt :481; _fallback_attempt :523 (§27 capacity re-plan; oversized-отправка запрещена); _run_with_watchdog :632 (живой поллер); execute_supervised :683; recent_states :1000; make_wrapped :1005 |
| `services/llm_client.py` | *modified* (аддитивно, default None = байт-в-бит) | `_post(..., timeout=, budget_reason_label=)` :665-696 + per-request httpx.Timeout :712-715/:760; supervised rename-точки: fuse-ветка :880-885 (execution_deadline_exceeded), budget-исчерпание :894-899 (retry_time_budget_exhausted); `_post_fallback(..., timeout=)` :912-941; `generate(..., supervised_transport=)` :1032-1040/:1083-1103 (per-call контракт в _post; ВНУТРЕННИЙ fallback-каскад ВЫКЛЮЧЕН для supervised-канала :1103-1109) |
| `services/pipeline_events.py` | *modified* | EV_L1_ACTIVITY/EV_WRITER_ACTIVITY/EV_LLM_SUPERVISOR :47-49; read-side alias в _REASON_MAP :66-70; llm_activity :235-254; llm_supervisor :256-264; __all__ +4 |
| `services/mca_events.py` | *modified* | REASON_CODES +4 (execution_deadline_exceeded/retry_time_budget_exhausted/provider_stalled/fallback_capacity_smaller) :199-203 |
| `services/pipeline_analytics.py` | *modified* | REASONS_RU +4 человеческих описания :137-145 (T-4615: «budget» ≠ денежный balance) |
| `services/summary_l1_clusterizer.py` | *modified* | `_make_llm_call` врезка wrap :1217-1231; `_supervise_call` :1249-1261 (OFF → None = прежний канал; wrap-фейл fail-open с WARN) |
| `services/summary_l2_writer.py` | *modified* | `_make_llm_call(..., operation="writer")` врезка :1093-1103; `_supervise_call` :1122-1135 |
| `services/summary_l2_review.py` | *modified* | `_call_llm(..., operation=)` :615-631; reviewer/revision call-sites :764/:862 — operation-метки («reviewer»/«revision») |
| `services/summary_generator.py` | *modified* | `_supervised_generate` :2751 (operation="legacy"; OFF → прежний канал); точки: `_llm_generate` ×2 :2782/:2797 (retry-once стадийный сохранён как логический бюджет), narrator `_generate` :2888 |
| `config/settings.py` | *modified* | 12 env-only ClassVar зоны D :951-999 (SUPERVISOR_ENABLED default ON; HARD_DEADLINE 3600 clamp на чтении; INACTIVITY 300; COLD_{TTFA,GENERATION}_{SYNC,ASYNC,STREAM}; ADAPTIVE_MIN_SAMPLES 3 / SAFETY 1.5; ASYNC/STREAMING_MODE_ENABLED default OFF — честные слоты); Δ каталога = 0 (F8: реестр 488) |
| `tests/conftest.py` | *modified* | `SUMMARY_LLM_SUPERVISOR_ENABLED` в оба списка изоляции (asap41 → ON; немаркированные → OFF байт-в-бит); EOL CRLF нормализован |
| `tests/test_summary_supervisor_asap41.py` | **new** | 32 теста (см. ниже) |
| `tests/test_summary_deploy_round1026.py` | *modified* (аменд пина) | AST-пин round1026: `_llm_generate`/`_generate_two_call` ИСКЛЮЧЕНЫ из byte-parity списка с NOTE-санкцией ADR-1028-8 D5 (LLM-точки Summary идут через `_supervised_generate`; прецедент — исключение `_run`/`_run_hybrid_l2` самим ASAP-2); прочие 11 функций пина без изменений; `_run_legacy_pipeline` token-пин `_llm_generate` остаётся зелёным |

### Контракты и kill-switch зоны D (spec §4 + §11.1)

* `SUMMARY_LLM_SUPERVISOR_ENABLED` (settings.py:974, default ON; env-only,
  resolves per-call): ON → РОВНО один orchestration-owner для Summary
  (attempt-потолок ≤4 HTTP на логический вызов: 1 primary + ≤1 primary
  transport-retry + ≤1 fallback-provider + ≤1 fallback transport-retry;
  нижний слой только transport — max_retries=1, retry_statuses=();
  внутренний fallback-каскад llm_client выключен supervised-каналом).
  OFF → wrap-врезки вертает None → прежний канал llm_client 2.58.46
  байт-в-бит (бюджеты/каскады/старые reason-строки; тест).
* Логические бюджеты стадий НЕ тронуты: L1 ≤2 (вкл. semantic correction
  retry — каждый логический вызов отдельный supervised attempt-бюджет),
  L2 ≤6 (writer+reviewer+revision по CALL_BUDGET_L2_STAGE), legacy
  retry-once — стадийный логический бюджет. Демонтаж = транспортные
  вложенные циклы (было ≤6 HTTP/вызов; стало ≤4).
* Scope AM-3: не-Summary потребители (Direct/STT/image/embeddings/lore/
  dream) — сигнатуры/поведение байт-в-бит (новые kwarg'и default None;
  test_off_post_keeps_old_reason_strings + полный прогон соседей зелёный).
* Mode A/B — контрактные слоты: SUMMARY_LLM_ASYNC_MODE_ENABLED /
  SUMMARY_LLM_STREAMING_MODE_ENABLED (env-only, default OFF — честная
  база до live-верификации PO-4); режим следует декларации
  (declare_execution_capabilities: реальный транспорт sync-opaque →
  opaque_sync_only=True); «пинговать генерацию» запрещено (no-ping тест).
* Watchdog: unhealthy = нет подтверждённой активности (streaming-ветка
  evaluate_watchdog) / attempt-дедлайн исчерпан (sync — честный
  эквивалент неактивности для opaque-транспорта); adaptive p95×safety
  ТОЛЬКО по успешным длительностям per (provider, model, operation,
  token-bucket); hard fuse — последний рубеж (developer deep env-only).
* T-4615 rename: fuse → `execution_deadline_exceeded`; исчерпание
  попыток → `retry_time_budget_exhausted`; read-side alias в
  pipeline_events.map_reason (старые логи читаются под новыми кодами);
  Analytics REASONS_RU — человеческие описания; не-Summary строки
  llm_client не тронуты (тест байт-в-бит).

### Тесты (tests/test_summary_supervisor_asap41.py — 32, все `@pytest.mark.asap41`)

* T-4612: `test_logical_call_never_exceeds_4_http` (вечный transport-фейл
  → РОВНО 4 HTTP реальным подсчётом httpx.AsyncClient.post, конечный
  LLMTransportError); `test_status_500_no_status_retry_single_fallback`
  (2 HTTP: retry_statuses=() у нижнего слоя); `test_success_first_http`
  (1 HTTP; usage-паритет); `test_transport_contract_of_primary_attempt`
  (max_retries=1 / retry_statuses=() / budget / timeout / supervised-
  метка); `test_generate_supervised_disables_internal_cascade`
  (каскад запрещён); `test_fallback_fits_same_whole_window_task`
  (§27/§28: 2+1=3 HTTP, payload инвариантен);
  `test_fallback_smaller_capacity_no_oversized_send` (oversized НЕ
  отправляется); OFF-parity (make_wrapped→None; старые reason-строки).
* T-4613: честная декларация sync; флаги без верифицированного адаптера
  → Mode C; режим следует декларации (слоты A/B); no-ping (ровно 1 HTTP
  /chat/completions).
* T-4614: cold default; adaptive p95 (400s-образцы → дедлайн ≥ 600s —
  живая генерация 622s-класса не убивается wall-clock); клампы
  [600,7200]/[60,900]; ветки evaluate_watchdog (stream-stall/elapsed-
  живость/sync-дедлайн); `test_stall_detection_finite_fallback`
  (stalled → cancel → finite fallback); `test_hard_fuse_trip_reason`
  (fuse → LLMTimeoutError); бакеты телеметрии (p50/p95/timeouts/ttfa/
  queue); timeout/failure НЕ обучают оценщик; события R17-чистые.
* T-4615: supervised fuse → execution_deadline_exceeded (caplog, старый
  код отсутствует); исчерпание попыток → retry_time_budget_exhausted
  (финальное событие Supervisor'а); read-side alias map_reason;
  REASON_CODES/REASONS_RU; новые события не содержат старых кодов;
  не-Summary старые строки (байт-в-бит).

### Команды и результаты

* Точечные: `pytest tests/test_summary_supervisor_asap41.py` —
  **32 passed**.
* Соседи: `pytest -k "summary or llm_client or llm"` — **1796 passed,
  0 failed** (после двух честных амендов: AST-пин round1026
  `_llm_generate`/`_generate_two_call` — NOTE-санкция ADR-1028-8 D5;
  фикс чтения настроек supervisor'а при `importlib.reload(config.settings)`
  в тест-хелпере — единый import-time binding).
* **Полный pytest: 10985 passed, 2 failed (те же 2 known pre-existing
  web/-bounds), ~5:35** (`pytest tests -q --timeout 180`): 10953
  (базис волн 2–3) + 32 (волна 4) = 10985; известные падения —
  `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_
  out_of_diff` и `test_unified_image_request_round1026.py::..._
  test_forbidden_paths_out_of_diff_vs_baseline` (web/-часть вне зоны D,
  воспроизводятся на чистой базе — см. репорт волн 2/3).
* F8-чек: `python tools/gen_param_registry_round1025.py --check` →
  **EXIT=0** («CHECK OK: реестр 488 == REGISTRY…») — Δ каталога = 0
  (все 12 ключей зоны D — env-only ClassVar вне каталога, spec §8.1/D9).
* Гигиена: BOM=0 / UTF-8 во всех затронутых файлах; EOL: LF для новых
  модулей, CRLF сохранён/нормализован для pre-existing
  (llm_client/settings/conftest/deploy-test); compile-check EXIT=0.

### Честные остатки / границы волны 4 (на приёмку Reviewer)

1. **Mode A/B — контрактные слоты** (честная база): реальные async-job/
   streaming-прогоны требуют верифицированных провайдер-адаптеров и
   платных live-вызовов — PENDING OWNER (PO-4); сейчас любые флаги
   дают Mode C с честными декларациями (не «stream ✓»).
2. **`http_attempts` в SupervisedCallState — верхняя граница ноги** (≤2):
   точное число HTTP внутри `_post` supervisor'у не возвращается;
   детерминированный подсчёт закреплён transport-тестом (4/2/3-сценарии).
3. **`budget_exhausted`-ветка `_post` (attempt не стартовал по времени)** —
   defensive/гонка-эквивалент c asyncio.timeout: детерминированно в тесте
   недостижима, rename-контракт закреплён alias'ом + supervised-финалом
   (retry_time_budget_exhausted); строка для не-Summary сохранена байт-в-бит.
4. **AST-пин round1026 аменджен** (исключены `_llm_generate`/
   `_generate_two_call`) — санкция ADR-1028-8 D5 задокументирована NOTE в
   тесте; транспортная семантика пина продолжена
   tests/test_summary_supervisor_asap41.py.
5. **`tokens/sec` в телеметрии** — записывается из usage, когда провайдер
   вернул usage (сейчас usage не возвращается глобальным каналом generate
   → поле остаётся в схеме record_outcome, наполняется когда появится);
   honest: нет выдуманной оценки.
6. **Watchdog для L1 correction retry / stage-цепочек** — каждая
   логическая попытка supervised независимо; кросс-стадийный wall-clock
   бюджет НЕ введён (spec: единого глобального timeout-числа нет).
7. **`SUMMARY_LLM_COLD_*` значения по умолчанию** (ttfa 120/gen 900 sync)
   — developer deep env-only, Δ каталога = 0; прод-подстройка — по
   телеметрии/прогонам владельца (T-4634).
8. external verification: новых зависимостей/сетевых протоколов нет
   (stdlib + существующий llm_client/httpx); Context7/Exa-проверка не
   требовалась — все задействованные API — контурные контракты проекта.

MEMORY_DELTA: (оркестратору, волна 4) — зона D реализована: новый модуль
services/summary_llm_supervisor.py — единый orchestration-owner LLM-вызовов
Summary-пайплайна (attempt-потолок ≤4 HTTP/логический вызов закреплён тестом
реальным подсчётом; внутренний llm_client fallback-каскад выключен
supervised-каналом через per-call `generate(supervised_transport=)`;
provider-fallback с capacity re-plan — oversized-отправка запрещена);
adaptive watchdog (ttfa/queue/generation per provider/model/operation/
token-bucket ТОЛЬКО по успешным; cold defaults per mode; clamp
[600,7200] hard fuse / [60,900] inactivity; живой длинный запрос не
убивается wall-clock) — AMEND ADR-1024-6 для Summary-пути; честная база
Mode C, слоты Mode A/B default OFF до live-верификации (PO-4); rename
total_budget_exceeded → execution_deadline_exceeded /
retry_time_budget_exhausted в supervised-эмиccии + read-side alias +
Analytics RU; kill-switch SUMMARY_LLM_SUPERVISOR_ENABLED (OFF = байт-в-бит
2.58.46). 2 known pre-existing failures — web/-bounds, не волны 4.

---

## Waves 5+6 — Зоны E/F: T-4616 / T-4617 / T-4618 / T-4619 / T-4620 (03.10.2026)

**Role:** Builder (волны 5–6: «Durability + Cover/Style»).

### Recovery-нотка (честно)

Две предыдущие Builder-сессии по волнам 5/6 оборвались (provider/runtime),
не завершив врезку. Эта сессия — RECOVERY: **ничего не сброшено**, валидные
наработки сохранены и продолжены. Найденные обрывы прошлой сессии:

1. `services/cover_style_jobs.py`: ссылка `SLOT_SOURCE_GLOBAL_STYLE` без
   импорта (NameError в `run_style_job` при не-настроенном слоте — падали
   12 тестов wave B) и удалённый импорт `resolve_style_slot` (NameError в
   `profile_diagnostics`) — **доведено**: добавлены импорты SLOT_SOURCE_*
   (4 источника лестницы) + restore `resolve_style_slot` (диагностика §41
   — статический чек-лист профиля, бит-в-байт 2.58.46; наследование в
   карточке — зона G/T-4623).
2. T-4617: content-hash барьер `bot_output_ledger` в `_publication_gate`
   отсутствовал (был только correlation-reconcile) — **доделано** в этой
   сессии + 2 теста (skip + контрпример).
3. Изоляция теста: `_set_settings` в wave-f тестах патчил только
   `config.settings.settings` — при `importlib.reload(config.settings)`
   в чужих тестах (прецедент conftest `_system2_flags_off_by_default`,
   tests/conftest.py:28-30) патч не долетал до инстанса
   `cover_style_pipeline.settings` → 5 order-dependent падений под
   `-k summary` — **исправлено** (патч класса + обоих инстансов,
   прецедент test_embedding_control_plane_asap4).

### Файл-манифест волн 5/6 (для детерминированной ревизии Reviewer)

| Файл | Статус | Якоря |
|---|---|---|
| `services/summary_run_store.py` | **new** (T-4616/17) | state machine/VALID_TRANSITIONS/state_rank :47-108; publication-статусы :111-116; run_durable_enabled :119; create_run :139; set_state+rank-guard :149; get_run :180; record_stage :187; mark_publishing :202; complete/fail_publication :230/:240; last_completed_stage :248; stage_history :256; terminal_state_for_run :263; purge_expired_runs :277 (TTL-гейт: только DONE/DEGRADED/FAILED) |
| `services/database.py` | *modified* (T-4616/17) | `_SUMMARY_RUNS_DDL` + индексы (state/chat) + `_SUMMARY_RUN_STAGES_DDL` + индекс (run_id,id); миграции `_migrate_summary_runs_v24`/`_migrate_summary_run_stages_v24` (`_migrate_*`, L-MCA14-3; прямые commit только здесь — MCA-01 allowlist 149→155); runtime: create_summary_run :2843 / update_summary_run_state :2866 / set_summary_run_publication :2903 (published никогда не перезаписывается) / get_summary_run :2940 / get_active_summary_run_for_chat :2954 / get_bot_output_by_correlation :2973 / record_summary_run_stage :2990 / list_summary_run_stages :3026 / last_completed_summary_run_stage :3051 / purge_expired_summary_runs :3072 (DELETE стадий+окон только терминальных run'ов) |
| `services/summary_generator.py` | *modified* (T-4616/17/18) | resume-врезка `_run` :509-591 (SUMMARY_RESUME; окно докатываемого run'а — только durable snapshot, перечитка запрещена); `_durable_run_create` :769; `_durable_mark` :779; `_durable_stage_result` :796; `_durable_run_finish` :809 (finally _run :700); `_publication_gate` :834 (PUBLISHING до send → published-skip → correlation-reconcile → content-hash барьер → retry); checkpoints SOURCE_READY :741-753 / STRUCTURING :1855 / STRUCTURE_READY :1890 / WRITING :2067 / TEXT_READY :1548,:2225 / BASE_COVER :2637 / STYLE_EDIT :2708; gate-врезки: plain :2450, rich :2754, rich-without-cover :2993; `_record_published_output` checkpoint :2381-2395 |
| `services/cover_style_pipeline.py` | *modified* (T-4619/20) | slot-source-enum лестницы §35 :138-167 (global_style/profile_connection/connections_default/global_image); `default_edit_connection` :170; `_capability_supports_edit` :190 (FALSE блокирует, UNKNOWN нет); `_edit_capabilities_for` :199 (registry resolve_capabilities_auto); `resolve_style_slot_inherited` :210-266 (legs 1-2 байт-в-байт → 3a/3c → честный not_configured); `style_global_default_enabled` :49 (kill-switch); `resolve_source`-поле базового слота :35-39 |
| `services/cover_style_jobs.py` | *modified* (T-4619/20) | импорты SLOT_SOURCE_* :42-45 + resolve_style_slot :47 (RECOVERY); COVER_STYLE_RESOLVE :32; SAFE_LOG_FIELDS +resolve_source :42; api-key наследованного global-image слота → keys.image_api_key :72-85/:1155-1166; run_style_job: resolve через `resolve_style_slot_inherited` :1140-1148, meta.resolve_source :1176, COVER_STYLE_RESOLVE ДО COVER_STYLE_START :1177-1187, caps по ФИНАЛЬНОМУ слоту :1195-1202 (единый registry §36, без хардкодов), check_edit_allowed gate :1204-1210 |
| `config/settings.py` | *modified* | +2 env-only ClassVar: `SUMMARY_RUN_DURABLE_ENABLED` (волна 5), `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` (волна 6) — Δ каталога = 0 |
| `tests/conftest.py` | *modified* | SUMMARY_RUN_DURABLE_ENABLED / SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED в оба списка изоляции (asap41 → ON; немаркированные → OFF байт-в-байт) |
| `tests/test_summary_run_store_asap41.py` | **new** | 19 тестов (T-4616) |
| `tests/test_summary_cover_style_wave_f_asap41.py` | **new** | 16 тестов (T-4617 fixture/T-4618/T-4619/T-4620) |
| `tests/test_cover_style_wave_b_asap4.py` | *modified* | моки resolve_style_slot → resolve_style_slot_inherited (async, pg-параметр) — контракт лестницы §35 |
| `tests/test_cover_styles_contract_asap32.py` | *modified* | статик-гейт: jobs резолвит через resolve_style_slot_inherited + pg=obj0 |
| `tests/test_mca01_tx_task_supervisor_round1027.py` | *modified* | allowlist database.py 149→155 (6 commit — только `_migrate_summary_runs_v24`/`_migrate_summary_run_stages_v24`) |
| `tests/test_tool_coordinator_round1026.py` | *modified* | allowlist + services/summary_run_store.py (конвенция волн 2/3) |

### DDL-факт (итог v24)

* SQLite `user_version 23→24`, три таблицы: `summary_source_windows`
  (волна 2) + `summary_runs` (run_id PK stable, chat_id, state, manual,
  window_from/to, source_ref, publication_status, publication_result_ref,
  pipeline_health, created_at, updated_at; индексы state/chat) +
  `summary_run_stages` (id PK autoincrement, run_id, stage, status,
  started_at, last_activity_at, finished_at, attempt, provider, model,
  result_ref, reason_code — append-only §50.54: единственный UPDATE
  surface у таблицы ОТСУТСТВУЕТ (scan-тест); DELETE — только TTL-purge
  терминальных run'ов). Повторный прогон — no-op (тест). PostgreSQL —
  no-op (scan-тест: asyncpg/PG-DDL в зоне E отсутствуют; cover_style_*
  PG-таблицы не тронуты).

### Kill-switches зон E/F (spec §11.1, env-only, default ON)

* `SUMMARY_RUN_DURABLE_ENABLED` — OFF → runs/stages/publication не
  пишутся (0 записей — тест), gate → None (байт-в-бит), resume отключён.
* `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` — OFF → ровно
  `resolve_style_slot` (байт-в-байт 2.58.46 — тест).
* Resolves per-call, никогда не бросают (паттерн capacity_guard_enabled).

### Контракты зон E/F (spec §5/§6)

* Resume §21: рестарт не пересоздаёт run — докат того же стабильного
  run_id; окно — только из immutable snapshot (не перечитка дрейфующей
  истории); rank-guard не отматывает checkpoint.
* Идемпотентность публикации (DoD 21): PUBLISHING фиксируется ДО send;
  published → skip; stuck-publishing → ledger-факт по correlation →
  skip; content-hash барьер (точное совпадение plain-рендера) → skip;
  иначе retry-лег. Единый gate во всех каналах (plain/rich/rich-no-cover)
  — двойной финальный месседж невозможен.
* Лестница наследования §35 (Medved Press fix): «По умолчанию» +
  пустой глобальный слот → Connections default (3a) → models.image_*
  (3c — тот же слот, что сгенерировал base cover) → честный
  not_configured; capability image_edit=FALSE блокирует наследование,
  UNKNOWN не блокирует (честная попытка → fail-soft ladder §37).

### Команды и результаты

* Точечные волны 5/6: `pytest tests/test_summary_run_store_asap41.py
  tests/test_summary_cover_style_wave_f_asap41.py` — **35 passed**
  (19+16).
* Соседи: `pytest -k summary` — **1465 passed, 0 failed** (после фикса
  изоляции `_set_settings`); `pytest -k "cover or bot_output or database
  or mca14 or run_store or style"` — **702 passed, 0 failed**;
  test_cover_style_wave_b + contract + wave_f + extra_cover —
  **72 passed**.
* **Полный pytest: 11020 passed, 2 failed (те же 2 known pre-existing
  web/-bounds), ~5:31** (`pytest tests -q --timeout 180`): 10985 (базис
  волн 2–4) + 35 (волны 5/6) = 11020. Падения —
  `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_
  out_of_diff` и `test_unified_image_request_round1026.py::..._
  test_forbidden_paths_out_of_diff_vs_baseline` — падают ТОЛЬКО на
  `web/api/analytics.py`, `web/api/cover_styles.py`,
  `web/static/polygon-background.js`, `web/static/telegram-init.js`
  (файлы прошлых санкционированных волн вне allowlist'ов; волны 5/6
  web/ не трогали; воспроизводятся на чистом diff).
* F8-чек: `python tools/gen_param_registry_round1025.py --check` →
  **EXIT=0** («CHECK OK: реестр 488 == REGISTRY…») — Δ каталога = 0
  (2 новых ключа — env-only ClassVar, spec §8.1/D9).
* Гигиена: BOM=0 во всех файлах волн 5/6; EOL: LF для новых модулей,
  CRLF сохранён для pre-existing (settings/conftest/mca01); исключение —
  test_tool_coordinator_round1026.py (UTF-8 BOM — состояние прошлых
  волн; baseline 2.58.46 был UTF-16LE; не перекодировался).
  compile-check EXIT=0.

### Честные остатки / границы волн 5/6 (на приёмку Reviewer)

1. **Stage-level resume skip** (T-4617): докат пере-прогоняет LLM-стадии
   по immutable snapshot с тем же run_id (дубликат публикации исключён
   gate'ом); переиспользование map/draft из result_ref требует persist'а
   артефактов — отдельное решение (зона G/I).
2. **Per-попытка last_activity_at-тикер стадий** — сейчас пишутся факты
   завершения; живой тикер — с Inspector-ридером зоны G (T-4621).
3. **profile_diagnostics (§41)** — остался на базовом resolver'е
   (бит-в-байт); наследование в чек-листе — зона G (T-4623).
4. **§46-ladder 5 фикстур** — консолидация в T-4627 (зона I, волна 7);
   волны 5/6 закрепляют gate/чекпоинты/лестницу наследования + регресс
   существующих ladder-тестов.
5. **Browser-Verification (spec, REQUIRED)** — привязан к зоне G
   (T-4622/T-4623, Inspector-карточки); волны 5/6 user-visible UI не
   меняют (новые карточки появятся в волне 7) — browser-прогон не
   выполнялся, маркер остаётся на T-4622/T-4623.
6. **2 known pre-existing failures** (web/-bounds) — вне волн 5/6, см.
   репорт волн 2/3/4.
7. external verification: новых зависимостей/сетевых протоколов нет
   (stdlib + существующие контурные API: bot_output_ledger
   find_bot_output_by_text — REUSE без изменений сигнатуры;
   image_capabilities.resolve_capabilities_auto — существующий);
   Context7/Exa-проверка не требовалась.

MEMORY_DELTA: (оркестратору, волны 5/6) — зоны E/F реализованы: durable
SummaryRun — SQLite v24 `summary_runs` + `summary_run_stages` (append-only
§50.54, state machine §20 с rank-guard'ом; kill-switch
SUMMARY_RUN_DURABLE_ENABLED; PG no-op); resume после рестарта = докат того
же стабильного run_id с окном из immutable snapshot; идемпотентность
публикации — единый _publication_gate во всех каналах доставки (PUBLISHING
до send + published-skip + correlation-reconcile + content-hash барьер
bot_output_ledger) — fixture «kill в PUBLISHING → ровно одна публикация»;
Medved Press fix — лестница наследования Style-слота §35
(resolve_style_slot_inherited; leg 3a Connections default → 3c
models.image_*; capability registry по финальному слоту; событие
COVER_STYLE_RESOLVE с resolve_source; kill-switch
SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED); MCA-01 allowlist database.py 149→155
(DDL `_migrate_*`-паттерн). 2 known pre-existing failures — web/-bounds.

---

## Wave 7 — Зона G: T-4621 / T-4622 / T-4623 / T-4624 (03.10.2026)

**Role:** Builder (волна 7: «Run Inspector / observability»). База — worktree
волн 2–6 (непрокоммиченные файлы в дереве; режим: без коммитов, без деплоя).
Режим сессии: RECOVERY — предыдущая Builder-сессия оборвалась (пустой ответ);
валидные наработки сохранены и доведены, ничего не сброшено.

### Recovery-аудит (честно)

Наследованные частичные правки по wave-7 файлам проверены против spec §7
(G.1–G.3): `services/pipeline_analytics.py`, `web/app.js`, `web/index.html`,
`tests/js/asap41_zone_g_inspector_test.js`,
`tests/test_summary_inspector_zone_g_asap41.py`,
`tools/ui_asap41_zone_g_e2e.py` (+ артефакт
`tools/_ui_asap41_zone_g.json`). Находка обрыва: предыдущая сессия успела
записать e2e-артефакт до гибели; вся зона G-реализация оказалась
консистентной, доделка — верификация + честная фиксация статусов задач.
Сторонние untracked-артефакты (`playwright-mcp/`, `extra_images/`,
`node_modules/`, `package*.json`) не тронуты (не мой diff).

### Файл-манифест волны 7 (для детерминированной ревизии Reviewer)

| Файл | Статус | Якоря |
|---|---|---|
| `services/pipeline_analytics.py` | *modified* (T-4621/22/23/24) | `_capacity_card` :345 (карточка «КОНТЕКСТ МОДЕЛИ» + replan-счётчик); `_liveness_cards` :448 (liveness: события + durable stage-rows); `_cover_style_card` :556 (карточка стиля); `_coverage_breakdown` :654 (раздельные оси); врезки `build_run_view` :992/:1003; `_INSPECTOR_EVENTS` +12 имён :1307; `collect_run` stage-ридер :1366-1391 (fail-open); `REASONS_RU` +~30 человеческих описаний :135-190 (capacity/mode/map-degraded/style-лестница); `_safe_reason_code` :265 |
| `web/app.js` | *modified* | computed `pipelineCoverageRows` :2930 (строки, state ok/warn/failed); `pipelineCapacityCard` :2995 (числа с пробелами, mode/reason/window_source); `pipelineLivenessRows` :3022; `pipelineCoverStyleCard` :3038 (styled/base_fallback/no_cover + точная причина) |
| `web/index.html` | *modified* | блок «Покрытие источника — по стадиям» :3123; #pipeline-capacity-card :3137; #pipeline-liveness-card :3152; #pipeline-cover-style-card :3226 (существующая first-class coverage-карточка R4-E не редактирована) |
| `services/pipeline_events.py` | *modified* (аддитивно) | НОВЫЕ эмиттеры `SUMMARY_TEXT_READY` :420/:55 + `SUMMARY_REVISION_RESULT` :429/:56 (врезки: summary_generator.py:1571/:2255, summary_l2_review.py:908); существующие имена не переименованы (контрактный тест) |
| `tests/test_summary_inspector_zone_g_asap41.py` | **new** | 26 тестов (см. ниже), все @pytest.mark.asap41 |
| `tests/js/asap41_zone_g_inspector_test.js` | **new** | JS unit-сьют карточек (реальная логика app.js + разметка index.html) → ZONE-G-INSPECTOR-OK |
| `tools/ui_asap41_zone_g_e2e.py` | **new** (Browser-Verification REQUIRED) | Playwright e2e: fixture-run через РЕАЛЬНЫЙ mca-17a транспорт на temp-SQLite → desktop 1280x800 + mobile 390x844 |
| `tools/_ui_asap41_zone_g.json` | **new** | e2e-артефакт (failures: 0) |

### Контракты зоны G (spec §7 G.1–G.3)

* **T-4621 (§38, DoD 28):** coverage_breakdown — раздельные оси
  `source` (839/839·100%) / `l1` (input_total + input_mode
  WHOLE_WINDOW·1 запрос | segments + result: failed|ok + map_degraded) /
  `writer` / `final` / `overflow` (segments N + messages_covered/total +
  lossless). L1 failure НЕ смешивается с source 100% в единый успех
  (R6-G-001) — отдельная строка state='failed'. Данные — structured
  state (usage_json + in-memory снапшот; guard-скан «не
  open/read_text/glob/subprocess»).
* **T-4622 (§39/§40, DoD 29):** capacity-карточка из
  SUMMARY_CAPACITY_RESOLVED/SUMMARY_EXECUTION_MODE_SELECTED:
  provider/model/effective window/serialized input/output reserve/mode +
  reason_ru + window_source по цепочке §5 + `replans` (= len(caps)-1 —
  re-plan события T-4605). Liveness: на каждой LLM stage — execution
  mode (честная декларация: sync не показывается как stream — тест),
  provider fallback (outcome=fallback/fallback_target), last_activity,
  «жива (активность подтверждена)/завершена/ждёт/стадия упала».
* **T-4623 (§41, DoD 30):** cover_style-карточка из COVER_* событий:
  base_cover_ok, selected_style, style_provider/model, capability_edit
  (edit_unsupported → «✕»), reference_assets (только при реальном
  reference_count), style_edit_ok, result = styled|base_fallback|
  no_cover, fallback_reason — ТОЧНЫЙ код (не generic style_failed,
  D6.3), resolve_source по лестнице §35 (global_style/profile_connection/
  connections_default/global_image — реальные SLOT_SOURCE-идентификаторы).
* **T-4624 (§42/§43):** один run_id сквозной; аддитивные имена;
  существующие не переименованы (EV_*-контрактный тест); новые эмиттеры
  TEXT_READY/REVISION_RESULT врезаны в реальный пайплайн;
  `_INSPECTOR_EVENTS` расширен на 12 имён (drill-down читает новые
  события). Per-attempt last_activity тикер: `summary_run_stages` —
  append-only по попытке (retry = НОВАЯ строка с last_activity_at,
  database.py:2990-3019); collect_run подмешивает stage-строки в
  liveness (fail-open); живая стадия тикает из SUMMARY_L1_ACTIVITY/
  SUMMARY_WRITER_ACTIVITY. «L1_TIMEOUT» — нового admin-ключа НЕТ (F8:
  реестр 488, EXIT=0). R17: fixture-скан (api_key/sk-/bytes/тексты
  сообщений) чист.

### Тесты

* `tests/test_summary_inspector_zone_g_asap41.py` — **26 passed**
  (`pytest tests/test_summary_inspector_zone_g_asap41.py`):
  T-4621: l1_failed_source_full_are_separate_axes (ОБЯЗАТЕЛЬНЫЙ fixture
  §38), l1_ok_same_fixture, map_degraded из L1_STAGE.counts,
  overflow_segments_and_messages_covered, writer_input_coverage_axis,
  no_log_parsing_in_path (guard).
  T-4622: capacity card fields из structured state / no event → no card /
  replan counter / reason-коды §5; liveness: sync ≠ stream (честная база
  T-4613), provider_fallback visible, running alive-ticker, waiting.
  T-4623: styled card / точная причина не generic / base_failed →
  no_cover / resolve_source ladder §35 / no events → no card / reason
  семьи fallback.
  T-4624: полный перечень на fixture-run (реальный mca-17a emit_stage
  транспорт), overflow-run добавляет РОВНО три сегментных, имена не
  переименованы, R17-скан чист, integration surface.
* `node tests/js/asap41_zone_g_inspector_test.js` —
  **ZONE-G-INSPECTOR-OK, EXIT=0** (4 computed'а как свойства, раздельные
  строки + overflow warn, числа/причины capacity, честный sync, styled/
  base_fallback/no_cover + точная причина, разметка index.html, R17-скан
  разметки).

### Команды и результаты

* Точечные pytest: **26 passed** (см. выше).
* **Полный pytest: 11046 passed, 2 failed (те же 2 known pre-existing
  web/-bounds), ~5:29** (`pytest tests -q --timeout 180`): 11020 (базис
  волн 2–6) + 26 (волна 7) = 11046. Падения —
  `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_
  paths_out_of_diff` и `tests/test_unified_image_request_round1026.py::
  TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` — падают
  ТОЛЬКО на web/-файлах прошлых санкционированных волн (web/api/
  analytics.py, web/api/cover_styles.py, web/static/polygon-background.js,
  web/static/telegram-init.js), воспроизводятся на чистом diff; волна 7
  их allowlist'ы не расширяла.
* JS-сьют: **54/54 файлов passed, 0 failed** (node по всем tests/js/*.js,
  включая новый asap41_zone_g_inspector_test.js).
* F8-чек: `python tools/gen_param_registry_round1025.py --check` →
  **EXIT=0** («CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто,
  TSV/map идемпотентны») — Δ каталога = 0 (зона G не добавляет ключей).
* **Browser-verification (Playwright, spec REQUIRED):
  `tools/ui_asap41_zone_g_e2e.py` → EXIT=0, failures: 0**:
  desktop 1280x800 И mobile 390x844 — все карточки рендерятся из
  fixture-run через реальный mca-17a транспорт (temp-SQLite; прод-БД не
  загрязняется): coverage_card + раздельная ось «не выполнено» рядом с
  source 839/100%, capacity_card (mode WHOLE_WINDOW + причина),
  liveness_card (L1 + Writer), cover_style_card (styled + Базовая
  обложка), run_id сквозной виден. 0 новых console/pageerror (один
  известный baseline-дефект чужой фичи `execMetricsRows` отфильтрован,
  документирован в round1030 evidence).
  Скриншоты: plans/archive/asap-4-1-durable-whole-window-summary-round1031/
  evidence/asap41_zone_g_desktop.png (578 KB) /
  asap41_zone_g_mobile.png (130 KB); артефакт проверки —
  tools/_ui_asap41_zone_g.json (payload_sanity: coverage_breakdown/
  capacity/cover_style присутствуют, mode=WHOLE_WINDOW, l1_result=
  failed, styled=styled — no-false-quality: run published, health
  честно degraded).
* Гигиена: все затронутые файлы волны 7 — UTF-8 без BOM, LF
  (pipeline_analytics/app.js/index.html/оба теста/e2e-скрипт); артефакт
  _ui_asap41_zone_g.json — сгенерирован (CRLF-конвенция json.dump).
  compile-check затронутых py-файлов в составе полного pytest — EXIT 0.

### Честные остатки / границы волны 7 (на приёмку Reviewer)

1. **reference_assets в e2e-фикстуре отсутствует** (честно: в fixture
   COVER_STYLE_SUCCEEDED не передан reference_count → карточка не
   рисует выдумку; presence-путь закреплён unit-тестом
   reference_assets=2). На e2e поле «Reference assets» не рендерится —
   корректное честное отсутствие, не дефект.
2. **Liveness живого run'а**: тикер живой стадии идёт из
   SUMMARY_*_ACTIVITY событий (in-flight) + durable stage-строки
   (append-only по попытке); in-runtime heartbeat-UPDATE в
   summary_run_stages отсутствует принципиально (append-only по
   ADR-1028-8 D6; живость = события, завершённость = stage-rows).
3. **collect_run stage-ридер fail-open**: ошибка чтения durable
   stage-истории деградирует liveness до event-only витрины (не ломает
   drill-down) — отмечен pragma no cover.
4. **known console baseline**: `execMetricsRows is not a function` —
   чужой фича-дефект (round1030), не волна 7; отфильтрован и
   задокументирован.
5. **2 known pre-existing failures** (web/-bounds) — вне волны 7, см.
   репорты волн 2/3/4/5/6.
6. external verification: новых зависимостей/сетевых протоколов нет
   (существующий Vue-фронт, pipeline_events-транспорт; playwright —
   dev-tool вне прод-кода); Context7/Exa-проверка не требовалась — все
   задействованные API — контурные контракты проекта.

MEMORY_DELTA: (оркестратору, волна 7) — зона G реализована: Inspector
читает ТОЛЬКО structured state (usage_json событий + durable
summary_run_stages, никакого парсинга логов); coverage_breakdown —
раздельные оси source/l1(input+result)/writer/final/overflow (L1 failed
не маскируется source 100%); карточки capacity (WHOLE_WINDOW/
CAPACITY_OVERFLOW + reason_ru + window_source §5 + replan-счётчик),
liveness (честный sync, provider fallback, жива/завершена/ждёт) и cover
style (styled|base_fallback|no_cover + точная причина, resolve_source
лестницы §35); новые события SUMMARY_TEXT_READY/SUMMARY_REVISION_RESULT
врезаны в пайплайн, _INSPECTOR_EVENTS +12 имён; per-attempt
last_activity тикер = append-only stage-rows (retry = новая строка).
Browser-verification выполнена (desktop+mobile, failures: 0). 2 known
pre-existing failures — web/-bounds, не волна 7.

---

## Wave 8 — Блок I (тесты): T-4625 / T-4626 / T-4627 / T-4628 (03.10.2026)

**Role:** Builder (волна 8: «тестовая консолидация»). База — worktree
волн 2–7 (11046/2 known; те же непрокоммиченные файлы в дереве; режим:
без коммитов, без деплоя). Спека: spec §9 (§44–§47) + §11.1; якоря
владельца §44–§47, §48-модель. Директива Orchestrator Wave-8: T-4625
golden whole-window / T-4626 Supervisor full-runs / T-4627 ladder
консолидация / T-4628 OFF-parity матрица; оригинальный tasks.md T-4628
(§47 attribution) закрыт дополнительно (обе задачи уложены).

### Файл-манифест волны 8 (новые тест-файлы; prod-код НЕ изменён)

| Файл | Статус | Содержание |
|---|---|---|
| `tests/test_summary_wave8_golden_asap41.py` | **new** | 13 тестов: G1–G5 golden-сценарии (§44/§9) + 8 param-фикстур §47 attribution |
| `tests/test_summary_wave8_supervisor_runs_asap41.py` | **new** | 6 full-run сценариев Supervisor (§27/§30/§45/§29) |
| `tests/test_summary_wave8_ladder_matrix_asap41.py` | **new** | 5 §46-веток единой матрицы (M1–M5: публикуется/coverage/health) |
| `tests/test_summary_wave8_off_parity_asap41.py` | **new** | 5 тестов: комбинированный OFF 9 kill-switches + per-зоны проверки |

Prod-исходники волны 8 не трогались (diff ограничен tests/). Изменений
DDL/каталога нет (F8 CHECK OK, реестр 488).

### Сценарии и главные assert'ы (иначе — не заглушки)

* **T-4625 golden (§44/§9):** G1 — 839 synthetic → WHOLE_WINDOW, РОВНО 1
  L1-вызов («СООБЩЕНИЯ ЧАТА»-шов), plan snapshot mode=WHOLE_WINDOW,
  segments=None, coverage 100%, публикация, ctx.status ok; G2 — nano-gpt
  (registry 131072 → WHOLE_WINDOW) → локальная 32k (runtime props →
  CAPACITY_OVERFLOW), `_cache_key` сменился, авто re-plan, coverage
  инвариант, window/семантика не меняются (§28); G3 — L1 мусор ×2 →
  Writer-контент `ИСТОЧНИК…structure source yourself` + ВСЕ tg_message_id,
  `_run_legacy_pipeline` NOT awaited (§48 Run 1 запрет), L1_STAGE
  status=failed рядом с ctx.source_coverage=100 (R6-G-001); G4 — Legacy
  от `lfw.load_legacy_rows` snapshot → один вызов, XML ≥560
  `<message`, каждый id присутствует, «hard cap» NOT in caplog
  (dead-path), health ok; G5 — CAPACITY_OVERFLOW (manual cap 260, 24
  строки, ≥2 сегмента) с ВСЕМИ невалидными ответами → deterministic
  minimal maps → coverage 100% по ledger (не 0/24), Writer получает
  SEMANTIC MAP + Сегмент-заготовки, published, map-режим честный.
* **T-4626 Supervisor full-runs (§27/§30/§45/§29):** F1 — primary down
  → supervisor fallback (re-plan fits) → 3 HTTP ≤ ATTEMPT_CEILING_HTTP(4),
  контент из fallback, no-ping; F2 — все уровни down → РОВНО 4 HTTP
  (потолок), финальное событие retry_time_budget_exhausted, старых
  причин нет; F3 — ПОЛНЫЙ run_l1 на реальном LLMClient-транспорте
  (httpx-моки): primary ×2 down → fallback map-ответ → L1 usable,
  3 HTTP ≤ 4, coverage 100%; F4 — stalled (attempt-дедлайн 0.05s) →
  cancel → finite fallback, ≤4 HTTP; F5 — hard fuse 0.05s →
  LLMTimeoutError + reason execution_deadline_exceeded; F6 — record
  timeout ×5 НЕ меняет adaptive дедлайн (до == после), успешные
  400s-образцы дают ≥600s (§50: живая генерация не убивается
  wall-clock), бакет/operation изоляция (cold default), stamps: samples=4,
  timeouts=5 (reliability-signal, не обучение).
* **T-4627 ladder matrix (§46, R4-D-029):** M1 — L1 fail → Writer от
  полного окна, публикуется, coverage 100%, L1_STAGE failed; M2 —
  L2 unusable → `_legacy_fallback("l2_unusable")` (LEVEL-3),
  `ctx.fallback=="legacy"`, health **degraded** (не стирается
  публикацией — §50.53), coverage 100% до падения; M3 — style fail
  (REASON_STYLE_FAILED через шов `_maybe_apply_cover_style`, prod-
  механика jobs закреплена волной 6) → rich с БАЗОВОЙ обложкой
  (media=[MEDIA:…]), cover_status ok, health ok (текст не тронут, §34);
  M4 — image API raise → Rich БЕЗ медиа/или plain, cover_status
  unavailable, health ok, текст опубликован; M5 — send_rich raise →
  plain-канал с ТОТ ЖЕ документ (TITLE + оба абзаца вербатим), ctx.
  publish_channel=text/status ok, coverage 100%. Все ветки — реальный контур
  `_run_hybrid_l2`/`_publish_rich_document`/`_publish_plain_document`
  (моки только LLM/сеть/telegram-layer).
* **T-4628 OFF-parity (§47/§11.1):** (a) §47-матрица — 8 сценариев,
  Writer И Reviewer получают вербатим text каждого сообщения сценария
  (два Мити/reply-chain/forward+source/цитата/шутка vs факт/числа 1 234
  567 ₽/дата 31.12.2026/две редакции) — атрибуция против оригинала,
  без срезов; (b) combined-OFF — все 9 kill-switches §11.1 OFF
  (патч по всем Settings-классам) на РЕАЛЬНОМ прогоне `_run_hybrid_l2`
  с temp-SQLite: 0 строк в summary_source_windows/summary_runs/
  summary_run_stages; capacity snapshot None; L1 — контракт §95-v2
  (v2-ответ принят, map-схема не видна: ни SEMANTIC MAP, ни topics в
  пакетах); Writer без «ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА» (FactPackage-
  центричный); каждая llm.generate без supervised_transport; отдельный
  legacy-тест: окна обрезаются капами 560→<560 (2.58.46-поведение),
  style-резолвер `resolve_style_slot_inherited`[:-] ==
  `resolve_style_slot` (байт-в-байт), `sup.make_wrapped` → None; (c)
  поимённый prod-дефолт: каждый из 9 флагов ON в Settings; never-
  raises per-call резолвы (супервизор/стиль/legacy/durable/ssw/
  writer-source) на мусорных env; zone-A точечный: при OFF
  `_establish_source_window` не вызывает store (spy) и таблица пуста.

### Известные волне-8 решения честности

* **cfg-патч reload-безопасности:** флаги патчатся по «type(cs.settings)/
  type(sl1.settings)/type(sg.settings)» по всем классам (reload'ы
  settings в соседних тестах меняют класс инстанса; прецедент conftest
  `_asap4_flags_off_by_default`) — found по первому -k прогону (G3
  rich-ветка при cover OFF), закреплено.
* **Заглушки второго контура не используются:** LLM-моки — head-routing
  на канон-маркерах (СООБЩЕНИЯ ЧАТА/ИСТОЧНИК/ПРОВЕРЬ СТАТЬЮ), нет
  «второго контура» тестов; ladder-маты — только LLM/сеть/telegram
  слои (send_text с 3 позиционными (bot, chat_id, text) — учтено).
* **Durable OFF в ladder-фикстурах** (детерминизм матрицы) —
  публикация gate → None; идемпотентность публикации закреплена fixture
  зоны E (T-4617) и остаётся.
* **Style-fail шов** — `_maybe_apply_cover_style` (генератор) для
  M3; jobs-уровень (run_style_job/edit_image/provider) закреплён
  тестами волны 6 (not_configured/edit_unsupported/registry). Честно:
  сквозной style-edit e2e-прогон в матрице опирается на оба шва.
* **§47 attribution** — input-уровень (полный оригинал у Writer/Reviewer
  вербатим); LLM-качество атрибуции — прод-приёмка §48 Run 1 (PO-1).

### Команды и результаты

* Точечные: `pytest tests/test_summary_wave8_golden_asap41.py
  tests/test_summary_wave8_supervisor_runs_asap41.py
  tests/test_summary_wave8_ladder_matrix_asap41.py
  tests/test_summary_wave8_off_parity_asap41.py` — **21 passed**; после
  добавления §47-матрицы: golden **13 passed** (5+8) → суммарно **29 new**.
* Соседи: `pytest -k "summary or llm"` — **1878 passed, 0 failed**.
* **Полный pytest: 11075 passed, 2 failed (те же 2 known pre-existing
  web/-bounds), ~5:42** (`pytest tests -v --timeout 120`): 11046 (базис
  волн 2–7) + 29 (волна 8) = 11075. Падения —
  `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_
  out_of_diff` и `test_unified_image_request_round1026.py::…_vs_baseline`
  (web/-файлы прошлых санкционированных волн; волна 8 не трогала;
  воспроизводятся на чистом diff).
* F8-чек: `python tools/gen_param_registry_round1025.py --check` →
  **EXIT=0** («CHECK OK: реестр 488 == REGISTRY…») — Δ каталога = 0.
* Гигиена: все 4 новых файла — UTF-8 без BOM, LF, py_compile EXIT=0;
  prod-код и каталог не изменены (diff волны 8 ограничен tests/).
* Deprecation-warning полного прогона — известный (starlette/httpx
  baseline, вне эпика).

### Синхронизация с определением T-4628 (факт для Reviewer)

**tasks.md T-4628 (оригинал) = §47 attribution (8 fixture-сценариев);**
директива Orchestrator на Wave-8 поставила T-4628 = «OFF-parity всей
матрицы». Обе уложены в волне 8: §47-матрица (8 сценариев в golden-
файле) + OFF-parity матрица (отдельный файл, 5 тестов). Spec §9 внушает
OFF-parity как сквозную зонную обязанность — теперь она консолидирована
единым комбинированным OFF-прогоном поимённо 9 kill-switches.

MEMORY_DELTA: (оркестратору, волна 8) — тестовый блок I закрыт: волна 8
= 29 новых тестов (11075 total / 2 known web/-bounds) без изменений
prod-кода; консолидация — golden 839/switch/L1-fail→Writer/Legacy-100%/
minimal-map (T-4625), Supervisor full-runs с РЕАЛЬНЫМ подсчётом HTTP и
attempt-потолком ≤4 (T-4626), единая §46-ladder матрица
«публикуется/coverage/health» (T-4627), комбинированный OFF 9 kill-
switches §11.1 → бит-в-бит 2.58.46 + §47 attribution 8 сценариев (T-4628,
двойное покрытие: Original tasks.md + директива Orchestrator).
F8 EXIT=0, гигиена BOM/EOL/compile чисто. Reviewer gate T-4629 —
следующий.

## Пост-gate фикс [M-ASAP41-1] (Builder, 03.10.2026, doc-only)

Директива Orchestrator: точечный фикс единственного блокера финального
gate T-4629 (review.md Blocking findings [M-ASAP41-1], Medium,
requirement-blocking, doc-only). Коммита нет (R18-режим).

### Что изменено (4 файла + 1 новый тест)

1. `services/param_catalog.py` (якоря: :735-736 LLM_TIMEOUT, :745-746
   LLM_TOTAL_BUDGET — совпадают с review.md): к описаниям обоих ключей
   добавлена пометка spec §8.1 «Не управляет фоновым Саммари (Summary) —
   длительность Саммари определяет супервизор исполнения» (формулировка
   по корректирующему действию ревью; spec-маркер «не управляет
   Summary» присутствует дословно). Только строки `description`;
   значения/типы/группы/settings_field не тронуты.
2. `tests/test_summary_param_catalog_annotation_asap41.py` (NEW):
   5 тестов TestSpec81SummaryAnnotation — маркер у обоих ключей;
   пояснение «длительность … определяет супервизор»; негативный sweep
   «пометки нет у остальных 486 ключей» (охват = ровно 2 ключа §8.1);
   doc-only инвариант type/group/settings_field = как было.
3. `plans/docs/param-registry-round1025.tsv` — перегенерирован (полный
   свип F8 emit); содержательный дифф = ровно 2 строки (llm_timeout,
   llm_total_budget) с новой аннотацией, счётчики 488/77 те же.
4. `plans/docs/param-registry-round1025.meta.md` — перегенерирован:
   APP_VERSION 2.58.46, HEAD 60f1c7c, счётчики REGISTRY 488 /
   GROUPS 105 / _TAB_BY_GROUP 103 / TAB_RULES 21 идемпотентны.
5. `tests/fixtures/round1025/f8_baseline.json` — осознанное обновление
   по историческому прецеденту (round1026/ASAP-2.1/extra-cover):
   `sha256(services/param_catalog.py)` f1001fb0…→ec2d9dc7…, к
   `superseded_by` добавлена запись ASAP-4.1 (doc-only, REGISTRY 488
   без роста, app_version остаётся историческим 2.58.15). Минимальный
   дифф: 2 строки. Замороженные тесты f8_registry против новой базы —
   зелёные.

### Команды и результаты (собственные прогоны Builder)

* Новый тест: `pytest tests/test_summary_param_catalog_annotation_asap41.py`
  → **5 passed**.
* Целевые: `pytest tests/test_summary_param_catalog_annotation_asap41.py
  tests/test_round1025_f8_registry.py tests/test_param_catalog.py -q`
  → **68 passed, 0 failed** (frozen invariants против обновлённой
  fixture-базы).
* Сосед: `pytest tests/test_settings_helpers.py -q` → **48 passed**;
  rg по tests/web «меньше сбоев на медленных»/«быстрее сдаётся» —
  точный пин старого текста отсутствует нигде.
* F8 полный свип: `python tools/gen_param_registry_round1025.py` —
  EMIT EXIT=0 (488 строк); `… --check` → **EXIT=0** («CHECK OK: реестр
  488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны»).
* Гигиена: `py_compile param_catalog.py + новый тест + F8-инструмент`
  → EXIT=0; fixture JSON — UTF-8 без BOM, LF, trailing newline сохранён.

### Границы (честно)

* Полный pytest после этого точечного фикса осознанно НЕ перезапускался
  (вне директивы Orchestrator: достаточно «точечного теста каталога»;
  базис эпика 11074–11077 с известными 2 web/-bounds + флапом
  betterstack не зависит от строк описаний каталога; вердикт review.md
  — «ревью дельты: F8 --check EXIT=0 + точечные тесты» выполнен).
* Runtime-поведение не тронуто (изменены только строки описаний;
  семантика LLM_* для не-Summary AM-3 boundary байт-в-бит).

MEMORY_DELTA: (оркестратору, фикс [M-ASAP41-1]) — spec §8.1 аннотация
«не управляет Summary» добавлена в описания LLM_TIMEOUT/LLM_TOTAL_BUDGET
(param_catalog.py:735/745), F8-артефакты перегенерированы (emit+check
EXIT=0, Δ каталога=0: 488/105/103/21/77 без изменений), fixture
f8_baseline.json обновлён осознанно (sha256 ec2d9dc7…, app_version
остаётся 2.58.15), тест-контракт — файл
test_summary_param_catalog_annotation_asap41.py (5 тестов, охват ровно
2 ключа). 68+48 тестов зелёные, py_compile EXIT=0. Doc-only, коммита
нет (R18).
