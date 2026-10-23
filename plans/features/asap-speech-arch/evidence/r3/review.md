# REV-SPEECH-INIT — независимое ревью R3

- LANE_ID: `REV-SPEECH-INIT`
- Кандидат: `258d3fae` (ветка `speech-init-fix-r3`, worktree `C:\Code\Python\adminbot-wt-speech`), evidence-коммит `28aeb384`
- База: `e4ee54f3` (production 2.58.113); R2 harness: `6b6f8ef7`
- Дата ревью: 23.10.2026, локальное время ~21:35 (UTC+12)
- Режим: read-only, без provider-вызовов, SSH и прода

## Вердикт

**Approved for controlled deployment (parent not DONE).**

Код R3 можно включать в релизный поезд: Direct не сломан, канон изменён только в §3.7, миграция/откат согласованы, живая I-матрица воспроизводит нужное поведение. Полного `DONE` нет: 48-часовое наблюдение в проде и EVAL-MODES остаются открытыми. Отдельное условие — ветка ещё не в текущем master (`fb8f2ad6`); перед выкатом нужен мерж/черри-пик и повторный прогон на объединённом кандидате.

## 1. Канон: изменена только §3.7

`git diff e4ee54f3..258d3fae -- services/chat_prompts.py`: 40 добавленных / 2 удалённых строки. Это замена секции `ВЫБОР УЧАСТИЯ` W1 → R3, новые комментарии и константа `PREV_DIRECT_L1_PLANNER_CLAR`. Схема, контракт «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА», `_DIRECT_L1_PLANNER_RULES` и остальные секции не менялись:

- `_DIRECT_L1_CLARIFICATION_CONTRACT` совпадает с прод-версией байт-в-байт (1932 символа).
- `_DIRECT_L1_PLANNER_RULES` совпадает (1477 символов).
- `_DIRECT_L1_PLANNER_BASE`/W1 совпадает (3133/1533 символа).
- Дифф активного промпта — один непрерывный участок: удалено 772 символа W1, добавлено 1921 символ R3; префикс 1479 и суффикс 4291 совпадают.
- `PREV_DIRECT_L1_PLANNER_CLAR` == прод-промпт 2.58.113: `sha256 c987c03e3ee0…`, 6542 символа.
- Активный R3: `sha256 ab6817a18657…`, 7691 символ; сборка = `_DIRECT_L1_PLANNER_BASE_R3 + CLAR + RULES`.

Вывод: schema, Direct-часть уточнений, act-строка и §4.3 не тронуты. Требование «только §3.7» выполнено.

## 2. Direct не сломан — да

Прогнано на worktree кандидата:

- `tests/test_asap2_clar_contract.py` — 24 passed
- `tests/test_asap7_direct_l1.py` — 37 passed
- `tests/test_asap_w1_semantics.py` — 21 passed
- `tests/test_direct_l1_corrective_r1.py` — 12 passed
- `tests/test_direct_l1_l1d_contract.py` — 15 passed
- `tests/test_prompt_migrations.py` — 42 passed
- `tests/test_asap_speech_i_matrix.py` — 25 passed

Итого: **151 passed на 6 файлах** (без новой матрицы) и **176 passed на 7 файлах** с ней. Оба прогона зелёные. В отчёте R3 стоит «151 passed (7 файлов)» — это неточность учёта: 151 относится к 6 файлам, седьмая матрица добавляет 25 тестов. На поведение не влияет, но строку отчёта нужно поправить.

Дополнительно: `test_asap8_initreply_binding.py` + `test_asap8_f6_initiative.py` — 37 passed; `test_direct_chat_prompts.py` + `test_soul1_core_composer_integration.py` — 46 passed; `test_soul1_registry_completeness.py` — 12 passed (fingerprint-гард).

`tests/test_asap2_telemetry_clar.py` в ветке кандидата отсутствует: файл появился позже в master коммитом `e3d28812` (ASAP2 telemetry). На master он зелёный (9 passed), но к R3-ветке не относится. В объединённом релизном кандидате его нужно прогнать вместе с R3.

## 3. I-матрица по raw

Модель `deepseek/deepseek-v4.1-flash`, FakeBot + spy `send_text`/`set_message_reaction`, живые чаты не затрагивались. Всего 27 completion-вызовов в 4 прогонах (18/2/4/3), ни один прогон >20.

