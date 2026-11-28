# Release/Test Barriers Corrective — отчёт реализации (2026-11-28)

- **Ветка:** `fix/release-test-barriers-2026-11-28`
- **База:** `release/2.58.272` tip `a2195fe3f` (продуктовый кандидат `f6cd011e0` + bump `cb47e6cbd`); на момент
  rebase release-ветка ушла вперёд deploy-docs `fa4ba6292` (код не менялся) — ветка ребейзнута на неё.
- **Worktree:** `WorkspaceData/worktrees/…/release-test-barriers-2026-11--19f1987d0616-5da2a6da`
- **Кодовый кандидат:** `7e8eb8a05a8ea0bfefbef4b7a277328d9189f61d` (tests/contracts + `plans/project.md`; evidence-коммит идёт следом)
- **Corrective r1 (review-r1, F-BAR-01/02/03):** code `222ad0046` (routes contract: уникальность маршрутов, guard-эвристика, CLI `--emit/--check`), evidence — этот коммит; см. §10.
- **Прямое поручение владельца:** убрать повторяющиеся механические барьеры тестов и релиза (2026-11-28).

## 1. Полнофайловые sha256-пины продуктовых файлов — найдено и заменено

Инвентарь (полный, по всем `tests/*.py`):

| Файл-объект | Где был пин | Замена |
|---|---|---|
| `web/api/routes.py` | `test_round1025_f8_registry.ROUTES_SHA256_F11` (+`test_routes_file_unchanged`); копия в `test_mca23_planned_vs_actual`; импорт в `test_asap7_cover_preview`, `test_mca10b…`, `test_mca12…`, `test_mca17c…`, `test_fc_trust_s6_aggregate_api` | `tests/routes_contract.py`: объявленный манифест `tests/fixtures/routes_contract.json` (78 операций: path + methods + initData + нормализованные guard-проверки). Падает при удалении/переименовании маршрута, смене метода, снятии RBAC/иной проверки прав, появлении необъявленного маршрута. |
| `services/param_catalog.py` | `PARAM_CATALOG_SHA256_FOLLOWUP` (`TestFrozenInvariants.test_param_catalog_unchanged`) | `test_param_catalog_identity_contract`: идентичность **ключей** с `catalog_baseline.json` + валидность `type`/`sensitivity` по самому REGISTRY. Типов baseline не хранит: описания/типы/секретность защищены переэмиссией `gen.run_check`/`--check` по TSV (отдельный TestGenerator). |
| `services/pg_db.py` | `PG_DB_SHA256_B07` (`test_ddl_source_unchanged`) | `test_ddl_source_contract`: нет `DROP TABLE`/`TRUNCATE`, `CREATE … IF NOT EXISTS`, обязательные таблицы присутствуют, цепочка `migration_steps()` строго возрастает без дублей. |

**Не тронуты (осознанно, это не пины активно изменяемого исходника):**

- `tests/test_prompt_versioning_enforcement.py`, `test_checkup_contract.py`, `test_fc_trust_s5_writer.py`, `test_evol_w17_small_canon_reqs.py` — sha канонического **текста промпта** (контент-контракт, версионируется отдельно).
- `tests/test_webapp_round1026_polygon.py::test_delaunator_sha256` — контрольная сумма **стороннего vendor-артефакта** + фиксация лицензии (supply-chain integrity).
- `tests/test_evol032_health_glass.py` — сравнение защищённой оптики с `HEAD` (локальная модификация), не литеральный хэш.
- `tests/fixtures/round1025/f8_baseline.json` `sha256`/`sha256_artifacts` — исторические поля, тестами не используются.
- Release identity (sha256 reviewed-кандидата/деплоя в assembly/manifest) **не менялась**.

## 2. Литералы текущей версии в тестах → канонический контракт

`tests/version_contract.py::assert_version_contract()` проверяет:

1. `config.settings.APP_VERSION` (runtime) совпадает с литералом `config/settings.py`;
2. формат `MAJOR.MINOR.PATCH`;
3. release-метаданные `plans/docs/param-registry-round1025.meta.md` называют ту же версию;
4. `web/index.html` использует runtime-подстановку `__APP_VERSION__`.

