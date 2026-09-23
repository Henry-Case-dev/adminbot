# ADR-1026-10 — S8 «Adapter аналитики Саммари»: ядро без S6 (publish GATED), backend-источник узлов через тот же `ExecutionNode`-контракт, честные §112-метрики, Δ DDL=0

- **Статус:** **Accepted** — Proposed (Step 2 @Architect, T-3411, 24.09.2026) → **Accepted фактом мержа `plans/ARCHITECTURE.md` §79** (T-3431, Шаг 7 @Architect, 24.09.2026) после **единого Reviewer gate** (Approved C0/H0) и deploy **VERIFIED 2.58.27** (T-3433 @DevOps).
- **Фича:** S8 `summary-analytics-adapter-round1026` (Эпик 2, шаги §23–§25/§29/§30/§111/§112).
- **Тип:** web + api adapter (backend-источник узлов/метрик + клиентский `ExecutionGraph`-нормализатор, zero-build).
- **Связано:** **F6 `ADR-1025-19`** (ExecutionGraph-адаптер, `ExecutionNode`, kinds `algorithm`/`format`/`publish` — **REUSE**); **S7 `ADR-1026-9`** (`run_id`=`correlation_id`, события §108/§109 — источник снапшота прогона); **governed-by `ADR-1025-24 D4`** (публикационный гейт S6/S10); **`ADR-1023-7`** (`llm_usage_events`/`llm_pricing`/`/analytics/*` — REUSE); **`ADR-1022-4`/`ADR-1023-6`** (2-вызовность); **`ADR-1026-8`** (S9 dry-run — не дублировать); §28 (честная стоимость) — REUSE.
- **Baseline (заявлено Step 0 @Memory; подтверждает @DevOps T-3410):** HEAD `2ffeb6a` == `origin/master`; `APP_VERSION` 2.58.26; pytest `.venv` 8890/0; JS 45/45; каталог 469/426/444/100/98/21; Δ DDL=0 (SQLite v12); прод активен.
- **Номер ADR:** `ADR-1026-10` — следующий свободный (S7 = ADR-1026-9).

---

## Контекст

§111 требует «Использовать ExecutionGraph, реализованный в первом эпике» и передавать узлы нового пайплайна — Algorithmic Filter, L1 Clusterizer, L2 Writer, Formatting, Publication — «только реальные этапы», с `kind` = `algorithm`/`llm`/`format`/`publish`, «не создавать вторую систему визуализации», «не переписывать GraphViewer», «расширить backend adapter». §23 даёт канонический `ExecutionNode` и прямо разрешает «адаптировать к существующему стеку», «не изменять серверную схему без необходимости», «нормализовать через отдельный adapter». §25 задаёт слой «Backend metrics → Normalized execution graph → UI» и запрещает выдумывать связи/выдавать агрегат за трассировку. §24 делит состав полей по `kind` и запрещает выдуманные LLM-токены для `algorithm`. §112 перечисляет метрики и запрещает выдуманный `$0`. §29/§30 — mobile и совместимость.

**Проверенные факты кода (Step 0 @Memory + Step 2):**

1. Фактический adapter — **клиентский** `web/static/execution_graph.js` (`fromTrace`/`fromSummary`/`filter`/`detail`; F6 §65, ADR-1025-19 D1). `web/api/analytics.py` и схема БД в F6 **не расширялись** (R16, Δ DDL=0). ADR-1025-19 D1 прямо допускает перенос/расширение adapter на сервере в Эпике 2 (S8).
2. `KIND_ENUM` уже содержит `llm|algorithm|tool|format|publish|other`; но реальные шаги Эпика 2 (`l1_clusterizer`, `l2_writer`) **не замаплены** → попадают в `other`. `STEP_KIND` содержит плейсхолдеры `algorithm`/`format`/`publish`.
3. Данные плоские: `llm_usage_events` (`correlation_id, module, step, tool_name, source, chat_id, model, input_tokens, output_tokens, tokens_estimated, cost_usd, price_known`) — **нет** `parent_id`, `status`, `duration`, `finished_at`. В таблице есть только LLM-этапы; `filter`/`format`/`publish` **не записываются**.
4. S7 (`ADR-1026-9`) создал сквозной `run_id`=`correlation_id` и структурированный контекст прогона `RunContext` (`services/summary_run_log.py`), а `_apply_filter` собирает `_filter_metrics` (`source_count`/`saved_count`/`restored_count`/`drop_percent`/`duration_ms`/`status`). Всё это — **in-memory** на время прогона; в конце прогона `finish_run(ctx)` только логирует.
5. S9 (`ADR-1026-8`) уже читает токены/стоимость из `llm_usage_events` по `correlation_id` (`summary_test_run._collect_usage`, `_STEP_MAP={'l1_clusterizer':'l1','l2_writer':'l2'}`) и отдаёт §112-метрики в dry-run; имеет собственный in-memory store (TTL/≤20) — **прецедент для снапшота без DDL**.
6. Процесс **один** (`bot.py` + `web/app.py`: один event loop — R2/R3), поэтому in-memory снапшот, созданный пайплайном в боте, виден read-only эндпоинту FastAPI.
7. F6 follow-up **`L-F6S-1`** (Low, OPEN): `fromSummary` жёстко `priceKnown:true`, а `/analytics/usage/summary` не отдаёт `price_known` → в агрегате возможен `$0` при неизвестной цене.

