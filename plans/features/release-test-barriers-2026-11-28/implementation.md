# Release/Test Barriers Corrective — отчёт реализации (2026-11-28)

- **Ветка:** `fix/release-test-barriers-2026-11-28`
- **База:** `release/2.58.272` tip `a2195fe3f` (продуктовый кандидат `f6cd011e0` + bump `cb47e6cbd`); на момент
  rebase release-ветка ушла вперёд deploy-docs `fa4ba6292` (код не менялся) — ветка ребейзнута на неё.
- **Worktree:** `WorkspaceData/worktrees/…/release-test-barriers-2026-11--19f1987d0616-5da2a6da`
- **Кодовый кандидат:** `7e8eb8a05a8ea0bfefbef4b7a277328d9189f61d` (tests/contracts + `plans/project.md`; evidence-коммит идёт следом)
- **Corrective r1 (review-r1, F-BAR-01/02/03):** code `222ad0046` (routes contract: уникальность маршрутов, guard-эвристика, CLI `--emit/--check`), evidence — этот коммит; см. §10.
- **Corrective r2 (review-r2, F-BAR-07):** code `114c6b4b4` (`can_access_chat` и аналогичные access-хелперы), evidence — этот коммит; см. §11.
- **Corrective r3 (review-r3, F-BAR-08/09):** code `69096c451` (разделение direct/helper checks, schema 2; аргумент `match_permission`), evidence — этот коммит; см. §12.
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
- Guard-набор выводится эвристикой имени в контексте вызова (`(?:^|_)requires?_`, `^_?assert`,
  `_guard$`, `_rights$`, `^can_`, `^guard_`, `*_admin`) плюс явный whitelist (`can_access_chat`,
  `gate_authorization`, `guard_admin_lockout`, `guard_last_wildcard`, `validate_permissions`,
  `match_permission`, …). `match_permission` обрабатывается как `requires_permission` — вместе с
  запрошенным правом (F-BAR-09).
