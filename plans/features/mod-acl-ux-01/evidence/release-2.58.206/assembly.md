# MOD-ACL-UX-01 — сборка релизного кандидата `2.58.206` (M2.1, без деплоя)

Дата сборки: 16.11.2026, 19:43 (+12:00). Статус:
**assembly done / REVIEW / BLOCKED**. Production не менялся, деплоя не было;
`VERIFIED` не заявляется.

## 0. Итог и блокер

Ветка `release/mod-acl-m21-2.58.206` собрана от `bca18c1e` и запушена; bump
`2.58.206` и evidence оформлены. **Кандидат не готов к predeploy-одобрению:**
broad-прогон выявил один новый (не pre-existing) красный тест:

```
tests/test_mod_acl_ux_m2_inflight.py::test_text_initiative_off_mid_flight_single_outcome
кандидат: 1 failed (writer.generate_calls == 0, ожидалось 1)
база bca18c1e: 5 passed (файл целиком)
```

Причина (source-proof): M2.1 D1 добавил per-chat гейт
`initiative_observer.initiative_chat_enabled(chat_id)` в начало
`handle_initiative` (`services/direct_chat_service.py`, M2.1-коммит
`1a417917`). В сценарии M2 чат выключается оценщиком **после** первичной
проверки наблюдателя (`services/initiative_observer.py:2538`), но **до**
генерации. Новый входной гейт возвращает `{"status": "disabled"}` до
`writer.generate_initiative_reply`, поэтому `publish_guard`
(`initiative_observer.py:3142-3161`) не достигается, а тест M2
(`MAC-S2-113/114`) ждёт одну генерацию и терминальную отмену с
`capability_off`. Тест M2.1 не менялся (`git diff bca18c1e..HEAD --
tests/test_mod_acl_ux_m2_inflight.py` пуст).

Это не pre-existing падение и не следствие bump. Требуется решение лейна
M2.1 (восстановить порядок генерация→публикация или осознанно обновить
M2-контракт и тест с повторным Reviewer-одобрением). В этой сборке
продуктовый код и тесты **не менялись**.

## 1. База и состав поезда

- База поезда / production / откат: `bca18c1e` (`2.58.205`, schema 47, DDL 0).
- Рабочая ветка: `release/mod-acl-m21-2.58.206`.
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\mod-acl-m21-release-ab60a0ebd92c-a64ea245`
  (unit `mod-acl-m21-release-2.58.206`, зарегистрирован housekeeping;
  сохраняется для Reviewer/DevOps).
- Код-вершина M2.1: `0585f238` (product `1a417917`, test-only `bd92838d`).
- Bump-коммит: `afcaf95f` (`chore(release): 2.58.206`).
- `git merge --ff-only acl/m2.1-perchat-adapters` → exit 0, мержей нет.

```
bca18c1e (2.58.205, prod/откат)
  -> be8e8ecf feat(acl): M2.1 per-chat adapters for 12 module consumers
  -> 3baebedb docs(acl): M2.1 evidence (RED base, GREEN 464, 3 mutations)
  -> def84275 fix(acl): M2.1 recheck media-download callback per chat
  -> 5754ddb4 docs(acl): M2.1 evidence refresh (465 green, 31 red, download callback recheck)
  -> b278a547 fix(acl): M2.1 remove product master-AND per chat
  -> a45195a6 docs(acl): M2.1 corrective evidence (476 green, 44 red, 3/3 mutations)
  -> 9b78b6ab test(acl): M2.1 remove tautological pool/model assertions
  -> 42fc68e9 docs(acl): M2.1 evidence diff labels and test commit
  -> 3f848604 docs(acl): M2.1 refresh RED artifact for final tests
  -> 299ac2b7 docs(acl): clarify initiative observer tick axis
  -> 1a417917 fix(acl): M2.1 D1-D3 per-chat publish, force-repeat, persona frame
  -> 3577c2ca docs(acl): M2.1 D1-D4 corrective evidence (480 green, 4/4 RED base, 3/3 mutations)
  -> 222a40e7 docs(acl): M2.1 D1-D4 note per-chat due-scan resolver cost
  -> bd92838d test(acl): M2.1 F1 test-debt + committed due-scan per-chat test
  -> 0585f238 docs(acl): M2.1 F1 test-debt closure + due-scan evidence
  -> afcaf95f chore(release): 2.58.206 - bump APP_VERSION и всех пинов версии
