# review.md — `mca-asap2-summary-pipeline` (ASAP 2 / P0, двухконтурная Architecture Summary)

- **Дата:** 2026-09-28
- **Reviewer:** General-fallback (emergency-сессия вместо павшей Reviewer-сессии; независимый review, код/tests/config не правились)
- **Binding:** рабочее дерево поверх HEAD `e882d58ca32f0b45e049631cb1a4c0aa9b825d54` (git status: 140 M-файлов + untracked волна; scope-файлы ниже)
- **Scope tracked-diff SHA-256** (`git diff HEAD -- <35 scope-файлов>` → 452 047 bytes):
  `60E8ED874E8B7F4EEF745849FE4764781F46E139F1ACFC71ABC13E28BD5468E7`
- **Untracked scope-файлы (SHA-256):**
  | hash | file |
  |---|---|
  | 396f8316acfa1f4e0c039be3f2a1b51745796a7c673524c33319797eaab2f2d2 | services/summary_l1_repair.py |
  | 6053da01c13f1d6c5a789daff96c3fb3ddc852833586c8caff28d0c68c56c643 | services/summary_hybrid_budget.py |
  | 7536b0bb19728fcd26cc4861027e3fd844b3365600909e9672deb167a3eb426c | tests/test_summary_l1_repair_round1027.py |
  | cee7db7a94bcd69ca82ab4021a2c8ab7009191e4a291fdcb15cca2d1b08096fb | tests/test_summary_asap2_acceptance_round1027.py |
  | 451d1652affe37c0c2a0e0c05d57d53cd0705cec1edbda6a8f6cb7ba024077f4 | tests/test_summary_asap2_failsoft_round1027.py |
  | 959609e878659525da17683016b09adc54d6396d12e6c17ab805e102f7e9adfa | tests/test_summary_asap2_miniapp_round1027.py |
  | 329df971de55ef0aad09c1f479e8a492980a217b578b43607c32de7825b7007e | tests/test_summary_asap2_observability_round1027.py |
  | 5366be8b5174596369b0c0157d44f1e8d942f636dda879f1023a3a6debe2098d | tests/test_summary_asap2_l1_retry_round1027.py |
  | 03fedb677030a93c061e7c1ecbed256927728a05efd9e63f22fbcc9dcbedff49 | tests/js/round1027_asap2_summary_sections_test.js |
- **Binding-хэши источников (перепроверено `Get-FileHash`):**
  - spec.md = `C30AABC49CC3E996C7CBF072A154FCD7EA7E8C0963974F9ACEE34B30F67C12DC` ✅ совпал
  - ADR-1027-10 = `5542CCBE8A809FBF6B32E88C5CC5FE235FA38CA74EAAF2D72040E7A6EFD60DD3` ✅ совпал
  - Требования владельца: `plans/current_task.md:1884–2768` прочитаны полностью (§0–§21, 16 приёмочных тестов §17, DoD §20, антипаттерны §21), immutable — не тронуты.

## ВЕРДИКТ: **Needs Fixes (один блокующий finding — H1 changelog; фикс точечный, без изменения механики)**

Функционально фича реализована полностью и в соответствии с контрактами (a)–(n): все 13 секций проверок
зелёные, прогоны 0 failed. Блокер — **H1 (High): changelog-комментарий APP_VERSION 2.58.33 в
config/settings.py описывает SUPERSEDED partial-реализацию**, а не фактическую. Это релизная аннотация
фичи, следующим шагом идущей на прод (T-3963); misleading release notes перед прод-деплоем недопустимы.
После переформулировки одного комментария (плюс рекомендованно — Low-комментарии L1–L3) diff-хэш дерева
меняется: **обязательна повторная перевалидация прогонами H1-скоупа** (см. «Что должен исправить Builder»).

---

## Таблица проверок 1–13

