# VMQ-M2 (M-04, M-05, O-04) — единый retrieval: person overview/temporal bundle + semantic hints

Дата: 15.11.2026. Ветка `vmq/m2`, база — принятая линия ONTO-B
`64dab0eb` (код `d15b13da`), которая стоит на ONTO-A `d67262cb`/код
`8cb9e00d` и production `c97c06e4` (2.58.203). **Code tip:
`f7a9c596638ea733de5673c5fd31675c746e20a7`** (финальный docs-коммит
добавляет только этот файл). Worktree:
`C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-onto-01-3689dd92710d-612f4000`
(unit `VMQ-M2`).

Контракт: `evidence/m2-contract-confirmation-2026-11-15.md`
(`ARCH_REUSE_CONFIRMED`; sha256 `1ac37764…bceef`), `architecture-m1-episodes.md`,
`architecture-onto-ab.md` (§49–66), `plan.md` §2/§3, `requirements-map.json`
строки `MAN-M-04` (L1073), `MAN-M-05` (L1074), `MAN-O-04` (L1078).

DDL, схемы, флагов и production **не потребовалось**. `plans/current_task.md`,
карты и производственная среда не менялись.

**Расширение write scope (approval Orchestrator, 15.11.2026):** к первичному
срезу добавлена доставка overview в живой Writer bundle и в person-overview
инструмент — минимальные правки `services/tool_router.py` и
`services/direct_chat_service.py` (см. раздел «Доставка M-04»). Владелец
формата — уже входивший в scope `services/mca_retrieval_context.py`:
добавлена чистая `overview_bundle_slots()` (единый форматтер для bundle и
tool-envelope), `apply_overview_to_bundle()` на неё делегирует; второго
форматтера/маршрута/bundle нет.

## Что изменено

| Файл | Статус | Содержание |
|---|---|---|
| `services/mca_retrieval_context.py` | +~500/−3 | `RetrievalOverview`, `overview_from_views`, `build_retrieval_overview`, `overview_bundle_slots`, `apply_overview_to_bundle`, `_semantic_hints`, `_overview_subject`; аддитивные поля `RetrievalRequest.include_overview`, `RetrievalResult.overview`, `EvidenceBundle.{coverage,independent_periods,counterexamples,limitations,episode_refs,semantic_hints}`; bounded `usage_json["overview"]` |
| `services/direct_chat_service.py` | +130/−27 | доставка overview по существующему пути: `_rag_retrieve`/`_rag_unified_rows`/`_build_rag_block` (флаг + запоминание того же результата), `_build_evidence_bundle(retrieval_result=…)`, `_apply_plan_memory_scope_locked` (historical), `_bundle_scoped_slice` (рендер слотов) |
| `services/tool_router.py` | +57/−2 | `_memory_lookup_unified(include_overview=…)`, `_memory_lookup_biography`/`_memory_lookup_general` запрашивают overview, `_memory_lookup_overview_extra` — bounded поля в envelope |
| `tests/test_memory_unified_retrieval.py` | 972 строки, 21 тест | M-04/M-05/O-04 + доставка (6 новых тестов) |
| `services/database.py`, `mca_episodes.py`, `semantic_contracts.py`, `relation_evidence.py`, `direct_context_composer.py` | без изменений | переиспользованы как владельцы |

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

### Доставка M-04 в живой Writer bundle и person-overview (approved repair)

Поток остаётся одним:

```text
direct chat: _build_user_content → _build_rag_block → _rag_unified_rows
   → _rag_retrieve → retrieve(include_overview=True)  [единственный вызов]
   → self._rag_overview_result (тот же RetrievalResult)
   → _build_evidence_bundle(retrieval_result=…) → EvidenceBundle(coverage/
     independent_periods/counterexamples/limitations/…)
   → _bundle_scoped_slice → Writer/L1-контекст (bounded, R17-safe)
person overview tool: _memory_lookup_biography/_general
   → _memory_lookup_unified(include_overview=True) → тот же retrieve()
   → envelope: coverage / independent_periods / counterexamples / limitations
```

