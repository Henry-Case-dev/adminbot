# Архитектурный контракт VMQ-ONTO-A/B (O-01..O-04)

Дата: 13.11.2026. Основание: `plans/owner_inputs/2026-11-09-vmq-onto-01.md` §§2, 5.3–5.8, §14; текущий пользовательский реестр `plans/current_task.md` §14, строки 9356–9359 и §5. Проверка кода — именно `23477658` (production 2.58.198, schema 47, DDL 0), а не `master` (`fc21da43`, отдельная линия без релизного кода). Код/БД/карты/production этим решением не менялись.

## Решение

**Один чистый typed-contract модуль `services/semantic_contracts.py`, используемый из существующего unified `services/mca_retrieval_context.py::retrieve()` и существующего memory/provenance слоя.** Это небольшой валидатор/проектор семантического значения и отношений, не самостоятельный ontology store, extractor, resolver, search pipeline или LLM. VMQ-ONTO-A реализует семантические типы/meaning и неоднозначность; VMQ-ONTO-B добавляет relation view и интеграцию в тот же retrieve. Файлы одного общего API: A и B выполняются последовательно; параллельное изменение общего контракта запрещено.

На `23477658` `services/semantic_contracts.py` отсутствует; `services/graphrag_provenance.py` уже реализует provenance-классификацию, независимые evidence roots, legacy-классификацию и relation write verdict. `mca_retrieval_context.retrieve()` собирает существующие каналы и строковые candidates, а `direct_chat_service` direct-RAG уже вызывает его и потребляет `fact_rows`. `memory_contracts.py ПРИСУТСТВУЕТ в релизном срезе 23477658 (проверено Orchestrator: `git cat-file -e 23477658:services/memory_contracts.py` -> exists); Builder обязан переиспользовать его, а не создавать замену.

### Typed value model

Модуль предоставляет только неизменяемые внутренние typed views/validators (конкретные Python-имена — в соответствии с API кандидата, без создания несовместимого параллельного enum):

- canonical `entity_type`: ровно существующие `user | topic | event | fact`; derived meaning не расширяет тип узла;
- entity identity: существующая `chat_id`/scope + canonical ID (Telegram UID при user) + существующая ссылка на узел/факт. Имя/алиас — поисковый hint, не identity;
- meaning roles: `speaker` (кто произнёс/утверждает) и `subject` (о ком/чём утверждение), при наличии — object, quote/forward/origin и distinct `event_time`, `asserted_at`, `observed_at`; отсутствующее значение остаётся unknown/None;
- verification/truth/provenance: только имеющиеся значения/классы (`verified|tentative|unknown|rejected`, conflict/superseded и provenance class из существующих источников). Не вводить `ontology_proven` и не выводить truth из type, alias, повторов, LLM или красоты связи;
- relation semantics: direction-bearing predicate/link type из существующего `LINK_TYPES`/evidence contract; source/assertion, speaker, subject/object, temporal scope и evidence refs несут исходный scope. Неподдерживаемое/неполное отношение возвращается как unknown/tentative или legacy-unverified, а не повышается.

Legacy facts/nodes/edges отображаются **на чтении**: type берётся только из валидного существующего `entity_type`/предметной записи; достоверно восстанавливаемые source/speaker/subject/time поля проецируются, отсутствующие остаются unknown. Старые строки без надёжного типа не переименовываются/не удаляются: их можно вернуть как legacy weak hint, но не трактовать как верифицированную персону/связь. Никакой UPDATE/записи массовой классификации архива и никакого backfill, требующего переэмбеддинга.

Negative examples — тестовые контрпримеры на функции разрешения/проекции, не отдельное долговременное хранилище и не лексические blacklist-правила: нарицательное/мем «Папаха» не разрешается автоматически в пользователя; одинаковые имена в одном/разных чатах остаются разными при разных canonical IDs; alias сходство само по себе не объединяет; одно совместное упоминание не порождает отношение/ссору; цитата, репост, ирония, пересказ или собственный ответ бота не становятся независимым прямым подтверждением. При неразрешимой ambiguity возвращать ambiguity и не выбирать произвольно.

### Единственный путь данных

```text
существующие source rows / graph facts / nodes / evidence links
  → существующие attribution/entity/provenance owners
  → semantic_contracts: typed read-only projection + validation
  → существующий mca_retrieval_context.retrieve() (те же каналы/candidates)
  → существующий RetrievalResult и relation projection
  → существующие direct-RAG/Composer/Writer consumers
