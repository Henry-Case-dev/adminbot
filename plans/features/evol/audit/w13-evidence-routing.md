# W13 — Runtime evidence policy (P0): отчёт полосы Builder

Фича: `ASAP-EVIDENCE-ROUTING-01` v3 (§1, §2.1, §2.3, поправки C1–C4).
Замороженный контракт: `plans/features/evol/arch/evidence-routing-contract.md`.
База ветки: `evol/impl` @ `57081925` (prod 2.58.145 @ `4bf3604a`).
Режим: только правки файлов и `pytest`; никаких `git reset/checkout/stash/clean/restore` и коммитов. Рабочее дерево содержит также незакоммиченные правки соседней полосы (окно/reuse: `tool_router.py`, `web_content_extractor.py`, `source_reuse.py`, `auto_budget.py`, `model_capacity.py`) — они не мои и не изменялись.

## 1. Что реализовано

### 1.1. Новый чистый модуль `services/evidence_policy.py`

Один вход → один выход, без LLM/БД/сети/I/O:

| Элемент | Содержание |
| --- | --- |
| `ClaimKey` | канон `sha1(entity\|relation\|version\|date\|metric)[:16]`; поля нормализуются существующим `claim_envelope.normalize_proposition`, relation — закрытый набор из 7 |
| `EvidenceDecision` | `required`, `evidence_class`, `claims`, `source_kind`, `skip_reason`, `explicit_request`, `note` + аддитивные `required_caps`, `failure_code`, `required_unmet`, `blocked`; `event_fields()` даёт R17-safe полезную нагрузку события |
| `evaluate_evidence_need(plan, task_kind, explicit, supplied, runtime_state, context=None)` | правила §1.2 в порядке контракта (1→8), reuse (9), `allowed()` (10) |
| `allowed(capability, ctx)` | единственная точка разрешения: RBAC → запрет сети → реальная доступность провайдера/ключа → стоимость/квота → SSRF → privacy |
| `effective_capabilities(l1_requested, runtime_required, ctx)` | `allowed(union)`, отказы с кодом (не молчаливое удаление) |
| `EvidenceSkipReason` (12) / `EvidenceFailureCode` (8) | конвертация в существующие `mca_events.REASON_CODES` ровно один раз (`skip_reason_code` / `failure_reason_code` / `blocked_reason_code`) |
| `guard_egress(...)`, `drop_claim_sentence(...)`, `EgressVerdict` | bounded outbound guard §2.3 на существующих примитивах (`claim_relevance`, `normalize_proposition`, `classify_speech_act`) |
| `delivered_claim_keys`, `claims_coverage` | `source_fetched ≠ delivered_to_writer` |
| `is_runtime_self_question`, `is_external_forbidden`, `is_attributed_speech` | узкие детерминированные детекторы (без инцидентных словарей) |
| `policy_enabled()` / `egress_guard_enabled()` | kill-switch `EVIDENCE_ROUTING_POLICY_ENABLED` / `EVIDENCE_EGRESS_GUARD_ENABLED` (env + ClassVar, паттерн `mca_gates`); OFF → прежнее поведение |

### 1.2. `mca_events.REASON_CODES`: ровно +3

`evidence_skipped`, `evidence_reused`, `evidence_unverified_claim_removed` (311 → 314). Подпричина skip'а едет отдельным полем события (`usage_json`), а не вторым кодом. Тесты-счётчики санкции обновлены: `test_mca19_block_f_round1043`, `test_mca20_integration_round1045`, `test_mca20_rework1_f1_f2` (311 → 314 с комментарием о санкции).

**Расхождение внутри контракта (§1.4), разрешено в пользу 3-кодовой санкции:** таблица называет для `USER_FORBIDS_EXTERNAL` «новый `external_tools_disabled`», но там же санкционирует РОВНО три новых кода. Взят существующий `disabled`; `blocked_reason_code(BLOCK_EXTERNAL_DISABLED)` = `disabled`. Это единственное место, где «новый код» из таблицы не заведён.

### 1.3. `services/direct_l1.py` — только поле `external_claims`

`L1Plan.external_claims` + парсер `_parse_external_claims` (allowlisted, ≤4 элемента, `entity` обязательна, невалидный `relation` → отброс, невалидный элемент → отброс, отсутствие поля → `()`). Поле уточняет claim-key и **не** даёт права отменить обязательную проверку.

### 1.4. `services/direct_execution.py` — C1 и C4

