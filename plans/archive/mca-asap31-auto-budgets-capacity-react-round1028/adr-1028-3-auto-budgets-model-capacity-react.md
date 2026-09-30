# ADR-1028-3 — Auto Budgets: Model Capacity Resolver и единая бюджетная модель (ASAP-3.1)

- **Статус:** Accepted (Architect narrow reconcile, §113) → **prod-validated 2.58.37** → **incident-fixed 2.58.38** (addendum D-доп., reconcile 30.09.2026). История статуса — раздел «Прод-валидация и инцидент-аддендум».
- **Дата:** 2026-09-30
- **Feature:** `mca-asap31-auto-budgets-capacity-react` (R3), release 2.58.37; инцидент-фикс 2.58.38
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

---

## Прод-валидация и инцидент-аддендум (D-доп.) — reconcile 30.09.2026

_История решений D1–D8 сохранена выше без изменений; ниже — только статус-история и addendum, не переписывающий исходные D. Заголовок не является новым ADR: это addendum/errata к ADR-1028-3._

### История статуса

1. **Accepted (design)** — narrow reconcile §113 (реализация D1–D8, санкции Δ каталога/GROUPS/события).
2. **Approved FOR RELEASE (Reviewer round 2)** — rework H-ASAP31-1/-2 + M-1; binding Reviewed-Commit `fafbad8`, WTH `1b9fd477…`.
3. **Prod 2.58.37 выпущена (deploy VERIFIED)** — feat `1f8a0f3`, docs `df0387d`; прод-валидация Auto Budgets/Модель-Слотов/Аналитики/Summary-Chunking подтверждена.
4. **ИНЦИДЕНТ (прод 2.58.37)** — пустая публикация крона `msg 1120810`.
5. **Approved ready-to-redeploy (Reviewer round 3, incident-fix)** — WTH `c8982d63…` → commit-time `67846e1c…` (31-path version-metadata drift, код фикса байт-идентичен).
6. **Prod 2.58.38 выпущена (deploy VERIFIED)** — feat `5ff1eac` (код фикса), docs `6c5f9b9`, deploy-doc `7881f93`; инцидент-класс закрыт; binding не инвалидирован (review привязан к коду, код фикса байт-идентичен ревью-манифесту).

### Инцидент 2.58.37 → фикс 2.58.38 (D-доп.)

**Симптом (прод, крон 19:00 UTC 29.09.2026):** окно 1089 сообщений → L1 `unknown_field` → correction retry закончился timeout обоих провайдеров → ветка «L1 непригоден» вызвала `build_fallback_package` **без `budget`** → `_enforce_budget` применил статический потолок (hot `summary_hybrid_context_tokens=30000` → ≈18661) и вытеснил ЕДИНСТВЕННУЮ тему ЦЕЛИКОМ вместе с хронологией → пакет `threads=[]` со статусом `truncated` (deliverable) прошёл delivery-гейт → L2 опубликовал мета-текст «пакет пуст» (`msg 1120810`).

**Корневая причина (класс):** деградационная ветка вызывала fallback-сборку в обход резолверного бюджета (D2/D5), а `_enforce_budget` не различал «вытеснить тему» и «обрезáть её содержимое» → материально пустой пакет мог быть передан в L2 под publish-статусом.

**Решение инцидента — D-доп. (три части, release 2.58.38):**

- **D-доп.1 — budget passthrough на L1-unusable ветке.** Ветка «L1 непригоден» передаёт `budget=l2_budget` — тот же resolver-бюджет, что и нормальный/defensive пути (все 4 call-site Summary несут resolверный бюджет; dry-run — исключение, публикации не делает). Инвариант DoD-76/§131/§37 (все стадии из одного резолвера) восстановлен на деградационных путях.
- **D-доп.2 — guard «последняя/единственная тема НИКОГДА не вытесняется».** Целые темы вытесняются только пока `len(threads) > 1`; содержимое последней темы режется по бюджету (сначала fragments старые→новые, затем chronology) со структурой темы; возврат `_enforce_budget` расширен 5-м элементом `skipped_chronology` (метрика `skipped_chronology_count`). При пустом по материалу fallback-пакете при непустом источнике — громкое `SUMMARY_COVERAGE_DEGRADED {reason="near_empty_package"}` + WARN `PACKAGE_NEAR_EMPTY` (fail-open телеметрия). Основной путь при пустом материале остаётся fail-closed (`STATUS_EMPTY`, не deliverable).
- **D-доп.3 — delivery-gate: материально пустой пакет → LEVEL-3 Legacy, не L2.** Fallback-пакет, пустой по материалу (0 fragments ∧ 0 chronology) при непустом source-окне, НЕ публикуется как обычное саммари → маршрут LEVEL-3 `_legacy_fallback("empty_fallback_package")` (published-guard; при провале Legacy — `STATUS_DEGRADED`, **не** публикация мета-текста).

**Инварианты D-доп. (обязательны):** два независимых слоя защиты (guard структуры + delivery-гейт), каждый покрыт мутационно-чувствительными тестами; `run_l2` принимает на вход только пакеты со статусом `ok`/`truncated`; непустое окно НИКОГДА не завершается публикацией мета-текста про пустоту; coverage-деградация всегда громкая (`SUMMARY_COVERAGE_DEGRADED`), не тихий успех.

### Прод-валидация 2.58.38 (evidence)

- Deploy VERIFIED: буст 2.58.37→2.58.38, прод `/healthz` 2.58.38, health 200, Δ DDL=0, сиды не требовались; инцидент-регрессия на проде **27 passed** (`test_summary_incident_empty_package_asap31.py` + `test_summary_coverage_asap31.py` + `test_l2_budget_asap31.py`).
- Причинный реплей по прод-логам (до фикса): run `d1062dcd` 1089 → `L1_FALLBACK_PACKAGE … fragments=0 chronology=0` → `L2_START` → `PUBLISH_RICH_COMPLETE message_id=1120810`; после фикса прогон 01:00 UTC при OFF-флаге — штатный `LEGACY_FALLBACK` (публикация реального саммари `msg 1121343`), пустого мета-текста нет.
- Флаг `SUMMARY_COVERAGE_CHUNKING_ENABLED` возвращён в дефолт кода **ON** (политика владельца «все функции включены»).
- Evidence: `plans/features/mca-asap31-auto-budgets-capacity-react/{review.md (round 3), evidence.md, deployment.md, review-evidence-oversight-blank.png}`; ARCHITECTURE §104.

### Остаточные (non-blocking, backlog)

L-ASAP31-4 (dry-run без resolver-бюджета — точность preview), L-ASAP31-6 (телеметрия-косметика `coverage=0.0` near-empty), M-ASAP31-2 (tool-path Direct без fallback-пересборки), carry-over L-ASAP31-1/2/3; отдельная задача — семантика `FACT_PACKAGE_TRUNCATED` (per-topic cap vs бюджетный потолок); владельцу — пустая публикация `msg 1120810`. Зарегистрированы в `plans/backlog.md`.

_Addendum внесён в reconcile 30.09.2026 (docs-only). Reviewed/deployed код фикса байт-идентичен ревью-манифесту — approval не инвалидирован._
