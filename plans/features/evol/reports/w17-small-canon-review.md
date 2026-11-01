# W17: независимое ревью двух малых требований (ER-S25, ER-54)

Дата: 02.11.2026. Reviewer (независимая проверка).
Кандидат: ветка `feat/evol-small-reqs`, коммиты `e3d8ee6a` + `8e9f77cf` + `4062ac81`,
база `087c9a1c` (= содержимое прода 2.58.147 / `e18a86eb`; `git diff e18a86eb 087c9a1c`
по изменяемым файлам пуст, байты прода подтверждены). Рабочее дерево кандидата
чистое; деплоя и прода не касался.

## 1. Что проверено

* Карта: `ER-S25` (L02388, slice `EVOL-B-MEMCYCLES`, раздел 10, сценарий 25)
  и `ER-54` (L02245, slice `EVOL-SOCIAL-FRAME`, раздел 6); acceptance прочитан.
* `services/chat_prompts.py`: правила L1 (строки 1063-1079, в т.ч. правило 7),
  блок `_DIRECT_L1_TWO_PHASE_EVR2` (1353-1361), `PREV_DIRECT_L1_PLANNER_EVR1`.
* `services/factcheck_prompts.py`: `FACTCHECK_PHASE_SCOPE_*` (315-389), оба
  канона и слепки прод-байт.
* `services/evidence_policy.py`: `evaluate_evidence_need` (640-778),
  `guard_egress` (1121-1213), `drop_claim_sentence`, `is_attributed_speech`.
* `services/direct_chat_service.py`: сборка L1-payload (5327-5369, 11809-11811),
  `_evidence_supplied` (2486-2509), `_evidence_preflight` (5555+).
* `services/factcheck_service.py`: effective-путь обоих канонов (1478, 1543-1546),
  fallback 1505-1510.
* `services/prompt_registry.py` (метки/печати, `activation_plan` 700-736),
  `services/prompt_release_policy.py` (1197-1320, 1333-1379),
  `services/prompt_migrations.py` (1-11, 848-892).
* `plans/docs/canon/architecture.md` Section 72; новый тест-файл целиком.

## 2. Реализация: что подтверждено

### ER-S25

* L1-payload в проде собирается как `resolve_prompt("prompts.direct_l1_planner_system_prompt",
  DIRECT_L1_PLANNER_SYSTEM_PROMPT)`; блок двух фаз входит в результат (проверено
  прямым вызовом), composer - только observability (`emit_layer_events_once`,
  результат не подставляется в messages).
* Маркеры фаз - существующие поля: `response_act="summarization"` и
  `structure="summary"` входят в закрытые наборы (`RESPONSE_ACT_CANON`,
  `response_extent.STRUCTURES`), `external_claims` парсится
  `_parse_external_claims` по тем же ключам, что описаны в EVR1. Нового поля,
  сервиса, словаря или детектора нет.
* Политика evidence фазу проверки не глотает: на смешанном плане
  (`summarization` + `summary` + claims) с РЕАЛЬНЫМ конструктором
  `_evidence_supplied` (`transformed_only=True`) решение - `required=True`,
  `note="external_claims"`, 2 claim; чистый пересказ - `required=False`,
  `TEXT_TRANSFORM_OR_TRANSLATION`. Дополнительно проверено: `attributed_only`
  при наличии claims тоже не гасит проверку (правило 4 требует `not claims`).
* Egress: атрибутированная сводка не трогается, снимается только предложение
  фазы проверки (`one_lookup -> hint_retry -> drop`), остаток сводки совпадает
  с исходным текстом. Граница: неатрибутированная сводка с числовым claim
  может быть снята guard-ом, но канон как раз требует атрибуцию в фазе
  пересказа (остаточный риск соблюдения модели, не код).
* Исходная история: правка не добавляет ни одной записи в сообщения/историю;
  изменены только текст канона, реестр, лестница-метаданные и тесты.

**Блокер:** в эффективном payload для ровно этой просьбы остался неразрешённый
конфликт с правилом 7, см. раздел 5.

### ER-54

* Блок фаз в активном каноне Аналитика (`806d6cc6af77`) и в одиночном
  каноне (`d02776dec166`); оба уходят модели через `resolve_prompt`
  (строки 1543 и 1478), одиночный - с подстановкой `{max_symbols}` (1510).
* Нормативное ядро - один объект `FACTCHECK_PHASE_SCOPE_CORE`, входит в оба
  канона ровно один раз; блок = заголовок + ядро.
* Блока нет в `summary.base.single`, `summary.base.l2_writer`,
  `direct.base.l2_writer`, `direct.base.l1_planner` (проверено `factory_text`).
* Документ и код: Section 72 эталона байт-в-байт равен коду; пин был честным
  до правки (base-документ = `aa6a2ed38b4c` = base-код), после - `d02776dec166`.