* `resolve_execution_mode(plan, tool_schemas, *, required_caps=())`: `execution_mode="none"` + непустые `required_caps` → `simple_tools` с причиной `evidence_required_overrides_plan`. Демотация adaptive не изменена.
* `derive_simple_steps(..., required_caps=())` / `run_simple_tools(..., required_caps=())`: read-only шаги деривируются и при **пустом** L1-плане (union с дедупом, L1-порядок приоритетен).
* `l2_evidence_budget_chars(..., output_reserve_tokens=0)`: резерв вывода больше не вычитается второй раз; остаётся один раз в композере.
* `measure_nonevidence_chars(system_base, plan_block, time_line, user_blocks, lessons, speech, character)`: один измеритель всего «прочего» payload, включая базу Writer и план-блок.

### 1.5. `services/direct_chat_service.py` — интеграция

| Точка | Что сделано |
| --- | --- |
| preflight перед tool-фазой (`_handle_direct`, после `l1_plan`/`response_plan`) | `_evidence_preflight(...)`: два прохода (класс → контекст разрешений под обязательные capabilities), событие `EVIDENCE_POLICY_DECIDED`, fail-open |
| merge capability (`_l1_tool_subset`) | C2: `skip` (low confidence) только для L1-запрошенных; `required` в отдельном защищённом наборе, код `low_confidence` для них не эмитится; union `L1_requested ∪ runtime_required` |
| C3 в `_l1_tool_subset` | `hot.get("flags.search_enabled")` / `flags.webpage_enabled` гасят инструменты **до** вызова, с наблюдаемым кодом `disabled` (тот же источник истины, что у хендлеров) |
| выбор mode / tool-фаза | `required_caps` доезжают до `resolve_execution_mode` и `run_simple_tools` |
| упаковка evidence | план-блок строится до измерения; capacity из одного измерителя + bounded резерв под машинную строку; `EVIDENCE_DELIVERY` с `fetched/delivered_to_writer/coverage_ratio` |
| Writer | один Writer, топология не менялась; в user-часть добавляется машинная строка `[EVIDENCE]` (coverage/недополучение) и `[RUNTIME]` (фактический маршрут — только для вопроса о себе); пусто → payload байт-в-байт |
| egress (§2.3) | `_run_evidence_egress_guard`: ≤1 адресный lookup (`_evidence_lookup` — тот же `run_simple_tools`), ≤1 регенерация (`_evidence_rewrite` — тот же `_l2_write_answer`), затем детерминированное удаление только этого предложения; событие `EVIDENCE_EGRESS_CHECK`; взаимоисключающе с freshness-ретраем (`not _evidence_retry_used_here`) |
| Initiative | не менялось: participation decision до любой tool-фазы; `handle_initiative` структурно не содержит tool-фазы (закреплено AST-тестом) |

### 1.6. Тесты — `tests/test_evol_evidence_routing.py` (новый, offline)

45 тестов: таблица правил политики, enum'ы и привязка к `REASON_CODES`, C1–C4, route-level прогоны через реальные `_l1_tool_subset`/`_l1_tool_phase` с мок-роутером, egress-guard на фейковых lookup/rewrite, preflight/fail-open на реальном шве сервиса, структурные инварианты (фон без web-импортов, initiative без tool-фазы).

## 2. Покрытие сценариев ТЗ (46-матрица)

