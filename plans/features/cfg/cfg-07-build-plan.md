# CFG-07 Build Plan — речевая целостность: 07A/07B/07C → CFG-FINAL

Подготовлено: PM, lane CFG-07-PREP, 20.10.2026. Режим read-only по коду; этот файл — единственная запись.
Бриф для оркестратора. Билд не назначается. База сверки: кандидат UNIFIED-CORE `37097f7c` (2.58.98, ревью в полёте), прод = 2.58.97.

## 0. Главный вывод сверки

**CFG-07B поглощён UNIFIED-CORE почти целиком.** Слот «исполнение Expression» из `plans/features/add-exp/prep-add-exp.md` §2 реализован и задеплоен в кандидате 2.58.98: режимы off/occasional/frequent (тексты владельца F3 от 20.10), runtime-wiring всех маршрутов, диагностика, миграция `allowed`→`occasional`. Остаток 07B — консолидация доказательств, не новая реализация. CFG-07A покрыта частично (два конкретных источника метатекста вычищены, Core подключён везде), CFG-07C не начата (egress-guard — новый механизм).

## 1. CFG-07A — аудит речевого маршрута и запрет backstage (map: 10 строк)

### Уже покрыто `37097f7c` → REUSED_EXISTING

| Req | Что сделано | Доказательство |
|---|---|---|
| 07A.1 (частично) | Core+Expression подключены во ВСЕ пользовательские маршруты: `speech_owner_block` — `services/prompt_composer.py:740`; call sites: `factcheck_service.py:214,271`, `summary_generator.py:1850,4070`, `checkup_service.py:67`, `search_service.py:91`, `web_summarizer_service.py:71`, `youtube_summarizer_service.py:109,152,194` | 18 CONTRACT-тестов `tests/test_unified_core_route_coverage.py` (factcheck two-call/single/byte-parity, summary narrator/single, checkup chat/tool-neutral, search, youtube, web, off-mode, hot-apply, factory defaults) + 16 payload-трасс в `plans/features/add-exp/evidence/directives-fix/` |
| 07A.2/07A.7 (2 источника метатекста) | C14: строка safety-bypass («Игнорируй все настройки…») вычищена из фактчек-канона по ADR-1013-3 (PREV-лестница, byte-tests); C13: мёртвый `tone_hint` убран из analyst-канона | `services/prompt_migrations.py` (ступени `PREV_FACTCHECK_UNIFIED_CORE*`, ROLLBACK на непосредственный прежний канон); тесты `test_factcheck_canon_has_no_safety_bypass`, `test_analyst_canon_has_no_dead_tone_hint`, `test_unified_core_migration_ladder_and_rollback`, `test_persisted_old_factcheck_canon_still_suppressed` |
| 07A.6 (частично) | Юмор-директивы переписаны без декларативной режиссуры; humor-путь не берёт expression-регистр | `services/mca_humor_craft.py` (дифф 37097f7c); тесты `test_header_has_no_false_l1_delegation`, `test_humor_path_never_takes_expression_register` |
| 07A.8 (factcheck-часть) | raw tool_context/reason/style_note не идут в Writer фактчека — закрывается планом CFG-06 W3 (`stage2_payload` whitelist в `system2_handoff`) + W5 (удаление `style_note`-утечки `_temporal_verbalize` L753–758) | план CFG-06, §2 W3/W5 — принадлежит CFG-06, не дублировать |

### Остаток → слайсы

**Слайс 07A-1 «Deployed-аудит + корпус»** (владелец map-слайса CFG-07A)
- Write scope: `plans/features/cfg/evidence/cfg-07/audit/**` (+ корпус фикстур там же). Код не трогается.
- Закрывает: 07A.1 (остаток: env-флаги, релизы SOUL-1, deployed SHA, сравнение до/после юмора на проде), заготовка корпуса для 07D.1/07D.6 (фрагменты из скриншотов + версии prompts/hot-config).
- Deps: финал — после релиза CFG-06 (W7, новый deployed SHA); офлайн-часть корпуса — можно готовить read-only уже сейчас.
- Acceptance: таблица effective payload (Core→style policy→юмор/мат→каналы→вербализатор→validator→postprocess→Telegram) с пруфами на deployed SHA; каждый env-флаг и релиз SOUL-1 подтверждён значением на проде (технические проверки: прод-байты/логи/healthz, без сообщений в чат — прецедент 2.58.97); «Core уже включён» не декларируется без трассы.
- Risk R1. Next: 07A-2 merge.

