# ASAP 7 — Architecture (Phase 1, ARC-1)

- Дата: 2026-10-09. HEAD `08a8849`. Входы: audit-direct.md, audit-cover.md, audit-modules-chat-claims.md, current_task.md §0–§23 (ASAP 7), workflow_state.md.
- Назначение: исполняемый контракт для Builder F1–F9. Только решения реальных развилок; всё, что определено ТЗ, здесь не переоспаривается.
- Вопросы владельцу: **нет** (все развилки разрешаются ТЗ + кодом; см. §10).

---

## 1. Блок Direct — целевая топология (F1/F2)

### 1.1. Решение §2.7: отдельный pre-tool L1 Planner вызов (вариант «b» аудита)

**Fused-вариант отклонён.** Техническая причина: в текущей схеме Decision Task инжектится в payload ДО `chat_with_tools` (:2480-2483), но решение живёт в финальном тексте ПОСЛЕ tool-раундов — протокол tool-calling не даёт увидеть JSON решения до исполнения тулов (D-3 неустраним внутри fused-вызова). Structured-first-phase внутри того же вызова не существует.

**Схема вызовов (cognitive Direct path, `flags.direct_l1_enabled=ON`):**

```text
дет. пре-гейты (throttle/breaker/dedup/pre-gates dig+image/stats-intent) — без изменений
  ↓
L1 PLANNER — 1 LLM call (compact context §1.5, model slot §1.6) → L1Plan JSON
  ↓ hard override: force → action=reply (LLM не спрашивается об action)
  ├─ action=silent → 🗿 (_execute_silent_ack:1712) / тишина → END
  ├─ action=react  → react_moai (reaction из allowed-набора) → END
  └─ action=reply
       ↓ deterministic capability mapping (§1.4)
       ├─ resolved tools = ∅ → L2 WRITER — 1 LLM call (полный Writer-контекст + plan-блок)
       └─ resolved tools ≠ ∅ → chat_with_tools (существующий bounded loop, тула
          model-driven, анонсирован ТОЛЬКО resolved-подсет; DAG-executor сохранён)
             → ToolLoopResult → deterministic evidence packaging (БЕЗ LLM)
             → L2 WRITER — 1 LLM call (Writer-контекст + plan-блок + evidence packet)
```

Итого semantic-стадий: L1=1, L2=1; tool-раунды — внутренний контракт цикла (учёт в usage как сейчас, `module=direct_chat`). §22 п.3 соблюдён: старый post-tool Синтезатор+Вербализатор (2 вызова) и fused Decision Task в primary path не сосуществуют с новым L1.

### 1.2. Судьба Синтезатора/Вербализатора (гейт :2807-2818)

- **Синтезатор** (`_synthesize_direct_answer` stage-1, :3174-3184) → **превращается в deterministic evidence packaging**: новый чистый построитель `build_evidence_packet(raw: ToolLoopResult, plan)` (новый `services/direct_l1.py` или секция в нём) — из уже существующих `tool_results`/`tool_context`/`tool_trace` (tool_loop.py:95-131) собираёт санитизированный bounded-текст (существующий `redact_secrets`, кап символов, статус/ошибка per tool). LLM-вызов и `parse_direct_synthesis` из primary path уходят.
- **Вербализатор** → становится **L2 Writer на ВСЕХ Direct-путях**: тот же prompt-канал (`prompts.direct_chat_verbalizer_system_prompt`), `verbalize_validated`, form/numeric-контракты, channel rules — переиспользуются без дублей. Меняется только условие запуска: не «после успешного tool-loop», а «после L1 action=reply» (с evidence packet при тулах, без — иначе).
- Гейт :2807-2818 демонтируется; lore_compiled-ветка (дет. HTML-история) остаётся ВНЕ L2 (без изменений, :2838-2840).
- Legacy-ветка: `DIRECT_L1_ENABLED=false` → байт-в-байт прежний pipeline (fused Decision Task + System2). Старый код не удаляется до конца live-acceptance F1; после — Scanner фиксирует dead path, удаление отдельным cleanup-коммитом.

### 1.3. Контракт L1 output (финализированная схема)

Модуль `services/direct_l1.py`, `@dataclass L1Plan`. JSON:

```json
{
  "action": "reply | react | silent",
  "reaction": "<emoji>|null",
  "response_act": "answer|agreement|disagreement|banter|tease|hostile_rebuff|emotional_reply|support|clarification|explanation|research|comparison|summarization|creative|historical_recall|other|<free ≤32>",
  "extent": "one_word|micro|compact|auto|normal|detailed|longform|exhaustive",
  "tone": "inherit|neutral|warm|playful|ironic|sarcastic|annoyed|aggressive|serious|<free ≤24>",
  "emotional_mirroring": "none|light|medium|strong",
  "structure": "<set STRUCTURES из response_extent>",
  "delivery_hint": "plain|rich|media",
  "tool_policy": "none|auto",
  "capabilities_needed": ["web_search", "..."],
  "needs_clarification": false,
  "clarification_target": null,
  "confidence": 0.94
}
```