| Сценарий | Тест |
| --- | --- |
| 1 «погугли» + low confidence → Search вызван | `test_scenario1_explicit_search_low_confidence_still_calls_tool` |
| 4 технический claim без «погугли» | `test_scenario4_technical_question_without_marker_requires_evidence` |
| 5 low-confidence skip не снимает capability | `test_scenario5_low_confidence_skip_cannot_remove_capability` |
| 6 `execution_mode=none` не скрывает проверку | `test_c1_execution_mode_none_overridden_by_required_caps`, `test_c1_required_caps_derive_steps_with_empty_l1_plan` |
| 7 категорическое «не существует» | `test_scenario7_categorical_nonexistence_needs_source` |
| 8 только сниппет ≠ прочитанный источник | `test_scenario8_snippet_is_not_a_read_source` |
| 11 «лол» → 0 вызовов | `test_scenario11_social_turn_makes_no_tool_calls` |
| 12 техническая тема + сарказм → 0 вызовов | `test_scenario12_technical_topic_with_sarcasm_makes_no_calls` |
| 14 атрибутированный пересказ | `test_scenario14_attributed_retelling_is_not_forced_to_search` |
| 15 новый claim даже в шутке | `test_scenario15_new_external_claim_requires_check_even_with_joke` |
| 16 одна адресная попытка + одна регенерация, шутка цела | `test_scenario16_egress_one_lookup_one_retry_keeps_joke` |
| 17 метафора/мат вне guard'а | `test_scenario17_metaphor_and_mat_are_outside_guard` |
| 19/20/22 фон без web | `test_scenario19_background_services_have_no_web_imports` |
| 23 публичный пересказ Summary | `test_scenario23_public_summary_retelling_is_transformation` |
| 24 смешанный ответ: проверяется только добавка | `test_scenario24_only_new_claim_is_checked_in_mixed_reply` |
| 28 Initiative SILENT/REACT | `test_scenario28_silent_and_react_have_no_evidence_phase` |
| 29 Initiative = тот же контур, без второго preflight | `test_scenario29_initiative_path_has_no_tool_phase` (AST-инвариант) |
| 30 verified_reuse | `test_scenario30_same_claim_with_fresh_source_is_verified_reuse` |
| 31 новая версия → новый fetch | `test_scenario31_changed_version_invalidates_reuse`, `test_claim_key_canon_distinguishes_metric_and_date` |
| 32 «что было в чате» | `test_scenario32_chat_history_answer_needs_no_network` |
| 33 «на какой модели работаешь?» | `test_scenario33_own_model_question_is_runtime_source`, `test_runtime_self_question_detector_is_narrow` |
| 41 запрет сети/RBAC/квота/SSRF | `test_c3_search_switch_off_blocks_network_and_reason_is_honest`, `test_c3_subset_hides_web_tools_when_module_off`, `test_user_forbids_external_makes_required_unmet`, `test_rbac_quota_ssrf_codes_are_specific` |
| 45 корпус: `invalid_skip == 0`, `unnecessary_search == 0` | `test_scenario45_corpus_zero_invalid_skip_zero_extra_search` (8 размеченных классов) |
| C4 двойной резерв / измеритель | `test_c4_no_double_output_reserve`, `test_c4_measure_includes_plan_block_and_system_base` |
| kill-switch OFF | `test_policy_gate_off_returns_previous_behaviour`, `test_egress_gate_off_keeps_answer_byte_identical` |

## 3. Статус поправок C1–C4

| # | Статус | Доказательство |
| --- | --- | --- |
| C1 | **ЗАКРЫТО** | `resolve_execution_mode(..., required_caps)` + `derive_simple_steps(required_caps=)`; тесты 6/C1 |
| C2 | **ЗАКРЫТО** | `_l1_tool_subset`: `skip` только для L1-запрошенных, `required` защищён; тест 5 |
| C3 | **ЗАКРЫТО** | `allowed()` читает флаги `flags.search_enabled`/`flags.webpage_enabled`; `_l1_tool_subset` гасит инструменты до вызова; тесты C3 (2 шт.) |
| C4 | **ЗАКРЫТО в моей зоне** | `l2_evidence_budget_chars(..., output_reserve_tokens=0)` + `measure_nonevidence_chars` (база Writer + план-блок); тесты C4 (2 шт.) |

## 4. Тестовое доказательство

Команды (offline, без сети и без Telegram-публикаций):

```text
py -m pytest tests/test_evol_evidence_routing.py -q            → 45 passed
py -m pytest tests/test_addtr_tools_minifix.py tests/test_soul1_capability_intent.py -q → 124 passed
py -m pytest tests/test_asap7_direct_l1.py tests/test_evol_evidence_routing.py -q       → 82 passed
py -m pytest tests/ -q -k "direct or initiative or tool or l1 or evidence or prompt or mca19 or mca20" -p no:randomly
                                                              → 3518 passed, 15 failed (все — пред-существующие)
```

Классификация 15 падений: **pre-existing**, подтверждено прогоном на чистом HEAD. Для сравнения создавался отдельный `git worktree` на `57081925` (без моих правок), тот же фильтр:

```text
pristine HEAD: 15 failed, 3257 passed
моя сборка:    15 failed, 3518 passed   ← то же множество падений, +261 зелёный тест
```

Список (одинаков в обоих прогонах): 5× `test_direct_fallback_recompose_asap32` (дрейф сигнатуры `_fallback_with_retries` в `llm_client`), 1× `test_mca20_rework1_f1_f2::test_evidence_injection_stays_data_not_instructions` (экранирование `<evidence>` в FC-рендере), 3× `test_soul1_w6_speech_ui` (web-слой соседней полосы), 6× `test_summary_*` (включая известный по контракту §6.3 красный `test_summary_publish_integration_round1026::test_on_l1_not_usable_level2_l2_publishes_article`). Один тест в широком наборе плавает (15↔16 между прогонами, из пред-существующего набора — не мой).

