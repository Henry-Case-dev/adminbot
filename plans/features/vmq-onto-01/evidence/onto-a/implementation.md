# VMQ-ONTO-A (O-01, O-02) — implementation evidence

Дата: 15.11.2026. Branch `vmq/onto-a`, база — production-линия
`c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` (2.58.203). Code tip:
`a7a576b1f1833da7be53f7bd75d25e1eaf815937`.

Контракт: `plans/features/vmq-onto-01/architecture-onto-ab.md` +
`plans/features/vmq-onto-01/evidence/onto-a-contract-confirmation-2026-11-15.md`
(ARCH_REUSE_CONFIRMED). Отклонений от замороженного контракта и расширения
write scope нет. `services/mca_retrieval_context.py`, `services/database.py`,
схема/миграции, settings/flags, prompts, UI и production не менялись.

## Что изменено

| Файл | Статус | Содержание |
|---|---|---|
| `services/semantic_contracts.py` | новый (1213 строк) | read-only typed-проекция/валидация значения: `TypedEntityType`, `SemanticIdentity`, `SemanticRole`, `MeaningTime`, `SemanticMeaning`, `classify_entity_type`, `project_identity`, `project_node_meaning`, `project_fact_meaning` |
| `tests/test_semantic_contracts.py` | новый (673 строки, 23 теста) | contract + integration-тесты O-01/O-02 на реальных владельцах |
| `services/message_identity.py` | без изменений | роли author/reply/quote/forward уже разделены (`roles()`), второй модели не создаётся |
| `services/summary_aliases.py` | без изменений | UID-first каскад и удаление неоднозначного обратного имени уже есть; alias используется как hint |

Изменения в двух последних файлах были бы не минимальными: существующие
примитивы уже покрывают требуемую семантику, дублирование создало бы второго
владельца. Write scope использован по минимуму.

## Переиспользование существующих владельцев (без второго контура)

- идентичность/неоднозначность: `entity_resolver.resolve_entity`,
  `mca_entity_canonical`, `seed_self_identity` — проекция только читает
  `EntityResolution`/`EntityRef`/`ResolutionCandidate`;
- UID-доказанность: причина `REASON_STABLE_IDENTITY` существующего резолвера
  (ленивый импорт; при недоступности владельца — консервативно «нет»);
- provenance/verification: `graphrag_provenance.classify_fact_provenance`,
  `classify_origin_class`, `memory_contracts.OriginClass`,
  `provenance.VERIFICATIONS/CONFLICT_STATUSES`;
- роли сообщения: `message_identity.roles` (author ≠ forward ≠ quoted ≠ reply);
- alias-каскад: `summary_aliases` через резолвер (тесты используют
  `build_alias_resolver`/hot-слой, как остальные suite).

Модуль не содержит SQL/DDL/записи, не вызывает LLM/embedding/search, не
импортирует `database`/`mca_retrieval_context`/`ai_service`.

## Соответствие приёмке

### O-01 (типы, роли, честный unknown)

- Типы ровно `user|topic|event|fact` (`memory_contracts.ENTITY_TYPES_ALLOWED`).
  Тип выводится из сигналов: `chat_scope` + participant identity (user) +
  `event_time` (event) + statement provenance (fact); `topic` не требует
  person/time-сигналов, а participant identity у самого референта запрещена
  (`type_conflict_single_slot`). Неизвестный тип → `unknown`, недопустимый
  (`person`) → `rejected`, чужой chat scope → `rejected/cross_chat_scope`.
- Тип не зависит от строки: у `classify_entity_type` нет параметра
  имя/упоминание (структурная проверка в тесте).
- speaker/subject — разные слоты: subject не заполняется автором и наоборот;
  отсутствующая роль остаётся `identity is None` + `role_unresolved`.
- Времена раздельны: `event_time` ≠ `asserted_at` ≠ `observed_at`
  (`message_timestamp` — утверждение, `created_at` — обнаружение), подстановок
  нет; `valid_from/valid_to` — существующий temporal scope.
- Provenance сохраняется: `provenance_class`, `origin_class`, `origin`,
  `conflict_status`, `source_ref_id/fact_id/tg_message_id`; `verification` —
  выводимое свойство (вручную не выставляется).
- `verified` требует подтверждающего происхождения; бот-вывод
  (`derived_with_lineage`), цитата/репост (`quote_forward`), co-occurrence,
  legacy без атрибуции и `conflicting` — `tentative`/`unknown`.

### O-02 (alias vs common noun, same name, ambiguity, негативы)

- Имя/алиас/casefold-совпадение для `user` → `basis=name_hint`,
  `status=tentative`, `canonical is None`, референс только в `hint_ref`.
  Канонический объект требует participant identity (`participant_identity`) или
  адреса строки для topic/event/fact (`node_address`).
- Нарицательное имя («Папаха», lowercase casefold-совпадение) не даёт
  канонического человека и `verified`; `as_dict()["identity"]["canonical"]`
  остаётся `None`.
- Одинаковые display-name разных людей различаются по chat scope и UID:
  разные `canonical.node_id`, а результат из чужого чата отвергается
  `cross_chat_scope` (не «сливается»).
