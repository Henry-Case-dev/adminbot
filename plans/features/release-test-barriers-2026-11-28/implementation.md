# Release/Test Barriers Corrective — отчёт реализации (2026-11-28)

- **Ветка:** `fix/release-test-barriers-2026-11-28`
- **База:** `release/2.58.272` tip `a2195fe3f` (продуктовый кандидат `f6cd011e0` + bump `cb47e6cbd`); на момент
  rebase release-ветка ушла вперёд deploy-docs `fa4ba6292` (код не менялся) — ветка ребейзнута на неё.
- **Worktree:** `WorkspaceData/worktrees/…/release-test-barriers-2026-11--19f1987d0616-5da2a6da`
- **Кодовый кандидат:** `7e8eb8a05a8ea0bfefbef4b7a277328d9189f61d` (tests/contracts + `plans/project.md`; evidence-коммит идёт следом)
- **Прямое поручение владельца:** убрать повторяющиеся механические барьеры тестов и релиза (2026-11-28).

## 1. Полнофайловые sha256-пины продуктовых файлов — найдено и заменено

Инвентарь (полный, по всем `tests/*.py`):

| Файл-объект | Где был пин | Замена |
|---|---|---|
| `web/api/routes.py` | `test_round1025_f8_registry.ROUTES_SHA256_F11` (+`test_routes_file_unchanged`); копия в `test_mca23_planned_vs_actual`; импорт в `test_asap7_cover_preview`, `test_mca10b…`, `test_mca12…`, `test_mca17c…`, `test_fc_trust_s6_aggregate_api` | `tests/routes_contract.py`: объявленный манифест `tests/fixtures/routes_contract.json` (78 операций: path + methods + initData + нормализованные guard-проверки). Падает при удалении/переименовании маршрута, смене метода, снятии RBAC/иной проверки прав, появлении необъявленного маршрута. |
| `services/param_catalog.py` | `PARAM_CATALOG_SHA256_FOLLOWUP` (`TestFrozenInvariants.test_param_catalog_unchanged`) | `test_param_catalog_identity_contract`: идентичность ключей с `catalog_baseline.json`, валидные типы/чувствительность; описания/типы/секретность остаются под переэмиссией `gen.run_check` (отдельный TestGenerator). |
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
- Тесты: `test_round1025_f8_registry`, `test_mca23_planned_vs_actual`, `test_asap7_cover_preview`,
  `test_mca10b_random_applications_block_d_round1041`, `test_mca12_stories_round1046`,
  `test_mca17c_invariants_round1047`, `test_fc_trust_s6_aggregate_api`, `test_tool_coordinator_round1026`,
  `test_unified_image_request_round1026`, `test_webapp_f9_round1025`, `test_hotfix_round1025_cachebust`,
  `test_webapp_round108_ui`, + 19 version-литеральных файлов из §2.
- Правило: `plans/project.md` — «соразмерные проверки изменённых компонентов; полный прогон — при техническом
  основании/обязательном релизном требовании; релизные гейты не ослабляются».
- Карты/`progress_scope.json`/`workflow_state.md` не изменялись.

## 9. Ограничения

- `routes_contract.json` — объявленный контракт: санкционированное добавление маршрута требует одной осознанной
  записи в манифест (команда генерации описана в `tests/routes_contract.py`), но больше не зависит от
  комментариев/форматирования/тела обработчиков.
- Проверки прав нормализованы по guard-вызовам (`_ctx_global_admin`, `requires_permission:<право>`,
  `_prompt_require_*`, `_require_chat_access`, `_is_global_admin`, …); смена *семантики* самого guard-хелпера
  контрактом маршрутов не покрывается — это зона тестов ACL/ролей.
- 3 UI-снимка 10.8 остаются красными (см. §4), не входят в контракт этой задачи.
- `test_webapp_round108_ui` содержит и исправленный version-тест, и 3 несвязанных падения; в прогонах выше они
  явно отделены deselect'ом.
