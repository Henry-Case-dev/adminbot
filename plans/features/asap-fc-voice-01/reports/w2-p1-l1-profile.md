# W2 / P1 — общесистемный L1 decision-profile (ASAP-FC-VOICE-01 / B)

- Дата: 2026-11-02. Ветка `feat/fc-voice-p1-l1-profile`, база `2317d26f`
  (включает ER-08-RC и байты deployed 2.58.148).
- Контракт: `plans/features/asap-fc-voice-01/arch/l1-decision-profile-contract.md`
  (авторитетный), источник: `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md` §5.
- Область: Direct L1 и Initiative L1 — единственные публичные decision-планеры
  с характером. Speech/Core/Expression, Evidence Routing, Social Context,
  фоновые Summary/Sleep/Memory не менялись.

## 0. Правки по ревью W2/P1 (Needs Fixes → исправлено)

### F1 (blocker) — кадр больше не ambient, а пин ЭТОГО хода/чата

Что было: `build_decision_profile_block` читал `mca_self_model.current_run_frame()`
— ambient `ContextVar`, который `set_run_frame` ставит, но НИКТО не сбрасывает.
Инициативный цикл обходит несколько чатов; при `persona_enabled=False` или сбое
резолва (`resolve_character_context` внутри try/except) пин оставался от
предыдущего чата, и планер получал чужой характер. Ревьюер воспроизвёл: чат 222
получал `frame_version`, `инициативность: 0.90`, `сарказм: 0.80` и пометку
`(в этом чате)` чата 111 — нарушение §7 п.21 владельца.

Как теперь (две независимые защиты, без нового движка/кеша):

1. **Граница хода.** `bot_persona.reset_turn_frame()` → существующий
   `mca_self_model.clear_run_frame()` вызывается ОДИН раз в начале хода:
   Direct — до резолва характера (`handle`, перед `if persona_enabled:`),
   Initiative — в начале `plan_initiative_decision`, до `_initiative_character`.
2. **Проверка владельца.** Новая `mca_self_model.current_run_frame_pin()` отдаёт
   пин ЦЕЛИКОМ (`frame` + `chat_id` хода). `bot_persona._pinned_frame_for_turn(
   ctx, chat_id)` принимает кадр только при совпадении всех условий:
   `ctx.frame_version` непустой (кадр резолвился в ЭТОМ ходе) · пин существует ·
   `RunFrame.chat_id == chat_id` вызова · версия пиннутого кадра == версия из
   `ctx`. Иначе — честный `legacy`/`absent`.
3. Оба call site передают `chat_id` хода: `_plan_direct_l1(..., chat_id=chat_id)`
   и `plan_initiative_decision(..., chat_id=chat_id)`.
4. Резолв характера инициативы дополнительно обёрнут в fail-open: исключение
   даёт `("", None)`, а не падение хода и не наследование чужого кадра.

Воспроизведение ревьюера теперь закрыто тестом
`test_initiative_of_chat_b_never_receives_chat_a_values`: сначала пин чата 111
(кадр с `инициативность 0.90`, `сарказм 0.80`, version `111…`), затем ход
инициативы чата 222 в двух деградированных вариантах — `persona_enabled=False`
и сбой резолва. В payload чата 222: `источник: кадр поведения недоступен`, нет
ни `0.90`, ни `0.80`, ни version, ни пометки `(в этом чате)`.

### F2 (blocker) — провенанс больше не врёт в деградированном случае

Было: `decision_profile_source` искал ПОДСТРОКУ `источник: кадр поведения`, а
legacy-строка «источник: кадр поведения недоступен» содержит её целиком → трасса
писала `frame` для legacy-блока. Стало: сравнение ЦЕЛОЙ строки
`источник:` (структурный маркер); неизвестный/пустой блок → `legacy` (право
называться `frame` нужно доказать). Тесты: `test_decision_profile_source_is_
structural_not_substring` (обе ветви + пустой блок) и
`test_profile_absent_is_honest_and_not_invented` (legacy → `legacy`).

### F3 (docs) — описан реальный механизм активации/откат

