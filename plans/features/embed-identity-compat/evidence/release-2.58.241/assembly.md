# Релиз 2.58.241 — сборка (EMBED-SIMPLIFY / слайс `SIMPLIFY`)

- **Роль:** сборка релиза (Builder-полоса). **Без деплоя и без SSH** — выкладка и пост-деплой
  проверки за DevOps.
- **Задача:** линейная релизная ветка `release/embed-simplify-2.58.241` из **фактического прода**
  2.58.240 (`f7e20e15d`) + два независимо одобренных коммита слайса + штатный bump 2.58.241.
- **Owner-источник:** `plans/owner_inputs/2026-11-24-embedding-vmq-ibm-qrng-ux.md` §1/§6,
  sha256 `6631186ccfbc3ba81c369f18bca6168a33ac20ad1e2f789cae3d34348ea8c73d`.
- **Строки:** `SIMPL-01..07`, слайс `SIMPLIFY`
  (`requirements-map.json` → `additional_requirements[29..35]`; это файл канонического
  planning-checkout, в дельту релиза не входит). `SIMPL-01`/`SIMPL-02` = `live_required: preprod`.
- **Ревью кандидата:** `plans/features/embed-identity-compat/evidence/simplify-2026-11-24/review-r1.md`
  (sha256 `17fa8aab67e87851ae27b401b6dcb66a111624f8ca8494693a3639527d3c4fd7`; r1 = NEEDS_FIXES по
  `SIMPL-R1-F1`, r2 = **APPROVED_FOR_RELEASE_PREPARATION** на `87b4c96c6`). Артефакт ревью —
  некоммитнутый файл worktree кандидата, поэтому здесь он указан ссылкой и суммой, а не копией
  (иначе дельта релиза перестала бы быть «слайс + пин»).
- **Вход `SIMPL-05`:** `plans/features/embed-identity-compat/evidence/audit-2026-11-24.md`,
  sha256 `6be1e9dd1240758272de434902924f8f7d1697116323e01a294261b896d02f46`.

```json
{
  "release": "2.58.241",
  "slice": "SIMPLIFY",
  "rows": ["SIMPL-01","SIMPL-02","SIMPL-03","SIMPL-04","SIMPL-05","SIMPL-06","SIMPL-07"],
  "deployed_base": {"sha": "f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9", "version": "2.58.240",
                    "tree": "85777a31428eb6cfb6ea7a3094b71fa3a9e08826"},
  "reviewed_candidate": {"branch": "fix/embed-simplify-2026-11-24",
                         "tip": "87b4c96c698d97cd60477e79d93f50e6126d5b30",
                         "base": "a200b8c9a361487a2601fc6f9e4c2b09cd6c901e",
                         "verdict": "APPROVED_FOR_RELEASE_PREPARATION"},
  "release_branch": "release/embed-simplify-2.58.241",
  "content_tip": {"sha": "c9ef3dfa73b783cc9f84a66cc1f425d76ea61f3f",
                  "tree": "577d23eefc84fc80f10bc1790fd8f0995438c147",
                  "commits": ["3ffa6f2df (SIMPL-01..07)", "c9ef3dfa7 (SIMPL-01 F1)"]},
  "bump_tip": {"sha": "0d97fec12ca7abd6ac7a61222955afedf66edaa3",
               "tree": "8e6058e29812a3aa4821f44f68bb9e4fcb5fef33",
               "version": "2.58.241"},
  "delta_vs_deployed": {"files": 40, "insertions": 879, "deletions": 169,
                        "slice_files": 8, "version_pin_files": 32,
                        "ddl": 0, "migrations": 0, "flags": 0, "settings_rows": 0, "web_files": 0},
  "lineage": {"candidate_base_is_ancestor_of_deployed": true,
              "slice_patch_sha256": "4b5ae13400b54e81fd313cc5b6ef8f54f3db183d386d7cbea49c2d128e6ea4b5",
              "commit1_patch_sha256": "7ec1a727d3f9c44ae5799a2a9a42f85f6237aead70573f9dddb504dda012e6ae0",
              "commit2_patch_sha256": "feb58a80007e84ea1a5703f94019bdb7b52672879390b33cfe5657ef926e6a1c",
              "candidate_tip_to_release_content": "32 version-pin files, +35/-35, slice untouched"},
  "tests": {"passed": 476, "failed": 3, "pre_existing": 3,
            "new_file": 10, "targeted_embed": 75, "control_plane_deps": 209,
            "summary_memory": 79, "graphrag_identity_recovery": 83,
            "version_pin_guard": 20, "js_pin_guards": "4/4 OK"},
  "manifest_dry_run": {"version": "2.58.241", "dirty_tracked": false,
                       "deployed_sha": "0d97fec12ca7abd6ac7a61222955afedf66edaa3",
                       "previous_sha": null, "previous_version": null,
                       "note": "clean checkout без .deploy/release.json (файл gitignored); на хосте previous = f7e20e15d / 2.58.240"},
  "rollback": {"code_only_sha": "f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9",
               "ddl": 0, "flags": 0, "data_migration": false},
  "status": "ASSEMBLED — ожидает независимого ревью дельты и деплоя"
}
```

