# A9 `agentic-events-graph-round1026` — спецификация (Step 2 @Architect, T-3689)

- **Epic-ID:** Эпик 3 «Agentic Intelligence», **Wave 5 (продолжение)** (Wave 6 не изобретается; A8 помечена «Wave 5 (продолжение)» — `backlog:296/334`). **Feature-ID:** `agentic-events-graph-round1026`. **Раунд:** 10.26.
- **Тип** (`backlog:311`): **backend/лог + web adapter** — события диагностики решений §49 + интеграция в **существующий** ExecutionGraph §51 + поверхность отображения Mini App §50 (**display-only**). **P1.** **Зависит от:** **A1–A8** ✅. **Включает L-1 follow-up** (review T-3683).
- **ТЗ-источник (IMMUTABLE, `plans/current_task.md`, только чтение — R17/R18):** **§49 «ДИАГНОСТИКА РЕШЕНИЙ»** (`:5634–5681`; содержательные `:5638–5680` — 12 событий, 8 обязательных полей, запрет приватного досье, цель админ-диагностики), **§51 «ИНТЕГРАЦИЯ С КАРТОЙ ВЫЗОВОВ»** (`:5719–5747`; содержательные `:5723–5746` — REUSE ExecutionGraph, 9 реальных этапов, запрет второй аналитики, запрет выдуманных LLM-токенов, silent без фиктивного Вербализатора), **§50 «ИНТЕГРАЦИЯ С MINI APP»** (`:5682–5718`) — **граница отображения** (интерфейс Эпика 1, без отдельной панели, без дублирования параметров). **Приёмочный ориентир:** **§53** «по логам невозможно понять, почему инструмент не сработал» (`:5846–5847`) — failure criterion, который A9 **закрывает**. **§52** (`:5754–5801`) — **A10** (агрегатный gate); **в §52 23 нумерованных сценария, а `backlog:312` указывает «22»** — расхождение зафиксировано для doc-maintenance (PM), не правится в этом шаге.
- **Связанные документы:** `tasks.md` (14 REQ-A9-01…-14 verbatim-traced, 14 инвариантов, блоки 0/A–J, U1–U13, §50-граница, L-1, F0.3); **ADR-1026-22** (`adr-1026-22-*.md`, D1–D14, Status **Proposed → Accepted по merge**, ожидаемый раздел `plans/ARCHITECTURE.md` **§91** — следующий свободный после §90 A8).
- **Зависимости (вход; контракты потребляются, не дублируются):** **A8** ✅ — `react_moai(bot, chat_id, message_id, *, reaction=None, reason_code=None)`, закрытый enum **7 исходов** (`REACTION_OK/UNAVAILABLE/FORBIDDEN/MESSAGE_GONE/SERVICE/RATE_LIMITED/UNKNOWN`), `REACTION_MECHANICS_ENABLED`, один call-site `set_message_reaction` (§90); **L-1** (review T-3683). **A7** ✅ — `CoordinatorDecision.action/target_message_id/reaction/reason_code`, словарь 15 `reason_code`, silent/react short-circuit (§89). **A1** ✅ — `CoordinatorDecision` (не дублировать). **A2** ✅ — `ToolLoopResult`/`tool_trace`/`tool_results`/chain-коды (§84). **A3/A4** ✅ — `ImageRequest`/`run_image_request` + `image_context_memory` resolution-enum (§85/§88). **A6** ✅ — `get_user_context`/`_get_user_context`/`_memory_lookup_finish` (§87). **A5** ✅ — `worker_budget`/лимиты (§86). **F0.3** — `anticliche_worker._event` (`services/anticliche_worker.py:80`, события `ANTI_CLICHE_*`). **ExecutionGraph-ядро:** `services/execution_graph_source.py` (`RunSnapshotStore:109`, `record_run:184`, `build_graph:485`, kind-enum `:38–42`), `web/api/analytics.py` `GET /analytics/execution/latest:281` (RBAC global-admin), `web/static/execution_graph.js` (`KIND_ENUM:48`, `fromExecution:341`), `web/index.html` вкладка «Аналитика» (`:2192+`), `web/app.js` `execGraph:2558`/fetch `:4335`/`execGraphApi:4432`.
- **Baseline (Step 0 @Memory, 25.09.2026; в Step 2 НЕ перемеряется):** HEAD **`e8646af`** + **UNCOMMITTED epic-release рабочее дерево A2–A8** — A9 строится **поверх**; ничего не откатывать/не коммитить. `APP_VERSION` **2.58.30**; канон инструментов **12**; **Δ DDL = 0** (SQLite **v12**); **Δ каталога = 0** (счётчики после A8: `REGISTRY 473` / Settings `430` / categorized `448` / `GROUPS 102` / `_TAB_BY_GROUP 100` / `TAB_RULES 21`). Baseline-анкер **`e8646af`**; hot-откат = env-only `AGENTIC_EVENTS_ENABLED=false`; cold = `git revert`/анкер; теги/бэкапы/`stash` не удаляются (R18).
- **Release policy:** **EPIC_ONLY.** A9 не деплоится после approval; входит в **pending epic-release Эпика 3** (`included in pending epic release`; пер-фича деплоя/тега/bump нет; агрегатный bump **2.58.30 → 2.58.31** — на границе эпика). **@DevOps на пер-фича деплой не вызывается.**
- **Risk-Level: R2** (финальный; обоснование — §13; решение U1/U3 — D1: in-memory, Δ DDL=0). **Статус:** Proposed.

## 1. Область и исключения

**Входит (что делает A9):**
- **Схема событий §49** — закрытый enum **12 типов** + обязательные поля операции (`run_id`/`chat_id`/`message_id`/`action`/выбранные инструменты/причина/длительность/ошибки) + `schema_version` (U1; REQ-A9-01/-02). (§3.1)
- **R17-whitelist payload** — только id/enum/числа/имена инструментов/`reason_code`; никакого приватного содержимого досье, промптов, сырых текстов/ответов LLM, URL с секретами (REQ-A9-03). (§3.2)
- **Тонкая обёртка эмиссии** — fail-open, без блокирующего ввода-вывода на hot-path, без изменения поведения, без 3-го LLM-вызова; kill-switch-гейт (REQ-A9-01/-13; U2). (§3.3)
- **Точки эмиссии** — Phase P decision start/complete; silent→`MESSAGE_IGNORED`; react→`REACTION_SENT`; `tool_loop` на каждый вызов (start/complete/failed/plan); image-пути (`IMAGE_CONTEXT_RESOLVED`/`IMAGE_GENERATION_START/COMPLETE/FAILED`); `MESSAGE_IGNORED`/`REACTION_SENT` из A7-short-circuit. (§3.4)
- **Интеграция в существующий ExecutionGraph §51** — 9 реальных этапов (Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation) через **существующий** adapter (REQ-A9-05/-06/-07). (§3.5)
- **Честные метрики** — алгоритмические узлы честно без LLM-токенов (`null` ≠ `$0`); silent → узел Decision без фиктивного Вербализатора/Text Generation (REQ-A9-08/-09). (§3.6)
- **API-поверхность** — аддитивное расширение **существующего** `GET /analytics/execution/latest` (RBAC global-admin, fail-open shape); новых endpoint нет (REQ-A9-04/-05/-07; U9). (§3.7)
- **Mini App §50 — display-only** — срез отображения новых событий/узлов в **существующей** вкладке «Аналитика» Эпика 1; без отдельной панели и без дублирования параметров (REQ-A9-10/-11; U10). (§3.8)
- **Включение `ANTI_CLICHE_*` (F0.3)** — события воркера в единый event-enum/whitelist/kill-switch (без второй системы логирования), **без** принудительного маппинга в чат-граф (REQ-A9-14; U5). (§3.9)
- **L-1 follow-up** — `TelegramForbiddenError` (HTTP 403) → `REACTION_FORBIDDEN` (тот же R17-safe `_warn_reaction_failed`, 1 вызов, 0 текста; REQ-A9-12). (§3.10)
- **Kill-switch** `AGENTIC_EVENTS_ENABLED` (env-only, default ON; OFF → события не пишутся, поведение неизменно). (§8)