`§2.5` переписан: активация — метка+печать через
`prompt_release_policy.apply_release` (вызов из `bot.py:1383-1384` через
делегатор `migrate_prompt_canons`), активация возможна ПОВЕРХ ручной правки
(EVOL-012), откат — `activate_revision` (журнал). `PROMPT_MIGRATIONS`/
`ROLLBACK_MIGRATIONS` на старте не исполняются (`rollback_prompt_canons` —
намеренный ERROR), поэтому соответствующие тесты помечены как проверяющие
мёртвый на старте код, а не механизм релиза.

## 1. Что было сломано (причина по коду)

`bot_persona.build_persona_prompt_block` рендерит Writer-прозу
`<Persona>\nИмя…\nБиография…\nХарактер…\n</Persona>`. Планер получал эту прозу
головным срезом `[:L1_PERSONA_FRAME_CHARS]` (400 символов,
`direct_l1.py:857,1493-1495`), то есть обычно имя и начало биографии:
поведенческих фактов (инициативность, краткость, склонность спорить, уместность
сарказма) в пакете не было вовсе. Хуже: секция `[ХАРАКТЕР (кадр)]` стояла
последней и **не входила** в `protected`-набор `_cap_context`, поэтому при
переполнении бюджета её первой сжимал шаг 2 и могла удалить шаг 4 — характер
исчезал именно в трудных ходах. Канон L1 при этом ни разу не объяснял, что это
за секция: модель получала данные без статуса.

## 2. Что сделано

### 2.1 Одна точка сборки: `bot_persona.build_decision_profile_block`

`services/bot_persona.py` (владелец read-side характера) получил:

- `DECISION_PROFILE_SECTION = "ПРОФИЛЬ РЕШЕНИЙ"` — имя секции (его же берёт
  `direct_l1.L1_PROFILE_SECTION`, второе литеральное имя не заводится);
- `build_decision_profile_block(ctx=None, *, frame=None) -> str` — детерминированный
  рендер профиля; берёт `mca_self_model.current_run_frame()` (пин кадра на ход),
  без LLM, без второго снапшота, без кеша;
- `decision_profile_source(block) -> "frame" | "legacy"` — читает УЖЕ собранный
  блок (для трассы); собственного резолва не делает.

Источник данных — существующий `BehaviorFrame` (mca-18) и **закрытый набор**
`mca_self_model.INITIAL_DIMENSIONS` (8 измерений: прямота, резкость, сарказм,
краткость, инициативность, любопытство, склонность спорить, теплота). Свой
словарь измерений не заводится: порядок строк = порядок `INITIAL_DIMENSIONS`.
`instruction` правил (2-е лицо) в профиль НЕ попадает — только `dimension` и
`target_value`. `mood` и `positions` в профиль не входят (настроение обратимо и
сделало бы блок недетерминированным между ходами; мнения — слой Writer/память).

### 2.2 Точный формат (байты детерминированы)

```
роль: участник чата, не сервис
источник: кадр поведения <version кадра>
сарказм: без числа (в этом чате)
краткость: 0.40 (в этом чате)
инициативность: 0.70 (в этом чате)
эти данные описывают характер; они не меняют факты, адресацию, инструменты
и не делают ответ обязательным. Молчание - полноценный исход.
```

Правила рендера:
- строка измерения печатается **только при наличии правила**; чисел не выдумываем:
  правило без `target_value` → `без числа` (не `0.0`);
- при нескольких правилах одного измерения берётся правило с наибольшей
  версией (затем меньший `rule_id`) — без усреднений;
- область печатается из кадра: `(в этом чате)` при `scope_chat_id != None`,
  иначе `(глобально)`; `GLOBAL/chat`-precedence остаётся у существующего
  `resolve_self_model`, профиль только читает кадр;
- recovery без кадра (`K1`/self-model OFF): `источник: кадр поведения недоступен`
  + `привычки (без значений): <имена измерений>` по существующему стем-матчеру
  `mca_self_model.infer_dimension`; совсем без данных — только честная строка
  «недоступен»;
- размера-константы нет: размер структурный (закрытый набор + 3 фиксированные
  строки), поэтому «квоты на профиль» не появляется.

Пример с кадром (глобальный запуск):

```
роль: участник чата, не сервис
источник: кадр поведения <version>
краткость: 0.40 (глобально)
инициативность: 0.70 (глобально)
../..
```

