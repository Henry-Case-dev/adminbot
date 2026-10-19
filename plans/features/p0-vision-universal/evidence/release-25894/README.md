# REL-25894 — evidence релиз-пакета **2.58.94** (VISION-DL-FIX)

**Кандидат:** bump-коммит `70659be39fca212a40bc2768a485b7bb742af396` (2.58.94)
**Прод-базис:** `b4d30cab364e920d453d2d6a2afe2f95e1c24834` (2.58.93)
**Рубеж отката:** локальная ветка `release/fix-2.58.93` @ `b4d30cab`
**Верификация:** изолированный worktree `%OPENCODE_WORKFLOW_SCRATCH%\release-25894\wt`
(detached @ `70659be3`), интерпретатор `C:\Code\Python\adminbot\.venv\Scripts\python.exe`.

| Файл | Что подтверждает |
|---|---|
| `frozen-fingerprint.txt` | sha256_12 + полные sha256 8 артефактов (`deploy_25894.py::EXPECT12`); база = прод b4d30cab |
| `bump-verify.txt` | bump-коммит версионно-чистый: 31 файл, каждая изменённая строка — только `2.58.93→2.58.94` (или HEAD-штамп meta `1e363143→7c2998b1`) |
| `delta-non-plans.txt` | полная дельта `b4d30cab..70659be3` без `plans/**` (33 файла) |
| `delta-runtime-stat.txt` | runtime-дельта (3 файла, +166/−6) |
| `markers-candidate.txt` | счётчики DL-FIX-маркеров на кандидате (ожидания деплой-скрипта) |
| `focused-blast.txt` | сводка фокусных/бласт-наборов S1–S7 (числа и команды) |
| `focused-s1-vision-dl-fix.txt` | `tests/test_vision_dl_fix.py` → 7 passed |
| `focused-s2-vision-core-195.txt` | свод-195 (vision core + mca19 A–G + rework + addtr_postgen) → 195 passed |
| `focused-s3-media-profile.txt` | профиль media/download/voice/video/avatars (25 файлов) → 741 passed |
| `focused-s4-t5150.txt` | `test_t5150_startup_migrations_round1046.py` → 5 failed (пре-сущ.) |
| `focused-s5-f8.txt` | F8-пара py → 29 passed |
| `focused-s6-gen-param-check.txt` | F8 каталог `--check` → CHECK OK (579 == REGISTRY) |
| `js-sweep.txt` | `node tests/js/*_test.js` → 88 файлов / 0 падений (после бампа пинов) |
| `deploy-offline-check.txt` | `check_deploy_25894.py` против кандидата → EXIT 0 (hashes 8/8, вайтлист == дельта 3/3, BUMP == HEAD, upload на месте) |
| `pytest-full.txt` + `pytest-command.txt` | полный `pytest -q` на кандидате (чистый прогон) |
| `pytest-attribution.txt` | атрибуция падений полного прогона (пре-сущ. + env-флейк) |

Деплой/приёмка (заполняет деплой-лейн ПОСЛЕ выката, НЕ этот пакет):
`deploy/deploy-run.txt`, `deploy/final-verification.txt`,
`deploy/deploy-summary.md`, `acceptance/**` (в т.ч. положительное
распознавание: download→decode→vision→store, `mca_media_analyses`).
