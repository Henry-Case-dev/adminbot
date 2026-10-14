# ASAP 7 — Phase 0 / Forensic-аудит Direct Chat pipeline (lane P7-A)

- Дата: 2026-10-09. HEAD: `08a88496cd6b0b5a32193776063edbe320c837f4` (master).
- Scope: только Direct Chat (Workstream A/B + Direct-пункты CLAIM→REALITY). Модули/multi-chat/Cover — другие лейны.
- Источник требований: `plans/current_task.md` ASAP 7 (строки 31769–33788), §1.1–1.3, §2, §3, §15 (Golden D1–D15), §18, §20–§23, §25.
- Прод-сверка: только разрешённый HTTP `GET /healthz` → `HTTP 200 {"status":"ok","version":"2.58.71"}` (SSH не трогался, fail2ban-режим соблюдён).
- Baseline-шум (не чинил, не оценивал): незакоммиченные правки `services/disk_retention.py`, `plans/MEMORY.md`, `plans/backlog.md`, `plans/workflow_state.md`, `plans/runtime_task.md`, архивный evidence, untracked `node_modules/`, `.playwright-mcp/`, `package*.json`, `AGENTS.md`. Это WIP параллельных сессий, к Direct не относится.

---

## 1. Вердикты по гипотезам

### H1 — MCA-23 planning = hardcode-классификатор → **ПОДТВЕРЖДЕНА (TRUE)**

Всё «планирование» MCA-23 — детерминированный regex/keyword-слой, 0 LLM-вызовов, построенный ДО любого смыслового LLM-понимания сообщения:

| Элемент | Где | Факт |
|---|---|---|
| `classify_request` | `services/response_extent.py:270-363` | 0 LLM. `task_kind` по ~12 regex-семействам (`_CREATIVE_RE:219`, `_EXPLAIN_RE:222`, `_RESEARCH_RE:228`, `_MEDIA_DL_RE:237` и др.); extent по таблице `_EXTENT_OF_TASK:257-267`; «3 слова + ?» → `micro` (:336-343); `direct_answer` + «да/нет» → `micro` (:345-347, `_YESNO_RE:253`) |
| Скрытое ограничение social_chat→compact | `response_extent.py:349-353` | «болтовня» без маркеров принудительно `extent=compact` — ровно то, что запрещает §22 п.8 |
| Явная форма | `response_extent.py:215-218, 324-330` | deterministic override — это разрешено §3 (оставить deterministic для явных вещей) |
| `build_tool_plan` | `response_extent.py:483-543` | активация ТОЛЬКО при (а) маркере `_MULTI_READ_RE:249-251` и (б) ≥2 уникальных URL (:514). «Единственный настоящий multi-tool план» = fetch_article×N + опциональный web-шаг (:516-536) |
| Clarification | `response_extent.py:548-565` | фиксированная media-only формулировка `CLARIFY_MEDIA_TARGET:548-550`, только для `media_download/transcription` |
| Delivery | `response_extent.py:355-360` | research/report → rich, media_* → media — детерминированно |
| Вызов в Direct route | `services/direct_chat_service.py:2310-2340` | `classify_request(query)` на :2315 — после пре-гейтов, ДО Stage-1 LLM-вызова (:2544). Extent-блок клеится к системному промпту :2321 |
| Вторая точка | `direct_chat_service.py:1292-1296` | `build_coordinator_decision` дублирует classify (post-tool, тот же результат) |

План строится до смыслового LLM-понимания: **да** — это единственный «планировщик» в системе; LLM о плане не знает и план не корректирует. Вердикт отчёта MCA-23 «semantic planning» по факту: **regex-классификатор + extent-шаблоны**. По §1.3: отчёт «MCA-23 phase 2 complete» → `PARTIAL`, не `VERIFIED`.

Что при этом реально хорошо (не оспаривается): kill-switch-обвязка, extent-блоки заменяют cap, scrub — реализованы аккуратно; проблема не в качестве кода, а в принципе (regex как semantic brain, §2.1–2.2).