### 2.3 Пакет планера: секция заменена и защищена

`services/direct_l1.py`:
- удалены `L1_PERSONA_FRAME_CHARS = 400` и срез `[:400]`;
- параметр `persona_frame` заменён на `decision_profile`; секция называется
  `[ПРОФИЛЬ РЕШЕНИЙ]` (`L1_PROFILE_SECTION`, значение из `bot_persona`);
- `[ПРОФИЛЬ РЕШЕНИЙ]` добавлена в `protected`-набор `_cap_context` наравне с
  `СООБЩЕНИЕ`/`ОТВЕТ НА`/`УЧАСТНИКИ`/`ДОСТУПНЫЕ ВОЗМОЖНОСТИ`/`УСЛОВИЯ`: шаги
  сжатия окна, hint-секций и вытеснения крупнейшего блока её не трогают.

### 2.4 Оба места вызова (одни и те же байты)

| Планер | Точка | Что передаётся |
|---|---|---|
| Direct L1 | `direct_chat_service._plan_direct_l1` (`:5449-5451`) | `decision_profile=_decision_profile` — из кадра хода (`character_ctx`) |
| Initiative L1 | `direct_chat_service.plan_initiative_decision` (`:11980`) | `decision_profile=_init_profile` — из того же кадра |

`_initiative_persona_block` разделён на `_initiative_character(chat_id) ->
(проза Writer'а, ctx)`; сам `_initiative_persona_block` оставлен как обёртка
(Writer-путь и существующие стенды не ломаются). Для одного chat/хода оба сайта
берут ОДИН кадр (`current_run_frame`) и один builder, поэтому блок байт-идентичен;
повторного снапшота и модульного кеша нет — следующий ход читает новый кадр.

**Изоляция хода/чата (правка ревью F1).** Ambient-кадр (`ContextVar`) переживает
ход, а инициативный цикл обходит несколько чатов, поэтому одного
`current_run_frame()` недостаточно. Теперь две независимые защиты:

1. `bot_persona.reset_turn_frame()` вызывается ОДИН раз в начале хода (Direct —
   до резолва характера, Initiative — в начале `plan_initiative_decision`) и
   снимает пин предыдущего хода/чата (`mca_self_model.clear_run_frame()`);
2. `_pinned_frame_for_turn(ctx, chat_id)` принимает кадр только при ОДНОВРЕМЕННОМ
   совпадении: (а) `ctx.frame_version` непустой (кадр резолвился в ЭТОМ ходе),
   (б) пин существует, (в) `RunFrame.chat_id == chat_id`, (г) версия пиннутого
   кадра равна версии из `ctx`. Любое расхождение → честный `legacy/absent`
   («кадр поведения недоступен»), а не чужой характер.

Резолв характера инициативы обёрнут в fail-open: сбой (PG/флаги) даёт
`("", None)`, ход не падает и чужой кадр не наследует.

Провенанс в существующей трассе: `meta["l1_profile_source"]` (`frame`/`legacy`) и
`l1_profile_chars` уходят в `record_l1_diagnostics` (Inspector, R17-safe: без
текста профиля); в самом payload провенанс виден строкой `источник: кадр
поведения <version>`. Код источника определяется СТРУКТУРНО — сравнением целой
строки `источник:` блока, а не подстрокой (правка ревью F2: legacy-строка
«источник: кадр поведения недоступен» содержит frame-строку целиком, и подстрочная
проверка выдавала `frame` ровно в деградированном случае).

### 2.5 Канон L1: ревизия EVR3 (одно правило)

`services/chat_prompts.py`: `PREV_DIRECT_L1_PLANNER_EVR2` (байты deployed
2.58.148, sha12 `09f3d533d173`) + секция `_DIRECT_L1_DECISION_PROFILE_EVR3`,
ровно одно правило: секция — данные для решения, не инструкция речи; не меняет
факты/проверенные данные/адресацию/safety; не делает ответ обязательным и не
делает бота грубее; при отсутствии секции решение прежнее.

