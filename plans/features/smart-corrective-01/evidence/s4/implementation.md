# SMART-CORRECTIVE-01 — S4-COMPLETION implementation evidence

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-14.

## Идентичность кандидата

- Epic: `smart-corrective-01`, срез `S4-COMPLETION`.
- Базовая линия: ветка `sc/corrective-s3` @ `bbb30555` (production-код S1/S2/S3
  = `163b8ddd`, S3 code candidate; release line `release/2.58.200` @
  `13884daa`).
- Рабочая ветка: `sc/corrective-s4`.
- Code candidate commit: `8ccd0730` (`fix(tool-loop): research completion
  state and bounded continuation (S4)`).
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-68195166`
  (managed `WorkspaceData/worktrees`, registered как `s4-completion`).

## Изменённые файлы

Production:

- `services/tool_loop.py` — минимальное расширение существующего
  `ToolLoopResult`/tool-loop (второго agentic-пайплайна нет):
  - `research_state` (dict): `status` = `complete|partial|failed`, `cause`
    (машинный код), `continuation` = `{available, next_action, options, token}`,
    `evidence_refs`, `gaps`, `confirmed`, `failed`, `attempts`,
    `continuation_passes`;
  - `continuation_offers` — счётчик фактически предложенных продолжений;
  - достаточность: нет инструментальных попыток → `complete`
    (`no_research_needed`); подтверждённые результаты без структурных
    пробелов → `complete` (`evidence_sufficient`); структурный пробел →
    `partial` (данные есть) / `failed` (данных нет);
  - пробелы выводятся структурно из envelope-журнала (статусы/коды/
    `verified`/`outcome`/`continuation`/`truncation`, аргументы запроса по
    fingerprint) — без таблиц «ошибка → файл/инструмент» и без анализа
    текста модели;
  - `ensure_research_completion` (opt-in, default **False**): если модель
    остановилась текстом при `partial` и доступен способ продолжения — в ТОМ
    ЖЕ цикле добавляется одна user-директива `<research_continuation>` с
    фактическими пробелами и родовыми вариантами (уточнить запрос/другой
    кандидат/оставшиеся фрагменты/резервный маршрут/другие доступные
    инструменты). Направление выбирает модель;
  - прогресс-гейт вместо квоты: повторное предложение только при НОВОМ
    отпечатке пробелов И новых записях журнала; отсутствие новых данных/тот
    же отпечаток → финал `partial` с cause `continuation_not_taken`/
    `no_progress`;
  - `research_partial_note(state)` — готовая честная пометка для потребителя.
- `services/checkup_service.py` — чекап как потребитель:
  - `chat_with_tools(..., ensure_research_completion=True)`;
  - телеметрия run-словаря: `research_status`, `research_cause`,
    `research_continuations`, `research_confirmed`, `research_unresolved`,
    `research_evidence_ref_count`, `research_continuation_available`
    (существующие `research_rounds/calls/tools/degraded/reason` сохранены);
  - свободный ответ модели при незакрытом структурном пробеле получает
    пометку «это частичный результат — <причина>. Неподтверждено: …» (ДО
    единственного outbound-прохода стиля, чтобы настройки чата применялись к
    финальному тексту целиком). Деградированные ответы не дублируют пометку:
    причину уже несёт финальная фаза tool-loop.

Тесты:

- `tests/test_smart_corrective_completion.py` (new, 11 тестов; см. ниже).

Документ: этот файл.

## Интерфейс для S3B/S6 (что переиспользовать, что не дублировать)

- `ToolLoopResult.research_state["status"]` — `complete|partial|failed`;
  `["cause"]` — машинный код; `["continuation"]["available"]`,
  `["next_action"]` (`continue_research|declare_limitation|none`),
  `["options"]`, `["token"]` (opaque cursor, если есть);
  `["evidence_refs"]` — refs фактически полученных результатов;
  `["gaps"]` — `[{kind, tool, code, retryable, token}]`;
  `["confirmed"]`/`["failed"]`/`["attempts"]`.
- `ToolLoopResult.continuation_offers` — сколько продолжений реально
  предложено (наблюдаемость).
- Публичные хелперы: `research_cause_text(cause)`,
  `research_partial_note(state)`; константы `RESEARCH_COMPLETE`,
  `RESEARCH_PARTIAL`, `RESEARCH_FAILED`.
- S6/DevOps: телеметрия чекапа (ключи выше) — в существующем
  `checkup_triggered.source_ref_json`; новых событий/словарей нет.
- S3B/lifecycle: `research_state` не вводит второго планировщика; при
  необходимости использовать те же поля, а не копировать логику.

## Семантические правила (наблюдаемые)

1. **Достаточность.** Нет инструментальных попыток → `complete`
   (`no_research_needed`, здоровый чекап = один вызов модели). Все попытки
   структурно разрешены (ok/проверенное отсутствие, без незакрытой
   неполноты) → `complete` (`evidence_sufficient`).
2. **Продолжение при частичном.** Единичный отказ (`error/timeout`),
   нерелевантный/неподтверждённый результат (`verified=false`,
   `mention/other`), неполный фрагмент (`truncation` с доступным остатком,
   причём остаток относится к запрошенному диапазону) дают `gaps`; при
   `ensure_research_completion` модель получает директиву в том же цикле.
3. **Пробел закрывается фактом.** Если ПОЗЖЕ тот же инструмент доставил
   подтверждённые данные, более ранний отказ/неполнота не считаются вечно
   незавершённым исследованием (иначе любой повтор навсегда помечал бы чекап
   частичным).
4. **Окно vs порция.** `truncation` с причиной `over_window` при явно
   запрошенном `line_end`, который доставлен, НЕ является незакрытым
   пробелом: модель получила ровно свой диапазон. Физическая порция
   (`over_portion`) и открытый запрос (без `line_end`) — являются.
5. **Невозможность продолжения.** Только `denied/terminal`-пути без других
   доступных инструментов → автоматического продолжения нет: `partial` с
   `cause=source_unavailable`, пометка с конкретной причиной и
   неподтверждёнными участками.
6. **Обычные диалоги нейтральны.** Без opt-in директива не добавляется;
   `research_state` доступен потребителю, но поведение не меняется.
7. **Нет бесконечного цикла.** Повторный offer требует нового отпечатка
   пробелов И роста журнала; повтор того же состояния/отсутствие новых
   данных завершает исследование честным `partial`.

## RED → GREEN (поведенческий probe на реальном коде)

Probe: `red_probe.py` (временный run, закрыт после промоушена результатов).
Сценарий A: модель получила НЕрелевантный первый результат (`verified=false`,
`mention`) и вернула промежуточный текст. Сценарий B: подтверждённый
результат → обычный финал.

Базовая линия `bbb30555` (до S4):

```json
{"A_irrelevant_first": {"llm_calls": 2, "report_is_interim_text": true,
  "partial_marked": false, "research_status": "<no contract>",
  "continuations": "<no contract>", "directive_rounds": 0},
 "B_sufficient": {"llm_calls": 2, "report": "Причина: heartbeat не обновляется.",
  "partial_marked": false}}
