# round1020 — READ-ONLY аудит LLM-движка (БЛОК 4 ТЗ)

> **Фаза A эпика `round1020-lore-compiler-rag-refactor`** (T-1866…T-1870, Step 2 @Architect, 16.09.2026).
> **Режим:** READ-ONLY по коду. Ни один файл вне `plans/**` не изменён; коммитов нет.
> **Baseline:** HEAD `2f3e1f0` (docs-финал 10.19), pytest 6326/0, SQLite v11, APP_VERSION 2.57.0.
> **R17:** секретов/значений env/токенов в отчёте нет (в т.ч. plaintext-секрет из `plans/current_task.md` не цитируется).
> **Метод:** чтение `services/tool_loop.py`, `services/tool_router.py`, `services/tool_schemas.py`,
> `services/direct_chat_service.py`, `services/llm_client.py`, `services/payload_builder.py`,
> `services/chat_prompts.py`, `services/summary_memory.py`, `services/summary_generator.py`,
> `services/summary_cleanup.py`, `services/summary_xml.py`, `services/factcheck_service.py`,
> `services/smartmodule_utils.py`, `services/database.py`, `config/settings.py`, `web/app.js`.

---

## Сводка (TL;DR)

| Вопрос ТЗ | Вердикт | Главный Blocker |
|---|---|---|
| **Q1 Tool Recursion** | **Реализована и многотуровая**, не single-turn | тулы есть только в `direct_chat`; нет вложенности/планирования; лимит раундов → **тишина** вместо частичного ответа |
| **Q2 Scratchpad / Reasoning** | **Отсутствует полностью** | нет парсинга `reasoning_content`; нет среза тегов; доставка **plain-text**; канон «1-2 предложения» **убьёт длинный storytelling** |
| **Q3 Context Assembly** | **Монолит + XML-теги, один system + один user** | нет middleware/интерцепторов → БЛОК 0 придётся внедрять в ~10+ точек вручную; Time Injection в **head system** конфликтует с каноном prompt-cache |
| **Q4 Agentic Factorization** | **Один универсальный промпт + rule-based Fast-Track** | LLM-intent-router нет; `tool_choice="auto"` не форсируется; фактчекер вообще без тулов |

**Главное расхождение ТЗ с реальностью:** в БЛОКЕ 4 ТЗ формулировка допускает, что цикл «обрывается после первого вызова» — **это не так**, рекурсия есть (`TOOL_MAX_ROUNDS=4`). Настоящий дефицит — не цикл, а **отсутствие слоёв вокруг него**: планирования, наблюдаемого reasoning, метаданных в tool-результатах и разделения «решить» / «синтезировать».

---

## Q1. Tool Recursion (рекурсия инструментов)

### 1.1 Текущее состояние

**Точка входа (единственная).** Инструменты подключены только к `direct_chat`:

- `services/direct_chat_service.py:620-627` — `chat_with_tools(self.llm, payload, tools=TOOL_CALLING_TOOLS, router=self.tool_router, ctx=ToolContext(chat_id, query, bot=bot, reply_to_message_id=…, user_id=…), temperature=…, chat_id=chat_id)`;
- `services/direct_chat_service.py:628-631` — если `tool_router is None`, обычный `llm.generate(payload)` (путь без тулов, обратная совместимость);
- импорт: `services/direct_chat_service.py:130` (`from services.tool_loop import chat_with_tools`), `:132` (`TOOL_CALLING_TOOLS`).

**Цикл** — `services/tool_loop.py::chat_with_tools` (`:28-93`):

