# S10 `summary-deploy-round1026` — evidence (Step 4 @Builder)

- **Фича:** S10 (Эпик 2, §107/§114/§115/§116/§117), **P0 gate**, Risk **R2**. **ADR-1026-12** (D1–D8), `spec.md` (REQ-S10-01…-14 / SC-01…SC-18).
- **Дата:** 24.09.2026. **Автор:** @Builder.
- **Baseline:** HEAD **`76abf91`** == `origin/master` == annotated-тег **`pre-round1026-s10`**; `APP_VERSION` был **2.58.28**; pytest `.venv` baseline **9000/0**; JS **47/47**; каталог **469/426/444/100/98/21**; Δ DDL=0 (SQLite v12).
- **Итог Step 4:** механика активации (default ON), docstrings, README, §114-harness (11/11), §115-процедура/артефакты, §117-результаты; тесты OFF-default обновлены. `APP_VERSION` → **2.58.29**; pytest **9026/0** (+26); JS **47/47**; `git diff --check`=0. **Коммит не делался.**
- **Ограничения процесса:** `plans/current_task.md`, машинный блок `OPENCODE_WORKFLOW_STATE_V1`, `tasks.md`, `spec.md`/ADR (заморожены Step 2), `backlog.md`, `metrics.md`, `ARCHITECTURE.md` — **не изменялись**; `@Scanner` не создавался. Чекбоксы `tasks.md` не проставлялись (правки `tasks.md` — только @PM).

## 1. Что реализовано (по блокам tasks.md)

### Блок B — механика активации §107 (T-3464…T-3466)
- **`config/settings.py:978–988`** — `SUMMARY_HYBRID_L2_ENABLED` **`_env_bool("SUMMARY_HYBRID_L2_ENABLED", True)`** (было `False`): code-default **OFF→ON**; комментарий переписан (D2: default ON; `per-chat → hot → env/default` сохранён как **аварийный kill-switch**; «ручная активация»/UI-селектор Legacy↔Hybrid запрещены; «аварийное выключение» `false`+рестарт разрешено). Логика резолва **не менялась**.
- **`services/summary_generator.py`** — **только docstrings**: `_hybrid_l2_enabled` (default True, аварийный OFF) и `_run_hybrid_l2` (основной путь без ручной активации). Тела функций **не тронуты** (AST-тест).
- **`services/summary_l2_writer.py`** — docstring: за флагом, с S10 default ON, явный `false` — kill-switch.
- **Фильтр/роутинг** — уже default ON/активны (факты 4–5 spec): код не требуется; покрыты тестами (см. §3).
- **`config/settings.py:1827`** — bump `APP_VERSION` **2.58.28 → 2.58.29** (+ S10-описание); **`README.md`** — `v2.58.29` + S10-раздел (cache-bust через `?v=__APP_VERSION__`).

### Блок C — §114 предполётный harness (T-3467) + тесты (T-3471)
- **NEW `tests/test_summary_deploy_round1026.py`** (25 тестов): 11 §114-сценариев (класс `TestSec114Scenarios`), активация (default ON без ручного действия; explicit OFF kill-switch; per-chat override), фильтр/роутинг, R17, границы diff, AST-равенство логики, version/catalog. **0 реальных отправок** (шпионы + guard, бросающий при обходе). Чек-лист — `sec114-harness.md`.
- **Обновление OFF-default-тестов (T-3471):** `tests/test_summary_l2_integration.py` (`test_flag_default_off` → `test_flag_default_on`; `test_hybrid_disabled_by_default` → `test_hybrid_disabled_by_explicit_false`; + `test_hybrid_enabled_by_default`); комментарии `tests/test_summary_fact_package.py:544-547`, `tests/test_summary_l1_clusterizer.py:1011-1013`, docstring `tests/test_summary_test_run.py:5`.
- **Legacy-тесты `_run` переведены на ЯВНЫЙ OFF** (требование «OFF-путь тестируется явным флагом, а не дефолтом»): helpers `tests/summary_cover_helpers.py::generator`, `tests/test_summary_generator.py::_make_generator`, `tests/test_summary_cover_round1023.py::_make_generator`, `tests/test_summary_concurrency.py::_make_generator`; helper `_patch_chat_limit` в `tests/test_summary_logging_runid.py`/`tests/test_summary_publish_integration_round1026.py` (явный OFF, если не задан ON); точечно `tests/test_summary_filter_integration.py`, `tests/test_summary_context_restore_integration.py`, `tests/test_summary_l1_clusterizer.py`, `tests/test_summary_two_call_round1022.py`, `tests/test_verbilizer_response_modes_round1023.py`, `tests/test_token_analytics_round1023.py`.
- **Version-pins** `2.58.28 → 2.58.29`: 17 pytest-файлов + 4 JS-файла; `tests/test_round1025_f8_registry.py:126-130` (комментарий bump-цепочки + ассерт).

