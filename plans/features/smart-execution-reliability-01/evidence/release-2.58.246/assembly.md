# Релиз 2.58.246 — сборка (E-LAG scheduler + UR-28.4)

- **Роль:** Builder (локальная сборка). **Без деплоя и SSH** — выкладка и
  post-deploy за DevOps после независимого delta-ревью.
- **База (production 2.58.245):** `e3467ccb787709650af3f493a88861e60ac51684`
  (release `release/model-swap-2.58.245`, MODEL-SWAP-01..05).
- **Ветка:** `release/2.58.246` от `e3467ccb7` в отдельном registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/release-2-58-246-…`,
  epic/unit `release-2.58.246`); без merge-коммитов.
- **Состояние базы:** на старте сборки файл
  `plans/features/embed-identity-compat/evidence/release-2.58.245/deploy-2.58.245.md`
  ещё отсутствовал (деплой шёл), поэтому сборка начата на `e3467ccb7` без
  rebase на `5621bda8d`. **В процессе сборки evidence появился:**
  `2.58.245` выложен на production **DEPLOY OK** на точном
  `e3467ccb787709650af3f493a88861e60ac51684` (tree `d4f345054`, manifest
  `deployed_sha=e3467ccb7`, version `2.58.245`, previous `5621bda8d`/2.58.244,
  identity `verified_deployed`, `NRestarts=0`, `/healthz` 2.58.245, schema v48,
  **DDL 0**, миграций 0, отката не было; `MODEL-SWAP-03/04/05` остаются
  `delivered_awaiting_evidence`). То есть база сборки = фактический прод,
  rollback-цель manifest'а совпадает с production-манифестом.
- **Срезы (оба APPROVED_FOR_RELEASE_PREPARATION):**
  1. **E-LAG** (`fix/exp-e-lag-sched-2026-11-25`, base `5621bda8d`):
     review `plans/features/smart-execution-reliability-01/evidence/exp-e/sched-fix-review-r1.md`,
     sha256 `f8949c5b2bb204aa0fcc5993421e281ceceefb50e6e76df0bf3f78d3b136f84c`
     (сверено), reviewed tip `70044b58e`, product `fbba6a60c`; строки
     `EXP-E-LAG-01`, `EXP-E-TRUNC-01`.
  2. **UR-28.4 / UR-C-SCHED** (`feat/ur-28-4-2026-11-25`, base `5621bda8d`):
     review `plans/features/unified-reply/evidence/ur-28-4-review-r2.md`,
     sha256 `8231d641d6d574afa8be45f9c0e857b91cee2d4d5ffc94c1c6c9a502da52527b`
     (сверено), reviewed tip `c5884b544` (B-1/N-1 закрыты, UR-C-SCHED 7/7),
     product `70ea7d8e7` (первый кандидат `b423fbccf`).

```json
{
  "release": "2.58.246",
  "slices": [
    {"id": "E-LAG", "rows": ["EXP-E-LAG-01", "EXP-E-TRUNC-01"],
     "branch": "fix/exp-e-lag-sched-2026-11-25",
     "base": "5621bda8dd302c19fa7cda29d84c8541c5d2304a",
     "source_tip": "70044b58e", "source_product": "fbba6a60c",
     "review": {"file": "plans/features/smart-execution-reliability-01/evidence/exp-e/sched-fix-review-r1.md",
                "sha256": "f8949c5b2bb204aa0fcc5993421e281ceceefb50e6e76df0bf3f78d3b136f84c",
                "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}},
    {"id": "UR-28.4", "rows": ["UR-C-SCHED"],
     "branch": "feat/ur-28-4-2026-11-25",
     "base": "5621bda8dd302c19fa7cda29d84c8541c5d2304a",
     "source_tip": "c5884b544", "source_product": "70ea7d8e7",
     "review": {"file": "plans/features/unified-reply/evidence/ur-28-4-review-r2.md",
                "sha256": "8231d641d6d574afa8be45f9c0e857b91cee2d4d5ffc94c1c6c9a502da52527b",
                "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
                "closed": ["B-1", "N-1"], "row_status": "7/7"}}
  ],
  "base": {"sha": "e3467ccb787709650af3f493a88861e60ac51684",
           "version": "2.58.245",
           "state": "deploy_in_progress_by_devops_no_evidence_file"},
  "integration": "linear cherry-pick -x: E-LAG 5621bda8d..70044b58e, then UR 5621bda8d..c5884b544",
  "content_tip": {"sha": "683e23a63", "tree": "9ce597330043263ee0eb2ea4dbbc9f363f0f1aa6",
                  "commits_above_base": 12,
                  "delta_vs_base": {"files": 14, "insertions": 1652, "deletions": 26}},
  "bump_tip": {"sha": "d66b844032b84759875f1a73f3a7e859e70f707b",
               "tree": "932535ac10ebd5f09d7a4741dddcffac475f8679",
               "version": "2.58.246",
               "delta": {"files": 32, "insertions": 35, "deletions": 35}},
  "total_delta_vs_base": {"commits": 13, "files": 46, "insertions": 1687, "deletions": 61},
  "product_identity": {
    "services/mca_experience_jobs.py": {"blob": "bca2de7c1e5b2eec5a3563a08e8f2a3ab6c5037d", "equals_source": true},
    "services/memory_maintenance.py": {"blob": "189a369c2d44273b71ed78d6efebb3595c66ae21", "equals_source": true},
    "tests/test_exp_e_lag_scheduling.py": {"blob": "a9ae626313ebee320bbdf8fa7fa283868e7465c0", "equals_source": true},
    "web/api/routes.py": {"blob": "91b9721113df6a5d3de5338ca9b652134003d527", "equals_source": true},
    "tests/test_ur_per_chat_schedule.py": {"blob": "a3f54834ffb193384cfd1a0c473966e282f85d01", "equals_source": true},
    "web/app.js": {"blob": "3edd1b6db8ea04ee52e79a1498995a6b6b015021",
                   "equals_source": false,
                   "composition": "2.58.245 blob + exact UR hunks (105/105 lines)",
                   "ur_source_blob": "29554b07ae30cd350ae2b48a9c51c8b7bcd6d2d2"},
    "web/index.html": {"blob": "a64b2c6e93fdc54a8665226ac3219245ed220617",
                       "equals_source": false,
                       "composition": "2.58.245 blob + exact UR hunks (51/51 lines)",
                       "ur_source_blob": "7bb9a4456725858058431aa2d41796077bee0d61"}
  },
  "rollback": {"code_only_sha": "e3467ccb787709650af3f493a88861e60ac51684",
               "ddl": 0, "migrations": 0, "flags": 0,
               "data_migration": false, "new_stores": 0, "prompts_changed": false},
  "manifest_dry_run": {
    "at": "repin_tip_clean_tree",
    "schema": 1,
    "deployed_sha": "da4dde28a9e5bed8a341655a5d6e752bea8d6284",
    "version": "2.58.246",
    "previous_sha": "e3467ccb787709650af3f493a88861e60ac51684",
    "previous_version": "2.58.245",
    "release_branch": "release/2.58.246",
    "effect": "deploy",
    "dirty_tracked": false,
    "written": false,
    "rollback_variant_rc": 0,
    "note": "прогон повторён после корректива R246-DR1-F1 (re-pin на чистом дереве); на docs-tip ветки тот же прогон даёт deployed_sha = фактический HEAD"
  },
  "corrective": {
    "finding": "R246-DR1-F1",
    "commit": "da4dde28a9e5bed8a341655a5d6e752bea8d6284",
    "file": "tests/test_round1025_f8_registry.py",
    "pin_before": "9413f30397fd53743c8e11042b4a00a27a5e7d108012dd0d6f67c399c1a4bfb8",
    "pin_after": "8f582128a2c7c9c8e23fd20b2e0f045236856a8297bc0480aae22607a4ac09a1",
    "product_bytes_changed": false
  },
  "tests": {
    "slice_suites": {"total": 12, "passed": 12, "failed": 0},
    "focused_exp_e_scheduler_21_files": {"total": 303, "passed": 302, "failed": 1,
                                         "failed_ids": ["tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons"],
                                         "status": "pre-existing on base"},
    "ur_summary_set_5_files": {"total": 156, "passed": 154, "failed": 2,
                                "status": "pre-existing on base"},
    "version_pins_py_k_app_version": {"total": 21, "passed": 20, "failed": 1,
                                      "failed_ids": ["tests/test_webapp_round108_ui.py::TestCacheBustAndEsc108::test_app_version_matches_readme"],
                                      "status": "pre-existing on base (README не бамплен); прежняя строка 18/18 — узкая выборка 24 файлов"},
    "route_pin_tests": {"total": 75, "passed": 74, "failed": 1,
                        "failed_ids": ["tests/test_mca23_planned_vs_actual.py::TestResponseEndpoints::test_routes_pin_untouched"],
                        "status": "pre-existing on base (собственный устаревший хеш 453e17f8…); оба route-pin теста зелёные после re-pin"},
    "js_version_pins": {"total": 4, "passed": 4, "failed": 0},
    "model_swap_ui_regression": {"total": 19, "passed": 19, "failed": 0},
    "py_compile_changed_py": {"files": 32, "ok": 32},
    "node_check_app_js": {"rc": 0},
    "git_diff_check": {"worktree_rc": 0, "range_rc": 0}
  }
}
```

## 1. Линия и интеграция

- Интеграция — **линейный cherry-pick** (`-x`) на `e3467ccb7`, без merge-коммитов
  и без правок содержимого:
  - E-LAG: `5621bda8d..70044b58e` (3 коммита) → `cad669e05`, `09f9bc79f`, `99acc9a6d`;
  - UR-28.4: `5621bda8d..c5884b544` (9 коммитов) → `44a22810d`, `a798768ee`,
    `79bddf067`, `ed71e4016`, `df70e8436`, `806a10f38`, `d1180e882`,
    `b62650c66`, `683e23a63`.
- **Уточнение к диспатчу (честно):** для UR-28.4 в задании названы tip
  `c5884b544` и кандидаты `70ea7d8e7`/`b423fbccf`; фактическая линейная
  цепочка среза над базой содержит **9** коммитов. Ранние коммиты
  `b70598193` (payload `/api/config/time` — `summary_schedule`),
  `736725b20` (UI-строка в шапке саммари), `c3017f059` (evidence),
  `fd21dc934` (удаление неиспользуемого состояния) не перечислены, но без них
  дерево проверенного tip `c5884b544` недостижимо; продуктовая часть
  `web/api/routes.py` приходит именно из `b70598193`. Включены полностью.
- Авто-merge затронул только `web/app.js`/`web/index.html` (2.58.245 и UR
  правят разные места); конфликтов не было. Проверено, что результат — **точная
  композиция** обеих правок (§3).
- **Content tip:** `683e23a63` (tree `9ce597330043263ee0eb2ea4dbbc9f363f0f1aa6`).
- **Bump tip:** `d66b844032b84759875f1a73f3a7e859e70f707b`
  (tree `932535ac10ebd5f09d7a4741dddcffac475f8679`).
- Над базой 13 коммитов (3 + 9 + 1 bump) + docs-коммит сборки + корректирующий
  коммит delta-ревью r1 `da4dde28a` (re-pin `ROUTES_SHA256_F11`, только тест) +
  этот evidence-коммит.

## 2. Границы дельты

| Проверка | Результат |
|---|---|
| Срезы (`e3467ccb7..683e23a63`) | **14** файлов, `+1652/−26` |
| — E-LAG | `services/mca_experience_jobs.py` (+260/−21), `services/memory_maintenance.py` (+3 docstring), `tests/test_exp_e_lag_scheduling.py` (новый, 326), 2 evidence (md 146 + handoff json 15) |
| — UR-28.4 | `web/api/routes.py` (+87/−3), `web/app.js` (+79/−2), `web/index.html` (+45/−0), `tests/test_ur_per_chat_schedule.py` (новый, 330), 5 evidence (md 203, 2 json, 2 png) |
| Bump | ровно **32** файла, `+35/−35` — только версия (§4) |
| Всего `e3467ccb7..d66b84403` | **46** файлов, `+1687/−61` |
| `migrations/`, DDL | **0** |
| `config/` | только `config/settings.py` (`APP_VERSION` + release-клауза) |
| Новые флаги (`ClassVar[bool]`) | **0** |
| `requirements.txt`, `prompts/`, `services/database.py`, `services/graphrag_rebuild.py`, `web/api/memory_agi.py` | **0** (не затронуты) |

Схема остаётся **v48 / DDL 0**, миграций и изменений данных нет.

## 3. Identity продуктовых файлов (относительно reviewed candidates)

| Файл | Blob в 2.58.246 | Сверка |
|---|---|---|
| `services/mca_experience_jobs.py` | `bca2de7c1` | **=** `70044b58e` (E-LAG tip) |
| `services/memory_maintenance.py` | `189a369c2` | **=** `70044b58e` |
| `tests/test_exp_e_lag_scheduling.py` | `a9ae62631` | **=** `70044b58e` |
| `web/api/routes.py` | `91b972111` | **=** `c5884b544` (UR tip) |
| `tests/test_ur_per_chat_schedule.py` | `a3f54834f` | **=** `c5884b544` |
| `web/app.js` | `3edd1b6db` | **композиция** |
| `web/index.html` | `a64b2c6e9` | **композиция** |

`web/app.js` и `web/index.html` **не могут** совпадать с blob'ами среза
байт-в-байт: в 2.58.245 (MODEL-SWAP) в те же файлы добавлены свои блоки
(`+306`/`+198` относительно общей базы `5621bda8d`). Поэтому идентичность
проверена в обе стороны по фактическим правкам (`git diff -U3`, тела хунков):

- `git diff e3467ccb7 HEAD -- web/app.js` **идентичен по телу** диффу
  `5621bda8d..c5884b544 -- web/app.js` (105/105 строк, включая контекст);
  для `web/index.html` — 51/51; все добавленные строки совпадают (79 и 45),
  удалённых строк сверх правки среза нет.
- Симметрично, `git diff c5884b544 HEAD -- web/app.js` идентичен диффу
  2.58.245 (`342/342` строк), `web/index.html` — `210/210`.
- Следствие: обе функциональные области (MODEL-SWAP UI и UR-28.4 UI)
  присутствуют ровно в том виде, в котором их проверяли независимые ревью;
  посторонних правок в этих файлах нет. Дополнительно живой прогон UI-набора
  2.58.245 (`test_embed_model_swap_ux.py`, 19/19) и UR-набора (§6) зелёный.

## 4. Bump 2.58.245 → 2.58.246

`d66b84403` — **standard version wave**, тот же набор файлов, что bump 2.58.245
(`7aacf17b3`): 32 файла, `+35/−35`.

| Группа | Файлы |
|---|---|
| `APP_VERSION` + release-клауза | `config/settings.py` (1 строка: `2.58.246` + новая клауза, прежняя голова стала `Prior (25.11.2026): 2.58.245 - MODEL-SWAP…`) |
| F8 meta | `plans/docs/param-registry-round1025.meta.md` |
| py-пины (`APP_VERSION == "2.58.246"`) | 24 теста `round1025/1026`, 2 инструмента `ui_mod_acl_m4b*` |
| JS-пины (escaped `2\.58\.246`) | `round1025_hotfix{7,8,9,10}_*_test.js` |

Проверено программно (byte-level замена):
- 32 файла, 35 строк, **0** не-версионных отличий: обратная замена токена
  воспроизводит исходные байты; для `settings.py` — удаление вставленной
  клаузы и обратная замена версии дают байт-идентичный исходник.
- BOM `EF BB BF` и EOL `CRLF` сохранены (`settings.py`: 3665 CRLF / 0 LF до и после).
- `APP_VERSION = "2.58.246"` читается AST-разбором `tools/release_manifest.py`.
- Исторические evidence 2.58.243/244/245 не менялись.

## 5. Manifest dry-run

Чистое tracked-дерево `d66b84403`; `.deploy/release.json` (gitignored)
временно содержал production-манифест `e3467ccb7 / 2.58.245`:

```json
{
  "schema": 1,
  "deployed_sha": "d66b844032b84759875f1a73f3a7e859e70f707b",
  "version": "2.58.246",
  "deployed_at": "2026-11-25T06:13:58.343091Z",
  "effect": "deploy",
  "previous_sha": "e3467ccb787709650af3f493a88861e60ac51684",
  "previous_version": "2.58.245",
  "release_branch": "release/2.58.246",
  "dirty_tracked": false
}
```

`--dry-run` rc 0, файл не записан; `--effect rollback --dry-run` rc 0 (та же
identity, `effect=rollback`). Seed удалён после прогона. `previous` совпадает с
production-манифестом 2.58.245 (`e3467ccb7`/`2.58.245`). На финальном tip
ветки (docs-only evidence-коммит сверху) тот же прогон даёт
`deployed_sha = <финальный HEAD>`, остальные поля идентичны; DevOps повторяет
manifest на **точном deployed SHA**. По контракту задачи: release `2.58.246`,
previous `e3467ccb7`/`2.58.245`, DDL 0, миграций 0, новых флагов 0,
rollback code-only `e3467ccb7`.

**Корректив delta-ревью r1 (R246-DR1-F1):** после re-pin пина
`ROUTES_SHA256_F11` (коммит `da4dde28a`, изменён ровно один файл —
`tests/test_round1025_f8_registry.py`; продуктовые байты не тронуты) прогон
повторён на чистом дереве `da4dde28a` с тем же seed `e3467ccb7`/2.58.245:

```json
{
  "schema": 1,
  "deployed_sha": "da4dde28a9e5bed8a341655a5d6e752bea8d6284",
  "version": "2.58.246",
  "deployed_at": "2026-11-25T06:43:46.709328Z",
  "effect": "deploy",
  "previous_sha": "e3467ccb787709650af3f493a88861e60ac51684",
  "previous_version": "2.58.245",
  "release_branch": "release/2.58.246",
  "dirty_tracked": false
}
```

`--dry-run` rc 0 (файл не записан), `--effect rollback --dry-run` rc 0.
Версия осталась **2.58.246**, previous — `e3467ccb7`/**2.58.245**,
`dirty_tracked=false`, `effect=deploy`. На docs-tip ветки (этот
evidence-коммит сверху) тот же прогон даёт `deployed_sha = <фактический HEAD>`
при идентичных остальных полях.

## 6. Тесты на bumped tip `d66b84403` и коррективе `da4dde28a`

Окружение: Python 3.12.0 (`C:\Users\main\AppData\Local\Python\bin\python.exe`,
pytest 9.1.1), `PYTHONPATH=<worktree>`, `PYTHONDONTWRITEBYTECODE=1`,
`-p no:cacheprovider`.

| Прогон | Результат |
|---|---|
| `pytest tests/test_exp_e_lag_scheduling.py tests/test_ur_per_chat_schedule.py -q` | **12 passed** (6.96 s) — 5 E-LAG + 7 UR-C-SCHED |
| Фокусный exp-e/scheduler набор (21 файл, состав из E-LAG review) | **302 passed, 1 failed** (59.27 s); fail — pre-existing (§7) |
| UR/summary set: `test_ur_c_sched`, `test_ur_c_clock`, `test_summary_scheduler`, `test_summary_generator`, `test_ur_ui_effective_config` | **154 passed, 2 failed** (17.63 s); оба — pre-existing (§7) |
| Version-пины: широкий прогон `pytest tests -k app_version` | **20 passed, 1 failed** (59.95 s); fail — `test_webapp_round108_ui.py::TestCacheBustAndEsc108::test_app_version_matches_readme` (README не бамплен), pre-existing на `e3467ccb7`. Прежняя строка «18 passed / 0 failed» была узкой выборкой 24 файлов (N2 delta-ревью), не полным прогоном |
| Route-пины после re-pin: `test_round1025_f8_registry.py` + `test_mca23_planned_vs_actual.py` + `test_mca12_stories_round1046.py` | **1 failed, 74 passed** (8.95 s) — единственное падение pre-existing `test_mca23…::test_routes_pin_untouched` (свой устаревший хеш `453e17f8…`, §7); `TestFrozenInvariants::test_routes_file_unchanged` и `test_mca12…::test_routes_pin_unchanged_and_router_registered` **зелёные** |
| — то же с `-k "frozen or routes or registry"` | **1 failed, 30 passed, 44 deselected** (5.48 s); тот же pre-existing mca23 |
| 4 JS version-pin теста (`node --test`, `tests/js/round1025_hotfix{7,8,9,10}_*`) | **4 pass, 0 fail** |
| Регрессия UI 2.58.245 на слитых `app.js`/`index.html`: `test_embed_model_swap_ux.py` | **19 passed** (23.86 s) |
| `node --check web/app.js` | rc 0 |
| `py_compile` по 32 изменённым `.py` дельты `e3467ccb7..HEAD` | **32 ok, 0 errors** |
| `git diff --check` (worktree и `e3467ccb7..HEAD`) | rc 0 / rc 0 |

**Почему route-пины не были пойманы раньше (честно):** ни UR-ревью r2, ни эта
сборка не запускали route-pin наборы — в списках прогонов их не было, а re-pin
при правке `web/api/routes.py` не входил в шаги среза. Поэтому устаревший
`ROUTES_SHA256_F11` (значение до UR-28.4) не проявился до delta-ревью r1, где
оба теста впервые упали на кандидате (на базе `e3467ccb7` они проходят).
В коррективе `da4dde28a` пин пересчитан по фактическим байтам файла
(`sha256 = 8f582128a2c7c9c8e23fd20b2e0f045236856a8297bc0480aae22607a4ac09a1`,
пересчитано независимо `Get-FileHash`/`git hash-object` = `91b9721113…` blob,
400 944 B), добавлена однострочная provenance-пометка в формате соседних
пинов; route-набор и остальные byte-freeze пины (`param_catalog.py`,
`pg_db.py`) не менялись. Продуктовые байты идентичны `b55d00ab9`: изменён
ровно один файл — `tests/test_round1025_f8_registry.py`.

**Артефакт окружения (не дефект кандидата):** при fd-capture в пайп
PowerShell два subprocess-теста (`test_round1025_f8_registry.py::
TestGeneratorIdempotency::test_check_subprocess_exit_zero` и
`test_mca12_stories_round1046.py::test_js_ui_suite`) падают
`OSError: [WinError 6] Неверный дескриптор` на `DuplicateHandle` в
`subprocess.run`; с `--capture=sys` оба зелёные. Оба теста не трогают
routes.py и на базе ведут себя так же — это свойство пайпа, а не кода.

## 7. Pre-existing (воспроизведено на базе `e3467ccb7`, не правилось)

Отдельный detached-worktree на `e3467ccb7` (после проверки удалён), те же
команды:

1. `tests/test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons`
   — `assert 'graph_facts' not in '"""MCA-16 …'`; на базе `e3467ccb7`
   **1 failed** (и идентично на `5621bda8d` — зафиксировано в E-LAG review r1).
2. `tests/test_summary_generator.py::TestEpic60RunningSummary::test_below_ratio_no_trigger`
   — `assert tasks == []`.
3. `tests/test_summary_generator.py::TestEpic60RunningSummary::test_expired_summary_stays_then_retriggers_on_new_messages`
   — `assert 0 == 1`.

Сводный базовый прогон (`test_summary_generator.py` + block_d-тест) на
`e3467ccb7`: **3 failed, 63 passed** — те же три ID с теми же assert'ами, что и
на bumped tip. Ни один из них не связан со срезами или bump: срезы не меняют
генератор саммари, опытный deep-sleep и не добавляют этих путей.

## 8. Rollback

- **Code-only:** `e3467ccb787709650af3f493a88861e60ac51684` (2.58.245),
  `tools/release_manifest.py --effect rollback`.
- **DDL 0, миграций 0, флагов 0, новых хранилищ 0**, `requirements.txt` и
  `prompts/` не менялись: данные и настройки не мигрируют и не откатываются.
  Схема остаётся v48.
- Durable-маркеров срезов нет: E-LAG использует существующие
  `hot`-записи/`rows_by_chat`, UR-28.4 — существующий payload
  `/api/config/time`; при откате кода старые поля просто не читаются.

## 9. Что должно оценить delta-ревью

1. **Два независимых среза в одной сборке.** E-LAG меняет планирование
   прохода опыта (`services/mca_experience_jobs.py`, +260/−21) и docstring
   обслуживания памяти; UR-28.4 — API-поле `summary_schedule` и UI-строку
   следующего запуска. Оба продукта — APPROVED_FOR_RELEASE_PREPARATION; delta-
   ревью должно подтвердить, что вошли именно проверенные версии (§3) и
   ничего сверх них (14 файлов срезов + 32 bump).
2. **Слитые `web/app.js`/`web/index.html`.** Единственное место, где правки
   двух срезов физически соседствуют: доказана точная композиция в обе
   стороны (§3) и зелёные UI-наборы обоих срезов (19/19 model-swap, UR-набор
   §6). Стоит перепроверить, что блоки 2.58.245 не переставлены и не потеряны.
3. **Диспатч и факт по коммитам UR.** В задании перечислены не все 9
   коммитов среза (§1); ранние `b70598193`/`736725b20`/`c3017f059`/`fd21dc934`
   обязательны для reviewed tree.
4. **Bump — 32 файла / 35 строк, только версия** (§4): подтвердить выборочно,
   что пины не «подкручены» по смыслу (изменён только токен версии), и что
   `config/settings.py` не получил функциональных правок.
5. **Три pre-existing падения** (§7) не блокируют релиз, но остаются долгом
   тестового набора: они падают идентично на production-базе 2.58.245.
6. **Live-эффект E-LAG и реальная смена модели — postdeploy.** В этой сборке
   нет preprod/live-прогонов: production-доступ и SSH запрещены заданием.
   Фактический эффект E-LAG (тик `due` из измеренного лага/истёкшего retry на
   реальных данных) и реальная смена модели embeddings (MODEL-SWAP-03/04/05)
   остаются postdeploy-действиями агентов; закрывать их как VERIFIED нельзя.

## 10. Остаточное (не блокирует)

1. Preprod/live для E-LAG не выполнялся — только unit/фокусные наборы и
   независимые пробы ревьюера на предыдущем шаге (review r1).
2. Три исторических падения тестов (§7) — долг тестового набора, не регрессия
   релиза.
3. Playwright-проверки UI используют реальные `web/index.html` + `web/app.js`
   с route-stubbed API (mock-DTO), не live `/api/status`; живой вид — post-deploy.