**Открытые вопросы Step 1 (a)–(i):** нарезка без S6; маппинг `step→kind` и источник узлов; «backend adapter» vs клиентский; состав §112 для `algorithm`/`format`; корреляция; агрегаты/режимы; санкции (DDL/каталог/флаг); граница publish; deploy/bump.

---

## Решения

### D1. Старт ядром без S6; publish-срез GATED — по прецеденту S7 (ответ (a))

**Решение.** S8 стартует **ядром**: adapter-слой + узлы `algorithm` (Filter) / `llm` (L1, L2) / `format` (Formatting) + метрики §112 + mobile §29. Публикационный срез — **GATED**: узлы `kind="publish"`, события `PUBLISH_RICH_*`/`PUBLISH_TEXT_*`, путь §100–§106 **не реализуются и не вызываются**. `cover_status` (§112) — **не GATED** (генерация обложки существует вне S6). GATED-граница проверяется: (1) пустым diff публикационных модулей/`generate_image`; (2) тестом «нет publish-узла»; (3) тестом «нет `PUBLISH_*`» в исходниках S8.

**Альтернативы.**
- **(a) Ждать S6.** Отклонено: гейт D4 зависит от владельца (live-приёмка Эпика 1) → неограниченная задержка; ядро S8 не требует публикационного пути. Прецедент S7 (ядро верифицировано без S6, `PUBLISH_*` GATED) уже доказал безопасность.
- **(b) Минимальная нарезка «только LLM-узлы».** Отклонено: не закрывает §111 (Filter/Formatting) и §24/§112 для `algorithm`/`format`; ядро можно верифицировать полностью без S6.

### D2. Источник узлов и маппинг `step→kind` (ответ (b))

**Решение.** Маппинг реальных шагов → `kind` (клиентский `STEP_KIND`/`STEP_LABEL`): `filter`→`algorithm`; `l1_clusterizer`→`llm`; `l2_writer`→`llm`; `formatting`/`format`→`format`; legacy `single`/`stage1`/`stage2`/`image`→`llm` (уже F6); `publication`→`publish` **зарезервирован, GATED**. Ни один реальный шаг не попадает в `other`. Источник узлов — **два реальных, один ключ** `run_id`: (1) `llm_usage_events` (PG, `module='summary'`, `correlation_id`) → `llm`-узлы (REUSE SQL-образца S9; второй сборщик не создаётся); (2) **структурированный снапшот прогона** (S7-данные `RunContext` + `_filter_metrics`, фиксируемые in-memory в конце прогона) → `algorithm`/`format`-узлы и §112.

**Альтернативы.**
- **(a) Писать не-LLM этапы в `llm_usage_events`.** Отклонено: искажает `calls`/`by_module`, смешивает LLM-стоимость с ресурсами сервера (§28).
- **(b) Парсить строки log ring.** Отклонено: хрупко, смешивает диагностический (логи) и data-слои; структурированный снапшот честнее и тестируемее.
- **(c) Синтезировать узлы из агрегатов.** Отклонено §25/§24 (выдуманные узлы).

### D3. Границы «backend adapter» vs клиентский adapter (ответ (c))

**Решение.** Слой «Backend metrics → Normalized execution graph → UI» делится на: (1) **backend-источник** — аддитивный read-only эндпоинт `GET /api/analytics/execution/latest?run_id=…` (global-admin, fail-open) в существующем `web/api/analytics.py`; (2) **backend-нормализация** — отдельный чистый модуль `services/execution_graph_source.py` (NEW; без DDL/побочных эффектов); (3) **клиентский нормализатор** — `fromExecution(payload)` + расширенный `STEP_KIND` в `web/static/execution_graph.js`. Преобразование API-ответов **вне** SVG/Vue-компонента (§25). Рендер (`tokenFlowTree`) — view-проекция. `GraphViewer`/`NodeCard`/`DetailPanel` не переписываются; допускаются только аддитивные подписи/стили kind-узлов. **Один** аддитивный эндпоинт — минимальная реализация §111 «Расширить backend adapter» (трактовка R16).