* В канонах фактчека до правки слова "противореч*" не было (0 вхождений),
  новый блок ничему не противоречит; разбиение claim-единиц не сливает фазы,
  настоящее противоречие внутри одной фазы по-прежнему помечается.

## 3. Валидность тестов и мутации

15 тестов в `tests/test_evol_w17_small_canon_reqs.py`, все содержательные
(нет `assert True`, пустых тел, моков проверяемого шва). Прогон: 15 passed.
Смежные 18 файлов: 434 passed. 7 известных пре-существующих отказов
воспроизведены ровно как заявлено (2 в `test_samples_fewshot` / mca_expression,
5 в `test_direct_fallback_recompose_asap32`, файл не правился).

Мутации в отдельном scratch-worktree под `WorkspaceData/worktrees` (после
проверки удалён; рабочее дерево кандидата не менялось), набор из трёх файлов:
`test_evol_w17_small_canon_reqs.py`, `test_factcheck_prompts.py`,
`test_asap_speech_r3b_canon.py`.

| Мутация | Наблюдённый результат |
| --- | --- |
| baseline | 34 passed |
| A. убрать `FACTCHECK_PHASE_SCOPE_BLOCK` из одиночного канона | 10 failed: `test_byte_for_byte`, `test_er54_single_stage_rule_reaches_effective_payload`, `test_er54_both_stages_share_the_same_normative_core`, `test_er54_doc_block_and_code_canon_are_byte_identical`, `test_er54_phase_scope_reaches_factcheck_judge` (через `seal_integrity`), миграционные тесты, L1-пины |
| B. убрать `_DIRECT_L1_TWO_PHASE_EVR2` из L1 | 8 failed: `test_scenario25_canon_has_two_phase_contract`, `test_scenario25_migration_applies_only_to_deployed_bytes`, `test_l1_owner_contract_byte_intact`, пины метки/печати/отпечатка |
| C. один байт в Section 72 | 2 failed: `test_er54_doc_block_and_code_canon_are_byte_identical`, `test_byte_for_byte` |

Вывод: presence-тесты, пин "документ = код" и цепочка метка/печать/отпечаток
живые (падают при поломке). НО: при мутации B тесты
`test_scenario25_plan_keeps_phases_distinguishable`,
`test_scenario25_check_phase_reaches_runtime_policy`,
`test_scenario25_factcheck_phase_does_not_rewrite_summary` остаются зелёными:
они проверяют `normalize_l1_plan` / политику / guard, а не влияние канона на
план. Как unit-тесты швов они корректны, но не доказывают, что канон заставит
модель выбрать `summarization`; в карте это стоит писать именно так, иначе
таблица отчёта читается как доказательство связи канон-план.

## 4. Ревизии, печати, откат

* `sha12` совпадают с реестром: L1 `7637864d50b5`, Аналитик `806d6cc6af77`,
  одиночный `d02776dec166`; слепки `eb496e938c49` / `9573b3d86161` /
  `aa6a2ed38b4c` = байты прода 2.58.147; `seal_integrity() == {}`.
* `FACTORY_SET_SHA256_12 = 748641ded024` = пересчитанный
  `factory_set_fingerprint()`; промежуточный `63c0ae3546d1` действительно стоял
  на `e3d8ee6a` (changed=2: L1 + Аналитик), +1 - одиночный канон в `4062ac81`.
  Итог changed=3 в двух шагах, как в отчёте.
* Активация - по метке (`prompt_registry.activation_plan`): новая метка даёт
  `PLAN_ACTIVATE`, заводской текст становится активным даже поверх ручной
  правки; ручной текст остаётся неизменяемой ревизией журнала (проверено
  тестом и чтением `_apply_scope_release` / `_check_activation_drift`).
  Рестарт с той же меткой - no-op.
* Важно для формулировок: `PROMPT_MIGRATIONS` / `ROLLBACK_MIGRATIONS` с
  EVOL-016 стартом НЕ исполняются (`prompt_migrations.py` 1-11, 848-907;
  `rollback_prompt_canons` отказывает). Это метаданные и источник
  `known_canon_hashes`. Фактический откат - `activate_revision` по журналу;
  предыдущая заводская ревизия (байты 2.58.147) в журнале есть, поэтому откат
  на прод-байты достижим. Фраза "ступень привязана к точным байтам" верна для
  лестницы-метаданных, а "кастом не перетирается" - только про историю:
  эффективное значение владельца по действующей политике заменяется (сам отчёт
  это пишет, но таблица раздела 3 читается иначе).
* Отдельный шаг миграции для канона Аналитика не нужен: активация идёт по
  метке; добавленная запись корректна как known-canon/эталон. Пропуска нет.