| # | Проверка | Команда/rg | Факт | Вывод |
|---|---|---|---|---|
| 1 | §1/§14 MAX_SUMMARY_PARTS — только Legacy | `rg -in "max_summary_parts" services/ handlers/ config/settings.py` | В Hybrid-путях (`summary_l2_writer.py`, `summary_fact_package.py`, `summary_hybrid_budget.py`) ключ не читается — только док-строки «выведен» (l2_writer:23,66). Legacy: prompt-бюджет `max_symbols = max_parts*4000-200` (summary_generator.py:681) — backward-compat; send-кап `_cap_legacy_chunks` + WARN `LEGACY_CHUNKS_CAPPED` (163–171, 1114/1158/2259) по всем legacy-веткам доставки (2054, 2116); hybrid-plain `max_chunks=None` (1070–1080); rich-путь капом не ограничен. `resolve_l2_max_paragraphs` удалён (тест-пин `hasattr == False`, test_summary_asap_hotfix_round1027.py:61) | ✅ PASS |
| 2 | §3/§16 trim-костыль удалён | `rg -n "SUMMARY_L2_TRIM_ENABLED\|_trim_document_for_publication\|REASON_TRIMMED" services/ config/` | 0 реализаций; только «УДАЛЁН»-коммент (settings.py:1098) и тесты-защитники отсутствия (hotfix_round1027.py:82–83; tool_coordinator:663 — переписан в «не должно быть»). `paragraphs[:`/`text[:`/`blocks[:` вне тех-пределов в summary-диффе отсутствуют (`git diff … \| Select-String '^\+.*\[:'` = пусто); остались только технические: 200/900/498/32000 (l2_writer 62–68, formatter 44–47), FRAGMENT_MAX_CHARS=1000 / PER_MESSAGE_CAP=200 (pre-existing package-caps, не статья). Trim-тесты переписаны: test_summary_l2_writer.py::test_hard_cap_498_scenario вместо max_paragraphs=3 | ✅ PASS |
| 3 | §2/§10 пресеты/таргеты | чтение `summary_l2_writer.py` | `HYBRID_PRESETS` = casual (4000,5) / serious (6500,8) default / deep_research (11000,14) (75–80); max_chars default 24000 = WARN-порог: 24000<chars≤32000 → публикуем + WARN `L2_OVER_SOFT_CEILING` без обрезки (943–955); >32000 → fail-closed `too_long` в валидаторе (636) → LEVEL-3; target-блок — детерминированный append user-контента L2 «ЗАДАНИЕ ПО ДЛИНЕ И ДЕТАЛИЗАЦИИ…» (415–419), max_chars в промпт не передаётся; paragraph target — только log-поле `paragraphs_hint`, валидатором не сравнивается; тесты-пины: t3958_presets_values_locked, soft_ceiling_warn_and_publish, above_rich_hard_limit_rejected, 08/09 | ✅ PASS |
| 4 | §4/§5/§6/§15 L1-v2 + repair + correction retry | чтение `summary_l1_contract.py`, `summary_l1_repair.py`, `summary_l1_clusterizer.py:101–229, 785–917` | `SCHEMA_VERSION=2` (contract:60, валидатор ==2:361–365); many-to-many разрешён (partition-правило снято); `REASON_MESSAGE_IN_MULTIPLE_THREADS` физически удалён из кода (только «УДАЛЁН»-комменты) и его НЕТ в `_RETRYABLE_REASONS` (clusterizer:108–119 = ровно контракт (c): invalid_json/empty_response/bad_type/unknown_field/bad_schema_version/invalid_thread_id/invalid_topic/invalid_fact/l1_useless_after_repair/unknown_message_id-defense; too_many_*/транспорт не ретраящихся — тесты 239/290/300); repair вызывается МЕЖДУ parse и validate (855–858 в цикле, kill-switch OFF → 891–898 прежняя строгость); useless-формула `topics_after==0 ∨ facts_after==0 ∨ unknown/max(referenced_before,1) > 0.5` (repair.py:248–250); счётчики unknown_ids_removed/facts_removed/topics_removed (+evidence_membership_added/unassigned_conflicts_resolved/overlapping) — логируются L1_REPAIR (859–875); correction retry ≤1, вторая попытка = system + исходный user + correction-блок с текстом причины и «Do not invent message ids.» (176–229) — НЕ same-prompt (сравнение messages 1-й/2-й попытки — тест `test_correction_retry_after_invalid_json`, текст id — только в промпт, не в лог: `test_unknown_id_correction_lists_ids_in_prompt_only`) | ✅ PASS |
| 5 | §8/§9 fail-soft LEVEL-1/2/3 + матрица | чтение `summary_generator.py:755–1001`, `summary_fact_package.py:732–800` | LEVEL-2: `build_fallback_package` (0 LLM) — тема `thread_001`/`name="Общий ход обсуждения"` (FALLBACK_TOPIC_NAME:84), chronology=все ASC с `topic_ids=["thread_001"]`, fragments v2; вызывается и при L1-not-usable (876–883), и defensive при not-deliverable пакета (897–903); **L2 вызывается в любом случае** (910–914); WARN `L1_FALLBACK_PACKAGE` (fact_package:793–797); пустой payload → empty-семантика, не failure (885–892). LEVEL-3: общий `_run_legacy_pipeline` (590+), OFF-режим и fallback одним методом; гейт `flags.summary_legacy_fallback_enabled` (577–588); guard двойной публикации — флаг `published` + ранний выход `_legacy_fallback` (807–808), тест `t3959_guard_published_no_double_publication`; worst case ≤5: run_l1 ≤2 (attempt-loop) + run_l2 1 + legacy ≤2 (System2 two-call) — тест `t3959_11b_worst_case_five_generations`. Матрица 11 строк контракта (i) ↔ код: 1 OFF→legacy (522), 2 empty→не failure (464–472/885), 3 L1 dead→LEVEL-2 (876), 4 L1-slot — не реализуемо (resolve_l1_slot не бросает, fallback на main-модель; L2SlotError гасится в run_l2:873 → unusable → строка 6), 5 package not-deliverable (897), 6 L2 unusable→legacy (916–932), 7 cover fail→plain (952+/`_plain_fallback`), 8 rich fail→plain полного текста (`_deliver_l2_rich`→`_publish_rich_document` max_chunks=None), 9 plain fail→legacy (964–973), 10 exception при неопубликованном→legacy (983/998), 11 legacy мёртв → `SUMMARY_GENERATION_FAILED` (856–862, deploy-тест scenario_07b) | ✅ PASS |
| 6 | §11/§12 раздельные бюджеты + payload | чтение `summary_hybrid_budget.py` (118 строк), `summary_l1_clusterizer.py:309–466`, `summary_fact_package.py:17–22,272–374`, `summary_l2_writer.py:356–399` | Hybrid читает ТОЛЬКО `limits.summary_hybrid_context_*` (resolve_l1_budget→resolve_hybrid_context_budget clusterizer:534; fact_package:215; `_apply_filter` mode-dependent generator:1443–1466); Legacy — только `limits.summary_max_context_*` (656–665). Формула: `safe_budget − tokens(system) − markers − output_reserve(4000/6000 env ClassVar)` (hybrid_budget:77–118, settings:1128–1131); оценка — по serialized §92-JSON: `count_tokens(json.dumps(item, separators=(",",":")))` (clusterizer:311–316); margin = TOKEN_SAFETY_MULTIPLIER через `safe_budget` (~1.15, не 50%); eviction ASC `(reply_protected, −weight_S1(score_message reuse), timestamp, id)`, последнее сообщение неприкосновенно, любое вытеснение → truncated+skipped_ids+WARN (334–457). Fragments v2 несут `message_id/author_id/display_name/timestamp/reply_to_id/text`, chronology — `topic_ids[]` many-to-many; build_l2_input пробрасывает verbatim (381–399); тех-meta (chat_id/DB id/message_type/mentions) не тащится | ✅ PASS |
| 7 | §13/§14 miniapp + каталог + F8 | `python -m …; tools/gen_param_registry_round1025.py --check`; чтение app.js/param_catalog | Вкладки `hybrid: 'HYBRID SUMMARY'`, `legacy: 'LEGACY SUMMARY FALLBACK'` (app.js:616), маппинг по группам `workspaceGroupTab` (6301–6324): hybrid-группы→'hybrid', legacy-группы→'legacy'; cross-isolation тесты `t3960_cross_isolation_keys_vs_groups`/`js_workspace_sections` + node-harness OK. Подпись MAX_SUMMARY_PARTS — **verbatim** §13:2447–2449: «Максимальное число обычных Telegram-сообщений, на которые может быть разбит Legacy Summary. Не влияет на Hybrid Article.» (param_catalog:1181–1182). Счётчики: **REGISTRY 489 / GROUPS 107 / _TAB_BY_GROUP 105 / TAB_RULES 21** (python-инспекция) — ровно дельта +16/+5/+5/0; F8-CLI: `CHECK OK: реестр 489 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` (exit 0); pytest test_round1025_f8_registry.py: 29 passed | ✅ PASS |
| 8 | §18 observability | rg событий | 7 новых: `L1_PARSE` (clusterizer:839), `L1_REPAIR` (:859), `L1_CORRECTION_RETRY` (:908 WARN), `L1_FALLBACK_PACKAGE` (fact_package:797 WARN), `LEGACY_FALLBACK` (generator:811/817 WARN, поля reason∈{l1_unusable…hybrid_exception:<Class>}, calls_so_far), `LEGACY_CHUNKS_CAPPED` (generator:168), `L2_OVER_SOFT_CEILING` (l2_writer:952). Поля: FILTER_COMPLETE += messages_before/after + serialized_chars/tokens (generator:1517–1518); FACT_PACKAGE topics/messages; L2_START += response_mode/target_chars/target_paragraphs (l2_writer:747–756); L2_COMPLETE += chars, `trimmed=` удалён; SUMMARY_COMPLETE += `fallback=none/legacy` (run_log:235). Пины старых имён не переименованы (тест `t3956_existing_event_names_not_renamed`); raw-тексты/секреты в fmt-строках новых событий отсутствуют (только %d/%s кодов/чисел; unknown-id списки — только correction-промпт, тест caplog-отсутствия) | ✅ PASS |
| 9 | §17 прогоны | команды справа | **73 passed / 0 failed** (6 ASAP-2-файлов + repair + переписанный hotfix-файл, 5.2 s); **-k "summary": 1168 passed / 0 failed** (83 s); **JS: 49/49 харнессов exit 0** (включая round1027_asap2_summary_sections_test.js → `ASAP2-SUMMARY-SECTIONS-OK`); смежные каталог/промпт/табы: 160 passed (param_catalog/prompt_migrations/frontend_tab_mapping/settings_persistence/ia_smoke). 16 сценариев §17 → таблица ниже, все покрыты | ✅ PASS |
| 10 | §19 graph memory не тронут | `git diff HEAD --stat -- services/graph* services/execution_graph* services/memory_rebuild.py` + атрибуция | `services/graph*` — **0 файлов в диффе**; memory_rebuild.py — содержательная правка, но с маркерами **B-MCA01-1/ADR-1027-3 D3** (`write_transaction`) → относится к MCA-волне, не к ASAP-2; ASAP-2-маркер-скан всех 140 diff-файлов (кроме scope/tests/plans): единственный hit — README.md (docs-секция ASAP-2, легально). Граф-сценарии hotfix-файла сохранены (contract (m)) | ✅ PASS |
| 11 | KNOWN FINDING changelog | чтение config/settings.py:2182 | Подтверждено: комментарий APP_VERSION 2.58.33 описывает СТАРЫЙ partial (same-prompt «РОВНО одна повторная LLM-попытка», `_RETRYABLE_REASONS` с `message_in_multiple_threads`, «env-only kill-switch … Δ каталога=0», «промпты не меняются») — всё это НЕ соответствует факту: correction-блок после repair, `message_in_multiple_threads` удалён из набора, hot-ключи каталога, Δ каталога +16, каноны L1/L2 заменены R1027. **Severity High** | ⚠️ **HIGH — блокёр** |
| 12 | Откат SUMMARY_HYBRID_L2_ENABLED=false | код+тесты | Резолв `per-chat → hot → env` сохранён байт-в-байт (558–575), OFF → `_run_legacy_pipeline` сразу (522), worst-байт legacy-путь + send-кап; тесты: default ON пин (deploy_round1026:378), OFF kill-switch покрытие (test_summary_l2_integration/test_summary_deploy_round1026), точечные `SUMMARY_L1_REPAIR/L1_RETRY/LEGACY_FALLBACK_ENABLED=false` — retry_kill_switch_off_single_call / kill_switches_off_via_env_classvar; spec §8 «Откат» соответствует | ✅ PASS |
| 13 | Browser pass | см. секцию Browser-статус | Не независимо повторён (ограничение среды); артефакты Builder проверены просмотром + независимые structural-хаpness | ⚠️ ОГРАНИЧЕНИЕ (не finding фичи) |

