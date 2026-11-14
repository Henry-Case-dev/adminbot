# SMART-CORRECTIVE-01 — сборка релизного поезда 2.58.201

Собрано Builder-ом 15.11.2026 в управляемом worktree
`WorkspaceData/worktrees/c742e4de9e92c489/smart-corrective-01-0097aecc4a7a-6fc68e04`
(ветка `release/smart-corrective-01`). Деплой не выполнялся, master-планы не
менялись.

## 1. База

- `release/2.58.200` = `13884daa32e5cf2a1c05c5c43188ca299f8179f8`.
- Код базы совпадает с развёрнутым `0e4a144d` (bump 2.58.200 на `1d9cf251`).

## 2. Интегрированные ветки

| Ветка (head) | Код-тип | Содержимое |
|---|---|---|
| `sc/corrective-s5d` = `343fdfa2` | `4185803c` | цепочка сторожа S5A → S5B → S5C → S5D (W-01/W-10/W-11 и др.) |
| `sc/corrective-s6` = `717bcc61` | `5d2eb427` | корректива S1/S2 → S3 → S4 → S3B → S6 (`163b8ddd`, `8ccd0730`, `1bbe767d`, …) |
| `sc/fc-12-09` = `47090158` | `1e82806a` | фактчек SFC-12-09 (склейка запроса: собственный claim-юнит и запрос) |

Все три ветки отведены от одной базы `13884daa` (merge-base проверен для
каждой).

## 3. Merge-коммиты

- `c98d7389` — `merge(release-train): smart-corrective-01 watchdog chain S5A-S5D (code tip 4185803c)`
- `99c61f0a` — `merge(release-train): smart-corrective-01 corrective chain S1S2-S3-S4-S3B-S6 (code tip 5d2eb427)`
- `35104577` — `merge(release-train): smart-corrective-01 FactCheck SFC-12-09 fix (code tip 1e82806a)`

Порядок: сторож → корректива → фактчек. Все три merge чистые (`ort`), без
ручных разрешений.

## 4. Конфликты

**Нет.** Ни один merge не потребовал правок. Дополнительно проверено:
для каждой ветки файлы кода, изменённые ею относительно базы, в объединённом
дереве **байт-в-байт** совпадают с версией ветки
(`git diff <branch> HEAD -- <files>` пусто; 18 + 23 + 3 = 44 файла кода).
Маркеров конфликтов в `services/`, `config/`, `tests/` нет.

## 5. Runtime-полнота

- Импорт и `APP_VERSION` проверены на объединённом дереве (`2.58.200` до bump).
- Каталог параметров `services.param_catalog.REGISTRY` = **645**, GROUPS = **121** —
  как на базе; новых флагов/настроек/промптов корректива не добавляет
  (изменения `config/settings.py` в S6 — только комментарии-политика).
- Схема БД: цель `user_version` = **47**, `services/database.py` не изменён,
  `migrate_history/` не менялся → DDL = 0.
- Мастер-планы (`plans/`) для рантайма не требуются: изменения кода лежат в
  `services/`, `config/`, `tests/`; `plans/**` в поезде — только evidence.

## 6. Bump версии 2.58.200 → 2.58.201

Формат повторяет `0e4a144d` (30 файлов / 31 строка):

- `config/settings.py` — `APP_VERSION = "2.58.201"` + релизная заметка
  2.58.201 и `Prior 2.58.200` (исторический текст сохранён);
- `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION: 2.58.201`;
- 24 py-файла релизных пинов (`assert APP_VERSION == "2.58.201"`,
  `test_webapp_round1026_polygon.py` — 2 строки);
- 4 JS-харнесса: экранированный регексп `2\.58\.201`.

`git diff` bump-коммита: `30 files changed, 31 insertions(+), 31 deletions(-)`.
Исторические/смысловые упоминания `2.58.200` (комментарии
`services/checkup_prompts.py`, `tests/test_checkup_prompts.py`, фикстуры
`test_smart_corrective_*`, `test_factcheck_subject_contract.py`,
`test_evol_source_reader.py`, `test_smart_e_local_first_source.py`) не
переписывались — это не пины.

Bump-коммит: `051ab76ae51bf0f2cdf7783187756518782b6ab0`.

## 7. Manifest dry-run (чистое дерево)

`python tools/release_manifest.py --repo-root . --dry-run` на `051ab76a`:

```json
{
  "deployed_at": "2026-11-14T12:35:00.697557Z",
  "deployed_sha": "051ab76ae51bf0f2cdf7783187756518782b6ab0",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/smart-corrective-01",
  "schema": 1,
  "version": "2.58.201"
}
```

`.deploy/` не создавался (`--dry-run`). После коммита с этой evidence-записью
dry-run повторён на итоговой вершине ветки: `version=2.58.201`,
`dirty_tracked=false`, `deployed_sha` == head ветки (значение совпадает с
`git rev-parse release/smart-corrective-01` и приведено в handoff).

## 8. Тесты (main venv `C:\Code\Python\adminbot\.venv`, cwd = дерево поезда)

| Набор | Файлов | Результат |
|---|---|---|
| Корректива S1/S2–S6 | 14 | **379 passed** |
| Сторож S5A–S5D + инциденты | 5 | **70 passed** |
| Фактчек SFC-12-09 | 2 | **92 passed** |
| Приёмочный набор прежнего релиза | 17 | **364 passed** |
| FACTCHECK (15 файлов прежнего релиза) | 15 | **283 passed** |
| Pin-guard (24 py-пина) | 24 | **856 passed / 4 failed** |
| Broad smoke (26 файлов прежнего релиза) | 26 | **1040 passed / 12 failed** |
| JS pin-харнессы (node) | 4 | **4 PASS** |
| Речь/промпты (`test_speech_*`, asap speech, initiative speech …) | 19 | **258 passed / 5 failed** |
| Настройки/пины фронта + `test_param_catalog` | 9 | **217 passed / 1 failed** |
| Чекап-хендлеры, prompt journal, expression, asap8_f4, incident package | 5 | **104 passed** |

Компиляция: `py_compile` по 44 изменённым `.py` — exit 0.
`git diff --check` — 0.

## 9. Сверка известных падений (без новых)

- Pin-guard **4** — те же идентификаторы, что в базовом отчёте 2.58.200:
  `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`,
  `::TestBounds::test_forbidden_paths_out_of_diff`,
  `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`,
  `::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`.
- Broad smoke **12** — тот же список: `test_budget_global_toggle_round1024` (3),
  `test_budget_guardrails_round1024` (2 menu-freeze),
  `test_budget_overrides_merge_round1024` (6),
  `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface` (1).
- Речь/промпты **5** — воспроизведены на базе `13884daa`
  (те же 5, `258 passed` на базе) → pre-existing, не регрессия поезда:
  `test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::test_style_anchors_not_broken`,
  4 × `test_initiative_speech_layers_chat_overrides.py` (устаревший
  `_StubService` без `_writer_evidence_capacity`, метод есть уже на базе).
- Настройки **1** — воспроизведён на базе `13884daa`:
  `test_chat_settings_seed_round1019.py::TestNoHardcodedId::test_chat_id_absent_from_services`
  (`database.py`).

Новых падений относительно базы — **0**.

## 10. Итог

- Код-вершина поезда: `051ab76a` (bump 2.58.201).
- Вершина ветки: коммит с этой записью (`docs(release): 2.58.201 …`), он же
  push-вершина `release/smart-corrective-01`; SHA в handoff.
- Кумулятивно от базы: `93 files changed, 13576 insertions(+), 360 deletions(-)`
  (из них код/тесты — 72 файла, `10417/359`; остальное — evidence `plans/**`).
- Worktree остаётся зарегистрированным до деплоя (нужен DevOps). Пробные
  прогоны закрыты, evidence перенесён в репозиторий.

## 11. Addendum 2.58.202 — guard S6 «сохранённая редакция чата»

Ветка `sc/corrective-s6-guard` (head `703b2877`, код `a8b6197f`) — прямой
потомок `409f4e8a` (2.58.201, развёрнут). Merge: **`f08d4996`**
(`merge(release-train): smart-corrective-01 S6 prompt guard, saved chat edition
over factory cutover (code a8b6197f)`), конфликтов нет.

Содержимое merge (7 файлов, 558+/11-): `services/prompt_release_policy.py`
(живая ручная ревизия адресата + `read_live_manual_revision` + код
`factory_superseded_manual`), `docs/prompt-versioning-contract.md`,
`tests/test_smart_corrective_prompt_delivery.py`, `tests/test_prompt_baseline.py`,
`tests/test_evol016_prompt_activation.py`, evidence `s6-prompt-guard/*`.
Текст и метки заводских промптов не менялись; каталог 645/121, схема v47,
DDL=0.

