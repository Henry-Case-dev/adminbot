# ADR-1026-18 — A6 «Memory Lookup API»: новый LLM-инструмент `get_user_context` поверх существующего досье+RAG (§32–§35), атомарное расширение канона 11→12, envelope результата из 5 полей §33, purpose-роутинг, lazy RAG, границы A4/A5/A7

- **Статус:** **Accepted** (merge в `plans/ARCHITECTURE.md` **§87**, 25.09.2026; T-3623 @Architect). **Accepted = решение принято и включено в pending epic-release Эпика 3; НЕ «deployed»** — release policy **EPIC_ONLY**, deployment **DEFERRED_TO_EPIC** (пер-фича деплоя/тега/bump нет; bump — в агрегате Эпика 3 на границе эпика).
- **Фича:** A6 `memory-lookup-api-round1026` (Эпик 3 «Agentic Intelligence», Wave 4, Раунд 10.26). **P0.**
- **Тип:** backend/memory tool — новый LLM-видимый инструмент; **read-only**; **Δ DDL = 0**; **Δ каталога = 0**; без 3-го LLM-вызова; канон инструментов **11 → 12**.
- **ТЗ-основание:** `plans/current_task.md` **§32** (`:5066–5092`), **§33** (`:5095–5133`), **§34** (`:5136–5177`), **§35** (`:5180–5214`); ориентиры **§52** п.11 (`:5775`), п.12 (`:5777`), п.14 (`:5781`), **§53** (`:5818–5850`), **§54** п.6 (`:5882`); границы §22–§25 (A4), §26–§31 (A5), §36–§48 (A7), §49/§51 (A9), §104 `generate_image` (не трогать).
- **Durable-вход:** `plans/docs/agentic-audit-round1026.md` (A0, APPROVED) — **EV-21** «`get_user_context` отсутствует»; `#duplicates`; §8.2 «досье — не инструмент, вводится впервые без дублирования `build_persona_card`»; §8.3 (REUSE `build_persona_card`/`format_dossier_block`/RAG; второй RAG-контур/резолвер запрещены).
- **Baseline (Step 0 @Memory):** HEAD **`e8646af`** + UNCOMMITTED epic-release дерево A2/A3/A5 (79 файлов dirty) — не трогать/не коммитить; `APP_VERSION` **2.58.30**; канон **11**; SQLite **v12**; Δ DDL=0; Δ каталога=0 (470/427/445/101/99/21); анкер отката `e8646af`.
- **Связано (REUSE):** ADR-1026-15 (A2: envelope `ToolLoopResult.tool_results`/`ToolContext.result_for`, §17-лимиты, **прецедент атомарного расширения канона D5**), ADR-1026-14 (A1: 2-вызовность, env-only kill-switch-прецедент), ADR-1026-13 (A0: durable-аудит, `#duplicates`/`#epic3-reuse`; **санкция D3 ИСХЕРПАНА A2 — повторно НЕ используется**), ADR-1026-16/-17 (A3/A5: паттерн env-only/аддитивности; **DDL A6 не использует**), ADR-1020-4 (канон/«новое — в хвост»), ADR-1020-1 (ID-политика `tg:`/`msg:`), ADR-1013-3 (промпт-канон — **NOT_APPLICABLE**, кроме атомарного `description` новой схемы).

## Контекст

§32 требует дать LLM возможность запрашивать досье **по инициативе LLM** (on-demand), не подмешивая полные досье всех пользователей и не используя «один огромный универсальный dump»; каждый сценарий («что знаешь о Лёхе» / «ответь в стиле Лёхи» / «как Лёха реагирует» / «нарисуй Лёху») требует своего набора данных. §33 задаёт рекомендуемый контракт `get_user_context(user_id, chat_id, purpose, max_items)` с шестью purpose, прямо разрешает **адаптировать** API к существующим инструментам, запрещает новую базу памяти и требует результат из **5 элементов** (факты, источники, степень подтверждённости если доступна, временной контекст, признак отсутствия данных) и запрет выдавать неподтверждённые предположения за факты. §34 вводит досье+RAG: досье — «что известно», RAG — «какие сообщения подтверждают/дополняют»; RAG **не** вызывать автоматически всегда; пример speech_style (резолв → сведения о стиле → при необходимости несколько характерных сообщений → краткий style profile → Вербализатору); «не подмешивать сотни сообщений», «не копировать большие куски личной переписки», «не менять системную личность бота — только временная стилизация». §35 требует комбинирования памяти и фактчека через общий механизм цепочек и разведения задач: память подтверждает, что утверждение **было высказано**, фактчек проверяет **содержание**.

