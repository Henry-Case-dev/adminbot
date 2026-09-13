# ADR-1014-2 — Anti-Echo Self-Marking: новый origin `bot_self_reply` (DDL РАЗРЕШЁН) + LLM-экстрактор

- **Статус:** ACCEPTED (Step 2 @Architect, **итерация 2**, 13.09.2026). **Отменяет редакцию 1 (`status='self_reply'`, rule-based).**
- **Раунд:** 10.14, фича **F1** `anti-echo-self-reply-round1014` (T-1477).
- **Контекст:** `plans/current_task.md` §1 + **UPD п.1,3** (owner: «В SQLite сними заморозку с таблицы фактов: добавь честный, новый origin … Делай базу логичной»; «Экстрактор сути — Только LLM … третье отдельное подключение»); `services/database.py:53,67-101,230-246,475-905,1588-1649,2388-2415,2359-2385,3560-3598`; `services/summary_memory.py:211-222,286-305,755-811,2184-2306,2431-2475`; `services/dream_worker.py:132-136`; `services/llm_client.py:891-954`.
- **Снимает инвариант:** «SQLite остаётся v8 / origin CHECK заморожен» (**снят владельцем**, UPD п.1).
- **Связано:** ADR-1014-1 (PG Persona), ADR-1013-1 (роль-роутер воркеров).

## 1. Контекст

Редакция 1 маркировала self через `status='self_reply'` (обход CHECK origin) и rule-based экстрактор. Владелец отклонил оба: «добавь честный, новый origin для сообщений бота, а не переиспользуй self_reply»; «Вырезание сути регулярками убьет контекст». DDL/миграции разрешены.

Факты: `graph_facts.origin` CHECK на 10 значений (`database.py:67-71`); текущая SQLite-схема **v8** (`_SCHEMA_VERSION_AGI_MEMORY = 8`, `database.py:53`). `origin='bot_direct_reply'` — прямые ответы, вес 0.7, важность 3, входит в RAG и частично в Сон.

## 2. Решение

### D1. Маркер self = `graph_facts.origin = 'bot_self_reply'` (11-й origin)

- `status` остаётся `'confirmed'` (`status='self_reply'` **НЕ вводится** — прямое требование владельца).
- `kind='fact'`, `target_user=NULL`, `importance=2` (база в `_IMPORTANCE_BASE`), `weight` — из ключа (§D3).
- Единый список origin расширяется в ОДНОМ месте — `_GRAPH_FACT_ORIGINS_SQL` (`database.py:67-71`) на 11 значений.

### D2. SQLite-миграция v8 → v9 (`_migrate_self_origin_v9`), bump `_SCHEMA_VERSION_AGI_MEMORY 8→9`

- **Версии:** `_SCHEMA_VERSION_AGI_MEMORY = 9` (текущая цель, требование владельца); историческая v8-версия фиксируется отдельно (`_SCHEMA_VERSION_AGI_MEMORY_V8 = 8`, используется `_migrate_agi_memory_v8`), новый метод `_migrate_self_origin_v9` ставит `PRAGMA user_version = _SCHEMA_VERSION_AGI_MEMORY` (9).
- **Причина:** SQLite не умеет `ALTER ... CHECK` → rebuild таблицы (прецеденты `_migrate_video_origins_v4`/`_migrate_user_memory_v5`/`_migrate_agi_memory_v8`).
- **Guard (идемпотентность):** `SELECT sql FROM sqlite_master WHERE name='graph_facts'`; rebuild только если `'bot_self_reply' not in sql`. Повторный запуск — no-op. **`PRAGMA user_version = 9` ставится ВСЕГДА** (вне guard) — на новой БД CHECK уже может нести значение (v5/v8 интерполируют обновлённый `_GRAPH_FACT_ORIGINS_SQL`), тогда rebuild пропускается, но версия фиксируется.
- **Rebuild:** `ALTER TABLE graph_facts RENAME TO graph_facts_v9_legacy` → `CREATE TABLE graph_facts (...) CHECK (origin IN <11 значений>)` → `INSERT INTO graph_facts (...) SELECT <все 16 колонок> FROM graph_facts_v9_legacy` → `DROP TABLE graph_facts_v9_legacy` → пересоздать индексы.
- **Копируются ВСЕ 16 колонок** v8: `id, chat_id, fact, origin, expires_at, created_at, target_user, weight, status, last_confirmed_at, supersedes, message_timestamp, importance, source_ids, kind, belief_meta` (важно: не потерять `importance`/`kind`/`source_ids`/`belief_meta`).
- **Индексы** пересоздаются ровно как в v8: `idx_graph_facts_chat_origin`, `idx_graph_facts_target_user`, `idx_graph_facts_history_import` (partial UNIQUE), `idx_graph_facts_chat_kind`, `idx_graph_facts_beliefs` (partial).
- **FTS/vec:** `graph_facts_fts` (external content, `content='graph_facts'`) и `graph_facts_vec` (`rowid=fact_id`) **НЕ пересоздаются** — `id` сохраняются 1:1 (прецедент D201). После миграции — проверочный `INSERT INTO graph_facts_fts(graph_facts_fts) VALUES('rebuild')` без необходимости (content-таблица резолвится динамически); тест сверяет FTS-хиты по id.
- **Порядок:** `initialize()` (`database.py:394-401`) добавляет вызов `await self._migrate_self_origin_v9()` после `_migrate_agi_memory_v8()`.
- **Обратимость (откат):** перед откатом к v8 — `UPDATE graph_facts SET origin='bot_direct_reply' WHERE origin='bot_self_reply'` (иначе старый CHECK отклонит строки); затем `git revert` (миграция повторно не срабатывает). Данные не теряются: пересоздание `origin`/статус консервативно.
- **Новая БД:** сначала `_SCHEMA_SQL` (v7-база) → v5 → v8 → v9; guard'ы корректно отработают (см. §5 тест «from scratch»).

