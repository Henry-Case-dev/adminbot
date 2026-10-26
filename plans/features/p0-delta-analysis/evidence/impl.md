# P0 DELTA — implementation evidence (lane P0-DELTA-IMPL)

- Ветка: `task/p0-delta` (worktree `C:\Code\Python\adminbot-wt-delta`), база
  `release/p0-2026-10-26` @ `87ad5908` (deployed 2.58.131).
- Дата: 26.10.2026. Однописатель (LEAF), сабагентов нет, прод/SSH/Telegram не
  трогались.
- Источники: `plans/owner_inputs/2026-10-26-p0-delta-analysis.md` (§1-§14);
  аудит `plans/features/p0-delta-analysis/evidence/audit.md` (файл:строки на
  534ac7dd, дефекты подтверждены на проде 2.58.130).

## Дефект 1 — Lore bypass без проверки интента (audit §5)

**Было** (`direct_chat_service.py:3825-3827` @87ad5908): условие подмены —
только `lore_compiled and lore_story`; готовая драматичная история заменяла
ответ Writer на ЛЮБОМ ходе, где tool-модель вызвала `compile_lore_story`.

**Стало**:
- `services/direct_l1.py` — детерминированный предикат
  `lore_story_delivery_allowed(l1_plan, response_plan)` по СУЩЕСТВУЮЩИМ полям
  плана: story-акты (`creative`, `historical_recall`) / `structure=story` →
  подмена разрешена; analysis-акты (`research`, `explanation`, `comparison`,
  `summarization`, `clarification` — включая канонизацию «analysis»/«анализ»
  из P0C-INT R2) и структуры (`report/explanation/comparison/summary/steps`) →
  подмена запрещена, история остаётся материалом в evidence-пакете (тул-
  результат с provenance уже внутри, Writer отвечает сам); интенция не
  определена или плана нет (легаси/fallback) → **fail-open** (прежнее
  поведение, без ложноположительных блоков).
- `services/direct_chat_service.py` — точка подмены вынесена в юнит-
  тестируемый helper `lore_story_override(tool_ctx, l1_plan, response_plan)`;
  call-site гейтован (REGRESSION-пин тестом на исходник).
- Kill-switch `LORE_STORY_INTENT_GATE_ENABLED` (env-only ClassVar, default ON;
  OFF → прежнее поведение байт-в-байт) — прецедент `SYSTEM2_DIRECT_ENABLED`.

**Сохранено**: `compile_lore_story`, `dig_into_lore`, fallback/legacy,
`LORE_STORY_SYSTEM_PROMPT` (байт-канон не тронут — тест
`test_lore_compiler_round1020` зелёный), numeric-гард, freshness-guard.
`compile_lore_story` schema description НЕ менялась (дословная EN-строка ТЗ
байт-пиннута двумя тестами; корневой фикс — гейт доставки, аудит G1b помечал
его опциональным).

## Дефект 2 — Многолетний период невыразим (audit §9.2)

**Было**: план без периода; `time_range` enum без годов; dig `year` — один
календарный год; «N лет назад» — одиночный год.

**Стало (аддитивно, без второго роутера и новых тулов)**:
- `query_chat_memory`: опциональные `year_from`/`year_to` (годы) +
  top-level `author`. SQL-слой уже принимал `since_ts/until_ts/author_ids`
  (MCA-15 D1) — фасад `search_long_term`/`count_mentions` теперь
  прокидывает их (`services/summary_memory.py`); новые kwargs передаются
  ТОЛЬКО при заданном фильтре (дефолтный вызов байт-в-байт, строгие
  сигнатуры заглушек не ломаются).
- `dig_into_lore`: опциональный `year_to` → bounds `[year..year_to]`.
- stats-режим: `year_from/year_to` → `StatsQuery.interval_to` (SQL);
  `author` принимает Telegram uid и «me».
- Инвалидный явный период (вне [2000, текущий] / `year_to < year_from`) →
  честный JSON `unsupported/invalid_period` — окно не исчезает молча.

## Дефект 3 — Покрытие/свежесть выборки (audit §9.3)

**Было**: top-40 по rank с пост-фильтром окна ПОСЛЕ LIMIT
(`tool_router.py:766-780`, `1022-1031`); `lore_dense_dialogs` сканировал
строго первые 300 ASC (`database.py:8587-8588`); покрытие показа не
сообщалось.

**Стало**:
- Фильтры окна/автора — В SQL ДО LIMIT (фасад, см. дефект 2); пост-фильтры
  в цикле сохранены как страховка для memory-заглушек.
- `lore_dense_dialogs`: при `total > max_scan` — стрйд-сэмпл по всему
  периоду (`ROW_NUMBER() % stride`, stride = ceil(total/max_scan) по точному
  COUNT); `total <= max_scan` → прежний полный ASC байт-в-байт; ошибка
  window-функции → fail-open на легаси ASC-скан.
- Честное покрытие модели (данные, не технический дамп):
  - `query_chat_memory`: «Показано X из N сообщений (верх по релевантности)…»
    при count > shown; human-метка периода (year_from/year_to) в заголовке.
  - dig JSON: блок `coverage {messages_total, messages_shown, facts_shown,
    sampling}` в обоих (K1 ON/OFF) контрактах.