**Фактическое состояние baseline (Step 0 EVIDENCE + карта кода).** `get_user_context` **отсутствует** (A0 EV-21, grep 0). Канон инструментов — **11** (`services/tool_schemas.py:427–439`); `active_tools` и env-гейт-прецедент — `:469–494` / `_article_tool_enabled:460–466`; диспетчер `services/tool_router.py:497–523` (R17-прецедент `:519–523`). Досье/граф: `direct_chat_service.build_persona_card:2303` (presenter строки с чат-лором), `database.get_persona_card:4624` (факты `target_user`+`status='confirmed'`) + `get_generated_dossier`/`get_protected_facts`/`list_chat_memes`, `dossier_prompts.format_dossier_block:568`, AliasResolver (`summary_aliases.py`). `graph_facts` несёт `origin` (CHECK-список), `created_at`, `tg_message_id`, `weight`, `status`, `last_confirmed_at`, `target_user`, FTS5/vec. RAG: `summary_memory.search_long_term:1826`, `get_rag_context:2479`, `get_rag_facts`, `vector_search`. **GAP:** ровно этого инструмента нет; `appearance` выделенного хранилища не имеет; `speech_style` per-user профиля не имеет (есть только chat-anchored `_build_style_anchors:2038` про ответы бота). A2-envelope и §17-лимиты (`tool_loop.py:42–51`) готовы к reuse.

**Открытые вопросы Step 1 (U1–U7)** требуют lasting-решений: U1 storage mapping `appearance`/`speech_style`; U2 набор фактчек-инструментов; U3 проводка источников/подтверждённости; U4 семантика `max_items`; U5 Δ каталога; U6 порядок с A1-координатором; U7 применимость A0-гипотез.

## Решения

**D1. Санкция расширения канона 11 → 12 — атомарно, для `get_user_context`; env-only `MEMORY_LOOKUP_ENABLED` (default ON).**
- Канон `TOOL_CALLING_TOOLS` расширяется **ровно на +1** инструмент `get_user_context` **атомарно**: JSON-схема + регистрация **в хвост** (первые **11 — байт-в-байт**, ADR-1020-4) + запись диспетчера + метод роутера + `active_tools` + env-гейт + тесты `len==12` — **одним изменением**. Прецедент — **ADR-1026-15 D5** (канон 10→11, `fetch_article`).
- **Основание:** A0 **ADR-1026-13 D3** замораживал канон на 10 с разовой санкцией расширения; эта санкция **уже использована A2** (10→11) и **повторно НЕ используется** (прямое требование `tasks.md`). A6 получает **новую** санкцию настоящим ADR (11→12) по прецеденту D5-рецепта ADR-1026-15.
- **Kill-switch `MEMORY_LOOKUP_ENABLED`** (env-only `ClassVar`, default ON, Δ каталога=0): OFF → инструмент **не объявляется** в `active_tools` (эффективный набор = 11); наличие схемы и счётчик `TOOL_CALLING_TOOLS==12` **безусловны**. Константа имени `MEMORY_LOOKUP_TOOL_NAME="get_user_context"`.
- **Не второй контур:** тот же `ToolRouter`/`tool_loop`/`ToolDeps`/`ToolContext`.
- **Альтернативы:** (i) не расширять канон (инструмент недоступен LLM) — отклонено (§32/§33 требуют LLM-инициативу); (ii) переиспользовать санкцию A0 D3 — **запрещено** (исчерпана A2); (iii) каталожный kill-switch — отклонено (Δ каталога ≠ 0, U5).

