# S4 (stage D) - независимое ревью кандидата `1a991e7d`

- **Эпик:** SMART-EXECUTION-RELIABILITY-01, slice **S4-CAPACITY**.
- **Кандидат кода:** `1a991e7d`; docs-коммит `f060241c`; база `d20a7f73`.
- **Worktree:** `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\SMART-EXECUTION-RELIABILITY-01-92d1db8aefb1-7df1e82b` (ветка `smart/d-capacity`).
- **Проверено:** `git diff 1a991e7d..f060241c -- services config tests` пуст: тесты и код ревью соответствуют именно `1a991e7d`; docs-коммит меняет только evidence-файл.
- **Контракт:** `architecture-contract-part2.md`, раздел D (S4); owner input `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`, ЭТАП D.
- **Требования карты:** `SXR-D1-01`, `SXR-D1-02`, `SXR-D1-03`, `SXR-D2-01`, `SXR-D2-02`, `SXR-D3-01`, `SXR-D3-02`, `SXR-D4-01`, `SXR-D5-01`, `SXR-D6-01`.
- **Вердикт:** **Needs Fixes** - один блокирующий regression в существующем тесте LLM-клиента; остальное по этапу D подтверждено на этом кандидате.

## 1. Блокирующая находка

### B1. Кандидат оставляет красным существующий `tests/test_llm_client.py`

- **Требование/инвариант:** D6 не должен ломать существующий контракт ошибок LLM-клиента; релизный кандидат обязан оставлять тестовый набор зелёным.
- **Где:** `services/llm_client.py`, `_context_overflow_exc`; сообщение нового исключения формируется как `LLMContextOverflowError(f"LLM context overflow ({status}): {err}")`. Существующий тест `tests/test_llm_client.py:1126` ожидает прежний текст `LLM HTTP 400: https://api.test/v1/chat/completions`.
- **Воспроизведение (точный кандидат):**
  ```
  python -m pytest -q -p no:cacheprovider tests/test_llm_client.py::TestEpic49DiagnosticLog::test_final_400_logs_diagnostics
  ```
  Наблюдалось: `1 failed, 114 passed`; `assert 'LLM context overflow (400): ...' == 'LLM HTTP 400: ...'`. На базе `d20a7f73` тот же тест: `1 passed`.
- **Влияние:** файл `test_llm_client.py` не входил в заявленные наборы 34/280/475, поэтому regression не был замечен Builder'ом. Помимо красного теста, меняется текст исключения для всех context-overflow 400; внешние потребители/логи, сопоставляющие `str(exc)`, получают другое значение.
- **Минимальная коррекция (Builder):** либо сохранить исходный текст исключения (`LLM HTTP {status}: {url}`) и оставить типизацию/поля `context_info`/`context_recovery`, либо осознанно обновить тест под новый контракт и добавить assert `isinstance(exc, LLMContextOverflowError)`. Предпочтительно сохранить текст и добавить один интеграционный тест реального `_post`/`generate_with_metadata` с 400 + context-body: сейчас сквозная связка "HTTP 400 -> typed overflow -> recovery plan" покрыта только helper'ом `_context_overflow_exc` и тест-двойником Writer'а.
- **Проверка после фикса:** указанный тест, весь `tests/test_llm_client.py`, затем `test_capacity_stage_d_smart.py` (34) и набор 280.
- **Владелец:** Builder.

## 2. Неблокирующая находка (latent, BACKLOG_ONLY)

### N1. Инвалидация proven-limit чувствительна к написанию ID модели

- **Факт:** `record_proven_limit` инвалидирует `_CACHE` через `invalidate_runtime_capacity`, сравнивая model как raw lower-string; `proven_limit_for` при этом использует `normalize_model_id` (basename, namespace/suffix). При разных написаниях cache может затенять proven limit.
- **Воспроизведение (in-process probe на кандидате):** каталог NanoGPT отдал `z-ai/glm-5.3-flash-uncensored` -> 1 048 576; `resolve_capacity` закэшировал это; затем `record_proven_limit(base, "glm-5.3-flash-uncensored", 131 072)`; повторный `resolve_capacity(base, "z-ai/glm-5.3-flash-uncensored")` вернул `provider_catalog 1048576`, а не `proven_limit 131072` (short-ID запрос возвращает `proven_limit 131072`).
- **Оценка:** текущие production-вызовы (`llm_client` и summary supervisor) передают то же написание, что и cache-key, поэтому сейчас это latent edge, а не пользовательский отказ. Но D2/D3 требуют нормализации alias/namespace; при следующем касании `record_proven_limit`/`invalidate_runtime_capacity` стоит сравнивать `normalize_model_id` и добавить regression-тест с full-ID/short-ID. Тест `test_proven_limit_invalidates_cached_planning_window` покрывает только одинаковое написание.