## 1. Линейность и происхождение (машино-проверяемо)

| Проверка | Команда | Результат |
|---|---|---|
| База прода содержит базу кандидата | `git merge-base --is-ancestor a200b8c9a f7e20e15d` | **rc=0** (a200b8c9a — предок 2.58.240) |
| Ветка создана из точного прода | `git worktree add -b release/embed-simplify-2.58.241 <path> f7e20e15d` | HEAD = `f7e20e15d`, tree `85777a31…` = tree из deploy-2.58.240 |
| Коммиты применены линейно | `git cherry-pick e67378335; git cherry-pick 87b4c96c6` | без конфликтов, **0** merge-коммитов |
| Патчи идентичны отревьюенным | `git show --format= <sha>` sha256 | c1 `7ec1a727…` == c1; c2 `feb58a80…` == c2 |
| Вся дельта слайса идентична | `git diff a200b8c9a..87b4c96c6` vs `git diff f7e20e15d..c9ef3dfa7` | байт-идентично, sha256 `4b5ae134…` (83 370 B) |
| Кандидат → релизный контент = только пины | `git diff 87b4c96c6..c9ef3dfa7` | **32 файла, +35/−35**, ни одного файла слайса |

Линейная цепочка: `f7e20e15d` → `3ffa6f2df` → `c9ef3dfa7` → `0d97fec12` (bump).
`git log --merges f7e20e15d..0d97fec12` пуст.

## 2. Границы дельты (`git diff f7e20e15d..0d97fec12`)

- **40 файлов**: 8 файлов слайса (`services/embedding_control_plane.py`,
  `services/summary_memory.py`, `services/llm_client.py`, `tests/test_embed_simplify_2026_11_24.py`,
  `tests/test_embed_identity_compat.py`, `tests/test_embed_identity_compat_restart_legacy.py`,
  `tests/test_p0_embed_admission_msi.py`, `evidence/simplify-2026-11-24/implementation.md`)
  + 32 файла штатного bump.
- `web/*`: **0** файлов; `migrations/*`: **0**; `services/database.py`, `graphrag_rebuild.py`,
  `mca_retrieval_context.py`, `llm_probe.py`, `direct_*`, `chat_clock.py`, `tool_router.py`,
  `.env.example`: **блобы идентичны** базе.
- **DDL 0, миграций 0, новых флагов/настроек 0, новых таблиц/реестров/identity-систем 0**
  (оба коммита не трогают схему; `config/settings.py` — только строка `APP_VERSION`).
- Пин-строки: в 31 файле различие **только** в токене версии (`2.58.240` → `2.58.241`,
  в `tests/js/*` — `2\.58\.240` → `2\.58\.241`), проверено по строкам хунка (+34/−34).
  `config/settings.py` — единственное исключение по конвенции релиза: значение `APP_VERSION`
  **и** голова описания переведены на `2.58.241 - EMBED-SIMPLIFY (SIMPL-01..07) …`,
  прежняя голова понижена в `Prior 2.58.240 - UNIFIED-REPLY UR-C-CLOCK` (так же оформлен bump
  2.58.239 → 2.58.240, `6123a1469`/`f7e20e15d`).
- `git diff --check` (worktree и диапазон): rc=0.

## 3. Соответствие строкам (что именно доказывает каждый набор)

