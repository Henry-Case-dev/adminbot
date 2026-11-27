# Release 2.58.259 — FCT-S3-RETRIEVAL + VMQ P-OLDROW (два reviewed-кандидата одним релизом)

- **Дата сборки:** 2026-11-27
- **Роль:** Builder (сборка релиза, **без деплоя**)
- **Основание:** два независимо одобренных кандидата; файлы не пересекаются.
  - FCT-S3-RETRIEVAL — review **r2 APPROVED** (`cc774ec0…`), F6 закрыт тестом.
  - VMQ P-OLDROW — review **r2 APPROVED_FOR_RELEASE_PREPARATION** (`3fb377d3…`).
- **База (deployed):** `886d11073cfdaa4646597c3a2b1ae09fde42c342` = **2.58.258** (UR-BAN-02)
- **Ветка:** `release/fct-s3-2.58.259` (содержит оба среза)
- **Tip релиза (продуктовый):** `bca5563be764dd3999b0cced9011e1e945bd9c0f`
- **Tree:** `dd2bd55cfc6ca9b91d643cb6c52541872fab694b`
- **Статус:** ASSEMBLED, не деплоился. Деплой — DevOps/Orchestrator.

## 1. Кандидаты

| # | Срез | Кандидат (reviewed) | Ветка | Контракт | Ревью |
|---|---|---|---|---|---|
| 1 | FCT-S3-RETRIEVAL | `2c811d98b7257810c2fef5b61ce7b416798ccb40` (+ F6-тест `40866af41`) | `feat/fct-s3-retrieval` (tip `d12263f35`) | `fct-s3-s4-contract-2026-11-27.md` sha256 `adb3bc325c4c4048d79d16b62f5b47c941a356ab4ee1c7b7953a5f3050630190` | r2 APPROVED |
| 2 | VMQ P-OLDROW | `77350314752882da1c718e20fa14d5484c42adb2` | `fix/vmq-oldrow` | `vmq-mem/selector-rootcause-2026-11-27.md` sha256 `bcce78bb31cec83f703031270af3a52ec2eb30a9a7421e726e45f0297b2e50fc` | r2 APPROVED_FOR_RELEASE_PREPARATION |

История ветки релиза:

```
bca5563be fix(vmq-mem): P-OLDROW F1 — subject_scope не замещает базовый срез   [cherry-pick -x]
b8081dbbc feat(vmq-mem): P-OLDROW — старший subject-bound период доходит до Writer
55167ddcf chore(release): 2.58.259 assembly evidence (FCT-S3 retrieval)
baab52324 chore(release): 2.58.259 - bump APP_VERSION and version pins (FCT-S3 retrieval)
bb3c958fb … 4c4c41301  (6 reviewed-коммитов FCT-S3, cherry-pick -x)
886d11073 chore(release): 2.58.258 assembly evidence (UR-BAN-02)   ← deployed base
```

Оба переноса — `cherry-pick -x`, **без единого конфликта**: feature-ветки отведены от
`9516c9125` (2.58.257), а все затрагиваемые ими файлы байт-идентичны этой точке
(проверено до переноса).

## 2. Байтовая идентичность reviewed-кода (доказано)

`raw/product-delta.txt`, `BYTE_IDENTICAL_ALL = True`:

| Срез | Файл | release tip blob | candidate blob |
|---|---|---|---|
| FCT-S3 | `services/factcheck_planner.py` | `3099bd9c30c8…` | `3099bd9c30c8…` |
| FCT-S3 | `services/search_aggregator.py` | `9a708f2c4def…` | `9a708f2c4def…` |
| VMQ | `services/mca_retrieval_context.py` | `1f9bca3cb2a6…` | `1f9bca3cb2a6…` |
| VMQ | `services/direct_chat_service.py` | `2fbf8ba30e21…` | `2fbf8ba30e21…` |

**Носители, которые обязаны остаться нетронутыми (байт-идентичны базе):**

| Файл | blob | статус |
|---|---|---|
| `services/safe_fetch.py` | `7e7cf0a505a9…` | без изменений (контракт S3) |
| `services/factcheck_attribution.py` | `bbcedf1b1db0…` | без изменений (контракт S3) |
| `services/direct_execution.py` | `f138c7a73703…` | без изменений (2.58.258 UR-BAN-02) |
| `web/api/routes.py` | `fa354eb402d0…` | без изменений |

Пересечений между срезами нет: S3 — `factcheck_planner`/`search_aggregator`,
VMQ — `mca_retrieval_context`/`direct_chat_service`.

## 3. Состав релиза от базы (111 файлов)

`raw/changed-files.txt`:

