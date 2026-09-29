# ADR-1028-3 — Auto Budgets: Model Capacity Resolver и единая бюджетная модель (ASAP-3.1)

- **Статус:** Accepted (Architect narrow reconcile, §113)
- **Дата:** 2026-09-30
- **Feature:** `mca-asap31-auto-budgets-capacity-react` (R3), release 2.58.37
- **Связанные:** ADR-1028-2 (ASAP-3: Direct consumer-side capacity D1/D2), ADR-1027-10 (двухконтурный Summary), ADR-1019-8 (safe_budget/token_counter)

## Контекст

После ASAP-3 в проде сосуществуют три независимых бюджетных механизма: Direct использует `services/model_capacity.py` (карта окон + env + fallback 16384, кэш без инвалидации, preemptive min(primary, fallback)); Summary L1/L2 использует статический `limits.summary_hybrid_context_tokens` (default 30000 → 21001 после вычетов), не зная ничего о реальном окне выбранной модели — прод-инцидент: 369 сообщений окна 6 ч, 81 выброшено до запроса, `limit=21001`. Miniapp сводит в один тумблер context policy и суточные квоты (`budgetsUnlimitedKeys`, 7 ключей). REACT выбирает реакцию детерминированным классификатором. Дополнительно: IA v2 навигация потеряла пункт «Аналитика» (NAV_ITEMS_V2 без oversight), полигональный фон мигает из-за topology rebuild 4 Гц, bottom nav обрезается из-за guessed-offset геометрии.

Владелец (§113) требует НЕ огромный redesign, а ревалидацию и сведение перед implementation.

## Решение (D1–D8)

**D1 — один Model Capacity Resolver как единственный источник окна.** Резолв по реальной тройке provider/base_url+model с детерминированным precedence: developer override (Advanced, `models.chat_context_window_override`, 0=Auto) → runtime metadata → provider catalog → verified registry → conservative fallback (последним, аварийно, с событием `MODEL_CAPACITY_FALLBACK` и UI-badge). `effective = min(runtime, provider/model)`. Альтернативы: (а) оставить карту+env — отклонено: неизвестные модели молча получают 16384 (§8 прямо запрещает), env как нормальный путь противоречит §4; (б) универсальный metadata-parser — отклонено §6 (только adapters по реальным подключениям). Первого релиза состав адаптеров: registry (прод — generic OpenAI-compatible endpoints), OpenRouter catalog, llama.cpp `/props`, Ollama `context_length`, vLLM config/registry+override.

**D2 — Stage Auto Budget Resolver поверх capacity, формула без скрытых слоёв.** `effective_window − mandatory − output_reserve(stage) − safety_reserve(×1) = auto_input_budget`; policy-слой −1/0/>0 сохранён. Safety применяется ровно один раз (прецедент инцидента 39371→27826: двойной множитель уже убит в ADR-1028-2, инвариант переносится на все стадии). Альтернатива «статические 30000 с запасом» — отклонена: это и есть причина 21001.

**D3 — Summary Window = exhaustive coverage контракт.** Configured window определяет полный source set; всё помещается → 1×L1; не помещается → lossless chunking (каждый source ID ≥1 primary chunk, overlap с дедупом по stable ID, reply continuity, oversized segmentation); merge не теряет темы; L2 не теряет уникальные темы; coverage измеряется (100% = успех, иначе явный degraded); `skipped=N` из-за budget исчезает как normal behavior; timeout ≠ drop (retry → fallback → rechunk ПОЛНОГО набора); manual cap = размер одного L1-запроса, не объём обработки; LLM-вызовы определяются физикой, не искусственным бюджетом. Альтернатива «увеличить 30000 до 100000» — отклонена §115 (параметрический hotfix, не устраняет причину).

**D4 — граница soft targets и physical context.** Входная сторона (Summary) — exhaustive/физическая; выходная (длина статьи: response_mode/target_chars/§99) — semantic policy без изменения. Manual cap ≤ размера окна не уменьшает coverage. Смешение запрещено.

**D5 — Model Slots registry; бюджет привязан к стадии.** Минимальный состав: direct.primary/fallback, summary.l1/l2, summary.legacy (условный), intel.background/reflection; один model id — несколько slots; наследование отображается, не дублируется; frontend ничего не вычисляет. Fallback-модель получает recomposed payload под своё окно (preemptive-min из текущего кода снимается).