**Не входит (границы, категорически):**
- **A8-механика реакции** (§41) — **не переписывается** (A9 только **события** `REACTION_SENT`/`MESSAGE_IGNORED` и L-1-классификация); `set_message_reaction`/fallback/enum 7 исходов/`reaction`-карта — вне diff.
- **A7-правила §44** (`:5480–5498`) — **не переопределяются** (`_decision_pre_action`/классы/приоритеты/`action`/`reason_code`-семантика — не меняются).
- **A10** (§52–§54) — агрегатный acceptance-gate; вне A9 (кроме §53 `:5846–5847` как приёмочного ориентира).
- **A1** `CoordinatorDecision` — **не дублировать** (reuse полей как есть).
- **A2/A3/A4/A5/A6** — не переписываются; `tool_loop`/envelope/`ImageRequest`/`image_context_memory`/`get_user_context` — вне функционального diff (только точки эмиссии).
- **Вторая система аналитики** (`§51 :5738–5739`) — запрещена: новых модулей аналитики/endpoint’ов/сборщиков нет; всё идёт в **существующий** ExecutionGraph.
- **Выдуманные LLM-токены** для алгоритмических операций (`§51 :5741–5742`) — запрещены.
- **Новый инструмент / 3-й LLM-вызов** — канон **12** без изменений; JSON-схемы инструментов не трогаются.
- **Новый каталог/группы/вкладки/DDL/PG-таблица событий** — запрещены (Δ каталога = 0; Δ DDL = 0 — D1).
- **§104 `generate_image`** — no-go (генерация не переписывается; A9 только эмитит события вокруг существующего `run_image_request`/`generate_and_send`).
- **Правки** `plans/current_task.md` (immutable, R17/R18)/машинного блока/`tasks.md`/`backlog`/`metrics`/`ARCHITECTURE`/`MEMORY`/durable-аудита — не в этом шаге. **@Scanner отсутствует** (единый Reviewer gate). **@DevOps не вызывается.**

## 2. Трассируемость REQ → SC

> Каждый REQ-A9-01…-14 привязан к ≥1 SC; каждый SC восходит к ≥1 REQ. **Orphan-REQ и orphan-SC нет (14 REQ → 16 SC: 14 специфичных + 2 кросс-скоупных).** Колонки SC/ADR в `tasks.md` заполняются @PM на сверке T-3690; формулировки — здесь. Полная детализация — §3/§6/§7/§9.

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC | ADR |
|---|---|---|---|---|---|
| REQ-A9-01 | §49 — 12 событий: `DECISION_START`/`DECISION_COMPLETE`/`TOOL_PLAN_CREATED`/`TOOL_CALL_START`/`TOOL_CALL_COMPLETE`/`TOOL_CALL_FAILED`/`REACTION_SENT`/`MESSAGE_IGNORED`/`IMAGE_CONTEXT_RESOLVED`/`IMAGE_GENERATION_START`/`IMAGE_GENERATION_COMPLETE`/`IMAGE_GENERATION_FAILED` (`:5638–5662`) | B | T-3691, T-3698 | SC-A9-01 | D2, D5, D11 |
| REQ-A9-02 | §49 — «Для каждой операции фиксировать: run_id / chat_id / message_id / action / Выбранные инструменты / Причину решения / Длительность / Ошибки.» (`:5664–5673`) | B | T-3691, T-3698 | SC-A9-02 | D4, D5 |
| REQ-A9-03 | §49 — «Не выводить приватное содержимое досье в публичные логи.» (`:5675–5676`) | B, G | T-3691, T-3698 | SC-A9-03 | D5 |
| REQ-A9-04 | §49 — «В административной диагностике показывать достаточно информации, чтобы понять, почему бот промолчал или вызвал инструмент.» (`:5678–5680`) | B, D, E | T-3691, T-3695, T-3696 | SC-A9-04 | D5, D9, D10 |
| REQ-A9-05 | §51 — «Использовать расширяемую ExecutionGraph из Эпика 1.» (`:5723–5724`) | C, D | T-3693, T-3695 | SC-A9-05 | D7, D9 |
| REQ-A9-06 | §51 — 9 реальных этапов: Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation (`:5726–5736`) | C | T-3693, T-3698 | SC-A9-06 | D7 |
| REQ-A9-07 | §51 — «Не создавать вторую независимую систему аналитики инструментов.» (`:5738–5739`) | C, D, H | T-3693, T-3695, T-3701 | SC-A9-07 | D7, D9 |
| REQ-A9-08 | §51 — «Не записывать выдуманные LLM-токены для обычных алгоритмических операций.» (`:5741–5742`) | C | T-3694, T-3698 | SC-A9-08 | D8 |
| REQ-A9-09 | §51 — «Если действие завершилось молчанием, показывать результат решения без фиктивного вызова Вербализатора.» (`:5744–5746`) | C | T-3694, T-3698 | SC-A9-09 | D6, D8 |
| REQ-A9-10 | §50-граница — «Все новые возможности должны использовать интерфейс, созданный в Эпике 1. Не создавать отдельную административную панель.» (`:5686–5689`) | E, H | T-3696, T-3701 | SC-A9-10 | D10 |
| REQ-A9-11 | §50-граница — «Не дублировать один параметр в нескольких независимых формах.» (`:5716–5717`) | E, H | T-3696, T-3701 | SC-A9-11 | D10 |
| REQ-A9-12 | L-1 follow-up (review T-3683, A8) — `TelegramForbiddenError` (HTTP 403) → `REACTION_FORBIDDEN`, не `unknown`; поведение безопасности идентично | F | T-3697 | SC-A9-12 | D13 |
| REQ-A9-13 | §53 — «по логам невозможно понять, почему инструмент не сработал» (`:5846–5847`) — failure criterion, закрываемый A9 | B, G | T-3691, T-3698, T-3699 | SC-A9-13 | D5, D6 |
| REQ-A9-14 | F0.3 `ANTI_CLICHE_*` события (`backlog:311`; `anticliche_worker._event` существует `services/anticliche_worker.py:80`) — включить в объём A9 (U5) | B, C | T-3691, T-3693 | SC-A9-14 | D11 |