### H2 — существующие L1/L2 = post-tool System2, НЕ pre-tool L1 Planner → **ПОДТВЕРЖДЕНА (TRUE)**

- Гейт запуска двухвызовного пути: `direct_chat_service.py:2807-2818` — требует `SYSTEM2_DIRECT_ENABLED` AND `isinstance(raw, ToolLoopResult)` AND `not raw.degraded` AND **непустой `raw.tool_trace`** AND не-lore AND (coordinator None или `action == ACTION_TOOL`) AND `media_writer_needed`. То есть **только после успешного tool-loop с реально вызванными тула́ми**.
- Обычный короткий/социальный Direct message (тулы не вызывались) → `chat_with_tools` возвращает строку, не `ToolLoopResult` → гейт ложный → **через L1→L2 не проходит** (один Stage-1 вызов, fast path §8 — по дизайну MCA-23, но это и значит, что «L1 Синтезатор» не видит 90%+ трафика).
- `_synthesize_direct_answer` (`direct_chat_service.py:3105-3295`): Stage-1 = Синтезатор («превратить выводы инструментов в JSON-справку», `chat_prompts.py:284-310`), Stage-2 = Вербализатор (`chat_prompts.py:314-349`). Это **evidence packaging → формулировка**, не decision/planning: план сюда приходит уже готовым (regex), решение REPLY/REACT/SILENT уже принято раньше.
- UI-карточки: `web/app.js:10340-10365` — `directStageCards()` строит `L1 · Синтезатор` и `L2 · Вербализатор`, **обе** биндятся на один и тот же `models.llm_model_name` и один `models.llm_base_url`. Отдельного L1 model slot не существует (`services/param_catalog.py` — только промпты-ключи synthesizer/verbalizer, моделей-слотов нет; проверка grep). Иллюзия двух независимых настроек, о которой предупреждает §2.8/L2-примечание.
- Промпты существуют и реально резолвятся: `direct_chat_service.py:3176-3177` (синтезатор), `:3195-3198` (вербализатор).

**Вывод:** существующий System2 — это post-tool Synthesizer+Verbalizer из раунда 10.22/10.23. Засчитать его как требуемый pre-tool L1 Planner (§2) нельзя. В терминах §22 п.2: «назвали старый post-tool Synthesizer новым L1» — ровно этот риск реализован в нейминге UI.

### H3 — промпт-хвосты душат extent → **ПОДТВЕРЖДЕНА ЧАСТИЧНО (cap снят, но глобальный хвост жив)**

Снятие cap «1–2 предложения» — сделано честно, несколькими слоями:
- Новый канон без cap: `services/chat_prompts.py:264-265` (`_CHAT_LIMIT_BLOCK_MCA23` — «длина определяется задачей»), сборка `CHAT_SYSTEM_PROMPT:274-275`; Вербализатор: `_VERBALIZER_EXTENT_RULE_MCA23:338-341`, `DIRECT_VERBALIZER_SYSTEM_PROMPT:347-349`.
- PG/hot-миграция: `services/prompt_migrations.py:114-133` — все 9 ступеней старых канонов (включая cap-версии) ведут на MCA23-канон; старые тексты сохранены только как PREV-слепки (по правилу «правка канона = бамп + слепок»). Дефолты промптов (`param_catalog` → `services.chat_prompts.CHAT_SYSTEM_PROMPT`) — новые.
- Runtime-scrub PG-кастома: `response_extent.py:423-460` (`strip_cap_phrases`/`scrub_for_plan`), вызовы `direct_chat_service.py:2324` (Stage-1 system) и `:3216` (verbalizer).

**Но хвост остался — и это главный конфликт:**
- `_SANDWICH_REMINDER` = `"отвечай коротко, по делу, на последний вопрос …"` (`direct_chat_service.py:347-349`), клеится **последней строкой user-контента каждого Direct-запроса безусловно** (:3636-3638, через композер тоже), и при этом входит в **неприкосновенные** kinds бюджета (`:5349`, `:5409` — не режется).
- Он не проходит через `scrub_for_plan` (scrub чистит только cap-фразы из PG-кастома и только для longform-семейства) и не зависит от плана: longform-план получает «ОЖИДАЕМАЯ ПОЛНОТА: РАЗВЁРНУТЫЙ ТЕКСТ…» в system + «отвечай коротко, по делу» в конце user. Прямое нарушение Golden **D11** («финальный prompt не содержит скрытого глобального КОРОТКО») и §22 п.9.