---

## §17 — карта 16 приёмочных сценариев → тесты

| §17 | Сценарий | Тест (сам проверен прогоном) |
|---|---|---|
| 1 | parts=1, L2 8 абзацев → полная статья | `test_t3958_01_parts_1_hybrid_publishes_full_article` |
| 2 | parts=1, legacy >4000 → ≤1 часть + WARN | `test_t3958_02_legacy_cap_helper_dedupe_warn` (юнит) + `test_summary_publish_integration_round1026.py:994–1043` (integration legacy-cap + hybrid None) |
| 3 | message в topics A и B → VALID | `test_t3958_03_message_in_two_topics_valid` |
| 4 | reply в одной теме, смыслово в другой → VALID | `test_t3958_04_reply_one_topic_meaning_other_valid` |
| 5 | один unknown id → repair → продолжается | `test_t3958_05_single_unknown_id_repaired_pipeline_continues` + `test_single_unknown_id_repaired_no_retry` |
| 6 | overlapping topics → FactPackage строится | `test_t3958_06_overlapping_topics_package_built` |
| 7 | одна evidence через разные topics → без двойного пересказа | `test_t3958_07_shared_evidence_semantic_dedup_instruction` |
| 8 | L2 > target умеренно → не режем | `test_t3958_08_over_moderate_target_not_cut` (+`soft_ceiling_warn_and_publish`) |
| 9 | L2 < target → не ошибка | `test_t3958_09_under_target_not_error` |
| 10 | L1 мёртв → fallback-пакет → L2 | `test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback` |
| 11 | Hybrid мёртв → Legacy | `test_t3959_11_hybrid_dead_legacy_published` (+worst-case `11b`) |
| 12 | sendRichMessage fail → plain hybrid | `test_t3959_12_rich_fail_plain_full_text` |
| 13 | plain fail → Legacy chunks | `test_t3959_13_plain_dead_legacy_fallback` |
| 14 | miniapp: Hybrid отдельно | `test_t3960_14_hybrid_section_exists_and_complete` (+14b) |
| 15 | miniapp: Legacy отдельно | `test_t3960_15_legacy_section_exists_and_complete` (+15b общие вне секций) |
| 16 | подпись MAX_SUMMARY_PARTS | `test_t3960_16_max_summary_parts_signature_verbatim` (+`t3960_cross_isolation_keys_vs_groups`) |

