# ACCEPT — независимая приёмка H1–H32

- Вердикт: **ACCEPTED** (поведение среза). Карта не переписывалась.
- Кандидат: `0b8dfe6af297aaa65caa1a216d584ef43f6b1d73` (HEAD master, `0b8dfe6a`).
- Срез: ACCEPT, 39 строк карты. Поведенческих FAIL нет.
- Гейт `--stage review` красный только клерком (строки PENDING, `candidate_commit` карты устарел). Это не дефект продукта. Для PM: `APPROVED_BEHAVIOR / MAP_SYNC_REQUIRED`.
- Живые Telegram-отправки не выполнялись.

## Что проверено заново

Наборы волн 1–4 прогнаны на этом кандидате: **232 passed / 0 failed** (13.72 с).

Регрессия памяти, сна, Direct Chat, композера и схем инструментов: **767 passed / 0 failed** (32.42 с).

Независимые пробы (не в репозитории):

- `WorkspaceData/runs/c742e4de9e92c489/p0-history-analysis-24c1789f4d07/temp-3c05b62fb0/accept_probe.py`
- тот же каталог, `probe_5000.py` — повтор H6 после ложного срабатывания первой пробы.

Первый прогон depth=5000 упал из-за проверки подстроки `TOK100` внутри `TOK1000`, не из-за продукта. Повтор с маркерами `MARK-N-END`: 125 страниц, 5000 уникальных строк, границы `101:101..5100:5100`, `incomplete=0`.

## H1–H32

