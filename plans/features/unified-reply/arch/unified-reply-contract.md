# UNIFIED-REPLY — архитектурный контракт (UR-01..UR-30)

- **Статус:** ARCHITECT_VALIDATED (с поправками на устаревшие якоря ТЗ).
- **Основа:** `plans/owner_inputs/2026-11-05-unified-reply.md` (v1.1, 30 требований).
- **ТЗ написано против** `master 24ca634b`; **этот контракт проверен против фактического HEAD** `4e5a01f9` (ветка `evol/impl`, worktree `6f4c07e43141f379`), который уже содержит RC v5 (speech projection, factcheck target continuity, self-correction), evidence-pack инициативы и пакет prompt-versioning (PVR, 2.58.155).
- **Принцип:** семантика ТЗ владельца сохраняется полностью; вместо «построить с нуля» в нескольких местах фиксируется «достроить существующее». Ни одно требование владельца не ослабляется.

---

## 1. Якоря текущего состояния (HEAD 4e5a01f9) и устаревшие утверждения ТЗ

### 1.1 Таблица якорей

| # | ТЗ (master 24ca634b) | Факт на HEAD 4e5a01f9 | Вердикт |
|---|---|---|---|
| 1 | `direct_chat_service.py:8791+` `plan_initiative_decision()` c `capabilities=()` и прямым `llm.generate(step="l1_planner")` | `plan_initiative_decision` — **12735**; `capabilities=()` — **12858**; прямой `llm.generate(step="l1_planner")` — **12903**; при этом уже: `resolve_l1_context_budget` (**12844**), возврат `L1Plan` (F6), `_recent_bot_replies` в контексте (**12775**) | Строки устарели; **ядро претензии верно** (нет общего capability/permission/repair-маршрута), но L1 инициативы уже model-aware и уже возвращает `L1Plan` |
| 2 | `direct_chat_service.py:8906+` `generate_initiative_reply()`: 12 строк окна, `max_tokens=700`, «инструментального этапа там нет» | `generate_initiative_reply` — **12913**; `render_window_lines(window, 12, ...)` — **~13013**; `_l2_write_answer(..., writer="initiative_writer", max_tokens=700)` — **13149**; egress-rewrite `max_tokens=700` — **13176**. **НО: tool-фаза уже существует** — `_l1_tool_subset` + `_l1_tool_phase` вызываются в **13099–13102** (evidence-pack механизм `_evp`, claim-keys, `_evidence_reuse_pack`, egress-guard) | Строки устарели; `700` и `12×200` подтверждены; «нет инструментального этапа» — **УСТАРЕЛО**: этап есть, но управляется evidence-policy (claims/`required`), а не осью `search_intent` из UR-06. Задача UR-B — унификация политики, не строительство с нуля |
| 3 | `direct_l1.py:644+,662+` `L1_WINDOW_MESSAGES=20`, `L1_WINDOW_LINE_CHARS=200`, `L1_PERSONA_FRAME_CHARS=400`, budget 1600, `_cap_context()` | `L1_WINDOW_MESSAGES=20` — **888**; `L1_WINDOW_LINE_CHARS=200` — **904**; `L1_PERSONA_FRAME_CHARS` — **удалён** (комментарий на 890); дефолт `DIRECT_L1_CONTEXT_TOKENS=1600` — **723**, флор `L1_CONTEXT_FLOOR_TOKENS=1600` — **937**; `resolve_l1_context_budget` — **1350** (вызовы: Direct **5910**, Initiative **12844**); `_cap_context` — **1550**; `window_line_chars` уже выводит лимит строки из бюджета (**942–963**) | Частично устарело: персон-фрейм уже удалён; бюджет уже частично model-aware для обоих режимов; константные капы окна/строки ещё режут независимо от allocator |
| 4 | `direct_chat_service.py:6630+` `_render_current_question()` режет по `chat_current_question_max_chars` | `_render_current_question` — **9678**; ER-08 (02.11.2026): `cap_chars` теперь **только для L1** (дефолт 800, `settings.py:2985`), `None` → полный текст для Writer | Частично устарело: Writer уже без капа; **L1 всё ещё режет на 800** — UR-10 остаётся актуальным для L1-входа |
| 5 | `summary_memory.py:2700+` `get_window_messages()` SQL-окно 6 ч / 500 сообщений | `get_window_messages` — **3231**; `SUMMARY_WINDOW_HOURS=6.0` (`settings.py:492`), `SUMMARY_MAX_WINDOW_MESSAGES=500` (`settings.py:1981`), триггер конспекта `CHAT_CONTEXT_FILL_RATIO` — **3250** | Подтверждено; строки устарели |
| 6 | `direct_chat_service.py:5540+` `Global_Context` = конспект + post-watermark хвост | `_build_global_context_parts` — **8473**; приоритеты в composer: `global_head` P2, `global_tail` P1 (`direct_context_composer.py:72-75`) | Строки устарели; сборка уже идёт через composer-приоритеты |
| 7 | `direct_context_composer.py:254+` allocator P0–P3 «не режет, если влезает» | Приоритеты — **51–80**: P0 = current/target/relations/protected/lore/branch/episode/sandwich/**correction**; P1 = global_tail/thread; P2 = global_head/rag/history_supplement/map; P3 = middle/weak/anchors; eviction P3→P2→P1; §16 «всё влезает — не режем» | Подтверждено; строки устарели. `correction` уже P0 — «актуальные пользовательские исправления» защищены |
| 8 | `direct_chat_service.py:7792+` `style_anchors` из прошлых ответов бота, фильтр по первым словам | `_build_style_anchors` — **11279**; `db.last_bot_replies` (**11296**, database.py:**11095**), `flags.chat_style_anchors_enabled`, dedup по первому слову | Подтверждено; строки устарели. Также жива `_build_mood_block` (лексика «зло/радостно») — сразу после `_build_style_anchors` (**~11325+**) |
| 9 | `direct_chat_service.py:1893+,1981+`; `database.py:4745+` `bot_replies` TTL 3600; `mca_bot_outputs` durable ledger | `bot_replies` — **персистентная таблица** TTL 3600/cap 200 (**3276–3291**); `_recent_bot_replies` — **3364**; `mca_bot_outputs` DDL v22 — **database.py:863–910** (индексы chat_tg/hash/corr), запись **5193**, выборки **5228–5534**; `thread_chain` уже восстанавливает ход бота из ledger после TTL (**thread_chain.py:335–336**) | Подтверждено и даже сильнее: механизм ledger→history уже частично встроен (UR-23 опирается на него, не строит заново) |
| 10 | `direct_chat_service.py:5177+`; `canonical_context.py:313+` время через `limits.chat_timezone` c fallback `summary_timezone`; `format_chat_time()` — только строка для Direct | `_chat_time_line` — **8041–8053**: `_cp_g(chat_id, "limits.chat_timezone", hot.get(...))` → fallback `limits.summary_timezone` → `format_chat_time`; `format_chat_time` — **canonical_context.py:797**; **единственный** вызов — Direct **8053**; резолвер per-chat: `get_chat_param` — **chat_params.py:344**, **sourced-вариант** `(value, source)` — **chat_params.py:704** (chat/global/factory) | Подтверждено; строки устарели. Sourced-геттер уже есть — `timezone_source` для TimeSnapshot берётся из него |
| 11 | `summary_scheduler.py:135+`; `param_catalog.py:1560+` общий cron 0/6/12/18 по `limits.summary_timezone` | **Точно подтверждено**: `AsyncIOScheduler(timezone=limits.summary_timezone)` — **135**; `CronTrigger(hour="0,6,12,18")` — **140–141**; лог — **151**; тик проходит все чаты (`reactions.summary_target_chat_ids` / `get_smart_chat_ids`). В каталоге: `SUMMARY_TIMEZONE` — **1644** (группа `limits_summary`), `CHAT_TIMEZONE` — **1649** (`limits_chat_behavior`), `GOODMORNING_TZ` — **2195** (`reactions_goodmorning`), select-виджет `CHAT_TIMEZONE` c 12 захардкоженными зонами — **3197–3212** | Полностью подтверждено; строки каталога устарели |
| 12 | `factcheck_service.py:520+,602+,1073+,1147+`; `temporal_factcheck.py:328+` свой payload, UTC/unknown-TZ, нет ChatClock | Шаги: `single` **1874**, `stage1` **1892**, `stage2` **1947**, `temporal_verdict` **2320**, `temporal_fallback` **2325/2380**, `temporal_validator` **2362**, `temporal_verbalize` **2681**; `tz_unknown_interval` — **temporal_factcheck.py:389/762**; `format_chat_time` факчеком не импортируется | Подтверждено; строки устарели. Сборка контекста — `factcheck_context.py` (`ConversationContext`, verbatim/digest с budget) |
| 13 | `direct_chat_service.py:4635+` `_l2_write_answer()` c `verbalize_validated(max_retries=2)` | `_l2_write_answer` — **7406**; `verbalize_validated(..., max_retries=2)` — **7656** и **7897** (два call-site: основной и fallback-путь) | Подтверждено; строки устарели. UR-15 должен покрыть **оба** call-site |
| 14 | `mca_retrieval_context.py:480+` retrieval объеденяет exact/FTS, vector, graph, episodes | `RetrievalRequest` — **315** (scope/mode/identity-prior: subject/speaker/reply-target entity ids), `retrieve` — **541** | Подтверждено; строки устарели |
| 15 | `llm_client.py:1344+` `max_output_tokens→max_tokens`; `generate()` теряет `finish_reason` | `generate` (str) — **1353**; **`generate_chat` уже возвращает `LLMChatResult(content, tool_calls, finish_reason, reasoning)` — 301/1678/1880–1886**; `max_output_tokens` уже параметр `generate_chat` (MCA-23); `supervised_transport` для summary-надзора | **Частично устарело**: finish_reason уже доступен через `generate_chat`. UR-18 сводится к тонкой обёртке `generate_with_metadata()` + подключение L1/L2 Writer'ов, а не к новому транспортному слою |
| 16 | `mca_intents.py:594+` `chunk_text()` до 4096 | `chunk_text` — **594** | Подтверждено; якорь точный |
| 17 | `param_catalog.py:1790+` `CHAT_BUDGET_RESPONSE_RATIO` no-op | **1901–1903**, описание прямо: «рантайм его не читает» | Подтверждено; строка устарела |
| 18 | `summary_memory.py:2810+` TTL running summary «сохраняется при истечении» | Комментарий read-path уже говорит: «TTL пишется, при чтении НЕ "убивает"» — **3348–3350**; запись TTL — **3412**; параметр в каталоге «Срок жизни бегущего конспекта, минут» — **param_catalog.py:1790** | Частично устарело: семантика чтения уже исправлена; остаётся UI-формулировка и watermark-статус для UR-12 |
| 19 | `direct_execution.py:76+` потолки adaptive chain, query 800 | `ORCHESTRATOR_MAX_STEPS=4` — **94**, `MAX_TOTAL_TOKENS=6000` — **95**, `MAX_METERED_CALLS=4` — **96**, `QUERY_CHARS=800` — **97**, `EVIDENCE_SNIPPET_CHARS=400` — **99**, срез snippet — **808**; `_SEARCH_MAX_SYMBOLS` — в `search_service.py` | Подтверждено; строки устарели |
| 20 | — (нет в ТЗ) | `auto_budget.resolve_stage_budget` уже имеет `policy_mode: unlimited|dynamic|cap|auto` (**auto_budget.py:147,163–233**; Dynamic 16000 — «operational soft target», §35) | UR-11 «Dynamic по умолчанию» — уже реализован механизм; остаётся включить его как единственный путь для L1/initiative стадий |
| 21 | — (нет в ТЗ) | `SpeechProjection` — **canonical_context.py:465** (RC v5), используется в Direct L1/Writer и Initiative Writer; `speech_projection_enabled()` рядом | Не ломать: UR-10/UR-C обязаны сохранять projection-метки в рендере окна |
| 22 | — (нет в ТЗ) | goodmorning relay уже пишет ledger после отправки (`goodmorning_relay.py:~161`, tg_message_id) | UR-23 write-path частично готов на этом маршруте |

### 1.2 Крупнейшие stale-выводы (влияют на объём пакетов)

1. **Инициатива уже имеет tool-фазу** (якорь 2). UR-03/UR-B = выравнивание её управления под ось `knowledge_origin`/`search_intent` из L1 (сейчас управляет evidence-policy `required`+claims), а не создание этапа.
2. **L2 у инициативы уже общий** (`_l2_write_answer`). UR-04 = убрать `writer="initiative_writer"`-ограничения (`max_tokens=700`, `12×200`), оставить метку как diagnostics.
3. **`LLMChatResult(finish_reason=...)` уже существует** (якорь 15). UR-18/UR-19 — обёртка + continuation до отправки, не новый транспорт.
4. **L1 бюджет уже model-aware** для Direct и Initiative (якоря 1, 3). UR-10/UR-11 = переход от константных кап (`20×200`, `[:800]`, флор 1600 как потолок) к ContextSelection + allocator, не создание capacity-механизма.
5. **Ledger→история уже частично работает** (якоря 9, 22; thread_chain). UR-23 = единый read-path + полнота write-path, не новый индекс.

---

## 2. Пять контрактов хода

Все пять — dataclass-контракты; исполнение остаётся в существующих модулях. Новый файл разрешён ровно один: `services/turn_types.py` — **только** фрозен-датаклассы и enums, без логики (это контракт-модуль, не «второй пайплайн»). `L1Plan` остаётся канонически в `services/direct_l1.py` (расширяется на месте).

### 2.1 `TurnRequest` (владелец: адаптеры входа; consumers: engine)

```python
# services/turn_types.py
@dataclass(frozen=True)
class TurnRequest:
    trigger_type: str                    # "direct" | "initiative"
    chat_id: int
    correlation_id: str
    source_message_id: int | None        # tg id (direct) / None (initiative)
    raw_text: str                        # полный исходный текст/caption — НЕ preview, НЕ [:800]
    media_markers: tuple[str, ...]       # media_marker(...), speech-projection-aware
    speaker_uid: int | None
    reply_parent: ReplyParentRef | None  # tg_id, author_uid, alias, source_ref
    addressee: AddresseeRef | None       # для инициативы — intent_row.addressee_user_id (L1D)
    aliases_snapshot: Mapping[int, str]  # результат _refresh_turn_aliases
    opportunity: OpportunityRef | None   # durable intent: intent_id/goal/kind/origin/created_at (P0, 18.10)
    capabilities: tuple[str, ...]        # resolved ДО планирования: direct_capabilities.resolve_capabilities
    tool_state: ToolStateSnapshot        # реальные разрешения/доступность провайдеров поиска
    model_slot: SlotBudgetMeta           # результат resolve_l1_context_budget (slot/fallback/meta)
    delivery: DeliveryPolicy             # direct: force/direct-request; initiative: SendRecheck-политика
    turn_started_at_utc: int
    time_snapshot: "TimeSnapshot"        # §3 — время начала хода (phase="plan")
```

- Строится: `DirectChatService.handle` (direct) и `DirectChatService.handle_initiative` (initiative) — **публичные входы сохраняются** (UR-01). Оба вызывают единый приватный `await self._execute_turn(req: TurnRequest)` в том же `direct_chat_service.py`.
- `plan_initiative_decision()` перестаёт вызывать `self.llm.generate(step="l1_planner")` с `capabilities=()` напрямую: он **готовит вход** (opportunity, addressee, window seed) и вызывает общий L1-executor (извлечённое из `_plan_direct_l1` ядро: слот/permission/repair/usage — одна копия, UR-02). Право инициативы на молчание (`SILENT` при repair-отказе) сохраняется; прямое обращение не проходит инициативный гейт молчания.
- `TurnRequest` — данные. Любые тексты из чата — недоверенный контент, в системные инструкции не интерполируются.

### 2.2 `ContextSelection` (владелец: `direct_context_composer.py`; producers: composer + retrieval + ledger read-path)

```python
# services/turn_types.py (типы), сборка — direct_context_composer + direct_chat_service
@dataclass(frozen=True)
class ContextFragment:
    kind: str            # user_statement|bot_statement|chat_event|summary_inference|external_evidence
    source_id: str       # msg:<id> | bot_output:<id> | summary:<id> | evidence:<id> (mca-04a SourceRef)
    timestamp_utc: int
    speaker_uid: int | None
    author_label: str    # актуальный алиас чата
    text: str            # полный текст; режет ТОЛЬКО allocator
    reply_to: str | None # source_id или tg:<id>
    authority: str       # primary | supporting | background
    fresh: bool

@dataclass
class ContextSelection:
    current_question: ContextFragment            # P0, полный текст (UR-10: без [:800])
    reply_parent: ContextFragment | None         # P0
    thread: tuple[ContextFragment, ...]          # P1 свежие соседи темы, ВКЛЮЧАЯ bot_statement
    memory: tuple[ContextFragment, ...]          # retrieval: exact/lexical+reply → vector/episodes; dedup
    self_outputs: tuple[ContextFragment, ...]    # bot_statement из ledger (§5); не стилевые якоря
    summary_map: SummaryMapRef | None            # P2 running summary + watermark (охвачено до <ts>)
    evidence: "ToolEvidence | None"              # P0 проверенные внешние факты
    provenance: SelectionProvenance              # counts raw/selected/included + причины потери (для UR-20)
```

- Блоки `Current_Question / Conversation_Thread / Global_Context / RAG_Memory / Old_Episode` **сохраняются как render-проекции** фрагментов там, где их читают действующие компоненты (UR-09 п.7); единственный владелец усечения — allocator (`direct_context_composer`, приоритеты §1.1-7).
- L1 и L2 получают **разные проекции одного** `ContextSelection` (UR-04: не обязаны получать одинаковый объём); `render_window_lines` остаётся как рендер проекции, но без независимых констант `20×200`/`12` на смысловом пути.
- Provenance (`raw → selected → included` + reason) пишется в turn-диагностику — это источник «Что бот видел» (UR-20) без новых хранилищ.

### 2.3 `ToolEvidence` (владелец: `direct_execution.py`; consumers: L2, factcheck-стиль трассы, UR-08 telemetry)

```python
# services/turn_types.py (типы), производство — direct_execution (_l1_tool_phase → build_evidence_pack)
@dataclass
class ToolEvidence:
    search_intent: str            # required|beneficial|not_applicable (нормализовано, §2.4)
    search_called: bool
    search_status: str            # ok|empty|timeout|contradictory|unavailable|skipped_not_required
                                  # privacy_blocked — только чтение исторических событий (BGS-01: не генерируется)
    search_skip_reason: str       # машиночитаемая причина
    source_ids: tuple[str, ...]
    source_count: int
    evidence_used: bool
    sources: tuple[SourceRecord, ...]     # url/title/published_at(source tz)/snippet; ПОЛНЫЕ тексты — вне payload,
                                          # доступ по content_ref (существующий storage)
    tool_trace: tuple[ToolTraceEntry, ...]# tool/args_digest/ms/status — синхронно с _record_provider_call
```

- Производится обеими ветками через существующие `_l1_tool_subset` + `_l1_tool_phase` + `ToolRouter` (для инициативы — уже существующий вызов **13099–13102**, заменяется только источник решения: `search_intent` из `L1Plan` вместо evidence-`required`; claim-key reuse и egress-guard сохраняются).
- Caps `_SEARCH_MAX_SYMBOLS`/`QUERY_CHARS=800`/`SNIPPET=400` остаются сетевыми/безопасностными, но перестают быть смысловыми: потеря сущностей в запросе недопустима (UR-07); полный результат хранится вне payload, L2 получает отобранные фрагменты под бюджет от allocator.

### 2.4 `L1Plan` — расширение существующего (`services/direct_l1.py:227`)

Добавляются поля (остальное — action/reaction/extent/tone/form_override/response_act — без изменений):

```python
    knowledge_origin: str = ""      # conversation_only|internal_memory|open_world|mixed
    search_intent: str = ""         # required|beneficial|not_applicable
    capabilities_needed: tuple[str, ...] = ()
```

**Серверные инварианты (структурные, не словарные):**
- `knowledge_origin in {open_world, mixed}` и пустой `search_intent` → нормализация к `required` (до tool-фазы);
- явное пользовательское «проверь в интернете» не демотируется (уровень turn-нормализации фиксирует user_forced_search, executor не понижает);
- `SILENT/REACT` → tool-фаза не запускается; поиск ради отчётности запрещён;
- JSON-repair у L1 — общий маршрут (одна копия из `_plan_direct_l1`); `capabilities` в вызов передаются фактические (`resolve_capabilities`), не `()`.

### 2.5 `LLMCompletion` (владелец: `llm_client.py`)

```python
# services/llm_client.py, рядом с LLMChatResult (301)
@dataclass(frozen=True)
class LLMCompletion:
    text: str
    finish_reason: str | None     # как вернул провайдер; НЕ нормализуем неизвестное к "stop"
    model: str
    provider: str
    usage: dict | None
    max_output_tokens_sent: int | None
    attempt: int
    correlation_id: str | None
    channel: str                  # primary|fallback (из sent-трассы)
    fallback_meta: dict
```

- `generate_with_metadata(...)` — тонкая обёртка над существующим `generate_chat` (он уже отдаёт `finish_reason`) + usage/`max_output_tokens_sent`/attempt; `supervised_transport` и `fallback_payload_adapter` пробрасываются. Легаси `generate()` продолжает возвращать `str` (обратная совместимость).
- Consumer'ы: L1-executor, `_l2_write_answer`, continuation-loop (UR-19: при `finish_reason=length` — продолжение тем же планом/источниками до отправки, bounded attempts/time, `incomplete_generation` + честный fallback при невозможности), supervised summary path.
- Инициативный `max_tokens=700` и его egress-rewrite-копия (**13149/13176**) удаляются; output рассчитывается от реального окна модели + `response_plan.extent` (существующий `response_extent`).

### 2.6 Карта владения и слияния (Direct/Initiative → один engine)

| Модуль | UR-A | UR-B | UR-C | UR-D | UR-E | Time/tz |
|---|---|---|---|---|---|---|
| `turn_types.py` (новый) | **W** | R | R | R | R | R |
| `direct_l1.py` (L1Plan, build_l1_context, budget) | **W** | R | R | R | — | R |
| `direct_chat_service.py` (handle/handle_initiative/_execute_turn/L1-вызов/L2) | **W** | W (tool-вызовы) | W (selection assembly) | W (L2/continuation) | W (style-сборка) | W (attach) |
| `direct_execution.py`/`tool_router.py`/`search_*` | R | **W** | R | R | — | R |
| `direct_context_composer.py`/`summary_memory.py`/`mca_retrieval_context.py` | R | R | **W** | R | R | R |
| `llm_client.py` | R | R | — | **W** | — | R |
| `style_policy.py`/`negative_constraints.py`/`prompt_composer.py` | — | — | — | R | **W** | — |
| `bot_output_ledger.py`/`thread_chain.py`/`database.py` | — | — | **W** (read-path, additive DDL) | — | — | — |
| `chat_clock.py` (новый)/`canonical_context.py`/`chat_params.py` | — | — | — | — | — | **W** |
| `summary_scheduler.py`/`goodmorning_scheduler.py` | — | — | — | — | — | **W** |
| `web/app.js`, `web/index.html`, `web/static/app.css` | — | — | — | — | — | — (только UR-F, после CMV-D/E) |

`W` = пишет, `R` = читает. `direct_chat_service.py` — сериализуемая точка: пакеты UR-A→B→C→D→E ведутся одной линией с попакетными merge (см. §6).

---

## 3. ChatClock / TimeSnapshot — единое время чата (UR-24/25/26)

### 3.1 Контракт

```python
# services/chat_clock.py (новый модуль, один, без второго резолвера)
@dataclass(frozen=True)
class TimeSnapshot:
    as_of_utc: datetime        # aware, server clock (инъекция clock для тестов)
    local_datetime: datetime   # aware, fold-корректный
    weekday: str
    timezone: str              # IANA ID; fixed-offset «UTC+5» не подменяет IANA
    utc_offset: str            # "+05:45"
    timezone_source: str       # chat | global | factory | legacy_migrated
    config_version: str

def resolve_chat_timezone(chat_id) -> tuple[str, str, str]:
    """(iana, source, config_version). Каноническая цепочка UR-24:
    per-chat limits.chat_timezone → per-chat legacy limits.summary_timezone
    → global limits.chat_timezone → global legacy limits.summary_timezone
    → GOODMORNING_TZ (только если НИ одно поле не задано явно; env-дефолт
    не считается осознанным override) → factory default.
    Резолв через get_chat_param_sourced (chat_params.py:704) + отдельный
    read legacy-ключей с пометкой legacy_migrated; конфликт логируется
    одноразово (не скрытый сброс). "" = наследование, не зона."""

def snapshot(chat_id, *, at_utc=None, clock=None) -> TimeSnapshot
def render_chat_time_context(snap, *, phase: str, source_label: str | None = None) -> str
    # ЕДИНСТВЕННЫЙ блок <Chat_Time_Context> (user/data-content, НЕ system — prompt-cache),
    # метки: «время чата на момент планирования/ответа», при наличии — «время источника» отдельным полем.
def attach_time_context(messages, snap, *, phase) -> list
    # ОДИН helper на уровне сборки стадий; НЕ в llm_client.generate (UR-26 запрещает).
```

- **DST/fold:** `ZoneInfo` на конкретный UTC-instant; несуществующее локальное время (spring gap) → перенос на первый валидный instant того же календарного дня (явное правило, не `replace(tzinfo=...)`); неоднозначное (fall fold) → `fold=0` (раннее появление) + offset в блоке. Никогда не менять epoch-хранение и историю (UR-24).
- **Кэш:** `(chat_id, config_version)` → tz; сброс через существующий `chat_params` invalidate (`invalidate_chat`, chat_params.py:248) и notify-hook сохранения. In-flight ход остаётся на своём snapshot; новые — новый пояс.
- **Бюджет:** блок входит в composer как protected P0-строка — не выкидывается как «стилистика»; при физической нехватке — честная capacity error, а не вызов LLM с противоречивыми часами.
- **tzdata отсутствует:** конфигурационная ошибка в диагностике + явная деградация в UTC (`timezone_source="utc_fallback"`), не молчаливая подмена.
- **Миграция UI:** из рабочего UI убираются `SUMMARY_TIMEZONE` (1644) и `CHAT_TIMEZONE` (1649) и select из 12 зон (3197); legacy-ключи read-only; legacy API write → понятный отказ с указанием нового поля (не ложный успех). Добавitive поле одно: `Модули → Время` для выбранного чата (UR-29).

### 3.2 Точки инъекции (полный список UR-26 → snapshot-фаза)

| Контур | Call-site (HEAD) | Phase |
|---|---|---|
| Direct L1 planner | `_plan_direct_l1` → `build_messages` (5834–6001) | plan (turn_started) |
| Direct tool orchestrator | `direct_execution` сборка orchestrator payload (808+, 870+) | plan (reuse snapshot L1) |
| Direct L2 Writer | `_l2_write_answer` (7406) | **answer** (answer_as_of_utc перед сборкой финального текста) |
| Direct repair/continuation/fallback | continuation-loop UR-D + `verbalize_validated`-пути (7656/7897) | answer |
| Direct legacy answer path | `_chat_time_line` (8041) заменяется на `render_chat_time_context` | answer |
| Initiative Observer | `initiative_observer` 2149 (`skipped_digest`), 2185 (`opportunity_eval`) | plan (там, где от времени зависит уместность) |
| Initiative L1 | `plan_initiative_decision` (12735) | plan |
| Initiative tool-фаза | `generate_initiative_reply` → `_l1_tool_phase` (13099–13102) | plan |
| Initiative L2 | `generate_initiative_reply` → `_l2_write_answer` (13149) | answer |
| Initiative recheck | SendRecheck-контур `handle_initiative` (13712+) | answer (re-snapshot при пересечении полуночи/изменении даты) |
| Factcheck single/tool-loop/stage1/stage2 | `factcheck_service` 1874/1892/1947/2017 | plan (время оценки); `prepared_text` Nostalgia НЕ получает вымышленное время |
| Factcheck temporal verdict/validator/verbalize | 2320/2362/2681 | answer; **время публикации источника — отдельное поле в своём поясе, ChatClock его не подменяет** (UR-27) |
| Summary L1 clusterizer | `summary_l1_clusterizer.py:1298` | plan (один snapshot на логическую стадию/версию прогона) |
| Summary L2 writer | `summary_l2_writer.py:1388` | answer |
| Summary reviewer/repair | `summary_l2_review.py`, `summary_l2_repair.py`, `summary_quote_repair.py` | answer |
| Summary legacy/hybrid + supervisor + fallback | `summary_generator.py:4096–4104`, `summary_llm_supervisor.py:535` | answer (attach до supervised transport; при provider-switch блок сохраняется в payload) |
| Summary manual/test-run/cron | `summary_test_run.py`, scheduler-запуски | plan + answer; `summary_window_end_utc` не меняется задним числом; отложенная генерация → новое `answer_as_of_utc` явно |
| Goodmorning | slot-вычисление `goodmorning_scheduler` (§4); медиа/caption — не LLM-речевые, TimeContext не обязателен | scheduler-side |
| **НЕ подключать** | embedding (`llm_client.embed`), классификаторы без пользовательской речи, DB-команды, meta/сервисы | — |

Правило: один snapshot на логическую стадию; L2 получает свежий `answer_as_of_utc` только если tool-цепочка/долгая генерация пересекла минуту/полночь — иначе reuse plan-snapshot с явной меткой. `SILENT/REACT` без L2 — их L1 видит часы (plan).

### 3.3 Наблюдаемость и тесты

- На каждом фактическом модельном вызове логируются `stage, chat_id, timezone, as_of_utc, config_version, clock_included, skip_reason` — расширение полей существующих provider-call событий (`_record_provider_call`, llm_client.py:517–566), без приватных текстов.
- **Механизм «финальный outbound payload» уже существует**: `_record_sent_call` записывает фактический body (`messages`, model, channel primary/fallback). Тесты UR-26/UR-30 читают именно эти события (или monkeypatch `llm_client._post`) на **каждом** call-site из §3.2 — включая supervised summary path и fallback — и утверждают: блок `<Chat_Time_Context>` присутствует, привязан к правильному `chat_id`, не обрезан бюджетом; отсутствие `clock_included=true` без документированного невидимого режима = провал.
- Frozen-clock тесты: `Europe/Warsaw` зима/лето, `Europe/Berlin` DST spring/fall, `Asia/Kathmandu` +05:45, `Pacific/Auckland` смена суток, UTC; соседние чаты с разными поясами и одинаковым instant → разные правильные local date/weekday; смена зоны посреди хода; невозможное/неоднозначное локальное время; invalid IANA; отсутствие tzdata; legacy overrides.

---

## 4. Per-chat планирование саммари и goodmorning (UR-28)

Дизайн (один планировщик, без второго scheduler и без нового агента):

1. **Механизм:** в `summary_scheduler` один глобальный cron `hour="0,6,12,18"` заменяется на **один** лёгкий тикер APScheduler (interval 60 c, `max_instances=1`, `coalesce=True` — семантика сохраняется) + per-chat вычисление due-слотов: для каждого чата с `summary_effective_enabled(chat_id)` резолвер ChatClock даёт ближайшие локальные 00/06/12/18 как UTC-инстанты (`next_due_at_utc`), frequency и все gates не меняются.
2. **Claim-ключ (аддитивная таблица `slot_claims`, SQLite `INSERT ... ON CONFLICT DO NOTHING` / PG `ON CONFLICT`):** `kind ("summary"|"goodmorning") + chat_id + local_schedule_date (ISO в поясе чата) + local_slot ("00"|"06"|"12"|"18") + slot_utc_instant + schedule_config_version`. Атомарный claim до запуска; повторный тик/рестарт/конкурентный worker дубль не создают.
3. **DST:** несуществующее локальное время (gap) → запуск на первый валидный instant того же календарного дня; повторяющееся (fold) → один запуск на слот на более раннем появлении (claim по `local_date+slot`, не по instant — второй instant пропускается).
4. **Coalescing простоя:** на тикере просроченный слот запускается один раз, пока попадает в существующее окно pregen-deadline политики; иначе честный `skip` с `reason_code="missed_slot_expired"`; уже покрытый период не пересказывается (существующий coverage ledger остаётся источником истины по сообщениям).
5. **Смена пояса:** пересчитываются только будущие слоты; активный run не трогается; `config_version` в claim-ключе исключает ложные skip/suppress после смены; прошедшее не перепубликуется.
6. **Goodmorning:** `GOODMORNING_TIME` остаётся часом рассылки; пояс берётся **только** из ChatClock чата (§3.1 цепочка миграции уже поглощает `GOODMORNING_TZ`); тот же claim-механизм (`kind="goodmorning"`); `target_chat_ids`, per-chat gate, «нет target → старт False», dedup сохраняются; редактор `GOODMORNING_TZ` из UI убирается (param_catalog 2195 → legacy).
7. **UI:** «Следующий запуск» = `next_due(chat_id)` от того же резолвера; отдельной «зоны саммари» не появляется (UR-28/UR-29).
8. **Запрет параллелизма:** старый глобальный cron после переключения не остаётся активным (replace_existing + удаление старой job-регистрации; один owner слота — тикер).

---

## 5. Единая история собственных реплик (UR-23) и снятие стилевых якорей (UR-14)

**Read-path (один):** сборщик `ContextSelection` строит хронологию из `get_window_messages` (кандидатный хвост людей) **plus** `mca_bot_outputs` (durable ledger: chat-scoped, `delivery_status=ok`, актуальная ревизия, `sent_at`, `parent_message_ref`, `correlation_id`, `tg_message_id`) — merge по времени; bot-строки → `ContextFragment(kind="bot_statement", speaker_uid=bot_id, source_id="bot_output:<id>")`; reply-граф бот-ходов — через существующий механизм `thread_chain` (он уже читает ledger после истечения TTL bot_replies — thread_chain.py:335–336). Старые собственные сообщения — SQL-выборка по ledger по ID/дате + лёгковесный текстовый поиск; **никаких** новых эмбеддинг-индексов, LLM-агентов, семантической памяти.

**Write-path (полнота):** запись в ledger после подтверждённой отправки на всех пользовательских send-путях (Direct — уже пишет; goodmorning — уже пишет; проверить и дополнить Summary/Factcheck и multicast-маршруты). Многочастные ответы — один `correlation_id` + порядок чанков; частичная доставка — честный per-chunk `delivery_status`; правки — новая ревизия без разрушения истории; полный текст восстанавливаем по `content_ref` (существующий storage), `[:20000]`-preview не единственный источник.

**Снятие стилевых якорей без потери истории:** `_build_style_anchors` (11279) и её вызовы убираются из активной сборки Direct/Initiative; инструкций «подражай» больше нет; bot-реплики **остаются** в `thread`/`self_outputs` как обычные фрагменты диалога. `CHAT_STYLE_ANCHORS_ENABLED/COUNT/MAX_CHARS`, `CHAT_BUDGET_ANCHORS_RATIO` → legacy/read-only (param_catalog помечается, из рабочего UI убираются). Промпты владельца («Речь и характер», библиотеки примеров) и prompt-versioning (PVR: `declare_prompt`/revision/seal) не трогаются; новые машинные шаблоны регистрируются в том же версионном контроле.

**Авторитет:** `bot_statement` подтверждает только «бот это говорил», не истинность; шутка про «4 утра» не становится временем; пользовательские поправки не стирают факт прошлой ошибки (запись + актуальная ревизия при исправлении текста). Scope всех выборок — `chat_id`; self ID проверяется; старые/пустые/media-only/удалённые/повторные строки обрабатываются; при неизвестной истории бот не притворяется помнящим.

---

## 6. Параллельная безопасность и порядок пакетов

**Классификация:**

- `PARALLEL_SAFE` (backend, старт сейчас): `services/**`, `config/settings.py`, `tests/**` — не пересекаются с активной CMV-D/E линией.
- `SERIALIZE` (общая точка): `services/direct_chat_service.py` — пишется линией UR-A→B→C→D→E по очереди (попакетные merge, §2.6).
- `BLOCKED_BY:CMV-D/E-merge` (web): `web/app.js`, `web/index.html`, `web/static/app.css` — **только UR-F и только после слияния CMV-D/E**. Backend-API для UR-F (effective-config endpoint, turn-inspector данные, время) готовится параллельно в backend-роутах — конфликтов с web-файлами нет.
- `READ_ONLY_PARALLEL`: тесты и планы.

**Порядок пакетов и контрольные точки:**

1. **UR-A** — `turn_types.py` (фриз контрактов TurnRequest/ContextSelection/ToolEvidence), общий L1-вход (`plan_initiative_decision` → общий planner, capabilities реальные), адаптеры handle/handle_initiative → `_execute_turn`. Delivery не меняется. **Checkpoint-1: контракты сфризены** — после него Time-lane и UR-B/C/D могут расходиться по файлам.
2. **ChatClock/timezone backend** (UR-24/25/26 без UI) — параллельная линия после Checkpoint-1; точки интеграции — stage-assembly из §3.2.
3. **UR-B** — tool-фаза/search-first: ось `search_intent` в L1Plan, унификация инициативной tool-фазы (13099–13102) на общий policy, целевой query builder (BGS-01: без обязательной обезлички и без privacy-вето; секреты/телефоны/e-mail/полный чат не экспортируются), честная трасса UR-08. Зависит от UR-A.
4. **UR-C** — ContextSelection production (полный Current Question, reply-цепи, retrieval, self-output read-path, running summary условия по watermark, Dynamic stage budget единственным путём). Зависит от UR-A; с UR-B не пересекается по файлам.
5. **UR-D** — LLMCompletion + continuation + снятие 700/4096/16384 semantic-капов. Зависит от UR-A; `llm_client.py` — отдельный файл, может идти параллельно UR-B/C.
6. **UR-E** — speech: снять автостиль, один deterministic style-pass, mood-hint → контекстный тон, diagnostic-only клише. После UR-D.
7. **UR-F** — UI (после CMV-D/E). **Checkpoint-final.**
8. **UR-G** — независимое ревью/E2E — непрерывно на каждом checkpoint + финально.

**Минимальные merge-точки:** CP1 (UR-A+контракты) → CP2 (Time-lane + UR-B) → CP3 (UR-C+UR-D) → CP4 (UR-E) → CP5 (UR-F после CMV-D/E) → release. Rollback: старый путь за короткоживущим флагом с документированным удалением после приёмки (UR-10 §10 ТЗ).

---

## 7. Риски и фальсифицируемые инварианты Reviewer

### 7.1 Риски (R0 — недопустимо сломать)

- **R0 Адресация/атрибуция:** merge ledger-строк в окно не должен перепутать `speaker_uid`/алиасы/reply-edges (RC v5 speech-projection manifest сохраняется). *Инвариант:* в fixture «диалог.txt» правильный `target_user_id` во всех репликах; бот-фрагменты имеют `speaker_uid=bot_id` и свой label.
- **R0 Поисковый payload и секреты (BGS-01):** запрос к поисковику не содержит `user_id`/`tg_id`, API-ключей/токенов, телефонов, e-mail, приватных ссылок и полного дампа переписки. Приватность темы или участие человека в разговоре **не** являются причиной отказа: `privacy_blocked` не генерируется, недоступность инструмента даёт техническую причину. *Инвариант:* payload `execute_web_search` на fixture «разговор с участником чата» содержит целевой запрос и не содержит запрещённых токенов; следов `privacy_blocked` в новых трассах нет.
- **R1 Timezone/DST:** сдвиги зон, half-hour пояса, fold/gap, смена зоны посреди хода. *Инварианты:* §3.3 тест-матрица; slot-claim уникальность; после рестарта/смены зоны нет повторной публикации.
- **R1 Самоподражание/авторитет:** bot_statement не попадает в стилевые инструкции и не повышает фактологическую достоверность. *Инвариант:* в payload L2 нет `<style_anchors>` при выключенных anchors и нет «подражай»-инструкций; «4 утра» из шутки не становится ответом «сейчас 4 утра».
- **R2 Обрывы/continuation:** `finish_reason=length` не публикуется; continuation не меняет адресата/план;bounded attempts. *Инвариант:* payload-capture: ни один отправленный текст не заканчивается серединой слова при length; `incomplete_generation` трассируется.
- **R2 Двойное усечение:** только allocator режет. *Инвариант:* grep-аудит смыслового пути: `[:800]`, `render_window_lines(window, 12)`, `max_tokens=700` отсутствуют в активных маршрутах; L1 получает full current question.
- **R3 Prompt/version integrity:** PVR-пакет (journal/seal/baseline) не обходится; TimeContext не попадает в кешируемый system-префикс и не дублируется по слоям. *Инвариант:* новые машинные блоки зарегистрированы `declare_prompt`; seal_integrity не нарушен; в payload блок `<Chat_Time_Context>` встречается ровно один раз на стадию.
- **R3 Scheduler-дубли:** два worker/рестарт/смена зоны. *Инвариант:* §4 claim-ключ; интеграционный тест двух конкурентов на один слот.

### 7.2 Честные ограничения контракта

- Live-инспекция отрендеренного UI (Playwright/Browser Use) для UR-F **откладывается на старт UR-F**: web-файлы сейчас во владении CMV-D/E; съёмка экранов сейчас зафиксировала бы чужое промежуточное состояние. Visual contract для UR-F (три экрана «Как бот отвечает» / «Что бот видел» / «Доп. настройки», «Модули → Время») строится на кодовых якорях §1.1 (param_catalog 1644/1649/2195/3197, группы каталога) и обязана включать live-inspection + Visual Neighborhood Sweep на CP5 до merge.
- Оценка «+30% интеллекта» и процентные acceptance-числа UR-08 (100%/95%) — продуктовые ориентиры владельца; инженерно проверяются через размеченный сценарный набор и трассу `search_called/search_status/source_count`, а не через invented-метрики.
- URL/внешние факты в этом документе не использовались: все якоря — из кода HEAD.

### 7.3 Что уже сделано на HEAD (не переделывать)

`LLMChatResult.finish_reason`; model-aware L1 budget (оба режима); tool-фаза и evidence-pack инициативы; общий `_l2_write_answer`; ledger→thread_chain restore; ER-08 full-text Writer; running summary read-семантика TTL; Dynamic policy в `auto_budget`; sourced config-геттер; speech projection. Контракт опирается на них и достраивает, а не заменяет.

### 7.4 Поправка BGS-01/BGS-04 (решение владельца 2026-11-05)

Позднее продуктовое решение владельца (`plans/owner_inputs/2026-11-05-behavior-gates-simplification.md`, §0.1, §2, §5, §8) снимает privacy-вето на веб-поиск и ограничивает смысловую постцензуру. Что это меняет в настоящем контракте:

- `privacy_ok`/`BLOCK_PRIVACY`/`privacy_blocked` больше **не** критерий отказа для `web_search`/`fetch_url` и иных внешних read-only инструментов; значение `privacy_blocked` в `search_status` читается только для исторических событий. Замена на другой «мягкий» классификатор приватности (`query_not_public`, `private_chat_claim`) запрещена.
- §2.3 (`ToolEvidence`) и §6.3 (UR-B) сохраняют `ToolEvidence`, `search_intent`, трассу источников; меняется только правило построения запроса — целевая задача по смыслу, без обязательной privacy-перепаковки.
- Технические границы неизменны: RBAC/права чата, `flags.search_enabled`, явное «не ищи в интернете», `SafeFetcher`/SSRF, rate limit/стоимость провайдера, отсутствие имитации поиска.
- §7.1 R0 переформулирован: проверяется реальный payload (нет UID, ключей, телефонов, e-mail, полного чата), а не «приватность темы».
- UR-15/UR-15.2 уточнены BGS-04: обязательные Form/Numeric/Format-проверки применяются к реальным трансформациям и протокольным ошибкам, а не к свободной генерации.