## 3. Acceptance ledger (по проверенному кандидату)

| ID | Статус | Доказательство |
|---|---|---|
| SXR-D1-01 | VERIFIED | Заводское 1M; env `0`/`500`/`garbage` -> 1M (отдельный прогон); base RED: `settings=16384`, `resolve=16384`; `test_factory_unknown_window_is_1m_not_16384`, `test_unknown_window_helper_never_falls_back_to_16384`, sync/async/legacy/evidence тесты. Явно заданный env `16384` - это конфигурация владельца, не fallback. |
| SXR-D1-02 | VERIFIED | `estimated_unknown`/`estimated` в async; `estimated`-флаг в `model_slots`; `REASONS_RU`; тесты 34/280. Предзаполнения контекста/памяти нет. |
| SXR-D1-03 | VERIFIED | Точные записи `MODEL_EXACT_WINDOWS` сохранены; семейные префиксы больше не определяют ёмкость (это прямо требует D2/D3). Следствие: `deepseek-v4.1-flash` до каталога - 1M estimated, честно помеченный; это не замена точной записи, а отказ от family-guess. |
| SXR-D2-01 | VERIFIED | `CapacityResult` учитывает provider/base_url/route/exact ID/runtime/catalog/verified cache/override; NanoGPT/OpenRouter/DeepSeek/llama.cpp/Ollama/vLLM адаптеры. |
| SXR-D2-02 | VERIFIED (с residual N1) | Precedence proven -> override (clamped) -> runtime -> catalog -> cache -> exact registry -> 1M реализован; conflict-поля `override_value`/`clamped_by_proven_limit`; override не помечен verified; family-guess отсутствует. N1 - latent-край для будущих вызовов, текущие пути используют одно написание. |
| SXR-D3-01 | VERIFIED | `_adapter_nanogpt_catalog` + `catalog_item_for_model`: exact ID, namespace/suffix/alias, ambiguous basename = miss, catalog miss -> 1M/registry; тесты 34. |
| SXR-D3-02 | VERIFIED | Выдуманной записи `glm-5.3*` в registry нет (`_registry_exact_window` -> None); универсальный путь работает для смены моделей. |
| SXR-D4-01 | VERIFIED | Direct primary/fallback - отдельные async-бюджеты (`direct.primary`/`direct.fallback`); tool_router/search/orchestrator берут `_chat_model`+`_base_url`; L1 fallback - отдельный sync exact-registry (`gpt-4` 8192); primary не занижается. Остаточный риск: L1 fallback для catalog-only маленькой модели sync-путём даст 1M (не проверено live; не блокер этого среза). |
| SXR-D5-01 | VERIFIED | `settings.py` diff - только `CHAT_UNKNOWN_MODEL_WINDOW` и комментарии; бюджетные ключи не тронуты; `test_capacity_budget_keys_untouched`, `test_budgets_off_uses_full_window_minus_reserves`, `test_recovery_budget_separates_window_and_output`. |
| SXR-D6-01 | UNVERIFIED / Needs Fixes | Механика `note_context_overflow`/`ContextRecoveryPlan`/L2 recompose/`<Tool_Evidence>`/bounded attempt покрыта тестами 34 и Writer; но реальная связка `_post` HTTP 400 -> `LLMContextOverflowError` оставляет красным `test_final_400_logs_diagnostics` (B1), а сквозной интеграционный тест отсутствует. После B1 - повторная проверка. |

**REVIEW-ready сейчас:** D1-01, D1-02, D1-03, D2-01, D2-02 (с N1), D3-01, D3-02, D4-01, D5-01. **Не REVIEW-ready:** D6-01 до фикса B1.

## 4. Проверки: выполнено vs переиспользовано