| Кейс | Факт raw | Оценка |
|---|---|---|
| I-01 общий спор | 2/2 `silent`, отправок нет, reply на последнее отсутствует | PASS по §7 (silent допустим); оба прогона — ранний R3, не финальный канон |
| I-02 возражение | прогон 1: target=4 → row 4 = Гоша (990002777), tg 846395, `reply_to=846395`; финальный: target=1 → row 1 = Гоша, tg 846834, `target_user_id=990002777`, `reply_to=846834` | PASS 2/2: цель = сообщение адресата, адресат верный |
| I-04 новая общая тема | ранний R3: 2/2 `silent`; финальный: 2/2 `delivery=chat`, target=null, `reply_to=null` | PASS на финальном каноне |
| I-09 реакция | прогон 1: target=10 → row 10 = Гоша, tg 846401, reaction исполнена; финальный: target=3 → row 3 = Гоша, tg 846836, reaction исполнена | PASS 2/2: положительный путь доказан |
| I-07 старое сообщение бота | в user-контексте L1 есть `[ОТВЕТЫ БОТА (недавние)]` со старым ответом; план `silent` | PASS (контекст), молчание допустимо |
| I-03 флуд | живой прогон R3 не повторялся; тот же механизм, что I-09; positive path — durable-тест | SAFETY PASS / live NOT_REPRODUCED (честно указано) |

Стохастичность: I-01 — 2 прогона (ранний R3); I-04 — 4 прогона (2 ранних silent + 2 финальных chat); I-02/I-09 — по 2 прогона суммарно (ранний + финальный). Это не статистика; §7 требует 48-часовое наблюдение. Отдельно отмечу: raw I-01 и repeat не содержат `l1_system_sha12`, а первый прогон шёл на раннем R3 `25535e8e2f83`; финальный `ab6817a18657` для I-01 напрямую не зафиксирован. Разница раннего и финального R3 — одна вставленная фраза «Если по общей теме… выбери chat…», то есть финальный канон может дать `chat` вместо `silent` (оба допустимы), но не возвращает reply-на-последнее. Аналогично raw I-04-финал не содержит `l1_system_sha12`; принадлежность финальному канону подтверждается `ledger-runs.json` (purpose run_r3c), а не самим raw. Это evidence-оговорки, а не поведенческий блокер.

## 4. React: target обязателен, без target — молчание

- §3.7 R3: «Для реакции укажи target_message_id… без конкретной цели реакция не исполняется».
- `_execute_initiative_react`: без валидной цели возвращает `silent/l1_react`, текста не отправляет; durable-тест `test_i09_react_without_target_is_honest_silence` — passed.
- Положительный путь: I-09 оба прогона исполнили реакцию на сообщение Гоши (`846401` и `846836`).

Замечаний нет.

## 5. bot_replies: окно инициативы из контекста, Direct-дефолт 600 с

- `_recent_bot_replies(chat_id, limit=3, *, window_seconds=None)`: при `None` — `bot_replied_recently_window_seconds()` (default 600); инициатива передаёт `_initiative_context_window_seconds()`.
- `_initiative_context_window_seconds()` = `max(3600, limits.summary_window_hours * 3600)` — тот же hot-ключ и fallback, что у `MemoryService.get_window_messages` (`services/summary_memory.py:2698`).
- `DirectChatService` на строке 2843 по-прежнему вызывает `_recent_bot_replies(chat_id)` без окна; дефолт не изменён.
- I-07 raw: ответ бота 1200 с назад виден в `[ОТВЕТЫ БОТА]` инициативного L1. Durable-тест `test_i07_bot_reply_older_than_600s_reaches_initiative_l1` подтверждает: 1200 с видит инициатива, 1200 с не видит Direct (600 с). `test_i07_recent_bot_replies_reach_l1_context` — passed.

Замечаний нет.

## 6. Миграция и откат

- `PROMPT_MIGRATIONS[...]`: добавлена ступень `(PREV_DIRECT_L1_PLANNER_CLAR, DIRECT_L1_PLANNER_SYSTEM_PROMPT)`; прежние ступени (base/1021/1022/L1D/W1) сохранены, циклов нет.
- `ROLLBACK_MIGRATIONS[...]`: `(R3, PREV_DIRECT_L1_PLANNER_CLAR)` — снимается только ступень R3, стек цел.
- `FACTORY_REVISION_LABELS["direct.base.l1_planner"] = "l1-planner-participation-r3"`.
- Fingerprint: prod `24ae494ac422` → R3 `c531f7b289d1`; по-блочное сравнение factory-текстов даёт ровно **1** изменённый блок — `direct.base.l1_planner`. Совпадает с заявленным `changed = 1`.
- `factory_text("direct.base.l1_planner") == DIRECT_L1_PLANNER_SYSTEM_PROMPT` — true.
- Идемпотентность, rollback и сохранение кастома проверены `test_prompt_migrations.py` / `test_asap2_clar_contract.py`: повторная миграция — no-op; кастом (не точное совпадение байт) не перетирается ни вперёд, ни назад.
- ΔDDL = 0: в диффе нет schema/migration/SQL-файлов, новых таблиц/колонок нет.

