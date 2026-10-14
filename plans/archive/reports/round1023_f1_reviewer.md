# Отчёт @Reviewer — раунд 10.23, Фича F1 `target-message-marking-round1023`

> **ИТОГОВЫЙ СТАТУС (итерация 2, коммит `7fc0e55`): ✅ Approved.**
> Итерация 1 (коммит `9ff836d`): ❌ Changes Requested — 1 High / 3 Medium / 4 Low. Все замечания закрыты (см. §3),
> остаточные риски — Low/Info, не блокирующие.
>
> **Ревьюер:** @Reviewer (Senior Principal Engineer, качество/безопасность/архитектура/прод-готовность).
> **Дата:** 19.09.2026. **Шаг:** 5 (строгий аудит) + итерация 2.
> **Коммит:** `9ff836d` (`feat(services,handlers,tests): раунд 10.23 F1 …`) + `7fc0e55` (review iter1). Baseline HEAD `731a845`.
> **Объём:** 22 файла, +816/−61. Новый `services/target_marking.py`, маркировка в `summary_xml.py`/`canonical_context.py`/`chat_context.py`,
> проводка в `summary.py`/`factcheck.py`/`summary_generator.py`/`direct_chat_service.py`, правило в 3 Stage-1 промптах, канон-миграции, тесты.
> **Метод:** чтение `spec.md`/`ADR-1023-1.md`/`tasks.md`/`round1023-architecture.md`; `git show --stat`; полный `git diff 9ff836d^ 9ff836d`;
> адресные чтения всех call-site; инструментальная проба рендера `_render_thread`; целевой + регрессионный + полный pytest.

---

## Status: **Changes Requested**

Фича в целом сделана сильно: legacy-путь байт-в-байт сохранён, XML well-formed, канон-миграция добавлена, полный pytest зелёный.
Но заявленный инвариант **«маркер ставится ровно на одном сообщении»** на прямом чате **нарушен гарантированно** (маркер попадает в 2–3 блока сразу),
а тест «антиэхо», на который ссылается спека как на защиту от утечки маркера в финал, **не проверяет ничего** — это `assert` о литерале.

**Сводка:** 0 Critical / **1 High** / **3 Medium** / **4 Low** / 1 Info.

| Sev | Кол-во | Коды |
|---|---|---|
| Critical | 0 | — |
| High | 1 | R1023F1-01 |
| Medium | 3 | R1023F1-02, R1023F1-03, R1023F1-04 |
| Low | 4 | R1023F1-05…08 |

**Тесты (запущено самостоятельно, виртуальное окружение `.venv`, Python 3.12):**
- Целевой набор `test_target_marking_round1023 + test_direct_chat_prompts + test_prompt_migrations + test_summary_handlers` → **136 passed / 0 failed**.
- Регресс `test_summary_xml + test_memory_core_round1020 + test_summary_two_call_round1022 + test_factcheck_two_call_round1022 + test_direct_two_call_round1022 + test_outgoing_guard_round1022` → **137 passed / 0 failed**.
- Полный `pytest -q` → **6986 passed / 0 failed**, 1 warning (стороннее `StarletteDeprecationWarning`). Заявленное число подтверждено.

---

## 1. Находки

### R1023F1-01 — **High** — маркер дублируется в прямом чате (инвариант «ровно на одном» нарушен)

**Файл:** `services/direct_chat_service.py`
**Локация:** `_build_user_content` — `:982` (триггер), `:995-998` (`branch`), `:1000-1002` (`global`), `:1011-1015` (`thread`);
`_context_row_line` `:2407-2424`; `_chain_line` `:2481-2498`; `_render_thread` `:2516-2547`; `_render_branch` `:2549-2560`.