## DoD §20 (1–16)

| # | Пункт | Статус | Evidence |
|---|---|---|---|
| 1 | MAX_SUMMARY_PARTS только legacy-семантика | ✓ | проверка 1; подпись/каталог Legacy (проверка 7) |
| 2 | Hybrid вообще не читает его | ✓ | rg (проверка 1); тесты hybrid-путей без ключа |
| 3 | У Hybrid свои настройки длины | ✓ | `limits.summary_hybrid_*` (f)/(g), settings 1102–1124 |
| 4 | Статья не режется алгоритмически | ✓ | проверка 2; hard-пределы 498/32000/900/200 остались (это не trim) |
| 5 | Длина — soft target в storyteller | ✓ | length-блок l2_writer:415; §10 формулировки в каноне R1027 |
| 6 | message в нескольких topics | ✓ | threads-v2, overlap=норма (+repair счётчик) |
| 7 | message_in_multiple_threads не ошибка | ✓ | удалён из кода/ретраев; тесты 3/4 |
| 8 | Minor L1-несостыковка — локальный repair | ✓ | summary_l1_repair.py контракт (b) |
| 9 | Hybrid — настоящий fallback path | ✓ | LEVEL-2/3 + матрица (проверка 5) |
| 10 | Legacy — рабочий fallback | ✓ | `_run_legacy_pipeline` общий OFF/LEVEL-3; тесты 11/13 |
| 11 | Miniapp разделён | ✓ | вкладки hybrid/legacy (проверка 7), S1/S3-скрины |
| 12 | Regression-тесты инвариантов | ✓ | §17-карта, 73+1168+JS49 0 failed |
| 13 | Реалистичный чат: полная связная статья | частично (код✓/тесты✓, прод-верификация T-3963 post-deploy по §18-логам) |
| 14 | Обложка + sendRichMessage | код✓ (`_deliver_l2_rich`, cover fallback на LEVEL-2), прод-верификация T-3963 |
| 15 | Сбой rich → plain | ✓ тест 12 |
| 16 | Полный сбой Hybrid → Legacy | ✓ тесты 11/13 |

## Прогоны Reviewer (счётчики)

| Прогон | Результат |
|---|---|
| `python -m pytest tests/test_summary_l1_repair_round1027.py tests/test_summary_asap2_{acceptance,failsoft,miniapp,observability,l1_retry}_round1027.py tests/test_summary_asap_hotfix_round1027.py -q` | **73 passed / 0 failed** (5.23 s) |
| `python -m pytest -k "summary" -q` | **1168 passed / 0 failed / 8745 deselected** (83.09 s) |
| `node tests/js/round1027_asap2_summary_sections_test.js` | exit 0 `ASAP2-SUMMARY-SECTIONS-OK` |
| все 49 `tests/js/*.js` | **49 OK / 0 fail** |
| `python tools/gen_param_registry_round1025.py --check` | exit 0 «реестр 489, карта полна, R17-чисто, TSV/map идемпотентны» |
| `python -m pytest tests/test_round1025_f8_registry.py -q` | 29 passed |
| `python -m pytest tests/test_param_catalog.py tests/test_prompt_migrations.py tests/test_frontend_tab_mapping.py tests/test_settings_persistence_round1014.py tests/test_round106_ia_smoke.py -q` | 160 passed |
| Полный baseline 9913/0 (evidence T-3961) | Reviewer НЕ перепрогонял полностью; independent-срезы выше — 0 failed |

