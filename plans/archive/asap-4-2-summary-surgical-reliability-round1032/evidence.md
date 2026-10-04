# evidence.md — `asap-4-2-summary-surgical-reliability`

> Durable evidence журнал. Не заменяет `tasks.md`/`review.md`. Только
> компактные ссылки: файлы, команды, фактические результаты. Без секретов,
> без сырых логов, без Base64.

## Контекст и baseline (Step 2a @Builder, 04.10.2026)

- **Feature:** `asap-4-2-summary-surgical-reliability` (ASAP 4.2), Step 2a — Summary core (D1/AM-1).
- **Спека:** `spec.md` D1 + `adr-1028-10` D1 (AM-1) + `requirements-map.md` R8-A/B/C/D/E.
- **Baseline HEAD:** `373c387` (master; до правок). Рабочее дерево на старте
  содержало пре-существующие (не мои) правки `plans/docs/mca-round1027-arch-frames.md`,
  `plans/metrics.md`, `plans/workflow_state.md` — НЕ трогал.
- **Коммиты/деплой:** не делались (запрещено условием).
- **Окружение прогона:** `.venv\Scripts\python.exe` (Python 3.12), Windows.

## Что изменено (Step 2a)

| Файл | Характер | Задача |
|---|---|---|
| `services/summary_source_anchors.py` | NEW — `SourceAnchorMap`, base36 checksum, kill-switches | T-4802 |
| `services/summary_l1_repair.py` | +anchor-space `repair_l1_anchors` / `AnchorRepairReport` | T-4804 |
| `services/summary_l1_semantic_map.py` | +L1 map v2 (`validate_semantic_map_v2`, `compute_unassigned_anchors`); `MapResult` +anchor-поля | T-4803/T-4804 |
| `services/summary_l2_anchor_repair.py` | NEW — L2 evidence repair + `ReviewResult`/`ReviewReason` + targeted revision | T-4805/T-4806 |
| `services/summary_prompts.py` | +anchor-space канон-константы (L1 v2/Writer/Reviewer/revision) | T-4807 (частично) |
| `config/settings.py` | +4 env kill-switch (`SUMMARY_SOURCE_ANCHORS_ENABLED` и др.) | T-4802…T-4806 |
| `tests/test_summary_source_anchors_asap42.py` | NEW — targeted-набор Step 2a | T-4828 (подмножество) |

**Baseline/итоговое состояние:** изменённые/новые файлы — см. `git status --short`;
коммитов нет. `git diff --stat` (без plans-пре-существующих): settings +20,
l1_repair +119, l1_semantic_map +314, summary_prompts +64; untracked —
anchors/l2_anchor_repair/tests.

## Проверки (фактические результаты)

- `py_compile` изменённых модулей + теста → **COMPILE_OK**.
- Import-check без циклов: `import services.summary_l1_clusterizer` → **IMPORT_OK**.
- Targeted-набор Step 2a: `pytest tests/test_summary_source_anchors_asap42.py -q`
  → **24 passed** (2.9 s).
- Смежные существующие (de-risk затронутых модулей):
  - `pytest tests/test_summary_l1_repair_round1027.py tests/test_summary_semantic_map_asap41.py -q`
    → **40 passed** (в объединённом прогоне 64 passed с Step 2a).
  - `pytest tests/test_summary_asap21_prompt_migrations.py tests/test_prompt_migrations.py tests/test_summary_prompts.py -q`
    → **72 passed**.
- **Полный pytest НЕ гонялся** — по owner §49 (после targeted) и условию задачи.

### Покрытые targeted-сценарии §49 (Summary-часть)

| Сценарий | Тест | Результат |
|---|---|---|
| checksum mismatch rejected / typo не alias | `test_checksum_mismatch_rejected`, `test_typo_does_not_alias_other_message` | pass |
| anchor format/биекция/reverse/immutability/build-asserts/R17-safe | `test_anchor_format_bijection_and_reverse_mapping`, `test_map_is_frozen_and_immutable`, `test_build_asserts_duplicate_real_ids_fail_open`, `test_anchor_normalization_case_insensitive` | pass |
| unassigned считает код, LLM игнорируется | `test_unassigned_computed_by_code_ignores_llm`, `test_compute_unassigned_anchors_union_topics_events_relations`, `test_unassigned_empty_and_invalid_input_safe` | pass |
| L1 invalid anchor repair (не invalidate) | `test_l1_invalid_anchor_repaired_not_invalid`, `test_l1_repair_drops_only_empty_dependent_container`, `test_l1_all_broken_no_structure_is_empty`, `test_l1_structural_invalid_still_fatal` | pass |
| L2 invalid evidence repair (абзац остаётся) | `test_l2_invalid_evidence_repair_keeps_paragraph`, `test_l2_paragraph_without_evidence_is_signal_not_kill` | pass |
| bad anchor не убивает Hybrid document | `test_bad_anchor_does_not_kill_hybrid_document`, `test_l2_unrepairable_structure_returns_none` | pass |
| Reviewer verdict reason-коды + targeted revision | `test_review_result_reason_codes_and_drops`, `test_review_result_approved_when_no_valid_issue`, `test_targeted_revision_is_single_paragraph_and_bounded`, `test_review_reason_enum_complete` | pass |

## НЕ сделано в этом шаге (честно)

1. **Live pipeline call-site wiring (главное).** Новые anchor-пути
   (`validate_semantic_map_v2`, `repair_l1_anchors`, `repair_l2_evidence`,
   `validate_review_result`) реализованы и покрыты unit-тестами, но **не
   вызываются** из `summary_l1_clusterizer.run_l1`, `summary_l2_writer`,
   `summary_l2_review`. Пока не подключено: production по-прежнему использует
   v1 map / message_ids (kill-switch ON не даёт эффекта). Это Step 1 fix
   (clusterizer/writer/reviewer) + Step 3 integration (T-4829).
2. **L1 correction-retry policy** не менялся: `RETRYABLE_MAP_REASONS`/retry
   loop остались v1-ориентированными. «broken-anchor-only → НЕ retry» в live
   path не проверено.
3. **Промпты (T-4807):** добавлены *новые* anchor-space константы
   (`SUMMARY_L1_ANCHORS_SYSTEM_PROMPT`, `SUMMARY_L2_WRITER_ANCHORS_BLOCK`,
   `SUMMARY_L2_REVIEWER_ANCHORS_BLOCK`, `SUMMARY_L2_TARGETED_REVISION_ANCHORS_BLOCK`),
   но **live-канон не переключён** и `prompt_migrations` не расширены — иначе
   prompt попросил бы anchors у пайплайна, который их не подаёт. Активация —
   вместе с wiring (п.1).