**D2. Контракт инструмента — адаптация §33 к существующим инструментам.**
- Имя `get_user_context` (рабочее, из §33). Параметры: `person` (required, string: имя/алиас/`@username`/id строкой), `user_id` (optional, integer, альтернативный якорь; приоритет над `person`), `purpose` (required, enum из 6), `max_items` (optional, integer ≥1).
- **`chat_id` — не параметр модели:** берётся из `ToolContext` (как у всех существующих инструментов). Это и есть адаптация (§33 `:5116–5118`), а не слепое копирование сигнатуры.
- **Невалидные аргументы (§52 п.14):** отсутствие `person` и `user_id`; неизвестный `purpose`; не-строковый `person`; не-int/`<1` `max_items` → `{"status":"error","error":"invalid_arguments","detail":"<code>"}`; инструмент **не бросает**, цепочка/другие инструменты не ломаются.
- **Неизвестный человек** → `status:"ok"`, `no_data:true`, `empty_reason:"unknown_person"` (честный результат, не ошибка). **Неоднозначное имя** (§53) → `person.resolution:"ambiguous"`, `no_data:true`, `empty_reason:"ambiguous"`, кандидаты — только id/ref; факты **не** сливаются и не возвращаются.
- **Альтернатива:** оставить `chat_id` параметром модели — отклонено (противоречит существующим инструментам и создаёт риск подмены чата).

**D3. Purpose → источники (U1) + lazy RAG (U6-часть).**
| purpose | Источники (reuse) | RAG |
|---|---|---|
| `identity` | `AliasResolver` (canon/aliases) + `db.get_persona_card` | нет |
| `appearance` | `graph_facts` (target_user, confirmed) — **generic-фильтр** по лексикону внешности; extraction — **A4** | нет |
| `speech_style` | bounded per-user slice (существующие message/RAG-аксессоры) + patterns `db.get_generated_dossier` → **compact style profile** | да (bounded; только для характерных сообщений) |
| `biography` | `graph_facts` (target_user, confirmed, weight DESC) + `db.get_generated_dossier` | нет |
| `relationships` | edges `db.get_persona_card.links` | нет |
| `general` | FTS/vec RAG: `search_long_term`/`vector_search`/`get_rag_context`/`get_rag_facts` | да |
- **Lazy RAG — детерминированная карта `{general, speech_style}`** (не «всегда»). Для `speech_style` RAG — только если bounded-slice не даёт минимума характерных сообщений. Тестируется spy/mock.
- **`appearance`:** выделенного хранилища нет; A6 реализует generic-фильтр и честный `no_data`/`no_storage_for_purpose`; **извлечение/классификация внешности (в т.ч. из изображений) — граница A4** (явно).
- **`speech_style`:** `_build_style_anchors` (`direct_chat_service.py:2038`) — chat-anchored к ответам **бота**, не является per-user профилем; A6 строит **компактный** профиль **на лету** из существующих данных (без нового хранилища и без нового LLM-вызова). Системная личность бота не меняется.
- **Отношения:** reuse edges `get_persona_card.links` (структурированы, `origin != bot_direct_reply`). `user_relations.get_relations_snapshot` (stage/activity) в A6 **не подключается** (потребовал бы нового DI в `bot.py`); документируется как опциональное обогащение A4+ без дублирования. Это осознанный минимализм blast radius.
- **Альтернативы:** `appearance` через эмбеддинги/storage — отклонено (новая БД/Δ DDL запрещены); использование `_build_style_anchors` как per-user профиля — отклонено (это стиль бота, не человека).