| Механика | Где |
|---|---|
| `TOOL_MAX_ROUNDS = 4` (1 стартовый + до 3 tool-раундов) | `tool_loop.py:24` |
| `_TOOL_CALLS_PER_ROUND_MAX = 2` (лишние вызовы в раунде обрезаются) | `tool_loop.py:25`, обрезка `:67-71` |
| Вызов LLM с `tool_choice="auto"` | `tool_loop.py:43-46` |
| Нет `tool_calls` и есть текст → **возврат финального текста** | `tool_loop.py:58-64` |
| Нет `tool_calls` и нет текста → `LLMBadResponseError` | `tool_loop.py:65` |
| `assistant`-сообщение с `tool_calls` кладётся историей | `tool_loop.py:72-76` |
| Исполнение каждого тула через `router.dispatch(name, args, ctx)` | `tool_loop.py:77-82` |
| Результат → `{"role": "tool", "tool_call_id": …, "content": output}` и **новый раунд LLM** | `tool_loop.py:87-88`, цикл продолжается |
| Ошибка тула → текст `ОШИБКА <tool>: <class>` уходит модели | `tool_loop.py:83-88`; `tool_router.py:315-322` |
| Лимит раундов исчерпан → `LLMBadResponseError("no final answer within round limit")` | `tool_loop.py:91-93` |
| Деградация: провайдер отверг `tools` на 1-м раунде → один обычный вызов без тулов | `tool_loop.py:49-57` |

**Реестр исполнения** — `services/tool_router.py:300-322` (таблица из **7** имён: `execute_web_search`, `query_chat_memory`, `dig_into_lore`, `summarize_video`, `download_media`, `get_bot_health`, `get_recent_history`). `dispatch` **никогда не бросает**, последовательное исполнение (параллелизма нет — `tool_router.py:1-9`).

**Дополнительно — детерминированный пре-гейт:** `services/direct_chat_service.py:577-584` → `_dig_pre_gate_block` (`:919-975`) по маркерам ностальгии **принудительно** исполняет `dig_into_lore` ДО генерации и вставляет `<dig_result>` в user-контент; раунды `TOOL_MAX_ROUNDS` при этом **не тратятся**.

**Вывод по Q1:** бот **способен** вызвать инструмент → получить результат → проанализировать → вызвать другой инструмент / тот же с другими аргументами → и только затем отдать финальный текст. Это полноценный multi-turn tool-loop (не single-turn). Жёсткий предел — **4 LLM-вызова суммарно** на сообщение.

### 1.2 Blockers (чего не хватает для Agentic AI)

1. **Лимит раундов завершается тишиной, а не частичным ответом.** `tool_loop.py:91-93` бросает `LLMBadResponseError` → `direct_chat` отвечает молчанием + 🗿 (`direct_chat_service.py:647-655`). Для агентного цикла «search → read → verify → rewrite» нужен graceful degrade («отвечай тем, что собрал»), иначе 5-й шаг = потеря ответа и потерянного бюджета.
2. **Ошибка LLM на раунде > 0 роняет весь ответ.** `tool_loop.py:49-57` перехватывает только `round_index == 0`; на поздних раундах `LLMError` уходит наверх → фраза-заглушка (`direct_chat_service.py:682-699`). Агентный цикл обязан быть устойчивым к сбою на любом шаге.
3. **Тулы есть только у `direct_chat`.** `factcheck_service.py:69-74` вызывает `llm.generate(...)` **без** `tools`; `search_service`, `summary_generator`, `youtube/web summarizer`, воркеры (`dream_worker`, `lore_worker`, `nostalgia_worker`) — тоже без тулов. Это прямой вход в БЛОК 6.2 (Full Tool Access фактчекера).
4. **Нет вложенности/суб-агентов.** `dispatch` — терминальный вызов метода; инструмент не может запустить собственный под-цикл `chat_with_tools` с урезанным tool-сетом (нет API, нет отдельного ctx-стека). Внутренние LLM-вызовы есть только внутри самих сервисов (`summarize_video` → `YoutubeSummarizerService`, `get_bot_health` → `CheckupService`) и они не часть tool-loop.
5. **`ToolContext` не несёт состояния цикла** (`tool_router.py:261-275`: только `chat_id`, `query`, `bot`, `reply_to_message_id`, `user_id`). Нет: списка уже вызванных тулов, накопленных артефактов, остатка бюджета — то есть нет базы для дедупа повторных одинаковых вызовов и для «агентной памяти» между раундами.
6. **Нет планирования (plan/act).** Модель не получает инструкции «сначала составь план, потом вызывай»; нет промежуточного артефакта плана. Всё — «жадный» выбор тула на каждом раунде.
7. **Нет наблюдаемости для агентности.** Логи — только `[tools] round=/tool=/out_chars=` (`tool_loop.py:89-90`); нет метрик «сколько раундов реально понадобилось», «какие цепочки тулов», «сколько раз тул вернул пусто и модель всё равно продолжала». Без этого нельзя ни отладить агентный цикл, ни измерить эффект.
8. **Нет stop-condition по результату тула.** Если тул вернул «ничего не нашёл» (`tool_router.py:468`, `:559`, `_HISTORY_EMPTY:95`), код не имеет права остановить цикл — решает только модель, что провоцирует лишние раунды и расход.

