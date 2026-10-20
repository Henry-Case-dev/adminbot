# CFG-06 W4 — планировщик проверки + структурный evidence: что сделано

Дата: 20.10.2026. База: deployed `29cc49ba` + незакоммиченные W0–W3 правки лейна.
Параллельная полоса W5 (renderer/доставка) — её файлы/зоны не затронуты (проверено git status: изменения только в скоупе W0–W4).
КОММИТ НЕ СОЗДАВАЛСЯ.

| Файл | Тип | Суть |
|---|---|---|
| `services/factcheck_planner.py` | **новый** | RetrievalPlan/SearchQuery, осмысленные запросы из claim_items (фикс 06A.4), privacy-фильтр, структурный evidence → замороженные `EvidenceRef`/`EvidenceMap` (W3), SafeFetcher-REUSE |
| `services/factcheck_orchestrator.py` | правка (ТОЛЬКО моя зона) | анкор planning-стадии: `build_retrieval_plan` после gate-маршрутов; анкор EvidenceMap: `execute_retrieval` заполняет пустой EvidenceMap legacy-ветки ДО presentation (temporal-ветка с своими ev-N не перезаписывается) |
| `tests/test_factcheck_planner_cfg06.py` | **новый** | 15 CONTRACT (TEST-LIFECYCLE: CONTRACT owner=CFG-06) |

Не тронуты: `services/factcheck_service.py`, `services/temporal_factcheck.py`, `services/search_aggregator.py`, каноны промптов, Presentation-зона (W5), файлы тестов W1–W3/W5. Замороженные схемы не менялись (фриз-тесты W3 зелёные без правок).

## План-механика (кратко)

1. Вход: `SuitabilityDecision` (+claim_items) + ConversationContext (авторы для privacy).
2. Gate: планировщик — часть v2 (`flags.factcheck_pipeline_v2`, default OFF); OFF / scope без web / нет клейма → **None = ноль платных запросов** (OFF-паритет).
3. Запросы (≤3, ≤200 симв., цели различаются): `entity_check` (сущности+термины) → `numeric_verification` (числовые фразы «120 мм») → `temporal_context` (+годы) → `claim_origin` (цитата ≥12 симв. + поиск первоисточника). Фикс 06A.4: запрос НЕ дословный слайс клейма (тест-инвариант).
4. Privacy (06G.3): имена участников чата (из ConversationContext) удаляются из запросов, `dropped_privacy` в плане/логе.
5. Выполнение: существующий `SearchAggregator.search` (REUSE) → блоки «title/snippet/url» парсятся в `EvidenceRef` (URL **отдельно** от support, 06D.4); до 2 первоисточников через **существующий `SafeFetcher.fetch_text`** (REUSE, инъекция для офлайн-тестов — прецедент `enrich_evidence_dates`): выдержка (первый абзац ≥80 симв., cap 600, теги срезаны) + дата публикации через `tf.parse_publication_date`, `source_kind="primary"`.
6. `EvidenceMap`: стабильные ID `ev-N` ТЕКУЩЕГО прогона, allowlist = ID прогона (консистентность тестом); ошибки запросов/фетчей — честная деградация, пусто → None.

## Интеграция в оркестратор (якорь §6)

- Plan-стадия: после gate-маршрутов (no_claim/ambiguous отвечают ДО планировщика — ноль лишних расходов); лог queries/intents/privacy_dropped.
- Evidence-стадия: только когда ветка не дала своих evidence (envelope-ветка с ev-N — не трогается, тест) и scope требует web и `service.aggregator` существует. Аргументы `service.check_claim` НЕ меняются (байт-паритет W3 сохранён — тест в anchor-наборе).
- Граница W4→W6: планировщик в W4 даёт **структурированный evidence-слой presentation** (аддитивно, после вердикта); перенос поиска в вычисление вердикта «строго по плану ДО вердикта» и бюджеты — W6-интеграция (осознанная граница, документирована).

## Тесты (числа)

W4: **15 CONTRACT** — RED (ImportError без модуля) → GREEN 15/15. Совместный прогон моей зоны: planner(15) + orchestrator(16) + gate(18) + W1-context(11) + **route-coverage (18 CONTRACT)** + handlers + service = **137 passed / 0 failed** (W3-зона оркестратора и чужие зоны не сломаны). Настройки/smart_cache не менялись с W3 (зелёные там же).

## Фрагменты доказательств

- `w4-red-green.txt` (этот прогон), sha256 — `w4-sha256.txt`.
- Пример плана из W0-трассы: клейм «В 2019 году в Килякете выпало рекордное количество осадков…» → интенты entity_check + temporal_context («2019»), сущность «Килякет» сохранена, слайса нет (тест `test_semantic_queries_not_raw_slice`).
- Негативы: OFF → None; scope=chat_history → None; авторы не утекают; битый primary-fetch → fail-open; падение движка → честная деградация (None, не пустые ссылки).

## Осталось для W6-интеграции

1. Перенос выполнения плана ДО вычисления вердикта (единый retrieval-контур v2: один поиск на прогон вместо service-внутреннего + planner-слоя) + бюджеты/дедлайны (06C.8).
2. Консолидация трасс/метрик (queries attempted/relevant/used; 06G.7).
3. Инвалидация/версионирование кешей под planner-версию (`fp1`) — вместе с кеш-консолидацией W6.
4. (Опционально W6+): релевантность/спорность сниппета → приоритет открытия первоисточника (06C: «спорные тезисы открывают первоисточник») — сейчас SafeFetch открыт по первым 2 URL плана.
