# ADR-1028-2 — Direct Context Composer (model-aware budget) + Decision Addressing Matrix (ASAP-3)

**Статус:** Accepted (design-фаза `mca-asap3-direct-context-reply-reliability`, раунд 1028, ASAP-трек).
**Scope контракта:** только consumer-side Direct Chat (§0 ТЗ). Summary-пайплайн, free-will фона, WIP-волны MCA — вне контракта.
**Спека-компаньон:** `plans/features/mca-asap3-direct-context-reply-reliability/spec.md`.
**Версия:** 2.58.34 → 2.58.35 (per-feature bump, D16).

## Контекст (факты кода, HEAD 2.58.34)

1. Prod-инцидент §1: `limits.chat_global_context_max_tokens=-1` → `resolve_context_tokens(-1)` возвращает `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (settings.py:517, default 32000) → `safe_budget(32000)=32000/1.15≈27826` (`services/token_counter.py:207-230`; `TOKEN_SAFETY_MULTIPLIER`, settings.py:1641) → WARN `direct: global context truncated | tokens=39371 -> 27826` (`services/direct_chat_service.py:3775-3778`). Аналогично thread (`:3855-3902`).
2. При aggregate `-1` adaptive accounting пропускается целиком (`_apply_context_budget`, `:2802-2811` — ранний return до accounting, §5 ТЗ).
3. Двойное независимое усечение: per-block self-truncation в `_build_global_context`/`_render_thread` + share-доли aggregate (`:2850-2946`); диагностика `_check_context_config_invariant` (`:2203-2257`) причину не устраняет.
4. Decision layer A7 (`ADR-1026-20`): `_decision_pre_action` (`:932-1003`) не имеет force-гейта («бот, ок» → MSG_ACK → ignore_trivial → ACTION_SILENT); `DecisionContext.bot_replied_recently = reply_to_bot` (`:1233` — нарушение §23); ACTION_SILENT = тишина без 🗿 (`:1435-1445`); реакции A8 — закрытая карта `_REACTION_BY_REASON` (`:617-622`, {😂,👍,🔥} + 🗿-fallback) поверх 15-кода `REASON_CODES` (`:604-610`).
5. Смерженные REUSE-слои: `services/mca_retrieval_context.py` (единый retrieval-контракт mca-07: каналы exact/lexical/vector/episode, `RETRIEVAL_POLICY_VERSION`, `EvidenceBundle`), `services/thread_chain.py` (ADR-1023-2), `_estimate_external_payload_tokens` (`:1892-1954`, MCA-07 full-payload оценка), protected spans в `_truncate_block` (`:2991-3007`), `react_moai` (A8, 7-исходный enum), `emit_agentic_event` (A9, закрытый enum 20 типов, гейт `AGENTIC_EVENTS_ENABLED`).
6. Каталог: базлайн после ASAP-2.1 — F8 **481/105/103/21** (REGISTRY/GROUPS/_TAB_BY_GROUP/TAB_RULES; полная шестёрка 481/422/456/105/103/21 — арифметика §101-ASAP-2 «489/430/464/107/105/21» минус ASAP-2.1 «−8 ключей/−2 группы»).
7. Прецедент ceiling-решения, который мы сужаем: ADR-1019-8 (F4) ввёл «-1 → потолок 32000» для всего семейства контекст-лимитов. Настоящий ADR **SUPERSEDE ADR-1019-8 на ON-пути Direct**; для Summary и OFF-пути семантика ADR-1019-8 сохраняется (граница §0).

## Решения

### D1 (§49 Q1) — источник физического окна модели
Новый нейтральный модуль `services/model_capacity.py` (потребитель — Direct; Summary не импортирует):
`resolve_model_context_window(model_name) -> (window, window_source)`; `window_source ∈ {model_map, env_override, unknown_fallback}`; карта известных моделей + env `CHAT_MODEL_CONTEXT_WINDOW` (принудительный override) + env `CHAT_UNKNOWN_MODEL_WINDOW` (default **16384**, консервативный fallback + однократный WARN); для LLM-fallback-модели берётся **min** окно primary/fallback. Оба env — ClassVar (Δ каталога = 0, прецедент `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`).
*Альтернативы:* runtime-запрос `/models` провайдера — отклонено (недетерминизм, latency, провайдер может врать); один глобальный ceiling — отклонено (анти-цель §2/§52.A); окно в каталоге per-param — отклонено (это не операционный параметр, а capability-факт; env-override покрывает исключения).
*Следствие:* карта требует сопровождения при смене модели; unknown-модель видно в `CONTEXT_CAPACITY` и можно исправить env-ом без релиза.

### D2 (§49 Q2) — формула полного payload, ровно один safety-запас
```
window = resolve_model_context_window(model)                    # D1
external = _estimate_external_payload_tokens(chat_id)           # РЕЮС MCA-07 (:1892): system+persona+tool schemas, tiktoken
output_reserve = max(1024, int(window × hot(limits.chat_budget_reserve_ratio)))   # РЕЮС ключа, default 0.10
available = safe_budget(window − external − output_reserve)     # ЕДИНСТВЕННОЕ применение TOKEN_SAFETY_MULTIPLIER (1.15) = uncertainty reserve §4
budget = policy(available, limits.chat_context_budget_tokens):
           -1 → available; 0/None → min(available, 16000); >0 → min(available, cap)
