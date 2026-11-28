# Release 2.58.271 — FC-TRUST S6-U2: сводные показатели прогонов (только вычисление)

- **Дата сборки:** 2026-11-28.
- **Роль:** DevOps (сборка релиза + деплой).
- **База (deployed):** `438ad790e` = **2.58.270** (продукт `e30ae12bf`), `user_version=50`.
- **Ветка:** `release/2.58.271` от базы, worktree
  `WorkspaceData/worktrees/…/release-2-58-271-b8bb902573bf-569529ef`.
- **Reviewed-кандидат:** продукт `936bc31a76971e47e7f101bcddc1e7656d7c7270`,
  ветка `feat/fct-s6-u2-aggregates-2026-11-28`, tip `199405d29` (после продукта — только evidence).
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s6-u2-2026-11-28/review-r1/review-r1.md`
  sha256 `56573ea6fab85e89033c503aa8c8a6398a1473801e775a59bcc0923b37b86498` —
  **APPROVED_FOR_RELEASE_PREPARATION**. Файл живёт в master-линии; в дерево релиза не копировался
  (`raw/review-pin.txt`).

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `b6132a81b` | feat(fct-s6-u2): read-only агрегаты прогонов фактчека; **побайтово** файлы `936bc31a7` |
| `8578ebe17` | chore(release): bump 2.58.270 → 2.58.271 (version-only, 29 файлов / 34 вхождения) |

Файлы взяты через `git checkout 936bc31a7 -- <files>` ⇒ блобы совпадают с кандидатом по
построению; независимо проверено по index-блобам, по коммиту кандидата и по сырым байтам
(`raw/identity.txt`):

```
services/temporal_factcheck.py        worktree_blob=582a2efb48a1… candidate_blob=582a2efb48a1… base_blob=c617cff82570…
tests/test_fc_trust_s6_aggregates.py  worktree_blob=6643c50faea1… candidate_blob=6643c50faea1… base_blob=(absent)
all_product_files_byte_identical_to_candidate=True
```

sha256: `temporal_factcheck.py` = `5231d6b8238f5b173ff1adca16f81d1874b50b244a8da452a6da32254de29f37`
(101 574 B), тест = `18774e3c332b1d7c50101c636145ff5e3e65ab91bbc1603eb5109766412df62b` (9 914 B).

## 1. Продуктовый диф — ровно 2 продуктовых файла

`raw/product-delta.txt` / `raw/product-diff-stat.txt`:

```
M	services/temporal_factcheck.py        (+236)
A	tests/test_fc_trust_s6_aggregates.py  (+220)
2 files changed, 456 insertions(+)
```

Содержимое: `aggregate_factcheck_snapshots(...)` (чистая функция над уже прочитанными
строками) и `async def summarize_factcheck_aggregates(db, …)` — только SELECT'ы по
`pipeline_runs` / `factcheck_claims` / событиям; INSERT/UPDATE/DELETE/CREATE/commit в дельте 0
(`git diff … | Select-String "INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|commit("` → пусто, кроме
`order by`/`created_at`). `IMPORT_OK` подтверждён на собранном дереве.

## 2. DDL 0 — схема остаётся v50

`raw/identity.txt`: `ddl_or_migration_paths=none`; `services/database.py`, `services/param_catalog.py`
и `migrations/` не тронуты. Миграции не запускаются; на проде `user_version` должен остаться **50**.
Новых флагов/сидов/LLM-вызовов/эндпоинтов нет.

## 3. Bump 2.58.270 → 2.58.271 — version-only

`raw/bump-verify.txt`:

```
files_in_canonical_set=29 files_changed=29 occurrences_replaced=34
skipped_no_occurrence=(none)
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
remaining_old_occurrences=0 new_occurrences=34
crlf_total=3665 bare_lf_total=15441
APP_VERSION_lines=['APP_VERSION = "2.58.271"   # …']
config/settings.py: occurrences=1 crlf=3665 bare_lf=0 size_before=362807 size_after=362807
```

Набор 29 путей — тот же канонический bump-set, что у `3eafef83c` (269→270) и `07c345e88`
(268→269), списки совпадают побайтово по именам. EOL `config/settings.py` (CRLF, 3665) и размеры
файлов не изменились. Исторические evidence-каталоги `release-2.58.26x/` намеренно не бомпались.

## 4. Routes-пин, бандл и промпты не менялись

```
web/api/routes.py              sha256 = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a  (== base)
web/app.js                     sha256 = 3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a  (== base)
services/factcheck_prompts.py  sha256 = 4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4  (== base)
web/ в диффе base..HEAD = 0 файлов
```

## 5. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `test_fc_trust_s6_aggregates` + `test_fc_trust_s6_run_link` + `test_fc_trust_verdict` + `test_factcheck_p0_fc` | **77 passed**, 1 warning (pre-existing ddgs rename) — 15.27 s | `tests-fct.txt` |
| Пины: `test_round1025_f8_registry` + `test_webapp_f11_round1025` + `test_mca23_planned_vs_actual` | **86 passed** — 6.66 s | `tests-pins.txt` |
| `test_fc_trust_s6_aggregates.py` отдельно | **9 passed** — 3.59 s | (в `tests-fct.txt` есть полный прогон) |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |
| `import services.temporal_factcheck` | **IMPORT_OK** | — |

## 6. Манифест

`raw/manifest-dryrun.txt` — прогон `tools/release_manifest.py --dry-run` на собранном дереве
до evidence-коммитов; `previous_sha`/`previous_version` на проде подставляются из фактического
`.deploy/release.json` (ожидается `438ad790e…` / `2.58.270`), `deployed_sha` на проде =
фактический HEAD после evidence-коммитов. `dirty_tracked=false`.

## 7. Байтовая идентичность блобов на прод-кандидате

После evidence-коммитов продукт-блобы не меняются:
`services/temporal_factcheck.py` = `582a2efb48a1…`,
`tests/test_fc_trust_s6_aggregates.py` = `6643c50faea1…` (`raw/identity-committed.txt`).
Проверка на проде — `git rev-parse HEAD:<path>` (см. deploy evidence).

## 8. Откат

DDL Δ=0, единственная продуктовая дельта — `temporal_factcheck.py` ⇒ **code-only откат** к
`438ad790e` (`git checkout --detach 438ad790e` + restart). Код 2.58.270 совместим со схемой v50.
Dry-run манифеста отката — в deploy evidence.
