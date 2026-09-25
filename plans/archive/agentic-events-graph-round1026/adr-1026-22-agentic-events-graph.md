# ADR-1026-22 — A9 «Agentic Events Graph»: диагностические события §49 поверх существующего ExecutionGraph §51 + display-only Mini App §50 — закрытый event-enum + R17-whitelist, fail-open эмиссия над structured-logger + in-memory снапшот (Δ DDL=0), 9 реальных этапов без выдуманных LLM-токенов, silent без фиктивного Вербализатора, env-only `AGENTIC_EVENTS_ENABLED`, включение `ANTI_CLICHE_*`, L-1 `forbidden`-классификация, границы A7/A8/A10, R2

- **Статус:** **Accepted (merge to `plans/ARCHITECTURE.md` §91, 25.09.2026; T-3703 @Architect).** **Accepted = решение принято и включено в pending epic-release Эпика 3; НЕ «deployed»** — release policy **EPIC_ONLY**, deployment **DEFERRED_TO_EPIC** (пер-фича деплоя/тега/bump нет; агрегатный bump **2.58.30 → 2.58.31** — на границе эпика).
- **Фича:** A9 `agentic-events-graph-round1026` (Эпик 3 «Agentic Intelligence», Wave 5 — продолжение; Раунд 10.26). **P1.**
- **Тип** (`backlog:311`): backend/лог + web adapter — события §49 + REUSE ExecutionGraph §51 + Mini App §50 display-only. **Δ DDL = 0**; **Δ каталога = 0**; канон **12**; без LLM-вызова.
- **ТЗ-основание:** `plans/current_task.md` **§49** (`:5634–5681`), **§51** (`:5719–5747`), **§50** (`:5682–5718`, граница отображения); приёмочный ориентир **§53** (`:5846–5847`); **§52** (`:5754–5801`) — A10. **§41-механика** — A8 (не переписывается); **§44-правила** — A7 (не переопределяются).
- **Durable-вход:** `plans/docs/agentic-audit-round1026.md` (A0, APPROVED) — `#epic3-reuse` (REUSE ExecutionGraph, вторая аналитика запрещена), `#tool-map`, `#duplicates`.
- **Baseline (Step 0 @Memory, 25.09.2026):** HEAD **`e8646af`** + **UNCOMMITTED epic-release дерево A2–A8** — не трогать/не коммитить; `APP_VERSION` **2.58.30**; канон **12**; SQLite **v12**; Δ DDL=0; счётчики каталога после A8 **`473/430/448/102/100/21`**; анкер отката **`e8646af`**.
- **Связано:** **REUSE** — ADR-1026-21 (A8: `react_moai`+7-enum, L-1), ADR-1026-20 (A7: `CoordinatorDecision.action/reason_code`, silent/react short-circuit), ADR-1026-15 (A2: `ToolLoopResult`/`tool_results`/chain-коды), ADR-1026-16/-19/-18 (A3/A4/A6: `ImageRequest`/`image_context_memory`/`get_user_context`), ADR-1026-17 (A5), ADR-1026-14 (A1 `CoordinatorDecision` — не дублировать), ADR-1026-10/-11 (S8/S6 ExecutionGraph), ADR-1026-13 (A0), ADR-1020-4/ADR-1020-1; **NOT_APPLICABLE** — ADR-1026-2 (F8 — Δ каталога=0), ADR-1013-3 (промпты); **граница** — §41/A8, §44/A7, §52–§54/A10, §104.

## Контекст

§49 требует «понятные события» диагностики решений: 12 типов (`DECISION_START/COMPLETE`, `TOOL_PLAN_CREATED`, `TOOL_CALL_START/COMPLETE/FAILED`, `REACTION_SENT`, `MESSAGE_IGNORED`, `IMAGE_CONTEXT_RESOLVED`, `IMAGE_GENERATION_START/COMPLETE/FAILED`), для каждой операции — `run_id`/`chat_id`/`message_id`/`action`/инструменты/причину/длительность/ошибки; приватное содержимое досье — **не** в публичные логи; админ-диагностика должна объяснять, почему бот промолчал или вызвал инструмент. §51 требует **использовать расширяемую ExecutionGraph Эпика 1**, отображать **9 реальных этапов** (Decision / Memory Lookup / RAG / Web Extraction / Factcheck / Image Prompt Preparation / Image Generation / Reaction / Text Generation), **не создавать вторую аналитику инструментов**, **не писать выдуманные LLM-токены** для алгоритмических операций и при молчании показывать результат решения **без фиктивного Вербализатора**. §50 (граница) — использовать интерфейс Эпика 1, **не создавать отдельную панель**, **не дублировать параметры**. §53 («по логам невозможно понять, почему инструмент не сработал», `:5846–5847`) — failure criterion, закрываемый A9.

