# A9 `agentic-events-graph-round1026` — Evidence (Builder, T-3691…T-3701)

- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 5 (продолжение) — A9.
- **Risk:** **R2** (финальный; spec §13 / ADR-1026-22 D1: in-memory расширение
  `RunSnapshotStore`, Δ DDL=0). **`threat-failure-analysis.md` — `NOT_APPLICABLE`**
  (R3-ветка DDL/блокирующего hot-path/R17-утечки/второй аналитики не наступила;
  D1/D12). Reviewer может повысить риск по фактическому diff — тогда артефакт обязателен.
- **Baseline anchor:** HEAD **`e8646af`** (`e8646af2bcaa79b55cadda756d0e8cc7789fe24f`)
  + UNCOMMITTED epic-release дерево A2–A8 (не трогались/не коммитились). A9 построен
  поверх; **0 коммитов, 0 тегов, без bump**.
- **Release policy:** EPIC_ONLY → deploy **`DEFERRED_TO_EPIC`**; @DevOps не вызывался.
- **APP_VERSION:** **2.58.30** (без bump). **Канон инструментов:** **12**.
- **Feature dir:** `plans/features/agentic-events-graph-round1026/`
- **Spec:** `spec.md` (REQ-A9-01…-14 → SC-A9-01…-16) · **ADR:** `adr-1026-22-agentic-events-graph.md` (D1–D14, binding).

## Changed files (A9 contribution only)

Source:
- **`services/agentic_events.py` (NEW, ~230 строк)** — единственная R17-safe
  точка эмиссии §49/F0.3: закрытый enum `AGENTIC_EVENT_TYPES` (12+8=**20**),
  `SCHEMA_VERSION="1"`, `EVENT_FIELDS`-whitelist, `filter_event_fields`,
  синхронный fail-open `emit_agentic_event`, `agentic_events_enabled`
  (env-only kill-switch per-call). Строки-значения валидируются «идентификатором
  без пробелов» → текст сообщений/досье/промптов не проходит.
- **`services/execution_graph_source.py`** — аддитивно (D1/D7/D8):
  `KIND_TOOL="tool"`; 9 stage-констант `STAGE_DECISION…STAGE_TEXT_GENERATION`
  + `AGENTIC_STAGE_ORDER` + `STAGE_LABELS`/`STEP_KIND`/`STEP_LABEL` записи;
  `_AGENTIC_KEY`/`_AGENTIC_MAX_EVENTS=64`/`_AGENTIC_EVENT_FIELDS`;
  `RunSnapshotStore.put` сохраняет агентные события; `append_agentic`;
  `record_agentic_event`/`get_agentic_events`; `_stage_for_tool`,
  `_build_agentic_nodes`, `_agentic_text_generation_node`; `build_graph`
  использует агентный путь при наличии событий (legacy-путь без агентных
  данных — байт-в-байт).
- **`services/direct_chat_service.py`** — Phase P (D5/D6): `DECISION_START`
  (вход), `DECISION_COMPLETE` (после `_decision_pre_action`), `MESSAGE_IGNORED`
  (silent-ветка), `REACTION_SENT` (после `react_moai` с outcome 7-enum);
  `pre_target=None` инициализация (аддитивно, без смены политики A7).
- **`services/tool_loop.py`** — (D5) `TOOL_PLAN_CREATED` (имена тулов),
  `TOOL_CALL_START` (перед dispatch), `TOOL_CALL_COMPLETE`/`TOOL_CALL_FAILED`
  (invalid_args / dispatch-исключение / chain-skip / дедуп-skip).
- **`services/image_generation.py`** — `run_image_request` (call-site
  `log_image_context_build`): `IMAGE_CONTEXT_RESOLVED` +
  `IMAGE_GENERATION_START`/`COMPLETE`/`FAILED` вокруг **существующего**
  `generate_and_send` (§104 не тронут).
- **`services/anticliche_worker.py`** — `_event` маршрутизирован через
  `emit_agentic_event` (второй логгер/канал не создан); в чат-граф не
  форсируется (нет `run_id`, D11).
