# VMQ-M2 (M-04, M-05, O-04) — единый retrieval: person overview/temporal bundle + semantic hints

Дата: 15.11.2026. Ветка `vmq/m2`, база — принятая линия ONTO-B
`64dab0eb` (код `d15b13da`), которая стоит на ONTO-A `d67262cb`/код
`8cb9e00d` и production `c97c06e4` (2.58.203). Worktree:
`C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-onto-01-3689dd92710d-612f4000`
(unit `VMQ-M2`).

Контракт: `evidence/m2-contract-confirmation-2026-11-15.md`
(`ARCH_REUSE_CONFIRMED`; sha256 `1ac37764…bceef`), `architecture-m1-episodes.md`,
`architecture-onto-ab.md` (§49–66), `plan.md` §2/§3, `requirements-map.json`
строки `MAN-M-04` (L1073), `MAN-M-05` (L1074), `MAN-O-04` (L1078).

Расширение write scope, DDL, схемы, флагов и production **не потребовалось**.
`plans/current_task.md`, карты и производственная среда не менялись.

## Что изменено

| Файл | Статус | Содержание |
|---|---|---|
| `services/mca_retrieval_context.py` | +478/−3 (только добавления, кроме 1 переписанной строки `fact_rows`) | `RetrievalOverview`, `overview_from_views`, `build_retrieval_overview`, `apply_overview_to_bundle`, `_semantic_hints`, `_overview_subject`; аддитивные поля `RetrievalRequest.include_overview`, `RetrievalResult.overview`, `EvidenceBundle.{coverage,independent_periods,counterexamples,limitations,episode_refs,semantic_hints}`; bounded `usage_json["overview"]` |
| `tests/test_memory_unified_retrieval.py` | новый, 15 тестов | M-04/M-05/O-04 на реальной БД и существующих владельцах |
| `services/database.py`, `mca_episodes.py`, `semantic_contracts.py`, `relation_evidence.py`, `direct_context_composer.py`, `direct_chat_service.py`, `tool_router.py` | без изменений | переиспользованы как владельцы |

Единый маршрут сохранён: `retrieve()` остаётся **единственной** точкой.
Новых маршрутов/поиска/БД/провайдера/LLM/embedding нет; overview строится
ТОЛЬКО когда вызывающий явно попросил (`include_overview=True`), иначе
результат прежний байт-в-байт (ноль новых чтений — проверено SQL-трассой).

## Соответствие приёмке

### M-04 — person overview / temporal через существующий `retrieve()`

| Клаузула | Как выполнено | Тест |
|---|---|---|
| один `retrieve()` отвечает на person overview | `retrieve(include_overview=True)` + существующий субъект-канал (`subject_ref_id`/`target_user`) и episode-канал | `test_person_overview_overview_and_single_bundle` |
| temporal queries по периодам | coverage по времени ИСХОДНЫХ сообщений (`period_year` M1), честный пропуск года | `test_temporal_query_across_periods_single_route` |
| bundle содержит coverage | `EvidenceBundle.coverage` (периоды + границы + пропуски) | там же; probe-artifact |
| независимые периоды | `independent_periods`/`period_support`: одинаковый нормализованный текст (мем) не добавляет опору | `test_repeated_meme_is_not_independent_period` |
| контрпримеры | `EvidenceBundle.counterexamples` из `LongitudinalView.counterexample_pairs`, отдельно от `support_source_refs` | `test_person_overview_overview_and_single_bundle` |
| limitations | `EvidenceBundle.limitations` = честные коды M1 + `repeated_claims_present`/`episode_source_integrity_partial`/`episodes_stale`/scope-коды | там же; `test_empty_coverage_is_honest` |
| повтор мема ≠ независимое подтверждение | `independent_support_count=1`, `repeated_claims=1`, период 2023 `independent=0` | `test_repeated_meme_is_not_independent_period` |
| деградация без потери выдачи | ошибка episode-view → `overview=None`, retrieval `ok` | `test_overview_failure_does_not_break_retrieval` |
| покрытие не объявляется полным | `coverage["complete"]=False` + `complete_reason` | `test_person_overview_overview_and_single_bundle` |