**D4. Envelope результата — 5 полей §33 как структурированное расширение A2 (U3).**
- Результат — **JSON-объект** (строка), который A2 (`_classify_output`/`_make_envelope`, `tool_loop.py:143–221`) разворачивает в `data` envelope; доступен через `ToolContext.result_for("get_user_context")`/`ctx.tool_results`.
- Поля: `facts[]` (текст + per-fact `confidence`/`weight`/`time`/`source_id`), `sources[]` (`kind`/`ref`/`origin`/`ts`), `confidence` (`available`/`label`/`value`), `time_context` (`from`/`to`/`label`), `no_data` + `empty_reason`, служебные `status`/`purpose`/`person`/`truncated`.
- **Mapping (U3):** `sources` ← `graph_facts.origin`+`tg_message_id`(ID-политика `tg:`)+`created_at`, RAG/msg-id (`msg:`), edges; `confidence` ← `graph_facts.status`+`weight`(+`last_confirmed_at`): `confirmed`+weight≥порог → `confirmed`; `confirmed`+weight<порог → `likely`; иной status → `unconfirmed`; носитель отсутствует → `available=false`, `label:"unknown"`.
- **Честность (§33 `:5132–5133`):** ни один элемент не помечается `confirmed` без подтверждения носителем; `no_data`/`empty_reason` обязательны; отсутствие данных не «заполняется» домыслами.
- **Envelope `data` — in-memory на прогон**, не сериализуется в модельный ввод сверх tool-сообщения и **не логируется/не персистится** (R17; прецедент review A2).
- **Альтернатива:** plain-строка без структуры — отклонено (A4 и §35-цепочкам нужна структура, а не распарсенные строки).

**D5. `max_items`/капы (U4) + вердикт Δ каталога (U5).**
- `max_items` = предел числа элементов `facts[]`/срезов; per-purpose дефолты (`identity=5`, `appearance=10`, `biography=10`, `relationships=10`, `general=8`, `speech_style=5`) с hard-ceiling `MEMORY_LOOKUP_MAX_ITEMS_HARD=20` (clamp).
- Доп. капы: `MEMORY_LOOKUP_MESSAGE_SLICE_MAX=5` (hard 10), `MEMORY_LOOKUP_SLICE_MAX_CHARS=240`, `MEMORY_LOOKUP_RESULT_MAX_CHARS=4000`. «Сотни сообщений» и большие цитаты невозможны by design (§34 `:5168`/`:5170–5171`).
- Инструмент — **free/local** (не в `METERED_TOOLS`); подчиняется A2 `TOOL_MAX_TOTAL_CALLS=6`/дедупу, но не расходует `TOOL_CHAIN_MAX_METERED_CALLS`.
- **Δ каталога = 0:** капы/kill-switch — env-only/код-константы (прецедент A2/A5); F8/ADR-1026-2 не переиздаётся; счётчики 470/427/445/101/99/21 без изменений.
- **Альтернатива:** каталожные лимиты — отклонено (Δ каталога ≠ 0, U5).

**D6. Комбинирование с фактчеком (§35); фактчек-набор остаётся 3 (U2).**
- Цепочка §35 исполняется **существующим** A2-механизмом: `get_user_context(purpose=general)` → сообщение/утверждение через envelope → один из **3** фактчек-инструментов (`dig_into_lore`/`compile_lore_story`/`execute_web_search`).
- **Память ≠ фактчек:** память подтверждает факт **высказывания**, фактчек — **содержание**; это документируется в `description` инструмента. Поиск похожих сообщений памятью не подменяет фактчек.
- `factcheck_tools` остаётся **3**; новый фактчек-инструмент/Markdown-URL-пайплайн — граница **A7**.
- **Альтернатива:** добавить память в `factcheck_tools` — отклонено (§35 требует комбинирования, не расширения; U2).

**D7. Порядок с A1-координатором (U6); 0 новых LLM-вызовов.**
- Lookup — **обычный tool call** внутри существующего `chat_with_tools` (reuse A1-координатора и общего механизма цепочек); **нового pre-gate не вводится**; порядок «память → фактчек» задаёт модель/цепочка A2.
- **0 новых LLM-вызовов**; 2-вызовность System 2 (`await_count==2`) не трогается; результат — через A2-envelope (`ctx.tool_results`/`result_for`).
- **Альтернатива:** отдельный pre-gate lookup — отклонено (дублирование экспертизы A1/A2, риск регресса живого чата).

**D8. R17-лог и R18; новых тегов не требуется.**
- Единственный новый лог: `[memory] lookup | purpose=%s | user_id=%s | chat_id=%s | count=%d | latency_ms=%d | empty_reason=%s`. **Никогда:** текст досье/сообщений/цитат, имена, промпты, ключи, сырые аргументы.
- `empty_reason` ∈ `{"", empty, unknown_person, ambiguous, no_storage_for_purpose, disabled, lookup_failed}` — закрывает §53 «почему инструмент не сработал».
- **R18:** теги/бэкапы/`stash` не удаляются; новых тегов A6 не создаёт (EPIC_ONLY; анкер — на границе эпика).

