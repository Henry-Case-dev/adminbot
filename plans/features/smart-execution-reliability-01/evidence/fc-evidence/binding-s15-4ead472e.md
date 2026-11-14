# S15-FC-EVIDENCE — binding evidence (кандидат 4ead472e)

Срез: `S15-FC-EVIDENCE` (FACTCHECK-REQUEST-INTEGRITY v2 §7–§8/§10.3,
SMART-EXECUTION-RELIABILITY-01, wave9).
База среза: `80c83d24` (S14) + зависимости `b1f7609e` (S3-EVIDENCE) и
`da830157` (S4-CAPACITY).
Ветка: `smart/fc-s15-evidence`.
Код-кандидат: `4ead472e` (sha256 `services/factcheck_service.py`
`7fc89d9996105035…`, `tests/test_factcheck_evidence_delivery.py`
`efdd2b5e224666cb…`).
Evidence-коммиты после кода (`c5e87342` + этот binding) не меняют поведение;
reviewer смотрит HEAD ветки.
Источник: `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md`
(§7.1–7.5 строки 700–767, §8.1–8.3, §10.3).
Покрытие: 10 req_id (`SFC-7-01…7-06`, `SFC-8-01…8-03`, `SFC-10-03`),
81 строка карты (`requirements-map-fc-amendment.json`: 8+3+5+2+7+12+20+5+8+11).

## 1. Что изменено (срез S15, диф от `da830157`)

| Файл | Изменение |
|---|---|
| `services/factcheck_service.py` | `RouteCapacity`/`EvidenceDelivery`; `_client_route` читает ФАКТИЧЕСКИЕ `_chat_model/_base_url` и `_fallback_model/_fallback_base_url` клиента; `_route_capacity` → единый резолвер `model_capacity.resolve_evidence_window_tokens(model, base_url)` (окно и output-резерв отдельно); `_pack_evidence` — порция по ёмкости, без caps 20 строк/1200 символов, остаток указателями; `_evidence_delivery` — полный support из ref, provenance `source_kind/opened/strength`, `refs_only` для веб-прогона; `_evidence_context_note` — запрет вывода «доказательств нет» при остановке поиска бюджетом/deadline, доходит до analyst И validator; `fallback_payload_adapter` recompose под ёмкость фактического fallback-маршрута; `evidence_diagnostics` += `evidence_delivery`, `stop_reason`, `fetch_skipped_budget`; `_temporal_max_evidence` сохранён только как аварийный degrade при неизвестной ёмкости |
| `services/factcheck_attribution.py` | атрибуционная цитата больше не режется cap 400; `message_text` помечен как диагностический (не evidence) |
| `services/factcheck_orchestrator.py` | durable-запись сохраняет РОВНО доставленные строки (`max_evidence=len(run.evidence_rows)`), а не прежний потолок 20 |
| `services/llm_client.py`, `services/source_reader.py`, `tests/test_evol_source_reader.py`, `tests/test_smart_c1_source_reader_limits.py` | только перевод CRLF→LF (содержимое байт-в-байт, см. §7) |
| `tests/test_factcheck_evidence_delivery.py` | новый CONTRACT-набор, 12 тестов |
| `evidence/fc-evidence/raw/*` | скрипты и сырые результаты (аудит, RED, мутации) |

Классический 16384 в фактчеке отсутствует: `assignments_16384 = 0`, а
`resolve_evidence_window_tokens` требует фактический маршрут
(`raw/audit-candidate-c5e87342.json`, `caps`).

## 2. Аудит восьми звеньев (SFC-7-06)

Факты — из кода кандидата и трёх прогонов одного и того же probe
(`raw/s15_audit_probe.py`) на `d20a7f73` (deployed), `80c83d24` (база) и
`c5e87342` (кандидат): `raw/audit-deployed-d20a7f73.json`,
`raw/audit-base-80c83d24.json`, `raw/audit-candidate-c5e87342.json`.
Различия в выводе = различия кода, окружение одно (без сети/БД).