Проверка «глобальный cap удалён и из кода, и из PG-путей»: код — да; PG-миграции — да; effective source (default canon) — чист. Единственный оставшийся глобальный «коротко» — sandwich-хвост (см. Баги D-1).

### H4 — production acceptance MCA-23 не завершена → **ПОДТВЕРЖДЕНА (LIVE_PENDING, задним числом не закрывать)**

- `git show 08a8849` (docs, HEAD): `plans/workflow_state.md` дословно — «Golden E2E каркас A–R 18/18 (**stub**); live-сценарии — **за владельцем** в чате»; «остаток: live-acceptance фаз 2 у владельца».
- `commit 8b44669` (feat phase 2 2.58.71): «Golden E2E каркас A–R 18/18 (**live — prod acceptance**)» — т.е. сам коммит фиксирует, что live-часть не выполнена агентами.
- Прод задеплоен и жив: `/healthz` → 200, `version 2.58.71` (проверено сегодня). Деплой ≠ acceptance.
- Golden-тесты — юнит/интеграционные стабы с фейковым LLM, разнесены по файлам: `tests/test_mca23_phase2.py` (Golden E/M/I/O: :122, :231, :275, :395, :609), `tests/test_mca23_response_plan.py` (A/B/C/L-семейство). Единого «18 сценариев» harness-файла нет.

Статус: live acceptance MCA-23 фазы 2 — **owner gate, открыт**. Хвост закрыт честно (не задним числом); ASAP 7 не должен его «до-закрывать» молча.

---

## 2. Call graph текущего Direct path (file:line, LLM vs regex)

Вход: `handlers/direct_chat.py:165` `_is_direct_trigger` — OR: reply-to-bot / entities-mention (:144) / keyword `бот…` / persona-name. Далее `DirectChatService.handle` (`services/direct_chat_service.py:1790`).