**Проблема.** Один и тот же `trigger_message_id` передаётся в **несколько независимых сборок** одного и того же контекста:
1. `_collect_thread_chain` (`:2444-2445`) стартует **от текущего сообщения**, поэтому цепочка всегда содержит триггер (для обычного, не-reply сообщения `chain == [текущее]`).
2. `_render_thread` (`:2516`) безусловно рендерит цепочку → триггер попадает в `<Conversation_Thread>`.
3. `_build_global_context` (`:2328-2347`) рендерит окно, в котором уже лежит текущее сообщение (observer сохраняет его до хендлера) → триггер попадает ещё и в `<Global_Context>`.
4. Для reply-триггера добавляется `_render_branch` (`:995`) → тот же триггер третий раз.

Итог: **на каждом прямом сообщении** в промпт уходит ≥2 маркера (`global` + `thread`), для reply-триггера — 3.
Инструментально подтверждено: `_render_thread` с цепочкой из одного текущего хода выдаёт `&lt;&lt;&lt; [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` внутри `<Conversation_Thread>`.

Это прямо противоречит `spec.md` §2.2 («Маркер ставится **ровно на одном** сообщении») и `ADR-1023-1` (R3), и обесценивает
de-dup, который Builder аккуратно сделал в XML (`remaining_trigger`, `summary_xml.py:71-83`) и в `chat_context` (`chat_context.py:41,57-58`).
Поскольку прямой чат — самая горячая точка, «крайним случаем» это не является.

**Why it matters.** Модель получает противоречивую разметку: «вот твоя команда» в трёх местах. Это не роняет систему, но:
(а) размывает однозначность указателя — ровно тот симптом, который фича лечила; (б) тратит токены на дубли; (в) нарушает
приёмочный критерий спеки, т.е. формально фича не принята.

**Required fix.** Ввести сквозной «расход триггера» на время сборки `_build_user_content`: маркировать ровно один блок
(предлагаю `<Global_Context>` как единственный «исторический» контекст; `thread`/`branch` — вспомогательные и должны получать `trigger_message_id=None`),
либо прокидывать изменяемый флаг «уже помечено» и не маркировать повторно. Добавить тест: на одном вызове `_build_user_content`
суммарное число маркеров (и `<<<`, и `&lt;&lt;&lt;`) во всех блоках **ровно 1**.

---

### R1023F1-02 — **Medium** — проводка T-2100 в прямом чате не покрыта ни одним тестом

**Файл:** `tests/` (отсутствие), `services/direct_chat_service.py:982`.
**Проблема.** `grep` по `tests/` не находит **ни одного** упоминания `trigger_message_id`/`is_target_row`/`TARGET_MARKER`
в тестах прямого чата. `tests/test_target_marking_round1023.py` проверяет только `format_context_item`, `format_chat_context` и XML —
то есть две трети проводки (`_build_user_content`, `_context_row_line`, `_chain_line`, `_render_thread`, `_render_branch`) не проверены.
**Why it matters.** Любая регрессия проводки (убрали `trigger_message_id` из `_render_thread`, поменяли `getattr` на несуществующий атрибут,
сломали `f"tg:{...}"`) пройдёт CI незамеченной: тесты «зелёные», фича в проде молча не работает. Для P0-фичи это недопустимо.
**Required fix.** Добавить прямые тесты методов `DirectChatService`: `_context_row_line(row, …, trigger_message_id=N)` даёт ровно один маркер при совпадении
и legacy при `None`; `_chain_line`/`_render_thread`/`_render_branch` маркируют ход-триггер; `_build_user_content` (с мок-`self`) — суммарно один маркер.

---

### R1023F1-03 — **Medium** — «антиэхо»-тест ничего не проверяет; жёсткой защиты от утечки маркера в финал нет