### Блок D — §115 процедура/артефакты (T-3468/T-3469)
- **NEW `plans/features/summary-deploy-round1026/procedure-115.md`**: 7 пост-деплой-проверок + детерминированные rich/plain-артефакты (рендер S5-форматтером, 0 LLM/0 отправок). Живой прогон (§115 п.5/7) — за @DevOps/владельцем после деплоя.

### Блок E — §117-результаты (T-3470)
- **NEW `plans/features/summary-deploy-round1026/results.md`**: 14 пунктов §117 «После Эпика 2» с трассировкой к S1–S10; «живые» пункты помечены ⏳ post-deploy.

## 2. Команды и фактические результаты

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9026 passed, 0 failed** (155.35 с); baseline 9000 → **+26** |
| Новый S10-файл | `pytest tests/test_summary_deploy_round1026.py -q` | **25 passed** (11 §114 + активация/роутинг/границы) |
| 2-вызовность | `pytest -k two_calls tests/test_summary_l1_clusterizer.py tests/test_summary_l2_integration.py tests/test_summary_test_run.py tests/test_summary_deploy_round1026.py` | **5 passed** (`await_count==2`; ON-сценарии harness тоже 2) |
| JS (47 файлов) | цикл `node tests/js/*.js` | **OK=47 FAIL=0** |
| `git diff --check` | — | exit **0** |
| Каталог/версия | импорт `param_catalog`/`settings` | `APP_VERSION` **2.58.29**; **469/426/444/100/98/21** |
| Каталог `--check` | `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` |
| Δ DDL=0 | `db/**` вне diff; DDL-поиск по изменённым модулям | подтверждено (`TestBounds::test_no_ddl_in_touched_sources`) |
| Границы diff | `git diff --name-only pre-round1026-s10 -- <запрещённые пути>` | **пусто** (`image_generation.py`/`telegram_send.py`/`summary_prompts.py`/`prompt_migrations.py`/`summary_filter.py`/`summary_context_restore.py`/`summary_l1_clusterizer.py`/`summary_fact_package.py`/`summary_article_formatter.py`/`summary_test_run.py`/`routes.py`/`web`/`db`/`param_catalog.py`/`bot.py`) |
| Логика не тронута | AST-равенство `_run`/`_run_hybrid_l2`/`_hybrid_l2_enabled` без docstring vs `pre-round1026-s10` | идентично (`TestBounds::test_run_logic_ast_identical_to_baseline`) |
| 0 новых зависимостей | манифесты/локи вне diff | подтверждено |
| CSP/zero-build | `web/**` вне diff | подтверждено |

## 3. Покрытие SC (сжато)

- **SC-01/SC-03** — `TestActivation` (default ON; `_run` → `_run_hybrid_l2` без ручного действия; explicit `false` → legacy; per-chat override).
- **SC-02/SC-14** — §104/§110/S8/S9/routes/db/каталог/`telegram_send`/каноны вне diff; UI-тумблеров/селектора Legacy↔Hybrid нет (diff D1).
- **SC-04** — `SUMMARY_FILTER_ENABLED` default True + `TestFilterAndRouting::test_filter_default_on_is_applied` (S1 вызывается).
- **SC-05** — `test_independent_l1_l2_slots` (env-only, пусто → глобал).
- **SC-06…SC-08** — §114 harness 11/11, 0 реальных отправок; порядок «проверка → деплой» (`sec114-harness.md`).
- **SC-09/SC-10** — `procedure-115.md` (7 проверок + rich/plain артефакты); live — ⏳.
- **SC-11** — §116: все критерии «не завершён» не нарушены (см. §5).
- **SC-12** — `results.md` (14 пунктов).
- **SC-13/SC-16** — Δ DDL=0, Δ каталога=0 (F8 N/A), CSP/zero-build, 0 зависимостей, 2-вызовность, R17/R18, регресс 9026/0, JS 47/47, `git diff --check`=0.
- **SC-15** — откат: soft `SUMMARY_HYBRID_L2_ENABLED=false`+рестарт / hard `git revert`; тег `pre-round1026-s10`→`76abf91` (R18).
- **SC-17/SC-18** — Risk R2 (ADR D6); live-приёмка — за владельцем.

