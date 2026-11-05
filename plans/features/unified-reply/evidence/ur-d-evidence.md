# UR-D evidence — L2/output: общий Writer, LLMCompletion, continuation, безопасная отправка

Slice: `UR-D` · Candidate: branch `ur/d-writer`, коммит `4e0bf18b` (base `6180380d`, `evol/impl`).
Карта: `plans/features/unified-reply/requirements-map.json` (slice `UR-D`, 11 строк).
Основной тест-файл: `tests/test_ur_d_writer.py` (17 тестов, CONTRACT owner=UNIFIED-REPLY/UR-D).

## Что было объединено (один код)

* **Writer-шов**: Direct и Initiative пишут одним `_l2_write_answer()` (один verbalizer-канал,
  один continuation-контур, один fallback-репак, один композер речи `_compose_speech_system`);
  `writer=...` — только имя в трассе, не второй код.
* **Контекст инициативы**: диалог отбирает общий `ContextSelection`
  (`direct_context_composer.collect_window_fragments` + `build_context_selection`, бюджет слота
  `initiative.l2` из `auto_budget.resolve_stage_budget`); ручная сборка
  `render_window_lines(window, 12)` и срез `[-12:]` удалены из активного маршрута. Рендер строк
  с метками прогона — тот же общий рендерер (один владелец формата EVOL v5); selection решает,
  что видно, окно задаёт порядок.
* **Output**: `response_extent.writer_max_output_tokens()` вычисляет физически допустимый
  `max_tokens` из реального `max_output` провайдера и остатка окна под фактический размер входа;
  Writer вызывает его сам (модель/endpoint — только от инжектированного клиента). Инициативный
  `max_tokens=700` удалён; longform-дефолт 4096 и ceiling 16384 больше не подставляются в
  семантические маршруты (Writer — оба режима; legacy single-маршрут тоже вычисляет). Факт
  провайдера неизвестен → `None` → ключ не отправляется. Tool-стадии (оркестратор JSON) сохраняют
  функциональную границу `longform_max_tokens` (не семантический ответ).
* **Скрытые капы речи**: из `<Initiative_Context>` удалены «Держись в рамках ожидаемой полноты» и
  «не устраивай доклад» — полноту несёт extent-блок плана (UR-04 §3 источника).

## Покрытие по строкам карты (status VERIFIED, кандидат 4e0bf18b)

| Req | Тест(ы) (`tests/test_ur_d_writer.py`, если не указано иное) | Что доказывает |
|---|---|---|
| UR-RES-05 | `test_unfinished_initiative_not_published`, `test_length_answer_completed_before_sending` | length без прогресса → writer_failed, Telegram ничего не отправляет; восстанавливаемый length → целостный ответ до отправки |
| UR-04 | `test_both_triggers_share_writer_seam`, `test_both_triggers_share_speech_composer`, `test_initiative_no_hidden_briefness_directive` | один шов Writer'а и один base_key композера на оба триггера; факты повода в промпте, «не устраивай доклад» нет, extent из плана |
| UR-05 | `test_sendrecheck_suppresses_send_after_answer`, `test_stale_target_cancels_semantic_reply` (+ прежние I6/I6b/initreply_binding зелёные) | SendRecheck/target/счётчик отправки сохранены на границе отправки |
| UR-10.3 | `test_initiative_window_from_shared_selection_no_hard_cap` | окно из общего ContextSelection: >12 строк при достаточном бюджете, аллокатор снимает при бюджете 40 токенов (8 строк); метки `[M1]` — общий рендер |
| UR-18 | `test_length_finish_reason_continues_same_author`, `test_generate_stays_str_compatible`, `test_fallback_keeps_finish_reason` | `generate_with_metadata` доезжает до Writer, continuation читает finish_reason; `generate()` — str; fallback-нога сохраняет finish_reason + chain |
| UR-19 | `test_output_computed_from_real_capacity`, `test_unknown_resource_sends_no_max_tokens_key` | max_tokens = min(провайдерский max_output, окно − фактический вход); неизвестный ресурс → None (ключа нет) |
| UR-19.1 | `test_semantic_constants_are_not_sent`, `test_output_computed_from_real_capacity`, `test_length_answer_completed_before_sending` | инициативного 700 нет; output вычислен; короткий extent не создаёт обрубок (continuation держит границу) |
| UR-19.2 | `test_semantic_constants_are_not_sent`, `test_unknown_resource_sends_no_max_tokens_key`, `test_d12_longform_not_cut_by_hidden_cap` (`tests/test_asap7_direct_l1.py`, обновлён под новый контракт) | 4096/16384 не подставляются как семантическая граница; ответ уходит целиком |
| UR-19.3 | `test_length_finish_reason_continues_same_author` (+ весь `tests/test_rlr_length_continuation.py` зелёный) | continuation тем же автором: исходный контекст не меняется, assistant-граница накопленного текста, склейка без потери слова |
| UR-19.4 | `test_unfinished_initiative_not_published`, `test_length_answer_completed_before_sending` | продолжение до отправки; incomplete → честный отказ, инициатива отменяется; точки к обрезанному слову никто не дописывает |
| UR-19.5 | `test_chunk_text_is_lossless_and_pure`, `test_first_chunk_bound_to_reply_others_not` | chunk_text чистый/lossless, первый chunk с reply_to, остальные без; чанкование после валидированного завершения |

