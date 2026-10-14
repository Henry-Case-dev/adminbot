# ASAP 7 — SWEEP-FIX отчёт (финальная гигиена релиза 2.58.74)

STATUS: FINAL
LANE: SWEEP-FIX, HEAD a1b3279. Старт: 97 failed / 12794 passed → финал: **12889 passed / 2 failed**
(ровно два задокументированных pre-existing). Полный синхронный прогон `.venv`, `-p no:randomly`,
9:01. node --check 4 js-харнессов OK.

## Root cause группы E (главное)

**Утечка состояния найдена и устранена — это `importlib.reload(config.settings)`.**

Chain: `tests/test_betterstack_handler.py::_import_bot` (а также ~60 других reload-сайтов:
test_settings_helpers, test_mca01_tx, test_bot_main_flow, test_summary_test_api,
test_mca17a) делает `importlib.reload(config.settings)` без восстановления namespace.
Reload переписывает `config.settings.Settings`/`settings` НОВЫМИ объектами, при этом все
сервисы, импортированные при коллекции pytest, держат ссылки на СТАРЫЙ класс/инстанс.
Legacy-пины ClassVar через рантайм-импорт внутри фикстуры
(`from config.settings import Settings` — конвенция F1 в test_direct_chat.py:56) после
reload патчат НОВЫЙ класс и не долетают до сервисов: гейт L1
(`services/direct_l1.py:300`, `getattr(settings, "DIRECT_L1_ENABLED", True)`) продолжал
видеть True → L1-планировщик запускался в legacy single-call путях → «l1 planner outage
— deterministic fallback», `messages[0]` становился вербализатором вместо
CHAT_SYSTEM_PROMPT → 53 порядка-зависимых RED (direct_chat 28, mca08×2, mca09,
payload_builder, tool_calling, llm_react, decision_matrix, llm_decision).

Фикс (root cause, без изменения legacy-ассертов): центральная autouse-фикстура
`_settings_module_identity_restore` в tests/conftest.py — слепок namespace
config.settings до теста, восстановление после. Нейтрализует ВСЕ reload-сайты разом;
прецедент изоляции в том же conftest (_reset_global_persona_name) и предупреждение
_system2_flags_off_by_default («патчим ClassVar на ВСЕХ Settings-классах… часть тестов
делает importlib.reload»).

Доказательство: репродьюсер [test_belief_decay + test_betterstack_handler +
test_betterstack_probe + test_direct_chat] — до фикса 28 failed / после 225 passed;
весь набор жертв (17 файлов вкл. все reload-песочницы) — 649 passed / 2 failed (ровно
два документированных pre-existing).

Гипотеза брифа про «мутирующие новые тесты F1/F2/F4/F7/F9» НЕ подтвердилась: новые
asap7-файлы чисты (проверено парой прогонов с test_direct_chat до фикса — зелёные);
поломка сидела в старом test_betterstack_handler (R10.18) и проявилась только теперь,
потому что F1 сделала DIRECT_L1_ENABLED рантайм-читаемым гейтом с рантайм-импорт-пинами.

## Изменения по группам (все с rationale)

### Группа D — миграционная цепочка v35 (8)
- tests/test_mca05_episodes_stories_round1027.py: хвост-марк реестра
  `_SCHEMA_VERSION_STORIES_MARK` v34→v35 (`_SCHEMA_VERSION_LLM_USAGE_PLAN_META`,
  F2 architecture §1.10, SQLite no-op). Конвенция волн (прецедент v32→v33→v34).
- tests/test_t5150_startup_migrations_round1046.py: a/b/d/e/e2 — итог user_version 34→35,
  pending=[33,34,35], +`migration v35 applied`, книга +строка (35, llm_usage_plan_meta_v35),
  повтор no-op. 63+7 passed.

### Release-owned свип — версия 2.58.74 (группа A + C, 18)
- 12 py-файлов пинов (hotfix6-10, f6/f7/f9/f11, polygon, design_tokens, scope_selector):
  "2.58.71"→"2.58.74" (пин факта бампа; прецедент свипов mca-12/17c/21/5).
- 4 js-харнесса (round1025_hotfix7/8/9/10): regex-пин 2\.58\.71→2\.58\.74.
- README.md: шапка v2.58.71→v2.58.74 + краткая ироничная сводка ASAP 7
  (owner-контракт «в конце внеси изменения в README»).
- round108/cachebust сравнивают с README динамически → зелёные после README.

### Группа B — UI-снапшоты/jargon (4 + санитизация)
- test_webapp_ui_rework_round1020.py: снимок навигации дополнен `mod_initiative`
  (F1 wave1: модуль «Инициатива» — легитимная дельта), счётчик модулей 14→15.
- test_webapp_nav_disclosure_ui.py: stale-пин счётчика memory-групп 3→5
  (MCA-10a +memory_random, MCA-16 +memory_experience — pre-existing red с раундов
  10.37/10.39, НЕ от волн; контракт «memory-табы покрывают все memory-группы» цел).