**Слайс 07A-2 «Анти-backstage контракт + честные ограничения»** (владелец CFG-07A)
- Write scope: каноны/промпты пользовательских маршрутов (factcheck/summary/direct/checkup/search/youtube — ПОСЛЕ фриза W3, не форкать контракты CFG-06), встроенные фразы ошибок/fallback, новый тест `tests/test_cfg07_backstage_contract.py`, evidence `plans/features/cfg/evidence/cfg-07/07a/**`.
- Закрывает: 07A.2–.7 (остаток), 07D.1, 07D.2 (офлайн-часть).
- Acceptance (наблюдаемое): корпус backstage-проб (mock-Writer с форсом «сейчас сделаю смешно», «аналитик подтянул», «в моей справке», ссылок на промпт/логи/System2) — в публичном ответе ни одной; позитивные контролы живы: честное «проверил — не нашёл подтверждений» при реально выполненной проверке не вырезается; «такого сообщения не нашлось» вместо «в логах нет»; прямой административный вопрос об устройстве — честный ответ; допустимый сарказм не удалён целиком; не один растущий black-list regex (смысловой guard — это 07C, здесь только инструкция + устранение источников). 07D.1 live-глазами владельца — опционально (уже покрыто формулировкой owner_live_checks).
- Deps: CFG-06 W3 (фриз канонов фактчека) — серийно после CFG-06. Risk R2. Next: 07C-G.

## 2. CFG-07B — параметр «Мат» (map: 11 строк) → почти весь REUSED_EXISTING

### Таблица поглощения (доказательство = файл:якорь + тест на `37097f7c`)