| ID | Итог | Доказательство |
|---|---|---|
| H1 | PASS | Проба `depth=50`: 2 страницы, последние 50, хронология, чужой чат не попал. Короткий путь без LLM: проба `H1-short-path-30` (30 сообщений, 0 вызовов) и `tests/test_history_segments.py::test_fitting_sample_untouched_zero_llm`. Дефолт без параметра: `tests/test_history_pages.py::test_default_depth_50_is_not_cap`. |
| H2 | PASS | Проба `depth=150`: 4 страницы, ровно последние 150, ASC, без усечения многоточием, чужой чат исключён. Старый потолок 150 не вернулся; формат страниц — принятый контракт TRUNC-PAGES, не регресс охвата. |
| H3 | PASS | Проба `depth=400`: 10 страниц, окно 4701..5100 из архива 5100, счётчики `processed+remaining=available`. |
| H4 | PASS | Проба `depth=500`: 13 страниц (12x40+20), охват ровно 500, `incomplete=0`. |
| H5 | PASS | Проба `depth=2000`: 50 страниц, 2000 строк, новейшее в конце последней, сообщение до окна отсутствует. `@@HISTORY_SAMPLE` стабилен вдоль цепочки. |
| H6 | PASS | `probe_5000.py`: `requested=available=processed=5000`, 125 страниц, `has_next` только до последней, скрытого потолка 150/500/2000 нет. Страница БД 500 не обрезает выборку. |
| H7 | PASS | Проба `H7-short`: архив 17, запрос 400 даёт `available=17`, `processed=17`, `incomplete=0`, `has_next=0`. Дубль: `tests/test_history_pages.py::test_available_short_of_requested`. |
| H8 | PASS | Проба `H8-insert-during-pages`: после первой страницы вставлены 5 новых сообщений; cursor-обход сохранил `available=120`, границы и конец выборки, новые строки не вошли. Плюс `tests/test_history_pages.py::test_sample_fixed_while_new_messages_arrive`. |
| H9 | PASS | Проба `H9-over-3500`: 8 сообщений, 5128 символов, одна страница, текст целиком, без обрезки. |
| H10 | PASS | Проба `segments-over-100k`: 117802 символа, `@@HISTORY_COVERAGE`, `complete=1`, `processed=130`, 33 сегмента, ни один промпт не длиннее 20000. Страницы: `tests/test_history_pages.py::test_over_100k_chars_via_pages`. |
| H11 | PASS | `tests/test_history_segments.py::test_single_huge_message_counted_not_cut` и `tests/test_history_pages.py::test_single_huge_message_not_cut` (в прогоне 232). Учёт строки сохранён, `text[:N]` нет, `oversize=1`. |
| H12 | PASS | Во всех пробах глубины новейший маркер — в последней строке последней страницы; предшествующий окну маркер отсутствует. `tests/test_history_pages.py::test_newest_at_end_of_last_page`. |
| H13 | PASS | Пробы не содержат обрезки многоточием. `tests/test_history_pages.py::test_no_symbol_cap_on_history_path`. В коде истории константы `_HISTORY_MAX_SYMBOLS` нет. |
| H14 | PASS | `tests/test_history_pages.py::test_vanished_tail_reports_incompleteness`: `incomplete=1`, `reason=tail_missing`, захваченный `available` не ужимается, выживший хвост доходит. |
| H15 | PASS | Отдельная проба точных refs: `tg:1,3,5,58,60,62,116,118,120` все в событиях, `complete=1`, 3 события. Постоянный тест `tests/test_history_segments.py::test_topics_at_start_middle_end_all_present` путь гоняет, но проверка старта слабая (см. незакрывающее). |
| H16 | PASS | `tests/test_history_segments.py::test_event_across_boundary_keeps_connection` (`continues_from=1` на стыке страниц) и `test_intra_page_cut_reply_keeps_connection` (разрез внутри страницы, две связи). |
| H17 | PASS | `tests/test_history_segments.py::test_same_topic_across_segments_is_mention_not_new_event`: повтор — mentions, id в refs не дублируется. |
| H18 | PASS | `tests/test_history_segments.py::test_independent_discussions_not_collapsed`: два события, множества refs не пересекаются. |
| H19 | PASS | `tests/test_history_segments.py::test_failed_segment_visible_others_delivered` и `test_findings_budget_overflow_honest_markers` (`complete=0`, `reason=findings_budget`, omitted назван). |
| H20 | PASS | `tests/test_history_segments.py::test_delivered_range_never_reread` и `test_segments_not_reanalyzed_on_second_call`: один LLM-вызов на сегмент. |
| H21 | PASS | `tests/test_history_isolation.py::test_old_hit_not_in_range_block_only_labeled_supplement` и `test_range_supplement_is_labeled_not_in_range_set`. |
| H22 | PASS | `tests/test_history_isolation.py::test_episode_span_crossing_old_edge_clipped` и `test_supplement_materializes_labeled_after_episode`. |
| H23 | PASS | `tests/test_history_relevance.py::test_touch_skips_bot_generated_origins`, `test_repeated_delivery_dampens_ranking_knn`; сон: `tests/test_dream_belief_bot_provenance.py::test_bot_only_sources_no_independent_importance` (в батарее 767). Штраф только порядок, bot-origin в сумме важности = 0. |
| H24 | PASS | Проба `H24-explicit-membership`: после 8 подач явный запрос возвращает цель первой из 10. Проба `H24-passive-dampened-membership`: тот же состав, цель на последней позиции. Совпадает с принятой правкой: явный запрос не штрафуется, passive только переставляет. `tests/test_history_relevance.py::test_explicit_query_returns_target_amid_shared_keyword`, `test_passive_penalty_never_changes_set_membership`. |
| H25 | PASS | `tests/test_history_w4_fixes.py::test_identity_matches_by_user_id`: одинаковое имя, разные uid — не один человек. |
| H26 | PASS | `tests/test_history_w4_fixes.py::test_forward_attribution_owner_and_conflict`: владелец исходной публикации, флаг `attribution_conflict`, вид forwarded. |
| H27 | PASS | Постоянные тесты на синтетике (разные темы). Проба H24 — другая тема `зыбун-поляна`, тот же исход. |
| H28 | PASS | Один и тот же обход страниц для 50/150/400/500/2000/5000. В логике истории нет ветки сравнения с 400 или 2000. Упоминания этих чисел в схеме — примеры для модели, не потолок. |
| H29 | PASS | В изменённых модулях `services/` литерала «внуково» нет. `tests/test_history_quality.py::test_no_topic_or_name_exceptions`. |
| H30 | PASS | `tests/test_history_relevance.py::test_ranking_module_has_no_topic_or_name_literals`. Исключение bot-origin — набор provenance, не словарь тем. |
| H31 | PASS | Проба 5000 доказывает отсутствие нового общего потолка. `_HISTORY_PAGE_ROWS=40` — размер одного возврата. `_RECENT_MESSAGES_PAGE_SIZE=500` — страница чтения БД, выборка 5000 её превышает. `_HISTORY_MAX_DEPTH` удалён. `_MEMORY_MAX_SYMBOLS=3500` остаётся у других инструментов, не у истории. |
| H32 | PASS | Проба `H32-small-slot-continues`: слот 500, 130 сегментных вызовов, ответ начинается с `@@HISTORY_COVERAGE`, строки отказа «невозможно из-за одного контекста» нет. |

## Остальные строки ACCEPT