| Строка | Код на релизном контенте | Тесты на этом же типе |
|---|---|---|
| `SIMPL-01` provider/endpoint/key/alias/PCI/quota ≠ смена пространства | `embedding_control_plane.py:3048` (MSI по `_canonical_model_name`), `:3138`/`:3151` (legacy-строка тоже канонична), `:265`,`:741-810`,`:797` (health по значению ключа, TTL `HEALTH_AUTH_FAILED_TTL_S=900`) | `test_simpl01_provider_endpoint_change_keeps_index_serviceable`, `test_simpl01_msi_ignores_provider_namespace`, `test_simpl01_legacy_namespaced_model_is_not_a_new_space`, `test_simpl01_auth_failed_is_per_key_and_expires` |
| `SIMPL-02` каждая совместимая нога пишет и ищет | `summary_memory.py:3211` `_serving_route_space_matches` (MSI, не провайдер), вызов `:3411` | `test_simpl02_cache_gate_uses_model_space_not_provider`, `test_p0_embed_admission_msi.py::test_same_msi_different_pci_writes_and_semantic_search` (реальная запись + реальный semantic KNN через fallback) |
| `SIMPL-03` несовместимость только по свойствам модели/векторов | резолвер не изменён: `insufficient` без MSI/допуска, `incompatible` только на модель/размерность/препроцессинг (`:3988`, `:4056`) | `test_simpl03_missing_provenance_is_not_incompatible`, `test_simpl06_real_incompatibility_still_blocks_write` |
| `SIMPL-04` проба не блокирует память | `embedding_control_plane.py:4346-4355` — `insufficient` без паузы; паузы только в legacy-ветке (`:4334`); чтение открыто при ACTIVE+равной размерности (`summary_memory.py:2936`, `:3069`) | `test_insufficient_does_not_pause_rebuild_until_verdict`, `test_b1_restart_then_insufficient_keeps_job_running_without_rebuild`, `test_simpl02_insufficient_active_equal_dims_serves_reads` |
| `SIMPL-05` дубли сняты, новых сущностей нет | удалены мёртвые `_PAUSED_BY_COMPAT`/`_pause_rebuild_under` (в коде нет вхождений), слиты проверки count и cache-гейт; аудит §1–§6 | `test_simpl02_cache_gate_uses_model_space_not_provider`, `test_simpl07_msi_and_admission_formats_unchanged` + аудит диффа |
| `SIMPL-06` валидация ответа не ослаблена | `llm_client.py:413` `_validate_embed_vectors` (count/пусто/рваная/NaN/inf/нечисла), применяется в `:3049` и `:3108` | `test_simpl06_control_plane_rejects_malformed_vectors`, `test_canary_drift_still_blocks_same_msi` |
| `SIMPL-07` нет новых identity-систем, DDL 0, история цела | MSI `:3048-3058` и `admit1:` `:4357-4386` не менялись; DDL/таблиц/колонок нет | `test_simpl07_msi_and_admission_formats_unchanged` + `git diff` (DDL 0) |

## 4. Тесты (фактические прогоны на релизном контенте, `.venv` канонического checkout, cwd = worktree)

| Набор | Результат |
|---|---|
| `tests/test_embed_simplify_2026_11_24.py` | **10 passed** |
| `test_embed_identity_compat` + `..._restart_legacy` + `test_p0_embed_admission_msi` + `test_p0_embed_503_failover` + `test_embed_simplify…` | **75 passed** |
| `test_embedding_control_plane_asap4` + `test_embed_fallback_slots_routing` + `test_llm_client` + `test_embed_meta_wire` + `test_evol010_embedding_defects` | **209 passed** |
| `tests/test_summary_memory.py` | **79 passed** |
| `test_graphrag_identity_reindex` + `test_graphrag_rebuild_asap32` + `test_asap5_graphrag_recovery` + `test_asap6_embedding_generations` + `test_mca07_retrieval_context_round1027` | **83 passed, 2 failed** (pre-existing, §5) |
| version-pin guard: `pytest tests -k "app_version"` | **20 passed, 1 failed** (pre-existing, §5) |
| JS-пины `tests/js/round1025_hotfix{7,8,9,10}_*.js` | **4/4 OK** (маркеры OK, `APP_VERSION = "2\.58\.241"`) |
| `python -m py_compile` на 8 изменённых модулях/тестах + `config/settings.py` | rc=0 |
| `git diff --check` (рабочее дерево и `f7e20e15d..HEAD`) | rc=0 |

Итого **476 passed / 3 failed**, все три падения — pre-existing на базе (§5).
Проверено, что тесты действительно исполняют релизное дерево: `config.settings.__file__` и
`services.embedding_control_plane.__file__` указывают в worktree релиза, `APP_VERSION = 2.58.241`.