### D3. Вес = каталог-ключ `limits.graph_fact_weight_bot` (дефолт 0.2) + важность 2

- `summary_memory._origin_weight` (`:211-222`): новая ветка `if source_type == 'bot_self_reply': return _clamp_weight(hot.get('limits.graph_fact_weight_bot', settings.GRAPH_FACT_WEIGHT_BOT))`.
- `database._IMPORTANCE_BASE['bot_self_reply'] = 2` (ниже пользовательского `bot_direct_reply=3`).
- Пользовательский `GRAPH_FACT_WEIGHT_DIRECT = 0.7` не меняется.
- Новый ключ — санкционированный Δ каталога (см. spec F1 §5).

### D4. Экстрактор сути — **только LLM** (роль `reflection`)

- Новый модуль `services/self_reflection.py`:
  - `SELF_REFLECTION_PROMPT` (код-константа, не PG-канон — по ADR-1013-3);
  - `async extract_self_essence(llm, answer, *, chat_id=None) -> str` — `llm.generate_worker('reflection', [...], chat_id=chat_id)`; **fail-open**: `ValueError` (роль ещё не зарегистрирована — F8 не влит) / `LLMError` / пустой/кривой ответ → `llm.generate(...)` (основная модель); если и это упало → `''`;
  - нормализация результата: `strip`, удаление переносов, cap `settings.SELF_ESSENCE_MAX_CHARS` (300); ожидаемый формат `[Бот] <решил|посоветовал|заявил>: <суть>`;
  - `record_extractor_status(status, error=None)` — пишет `persona_state` (см. D9) best-effort.
- **Вызов:** `direct_chat_service._memorize_direct_reply` (`:959-990`), после успешной отправки (fire-and-forget как сейчас); при флаге ON.
- **Fail-safe:** пусто/ошибка → self-факт НЕ пишется (ответ юзеру не рушится).
- **Стоимость:** один доп. LLM-вызов на ответ бота — осознанно (владелец: «Только LLM»).

### D5. Анти-эхо-инструкция — динамический блок

- `_SELF_ECHO_INSTRUCTION = "Ниже — твои ПРОШЛЫЕ слова. Относись к ним критически: ты мог шутить, отыгрывать роль или ошибаться."` (`summary_memory.py`, рядом с `_ORIGIN_LABELS`).
- В `direct_chat_service._build_rag_block` (`:1690-1771`): если среди `kept` есть `item[0] == 'bot_self_reply'` → строка добавляется в начало `<RAG_Memory>` (после открывающего тега). Канон `prompts.direct_chat_system_prompt` не трогается → PREV/`PROMPT_MIGRATIONS` НЕ нужны.

### D6. Исключение self из Сна / «золотых» / decay / компакции / счётчиков — **по origin**

При новом origin «бесплатный карантин через status» недоступен → добавляются точечные фильтры `origin != 'bot_self_reply'`:
1. **Сон:** `bot_self_reply` **не входит** в `_DREAM_SOURCE_ORIGINS` (`dream_worker.py:132-136`) → `get_dream_candidate_chats`/`get_dream_candidates` (фильтр `origin IN origins`) его не видят. Дополнительно `database.list_new_confirmed_facts` (`:1971-1984`, подкрепление belief — фильтрует только `kind/status`) → `AND origin != 'bot_self_reply'`.
2. **«Золотые» (ностальгия):** `search_golden_facts_fts` (`:2359-2385`, уже режет `bot_direct_reply`) → `AND f.origin != 'bot_self_reply'`.
3. **Decay/компакция:** `get_live_graph_facts` (`:3315`), `find_exact_dup_groups` (`:3332`), `purge_unconfirmed_graph_facts` не касается confirmed; кампакт-пересмотр → исключить self, чтобы редко-авторитетные собственные слова не «подтверждались» слиянием.
4. **Счётчики:** `graph_stats.facts` (`:3579-3581`) → `AND origin != 'bot_self_reply'`; добавить отдельный ключ `bot_self_replies` (мониторинг).
5. **RAG:** self по умолчанию невидим; включается явным `include_self=True` (см. D7).
6. **Style anchors:** `_build_style_anchors` читает `bot_replies` (отправленные ответы), а не `graph_facts` — правок не требует.

