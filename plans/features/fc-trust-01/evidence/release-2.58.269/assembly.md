# Release 2.58.269 — FC-TRUST-01 S6 U1 (схема v50: сшивка прогона, провенанс evidence, стадия deliver)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (сборка релиза + деплой)
- **Статус:** ASSEMBLED; деплой — отдельный файл `deploy-2.58.269.md`.
- **База (deployed):** `e46aa0696` = **2.58.268** (продукт `a0a34dcd3`), `user_version=49`.
- **Ветка:** `release/2.58.269` (создана от базы, worktree
  `WorkspaceData/worktrees/…/fc-trust-01-5efb63338e2a-212640ef`).
- **Reviewed-кандидат:** `fa3cb0391f53728d1b64961b34d49cf8eee9174e`,
  ветка `feat/fct-s6-u1-run-link-2026-11-28`, tip `589269b04d4b6f87620bf89110f7ac34ac000f7f`
  (после продукта — только evidence).
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s6-u1-2026-11-28/review-r1/review-r1.md`
  sha256 `e48b2abd600fc67c5b70f5bf5441d61cde8e518ca1ca091f0cc71495eba93e80` —
  **APPROVED_FOR_RELEASE_PREPARATION** (`raw/review-pin.txt`; файл живёт в master-линии,
  коммит `7074a1e43`, в дерево релиза не копировался). Блокирующих findings нет:
  B-1 (append стадии к последнему run при cooldown) и B-2 (DDL не в одной транзакции) —
  BACKLOG_ONLY, вне контракта S6-U1.

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `f4ca6dc8d` | feat(fct-s6-u1): схема v50 — `correlation_id` + индекс, провенанс evidence (`evidence_id`/`opened`/`strength`), стадия `deliver` в `stage_trace`, legacy run — **побайтово** файлы `fa3cb0391` |
| `07c345e88` | chore(release): bump 2.58.268 → 2.58.269 (version-only, 29 файлов / 34 вхождения) |

Продуктовые и тестовые файлы взяты через
`git checkout fa3cb0391 -- <files>` ⇒ блобы совпадают с кандидатом по построению;
независимо проверено по index-блобам, по коммиту кандидата, по его tip'у и по сырым байтам
(`raw/identity.txt`, `raw/identity-committed.txt`):

```
services/database.py                   idx=526377c8f78d… match=True bytes_equal=True base=1c3056db3bab…
services/temporal_factcheck.py         idx=c617cff82570… match=True bytes_equal=True base=3c5aa47f7cca…
services/factcheck_orchestrator.py     idx=7fbf0eaa67be… match=True bytes_equal=True base=15688f173fe3…
services/factcheck_service.py          idx=7590f714fc03… match=True bytes_equal=True base=6f916bb9801e…
handlers/factcheck.py                  idx=896776418664… match=True bytes_equal=True base=fbe1c7f3f6ef…
tests/test_fc_trust_s6_run_link.py     idx=1b5c061112da… match=True (новый, base absent)
tests/test_t5150_startup_migrations_round1046.py idx=b96ee6108a71… match=True bytes_equal=True base=f707509b6801…
```

`match_tip=True` для всех семи ⇒ файлы не менялись после ревью.

## 1. Продуктовый диф — ровно 5 продуктовых файлов + 2 теста

| Файл | Δ | index blob (= кандидат) |
|---|---|---|
| `services/database.py` | +123/−9 | `526377c8f78d…` True |
| `services/temporal_factcheck.py` | +72/−2 | `c617cff82570…` True |
| `services/factcheck_orchestrator.py` | +23/−3 | `7fbf0eaa67be…` True |
| `services/factcheck_service.py` | +6/−0 | `7590f714fc03…` True |
| `handlers/factcheck.py` | +4/−0 | `896776418664…` True |
| `tests/test_fc_trust_s6_run_link.py` (новый) | +334/−0 | `1b5c061112da…` True |
| `tests/test_t5150_startup_migrations_round1046.py` | +2/−1 | `b96ee6108a71…` True |

`raw/product-delta.txt`: `changed_files_total_vs_base=36`,
`outside_product_tests_and_bump_files=(none)`, `bump_touched_files=29`.
Полный диф — `raw/product-diff-full.txt`. Других продуктовых изменений нет.

Единственная правка существующего теста — ожидание числа индексов
`idx_mca_factcheck%` 3 → 4 (добавлен индекс v50); это прямое следствие миграции,
само поведение не ослаблено.

## 2. Канон промптов и сиды не изменены

`services/factcheck_prompts.py`: sha256 `4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4`
(= канон), блоб `64bb06c05fc7…` одинаков у кандидата и базы ⇒ файл не тронут
(`raw/identity.txt`, `raw/identity-committed.txt`).
`services/param_catalog.py` не менялся ⇒ новых сидов нет;
`tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 668 == REGISTRY**
(`raw/registry-check.txt`). Ожидаемое число строк PG `bot_settings` — **558 без изменений**.

