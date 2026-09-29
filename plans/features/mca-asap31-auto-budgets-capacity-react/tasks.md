# mca-asap31-auto-budgets-capacity-react — tasks.md (ASAP-3.1 Acceptance Addendum)

- **Эпик:** `memory-context-autonomy` (round 10.27), ASAP-3.1 — acceptance addendum после ASAP-3. Это **не** новый большой эпик и не переделка Direct Context (§Цель).
- **Источник требований:** `plans/current_task.md`, строки **6067–9922**, §1–§146, прочитано полностью; SHA256 файла **`D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB`** (зафиксирован до чтения; файл не изменялся, R17/R18).
- **Baseline (по данным Оркестратора):** прод **2.58.36** (HEAD `c5cb5a9`, DDL v19); каталог 483/423/458/105/103/21; `budgetsUnlimitedKeys` в `web/app.js`; `services/model_capacity.py` fallback 16384 + `CHAT_MODEL_CONTEXT_WINDOW`; REACT — детерминированные наборы по классу (A8-аддитивно); `/api/direct/context-diagnostics` есть.
- **Входные артефакты:** `plans/archive/mca-asap3-direct-context-reply-reliability-round1028/` (spec/composer/model_capacity/decision matrix); `plans/archive/mca-asap21-summary-quality-ui-cleanup-round1028/`; `plans/archive/mca-asap2-summary-pipeline-round1027/`.
- **Диапазон задач:** **T-4051…T-4090 (40 задач)**, блоки A–N. T-4050 занят, ID прочим фичам не выдавать.
- **DoD:** §55 (пп. 1–25) + §112 (пп. 26–58) + §146 (пп. 59–77); финальный gate §117 — только после §55 + §112–§116.
- **Порядок работ (§113):** Architect narrow reconcile → Builder → **Browser Use frontend verification** → Playwright regression → Reviewer → rework → Approved → production deploy → production live acceptance → screenshot/log evidence → обновлённый §61 → `current_task continuation unblocked`.
- **Инцидент-контекст (§74/§75):** L1 truncated `skipped=81 | kept=288 | limit=21001` — legacy path `services/summary_hybrid_budget.py` (`HYBRID_CONTEXT_TOKEN_DEFAULT=30000` → safe_budget − system prompt − L1 output reserve 4000 ≈ 21001); плюс transport timeouts primary (nano-gpt) + fallback (deepseek) → `L1_FALLBACK_PACKAGE`. Две РАЗНЫЕ причины — обе должны быть видны отдельно (§74).
- **Известные среды падения тестов (учитывать в M):** `trafilatura` (env), `InputRichMessageMedia` (чужой WIP), `test_forbidden_paths_out_of_diff` (якорный), frozen-hash пины F8 (прецедент CRLF/LF, backlog §ASAP-3.3) — фиксировать от eol-нормализованного вида.
- **Deploy:** corrective production release, bump **2.58.36 → 2.58.37** (§53, §108–§111), rollback обязателен (блок N).

## Глобальные запреты (включены в критерии соответствующих задач)