Нормализация (никогда не бросает):
- `action` невалиден/нет → `INVALID` → **bounded repair: ровно 1 повтор** с аннотацией ошибки (паттерн summary L1 repair) → иначе deterministic legacy fallback (classify_request + прежняя demote-матрица). Никаких циклов (D14).
- `extent`/`structure`/`delivery_hint`/`tool_policy` — закрытые множества (переиспользуют EXTENTS/STRUCTURES/DELIVERY_HINTS/TOOL_POLICIES из response_extent.py); неизвестное → `auto`/`chat`/`plain`/`none`.
- `response_act`/`tone` — **открытый словарь** (§2.3/§2.4 ТЗ: «не превращать enum в клетку»): lowercase, трим, лимит длины, неизвестное → `"other"`/`"inherit"`. L2 получает как hint-строку без механического штампа.
- `reaction` не из `ALLOWED_LLM_REACTIONS` → REACT демотируется в дет. реакцию (нынешняя семантика :2658-2683).
- `confidence` clamp [0,1]; **бакеты**: `low <0.5`, `medium <0.75`, `high ≥0.75`. Семантика: `low` → capabilities НЕ исполняются (reason `low_confidence`, L2 получает честную пометку) и SILENT демотируется в дет. матрицу; телеметрия — всегда (§18). Иных behavioral-эффектов нет.

Системный промпт L1 — новый канон-ключ `prompts.direct_l1_planner_system_prompt` (дефолт в chat_prompts.py + PREV-слепок + лестница prompt_migrations.py по действующим правилам «правка канона = бамп»).

### 1.4. Capability→tools mapping (allowlist, D15)

Новый `services/direct_capabilities.py` — статическая таблица (единственный источник):

| capability (L1) | tool (фактические имена tool_schemas.py:74-620) |
|---|---|
| web_search | execute_web_search |
| fetch_url | fetch_article |
| chat_history | get_recent_history |
| chat_memory | query_chat_memory |
| user_memory | get_user_context |
| historical_search | dig_into_lore (+ compile_lore_story при lore ON) |
| fact_check | fact_check |
| image_understanding | recognize_image |
| media_download | download_media |
| transcription | transcribe_video |
| video_summary | summarize_video |
| image_generation | generate_image |
| statistics | — тулa в наборе НЕТ (MCA-15 stats-intent — дет. пре-блок, не tool): capability резолвится в ∅ → честная пометка L2 «недоступно» |

- Механика: `resolved = CAPABILITY_TO_TOOLS ∩ active_tools(lore, image)`; `build_tool_plan` сохраняется **только как дет. fast-path для объективного факта «2+ URL + явное сравнение»** (§3 разрешает дет. для объективных вещей); primary источник мульти-тул — capability-подсет, анонсируемая в `chat_with_tools`. §22 п.10 закрыт: ≥2 URL больше не «единственный мозг».
- **Hallucinated capability**: нет в таблице или не резолвится → drop + `agentic event L1_CAPABILITY_REJECTED (capability, reason)` + честная пометка L2 «недоступно» (D15). Не ошибка прогона.
- **Partial failure**: прежний fail-soft tool_loop (Golden M) без изменений.

### 1.5. L1 context budget (§2.9)

Новый компактный сборщик `build_l1_context(...)` в `direct_l1.py`. Состав: current message; reply target/quote; окно последних N (дефолт 20) сообщений из уже поднятого `window`; speaker/addressee (из `target`-блока); compact memory-hints — переиспользовать `_bundle_scoped_slice` (:3171); speech/emotion hints — переиспользовать `_build_speech_understanding` (:2290) в коротком рендере; available capabilities (после resolve — список имён); force/direct-address факты; personality compact frame (голова существующего character_block, кап). Кап бюджета: `limits.direct_l1_context_tokens` (дефолт 1600, каталог); полный Writer-контекст L1 НЕ получает.

Метрики (§2.9): каждый L1-вызов пишет usage-row (`step="l1_planner"`, §1.10) + agentic event `L1_PLAN` (R17-whitelist: action/response_act/extent/tone/bucket/capabilities requested/resolved/inherited/fallback/latency_ms/input_chars).

**`_SANDWICH_REMINDER` (:347-349, :3636-3638): решение — точечная замена текста глобально.** Новый текст: `«отвечай на последний вопрос (<Current_Question>); людей называй именами из карты, без скобок и номеров»` — удаляются только слова «коротко, по делу» (нарушение D11/§22 п.9), якорь на последний вопрос и анти-артефакт имен сохраняются (это не cap, а формат/фокус). Обоснование: полный remove теряет работающий якорь внимания при длинном контексте; «только при micro» неверно — якорь нужен и longform. Contract-тест D11: финальный промпт longform-плана не содержит «коротко»/«по делу». L1-промпт sandwich не получает вовсе (L1 не пишет прозу).