- **`services/smartmodule_utils.py`** — **L-1 (D13, REQ-A9-12):** импорт
  `TelegramForbiddenError` из `aiogram.exceptions` + новый
  `except TelegramForbiddenError: return REACTION_FORBIDDEN` перед generic
  `except Exception`; тот же R17-safe `_warn_reaction_failed`, 1 вызов,
  0 текста/fallback.
- **`config/settings.py`** — env-only `ClassVar`
  `AGENTIC_EVENTS_ENABLED = _env_bool("AGENTIC_EVENTS_ENABLED", True)`
  (рядом с `REACTION_MECHANICS_ENABLED`; Δ каталога=0).
- **`web/static/execution_graph.js`** — display-only (D10): аддитивные
  `STEP_KIND`/`STEP_LABEL` для 9 этапов §51; renderer/`fromExecution` не
  рефакторились.
- **`web/api/analytics.py` — НЕ изменён** (T-3695): агентные узлы идут через
  существующий `build_graph` → `GET /analytics/execution/latest`; нового
  endpoint нет (проверено `git diff`: файла нет в diff).

Tests/artifacts:
- **`tests/test_agentic_events_round1026.py` (NEW, 52 теста)** — схема/enum,
  эмиссия по каждой точке, R17-негативы, fail-open, kill-switch OFF-паритет,
  9 этапов + kind-маппинг, no-fake-tokens, silent-no-verbalizer,
  ANTI_CLICHE_* (лог/без графа), API-поверхность/fail-open/статические границы,
  image/tool_loop/direct-chat точки эмиссии (spy).
- **`tests/test_smartmodule_utils.py` (+2 аддитивных, класс `TestReactMoaiL1A9`)**
  — `TelegramForbiddenError` → `forbidden` (1 вызов, 0 текста) и generic →
  `unknown` (не сломан).
- **`tests/js/round1026_s8_execution_graph_test.js` (+1 секция 8)** — A9-маппинг
  9 этапов + display-only passthrough `fromExecution` (реальные токены
  `text_generation`, `null` у algorithmic).
- **Санкционированные реконсиляции boundary/pin-тестов (только списки/ассерты
  границ, не функциональность):**
  - `tests/test_tool_coordinator_round1026.py` (A1) — `execution_graph_source.py`
    и `web/static/execution_graph.js` исключены из forbidden-web с NOTE A9
    (ADR-1026-22 D1/D7/D10).
  - `tests/test_unified_image_request_round1026.py` (A3) — то же forbidden-список
    + web-allowlist с NOTE A9.
  - `tests/test_telegram_reactions_round1026.py` (A8) —
    `test_no_a9_events` → `test_a9_events_scope_reconciled`: A9-события теперь
    санкционированно есть в `direct_chat_service`; `smartmodule_utils` по-прежнему
    без A9-событий.
- `plans/features/agentic-events-graph-round1026/evidence.md` (NEW, этот файл) +
  `tasks.md` T-3691…T-3701 → `[x]` (T-3702…T-3705 оставлены `[ ]`).

## T-3691…T-3701 — status

- [x] **T-3691 схема событий + payload-whitelist + R17** — `services/agentic_events.py`:
  20-типовой enum (12 §49 + 8 `ANTI_CLICHE_*`), `schema_version="1"`, `EVENT_FIELDS`,
  `filter_event_fields` (drop-unknown-key + строгая value-валидация). `MESSAGE_IGNORED`
  из silent-short-circuit A7 (D6). `CoordinatorDecision`/`ToolLoopResult` не дублированы.
- [x] **T-3692 emission wrapper** — синхронный fail-open `emit_agentic_event`
  (kill-switch → whitelist → structured-log → `record_agentic_event`); не бросает;
  без `await`/`create_task`/блокирующего I/O; 3-го LLM-вызова нет. Доказано
  `test_emit_never_raises_on_store_failure` + `iscoroutinefunction`-проверкой.
- [x] **T-3693 graph kind / 9 этапов** — `KIND_TOOL` + 9 stage-констант/порядок/подписи;
  `_build_agentic_nodes` (tool→stage по имени), `record_agentic_event`, `build_graph`.
  `ANTI_CLICHE_*` — только единый лог (без графа, U5/D11).
