# VMQ-M2 — подтверждение контракта для ONTO-A/B

Дата: 15.11.2026. Проверены master (`HEAD 72d4417e`), production baseline `c97c06e4` (2.58.203), а также кандидатные линии `vmq/onto-a` и `vmq/onto-b`. Проверка read-only; код не изменялся.

## Решение

**ARCH_REUSE_CONFIRMED.** Реального нового cross-module решения для M2 не осталось. Builder может реализовывать M-04/M-05/O-04 после последовательного соединения ONTO-A и ONTO-B в одном release candidate, строго в существующем unified retrieval.

## Подтверждённый контракт

- Единственная точка retrieval — `services/mca_retrieval_context.py::retrieve()`. Существующие `RetrievalRequest`/`RetrievalResult`, `EvidenceBundle`, `fact_rows`, `relations`, year coverage и ACL `effective_chat_ids` достаточны для M2. Не добавлять второй router, `retrieve()`, candidate pool, DB/search engine, provider или LLM pipeline.
- M1 предоставляет существующий `mca_episodes` pipeline/repository, episode/story versions, source refs и bounded coverage/range reads. `EpisodeView`/`LongitudinalView` — логические read-only projections поверх текущих episode/story/coverage контрактов, а не новое хранилище или обязательные отдельные классы.
- ONTO-B добавляет directed relation/provenance/legacy/conflict projection к typed API. Semantic definitions/relations в M2 — только hints/аддитивная проекция; они не выбирают кандидатов сами и не становятся вторым маршрутизатором.
- `EvidenceBundle` остаётся единственным in-memory bundle: добавлять только необходимые bounded coverage/episode/longitudinal/semantic references, сохраняя source-ref semantics и `context_version`; архивный текст и durable bundle table не вводить.
- `chat_id`/`chat_ids` и source rows — канонический scope. Missing/ambiguous/legacy/foreign-chat input даёт unknown/tentative/degraded, не verified; cross-chat merge/утечка запрещены.
- Correction/version state использует существующие source/evidence revisions, story/episode versions и provenance lineage. Отдельный журнал определений не создаётся.

## Приёмка M-04/M-05/O-04

- **M-04:** один вызов `retrieve()` покрывает person overview и temporal change через existing episode/longitudinal coverage и evidence expansion; Writer получает тот же единый bundle. Нужны assertions на episode/period/source refs и bundle payload, не только на текст ответа.
- **M-05:** static diff/schema/call audit и targeted tests подтверждают отсутствие DDL, destructive archive rewrite, mass ingest/re-embedding, embedding/index rebuild, cross-chat rows и дополнительных retrieval/search/model/provider calls.
- **O-04:** semantic definitions/relations являются hints внутри того же retrieval; directed provenance, ambiguity, conflict и version semantics сохраняются. Alias/co-occurrence/legacy/quote/foreign chat не повышаются до verified и не меняют scope.

## Write scope и сериализация

1. `services/mca_retrieval_context.py` — единственный retrieval writer: ONTO projections, Episode/Longitudinal coverage, bounded bundle fields и correction/version lineage.
2. `tests/test_memory_unified_retrieval.py` — meaningful contract/integration/negative tests.
3. `services/database.py` не входит в default scope; только при доказанном persistent/schema gap, с аддитивной миграцией и отдельным serialized review. Destructive rewrite запрещён.
4. `services/direct_context_composer.py` по умолчанию остаётся неизменным: он уже потребляет единый bundle/retrieval result. Изменять его можно только при доказанном exact-candidate разрыве доставки M-04 до Writer, минимально и сериализованно.

`VMQ-M1 → VMQ-M2`; `ONTO-A → ONTO-B` (общий `semantic_contracts.py`); `ONTO-B → M2`. M2 и MEM не пишут одновременно `services/mca_retrieval_context.py`: measurement MEM выполняется только после M2 и не является разрешением на параллельную правку. `services/database.py` также сериализуется.

## Выкладка и REVIEW-зависимости

Безопасный порядок: **ONTO-A → ONTO-B → M2**, с candidate-bound independent review каждого шага. M2 требует интегрированные M1 episode/longitudinal outputs и ONTO-B API; его нельзя выкатывать против старого retrieval без этих входов. O-01/O-02 и O-03 остаются REVIEW до независимого approval и являются реальными зависимостями M2. REVIEW VMQ-A-01 не меняет runtime contract, но должен быть reconciled до parent release gate.

## Проверки Builder/Reviewer

На exact integrated candidate проверить person overview, temporal change across periods, empty/partial/unknown coverage, same-chat и foreign-chat negative, semantic hint без второго route, ambiguity/conflict/version/legacy, один `retrieve()` и один bundle до Writer, ноль extra model/embedding/search/router calls, отсутствие DDL/mass re-embedding/archive rewrite и сохранность lineage. Reviewer отдельно falsifies cross-chat isolation и duplicate-route behavior.

Внешние источники не использовались. **Вердикт: ARCH_REUSE_CONFIRMED.**
