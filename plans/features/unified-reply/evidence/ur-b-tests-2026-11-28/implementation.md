# UR-B tests-only (2026-11-28)

База/HEAD: `74ef57ef4` (release 2.58.273, задеплоен).
Ветка: `feat/ur-b-testonly-2026-11-28`.
Продуктовый код не менялся: только новые тестовые файлы.
Деплой не выполнялся.

## Что добавлено

| Файл | Строки карты |
|---|---|
| `tests/test_ur_b_tool_evidence.py` | UR-03.1, UR-04.3 |
| `tests/test_ur_14_bot_output_history.py` | UR-14.1 |
| `tests/test_ur_b_observer_no_search.py` | UR-06.5 (перенос `TestObserverCheckMakesNoSearch` из `ur/b-evidence@6099cc17` + SILENT/REACT) |

## По строкам

### UR-03.1 — права/состояние провайдеров до планирования; одна ToolEvidence

Тесты:
- `TestProviderStateBeforePlanning::test_turn_tool_state_is_the_runtime_provider_set`
  — `_resolve_turn_tool_state` (конструктор `TurnRequest` до плана) берёт
  `source == "active_tools"`, `search_available` из ФАКТИЧЕСКОГО набора tools;
  при урезанном runtime-наборе поиск честно недоступен.
- `TestOneToolEvidenceStructure::test_success_keeps_sources_events_and_trace_in_one_evidence`
  — на живом `run_tool_phase` + реальном `ToolRouter`: `source_ids` == id
  `sources`, `source_count`, `tool_events` совпадает с `raw.tool_results`,
  точный набор ключей события (status/error_code/error_type/duplicate/attempt/
  duration_ms/out_chars/…), нет `data`/`args_fingerprint`, `full_text`
  открывает каждый `content_ref`, `tool_trace` в той же структуре.
- `test_duplicate_call_projected_as_duplicate_in_same_evidence` — два шага
  с одинаковым tool+args через настоящий `run_simple_tools`/`_dispatch_step`
  (duplicate-шаг зависит от первого, чтобы волна была последовательной):
  провайдер вызван ровно один раз; в `tool_events` второй вызов —
  `duplicate=True`, `attempt=2`, тот же `out_chars`, `duration_ms=0`.
- `test_error_event_carries_code_type_and_time` — падение провайдера:
  `status=error`, `error_code=tool_error`, `error_type` с текстом причины,
  `duration_ms>=0`, `out_chars>0`, `tool_trace.ok=False`,
  `claim_policy != claim_allowed`, источников нет.

Мутации (RED): отключение `dedup_skip` даёт второй сетевой вызов; обнуление
`error_type` в `_tool_events_from`; `search_available=True` константой.
См. `raw/mutations.txt` п.1–3.

Наблюдение (не блокер строки): cached-дубль всё ещё добавляет
`EvidenceSource`, поэтому `ToolEvidence.source_ids` содержит повтор одного
id, `source_count` считает его дважды. Живая `derive_simple_steps` дублей не
порождает (caps дедуплицируются, mapping tool уникален), adaptive до dispatch
ловит cycle — путь сейчас защитный/недостижимый. Продукт не правился;
follow-up нужен только если деривация когда-либо начнёт давать дубли.

### UR-04.3 — L1 и L2 делят один набор источников в разных форматах

Тест: `TestSharedL1L2SourceSet::test_l1_and_l2_project_same_source_refs_in_their_own_formats`.
Один и тот же кандидатный набор строк проецируется двумя живыми
потребителями:
- L1: `direct_context_composer.allocate_window_projection` + `build_l1_context`
  (`[ПОСЛЕДНИЕ СООБЩЕНИЯ]`, ссылки `[msg:<id>]`, бюджет L1 = 10^6);
- L2: `direct_chat_service._build_l2_selection_candidates` +
  `_materialize_selection` (канонический `<Global_Context>`, ссылки
  `tg:<id>`, бюджет selection = 0/full).

Ассерт: множества source refs (`msg:<tg>`) идентичны в обеих стадиях и
совпадают с исходными строками; форматы разные (секции/строки vs XML-блок),
тексты не равны; у стадий независимые бюджеты. Никакого принудительного
одинакового объёма не предполагается.

Мутация (RED): L1 source_id `msg:<tg>` → `win:<index>` ломает идентичность
(L1 refs != L2 refs).

Честная граница: live L1 пока не принимает сам объект `ContextSelection`
(открытые строки UR-C), поэтому тест доказывает контракт на шве, где оба
потребителя строятся из одного набора строк/одного source-id пространства.

