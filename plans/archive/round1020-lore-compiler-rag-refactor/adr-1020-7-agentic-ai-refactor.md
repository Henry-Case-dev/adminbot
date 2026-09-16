# ADR-1020-7 — Agentic AI: fail-safe tool-loop, reasoning-парсинг, Context Middleware, `graph_facts` v12, EN-схемы (БЛОК 7)

- **Статус:** 🟢 **Принято** (Step 2 @Architect, 16.09.2026, ред. 2) — санкционировано Human Gate
  (БЛОК 7 ТЗ `plans/current_task.md:293-319`; ответы О3/О5/О7). Отдельного гейта не требует.
- **Раунд:** 10.20, **новая фаза G** (`agentic-ai-refactor-round1020`), задачи T-1918+ (нумерация @PM)
- **Спека:** [`spec.md`](spec.md) §18 (§18.1–§18.4)
- **Аудит-основание:** `plans/reports/round1020_llm_engine_audit.md` §Q1.2-1/2/5/7, §Q2.2-1/2, §Q3.2-1/2/3/6, §Q4.2-3
- **AMEND:** [ADR-1020-1](adr-1020-1-context-metadata-contract.md) (middleware + ID/forward-политика + v12),
  частично [ADR-1020-2](adr-1020-2-tool-routing-chronology.md) §4 (EN-схемы — расширено на все 8),
  [ADR-1020-6](adr-1020-6-story-delivery-format.md) (снятие канона локально)
- **Накопленные ограничения:** `round10.19_scanner_audit.md` (§8.5/§9.1 sentinel контекста S10.19-13 CLOSED,
  §9.2 S10.19-15/-18, §10.2 S10.19-23), `plans/reports/global_map.md` (SQLite v11 baseline)

## Контекст

Аудит round1020 (Фаза A, READ-ONLY) выявил четыре класса дефектов движка, которые ТЗ БЛОК 7 переводит в скоуп:

1. **Tool-loop деградирует в тишину.** Исчерпание `TOOL_MAX_ROUNDS=4` → `raise LLMBadResponseError`
   (`services/tool_loop.py:91-93`) → `direct_chat` отвечает молчанием + 🗿 (`direct_chat_service.py:647-655`).
   `LLMError` на `round_index > 0` перехватывается только для `round_index == 0` (`tool_loop.py:49-57`) →
   поздние раунды роняют оплаченный ответ в `CHAT_ERROR_PHRASES`. Потерян и бюджет, и «надуманный» контекст.
2. **Нет Scratchpad/Reasoning.** `generate_chat` читает только `content`/`tool_calls`
   (`services/llm_client.py:1005-1032`); при пустом `content` и непустом `reasoning_content` бросается
   `LLMBadResponseError("empty content (no tool_calls)")` (`:1031-1032`) — reasoning-модели несовместимы.
   Текстовые теги-черновики (`<reasoning>…</reasoning>`) уезжают пользователю как есть (единственная
   «обработка» — `answer = str(raw).strip()`, `direct_chat_service.py:656`). Канон `CHAT_SYSTEM_PROMPT`
   режет ответ до 1–2 предложений (`chat_prompts.py:171-172`) — это ломает `compile_lore_story` и фактчек.
3. **Контекст собирается монолитно, метаданные режутся бюджетом.** ≥14 точек подачи контекста (§2.3),
   единого middleware нет; `_apply_context_budget` (`direct_chat_service.py:1200-1351`) режет блоки по токенам
   и может обрезать/потерять `[…]`-заголовок метаданных; у `graph_facts` нет `tg_message_id`/`forward_from`
   (`database.py:286-296`), поэтому ID-политика и «Переслано: …» для фактов недоступны (ADR-1020-1 п.3–5).
4. **Схемы тулов на русском.** `services/tool_schemas.py` — 8 схем, описания на русском; шапка `:1-5`
   объявляет канон «не менять без ревизии spec». LLM-роутинг по русским `description` менее предсказуем.

## Решение

### 1. Tool Recursion Fail-Safe (Graceful Degradation)