## Вердикт по BOM/CRLF-выборке (побочные правки чужих файлов)

Заявка handoff («~50 чужих файлов — только BOM/CRLF-нормализация») **не подтверждается как описана**:
byte-level скан всех 140 modified tracked-файлов (`git show HEAD:f` vs worktree после снятия BOM/CR):
**EOL/BOM-only файлов — 0**; все 140 имеют содержательные диффы. НО: атрибуция сканом ASAP-2-маркеров
(`ASAP-?2|asap2|summary_hybrid|l1_repair|hybrid_budget|LEGACY_CHUNKS_CAPPED|build_fallback_package|…`)
показала **ноль ASAP-2-правок в чужих файлах**: содержательные диффы чужих файлов принадлежат
параллельной незакоммиченной MCA-волне round1027 (маркеры `MCA-01/B-MCA01-1/MCA-03/MCA-07/safe_fetch/
write_transaction/task_supervisor` в diff'ах; `handlers/summary.py` — чисто MCA-03, `web/index.html` —
MCA-17a/shell-волна). Spec §1 прямо предписывает MCA-волну не трогать и не включать в эту фичу.
**Critical нет** (ASAP-2 чужие файлы не правил), но **Medium M1** за ложную заявку и **M2** —
scope-лист handoff включает `handlers/summary.py`/`web/index.html`, где у ASAP-2 дифф пуст: feat-коммит
(T-3963/Q8) обязан стейджить строго ASAP-2-скоуп и не затянуть MCA-волну.

## Findings

### Critical
— нет.

### High
- **H1. `config/settings.py:2182` — changelog APP_VERSION 2.58.33 описывает SUPERSEDED partial, а не фактическую реализацию.**
  Текст: «run_l1 — РОВНО одна повторная LLM-попытка при невалидном ответе … `_RETRYABLE_REASONS`:
  …/message_in_multiple_threads; env-only kill-switch SUMMARY_L1_RETRY_ENABLED (default ON, Δ каталога=0)…
  промпты не меняются. Откат: env SUMMARY_L1_RETRY_ENABLED=false».
  Факт (проверено): retry — **correction** после deterministic repair (clusterizer:785–917),
  `message_in_multiple_threads` **удалён** из набора (:108–119), kill-switch'и стали **hot-ключами каталога**
  (`flags.summary_hybrid_l1_repair_enabled/_retry_enabled/summary_legacy_fallback_enabled`), **Δ каталога=+16**,
  каноны L1/L2 заменены на R1027 с PREV_*/ROLLBACK, добавлены `limits.summary_hybrid_*`, удалён
  `SUMMARY_L2_TRIM_ENABLED` (сам пункт 2.58.32 в комменте тоже описывает уже удалённыйtrim как действующий
  механизм с `trimmed_for_publication`/`paragraphs_before/kept/dropped` — этих маркеров в коде больше нет).
  **Репродукция:** открыть строку; сравнить с rg-фактами выше. **Что требуется:** переписать ASAP-2-хунку
  комментария 2.58.33 по фактической реализации (repair→correction retry, +16 каталога, новые hot/env-ключи,
  удаление trim-костыля, откат `SUMMARY_HYBRID_L2_ENABLED=false`), историю 2.58.32 оставить как прошлую
  версию с пометкой «SUPERSEDED в 2.58.33 (trim удалён §16)». Только комментарий, механику не трогать.

### Medium
- **M1.** Handoff/evidence-заявка «~50 чужих файлов — BOM/CRLF-нормализация» не соответствует дереву
  (0 EOL-only файлов; чужие диффы = MCA-волна). Исправить формулировку в evidence.md, иначе следующий
  релизный цикл будет стейджить по неверному признаку.
- **M2.** `handlers/summary.py` и `web/index.html` в scope-перечне handoff не содержат ASAP-2-изменений
  (MCA-03/MCA-17a). При feat-коммите T-3963 их стейджить в этот коммит нельзя.

### Low
- **L1.** `services/summary_l1_contract.py:361` — комментарий «строго int == 1» при коде `!= SCHEMA_VERSION` (=2). Ретросправка, не логика.
- **L2.** `services/summary_l1_clusterizer.py:686` (докстрока run_l1: «budget=None → `limits.summary_max_context_*`») и `:89` (тот же stale-коммент) — фактически hybrid-ключи (:528–535). Устаревшие док-строки.
- **L3.** `config/settings.py:1099` — остаточная ссылка-коммент на `limits.max_summary_parts` в ASAP-2 блоке допустима как историч. справка, но лучше согласовать с H1-переписыванием за одним проходом.

## Browser-статус