## 5. Блокирующая находка

**BLOCKER / PROMPT_CONFLICT_UNRESOLVED (ER-S25).**
Требование: "Сделай саммари и проверь, кто прав" - фазы различимы; сводка без
вердиктов; проверка отдельно.
Где: `services/chat_prompts.py`, активный L1-канон: правило 7 (1069-1073) и
новый блок `_DIRECT_L1_TWO_PHASE_EVR2` (1353-1361).
Наблюдение: правило 7 прямо относит к `response_act=research` просьбу
"обобщить сообщения, переписку, историю" и добавляет "Материал важнее оценки:
если в конце добавлен вопрос-оценка, сперва разбор, а оценка - его вывод, не
замена". Это ровно формулировка сценария 25. Новый блок для той же просьбы
требует `response_act=summarization` + `structure=summary` и прямо запрещает
сливать фазы в один act. Оба текста активны, предложения о приоритете нет; в
карте конфликтов отчёта основание "правило 7 - про разбор без пересказа"
неверно: правило перечисляет обобщение переписки и истории.
Влияние: планировщик может по-прежнему вернуть `research` на "сделай саммари и
проверь, кто прав"; тогда маркер `summarization+summary` исчезает, Writer
получает "смысловой акт ответа: research", и разделение фаз - то, что требование
вводит - не гарантировано. Это не стиль: именно тот дефект, который ER-S25
закрывает, остаётся достижимым в эффективном payload.
Минимальная правка: одно предложение-приоритет в `_DIRECT_L1_TWO_PHASE_EVR2`
(например: "Если просьба содержит и пересказ/свод обсуждения, и разбор правоты,
план - response_act=summarization и structure=summary с external_claims;
правило 7 (разбор материала) в этом случае пересказ в research не превращает").
Правило 7 и owner-тексты не переписывать. Затем бамп печати L1 и
`FACTORY_SET_SHA256_12` (та же невыпущенная ревизия EVR2, как было с recheck)
и обновление пинов, где стоит `7637864d50b5`.
Перепроверка: добавить в `test_scenario25_canon_has_two_phase_contract` одно
утверждение о наличии приоритетного предложения; прогнать
`test_evol_w17_small_canon_reqs.py`, `test_post_asap5_w1_writer_core.py`,
`test_post_asap5_w2_tech_reasoning.py`, `test_asap_speech_r3b_canon.py`,
`test_direct_l1_l1d_contract.py`, `test_speech_p0_corrective_l1_route.py`,
`test_evol_evidence_routing.py`, `test_p0_prompts_core.py`,
`test_expression_isolation_followup.py`. Мутация: удаление этого предложения
должно ронять новый тест.

## 6. Две заявленные границы: оценка

1. **Поведение модели offline не проверяется.** Законная граница: acceptance
   карты - правило в L1/ResponsePlan плюс фикстура; `live_required=false`,
   `live_when=preprod`. Проверено: правило доходит до payload, швы политики и
   egress ведут себя по контракту. Что модель реально выберет
   `structure=summary` и заполнит `external_claims` - только живой прогон после
   выката. Это не отменяет блокер раздела 5: противоречие в самом payload -
   не "поведение модели", а дефект текста контракта.
2. **`factcheck.critique.directive` не менялся.** Вне области: это речевая
   директива раздела "Критический разнос", применяется только по уже
   установленным findings и не решает вопрос противоречия фаз. Не блокер.

## 7. Неблокирующие замечания

* Пин "документ = код" и presence-тесты живые (мутации A и C), сохранять.
* Тест миграции одиночного канона проверяет реальный путь
  (`migrate_prompt_canons` -> `apply_release`), но только для одного блока;
  остальные строки таблицы миграции - метаданные лестницы (см. раздел 4).
* "Исходная история неизменна" отдельным тестом не закрыта: свойство
  установлено инспекцией (в правке нет записи в сообщения). Для карты это
  нормальное evidence "инспекция + отсутствие write-путей", но не "тест".
* Неатрибутированная сводка может быть снята egress-guard-ом (проверено
  прямым вызовом). Канон требует атрибуцию, это риск соблюдения модели,
  не код-дефект.

## 8. Итог

**Needs Fixes.** Один блокер (раздел 5), правка - одно предложение и пины.
ER-S25 - НЕ закрываем (FAILED до исправления). ER-54 - закрываем по
canon+mechanism с оговоркой о живом прогоне; правка раздела 5 его не
затрагивает (меняются только байты L1).

Прогоны этого ревью: `tests/test_evol_w17_small_canon_reqs.py` - 15 passed;
18 смежных файлов - 434 passed; 7 известных пре-существующих отказов
воспроизведены (2 + 5). Внешние источники не требовались: все факты локальны
(код, канон, Git).
