# S4 (stage D) — единый capacity contract: привязка к кандидату

- **Epic:** SMART-EXECUTION-RELIABILITY-01, slice **S4-CAPACITY** (stage D).
- **Кандидат кода:** `1a991e7d` (ветка `smart/d-capacity`), база `d20a7f73`
  (production 2.58.199). Линия коммитов: `6fe1a708` → `e4be5f98` →
  `4a2b4b34` → `8210eb7b` → `1a991e7d`.
- **Предыдущие привязки:** `evidence/binding-d-4a2b4b34.md` (матрица строк/
  тестов кандидата `4a2b4b34` сохранена ниже) и `evidence/binding-d-8210eb7b.md`.
  `8210eb7b` добавляет уточнение контракта D2 (route в области кэшированного
  значения) и его тест; `1a991e7d` — только удаление лишней пустой строки в
  конце `services/model_capacity.py` (код не меняется, те же прогоны).
- **Контракт:** `architecture-contract-part2.md` §D (S4) → assignment п.1;
  owner input `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`
  (ЭТАП D).
- **Требования карты:** `SXR-D1-01`, `SXR-D1-02`, `SXR-D2-01`, `SXR-D2-02`,
  `SXR-D3-01`, `SXR-D4-01`, `SXR-D5-01`, `SXR-D6-01`.
