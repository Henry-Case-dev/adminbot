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
| egress (§2.3) | `_run_evidence_egress_guard`: ≤1 адресный lookup (`_evidence_lookup` — тот же `run_simple_tools`, разрешение перепроверяется `allowed()`: рубильник/запрет пользователя/RBAC → 0 сетевых вызовов), ≤1 регенерация (`_evidence_rewrite` — тот же `_l2_write_answer`), затем детерминированное удаление только этого предложения; событие `EVIDENCE_EGRESS_CHECK`; взаимоисключающе с freshness-ретраем (`not _evidence_retry_used_here`); классы без собственного внешнего claim (`social/background/attributed/transformation/historical/runtime`) guard не запускают вовсе |
| Initiative | participation decision до любой tool-фазы; retrieval — в `generate_initiative_reply` ПОСЛЕ решения REPLY: тот же `_evidence_preflight` → tool-фаза по `required_caps` → пакет в Writer → bounded guard. SILENT/REACT до метода не доходят (внутри — ещё один ранний выход) → 0 LLM/0 сети; `handle_initiative` инструментов не запускает (AST-инвариант) |

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
| 28 Initiative SILENT/REACT | `test_scenario28_silent_and_react_have_no_evidence_phase`, `test_scenario28_initiative_silent_makes_no_calls` |
| 29 Initiative = тот же контур (preflight → tools → Writer → guard) | `test_scenario29_initiative_uses_same_evidence_contour`, `test_scenario29_initiative_path_structure` (AST: `handle_initiative` без tool-фазы) |
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

1. **~~Initiative evidence-фаза~~** — ЗАКРЫТО в review-fix (§8, блокер 3): `generate_initiative_reply` после решения REPLY выполняет тот же preflight → tool-фазу по `required_caps` → пакет в Writer → bounded guard; SILENT/REACT остаются без единого вызова.
2. **Storage для reuse**: `services/source_reuse.py` — соседняя полоса. Политика уже принимает `verified_reuse` (claim-key) и корректно инвалидирует по версии/дате/метрике; после подключения хранилища сценарии 30/31 заработают на бою без правок моего модуля.
3. **Coverage-строка §4.5 в план-блоке**: у меня она едет отдельным машинным user-блоком `[EVIDENCE]` (правка `build_l2_plan_block` была вне моей зоны — `direct_l1.py` ограничен полем `external_claims`). Формально контракт называет план-блок; перенос — косметика одного места.
4. **`source_read`**: `allowed()` честно возвращает `capability_not_ready` до EVOL-SRC; поручение «прочитай код» пока не детектируется (детектор не заводился), поэтому `explicit.read_source` всегда `False`.
5. **Промпт-часть (§5 контракта)** — полоса C: текст L1-планировщика/вербализатора/секции W2 не менялся; машиночитаемое поле `external_claims` уже парсится, но модель о нём ещё не проинформирована промптом. До этого поле будет заполняться редко (деривация §1.2 п.6 работает и без него).
6. **Один плавающий пред-существующий тест** в широком наборе (15↔16) — вне моей зоны, требует отдельного разбора владельцем теста.

## 7. Итог (обязательные три строки)

Политика обязательности read-only проверки реализована как один чистый модуль `services/evidence_policy.py`: класс берётся из планируемого содержания (поля L1-плана + `external_claims` в том же единственном вызове), обязательность объединяется как `allowed(L1_requested ∪ runtime_required)` с RBAC/запретом сети/доступностью/квотой/SSRF/privacy, а фон/социал/трансформация/атрибуция/история/runtime исключаются закрытым enum'ом с привязкой к существующим `reason_code`.

C1–C4 закрыты в моей зоне: `execution_mode=none` и low confidence больше не отменяют обязательную проверку, рубильник «Модуль Поиск» действует в Direct tool-пути до сетевого вызова, двойной резерв вывода убран и «прочее» считается одним измерителем; исходящий guard делает не более одного адресного lookup и одной регенерации, затем удаляет только неподтверждённое предложение, сохраняя тон.

Доказательство: 45 новых контрактных тестов зелёные, широкий набор `direct/initiative/tool/l1/evidence/prompt` — 3518 passed при том же множестве из 15 пред-существующих падений, что и на чистом HEAD (сверка отдельным worktree); в `mca_events.REASON_CODES` добавлены ровно три санкционированных кода, остатки волны 2 (retrieval для Initiative, подключение `source_reuse`, промпт-ревизия §5) перечислены явно.

> Актуальные цифры и закрытые блокеры ревью — в §8 (review-fix): 52 теста политики + 50 тестов окна, широкий набор 3376 passed при том же множестве 15 пред-существующих падений; retrieval для Initiative больше не остаток, а реализован (сценарий 29).
>
> §9 (review-fix 2) сужает класс-уровневый skip из §8.1: `social` и `attributed` больше не глушат guard — выдуманный факт в шутке или в пересказе чужой речи проверяется.

## 8. Review-fix: блокеры ревью P0 (закрыто)

Все правки — в моей зоне (`services/evidence_policy.py`, `services/direct_chat_service.py`, `services/web_content_extractor.py`, `config/settings.py`) плюс одна минимальная шов-правка `services/tool_router.py` (см. 8.5). Никаких `git reset/checkout/stash/clean/restore` и коммитов не выполнялось; чужие файлы соседних полос (`services/cover*`, `services/prompt*`, web-слой) не трогались.

### 8.1. Блокер 1: guard удалял обычный социальный текст с дробным числом

**Причина.** `_RISK_VERSION_RE` считал версией любой `\d+\.\d+`, а `guard_egress` запускался и для социальных решений: «Я потратил 1.5 часа…» → высокорисковое предложение → один lookup (лишний веб-запрос по приватному тексту) → регенерация → удаление предложения.

**Исправление.**
* `_RISK_VERSION_RE`: версия — ЛИБО слово-контекст (`версия/version/v` + номер), ЛИБО минимум три компонента (`1.2.3`). Голое `1.5` версией не считается.
* `guard_egress` вводит `GUARD_SKIP_CLASSES = (social, background, attributed, transformation, historical, runtime)` и возвращает `GUARD_NONE` (`note="not_externally_factual"`) для классов без собственного внешнего claim (в т.ч. при `required=False` и пустых claims) — проверять нечего, сеть не запускается, текст не режется.

**Доказательство.** `test_review_decimal_number_is_not_a_version_claim`, `test_review_social_reply_with_decimal_makes_no_lookup` (guard + `_run_evidence_egress_guard`: lookup/rewrite = 0, ответ байт-идентичен), прежние сценарии 7/8/16/17/24 остались зелёными.

### 8.2. Блокер 2: адресный lookup обходил рубильник и запрет пользователя

**Причина.** `_evidence_lookup` собирал `active_tools()` без фильтра и вызывал `run_simple_tools` напрямую — мимо `allowed()`/`_evidence_context`.