**Файл:** `tests/test_target_marking_round1023.py:194-200`; `services/outgoing_guard.py` (не тронут).
**Проблема.** `test_final_text_has_no_marker_artifacts` делает `assert TARGET_MARKER not in "<произвольная захардкоженная строка>"` —
это тавтология, она пройдёт даже если антиэхо не существует вовсе. При этом `sanitize_outgoing` (egress-guard раунда 10.22)
чистит только `<thought>`, `fact:ID`, `msg:ID` — **маркер им не вычищается**. Stage-2 (Нарратор/Вербализатор) получает вывод Stage-1 как вход;
если Редактор проэхоит `<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` в выжимку, ничто не мешает этому дойти до пользователя.
**Why it matters.** `spec.md` §2.4/§7 и `ADR-1023-1` R2 заявляют «маркер не протекает в финальный пользовательский текст» как приёмочный критерий.
Сейчас это утверждение не подкреплено ни рантайм-защитой, ни осмысленным тестом — риск утечки служебной разметки в лицо пользователю.
**Required fix.** Либо добавить паттерн `TARGET_MARKER_CORE`/`<<<` в `sanitize_outgoing` (defense-in-depth, идемпотентно),
либо заменить тест на реальный: подать на вход Stage-2 вывод Stage-1, содержащий маркер, и доказать, что он не доходит до отправки.
Текущий `assert` о литерале удалить.

---

### R1023F1-04 — **Medium** — для `/summary` триггер мёртв всегда, а комментарий говорит «обычно»

**Файл:** `handlers/summary.py:288` (комментарий `:285-286`); `handlers/summary.py:169-171` (observer).
**Проблема.** Observer (`summary_observer`) явно отбрасывает сообщения, начинающиеся с `/summary`, и **никогда их не сохраняет**.
Значит `message.message_id` команды `/summary` заведомо не совпадёт ни с одним `smart_messages.tg_message_id`,
и передаваемый `trigger_message_id` — гарантированно висячий id. Фактически F1 для саммари — **no-op на 100%**,
тогда как комментарий утверждает «обычно legacy-путь», а `spec.md` §9 — «может отсутствовать».
**Why it matters.** Основной сценарий из ТЗ («пересказ собственной команды» в саммари) фичей не закрывается; вводит в заблуждение
и приёмку, и последующие фичи (F2/F3 опираются на F1 как на ядро контекста).
**Required fix.** Принять явное решение и зафиксировать его в спеке/ADR: (а) сохранять команду в `smart_messages` (или отдельный
`trigger_id` в контексте генерации) — тогда фича работает; (б) либо честно записать в спеке `T-2106` «для саммари маркер недостижим без
отдельного носителя триггера» и убрать вводящий в заблуждение комментарий. Молча оставлять как есть — нельзя.

---

### R1023F1-05 — **Low** — `append_marker` дедуплицирует только полный токен

**Файл:** `services/target_marking.py:56-66`.
**Проблема.** Проверка `if TARGET_MARKER in text` не ловит тело, уже содержащее `TARGET_MARKER_CORE` (пользователь буквально написал
`[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]`) → маркер наклеится вторым. `append_marker("   ")` даёт `"   <<< …"` (нет `.strip()`).
**Required fix.** Дедуплицировать по `TARGET_MARKER_CORE`, пустое/пробельное тело — трактовать как пустое.

### R1023F1-06 — **Low** — `_chain_line` использует другой контракт сопоставления, чем `is_target_row`

**Файл:** `services/direct_chat_service.py:2493-2494`.
**Проблема.** `is_target_row` защищается от `None/""/0` и сравнивает `int`, а `_chain_line` — `trigger_message_id is not None` + строковое `== f"tg:{id}"`.
`trigger_message_id=0` (или строка) ведёт себя по-разному в двух рендерерах одного и того же контекста.
**Required fix.** Переиспользовать единый матчер/нормализацию id (или хотя бы тот же guard `in (None, "", 0)`).

### R1023F1-07 — **Low** — обратный шаг канона для чата не ведёт на `PREV_CHAT_R1023`