| Req | Статус | Доказательство |
|---|---|---|
| 07B.1 | REUSED_EXISTING (с оговоркой размещения, §6.1) | Переключатель = режимы «Без мата / Эпизодически / Часто»: `web/api/speech.py` `EXPRESSION_CONTROLS` (~L115–141, effect-тексты F3), UI `web/app.js` «Речь → Как выражаться»; GLOBAL/CHAT override + видимый источник + сброс наследования — существующая механика Speech UI; заводское ON = default `occasional`: `test_factory_defaults_inject_core_and_occasional`; источник/reset: `test_global_payload_explicit_effective_and_no_inherit`, `test_chat_scope_inherit_label_isolation_and_reset` |
| 07B.2 | REUSED_EXISTING | Единое правило = profanity-режим Expression; «profanity_use» — проекция: ON ⇔ occasional/frequent, OFF ⇔ off (дизайн-решение в `plans/features/add-exp/design-add-exp.md`, ADD-1.E1: второй storage запрещён); миграция read-alias `allowed`→`occasional` без потери данных: `test_migration_read_alias_keeps_data_and_never_frequent`, `test_modes_are_closed_set_and_allowed_is_read_alias`; `MAT_ENABLED`/`SWEAR_ENABLED` в коде НЕ существуют (git grep 37097f7c — 0 совпадений); registry/schema/UI/persistence обновлены одним изменением (`web/api/speech.py`, `services/mca_expression.py`, `services/prompt_migrations.py`); `runtime_wired: True` в `speech.py` |
| 07B.3 | REUSED_EXISTING | Тексты владельца (20.10) байт-в-байт: `services/mca_expression.py::PROFANITY_INSTRUCTIONS` — off «Не используй мат в собственной речи», occasional «Иногда используй мат…», frequent «Матерись свободно и регулярно…»; OFF-цитаты: `EXPRESSION_HEADER` «дословные цитаты и чужой текст передаются как есть»; тесты `test_owner_exact_texts_are_canon`, `test_instruction_texts_byte_exact_and_distinct`, `test_core_and_canon_byte_parity_with_expression_off` |
| 07B.4 | REUSED_EXISTING | Три режима, уровень «умеренно/жёстко» не введён без нужды; закрытый сет: `test_modes_are_closed_set_and_allowed_is_read_alias`; насильные вставки запрещены: `test_no_mechanical_counters_or_forced_inserts`, `test_no_profanity_postprocessor_exists` |
| 07B.5 | REUSED_EXISTING | Единое правило P0 на всю пользовательскую речь с исключениями машинных стадий: `EXPRESSION_HEADER` (factcheck/сводки/служебные ответы; цитаты как есть); тесты `test_header_unified_rule_p0`, `test_factcheck_machine_plan_has_no_expression_and_no_examples`, `test_machine_writers_keep_profile_reason_not_expression_defect`, `test_checkup_tool_loop_without_chat_id_stays_neutral`; style policy не удаляет и не вставляет мат: `test_style_policy_neither_removes_nor_inserts_profanity` |
| 07B.6 | REUSED_EXISTING | chat/global/factory merge: `test_effective_per_control_merge_chat_global_factory`; без рестарта: `test_hot_apply_changes_payload_without_restart`; fallback получает блок (docstring `speech_owner_block` + route-coverage); effective payload отражён (16 трасс directives-fix) |
| 07B.7 | REUSED_EXISTING (инструкция) + AGENT_CHECK (измерение) | Hard-семантика: сильная генеративная инструкция (frequent-текст); постпроцессорной вставки нет (тесты выше). «Измерение соблюдения / bounded retry при систематической стерильности» — «если это оправдано» (L360): решение по результатам офлайн-eval (`evidence/directives-fix/eval.json`, harness `eval_directives.py`); механические счётчики отменены владельцем 20.10 — не возвращать |
| 07B.8 | REUSED_EXISTING | Диагностика: `EXPRESSION_DIAG_CLASSES`/`emit_expression_diag` в `services/mca_expression.py` (closed set policy_not_injected/composer_excluded/model_ignored_instruction/postprocess_changed/provider_limitation/unknown; R17 — только коды/числа/хеши, без приватных текстов); тесты `test_diag_classes_closed_set_and_r17_dedup`, `test_composer_excluded_diag_fires_for_expression_skip`, `test_fallback_adapter_marker_loss_reports_policy_not_injected`, `test_live_check_endpoint_honest_paths`, `test_live_check_class_reports_missing_marker`, `test_ui_renders_payload_not_raw_codes` |
| ADD-1.C4 | REUSED_EXISTING | Покрыт 07B.1/.3: SOUL-1 сохраняет манеру (frequent-директива), default ON (occasional), OFF-цитаты не портятся (`test_core_and_canon_byte_parity_with_expression_off`) |
| 07D.3 | Офлайн-часть REUSED, live → владельцу | Офлайн: harness+отчёты `plans/features/add-exp/evidence/directives-fix/{eval.json, red-exact.txt, green-exact.txt, probe-*, disjoint-check.json, budget.json}`; изоляция/наследование/hot-reload — тесты выше. Live-набор (ON-регистр в перепалках, OFF-чистота) уже в `plans/owner_live_checks.md` §2 — владельцу, не блокер |
| 07D.4 | Частично REUSED | Защита цитат/машинных стадий: `test_style_policy_neither_removes_nor_inserts_profanity` + byte-parity + tool-loop neutral. Остаток: консолидированный прогон URL/код/JSON/научные термины/числа/HTML — добрать тестом в 07B-V только при дырах |

**Слайс 07B-V «Консолидация доказательств»** (владелец CFG-07B)
- Write scope: `plans/features/cfg/evidence/cfg-07/07b/**` (+ один новый тест `tests/test_cfg07_protected_spans.py` строго при найденных дырах 07D.4). Код не меняется; найденный дефект = отдельный микрослайс на решение оркестратора.
- Deps: НЕТ жёстких — кандидат `37097f7c` существует; **можно исполнять сейчас, параллельно билду CFG-06** (скоупы не пересекаются).
- Acceptance: evidence-пакет «req → файл:якорь → тест» по всем 11 строкам (таблица выше превращена в проверенный артефакт); офлайн-eval повторён на текущем HEAD кандидата; 07D.4-пробелы закрыты или честно перечислены.
- Risk R1. Next: ничего (после G0-вердикта — закрыть строки карты).

