# REL-25893 — evidence релиз-пакета **2.58.93** (CFG-02C)

**Лейн:** RELEASE-PKG-93 (writer; без деплоя/SSH-записей). **Дата:** 19.10.2026.
**Кандидат:** bump-коммит `74160a5d9b893378a93e722e76424ee0d3f74906` (2.58.93)
= master-линия прод-2.58.92 (`1d367e4c`) + CFG-02C (`1d9a7107`) + доки
(`77e7dd5a`/`26ebc0a8`/`3492fc45`/`1e363143`) + bump (31 файл).
**Верификация:** изолированный worktree
`OPENCODE_WORKFLOW_SCRATCH\release-25893\wt` @ `74160a5d` (detached; главное
дерево для прогонов кандидата не использовалось).
**Прод до релиза:** 2.58.92 @ `1d367e4c` (ветка рубежа `release/fix-2.58.92`
создана локально на `1d367e4c`).

## Файлы

| Файл | Что |
|---|---|
| `delta-non-plans.txt` | полная дельта `1d367e4c..74160a5d` без `plans/**` (44 файла) |
| `delta-runtime-stat.txt` | stat 9 runtime-файлов (+356/−23) |
| `frozen-fingerprint.txt` | sha256_12 + полные sha256 14 артефактов (`deploy_25893.py::EXPECT12`) |
| `pytest-full.txt` | полный `pytest -q`, **чистый** прогон (10 failed / 14465 passed, 713.93s) — основной evidence |
| `pytest-full-parallel.txt` | полный `pytest -q`, прогон ПАРАЛЛЕЛЬНО с фокусными (10 failed / 14465 passed, 787.81s; 10-е падение — флейк `test_nostalgia_worker`) |
| `pytest-clean-command.txt` | CWD/HEAD/команда/START-END/EXIT/tail чистого прогона |
| `pytest-parallel-command.txt` | то же для параллельного прогона |
| `pytest-attribution.txt` | атрибуция: 9 pre-existing + environment-флейк random_source (разный тест в двух прогонах) |
| `focused-blast.txt` | сводка бласт-наборов CFG-02C (19/135/308/286/263/176/90/22 + 29 + 579) |
| `focused-raw.txt` | raw-логи фокусных наборов S1–S9 |
| `nostalgia-iso.txt` | изоляция `tests/test_nostalgia_worker.py` — 26 passed |
| `soul1w5-iso.txt` | изоляция `tests/test_soul1_w5_initiative_vitality.py` — 18 passed |
| `js-sweep.txt` | `node tests/js/*_test.js` (88 файлов / 0 падений) |
| `ui-e2e.txt` | `tools/ui_cfg02c_image_isolation_e2e.py` (RESULT: PASS) |
| `gen-param-check.txt` | `tools/gen_param_registry_round1025.py --check` (579 OK) |
| `deploy-offline-check.txt` | `check_deploy_25893.py` против кандидата (EXIT 0) |

## Ссылки

- Релиз-док: `plans/features/cfg/release-25893-report.md` (состав, дельта,
  проверки, чек-лист §Ф6, откат, риски, деплой-артефакты, фингерпринт).
- Ревью слайса: `plans/features/cfg/review-cfg-02c.md` (`77e7dd5a`, Approved;
  `CFG-02C.5` → READY_FOR_LIVE postdeploy).
- Эвиденс слайса: `plans/features/cfg/evidence/cfg-02c/**` (RED→GREEN,
  бласт-радиус, UI-скриншоты, fingerprint).
- Деплой-артефакты (scratch, НЕ запускались):
  `%OPENCODE_WORKFLOW_SCRATCH%\release-25893\{deploy_25893.py (sha12 ab71cc472dd7),
  rel93_final.sh (sha12 9b10fa2875b4), check_deploy_25893.py (sha12 6dc01284f2a6)}`.
