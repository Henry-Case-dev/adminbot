# Спека эпика `round1020` — «Летописец» (Lore Compiler) + рефакторинг RAG/памяти + UX/UI мини-аппа

> **Статус:** 🟢 **FINAL / SPEC_READY-DELTA** (Step 2 @Architect, 16.09.2026, ред. 2 — дельта перед @Builder).
> **Human Gate пройден**, ответы на О1–О7 зафиксированы (§14 — «открытых решений нет»). Спека дополнена
> **БЛОК 7 (Agentic AI & рефакторинг движка)** и **БЛОК 8 (Актуализация «Справки» UI)** — §18/§19.
> Спека спроектирована по итогам READ-ONLY аудита LLM-движка (`plans/reports/round1020_llm_engine_audit.md`, Фаза A).
> Реализация — @Builder фазами B → C → E (+ D ∥ B) и **новыми фазами G (БЛОК 7) → H (БЛОК 8)**.
> **Эпик:** `plans/features/round1020-lore-compiler-rag-refactor/` (`README.md`, `tasks.md`, T-1866…T-1917).
> **ТЗ:** `plans/current_task.md` — БЛОК 0 (7–11), БЛОК 1 (14–45), БЛОК 2 (48–76), БЛОК 3 (88–140),
> БЛОК 4 (144–177), БЛОК 5 (181–211), БЛОК 6 (225–254), **UPD/Human Gate (278–291), БЛОК 7 (293–319), БЛОК 8 (323–330)**.
> **ADR:** [`adr-1020-1-context-metadata-contract.md`](adr-1020-1-context-metadata-contract.md) *(AMEND ред. 2: middleware)*,
> [`adr-1020-2-tool-routing-chronology.md`](adr-1020-2-tool-routing-chronology.md),
> [`adr-1020-3-time-injection-tz-antihallucination.md`](adr-1020-3-time-injection-tz-antihallucination.md) *(AMEND: О2/О4)*,
> [`adr-1020-4-lore-compiler-tool.md`](adr-1020-4-lore-compiler-tool.md) *(AMEND: О3)*,
> [`adr-1020-5-factcheck-full-tool-access.md`](adr-1020-5-factcheck-full-tool-access.md),
> [`adr-1020-6-story-delivery-format.md`](adr-1020-6-story-delivery-format.md) *(AMEND: О5)*,
> [`adr-1020-7-agentic-ai-refactor.md`](adr-1020-7-agentic-ai-refactor.md) **(НОВЫЙ, БЛОК 7)**,
> [`adr-1020-8-help-ui-update.md`](adr-1020-8-help-ui-update.md) **(НОВЫЙ, БЛОК 8)**.
> **Baseline:** HEAD `2f3e1f0`; pytest **6326/0**; каталог **437/407/412/92/90/20**; SQLite **v11**; APP_VERSION **2.57.0**.
> **R17:** ни в спеке, ни в ADR, ни в отчётах нет секретов; значение SSH-пароля из `plans/current_task.md` не цитируется и не копируется.

---

## 1. Цель, скоуп, НЕ-скоуп

### 1.1 Цель

1. **Единый контракт метаданных** контекста (БЛОК 0): LLM нигде не получает «голый» текст.
2. **Новая фича «Летописец»**: 8-й инструмент `compile_lore_story(topic)` — граф + хронология + storytelling + UPD-диффы.
3. **Ремонт памяти/RAG**: жёсткий роутинг тулов, хронология ASC у всех потребителей, `/summary` (архив ≠ свежее),
   `dig_into_lore` (не отписка счётчиком), Time Injection + «Часовой пояс чата», анти-галлюцинации `mentions_by_authors`,
   persona fallback, «Безлимит (∞)» в «Сводке».
4. **UX/UI мини-аппа**: критич. баги binding/routing, досье участников, тикер досье, Liquid Glass, CSS Grid,
   sticky-save, human-readable labels, рестайлинг Advanced-аккордеона.
5. **Фактчекер**: Full Tool Access + функциональный промпт (тон не переписывается).
6. **Техдолг 10.19**: S10.19-15, S10.19-23, CLI `manage.py retention`.
7. **Agentic AI (БЛОК 7, ред. 2):** fail-safe tool-loop (graceful degradation вместо тишины), парсинг
   `reasoning_content` + stripper reasoning-тегов, единый Context Middleware с приоритетом метаданных,
   расширение `graph_facts` (`tg_message_id`/`forward_from`), перевод всех 8 tool-`description` на английский.
8. **Актуализация «Справки» UI (БЛОК 8, ред. 2):** Летописец, обновлённый Фактчек, безлимиты —
   с сохранением дерзкого ироничного tone of voice.

### 1.2 Скоуп

| Фаза | Файлы (точки интеграции) |
|---|---|
| A (готово) | `plans/reports/round1020_llm_engine_audit.md` + этот spec + ADR-1020-1…6 |
| B | `services/canonical_context.py` (новый модуль-хелпер), `services/summary_memory.py`, `services/summary_generator.py`, `services/summary_xml.py`, `services/tool_schemas.py`, `services/tool_router.py`, `services/direct_chat_service.py`, `services/dream_prompts.py`, `services/lore_worker.py`, `services/nostalgia_worker.py`, `services/chat_prompts.py`, `services/summary_prompts.py`, `services/param_catalog.py`, `web/app.js`, `web/index.html`, `services/oversight.py` |
| C | `services/lore_compiler_service.py` (новый), `services/lore_prompts.py`, `services/tool_schemas.py`, `services/tool_router.py`, `services/tool_loop.py` (только сигнал режима), `services/direct_chat_service.py`, `services/database.py` (аддитивная таблица/чтение) |
| D | `web/app.js`, `web/index.html`, `web/static/app.css` — **только внутри существующих вкладок/модалок** |
| E | `services/factcheck_service.py`, `services/factcheck_prompts.py`, `services/oversight.py`, `manage.py`, `services/memory_maintenance.py` |
| **G** (БЛОК 7) | `services/tool_loop.py`, `services/llm_client.py`, `services/summary_cleanup.py`, `services/context_middleware.py` (новый), `services/canonical_context.py`, `services/direct_chat_service.py`, `services/summary_memory.py`, `services/summary_xml.py`, `services/summary_generator.py`, `services/tool_router.py`, `services/dream_prompts.py`, `services/lore_worker.py`, `services/nostalgia_worker.py`, `services/factcheck_service.py`, `services/search_service.py`, `services/youtube_summarizer_service.py`, `services/web_summarizer_service.py`, `services/tool_schemas.py`, `services/database.py` (v12 + аддитивные поля), `services/lore_prompts.py`, `services/chat_prompts.py`, `services/factcheck_prompts.py` |
| **H** (БЛОК 8) | `services/info_service.py`, `plans/docs/info_text.md`, `plans/docs/intelligence_user_guide.md`, `services/config_cache.py` — **тексты только; структура вкладок/меню не меняется** |

### 1.3 НЕ-скоуп (жёстко)

- **Структура меню, навигация, состав и порядок разделов мини-аппа НЕ меняются** (ТЗ стр. 92; инвариант §3.1 задач).
  Правки — только внутри существующих вкладок/модалок. Тест-снимок навигации обязателен (T-1903).
- **Порядок роутеров `bot.py` не меняется** (только DI-kwargs).
- `TOOL_MAX_ROUNDS`, `_TOOL_CALLS_PER_ROUND_MAX`, `llm_client.generate_chat` — не менять.
- `media/`, `.env`, секреты — не трогать (R17).
- **Не переписывать тон/мат промптов** (в т.ч. фактчекера): правятся только функциональные инструкции (ТЗ стр. 217–219).
- **Не реализовывать заново**: ручной DeepDream, диагностика порогов Личности (10.18/ADR-1018-2), ASC для
  `get_rag_context` (D206), Advanced-аккордеон, tool recursion — verify-only / рестайлинг / описание (§11).
- **Вне эпика (обнаружено аудитом, см. §16, ред. 2)**: только **LLM-intent-router**, форсирование
  `tool_choice`, вложенные суб-агенты/планирование (plan/act) и снятие cap `TOOL_MAX_ROUNDS`. Они
  фиксируются как backlog следующего шага; `TOOL_MAX_ROUNDS=4` **не меняется** (БЛОК 7.1 меняет только
  поведение **при** исчерпании, не сам лимит).
  > **AMEND ред. 2:** ранее вынесенные «вне эпика» парсинг `reasoning_content` и graceful degrade по
  > раундам **перенесены в скоуп** решением владельца (БЛОК 7) → §18. См. §16 (обновлён).

---

## 2. БЛОК 0 — Канонический контракт метаданных (BRIDGE: ADR-1020-1)

### 2.1 Проблема

Аудит (Q3) показал: единого форматтера метаданных нет; есть минимум **4 частных** рендера
(`summary_memory._fact_prefix` `:877-901`, `_format_origin_labeled_line` `:927-940`, `summary_xml.build`
`:56-104`, `tool_router._resolve_name`+`_dig_date` `:1036-1048`/`:984-989`) и **≥10 точек подачи контекста**.
Без общего хелпера БЛОК 0 породит рассинхрон форматов.

### 2.2 Решение — новый модуль `services/canonical_context.py`

```python
def format_context_item(*, ts=None, author=None, item_id=None,
                        forward_source=None, text="",
                        kind="msg") -> str: ...
```
- **Канон формата** (единый для всех путей):

  | kind | Формат |
  |---|---|
  | `msg` (сообщение) | `[ДД.ММ.ГГГГ ЧЧ:ММ \| Автор \| ID \| Переслано: Источник]: Текст` |
  | `fact` (факт RAG/графа) | `[ММ.ГГГГ \| Автор \| fact:ID]: Текст` (+ существующий ` (Внимание: возможно устарело)`) |
  | `archive` (историческая справка `/summary`) | `[Архивная справка: ДД.ММ.ГГГГ \| Автор \| ID]: Текст` |

- **Нормализация ТЗ:** пример ТЗ для архива записан через запятые; канон — **пайп-разделители** для всех kind
  (парсируемость + один хелпер), слово-маркер «Архивная справка» сохранено дословно. Зафиксировано в ADR-1020-1.
- **Правила:** отсутствующие поля **опускаются вместе с разделителем** (не выводим `None`/пустые заглушки);
  `\n`/`\t` внутри полей схлопываются в пробел (прецедент `_fact_prefix`); **никогда не выдумываем** автора/ID/источник (R16);
  `text` проходит `escape_xml_text` только в XML-путях — рендер `format_context_item` возвращает **plain-строку**.
- **ID-политика (решение архитектора):** `tg:<tg_message_id>` если есть → иначе `msg:<smart_messages.id>` →
  иначе `fact:<graph_facts.id>`. Baseline: у `graph_facts` нет ни `tg_message_id`, ни forward-полей
  (`database.py:286-296`), а `smart_messages` имеет всё нужное (`:209-221`).
  **AMEND ред. 2 (БЛОК 7.3, §18.3):** `graph_facts` расширяется колонками `tg_message_id`/`forward_from`
  (SQLite v11→v12) — после этого ID-политика для `kind="fact"` получает `tg:<tg_message_id>` там, где он известен.
- **Forward-политика:** `Переслано: <forward_source>` — только при `is_forward=1` и непустом источнике;
  для фактов RAG (где forward недоступен) сегмент **опускается** — не выдумываем (R16).
  **AMEND ред. 2:** после §18.3 факты получают `forward_from`; сегмент заполняется, если поле непусто, иначе опускается (R16 без изменений).