## 3. CFG-07C — egress-guard (map: 9 строк) → НЕ начата, новый механизм

**Слайс 07C-G «public_speech_guard на точке outbound»** (владелец CFG-07C)
- Write scope: новый `services/public_speech_guard.py`; интеграция на delivery-швах (factcheck — швы W5 `factcheck_render`/`factcheck_delivery`; Direct/fallback/error-пути; summary/checkup/search/youtube send); тесты `tests/test_cfg07_public_speech_guard.py`; evidence `plans/features/cfg/evidence/cfg-07/07c/**`.
- Закрывает: 07C.1–.6, 07D.5, 07D.6, 07D.7.
- Конструкция (из L363–372): после Composer/Writer, до финальной сериализации/доставки; стоимость ограничена; факты/ссылки/имена/цитаты/числа не меняет; детерминированный sanitize для машинных артефактов (JSON/role/tag/reason_code, сырой HTML), bounded retry для смысловой метаречи, честный fail-soft текст в стиле персонажа без «фиктивно уверенного вердикта»; НЕ применяется к машинным JSON/памяти/логам/поисковым запросам; обычные слова «лог/анализ/проверка» в содержательном контексте — не нарушение; не дублирует analyst/verbalizer-изоляцию и не создаёт второй Writer.
- Переиспользовать: `strip_phantom_tags`/grounding-валидаторы, `negative_constraints.verbalize_validated` (список reuse из брифа CFG-06 §5), словарь метатекста из 07A-2, честный fail-soft текст из 07A-2.
- Acceptance (наблюдаемое): 07D.5 — mock-Writer форсит `{"reason":"temporal_date_unknown"}`, `fact:123`, «по моим логам», «анализатор считает», сырой `<b>`, битую ссылку → на стороне Telegram ни одного артефакта, теги отрендерены/безопасно деградировали, факты не изменены, без пустых «успехов» и логических разрывов; 07D.6 — контрольные фрагменты скриншотов + версии prompts/hot-config воспроизводят регрессии ДО и не воспроизводят ПОСЛЕ (deployed SHA + флаги подтверждены); 07D.7 — переходы/дефолты SOUL-1/W3/W6, Direct/Factcheck/Initiative/tool/fallback, ближайший Summary; покрытие честное, без «100%» по необследованным маршрутам; 07C.6 (live_required, postdeploy) — технические проверки на проде в каждом маршруте (логи/трассы/байты, без сообщений в чат); живой просмотр владельцем — опционально, уже в owner_live_checks §6 по духу.
- Deps: CFG-06 W5 (швы доставки) + W3 (whitelist) + 07A-2 (словарь/fail-soft). Risk R2. Next: CFG-FINAL.

## 4. CFG-FINAL (map: 15 строк ADD-0.x/ADD-2.x)

Без нового кода: композитная приёмка ADD-2.6 (единый фактчек) и ADD-2.7 (один голос Core + переключатель мата + отсутствие backstage во всех публичных маршрутах + защита цитат + delivery) = регрессионный проход по VERIFIED-эвиденсу 06/07A/07B/07C + итоговый статус-отчёт со сквозной requirements-map (ADD-2.8). Барьер: все слайсы 06+07 VERIFIED. Отдельные композиты не закрывать частичными зелёными (прецедент CFG-04.B).

## 5. Граф зависимостей и волны

```
G0: вердикт ревью 2.58.98 (37097f7c)  ← валидирует всю REUSED-базу
CFG-06 (W0→…→W7, в плане) ──G1: release/deploy──┐
07B-V (можно СЕЙЧАС, ∥ CFG-06; write: evidence 07b/**)
07A-1.offline (read-only корпус, ∥ CFG-06) ─────┤
                                                 ▼
                       07A-1.final (deployed-аудит) ∥ 07A-2 (контракт)
                                     │ G2: 07A-2 merge
                                     ▼
                                  07C-G ──G3: все VERIFIED──► CFG-FINAL
```