```

Итого 16 коммитов: 4 продуктовых (`be8e8ecf`, `def84275`, `b278a547`,
`1a417917`), 2 test-only (`9b78b6ab`, `bd92838d`), 9 docs/evidence,
1 bump (`afcaf95f`).

### 1.1 Кумулятивный дифф

- До bump (`bca18c1e..0585f238`): **46 files, +3871/−252**.
  - продуктовый слой: 23 файла (`bot.py`, 8 `handlers/`, 12 `services/`,
    `web/api/stories.py`) — состав ниже;
  - тесты: 15 файлов;
  - evidence: 8 файлов (`evidence/m21/**`).
- После bump (`bca18c1e..afcaf95f`): **76 files, +3902/−283**
  (30 файлов / 31 строка / 32 замены пинов).

Продуктовый состав (`bca18c1e..0585f238`):

```
bot.py
handlers/checkup.py
handlers/direct_chat.py
handlers/factcheck.py
handlers/search.py
handlers/video_download.py
handlers/voice_transcription.py
handlers/web.py
handlers/youtube.py
services/bot_persona.py
services/capability_registry.py
services/chat_params.py
services/direct_chat_service.py
services/feature_gates.py
services/initiative_observer.py
services/mca_exploration.py
services/mca_gates.py
services/mca_intents.py
services/mca_self_model.py
services/media_download.py
services/tool_router.py
services/tool_schemas.py
web/api/stories.py
```

## 2. Статические проверки bumped-вершины

- `MigrationStep(` в `services/database.py`: **47**; целевая константа
  `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47`; схема v47.
- DDL в диффе `bca18c1e..HEAD` по `services/` и `config/`: **0**
  (`CREATE/ALTER/DROP TABLE`, `CREATE/DROP INDEX`, `PRAGMA user_version`,
  `executescript`).
- Свежая БД через `DatabaseService.initialize()` на дереве `2.58.206`:

```
APP_VERSION=2.58.206
migration_steps=47
observed_user_version=47
table_count=101
```

- Каталог/настройки: `REGISTRY 645 GROUPS 121 TAB_BY_GROUP 119 TAB_RULES 22
  fields 472` — совпадает с базой; новых флагов, настроек, промптов,
  моделей, агентов и планировщиков нет.
- Запрещённые файлы не менялись: `services/module_registry.py`,
  `services/permissions.py`, `services/access.py`,
  `services/prompt_registry.py`, `services/prompt_composer.py`,
  `services/prompt_factory.py`, `services/param_catalog.py`,
  `services/hot_config.py`, `config/**` (кроме строки bump).
  `git diff --name-only` по этому набору возвращает только
  `config/settings.py`.
- `py_compile config/settings.py` — exit 0; `git diff --check` — exit 0;
  `from config.settings import APP_VERSION` → `2.58.206`.
- `config/settings.py`: BOM сохранён, CRLF 3629, diff файла — 1 строка;
  исторический текст `Prior 2.58.205` сохранён.

## 3. Bump `2.58.205` → `2.58.206`

Коммит `afcaf95f`, та же волна пинов, что `bfcccb38`:

```
30 files changed, 31 insertions(+), 31 deletions(-)
```

- `config/settings.py` — `APP_VERSION = "2.58.206"` + релизная заметка
  M2.1 и `Prior 2.58.205`;
- `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION: 2.58.206`;
- 24 py-файла релизных пинов — 25 вхождений
  (`test_webapp_round1026_polygon.py` — 2 строки, остальные по одной);
- 4 JS-харнесса — экранированный регексп `2\.58\.206`;
- 32 текстовых замены версии; исторические `release-2.58.205/**` и
  evidence M2.1 не переписывались.

## 4. Тесты

Окружение: `.venv` Python 3.12.0, pytest 9.1.1, node v24.16.0; cwd = дерево
поезда. Полные логи — в run-каталоге сборки.

| Набор | Файлов | Результат |
|---|---|---|
| Focused M2.1/M2 (24 файла) | 24 | **481 passed / 0 failed** |
| Pin-guard (24 py-файла пинов) | 24 | **856 passed / 4 failed** |
| JS pin-харнессы (node) | 4 | **4/4 OK** |
| Broad A (module/ACL/gates/consumers/QND/media) | 30 | **483 passed / 1 failed** |
| Broad B (initiative/persona/direct_chat/tools/speech/stories/random/adjoining) | 31 | **785 passed / 15 failed / 18 errors** |

Broad A — новый блокер:

- `tests/test_mod_acl_ux_m2_inflight.py::test_text_initiative_off_mid_flight_single_outcome`
  — **1 failed** на кандидате; на базе файл целиком **5 passed**. Подробности
  в §0.

Pin-guard: те же 4 ID падают и на базе `bca18c1e` (отдельный прогон:
**4 failed**) — pre-existing, не вызваны кандидатом:

- `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

Broad B: все 15 failed и 18 errors — pre-existing, сверены с базой:

- 10 на базе: `test_initiative_coordination` (4),
  `test_initiative_speech_layers_chat_overrides` (4),
  `test_soul1_w5_observer_gates::test_initiative_writer_shares_core_style_and_persona`,
  `test_speech_p0_a2_memory::TestSelfEchoNotFactual::test_style_anchors_not_broken`;
- 3 на базе: `test_image_generation_round1023` (`test_generate_image_is_ninth`,
  `test_active_tools_gate`, `test_direct_chat_image_off_eight_tools`);
- 2 на базе: `test_asap5_graphrag_recovery::test_warning_coalesced_not_repeated`,
  `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced`;
- 18 errors: `test_youtube_multimodal_download_round1024.py` — фикстура
  патчит `handlers.youtube.get_smart_cache`, которого нет ни на кандидате,
  ни на базе (source-proof; в evidence `2.58.205` тот же файл уже давал
  pre-existing error). Base-прогон файла не завершён из-за перезапусков
  окружения; это ограничение, а не скрытое доказательство.

## 5. Manifest dry-run

`.deploy/` не создавался; production-манифест не читался. На content-вершине
`afcaf95f` (clean tracked):

```json
{
  "deployed_at": "2026-11-16T07:42:22.473288Z",
  "deployed_sha": "afcaf95f75f35aafd1bf83ea1f6da912fcecc377",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/mod-acl-m21-2.58.206",
  "schema": 1,
  "version": "2.58.206"
}
```

`previous_*` = null: в dev-worktree нет `.deploy/release.json`.
`manifest-dry-run.json` зафиксирован на `afcaf95f`; итоговая вершина
ветки отличается от неё только evidence-коммитом (файл не может содержать
SHA коммита, который его же добавляет).

## 6. Откат

- Целевой откат: `bca18c1e` (`2.58.205`), schema 47, DDL 0, миграций нет,
  данные не меняются.
- Процедура: переключить production-checkout на `bca18c1e`, штатный
  restart, проверить `/healthz` и identity манифеста.
- Bump-коммит отдельно откатывать не нужно: он меняет только строки
  версии/пины.

## 7. Ограничения

- Это сборка кандидата, а не приёмка: деплоя, живых Telegram/провайдер/UI
  прогонов нет; `VERIFIED` не заявляется.
- **Кандидат заблокирован** новым падением M2-теста (§0); predeploy-одобрение
  без решения лейна M2.1 невозможно.
- Broad-выборка — явные файловые батчи (61 файл, 1302 теста), не весь suite
  проекта; `evol_*`, `ur_*`, `nostalgia_*` и полный `-k` не запускались.
  Focused 24 и Broad A частично пересекаются по файлам.
- Окружение несколько раз перезапускало shell во время длинных pytest-прогонов;
  все завершённые логи сохранены, незавершённые прогоны не выдаются за
  доказательство (в частности, base-прогон youtube-файла).
- 4 pin-guard падения и broad 15+18 — pre-existing; в кандидате не
  исправлялись (вне scope).

## 8. Housekeeping и следующий шаг

- Release-worktree сохранён для Reviewer/DevOps; unit
  `mod-acl-m21-release-2.58.206` зарегистрирован; `retention.json` рядом.
- Временный base-check worktree (`mod-acl-m21-base-check`, detached
  `bca18c1e`) использован только для сравнения и закрывается после передачи
  чисел; branch refs не затрагиваются.
- Run-каталог сборки: `WorkspaceData/runs/.../mod-acl-m21-release-ab60a0ebd92c/
  probe-d462211900` (логи, bump-скрипт, манифест).
- Следующий шаг: решение по блокеру §0 в лейне M2.1 → повторный focused/broad
  прогон → только затем дельта-ревью и деплой (в этой задаче не выполнялись).