- **Двухъярусный контракт представления (AMEND ред. 3, ADR-1020-1 §«Разрешение конфликта T-1874»):**
  канонический пайп-префикс — **один** из способов сериализации, а не единственный.
  - **Ярус A (канонический префикс)** — обязателен там, где у строки **нет явного временного маркера**:
    `format_context_item(...)` → `[Дата Время | Автор | ID | Переслано: X]: текст`.
  - **Ярус B (эквивалентная явная сериализация)** — допустим, если обязательные метаданные **фактически
    присутствуют** в структурированном виде: XML-атрибуты `<message id/timestamp/author/is_forward/forward_source>`,
    `[Имя [ГГГГ-ММ-ДД ЧЧ:ММ]]`, `N. [ГГГГ-ММ-ДД]`, `[ГГГГ-ММ-ДД ЧЧ:ММ] автор:`, `[ММ.ГГГГ | Автор: X]`.
- **Критерий «нет голого текста» (FINAL, ред. 3):** строка-элемент данных compliant, если несёт
  (1) **временной маркер** — обязательно, если источник его отдаёт; (2) **автора** — обязательно, если источник
  отдаёт автора; (3) **ID** — best-effort (`tg:` → `msg:` → `fact:`, §2.2); (4) **`Переслано`** — best-effort.
  Поле, которого **нет в источнике**, опускается вместе с разделителем (R16); выдумывание запрещено.
  Отсутствие обязательного поля (1–2) при наличии значения в источнике = **non-compliance** → ярус A.
  Служебные строки (`«фон: …»`/`«широкий фон: …»` в `<Global_Context>`, `_SELF_ECHO_INSTRUCTION` в
  `<RAG_Memory>`, XML-обёртки) — **allowlist**, критерию не подлежат.

### 2.3 Точки применения (инвентаризация — deliverable T-1873/T-1874)