## 5. Pre-existing падения (не относятся к слайсу; не правились)

1. `tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced` — `assert 2 == 1`
   (второй WARNING при `building→superseded`).
2. `tests/test_asap5_graphrag_recovery.py::test_warning_coalesced_not_repeated` — та же причина.
   Оба воспроизведены ревьюером на базе `a200b8c9a` без правок; к слайсу не относятся.
3. `tests/test_webapp_round108_ui.py::TestCacheBustAndEsc108::test_app_version_matches_readme` —
   проверяет `"v" + APP_VERSION` в `README.md`. На базе 2.58.240 проверка тоже ложна
   (README байт-идентичен базе, `v2.58.240` в нём нет; последний пин в README — `v2.57.0`):
   воспроизведено чтением блобов `f7e20e15d:README.md` + `f7e20e15d:config/settings.py`.
   Это дефект состояния README до релиза, не регрессия bump'а → отдельная запись в бэклог,
   в этом релизе не правился (вне слайса).

`SIMPL-R1-F2` (`<= 1` в `test_p0_embed_admission_msi.py:362`) осознанно **не менялся** —
backlog-only по ревью.

## 6. Манифест

```
$ python tools/release_manifest.py --dry-run
{"deployed_at": "2026-11-24T10:54:34.202228Z",
 "deployed_sha": "0d97fec12ca7abd6ac7a61222955afedf66edaa3",
 "dirty_tracked": false,
 "effect": "deploy",
 "previous_sha": null, "previous_version": null,
 "release_branch": "release/embed-simplify-2.58.241",
 "schema": 1, "version": "2.58.241"}
```

`version=2.58.241`, `dirty_tracked=false` — как требуется. `previous_sha=null` — это **не** ошибка
сборки: `.deploy/release.json` gitignored и в чистом checkout отсутствует (та же картина была при
сборке 2.58.240); на хосте фактический манифест содержит `deployed_sha=f7e20e15d` / `2.58.240`,
поэтому при штатном `--effect deploy` `previous_*` заполнятся как `f7e20e15d` / `2.58.240`.

## 7. Откат

Только код: `git checkout --detach f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9` (2.58.240) + рестарт.
**DDL 0, миграций 0, новых флагов 0, миграции данных нет**, схема остаётся `user_version=48`;
написанные после деплоя векторы/факты остаются валидными для обеих версий (формат MSI/`admit1:`
не менялся). Pre-deploy backup и предыдущий backup — штатный deploy-пул keep=2.

## 8. Честные ограничения

1. **Live-гейт окружения доказан на 2.58.240, не на этом коде.**
   `plans/features/vmq-onto-01/evidence/vmq-env/verify-2026-11-24.md` (NanoGPT primary + 2 Google
   fallback, модель `gemini-embedding-001`, dims 3072; primary HTTP 200; fallback_1/2 200;
   одна запись `graph_facts.id=40067` + семантический KNN rank 1 / cosine 0.798792) прямо
   оговаривает: «Поведение кода более нового кандидата … этим доказательством не покрывается».
   Этот релиз **меняет** код совместимости → `SIMPL-01`/`SIMPL-02` остаются `PENDING`
   до пост-деплой проверки на выкаченном SHA (`deploy-checklist-2.58.241.md` §4–§7).
2. Прогонов на production/preprod в этой полосе не было (нет деплоя/SSH по заданию).
3. Визуальный гейт не срабатывал: `web/*` не изменён (Playwright + Browser Use не требовались).
4. Артефакт ревью `review-r1.md` не закоммичен (см. шапку) — его привязка к ledger остаётся
   за Orchestrator.

## 9. Следующие шаги

1. Независимое ревью этой дельты (`requirements_gate review --slice SIMPLIFY --candidate <tip> --repo …`)
   → `APPROVED_FOR_DEPLOY`.
2. DevOps: деплой точного tip релизной ветки по `deploy-checklist-2.58.241.md`, с пост-деплой
   проверкой effective-config/SHA, health, схемы, диска, grep по аудиту §7 и **одним реальным
   embed + одной записью + одним семантическим чтением на выкаченном кандидате**.
3. Только после этого `SIMPL-01/02` могут стать VERIFIED; до тех пор статус — ASSEMBLED.