---

## Q2. Scratchpad / Reasoning (механика черновика)

### 2.1 Текущее состояние

**Парсинг ответа модели** — `services/llm_client.py::generate_chat` (`:959-1045`):

- `content = message.get("content")` (`:1006`) — берётся **только** поле `content`;
- `tool_calls` — из `message.get("tool_calls")` (`:1008-1030`);
- `if content is None and not tool_calls: raise LLMBadResponseError("chat/completions: empty content (no tool_calls)")` (`:1031-1032`);
- `LLMChatResult(content, tool_calls, finish_reason)` (`:1041-1045`).

**Поля `reasoning_content` / `reasoning` / `thinking` / `extra_body` НЕ читаются и НЕ отправляются.** Grep по репозиторию (`reasoning|scratchpad|thinking|think>|hidden`) в `services/` не находит ни одной обработки (единственные совпадения — `hidden_from_local` из RBAC в `services/access.py`). То есть транспорт — «голый» OpenAI-совместимый `/chat/completions` без флагов reasoning (`llm_client.py:975-980`: payload = `model`, `messages`, опц. `temperature`, опц. `tools`/`tool_choice`).

**Что происходит с текстом перед отправкой в Telegram** (`services/direct_chat_service.py:656-663`):

```python
answer = str(raw).strip()                      # ← вся «обработка»
...
sent_id = await send_chunked_reply(bot, chat_id, answer, message.message_id)
```

- **Никакого среза тегов нет.** Единственная «чистка» в проекте — `services/summary_cleanup.py::cleanup_llm_text` (`:8-22`), и она заменяет **только типографику** (`«»„“—–` → `"-`), тегов не касается. Причём в `direct_chat` она **не вызывается вообще** (только `factcheck_service.py:79` и `summary_generator.py:238`).
- **Доставка — plain text:** `send_chunked_reply(..., parse_mode=None)` по умолчанию (`services/smartmodule_utils.py:113-120`, `:143`). Markdown/HTML не рендерится; `rich_message` в кодовой базе отсутствует.

**Вывод по Q2:** если модель напишет мысли в тегах вида `...`, **эти теги уедут пользователю как есть**. Механики «вырезать черновик» в проекте нет ни в одном слое.

### 2.2 Blockers

1. **Нет чтения `reasoning_content`.** Если провайдер вернёт reasoning-модель с пустым `content` и заполненным `reasoning_content`, код упадёт в `LLMBadResponseError("empty content (no tool_calls)")` (`llm_client.py:1031-1032`) → молчание + 🗿 (`direct_chat_service.py:647-655`). **Reasoning-модели сейчас несовместимы с движком.**
2. **Нет пайплайн-стадии «пост-обработка ответа direct_chat».** Точка `direct_chat_service.py:656` — единственный chokepoint, но явной функции-хука нет; чтобы добавить срез тегов, надо вводить новую стадию (и решить, применять ли её ко всем 4 путям вывода: `direct`, `factcheck`, `summary`, `tool`).
3. **Нет требования/контракта на «скрытый черновик».** Канон `CHAT_SYSTEM_PROMPT` (`services/chat_prompts.py:139-172`) **запрещает** маркдаун и ограничивает ответ **1-2 предложениями** (`:171-172`) — то есть прямо сейчас модель структурно не имеет места для reasoning и не имеет права на длинный текст.
4. **Доставка не поддерживает формат storytelling.** БЛОК 1 ТЗ требует **маркдаун** и **жирное** для истории; `parse_mode=None` это покажет как сырые `**`. Нужна санкция на смену формата доставки (parse_mode/`rich_message`) — это **архитектурное решение**, вне заявленного скоупа БЛОКА 1.
5. **Конфликт «1-2 предложения» vs «рассказ-летопись».** Финальный текст `compile_lore_story` идёт через тот же `direct_chat`-ответ под тем же системным каноном → **история будет обрезана каноном**. Это главный скрытый blocker БЛОКА 1/C (см. ADR-1020-6).

