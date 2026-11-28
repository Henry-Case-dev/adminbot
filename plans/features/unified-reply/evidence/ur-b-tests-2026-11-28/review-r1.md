# Независимое ревью UR-B tests-only — r1 (2026-11-28)

**Кандидат:** `e63bc50efec05d20cb6b238101f3991a417bded8` (ветка `feat/ur-b-testonly-2026-11-28`)
**База:** `74ef57ef4` (release 2.58.273, задеплоен)
**Вердикт:** **NEEDS_FIXES** — один блокирующий пробел в доказательстве UR-06.5 (observer-тест не исполняет реальный participation-decision, поэтому поиск на этом шве не виден). Остальные проверки инкремента прошли; продукт не изменён. Статусы строк: **все четыре — REVIEW**, VERIFIED не предлагается. Деплой не выполнялся и не проверялся.

## Независимая проверка

- `git diff --name-status 74ef57ef4..e63bc50ef`: только 3 новых тестовых файла и evidence; продуктовый diff за пределами `tests/`/`plans/` пуст.
- Новые тесты: **9 passed** (все 9, включая 2 параметра SILENT/REACT).
- Смежные UR-B: **152 passed**; selection/ledger: **79 passed**; direct/context: **311 passed**.
- `--collect-only`: **9 tests collected**.
- Observer-наборы: **53 passed, 4 failed** на кандидате; те же 4 падения воспроизведены на чистом `74ef57ef4`, извлечённом `git archive` (без новых файлов): `test_opportunity_carries_context_into_writer_and_sends`, `test_pending_direct_request_stops_observer_initiative`, `test_day_cap_still_hard_with_soft_target`, `test_initiative_writer_shares_core_style_and_persona`. К кандидату не относятся; причина — `_StubService` без `_writer_evidence_capacity` и soul1-gate.
- Перенесённый observer-тест не ослаблен: в `ur/b-evidence@6099cc17` тот же класс и те же ключевые ассерты (`status=="completed"`, writer вызван, отправка есть, оба канала поиска пусты, `stage["calls"]==0`). Новый файл добавляет только детерминизм `choose_conversation_alternative` и локальные хелперы; удалённых/ослабленных проверок нет.

## Мутации (независимо, по одной на строку)

Каждая мутация — временная правка tracked-продукта, затем `git checkout -- <file>`; после каждой `git status --porcelain` пуст.

| Строка | Мутация | Результат |
|---|---|---|
| UR-03.1 dedup | `_dispatch_step`: `cached_reason = budget.dedup_skip(...)` → `""` | RED: провайдер вызван дважды, `test_duplicate...:184` |
| UR-03.1 error_type | `_tool_events_from`: `error_type` → `""` | RED: `test_error...:235`, нет «поиск недоступен» |
| UR-03.1 provider state | `_resolve_turn_tool_state`: `search_available=(...)` → `True` | RED: slim-набор всё ещё `True`, `test_turn_tool_state...:115` |
| UR-04.3 source refs | `allocate_window_projection`: `source_id = str(frag.source_id)` → `f"win:{index}"` | RED: L1 refs ≠ L2 refs, `test_l1_and_l2...:304` |
| UR-06.5 SILENT/REACT | `run_tool_phase`: early-return `("silent","react")` → `("__never__",)` | RED: оба параметра, провайдер вызван, `:44` |
| UR-06.5 Observer | `observe_tick`: прямой `writer_service.tool_router.deps.search.search("observer-mutation")` | RED: `search.queries` непуст, `:206` |
| UR-14.1 bot_output | `ledger_record_to_fragment`: `bot_output:` → `self_output:` | RED: `source_id` не тот, `test_ur_14...:102` |

Все 7 мутаций RED; откат чистый. Это подтверждает, что тесты не тавтологичны и падают на реальном нарушении контракта.

### Контр-мутация (oracle counterexample) — блокер

