# UR-26.5 — payload-наблюдаемость стадий Summary (implementation evidence)

Кандидат: ветка `ur/26-summary-payloads`, HEAD `9c323ec4`
(база `df02ab0c` = tip `evol/impl`, включая фикс full-text ledger `d4116ed7`).
Автор: Builder-срез UR-26 summary payloads (UR-G payload matrix, строка
UR-30.4/ACC-E4, summary-нога).

## 1. Что реализовано

Единый строитель append-only stage-событий §50.54 + payload-наблюдаемость
(R17-safe: числа/коды/id/digest, без сырых текстов):

| Поле события | Смысл | Источник конвенции |
|---|---|---|
| `model` / `provider` | модель и host провайдера (без пути/ключа) | summary_run_log.provider_host |
| `finish_reason` | код завершения стадии (parsed/validated/llm_* /deterministic) | new (коды) |
| `usage` | `{input_tokens, output_tokens}` | _extract_usage (writer/clusterizer) |
| `chars` | размер сырого ответа стадии | число |
| `text_digest` | digest сырого текста стадии | turn_trace.text_digest (blake2s 16 hex) |
| `document_digest` | digest канонического plain-рендера документа (полный delivered-текст) | format_plain_text (UR-23.4 ledger tie) |
| `clock` | наличие ChatClock-блока в фактическом outbound payload + честные skip-коды | chat_clock.outbound_clock_meta / log_clock_call |
| `decision` | явный код решения (writer_ok / correction_retry:defect=X / repair_applied:N / repair_not_needed / repair_failed / verdict=… / revision_applied / l1_<status>) | new (никаких молчаливых fallback) |

## 2. Где эмитится каждая стадия (file:line на кандидате 9c323ec4)

* **Общий строитель**: `services/summary_stage_events.py` — `build_event` :91,
  `clock_meta` :54, `record` :72, `document_plain_digest` :45,
  `text_digest` (turn_trace-конвенция) :127.
* **stage1 `l1_plan`** (L1 clusterizer): `services/summary_l1_clusterizer.py`
  — empty-путь :1898 (честный `skip_reason=no_llm_call`), LLM-error :1979,
  финальное событие :2304 (status/usage/chars/digest/clock/decision).
* **stage2 `l2_writer`** (L2 writer): `services/summary_l2_writer.py`
  — transport-error :1714/:1727, correction-ошибка :1794/:1813, финальное
  событие :1880 (usage/chars/text_digest/document_digest/clock/decision).
* **repair** (детерминированный ремонт, внутри validate): там же —
  `repair_applied:N` / `repair_not_needed` :1895, `repair_failed` /
  `repair_not_applicable` :1910.
