# CFG-06 W2 — suitability gate + ContextualClaimResolution: что сделано

Дата: 20.10.2026. База: deployed `29cc49ba` + незакоммиченные W0/W1-правки того же лейна.
КОММИТ НЕ СОЗДАВАЛСЯ (коммитит оркестратор). Дельта W2:

| Файл | Тип | Суть |
|---|---|---|
| `services/factcheck_suitability.py` | НОВЫЙ | детерминированный многоступенчатый gate `fsg1` + ContextualClaimResolution (БЕЗ LLM-вызовов и БЕЗ правок промпт-канонов) |
| `handlers/factcheck.py` | правка | `_fetch_context_with_gate` (один гейт для ОБЕИХ развилок, 06B.1), ранний выход `no_claim_after_context` → короткая реплика без поиска (обе ветки) |
| `services/factcheck_context.py` | правка | аддитивно: `tokenize_for_relevance` (публичный алиас), `window_override`/`skip_cache_read` в `build_wide_context` (дозапрос needs_context) |
| `services/smartmodule_phrases.py` | правка | пул `FACTCHECK_NO_CLAIM_PHRASES` (короткая реплика «проверять нечего», в стиле существующих пулов) |
| `config/settings.py` | правка | `FACTCHECK_SUITABILITY_GATE_ENABLED` (env, default **False**) |
| `tests/test_factcheck_gate_cfg06.py` | НОВЫЙ | 18 CONTRACT-тестов (TEST-LIFECYCLE: CONTRACT owner=CFG-06) |

## Контракт флага

- `suitability_gate_enabled()`: hot `flags.factcheck_suitability_gate` → env `FACTCHECK_SUITABILITY_GATE_ENABLED` → **False**.
- Гейт активен ТОЛЬКО при W1-широком контексте ON **И** gate ON (у гейта должен быть структурированный ConversationContext; без него — прежний путь). Оба флага default OFF → прод-путь байт-паритетен (тест `test_gate_off_byte_parity`).
- Включение — этап W3 (объединение флагов миграции).

## Как работает gate (детерминированный, 06J.1)

Stage 1 (дешёвый, НИКОГДА не отказ): структурное профилирование — предикат (числа/даты/лексикон фактических сказуемых/копула «X — это Y» при ≥2 содержательных токенах/цитата), субъективные/предиктивные маркеры, референциальность (`is_referential_claim` + местоименная эллиптика). Мат/ирония НЕ влияют на предикат (06J.4 — не regex-блокиратор).

Stage 2 (ContextualClaimResolution, 06I.6): reply-анцедент → тема спора по стеммам (лёгкий стемминг для морфологии: живой/живым) с фильтром «кандидат-тезис = есть предикат или ≥6 токенов» (реакции «это бред» тезисами не становятся) → доминирующий спор по дискуссионным маркерам для пустого зонда («ну и что там?»). Два сопоставимых кандидата → `ambiguous_needs_clarification` (чужой тезис не приписывается); автор анцедента сохраняется в provenance (author + tg-якорь).

Stage 3 (решение): типизированный `SuitabilityDecision` — decision (`checkable_in_context` / `needs_context` / `ambiguous_needs_clarification` / `no_claim_after_context` / `context_unavailable`), claim_type (10 типов 06B.2), claim_items с provenance, scope (`none`/`web`/`chat_history`/`web_and_chat`), reason_code, confidence, target_ref, temporal_hint (датный клейм (ж) → существующий temporal-путь, не второй фактчек), gate_version. Асимметрия 06J.2: no_claim ТОЛЬКО после изучения контекста; неуверенность → checkable-фолбэк.

Live-протокол: `evaluate_with_expansion` — needs_context → ОДНО ограниченное расширение окна (потолок W1 не превышается) → повторное решение; второй needs_context честно деградирует в `context_unavailable` (НЕ отказ, pipeline продолжается как сегодня).

## Маршрутизация в handler (за флагом)

- `no_claim_after_context` → `send_chunked_reply(random.choice(FACTCHECK_NO_CLAIM_PHRASES))`, БЕЗ поиска/LLM/кеш-записи (идемпотентность 59.2 сохранена). Граница W2-лейна: реплика готовая (промпт-каноны заморожены); персона-озвученная короткая реплика через `speech_owner_block` — W3 (единый Writer).
- Остальные решения → pipeline продолжается без изменений (needs_context уже отработал расширением; ambiguous/checked — как сегодня).

## Корпус и метрики (06J.5) — `w2-corpus.json` / `w2-corpus.md`

40 проб = кейсы а–з + негативы (е2 мат+тезис, е3 сарказм) × фикстуры 20/100/200/500 сообщений; протокол двух проходов.

| Метрика | Значение |
|---|---|
| routing_accuracy | **1.0** (40/40) |
| false_refusal_rate | **0.0** |
| false_contextual_claim_rate | **0.0** |
| unnecessary_search_rate | **0.0** (no_claim всегда scope=none) |
| target_attribution_errors | **0** (анцедент сохраняет автора; case в: автор Петя, не Вася) |
| relevant_context_recall | **1.0** (тезис 50 сообщений раньше находится) |

Ход проектирования: 1 промежуточное расхождение (case г @ fixture 20) — дефект ФИКСТУРЫ (второй спор не влезал в фикстуру), не гейта; исправлено в фикстуре, не в движке.

## Тесты и регресс

`w2-red-green.txt`: RED (ImportError без модуля) → GREEN 18/18 gate-тестов; W1-регресс 11/11; суммарный фокусированный прогон затронутых сьютов (gate, W1-context, handlers, deep-context, unified-core route-coverage 18 CONTRACT, service, settings, smart_cache) = **238 passed / 0 failed**. Известные 2 pre-existing v35 фейла asap7_direct_settings — вне диффа, не тронуты.

## Что осталось до W3

- Персона-озвученная короткая реплика (speech_owner_block) и gate/CR-промпты — при разморозке `factcheck_prompts.py` (W3: единый Writer).
- Объединение W1/W2-флагов в один миграционный рубильник, байт-паритет legacy-ветки, egress-whitelist, route-coverage расширение — W3.
- `ambiguous_needs_clarification` сейчас фиксируется в решении (и логе), но не меняет пользовательский ответ — продуктовое уточнение (короткий вопрос владельцу чата) решается в W3/W5.