**Фактическое состояние baseline (Step 0 + карта кода).**
- **ExecutionGraph (Эпик 1/2, S8/S6)** уже существует: `services/execution_graph_source.py` — kind-enum `llm/algorithm/format/publish/other` (`:38–42`), `STEP_KIND`/`STAGE_LABELS` (`:73–91`), in-memory `RunSnapshotStore` (TTL 900 c / maxlen 20, `:109–167`; **Δ DDL=0**, прецедент S9 `_RunStore`), `record_run` (`:184`, whitelist `_SNAPSHOT_FIELDS`, ignore unknown keys, fail-open), `build_graph` (`:485`) собирает `algorithm/llm/format/publish` узлы, честно `None`-not-`$0` (`_node`/`llm_node`).
- **API** `web/api/analytics.py:281` `GET /analytics/execution/latest` — RBAC `requires_global_admin()`, читает PG `llm_usage_events` по `correlation_id` + in-memory снапшот, fail-open shape (`_execution_response`).
- **UI** `web/static/execution_graph.js` — `KIND_ENUM` уже содержит резервный **`tool`** (`:48`), `STEP_KIND`/`STEP_LABEL` (`:57–74`), `fromExecution` (`:341`); `web/index.html` вкладка «Аналитика» (`:2192+`); `web/app.js` `execGraph` (`:2558`)/fetch (`:4335`)/`execGraphApi` (`:4432`).
- **Точки эмиссии (verified):** `direct_chat_service.py` — `correlation_id` (`:1174`), `CoordinatorDecision` (`:616–650`), словарь 15 `reason_code` (`:483–505`), `_decision_pre_action` (`:827`), Phase P (`:1286–1316`), silent-short-circuit (`:1303–1307`), react-short-circuit + `react_moai` (`:1308–1316`); `tool_loop.py` — `ToolLoopResult` (`:73`), `tool_trace` (`:82`), `tool_results`, chain-коды `chain_timeout`/`chain_call_limit`/`chain_cost_limit` (`:62–64`), tool-цикл (`:323–462`); `smartmodule_utils.py` — `react_moai` (`:184`), 7-enum (`:111–123`), `_classify_reaction_error` (`:147`), `except TelegramBadRequest` (`:219`), generic `except Exception` (`:227`); `image_context_memory.py` — resolution-enum (`candidate`/`resolved`/`none`, шлюз D13 G0–G3 `:474–501`), `log_image_context_build` (`:846`); `image_generation.py` — `run_image_request` (`:395`), `GenerationResult` (`:122`), `reason_class` (`:546`); `tool_router.py` — `_get_user_context` (`:1176`)/`_memory_lookup_finish`; `anticliche_worker.py` — `_event` (`:80`, события `ANTI_CLICHE_*` `:506–624`).
- **A8 (вход)** ✅ поставляет `react_moai(..., reaction=None, reason_code=None)` + закрытый 7-enum + `REACTION_MECHANICS_ENABLED`; **L-1:** `TelegramForbiddenError` — **не** подкласс `TelegramBadRequest`, сегодня 403 → generic → `REACTION_UNKNOWN`.