---

## Q3. Scaffolding & Context Assembly (сборка контекста)

### 3.1 Текущее состояние

**Сборка system-промпта — монолит, одна функция:**

`services/direct_chat_service.py:585-608`:
1. `system_prompt = await _cpg(chat_id, "prompts.direct_chat_system_prompt", hot.get(..., CHAT_SYSTEM_PROMPT))` (`:589-593`) — каскад **per-chat override → hot → код-канон**;
2. persona-блок приклеивается **в хвост**: `system_prompt = system_prompt + "\n\n" + persona_block` (`:601-608`);
3. `payload = build_messages(system_prompt, user_blocks)` (`:609`).

`services/payload_builder.py:12-23` — канон payload: `[{"role":"system", content}, {"role":"user", content: "\n\n".join(user_blocks)}]`. **Один system + ОДИН user**, склеенный из списка строк. Никаких middlewares, интерцепторов, блок-объектов, post-processor-хуков — только список `str`, где роль блока кодируется XML-тегом внутри строки.

**Сборка user-контента — `_build_user_content`** (`services/direct_chat_service.py:717-840`): фиксированный порядок «важное к концу» (map → branch → rag → global → thread → target → relations → protected → lore → mood → current → anchors → sandwich) + бюджет-распределение `_apply_context_budget` (`:1200-1351`). Комментарий `:720-734` прямо фиксирует, что «меняется только эта сборка».

**Как вшиваются сырые факты RAG:**

- **Direct-путь:** `_build_rag_block` (`direct_chat_service.py:1844-1940`): `memory.get_rag_facts(...)` → `dedup_rag_vs_global` (`summary_memory.py:992+`) → опц. LLM-реранк `rerank_rag_facts` (`:2390+`) → `build_rag_context(kept, origin_labels=True)` (`:943-963`) → обёртка `<RAG_Memory>…</RAG_Memory>` + cap. **Хроно-сортировки здесь НЕТ** (порядок = релевантность KNN/MMR, `:1847-1850`).
- **Legacy-путь:** `get_rag_context` (`summary_memory.py:2315-2356`) → `build_rag_context` → XML `<context><user_gossip>/<bot_knowledge>`. **Хроно-сортировка есть, но только по флагу** `sort_by_timestamp=True` (`:2339-2340`, канон D206, сейчас включён **только** DirectChat).
- **Рендер факта:** `_fact_prefix` (`summary_memory.py:877-901`) → `[ММ.ГГГГ | Автор: X] `; `_format_origin_labeled_line` (`:927-940`) → `[{label}] {дата} {текст}{stale-suffix}`. **Никакого ID и никакого «Переслано: откуда»** — по сравнению с требуемым БЛОКОМ 0 форматом это ~50 % метаданных.
- **Сообщения (<chat_history>):** `services/summary_xml.py:56-104` — есть `id`, `timestamp` (ISO), `author`, `is_forward`/`forward_source`. Это **ближайший существующий предшественник** формата БЛОК 0 (но формат другой: XML-атрибуты, а не `[…]: Текст`).
- **Direct verbatim/стенограмма:** `_build_global_context` (`direct_chat_service.py:1990+`) и `_chain_line`/`_render_thread` дают `«{имя} [{uid}]: текст»` — **без даты и без forward-метки**.
- **Tool-результаты:** вшиваются как **чистая строка** `{"role":"tool", "content": output}` (`tool_loop.py:87-88`); Python-предобработки нет, кроме `_truncate` до 3500/4000 символов (`tool_router.py:62-63`, `:209-213`) и per-tool рендера (`dig_into_lore` → `[Имя YYYY-MM-DD]: текст` / `[label] [ММ.ГГГГ | Автор: X] текст`; `query_chat_memory` → `[Имя [YYYY-MM-DD HH:MM]]: текст` + строка счётчика, `tool_router.py:362-371`, `:464-492`).