**BROWSER PASS NOT INDEPENDENTLY REPEATED** — ограничение среды: локальный PostgreSQL недоступен
(port 5432 closed), dev-запуск miniapp требует auth-контур (подписанный Telegram initData из тестового
механизма — воспроизведение ровно Builder-стека, не независимая проверка). Опора: (1) Builder Playwright-артефакты,
которые Reviewer **лично инспектировал как изображения**: `tools/asap2_s1_hybrid_desktop.png`
(вкладки HYBRID SUMMARY / LEGACY SUMMARY FALLBACK отдельно, human-readable описания, маскированные
api-ключи) и `tools/asap2_s3_legacy_desktop.png` (LEGACY-секция: fallback-флаг, MAX_SUMMARY_PARTS=6 с
дословной подписью «Не влияет на Hybrid Article», hybrid-ключей в секции нет; хэши PNG зафиксированы:
S1 `1B212715539867BA…08401B1E3`, S3 `5C1DBED020F916F4…1699A4BE`); (2) собственные прогоны Reviewer:
`node tests/js/round1027_asap2_summary_sections_test.js` + 49 JS-харнессов (0 fail) и
`tests/test_summary_asap2_miniapp_round1027.py` (§17.14–16 + cross-isolation). S2/S4/S6/S7 структурно
покрыты этими harness'ами; живый интерактив S5 (save→POST→reload) — не повторён.

## Что должен исправить Builder (для перехода к Approved)

1. **H1** — переписать changelog-комментарий APP_VERSION 2.58.33 в `config/settings.py:2182` под
   фактическую реализацию ASAP-2 (correction-retry-после-repair; удаление `message_in_multiple_threads`
   из retry-набора; hot-ключи Recovery; Δ каталога +16; удаление trim-костыля 2.58.32; корректная ветка
   отката). Комментарий-only правка; механика/tests не меняются.
2. (Рекомендовано в том же проходе) L1–L3 stale-комменты.
3. После фикса — переподать binding: новый scope-diff SHA-256 + перепрогон `pytest
   tests/test_summary_asap2_* tests/test_summary_l1_repair_round1027.py tests/test_summary_asap_hotfix_round1027.py -q`
   и `node tests/js/round1027_asap2_summary_sections_test.js` (ожидание: 73 passed, JS OK — правка
   комментария не должна менять счётчики).
4. Для T-3963: стейдж feat-коммита строго по ASAP-2-скоупу (M1/M2): не включать `handlers/summary.py`,
   `web/index.html`, MCA-волну; changelog-правки README/plans — отдельный docs-коммит (Q8).

