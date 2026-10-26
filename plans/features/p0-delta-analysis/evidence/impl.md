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

## EXTENT-NO-WORDS micro-fix (26.10.2026, review-находка REQ-DELTA-02-NO-WORD-HARDCODE)

**Дефект**: legacy 0-LLM fallback-классификатор
`services/response_extent.classify_request` ветвился по литеральным словам
запроса («проанализируй», «почему», «скачай», «фанфик», …) — 12 словесных
regex-триггеров категорий (_EXPLAIN/_COMPARE/_RESEARCH/_CREATIVE/_SUMMARY/
_STEPS/_NOSTALGIA/_MEDIA_DL/_MEDIA_GEN/_TRANSCRIBE/_YESNO/_EXTENT_OF_TASK)
нарушали REQ-DELTA-02-NO-WORD-HARDCODE (карта p0-delta-analysis, M00032:
«в коде маршрутизации нет ветвлений по словам …; поиск по коду подтверждает
отсутствие таких литералов в решающей логике»).

**Стало**: fallback semantic-neutral — только структурные сигналы сообщения:
пустой текст → дефолт social_chat/compact/chat; короткий вопрос (≤3 слов,
«?») → micro/direct_answer (§8 fast path, прежнее поведение). Semantic-класс
задачи назначает L1 Planner; явная форма длины пользователя доезжает через
`explicit_form_override` поверх L1-плана (§2.5, primary path не тронут —
regex'ы явных форм и multi-read §17 в модуле сохранены для
`explicit_form_override`/`build_tool_plan`).

**Не тронуто**: L1-driven путь, `build_tool_plan`, `explicit_form_override`,
extent-блоки/scrub, `CLARIFY_MEDIA_TARGET` (функция план-дривен и жива в
L1-пути через планы L1: сервисный вызов direct_chat_service:3834 получает
L1-производный план).

**Осознанные behavioral deltas (fallback/legacy-only, L1-путь без изменений)**:
- L1-outage: маркерные слова больше не придают fallback-плану
  research/explanation/report-структуру → `lore_story_delivery_allowed`
  возвращается к своему задокументированному контракту fail-open для
  fallback-планов (докстринг гейта: «интенция полями плана не определена … →
  True»; словесная утечка структуры была недокументированным side-effect);
  защита дефекта 1 в healthy-пути (semantic L1-план) без изменений.
- L1-outage/legacy: «коротко/подробно» в запросе больше не перекраивают
  extent fallback-плана (нейтральный compact; в L1-пути явная форма
  применяется `apply_form_override` поверх outage-fallback — проверено
  test_asap7_direct_l1::test_form_override_semantics).
- Legacy (DIRECT_L1_ENABLED=false): media-слова («скачай» без цели) больше не
  рождают fixed §20-clarify — ход идёт обычным tool-путём (ASAP 7 §1.9 уже
  демотировал fixed-фразу; в L1-пути уточнение решает L1 семантически);
  media-план с URL/реплаем доставляется как раньше (URL — структурный сигнал,
  тул-модель не менялась). `clarification_question`/`media_writer_needed`
  остаются план-дривен контрактами (пины переведены на явные планы).
- Coordinator-метаданные при plan=None — нейтральные (внутренний trace, R17
  без текста).

**Тесты**: source-scan по телу `classify_request` (прецедент
test_speech_p0_corrective_l1_route.py): 51 запрещённый литерал + запрет
ссылок на словесные regex-константы в теле (TestFallbackNoWordHardcode);
word-пины §44 переведены на semantic-neutral контракт
(test_mca23_response_plan), clarification/media/planned-граф пины — на
явные планы (test_mca23_phase2, test_mca23_planned_vs_actual), legacy §20 —
на обычный tool-путь (test_tool_calling_round1015), coordinator-оси — на
нейтральные (test_mca23_response_plan::TestCoordinatorDecisionPlan).

**Верификация**: фокусный набор `-k "extent or response_plan or direct_l1"`
— база `2ac20bf3`: 151 passed / 0 failed; кандидат: 152 passed / 0 failed
(+1 net: +2 source-scan, +2 word-routing, -3 снятых словесных golden);
direct-chat шов (27 файлов, legacy+L1): база 1109 passed / 0 failed,
кандидат 1110 passed / 0 failed — все расхождения тестов объяснены
переводом word-пинов, collateral-падений нет. `py -3 -m compileall services`
— OK. Прод/SSH/Telegram/LLM не трогались.