**Проверенные внешние факты (research @Step 2):**
- Python **logging** — синхронный, буферизованный; существующий hot-path уже логирует (вызовы `logger.info/warning` в `direct_chat_service`/`tool_loop`), поэтому добавление event-строки не меняет профиль блокировки. Отдельный асинхронный event-store не нужен.
- aiogram **3.31.0** (`requirements.txt`): `TelegramForbiddenError` и `TelegramBadRequest` — оба подклассы `TelegramAPIError` (не являются подклассами друг друга) → отдельный `except TelegramForbiddenError` перехватывает 403 до generic `Exception`.
- Telegram `setMessageReaction` — механика A8 (ADR-1026-21), не переписывается; A9 только наблюдает возвращаемый enum-код.
- `llm_usage_events` (PG) — существующий источник реальных токенов LLM (S8); A9 token-данные оттуда не изменяет.

**Открытые вопросы Step 1 (U1–U13)** требуют lasting-решений; **U1/U3 (персистентность)** определяют финальный Risk, **U11/U12 (маппинг/honest-метрики)** — ядро §51.

## Решения

**D1. U1/U3 — персистентность: in-memory расширение `RunSnapshotStore`; Δ DDL=0; финал R2.**
- **Выбрано:** события/узлы живут в **существующем** in-memory реестре (`RunSnapshotStore`, TTL 900 c / maxlen 20) — новый store не создаётся; PG-таблица событий **не вводится**; SQLite остаётся v12. Запись — через `record_agentic_event` (аддитивно к `record_run`), фильтр по R17-safe whitelist, fail-open.
- **Обоснование:** (i) **прецедент S8/S9** — ExecutionGraph уже in-memory с принятыми рестарт-потерями; (ii) диагностический журнал **сохраняется в logs/journald** (события эмитятся structured-log строкой) → §53-критерий («понять, почему не сработал») закрывается logs’ами без DDL; (iii) нет retention-политики/миграций и **нет новой PII-поверхности** (R17) — in-memory события исчезают при рестарте; (iv) одна система (REUSE), EPIC_ONLY.
- **Последствие:** рестарт-потери live-графа приемлемы для диагностики «latest» (как у S8); при будущей потребности в истории — отдельная санкция DDL (не сейчас). **R2** (не R3): нет DDL/threat-артефакта.
- **Альтернативы:** PG append-only таблица — отклонено (Δ DDL≠0 → R3 + `threat-failure-analysis.md`, retention/PII-поверхность, миграции, вторая подсистема; не требуется для §49/§53 при наличии logs). Гибрид (PG только для событий) — отклонён (лишняя поверхность без продукта).

**D2. U2 — транспорт: тонкая fail-open обёртка над существующим structured-logger + in-memory store; новый event-store нет.**
- **Выбрано:** `emit_agentic_event(event, **fields)` — **синхронная** функция (без `await`/`create_task`), безопасная для async-кода: per-call kill-switch → whitelist-фильтр → structured-log строка `event=<TYPE> | k=v` (прецедент F0.3 `_event`) → аддитивная запись в `RunSnapshotStore`. **Никогда не бросает** (`try/except`), не делает блокирующего ввода-вывода. «Fire-and-forget» = результат не используется.
- **Обоснование:** §51 запрещает вторую аналитику → отдельный event-store/брокер запрещён; существующий logger уже на hot-path (профиль не ухудшается); fail-open гарантирует «0 влияния на чат».
- **Альтернативы:** отдельный async event-store/очередь — отклонено (вторая подсистема, состояние/риск); `asyncio.create_task` fire-and-forget — отклонено (unawaited-task/порядок/исключения; синхронная дешёвая функция проще и безопаснее); писать только в лог без store — отклонено (§51 требует узлы графа).

**D3. U4 — kill-switch: `AGENTIC_EVENTS_ENABLED` (env-only, default ON); Δ каталога=0.**
- `config/settings.py` рядом с `REACTION_MECHANICS_ENABLED:568`/`DIRECT_DECISION_MAKING_ENABLED:560`: `AGENTIC_EVENTS_ENABLED: ClassVar[bool] = _env_bool("AGENTIC_EVENTS_ENABLED", True)`. Резолв per-call, никогда не бросает. **OFF →** 0 событий/узлов, поведение и логи baseline (паритет). env-only `ClassVar` — **не** каталог-параметр (прецедент A8 D10), счётчик не растёт.
- **Альтернативы:** каталожный тумблер — отклонён (Δ каталога); без kill-switch — отклонён (нужен hot-откат).

