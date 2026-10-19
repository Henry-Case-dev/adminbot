# REL-25896 — evidence релиз-пакета **2.58.96** (ADD-EXP)

**Кандидат:** bump `14535c59d0dc2552f06de82ddd5a127fac0a5d9f` (2.58.96) + fix `f06f376f43da96958421e13d5e6b8dbfdc32b801` (тестовый гард round1019; runtime не тронут) + docs-коммит (этот каталог).
**Код-линия поезда:** ADD-EXP `4a09e29a` (ревью `981e9902` NF → RECHECK `d0afd2cc` Approved) + ledger `f1463f10`; **прод-базис:** `113f3a62` (2.58.95).
**Рубежи отката:** новый `release/fix-2.58.95` @ `113f3a62` (создаётся при пуше); авто-откат деплой-скрипта — `release/fix-2.58.94` @ `9072347b`.
**Изоляция:** worktree `%OPENCODE_WORKFLOW_SCRATCH%\release-25896\wt` (detached @ `f06f376f`), интерпретатор `.venv\Scripts\python.exe`; база — отдельный worktree `wt-base` @ `113f3a62`.

| Файл | Что внутри |
|---|---|
| `bump-verify.txt` | bump version-only: 31 файл, каждая изменённая строка = только `2.58.95→2.58.96` (или meta HEAD `b20fe4f7→f1463f10`) |
| `ddl-check.txt` | **ΔDDL = 0**: DDL/миграции (`services/database.py`, migrations-модули, `scripts/`) в дельту не входят |
| `delta-non-plans.txt` | дельта `113f3a62..f06f376f` без `plans/**` (46 файлов) + сводка 75 = 29 plans + 46 non-plans |
| `delta-runtime-stat.txt` | runtime-дельта (10 файлов, ADD-EXP + bump) |
| `deploy-25896-vs-25895.diff.txt` | diff `deploy_25896.py` против ИСПРАВЛЕННОГО `deploy_25895.py` (473686f333fb) — только константы/маркеры поезда |
| `deploy-markers-offline.txt` | исполнение D2/D3-маркеров deploy-скрипта на байтах кандидата — значения совпадают с ожиданиями |
| `deploy-offline-check.txt` | `check_deploy_25896.py`: **EXIT 0** (hashes 14/14, вайтлист == дельта 10/10 (prod..BUMP и prod..HEAD), BUMP ancestor, upload на месте) |
| `focused-base-pre-existing.txt` | прямое доказательство пре-сущ. падений на базе `113f3a62` (worktree `wt-base`) |
| `focused-blast.txt` | сводка фокусных наборов S1–S10 |
| `focused-legacy-guard-fix.txt` | RED→GREEN легаси-гарда round1019: база 7p → кандидат 1f/6p → фикс 7p |
| `focused-legacy-guard-red.txt` | сырой вывод RED-прогона гарда на кандидате до фикса |
| `focused-s1-add-exp.txt` | ADD-EXP контракт `tests/test_add_exp_expression.py` — 31 passed, 1 warning in 3.90s (rc=0) |
| `focused-s10-ui-e2e.txt` | UI e2e `tests/ui_p0a_ux_speech_compact_e2e.py` (Playwright) — == РРўРћР“: failures=0, POST=22 (rc=0) |
| `focused-s2-sec54.txt` | §5.4-наборы (w6 + persistfix + flags-composition) — 49 passed, 1 warning in 4.36s (rc=0) |
| `focused-s3-clusters.txt` | кластеры speech/composer/direct/authorial/sample-library (16 файлов) — 492 passed, 1 warning in 24.04s (rc=0) |
| `focused-s4-capability-registry.txt` | capability/registry sanity — 53 passed in 3.81s (rc=0) |
| `focused-s5-f8-pins.txt` | F8-пины — 29 passed in 5.06s (rc=0) |
| `focused-s6-gen-param-check.txt` | реестр `--check` — CHECK OK: реестр 579 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны. |
| `frozen-fingerprint.txt` | sha256_12 + полные sha256 14 артефактов `EXPECT12`; sha скриптов; bump/fix/база |
| `js-sweep.txt` | `node --check` web/**/*.js + tests/js/**/*.js: files=105 bad=0 |
| `markers-candidate.txt` | маркеры поезда на кандидате (ADD-EXP + spot 2.58.95) — все OK |
| `pytest-attribution.txt` | атрибуция падений run #2: сравнение с 2.58.95; разбор дефекта round1019 и его фикса; пре-сущ. классы |
| `pytest-command-run2.txt` | то же (raw s8b-command) |
| `pytest-command.txt` | команда/окружение run #2 (CWD, HEAD, UTC start/end) |
| `pytest-full.txt` | полный `pytest -q` кандидата **run #2** (после fix `f06f376f`): 9 failed, 14552 passed, 39 skipped, 1 warning in 690.08s (0:11:30) |
| `pytest-run1-red.txt` | полный прогон **run #1** (до fix): 10 failed, 14551 passed, 39 skipped, 1 warning in 735.35s (0:12:15) — RED-доказательство дефекта легаси-гарда |
| `rel96-markers-selfcheck.txt` | сверка всех ожиданий `rel96_final.sh` с байтами кандидата: 41/41 PASS + `bash -n` clean |
| `ui-e2e.json` | полный JSON UI e2e (failures=[], POST=22, 40 notes, скриншоты expression/store/examples) |

Деплой-артефакты (подготовлены в scratch лейна; НЕ запускались, прод не трогался):
`deploy_25896.py` sha256_12 **`b8179a3cdb3f`**, `rel96_final.sh` sha256_12 **`26548559ad7b`**, `check_deploy_25896.py` sha256_12 **`69cf192c0a3a`** (значения — в `frozen-fingerprint.txt`).
Чек-лист приёмки — `../release-25896-report.md` §4.