- [x] **T-3694 честные метрики** — algorithmic/tool-узлы `inputTokens=outputTokens=cost=None`,
  `priceKnown=false` (`null` ≠ `$0`); `text_generation` — только реальные токены
  `llm_usage_events`; silent → узел Decision без Text Generation/Вербализатора.
- [x] **T-3695 API-поверхность** — аддитивно через существующий
  `GET /analytics/execution/latest` (`web/api/analytics.py` не менялся); RBAC
  `requires_global_admin()` и fail-open shape сохранены; нового endpoint нет.
- [x] **T-3696 Mini App display slice** — `web/static/execution_graph.js`
  (`STEP_KIND`/`STEP_LABEL` +9); вкладка «Аналитика»/`fromExecution` существующие;
  панель/вкладка/параметры не создавались; JS-тест секция 8.
- [x] **T-3697 L-1 forbidden-классификация** — `smartmodule_utils.react_moai`:
  `except TelegramForbiddenError` → `REACTION_FORBIDDEN` (1 вызов, 0 текста,
  тот же warning). Runtime-verified: aiogram 3.31.0 `TelegramForbiddenError`
  **не** подкласс `TelegramBadRequest` (MRO: `TelegramForbiddenError → TelegramAPIError → …`).
- [x] **T-3698 тесты ядра** — `tests/test_agentic_events_round1026.py` (52) +
  L-1-кейсы: 12 событий, поля, R17-негативы, no-fake-tokens, silent-no-verbalizer,
  9 этапов, §53-диагностика (tool + status/error_code + причина).
- [x] **T-3699 off-parity + регресс + adversarial** — OFF → 0 событий/узлов/логов;
  отсутствующий/битый payload, `message_id=None`, неизвестный event, fail-open,
  конкурентная/большая эмиссия (bounded 64), отсутствие R17-утечки, L-1.
- [x] **T-3700 kill-switch + числа** — env-only `AGENTIC_EVENTS_ENABLED` (default ON,
  per-call); OFF-паритет; полный pytest 9513/0; JS 47/47; канон 12; Δ DDL=0
  (SQLite v12, `test_database` 98 passed); Δ каталога=0 (473/430/448/102/100/21);
  APP_VERSION 2.58.30; `git diff --check`=0.
- [x] **T-3701 diff-аудит границ** — см. раздел «Boundary audit» ниже.

## Verification commands + actual results

- **Full pytest:** `.venv\Scripts\python.exe -m pytest -q` →
  **9513 passed / 0 failed** (153.0s).
  Baseline Step 0 = **9459/0**; **+54** = 52 (`test_agentic_events_round1026.py`)
  + 2 (`test_smartmodule_utils.py`, L-1). **0 регрессий.**
- **A9 core:** `pytest -q tests/test_agentic_events_round1026.py` → **52 collected/passed**.
- **L-1:** `pytest -q tests/test_smartmodule_utils.py` → **passed** (включая
  `TestReactMoaiL1A9::test_forbidden_classified_and_no_text`,
  `test_generic_exception_still_unknown`).
- **Affected suites:** direct_chat / decision_making / image_generation /
  image_context_memory / tool_calling / tool_coordinator / agentic_ai /
  anticliche_semantics / webapp_api / webapp_parity → **706 passed** (см. итерацию;
  после реконсиляции A1/A3/A8 boundary-тестов полный прогон зелёный).
- **DDL:** `pytest -q tests/test_database.py` → **98 passed** → SQLite `user_version == 12`,
  Δ DDL = 0. Grep по A9-источникам: `CREATE TABLE/ALTER TABLE/CREATE INDEX/DROP TABLE` = 0.
- **F8:** `.venv\Scripts\python.exe tools\gen_param_registry_round1025.py --check` →
  **`CHECK OK: реестр 473 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.`**
- **Каталог (direct recompute):** REGISTRY **473** · Settings fields **430** ·
  categorized **448** · GROUPS **102** · `_TAB_BY_GROUP` **100** · TAB_RULES **21** → Δ=0.
  `AGENTIC_EVENTS_ENABLED` **не** в `param_catalog.REGISTRY` (env-only).