Bump 2.58.201 → 2.58.202: **`a476818d`**, тот же набор — 30 файлов / 31 строка
(`APP_VERSION` + релизная заметка 2.58.202 с `Prior 2.58.201`, F8-meta,
24 py-пина, 4 JS-регекспа `2\.58\.202`).

### Тесты (main venv, дерево поезда)

| Набор | Результат |
|---|---|
| Guard/S6 (17 файлов: prompt_delivery + prompt-релиз/история) | **320 passed, 2 skipped** |
| Чекап/совместимость промптов (13 файлов) | **331 passed** |
| Регрессия/смежные (14 файлов) | **264 passed / 1 failed** (`test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface`) |
| Базовая линия/активация (14 файлов) | **274 passed, 2 skipped / 1 failed** (тот же `test_prompt_field_audit`) |
| Sanity: сторож S5A-D + инциденты + FC SFC-12-09 + tool-loop/router + source reader + selfdiag research | **328 passed** |
| Pin-guard (24 py-пина) | **856 passed / 4 failed** — те же 4 известных |
| JS pin-харнессы (node, 4) | **4 PASS** |
| `py_compile` изменённых `.py` (4) | exit 0; `git diff --check` — 0 |

### Сверка pre-existing падений (на `409f4e8a`, чистое дерево)

`pytest tests/test_prompt_field_audit.py tests/test_soul1_registry_completeness.py`
→ `2 failed, 25 passed`: `test_every_editable_prompt_has_reachable_surface`
(reachable-surface учёт `direct.base.synthesizer`) и
`test_registry_consumer_pointers_point_at_real_lines` (`lore_worker.py`
line-pointer). Оба падения воспроизведены на развёрнутой вершине 2.58.201 —
unchanged, не регрессия guard-дополнения. Новых падений: **0**.

### Manifest dry-run (чистое дерево, `a476818d`)

```json
{
  "deployed_at": "2026-11-14T14:41:28.271291Z",
  "deployed_sha": "a476818de5b60ccf18b00709e4c02bc7fec099eb",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/smart-corrective-01",
  "schema": 1,
  "version": "2.58.202"
}
```

### Итог дополнения

- Merge-коммит: `f08d4996`; bump-коммит: `a476818d`.
- Кумулятивно от `409f4e8a`: 37 файлов, 589+/42- (код/тесты — 34 файла,
  354+/41-; остальное — evidence `plans/**`).
- Вершина ветки: коммит с этой записью (`docs(release): 2.58.202 guard
  addendum`), он же push-вершина `release/smart-corrective-01`; SHA в handoff.
- Worktree сохранён для DevOps, пробные прогоны закрыты.

---

# 2.58.203 — label + anchor addendum

Дополнение поезда на базе `0beed63d` (2.58.202, развёрнут). Два среза прошли
независимое ревью как `Approved` на своих ветках и слиты в тренировочную ветку
без правок кода.

## 1. Ветки и merge-коммиты

| Срез | Ветка (head) | Код | Merge-коммит |
|---|---|---|---|
| S6-ACTIVATION (метка заводской ревизии чекапа) | `sc/corrective-checkup-label` = `fd2b4bb0` | `1a945ec5` | `9b101624` |
| SFC-12-09 residual (предметный анкер в запросах частей) | `sc/fc-anchor` = `4852c67c` | `b0f6ec79` | `8012ce87` |

Оба merge чисты (`ort`), конфликтов нет. База обоих — `0beed63d`.

## 2. Состав поезда

`git diff --stat 0beed63d..1bdd8507` — **44 файла**, из них рантайм ровно 5:

- `services/prompt_registry.py`, `services/checkup_prompts.py` — S6-ACTIVATION
  (метка `checkup-p0-24-10-mixed-state`, печать `3140bb364044` сохранена,
  текст промпта не менялся);
- `services/factcheck_planner.py`, `services/factcheck_orchestrator.py` —
  SFC-12-09 residual (полный материал предмета в план + `_material_anchor_terms`
  / `_with_material_anchor`, `_needs_material_anchor`);
- `config/settings.py` — только `APP_VERSION` (bump).

