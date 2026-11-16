# MOD-ACL-UX-01 M2.1 — per-chat adapters для 12 модулей

**Статус:** реализация + тесты; кандидат на независимое ревью. `VERIFIED` не
заявляется, деплой не выполнялся.

**База:** `bca18c1e` (2.58.205, schema 47). **Ветка:**
`acl/m2.1-perchat-adapters`. **Code commit:** `def84275` (25 files,
+1115/−69; evidence-коммит поверх него). **Требования среза:**
`MAC-AC-04`, `MAC-S2-TT-5`, `MAC-S10-01`, `MAC-S15-12`,
`MAC-S2-SHARED-01`; consumer-proof для `MAC-S0-01`, `MAC-S2-TT-4`,
`MAC-S2-91`, `MAC-S2-116`, `MAC-AC-02`.

## 1. Что изменено по модулям

| # | Модуль | Ключ / домен | Фактическая ветка потребления | Изменение |
|---|---|---|---|---|
| 1 | initiative | `flags.initiative_enabled` + `flags.initiative_observer_enabled` + `chat_params.overrides["initiative.enabled"]` | `observe_tick`, `_scan_phase`, `initiative_publish_block_reason`, `random_trigger` | master-AND уже был; добавлен per-chat random-usage gate и поведенческие тесты |
| 2 | direct | `flags.direct_chat_botword_enabled` | `handlers/direct_chat.py::direct_chat_handler`, `_is_direct_trigger`, functional yield | канонический резолвер на входе; триггер вынесен в `_is_direct_trigger_unscoped` |
| 3 | factcheck | `flags.factcheck_enabled` | `handlers/factcheck.py::factcheck_handler` | `feature_gates.module_enabled` вместо глобального `hot.get` |
| 4 | search | `flags.search_enabled` | `handlers/search.py`, `services/direct_chat_service.py::_evidence_context/_l1_tool_subset` | резолвер в handler и в обоих decision-путях Direct |
| 5 | web | `flags.webpage_enabled` | `handlers/web.py`, `services/direct_chat_service.py` | то же |
| 6 | transcribe | `flags.enable_voice_transcription` | `handlers/voice_transcription.py::voice_transcription_handler` | резолвер вместо глобального `hot.get` |
| 7 | video_summary | `flags.video_summary_enabled` | `handlers/youtube.py::_dispatch_video_request` (только summary-ветки) | резолвер; transcribe-ветки не затронуты |
| 8 | media_download | `flags.download_enabled` | `services/media_download.py::module_enabled`, `handlers/video_download.py`, `tool_router._download_media` | per-chat гейт; общий транспорт `fetch_media_to_tmp` не останавливается |
| 9 | checkup | `flags.checkup_enabled` | `handlers/checkup.py`, `tool_router._get_bot_health` | резолвер в handler и tool-пути |
| 10 | stories | `flags.stories_vitrina_enabled` | `web/api/stories.py` (4 read-endpoint) | per-chat адаптер `stories_vitrina_enabled_for_chat`; manage-контур не менялся |
| 11 | character | `flags.self_model_enabled` | `bot_persona.resolve_character_context`, `mca_self_model.resolve_self_model` | master-AND с глобальной моделью; чат только отключает использование |
| 12 | random | `memory.random_enabled` | `mca_exploration.exploration_allowed`, `initiative_observer.random_trigger` | master-AND с глобальным пулом; чат не обходит выключенный пул |

Дополнительно `nostalgia` (вне 12, требование §12.3):
`MASTER_FALLBACK_KEYS["nostalgia"] = "memory.nostalgia_enabled"` и
master-first порядок в `_global_flag_sourced`; legacy
`flags.nostalgia_enabled` больше не перекрывает master.

## 2. Семантика GLOBAL/CHAT

Реализована каноническая семантика **GLOBAL default → CHAT override**
(owner input §2, строки 16/76–77; design §4.6/§12.2; `MAC-S2-TT-4`):

| GLOBAL | CHAT | Результат для 8 handler/tool-модулей |
|---|---|---|
| ON | INHERIT | ON (global) |
| ON | OFF | OFF |
| OFF | INHERIT | OFF |
| OFF | ON | ON (только этот чат) |

**Расхождение с формулировкой dispatch.** В постановке M2.1 строка
«GLOBAL OFF + CHAT ON → runtime выключен» названа master-AND. Это
противоречит нормативному owner input §2 («Глобальный переключатель =
наследуемое значение по умолчанию… НЕЛЬЗЯ писать
`effective = global_master AND chat_enabled` для пользовательских модулей»),
design §12.2 (для этих 8 модулей — читать через `resolve_param_capability`)
и уже VERIFIED `MAC-S2-TT-4`. Реализована owner-семантика; глобальный
master-AND сохранён только там, где глобальная ось — отдельный shared
product (initiative, character, random), а не default пользовательской
карточки. Это записано как ограничение/вопрос к Reviewer, а не скрыто.

## 3. Файлы и объём

Код и тесты (23 файла, +323/−69 по `git diff --stat` на базе `bca18c1e`):

