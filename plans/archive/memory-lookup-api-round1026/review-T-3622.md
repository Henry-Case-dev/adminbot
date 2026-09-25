# A6 `memory-lookup-api-round1026` — Review (T-3622, единый Reviewer gate)

- **Feature-ID:** `memory-lookup-api-round1026`
- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 4 — A6
- **Risk-Level:** R2 (ADR-1026-18 D11; по фактическому diff не повышен — control-flow `tool_loop` не менялся, изменения аддитивны/обратимы)
- **Status:** **Approved**
- **Release policy:** EPIC_ONLY — фича-гейт. Одобрение разрешает включение в pending epic-release кандидат; **деплой не разрешает** (агрегатный gate Эпика 3 — отдельно). Deploy = `DEFERRED_TO_EPIC`; `APP_VERSION` = **2.58.30** (без bump); пер-фича тега/коммита нет.
- **Scanner:** отсутствует — обе линзы (requirements/correctness + focused change audit) выполнены в этом едином проходе.

## Binding

- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash (SHA-256):** `05d882ea5ff64ed982a46aabbd46ae22c0dbaf4c69b96c567395de9fb6d2f543`
- **Spec-Hash (SHA-256, полный `spec.md`):** `4d81918024a43b883bc5491ed38d4b2e28af07defbcc0845d21f83d1eb79a36a`

**Recipe Working-Tree-Hash** (детерминированно, из корня репозитория):

```
h_diff    = sha256( stdout("git --no-pager diff e8646af") )               # bytes
h_status  = sha256( stdout("git status --porcelain") )                    # bytes
h_unt     = sha256( file_bytes("tests/test_memory_lookup_round1026.py") ) # новый A6-тест
Working-Tree-Hash = sha256( h_diff + h_status + h_unt )                   # три hex-строки, конкатенация, sha256
```

Фактические компоненты: `h_diff = 892c9bcfd4ed3a03c28344336ec9169b5e30fbf955b38d4e0dac58fa281b05f1`,
`h_status = 3ca2d16d00ba5a3212f7c61ee9af635f4d1ade3d76c6b9aef22797ba7e22dddb`,
`h_unt = d6256bcba04732110ae00f2ade6a89cc11c248fe02728ca91f7adbd0cf42dffb`.

> Working tree намеренно «грязный»: содержит sanctioned эпик-релизные A2/A3/A5 (не коммитить) **плюс** A6. Одобрение связано с этим точным снапшотом. Любой коммит, правка A6-файлов, spec.md или untracked A6-теста инвалидирует одобрение (пересчёт обязателен).

## Git base и inspected change scope

- **Base anchor:** `e8646af` (== HEAD). Baseline по spec/ADR: канон 11, SQLite v12, каталог 470/427/445/101/99/21, `APP_VERSION` 2.58.30.
- **A6-sanctioned файлы с изменениями (подтверждено `rg`):** `services/tool_schemas.py`, `services/tool_router.py`, `config/settings.py`, `services/database.py` (read-only reader), `tests/test_memory_lookup_round1026.py` (новый) + canon re-pin в 11 существующих тест-файлах.
- **Scope creep:** **не обнаружен.** Маркеры `get_user_context`/`MEMORY_LOOKUP`/`_memory_lookup` отсутствуют в `services/worker_budget.py`, `services/image_generation.py`, `services/pg_db.py`, `services/direct_chat_service.py`, `services/smartmodule_urls.py`, `services/param_catalog.py`, `services/tool_loop.py`, `bot.py`, `web/`, `plans/`. Проверено `rg -l`.
- `git diff --check` → exit **0** (только информационные LF→CRLF warnings).
- Изменения A2/A3/A5 в дереве (fetch_article, generate_image legacy/v21, image-paths) — чужие для A6, корректно помечены своими ADR; A6-правки — только хвост.

## Checks performed (воспроизведено независимо)