**Кросс-скоуповые примечания:** §50 — **граница отображения** (настройки уже поставлены A4/A5/A7/A8; A9 их **не дублирует**); §41-механика A8 — **вне функционального scope**; §44-правила A7 — вне scope; §52–§54 — **A10** (агрегатный gate), кроме §53 `:5846–5847`; §104 `generate_image` — no-go; `CoordinatorDecision` (A1) — не дублировать. **`SC-A9-15/-16` — кросс-скоупные агрегаторы; orphan-SC нет.**

### 2.1. Определения SC (наблюдаемо/тестируемо)

| SC | Формулировка | Восходит к REQ |
|---|---|---|
| SC-A9-01 | Закрытый enum **12 §49-типов** существует; каждый тип реально эмитится в заданной точке кода; тест наблюдает все 12 с обязательными полями. | REQ-A9-01 |
| SC-A9-02 | Каждое операционное событие несёт обязательные поля операции (`run_id`/`chat_id`/`message_id`/`action`/`tools`/`reason`/`duration_ms`/`errors`) корректных типов; отсутствующее — `None`/`-`, **не** выдумано. | REQ-A9-02 |
| SC-A9-03 | Whitelist payload соблюдён: приватное содержимое досье, промпты, сырые тексты/ответы LLM, URL с секретами **отсутствуют** (негативные тесты); присутствуют только id/enum/числа/имена инструментов/`reason_code`. | REQ-A9-03 |
| SC-A9-04 | Админ-диагностика достаточна: для молчания виден Decision + `reason_code`; для вызова инструмента — plan/call outcome и причина отказа. | REQ-A9-04 |
| SC-A9-05 | События/узлы идут **только** через существующий `ExecutionGraph` (`execution_graph_source.py` + `GET /analytics/execution/latest`); второй модуль/endpoint аналитики не создан. | REQ-A9-05 |
| SC-A9-06 | 9 §51-этапов отображаются узлами графа при наличии данных: Decision/Memory Lookup/RAG/Web Extraction/Factcheck/Image Prompt Preparation/Image Generation/Reaction/Text Generation; нет данных → нет узла. | REQ-A9-06 |
| SC-A9-07 | Нет второй независимой системы аналитики инструментов (структурная проверка: один adapter, один endpoint, один store; AS-дубликаты отсутствуют). | REQ-A9-07 |
| SC-A9-08 | Алгоритмические узлы несут честные `inputTokens/outputTokens/cost = None` (`null` ≠ `$0`); токены только у реальных LLM-строк `llm_usage_events`. | REQ-A9-08 |
| SC-A9-09 | При silent в графе присутствует узел **Decision** и **отсутствует** узел Text Generation/фиктивный Вербализатор; результат решения показан. | REQ-A9-09 |
| SC-A9-10 | Отображение использует интерфейс Эпика 1 (существующая вкладка «Аналитика»/карта вызовов); отдельной админ-панели нет. | REQ-A9-10 |
| SC-A9-11 | Параметры не дублируются: Δ каталога = 0; новых параметров/групп/вкладок нет. | REQ-A9-11 |
| SC-A9-12 | `TelegramForbiddenError` → `REACTION_FORBIDDEN`; unit-тест: 1 вызов `set_message_reaction`, 0 текста, тот же R17-safe warning (поведение безопасности идентично). | REQ-A9-12 |
| SC-A9-13 | §53 `:5846–5847` закрыт: для отказавшего инструмента события/граф объясняют, **почему** он не сработал (tool + status/error_code + причина решения). | REQ-A9-13 |
| SC-A9-14 | `ANTI_CLICHE_*` включены в единый event-enum/whitelist/kill-switch (без второго логгера), без принудительного маппинга в чат-граф. | REQ-A9-14 |
| SC-A9-15 | **Кросс-скоуп:** kill-switch OFF → события не пишутся, поведение/логи байт-в-байт baseline; ошибка эмиссии fail-open (основной поток продолжается); полный регресс зелёный. | REQ-A9-02, REQ-A9-03, REQ-A9-13 |
| SC-A9-16 | **Кросс-скоуп:** границы соблюдены — канон **12**; нет 3-го LLM-вызова; Δ DDL=0; Δ каталога=0; §104 no-go; EPIC_ONLY; R17; A8-механика/A7-правила не переписаны; `CoordinatorDecision` не дублирован; вторая аналитика не создана. | REQ-A9-05, REQ-A9-07, REQ-A9-08, REQ-A9-10, REQ-A9-11 |

## 3. Наблюдаемое поведение и отказные сценарии

### 3.1. Схема событий §49 (REQ-A9-01/-02; блок B; U1)
- **Закрытый enum `AGENTIC_EVENT_TYPES`** = **12 §49-типов** (D5) + **8 `ANTI_CLICHE_*`** (D11) = **20**; событие вне enum не эмитится. `schema_version = "1"`.
- **Общие поля** (R17-safe): `schema_version`, `event`, `run_id`, `chat_id`, `message_id`, `action`, `tools` (имена), `reason`, `duration_ms`, `errors` (коды), `ts`. Обязательность per-event — по таблице D5.
- **Дополнительные допустимые поля per-event** (закрытый whitelist, D5): `outcome` (A8 7-enum), `stage`, `tool`, `round`, `status`, `error_code`, `counts`, `source` (`direct`/`tool`), `resolution` (image resolution-enum), `reason_class` (image), `latency_ms`, `chars`/`prompt_chars` (**числа**, не текст), `mode`. Поля вне whitelist отбрасываются (`record_run`-прецедент игнорирования неизвестных ключей).
- **Нет данных → `None`/`-`**, не выдуманное значение (прецедент S8/S6 honest-`None`).

### 3.2. R17-whitelist payload (REQ-A9-03/-04/-13; U1/U6-handoff)
- **Разрешено:** id (`run_id`/`chat_id`/`message_id`), enum (`event`/`action`/`reason`/`outcome`/`resolution`/`status`), числа (`duration_ms`/`latency_ms`/счётчики/длины), имена инструментов, R17-safe коды.
- **Запрещено:** текст сообщений, содержимое досье/фактов/имён, промпты, сырые ответы/размышления LLM, URL с секретами, ключи. Негативные тесты фиксируют отсутствие подстрок приватного контента.
- События используют **существующий** structured-logger (формат `event=<TYPE> | k=v`, прецедент F0.3 `_event`) → persistence журнала как у logs (journald); отдельный лог-канал/файл не создаётся.

