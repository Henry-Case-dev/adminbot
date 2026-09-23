# S8 `summary-analytics-adapter-round1026` — evidence (Step 4 @Builder, блоки B–G)

- **Фича:** S8 (Эпик 2, Раунд 10.26) — adapter «Backend metrics → Normalized execution graph → UI» (§23–§25/§29/§30/§111/§112). **ADR-1026-10 D1–D10**, `spec.md` REQ-S8-01…-14 / SC-01…SC-18.
- **Дата:** 24.09.2026. **Автор:** @Builder.
- **Baseline:** HEAD **`2ffeb6a`** == `origin/master`; `APP_VERSION` 2.58.26; pytest `.venv` 8890/0; JS 45/45; каталог 469/426/444/100/98/21; Δ DDL=0.
- **Итог:** реализация B–G + тесты; **`APP_VERSION` 2.58.27**. Коммит **не делался** (по указанию). `plans/current_task.md` / machine-блок / `plans/backlog.md` / `plans/metrics.md` / `tasks.md` — **не изменялись**.
- **Рабочее дерево:** modified 33 файла + untracked: `services/execution_graph_source.py`, `tests/test_summary_execution_graph_round1026.py`, `tests/js/round1026_s8_execution_graph_test.js`, `plans/features/summary-analytics-adapter-round1026/` (этот файл). `plans/MEMORY.md`/`plans/workflow_state.md` были modified до старта (не трогались).

## 1. Что реализовано по блокам

### Блок B — маппинг `step→kind`, только реальные этапы (T-3413/T-3414)
- `web/static/execution_graph.js:55` — `STEP_KIND`: `filter`→`algorithm`, `l1_clusterizer`→`llm`, `l2_writer`→`llm`, `formatting`/`format`→`format`, `publication`→`publish` (**зарезервирован, GATED**); legacy (`single`/`stage1`/`stage2`/`image`) — как в F6. `STEP_LABEL` — реальные ru-подписи («Алгоритмический фильтр», «L1 Кластеризатор», «L2 Писатель», «Форматирование»).
- Правило «нет данных/шага → нет узла»: `normalizeExecutionNode` (`:271`) отбрасывает `kind='publish'` и не создаёт узел из пустого входа; серверный `llm_node` (`services/execution_graph_source.py:358`) возвращает `None` для пустого `step` и `publication`.
- Правило «нет `parent_id` → нет ветвления»: связи — только подтверждённая линейная последовательность одного `run_id` (канонический порядок пайплайна), `hasBranch=false`.

### Блок C — источник узлов / adapter (T-3415/T-3416/T-3417)
- **NEW `services/execution_graph_source.py`** — чистый backend-слой нормализации (§23/§25, вне SVG/Vue):
  - `RunSnapshotStore` (`:97`) — in-memory реестр снапшотов (TTL 900s / ≤20, без persistence → **Δ DDL=0**);
  - `record_run` (`:169`) / `record_run_from_context` (`:190`) — фиксация снапшота из S7 `RunContext` + S1 `_filter_metrics` (только R17-safe поля; неизвестные ключи игнорируются);
  - `algorithm_node` (`:308`) / `format_node` (`:340`) / `llm_node` (`:358`) / `build_graph` (`:412`) / `metrics_block` (`:499`);
  - маппинг реальных этапов + `STAGE_ORDER` (`:64`).
- **`web/api/analytics.py`** — аддитивный read-only `GET /api/analytics/execution/latest?run_id=` (`:279`, `_execution_response` `:183`, `_context_limit_info` `:165`); reuse `_SELECT_STEPS_SQL`/`llm_usage_events` по `correlation_id` (единый ключ, D5), fail-open.
- **`services/summary_generator.py`** — аддитивная фиксация снапшота в `_run` finally (best-effort, fail-open), поля `drop_percent`/`filter_status`/`filter_duration_ms` (S1) и `format_channel`/`format_status`/`format_duration_ms` (в `_deliver_l2_plain`/`_deliver_l2_rich`); `_elapsed_since` helper.
- **`services/summary_run_log.py`** — аддитивные поля `RunContext` (в лог §108 НЕ выводятся — R17-поверхность не растёт).
- Агрегат ≠ трассировка: `fromExecution` (прогон) и `fromSummary` (период) — несмешиваемые; агрегатные узлы `parentIds=[]`, `status='unknown'`.

