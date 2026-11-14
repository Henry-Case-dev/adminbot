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