| # | Звено | Где | Что ограничивает СЕЙЧАС | Факт deployed → база → кандидат |
|---|---|---|---|---|
| 1 | поиск → результаты | `search_aggregator.SearchAggregator.search_relevant` (каскад tavily→exa→ddg, остаток общего бюджета каждому уровню), `factcheck_planner.run_retrieval` | текст запроса ≤200 симв. (технический предел провайдера); запросов 12 → 64; deadline 10/45 c → 120/600 c; порция `search_text` 8000 → 100 000 | 12 / 10 c / 8000 → 64 / 120 c / 100000 → то же (S14, зависимость) |
| 2 | кандидаты → EvidenceMap | `evidence_refs_from_search` (20 результатов на страницу), `_assemble` | потолок 12 ссылок молча выбрасывал найденное (deployed) | 12-потолок есть → снят (S14) → снят; совпадает |
| 3 | открытые страницы | `execute_retrieval` → SafeFetcher, `primary_fetches` | открытий ≤2, excerpt ≤600 только для открытых (ON) / без обрезки (OFF); отказы считаются `fetch_errors`, пропуски — `fetch_skipped_budget/deadline` | то же → то же → то же; S15 НЕ менял политику открытий (это S14) |
| 4 | извлечённый материал → строки evidence | `temporal_factcheck.evidence_rows_from_refs/results`, `_evidence_delivery` | `support[:1200]` резал выдержку (deployed/база); `_evidence_delivery` восстанавливает полный support ref | `wide-12x2000`: 14902 симв. (все 1200-срезы) → 14902 → **26689** (2000 без обрезки) |
| 5 | EvidenceMap → payload | `_temporal_user_payload` (`<evidence>` + мета `claim=`) | до S15 — только текст, без provenance; 20 строк | `opened=`/`source=` нет → нет → **есть** (`opened=yes/no`, `source=secondary`, `strength`) |
| 6 | coverage | `ClaimCoverage` (candidates/opened/evidence/citation_ids) | не менялось | analyst получает `<claim_coverage>`; validator — evidence+границу доставки (существующий контракт) |
| 7 | analyst payload | `_temporal_user_payload` + `_evidence_delivery` | потолки 20/1200/8000 при неизменной ёмкости маршрута | 60 refs: 20 строк и 24230 симв. в ответ на маршрут 3000 токенов → то же → **2 строки + 58 в remainder**, 2457 симв., `capacity_unknown=false` |
| 8 | validator → verbalizer → ответ | `_temporal_validator_payload`, `stage2_payload` | validator: те же строки, без provenance и без границы поиска | validator 12 строк и в базе, и в кандидате; в кандидате — provenance + оговорка бюджета; verbalizer по существующему контракту L1→L2 получает JSON анализа, не сырой evidence (прежний cap 8000 к нему не применялся) |

Ключевые замеры доставки (`audit-candidate`, дефолт-ёмкость 1 000 000 токенов):

- `fb-production-single-snippet`: 1 строка, 209 симв. поддержки, analyst 312
  симв. секции, `opened=yes`, оговорка бюджета присутствует;
- `wide-12x2000`: 25 671 симв. evidence → 12 строк, 26 689 симв. секции, без
  `evidence_delivery` (всё поместилось, искусственной обрезки нет);
- `overflow-60x900` (окно 3000): 2 доставленные строки (2272 симв.), 58 ID/URL
  в `<evidence_delivery>`, `total=60`, `delivered+cуммаremainder=60`;
- `fallback-8x400` (fallback-окно 1000): primary-payload полный (8 строк),
  fallback-payload recomposed → 1 строка + 7 в remainder.

Durable-запись: в прогонах капитан `record_temporal_run(max_evidence=len(rows))`
— строк в БД ровно столько, сколько в payload (1/12/2/8), `max_rows` не
превышает доставленное.

## 3. Production-случай Facebook (SFC-8-01)

Источник: боевая БД `192.255.209.205:/var/www/admin_bot/local_database.db`,
прогон `tfr-d4f381867a884cbd` (13.11.2026 12:35:13 UTC = 14.11 00:35 +12,
chat `-1002661910336`), deployed `d20a7f73` (release 2.58.199). Журнал
systemd фактчековых событий не содержит (в deployed-релизе нет
`evidence_diagnostics`) — trace есть только в БД; это зафиксировано как факт,
а не догадка.

Что установлено по пунктам §8.1:

| Пункт | Факт |
|---|---|
| фактически выбранный предмет | `claim_text` = исходное сообщение «Не вышла бы она… обрезание женщин настолько древняя традиция… распространена в странах, на которые не имело влияние сша». Вопрос пользователя («реально есть страны… на которые не влияли Франция/Великобритания/Германия/США?») в предмет НЕ попал |
| построенные запросы | строились из этого `claim_text` (deployed `_claim_units(items, claim)` отбрасывает часть, не входящую дословно в claim): детерминированная проба `units_from_material_claim` — вопрос пользователя отсутствует; `units_request_only` — вопрос формирует отдельный unit, если предмет = запрос |
| участники-провайдеры | каскад `tavily→exa→ddg`; какие именно ответили в том прогоне — не сохранено (нет события), поэтому не утверждается |
| полученные результаты | evidence-таблица содержит РОВНО 1 строку: facebook-видео, `source_kind=secondary`, `published_at=NULL`, support 209 симв. = поисковый сниппет («…ИНОСТРАННЫМ СРЕДСТВОМ… Read more») |
| открытые страницы | открытий не зафиксировано: строка осталась сниппетом; durable-схема того релиза не хранила `opened` |
| причины отказов/отбрасывания | точные причины по каждому кандидату не сохранены (нет счётчиков `off_topic/stale/irrelevant` в том релизе); установлено ограничение: evidence-слой того релиза резал support до 1200 и доставлял не более 20 строк |
| точка возникновения deadline | `verdict_uncertainty`: «поиск по p1 прерван по лимиту времени»; deployed-бюджет по умолчанию 10 c / максимум 45 c (`_BUDGET_SECONDS_DEFAULT/_MAX`), т.е. поиск был остановлен ДО рассмотрения источников |
| пропущенные операции | `stage_trace` показывает `temporal_search: success` — пропуск по deadline не отражался в trace (наблюдаемость отсутствовала) |
| реально переданное аналитику evidence | одна строка ev-1 (209 симв. сниппета), без даты, без provenance; вердикт `insufficient_evidence` с `evidence-limited` |

Подтверждённые причины и где исправлены:

| Категория §8.1 | Подтверждённая причина | Исправление |
|---|---|---|
| потеря пользовательского запроса | subject не разрешался: план и envelope строились от материала; deployed не имеет `resolve_check_subject` (`caps.has_subject_resolver=false`) | S13 (зависимость `b1f7609e`): `resolve_check_subject` + единый предмет; проба кандидата: subject = вопрос пользователя, `origin=request`, `request_text` сохранён целиком |
| искусственные бюджеты | 10/45 c, 12 запросов, 3 уточнения, 8000 симв. текста, 20 строк, support 1200, 12 ссылок | S14 (120/600 c, 64 запроса, 24 уточнения, 100 000 симв., 20 результатов, 32 части) + S15 (снят потолок 20 строк и обрезка support на доставке; 12 ссылок снято в S14) |
| ошибочная остановка поиска | жёсткий лимит времени останавливал поиск независимо от объёма; остановка не отражалась в trace | S14: stop по содержательным состояниям + `stop_reason`; S15: `stop_reason`/`fetch_skipped_budget` в диагностике и оговорка analyst+validator |
| обрезка evidence | support[:1200] на доставке и cap 400 у атрибуционной цитаты | S15: полный support ref в delivery, цитата без cap (тесты `wide-12x2000`, `attribution_quote_not_truncated_at_400`) |
| невозможность получить продолжение | остаток не перечислялся, модель не знала о непоставленных материалах | S15: `<evidence_delivery>` с `remainder_ids/remainder_urls`, `delivered+remainder=total` (тесты overflow/tiny-share) |
| потеря результатов инструментов | найденное вне 20 строк/12 ссылок исчезало молча; БД писалась с потолком 20 | S15: ёмкость вместо потолков, durable == доставленному (оркестратор `max_evidence=len(rows)`) |
| несогласованность вердикта с предметом | вердикт и ответ строились от исходного материала, вопрос не проверялся | S13 (предмет) + S15 (оговорка «поиск остановлен бюджетом» запрещает вывод «доказательств нет» и на стадии validator) |

Дополнительно: S15 НЕ вводит доменных blacklist/allowlist и не меняет trust
scoring/EvidenceMap (SFC-8-03/10-03): в коде фактчека нет строки «facebook»
(тест), соцсеть проходит как обычный источник с provenance; новых trust-полей
и второго хранилища evidence не появилось.

## 4. Ёмкость фактического маршрута (SFC-7-03/7-04)

- Неизвестная модель: окно 1 000 000 токенов, источник `unknown_fallback`
  (`audit-candidate.caps.unknown_model_window`), evidence-бюджет 800 000 симв.,
  output-резерв 100 000 токенов — считается ОТДЕЛЬНО и не входит в бюджет
  evidence.
- Маршрут читается с фактического клиента: `_chat_model/_base_url` и
  `_fallback_model/_fallback_base_url`; проба фиксирует обращения резолвера
  ровно с этой парой (`capacity_calls`), не с «главной моделью» настроек.
- Подтверждённое окно приоритетнее: проба с окнами 1M/1000 даёт разные порции
  для primary/fallback; recompose выполняется только при фактическом переходе
  клиента на fallback (adapter), primary-payload не занижается заранее.
- Большое окно ≠ «отправить всё»: `search_text` в payload не попадает
  (`search_text_leaked=false`), доставляются только структурные refs; при
  реальном превышении — существующая порционная обработка + явный remainder.