Замечаний нет.

## 7. Нет хардкода

В диффе нет списков слов, regex-триггеров или квот под формулировки. Изменения — текст §3.7 (смысловые критерии), `INITIATIVE_LINE`, формулировка задачи инициативы, `speaker="наблюдатель"` и параметр окна `bot_replies`. Решения остаются за L1; транспорт только проверяет техническую возможность цели. Требование выполнено.

## 8. EVAL-MODES: различие не достигнуто, оставлено открытым

- 6 ходов (3 стимула × 2 режима) × 2 вызова = 12 completion-вызовов.
- `branches_present`: ровно `["occasional"]` или `["frequent"]` в каждом ходе; утечки второй ветки нет.
- `profanity_count`: occasional 0/3, frequent 0/3. В frequent-2 есть «херня», но `count_profanity` её не считает (её нет в `PROFANITY_ROOTS`); это не подкрутка, а ограничение диагностического счётчика.
- `services/mca_expression.py` и тексты `PROFANITY_INSTRUCTIONS` не менялись.
- Отчёт корректно оставляет дефект открытым: нужна выборка §9.2 (3 режима × 3 жанра × 10 стимулов) и трассировка провайдера. Это не блокер R3, но и не «победа».

## 9. Числа и воспроизведение

- 6 файлов (без новой матрицы): **151 passed** (3.6 с у меня; в отчёте 5.75 с — допустимая разница окружения).
- `test_asap_speech_i_matrix.py`: **25 passed**.
- 7 файлов вместе: **176 passed** (113 с; в общем прогоне заметно медленнее, но без падений).
- Смежные: 37 + 46 + 12 passed.
- `test_asap2_telemetry_clar.py`: в ветке кандидата нет; на master — 9 passed (`e3d28812`).

## 10. Находки

1. **RELATED_SMALL / evidence (не блокер поведения):** в `report.md` сказано «151 passed (7 файлов)». Фактически 151 — это 6 файлов; седьмая матрица добавляет 25, итого 176/7. Нужна правка строки отчёта, код не трогать.
2. **RELATED_SMALL / evidence:** I-01 в raw привязан к раннему R3 (`25535e8e2f83`), repeat не содержит system SHA; финальный `ab6817a18657` для I-01 напрямую не прогнан. Дельта финального канона — одна положительная chat-фраза; запрет reply-на-последнее не ослаблен. Рекомендую 2 прогона I-01 на финальном каноне или явно пометить в отчёте «early R3»; 48h live это также покрывает.
3. **RELEASE_CONDITION / integration:** ветка `speech-init-fix-r3` основана на `e4ee54f3`; текущий master `fb8f2ad6` R3 не содержит. Нужен мерж/черри-пик в актуальный release candidate. `direct_chat_service.py` и `direct_l1.py` при пробном merge авто-мержатся (R3-код и `_clar_target_present` сосуществуют), но в других файлах есть несвязанные конфликты (embed). После интеграции прогнать объединённый набор, включая master-only `test_asap2_telemetry_clar.py`.
4. **OPEN / EVAL-MODES:** различие occasional/frequent не подтверждено; выборка 12 вызовов недостаточна. Оставлено открытым корректно.
5. **READY_FOR_LIVE / 48h:** §7 требует 48-часовое наблюдение распределения в проде без квот. Это post-deploy проверка; до неё parent `DONE` невозможен.
6. **NONBLOCKING / map:** `plans/features/asap-speech-arch/requirements-map.json` привязана к `0f3ed53a` (не к `258d3fae`); строгий gate review/release в этом лейне не запускался. Это отдельная задача PM; карта не отражает R3.

## 11. Ответы на вопросы

- **Direct не сломан:** да.
- **Можно ли в поезд:** да, как controlled deployment после мержа/черри-пика в актуальный release candidate и повторного прогона; сам `258d3fae` чист.
- **Что остаётся открытым:** 48h live-наблюдение; EVAL-MODES (3×3×10 + трассировка); evidence-пометки I-01 и число файлов в отчёте; map/gate — PM.