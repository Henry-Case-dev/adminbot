# P0-EMBED-503-FAILOVER — admission correction: MSI, not PCI

Дата: 2026-11-22. Owner input:
`plans/owner_inputs/2026-11-22-p0-embed-admission-clarification.md`,
sha256 `adcc50d96c15aba8ffcdee13552ceebd6651df4aadf41ed592204a5391b4d468`
(verbatim amendment, не новый эпик).

Base tip: `d00a01b07eec2143f355dcba6067f92074e3d064`.
Candidate c5: `1b7d4bf0471a10aaff5d4f0c40eacd77f707727d`.

## 1. Что было неверно

Предыдущий candidate привязывал admission к PCI:

- `admission_valid()` требовал `admission["conn"] == conn_now`;
- `resolve_index_compat()` при совпадении MSI, но другом PCI возвращал
  `insufficient` / `compat_not_proven` / `COMPATIBILITY_UNKNOWN` /
  `needs_probe=true`;
- write-гейт `_serving_route_write_allowed()` из-за этого оставлял
  Google-fallback в `text-only`, хотя model/dims/preprocessing/MSI
  совпадали (`gemini-embedding-001`, 3072, MSI `e540d4ad890e121d`).

Это была ложная блокировка: менялся API-шлюз (apinet → Google), а не
модельное пространство. PCI — провенанс/диагностика, не identity.

## 2. Изменённые admission-ключи/функции

`services/embedding_control_plane.py`:

1. `admission_valid(admission, *, space_now, conn_now)` — **ключ допуска =
   `space` (MSI)**. `conn` больше не сравнивается; параметр `conn_now`
   оставлен для совместимости/диагностики. Historical PCI-keyed admission
   (`config_revision=adopt1:<space>:<old_conn>:...`) переиспользуется при
   совпадении MSI.
2. `classify_identity_compatibility()` — при равных `current_space` /
   `stored_space` возвращает `COMPAT_INSTANT` (раньше `UNKNOWN` без canary).
   `CANARY_DRIFT` → `REINDEX`, другое MSI → `REINDEX`, dimension mismatch →
   `INCOMPATIBLE_DIMENSION` остались.
3. `resolve_index_compat()`:
   - MSI активной generation == текущему MSI (+dims) → `compatible`,
     `serviceable=true`, класс `ADMITTED_COMPATIBLE` при валидном
     space-admission, иначе `INSTANT_COMPATIBLE`; migration/probe по факту
     смены шлюза не запускается;
   - MSI mismatch / provable model/dim/preprocessing mismatch →
     `incompatible` с конкретным `identity_changed`/`dimension_changed`
     (admission не переопределяет реальное расхождение);
   - MSI отсутствует, но есть сохранённые live-векторы → `needs_probe=true`,
     `reason_code=msi_unavailable`; `ensure_index_compat()` выполняет
     **одну** ограниченную пробу существующим `compat_probe` на старых
     строках индекса; success → durable admission для space (conn —
     провенанс), failure/insufficient → text-only/FTS;
   - exact fingerprint match по-прежнему `INSTANT`.
4. `format_admission()` — формат не менялся (совместимость), `conn` явно
   задокументирован как провенанс; admission storage/`config_revision`
   прежний, без нового store/DDL.
5. `profile_identity()`/`embedding_identity_v2()`/`embedding_canary_check()`
   не переписывались: PCI остаётся провенансом, canary DRIFT остаётся
   safety-гейтом.

`services/summary_memory.py`:

- `_serving_route_write_allowed()` уже вызывает `resolve_index_compat` с
  route-override; после MSI-коррекции same-MSI fallback проходит. Его
  docstring обновлён.
- `_vec_write_allowed()`, `_save_graph_fact_embedding()`,
  `_save_archive_embedding()`, `backfill_archive_vectors()`,
  `backfill_graph_fact_vectors()` не содержат нового PCI-гейта; они
  используют тот же resolver. Same-MSI fallback теперь пишет реальный
  вектор, different MSI/dim — text-only.
- `EmbeddingRouteNotAdmitted` остаётся terminal-состоянием только для
  реально несовместимого/недоказанного случая.

## 3. Тесты (обязательная матрица)

Новый файл `tests/test_p0_embed_admission_msi.py` (10 тестов):

- `test_live_msi_is_reproduced_from_model_and_dims` — локальный MSI
  `gemini-embedding-001`/3072 == `e540d4ad890e121d`.
- `test_same_space_without_canary_is_instant_compatible` — same MSI, разные
  PCI, без canary → `COMPAT_INSTANT`.
- `test_historical_pci_keyed_admission_is_reused_by_msi` — admission с
  `conn=apinet`, проверка с `conn=google` → valid; другое MSI → invalid.