## 4. R17 / R18 / инварианты

- **R17:** `TestBounds::test_r17_no_raw_text_in_logs` — секрет доставлен, но отсутствует в логах; R17-контракты S7/S6 не менялись (логика вне diff).
- **R18:** тег `pre-round1026-s10`, бэкапы `var/backups/s10-round1026-*`, `.env.bak.round1026-s10` — не удалялись.
- **Δ DDL=0**; **Δ каталога=0** (469/426/444/100/98/21; F8 не переиздаётся); **CSP/zero-build**; **0 новых зависимостей**; **2-вызовность** (`await_count==2`).

## 5. §116-критерии «ЭПИК 2 НЕ ЗАВЕРШЁН, ЕСЛИ…» (sanity)

- Новый пайплайн **не** выключен: code-default ON, активация без ручного действия (§3 SC-01). L1/L2 — правильные модели по слотам (SC-05). Фильтр ON (SC-04). L1 не пишет готовое Саммари (архитектура S3, вне diff). L2 получает содержание (пакет §96, вне diff). Rich Message — настоящий `<h1>` (SC-10). `generate_image` не переписан (SC-14). Absence обложки не теряет текст (SC-09/§114-09). Обычный `sendMessage` без неподдерживаемых тегов (§105 S6, вне diff). Причина сбоя устанавливаема (§109/S7, вне diff). Новые этапы в карте (S8, вне diff). Второй аналитики нет. Настройки — прежние UI (вне diff).

## 6. Границы diff (факт)

- **Изменено @Builder (tracked) — 37 файлов:** `config/settings.py` (default+комментарий+`APP_VERSION`), `services/summary_generator.py` (docstrings), `services/summary_l2_writer.py` (docstring), `README.md`, `plans/docs/param-registry-round1025.meta.md` (провенанс-штамп `APP_VERSION`) — **5 код/док-файлов**; **28 файлов в `tests/`** (27 тест-модулей + helper `tests/summary_cover_helpers.py`) + **4 JS-теста** — re-pin версии и/или явный OFF. Всего `git status` показывает 39 `M`, включая 2 pre-existing (ниже). Полный список — `git diff --name-only pre-round1026-s10`.
- **Untracked:** `plans/features/summary-deploy-round1026/` (spec/ADR/tasks + `evidence.md`/`results.md`/`procedure-115.md`/`sec114-harness.md`), `tests/test_summary_deploy_round1026.py`.
- **Вне diff (подтверждено пустым diff):** §104-контур (`services/image_generation.py`), `services/telegram_send.py`, каноны/промпты/миграции, логика `summary_filter.py`/`summary_context_restore.py`/`summary_l1_clusterizer.py`/`summary_fact_package.py`/`summary_article_formatter.py`, `services/summary_test_run.py`, `web/api/routes.py`, `web/**`, `db/**`, `services/param_catalog.py`, `bot.py`, манифесты зависимостей; тела `_run`/`_run_hybrid_l2`/`_hybrid_l2_enabled` — AST-идентичны baseline.
- **Pre-existing (не @Builder, изменены до старта Step 4):** `plans/MEMORY.md`, `plans/workflow_state.md`.

## 7. Хэши (SHA-256, на момент финальных прогонов)