- **Параллельно с билдом 06 (read-only или evidence-only скоупы):** 07B-V (writer, только `plans/features/cfg/evidence/cfg-07/07b/**`), 07A-1 офлайн-корпус, дизайн-скелет 07C-G (seams известны из плана 06 — без правок кода).
- **Жёсткие барьеры:** G1 — 07A-2 не merge до релиза 06 (иначе конфликт в канонах фактчека и форк контрактов W3); G2 — 07C-G не стартует до 07A-2 (нужен словарь метатекста и fail-soft текст); G3 — FINAL только после всех.
- Writer-лэйнов одновременно ≤2 (07B-V ∥ 07A-1/07A-2 внутри своей волны) — лимит ≤3 соблюдён; очередь 06→07A→07B→07C серийная по существующему плану, 07B-V лишь закрывает строки досрочно.
- Оркестратору: обновить `slice-graph.json` подпакетами 07A-1/07A-2/07B-V/07C-G (правка вне скоупа этого лейна) и прогнать `requirements_gate.py check --stage plan`.

## 6. Риски / неоднозначности исходника (цитаты; Human Gate не требуется)

1. **Размещение переключателя 07B.1.** Источник L354: «Добавить в раздел **Стиль письма / Speech Style Policy** понятный переключатель **„Использовать мат“**, рядом с … настройками кавычек, эмодзи». Доставлено: режим-селектор в «Речь → Как выражаться» (`owner_live_checks.md` §2). Разрешение: позднейшее решение владельца (тексты F3, 20.10; владелец уже получил UI и live-чек-лист) старше-приоритетнее; семантика (factory ON, override, источник, reset) выполнена. Не вопрос владельцу; фикс для Reviewer.
2. **Тип правила 07B.2.** L355: «отдельное эффективное правило `profanity_use`/аналогичный тип в текущей типизированной политике». Доставлено: profanity-режим Expression + документированная проекция ON/OFF (`design-add-exp.md`, ADD-1.E1). Источник допускает «/аналогичный тип» — покрыто; второй storage запрещён дизайном.
3. **Измерение/retry 07B.7.** L360: «измерение соблюдения/ограниченный retry … (если это оправдано)» против директивы владельца 20.10 «no counters/postprocessor/extra LLM». Решение агентское: bounded retry вводится только если офлайн-eval покажет систематическую стерильность; иначе честно фиксируется `model_ignored_instruction`. AGENT_CHECK, не гейт.
4. **Граница «явного технического/административного контекста» 07A.5** (L345) — инженерное правило (админ-команды/Inspector vs обычный чат), закладывается в словарь guard; выбора владельца не требует.
5. **Корпус из скриншотов 07D.6** (L381) — приватные тексты в evidence не публикуются (правило 06F.1); корпус живёт локально, в отчётах — маскированные фрагменты.
6. **Контингенция G0:** если ревью откатит часть UNIFIED-CORE, строки REUSED_EXISTING переоткрываются; 07B-V тогда превращается из консолидации в фикс. Барьер G0 это покрывает.
7. **Профанация в factcheck-канале:** после 07B мат не форсируется в цитаты/машинные стадии, но Expressia-инструкция формально действует «на всю пользовательскую речь» (P0-заголовок) — стык с жанровыми исключениями фактчека (CFG-06 W5) проверить тестом в 07A-2, чтобы P0-заголовок и «фактчек = точность» не спорили на уровне инструкций.

## 7. Handoff оркестратору

- Готово: покрытие 07A/07B/07C → слайсы со скоупами/зависимостями/приёмкой; REUSED-таблица 07B с доказательствами; барьеры G0–G3; новых Human Gate нет (все потенциальные неоднозначности закрыты более поздними решениями владельца: F3 20.10, standing PET_PROJECT, правило owner_live_checks).
- Действия оркестратора: (1) дождаться G0-вердикта 2.58.98; (2) при желании назначить 07B-V сейчас (evidence-only, не конфликтует с билдом 06); (3) обновить slice-graph подпакетами и прогнать план-гейт; (4) волну 07A/07C назначать только после G1/G2.
- Live-пункты владельцу (не блокеры, уже в `plans/owner_live_checks.md`): §2 режимы мата (07D.3), §6 единый голос в фактчеке/сводках (07D.1/ADD-2.7 по духу). Новых live-обязательств план не добавляет; 07C.6 — агентская техническая postdeploy-проверка.