В **реальную** `DirectChatService.plan_initiative_decision` (участие/decision-стадия observer-прохода) временно вставлен прямой вызов `await self.tool_router.deps.search.search("planner-mutation")` (в `try/except`). `tests/test_ur_b_observer_no_search.py::TestObserverCheckMakesNoSearch` остался **GREEN** (`1 passed`): тест monkeypatch-ит `service.plan_initiative_decision`, поэтому реальный planner не исполняется и ни один из двух поисковых каналов не видит вызов. Откат чистый. Это прямой контрпример к утверждению теста «проверка Observer'а целиком ... не делает ни одного поискового вызова» и к формулировке implementation.md «L1 ... не подменяется».

## Что проверено по строкам

- **UR-03.1.** `_resolve_turn_tool_state` вызывается на живом сервисе; `search_available`/capabilities берутся из фактического `active_tools_for_chat` (в т.ч. урезанный набор). `run_tool_phase`/`run_simple_tools`/`ToolRouter` реальные; dedup, `duplicate`, `attempt`, `duration_ms`, `error_code/error_type`, `tool_trace` и отсутствие `data`/`args_fingerprint` проверяются по фактическому `raw.tool_results`. Мок только `derive_simple_steps` (форсирует два шага) — это не проверяемая логика dedup.
- **UR-04.3.** Один набор строк проходит через живые `allocate_window_projection` + `build_l1_context` и `_build_l2_selection_candidates` + `_materialize_selection`; идентичность `msg:<tg>` и различие форматов/бюджетов проверены. Это **шов**, а не живое подключение `ContextSelection` к L1; тест это не заявляет сверх доказанного.
- **UR-06.5.** SILENT/REACT: живой `_l1_tool_phase` с `open_world/required`/capability `web_search` даёт 0 вызовов и `raw is None` — корректно. Observer: живой `observe_tick`, живая БД, реальные `_evidence_preflight`/`_l1_tool_subset`/`_l1_tool_phase`/`ToolRouter` в `generate_initiative_reply`; поиск наблюдается двумя каналами; `_dx.run_tool_phase` не вызывается; Writer получает пустой evidence. Но `plan_initiative_decision` (L1/decision) и `_l2_write_answer` (Writer) замоканы; `choose_conversation_alternative` замокан только для детерминизма и сам поиск не выполняет. См. F2.
- **UR-14.1.** Реальные write-path ledger (`record_delivered_output`), read-path (`list_bot_output_history`), `collect_self_output_fragments`, `collect_thread_chain`, живой L2-producer и канонический материализатор: проверены `chat_id`, `tg_message_id`, `sent_at`, parent, ревизия, `correlation_id`, `delivery_status`, `source_kind=="bot_output"`, `source_id=="bot_output:<id>"`, `KIND_BOT_STATEMENT`/`ROLE_SELF_OUTPUT`.

## Findings

### UR-B-R1-F1 — UR-03.1: тест не связывает состояние с конструктором TurnRequest/порядком «до планирования» (IN_SCOPE, Minor, не блокер)
- **Ожидалось:** проверка acceptance «права/состояние вычисляются до планирования» через `_build_turn_request`/`TurnRequest` (или явная формулировка, что тест покрывает только резолвер).
- **Фактически:** `TestProviderStateBeforePlanning` вызывает `service._resolve_turn_tool_state(...)` напрямую; сам `_build_turn_request` и порядок вызова до `_execute_turn` не проверяются, хотя docstring утверждает «это происходит конструктором TurnRequest ДО планирования».
- **Влияние:** рефакторинг, который вычисляет tool-state после планирования или обходит резолвер в конструкторе, этот тест не поймает. Смягчение: `tests/test_ur_turn_engine.py` проверяет capabilities, доехавшие до L1 у обоих триггеров, а статический call-site `direct_chat_service.py:8452` показывает резолв до `TurnRequest`; поэтому suite-уровневое покрытие есть, но данный тест заявляет больше, чем связывает. Не блокер test-only инкремента.