### 1.6. Model slot L1 (§2.8) + failure ladder (§2.10)

По прецеденту Hybrid Summary слотов (param_catalog.py:1060-1079): новая группа `models_direct_l1` в `models`-категории, поверхность на вкладке `mod_direct` (§19 ТЗ):

- `models.direct_l1_base_url`, `models.direct_l1_model_name`, `keys.direct_l1_api_key` (secret) — пусто = inherit main;
- `limits.direct_l1_temperature` (дефолт — как у Stage-1), `limits.direct_l1_timeout_seconds` (дефолт 15), `limits.direct_l1_max_output_tokens` (JSON-бюджет, дефолт 512);
- `flags.direct_l1_enabled` — product master toggle L1-линии (default ON); env `DIRECT_L1_ENABLED` остаётся emergency kill-switch (§4.3 AND-семантика, §4 ниже);
- `flags.direct_l1_fallback_enabled` — fallback на main-модель (default ON).

Резолвер `resolve_l1_model(chat_id)` → `(provider, base_url, model, api_key, source: "l1"|"main")`; UI показывает effective source (§22 п.5/6 закрыты тестом: effective==configured проверяется интеграционно).

**Ladder**: configured L1 → (fallback ON) main → **deterministic safe fallback** = classify_request + прежняя demote-матрица (легаси-ветка уже в коде) → без duplicate reply (существующие freshness/dedup-гварды :2879+ остаются). L1 outage не создаёт второго ответа: один turn — максимум одна отправка (инвариант тестом D13).

**D-2 (обязательный фикс в F1):** `DIRECT_RESPONSE_PLAN_ENABLED`, `DIRECT_TOOL_PLAN_ENABLED`, `DIRECT_RICH_DELIVERY_ENABLED`, `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS` — объявить ClassVar в config/settings.py (паттерн SYSTEM2_DIRECT_ENABLED:562), иначе rollback-контракт мёртв.

### 1.7. Hard gates: force / SILENT→🗿 / REACT

Всё детерминировано, LLM не может отменить (§0):
- **force** (keyword/mention/persona/reply) → `force_reply_required` резолвится ДО L1 (нынешний `_resolve_direct_trigger`:853-876); L1 вызывается, но `action` жёстко переопределяется в `reply` post-parse (hard override, reason `force`); allowed_actions для SILENT/REACT формируются прежней demote-матрицей (:2133).
- **SILENT**: только в autonomous-контексте (вне force), в allowed → 🗿 через `_execute_silent_ack:1712` (конъюнкция silent-ack неизменна); вне allowed → тишина (нынешняя семантика :2684-2731).
- **REACT**: reaction только из `ALLOWED_LLM_REACTIONS`; невалид → дет. реакция/тишина (как :2658-2683). Прежний отдельный pre-tool REACT-вызов (:2415-2475) в primary path демонтируется — его роль забрал L1; сохраняется в legacy-ветке.

### 1.8. Демоция response_extent.py (§3)

Остаётся (переиспользуется, не дублируется): explicit-form deterministic parser («одним словом», «в двух абзацах», «подробно» → form override ПОСЛЕ L1, поверх semantic extent — §2.5); `render_extent_block` как рендерер плана для L2; `longform_max_output_tokens`/rich-пороги; `classify_request` как **safe fallback при L1 outage** и в legacy-ветке. Удаляется из primary path: classify как semantic brain, `social_chat→compact` (:349-353), «3 слова+?→micro» (:336-343) как primary, 2-URL как primary источник мульти-тул, `CLARIFY_MEDIA_TARGET` как primary clarification. Проверка Ревьюером: ни одна из удалённых веток не вызывается при `flags.direct_l1_enabled=ON`.

### 1.9. Clarification (§3.2)

L1: `needs_clarification=true` + `clarification_target` (свободная строка-код: `media_target`, `time_range`, …). action=reply + response_act=clarification → **L2 формулирует один короткий контекстный вопрос** (режимная инструкция в L2-промпте; отдельного LLM-вызова нет). Гард: ≤1 вопрос за turn (флаг turn-scoped, без ретраев). Fallback fixed-фраза `clarification_question()` (:555-565) — только при отказе semantic path (L2 fail / L1 fallback). Дет. pre-gate media-без-цели сохраняется только в legacy-ветке и как fallback.

### 1.10. Analytics durable layer (D-4, §18)

**Решение: аддитивная колонка `plan_meta` (JSONB NULL) в существующем `llm_usage_events`** (pg_db.py:310) — одна аддитивная ΔDDL (реестр MigrationStep +1, идемпотентно, backup-guard; SQLite не затронут — таблица PG-only). Писатель — существующий `usage_events.record` (usage_events.py:36) + необязательный параметр `plan_meta`; содержимое — R17-whitelist enum-ов из §1.5. `step="l1_planner"` отличает L1-строки; факты tools (planned/actual) — те же поля + `execution_graph_source` узел.