### 3.3. Транспорт эмиссии — обёртка (REQ-A9-01/-13; U2; D2)
- **`emit_agentic_event(event, **fields)`** — тонкая **синхронная** функция (не `async`), безопасная для вызова из async-кода: не создаёт task/await, не делает блокирующего ввода-вывода, **никогда не бросает** (`try/except` внутри), резолвит kill-switch per-call. «Fire-and-forget» = вызов без использования результата.
- **Порядок:** (1) kill-switch OFF → `return` без эффекта; (2) валидация/фильтрация полей по whitelist; (3) structured-log строкой; (4) аддитивная запись в существующий in-memory store (для графа).
- **Инвариант:** ошибка/исключение эмиссии **не влияет** на основной поток (доказано тестом fail-open). Поведение чата не меняется; 3-го LLM-вызова нет.

### 3.4. Точки эмиссии (REQ-A9-01/-02/-09/-13/-14; блок B; D5/D6/D11)

| Событие | Точка (verified baseline) | Ключевые поля |
|---|---|---|
| `DECISION_START` | `direct_chat_service` Phase P entry (`:1286–1293`) | run_id/chat_id/message_id |
| `DECISION_COMPLETE` | после `_decision_pre_action` (`:1296–1302`) и на reply-пути после `build_coordinator_decision` | action/reason/duration_ms/tools |
| `TOOL_PLAN_CREATED` | где определены `tool_names`/запрошены инструменты (`tool_loop` при первом `tool_calls` `:323–337`) | tools |
| `TOOL_CALL_START` | `tool_loop` перед `router.dispatch` (`:419–422`) | tool/round |
| `TOOL_CALL_COMPLETE` | `tool_loop` после успешного dispatch (`:434–442`) | tool/round/status=ok/out_chars |
| `TOOL_CALL_FAILED` | `tool_loop` invalid-args (`:342–369`), dispatch-exception (`:423–427`), chain-skip (`:403–417`) | tool/round/error_code/status |
| `REACTION_SENT` | `direct_chat_service` A7 react-ветка после `react_moai` (`:1308–1316`) | outcome (7-enum)/reason/reaction |
| `MESSAGE_IGNORED` | `direct_chat_service` A7 silent-ветка перед `return` (`:1303–1307`) | action=silent/reason/target |
| `IMAGE_CONTEXT_RESOLVED` | `image_context_memory.log_image_context_build` (`:846`) / его call-site | resolution/sources/facts/slice/prompt_chars/latency |
| `IMAGE_GENERATION_START` | вокруг `run_image_request`/`generate_and_send` (`image_generation.py:395`) | source/prompt_chars |
| `IMAGE_GENERATION_COMPLETE` | после `GenerationResult.ok=True` | source/duration_ms |
| `IMAGE_GENERATION_FAILED` | после `GenerationResult.ok=False` | source/reason_class |
| `ANTI_CLICHE_*` (8) | `anticliche_worker._event` (`:80`) — маршрутизация в общую обёртку | существующие R17-safe поля воркера |

- `run_id` = `correlation_id` (D4): доступен в direct-чате (`:1174`), в `ToolContext` (`:2038`), в image-путях (проброс `correlation_id`). Новый идентификатор не вводится.
- **Не покрытые сайты:** прочие `react_moai`-вызовы (без A7-контекста) — `REACTION_SENT` **вне scope** (genuine unknown; не расширяем blast radius); миграция не требуется.
- **`ANTI_CLICHE_*`** не форсируются в чат-граф (воркер-scope: нет `chat_id`/`message_id`), только унифицированное R17-safe событие (D11).

### 3.5. 9 этапов → `kind` (REQ-A9-05/-06/-07; U4/U11; D7)
- Расширение **существующего** `execution_graph_source.py` (аддитивные `stageKey`/`STAGE_LABELS`/`AGENTIC_STAGE_ORDER` + узлы); `build_graph` дополняется агентными узлами при их наличии; сводный (Эпик 2) граф без агентных данных — байт-в-байт прежний.
- **`KIND_TOOL = "tool"`** добавляется в Python-константы (JS `KIND_ENUM:48` уже содержит `tool`); новых kind-ов не вводится.

| §51-этап | `stageKey` | `kind` | Токены/стоимость |
|---|---|---|---|
| Decision | `decision` | `algorithm` | `None` (никогда LLM) |
| Memory Lookup | `memory_lookup` | `tool` | `None` |
| RAG | `rag` | `tool` | `None` |
| Web Extraction | `web_extraction` | `tool` | `None` |
| Factcheck | `factcheck` | `tool` | `None` |
| Image Prompt Preparation | `image_prompt` | `algorithm` | `None` |
| Image Generation | `image_generation` | `tool` | `None` |
| Reaction | `reaction` | `tool` | `None` |
| Text Generation | `text_generation` | `llm` | только реальные из `llm_usage_events` |

- **Нет данных этапа → нет узла** (прецедент §24/§25/S8). Связи — `_link_sequence` по каноническому `AGENTIC_STAGE_ORDER`; ветвление не достраивается.

### 3.6. Честные метрики (REQ-A9-08/-09; U11/U12; D8)
- **No-fake-tokens:** узлы `algorithm`/`tool` (все агентные, кроме Text Generation) — `inputTokens=outputTokens=cost=None`, `priceKnown=false`; `null` ≠ `$0`. Токены появляются только из реальных LLM-строк.
- **Silent-no-verbalizer:** на silent граф содержит узел Decision (с `reason_code`); узел Text Generation/Вербализатор **не создаётся**; `MESSAGE_IGNORED` зафиксирован. Тест проверяет отсутствие фиктивного узла.

### 3.7. API-поверхность (REQ-A9-04/-05/-07; U9; D9)
- **Решение:** аддитивно расширить **существующий** `GET /analytics/execution/latest` (`web/api/analytics.py:281`); новый endpoint (`/analytics/agentic/latest`) **не создаётся** (иначе — вторая поверхность/двойная аналитика).
- Агентные узлы идут в тот же `nodes[]` существующего shape; RBAC — существующий `requires_global_admin()`; fail-open shape — существующий `_execution_response` (PG down/телеметрия OFF → shape-совместимый пустой граф, без ошибок UI). Новых обязательных полей контракта нет.

### 3.8. Mini App §50 — display-only (REQ-A9-10/-11; U10; D10)
- Новые `stageKey` рендерятся **существующим** `execution_graph.js` через аддитивные записи в `STEP_KIND`/`STEP_LABEL`; отдельный компонент/панель/вкладка **не создаётся**; `fromExecution` уже принимает узлы/`metrics`/`publicationStatus`.
- Настройки §50 **уже поставлены** A4/A5/A7/A8 — A9 их **не дублирует** (`:5716–5717`); новых параметров/групп/вкладок нет (Δ каталога = 0).