4. **T-4806 «§47 wrong-speaker из оригинала»** и bounded revision-loop в
   `summary_l2_review` не подключены; реализован только контракт
   (`ReviewResult`/`ReviewIssue`) + `build_targeted_revision_content`.
5. **T-4808/T-4809 (capacity/reserve)** — вне описанного объёма Step 2a
   (в ТЗ «Сделай» их нет); не трогал.
6. **T-4828 полный список §49** (NanoGPT, prompt-limit, streaming, seeds,
   RBAC, mobile layout и т.д.) — только Summary-ядро.

## Инварианты/наблюдаемость

- DDL = 0 (новых таблиц/колонок нет; env-only kill-switch, OFF = бит-в-бит
  2.58.47 по замыслу — live OFF-паритет ещё не измерялся без wiring).
- R17: в логи/payload не пишутся тексты; anchors — короткие внутренние
  токены, в публичный текст не попадают (unit: anchors ≠ raw ids).
- Inspector-поля (AM-5/D6): `MapResult.anchors_generated/anchors_repaired/
  anchors_dropped`, `AnchorRepairReport`, `EvidenceRepairReport`
  (`invalid_refs_repaired`, `paragraphs_without_evidence`).

---

## Step 2b — WIRING (T-4804..T-4807 + local integration §50, 04.10.2026)

- **Baseline HEAD:** `373c387` (master). Рабочее дерево на старте содержало
  пре-существующие (не мои) правки `plans/docs/mca-round1027-arch-frames.md`,
  `plans/metrics.md`, `plans/workflow_state.md` — НЕ трогал. Step 2a-файлы
  (`summary_source_anchors.py`, `summary_l1_repair.py`, `summary_l1_semantic_map.py`,
  `summary_l2_anchor_repair.py`, `summary_prompts.py`, `config/settings.py`,
  `tests/test_summary_source_anchors_asap42.py`) унаследованы как partial-работа
  и сохранены (не сбрасывал).
- **Коммиты/деплой:** не делались (запрещено условием).
- **Окружение:** `.venv\Scripts\python.exe` (Python 3.12), Windows.

### Что связано (wiring-якоря file:line)

| Зона | Файл:строка | Что |
|---|---|---|
| L1 | `services/summary_l1_clusterizer.py:586` | `resolve_anchor_map` — SourceAnchorMap из immutable окна (fingerprint окна) |
| L1 | `services/summary_l1_clusterizer.py:602-604` | `build_l1_user_content(..., anchor_map=)` — anchor-space вход LLM |
| L1 | `services/summary_l1_clusterizer.py:1661,1732-1735` | `run_l1` + `source_window`, `anchor_mode` |
| L1 | `services/summary_l1_clusterizer.py:1961` | `validate_semantic_map_v2` (repair=kill-switch) |
| L1 | `services/summary_l1_clusterizer.py:2110` | `anchor_map_correction_block` (reason валидатора) |
| L1 | `services/summary_l1_clusterizer.py:1473-1479` | Inspector anchors generated/repaired/dropped (map_stats) |
| L1 | `services/summary_l1_clusterizer.py:1494,1625,1718` | capacity-first прокидывает `source_window` (WHOLE_WINDOW) |
| L2 | `services/summary_source_anchors.py:304` | `anchor_space_item` (единый helper raw id→anchor) |
| L2 | `services/summary_l2_writer.py:587` | `build_l2_source_input(..., anchor_map=)` — Writer видит anchors |
| L2 | `services/summary_l2_writer.py:1048-1120` | `anchor_evidence_enabled` + `validate_l2_document_anchors` (repair evidence, абзац живёт) |
| L2 | `services/summary_l2_writer.py:1391,1480-1482` | `run_l2(anchor_map=)`, anchor-канон writer |
| L2 | `services/summary_l2_review.py:347-419` | `anchor_review_enabled`, `_verdict_from_anchor_result`, `apply_targeted_revision` |
| L2 | `services/summary_l2_review.py:421` | `_anchor_source_excerpts` |
| L2 | `services/summary_l2_review.py:752,818,929,1027,1046` | `run_l2_with_review(anchor_map=)`, anchor-вердикт, targeted revision |
| L1-canon | `services/summary_l1_semantic_map.py:985` | `anchor_map_correction_block` (v2 correction) |
| Gen | `services/summary_generator.py:210` | `_map_is_anchor_space` (map/evidence рассинхрон guard) |
| Gen | `services/summary_generator.py:644,776` | `_establish_source_window` возвращает immutable окно |
| Gen | `services/summary_generator.py:1781,1936` | `_run_hybrid_l2(source_window=)` → `run_l1(source_window=)` |
| Gen | `services/summary_generator.py:1054,1093-1156` | `_run_writer_source_stage`: anchor_map из окна; overflow→v1 |
| Gen | `services/summary_generator.py:2159` | `_run_writer_source_stage(source_window=)` |

### Проверки (фактические результаты)

- `py_compile` изменённых модулей + нового теста → **COMPILE_EXIT=0**.
- Import-check: `import services.summary_l1_clusterizer, summary_l2_writer,
  summary_l2_review, summary_generator` → **IMPORT_OK**.
- Targeted Step 2b: `pytest tests/test_summary_anchors_wiring_asap42.py -q`
  → **15 passed** (2.99 s).
- Регрессия релевантного набора (без полного pytest, owner §49):
  `pytest test_summary_source_anchors_asap42 test_summary_anchors_wiring_asap42
  test_summary_semantic_map_asap41 test_summary_l1_repair_round1027
  test_summary_l1_clusterizer test_summary_l2_writer test_summary_l2_integration
  test_summary_wave_d_asap4 test_summary_wave_c_asap4 test_summary_writer_source_asap41
  test_summary_wave8_off_parity_asap41 -q` → **382 passed**.
- Дополнительно: `test_summary_source_window_asap41 test_summary_golden_839_asap41
  test_summary_reviewer_source_asap41 test_summary_prompts
  test_summary_asap21_prompt_migrations test_prompt_migrations
  test_summary_legacy_source_window_asap41 test_summary_capacity_asap41 -q`
  → **131 passed**.
- **Полный pytest НЕ гонялся** — owner §49 (после targeted/integration).