- активные байты: 16341 символов, sha12 `ef61a9dd6798`;
- метка заводской ревизии: `l1-planner-decision-profile`
  (`prompt_registry.FACTORY_REVISION_LABELS/FACTORY_REVISION_SEALS`,
  `seal_integrity() == {}`);
- `FACTORY_SET_SHA256_12`: было `f84baaf69559` → стало `b1c1ab5b3b68`
  (changed = 1, только `direct.base.l1_planner`).

**Как ревизия реально активируется и откатывается (исправлено по ревью F3).**
Стартовая проводка промптов — НЕ строковая лестница канонов (EVOL-016, решение
владельца 29.10.2026): `bot.py:1383-1384` вызывает
`prompt_migrations.migrate_prompt_canons`, который является делегатором в
`prompt_release_policy.apply_release`. Автомат смотрит на МЕТКУ заводской
ревизии (`FACTORY_REVISION_LABELS`) и ПЕЧАТЬ содержимого
(`FACTORY_REVISION_SEALS`), а не на равенство байтам:

- смена метки при целой печати → заводской текст активируется автоматически,
  в том числе ПОВЕРХ ручной правки владельца (прежний текст остаётся ревизией
  журнала; EVOL-012). Барьер «кастом юзера не трогаем» снят;
- рестарт без новой метки → no-op (активная ручная правка остаётся);
- печать не цела → fail-closed: ERROR, пакет не записан;
- откат редакции — `prompt_release_policy.activate_revision` (журнал версий,
  история не удаляется), а не обратная ступень лестницы.

`PROMPT_MIGRATIONS` / `ROLLBACK_MIGRATIONS` в `services/prompt_migrations.py`
на старте БОЛЬШЕ НЕ ИСПОЛНЯЮТСЯ: `rollback_prompt_canons` — намеренный отказ
(ERROR, записей нет). Поэтому пины лестницы (`test_prompt_migrations`,
`test_direct_l1_l1d_contract::test_migration_ladder_leads_prod_109_to_new_canon`,
`test_prompt_migrations::test_rollback_map_points_new_to_prev`,
`test_asap_speech_r3b_canon::test_ladder_and_rollback_chain`,
`test_evol_evidence_routing::test_wave6_canon_revision_seal_and_rollback_target`)
проверяют ИСТОРИЧЕСКИЕ карты соответствия — то есть мёртвый на старте код, а не
механизм релиза. Обновление ступени в этой правке сделано, чтобы историческая
карта не расходилась с активными байтами, но НЕ является активатором: активацию
решает метка+печать (`l1-planner-decision-profile` / `ef61a9dd6798`).

## 3. Фоновые стадии (негатив)

Ничего не добавлено в machine-стадии: `compose_machine_system` для
`summary.base.single`, `summary.base.editor`, `summary.base.narrator`,
`summary.base.l1_clusterizer`, `memory.extract`, `memory.compress`,
`internal.dream.distill`, `internal.dream.deep_sleep_bridge` по-прежнему даёт
`profile=machine_json`, слои `core/expression/few_shot/identity/humor_craft/
style_policy_hint` не рендерятся; в их байтах нет `<Expression_Settings>`,
`<Speech_Base>`, `<Few_Shot>`, `<Persona>` и `[ПРОФИЛЬ РЕШЕНИЙ]`. Транспортные
швы (`LLMClient._post`, `ToolRouter._execute_web_search`) под шпионом — ни одного
вызова при сборке этих стадий.

## 4. Тесты

Новый файл `tests/test_asap_fc_voice_l1_decision_profile.py` (**17 тестов**,
`CONTRACT`): детерминизм профиля, закрытый набор измерений и отсутствие
выдуманных чисел, отсутствие речевых директив/примеров/уровней мата, честный
`кадр недоступен` и legacy-имена, секция в payload вместо прозы `<Persona>`,
выживание профиля под сжатием на живом бюджете (1600/400/150), реальный вызов
`_plan_direct_l1` с провенансом в трассе, байт-идентичность профиля у Initiative
и сохранность критериев silence, смена профиля следующим кадром без stale-кеша,
негатив фона, ревизия канона и её откат на deployed-байты, **изоляция ходов и
чатов** (чат A 111 → чат B 222 при persona OFF и при сбое резолва: ни версии, ни
значений, ни пометки «(в этом чате)» чата A; отказ при чужом/устаревшем пине;
сброс пина на границе хода) и **структурный провенанс** (`frame`/`legacy`).