Переведены 23 литерала в 20 файлах:
`test_decision_making_round1026`, `test_image_context_memory_round1026`, `test_mca17c_invariants_round1047`,
`test_scope_selector_round1025`, `test_summary_deploy_round1026`, `test_summary_fact_package`,
`test_summary_logging_runid`, `test_summary_publish_integration_round1026`, `test_summary_test_run`,
`test_telegram_reactions_round1026`, `test_tool_coordinator_round1026`, `test_unified_image_request_round1026`,
`test_webapp_design_tokens_round1025`, `test_webapp_f11_round1025`, `test_webapp_f6_round1025`,
`test_webapp_f7_round1025`, `test_webapp_f9_round1025`, `test_webapp_hotfix6/7/8/9/10_round1025`,
`test_webapp_round1026_polygon`, `test_round1025_f8_registry` (`test_app_version_recorded` — исторический
fixture 2.58.15 сохранён, runtime проверяется контрактом).

Дополнительно снята doc-sync «текущая версия обязана быть в README»:
`test_hotfix_round1025_cachebust::test_version_bumped_and_matches_readme` (осталась проверка «версия строго выше
до-хотфиксной»), `test_webapp_round108_ui::test_app_version_matches_readme` → version contract.
Это две дополнительные предсуществующие падучки того же механизма (см. §4).

Осознанно оставлены version-контракты: `tests/test_release_manifest.py` (формат/`next_patch`/манифест),
`test_deploy_identity.py` (runtime↔manifest↔deploy identity); они проверяют версионирование как механизм, а не
копию номера.

## 3. Шесть предсуществующих падений snapshot/diff-guard — воспроизведение и причина

Точный набор подтверждён релизной уликой 2.58.272 (base `3a78484b9` = 2.58.271 и собранное дерево):
`plans/features/fc-trust-01/evidence/release-2.58.272/raw/tests-base-parity.txt` (6 failed / 9 passed) и
`tests-bumped.txt` (6 failed / 864 passed) — одни и те же node id.

