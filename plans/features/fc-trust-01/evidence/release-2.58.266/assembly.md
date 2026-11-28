# Release 2.58.266 — FC-TRUST-01 S4 U1 (FCT-501 VERIFIED, FCT-023/702 REVIEW)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (сборка релиза + деплой)
- **Статус:** ASSEMBLED; деплой — отдельный файл `deploy-2.58.266.md`.
- **База (deployed):** `55178d5bd1c7f21f2c4966195df7cb7a93096503` = **2.58.265**,
  продуктовый tip базы `6ab3b718a`.
- **Ветка:** `release/2.58.266` (создана от базы).
- **Reviewed-кандидат (продукт):** `282151269852c57c916e8fd26f2bffd00747fad8`,
  ветка `feat/fct-s4-u1-evidence-2026-11-28`, tip `d5e1247cb` (после продукта — только evidence).
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s4-u1-2026-11-28/review-r2/review-r2.md`
  sha256 `15b01429613e2cbfdb11d0f297ea105fda45fd254d4a32306f6185770dcb75b2` —
  **APPROVED_FOR_RELEASE_PREPARATION** (RV-S4U1-01/02 закрыты, R1 `a0ae1ba05`).
  Implementation evidence того же кандидата: `.../fct-s4-u1-2026-11-28/implementation.md`
  sha256 `af23ff9bb93bb1c7622c15d7bdc86e0061e43ff5bfd3af43d5c34acfafccf1c8`.
  Оба файла живут в master-линии (`9e8e3d2f6`, `6304a8558`) и на ветке кандидата; в дерево
  релиза они не копировались (дубль не создавался).

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `7d4ab2f00` | feat(fct-023,fct-501,fct-702): ось `publication_kind` (D2), раздельные временные поля с «unknown never now», per-part флаг `unverified_media`; демоция non-direct публикации на открытой странице с note; убран ложный `news/YYYY` press-путь — **побайтово** файлы `282151269` |
| `9ffa54954` | chore(release): bump 2.58.265 → 2.58.266 (version-only, 29 файлов / 34 вхождения) |

Продуктовые файлы взяты через `git checkout 282151269 -- <files>` ⇒ блобы совпадают
с кандидатом по построению, независимо проверено по index-блобам (`raw/identity.txt`).

## 1. Продуктовый диф — 5 файлов + новый тест, 750+/18−, ровно кандидат

| Файл | index blob (= кандидат) | base blob | Δ |
|---|---|---|---|
| `services/factcheck_planner.py` | `1fdc8333544a…` True | `db1e73341020…` | +206/−12 |
| `services/search_aggregator.py` | `cba937d970b0…` True | `9a708f2c4def…` | +72/−0 |
| `services/temporal_factcheck.py` | `3c5aa47f7cca…` True | `4c94fa03eefc…` | +35/−5 |
| `services/factcheck_orchestrator.py` | `54c9e3004dfd…` True | `8db1e41fece0…` | +37/−1 |
| `services/factcheck_service.py` | `64cedab6a708…` True | `e06c6afb9c83…` | +3/−0 |
| `tests/test_fc_trust_s4_evidence.py` (новый) | `28eeb7d99e37…` True | — (нет в базе) | +397/−0 |

`raw/product-delta.txt`: вне перечисленных 6 файлов продуктовых изменений нет
(`product_files_changed=6`, `outside_product=(none)`). `raw/product-diff-full.txt` — полный диф
`55178d5bd..282151269` по этим файлам.

## 2. Полный delta релиза (продукт + тест + bump)

`raw/changed-files-preassembly.txt`: `git diff --stat 55178d5bd HEAD` = **35 файлов, 784+/52−**
(750+/18− продукт+тест, 34+/34− version-only bump).

## 3. Bump 2.58.265 → 2.58.266 — version-only

`raw/bump-verify.txt`:

```
files=29 occurrences_replaced=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
remaining_old_occurrences=0
APP_VERSION_lines=['APP_VERSION = "2.58.266"   # (27.11.2026): …']
config/settings.py: occurrences=1 crlf=3665 bare_lf=0 size_before=362807 size_after=362807
```

Набор из 29 путей идентичен предыдущим bump'ам (`config/settings.py`,
`plans/docs/param-registry-round1025.meta.md`, 25 тестов, 2 tools); EOL и размер settings.py
не изменились. Исторические evidence-каталоги `release-2.58.26x/` намеренно не бомпались.

## 4. DDL = 0, `user_version` 49 ⇒ rollback code-only

`raw/ddl-check.txt`: `migrations_or_db_py_changed=(none)`; `ddl_delta_lines=0`;
`max_schema_constant=49` (`services/database.py: _SCHEMA_VERSION_SELF_DIAG_SAMPLES`).

## 5. Seed: новых настроек нет

`raw/seed-factcheck.txt`: `services/param_catalog.py` не менялся
(blob `d4b0a884c738f5e2c18d94c518c7398e731dec36` = база, `same=True`), новых `factcheck`-лимитов 0;
`tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 668 == REGISTRY**
(`raw/registry-check.txt`). Ожидаемое число строк PG `bot_settings` — **558 без изменений**.