| Часть | Файлов | Состав |
|---|---|---|
| FCT-S3 продукт + тесты + impl-evidence | 32 | `factcheck_planner.py`, `search_aggregator.py`; `test_fc_trust_retrieval.py` (новый, 56 тестов) + **6** изменённых наборов; `fc-trust-01/evidence/fct-s3-implementation-2026-11-27/**` (23) |
| Bump 2.58.259 | 29 | `config/settings.py`, `param-registry-round1025.meta.md`, 25 test-пинов, 2 tools |
| S3 release-evidence | 18 | `fc-trust-01/evidence/release-2.58.259/**` (этот пакет) |
| **VMQ P-OLDROW** | **32** | `mca_retrieval_context.py`, `direct_chat_service.py`; `test_vmq_oldrow_person_delivery.py` (новый, 19) + **3** обновлённых ожидания; `vmq-onto-01/evidence/vmq-mem/oldrow-fix-2026-11-27/**` (26) |

Итого `886d11073..bca5563be` = **111 файлов**, DDL 0.

VMQ обновил ровно три существующих ожидания (со ссылкой на контракт, без снятия тестов):
`test_vmq_mem_slice_b.py::test_strict_row_is_not_diluted_by_weak_old_year`,
`test_vmq_mem_slice_d.py::test_a1p_historical_vs_auto`,
`test_mem_time_policy.py::test_historical_adds_period_channels_and_profile`.

## 4. Bump — version-only, набор не расширился

```
raw/bump-verify.txt
commit: baab52324943fa55e69378fe405b43f77a94e47a
changed lines: -34 / +34
pairs differing ONLY by version: 34
pairs with other changes: 0
files in commit: 29
VERSION-ONLY BUMP: OK (34 pairs / 29 files)
APP_VERSION: 2.58.259
settings_py_identical_to_bump = True
bump_set_files_touched_since_bump = []
pin_set_expanded = False
```

- Bump сделан один раз (на FCT-S3), для VMQ **не повторялся**: версия уже 2.58.259.
- `config/settings.py` байт-идентичен bump-коммиту; ни один файл пин-набора не
  менялся после bump → **набор пинов не расширился** (29 файлов / 34 вхождения).
- CRLF сохранены (3665 CRLF, 0 bare LF) — замена выполнялась побайтово.

## 5. Routes-пин — re-pin не нужен

```
raw/routes-pin.txt
routes_sha256_head = routes_sha256_base = 6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
ROUTES_SHA256_F11 = 6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
pin_matches_head = True   decision = no re-pin
```

## 6. DDL Δ = 0

```
raw/ddl-check.txt
changed files total: 111
changed DDL/schema files: []
services/database.py changed: False
services/pg_db.py changed: False
migrations/ changed: False
{"ddl_delta": 0}
```

→ миграций при деплое нет, **rollback code-only**.

## 7. Сохранение 2.58.258 (UR-BAN-02) и FCT-S3

```
raw/preservation-2.58.258.txt
direct_execution.py blob: tip = base 886d11073 = f138c7a737036a7cb30e354722019ba38d5c1cb3
                          (2.58.257 = c77f127f…)  → отличается
```
- Маркеры UR-BAN-02 на месте (`safety_steps = orchestrator_budget_for_window(...).max_steps`,
  `max_steps = explicit_steps or safety_steps`, `stop_reason="max_steps"`).
- `routes.py` и `direct_execution.py` — байт-идентичны базе.
- **FCT-S3 не затронут VMQ-переносом:** `factcheck_planner.py`/`search_aggregator.py`
  в tip = кандидат `2c811d98` (`identical=True`).

## 8. Прогоны

| Набор | Результат | Raw |
|---|---|---|
| VMQ новый модуль | **19 passed** | `vmq-tests-new.txt` |
| VMQ затронутые (11 файлов) | **211 passed, 4 failed** (все предсуществующие) | `vmq-tests-impacted.txt` |
| VMQ потребители (12 файлов: 171 + 245) | **416 passed** | `vmq-tests-consumers.txt` |
| FCT-S3 срез | **56 passed** | `tests-slice.txt` |
| FCT-S3 контрактные 12 наборов | **399 passed** | `tests-acceptance.txt` |
| S3 широкие потребители (44 файла) | **1392 passed, 2 failed** (предсуществующие) | `tests-broad-consumers.txt` |
| Пины/реестр (25 файлов) | **864 passed, 6 failed** (те же, что у 2.58.258) | `tests-pins.txt` |
| Смежные контуры (21 файл: direct/self-diag) | **635 passed, 9 failed** (предсуществующие) | `tests-adjacent.txt` |

### 8.1 Предсуществующие red-ы — 21 node id, воспроизведены на базе `886d11073`

`raw/tests-base-preexisting.txt` — на базе падают **те же** node id:

**Пины (6):** `test_mca17c_invariants_round1047.py::test_no_ddl_catalog_ks_tools_delta`,
`test_tool_coordinator_round1026.py::TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`,
`test_unified_image_request_round1026.py::{TestToolDescriptionU21::test_canon_unchanged,TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
`test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28`.

**S3-потребители (2):** `test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer`,
`test_mca20_rework1_f1_f2.py::TestValidatorStage::test_evidence_injection_stays_data_not_instructions`.

**Смежные (9):** `test_direct_context_scenarios_asap3.py::TestStaleSummary::test_lag400_middle_topk_under_pressure`,
5 × `test_direct_fallback_recompose_asap32.py::{TestGenerateChatRecompose,TestGenerateStrengthenedDiagnostics}`,
`test_direct_l1_corrective_r1.py::test_build_l1_context_bot_replies_caps_and_limit`,
2 × `test_selfdiag_corrective_research.py`.

**VMQ (4):** `test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year`,
`test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::{test_historical_plan_rebuilds_block_with_plan_scope,test_operative_plan_narrows_block,test_t16_research_plan_rebuilds_rag_block}`.

Ни один red не связан с обоими срезами; пины 2.58.259 зелёные (864 passed — как у 2.58.258).
`test_unified_reply_ur_b_search_first.py` (UR 2.58.258) — 68/68 passed.

## 9. Manifest dry-run

Снят в отдельном чистом detached-worktree на продуктовом tip `bca5563be`
(не на evidence-tip — прецедент 2.58.258). Затравка `.deploy/release.json`
описывает фактическое состояние прода: `deployed_sha=886d11073`, `version=2.58.258`.

```
raw/manifest-deploy.json
{
  "deployed_sha": "bca5563be764dd3999b0cced9011e1e945bd9c0f",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "886d11073cfdaa4646597c3a2b1ae09fde42c342",
  "previous_version": "2.58.258",
  "schema": 1,
  "version": "2.58.259"
}
```

`raw/manifest-rollback.json` — то же с `effect=rollback`; `previous_*=886d11073/2.58.258`
(откат возвращает на выложенную версию). **Rollback = code-only:** DDL Δ=0.

## 10. План выката (НЕ выполнен, для DevOps)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD          # ожидается 886d11073
git pull --ff-only                            # до tip ветки release/fct-s3-2.58.259
python tools/release_manifest.py              # effect=deploy, previous=886d11073
sudo systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz       # ожидается version 2.58.259
python manage.py disk audit && python manage.py disk cleanup --apply   # P0-PROD-DISK-01
```

После рестарта: `healthz.version=2.58.259`, `deployed_sha=<фактический HEAD>`,
`.deploy/release.json` (`previous_sha=886d11073`), ошибок схемы нет (DDL не ожидается),
свободное место.

Наблюдаемые эффекты: (S3) cross-провайдерная выдача без якоря не становится evidence
(`word_overlap_only` → `background_only` с `basis`), отсеянные кандидаты не попадают в
модельный раздел, дата несёт `published_at_source=provider`, исходы части различают
`resource_limit`/`global_deadline`/`provider_timeout`/`rate_limit`;
(VMQ) старший subject-bound период доходит до Writer и R1-резерв не замещает базовый срез.

## 11. Ограничения и честные пометки

- Деплой не выполнялся; прод не затрагивался.
- Evidence-коммит идёт отдельной поверхностью (`plans/` only): продуктовые байты от него
  не меняются, проверяется `git diff bca5563be..<final tip> -- services/ tests/` = пусто.
  Поэтому manifest снят на `bca5563be`; боевой манифест DevOps пишет по фактическому HEAD.
- **«Правки 5 существующих наборов» (S3)** — фактически **6** + 1 новый (9 путей, как в
  `index.md` §10 среза).
- **391 → 399** для S3-контракта: база 2.58.259 = 2.58.258, который добавил **+8** тестов
  в `test_unified_reply_ur_b_search_first.py` (58 против 50 на `9516c9125`; файл 68/68).
- Контракт S3 (`fct-s3-s4-contract-2026-11-27.md`) в release-ветке отсутствует — живёт
  только в docs-линии `master` (коммит `d0964e19d`); sha256 сверен через `git show`,
  совпадает. В дельту релиза не добавлялся.
- Контракт VMQ (`selector-rootcause-2026-11-27.md`) — в `vmq-onto-01/evidence/vmq-mem/**`,
  входит в 26 evidence-файлов VMQ-переноса.
- 21 предсуществующий red остаётся backlog'ом (доказано на базе).
- Модельное поведение — live-наблюдение; детерминированно доказаны коды исходов,
  типизация секции, даты, сохранение evidence и R1-резерв старшего периода.

## Артефакты

`raw/`: `identity.txt`, `changed-files.txt`, `product-delta.txt`, `routes-pin.txt`,
`ddl-check.txt`, `bump-verify.txt`, `preservation-2.58.258.txt`,
`vmq-tests-new.txt`, `vmq-tests-impacted.txt`, `vmq-tests-consumers.txt`,
`tests-slice.txt`, `tests-acceptance.txt`, `tests-broad-consumers.txt`,
`tests-pins.txt`, `tests-adjacent.txt`, `tests-base-preexisting.txt`,
`manifest-deploy.json`, `manifest-rollback.json`, `test-sets.json`, `SHA256SUMS`.