- Когда всё помещается — секции не режутся (`wide-12x2000`: 26 689 симв.
  evidence, мета-блок не добавляется).

## 5. Приёмка по строкам карты

| req_id | Чем подтверждено |
|---|---|
| SFC-7-01 | `test_evidence_over_8000_reaches_analyst_and_validator` (24 000 симв. → 12 строк по 2000 в analyst и validator, без обрезки), `test_no_hidden_row_cap_20` (60 строк), `raw/audit-*` (`wide-12x2000`: 14902→26689) |
| SFC-7-02 | `test_real_capacity_budget_limits_portion_and_keeps_remainder`, `test_tiny_share_route_still_marks_remainder` (остаток ID/URL, `delivered+remainder=total`, новая БД/пайплайн не созданы) |
| SFC-7-03 | `test_capacity_resolver_called_with_actual_route` (резолвер с фактической парой модель+endpoint; `16384` присвоений 0), `test_capacity_unknown_degrades_honestly` (честная деградация), `audit-candidate.caps` (1M/unknown) |
| SFC-7-04 | `test_fallback_route_recomposes_payload_to_its_capacity` (primary 1M, fallback 1000 → recompose + remainder) |
| SFC-7-05 | `test_evidence_over_8000…` (нет искусственной секционной обрезки при вмещении), `test_provenance_and_social_source_not_blocked` (осмысленный отбор сохранён, сниппет помечен), overflow-кейсы с provenance/coverage |
| SFC-7-06 | §2 аудит восьми звеньев на трёх коммитах + `test_diagnostics_expose_stop_reason_and_delivery`; postdeploy-наблюдение см. §8 |
| SFC-8-01 | §3: установлены предмет, запросы, evidence-строка, точка deadline, пропуски, переданное аналитику; причины исправлены в S13/S14/S15 (таблица) |
| SFC-8-02 | `test_budget_stopped_search_forbids_absence_conclusion` (analyst И validator), `test_no_budget_note_on_complete_search`, `opened=yes/no` в обоих payload |
| SFC-8-03 | `test_provenance_and_social_source_not_blocked` (facebook не заблокирован, источникам не добавлено доменных правил) |
| SFC-10-03 | новых trust scoring/шкал/второго EvidenceMap нет: диф среза не добавляет trust-полей; evidence проходит существующим EvidenceMap (`_assemble`), trust-контракт не менялся |

## 6. Тесты: команды, счётчики, RED, мутации

