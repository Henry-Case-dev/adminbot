# UR-C — привязка доказательств (bookkeeping PM)

- Срез: `UR-C` «Контекст, память и собственная история: ContextSelection, единый allocator, retrieval, ledger бота».
- Замержено в `evol/impl`: ветка `ur/c-context` @ `e0985f5c` → merge `9ac64a61`
  («merge(unified-reply): UR-C context selection, memory retrieval, self-output history [approved e0985f5c]»).
  Merge `9ac64a61` — предок `da6299e9`, поэтому входит в текущий интегрированный кандидат.
- Владелец карты: `plans/features/unified-reply/requirements-map.json`. Эта запись — сводка привязки, а не самостоятельное доказательство.
- Локальный прогон: `tests/test_ur_context_selection.py`, `tests/test_ur_bot_output_history.py` — зелёные на текущем дереве `evol/impl @ 1cb76b62`.

## Что реально изменено merge `9ac64a61`

| Файл | Δ | Смысл |
|---|---|---|
| `services/direct_context_composer.py` | +2818 | `ContextFragment`/`ContextSelection`/`SelectionProvenance`, `build_context_selection`, allocator, правки, конфликты, overflow |
| `services/summary_memory.py` | +267 | `running_summary_decision` (watermark/вытеснение), `summary_coverage` |
| `services/bot_output_ledger.py` | +96 | read-path `list_bot_output_history` |
| `services/database.py` | +53 | аддитивные выборки ledger, ревизии, correlation |
| `services/mca_retrieval_context.py` | +100 | `build_memory_query`/`build_memory_request` (тема+адресат+reply-parent) |
| `services/thread_chain.py` | +61 | дата/родитель бот-хода из ledger после TTL |
| `services/auto_budget.py` | +49 | Dynamic по умолчанию, model-aware stage policy |
| `tests/test_ur_context_selection.py`, `tests/test_ur_bot_output_history.py` | +876 | контракт отбора, allocator, память, конспект, ledger |

**НЕ входило в diff** (важно для честности привязки): `services/model_capacity.py`,
`services/direct_l1.py`, `services/direct_chat_service.py`, `services/param_catalog.py`, `web/**`.

## Привязано `VERIFIED` (21 строка)

| Строка | Доказательство (файл::тесты) |
|---|---|
| `UR-09` | `test_provenance_counts_are_truthful`, `test_budget_is_actually_respected_after_compression` — типизированные фрагменты + честная provenance |
| `UR-09.3` | `test_p0_overflow_is_explicit_and_keeps_full_text_available`, `test_long_question_keeps_middle_and_end` |
| `UR-09.4` | `test_reply_branch_more_than_three_hops_keeps_authors` (5 ходов, uid 11/12, имена, reply-parent) |
| `UR-09.5` | `test_bot_turn_is_dialog_fact_not_style_anchor` (бот — `bot_statement`, без style-anchor семантики) |
| `UR-09.8` | `test_drops_irrelevant_before_relevant` (фон и конспект сняты, память и ветка уцелели) |
| `UR-10.1` | `test_long_question_keeps_middle_and_end` (полный текст в selection, UI-выдержка `preview_text` отдельно) |
| `UR-11.2` | `test_dynamic_is_default_mode` (`auto_budget` в diff) |
| `UR-11.3` | `test_initiative_stages_are_model_aware`, `test_stage_budget_never_exceeds_physical_window` |
| `UR-11.5` | `test_no_trim_when_everything_fits`, `test_drops_irrelevant_before_relevant`, `test_budget_is_actually_respected_after_compression` |
| `UR-12` | `TestSummaryConditions` (watermark/вытеснение вместо магических чисел строк) |
| `UR-13.2` | `TestMemoryQuery` (`build_memory_query`/`build_memory_request`, реальные uid) |
| `UR-13.3` | `test_old_episode_reachable_with_real_messages` («348» + `msg:` идентификаторы через `mca_retrieval_context`) |
| `UR-13.5` | `TestCorrectionsAndConflicts` (поздняя правка P1, старая P3/superseded, конфликт помечен) |
| `UR-13.7` | `test_no_memory_no_invention` |
| `UR-23` | `test_bot_output_survives_ttl_with_date_and_parent`, `test_bot_turn_is_dialog_fact_not_style_anchor` |
| `UR-23.1` | `TestLedgerHistoryReadPath` (chat_id/tg/sent_at/parent/correlation/revision/delivery_status/content_ref) |
| `UR-23.2` | `test_chronological_delivered_only_and_chat_scoped`, `test_chunks_share_correlation_and_keep_order` |
| `UR-23.3` | `test_ttl_cache_turn_gets_real_sent_at_from_ledger`, `test_parent_link_survives_expired_bot_reply_parents` |
| `UR-23.5` | `test_bot_turn_is_dialog_fact_not_style_anchor` (authority `SUPPORTING`, не источник истины о мире) |
| `UR-23.7` | `test_chronological_delivered_only_and_chat_scoped` (scope, failed исключён), `test_media_only_and_unknown_date_are_honest` |
| `UR-RES-04` | `test_old_episode_reachable_with_real_messages`, `test_bot_output_survives_ttl_with_date_and_parent` |

## Осталось `PENDING` (45 строк) и почему

**Зависят от файлов вне diff среза (решение планировщика — не привязывать):**
`UR-11`, `UR-11.1` (`model_capacity.py` не менялся → «единственный allocator на `model_capacity`/`auto_budget`» доказан только частично);
`UR-10`, `UR-10.0`, `UR-10.2`, `UR-10.5` (`direct_l1.py` без изменений);
`UR-RES-03` (`direct_chat_service.py`/`direct_l1.py` — снятие 800/12×200/700);
`UR-09.9` (`direct_l1.py`/`direct_chat_service.py` — сохранение render-проекций);
`UR-11.4` (fallback на меньшую модель — `model_capacity`/L2-путь);
`UR-11.7`, `UR-11.8`, `UR-12.1`, `UR-12.2`, `UR-12.3`, `UR-12.5`, `UR-21.02`–`UR-21.18`
(`param_catalog.py`/UI — правка каталога и инспектор не входили в срез).

**Зависят от подключения ContextSelection к живому ходу:**
`build_context_selection` вызывается только из тестов; `direct_chat_service.py` его не использует.
Поэтому строки про фактический payload L1/L2 остаются `PENDING`:
`UR-09.1`, `UR-09.2`, `UR-09.6`, `UR-09.7`, `UR-11.6`, `UR-12.4`, `UR-23.4`, `UR-23.6`, `UR-23.8`, `UR-BAN-04`.

**Требуют live/E2E или не проверены тестами:**
`UR-BAN-03` (объём чтения под нагрузкой), `UR-13`, `UR-13.1`, `UR-13.4`, `UR-13.6`, `UR-13.8` —
разделение типов памяти, identity-prior при конфликте, физическая пагинация на миллионах сообщений.