| Файл:строка | Что именно |
|---|---|
| `direct_chat_service.py:1019–1080` (`_bundle_scoped_slice`) | рендер `Покрытие памяти` / `Независимые периоды` / `Контрпримеры памяти` / `Ограничения памяти` из слотов bundle; пусто → прежний текст байт-в-байт |
| `direct_chat_service.py:14051,14121` (`_rag_unified_rows`) | флаг `include_overview`; запоминается ТОТ ЖЕ `base`-результат (`self._rag_overview_result`); обычный путь вызывает `_rag_retrieve` прежней формой (двойники совместимы) |
| `direct_chat_service.py:14221` (`_rag_retrieve`) | `include_overview` → в существующий `RetrievalRequest` |
| `direct_chat_service.py:14435–14505` (`_build_rag_block`) | `overview_on = include_overview or is_history_query(query)` (существующая эвристика режима retrieval, не новый роутер); при `MCA_EVIDENCE_BUNDLE_ENABLED=OFF` overview не запрашивается (прежние чтения байт-в-байт) |
| `direct_chat_service.py:5452–5454` | тот же `RetrievalResult` передаётся в `_build_evidence_bundle(retrieval_result=…)` |
| `direct_chat_service.py:5931` (после `_apply_plan_memory_scope`) | пересборка под политикой плана (historical) обновляет слоты ТОГО ЖЕ bundle |
| `direct_chat_service.py:11607,11865` (`_build_evidence_bundle`) | `apply_overview_to_bundle(bundle, retrieval_result.overview)` — один bundle, `context_version`/`schema_version` не меняются |
| `direct_chat_service.py:14757-14790` (`_apply_plan_memory_scope_locked`) | `historical` — overview запрашивается при пересборке блока; двойник без поля → прежняя форма (compat) |
| `tool_router.py:4197–4271` (`_memory_lookup_unified`) | `include_overview` в существующий `RetrievalRequest` (default False — прочие purpose байт-паритетны) |
| `tool_router.py:4131–4154` (`_memory_lookup_biography`) | overview того же вызова добавляется в envelope (в т.ч. `no_data`-вариант — честные limitations) |
| `tool_router.py:4382–4401` (`_memory_lookup_general`) | то же для общего обзора |
| `tool_router.py:4639` (`_memory_lookup_overview_extra`) | bounded поля envelope через `mca_retrieval_context.overview_bundle_slots` (единый форматтер) |

Приёмка доставки (тесты):

| Клаузула | Тест |
|---|---|
| e2e: person-overview/временной путь доходит до Writer bundle с coverage/периодами/контрпримерами/limitations | `test_writer_bundle_carries_overview_from_same_result` |
| повтор мема = одна независимая опора и в bundle | `test_writer_bundle_repeated_meme_is_one_independent_period` |
| один маршрут: `retrieve()` вызван ровно один раз, тот же результат уходит в bundle, ноль embedding | `test_writer_bundle_carries_overview_from_same_result`, `test_tool_person_overview_requests_and_returns_overview` |
| обычный путь: без `include_overview` — ноль новых чтений, слоты пусты, текст прежний | `test_ordinary_direct_chat_path_has_no_overview_reads` |
| активация только на историческом/overview-вопросе + kill-switch bundle OFF | `test_build_rag_block_activates_overview_only_for_history_queries` |
| инструмент: biography/general получают поля, identity — паритет | `test_tool_person_overview_requests_and_returns_overview` |
| пустое покрытие честное (не выдумано) | `test_tool_empty_coverage_is_honest_not_fabricated` |
| cross-chat: чужие эпизоды не в bundle | `test_writer_bundle_carries_overview_from_same_result` |

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

RED модульной части на базе `64dab0eb` (набор тестов без реализации; на тот
момент 14 тестов):

```
$ python -m pytest tests/test_memory_unified_retrieval.py -q
14 failed in 6.53s
E  TypeError: RetrievalRequest.__init__() got an unexpected keyword argument 'include_overview'
```

RED доставки на `a82a9319` (текущий M2 tip без delivery-правок; 6 новых
тестов):

```
$ python -m pytest tests/test_memory_unified_retrieval.py -q
6 failed, 15 passed in 5.31s
E  KeyError: 'coverage'                    # tool envelope без overview
E  TypeError: … unexpected keyword argument 'retrieval_result'
```

GREEN на code tip `f7a9c596`:

```
$ python -m pytest tests/test_memory_unified_retrieval.py -q
21 passed in 5.29s
```

Тесты `test_overview_gate_off_keeps_zero_episode_reads` и kill-switch часть
delivery-теста добавлены как guard паритета при выключенных гейтах.

## Мутационная проверка (assertions не тавтологичны)

| Мутация | Результат |
|---|---|
| A: повтор мема считается независимой опорой | KILLED — `test_repeated_meme_is_not_independent_period` (1 failed) |
| B: `coverage.complete` объявляется `True` | KILLED — `test_person_overview_overview_and_single_bundle` |
| C: legacy-факт выброшен из hints (отбор вместо подсказки) | KILLED — `test_semantic_hints_do_not_change_candidates` |
| D: `source_fingerprint` выпадает из overview (коррекция не видна) | KILLED — `test_corrections_and_versions_apply_to_next_query` |
| E: живой seam bundle не наполняется overview (`_build_evidence_bundle`) | KILLED — `test_writer_bundle_carries_overview_from_same_result` |
| F: `_bundle_scoped_slice` не рендерит coverage | KILLED — тот же e2e |
| G: biography не запрашивает overview | KILLED — `test_tool_person_overview_requests_and_returns_overview` |
| H: `_rag_retrieve` игнорирует `include_overview` | KILLED — e2e bundle |