**D9. Границы волн и anti-duplication (U7).**
- **A4** (§22–§25) — потребитель контракта: имена/визуальный срез/image-prompt/заполнение appearance-заглушек — **не здесь**. Извлечение внешности — A4.
- **A5** (`worker_budget`/image-пути/`limits.*`) — **не в diff**. **A7** (§36–§48: URL+фактчек, безопасность, Decision Making/реакции) — **не в diff**. **§104 `generate_image`** — не трогать. **A9** — новых событий A6 не создаёт (ExecutionGraph REUSE).
- **Anti-duplication:** не дублировать `build_persona_card`/`format_dossier_block`/RAG/AliasResolver; второго резолвера/второго RAG-контура/второй аналитики — нет. `get_user_context` вводится **впервые** (EV-21), без дублирования агрегации досье.
- **A0 HY-01…HY-06** — image-специфичны → **NOT_APPLICABLE** как требования A6; EV-21/`#duplicates`/§8.2–8.3 — применимы как анти-дубликат/структурные ориентиры.
- **Промпты:** системные/воркерные промпты не меняются → **ADR-1013-3 NOT_APPLICABLE** (кроме атомарного `description` новой схемы инструмента в `tool_schemas.py`, что не является частью prompt-канона, прецедент A2).

**D10. Release policy = EPIC_ONLY (deferred); hot/cold-откат.**
- A6 отдельно **не деплоится**; вклад в **pending epic-release Эпика 3** (агрегатный манифест/order/gate/rollback — на границе эпика); `APP_VERSION` остаётся **2.58.30** (bump — в агрегате); **@DevOps на пер-фича деплой не вызывается**; пер-фича тег не создаётся.
- **Hot-OFF:** env-only `MEMORY_LOOKUP_ENABLED=OFF` → инструмент исчезает из `active_tools`, остальные 11 — байт-в-байт. **Cold:** `git revert` к **`e8646af`**. **DDL-откат не требуется** (Δ DDL=0).
- **Release-order:** A6 до **A4** (A4 потребляет контракт); совместим с A1/A2/A3/A5 (reuse, без изменения их контрактов).

**D11. Risk-Level: R2.**
- Read-only LLM-инструмент; нет DDL/каталога/денег/записи в БД/секретов/деструктивных операций; blast radius ограничен контрактом результата, R17-логом и расширением канона; OFF-путь байт-в-байт для остальных 11. В отличие от A2 (менял разделяемый `tool_loop` control-flow → R3) и A5 (DDL/деньги → R3), A6 **не меняет управляющий поток** и полностью аддитивен/обратим.
- **Что повысит до R3 (Reviewer-триггеры):** запись/DDL/каталог; изменение общего control-flow `tool_loop`/A2-envelope; логирование/персистенция envelope `data` (текстов досье); попадание в shared метеринг-бюджет; регресс первых 11; отсутствие байт-в-байт OFF-паритета; утечка приватного текста за пределы модельно-видимого tool-канала.
- **Соразмерная проверка:** adversarial-тесты (§8 spec), R17-тест, lazy-RAG spy, OFF-паритет, diff-аудит границ. Отдельный threat-failure-файл (R3-атрибут) не обязателен.

## Санкция расширения канона (verbatim, D1)

> **Санкционировано Шагом 2 @Architect (ADR-1026-18 D1).** Без этой санкции канон остаётся **11**, фича в Build не идёт. Санкция **ADR-1026-13 D3 исчерпана A2** (10→11) и повторно **не** используется; основание — прецедент **ADR-1026-15 D5**.