**Файл:** `services/prompt_migrations.py:143-144` (`ROLLBACK_MIGRATIONS`), `:96` (migrate-ступень `PREV_CHAT_R1023 → CHAT`).
**Проблема.** Для двух новых ключей откат добавлен корректно, а для `prompts.direct_chat_system_prompt` откат по-прежнему
уходит в `PREV_CHAT_R1021_SYSTEM_PROMPT` — т.е. снимает не только F1, но и стилевые блоки 10.21/10.22.
`spec.md` §3.6/§8 и `ADR-1023-1` §8 требуют обратимости F1-миграции.
**Required fix.** Добавить обратный шаг `(CHAT_SYSTEM_PROMPT → PREV_CHAT_R1023_SYSTEM_PROMPT)` и тест на него
(или явно задокументировать кумулятивную семантику отката «до R1021», но тогда честно назвать это не «обратимостью F1»).

### R1023F1-08 — **Low** — расхождения кода и таблицы файлов спеки

**Файл:** `plans/features/target-message-marking-round1023/spec.md:77-103`.
**Проблема.** `TARGET_INSTRUCTION_BLOCK` размещён в `services/target_marking.py` (спека §3.5 называет `prompt_style_blocks.py` либо инлайн);
`handlers/direct_chat.py` из таблицы §4 не менялся (и правильно — id взят внутри сервиса, `§3.4`). Функционально эквивалентно, но канон-доки расходятся с кодом.
**Required fix.** Синхронизировать `spec.md`/`plans/docs/canon/architecture.md` с фактическим размещением блока и убрать строку про `handlers/direct_chat.py`.

### R1023F1-09 — **Info** — комментарий `summary.py:285-286` вводит в заблуждение («обычно legacy» → «всегда legacy»)

См. R1023F1-04; правка текста комментария обязательна вместе с решением по носителю триггера.

---

## 2. Явная проверка контракта

**Спека/ADR:**
- ✅ Маркер ровно на одном совпадении по `tg_message_id` — **в XML и `chat_context`** (дедуп `remaining_trigger`); ❌ **в прямом чате** — см. R1023F1-01.
- ✅ `trigger_message_id=None` → рендер **байт-в-байт legacy** (тесты `test_legacy_none_byte_for_byte`, `test_no_match_legacy_byte_for_byte`, `test_default_false_is_legacy`, `test_chat_context_no_match_legacy`).
- ✅ XML: маркер дописывается **до** `_escape` (`summary_xml.py:101-105,116`), вывод well-formed (`ET.fromstring`), `&lt;&lt;&lt;`.
- ✅ Plain: сырой `<<<` (`format_context_item`).
- ✅ Ядро `[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` — escape-стабильно (`target_marking.py:29-33`).
- ✅ Промпт-правило в 3 Stage-1 (`SUMMARY_EDITOR`/`FACTCHECK_ANALYST`/`CHAT`); в вербализаторах отсутствует.
- ✅ `format_fact_line` не тронут; `is_target` применяется только при `kind == "msg"`.
- ⚠️ Канон-миграция атомарна (слепки `PREV_*_R1023`, migrate + rollback + `plans/docs/canon/**` + тесты одним коммитом); откат чата не на R1023 (R1023F1-07).

**Инварианты:**
- ✅ Нет новых LLM-вызовов; `services/system2_handoff.py`/`two-call` пайплайн не затронут (в diff отсутствуют).
- ✅ Новых точек отправки нет; `test_every_send_point_is_registered_or_allowlisted` + `test_migrated_modules_have_no_bare_sends` зелёные.
- ✅ R16/R17/R18 — сырой текст/секреты не логируются (в diff нет новых `logger.*` с телом сообщений); маркер секретов не содержит.
- ✅ `parse_mode=None` не менялся (send-пути не трогались).
- ✅ Δ каталога = 0, DDL = 0.

**Тесты:**
- ✅ `test_target_marking_round1023.py` — токен, matcher, XML (единственный маркер, legacy-байты, well-formed, дубль→первый), plain (сырой `<<<`, только `msg`), паритет, `chat_context`, промпты/антиэхо.
- ✅ Байт-эталоны `test_summary_xml.py` / `test_memory_core_round1020.py` не потребовали правок — legacy-путь реально сохранился (это плюс, а не пропуск T-2103).
- ❌ Нет тестов проводки прямого чата (R1023F1-02).
- ❌ «Антиэхо»-тест тавтологичен (R1023F1-03).
- ✅ Полный pytest — 6986 passed / 0 failed.