**D6 — разводка четырёх понятий бюджета.** Context Policy (Dynamic/Unlimited/Advanced Cap через существующий derive `limits.chat_context_budget_tokens`) ≠ суточные квоты (отдельная «Без суточных квот»: 4 quota-ключа) ≠ worker limits ≠ capacity. Старый 7-ключевой тумблер разбирается с non-destructive миграцией. Никаких VIP/hardcoded chat path; acceptance на втором chat_id.

**D7 — REACT: реакцию выбирает LLM в том же structured output; SILENT→🗿 остаётся единственным hardcode.** Детерминированная матрица сохраняет владение action (2-вызовность System 2 не нарушается); LLM выбирает только emoji при REACT из allowed Telegram-набора; невалидно/нет → детерминированный fallback; kill-switch `DIRECT_LLM_REACTION_ENABLED` + per-chat `flags.chat_decision_reactions_enabled` → OFF = текущее поведение. Force keyword → всегда REPLY.

**D8 — фронтенд-контракты.** Analytics: один route `#/oversight`, `oversight` возвращается в `NAV_ITEMS_V2` (sidebar + «Ещё»), каждый блок fail-open, human-first русские карточки поверх нового `GET /api/analytics/context-budgets` (без второго usage store); Status — компакт из того же резолвера. Polygon: scene seed через `crypto.getRandomValues` + детерминированный PRNG (тесты — через `?bgseed`), topology стабильна с редким crossfade-rebuild, амплитуды свечения снижены по размаху, diagnostics-поля. Bottom nav: одна модель геометрии — shell = измеренная видимая высота (в Telegram `viewportStableHeight`/`viewportHeight`, вне — `visualViewport`, fallback `innerHeight`), inset ровно один раз на `.bottom-nav` как flex-child; guessed-offset-паттерн уходит.

## Санкции

- **Δ каталога ≠ 0 санкционирована:** +1 ключ (`models.chat_context_window_override`), 6 переименований labels/группы (tokens≠«слова», §77/§89/§138). Ожидаемые F8: 483/423/458/105/103/21 → **484/424/459/105/103/21** (фиксируются фактическим харнессом, переиздание атомарное).
- **Δ DDL = 0** (coverage/бюджеты/реакции — через события); **Δ зависимостей = 0**; R17/R18 без изменений.
- **Kill-switch реестр (env-only, default ON):** `MODEL_CAPACITY_RESOLVER_ENABLED`, `AUTO_BUDGET_RESOLVER_ENABLED`, `SUMMARY_COVERAGE_CHUNKING_ENABLED`, `DIRECT_LLM_REACTION_ENABLED`, `UI_BUDGETS_SPLIT_ENABLED`, `ANALYTICS_CONTEXT_BUDGETS_ENABLED`, `CONFIG_MIGRATION_INFO_LOGGING_ENABLED`. Polygon/bottom-nav — без флагов (rollback revert-тегом, прецедент UI-rework).
- **Observability:** +5 новых событий (`MODEL_CAPACITY_RESOLVED`, `AUTO_CONTEXT_BUDGET`, `DIRECT_REACT`, `SUMMARY_L1_CHUNKED`, `SUMMARY_COVERAGE_DEGRADED`), аддитивные поля у существующих; коллизий с закрытым enum (28) нет.

## Последствия

- Прямо закрывает прод-инцидент 21001/369 и класс «молчаливых 16384»; смена модели/окна 6↔12 ч больше не требует ручных token knobs (§144/§145 регрессии).
- Стоимость: перепись model_capacity, chunker, разводка UI-тумблера, два frontend-фикса; компенсируется parity OFF-путей всех семи kill-switch'ей и регрессиями §40–§48/§142–§145.
- Откат: soft (флаги → байт-в-байт прежнее поведение) / cold (annotated-тег `pre-2.58.37` → revert). Owner контрактов — Architect; изменение любого D — только через re-review (инвалидация approval).

## Затронутые контракты

ADR-1028-2 D1/D2 (расширяется с Direct-only на все стадии; OFF-путь сохраняет байт-в-байт старый резолв), ADR-1027-10 §11 (hybrid-ключи получают Auto-семантику; Legacy-контур не трогается), §93-примитивы `estimate_and_split` (расширяются до полного chunk-контракта, эвристик нет), agentic-events enum (аддитивно 28→33), TAB_RULES/NAV (oversight в NAV_ITEMS_V2; RBAC global-admin без изменений).