```
`safe_budget` вызывается один раз на весь расчёт; повторное деление запрещено (§4, §52.B). Fail-open при ошибке оценки (external=0, method=unknown, фиксация в `CONTEXT_CAPACITY`). `CHAT_CONTEXT_BUDGET_TOKENS` (settings.py:1773, default 16000) остаётся Dynamic-политикой; `CHAT_BUDGET_RESERVE_RATIO` (settings.py:1781, default 0.10) — резервом вывода.
*Альтернативы:* два деления (статус-кво — 32000→27826, отклонено); убрать множитель (§48 запрещает); учёт по факту API-usage с ретраем — отклонено (переполнение нельзя ретраить бесплатно).

### D3 (§49 Q3) — единый композер Dynamic/Unlimited
Новый `services/direct_context_composer.py`; kill-switch `DIRECT_CONTEXT_COMPOSER_ENABLED` (ClassVar, default ON, Δ каталога = 0). Конвейер §6 ТЗ: candidates (существующие билдеры; при ON — global/thread без self-усечения, без WARN `truncated`) → классификация P0–P3 → full payload (D2) → allocation (eviction P3→P2→P1; P0 обычным budgeter'ом не удаляется) → materialize (порядок блоков не меняется). При `-1` accounting не пропускается (устранение `:2802-2811`). Rigid-доли `chat_budget_*_ratio` на ON-пути не применяются; «всё влезает — не режем» (§16); per-block `limits.chat_global_context_max_tokens>0` / `limits.chat_thread_max_tokens>0` сохраняются как явные admin-caps (min), `-1` — без капа, `0` — дефолты 5000/3000 как soft-target. OFF → байт-в-байт прежний путь, parity-тест обязателен (T-4017).
*Альтернатива:* «поднять ceiling до 64000» — §48 запрещает; отдельный Unlimited-композер — отклонено (две точки истины, дрейф §5 ТЗ).

### D4 (§49 Q4) — old verbatim episode: границы, идемпотентность
Источники — только смерженные: канал `mode="history"` `mca_retrieval_context` (exact/lexical/vector/episode-хиты) + `thread_chain` + `smart_messages` (tg_message_id/timestamp/user_id/text) + `bot_replies`/`bot_reply_parents`. Второй архив и второй движок запрещены (§10 ТЗ; Δ DDL=0). Границы — детерминированная функция без LLM: расширение по межсообщенному gap ≤ `CHAT_EPISODE_GAP_SECONDS` (env, default 300) + reply-graph closure (cap 6, cycle-safe) + склейка [start..end] с split по «дыркам» + caps (`CHAT_EPISODE_MAX_MESSAGES` default 40, `CHAT_EPISODE_MAX_COUNT` default 2) + дедуп против fresh tail + рендер каноническими строками яруса A в блок `<Old_Episode>` (P0). Идемпотентность: те же данные+константы → тот же span. Explainability: лог hit_id→span→причина; счётчик `direct_old_episode_retrieval_total`.
*Альтернативы:* LLM-сегментация (недетерминизм/цена/§17-запрет на доп. LLM); окно фиксированного размера вокруг хита (§10: «не случайная строка» — отклонено); новая индексная таблица (Δ DDL, второй архив — отклонено).

### D5 (§49 Q5) — stale running summary
Композер читает `get_running_summary` на момент сборки (без TTL-смерти, прецедент E4/T-806) и никогда не ждёт summary-job. Состав при stale: summary → P2-блок (keep-head, кап-доля available); unsummarized middle → bounded top-K (≤ `CHAT_MIDDLE_MAX_MESSAGES`, env, default 60) по детерминированному весу (recency, членство в reply-цепи, упоминание target/участников, лексическое перекрытие с запросом); fresh tail → verbatim (D6); old episodes → verbatim (D4). Никаких «summary + 400 raw → head/tail-cut» (§14). §33-поля (revision=«window_end_ts:raw_count» — РЕЮС `_summary_revision` `:2106`; watermark/lag/age/tail) в `CONTEXT_CAPACITY`/`CONTEXT_SELECT`.
*Альтернативы:* блокировка ответа до обновления summary — отклонена (§14); радикальная замена summary raw-хвостом — отклонена (summary остаётся фоном, §13).

### D6 (§49 Q6) — гарантия fresh verbatim tail
Fresh tail = последние сообщения окна (включая current message). Минимум `CHAT_FRESH_TAIL_MIN_MESSAGES` (env, default **20**) — P1-пол: tail не опускается ниже пока не исчерпаны P2/P3; ниже — только путь §17 (сначала полное снятие P2, потом episodes). Target — весь остаток available после P0: никакого магического N (§12); фактический размер в `CONTEXT_SELECT`. P2 (summary) не может вытеснить P1 (tail) — тест §38.

### D7 (§49 Q7) — длинные reply-цепи
`CHAT_THREAD_MAX_DEPTH` (settings.py:1304, default 6) остаётся отдельным knob'ом (не удаляется; «просто увеличить» запрещено §48). При composer ON: `thread_chain.collect_thread_chain` идёт до корня с hard-cap `CHAT_THREAD_WALK_MAX` (env, default 40, cycle-safe), рендерится столько ходов, сколько влезает в P1-бюджет (keep-end); per-chat `limits.chat_thread_max_depth` (>0) = минимальная гарантия глубины: min(guaranteed, budget-capable). Тезисы глубже бюджета достигаются episode retrieval (D4, reply-graph closure). Acceptance >6 hops обязателен (§40).

### D8 (§49 Q8) — trigger priority, поля, независимый bot_replied_recently
`DecisionContext`/`CoordinatorDecision` — **аддитивно** +`trigger_type` (`force_keyword|mention|persona_name|reply_to_bot|free_will`) и +`force_reply_required`; +аддитивный `REASON_CODES`-код `force_direct` (15→16; существующие не переименовываются — контракт A7 сохранён). Матрица:
1. **force** (botword regex / mention / persona name в тексте, независимо от reply) → `ACTION_REPLY` всегда, reason=force_direct; шорт-каты `ignore_trivial`/`recent_reply`/`low_information` не применяются; Decision Maker управляет только style/длиной (§21). Единственные исключения — технические ветки (CB OPEN → фраза; NoApiKeyForChat → sandbox-фраза; empty answer/LLMError → существующие пути) и safety prohibition.
2. **direct autonomous** (reply_to_bot ∧ ¬force) → Decision Making: REPLY/REACT/SILENT(→🗿 при гейтах D9).
3. **background** — в `handle()` не попадает; free-will вне контракта (§19C); 🗿 запрещён.
`bot_replied_recently` вычисляется независимо (окно `CHAT_BOT_REPLIED_RECENTLY_SECONDS`, env, default 600, по `bot_replies`/history) и больше не `= reply_to_bot` (фикс `:1233`, §23). Совместный кейс «бот, нет, ответь нормально» (reply-to-bot + botword) → force. `_BOTWORD_EXCLUDED_USER_IDS` сохраняется.

### D9 (§49 Q9) — REACT и SILENT+🗿: контракт
**REACT — полноценный outcome:** аддитивное расширение детерминированной карты `_REACTION_BY_REASON`: класс сообщения → набор кандидатов ({😂,🤣} laughter; {👍,👌} ack/emoji; {👍,🔥,❤️} похвала; {🤨,🤔} сомнение), выбор — стабильный hash от message_id (детерминизм, без LLM и без рандома); только standard Telegram reaction enum (ограничение A8); per-chat тумблер — существующий `flags.chat_decision_reactions_enabled` (default ON, РЕЮС). ACK/LAUGHTER/EMOJI могут → REACT, не принуждаются к SILENT (§36).
**SILENT+🗿 — отдельное состояние:** 🗿 на исходное сообщение строго при: `trigger_type=reply_to_bot` ∧ `addressed` ∧ decision executed ∧ финал SILENT. Запрещён на: background, not_addressed-silent, технически потерянных (cooldown/CB/exception до decision), rate-limit/drop, вместо contextual reaction (§26). Гейты: env `DIRECT_SILENT_ACK_ENABLED` (ClassVar, default ON) + per-chat `flags.chat_silent_ack_enabled` (default ON); OFF → сегодняшняя тишина (паритет). React и silent_ack — разные outcomes в коде/событиях/счётчиках (§27).
**Fail-soft (§28):** падение setMessageReaction при SILENT → остаётся SILENT + `DIRECT_SILENT_ACK_FAILED`; REACT-failure не генерирует текст (механика A8 ≤2 попытки, 429 без повтора). Force + пустой ответ LLM → существующий технический 🗿-путь, в silent_ack-статистику **не** попадает.

### D10 (§49 Q10) — флаги и rollback (PM-Q5)
Ровно 2 новых env-рубильника (ClassVar, default ON, Δ каталога = 0) + 2 новых per-chat каталог-ключа:
| Слой | Имя | OFF-семантика |
|---|---|---|
| env | `DIRECT_CONTEXT_COMPOSER_ENABLED` | весь композер OFF: байт-в-байт прежний контекст-путь, без новых событий/счётчиков (§47 master) |
| env | `DIRECT_SILENT_ACK_ENABLED` | silent = тишина без 🗿 (паритет) |
| каталог | `flags.chat_silent_ack_enabled` (env-дефолт = `DIRECT_SILENT_ACK_ENABLED`) | то же per-chat |
| каталог | `flags.chat_autonomous_reply_enabled` | reply-to-bot этого чата всегда текстовый ответ |
РЕЮС без дублей: `flags.chat_decision_reactions_enabled`/`CHAT_DECISION_REACTIONS_ENABLED`; master-гейты `DIRECT_COORDINATOR_ENABLED` (settings.py:552) и `DIRECT_DECISION_MAKING_ENABLED` (settings.py:560) работают как прежде. Force-toggle НЕ вводится (гарантия §21; см. D-PM-4 спеки). Rollback: soft (перечисленные флаги, без отката версии) → cold (git revert, annotated-тег, T-4038) → runbook §60 (T-4037).

### D11 (PM-Q1) — resolve_context_tokens не меняется; граница consumer-side
`resolve_context_tokens` / `safe_budget` / `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` **сохраняют семантику ADR-1019-8** (Summary-генератор, `test_summary_l1_clusterizer.py:634`, `test_summary_fact_package.py:583`, `test_token_counter.py:120` не затронуты). Composer на ON-пути не вызывает `resolve_context_tokens` для `-1` — sentinel разбирается собственной политикой D2. Обоснование: §0 запрещает менять Summary-поведение; глобальная смена семантики -1 потребовала бы регресса всех потребителей ради точечного direct-эффекта. Итог: `services/token_counter.py` не меняется вовсе (минимальный дифф).

### D12 (PM-Q2) — Context Mode: derive, Δ=0 от ключей
Context Mode [Dynamic]/[Unlimited] — представление существующего `limits.chat_context_budget_tokens`: `-1` → Unlimited, `0`/None → Dynamic (дефолт 16000), `>0` → Cap (display-only). Miniapp-переключатель пишет этот же ключ; backend читает его же — одна семантика (§7 ТЗ), состояние не дублируется. Инцидентный чат (все три ключа `-1`) после включения композера получает Unlimited без миграций.
*Альтернатива:* новый per-chat ключ `flags.chat_context_mode` — отклонена: Δ каталога +1 без новой выразительности + риск расхождения «mode vs limit».
**Санкция каталога (итог):** +1 ключ `flags.chat_autonomous_reply_enabled`, +1 ключ `flags.chat_silent_ack_enabled` (оба в существующую группу `flags_decision_making`, param_catalog.py:369); +0 групп, +0 вкладок. F8: **481/422/456/105/103/21 → 482/423/457/105/103/21**; F8 переиздаётся атомарно с коммитом (прецеденты ADR-1026-2, ASAP-2 §101, ASAP-2.1 §102); `test_param_catalog.py` (assert 422) обновляется. Δ DDL = 0.

### D13 (PM-Q3) — реестр caps: скрытые (снимаются на ON-пути) vs явные (сохраняются)
| Место | Сегодня | Классификация | Действие при composer ON |
|---|---|---|---|
| `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (settings.py:517) | скрытый cap при -1 | скрытый cap | **снимается** на direct ON-пути (функция не меняется, D11); живёт для Summary/OFF |
| `safe_budget` в `_build_global_context` (`:3775`) и `_render_thread` (`:3894`) | /1.15 поверх скрытого ceiling | двойной запас | **снимается** (self-truncation не вызывается); единственное деление — в D2 |
| aggregate `-1` → skip accounting (`:2802-2811`) | при Unlimited нет accounting | скрытый bypass | **снимается** (D3) |
| rigid `chat_budget_*_ratio` доли | всегда режут по ratio | скрытая деградация | **снимаются** на ON-пути (P-модель, §16); OFF-путь сохраняет |
| `CHAT_GLOBAL_CONTEXT_LIMIT` (settings.py:1293, 100 сообщ.) | счётный срез при отсутствии summary | soft target | сохраняется как P2-граница выбора, не кап |
| `limits.chat_global_context_max_tokens>0` / `chat_thread_max_tokens>0` | явный cap | явный admin override | сохраняется (min с allocation) |
| `CHAT_THREAD_MAX_DEPTH` (settings.py:1304, 6) | отдельный knob | явный (меняется семантика) | сохраняется как минимальная гарантия + expansion (D7) |
| `CHAT_CURRENT_QUESTION_MAX_CHARS` (800), `_DIG_RESULT_MAX_CHARS` (3600), L2/relations капы | bounded-инжекты | явные | сохраняются |
| Summary-лимиты `limits.summary_*`, `SUMMARY_MAX_CONTEXT_*` | не direct | вне контракта | не трогаются (§0) |