- `chat_with_tools` возвращает **`ToolLoopResult(str)`** — подкласс `str` с атрибутами
  `rounds_used: int`, `degraded: bool`, `reason: str` (`ok` | `round_limit` | `llm_error`),
  `tool_trace: list[dict]` (`{"round","tool","ok","out_chars"}`).
  Подкласс `str` выбран осознанно: `direct_chat_service.py:656` (`str(raw).strip()`), `:663`/`:667`
  (`send_chunked_reply`/`remember_bot_reply`) работают **без правок** — нулевой риск для 6326 тестов.
- При исчерпании раундов или `LLMError` на `round_index > 0` — **не бросать**, а вернуть:
  сначала последний непустой `content`, накопленный в раундах; если его нет — саркастичную заглушку
  `TOOL_LOOP_FALLBACK_PHRASE` (код-константа; **каталог-Δ = 0**).
- `NoApiKeyForChat` и provider-reject на `round_index == 0` (plain-фолбэк, FR-15) — **без изменений**.
- Пустой финал (нет `tool_calls` и нет текста) — **прежнее** `LLMBadResponseError` → молчание+🗿 (FR-14/65.1):
  это не «потерянный» ответ (думать было нечего); сохраняем существующий контракт и эталоны.
- Логирование потерянных раундов: `[tools] degraded | reason=… | rounds_used=… | lost_rounds=… | tools=… | partial_chars=…`
  — **без аргументов и текстов** (R17).

### 2. Scratchpad / Reasoning

- `LLMChatResult` (`llm_client.py:219-225`, `@dataclass(frozen=True)`) получает **аддитивное**
  `reasoning: str | None = None`; `generate_chat` читает `reasoning_content` (алиасы `reasoning`/`thinking`).
  Guard `:1031-1032` ослабляется: `raise` только если пусто **и** `content`, **и** `tool_calls`, **и** `reasoning`.
- `reasoning` **никогда не отправляется** пользователю (это черновик); reasoning-only ответ логируется
  (`reasoning_chars=N`) и обрабатывается штатной деградацией, без нештатного исключения.
- Новый модуль `services/reply_postprocess.py::strip_reasoning_tags(text)` — middleware среза тегов
  `<reasoning>/<thinking>/<scratchpad>/<analysis>/<thought>` (в т.ч. незакрытых, defensive).
  Применяется в **4 путях вывода:** direct (`:656`), финал tool-loop, factcheck (`factcheck_service.py:79`),
  summary (`summary_generator.py:238`, через `cleanup_llm_text`). Без тегов — no-op (байт-в-байт).
- **Снятие канона 1–2 предложений локально:** `compile_lore_story` — изоляцией канона
  (`LORE_STORY_SYSTEM_PROMPT`) + режимом доставки (ADR-1020-6) + использованием готового текста истории при
  `ctx.lore_compiled`; `factcheck` — `FACTCHECK_SYSTEM_PROMPT` не наследует `CHAT_SYSTEM_PROMPT`, явно
  разрешён полный вердикт. Глобальный `CHAT_SYSTEM_PROMPT` **не меняется** (ядро характера).

### 3. Context Assembly — единый Middleware + метаданные-приоритет + `graph_facts` v12

- Новый **тонкий** `services/context_middleware.py` над `canonical_context.format_context_item`:
  `context_item(...)`, `metadata_header(text)`, `truncate_keep_header(block, limit_tokens, kind)`.
  Это **AMEND** ADR-1020-1 п.8 («без middleware») — обёртка, а не переписывание сборки:
  `_build_user_content`/порядок блоков/дедуп/реранк/MMR **не меняются**.
- **Приоритет метаданных:** ведущий `[…]`-заголовок неприкосновенен при любом усечении; режется только body.
  `_apply_context_budget:1200-1351` и `_truncate_block:1353+` используют `truncate_keep_header` для
  контентных kinds; неприкосновенные kinds и sentinel-семантика контекста (`0`=не задано, `-1`=безлимит
  до `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`) — сохраняются (не регрессируем S10.19-13).