- Неоднозначность (`casefold_multiple`) сохраняется как `candidates` ≥ 2 без
  выбранного canonical (`unknown`, `ambiguous=True`); конструктор запрещает
  один кандидат, canonical при кандидатах и hint с participant identity.
- Совместное упоминание и пересылка не подтверждают факт; sender остаётся
  speaker, автор пересылки его не подменяет (`message_identity.roles`).

## RED → GREEN (кандидат-связанные прогоны)

RED на базе `c97c06e4` (модуль отсутствует, тесты новые):

```
$ python -m pytest tests/test_semantic_contracts.py -q
tests/test_semantic_contracts.py:21: in <module>
    from services import semantic_contracts as sc
E   ImportError: cannot import name 'semantic_contracts' from 'services'
1 error in 0.37s
```

GREEN на tip `a7a576b1`:

```
$ python -m pytest tests/test_semantic_contracts.py -q
23 passed in 8.73s
```

## Мутационная проверка (assertions не тавтологичны)

| Мутация | Результат |
|---|---|
| A: `_resolution_is_uid_proven(...)` → `return True` (имя/алиас считаются UID-идентичностью) | 3 failed / 19 passed: `test_uid_resolution_is_identity_and_name_is_only_hint`, `test_common_noun_does_not_become_person`, `test_alias_hint_does_not_merge_with_uid_identity` |
| B: `REQUIRED_TYPE_SIGNALS["user"] = ()` (тип без participant identity) | 2 failed / 20 passed: `test_entity_type_is_derived_from_signals_not_name`, `test_common_noun_does_not_become_person` |

Обе мутации откатаны; хэш файла после отката совпал с исходным.

## Затронутые suite на точном tip

```
tests/test_semantic_contracts.py                                           23 passed
tests/test_memory_identity.py + test_memory_identity_migration.py
  + test_asap3_identity_aliases.py                                          89 passed
tests/test_mca03_message_identity_round1027.py + test_summary_aliases.py
  + test_aliases_render_round1022.py + test_aliases_render_round1024.py      57 passed (1 warning fastapi)
tests/test_memory_contracts.py + test_mca04a_provenance_round1027.py
  + test_memory_attribution.py                                              164 passed
```

Всего 333 passed, падений нет; известных pre-existing падений в этих наборах не
наблюдалось. Полный suite не запускался: существующий код не менялся, добавлен
только новый модуль и его тесты (blast radius ограничен). Это остаётся
непроверенным за пределами перечисленных файлов и указано честно.

## Schema / DDL / no-reembedding audit

- `services/database.py` не изменён; на in-memory БД после `initialize()`
  `PRAGMA user_version = 47`.
- Модуль не содержит SQL/DDL/записи (AST-guard в тесте: нет
  `execute/commit/INSERT/UPDATE/CREATE/ALTER/DROP`).
- Read-only интеграционный тест: счётчики `nodes`, `graph_facts`,
  `mca_entity_canonical` до и после серии проекций равны.
- Импорт модуля не тянет `services.database`, `services.mca_retrieval_context`,
  `services.ai_service`, `services.entity_resolver` (subprocess-guard).
- Embedding/index/provider/LLM не задействованы.

## Конфигурация и охват

- Новых флагов/settings нет (в этом срезе запрещены). Тесты используют
  существующий effective-конфиг идентичности (`MCA_MEMORY_IDENTITY_ENABLED=on` +
  `flags.memory_identity_enabled`) для интеграционных сценариев резолвера;
  alias-слой подменяется стандартным для repo hot-config путём.
- ONTO-A не включается в retrieval этим кандидатом: интеграция — O-04 (M2),
  relation view/persistence — O-03 (ONTO-B). Никаких live/effective-state
  заявлений для production не делается.

## Честные ограничения

- `verification` — консервативная производная от существующих классов; факт с
  атрибуцией, но без установленного происхождения основания (perspective/
  attribution_method/forward) остаётся `tentative`, факт без атрибуции —
  `unknown`. Это соответствует «weak hint» контракту, но не доказывает
  архивное покрытие отношений.
- `event_time` не выводится из `nodes`/`graph_facts` (такого поля в схеме нет):
  он передаётся вызывающим; event-узел без времени остаётся `tentative`.
- Натуральные новые production-неоднозначности и долговременное качество
  памяти этим срезом не проверяются (вне O-01/O-02).
- Изменения `message_identity.py`/`summary_aliases.py` не потребовались —
  обоснование выше; если Reviewer считает иначе, это отдельная минимальная
  правка, а не текущий кандидат.

## Housekeeping

- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-onto-01-3689dd92710d-fb344eff`
  (ветка `vmq/onto-a`) — **сохраняется** для Reviewer/DevOps.
- Отдельные `allocate`-прогоны не создавались: тесты выполнялись штатным
  pytest внутри worktree, pycache направлен в WorkspaceData глобальной
  конфигурацией. Временные файлы внедрений (`%TEMP%\onto_probe.py`,
  `sc_orig.py`, commit-message) удалены после использования; уникального
  вывода в них не осталось.