| Файл | SHA-256 |
|---|---|
| `config/settings.py` | `0C14A544B277769155C598853D71E992CF5D2A141498CC9540CC0861CF7CD0A3` |
| `services/summary_generator.py` | `AD1CC281B105662F9EE45F63F4B6CB2F68DA348B0435A571F37D9390F6AA2E7F` |
| `services/summary_l2_writer.py` | `7AE529464FF0823F8A111A6A408BC806779AFA68E585AAB1FCF2BFB8F2951F62` |
| `README.md` | `9ED255FCE56568F0CA04369A18757B9EFC2F8F21907382FA69F824644441CC6A` |
| `plans/docs/param-registry-round1025.meta.md` | `455B45816F0CFA3C81CE55F76F6BEACC96BE30A7F380FDDC2F1B8040C841AD51` |
| `tests/test_summary_deploy_round1026.py` | `8D5028581010255744F0470460DE754F333DA32974F15402520FFE3BEB782DBC` |
| `tests/test_summary_l2_integration.py` | `4251CE8E12593C08A382C8E16B617600CDCAEA2D6331CBAD73FFE5C0D9023A3C` |
| `tests/summary_cover_helpers.py` | `3EDA2E19C1658D95E9EAF5136B64410BFE99A64576794EB45159E1BF24C522D3` |
| `tests/test_summary_generator.py` | `3DA4CECC2EFFB978C5416898DE85F038FF54FA590899D6992BF67046217EE422` |
| `tests/test_summary_cover_round1023.py` | `0FD0E27DC27D210A71C7D740ECD6C26BBA2AEFCE37B87A4741CD2103B1F40AFD` |
| `tests/test_summary_logging_runid.py` | `0D305BBF8B98769784A4958E23F54123411FED7A5B7ED922C03054F048C383B1` |
| `tests/test_summary_publish_integration_round1026.py` | `8B142CEF34D81D59D91A0DA935B9DD826D203CC0148A9F98216DAD9AB8A81B88` |
| `tests/test_summary_concurrency.py` | `A467471ED54583CBAAE161DAD711C0DFA8B791CE6E24699366BC2EDF28BE0955` |
| `tests/test_summary_filter_integration.py` | `E1CB291261EAABAE09DFAE2CD8210E33AC52DD7916BFDB45667CE10A9B1658B8` |
| `tests/test_summary_context_restore_integration.py` | `0E9277FA0E9FB169AC8D275DD06B07ADE49FFDE0AF6CCD9F18F92F02376A7890` |
| `tests/test_summary_l1_clusterizer.py` | `B217091ECD8DA5BD149CAAC71E29813449931A8928A2102B1FEBFBBD85DA9024` |
| `tests/test_summary_test_run.py` | `624C153831E4C834630D0ED914042F92BF65C8CC26AD7598CE83A81E6E478AF3` |
| `tests/test_summary_two_call_round1022.py` | `3F1B583589148CA3BD73BFD966AAE600BD37F2679E1D5FE112F7A7024E49C84C` |
| `tests/test_token_analytics_round1023.py` | `C38CA65D4FEF95E1D6001F581C275A1918AB05651F2C54D16DD0588FC3A5E52B` |
| `tests/test_verbilizer_response_modes_round1023.py` | `248BA7AB096DB73C7026FD58B1B1E2A95F3DB5111EB4C060ECCDB53D60EE4C6A` |

## 8. Решения/отклонения (для Reviewer)

1. **`plans/docs/param-registry-round1025.meta.md`** — обновлён только провенанс-штамп `APP_VERSION` 2.58.28→2.58.29 (прецедент S7/S8/S6: иначе `tests/test_round1025_f8_registry.py::test_meta_provenance` краснеет при bump). Каталог/TSV/F8 **не переиздаются** (Δ каталога=0, `--check` OK). Формально файл не перечислен в ADR D1, но его правка — минимально необходимая для зелёного регресса; при несогласии — вернуть @Architect.
2. **Массовое обновление legacy-тестов `_run`** (явный OFF) — вне точного списка ADR D1 (`tests/**` разрешён). Требование задачи «OFF-путь тестируется явным выставлением флага OFF, а не дефолтом» и зелёный регресс вынуждают это. Assertions не ослаблены — добавлен явный OFF там, где тест не про Hybrid.
3. **`test_summary_test_run.py`** — ассерт `flag_before == flag_after is False` → `is True` (dry-run по-прежнему не читает/не меняет флаг; значение default изменилось). Логика S9 не тронута.
4. **`_hybrid_l2_enabled`** — только docstring; поведение/fail-safe `False` при исключении сохранены.
5. **§115 живой прогон/§117 live-пункты** — не в Step 4 (post-deploy, @DevOps/владелец); Builder дал процедуру и детерминированные артефакты.

## 9. Незакрытое / вне Step 4

- **Коммит, merge (T-3476), архивация (T-3477), deploy/активация/§115 (T-3478), handoff (T-3479/T-3480)** — не выполнялись.
- **Live-приёмка** (владелец) — ⏳ PENDING; чекбоксы `tasks.md` не проставлялись.
- **Единственный флак при первом полном прогоне:** таймаут teardown `tests/test_summary_memory.py` (Windows asyncio) — при повторе и в изолированных прогонах не воспроизвёлся (`test_summary_memory.py` 79 passed; связка с S10-файлом 104 passed); финальный полный прогон — 9026/0 без таймаутов.