**D4. U6 — `run_id` = существующий `correlation_id` (S7); новый идентификатор нет.**
- Единый ключ: direct-чат (`correlation_id = usage_events.new_correlation_id()`, `:1174`), `ToolContext.correlation_id` (`:2038`), image-пути (проброс `correlation_id`). События группируются по тому же `run_id`, что LLM-узлы (`_SELECT_STEPS_SQL` по `correlation_id`). Второй идентификатор/учёт не вводится (прецедент S8 D5).
- **Альтернативы:** новый event-id — отклонён (второй учёт, разрыв с ExecutionGraph).

**D5. U8 — схема payload + R17-whitelist.**
- **Закрытый enum `AGENTIC_EVENT_TYPES`** = 12 §49-типов + 8 `ANTI_CLICHE_*` (D11) = **20**; `schema_version="1"`. Событие вне enum не эмитится.
- **Общие поля:** `schema_version`, `event`, `run_id`, `chat_id`, `message_id`, `action`, `tools` (имена), `reason`, `duration_ms`, `errors`, `ts`. Обязательность per-event.
- **Допустимые дополнительные поля (whitelist):** `outcome` (A8 7-enum), `stage`, `tool`, `round`, `status`, `error_code`, `counts`, `source` (`direct`/`tool`), `resolution` (image resolution-enum), `reason_class`, `latency_ms`, `chars`/`prompt_chars` (**числа**, не текст), `mode`. Ключи вне whitelist отбрасываются (прецедент `record_run` — «не расширяем поверхность утечки»).
- **R17:** только id/enum/числа/имена инструментов/`reason_code`; **никогда** — текст сообщений, досье/факты/имена, промпты, сырые ответы/размышления LLM, URL с секретами, ключи. Негативные тесты.
- **Альтернативы:** свободные `**fields` без whitelist — запрещено (R17); сериализовать `CoordinatorDecision` целиком — запрещено (сырьё/дрейф).

**D6. U7 — `MESSAGE_IGNORED` из silent-short-circuit A7.**
- В ветке `pre_action == ACTION_SILENT` (`:1303–1307`) перед `return` эмитится `MESSAGE_IGNORED` (поля: `action=silent`, `reason`=A7 `reason_code`, `target`). Политика A7 не дублируется: A9 только **наблюдает** уже принятое решение.
- **Silent-семантика:** граф содержит узел **Decision** с `reason_code`; узел **Text Generation/Вербализатор не создаётся** (нет фиктивного вызова) — §51 verbatim. `REACTION_SENT` — в react-ветке после `react_moai` с `outcome` (D13/L-1).
- **Альтернативы:** собственная реализация «почему молчание» — запрещено (дубль политики A7).

**D7. U11 — 9 этапов → `kind`: существующие kind-ы (+`tool`), без новых.**

| §51-этап | `stageKey` | `kind` | Токены |
|---|---|---|---|
| Decision | `decision` | `algorithm` | `None` |
| Memory Lookup | `memory_lookup` | `tool` | `None` |
| RAG | `rag` | `tool` | `None` |
| Web Extraction | `web_extraction` | `tool` | `None` |
| Factcheck | `factcheck` | `tool` | `None` |
| Image Prompt Preparation | `image_prompt` | `algorithm` | `None` |
| Image Generation | `image_generation` | `tool` | `None` |
| Reaction | `reaction` | `tool` | `None` |
| Text Generation | `text_generation` | `llm` | реальные из `llm_usage_events` |

- **`KIND_TOOL = "tool"`** добавляется в Python-константы (JS `KIND_ENUM:48` уже содержит `tool` — **renderer не рефакторится**, только аддитивные `STEP_KIND`/`STEP_LABEL`). **Новых kinds нет.** `build_graph` дополняется агентными узлами при их наличии; сводный граф без агентных данных — байт-в-байт. Нет данных этапа → нет узла (прецедент §24/§25).
- **Альтернативы:** ввести `decision`/`reaction`-kinds — отклонено (расширение renderer-контракта без нужды; label несёт `stageLabel`); маппить всё в `other` — отклонено (потеря семантики).