Reviewer-линза §52.A проверяется grep-ом по этому списку (T-4000 инвентарь = надмножество).

### D14 (PM-Q4) — граница REUSE
Разрешено и обязательно: смерженные слои §93–§100 (mca-07 retrieval-контракт/episode-канал/`EvidenceBundle`, mca-14/01 миграционная дисциплина — read-only), `thread_chain` (ADR-1023-2), канонический рендер яруса A, `react_moai` (A8), `emit_agentic_event` (A9), `bot_replies`/`bot_reply_parents`, `get_running_summary`. Запрещено: второй архив/движок истории, новые DDL, вызовы WIP-волн MCA, GraphRAG-записи (только существующие P2-блоки RAG).

### D15 (PM-Q5) — финальный реестр observability
События — аддитивно к enum A9 (+7): `DIRECT_TRIGGER`, `DIRECT_SILENT_ACK`, `DIRECT_SILENT_ACK_FAILED`, `CONTEXT_CAPACITY`, `CONTEXT_SELECT`, `CONTEXT_PRESSURE`, `CONTEXT_PHYSICAL_OVERFLOW`; РЕЮС `DECISION_START`/`DECISION_COMPLETE` (+аддитивные поля trigger_type/force_reply_required/message_class)/`MESSAGE_IGNORED`/`REACTION_SENT`; гейт `AGENTIC_EVENTS_ENABLED`. Счётчики §46 (финальные имена, «autonomous» — нормализация опечатки владельца): `direct_force_reply_total`, `direct_autonomous_reply_total`, `direct_autonomous_react_total`, `direct_autonomous_silent_total`, `direct_silent_ack_success_total`, `direct_silent_ack_failed_total`, `direct_old_episode_retrieval_total`, `direct_context_pressure_total`, `direct_context_physical_overflow_total`. Механика: process-local аккумуляторы через `get_process_accounting()` + grep-able строка `direct_metric name=… count=…`. R17: только id/enum/числа.