- **JS:** 47 файлов `tests/js/*.js` → **47/47 exit 0** (`$LASTEXITCODE`); новый
  A9-блок в `round1026_s8_execution_graph_test.js` → `S8-EXECGRAPH-OK`.
- **`git diff --check`:** exit **0** (только LF→CRLF warnings).
- **APP_VERSION:** **2.58.30**; **канон** `TOOL_CALLING_TOOLS` → **12**.
- **aiogram:** **3.31.0**; `issubclass(TelegramForbiddenError, TelegramBadRequest) == False`.

### Reproduced key scenarios (exact)

- 12 §49-событий эмитятся с обязательными полями (`run_id`/`chat_id`/`message_id`/
  `action`/`reason`/`duration_ms`/`ts`/`schema_version="1"`); параметризовано по всем 12.
- R17-негатив: `emit_agentic_event("DECISION_COMPLETE", action="Досье: Иван Петров…",
  reason="hello world", prompt=…, message_text=…)` → ни секрет, ни ключи
  `prompt`/`message_text`/`action`/`reason` не в логе и не в store.
- No-fake-tokens: 9-узловой граф → у всех кроме `text_generation`
  `inputTokens/outputTokens/cost = None`, `priceKnown = False`; `text_generation`
  несёт реальные 10/5/0.001 (price_known=True), при `price_known=False` → `cost=None`
  (`null` ≠ `$0`).
- Silent-no-verbalizer: `DECISION_COMPLETE action=silent` + `MESSAGE_IGNORED` →
  узлы `["decision"]`, `text_generation` отсутствует; `metrics.action == "silent"`.
- 9 этапов: события decision/memory_lookup/rag/web_extraction/factcheck/
  image_prompt/image_generation/reaction + реальная LLM-строка → ровно 9 узлов
  в `AGENTIC_STAGE_ORDER` (`algorithm/tool/tool/tool/tool/algorithm/tool/tool/llm`),
  8 связей; нет данных → нет узла (только `["decision"]`).
- Image-точка: `run_image_request` → `IMAGE_CONTEXT_RESOLVED` + `START` + `COMPLETE`
  (ok) / `FAILED` с `reason_class=timeout` при `GenerationResult(ok=False)`.
- Tool-точка (spy): `TOOL_PLAN_CREATED`/`TOOL_CALL_START`/`TOOL_CALL_COMPLETE`;
  при падении router → `TOOL_CALL_FAILED`.
- Direct-точка (spy, `_drive`): «Ок» → `DECISION_START`/`DECISION_COMPLETE(silent)`/
  `MESSAGE_IGNORED`; «АХАХА» → `REACTION_SENT` (без `MESSAGE_IGNORED`).
- OFF: `AGENTIC_EVENTS_ENABLED=False` → `agentic_events_enabled()==False`, 0 логов,
  0 узлов/store.
- fail-open: `record_agentic_event` бросает → `emit_agentic_event` не бросает,
  лог-emit по-прежнему происходит.
- L-1: `TelegramForbiddenError` → `REACTION_FORBIDDEN`, ровно 1 `set_message_reaction`,
  метод-коллы `["set_message_reaction"]` (0 текста); generic `RuntimeError` → `REACTION_UNKNOWN`.

## 14 acceptance invariants — status

1. **12 типов событий** → **OK** (`AGENTIC_EVENT_TYPES`, тест по каждому из 12).
2. **Обязательные поля операции** → **OK** (types; отсутствующее — не выдумано).
3. **R17 — приватное досье не в логах/событиях** → **OK** (негативные тесты; value-guard).
4. **REUSE ExecutionGraph, без второй аналитики** → **OK** (единый модуль/store/
   endpoint; `web/api/analytics.py` не менялся).
5. **9 реальных этапов** → **OK** (`AGENTIC_STAGE_ORDER`, 9 узлов).
6. **Без выдуманных LLM-токенов** → **OK** (`None` для algorithm/tool).
7. **Silent = Decision без Вербализатора** → **OK**.
8. **§50 display-only** → **OK** (аддитивные STEP_KIND/LABEL; нет панели/параметров).
9. **Без нового инструмента/LLM-вызова** → **OK** (канон 12; нет 3-го вызова;
   `CoordinatorDecision` не дублирован).