## 3. Bump 2.58.268 → 2.58.269 — version-only

`raw/bump-verify.txt`:

```
files=29 occurrences_replaced=34
skipped_no_occurrence=(none)
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
remaining_old_occurrences=0
APP_VERSION_lines=['APP_VERSION = "2.58.269"   # (27.11.2026): …']
config/settings.py: occurrences=1 crlf=3665 bare_lf=0 size_before=362807 size_after=362807
```

Набор из 29 путей идентичен предыдущим bump'ам (`raw/_bump.py` берёт его из bump-коммита
`9c45a454c`); EOL (CRLF в `config/settings.py`, 3665) и размеры файлов не изменились.
Исторические evidence-каталоги `release-2.58.26x/` намеренно не бомпались.

## 4. Схема: v49 ⇒ v50 — аддитивная миграция, DDL Δ = 1 шаг

`raw/ddl-check.txt` (тело миграции разобрано `ast`, докстринг с rollback-SQL не считается
исполняемым DDL):

```
migrations_or_db_py_changed=['services/database.py']
max_schema_constant=50 constants=49
run_link_constant_present=True
migration_step_present=True                       # factcheck_run_link_v50
migration_referenced_constants:
  _FACTCHECK_RUN_LINK_COLUMNS=(('correlation_id','TEXT'),)
  _FACTCHECK_EVIDENCE_LINK_COLUMNS=(('evidence_id','TEXT'),('opened','INTEGER'),('strength','TEXT'))
  _MCA_FACTCHECK_RUN_CORRELATION_INDEX_DDL=CREATE INDEX IF NOT EXISTS idx_mca_factcheck_runs_correlation ON mca_factcheck_runs(correlation_id)
migration_body_executed_statements:
  ALTER TABLE mca_factcheck_runs ADD COLUMN {name} {decl}
  CREATE INDEX IF NOT EXISTS idx_mca_factcheck_runs_correlation …
  ALTER TABLE mca_factcheck_evidence ADD COLUMN {name} {decl}
  PRAGMA user_version = 50
legacy_rows_untouched_no_update_delete=True
backfill_statements=(none)
schema_migrations_rows_only_added_no_delete=True
```

- Только `ADD COLUMN` (nullable, без DEFAULT), `CREATE INDEX IF NOT EXISTS` и `PRAGMA user_version`.
  Нет `UPDATE`/`DELETE`/backfill существующих строк; `relation` уже существует с v33.
- Идемпотентно: guard по `PRAGMA table_info` + `IF NOT EXISTS`; повторный старт — no-op
  (`test_t5150_startup_migrations_round1046` покрывает повтор и cold-revert).
- Версия фиксируется после `commit()` DDL; `schema_migrations` получает один ряд v50
  (`factcheck_run_link_v50`), удаления рядов нет.
- `database.py` — SQLite-only runner (`PRAGMA user_version`); PG-эквивалента для
  `mca_factcheck_runs`/`mca_factcheck_evidence` в проекте нет (grep по `mca_factcheck_runs`:
  `database.py`, `mca_process_registry.py`, `module_registry.py` — все SQLite-пути).

**Rollback-SQL (ручной, v50 ⇒ v49), та же формулировка, что в докстринге миграции:**

```sql
DROP INDEX IF EXISTS idx_mca_factcheck_runs_correlation;
ALTER TABLE mca_factcheck_runs DROP COLUMN correlation_id;
ALTER TABLE mca_factcheck_evidence DROP COLUMN evidence_id;
ALTER TABLE mca_factcheck_evidence DROP COLUMN opened;
ALTER TABLE mca_factcheck_evidence DROP COLUMN strength;
PRAGMA user_version = 49;
```