| Строка | Итог | Наблюдение |
|---|---|---|
| REQ-HA-H-BEHAVIOR-NOT-VERBATIM | PASS | Пробы сверяют охват, счётчики, состав и позицию, не заготовленный текст ответа. |
| REQ-HA-ARCH-REUSE | PASS | Диф `9da314e7^..HEAD` расширяет `get_recent_messages`, `ToolRouter`, `DirectChatService.collect_history_segments`, `MemoryManager`, evidence pack. Второго читателя истории нет. |
| REQ-HA-ARCH-NO-SECOND-ENGINE | PASS | Нового агента и второго Retrieval Engine нет. Сегменты — метод Direct Chat, один `llm.generate` на сегмент, `module=direct_chat`. |
| REQ-HA-ARCH-CORE-UNCHANGED | PASS | `chat_prompts.py`, `prompt_composer.py`, `prompt_registry.py`, `style_policy.py`, `prompt_factory.py` в дифе не менялись. В `prompt_style_blocks.py` только дописаны две константы инструкций анализа, речевые блоки не правлены. |
| REQ-HA-ARCH-NO-SEMANTIC-HARDCODE | PASS | Подтверждено H27–H30. |
| REQ-HA-P11-NO-LIVE-TESTS | PASS | Все прогоны — SQLite `:memory:` и фейковый LLM. В рабочие чаты ничего не отправлялось. |
| REQ-HA-P12-NO-CONFIRMED-REWRITE | PASS | Подтверждённые контуры переиспользованы. Сдвиг индексов `CANONICAL_ORDER` добавляет слот `history_supplement` после episode; относительный порядок прежних kind сохранён. |

## Регрессия

- Волны 1–4 (`test_p0_history_depth_round1029`, `test_history_pages`, `test_history_segments`, `test_history_isolation`, `test_history_quality`, `test_history_quality_wiring`, `test_history_w4_fixes`, `test_history_relevance`): **232 passed / 0 failed**.
- Память и сон (`test_belief_decay`, `test_asap8_v63_b03_memory`, `test_summary_memory`, `test_graphrag_database`, `test_dream_worker`, `test_dream_prompts`, `test_dream_persona_traits`, `test_dream_belief_bot_provenance`, `test_asap8_v6_wa1_dream_hours`, `test_asap8_v6_p1_d09_dream`): внутри общей регрессии, падений нет.
- Direct Chat, паритет композера, схемы и agentic (`test_direct_chat`, handlers/prompts/concurrency/lore/relations, `test_soul1_composer_parity_off`, `test_soul1_core_composer_integration`, `test_soul1_composer_layers`, `test_direct_context_composer_asap3`, `test_quota_removal_composer`, `test_tool_schemas`, `test_agentic_ai_round1020`, `test_agentic_events_round1026`, `test_recent_history_tool_round1015`): **767 passed / 0 failed** вместе с памятью и сном.
- R17: 209 журнальных записей обхода истории, маркеров текста сообщений нет.

## Гейт

ACCEPT, `--stage review --candidate 0b8dfe6af297aaa65caa1a216d584ef43f6b1d73`:

- `FAIL: candidate mismatch`
- 39 строк `mandatory not VERIFIED (got PENDING)`
- `stage=review inventory=184 manual=192 scoped=39 errors=40`, код выхода 1

DEPLOY, тот же кандидат (деплой не начинался, красный ожидаем):

- `FAIL: candidate mismatch`
- DONE-01..13, DEPLOY-SAFE, DONE-NO-OWNER-BLOCKS, OWNER-REPORT, DEPLOY-QUEUE — PENDING
- DEPLOY-POSTCHECK — PENDING, не READY_FOR_LIVE
- `scoped=18 errors=19`, код выхода 1

Это сверка карты, не поведения. Строки ACCEPT по поведению можно привязать к этому артефакту. DEPLOY остаётся PENDING до выката.

## Постоянные пробелы тестов

Блокирующего пробела нет: каждый H закрыт прогоном или тестом, который проверяет контракт, и этот прогон зелёный.

Незакрывающее: в `test_topics_at_start_middle_end_all_present` проверка старта `ref.startswith("tg:1")` истинна и для `tg:118`. Поведение старта подтверждено отдельной пробой точных refs. Имеет смысл сузить постоянное утверждение до `tg:1`/`tg:5`, но это не дефект продукта.

## Неблокирующее

- Слабое утверждение старта в тесте H15 (см. выше).
- `prompt_style_blocks.py` затронут только дописанными константами анализа, не режимами речи.
- Наборы `fallback_recompose` и allowlist `tool_coordinator` в эту батарею не входили и здесь не падали. Не переносить их в этот срез без нового наблюдения.
- Клерк карты (PENDING / чужой candidate) — работа PM, не повтор Builder.

## Следующий шаг

Orchestrator: поведение ACCEPT принято на `0b8dfe6a`. PM привязывает 39 строк ACCEPT к этому артефакту и кандидату. DEPLOY не считать уже проверенным продом: постдеплойные строки остаются открытыми до штатного выката.