**Исправление.** `_evidence_lookup(..., decision=None, user_forbids=False)`:
* вызывается только если `web_search` уже входит в `required_caps` решения политики;
* заново берёт снимок `_evidence_context(chat_id, ("web_search",), user_forbids=...)` и спрашивает `evidence_policy.allowed("web_search", ctx)` (RBAC → рубильник/запрет → провайдер/ключ → квота);
* при отказе — 0 сетевых вызовов и честный лог `evidence lookup blocked … code=…`, guard деградирует без выдуманной проверки.

**Доказательство.** `test_review_egress_lookup_respects_allowed_gate`: положительный контроль (разрешено → ровно один `execute_web_search`) и три отказа (рубильник `flags.search_enabled=false`, явный запрет в реплике, решение без `web_search` в `required_caps`) → `router.dispatched == []`.

### 8.3. Блокер 3: сценарий 29 не был реализован

**Причина.** `generate_initiative_reply` шёл сразу в `_l2_write_answer`; прежний тест закреплял отсутствие tool-фазы AST-инвариантом.

**Исправление.** После решения об участии (метод вызывается только при `action=reply`; внутри — ранний выход для SILENT/REACT) инициативная ветка идёт тем же контуром: `_evidence_preflight` → `_l1_tool_subset(decision=…)` + `_l1_tool_phase(required_caps=…)` (тот же `run_simple_tools`) → `build_evidence_pack` → `_l2_write_answer(evidence=…, user_blocks=+[EVIDENCE])` → `_run_evidence_egress_guard` (≤1 разрешённый lookup, ≤1 регенерация тем же Writer'ом, затем удаление только спорного предложения) + события `EVIDENCE_DELIVERY`/`EVIDENCE_EGRESS_CHECK`. SILENT/REACT: 0 LLM, 0 tool-вызовов, 0 сети.

**Доказательство.** `test_scenario29_initiative_uses_same_evidence_contour` (реальный шов сервиса: `router.dispatched == ["execute_web_search"]`, пакет и строка `[EVIDENCE]` доехали до Writer'а), `test_scenario28_initiative_silent_makes_no_calls` (SILENT/REACT → `""`, роутер и Writer не вызывались), `test_scenario29_initiative_path_structure` (AST: `handle_initiative` без tool-фазы, `generate_initiative_reply` — с ней).

### 8.4. Прочие замечания того же патча

1. **`EVIDENCE_WINDOW_DYNAMIC_ENABLED` реально зарегистрирован** в `config/settings.py` как env-only `ClassVar` (default ON, вне `dataclasses.fields` → каталог-Δ = 0): рубильник больше не «инертен». `test_evidence_window_kill_switch_is_registered_in_settings` + прежний `test_dynamic_off_keeps_legacy_behaviour`.
2. **`USER_FORBIDS_EXTERNAL` — законный skip, а не сбой.** `_with_allowed`: запрет сети (рубильник/чат/явный запрет в реплике) → `required=False`, `skip_reason=USER_FORBIDS_EXTERNAL`, `skip_code()=="disabled"`, `blocked=(("web_search","disabled"),)`, `failure_code=None`; `.NETWORK_UNAVAILABLE` остаётся только там, где проверка реально сорвалась (провайдер/ключ/квота/SSRF/privacy). Writer получает честную строку «внешняя проверка не выполнялась (user_forbids_external)». Тесты: `test_review_user_forbidden_is_valid_skip_not_failure`, `test_c3_search_switch_off_blocks_network_and_reason_is_honest`, `test_user_forbids_external_is_recorded_skip`.
3. **`total_chars`/остаток при extraction-ceiling'е честные.** `web_content_extractor._finalize_document` пишет реальный объём ДО обрезки (`total_chars=real_total`), `text`/`truncated_at_extraction` по-прежнему описывают доставленное. `tool_router._fetch_article`: `remainder_chars` = реальный остаток источника (`max(excerpt.remainder, total_chars - end)`), отдельно `remainder_retrievable_chars` = сколько добрать тем же инструментом, `why` различает `over_window` и `extraction_ceiling`. Тесты: `test_extraction_ceiling_is_honest` (30000 из 1000-символьного потолка), `test_extraction_ceiling_keeps_total_and_remainder_honest`.
4. **Сценарий 13** («на каком железе ты это запускал?») больше не классифицируется как `externally_factual`: `_SELF_STATE_RE` узко расширен предметами «железо/запуск» (по-прежнему нужен субъект «о себе»), решение → `runtime` + `sufficient_runtime_source`. Тесты: `test_review_scenario13_hardware_question_is_runtime_source`, расширенный `test_runtime_self_question_detector_is_narrow` (у собеседника про железо — не runtime-вопрос).
5. **Счётчики санкции reason-кодов.** Латентно красные пин-тесты `test_mca10b_…block_a_round1041::test_kill_switch_registry_73_and_defaults` и `test_mca17c_invariants_round1047::test_reason_280_single_delta` держали 311 вместо актуальных 314 — обновлены до +3 санкционированных кодов evidence-политики (остальные три пин-теста уже были 314).

### 8.5. Границы этого патча

* `services/tool_router.py` — одна шов-правка (остаток/`why`/`remainder_retrievable_chars`): без неё честный `total_chars` из экстрактора давал бы противоречие «total 30000 / remainder 0 / truncated false». Другие файлы соседней полосы не менялись.
* Minimal-двойники сервиса без `_evidence_preflight` (тестовые стабы SOUL) сохраняют прежний путь без evidence — реальный `DirectChatService` метод имеет всегда.

### 8.6. Прогоны (offline, без сети/Telegram-публикаций)

```text
py -m pytest tests/test_evol_evidence_routing.py -q                       → 52 passed
py -m pytest tests/test_evol_evidence_window.py -q                        → 50 passed
py -m pytest tests/test_evol_evidence_routing.py tests/test_evol_evidence_window.py -q → 102 passed
py -m pytest tests/test_web_content_extractor.py tests/test_tool_chains_round1026.py
   tests/test_tool_schemas.py tests/test_param_catalog.py
   tests/test_settings_persistence_round1014.py tests/test_asap8_v6_wa1_config_cache.py
   tests/test_cfg03_param_audit.py tests/test_asap7_direct_settings.py
   tests/test_soul1_core_registry_api.py tests/test_mca11_tool_result_round1028.py -q → 230 passed
py -m pytest tests/test_soul1_style_payload.py tests/test_soul1_w5_observer_gates.py
   tests/test_evol_evidence_routing.py tests/test_evol_evidence_window.py -q → 131 passed
py -m pytest tests/test_asap_speech_i_matrix.py tests/test_asap5_integration_w3.py
   tests/test_asap8_f6_initiative.py tests/test_asap8_initreply_binding.py
   tests/test_asap8_v63_b01_initiative_observer.py tests/test_evol_social_frame.py
   tests/test_initiative_delivery_telemetry.py tests/test_mca09_intents_block_e_round1040.py
   tests/test_mca09_intents_off_parity_round1040.py
   tests/test_mca10b_random_applications_block_a_round1041.py
   tests/test_mca10b_random_applications_block_c_round1041.py tests/test_nostalgia_w2.py
   tests/test_nostalgia_worker.py tests/test_p0_followup_nostalgia_ab.py
   tests/test_p0_init_arch_fix_observer.py tests/test_p0_initfix_initiative_observer.py
   tests/test_soul1_w5_initiative_vitality.py -q → 344 passed
py -m pytest tests/ -q -k "direct or initiative or tool or l1 or evidence or prompt" -p no:randomly
                                                    → 3376 passed, 15 failed (то же множество пред-существующих)
```

Плавающие пред-существующие (вне зоны, проверены поштучно — проходят одиночно): `test_betterstack_handler::test_real_302_not_followed_by_opener` (сетевой 302), `test_mca09_intents_block_e_round1040::test_candidate_ready_defers_intent_backoff`, `test_asap8_initreply_binding::test_case3_reply_to_l1_chosen_message`, `test_asap_speech_i_matrix::test_i05_deleted_target_cancels_for_semantic_addressee` — порядок/общее состояние `mca_random_source` в общем наборе; эти тесты используют `_FakeWriter`, мой код в них не участвует.

## 9. Review-fix 2: guard был ПОЛНОСТЬЮ выключен для шутки и атрибутированного пересказа (закрыто)

**Блокер (P0, последняя претензия ревью).** `guard_egress` не проверял ничего для классов `social`/`attributed` (`GUARD_SKIP_CLASSES` + условие `or not required`). Значит, добавленный Writer'ом новый внешний факт уходил в чат без единой проверки:
* сценарий 16: «Кстати, модели GeForce RTX 9090 не существует» в шутке (`act=banter`, `claims=[]`, `required=False`) → guard `none`;
* сценарий 24: «По словам участников, цена 500$. Новая цена будет 700$» → добавленная своя цена тоже не проверялась.

**Причина.** Skip строился по ПЛАНИРУЕМОМУ содержанию, а guard смотрит УЖЕ написанный текст: Writer дописывает факт мимо плана, и именно в самом «безопасном» классе он проходил без проверки. Ложный вызов на «1.5 часа» (§8.1) к этому моменту уже устранён сужением `_RISK_VERSION_RE` — класс-уровневый skip стал не нужен и вреден.

**Исправление (моя зона).**
* `GUARD_SKIP_CLASSES = ("background", "transformation", "historical", "runtime")` — `social` и `attributed` убраны; условие `or not required` убрано: решение «план не требует проверки» не означает «в тексте не появится новый внешний факт».
* `background` оставлен осознанно: класс выставляется при выключенном рубильнике политики (`policy_disabled`) — паритет прежнего поведения и §8.2 kill-switch.
* Попредложенческий `_attributed()` сохранён: чужая речь/цитата — не наш claim, проверяется только ДОБАВКА Writer'а.
* Детектор высокого риска не расширялся: «1.5 часа» (арифметика), метафора, мат, год без события по-прежнему `GUARD_NONE` — шутка не режется.
* Initiative (необязательный пункт ревью, сделан): правило 7b в `_evaluate` — план без claim'ов и с НЕфактическим актом (`response_act=other`) → `required=False`, `skip_reason=NO_NEW_EXTERNAL_CLAIM` (раньше §1.2 п.8 гнал веб-поиск по внутренней формулировке цели «напомнить про релиз 1017»). Новый `evidence_policy.claims_query(decision)` собирает запрос ТОЛЬКО из claim'а (`entity`+`version/metric/date`); `generate_initiative_reply` использует его вместо служебной цели.

**Что осталось честно ограниченным.** Для `social`/`attributed` решение политики не запрашивает `web_search` (`required_caps=()`), поэтому `_evidence_lookup` (контракт §8.2 закреплён тестом) адресный запрос не делает: путь деградирует честно — подсказка Writer'у убрать claim, при упорстве детерминированное удаление ТОЛЬКО этого предложения. Шутка/пересказ и остальной текст сохраняются; выдуманный факт в чат не уходит.

**Доказательство (новые/переписанные тесты `tests/test_evol_evidence_routing.py`).**
* `test_review_fix2_joke_with_added_nonexistence_is_checked` — реальное решение политики (`act=banter`, `claims=[]`, `required=False`): guard → `one_lookup_then_hint_retry` именно на предложении с «не существует» (шутка не в фокусе); через `_run_evidence_egress_guard` ровно 1 lookup + 1 регенерация, «Ну и мрак.» цело; при Writer'е, проигнорировавшем подсказку, `dropped_claim=1` и удалено только это предложение.
* `test_review_fix2_attributed_retelling_checks_only_the_addition` — реальное решение (`attributed`, `claims=[]`): в адресную проверку уходит только «Новая цена будет 700$» (в lookup нет «500»), пересказ остаётся в тексте; чистая атрибуция без добавки → `GUARD_NONE`.
* `test_review_fix2_transformation_class_is_still_not_guarded` — узкий skip не снят: пересказ Summary вне guard (`note="not_externally_factual"`, сценарий 23).
* `test_review_social_reply_with_decimal_makes_no_lookup` (переписан) — для `social` guard ТЕПЕРЬ запускается, но «1.5 часа» не высокий риск: `GUARD_NONE`, 0 lookup, 0 регенераций, ответ байт-идентичен.
* `test_review_fix2_casual_plan_without_claims_needs_no_search`, `test_review_fix2_casual_initiative_makes_no_search` — casual/инициатива (`other`, без claim'ов): `NO_NEW_EXTERNAL_CLAIM`, `router.dispatched == []`, Writer без evidence; `claims_query` строится из claim'а и не содержит внутренней цели.

**Прогоны (offline, без сети/живых провайдеров/Telegram-публикаций).**

```text
pytest tests/test_evol_evidence_routing.py tests/test_evol_evidence_window.py -q      → 107 passed
pytest tests/test_evol_evidence_{routing,window}.py + test_direct_chat*.py
   test_asap8_v6_wc_direct_d03/d04/matrix, test_asap8_f6_initiative,
   test_asap8_v63_b01_initiative_observer, test_initiative_delivery_telemetry,
   test_p0_initfix_initiative_observer, test_evol014_meme_initiative,
   test_soul1_w5_initiative_vitality, test_evol_social_frame,
   test_asap8_initreply_binding -q                                                    → 549 passed
pytest tests/test_asap7_direct_l1, test_direct_chat_lore_inject/prompts/relations_inject,
   test_direct_context_capacity/composer/scenarios_asap3,
   test_direct_decision_matrix_asap3, test_direct_l1_corrective_r1/l1d_contract,
   test_direct_llm_decision_asap32, test_direct_two_call_round1022,
   test_soul1_direct_prompt_reads -q                                                  → 271 passed, 5 failed (пред-существующие)
```

5 падений — `tests/test_direct_fallback_recompose_asap32.py` (`TypeError: fb_retries() got an unexpected keyword argument 'sent'`, вызов из `services/llm_client.py:1485`): тестовый двойник отстал от сигнатуры `_fallback_with_retries(payload, sent=…)`. `git diff HEAD` по `services/llm_client.py` и этому тесту ПУСТ — состояние ветки до моей правки, evidence-routing в этих тестах не участвует. Вне моей зоны; зафиксировано как incidental finding.

**Границы.** Изменены только мои файлы: `services/evidence_policy.py`, `services/direct_chat_service.py` (только инициативный запрос), `tests/test_evol_evidence_routing.py`, этот отчёт. Ни `git reset/checkout/stash/clean/restore`, ни коммитов не выполнялось; чужие полосы (`services/cover*`, web-слой, `services/pipeline_analytics.py`, правимые mca-тесты, скриншот-евidence) не трогались.

---

## 10. Review-fix 3: два блокера доказательной базы (закрыто)

Ревью доказательной базы дало два FAIL-критерия. Оба воспроизведены offline-пробой ДО правки и подтверждены после.

### 10.1. Правило 7b было ГЛОБАЛЬНЫМ и гасило §1.2 п.8 для Direct

**Блокер.** `if not claims and act not in FACTUAL_ACTS → NO_NEW_EXTERNAL_CLAIM` не различало пути. План Direct `response_act=other`, `tool_policy=none`, без `external_claims`, `task_kind=direct_answer` получал `required=False` — то есть контрактный §1.2 п.8 («неизвестно → проверка требуется») был мёртв: обязательная проверка пропускалась именно там, где содержание ответа нам просто неизвестно.

**Исправление (моя зона).**
* `RuntimeState.initiative: bool = False` — признак хода БЕЗ входящей реплики. Заполняется единственным новым аргументом `_evidence_preflight(..., initiative=True)` из инициативного Writer'а; Direct его не передаёт (значение по умолчанию `False`), поэтому для Direct действует обычный порядок правил.
* Законная часть 7b перенесена в правило 6 и срабатывает ТОЛЬКО при `runtime_state.initiative`: инициатива без claim'ов → `required=False`, `skip_reason=NO_NEW_EXTERNAL_CLAIM`, `note="initiative_without_claim_query"`. Сама 7b удалена (на её месте — комментарий с причиной), иначе она продолжала бы перекрывать п.8.
* Для Direct без claim'ов и с НЕфактическим актом теперь работает п.8: `required=True`, `required_caps=("web_search",)`, `note="unknown_requires_check"`.

### 10.2. Инициатива `act=answer` без claim'ов уходила в сеть со служебной целью

**Блокер.** `_init_search_query = claims_query(decision) or _goal_query` — при пустом `claims_query` в поисковик уходила внутренняя формулировка цели («напомнить Ane про релиз 1017»), т.е. единственный сетевой вызов тратился на служебный текст, а не на проверяемое утверждение.

**Исправление (моя зона).**
* `_init_search_query = _evp.claims_query(decision)` — фолбэка на цель больше нет; tool-фаза дополнительно требует непустой запрос (`and _init_search_query`).
* Правило 6 (см. 10.1) для инициативы без claim'ов вообще не запрашивает проверку → tool-фазы нет, пакета нет, Writer'у ничего не выдаётся за проверку.
* Честный случай «проверка обязательна, но адресовать нечем» (инициативная цель с маркером поиска, claim'ов нет) закрыт новым `evidence_policy.mark_required_unmet(decision)`: `required` остаётся `True`, решение помечается `required_unmet=True` + `failure_code=NO_RELEVANT_RESULTS` (`retrieval_empty`), `required_caps` очищаются, `note` получает `+no_addressable_query`. Preflight применяет это сам до события, поэтому `EVIDENCE_POLICY_DECIDED` несёт честные `required/required_unmet`, а Writer получает «внешняя проверка НЕ выполнена».

### 10.3. Доказательство (тесты `tests/test_evol_evidence_routing.py`)

* `test_review_fix2_direct_unknown_plan_still_requires_check` (переписан из rf2) — Direct `act=other` + `tool_policy=none` без claim'ов → `required=True`, `("web_search",)`, `skip_reason is None`, `note="unknown_requires_check"`.
* `test_review_fix2_casual_initiative_plan_without_claims_needs_no_search` — инициатива (`RuntimeState(initiative=True)`) `act=other` без claim'ов → `required=False`, `initiative_without_claim_query`, `claims_query == ""`; инициатива С claim'ом → `required=True`, запрос из claim'а («geforce rtx 9090 … 1.0», без служебной цели).
* `test_scenario29_initiative_uses_same_evidence_contour` (переписан) — инициатива С claim'ом: ровно один `execute_web_search`, в аргументах запроса есть claim («релиз 1017»), пакет доехал до Writer'а.
* `test_scenario29_initiative_answer_without_claims_makes_no_search` (новый) — инициатива `act=answer` без claim'ов: `router.dispatched == []`, `evidence == ""`, блока `[EVIDENCE]` Writer'у нет.
* `test_review_fix3_initiative_required_without_query_is_unmet` (новый) — инициативная цель «погугли про релиз 1017»: проверка обязательна, но запроса нет → 0 сетевых вызовов, Writer получает «внешняя проверка НЕ выполнена».
* `test_review_fix2_casual_initiative_makes_no_search` — сохранён без изменений и проходит (инициативный `act=other`, 0 вызовов).

### 10.4. Прогоны (offline; без сети, живых провайдеров и Telegram-публикаций)

```text
pytest tests/test_evol_evidence_routing.py -q                     → 60 passed
pytest tests/test_evol_evidence_routing.py
       tests/test_evol_evidence_window.py -q                      → 110 passed
+ direct/initiative набор §9 (test_direct_chat*, asap8_v6_wc_direct_d03/d04/matrix,
  asap8_f6_initiative, asap8_v63_b01_initiative_observer,
  initiative_delivery_telemetry, p0_initfix_initiative_observer,
  evol014_meme_initiative, soul1_w5_initiative_vitality, evol_social_frame,
  asap8_initreply_binding) -q                                     → 625 passed
+ direct-L1 набор §9 (asap7_direct_l1, direct_chat_lore_inject/prompts/
  relations_inject, direct_context_capacity/composer/scenarios_asap3,
  direct_decision_matrix_asap3, direct_l1_corrective_r1/l1_l1d_contract,
  direct_llm_decision_asap32, direct_two_call_round1022,
  soul1_direct_prompt_reads) -q                                   → 268 passed
```

5 пред-существующих падений `tests/test_direct_fallback_recompose_asap32.py` (`fb_retries() got an unexpected keyword argument 'sent'`) остаются вне моего набора и вне зоны: `git diff HEAD` по `services/llm_client.py` и этому тесту пуст.

**Кандидат.** Worktree `WorkspaceData/worktrees/c742e4de9e92c489/evol-71536a366a11-c63f6f44`, ветка `evol/impl`, HEAD `26905a89`; изменения этой правки не закоммичены (по правилу задания): `services/evidence_policy.py`, `services/direct_chat_service.py`, `tests/test_evol_evidence_routing.py`, этот отчёт.

**Остаточный риск.** Для Direct план без claim'ов и с `response_act=other` теперь тратит один bounded lookup (§1.2 п.8, осознанная асимметрия контракта) — это и есть восстановленное поведение, но вызовов в реальных casual-ходах станет больше; ширина ограничена прежними гейтами `allowed()`, рубильником и бюджетом «один адресный lookup».

**Review-fix 4 (01.11.2026, w13):** правило 6 сужено до НЕфактических актов (`runtime_state.initiative and not claims and act not in FACTUAL_ACTS`): инициатива `response_act=answer` без claim'ов больше НЕ получает тихое «проверять нечего» — решение `required=True` (`factual_plan_act`), а preflight с пустым `claims_query` честно помечает проверку `required_unmet` (`NO_RELEVANT_RESULTS`), Writer получает «внешняя проверка НЕ выполнена»; ни один сетевой вызов при этом не уходит (§5.2/сценарий 29: инициатива подчиняется тем же правилам, что Direct).
**RED→GREEN:** эмуляция прежней ветки даёт `required=False / initiative_without_claim_query`, после фикса — `required=True / factual_plan_act`; `test_scenario29_initiative_answer_without_claims_makes_no_search` переписан на честную пометку `[EVIDENCE] … НЕ выполнена`, добавлен `test_review_fix4_initiative_factual_act_without_claims_requires_check`; `pytest tests/test_evol_evidence_routing.py + tests/test_evol_evidence_window.py` → 111 passed, direct/initiative подмножество → 212 passed (exit 0).

---

## 11. Волны 3–5 (01.11.2026): подключение reuse, канон промптов, корпус

Кандидат: worktree `WorkspaceData/worktrees/c742e4de9e92c489/evol-71536a366a11-c63f6f44`, ветка `evol/impl`, HEAD `7e427fc8` + незакоммиченные правки этой полосы (по правилу задания коммитов не делалось; `git reset/checkout/stash/clean/restore` не выполнялись).

### 11.1. Волна 3 — reuse на РЕАЛЬНОМ пути Direct (§1.6/§3.2/§3.4/§4.3)

Волны 1–2 объявляли `verified_reuse` в политике, но живые швы не были подключены: `ToolContext.claim_keys` никто не заполнял, `evidence_budget_chars` получала только инициатива (и то legacy-константой), а факт доставки выдержки нигде не фиксировался. Сценарий 30 существовал только как тест политики. Что сделано:

| Точка | Правка |
| --- | --- |
| `direct_chat_service._evidence_supplied(..., verified_reuse=)` | чистый параметр (без I/O): claim-key, покрытые свежим источником |
| `_evidence_reuse_claims(plan, chat_id, bypass)` | `source_reuse.lookup` по каждому claim плана; зачёт ТОЛЬКО при `delivered_chars > 0`; явное «проверь заново» (`explicit.verify`) → `bypass` |
| `_evidence_preflight` | передаёт reuse-ключи в `SuppliedSources` → правило 9 политики даёт `QUALIFIED_VERIFIED_REUSE` |
| `_handle_direct` (после preflight, ДО tools) | `tool_ctx.claim_keys = decision.claims`; `tool_ctx.evidence_budget_chars = self._evidence_call_budget_chars(...)`; `_ev_reuse_pack = self._evidence_reuse_pack(...)` |
| reuse-ход | tool-фаза не запускается вовсе (`raw=None`): 0 сетевых вызовов, Writer получает пакет из уже прочитанного источника |
| `_record_evidence_delivery(decision, pack, chat_id)` | `source_reuse.record_delivery` по каждому РЕАЛЬНО доставленному claim (`delivered_chars_by_claim`) — `source_fetched ≠ verified_reuse` |
| `generate_initiative_reply` | те же `claim_keys` + reuse-пакет (инициатива не отдельный контур); отсутствующий у тестовых двойников метод → прежний путь без reuse |
| `direct_execution.build_reuse_evidence_pack` | тот же пакакер (`build_evidence_pack`) над записями кеша: одна упаковка, одна семантика truncation/limitations, строка `reuse: <claim_key> \| <source_id> \| age=…` |
| `direct_execution.delivered_chars_by_claim` | привязка доставки к claim'у: сущность И версия/дата/метрика обязаны быть в тексте источника (выдержка про 4.1 не подтверждает claim про 4.2) |

Smart Cache не тронут (в правке не участвует; `source_reuse` — существующий модуль волны 2).

### 11.2. Волна 4 — окно L1 и третий кап поиска

**`L1_WINDOW_LINE_CHARS = 200` — корневая причина, а не симптом.** Строка L1-окна резалась фиксированно, поэтому версия/цена/дата в длинном сообщении до планера не доезжали, и optional-поле `external_claims` почти не заполнялось. Введён `direct_l1.window_line_chars(window, budget_tokens=)` → кап выводится из реального бюджета (`limits.direct_l1_context_tokens`) и ФАКТИЧЕСКОГО числа строк окна:

```text
share = budget_tokens * 4 * L1_WINDOW_SHARE(0.6) / rows
cap   = clamp(share, floor=200, ceiling=1200)
```

Короткое окно получает длинные строки (до 1200), полное окно 20 строк остаётся на прежнем полу 200; общий бюджет пакета по-прежнему держит `_cap_context` (это потолок ОДНОЙ строки, а не новый бюджет). Факты: `window_line_chars([1 строка]) = 1200`, `window_line_chars([20 строк]) = 200`, claim на 260-м символе сообщения теперь виден планеру, при `budget_tokens=400` пакет укладывается в бюджет.

**Третий кап `search_service.research` (P2).** Раньше агрегатору отдавался `limits.search_max_symbols` (4000) как «слепой лимит качества» — тот же класс дефекта, что снят в tool-пути (§4.3): срез терял URL до нашей упаковки. Теперь агрегатор получает технический ceiling реального окна (`auto_budget.resolve_evidence_tool_window("search").hard_ceiling`), а `{max_symbols}` в каноне остаётся ПОТОЛКОМ ОТВЕТА и равно операторскому лимиту как есть (в каноне это «жёсткий потолок ответа», не объём выборки). При `EVIDENCE_WINDOW_DYNAMIC_ENABLED=OFF` — ровно прежние 4000 в обоих местах (паритет доказан тестом).

### 11.3. Волна 5 — канон промптов (§5 контракта)

| `prompt_id` (block_id) | Правка | Прежние байты (откат/ступень) | Метка ревизии |
| --- | --- | --- | --- |
| `prompts.direct_l1_planner_system_prompt` (`direct.base.l1_planner`) | в схему JSON добавлено optional `"external_claims": []`; новая секция «ВНЕШНИЕ УТВЕРЖДЕНИЯ» с форматом `entity/relation/version/date/metric` и фразами: «Обязательность read-only проверки исполняет runtime независимо от твоего мнения: уверенность, tool_policy и пустой capabilities_needed её не отменяют» + «external_claims не является разрешением не проверять» | `PREV_DIRECT_L1_PLANNER_EVR0` (`14743d288ea3`), ступень `prompt_migrations` + первый шаг `ROLLBACK_MIGRATIONS` | `l1-planner-external-claims` (`ff502bb6b60e`) |
| `prompts.direct_chat_verbalizer_system_prompt` (`direct.base.l2_writer`) | секция «ДОСТАВЛЕННЫЕ ДОКАЗАТЕЛЬСТВА»: опираться на доставленное; не добавлять проверяемых фактов вне его; не заявлять «проверил/нашёл», если проверки не было; «отсутствие результата ≠ не существует»; короткая реплика/шутка не превращается в отчёт со ссылками | `PREV_CHAT_VERBALIZER_EVR0` (`f5c4807d088e`… фактически байты PA5W2) | `l2-writer-evidence-discipline` (`68f0233d7050`) |
| `prompts.direct_chat_system_prompt` (`direct.base.tool_phase`) | ОДНА фраза после секции W2: «Обязательность внешней проверки решает runtime, а не доступность инструмента… задача этапа — передать Writer границу знания» | `PREV_CHAT_EVR0_SYSTEM_PROMPT` (байты W2) | `toolphase-runtime-evidence` (`7a5aea1b73a4`) |

Реестр/ступени: `FACTORY_REVISION_LABELS` + `FACTORY_REVISION_SEALS` обновлены; `FACTORY_SET_SHA256_12` `519663a57eb6 → 724a5d420896` (переутверждено осознанно, SOUL-AMD.3.2); `prompt_migrations.PROMPT_MIGRATIONS` получили по новой ступени на канон, `ROLLBACK_MIGRATIONS` — по новому первому шагу (активные байты → `PREV_*_EVR0`). Кастомы владельца не перетираются (ступень срабатывает только на точное совпадение байт). `prompt_factory.py` правки не потребовал: ревизии и слепки считаются из `factory_text`.

**Не менялись (по контракту §5):** `prompts.search_system_prompt`, `summary_*`, `dream/dossier/memory`, `factcheck_*`, `verbilizer_mode_*`. Регресс-тест `test_wave5_background_prompts_have_no_search_directive` проверяет отсутствие поисковой директивы в эффективных фоновых канонах.

**Карта конфликтов (обязательная таблица §5/§7 ТЗ).**

| Стадия / prompt_id / ревизия | Цитируемая конфликтующая инструкция | С чем конфликтует | Consumer / effective path | Решение | Тест |
| --- | --- | --- | --- | --- | --- |
| L1 planner / `l1-planner-external-claims` | «уверенность» и `tool_policy` как поля плана; прежнее правило 4 «когда достоверность существенно зависит…» | §1.2 п.8 и C1/C2: L1 не должен отменять обязательную проверку | `_plan_direct_l1` → `prompts.direct_l1_planner_system_prompt` (машинная стадия, без Core) | формулировка «решает runtime, а не твоё мнение»; L1 по-прежнему не теряет права просить поиск | `test_wave5_l1_planner_informs_model_about_external_claims`, `test_rule4*` |
| L1 planner | JSON-дисциплина «все поля обязательны» | optional-поле не должно заставлять выдумывать claim'ы | тот же | поле помечено НЕобязательным + «пустой список допустим» | тот же тест (`"external_claims": []`) |
| L2 Writer / `l2-writer-evidence-discipline` | «ТОЧНОСТЬ: не выдумывай» без правила «не заявлять проверку» | `public_speech_guard.claims_total_verification` ловит это только на выходе | `_l2_write_answer` → `prompts.direct_chat_verbalizer_system_prompt` | в канон добавлена фактовая дисциплина доставленных доказательств (промпт поддерживает guard, а не дублирует его) | `test_wave5_writer_has_factual_discipline` |
| L2 Writer | «Оформление и речевая манера определяются отдельными слоями» (Style/Core) | нельзя задавать стиль в секции про факты | тот же | секция говорит только о фактической стороне и о неуместности списка ссылок в шутке | тот же + `soul1_composer_parity_off` |
| tool phase / `toolphase-runtime-evidence` | «проверяй через execute_web_search, когда он доступен» (W2) | C3/`allowed()`: доступность инструмента ≠ основание обойти policy | `_compose_speech_system(writer="tool_phase")` | одна фраза: обязанность решает runtime; секция W2 не переписана | `test_wave5_tool_phase_says_runtime_decides_not_tool_availability`, `test_direct_chat_prompts` |
| фон (Summary/Dream/Dossier/Memory/FactCheck) | — | §2.5: ноль изменений и ноль поисковых директив | фоновые сервисы | не менялись | `test_wave5_background_prompts_have_no_search_directive`, `test_scenario19_background_services_have_no_web_imports` |

**Снимок effective payload (§5.5 контракта).** `tests/fixtures/soul1/direct-runtime-assembly-asap2.txt` — исторический снимок сборки. Перезаписывать его «на глаз» нельзя (он снят внешним скриптом в конкретном окружении и его USER-байты зависят от флагов тестовой сессии — проверено: два прогона в разных окружениях дают разные USER). Поэтому сверка переведена на детерминированную проекцию: `_canon_patch` заменяет в ЭТАЛОНЕ ровно изменившийся канонический блок активными байтами (и падает, если блок не найден ровно один раз). Всё остальное — исторические байты сборки — сравнивается байт-в-байт.

### 11.4. Волна 5 — корпус и метрики (сценарии 45/46)

`tests/test_evol_evidence_corpus.py` (новый, `CONTRACT`): 13 размеченных кейсов по 7 классам (`externally_factual`, `attributed`, `background`, `social`, `transformation`, `runtime`, `historical` + reuse-кейс) через РЕАЛЬНЫЕ швы (`evaluate_evidence_need` + `allowed`, `source_reuse`, `_evidence_reuse_pack`, `guard_egress`, `_run_evidence_egress_guard`). Сеть не вызывается ни разу: «вызов» — решение политики + мок-роутер.

Метрики прогона (числа сняты этим же прогоном, без подмены разметки):

```text
eligible_factual=4  verified_fresh=4  verified_reuse=1  alternate_source=7
attempted_failed=0  valid_skip=8      invalid_skip=0     unnecessary_search=0
unsupported_blocked=2
latency (CPU политика+упаковка+guard, без сети/LLM): 0.0055 s и 0.0043 s
```

Утверждения теста: `invalid_skip == 0`, `unnecessary_search == 0` на исключённых классах, `unsupported_blocked >= 2` (ложь в шутке и добавка в атрибутированном пересказе реально блокируются), состав метрик между двумя прогонами на одном корпусе совпадает (подмена разметки не «улучшает» числа).

Честное ограничение: `historical`-класс достижим только через `SuppliedSources.history_answer` — детерминированного детектора «ответ уже есть в истории» в проде нет (волна 1 его не заводила), поэтому кейс помечен как класс-контракт, а не как «наблюдённый на живом пути».

### 11.5. Тестовое доказательство (волны 3–5)

> Review-fix 5 (§12): числа ниже — состояние ДО правки блокеров; актуальные
> прогоны, состав тестов и что именно они доказывают — §12.4.

```text
pytest tests/test_evol_evidence_routing.py tests/test_evol_evidence_window.py
       tests/test_evol_evidence_corpus.py -q                       → 129 passed
pytest tests/test_evol_evidence_{routing,window,corpus}.py
       test_direct_chat_prompts.py test_direct_l1_l1d_contract.py
       test_prompt_migrations.py test_evol018_prompt_audit.py
       test_soul1_registry_completeness.py test_soul1_composer_parity_off.py
       test_smartsearch_service.py test_tool_schemas.py -q          → 284 passed
pytest tests/test_asap_speech_r3b_canon.py test_cfg07_backstage_contract.py
       test_p0_delta_depth_instruction.py test_p0_prompts_core.py
       test_post_asap5_w1_writer_core.py test_post_asap5_w2_tech_reasoning.py
       test_speech_p0_corrective_l1_route.py test_direct_l1_corrective_r1.py
       test_hot_config.py test_soul1_w5_observer_gates.py -q        → все зелёные
pytest tests/ -q -k "direct or initiative or tool or l1 or evidence or prompt
       or smartsearch or search or parity" -p no:randomly
                                        → 3777 passed, 13 failed (все пред-существующие)
```

13 падений (не мои, проверены `git status` — соответствующие файлы не менялись этой полосой): 5× `test_direct_fallback_recompose_asap32` (дрейф сигнатуры `_fallback_with_retries(sent=…)`), `test_mca11_money_limits_round1028::test_no_runtime_callers_off_parity` (упоминание `mca_money_limits` в `services/evidence_policy.py` волны 1 — файл закоммичен), `test_mca20_rework1_f1_f2::test_evidence_injection_stays_data_not_instructions` (FC-рендер экранирования `<evidence>`), 6× `summary_*` (включая известный по контракту §6.3 красный).

Новые/переписанные тесты этой полосы (по одному на обязательство):
`test_wave3_direct_reuse_two_turns_second_is_network_free`, `test_wave3_changed_version_still_does_new_fetch`, `test_wave3_reuse_requires_delivered_excerpt`, `test_wave3_explicit_recheck_bypasses_reuse`, `test_wave3_direct_sets_claim_keys_and_budget_before_tools` (AST), `test_wave3_call_budget_matches_pack_formula`, `test_wave3_delivered_chars_by_claim_are_per_claim`, `TestL1WindowLineBudget` (4), `test_corpus45_zero_invalid_skip_zero_unnecessary_search`, `test_corpus46_metrics_before_and_after_are_honest`, `test_repeat_dialog_reuses_and_background_summary_makes_no_call`, `test_wave5_*` (4).

### 11.6. Осознанные границы волн 3–5

1. **`fetch_article` schema** расширена аддитивно: `terms`, `section`, `offset`, `claim` (все опциональные). Роутер их уже понимал (`_article_terms`, `select_excerpt(section/offset)`, `_claim_keys`), поэтому схема теперь просто сообщает модели то, чем инструмент уже умел пользоваться; существующие тесты схем/роутера зелёные, `additionalProperties: false` сохранён.
2. **Инициатива**: `claim_keys` подключены, но `evidence_budget_chars` у неё остаётся `_l1.evidence_max_chars()` — в инициативном ходе нет композера L2 с `l2_input_budget`, считать per-call бюджет не из чего; это честная legacy-константа, а не «забыли».
3. **Reuse после рестарта** процесса пуст (in-memory LRU волны 2) — первый такой ход читает источник заново, как и записано в §3.3 контракта.
4. **`delivered_chars_by_claim`** привязывает доставку по сущности+версии/дате/метрике (текстовый матч канона `claim_key`), а не по source_id: источник, где нет названной версии, не подтверждает claim о версии. (Review-fix 5, §12.3: матч уточнён — по границам токена и только по внешним источникам.)
5. **Поисковый выжимка-лимит** (`{max_symbols}`) не переведён на динамическое окно: в каноне это «жёсткий потолок ответа», а не объём выборки; менять семантику канона без ТЗ — придумывать требование.

> Актуальные числа прогонов, состав тестов и уточнённые границы после ревью —
> §12 («Review-fix 5»). История §11 не переписана.

## 12. Review-fix 5 (01.11.2026): два блокера ревью волн 3-5

Ревью: `plans/features/evol/reports/w13-evidence-routing-review-waves3-5.md`
(Needs Fixes). Правки — минимальные, в тех же файлах; карта/acceptance не
трогались.

### 12.1. BLOCKER-1: reuse-ход молча отключал tool-фазу

Было: при найденном reuse-пакете `raw = None`, `_l1_tool_phase` не вызывался.
Следствие: `get_recent_history`/`query_chat_memory`/`dig_into_lore`/
`recognize_image`/`fact_check` не исполнялись и молчали: на «правда ли X, и что
мы про это говорили» Writer получал выдержку про X и выдумывал разговор.

Стало (контракт §3.4: reuse отдаёт тот же EvidenceSource, а не отменяет
инструменты):

1. `_l1_tool_subset` на reuse-ходе снимает ТОЛЬКО сетевые evidence-инструменты
   (`_EVIDENCE_TOOLS = {execute_web_search, fetch_article}`). Это не отказ
   capability, поэтому `capability_rejected` не эмитится — решение видно в
   `EVIDENCE_POLICY_DECIDED` (reason=`verified_reuse`) и `EVIDENCE_DELIVERY`
   (reused=1).
2. Tool-фаза исполняется всегда (`_handle_turn` больше не ставит `raw = None`).
3. Упаковка: reuse-выдержка и находки не-сетевых инструментов идут в ОДИН
   пакет одним бюджетом (`build_evidence_pack(..., prepend_sources=...)`),
   fair allocation/truncation считаются один раз.
4. `delivered_chars_by_claim` считает зачёт только по внешним источникам
   (`EXTERNAL_EVIDENCE_TOOLS`): пересказ чата не подтверждает внешний claim,
   иначе reuse продлевался бы историей разговора.
5. Инициативный путь (`generate_initiative_reply`) приведён к той же
   семантике: reuse-выдержка — база пакета, tool-фаза для не-сетевых
   инструментов исполняется.

### 12.2. BLOCKER-2: явная просьба перепроверить не отменяла reuse

Было: `_evidence_explicit_request.verify` брался только из
`temporal_factcheck.is_referential_claim`, поэтому существующий
`direct_capabilities.detect_action_intent` с `INTENT_FACT_CHECK` игнорировался.

Стало: `verify = (intent == INTENT_FACT_CHECK) or is_referential_claim(...)`.
Новых словарей фраз нет (§1.3), второго FC-пайплайна нет (§2.4: исполнитель —
web_search). Проверено поведение по фактическим формулировкам:

| формулировка | сигнал | reuse |
|---|---|---|
| «правда ли, что …» | `INTENT_FACT_CHECK` | снят (§1.2 п.2) |
| «проверь факт: …» | `INTENT_FACT_CHECK` | снят |
| «это правда?» | `INTENT_FACT_CHECK` | снят |
| «проверь это» | `INTENT_FACT_CHECK` + referential | снят |
| «фактчек: …» / «fact check …» | `INTENT_FACT_CHECK` | снят |
| «найди/поищи …» | `INTENT_WEB_SEARCH` | снят (как раньше) |

Не покрыто ни одним существующим детектором (см. 12.5 — вопрос PM/Architect):
«проверь заново …», «обнови данные про …», «перепроверь …», «проверь ещё
раз …», «актуальна ли инфа про …», «свежие данные про …».

### 12.3. Ложный зачёт доставки (п.10 ревью)

`delivered_chars_by_claim` матчил подстрокой: claim про `4.1` подтверждался
текстом `4.10`, дата `1 октября` — текстом `11 октября`. Теперь матч по
границам токена (`_token_in_text`): сущность — по границе слова, версия/дата/
метрика — с запретом соседней ЦИФРЫ (чтобы `4.1` внутри `deepseek v4.1 flash`
оставался валидным, а `4.10` — нет).

### 12.4. Тестовое доказательство (после правки)

```text
pytest tests/test_evol_evidence_routing.py tests/test_evol_evidence_window.py
       tests/test_evol_evidence_corpus.py -q -p no:randomly     → 134 passed
pytest tests/test_evol_fc_evidence_style.py tests/test_asap8_v6_wc_direct_d04.py
       tests/test_direct_chat.py tests/test_history_segments.py
       -q -p no:randomly                                        → 254 passed
pytest tests/ -q -p no:randomly -k "direct or initiative or tool or l1 or
       evidence or prompt or smartsearch or search or parity"
                                     → 3785 passed, 13 failed (те же пред-существующие)
```

13 падений — тот же набор, что в §11.5 (5× `test_direct_fallback_recompose_asap32`,
`test_mca11_money_limits_round1028::test_no_runtime_callers_off_parity`,
`test_mca20_rework1_f1_f2::test_evidence_injection_stays_data_not_instructions`,
6× `summary_*`); файлы этих тестов этой полосой не менялись.

Ставшие несущими тесты (было — тавтология):

1. `test_wave3_direct_reuse_two_turns_second_is_network_free` — ход доведён до
   tool-фазы на РЕАЛЬНОМ `ToolRouter`; сеть считается на границе сети
   (`_NetSearchSpy.search`, `_NetExtractorSpy.extract`) — оба счётчика 0, и
   сетевые инструменты не диспатчились.
2. `test_wave3_reuse_turn_still_runs_nonnetwork_tools` (новый) — сценарий
   владельца: reuse + `capabilities_needed=["web_search","chat_history"]`.
   Утверждает: `get_recent_history` реально исполнен (память вызвана, его
   источник есть в пакете), reuse-выдержка осталась в том же пакете, сеть — 0.
3. `test_wave3_chat_history_is_not_proof_for_external_claim` (новый) — история
   чата не засчитывает внешний claim (защита от вечного reuse).
4. `test_wave3_explicit_factcheck_phrases_cancel_reuse` (новый, 5 фраз) —
   required=True, `_evidence_reuse_pack is None`, запись удалена bypass'ом.
5. `test_wave3_delivered_chars_no_false_credit_on_version_prefix` (новый) —
   4.1 vs 4.10, «1 октября» vs «11 октября», rtx 5090 vs 50900; своя версия/дата
   по-прежнему засчитывается.
6. `test_wave3_call_budget_matches_pack_formula` — теперь равенство с формулой
   пакета (тот же измеритель, один резерв), а не «больше нуля»; плюс floor 300 и
   кэп 40% окна.
7. `test_corpus46_metrics_before_and_after_are_honest` — «до/после» различаются
   СОСТОЯНИЕМ хранилища (прогрев доставленных источников), а не просто вторым
   прогоном. Инвариант: `verified_fresh + verified_reuse + invalid_skip ==
   |claim-кейсы|` в обоих прогонах; разница равна числу прогретых claim'ов.
   Наблюдено: до `fresh=4, reuse=1`, прогрето 3, после `fresh=1, reuse=4`,
   `invalid_skip=0`, `unnecessary_search=0` в обоих.
7. `test_wave3_reuse_turn_has_no_raw_none_shortcut_in_handle_turn` (новый) —
   инвариант кода `_handle_turn`: нет `raw = None` и вызов `_l1_tool_phase` не
   стоит под условием «reuse-пакет найден» (защита от дрейфа: сам `_handle_turn`
   целиком по-прежнему не исполняется ни одним тестом — ~2000 строк с БД,
   Telegram и LLM).

Мутационные контрпримеры (разово, вне репозитория): снятие `_EVIDENCE_TOOLS`
ломает тест 1 (поиск реально уходит в сеть); `raw = None` ломает тест 2
(история не читается); подстрочный матч снова даёт ложный зачёт 4.1/4.10;
прежний сигнал verify (только `temporal_factcheck`) даёт False на «правда ли…».

### 12.5. Вопрос PM/Architect (нужно решение, не словарь)

Формулировки перепроверки, которых НЕТ ни в одном существующем детекторе
(`detect_action_intent` — `_FACTCHECK_MARKERS`/`_SEARCH_MARKERS`,
`temporal_factcheck.is_referential_claim`, `direct_execution._SEARCH_RE`), а
контракт §3.3 требует снимать reuse:

- «проверь заново, …»
- «обнови данные про …»
- «перепроверь, …»
- «проверь ещё раз, …»
- «актуальна ли инфа про …»
- «свежие данные про …»

Сейчас такие фразы дают reuse (если источник свежий) либо обычный `required`
по классу плана — то есть «перечитать источник» гарантирует только первый
вариант. Предложения (на выбор владельца контракта):
(а) расширить `_FACTCHECK_MARKERS` — прямо запрещено §1.3;
(б) один существующий маркер как класс «проверка факта» без нового словаря —
вопрос трактовки §1.3;
(в) сузить §3.3 до референтной проверки (описанное поведение) и зафиксировать
список фраз как «не гарантируется»;
(г) L1-план получает optional-поле «recheck: true» (как `external_claims`) —
новый детектор слов не нужен, решение принимает модель, runtime лишь применяет
bypass.

Рекомендация Builder: (г) — не нарушает §1.3, не добавляет словарей, снимает
требование §3.3 полностью; (в) — минимально и честно, если расширять контракт
не хотят.

Смежный вопрос того же класса (не блокер, поведение не хуже прежнего):
пользователь прислал ССЫЛКУ и спрашивает по claim'у, который уже покрыт
reuse. Политика (правило 9) всё равно решает reuse, поэтому `fetch_article`
на этом ходе не анонсируется — явная ссылка не читается. До review-fix 5 на
reuse-ходе не исполнялось НИЧЕГО, так что текущая правка строго расширяет
tool-фазу; но «явная ссылка сильнее reuse» контрактом не зафиксирована. Это
вопрос той же природы, что и список фраз: решать §1.2 п.2/§3.3 на уровне
политики, а не в `_l1_tool_subset`.



