# S8 `summary-analytics-adapter-round1026` — review (T-3428/T-3429, Step 5 @Reviewer, **единый gate**)

- **Feature-ID:** `summary-analytics-adapter-round1026` (Эпик 2, §23–§25/§29/§30/§111/§112; T-3410…T-3434)
- **Risk-Level:** **R2** (web + api adapter; аддитивный read-only эндпоинт + in-memory снапшот + аддитивная врезка в рантайм-пайплайн; Δ DDL=0, Δ каталога=0, без изменения авторизации/секретов/миграций — глубина расширена на интеграционные края эндпоинт↔PG↔снапшот↔UI).
- **Status:** **Approved** — Critical/High/блокирующих Medium = 0. Non-blocking: L-R1026S8-1/-2/-3 (Low/Info). Отдельного Scanner-approval **не существует** (Scanner удалён намеренно; его обязанности исполнены в линзе 2 этого gate). «К деплою ДА».
- **Reviewed-Commit:** `2ffeb6a3f95922ed4833110fe90634794ace0804` (HEAD == `origin/master`, closing-docs S7; annotated-тег `pre-round1026-s8` — tag-obj `eeb960b4` → `2ffeb6a`; правки feature — в worktree, **не закоммичены**)
- **Working-Tree-Hash:** `4151d36d7f87809e574c386d1a853ccc10307493049a3b23ff1f910e5681b014`
  - Рецепт (детерминированный, как в S7): SHA-256 манифеста (UTF-8; строки соединены LF + завершающий LF) = строка `git-diff 2ffeb6a sha256=3882c8a6307a361b534f8e2d658abd349c9837ab92154eed3ed9cfc9d084d19a` (SHA-256 **сырых байт** stdout `git diff 2ffeb6a`) + по строке `<путь> sha256=<hash>` для каждого untracked-файла (сортировка, POSIX-пути), **кроме** `plans/features/summary-analytics-adapter-round1026/review.md` (сам отчёт).
  - Per-file (SHA-256, lowercase): adr `c11e297ba59a4b7601e756f5f6bc74cac1e87ed1a4d89c40d4b402e41a46e03a`, evidence `d4740b944c09ce28165f2959b9f17faae345b574c48fc000f8d8d4e934f3b390`, spec `f397f3fd378625c9ea958dcd934595316f28fdb6668ff3a970a2c21138d71a6f`, tasks `220adab72a433868fddab00118fe9bce85cba1c35b6e3d678cd5faf3bd1da0c4`, `services/execution_graph_source.py` `948f7e7824a00d562476a2d2e123cd4e846747bb3c0773f4a08dce26d32e5ea6`, `tests/js/round1026_s8_execution_graph_test.js` `82059cc753bc57f20ff6bbffd5addad8c4e26217ab96e56b5e2496a57d3016da`, `tests/test_summary_execution_graph_round1026.py` `7dc3bac3131a05c50910cbe3c8b99b94bdcd45d2d0384f254f21f709f559a870`.
  - Запись в `plans/reports/audit_backlog.md` сделана **до** хэширования и входит в diff-SHA; `review.md` — вне манифеста (артефакт ревью). Любая правка product code / untracked-кода / `spec.md` после фиксации делает binding устаревшим.
- **Spec-Hash:** `f397f3fd378625c9ea958dcd934595316f28fdb6668ff3a970a2c21138d71a6f`
- **Git base и inspected change scope:** база `2ffeb6a`; **34 modified + 7 untracked** (из untracked `review.md` создан этим отчётом). Код S8: `services/execution_graph_source.py` (NEW), `web/api/analytics.py` (аддитивный `GET /analytics/execution/latest` + аддитивный `price_known` в `/analytics/usage/summary`), `web/static/execution_graph.js` (`STEP_KIND`/`STEP_LABEL` + `fromExecution`), `web/app.js`/`web/index.html`/`web/static/app.css` (§112-блок, mobile §29), `services/summary_generator.py`/`services/summary_run_log.py` (аддитивная фиксация in-memory снапшота прогона), `config/settings.py`+`README.md` (bump 2.58.27), тесты. **Вне diff (подтверждено пустым `git diff --name-only 2ffeb6a`):** `services/telegram_send.py`, `services/summary_xml.py`, `services/image_generation.py`, `web/api/routes.py`, `services/param_catalog.py`, `db/**`, `services/summary_test_run.py`, манифесты зависимостей.

