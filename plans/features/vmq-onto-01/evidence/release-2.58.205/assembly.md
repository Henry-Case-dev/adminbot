# VMQ-ONTO-01 — сборка релизного кандидата `2.58.205` (Slice D, без деплоя)

Дата сборки: 15.11.2026. Статус: **assembly done / REVIEW**, production не
менялся, деплоя не было.

- Ветка: `release/vmq-slice-d-2.58.205`
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-slice-d-release-7cbfe0890b57-dd600808`
  (unit `vmq-slice-d-release-2.58.205`, зарегистрирован глобальным
  housekeeping-инструментом; сохраняется для Reviewer/DevOps).
- База поезда (последний развёрнутый релиз): `2b419aa2` (`2.58.204`,
  deployed).
- Код-вершина поезда (замороженная композиция): `69b5c9f9`
  (продуктовый код `456cf769`; implementation `ef568e6f`).
- Bump-коммит: `bfcccb38` (`chore(release): 2.58.205`).
- Evidence Slice D: `8fbd2ffb`, `69b5c9f9` (Docs), `1c66892c`; review-файлы
  r1/r2/r3 добавлены в дерево из плановой линии (см. §1.1).

## 1. Состав поезда (линейно, без мержей)

`git merge-base --is-ancestor` даёт exit 0 на каждой паре; мержей в диапазоне
`2b419aa2..bfcccb38` — **0**.

```
2b419aa2 (2.58.204, deployed)
  -> 693b70e1 fix(vmq-mem): close residual memory/time gaps (Slice D)
  -> bfd87014 docs(vmq-mem): Slice D implementation and measurement evidence
  -> dbaf1a6d docs(vmq-mem): Slice D read-only probe harness
  -> 743a3d1a fix(vmq-mem): address Slice D review r1 (D1-D8)
  -> c4b2c1c2 docs(vmq-mem): review r1 fixes evidence (Slice D)
  -> ef568e6f fix(vmq-mem): L1 memory_scope is the replacement authority (ARCH_DECISION)
  -> 1c66892c docs(vmq-mem): L1-authority evidence and labeled relevance
  -> 456cf769 refactor(vmq-mem): period_replace_allowed exactly as decided
  -> 8fbd2ffb docs(vmq-mem): record Slice D code tip and L1-authority evidence
  -> 69b5c9f9 test(vmq-mem): N9 T3 control measures a real non-empty pool
  -> bfcccb38 chore(release): 2.58.205 - bump APP_VERSION и всех пинов версии