- **`graph_facts` (SQLite v11 → v12):** `tg_message_id INTEGER` (nullable) + `forward_from TEXT NOT NULL DEFAULT ''`.
  Идемпотентная миграция `_migrate_graph_facts_metadata_v12()` с guard по `PRAGMA table_info`, FTS не пересоздаётся,
  новых индексов нет (документировано). **PG — no-op** (таблицы `graph_facts` в PG нет). ID/forward-политика §2.2
  расширяется: `tg:<tg_message_id>` для фактов, где он известен; иначе `fact:<id>` и сегмент опускается (R16).

### 4. Agentic Factorization — Schemas EN + строгая типизация

- Все `description` **8** схем и описания параметров переводятся на английский; имена, `enum`, `required`,
  порядок `TOOL_CALLING_TOOLS` **не меняются**. Шапка канона `tool_schemas.py:1-5` переписывается (ред. 2),
  эталон `plans/docs/canon/architecture.md` — тем же коммитом (ADR-1013-3).
- Строгая типизация: `additionalProperties: False` у всех; `enum`/`minimum`/`maximum` заполнены; добавлено
  отсутствующее `description` у `summarize_video.mode`. Семантических изменений параметров нет.
- **`tool_choice="auto"` НЕ форсируется** — остаётся backlog (§16 спеки).

## Альтернативы и отклонения

- **Отдельная функция `chat_with_tools_result` + прежняя `chat_with_tools`** — отклонено: дублирование кода и
  риска рассинхрона; `str`-подкласс даёт совместимость без дубля.
- **Деградация и на пустом финале** (заглушка вместо 🗿) — отклонено: меняет эталоны FR-14/65.1 без пользы
  (терять нечего) и расширяет регресс-поверхность.
- **Отправлять `reasoning_content` как ответ при пустом `content`** — отклонено: черновик не должен попадать
  пользователю; при необходимости промоушен вводится отдельным флагом в следующем шаге.
- **Полный рефакторинг контекста на `ContextBlock`-объекты** — отклонено (§18.3): риск сломать бюджет/дедуп/MMR;
  тонкий middleware даёт нужный инвариант метаданных.
- **DDL `graph_facts` в PostgreSQL** — отклонено: таблицы нет, добавлять её вне скоупа.
- **Форсирование `tool_choice` / LLM-intent-router / суб-агенты** — отклонено (backlog §16): ТЗ 7.4 ограничено
  EN-схемами и типизацией.
- **Хранить `tg_message_id` для фактов в JSON-поле вместо колонки** — отклонено: поиск/ID-политика непарсируемы
  без индекса, R16-контракт нечёткий.

## Каталог-Δ

**Δ = 0** (заглушка — код-константа; `graph_facts`-колонки — DDL, не каталог; EN-схемы — код).

## Последствия

- Ответы перестают «пропадать» на 5-м шаге агентного цикла; появляется телеметрия цепочек (`tool_trace`).
- Reasoning-модели больше не роняют движок; черновики не утекают пользователю.
- Метаданные контекста защищены от бюджет-капа → предсказуемость «Дата/Время/Автор» во всех пайплайнах.
- SQLite **v12** — миграция идемпотентна/аддитивна; прогон по legacy-БД обязателен.
- EN-схемы меняют роутинг → снапшот + роутинг-тесты; риск `english-schema-regression` берётся под наблюдение.
- Риски и митигации — §12 спеки: `reasoning-parsing-compat`, `budget-cap-metadata-regression`,
  `graph-facts-migration`, `english-schema-regression`, `infra-graph-facts-id-policy`, `context-middleware-scope-creep`.

## Инварианты

`TOOL_MAX_ROUNDS`/`_TOOL_CALLS_PER_ROUND_MAX` не менять; имена/состав/порядок тулов и канон R9 — не менять;
`CHAT_SYSTEM_PROMPT` (ядро характера) — не менять; `_build_user_content`/дедуп/реранк/MMR — не менять;
sentinel-семантика контекста (S10.19-13) — не регрессировать; R16 (аддитивные поля, id-ключ),
R17 (без текстов/секретов в логах); `user_version` для `lore_stories` не бампать (О7); канон-миграции атомарны
(код + `plans/docs/canon/` + тесты одним коммитом); порядок роутеров `bot.py` не менять; `media/`/`.env` не трогать.