Все мутации откатаны; после отката SHA-256 файлов совпали с исходными
(`mca_retrieval_context.py` — `31234fea…dba62`; `direct_chat_service.py` и
`tool_router.py` — откат подтверждён скриптом `restored: True`), `git diff`
не содержит остаточных правок.

## Затронутые suite на точном кандидате

Финальный совместный прогон затронутых наборов (24 файла, `--timeout=180`,
один pre-existing deselected):

```
tests/test_memory_unified_retrieval.py                       21 passed
tests/test_memory_unified_retrieval_06.py                    (tool/lookup seam)
tests/test_memory_lookup_round1026.py
tests/test_mca07_retrieval_context_round1027.py
tests/test_mca08_character_speech.py
tests/test_mca16_experience_block_a_round1039.py
tests/test_mca16_experience_block_b_round1039.py
tests/test_mca22_truthset_round1027.py
tests/test_history_isolation.py
tests/test_mem_time_policy.py
tests/test_mem_time_l1_scope.py
tests/test_mem_time_profile.py
tests/test_memory_period_vector_leg.py
tests/test_speech_p0_a2_memory.py
tests/test_speech_p0_rag_diag.py
tests/test_mca19_block_g_round1043.py
tests/test_image_context_memory_round1026.py
tests/test_caps_tool_results.py
tests/test_tool_schemas.py
tests/test_mem08_search_read_model.py
tests/test_mem08_omnibox.py
tests/test_memory_contracts.py
tests/test_semantic_contracts.py
tests/test_vmq_m1_episode_contract.py
Итого: 727 passed, 1 deselected
```

Отдельно: **283 passed** — delivery-набор
(`test_memory_unified_retrieval*`, `test_memory_lookup_round1026`,
`test_mca07`, `test_mca08`, `test_mca16 a/b`, `test_mca22_truthset`,
`test_history_isolation`).

Предсуществующие падения на базе (проверено откатом правок до `f7a9c596`,
тот же результат — не связаны с M2):

```
test_speech_p0_a2_memory.py::TestSelfEchoNotFactual::test_style_anchors_not_broken  (deselected)
test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff
test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools
   → 2 failed, 95 passed в test_tool_coordinator/test_tool_chains
```

Предсуществующий wall-clock flake (не связан с M2):
`test_mca09_intents_block_e_round1040.py::test_handle_initiative_sent_single_transport_chunks`
(`services/mca_intents._now()` по умолчанию берёт `time.time()` — «тихие
часы» зависят от реального времени; в изоляции проходит). В раздельных
прогонах печатается предсуществующее
`WARNING: closed N leaked aiosqlite connection(s)` (наборы `mca22`/`mca05`);
новый файл закрывает свои соединения в `finally`. Полный suite проекта не
запускался: изменены 3 существующих seam-файла аддитивно + один retrieval
модуль; blast radius ограничен перечисленными наборами.

## DB / resource / cross-chat (реальные числа probe)

Probe-artifact'ы сняты на `69ea617c`; модульная логика overview доставкой не
менялась (те же значения подтверждены тестами на code tip).

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

## Честные ограничения

1. **Доставка M-04 реализована** (approved repair): тот же `RetrievalResult`
   наполняет ЕДИНЫЙ `EvidenceBundle` и рендерится в `_bundle_scoped_slice`;
   person-overview инструмент (`biography`/`general`) получает bounded поля
   в envelope. Второго retrieval/bundle/store/composer-пути нет.
   Остаточные ограничения доставки:
   * активация overview в direct-chat опирается на СУЩЕСТВУЮЩУЮ эвристику
     режима retrieval (`is_history_query`) и явное `historical`-решение L1 —
     нового роутера нет, но это значит, что «исторические» формулировки
     («расскажи…») получают 2 дополнительных bounded episode-чтения на ход;
     кандидаты/порядок/каналы от этого не меняются;
   * `identity/appearance/speech_style/relationships` overview не запрашивают
     (это не overview-цели) — паритет прежнего envelope;
   * при kill-switch `MCA_EVIDENCE_BUNDLE_ENABLED=OFF` overview не читается
     вовсе (прежние чтения байт-в-байт), а инструмент свой envelope сохраняет;
   * единый форматтер `overview_bundle_slots` живёт в
     `mca_retrieval_context.py` (модуль уже в scope этого среза): без него
     пришлось бы дублировать формат текста в tool_router.
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