### 3.9. `ANTI_CLICHE_*` (REQ-A9-14; U5; D11)
- **Решение:** включить 8 существующих событий F0.3 в единый event-enum/whitelist/kill-switch; `_event` маршрутизируется через `emit_agentic_event` (второй логгер не создаётся). **В чат-граф не форсируются** (нет `run_id`/`chat_id`/`message_id`) — сохраняют воркер-семантику.
- Точные имена (verified): `ANTI_CLICHE_UPDATE_START/MODEL_REQUEST/MODEL_RESPONSE/PARSE_ERROR/DEDUP_COMPLETE/SAVE_COMPLETE/UPDATE_COMPLETE/UPDATE_FAILED`.

### 3.10. L-1: forbidden-классификация (REQ-A9-12; блок F; D13)
- `services/smartmodule_utils.py`: импортировать `TelegramForbiddenError` из `aiogram.exceptions` (`:22`); добавить `except TelegramForbiddenError: return REACTION_FORBIDDEN` **перед** generic `except Exception` (`:227`) — с тем же `_warn_reaction_failed`. `TelegramForbiddenError` **не** подкласс `TelegramBadRequest`, поэтому сегодня 403 попадает в generic → `REACTION_UNKNOWN`.
- **Поведение безопасности не меняется** (тихий отказ, без fallback/текста/повтора) — меняется только классификация. Unit-тест: `TelegramForbiddenError` → `forbidden`, 1 вызов, 0 текста.

### 3.11. Отказные/негативные сценарии (что считается НЕ выполнением)
- Вторая аналитика / второй endpoint / второй event-store → не принято (§51).
- Выдуманные LLM-токены у алгоритмических узлов (`$0`/числа) → не принято (§51).
- Silent c фиктивным узлом Вербализатора/Text Generation → не принято (§51).
- Приватное содержимое досье/промпты/сырые тексты в payload/логах → не принято (R17; §49).
- Новый инструмент / 3-й LLM-вызов / Δ каталога≠0 / Δ DDL≠0 → не принято.
- Отдельная админ-панель / дублирование параметров → не принято (§50).
- Переопределение A8-механики/A7-правил/дублирование `CoordinatorDecision` (A1) → не принято.
- Ошибка эмиссии, ломающая основной поток → не принято (fail-open).
- Регресс существующего графа/аналитики или OFF-паритета → не принято.
- §104 `generate_image` в diff → не принято.

## 4. Решения по открытым вопросам U1–U13 (полные формулировки — ADR-1026-22)

> **Канонические U-IDs — из `tasks.md` (`:151–169`).** Ниже — решения; в §4.1 — покрытие тем Step-2 handoff (Orchestrator), чтобы ни один вопрос не был потерян при сверке T-3690.

| U (tasks.md) | Вопрос | Решение A9 | ADR |
|---|---|---|---|
| **U1** | Персистентность событий: in-memory (S8) vs PG-таблица | **In-memory расширение `RunSnapshotStore`**; Δ DDL=0; рестарт-потери графа приемлемы (журнал — в logs/journald); **финализирует R2** | D1 |
| **U2** | Транспорт эмиссии | **Тонкая fail-open обёртка** над существующим structured-logger + in-memory store; новый event-store **не создаётся** | D2 |
| **U3** | Нужна ли PG-таблица | **Нет** (следствие D1); DDL-санкция не запрашивается; R3/threat-артефакт не требуются | D1 |
| **U4** | Kill-switch: имя/скоуп | **`AGENTIC_EVENTS_ENABLED`** env-only, default ON; OFF → события не пишутся, поведение неизменно; Δ каталога=0 | D3 |
| **U5** | Включение `ANTI_CLICHE_*` | **Включить** в enum/whitelist/kill-switch; в чат-граф не форсировать | D11 |
| **U6** | Источник `run_id` | **Reuse `correlation_id` (S7)**; новый идентификатор не вводится | D4 |
| **U7** | Маппинг `MESSAGE_IGNORED` из silent-short-circuit A7 | Эмиссия в silent-ветке Phase P; silent → узел Decision без фиктивного Вербализатора | D6 |
| **U8** | Схема payload + whitelist; R17 | Закрытый enum + обязательные поля + whitelist id/enum/числа/инструменты/`reason_code`; негативные тесты | D5 |
| **U9** | API-поверхность | **Аддитивное расширение** `GET /analytics/execution/latest`; новый endpoint нет | D9 |
| **U10** | Mini App §50-срез | **Display-only** в существующей вкладке «Аналитика»; reuse Эпика 1; без параметров | D10 |
| **U11** | Маппинг 9 этапов → `kind` | Таблица §3.5; существующие kind-ы (+ `tool`); `algorithm`/`tool` без токенов; Text Generation=`llm` | D7 |
| **U12** | No-fake-tokens | Правило honest-`None`; `algorithm`/`tool` без LLM-токенов; тест | D8 |
| **U13** | Границы/риск/EPIC_ONLY/откат + pacing | R2; EPIC_ONLY/`DEFERRED_TO_EPIC`; hot=env-OFF; cold=revert; A9 **предшествует** A10 по зависимости (P1 vs P0 — не гейт) | D12 |

### 4.1. Покрытие тем Step-2 handoff (Orchestrator) → канонические U/D

| Тема handoff | Канонический U (tasks.md) | ADR |
|---|---|---|
| U1 event schema | U8 (payload/whitelist) + U1 | D5 (+D1) |
| U2 emission | U2 | D2 |
| U3 storage (DECIDES RISK) | U1 + U3 | D1 |
| U4 graph integration | U11 | D7 |
| U5 API surface | U9 | D9 |
| U6 R17 | U8 | D5 |
| U7 §50 scope | U10 | D10 |
| U8 kill-switch | U4 | D3 |
| U9 first-cut scope | U5 | D11 |
| U10 L-1 | (REQ-A9-12; отдельный U-нет) | D13 |
| U11 silence semantics | U7 + U12 | D6 (+D8) |
| U12 no fake tokens | U12 | D8 |
| U13 pacing | U13 | D12 |

## 5. Приёмочные инварианты A9 (14) → SC

> Нарушение = НЕ принято. Все 14 из `tasks.md` сохранены без потерь; привязка — к SC из §2.

