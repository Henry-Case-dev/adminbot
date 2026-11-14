# VMQ-ONTO-B (O-03) — typed-отношения: направление, автор, время, provenance, конфликты

Дата: 15.11.2026. Ветка `vmq/onto-b`, база — принятая линия ONTO-A
`d67262cb491ac558b578340414d604a7caab21c9` (код `8cb9e00d`, база
`c97c06e4` / 2.58.203). **Code tip: `d15b13da3e709c4311f347e307e356a895e28a24`**
(этот evidence-файл — следующий коммит той же ветки).

Контракт: `plans/features/vmq-onto-01/architecture-onto-ab.md` (строки O-03,
§49–56, §64) + `evidence/onto-a-contract-confirmation-2026-11-15.md`
(`ARCH_REUSE_CONFIRMED`) + `plans/current_task.md` §14 строка 9358.
Расширения write scope, DDL и схемы **не потребовалось**.

## Что изменено

| Файл | Статус | Содержание |
|---|---|---|
| `services/semantic_contracts.py` | +523 строки (только добавления) | typed-проекция отношения: `SemanticRelation`, `RelationDefinitionConflict`, `project_relation`, классы `RELATION_KIND_*`, `DEFINITION_CONFLICT_*`, relation reason/degraded коды |
| `tests/test_semantic_contracts.py` | +521 строка (только добавления) | 15 новых тестов O-03 на существующем evidence-пути (`edges` + `mca_evidence_links` → `relation_evidence.build_relation_view`) |
| `services/relation_evidence.py`, `services/memory_contracts.py`, `services/graphrag_provenance.py`, `services/provenance.py`, `services/database.py` | без изменений | переиспользованы как владельцы |

Изменений нет и в `services/mca_retrieval_context.py` (это O-04/M2), в
настройках/флагах, промптах, UI, схемах/миграциях и production.

## Переиспользование существующих владельцев (без второго контура)

- отношение владеет `memory_contracts.RelationView` / `RelationSourceView` —
  проекция получает готовый `view` и **ничего не пересчитывает**;
- сборка карточки/оснований — существующий `relation_evidence`
  (`build_relation_view`, `attach_edge_evidence`, `evidence_independent_count`);
- классы происхождения — `graphrag_provenance` (`OriginClass`,
  `SUPPORTING_ORIGIN_CLASSES`, `EDGE_CONFIDENT|TENTATIVE|LEGACY_UNVERIFIED`);
- типы связи — существующий `provenance.LINK_TYPES` / `memory_contracts`
  (`SUPPORTING_LINK_TYPES`, `WEAK_LINK_TYPES`), словарь не дублируется;
- независимость корней — `RelationView.independent_support`
  (`provenance.evidence_independent_count`), без локального подсчёта.

Модуль не содержит SQL/DDL/записи, не создаёт второй store/resolver/search/
LLM и не импортирует `database`/`mca_retrieval_context`/`ai_service`
(существующие AST/subprocess-guard тесты остаются зелёными). Явных enum’ов
вроде `ontology_proven` не вводилось.

## Соответствие приёмке O-03

Нормативный текст (`requirements-map.json`, `MAN-O-03`): «Отношения
типизированы и несут направление, автора утверждения, время и provenance:
cooccurrence не становится фактом отношений, legacy-связи помечены как не
подтверждённые, конфликты определений видны в данных».