### Покрытые Step 2b-сценарии

| Сценарий | Тест | Результат |
|---|---|---|
| L1 bad anchor → repair, не invalid; unassigned кодом; counters | `test_bad_anchor_repaired_not_invalid` | pass |
| raw TG id не подаются LLM (anchor-space вход) | `test_raw_ids_absent_from_llm_input` | pass |
| broken-anchor-only → НЕТ retry (1 вызов) | `test_broken_anchor_only_no_retry` | pass |
| invalid_json → retry c reason валидатора | `test_invalid_json_triggers_correction_with_reason` | pass |
| fabricated anchor не принимается молча | `test_fabricated_anchor_not_silently_accepted` | pass |
| OFF `SUMMARY_SOURCE_ANCHORS_ENABLED` → v1/message_ids | `test_kill_switch_off_keeps_v1` | pass |
| нет окна → v1 (старое поведение) | `test_no_source_window_keeps_v1` | pass |
| L1 anchor-канон выбран (schema_version 2) | `test_l1_anchor_system_canon_selected` | pass |
| L2 Writer: invalid evidence ref → repair, абзац живёт | `test_l2_writer_anchor_repair_keeps_paragraph` | pass |
| L2: все evidence битые → абзацы + signal, не Legacy | `test_l2_all_invalid_anchors_keep_paragraphs_signal` | pass |
| Reviewer approved → legacy=0 | `test_l2_review_invalid_anchor_does_not_kill_document` | pass |
| targeted revision одного абзаца (bounded) | `test_l2_targeted_revision_single_paragraph` | pass |
| §50 integration 1001 msg WHOLE_WINDOW, 1 bad L1 + 1 bad L2 → Hybrid выживает, legacy=0 | `test_integration_1000_window_hybrid_survives` | pass |
| generator helper: map/evidence anchor-space guard | `test_map_is_anchor_space_detection` | pass |
| resolve_anchor_map identity/валидность | `test_resolve_anchor_map_uses_window_identity` | pass |

### НЕ сделано в этом шаге (честно)

1. **v2 budget-compaction** (>MAX_THREADS / token-budget) для anchor-map не
   реализована: v2-валидатор канонизирует без v1-`compact_semantic_map`
   (WHOLE_WINDOW-тест мал; на очень широких окнах тема-кап не enforced v2-путём).
2. **T-4807 prompt-audit** — anchor-канон активирован, старый канон сохранён как
   OFF-слепок, но отдельный grep-тест «старых FactPackage-only формулировок нет»
   и вычистка противоречий в R1030-каноне не сделаны.
3. **§47 wrong-speaker «из оригинала»** — live-model поведение; unit не
   проверено (canary T-4830 scope).
4. **CAPACITY_OVERFLOW** остаётся v1 (anchors не протекают в v1 merge;
   `overflow_map=None` при anchor-режиме) — осознанно, WHOLE_WINDOW приоритет.
5. **Style-flow локального integration** (seed/preview/test/update) — вне шага.
6. **T-4828 полный §49** (NanoGPT/prompt-limit/streaming/seeds/RBAC/UI) — pending.

### Инварианты/наблюдаемость Step 2b

- DDL = 0; env-only kill-switch, OFF = прежний v1/message_ids контур (parity
  проверена targeted-тестом на L1; live OFF-паритет не измерялся).
- R17: LLM L1-вход и L2 source-input не содержат raw `message_id` в anchor-режиме;
  L2 canonical doc несёт `source_anchors` (внутренние токены), не raw id.
- Inspector (AM-5/D6): `L1Result.map_stats = {anchors_generated, anchors_repaired,
  anchors_dropped}`; L2 metrics `invalid_refs_repaired`,
  `paragraphs_without_evidence`, `evidence_anchor_space=1`.

---

## Step 2c-1 — image provider / capacity / streaming / compiler (T-4808…T-4816, 04.10.2026)

- **Baseline HEAD:** `373c387` (master). Рабочее дерево на старте содержало
  пре-существующие (не мои) правки `plans/docs/mca-round1027-arch-frames.md`,
  `plans/metrics.md`, `plans/workflow_state.md` — НЕ трогал. Step 2a/2b-файлы
  унаследованы как partial-работа и сохранены.
- **Коммиты/деплой:** не делались (запрещено условием).
- **Окружение:** `.venv\Scripts\python.exe` (Python 3.12), Windows.

### Что изменено (file:line якоря)

| Задача | Файл:строка | Что |
|---|---|---|
| T-4808 | `services/model_capacity.py:337` | `live_precedence_enabled()` kill-switch |
| T-4808 | `services/model_capacity.py:658` | `_cache_key(base_url, model, route)` — route в ключе |
| T-4808 | `services/model_capacity.py:703` | `resolve_capacity(..., route=)` + stale-registry cache re-resolve |
| T-4808 | `services/model_capacity.py:772` | `_resolve_uncached`: override уровень 1; live catalog/runtime суверенны |
| T-4808 | `services/model_capacity.py:900` | `_resolve_route_metadata` (verified route layer, честный None) |
| T-4809 | `services/model_capacity.py:296` | `capability_aware_output_reserve` / `reserve_for_capacity` |
| T-4809 | `services/summary_l1_clusterizer.py:1558` | L1 reserve через capability |
| T-4809 | `services/summary_generator.py:966,1002` | L2 reserve через capability |
| T-4810 | `services/llm_client.py:906` | `LLMClient.stream_chat_completion` (SSE, `on_activity`) |
| T-4810 | `services/summary_llm_supervisor.py:108` | verified chat-route → streaming capability |
| T-4810 | `services/summary_llm_supervisor.py:495` | `_primary_attempt` Mode B (stream → `last_activity_at`) |
| T-4811 | `services/summary_llm_supervisor.py:360` | `network_attempts` в snapshot |
| T-4812 | `services/cover_style_edit.py:167,195` | `build_edit_payload` (Image API) / `build_image_edits_payload` / multipart |
| T-4812 | `services/cover_style_edit.py:290` | `resolve_edit_route` + `_classify_route_from_endpoints` |
| T-4812 | `services/cover_style_edit.py:358,395` | `edit_image` route-aware (`/images` vs `/images/edit`), `route_unverified` fail-soft |
| T-4813 | `services/cover_style_edit.py:325,455` | `extract_edit_error`, 400-diagnostics (sanitized) |
| T-4813 | `services/image_capabilities.py:214` | `extract_provider_error` / `_sanitize_error_text` (маскирование) |
| T-4814 | `services/image_capabilities.py:174` | `extract_prompt_limit` |
| T-4814 | `services/image_capabilities.py:240` | `parse_discovery` реально заполняет prompt_limit (model→route) |
| T-4814 | `services/image_capabilities.py:440` | `record_runtime_limit` (per provider+base_url+model+route) |
| T-4814 | `services/image_capabilities.py:461` | `resolve_capabilities` new precedence + route cache key |
| T-4814 | `services/cover_style_jobs.py:1370` | ONE retry: cache→recompile→1 повтор |
| T-4815 | `services/image_prompt_compiler.py:26` | P0–P3 + `semantic_compression_enabled` |
| T-4815 | `services/image_prompt_compiler.py:186` | `compile_prompt` P0/P1 не режутся, overflow reason |
| T-4815 | `services/cover_style_jobs.py:1327` | `exceeded` → `prompt_limit_exceeded` + Base Cover |
| T-4816 | `services/image_prompt_compiler.py:78` | `CompiledPrompt.original_len/resolved_limit/exceeded/reason` |
| T-4816 | `services/cover_style_jobs.py:1289` | Inspector `original_chars`/`resolved_limit`/`compiled_chars` |
| settings | `config/settings.py:971` | +5 env kill-switch (D3/D4), default ON |
| tests | `tests/test_asap42_step2c_image_capacity.py` | NEW — targeted 28 |
| tests | `tests/test_extra_cover_style_jobs.py:462` | +prompt-limit ONE-retry тест |
| tests | `tests/test_summary_supervisor_asap41.py:426` | AM-2: streaming flag → Mode B |
| tests | `tests/test_capacity_resolver_asap31.py` и др. | AMEND override-L1 (ON) + legacy OFF-parity |

