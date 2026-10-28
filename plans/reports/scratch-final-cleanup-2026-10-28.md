# Scratch-final cleanup — 2026-10-28 (local machine, no production access)

Lane: SCRATCH-FINAL (file side), DevOps. Parallel lane owned `C:\Code\Python` sibling worktrees; untouched here. No SSH, no network to servers, no commits.

## Roots: before → after (measured bytes)

| Root | Before | After | Freed |
|---|---|---|---|
| `~\.config\opencode\OpenCodeScratch` | 36,608,855,516 | 7,205,970,069 | 29,402,885,447 |
| `~\.config\opencode\OpenCodeCache` | 0 (empty) | structure removed | — |
| `Temp\opencode` | 4,801,915,130 | 2,563,904,941 | 2,238,010,189 |
| **Total** | | | **≈31.64 GB** |

Deletion-log sum: 31,637,480,806 B (pass 1, 44,154 entries) + 16,769,756 B (pass 2, 15 files) = 31,654,250,562 B. Small vs measured delta is NTFS cluster rounding. Logs: `Temp\opencode\scratch-final-deletion.json`, `scratch-final-deletion-pass2.json`, stamps `scratch-final-before.json` / `scratch-final-after.json`, scripts `scratch-final-*.py`.

## Deleted (proven), by group