**tasks.md:**
- ✅ `T-2097…T-2105` — `[x]`; `T-2106` (DevOps деплой/живая приёмка) — `[ ]`, ожидаемо.
- ⚠️ `T-2103` отмечен `[x]` без правок эталонов — обосновано (legacy байт-в-байт), но стоит зафиксировать причину в tasks.md.

---

## 3. Что обязан исправить @Builder (точный список)

1. **R1023F1-01 (High):** устранить дублирование маркера в прямом чате — маркировать ровно один блок на всю сборку `_build_user_content`; добавить тест «суммарно ровно один маркер».
2. **R1023F1-02 (Medium):** покрыть тестами проводку `_context_row_line` / `_chain_line` / `_render_thread` / `_render_branch` / `_build_user_content` (legacy при `None`, маркер при совпадении).
3. **R1023F1-03 (Medium):** либо добавить маркер в `sanitize_outgoing` (egress-scrub), либо заменить тавтологичный антиэхо-тест на реальную проверку границы Stage-1 → отправка.
4. **R1023F1-04 (Medium):** принять решение по носителю триггера для `/summary` (сохранять команду/триггер или честно задокументировать no-op) и исправить вводящий в заблуждение комментарий.
5. **R1023F1-05…08 (Low):** дедуп `append_marker` по ядру; единый guard в `_chain_line`; обратный шаг канона чата на `PREV_CHAT_R1023` + тест; синхронизация `spec.md`/канона с фактическим размещением блока.

После правок: полный pytest 0 failed + повторный аудит @Reviewer.

---

**Верни исправленную версию. Текущий код отклонён.**

---
---

# Итерация 2 — повторный аудит (коммит `7fc0e55`)

> **Объём итерации:** 11 файлов, +274/−39; `services/direct_chat_service.py`, `services/target_marking.py`,
> `services/outgoing_guard.py`, `services/prompt_migrations.py`, `handlers/summary.py`, spec/tasks/canon, тесты.
> **Метод:** `git show 7fc0e55 --stat` + `git diff 9ff836d 7fc0e55` (полный); адресные чтения egress-контура
> (`outgoing_guard.py` → `telegram_send.py` → `smartmodule_utils._send_once`); инструментальные пробы:
> regex-fuzz `sanitize_outgoing` (no-op/idempotency/edge), сборка `_build_user_content` в prod-реалистичных сценариях
> (ordinary с непустой цепочкой + reply) с подсчётом маркеров; целевой + полный pytest.

## Status: **Approved**

Все High/Medium из итерации 1 закрыты **по существу, а не маскировкой** — проверено кодом и инструментально.
Остаточные наблюдения — Low/Info, не блокируют приёмку.

**Тесты (прогон выполнен):**
- Целевой F1 + смежные (`test_target_marking_round1023` + `test_direct_chat_prompts` + `test_prompt_migrations` + `test_summary_handlers` + `test_outgoing_guard_round1022`) → **175 passed / 0 failed**.
- Полный `pytest -q` → **7003 passed / 0 failed**, 1 warning (сторонний `StarletteDeprecationWarning`). Заявленное число подтверждено.

## 3.1. Проверка закрытия findings итерации 1