Читатель: `execution_graph_source` получает durable-оси «24ч/7д» SQL-агрегатом по `llm_usage_events WHERE module='direct_chat' AND step='l1_planner'` — in-memory snapshot-магазин (:189-203) остаётся для live-виджета, durable-слой закрывает честность периодов (докстринг :1126). **Вторая telemetry-модель не создаётся** — та же таблица, +1 nullable колонка. Rollback: старый код игнорирует колонку; kill-switch записи `TOKEN_ANALYTICS_ENABLED` существует.

---

## 2. Блок Cover (F6/F7/F8)

### 2.1. Ordering/бюджеты (п.11)

**Решение: (а) резолв provider prompt_limit для GENERATE (§2.2) + (б) канонический порядок строки `STORY_SCENE → SUMMARY_CONTEXT → BASE_STYLE`** (смена относительно cover_prompt_assembly.py:154/209-218).

Rationale: известный лимит делает порядок безопасным (компиляция укладывается); при unknown-лимите провайдерские тримы/капы режут хвост — хвостом теперь становится детерминированно-восстановимый стиль, а не irreplaceable summary-specific story/context (§12 E2E-маркеры живут в начале строки). Стиль защищён floor 160 (семантика compile_style_prompt) — владельческая инструкция («PERMsoc») доезжает, если физически возможно. Story-minimum уже защищён (`base_prompt_plan` :175-183) — сохраняется. B4 фиксится там же: sent_style перекапируется total_cap (style_cap = min(style_cap, total_cap - story_min - ctx_min)).

Rollback: env `SUMMARY_COVER_PROMPT_ORDER` = `story_first` (default) | `style_first` (legacy-порядок), объявлен в settings (урок D-2).

### 2.2. GENERATE prompt-limit (п.12)

Единый резолвер — существующий `services/image_capabilities.py` (`resolve_capabilities`, operation-параметризация уже есть: `manual_limit_key(..., operation)`; EDIT использует его сегодня):

1. manual override `cover_style.prompt_limit_overrides` — приоритетен (как у EDIT);
2. discovery/metadata (если endpoint отдаёт);
3. unknown → **компиляция под наш кап (1000) БЕЗ silent trim**, manifest честно пишет `prompt_limit: unknown`, agentic event `COVER_LIMIT_UNKNOWN` (enum, R17);
4. provider 400 с сигнатурой too-long (`looks_like_prompt_too_long`/`extract_prompt_limit` — уже есть) → **ровно один shorter-retry** с компиляцией под observed limit (source=`observed_provider_400`), повторный too-long → честный `prompt_limit_unknown_after_retry` (паттерн test_asap44_cover_final_closure.py:783-894 — переиспользуется как для EDIT, так и для GENERATE). Multi-paid loop запрещён: максимум 2 платные попытки на обложку.

### 2.3. Унификация компиляторов (п.13)

**Один server compiler**: `cover_prompt_assembly.base_prompt_plan/compose_base_cover_prompt` — единственный сборщик Base; `compile_style_prompt` остаётся единственным сборщиком Style-Edit (его доп. компоненты STYLE_PROFILE/REFERENCES/RUNTIME — часть контракта EDIT), но ОБА обязаны отдавать единую структуру `CoverPromptManifest` (компоненты + attempts + final_prompt + hash) и уважать один и тот же resolved limit. Три текущих пути сводятся:

- production Base (summary_generator.py:2840) — как есть, + новый порядок/лимит;
- Test Style preview (cover_style_preview.py:511) — уже тот же compile_style_prompt, ок;
- **Summary Test (web/api/summary_test.py:370) — легаци `compose_cover_image_prompt` ЗАМЕНЯЕТСЯ** на `compose_base_cover_prompt(style, story=cover_prompt, ctx=summary_context_text(document))` + запись манифеста. `compose_cover_image_prompt` остаётся только для дет. derive-fallback-пути либо удаляется (Scanner в Phase 4).

Контракт: **CoverPromptManifest — единственный источник** для UI/Analytics/тестов; любое место, отправляющее prompt провайдеру, обязано иметь манифест с `final_prompt == request.prompt` (инвариант тестом, §12).

### 2.4. Anomaly guard §11 (п.14)

В точке сборки Base (summary_generator.py:~2830) детерминированный гард:

```text
if document_plain_nonempty(≥MIN_MEANINGFUL_CHARS) and STORY_SCENE=="" and SUMMARY_CONTEXT=="":
    1) восстановить: story = normalize(cover_prompt) or derive_fallback_cover_prompt(article);
       ctx = summary_context_text(title, paragraphs)   # всегда выводим из финальной статьи
    2) recompile с восстановленными компонентами (component reason="anomaly_recovered")
    3) статья пуста/короче порога → обложки НЕТ, reason="cover_context_missing" (честный)
```

Событие `COVER_ANOMALY` (agentic, enum-only). Generic-style картинка больше не может уйти молча. Дополнительно (B6): instruction Stage-1 cover_prompt (`summary_prompts.py:188`) дополняется требованием «сцена обязана быть specific к этому summary» — проверяется E2E A/B, не кодом.