### M-05 — нет mass reembedding / destructive rewrite / cross-chat

| Клаузула | Как выполнено | Тест / artifact |
|---|---|---|
| нет mass re-embedding | векторный канал остаётся один (`retrieve_fact_candidates`); `embed_text`/`upsert_fact_vector`/`rebuild_index` не вызываются | `test_overview_reads_are_read_only`, `test_temporal_query_across_periods_single_route` |
| нет destructive rewrite/DDL | ноль write-SQL за два overview-вызова; `PRAGMA user_version` и список таблиц неизменны; строки `smart_messages`/`mca_episodes`/`graph_facts`/`mca_source_refs` те же | `test_overview_reads_are_read_only`; `probe-onto-single-retrieval-e2e.json` |
| нет cross-chat | overview — ровно `chat_id` запроса; ACL-набор из >1 чата НЕ сливается (код ограничения); эпизоды/факты чужого чата не попадают | `test_foreign_chat_rows_never_leak_into_overview`, `test_multi_chat_acl_scope_is_not_merged` |
| гейт OFF = прежний путь | `MCA_EPISODES_ENABLED=OFF` → `overview=None`, ноль чтений `mca_episodes` | `test_overview_gate_off_keeps_zero_episode_reads` |
| DB/resource | файловая БД (WAL): `user_version 47 → 47`, `journal_mode=wal`, WAL байты не изменились, counts равны до/после | `probe-onto-single-retrieval-e2e.json` → `db_resource_check` |

### O-04 — один retrieval, definitions как hints, corrections/versions

| Клаузула | Как выполнено | Тест |
|---|---|---|
| definitions — hint, не router | `_semantic_hints` через существующий `semantic_contracts` (`project_identity`, `project_fact_meaning`); кандидаты/порядок идентичны с hints и без | `test_semantic_hints_do_not_change_candidates` |
| нет второго роутера/БД/search engine | hints не выполняют SQL; additional SQL — только существующие чтения `mca_episodes`; FTS-вызовы те же | `test_one_route_no_extra_search_or_model_calls` |
| alias/имя не повышаются до verified | `participant_identity/verified` только для uid; имя без устойчивой идентичности — `basis=none`, `status!=verified` + код ограничения | `test_subject_definition_hint_is_not_promoted` |
| ambiguity не выбирает субъекта | `ambiguous_subjects` → субъект не фильтруется + код | `test_subject_definition_hint_is_not_promoted` |
| corrections/versions применяются к последующим запросам | версия источника (`smart_messages.current_revision`) меняет `episode_versions.source_fingerprint`; снятая атрибуция факта меняет `verification` следующего запроса; отдельного журнала/таблицы нет | `test_corrections_and_versions_apply_to_next_query` |
| e2e-трасса одного маршрута | SQL-трасса одного `retrieve()` + counters в `probe-onto-single-retrieval-e2e.json` | probe-artifact |
| bounded | caps на эпизоды/периоды/контрпримеры/limitations/hints; `as_dict()` JSON-совместим | `test_overview_bounded` |

## RED → GREEN (кандидат-связанные прогоны)

RED на базе `64dab0eb` (набор тестов без реализации; на тот момент 14 тестов):

```
$ python -m pytest tests/test_memory_unified_retrieval.py -q
14 failed in 6.53s
E  TypeError: RetrievalRequest.__init__() got an unexpected keyword argument 'include_overview'
```

Пятнадцатый тест (`test_overview_gate_off_keeps_zero_episode_reads`) добавлен
вместе с GREEN как guard паритета при выключенном гейте: он использует то же
отсутствующее на базе поле запроса.

GREEN на code tip (этот коммит):

```
$ python -m pytest tests/test_memory_unified_retrieval.py -q
15 passed in 4.64s
```

## Мутационная проверка (assertions не тавтологичны)

| Мутация | Результат |
|---|---|
| A: повтор мема считается независимой опорой | KILLED — `test_repeated_meme_is_not_independent_period` (1 failed) |
| B: `coverage.complete` объявляется `True` | KILLED — `test_person_overview_overview_and_single_bundle` |
| C: legacy-факт выброшен из hints (отбор вместо подсказки) | KILLED — `test_semantic_hints_do_not_change_candidates` |
| D: `source_fingerprint` выпадает из overview (коррекция не видна) | KILLED — `test_corrections_and_versions_apply_to_next_query` |