| ID | Sev | Статус | Доказательство |
|---|---|---|---|
| R1023F1-01 | High | ✅ CLOSED | `_build_user_content` передаёт триггер только в `_build_global_context` (`direct_chat_service.py:1004-1005`); `_render_branch:998`/`_render_thread:1014` вызываются **без** триггера. Инструментально (prod-реалистично, `FakeDB` с строками): ordinary-сообщение с непустой цепочкой → ядро встречается **1** раз (в `<Global_Context>`), reply → **1** раз. Добавлены тесты `test_build_user_content_single_marker_ordinary/reply/no_trigger`. |
| R1023F1-02 | Medium | ✅ CLOSED | Добавлен `TestDirectChatWiring`: `_context_row_line`, `_chain_line`, `_render_thread`, `_render_branch`, `_build_user_content` (ordinary/reply/no-trigger). Хелперы взяты из `tests/test_direct_chat.py` (кросс-импорт — устоявшийся паттерн репо). |
| R1023F1-03 | Medium | ✅ CLOSED | `sanitize_outgoing` режет `<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]` и ядро (`_TARGET_MARKER_RE`). Тавтологичный `test_final_text_has_no_marker_artifacts` удалён; добавлен `TestEgressScrub`, включая `test_stage1_echo_does_not_reach_user` (реальный вызов функции на маркер-содержащем тексте). Egress реально применяется к direct/summary/factcheck: `send_chunked_reply` → `smartmodule_utils._send_once` → `telegram_send.send_text` → `sanitize_outgoing`. |
| R1023F1-04 | Medium | ✅ CLOSED (как задокументированное ограничение) | Комментарий `handlers/summary.py:284-289` исправлен («НЕДОСТИЖИМ, всегда legacy»); `spec.md §9` переписан в «ЗАКРЫТО (R1023F1-04)»; примечание в `tasks.md`. Продуктовое решение, зафиксировано осознанно. |
| R1023F1-05 | Low | ✅ CLOSED | `append_marker` дедуплицирует по `TARGET_MARKER_CORE`, пробельное тело → как пустое; тесты `test_append_marker_dedup_by_core`/`_whitespace_body_is_empty`. |
| R1023F1-06 | Low | ✅ CLOSED | Введены `normalize_trigger_id` + `is_target_item_id`; `_chain_line:2496` переведён на единый матчер; guard `0/""/None` унифицирован; тесты. |
| R1023F1-07 | Low | ✅ CLOSED | `ROLLBACK_MIGRATIONS["prompts.direct_chat_system_prompt"]` → `PREV_CHAT_R1023_SYSTEM_PROMPT` (`prompt_migrations.py:145-146`); тесты `test_rollback_chat_targets_r1023` + `test_rollback_chat_restores_r1023`. |
| R1023F1-08 | Low | ✅ CLOSED | `spec.md §3.5/§4` и `plans/docs/canon/{architecture,backlog}.md` синхронизированы с фактическим размещением `TARGET_INSTRUCTION_BLOCK` в `services/target_marking.py` и с тем, что `handlers/direct_chat.py` не меняется. |

## 3.2. Проверка регрессии egress-scrub (R1023F1-03)

Инструментальные пробы `sanitize_outgoing` (guard ON, `parse_mode` зарезервирован, обхода нет):
- ✅ **No-op байт-в-байт** на легитимном тексте без маркера (URL, двоеточия, цифры, `a << b >> c <<< <<<<<`, `1 <<< 2`) — не меняется.
- ✅ Одиночный `<<<` **без** ядра не вырезается (нет ложного срабатывания на обычные угловые скобки).
- ✅ Полный токен и «голое» ядро вырезаются; сохранён остальной контент; `<<<` не остаётся.
- ✅ Стык нормализуется до одного разделителя (`"  "` не остаётся); в середине → `"до после"`.
- ✅ **Идемпотентность** подтверждена на всех пробах.
- ⚠️ Единственный краевой эффект: при вставке ядра **без пробелов** (`x[CORE]y`, `[[CORE]]`) соседние символы могут слипнуться (`xy`, `[]`). Для технического токена это допустимо (Low, см. §3.3).

## 3.3. Остаточные находки итерации 2 (не блокирующие)