* **reviewer/revision**: `services/summary_l2_review.py` — `_stage_event`
  расширена :950 (новые поля), `_payload_clock_meta` :1021 (мета строится по
  реконструированному ФАКТИЧЕСКОМУ outbound payload'у после attach),
  reviewer success `decision="verdict=<status>"` :1315, revision
  `decision="revision_applied"`/`revision_invalid:<reason>` :1601 (3 ветки
  ревизии: targeted_batch :1468, targeted :1515, patch/full_doc :1552).
* **supervisor**: `services/summary_llm_supervisor.py` :755 — наличие
  clock-блока в counts события `llm_activity` (start); остановки уже кодами:
  `provider_stalled` / `execution_deadline_exceeded` /
  `retry_time_budget_exhausted` (существующие события, доказаны тестом).
* **Inspector-проекция**: `services/execution_graph_source.py` :64 —
  allowlist `_STAGE_EVENT_KEYS` дополнен (finish_reason/usage/chars/
  text_digest/document_digest/clock/decision).
* **Генератор**: ctx проброшен во все вызовы-точки, где ctx в scope:
  run_l1 (главный hybrid), run_l2 (writer-source/overflow-fit/paged/master/
  hierarchical-сегменты/merge `_merge_writer_documents`).

ΔDDL=0: существующий in-memory `RunContext.stage_events` + проекция
Inspector; durable `summary_run_stages` не расширялся; новых таблиц нет.

## 3. Тесты (candidate-bound)

`tests/test_ur26_summary_payloads.py` — 12 тестов, все LLM-каналы
инжектированы (0 сетевых):

* (a) нормальный прогон: stage1+stage2 события с usage/chars/digest/clock
  (phase=plan / phase=answer), model/provider; полный review-прогон несёт
  writer+reviewer события; R17-guard — в JSON событий нет текстов чата/статьи.
* (b) revision: `decision="revision_applied"` + verdict reviewer кодом.
* (c) repair: S1-дефект → `repair_applied:N`; чистый документ →
  `repair_not_needed` (explicit).
* (d) supervisor: watchdog-остановка — события с кодами `provider_stalled` и
  `retry_time_budget_exhausted`; start-событие несёт `clock_included`.
* (e) digest = ПОЛНЫЙ delivered-текст: документ >20000 символов,
  `document_digest == text_digest(format_plain_text(document))` и
  `!= text_digest([:20000])` (мутация старого ledger-бага красная).
* (f) мутации (проверены на кандидате, затем откачены):
  удаление emission stage2 → 3 теста красные;
  «тихий» repair (событие удалено) → 2 теста красные.

Команды и результаты на кандидате `9c323ec4`:

```
pytest tests/test_ur26_summary_payloads.py -q                      → 12 passed
pytest tests/test_ur26_summary_payloads.py tests/test_summary_generator.py -q
                                                                   → 75 passed, 2 failed (Epic60, pre-existing)
pytest tests/test_ur_c_clock.py tests/test_asap44_l2_review_closure.py
  tests/test_asap8_f1_summary_l2_repair.py tests/test_summary_supervisor_asap41.py
  tests/test_summary_anchors_wiring_asap42.py tests/test_ur_g_acceptance.py
                                                                   → 129 passed
полный sweep tests/test_summary*.py (65 файлов)                    → 1462 passed, 6 failed (все pre-existing, см. §4)
```

Обновлённый существующий тест: `tests/test_summary_wave_d_asap4.py::
test_review_loop_records_stage_events` — append-only журнал стадий теперь
закономерно содержит l2_writer/repair (UR-26.5); порядок review-цикла
проверяется подпоследовательностью `["l2_reviewer","revision","l2_reviewer"]`
(сила исходной проверки порядка сохранена).

## 4. Классификация pre-existing падений (проверены на чистой базе df02ab0c)

| Тест | Статус на базе | Классификация |
|---|---|---|
| `test_summary_generator.py::TestEpic60RunningSummary::test_below_ratio_no_trigger` | FAILED | unrelated/pre-existing (Epic60 trigger-ratio; путь не тронут срезом) |
| `test_summary_generator.py::TestEpic60RunningSummary::test_expired_summary_stays_then_retriggers_on_new_messages` | FAILED | unrelated/pre-existing (Epic60) |
| `test_summary_asap2_failsoft_round1027.py::test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback` | FAILED | unrelated/pre-existing (rich-publish мок не awaited; публикационный шов, не payload-стадии) |
| `test_summary_two_call_round1022.py::TestSummaryTwoCall::{test_editor_then_narrator, test_validator_loop_retry, test_validator_exhausted_keeps_best}` | FAILED ×3 | unrelated/pre-existing (legacy `_llm_generate` editor/narrator/validator; срез этот шов не менял) |

## 5. Честные границы среза (для Reviewer)

* Закрыта **summary-нога** payload-матрицы UR-30.4/ACC-E4: reviewer/repair/
  supervisor/stage1/stage2 события + payload-тесты. Repair — детерминированная
  стадия (LLM-вызова нет) ⇒ clock-block не применим по определению; это
  документированный невидимый режим, решение видно кодом `decision`.
* Строки **UR-26.3** (Initiative: tool/Web Search, recheck при смене даты,
  prepared_text Nostalgia) и **UR-26.4** (Factcheck: tool-loop, короткие
  ответы, temporal_verdict/verbalize) — ДРУГИЕ пайплайны, этим срезом не
  закрываются; payload-тесты factcheck stage1/stage2 (упомянуты в
  blocked-заметке UR-30.4) в этот срез не входили и остаются открытыми.
* Lossless-chunked L1 (`_run_l1_lossless`) и legacy `_llm_generate` —
  отдельные швы: chunked-путь не эмитит l1_plan-событие (стандартный
  single-pass эмитит); legacy прикрыт существующим
  `TestSummaryClock.test_generator_llm_generate_attaches_answer_block`.

## 6. Дозакрытие подсаб-итом (слайс ur/26-5-deferred, кандидат 574a11c4)

Оба «честных открытых подсаб-итема» строки UR-26.5 закрыты; матрица выше
остаётся в силе (тот же кандидат 4dca6439, файл событий не менялся).

* **(a) Deferred generator.** `summary_generator._llm_generate`: retry-once
  после дефер-паузы (`SUMMARY_RETRY_ONCE_PAUSE`) обновляет answer-блок —
  `chat_clock.ensure_answer_snapshot` (правило минуты: та же минута → reuse,
  пересечение минуты/даты → новый снапшот) + новый helper
  `chat_clock.refresh_time_context` (замена блока в том же последнем
  user-сообщении; payload вне блока байт-в-байт прежний —
  `summary_window_end_utc` не пересобирается задним числом).
  Тесты: `TestDeferredGeneratorFreshAnswerClock` (перевод минуты → свежий
  as_of_utc на повторной попытке; окно неизменно; мутация «заморозить блок
  через дефер» → red; та же минута → reuse → идентичные payload).
* **(b) Chunked-L1 overflow.** `_run_l1_lossless` эмитит финальное
  `l1_plan`-событие (те же поля: model/provider/finish/usage/chars/
  text_digest/clock) с честной пометкой сборки из чанков:
  `finish_reason="chunked_merge"`, `decision="l1_ok_chunked"` (провалы:
  `l1_error_chunked`, `chunked_all_failed`/`chunk_run_failed`); usage —
  сумма по сегментным событиям, clock — от фресшего сегмента, digest/chars —
  по merged-плану. Дополнительно устранён разрыв прод-wiring: `ctx` теперь
  прокидывается `run_l1 → run_l1_capacity_first → _run_l1_lossless →
  сегментные run_l1` (раньше прод-путь whole-window/capacity-first терял ctx
  и stage1-события не эмитились вовсе; evidence 4dca6439 собирался прямыми
  вызовами run_l1 с ctx). Тест: `TestChunkedL1OverflowPlanEvent`
  (маркер asap41): ≥2 сегментных l1_plan + финал chunked_merge; мутации
  «не эмитить на overflow» и «не прокидывать ctx» → red.
* **Прогон среза:** `pytest tests/test_ur26_summary_payloads.py
  tests/test_summary_generator.py -q` → 78 passed, 2 failed — оба Epic60
  pre-existing (§4; воспроизведены на базе c5a97f6e без изменений слайса).
  Затронутые швы: `tests/test_ur_c_clock.py` + L1 chunked/capacity/semantic/
  wave + asap8/asap44/ur_d_writer → 280 passed, 0 failed.