1. **12 типов событий присутствуют.** *(REQ-A9-01; SC-A9-01)*
2. **Обязательные поля на операцию** (`run_id`/`chat_id`/`message_id`/`action`/инструменты/причина/длительность/ошибки). *(REQ-A9-02; SC-A9-02)*
3. **R17 — приватное досье не в логах/событиях.** *(REQ-A9-03; SC-A9-03)*
4. **REUSE ExecutionGraph, без второй аналитики.** *(REQ-A9-05/-07; SC-A9-05/-07)*
5. **9 реальных этапов.** *(REQ-A9-06; SC-A9-06)*
6. **Без выдуманных LLM-токенов** для алгоритмических операций (`null` ≠ `$0`). *(REQ-A9-08; SC-A9-08)*
7. **Silent = узел Decision без фиктивного Вербализатора.** *(REQ-A9-09; SC-A9-09)*
8. **§50 display-only:** интерфейс Эпика 1; без отдельной панели; без дублирования параметров. *(REQ-A9-10/-11; SC-A9-10/-11)*
9. **Без нового инструмента/LLM-вызова:** канон 12; нет 3-го вызова; JSON-схемы не трогаются; `CoordinatorDecision` не дублируется. *(SC-A9-16)*
10. **L-1 forbidden-классификация:** `TelegramForbiddenError` → `REACTION_FORBIDDEN` (тот же R17-safe warning, 1 вызов, 0 текста). *(REQ-A9-12; SC-A9-12)*
11. **Whitelist payload события** — только id/числа/enum/имена инструментов/`reason_code`. *(REQ-A9-03; SC-A9-03)*
12. **Kill-switch** env-only (`AGENTIC_EVENTS_ENABLED`, default ON; OFF → паритет). *(SC-A9-15)*
13. **Δ каталога = 0** (счётчики `473/430/448/102/100/21`); новых параметров/групп/вкладок нет. *(SC-A9-11, SC-A9-16)*
14. **EPIC_ONLY:** deployment `DEFERRED_TO_EPIC`; **Δ DDL = 0** (in-memory — D1). *(SC-A9-16)*

## 6. Feature contract

**Preconditions:**
- `AGENTIC_EVENTS_ENABLED` ON (env-only, default ON) для новых событий; OFF → обёртка no-op, поведение/логи baseline.
- `correlation_id` доступен в точке эмиссии (direct-чат `:1174`; `ToolContext`; image-пути — проброс).
- Канон `TOOL_CALLING_TOOLS == 12`; JSON-схемы инструментов не меняются; Δ DDL=0.
- Существующий ExecutionGraph (`RunSnapshotStore`/`build_graph`/`GET /analytics/execution/latest`) доступен как дом.

**Invariants:** §5 (14). Дополнительно: ошибка эмиссии не влияет на основной поток; события не содержат приватного контента; агентные узлы алгоритмического класса не несут LLM-токенов.

**Inputs/Outputs:**
- **Вход:** `event` + R17-safe поля (id/enum/числа/инструменты/коды); `run_id`=correlation_id; kill-switch.
- **Выход:** структурированная R17-safe event-строка (существующий logger) + аддитивная запись in-memory снапшота → узлы/связи в существующем `ExecutionGraph` → `GET /analytics/execution/latest` (тот же shape). **Второго канала/системы нет.**
- **Контракты:** `react_moai` (A8) — потребляется как есть (возвращаемый outcome-код); `ToolLoopResult`/`tool_trace`/`tool_results` (A2) — источник tool-событий, не дублируется; `CoordinatorDecision` (A1/A7) — reuse полей; `RunSnapshotStore`/`build_graph` (S8/S6) — аддитивное расширение.

**Failure semantics (fail-safe):**
- Любая ошибка эмиссии/валидации полей → `return` без эффекта (fail-open); основной поток продолжается.
- Kill-switch OFF → 0 событий, паритет baseline.
- Нет данных этапа → нет узла (не выдумываем).
- `message_id=None`/отсутствующий `run_id` → событие не эмитится (или поле `None`) — без падения.
- Неизвестный `event` → не эмитится (закрытый enum).

**Compatibility:** существующий сводный/граф-поток без агентных данных — байт-в-байт; API-ответ аддитивен; OFF-паритет; `react_moai`-сайты без A7-контекста не меняют поведение; L-1 меняет только enum-значение (unknown→forbidden), не поведение.

**Observability (R17):** только id/enum/числа/имена инструментов/`reason_code`; без текстов/имён/ключей/промптов/сырых ответов. Один logger, один adapter, один store.

**Acceptance evidence:** тесты §9 (`tests/test_agentic_events_graph_round1026.py` + аддитивные JS-тесты + L-1 unit-тест в `tests/test_smartmodule_utils.py`); full pytest (baseline → +N/0); JS; diff-аудит границ (Δ DDL=0, Δ каталога=0, канон 12).

**Release-order constraints:** A9 — после A8; **до A10** (A10 зависит A0–A9; `backlog:312`) — зависимость, не гейт. Внутри эпик-релиза A9 reuse (не меняет) контракты A1–A8.

**Rollback boundary:** hot — `AGENTIC_EVENTS_ENABLED=false` (события OFF, поведение baseline); cold — `git revert` к **`e8646af`** + агрегатный анкер Эпика 3; DDL-откат не нужен (Δ DDL=0).

**Ownership верификации:** @Builder (T-3691…T-3701) → **единый @Reviewer gate** (T-3702, Scanner отсутствует) → @Architect merge **§91** + ADR-1026-22 Accepted (T-3703) + @PM архивация → **T-3704 = `DEFERRED_TO_EPIC`** → T-3705 handoff → A10.

**Epic-release contribution:** A9 добавляет в pending epic-release Эпика 3 **диагностические события §49** (12 типов + поля операции + R17-whitelist + fail-open эмиссию + kill-switch) и их **интеграцию в существующий ExecutionGraph §51** (9 реальных этапов, honest-метрики, silent без фиктивного Вербализатора) + **display-only срез §50**; агрегируется в манифест на границе эпика; пер-фича деплоя нет. Закрывает L-1 (REQ-A9-12) и §53-критерий (`:5846–5847`).

## 7. Дизайн / технические решения

### 7.1. Дом и состав (D1/D2/D5/D7)
- **Схема/эмиссия** — `services/agentic_events.py` (новый **тонкий** модуль-утилита; **не** система аналитики): `AGENTIC_EVENT_TYPES` (20), `EVENT_FIELDS`/whitelist, `emit_agentic_event(event, **fields)`, `agentic_events_enabled()`. Модуль — единственная точка эмиссии (единый логгер/формат).
- **Граф** — `services/execution_graph_source.py` (аддитивно): `KIND_TOOL`, `STAGE_DECISION…STAGE_TEXT_GENERATION`, `AGENTIC_STAGE_ORDER`, `STEP_KIND`/`STAGE_LABELS`-дополнения, `record_agentic_event`/агентные node-builders, расширение `build_graph` (агентные узлы при наличии).
- **API** — `web/api/analytics.py` (`/analytics/execution/latest`) — без нового endpoint (узлы проходят через существующий `nodes[]`).
- **UI** — `web/static/execution_graph.js` (`STEP_KIND`/`STEP_LABEL` дополнения) + существующие `fromExecution`/`web/app.js execGraph`; без нового компонента.
- **Точки эмиссии** — `direct_chat_service.py`, `tool_loop.py`, `image_context_memory.py`, `image_generation.py`, `anticliche_worker.py` (аддитивные вызовы обёртки). `smartmodule_utils.py` — L-1-фикс.
- **Почему один тонкий модуль, а не новый store/система:** §51 прямо запрещает вторую аналитику; обёртка + существующий store/adapter = REUSE; второй store/endpoint = дублирование/дрейф.

