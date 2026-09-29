# spec.md — `mca-asap3-direct-context-reply-reliability` (ASAP-3 / P0 владельца)

> **Раунд:** 1028 (ADR-серия 1028; ASAP-трек, строго после ASAP-2.1). **Задачи:** T-3999…T-4041 (`tasks.md`).
> **Источник требований (единственный):** `plans/current_task.md`, блок «ASAP-3 / P0», **строки 4062–6063 (§0–§62)** — прочитан полностью, подтверждён по коду.
> **Версия:** 2.58.34 → **2.58.35** (per-feature bump по ASAP-конвенции; прецеденты ASAP-2/ASAP-2.1).
> **Risk-Level: R3** — production-critical контур direct-чата (координатор + decision layer + сборка контекста), обязательный PROD DEPLOY + LIVE ACCEPTANCE (§55–§58), изменения в A7-контракте (аддитивные). Что могло бы поднять риск: изменение Summary-пайплайна (запрещено §0), DDL-миграции (их нет — Δ DDL=0), rewrite decision layer (запрещён §18).

---

## 0. Подтверждённый root cause (по коду, вход для T-3999)

Цепочка воспроизводится на текущем HEAD (2.58.34):

1. per-chat ключи инцидентного чата: `limits.chat_global_context_max_tokens = -1`, `limits.chat_thread_max_tokens = -1`, `limits.chat_context_budget_tokens = -1` — пользовательская семантика «Unlimited».
2. `services/token_counter.py:207-226` — `resolve_context_tokens(-1, …)` → `state == "unlimited"` → возвращает `settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (`config/settings.py:517`, env-only, default **32000**).
3. `services/token_counter.py:228-230` — `safe_budget(32000)` = `32000 / hot(models.token_safety_multiplier=1.15)` ≈ **27826** (`TOKEN_SAFETY_MULTIPLIER`, `config/settings.py:1641`).
4. `services/direct_chat_service.py:3755-3778` (`_build_global_context`) — `resolve_chat_limit` → `budget = safe_budget(limit)`; при body > budget: **WARN** `direct: global context truncated | tokens=39371 -> 27826` → `trim_verbatim_lines` + keep-head reserve. Тот же паттерн для thread: `:3855-3902` (`_thread_limit` + `_render_thread`, WARN `direct: thread truncated`).
5. Инвариант двойного усечения уже зафиксирован как диагностика (`_check_context_config_invariant`, `:2203-2257`), но саму причину (скрытый ceiling + доля) не устраняет.

Дополнительные подтверждённые дефекты decision layer (вход для T-4001):

- `direct_chat_service.py:1233` — `bot_replied_recently=reply_to_bot`: признаки **приравнены** (нарушение §23).
- `_decision_pre_action` (`:932-1003`) — **нет force-гейта**: «бот, ок» → `MSG_ACK` → `ignore_trivial` → `ACTION_SILENT` (нарушение §21); ветка (9) `bot_replied_recently` может заглушить любой триггер.
- `ACTION_SILENT` сегодня = тишина **без** 🗿 (`handle()`, `:1435-1445` — только лог + `MESSAGE_IGNORED`); 🗿 ставится только на empty-answer/тех. пути (`react_moai` `:1596`, `:1663`).
- Реакции A8: `_REACTION_BY_REASON` (`:617-622`) — закрытая карта {😂,👍,🔥} + 🗿-fallback; полноценного выбора по классу/тону нет (§24).
- Сборка контекста: `_apply_context_budget` (`:2762-2989`) — жёсткие ratio-доли (Global=0.30, Thread=0.20…), при `-1` aggregate accounting **пропускается целиком** (`:2802-2811` — возврат до accounting, нарушение §5), per-block self-truncation в билдерах + aggregate = двойное независимое усечение (§6).
- MCA-07 (смержен, §99 ARCHITECTURE) уже дал: `_estimate_external_payload_tokens` (`:1892-1954`) — оценка external payload (system+persona+tools); protected spans в `_truncate_block`; pre-flight `context_overflow`. Это **REUSE-база**, не переделка.

## 1. Scope / Excluded scope

**В скоупе (только consumer-side Direct Chat):**

- SC-1. Model-aware полный payload-бюджет и единый Direct Context Composer (Dynamic/Unlimited) за kill-switch `DIRECT_CONTEXT_COMPOSER_ENABLED` (§2–§8, §12–§17).
- SC-2. Семантика sentinel `-1/0/>0` для direct-пути без скрытого cap (§2, §7).
- SC-3. Old verbatim episode retrieval из существующих источников + детерминированные границы эпизода (§9–§11).
- SC-4. Recent context всегда verbatim, running summary = сжатый фон, stale-watermark устойчивость (§12–§14).
- SC-5. Thread depth > CHAT_THREAD_MAX_DEPTH через budget-aware expansion + episode retrieval (§15).
- SC-6. Физический overflow — явная degradation без `text[:N]` (§17).
- SC-7. Trigger-модель адресации (force/autonomous/background), force-гейт в decision layer, независимый `bot_replied_recently` (§18–§23).
- SC-8. REACT полноценный outcome (расширенный детерминированный словарь реакций), SILENT+🗿 только для intentional direct silence, fail-soft reaction API (§24–§28, §36).
- SC-9. Интеграция в A7 `CoordinatorDecision` — только аддитивно, `DIRECT_COORDINATOR_ENABLED`/`DIRECT_DECISION_MAKING_ENABLED` сохраняются (§18, §29).
- SC-10. Observability: события §30–§33 + счётчики §46 (R17-safe, без raw content) (§30–§33, §46).
- SC-11. Miniapp: Context Mode [Dynamic]/[Unlimited] + диагностика (§34), секция DIRECT ADDRESSING / DECISION MAKING (§35) — в существующей IA.
- SC-12. Тесты §37–§44, dry-run/baseline T-4003, деплой §55, live acceptance §56–§58, отчёт §61.

**Вне скоупа (запрещено менять):**

- Summary L1 semantic graph / L2 storyteller / Hybrid / Legacy / MAX_SUMMARY_PARTS / article formatter / sendRichMessage — **не трогаются вообще** (§0). `resolve_context_tokens`/`safe_budget`/`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` **сохраняют текущую семантику** для Summary и всех не-direct потребителей (PM-Q1, D11 ADR).
- Free-will/observer policy фона (§19C) — не реструктурируется; фоновые сообщения не входят в `handle()` и не могут получить 🗿.
- WIP-волны MCA (не смерженные) — вне скоупа; REUSE только смерженных слоёв (PM-Q4, D14 ADR).
- Дополнительный LLM compression call — НЕ вводится (§17).
- Никаких destructive миграций raw history; Δ DDL = 0.

## 2. Трассировка требований (§ ТЗ → REQ → SC → задачи/тесты)

| § ТЗ | Требование | REQ | SC | Задачи | Приёмка |
|---|---|---|---|---|---|
| §1 | Root cause 39371→27826 подтверждён | REQ-01 | — | T-3999 | T-4031 TEST 1 |
| §2,§7 | `-1` = no artificial cap; семантика -1/0/>0 | REQ-02 | 2 | T-4000, T-4008 | T-4031 TEST 1/2 |
| §3 | Per-chat Context Mode без hardcoded chat_id | REQ-03 | 11 | T-4028 | T-4030, §56-G |
| §4 | Model-aware full payload budget | REQ-04 | 1 | T-4007 | T-4031 TEST 3/4 |
| §5 | Adaptive accounting и при Unlimited | REQ-05 | 1 | T-4009 | T-4031 TEST 3 |
| §6 | Одна точка усечения | REQ-06 | 1 | T-4000, T-4009 | T-4031 TEST 1/2 |
| §8,§16 | Priority P0–P3, eviction P3→P2→P1, без rigid ratio | REQ-07 | 1 | T-4010 | T-4032 (§38) |
| §9 | Raw history = source of truth, без миграций | REQ-08 | 3 | T-4002, T-4011 | T-4032 (§38) |
| §10,§11 | Old episode: hit → coherent span, детерминированные границы | REQ-09 | 3 | T-4011 | T-4032 (§38), §56-F |
| §12 | Recent context всегда verbatim | REQ-10 | 4 | T-4012 | T-4032 (§38) |
| §13 | Summary = background; финальная композиция | REQ-11 | 4 | T-4013 | T-4032 (§38/§39) |
| §14 | Stale summary без brutal cut | REQ-12 | 4 | T-4014 | T-4032 (§39) |
| §15 | Thread depth >6 | REQ-13 | 5 | T-4015 | T-4032 (§40) |
| §17 | Physical overflow degradation | REQ-14 | 6 | T-4016 | overflow-тест |
| §18,§29 | Decision layer не переписывается; приоритетная цепочка | REQ-15 | 7,9 | T-4025 | интеграционные |
| §19–§23 | Триггеры A/B/C; поля; force-гейт; reply_to_bot ≠ bot_replied_recently | REQ-16 | 7 | T-4018, T-4019, T-4020, T-4021 | T-4033, T-4034 |
| §24,§36 | REACT полноценный; ACK→REACT без принуждения | REQ-17 | 8 | T-4022 | T-4034 (§42) |
| §25–§27 | SILENT+🗿 гейт; запреты фонового 🗿 | REQ-18 | 8 | T-4023 | T-4034 (§42/§43) |
| §28 | Reaction failure fail-soft | REQ-19 | 8 | T-4024 | T-4034 (§44) |
| §30–§33 | События DIRECT_*/CONTEXT_*/summary-поля | REQ-20 | 10 | T-4026, T-4027 | obs-тесты |
| §34,§35 | Miniapp Context Mode + Decision секция | REQ-21 | 11 | T-4028, T-4029 | T-4030, §56-G |
| §37–§44 | Все приёмочные сценарии владельца | REQ-22 | 12 | T-4031…T-4034 | одноимённые |
| §45 | Prod-log baseline до изменений | REQ-23 | 12 | T-4003 | базлайн-отчёт |
| §46 | Счётчики | REQ-20 | 10 | T-4026, T-4027 | obs-тесты |
| §47,§60 | Флаги/rollback/runbook | REQ-24 | — | T-4017, T-4037 | parity-тесты |
| §48 | Запреты «не fix» | REQ-25 | — | T-4036 | чек-лист Reviewer |
| §49 | Ответы Q1–Q10 | REQ-26 | — | T-4004…T-4006 | ADR-1028-2 |
| §53 | Browser verification | REQ-27 | 11 | T-4030 | harness-прогоны |
| §54 | DoD 22 пункта | REQ-28 | — | T-4036 | DoD-матрица tasks.md |
| §55–§58 | Prod deploy + live acceptance + gate | REQ-29 | 12 | T-4038…T-4040 | deployment/live-acceptance |
| §61,§62 | Отчёт 18 пунктов; инвариант | REQ-30 | — | T-4041 | отчёт |

## 3. Контракт единого Direct Context Composer (Q1–Q7)

### 3.1 Q1 — источник физического окна модели

- Новый нейтральный модуль `services/model_capacity.py` (consumer-side Direct; Summary НЕ импортирует и не меняется):
  - статическая карта `MODEL_CONTEXT_WINDOWS: dict[str, int]` — известные модели по имени (`llm_client._chat_model`, lower-case префикс-матч);
  - env-override `CHAT_MODEL_CONTEXT_WINDOW` (ClassVar, int|None) — принудительное окно для текущей модели, приоритет выше карты;
  - env `CHAT_UNKNOWN_MODEL_WINDOW` (ClassVar, default **16384**) — консервативный fallback для неизвестной модели + WARN один раз на модель (не «тихий hidden cap»: источник решения логируется);
  - источник решения фиксируется: `window_source ∈ {model_map, env_override, unknown_fallback}`;
  - fallback-модель LLM (`models.llm_fallback_model`): если окно её меньше — берётся **min** (композер не может знать, каким финалом ответит провайдер; conservative).
- Неизвестная модель НЕ трактуется как unlimited (анти-цель §2 — «любая magic constant как скрытый cap»): fallback явный, настраиваемый env-ом, наблюдаемый в `CONTEXT_CAPACITY`. Санкция PM-Q5/PM-Q3: оба env — ClassVar, Δ каталога = 0.

### 3.2 Q2 — формула полного payload (одна точка safety-запаса)

```
window        = resolve_model_context_window(model_name)        # §3.1
external      = _estimate_external_payload_tokens(chat_id)      # РЕЮС MCA-07:
              #   system prompt + persona block + tool schemas (tiktoken)