| # | Точка | Файл:строка (baseline) | kind | Представление (ред. 3) |
|---|---|---|---|---|
| 1 | `<chat_history>` (саммари) | `services/summary_xml.py:56-104` | msg | ✅ equivalent (XML-атрибуты `id/timestamp/author/is_forward/forward_source`) — **байт-инвариант** |
| 2 | Direct `<Global_Context>` verbatim-хвост | `services/direct_chat_service.py:2082-2106` | msg | 🔴 **non-compliant → ярус A: применить формат (B)** |
| 3 | Direct thread/branch | `direct_chat_service.py:2164-2275` | msg | 🔴 **non-compliant → ярус A: применить формат (B)** (бот-ход: ts опускается — в `bot_replies` времени сообщения нет; ID `tg:<current_id>`) |
| 4 | `<RAG_Memory>` (direct) | `direct_chat_service.py:1940` → `summary_memory.build_rag_context(origin_labels=True)` | fact | 🟡 equivalent (ts+author); `fact:ID`/forward → **G (T-1924)** |
| 5 | Legacy RAG `<context>` (search/factcheck/скрипты) | `summary_memory.py:964-1004` | fact | 🟡 equivalent (ts+author); **структура XML — байт-инвариант**, текст строки → **G** |
| 6 | `dig_into_lore` messages/facts | `tool_router.py:504,555` | msg / fact | ✅ **formatted (B)** |
| 7 | `query_chat_memory` | `tool_router.py:362-371` | msg | 🟡 equivalent (основная ветка `[Имя [ГГГГ-ММ-ДД ЧЧ:ММ]]`); fallback `vector_search` → ⏸ **PENDING (follow-up, Р6 ADR)** |
| 8 | `get_recent_history` | `tool_router.py:928-944` (`_history_lines`) | msg | 🔴 **non-compliant → ярус A: применить формат (B)** |
| 9 | `/summary` архивная справка | `summary_generator.py:355` (`_compose_user_content`) | archive | ✅ **formatted (B)** |
| 10 | Сон/Дистилляция | `services/dream_prompts.py:80` (`build_dream_user`) | fact | ✅ equivalent (`N. [ГГГГ-ММ-ДД]`; автора у дистиллята нет) |
| 11 | Авто-лор | `services/lore_worker.py:614,618` | msg | ✅ equivalent (`[ГГГГ-ММ-ДД ЧЧ:ММ] автор:`) |
| 12 | Ностальгия | `services/nostalgia_prompts.py:105,115,148` | fact | ✅ equivalent (`[{speaker} {date}]` / `[{date}]`) |
| 13 | Фактчек `<chat_context>` | `services/chat_context.py:32` | msg | 🔴 **non-compliant → ярус A: применить формат (B)** |
| 14 | Видео/веб-выжимки (RAG-префикс) | `youtube_summarizer_service.py:90`, `web_summarizer_service.py:62` → `get_rag_context` | fact | 🟡 equivalent (как #5); ID/forward → **G** |

**Правило эпика (ред. 3):** «голый» текст запрещён; каждая точка обязана **фактически присутствующими
метаданными** соответствовать критерию §2.2 (ярус A **или** ярус B). Реестр `CONTEXT_POINTS` расширяется полем
`representation` (`canonical` | `xml_attrs` | `bracket_header` | `label_exempt`) — инвентаризационный тест
«нет голого текста» **генерируется из реестра** (per-point pattern; никакого «проверим потом»). Точки 1/4/5/7/10/11/12/14
не переписываются в B (эквивалент), точки 6/9 уже каноничны, остаток B — **2/3/8/13** (см. ADR-1020-1 Р3/Р4).

### 2.4 Blockers/риски, закрываемые спекой

- Нет middleware → **вводим один хелпер + инвентарный тест**; **AMEND ред. 2 (О7/БЛОК 7.3):** поверх хелпера
  добавляется **тонкий Context Middleware** `services/context_middleware.py` (§18.3) с приоритетом метаданных —
  он НЕ переписывает сборку контекста, а оборачивает хелпер и добавляет header-safe усечение.
  См. ADR-1020-1 (AMEND).
- Данных для полного формата у фактов нет → ID-политика §2.2 + опускание недоступных полей.
- Удлинение строк меняет поведение cap (`direct_chat_service.py:1928-1938`, `_apply_context_budget:1200-1351`) →
  после внедрения обязателен замер `facts=%d | chars=%d` до/после и при необходимости пересчёт кап-ключей
  (каталог-Δ §8, санкция владельца).
- **Разрешение конфликта T-1874 (ред. 3):** критерий «нет голого текста» = **метаданные фактически присутствуют
  в любой явной форме** (ярус A или ярус B, §2.2) — это снимает ложное противоречие «применить везде» ↔
  байт-инвариант. Остаток T-1874 = точки **2/3/8/13**; точки 1/4/5/7/10/11/12/14 — эквивалент (не трогаем);
  6/9 — каноничны; ID/forward для фактов — фаза **G (T-1924)**; fallback точки 7 — follow-up. Полная
  разметка/инварианты/снапшоты — ADR-1020-1 §«Разрешение конфликта T-1874».
- **Сопутствующие фиксы (обязательны, иначе скрытая регрессия):** `strip_context_header` в
  `direct_chat_service._line_markers` (первое двоеточие уедет в заголовок → E1 keep-importance) и в
  `summary_memory._fact_tokens` (F2-дедуп ↔ заголовок).

---

## 3. БЛОК 1 — «Летописец»: `compile_lore_story(topic)` (BRIDGE: ADR-1020-4, ADR-1020-6)

### 3.1 Контракт инструмента (JSON Schema, 8-й инструмент)

```python
TOOL_COMPILE_LORE_STORY = {
    "type": "function",
    "function": {
        "name": "compile_lore_story",
        "description": ("Use this ONLY when the user asks to explain a meme, tell a story, "
                        "or give a comprehensive historical overview of a topic. "
                        "Heavy narrative tool; slow. Do NOT use for simple factual lookups."),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "description": "Local meme/topic/event to tell the story about."}
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
}
```

- Регистрация: `services/tool_schemas.py` (`TOOL_CALLING_TOOLS` — **7 → 8**, в конец, канон R9 не тронут),
  dispatch-реестр `services/tool_router.py:302-310` (+ имя), метод `ToolRouter._compile_lore_story`.
- Доступ: только `direct_chat` (`services/direct_chat_service.py:620-627`) + фактчекер (фаза E).
- Гейт: `flags.lore_compiler_enabled` — **простой тумблер ВКЛ/ВЫКЛ, ДЕФОЛТ ВКЛ глобально для всех чатов**
  (О3, §13). Поэтапная раскатка 10/50/100 **отменена** решением владельца.

### 3.2 Пайплайн сбора (Шаг А — граф, Шаг Б — хронология)

**Шаг А (`graph_facts`, детерминированно, ASC):**
1. узел топика: `nodes.entity_name` (casefold-match) `database.py:247-256`;
2. связи 1–2 уровня: `edges` (`source_id/target_id`, `relation_type`, `weight`, `fact_id` — `database.py:258-278`);
3. привязанные Убеждения: `graph_facts` по `fact_id` рёбер (provenance уже есть — ADR-1018-3 D1);
4. переиспользовать существующий обход: `db.dig_graph_related_names` (`database.py:2218`, глубина
   `limits.dig_graph_hop_depth`, кап `_DIG_GRAPH_MAX_HOP_DEPTH=5`), но **расширить до структурного вывода**
   (новый read-метод `db.lore_graph_slice(chat_id, topic, depth=2)`), чтобы отдать связи, а не только имена;
5. рендер каждого факта — `format_context_item(kind="fact")`, сортировка **ASC по `rag_ts`** (детерминизм).

**Шаг Б (`chronological_dialogs`, строго ASC):**
1. `earliest`/`latest` упоминаний топика — существующий `search_messages_fts_count` (`database.py:1859-1878`)
   даёт `first_seen`/`last_seen`;
2. «2–3 диалога максимальной плотности» — новый read-метод
   `db.lore_dense_dialogs(chat_id, keywords, max_dialogs=3, window_minutes=30)`:
   FTS-выборка (`smart_messages_fts`, `:1847-1857`) → бакетирование по времени окна → топ-3 бакета по числу
   совпадений → полный текст окна **ASC**;
3. рендер каждой строки — `format_context_item(kind="msg")` (ID + forward из `smart_messages`);
4. кап по символам — код-константы (каталог-Δ=0 для лимитов; прецедент `_MEMORY_MAX_SYMBOLS`/`_HISTORY_MAX_SYMBOLS`).

**Итог для LLM (внутренний контракт сервиса):**

```json
{
  "topic": "<topic>",
  "first_seen": "YYYY-MM-DD",
  "last_seen": "YYYY-MM-DD",
  "total_mentions": 42,
  "mentions_by_authors": {"UserA": 2, "UserB": 40},
  "graph_facts": ["[05.2024 | Автор: Толян | fact:991]: ...", "..."],
  "chronological_dialogs": ["[15.05.2024 21:07 | Толян | tg:4123]: ...", "..."],
  "previous_story_at": 1739000000,
  "is_update": true
}
```

### 3.3 Storytelling-промпт (канон; правка атомарна: код + `plans/docs/canon/` + тесты)

- Новый канон `LORE_STORY_SYSTEM_PROMPT` в `services/lore_prompts.py` + эталон в `plans/docs/canon/architecture.md`
  (ADR-1013-3): структура «завязка → развитие → статус-кво», постирония/чатовый сленг, обязательные имена участников,
  интеграция смешных цитат, **HTML-разметка (`<b>`, `<i>`) вместо Markdown (О5 FINAL)**, «мало фактов — сымпровизируй вокруг, но не ври про ключевые действия».
- **UPD-инструкция** (та же миграция): «Часть этой истории уже была известна. Расскажи базу, затем блок
  **UPD (Свежак):** и органично впиши новое».
- Промпт ссылается на §2-формат метаданных (даты/авторы/ID) как на источник фактов.

### 3.4 Где происходит синтез (ключевое архитектурное решение)

**Решение (ADR-1020-4 + ADR-1020-6):** инструмент **сам** вызывает LLM с `LORE_STORY_SYSTEM_PROMPT`
(изолированный `LoreCompilerService`, свой `llm.generate`, температура/лимиты — код-константы) и возвращает
модели-диспетчеру **уже готовый текст**:

```json
{"status": "ok", "is_update": true, "story": "<готовый рассказ>"}
```
+ служебная инструкция в `content`: «верни `story` пользователю **дословно**, без сокращений и без пересказа».

Обоснование:
- ТЗ прямо требует «прогонять собранные данные через жестко заданный системный промпт» — то есть изоляцию стиля
  от канона `direct_chat` (иначе 1-2 предложения и запрет маркдауна обрежут историю: `chat_prompts.py:171-172`, `:160`).
- Диспетчерский путь не теряет tool-loop: финальный ответ — текст модели, но факт вызова фиксируется
  (`ToolContext.lore_compiled = True`), и `direct_chat` для этого turn применяет режим доставки летописца (§3.5).
- Отклонённая альтернатива «(B) отдать JSON + prompt диспетчеру»: размывает изоляцию стиля, дублирует промпт-канон
  в двух местах, ломает детерминизм вывода. Отклонённая альтернатива «бэкенд сам отправляет историю как `download_media`»:
  разрывает диалог (2 сообщения) и лишает модель возможности короткой ремарки.

### 3.5 Доставка (ADR-1020-6, **AMEND ред. 2 — решение О5 FINAL**)

- **FINAL (О5):** глобальный `parse_mode` остаётся **`None`** (без изменений, обычный путь DirectChat не тронут).
  Для историй Летописца **локально форсируется `parse_mode=HTML`**; storytelling-промпт использует **HTML-теги**
  (`<b>…</b>`, `<i>…</i>`, `<a href>`) **вместо Markdown** (`**…**`). Это убирает `**` из выдачи и снижает риск
  `can't parse entities` (HTML-экранирование предсказуемее MarkdownV2).
- Если `ctx.lore_compiled` за turn — `send_chunked_reply(..., parse_mode="HTML")`
  (`services/smartmodule_utils.py:113-120`), длинные тексты уже чанкуются по 4096.
- **Обязательный фолбэк:** `TelegramBadRequest` при отправке HTML → повтор той же доставки с `parse_mode=None`
  (plain-text), прецедент деградации `summary_generator:406-416`; тест «обычный ответ — plain, летописец — HTML,
  битая разметка → plain».
- В каноне `LORE_STORY_SYSTEM_PROMPT` (§3.3) markdown-инструкции **заменяются** на HTML-инструкции (атомарная
  канон-миграция, §9 п.3).

### 3.6 Механика диффов/UPD (T-1891)

- **Хранилище.** `smart_cache` (`services/smart_cache.py`) **не подходит**: `created_at = time.monotonic()`
  (`:137`, `:151`) → TTL не переживает рестарт, плюс LRU-вытеснение по `limits.smart_cache_max_rows`.
- **Решение:** **аддитивная таблица** `lore_stories` через `CREATE TABLE IF NOT EXISTS` **без подъёма `user_version`**
  (прямой прецедент: `smart_cache` `database.py:304-311`, `bot_reply_parents` `:328-334`, `dead_page_repost_map` `:313-326`, R51-5/R52-8):

  ```sql
  CREATE TABLE IF NOT EXISTS lore_stories (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      chat_id     INTEGER NOT NULL,
      topic_key   TEXT    NOT NULL,          -- normalize_text(topic) (services/smart_cache.normalize_text)
      topic       TEXT    NOT NULL,
      story       TEXT    NOT NULL,
      last_ts     INTEGER NOT NULL,          -- last_seen на момент компиляции
      created_at  INTEGER NOT NULL,
      updated_at  INTEGER NOT NULL,
      UNIQUE (chat_id, topic_key)
  );
  ```
- **Логика UPD:** `lore_stories` hit по `(chat_id, topic_key)` → `is_update=true`, в JSON передаётся
  `previous_story_at`; сервис тянет **только новые** сообщения (`timestamp > last_ts`) и включает UPD-ветку.
  Ветка UPD **не** дублирует всю базу: база переиспользуется из сохранённого `story` (передаётся в промпт
  как «известная база»), новое — из Шага Б.
- **Идемпотентность/откат:** таблица — новое хранилище, а не миграция; удаление таблицы = откат без следов.
- **Читать/писать** — через новые тонкие методы `Database` (read/write), в одном `to_thread`-паттерне, как прочие
  SQLite-операции; ошибки — WARNING + деградация до «первого запроса» (без UPD), диалог не роняется (NFR-4).
- **Fallback (если владелец запретит DDL):** `smart_archive_facts` с неймспейс-маркером
  `[ЛЕТОПИСЬ:<topic_key>]` + исключение маркера из RAG/L3-выборок. Записывается в ADR-1020-4 как альтернатива.

### 3.7 Роутинг `dig_into_lore` ↔ `compile_lore_story` (БЛОК 2.5)

- `description` переписать в **английский** (канон-ревизия; шапка `tool_schemas.py:1-5` предупреждает о ревизии):
  - `dig_into_lore`: *"Use this for fast, factual lookups. Answers simple questions like 'Who owns X?', 'When did Y happen?'. Returns minimal, precise facts."*
  - `compile_lore_story`: *"Use this ONLY when the user asks to explain a meme, tell a story, or give a comprehensive historical overview of a topic. Heavy narrative tool."*
- **Текст ТЗ с опечаткой `dig_into_lor` не переносится** — только `dig_into_lore` (в коде `tool_schemas.py:72`).
- Тест роутинга: набор фраз → ожидаемая пара (tool/нет tool) — фиксируется снапшотом описаний.

---

## 4. БЛОК 2 — Роутинг, хронология, `/summary`, `dig_into_lore` (BRIDGE: ADR-1020-2)

### 4.1 Хронология ASC — расширение (НЕ создание)

**Факт:** ASC уже есть для `get_rag_context(sort_by_timestamp=True)` — `summary_memory.py:2339-2340` (канон D206),
включён только для DirectChat-легаси; **у direct-пути** `get_rag_facts` (`:2360-2388`) и `_build_rag_block`
(`direct_chat_service.py:1847-1850`) хроно-сортировки нет — там порядок релевантности (KNN+MMR).

**Решение (аддитивно, без слома ранжирования):**
- ввести единый хелпер `order_rag_facts_asc(facts)` в `summary_memory.py` (stable sort by `rag_ts or 0`);
- применить его **перед рендером** во всех потребителях `build_rag_context`/`get_rag_context`:
  `search_service.py:78`, `factcheck_service.py:60`, `summary_generator.py:162`, `tool_router.py:392`,
  `web_summarizer_service.py:61`, `youtube_summarizer_service.py:89,174`, `scripts/run_golden_questions.py:117`;
- **direct-путь:** ASC применяется **после** дедупа и реранка, **перед** `build_rag_context` (`direct_chat_service.py:1919`);
  сохранение релевантности — через существующий `flags.chat_rag_rerank_enabled` (реранк остаётся фильтром, порядок — хроно).
- Совместимость: ранжирование по-прежнему определяет **состав** top-K (то, что попало в контекст), меняется только
  **порядок внутри контекста** — семантическое качество не теряется, таймлайн восстанавливается.
- **Регресс-гейт D206:** тесты ASC DirectChat обязаны остаться зелёными; добавляется тест «ASC у всех потребителей».

### 4.2 `/summary`: архив ≠ свежее

- Архивная маркировка в `_compose_user_content` (`summary_generator.py:339-361`): блоки `<historical_graph_facts>`,
  `<memory>`, `<facts>` рендерятся через `format_context_item(kind="archive")` (§2.2) — **контрастный** маркер
  «Архивная справка» + дата + автор.
- Правило в каноне `SYSTEM_PROMPT` (`services/summary_prompts.py:13-37`): «В данных есть свежая переписка и архивные
  факты. Чётко разделяй. Исторический факт подавай как лор/флешбэк ("Кстати, стоит вспомнить, что ещё в прошлом году…"),
  **КАТЕГОРИЧЕСКИ** не выдавай за свежее». Подмешивание архива **сохраняется** (R14) — меняется только подача.
- Канон-миграция: `SYSTEM_PROMPT` + слепок `PREV_*` + ступень в `services/prompt_migrations.py` (ADR-1013-3) атомарно.

### 4.3 `dig_into_lore`: сырые факты + group-by-authors + Anti-Hallucination Guard

**Backend (аддитивный SQL — R16):**
- новый метод `Database.search_messages_fts_count_by_author(chat_id, match, since_ts)` →
  `{count, first_seen, last_seen, by_author: {"<name>": N}}` (по образцу `search_messages_fts_count`
  `database.py:1859-1878` + `GROUP BY COALESCE(author_name,'')`, имя резолвится тем же R16-каскадом
  `tool_router._resolve_name:1036-1048`);
- `_dig_into_lore` (`tool_router.py:413-560`) возвращает **JSON-контракт** вместо plain-текста:

  ```json
  {"total_mentions": 42,
   "mentions_by_authors": {"Толян": 2, "Ваня": 40},
   "first_seen": "2024-02-15 21:07", "last_seen": "2026-08-02 11:40",
   "snippets": ["[15.05.2024 21:07 | Толян | tg:4123]: ...", "..."],
   "facts": ["[05.2024 | Автор: Ваня | fact:991]: ..."]}
  ```
- `snippets` не пустые **всегда, когда есть попадания** (борьба с «отпиской счётчиком», БЛОК 2.8); при отсутствии
  попаданий — `{"total_mentions": 0, ...}` + честный текст, без выдумок (R16).
- Обратная совместимость: tool-результат — строка; переход plain→JSON **аддитивен** по смыслу (модель видит больше полей).
  Снапшот-тесты, ассертящие текущий plain-текст `dig_into_lore`, обновляются осознанно (в спеке явно: «ожидаемая
  правка тестов = N», точное число фиксирует @Builder в T-1878).

**Prompting (канон, атомарно):**
- в `CHAT_SYSTEM_PROMPT` (`chat_prompts.py:164-169`): «Опирайся на детали: что, кто, последствия. Цифру называй
  **только** из результата инструмента и **разделяй**, сколько раз это писал собеседник, а сколько — остальные.
  Не отделывайся сухой статистикой».
- **Anti-Hallucination Guard** (тот же канон-блок): «КАТЕГОРИЧЕСКИ запрещено придумывать количество упоминаний.
  Цифры — только из JSON. Если точных цифр нет — не выдумывай».

### 4.4 Persona fallback («изящный слив») — БЛОК 5.3

- Новый абзац канона `CHAT_SYSTEM_PROMPT`: «Если собеседник ловит тебя на нестыковке в фактах/цифрах, а в памяти нет
  точного подтверждения — **не выдумывай** новые цифры. Признай косяк в саркастично-токсичной манере (перегрелись
  серверы / база покрылась пылью), но оставайся в рамках фактов». Тон — не переписывается, добавляется функциональный абзац.

---

## 5. БЛОК 3 — UX/UI мини-аппа: `miniapp-ux-refactor-round1020` (BRIDGE: ADR требует только UI-документ, T-1894)

> **ГЛАВНЫЙ ИНВАРИАНТ:** структура меню/навигации/разделов **не меняется** (ТЗ стр. 92). Все правки — внутри
> существующих вкладок (`web/app.js:18-190` TABS) и модалок. Тест-снимок навигации обязателен.

### 5.1 Критические баги (T-1895)

| # | Симптом | Точки аудита (baseline) | Контракт фикса |
|---|---|---|---|
| а | Пустые поля ввода при данных в БД (модели/ключи) | загрузка конфига/`configItems` в `web/app.js`; backend `/api/config` (секреты) | two-way binding: значение из БД всегда попадает в инпут; **секреты** — заглушка `••••••••••••` или `configured ****1234`; пусто **только** при реальном `null` (R16) |
| б | «Модули» → «Параметры» у карточки **«Выжимка видео»** не открывает модалку | `openModuleWindow` `web/app.js:2499-2508`; `canViewTab:2991-3051`; карточка `MODULES` `:70-77`; кнопка `web/index.html:758` | воспроизвести; гипотеза — отказ в `canViewTab(m.tab)`/`activeModuleTab` (`:1075-1085`); фикс — в границах существующей модалки |
| в | Мёртвый тумблер `relations_enabled` («Влиять на тон бота») | `relationsEnabled` `web/app.js:909`; загрузка `:4976`; `PUT /api/chat_lore/{id}/relations_enabled` `:5094-5122` | обработчик + сохранение состояния; при конфликте `updated_at` — штатный 409-путь; UI не «откатывается молча» |

Замечание аудита: чтение/запись `relations_enabled` **уже реализованы** (`:4976`, `:5094-5122`) — значит баг, вероятнее,
в привязке события/повторном перезатирании стейта; T-1895 обязан дать воспроизведение и корневую причину (README-гипотеза,
не факт).

### 5.2 Новое: досье участников (T-1896)

- Секция «Участники и отношения» (`TAB_RELATIONS`, `param_catalog.py:1963`-соседство, `web/app.js` tab `relations`):
  список участников выбранного чата + карточка с текущим **Досье** (из PersonalityExtractor) + кнопка
  «Редактировать досье».
- Backend: читать существующим API участников/персона-карточки (`direct_chat_service.build_persona_card:1665`,
  `list_persona_names:1733`), редактирование — аддитивный API-контракт (R16: id — ключ). **Новые RBAC-секции не вводим**
  (прецедент `canViewTab` `relations` `:3024-3027`).
- Требует @Scanner-проверки: не дублирует ли существующий persona-экран (`#/ai/persona`).

### 5.3 Новое: тикер досье в «Сводке» (T-1897)

- Реактивный тикер: `GLOBAL` → случайные досье всех чатов; конкретный чат → только его участники.
- Источник — тот же API досье (без новых таблиц); рендер — CSS-анимация (без сторонних библиотек — CSP-инвариант
  `miniapp-mobile-round1016`/ADR-1016-2).
- Реактивность: перерисовка при смене `activeChatId` **без лишних запросов** (связь с §7.4).

### 5.4 Визуальный стиль Liquid Glass (T-1898) + сетка (T-1899)

- Дизайн-токены (единый источник — CSS-переменные в `web/static/app.css`):
  `--glass-bg: rgba(30,35,40,0.6)`, `--glass-blur: blur(12px)`, `--glass-border: 1px solid rgba(255,255,255,0.1)`.
- Применение: панели «Сводка»/«Модули»/«ИИ» + **все** модалки.
- Сетка: `grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))` + центровка контейнера (десктоп).
- Обязательно: `@media (prefers-reduced-motion)` и mobile-first проверка (10.16/10.17 опыт).

### 5.5 Sticky-save вместо «Кнопка Сохранить везде» (T-1900)

- Удалить индивидуальные «Сохранить» под инпутами; одна **sticky-панель** внизу каждой модалки: «Отмена» / «Сохранить изменения».
- Контракт тумблеров: **мгновенный auto-save** (существующий путь; конфликты — 409-обработка).
- Контракт панели: собирает **dirty**-поля модалки; «Отмена» = откат к загруженному стейту; «Сохранить» = один батч-запрос
  (или N точечных PUT — решение @Builder по существующим API; в спеке требование: **одна** кнопка, без регрессии RBAC).
- Риск R9: конкурентность с auto-save тумблеров — тест «тумблер ON + панель Сохранить не перезатирает».

### 5.6 Human-readable labels (T-1901)

- Глобально во **всех** разделах: `title_ru`/`description` в `services/param_catalog.py` (таблицы каталога ~`:376+`,
  GROUPS `:139-300`) переписываются на человеческий язык; убрать «Кап», «L1/L2», «Слой А/В», машинные ключи в заголовках.
- Примеры ТЗ: `models.llm_retry_backoff_cap` → «Макс. пауза между попытками (сек)»;
  `Temperature: болтливый` → «Креативность (Болтливый режим)».
- Это **санкционированный каталог-Δ по текстам**: счётчики `REGISTRY/GROUPS/TAB_RULES` **не растут**, но тесты-снапшоты
  названий/описаний обновляются осознанно (точное число фиксирует @Builder; гейт T-1885/T-1904).

### 5.7 Рестайлинг Advanced-аккордеона (T-1902) — НЕ создание

- Уже существует: `web/index.html:611` `<details class="advanced">`, `progressive_level === 'advanced'`
  (`web/app.js:3077`), `advancedItems` (`:3092`), правило `resolve_progressive_level` (`param_catalog.py:1608`).
- Задача — **стилизация**: glassmorphism-полоса раскрытия, иконка (chevron/шестерёнка), плавная CSS-анимация
  (`<details>` + `::details-content`/JS-фолбэк), семантические блоки «Базовые» / «Расширенные системные».
- Категорически нельзя: менять состав групп, порядок вкладок, добавлять/удалять разделы.

---

## 6. БЛОК 5 — Time-Awareness, анти-галлюцинации, «Безлимит (∞)» (BRIDGE: ADR-1020-3)

### 6.1 Time Injection (БЛОК 5.1)

- Формат (ТЗ, дословно): `[Текущее время в чате: DD.MM.YYYY, HH:MM, День недели]`.
- **Место инъекции — FINAL (О2, решение владельца): Вариант A.** `build_messages`
  (`services/payload_builder.py:12-23`) добавляет строку времени **первым user-блоком**.
  System-промпт остаётся **статичным**; **Prompt Caching ломать КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** (канон FR-24/NFR-3,
  `chat_prompts.py:22-25` — соблюдён). Вариант B (prepend в head system) **отклонён** владельцем.
  Время — только `direct_chat` + воркеры, где есть «сейчас» (саммари/сон/ностальгия уже имеют tz-инфраструктуру).
  Обязательный тест: system-блок байт-в-байт статичен между запросами; строка времени присутствует **в первом user-блоке**.
- tz-источник — **FINAL (О4): новый ключ** `limits.chat_timezone` (per-chat, категория `limits`, не secret →
  `per_chat=True` автоматически, `param_catalog.py:110-124`) с человеческими названиями в `select_labels`
  (прецедент `_SELECT_WIDGET_PRESETS:1701-1713`): `UTC+2 (Калининград)`, `UTC+3 (Москва)`, `UTC+5 (Екатеринбург/Пермь)`, `UTC+7 (Красноярск)`…
  Реюз `limits.summary_timezone` **отклонён** владельцем (расписания воркеров ≠ часы диалога).
- **Существующий `limits.summary_timezone` (`config/settings.py:505`, `Asia/Yekaterinburg`) — НЕ трогаем** (от него зависят
  расписания `dream_worker.py:298`, `lore_worker.py:211`, `nostalgia_worker.py:124`, `memory_backup.py`, `memory_maintenance.py`).
  Новый ключ **фолбэчит** на него (совместимость с текущим прод-поведением).
- UI: селектор «Часовой пояс чата» в разделе «Поведение»/«Прямые ответы» (`mod_direct`, существует) — **без изменения меню**.

### 6.2 Анти-галлюцинации в `dig_into_lore` (БЛОК 5.2)

См. §4.3 (JSON-контракт `total_mentions` / `mentions_by_authors` / `snippets` + Anti-Hallucination Guard).

### 6.3 Persona fallback (БЛОК 5.3)

См. §4.4.

### 6.4 «Безлимит (∞)» в «Сводке» (БЛОК 5.4)

Аудит: строка `'Безлимит (∞)'` **уже существует** (`web/app.js:2147`, D-7/10.19), ветка `unlimited` — `:1296`.
Реальная проблема — **реактивность**: при смене `chat_id` виджеты «Бюджет контекста»/«Дневной фон» не перечитывают
`chat_params`. Контракт фикса:
- при смене чата — обязательный запрос `chat_params` (per-chat override → global → default);
- `-1` → рендер **«Безлимит (∞)»**; иначе — числа;
- backend-часть: `services/oversight.py` (см. §7.3 — там же техдолг S10.19-15, один и тот же блок лимитов);
- тест: `-1` → «Безлимит (∞)»; переключение чата → один запрос (`S10.19-15`/§7.4), без двойных чтений.

### 6.5 БЛОК 5.5 — VERIFY-ONLY (FINAL, О1)

Ручной DeepDream + диагностика причин пропуска Личности **уже реализованы** (10.18: ADR-1018-2, коммит `16a8c0b`,
`POST /api/memory/dream/run`, `tests/test_sleep_manual_cascade_round1018.py`, T-1717). **О1 FINAL: закрыто как verify-only** —
ADR-1018-2 не переоткрываем, заново не пишем. Задача: подтвердить отсутствие silent failures, наличие логов пропуска
и что ручной триггер **привязан к кнопке нового UI** мини-аппа (фаза D: раздел «Сон»/«Мониторинг Интеллекта»).
**Повторную реализацию не создавать.**

---

## 7. БЛОК 6 — Фактчекер + техдолг (BRIDGE: ADR-1020-5)

### 7.1 Full Tool Access (T-1907)

- Фактчекер (`services/factcheck_service.py:36-85`) сейчас **без тулов** (`llm.generate`, `:69-74`) и без `ToolRouter`
  в конструкторе (`:30-34`).
- Решение: инжектить `ToolRouter`/`ToolDeps` в `FactCheckService` (аддитивный kwarg, DI из `bot.py` — только kwargs)
  и переиспользовать `chat_with_tools` (`tool_loop.py`) с tool-сетом `dig_into_lore` + `compile_lore_story` + `execute_web_search`.
- **Контракт:** вердикт фактчека по-прежнему один текст; tool-loop — обёртка вокруг `llm.generate`.
- Бюджет/латентность: лимиты раундов те же (4); нужен замер стоимости (риск `factcheck-full-tools-cost`) —
  метрика в T-1911 + наблюдение на раскатке.
- Метаданные БЛОК 0 обязательны в `<chat_context>` (`factcheck_service.py:87-118`).

### 7.2 Функциональный промпт (T-1908, + БЛОК 7.2 P0)

- В `services/factcheck_prompts.py` добавляются **только** функциональные инструкции (тон/мат — как есть):
  (а) мировые факты/наука/новости → веб-поиск; (б) «кто что сказал в этом чате» → **обязательно** `dig_into_lore`/`compile_lore_story`;
  (в) использовать метки `[Дата Время | Автор | Переслано: откуда]` для аргументации точной датой/временем.
- **БЛОК 7.2 (P0) — снятие канона «1–2 предложения» для Фактчера:** `FACTCHECK_SYSTEM_PROMPT` **не наследует**
  `CHAT_SYSTEM_PROMPT` (`chat_prompts.py:171-172`); явной функциональной строкой фиксируется право на **полный
  развёрнутый вердикт** без лимита предложений. Тон/мат — не переписываются (см. §18.2).
- Канон-миграция атомарно (код + `plans/docs/canon/` + `PROMPT_MIGRATIONS`).

### 7.3 Техдолг S10.19-15 (T-1909)

`services/oversight.py:203-216` (`_limits_block`) вызывает `chat_usage.key_status` **дважды на чат** →
свести к одному вызову `budget_snapshot`/`key_status` на чат, обе метрики — из одного результата;
обновить тест `test_direct_contour_reads_key_status` (ассерт «ровно 1 вызов»). Связано с §6.4 (тот же блок лимитов).

### 7.4 Техдолг S10.19-23 + CLI retention (T-1910)

- **fsync каталога:** `services/memory_maintenance.py:389-425` — fsync файла уже есть; добавить `os.open(dir, O_RDONLY)`+`os.fsync`
  в том же `to_thread` (POSIX), на Windows — **no-op** с честным логом (в проекте dev-среда win32).
- **CLI `manage.py retention`:** не падать при живом боте — WAL-режим чтения (`?mode=ro&immutable=0` / read-only connect)
  или временный снапшот БД (`VACUUM INTO`/копия через SQLite backup API); **dry-run остаётся дефолтом**;
  R17 — в вывод не печатать пути/значения секретов.

---

## 8. Каталог-Δ (точный, сводится единым гейтом)

| Ключ | Тип | Категория/группа | Основание |
|---|---|---|---|
| `flags.lore_compiler_enabled` | bool | `flags` / `flags_module_direct` | §13 (флаг фичи C), **default ON (О3)** |
| `limits.chat_timezone` | str (select) | `limits` / `limits_chat_behavior` | §6.1 (О4 FINAL) |
| +N текстовых `title_ru`/`description` (без новых записей) | — | все категории | §5.6 (Δ по текстам) |

- Ожидаемое **Δ счётчиков** (REGISTRY/Settings/categorized/GROUPS/mapped/TAB_RULES): **+2 / +2 / +2 / 0 / +2 / 0**
  (точное значение фиксирует @Builder; эталон `tests/test_param_catalog.py` обновляется санкционированно).
- **Санкция владельца получена (О3/О4 FINAL):** оба ключа разрешены; `flags.lore_compiler_enabled` — **default ON
  глобально** (сид `bot_settings` = true; откат — тумблер OFF без редеплоя); `limits.chat_timezone` — новый ключ,
  реюз `summary_timezone` **отклонён** (ADR-1020-3).

---

## 9. Промпт-каноны (все правки — атомарные миграции)

| # | Промпт | Файл-код | Эталон | Миграция |
|---|---|---|---|---|
| 1 | `CHAT_SYSTEM_PROMPT` (+anti-hallucination, +persona fallback, +роутинг тулов, +time) | `services/chat_prompts.py:139-172` | `plans/docs/canon/architecture.md` | новый слепок `PREV_R9→CHAT_R2020` в `services/prompt_migrations.py` |
| 2 | `SYSTEM_PROMPT` (саммари: архив ≠ свежее) | `services/summary_prompts.py:13-37` | там же | новая ступень `PREV_SUMMARY_*` |
| 3 | `LORE_STORY_SYSTEM_PROMPT` (новый, **HTML вместо Markdown — О5**) | `services/lore_prompts.py` | там же | первая ступень (нет прод-значения) |
| 4 | `FACTCHECK_SYSTEM_PROMPT` (функциональные инструкции + **право на полный вердикт, БЛОК 7.2**) | `services/factcheck_prompts.py` | там же | новая ступень |
| 5 | Tool `description` (**EN для ВСЕХ 8 схем** + строгая типизация — БЛОК 7.4) | `services/tool_schemas.py:1-201` | там же | ревизия канона 3.3 + обновление шапки `:1-5` |
| 6 | `CHAT_SYSTEM_PROMPT` — **+анти-дубликат reasoning не нужен** (БЛОК 7.2 — middleware, не промпт) | `services/chat_prompts.py:139-172` | там же | без новой ступени (инструкции не меняются) |

**Инвариант ADR-1013-3:** эталон + код + тесты — **один коммит**; тесты байт-в-байт на существующие слепки остаются зелёными.

---

## 10. План миграций

| Слой | Изменение | Тип | Откат |
|---|---|---|---|
| SQLite | `lore_stories` (аддитивная, `CREATE TABLE IF NOT EXISTS`, **без** подъёма `user_version`) | новое хранилище (О7 FINAL) | `DROP TABLE` (данные фичи) |
| SQLite | **v11 → v12:** `graph_facts` += `tg_message_id INTEGER` (nullable) + `forward_from TEXT NOT NULL DEFAULT ''` (БЛОК 7.3, §18.3) | миграция колонок (идемпотентная, guard по `PRAGMA table_info`) | аддитивные колонки оставить / rebuild (данные не теряются) |
| SQLite | read-методы: `lore_graph_slice`, `lore_dense_dialogs`, `lore_stories_*`, `search_messages_fts_count_by_author`, `insert_graph_fact(..., tg_message_id=, forward_from=)` | аддитивные API | удаление методов |
| SQLite (pg) | **нет DDL** — схемы `graph_facts` в PG нет (`pg_db.py` — только `bot_settings`/роли/админы/`uptime_events`); только новые значения `bot_settings`/`chat_params` | данные | удаление значений |
| Каталог | Δ=+2 ключа + N текстов (§8) | санкц. Δ | откат записи + revert кода |
| Каноны промптов | §9 (перенумеровано; `LORE_STORY` HTML, `FACTCHECK` no-cap, tool-schemas EN×8) | атомарно | `PROMPT_MIGRATIONS` назад + revert |
| Канон Справки (БЛОК 8) | `INFO_CANON_VERSION` 2 → 3 + `KNOWN_INFO_SNAPSHOTS` += прежний канон; `info_text.md` синхронно | атомарно (код + `plans/docs/info_text.md` + байт-тест) | вернуть прежний канон + `version=2` |
| `.env` | **не требуется** (все ключи PG/дефолт в коде) | — | — |

**Важно:** для `lore_stories` — отсутствие `user_version`-бампа обязательно (прецедент `smart_cache`/`bot_reply_parents`),
иначе ломается миграционная матрица v11 и тесты версий.

---

## 11. Учёт исторических конфликтов 1–7

| # | Конфликт | Режим | Что именно делаем |
|---|---|---|---|
| 1 | БЛОК 5.5 + 6.1 (ручной DeepDream, пустые Парадигмы) уже в 10.18 | **verify-only** | только подтверждение работоспособности + логи пропусков; ADR-1018-2 не переоткрываем |
| 2 | `dig_into_lor` (ТЗ) vs `dig_into_lore` (код, `tool_schemas.py:72`) | исправляем | везде только `dig_into_lore`; опечатка зафиксирована в §3.7/§4.3 |
| 3 | ASC-хронология D206 уже есть (`summary_memory.py:2316-2368`), но не у direct-пути | **аддитивное расширение** | §4.1: единый хелпер + применение у всех потребителей + отдельно у direct после реранка |
| 4 | Advanced-аккордеон уже есть | **рестайлинг** | §5.7: только CSS/структура внутри `<details>`, состав групп не менять |
| 5 | Tool recursion уже есть (`TOOL_MAX_ROUNDS=4`) | **описание → AMEND ред. 2** | §4 ТЗ — аудит готов; БЛОК 7.1 **меняет поведение при исчерпании** (graceful degradation), сам лимит не трогаем |
| 6 | `compile_lore_story` не существует | **новая фича** | §3: 7 → 8 инструментов + флаг + ADR-1020-4 |
| 7 | Техдолг: S10.19-15, S10.19-23, CLI retention | **закрываем** | §7.3/§7.4 (fsync файла уже есть — добавляем каталог) |
| 8 | Аудит вынес reasoning-парсинг/снятие тегов «вне эпика» (§16 ред. 1) | **AMEND ред. 2 — в скоуп** | §18.2: парсинг `reasoning_content` + stripper-middleware (БЛОК 7) |
| 9 | ADR-1020-1 утверждал «без middleware» | **AMEND ред. 2** | §18.3: тонкий Context Middleware + приоритет метаданных (не переписывая сборку) |
| 10 | `graph_facts` без forward-полей (ADR-1020-1 п.3 отклонял DDL) | **AMEND ред. 2** | §18.3: SQLite v12 += `tg_message_id`/`forward_from` (санкционировано БЛОК 7.3) |
| 11 | `tool_choice="auto"` не форсируется | **остаётся backlog** | §16: вне скоупа (ТЗ 7.4 просит только EN-схемы + типизацию) |
| 12 | Advanced-аккордеон / «Безлимит (∞)» / ручной сон | **без изменений** | §5.7 / §6.4 / §6.5 (рестайлинг/реактивность/verify-only) |

---

## 12. Риски и регресс-гейты

| Риск (от @Memory/PM) | Митигация в спеке |
|---|---|
| `tool-canon-break` | снапшот существующих 7 схем + явная ревизия канона (§3.7, §9) |
| `prompt-canon-conflict` | 5 атомарных миграций + сохранение старых слепков (§9) |
| `manual-sleep-duplication` | §6.5 verify-only, ADR-1018-2 не трогаем |
| `rag-sort-regression` | ASC меняет только порядок, не состав top-K; тесты D206 зелёные (§4.1) |
| `metadata-migration-regressions` | один хелпер + критерий «метаданные фактически присутствуют» (§2.2, ред. 3) + инвентаризационный тест, **генерируемый из реестра** `CONTEXT_POINTS.representation` (14 точек, §2.3) |
| `factcheck-full-tools-cost` | те же лимиты раундов + замер стоимости (T-1911) + поэтапный выкат |
| **Регрессия R42/R46** (XML-структура саммари и RAG-разделение `user_gossip`/`bot_knowledge`) | `build_rag_context` legacy-ветка **не меняется**; новые метки — только через `kind`-параметр; тесты R42/R46 обязательны |
| **Регрессия D206** | существующий `sort_by_timestamp` путь сохраняется байт-в-байт; новый хелпер — надстройка |
| Prompt-cache/стоимость (R7) | **FINAL (О2):** время — первым user-блоком, system статичен; prompt-cache не ломается; замер `out_chars`/стоимости до/после |
| Секреты (R17) | запрет цитирования `plans/current_task.md`; скан логов/отчётов; retention-вывод без путей/значений |
| **`reasoning-parsing-compat`** (БЛОК 7.2) | поле `LLMChatResult.reasoning` — **аддитивное, default None**; guard на пустой `content` ослабляется только при непустом reasoning; reasoning **никогда** не уходит в Telegram; stripper — no-op для текстов без тегов; тесты «пустой content без reasoning → прежнее поведение» |
| **`budget-cap-metadata-regression`** (БЛОК 7.3) | header-safe усечение: `[метаданные]: body` — заголовок неприкосновенен, режется только body; замер `facts=%d | chars=%d` до/после; D206-эталоны зелёные; тесты `total > budget` и `unlimited(-1)` |
| **`graph-facts-migration`** (БЛОК 7.3) | SQLite v11→v12 идемпотентно, guard `PRAGMA table_info`; `tg_message_id` nullable, `forward_from DEFAULT ''`; существующие INSERT/`SELECT` по именам колонок не ломаются; FTS не пересоздаётся; тест legacy→v12; откат аддитивен |
| **`english-schema-regression`** (БЛОК 7.4) | меняются **только** `description`/типизация, не имена/состав/порядок; снапшот всех 8 схем + роутинг-тесты «фраза → тул»; при флаге OFF `compile_lore_story` отсутствует, 7 прежних имён сохранены |
| **`help-text-tone-drift`** (БЛОК 8) | tone-of-voice чек-лист (дерзко/иронично, без корпоративщины, мат не переписывать); ревью-гейт; байт-тест `DEFAULT_INFO_TEXT ↔ info_text.md` атомарно; `INFO_CANON_VERSION` бамп + снапшот прежнего |
| **`infra-graph-facts-id-policy`** (БЛОК 7.3) | после v12 ID-политика §2.2 расширяется `tg:` для фактов; тест «факт с `tg_message_id` → `tg:`, без него → `fact:`» (R16) |
| **`context-middleware-scope-creep`** (БЛОК 7.3) | middleware — **тонкая обёртка** над `format_context_item`; сборка блоков (`_build_user_content`, cap-порядок) не переписывается; инвентарный тест 14 точек сохраняется |
| **`global-context-header-coupling`** (ред. 3) | заголовок `[…]` в строках `<Global_Context>`/thread ломает наивный `find(":")` → обязательные фиксы `_line_markers` (E1) и `_fact_tokens` (F2) через `strip_context_header`; тесты keep-importance + `dedup_rag_vs_global` зелёные; служебные метки — в allowlist |
| **`snapshot-churn-context-metadata`** (ред. 3) | переписывание снапшотов **только** для точек 2/3/8/13 (список файлов — ADR-1020-1 Р4), детерминированный `fake_time`; `<chat_history>`/legacy-RAG-структура — **не трогать**; любое прочее расхождение — сигнал регрессии, а не «обновить снапшот» |
| **`fact-id-enrichment-deferral`** (ред. 3) | `fact:ID`/forward для фактов (точки 4/5/10/14) отсутствуют до v12 → не имитировать; в B статус «эквивалент (ts+author)», реальное наполнение — **G/T-1924**; тест «до v12 в факт-строках нет выдуманных ID» (R16) |

---

## 13. Feature flags / Progressive Delivery (**FINAL, О3**)

- **Фича C («Летописец») — простой тумблер `flags.lore_compiler_enabled` ВКЛ/ВЫКЛ, ДЕФОЛТ ВКЛ глобально.**
  **Поэтапная раскатка 10/50/100 % и процентный механизм ОТМЕНЕНЫ** решением владельца (О3) — применяется
  существующая per-chat/глобальная инфраструктура `chat_params`/`bot_settings`; код-дефолт = `True`,
  сид `bot_settings` = `true` (глобально для всех чатов).
- **Откат:** тумблер OFF в админке — `compile_lore_story` недоступен, остальные 7 инструментов работают,
  **без редеплоя**. Полное снятие — `git revert` + удаление ключа (Δ-1).
- **БЛОК 7 (фаза G) — безусловный** (не за флагом): graceful degradation, reasoning/stripper, Context Middleware,
  v12, EN-схемы. Откат — `git revert` (правило раунда). **Исключение:** EN-схемы роутятся и при OFF-флаге —
  снапшот-тесты 8 схем фиксируют новый текст независимо от флага.
- **БЛОК 8 (фаза H) — безусловный**, откат — прежний канон Справки (`INFO_CANON_VERSION` 2 + снапшот).
- **Фазы B/D/E — безусловные**, откат `git revert`; tz-настройка — **данные**, не флаг.
- **Порядок доставки:** A (отчёт + spec + ADR) → Human Gate ✅ → {B ∥ D} → C (флаг ON) → E → **G (БЛОК 7) → H (БЛОК 8)** → F (SPEC_READY → деплой).
  > **Примечание:** G/H добавлены после гейта; порядок G → H (справка описывает уже реализованное в G/C),
  > внутри G рекомендуется **7.1 → 7.2 → 7.4 → 7.3** (7.3 трогает БД v12 — делать после стабилизации tool-loop).

---

## 14. Открытые решения — **Human Gate пройден, открытых решений нет**

**Вердикты владельца (зафиксированы FINAL, 16.09.2026):**

| # | Вопрос | Решение FINAL | Где в спеке |
|---|---|---|---|
| **О1** | Дельта по дублям 10.18 (БЛОК 5.5/6.1) | **verify-only** — заново не пишем, ADR-1018-2 не переоткрываем; привязать manual DeepDream к кнопке нового UI | §6.5, §5 (фаза D) |
| **О2** | Куда инжектить «Текущее время» | **Вариант A:** первым **user-блоком**; system статичен; **Prompt Caching ломать запрещено** | §6.1, ADR-1020-3 (AMEND) |
| **О3** | Санкция на 7 → 8 инструментов + флаг | **Разрешено.** Простой Feature Flag ВКЛ/ВЫКЛ, **дефолт ВКЛ глобально**; поэтапная раскатка отменена | §3.1, §13, ADR-1020-4 (AMEND) |
| **О4** | Новый ключ каталога «Часовой пояс чата» | **`limits.chat_timezone`** (Δ+1); реюз `summary_timezone` отклонён | §6.1, §8, ADR-1020-3 (AMEND) |
| **О5** | UI-объём + формат доставки историй | **UI подтверждён полностью** (структура меню не меняется). Глобальный `parse_mode` = **None**; для историй Летописца локально **`parse_mode=HTML`** + промпт с HTML-тегами вместо Markdown | §3.5, §5, ADR-1020-6 (AMEND) |
| **О6** | Политика `plans/current_task.md` | **untracked + `.gitignore`; секрет не коммитить, значение не цитировать** (R17) | §1.3, §12 (R11) |
| **О7** | DDL для UPD-хранилища | **аддитивная `lore_stories` без бампа `user_version`** | §3.6, §10 (ADR-1020-4) |

> Открытых вопросов к владельцу **не осталось**. Новые технические решения БЛОК 7/8 (v12, stripper, EN-схемы,
> Context Middleware, канон Справки) — **архитектурные** и не требуют гейта: опираются на уже выданные санкции
> (БЛОК 7/О3–О5/О7) и не меняют НЕ-скоуп §1.3. См. ADR-1020-7/1020-8.

---

## 15. Тест-план и гейты (сводно)

1. **Метаданные:** формат `format_context_item` (все kind, R16-опускание пустых полей); инвентаризационный тест
   «нет голого текста» по 14 точкам §2.3.
2. **Хронология:** ASC у всех потребителей + D206-тесты зелёные + состав top-K не изменился (снапшот).
3. **`/summary`:** архивная маркировка присутствует; промпт-миграция байт-в-байт; R42/R46 зелёные.
4. **`dig_into_lore`:** JSON-контракт, `mentions_by_authors` >1 автора, `snippets` непусты при попаданиях,
   Anti-Hallucination Guard в каноне.
5. **Time Injection/tz:** строка времени в правильном месте; `-1` → «Безлимит (∞)»; один запрос `chat_params` при смене чата.
6. **`compile_lore_story`:** 8 инструментов в снапшоте; `graph_facts` ASC; `chronological_dialogs` ASC;
   UPD-ветка (второй запрос → `is_update=true` + блок UPD); флаг OFF → тул недоступен; таймаут/ошибка → честный error,
   диалог не роняется.
7. **UI:** `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; тесты binding/routing/тумблера/тикера;
   **снимок навигации** (меню не изменено); sticky-save vs auto-save (без перезатирания).
8. **Фактчекер:** тул-сет доступен; метаданные в контексте; промпт-миграция; `key_status` вызван **1×**;
   retention при живом боте (WAL); fsync каталога (best-effort).
9. **Гейты эпика:** полный `pytest` 0 failed; каталог-Δ санкционирован; R17-скан чист; `git diff --check`;
   русские conventional commits; **SPEC_READY владельцу ДО деплоя**.
10. **БЛОК 7.1 (tool fail-safe):** `ToolLoopResult` — `str`-совместим (`str(result).strip()` = текст);
    лимит раундов → `degraded=True, reason="round_limit"`, ответ **не пустой**, `tool_trace` заполнен;
    `LLMError` на round>0 → деградация (не исключение); `round_index==0` provider-reject → прежний plain-fallback;
    `NoApiKeyForChat` — прежний проброс; лог потерянных раундов (кол-во/тулы/остаток, без текстов — R17);
    эталоны `direct_chat` (молчание+🗿 на пустой финал) зелёные.
11. **БЛОК 7.2 (reasoning):** `LLMChatResult.reasoning` — аддитивно; reasoning-only ответ **не** роняет парсер;
    `strip_reasoning_tags` вырезает `<reasoning>/<thinking>/<scratchpad>` (в т.ч. незакрытый — defensive);
    применён на **4 путях**: direct (`:656`), tool-loop (финал), factcheck (`:79`), summary (`:238`, через `cleanup_llm_text`);
    текст без тегов — байт-в-байт неизменен; reasoning-текст не попадает в Telegram.
12. **БЛОК 7.3 (context middleware + v12):** header-safe усечение — `[…]`-заголовок сохраняется при любом
    `total > budget`; `-1` (unlimited) — усечения нет; инвентарный тест 14 точек зелёный; миграция v11→v12
    идемпотентна (guard + `PRAGMA user_version=12`), legacy-БД → колонки есть, данные сохранены, FTS не тронут;
    факт с `tg_message_id` → `tg:`, без — `fact:` (R16).
13. **БЛОК 7.4 (EN-схемы):** снапшот всех 8 `description` (EN, без кириллицы); имена/порядок/`required` не изменились;
    роутинг-тесты «фраза → тул» зелёные; `additionalProperties:False` у всех; enum/min-max строго типизированы.
14. **БЛОК 8 (Справка):** `INFO_CANON_VERSION == 3`; `DEFAULT_INFO_TEXT ↔ info_text.md` байт-в-байт;
    `KNOWN_INFO_SNAPSHOTS` содержит прежний канон (миграция PG идемпотентна); в тексте есть Летописец/Фактчек-апдейт/
    безлимиты; tone-of-voice чек-лист пройден; структура вкладок/меню не изменена (снимок навигации).

---

## 16. Вне скоупа round1020 — backlog следующего шага Agentic AI (**AMEND ред. 2**)

> **AMEND ред. 2 (Human Gate, БЛОК 7):** пункты 1–4 из списка ред. 1 и часть пункта 5 (наблюдаемость цепочек)
> **ПЕРЕНЕСЕНЫ В СКОУП** эпика → см. §18 (ADR-1020-7). Ниже — что реально осталось вне round1020.

**Реализуется в round1020 (перенесено по решению владельца):** §18.1 (graceful degrade + устойчивость к `LLMError`
на поздних раундах), §18.2 (парсинг `reasoning_content` + срез тегов-черновика), §18.3 (Context Middleware +
`graph_facts` метаданные + приоритет заголовка), §18.4 (EN-схемы + строгая типизация). Наблюдаемость цепочек —
частично: `ToolLoopResult.tool_trace` + лог потерянных раундов.

**Остаётся вне скоупа (backlog):**

1. **Stop-condition по пустому результату тула** и **дедуп повторных одинаковых вызовов** — политика решает модель;
   `ToolContext` по-прежнему не несёт состояния цикла (`tool_router.py:261-275`).
2. **LLM-intent-router** (второй LLM-вызов на классификацию) + **форсирование `tool_choice`** (сейчас `"auto"`,
   `tool_loop.py:45`) — нет инфраструктуры маленькой модели/кэша решений и бюджета на второй вызов.
3. **Вложенные суб-агенты / plan-act** — `dispatch` терминален (нет API под-цикла с урезанным tool-сетом).
4. **Снятие/увеличение cap `TOOL_MAX_ROUNDS`** — лимит `4` сохраняется (БЛОК 7.1 меняет только поведение при исчерпании).
5. **Полный рефакторинг сборки контекста на объекты `ContextBlock`** — отклонено (§18.3: тонкий middleware).

---

## 17. Трассировка задач (@PM → спека)

| Задача | Раздел спеки |
|---|---|
| T-1866…T-1871 (аудит A) | `plans/reports/round1020_llm_engine_audit.md` |
| T-1872…T-1874 (метаданные) | §2, ADR-1020-1 |
| T-1875/T-1876 (роутинг/ASC) | §3.7, §4.1, ADR-1020-2 |
| T-1877 (`/summary`) | §4.2 |
| T-1878 (dig сырые факты + промпт) | §4.3 |
| T-1879 (Time Injection + tz) | §6.1, ADR-1020-3 |
| T-1880/T-1881 (анти-галлюцинации/fallback) | §4.3, §4.4 |
| T-1882 («Безлимит (∞)») | §6.4 |
| T-1883 (verify-only 5.5) | §6.5 |
| T-1886…T-1893 (Летописец) | §3, ADR-1020-4, ADR-1020-6 |
| T-1894…T-1904 (UX/UI) | §5 |
| T-1905…T-1912 (фактчек/техдолг) | §7, ADR-1020-5 |
| T-1913…T-1917 (гейты/деплой) | §13, §15 |
| **БЛОК 7** (Agentic AI): T-1918 (гейт), T-1919 (7.1), T-1920 (7.2a), T-1921 (7.2b), T-1922 (7.2c), T-1923 (7.3a), T-1924 (7.3b), T-1925 (7.4), T-1926/T-1927 (тесты/ревью) | **§18**, ADR-1020-7 |
| **БЛОК 8** (Справка UI): T-1928 (гейт), T-1929 (тексты), T-1930 (тесты), T-1931 (приёмка) | **§19**, ADR-1020-8 |
| **AMEND** ADR-1020-1/2/3/4/5/6 (О2/О4/О3/О5 + middleware/EN/v12) | §2.4, §3.5, §6.1, §8, §10, §14 |

---

## 18. БЛОК 7 — Agentic AI & рефакторинг движка (BRIDGE: ADR-1020-7) — **RED. 2 / Human Gate**

> **Скоуп:** §18.1 fail-safe tool-loop · §18.2 Scratchpad/Reasoning · §18.3 Context Middleware + `graph_facts` v12 ·
> §18.4 EN-схемы тулов. **Порядок реализации (рекомендация):** 7.1 → 7.2 → 7.4 → 7.3.
> **НЕ трогаем:** `TOOL_MAX_ROUNDS`, `_TOOL_CALLS_PER_ROUND_MAX`, имена/состав/порядок тулов, сборку `_build_user_content`.

### 18.1 Tool Recursion Fail-Safe (БЛОК 7.1) — `services/tool_loop.py`

**Проблема (baseline):** исчерпание 4 раундов → `raise LLMBadResponseError` (`tool_loop.py:91-93`) →
`direct_chat` отвечает **молчанием + 🗿** (`direct_chat_service.py:647-655`); `LLMError` на `round_index > 0`
перехватывается только для `round_index == 0` (`tool_loop.py:49-57`) → на поздних раундах улетает в
`CHAT_ERROR_PHRASES`. Теряется уже оплаченный бюджет и весь «надуманный» контекст.

**Контракт результата — новый `ToolLoopResult` (str-совместимый):**

```python
class ToolLoopResult(str):
    """Финальный текст tool-цикла. ЯВЛЯЕТСЯ str → `str(raw).strip()` и весь
    downstream (send_chunked_reply/remember_bot_reply) работают БЕЗ правок.
    Доп. телеметрия — атрибуты (не сериализуются)."""
    rounds_used: int          # сколько LLM-раундов реально израсходовано (1..4)
    degraded: bool            # True — ответ получен деградацией (не штатный финал)
    reason: str               # "ok" | "round_limit" | "llm_error"
    tool_trace: list[dict]    # [{"round": int, "tool": str, "ok": bool, "out_chars": int}]
    # __new__(cls, text, *, rounds_used, degraded=False, reason="ok", tool_trace=None)
```

- **Обратная совместимость с `direct_chat_service.py:620-631`:** сигнатура `chat_with_tools(...)` не меняется
  (тип возврата `str` → `ToolLoopResult`, подкласс `str`). `answer = str(raw).strip()` (`:656`) даёт **plain-строку**;
  `remember_bot_reply` (`:667`) принимает ту же строку. Никаких правок вызова не требуется.
  **Инвариант:** для штатного финала (`reason="ok"`) результат **байт-в-байт** совпадает с прежним.

**Правила деградации (новое):**

| Ситуация | Baseline | Новое поведение |
|---|---|---|
| Исчерпаны `TOOL_MAX_ROUNDS`, финального текста нет | `raise LLMBadResponseError` → тишина+🗿 | `degraded=True, reason="round_limit"`: вернуть **последний непустой `content`**, накопленный в раундах; если такого нет — **саркастичная заглушка** `TOOL_LOOP_FALLBACK_PHRASE` (код-константа) |
| `LLMError` на `round_index > 0` | проброс → `CHAT_ERROR_PHRASES` | `degraded=True, reason="llm_error"`: та же логика (partial → заглушка) |
| `LLMError` на `round_index == 0` (провайдер не умеет tools) | plain-вызов без tools (FR-15) | **без изменений** |
| `NoApiKeyForChat` | проброс → sandbox-фраза | **без изменений** |
| Пустой финал (нет `tool_calls` и нет текста) | `raise LLMBadResponseError` → тишина+🗿 | **без изменений** (это не «потерянный» ответ: думать было нечего; сохраняем FR-14/65.1 и 🗿-контракт) |

- **Логирование потерянных раундов (обязательно, R17):**
  `logger.warning("[tools] degraded | reason=%s | rounds_used=%d | lost_rounds=%d | tools=%s | partial_chars=%d")` —
  только имя тулов/числа/длины, **без аргументов и без текста** (R17).
- **Наблюдаемость:** `tool_trace` заполняется на каждом исполнении (`ok=True/False`) — база для метрик следующего шага.
- **Влияние на фазу E:** `chat_with_tools` переиспользуется фактчекером (§7.1) → деградация даёт вердикт вместо
  молчания. Тест «фактчекер не падает при лимите раундов» обязателен.
- **Тесты:** см. §15 п.10. Эталоны молчания (пустой финал) остаются зелёными; тесты, ассертившие `LLMBadResponseError`
  **на лимите раундов**, обновляются осознанно (точное число фиксирует @Builder).

### 18.2 Scratchpad / Reasoning (БЛОК 7.2) — `llm_client` + stripper-middleware

**A. Парсинг `reasoning_content`** (`services/llm_client.py::generate_chat`, `:959-1045`, разбор `:1005-1032`):

- В `LLMChatResult` (`:219-225`, `@dataclass(frozen=True)`) добавляется **аддитивное** поле
  `reasoning: str | None = None` (дефолт → существующие конструкторы/тесты не ломаются).
- В `generate_chat` после `message = choice.get("message") or {}` (`:1005`) читается `reasoning_content`
  с алиасами `reasoning`/`thinking` (первое непустое) → `reasoning_text`.
- **Guard пустого ответа** (`:1031-1032`) ослабляется: `raise` только если
  `content is None and not tool_calls and not reasoning_text`. `tool_loop`/`direct_chat` **не отправляют**
  `reasoning` пользователю (это черновик): поведение «reasoning-only ответ» = прежнее молчание/деградация,
  но **без** нештатного `LLMBadResponseError` и с WARNING-логом `reasoning_chars=N`.

**B. Stripper текстовых reasoning-тегов (middleware):**

- Новый модуль `services/reply_postprocess.py::strip_reasoning_tags(text) -> str`:
  вырезает блоки `<reasoning>…</reasoning>`, `<thinking>…</thinking>`, `<scratchpad>…</scratchpad>`,
  `<analysis>…</analysis>`, `<thought>…</thought>`; **незакрытый** тег → срез до конца + WARNING (defensive).
  Без тегов — **no-op** (байт-в-байт).
- **Единая точка применения на всех 4 путях вывода:**
  1. **direct** — `direct_chat_service.py:656`: `answer = strip_reasoning_tags(str(raw).strip())`;
  2. **tool** — финальный `return text` в `tool_loop` (idempotent, страховка для tool-пути);
  3. **factcheck** — `factcheck_service.py:79` (рядом с `cleanup_llm_text`);
  4. **summary** — `summary_generator.py:238` (рядом с `cleanup_llm_text`).
- **Реюз:** `cleanup_llm_text` (`summary_cleanup.py:8-22`) дополняется вызовом `strip_reasoning_tags` —
  тогда factcheck/summary получают срез автоматически; direct/tool вызывают напрямую (они `cleanup_llm_text`
  не используют — см. аудит Q2).
- **Снятие канона «1–2 предложения» ЛОКАЛЬНО (P0):**
  - `compile_lore_story` — изолирован каноном `LORE_STORY_SYSTEM_PROMPT` (§3.3) + режим доставки §3.5;
    дополнительно, при `ctx.lore_compiled`, доставка использует **готовый текст истории** (детерминизм в коде),
    а не сжатую диспетчерскую ремарку.
  - `factcheck` — `FACTCHECK_SYSTEM_PROMPT` **не наследует** `CHAT_SYSTEM_PROMPT`; явной строкой закрепляется
    право на полный вердикт (см. §7.2, §9 п.4).
  - **`CHAT_SYSTEM_PROMPT` (`chat_prompts.py:171-172`) НЕ меняется** — канон бота (ядро характера) сохраняется.
  > **Уточнение к T-1922 (приоритет ADR):** исключение реализуется **НЕ правкой канона** `CHAT_SYSTEM_PROMPT`,
  > а **режимом доставки** (`ctx.lore_compiled` + готовый текст истории) и изоляцией `LORE_STORY_SYSTEM_PROMPT`;
  > для фактчека — правка его **собственного** промпта. Формулировку T-1922 «исключение по режиму в
  > `CHAT_SYSTEM_PROMPT`» считать **устаревшей** (см. ADR-1020-7 §2).

**Как не сломать 6326 тестов:** все изменения аддитивны (новое поле с дефолтом; stripper — no-op без тегов;
`ToolLoopResult` — подкласс `str`). Единственные осознанные правки — тесты, прямо ассертившие
`LLMBadResponseError` на лимите раундов и снапшоты EN-схем (§18.4). Число правок @Builder фиксирует в задаче.

### 18.3 Context Assembly — единый Middleware + `graph_facts` v12 (БЛОК 7.3)

**A. Единая точка инъекции (AMEND ADR-1020-1).** Инвентаризация аудита (Q3) дала **≥14 точек** подачи контекста
(§2.3). Вводится **тонкий** `services/context_middleware.py` — обёртка над `canonical_context.format_context_item`
(НЕ переписывание сборки):

```python
def context_item(*, ts=None, author=None, item_id=None, forward_source=None,
                 text="", kind="msg") -> str: ...          # → format_context_item (§2.2)
def metadata_header(text: str) -> tuple[str, str]: ...     # ("[Дата Время | Автор | ID]:", " body")
def truncate_keep_header(block: str, limit_tokens: int, kind: str = "") -> str: ...
```

- Точки применения §2.3 заменяют прямые вызовы `_fact_prefix`/`_format_origin_labeled_line`/ручные f-строки
  на `context_middleware.context_item(...)` там, где нужен **ярус A** (ред. 3: точки 2/3/8/13 — из фазы B уже
  с каноническим заголовком, т.к. T-1874 форматирует их `format_context_item`); точки яруса B (§2.3)
  не переписываются; инвентарный тест «нет голого текста» (генерируется из реестра) сохраняется.
- **Нормализация строк (ред. 3):** `strip_context_header` применяется там, где строка парсится как
  `предикат: контент` (`_line_markers` E1, `_fact_tokens` F2) — иначе заголовок с `msg:<id>` уезжает в контент.
- **Приоритет метаданных (ВЫСШИЙ):** `truncate_keep_header` **никогда** не режет ведущий `[…]`-заголовок —
  режется **только body**; при исчерпании body блок не «исчезает из-за заголовка».
- **Интеграция в бюджет:** `_apply_context_budget` (`direct_chat_service.py:1200-1351`) и
  `_truncate_block` (`:1353+`) для контентных kinds (`rag`/`global`/`thread`/`map`/`anchors`) используют
  `truncate_keep_header`; неприкосновенные kinds (`target`/`protected`/`lore`/`current`/`sandwich`/`relations`)
  — без изменений. `unlimited (-1)` — как сейчас, усечения нет.
- **Замер (обязательный гейт):** `facts=%d | chars=%d` до/после; D206/R42/R46-эталоны зелёные.

**B. Расширение схемы `graph_facts` (SQLite v11 → v12):**

| Колонка | Тип | Дефолт | Смысл |
|---|---|---|---|
| `tg_message_id` | `INTEGER` (nullable) | `NULL` | id TG-сообщения-источника → ID-политика `tg:` (§2.2) |
| `forward_from` | `TEXT NOT NULL DEFAULT ''` | `''` = не forward | источник пересылки → сегмент `Переслано: …` |

- **Миграция SQLite:** новый `_migrate_graph_facts_metadata_v12()` в `database.py` (вызов в `initialize()`
  после `_migrate_edges_fact_id_v10`, до `PRAGMA user_version`): guard по `PRAGMA table_info(graph_facts)`,
  затем `ALTER TABLE graph_facts ADD COLUMN tg_message_id INTEGER` и
  `ADD COLUMN forward_from TEXT NOT NULL DEFAULT ''`; **идемпотентно**; `_SCHEMA_VERSION = 12`.
  FTS `graph_facts_fts` **не пересоздаётся** (rowid не меняются, прецедент D201).
- **Индексы:** новых **нет** (запросов по `tg_message_id` нет; `idx_graph_facts_chat_origin` сохраняется) —
  документированное решение. При необходимости `idx_graph_facts_tg` добавляется аддитивно без бампа.
- **PG:** DDL **не требуется** — таблицы `graph_facts` в PostgreSQL нет (`pg_db.py` — только
  `bot_settings`/роли/админы/`uptime_events`); зафиксировать no-op явно.
  > **Уточнение к T-1924 (приоритет ADR):** шаг «pg — `ALTER TABLE … ADD COLUMN IF NOT EXISTS`» **не применим** —
  > в PG нет этой таблицы; **не создавать** phantom-таблицу `graph_facts` в PG (вне скоупа). PG-миграция = no-op.
- **Влияние на существующие запросы:** `SELECT` идут по именам колонок (aiosqlite `Row`) → новые поля аддитивны;
  существующие `INSERT` не трогаются (дефолты); `insert_graph_fact` получает **опциональные** kwargs
  `tg_message_id=None, forward_from=""` (R16-аддитивно); запись метаданных выполняется в точках, где источник
  известен (`_memorize_*`/`smart_messages`-контекст), иначе — `NULL`/`''` (не выдумываем, R16).

**C. Учёт накопленных ограничений Scanner (10.19):** `resolve_context_tokens`/sentinel-семантика контекста
(`0` = не задано, `-1` = безлимит до `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`) **сохраняются**;
header-safe усечение не должно вернуть регресс S10.19-13 (`-1` → «1 токен»). Открытый Low S10.19-15
(двойной `key_status`) и S10.19-23 (fsync каталога) закрываются в фазе E (§7.3/§7.4).

### 18.4 Agentic Factorization — Schemas EN + строгая типизация (БЛОК 7.4) — `services/tool_schemas.py`

- **Перевод `description` ВСЕХ 8 схем на английский** (имя, `type`, `enum`, `required`, порядок `TOOL_CALLING_TOOLS`
  НЕ меняются). `dig_into_lore`/`compile_lore_story` — формулировки §3.7 (уже EN); остальные 6 (`execute_web_search`,
  `query_chat_memory`, `summarize_video`, `download_media`, `get_bot_health`, `get_recent_history`) — новые EN-описания
  с сохранением смысла и приоритетов R9 (память → лор → веб). **Параметры** (`query`/`year`/`person`/`mode`/`depth`/…)
  тоже переводятся.
- **Ревизия канона 3.3:** шапка `tool_schemas.py:1-5` («не менять без ревизии spec») переписывается под ред. 2
  (EN — новый канон описаний); эталон `plans/docs/canon/architecture.md` обновляется **тем же коммитом** (ADR-1013-3).
- **Строгая типизация:** у всех схем — `additionalProperties: False`; `enum` для `mode`/`time_range`/`quality`;
  `minimum`/`maximum` для `depth` (`1..150`); у `summarize_video.mode` добавляется отсутствующее `description`;
  `required` — минимально необходимое (как сейчас). **Семантических изменений параметров нет.**
- **Риск регрессии роутинга** (`english-schema-regression`): митигация —
  (1) снапшот-тест всех 8 `description`; (2) роутинг-тесты «фраза → ожидаемый тул/без тула»;
  (3) при OFF-флаге летописца состав = 7 прежних имён (с новыми EN-описаниями) — тест «флаг OFF → тул недоступен».
- **`tool_choice="auto"` НЕ форсируется** в этом эпике (backlog §16 п.2) — решение владельца ограничено EN+типизацией.
  > **Уточнение к T-1925 (приоритет ADR):** пункт «политика форсирования `tool_choice` (per-intent)» — **вне скоупа**
  > round1020 (остаётся backlog §16 п.2); в T-1925 реализуется **только** EN-описания 8 схем + строгая типизация.

---

## 19. БЛОК 8 — Актуализация раздела «Справка» (UI) (BRIDGE: ADR-1020-8) — **РЕД. 2 / Human Gate**

**Где живёт «Справка» (точки интеграции — код не менять этим шагом):**

| Слой | Файл:строка (baseline) | Роль |
|---|---|---|
| Источник текста (код-канон) | `services/info_service.py:83-135` (`DEFAULT_INFO_TEXT`) | rich-HTML справки; байт-эталон `plans/docs/info_text.md` |
| Версионирование | `services/info_service.py:145` (`INFO_CANON_VERSION=2`), `:148` (`KNOWN_INFO_SNAPSHOTS`) | идемпотентная миграция прод-PG |
| Second block («Гайд») | `services/info_service.py:169-174` (`GUIDE_KEY`, `GUIDE_SEED_FILE` = `plans/docs/intelligence_user_guide.md`) | Markdown-гайд (сид) |
| Миграция/сид | `services/config_cache.py:230-334` (`_write_info_canon`, `_seed_intelligence_guide`) | перенос в PG + бампа версии |
| Отрисовка | `web/index.html:2564-2651` (вкладка `activeTab === 'info'`), `web/app.js:4390-4460` (`loadInfo`/`resetInfoCanon`/`loadGuide`) | UI; структура вкладок **не меняется** |

**Что обновить (контент):**

1. **Новый раздел «Летописец» (`compile_lore_story`)** — как просить («Бот, поясни за …», «расскажи историю про …»),
   что вернётся (саркастичная история с именами/цитатами), и что при повторном запросе будет блок **UPD (Свежак)**.
2. **Обновлённый Фактчек** — теперь видит **и локальную историю чата** (`dig_into_lore`/`compile_lore_story`),
   и веб; может «ткнуть в дату/время» по меткам `[Дата Время | Автор | Переслано: откуда]`; вердикт полный (не 1–2 предложения).
3. **Безлимиты** — объяснить сентинелы: `-1` → **«Безлимит (∞)»** (с потолком безопасности для контекста),
   per-chat override (глобальный → чат → дефолт), и что лимиты видны в «Модули → Бюджеты».
4. Удалить/актуализировать устаревшие механики, если такие найдутся в текущем тексте (без выдумывания фактов).

**Tone of voice (КРИТИЧНО):** сохранить существующий **дерзкий, ироничный** стиль; не превращать в корпоративный
мануал; не переписывать ненормативную лексику (та же политика, что для промптов). Проверяется ревью-гейтом по
чек-листу: `<h1>`/`<h2>`-структура, разговорные конструкции, отсутствие канцелярита.

**Механика канона (атомарно, ADR-1016-3):**
- `INFO_CANON_VERSION` 2 → **3**; `KNOWN_INFO_SNAPSHOTS += (DEFAULT_INFO_TEXT v2,)`;
  `DEFAULT_INFO_TEXT` и `plans/docs/info_text.md` обновляются **байт-в-байт одним коммитом** (байт-тест).
- «Гайд по возможностям» (`plans/docs/intelligence_user_guide.md`) — при необходимости синхронно, тем же коммитом.
- **Δ каталога = 0** (текст справки — не параметр каталога).

---

**Handoff:** `@Orchestrator` — **Architecture phase (ред. 2) завершена.** Human Gate пройден (О1–О7 FINAL, §14);
спека дополнена БЛОК 7 (§18, ADR-1020-7) и БЛОК 8 (§19, ADR-1020-8); ADR-1020-1/3/4/6 — AMEND.
Дальше: `@Memory` (Step 3, лог решений) → **@Builder** (Step 4) по фазам B/D ∥ → C → E → **G → H** → F
(SPEC_READY → деплой). Режим этого шага — **READ-ONLY по коду** (изменялись только spec/ADR).