### UR-B-R1-F2 — UR-06.5: реальный participation-decision не исполняется; поиск в нём не виден (IN_SCOPE, Major, блокер)
- **Ожидалось:** observer-тест доказывает отсутствие поиска на всём проходе, включая decision-стадию, либо явно ограничивает claim и добавляет отдельную проверку planner'а.
- **Фактически:** `plan_initiative_decision` замокан на фиксированный `conversation_only`-план, `_l2_write_answer` — на записывающую заглушку. Implementation.md говорит «Сама проверяемая логика (наблюдатель/L1/tool-фаза/Writer) не подменяется», но L1-decision и Writer подменены. Контр-мутация с поиском внутри реальной `plan_initiative_decision` осталась GREEN.
- **Влияние:** неправильная реализация, выполняющая поиск на стадии принятия решения об участии, проходит тест; acceptance «Observer не выполняет постоянный поиск ... до решения об участии» не доказан для этой стадии. Это missing essential proof, а не стилистика.
- **Минимальное исправление:** исполнить реальный `plan_initiative_decision` с fake LLM, возвращающим `conversation_only`-план (и тем же `ToolRouter`/`_SearchProvider`), сохранив оба поисковых канала и writer-заглушку; либо явно сузить claim теста/implementation.md до tool-фазы и добавить отдельный тест реального planner'а на отсутствие поиска. После этого — повторное ревью точной правки.

### UR-B-R1-F3 — принадлежность строк (BACKLOG)
`requirements-map.json`: UR-04.3 имеет `slice: UR-D`, UR-14.1 — `slice: UR-E` с note «полноценный участник по всем осям — UR-C/UR-23». Инкремент test-only, продукт не менялся; статусы этих строк нельзя двигать как UR-B-поставку. Рекомендация — REVIEW с сохранением владения UR-C/UR-D/UR-23.

### UR-B-R1-F4 — cached-дубль и source_ids (BACKLOG)
В duplicate-тесте `set(ev.source_ids) == {ev.sources[0].source_id}` маскирует возможный повтор id: cached-дубль добавляет второй `EvidenceSource`, `source_count` считает его дважды. Implementation.md это честно фиксирует как наблюдение; продукт не правился. Follow-up нужен только если живая деривация начнёт давать дубли (сейчас путь защитный/недостижимый).

## Ограничения, подтверждённые фактами

- UR-04.3: live L1 ещё не принимает объект `ContextSelection`; тест доказывает контракт на шве, не полное живое подключение (UR-C).
- UR-14.1: у `ContextFragment` нет отдельного `chat_id`; принадлежность чату доказывается ledger-строкой и chat-scoped read-path. Литерал `source=bot_output` живёт в `thread_chain.source_kind` и `source_id=bot_output:<id>`, ledger-projection называет источник `bot_output_ledger`.
- UR-06.5: planner/writer — швы; реальные observer runner, preflight, subset, tool phase и ToolRouter проверены; planner-мок ограничивает полноту (F2, блокер).
- 4 падения observer — предсуществующие на базе, не приписаны кандидату; продукт не менялся.

## Рекомендация по статусам (карта не правилась)

| Строка | Статус | Причина |
|---|---|---|
| UR-03.1 | **REVIEW** | dedup/error/provider state/tool trace покрыты; остаются F1 (порядок до планирования) и F4 (cached source_ids). |
| UR-04.3 | **REVIEW** | идентичность source refs на шве доказана; живое подключение `ContextSelection` к L1 — UR-C; строка UR-D. |
| UR-06.5 | **REVIEW — нужен фикс F2 до VERIFIED** | SILENT/REACT и observer no-search на реальном runner/tool-фазе; decision-стадия не исполняется, контр-мутация GREEN. |
| UR-14.1 | **REVIEW** | ledger/read-path/thread chain/L2 materialization покрыты; нет `chat_id` на фрагменте, живой ход — UR-C/UR-23. |

VERIFIED ни по одной строке не предлагается. Деплой не заявляется. Повторное ревью после исправления F2 должно проверить точную правку, оба поисковых канала и отсутствие нового ослабления перенесённого теста.