### 2.5. Read path прозрачности (п.15)

- **Run Inspector**: `GET /api/analytics/pipeline/runs/{run_id}?include_prompt=true` — **global admin only**, fail-closed; возвращает `load_base_cover_manifest` (cover_style_jobs.py:798 — обретает первого production-читателя) + cover_style state-манифест (обе attempts: exact `sent_text`/`final_prompt`, reason, hash). UI: блок «exact prompt» + copy button (index.html:795-841 расширяется; сейчас рендерятся только counts — app.js:10224-10234).
- **Live editor preview**: новый `POST /api/cover/preview-compile` (global admin) — ТОТ ЖЕ server compiler (§2.3): draft style + выбранный test-context → exact compiled text + breakdown (BASE_STYLE/STORY_SCENE/SUMMARY_CONTEXT: original/sent/status/reason + лимит/использовано/остаток). Без контекста — честно «preview context not selected» (§9.4), никаких fake production промптов. Frontend только отображает manifest (§22 п.15).
- Изменение routes.py → ROUTES_SHA256 переутверждается по действующему workflow (прецедент 2.58.57).
- **R17**: полный prompt ТОЛЬКО в этих admin-API ответах; generic logs/analytics без include_prompt — hash/length/enum/reason (analytics.py:616-636 не ослабляются); тест fail-closed (non-admin → 403, prompt отсутствует в ответе).

### 2.6. Runtime-верификация перед/во время Builder (п.16) — порядок внутри Cover-лейна: **F8 → F6**

1. **F8-minimum деплоится первым**: read-path даёт владельцу 2-click проверку гипотезы style-only на живых прогонах (два разных summary → сравнить final_prompt в Run Inspector). Это единственный безопасный prod-канал: SSH не трогается, чек владелец делает в админке.
2. **Локально (Builder, до F6)**: byte-compare golden — `compose_base_cover_prompt(owner_style, story, ctx)` против наблюдаемой владельцем строки из §8.1 ТЗ (стиль владельца ≠ код-дефолт уже подтверждает S6; отсутствие STORY/CONTEXT в наблюдаемой строке подтвердит B1).
3. **Durable-артефакты уже пишутся и после F8 читаются**: media job `prompt` (image_generation.py:1272-1276) + `task_jobs` cover_base `manifest.final_prompt` (summary_generator.py:2859-2875) — расхождение manifest↔request = отдельный RED (§22 п.17).
4. **Provider probe**: прямой вызов image API из локальной среды НЕ выполняется (ключи — protected store прода; SSH/экспорт запрещены). Вместо: (а) unknown→honest-семантика (§2.2.3) безопасна при любом лимите; (б) observed-400 learning в проде после F6 фиксирует реальный кап в манифестах (source=`observed_provider_400`) — это и есть runtime-подтверждение, без paid-циклов.
5. Health живости — только `GET /healthz` (HTTP 200, версия).

---

## 3. Блок Modules (F3/F4)

### 3.1. ModuleSpec registry (п.17) — аддитивный путь

Новый `services/module_registry.py`: `@dataclass ModuleSpec` с полями §4.4 ТЗ (id, title, parent_id, description, master_param, runtime_gate, settings_groups, model_slots, status_source, analytics_anchor, help_anchor, visibility, classification, rationale). Источник канона — Python-реестр; frontend получает его через существующий config/meta-API (аддитивный ключ ответа), `MODULES` в app.js рендерит из registry при наличии записи, fallback на текущий hardcoded список — до завершения миграции (Δ риска = 0).

Инвариант-тесты:
- **M4 (registry drift)**: каждый ProductModuleSpec обязан иметь master_param (существующий ключ каталога), settings_groups ⊆ GROUPS, status_source, help_anchor — иначе тест RED.
- **M2 (inventory)**: статический аудит `mca_gates.KILL_SWITCHES` + последних MCA-волн: каждый operator-facing gate маппится на registry-запись ИЛИ на явную `INFRASTRUCTURE_RATIONALE`-таблицу (fixture-файл в tests). Не превращать 85 env-флагов в 85 чекбоксов: rationale-таблица — легальный исход для maintenance/infra.

Миграция hardcoded MODULES: F3 регистрирует Initiative; F4 — остальных; слияние списков проверяется drift-тестом (JS-список ⊆ registry). Полный переход frontend на server-driven — отдельное будущее решение, в ASAP 7 НЕ входит.

### 3.2. Маппинг orphans (п.18)