### Блок D — UI/узлы/агрегаты/mobile (T-3418/T-3419/T-3420)
- `web/static/execution_graph.js:338` — `fromExecution(payload)` (проекция backend-графа в существующий контракт `ExecutionNode`; `fromTrace`/`fromSummary`/`filter`/`detail` не тронуты; publish-узлы отбрасываются — GATED).
- `web/app.js:2556` — computed `execGraph` (через `EG.fromExecution`), `:2564` `execMetricsRows`, `:2618` `execPublicationLabel`; `tokenFlowTree` в режиме «последний вызов» приоритезирует реальный граф прогона, иначе — F6-трассировка (обратная совместимость); `loadTokenAnalytics` (`:4313`) догружает `/api/analytics/execution/latest` fail-open.
- `web/index.html:2309` — §112-блок (внутри **единственной** карты `.token-flow`; literal `algorithm` в шаблоне отсутствует).
- `web/static/app.css:2073` — additive mobile §29 (вертикальная последовательность, перенос чисел, не сжимается до 320px).
- `GraphViewer`/`NodeCard`/`DetailPanel` **не переписаны** (аддитивные узлы/подписи через существующий рендер).

### Блок E — §112-метрики (T-3421/T-3422/T-3423)
- Перечень §112 в `metrics_block` (`:499`): исходные/после фильтра/восстановленные/отсев/темы/токены L1·L2/стоимость L1·L2/общая/время/`cover_status`/`publication_status`.
- Честность: неизвестная цена → `None` («Нет данных»), **никогда `$0`**; `publication_status="gated"`; `-1`-sentinel → «Без лимита» (`_context_limit_info`).
- `L-F6S-1` закрыт: `web/api/analytics.py:52,60,67,76` — аддитивный `price_known` (`BOOL_AND`) в `/analytics/usage/summary` (totals/by_module/series); `fromSummary` больше не ставит жёстко `priceKnown:true`.
- S9 не дублируется: сбор токенов/стоимости — тот же `llm_usage_events` по `run_id`; второй сборщик не создан; `services/summary_test_run.py` — вне diff.

### Блок F — тесты/R17/регресс (T-3424/T-3425/T-3426)
- **NEW `tests/test_summary_execution_graph_round1026.py`** — 31 тест: маппинг, «нет данных → нет узла», algorithm без LLM-токенов, publish GATED, честная стоимость, §112, реестр (bounded/TTL/duck-typed), R17, инварианты (Δ DDL=0, Δ каталога=0, 2-вызовность, publish/§110/S9/`routes.py`/`param_catalog`/`db` вне diff, `-1`→«Без лимита»).
- **NEW `tests/js/round1026_s8_execution_graph_test.js`** (`S8-EXECGRAPH-OK`) + регистрация в `tests/test_webapp_js_unit.py`.
- Добавлены endpoint-тесты S8 в `tests/test_webapp_analytics_api.py` (401/403/200, `publication_status=gated`, `price_known`).
- Обновлены version-pin тесты (bump 2.58.27) — 16 pytest-файлов + 4 JS-файла (S7-паттерн); `tests/test_webapp_f6_round1025.py` — маршрутов analytics 4→5 (санкционированный аддитивный эндпоинт, D3); `plans/docs/param-registry-round1025.meta.md` — `APP_VERSION` 2.58.27 (provenance-штамп, S7-прецедент; **каталог не переиздаётся**).