**Альтернативы.**
- **(a) Расширять `/analytics/usage/latest` полем `graph`.** Отклонено: «последний `correlation_id` любого модуля» ≠ «последний прогон Саммари»; отдельный эндпоинт не меняет контракт F6.
- **(b) Вся нормализация на клиенте.** Отклонено: filter/format-узлов нет в `/analytics/*` → недостижимы без серверного источника.
- **(c) Новая визуализация/компонент.** Запрещено §111/§30.

### D4. Состав §112 для `algorithm`/`format` и честная стоимость (ответ (d))

**Решение.** Поля по `kind`: `llm` — `model`/токены/`cost` (если `price_known`)/`tokens_estimated`; `algorithm` — `source_count` (обработано)/`saved_count` (сохранено)/`restored_count`/`drop_percent`/`duration_ms`/`status` и **никогда** LLM-токены/стоимость; `format` — `channel`/`paragraphs`/`status`/`duration_ms`, без токенов. Недоступное → `null` → «Нет данных». Неизвестная стоимость → **«Нет данных»**, **никогда `$0`**; `-1`-sentinel → «Без лимита»; стоимость LLM **не смешивается** с ресурсами сервера. `publication_status="gated"` (честный факт, не выдуманное «опубликовано»). Сбор токенов/стоимости — единый (REUSE), без дублирования S9. **Закрывается `L-F6S-1`:** `/analytics/usage/summary` (+`by_module`/`series`) дополняется аддитивным `price_known` (`BOOL_AND(price_known)`); `fromSummary` перестаёт жёстко ставить `priceKnown:true`.

**Альтернативы.**
- **(a) Оставить `$0`/`priceKnown:true`.** Прямо запрещено §112/§28.
- **(b) Показывать `algorithm` «0 токенов».** Выдуманные LLM-данные — запрещено §24.

### D5. Корреляция — единый `run_id`=`correlation_id` (ответ (e))

**Решение.** LLM-узлы/токены/стоимость — по `correlation_id` в `llm_usage_events` (`module='summary'`); filter/format/§112 — по тому же `run_id` в снапшоте. Второй идентификатор/учёт **не вводится** (S7/S1–S5/S9 — тот же ключ).

**Альтернатива.** Отдельный `graph_id` — отклонено: разрывает корреляцию и создаёт второй учёт.

### D6. Агрегаты и режимы (ответ (f))

**Решение.** «Последний вызов» — конкретная цепочка одного `run_id`; «период» — агрегат (`/analytics/usage/summary`) с раскрытием. Режимы не смешиваются; агрегат не изображается как трассировка (агрегатные узлы `parentIds=[]`, `status='unknown'`). Связи — только подтверждённая линейная последовательность одного `run_id`; **нет `parent_id` → нет ветвления/связи**; при отсутствии предшествующего этапа `parentIds=[]`.

**Альтернативы.** (a) Единый «умный» вид — запрещено §26/§25. (b) Ветвление по эвристике — запрещено §25.

### D7. Санкции: Δ DDL=0, Δ каталога=0, новый флаг не вводится (ответ (g))

**Решение.** **Δ DDL=0 подтверждено** — новых таблиц/колонок/индексов нет; снапшот прогона — in-memory (прецедент S9 `_RunStore`), без persistence. **Δ каталога=0** — `services/param_catalog.py` вне diff, новых ключей/env нет, F8 не переиздаётся. **Новый флаг не вводится** — откат покрыт существующими env-only `ClassVar`: `TOKEN_ANALYTICS_ENABLED` (OFF → пустой граф, fail-open) и `TOKEN_FLOW_NODEFLOW_ENABLED` (OFF → плоские бейджи). Каталоговый ключ-флаг запрещён (Δ каталога≠0). При подтверждённой необходимости санкции Builder возвращает @Architect.

**Альтернативы.** (a) Новый env-only `SUMMARY_EXECUTION_GRAPH_ENABLED` — отклонено как default (дублирует существующие ручки, §ТЗ предостерегает от сложной системы флагов; прецедент ADR-1025-19 D8); допустимо только по требованию @Reviewer. (b) Каталоговый флаг — запрещено.

### D8. Граница S6/publish в diff (ответ (h))

