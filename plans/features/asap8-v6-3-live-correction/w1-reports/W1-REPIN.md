# W1-REPIN — re-pin freeze-тестов каталога + классификация остаточных (v6.3 B01)

Лейн: W1-REPIN · дата: 15.10.2026 · база: HEAD bc91b90 + незакоммиченное дерево Wave 1 (НЕ коммитилось).
Санкция: ASAP 8 v6.3 B01 (W1-CHAT-INTEL) — Δ каталога +10 ParamSpec INITIATIVE_* (2 flags_intent, 8 limits_intent), REQ-B01-4 (per-chat профиль частоты инициативы, снапшот plans/features/asap8-v6-3-live-correction/source-lines-37423-EOF.md).

## 1. Правки ParamSpec (services/param_catalog.py — только title/description)

| Ключ | Правка |
|---|---|
| INITIATIVE_EVAL_LLM_BUDGET_PER_DAY | title «LLM-оценок в сутки на чат» → «Семантических оценок в сутки на чат» (FORBIDDEN 'llm', test_webapp_round109_ui::TestDescriptions::test_no_forbidden_jargon) + добавлен description (был пустой) |
| INITIATIVE_MAX_REPLIES_PER_DAY | +description (тест-канон test_descriptions_nonempty) |
| INITIATIVE_DAY_WINDOW_SECONDS | +description |
| INITIATIVE_MAX_REPLIES_PER_TOPIC | +description |
| INITIATIVE_EVAL_MIN_MESSAGES | +description |

Все новые тексты проверены по FORBIDDEN-словарю round109 (rag/llm/stt/…/дайджест) и AI-шаблону «включ…выключ…» — чисто. Стиль — как у соседних MCA_INTENT_* записей.

### Permission-матрица (задача 1c)
`test_webapp_api::test_param_permissions_matrix_metadata_and_coverage` строит матрицу автопокрытием (items == categorized, category+group → tab/tab_title). Явный permission-флаг новым ключам НЕ нужен — прецедент CHAT_DECISION_* (ADR-1026-20 D6) идентичен. Пин 536 → 546.

## 2. Re-pin счётчиков (561→571, categorized 536→546, delta 150→160)

Имена тестов сохранены; ожидания обновлены, санкционные комментарии добавлены в ключевых точках.

| Файл:что | Было → Стало |
|---|---|
| tests/test_round1025_f8_registry.py | test_counts_frozen 561→571 (GROUPS 120/TAB 118/RULES 23 без роста); test_rows_complete_no_empty rows 561→571; test_delta_explicit 150→160; test_meta_provenance "561"/"150"→"571"/"160"; test_all_params_have_a_place 561→571 |
| tests/fixtures/round1025/f8_baseline.json | counts.REGISTRY 561→571, counts.delta 150→160; sha256 param_catalog.py → 0bfc9724d3e4687651283f5dfc59b406ca4535080f2891572782061e9761f16b; superseded_by += запись ASAP 8 v6.3 B01 (стиль/хронология цепочки сохранены) |
| tests/fixtures/round1025/catalog_baseline.json | registry_keys 561→571 (+10 INITIATIVE_*), counts.REGISTRY 571 |
| plans/docs/param-registry-round1025.tsv | регенерирован генератором: 571 строка (+10 INITIATIVE_*), 572 с header |
| plans/docs/param-registry-round1025.meta.md | регенерирован (провенанс 571/411/160) |
| plans/docs/screen-map-round1025.md | регенерирован (ключи == registry_keys, 571) |
| tests/test_param_catalog.py | _CLASSVAR_CATALOGUED +10 (прецедент MCA_INTENT_*); test_pg_keys_dotted_and_unique — ns-исключение «initiative.*» (product-ключи резолва B01, категории flags/limits); test_group_counts_match_design flags 96→98, limits 212→220 |
| tests/test_history_retention_toggle.py | extra-исключение coverage +10 INITIATIVE_* |
| tests/test_webapp_api.py:1420 | categorized 536→546 |
| tests/test_webapp_round109_ui.py | REGISTRY 561→571 |
| tests/test_mca19_block_f_round1043.py | TSV-строки 562→572; REASON_CODES 285→290 |
| tests/test_mca10b_random_applications_block_d_round1041.py | fx.delta 150→160 |
| REASON_CODES 285→290 (wave: services/mca_events.py +5 кодов B01/B02) | test_mca10b_random_applications_block_a_round1041, test_mca17c_invariants_round1047, test_mca20_integration_round1045, test_mca20_rework1_f1_f2 |
| Bulk 561→571 / 536→546 (прецедент tools/_mca20_reissue_f8.py шаг 3) | test_budget_data_repair_round1024, test_budget_global_toggle_round1024, test_budget_guardrails_round1024 (×2), test_budget_settings_round1019 (×2), test_decision_making_round1026, test_frontend_tab_mapping, test_help_guide_round1014 (×2), test_ia_inventory_round1025, test_image_context_memory_round1026, test_mca10a_random_source_block_c_round1037, test_mca10b_random_applications_block_d_round1041 (fx/cb/stdout), test_mca17c_invariants_round1047, test_mca19_block_f_round1043, test_memory_lookup_round1026, test_round106_ia_smoke, test_self_reflection_provider_round1014 (×2), test_settings_persistence_round1014 (×2), test_summary_asap21_prefilter_removal, test_summary_asap2_miniapp_round1027, test_summary_deploy_round1026, test_summary_fact_package (×2), test_summary_l1_clusterizer (×2), test_summary_l2_writer (×2), test_summary_logging_runid (×2), test_summary_publish_integration_round1026 (×2), test_summary_test_run (×2), test_telegram_reactions_round1026 (×2), test_tool_chains_round1026, test_tool_coordinator_round1026 (×2), test_ui_verbilizer_tabs_round1023, test_unified_image_request_round1026, test_webapp_f11_round1025, test_webapp_f4_round1025, test_webapp_f5_round1025, test_webapp_f7_round1025, test_webapp_f9_round1025, test_webapp_hotfix10_round1025, test_webapp_hotfix7_round1025, test_webapp_hotfix8_round1025, test_webapp_hotfix9_round1025, test_webapp_parity_smoke, test_webapp_round1010_ui, test_webapp_round1011_ui, test_webapp_round1012_ui (×2), test_webapp_round1013_ui (×2), test_webapp_round1014_ui (×2), test_webapp_round1020_ui, test_webapp_round1026_polygon |