10. **L-1 forbidden-классификация** → **OK** (1 вызов, 0 текста, тот же warning).
11. **Whitelist payload** → **OK** (id/числа/enum/имена тулов/`reason_code`).
12. **Kill-switch** → **OK** (env-only, default ON; OFF-паритет).
13. **Δ каталога = 0** → **OK** (473/430/448/102/100/21; `AGENTIC_EVENTS_ENABLED`
    не в REGISTRY).
14. **EPIC_ONLY / Δ DDL = 0** → **OK** (deploy `DEFERRED_TO_EPIC`; SQLite v12; DDL-grep=0).

## R17 / R18

- **R17:** payload — только id/enum/числа/имена инструментов/`reason_code`;
  строка-значение без пробелов (текст/досье/промпт/URL-секрет не проходят);
  `ANTI_CLICHE_*` — без фраз. Негативные тесты: `test_r17_forbidden_content_never_stored_or_logged`,
  `test_worker_phrase_content_not_logged`, `test_whitelist_drops_unknown_keys`.
  Единый существующий logger/adapter/store (второго канала нет).
- **R18:** коммитов/тегов/веток не создавалось; `plans/current_task.md`, машинный
  блок, `workflow_state`, spec/ADR, backlog/metrics/ARCHITECTURE/MEMORY,
  durable-аудит — **не изменялись**; бэкапы/stash целы; baseline-анкер `e8646af` сохранён.

## Boundary audit (T-3701)

- **Вторая аналитика/endpoint** — **нет**: `web/api/analytics.py` отсутствует в
  `git diff` (аддитивность через существующий `build_graph`); новых модулей аналитики нет.
- **Новый инструмент / 3-й LLM-вызов** — **нет**: `TOOL_CALLING_TOOLS == 12`;
  JSON-схемы не менялись; LLM-вызовов в A9-коде нет.
- **Выдуманные LLM-токены** — **не пишутся**: `None`/`null` у algorithm/tool.
- **§50 display-only** — **да**: только `web/static/execution_graph.js`
  (аддитивные STEP_KIND/LABEL); новых панелей/вкладок/параметров/групп нет;
  Δ каталога=0.
- **A8-механика реакции** — не переписана: изменён только `react_moai` (L-1,
  санкция D13); `set_message_reaction`/fallback/7-enum не тронуты.
- **A7-правила §44** — не переопределены: в Phase P добавлены только эмиссии,
  `_decision_pre_action`-политика/классы/приоритеты/`action`/`reason_code` без правок.
- **A1 `CoordinatorDecision`** — не дублирован; **A2–A6** — только точки эмиссии.
- **§104 `generate_image`** — no-go: `generate_and_send` не менялся; A3-AST-гейт
  (`test_unified_image_request_round1026.py`) зелёный.
- **Δ DDL=0** — grep 0; SQLite v12 (`test_database` 98 passed).
- **APP_VERSION 2.58.30; canon 12** — подтверждено.
- **Санкционированные реконсиляции тестов** (A1/A3 forbidden-списки, A8
  `test_no_a9_events`) — правки только списков/ассертов границ с NOTE A9; функциональность
  и число тестов не редуцированы.

## Threat artifact

- **`threat-failure-analysis.md` — `NOT_APPLICABLE`** (Risk **R2**, ADR-1026-22 D1/D12):
  in-memory Δ DDL=0, fail-open, без блокирующего I/O, без второй аналитики,
  без R17-утечки. При подъёме до R3 (PG/DDL, блокирующий hot-path, утечка R17,
  вторая аналитика) — обязателен.

## Blockers / Checks not run

- **Блокеров нет**; все запланированные проверки выполнены.
- Сетевые/провайдерские/LLM-вызовы не выполнялись (unit/integration с fakes).
- A3 owner-gate `PENDING OWNER VERIFICATION` — внешний, A9 его не закрывает.
- `threat-failure-analysis.md` не создавался (N/A при R2/D1) — **осознанно**.
- Реальный деплой не выполнялся и не требуется (**DEFERRED_TO_EPIC**).

