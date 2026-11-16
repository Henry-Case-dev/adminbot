# P0-PROD-DISK-01 — сборка релизного кандидата `2.58.206` (без деплоя)

Дата сборки: 16.11.2026. Статус: **assembly done / REVIEW**; production не
трогался, VERIFIED не заявляется.

- Ветка: `release/p0-prod-disk-2.58.206`
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\p0-prod-disk-01-2a6b1cdc3425-df026980`
  (unit `p0-prod-disk-release-2.58.206`, зарегистрирован глобальным
  `workflow_housekeeping.py`; сохраняется для Reviewer/DevOps).
- База/прод/откат: `bca18c1e` (`2.58.205`, schema 47, DDL 0).
- Retention-кандидат: `122b47de` (`fix/p0-retention-port`), один коммит от
  `bca18c1e`; Reviewer Approved (6 файлов: sidecar/keep=2/CLI/daily/
  fail-closed).
- UI-кандидат: `0cbc5459` (`fix/p0-disk-status-thresholds`), один коммит от
  `bca18c1e`; Reviewer Approved (Playwright + Browser Use; пороги 85/90).
- Bump-коммит: `ebd0160b` (`chore(release): 2.58.206`).
- Историческая ветка `release/mod-acl-m21-2.58.206` (M2.1) **не
  использовалась**; M2.1 выходит отдельно как `2.58.207`.

## 1. Состав (линейная история от базы)

```
bca18c1e (2.58.205, deployed, schema 47)
  -> 122b47de fix(disk): port P0 deploy-retention delta onto 2.58.205 (keep=2 + WAL/SHM)   [merge --ff-only]
  -> da44543d fix(status): P0-PROD-DISK-01 disk thresholds 85/90 on Status (bar-red + text, aria-live)  [cherry-pick 0cbc5459]
  -> ebd0160b chore(release): 2.58.206 - bump APP_VERSION и всех пинов версии