### UR-06.5 — SILENT/REACT и Observer не ищут

Перенос `TestObserverCheckMakesNoSearch`:
- `tests/test_ur_b_observer_no_search.py::TestObserverCheckMakesNoSearch`;
- адаптация к базе: импорты хелперов из `tests/test_ur_b_live_wiring.py`;
- детерминизм публикации: `mca_exploration.choose_conversation_alternative`
  замокан НА `(None, None)` только для этого теста, потому что текущая
  вероятностная политика может отложить инициативу (`random_fallback`), и
  тогда прохода до Writer'а нет, а «0 поисков» ничего не доказывает. Сама
  проверяемая логика (наблюдатель/L1/tool-фаза/Writer) не подменяется.
- Проход доходит до Writer'а и отправки; поиск = 0 по двум каналам:
  подменный провайдер роутера и `SearchAggregator.search`; evidence у
  Writer'а пуст; `_dx.run_tool_phase` не вызывался (нет claim-запроса);
  `execute_web_search` при этом присутствует в активном наборе.

SILENT/REACT: `TestSilentReactNoSearch` — живой `_l1_tool_phase` на
`silent`/`react` с осью `open_world/required` и capability `web_search` даёт
0 запросов провайдера и `raw is None`.

Мутации (RED): снятие early-return SILENT/REACT в `run_tool_phase`; прямой
поисковый вызов из `observe_tick`. См. `raw/mutations.txt` п.5–6.

### UR-14.1 — свои сообщения бота — полноправные участники истории

Тест: `tests/test_ur_14_bot_output_history.py::test_delivered_bot_output_is_full_history_participant`.
Через настоящий write-path (`bot_output_ledger.record_delivered_output`) и
read-path (`list_bot_output_history`/`collect_self_output_fragments`):
`chat_id`, `tg_message_id`, `sent_at`, `parent_message_ref`, ревизия,
`correlation_id`, `delivery_status='delivered'`; source-маркер
`source=bot_output_ledger`, `source_id=bot_output:<id>`, в
`thread_chain.ChainItem.source_kind == "bot_output"`; фрагмент —
`KIND_BOT_STATEMENT`/`ROLE_SELF_OUTPUT` с теми же осями; живой
`_build_l2_selection_candidates` + `_materialize_selection` кладут ответ бота
в общий `<Global_Context>` рядом с человеком, без style-anchor семантики.

Мутация (RED): `bot_output:` → `self_output:` в
`ledger_record_to_fragment` ломает source-маркер.

Честная граница: у `ContextFragment` нет отдельного поля `chat_id`;
принадлежность чату доказывается ledger-строкой и chat-scoped read-path.
Литеральный `source=bot_output` живёт в `thread_chain.source_kind` и
`bot_output:` id; ledger-projection называет источник `bot_output_ledger`.

## Прогоны

См. `raw/`.

- Новые тесты: **9 passed** (`raw/new-tests-green.txt`).
- Смежные UR-B: **152 passed** (`test_unified_reply_ur_b_search_first.py`,
  `test_unified_reply_ur_b_review_fixes.py`,
  `test_unified_reply_ur_b_no_topic_veto.py`, `test_ur_b_live_wiring.py`).
- Selection/ledger: **79 passed** (`test_ur_context_selection.py`,
  `test_ur_c_2_live_wiring.py`, `test_ur_bot_output_history.py`,
  `test_ur_23_self_repeat.py`).
- Direct/context: **311 passed** (`test_direct_context_composer_asap3.py`,
  `test_direct_context_capacity_asap3.py`, `test_direct_l1_l1d_contract.py`,
  `test_direct_chat.py`, `test_direct_chat_handlers.py`,
  `test_direct_chat_concurrency.py`).
- Observer: **53 passed, 4 failed** — падения предсуществующие на базе
  `74ef57ef4` (продукт не менялся, новые файлы этими сьютами не
  импортируются): `_StubService` без `_writer_evidence_capacity` и два
  soul1-gate теста. Список — `raw/observer-suites.txt`.
- Collect-only: 9 тестов (`raw/collect-only.txt`).

## Рекомендация статусов (карта не правилась)

- UR-03.1 — **REVIEW** с наблюдением про duplicate `source_ids` (не блокер;
  путь защитный).
- UR-04.3 — **REVIEW**; идентичность refs доказана на шве. Полное живое
  подключение `ContextSelection` к L1 остаётся открытыми строками UR-C.
- UR-06.5 — **REVIEW**.
- UR-14.1 — **REVIEW**.

VERIFIED не предлагается: финальное решение — за независимым Reviewer.
