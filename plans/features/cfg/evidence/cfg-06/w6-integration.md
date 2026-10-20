# CFG-06 W6 — интеграция v2: единый retrieval-контур, трассы/метрики, cache-hit рендер

Дата: 20.10.2026. Сводит W4 (planner) и W5 (renderer/доставка) в единый контур
v2. База: deployed `29cc49ba` + незакоммиченные W0–W5 правки лейна.
КОММИТ НЕ СОЗДАВАЛСЯ.

## 1. Сведено

| Задача брифа | Реализация |
|---|---|
| 1. Join-патч W4-теста (§6) | `test_factcheck_planner_cfg06.py::test_legacy_branch_evidence_filled_args_parity` — pre-W5 plain-ассерт заменён на W5-контракт: `href` ровно 1 раз, в `visible_text` полного URL нет (label = домен). Конфликт воспроизведён RED-демо (старый ассерт против renderer → FAILED; лог w6-red-green.txt) |
| 2. Единый retrieval-контур (06C.8) | `fsp.run_retrieval` (`RetrievalOutcome`): план выполняется **ДО** вердикта; выдача строкой (`search_text`, бюджет 8000 симв.) идёт в legacy-ветку через аддитивный kwarg `service.check_claim(..., search_results=)` — внутренний поиск агрегатора пропускается (**один поиск на прогон**). Бюджеты: ≤3 запроса (план), общий дедлайн контура (default 10 с), потолок evidence 12; исчерпание/ошибки → честная деградация: partial/None, а None → fallback на внутренний поиск ветки (никогда пустой verdict без данных) |
| 3. Трассы/метрики (06G.7) | `_log_retrieval_metrics`: logger-дайджест прогона (attempted/used/refs/fetch_errors/budget_exhausted/fp1) + mca-событие `factcheck_run`/`factcheck.retrieval` (fail-open); gate-решения логируются на маршрутах (W2/W3); кеш legacy-ветки v2 версионирован `_v2_cache_input` = `fcv2␀PIPELINE_VERSION␀fp1␀claim` — записи прод-пути и v2 не пересекаются в обе стороны (06H.6); envelope-кеш — свой `tf1`-версионированный составной ключ (planner туда не пишет — документировано) |
| 4. Envelope cache-hit → renderer | cache-hit больше не отвечает plain `_reply`: возвращает `CheckedVerdict(cache_hit=True)` в общий поток → `render_factcheck` (детерминированное преобразование того же кешированного текста — консистентность кеша) → `deliver_factcheck` (HTML, одна доставка). Тест `test_cache_hit_delivered_via_renderer`: ровно 1 доставка с parse_mode="HTML", заголовок по enum («Не подтверждается»), тело — кешированный текст |
| 5. Финальный общий прогон | **333 passed / 0 failed** (состав ниже); известные вне диффа подтверждены отдельно: 2 FAIL `test_outgoing_guard_round1022` (aiogram-дрейф `InputRichMessageMedia`), 2 FAIL `test_asap7_direct_settings` (v35) |
| 6. Сквозной egress-тест | `test_request_to_delivery_no_service_fields`: FactcheckRequest → delivery на моках — служебные токены (as_of/gate_version/reason_code/fsg1/fcv2/fp1/temporal_status) отсутствуют в visible-тексте; ссылки только из EvidenceMap (href, полный URL не в visible); каждый чанк ≤4096 с целыми `<b>`-парами и парсимым visible |

## 2. Ветвь envelope и единый поиск: граница W6

Legacy-ветка v2: один поиск на прогон (план → search_results). Envelope-ветка:
собственный `temporal_search` остаётся поиском этого прогона (каскад дат и
period-запросы — часть temporal-семантики D8); planner в этой ветке не
выполняется (её EvidenceMap уже несёт ev-N прогона). Полная унификация
temporal-запросов под planner — за пределами W6-задач, отмечено как
направление W7/пост-W6 (не блокер композита: правила evidence/egress/кеша
у веток уже общие).

## 3. Детерминизм (найдено и починено в W6)

`_claim_terms` планировщика итерировал set-токены → порядок запросов плавал
между процессами (queries менялись от запуска к запуску; raw-slice-guard
сравнивал со случайным порядком). Заменено на детерминированный finditer по
исходному тексту (lowercase, без стоп-слов, ≤8, исходный порядок); хрупкий
guard заменён на «запрос ≠ весь клейм дословно». Подтверждено двумя
процессами: идентичные JSON-тексты запросов. Инварианты 06A.4 сохранены
тестом (`test_semantic_queries_not_raw_slice` — обновлён на детерминированную
форму).

## 4. Прогон (задача 5)

| Набор | Результат |
|---|---|
| `test_factcheck_w6_cfg06.py` (новый, 6) | 6 passed |
| W4 planner (после join-патча) | 15 passed |
| Полный фокусированный CFG-06 + швы | **333 passed / 0 failed** |
| Состав | orchestrator(16)+planner(15)+gate(18)+context(11)+renderer(36)+W6(6)+route-coverage(18 CONTRACT)+handlers+service+two_call+prompts+grounding×2+tools+B07+settings+smart_cache |
| Известные вне диффа | 2 FAIL outgoing_guard (aiogram), 2 FAIL asap7_direct_settings (v35) — подтверждены ровно этими числами |

## 5. Осталось W7 (приёмка/релиз)

1. Live-постдеплой техсмоук (прод-байты/логи/healthz, БЕЗ чатов) + спор 200+
   синтетически на deployed-контуре (06J.6/06H.1-live).
2. Композит CFG-06.B целиком (все 5 условий на deployed-контуре).
3. Владельцу (опционально, owner_live_checks): 06E.4/06G.8 глазами; живой
   фактчек на коротком споре.
4. Направление пост-W6 (не блокер): унификация temporal-запросов под
   planner-семантику.