**D8. U12 — no-fake-tokens: honest-`None` для алгоритмических операций.**
- Все агентные узлы кроме Text Generation — `inputTokens=outputTokens=cost=None`, `priceKnown=false`, `costCurrency=null`; `null` ≠ `$0` (прецедент `_node`/`algorithm_node`/`metrics_block`). Токены — только из реальных `llm_usage_events`-строк (Text Generation). Тест фиксирует.
- **Альтернативы:** заполнять `0`/`$0` — запрещено §51 `:5741–5742`.

**D9. U9 — API-поверхность: аддитивное расширение `GET /analytics/execution/latest`; новый endpoint нет.**
- Агентные узлы идут в существующий `nodes[]`/`edges[]` shape; RBAC — существующий `requires_global_admin()`; fail-open — существующий `_execution_response` (PG down/телеметрия OFF → shape-совместимый пустой граф). Новых обязательных полей контракта нет.
- **Альтернативы:** новый `/analytics/agentic/latest` — отклонён (§51 «не создавать вторую систему аналитики»; вторая поверхность/RBAC/дублирование).

**D10. U10 — Mini App §50: display-only срез в существующей вкладке «Аналитика».**
- Аддитивные `STEP_KIND`/`STEP_LABEL` в `execution_graph.js`; `fromExecution`/`web/app.js execGraph` уже принимают узлы/`metrics`/`publicationStatus`. Отдельный компонент/панель/вкладка **не создаётся**; настройки §50 уже поставлены A4/A5/A7/A8 — **не дублируются** (`:5716–5717`); Δ каталога=0.
- **Альтернативы:** новая панель/вкладка — прямо запрещено §50 `:5686–5689`.

**D11. U5 — включение `ANTI_CLICHE_*` (F0.3): enum/whitelist/kill-switch; не в чат-граф.**
- 8 существующих событий (`ANTI_CLICHE_UPDATE_START/MODEL_REQUEST/MODEL_RESPONSE/PARSE_ERROR/DEDUP_COMPLETE/SAVE_COMPLETE/UPDATE_COMPLETE/UPDATE_FAILED`) включаются в `AGENTIC_EVENT_TYPES`/whitelist/kill-switch; `anticliche_worker._event` (`:80`) маршрутизируется через `emit_agentic_event` — второй логгер/канал не создаётся. В чат-граф **не форсируются** (воркер-scope: нет `run_id`/`chat_id`/`message_id`).
- **Обоснование:** `backlog:311` явно включает `ANTI_CLICHE_*` в A9; унификация событий/whitelist/switch — минимальная, без изобретения граф-семантики воркера.
- **Альтернативы:** исключить — отклонено (backlog); строить узлы воркера в чат-графе — отклонено (нет run-контекста, семантическая путаница).

**D12. U13 — границы/EPIC_ONLY/откат/pacing.**
- **EPIC_ONLY:** deployment **`DEFERRED_TO_EPIC`**; @DevOps не вызывается; пер-фича тег/bump нет; `APP_VERSION` остаётся **2.58.30** (агрегатный bump 2.58.30 → 2.58.31 — на границе эпика).
- **Границы:** §41/A8-механика — не переписывается; §44/A7-правила — не переопределяются; §52–§54/A10 — вне A9 (кроме §53.5846); §104 `generate_image` — no-go; вторая аналитика/endpoint — запрещены; канон **12**; нет 3-го LLM-вызова; Δ DDL=0; Δ каталога=0; `CoordinatorDecision` (A1) — не дублировать.
- **Pacing:** A9 **предшествует** A10 по зависимости (A10 зависит A0–A9; `backlog:312`); P1 vs P0 — **не гейт**, а порядок.
- **Откат:** hot — `AGENTIC_EVENTS_ENABLED=false`; cold — `git revert` к **`e8646af`** + агрегатный анкер; DDL-откат не нужен (Δ DDL=0).

