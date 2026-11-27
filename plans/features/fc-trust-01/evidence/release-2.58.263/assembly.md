# Release 2.58.263 — FC-TRUST-01 S3/S2 (FCT-301, FCT-303, FCT-013, FCT-314)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (сборка релиза + деплой)
- **Статус:** ASSEMBLED (сборка); деплой — отдельный файл `deploy-2.58.263.md`.
- **База (deployed):** `c0db22aa957da51ea39e75b24de3e0dbdc8c1509` = **2.58.262** (release/2.58.262).
- **Ветка:** `release/2.58.263` (создана от базы)
- **Tip продукта (bump):** `ed935443e587405d9e14425505d6f4f6b14b7e86`
- **Reviewed-кандидат:** `a50bcaf6ab394d66de40513e64525a748b8729a3`, ветка `fix/fct-s3-retrieval-2026-11-28`, tip `21d44458a`.
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s3-retrieval-remaining-2026-11-28/review-r1/review-r1.md`
  sha256 `216d1d76cd4c504d40749734687b259cff2f8b6cd44ff5a0e78f175a94cf4814` — APPROVED_FOR_RELEASE_PREPARATION.

## 0. Состав — 5 reviewed-коммитов + bump

| Новый коммит | Исходный | Содержание |
|---|---|---|
| `f238e0a1e` | `181e2cabc` | fix(fct-301): run-level retrieval class из закрытого stop_reason |
| `8f5811360` | `67d089e14` | fix(fct-013): сняты скрытые потолки частей тезиса и доказательств |
| `4b391b1ff` | `a994d9dde` | fix(fct-314): названное усечение окна/дайджеста/reply-цепочки |
| `23589653a` | `9ba0f7b7d` | feat(fct-303): 9 owner-параметров `limits.factcheck_*` в каталог |
| `81bd15777` | `a50bcaf6a` | test(fct-301): публичный текст при rate limit |
| `ed935443e` | — | chore(release): bump 2.58.262 → 2.58.263 |

`git cherry-pick -x` без конфликтов: рабочее дерево после 5 коммитов **побайтово равно**
reviewed-кандидату (`git diff a50bcaf6a HEAD` пуст, tree `609f8151960846ee8dd5f4da3bbed24b86546156`).

## 1. Продуктовый диф — 4 файла, 239+/22−, ровно кандидат

`raw/identity.txt`, `raw/product-delta.txt`, `raw/product-diff-full.txt`.

| Файл | HEAD blob | = кандидат | base blob | Δ |
|---|---|---|---|---|
| `services/factcheck_service.py` | `3e056460162e…` | True | `7058327d914f…` | +129/−10 |
| `services/factcheck_context.py` | `f7bbe5991c91…` | True | `aa4e52b8aa3d…` | +44/−10 |
| `services/param_catalog.py` | `d4b0a884c738…` | True | `2ffce87a15d9…` | +63/−0 |
| `services/factcheck_planner.py` | `2ba5df49e40d…` | True | `3099bd9c30c8…` | +3/−2 (только комментарий) |

Итого `239+/22−`. `services/factcheck_orchestrator.py`, `safe_fetch.py`, `web/`, `handlers/`,
`config/`, миграции — **0 изменений**.

## 2. Полный delta релиза (продукт + тесты/фикстуры/реестр/bump)

`raw/changed-files.txt`, `git diff c0db22aa9..HEAD --stat`.

- до bump: 70 файлов, `1034+/121−` — ровно состав reviewed-кандидата (4 продуктовых,
  тесты `test_fc_trust_retrieval.py`, `test_factcheck_p0_fc.py`, `test_factcheck_context_cfg06.py`,
  `test_factcheck_post_release_w1.py`, `test_param_catalog.py`, фикстуры round1025,
  `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`,
  `tools/_fct303_reissue_*.py`, обновления version-pin тестов);
- после bump: 78 файлов, `1068+/155−`.

Иных продуктовых изменений нет: `git diff c0db22aa9 HEAD --stat` содержит только перечисленное.

## 3. Bump 2.58.262 → 2.58.263 — version-only

`raw/bump-verify.txt`.

```
files=29  additions=34  deletions=34
removed_lines=34  added_lines=34
all_removed_map_to_added_by_version=True   (каждая −строка +2.58.263 == соответствующая +строка)
non_version_changed_pairs=0
config/settings.py: crlf=3665 bare_lf=0 size=362807 (размер и EOL как в базе)
APP_VERSION = "2.58.263"
```

Набор файлов идентичен предыдущему bump (29 путей: `config/settings.py`,
`plans/docs/param-registry-round1025.meta.md`, 25 тестов, 2 tools).

## 4. DDL = 0, `user_version` 49 ⇒ rollback code-only

`raw/ddl-check.txt`: изменённых миграций/`services/database.py`/`services/pg_db.py` — 0,
DDL-ключевых добавленных строк в `services/` — 0, `max_schema_constant=49`, `ddl_delta=0`.

## 5. Seed: 9 новых owner-параметров фактчека

`raw/seed-factcheck.txt`: `_FACTCHECK_RETRIEVAL_PG_ONLY` = 9 ключей `limits.factcheck_*`
(retrieval_seconds, retrieval_seconds_max, refine_calls, max_queries_total, search_text_chars,
page_size, claim_portion, primary_fetches, excerpt_chars), все с `code_source`
`services.factcheck_planner.FACTCHECK_*` (заводские значения — код-канон, без новых гейтов).
PG-only ⇒ при первом старте сид добавляет 9 строк `bot_settings`; ожидаемое изменение
счётчика настроек 549 → 558 (факт фиксируется в deploy-файле).

## 6. Routes-пин не менялся

`raw/routes-pin.txt`:

```
routes_sha256_head = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
ROUTES_SHA256_F11  = b8f63355495c…  pin_matches_head=True
routes_blob_head   = a851e4f857b13ea1851ebfcc00aec940b867a896 (= base, = reviewed)
routes_changed_in_release=False
```

## 7. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `test_fc_trust_retrieval.py` + `test_factcheck_p0_fc.py` + `test_factcheck_context_cfg06.py` + `test_factcheck_post_release_w1.py` + `test_param_catalog.py` | **201 passed**, 1 warning (`duckduckgo_search` rename) | `tests-core.txt` |
| Пины: `test_round1025_f8_registry.py` + `test_webapp_f11_round1025.py` | **62 passed** | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

201 passed совпадает с GREEN независимого Reviewer (201 passed) на том же кандидате.

## 8. Манифест (dry-run, не деплой)

`raw/manifest-dryrun.txt` — с временным stub «текущий прод = c0db22aa9 / 2.58.262»
(stub удалён, `.deploy/` в worktree отсутствует):

```json
{ "deployed_sha": "ed935443e587405d9e14425505d6f4f6b14b7e86",
  "version": "2.58.263", "effect": "deploy",
  "previous_sha": "c0db22aa957da51ea39e75b24de3e0dbdc8c1509",
  "previous_version": "2.58.262",
  "release_branch": "release/2.58.263",
  "dirty_tracked": false, "schema": 1 }
```

**Rollback = code-only** (DDL Δ=0, схема v49).

## 9. Ограничения

- FCT-192 остаётся REVIEW (S4 residual) — вне этого релиза, по ревью.
- Тесты не запускаются на проде; live-проверки — в `deploy-2.58.263.md`.

## Приложения

`raw/`: `identity.txt`, `changed-files.txt`, `product-delta.txt`, `product-diff-full.txt`,
`bump-verify.txt`, `ddl-check.txt`, `seed-factcheck.txt`, `routes-pin.txt`,
`tests-core.txt`, `tests-pins.txt`, `registry-check.txt`, `manifest-dryrun.txt`, `SHA256SUMS`.
