# Train log — `release/mod-acl-m21-2.58.206`

Дата: 16.11.2026, 19:43 (+12:00). Сборка без деплоя; production не менялся.

## 1. Идентичность и рабочее дерево

- Git root: `C:\Code\Python\adminbot`.
- База: `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1` (`2.58.205`,
  schema 47, DDL 0).
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\mod-acl-m21-release-ab60a0ebd92c-a64ea245`;
  unit `mod-acl-m21-release-2.58.206`.
- `git worktree add -b release/mod-acl-m21-2.58.206 <path> bca18c1e` — ok.
- `git merge --ff-only acl/m2.1-perchat-adapters` — exit 0; HEAD `0585f238`;
  мержей нет; дерево чистое (tracked).

## 2. Проверки состава (до bump)

- `git rev-list --count bca18c1e..0585f238` = 15.
- Кумулятивный дифф: **46 files, +3871/−252**; продуктовых 23, тестов 15,
  evidence 8.
- `MigrationStep(` = 47; DDL-grep по `services/`+`config/` = 0.
- Каталог: `REGISTRY 645 / GROUPS 121 / TAB_BY_GROUP 119 / TAB_RULES 22`,
  `fields 472`.
- `services/module_registry.py`, `services/permissions.py`,
  `services/access.py`, prompt registry/composer/factory,
  `services/param_catalog.py`, `services/hot_config.py` — в диффе
  отсутствуют; `config/**` не менялся.

## 3. Bump

- Скрипт: `bump_2.58.206.py` (run-каталог), та же волна, что `bfcccb38`.
- Результат: `files=30 replacements=32`; `git diff --stat` — **30 files,
  31 insertions, 31 deletions**; `git diff --check` — exit 0.
- `config/settings.py`: BOM=true, CRLF=3629, diff 1 строка; APP_VERSION
  импортируется как `2.58.206`.
- Коммит: `afcaf95f75f35aafd1bf83ea1f6da912fcecc377`
  (`chore(release): 2.58.206 - bump APP_VERSION и всех пинов версии`).

## 4. Тесты bumped-вершины

| Шаг | Команда/набор | Результат |
|---|---|---|
| Focused M2.1/M2 | 24 файла из `evidence/m21/tests-summary.json` | **481 passed** |
| Pin-guard | 24 py-файла релизных пинов | **856 passed / 4 failed** |
| JS pins | 4 node-харнесса | **4/4 OK** |
| Broad A | 30 файлов (module/ACL/gates/M2 consumers/QND/media) | **483 passed / 1 failed** |
| Broad B | 31 файл (initiative/persona/tools/speech/stories/random/adjoining) | **785 passed / 15 failed / 18 errors** |

Сверка с базой `bca18c1e` (detached worktree `mod-acl-m21-base-check`):

- `tests/test_mod_acl_ux_m2_inflight.py` — **5 passed** на базе;
  на кандидате — **1 failed** (`test_text_initiative_off_mid_flight_single_outcome`,
  `writer.generate_calls == 0` вместо 1). Это **новый блокер**, не
  pre-existing.
- `test_initiative_coordination.py` — 4 failed на базе (те же ID).
- `test_initiative_speech_layers_chat_overrides.py` +
  `test_soul1_w5_observer_gates.py` + `test_speech_p0_a2_memory.py` —
  6 failed на базе (те же ID).
- `test_image_generation_round1023.py` — 3 failed на базе (те же ID).
- Два graphrag warning-теста — 2 failed на базе (те же ID).
- 4 pin-guard ID — 4 failed на базе (те же ID).
- `test_youtube_multimodal_download_round1024.py` (18 errors на кандидате):
  фикстура патчит `handlers.youtube.get_smart_cache`, которого нет и на базе
  (source-proof); base-прогон файла не завершён из-за перезапусков окружения.

Причина блокера: M2.1 D1 (`1a417917`) добавил per-chat гейт
`initiative_chat_enabled(chat_id)` в начало `handle_initiative`
(`services/direct_chat_service.py`). Чат выключается оценщиком после
первичной проверки наблюдателя, но до генерации; новый входной гейт
возвращает `disabled` до `writer.generate_initiative_reply`, поэтому
`publish_guard`/`initiative_publish_block_reason` не достигается. Тест M2
(`MAC-S2-113/114`) не менялся в M2.1 и ждёт одну генерацию + отмену
`capability_off`. Продуктовый код и тесты в сборке не правились.

## 5. Manifest и статические проверки

- `python tools/release_manifest.py --dry-run` на `afcaf95f`:
  `version=2.58.206`, `dirty_tracked=false`,
  `release_branch=release/mod-acl-m21-2.58.206`, `previous_*=null`.
- Свежая БД: `APP_VERSION=2.58.206`, `migration_steps=47`,
  `observed_user_version=47`, `table_count=101`.
- `py_compile config/settings.py` — exit 0.

## 6. Evidence и дальнейшие шаги

- Evidence: `plans/features/mod-acl-ux-01/evidence/release-2.58.206/`
  (`assembly.md`, `tests-2.58.206.json`, `manifest-dry-run.json`,
  `rollback.json`, `train-log.md`, `retention.json`, diff-статистика).
- Evidence-коммит добавляется поверх `afcaf95f`; затем — push без force
  (`git push -u origin release/mod-acl-m21-2.58.206`). Точный tip — в
  handoff.
- Деплой не выполнялся; predeploy-одобрение невозможно до решения по
  блокеру §4.