- **Канон:** `services/tool_schemas.py::TOOL_CALLING_TOOLS` — **11 → 12**; 12-й (в хвост) — `get_user_context`; первые 11 — **байт-в-байт**.
- **Атомарные части (все обязательны в одном изменении):** (1) JSON-схема `TOOL_GET_USER_CONTEXT`; (2) регистрация в `TOOL_CALLING_TOOLS` хвостом; (3) `_memory_lookup_enabled()` + env-only `MEMORY_LOOKUP_ENABLED` (ClassVar, default ON) в `active_tools`; (4) запись `"get_user_context"` в диспетчер `tool_router.py:497–523` + метод `_get_user_context`; (5) ре-пин тестов `len==12` и существующих канон-тестов; (6) `MEMORY_LOOKUP_TOOL_NAME`.
- **Δ DDL = 0** (SQLite остаётся **v12**; новых таблиц/колонок/индексов/PG нет). **Δ каталога = 0** (env-only/код-константы; счётчики 470/427/445/101/99/21 без изменений).
- **Обратный путь:** `MEMORY_LOOKUP_ENABLED=OFF` → инструмент не объявлен (эффективно 11); cold — `git revert` к `e8646af`; канон-откат промптов не требуется (промпты не меняются).

## AMEND / REUSE-карта (Dn → задачи)

| ADR | Статус в A6 | Суть |
|---|---|---|
| ADR-1026-15 (A2) | **REUSE (ключевой)** | envelope `ToolLoopResult.tool_results`/`ToolContext.result_for`; §17-лимиты/дедуп; **прецедент атомарного расширения канона D5** |
| ADR-1026-14 (A1) | **REUSE** | 2-вызовность System 2; общий механизм цепочек; env-only kill-switch-прецедент |
| ADR-1026-13 (A0) | **REUSE (только durable-аудит/ориентиры)** | EV-21/`#duplicates`/§8.2–8.3; **санкция D3 ИСХЕРПАНА A2 — НЕ переиспользуется** |
| ADR-1020-4 | **AMEND (канон-хвост)** | «новое — в хвост»; канон расширен 11→12 без изменения первых 11 |
| ADR-1013-3 | **NOT_APPLICABLE** | Системные/воркерные промпты не меняются; новое — только `description` схемы (атомарно) |
| ADR-1020-1 | **REUSE** | ID-политика `tg:`/`msg:` для источников |
| ADR-1026-16/-17 | **REUSE (паттерн)** | Аддитивность/env-only; **DDL/каталог A6 НЕ использует** |
| ADR-1023-5 / §104 | **REUSE (граница)** | `generate_image` не трогать |

| Решение | Задачи (tasks.md) |
|---|---|
| D1 (канон 11→12 + kill-switch) | T-3611, T-3612, T-3619, T-3620 |
| D2 (контракт/адаптация/невалидные аргументы) | T-3611, T-3612, T-3619 |
| D3 (purpose→источники + lazy RAG) | T-3613, T-3614, T-3615, T-3616 |
| D4 (envelope 5 полей/честность) | T-3617, T-3618, T-3619 |
| D5 (`max_items`/капы, Δ каталога=0) | T-3616, T-3618, T-3620 |
| D6 (§35-комбинирование, фактчек=3) | T-3619, T-3621 |
| D7 (порядок с A1, 0 новых LLM) | T-3612, T-3613 |
| D8 (R17-лог/R18) | T-3612, T-3619, T-3620 |
| D9 (границы/anti-duplication) | T-3621 |
| D10 (deploy EPIC_ONLY/rollback) | T-3623, T-3624 |
| D11 (risk R2) | T-3619, T-3622 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Канон | не расширять; использовать A0 D3; новая санкция | **новая санкция 11→12 (ADR-1026-18 D1)** | A0 D3 исчерпана A2; §32/§33 требуют LLM-инициативу |
| Kill-switch | каталожный; env-only | **env-only `MEMORY_LOOKUP_ENABLED`** | Δ каталога=0; прецедент A2/A5 |
| `chat_id` | параметр модели; из `ToolContext` | **из `ToolContext`** | Адаптация к существующим инструментам; риск подмены чата |
| `appearance` | storage/эмбеддинги; keyword-инференс как факты; фильтр + honest no_data | **фильтр + honest no_data (extraction=A4)** | Нет хранилища; не выдавать инференс за факт; граница A4 |
| `speech_style` | bot-anchored `_build_style_anchors`; on-the-fly per-user профиль | **on-the-fly compact profile** | `_build_style_anchors` — про бота; новый storage запрещён |
| Lazy RAG | всегда; никогда; карта purpose | **карта `{general, speech_style}`** | §34 «не всегда»; тестируемо |
| `max_items` | общий; только факты; per-purpose+ceiling | **per-purpose + ceiling + slice/char caps** | Предсказуемость; «не сотни сообщений» |
| Фактчек-набор | расширить; оставить 3 | **оставить 3** | §35 — комбинирование, не новые инструменты; A7-граница |
| Envelope | plain-строка; структурированный | **структурированный JSON (5 полей §33)** | Нужен A4/§35-цепочкам |
| Deploy | ДА/bump; EPIC_ONLY | **EPIC_ONLY (deferred)** | Изменяет общий канон/меню инструментов; пер-фича деплоя нет |
| Риск | R2; R3 | **R2** | Read-only, без DDL/каталога/денег, обратимо |