```

`git merge --ff-only 122b47de` — fast-forward. Cherry-pick `0cbc5459` —
без конфликтов (`da44543d`); оба изменения сохранены. Состав кандидатов не
менялся: retention-диф `bca18c1e..122b47de` (6 файлов, +656/−35), UI-диф
`bca18c1e..0cbc5459` (16 файлов, +906/−2) вошли без правок кода.

Cumulative diff `bca18c1e..ebd0160b` (до evidence-коммита):

```
52 files changed, 1593 insertions(+), 68 deletions(-)
```

Из них 30 файлов / 31 строка — стандартная волна пинов версии (bump),
22 файла — код/тесты/доки candidates. Новых модулей, флагов, миграций нет.

## 2. Bump `2.58.205` -> `2.58.206`

По шаблону `bfcccb38` (30 файлов / 31 строка):

- `config/settings.py` — `APP_VERSION = "2.58.206"` + релизная заметка
  2.58.206 и `Prior 2.58.205` (исторический текст сохранён; BOM и CRLF
  сохранены: BOM=true, 30 файлов diff, `git diff --check` exit 0);
- `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION: 2.58.206`;
- 24 py-файла пинов: `assert APP_VERSION == "2.58.206"` /
  `'APP_VERSION = "2.58.206"'` (`test_webapp_round1026_polygon.py` — 2 пина);
- 4 JS harness-пина: `/APP_VERSION = "2\.58\.206"/`.

Исторические упоминания `2.58.205` (release evidence 2.58.205, docs,
фактическое имя deploy-копии в retention-тесте) сознательно не менялись —
это не пины версии.

## 3. Статические проверки

- DDL = 0: в diff `bca18c1e..HEAD` по `services/` и `config/` нет
  `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`, `CREATE INDEX`, `DROP INDEX`,
  `PRAGMA user_version`, `executescript` — 0 совпадений.
- `MigrationStep(` в `services/database.py`: **47** на базе `bca18c1e`,
  **47** на релизной вершине; список не пуст.
- Свежая БД, созданная `DatabaseService.initialize()` на дереве `2.58.206`:

```
APP_VERSION=2.58.206
target_user_version_constant=47
observed_user_version=47
table_count=101
```

- Каталог/настройки не изменились: REGISTRY **645** / GROUPS **121** /
  `_TAB_BY_GROUP` **119** / TAB_RULES **22** / Settings fields **472**
  (как на `bca18c1e`).
- Новых флагов, hot_config, composer, migrations, моделей, агентов,
  планировщиков нет; в delta-путях нет `hot_config`/`composer`/`migration`.
- `deploy_v2.9.2.py` не тронут (`git diff --name-only bca18c1e..HEAD -- deploy_v2.9.2.py` пусто).
- `APP_VERSION` импортируется = `2.58.206`; `py_compile` изменённых
  Python-файлов — OK.

## 4. Тесты (детали — `tests-2.58.206.json`)

| Набор | Объём | Результат |
|---|---|---|
| Retention focused (deploy/round1024/server/memory) | 4 файла | **112 passed / 0 failed** |
| UI+Status pytest (15 файлов, набор UI-кандидата) | 411 тестов | **411 passed / 0 failed** |
| UI node harnesses (p0 + 6 соседних) | 7 скриптов | **7 OK** |
| Playwright UI (`capture_p0_disk_status_ui.py`, 8 сценариев) | 1280×800 и 390×844 | **8 scenarios / 0 errors** |
| Pin-guard (24 py-файла волны пинов) | 860 тестов | **856 passed / 4 failed** (pre-existing, см. ниже) |
| JS pin-харнессы (node) | 4 файла | **4 OK** |
| Broad-выборка `-k "disk or retention or backup or status or release_manifest or deploy_identity"` | 778 тестов | **778 passed / 0 failed** |

Pin-guard: 4 падения **воспроизведены на базе `bca18c1e` в отдельном
detached worktree** теми же node-id и теми же assert-сообщениями
(`assert not True`, `assert 18 == 17`, расхождение canon-списка,
`assert not True`) — pre-existing, кандидатом не вызваны и не чинились:

```
tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff
tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools
tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged
tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline
```

Примечание окружения: pytest запускался с `-s`, иначе в этом shell
subprocess-based node-тесты падают на `DuplicateHandle`
(`WinError 50/6`) — это дефект обёртки окружения, не продукта; с `-s`
тот же набор проходит (47/47 в `test_webapp_js_unit.py`).

## 5. Manifest dry-run (на content-tip `ebd0160b`)

```json
{
  "deployed_at": "2026-11-16T08:54:07.378673Z",
  "deployed_sha": "ebd0160b9a8252b7fd91ec6c7b534cb6f4fecd4d",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/p0-prod-disk-2.58.206",
  "schema": 1,
  "version": "2.58.206"
}
```

`dirty_tracked=false`, `version=2.58.206`, ветка релиза. Полный файл —
`manifest-dry-run.json`. Evidence-коммит меняет tip только метаданными
(файл не может содержать SHA коммита, который его добавляет —
криптографическая неподвижная точка); deploy-time manifest на production
записывает фактически развёрнутый commit сам.

## 6. Откат

- Цель отката: `bca18c1e` (`2.58.205`), schema 47, DDL=0, данные не
  меняются — достаточно вернуть checkout на `bca18c1e` и перезапустить
  сервис. Детали — `rollback.json`.
- Retention-политика — только код; откат кода возвращает прежнее поведение,
  но уже удалённые новым кодом файлы не восстанавливаются (удаление
  необратимо). В этой задаче деплоя и удалений на production не было.

## 7. Ограничения / что не проверено

- Деплой не выполнялся; production effective-state, реальные backups/ и
  `/healthz` не проверялись.
- Playwright-проверка — harness с route-stub `/api/*` и mock Telegram SDK,
  не live TMA и не production-телеметрия.
- 4 pin-guard падения pre-existing и вне scope; не исправлялись.
- Внешние LLM/сетевые сценарии в broad-выборку не входили.

## 8. Housekeeping

- Worktree создан через `worktree-path` и зарегистрирован; остаётся для
  Reviewer/DevOps до вердикта и деплоя (или отказа).
- Временные probe-файлы вынесены в tool-owned run и закрываются после
  сборки; base-check worktree `bca18c1e` удалён, unit-check = complete.
- Доказательства: `assembly.md`, `tests-2.58.206.json`,
  `manifest-dry-run.json`, `rollback.json`, `train-log.md`,
  `ui-playwright-2.58.206.json`, `retention.json` (worktree retained for
  Reviewer/DevOps; unit-check с `--retention-file` — учтён).