### Блок G — интеграция и границы (T-3427)
- S6/publish — GATED (нет `kind="publish"`-узлов; `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` отсутствуют в исходниках S8); §110-viewer (S7) не переписан; S9 — reuse; F6 `ExecutionGraph` — REUSE.

## 2. Команды и результаты прогонов

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс pytest | `.venv\Scripts\python.exe -m pytest -q` | **8926 passed, 0 failed** (120.6s); baseline 8890 → +36 |
| Новый Python-тест | `pytest tests/test_summary_execution_graph_round1026.py -q` | **31 passed** |
| JS (все файлы) | `node tests/js/*.js` (цикл по 46 файлам) | **OK=46 FAIL=0** (baseline 45) |
| Новый JS-тест | `node tests/js/round1026_s8_execution_graph_test.js` | `S8-EXECGRAPH-OK` |
| 2-вызовность | `pytest tests/test_summary_l1_clusterizer.py tests/test_summary_test_run.py -k two_calls` | **3 passed** (`await_count==2`) |
| API/RBAC S8 | `pytest tests/test_webapp_analytics_api.py tests/test_webapp_f6_round1025.py tests/test_webapp_round1024_nodeflow.py` | **39 passed** |
| `git diff --check` | `git diff --check` | exit **0** (без whitespace-ошибок) |
| Каталог (Δ=0) | `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` |
| Δ DDL=0 | full pytest (DDL-guard тесты) + `execution_graph_source` без DDL | подтверждено |
| publish/§110/S9 вне diff | `git diff --name-only pre-round1026-s8 -- services/telegram_send.py services/summary_xml.py services/image_generation.py web/api/routes.py services/param_catalog.py db services/summary_test_run.py` | **пусто** |

## 3. R17 / R18
- R17: узлы/метрики/снапшот содержат только числа/коды/id/строки статусов; `record_run` игнорирует неизвестные ключи (промпты/сырые тексты не сохраняются) — покрыто `TestR17`. Новые поля `RunContext` в лог не выводятся.
- R18: теги/бэкапы не удалялись; `pre-round1026-s8` не трогался.

## 4. Незакрытое / открытые вопросы для @Architect
1. **Снапшот в живом пайплайне.** D2 требует фиксацию снапшота в конце прогона → аддитивно затронуты `services/summary_generator.py` (1 вызов best-effort + format-поля) и `services/summary_run_log.py` (поля `RunContext`), хотя `spec.md §19` их явно не перечислял. Изменения аддитивны, fail-open, 0 LLM-вызовов; прошу подтвердить, что это в scope (иначе — отдельное решение).
2. **Связи (`parentIds`) узлов S8.** Связывание filter→L1→L2→format по каноническому порядку пайплайна одного `run_id` трактовано как «подтверждённая линейная последовательность» (D6), т.к. в источниках нет общего `parent_id`/timestamp для non-LLM этапов. Ветвление не достраивается. Прошу подтвердить трактовку (альтернатива — `parentIds=[]` у всех узлов).
3. **`context`-блок §112.** `-1`-sentinel→«Без лимита» вычисляется в endpoint (`_context_limit_info`), а не в чистом модуле (читает `hot_config`/`settings`). Если требуется строгая «чистота» — перенести/параметризовать.
4. **`plans/docs/param-registry-round1025.meta.md`** — обновлён только `APP_VERSION` (S7-прецедент), иначе `test_meta_provenance` краснеет при bump; каталог/TSV не переиздавались (Δ каталога=0 подтверждён `--check`).
5. **`tasks.md` не редактировался** (по указанию) → чекбоксы T-3413…T-3427 не проставлены; статус фичи — за @Orchestrator.
6. **Не выполнялось:** коммит, deploy, live-приёмка (PENDING OWNER VERIFICATION, SC-18), ручной визуальный прогон UI в браузере.
7. **Отклонений от спеки нет**; фиктивных узлов/связей/`$0` нет; вторая визуализация не создавалась.
