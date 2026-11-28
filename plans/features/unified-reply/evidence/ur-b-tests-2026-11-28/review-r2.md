# Независимое пере-ревью UR-B tests-only — r2 (2026-11-28)

**Кандидат:** `ffeaab2450b1ec806126ba041800fbc09d8a76b6` (parent `e63bc50efec05d20cb6b238101f3991a417bded8`)
**База:** `74ef57ef4` (release 2.58.273, задеплоен)
**Вердикт:** **APPROVED_FOR_RELEASE_PREPARATION** — блокирующий F2 закрыт, F1 закрыт, новых блокирующих пробелов нет. Продукт не изменён. Статусы строк: **все четыре — REVIEW**, VERIFIED не предлагается. Деплой не выполнялся и не проверялся.

## Область r2

Проверялись только F2 (blocking) и F1 (minor) из `review-r1.md`; F3/F4 по указанию остаются backlog и повторно не аудировались. Diff `e63bc50ef..ffeaab245`: только `tests/` и evidence; `git diff --stat 74ef57ef4..ffeaab245 -- services` пуст.

## F2 — реальный planner и Writer (закрыт)

В `TestObserverCheckMakesNoSearch` удалены monkeypatch'и `plan_initiative_decision` и `_l2_write_answer`. Сервис собирается с `_InitiativeLLM`: fake только LLM-транспорт (`l1_planner` → `conversation_only`/`not_applicable`-план, `l2_writer` → текст); роутер/провайдер/`observe_tick`/`generate_initiative_reply`/`_l2_write_answer` настоящие. Тест проверяет фактическое исполнение: `planner_llm.steps().count("l1_planner") == 1`, `"l2_writer" in steps`, `bot.sent`, `status == "completed"`, и 0 поисков по двум каналам (`search.queries == []`, `aggregated == []`), плюс `stage["calls"] == 0` для `_dx.run_tool_phase`.

**Независимые контр-мутации (все RED, затем `git checkout --`):**
- поиск в **реальной** `DirectChatService.plan_initiative_decision` → `search.queries == ['planner-mutation']`, тест FAILED (`test_ur_b_observer_no_search.py:229`);
- поиск в **реальном** `generate_initiative_reply` (Writer-стадия) → `search.queries == ['writer-mutation']`, тест FAILED;
- поиск в `observe_tick` → `['observer-mutation']`, тест FAILED.
После каждой мутации `git status --porcelain` пуст. Это закрывает именно тот counterexample, который был в r1.

**Нет новой маскировки:** fake LLM не содержит поисковых вызовов и не подменяет проверяемую логику; `_SearchProvider` и `SearchAggregator.search` — реальные счётчики; `_dx.run_tool_phase` обёрнут, а не заменён; `choose_conversation_alternative` по-прежнему мок только для детерминизма участия и сам поиск не выполняет.

## F1 — порядок «runtime state → TurnRequest → planner» (закрыт)

Добавлен `test_turn_request_binds_runtime_state_before_planner_call`: slim runtime-набор → реальный `_build_turn_request` → `req.tool_state.search_available is False`, `req.capabilities == req.tool_state.capabilities`; затем `_execute_turn` с `record_turn_trace`, fake-LLM внутри planner'а проверяет `captured["req"] is req` и отсутствие `web_search` **до** возврата плана. Это ассерт порядка, а не docstring.

**Мутация:** `_resolve_turn_tool_state.search_available` → `True` даёт RED в обоих provider-state тестах (`test_turn_tool_state_is_the_runtime_provider_set` и новый `test_turn_request_binds_runtime_state_before_planner_call`). Откат чистый.

## Прогоны (независимо)

- Новые/исправленные: **10 passed**.
- Смежные UR-B: **152 passed**; selection/ledger: **79 passed**; direct/context: **311 passed**.
- Observer-наборы: **53 passed, 4 failed** — те же предсуществующие падения, что на базе `74ef57ef4` (`test_opportunity_carries_context_into_writer_and_sends`, `test_pending_direct_request_stops_observer_initiative`, `test_day_cap_still_hard_with_soft_target`, `test_initiative_writer_shares_core_style_and_persona`); к r2 не относятся.
- `--collect-only`: **10 collected**.
- Мутации: **9/9 RED** — M1 dedup, M2 error_type, M3 provider state (2 теста), M4 L1 source refs, M5 SILENT/REACT, M6 observer direct search, M7 bot_output marker, M8 real planner search, M9 real Writer search. Каждая с откатом; дерево чистое.
- `git diff --stat 74ef57ef4..ffeaab245 -- services` пуст; изменены только тесты/evidence.

## Остаточные наблюдения (не блокеры)

- **R2-O1 (BACKLOG/Minor):** r2 убрал явный ассерт `seen["evidence"] == ""` и точный счётчик вызова Writer из r1. Инвариант «0 поисков» покрыт каналами + `stage["calls"] == 0`; если evidence-проводка Writer'а входит в дальнейший scope, полезно добавить ассерт на реальные сообщения `l2_writer`.
- **R2-O2 (BACKLOG/Minor):** реальные planner/Writer исполняются с `FakeMemory(window=[])`, а не с seeded DB; на no-search инвариант это не влияет, но «полный контекст» observer-прохода не проверяется. Если нужна контекстная интеграция — передать seeded memory.
- F3/F4 не переаудировались; остаются backlog, как указано.

## Ограничения

- UR-04.3: live L1 всё ещё не принимает объект `ContextSelection`; доказан контракт на шве (UR-C/UR-D).
- UR-14.1: у `ContextFragment` нет `chat_id`; принадлежность чату доказывается ledger-строкой и chat-scoped read-path; литерал `source=bot_output` — `thread_chain.source_kind` + `source_id=bot_output:<id>`.
- UR-06.5: real planner/Writer с fake LLM-транспортом; F2 закрыт контр-мутациями; live production observer не запускался.

## Рекомендация по статусам (карта не правилась)

| Строка | Статус | Причина |
|---|---|---|
| UR-03.1 | **REVIEW** | F1 закрыт; dedup/error/provider state/tool trace покрыты; F4 (cached source_ids) — backlog. |
| UR-04.3 | **REVIEW** | идентичность source refs на шве; живое подключение — UR-C; строка UR-D. |
| UR-06.5 | **REVIEW** | F2 закрыт: real planner/Writer, 0 поисков по двум каналам, `run_tool_phase` не вызывался; остаются R2-O1/O2. |
| UR-14.1 | **REVIEW** | ledger/read-path/thread chain/L2 materialization покрыты; нет `chat_id`, живой ход — UR-C/UR-23. |

VERIFIED ни по одной строке не предлагается. Деплой не заявляется. Повторное ревью не требуется для F2/F1; дальнейшие изменения — только при новом материальном основании.