| Проверка | Команда | Результат |
|---|---|---|
| Новый A6-тест | `pytest tests/test_memory_lookup_round1026.py -q` | **43 passed** in 2.49s |
| Canon/координатор/цепочки | `pytest tests/test_tool_schemas.py tests/test_tool_coordinator_round1026.py tests/test_tool_calling_round1015.py -q` | **104 passed** in 3.01s |
| Полный регресс | `pytest -q` | **9213 passed, 0 failed** in 151.97s (1 warning, не связано) |
| JS-тесты | `node tests/js/*.js` (47 файлов, node v24.16.0) | **47/47, 0 fail** |
| Каталог | `param_catalog` | **REGISTRY 470 · Settings 427 · categorized 445 · GROUPS 101 · `_TAB_BY_GROUP` 99 · TAB_RULES 21** — без изменений |
| DDL | схема SQLite | `user_version` = **12** (полный suite, `test_database.py`); A6-reader — только `SELECT`; новых таблиц/колонок/индексов/PG нет |
| `APP_VERSION` | `config/settings.py:1886` | **2.58.30** (без bump) |
| diff-check | `git diff --check` | exit **0** |

## Requirement / evidence coverage (Lens 1)

| REQ | SC | Реализация | Подтверждение |
|---|---|---|---|
| A6-01 | SC-01/19 | `_get_user_context` (LLM-initiated tool), `TOOL_GET_USER_CONTEXT` | `test_schema_shape`, `TestPurposeRouting`, `TestComposition` |
| A6-02 | SC-02 | Выдача по одному человеку/purpose, без dump | `test_no_universal_dump_only_asked_person` (1 вызов reader'а) |
| A6-03 | SC-03/19 | Своя карта источников на 6 purpose | `TestPurposeRouting` (identity/appearance/biography/relationships/general/speech_style) |
| A6-04 | SC-04 | Схема `person`/`user_id`/`purpose`/`max_items`; `required=[person,purpose]`; `additionalProperties:false` | `test_schema_shape` |
| A6-05 | SC-05/19 | enum 6 значений | `test_schema_shape`; неизвестный → `invalid_purpose` |
| A6-06 | SC-06/21 | `chat_id` из `ToolContext` (не параметр модели); адаптация контракта | схема без `chat_id`; `_memory_lookup_parse`; canon-тесты |
| A6-07 | SC-07 | reuse AliasResolver/`get_persona_card`/`get_generated_dossier`/`format_dossier_block`/RAG; read-only reader; Δ DDL=0 | boundary + `get_user_context_facts` (SELECT) |
| A6-08 | SC-08/20 | envelope 5 полей §33 (facts/sources/confidence/time_context/no_data) | `test_five_fields_always_present` |
| A6-09 | SC-09/20 | `unknown` без носителя; `confirmed` только при `status='confirmed'`; weight<0.5 → `likely` | `test_unknown_never_confirmed_without_carrier`, `test_low_weight_is_likely_not_confirmed` |
| A6-10 | SC-10 | lazy RAG только `{general, speech_style}` | `TestLazyRag` (spy `memory.calls == []` для 4 purpose) |
| A6-11 | SC-11 | hard-ceiling 20; slice ≤5; | `TestCaps` |
| A6-12 | SC-12 | фрагмент ≤240 симв.; результат ≤4000/`truncated` | `test_slice_chars_capped`, `test_result_budget_4000_with_truncated_flag` |
| A6-13 | SC-13 | `speech_style` = compact-профиль; личность бота не меняется | код (`_memory_lookup_style_profile`), boundary |
| A6-14 | SC-14 | envelope через A2 `chat_with_tools`; invalid-args не рвёт цепочку | `test_envelope_reaches_tool_context`, `test_invalid_does_not_crash_chain` |
| A6-15 | SC-15 | `factcheck_tools==3`; память ≠ фактчек (в `description`) | `test_factcheck_tools_unchanged_three`, `test_memory_tool_absent_from_factcheck` |
| A6-16 | SC-16 | §52 п.11/12 — композиция через существующий A2 | `TestComposition` |
| A6-17 | SC-17/21/22 | unknown/ambiguous/R17-лог/OFF-паритет | `test_unknown_person_honest`, `test_ambiguous_name_no_fact_merge`, `TestR17Log`, `test_active_tools_memory_off` |
| A6-18 | SC-18/22 | артефакт механизма; deploy `DEFERRED_TO_EPIC`, hot/cold-откат | evidence/boundary; коммитов/тегов/bump нет |

**Не покрытых REQ/SC не найдено.** Orphan-REQ/SC отсутствуют.

## Focused change audit (Lens 2)

- **Канон-атомарность:** A6-добавления — **только в хвост** `TOOL_CALLING_TOOLS` (11-й `fetch_article` — A2; 12-й `get_user_context` — A6); схема, `MEMORY_LOOKUP_TOOL_NAME`, `_memory_lookup_enabled`, env-гейт, диспетчер (`tool_router.py:547`), тесты `len==12` — в одном изменении. Из `git diff HEAD -- services/tool_schemas.py` видно, что A6 не трогает `TOOL_QUERY_CHAT_MEMORY`…`TOOL_TRANSCRIBE_VIDEO` (первые 10 — байт-в-байт к HEAD; A2-блок `TOOL_FETCH_ARTICLE` помечен ADR-1026-15, A6-блоки — ADR-1026-18).
- **Kill-switch:** `MEMORY_LOOKUP_ENABLED` (ClassVar, env-only, default ON, `settings.py:903`); `active_tools()` при OFF исключает ровно `get_user_context`; `TOOL_CALLING_TOOLS` остаётся 12. Активный набор: default (image OFF) = **11** (12 − generate_image); OFF = **10** — байт-паритет с baseline-набором после A2/A3/A5 (совпадает с evidence и тестом). «Остальные 11» из SC-A6-21 выполняются на уровне канона (12−1). Прямой вызов при OFF → `{"status":"error","error":"disabled"}`.
- **R17-лог:** единственная новая строка — `_memory_lookup_finish` (`tool_router.py:1205`): `purpose/user_id/chat_id/count/latency_ms/empty_reason`; `purpose` клампится к enum/`-`; исключение логируется только классом (`type(exc).__name__`). Тексты досье/сообщений/имён/сырых аргументов в логах отсутствуют (грепом по A6-методам + `TestR17Log`). Envelope `data` живёт в `ctx.tool_results` in-memory; `tool_loop` логирует только `tool`/`out_chars`/счётчики — R17-safe.
- **Reuse / anti-duplication:** не дублируются `build_persona_card`/`format_dossier_block`/RAG; `get_user_context_facts` (`database.py:4653`) — тонкий read-only `SELECT` по существующему `graph_facts` (колонки `last_confirmed_at`/`message_timestamp`/`kind` существуют в миграциях v12), без DDL/второго хранилища. Резолвер — существующий `AliasResolver` (`_aliases`/`canon_name`/`resolve`); при отсутствии — fail-open `build_alias_resolver`.
- **Интеграция:** `deps.db`/`deps.aliases`/`deps.memory` реально инжектятся (`bot.py:494-510`), поэтому инструмент работоспособен вне тестов; `_classify_output` разворачивает JSON в `data`; `get_user_context` **не** в `METERED_TOOLS` (`tool_loop.py:55`) → `metered=false` (free/local).
- **Границы:** Δ DDL=0, Δ каталога=0, A4 (§22–§25) не реализован (appearance = generic-лексиконный фильтр + honest `no_data`; извлечение — A4), A5/A7/§104 не затронуты, `factcheck_tools==3`, промпты не менялись (кроме `description` новой схемы, санкционировано D1).
- **Test quality spot-check:** lazy-RAG spy — содержательный (`memory.calls == []`); honesty-тест — содержательный (проверяет `confidence.available=False/label=unknown`, отсутствие `confirmed` без носителя); byte-parity-тест — **тавтологичный** (см. L-A6-01), но требование независимо подтверждено diff-инспекцией.

## Counterexamples checked

- Невалидные аргументы (`missing_person`/`invalid_purpose`/`invalid_person`/`invalid_max_items`, включая `0/-3/"x"/True`) → структурная ошибка, цепочка/следующий инструмент живы (`test_invalid_does_not_crash_chain`).
- Неизвестный человек → `status:"ok"`, `no_data:true`, `unknown_person` (честно, не ошибка).
- Одинаковые имена (`{"5":"Лёха","6":"Лёха"}`) → `ambiguous`, кандидаты `[5,6]`, факты не сливаются и не возвращаются.
- RAG-шум (`get_rag_facts`/`search_long_term` заполнены) при identity/appearance/biography/relationships → RAG **не** вызывается.
- Переполнение: 10 фактов по 3000 симв. → результат ≤4000 и `truncated=true`.
- Kill-switch OFF → инструмент скрыт, прямой вызов → `disabled`.
- Приватный факт/имя в логах — отсутствуют (`TestR17Log`).
- `max_items=999` → clamp до 20.

## Blocking findings

**Нет.** Critical/High и requirement-blocking Medium отсутствуют.

## Non-blocking debt (Low, регистрируется; не блокирует релиз)

| ID | Severity | Location | Суть / рекомендация |
|---|---|---|---|
| L-A6-01 | Low | `tests/test_memory_lookup_round1026.py:165-186` | `test_first_eleven_byte_identical` сравнивает `TOOL_CALLING_TOOLS[:11]` с теми же модульными объектами (тавтология): ловит переупорядочивание, но **не** мутацию содержимого схем. Требование выполнено (независимо подтверждено diff-инспекцией: A6 — только хвост), но для регресс-мощности стоит сравнивать со снимком (JSON-сериализация/стабильные байты). |
| L-A6-02 | Low | `services/tool_router.py:1214-1246` + `:1819` | В предельном случае усечения (>4000 симв.) `_memory_lookup_serialize` может опустошить `facts[]`, оставив `no_data:false`. Косметическая нестыковка флагов; рекомендуется после усечения пересчитать `no_data`, если `facts` пуст. |
| L-A6-03 | Low | `tests/test_tool_schemas.py:122-123` (и docstring `active_tools`) | Устаревший комментарий «полный канон 11» после bump 11→12 (само ассершн-множество корректно, exact `== 12`). Документационная правка. |
| L-A6-04 | Low | `services/tool_router.py:1425-1442` | Для неизвестного человека `appearance` возвращает `empty_reason="no_storage_for_purpose"`, а не `unknown_person`. Оба честны (`no_data:true`), но семантически можно уточнить. |
| L-A6-05 | Low | `plans/features/memory-lookup-api-round1026/spec.md` §6.1 | Формулировка «при `MEMORY_LOOKUP_ENABLED=OFF` — 11» неоднозначна: активный набор = 10 (baseline-паритет), а «остальные 11» относятся к канону. Кода/приёмки не нарушает; рекомендуется уточнить при merge в ARCHITECTURE. |
| L-A6-06 | Low | `services/tool_router.py:1274-1284` | `user_id`/`max_items` коэрцятся (`int(2.5)`, `int("7")`) — лояльнее JSON-схемы. Не вредит (схема гейтит модель), но строгая типизация была бы аккуратнее. |

## Unavailable checks

Обязательных недоступных safety-проверок нет. Отмечу: отдельного threat/failure-файла нет — для R2 он не обязателен (R3-атрибут); live-интеграция с прод-БД не выполнялась (фича не задеплоена и deploy `DEFERRED_TO_EPIC`), но полный suite + инспекция схемы/миграций закрывают SQL-совместимость read-only reader'а.

## Handoff

- Это **feature gate**, не агрегатный epic-release gate. `Status: Approved` разрешает включение A6 в pending epic-release кандидат Эпика 3; **деплой/DevOps не авторизуется** (EPIC_ONLY). Агрегатный gate — на границе эпика, когда все фичи одобрены.
- Машинный чекпоинт пишет @Orchestrator (Reviewer его не трогает).