| Фича | Класс | parent / поверхность |
|---|---|---|
| Initiative / Intents | **Product Module**, top-level карточка «Инициатива» (tab `mod_initiative`) | master `flags.initiative_enabled` (catalog, default ON, effective=AND с `MCA_INTENTS_ENABLED`); группы `flags_intent` (4 тумблера K2-K4) + `limits_intent` (5 лимитов) — catalog-ключи с env-fallback (`hot.get(key, settings.ENV)`), без дублей storage; связанные budgets/random — ссылка-переход, не дубль (:6456-6460 «Настройки блока» больше не показывает чужие ключи). Страница: requested/effective/source, last heartbeat, pending, last decision, skip/defer reason, next due (из intent_snapshot, status_service.py:1034) |
| Stories / Episodes | Submodule «Память» | registration + группа toggles (`MCA_STORIES_*`/`MCA_EPISODES_*` → catalog flags), статус уже есть |
| SelfModel / Character (7 env-осей) | Submodule «Характер» (parent Persona/Досье) | catalog flags-группа (Advanced-размещение), effective-дисплей |
| Experience / Lessons | Submodule «Память» | настройки ЕСТЬ (memory_experience, param_catalog.py:2228) — добавить только registration/родителя, настройки не дублировать |
| Random / Quantum | Submodule «Случайность» (shared, parent «Память», rationale в registry) | настройки ЕСТЬ (memory_random, random.uses.*, keys_random) — добавить owner-карточку-секцию и ссылки из Initiative/Sleep |
| Temporal Factcheck | OK — эталон | не трогать (M3-тест уже зелёный по сути) |
| Embeddings/GraphRAG, Dossier/maintenance | Infrastructure/Maintenance | rationale в registry; settings-раскладку проверить на «понятный parent» (M2-аудит) |

### 3.3. §4.3 общий паттерн toggle (п.19)

`module_registry.effective_gate(module_id) -> (requested, effective, source)`:

```text
env_emergency OFF → effective OFF, source="emergency_env"   (env важнее UI)
product toggle OFF → effective OFF, source="product_toggle"
оба ON → effective ON, source="both"
```

UI карточки: requested (значение тумблера), effective (факт runtime-гейта), source/reason, restart-required если env меняли (честно). Паттерн обязателен для Initiative и всех новых product toggles F4.

---

## 4. Блок Chat lifecycle (F5, п.20)

**Root cause** (P7-C): хендлеры на `chat_member`-observer (chat_lifecycle.py:76/148), собственное вступление бота приходит как `my_chat_member` → пустой observer → профиля нет. Фикс:

1. **`@chat_lifecycle_router.my_chat_member`** — два хендлера join/leave с теми же `ChatMemberUpdatedFilter` (IS_NOT_MEMBER>>IS_MEMBER и обратно), переиспользуют существующие `upsert_profile_on_join`/`set_active`/`ensure_gates_defaults` (:89-107). `my_chat_member` доставляется всегда, вне allowed_updates — polling-конфигурация (bot.py:1220) не требует правок. Существующие `chat_member`-хендлеры СОХРАНЯЮТСЯ (полезны при бот-админе для чужих событий… фактически `_is_bot_user` их отфильтровывает — решение: оставить без изменений, они безвредны; удалять не в этом эпике).
2. **Fallback registration**: тонкий fail-open `ensure_group_profile(chat_id)` в единой точке входа message-роутинга (до диспетчеризации, только `chat_id<0`, только при отсутствии профиля в кэше, с backoff-памятью чтобы не звать на每 message) — вызывает существующий `chat_lore_store.ensure_profile` (:373-386). Гейт `CHAT_PROFILE_FALLBACK_ENABLED` (env, default ON, объявлен в settings).
3. **Re-add**: join-хендлер идемпотентен (upsert + set_active(True), гейты-дефолты только для новых — уже так, :101-102).
4. **Group→supergroup migration**: существующий `on_chat_migrated` (:171+) работает — добавить только `set_active(new, True)`/upsert нового профиля, если его ещё нет (сейчас мигрирует chat_links/profile — проверить покрытие C9 тестом).
5. **Selector refresh UX**: `loadAccessCtx()` вызывается при открытии селектора/drawer и в `toggleScope` (app.js:10829 — добавить re-fetch); **UX-контракт inactive: показывать с badge «неактивен»** (не скрывать): global admin должен видеть все известные чаты (соответствует SQL :46-53, где is_active возвращается но не фильтруется); badge добавляется в `activeChatOptions` (:4242-4265).
6. **RBAC** не меняется (access.py:192-238 — контракт уже корректен). Ручных DB-фиксов нет (§22 п.14).

---

## 5. Срезы F1–F9 (п.21): write-области, зависимости, параллелизм