Выполнено на точном кандидате (`f060241c`, код = `1a991e7d`), venv `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, Python 3.12:

| Проверка | Результат |
|---|---|
| `tests/test_capacity_stage_d_smart.py` | **34 passed** |
| 11 файлов capacity/context/evidence (как в binding, раздел 3) | **280 passed** |
| 14 файлов D6/Writer/инспектор/Direct (как в binding, раздел 3) | **475 passed** |
| `tests/test_llm_client.py` | **114 passed, 1 failed** (B1) |
| `tests/test_summary_supervisor_asap41.py`, `test_summary_wave8_supervisor_runs_asap41.py`, `test_llm_completion_metadata_ur18.py`, `test_llm_circuit_breaker.py`, `test_llm_react_asap31.py` | **91 passed** |
| `test_asap7_direct_l1.py`, `test_mca23_response_plan.py`, `test_summary_coverage_ledger_asap41.py`, `test_tool_router.py` | **131 passed** |
| `test_asap42_step2c_image_capacity.py`, `test_asap44_cover_final_closure.py`, `test_asap7_cover_fix.py` | **85 passed** |
| base RED probe `d20a7f73` | `settings=16384`, `resolve unknown=(16384,'unknown_fallback')`, `evidence=(16384,...)`, нет `LLMContextOverflowError`/`note_context_overflow`/`MODEL_EXACT_WINDOWS`; файла stage-D тестов нет |
| mutation: игнорировать route в `_cached_verified_window` | тест route-scope **failed** (`provider_catalog 202752` унаследован чужим route), после `git checkout` - **passed** |
| независимый probe: env 0/garbage/500 | все -> 1M; явный env 16384 -> 16384 (конфигурация, не fallback) |

Широкий `-k "capacity or context"` по всему `tests/` был запущен, но оборван перезапуском backend OpenCode до результата; **не заявляется**. Заявленные 34/280/475 подтверждены, сверх них найден B1.

Diff-аудит: 26 файлов = 1 `config/settings.py`, 10 сервисов, 1 evidence, 14 тестов. Новых budget-ключей, DDL, БД или отдельного store нет; `_PROVEN_LIMITS` - process-local dict. Все вхождения `16384` вне тестов классифицируются как: комментарии; `direct_execution.ORCHESTRATOR_STEPS_WINDOW_DIVISOR` (делитель шагов, не окно); `mca_vision.OUTPUT_TOKEN_THINKING_DEFAULT` и `response_extent._MAX_OUTPUT_TOKENS_CEILING` (max_output); подтверждённые runtime/exact-registry значения в тестах (например, llama.cpp 16384). Дефолтного окна 16384 больше нет.

## 5. Что остаётся postdeploy / не проверено

- Живой каталог NanoGPT: реальные `context_length`/`max_output_tokens` для `z-ai/glm-5.3-flash-uncensored`, доступность `detailed=true`, поведение при смене модели.
- Production effective values: env/hot `CHAT_UNKNOWN_MODEL_WINDOW`, `CHAT_MODEL_CONTEXT_WINDOW`, `models.chat_context_window_override`, слоты, fallback model/base_url, kill-switch'и резолвера. В тестах сеть замокана.
- Реальный context-overflow от провайдера: один recovery-цикл, сохранение tool evidence, отсутствие миллионного probe, `capacity_proven_limit_total`/`MODEL_CAPACITY_*` события, инвалидация кэша в живом процессе; `_PROVEN_LIMITS` process-local и сбрасывается рестартом - это осознанное ограничение.
- L1 fallback с маленькой catalog-only моделью (sync-путь) и реальный fallback-recompose.
- B1 и N1 не закрыты; эпик DONE не отмечать, карту/scope не править.

## 6. Housekeeping

- Worktree кандидата `...7df1e82b` **сохраняется** для Builder/Reviewer/Orchestrator (не интегрирован в релизную линию).
- Временный run `WorkspaceData/runs/.../probe-6bd67dccc5` закрывается `run-close` после записи отчёта; исходный код не менялся (`git status` чист).

## 7. Handoff: три опоры доказательств

- **Implementation:** проверены `services/model_capacity.py` (`_unknown_window`, `resolve_model_context_window`, `_resolve_uncached`, `_cached_verified_window`, `record_proven_limit`, `note_context_overflow`, `recovery_budget_tokens`, `fallback_window_for_model`), `config/settings.py` (только `CHAT_UNKNOWN_MODEL_WINDOW`), `services/llm_client.py` (`LLMContextOverflowError`, `_context_overflow_exc`), `services/direct_chat_service.py` (L2 recovery), `services/summary_llm_supervisor.py`, `services/tool_router.py`, `services/search_service.py`, `services/auto_budget.py`, `services/direct_execution.py`.
- **Test validity:** прочитаны assertions 34 stage-D тестов и изменённых тестов; 34/280/475 зелёные; base RED подтверждён; mutation route-scope дала красный и восстановилась; существующий `test_llm_client.py` дал красный (B1), то есть тестовый набор не является полностью зелёным.
- **Independent challenge:** (1) реальный HTTP 400 с context-body через существующий `test_llm_client.py` -> изменение текста исключения и падение теста (B1); (2) in-process probe с full-ID cache и short-ID proven limit -> cache затеняет proven (N1, latent); (3) env 0/garbage/500 -> 1M.
