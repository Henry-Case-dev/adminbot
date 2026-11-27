# Release 2.58.264 — FC-TRUST-01 S1 (FCT-112 VERIFIED, FCT-113 REVIEW)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (сборка релиза + деплой)
- **Статус:** ASSEMBLED (сборка); деплой — отдельный файл `deploy-2.58.264.md`.
- **База (deployed):** `4cdd72e17ef418c3901497dcce717d53bda1a62f` = **2.58.263** (release/2.58.263),
  продуктовый tip базы `ed935443e`.
- **Ветка:** `release/2.58.264` (создана от базы).
- **Reviewed-кандидат (продукт):** `c55b0ddb4ac4ec17ecb1acb195557bb9919f5142`,
  ветка `fix/fct-s1-contract-gaps-2026-11-28`, tip `b614f3fdb`.
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s1-gaps-2026-11-28/review-r2/review-r2.md`
  sha256 `80fba406…` — **APPROVED_FOR_RELEASE_PREPARATION** (RV-S1-01 закрыт; R1 `56e3d1240`).

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `0118dc081` | feat(fct-112,fct-113): поля части ClaimUnit + единая ось `assertion_kind` в `<claim_parts>`/verdict; литеральные anchor-rows тесты — **побайтово** файлы `c55b0ddb4` |
| `c531aab1e` | chore(release): bump 2.58.263 → 2.58.264 (version-only, 29 файлов / 34 вхождения) |

Продуктовые файлы взяты через `git checkout c55b0ddb4 -- <files>` ⇒ блобы совпадают с кандидатом
по построению, независимо проверено по index-блобам (`raw/identity.txt`).

## 1. Продуктовый диф — 3 файла, 348+/25−, ровно кандидат

| Файл | HEAD blob | = кандидат | base blob | Δ |
|---|---|---|---|---|
| `services/factcheck_planner.py` | `b143e4a7713c…` | True | `2ba5df49e40d…` | +256/−23 |
| `services/factcheck_service.py` | `12c74ebc578e…` | True | `3e056460162e…` | +83/−1 |
| `services/factcheck_orchestrator.py` | `485bbe38cef2…` | True | `d1a4567f026c…` | +9/−1 |
| `tests/test_fc_trust_s1_contract.py` (новый) | `5d5affc9ef6b…` | True | — (нет в базе) | +403/−0 |

Итого `348+/25−` в `services/` (25 удалённых строк — только замены, новых удалений поведения нет),
+403 строка теста. `git diff --stat c55b0ddb4 -- ':(exclude)plans'` пуст ⇒ **других продуктовых
изменений нет** (`raw/product-delta.txt`, `raw/product-diff-full.txt`, `raw/identity.txt`).

## 2. Полный delta релиза (продукт + тест + bump)

`raw/changed-files-preassembly.txt`; после bump: `33 файла, 785+/59−`
(751+/25− продукт+тест, 34+/34− version-only bump).

## 3. Bump 2.58.263 → 2.58.264 — version-only

`raw/bump-verify.txt`:

```
files=29  additions=34  deletions=34
removed_lines=34  added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
pairs_differing_only_by_version=34/34
config/settings.py: crlf=3665 bare_lf=0 size=362807 (EOL и размер как в базе)
APP_VERSION = "2.58.264"   (единственная изменённая строка settings.py; 1/1)
```

Набор из 29 путей идентичен предыдущему bump (`config/settings.py`, `plans/docs/param-registry-round1025.meta.md`,
25 тестов, 2 tools). Исторические evidence-файлы `release-2.58.263/` (13 вхождений в 3 файлах)
намеренно не бомпались.

## 4. DDL = 0, `user_version` 49 ⇒ rollback code-only

`raw/ddl-check.txt`: изменённых миграций/`services/database.py`/`services/pg_db.py` — 0;
DDL-строк в диффе `services/config/web/handlers` — 0; `max_schema_constant=49`; `ddl_delta=0`.

## 5. Seed: новых настроек нет

`raw/seed-factcheck.txt`: `services/param_catalog.py` не менялся (blob `d4b0a884c738…` = база),
дифф 0 строк, новых `limits.factcheck_*` нет. `tools/gen_param_registry_round1025.py --check` →
`CHECK OK: реестр 668 == REGISTRY`. Ожидаемое число строк PG `bot_settings` — **558 без изменений**
(заводские значения и сохранённые пользовательские настройки не затрагиваются).

## 6. Routes-пин не менялся

`raw/routes-pin.txt`:

```
routes_sha256_head = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_blob_head   = a851e4f857b13ea1851ebfcc00aec940b867a896 (= base = candidate)
ROUTES_SHA256_pin_matches_head = True
```

## 7. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `tests/test_fc_trust_s1_contract.py` | **27 passed** (5.04 s) | `tests-s1-contract.txt` |
| `test_fc_trust_retrieval` + `test_fc_trust_target` + `test_factcheck_p0_fc` + `test_factcheck_context_cfg06` + `test_factcheck_post_release_w1` | **191 passed**, 1 warning (`duckduckgo_search` rename, pre-existing) | `tests-core.txt` |
| Пины: `test_webapp_f11_round1025` + `test_round1025_f8_registry` | **62 passed** | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

27 и 191 совпадают с GREEN независимого Reviewer на том же кандидате.

## 8. Манифест

`raw/manifest-dryrun.txt` — dry-run со stub «текущий прод = `4cdd72e17` / 2.58.263»
(stub удалён, `.deploy/` в worktree отсутствует):

```json
{ "deployed_sha": "c531aab1ee7b…", "version": "2.58.264", "effect": "deploy",
  "previous_sha": "4cdd72e17ef41…", "previous_version": "2.58.263",
  "release_branch": "release/2.58.264", "dirty_tracked": false, "schema": 1 }
```

На проде манифест пишется штатным `tools/release_manifest.py` после checkout ⇒
`deployed_sha` = фактический HEAD (assembly-коммит), `previous` = `4cdd72e17` / 2.58.263,
`dirty_tracked=false`. **Rollback = code-only** (DDL Δ=0, схема v49).

## 9. Ограничения

- FCT-113 остаётся REVIEW (структурная ось закрыта; семантика `decision_status`/`normative_state_on_date` — S4), по ревью.
- B-1 (plan-level `assertion_kind` для mixed/caption) — BACKLOG_ONLY, в этот релиз не входит.
- Тесты на проде не запускаются; live-проверки — в `deploy-2.58.264.md`.

## Приложения

`raw/`: `identity.txt`, `product-delta.txt`, `product-diff-full.txt`, `changed-files-preassembly.txt`,
`bump-verify.txt`, `ddl-check.txt`, `seed-factcheck.txt`, `routes-pin.txt`, `tests-s1-contract.txt`,
`tests-core.txt`, `tests-pins.txt`, `registry-check.txt`, `manifest-dryrun.txt`, `SHA256SUMS`.
