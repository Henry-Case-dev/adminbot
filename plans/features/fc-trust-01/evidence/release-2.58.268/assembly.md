# Release 2.58.268 — FC-TRUST-01 S5 U1 (даты доказательств в тексте Writer)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (сборка релиза + деплой)
- **Статус:** ASSEMBLED; деплой — отдельный файл `deploy-2.58.268.md`.
- **База (deployed):** `9709b14af6d87a9de18a53825542f7c60c2ffe1f` = **2.58.267** (продукт `718fe0a82`).
- **Ветка:** `release/2.58.268` (создана от базы).
- **Reviewed-кандидат (продукт):** `a0a34dcd32a3c55004c0f4c1f88cc9b2283391ae`,
  ветка `feat/fct-s5-u1-writer-dates-2026-11-28`, tip `dd75a9e67` (после продукта — только evidence).
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s5-u1-2026-11-28/review-r1/review-r1.md`
  sha256 `fdfd805c0fc065b05f7a09abaeb35adc74f76b6c90bd4f827ca828b5778a303c` —
  **APPROVED_FOR_RELEASE_PREPARATION** (`raw/review-pin.txt`; файл живёт в master-линии, коммит
  `62cce15ed`, в дерево релиза не копировался). Блокирующих findings нет; B-1 (`retrieved_at`
  для snippet-only строк) — BACKLOG_ONLY.

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `4414a026c` | feat(fct-801): даты Writer-payload из уже собранного evidence, unknown остаётся отсутствующим (без `now()`) — **побайтово** файлы `a0a34dcd3` |
| `9c45a454c` | chore(release): bump 2.58.267 → 2.58.268 (version-only, 29 файлов / 34 вхождения) |

Продуктовые файлы взяты через `git checkout a0a34dcd3 -- <files>` ⇒ блобы совпадают с кандидатом
по построению; независимо проверено по index-блобам и по сырым байтам (`raw/identity.txt`):

```
services/factcheck_service.py      idx=6f916bb9801e04d6c12b899d23779fbb2dbc70d3 match=True bytes_equal=True base=64cedab6a708…
tests/test_fc_trust_s5_writer.py    idx=4e1390cfec76130b15c659f8864f6352be06e4cd match=True bytes_equal=True base=(absent)
```

## 1. Продуктовый диф — ровно 2 файла кандидата

| Файл | Δ | index blob (= кандидат) |
|---|---|---|
| `services/factcheck_service.py` | +122/−0 | `6f916bb9801e…` True |
| `tests/test_fc_trust_s5_writer.py` (новый) | +234/−0 | `4e1390cfec76…` True |

`raw/product-delta.txt`: `product_files_changed=2`,
`outside_product_and_bump_files=(none)`, `bump_touched_files=29`.
Полный диф кандидата — `raw/product-diff-full.txt`.

## 2. Канон промптов не изменён

`services/factcheck_prompts.py`: sha256 `4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4`
(= канон), блоб `64bb06c05fc7…` совпадает и у кандидата, и у базы ⇒ файл не тронут (`raw/identity.txt`).
`renderer`, `orchestrator`, `handlers`, `web`, `config` (кроме bump-строки) не изменялись.

## 3. Bump 2.58.267 → 2.58.268 — version-only

`raw/bump-verify.txt`:

```
files=29 occurrences_replaced=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
remaining_old_occurrences=0
APP_VERSION_lines=['APP_VERSION = "2.58.268"   # (27.11.2026): …']
config/settings.py: occurrences=1 crlf=3665 bare_lf=0 size_before=362807 size_after=362807
```

Набор из 29 путей идентичен предыдущим bump'ам (`raw/_bump.py` берёт его из bump-коммита
`7b835b838`); EOL (CRLF в `config/settings.py`, 3665) и размер файла не изменились.
Исторические evidence-каталоги `release-2.58.26x/` намеренно не бомпались.

## 4. DDL = 0, `user_version` 49 ⇒ rollback code-only

`raw/ddl-check.txt`: `migrations_or_db_py_changed=(none)`; `max_schema_constant=49`
(49 констант `_SCHEMA_VERSION*` в `services/database.py`), схема не повышалась.
`services/param_catalog.py` не менялся ⇒ новых сидов нет;
`tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 668 == REGISTRY**
(`raw/registry-check.txt`). Ожидаемое число строк PG `bot_settings` — **558 без изменений**.