## 6. Routes-пин не менялся

`raw/routes-pin.txt`:

```
routes_sha256_head = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_blob_head   = a851e4f857b1… (= base; routes_changed=(none))
pin_matches_b8f63355 = True
```

## 7. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `test_fc_trust_s4_evidence` + `test_fc_trust_verdict` + `test_fc_trust_s1_contract` | **82 passed** (8.63 s) | `tests-s4-verdict-s1.txt` |
| `test_fc_trust_retrieval` + `test_fc_trust_target` + `test_factcheck_p0_fc` + `test_factcheck_context_cfg06` + `test_factcheck_post_release_w1` | **191 passed**, 1 warning (`duckduckgo_search` rename, pre-existing) | `tests-core.txt` |
| Пины: `test_webapp_f11_round1025` + `test_round1025_f8_registry` | **62 passed** (4.27 s) | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

82 включает новые 31 проверки S4 U1 (совпадает с прогоном Reviewer на том же кандидате: 55
в паре s4+verdict, 123 в retrieval/p0/cfg06).

## 8. Манифест

`raw/manifest-dryrun.txt` — dry-run на bump-коммите (`deployed_sha` = `9ffa54954`, факт
evidence-коммита фиксируется при деплое):

```json
{ "deployed_at": "2026-11-28T01:01:46.962184Z", "deployed_sha": "9ffa5495440b…",
  "deployer": "devops", "dirty_tracked": false, "effect": "deploy",
  "previous_sha": "55178d5bd1c7f…", "previous_version": "2.58.265",
  "release_branch": "release/2.58.266", "schema": 1, "version": "2.58.266" }
```

На проде манифест пишется после checkout ⇒ `deployed_sha` = фактический HEAD, `previous` =
`55178d5bd` / 2.58.265, `dirty_tracked=false`. **Rollback = code-only** (DDL Δ=0, схема v49).

## 9. Ограничения

- FCT-023/702 остаются REVIEW по ревью (русские подписи формы публикации — U3; B-1 `/article/`
  → `journal_article` — BACKLOG_ONLY, в релиз не входит).
- Тесты на проде не запускаются; live-проверки — в `deploy-2.58.266.md`.

## Приложения

`raw/`: `identity.txt`, `product-delta.txt`, `product-diff-full.txt`,
`changed-files-preassembly.txt`, `bump-verify.txt`, `ddl-check.txt`,
`seed-factcheck.txt`, `routes-pin.txt`, `tests-s4-verdict-s1.txt`, `tests-core.txt`,
`tests-pins.txt`, `registry-check.txt`, `manifest-dryrun.txt`, `SHA256SUMS`.
Скрипты сборки: `raw/_bump.py`, `raw/_checks.py`, `raw/_assembly_artefacts.py`