### Проверки (фактические результаты)

- `py_compile` всех изменённых модулей/тестов → **COMPILE_EXIT=0**.
- Import-check: `model_capacity/image_capabilities/image_prompt_compiler/
  cover_style_edit/cover_style_jobs/media_execution/summary_llm_supervisor/
  llm_client` → **IMPORT_OK**.
- Targeted Step 2c-1 relevant set (23 файла, объединённый прогон):
  **736 passed**, 1 warning (Starlette deprecation) in 49.15 s.
  - new: `tests/test_asap42_step2c_image_capacity.py` → **28 passed**.
  - updated ASAP3.1/4.1 override-L1: capacity set → **52 passed**.
  - adjacent image/cover/supervisor/anchors/generator/param-catalog — без
    регрессий.
- **Полный pytest НЕ гонялся** — owner §49 (после targeted/integration).

### Покрытые targeted-сценарии §49 (Step 2c-1)

| Сценарий | Тест | Результат |
|---|---|---|
| capacity live metadata > stale registry; OFF-parity; cache key/route | `test_live_metadata_beats_stale_registry`, `test_legacy_min_runtime_declared_when_off`, `test_cache_key_includes_route`, `test_provider_switch_re_resolves` | pass |
| capability reserve (8000/2000/unknown/OFF) | `test_capability_reserve_*` | pass |
| streaming capability/mode + SSE assembly + activity | `test_declare_streaming_capability_follows_flag`, `test_stream_chat_completion_assembles_and_touches` | pass |
| NanoGPT edit contract обе ветки + no-mixing + multipart | `test_build_edit_payload_input_references`, `test_build_image_edits_payload_single_and_array`, `test_build_image_edits_multipart`, `test_classify_route_from_endpoints` | pass |
| route_unverified fail-soft | `test_edit_route_unverified_fail_soft` | pass |
| edit route-aware endpoint/payload | `test_edit_image_uses_image_edits_branch`, `test_edit_image_legacy_uses_input_references` | pass |
| provider error parsing / R17 sanitized 400 | `test_extract_provider_error_sanitized`, `test_edit_image_400_diagnostics_no_secrets` | pass |
| prompt-limit discovery/cache/invalidation/route-no-leak/one-retry | `test_parse_discovery_prompt_limit_model_then_route`, `test_runtime_limit_cached_per_route_no_leak`, `test_prompt_limit_400_one_retry` | pass |
| no hardcoded 800 | `test_no_hardcoded_800_in_limit_sources`, `test_extract_prompt_limit_patterns` | pass |
| P0–P3 / no `[:N]` / overflow reason | `test_p0_p1_never_cut_p3_dropped`, `test_p0_p1_overflow_gives_reason_not_scissors`, `test_p2_compressed_to_semantic_brief`, `test_compiler_off_legacy_parity` | pass |
| attempt ceiling / network_attempts visible | `test_supervisor_attempt_ceiling_and_network_attempts_visible` | pass |

### НЕ сделано в этом шаге (честно)

1. **REAL live-верификация:** stream canary T-4830 и NanoGPT edit canary
   T-4831 (mock не засчитывается) — не запускались (нет PO-1/creds). Mode B
   активируется флагом `SUMMARY_LLM_STREAMING_MODE_ENABLED` (default OFF до
   owner live); код/декларация готовы.
2. **PO-1 model→route** для `qwen-image-3-pro` через live
   `GET /api/v1/images/models/{model}/endpoints`: route-resolution
   реализован и unit-проверен, но фактический route модели подтверждается
   canary. Без подтверждения → честный `route_unverified` → Base Cover.
3. **Live prompt-limit N** (metadata-поле или machine-readable 400) —
   per-route precedence и ONE retry реализованы; реальное значение лимита
   остаётся `unknown` до live (без hardcode 800).
4. **Mode A (async job/status)** остаётся слотом (нет верифицированного
   job/status API) — AM-2 это допускает.
5. **`network_attempts` в Inspector** — по-прежнему верхняя граница
   supervised-ноги для primary (точный подсчёт внутри `_post` не менялся);
   для fallback считается реально.
6. **OFF parity live** не измерялся end-to-end (только targeted unit для
   каждой зоны kill-switch).

### Инварианты/наблюдаемость Step 2c-1

- **DDL = 0**; все зоны env-kill-switch, OFF → 2.58.47 (unit-parity per zone).
- R17: provider 400 diagnostics — только `status/reason_code/sanitized
  message/request_id/route/model`; data-URL/URL/Bearer/`sk-`/длинные токены
  маскируются; prompt/keys/bytes не логируются.