Все мутации откатаны; SHA-256 файла после отката совпал с исходным
(`31234fea…dba62`), `git diff` не содержит остаточных правок.

## Затронутые suite на точном кандидате

```
tests/test_memory_unified_retrieval.py                         15 passed
tests/test_mca07_retrieval_context_round1027.py
tests/test_vmq_m1_episode_contract.py
tests/test_semantic_contracts.py
tests/test_mca22_core_round1027.py
tests/test_mca22_truthset_round1027.py                       213 passed  (вкл. 15 новых)
tests/test_mem08_search_read_model.py
tests/test_mem08_omnibox.py
tests/test_mem_time_asof.py
tests/test_mem_time_l1_scope.py
tests/test_mem_time_policy.py
tests/test_history_isolation.py
tests/test_memory_contracts.py
tests/test_memory_attribution.py
tests/test_mca05_episodes_stories_round1027.py               299 passed
tests/test_mca16_experience_block_a_round1039.py
tests/test_mca16_experience_block_b_round1039.py
tests/test_mca09_intents_block_e_round1040.py                153 passed
  (+1 deselected: test_handle_initiative_sent_single_transport_chunks)
tests/test_evol_social_frame.py
tests/test_mca15_chat_statistics_round1028.py
tests/test_summary_memory.py
tests/test_search_aggregator.py
tests/test_search_short_tokens.py
tests/test_unified_reply_ur_b_search_first.py                168 passed
```

Итого (один совместный прогон 24 файлов, exact candidate): **833 passed,
1 deselected, 1 warning (предсуществующий:
`coroutine 'start_resume_ticker...' was never awaited`)**.

Предсуществующий wall-clock flake (не связан с M2):
`test_mca09_intents_block_e_round1040.py::test_handle_initiative_sent_single_transport_chunks`
в одном прогоне дал `AssertionError: 'silent' == 'sent'`; причина —
`services/mca_intents._now()` по умолчанию берёт `time.time()` (строка 94),
т.е. «тихие часы» зависят от реального времени. В изоляции на том же
кандидате тест проходит (`1 passed in 3.88s`); `include_overview` по
умолчанию `False`, retrieval в этом тесте не участвует. В раздельных
прогонах тех же наборов дополнительно печатается предсуществующее
`WARNING: closed N leaked aiosqlite connection(s)` (наборы `mca22`/`mca05`,
до этой правки); новый файл закрывает свои соединения в `finally`. Полный
suite проекта не запускался: изменён один retrieval-модуль аддитивным слоем,
blast radius ограничен перечисленными наборами.

## DB / resource / cross-chat (реальные числа probe)

`evidence/vmq-m2/probe-onto-single-retrieval-e2e.json` (файловая БД, WAL,
exact candidate):

- `user_version`: 47 → 47; `journal_mode = wal`; WAL: 4 124 152 → 4 124 152 байт;
- `write_statements`: `[]` (ни INSERT/UPDATE/DELETE/DDL за вызов);
- counts до/после равны: `smart_messages`, `mca_episodes`, `mca_story_versions`,
  `graph_facts`, `mca_source_refs`, `mca_evidence_links`,
  `mca_embedding_index_generations`;
- cross-chat: эпизоды/факты второго чата в overview и кандидатах — `[]`;
- один маршрут: `graph_facts_fts MATCH`×1, `smart_messages_fts MATCH`×1,
  episode-чтения ×2 (существующие `subject_longitudinal_view` +
  `list_episode_views`), forbidden memory calls `[]`.

`evidence/vmq-m2/probe-person-overview-bundles.json` — тот же кандидат:
периоды 2021/2023, пропуск 2022, `independent_support_count=2`,
counterexamples=1, limitations=5, `semantic_hints` = participant_identity/verified
+ tentative + unknown (legacy).

## Конфигурация и гейты