### D7. RAG: `include_self` (5-й элемент кортежа НЕ нужен)

- Т.к. источник различается по `origin`, метка строится без status: `_ORIGIN_LABELS['bot_self_reply'] = 'Источник: Я сам (Бот)'` → строка `[Источник: Я сам (Бот)] <дата> <текст>`. RAG-кортежи остаются 4-элементными `(origin, fact, rag_ts, author)` — регресс-риск редакции 1 (5-й элемент) снят.
- `database.search_graph_facts_fts` (`:2388-2415`): новый параметр `include_self=False`; `if not include_self: sql += "AND f.origin != 'bot_self_reply' "`.
- `summary_memory._vec_candidates` (`:2474`): `and (include_self or row["origin"] != "bot_self_reply")`.
- `_search_graph_facts`/`_knn_graph_facts`/`get_rag_facts`/`_vec_candidates` — прокинуть `include_self`.
- Direct-путь `_build_rag_block` вызывает `get_rag_facts(..., include_direct_reply=True, include_self=True)`.

### D8. Флаги — **ON по умолчанию** (требование владельца, UPD п.2)

- `flags.bot_self_awareness_enabled` (bool, группа `flags_memory`, дефолт **True**), `settings.BOT_SELF_AWARENESS_ENABLED = _env_bool(..., True)`.
- OFF → `_memorize_direct_reply` байт-в-байт прежний (без разделения query/answer, без экстрактора), RAG без self/инструкции. Progressive delivery сохранён как рубильник, но по умолчанию ON.

### D9. Метрики воркера экстрактора — `persona_state` (singleton, PG; F1 владеет DDL)

```sql
CREATE TABLE IF NOT EXISTS persona_state (
    id                  BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),
    last_extract_at     TIMESTAMPTZ,
    last_extract_status TEXT NOT NULL DEFAULT 'never',  -- ok|empty|error|skipped
    last_error          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
F2 добавляет колонки/сид для трейтов (`last_trait_at`, `last_trait_status`) — см. ADR-1014-1 §2.5/spec F2. F4 читает сводку через `bot_persona.get_persona_health`.

## 3. Рассмотренные альтернативы

| Альтернатива | Отклонена потому что |
|---|---|
| `status='self_reply'` (редакция 1) | **Отклонена владельцем** (UPD п.1): «не переиспользуй self_reply; делай базу логичной». |
| Rule-based экстрактор (редакция 1) | **Отклонён владельцем** (UPD п.3): регулярки убивают контекст. |
| `belief_meta={"self":true}` | хрупкий JSON-LIKE (S10.13-11/13); нет карантина. |
| Оставить CHECK на 10 origin | запрещено владельцем; невозможно честно отделить self. |
| Хранить self в отдельной таблице | дублирование RAG-путей; origin — штатный механизм. |
| LLM-экстрактор без dedicated-роли | владелец требует третье подключение (F8); реализуем роль `reflection` + фоллбэк на основную модель. |

## 4. Последствия

**Плюсы:** честная схема (11 origin), self отделён на уровне данных; RAG-кортеж 4-элементный (меньше регрессов); метка/инструкция без PG-канона; метрики экстрактора; обратимая миграция.

**Минусы/издержки:** миграция rebuild (риск потери колонок — закрыт копированием всех 16 + тестом); нужны точечные origin-фильтры в 5–7 SQL-местах (закрыто тестами); один доп. LLM-вызов на ответ бота; Scanner проверяет миграцию.

## 5. Верификация

См. spec F1 §7 (тест-план) и §9 (DoD). Ключевые маркеры: миграция v8→v9 дважды (идемпотентно) + «from scratch» + сохранность всех 16 колонок и FTS/vec; self не виден Сну/золотым/компакции/`graph_stats.facts`; self виден только direct-RAG с меткой `[Источник: Я сам (Бот)]` и анти-эхо; `origin=bot_self_reply`, `status='confirmed'`; флаг OFF = байт-в-байт; экстрактор LLM + фоллбэк; `persona_state` обновляется.