- `handlers/`: `direct_chat.py` (+62/−13), `factcheck.py` (+7/−2),
  `search.py` (+7/−2), `web.py` (+7/−2), `voice_transcription.py` (+10/−3),
  `youtube.py` (+7/−2), `checkup.py` (+7/−2), `video_download.py` (+15/−3).
- `services/`: `feature_gates.py` (+57/−6), `mca_gates.py` (+56),
  `initiative_observer.py` (+15/−1), `direct_chat_service.py` (+17/−8),
  `media_download.py` (+17), `tool_router.py` (+12/−3),
  `bot_persona.py` (+4/−2), `mca_self_model.py` (+2/−2),
  `mca_exploration.py` (+1/−1).
- `web/api/stories.py` (+10/−8).
- Новые тесты: `tests/test_mod_acl_ux_01_m21_adapters.py` (513 строк),
  `tests/test_mod_acl_ux_01_m21_gates.py` (269 строк).
- Обновлены 5 существующих структурных тестов, которые закрепляли старый
  глобальный `hot.get`-паттерн: `tests/test_asap8_f5_module_truth.py`,
  `tests/test_asap8_v63_b07_temporal_factcheck.py`,
  `tests/test_smoke_round1016_fixes.py`,
  `tests/test_mca12_stories_round1046.py`,
  `tests/test_asap8_f7_stories.py`. Ослабления нет: проверки переведены на
  новые ключи/адаптеры и сохраняют прежний смысл (свой гейт, отсутствие
  Summary-зависимости, disabled-состояние).

**Файлы вне исходного write scope (обоснование):**
`services/bot_persona.py` и `services/mca_self_model.py` — фактические
read/usage-ветки характера с `chat_id`; `services/mca_exploration.py` —
фактическая random-usage-ветка с `chat_id`; `web/api/stories.py` — read-API
историй с `chat_id`; перечисленные 5 тестов — их структурные ожидания
описывали отменяемый глобальный паттерн. `module_registry.py`,
`permissions.py`, `access.py`, prompt registry, VMQ QRNG, `cognitive_map.py`,
`config_cache.py`, `param_catalog.py` не изменялись.

## 4. Проверки

- **RED на базе `bca18c1e`:** только новые тесты скопированы в чистый
  checkout базы → **31 failed / 5 passed** (`pytest-red-base.txt`).
- **GREEN на кандидате:** 24 focused-файла, включая оба новых,
  M2/ACL, handler-тесты, stories/character/random/initiative, структурные
  тесты → **465 passed, 0 failed** (`pytest-green.txt`,
  `pytest-green.xml`, `tests-summary.json`).
- **Мутации:** 3/3 killed (`mutations.txt`, `mutations.json`):
  снятие initiative master-AND, возврат глобального `hot.get` в search,
  снятие nostalgia precedence.
- **Конфигурация:** DDL 0, миграций нет, новых флагов/hot-config/таблиц
  нет; stored values и промпты не переписываются (тест
  `test_adapter_does_not_rewrite_stored_values`).
- **Второй ACL/registry/resolver:** отсутствует; тест
  `test_no_second_resolver_or_acl`; `module_registry` используется только
  на чтение через существующий `resolve_module_capability`.

## 5. Известные ограничения

1. **Live production probe не выполнялся** (деплой не входит в задачу;
   кандидат не задеплоен). Consumer-proof — тесты на фактических ветках,
   не production-наблюдение.
2. **Pre-existing failures базы** (не связаны с M2.1, воспроизведены на
   `bca18c1e`): `test_anticliche_sources_ac_data::test_fresh_skip_reports_real_rule_count`,
   `test_initiative_coordination::test_act_on_opportunity_conflict_defers_to_intent`,
   `test_initiative_coordination::test_evaluate_phase_precheck_blocks_before_llm`,
   `test_initiative_coordination::test_t1_nostalgia_delegated_refusal_sends_nothing`,
   `test_initiative_coordination::test_t5_every_text_send_site_passes_publish_guard`,
   `test_soul1_w5_observer_gates::test_initiative_writer_shares_core_style_and_persona`,
   `test_addtr_tools_minifix::test_l1_seam_announce_then_execute_once`.
3. **`stories` manage-контур** (`stories_manage_enabled`) остаётся
   глобальным: M2.1 закрывает только read-контур, как и записано в
   постановке; mutation-контур — вне среза.
4. **Random shared pool**: чат OFF останавливает использование у себя
   (exploration/initiative draw), но не ANU/refill/другие чаты. Глобальный
   master остаётся AND-осью; это осознанно, не «второй master».
5. **Dispatch vs owner**: см. §2; если Reviewer считает буквальную
   master-AND-формулировку dispatch обязательной для 8 модулей, это
   изменение контракта, а не дефект реализации, и требует отдельного
   решения (owner input прямо запрещает такую формулу).

## 6. Артефакты

- `evidence/m21/pytest-red-base.txt` — RED базы.
- `evidence/m21/pytest-green.txt` / `.xml` — GREEN кандидата.
- `evidence/m21/tests-summary.json` — машиночитаемая сводка.
- `evidence/m21/mutations.txt` / `mutations.json` — мутации.
- `evidence/m21/implementation.md` — этот файл.