## 5. Routes-пин не менялся

`raw/ddl-check.txt`:

```
routes_sha256 = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_pin_b8f63355 = True
appjs_sha256 = 3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a
```

`web/api/routes.py` и `web/app.js` в дифе от базы отсутствуют.

## 6. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `test_fc_trust_s5_writer` + `test_fc_trust_render` + `test_fc_trust_s4_evidence` + `test_fc_trust_verdict` + `test_fc_trust_retrieval` + `test_factcheck_p0_fc` | **205 passed**, 1 warning (`duckduckgo_search` rename, pre-existing) — 16.49 s | `tests-fct.txt` |
| `test_fc_trust_s5_writer` отдельно | **8 passed** — 3.00 s | `tests-s5-writer-only.txt` |
| Пины: `test_webapp_f11_round1025` + `test_round1025_f8_registry` | **62 passed** — 4.99 s | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

## 7. Манифест

`raw/manifest-dryrun.txt` — dry-run на bump-коммите (`deployed_sha` = `9c45a454c`, фактический
HEAD фиксируется при деплое):

```json
{ "deployed_at": "2026-11-28T02:56:49.607179Z", "deployed_sha": "9c45a454cb5130de8b2fe75efa88e46313f54aa1",
  "deployer": "devops", "dirty_tracked": false, "effect": "deploy",
  "previous_sha": null, "previous_version": null,
  "release_branch": "release/2.58.268", "schema": 1, "version": "2.58.268" }
```

`previous_*` = `null` только потому, что локальный worktree не содержит `.deploy/release.json`
(manifest пишется `tools/release_manifest.py` на проде). На проде previous берётся из рабочего
манифеста ⇒ `9709b14af` / 2.58.267; `deployed_sha` = фактический HEAD; `dirty_tracked=false`.
**Rollback = code-only** (DDL Δ=0, схема v49).

## 8. Ограничения

- Живой LLM-прогон Writer'а не выполнялся ни Builder'ом, ни Reviewer'ом: проверены payload и
  структурные тесты. Поэтому строки 802/803/805 остаются REVIEW (как в ревью).
- B-1 ревью (BACKLOG_ONLY) — `retrieved_at` snippet-only строк; вне контракта S5-U1, в релиз не входит.
- Тесты на проде не запускаются; live-проверки — в `deploy-2.58.268.md`.

## 9. Идентичность на коммите релиза (не только в index)

`raw/identity-committed.txt` — блобы из **закоммиченного дерева**, а не из index:

```
services/factcheck_service.py       head_blob=6f916bb9801e… = candidate, committed_bytes_equal_worktree=True
tests/test_fc_trust_s5_writer.py     head_blob=4e1390cfec76… = candidate, committed_bytes_equal_worktree=True
services/factcheck_prompts.py        head_blob=64bb06c05fc7… = candidate, sha256=4cd1e893…, unchanged
```

Коммит с этим разделом (`docs(release)`) не трогает продуктовые файлы — только
`plans/features/fc-trust-01/evidence/release-2.58.268/**` ⇒ байтовая идентичность сохраняется
в задеплоенном дереве.

## Приложения

`raw/`: `identity.txt`, `identity-committed.txt`, `product-delta.txt`, `product-diff-full.txt`,
`changed-files-preassembly.txt`, `bump-verify.txt`, `ddl-check.txt`, `registry-check.txt`,
`review-pin.txt`, `manifest-dryrun.txt`, `tests-fct.txt`, `tests-s5-writer-only.txt`,
`tests-pins.txt`, `SHA256SUMS`.
Скрипты сборки: `raw/_identity.py`, `raw/_bump.py`, `raw/_assembly_artefacts.py`, `raw/_sums.py`.