*Review не изменял ни один файл, кроме создания этого `plans/features/mca-asap2-summary-pipeline/review.md.
Временные helper-скрипты аудита (`_review_tmp_*.py`) удалены, дерево не изменено (git status совпадает).*

---

# РАУНД 2 (2026-09-28, ревалидация rework по finding-ам раунда 1)

- **Feature-ID:** `mca-asap2-summary-pipeline` · **Risk-Level:** R2 (из раунда 1, не пересматривался)
- **Status: Approved**
- **Git base:** HEAD `e882d58ca32f0b45e049631cb1a4c0aa9b825d54` (не изменился)
- **Новый Binding (актуальный; раунд-1 binding `60E8ED87…BD5468E7` настоящим заменяется):**
  - **Scope tracked-diff SHA-256 (канонический 35-файловый список, `git diff HEAD -- <список>` → 463 919 bytes):**
    `D0A5E27CB61D60CA088882D65E5A8EA324EE6CA06FD2B6183C85735399E64918` — **сам пересчитан Reviewer, побайтово совпал с заявкой Builder.**
  - **Untracked scope (9 файлов):** хэши сверены `Get-FileHash`-подобной sha256-инспекцией — **все 9 совпадают с таблицей раунда 1, не изменялись** (summary_l1_repair, summary_hybrid_budget, 6 ASAP-2/repair pytest-файлов, round1027 JS-харнесс).
  - **Working-Tree-Hash (раунд 2):** детерминированный манифест = SHA-256 выше (tracked-дельт 35) ⊕ конкатенация 9 untracked-хэшей таблицы раунда 1 ⊕ HEAD `e882d58`.
- **Spec-Hash:** `C30AABC49CC3E996C7CBF072A154FCD7EA7E8C0963974F9ACEE34B30F67C12DC` — перепроверен, **не изменился** ✅
- **ADR-1027-10:** `5542CCBE8A809FBF6B32E88C5CC5FE235FA38CA74EAAF2D72040E7A6EFD60DD3` — не изменился ✅

## Канонический поимённый 35-файловый список scope tracked-diff (для раунда 3 и DevOps; из evidence.md «Rework review-раунда 1», подтверждён Reviewer пересчётом):

```
services/summary_l1_contract.py, services/summary_l1_clusterizer.py,
services/summary_l2_writer.py, services/summary_fact_package.py,
services/summary_generator.py, services/summary_prompts.py,
services/prompt_migrations.py, services/summary_run_log.py,
services/param_catalog.py, services/summary_article_formatter.py,
config/settings.py, web/app.js, plans/docs/canon/architecture.md,
plans/docs/param-registry-round1025.tsv,
plans/docs/param-registry-round1025.meta.md,
plans/docs/screen-map-round1025.md,
tests/fixtures/round1025/f8_baseline.json,
tests/fixtures/round1025/catalog_baseline.json,
tests/js/round1025_f5_workspace_route_test.js,
tests/test_summary_asap_hotfix_round1027.py, tests/test_summary_l1_clusterizer.py,
tests/test_summary_l2_writer.py, tests/test_summary_fact_package.py,
tests/test_summary_publish_integration_round1026.py,
tests/test_summary_deploy_round1026.py, tests/test_summary_logging_runid.py,
tests/test_summary_l2_integration.py, tests/test_summary_filter_integration.py,
tests/test_summary_test_run.py, tests/test_summary_test_api.py,
tests/test_tool_coordinator_round1026.py, tests/test_frontend_tab_mapping.py,
tests/test_param_catalog.py, tests/test_prompt_migrations.py,
tests/test_round1025_f8_registry.py
```
Примечание по байтовому расхождению раунда 1: старый `60E8ED87` (452 047 B) считался по другому составу перечня; каноническим отныне считается список выше (заявка Builder 457 110 B pre-rework → 463 919 B post-rework; Δ = правки комментариев в 3 файлах).

## 4. ГЛАВНОЕ — дельт между раундом 1 и текущим деревом = comment/doc-only (доказательство)

1. **Изоляция дельт по mtime всего дерева:** файлы, изменённые позже round-1 `review.md` (15:11:10): `config/settings.py` (16:18), `services/summary_l1_clusterizer.py` (16:17), `services/summary_l1_contract.py` (16:13) + только документация (`evidence.md`, `workflow_state.md`) и артефакты (`__pycache__/*.pyc`, `.pytest_cache`). Иные scope-файлы (32 из 35, включая `web/app.js` 13:08) — **не трогались**; 9 untracked — хэши не изменились.
2. **Классификация изменённых хунков** (`git diff HEAD` по 3 файлам, скриптовый разбор +/- строк по хукам, где находятся rework-метки):
   - `summary_l1_contract.py` hunk `@@ -334,7 +358,8` — +2/−1, **0 исполняемых** (коммент 361–362 переписан «== 1» → «== SCHEMA_VERSION (v2: ровно 2)»; валидатор 363–366 байт-в-байтово прежний, сдвиг +1 ровно по +1 строке комментария).
   - `summary_l1_clusterizer.py` hunk `@@ -66,8 +86,13` — +7/−2, **0 исполняемых** (док-блок бюджета 89–95; константы `L1_CONTEXT_TOKEN_DEFAULT = 30000`/`CHARS_ENV` на 96–97 сохранены). Сдвиг `_RETRYABLE_REASONS` 108→113 = ровно +5 net-прироста этого блока; состав набора (10 причин, без `message_in_multiple_threads`, с `l1_useless_after_repair` + defense `unknown_message_id`) идентичен раунду 1. Docstring run_l1 (687–708) — сдвиг тел run_l1-фрагментов (repair 855→866) ровно по приросту docstring; исполняемая механика call→parse→repair→validate→correction-retry подтверждена чтением 842–936 без изменений против раунда 1.
   - `config/settings.py` — changelog-хунка 2182→2184 (+2 ровно по вставленным L3-комментам 1100–1102); **исполняемая часть `APP_VERSION = "2.58.33"` неизменна**; `SUMMARY_L2_TRIM_ENABLED` в коде отсутствует (только в комментах :1098 и исторической хунке).
   - `git diff -w` sanity: contract 90/90 (все различия — контент коммент-строк), settings 274/274, clusterizer −72 строк в -w-срезе — это continuation-пробелы старых ASAP-2-строк против HEAD, не исполняемые семантические различия.
3. **Поведенческое подтверждение:** идентичные раунду 1 счётчики прогонов (73/0, 1168/0, registry OK, JS OK) — ни один тест-пин не сдвинулся.

**Вывод: дельт раунда 1 → раунд 2 содержит ноль добавленных/удалённых/изменённых исполняемых строк; только # комментарии, docstring-строки и переформулировка release-note-комментария.**

## 1. H1 — changelog `config/settings.py:2184` (переписан под фактический билд)

Проверено наличие в ASAP-2-хунке **всех** обязательных тезисов и соответствие коду: correction retry ≤1 строго после deterministic repair (`summary_l1_repair.py` между parse/validate; uselessness-формула `topics_after==0 ∨ facts_after==0 ∨ unknown/max(referenced,1)>0.5`; reason `l1_useless_after_repair`) ✅; threads-v2 `schema_version: 2` many-to-many ✅; `message_in_multiple_threads` УДАЛЁН из фатальных И из retryable ✅ (в коде не встречается — rg 0 hits); trim 2.58.32 УДАЛЁН (§16) ✅; `max_summary_parts` строго Legacy (prompt-бюджет parts×4000−200 + send-кап + WARN `LEGACY_CHUNKS_CAPPED`) ✅; пресеты 4000/6500/11000, 24000=WARN без обрезки, >32000 too_long→Legacy ✅; fail-soft LEVEL-1/2/3, общий `_run_legacy_pipeline`, published-guard, ≤5 генераций (ADR-1027-10 D3, AMEND ADR-1026-7 D5) ✅; Δ каталога +16 hot-ключей/+5 групп, F8 переиздан 489/430/464/107/105/21 ✅ (инспекция `param_catalog`: REGISTRY 489, settings_field 430, categorized 464, GROUPS 107, _TAB_BY_GROUP 105, TAB_RULES 21 — ровно дельт +16/+5/+5/0 от A7-базиса 473/430/448/102/100/21); каноны R1027 PREV_*/ROLLBACK и явное «**ПРОМПТЫ ИЗМЕНЕНЫ (не «не меняются»)**» ✅ (требование «не утверждать «не меняются»» исполнено); Recovery hot-ключи + env-слой ✅; откат `SUMMARY_HYBRID_L2_ENABLED=false` + точечные env kill-switch'и + cold revert ✅; Δ DDL=0, Δ зависимостей=0, R17/R18-safe ✅; GraphRAG не тронут ✅.
**Stale-утверждения old-partial:** «РОВНО одна повторная LLM-попытка» — 0 hits; old-набор retryable — отсутствует; «Δ каталога=0» и «промпты не меняются» остались ТОЛЬКО в исторических хунках 2.58.32/Эпика (вне ASAP-2-секции, позиция 5339/6827 > конца 2.58.33-секции 4544) — легальная история. Хунка 2.58.32 сохранена с маркером «**ИСТОРИЧ: SUPERSEDED в 2.58.33, trim-костыль удалён §16**» (позиция 4641) ✅. Формулировки «same-prompt»/«trimmed_for_publication» внутри 2.58.33-секции присутствуют исключительно как описания ОТВЕРГНУТОГО подхода и УДАЛЁНного механизма — не stale-притязания.

