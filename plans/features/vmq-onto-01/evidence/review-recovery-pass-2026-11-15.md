# REVIEW RECOVERY PASS — VMQ-ONTO-01 / VMQ-MEM / VMQ-MEM-TIME (2026-11-15)

Независимый Reviewer: DeepSeek V4 Pro (`opencode-go/deepseek-v4-pro`), сессия `ses_e228ff98bffeLLjuKDL1tR7BNp`.
Проверенный код: `2b419aa2` (release/vmq-onto-01-2.58.204, deployed 2.58.204), worktree `vmq-onto-01-review-r1`, чистый.
Baseline происхождения: `c97c06e4` (2.58.203). Карта/plan/evidence читались из канонической плановой линии.
Вердикт сохранён без изменений; Reviewer не редактировал продукт/тесты/планы.

## Результат

| Срез | Вердикт |
|---|---|
| ONTO-A `8cb9e00d` | Approved |
| ONTO-B `d15b13da` | Approved |
| M2 / O-04 `f7a9c596` | Approved |
| Slice A `570a49db` | Approved |
| Slice B `d159ea8a` | Approved |
| Slice C `16931216` | Approved (evidence bookkeeping gap — см. ниже) |

Проверенные контракты: обязательный `chat_scope` для всех типов/связей и изоляция чатов; UID-first идентичность, speaker≠subject, `source_ref_id`; направление отношений и provenance; время обновления ≠ время возникновения; co-occurrence не факт, legacy помечен, конфликты определений видимы; единственный `retrieve()`, один `RetrievalResult`/`EvidenceBundle`, без второго retrieval/LLM/store/composer; temporal intent и person overview; явный год ограничивает материал (2025/2026 не выдаются за 2023); unknown-year не выдаётся за событие года; SQL-окно вместо пост-фильтра top-N; vector admission fail-closed; bounded historical soft fallback и multi-year quota; разделение фактов о человеке, его сообщений и слов других; хронология из подтверждённых событий; `Old_Episode` с целевым окном; структурированный overview trigger, «что сейчас» без обзора, отсутствие наследования historical intent; доставка overview в bundle/Writer.

## Независимые прогоны и контрпримеры

- `test_vmq_mem_period_intent` + `test_vmq_mem_slice_b` + `test_vmq_mem_slice_c`: **56 passed**.
- `test_semantic_contracts` + `test_memory_unified_retrieval` + `test_mem_time_policy`: **100 passed**.
- `test_tool_coordinator_round1026` + `test_unified_image_request_round1026`: **4 failed / 75 passed** — ровно 4 известных pin-guard failure.
- Контрпример 1: все 4 типа без `chat_scope` → tentative/unknown, не verified.
- Контрпример 2: пул 2023+2026+unknown при intent 2023 → принят только 2023, `dropped_out=1`, `dropped_unknown=1`.
- Контрпример 3: «что происходит в чате сейчас» → `none`/`wants_overview=False`; owner-запрос → `historical`/`True`.
- Повторно подтверждены ранее задокументированные мутации (не перезапускались): chat_scope removal 12 failed/29 passed; `wants_overview=False` 10 failed/5 passed; cooccurrence→fact 2 failed/39 passed.

## Находки

1. **4 pin-guard failure — BACKLOG_ONLY, не регрессия VMQ.** `test_tool_coordinator_round1026` и `test_unified_image_request_round1026` падают из-за накопленного дрейфа после baseline `pre-round1026-a1`: 18-й инструмент `prompt_readback` уже присутствует в `c97c06e4`; `tool_schemas.py` не менялся в поезде; `web/` не менялся (`git diff c97c06e4..2b419aa2 -- web/` пуст). Это устаревший структурный guard, не дефект кандидата.
2. **Slice C evidence — EVIDENCE_GAP bookkeeping.** Код Slice C в поезде байт-идентичен одобренному (`git diff 16931216 8bc2bcf7 -- services/ tests/` пуст), но evidence-трио и corpus/measurement/root-cause файлы привязаны к `8bc2bcf7` и отсутствуют в дереве `2b419aa2`. Продуктового дефекта нет; PM обязан держать evidence на плановой линии и не заявлять его наличие в frozen release tree. Ранее уже зафиксировано в `delta-review-r1.md`.
3. **Живая векторная нога — UNVERIFIED.** KNN с рабочим провайдером в среде недоступен (`EMBED_API_FAILED provider_unavailable`); live admission не доказан.
4. **Живая доставка M-04/O-04 overview в реальном ходе — UNVERIFIED.** E2E на копии БД подтверждает поля bundle, но не живой systemd/L1 и не текст итогового ответа.

## Ограничения

Полный 20k-suite не запускался. Текст итогового ответа не оценивался — проверена доставка полей в bundle/Writer. Реальная полнота субъектной идентичности P1 частично доказана (refs 15612/15856 не разрешены как P1).

## Вывод

Прежних доказательств достаточно для review/predeploy-уровня по всем шести срезам; статусы карты этим проходом не повышаются. Не считать подтверждёнными: живую векторную ногу/live admission, живую доставку M-04/O-04, live-полноту субъекта P1. Блокеров для продолжения очереди нет.