output_reserve = max(1024, int(window × limits.chat_budget_reserve_ratio))  # hot-ключ РЕЮС (default 0.10)
base          = window − external − output_reserve
available     = safe_budget(base)   # РОВНО ОДНО применение TOKEN_SAFETY_MULTIPLIER (1.15) —
                                    # это и есть «tokenizer uncertainty reserve» §4;
                                    # повторно НЕ применяется нигде
budget        = policy(available, limits.chat_context_budget_tokens):
                  -1  → available                        (Unlimited)
                  0/None → min(available, 16000)         (Dynamic, дефолт CHAT_CONTEXT_BUDGET_TOKENS)
                  >0 → min(available, cap)               (explicit user/admin cap)
```

- Оценка external уже консервативна (реальные строки, tiktoken); единое деление на 1.15 поглощает ошибку оценщика. §48 «убрать TOKEN_SAFETY_MULTIPLIER» — не выполняется (§4 «не применять повторно» — выполняется).
- При отсутствии модели/ошибке оценки — fail-open: `external=0`, метод `unknown`, `CONTEXT_CAPACITY` фиксирует (не блокирует ответ).
- Growth-инварианты: рост system/tools/personality → available ↓ (TEST 4); рост window → Unlimited ↑ без правки констант (TEST 5).

### 3.3 Q3 — единый композер Dynamic/Unlimited

Один конвейер (`services/direct_context_composer.py`, новый), kill-switch `DIRECT_CONTEXT_COMPOSER_ENABLED` (env ClassVar, default ON):

1. **Собрать candidates** — существующими билдерами (map/branch/rag/global/thread/target/relations/protected/lore/nostalgia/mood/current/anchors/sandwich), НО при composer ON билдеры global/thread вызываются в режиме «без self-усечения» (limit=None → без WARN `truncated`, полный кандидат);
2. **Классифицировать приоритет** (см. 3.4);
3. **Посчитать фактический full payload** (§3.2) и available;
4. **Распределить** — evict P3→P2→P1; P0 не трогается обычным budgeter'ом;
5. **Materialize** — порядок блоков в payload НЕ меняется (совместимость с существующим промптом и «важное к концу»).

Разница Dynamic/Unlimited — только слой policy (§3.2); physical limit применяется всегда. При Unlimited accounting **не пропускается** (устраняет `:2802-2811`). Rigid ratio-доли (`chat_budget_*_ratio`) на ON-пути не используются: место распределяется по фактическим потребностям кандидатов с порядком жертв; empty-секции не съедают бюджет; «всё помещается — не режется» (§16). Per-block `limits.chat_global_context_max_tokens > 0` / `chat_thread_max_tokens > 0` остаются **явными admin hard-cap** (min с распределением); `-1` — без капа; `0` — inherit (дефолты 5000/3000 как soft-target классификации P2/P1-блоков).

OFF-режим (`DIRECT_CONTEXT_COMPOSER_ENABLED=false`) → байт-в-байт сегодняшний путь (self-truncation билдеров + старый `_apply_context_budget`), обязательный parity-тест (T-4017).

### 3.4 Priority model (§8 × §12; сквозная карта)

| Класс | Содержимое (маппинг §12→§8) | Eviction |
|---|---|---|
| P0 MUST KEEP | `<Current_Question>`; replied-message (из reply-цепи); `<Conversation_Branch>`; `<Target_User>`; attribution (map/`user_relations`); protected mandatory facts (`<protected_facts>`/`<chat_lore>`); old episode, релевантный текущему запросу | только путём §17 |
| P1 | fresh verbatim tail (§3.6); `<Conversation_Thread>`; strong old episodes | после исчерпания P3→P2; tail не ниже минимума §3.6 |
| P2 | running summary (background, фикс-кап); `<Global_Context>`; RAG facts; level-2; conversation map (P2-часть); nostalgia-маркер | первый эшелон |
| P3 | слабый фон, дубликаты, уже представленное (dedup rag-vs-global остаётся) | до P2 |

Eviction внутри блока — существующими механиками (`trim_verbatim_lines` с importance-удержанием, `_truncate_block` с protected spans, keep-head для конспекта); **без** `text[:N]` и без keep_head/keep_tail как единственной стратегии (§48). Каждое решение → `CONTEXT_SELECT`.

### 3.5 Q4 — old verbatim episode: границы и идемпотентность

- **Источники (REUSE, PM-Q4):** единый retrieval-контракт `services/mca_retrieval_context.py` (смержен, §99) в режиме `mode="history"` → кандидаты каналов exact/lexical/vector/episode; `services/thread_chain.py` (ADR-1023-2) — reply-граф; `smart_messages` (tg_message_id, timestamp, user_id, text) — raw source of truth; `bot_replies`/`bot_reply_parents`. **Второй архив/движок запрещён** (§10); GraphRAG/facts — только как существующие P2-блоки, композер их не перечитывает.
- **Алгоритм границ (детерминированный, explainable, 0 LLM):** вход = retrieval-хит (id сообщения/эпизода).
  1. Span-кандидаты: назад/вперёд по (chat_id, timestamp ASC) в пределах окна: расширение, пока межсообщенный gap ≤ `CHAT_EPISODE_GAP_SECONDS` (env, default 300с), участники уже в span — приоритет чтения, не фильтр;
  2. reply-graph closure: предки/потомки по reply_to в пределах span, depth cap 6 (cycle-safe);
  3. Склейка в непрерывный [start..end] по message_id; «дырки» > gap → split, берётся эпизод, содержащий хит;
  4. Caps: ≤ `CHAT_EPISODE_MAX_MESSAGES` (env, default 40) сообщений на эпизод, ≤ 2 эпизодов на run (env `CHAT_EPISODE_MAX_COUNT`); приоритет у хита с лучшим score;
  5. Дедуп vs fresh tail (§3.6): пересечение → эпизод клипается до tail_start, иначе отбрасывается;
  6. Рендер — каноническими строками яруса A (`_context_row_line`), блок `<Old_Episode>`, класс P0.
- **Идемпотентность:** границы — чистая функция (данные + константы); тот же запрос/окно → тот же span; повторный хит в уже выбранном эпизоде не дублирует блок.
- **Explainability:** лог/событие фиксирует hit_id → span(start,end) → причина (gap_steps, reply_links, cap_applied); счётчик `direct_old_episode_retrieval_total`. Ни один шаг не зависит от LLM (SLO объяснимости, риск №5 tasks.md).

### 3.6 Q6 — гарантия fresh verbatim tail

- Fresh tail = сообщения окна после summary watermark (или всё окно при отсутствии конспекта), последние по времени, включая current message.
- **Минимум:** `CHAT_FRESH_TAIL_MIN_MESSAGES` (env, default **20**) — P1-минимум: tail не режется ниже минимума, пока не исчерпаны P2/P3; ниже минимума — только путём §17 (сначала полностью снимаются P2, потом episodes).
- **Target:** сколько влезло: tail получает весь остаток available после P0 — никакого единого магического N независимо от модели/payload (§12). Размер tail фиксируется в `CONTEXT_SELECT` (messages/tokens).
- Recent tail никогда не замещается summary (P2 не может вытеснить P1) — тест §38.

### 3.7 Q5 — stale running summary

- Композер читает summary **на момент сборки** (`get_running_summary`, без TTL-смерти) и никогда не ждёт background job — direct-ответ не блокируется (§14).
- Watermark stale (lag до сотен сообщений) обрабатывается композицией, а не ножницами:
  - summary → P2-блок (фикс-кап доли available, keep-head — конспект держится);
  - unsummarized middle (ts > watermark, до tail_start) → **importance-aware selection**: bounded top-K (≤ `CHAT_MIDDLE_MAX_MESSAGES`, env, default 60) по детерминированному весу (recency; членство в reply-цепи триггера; упоминание target/участников; лексическое перекрытие с запросом) — класс P3/P2 по нижней границе выбора;
  - fresh tail (§3.6) → verbatim; old episodes (§3.5) → verbatim.
- §33-observability: `summary_revision` (= `window_end_ts:raw_count`, РЕЮС `_summary_revision`), `summary_watermark` (window_end_ts), `summary_lag_messages`, `summary_age`, `unsummarized_tail_messages/tokens` — в `CONTEXT_CAPACITY`/`CONTEXT_SELECT`. Диагностический вопрос «summary worker отстал?» отвечает по логам без raw content.

### 3.8 Q7 — длинные reply-цепи (> CHAT_THREAD_MAX_DEPTH)

- `CHAT_THREAD_MAX_DEPTH` (default 6) остаётся **отдельным knob'ом** (не удаляется, не «просто увеличивается» — §48).
- Композер включает **dynamic expansion**: `thread_chain.collect_thread_chain` вызывается с walk-глубиной до корня (hard cap `CHAT_THREAD_WALK_MAX` env, default 40, cycle-safe), но в payload рендерится столько ходов, сколько влезает в бюджет P1 (keep-end); фактическое число ходов = f(available), не константа.
- Если критический тезис глубже — он достижим ещё и через episode retrieval (reply-graph closure §3.5 поднимает chain-эпизод); acceptance >6 hops обязателен (§40).
- Per-chat override `limits.chat_thread_max_depth` (>0) сохраняется как **минимальная гарантия** глубины рендера: min(guaranteed_depth, budget-capable).

### 3.9 §17 — physical overflow

Если P0 + fresh-tail-минимум > available (даже после снятия P2/P3 и episodes):
1. сохранить: current turn, replied message, `<Current_Question>`, `<Target_User>`, protected facts, essential episode (компактнейшая из релевантных ветвей);
2. secondary — hierarchical reduction (branch→thread→episode шагами с protected spans);
3. `CONTEXT_PHYSICAL_OVERFLOW` событие + счётчик; **никакого** silent `text[:N]`;
4. дополнительный LLM compression call НЕ вводится.

## 4. Контракт Direct Decision Making (Q8–Q9)

### 4.1 Q8 — trigger priority и поля адресации

`DecisionContext` расширяется **аддитивно**: `trigger_type: str`, `force_reply_required: bool`; `reply_to_bot` остаётся. Значения `trigger_type`: `force_keyword` (botword regex), `mention` (@username / entity mention), `persona_name` (имя персоны), `reply_to_bot`, `free_will`.

Резолв при входе в `handle()` (триггерный гейт `handlers/direct_chat.py:164-204` уже состоялся):

| Приоритет | Условие | trigger_type | force_reply_required | Исход |
|---|---|---|---|---|
| 1 | botword/persona_name/mention в тексте (независимо от reply) | force_keyword/persona_name/mention | **True** | **ACTION_REPLY всегда** (reason=force_direct); шорт-каты ignore_trivial/recent_reply/low_information не применяются; Decision Maker влияет только на style/длину (§21). Исключения — только техническая невозможность (CB OPEN → фраза; NoApiKey → sandbox-фраза; empty/LLMError → существующие ветки) и safety/system prohibition |
| 2 | reply_to_bot ∧ ¬force | reply_to_bot | False | Decision Making: REPLY / REACT / SILENT(→🗿) |
| 3 | прочее | free_will | False | В `handle()` не попадает (фоновые роутеры); existing free-will; 🗿 запрещён |

- «бот, нет, ответь нормально» (reply-to-bot с ботвордом) → force (приоритет 1).
- `bot_replied_recently` — **независимый признак** (временное окно по `bot_replies`/history, env `CHAT_BOT_REPLIED_RECENTLY_SECONDS`, default 600); больше **не** `= reply_to_bot` (фикс `:1233`). Влияет на ветку автономного SILENT (reason=recent_reply), не отменяет force (§23).
- Существующее исключение `_BOTWORD_EXCLUDED_USER_IDS` (alan/kostik keyword-ветка) сохраняется без изменений.
- Матрица «trigger × исход» и запрет «force никогда не SILENT/REACT» — контракт T-4005; тест §41/§52.F.

### 4.2 Q9 — REACT и SILENT+🗿: контракт и метрики

- **REACT = полноценный outcome.** Расширение детерминированной карты A8 `_REACTION_BY_REASON` (additive): класс сообщения → набор кандидатов {😂,🤣} (laughter), {👍,👌} (ack/emoji), {👍,🔥,❤️} (похвала), {🤨,🤔} (сомнение) — с учётом message class/emotion/persona-тона; выбор из набора детерминированный (стабильный hash по message id) — без единой hardcode-реакции (§24); только standard Telegram reaction enum (ограничение A8 сохраняется); per-chat тумблер — существующий `flags.chat_decision_reactions_enabled` (default ON). ACK/LAUGHTER/EMOJI могут → REACT, не принуждаются к SILENT+🗿 (§36).
- **SILENT+🗿 — отдельное состояние.** 🗿 на исходное сообщение строго при конъюнкции: trigger direct-autonomous (`trigger_type=reply_to_bot`) ∧ `context.addressed` ∧ decision executed ∧ финал `ACTION_SILENT`. Запрещён (§26): на background/free-will; на not_addressed-silent; на технически потерянных (cooldown/CB/exception-ветки до decision); при rate-limit/drop; вместо contextual reaction. `DIRECT_SILENT_ACK_ENABLED` (env ClassVar, default ON) + per-chat `flags.chat_silent_ack_enabled` (default ON) — гейты; OFF → сегодняшнее поведение (тишина, паритет).
- **Код/статистика разделяют outcomes:** react ≠ silent_ack (разные reason/счётчики/события).
- **Fail-soft (§28):** падение `setMessageReaction` при SILENT → остаётся SILENT, лог/событие `DIRECT_SILENT_ACK_FAILED`; REACT-failure не генерирует текст (существующая механика A8, ≤2 попытки, 429 без повтора). Force + пустой ответ LLM → существующий 🗿-путь технической деградации, в `direct_silent_ack_*` **не** считается, фиксируется как force outcome=failure.
- **Контракт A7 не ломается (§18):** `CoordinatorDecision` — только аддитивные поля (`trigger_type`, `force_reply_required`); `REASON_CODES` — только аддитивный код `force_direct`; карта A8 reason→emoji расширяется; `DIRECT_COORDINATOR_ENABLED`/`DIRECT_DECISION_MAKING_ENABLED` работают как прежде (master kill-switch). Существующие 15 reason-кодов не переименовываются и не удаляются; существующие потребители не ломаются.

## 5. Q10 — флаги, observability, miniapp (PM-Q5 — финальный реестр)

### 5.1 Флаги (ровно 2 новых env-рубильника + 2 новых per-chat каталог-ключа; §47 «не плодить»)

| Слой | Имя | Default | Слой отката | OFF-семантика |
|---|---|---|---|---|
| env ClassVar | `DIRECT_CONTEXT_COMPOSER_ENABLED` | ON | §47 master | точный прежний direct behavior байт-в-байт (self-truncation + старый `_apply_context_budget`; без новых событий/счётчиков) |
| env ClassVar | `DIRECT_SILENT_ACK_ENABLED` | ON | ack-контур | silent = тишина без 🗿 (паритет сегодняшнему ACTION_SILENT) |
| каталог per-chat | `flags.chat_silent_ack_enabled` | ON | hot-key, env-дефолт = `DIRECT_SILENT_ACK_ENABLED` | то же, per-chat |
| каталог per-chat | `flags.chat_autonomous_reply_enabled` | ON | hot-key | reply-to-bot всегда текстовый ответ (decision-матрица не применяется к этому чату) |
| (РЕЮС) | `flags.chat_decision_reactions_enabled` + env `CHAT_DECISION_REACTIONS_ENABLED` | ON | уже существует | реакции выключены (как сегодня) |
| (не вводится) | force-reply toggle | — | — | force — безусловная гарантия §21; miniapp показывает keywords read-only со статусом ON (см. 5.4, расхождение D-PM-4) |

Resolves per-call, никогда не бросают, Δ каталога от env-рубильников = 0 (ClassVar, прецедент MULTILAYER_EXTRACTION_ENABLED/DIRECT_COORDINATOR_ENABLED).

### 5.2 События (аддитивно к закрытому 20-типовому enum A9 → +7 типов; РЕЮС `emit_agentic_event`, гейт `AGENTIC_EVENTS_ENABLED`)

| Событие | Поля (R17-safe, без raw text) | § |
|---|---|---|
| `DIRECT_TRIGGER` | trigger_type, force_reply_required, reply_to_bot, is_private, chat_id, message_id | §30 |
| `DIRECT_SILENT_ACK` | reaction=🗿, success, chat_id, target_message_id, reason_code | §25/§31 |
| `DIRECT_SILENT_ACK_FAILED` | error_code (enum), chat_id, target_message_id | §28 |
| `CONTEXT_CAPACITY` | model, window, window_source, external_tokens, output_reserve, available_context, budget, policy_mode(unlimited/dynamic/cap), summary_revision/watermark/lag_messages/age | §32/§33 |
| `CONTEXT_SELECT` | recent_verbatim_messages/tokens, reply_thread_messages, old_episode_count/messages/tokens, middle_selected_messages, compressed_background_tokens, rag_tokens | §32/§33 |
| `CONTEXT_PRESSURE` | excluded_low_priority, compressed_or_dropped, physical_overflow, unsummarized_tail_messages/tokens | §32/§33 |
| `CONTEXT_PHYSICAL_OVERFLOW` | preserved_kinds, available, needed | §17/§32 |

Существующие `DECISION_START`/`DECISION_COMPLETE`/`MESSAGE_IGNORED`/`REACTION_SENT` переиспользуются; `DECISION_COMPLETE` получает **аддитивные** поля trigger_type/force_reply_required/message_class. FORCE: action=reply, reason=force_direct.

### 5.3 Счётчики §46 (финальные имена; process-local аккумуляторы через существующий `get_process_accounting()` + структурная строка лога `direct_metric name=<…> count=<…>` на каждое инкрементное событие — grep-able база для §57)

1. `direct_force_reply_total` 2. `direct_autonomous_reply_total` 3. `direct_autonomous_react_total` 4. `direct_autonomous_silent_total` 5. `direct_silent_ack_success_total` 6. `direct_silent_ack_failed_total` 7. `direct_old_episode_retrieval_total` 8. `direct_context_pressure_total` 9. `direct_context_physical_overflow_total`.

(Орфография «autonomous» — нормализация опечатки §46 «autonomous»; расхождение D-PM-3.)

### 5.4 Miniapp (PM-Q7 — в существующей IA, без редизайна)

- **«DIRECT CONTEXT»** — внутри существующей карточки группы `limits_chat` («Прямой чат: контекст», param_catalog.py:251): переключатель **Context Mode [Dynamic]/[Unlimited]** (+ режим «Cap (вручную)» display--only при `>0`); описания дословно §34; диагностическая панель (Model context window / Available for context / Current payload / Recent verbatim / Retrieved old episodes / Compressed background / Excluded low-priority) — источник: аддитивный read-only `GET /api/direct/context-diagnostics?chat_id=` (значения последнего ON-прогона из process-local snapshot, TTL не нужен — одно значение на чат; R17: только числа; роутер — существующий web/api слой, Δ каталога = 0).
- **«DIRECT ADDRESSING / DECISION MAKING»** — внутри существующей группы `flags_decision_making` («Принятие решений», param_catalog.py:369): force keywords — read-only отображение configured списка (`reactions.chat_botword_pattern` / persona name) с описанием §35; 3 тумблера с [✓] default ON: Autonomous replies (`flags.chat_autonomous_reply_enabled`), Use contextual reactions (РЕЮС `flags.chat_decision_reactions_enabled`), Silent acknowledgement (`flags.chat_silent_ack_enabled`). Никаких новых групп/вкладок.
- Приватные raw messages в панелях запрещены (§34).

## 6. Данные и совместимость

- **Δ DDL = 0.** Ни одной новой таблицы/колонки; episode retrieval — чтение существующих `smart_messages`/`bot_replies`/`lore_stories`; диагностика — process-local snapshot.
- **Δ каталога (санкционировано, PM-Q2/PM-Q5): +1 ключ** `flags.chat_autonomous_reply_enabled` (группа `flags_decision_making` существующая) **+1 ключ** `flags.chat_silent_ack_enabled` (там же); **+0 групп; +0 вкладок.** Context Mode — derive от существующего `limits.chat_context_budget_tokens` (-1 → Unlimited, 0/None → Dynamic, >0 → Cap) — **без новых ключей** (PM-Q2). Точные F8-счётчики: **REGISTRY 481 → 482; Settings dataclass 422 → 423; categorized 456 → 457; GROUPS 105; _TAB_BY_GROUP 103; TAB_RULES 21** — Δ>0 → **F8 переиздаётся** (дисциплина frozen-F8, прецеденты ADR-1026-2 / ASAP-2 §101 / ASAP-2.1 §102). Test `test_param_catalog.py` (assert 422) и fixture-каноны обновляются атомарно.
- **Совместимость sentinel:** `resolve_context_tokens`/`safe_budget`/`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` не меняются (Summary и не-direct потребители не затронуты — регресс summary-тестов зелёный, §0). Composer на ON-пути НЕ вызывает `resolve_context_tokens` для -1 (см. PM-Q3 список).
- **Ассеты/UI:** zero-build CSP, без новых vendor-скриптов; cache-bust `?v=` по конвенции при изменении web-ассетов.

## 7. Безопасность / приватность

- R17: события/логи/диагностика — только id/enum/числа/коды; raw user text, промпты, ответы LLM запрещены. Обязательная R17-проверка в T-4026/T-4027.
- Episode rendering — данные собственного чата (chat_id-scope запросы); cross-chat утечки исключены существующим scope-контролем.
- Реакции — официальный `setMessageReaction`, standard enum (механика A8 без изменений).
- Новый read-only endpoint — существующий RBAC-слой admin-панели (как остальные `GET /api/*`).

## 8. Приёмочные сценарии

- **Тесты кода (§37–§44):** T-4031 (TEST 1–5: нет `39371→27826`; нет скрытого 32000; accounting при -1; рост external ↓ available; рост window ↑ Unlimited); T-4032 (§38 fixture 500 сообщений/эпизод ~200 назад verbatim/summary-background/middle-режется-раньше; §39 lag 50/100/300/400; §40 >6 hops); T-4033 (§41 force-матрица); T-4034 (§42/§43/§44 autonomous/background/failure). Полный pytest + JS — T-4035.
- **Browser verification (§53) — REQUIRED** (меняется user-visible web UI: переключатель, тумблеры, диагностическая панель). Playwright MCP против локального стенда (тот же контур, что приёмка §9 ASAP-2.1: локальный dev-сервер + seeded PG, без выдуманных credentials и без прод-авторизации): (1) Dynamic↔Unlimited переключение и сохранение; (2) descriptions §34; (3) per-chat switching (значения разных чатов не смешиваются); (4) persistence after reload; (5) Decision-тумблеры §35 рендер + переключение; (6) silent acknowledgement toggle; (7) reactions toggle; (8) отсутствие mixed/stale значений; console/pageerror = 0. Viewport'ы: desktop 1280×800 + mobile 390×844. Скриншоты/логи — в feature artifacts. Telegram WebView-отличия — реальная проверка владельцем в §56-G (harness не подменяет).
- **Live acceptance (§56, прод):** A FORCE «бот, ты тут?» → текст; B autonomous reply → decision реально выполняется (REPLY/REACT/SILENT; SILENT → 🗿); C «ахах» → реакция предпочтительнее текста; D обычная беседа → нет массовых 🗿; E Unlimited > 27826 tokens без hidden truncation; F old episode в trace; G miniapp ↔ backend behavior. Чек-листы — T-4039.
- **Post-deploy (§57):** счётчики §46 vs базлайн T-4003; отсутствие ERROR-спайка, reaction spam, постоянного physical overflow, silent force-direct, скрытых 27826-truncations. Gate §58 = Reviewer Approved + deploy + live acceptance + post-deploy.

## 9. DoD §54 — 22/22 (карта в tasks.md, сверка spec)

Покрытие 1–22 подтверждено: 1–6 → SC-1/2/11 (REQ-02…04, REQ-03); 7–12 → SC-3/4/5 (REQ-07…13); 13–19 → SC-7/8 (REQ-15…19); 20 → §5.4/§8; 21 → §5.2/§5.3; 22 → T-4035 + §8 browser. Полная матрица задача→тест — в `tasks.md` (DoD-матрица §54).

## 10. Запреты §48 — чек-лист (Reviewer)

Ни одно из перечисленного в §48 не является решением ASAP-3; спека не содержит: подмены 32000→64000; удаления TOKEN_SAFETY_MULTIPLIER (он применяется ровно один раз — §3.2); «просто увеличить» лимиты/depth (глубина — budget-aware, §3.8); отправку всех 500 сообщений; `text[:N]`; keep_head/keep_tail как единственную стратегию; отключение summary (summary остаётся P2-фоном); «reply всегда текст» (force-only); отключение Decision Making; «всегда бот» (reply_to_bot остаётся триггером); 🗿-спам на фон; 🗿 как единственную реакцию (словарь расширен); LLM retries вместо pipeline-fix; переписывание ASAP-2 Summary.

## 11. Риски и rollback

| Риск | Митигция |
|---|---|
| Общий utility с Summary (PM-Q1) | D11: consumer-side only; `resolve_context_tokens` не меняется; полный summary-регресс в T-4035 |
| Скрытые caps выживут (§52.A) | PM-Q3 список (D13) + grep-инвентарь T-4000 + Reviewer-линза A |
| 🗿-спам при ошибках классификации | Жёсткая конъюнкция гейта (§4.2) + §43 anti-spam тест + prod-метрика direct_autonomous_silent_total |
| Force перехвачен шорт-катами | Force-гейт (приоритет 1 матрицы §4.1) до всех веток `_decision_pre_action` + матрица §41 |
| Качество границ эпизодов | Детерминированный алгоритм §3.5 + лог hit→span + fixture §38 |
| Дрейф OFF-режима | Dual-mode parity-тесты T-4017 (байт-в-байт) |
| Каталог/флаги | Δ санкционирована в этом spec; F8 переиздание в атомарном коммите |

**Rollback (Q10):** soft — env `DIRECT_CONTEXT_COMPOSER_ENABLED=false` (композер и вся контекст-ветка OFF-паритет) и/или `DIRECT_SILENT_ACK_ENABLED=false` (ack-контур) и/или per-chat `flags.chat_autonomous_reply_enabled=false` — без отката версии; изменения настроек применяются рестартом/горячим ключом по слою. Cold — git revert фича-коммита до 2.58.34 (точка — annotated-тег по §55/T-4038). Runbook §60 — T-4037.

## 12. Деплой и заключительные артефакты

- Per-feature bump **2.58.34 → 2.58.35** (PM-Q6, D16), единый релиз ASAP-3: код+тесты+каталог+F8 атомарно; preflight/checkpoint/health/`/healthz` 2.58.35/`database is locked`=0 — T-4038; workflow-гейт §59 (никаких других current_task-задач до закрытия).
- **Финальный отчёт §61 — шаблон 18 пунктов** (T-4041): 1 Root causes; 2 Architect decisions (ADR-1028-2 D1–D17 сводка); 3 основной diff; 4 какие старые caps удалены/изменены (PM-Q3 список с фактом); 5 Dynamic как работает; 6 Unlimited как работает; 7 old verbatim episode retrieval; 8 Force Direct; 9 autonomous reply; 10 выбор REACT; 11 SILENT+🗿; 12 Test results; 13 Browser verification; 14 Production deployment evidence; 15 Live acceptance results; 16 Post-deploy logs/metrics; 17 Rollback state; 18 подтверждение «ASAP-3 production acceptance complete; current_task continuation unblocked». До п.18 — continuation BLOCKED (§59).
- **Инвариант §62** (проверка при закрытии): raw history = истина; running summary = compressed background; recent = verbatim; relevant old = verbatim episode on demand; dynamic budget режет шум, не смысл; unlimited = нет искусственного cap; «бот, …» → FORCE_REPLY; reply на бота → autonomous (REPLY/REACT/SILENT→🗿); background → existing free-will.

## 13. Расхождения tasks ↔ spec (для PM-сверки; все закрыты в пользу spec)

| # | Расхождение | Решение |
|---|---|---|
| D-PM-1 | tasks.md:7 называет единственным базовым kill-switch `DIRECT_COORDINATOR_ENABLED`; у A7 есть второй master `DIRECT_DECISION_MAKING_ENABLED` (settings.py:560), а композеру нужен свой | В ADR фиксируются 3 независимых master: координатор (A1), decision (A7) — РЕЮС, composer — новый (§5.1); parity-тесты покрывают комбинации |
| D-PM-2 | §47/tasks предлагают имя `new_direct_context_composer_enabled`; проектная конвенция env-флагов — SCREAMING_SNAKE ClassVar | Финальное имя `DIRECT_CONTEXT_COMPOSER_ENABLED` (PM-Q5, D15) |
| D-PM-3 | §46 владельца содержит опечатку «direct_autonomous_*» | Нормализовано в `direct_autonomous_*` (§5.3); расхождение задокументировано для отчёта §61 |
| D-PM-4 | §35 можно прочитать как требование тумблера «Force keyword reply» | Трактовка spec: force — read-only display (гарантия §21 не отключаема); [✓]-тумблеры — ровно три (autonomous/reactions/silent-ack). Если владелец хочет настоящий toggle — это решение владельца, сейчас НЕ реализуем |
| D-PM-5 | tasks.md:12 называет §93–§100 «WIP-волны»; фактически это **смерженные** слои (round 10.27, deploy DEFERRED_TO_RELEASE) | PM-Q4 граница: REUSE смерженных §93–§100 разрешён и обязателен (thread_chain, mca-07 retrieval/episode-канал, protected spans, A6/A8 примитивы); не-смерженные WIP — вне скоупа |
| D-PM-6 | T-4028/T-4029 не выделяют задачу под diagnostics-endpoint §34 | Endpoint входит в scope T-4028 (аддитивный read-only GET; Δ каталога=0); новая задача не нужна — подтверждено Architect |
| D-PM-7 | §12 даёт 6-уровневый порядок, §8 — 4 класса P0–P3 | Сквозная карта соответствия — §3.4; противоречия нет (P0 ⇔ уровни 1–2+релевантный old episode, P1 ⇔ 3–4, P2 ⇔ 5–6, P3 ⇔ шум) |
| D-PM-8 | Счётчик `bot_replied_recently` окно не специфицировано ТЗ | Env `CHAT_BOT_REPLIED_RECENTLY_SECONDS` default 600, ClassVar, Δ каталога=0 |

## 14. Зависимости

- Блокировки: T-4004 (этот spec+ADR) → T-4007…T-4017; T-4005 → T-4018…T-4025; T-4006 → T-4026…T-4029, T-4037. Группа A — параллельно, T-4003 желателен до финала ADR (базлайн).
- REUSE-контракты (не ломать): `mca_retrieval_context` (RETRIEVAL_POLICY_VERSION), `thread_chain.ChainItem`, `_estimate_external_payload_tokens`, `_truncate_block`/protected spans, `react_moai` (7-исходный enum A8), `emit_agentic_event`, `EvidenceBundle`/`context_version`, `get_running_summary`, `resolve_item_id`/канонический рендер яруса A.
