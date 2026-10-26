# REVIEW-DELTA-DEPTH — независимое ревью среза DELTA-DEPTH (27.10.2026)

**Verdict: Approved** (lane REVIEW-DELTA-DEPTH, leaf-обзор одного коммита; финальное слово за parent Reviewer).

**Binding:** кандидат `8e8c8c27` (task/p0-delta, «p0-delta(DELTA-DEPTH): verbatim §11 owner instruction + writer substance requirement»), база `683905b7` (release-линия с res23; прод = b5716022/2.58.133). Detached-ворктри `C:\Code\Python\adminbot-wt-delta-depth-rev`. Код ревьюером не менялся; SSH/прод/Telegram/LLM не трогались.

## Результаты по пунктам VERIFY

1. **Вербатим §11 — ПОДТВЕРЖДЕНО.** `DELTA_READY_INSTRUCTION_TEXT` == внутренний текст «…» строк 129–134 `plans/features/p0-delta-analysis/source-2026-10-26.md`, сверено НЕ через тест, а независимой python-сверкой байт (sha256 префикс константы и источника совпал: `aefbc213ec9fbad8`; у 6 строк нет leading/trailing whitespace, guillemet'ов внутри нет — извлечение однозначно). Тест не хардкод: `test_delta_instruction_is_verbatim_from_source` читает снапшот источника из репо в рантайме (`tests/test_p0_delta_depth_instruction.py:36-44`).
2. **Ровно-один-раз / отсутствие на casual — ПОДТВЕРЖДЕНО.** Единственный носитель — план-блок (`direct_l1.py:1247-1255`, строки «как отвечать: …» / «по существу: …»), режимный блок дельту не содержит (`test_delta_instruction_not_in_mode_blocks`; self-check `delta_deep_auto_plan_once` включает `_delta not in deep_system`). research/deep-auto: 1×1 (юнит-тесты payload + self-check `delta_research_plan_once`, `delta_deep_auto_plan_once`); casual/answer: 0 (юнит + self-check `delta_casual_absent`). Вставка независима от `include_analysis` (deep+пустой extent при include_analysis=False всё равно несёт дельту 1×). NO_META closing/structure не тронуты (в diff отсутствуют), все no_meta-инварианты self-check = true, `test_no_conflict_with_no_meta` passed. Analysis 1×1 цел (count==1 в `test_deep_research_with_extent_exactly_once`; `no_meta_directive_1x1_research/answer` = true). Нового слоя/LLM-вызова нет: diff добавляет только константы, предикат, опц. параметр блока, инструментарий пробы и тест.
3. **DELTA_SUBSTANCE_TEXT — КОРРЕКТЕН.** «Сделай выводы по существу вопроса на основе найденного; при неполном покрытии честно скажи, что установлено и за какой период, и дай лучшие наблюдения вместо отчёта о покрытии.» — цифр нет (проверено), маркеров списков/схем нет, приказов композиции/старта нет («начинай с», «обязател», «схема» и т.п. отсутствуют; пинится `test_no_mandatory_structures_numbers_examples` и self-check `delta_no_composition_mandate`). Читается как требование наличия выводов, НЕ «всегда начинай с вывода». Owner-guard (без универсальных шаблонов, NO_META announcement-only) соблюдён: вставленный текст — дословный текст владельца, substance-строка композиции не задаёт.
4. **Call-sites — ТОЧНО ДВА.** Основной ответ `direct_chat_service.py:3841`, инициатива `:9321` — оба через один предикат `delta_instruction_needed`; других продуктовых вызовов `build_l2_plan_block` нет (factcheck этот блок не собирает); `include_delta` по умолчанию False — прочие пути не затронуты. Wiring пинится `test_direct_chat_call_sites_pass_delta_flag` (count==2).
5. **S03-юнит — ЧЕСТНЫЙ.** `test_stub_scenario_writer_prompt_asks_conclusions_over_coverage` реально требует в Writer-промпте substance-строку (наличие в блоке 1×, ключевые фразы «выводы по существу вопроса на основе найденного», «честно скажи, что установлено и за какой период», «вместо отчёта о покрытии») + 1× в payload.
6. **Прогоны (этот ворктри, кандидатом):** mandated pytest-набор — **149 passed, 0 failed** (93.8s); `probes_full/harness_probe_full.py --self-check` — **EXIT=0, ok=[]**, новые инварианты delta_* = true. Сравнение с базой не потребовалось (сбоев нет; заявленные Builder'ом 4 pre-existing фейла `test_soul1_composer_parity_off` на чистой базе — вне mandated-набора, поверхность композер-паритета диффом не тронута, `test_prompt_migrations.py` зелёный).

## Находки

Блокирующих нет. Замечаний по швам нет: fabric-реестр промптов не менялся (`test_prompt_migrations` зелёный), legacy-ветка пробы защищена signature-проверкой `_accepts_delta`, инициатива при fallback-плане не получает дельту (блок пуст).

## Использованные проверки vs переиспользование

Самостоятельно: независимая байт-сверка вербатима, чтение diff `683905b7..8e8c8c27` полностью, контексты обоих call-sites, место вставки в `build_l2_plan_block`, оба mandated-прогона. Переиспользовано: none (evidence Builder'а сверена с собственными наблюдениями).

Внешние источники не требовались (все факты репо-локальные).