Локальный прогон этого SQL на пробной БД (не продукт), SQLite `3.42.0` —
`raw/rollback-probe-local.txt`: форма v50 → v49, индекс удалён, старые `SELECT` работают,
данные строк сохранены, `integrity_check=ok`, `quick_check=ok`, temp-БД удалена.
Код 2.58.268 совместим с v50 (все колонки nullable, старый код их не читает) ⇒
**rollback кода = code-only**, откат схемы не обязателен.

## 5. Routes-пин не менялся

`raw/ddl-check.txt`:

```
web/api/routes.py_sha256 = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_pin_b8f63355 = True
web/app.js_sha256 = 3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a
routes_or_appjs_in_diff = (none)
```

## 6. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `test_fc_trust_s6_run_link` + `test_t5150_startup_migrations_round1046` + `test_fc_trust_s5_writer` + `test_fc_trust_verdict` + `test_factcheck_p0_fc` | **83 passed**, 1 warning (`duckduckgo_search` rename, pre-existing) — 24.84 s | `tests-fct.txt` |
| `test_fc_trust_s6_run_link` отдельно | **7 passed** — 4.13 s | `tests-s6-run-link-only.txt` |
| Пины: `test_round1025_f8_registry` + `test_webapp_f11_round1025` + `test_mca23_planned_vs_actual` | **86 passed** — 5.55 s | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |
| локальный rollback-probe (SQLite 3.42.0) | v50 → v49, старые SELECT ок, integrity/quick ok | `rollback-probe-local.txt` |

## 7. Манифест

`raw/manifest-dryrun.txt` — dry-run `tools/release_manifest.py --dry-run` на bump-коммите;
фактический `deployed_sha` фиксируется на проде при деплое (файл `.deploy/release.json`
пишется только на проде, в работе `Test-Path .deploy/release.json` = False):

```json
{ "deployed_at": "2026-11-28T03:56:22.657247Z", "deployed_sha": "07c345e8856f09c6dae99a0d062d32ba2efacf82",
  "deployer": "devops", "dirty_tracked": false, "effect": "deploy",
  "previous_sha": null, "previous_version": null,
  "release_branch": "release/2.58.269", "schema": 1, "version": "2.58.269" }
```

`previous_*` = `null` только потому, что локальный worktree не содержит `.deploy/release.json`.
На проде previous берётся из рабочего манифеста ⇒ `e46aa0696` / 2.58.268;
`deployed_sha` = фактический HEAD; `dirty_tracked=false`.

## 8. Ограничения

- Тесты на проде не запускаются; live-проверки и проверка обратимости на копии прод-БД —
  в `deploy-2.58.269.md`.
- Строки FCT-901/902/904 остаются REVIEW до фактической проверки на проде (миграция и
  запись correlation/deliver наблюдаются в `deploy-2.58.269.md`); FCT-903 — PENDING (S6-U2).
- B-1/B-2 ревью (BACKLOG_ONLY) в релиз не входят.

## 9. Идентичность на коммите релиза (не только в index)

`raw/identity-committed.txt` — блобы из **закоммиченного дерева**
(`head=07c345e8856f09c6dae99a0d062d32ba2efacf82`): у всех семи файлов
`head_blob == candidate_blob`, `committed_bytes_equal_worktree=True`;
`factcheck_prompts.py` `unchanged_vs_base=True`.
Коммит с этим разделом (`docs(release)`) не трогает продуктовые файлы — только
`plans/features/fc-trust-01/evidence/release-2.58.269/**` ⇒ байтовая идентичность сохраняется
в задеплоенном дереве.

## Приложения

`raw/`: `identity.txt`, `identity-committed.txt`, `product-delta.txt`, `product-diff-full.txt`,
`changed-files-preassembly.txt`, `bump-verify.txt`, `ddl-check.txt`, `registry-check.txt`,
`review-pin.txt`, `manifest-dryrun.txt`, `rollback-probe-local.txt`, `tests-fct.txt`,
`tests-s6-run-link-only.txt`, `tests-pins.txt`, `SHA256SUMS`.
Скрипты сборки: `raw/_identity.py`, `raw/_identity_committed.py`, `raw/_bump.py`,
`raw/_assembly_artefacts.py`, `raw/_ddl_check.py`, `raw/_rollback_probe.py`, `raw/_sums.py`.