**D13. L-1 — `TelegramForbiddenError` → `REACTION_FORBIDDEN`.**
- `services/smartmodule_utils.py`: импорт `TelegramForbiddenError` из `aiogram.exceptions` (`:22`); новый `except TelegramForbiddenError: return REACTION_FORBIDDEN` (с тем же `_warn_reaction_failed`) **перед** generic `except Exception` (`:227`). `TelegramForbiddenError` не подкласс `TelegramBadRequest` → сегодня 403 попадает в generic → `REACTION_UNKNOWN`.
- **Поведение безопасности идентично** (тихий отказ, без fallback/текста/повтора); меняется только классификация. Unit-тест: `forbidden`, 1 вызов `set_message_reaction`, 0 текста; generic `Exception` → `unknown` (не сломан).
- **Альтернативы:** оставить как есть/отложить — отклонено (REQ-A9-12, handoff A8 `backlog:334`).

**D14. Границы (verbatim-critical).**
- **§49:** 12 событий + 8 полей + «не выводить приватное досье» + админ-диагностика — реализованы; формулировки не сужены.
- **§51:** REUSE ExecutionGraph; 9 реальных этапов; **не** вторая аналитика; **не** выдуманные LLM-токены; silent без фиктивного Вербализатора — соблюдены.
- **§50:** интерфейс Эпика 1; нет отдельной панели; нет дублирования параметров — соблюдены (display-only).
- **§53** `:5846–5847` — закрыт (REQ-A9-13/SC-A9-13).
- **A8-механика** — не переписывается (только L-1-классификация); **A7-правила §44** — не переопределяются; **A1** `CoordinatorDecision` — не дублируется; **A2–A6** — не переписываются (только точки эмиссии).
- **Канон 12; нет LLM-вызова; Δ DDL=0; Δ каталога=0; §104 no-go; R17-логи; EPIC_ONLY/@DevOps не вызывается.**

## Санкции и вердикты (verbatim-critical)

- **Канон:** **НЕ расширяется.** `TOOL_CALLING_TOOLS == 12`; новый инструмент/JSON-схема не вводятся.
- **Δ DDL = 0** (D1): новых таблиц/колонок/индексов/PG нет; SQLite **v12**; миграций нет.
- **Δ каталога = 0** (D3/D10): новых параметров/групп/вкладок нет; F8 не переиздаётся; счётчики `473/430/448/102/100/21` без изменений.
- **Kill-switch:** `AGENTIC_EVENTS_ENABLED` (env-only, default ON; OFF → 0 событий/узлов, паритет baseline).
- **API:** аддитивное расширение `GET /analytics/execution/latest`; новых endpoint нет (D9).
- **Промпты:** ADR-1013-3 = **NOT_APPLICABLE** (промпты/JSON-схемы не меняются).
- **Risk:** **R2** (D1); R3-артефакт `threat-failure-analysis.md` **не требуется**; при подъёме (DDL/блокировка hot-path/утечка R17/вторая аналитика) — обязателен.
- **Обратный путь:** `AGENTIC_EVENTS_ENABLED=false` → baseline; cold — `git revert` к **`e8646af`** + агрегатный анкер; DDL-откат не нужен.
- **Release policy:** **EPIC_ONLY** → deployment **DEFERRED_TO_EPIC**; @DevOps не вызывается; `APP_VERSION` **2.58.30** (агрегатный bump — на границе эпика).
- **§104 `generate_image`** — no-go (вне diff).

## AMEND / REUSE-карта

