# Release 2.58.267 — FC-TRUST-01 S4 U3 (publication labels, technical status, per-part media caveat, article classifier)

- **Дата сборки:** 2026-11-28
- **Роль:** DevOps (сборка релиза + деплой)
- **Статус:** ASSEMBLED; деплой — отдельный файл `deploy-2.58.267.md`.
- **База (deployed):** `cd2245fdbc50b764843aa1f6128cae824f054af7` = **2.58.266**.
- **Ветка:** `release/2.58.267` (создана от базы).
- **Reviewed-кандидат (продукт):** `718fe0a824522d68aa58605fc2b8ef1711e62534`,
  ветка `feat/fct-s4-u3-publication-2026-11-28`, tip `266c9d381` (после продукта — только evidence).
- **Ревью:** `plans/features/fc-trust-01/evidence/fct-s4-u3-2026-11-28/review-r1/review-r1.md`
  sha256 `50ad6040fd29dc419c087a0ce43779a085e0016c94969bd1ee83703ed7872c51` —
  **APPROVED_FOR_RELEASE_PREPARATION** (RV-S4U3-01 = BACKLOG_ONLY, блокеров нет).
  Implementation evidence того же кандидата: `.../fct-s4-u3-2026-11-28/implementation.md`
  sha256 `dd995223a9760164bedee68ff2116f65e01d073b1947c9a336402c2a3f962e1d` (`124e362db`).
  Оба файла живут в master-линии; в дерево релиза не копировались.

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `390f146f0` | feat(fct-702,fct-023,fct-603): подписи `publication_kind`, технический статус исполнения в тексте, per-part медиа-оговорка, классификатор journal/article — **побайтово** файлы `718fe0a82` |
| `7b835b838` | chore(release): bump 2.58.266 → 2.58.267 (version-only, 29 файлов / 34 вхождения) |

Продуктовые файлы взяты через `git checkout 718fe0a82 -- <files>` ⇒ блобы совпадают
с кандидатом по построению, независимо проверено по index-блобам (`raw/identity.txt`):

```
services/factcheck_renderer.py      idx=9866e390cd65feeebae520b463307e738a355db2 match=True base=ffb8eefb2f68…
services/factcheck_orchestrator.py  idx=15688f173fe3aeb875a880f46037662009c8d2e7 match=True base=54c9e3004dfd…
services/search_aggregator.py       idx=502604e57986bac8f692b49020e79fc0ac1d0e98 match=True base=cba937d970b0…
tests/test_fc_trust_render.py       idx=0b2c70491789d3723fe779f1b41ade18c215b2cb match=True base=(absent)
```

## 1. Продуктовый диф — 3 файла + новый тест, ровно кандидат

| Файл | Δ | index blob (= кандидат) |
|---|---|---|
| `services/factcheck_renderer.py` | +188/−22 | `9866e390cd65…` True |
| `services/factcheck_orchestrator.py` | +17/−0 | `15688f173fe3…` True |
| `services/search_aggregator.py` | +1/−1 | `502604e57986…` True |
| `tests/test_fc_trust_render.py` (новый) | +338/−0 | `0b2c70491789…` True |

Итого `git diff --numstat cd2245fdb` = 4 файла, 544+/23−. `raw/product-delta.txt`:
`product_files_changed=4`, вне перечисленных файлов и bump-набора изменений **нет**
(`outside=(none)`), `bump_touched_files=29`, `non_version_bump_files=(none)`.
`raw/identity-committed.txt` — те же блобы на коммите релиза (не только в index) ⇒ байтовая
идентичность сохраняется в задеплоенном дереве.
DDL/миграции не менялись (`raw/ddl-check.txt`). `factcheck_prompts.py`, handlers, web,
`config/settings.py` (кроме bump-строки) не тронуты.

## 2. Полный delta релиза (продукт + тест + bump)

`raw/changed-files-preassembly.txt`: `git diff --stat cd2245fdb HEAD` = **33 файла, 578+/57−**
(544+/23− продукт+тест, 34+/34− version-only bump).

## 3. Bump 2.58.266 → 2.58.267 — version-only

`raw/bump-verify.txt`:

```
files=29 occurrences_replaced=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
remaining_old_occurrences=0
APP_VERSION_lines=['APP_VERSION = "2.58.267"   # (27.11.2026): …']
config/settings.py: occurrences=1 crlf=3665 bare_lf=0 size_before=362807 size_after=362807
```

Набор из 29 путей идентичен предыдущим bump'ам (`config/settings.py`,
`plans/docs/param-registry-round1025.meta.md`, 25 тестов, 2 tools); EOL и размер settings.py
не изменились. Исторические evidence-каталоги `release-2.58.26x/` намеренно не бомпались.

## 4. DDL = 0, `user_version` 49 ⇒ rollback code-only

`raw/ddl-check.txt`: `migrations_or_db_py_changed=(none)`; `ddl_delta_lines=0`;
`max_schema_constant=49` (`services/database.py:_SCHEMA_VERSION_SELF_DIAG_SAMPLES`).

## 5. Seed: новых настроек нет

`raw/seed-factcheck.txt`: `services/param_catalog.py` не менялся
(`same=True`, новых `factcheck`-лимитов 0);
`tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 668 == REGISTRY**
(`raw/registry-check.txt`). Ожидаемое число строк PG `bot_settings` — **558 без изменений**.

## 6. Routes-пин не менялся

`raw/routes-pin.txt`:

```
routes_sha256_head = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_blob_head   = (= base; routes_changed=(none))
pin_matches_b8f63355 = True
```

## 7. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `test_fc_trust_render` + `test_fc_trust_s4_evidence` + `test_fc_trust_verdict` | **90 passed** (8.90 s) | `tests-render-s4-verdict.txt` |
| `test_fc_trust_retrieval` + `test_fc_trust_s1_contract` + `test_factcheck_p0_fc` + `test_factcheck_context_cfg06` + `test_factcheck_post_release_w1` | **188 passed**, 1 warning (`duckduckgo_search` rename, pre-existing) | `tests-core.txt` |
| Пины: `test_webapp_f11_round1025` + `test_round1025_f8_registry` | **62 passed** (4.36 s) | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

90 совпадает с прогоном Reviewer на том же кандидате (90 в render/s4/verdict; 107 в его
retrieval+p0 — здесь расширенный набор s1/cfg06/post_release даёт 188 вместе).

## 8. Манифест

`raw/manifest-dryrun.txt` — dry-run на bump-коммите (`deployed_sha` = `7b835b838`, фактический
HEAD фиксируется при деплое):

```json
{ "deployed_at": "2026-11-28T01:47:30.400056Z", "deployed_sha": "7b835b838245f903e92ba6ab752e126e4350fd9e",
  "deployer": "devops", "dirty_tracked": false, "effect": "deploy",
  "previous_sha": "cd2245fdbc50b764843aa1f6128cae824f054af7", "previous_version": "2.58.266",
  "release_branch": "release/2.58.267", "schema": 1, "version": "2.58.267" }
```

На проде манифест пишется после checkout ⇒ `deployed_sha` = фактический HEAD, `previous` =
`cd2245fdb` / 2.58.266, `dirty_tracked=false`. **Rollback = code-only** (DDL Δ=0, схема v49).

## 9. Ограничения

- RV-S4U3-01 (BACKLOG_ONLY): `publication.notice()` не передаёт `ambiguous_no_text_claim` /
  `album_incomplete` в `media_note`; вне текущего контракта, в релиз не входит.
- Тесты на проде не запускаются; live-проверки — в `deploy-2.58.267.md`.

## Приложения

`raw/`: `identity.txt`, `product-delta.txt`, `product-diff-full.txt`,
`changed-files-preassembly.txt`, `bump-verify.txt`, `ddl-check.txt`, `seed-factcheck.txt`,
`routes-pin.txt`, `tests-render-s4-verdict.txt`, `tests-core.txt`, `tests-pins.txt`,
`registry-check.txt`, `manifest-dryrun.txt`, `SHA256SUMS`.
Скрипты сборки: `raw/_bump.py`, `raw/_checks.py`, `raw/_assembly_artefacts.py`, `raw/_sums.py`.