## LORE-VERBATIM-GATE micro-fix (27.10.2026, live-находка D1, §Находка live-scenarios)

**Дефект**: гейт подмены `lore_story_delivery_allowed` корректно блокировал
доставку готовой lore-истории на analysis-ходах (`lore_story_override`), но
служебная инструкция `_LORE_RETURN_INSTRUCTION` («верни story ДОСЛОВНО»;
добавляется в tool-payload `compile_lore_story` при
`ctx.lore_verbatim_instruction=True` — дефолт ToolContext) всё ещё попадала
в payload на ЛЮБОМ интенте. Writer видел инструкцию и эхом возвращал
скомпилированную историю на research/summary-сценариях (S03 период, S05
мета-эссе, S07 отношения двух людей, S10 вне-период; live prod 2.58.132) —
D1 «lore story не подменяет analysis-ответ» не выполнялся фактически.

**До/После (payload)**:
- До (baseline 2ef0615a, RED-probe `lore_verbatim_red_probe.py`):
  analysis-план research/report → gate_delivery_allowed=False,
  ctx.lore_verbatim_instruction=True (дефолт) → verbatim_in_payload=True
  (`[СИСТЕМНАЯ ИНСТРУКЦИЯ: верни пользователю текст из поля "story"
  ДОСЛОВНО …]` в конце тул-результата).
- После: инструкция в payload ⇔ доставка разрешена тем же гейтом —
  `lore_verbatim_allowed(l1_plan, response_plan)` (новый хелпер):
  kill-switch `LORE_STORY_INTENT_GATE_ENABLED` OFF → True (легаси-поведение),
  иначе `direct_l1.lore_story_delivery_allowed`. При гейте False payload без
  инструкции; история остаётся provenance-материалом тул-результата
  (`"story"`-поле/метки происхождения не тронуты), ответ компонует Writer
  по плану.

**Изменения** (2 файла, +218/-3 строк суммарно с тестами):
- `services/direct_chat_service.py`: модульный хелпер
  `lore_verbatim_allowed` (после `lore_story_override`, та же семантика
  гейта + kill-switch, never-throws) и единственная tool-loop точка —
  construction ToolContext в `_handle_turn` теперь передаёт
  `lore_verbatim_instruction=lore_verbatim_allowed(l1_plan, response_plan)`
  (прецедент S10.20-4: caller, знающий интент, прокидывает значение — в
  фактчеке False).
- `tests/test_p0_delta_routing.py`: класс `TestLoreVerbatimInstructionGate`
  (+12 тестов, CONTRACT/REGRESSION): iff-матрица (verbatim ⇔ delivery),
  легаси task_kind-гейт, fail-open без плана, kill-switch OFF → легаси,
  source-пин wiring в call-site; четыре живых сценария S03/S05/S07/S10 как
  payload-юниты (реальный dispatch compile_lore_story: БД in-memory +
  фейк-LLM синтеза, конструкция ctx ровно как в call-site) + легаси-S05
  вариант + story-контролы S04/S09 (инструкция на месте — genuine
  story-доставка не сужена).

**Не тронуто**: `compile_lore_story` и `dig_into_lore` (`tool_router.py` —
0 строк), `lore_story_override`, дефолт
`ToolContext.lore_verbatim_instruction=True` (другие вызовы/легаси-пути),
creative/historical_recall пути (S04/S09), фактчек (уже False, S10.20-4).

**Верификация** (кандидат vs база 2ef0615a):
- `pytest tests/test_p0_delta_routing.py tests/test_tool_router.py -q`:
  база 99 passed / 0 failed → кандидат 111 passed / 0 failed (+12 новых,
  collateral 0).
- `pytest tests -k "delta or lore or tool_router" -q --ignore=…vision_ui_e2e`:
  база 527 passed → кандидат 539 passed / 0 failed.
- `py -3 -m compileall services` — OK.
- Direct-шов `-k "direct"`: 870 passed / 7 failed — все 7 воспроизводятся
  на ЧИСТОМ 2ef0615a без правок (test_asap7_direct_settings ×2,
  test_direct_fallback_recompose_asap32 ×5; проверено stash-прогоном),
  pre-existing, к micro-fix не относятся — дельта дефектов = 0.
- Прод/SSH/Telegram/LLM не трогались.