### 7.2. Псевдокод обёртки
```
def emit_agentic_event(event, **fields) -> None:
    try:
        if not agentic_events_enabled():          # D3 kill-switch
            return
        if event not in AGENTIC_EVENT_TYPES:      # D5 закрытый enum
            return
        safe = {k: v for k, v in fields.items()
                if k in EVENT_FIELDS.get(event, _COMMON_FIELDS)}
        logger.info("event=%s | %s", event, _kv(safe))   # R17-safe
        execution_graph_source.record_agentic_event(event, **safe)  # fail-open
    except Exception:                              # fail-open: поток не рвём
        return
```
- Вызов — синхронный, без `await`/`create_task`; не делает блокирующего ввода-вывода; результат не используется.

### 7.3. Точки кода (ориентиры baseline)
- `services/direct_chat_service.py:1174` (`correlation_id`), `:1286–1316` (Phase P: start/complete/silent/react), `:1303–1307` (`MESSAGE_IGNORED`), `:1308–1316` (`REACTION_SENT` + L-1-consumer).
- `services/tool_loop.py:323–337` (`TOOL_PLAN_CREATED`), `:342–369` (`TOOL_CALL_FAILED` invalid-args), `:403–417` (chain-skip → failed), `:419–442` (`TOOL_CALL_START`/`COMPLETE`), `:276–285` (tool-раунд LLM).
- `services/image_context_memory.py:846` (`IMAGE_CONTEXT_RESOLVED`).
- `services/image_generation.py:395` (`run_image_request` — start/complete/failed вокруг).
- `services/anticliche_worker.py:80` (`_event` → обёртка).
- `services/smartmodule_utils.py:22` (import), `:219–230` (try/except; L-1) .
- `services/execution_graph_source.py:38–42` (kinds), `:59–92` (labels/step), `:109`/`:184`/`:485` (store/record/build).
- `web/api/analytics.py:281` (endpoint), `web/static/execution_graph.js:48/57–74/341` (kind/labels/fromExecution), `web/app.js:2558/4335/4432`, `web/index.html:2192+`.

## 8. DDL / каталог / kill-switch — вердикт

- **Δ DDL = 0 (U1/U3; D1).** Новых таблиц/колонок/индексов/PG-таблицы событий **нет**; SQLite остаётся **v12**; миграций нет. Рестарт-потери in-memory графа **приемлемы** (прецедент S8; диагностика сохраняется в logs/journald; §53-closure не требует DDL — комментарий handoff учтён).
- **Δ каталога = 0 (U4; D3).** Новых параметров/групп/вкладок нет; F8 не переиздаётся. Счётчики без изменений:

| Счётчик | Baseline (после A8) | Целевое | Δ |
|---|---|---|---|
| `REGISTRY` | 473 | 473 | 0 |
| Settings fields | 430 | 430* | 0 |
| categorized | 448 | 448 | 0 |
| `GROUPS` | 102 | 102 | 0 |
| `_TAB_BY_GROUP` | 100 | 100 | 0 |
| `TAB_RULES` | 21 | 21 | 0 |

\* env-only `ClassVar AGENTIC_EVENTS_ENABLED` не является каталог-параметром (прецедент `REACTION_MECHANICS_ENABLED`/`DIRECT_DECISION_MAKING_ENABLED`) и **не** учитывается в Settings-счётчике.

- **Kill-switch** `AGENTIC_EVENTS_ENABLED` — env-only `ClassVar` (`config/settings.py`, рядом с `REACTION_MECHANICS_ENABLED:568`), default **ON**, резолв per-call, никогда не бросает. **OFF →** 0 событий/узлов, поведение и логи baseline (паритет).
- **Обратная совместимость:** существующий сводный граф/аналитика — без функциональных изменений (агентные узлы только при наличии данных); API-ответ аддитивен; `react_moai`-контракт не меняется; миграционный откат не требуется.

## 9. Стратегия тестов

- **Эмиссия по точкам (T-3698):** для каждой из 12 §49-точек — событие наблюдается с обязательными полями (mock/spy logger); `DECISION_START`→`COMPLETE`; `MESSAGE_IGNORED` на silent; `REACTION_SENT` на react; `IMAGE_*` на image-пути; `TOOL_*` на tool-цикле (plan/start/complete/failed).
- **R17-негатив (T-3698/T-3699):** payload не содержит текста сообщений/досье/промптов/сырых ответов/URL-секретов; whitelist отбрасывает лишние ключи.
- **No-fake-tokens (T-3698):** алгоритмические узлы — `inputTokens=outputTokens=cost=None`, `priceKnown=false`; Text Generation несёт токены только при реальной LLM-строке.
- **Silent-no-verbalizer (T-3698):** silent → узел Decision присутствует, Text Generation/Вербализатор отсутствует.
- **9-этапный рендер (T-3698 + JS):** каждый §51-этап при наличии данных → узел с корректным `kind`/label; отсутствие данных → нет узла; сводный граф без агентных данных не изменился.
- **API RBAC + fail-open (T-3699):** не-админ → отказ (существующий RBAC); PG down/телеметрия OFF → shape-совместимый пустой граф без ошибок UI.
- **OFF-паритет (T-3699/T-3700):** `AGENTIC_EVENTS_ENABLED=false` → 0 новых событий/узлов; логи/поведение baseline.
- **Fail-open эмиссии (T-3699):** искусственная ошибка в обёртке → основной поток завершается штатно.
- **Adversarial (T-3699):** отсутствующий/битый payload, конкурентная эмиссия, большие объёмы, `message_id=None`, неизвестный `event`.
- **L-1 (T-3697):** `TelegramForbiddenError` → `forbidden`, 1 вызов, 0 текста; generic `Exception` → `unknown` (не сломан).
- **Регресс/числа (T-3700/T-3701):** полный pytest (baseline → +N/0), JS; канон **12**; **Δ DDL=0**; **Δ каталога=0**; `APP_VERSION` **2.58.30** (без bump); `git diff --check`=0; diff-аудит границ (вторая аналитика/токены/§50-панель/A8-механика/A7-правила/§104 вне diff; `CoordinatorDecision` не дублирован).

## 10. Deploy / rollback (EPIC_ONLY)

- **Deploy = `DEFERRED_TO_EPIC`** (T-3704): пер-фича деплоя/тега/bump нет; вклад в pending epic-release Эпика 3; `APP_VERSION` остаётся **2.58.30** (агрегатный bump 2.58.30 → 2.58.31 — на границе эпика). **@DevOps не вызывается.**
- **Hot-откат:** `AGENTIC_EVENTS_ENABLED=false` → события/узлы OFF, поведение baseline. Дополнительно (при необходимости) — существующие kill-switches источников (`REACTION_MECHANICS_ENABLED`, `DIRECT_DECISION_MAKING_ENABLED` и др.) без изменений A9.
- **Cold-откат:** `git revert` к **`e8646af`** + агрегатный анкер Эпика 3; **DDL-откат не требуется** (Δ DDL=0); F8-артефакты не меняются (Δ каталога=0). Теги/бэкапы/stash не удаляются (R18).
- **Release-order:** `A0 → A1 → A2 → A3 → A5 → A6 → A4 → A7 → A8 → A9 → A10`; A9 reuse контракты A1–A8; handoff → A10 (агрегатный gate §52–§54).