- `test_same_msi_different_pci_writes_and_semantic_search` — primary
  `apinet_paid` 503 → fallback_1 `google_free_1` 200 → **`graph_facts_vec=1`**
  и реальный KNN/semantic hit (`WHERE embedding MATCH ... k=5`) находит
  fact_id; после восстановления primary старый вектор не теряется, новый
  факт пишется primary.
- `test_text_only_backfill_recovers_via_same_msi_fallback` — all legs 503 →
  text-only; fallback recovered → существующий `backfill_graph_fact_vectors`
  пишет 1 вектор, повторный — 0, semantic hit есть.
- `test_different_msi_is_text_only` — active model `text-embedding-004`
  vs current `gemini-embedding-001` → incompatible, `graph_facts_vec=0`,
  FTS-hit, `embedding_cache` не содержит fallback-вектор.
- `test_dimension_mismatch_is_text_only` — active dims 1536 vs 3072 →
  `dimension_changed`, no write.
- `test_canary_drift_still_blocks_same_msi` — DRIFT при same MSI → no write.
- `test_no_msi_probe_success_persists_msi_admission` — active row без MSI,
  старые векторы; ровно **один** probe call; durable admission
  `space=e540…`; последующая запись через same-MSI fallback даёт
  `graph_facts_vec=13` (12 old + 1 new) и semantic hit нового факта.
- `test_no_msi_probe_failure_stays_text_only` — probe на других векторах
  (не Google-vs-Google) → incompatible, один вызов, admission нет,
  `graph_facts_vec` остаётся 12, новый факт text-only.

Обновлены существующие guard-тесты:

- `test_embed_identity_compat.py::test_garbage_admission_fails_closed` —
  garbage `config_revision` при отсутствии MSI → `insufficient`,
  `needs_probe=true`, без auto-trust; MSI-случай покрыт новым файлом.
- `test_embed_identity_compat_restart_legacy.py::test_b3_active_legacy_without_msi_never_rebuilds`
  — no-MSI + saved vectors → `msi_unavailable`/`needs_probe`, без rebuild.
- `tests/test_p0_embed_503_failover.py` — удалён PCI-bound тест, ожидавший
  `graph_facts_vec=0` при Google 200/3072; e2e all-legs-down/backfill
  сохранён.

## 4. RED / GREEN

RED на tip `d00a01b07` (до MSI-фикса), новый файл:
`6 failed, 4 passed` — same-space INSTANT, historical PCI admission,
same-MSI write+semantic, fallback backfill, no-MSI probe success/failure.
Лог: `tests-red-base-msi-2026-11-22.txt`.

GREEN на c5: **657 passed, 0 failed/errors**, 1 pre-existing deselected:
`tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced`
(падает identically на base `d00a01b07`; source-empty reconciliation emits
two warnings, к admission не относится).
Машинный отчёт: `tests-admission-msi-2026-11-22.json` (657 testcases,
полный список outcomes). Сырой вывод:
`tests-admission-msi-2026-11-22.txt`.

Мутации (`mutations-admission-msi-2026-11-22.txt`):

- PCI-bound admission → `test_historical_pci...` падает `assert False is True`;
- no-write route gate → same-MSI semantic-тест падает `graph_facts_vec 0 != 1`;
- any-space admitted (игнор MSI mismatch) → different-MSI тест падает
  `compatible != incompatible`.

## 5. Diff / границы

`git diff --name-only d00a01b07..1b7d4bf`:

- `services/embedding_control_plane.py`
- `services/summary_memory.py` (только docstring route-gate)
- `tests/test_p0_embed_admission_msi.py` (new)
- `tests/test_p0_embed_503_failover.py`
- `tests/test_embed_identity_compat.py`
- `tests/test_embed_identity_compat_restart_legacy.py`

Не изменены: модель `gemini-embedding-001`, существующие индексы/эмбеддинги,
DDL/схема, UI, настройки/ключи владельца, `plans/progress_scope.json`,
`plans/workflow_state.md`, 2.58.229 и другие задачи очереди.

Ограничения:

- Деплой/live smoke не выполнялись (prod/SSH/LLM запрещены этим lane).
  apinet 503 остаётся внешним; «apinet починен» не заявляется.
- Same-MSI fallback admitted по метаданным generation; real MSI/model/
  dimension/preprocessing mismatch и canary DRIFT по-прежнему блокируют.
- No-MSI legacy probe использует существующий `compat_probe` с его текущими
  порогами (строже owner-floor 0.98/0.95: mean≥0.995/min≥0.990 + hit5≥0.80),
  одна серия на старых векторах; live-кейс same-MSI в пробе не нуждается.
- `smart_archive source_empty/superseded` — отдельная проблема, не 503.