| Кл. | Как выполнено | Тест |
|---|---|---|
| типизированы | `relation_type` из существующей строки `edges.relation_type`; концы — типизированные `EntityRef` (`user|topic|event|fact`) в одном chat scope; `relation_kind`/`verification` выводимы | `test_relation_is_typed_and_directed` |
| направление | `direction='directed'` = существующее `edges.source_id → target_id`; обратное ребро — отдельная строка, порядок концов не «исправляется» | `test_relation_direction_is_not_reversed` |
| автор утверждения | `asserted_by` = speaker существующих оснований, subject связи его не подменяет; нет автора — пусто, а не догадка | `test_relation_carries_assertion_author_and_time`, `test_relation_author_and_time_are_not_invented` |
| время | `time.asserted_at`/`event_time` из `asserted_ts`/`event_ts` оснований; разные значения → `None` + `relation_assertion_time_ambiguous` | `test_relation_time_conflict_is_not_resolved` |
| provenance | `provenance_class` в существующей шкале `graphrag_provenance`, `origin_class` = `OriginClass`; источник — `RelationView` | `test_relation_is_typed_and_directed`, `test_relation_projection_reuses_existing_relation_view` |
| cooccurrence ≠ факт | `mentions`/`cooccurrence` дают `relation_kind='cooccurrence_hint'`, `is_relation_fact=False`, `verification=unknown`; частота (`edges.weight`) факт не создаёт | `test_cooccurrence_never_becomes_relation_fact` |
| legacy не подтверждено | ребро без оснований / `legacy_unknown` → `relation_kind='legacy_unverified'`, `legacy=True`, `provenance_class='legacy_unverified'`, `verification=unknown` | `test_legacy_edge_is_marked_unverified` |
| конфликты определений видны | `definition_conflicts` из данных: `contradicts`/`supersedes`-основание, статусы `contradicted|superseded|rejected`; конфликт **не** разрешается молча и не даёт `verified` | `test_definition_conflict_is_visible_and_not_verified`, `test_contradicted_and_superseded_statuses_stay_visible` |
| повтор корня / репост / self-output | один `source_ref` дважды = 1 независимый корень; репост/цитата и вывод бота не дают прямого подтверждения даже при ложно выставленных `verified/independent` | `test_duplicate_evidence_root_does_not_add_support`, `test_repost_and_bot_output_do_not_confirm_relation` |
| опровержение без утверждения | `relation_kind='counter_evidence'`, `is_relation_fact=False`, `verification=unknown` | `test_counter_evidence_only_is_not_a_relation_fact` |
| chat scope / концы | чужой чат, чужой узел, неверное направление и не-`RelationView` отклоняются; карточки ребра в другом чате не существует | `test_relation_scope_and_endpoints_are_strict` |
| read-only | счётчики `nodes`/`edges`/`mca_source_refs`/`mca_evidence_links` не меняются после проекций | `test_relation_projection_does_not_write` |

Инварианты: `verified` требует одновременно `status='confirmed'`, ≥1
независимый корень, `provenance_class='confident'`, наличие прямого
утверждения (`origin_class='explicit_direct'`) и отсутствия видимого
конфликта. `verification`/`relation_kind`/`legacy`/`degraded`/`reason_code` —
выводимые свойства, выставить их вручную нельзя.

## RED → GREEN (кандидат-связанные прогоны)

RED на базе `d67262cb` (модуль без ONTO-B, тесты добавлены):

```
$ python -m pytest tests/test_semantic_contracts.py -q
14 failed, 26 passed
(все 14 — новые O-03: AttributeError: module has no attribute 'project_relation')
```

GREEN на code tip `d15b13da`:

```
$ python -m pytest tests/test_semantic_contracts.py -q
41 passed
```

## Мутационная проверка (assertions не тавтологичны)

| Мутация | Результат |
|---|---|
| A: `_is_relation_assertion` → `return True` (co-occurrence/legacy считаются утверждением) | 2 failed: `test_cooccurrence_never_becomes_relation_fact`, `test_counter_evidence_only_is_not_a_relation_fact` |
| B: `definition_conflicts` → `()` (конфликт не виден) | 2 failed: `test_definition_conflict_is_visible_and_not_verified`, `test_contradicted_and_superseded_statuses_stay_visible` |
| C: `time.asserted_at` берёт первое значение вместо честного `None` | 1 failed: `test_relation_time_conflict_is_not_resolved` |
| D: `verified` перестаёт требовать отсутствие конфликта | 1 failed: `test_definition_conflict_is_visible_and_not_verified` |
| E: `_DIRECT_ORIGIN_CLASSES` = все supporting-классы (репост/дериватив как прямое подтверждение) | 1 failed: `test_repost_and_bot_output_do_not_confirm_relation` |