```

→ исходный дефект воспроизведён: промежуточный текст публикуется как полный
отчёт, продолжения нет, причина частичности не обозначена.

Кандидат `8ccd0730`:

```json
{"A_irrelevant_first": {"llm_calls": 3, "report_is_interim_text": false,
  "partial_marked": true, "research_status": "partial", "continuations": 1,
  "directive_rounds": 1},
 "B_sufficient": {"llm_calls": 2, "report": "Причина: heartbeat не обновляется.",
  "partial_marked": false, "research_status": "complete"}}
```

→ продолжение предложено и исполнено (1 директива), промежуточный текст не
публикуется, отчёт помечен как частичный с причиной; здоровый чекап остался
двумя вызовами без пометки.

## Тесты и фактические результаты (worktree, offline/test fixtures)

```
py -3 -m pytest tests/test_smart_corrective_completion.py -q
=> 11 passed

py -3 -m pytest tests/test_smart_corrective_completion.py \
  tests/test_tool_loop.py tests/test_checkup_service.py \
  tests/test_checkup_contract.py tests/test_selfdiag_corrective_research.py \
  tests/test_smart_exec_selfdiag.py tests/test_smart_exec_evidence.py \
  tests/test_smart_g_finalize_round1114.py tests/test_smart_exec_ab_round1114.py \
  tests/test_mca11_tool_result_round1028.py \
  tests/test_mca11_chain_stages_round1028.py tests/test_agentic_ai_round1020.py \
  tests/test_agentic_events_round1026.py tests/test_mca23_phase2.py \
  tests/test_smoke_round1016_tool_loop.py tests/test_factcheck_service.py \
  tests/test_factcheck_tools_round1020.py -q
=> 438 passed, 3 warnings (known pytest timeout-config warning)

py -3 -m pytest tests/test_tool_router.py \
  tests/test_smart_corrective_budget_policy.py \
  tests/test_smart_corrective_source_reader.py tests/test_evol_source_reader.py \
  tests/test_smart_e_local_first_source.py tests/test_smart_c1_source_reader_limits.py \
  tests/test_diagnostic_policy.py tests/test_diagnostic_probes.py -q