**Вывод по Q3:** сборка — **монолит без middleware**. Есть богатая Python-предобработка (dedup/MMR/rerank/cap/TTL), но **точки подачи контекста размазаны по ≥10 местам**, и единого канонического форматтера метаданных нет — есть частные (`_fact_prefix`, `_format_origin_labeled_line`, `summary_xml.build`, `_speaker_tag`, `_dig_date`).

### 3.2 Blockers

1. **Нет единой точки инъекции метаданных (главный риск БЛОКА 0).** Реализовать формат `[Дата Время | Автор | ID | Переслано: откуда]: Текст` «в одном месте» физически нельзя: обязательные точки применения — `summary_xml.build`, `direct_chat_service._build_global_context/_chain_line/_render_thread`, `summary_generator._compose_user_content`, `tool_router._dig_into_lore/_query_chat_memory/_get_recent_history/_history_lines`, `summary_memory._fact_prefix/_format_origin_labeled_line/build_rag_context`, `dream_prompts.build_dream_user`, `lore_worker`, `nostalgia_worker`, `factcheck_service.build_user_content`, `search_service`, `youtube/web_summarizer_service`. Без общего хелпера + инвентаризации формат неизбежно разъедется (риск `metadata-migration-regressions`).
2. **Данные для формата частично отсутствуют.** У `graph_facts` нет `tg_message_id` и нет `is_forward/forward_source` (`database.py:286-296`); forward-атрибуты есть только у `smart_messages` (`:209-221`). «ID сообщения (если применимо)» и «Переслано: откуда» для фактов RAG **технически недоступны без расширения** — нужно решение: ID факта vs ID сообщения, и как поступать с фактами без forward.
3. **Нет middleware/интерцепторного слоя.** Любая сквозная политика (метаданные, time injection, анти-галлюцинация-guard) сейчас кодируется копипастой в вызывающих местах. Для целей эпика это главный источник регрессий.
4. **Time Injection конфликтует с каноном prompt-cache.** Канон (`services/chat_prompts.py:22-25`, FR-24/NFR-3): «системный промпт **статичен** между запросами; вся динамика — строго в user-блоке». ТЗ БЛОК 5.1 требует «в **самое начало глобального системного промпта**». Прямое противоречие → нужна санкция на AMEND канона (см. ADR-1020-3) и решение «prepend в `build_messages`» vs «динамическая строка в user-блоке».
5. **Промпт-канон + hot/chat_params дают тройной источник правды.** `prompts.direct_chat_system_prompt` живёт в коде-каноне + `bot_settings` (hot) + `chat_params` (per-chat) + `PROMPT_MIGRATIONS` (`services/prompt_migrations.py`). Любая правка промпта = канон-миграция (ADR-1013-3), иначе прод-значение перекроет код.
6. **Бюджет/кап режет метаданные непредсказуемо.** `:1928-1938` и `_apply_context_budget` режут XML по символам/токенам — при удлинении каждой строки метаданными изменится и число фактов, попадающих в контекст (latent-регрессия RAG-качества).

---

## Q4. Agentic Factorization (агентное разделение)

### 4.1 Текущее состояние

**Один универсальный промпт.** Все интенты `direct_chat` обслуживает один `CHAT_SYSTEM_PROMPT` (`services/chat_prompts.py:139-172`), внутри которого текстом перечислены тулы (`:164-169`) — и одновременно задана персона, тон, приоритеты и лимит длины. Специализации промпта по интенту нет.

**Схемы тулов** — `services/tool_schemas.py` (**7** штук, `:190-201`), описания на русском.