F8-чек: `py -3 tools/gen_param_registry_round1025.py --check` → EXIT=0 («CHECK OK: реестр 571 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны»).

Инцидент в процессе: bulk-скрипт перевёл LF→CRLF в 48 тестовых файлах; конвенции line-ending восстановлены байт-точно по HEAD (итоговый git diff — только пин-строки).

## 3. Классификация остаточных фейлов полного свипта

Метод: (a) изолированный прогон файла; (b) pair/префикс-прогоны; (c) HEAD-worktree bc91b90 (git worktree в temp, рабочий tool не stash'ился).

| Тест | isolate | HEAD | Вердикт |
|---|---|---|---|
| test_asap8_v63_b07_temporal_factcheck::test_seed_idempotent_owner_values_delta_zero | FAIL | PASS | **CURRENT-BLOCKER (wave)** — см. §4 |
| test_pg_db.py ×7 (TestDdl::test_init_twice_no_errors, TestRoleSeeds::test_seed_sql_conflict_do_nothing, TestSettingsSeed ×4, TestJsonCodecs::test_bad_code_source_warns_and_continues) | FAIL | PASS | **CURRENT-BLOCKER (wave)** — см. §4 |
| test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer | FAIL | PASS | **wave-caused**: handlers/chat_migration.py добавил 4 write-точки (не в allow-списке пина). Аудит/репин — на лейне-владельце chat_migration (вне моего WRITE_SCOPE, фиксить продукт/чужой контракт нельзя) |
| test_mca02_safe_fetch_round1027::test_web_extractor_blocks_destination_without_fallback | FAIL | FAIL | pre-existing (не wave) |
| test_mca16_experience_block_d_round1039::test_no_per_message_llm_reflection_module_is_llm_free | FAIL | FAIL | pre-existing (не wave) |
| test_summary_asap2_failsoft_round1027::test_t3959_10 | FAIL | FAIL | pre-existing (не wave) |
| test_outgoing_guard_round1022 ×2 (send_rich_message) | FAIL | FAIL | pre-existing env: aiogram 3.29.1 без InputRichMessageMedia |
| test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article | FAIL | **FAIL (изолированный файл-прогон на HEAD bc91b90)** | pre-existing, не wave; вторая «ожидаемая ×2» от этого файла была catalog-пином (test_catalog_zero_delta) — закрыта репином |
| test_nostalgia_worker::test_unanswered_resolved_by_user_message | PASS | pair FAIL | **межфайловая утечка, предсуществующая**: test_bot_main_flow (test_main_polling_error_state / test_dev_stop_actually_stops_bot) оставляет `_FakeCache` в глобальном `services/hot_config._cache` (bot.main() → set_config_cache), из-за чего гейт nostalgia читает Settings-дефолт вместо тестового флага → sent=0. Воспроизведено pair-прогоном и на HEAD. **ПОЧИНЕНА** conftest-фикстурой (см. ниже); в финальном свипте файл зелёный |
| test_mca09_intents_block_e_round1040::test_candidate_ready_defers_intent_backoff / test_handle_initiative_cancelled_by_recheck | PASS | PASS (файл целиком на HEAD: 15 passed) | **межфайловая утечка, порядок-зависимая**: изолированный файл-прогон в wave-дереве и на HEAD — зелёные; падает только в полном свипте, причём identity падающего теста ПЛАВАЕТ между прогонами (sweep2: candidate_ready, sweep3: cancelled_by_recheck) — сильное доказательство межфайлового загрязнения состояния, а не детерминированного дефекта. Механизм шире санкционированных hot_config/_pending (фикстура их сняла — candidate_ready позеленел); остаток классифицирован, не фиксен |

### Фикс тест-инфраструктуры (санкция брифа п.5)
tests/conftest.py + module-scoped autouse фикстура `_global_singletons_reset_per_file`: после КАЖДОГО тестового файла сбрасывает `services/hot_config.set_config_cache(None)` и `services/mca_events.reset_pending()` (буфер `_pending` + счётчики spool). Внутрифайловое состояние не трогается (teardown после yield). TEST-LIFECYCLE: REGRESSION owner=W1-integration. Прецедент: `_settings_module_identity_restore` (SWEEP-FIX ASAP 7).
Проверено: pair test_bot_main_flow+nostalgia зелёный; кэш-чувствимые файлы (test_hot_config, test_config_cache, test_direct_chat_concurrency, b01_observer) — зелёные.

## 4. CURRENT-BLOCKER для Orchestrator (вне WRITE_SCOPE, продукт не трогал)

**Корень:** 10 ParamSpec INITIATIVE_* объявлены с `settings_field="INITIATIVE_*"`, но в `config/settings.py` эти имена НЕ существуют (ни field, ни ClassVar — проверено `hasattr(Settings, ...)` = False).

**Симптом:** `_seed_settings_into` (services/pg_db.py:755, wave B07.2) для не-секретных specs сидируемых категорий (flags/limits ∈ SEED_CATEGORIES) делает `getattr(settings, spec.settings_field)` БЕЗ default → AttributeError: 'Settings' object has no attribute 'INITIATIVE_OBSERVER_ENABLED'. Падают 8 тестов (test_pg_db ×7 + b07_seed), и **реальный PG-сид на проде упадёт так же** → релиз-блокер B01.

**Отчёт лейна W1-CHAT-INTEL** (w1-reports/W1-CHAT-INTEL.md:197) помечал Settings-ClassVar как «опционально (getattr с default уже работает)» — эффект сида не учтён.

**Минимальный патч (прецедент MCA_INTENT_*, config/settings.py:1565):** добавить 10 ClassVar env-осей (2 bool: INITIATIVE_OBSERVER_ENABLED/INITIATIVE_ENABLED default True; str INITIATIVE_FREQUENCY_PROFILE default "normal"; 7 int — дефолты профиля normal: min_gap 7200, max_replies_per_day 6, day_window 86400, max_replies_per_topic 1, eval_min_messages 8, eval_min_interval 2700, eval_llm_budget 12). ClassVar не меняют пин Settings-полей (454) и уже внесены в исключения coverage-тестов настоящим лейном. Инициативный выход: лейн W1-CHAT-INTEL.

## 5. Финальный полный свипт

`py -3 -m pytest tests -q` (sweep3, текущее дерево): **16 failed, 13442 passed, 1 skipped, 9:14**.
Прогрессия: старт свипта лейна 87 failed → после репина 35 → финал 16.

Все 16 — заранее классифицированные, ни одного каталог-пина:

| Группа | Тесты | Классификация |
|---|---|---|
| INITIATIVE_* не в Settings (один корень) | test_pg_db ×7 + test_asap8_v63_b07_temporal::test_seed_idempotent_owner_values_delta_zero | CURRENT-BLOCKER (§4), вне WRITE_SCOPE |
| chat_migration write-points | test_mca01_tx_task_supervisor::test_write_points | wave-caused, репин на лейне-владельце |
| порядок-зависимая утечка | test_mca09_intents_block_e (identity теста плавает между прогонами) | isolate/HEAD зелёные |
| env/предсуществующие | test_mca02_safe_fetch, test_mca16_experience, test_summary_asap2_failsoft, test_outgoing_guard ×2, test_summary_publish_integration::TestOnDelivery | все FAIL на HEAD bc91b90 изолированно |

Затронутые фикстурой файлы перепроверены вместе (test_bot_main_flow + test_nostalgia_worker + test_mca09_intents_block_e + reload-тяжёлые test_betterstack_handler/test_settings_helpers): **128 passed**. Кэш-чувствимые (test_hot_config, test_config_cache, test_direct_chat_concurrency, b01_observer) — зелёные.

Финальный sha256 `services/param_catalog.py`: `0bfc9724d3e4687651283f5dfc59b406ca4535080f2891572782061e9761f16b`.

## 7. Готовность к коммиту

Тестовая часть лейна (репины, fixtures, F8-артефакты, conftest-фикстура) — готова и не коммитилась. Набор НЕ готов к коммиту как «зелёный» до закрытия §4: нужен продуктовый микро-патч (10 ClassVar INITIATIVE_* в config/settings.py, прецедент MCA_INTENT_*) от лейна W1-CHAT-INTEL/Orchestrator — снимет 8 фейлов (pg_db ×7 + b07 seed) и разблокирует прод-сид. Плюс решение по mca01-пину (аудит 4 write-точек chat_migration.py). Остальные 7 — санкционированные предсуществующие/env.

## 6. Внешние источники

Не привлекались: все решения опираются на внутрирепозиторные факты (тест-каноны, прецеденты MCA-20/ASAP-7, текущий код).