- **§115 — запрет «параметрических» hotfix'ов:** `PULSE_SPEED /= 2`; смена только `TOPO_HZ` 4→3 без устранения fade reset; ещё один `padding-bottom`/`bottom: env(...)`; `z-index`; скрыть Analytics card; try/catch вокруг всего Analytics render; поднять Summary static budget 30000→100000; `CHAT_MODEL_CONTEXT_WINDOW=131072` как «решение»; переименовать machine key без изменения UX. Нужен fix причины.
- **§8:** никаких молчаливых `16384` в UI (fallback виден как warning/badge).
- **§29/§50:** не создавать второй usage store / второй независимый расчёт бюджетов (Status/Direct/Analytics — из одного resolver'а).
- **§16:** никаких VIP/hardcoded chat path (PERMsoc-ID, whitelist, «главный чат»).
- **§51:** миграция без destructive reset; старые effective значения сохраняются.
- **§80/§139:** timeout ≠ «резать контекст»; transport и capacity — разные понятия.
- **§118–§120/§128:** budget не используется для semantic dropping source messages; `skipped=N` из-за budget отсутствует как normal behavior.
- **§124/§125:** happy path (всё помещается) не дробится искусственно; multi-pass только по физике.
- **§58/§70/§95:** для frontend-багов не принимать grep-only/константные «фиксы» — только реальный Browser Use/Playwright + визуальная проверка.
- **§34:** raw текст диалога в production logs не писать.

---

## Контракты Architect — binding (spec.md разделы 3–10, ADR-1028-3 Accepted; изменение любого D — только через re-review/инвалидацию approval)

1. **Kill-switch реестр (env-only, default ON; OFF = байт-в-байт прежнее поведение):** `MODEL_CAPACITY_RESOLVER_ENABLED` (T-4053), `AUTO_BUDGET_RESOLVER_ENABLED` (T-4056), `SUMMARY_COVERAGE_CHUNKING_ENABLED` (T-4070), `DIRECT_LLM_REACTION_ENABLED` (T-4078, + существующий per-chat `flags.chat_decision_reactions_enabled`), `UI_BUDGETS_SPLIT_ENABLED` (T-4064/T-4066), `ANALYTICS_CONTEXT_BUDGETS_ENABLED` (T-4075), `CONFIG_MIGRATION_INFO_LOGGING_ENABLED` (T-4086). Polygon/bottom-nav — БЕЗ флагов (откат revert-тегом, прецедент UI-rework).
2. **Observability:** закрытый enum событий 28 → 33, аддитивно +5: `MODEL_CAPACITY_RESOLVED`, `AUTO_CONTEXT_BUDGET`, `DIRECT_REACT`, `SUMMARY_L1_CHUNKED`, `SUMMARY_COVERAGE_DEGRADED` — коллизий с существующими `DIRECT_*`/`DECISION_*`/`CONTEXT_*` нет; R17-whitelist полей per-event по паттерну §49.
3. **Санкция Δ каталога (F8-переиздание обязателен, атомарно той же серией коммитов):** +1 ключ `models.chat_context_window_override` (int, default 0=Auto; settings-поле — существующий `CHAT_MODEL_CONTEXT_WINDOW`; группа models_llm) + 6 переименований labels/группы (spec 10.1, Q7/§77/§89). Ожидаемые F8-числа: **483/423/458/105/103/21 → 484/424/459/105/103/21** (точные значения — из фактического вывода F8-харнесса в билд-коммите). Δ DDL = 0 (подтверждено — coverage/бюджеты/реакции через события); Δ зависимостей = 0; R17/R18 без изменений.
4. **LLM REACT (Q11/D7):** decision-матрица сохраняет владение action REPLY/REACT/SILENT (2-вызовность System 2, await_count==2); LLM выбирает ТОЛЬКО emoji в Stage-1 structured output при action=REACT; allowed set = union A8-наборов (~10 Telegram-emoji); невалидное/отсутствующее → детерминированный fallback; SILENT→🗿 — единственный hardcode, без изменений.
5. **Summary (D3/D4):** вход — exhaustive/физический (полный source set, lossless chunking при переполнении); выход — semantic policy формы статьи (soft targets, §99) отдельно и НИКОГДА не режет входной source set; manual cap = размер одного L1-запроса (chunk). Второй usage store / второй независимый расчёт бюджетов ЗАПРЕЩЁН (§24, §29, §50).
6. **Model Slots (Q10):** состав первого релиза зафиксирован spec Q10 (без `intel.history`; video/text composer-стадии — НЕТ в первом релизе; decision/react — без отдельного слота).
7. **Cache TTL (Q9):** remote catalogs 24 ч; локальные runtime-адаптеры (llama.cpp/Ollama) 300 с; `MODEL_CAPACITY_CACHE_TTL_SECONDS` (default 86400) — env-only, в каталог и обычный UI не попадает; в Advanced — read-only source/age/fallback.

---

## Блок A — Аудит

### T-4051 [MECH] Инвентаризация четырёх понятий бюджета и budget-путей в текущем коде
- **Acceptance:** артефакт `audit.md` в папке фичи, фиксирует: (1) `budgetsUnlimitedKeys()` — все 7 объединённых ключей (`chat_global_key_budget_requests/tokens`, `worker_daily_llm_calls/tokens_per_chat`, `chat_global_context_max_tokens`, `chat_thread_max_tokens`, `chat_context_budget_tokens`) и фактическую семантику одного тумблера (§1, §17); (2) `services/model_capacity.py` — fallback 16384, `window_source=unknown_fallback`, `CHAT_MODEL_CONTEXT_WINDOW` (§1, §3, §8); (3) `services/summary_hybrid_budget.py` — арифметику 30000→21001 и место truncation L1 (§75); (4) текущий REACT-классификатор (детерминированные наборы по классу) и точку врезки LLM-выбора (§30); (5) диагностический путь `/api/direct/context-diagnostics` и execution snapshots как consumers (§1, §24, §29); (6) catalog-ключи Summary (`summary_hybrid_context_tokens/chars`, названия вида «потолок контекста (слов)») (§77, §89).
- **Результат:** карта «сущность → файл → проблема → задача» для B/C/D/E/F/G/H. Ничего не менять в коде.
- **Секции:** §1, §2, §17, §30, §75, §77. **Риски:** низкий; риск — пропустить legacy-ключ, mitigated полным grep каталога.

## Блок B — Model Capacity Resolver

### T-4052 [ARCH] Спецификация Model Capacity Resolver (Architect)
- **Acceptance (spec.md фичи, раздел capacity):** (1) структурированный результат резолва (provider, model, declared/runtime/effective window, max_output_tokens, source, confidence, resolved_at, fallback_used) — §3; (2) precedence: developer override → runtime metadata → provider catalog → verified registry → conservative fallback последним — §4; (3) `effective = min(runtime, provider/model)`, локальный runtime 16K при theoretical 128K обязателен к использованию — §5; (4) adapters по подключениям: OpenRouter (`context_length` + кэш), llama.cpp (`/props` → `n_ctx`), Ollama (`context_length` running model), vLLM (`max_model_len`: config introspection, если endpoint доступен; иначе verified registry + developer override — санкционировано spec Q8; недоступный metadata-endpoint НЕ блокирует релиз), generic OpenAI-compatible (adapter отсутствует по определению протокола → registry → fallback; не выдумывать размер regex'ом из имени) — §6; (5) cache по ключу provider/base_url/model/runtime identity + invalidation (смена model/base_url/stage/fallback/override, config reload, explicit refresh, TTL; если restart объективно обязателен — UI честно сообщает, §38) — §7, §38; TTL по Q9: remote catalogs 24 ч, локальные runtime-адаптеры (llama.cpp/Ollama) 300 с, `MODEL_CAPACITY_CACHE_TTL_SECONDS` (default 86400) — env-only; (6) fallback-политика: допустим только аварийно, лог `MODEL_CAPACITY_FALLBACK` (provider, model, base_url class, fallback_window, reason), badge «Capacity: fallback» — §8; (7) семантика override: `0/null = Auto`, `>0 = Developer override`, `-1` никогда не capacity (только policy «Unlimited») — §39; (8) единая backend-схема consumers — §37.
- **Секции:** §3–§8, §37, §38, §39. **Риски:** средний — доступность metadata-эндпоинтов у конкретных провайдеров прод-моделей; смягчение — registry + fallback как нижний этаж, badge всегда.
- **Блокирует:** T-4053, T-4054, T-4056, T-4075.

### T-4053 [MECH] Реализация Model Capacity Resolver (перепись `services/model_capacity.py`)
- **Acceptance:** резолв по реальной паре provider/runtime + base_url + model (не display name); известная прод-модель (`deepseek/deepseek-v4.1-flash` и остальные активные) больше не получает молчаливый 16384; fallback логируется `MODEL_CAPACITY_FALLBACK` и всплывает как warning/badge; событие `MODEL_CAPACITY_RESOLVED` (slot, provider, model, effective_window, source, fallback_used) — §49; invalidation по §38 (смена модели → пересчёт без ручного restart, где позволяет hot-reload; если restart объективно обязателен — UI честно сообщает, §38); override `0/null=Auto` (§39); новый ключ каталога `models.chat_context_window_override` (int, default 0=Auto; settings-поле — существующий `CHAT_MODEL_CONTEXT_WINDOW`; группа models_llm) — F8-переиздание атомарно с билдом (ожидаемые числа 483/423/458/105/103/21 → 484/424/459/105/103/21, факт — из харнесса); kill-switch env `MODEL_CAPACITY_RESOLVER_ENABLED` (default ON), OFF — байт-в-байт прежний резолв (карта + env + fallback 16384).
- **Секции:** §3, §4, §5, §6, §7, §8, §37, §38, §39. **Зависит от:** T-4052. **Риски:** средний — деградация резолва для unknown-модели; mitigated fallback+badge (§8).

### T-4054 [MECH] Тесты Model Capacity Resolver (§40, §41)
- **Acceptance:** fixtures: known remote model (source provider/runtime, fallback false) / unknown remote (registry) / completely unknown (fallback + warning + UI badge) / developer override (побеждает, source developer_override) / model switch (cache invalidated, budget пересчитан) — §40; adapter-level tests: Ollama `context_length`, llama.cpp `n_ctx` (`/props`/metadata), vLLM deployment `max_model_len` vs theoretical — §41. Все — без внешней сети (mock endpoints).
- **Секции:** §40, §41. **Зависит от:** T-4053. **Риски:** низкий.

## Блок C — Auto Budget Resolver

### T-4055 [ARCH] Спецификация Auto Budget Resolver (Architect)
- **Acceptance (spec.md, раздел auto-budget):** (1) вход: model capacity, stage, actual mandatory payload, output policy, context policy, developer overrides; выход — структура как §9 (stage, model, context_window, mandatory_tokens, output_reserve, safety_reserve, auto_input_budget, policy_mode, manual_cap, effective_input_budget, source) — числа в ТЗ только пример структуры, не defaults; (2) safety reserve применяется РОВНО ОДИН раз (один понятный расчёт на request; каждая составляющая видна в diagnostics) — §10; (3) output reserve stage-aware: фактический `max_tokens` → stage policy → safe default; админу не показывается как обязательное поле — §11; (4) token estimation: tokenizer-specific → существующий counter → conservative fallback; после ответа — provider-reported actual; Analytics различает estimated/actual — §12; (5) наследование stage→primary и правило fallback-модели (не слать payload, собранный под большое окно primary; перед fallback: resolve → пересчёт → recompose) — §14; (6) coverage_policy/overflow_strategy metadata в registry stages (`summary.l1: exhaustive/chunk_all`; `direct.primary: relevance_composed/priority_reduce`) — §133; (7) Q4/Q5 — отвечены Architect в spec §2 (binding): арифметика 21001 — статический артефакт legacy-ключа; вход exhaustive/физический, выход — soft targets отдельно, никогда не режут входной source set; manual cap = размер одного L1-запроса.
- **Секции:** §9–§12, §14, §23, §37, §132, §133, §114. **Риски:** средний/высокий — ядро фичи; неверная формула касается всего. **Блокирует:** T-4056, T-4057, T-4069, T-4070.

### T-4056 [MECH] Реализация Auto Budget Resolver + wiring consumers
- **Acceptance:** единый resolver поверх capacity resolver; подключены: Direct Context Composer, Summary L1/L2 packers, fallback recompose, `/api/direct/context-diagnostics`, `/api/analytics/context-budgets`, компактный Status view — один источник цифр, Status/Direct/Analytics не считают сами (§29, §37); все Smart Module LLM-стадии получают capacity через resolver, потребительский код не хардкодит `30000/16000/21001/32000` (§131); frontend ничего не вычисляет сам (§37); breakdown каждой составляющей в diagnostics (§10); kill-switch env `AUTO_BUDGET_RESOLVER_ENABLED` (default ON), OFF — прежняя статическая арифметика бюджетов (Direct D2 + Summary static) без новых слоёв.
- **Секции:** §9, §10, §11, §12, §29, §37, §131. **Зависит от:** T-4052, T-4055. **Риски:** средний — регрессия Direct (известные падения composer-тестов ASAP-3 учесть).

### T-4057 [MECH] Fallback-модель с меньшим окном (Direct): recompose обязателен
- **Acceptance:** при переключении на fallback model с меньшим context window: capacity fallback резолвится отдельно, effective budget пересчитывается, при необходимости context recomposed; fallback НЕ получает oversized primary payload; P0 сохраняется; pressure/overflow observable (§42). Интеграционный тест по сценарию §42.
- **Секции:** §14, §42. **Зависит от:** T-4056. **Риски:** средний — touchpoints в composer fallback-цепочке.

## Блок D — Model Slots

### T-4058 [ARCH] Спецификация backend registry LLM slots (Architect)
- **Acceptance (spec.md, раздел slots):** состав первого релиза — spec Q10 (отвечен, binding): `direct.primary`; `direct.fallback` (если настроена — иначе слот не показывается); `summary.l1`, `summary.l2` (наследование от primary — компактной строкой, не дубликат); `summary.legacy` (только когда активен Legacy fallback контур); `intel.background` (одной строкой); `intel.reflection` (если пара отличима); decision/react выполняются моделью `direct.primary` — отдельный слот НЕ создаётся; video/text LLM stages, использующие context composer — НЕТ в первом релизе (расширение отдельным решением при появлении второго composer-потребителя); image/STT/embeddings вне text-context matrix (§13); один model id может быть в нескольких slots с разными auto budgets (§13); наследование отображается как `Summary L1 → наследует Direct Primary`, не дублируется (§14); policy metadata из T-4055 (§133). Состав slots фиксируется spec Q10 (binding); отступление от Q10 — только через re-review (инвалидация approval).
- **Секции:** §13, §14, §133. **Блокирует:** T-4059, T-4075, T-4064.

### T-4059 [MECH] Реализация slots registry API + наследование
- **Acceptance:** backend отдаёт готовую структуру активных slots (назначение, display name, model id, provider, окно, source, auto budget, policy mode, last payload, utilization, warning при fallback) — §18/§25 shape; frontend НЕ вычисляет slots по хардкод-списку моделей (§13); наследование `L1 — наследует основную модель` показывается компактно (§19).
- **Секции:** §13, §14, §18, §19, §25. **Зависит от:** T-4058. **Риски:** низкий/средний.

## Блок E — Per-chat Context Policy + episode 200+ + Dynamic 16000

### T-4060 [MECH] Per-chat Context Policy через один generic механизм
- **Acceptance:** режимы Dynamic / Unlimited / Manual Cap (только Advanced); Unlimited ограничен физической capacity модели, artificial cap не накладывается (§15); Dynamic: P0/P1 protected, шум режется первым, soft target ≠ hard scissors (§15); **никаких** hardcoded chat ID / VIP branch / whitelist / «главного чата» (§16); acceptance на втором обычном тестовом chat_id: Dynamic → Save → Reload → effective=Dynamic; Unlimited → Save → Reload → effective=Unlimited; вернуть исходное (§16); unit/integration тест на двух разных chat_id (§16, §52 per-chat).
- **Секции:** §15, §16, §43, §52. **Риски:** средний — поиск существующего hardcoded path (если есть) в E-аудите T-4051.

### T-4061 [MECH] Разводка «Безлимит по этому чату» + миграция без потерь
- **Acceptance:** старый объединённый toggle (`budgetsUnlimitedKeys`, 7 ключей) больше не связывает context и quota; Context Unlimited управляется только Context Policy; «Без суточных квот» — отдельная настройка, меняет только usage/quota keys и не трогает context keys (§17); тест разделения: Context Unlimited не меняет daily key request/token/worker quota; «Без суточных квот» не меняет Direct Context Dynamic/Unlimited и thread/context policy (§46); миграция: перед миграцией читаются existing per-chat/global значения; если старый toggle выставил все 7 в `-1` — намерение сохраняется, значения больше не связаны одной кнопкой; **не destructive reset** (§51); effective значения после миграции == до (§51).
- **Секции:** §17, §46, §51. **Зависит от:** T-4051. **Риски:** средний — миграция прод-конфига; mitigated audit-first и non-destructive правило.

### T-4062 [MECH] Подтверждение verbatim episode 200+ сообщений
- **Acceptance:** сценарий: current request → retrieval hit ≥200 сообщений назад → deterministic episode expansion → coherent raw dialogue → verbatim included (§34); evidence содержит `distance_messages`, `episode_messages`, `episode_tokens`, `verbatim=true`, source (§34); raw текст в production logs не пишется (§34). Если канал недоступен в prod — задокументировать как gap с причиной (не фальсифицировать evidence).
- **Секции:** §34. **Риски:** средний — зависит от реальной истории чата; mitigated синтетический integration-фикстур + прод-прогон.

### T-4063 [MECH] Dynamic 16000 — закрепить soft target тестом
- **Acceptance:** тест: если P0/P1/relevant material превышает soft target 16000, но помещается в physical window — НЕ режется ради target; 16000 остаётся operational soft target, не hard cap (§35).
- **Секции:** §35. **Риски:** низкий.

## Блок F — Miniapp «Бюджеты» + Developer/Advanced + Direct Context UI

### T-4064 [MECH] Страница «Бюджеты»: авто-карточки активных slots
- **Acceptance:** read-only карточка «Автоматические бюджеты моделей» показывает только реально активные text-model slots (§18); для каждого: назначение, display name, model id, provider, context window, capacity source, auto input budget, policy mode, last payload, utilization, warning при fallback capacity (§18); automatic visibility: отдельная модель L1 → отдельная строка; наследование → компактная строка; нет fallback model → нет пустой карточки; capacity fallback → warning + «Подробнее в Advanced» (§19); UI строится из effective runtime configuration, не из статического списка лимитов (§19); никакой required-обработки чисел пользователем (§18); kill-switch env `UI_BUDGETS_SPLIT_ENABLED` (default ON), OFF — прежняя структура настроек без страницы «Бюджеты»/split.
- **Секции:** §18, §19, §43. **Зависит от:** T-4059. **Риски:** низкий/средний.

### T-4065 [MECH] Developer/Advanced settings: capacity-параметры
- **Acceptance:** в «Расширенные системные» перенесены/добавлены: Model context window override (`0/empty = Auto`), capacity source/status read-only (source/age/fallback), cache TTL — env-only (`MODEL_CAPACITY_CACHE_TTL_SECONDS`, Q9), в UI не выводится, manual context cap, output reserve override по stage (если нужен), tokenizer/safety override (только если поддерживаемый knob), fallback window read-only/developer (§20); поля условные: показывается «Auto detected: …»; при неуверенности резолвера — «Не удалось определить автоматически — используется fallback 16 384» и только тогда подсказка Developer override (§21); Advanced-тест: auto capacity read-only, source виден, manual override доступен, Auto восстанавливается очисткой/0, fallback warning понятен, второй источник истины не создаётся (§44); сложные параметры имеют русское описание 1–3 предложения (что это, когда используется, что значит «Авто», когда менять) (§85); technical key — мелким monospace в «Технические детали» (§86).
- **Секции:** §20, §21, §39, §44, §85, §86. **Риски:** низкий.

### T-4066 [MECH] Direct Context UI: упрощение карточки
- **Acceptance:** в «Прямые ответы» простой блок: Context Mode `Dynamic | Unlimited`; ниже — Current model, Auto context window, Auto available budget, Current/last payload, pressure status (§22); подробный breakdown — в `<details>` «Диагностика последнего прогона» (§22); ручные числовые caps убраны с основного экрана (§22); kill-switch env `UI_BUDGETS_SPLIT_ENABLED` (default ON), OFF — прежний вид карточки Контекст; acceptance §43: обычный админ может выбрать Dynamic/Unlimited, увидеть модель/окно/бюджет/загрузку, НЕ вводя 131072/16384/safety multiplier/tokenizer margin/output reserve.
- **Секции:** §22, §43. **Риски:** низкий.

### T-4067 [MECH] UI copy audit budget-экранов (human-first русский)
- **Acceptance:** пересмотрены минимум: «Модули → Бюджеты», «Прямые ответы → Контекст», «Summary → Лимиты», «ИИ → Модели», «Аналитика», Status budget preview, Advanced settings (§89); 6 санкционированных переименований каталога (spec 10.1 + Q7) применены: `limits.summary_hybrid_context_tokens` → «Hybrid: максимальный размер одного L1-запроса (токены)» + описание §138; `limits.summary_hybrid_context_chars` → «Hybrid: аварийный символьный потолок (legacy)» + вывод из normal UI (ключ СОХРАНЯЕТСЯ, удаления НЕТ); `CHAT_CONTEXT_BUDGET_TOKENS` → «Контекст: бюджет Direct, токенов»; `CHAT_GLOBAL_KEY_BUDGET_TOKENS` → «Лимит токенов общего ключа в сутки (чат)»; `SUMMARY_MAX_CONTEXT_TOKENS` → «…, токенов»; группа `limits_chat_budgets` → «Прямой чат: бюджеты (токены)»; запрещены как главный текст: raw config key, P0/P1/P2/P3, provider_catalog, unknown_fallback, `131072`, `summary_hybrid_context_tokens`, serialized_tokens, внутренние enum/reason codes (§83); tokens ≠ «слова», при слове «токены» — однократное пояснение (§89); переводы machine states: provider_catalog→«каталог провайдера», runtime→«фактические настройки сервера», developer_override→«задано разработчиком вручную», fallback→«Не удалось определить автоматически — используется безопасное резервное значение» (§87); правила названий §84 соблюдены («Окно модели», «Определено автоматически», «Доступно для контекста», «Режим: Без искусственного лимита»…); machine IDs допустимы вторичным текстом (§83).
- **Секции:** §83, §84, §85, §86, §87, §89. **Зависит от:** — (Q7 отвечен: spec §2 Q7 + санкция spec 10.1). **Риски:** низкий.

## Блок G — Summary Window = полный охват (§118–§146) + инцидент-регрессии

### T-4068 [ARCH] Спецификация Summary coverage contract (Architect)
- **Acceptance (spec.md, раздел summary-coverage):** (1) configured Summary window определяет полный SOURCE SET; все сообщения окна обязаны быть обработаны; бюджет — только транспортный/физический рубеж, не semantic selection policy (§118, §119); (2) если всё окно помещается — ОДИН L1 pass получает весь набор; запрещены importance eviction/sampling/short-message filtering/oldest dropping/soft-target truncation/fixed 30K-21K при большом окне (§119); (3) если не помещается — lossless chunking: partition → L1 по каждому chunk → merge → L2; каждый source message ID ≥1 primary chunk; `chunks=N` вместо `skipped=N` (§120); (4) chunking contract: chronological order, stable IDs, без удаления коротких/standalone/«неважных», учёт serialized size/metadata/reply relationships, overlap с дедупликацией по stable ID на merge (§121); (5) reply continuity: boundary packing с overlap (parent/соседей/фрагмент цепочки), overlap ≠ замена coverage (§122); (6) oversized single message: lossless segmentation с message_id/author/timestamp/part index/связью частей, merge восстанавливает принадлежность (§123); (7) chunk merge объединяет темы через границы chunks; доп. merge LLM call допустим ТОЛЬКО при реальном physical overflow (§124); (8) fast path 1×L1+1×L2; overflow path N×L1+merge+L2; число вызовов — от физики (§125); (9) L2 не теряет уникальные темы ради soft target; hierarchical semantic reduction допустима только когда все исходники прочитаны L1 (§126); (10) manual cap = «макс. размер одного L1 запроса», не «макс. обработанный объём» (§137); (11) timeout ≠ удаление сообщений: retry по policy → fallback → (при меньшем окне fallback) lossless rechunk ПОЛНОГО source set → fail-soft package (§139, §140); L1_FALLBACK_PACKAGE строится из полного window насколько возможно локально (§141); (12) ответы на §114 Q4/Q5 зафиксированы; граница D4: входная сторона — exhaustive/физическая (полный source set, lossless chunking), выходная — semantic policy формы статьи (`summary_hybrid_response_mode/_target_chars/_target_paragraphs/_max_chars`, §99): soft targets формируют выход и НИКОГДА не режут входной source set — смешивание запрещено; (13) stage policy metadata (§133) согласована с T-4055.
- **Секции:** §118–§145 (контрактная часть), §114. **Блокирует:** T-4069, T-4070, T-4071, T-4072, T-4074.

### T-4069 [MECH] Summary L1/L2 подключены к общему Auto Budget Resolver
- **Acceptance:** audit Hybrid Summary context keys завершён (вход T-4051); `summary_hybrid_context_tokens` → semantics: default Auto (0/null=Auto, >0=Developer manual cap), physical capacity берётся из реально выбранной `models.summary_l1_base_url + models.summary_l1_model_name` (L2 аналогично); наследование показывается как inheritance (§23, §76); старый fixed Hybrid default 30000 не создаёт artificial 21001 cap в Auto mode (§75, §112.41); legacy `MAX_SUMMARY_PARTS` не используется для Hybrid (§23); `summary_hybrid_context_chars` — ключ СОХРАНЯЕТСЯ (Δ удалений = 0), остаётся legacy/emergency и выводится из normal UI (группа остаётся Advanced, label «Hybrid: аварийный символьный потолок (legacy)», санкция spec 10.1); два равноправных manual caps tokens+chars в обычном UI не поддерживаются (§77); manual cap `>0` = размер ОДНОГО L1-запроса (chunk), не объём обработки (§137, Q5); миграция: untouched canonical/default → Auto по существующей convention; реально кастомное значение владельца → сохранено как Developer manual cap с UI «Ручное ограничение включено» и возможностью вернуться к «Авто»; лог «кастом владельца — НЕ трогаем» подтверждает custom-preservation принцип (§78); обязательные stages resolver'а: direct.primary, direct.fallback, summary.l1, summary.l2, summary.legacy (если применимо), активные background text stages (§76).
- **Секции:** §23, §75, §76, §77, §78. **Зависит от:** T-4056, T-4068. **Риски:** высокий — ядро инцидента 21001.

### T-4070 [MECH] Lossless chunker + merge: реализация контракта
- **Acceptance:** реализованы §121–§126: chronological order, stable IDs, coverage invariant (каждый source ID ≥1 primary chunk), overlap dedup по stable ID, reply-continuity overlap, oversized-message segmentation с восстановлением принадлежности на merge, cross-chunk theme merge (одна тема из N chunks → одна связная тема), fast path без искусственного дробления, merge LLM call только при physical overflow, L2 hierarchical reduction без потери уникальных тем (§126); kill-switch env `SUMMARY_COVERAGE_CHUNKING_ENABLED` (default ON), OFF — прежний single-pass/truncation path (байт-в-байт прежнее поведение).
- **Секции:** §120, §121, §122, §123, §124, §125, §126. **Зависит от:** T-4068, T-4069. **Риски:** высокий — самая сложная механика фичи.

### T-4071 [MECH] Coverage metrics + события; убрать семантику `skipped`
- **Acceptance:** метрики на run: `source_window_start/end`, `source_messages_total/processed/unprocessed`, `l1_chunks`, `duplicate_overlap_messages`, `coverage_percent` (§127); успешный normal Summary: unprocessed=0, coverage=100%; coverage<100% — явный degraded state, не тихий «нормальный» summary (§127); события `SUMMARY_L1_CHUNKED` (source/processed/chunks/coverage) и `SUMMARY_COVERAGE_DEGRADED` (... reason) (§128); normal path «skipped из-за budget» не существует (§128); в Summary/Analytics — «Полнота источника»: «369 из 369 обработано · 100%», «1 проход/несколько проходов» (§135).
- **Секции:** §127, §128, §135. **Зависит от:** T-4070. **Риски:** низкий/средний.

### T-4072 [MECH] Summary UI: read-only полнота + Advanced manual cap
- **Acceptance:** обычный Summary UI без ручного input cap; read-only: «Окно саммари: 6 часов», «Сообщений в последнем запуске: 369», «Модель L1: …», «Окно модели: определено автоматически», «Режим обработки: один проход/несколько проходов», «Полнота: 100%» (§136); manual cap только в «Расширенные системные», название «Максимальный размер одного L1-запроса» с описанием §138 (не «Сколько контекста брать в Summary»); cap ограничивает размер chunk, а не общий coverage (§137); human-readable label'ы §83–§89 применимы.
- **Секции:** §136, §137, §138, §83. **Зависит от:** T-4069, T-4071. **Риски:** низкий.

### T-4073 [MECH] Timeout policy audit L1 + разделение transport/capacity
- **Acceptance:** ограниченный audit: effective primary timeout, total retry budget, число retries, фактическая длительность primary/fallback, dedicated L1 slot vs inherited global, нет неожиданного умножения timeout на retries/fallback; соответствие intended policy (прод-пример ≈156 c до fallback package); если контракт корректен — не перепроектировать (§81); timeout НЕ лечится уменьшением контекста «на глаз» (§80); Analytics показывает отдельно: request input tokens, attempt count, latency, timeout, primary/fallback provider, fallback reason (§80); `L1_FALLBACK_PACKAGE` — не авария: статус «Опубликовано» + badge «L1: резервный пакет» + причина «Основная модель не ответила вовремя» (§82); лог-набор инцидента §74 разделён на две наблюдаемые причины (budget truncation vs transport timeout) в Analytics/diagnostics (§74).
- **Секции:** §74, §80, §81, §82. **Зависит от:** T-4069 (параллельно допустимо). **Риски:** низкий/средний (только audit, если контракт ок).

### T-4074 [MECH] Регрессионные тесты инцидентов Summary
- **Acceptance:** (1) **369 сообщений / 6h / большое окно L1:** source_total=369, processed=369, unprocessed=0, coverage=100%, l1_chunks=1, нет `skipped=81`, нет искусственного `limit=21001` (§101, §142); (2) **маленькая локальная модель (16K/32K):** все 369 обработаны, chunks>1, coverage 100%, chronological order, replies у границ сохраняют контекст, без semantic prefilter (§143); (3) **смена L1 модели A(large)→B(small):** cache invalidated, stage autobudget пересчитан, авто-переход в multi-chunk, coverage 100%, пользователь не меняет token numbers (§144); (4) **окно 6h→12h:** никаких ручных budget changes, resolver пересчитывает workload, при необходимости растёт chunk count, coverage 100% (§145); (5) **timeout при полном влезании:** retry/fallback/rechunk полного source set под fallback capacity; fallback не получает только «kept» subset; «timeout → выбросить 30%» запрещён (§139, §140, §102 — резолв capacity nano-gpt/deepseek endpoint'ов раздельно); (6) manual cap ≤ размера окна ограничивает только размер одного chunk (§137).
- **Секции:** §101, §102, §137, §139, §140, §141, §142, §143, §144, §145. **Зависит от:** T-4070, T-4071. **Риски:** высокий по важности; это ключевые доказательства фичи.

## Блок H — Analytics «Автобюджеты моделей»

### T-4075 [MECH] Endpoint `GET /api/analytics/context-budgets`
- **Acceptance:** endpoint для global admin, optional `?chat_id=…`; shape §25 (generated_at, chat_id, policy_mode, slots[]: capacity {declared, runtime, effective, source, confidence, fallback_used}, budget {mandatory_tokens, output_reserve, safety_reserve, auto_input_budget, manual_cap, effective_input_budget}, observed {last/p50/p95/max input tokens, pressure_events, physical_overflow_events}); read-side view поверх resolver + usage events + Direct diagnostics/execution snapshots; **второй usage store не создаётся** (§24, §50); coverage policy stage в данных (§133, §134); kill-switch env `ANALYTICS_CONTEXT_BUDGETS_ENABLED` (default ON), OFF — endpoint и autobudget-блок отключены, остальная Аналитика не затронута (fail-open §73).
- **Секции:** §24, §25, §29, §50, §133, §134. **Зависит от:** T-4056, T-4059. **Риски:** средний.

### T-4076 [MECH] Analytics UI: human-first карточки и группировка
- **Acceptance:** таблица/карточки с колонками §26 (Модуль/стадия, Модель, Provider, Context window, Source, Auto budget, Last, P95, Utilization, Pressure, Status; Status: OK/Высокая загрузка/Fallback capacity/Manual override/Physical overflow); Unlimited НЕ показывается как 100% progress bar; utilization относительно physical/effective auto budget (§26); badges источника §27 (runtime/provider catalog/registry/developer override/fallback); human-first карточка как §88 (обычный экран не начинается с формулы; детали — под «Подробнее»); группировка секций §104: «Модели и автобюджеты» / «Использование и стоимость» / «Надёжность моделей» / «Выполнение» / «Память»; mobile — accordion/cards, не стена 50 строк; «Полнота источника» Summary (§135) и Coverage Policy человекочитаемо: «Охват: все сообщения выбранного окна» / «369 сообщений · обработано 369 · 2 прохода · охват 100%» / Direct: «Охват: релевантный контекст», enum не как основной текст (§134); timeout stats §103 («последняя задержка», P95, таймауты за период, повторы, переходы на резервную модель) — русскоязычно; понятные состояния вместо сырых warnings §105 (L1_FALLBACK_PACKAGE→«Кластеризация выполнена в резервном режиме»+подпись; MODEL_CAPACITY_FALLBACK→«Размер контекста модели не удалось определить автоматически»+подпись; CONTEXT_PRESSURE→«Контекст почти заполнен»); при нескольких активных slots Analytics показывает только их и обновляется при смене модели без frontend hardcode (§45).
- **Секции:** §26, §27, §45, §88, §103, §104, §105, §134, §135. **Зависит от:** T-4075. **Риски:** средний.

## Блок I — Status page

### T-4077 [MECH] Status «Бюджеты интеллекта»: компактное summary
- **Acceptance:** на главном «Статус» НЕ полная таблица; компактные строки вида «Direct: 1.05M · Auto 982K · last 39K», «Summary L1/L2: …» (§28); warning badge при fallback/manual override; клик/ссылка ведёт в полную Аналитику/Бюджеты (§28); цифры из того же resolver'а — Status не считает сам (§29); legacy `memoryContext`/`/api/status.context` можно сохранить для backward compat, но source of truth один (§29).
- **Секции:** §28, §29. **Зависит от:** T-4056. **Риски:** низкий.

## Блок J — LLM REACT + SILENT 🗿 + Force Direct

### T-4078 [MECH] Reaction выбирает LLM в том же decision call
- **Acceptance:** контракты Q11/D7: детерминированная decision-матрица ОСТАЁТСЯ владельцем action REPLY/REACT/SILENT (2-вызовность System 2 сохранена, await_count==2, границы A7); LLM выбирает ТОЛЬКО emoji при action=REACT — аддитивное поле в structured output СУЩЕСТВУЮЩЕГО Stage-1 (тот же вызов, что генерирует ответ); allowed set = union расширенных A8-наборов (~10 Telegram-emoji: `😂,🤣,👍,👌,❤️,🔥,🤨,🤔,💀,🤡`; финализируется в этой задаче из фактического enum-константа, расширение только целыми Telegram-emoji); невалидное/отсутствующее значение → детерминированный fallback `_reaction_for_class`/`_stable_reaction_pick` молча (fail-soft, не ошибка пользователю); kill-switch env `DIRECT_LLM_REACTION_ENABLED` (default ON) + per-chat `flags.chat_decision_reactions_enabled`; любой OFF → байт-в-байт текущее детерминированное поведение; observability `DIRECT_REACT {source=llm_decision, reaction, trigger_type}`. При `REACT` конкретная допустимая Telegram reaction выбирается LLM в том же structured output Decision Maker (`{"action":"REACT","reaction":"💀","reason":"…"}`); **не делается второй LLM request** (§30); backend передаёт Decision Maker разрешённый набор reactions; выбор учитывает сообщение/контекст/personality/тон/отношения/иронию/предыдущий разговор; одинаковое «ахах» не обязано всегда давать 😂 (§31); backend только валидирует выбранное значение против allowed-набора (§31); **SILENT — единственный намеренный hardcode:** direct-autonomous `SILENT` → acknowledgement всегда `🗿`, LLM не выбирает emoji, смысл «увидел, но сознательно проигнорировал»; для background silence никакого 🗿 (§32); Force keyword (`бот, …`) остаётся выше Decision Making → всегда REPLY, не REACT/не SILENT, даже если сообщение похоже на laughter/ack (§33).
- **Секции:** §30, §31, §32, §33. **Риски:** средний — врезка в существующий Decision Maker без третьего вызова (прецедент A1 `tool-coordinator`).

### T-4079 [MECH] Тесты LLM REACT / SILENT / Force
- **Acceptance:** mock Decision LLM `{"action":"REACT","reaction":"💀"}` → отправлено 💀; `{"action":"REACT","reaction":"🤡"}` → отправлено 🤡; нет hardcoded `laughter→😂` (§47); SILENT direct → 🗿 даже если LLM вернула другое reaction вместе с SILENT; background SILENT → без обязательной реакции (§48); Force → text reply (§33, §53.10); недопустимое reaction значение отклоняется валидацией (§31).
- **Секции:** §47, §48, §33. **Зависит от:** T-4078. **Риски:** низкий.

## Блок K — Frontend corrective pass (§56–§72) — Browser Use/Playwright ОБЯЗАТЕЛЬНЫ

### T-4080 [MECH] Polygon: устранение первопричины мерцания
- **Acceptance:** подтверждена/опровергнута причина `TOPO_HZ=4` + `TOPO_FADE_MS=320` (пересборка ~250 мс сбрасывает fade раньше завершения 320 мс перехода) — Architect Q1; topology НЕ пересобирается визуально с частотой 4 Hz: topology стабильна пока геометрия не требует реальной пересборки; редкие rebuild — через old/new crossfade несколько секунд, без гашения яркости всей mesh; rebuild по displacement threshold / раз в десятки секунд (§59); glow «дышит»: период порядка минут, малая амплитуда; уменьшена именно AMPLITUDE (не только скорость): halo alpha/radius, radiation radius, bloom alpha, line glow, color morph — ни один слой не мигает заметно (§60); visual acceptance: Browser Use 60–90 с + periodic screenshots/canvas diagnostics: нет пульсации ~4 Hz, нет вспышек каждые несколько секунд, узлы не «лампочки», кадры через 20–30 с показывают небольшое плавное изменение, текст читаем (§61); **запреты §115:** «PULSE_SPEED /= 2» и «TOPO_HZ 4→3 без устранения fade reset» не принимаются как фикс.
- **Секции:** §56, §57, §58, §59, §60, §61, §115. **Зависит от:** — (Architect Q1 отвечен в spec §2). **Риски:** средний; визуальный субъективный критерий — mitigated diagnostics-полями T-4081 и скриншотами.

### T-4081 [MECH] Polygon: живая случайная форма + медленный глобальный дрейф
- **Acceptance:** при старте страницы один раз создаётся scene seed через `crypto.getRandomValues()`/безопасный browser RNG (не `Math.random()` каждый frame); сцена строится детерминированно из seed; один seed на lifetime страницы; новая полная загрузка → новая композиция; test/debug override (query flag/injected seed) для deterministic тестов; production random и deterministic tests не конфликтуют (§63); seed определяет высокоуровневую композицию: center X/Y, scale, aspect, лёгкий rotation/skew, расположение violet/cyan/indigo clusters, плотность, размеры кластеров, число вторичных (§64); mesh может занимать ~половину/большую часть экрана, частично выходить за край, смещаться от центра; узнаваемая композиция референса сохраняется (§64); отдельный global scene transform: медленный drift center по smooth path, медленное изменение scale, едва заметный rotation/tilt; local node drift поверх; периоды десятки секунд/минуты, без резких прыжков (§65); вариативность размера: compact ~45–65% / medium ~65–90% / large ~90–115% (частичный выход за viewport); диапазоны корректируемы по визуальному тесту (§66); во время сессии нет резкой перегенерации — только плавное движение/дыхание/редкий плавный topology change (§67); `prefers-reduced-motion` сохранён: один красивый статичный кадр, случайная композиция при загрузке допустима, без pulse/drift (§68); diagnostics `window.__PolygonBackground.getDiagnostics()` расширен: sceneSeed, sceneScale, sceneCenterX/Y, topologyRebuilds, lastTopologyRebuildAge, glowPhase, renderer, fps/frame count; не выводить в обычный UI (§69).
- **Секции:** §62, §63, §64, §65, §66, §67, §68, §69. **Зависит от:** — (Architect Q2 отвечен в spec §2). **Риски:** средний.

### T-4082 [MECH] Analytics не открывается: fix первопричины + discoverability + fail-open
- **Acceptance:** реальная причина неоткрытия `Аналитика` найдена и устранена (routing/render exception/RBAC/IA/network — по факту; Q3 ОТВЕЧЕН Architect статически, spec §2/F11: `NAV_ITEMS_V2` не содержит `oversight`, структурный фикс = вернуть oversight в NAV_ITEMS_V2; статический ответ НЕ отменяет обязательные Browser Use-измерения) (§70, Architect Q3); проверка **только** Browser Use по 12-шаговому чеклисту §71: открыть Miniapp как global admin → Статус → клик карточки «Аналитика» → URL/hash → route → activeTab → отрисовка oversight template → Console errors → network (`/api/oversight/summary`, `/api/analytics/usage/latest`, `/api/analytics/usage/summary`, `/api/analytics/execution/latest`) → deep-link `#/oversight` → повторить desktop → повторить mobile; grep «строка `#/oversight` в JS» НЕ считается доказательством (§71); для global admin Analytics discoverable: desktop sidebar + mobile «Ещё»/подходящий shell entry; одна страница/один route `#/oversight`, несколько navigation entry points допустимы; вторая Analytics page НЕ создаётся; RBAC — только global admin (текущий контракт) (§72); fail-open: падение одного endpoint не ломает страницу; каждый блок (summary/token analytics/context budgets/execution graph) показывает русскоязычную ошибку внутри карточки («Не удалось загрузить аналитику токенов»); console exception одного блока не убивает экран (§73); Playwright regression §99: global admin: Status → click «Аналитика» → URL `#/oversight` → heading «Аналитика» visible → token analytics block visible → autobudget block visible; mobile: достижима через понятную навигацию; deep-link открывает screen (§99); **запреты §115:** скрыть карточку; try/catch вокруг всего render — не принимаются.
- **Секции:** §56, §70, §71, §72, §73, §99, §115. **Зависит от:** — (Architect Q3 отвечен: F11/NAV_ITEMS_V2); 12-шаговый Browser Use §71 остаётся в acceptance обязательно. **Риски:** высокий (P0 frontend bug, обязателен до появления autobudget-блока в Analytics).

### T-4083 [MECH] Bottom mobile nav: одна модель viewport geometry
- **Acceptance:** Architect выбирает ОДНУ модель геометрии (§92, Q6): actual visible viewport height → shell этой высоты; safe/content inset применяется ровно один раз; bottom nav — обычный flex-child; main — остаток; кандидаты источника высоты: Telegram `viewportHeight`/`viewportStableHeight`, `visualViewport.height/offsetTop`, `window.innerHeight` — выбор по доказанному поведению, не по одному браузеру (§92); layout invariant §93: visible viewport → header → main (единственный scroll container) → bottom navigation (с собственным safe-area padding); НЕ «viewport минус guessed bottom offset + nav без safe-area + ещё один CSS fallback» (§93); запрещено наращивать ещё один bottom/padding/subtraction/offset (§92); acceptance invariants §94 (после render): `rect.top >= 0`; nav полностью видима; `rect.bottom <= actualVisibleBottom + tolerance`; icon и label полностью видны; safe-area/Telegram bottom controls не перекрывают label; main content не под nav; последний интерактивный элемент main доскролливается выше nav; проверка визуально И программно (§94); SaveBar coexistence §98: SaveBar не перекрывает last config field, не прячется под bottom nav; nav не прячется под Telegram/system UI; достаточный scroll-padding main; панели не накладываются; допустимо SaveBar внутри scroll/main, nav снаружи (§98); viewports §96: 320×640, 360×800, 390×844, 430×932, desktop ~1440×900 (+actual Telegram WebView при доступности); режимы: normal, fullscreen, после scroll, после открытия/закрытия «Ещё», после перехода между модулями, при sticky SaveBar, при фокусе input/keyboard насколько позволяет среда (§96); **запреты §115:** ещё один `padding-bottom: 20px`, ещё один `bottom: env(...)`, увеличение z-index — не принимаются.
- **Секции:** §56, §90, §91, §92, §93, §94, §96, §98, §115. **Зависит от:** — (Architect Q6 отвечен в spec §2). **Риски:** высокий (пережил несколько hotfix-итераций; требуется измеренная геометрия, §90).

### T-4084 [MECH] Visual evidence + polygon browser regression
- **Acceptance:** screenshots «до/после» сохранены минимум для: Polygon background, Analytics opened, mobile Summary/module page, bottom nav fully visible, mobile «Ещё», autobudgets Analytics (§97); Reviewer смотрит screenshots, а не только отчёт Builder (§97); Playwright/browser-use polygon regression по свойствам (не pixel-perfect): canvas существует, renderer active, scene seed non-empty, seed отличается в двух независимых production-like сессиях, center position меняется со временем, topology rebuild count не растёт ~4/sec, нет draw errors, reduced-motion не запускает endless rAF (§100); visual screenshot review подтверждает эстетику (§100); frontend проверка — реальными кликами (менять chat scope, Dynamic/Unlimited, открывать Analytics/Advanced, скроллить, открывать модуль, проверять SaveBar/bottom nav, screenshots, console, failed network) — Browser Use не только как screenshot-maker (§107); grep-based тесты/CSS-маркеры/snapshot-строки/unit без layout — только дополнительные (§95).
- **Секции:** §95, §96, §97, §100, §107. **Зависит от:** T-4080–T-4083, T-4076. **Риски:** низкий/средний.

## Блок L — Observability / Metrics

### T-4085 [MECH] События и метрики бюджетов/реакций
- **Acceptance:** события §49: `MODEL_CAPACITY_RESOLVED` (slot, provider, model, effective_window, source, fallback_used), `AUTO_CONTEXT_BUDGET` (slot, context_window, mandatory_tokens, output_reserve, safety_reserve, effective_input_budget, policy_mode), `CONTEXT_PRESSURE` (slot, selected_tokens, budget, dropped P2/P3 counts, physical_overflow), `DIRECT_REACT` (source=llm_decision, reaction, trigger_type), `DIRECT_SILENT_ACK` (reaction=🗿, success); **никакого raw chat text** (§49); метрики §50: capacity fallback count, manual override count, context pressure count, physical overflow count, P0/P1 protected count, per-slot p50/p95 input tokens, direct LLM react count, reaction distribution, silent ack count; вторая система token usage НЕ создаётся — переиспользуются usage events (§50); event names повторно не дублируются: закрытый enum 28 → 33 типов, аддитивно +5 (`MODEL_CAPACITY_RESOLVED`, `AUTO_CONTEXT_BUDGET`, `DIRECT_REACT`, `SUMMARY_L1_CHUNKED`, `SUMMARY_COVERAGE_DEGRADED` — последние два генерируются в контуре T-4071), коллизий с существующими `DIRECT_*`/`DECISION_*`/`CONTEXT_*` нет (ADR-1028-3); R17-whitelist полей per-event по паттерну §49.
- **Секции:** §49, §50. **Зависит от:** T-4053, T-4056, T-4078. **Риски:** низкий.

### T-4086 [MECH] Migration warnings не выглядят как поломка
- **Acceptance:** штатное сохранение custom-значения владельца (`[context_migration] кастом владельца — НЕ трогаем`, аналог в `image_migration`) логируется как `INFO | CONFIG_MIGRATION_CUSTOM_PRESERVED` (или эквивалентный структурированный event), а не WARNING (§79); WARNING остаются только для migration failed/incompatible/corrupt/cannot-preserve (§79); существующее поведение сохранения custom не регрессировало (§78); kill-switch env `CONFIG_MIGRATION_INFO_LOGGING_ENABLED` (default ON), OFF — прежнее WARNING-логирование.
- **Секции:** §78, §79. **Риски:** низкий.

## Блок M — Сводные приёмочные тесты

### T-4087 [MECH] Сводный acceptance run (backend + интеграция)
- **Acceptance:** прогнаны и зелёные (с учётом известных сред падения — тривья trafilatura, InputRichMessageMedia чужой WIP, test_forbidden_paths_out_of_diff якорный, F8 frozen-hash пины от eol-нормализованного вида): тесты T-4054 (§40, §41), T-4057 (§42), T-4060 (два chat_id, §16), T-4061 (разделение context/quota, §46), T-4062 (episode 200+), T-4063 (§35), T-4074 (§101/§142–§145, §139–§140), T-4079 (§47, §48); Miniapp-интеграции: §43 (обычный админ: Dynamic/Unlimited/model/window/budget/загрузка без ввода чисел), §44 (Advanced read-only source/override/Auto restore), §45 (Analytics показывает только активные slots: Direct Primary/Fallback, Summary L1/L2, inheritance, background; обновление при смене модели без frontend hardcode); Browser Verification §52 обязателен: desktop и mobile; Budgets (auto cards, Dynamic/Unlimited, Advanced, capacity badge, fallback warning, manual override, quota separation), Analytics (таблица, модели, source, utilization, model switch), per-chat (минимум два chat_id, режимы независимы); тесты фиксируют estimated vs actual в Analytics (§12); приоритет: физический overflow объясним, artificial — нет (§101).
- **Секции:** §12, §16, §35, §40–§48, §43, §44, §45, §46, §52, §101, §142–§145. **Зависит от:** почти всех. **Риски:** средний.

## Блок N — Релиз

### T-4088 [MECH] Release prep: bump 2.58.36 → 2.58.37 + rollback-план
- **Acceptance:** `APP_VERSION` bump до 2.58.37; changelog-дельта (автобюджеты, Summary coverage, LLM REACT, frontend corrective pass); pre-deploy бэкап + annotated-тег отката (прецедент `pre-round1026-*`); план отката: тег → предыдущий прод-коммит; 7 env-only kill-switch'ей (default ON): `MODEL_CAPACITY_RESOLVER_ENABLED`, `AUTO_BUDGET_RESOLVER_ENABLED`, `SUMMARY_COVERAGE_CHUNKING_ENABLED`, `DIRECT_LLM_REACTION_ENABLED`, `UI_BUDGETS_SPLIT_ENABLED`, `ANALYTICS_CONTEXT_BUDGETS_ENABLED`, `CONFIG_MIGRATION_INFO_LOGGING_ENABLED` — каждый OFF = байт-в-байт прежнее поведение; Polygon/bottom-nav — без флагов (откат revert-тегом); F8-переиздание каталога — атомарно той же серией коммитов (ожидаемые числа 483/423/458/105/103/21 → 484/424/459/105/103/21; точные — из фактического вывода харнесса); порядок §113: deploy только после Reviewer Approved; secrets-дисциплина R17 (ключи/SSH только на шаге деплоя).
- **Секции:** §53, §113. **Зависит от:** Reviewer Approved. **Риски:** средний (обычные release-риски; композиция WIP — известный прецедент заморозки пинов).

### T-4089 [MECH] Production acceptance (§53 + §108–§110) + screenshot/log evidence
- **Acceptance:** §53 (11 пунктов): (1) Direct model определяется автоматически; (2) известная prod-модель не на generic 16384, если capacity определима; (3) candidate context >30K/>40K не режется искусственно при достаточном window; (4) Dynamic/Unlimited работают на двух разных chat_id; (5) Analytics показывает auto budgets текущих моделей; (6) смена тестовой model/config корректно invalidates capacity (тестовую модель/конфиг для этого пункта предварительно согласовать с владельцем — §53.6); (7) old verbatim episode 200+ подтверждён; (8) REACT выбирает reaction из LLM decision; (9) SILENT direct даёт 🗿; (10) Force keyword даёт text reply; (11) нет нового error spike. §108 frontend: Polygon — похож на референс, glow не мерцает, форма не всегда по центру, mesh медленно движется, новая сессия = другая композиция; Analytics — открывается с Status, deep-link, через нормальную navigation entry, autobudgets отображаются, partial endpoint failure не ломает screen; Mobile shell — нижняя nav полностью видна, labels не обрезаны, «Ещё» работает, SaveBar не конфликтует, последний field доступен. §109 Summary budgets: прод-Summary с большим окном — L1 capacity resolved, auto L1 budget от модели, нет fixed 30K/21K cap в Auto, source messages не выкинуты без физической причины, L2 — свой stage autobudget, fallback model — своя capacity, timeout как transport issue, fallback package fail-soft. §110 human-readable: Browser Use проходит Miniapp без raw keys; русскоязычный админ понимает: какая модель, сколько контекста, что автоматически, Dynamic/Unlimited, override, timeout, fallback, где глубокая настройка; без знания P0/provider_catalog/safe_budget/PG key. Evidence: screenshots до/после (§97), логи.
- **Секции:** §53, §108, §109, §110, §111 (вход для отчёта). **Зависит от:** T-4088. **Риски:** средний.

### T-4090 [MECH] Финальный human-readable отчёт (§116) + разбор инцидента (§111) + §117 gate
- **Acceptance:** отчёт владельцу короткий и понятный, разделы §116: «Что исправили» (простыми словами), «Автоматические бюджеты» (какие active модели, какой capacity source), «Summary incident» (почему 21K truncation и timeout, что после fix), «Frontend» (Analytics, Polygon, Bottom nav, Human-readable settings), «Что уже работает в production из MCA» (название, что делает, активно/фундамент — §36, §54); технические SHA/ADR/tests — ниже как evidence, не вместо человеческого объяснения (§116); разбор инцидента §111 — отдельно, простыми словами, с обязательными ответами на 8 вопросов (1: почему L1 ограничен ~21K; 2: почему выкинуты 81 сообщение; 3: physical limit или artificial cap; 4: почему primary timeout; 5: почему fallback timeout; 6: сработал ли L1_FALLBACK_PACKAGE; 7: сформировалось ли Summary; 8: как новая Auto Budget система изменила бы этот run); НЕ одним «исправлено» (§111); «Автобюджеты» раздел §54 (какая модель для Direct, окно, откуда известно, auto budget, fallback/override — без внутренних коэффициентов); «Что уже реально работает в production» §36 (что делает, активна ли, видит ли пользователь, закончена ли; НЕ список импортов/SHA/модулей); финальная строка `ASAP-3 production acceptance complete; current_task continuation unblocked.` — только после выполнения §55 + §112–§116 (§117); до этого фича остаётся в corrective acceptance state (§117).
- **Секции:** §36, §54, §111, §116, §117. **Зависит от:** T-4089. **Риски:** низкий.

---

## Traceability: секции ТЗ → задачи → тесты

| Секции | Тема | Задачи | Тесты/проверки |
|---|---|---|---|
| §Цель, §1, §2 | Контекст, 4 понятия бюджета | T-4051 | audit.md |
| §3–§8 | Capacity Resolver | T-4052, T-4053 | T-4054 (§40, §41) |
| §9–§12 | Auto Budget Resolver | T-4055, T-4056 | T-4056 (diagnostics), T-4087 (estimated/actual) |
| §13, §14 | Model Slots + наследование | T-4058, T-4059 | T-4057 (§42), T-4087 (§45 inheritance) |
| §15, §16 | Per-chat Context Policy, нет VIP path | T-4060 | T-4060 (2 chat_id), T-4087 (§52) |
| §17 | Разводка тумблера | T-4061 | T-4061 (§46) |
| §18, §19, §20, §21, §22 | Miniapp Budgets/Advanced/Direct UI | T-4064, T-4065, T-4066 | T-4087 (§43, §44), §52 Browser |
| §23 | Summary budgets → auto resolver | T-4069 | T-4074 |
| §24–§27 | Analytics секция/payload/UI/source badges | T-4075, T-4076 | T-4076, T-4087 (§45) |
| §28, §29 | Status compact + один источник | T-4077 | §52 Browser |
| §30–§33 | LLM REACT, SILENT 🗿, Force Direct | T-4078 | T-4079 (§47, §48), §53.8–10 |
| §34 | Verbatim episode 200+ | T-4062 | T-4062 evidence |
| §35 | Dynamic 16000 soft target | T-4063 | T-4063 |
| §36, §54 | Production-отчёт простыми словами | T-4090 | отчёт |
| §37, §38, §39 | Source of truth, invalidation, override semantics | T-4052, T-4053, T-4056 | T-4054 (model switch) |
| §40, §41 | Тесты resolver/local runtime | T-4054 | — |
| §42, §102 | Fallback model recompose | T-4057, T-4074 | T-4057, T-4074(5) |
| §43–§46 | Miniapp/Advanced/Analytics/separation тесты | T-4060, T-4061, T-4064, T-4066, T-4087 | T-4087 |
| §47, §48 | Тесты reactions/SILENT | T-4079 | — |
| §49, §50 | Observability + metrics | T-4085 | T-4085 |
| §51 | Миграция UI/настроек | T-4061 | T-4061 |
| §52 | Browser Verification | T-4087, T-4084 | §52 чеклист |
| §53 | Production acceptance | T-4089 | 11 пунктов |
| §55 | DoD v1 (пп.1–25) | mapping ниже | — |
| §56–§61 | Polygon flicker/glow | T-4080 | §61 visual acceptance |
| §62–§69 | Polygon живая форма/diagnostics | T-4081 | §100 regression |
| §70–§73 | Analytics bug/discoverability/fail-open | T-4082 | §71 чеклист, §99 |
| §74–§76 | Incident logs, 21001, Summary → resolver | T-4069, T-4073 | T-4074(1) |
| §77, §78 | hybrid keys → Advanced, миграция | T-4069, T-4072 | T-4074(6) |
| §79 | Migration warnings | T-4086 | T-4086 |
| §80–§82 | Timeout policy / fallback package | T-4073 | T-4074(5) |
| §83–§89 | Human-readable UI / copy | T-4067, T-4072, T-4076 | §106 review pass |
| §90–§94 | Bottom nav геометрия | T-4083 | §94 invariants |
| §95–§98 | Browser Use обязателен, viewports, evidence, SaveBar | T-4083, T-4084 | §96/§97/§98 |
| §99–§101 | Playwright regression / polygon / Summary budget | T-4082, T-4084, T-4074 | §99, §100, §101 |
| §103–§106 | Timeout stats, группировка, состояния, copy review | T-4073, T-4076, T-4067 | §106 (Reviewer pass — отразить в review.md фичи) |
| §107 | Browser Use как интерактор | T-4084 | — |
| §108–§111 | Production acceptance frontend/Summary/human/incident | T-4089, T-4090 | §108–§111 |
| §112 | DoD v2 (пп.26–58) | mapping ниже | — |
| §113 | Workflow gate | порядок работ (шапка) | — |
| §114 | Вопросы Architect | отвечены в reconcile (см. ниже) | — |
| §115 | Запрет hotfix'ов | критерии T-4080–T-4083 | — |
| §116, §117 | Финальный отчёт, финальный gate | T-4090 | §116 разделы |
| §118–§126 | Summary Window contract, chunking | T-4068, T-4070 | T-4074 |
| §127–§129 | Coverage metrics, no skipped, окно > budget | T-4071 | T-4074 |
| §130 | Смена окна меняет workload | T-4074(4) | §145 |
| §131, §132, §133 | Общий resolver для всех Smart stages, coverage policy | T-4055, T-4056, T-4075 | T-4076 (§134) |
| §134, §135, §136 | Coverage Policy в Analytics, полнота, Summary UI | T-4076, T-4072 | T-4076 |
| §137, §138 | Manual cap semantics, название | T-4072 | T-4074(6) |
| §139, §140, §141 | Timeout≠chunk, fallback full set | T-4073, T-4074 | T-4074(5) |
| §142–§145 | Регрессии 369/локальная/смена модели/12h | T-4074 | — |
| §146 | DoD v3 (пп.59–77) | mapping ниже | — |

## DoD mapping

- **§55 (1–25)** → capacity auto (1–3): T-4052/T-4053/T-4054; budget централизован + safety ×1 + stage reserve (4–6): T-4055/T-4056; frontend не считает (7): T-4059/T-4056; обычный админ (8): T-4064/T-4066; Advanced overrides (9): T-4065; context/quota разделены (10, 11): T-4061; Analytics autobudgets (12): T-4075/T-4076; Status summary (13): T-4077; source visible + fallback warning (14, 15): T-4053/T-4064/T-4076; Unlimited generic + второй chat (16, 17): T-4060; episode 200+ (18): T-4062; REACT LLM (19): T-4078/T-4079; SILENT 🗿 (20): T-4078/T-4079; Force REPLY (21): T-4078/T-4079; fallback recompose (22): T-4057; prod-фичи простыми словами (23): T-4090; тесты без регрессий (24): T-4087; corrective deploy + smoke (25): T-4088/T-4089.
- **§112 (26–58)** → Polygon flicker/pulse/seed/composition/drift/reduced (26–35): T-4080/T-4081/T-4084; Analytics route/entry/fail-open (36–38): T-4082; Summary L1/L2 на общем resolver + нет 21001 в Auto (39–41): T-4069; manual cap в Advanced (42): T-4072; миграция custom без потерь (43): T-4069; migration INFO (44): T-4086; timeout vs pressure (45, 46): T-4073/T-4076; human-readable labels / tokens≠слова / без raw keys (47–49): T-4067; bottom nav / SaveBar / viewports / desktop / click-through / Playwright / screenshots (50–56): T-4083/T-4084/T-4087; incident 369 без 21001 (57): T-4074; отчёт по инциденту (58): T-4090.
- **§146 (59–77)** → window=source set (59–61): T-4068/T-4069; один pass если влезает (62): T-4070/T-4074(1); lossless chunking (63, 64): T-4070; overlap dedup (65): T-4070; cross-chunk themes (66): T-4070; L2 не теряет темы (67): T-4070; coverage измеряется / 100% / нет skipped (68–70): T-4071; manual cap per-request (71): T-4072/T-4074(6); fallback rechunk full set (72): T-4074(5); deterministic fallback полный set (73): T-4073/T-4074; смена окна/модели без ручных настроек (74, 75): T-4074(3, 4); все Smart stages через resolver (76): T-4056; coverage/overflow policy per stage (77): T-4055/T-4058.

## Вопросы @Architect (§114 + производные) — ВСЕ ОТВЕЧЕНЫ в reconcile

**Статус: закрыты.** Architect narrow reconcile завершён: ответы Q1–Q12 — spec.md §2, контракты — разделы 3–9, санкции — раздел 10, ADR-1028-3 Accepted (binding). Ниже — исходная постановка (история, не открытые блокеры):

1. **Q1 Polygon flicker (§114, §58):** подтверждается ли `TOPO_HZ=4` + `TOPO_FADE_MS=320` как основной brightness reset; какие ещё слои дают заметную amplitude → **блокирует T-4080**.
2. **Q2 Polygon motion (§114, §63–§65):** схема production-random scene seed (crypto RNG) + global scene transform с сохранением deterministic-тестов → **блокирует T-4081**.
3. **Q3 Analytics (§114, §70):** почему реальный клик «Аналитика» не открывает screen — routing/render exception/RBAC/IA/network; ответ с Browser Use-измерениями → **блокирует T-4082**.
4. **Q4 Summary 21001 (§114, §75):** подтверждение точной арифметики текущего L1 budget (`30000 → safe_budget − system − 4000 ≈ 21001`) → **вход T-4055/T-4068/T-4069**.
5. **Q5 Summary autobudget (§114, §76, §129):** как подключить Summary L1/L2 к общему resolver, не смешивая soft output targets с physical context → **блокирует T-4055/T-4068**.
6. **Q6 Bottom nav (§114, §92):** какие реальные значения viewport/safe-area дают clipping; измерения Browser Use/Playwright; выбор единственной модели геометрии → **блокирует T-4083**.
7. **Q7 UI copy (§114, §89):** перечень budget/config labels, которые технически неверны/непонятны → **вход T-4067**.
8. **Q8 (производный, §6):** vLLM — какой источник `max_model_len` для наших deployments (config introspection vs registry+developer override); состав adapters первого релиза (OpenRouter/llama.cpp/Ollama/vLLM/generic) → **вход T-4052**.
9. **Q9 (производный, §7):** TTL кэша capacity для remote catalogs — значение по умолчанию и где настраивается (env/Advanced); подтверждение, что cache TTL не попадает в обычный UI без нужды → **вход T-4052/T-4065**.
10. **Q10 (производный, §13):** финальный состав slots для prod (video/text LLM stages, использующие composer — в матрице или нет; `summary.legacy` применим ли) → **вход T-4058**.
11. **Q11 (производный, §30):** санкция формата structured output Decision Maker (поле `reaction` в существующем schema; allowed-reactions список — источник и размер) и kill-switch для LLM-REACT на случай деградации → **вход T-4078**.
12. **Q12 (производный, §118/§130):** семантика «перестроить Summary за период» (explicit rebuild) — входит ли в exhaustive-contract этого pass'а или остаётся текущим поведением → **вход T-4068**.

## [ARCH]-зависимости — reconcile завершён (spec.md §2 Q1–Q12 + контракты разделы 3–9 + санкции раздел 10; ADR-1028-3 Accepted)

- **T-4052** (capacity spec; Q8/Q9 отвечены) → T-4053, T-4054, T-4056, T-4075.
- **T-4055** (auto budget spec; Q4/Q5 отвечены) → T-4056, T-4057, T-4069, T-4070.
- **T-4058** (slots spec; Q10 отвечен — состав binding) → T-4059, T-4064, T-4075.
- **T-4068** (summary coverage spec; Q4/Q5/Q12 отвечены, D3/D4) → T-4069, T-4070, T-4071, T-4072, T-4074.
- **Q1** → T-4080; **Q2** → T-4081; **Q3** → T-4082 (статический ответ F11/NAV_ITEMS_V2; Browser-Use 12-шаговые измерения остаются в acceptance); **Q6** → T-4083; **Q7** → T-4067; **Q8/Q9** → T-4052/T-4065; **Q11** → T-4078; **Q12** → T-4069.
- **Санкции — УТВЕРЖДЕНЫ (spec 10 + ADR-1028-3):** Δ каталога ≠ 0 санкционирована точно: +1 ключ `models.chat_context_window_override`, 6 переименований labels/группы (§77/§89); ожидаемые F8-числа **483/423/458/105/103/21 → 484/424/459/105/103/21** (фиксируются фактическим харнессом, переиздание атомарное). Δ DDL = 0 — подтверждено (coverage/бюджеты/реакции через события). Δ зависимостей = 0; R17/R18 без изменений. Kill-switch реестр (7 env, default ON) и +5 событий (28→33, без коллизий) — см. «Контракты Architect» в шапке. Owner контрактов — Architect; изменение любого D — только через re-review (инвалидация approval).

## Ранее открытые пункты — закрыты reconcile, перенесены в acceptance задач

- Рестарт-семантика §38 → T-4052 (п.5: «если restart объективно обязателен — UI честно сообщает») и T-4053 (acceptance).
- Диапазоны mesh size compact/medium/large §66 → T-4081 (acceptance: «диапазоны корректируемы по визуальному тесту»; стартовые 45–65/65–90/90–115% из spec Q2).
- Тестовая смена model/config на проде §53.6 → T-4089 (п.6: предварительно согласовать с владельцем временную тестовую модель).
- RBAC Analytics — подтверждено spec Q3: «только global admin» остаётся (текущий product contract) → T-4082/T-4075.
- Возврат исходных значений per-chat политик после acceptance-прогонов на втором chat_id — в acceptance T-4060 («вернуть исходное», §16).