| Slice | Scope | Write-области | Зависимости | Параллельность |
|---|---|---|---|---|
| **F1** Direct L1 core | §1.1-1.9 | `services/direct_l1.py`*NEW*, `services/direct_capabilities.py`*NEW*, `direct_chat_service.py` (region 2290-2830, sandwich :347), `response_extent.py` (demote), `chat_prompts.py` (L1 канон), `prompt_migrations.py`, `direct_llm_react.py` (legacy-mark), `config/settings.py` (D-2 декларации + DIRECT_L1_ENABLED), `tool_schemas.py` (только чтение имён) | — | SERIALIZE с F2 (общий service-файл); параллельна с F3/F5/F8 |
| **F2** Direct settings+analytics | §1.6, §1.10, §18-19 ТЗ | `param_catalog.py` (группа direct_l1), `config/settings.py`, `usage_events.py` (+plan_meta), `pg_db.py` (ΔDDL+1), `execution_graph_source.py` (durable axes), `web/api/analytics.py` (L1-узлы), `web/index.html`, `web/app.js` [SECTION-DIRECT-UI] | **BLOCKED_BY F1** | после F1 |
| **F3** Module registry + Initiative | §3.1, §3.3 | `services/module_registry.py`*NEW*, `param_catalog.py` (flags_intent/limits_intent), `mca_gates.py`/`mca_intents.py` (AND-гейт), `web/app.js` [SECTION-MODULES], `web/index.html` (tab), `status_service.py` (requested/effective/source) | — | PARALLEL_SAFE (секция app.js заморожена за F3) |
| **F4** Module completeness | §3.2 | `param_catalog.py` (stories/character группы), `web/app.js` [SECTION-MODULES], `module_registry.py`, `config/settings.py` (декларации) | **BLOCKED_BY F3** | после F3 |
| **F5** Chat lifecycle | §4 | `handlers/chat_lifecycle.py`, `bot.py` (точка fallback), `chat_lore_store.py` (без правок контракта), `web/app.js` [SECTION-ACCESS], `web/api/access.py` (badge-поле уже есть) | — | PARALLEL_SAFE |
| **F8** Cover exact-prompt read path | §2.5, §2.6 | `web/api/analytics.py` (include_prompt), `web/api/cover_styles.py`/`cover_manifest`, `cover_style_jobs.py` (reader), `web/index.html`, `web/app.js` [SECTION-COVER-RUNS] | — | PARALLEL_SAFE; **идёт первым в Cover-лейне** |
| **F6** Cover content-loss fix | §2.1, §2.2, §2.4 | `cover_prompt_assembly.py`, `summary_generator.py` (S8+guard), `image_generation.py` (GENERATE limits), `image_capabilities.py` (GENERATE op), `cover_style_jobs.py` (B4/B5), `summary_prompts.py` (specific-scene), `config/settings.py` (ORDER env) | BLOCKED_BY F8 (runtime-эвиденс перед фикс-подтверждением; кодово независим) | SERIALIZE с F7 (общие cover-файлы) |
| **F7** Cover live preview + унификация | §2.3, §2.5 (preview) | `cover_prompt_assembly.py`, `web/api/summary_test.py` (:370 замена), `web/api/cover_styles.py` (preview-compile), `web/index.html`, `web/app.js` [SECTION-COVER-UI] | **BLOCKED_BY F6** | после F6 |
| **F9** Help resync | §13/§20/§22 п.20 | `info_service.py` (canon v8: §13 сузить после runtime-truth), `config_cache.py` (миграция канона) | BLOCKED_BY F1+F6 (только после подтвержденного behavior) | последним |

### 5.1. Freeze-контракт web/app.js (общий для F2/F3/F4/F5/F7/F8)

Решение: **секционная нарезка + фиксированный порядок слияния** (вынос примитивов — оверинжиниринг для одного эпика).

```text
SECTION-MODULES      (MODULES/WORKSPACE_TABS, ~:515-660)        → F3, затем F4
SECTION-DIRECT-UI    (Direct settings/L1-L2 cards ~:10340+, Pipeline widget ~:1817, ~:5387) → F2
SECTION-ACCESS       (~:4242-4265, :4828-4860, :10829)          → F5
SECTION-COVER-RUNS   (Run Inspector render ~:1817+/5387+)       → F8
SECTION-COVER-UI     (style editor/test-style ~:10055-10234)    → F7
```

Правила: PR слайса трогает ТОЛЬКО свою секцию (+ общие helpers в шапку файла с префиксом слайса, добавление — ok, правка чужой секции — нет); порядок слияния F8→F7 и F3→F4 фиксирует главного ребейзера; конфликты = нарушение секций (Reviewer возвращает).

### 5.2. Freeze-контракт direct_chat_service.py (F1/F2)

F1 владеет регионом 1900-3100 (rewire pipeline); F2 НЕ трогает его вовсе — только `param_catalog/settings/pg_db/usage_events/execution_graph/analytics/web`. Точка стыковки: F2 читает `L1Plan`/метрики из `direct_l1.py` (публичный контракт §1.3), который F1 уже залил. ⇒ F2 строго после F1.

### 5.3. Порядок волн (каждый слайс deployable)

```text
Wave 1 (параллельно): F5 (P0 user-bug), F8, F3
Wave 2 (параллельно): F1, F6 (после F8-эвиденса)
Wave 3 (параллельно): F2 (после F1), F7 (после F6), F4 (после F3)
Wave 4:               F9 (после runtime-truth F1+F6)
```