- **Docs-коммит:** этот файл (`git log -- plans/features/smart-execution-reliability-01/evidence`).
- **Ре-верификация 14.11.2026 (сессия восстановления после перезапуска
  backend OpenCode):** прогоны выполнены на дереве `8210eb7b` из
  `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (Python 3.12.0),
  `-p no:cacheprovider`, рабочая директория — этот worktree. Перезапуски
  backend'а случались во время сессии, но не меняли ни файлы worktree, ни
  результаты уже завершённых прогонов (повторные прогоны совпали).

## 1. Что изменено в поведении

| Требование | Наблюдаемое поведение | Где |
|---|---|---|
| D1 | Заводское `CHAT_UNKNOWN_MODEL_WINDOW = 1_000_000`. Ни один путь резолва не возвращает `16384`: sync (`resolve_model_context_window`, `resolve_evidence_window_tokens`), async (`resolve_capacity`), legacy-контур kill-switch OFF, fallback-модель. Отсутствие/ноль/ошибка кастования → 1M. | `config/settings.py`, `services/model_capacity.py` |
| D1-02 | 1M помечается `source=estimated_unknown`/`unknown_fallback`, `confidence=estimated`; это планировочная оценка: память заранее не выделяется, контекст не заполняется (нет кода предзаполнения). В слотах и аналитике видна как `estimated`. | `model_capacity.py`, `model_slots.py`, `pipeline_analytics.py` |
| D2-01/02 | Один резолвер, precedence: `proven_limit` → `developer_override` (планирование, обрезается пределом) → `runtime` → `provider_catalog` → verified cache того же endpoint/model/route → exact registry → 1M estimated. Override не отменяет предел: видны `override_value`, `clamped_by_proven_limit`, effective = предел. Override не помечается provider-verified (`confidence=override`). Семейные префиксы ёмкость не определяют. | `model_capacity.py` (`_resolve_uncached`, `CapacityResult`) |
| D2-route (8210eb7b) | Синхронный потребитель (`resolve_evidence_window_tokens`) видит подтверждённое значение только своей пары endpoint+model+route: запись, посчитанная для `route="image_edits"`, не наследуется chat/tool-путём (и наоборот). | `model_capacity.py` (`_cached_verified_window`) |
| D3 | `z-ai/glm-5.3-flash-uncensored` резолвится только существующим `_adapter_nanogpt_catalog` по точному ID (`catalog_item_for_model`: namespace/suffix/alias; неоднозначный basename = честный miss). Записи `glm-5.3*` в реестре НЕТ. Кэш ключуется provider/base_url/model/route/override → смена модели резолвится заново. | `model_capacity.py` |
| D4 | Окно считается для фактически назначенной модели: tool-loop (`tool_router._evidence_window`), агрегатор поиска (`search_service`), orchestrator (`direct_execution`), Direct primary/fallback, L1, Summary L1/L2, slots. Primary не занижается окном fallback заранее; fallback получает свой бюджет и recompose при фактическом переходе. | `tool_router.py`, `search_service.py`, `auto_budget.py`, `direct_execution.py`, `direct_chat_service.py` |
| D5 | Окно, token budget и `max_output` — разные величины (`output_reserve_tokens`, `compute_available_budget`, `capability_aware_output_reserve`, `recovery_budget_tokens`); при budgets OFF доступно окно минус protocol/output reserve. Бюджетные ключи `settings.py` не тронуты (в diff только capacity-ключ `CHAT_UNKNOWN_MODEL_WINDOW` и комментарии). | `model_capacity.py`, `auto_budget.py`, `config/settings.py` |
| D6 | Структурированный разбор context-overflow (code/body/text) → запись `proven_limit` + инвалидация кэшей endpoint/model + план ограниченного восстановления (1 попытка). Summary supervisor обновляет ёмкость и эмитит честное событие. L2 Writer пересобирает payload под доказанный предел существующим L2-репаком (защищены запрос и tool evidence), отправляет ОДИН раз, обновляет prepared-вариант (receipt/инспектор видят реально отправленное тело). Нет миллионного probe, нет 16384, нет бесконечных платных повторов. | `llm_client.py`, `model_capacity.py`, `summary_llm_supervisor.py`, `direct_chat_service.py` |

## 2. RED на базе `d20a7f73`

Один и тот же скрипт на чистом worktree базы (`2-58-199-train-…`, HEAD `d20a7f73`):

```
BASE settings.CHAT_UNKNOWN_MODEL_WINDOW = 16384
BASE resolve unknown -> (16384, 'unknown_fallback')
BASE evidence window unknown -> (16384, 'unknown_fallback')
BASE has LLMContextOverflowError: False
BASE has note_context_overflow: False
BASE has MODEL_EXACT_WINDOWS: False
```

GREEN на `4a2b4b34`:

```
BRANCH settings.CHAT_UNKNOWN_MODEL_WINDOW = 1000000
BRANCH resolve unknown -> (1000000, 'unknown_fallback')
BRANCH evidence window unknown -> (1000000, 'unknown_fallback')
BRANCH glm-5.3 exact registry entry: None      # выдуманной записи нет
BRANCH LLMContextOverflowError: True
BRANCH note_context_overflow: True
```

Durable RED→GREEN: `tests/test_capacity_stage_d_smart.py` отсутствует на базе,
каждый его тест утверждает новое наблюдаемое поведение (1M/estimated, точный
NanoGPT ID, precedence, bounded recovery). D6-тесты Writer'а
(`tests/test_ur_d_writer.py::TestContextOverflowRecovery`) на базе невозможны:
`LLMContextOverflowError`/`ContextRecoveryPlan` не существуют.

RED для инкремента `8210eb7b` (проверено пробой на базовом worktree
`2-58-199-train-…`, HEAD `d20a7f73`): в базовом `services/model_capacity.py`
нет ни `UNKNOWN_WINDOW_DEFAULT`, ни sync-кэша подтверждённой ёмкости
(`_cached_verified_window` отсутствует), т.е. route-скоуп кэша физически
нечего ограничивать; на кандидате helper есть и сравнивает
provider+host+model+route.

## 3. Тесты (точные прогоны на `1a991e7d`)

| Набор | Результат |
|---|---|
| `tests/test_capacity_stage_d_smart.py` | **34 passed** |
| capacity/context/evidence (11 файлов: `test_capacity_resolver_asap31`, `test_capacity_nanogpt_asap32`, `test_direct_context_capacity_asap3`, `test_direct_context_composer_asap3`, `test_auto_budget_asap31`, `test_summary_capacity_asap41`, `test_summary_coverage_asap31`, `test_bgs05_budgets`, `test_evol_evidence_window`, `test_er08_limits_context`, `test_capacity_stage_d_smart`) | **280 passed** |
| D6/Writer/инспектор + остальные Direct/инспекторские (14 файлов: `test_ur_d_writer`, `test_direct_chat`, `test_ur_f_inspector_step1`, `test_ur_f_inspector_step2`, `test_capacity_stage_d_smart`, `test_direct_chat_handlers`, `test_direct_chat_concurrency`, `test_direct_llm_decision_asap32`, `test_asap8_v6_wc_direct_d03`, `test_migrate_direct_chat_v2_script`, `test_rc_direct_self_correction`, `test_soul1_direct_prompt_reads`, `test_asap7_direct_settings`, `test_ur_ui_effective_config`) | **475 passed** |
| те же две группы порознь (проверка привязки счётчиков к неизменному дереву `4a2b4b34`) | **293 passed** (5 файлов) и **181 passed** (9 файлов) |
| UR/Direct волна (17 файлов: `test_ur_context_selection`, `test_ur_b_live_wiring`, `test_ur_turn_engine`, `test_ur_g_acceptance`, `test_ur_e_speech`, `test_ur_c_clock`, `test_ur_bot_output_history`, `test_direct_context_scenarios_asap3`, `test_direct_decision_matrix_asap3`, `test_direct_l1_corrective_r1`, `test_direct_l1_l1d_contract`, `test_direct_chat_lore_inject`, `test_direct_chat_relations_inject`, `test_direct_chat_prompts`, `test_asap7_direct_l1`, `test_asap8_v6_wc_direct_d04`, `test_asap8_v6_wc_direct_matrix`) | **346 passed** |
| `-k "capacity or context"` по всему `tests/` | **961 passed**, 3 failed (pre-existing, см. §5) |

Порядок прогонов 14.11.2026 (кандидат): на дереве `4a2b4b34` —
**33 / 279 / 293 / 181 passed**; затем `8210eb7b` (route-скоуп кэша + его
тест) — **34 / 280 / 475 passed** и отдельно повторённые **293 / 181**
(совпали с прежними, новых падений нет). На финальном дереве `1a991e7d`
(удалена только пустая строка в конце файла) наборы **280** и **475**
повторены и совпали. Широкий `-k "capacity or context"` в сессии
восстановления дважды стартовал и оба раза был оборван перезапуском backend
OpenCode до завершения, поэтому его повторный результат не заявляется: в силе
остаётся первичный прогон из строки выше и разбор pre-existing падений в §5.
Перезапуски backend'а не меняли ни один файл worktree (дерево проверено
`git status` после каждого).

Границы diff'а по настройкам проверены отдельно: `git diff d20a7f73..HEAD --
config/settings.py` содержит только ключ `CHAT_UNKNOWN_MODEL_WINDOW`
(16384 → 1 000 000) и комментарии; бюджетные ключи (`CHAT_CONTEXT_BUDGET_TOKENS`,
`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`, `CHAT_BUDGET_RESERVE_RATIO`)
не изменены — это же утверждает `test_capacity_budget_keys_untouched`.

Что именно утверждают ключевые тесты:

- `test_factory_unknown_window_is_1m_not_16384`, `test_unknown_window_helper_never_falls_back_to_16384`
  — заводское значение и helper никогда не дают 16384 (в т.ч. при 0/мусоре env).
- `test_async_resolver_unknown_is_estimated_not_verified` — `source=estimated_unknown`,
  `confidence=estimated`, окно 1M.
- `test_nanogpt_exact_id_resolves_after_namespace_strip`, `…_suffix_variant`,
  `test_nanogpt_ambiguous_basename_is_honest_miss`, `test_nanogpt_catalog_miss_does_not_fabricate_entry`
  — точное сопоставление ID, выдуманных записей нет.
- `test_family_name_never_defines_capacity` — `glm-4` не даёт ёмкость `glm-5.3-*`.
- `test_model_switch_refreshes_capacity` — смена модели на том же endpoint даёт новое значение.
- `test_proven_limit_beats_catalog_and_caps_override` — предел сильнее каталога и override;
  конфликт виден (`override_value`, `clamped_by_proven_limit`).
- `test_override_below_proven_limit_stays_owner_choice` — override ниже предела остаётся решением владельца.
- `test_verified_cache_used_by_sync_tool_path` — sync-путь видит подтверждённую ёмкость
  того же endpoint; чужой endpoint её не наследует.
- `test_cached_verified_window_scope_includes_route` (`8210eb7b`) — значение,
  посчитанное для другого route того же endpoint/model, sync-путём не
  наследуется; своя route-запись и route-less запись видны только своим путям.
- `test_proven_limit_invalidates_cached_planning_window` — предел сбрасывает уже
  посчитанное планировочное окно (регистр ID не важен).
- `test_primary_chain_not_shrunk_by_small_fallback` — primary не занижается fallback'ом.
- `test_budgets_off_uses_full_window_minus_reserves` — при OFF доступно полное окно минус reserves.
- `TestContextOverflowRecovery::test_l2_recomposes_once_under_proven_limit` — L2 Writer:
  ровно два вызова (`l2_writer` → `l2_recovery`), payload короче, `<Tool_Evidence>` сохранён.
- `TestContextOverflowRecovery::test_l2_without_recovery_plan_does_not_retry` — без раскрытого
  предела второго платного вызова нет; ошибка остаётся вызывающему.
- `test_outbound_model_calls_inventory_is_classified` (инспектор) — новый исходящий вызов
  классифицирован (`covered:l2_writer`), ручных маркеров доставки по-прежнему нет.
- `test_context_overflow_structured_json_updates_capacity`, `…_text_only_is_parsed`,
  `test_context_overflow_without_limit_is_uncertain_not_16384`,
  `test_context_overflow_recovery_is_bounded`, `test_recovery_budget_separates_window_and_output`,
  `test_llm_client_context_overflow_error_carries_recovery` — механика D6 в резолвере и клиенте.
- `test_capacity_budget_keys_untouched` — бюджетные ключи настроек не переименованы/не удалены.

Тесты, опиравшиеся на удалённый 16384-fallback, получили **подтверждённое**
маленькое окно (runtime-metadata / exact-реестр / явный window-source), при
этом проверяемая семантика сохранена: `test_summary_coverage_asap31`,
`test_direct_fallback_recompose_asap32`, `test_er08_limits_context`,
`test_ur_f_inspector_step1`.

## 4. Effective configuration

| Параметр | Значение в тестовой среде | Источник/приоритет в production |
|---|---|---|
| `CHAT_UNKNOWN_MODEL_WINDOW` | 1 000 000 (заводское) | env → ClassVar; заводское 1M |
| `MODEL_CAPACITY_RESOLVER_ENABLED` | ON (маркер `asap31`) | env-only kill-switch, default ON |
| `CHAT_MODEL_CONTEXT_WINDOW` | не задан (тесты) | env override; ниже `proven_limit` |
| `models.chat_context_window_override` | не задан | hot-слой чата; планирование, обрезается пределом |
| `AUTO_BUDGET_RESOLVER_ENABLED` | ON | env; OFF → legacy-контур с 1M unknown |

Тесты выполнены с ON-дефолтами резолвера; OFF-паритет покрыт отдельными тестами
kill-switch (`test_legacy_killswitch_unknown_window_is_1m`, `test_evol_evidence_window`).
Production-значения (env/hot/каталог) не сверялись с живым процессом — это шаг
деплой-проверки, а не доказанное здесь состояние.

## 5. Pre-existing failures (проверено на базе `d20a7f73`)

- `-k "budget or evidence or tool_router"`: **15 failed — идентичный список на
  базе и на кандидате** (`test_budget_*_round1024`, `test_mca20_rework1_f1_f2`,
  `test_meme_pipeline_stages::test_stage_b_instruction_carries_exact_j_budget`,
  `test_direct_fallback_recompose_asap32::TestGenerateChatRecompose`). Кандидат
  добавил 4 проходящих теста, ни одного нового падения.
- `-k "summary"`: 7 падений воспроизводятся на базе побайтно
  (`test_summary_generator::TestEpic60RunningSummary` ×2,
  `test_summary_two_call_round1022` ×3,
  `test_verbilizer_response_modes_round1023::…kill_switch_off_prev_narrator`,
  `test_webapp_dm_ui::…dm_positive_ids_behavioral`).
- Два падения в этой выборке (`test_summary_coverage_ledger_asap41::…honest_degraded`,
  `test_summary_source_window_asap41::…single_point_writes_and_logs`) —
  order-dependent: изолированно проходят; полный прогон той же выборки на базе
  завершился `pytest-timeout` (нестабильность тестовой базы, не кандидата).

## 6. Что не доказано этим кандидатом

- **Живой каталог NanoGPT** не вызывался: сеть замокана (`_http_get_json`
  двойник). Поля `context_length`/`max_output_tokens` взяты из документации,
  зафиксированной в коде; фактический ответ прод-каталога проверяется после деплоя.
- **Production effective values** (env/hot-override/каталог) не сверялись с
  работающим процессом.
- **Same-model recovery для промежуточных tool-раундов** не добавлялся: там
  работает существующая fallback-лестница `chat_with_tools` с recompose.
  D6 замкнут для L2 Writer (финальная проза) и Summary supervisor.
- **Стоимость recovery** ограничена числом вызовов (≤1 дополнительный), не
  измерена в деньгах/латентности.

## 7. Побочные находки (BACKLOG_ONLY, вне scope)

1. `tests/test_direct_fallback_recompose_asap32.py` — 5 падающих на базе тестов
   `TestGenerateChatRecompose` (pre-existing, см. §5).
2. `services/direct_execution.py: ORCHESTRATOR_STEPS_WINDOW_DIVISOR = 16384` —
   делитель числа шагов адаптивной цепочки, не окно контекста.
3. `response_extent._MAX_OUTPUT_TOKENS_CEILING = 16384` и
   `mca_vision.OUTPUT_TOKEN_THINKING_DEFAULT = 16384` — величины `max_output`,
   а не окна контекста (D5 разделяет величины).

## 8. Housekeeping (retained, не disposable)

- Worktree `WorkspaceData/worktrees/c742e4de9e92c489/SMART-EXECUTION-RELIABILITY-01-92d1db8aefb1-7df1e82b`
  (ветка `smart/d-capacity`, кандидат `1a991e7d`) **сохраняется**: он не
  интегрирован в релизную линию и является точным кандидатом независимого
  ревью. Owner — Builder S4-CAPACITY; потребитель — Reviewer/Orchestrator;
  следующее событие — после вердикта Reviewer и интеграции в релизный поезд
  SMART закрыть обычным `unit-close`.
- Одноразовые артефакты сессии (лог прерванного широкого прогона) лежат вне
  репозитория, в `WorkspaceData/runs/`, и закрываются `run-close`; в git они
  не попадают.