Остальное: `plans/docs/param-registry-round1025.meta.md` (bump), 5 файлов
evidence `plans/features/**`, 33 файла тестов (4 JS-пина, 2 зеркала
`test_factcheck_subject_contract.py` / `test_s17_subject_acceptance.py`,
`test_p0_prompts_core.py`, 2 `test_smart_corrective_*`, 24 py-пина версии).
Других рантайм-файлов в diff нет.

## 3. Bump 2.58.202 → 2.58.203

Коммит `1bdd8507` — `chore(release): 2.58.203`, ровно **30 файлов / 31 строка**
(тот же набор, что в прошлых bump'ах): `APP_VERSION` + цепочка `Prior 2.58.202`,
F8-meta, 24 py-пина, 4 JS-регэкспа `2\.58\.203` (`test_webapp_round1026_polygon.py`
— 2 строки). Заводской текст и печать промптов, owner-значения и фабричные
настройки не менялись.

## 4. Тесты (main venv, cwd = тренировочный worktree, `1bdd8507`)

| Набор | Результат |
|---|---|
| Guard/метка (18 файлов: activation + prompt_delivery + prompt-версии/аудит) | **328 passed, 2 skipped** |
| Проверка/совместимость промптов (13 файлов) | **331 passed** |
| Реестр чата/чтение (14 файлов) | **264 passed / 1 failed** (`test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface`) |
| Активация/история (14 файлов) | **274 passed, 2 skipped / 1 failed** (тот же `test_prompt_field_audit`) |
| SOUL-1 (6 файлов) | **72 passed** |
| Зеркала анкера (2 файла) | **112 passed** |
| planner + orchestrator + acceptance + subject contract | **161 passed** |
| все `tests/test_*factcheck*.py` + `tests/factcheck_acceptance` | **718 passed** |
| Sanity: сторож S5A–S5D + `recovery_scope` + S1–S4 | **146 passed** |
| Pin-guard (24 py-файла) | **856 passed / 4 failed** — ровно известные 4 |
| JS pin-регэкспы (node, 4 файла) | **4 PASS** |
| FC live-canary harness `--self-test` (v1.4.0, `16fbae81`, вне поезда) | **self_test_passed=true** |
| `py_compile` изменённых `.py` (7) | exit 0 |

Известные падения воспроизведены на чистой базе `0beed63d` (отдельный
detached-worktree, `APP_VERSION = 2.58.202`):
`pytest tests/test_prompt_field_audit.py tests/test_soul1_registry_completeness.py
tests/test_tool_coordinator_round1026.py tests/test_unified_image_request_round1026.py`
→ **6 failed, 100 passed** — та же шестёрка, что на поезде. Новых падений нет.

Природа известных: `test_every_editable_prompt_has_reachable_surface`
(reachable-surface блок `direct.base.synthesizer`) и
`test_registry_consumer_pointers_point_at_real_lines` (`lore_worker.py`
line-pointer) — pre-existing с 2.58.201, не связаны с меткой/анкером;
pin-guard 4 — канон/`forbidden_paths` в `test_tool_coordinator_round1026.py` и
`test_unified_image_request_round1026.py`, ошибка в самих тестах-пинах.

## 5. Manifest dry-run

`python tools/release_manifest.py --repo-root . --dry-run` на `1bdd8507`:

```json
{
  "deployed_at": "2026-11-14T17:54:02.248037Z",
  "deployed_sha": "1bdd85079cac9f0ba36c279b5dced4d2505b135d",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/smart-corrective-01",
  "schema": 1,
  "version": "2.58.203"
}
```

`.deploy/` не создавался (`--dry-run`). Для DevOps: манифест пишется штатно на
самом выкате; `deployed_sha` должен совпасть с tip'ом ветки, `dirty_tracked`
должен остаться `false`.

## 6. Границы

- Прод не трогался; deployed остаётся `0beed63d` / 2.58.202.
- Схема не менялась (v47, DDL=0); каталог 645/121; новых флагов, настроек,
  промптов, моделей, агентов и планировщиков нет.
- Постдэплой-подтверждение (строки `[prompt_release] activation`, новый
  `factory_revision_applied`, `prompt_source`/`prompt_base_hash` реального
  чекапа, `factory_superseded_manual` для C2, запросы частей с анкером в
  живом прогоне) — этап DevOps/live, не этот лейн.
- Worktree оставлен для DevOps; пробные прогоны закрыты.