**Решение.** GATED: `kind="publish"`-узлы, `PUBLISH_RICH_*`/`PUBLISH_TEXT_*`, §100–§106. В diff присутствует **только зарезервированный** маппинг `publication→publish` (значение есть, не активируется — источник данных отсутствует), что совместимо с §30 («заранее предусмотреть», «не создавать фиктивные данные»). Проверка: публикационный путь и `generate_image` вне diff; тесты «нет publish-узла»/«нет `PUBLISH_*`».

### D9. Deploy = ДА; bump 2.58.26 → 2.58.27 (ответ (i))

**Решение.** Меняются рантайм-модули, новый эндпоинт и наблюдаемое UI → bump + `README.md` + cache-bust; перед деплоем — §114-тесты; подтвердить, что публикационный путь не изменён. Откат — annotated-тег **`pre-round1026-s8`** (→ `2ffeb6a`) + `git revert`; hot-OFF не требуется (adapter/источник аддитивны).

**Альтернатива.** **NOT_APPLICABLE** отклонено: рантайм/UI меняются → прод/master рассинхронизировались бы.

### D10. Reuse и инварианты

**Решение.** **2-вызовность** сохранена (0 новых LLM-вызовов, read-only); **CSP/zero-build**; **0 новых внешних зависимостей**; **R17/R18**; §110-viewer (S7) и S9-контур — вне diff; второй контур логирования/сбора метрик не создаётся; F6 `ExecutionGraph` — REUSE.

---

## Последствия

**Плюсы.** Ядро S8 поставляется и верифицируется без S6/D4 (прецедент S7); узлы реальных этапов Эпика 2 идут через **тот же** `ExecutionNode`-контракт без рефакторинга рендера; §112-метрики честны (нет `$0`, нет выдуманных LLM-токенов для `algorithm`); закрыт F6 follow-up `L-F6S-1`; Δ DDL=0, Δ каталога=0, 0 новых зависимостей; публикационный путь не затронут.

**Минусы/цена.** Добавляется один аддитивный read-only эндпоинт (трактовка R16 «минимально»); снапшот прогона — in-memory (теряется при рестарте; «latest» без persistence; для явного `run_id` доступны LLM-узлы из PG, non-LLM — «Нет данных»); реальные `l1_clusterizer`/`l2_writer` теперь маппятся в `llm` (в F6 показывались как `other` — исправление, а не регрессия).

**Затронутые контракты.** Расширяется UI/data-контракт карты вызовов (аддитивный эндпоинт + `ExecutionNode`-shape для non-LLM узлов); аддитивно дополняется `/analytics/usage/summary` (`price_known`). Контракты БД, `param_catalog.py`, §100–§106, §110-viewer, S9 — **не меняются**.

**Ограничения (документируются).** `PUBLISH_*`/publish-узлы отсутствуют до снятия гейта D4 (S6); `provider`/`durationMs` для `llm`-узлов — «Нет данных» (нет в `llm_usage_events`); `publication_status` — `gated`; live-приёмка Эпика 1/S1–S5/S7/S9 — PENDING OWNER VERIFICATION (не блокирует верификацию ядра).

---

## AMEND / REUSE-карта

| Ранее | Действие | Что именно |
|---|---|---|
| **ADR-1025-19** (F6 ExecutionGraph/`ExecutionNode`) | **REUSE + расширение** | Контракт `ExecutionNode` сохраняется; добавляется `fromExecution` + backend-источник non-LLM узлов; `GraphViewer`/`NodeCard`/`DetailPanel` не переписываются |
| **ADR-1026-9** (S7 `run_id`/`RunContext`/события §108/§109) | **REUSE** | `run_id`=`correlation_id`; `RunContext`/`_filter_metrics` — источник снапшота прогона; `PUBLISH_*` GATED |
| **ADR-1026-8** (S9 dry-run, §112) | **REUSE (не дублировать)** | Сбор токенов/стоимости — единый (`llm_usage_events`/`llm_pricing`); S9-контур вне diff |
| **ADR-1023-7** (`llm_usage_events`/`llm_pricing`/`/analytics/*`) | **REUSE** | Единственный источник токенов/стоимости; `correlation_id` |
| **ADR-1022-4 / ADR-1023-6** (2-вызовность) | **REUSE** | 0 новых LLM-вызовов; `await_count==2` |
| **ADR-1025-24 D4** (публикационный гейт S6/S10) | **governed-by** | publish-срез GATED |
| **`L-F6S-1`** (F6 follow-up: агрегат `$0`) | **закрывается** | Аддитивный `price_known` в `/analytics/usage/summary`; `fromSummary` без жёсткого `priceKnown:true` |
| **§28/§112** | **REUSE** | Честная стоимость: «Нет данных», «Без лимита», без смешения LLM-стоимости и ресурсов сервера |
| **ADR-1026-10** | **НОВЫЙ** | Step 2 @Architect (T-3411) |

