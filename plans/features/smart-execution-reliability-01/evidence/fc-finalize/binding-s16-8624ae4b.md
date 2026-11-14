# S16-FC-FINALIZE — binding evidence

| Параметр | Значение |
|---|---|
| Задача | `SMART-EXECUTION-RELIABILITY-01` (дополнение FACTCHECK-REQUEST-INTEGRITY v2) |
| Срез | `S16-FC-FINALIZE` — финализация: ответ по предмету, честный частичный результат, чистая речь, пропорциональность |
| Ветка | `smart/fc-s16-finalize` |
| Кандидат | `8624ae4b` (первый коммит среза `34777177`); HEAD ветки после evidence-коммитов — `47d1ee74`, код среза не меняется |
| База S16 | `d8f50a68` = merge `cffc9fb2` (G/S7, объявленная зависимость) в `9a89e3da` (S15) |
| Зависимости | `9a89e3da` (S15) и `cffc9fb2` (G/S7) присутствуют в истории `8624ae4b` |
| Требования | `SFC-9-01`, `SFC-9-02`, `SFC-9-03`, `SFC-9-04`, `SFC-10-06` (43 строки карты `requirements-map-fc-amendment.json`) |
| Источник | `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md` §9.1–9.4, §10.6 |

Изменяемая область: `services/factcheck_service.py`, `services/factcheck_renderer.py`,
`tests/test_factcheck_finalization.py`, `plans/features/smart-execution-reliability-01/evidence/fc-finalize/**`.
`services/factcheck_prompts.py` намеренно не менялся: правка канона требует новой
версии реестра (`prompt_registry.py` вне write-scope). Новых LLM-стадий нет.
Общий механизм завершения инструментального исследования родительского эпика
(G, `direct.tool_finalize`) не дублируется и не переопределяется: factcheck не
создаёт второго механизма, а на tool-loop вызовах действует существующий
финальный контракт G с неизменной печатью (`8edac2662468`).

## 1. Трасса фактического поведения (до правки, база `9a89e3da`)

Проверено прогонами `check_claim_envelope` с двойниками LLM/search на четырёх
сценариях (сырые логи: `raw/probe-base-9a89e3da.txt`, скрипт `raw/probe_s16.py`):

1. **Предмет проверки терялся на финализации.** При вопросе о связанной части
   (`subject.text` = вопрос, `material_claim_text` = исходное сообщение) в payload
   аналитика и вербализатора уходил только `<claim>` = вопрос. `request_text`,
   `form_request` и `material_claim_text` в промпты не попадали вообще:
   `grep` по `services/` показывал их использование только в S13-резолвере
   предмета, не в стадиях ответа. Проверять «второе утверждение» было нечем.
2. **Техническое прерывание при собранном evidence давало заглушку.** Остановка
   поиска бюджетом с 3 evidence-строками и недоступным вербализатором давала
   `Недостаточно данных для полной проверки утверждения. Дата оригинала: …` —
   evidence оставался только в durable-строках, в ответ не попадал.
   `classify_retrieval` законно возвращает `ok` при любом evidence, поэтому
   техническая граница поиска не доходила ни до вербализатора, ни до ответа
   (в payload вербализатора не было ни `situation`, ни оговорки).
3. **Служебные метки могли выйти в речь.** `_egress_clean` в оркестраторе срезал
   только латинские имена полей; значение enum (`insufficient_evidence`),
   `ev-N`, `claim c1`, `p1` и сырой `<chat_context>`-контейнер оставались.
   Отдельный эффект: цифры из `ev-1`/`p2` считались «непроверенными числами», и
   живой ответ целиком заменялся формализованным структурным отчётом.
4. **Пропорциональность уже соблюдалась:** короткий ответ проходил как есть,
   длинный не обрезался (`max_symbols` — потолок генерации, не целевая длина).