**Роутинг намерений существует — но он rule-based, до LLM:**
- Fast-Track роутеры `bot.py` (0c factcheck, 0d search, 0e youtube, 0f web, 0g checkup) + 4e download — по каноническому тексту/регексу (канон: `plans/archive/hybrid-tool-calling-round1015/adr-1015-3-tool-calling.md`);
- `services/command_prefix.py` — префикс/имя бота (персона/wake-word);
- `direct_chat_service._dig_pre_gate_block` (`:919-975`) — регекс маркеров ностальгии → принудительный `dig_into_lore` (это ближайшее к «intent routing» в коде, но детерминированное);
- отдельные LLM-«роли» у воркеров — `llm_client.generate_worker(role, …)` (`:923-957`) — это **не** роутер интентов, а выбор модели по роли.

**Разделения «решить» / «синтезировать» нет:** выбор тула и синтез финального текста делает **один и тот же** `generate_chat` в одном цикле (`tool_loop.py:41-46`, `:58-64`), `tool_choice="auto"` — никогда не форсируется.

### 4.2 Blockers

1. **Нет LLM-intent-router.** Добавление = второй LLM-вызов на сообщение (латентность/стоимость) без бюджета и метрик; в проекте нет ни инфраструктуры «маленькая модель для классификации», ни кэша решений.
2. **`tool_choice="auto"` не форсируется** (`tool_loop.py:45`) — модель вправе ответить из «памяти» вместо вызова тула. Это корневая причина симптома БЛОК 5.2 («выдумывает статистику»): нет принуждения к `dig_into_lore`/`query_chat_memory`, а результат тула не обязателен как источник цифр.
3. **`description` тулов — на русском, ТЗ БЛОК 2.5 требует английских** формулировок; при этом шапка файла прямо предупреждает: «Имена/схемы — канон 3.3 (не менять без ревизии spec)» (`tool_schemas.py:1-5`). Правка = ревизия канона + тесты.
4. **Фактчекер без тулов** (`factcheck_service.py:36-74`) — посылка БЛОК 6.2 верна; при этом фактчекер **не** может переиспользовать `chat_with_tools` «как есть»: у него нет `ToolRouter`/`ToolDeps` в конструкторе (`:30-34`), а его пайплайн — не «диалог», а «вердикт» (нет истории сообщений).
5. **Нет per-intent бюджета.** Если ввести второй LLM-вызов (router), понадобится учёт (`chat_usage.register_usage`, `services/chat_usage.py:107+`) и тарифная политика — иначе BYOK/бюджеты per-chat начнут «съедаться» незаметно.

---

## Расхождения ТЗ с реальностью (сводно)