- Новых флагов/settings нет. Overview включается **только** полем запроса
  `include_overview` (default `False` = прежнее поведение).
- Чтение overview живёт под существующим мастер-гейтом
  `MCA_EPISODES_ENABLED` (default ON); при OFF → `overview=None`, retrieval
  работает как раньше.
- `MCA_RETRIEVAL_CONTEXT_ENABLED`/`MCA_EVIDENCE_BUNDLE_ENABLED` не менялись;
  тесты пути bundle выполнялись с их effective-значением по умолчанию (ON).
- Тестовые override: только `DatabaseService(":memory:")` и spy-memory для
  векторного канала; значения продакшн-настроек не подменялись.

## Честные ограничения и найденный gap доставки

1. **Доставка overview в ЖИВОЙ Writer-bundle/person-overview — вне write scope
   этого среза и НЕ реализована.** Фактическое состояние:
   * единственный `EvidenceBundle` живого пути собирается в
     `services/direct_chat_service.py::_build_evidence_bundle` (строка 11568;
     `return _mca_rc.EvidenceBundle(...)` — 11825) из уже отрендеренных
     user-блоков, а в Writer/System2 попадает через `_bundle_scoped_slice`
     (1019–1059). Вызов на строке 5424 **не имеет** `RetrievalResult` в
     области видимости, поэтому «в одну строку» overview туда не подать;
   * person-overview инструмент уже идёт через тот же `retrieve()`:
     `services/tool_router.py::_memory_lookup_unified` (4193–4260) собирает
     `RetrievalRequest(purpose="dossier", intent="who",
     subject_entity_ids=…, subject_names=…)` и вызывает единственную точку.
     Чтобы overview доходил до ответа инструмента, там нужен
     `include_overview=True` + перенос overview в конверт инструмента;
   * `services/direct_context_composer.py` bundle вообще не потребляет
     (`grep bundle` — 0), поэтому «доставка через composer» невозможна.
   Оба требуемых изменения — в файлах вне выданного write scope
   (`direct_chat_service.py`, `tool_router.py`). **Нужно решение
   Orchestrator**: либо сериализованный минимальный patch этих двух call-site
   (proposed: `include_overview=True` в `_memory_lookup_unified`;
   `bundle = _mca_rc.apply_overview_to_bundle(bundle, overview)` после сборки
   bundle + рендер новых слотов в `_bundle_scoped_slice`), либо привязка
   доставки к следующему срезу (VMQ-MEM/релиз). Модульная часть M-04
   (overview + слоты ЕДИНОГО bundle) реализована и проверена.
2. **Live/preprod evidence M-04/O-04 не получен**: по заданию production/
   deployment запрещены, поэтому `person-overview-bundles.json` и
   `onto-single-retrieval-e2e.json` как LIVE-артефакты остаются открытыми.
   Вместо них приложены честно помеченные `artifact_kind:
   candidate_probe_not_live` файлы с реальным выводом того же кандидата.
3. `independent_periods` группирует различный нормализованный текст по
   периоду первого появления; повтор в другом периоде не добавляет
   независимой опоры. Это консервативно: точная переформулировка одного факта
   разными словами считается независимой (лексическое сравнение — вне
   контракта и создало бы новый словарь).
4. Историческое multi-period чтение профиля не возвращает `chat_id`
   (оконный SELECT), поэтому в hints подставляется фактический scope чтения
   (`request.chat_id`), а не выдуманное значение. Других подстановок нет.
5. `edges.relation_type` и typed-relations ONTO-B в overview не включены:
   O-04 требует definitions как hints и один маршрут; typed-relation проекция
   уже доступна отдельным API (`semantic_contracts.project_relation`) и не
   дублируется здесь, чтобы не появлялось второго чтения `edges`.
6. Внешние источники не использовались: решение основано на зафиксированном
   контракте и текущем коде кандидата.

## Housekeeping

- Probe-run `WorkspaceData/runs/…/probe-bba963574c` закрыт после переноса
  результатов в этот файл и probe-artifact'ы (`run-close --apply`).
- Worktree сохранён для Reviewer по указанию Orchestrator (unit `VMQ-M2`,
  ветка `vmq/m2`).
