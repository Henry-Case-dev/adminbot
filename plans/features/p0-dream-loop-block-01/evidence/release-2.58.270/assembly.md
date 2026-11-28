# Release 2.58.270 — P0-DREAM-LOOP-BLOCK (MMR вне event loop, честный бюджет)

- **Дата сборки:** 2026-11-28 (сборка завершена 05:58Z).
- **Роль:** DevOps (сборка релиза + деплой).
- **Статус:** ASSEMBLED; деплой — отдельный файл `deploy-2.58.270.md`.
- **База (deployed):** `6d97c02d8` = **2.58.269** (продукт `fa3cb0391`), `user_version=50`.
- **Ветка:** `release/2.58.270` от базы, worktree
  `WorkspaceData/worktrees/…/p0-dream-loop-release-2-58-270-bfcae9601298-23c78ff9`.
- **Reviewed-кандидат:** продукт `e30ae12bf0a6fff5f7eac7bfaea400175dd55c52`,
  ветка `fix/p0-dream-loop-block-2026-11-28`, tip `028dcf637f7927231352e9b876dc1aa1ebde3852`
  (после продукта — только evidence).
- **Ревью:** `plans/features/p0-dream-loop-block-01/evidence/fix-2026-11-28/review-r1/review-r1.md`
  sha256 `4abee23f…` — **APPROVED_FOR_RELEASE_PREPARATION** (B-1/B-2 — BACKLOG_ONLY).
  Файл живёт в master-линии; в дерево релиза не копировался (`raw/review-pin.txt`).
- **Инцидент:** `plans/features/p0-dream-loop-block-01/source-2026-11-28.md` —
  `lag_ms=728 994`, стек `dream_worker → … → _knn_graph_facts → _mmr_select → _cosine`.

## 0. Состав — продукт кандидата + bump

| Новый коммит | Содержание |
|---|---|
| `344d6126b` | fix(p0-dream-loop): MMR-отбор через `asyncio.to_thread` + `wait_for` бюджет; **побайтово** файлы `e30ae12bf` |
| `3eafef83c` | chore(release): bump 2.58.269 → 2.58.270 (version-only, 29 файлов / 34 вхождения) |

Файлы взяты через `git checkout e30ae12bf -- <files>` ⇒ блобы совпадают с кандидатом
по построению; независимо проверено по index-блобам, по коммиту кандидата, по его tip'у и
по сырым байтам (`raw/identity.txt`):

```
services/summary_memory.py                    index=2fdb657c1f35… match_product=True match_tip=True bytes_equal=True base=6ebe96e8b955…
tests/p0_dream_loop/test_no_event_loop_block.py index=391772ed50ef… match_product=True match_tip=True bytes_equal=True base=(absent)
```

sha256: `summary_memory.py` = `e93a4aac299051c5183050f31b34aea03fb02dc777312e98bea1d4c476985485` (480 595 B),
тест = `d209eb3e1054b938fa6eab63b19f45906e4c786e5ce517fc2ad612cfeabab4b2` (6 509 B) — совпадают
у рабочего дерева и у кандидата. `match_tip=True` ⇒ после ревью файлы не менялись.

## 1. Продуктовый диф — ровно 1 продуктовый файл + 1 новый тест

`raw/product-delta.txt`:

```
changed_files_total_vs_base=31
product_files=['services/summary_memory.py', 'tests/p0_dream_loop/test_no_event_loop_block.py']
bump_touched_files=29
outside_product_tests_bump_evidence=(none)
ddl_relevant_changed=(none)
43	3	services/summary_memory.py
156	0	tests/p0_dream_loop/test_no_event_loop_block.py
```

Дельта `summary_memory.py` — **+43/−3**: обёртка `_mmr_select_offloop`
(`asyncio.wait_for(asyncio.to_thread(_mmr_select, …))`, бюджет `_MMR_SELECT_TIMEOUT_SECONDS=5.0`,
при исчерпании — детерминированный top-by-rel с `stats["mmr_budget_exhausted"]=1` и WARNING без
текстов фактов) и два места вызова `_knn_graph_facts` переведены на неё. Сам `_mmr_select`
не изменён ⇒ идентичность выбора сохранена (ревью подтвердило побайтово).

## 2. DDL 0 — схема остаётся v50