| # | Утверждение ТЗ / PM | Факт в коде | Что делать |
|---|---|---|---|
| 1 | Тул называется `dig_into_lor` | **`dig_into_lore`** — `services/tool_schemas.py:72`, реализация `services/tool_router.py:413` | В коде/спеке — только `dig_into_lore` |
| 2 | Тулов 7, `compile_lore_story` «новый 8-й» | Подтверждено: 7 (`tool_schemas.py:190-201`), `compile_lore_story` отсутствует (grep) | 7 → 8 + канон-ревизия схем |
| 3 | «векторный поиск отдаёт чанки, ломая таймлайн» | Хроно-ASC **уже есть** для `get_rag_context` (`summary_memory.py:2339-2340`, D206), но **его нет** в direct-пути `get_rag_facts`/`_build_rag_block` (`:2360-2388`, `direct_chat_service.py:1847-1850`) | БЛОК 2.6 — **аддитивное** расширение ASC на остальные потребители + решение по direct-пути |
| 4 | «бот не знает текущее время» | Верно: инъекции текущего времени в чат-промпт нет. Есть tz только для воркеров: `limits.summary_timezone` = `settings.SUMMARY_TIMEZONE` (`config/settings.py:505`, используется в `dream_worker.py:298`, `lore_worker.py:211`, `nostalgia_worker.py:124`, `memory_backup.py`, `memory_maintenance.py`) | БЛОК 5.1 = новый глобальный чат-ключ + инъекция |
| 5 | Инструменты поддерживают рекурсию? «возможно single-turn» | **Многотуровая рекурсия есть** (`TOOL_MAX_ROUNDS=4`) | БЛОК 4 = описание; не переписывать |
| 6 | Reasoning-теги `...` | Никакой поддержки: ни парсинга `reasoning_content` (`llm_client.py:1005-1032`), ни среза тегов (`direct_chat_service.py:656`) | Новый рабочий пакет (вне БЛОК 1/2 как заявлено) |
| 7 | Storytelling-промпт с **маркдауном** | Доставка `parse_mode=None` (`smartmodule_utils.py:119`), канон запрещает маркдаун + режет ответ до 1-2 предложений (`chat_prompts.py:160`, `:171-172`) | **Конфликт**: нужен ADR по формату/длине вывода летописца |
| 8 | БЛОК 5.5 / 6.1 (ручной сон, пороги) | Уже реализовано в 10.18 (ADR-1018-2, `POST /api/memory/dream/run`, `tests/test_sleep_manual_cascade_round1018.py`) | verify-only |
| 9 | Аккордеон Advanced | Уже есть (`web/index.html:611` `<details class="advanced">`, `web/app.js:3077` `progressive_level === 'advanced'`) | рестайлинг |
| 10 | «Безлимит (∞)» в Сводке не работает | В `web/app.js:2147` строка `'Безлимит (∞)'` **уже есть** (D-7/10.19); проблема, вероятно, в том, что виджет не перечитывает `chat_params` при смене чата (`:1296`, `:2144`) | БЛОК 5.4 = реактивность (state binding), а не текст |

---

## Итоговые Blockers-приоритеты (для фаз B/C/E)

| Приоритет | Blocker | Влияние |
|---|---|---|
| **P0** | Нет единого форматтера метаданных + ≥10 точек подачи контекста (Q3.2-1/3) | БЛОК 0 без него = регрессия по всем пайплайнам |
| **P0** | Конфликт Time Injection (system head) vs канон prompt-cache (Q3.2-4) | БЛОК 5.1 заблокирован без ADR-AMEND |
| **P0** | Конфликт «1-2 предложения» + plain-text vs storytelling+markdown (Q1.2-?, Q2.2-5) | БЛОК 1/C заблокирован без ADR доставки |
| **P1** | Лимит раундов/ошибки поздних раундов → тишина (Q1.2-1/2) | Агентность и БЛОК 6.2 (фактчекер в цикле) |
| **P1** | Тулы недоступны вне `direct_chat` (Q1.2-3, Q4.2-4) | БЛОК 6.2 требует рефакторинга конструктора фактчекера |
| **P1** | `tool_choice="auto"` не форсируется (Q4.2-2) | БЛОК 5.2/2.8 (анти-галлюцинация) |
| **P2** | Нет парсинга `reasoning_content` (Q2.2-1) | Блокирует переход на reasoning-модели (не в скоупе, но критично для Agentic AI) |
| **P2** | Нет stop-condition/дедупа/наблюдаемости цикла (Q1.2-5/7/8) | Качество агентных цепочек и отладка |
| **P2** | Бюджет-кап режет метаданные (Q3.2-6) | Скрытая регрессия RAG-качества |

## Что аудит НЕ требует менять (verify-only, подтверждено кодом)

- `TOOL_MAX_ROUNDS`, `_TOOL_CALLS_PER_ROUND_MAX`, `llm_client.generate_chat`, `tool_loop.chat_with_tools` — рабочие и достаточные для БЛОК 4 (описание, не разработка).
- Хроно-ASC для `get_rag_context` (D206) — есть; БЛОК 2.6 = расширение, не создание.
- Ручной DeepDream и диагностика порогов (10.18/ADR-1018-2) — не переоткрывать.
- Advanced-аккордеон и строка «Безлимит (∞)» — есть; БЛОК 3.8/5.4 = рестайлинг и реактивность.

---

**Handoff:** отчёт → **Human Gate A (T-1871)** → Step 2 (B/C) стартует только после вердикта владельца (ТЗ стр. 78–80).