## Epic inputs contributed by this feature (release-candidate)

- Code: `services/agentic_events.py` (new), `services/execution_graph_source.py`,
  `services/direct_chat_service.py`, `services/tool_loop.py`,
  `services/image_generation.py`, `services/anticliche_worker.py`,
  `services/smartmodule_utils.py` (L-1), `config/settings.py`,
  `web/static/execution_graph.js`.
- Tests: `tests/test_agentic_events_round1026.py` (new, 52) + 2 L-1 в
  `test_smartmodule_utils.py` + 1 JS-секция; реконсиляции boundary-тестов A1/A3/A8.
- Deploy: **DEFERRED_TO_EPIC**; hot rollback `AGENTIC_EVENTS_ENABLED=false`
  (0 событий/узлов, baseline); cold `git revert` → `e8646af`; DDL-откат не нужен.
- Handoff → A10 (§52–§54 агрегатный gate).

## Manifest hints for Reviewer

- **HEAD:** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`
- **Working tree:** modified (tracked) `config/settings.py`,
  `services/execution_graph_source.py`, `services/direct_chat_service.py`,
  `services/tool_loop.py`, `services/image_generation.py`,
  `services/anticliche_worker.py`, `services/smartmodule_utils.py`,
  `web/static/execution_graph.js`, `tests/test_smartmodule_utils.py`,
  `tests/test_tool_coordinator_round1026.py`,
  `tests/test_unified_image_request_round1026.py`,
  `tests/test_telegram_reactions_round1026.py`,
  `tests/js/round1026_s8_execution_graph_test.js`; untracked (`??`)
  `services/agentic_events.py`, `tests/test_agentic_events_round1026.py`,
  feature-папка.
- **SHA-256 (рабочее дерево):**
  - `services/agentic_events.py` `7e1c6203a408fa2417400fa7c895f123080e67ce28fd9ab0941f5111ee072526`
  - `services/execution_graph_source.py` `31328271d0701c863dc7b88ce6a42b879921604e0dfd99903a39c0600940fccb`
  - `services/direct_chat_service.py` `67e5bde9f2c57fe86e0d50d012fd23db291f3123be6645cffe43cbfa1cf570bb`
  - `services/tool_loop.py` `fa98c68937b0d759ccb13d32e10dfce8dd817526d057b9cd5f4d7cdbe34a1ba6`
  - `services/image_generation.py` `103b11881421d979be64b5e50d329c737b6d5088d8e2806c7d3c34bb26dacfa9`
  - `services/anticliche_worker.py` `8ab8949a1b071c5618d5db6180b94e7f92722b2ef3e54ce205d3b6eddb3be86a`
  - `services/smartmodule_utils.py` `fab999963d2fedba720030589726a9bb14156dd504f320c2d09c59065ccc5a8c`
  - `config/settings.py` `5b71fc6253f8575f580f0d30e0664c3b7c96c08c68be60eece82ec2344158ebe`
  - `web/static/execution_graph.js` `67067a7bd6d017b74fc467ecf95eb477ad20d9ef87bbbc06212838cfd79a80c1`
  - `tests/test_agentic_events_round1026.py` `7856c518f7a145ec8989f6de26468df8c833224231b180b451689c0e6227a179`
  - `tests/test_smartmodule_utils.py` `b4622661232621de508e714f47836fa2ea2b7a41abe447de6fb5c1784b9cdc9e`
  - `tests/test_tool_coordinator_round1026.py` `c5559d93fbe7690a8ca6347a503b93af5db0956b098700d651355f7454b56899`
  - `tests/test_unified_image_request_round1026.py` `ab8e1064a488d27f89d9261f686533268bf9e904b671a0bec34bf25bbcd7684f`
  - `tests/test_telegram_reactions_round1026.py` `5b3b17f22c3fd137de84c8f5150e800dfc11d9805dd842bf0037ff9942c0c317`
  - `tests/js/round1026_s8_execution_graph_test.js` `14babb36ef29424ef2c7da3046466cbaca6935f691dc8606a8da305d21404e4e`