`raw/product-delta.txt`: `ddl_relevant_changed=(none)` — ни `services/database.py`, ни
`services/param_catalog.py`, ни `migrations/` не тронуты. Миграции не запускаются;
на проде `user_version` должен остаться **50**. Новых сидов/флагов/LLM-вызовов нет.

## 3. Bump 2.58.269 → 2.58.270 — version-only

`raw/bump-verify.txt`:

```
files_in_canonical_set=29 files_changed=29 occurrences_replaced=34
skipped_no_occurrence=(none)
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0
remaining_old_occurrences=0 new_occurrences=34
crlf_total=3665 bare_lf_total=15441
APP_VERSION_lines=['APP_VERSION = "2.58.270"   # …']
config/settings.py: occurrences=1 crlf=3665 bare_lf=0 size_before=362807 size_after=362807
```

Набор из 29 путей — тот же канонический bump-set (из bump-коммита `07c345e88`);
EOL `config/settings.py` (CRLF, 3665) и размеры файлов не изменились. Исторические
evidence-каталоги `release-2.58.26x/` намеренно не бомпались.

## 4. Routes-пин и бандл не менялись

```
web/api/routes.py sha256 = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
web/app.js        sha256 = 3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a
web/ в диффе base..HEAD = 0 файлов
```

## 5. Проверки на собранном дереве (cwd = release-worktree, venv 3.12; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `tests/p0_dream_loop` + `test_summary_memory` + `test_dream_worker` + `test_fc_trust_verdict` | **132 passed**, 1 warning (pre-existing) — 16.7 s | `tests-core-retry.txt` |
| тот же набор, стабильность ×3 | **132 passed** ×3 (16.58 / 17.38 / 16.54 s) | `tests-core-stability.txt` |
| `test_summary_memory.py` отдельно | **79 passed** — 9.45 s | `tests-summary-memory-standalone.txt` |
| `tests/p0_dream_loop` + `test_summary_memory` | **83 passed** — 11.08 s | `tests-p0-plus-summary-repro.txt` |
| Пины: `test_round1025_f8_registry` + `test_webapp_f11_round1025` + `test_mca23_planned_vs_actual` | **86 passed** — 6.65 s | `tests-pins.txt` |
| `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 668 == REGISTRY** | `registry-check.txt` |

**Честно о сбое окружения:** самый первый комбинированный прогон (`raw/tests-core.txt`) завис
на teardown фикстуры `tests/test_summary_memory.py:39` (`loop.run_until_complete(d.close())`,
Windows proactor loop) после 17 зелёных тестов — pytest-timeout снял дамп стека. Немедленные
повторные прогоны того же набора (4 из 4) дают **132 passed** без зависаний, файл отдельно —
79 passed. Это недетерминированный артефакт Windows-event-loop в тестах, не воспроизводимый
на собранном дереве; логика фикса тут не участвует (фикстура создаёт свой отдельный loop).

## 6. Манифест (dry-run на собранном дереве до evidence-коммита)

`raw/manifest-dryrun.txt`:

```json
{
  "deployed_at": "2026-11-28T05:58:29.221499Z",
  "deployed_sha": "3eafef83cbd3d875ea71c89c816d81d223b42deb",
  "deployer": "devops",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/2.58.270",
  "schema": 1,
  "version": "2.58.270"
}
```

`previous_sha`/`previous_version` на проде подставятся из существующего `.deploy/release.json`
(ожидается `6d97c02d8…` / `2.58.269`); `deployed_sha` на проде = фактический HEAD после
evidence-коммита. `dirty_tracked=false`.

## 7. Байтовая идентичность блоба на прод-кандидате

После evidence-коммита продукт-блобы не меняются: `services/summary_memory.py` =
`2fdb657c1f35…`, `tests/p0_dream_loop/test_no_event_loop_block.py` = `391772ed50ef…`.
Проверка на проде — по `git rev-parse HEAD:<path>` (см. deploy evidence).

## 8. Откат

DDL Δ=0 и единственная продуктовая дельта — `summary_memory.py` ⇒ **code-only откат** к
`6d97c02d8` (`git checkout --detach 6d97c02d8` + restart). Код 2.58.269 совместим со схемой
v50 (схема не менялась). Dry-run манифеста отката — в deploy evidence.
