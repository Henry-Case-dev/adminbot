# REL-25895 — evidence релиз-пакета **2.58.95** (CFG-03 + POSTGEN-DIAG + VISION-ADAPT)

**Кандидат:** bump-коммит `35b8b455d0dc2552f06de82ddd5a127fac0a5d9f` (2.58.95)
**Код-база (родитель bump-коммита):** `b20fe4f7` (VISION-ADAPT)
**Прод-базис:** `9072347b986b91f05d580a11c1aae6646b250e29` (2.58.94)
**Рубежи отката:** новый рубеж `9072347b` → ветка `release/fix-2.58.94`
(создаётся при пуше — не в этом лейне); предыдущий — `release/fix-2.58.93`
@ `b4d30cab` (2.58.93)
**Изоляция:** worktree `%OPENCODE_WORKFLOW_SCRATCH%\release-25895\wt`
(detached @ `35b8b455`), интерпретатор `.venv\Scripts\python.exe`; для
PIL-зависимых файлов канонический — глобальный `py -3`.

| Файл | Что внутри |
|---|---|
| `frozen-fingerprint.txt` | sha256_12 + полные sha256 9 артефактов `EXPECT12`; sha скриптов; bump/база |
| `bump-verify.txt` | bump version-only: 31 файл, каждая изменённая строка = только `2.58.94→2.58.95` (или meta HEAD `61ecd034→b20fe4f7`) |
| `delta-non-plans.txt` | дельта `9072347b..35b8b455` без `plans/**` (39 файлов) + сводка 146 = 107 plans + 39 non-plans |
| `delta-runtime-stat.txt` | runtime-дельта (5 файлов, **+1052/−38**) |
| `ddl-check.txt` | **ΔDDL = 0**: DDL/миграции (`services/database.py`, migrations-модули, `scripts/`) в дельту не входят |
| `markers-candidate.txt` | маркеры поезда на кандидате (CFG-03 / POSTGEN-DIAG / VISION-ADAPT) — все OK |
| `pytest-full.txt` + `pytest-command.txt` | полный `pytest -q` кандидата (737.70s): **9 failed / 14520 passed / 39 skipped** |
| `pytest-attribution.txt` | 9 failed — точное совпадение множества с прогоном 2.58.94; 39 skipped = PIL в `.venv`; баланс 14559 = 14520p + 39s |
| `focused-blast.txt` | сводка фокусных наборов S1–S10 |
| `focused-s1-vision-adapt.txt` | adapt **43 passed** (`py -3`) |
| `focused-s2-postgen-diag.txt` | postgen **27 passed** (`py -3`) |
| `focused-venv-pil-skips.txt` | `.venv`-варианты (5p/38skip и 26p/1skip) — честная причина skip (нет PIL) |
| `focused-s3-postgen-cluster.txt` | постген-кластер (20 файлов): **447 passed, 39 skipped (PIL), 0 failed** |
| `focused-s4-cfg03.txt` | CFG-03 контракт: **16 passed** |
| `focused-s5-cfg03-cluster.txt` | CFG-03-кластер (10 файлов): **453 passed** |
| `focused-s6-f8-pins.txt` | F8-пины после bump: **29 passed** |
| `focused-s6b-gen-param-check.txt` | реестр `--check`: **579 == REGISTRY** |
| `focused-s7-speech-ui.txt` | speech/UI-наборы (7 файлов): **100 passed** |
| `focused-s8-t5150.txt` | t5150: **5 failed / 2 passed** — пре-сущ. |
| `focused-base-pre-existing.txt` | прямое доказательство: те же 9 падений на **базе** `9072347b` (worktree `wt-base`), 9 failed / 63 passed |
| `js-sweep.txt` | `node tests/js/*_test.js`: **88 файлов / 0 падений** |
| `focused-s10-ui-e2e.txt` | Playwright e2e `tools/ui_cfg03_descriptions_e2e.py`: **RESULT: PASS** |
| `deploy-offline-check.txt` | `check_deploy_25895.py`: **EXIT 0** (hashes 9/9, вайтлист == дельта 5/5, BUMP == HEAD, upload на месте) |

Деплой-артефакты (следующие лейны; скрипты НЕ запускались, прод не трогался) —
в `%OPENCODE_WORKFLOW_SCRATCH%\release-25895\`:
`deploy_25895.py` sha256_12 **`03d52c843908`**,
`rel95_final.sh` sha256_12 **`b912792903f4`**,
`check_deploy_25895.py` sha256_12 **`3e6883288482`**.
Чек-лист приёмки — `../release-25895-report.md` §4.