| # | Шаг | Где | Тип решения |
|---|---|---|---|
| 1 | Throttle (кулдаун→фраза) | :1801-1824 | deterministic |
| 2 | Circuit breaker | :1829-1834 | deterministic |
| 3 | Per-chat concurrency lock | :1839-1848 | deterministic |
| 4 | Update-identity dedup (chat,tg_id,rev) | :1854-1874 | deterministic |
| 5 | Correction-фразы триггер (`_gprov.plan_correction`) | :1885-1890 | **regex** |
| 6 | Text dedup replay | :1910-1933 | deterministic |
| 7 | Style-scope ingest/resolve (K3) | :1946-1968 | дет. + `_decision_addressed:1601` |
| 8 | Context compose: `_build_user_content:3507` → блоки → `_compose_user_content:3895` (classification P0-P3, ADR-1028-2 D3 :3639) → `_apply_context_budget:5338` (cap `CHAT_CONTEXT_BUDGET_TOKENS`, per-chat policy; неприкосновенные: target/protected/lore/current/**sandwich** :5409) | :1969-1973 | deterministic; бюджет = токены |
| 9 | Stats-intent пре-блок (MCA-15) | :1980-2001 | **regex** (`_stats_intent_block:4881`) |
| 10 | Прe-гейты dig/image (nostalgia-маркеры, image-ключи) | :2002-2004+, `_dig_pre_gate_block:4824`, `_image_pre_gate_block:4941` | **regex** |
| 11 | **Decision Phase P** (дет.): `decision_on:2030`, `_decision_context:2076`, message-class `:1324` (**regex**), pre-action `_decision_pre_action:1353` (explicit/question/tool → REPLY) | :2030-2157 | deterministic |
| 12 | **LLM REACT** (только если pre_action=REACT и флаги): отдельный 1 вызов `self.llm.generate` с `inject_react_task` **ДО tools** | :2415-2475; `services/direct_llm_react.py:83-134` | **LLM** (fallback дет.) |
| 13 | **Decision Task** (REPLY/REACT/SILENT) инжектится в ТОТ ЖЕ payload Stage-1 | :2480-2483; `direct_llm_react.py:218-233,250-277` | **LLM**, но парсинг решения — ПОСЛЕ tool-loop (:2598-2600) |
| 14 | ResponsePlan: `classify_request` + extent-блок + scrub + `record_response_plan` (ExecutionGraph) | :2310-2340; `response_extent.py:270,405,456`; `execution_graph_source.py:870-878` | **regex** (0 LLM) |
| 15 | Clarification-гейт (media без цели → 1 фикс-вопрос, отправка, return) | :2489-2502; `response_extent.py:555-565` | deterministic (фикс-фраза) |
| 16 | Tool plan build (≥2 URL) → `chat_with_tools` (tool-loop: `services/tool_loop.py:443`, plan-исполнение `_topo_order:218`, bounded) или одиночный `llm.generate` | :2529-2568 | plan = **regex**; выбор тулов внутри цикла = **LLM** (model-driven) |
| 17 | Парсинг decision JSON из финала Stage-1; REACT → `react_moai`; **SILENT → 🗿** `_execute_silent_ack:1712` (конъюнкция silent-ack); INVALID/REPLY-без-текста → дет. fallback/тишина | :2598-2757 | **LLM**-решение + дет. fallback |
| 18 | Coordinator (0 LLM, пост-фактум): `build_coordinator_decision:1270` | :2773-2794 | deterministic |
| 19 | **System2 (пост-tool)**: гейт :2807-2818 → `_synthesize_direct_answer:3105` (2 LLM-вызова: stage1 :3180, stage2 :3235-3240) | — | **LLM** ×2 |
| 20 | Пост-обработка: strip reasoning :2834, lore-story :2838-2840, numeric guard :2845 (`services/` numeric_contract), duplicate guard + 1 regen :2879-2934 | — | deterministic (+1 LLM-реген при дубле) |
| 21 | Delivery: ResponseDocument :2973; rich-wanted :2974-2981 (план + режим + ≥400 симв. `response_extent.py:55`); `_send_direct_answer:3300` (rich :3339-3352 → fail → plain same doc :3353-3354; safe-HTML lore/deep_research :3355-3364; media — тул доставляет сам, Writer пропускается `media_writer_needed:575`) | :2965-2987 | deterministic |
| 22 | Ledger + memorize (fire-and-forget после send) | :3011-3038 | deterministic |

**Сводка «где LLM, где regex»:** LLM-решения в Direct — (а) one-shot REACT (pre-tool, узкое условие), (б) Decision Task, сплавленный с главным tool-loop вызовом (решение парсится после тулов), (в) пост-tool Синтезатор+Вербализатор (не decision), (г) model-driven выбор тулов внутри цикла. Всё «планировое» (task_kind/extent/structure/delivery/tool_policy/tool-plan/clarification/coordinator) — **regex/deterministic до LLM**.

---

## 3. Существующий Decision Maker — точный контракт (кандидат на §2.7)

- **Триггер-матрица**: `_resolve_direct_trigger` (`direct_chat_service.py:853-876`): force-keyword/persona/mention → `force_reply_required=True` (**REPLY гарантирован**, гейт ДО decision); reply_to_bot → autonomous (Decision Making); free_will в handle не попадает.
- **Phase P (дет.)**: `_decision_pre_action:1353` — priority: пре-гейт-результат → explicit → question → tool-result → …; возвращает (action, reason, reaction, target). Флаги: `DecisionToggles:901` (ignore_trivial/reactions/image_reactions, per-chat :1766).
- **LLM-линия**: `llm_decision_enabled` (`direct_llm_react.py:333-341`) = env `DIRECT_LLM_DECISION_ENABLED` (settings.py:630, объявлен) AND env + per-chat reactions-флаг. `decision_llm_pending` ставится на :2120-2125; allowed-actions формируются из demote-матрицы (:2133).
- **Контракт вывода** (`direct_llm_react.py:218-233, 287-330`): REPLY = обычный текст (не JSON); REACT = строго одна JSON-строка `{"action":"REACT","reaction":"<emoji>","reason":"…"}`; SILENT = `{"action":"SILENT","reason":"…"}`; битый JSON → sentinel `INVALID` → детерминированный fallback. Второй LLM-call ради emoji запрещён (§52).
- **Момент исполнения**: инжект до `chat_with_tools` (:2480-2483 → :2544), парсинг после (:2598-2600, скип при degraded). Т.е. единое REPLY/REACT/SILENT-решение исполняется **внутри/после tool-loop**: модель может вызвать тула и только потом «решить» SILENT — тула уже выполнена. Исключение: pre_action=REACT — отдельный pre-tool вызов (:2415).
- **Hard gates**: force → REPLY всегда; SILENT (conscious) → 🗿 через `_execute_silent_ack:1712` (per-chat silent-ack, «фон — тишина»); SILENT вне allowed → тишина; REPLY-JSON-без-текста → fallback прежней матрицы (:2732-2757).
- **Coordinator** (`build_coordinator_decision:1270-1321`, `CoordinatorDecision:1053`): 0 LLM, post-tool; intents/addressee/memory_need/evaluation/action + axes плана; используется как гейт System2 (:2812-2813) и для логов. Не decision-maker в смысле §2 — это классификатор фактов прогона.

---

## 4. CLAIM → REALITY (Direct-пункты отчёта ASAP 6 фазы 2; 8b44669 / 08a8849)

| # | CLAIM | Implementation path (evidence) | Verdict |
|---|---|---|---|
| C1 | «Удалён глобальный cap 1–2 предложения» | Канон+вербализатор без cap (`chat_prompts.py:264-265,338-349`); PG-миграционная лестница (`prompt_migrations.py:114-133`); runtime-scrub (`response_extent.py:423-460`). НО: глобальный хвост «отвечай коротко, по делу» в каждом финальном промпте (`direct_chat_service.py:347-349,3638`) и scrub только для longform | **PARTIAL** (канон чист; в effective-сборке глобальное «коротко» живёт в sandwich) |
| C2 | «Длинный creative и короткий yes/no работают» | `creative_writing→longform` (`response_extent.py:219-221,257`), `да/нет→micro` (:253,345-347); extent-блоки :368-391; max_tokens для longform (:166-182, :3224-3240); юнит-тесты `test_mca23_response_plan.py`, `test_mca23_phase2.py:437-471` | **PARTIAL** (unit-level VERIFIED; live — owner-pending;давление sandwich-хвоста на longform не проверялось live) |
| C3 | «Multi-tool за один ответ (DAG)» | Исполнитель — настоящий bounded DAG: `tool_loop.py:174-235` (normalize, topo, failure_policy, ≤6 шагов, §17-бюджеты), partial-failure fail-soft (Golden M :275). НО источник плана — только regex-случай «маркер сравнения + ≥2 URL» (`response_extent.py:483-543`, вызов `direct_chat_service.py:2529-2543`); общий multi-tool — прежний model-driven цикл, не «новый DAG» | **PARTIAL** (DAG-executor реален; semantic-DAG нет — покрытие ≈ 2+ URL, что прямо названо запрещённым в §22 п.10 как конечное состояние) |
| C4 | «Rich/plain same-content fallback» | `ResponseDocument` (`services/response_document.py`), `_send_direct_answer:3330-3354` — plain и rich рендерят один документ, Rich fail → `plain_text()` того же документа, без регенерации; тест `test_golden_o_rich_fail_plain_same_document` (`test_mca23_phase2.py:609`) | **PARTIAL** (код+тесты VERIFIED; live-падение rich на проде никем не воспроизводилось → runtime-часть LIVE_PENDING) |
| C5 | «Один clarification» | Гейт `direct_chat_service.py:2489-2502` — ровно один фикс-вопрос за turn, после — return (0 LLM); `clarification_question:555-565`; тесты :550-577 | **VERIFIED** (как заявлено: один). Оговорка: формулировка фиксированная media-only — это fallback-семантика, не контекстная (§3.2 целевое) |
| C6 | «Plan → Fact в Analytics» | Запись плана `:2333-2340` → `execution_graph_source.py:629-878` (planned-vs-actual, 4 исхода) → `web/api/analytics.py:301` `/analytics/execution/latest` → виджет «План → Факт» (`web/index.html:4504-4548`, `web/app.js:1817-1830,5387-5420`). НО: хранилище in-memory, maxlen=20 прогонов, TTL ~15 мин (`execution_graph_source.py:170-198,1126`); «24ч/7д» агрегируется по тому же окну (докстринг :1126 честно: durable-слой §35 «не реализован — UI агрегирует по snapshot-ам»); рестарт процесса стирает всё; planned-слой = axes regex-плана, не L1-плана | **PARTIAL** (виджет реален и рисует честное сравнение; «24ч/7д» фактически ~15-минутное окно; истории нет) |
| C7 | «Golden E2E A–R 18/18 (stub), live — за владельцем» | Зафиксировано в самом HEAD `08a8849` (workflow_state: «stub», «live-сценарии — за владельцем»); стаб-тесты рассеяны по `test_mca23_phase2.py`/`test_mca23_response_plan.py` | **VERIFIED** (как заявлено — честный stub; live = LIVE_PENDING/owner gate) |

Дополнительные заявления отчёта вне Direct (embeddings v34, help sync, pytest 12670+, production 2.58.71) — вне моего лейна; прод-версия 2.58.71 подтверждена `/healthz`.

---

## 5. Подтверждённые баги/разрывы (приоритеты)

### D-1 · P1 — `_SANDWICH_REMINDER` = глобальное «отвечай коротко» в каждом финальном промпте
`direct_chat_service.py:347-349`, аппенд :3638 (и через композер), неприкосновенен в бюджете :5409, не проходит plan-aware scrub. Ломает Golden D11 и §22 п.9; сводит на нет extent longform (последняя строка промпта сильнее среднего блока). **Ложится на F1** (новый L1/extent-контракт обязан заменить хвост на plan-aware формулировку или удалить).
TEST-LIFECYCLE кандидат: CONTRACT на «финальный prompt longform-плана не содержит глобального КОРОТКО».

### D-2 · P1 — Заявленные env kill-switch-ы Direct-планов мёртвые (rollback-путь не работает)
`DIRECT_RESPONSE_PLAN_ENABLED`, `DIRECT_TOOL_PLAN_ENABLED`, `DIRECT_RICH_DELIVERY_ENABLED`, `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS` читаются как `getattr(settings, …, default)` (`response_extent.py:133-182`), но **не объявлены** в `config/settings.py` (проверено импортом: все четыре → `<ABSENT>`; у `Settings` нет `__getattr__`, :180/@dataclass(frozen):179). Итог: env не влияет, дефолты зашиты; заявленный в 8b44669 soft-откат `DIRECT_TOOL_PLAN_ENABLED=false` невозможен через env. Тесты зелёные, потому что патчат инстанс (`object.__setattr__`). **Ложится на F2** (settings/slot-инфраструктура) — декларировать поля или перевести на существующий hot/каталог-механизм.

### D-3 · P1 — Decision Task сплавлен с tool-loop: решение парсится после выполнения тулов
:2480-2483 (инжект) vs :2598-2600 (парсинг). Возможен «SILENT после платных вызовов»; для unified L1 (§2) это анти-паттерн: решение должно быть pre-tool. Не «сломанный behavior», а архитектурный разрыв, который обязан разрешить Architect (§2.7) — см. вопросы. **Ложится на F1**.

### D-4 · P2 — Analytics «24ч/7д» окна фактически ~15-20 последних прогонов in-memory
`execution_graph_source.py:170-198,1126`; рестарт/мультипроцесс = слепые зоны; §35 durable-периоды не реализованы (докстринг это признаёт). Честность UI: переключатель есть, данных за период нет. **Ложится на F2** (analytics).

### D-5 · P2 — UI «L1/L2» вводит в заблуждение (одна модель на обе карточки)
`web/app.js:10359-10364` — обе карточки на `models.llm_model_name`; отдельного L1 slot нет. §2.8 требует честный inheritance или настоящий слот. **Ложится на F2**.

### D-6 · P2 (принято как известное, фиксирует H1) — regex-классификатор = primary semantic brain
`response_extent.py:270-363` + вызов :2315. Целевое устранение — сам Workstream A/F1; до тех пор `social_chat→compact`, «3 слова+?→micro» и т.д. остаются активными.

Baseline-шум (`services/disk_retention.py` и планы) — не баг Direct, не тронут.

---

## 6. Вопросы для Architect (реальные развилки)

1. **§2.7 — как именно расширять Decision Maker до pre-tool L1.** Два жизнеспособных варианта, ТЗ допускает оба («переиспользовать как новый L1» vs «детерминированный evidence packaging / удалить»):
   - (a) Единый Stage-1 = расширенный Decision Task: L1-JSON (action/response_act/extent/tone/capabilities…) + tool-call phase + reply — но тогда либо решение всё равно парсится после тулов (текущий дефект D-3), либо нужен structured first-phase (например, отдельный короткий pre-tool вызов L1, а Stage-1 становится чистым L2 Writer с тулами между ними = 2 semantic LLM call — это соответствует «Desired call topology» §2.7);
   - (b) Отдельный лёгкий L1 Planner call (§2.9-бюджет, свой model slot) → deterministic capability-мэппинг → tool-loop → L2 Writer (= переименованный/упрощённый Вербализатор), старый Синтезатор → deterministic evidence packaging (он и сейчас почти детерминированный форматтер JSON).
   Ключевое ограничение: не получить 3-4 semantic call (§22 п.3) и сохранить force/SILENT-контракты. Решение влияет на F1-слайс.
2. **Судьба Синтезатора** в выбранном варианте: оставлять 2-вызовный post-tool путь как «rich evidence mode» параллельно новому L1, или консолидировать (риск третьего semantic call — см. §2.7 «не оставлять третий call из страха»). Требует явного решения, т.к. влияет на бюджет вызовов и на UI-карточки (D-5).
3. **Durable-слой planned-vs-actual** (D-4): писать ли план/факт-исходы в уже существующие durable-события (`llm_usage_events`/agentic) для честных 24ч/7д (§18/§35), или переименовать окна в UI. Это продуктовое обещание Analytics, не чистая реализация.

Не выносится владельцу: выбор модели L1 по умолчанию (inherit main определён §2.8), способ хранения kill-switch-ей (D-2 — инженерное исправление в рамках F2), формулировки extent-блоков.

---

## 7. Статус по Golden D1–D15 (сегодняшний код, статически)

- D11 («финальный prompt не содержит скрытого глобального КОРОТКО») — **FAIL сегодня** (D-1).
- D1/D2/D3/D12 — частично покрыты regex-семантикой (extent существует), но «L1 понимает referent из контекста» (D1) **не выполняется** — короткое «а этот?» классифицируется по длине в micro (response_extent.py:336-343), без семантики. Это ядро Workstream A.
- D4/D5/D6 (aggression/banter как semantic outcome) — инфраструктуры нет (нет response_act/tone в решении; Decision Task умеет только REPLY-текст/REACT-emoji/SILENT).
- D7/D8 (semantic capabilities без 2-URL) — не выполняется: план только 2+URL (H1).
- D9/D10 — выполняются в фикс-фразной форме (C5).
- D13/D14/D15 — целевые контракты нового L1; сегодня аналоги: decision JSON INVALID→fallback (есть), L1-model-failure — N/A (нет L1 slot).

---

*Аудит подготовлен lane P7-A. Только чтение репозитория; записан единственный файл — этот. Полный pytest не запускался (по ограничениям); выполнен один узкий статический probe (`config.settings` import + getattr — вывод в §5 D-2) и один разрешённый HTTP `/healthz`.*