5. **Контракт стадий уже соблюдался:** ровно
   `temporal_verdict → temporal_validator → temporal_verbalize`, без третьей
   обязательной стадии; печати канона голоса совпадали с реестром
   (`prompt_registry.seal_integrity() == {}`).

## 2. Что изменено

### `services/factcheck_service.py`

- `partial_inventory(...)` / `partial_inventory_has_content(...)` /
  `partial_inventory_lines(...)`: честное разделение уже полученного результата
  на подтверждённое / опровергнутое / подтверждённое частично / недостаточно
  подтверждённое / технически непроверенное. Когда разбора частей нет, но
  материалы собраны, перечисляются только фактически полученные выдержки
  (до 3, по 160 символов, с хостом) — без выводов и без источников, которых не
  было. Часть без содержательного вердикта не получает придуманный статус.
- `_search_boundary_situation(...)`: техническая граница поиска (бюджет/дедлайн)
  при непустом evidence доходит до финализации человеческой фразой; факт
  добавляется в `uncertainty["search_boundary"]`, `situation` вербализатора и
  детерминированный частичный ответ.
- `_temporal_user_payload` (аналитик) и `_temporal_validator_payload` (валидатор):
  `<original_material>` и `<user_request>` добавляются, только если предмет —
  не сам материал и вопрос не совпадает с предметом (без дублей). Предмет
  проверки остаётся тем же `claim`; вопрос получает приоритет, потому что он и
  есть предмет, а материал виден проверке.
- Payload вербализатора: `original_material`, `user_request`, `requested_form`
  (только при наличии, только данные существующей стадии), `partial` +
  `partial_note` для неполного разбора. При содержательном частичном результате
  `limit_note` («назови ограничение») больше не подменяет ответ; при полностью
  пустом результате прежняя короткая честная граница сохранена.
- `_temporal_fallback_text` (вербализатор недоступен): при собранном результате
  выдаёт честное разделение и собранные материалы вместо заглушки; техническая
  причина поиска называется дословно прежней фразой (`истёк лимит времени…`,
  `поисковые сервисы не ответили…`), повтор ограничения снят. Заглушка остаётся
  только когда результата действительно нет.
- `strip_service_tokens(...)`: граница пользовательской речи — срезает служебные
  присваивания (`reason_code=…`), enum-литералы, внутренние ID (`ev-N`,
  `claim…`, `p1`, `c1`), имена схемы (`claim/claims/part/parts`), `OCR` и сырые
  контейнеры (`<chat_context>`, `<analysis_context>`, `<evidence_delivery>` и
  т.п.). Применяется к тексту вербализатора ДО проверки чисел (иначе `ev-1`
  вызывал структурный отчёт) и к legacy-финализации. Ответ, от которого остались
  только разделители, не публикуется — берётся честный частичный результат/ошибка.
- `_finalize_text`: та же чистка на одиночном legacy-пути.

### `services/factcheck_renderer.py`

- `_content(...)`: последняя граница перед сериализацией — тело и `notice`
  проходят ту же чистку служебных меток (идемпотентно; нормальный текст и факты
  не меняются). Заголовки/ссылки/структура не тронуты.

### `tests/test_factcheck_finalization.py`

12 контрактных тестов (не вакуумных): предмет всего сообщения и связанной части,
честный частичный результат при бюджетном прерывании, инвентарь вербализатора
вместо `limit_note`, техническая часть не выдаётся за «нет данных», прежняя
фраза при полном отсутствии результата, отсутствие enum/ID/OCR-контейнеров
(включая legacy-путь и renderer), служебный дамп не публикуется вместо ответа,
короткий/длинный ответ без нового потолка, отсутствие третьей стадии и
сохранение байтов канона (печати `45361c23221c`/`ed4c7a642804`/
`dcbd765fb860`/`cfcd9009df17`, `seal_integrity() == {}`).

## 3. Требования → доказательства