Mutation-проверки (каждая — красный прогон, затем возврат):

| Мутация | Красный тест |
|---|---|
| убрать `decision_profile=` в `_plan_direct_l1` | `test_direct_service_l1_payload_gets_profile_from_turn_frame` |
| убрать `L1_PROFILE_SECTION` из `protected` | `test_profile_survives_budget_compression_at_live_budget` |
| снять правило EVR3 из канона | `test_canon_revision_keeps_deployed_bytes_as_rollback_target`, `test_migration_and_rollback_only_match_exact_deployed_bytes`, `test_initiative_payload_gets_same_profile_bytes` |
| убрать `decision_profile=` у Initiative | `test_initiative_payload_gets_same_profile_bytes` |
| вернуть ambient-чтение кадра (F1) | `test_profile_does_not_reuse_a_pinned_frame_of_another_chat`, `test_profile_rejects_a_stale_pin_of_the_same_chat` |
| вернуть ambient-чтение И снять `reset_turn_frame` (состояние `1aa818c5`) | + `test_turn_reset_drops_the_previous_chat_frame`, `test_initiative_of_chat_b_never_receives_chat_a_values` (4 красных) |
| вернуть подстрочный провенанс (F2) | `test_decision_profile_source_is_structural_not_substring`, `test_profile_absent_is_honest_and_not_invented`, `test_profile_does_not_reuse_a_pinned_frame_of_another_chat` |

### Прогоны

- новый контрактный набор: **17 passed**;
- целевой набор L1/канон/миграции/реестр (26 файлов, включая
  `test_asap7_direct_l1`, `test_direct_l1_*`, `test_er08_limits_context`,
  `test_soul1_machine_profile_no_core`, `test_soul1_composer_parity_off`,
  `test_prompt_migrations`, `test_post_asap5_*`, `test_asap_speech_*`,
  `test_evol_*`, `test_p0_prompts_core`): **423 passed** (до правок ревью) и
  **247 passed** на затронутом подмножестве после них;
- полный `pytest tests`: **17461 passed, 65 failed, 23 errors (20:56)**.
  Те же 88 узлов, прогнанные по отдельности на этой ветке и на базовом коммите
  `2317d26f` (чистый worktree через `git worktree add`), дают ОДИН И ТОТ ЖЕ
  набор: 36 failed + 19 errors, списки совпадают побайтно (`Compare-Object` —
  пусто). То есть падения предсуществующие (окружение/порядок: summary,
  youtube-download, webapp/Node, outgoing-guard, чат-ключи без PG/сети) и
  правкой не вызваны.
- `tools/er65_prompt_segment_snapshot.py --check`: OK.

Примечание по гигиене: полный прогон перезаписывает `plans/features/evol/audit/
evidence/*` (скриншоты/json UI-e2e). Эти файлы восстановлены байт-в-байт из
HEAD и в коммиты не попали.

Обновлены пины, которые законно сдвинулись от правки канона/пакета:
`test_p0_prompts_core`, `test_expression_isolation_followup`,
`test_post_asap5_w1_writer_core`, `test_post_asap5_w2_tech_reasoning`,
`test_speech_p0_corrective_l1_route`, `test_asap_speech_r3b_canon`,
`test_evol_w17_small_canon_reqs`, `test_evol_evidence_routing`,
`test_prompt_migrations`, `test_direct_l1_corrective_r1`,
`test_direct_l1_l1d_contract`, `test_er08_limits_context` (филлер `persona_frame`
стал защищённой секцией → давление создаёт hint-секция),
`test_soul1_composer_parity_off` (эталон P4: секция характера заменяется
детерминированно текущим профилем), `test_asap_speech_i_matrix` (шов
`_initiative_character`).

## 5. ER-65 снимок

`tools/er65_prompt_segment_snapshot.py`: в `SOURCE_FILES` добавлен
`services/bot_persona.py` (его байты теперь определяют user-payload L1), кандидат
слоя переименован `l1_context_persona_frame` → `l1_context_decision_profile`
(значение пустое, на байты снимка не влияет).