| Group | Bytes | Entries | Proof basis |
|---|---|---|---|
| pytest temp `tmp\pytest-of-main` | 20,773,833,608 | 56 dirs | pytest disposable tmp (voice.mp4/mid.mp4 fixtures etc.) |
| `pycache\Code\Python\adminbot\.venv` partial venv copies | 3,800,756,980 | 76 dirs | build artifact (regenerable venv) |
| stale build/probe archives (head.tar, tree.tar.gz, head.zip, w5_base.zip, cand/base.tar, rev258110/111 trees' archives, p0c-int-candidate.tar.gz, pa5_stage.tar, pre-round1025-hotfix5-src.zip …) | 3,388,707,243 | 26 | git-derived snapshots of shipped/aborted rounds |
| repo-copy files identical to working tree (same relpath) | ~2.0 GB of the row below | 40,234 | sha256 == repo working tree |
| promoted evidence (png/json/md/js/… hash matches repo plans/**, extra_images, var backups, services) | ~0.3 GB of the row above | (same 40,234) | sha256 == promoted evidence in repo |
| db duplicates identical to repo-preserved copies | 783,982,592 | 4 | sha256 match: `local_database_2026-09-04_history.db` (755 MB), `pre_migration_20261007_010900.db` (28.6 MB) + 2 sidecars |
| `tmp\data-gym-cache` | 278,271,994 | 75 dirs | cache |
| `w5_iso\.venv`, `fresh-venv`, other venvs | 268,521,656 | 3 dirs | build artifact |
| stale test/probe databases (cfg01_probe×3, c06probe, mgprobe+wal+shm, asap3_dossier, dossier_rename, p0b_load, _probe_axis, _review_repro, _slow, _fail …) | 61,909,456 | 32 | test/probe dbs |
| pass-2 stale test dbs (cfg01_workers, harness_exp/exp2/mem, f7rev, inc01_after/red+wal+shm, w5_base _base_dbg/_base_dbg2/_state, tick t.db) + falsif `local_database.db` (sha == repo) + auto_blob.tmp | 16,769,756 | 15 | targeted list after log audit |
| `.pytest_cache`, `__pycache__` | 2,512,800 | 57 | cache |
| empty dirs pruned | 0 | 3,591 | — |

## Kept, with reasons

- **Registered Git worktrees (18 paths) — untouched.** 12 under `OpenCodeScratch\adminbot-ccef72c25768\` (cfg02a-cand/red, payload-verify-recheck(2), release-25887\base25887, release-25895\wt(,wt-base), rev-embed-r2\wt-5877810d,wt-d3ba845b, rev-rel-25887, rev-rel-soul, win-glass-release-25885\wt) and 6 under `Temp\opencode` (adminbot-base-534ac7dd, alias-red-272170e3, f10parent, head_check, mca19_headcheck, rev-embed-base). Verified via `git worktree list --porcelain`.
- **Full clones (own `.git` folder) — untouched, no unique commits:** `intel-probe` (master @ 08a8849 — ancestor of main master), `OpenCodeScratch\…\w5_head` (HEAD bf208505 and W5 candidate bc277a3d — both ancestors of master; untracked probe outputs: amend_plan.txt, amend_review.txt, main_plan.txt, main_review.txt, tests_out.txt), `workflow_smoke` (synthetic smoke fixture: local commits a7501e4, 0d2dd9b, 3bd27ee + untracked SMOKE_PLAN.md, TASK_SPEC.md, neg_gate_tests.py, plans/, update_map_verified.py — not adminbot history), `adminbot-clean` (**broken/unreadable** clone: `.git` present with objects/refs/logs but `git` reports "not a git repository" — likely interrupted filter-repo; needs owner decision before any future removal).
- **`w5_iso\migrate_history\*.json` (≈1.08 GB)** — unique local data exports (2024–2026 history), not regenerable from git; kept and reported.
- **Old-version source trees** `rev258110\tree_cand|tree_base` (≈260 MB), `rev258111\*_tree` (≈17 MB) — files differing from the current working tree are kept per lane rule; content is derivable from integrated git history of shipped releases 258110/258111 if ever needed again.
- **Unique probe scripts/maps/logs** (~13,500 files, small): comparison maps (`map_ours/theirs.json`), prompts probes, w7-review mutation trees, playwright console logs in `wa2`, evidence pngs with no repo match, `.opencode-workflow-scratch.json` markers.
- **`bu-chrome-profile` (≈199 MB)** — browser-automation profile (login state), neither duplicate nor stale artifact.
- Cleanup stamps/manifests/scripts in `Temp\opencode` root.

## Cause-fix documentation edits (this lane)

- `~\.config\opencode\AGENTS.md` (workspace-lifecycle section only): dirty-worktree disposition mandatory at epic close (preserve branch / patch / recorded discard; dozens of dirty checkouts = workflow defect); full-repo backup copies/clones never substitute for targeted deltas; portability preserved.
- `agents\DevOps.md`: same two rules added to epic-close hygiene paragraph.
- `agents\Builder.md`: no full-clone backups as preservation (workspace paragraph); explicit dirty-checkout disposition required in epic-boundary handoff.
- `agents\Orchestrator.md`: disposition requirement at epic terminal housekeeping handoff.
- Unittest after edits: `py -3.12 -m unittest tools.test_workflow_housekeeping` → **Ran 11 tests, OK**.

## Incidental findings (non-blocking)

1. `adminbot-clean` is a corrupted local clone (~104 MB) — invalid repo metadata; candidate for a future owner-confirmed removal (excluded here by clone ban).
2. `w5_iso\migrate_history` JSONs (~1.08 GB) and the scratch dirs of 18 registered worktrees (~5 GB) are the remaining bulk; the former is owner-data, the latter belong to still-registered worktrees that epic-close should retire when their epics close.
3. Legacy full-repo copy/clone habit (the cause of this 36 GB) is now explicitly banned in the global docs.

---

# Tail-проход (финал) — 28/29.10.2026, 23:57–00:40 (+1200)

Лейн: SCRATCH-TAIL (финальный файловый проход), DevOps. Только локально: без SSH, без прод-сервера, без коммитов.

## Гонка процессов и почему понадобился tail-проход

Файловый проход (pass 1 + pass 2) завершился в 23:27 и сравнивал содержимое только с рабочим деревом репозитория. Гит-лейн снял регистрацию worktree позже, ~23:53, поэтому остаток `OpenCodeScratch\adminbot-ccef72c25768` (2.585 ГБ, 15 256 файлов — поздние остатки worktree-полигонов) ни разу не хешировался. Tail-проход обработал все три зоны заново с более строгим доказательством: **содержимое файла — blob, достижимый из любой ссылки главного репозитория** (`git rev-list --objects --all` → 19 792 blob-OID; сравнение по git blob OID сырых байт, с fallback-нормализацией CRLF→LF). Зарегистрированных worktree в зонах нет (`git worktree list --porcelain` = только главный; повторно проверено внутри скрипта).

## Результат по зонам (байты, замеры `scratch-final-mid.json` → `scratch-final-after2.json`)

| Зона | До | После | Освобождено (измерено) |
|---|---|---|---|
| Z1 `~\.config\opencode\OpenCodeScratch` | 2 596 666 839 (15 580 файлов) | 1 532 979 415 (7 276 файлов) | 1 063 687 424 |
| Z2 `~\AppData\Local\Temp\opencode` | 961 416 475 (4 810 файлов) | 654 821 124 (3 154 файла) | 306 595 351 * |
| Z3 `C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH` | 2 483 878 538 (16 790 файлов) | 239 904 562 (136 файлов) | 2 243 973 976 |
| Итого освобождено на диске | | | **≈ 3.61 ГБ** (+ вывоз 282.5 МБ в карантин) |

\* расхождение с суммой удалений+карантина Z2 (316.2 МБ) — в `Temp\opencode` остались созданные tail-логи (~9.6 МБ), они же — аудит-след.

## Удалено (доказательно), 22 332 записи / 3 341 335 451 B

| Зона | Записей | Байт | Основные причины |
|---|---|---|---|
| Z1 | 7 296 | 951 219 299 | git-history blob match (содержимое worktree-остатков достижимо из истории) |
| Z2 | 1 235 | 301 869 652 | git-history match 1 232 зап. (290.8 МБ: деревья старых версий `rev258110`/`rev258111` и др. — вывод pass 1 «derivable from history» подтверждён точным OID-совпадением); stale-архивы 3 зап. (11.1 МБ) |
| Z3 | 13 801 | 2 088 246 500 | git-history match 13 634 зап. (1.081 ГБ: контрольные копии кода `amd-probes\head`, `ab-eval\head`, `final6\t`); stale-архивы 11 зап. (1.005 ГБ: `amd-probes\head.tar` 492 МБ, `final6\new.tar.gz` 459 МБ, `new_code.tar.gz` 8.5 МБ и др.); zone-3 логи 120 зап. (1.8 МБ, регламентировано миссией); artifact-части 36 зап. (1.2 МБ) |

Лог: `C:\Users\main\AppData\Local\Temp\opencode\scratch-final-tail-deletion.json` (кумулятивный, обе части).

## Карантин (перемещено, не удалено), 4 288 записей / 282 546 450 B, sha256-манифесты, verify после перемещения: **all True**

| Зона | Куда | Записей | Байт |
|---|---|---|---|
| Z1 | `~\.config\opencode\WorkspaceData\quarantine\scratch-unique\` (топ `adminbot-ccef72c25768` = 104 857 598 B — точно в лимите 100 МБ/topdir) | 1 008 | 112 468 125 |
| Z2 | `~\.config\opencode\WorkspaceData\quarantine\temp-opencode-unique\` | 427 | 14 350 849 |
| Z3 | `~\.config\opencode\WorkspaceData\quarantine\adminbot-scratch-unique\` | 2 853 | 155 727 476 |

Манифест: `C:\Users\main\AppData\Local\Temp\opencode\scratch-final-tail-quarantine.json` (from/to/bytes/sha256/sha256_after/verified).

## Оставлено (с причинами)

- **`w5_iso\migrate_history` — цел, 4 JSON, 1 082 500 686 B** (уникальные экспорты истории 2024–2026, owner-data). Защита по каталогу `migrate_history`; в логах удалений/карантина — 0 записей.
- **БД/бэкапы/секреты без git-доказательства (111 записей)**: `embed-resolver-pre\copy.db.gz` (184 854 681 B — снапшот БД закрытого лейна), ~25 probe-БД (`probe.db`, `w3_*.db`, `harness.db` и др., ~30 МБ), ~25 dotnet-sentinel-файлов (ложное срабатывание по слову «credential» — оставлены намеренно), `.env*` копии в worktree-остатке (7 131 B каждая, не перемещались — секреты).
- **Клоны со своим `.git`: `w5_head`** (Z1) — не тронут. Keep-каталоги Z2 не тронуты: `bu-chrome-profile` (браузерный профиль), `adminbot-clean` (битый клон, нужно отдельное решение владельца), `intel-probe`, `workflow_smoke`.
- **Аудит-след**: все `*cleanup*`/`scratch-final*`/`worktree-*` файлы и measure-скрипты в корне `Temp\opencode` (27 шт.) + маркеры `.opencode-workflow-scratch.json` (77).
- **Uncertain сверх бюджета карантина**: Z1 — 7 065 файлов / 446.3 МБ в `adminbot-ccef72c25768` (мелкие неуникализированные артефакты закрытых лейнов, уложиться в 100 МБ/topdir нельзя без потери доказательной ценности; оставлены на месте, перечислены в логе); Z3 — 110 файлов / 19.9 МБ (крупные >2 МБ несовпадающие файлы: `add-exp-f0` 5.5 МБ, `acceptance-92` 3.4 МБ и др.). Лог: `scratch-final-tail-kept.json`.

## Проверки

- `git -C C:\Code\Python\adminbot status --porcelain`: до — 133 строки, после — 133 строки; **tracked-набор идентичен** (29 строк ` M` в `plans/**`, `plans/progress_scope.json`, `plans/workflow_state.md` — все существовали до прохода; новых tracked-модификаций **0**). Z3 — untracked, путь не в `.gitignore` (проверено `git check-ignore`), каждый файл дополнительно сверялся с `git ls-files` перед обработкой.
- `py -3.12 -m unittest tools.test_workflow_housekeeping` (из `~\.config\opencode`): **Ran 11 tests, OK**.
- Ошибок выполнения: 0. Пустых каталогов вычищено: 1 096 + 1 305. Финальные размеры: `C:\Users\main\AppData\Local\Temp\opencode\scratch-final-after2.json`.

## Остатки по объёму (что дальше держит место)

1. `OpenCodeScratch\adminbot-ccef72c25768\w5_iso\migrate_history` — 1.08 ГБ owner-данных (экспорты истории чатов). Не трогать без решения владельца.
2. Uncertain-остаток worktree-полигона — 446 МБ (мелочь закрытых лейнов, сверх карантина).
3. `embed-resolver-pre\copy.db.gz` — 185 МБ, Z3.
4. `Temp\opencode`: keep-каталоги (`bu-chrome-profile` 199 МБ, `intel-probe` 328 МБ — клон, `adminbot-clean` 104 МБ — битый клон, `workflow_smoke`).
5. Битый клон `adminbot-clean` — кандидат на удаление по явному решению владельца (запрещено правилом «не удалять клоны» без подтверждения).

Скрипты tail-прохода: `Temp\opencode\scratch-final-tail.py` (+ `scratch-final-tail-aggregate.py`, `scratch-final-measure2.py`).