| Требование | Доказательство |
|---|---|
| SFC-9-01 | `test_no_third_llm_stage_or_editor_and_voice_canon_bytes_kept`: ровно 3 существующих шага, ответ вербализатора публикуется байт-в-байт, печати промптов и `seal_integrity()` не изменились; новых модулей/стадий/шаблонов нет |
| SFC-9-02 | `test_whole_message_is_the_subject_without_duplication`, `test_related_part_question_sees_material_and_request`: материал и вопрос видны аналитику/валидатору/вербализатору; ответ — живой текст вербализатора, без обязательного раздела/объявления предмета |
| SFC-9-03 | `test_budget_interruption_keeps_evidence_and_splits_honestly`, `test_verbalizer_receives_partial_inventory_not_limit_stub`, `test_technical_part_is_not_reported_as_no_data`, `test_empty_research_still_reports_the_technical_cause` |
| SFC-9-04 | `test_short_fact_gets_short_answer_and_long_publication_is_not_capped`: короткий ответ не дополняется, длинный не обрезается; новых min/max нет |
| SFC-10-06 | `test_service_enums_ids_and_ocr_context_never_reach_the_user`, `test_service_only_answer_is_not_published_as_the_answer`, `test_renderer_strips_service_tokens_from_verdict_text`, `test_legacy_single_path_also_keeps_service_tokens_out` |

## 4. Команды и результаты

Python: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, worktree среза.

| Проверка | Команда | Результат |
|---|---|---|
| RED на базе `9a89e3da` | `pytest tests/test_factcheck_finalization.py -q` (файл скопирован в worktree базы) | **8 failed, 4 passed** (`raw/pytest-red-base-9a89e3da.txt`) |
| Фокус кандидата `8624ae4b` | `pytest tests/test_factcheck_finalization.py tests/test_factcheck_renderer_cfg06.py tests/test_factcheck_service.py tests/test_factcheck_evidence_delivery.py tests/test_factcheck_subject_contract.py tests/test_factcheck_prompts.py tests/test_rlr_factcheck_numeric_stage.py tests/test_factcheck_p0_fc.py tests/test_factcheck_orchestrator_cfg06.py tests/test_factcheck_post_release_w1.py -q` | **240 passed** (`raw/pytest-focused-8624ae4b.txt`) |
| Та же выборка на базе `d8f50a68` (без нового файла) | см. raw | **228 passed** (`raw/pytest-focused-base-d8f50a68.txt`) |
| Широкий фактчек-контур | `pytest tests -q -k "factcheck or smart_g or smart_ab"` | **782 passed, 1 failed** (`raw/pytest-factcheck-broad-8624ae4b.txt`); падение `test_factcheck_fc_r1_fix.py::TestRelevanceCascade::test_all_irrelevant_is_honest_failure` воспроизводится на базе в том же комбинированном прогоне (сеть/порядок), в изоляции зелёный на обеих линиях — не дефект кандидата |
| Пробелы/переводы строк | `git diff --check d8f50a68 HEAD -- services tests` | **пусто, exit 0** (`raw/git-diff-check-d8f50a68.txt`); дифф к базе S16: 0 CR, 0 CRLF; три файла среза — LF (`raw/whitespace-and-blobs.txt`) |
| `-w` не скрывает изменений | сравнение нормализованных added/removed строк `git diff` и `git diff -w` к `d8f50a68` | множества совпадают (714/22) — скрытых whitespace-правок поведения нет |
| Сравнение с `9a89e3da` | `git diff --check 9a89e3da HEAD -- services tests` | 46 предупреждений trailing whitespace — все в файлах зависимости G/S7 (`prompt_registry.py`, `tool_loop.py`, `tests/test_agentic_ai_round1020.py` и др.), у которых CRLF существовал уже в `9a89e3da`; файлы S16 чистые (`raw/git-diff-check-9a89e3da.txt`, `raw/changed-files-vs-9a89e3da.txt`) |