| ID | Sev | Файл:строка | Суть | Рекомендация |
|---|---|---|---|---|
| R1023F1-09 | Low | `services/direct_chat_service.py:2519-2522, 2552-2553` | `trigger_message_id` у `_render_thread`/`_render_branch` теперь **не передаётся в прод-пути** (мёртвый параметр), а докстринги по-прежнему гласят «10.23 (F1): ход-триггер получает маркер» — вводят в заблуждение. Путь достижим только из тестов, `is_target_item_id` в проде фактически не востребован. | Либо удалить параметр из `_render_thread`/`_render_branch` и перенести проверку матчера целиком в тесты `target_marking`, либо поправить докстринги («параметр сохранён для паритета/тестов; в проде триггер расходуется в `<Global_Context>`»). |
| R1023F1-10 | Low | `services/outgoing_guard.py:43-45` | При вставке ядра без пробелов regex может склеить соседние слова (`x<<<[CORE]y` → `xy`). Для технического токена риск пренебрежим, но при желании — сохранять разделитель, если хотя бы с одной стороны есть непустой контекст. | Опционально: возвращать `" "` при наличии любого соседнего символа, не только при пробелах с двух сторон. |
| R1023F1-11 | Info | `plans/features/target-message-marking-round1023/spec.md §9` | Флагманский сценарий ТЗ (пересказ собственной `/summary`-команды) остаётся незакрытым по решению «вне F1». Ограничение задокументировано, но **отдельной задачи/строки в backlog на носитель триггера саммари нет** — риск, что гэп потеряется. | Завести follow-up-задачу (в `plans/backlog.md`) на «носитель триггера для `/summary`» — вне F1, но с traceability. |
| R1023F1-12 | Info | `tests/test_target_marking_round1023.py:305-313` | Отдельный тест «ordinary single marker» использует пустой `FakeDB`, поэтому цепочка пуста и блок `<Conversation_Thread>` не рендерит текущий ход (не самый горячий вариант). Сам инвариант закрыт структурно (thread/branch не получают триггер) — проверено независимой инструментальной пробой с непустой цепочкой → 1 маркер. | Опционально дополнить тест `FakeDB(rows={100: row})`, чтобы зафиксировать именно прод-реалистичный случай. |

## 3.4. Инварианты итерации 2

- ✅ **Нет новых LLM-вызовов** — diff затрагивает только `outgoing_guard`/`target_marking`/`direct_chat_service`/`prompt_migrations` + доки/тесты; `system2_handoff`/two-call пайплайн не тронут.
- ✅ **Нет новых точек отправки** — `SEND_POINTS`/`SEND_ALLOWLIST` не расширялись; `test_outgoing_guard_round1022` (покрытие реестра) зелёный.
- ✅ **R16/R17/R18** — новых логов с сырым текстом/секретами нет; egress fail-closed логирует только длины.
- ✅ **`parse_mode=None`** — не менялся; сигнатура `sanitize_outgoing(..., parse_mode=None)` зарезервирована, обхода guard нет.
- ✅ **Байт-в-байт legacy** при `trigger_message_id=None` — подтверждено тестами XML/`chat_context`/`canonical_context`.
- ✅ **Канон-обратимость** — откат чата теперь снимает только F1 (`PREV_CHAT_R1023`), сохраняя блоки A/B 10.21/10.22.

## 3.5. Вердикт итерации 2

Итерация 1 закрыта полностью: High (дубль маркера) снят структурно и подтверждён инструментально «ровно 1 маркер» в ordinary/reply;
Medium (тесты проводки, антиэхо, `/summary`-ограничение) закрыты адекватно; Low (дедуп, guard, откат, доки) — исправлены.
Регрессий в egress-scrub нет (no-op байт-в-байт, идемпотентность, без ложных срабатываний на `<<<`).
Полный pytest **7003/0**.

**Approved @Orchestrator — код прошёл ревью. Можно двигаться к T-2106 (деплой + живая приёмка).**
Остаточные Low/Info (R1023F1-09…12) — рекомендации, не блокируют; R1023F1-11 желательно закрыть отдельной задачей в backlog.
