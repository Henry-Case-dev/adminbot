# audit.md — T-4051: инвентаризация четырёх понятий бюджета и budget-путей

- **Задача:** T-4051 [MECH]. Код НЕ меняется этим артефактом. Baseline: HEAD `ffbad8` (прод 2.58.36, `c5cb5a9`), чужой WIP (mca-04b, node_modules, metrics.md/workflow_state.md) не тронут.
- **Источник:** spec.md (SHA-256 `CC419781…D33ED` verified), current_task.md 6067–9922 (SHA-256 `D6AD5DFB…AF2EB` verified), ADR-1028-3.

## Карта «сущность → файл → проблема → задача»

### (1) `budgetsUnlimitedKeys()` — 7 объединённых ключей (§1, §17)
- **Файл:** `web/app.js:4751–4826` (`budgetsUnlimitedKeys`, `budgetsUnlimitedActive`, `toggleBudgetsUnlimited`); UI в `web/index.html` (~855–865).
- **Семантика:** один тумблер «Безлимит по этому чату» пишет per-chat `-1` во ВСЕ 7 ключей: `limits.chat_global_key_budget_requests`, `limits.chat_global_key_budget_tokens`, `limits.worker_daily_llm_calls_per_chat`, `limits.worker_daily_llm_tokens_per_chat` (quota-класс), `limits.chat_global_context_max_tokens`, `limits.chat_thread_max_tokens` (context-каналы), `limits.chat_context_budget_tokens` (context policy). OFF пишет явные global-значения.
- **Проблема:** смешивает 3 сущности: суточные квоты, фоновые worker-лимиты, context policy (§17: «Это разные сущности»).
- **Задача:** T-4061 (разводка: Context Policy = только `chat_context_budget_tokens`; «Без суточных квот» = 4 quota-ключа; `chat_global_context_max_tokens`/`chat_thread_max_tokens` уходят из обоих), миграция §51 non-destructive, kill-switch `UI_BUDGETS_SPLIT_ENABLED`.

### (2) `services/model_capacity.py` — fallback 16384 (§1, §3, §8)
- **Файл:** `services/model_capacity.py:41–176` (карта `MODEL_CONTEXT_WINDOWS` префикс-матчем longest-prefix, env `CHAT_MODEL_CONTEXT_WINDOW` = приоритет 1, `CHAT_UNKNOWN_MODEL_WINDOW` 16384 fallback + однократный WARN; процесс-кэш `_WINDOW_CACHE` без инвалидации; `resolve_effective_window` = preemptive `min(primary, fallback)`).
- **Проблема:** unknown-модель молча получает 16384 как «нормальный путь» (§8 запрещает); env — нормальный путь (§4: override — escape hatch); preemptive-min сужает бюджет primary заранее, recompose по факту нет (§14).
- **Потребители:** `services/direct_chat_service.py:198–201, 2718–2747` (`resolve_effective_window` → `compute_available_budget` → `apply_budget_policy`); `services/direct_context_composer.py:32–35, 611–631` (`emit_context_capacity` c `window_source`).
- **Задача:** T-4053/T-4054 (перепись: precedence override → runtime → provider_catalog → registry → fallback; TTL-кэш; `MODEL_CAPACITY_FALLBACK`; события), T-4057 (fallback recompose).

### (3) `services/summary_hybrid_budget.py` — арифметика 30000→21001 (§75)
- **Файл:** `services/summary_hybrid_budget.py:50` (`HYBRID_CONTEXT_TOKEN_DEFAULT = 30000`), `:57–128` (`resolve_hybrid_context_budget` → `hybrid_input_budget` = `safe_budget(limit) − tokens(system) − markers − reserve`); `services/summary_l1_clusterizer.py:569–577` (`resolve_l1_budget`), `:721–787` (`run_l1`: `pack_l1_input` → truncation → `L1 truncated input | skipped=N | kept=M | limit=21001` в `:783–787`).
- **Арифметика (Q4):** `int(30000/1.15) = 26086` (safe_budget, `models.token_safety_multiplier`) − tokens(L1 system prompt ≈1085) − `SUMMARY_L1_OUTPUT_RESERVE_TOKENS = 4000` = **21001**. Capacity выбранной L1-модели НЕ участвует.
- **Примитив:** `estimate_and_split` (`:158–210`, overlap=1, последнее сообщение неприкосновенно) — база chunker'а.
- **Задача:** T-4069 (Auto-семантика: `0/null/untouched-default` → capacity от слота `summary.l1`), T-4070 (lossless chunking), T-4071 (coverage, убрать `skipped`).