## 5. Мутационные проверки (кандидат `8624ae4b`)

| Мутация | Диff | Результат |
|---|---|---|
| A: `elif has_partial` → `elif False` (возврат заглушки) | `raw/mutation-a-8624ae4b.diff` | RED: `test_budget_interruption_keeps_evidence_and_splits_honestly` (`raw/mutation-a-8624ae4b.txt`) |
| B: `strip_service_tokens` → no-op | `raw/mutation-b-8624ae4b.diff` | RED: 4 теста утечки/чистки (`raw/mutation-b-8624ae4b.txt`) |
| C: убрать `original_material`/`user_request` из payload вербализатора | `raw/mutation-c-8624ae4b.diff` | RED: `test_related_part_question_sees_material_and_request` (`raw/mutation-c-8624ae4b.txt`) |
| D: игнорировать границу поиска (`search_boundary = ""`) | `raw/mutation-d-8624ae4b.diff` | RED: 2 теста частичного результата (`raw/mutation-d-8624ae4b.txt`) |

## 6. Конфигурация и режимы

- `SYSTEM2_FACTCHECK_ENABLED` (default `True`): новые поля payload одинаковы для
  двухвызовного и одиночного пути; legacy-тест выполнен в эффективном default-режиме.
- `SMART_VERBALIZER_MODES_ENABLED` (default `True`): добавлены только поля данных;
  байты промптов OFF/ON не менялись (печати совпадают), поэтому OFF-путь получает
  те же данные и не меняет речевой контракт.
- Флаги/значения бюджетов фактчека не менялись; S16 не вводит master-выключателей.
- Production effective-state не проверялся в этом срезе (postdeploy, S17).

## 7. Остаточные пункты (не блокируют S16)

- `live_required=false` у всех 43 строк S16; реальная приёмка сценариев 12.1–12.8 и
  наблюдаемость §13 — S17 (Reviewer+DevOps), один релизный поезд с S12.
- Осознанно не менялись: системные промпты (нужна новая ревизия реестра —
  `prompt_registry.py` вне write-scope) и `factcheck_prompts.py`.
- Известное ограничение чистки: если модель вернула только цитатный обрывок без
  служебных меток (синтетический случай), он публикуется как есть — контракт
  «служебные метки не выходят» соблюдён, но осмысленность ответа обеспечивает
  вербализатор, а не постобработка. При полностью служебном дампе берётся
  детерминированный частичный результат.

## 8. Побочные наблюдения / backlog

- `tests/test_factcheck_fc_r1_fix.py::TestRelevanceCascade::test_all_irrelevant_is_honest_failure`
  падает только в комбинированном прогоне `-k factcheck…` и идентично падает на базе
  — предсуществующая зависимость от порядка/сети, вне scope S16.
- Файлы зависимости G/S7 содержат CRLF (существовали до S16): сравнение с `9a89e3da`
  показывает их trailing whitespace; нормализация — вне write-scope S16.

## 9. Сырые логи

- `raw/probe_s16.py` — воспроизводимый сценарий (весь материал / связанная часть /
  бюджет + evidence / утечка / длина).
- `raw/probe-base-9a89e3da.txt`, `raw/probe-candidate-8624ae4b.txt` — трасса до/после.
- `raw/pytest-red-base-9a89e3da.txt` — RED на базе.
- `raw/pytest-focused-8624ae4b.txt`, `raw/pytest-focused-base-d8f50a68.txt` — фокус.
- `raw/pytest-factcheck-broad-8624ae4b.txt` — широкий прогон.
- `raw/mutation-*-8624ae4b.{diff,txt}` — мутации и их RED.
- `raw/git-diff-check-*.txt`, `raw/whitespace-and-blobs.txt`, `raw/git-diff-stat.txt`,
  `raw/changed-files-vs-9a89e3da.txt`, `raw/candidate-log.txt` — git/пробельная гигиена.
