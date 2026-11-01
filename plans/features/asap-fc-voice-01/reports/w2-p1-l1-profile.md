# W2 / P1 — общесистемный L1 decision-profile (ASAP-FC-VOICE-01 / B)

- Дата: 2026-11-02. Ветка `feat/fc-voice-p1-l1-profile`, база `2317d26f`
  (включает ER-08-RC и байты deployed 2.58.148).
- Контракт: `plans/features/asap-fc-voice-01/arch/l1-decision-profile-contract.md`
  (авторитетный), источник: `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md` §5.
- Область: Direct L1 и Initiative L1 — единственные публичные decision-планеры
  с характером. Speech/Core/Expression, Evidence Routing, Social Context,
  фоновые Summary/Sleep/Memory не менялись.

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
читают ОДИН кадр (`current_run_frame`) и один builder, поэтому блок байт-идентичен;
повторного снапшота и модульного кеша нет — следующий ход читает новый кадр.

Провенанс в существующей трассе: `meta["l1_profile_source"]` (`frame`/`legacy`) и
`l1_profile_chars` уходят в `record_l1_diagnostics` (Inspector, R17-safe: без
текста профиля); в самом payload провенанс виден строкой `источник: кадр
поведения <version>`.

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
  (changed = 1, только `direct.base.l1_planner`);
- `prompt_migrations`: ступень вперёд `(PREV_..._EVR2 → активные)`, откат
  `(активные → PREV_..._EVR2)` первым шагом, прежний стек цел (ADR-1013-3);
- миграция срабатывает ТОЛЬКО на точное совпадение байт: кастомы владельца не
  перезаписываются (проверено тестом на «байты + мой хвост»).

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

Новый файл `tests/test_asap_fc_voice_l1_decision_profile.py` (12 тестов,
`CONTRACT`): детерминизм профиля, закрытый набор измерений и отсутствие
выдуманных чисел, отсутствие речевых директив/примеров/уровней мата, честный
`кадр недоступен` и legacy-имена, секция в payload вместо прозы `<Persona>`,
выживание профиля под сжатием на живом бюджете (1600/400/150), реальный вызов
`_plan_direct_l1` с провенансом в трассе, байт-идентичность профиля у Initiative
и сохранность критериев silence, смена профиля следующим кадром без stale-кеша,
негатив фона, ревизия канона и её откат на deployed-байты.

Mutation-проверки (каждая — красный прогон, затем возврат):

| Мутация | Красный тест |
|---|---|
| убрать `decision_profile=` в `_plan_direct_l1` | `test_direct_service_l1_payload_gets_profile_from_turn_frame` |
| убрать `L1_PROFILE_SECTION` из `protected` | `test_profile_survives_budget_compression_at_live_budget` |
| снять правило EVR3 из канона | `test_canon_revision_keeps_deployed_bytes_as_rollback_target`, `test_migration_and_rollback_only_match_exact_deployed_bytes`, `test_initiative_payload_gets_same_profile_bytes` |
| убрать `decision_profile=` у Initiative | `test_initiative_payload_gets_same_profile_bytes` |

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