Перегенерировано: `plans/features/evol/evidence/er65/sent-segments.json` +
`sent-segments.md`. `--check` — ЗЕЛЁНЫЙ («снимок воспроизводится байт-в-байт,
stages=27, segments=58, two isolated processes identical»); summary 27 стадий /
58 сегментов / 229879 символов (было 225435).

**После правок ревью F1/F2 снимок перегенерирован ещё раз: 0 сегментов
сообщений изменено** (58/58 совпадают, chars/sha те же), поменялись только
digests провенанса `services/bot_persona.py` и `services/direct_chat_service.py`
— то есть поведение payload'а не изменилось, изменился только документируемый
код. `--check` зелёный.

Какие сегменты реально поменялись (сравнение с прежним артефактом; 4 стадии,
8 сегментов, все — планеры L1):

| Стадия | Сегмент | Было | Стало |
|---|---|---|---|
| `direct.l1_planner` (prod_on) | system / user | 15453 `09f3d533d173` / 679 | 16341 `ef61a9dd6798` / 902 |
| `direct.l1_planner` (factory_off) | system / user | 15453 / 679 | 16341 / 902 |
| `direct.l1_planner.tools` | system / user | 15453 / 679 | 16341 / 902 |
| `initiative.l1_planner` | system / user | 15453 / 1199 | 16341 / 1422 |

Сегменты фактчека, System2, тулов, Writer'ов и фоновых стадий не менялись.

Отдельно, ДО этой правки существовавший дрейф (проверено дважды: в моём
worktree до любых изменений и в чистом worktree на базовом коммите `2317d26f`):
`--check` там КРАСНЫЙ —
`direct.l2_writer.fallback_model_capacity`, user-сегмент 709 (артефакт) → 745
(фактические байты базового кода). То есть предыдущий артефакт был устаревшим
по этому сегменту ещё до ASAP-FC-VOICE-01 (следствие ER-08-RC: снимок после него
не перегенерировали). В новом артефакте этот сегмент снова 709 — но при этом
стенд на текущей ветке режет блок плана на 36 символов раньше, чем базовый код
(system та же, 8037 симв.; меняется только позиция среза `Response_Plan`).
L2-код в этой правке не тронут, разница — внутри бюджетной арифметики самого
стенда; фиксирую как наблюдение для ER-08-RC/Reviewer, а не как изменение L2.

## 6. Что может доказать только живой прогон

- Реальное решение планера: профиль не делает L1 болтливее/токсичнее и не
  отменяет SILENT на поводе, который сам L1 считает умершим (в тестах проверена
  доставка данных и неизменность критериев/канона, но не вывод модели).
- Initiative в реальном чате: молчание при высокой инициативности/склонности
  спорить и неизменность `tone` на нейтральном вопросе при высоком сарказме.
- Фактические PG-значения кадра в проде (версии/области правил) и то, что
  `flags.persona_enabled`/`character_layers_enabled`/self-model включены так же,
  как в артефактах: стенд читает их из hot-кэша/кода.
- Фактический бюджет пакета конкретной модели на проде (`model_window`), а не
  только расчётные 1600/400/150.

## 7. Попутные наблюдения (не блокеры этой правки)

1. **ER-65 / L2 fallback (pre-existing).** На базовом `2317d26f` артефакт
   ER-65 уже расходился с кодом по `direct.l2_writer.fallback_model_capacity`
   (709 в артефакте против 745 в коде) — снимок после ER-08-RC не обновляли.
   Новый артефакт снова 709, но стенд на текущей ветке режет `Response_Plan` на
   36 символов раньше при идентичной system. Код L2 в этой правке не тронут;
   владелец вопроса — ER-08-RC/Reviewer.
2. **`_initiative_persona_block` → `_initiative_character`.** Резолв характера
   для инициативы теперь возвращает и ctx; старый метод сохранён обёрткой, но
   стенды, подменявшие именно `_initiative_persona_block` в решении L1, должны
   целиться в `_initiative_character` (один тест обновлён).
3. **Полный прогон не зелёный сам по себе** (65 failed / 23 errors) — это
   предсуществующее состояние окружения, подтверждённое сравнением с базой;
   к профилю решений отношения не имеет.