Замечание по гигиене: созданный для сверки worktree удалён после прогона (`git worktree remove`, без `--force`), временные копии — под `WorkspaceData/runs/`, ничего рядом с репозиторием не создавалось.

## 5. Осознанные границы (не «забыли», а решение с причиной)

1. **Правило 8 контракта («неизвестно → проверяем»)**: для деградированного плана (`plan.source == "fallback"`, содержания нет вовсе) и без детерминированных сигналов ввода класс = `NO_NEW_EXTERNAL_CLAIM`. Иначе каждая авария планировщика оплачивала бы сетевой запрос, включая «лол». Все остальные «неизвестные» планы по-прежнему требуют проверки (асимметрия сохранена).
2. **`verify` («проверь это») требует `web_search`, а не `fact_check`**: фактчек-вердикт остаётся за FC-полосой и запрашивается только самим L1-планом — иначе появлялся бы второй preflight/verdict (§2.4) и лишний инструмент в существующих сценариях.
3. **Удаление `external_tools_disabled`** — см. §1.2.
4. **Egress-регенерация** использует тот же `_l2_write_answer` (второго Writer'а нет) и не более одного раза на ход; при конфликте с freshness-ретраем приоритет у evidence-guard (worst case ≤3 LLM-вызова, как и записано в §7 контракта).
5. **Legacy-путь (Direct L1 OFF)**: политика считается и egress-guard работает, но принудительная инъекция инструментов не делается — legacy tool-путь модельный по конструкции и является путём откатa (byte-parity).

## 6. Остатки для волны 2

1. **Initiative evidence-фаза**: `generate_initiative_reply` не имеет retrieval-шага (по брифу — «verify, don't change»). Сценарий 29 закрыт структурно (нет второго preflight, participation раньше), но полноценная «та же политика» для инициативной публикации появится только с retrieval внутри этого метода. Это отдельная работа (риск: тексты инициативы с датами/числами).
2. **Storage для reuse**: `services/source_reuse.py` — соседняя полоса. Политика уже принимает `verified_reuse` (claim-key) и корректно инвалидирует по версии/дате/метрике; после подключения хранилища сценарии 30/31 заработают на бою без правок моего модуля.
3. **Coverage-строка §4.5 в план-блоке**: у меня она едет отдельным машинным user-блоком `[EVIDENCE]` (правка `build_l2_plan_block` была вне моей зоны — `direct_l1.py` ограничен полем `external_claims`). Формально контракт называет план-блок; перенос — косметика одного места.
4. **`source_read`**: `allowed()` честно возвращает `capability_not_ready` до EVOL-SRC; поручение «прочитай код» пока не детектируется (детектор не заводился), поэтому `explicit.read_source` всегда `False`.
5. **Промпт-часть (§5 контракта)** — полоса C: текст L1-планировщика/вербализатора/секции W2 не менялся; машиночитаемое поле `external_claims` уже парсится, но модель о нём ещё не проинформирована промптом. До этого поле будет заполняться редко (деривация §1.2 п.6 работает и без него).
6. **Один плавающий пред-существующий тест** в широком наборе (15↔16) — вне моей зоны, требует отдельного разбора владельцем теста.

## 7. Итог (обязательные три строки)

Политика обязательности read-only проверки реализована как один чистый модуль `services/evidence_policy.py`: класс берётся из планируемого содержания (поля L1-плана + `external_claims` в том же единственном вызове), обязательность объединяется как `allowed(L1_requested ∪ runtime_required)` с RBAC/запретом сети/доступностью/квотой/SSRF/privacy, а фон/социал/трансформация/атрибуция/история/runtime исключаются закрытым enum'ом с привязкой к существующим `reason_code`.

C1–C4 закрыты в моей зоне: `execution_mode=none` и low confidence больше не отменяют обязательную проверку, рубильник «Модуль Поиск» действует в Direct tool-пути до сетевого вызова, двойной резерв вывода убран и «прочее» считается одним измерителем; исходящий guard делает не более одного адресного lookup и одной регенерации, затем удаляет только неподтверждённое предложение, сохраняя тон.

Доказательство: 45 новых контрактных тестов зелёные, широкий набор `direct/initiative/tool/l1/evidence/prompt` — 3518 passed при том же множестве из 15 пред-существующих падений, что и на чистом HEAD (сверка отдельным worktree); в `mca_events.REASON_CODES` добавлены ровно три санкционированных кода, остатки волны 2 (retrieval для Initiative, подключение `source_reuse`, промпт-ревизия §5) перечислены явно.