Окружение: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`,
`pytest -q -p no:cacheprovider`.

| Прогон | Результат | Файл |
|---|---|---|
| `pytest tests/test_factcheck_evidence_delivery.py` (кандидат) | **12 passed** | `raw/pytest-new-green.txt` |
| затронутые швы, 27 файлов (кандидат) | **839 passed, 6 failed** — все 6 пре-существующие (см. §9), идентичны базе и master | `raw/pytest-affected-seams.txt` |
| те же швы на базе `80c83d24` | 737 passed, 7 failed (тот же набор + сетевой флейк) | `raw/pytest-affected-seams-base-80c83d24.txt` |
| **RED на базе**: финальный тест-файл в дереве `80c83d24` | **11 failed, 1 passed** (проходит только вакуумный негатив «нет оговорки без остановки») | `raw/red-base-80c83d24.txt` |
| master (repo root) для пре-существующих | 6 failed (те же) | `raw/pytest-pre-existing-master.txt` |

Швы (кандидат): `test_factcheck_evidence_delivery`, `test_factcheck_service`,
`test_factcheck_resources`, `test_factcheck_subject_contract`,
`test_factcheck_fc_r1_fix`, `test_factcheck_p0_fc`, `test_mca20_rework1_f1_f2`,
`test_mca20_temporal_round1044`, `test_capacity_stage_d_smart`,
`test_capacity_resolver_asap31`, `test_capacity_nanogpt_asap32`,
`test_smart_c1_source_reader_limits`, `test_evol_source_reader`,
`test_evol_evidence_window`, `test_smart_exec_evidence`, `test_llm_client`,
`test_summary_capacity_asap41`, `test_summary_coverage_asap31`,
`test_er08_limits_context`, `test_bgs05_budgets`, `test_auto_budget_asap31`,
`test_direct_context_capacity_asap3`, `test_direct_fallback_recompose_asap32`,
`test_mca23_phase2`, `test_mca23_response_plan`, `test_ur_d_writer`,
`test_ur_f_inspector_step1`.

Мутации (`raw/s15_mutation_probe.py`, сводка `raw/mutations-s15.json`; каждая
правка — временная, файл восстановлен):

| Мутация | Вернули | Красные тесты |
|---|---|---|
| `row-cap-20` | потолок 20 строк | `test_no_hidden_row_cap_20`, `test_capacity_unknown_degrades_honestly` |
| `support-cut-1200` | `support[:1200]` | `test_evidence_over_8000_reaches_analyst_and_validator` |
| `fallback-ignores-route` | fallback без recompose | `test_fallback_route_recomposes_payload_to_its_capacity` |
| `silent-budget-no-note` | тихая остановка без оговорки | `test_budget_stopped_search_forbids_absence_conclusion` |
| `capacity-16384` | окно 16384 вместо резолвера | 6 тестов (evidence-over-8000, row-cap, route-call, remainder, fallback, tiny-share) |

Адверсариальные кейсы в наборе: маршрут 250 токенов (200 симв. бюджета) —
остаток не теряется; 60 строк при ёмкости 3000 — доставка остановлена,
остаток перечислен; fallback уже primary; resolver бросает исключение —
деградация к прежней порции с `capacity_unknown=true`, а не «бюджет 0».

## 7. Пробелы/переводы строк

- `git diff --check 80c83d24 HEAD -- services tests` — **пусто** (проверено на
  `c5e87342`).
- 5 файлов, унаследованных от S3/S4, переведены CRLF→LF без изменения
  содержимого: `services/factcheck_service.py`, `services/llm_client.py`,
  `services/source_reader.py`, `tests/test_evol_source_reader.py`,
  `tests/test_smart_c1_source_reader_limits.py`.
- `git diff -w 80c83d24 HEAD -- services tests` до и после нормализации
  различается ТОЛЬКО строками `index <blob>` (доказательство:
  `raw/whitespace-normalization-diff-w.txt`); поведенческий патч тот же —
  `38 files changed, 4867 insertions(+), 431 deletions(-)` в `-w`-стате.

## 8. Остаточное (не выдаётся за проверенное)

1. **SFC-7-06, `live_required: postdeploy`**: аудит восьми звеньев выполнен на
   коде/пробах, но фактический боевой прогон после выката не выполнялся.
   Postdeploy-наблюдение: один реальный фактчек на кандидате — в
   `mca_event=factcheck_diagnostics` должны появиться `evidence_delivery.route`,
   `delivered_rows`, `stop_reason`; в `<evidence_delivery>` — согласованность
   `delivered+remainder=total`; в БД число строк = доставленному.
2. Политика извлечения `excerpt_chars=600` и `primary_fetches=2` — решение S14
   (SFC-5), в S15 не менялась; при `budgets_enabled=OFF` обрезки нет. Если
   владелец захочет длиннее выдержки при ON — это отдельная настройка
   `limits.factcheck_excerpt_chars`, не потолок доставки.
3. Медиа-слой (OCR/транскрипт) свои пределы не менял и в S15 не входит; в
   фактчековом пути дополнительного символьного cap на текст тезиса не найдено.
4. Финальный ответ по предмету (жанр/структура) — S16-FC-FINALIZE, не этот
   срез; S15 обеспечивает предмет и полноту evidence.

## 9. Пре-существующие дефекты (BACKLOG_ONLY, не блокируют срез)

1. `tests/test_mca20_rework1_f1_f2.py::TestValidatorStage::
   test_evidence_injection_stays_data_not_instructions` — падает на `master`
   и на базе: блок инъекции без URL отбрасывается как evidence (FC-EVIDQ §3.4),
   поэтому `&lt;/evidence&gt;` в payload не появляется; проверка экранирования
   перестала достигаться. Продукт инъекцию не пропускает; тест устарел.
2. `tests/test_direct_fallback_recompose_asap32.py` — 5 тестов падают на
   `master` и базе: стабы `_fallback_with_retries` не принимают новый kwarg
   `sent=` (`TypeError … unexpected keyword argument 'sent'`). Тестовый дефект.
3. `tests/test_factcheck_fc_r1_fix.py::TestRelevanceCascade::
   test_all_irrelevant_is_honest_failure` — сетевой флейк: каскад после
   tavily/exa уходит в реальный DDG (не замокан httpx), результат зависит от
   сети; в прогонах 2 pass / 1 fail.

## 10. Housekeeping

- Probe-файлы и логи durable: `evidence/fc-evidence/raw/` (коммит `c5e87342`).
- Временные worktree-прогоны (`80c83d24`, `d20a7f73`) зарегистрированы как
  unit `S15-FC-EVIDENCE`; после снятия аудита закрываются `unit-close`.
  Основной worktree среза сохраняется до конца ревью.