## Карта D1–D10 → реализация (факт после T-3431)

| D | Решение | Реализация (факт) | Верификация (факт) |
|---|---|---|---|
| **D1** | Ядро без S6; publish GATED | publish-путь вне diff; маппинг `publication→publish` **зарезервирован** (`web/static/execution_graph.js:55`); `PUBLISH_*` в исходниках S8 = 0 | SC-12; `TestBoundaries`/«нет publish-узла»/«нет `PUBLISH_*`»; JS к.3 |
| **D2** | Источник узлов + `step→kind` | `STEP_KIND`/`STEP_LABEL` (`execution_graph.js:55`); `llm_usage_events` (`_SELECT_STEPS_SQL`) + `RunSnapshotStore` (`services/execution_graph_source.py:97`) | SC-01/SC-02/SC-06; `TestStepKindMapping`, `TestRunSnapshotStore`, `test_no_data_no_node`; JS к.1 |
| **D3** | Backend adapter vs клиентский | `services/execution_graph_source.py` (**NEW**, 527 стр.) + `web/api/analytics.py:279` (`GET /analytics/execution/latest`) + `fromExecution` (`execution_graph.js:338`) | SC-03/SC-04/SC-07; `test_single_visualization_and_no_rewrite`; JS к.7 |
| **D4** | Состав §112 + честная стоимость | `metrics_block` (`execution_graph_source.py:499`) + `price_known` (`web/api/analytics.py:52,60,67,76`); `publication_status="gated"` | SC-05/SC-08/SC-09; `TestMetricsBlock`, `test_unknown_price_never_zero`, `TestContextLimit`; JS к.4/к.6 |
| **D5** | Корреляция | `run_id`=`correlation_id` (SQL по `correlation_id` + снапшот по `run_id`) | SC-06; `test_admin_200_llm_nodes_from_pg`; JS к.2 |
| **D6** | Режимы/агрегаты/связи | `fromExecution` (прогон) vs `fromSummary` (период) — несмешиваемые; `parentIds` только подтверждённые (`build_graph`, `hasBranch=false`) | SC-10/SC-11; `test_order_and_linear_links`, `test_gap_does_not_glue_distant_stages`; JS к.2/к.3 |
| **D7** | Санкции | Δ DDL=0 (снапшот in-memory); Δ каталога=0 (`param_catalog.py` вне diff); без нового флага | SC-13; `test_no_ddl_in_s8_source`, `test_catalog_delta_zero`, `test_no_new_catalog_flag` |
| **D8** | Граница S6/publish | publish вне diff (`telegram_send.py`/`summary_xml.py`/`image_generation.py`/`routes.py`/`param_catalog.py`/`db/**`/`summary_test_run.py`) | SC-12; `TestBoundaries`; JS к.3 |
| **D9** | Deploy bump | `APP_VERSION` 2.58.27 + `README.md` + cache-bust; откат `pre-round1026-s8`→`2ffeb6a`; deploy **VERIFIED** (`64cdb0e`/`7c5338e`/`f14ae56`, MainPID 540872, health 200) | SC-17; `deployment.md` **VERIFIED** |
| **D10** | Reuse/инварианты | 2-вызовность (`await_count==2`), CSP/zero-build, R17/R18, §110-viewer/S9 вне diff; F6 `ExecutionGraph` — REUSE | SC-14/SC-15/SC-16; `TestInvariants`, `TestR17`, `test_no_llm_calls_in_s8_source` |

## Ссылки

- `plans/features/summary-analytics-adapter-round1026/{spec.md, tasks.md, evidence.md, review.md, deployment.md}`; ТЗ `plans/current_task.md` §23–§25/§29/§30/§111/§112; `plans/ARCHITECTURE.md` §65 (F6), §78 (S7), **§79 (S8, Merge — ADR Accepted)**.
- Архивы: `plans/archive/memory-analytics-reorg-round1025/adr-1025-19-…`, `plans/archive/summary-logging-runid-round1026/adr-1026-9-…`, `plans/archive/epic1-verification-round1025/adr-1025-24-…`.
- Код: `web/static/execution_graph.js`, `web/app.js` (`tokenFlowTree`/`execTrace`/`execPreview`/`execGraphApi`), `web/api/analytics.py`, `services/usage_events.py`, `services/summary_run_log.py` (`RunContext`/`finish_run`), `services/summary_generator.py` (`_run`/`_apply_filter`/`_deliver_l2_*`), `services/summary_test_run.py` (`_collect_usage`/`_metrics`), `services/log_ring.py`.
