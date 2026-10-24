# ASAP-2 residual verify (read-only) — T24 / DONE-D5 / DONE-D6 / MIGR-PAYLOAD / MIGR-HOTAPPLY

LANE: `ASAP2-VERIFY-RESIDUAL-RETRY`. Режим: чтение + прогон профильных тестов; **прод, SSH, Telegram не трогались, код не менялся**.
Дата прогона: 25.10.2026 (локально, Windows).

## 0. Окружение и расхождение по базе

| Факт | Значение |
|---|---|
| worktree | `C:\Code\Python\adminbot-wt258119` |
| `git fetch origin` → `origin/master` | `675308b5` («docs(p0): final acceptance matrix (584 required)…») |
| `git status --porcelain` до работы | пусто (clean) |
| заявленный в задании tip `5d2ad4b1` | **отсутствует в репозитории** (`git log 5d2ad4b1` → `unknown revision`), `merge-base --is-ancestor` → fatal |
| фактическая база проверки | `675308b5` = текущий `origin/master` |
| интерпретатор | `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (3.12), `import services` → `C:\Code\Python\adminbot-wt258119\services\__init__.py` (код берётся из worktree, не из основного репо) |

`git reset --hard` не выполнялся: worktree уже чист и стоит на `origin/master`. Расхождение `5d2ad4b1` vs `675308b5` — устаревшая ссылка в задании, не потеря работы.

## 1. T24 — PASS (структурно/service-level; живой прогон остаётся внешним)

Формулировка (карта, `MAN-T24`, source §6.3 #24): «Уточняющий ответ пользователя после restart и повторной загрузки истории → тот же контекстный результат, если история доступна».

**Ссылка в карте устарела по номерам строк.** В карте указано `tests/test_asap2_clar_contract.py:513-546`; фактически тест сейчас на **:545-578** (файл вырос). Тест называется `test_24_second_turn_sees_original_request_bot_question_answer`.

Что реально утверждает тест (`tests/test_asap2_clar_contract.py:545-578`):
- `:553-565` первый ход: в L1-payload есть исходная просьба «Бот, скинь recap чата», вопрос бота «За какой период рассказать…», `[СООБЩЕНИЕ]` + «сегодня» (ровно 1 маркер);
- `:567-568` L2-Writer второго хода не получает «clarification»;
- `:570-578` «рестарт» = **новый экземпляр сервиса** + повторная загрузка истории через `FakeMemory(window=...)`, затем `assert text2 == text` — payload **байт-равен**.

Дополнительно `:584-…` (`test_24_truncated_window_and_branch_are_honest`): усечённое окно не выдумывает просьбу, бюджет 140 токенов сохраняет `[СООБЩЕНИЕ]`, Telegram-reply доносит вопрос бота.

Прогон: `pytest tests/test_asap2_clar_contract.py -q` → **24 passed in 3.86s** (0 failed, 0 skipped).

**Граница:** это service-level с фейковым LLM/памятью (0 сети, 0 платных вызовов). «Тот же контекстный результат» доказан как байт-равенство **собранного** payload, а не как живой ответ модели после рестарта процесса. Для инженерной приёмки этого достаточно (acceptance допускает «структурный/интеграционный тест»), живой прогон после рестарта остаётся `WAITING_EXTERNAL`.

## 2. DONE-D5 — PASS (service-level; граница: инструменты исполнялись с фейковым dispatch)

Формулировка (карта `L00305`, §8 условие 5): стандартный Direct → tool → L2 не получает лишнюю команду переспросить; для действительно отсутствующей обязательной цели уточнение остаётся доступным (матрица #11, #13–#17, #32).

Код:
- `services/direct_chat_service.py:4470-4473` — tool-фаза возвращает `None` только при `not tool_schemas`, `tool_router is None` **или** `getattr(plan,"needs_clarification",False)`. Speech-сигнал/NLU-эвристик в гейте нет (#32).
- `services/direct_l1.py:992-1001` — директива «недостающий обязательный предмет: <target>» + «Спроси только о нём одним понятным вопросом…» добавляется **только** при `clarification=True` и непустом `clarification_target`; пустая цель → директивы нет вовсе (#30, generic-опрос не генерируется).
- `services/direct_chat_service.py:3685-3686` — `clarification=bool(needs_clarification)`; `build_l2_plan_block(..., clarification=False)` для обычного маршрута даёт **84 символа** (`<Response_Plan>`, `действие: reply`, `смысловой акт…` при не-clarification акте) — 0 директив уточнения (проверено в этом прогоне, см. §4).

Тесты/прогоны:
- `tests/test_addtr_tools_minifix.py:221-235` (`test_full_handle_health_evidence_reaches_l2_writer`) — INTEGRATION handle → L1 → tool-фаза → L2: инструмент реально диспатчится (`["get_bot_health"]`), отчёт попадает в `llm.l2_user_content()`; `:197-217` seam «анонс → ровно один вызов».
- `pytest tests/test_addtr_tools_minifix.py -q` → **15 passed in 3.93s**.
- `pytest tests/test_asap8_v6_wc_direct_d04.py -q` (контракт execution modes / `run_simple_tools`) → **34 passed in 3.30s**.
- `tests/test_asap2_clar_contract.py:129` (`test_32_speech_hints_never_suggest_clarify`), `:62/:75` (T30: пустая цель не даёт generic, цель даёт узкую директиву) — в составе 24 passed.

**Наблюдение для карты (не блокер):** в карте (`DONE-D5`, evidence `services/direct_chat_service.py:4424-4427`) сказано «возвращает None **только** при needs_clarification — других условий нет». На текущем master строки сместились в **4470-4473** и условий три (`not tool_schemas`, `tool_router is None`, `needs_clarification`). Два дополнительных условия не связаны с переспросом (нет схем/роутера → Writer без evidence), инвариант D5 не нарушают, но формулировку evidence стоит поправить при следующем обновлении карты.

**Граница:** живого исполнения инструментов против внешних API (и прода) в этом прогоне не было — dispatch фейковый. Семантика #13–#17 опирается на probe r1/r2 (платные живые прогоны, уже в карте), а не на этот прогон.

## 3. DONE-D6 — FAIL как «закрыто»; дефекта нет, не хватает живого охвата §6

Формулировка (карта `L00306`, §8 условие 6): сценарии §6 пройдены как семантические прогоны действующей модели **и** интеграционные проверки, без runtime словарей фраз/регулярок для обхода тестов.

- Часть «без словарей/регулярок» — подтверждается: DONE-D7 уже VERIFIED (аудит диффа: 0 новых `re.compile`/`def`/`class`/`CREATE TABLE` в runtime); в этом прогоне новых регулярок в проверенных путях не появилось.
- Часть «семантические прогоны действующей модели» — покрыта **частично**: `evidence/probe/results.md` (38/45 платных вызовов, 0 ложных/повторных уточнений, 2 узких уточнения, 3 продолжения; T01–T09, T12, T13, T15, T16, T19, T21, T23, T25 + структурные T27–T31), `evidence/probe-r2/*` (T22, T20 speech A/B, T18b, T26…). По самой карте остаются **9 классов §6 без живого прогона**, прод-статистика `needs_clarification` — `not_instrumented` (прокси `response_act=clarification` 46/324 флаг не заменяет).

Вывод: **закрыть DONE-D6 чтением/локальными тестами нельзя** — недостающая часть требует платных живых прогонов L1/L2 и/или появления реального сообщения на проде (тогда `plan_meta` снимется без доп. работы). Классификация остаётся `WAITING_EXTERNAL`, а не «проверено этим прогоном». Формально для приёмки — **не PASS**.

## 4. MIGR-PAYLOAD — PENDING; «реального старого payload» в репозитории нет

Что искалось: снятый реальный model payload (`messages[]`) допустимого тестового маршрута — в `plans/features/asap2-direct-chat/evidence/**`, фикстурах и `tests/`.
Найдено: **ни одного** снятого `messages[]`-payload (grep `"role": "system"`, `messages[]`, «model payload» по evidence asap2 → 0 совпадений). Есть только:
- `evidence/prod-snapshot/report.md` §4 — эффективные **байты канонов** + выход `build_l2_plan_block` (не payload);
- `evidence/fix-r1/report.md` §B2/T33 — in-process равенство payload Composer ON/OFF (фейковый LLM);
- `plans/features/soul-1/evidence/**` — payload-дампы **другой** фичи (SOUL-1), к канонам ASAP-2 не относятся.

Что есть вместо payload — **старые каноны как константы кода** (`services/chat_prompts.py`, `services/prompt_migrations.py:43-51,145-221`):

| Версия | L1 planner | L2 verbalizer |
|---|---|---|
| OLD (W1, до миграции) | `PREV_DIRECT_L1_PLANNER_W1` — 4641 симв., sha `f8ab20121c02` | `PREV_CHAT_VERBALIZER_W1_31` — 1982 симв., sha `be03964322aa` |
| NEW (действующая) | `DIRECT_L1_PLANNER_SYSTEM_PROMPT` — 8261 симв., sha `6c2ddc17c998` | `DIRECT_VERBALIZER_SYSTEM_PROMPT` — 3081 симв., sha `83ff62bbee40` |

(sha новых канонов совпадают с заявленными в карте/`arch-audit.md`; `be03964322aa` совпадает с `stored_sha` withheld-L2 из `arch-audit.md`.)

Read-only реконструкция маршрута §6.3 #20 (`window`: «Бот, скинь recap чата» → вопрос бота → «сегодня», `build_l1_context` + `build_l2_plan_block(clarification=False)`), 0 обращений к БД/сети:
- NEW: L1-payload 8559 симв. (system 8261 + контекст), L2-payload 3165 симв. (system 3081 + план-блок 84);
- OLD: L1-payload 4939 симв., L2-payload 2066 симв.;
- оба варианта: 0 вхождений `clarify=ask`, 0 «Ничего кроме вопроса», 0 «смысловой акт ответа: clarification» в system и в план-блоке; в NEW L1 канон «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА» — ровно 1 раз;
- в L1-контексте: `[СООБЩЕНИЕ]` ×1, исходная просьба и вопрос бота присутствуют.

Это доказывает **содержимое** эффективных текстов и отсутствие второго model-facing приказа, но не доказывает, что payload реально ушёл в модель: живого L1-вызова (платного) и снятого `messages[]` на проде не было.

Классификация: **AGENT_CHECK** (не решение владельца) — нужен один допустимый реальный L1-turn на тестовом маршруте с дампом `messages[]` без секретов (или первый же реальный диалог на проде, тогда снимается `plan_meta`+payload). Вне рамок этой полосы (запрет прода/Telegram).
Если оркестратору нужна формулировка `OWNER_ACTION`, точный текст: «Нужен один реальный (платный) тестовый диалог в разрешённом тестовом чате: сообщение → уточнение бота → ответ «сегодня»; с диалога снимается фактический `messages[]` L1/L2 и подтверждается, что в нём нет `clarify=ask`/«Ничего кроме вопроса», а правило §4.2 L1 и §4.3 присутствуют. Без этого `MIGR-PAYLOAD` остаётся PENDING».

## 5. MIGR-HOTAPPLY — не выполнялось (требует записи в прод-БД)

По заданию не выполнялось. Что требуется для закрытия: правка промпта через Inspector на проде (запись в БД) → следующий turn без рестарта процесса должен использовать новый effective prompt; снять `effective`/`stored`/`factory` до и после.
Static-часть уже закрыта тестами кандидата (`fix-r1/report.md` §B3/T34: миграция ровно 2 записи, повтор — no-op, откат возвращает прежние байты, кастом владельца не перетирается, `resolve_prompt` отдаёт новые каноны, `FACTORY_SET_SHA256_12 == factory_set_fingerprint()`), плюс ΔDDL=0 (схема БД не менялась). Классификация: **AGENT_CHECK с записью в прод-БД** — вне рамок полосы.

## 6. Итог полосы

| Пункт | Статус после прогона | Основание |
|---|---|---|
| `T24` | **PASS** (service-level) | `tests/test_asap2_clar_contract.py:545-578`, `text2==text`; 24 passed |
| `DONE-D5` | **PASS** (service-level) | `direct_chat_service.py:4470-4473`, `direct_l1.py:992-1001`; 15 + 34 + 24 passed |
| `DONE-D6` | **не PASS** (PENDING/WAITING_EXTERNAL) | 9 классов §6 без живого прогона; прод-статистика not_instrumented |
| `MIGR-PAYLOAD` | **PENDING** | реального payload в репо нет; старые каноны есть (санкции §4), нужен один живой turn |
| `MIGR-HOTAPPLY` | **не выполнялось** | требует записи в прод-БД (вне рамок) |

Замечания к карте (не правились, карта вне скоупа): устаревшие номера строк в evidence `T24` (`:513-546` → `:545-578`) и `DONE-D5` (`:4424-4427` → `:4470-4473`, и «только одно условие» → три условия).

## 7. Команды прогона (воспроизводимо)

```
pytest tests/test_asap2_clar_contract.py -q          # 24 passed in 3.86s
pytest tests/test_addtr_tools_minifix.py -q          # 15 passed in 3.93s
pytest tests/test_asap8_v6_wc_direct_d04.py -q       # 34 passed in 3.30s
```
Интерпретатор: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, cwd = worktree (импорт `services` из worktree проверен).