- test_webapp_round109_ui.py (no_forbidden_jargon): чёрный список НЕ тронут.
  Санитизированы 3 описания в services/param_catalog.py (все — от волн F2/F4):
  - limits.direct_l1_max_output_tokens: «служебного JSON-плана» → «служебного
    плана-справки (машиночитаемого)»;
  - flags.stories_vitrina_enabled: «read-API /api/stories*» → «чтение историй»;
  - flags.stories_manage_enabled: «POST /api/stories/{id}/action» → «управляющие
    действия с историей (под правами и защитой от конфликтующих правок)».
  Сопровождение: F8-переиздание TSV/meta (gen_param_registry_round1025, EMIT OK +
  CHECK OK, реестр 560/группы 120/tab 118/23 — без роста, DOC-ONLY), sha256
  param_catalog.py в tests/fixtures/round1025/f8_baseline.json обновлён осознанно
  с нотой (прецедент DOC-ONLY ASAP-4.1 [M-ASAP41-1]). pg_db.py/routes.py не менялись.

### Группа E — детерминированная часть (25)
- L1-off пины (прецедент test_direct_chat.py волны F1): tests/test_payload_builder.py,
  tests/test_direct_two_call_round1022.py, tests/test_mca08_character_speech.py,
  tests/test_mca08_style_form.py, tests/test_auto_budget_asap31.py,
  tests/test_image_generation_round1023.py — legacy-контракты single-call/2-call/
  byte-parity K1-K3/tool-list без изменения ассертов.
- tests/test_mca01_tx_task_supervisor_round1027.py: database.py 196→198 — +2 commit
  внутри `_migrate_llm_usage_plan_meta_v35` (миграционная машина F2, guarded;
  census-пин counts). Прецедент: +5 v34 asap6.
- tests/test_tool_coordinator_round1026.py + tests/test_unified_image_request_round1026.py:
  bounds-allowlist + `web/api/summary_test.py` — файл существовал с round1026 (S9) и
  до волны был байт-в-байт с baseline pre-round1026-a1; wave3 (2.58.74, REV-3 Approved)
  санкционированно расширил его → появился в diff-vs-baseline. NOTE-прецедент тех же тестов.
- tests/test_history_retention_toggle.py: whitelist settings_field_coverage +13 ClassVar
  env-осей гейтов (F1 wave1: MCA_EPISODES_*/MCA_STORIES_*/MCA_CHARACTER_*/MCA_STYLE_SCOPE/
  MCA_TRAIT_RULES/MCA_SELF_MODEL/MCA_LEGACY_TRAITS_MIGRATION/MCA_POSTPROCESS_FORM_GUARD) —
  тот же паттерн, что санкционированная F3 добавка +9 MCA_INTENT_* (env-ось AND-гейта,
  product-оси в каталоге).

### Группа F — extra_cover_style_runtime (4)
- Не env-RED и не продуктовый баг: стаб `generate_image_verbose` в тесте отстал от
  реальной сигнатуры — F7 (2.58.73, content-loss fix) добавил kwargs
  `shorter_prompt`/`attempt_log` (image_generation.py:1303); стаб падал TypeError ДО
  вызова → COVER_GENERATION_FAILED → image_calls==0. Стаб зеркалит сигнатуру; ассерты
  контракта §90/§79/§80/§81 не тронуты. 7 passed.

## Верификация
- node --check 4 харнессов: OK (финально перепроверен).
- Focused: D 70 passed, A 321 passed, B 71 passed, F8-семейство 68 passed, C 38 passed,
  L1-off-файлы 29 passed, набор жертв утечки 17 файлов 649 passed.
- Репродьюсер утечки [belief_decay+betterstack_handler+betterstack_probe+direct_chat]:
  до фикса 28 failed → после 225 passed.
- **ФИНАЛЬНЫЙ полный прогон (sync, .venv, -p no:randomly): 12889 passed / 2 failed** (9:01).

## Pre-existing (доказательства, не трогались)
- `tests/test_tool_loop.py::TestChatWithTools::test_query_chat_memory_count_reaches_model` —
  RED изолированно на чистом HEAD a1b3279 (worktree-проба
  `%TEMP%\opencode\sweepfix_head_probe`, main-venv, 2 failed in 15.94s; ассерт ожидает
  «Найдено 7 упоминаний…», фактический формат ответа инструмента «Широкий поиск
  (префиксы, не морфология): 7 сообщений…» — расхождение формата, вне скоупа свипа).
- `tests/test_direct_chat_concurrency.py::TestDirectChatConcurrency::test_third_handle_waits_for_slot_at_n2` —
  RED изолированно на чистом HEAD a1b3279 (та же worktree-проба; `assert 9 == 3` —
  счётчик вызовов, вне скоупа свипа). Прецедент: REV-2/REV-3 worktree-пробы брифа.
- Worktree-проба после доказательства удалена (--force), мусора не осталось.