## Дефект 4 — «Сообщения человека» без надёжного субъекта (audit §9.4)

**Было**: `_dig_person_terms` брал ПЕРВОЕ совпадение алиаса (дубликаты имён
не видны); без мэтча фильтр автора тихо исчезал, имя становилось OR-токеном
— «о человеке» выдавалось за «от человека».

**Стало**: единый резолвер `_resolve_person_identity` для `author`/`person`
всех трёх контуров (query_chat_memory normal, stats, dig):
1. Telegram uid: «123», «id:123», «user:123» → int uid;
2. «me»/«self»/«я» → uid говорящего (`ctx.user_id`; нет → честный
   `caller_unknown`);
3. алиас/имя — set-семантика `_resolve_author_id` (ровно один мэтч; >1 →
   `author_ambiguous`; похожие ники НЕ сливаются).
Ненайденный/неоднозначный субъект → честный JSON-отказ
(`author_unresolved`/`author_ambiguous`/`caller_unknown`, словарь reasons —
существующий stats-контракт), поиск без фильтра НЕ выполняется. При резолве
по uid каноническое имя добавляется в name-формы для facts/target_user.
`_dig_person_terms` удалена (заменена). Поиск по упоминаниям без person не
изменён.

## Дефект 5 — L2-пересказы как независимые свидетельства (audit §9.5)

**Было**: dig facts рендерил beliefs и прямые факты одним kind="fact" без
origin; vector/RAG fallback вставлял производные факты как обычные строки.

**Стало** (reuse существующих origin-данных SELECT'а + канон рендера):
- dig facts: метка происхождения на каждой строке — `[пересказ из чата]`,
  `[вывод бота]`, `[запомнено]`, `[из статьи]` и т.д.
  (`_DIG_FACT_ORIGIN_LABELS`; неизвестный origin — сам origin; пустой —
  `[память]`); `status=archived_belief` → суффикс «(архивное убеждение)».
- `query_chat_memory` fallback: vector/RAG — отдельный блок с заголовком
  «Контекст из памяти (обобщённые факты и пересказ, не дословные
  сообщения):»; при заданном author эти каналы НЕ вызываются (не умеют
  фильтровать по автору — честно, без смешивания).
- Сниппеты kind="msg" — прямые цитаты корпуса, без меток пересказа
  (различение прямое/производное в payload сохранено).

## §8 — применимость LORE_STORY_SYSTEM_PROMPT

Канон применяется только в синтезе истории (`lore_compiler_service.py:208`,
AST-тест). С гейтом дефекта 1 анализ реального прошлого больше не получает
драматургический канон: анализ-планы отвечают Writer'ом. Творческие
возможности Lore не подавлены (story-интенции доставляются как раньше).

## Сценарная матрица §12 (payload-level, БЕЗ речевого эталона)

`tests/test_p0_delta_routing.py::TestScenarioMatrixNoTemplate`:
8 интентов владельца (свободное рассуждение / факт / анализ человека /
изменения за период / мем-история / отношения / точная статистика /
творческий) — для каждого L1-JSON → `normalize_l1_plan` → `task_kind` +
`response_mode` + lore-гейт. Проверено: ≥4 различных task_kind; «analysis/
анализ» канонизируются в research (без второго роутера); разговорная
интерпретация отношений не принуждается к архиву (tool_policy=none);
extent/длина НЕ являются сигналом маршрутизации (one_word и longform дают
одинаковые решения гейта); новых обязательных композиционных констант нет.

## Верификация

- `py -3 -m compileall services config tests` → exit 0.
- `tools/gen_param_registry_round1025.py --check` → CHECK OK (582 == REGISTRY;
  флаг env-only ClassVar, Δ каталога = 0).
- Новые тесты: `tests/test_p0_delta_routing.py` — 54 (все дефекты + матрица).
- Обновлены (осознанно, под новый контракт): `test_tool_router.py` —
  рендер факта с origin-меткой; person в graph-expansion тестах резолвится
  алиасом (+ пины SQL-kwargs).
- Сфокусированные наборы: 496 passed (tool_router, summary_memory,
  tool_schemas, mca15 stats, lore_compiler, memory_lookup, asap7 L1, L1D,
  two_call, agentic, factcheck_tools).
- Полный suite кандидата vs база `87ad5908`: наборы падений ИДЕНТИЧНЫ
  (env-флейки миграций/UI-байт-тестов; 1 сетевой флейк betterstack проходит
  standalone дважды; на базе, наоборот, флэйкнули 2 теста, зелёные на
  кандидате). Новых падений от изменения нет.

## Честные пробелы (вне этой полосы)

- LIVE-проба 10 реальных сценариев §12 на проде (маршрутизация tool-модели,
  поведение L2 Writer с lore-as-material) — DevOps/next step; здесь только
  payload/unit-уровень.
- EN-описание `compile_lore_story` оставлено дословным по ТЗ (байт-пин);
  поведение анализа защищает гейт доставки.
- `after_id`/`max_id` watermark stats в схему инструмента не проброшен
  (вне списка дефектов этого lane).