## Проверки (воспроизведено @Reviewer независимо, 24.09.2026)

| Проверка | Команда/метод | Результат |
|---|---|---|
| Полный регресс pytest | `.venv\Scripts\python.exe -m pytest -q` | **8926 passed / 0 failed** (115.08 s) — baseline 8890 → +36 |
| Новый Python-тест S8 | `pytest tests/test_summary_execution_graph_round1026.py -q` | **31 passed** |
| JS (все файлы) | цикл `node tests/js/*.js` | **OK=46 FAIL=0** (baseline 45) |
| S8/RBAC/API | `pytest tests/test_webapp_analytics_api.py tests/test_webapp_f6_round1025.py tests/test_webapp_round1024_nodeflow.py` | **39 passed** (401/403/200, `publication_status=gated`, `price_known`) |
| 2-вызовность | `pytest tests/test_summary_l1_clusterizer.py tests/test_summary_test_run.py -k two_calls` | **3 passed** (`await_count==2`) |
| `git diff --check` | — | exit **0** |
| Каталог | `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`; `Settings`=**426** |
| Δ DDL | `git diff --name-only 2ffeb6a -- db` + `git status --porcelain db` | пусто; untracked в `db/` нет |
| Вне diff | `git diff --name-only 2ffeb6a -- <запрещённые>` | пусто (все границы §13 сохранены) |
| `PUBLISH_*` | `rg` по изменённым исходникам S8 | 0 вхождений |
| R18 | `git cat-file -t`/`rev-parse`, `Test-Path`, `git stash list` | тег `pre-round1026-s8` (annotated, obj `eeb960b4` → `2ffeb6a`); `var/backups/s8-round1026-20260924-053821/` ✓; `.env.bak.round1026-s8` ✓; `stash@{0}` не тронут ✓ |
| Release readiness | import `APP_VERSION`; README | `2.58.27`; README `v2.58.27`; cache-bust `?v=__APP_VERSION__` |

## Линза 1 — requirements/correctness coverage (REQ-S8-01…-14 / SC-01…SC-18)

| REQ | Реализация (факт) | Тест/проверка | Вердикт |
|---|---|---|---|
| REQ-S8-01 | reuse F6 `ExecutionGraph`; `fromExecution` (`web/static/execution_graph.js:338+`) | JS-тест к.7; ровно одна карта `class="token-flow mb-3"` | OK |
| REQ-S8-02 | `STEP_KIND` + узлы только из реальных данных; «нет данных → нет узла» (`normalizeExecutionNode`, `llm_node`/`algorithm_node`/`format_node`) | `TestAlgorithmNode/TestFormatNode/TestLlmNode.test_no_data_no_node`; JS к.5 | OK (нюанс L-R1026S8-1) |
| REQ-S8-03 | `filter→algorithm`, `l1_clusterizer`/`l2_writer→llm`, `formatting`/`format→format`, `publication→publish` (GATED) | `TestStepKindMapping`; JS к.1 | OK |
| REQ-S8-04 | вторая визуализация не создана; `GraphViewer`/`NodeCard`/`DetailPanel` не переписаны (diff `index.html` — только аддитивный §112-блок) | `test_single_visualization_and_no_rewrite`; JS к.7 | OK |
| REQ-S8-05 | тот же `ExecutionNode`-контракт (`_node`, `services/execution_graph_source.py:280`) | `test_order_and_linear_links`; JS к.2 | OK |
| REQ-S8-06 | канонический shape `id/runId/parentIds/kind/stageKey/stageLabel/status/provider/model/…`; недоступное → `null` | `TestLlmNode.test_honest_cost_known`; JS к.2 | OK |
| REQ-S8-07 | `algorithm` — без LLM-токенов/стоимости; `llm` — model/токены/`cost`/`tokensEstimated`; `format` — канал/абзацы/статус | `TestAlgorithmNode.test_real_filter_metrics`, JS к.2 | OK |
| REQ-S8-08 | отдельный backend-модуль нормализации + клиентский `fromExecution` (вне SVG/Vue); связи — только линейная последовательность одного `run_id`, `hasBranch=false` | `test_gap_does_not_glue_distant_stages`; JS к.2/к.3 | OK (нюанс L-R1026S8-1) |
| REQ-S8-09 | `metrics_block` — полный перечень §112 (13 позиций); UI `execMetricsRows` — 13 строк | `TestMetricsBlock.test_full_list_and_gated`; JS к.7 | OK |
| REQ-S8-10 | `price_known=false`/`null` → `None`/«Нет данных», **никогда `$0`**; `BOOL_AND(price_known)` в `/analytics/usage/summary`; `-1`→«Без лимита»; `publication_status="gated"` | `test_unknown_price_never_zero`, `test_unknown_cost_no_fake_zero`, `TestContextLimit`; JS к.4/к.6 | OK (нюанс L-R1026S8-2) |
| REQ-S8-11 | единый ключ: SQL по `correlation_id` (`_SELECT_STEPS_SQL`) + снапшот по `run_id`; второй идентификатор не введён | `test_admin_200_llm_nodes_from_pg`; JS к.2 | OK |
| REQ-S8-12 | вертикальная последовательность (`flex-direction: column` — существующая F6 CSS) + аддитивные mobile-правила (`.token-flow{min-width:0}`, `@media 360px` перенос чисел) | существующий F6 §29-тест (`round1025_f6_analytics_memory_test.js` к.7) | OK (без отдельного S8-теста — Info) |
| REQ-S8-13 | R17/R18/Δ DDL=0/Δ каталога=0/CSP/zero-build/2-вызовность | таблица выше; `TestR17`, `TestInvariants`, `TestBoundaries` | OK |
| REQ-S8-14 | §110-viewer/S9/publish — вне diff; S9-контур не дублируется (тот же `llm_usage_events`) | `TestBoundaries`, `test_no_llm_calls_in_s8_source` | OK |