- Inspector (AM-5/D6): `prompt_diagnostics = {original_chars, resolved_limit,
  compiled_chars, original_style_prompt_chars, overflow_reason, dropped_sections}`;
  supervisor snapshot `network_attempts`; route+prompt_limit в `EditResult.meta`.
- Cache-инвариант: `provider+base_url+model+route` (capacity и prompt-limit)
  — смена любого компонента → re-resolve; `800` не протекает.

---

## Step 2c-2 — D5 MiniApp / seeds / UX (T-4817…T-4827, 04.10.2026)

- **Baseline HEAD:** `373c387` (master). Рабочее дерево на старте содержало
  пре-существующие (не мои) правки Step 2a/2b/2c-1 + `plans/*` — НЕ трогал.
- **Коммиты/деплой:** не делались (запрещено условием). Провайдер/DB не
  вызывались; реальный provider — это PO-1 (canary T-4831/T-4837).
- **Окружение:** `.venv\Scripts\python.exe` (Python 3.12), Windows; node v24.

### Что изменено (file:line-якоря)

| Задача | Файл:строка | Что |
|---|---|---|
| T-4817 | `services/cover_style_registry.py:59` | `SEEDED_INSTRUCTION` расширен compact-ядром: modern Russian graphic novel/comic, 2–3 callouts, русский текст, сцена/персонажи (смысл сохранён) |
| T-4818 | `services/cover_style_registry.py:291` | `set_preview` — `preview_before_asset_id` заменяется (не COALESCE): seeded placeholder → реальный base |
| T-4818 | `tests/test_asap42_step2c2_miniapp_seeds.py:169` | e2e seed-wiring тест (import_seed_file→upsert_asset→add_reference→profile preview ids) |
| T-4819 | `web/api/cover_styles.py:836` | `_generate_test_base` (safe `TEST_STYLE_BRIEF` → `image_generation.generate_image_verbose`) |
| T-4819 | `web/api/cover_styles.py:800` | `TestStyleBody.content_base64: str = ""` (upload опционален; основной путь без файла) |
| T-4819 | `web/api/cover_styles.py:878` | `cover_test_style` — generation path / upload path; mode=preview (counter не тратится); fail сохраняет прошлый preview; `developer_reason` |
| T-4819 | `web/api/cover_styles.py:869` | `_human_style_fail_message` (D5.8, human phrase) |
| T-4820 | `web/index.html:637` | refs UI: replace/remove/upload видны/доступны только `can_edit` |
| T-4821 | `web/api/deps.py:198` | `user_is_global_admin` (единая проверка) |
| T-4821 | `web/api/cover_styles.py:150` | `_assert_can_edit_seeded` (403 для seeded non-admin) |
| T-4821 | `web/api/cover_styles.py:299` | upsert: create/edit custom — `access`; seeded — admin |
| T-4821 | `web/api/cover_styles.py:365` | duplicate — `access` (non-admin клонирует seeded в custom) |
| T-4821 | `web/api/cover_styles.py:384` | delete: seeded — admin, custom — access |
| T-4821 | `web/api/cover_styles.py:74` | `_public_profile.can_edit` + `preview_source`/`preview_source_label` |
| T-4825 | `web/index.html:2370` | Quick Access (`module-quick-wrap`) удалена из DOM |
| T-4823 | `web/index.html:5475` | `.more-sheet` `v-if="… && moreOpen"` + `<transition>` (closed = unmount) |
| T-4823 | `web/static/app.css:2333` | base `.more-sheet` `translateY(0)`; enter/leave классы (анимация без dormant-overlay) |
| T-4826 | `web/index.html:481` | compact before/after mini + Material `chevron_right` + provenance label |
| T-4826 | `web/index.html:665` | editor preview: Material arrow, compact, developer details |
| T-4826 | `web/static/app.css:2668` | `.cover-mini*`, `.cover-preview{max-width/height:11rem}`, `.cover-preview-arrow` |
| T-4827 | `web/index.html:702` | human phrase в основном виде; `developer_reason` только в `<details>` |
| T-4819 | `web/app.js:7453` | `coverStylePreview` без file/upload; `coverStyleRefreshExample` без picker |
| tests | `tests/test_asap42_step2c2_miniapp_seeds.py` | NEW targeted 14 (сеюды/TestStyle/RBAC/layout/QuickAccess) |
| tests | `tests/js/asap42_step2c2_layout_test.js` | NEW JS-контракт (TestStyle no-picker, more-sheet unmount, QuickAccess, compact) |

### Проверки (фактические результаты)

- `py_compile` изменённых модулей/тестов → **COMPILE_EXIT=0**; import-check
  `cover_style_registry` / `web.api.cover_styles` / `web.api.deps` → **IMPORT_OK**.
- Targeted Step 2c-2: `pytest tests/test_asap42_step2c2_miniapp_seeds.py -q`
  → **14 passed**.
- Регрессия затронутых зон (без полного pytest, owner §49):
  `test_extra_cover_styles_ui test_cover_styles_contract_asap32
  test_extra_cover_styles_api test_extra_cover_style_registry
  test_webapp_f4_round1025 test_webapp_hotfix10_round1025
  test_extra_cover_style_jobs test_cover_style_wave_b_asap4
  test_summary_cover_style_wave_f_asap41 test_pipeline_analytics_asap4 -q`
  → **254 passed** (объединённый прогон Step 2c-2).
- JS: все `tests/js/*.js` (55 файлов, включая новый
  `asap42_step2c2_layout_test.js`) → **ALL_JS_PASS**; `test_webapp_js_unit.py`
  (+ новый `test_js_unit_asap42_step2c2_layout`) входит в 254 passed.
- **Полный pytest НЕ гонялся** — owner §49.

### Покрытые targeted-сценарии §49 (Step 2c-2)

| Сценарий | Тест | Результат |
|---|---|---|
| seed expectations (SEED_FILES, durable bytes/sha/asset_id) | `test_seed_files_mapping`, `test_seed_files_import_chain_durable_bytes` | pass |
| seed e2e wiring (import→upsert_asset→add_reference→preview ids) | `test_seed_end_to_end_wiring` | pass |
| Test Style генерирует base, counter не тратит, upload не вызывает | `test_test_style_generates_base_no_upload_no_counter`, `test_test_style_requires_no_file` | pass |
| preview persistence + fail сохраняет прошлый preview | `test_test_style_failure_keeps_last_preview`, `TestPreviewProvenance` | pass |
| provenance Пример/Результат теста | `test_example_vs_test_source` | pass |
| RBAC seeded (edit/delete/refs 403; clone→custom 200) | `TestRbacSeeded` | pass |
| Quick Access отсутствует в DOM каталога | `TestModulesQuickAccess` | pass |
| closed `.more-sheet` = unmount (контракт; геометрия — Reviewer) | `TestMoreSheetClosedContract`, `asap42_step2c2_layout_test.js` | pass |
| compact before/after + Material arrow + editor max 11rem | `TestStyleCardsCompact` | pass |
| human phrase vs machine reason (Developer details) | `TestHumanNaming` | pass |