---

## 6. Тест-план (п.22) — targeted-first (ASAP 4.2 §49-52: полный suite только на границах волн)

| Slice | Таргет-тесты (новые файлы tests/test_asap7_*.py) | Lifecycle |
|---|---|---|
| F1 | `direct_l1`: D1-D12 сценарные (fake LLM), D13 (outage→fallback, no duplicate), D14 (invalid JSON→1 repair→fallback), D15 (hallucinated capability); CONTRACT: D11 (нет глобального «коротко» в финальном промпте), force→REPLY, SILENT→🗿, топология (≤2 semantic calls на reply-путь); legacy-паритет при DIRECT_L1_ENABLED=false | CONTRACT + REGRESSION(D-1/D-2/D-3) |
| F2 | каталог-группа/slot effective==configured; ΔDDL миграция идемпотентно; durable-оси 24ч/7д по plan_meta; §18-виджет поля | CONTRACT |
| F3 | M1 (Initiative полный чек), M4 (drift), M2-fixture (маппинг gates) | CONTRACT |
| F4 | M2-расширение новыми registration, M3 (parent submodules) | CONTRACT |
| F5 | C1-C9: synthetic `my_chat_member` join/leave/re-add/migrate, fallback-registration, RBAC-неослаблен, stale-localStorage (уже есть — не ломать) | REGRESSION(P7-C-1/2) |
| F6 | E2E A/B semantic markers (§12: final_prompt содержит маркер A/B, A не протёк); §11 guard (recovered / cover_context_missing); B4 recaper; B5 ceiling-bound; unknown→retry→honest (паттерны test_asap44) | CONTRACT + REGRESSION(B1/B2) |
| F7 | compiler-parity golden (3 входа → одинаковый манифест); preview fail-closed auth; Summary Test = production-сборка | CONTRACT |
| F8 | R17: non-admin 403 + отсутствие prompt; manifest.final_prompt == request.prompt | CONTRACT |
| F9 | guide-content v8 тесты (паттерн test_mca23_guides_content) | CONTRACT |

Полный pytest + JS-харнессы — один раз на волну (перед деплоем Wave 1/2/3/4), плюс перед финальным отчётом. Никаких полных прогонов после каждой мелочи.

---

## 7. Риски / откаты (п.23)

| Риск | Митигация / откат |
|---|---|
| L1 outage / мусорный JSON | ladder §1.6: slot→main→deterministic; 1 repair max; duplicate-reply невозможен (инвариант D13) |
| L1 line целиком | `DIRECT_L1_ENABLED=false` (env, ОБЪЯВЛЕН в settings) → байт-паритет legacy; product-тумблер `flags.direct_l1_enabled` — штатный путь (§4.3 AND) |
| Латентность 2 serial calls | timeout L1 15s (каталог); pre-gates короткие пути не меняются; РИСК принят ТЗ (топология §2.7) |
| Cover ordering | `SUMMARY_COVER_PROMPT_ORDER=style_first` → прежний порядок байт-в-байт; limit-resolver OFF → honest-unknown (без silent trim в любом случае) |
| ΔDDL plan_meta | аддитивная nullable; старый код игнорирует; отккат = git revert (колонка инертна) |
| my_chat_member фикс | аддитивные хендлеры; fallback-ensure за флагом; chat_member-хендлеры не удаляются |
| app.js конфликты | секционный freeze §5.1, порядок слияния, Reviewer-проверка секций |
| Реестр модулей | аддитивный; JS fallback на hardcoded при недоступности registry-данных |

Порядок деплоя = §5.3 волны; каждый слайс самостоятелен (F6 без F7 работает, F3 без F4 работает и т.д.).

---

## 8. Observability (сводно)

- Direct: agentic `L1_PLAN`/`L1_CAPABILITY_REJECTED`/`CLARIFY` (R17 enum) + usage `step="l1_planner"` + `plan_meta`; Run snapshot узлы «L1 Planner / Tools planned / Tools actual / Clarification / L2 Writer / Delivery» (§18 ТЗ); карточки UI L1/L2 показывают effective model/source (D-5).
- Cover: `COVER_ANOMALY`, `COVER_LIMIT_UNKNOWN`, manifest в task_jobs/media jobs (уже пишутся) + read-path F8; generic logs — hash/len/enum only.

## 9. DoD-мэппинг

Каждый пункт §23 ТЗ покрыт: Direct — §1 (все), Modules — §3, Multi-chat — §4, Cover — §2, Report integrity — §6/§2.6 + существующее правило §20 (OWNER PENDING не называется VERIFIED; H4-хвост MCA-23 остаётся owner gate, ASAP 7 его молча не закрывает).

## 10. Вопросы владельцу

**Пусто.** Все развилки разрешены ТЗ §0/§2.7/§22 + кодом. Выбор «badge vs hide» для inactive-чатов ТЗ делегировал Architect (§7.3) — зафиксировано: badge «неактивен», без скрытия (§4.5).