```

Итого 11 коммитов: 4 кодовых (`693b70e1`, `743a3d1a`, `ef568e6f`,
`456cf769`), 6 docs/evidence (`bfd87014`, `dbaf1a6d`, `c4b2c1c2`, `1c66892c`,
`8fbd2ffb`, `69b5c9f9`), 1 bump (`bfcccb38`).
`git merge --ff-only vmq/slice-d` прошёл; HEAD до bump = `69b5c9f9` ровно.

### 1.1 Evidence в дереве кандидата

На ветке `vmq/slice-d` уже были: `slice-d-2026-11-15.md`,
`slice-d-tests-2026-11-15.json`, `corpus-run-slice-d-2026-11-15.json`,
`vector-leg-inventory-2026-11-15.json`, `labeled-relevance-2026-11-15.md`,
`harness-slice-d-2026-11-15/` (README, `measure.py`, `vector_inventory.py`,
`l1_measure.py`), `l1-measure-2026-11-15.json`.

Отсутствовали review-вердикты (`slice-d-review-r1/r2/r3.md`): они лежат в
плановой линии (`master`, коммит `e8f3027b`) и скопированы в дерево
**байт-в-байт** (sha256 совпадает; файлы не переписывались).

Финальный вердикт Reviewer для post-N9 вершины добавлен отдельно из плановой
линии: `plans/features/vmq-onto-01/evidence/vmq-mem/slice-d-final-approval.md`
(источник — `master`, коммит `b9e4fb49`; скопирован байт-в-байт,
sha256 `E5C99B6C80E158BF4DF17568CEEE1444CE570D2CF589A24BD1DD82D60BAE446F`).
Он фиксирует **Approved (predeploy)** для product `456cf769` / evidence tip
`69b5c9f9`, закрытие N9 и перечень неподтверждённых строк (MEM-04/TIME-01,
TIME-02 reply, TIME-07).

Итоговый docs-коммит сборки добавляет review-файлы, финальный вердикт и этот
отчёт. Операционный runbook кандидата — `predeploy.md` (backup/read-back,
откат `2b419aa2`, postdeploy checklist, L1-наблюдение).

## 2. Кумулятивный дифф против базы `2b419aa2`

До bump (`2b419aa2..69b5c9f9`):

```
21 file changed, 4292 insertions(+), 99 deletions(-)
```

из них 11 файлов — продуктовый код/тесты (ниже), 10 — evidence/harness.

После bump (`2b419aa2..bfcccb38`):

```
51 files changed, 4323 insertions(+), 130 deletions(-)
```

Продуктовый состав (11 файлов, `2b419aa2..69b5c9f9`):

```
services/database.py                    |  13 +-
services/direct_chat_service.py         | 279 +++++++++++--
services/mca_retrieval_context.py       | 167 +++++++-
services/tool_router.py                 |  94 +++-
services/turn_trace.py                  |  75 ++-
services/usage_events.py                |   4 +
tests/fixtures/vmq_slice_d_labeled.json | 118 +++++
tests/test_mem_time_policy.py           |  16 +-
tests/test_memory_period_vector_leg.py  |  46 +-
tests/test_vmq_mem_period_intent.py      |   5 +-
tests/test_vmq_mem_slice_d.py           | 780 ++++++++++++++++++++++++
11 files changed, 1498 insertions(+), 99 deletions(-)
```

Лишних путей нет: `config/**` (кроме bump-строки `APP_VERSION`), миграции,
hot_config, composer, DDL — не менялись.

### 2.1 `services/database.py` — ВАЖНО: файл менялся (+10/−3), только чтения

Handoff предполагал «в Slice D `database.py` не менялся». Фактическая
проверка это **не подтверждает**: в `693b70e1` изменён
`DatabaseService.get_author_message_periods` — диапазон лет
`range(base_year-2, base_year-5, -1)` (2024/2023/2022, без 2025) заменён на
`range(base_year-3, base_year)` (2023/2024/2025), плюс обновлён docstring.
Это существующее чтение по индексу `(chat_id, timestamp)` с той же годовой
квотой `limit//5`; вставок/обновлений/удалений нет.

Проверка добавленных строк на
`INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|TRUNCATE|PRAGMA user_version|executescript`
даёт **0** продуктовых совпадений. Кандидат `69b5c9f9` ревьюировался вместе с
этим изменением; исключать его из релиза без отдельного решения нельзя.

### 2.2 DDL и схема: DDL = 0, цель `user_version` = 47

- В диффе `2b419aa2..HEAD` по `services/` и `config/` нет ни одного
  `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`, `CREATE INDEX`, `DROP INDEX`,
  `PRAGMA user_version = …`, `executescript` — grep даёт 0.
- `MigrationStep(` в `services/database.py`: **47** на базе `2b419aa2` и
  **47** на вершине `bfcccb38`; новых ступеней нет.
- Свежая БД, созданная `DatabaseService.initialize()` на дереве `2.58.205`:

```
APP_VERSION=2.58.205
target_user_version_constant=47
observed_user_version=47
table_count=101
```

### 2.3 Новых флагов/настроек нет

На дереве `2.58.205` после bump:

```
REGISTRY 645 GROUPS 121 TAB_BY_GROUP 119 TAB_RULES 22 fields 472
```

Совпадает с базой `2.58.204`: каталог 645→645, новых флагов, настроек,
промптов, моделей, агентов и планировщиков Slice D не добавляет.

## 3. Bump `2.58.204` → `2.58.205`

Коммит `bfcccb38`, та же волна пинов, что в предыдущих релизах:

```
30 files changed, 31 insertions(+), 31 deletions(-)
```

- `config/settings.py` — `APP_VERSION = "2.58.205"` + релизная заметка
  2.58.205 и `Prior 2.58.204` (исторический текст сохранён; BOM и CRLF
  сохранены — проверено: BOM=true, CRLF=3629, diff файла 1 строка);
- `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION: 2.58.205`;
- 24 py-файла релизных пинов — 25 вхождений
  (`test_webapp_round1026_polygon.py` — 2 строки, остальные по одной);
- 4 JS-харнесса — экранированный регексп `2\.58\.205`.

Всего 32 замены версии в 30 файлах. Исторические упоминания `2.58.204`
(evidence `release-2.58.204/**`, комментарий-история `config/settings.py`,
`plans/**`) не переписывались — это не пины. В `tests/` и `tests/js/`
вхождений `2.58.204` не осталось.

Проверки bump-вершины:

- `python -m py_compile` для `config/settings.py` и затронутых
  `services/{database,direct_chat_service,mca_retrieval_context,tool_router,
  turn_trace,usage_events}.py` — exit 0;
- `git diff --check` — exit 0;
- `from config.settings import APP_VERSION` → `2.58.205`.

## 4. Тесты на bumped-вершине

Окружение: `C:\Code\Python\adminbot\.venv` (Python 3.12.0, pytest 9.1.1),
cwd = дерево поезда; `node v24.16.0`.

| Набор | Файлов | Результат `bfcccb38` |
|---|---|---|
| Slice D/B/C/period/unified/mem_time/vector/contracts (17 файлов) | 17 | **447 passed** |
| Direct chat + tool router (7 файлов) | 7 | **355 passed** |
| Pin-guard (24 py-файла релизных пинов) | 24 | **856 passed / 4 failed** |
| JS pin-харнессы (node) | 4 | **4 OK** |
| Каталог параметров + settings-хелперы | 3 | **94 passed** |
| Broad-выборка `-k "memory or retrieval or graphrag or persona or tool_router or mca07 or mca13 or mca22 or mem_time or mem08 or history_isolation or direct_chat or turn_trace or selection"` | 2370 собранных | **2364 passed / 5 failed / 1 error** (4 батча по node-id, тот же `-k`) |

Slice D-набор включает: `test_vmq_mem_slice_d/_b/_c`,
`test_vmq_mem_period_intent`, `test_mem_time_policy`,
`test_memory_period_vector_leg`, `test_memory_unified_retrieval(_06)`,
`test_memory_contracts`, `test_mem_time_asof/_profile/_l1_scope`,
`test_mca07_retrieval_context_round1027`, `test_memory_attribution`,
`test_history_isolation`, `test_mca18_memory_subject_block_b_round1042`,
`test_vmq_mem_retrieval_fixes`.

Предсуществующие падения pin-guard (те же 4 ID падают на базе `2b419aa2`,
проверено отдельным прогоном: **4 failed**):

- `tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

Это пины «канон инструментов / запрещённые пути диффа относительно своего
базового коммита», разъехавшиеся до этого кандидата; в Slice D не
исправлялись (вне scope).

Broad-выборка (2370 собранных тестов, тот же `-k`, разбита на 4 батча по
node-id для устойчивости к обрывам сессии) дала **2364 passed / 5 failed /
1 error** — те же pre-existing шесть, что в прошлом прогоне Slice D:

- `test_asap5_graphrag_recovery.py::test_warning_coalesced_not_repeated`
- `test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced`
- `test_image_generation_round1023.py::TestPreGateIntegration::test_direct_chat_image_off_eight_tools`
- `test_soul1_w5_observer_gates.py::test_initiative_writer_shares_core_style_and_persona`
- `test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::test_style_anchors_not_broken`
- error: `test_youtube_multimodal_download_round1024.py::TestDownloadPublishMultimodal::test_multimodal_success_writes_no_memory`

## 5. Manifest dry-run

`.deploy/` не создавался (`--dry-run`), production-манифест не трогался.
На bump-вершине `bfcccb38`:

```json
{
  "deployed_at": "2026-11-15T09:15:22.252755Z",
  "deployed_sha": "bfcccb38d5b423dd64d96edabb52f07184248edb",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/vmq-slice-d-2.58.205",
  "schema": 1,
  "version": "2.58.205"
}
```

`previous_*` = `null`, потому что в dev-worktree нет `.deploy/release.json`
(он существует только на прод-хосте и не читался). После evidence-коммита
dry-run повторён на итоговой вершине ветки: `version=2.58.205`,
`dirty_tracked=false`, `release_branch=release/vmq-slice-d-2.58.205`,
`deployed_sha` = tip ветки (точное значение — в handoff, т.к. файл evidence
не может содержать SHA коммита, который его же и создаёт).

## 6. Откат

- Целевой откат: `2b419aa2` (`2.58.204`, deployed).
- Схема и данные не меняются: schema 47, DDL=0, миграций нет; откат —
  переключение checkout на `2b419aa2` + штатный restart.
- Откат bump-коммита отдельно не нужен: bump меняет только строки версии.
- Если откатывается только продуктовый слой Slice D — база остаётся
  совместимой (все изменения — чтения; новых таблиц/колонок нет).

## 7. Честные ограничения

- Это шаг **сборки кандидата**, а не приёмки: деплоя и живых прогонов
  Telegram/провайдера/UI нет. VERIFIED не заявляется.
- `services/database.py` в Slice D **менялся** (+10/−3, read-only loop fix) —
  это отличается от предположения handoff и зафиксировано в §2.1.
- Финальный вердикт Reviewer для post-N9 вершины сохранён:
  `slice-d-final-approval.md` (Approved (predeploy) для `456cf769` /
  `69b5c9f9`, N9 закрыт). Это predeploy-одобрение, а не VERIFIED:
  MEM-04/TIME-01, TIME-02 reply и TIME-07 в нём явно не подтверждены.
- L1 `memory_scope` на пяти запросах не измерен (нет ключа LLM; в копии БД
  нет durable L1-плана) — отдельная находка Slice D, не блокер сборки.
- Векторная нога `compat_not_proven`; семантика на лексическом пути
  ограничена основами.
- Прогнаны точечные и broad-`-k` наборы, а не весь suite проекта; broad ≠
  полное покрытие.
- 4 pre-existing падения pin-guard не исправлялись (вне scope).

## 8. Housekeeping и следующий шаг

- worktree сохранён для Reviewer/DevOps; unit
  `vmq-slice-d-release-2.58.205` зарегистрирован; `retention.json` — рядом.
- прогоны/скрипты сборки — в
  `WorkspaceData/runs/.../vmq-slice-d-release-7cbfe0890b57/probe-55128b6434`
  и закрываются `run-close` после передачи чисел в evidence.
- следующий шаг: дельта-ревью `2b419aa2..<tip>`; деплой — только после
  одобрения (в этой задаче не выполняется).