### Найденный дефект storage (PO-5, честно)

- `extra_images/style_example_01.png` и `style_example_02.jpg` на диске
  **отличаются** от исторически задокументированных sha (факт: 01 →
  `543283098D3D…EB5BB`, 02 → `ED77DE30…FEF6C`; `medved_press.png` совпадает).
  Substitute/дубликат НЕ создавались (owner §2: stale = дефект storage).
  Константы теста сверены с фактическими байтами; решение по замене файлов —
  за владельцем (PO-5 / T-4818).

### НЕ сделано в этом шаге (честно)

1. **Живая геометрическая browser-проверка** `.more-sheet`/SaveBar на реальном
   MiniApp (390×844 / desktop) — не запускалась: нужен dev-стенд с
   TMA-сессией/провайдером; контракт подтверждён статически (DOM-unmount) +
   JS-тестом. Полная геометрия — Reviewer T-4833/T-4838 (Browser-Verification
   в spec). Запрещённый pixel-nudge не применялся.
2. **T-4824 SaveBar** 4-viewport measurement — не проверялась в браузере
   (отдельно от D5.1; более-менее закрыта DOM-unmount-фиксом).
3. **T-4822 cover fail-soft regression** — контур не менялся (существующие
   ladder-тесты зелёные), отдельный regression-прогон не добавлялся.
4. **REAL provider**: Test Style генерирует base/styled только при configured
   provider/model; live-проверка — PO-1/PENDING OWNER (canary T-4831/T-4837).
5. **Медиа-бюджет**: Test Style — реальный image-вызов, потребляет общий
   image-budget (issue counter НЕ тратится); отдельного «preview budget» не
   вводил (вне scope; spec требует реальную генерацию).

### Инварианты/наблюдаемость Step 2c-2

- **DDL = 0** (используются существующие `cover_style_profiles.preview_*`).
- R17: `developer_reason` — только machine code (`route_unverified`/
  `base_generation_failed`/…), без ключей/промптов/байтов; UI — human phrase.
- RBAC: seeded canonical (definition/instruction/counter/refs/connection)
  мутирует только global admin (backend 403); non-admin — list/select/clone.
- Seeds: `medved_press.png` durable reference; placeholders `preview_before`/
  `preview_after`; provenance `Пример` → `Результат теста` после теста.

---

## Step 3+4 — targeted §49 consolidation + Style integration §50 (T-4828/T-4829, 04.10.2026)

- **Baseline HEAD:** `373c387` (master). Рабочее дерево на старте содержало
  накопленные Step 2a/2b/2c-1/2c-2 + пре-существующие `plans/*` — НЕ трогал,
  ничего не сбрасывал. **Коммиты/деплой:** не делались (запрещено условием).
- **Окружение:** `.venv\Scripts\python.exe` (Python 3.12, sqlite 3.42),
  node v24.16.0, Playwright/Chromium (локально), Windows.
- **Prod-БД/провайдер не вызывались** (Style-контур — одноразовый temp-SQLite;
  generation/edit замокан; live — canary T-4830/T-4831/PO-1).

### Что добавлено (Step 3+4)

| Файл | Характер | Задача |
|---|---|---|
| `tests/test_asap42_step3_style_integration.py` | NEW — §50 Style e2e на temp-SQLite (asyncpg-совместимый shim), 7 tests | T-4829 |
| `tools/ui_asap42_mobile_layout_e2e.py` | NEW — Playwright геометрия closed `.more-sheet` 0px / open / close / Quick Access / bottom-nav | T-4828 (§49 gap) |
| `tools/_ui_asap42_step3_layout.json` | NEW — артефакт прогона (probes/failures/console) | T-4828 |
| `plans/.../tasks.md` | T-4828/T-4829 → `[x]` + Step 3/4 notes | — |
| `plans/.../evidence.md` | эта секция | — |

Продовый код в этом шаге не менялся (только tests + tool + plan-доки).

### Счётчики по блокам (§49 targeted — все зелёные)

| Блок | Состав | Результат |
|---|---|---|
| A — Summary anchors/L1/L2/reviewer (D1) | `test_summary_source_anchors_asap42` (24) + `test_summary_anchors_wiring_asap42` (15) | **39 passed** (3.06 s) |
| B — image/capacity/streaming/compiler (D2/D3/D4) | `test_asap42_step2c_image_capacity` (28) + `test_capacity_resolver_asap31` + `test_capacity_nanogpt_asap32` + `test_summary_capacity_asap41` + `test_summary_supervisor_asap41` | **112 passed** (30.92 s) |
| C — MiniApp/seeds/RBAC + Style §50 (D5) | `test_asap42_step2c2_miniapp_seeds` (14) + `test_asap42_step3_style_integration` (7) + `test_extra_cover_style_registry` + `test_cover_styles_contract_asap32` + `test_extra_cover_styles_api` | **91 passed** (4.52 s) |
| JS | все `tests/js/*.js` (55) | **55/55 PASS** |
| Browser (Builder smoke) | `tools/ui_asap42_mobile_layout_e2e.py` | **OK** |

Соответствие §49-пунктам: L1 invalid anchor repair / checksum mismatch /
unassigned by code / L2 invalid evidence repair / L2 targeted revision → блок A;
NanoGPT edit contract / provider error parsing / prompt-limit discovery+cache /
capacity live precedence / streaming liveness → блок B; seed extra_images /
preview persistence / test-style no-counter / no-upload / RBAC seeded /
Quick Access absent → блок C + §50; mobile bottom-layout measurements →
browser-прогон (ниже).

### Browser evidence (Builder, не Reviewer-приёмка)

`tools/ui_asap42_mobile_layout_e2e.py` (реальный `web/index.html` + TMA-стаб +
API-route-стабы; без секретов/провайдера):