| ADR / артефакт | Статус в A9 | Суть |
|---|---|---|
| **ADR-1026-10/-11** (ExecutionGraph S8/S6) | **REUSE + аддитивное расширение** | `RunSnapshotStore`/`record_run`/`build_graph`/endpoint — дом; добавляются агентные stage/узлы; сводный граф без агентных данных не меняется; in-memory/Δ DDL=0 сохраняется |
| **ADR-1026-21** (A8 `react_moai`, 7-enum) | **REUSE / граница** | механика не переписывается; A9 наблюдает возвращаемый outcome и эмитит `REACTION_SENT`; **L-1**-классификация (D13) дополняет enum |
| **ADR-1026-20** (A7 `action`/`reason_code`/short-circuit) | **REUSE / граница** | `MESSAGE_IGNORED`/`REACTION_SENT` из silent/react-веток; правила §44/`_decision_pre_action` не переопределяются |
| **ADR-1026-15** (A2 `ToolLoopResult`/`tool_results`/chain-коды) | **REUSE / граница** | источник `TOOL_PLAN_CREATED`/`TOOL_CALL_*`; цикл/лимиты не меняются |
| **ADR-1026-16/-19** (A3/A4 `ImageRequest`/`image_context_memory`) | **REUSE / граница** | `IMAGE_CONTEXT_RESOLVED`/`IMAGE_GENERATION_*` вокруг существующих точек; pipeline не меняется |
| **ADR-1026-18** (A6 `get_user_context`) | **REUSE / граница** | Memory Lookup — tool-узел из существующего tool-контекста |
| **ADR-1026-17** (A5) | **REUSE / граница** | вне diff |
| **ADR-1026-14** (A1 `CoordinatorDecision`) | **REUSE / граница** | контракт не дублируется |
| **ADR-1026-13** (A0) | **REUSE (ориентиры)** | `#epic3-reuse`/`#tool-map`/`#duplicates` |
| **ADR-1026-2** (F8-переиздание) | **NOT_APPLICABLE** | Δ каталога = 0 |
| **ADR-1013-3** | **NOT_APPLICABLE** | промпты не меняются |
| **ADR-1020-4 / ADR-1020-1** | **REUSE** | канон/ID-политика |
| **§41/A8-механика; §44/A7-правила; §52–§54/A10** | **не переопределяются / вне scope** | границы |
| **F0.3 `ANTI_CLICHE_*`** | **REUSE + унификация** | `_event` → общая обёртка (D11) |
| **§104** | **no-go** | `generate_image` не трогать |

| Решение | Задачи (`tasks.md`) |
|---|---|
| D1 (U1/U3: in-memory, R2) | T-3691, T-3695 |
| D2 (U2: обёртка эмиссии) | T-3691, T-3692 |
| D3 (U4: kill-switch) | T-3700 |
| D4 (U6: `run_id`=correlation_id) | T-3691, T-3693 |
| D5 (U8: схема/whitelist/R17) | T-3691 |
| D6 (U7: `MESSAGE_IGNORED`, silent) | T-3691, T-3694 |
| D7 (U11: 9 этапов→kind) | T-3693 |
| D8 (U12: no-fake-tokens) | T-3694 |
| D9 (U9: API) | T-3695 |
| D10 (U10: Mini App display) | T-3696 |
| D11 (U5: `ANTI_CLICHE_*`) | T-3691, T-3693 |
| D12 (U13: границы/EPIC_ONLY/откат) | T-3700, T-3703 |
| D13 (L-1) | T-3697 |
| D14 (границы) | T-3701 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Персистентность (U1/U3) | PG-таблица; in-memory S8 | **in-memory, Δ DDL=0** | прецедент S8; logs-журнал; нет retention/PII/миграций; R2 |
| Транспорт (U2) | новый event-store/очередь; logger+store | **fail-open обёртка над logger+store** | §51 не вторая аналитика; без блокировок/состояния |
| Kill-switch (U4) | каталожный; env-only | **`AGENTIC_EVENTS_ENABLED`** | Δ каталога=0; hot-откат |
| `run_id` (U6) | новый id; correlation_id | **correlation_id (S7)** | единый ключ S8; без второго учёта |
| Схема/R17 (U8) | свободные поля; whitelist | **закрытый enum + whitelist** | §49 «не досье»; R17 |
| MESSAGE_IGNORED (U7) | своя политика; из A7-silent | **из A7-silent** | нет дубля §44-политики |
| 9 этапов (U11) | новые kinds; существующие | **существующие (+`tool`)** | JS уже содержит `tool`; минимум риска |
| Метрики (U12) | `0`/`$0`; honest-`None` | **honest-`None`** | §51 verbatim; прецедент S6/S8 |
| API (U9) | новый endpoint; расширить существующий | **расширить `/analytics/execution/latest`** | §51 не вторая аналитика |
| Mini App (U10) | новая панель; существующая вкладка | **display-only в «Аналитике»** | §50 verbatim |
| ANTI_CLICHE (U5) | исключить; включить | **включить в enum/whitelist, не в граф** | `backlog:311`; нет run-контекста |
| L-1 | отложить; включить | **включить** | `backlog:334`; REQ-A9-12 |
| Риск (U13) | R3 (+threat); R2 | **R2** | аддитивно/fail-open/без LLM/DDL/каталога |
| Дом графа | новый adapter; расширить `execution_graph_source` | **расширить существующий** | §51 REUSE; единая система |