### D16 (PM-Q6) — деплой-конвенция
Per-feature bump **2.58.34 → 2.58.35** (settings.py:2172), единый релиз ASAP-3 (код+тесты+каталог+F8 атомарно), по ASAP-конвенции — отдельно от MCA-волнового агрегата (прецеденты ASAP-2 2.58.33, ASAP-2.1 2.58.34). Preflight, checkpoint, annotated-тег отката, прод ff, рестарт `admin_bot`, health 200, `/healthz` 2.58.35, `database is locked`=0 (T-4038). Workflow-гейт §59: никаких других current_task-задач до закрытия ASAP-3.

### D17 (PM-Q7) — размещение в miniapp
В существующей IA без редизайна: **«DIRECT CONTEXT»** — в карточке группы `limits_chat` («Прямой чат: контекст», param_catalog.py:251): переключатель Context Mode + описания §34 + диагностическая панель (источник — аддитивный read-only `GET /api/direct/context-diagnostics?chat_id=`, значения последнего ON-прогона, process-local, R17-числа, Δ каталога = 0). **«DIRECT ADDRESSING / DECISION MAKING»** — в карточке группы `flags_decision_making` («Принятие решений», param_catalog.py:369): force keywords read-only (источник `reactions.chat_botword_pattern`/persona name) + 3 тумблера (D10) с defaults ON. Новых групп/вкладок нет.

## Последствия и риски
- R3 обоснован: касание production direct-контура и A7-контракта; компенсаторы — kill-switch D10, parity-тесты T-4017, полный summary-регресс (D11), матрица тестов §37–§44, live acceptance §56, gate §58.
- Риск карты моделей (D1) — управляется env-override + `window_source` в `CONTEXT_CAPACITY`.
- Риск 🗿-спама — конъюнктивный гейт D9 + anti-spam тест §43 + метрика `direct_autonomous_silent_total`.
- Не решается этим ADR: настоящий тумблер force-reply (D-PM-4; только по явному решению владельца), изменение Summary (запрещено §0).

## Затронутые контракты
ADR-1019-8 (SUPERSEDE на ON-пути Direct; вне Direct без изменений); ADR-1026-14/20/21 (A1/A7/A8 — аддитивные расширения, обратная совместимость сохранена); ADR-1027-7 (mca-07 — REUSE без изменений); ARCHITECTURE.md — обновление в reconcile-фазе (после Reviewer Approved + deploy + §58).