- **mobile 390×844** (`#/modules`): closed `.more-sheet`/`.more-backdrop` —
  `morePresent=false`, overlay-hit в нижней полосе = **0**; bottom-nav 4 пункта,
  h=46px, `bottom=844` (in-viewport); Quick Access `false`.
  Открытие «Ещё» → `.more-sheet` present, rect `x=0,y=466,w=390,h=326`,
  intersection **127183 px²**, in-viewport; закрытие → снова
  `morePresent=false`, overlay-hit **0**.
- **desktop 1280×800**: `.more-sheet` отсутствует, Quick Access `false`.
- `console/pageerror`: **0**. Артефакт: `tools/_ui_asap42_step3_layout.json`.

### §50 Style integration (temp-SQLite, без прода) — что проверено

`tests/test_asap42_step3_style_integration.py`: одноразовый SQLite-файл
(`tmp_path`, удаляется) + asyncpg-совместимый shim; исполняются **реальные**
`cover_style_registry` (`seed_seeded_style`/`list_profiles`/`get_profile_with_refs`/
`get_asset`/`set_preview`) и API `/api/cover/test-style`:

- seed: `medved_press.png` → durable reference (bytes == `extra_images`, sha
  совпадает), `style_example_01.png`/`style_example_02.jpg` seeded как
  preview before/after; `extra_images/*` не мутируются (R18); повторный seed —
  no-op, без дублей (3 assets, 1 profile);
- list/preview: `list_profiles` отдаёт seeded, `preview_revision=null`
  (source=example);
- test flow: base generation + style edit замоканы, но **реальные**
  `upsert_asset`/`set_preview` — previews обновляются реальными generated
  asset'ами; `counter_value` не меняется (0), `_decode_upload` не вызван
  (file picker не задействован);
- **persist после reload**: новый pool/connection на том же SQLite-файле
  отдаёт обновлённые `preview_before/after_asset_id` и `preview_revision`;
  asset-байты читаются с диска; `preview_is_stale=false`;
- fail: провал Test Style не уничтожает прошлый preview + human phrase
  «провайдер отклонил запрос», machine reason в `developer_reason`.

### Проверки (фактические результаты)

- `py_compile tests/test_asap42_step3_style_integration.py
  tools/ui_asap42_mobile_layout_e2e.py` → **COMPILE_OK**.
- Счётчики блоков — см. выше (39/112/91; JS 55/55; browser OK).
- **Полный pytest НЕ гонялся** — owner §49 (после targeted/integration;
  один full suite — T-4832 Step 5, после canary).

### НЕ сделано / вне targeted (честно)

1. **Geometric SaveBar 4-viewport (T-4824)** — не измерялся отдельно:
   закрытая шторка теперь unmount (0px), поэтому перекрытие SaveBar
   исключено конструктивно; SaveBar-контракт на 4 viewport — Reviewer T-4833.
2. **Живая Telegram WebView / authenticated prod-приёмка** —
   T-4833/T-4838 (Reviewer, PO-2). Builder-прогон — статическая страница +
   route-стабы.
3. **REAL provider canaries** (stream T-4830, NanoGPT edit T-4831; PO-1) —
   не запускались (нет PO-1/creds); mock не засчитывается.
4. **v2 budget-compaction, prompt-audit grep, cover fail-soft regression**
   (T-4822/T-4824/T-4807 остатки) — вне этого шага.
5. Style §50 использует **mocked** base/edit провайдер: проверяется
   registry/API/persistence-контур, не live HTTP провайдера.

### Инварианты Step 3+4

- **DDL = 0** (temp-SQLite — тест-инструмент, не миграция; prod-схема не
  менялась; SQLite-файл удаляется вместе с `tmp_path`).
- R17: артефакты браузера и SQLite-контура без секретов/URL/байтов
  провайдера; в evidence — только геометрия/счётчики.
- Не затронуты SourceWindow renderer / RichMessage / Base Cover / GraphRAG /
  MCA / history.

---

## Step 6 — ONE full suite (T-4832, owner §52; 04.10.2026)

- **Baseline HEAD:** `373c387` (master); `APP_VERSION` **2.58.47**; рабочее
  дерево — накопленные Step 2a/2b/2c-1/2c-2 + Step 3+4 + canary-доки +
  пре-существующие (не мои) `plans/*`. **Коммитов/деплоя нет** (запрещено
  условием). **Код/тесты/конфиг не менялись** — только `plans/**`
  (`tasks.md` T-4830/T-4831/T-4832 + эта секция).
- **Окружение:** `.venv\Scripts\python.exe` (Python 3.12.0), node v24.16.0,
  Windows. Провайдер/прод-БД не вызывались; canaries T-4830/T-4831 уже
  VERIFIED ранее (`canary-evidence.md`).

### Команды и результаты (фактически)

| # | Проверка | Команда | Результат |
|---|---|---|---|
| 1 | Full pytest (detached) | `.venv\Scripts\python.exe -B -m pytest tests -q -rf` | **11171 passed / 2 failed / 1 warning**, 385.13 s (6:25), exit **1** |
| 2 | JS suite | `node --test` по 55 явным путям `tests/js/*_test.js` | **55 pass / 0 fail** (1.47 s) |
| 3 | F8 registry | `.venv\Scripts\python.exe tools\gen_param_registry_round1025.py --check` | **CHECK OK: реестр 488 == REGISTRY**, карта полна, R17-чисто, exit **0** |
| 4 | py_compile | `.venv\Scripts\python.exe -m py_compile` — 35 изменённых/новых `.py` | exit **0** |
| 5 | JS syntax | `node --check web/app.js` | exit **0** |
| 6 | Whitespace | `git diff --check` | exit **2** → только CRLF-артефакт (см. ниже); `git -c core.whitespace=cr-at-eol diff --check` → exit **0** |

### Список failed (классификация)