## Последствия

- §49 реализован: 20-типовой закрытый event-enum (12 §49 + 8 `ANTI_CLICHE_*`), обязательные поля операции, R17-whitelist (id/enum/числа/инструменты/`reason_code`), fail-open эмиссия, env-only kill-switch; приватное досье/промпты/сырые тексты в события не попадают.
- §51 реализован: 9 реальных этапов в **существующем** ExecutionGraph; алгоритмические узлы без выдуманных LLM-токенов (`null` ≠ `$0`); silent → узел Decision без фиктивного Вербализатора; вторая аналитика не создана.
- §50 соблюдён: display-only срез в существующей вкладке «Аналитика»; без отдельной панели/дублирования параметров.
- §53 `:5846–5847` закрыт: события/граф объясняют, почему инструмент не сработал.
- L-1 закрыт: `TelegramForbiddenError` → `REACTION_FORBIDDEN` (поведение безопасности идентично).
- Канон **12**; **Δ DDL=0**; **Δ каталога=0**; R17; risk **R2**; hot-откат env-OFF; cold — `git revert` к `e8646af`; deploy `DEFERRED_TO_EPIC`; handoff → A10.

## Ссылки

- `plans/features/agentic-events-graph-round1026/{spec.md, tasks.md}` (spec — Step 2 T-3689; сверка — @PM T-3690).
- Durable-аудит: `plans/docs/agentic-audit-round1026.md` (`#epic3-reuse`, `#tool-map`, `#duplicates`).
- ТЗ: `plans/current_task.md` §49 (`:5634–5681`), §50 (`:5682–5718`), §51 (`:5719–5747`), §52 (`:5754–5801`), §53 (`:5846–5847`).
- Входы: `plans/archive/telegram-reactions-round1026/` (A8, ADR-1026-21, §90); `plans/archive/decision-making-round1026/` (A7, ADR-1026-20, §89); `plans/archive/tool-chains-round1026/` (A2, ADR-1026-15); `plans/archive/unified-image-request-round1026/` (A3, ADR-1026-16); `plans/archive/image-context-memory-round1026/` (A4, ADR-1026-19); `plans/archive/memory-lookup-api-round1026/` (A6, ADR-1026-18); `plans/archive/image-daily-limit-round1026/` (A5, ADR-1026-17).
- Код (baseline `e8646af` + незакоммиченный epic-release A2–A8): `services/execution_graph_source.py` (`:38–42`, `:73–91`, `:109`, `:184`, `:485`); `web/api/analytics.py:281`; `web/static/execution_graph.js` (`:48`,`:57–74`,`:341`); `web/app.js` (`:2558`,`:4335`,`:4432`); `web/index.html:2192+`; `services/direct_chat_service.py` (`:1174`,`:483–505`,`:616–650`,`:827`,`:1286–1316`); `services/tool_loop.py` (`:62–64`,`:73`,`:82`,`:323–462`); `services/smartmodule_utils.py` (`:22`,`:111–123`,`:147`,`:184`,`:219–230`); `services/image_context_memory.py` (`:474–501`,`:846`); `services/image_generation.py` (`:122`,`:395`,`:546`); `services/tool_router.py:1176`; `services/anticliche_worker.py:80` (`ANTI_CLICHE_*:506–624`); `config/settings.py` (`:560`,`:568`).
- Тех-контекст/версии: `requirements.txt` (aiogram **3.31.0**); Python `logging` (sync/буферизованный); существующий ExecutionGraph (S8/S6).
- Архитектура: `plans/ARCHITECTURE.md` §90 (A8), §79 (S8), §65 (F6); ожидаемый merge — **§91** (следующий свободный).
- Точка отката: коммит **`e8646af`** (пер-фича тега не создаётся — `EPIC_ONLY`).