SC-01…SC-18: покрыты перечисленными проверками; SC-18 (live Эпика 1/S1–S5/S7/S9) — **PENDING OWNER VERIFICATION** (не блокирует ядро S8, соответствует ADR D1).

## Линза 2 — focused change audit coverage

1. **Δ DDL=0:** `db/**` вне diff, untracked в `db/` нет; новый модуль не содержит `CREATE/ALTER/CREATE INDEX` (`test_no_ddl_in_s8_source`); снапшот — in-memory (`RunSnapshotStore`, TTL 900s/≤20, `threading.Lock`). **OK.**
2. **Δ каталога=0:** `services/param_catalog.py` вне diff; `Settings`=426 (`test_catalog_delta_zero`); `gen_param_registry --check` OK; новых env/флагов нет (`SUMMARY_EXECUTION_GRAPH_ENABLED` отсутствует — `test_no_new_catalog_flag`). `plans/docs/param-registry-round1025.meta.md` изменён только `APP_VERSION` (provenance-штамп, S7-прецедент), каталог/TSV не переиздавались. **OK.**
3. **R17:** узлы/снапшот — только числа/коды/id/строки статусов; `record_run` игнорирует неизвестные ключи (`test_record_ignores_unknown_keys`); `llm_node` metadata = `{tokensEstimated,module,source,toolName}` (`test_node_has_no_raw_text_fields`); новые `RunContext`-поля (`drop_percent/filter_*/format_*`) **не выводятся** ни в `log_summary_start/complete/failed` (проверено чтением `summary_run_log.py:186-230`). **OK.**
4. **R18:** тег/бэкап/`.env.bak`/`stash@{0}` целы (таблица). **OK.**
5. **CSP/zero-build, 0 новых зависимостей:** в `execution_graph.js` нет внешних CDN/inline/`eval`/`createElement`/`innerHTML` (JS к.7); манифесты зависимостей вне diff; `web/index.html` — только аддитивный §112-блок. **OK.**
6. **2-вызовность:** S8 — read-only, 0 новых LLM-вызовов (`test_no_llm_calls_in_s8_source`); `await_count==2` зелёные. **OK.**
7. **Границы §13:** `git diff --name-only 2ffeb6a` по `telegram_send.py`/`summary_xml.py`/`image_generation.py`/`routes.py`/`param_catalog.py`/`db`/`summary_test_run.py` — **пусто**; `PUBLISH_RICH/PUBLISH_TEXT` — 0; `kind="publish"`-узлы не эмитятся (сервер `llm_node` возвращает `None`; клиент `normalizeExecutionNode` отбрасывает; JS к.3). **OK.**
8. **Скрытые побочные эффекты:** `record_run_from_context` вызывается в `finally` `_run` best-effort (исключение не рвёт прогон); `_apply_filter` не изменён по поведению (аддитивно заполняются `ctx.drop_percent/filter_status/filter_duration_ms` при `run_id==correlation_id`); version-pin тесты обновлены только на `2.58.27` (проверено diff'ом), логика тестов не ослаблена; `test_webapp_f6_round1025.py` — 4→5 маршрутов (санкционированный аддитивный эндпоинт, D3). **OK.**
9. **Binding пересчитан** (значения выше; diff-SHA `3882c8a6…`).

## Спорные трактовки @Builder — вердикты

- **Q1 (аддитивный снапшот в `services/summary_generator.py`/`services/summary_run_log.py`).** **В scope, не scope drift.** ADR D2 прямо требует «структурированный снапшот прогона (S7-данные `RunContext` + `_filter_metrics`, фиксируемые in-memory в конце прогона)», а spec §19 перечисляет «аддитивный снапшот прогона (in-memory)» среди артефактов. Изменения аддитивны, best-effort/fail-open, 0 LLM-вызовов, поведение пайплайна не меняют; новые поля `RunContext` в лог §108 не выводятся. Блокера нет.
- **Q2 (связи узлов = линейная последовательность по каноническому порядку внутри одного `run_id`).** **Санкционировано, не выдуманная связь.** spec §3/§9 (D6): «Связи (`parentIds`) — только подтверждённая линейная последовательность **одного** `run_id`; ветвление без `parent_id` не изобретается»; «допускается только подтверждённая линейная последовательность одного `run_id` (предыдущий реальный этап); при отсутствии предшествующего этапа — `parentIds=[]`». Порядок `filter → L1 → L2 → formatting` — инвариант пайплайна (`STAGE_ORDER`), все узлы принадлежат одному `run_id`; ветвление не достраивается (`hasBranch=false`), рёбра-спины в UI не превращаются в ветки (`web/app.js:2540-2546` — `children` только для `e.branch`). Блокера нет.
- **Q3 (`_context_limit_info` вычисляется в endpoint, а не в чистом `execution_graph_source.py`).** **Не нарушение D3.** D3/§25 запрещают преобразование API-ответов **внутри SVG/Vue-компонента** и требуют отдельный чистый модуль для нормализации «raw sources → canonical nodes». Нормализация узлов/метрик выполнена в чистом модуле; `_context_limit_info` — config-derived (читает `hot_config`/`settings`) и намеренно оставлен в роутере, чтобы чистый модуль остался без побочных эффектов. Архитектурное замечание (L-R1026S8-2: поле пока не потребляется UI), блокера нет.

## Проверенные counterexamples (не только happy path)

- **Нет данных этапа → нет узла:** `algorithm_node({})`/`None`/`{"threads":3}` → `None`; `format_node({})`/`None` → `None`; `llm_node({"step":""})`/`None` → `None`. ✓
- **Пропуск этапа не «склеивает» несоседние:** `build_graph` с одним `l1_clusterizer` → `parentIds=[]` (нет фиктивного `filter`-родителя). ✓
- **`kind="publish"`:** серверный `llm_node({"step":"publication"})` → `None`; клиентский `fromExecution` с publish-узлом → узел отброшен, ребро к нему снято; `PUBLISH_*` в коде = 0. ✓
- **Неизвестная цена:** `price_known=false` + `cost_usd=0` → `cost=None`/`costCurrency=None`/`priceKnown=false`; `metrics.cost.l1/total=None`; UI `fmtCost(...,false)`→«Нет данных». `$0` возможен только при подтверждённом `price_known=true` и `cost=0`. ✓
- **Пустой/битый ответ эндпоинта:** `fromExecution(null/undefined/{}/{nodes:[]})` → `empty=true`, `nodes=[]`. `build_graph("",None,[])` → `empty=true`, `publication_status="gated"`, `metrics` shape-совместим. ✓
- **PG down / телеметрия OFF / нет снапшота:** эндпоинт возвращает пустой shape-совместимый граф (fail-open), `logger.warning` без падения; `fromExecution` на пустом → `empty=true`. ✓
- **Истёкший/лишний снапшот:** `RunSnapshotStore` TTL/лимит ≤20 (эвикция старейшего), `record_run` с пустым `run_id` — no-op; метрики другого прогона не подмешиваются (`test_record_run_from_context_ignores_stale_metrics`). ✓
- **L-F6S-1:** `fromSummary` c `price_known:false` → `totals.priceKnown=false`/`cost=null`; без поля (старый ответ) → `true` (обратная совместимость). ✓
- **R17:** неизвестные ключи (`prompt`/`raw_text`) не сохраняются; в узле нет `prompt/response/secret/api_key/authorization`; новые `RunContext`-поля не попадают в §108-лог. ✓
- **R18/границы:** тег/бэкап/`.env.bak`/stash целы; публикационный путь/`routes.py`/`param_catalog.py`/`db/**`/`summary_test_run.py` вне diff. ✓
- **Пограничный (см. L-R1026S8-1):** снапшот с одним `source_count` (пустое окно / фильтр OFF) → `algorithm_node` **создаётся** (`status="unknown"`, `metrics.source_count`). spec D2 перечисляет `source_count` как вход узла `algorithm`, поэтому это трактуется как допустимое, но зафиксировано как non-blocking (рекомендация — требовать filter-derived поле либо явно задокументировать).

## Blocking findings

**Нет.** Critical/High/блокирующих Medium = 0. «К деплою ДА».

## Non-blocking debt (owned follow-up)

- **L-R1026S8-1 (Low, honesty/§3 edge):** `algorithm`-узел эмитится по одному `source_count` без filter-метрик (пустое окно / фильтр OFF) — `services/execution_graph_source.py:323-325`; UI покажет «Алгоритмический фильтр · Обработано: N» со статусом «нет данных». spec D2 явно допускает `source_count` как вход узла, поэтому non-blocking; рекомендация — требовать `filter_status`/filter-derived поле либо задокументировать трактовку.
- **L-R1026S8-2 (Low, unused/§112):** `metrics.context` (`_context_limit_info`, `web/api/analytics.py:165-183,186`) вычисляется и отдаётся, но UI `execMetricsRows` его не рендерит → «Без лимита» пользователю не видно. В перечне REQ-S8-09 контекст-лимита нет, поэтому non-blocking; рекомендация — либо вывести строку, либо не отдавать поле.
- **L-R1026S8-3 (Info, docs):** комментарий `tests/test_round1025_f8_registry.py:125` после bump читается как «S7 … 2.58.25 → 2.58.27» (фактически S7→2.58.26, S8→2.58.27).
- **Info:** mobile §29 (S8-специфичные CSS-маркеры `.token-flow{min-width:0}`, `@media 360px`) не покрыты отдельным S8-тестом — существующий F6 §29-тест и вертикальный `.token-flow` (flex-column) сохраняются.
- **Info:** L-R1026S7-1 (Low, R17, pre-existing S1, вне diff) остаётся OPEN — S8 его не касался (вне scope).

## Unavailable checks

- **Live-приёмка владельца** (Telegram/WebView, Эпик 1/S1–S5/S7/S9) — **PENDING OWNER VERIFICATION** (SC-18; соответствует ADR D1, не блокирует ядро S8).
- **Deploy T-3433 не выполнялся** (вне Reviewer gate); прод/`/api/health`/`database is locked` не проверялись (нет SSH).
- **Baseline pytest 8890/0 и JS 45/45 на `2ffeb6a` не перемерялись** (worktree занят); дельта +36/+1 согласуется с составом изменений (31 новый pytest-файл-кейс + 4 endpoint-кейса + регистрация JS-теста + 1 JS-файл).
- **Ручной визуальный прогон UI в браузере** не выполнялся (нет live-стенда); mobile §29 проверен статически (CSS/разметка) и существующим F6-тестом.

## Handoff

RESULT: **Approved** @Orchestrator — **единый gate T-3428/T-3429 пройден** (линза 1 requirements/correctness + линза 2 focused change audit). Актуальные bindings: Reviewed-Commit `2ffeb6a`, Working-Tree-Hash `4151d36d…`, Spec-Hash `f397f3fd…`. Отдельного Scanner-approval не существует. Далее: T-3430 (rework **не требуется** — блокеров нет) → T-3431 merge (`plans/ARCHITECTURE.md` §79, ADR-1026-10 Accepted) → T-3432 archive → T-3433 deploy (bump 2.58.27; откат `pre-round1026-s8`/`git revert`) → T-3434 handoff. Non-blocking L-R1026S8-1/-2/-3 — owned follow-up; live — PENDING OWNER VERIFICATION. **Binding связан с текущим состоянием worktree: любая правка product code / untracked-кода / `spec.md` после этой фиксации делает approval устаревшим и требует пересчёта.**