### (4) REACT-классификатор + точка врезки LLM (§30)
- **Файл:** `services/direct_chat_service.py:619–750` (`ACTION_REACT`; детерминированные наборы `_REACTION_SETS_BY_CLASS` = `{😂,🤣}/{👍,👌}/{👍,👌,❤️}` + `_REACTION_DOUBT_SET` `{🤨,🤔}`; `_stable_reaction_pick` stable-hash по message_id; `_reaction_for_class`), kill-switch `flags.chat_decision_reactions_enabled` (`:1457–1466`).
- **Точка врезки:** короткое замыкание REACT в `handle()` (`~1715–1752`): reaction отправляется БЕЗ LLM-вызова (`react_moai`/`react`). LLM-врезка: не делать шорт-кат, идти в Stage-1 (тот же вызов, что генерирует ответ) и получать reaction из structured output; невалидно → `_reaction_for_class`. SILENT→🗿 (`:762–767` `silent_ack_enabled`, `REACTION_MOAI = "🗿"` `:627`) — не трогается. Force-гейт (`_resolve_direct_trigger`, `:789+`, приоритет 1) — выше матрицы.
- **Задача:** T-4078/T-4079 (kill-switch `DIRECT_LLM_REACTION_ENABLED`, allowed set = union A8 ~10 emoji, тесты §47/§48).

### (5) Диагностический путь + consumers (§1, §24, §29)
- **Файл:** `services/direct_context_composer.py:551–608` (`record_direct_metric`, `record_diagnostics`/`get_diagnostics` — process-local), `web/api/direct.py` (`/api/direct/context-diagnostics` read-only), `services/execution_graph_source.py` (ExecutionGraph snapshots), `web/api/analytics.py:193+` (`/analytics/usage/latest|summary`, `/analytics/execution/latest`; RBAC `requires_global_admin`).
- **Проблема:** Analytics/Status не показывают effective window/автобюджеты/стадии/pressure; второй расчёт запрещён (§29) — все цифры из одного resolver'а.
- **Задача:** T-4075 (`GET /api/analytics/context-budgets`), T-4076 (Analytics UI), T-4077 (Status compact; НЕ публиковать `/api/status.context` заново — существующий `memoryContext` остаётся legacy).

### (6) Catalog-ключи Summary (§77, §89)
- **Файл:** `services/param_catalog.py:255` (группа `limits_chat_budgets` «Прямой чат: бюджеты слов»), `:897–905` (`limits.summary_hybrid_context_tokens` «Hybrid: потолок контекста (слов)»; `…_chars` «…(символов)»), `:1378` (`SUMMARY_MAX_CONTEXT_TOKENS` «Legacy: потолок контекста пересказа, слов»), `:1434` (`CHAT_CONTEXT_BUDGET_TOKENS` «Контекст: общий бюджет, слов (кусочков текста)»), `:1585` (`CHAT_GLOBAL_KEY_BUDGET_TOKENS` «Лимит слов общего ключа в сутки (чат)»).
- **Проблема:** tokens названы «словами»; `…_chars` — legacy/emergency должен уйти из normal UI (ключ сохраняется, Δ удалений = 0).
- **Задача:** T-4067 (6 переименований spec 10.1 + новый ключ `models.chat_context_window_override` → F8 484/424/459/105/103/21), T-4072 (manual cap в Advanced).

## Сопутствующие факты
- **Kill-switch паттерн:** env-only ClassVar в `config/settings.py`, резолв per-call, default ON, OFF = байт-в-байт (прецеденты `DIRECT_CONTEXT_COMPOSER_ENABLED`, `DIRECT_SILENT_ACK_ENABLED`).
- **События:** `services/agentic_events.py` — закрытый enum 28 типов (`CORE 12 + ANTI_CLICHE 8 + DIRECT 8`), R17-whitelist `EVENT_FIELDS`; новые +5 (`MODEL_CAPACITY_RESOLVED`, `AUTO_CONTEXT_BUDGET`, `DIRECT_REACT`, `SUMMARY_L1_CHUNKED`, `SUMMARY_COVERAGE_DEGRADED`) коллизий не имеют → 33.
- **UI-флаги:** env-флаги доставляются фронтенду через `/api/me` `ui_flags` (`web/api/routes.py:351+`) — сюда добавить `UI_BUDGETS_SPLIT_ENABLED`, `ANALYTICS_CONTEXT_BUDGETS_ENABLED`.
- **Migration custom-preservation:** `services/config_migrations.py:42–57, 111–113, 142–143, 185–186, 218–219, 320–322` — WARNING «кастом владельца — НЕ трогаем» → T-4086 переводит штатные случаи в INFO (`CONFIG_MIGRATION_INFO_LOGGING_ENABLED`).
- **Fallback LLM:** `services/llm_client.py:953–1023` (`generate`: при `LLMError` primary → `_fallback_with_retries(ТОТ ЖЕ payload)` — oversized payload уходит fallback'у как есть → точка врезки `fallback_payload_adapter` для T-4057).
- **F8-харнесс:** `tests/test_round1025_f8_registry.py` (frozen counts/keys — переиздать после Δ каталога; прецедент eol-нормализации).
- **Episode 200+:** `services/direct_context_composer.py:368+` (`compute_episode_span`) — детерминированное расширение, T-4062 подтверждает тестом.
- **Legacy `MAX_SUMMARY_PARTS`** в Hybrid не используется (подтверждено: `summary_hybrid_budget.py` ключ не читает) — закрепить тестом (T-4069).
