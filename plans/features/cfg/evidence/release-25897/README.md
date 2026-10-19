# REL-25897 — evidence релиз-пакета **2.58.97** (CFG-04 + ADD-EXP F1)

**Кандидат:** bump `fcd73a3855ecd1472bbb577b3e3cab5c0aafb869` (2.58.97) + fix `8b437c39580b607a85d3f898178d0ba114c073d8` (help-sync гард; runtime не тронут) + docs-коммит (этот каталог).
**Код-линия поезда:** ADD-EXP F1 `5b86517e` (ревью `188f7414` Approved) + CFG-04 `2428768` (ревью `e27216d3` Approved); **прод-базис:** `95d11472` (2.58.96).
**Рубежи отката:** новый `release/fix-2.58.96` @ `95d11472` (создаётся при пуше); авто-откат деплой-скрипта — `release/fix-2.58.95` @ `113f3a62`.
**Изоляция:** worktree `%OPENCODE_WORKFLOW_SCRATCH%\release-25897\wt` (detached @ `8b437c39`), интерпретатор `.venv\Scripts\python.exe`; база — отдельный worktree `wt-base` @ `95d11472`.

| Файл | Что внутри |
|---|---|
| `bump-verify.txt` | bump version-only: 31 файл, каждая изменённая строка = только `2.58.96→2.58.97` (или meta HEAD `f1463f10→2428768`) |
| `cfg04-after.json` | полный JSON UI e2e CFG-04 (after): viewports/проверки/failures/console_errors |
| `ddl-check.txt` | **ΔDDL = 0**: DDL/миграции (`services/database.py`, migrations-модули, `scripts/`) в дельту не входят |
| `delta-non-plans.txt` | дельта `95d11472..8b437c39` без `plans/**` (42 файла) + сводка 235 = 193 plans + 42 non-plans |
| `delta-runtime-stat.txt` | runtime-дельта (5 файлов: CFG-04 ×3 + ADD-EXP F1 + bump) |
| `deploy-markers-offline.txt` | исполнение D2/D3-маркеров deploy-скрипта на байтах кандидата — значения совпадают с ожиданиями |
| `deploy-offline-check.txt` | `check_deploy_25897.py`: **EXIT 0** (hashes 9/9, вайтлист == дельта 5/5 (prod..BUMP и prod..HEAD), BUMP ancestor, upload на месте) |
| `flake-mca09.txt` | env-флейк mca09: изоляция 15/15 на кандидате и базе; тайминг-класс |
| `focused-base-pre-existing.txt` | прямое доказательство пре-сущ. падений на базе `95d11472` (worktree `wt-base`) |
| `focused-blast.txt` | сводка фокусных наборов S1–S12 |
| `focused-help-sync-fix.txt` | RED→GREEN help-sync-гарда: база 24p → кандидат 1f/23p → фикс 24p |
| `focused-help-sync-red.txt` | сырой вывод RED-прогона help-sync на кандидате до фикса |
| `focused-s1-cfg04.txt` | CFG-04 контракт `tests/test_cfg04_forms_contract.py` — 29 passed in 2.95s (rc=0) |
| `focused-s11-cfg04-e2e.txt` | UI e2e CFG-04 `tools/ui_cfg04_forms_e2e.py` (Playwright, 7 viewport) — [matrix] chat-РІР°СЂРёР°РЅС‚ config: override items=116 | [cfg04] mode=after viewports=7 failures=0 shots=14 console_errors=0 (rc=0) |
| `focused-s12-speech-e2e.txt` | speech savebar e2e (регрессия 2.58.96) — == РРўРћР“: failures=0, POST=22 (rc=0) |
| `focused-s2-profile-202.txt` | CFG-04 профиль 8 файлов — 202 passed, 1 warning in 7.15s (rc=0) |
| `focused-s3-add-exp-33.txt` | ADD-EXP F1 `tests/test_add_exp_expression.py` — 33 passed, 1 warning in 3.71s (rc=0) |
| `focused-s4-sec54.txt` | §5.4-наборы (w6 + persistfix + flags-composition) — 49 passed, 1 warning in 4.15s (rc=0) |
| `focused-s5-clusters.txt` | кластеры speech/composer/direct/authorial/sample-library (16 файлов) — 492 passed, 1 warning in 21.33s (rc=0) |
| `focused-s6-capability-registry.txt` | capability/registry sanity — 53 passed in 3.21s (rc=0) |
| `focused-s7-f8-pins.txt` | F8-пины — 29 passed in 4.33s (rc=0) |
| `focused-s8-js-unit-38.txt` | JS-unit sweep `test_webapp_js_unit.py` — 38 passed in 5.78s (rc=0) |
| `focused-s9-gen-param-check.txt` | реестр `--check` — CHECK OK: реестр 579 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны. |
| `frozen-fingerprint.txt` | sha256_12 + полные sha256 9 артефактов `EXPECT12`; sha скриптов; bump/fix/база |
| `js-sweep-106.txt` | `node --check` web/**/*.js + tests/js/**/*.js: files=106 bad=0 |
| `markers-candidate.txt` | маркеры поезда на кандидате (CFG-04 + ADD-EXP F1 + spot 2.58.95) — все OK |
| `pytest-attribution.txt` | атрибуция падений run #2: сравнение с 2.58.96; разбор help-sync фикса и mca09-флейка; пре-сущ. классы |
| `pytest-command.txt` | команда/окружение run #2 (CWD, HEAD, UTC start/end) |
| `pytest-full.txt` | полный `pytest -q` кандидата **run #2** (после fix `8b437c39`): 9 failed, 14583 passed, 39 skipped, 1 warning in 667.18s (0:11:07) |
| `pytest-run1-red.txt` | полный прогон **run #1** (до fix): 11 failed, 14581 passed, 39 skipped, 1 warning in 718.93s (0:11:58) — RED-доказательство (help-sync + env-флейк) |
| `rel97-markers-selfcheck.txt` | сверка всех ожиданий `rel97_final.sh` с байтами кандидата: 43/43 PASS + `bash -n` clean |
| `speech-e2e.json` | полный JSON speech e2e (failures=[], POST=22) |

Деплой-артефакты (подготовлены в scratch лейна; НЕ запускались, прод не трогался):
`deploy_25897.py`, `rel97_final.sh`, `check_deploy_25897.py` — sha256_12 в `frozen-fingerprint.txt`.
Чек-лист приёмки — `../release-25897-report.md` §4.