## 11. Ownership верификации / цепочка

- **Step 2 @Architect (T-3689):** `spec.md` + ADR-1026-22 (этот документ).
- **Сверка @PM (T-3690):** `PLANNING_CONSISTENT`; заполнение SC/ADR-колонок; фиксация Δ DDL=0/Δ каталога=0/канон 12/Risk R2; реконсиляция U-нумерации (tasks.md ↔ темы handoff, §4.1) и поправка якоря `anticliche_worker.emit_event`→`_event:80`.
- **Build (T-3691…T-3701):** схема/whitelist → обёртка → 9-этапный граф → честные метрики → API → Mini App display → L-1 → тесты ядра → off-parity/регресс/adversarial → kill-switch/числа → diff-аудит границ.
- **@Reviewer (T-3702, единый gate):** обе линзы; REQ-A9-01…-14; §49; §51; §50 display-only; §53.5846; R17; REUSE-граф; honest-метрики; silent; L-1; канон 12; Δ DDL/каталог=0; OFF-паритет; risk. **@Scanner отсутствует.**
- **@Architect (T-3703):** merge **§91**; ADR-1026-22 → Accepted. **@PM:** архивация feature-папки.
- **T-3704 = `DEFERRED_TO_EPIC`; T-3705 — handoff → A10.**

## 12. Рассмотренные альтернативы (сводно; детали — ADR-1026-22)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Персистентность (U1/U3) | in-memory S8; PG-таблица | **in-memory (Δ DDL=0)** | прецедент S8; журнал в logs; нет retention/PII-поверхности; одна система; R2 |
| Транспорт (U2) | structured-logger+store; новый event-store | **обёртка над существующим** | нет второй подсистемы; fail-open/async-safe проще |
| Kill-switch (U4) | каталожный; env-only | **env-only `AGENTIC_EVENTS_ENABLED`** | Δ каталога=0; пер-фича hot-откат |
| run_id (U6) | новый id; correlation_id | **correlation_id (S7)** | единый ключ, прецедент S8; нет второго учёта |
| Схема/R17 (U8) | свободные поля; закрытый whitelist | **закрытый enum+whitelist** | R17; §49 «не выводить досье» |
| MESSAGE_IGNORED (U7) | отдельный флаг; из silent-ветки | **из silent-short-circuit A7** | решение уже принимается; нет дубля политики |
| 9 этапов→kind (U11) | новые kinds; существующие | **существующие (+`tool`)** | JS enum уже содержит `tool`; минимальный риск |
| No-fake-tokens (U12) | заполнять нулями; honest-None | **honest-None (null≠$0)** | §51 verbatim; прецедент S8/S6 |
| API (U9) | новый endpoint; расширить существующий | **расширить `/analytics/execution/latest`** | нет второй поверхности/аналитики |
| Mini App (U10) | новая панель; существующая вкладка | **display-only в «Аналитике»** | §50 verbatim; настройки уже поставлены |
| ANTI_CLICHE (U5) | исключить; включить | **включить в enum/whitelist, не в граф** | backlog:311; нет chat/run-контекста |
| L-1 (REQ-12) | отложить; включить | **включить фикс** | handoff A8 (backlog:334); REQ-A9-12 |
| Риск (U13) | R3 (+threat); R2 | **R2** | аддитивные события/fail-open/без LLM/DDL/каталога |

## 13. Risk-Level и усиление

- **Risk-Level: R2 (финальный; D1 — in-memory, Δ DDL=0).** Обоснование: A9 — **аддитивные R17-safe события и узлы** поверх **существующего** ExecutionGraph (read-side adapter + in-memory снапшот), **fail-open**, **без нового пайплайна/LLM-вызова/инструмента/DDL/каталога**; любая ошибка эмиссии не влияет на основной поток; blast radius ограничен диагностикой/отображением; OFF kill-switch возвращает точный baseline. Единственное изменение поведения — L-1 (enum-значение `unknown`→`forbidden`, поведение безопасности идентично).
- **Что повысит до R3 (Reviewer-триггеры):** появление PG-таблицы/DDL событий; блокирующий ввод-вывод/новая очередь на hot-path; изменение поведения чата/реакции; утечка приватного контента (R17); вторая система аналитики/endpoint; выдуманные LLM-токены; переопределение A8-механики/A7-правил; регресс OFF-паритета; новый инструмент/3-й LLM-вызов; изменение канона/каталога.
- **Понижение/удержание R2:** доказанные Δ DDL=0/Δ каталога=0; fail-open/OFF-паритет; honest-None; R17-негативы; REUSE-граф; полный регресс зелёный. **Финал — за Reviewer по фактическому diff.**
- **R3-артефакт `threat-failure-analysis.md` — НЕ требуется** (остаёмся R2/D1). При подъёме Architect/Reviewer до R3 (в т.ч. смена хранилища на PG) — **обязателен**.

## 14. Открытые вопросы / статус

- **U1–U13 — ✅ закрыты** решениями §4 (полные формулировки — ADR-1026-22 D1–D14); темы Step-2 handoff покрыты §4.1 (потерь нет).
- **Канон 12 / Δ DDL=0 / Δ каталога=0 / R2 / EPIC_ONLY** — ✅ (§8, §13).
- **Open (не блокирует Step 2; для PM/Builder, требования не выдумывать):**
  - **U-нумерация:** канон — `tasks.md` U1–U13; handoff-темы сведены в §4.1; при сверке T-3690 PM фиксирует соответствие.
  - **Кодовый якорь `anticliche_worker`:** функция называется `_event` (`:80`), не `emit_event`; в `tasks.md` указан `emit_event` — **поправить при doc-maintenance** (не в этом шаге).
  - **§52 22/23:** в §52 23 сценария, `backlog:312` — «22»; поправить при doc-maintenance.
  - Точные per-event поля whitelist и имена новых констант (`AGENTIC_EVENT_TYPES`/`emit_agentic_event`/`AGENTIC_EVENTS_ENABLED`/stage-ключи) — рабочие; изменяются только правкой spec/ADR, не Builder’ом.
  - `IMAGE_GENERATION_*` source-точки: единая точка сходимости `run_image_request` (direct pre-gate и tool) — подтвердить на Build, что старт/успех/ошибка наблюдаются в одном месте без дубля; image-дубликат с legacy LLM-строкой не подавлять (честные данные).
  - Точное число новых pytest (baseline → +N) подтверждается фактическим прогоном Build.
- **A3 owner-gate `PENDING OWNER VERIFICATION` — внешний**, A9 его не закрывает.
