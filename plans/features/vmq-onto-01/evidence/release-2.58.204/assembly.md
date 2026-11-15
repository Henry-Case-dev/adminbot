# VMQ-ONTO-01 — сборка релизного поезда `2.58.204` (сборка, без деплоя)

Дата сборки: 15.11.2026. Статус: **assembly done / REVIEW**, production не
менялся, деплоя не было.

- Ветка: `release/vmq-onto-01-2.58.204`
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-onto-01-3689dd92710d-3177a5d0`
  (unit `vmq-onto-01-release-2.58.204`, зарегистрирован глобальным
  housekeeping-инструментом; сохраняется для Reviewer/DevOps).
- База поезда (последний развёрнутый релиз): `c97c06e4` (`2.58.203`).
- Код-вершина поезда (замороженная композиция): `16931216`.
- Bump-коммит: `735af15b` (`chore(release): 2.58.204`).

## 1. Состав поезда (линейно, без мержей)

| # | SHA | Коммит | Срез |
|---|---|---|---|
| 1 | `8cb9e00d` | `fix(onto-a): require chat_scope for every typed entity type (O-01 R1)` | ONTO-A (с R1-коррекцией) |
| 2 | `d15b13da` | `feat(onto-b): typed relation projection with direction/author/time/provenance (O-03)` | ONTO-B |
| 3 | `f7a9c596` | `refactor(vmq-m2): compact plan-scope rebuild call (no behaviour change)` | M2 (M-04/O-04) |
| 4 | `570a49db` | `fix(vmq-mem): period intent keeps the target year; honest vector admission (Slice A)` | Slice A |
| 5 | `d159ea8a` | `fix(vmq-mem): subject chronology and relations projection (Slice B)` | Slice B |
| 6 | `16931216` | `fix(vmq-mem): M2 overview trigger uses structured period intent (Slice C)` | Slice C |

Линейность проверена (`git merge-base --is-ancestor`, exit 0 на каждой паре):

```
c97c06e4 -> 8cb9e00d -> d15b13da -> f7a9c596 -> 570a49db -> d159ea8a -> 16931216
```

Все шесть кандидатов и база `c97c06e4` — предки `16931216`; мержей в диапазоне
нет (`c97c06e4..16931216` = 19 коммитов, из них 6 кодовых шагов выше и
13 docs/evidence-коммитов тех же срезов).

## 2. Кумулятивный дифф против плана PM

`git diff --stat c97c06e4 16931216` до bump:

```
23 files changed, 8996 insertions(+), 198 deletions(-)
```

Совпадает с планом PM (23 файла, +8996/−198). Файловый состав — ровно
ожидаемый, лишних путей нет:

- `plans/features/vmq-onto-01/evidence/**` — 12 файлов (evidence срезов
  ONTO-A, ONTO-B, M2, Slice A, Slice B; только документация);
- `services/` — 5 файлов: `semantic_contracts.py` (+1746), `mca_retrieval_context.py`
  (+1141), `direct_chat_service.py`, `tool_router.py`, `database.py`;
- `tests/` — 6 файлов: `test_semantic_contracts.py`, `test_memory_unified_retrieval.py`,
  `test_vmq_mem_period_intent.py`, `test_vmq_mem_slice_b.py`, `test_vmq_mem_slice_c.py`,
  `test_mem_time_policy.py`.

Замороженные «не трогать»-зоны проверены по списку имён диффа
(`SELECT-STRING` по `direct_context_composer|migration|config/|mca_gates|hot_config`
дал 0 совпадений):

- `services/direct_context_composer.py` — не менялся;
- `config/**` (включая `config/settings.py`) — в кодовой части поезда не менялся;
- `mca_gates.py`, `hot_config.py` — не менялись;
- миграции/схема — не менялись (раздел 2.2).

### 2.1 `services/database.py` — только чтения

`git diff --numstat` = **+185/−25**. Все добавленные SQL-операторы — `SELECT`
(CTE `WITH … AS`, `ROW_NUMBER() OVER`, подзапросы) и чтения через
`self.db.execute(...)` без записи. Проверка добавленных строк на
`INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|TRUNCATE|PRAGMA user_version|executescript`
даёт **0** продуктовых совпадений (единственные совпадения — комментарии
`# pragma: no cover`).

Снятые 25 строк — не удаление поведения: существующий блок резолва
`source_ref_id` субъекта вынесен 1:1 в `_subject_ref_id()` (тот же SQL, те же
параметры, тот же `fact_attribution_enabled()`-гейт и те же `logger.debug`),
`_person_scope_clause()` вызывает его. Новые чтения появляются только в новых
методах (`get_subject_profile_facts` — Slice B, `list_*` связи/периоды — ONTO/M2).

### 2.2 DDL и схема: DDL = 0, цель `user_version` = 47

- В продуктовых строках диффа поезда нет ни одного `CREATE TABLE`,
  `ALTER TABLE`, `DROP TABLE`, `CREATE INDEX` или `PRAGMA user_version = …`
  (3 совпадения по всему диффу — только evidence-документ и тест, читающий
  `PRAGMA user_version` для проверки неизменности).
- `MigrationStep(` в `services/database.py`: **47** на базе `c97c06e4` и **47**
  на вершине `16931216` — ни одна ступень не добавлена; текущая цель —
  `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47`.
- Проверка на живом коде (не только по диффу): свежая БД, созданная
  `DatabaseService.initialize()` на дереве `2.58.204`:

```
APP_VERSION=2.58.204
target_user_version_constant=47
observed_user_version=47
table_count=101
```

### 2.3 Новых флагов/настроек нет

На дереве `2.58.204` после bump:

```
REGISTRY 645 GROUPS 121 TAB_BY_GROUP 119 TAB_RULES 22 fields 472
```

Совпадает с базой `2.58.203` (645/121/119/22, 472 поля `Settings`): каталог
параметров 645→645, новых флагов, настроек, промптов, моделей, агентов и
планировщиков поезд не добавляет.

## 3. Bump `2.58.203` → `2.58.204`

Коммит `735af15b`, ровно та же волна пинов, что в предыдущих релизах:

```
30 files changed, 31 insertions(+), 31 deletions(-)
```

- `config/settings.py` — `APP_VERSION = "2.58.204"` + релизная заметка
  2.58.204 и `Prior 2.58.203` (исторический текст сохранён, BOM и CRLF файла
  сохранены; первая попытка записи сняла BOM и была откачена до коммита —
  итоговый дифф файла 1 строка);
- `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION: 2.58.204`;
- 24 py-файла релизных пинов — 25 вхождений (`test_webapp_round1026_polygon.py`
  — 2 строки, остальные по одной);
- 4 JS-харнесса — экранированный регексп `2\.58\.204`.

Продуктовая логика не менялась: в bump-коммите нет ни одного файла вне
перечисленных 30, все изменения — строки версии. Исторические упоминания
`2.58.203` (комментарии `services/checkup_prompts.py`,
`services/prompt_registry.py`, фикстуры `test_smart_corrective_*` и evidence)
не переписывались — это не пины.

Проверки bump-вершины:

- `python -m py_compile` для `config/settings.py`, `services/{semantic_contracts,
  mca_retrieval_context,direct_chat_service,tool_router,database}.py` — exit 0;
- `git diff --check` — exit 0 (пробельных ошибок нет);
- `from config.settings import APP_VERSION` → `2.58.204`.

## 4. Тесты на bumped-вершине (сравнение с pre-bump)

Окружение: `C:\Code\Python\adminbot\.venv` (Python 3.12.0, pytest 9.1.1),
cwd = дерево поезда. Каждый набор прогнан дважды: на pre-bump вершине
`16931216` и на bumped-вершине `735af15b`.

| Набор | Файлов | Pre-bump `16931216` | Bumped `735af15b` |
|---|---|---|---|
| Contract-наборы поезда (`semantic_contracts`, `memory_unified_retrieval`, `mem_time_policy`, `vmq_mem_period_intent`, `vmq_mem_slice_b`, `vmq_mem_slice_c`) | 6 | **156 passed** | **156 passed** |
| Direct chat + tool router (`test_direct_chat{,_concurrency,_handlers,_lore_inject,_prompts,_relations_inject}`, `test_tool_router`) | 7 | **355 passed** | **355 passed** |
| Pin-guard (24 py-файла релизных пинов) | 24 | **856 passed / 4 failed** | **856 passed / 4 failed** |
| JS pin-харнессы (node) | 4 | **4 OK** | **4 OK** |
| Каталог параметров + settings-хелперы (`test_param_catalog`, `test_summary_param_catalog_annotation_asap41`, `test_settings_helpers`) | 3 | **94 passed** | **94 passed** |
| Память: смежные наборы (`memory_unified_retrieval_06`, `vmq_mem_retrieval_fixes`, `memory_period_vector_leg`, `mem_time_asof/_profile/_l1_scope`, `memory_contracts`, `mca07_retrieval_context_round1027`, `memory_attribution`, `mca18_memory_subject_block_b_round1042`) | 10 | **291 passed** | **291 passed** |

Итог по прогнанному: **1752 passed / 4 failed** на обеих вершинах —
**новых падений от bump нет**, наборы идентичны по составу тестов.

Известные pre-existing падения (те же 4 теста на base и на bumped-вершине,
к поезду отношения не имеют):

- `tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

Это пины «канон инструментов / запрещённые пути диффа относительно своего
базового коммита», разъехавшиеся задолго до этого поезда; в этом кандидате
они не исправлялись (вне scope) и отдельно не ухудшались.

## 5. Manifest dry-run

`.deploy/` не создавался (`--dry-run`), production-манифест не трогался.

На bump-вершине `735af15b`:

```json
{
  "deployed_at": "2026-11-15T02:35:23.531801Z",
  "deployed_sha": "735af15bf0bbb029f2e6aec3e3cc5cd4aae64ccb",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/vmq-onto-01-2.58.204",
  "schema": 1,
  "version": "2.58.204"
}
```

`previous_*` = `null`, потому что в dev-worktree нет своего `.deploy/release.json`
(он существует только на прод-хосте и не читался). На итоговой вершине ветки
dry-run повторён после evidence-коммита: `version=2.58.204`,
`dirty_tracked=false`, `release_branch=release/vmq-onto-01-2.58.204`,
`deployed_sha` = tip ветки (точное значение — в handoff, т.к. файл evidence
не может содержать SHA коммита, который его же и создаёт).

## 6. Честные ограничения

- Это шаг **сборки поезда**, а не приёмки: ни деплоя, ни живых прогонов
  Telegram/провайдера/UI здесь нет. Реальная проверка поведения после выката —
  Reviewer/DevOps по своей процедуре после дельта-ревью.
- Прогнаны **точечные** наборы (влияющие на срезы и их прямые соседи), а не
  полный suite проекта; числа выше не являются утверждением о полном покрытии.
- `DDL = 0` доказан двумя способами (нет DDL-операторов в диффе; 47 ступеней
  миграций на базе и вершине + фактический `PRAGMA user_version = 47` на
  свежей БД). Продакшн-БД при сборке не открывалась.
- Замороженная композиция `16931216` **не включает** docs-трио Slice C
  (`plans/features/vmq-onto-01/evidence/vmq-mem/slice-c-2026-11-15.md`,
  `slice-c-retention-2026-11-15.json`, `slice-c-tests-2026-11-15.json`) —
  они лежат отдельным docs-коммитом `8bc2bcf7` на `vmq/mem-c` поверх
  `16931216` (3 файла, +296, только документация). В поезд по инструкции не
  добавлялись; решение (довозить ли docs-коммит) — за PM/Reviewer.
- 4 pre-existing падения pin-guard'ов не исправлялись: они не вызваны этим
  кандидатом (идентичны на base) и относятся к другим пинам.
- Ассамблея не меняла `plans/current_task.md`, карты требований и прод-среду.

## 7. Housekeeping и следующий шаг

- worktree сохранён для Reviewer/DevOps (ветка
  `release/vmq-onto-01-2.58.204`, зарегистрирован как unit
  `vmq-onto-01-release-2.58.204`);
- одноразовые probe-артефакты сборки (скрипт bump, DDL-проба, логи наборов,
  dry-run вывод) лежат в `WorkspaceData/runs/.../probe-4c97a7ca64` и
  закрываются штатным `run-close` после передачи чисел в этот документ;
- следующий шаг: дельта-ревью Reviewer по `c97c06e4..<tip>`; деплой — только
  после одобрения (в этой задаче не выполняется).
