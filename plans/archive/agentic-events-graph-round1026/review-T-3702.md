# A9 `agentic-events-graph-round1026` — единый Reviewer gate (T-3702)

- **Feature-ID:** `agentic-events-graph-round1026` (Epic 3 «Agentic Intelligence», Wave 5 (продолжение), раунд 10.26)
- **Risk-Level:** **R2** (финальный — подтверждён по фактическому diff; `threat-failure-analysis.md` — NOT_APPLICABLE, см. §4)
- **Status: Approved** (feature gate; `included in pending epic release`, deployment `DEFERRED_TO_EPIC`)
- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` (`git rev-parse HEAD`)
- **Working-Tree-Hash:** `84d6df00b7cc5ce13cc343d01e1ea4cd6474587560c9e92739f23a42bc210f23`
- **Spec-Hash:** `3f7035843cdd9fa0f76e7ecab8aa76cfbd9b6a24b68d7cd430b1b559b963cd1e`
- **Гейт:** feature gate (НЕ агрегатный epic release gate). DevOps/commit/tag/bump не выполнялись и не санкционируются.
- **Дата:** 25.09.2026. **Scanner:** отсутствует (единый Reviewer gate, обе линзы в одном проходе).

## 1. Git base и inspected change scope

- **Baseline-анкер:** `e8646af` + **UNCOMMITTED epic-release дерево A2–A8** (ничего не коммитилось/не откатывалось; staged — пусто).
- **A9-санкционированные изменения (подтверждено построчно):**
  - `services/agentic_events.py` (NEW, 234 стр.) — единый R17-safe event-enum + whitelist + fail-open `emit_agentic_event`.
  - `services/execution_graph_source.py` — аддитивно: `KIND_TOOL`, 9 stage-констант/`AGENTIC_STAGE_ORDER`/labels, `_AGENTIC_KEY`/лимит 64, `append_agentic`/`record_agentic_event`/`get_agentic_events`, `_stage_for_tool`, `_build_agentic_nodes`, `_agentic_text_generation_node`, агентная ветка `build_graph`.
  - `services/direct_chat_service.py` — только 4 точки эмиссии Phase P (`DECISION_START`/`DECISION_COMPLETE`/`MESSAGE_IGNORED`/`REACTION_SENT`) + инициализация `pre_target=None`.
  - `services/tool_loop.py` — точки эмиссии `TOOL_PLAN_CREATED`/`TOOL_CALL_START`/`TOOL_CALL_COMPLETE`/`TOOL_CALL_FAILED` (invalid_args / chain-skip / dispatch-exception / дедуп).
  - `services/image_generation.py` — `run_image_request`: `IMAGE_CONTEXT_RESOLVED` + `IMAGE_GENERATION_START/COMPLETE/FAILED`; генератор `generate_and_send` (§104) не тронут.
  - `services/anticliche_worker.py` — `_event` маршрутизирован в `emit_agentic_event`.
  - `services/smartmodule_utils.py` — **только L-1**: import `TelegramForbiddenError` + `except TelegramForbiddenError → REACTION_FORBIDDEN` перед generic.
  - `config/settings.py` — env-only `ClassVar AGENTIC_EVENTS_ENABLED` (default ON).
  - `web/static/execution_graph.js` — display-only: +9 записей `STEP_KIND`/`STEP_LABEL`.
  - `tests/test_agentic_events_round1026.py` (NEW, 52), `tests/test_smartmodule_utils.py` (+2 L-1), `tests/js/round1026_s8_execution_graph_test.js` (+1 секция), boundary-реконсиляции A1/A3/A8, evidence/tasks.
- **Интеграционные края:** `web/api/analytics.py` — **diff пустой**; агентные узлы доходят до ответа через неизменённые `build_graph` → `_execution_response` → `GET /analytics/execution/latest`.

## 2. Checks performed (фактические прогоны Reviewer, не с Builder)

| Проверка | Результат |
|---|---|
| `pytest -q tests/test_agentic_events_round1026.py` | **52 passed** (2.68 s) |
| `pytest -q tests/test_smartmodule_utils.py -k "L1A9 or forbidden or generic"` | **2 passed**, 34 deselected |
| Затронутые сюиты (direct_chat/handlers/concurrency, decision_making, agentic_ai, image_generation, image_context_memory, tool_calling, tool_coordinator, smartmodule, anticliche_semantics, webapp_api, webapp_parity, summary_execution_graph) | **854 passed** (17.30 s) |
| Full `pytest -q` | **9513 passed / 0 failed** (159.09 s) |
| JS `tests/js/*.js` (all) | **47/47 exit 0** (`S8-EXECGRAPH-OK`) |
| `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 473 == REGISTRY …` |
| Каталог (direct recompute) | REGISTRY **473** · Settings **430** · categorized **448** · GROUPS **102** · `_TAB_BY_GROUP` **100** · TAB_RULES **21** → Δ=0 |
| Канон / версия | `TOOL_CALLING_TOOLS == 12`; `APP_VERSION == 2.58.30`; `AGENTIC_EVENTS_ENABLED` в REGISTRY **нет** |
| Δ DDL | `pytest tests/test_database.py` **98 passed** (SQLite v12); grep `CREATE/ALTER/DROP/CREATE INDEX` по A9-источникам = **0** |
| `git diff --check` | exit **0** (только LF→CRLF warnings) |
| Per-file SHA-256 vs `evidence.md` (10 ключевых файлов) | **все совпали** — дрейфа нет |

### 2.1. Независимые негативные/адверсариал-пробы (написаны Reviewer)

- **R17-негатив (smuggling):** `emit_agentic_event("DECISION_COMPLETE", action="Досье: Иван Петров промпт <system> секрет-API-KEY-123", reason="hello world", prompt=…, message_text=…)` → секрет **отсутствует** и в логе, и в store; ключи `prompt`/`message_text`/`action`/`reason` отброшены; имя инструмента с пробелами отфильтровано, осталось только безопасное. **PASS.**
- **Fail-open:** `record_agentic_event` бросает → `emit_agentic_event` не бросает, лог-строка сохранена. **PASS.**
- **Kill-switch OFF-паритет:** `AGENTIC_EVENTS_ENABLED=False` → 0 логов, 0 store, `latest_run_id() is None`. **PASS.**
- **No-fake-tokens:** агентные `algorithm`/`tool`-узлы → `inputTokens=outputTokens=cost=None`, `priceKnown=False`. **PASS.**
- **Bounded/конкурентность:** 8×20 конкурентных эмиссий → store ограничен **64** событиями (lock защищает). **PASS.**
- **`message_id=None`:** не падает, событие логируется, decision-узел строится. **PASS.**

## 3. Requirement / evidence coverage (REQ-A9-01…-14 → SC)

- **§49 / REQ-A9-01:** закрытый enum `AGENTIC_EVENT_TYPES` = 12 §49 + 8 `ANTI_CLICHE_*` = 20; все 12 эмитятся и наблюдаются (параметризованный тест), `schema_version="1"`. **OK.**
- **REQ-A9-02:** обязательные поля (`run_id`/`chat_id`/`message_id`/`action`/`tools`/`reason`/`duration_ms`/`errors`/`ts`) — whitelist/типизация; отсутствующее = отсутствие поля, не выдумано. **OK** (по дизайну «нет данных → None/`-`»).
- **REQ-A9-03 / R17:** whitelist id/enum/числа/имена инструментов/коды; строки валидируются «идентификатором без пробелов»; негативные тесты + независимая проба Reviewer pass. **OK.**
- **REQ-A9-04 / §53:** молчание → узел Decision с `reason`/`action`; отказ инструмента → узел с `tool`/`status`/`error_code`. **OK.**
- **REQ-A9-05/-06/-07 / §51:** REUSE существующего ExecutionGraph; 9 stage-констант и kind-маппинг (`algorithm/tool/…/llm`); второй аналитики/endpoint/store нет. **OK** (см. L-A9-3702-02 — reachability-нюанс, non-blocking).
- **REQ-A9-08:** honest-`None` (`null` ≠ `$0`), токены только из реальных `llm_usage_events`. **OK.**
- **REQ-A9-09:** silent → узел Decision без Text Generation/Вербализатора; `MESSAGE_IGNORED` зафиксирован. **OK.**
- **REQ-A9-10/-11 / §50:** поверхность — только аддитивные `STEP_KIND/LABEL`; новых панелей/вкладок/параметров нет (web/index.html/app.js изменены A5, не A9); Δ каталога=0. **OK.**
- **REQ-A9-12 / L-1:** `TelegramForbiddenError → REACTION_FORBIDDEN`, 1 вызов, 0 текста, generic → `unknown` не сломан. **OK.**
- **REQ-A9-13:** SC-A9-13 закрывается событиями tool + графом. **OK.**
- **REQ-A9-14:** 8 `ANTI_CLICHE_*` в enum/whitelist/kill-switch, без форсирования в чат-граф. **OK.**
- **SC-A9-15:** OFF-паритет + fail-open + регресс. **OK.**
- **SC-A9-16:** канон 12 / нет 3-го LLM-вызова / Δ DDL=0 / Δ каталога=0 / §104 no-go / A8/A7/A1 не переписаны. **OK.**

## 4. Focused change audit + adjudications

- **`web/api/analytics.py` EMPTY diff — АДЪЮДИКАЦИЯ: подтверждено.** `git diff e8646af -- web/api/analytics.py` пуст, A9-маркеров нет. Новые узлы доходят через неизменённые `execution_graph_source.build_graph` (стр. 748+) и `_execution_response` (analytics.py:186/188); endpoint `/analytics/execution/latest` (analytics.py:281) единственный, RBAC `requires_global_admin()` и fail-open shape не тронуты. Заявка Builder «аддитивно без правки файла» — истинна.
- **A9-маркеры вне санкции — нет scope creep.** `param_catalog.py`, `tool_schemas.py`, `worker_budget.py`, `analytics.py`, `tool_router.py`, `database.py`, `pg_db.py` — **0** вхождений `agentic/emit_agentic/AGENTIC_EVENT`. Изменения этих файлов в дереве — от A2–A8, не от A9. Границы A1 (`CoordinatorDecision`) не дублированы, A2–A6 не переписаны, A7-политика (`_decision_pre_action`) и A8-механика (`set_message_reaction`) не тронуты, §104 `generate_and_send` не изменён.
- **Boundary-реконсиляции A1/A3/A8 — АДЪЮДИКАЦИЯ: легитимны, ассерты не ослаблены.**
  - A1 (`test_tool_coordinator_round1026.py`): `execution_graph_source.py` и `web/static/execution_graph.js` убраны из forbidden и добавлены в web-allowlist с NOTE A9 (ADR-1026-22 D1/D7/D10); прочие forbidden-пути и `api/routes.py` сохранены; счётчики обновлены на A8-baseline (473/430/448/102/100/21), канон 12. Это санкционированное расширение, а не сокрытие.
  - A3 (`test_unified_image_request_round1026.py`): тот же forbidden-список + web-allowlist с NOTE A9; §104 прикрыт A3-AST-гейтом. Легитимно.
  - A8 (`test_telegram_reactions_round1026.py`): `test_no_a9_events` → `test_a9_events_scope_reconciled`; теперь проверяет **отсутствие** `REACTION_SENT`/`MESSAGE_IGNORED` в `smartmodule_utils.py` (граница A8) и **наличие** их в `direct_chat_service.py` (санкция A9). Это корректная инверсия контракта, а не ослабление: A8-граница сохранена и усилена.
- **Threat N/A (R2, ADR-1026-22 D1) — АДЪЮДИКАЦИЯ: обоснование достаточно.** Дополнительно проверено Reviewer:
  - **DDL=0** (grep 0, SQLite v12).
  - **Hot-path:** `emit_agentic_event` — синхронный, но **неблокирующий**: `logger.info` + in-memory `append_agentic` под коротким `threading.Lock`. Проверено, что `BetterStackHandler.emit` **буферизует** запись в `deque` и не делает сетевого I/O в вызывающем потоке (сеть — в фоновом `betterstack-flusher`); `LogRing` — in-memory. Новых очередей/сетевого I/O на hot-path нет. Await/`create_task` в эмиссии отсутствуют.
  - **R17** — негативные тесты + независимая проба pass.
  - **Вторая аналитика/endpoint** — нет.
  Ни один R3-триггер (DDL, блокирующий hot-path, утечка R17, вторая аналитика, смена канона/каталога) не наступил → `threat-failure-analysis.md` NOT_APPLICABLE правомерно.
- **Точки эмиссии (spot-check 3):** Phase P (`DECISION_START` на входе, `DECISION_COMPLETE` после `_decision_pre_action`, silent/react short-circuit) — поля `run_id`=correlation_id, `action`/`reason` — коды A7; `tool_loop` (plan/start/complete/failed с `tool`/`round`/`status`/`error_code`/`out_chars`) — значения R17-safe; `image_generation.run_image_request` (`resolution`/`sources`/`facts`/`slice`/`prompt_chars`/`latency_ms`, `source`, `reason_class`). Блокирующих `await`/`gather` в эмиссии нет.
- **R17 в реальных строках эмиссии:** все call-sites передают только id/enum/числа/имена инструментов/коды; `ANTI_CLICHE_*` (`anticliche_worker._event`) — только capacity/counts/round/status/reason/model/source/raw_len; фразы не передаются.
- **JS display-only:** `+10` строк в `STEP_KIND`/`STEP_LABEL`, renderer/`fromExecution` не рефакторены; новых компонентов/панелей нет.

## 5. Counterexamples checked

- Подмена приватного текста в `action`/`reason`/произвольные ключи → отброшено (лог+store чисты). **Проверено.**
- Ошибка store во время эмиссии → hot-path не рвётся (fail-open). **Проверено.**
- `AGENTIC_EVENTS_ENABLED=false` → паритет baseline (0 событий/узлов/логов). **Проверено.**
- Агентный узел алгоритмического класса → нет выдуманных токенов/стоимости. **Проверено.**
- Silent-прогон → Decision без Text Generation/Вербализатора. **Проверено (тест).**
- Нагрузка/конкурентность → store ограничен 64, без гонок. **Проверено.**
- `message_id=None` / отсутствующий `run_id` → нет падения; без `run_id` в граф не пишется. **Проверено.**
- Неизвестный `event` → отброшен (закрытый enum). **Проверено (тест).**
- LEGACY-граф без агентных данных → прежний путь (`filter`/llm/format/publish) не изменён. **Проверено (тест + full suite).**

## 6. Non-blocking debt (bounded follow-up)

1. **L-A9-3702-01 (Low, точность evidence).** `evidence.md` T-3699 заявляет адверсариал-покрытие «конкурентная/большая эмиссия (bounded 64), message_id=None», но в `tests/test_agentic_events_round1026.py` явных тестов на bounded/конкурентность/`message_id=None` нет. Reviewer независимо подтвердил корректность (лимит 64, потокобезопасность, `message_id=None` без падения), поэтому это дефект **заявки**, а не кода. Рекомендация: добавить 1–2 явных теста илиуточнить формулировку T-3699.
2. **L-A9-3702-02 (Low, наблюдаемость §51).** `_AGENTIC_TOOL_STAGE_PATTERNS` маппит RAG через `("rag","knowledge","search_knowledge")`, Factcheck через `("factcheck",…)`, но **ни один** из канонических 12 инструментов не содержит этих подстрок (`query_chat_memory` уходит в `memory_lookup`; `dig_into_lore`/`get_bot_health`/`get_recent_history`/`compile_lore_story` не маппятся ни на один этап). Значит, в реальном прогоне достижимы максимум 7 из 9 §51-этапов; тест использует синтетические имена (`rag_search`, `factcheck_text`), которых в каноне нет. Требованию это не противоречит (спек: «нет данных этапа → нет узла»), но формулировку «9 реальных этапов» нельзя считать полностью реализуемой текущим каноном инструментов. Рекомендация: при следующем касании либо добавить маппинг существующих инструментов на RAG/Factcheck, либо зафиксировать ограничение в A10/доке. **Не блокирует** (SC-A9-06 выполнен: этапы отображаются при наличии данных; отсутствие данных — честное отсутствие узла).
3. **L-A9-3702-03 (Low, косметика).** В `build_graph` top-level `started_at` вычисляется только из `llm_nodes`, пустого на агентном пути, поэтому у агентного прогона `started_at=null` и у агентных узлов `startedAt=null`, хотя у `text_generation` есть реальная LLM-строка. UI (`app.js`) `startedAt` потребляет. Не требование, отображение остаётся корректным (без токенов/статусов).
4. **L-A9-3702-04 (Low, формат логов).** F0.3 `_event` теперь логируется единым логгером `services.agentic_events` (без префикса `[anticliche] `) и при `AGENTIC_EVENTS_ENABLED=false` молчит. Это принятая схема D11 (единый канал/kill-switch), но внешний парсинг журнала, завязанный на старый префикс/имя логгера, может потребовать обновления.

## 7. Blocking findings

**Нет.** Critical/High/requirement-blocking Medium отсутствуют. Все четыре пункта §6 — non-blocking, отправлены как bounded follow-up.

## 8. Unavailable checks / замечания по окружению

- **Полный pytest** воспроизведён: **9513 passed / 0** (чистый прогон). При этом 1 из 3 прогонов в этом окружении дал **флейк в `tests/test_betterstack_handler.py::TestNoRedirect::test_real_302_not_followed_by_opener`** (localhost-сервер: `hits["redirect"] == 2` вместо 1; в изоляции и с A9-тестами проходит), а 1 прогон — async-таймаут в несвязанном тесте. Оба случая **не относятся к A9** (A9 не трогает `betterstack_handler`/urllib/asyncio) и классифицированы как среда-флейк. Число тестов совпадает с заявкой Builder (9513).
- Сетевые/провайдерские/LLM-вызовы не выполнялись; тесты — unit/integration с fakes.
- A3 owner-gate `PENDING OWNER VERIFICATION` — внешний, A9 его не закрывает.

## 9. Binding (точное состояние ревью)

- **Reviewed-Commit:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working-Tree-Hash (recipe):** `sha256( "diff-head\n" + git diff HEAD --no-color (staged+unstaged, весь tracked) + "\nuntracked\n" + sorted("path <sha256(path)>") по `git ls-files --others --exclude-standard` )` = `84d6df00b7cc5ce13cc343d01e1ea4cd6474587560c9e92739f23a42bc210f23`
  - компоненты: `sha_diff_head=6a733e7191855eecc4ae256205bfdd56ab6a915372a91aa6db6e538e670efce1`, `sha_untracked_manifest=aa74ed16d09cd391928bb6902db2f706ec4213aef25a1751f5dbfe285c1e15aa`, untracked files = 55.
- **Spec-Hash:** `3f7035843cdd9fa0f76e7ecab8aa76cfbd9b6a24b68d7cd430b1b559b963cd1e`
- Любое последующее изменение кода, untracked-файлов, сгенерированных release-входов или `spec.md` делает это одобрение **stale**.

## 10. Verdict

**Approved** — обе линзы (requirements/correctness + focused change audit) независимо поддержаны; REQ-A9-01…-14 → SC покрыты, R17 подтверждён независимой негативной пробой, REUSE-граф и honest-метрики соблюдены, L-1 работает, канон 12 / Δ DDL=0 / Δ каталога=0 / `analytics.py` diff пуст, OFF-паритет и fail-open воспроизведены. Одобрение — **feature gate** для включения в pending epic-release Эпика 3; агрегатный epic release gate и DevOps — отдельно.