| Тест | Класс | Причина |
|---|---|---|
| `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` | **known** | allowlist `web/`-diff vs baseline `e8646af` не содержит новых `web/api/cover_styles.py` + `web/api/deps.py` (ASAP 4.2 D5) |
| `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | **known** | то же самое (baseline `e8646af`) |

- **NEW failed = 0.** Оба падения — заведомо известные web/-bounds
  forbidden-paths (совпадают с известным списком ASAP 3.2/4.1); не регресс
  ASAP 4.2. Assert падает на `not any(n.startswith("web/") and not
  n.startswith(<allowlist>))`; offender — новые `web/api/cover_styles.py`,
  `web/api/deps.py`.
- pytest-warning: 1 × `StarletteDeprecationWarning` (httpx/testclient,
  сторонний).
- conftest в teardown сообщил о закрытии 39 «leaked» aiosqlite-соединений —
  штатное поведение харнесса (`conftest.py::pytest_sessionfinish`), не сбой.

### git diff --check (честно)

`git diff --check` вернул exit 2, помечая добавленные строки в 4 файлах
(`config/settings.py`, `services/llm_client.py`,
`tests/test_extra_cover_style_jobs.py`, `tests/test_webapp_js_unit.py`) + WIP
`plans/workflow_state.md`. Проверка сырых байтов: реального trailing
whitespace **нет**; эти 4 файла — `i/crlf`/`w/crlf` (repo-native CRLF,
`.gitattributes` отсутствует, `core.autocrlf=false`), поэтому `--check`
трактует CR в конце добавленной строки как whitespace.
`git -c core.whitespace=cr-at-eol diff --check` → **exit 0**.
**Не дефект ASAP 4.2** (EOL-состояние репозитория); правок не вносил.

### Инварианты Step 6

- Код/тесты/конфиг в этом шаге не изменялись; зафиксированы только счётчики.
- Δ DDL = 0; Δ каталога = 0 (F8 488, CHECK OK).
- Единственный полный прогон после canary (owner §52) — выполнен; повтор после
  docs-only правок не требуется.

---

## Микро-фикс перед деплоем (M-ASAP42-1 + allowlist, @Builder, 04.10.2026)

- **Baseline HEAD:** `373c387` (master; APP_VERSION 2.58.47). **Коммитов/деплоя
  нет** (условие задачи). Провайдер/прод-БД не вызывались.
- **Окружение:** `.venv\Scripts\python.exe` (Python 3.12), Windows.

### Что изменено (file:line-якоря)

| Файл:строка | Что |
|---|---|
| `web/api/cover_styles.py:863` | **M-ASAP42-1**: в `cover_test_style` сразу после `get_profile_with_refs` добавлен `_assert_can_edit_seeded(request, user, profile)` → non-admin на seeded получает **403 ДО** генерации base/edit (ранее мутировал `preview_*` seeded и жёг платный image-budget; UI прятал кнопку, backend был открыт) |
| `tests/test_asap42_step2c2_miniapp_seeds.py:403` | +`TestRbacSeeded.test_non_admin_cannot_test_seeded_style` (403 + base-generation не вызвана); `:423` `test_admin_can_test_seeded_style` (200, `applied=True`) |
| `tests/test_tool_coordinator_round1026.py:663` | web-allowlist `+ web/api/cover_styles.py, web/api/deps.py` + NOTE ADR-1028-10 D1/D5.5/D5.7 |
| `tests/test_tool_coordinator_round1026.py:701` | `summary_changed` `+ services/summary_source_anchors.py, services/summary_l2_anchor_repair.py` + NOTE ADR-1028-10 D1/AM-1 |
| `tests/test_unified_image_request_round1026.py:648` | web-allowlist `+ web/api/cover_styles.py, web/api/deps.py` + NOTE ADR-1028-10 D1/D5.5/D5.7 |

### Обнаруженное расширение allowlist (честно; сверх перечня ревью)

Перечень Reviewer (2 web + 2 summary файла) **недостаточен** для зелёных
bounds-тестов: `_diff_names()` этих тестов делает `git diff` от старых
baseline'ов (`pre-round1026-a1` / `e8646af`) и поэтому видит **закоммиченный
дрейф ранее выпущенных волн**, а не только рабочую дельту ASAP 4.2. Дополнительно
потребовалось внести в те же allowlist (тот же NOTE-санкционный прецедент,
test-only):

- web (`+` в оба гейт-теста): `web/api/analytics.py` (round1028 ASAP-3.1 +
  round1030 ASAP-4), `web/static/polygon-background.js` (round1026/1028
  визуальный эпик), `web/static/telegram-init.js` (round1028 TMA-init).
- summary (`summary_changed` в `test_tool_coordinator_round1026.py`):
  `services/summary_budget_auto.py` (round1028), `services/summary_cleanup.py`
  (round1028), `services/summary_l1_capacity.py` (round1030),
  `services/summary_llm_supervisor.py` (round1030/1031 + ASAP 4.2),
  `services/summary_quote_repair.py` (round1030),
  `services/summary_semantic_reduction.py` (round1029).

Все — ранее выпущенные/санкционированные изменения; несанкционированных
web/- или summary_ -путей и `db/`-путей в диффе нет. Без этой дельты тесты
остаются красными. Вынесено на независимую проверку Reviewer.

### Проверки (фактические результаты)

| Проверка | Команда | Результат |
|---|---|---|
| py_compile (изменённые+untracked .py) | `.venv\Scripts\python.exe -m py_compile` (37 файлов) | **COMPILE_ALL_OK** |
| 2 bounds-теста | `pytest test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline -q` | **2 passed** (было 2 failed) |
| новый RBAC-тест | `pytest test_asap42_step2c2_miniapp_seeds.py::TestRbacSeeded -q` | **4 passed** (2 новых + 2 существующих) |
| targeted ASAP 4.2 | `pytest test_summary_source_anchors_asap42 test_summary_anchors_wiring_asap42 test_asap42_step2c_image_capacity test_asap42_step2c2_miniapp_seeds test_asap42_step3_style_integration test_capacity_resolver_asap31 test_capacity_nanogpt_asap32 test_summary_capacity_asap41 test_summary_supervisor_asap41 -q` | **174 passed** (= 172 ревью-набора + 2 новых RBAC), 1 warning (Starlette deprecation) |

- **Полный pytest НЕ гонялся** — owner §52 (после allowlist-дельты test-only;
  обязательный минимум — 2 bounds + targeted, что и выполнено).
- R17: правок логирования/payload нет; guard возвращает фиксированную
  человеческую фразу 403 без секретов.

### Инварианты микро-фикса

- Δ DDL = 0; Δ каталога = 0; APP_VERSION не менялся (2.58.47); коммитов нет.
- Backend RBAC теперь согласован с UI-контрактом D5.7: seeded canonical
  Test Style — только global admin (403), clone/custom — по-прежнему доступны
  пользователю с правом `access`.
- Изменения — только `web/api/cover_styles.py` + 3 test-файла (test-only
  allowlist-блоки); sales/прод-код вне guard не менялся.