Все мутации откатаны; после каждой откат-копии SHA-256 файла совпадал с
кандидатом, а финальный `git diff` относительно коммита не показал остаточных
изменений.

## Затронутые suite на точном кандидате

```
tests/test_semantic_contracts.py                       41 passed
tests/test_memory_contracts.py                         64 passed
tests/test_mca04a_provenance_round1027.py              68 passed
tests/test_memory_attribution.py                       32 passed
tests/test_graphrag_memory.py                         181 passed
```

Итого 386 passed, падений и pre-existing ошибок в этих наборах не наблюдалось.
Полный suite проекта не запускался: production-код не менялся, добавлен
только новый API и его тесты; blast radius ограничен перечисленными файлами.

## Schema / DDL / no-reembedding audit

- `services/database.py` не изменён; схема/`user_version`/миграции не
  затрагивались (schema 47 не менялась), DDL/записи в модуле нет
  (существующий AST-guard `test_module_has_no_sql_ddl_or_second_identity_store`
  зелёный, локальные импорты модуля ограничены provenance/contracts).
- Никакого backfill/переиндексации/reembedding: проекция читает уже
  собранные `RelationView`/evidence-links, второго прохода по архиву нет.
- Read-only интеграционный тест: счётчики `nodes`, `edges`, `mca_source_refs`,
  `mca_evidence_links` до/после серии проекций равны.

## Конфигурация

Новых флагов/settings нет (в этом срезе запрещены). Тесты используют
существующий effective-путь provenance-гейта (`MCA_PROVENANCE_ENABLED`
default ON) — им живёт `relation_evidence.attach_edge_evidence`; значений по
умолчанию не меняли. ONTO-B не подключён к retrieval (это O-04/M2), поэтому
никаких live/effective-state утверждений для production не делается.

## Честные ограничения

- `edges.relation_type` — свободная строка существующей схемы. Проекция несёт
  её как предикат, но **не** классифицирует предикаты в закрытый словарь
  (`друг/враг/коллега`): такой словарь был бы новым лексическим списком/онтологией.
- «Конфликт определений» выводится только из данных об основании
  (`contradicts`/`supersedes`-связи, противоречивый статус ребра). Два разных
  `relation_type` на одну пару без опровергающего основания конфликтом не
  объявляются — это потребовало бы лексических противопоставлений.
- `verified` не требует известного автора/времени: существующий evidence-
  контракт (R-1) этого не требует. Отсутствие автора/времени показывается как
  `asserted_by=()`/`asserted_at=None` + degraded-код, а не подставляется.
- `assertion_mode` оснований виден в `assertion_modes`, но не гейтит
  `verified`: модальность фактов относится к O-01, а её гейтирование здесь
  изменило бы существующую семантику confirmed-рёбер без требования O-03.
- Время события берётся только из существующего `valid_from` факта; у
  `edges` поля времени события нет → остаётся unknown.
- `edge_evidence(...)` возвращает `unmapped_sources` (нераскрытые основания),
  но существующий `build_relation_view` их не переносит. Значит ребро с
  неразрешимыми evidence-строками может выглядеть подтверждённым; это
  ограничение существующего публичного view, чинить его здесь — отдельный
  срез `relation_evidence` (в write scope ONTO-B не входит).
- Натуральные исторические relations и коррекция архивного корпуса этим
  срезом не проверяются и не утверждаются (вне A/B).

## Границы и housekeeping

- Write scope использован минимально: `services/semantic_contracts.py` +
  `tests/test_semantic_contracts.py`; расширение не требовалось, DDL нет.
- Worktree сохранён для Reviewer:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-onto-01-3689dd92710d-699aba96`
  (ветка `vmq/onto-b`, registered unit `VMQ-ONTO-B`).
- Disposable probe `WorkspaceData/runs/.../probe-ce24ee6f5e` (бэкапы файла,
  мутационный скрипт) закрыт после переноса результатов в этот файл.
- `plans/current_task.md`, карты и production не изменялись.