Мутация («второго автора не скрыть»): `test_second_authoring_call_is_caught` — второй
литературный вызов с тем же `author_state` хода даёт `semantic_rewrite_count == 1` (механизм
`turn_trace.author_state`, тот же, что передаёт `_l2_write_answer`).

## Прогоны (worktree `WorkspaceData/worktrees/c742e4de9e92c489/unified-reply-ur-d-…`, py3.12)

* Команда брифа: `pytest tests/test_ur_d_writer.py tests/test_direct_chat*.py
  tests/test_ur_turn_engine.py tests/test_ur_b_live_wiring.py tests/test_rlr_*.py -q`
  → **526 passed, 0 failed**.
* Инициативный батч (coordination/asap8/evol/soul1/nostalgia/mca09/…) → 309 passed + 4 pre-existing
  (см. ниже).
* Широкий регресс (mca23/asap7/ur-c/unified_core/soul1/w5/…) → 438 passed + 2 pre-existing
  partition (см. ниже).
* Базовая линия до правок на `6180380d`: та же команда брифа → 509 passed (зелёная).

## Известные сбои, НЕ принадлежащие UR-D (классификация по базе 6180380d)

1. `tests/test_initiative_coordination.py`: 4 теста (act_on_opportunity_conflict…,
   evaluate_phase_precheck…, t1_nostalgia_delegated_refusal…, t5_every_text_send_site…) —
   падают на базе даже в изоляции: шов PublicationCoordinator/делегации наблюдателя
   (линия meme-publication initiative): отказ брони не отсекает вызов handle_initiative. Это НЕ
   контракт handle_initiative (SendRecheck/target/счётчик внутри — целы и покрыты); владелец —
   координационная линия INIT-COORD/meme-publication. → unrelated/pre-existing, передано родителю.
2. `tests/test_mca10b_random_applications_block_a_round1041.py::test_kill_switch_registry_73_and_defaults`
   — registry-count drift: `len(mca_events.REASON_CODES)` 315 vs ожидание 314 (чужой merge добавил
   код причины без обновления счётчика). → unrelated/pre-existing.
3. `tests/test_unified_core_route_coverage.py::test_factcheck_single_path_*` (2 теста) — падают
   ТОЛЬКО в мульти-файловом батче и ТОЛЬКО на базе тоже (проверено checkout 6180380d) →
   известный context-partitioning-сбой теста (глобальное состояние `monkeypatch_free`), к UR-D
   отношения не имеет.
Маркеры `sent=` / `projection` / `history_w4` из брифа на этой базе в команде брифа не
воспроизводятся (0 падений).

## Честные ограничения

* Живой прод-вызов с реальным провайдерским max_output не выполнялся (слайс без live-обязательства,
  `live_required: false`): производственное поведение `writer_max_output_tokens` на реальном
  каталоге покрывается типами `CapacityResult` и резолвером, но фактический max_output
  прод-модели не снимался.
* `longform_max_tokens` остаётся в tool-стадиях (`_l1_tool_phase`, `chat_with_tools`) как
  функциональная граница JSON-вызова оркестратора (не семантический ответ); env-кнопка
  `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS` для этих стадий сохранена (rlr_live_proof).
* Композер речи в проде выключен владельцем (UNIFIED_COMPOSER_ENABLED, ожидание SOUL-слайса);
  тест композера форсит ON, чтобы доказать общий base_key на оба триггера.