## Последствия

- LLM получает **on-demand** инструмент `get_user_context`: может запросить сведения о конкретном человеке, не раздувая каждый запрос полными досье (закрывает §53 «бот не умеет получить нужные сведения из досье»).
- Канон инструментов — **12** (`get_user_context` в хвосте); `active_tools` default (image OFF) = 11; при `MEMORY_LOOKUP_ENABLED=OFF` — 11, остальные без изменений.
- Результат структурирован по 5 полям §33 и проходит через A2-envelope, доступный A4 и §35-цепочкам; неподтверждённое честно помечается, отсутствие данных — явный флаг; источники — идентификаторы, не сырьё.
- Lazy RAG: подтверждающие сообщения ищутся только для `general`/`speech_style`; капы исключают «сотни сообщений» и крупные цитаты.
- Память и фактчек разведены: память подтверждает высказывание, фактчек — содержание; `factcheck_tools`=3.
- **Δ DDL = 0, Δ каталога = 0;** новых LLM-вызовов нет; 2-вызовность сохранена; A4/A5/A7/§104 не затронуты.
- Риск **R2**; hot-откат `MEMORY_LOOKUP_ENABLED=OFF`; cold — `git revert` к `e8646af`; DDL-откат не нужен; deploy `DEFERRED_TO_EPIC`.

## Ссылки

- `plans/features/memory-lookup-api-round1026/{spec.md, tasks.md}` (spec — Step 2 T-3609; сверка — @PM T-3610).
- Durable-аудит: `plans/docs/agentic-audit-round1026.md` (EV-21; `#duplicates`, `#epic3-reuse`, `#epic3-summary`).
- ТЗ: `plans/current_task.md` §32 (`:5066–5092`), §33 (`:5095–5133`), §34 (`:5136–5177`), §35 (`:5180–5214`), §52 (`:5775`/`:5777`/`:5781`), §53 (`:5818–5850`), §54 (`:5882`), §104 (`:3180–3203`).
- A2 (вход): `plans/ARCHITECTURE.md` §84; `plans/archive/tool-chains-round1026/adr-1026-15-tool-chain-contract-and-limits.md` (D5-прецедент канона).
- A1 (вход): `plans/ARCHITECTURE.md` §83; `plans/archive/tool-coordinator-round1026/adr-1026-14-coordinator-scope-in-synthesizer.md`.
- A0 (вход): `plans/archive/agentic-audit-round1026/adr-1026-13-agentic-audit-artifact-and-evidence-discipline.md` (D3 — исчерпана A2).
- A3/A5 (вход): `plans/archive/unified-image-request-round1026/adr-1026-16-*.md`; `plans/archive/image-daily-limit-round1026/adr-1026-17-*.md`.
- Код (baseline `e8646af` + незакоммиченный A2/A3/A5): `services/tool_schemas.py:427–439,460–494`; `services/tool_router.py:419–470,497–523,616+`; `services/tool_loop.py:42–58,143–221`; `services/direct_chat_service.py:2038,2303`; `services/database.py:345–368,4624`; `services/dossier_prompts.py:568`; `services/summary_memory.py:1826,2479,2524`; `services/summary_aliases.py:15–75`; `services/user_relations.py:338`; `config/settings.py` (env-only ClassVar-прецеденты).
- Точка отката: коммит **`e8646af`** (пер-фича тег не создаётся — `EPIC_ONLY`).