=> 368 passed, 1 failed (pre-existing, см. ограничения)

py -3 -m pytest tests/test_prompt_readback.py tests/test_tool_schemas.py \
  tests/test_mca19_block_g_round1043.py tests/test_mca20_integration_round1045.py \
  tests/test_direct_chat.py tests/test_asap7_direct_l1.py \
  tests/test_decision_making_round1026.py -q
=> 410 passed

py -3 -m pytest tests/test_checkup_handlers.py tests/test_checkup_prompts.py \
  tests/test_p0_checkup_core_contract.py tests/test_self_diag_golden.py \
  tests/test_caps_tool_results.py tests/test_er08_limits_context.py \
  tests/test_smartmodule_phrases.py tests/test_tool_calling_round1015.py \
  tests/test_tool_coordinator_round1026.py tests/test_direct_chat_handlers.py \
  tests/test_er65_sent_segment_snapshot.py tests/test_payload_builder.py \
  tests/test_p0b_current_question_priority.py \
  tests/test_direct_fallback_recompose_asap32.py \
  tests/test_memory_lookup_round1026.py tests/test_token_analytics_round1023.py -q
=> 653 passed, 8 failed (все 8 идентичны на чистой базовой линии
   `sc/corrective-s3`: см. ограничения)

py -3 -m py_compile services/tool_loop.py services/checkup_service.py
=> OK
```

### Что именно проверяют новые тесты (наблюдаемое поведение)

| Сценарий | Тест | Наблюдение |
|---|---|---|
| Достаточные факты | `test_confirmed_result_ends_immediately` | 2 LLM-вызова, `complete/evidence_sufficient`, 0 продолжений, отчёт байт-в-байт = ответ модели |
| Здоровый чекап | `test_healthy_checkup_without_tool_calls` | 0 tool calls, 1 LLM-вызов, `complete/no_research_needed`, без пометки |
| Нерелевантный первый результат | `test_irrelevant_first_result_gets_continuation` | промежуточный текст не публикуется; директива с пробелом и родовыми вариантами; модель реально сменила запрос; финал подтверждён, `continuations=1` |
| Единичный транзиентный отказ | `test_single_transient_failure_allows_continuation` | повтор с изменёнными аргументами реально исполнен, финал подтверждён |
| Другой доступный инструмент | `test_unavailable_source_allows_other_declared_tool` | при недоступном коде доступна runtime-кросс-проверка; она исполняется; незакрытая область честно названа |
| Неполный фрагмент | `test_incomplete_fragment_continues_from_next_arguments` | продолжение исполнено с `line_start` следующей страницы |
| Пути объективно исчерпаны | `test_denied_only_path_returns_partial_with_cause` | автоматического продолжения нет; отчёт = ответ модели + «это частичный результат» + причина + `read_source_code: недоступен (policy_denied)` |
| Модель отказалась продолжать | `test_model_declines_continuation_and_partial_is_marked` | 1 offer, затем `partial/continuation_not_taken`; пометка «возможность продолжить исследование не была использована» |
| Нет бесконечного цикла | `test_repeated_same_failure_offers_only_once` | один offer; повторный отказ с новыми аргументами не даёт нового offer; `partial/no_progress`; 4 вызова LLM и всё |
| Обычные диалоги | `test_ordinary_dialog_does_not_re_research` | без opt-in: 2 вызова, директивы нет; `research_state` доступен (`partial`, continuation available) |
| Partial сохраняет evidence | `test_partial_keeps_results_refs_and_text` | `tool_results` с `data.source_id`/`provenance`, `tool_context` с фрагментом, `evidence_refs` и `gaps` в state; текст модели не подменён |

## Покрытие строк S4-COMPLETION

| req_id | Статус | Доказательство |
|---|---|---|
| `SC-CMP-DONE-01` | REVIEW | `test_confirmed_result_ends_immediately`, `test_healthy_checkup_without_tool_calls`; probe B: 2 вызова, `complete` |
| `SC-CMP-DONE-02` | REVIEW | `test_irrelevant_first_result_gets_continuation`, `test_single_transient_failure_allows_continuation`, `test_incomplete_fragment_continues_from_next_arguments`: продолжение исполнено и дало подтверждённый/честный результат |
| `SC-CMP-DONE-03` | REVIEW | `_research_gaps`/«пробел закрывается фактом» + `test_confirmed_result_ends_immediately`: подтверждённые результаты без незакрытых пробелов завершают исследование без вызовов; завершённый пробел не блокирует финал |
| `SC-CMP-DONE-04` | REVIEW | `test_denied_only_path_returns_partial_with_cause` (недоступно → partial с cause и неподтверждённой областью), `test_model_declines_continuation_and_partial_is_marked`, `test_repeated_same_failure_offers_only_once` |
| `SC-CMP-CONT-01` | REVIEW | options `refine_query` + текст директивы «уточнить направление поиска»; `test_irrelevant_first_result_gets_continuation` (модель изменила запрос) |
| `SC-CMP-CONT-02` | REVIEW | options `other_candidates`/`refine_query`; тот же тест: второй запрос отличается от первого |
| `SC-CMP-CONT-03` | REVIEW | options `other_candidates` (для incomplete/ambiguous/unconfirmed); `untried_tools` для другого объявленного инструмента |
| `SC-CMP-CONT-04` | REVIEW | `test_incomplete_fragment_continues_from_next_arguments`: `continuation.next_arguments` → реальный `line_start` второго вызова |
| `SC-CMP-CONT-05` | REVIEW | options `alternate_route`; `test_single_transient_failure_allows_continuation` (повтор маршрута после транзиентного отказа) |
| `SC-CMP-CONT-06` | REVIEW | `test_unavailable_source_allows_other_declared_tool`: runtime-инструмент как кросс-проверка/резервный источник; директива «сопоставить данные с другими доступными инструментами» |

Все строки — `REVIEW` (кандидат), не `VERIFIED`: независимое ревью и
production-эталон впереди.

## Ограничения и явно непроверенное

1. **Семантическая релевантность не разбирается.** Контур не анализирует
   текст модели и не решает «файл не тот»: он различает структурные
   состояния (подтверждено/неподтверждено/неполно/отказ/недоступно) и
   предъявляет модели факты; направление продолжения выбирает модель
   (owner §6.4).
2. **Production effective config.** Production-доступ не использовался.
   Новых флагов/DDL/настроек/shadow-режима нет; поведение включается
   первым релизом (чекап opt-in внутри сервиса, обычные диалоги не меняются).
   Effective-state чекапа на проде фиксируется на этапе DevOps/приёмки.
3. **Один честный нюанс отчёта.** Недоступный объявленный источник
   (`denied/terminal`) при подтверждённом другом источнике оставляет
   состояние `partial/source_unavailable` и пометку в отчёте: это осознанно
   (SC-CMP-DONE-04 «недоступные сведения должны быть обозначены»), а не
   дефект продолжения.
4. **Предсуществующие падения тестов на базовой линии** (не связаны с S4,
   воспроизведены на чистом `sc/corrective-s3`):
   - `tests/test_diagnostic_probes.py::TestValidation::test_time_window_is_bounded`
     — тест использовал дату `2026-11-14T00:00:00Z` как «будущую»; на
     2026-11-14 она больше не в будущем (время-зависимый тест, `BACKLOG_ONLY`);
   - `tests/test_tool_coordinator_round1026.py` (2: устаревший canon/allowlist
     release-линии), `tests/test_er65_sent_segment_snapshot.py` (1),
     `tests/test_direct_fallback_recompose_asap32.py` (5) — идентичные
     падения на базовой линии (`BACKLOG_ONLY`, не блокер S4).
5. **Reuse-контракт S3 не менялся**: продолжение по `cursor` идёт через
   существующий Router (S3), S4 только предъявляет модели
   `continuation.next_arguments`/`cursor` в директиве и не изобретает токен.
6. **Live/UI-проверки не требуются** для этого среза: визуальных изменений и
   real-LLM canary в S4 нет (проводка проверяется на детерминированных
   двойниках границы провайдера; существующие проверки чекапа/production —
   этап приёмки).

## Остаточные находки (BACKLOG_ONLY, не в этом кандидате)

- `tests/test_diagnostic_probes.py::test_time_window_is_bounded` —
  время-зависимый тест истёк 2026-11-14; нужно отдельное исправление
  теста (не входит в write-scope S4).
- 8 предсуществующих падений вне write-scope (см. п.4) — для общего прогона
  релизного поезда.

## Хозяйство (workspace)

- Worktree `s4-completion` остаётся зарегистрированным для review
  (commit `8ccd0730`); удаление/закрытие — после join и переноса
  доказательств.
- Один probe-run (`probe-c3dcc5de1a`, kind=probe, unit=s4-completion)
  содержал RED/GREEN probe и логи; результаты промоутированы в этот файл,
  run закрыт `run-close` (см. отчёт агенту).
- Временных копий репозитория/зависимостей не создавалось.