## 2. L1–L3 stale-комменты — исправлены

- `services/summary_l1_contract.py:361–362` — «== SCHEMA_VERSION (v2: ровно 2)» ✅
- `services/summary_l1_clusterizer.py:89–97` (hybrid-резолв вместо stale legacy-ссылки) и `:689–696` (run_l1 docstring: hybrid-ключи через `resolve_hybrid_context_budget`) ✅
- `config/settings.py:1100–1102` — `limits.max_summary_parts` «НЕ наследуется… строго Legacy-контуру», согласовано с H1 ✅

## 3. M1/M2 — закрыты в evidence.md

- M1: раздел «Rework review-раунда 1» (evidence.md:469–479) — ложная BOM/CRLF-заявка скорректирована: «EOL/BOM-only — 0; чужие диффы = параллельная MCA-волна round1027» ✅
- M2: там же (:480–486) — зафиксирован do-not-stage список (`handlers/summary.py` MCA-03, `web/index.html` MCA-17a + `services/mca_*`, `database.py`, `summary_memory.py`, `bot.py`, `tools/history_import/*`); повторная проверка ASAP-2-маркеров в diff этих двух файлов — **0 hits** ✅

## Прогоны раунда 2 (Reviewer, собственный пересчёт)

| Прогон | Результат |
|---|---|
| `python -m pytest tests/test_summary_l1_repair_round1027.py tests/test_summary_asap2_{acceptance,failsoft,miniapp,observability,l1_retry}_round1027.py tests/test_summary_asap_hotfix_round1027.py -q` | **73 passed / 0 failed** (5.14 s) |
| `python -m pytest -k "summary" -q` | **1168 passed / 0 failed / 8745 deselected** (81.16 s; первый запуск прерван таймаутом среды на 98%, чистый повтор — все зелёные) |
| `python tools/gen_param_registry_round1025.py --check` | exit **0** — «реестр 489 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны» |
| `node tests/js/round1027_asap2_summary_sections_test.js` | exit **0** — `ASAP2-SUMMARY-SECTIONS-OK` |

## Browser-статус раунда 2

UI-файлы (`web/app.js` 13:08 и весь `web/`) с момента round-1 review **не изменялись** (mtime-изоляция п.4.1; tracked-diff `web/app.js` входит в неизменный хэш-состав). Дельт rework — только Python-комменты. Браузерная ревалидация в дельте **не требовалась**; ограничение раунда 1 (PG-5432 недоступен, live S5 save→POST→reload не повторён независимо) **не ухудшилось**.

## Вердикт и debt

**Status: Approved** — H1 закрыт точечно и фактологически, L1–L3/M1/M2 закрыты, дельт доказан как comment/doc-only, механика/тесты/config-значения не менялись, оба обязательных среза (requirements-лэнс раунда 1 остаётся в силе — скоуп-дельт его не касался; focused change-audit дельты — выше) поддержаны независимо.

Non-blocking debt (переносится из раунда 1, блокерами не являются):
- D-1: live S5-интерактив miniapp — верификация post-deploy по §18-логам (T-3963);
- D-2: DoD 13/14 (реалистичный чат, обложка) — прод-верификация T-3963;
- D-3 (Low, документационный): в `evidence.md` «Прогоны после rework-раунда 1» — плейсхолдеры «(см. отчёт Builder: ожидание…)» вместо фактических цифр; значения подтверждены независимым прогоном Reviewer (73/0, 1168/0, exit 0) — рекомендуется DevOps/Orchestrator вклеить фактические счётчики при docs-коммите.

## Staging-guidance для DevOps (T-3963)

- **ASAP-2 feat-коммит = строго 35 scope-файлов канонического списка выше + 9 untracked-файлов таблицы** (services/summary_l1_repair.py, services/summary_hybrid_budget.py, tests/test_summary_l1_repair_round1027.py, tests/test_summary_asap2_acceptance/failsoft/miniapp/observability/l1_retry_round1027.py, tests/js/round1027_asap2_summary_sections_test.js).
- **НЕ стейджить** в этот коммит: `handlers/summary.py`, `web/index.html` (чистые MCA-правки), остальные ~190 изменённых файлов MCA-волны round1027 — их собственная судьба/коммиты, вне этого feat-коммита.
- **Docs-коммит отдельно**: README, `plans/reports/*`, `plans/features/*`, `workflow_state.md` (Q8). ВНИМАНИЕ: 8 файлов в feat-скоммите — тест-закреплённые артефакты (registry TSV/meta, screen-map, f8/catalog baseline JSON, canon/architecture.md, JS-харнесс f5) — их выносить в docs-коммит НЕЛЬЗЯ: `--check`, `test_round1025_f8_registry` и pinned-канон-тесты ходят именно в них; коммит без них красный.
- **Сверка биндинга перед коммитом:** пересчитать scope tracked-diff SHA-256 по каноническому списку — обязан дать `D0A5E27CB61D60CA088882D65E5A8EA324EE6CA06FD2B6183C85735399E64918` (463 919 B) на дереве поверх `e882d58`; любое расхождение = ревью протухло, новый раунд.

*Раунд 2 не изменял ни одного файла, кроме дописывания этого `review.md`. Временный helper `_rev2_tmp_probe.py` удалён; git status/дерево не изменены.*
