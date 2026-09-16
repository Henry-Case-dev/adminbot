# ADR-1020-2 — Роутинг инструментов, хронология ASC и рефакторинг `dig_into_lore` (БЛОК 2)

- **Статус:** 🟢 **Принято** (Step 2 @Architect, 16.09.2026; **AMEND ред. 2** — О1/О3 FINAL)
- **AMEND ред. 2:** EN-`description` (п.4) распространяется на **все 8 схем** и дополняется строгой типизацией —
  см. [ADR-1020-7](adr-1020-7-agentic-ai-refactor.md) §4 (БЛОК 7.4).
- **Раунд:** 10.20, фаза B (`rag-chronology-tool-routing-round1020`), задачи T-1875…T-1878
- **Спека:** [`spec.md`](spec.md) §3.7, §4.1, §4.2, §4.3
- **Аудит-основание:** `round1020_llm_engine_audit.md` §Q1/§Q3/§Q4

## Контекст

1. **Хронология.** Канон **D206** (`services/summary_memory.py:2316-2368`, `sort_by_timestamp=True`) уже даёт ASC,
   но только для `get_rag_context` и только в DirectChat-легаси. Direct-путь (`get_rag_facts:2360-2388`,
   `_build_rag_block:1844-1940`) хроно-сортировки **не имеет** — там порядок релевантности (KNN × w_eff + MMR).
2. **`dig_into_lore`** (`tool_router.py:413-560`) отдаёт plain-текст сниппетов и фактов; агрегации по авторам нет
   (счётчик только у `query_chat_memory` → `count_mentions:1685-1698` → `search_messages_fts_count:1859-1878`).
   Симптом владельца: отписки «упоминалось 30 раз» + приписывание чужих упоминаний собеседнику.
3. **Роутинг.** `description` инструментов — на русском, шапка `tool_schemas.py:1-5` запрещает менять схемы без ревизии.
4. **Составление ASC «в лоб»** конфликтует с ролью релевантности при отборе top-K.

## Решение

1. **Хронология — только порядок, не состав.** Хелпер `order_rag_facts_asc(facts)` (stable sort по `rag_ts or 0`)
   применяется **перед рендером** у всех потребителей `build_rag_context`/`get_rag_context`:
   `search_service:78`, `factcheck_service:60`, `summary_generator:162`, `tool_router:392`,
   `web_summarizer_service:61`, `youtube_summarizer_service:89,174`, `scripts/run_golden_questions:117`.
   В direct-пути — **после** дедупа и реранка, **перед** `build_rag_context` (`direct_chat_service.py:1919`).
   Top-K по-прежнему отбирается релевантностью; таймлайн восстанавливается внутри контекста.
2. **`dig_into_lore` → JSON-контракт (аддитивно, R16):**
   `{"total_mentions", "mentions_by_authors", "first_seen", "last_seen", "snippets", "facts"}`;
   новый SQL-метод `search_messages_fts_count_by_author` (по образцу `search_messages_fts_count`,
   `database.py:1859-1878`, `GROUP BY author_name` + R16-резолв имён `tool_router._resolve_name:1036-1048`).
   `snippets` **непусты всегда, когда есть попадания** (борьба с «отпиской счётчиком», БЛОК 2.8).
3. **`/summary`: архив ≠ свежее.** Блоки `<historical_graph_facts>`, `<memory>`, `<facts>`
   (`summary_generator._compose_user_content:339-361`) рендерятся с `kind="archive"` + правило канона саммаризатора
   «архив подавай как лор/флешбэк, КАТЕГОРИЧЕСКИ не как свежее». Подмешивание архива сохраняется (это фича, R14).
4. **`description` тулов — на английском** (канон-ревизия): `dig_into_lore` — fast factual lookups / minimal precise facts;
   `compile_lore_story` — ONLY explain a meme / tell a story / comprehensive historical overview, heavy narrative.
5. **Опечатка ТЗ** `dig_into_lor` не переносится — в коде и в спеке только `dig_into_lore`.
6. **Anti-Hallucination Guard** в каноне `CHAT_SYSTEM_PROMPT`: цифры — только из JSON; разделять «сколько раз писал
   собеседник» vs «остальные»; нет цифр — не выдумывать.

## Альтернативы и отклонения

- **Полностью перевести все RAG-потребители на хроно-порядок с изменением top-K:** отклонено — потеря семантического качества.
- **Глобально включить `sort_by_timestamp=True` для всех и убрать релевантный порядок direct-пути:** отклонено —
  регресс MMR-диверсификации (Epic 60/66), риск `rag-sort-regression`.
- **Вернуть `dig_into_lore` plain-текст + отдельно счётчик:** отклонено — не решает приписывание чужих упоминаний (R16).
- **Переписать `description` на русском:** отклонено — ТЗ требует английских формулировок для однозначного роутинга.

## Каталог-Δ

**Δ = 0** (лимиты `dig_max_*`/`_MEMORY_*` — существующие/код-константы).

## Последствия

- Таймлайн восстановлен у всех потребителей; состав top-K не меняется → низкий риск качества.
- **Правка тестов:** снапшоты `dig_into_lore`, ассертящие plain-текст, обновляются осознанно (точное число — T-1878).
- Канон-миграция `CHAT_SYSTEM_PROMPT` (анти-галлюцинации + EN-описания) — атомарно (ADR-1013-3).

## Инварианты

D206-путь `sort_by_timestamp` сохраняется байт-в-байт; R42/R46 (XML саммари, `user_gossip`/`bot_knowledge`) не менять;
R16/R17; `TOOL_MAX_ROUNDS`/`_TOOL_CALLS_PER_ROUND_MAX` не менять; порядок роутеров `bot.py` не менять.
