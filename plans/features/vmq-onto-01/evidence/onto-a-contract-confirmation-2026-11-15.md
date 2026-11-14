# VMQ-ONTO-A — подтверждение замороженного контракта

Дата: 15.11.2026. Проверены рабочая линия `master` (`HEAD 3b095c33`) и
production-коммит `c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` (2.58.203).

## Решение

**ARCH_REUSE_CONFIRMED.** Реального нового cross-module решения не осталось;
Builder может реализовывать O-01/O-02 в пределах замороженного контракта
`plans/features/vmq-onto-01/architecture-onto-ab.md` (версия/исходная проверка
в документе намеренно остаётся исторически привязанной к `23477658`).

## Проверенные основания

- `architecture-onto-ab.md:11–23, 49–56, 62–67` фиксирует ровно типы
  `user|topic|event|fact`, раздельные `speaker`/`subject`, честные unknown,
  строгий `chat_scope`/provenance, alias как hint, запрет лексических trigger
  lists, произвольного merge и второго ontology/search/store pipeline.
- В production `c97c06e4` присутствует `services/memory_contracts.py`;
  `services/semantic_contracts.py` отсутствует, то есть O-01/O-02 ещё не
  реализованы и должны добавить именно новый read-only contract, а не
  исправлять уже существующий semantic-модуль.
- `services/message_identity.py:4–18, 81–140, 209–254` подтверждает
  `(chat_id, tg_message_id)`, различение `sent_at`/`ingested_at`, source/origin
  и раздельные author/reply/quote/forward роли. Это основание для provenance и
  scope, но не повод смешивать author/speaker с subject.
- `services/summary_aliases.py:6–25, 93–129, 145–197, 329–393` подтверждает
  UID-first alias cascade, per-chat merge, неслияние по display-name и удаление
  неоднозначного обратного имени. ONTO-A должен использовать это как hint и
  сохранять ambiguity, не создавать второй resolver.
- `services/database.py` содержит `nodes.entity_type` с CHECK ровно на
  `user/topic/event/fact` (`:2159–2168`), а `graph_facts` остаётся существующим
  источником фактов (`:2198–2221`). Проверка не выявила необходимости DDL,
  миграции или schema-изменения; заявленная schema 47 остаётся совместимой.

## Границы реализации и тестов

Разрешённый write scope: `services/semantic_contracts.py`,
`services/message_identity.py`, `services/summary_aliases.py` и
`tests/test_semantic_contracts.py` (только минимальные необходимые добавления).
`services/semantic_contracts.py` — чистая typed read-only проекция/валидация;
не SQL-owner, не extractor, не LLM, не search/rerank, не entity-merge и не
новое хранилище. Существующие identity/alias функции переиспользуются, без
изменения их устойчивых публичных смыслов.

O-01 должен доказать положительные четыре типа, speaker/subject, unknown для
пропусков и отказ/degraded для неправильного type или cross-chat scope.
O-02 должен доказать canonical UID, alias-only hint, common noun ≠ user,
разные одинаковые имена ≠ одна identity и сохранение ambiguity; co-mention,
quote/forward/irony не создают identity/fact.

## Граница ONTO-B и M2

ONTO-B (`O-03`) остаётся последующим сериализованным потребителем общего
контракта: только typed/directed relations с provenance/source refs и
независимыми корнями. `cooccurrence`/совместное упоминание не является fact и
не должно протекать в ONTO-A как identity или подтверждение.

M2 (`O-04`) потребляет semantic definitions только как hints в **одном**
существующем retrieval; ONTO-A не добавляет второй retrieve, candidate pool,
поиск, embedding, provider call или persisted projection. В ONTO-A не входят
relation view, relation persistence, episode/longitudinal assembly, ranking и
Writer bundle.

## Коррекции и риск

Архитектурная коррекция не требуется. Единственная отмеченная разница —
текущий production baseline уже `c97c06e4`, тогда как историческая строка
замороженного документа ссылается на `23477658`; это не меняет контракт и
сохранено здесь как validation lineage, без переписывания frozen reference.
Риск R1: новый общий typed API должен быть аддитивным и не менять текущие
candidate/order semantics. Rollback — удалить integration commit нового
модуля/вернуть вызывающую интеграцию; schema/data rollback не нужен.

## Следующее действие

Builder реализует O-01/O-02 в указанном scope, затем передаёт candidate-bound
unit/integration tests и diff на независимое ревью. Production и миграции в
этом срезе не выполняются.

Внешние источники не использовались: решение основано на текущем коде,
production-коммите и уже принятом owner/architecture contract.