```

Новый модуль не выполняет SQL-поиск, embeddings, reranking, entity merge, extraction или отдельный вызов модели. Интеграция не добавляет второй `retrieve()`, candidate pool, route, API либо fallback search. Typed view аддитивен к уже возвращаемым данным, а не меняет состав/порядок текущих кандидатов без отдельно доказанной необходимости. Feedback/correction продолжает идти через текущий write-owner и `graphrag_provenance`/relation evidence; `semantic_contracts` валидирует/проецирует, но не мутирует `graph_facts` или evidence links в обход владельца.

## Границы, scope, риски

**Ожидаемый write scope Builder:**
- `services/semantic_contracts.py` — новый модуль typed view/validation;
- `services/mca_retrieval_context.py` — минимальная интеграция в уже существующий retrieve/result без второго поиска;
- ближайшие существующие contract/retrieval tests либо один узкий `tests/test_semantic_contracts.py`.

Другие memory owners трогать только при доказанной несовместимости, с возвратом изменения в соответствующий serialized slice. Никаких правок `services/database.py`, migration/schema, settings/flags, embedding/provider/index, direct-RAG composer, prompts, UI, production, планов/карт, или памяти/эпизодов в рамках A/B. Никакого нового хранилища, DDL, индекса, агента, LLM-вызова или полного NVIDIA runtime: owner ТЗ прямо исключает это без доказанной нехватки текущего контракта. Для ONTO-A/B такой нехватки пока не выявлено и отдельный store/DDL не требуется.

Blast radius — R1, средний только в retrieval data contract; один retrieval seam и типизированный результат могут затронуть downstream readers, поэтому сохранить поля результата обратно совместимыми/аддитивными и тестировать callers. Схема и сохранённые данные не меняются, rollback — вернуть integration commit и новый модуль; данные отката/миграции не нужны.

## Инварианты и деградация

1. Чатовая изоляция строгая; alias/поиск/relations не пересекают `chat_id` и не обходят permissions/subject scope.
2. Telegram UID/canonical ID выше строковой похожести; speaker не подменяется subject. Время события, утверждения и обнаружения различаются; неизвестное не изобретается.
3. Verified/confident требует уже существующего supporting-evidence/provenance contract. Повтор одного root, forward/quote и bot self-output не увеличивают независимую поддержку. Conflict сохраняется видимым.
4. Legacy и частично атрибутированная память остаются доступными как слабые hints; typed-contract failure не уничтожает память и не блокирует базовую выдачу.
5. Отсутствующий контракт/поле/неизвестный enum/ошибка проекции = явно unconfigured/unknown/degraded с существующим безопасным путём `retrieve()`; нельзя молча выдавать typed verified. Нельзя создавать новую выдачу, лишь чтобы имитировать работу ontology.
6. Сохранить существующие настройки и behavior памяти. Архив не переписывается; embedding count/generation/fingerprint, модель и размерность неизменны; не запускается ни один массовый ingest/reembed/backfill.

## Приёмка, тесты и статус evidence

Builder до правки фиксирует baseline кода на целевом candidate, затем добавляет детерминированные contract/integration assertions:

- **O-01:** valid user/topic/event/fact типы и правильное различение speaker/subject; отсутствующие роли/даты остаются unknown; неверные типы/перекрёстный chat scope отклоняются/деградируют, не получают verified.
- **O-02:** положительная разрешённая canonical identity и alias как hint; негативные примеры выше (common noun vs alias, одинаковые display names при разных IDs/scopes, неоднозначность, co-mention, quote/forward/irony); ambiguity не превращается в случайный выбор.
- **O-03:** directed typed relation с source refs/independent root, provenance class и time; недостаточная provenance даёт legacy/tentative, conflict сохраняется; legacy relation без `subject_ref_id` не становится verified; duplicate root, bot output и repost не создают независимого подтверждения. Проверять через существующие `graphrag_provenance` и relation-evidence path, не мокать их как замену subject under test.
- **O-04:** тест вызова существующего retrieval доказывает один и тот же `retrieve()` формирует typed projection и candidates; no second search/embedding/model call; correction/version inputs сохраняют source lineage и version/fingerprint semantics, а результат остаётся candidate-bound к исходному evidence. Версии только из существующих revisions/fingerprints; не создавать отдельный журнал/таблицу.
- **Backward compatibility:** legacy stored row читается без записи/миграции и остаётся доступен как weak hint; существующие ключи/семантика `RetrievalResult`, каналы, ranking/order и direct-RAG `fact_rows` не ломаются при выключенной/недоступной typed projection.
- **No reembedding / no secrets:** статический diff/schema audit подтверждает отсутствие DDL, записи/массового прохода по архиву, embedding API/index rebuild. Canary/mock fault tests: ошибки не раскрывают тексты фактов, источников, query, credentials/API keys в событиях/logs; event fields — только разрешённые идентификаторы/коды и bounded metadata.

### Строки O-01..O-04 и точное evidence

| Строка | Builder handoff `REVIEW` только при наличии | Что обязательно остаётся вне REVIEW/VERIFIED |
|---|---|---|
| O-01 | candidate-bound тест typed meanings user/topic/event/fact + speaker/subject, unknown semantics и retrieval compatibility; точные команды/вывод targeted tests; inspected code refs и diff | Любые реальные многолетние person-overview/episode coverage результаты принадлежат M1/M2/MEM, не доказываются contract unit test |
| O-02 | candidate-bound positive/negative fixtures для alias/common noun, distinct IDs и ambiguity с проверкой результата (не только вызова resolver) | Естественные новые неоднозначные production cases — observation, только если исходное требование требует соответствующий runtime event; нельзя выдумывать live proof |
| O-03 | tests по relation direction + real existing provenance functions/fixtures: verified лишь при допустимых refs, legacy weak, duplicate root/quote/self-output/conflict негативные случаи; evidence lineage refs | Приёмка всех persisted исторических relations/коррекция корпуса не входит в A/B; полное reconciliation архивных связей не утверждать |
| O-04 | source mapping на `retrieve()`/caller + integration test фиксирует один retrieval path и candidate/result lineage, отсутствие дополнительных search/LLM/embedding вызовов; correction/version compatibility test | E2E многолетний паритет и Writer bundles остаются M2/MEM; будущие естественные feedback/corrections не должны быть приписаны без наблюдения |

Builder меняет строки карты на `REVIEW` только после готового проверенного candidate и прикрепления существующих candidate-bound implementation/test evidence. Независимый Reviewer должен лично проверить код, assertions и атакующий контрпример (например, same-name entity в другом chat либо legacy edge с повторённым forward) по точному candidate; только его отдельный Approved evidence допускает review gate. Архитектурная записка не является acceptance evidence реализации. Обычный код/тестовый proof исполним до выпуска; production/effective state подтверждается только после разрешённого релиза. Любая будущая real-event проверка, если обязательность прямо следует исходному owner contract, остаётся внутренним future evidence, не ручным заданием владельцу; данный дизайн не создаёт нового окна наблюдения.

## M1/M2 dependency и параллельная безопасность

ONTO-A/B **не требуют наличия эпизодов M1**: их typed contract строится над уже существующими nodes/facts/source refs/relations и применим к пустому/отсутствующему episode набору. M1 может идти независимо от кода semantic contracts, но совместимый shared type contract должен быть зафиксирован этим документом; если M1 уже пишет пересекающийся API/module, сериализовать интеграцию общего файла.

ONTO-A → ONTO-B: `SERIALIZE` (один общий `semantic_contracts.py` и его API). ONTO-A/B относительно M1: `PARALLEL_SAFE` по предметной логике; `SERIALIZE` при совместном write одного файла/типового API. ONTO-A/B → M2: `BLOCKED_BY:VMQ-ONTO-A-B` для потребления ONTO relation projection; базовая независимая часть M2/unified retrieval не блокируется. ONTO-A/B не должны менять retrieval алгоритм или требовать episodes, чтобы Builder мог закончить независимо. Shared retrieval module writer — один владелец за раз; тестовые fixtures могут готовиться read-only параллельно.

## Следующее действие Builder

**Цель:** реализовать минимальный semantic contract VMQ-ONTO-A/B по этому документу на интеграционной release-линии, добавить типизированную проекцию в единственный существующий retrieval и доказать O-01..O-04.

**Write scope:** `services/semantic_contracts.py`, `services/mca_retrieval_context.py`, узкие существующие retrieval/contract tests или новый `tests/test_semantic_contracts.py`.

**Запрещено:** второй retrieval/search/LLM/agent/store; DDL/schema/migration; массовое изменение/переиндексация/reembedding/архивный backfill; изменение провайдеров/embeddings/settings/prompts/пользовательских preferences; изменение `graph_facts`/evidence в обход их write owner; unrelated M1/M2 work, direct composer/UI, production и deployment. Если на целевом candidate реально отсутствует контракт, необходимый для безопасной реализации, не строить параллельный контракт по догадке: остановить эту часть и вернуть точные code refs/несовместимость Architect.

**Обязательные тесты:** O-01..O-04 и негативные примеры, единый retrieval path, lineage/provenance/conflict/legacy, backward compatibility, no secrets, no DDL/no mass reembedding; targeted relevant suite, diff/schema audit.

**Acceptance:** all applicable tests pass with meaningful result assertions; existing legacy data remains readable and unchanged; typed unknown/degraded is honest; one retrieval path only; no extra model/provider/index activity; evidence bound to exact candidate with commands, output, refs and diff; no production action. Передачей в REVIEW не объявлять независимое Approved или VERIFIED.

Внешние источники не использовались: решение целиком основано на зафиксированном owner contract и текущем релизном коде.

ARCH_ONTO_AB_READY