- Манифест schema 2 разделяет `direct_checks` (тело/сигнатура handler'а, без вложенных функций) и
  `helper_checks` (вложенные функции handler'а + module-level хелперы, до 2 уровней). Наборы сравниваются
  **независимо**, поэтому удаление прямого guard'а всегда RED, даже если одноимённый guard остался в
  хелпере (F-BAR-08). Побочный эффект: `_prompt_require_edit` внутри capability-probe
  `_prompt_can_activate` пинится и для `GET /prompts/{prompt_key}/versions` (вызов реально исполняется,
  но отказ проглатывается) — осознанное over-approximation, а не заявленная enforcement-точка.
- **Вне контракта (честно, corrective r2/r3):** `_persona_access` — резолвер ctx, а не enforcement;
  `gate_snapshot`/`gate_state` — состояние модулей, не авторизация; `validate_value_rule` — валидация
  значения; `get_permissions` — чтение; локальные capability-переменные (`can_read`/`can_edit`/`can_write`,
  модуль `prompt_access`, `global_access`) в checks не попадают (для callback-ссылок используется
  отдельное узкое правило `_is_guard_callback_name`). Также не покрывается смена семантики внутри самого
  guard-хелпера, порядок/кратность одинаковых вызовов (check-наборы — множества) и цепочки хелперов
  глубже 2 уровней.
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

## 11. corrective r2: F-BAR-07 (`can_access_chat` и аналогичные access-хелперы)

Ревью r2 (`review-r2.md`, коммитится без изменений) подтвердило F-BAR-01/03 CLOSED и F-BAR-02 CLOSED
для пяти перечисленных имён, но нашло тот же класс: производная эвристика не классифицировала
`can_access_chat`, поэтому снятие chat-isolation gate у 7 маршрутов оставляло контракт зелёным.
Corrective r2 code — `114c6b4b4`.

### 11.1 Что изменено

`tests/routes_contract.py`:

- `is_guard_call_name()` (контекст **вызова**) расширен: `^can_` (can_access_chat, can_edit_param,
  can_view_key_value, can_view_param), `^guard_` (guard_admin_lockout, guard_last_wildcard) + явные
  `can_access_chat`, `gate_authorization`, `guard_admin_lockout`, `guard_last_wildcard`,
  `validate_permissions`, `match_permission`. Явные имена гарантируют покрытие даже при будущей
  правке шаблонов.
- Для guard'ов, переданных **по ссылке** (`recheck=_recheck_meme_rights`), введено отдельное узкое
  правило `_is_guard_callback_name()`: широкие call-only шаблоны (`^can_`) там не применяются, иначе
  модуль `prompt_access` и локальные `can_read`/`can_edit`/`can_write`/`global_access` попали бы в
  `checks`. Это проверено тестами (`test_references_are_not_guard_callbacks`).
- `_persona_access` намеренно **не** guard: это резолвер `ctx`, а не enforcement-проверка.
- `tests/fixtures/routes_contract.json` переэмитирован: изменения в 25 маршрутах. Ключевое:
  - 7 маршрутов chat-isolation теперь пинят `can_access_chat`: `GET/POST /config/time`,
    `GET /direct/context-diagnostics`, `GET /direct/turn-diagnostics`, `GET /config/keys/status`,
    `GET /config/overrides-map`, `GET /status` (+ `GET/POST /config`, `GET /experience/pipeline`,
    `GET /persona`, `GET /persona/rules/{rule_id}/sources`, `GET /persona/self-model` — там он тоже
    присутствует и теперь виден);
  - per-key права: `can_edit_param`, `can_view_param`, `can_view_key_value` у config/vision-маршрутов;
  - роли: `guard_admin_lockout`, `guard_last_wildcard`, `validate_permissions`, `match_permission`;
  - `GET /config`: `gate_authorization`.
- `tests/test_routes_contract_barriers.py` (+23 теста, всего 50): новые guard-имена, негативные
  проверки callback-правила (модули/локальные переменные не guard'ы), синтетический X1
  (`_source_checks` видит/не видит `can_access_chat`), манифест фиксирует `can_access_chat` у всех 7
  маршрутов и аналогичные хелперы у roles/config.

### 11.2 Мутации r2 (все RED, `raw/mutation-r2-*.txt`)

| # | Мутация | Результат |
|---|---|---|
| X1 | `GET /direct/context-diagnostics`: удалён только `if not access_srv.can_access_chat(...)` | **RED**: `изменены проверки прав /direct/context-diagnostics ('GET',): ['can_access_chat','get_tma_user'] -> ['get_tma_user']` |
| X2 | `GET /prompts/{prompt_key}/versions`: удалён `await _prompt_require_view(...)` | **RED** (checks теряют `_prompt_require_view`; over-approximation `_prompt_require_edit` не маскирует) |
| X3 | `POST /admins`: удалён `guard_admin_lockout(...)` | **RED** `/admins` |
| X4 | `POST /roles`: удалён `validate_permissions(...)` | **RED** `/roles` |
| X5 | `GET /config`: удалён `fc.gate_authorization(...)` | **RED** `/config` |
| X6 | `POST /roles`: удалён `guard_last_wildcard(...)` | **RED** `/roles` |
| M1 | `GET /admins`: право `access` → `admin` | **RED** |
| M2 | `GET /health`: добавлен `Depends(get_tma_user)` | **RED** |
| M3 | rename `/persona/rules/{rule_id}/sources` | **RED** |
| M4 | `POST /vision/test`: убран `_ctx_global_admin` | **RED** |
| M5 | shadow-дубль `GET /admins` без RBAC | **RED** `неуникальные (path, methods)` |
| M6 | `_prompt_hidden_admin(...)` → `if False:` | **RED** |
| M7 | удалён `_random_selector_guard` | **RED** |
| M8 | убран `recheck=_recheck_config_chat_rights` | **RED** |
| M9 | убран `recheck=_recheck_meme_rights` | **RED** |

Все мутации правили только `web/api/routes.py` с восстановлением; после прогона изменены только
`tests/**`/`plans/**`.

### 11.3 Прогоны r2

| Прогон | Результат | Raw |
|---|---|---|
| self-check `tests/test_routes_contract_barriers.py` + `test_routes_contract_intact` | **51 passed** | — |
| 32 изменённых `tests/test_*.py` (cf. `fa4ba6292`) | **1024 passed, 3 failed** — только известные `test_webapp_round108_ui` (`test_old_labels_gone`, `test_three_windows`, `test_no_accordion`) | `corrective-r2-changed-files.txt` |
| `tests/test_status_section_ui_merge_round1019.py` | **1 failed, 6 passed** — четвёртый предсуществующий red (F-BAR-06), не регрессия | `corrective-r2-status-section-round1019.txt` |
| `pytest --collect-only -q` | **23 734 collected, exit 0**, ошибок коллекции нет | `corrective-r2-collect-only.txt` |
| `python tools/gen_param_registry_round1025.py --check` | **EXIT 0** (`реестр 668 == REGISTRY`) | `corrective-r2-manifest-parity.txt` |
| `--emit` ×2 + `--check` | sha256 манифеста `1e126646…a3c5b9f` неизменен, CHECK OK; испорченная копия → `CHECK FAILED`, exit 1 | `corrective-r2-manifest-parity.txt` |
| `collect_routes()` vs манифест | **78 == 78, equal=True**, дублей/пересечений нет, public без initData = `['/health']` | `corrective-r2-manifest-parity.txt` |

### 11.4 Что теперь покрыто контрактом и что осталось вне него

Покрыто: все 7 chat-isolation маршрутов (`can_access_chat`), per-key проверки `can_edit_param`/
`can_view_param`/`can_view_key_value`, `gate_authorization`, `guard_admin_lockout`,
`guard_last_wildcard`, `validate_permissions`, `match_permission`.

Осталось вне контракта (честно; см. §9): `_persona_access` (резолвер ctx), `gate_snapshot`/
`gate_state` (состояние модулей), `validate_value_rule` (валидация значения), `get_permissions`
(чтение), локальные capability-переменные; семантика внутри guard-хелпера и порядок/кратность
одинаковых вызовов (`checks` — множество). Повторный аудит всего модуля на новые имена не
проводился; класс закрыт для перечисленных соглашений (`^can_`, `^guard_`, `*_admin`,
`(?:^|_)requires?_`, `*_guard`, `*_rights`) и явного списка.

## 12. corrective r3: F-BAR-08/09 (direct vs helper; аргумент `match_permission`)

Ревью r3 подтвердило F-BAR-07 CLOSED и нашло два IN_SCOPE-дефекта: set-union прямых и helper-проверок
маскирует удаление прямого guard'а при одноимённом guard'е в хелпере (F-BAR-08), и аргумент
`match_permission` (алиас `requires_permission`) не фиксировался (F-BAR-09). Corrective r3 code —
`69096c451`; `review-r3.md` закоммичен без изменений.

### 12.1 Схема манифеста (bump 1 → 2)

`tests/routes_contract.py`:

- `_source_checks(fn)` теперь считает **только прямые** проверки: сигнатура + собственное тело
  handler'а, **без** вложенных функций (`_own_nodes`). Плюс route-level зависимости (`get_tma_user`,
  `requires_permission` и т.п.) остаются в `direct_checks`.
- `_helper_checks(fn, module_funcs, max_depth=2)` — отдельный набор: вложенные функции самого handler'а
  (например, `_recheck_config_chat_rights` в `POST /config`) + module-level хелперы, вызываемые из
  handler'а, до 2 уровней (visited-набор от циклов). Глубина 2 нужна для цепочки
  `_persona_can_edit` → `_persona_has_edit_action` (F-BAR-09).
- `assert_routes_contract_intact()` сравнивает `direct_checks` и `helper_checks` **независимо**:
  удаление прямого guard'а всегда меняет `direct_checks`, даже если то же имя осталось в хелпере.
  Ошибки раздельные: «изменены прямые проверки прав …» / «изменены проверки прав в хелперах …».
- Чтение объединения — `route_checks(row)`; потребитель `test_fc_trust_s6_aggregate_api` переведён на
  него. Ручного `checks` в манифесте больше нет.
- `match_permission` добавлен в `_PERMISSION_ARG_CALLS` и обрабатывается как `requires_permission`:
  в манифесте теперь `match_permission:edit_persona` / `match_permission:section.content`, а не голое
  имя (F-BAR-09).

Манифест переэмитирован (`schema: 2`, 78 маршрутов, sha256
`05ed342b…42a19987f`): у каждой строки `direct_checks`/`helper_checks`; проверки из вложенных функций
перенесены из «прямых» в helper-уровень (например, тело `_recheck_config_chat_rights` у `POST /config`).
Публичный набор без initData по-прежнему `['/health']`; дублей/пересечений методов нет.

### 12.2 Мутации r3 (все RED, `raw/mutation-r3-*.txt`)

| # | Мутация | Результат |
|---|---|---|
| X1 | `/direct/context-diagnostics`: удалён прямой `can_access_chat` | **RED**: `изменены прямые проверки прав … ['can_access_chat','get_tma_user'] -> ['get_tma_user']` |
| X1b | `/direct/turn-diagnostics`: то же (одноимённый guard есть в `_turn_attach_text`) | **RED** — `direct_checks` теряет `can_access_chat` |
| X1c | `GET /config/time`: то же | **RED** |
| X1d | `GET /config`: то же (guard есть в `_module_states_for_config`) | **RED** |
| X1e | `POST /config`: то же (guard есть во вложенном `_recheck_config_chat_rights`) | **RED** — `direct_checks` теряет `can_access_chat`, `helper_checks` сохраняет |
| X3 | `POST /admins`: удалён `guard_admin_lockout` | **RED** |
| X4 | `POST /roles`: удалён `validate_permissions` | **RED** |
| X5 | `GET /config`: удалён `fc.gate_authorization` | **RED** |
| X6b | `POST /roles`: удалён `guard_last_wildcard` | **RED** |
| P2 | `match_permission(..., 'edit_persona')` → `'access'` | **RED**: `в хелперах /persona ('DELETE',): ['match_permission:edit_persona', 'match_permission:section.content'] -> ['match_permission:access', ...]` |
| M1 | `GET /admins`: право `access` → `admin` | **RED** |
| M2 | `GET /health`: добавлен `Depends(get_tma_user)` | **RED** |
| M3 | rename `/persona/rules/{rule_id}/sources` | **RED** |
| M4 | `POST /vision/test`: убран `_ctx_global_admin` | **RED** |
| M5 | shadow-дубль `GET /admins` без RBAC | **RED** |
| M6 | `_prompt_hidden_admin(...)` → `if False:` | **RED** |
| M7 | удалён `_random_selector_guard` | **RED** |
| M8 | убран `recheck=_recheck_config_chat_rights` | **RED** |
| M9 | убран `recheck=_recheck_meme_rights` | **RED** |

Все мутации правили только `web/api/routes.py` (восстановление `git checkout`-эквивалентом); после
прогона изменены только `tests/**`/`plans/**`.

### 12.3 Прогоны r3

| Прогон | Результат | Raw |
|---|---|---|
| `tests/test_routes_contract_barriers.py` | **54 passed** (было 50; +X1b/X1d/X1e-класс, direct/helper-схема, P2) | `corrective-r3-manifest-parity.txt` |
| self-check + `test_routes_contract_intact` + `test_fc_trust_s6_aggregate_api` | **64 passed** | — |
| 32 изменённых `tests/test_*.py` (cf. `fa4ba6292`) | **1028 passed, 3 failed** — только известные `test_webapp_round108_ui` (`test_old_labels_gone`, `test_three_windows`, `test_no_accordion`) | `corrective-r3-changed-files.txt` |
| `tests/test_status_section_ui_merge_round1019.py` | **1 failed, 6 passed** — четвёртый предсуществующий red (F-BAR-06), не регрессия | `corrective-r3-status-section-round1019.txt` |
| `pytest --collect-only -q` | **23 738 collected, exit 0**, ошибок коллекции нет | `corrective-r3-collect-only.txt` |
| `python tools/gen_param_registry_round1025.py --check` | **EXIT 0** (`реестр 668 == REGISTRY`) | `corrective-r3-manifest-parity.txt` |
| `--emit` ×2 + `--check` | sha256 `05ed342b…42a19987f` неизменен; `CHECK OK`; испорченная копия → `CHECK FAILED`, exit 1 | `corrective-r3-manifest-parity.txt` |
| `collect_routes()` vs манифест | **schema 2, 78 == 78, equal=True**, дублей/пересечений нет, public = `['/health']`, rows с legacy `checks` = 0 | `corrective-r3-manifest-parity.txt` |

### 12.4 Что осталось вне контракта

`_persona_access` (резолвер ctx), `gate_snapshot`/`gate_state` (состояние модулей),
`validate_value_rule` (валидация значения), `get_permissions` (чтение), локальные capability-переменные
(`can_read`/`can_edit`/`can_write`, модуль `prompt_access`, `global_access`) — по-прежнему не checks.
Не покрываются: смена семантики внутри самого guard-хелпера, порядок/кратность одинаковых вызовов
(check-наборы — множества), цепочки хелперов глубже 2 уровней, а также guard'ы, переданные по ссылке
под именем, не подходящим под узкое callback-правило. Продукт не менялся; ассерты не ослаблены —
сравнение стало строже (два независимых набора вместо одного union).