| # | Тест | Было | Причина | Стало |
|---|---|---|---|---|
| 1 | `test_mca17c_invariants_round1047::test_no_ddl_catalog_ks_tools_delta` | `assert 50 == 48` | устаревший литерал `user_version=48` при фактических 50 (санкционированные v49/v50) | литерал убран; остаётся `actual == max(migration_steps())` — канонический инвариант «БД применяет весь зарегистрированный хвост» |
| 2 | `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff` | `web/...` в diff от `pre-round1026-a1`, allowlist устарел на ~250 релизов | историческое сравнение с master-линией + allowlist всех последующих волн | рабочая дельта (`git status --porcelain`) и durable-запрет только `plans/current_task.md` + `db/`; границы §104/каталога/DDL защищены отдельными контрактами |
| 3 | `test_tool_coordinator_round1026::TestBounds::test_canon_twelve_tools` | `18 != 17` | канон инструментов не отразил санкционированные SELF-DIAG-01 D6-19/20 (`inspect_runtime`, `prompt_readback`) | единый `TOOL_CANON` (18) в coordinator-тесте; exact-list + уникальность |
| 4 | `test_unified_image_request_round1026::TestToolDescriptionU21::test_canon_unchanged` | лишние `inspect_runtime`, `prompt_readback` | вторая копия канона инструментов | импортирует `TOOL_CANON`, проверяет префикс и `generate_image` на позиции 8 — одна копия контракта |
| 5 | `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | `web/...` в diff от `e8646af` | то же историческое сравнение + allowlist | та же рабочая дельта; AST-границы A3 (`_baseline_file`) сохранены |
| 6 | `test_webapp_f9_round1025::TestInvariants::test_secrets_count_28` | `34 != 32` | комментарий уже говорил «→34», assert не обновлён — снимок числа | точный инвентарь 34 secret-имён (security-relevant identity, не число) |

Ни один из шести не оказался реальным продуктовым дефектом: все — устаревшие снимки/дифф-гарды. Снятие
защит не производилось; защиты переведены в контракты и проверены мутациями (§5).

## 4. Дополнительно найденные предсуществующие падения (вне шести)

При расширенном прогоне изменённых/смежных файлов обнаружены ещё падения в `tests/test_webapp_round108_ui.py`:

- `test_app_version_matches_readme` — тот же version-doc-sync барьер; **исправлен** (§2).
- `TestRenames108::test_old_labels_gone` (`«Как это работает»` снова присутствует в `web/app.js`),
  `TestAccessWindows108::test_three_windows` (`modal-backdrop` 2 вместо 3),
  `TestAccessWindows108::test_no_accordion` (`role="tabpanel"` присутствует) — **не относятся** к
  version/route/sha-механизмам; это старые UI-снимки 10.8. Оставлены без изменений как honest backlog
  (лог: `raw/preexisting-round108-unrelated.txt`), чтобы не расширять задачу на рефакторинг UI-тестов.
- Четвёртый предсуществующий красный (найден ревью r1, F-BAR-06):
  `tests/test_status_section_ui_merge_round1019.py::TestStatusSectionMerge::test_mode_version_line_removed`
  — устаревший UI-снимок (`statusData.bot.version` присутствует в `web/app.js`), падает и на базе
  `fa4ba6292`, и на кандидате; к механизмам этой задачи не относится. Записан в `plans/backlog.md`
  (лог: `raw/corrective-r1-status-section-round1019.txt`).

## 5. Мутации (RED) и норма (GREEN)

Маршрутный контракт — мутации продуктового `web/api/routes.py`, затем `git checkout --`:

| Мутация | RED-причина |
|---|---|
| удалить маршрут (`/health` → `/health-renamed`) | `маршруты контракта отсутствуют … [('/health', ('GET',))]` |
| сменить метод (`POST /admins` → `GET`) | `необъявленные маршруты … [('/admins', ('POST',))]` |
| снять RBAC-зависимость (`requires_global_admin()` → `get_tma_user`) | `изменены проверки прав /admins ('POST'): ['get_tma_user','requires_global_admin'] -> ['get_tma_user']` |
| удалить auth-параметр целиком | `изменена auth-модель /admins: init_data True -> False` |
| добавить необъявленный маршрут `/probe-undeclared` | `необъявленные маршруты … [('/probe-undeclared', ('GET',))]` |

Логи: `raw/mutation-*.txt`. Норма: `raw/six-fixed-green.txt` (6 passed) и `changed-files-green.txt`
(974 passed, 3 deselected — только перечисленные UI-снимки 10.8).

Дополнительно: `raw/mutation-tool-canon-removed.txt` (удаление `TOOL_PROMPT_READBACK` из
`services/tool_schemas.py` → RED канона), `raw/mutation-secret-flag-removed.txt` (снятие `secret=True`
у `API_TOKEN` → RED инвентаря секретов). Продуктовые файлы восстановлены (`git status` чист).

## 6. Version bump больше не требует правки тестов

`raw/version-bump-no-test-edit.txt`: временно `APP_VERSION=2.58.299` в `config/settings.py` **и** release-метаданных,
тесты не менялись → `pytest -k version` по 24 затронутым/смежным файлам: **25 passed**, EXIT=0; затем восстановлено.
Негативный контроль `raw/version-negative-control.txt`: bump только `settings.py` (метаданные не обновлены) →
`AssertionError: release-метаданные называют '2.58.272', runtime — '2.58.299'` (контракт действительно
дискриминирует, а не тавтологичен).

## 7. Прогоны (фактические)

| Прогон | Результат | Raw |
|---|---|---|
| 6 бывших падений (node id) | **6 passed** | `six-fixed-green.txt` |
| 31 изменённый тест-файл | **974 passed, 3 deselected** | `changed-files-green.txt` |
| то же без deselect | 974 passed / 3 failed (только §4 UI-снимки 10.8) | `changed-files.txt` |
| 3 UI-снимка 10.8 отдельно (подтверждение предсуществования) | 3 failed | `preexisting-round108-unrelated.txt` |
| `python tools/gen_param_registry_round1025.py --check` | EXIT 0, реестр 668 | `registry-check.txt` |
| смежные version/release/identity: `test_release_manifest`, `test_deploy_identity`, `test_smart_exec_selfdiag`, `test_webapp_api`, `test_hotfix_round1025_cachebust`, `test_aliases_render_round1022` | 258 passed, 1 failed до правки README-теста; после правки — 27 passed по `test_hotfix…` + `test_webapp_f9` | — (включено в changed-files-green) |
| `git diff --check` | OK | — |

## 8. Изменённые файлы

- Новые: `tests/routes_contract.py`, `tests/fixtures/routes_contract.json`, `tests/version_contract.py`.
- Self-check контракта (corrective r1): `tests/test_routes_contract_barriers.py`.
- Тесты: `test_round1025_f8_registry`, `test_mca23_planned_vs_actual`, `test_asap7_cover_preview`,
  `test_mca10b_random_applications_block_d_round1041`, `test_mca12_stories_round1046`,
  `test_mca17c_invariants_round1047`, `test_fc_trust_s6_aggregate_api`, `test_tool_coordinator_round1026`,
  `test_unified_image_request_round1026`, `test_webapp_f9_round1025`, `test_hotfix_round1025_cachebust`,
  `test_webapp_round108_ui`, + 19 version-литеральных файлов из §2.
- Правило: `plans/project.md` — «соразмерные проверки изменённых компонентов; полный прогон — при техническом
  основании/обязательном релизном требовании; релизные гейты не ослабляются».
- Карты/`progress_scope.json`/`workflow_state.md` не изменялись.

## 9. Ограничения

- `routes_contract.json` — объявленный контракт: санкционированное добавление маршрута или изменение
  проверок требует одной осознанной переэмиссии манифеста, но больше не зависит от
  комментариев/форматирования/тела обработчиков. Точные команды:
  `python -m tests.routes_contract --emit` (записать) и
  `python -m tests.routes_contract --check` (сверить без записи; exit 0/1).
- Проверки прав нормализованы по guard-вызовам (`_ctx_global_admin`, `requires_permission:<право>`,
  `_prompt_require_*`, `_require_chat_access`, `_is_global_admin`, …); смена *семантики* самого guard-хелпера
  контрактом маршрутов не покрывается — это зона тестов ACL/ролей.
- Guard-набор выводится эвристикой имени (`_require*`/`_assert*`/`*_guard`/`*_rights`/`*_admin`) плюс явный
  whitelist; guard внутри module-level хелпера, который вызывается из маршрута, раскрывается на **один**
  уровень. Глубже контракт не идёт (маршрутный, не граф всего модуля). Побочный эффект одного уровня:
  `_prompt_require_edit` внутри capability-probe `_prompt_can_activate` пинится и для
  `GET /prompts/{prompt_key}/versions` (вызов реально исполняется, но отказ проглатывается) — это осознанное
  over-approximation, а не заявленная enforcement-точка.
- 3 UI-снимка 10.8 остаются красными (см. §4), не входят в контракт этой задачи.
- `test_webapp_round108_ui` содержит и исправленный version-тест, и 3 несвязанных падения; в прогонах выше они
  явно отделены deselect'ом.

## 10. corrective r1: F-BAR-01/02/03 (закрытие findings независимого ревью)

Ревью r1 (`review-r1.md`, §4) нашло два blocking-пробела в новом маршрутном контракте и один
документационный: F-BAR-01 (дубль маршрута молча схлопывался), F-BAR-02 (inline-guard'ы вне whitelist
невидимы), F-BAR-03 (не существовало документированной команды переэмиссии). F-BAR-04/05/06 —
BACKLOG_ONLY, записаны в `plans/backlog.md`, не «чинились». Продукт не менялся: правки только в
`tests/**` (эти два файла), `plans/features/release-test-barriers-2026-11-28/**`, `plans/backlog.md`.

### 10.1 F-BAR-01 — дубль маршрута теперь ловится

`tests/routes_contract.py`:

- `duplicate_route_keys(rows)` / `overlapping_route_methods(rows)` / `assert_routes_unique(rows, where)` —
  отказ при одинаковом `(path, methods)` и при одном методе, зарегистрированном двумя обработчиками;
- `collect_routes()` проверяет уникальность **дважды**: на AST-декораторах `api_router` (два декоратора с
  одним ключом) и на живом `api_router.routes` (включая пересечение методов);
- каждый живой `APIRoute` обязан иметь AST-декоратор (`assert fn is not None`), иначе проверки доступа
  нечем проверить — молчаливый `checks=[]` больше невозможен;
- `assert_routes_contract_intact()` валидирует и сам манифест (ручной дубль в fixture тоже RED).

Мутация M5 (точный сценарий ревьюера: второй `@api_router.get("/admins")` с `Depends(get_tma_user)` без
RBAC **перед** оригиналом) → `AssertionError: неуникальные (path, methods) в AST-декораторы routes.py:
[('/admins', ('GET',))]` (лог `raw/mutation-m5-shadow-route-admins.txt`). Позитивный тест того же
сценария — `tests/test_routes_contract_barriers.py::TestDuplicateRoutes` (rows-уровень и AST-уровень,
shadow-обработчик назван `get_admins_shadow`).

### 10.2 F-BAR-02 — guard-набор выводится, а не только расширен

- `is_guard_call_name(name)`: явный `EXPLICIT_GUARD_CALLS` + эвристика `(?:^|_)requires?_`, `^_?assert`,
  `_guard$`, `_rights$`, `*_admin` (private/`is_`/`user_is_`/`*_global_admin`/`*_hidden_admin`).
  Бизнес-операции `add_admin`/`remove_admin`/`upsert_admin` и локальные переменные вида `required`
  намеренно не считаются guard'ами (проверено тестами).
- `_source_checks()` учитывает не только прямые вызовы, но и guard, переданный callback'ом
  (`recheck=_recheck_config_chat_rights`), и **на один уровень** раскрывает module-level хелперы,
  вызываемые из маршрута (например, `_post_config_global`), чтобы guard внутри общего хелпера не был
  невидим. Глубже — нет (ограничение §9).
- `tests/fixtures/routes_contract.json` переэмитирован; диф ограничен 4 маршрутами:
  `POST /config` (+`_meme_template_guard`, `_random_selector_guard`, `_recheck_config_chat_rights`,
  `user_is_global_admin`), `POST /initiative/meme-settings` (+`_meme_template_guard`,
  `_recheck_meme_rights`), `GET /prompts/catalog` (+`_prompt_hidden_admin`),
  `GET /prompts/{prompt_key}/versions` (+`_prompt_require_edit` через `_prompt_can_activate`).
- `tests/test_routes_contract_barriers.py::TestGuardHeuristic` фиксирует, что все пять имён из ревью
  (`_prompt_hidden_admin`, `_random_selector_guard`, `_recheck_config_chat_rights`, `_recheck_meme_rights`,
  `_meme_template_guard`) видимы и реально записаны в манифесте.

Мутации (лог `raw/mutation-m6-…`/`m7-…`/`m8-…`/`m9-…`): M6 `if not _prompt_hidden_admin(...)` → `if False:`
→ RED `изменены проверки прав /prompts/catalog … ['_prompt_hidden_admin','get_tma_user'] -> ['get_tma_user']`;
M7 удаление `_random_selector_guard(cache, prepared)` из общего хелпера → RED `/config`; M8 удаление
`recheck=_recheck_config_chat_rights` → RED `/config`; M9 удаление `recheck=_recheck_meme_rights` → RED
`/initiative/meme-settings`.

### 10.3 F-BAR-03 — реально работающая команда переэмиссии

В `tests/routes_contract.py` добавлен `__main__`-CLI:

```
python -m tests.routes_contract --emit    # записать tests/fixtures/routes_contract.json
python -m tests.routes_contract --check   # сверить без записи, exit 0/1
```

`--emit` детерминирован (LF, indent=2, сортировка) и **байт-идентичен при повторном запуске**:
sha256 `2f2e6774…81ac31ba` до и после двух `--emit` (`raw/corrective-r1-manifest-parity.txt`).
`--check` — exit 0 на согласованном дереве. Те же свойства закреплены тестами
`TestManifestEmission` (рендер == файл, emit в tmp == байты fixture, subprocess `-m ... --check`).

### 10.4 Мутации r1 (все RED) и прогоны

Все мутации — правка `web/api/routes.py` с обязательным восстановлением (`git status` после прогона:
изменены только `tests/**`), лог на мутацию в `raw/mutation-m*.txt`:

| # | Мутация | Результат |
|---|---|---|
| M1 | `GET /admins`: `requires_permission("access")` → `("admin")` | **RED** `изменены проверки прав /admins` |
| M2 | `GET /health`: добавлен `Depends(get_tma_user)` | **RED** (auth-модель/публичный инвариант) |
| M3 | `GET /persona/rules/{rule_id}/sources` → `/persona/rule-sources/{rule_id}` | **RED** `маршруты контракта отсутствуют` |
| M4 | `POST /vision/test`: убран `_ctx_global_admin(cache, user)` | **RED** `изменены проверки прав /vision/test` |
| M5 | дубль `GET /admins` без RBAC перед оригиналом | **RED** `неуникальные (path, methods)` |
| M6 | `GET /prompts/catalog`: `if not _prompt_hidden_admin(...)` → `if False:` | **RED** checks `/prompts/catalog` |
| M7 | удалён `_random_selector_guard` в общем хелпере | **RED** checks `/config` |
| M8 | убран callback `_recheck_config_chat_rights` | **RED** checks `/config` |
| M9 | убран callback `_recheck_meme_rights` | **RED** checks `/initiative/meme-settings` |

Прогоны (venv `C:\Code\Python\adminbot\.venv`, `PYTHONPATH` = worktree, `-p no:cacheprovider`):

| Прогон | Результат | Raw |
|---|---|---|
| `pytest tests/test_routes_contract_barriers.py -q` | **27 passed** | (в changed-files) |
| 31 изменённый тест-файл кандидата + новый self-check | **1001 passed, 3 failed** — только известные `test_webapp_round108_ui` (`test_old_labels_gone`, `test_three_windows`, `test_no_accordion`) | `corrective-r1-changed-files.txt` |
| `tests/test_status_section_ui_merge_round1019.py` | **1 failed, 6 passed** — четвёртый предсуществующий красный (F-BAR-06, не регрессия) | `corrective-r1-status-section-round1019.txt` |
| `pytest --collect-only -q` | **23 711 tests collected, exit 0**, ошибок коллекции нет | `corrective-r1-collect-only.txt` |
| `python tools/gen_param_registry_round1025.py --check` | **EXIT 0** (`реестр 668 == REGISTRY`) | `corrective-r1-registry-check.txt` |
| `collect_routes()` vs `routes_contract.json` | **78 == 78, equal=True**, дублей/пересечений нет, public без initData = `['/health']` | `corrective-r1-manifest-parity.txt` |
| `--emit` ×2 + `--check` | sha256 манифеста неизменен, CHECK OK | `corrective-r1-manifest-parity.txt` |

Новых падений относительно ревью r1 нет (1001 = 974 прежних + 27 новых self-check); ассерты не
ослаблялись, зависимостей не добавлялось, продукт/DDL/флаги/прод не затрагивались.

### 10.5 F-BAR-04/05/06 — только backlog

Записаны короткими строками в `plans/backlog.md`: дублирующий assert ключей каталога (и уточнённая
формулировка §1 этого отчёта), JS-литералы версии в `tests/js/*` вне pytest-гейта, четвёртый
предсуществующий красный UI-снимок `test_status_section_ui_merge_round1019`. В этой задаче не
исправлялись осознанно.
