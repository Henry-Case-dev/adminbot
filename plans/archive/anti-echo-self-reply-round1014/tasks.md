# Фича F1 — `anti-echo-self-reply-round1014` (Механика самосознания: Anti-Echo & Self-Reflection)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). `spec.md` + `adr-1014-2` реализованы: код + миграция v9 + тесты; полный `pytest` 5428 passed/0 failed.
> **Раунд:** 10.14. **Нумерация:** T-1477…T-1486 (продолжает T-1476).
> **Тип:** backend (+ PG-DDL). **Приоритет:** P0 (фундамент эпика).
> **Зависимости:** нет (F8-роль `reflection` опциональна — фоллбэк на основную модель).
> **ТЗ:** `plans/current_task.md` §1 + **UPD п.1,3**. **Эпик:** Self-Awareness / Persona round1014.
> **Baseline:** HEAD `2edc65b`, pytest 5392/0, SQLite v8, каталог 427/90/399/403. **Локальный Δ F1:** REGISTRY 429 / GROUPS 90 / Settings 401 / categorized 405 / mapped 88 / TAB_RULES 19.

## 0. Цель

Собственные ответы бота получают честный новый `origin='bot_self_reply'` (SQLite v9), пониженный вес (0.2), проходят
LLM-экстрактор сути и не участвуют в Сне/«золотых»/компакции; при подаче своих прошлых слов в контекст добавляется
анти-эхо-инструкция. **DDL разрешён владельцем** (UPD п.1).

## 1. Требования (ТЗ §1 + UPD)

- [x] **Маркировка:** новый origin для сообщений бота (self), **не** переиспользовать `status='self_reply'`.
- [x] **Понижение авторитета:** вес self 0.2 против пользовательских 0.7.
- [x] **Экстракт:** суть через **LLM** (регулярки отклонены); формат `[Бот] решил/посоветовал/заявил: …`.
- [x] **Анти-эхо промпт** при подаче собственных прошлых слов.
- [x] **SQLite:** расширить CHECK origin (10→11) через rebuild + bump v8→v9, безопасно и обратимо.
- [x] **Метрики:** статус работы экстрактора (`persona_state`).

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- `services/database.py` — CHECK origin `:67-71`, `_IMPORTANCE_BASE` `:78-88`, `initialize` `:383-401`, миграции
  `:594-905`, `insert_graph_fact` `:1588`, `search_graph_facts_fts` `:2388`, `list_new_confirmed_facts` `:1971`,
  `search_golden_facts_fts` `:2359`, `get_live_graph_facts` `:3315`, `find_exact_dup_groups` `:3332`,
  `graph_stats` `:3560`.
- `services/summary_memory.py` — `_origin_weight` `:211`, `_ORIGIN_LABELS` `:294`, `_search_graph_facts`
  `:2184`, `_knn_graph_facts` `:2235`, `get_rag_facts` `:2087`, `_vec_candidates` `:2431`, `_format_origin_labeled_line`
  `:755`.
- `services/self_reflection.py` — **новый**: `SELF_REFLECTION_PROMPT`, `extract_self_essence`, `record_extractor_status`.
- `services/direct_chat_service.py` — `_memorize_direct_reply` `:959-990`, `_build_rag_block` `:1690-1771`.
- `services/pg_db.py` — `DDL_STATEMENTS` (+`persona_state` + сид).
- `services/llm_client.py` — роль `reflection` (регистрирует F8; F1 только потребляет с фоллбэком).
- `config/settings.py` `:797-798`; `services/param_catalog.py` `_LIMITS`/`_FLAGS`; `.env.example`.
- Тесты: `tests/test_self_reflection.py`, `tests/test_graph_facts_origin_v9.py`, `tests/test_summary_memory*`,
  `tests/test_dream*`, `tests/test_direct_chat*`, `tests/test_param_catalog.py`.

## 3. Инварианты (обновлено: DDL РАЗРЕШЁН)

- ✅ **PG-DDL разрешён** (UPD п.1). Новые DDL — только идемпотентные (`IF NOT EXISTS`), безопасные, с тестом.
- ✅ **SQLite миграция разрешена**: bump v8→v9 ТОЛЬКО через rebuild с сохранением всех 16 колонок + индексов;
  FTS/vec не пересоздаются (id 1:1); повторный запуск — no-op; обратный путь документирован.
- ⛔ **Порядок роутеров `bot.py` не трогать** (искл.: DI-kwargs новых hot-значений).
- ⛔ **`media/` и `.env` не трогать**; `.env.example` — только плейсхолдеры.
- **R17:** секреты — `{configured,last4}`; не логировать. **R16:** id — ключ, не имя.
- **Каталог:** новые ключи — только санкционированный Δ + пин-тесты (общий Δ раунда: REGISTRY 435 / Settings 406 /
  categorized 411 / GROUPS 90 / mapped 88 / TAB_RULES 19).
- **Промпты:** `SELF_REFLECTION_PROMPT` — код-константа вне PG-канона (ADR-1013-3); канон direct не менять.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, пин-тесты каталога, R17-скан,
  русские conventional commits, атомарно (код + миграция + тесты + эталон).

## 4. Зависимости

- **Вверх:** нет (F8 улучшает: dedicated-роль `reflection`; без неё — фоллбэк на основную модель).
- **Вниз:** F2 (читает `persona_state` для метрик), F3/F4/F6 (метки self), F8 (регистрирует роль).

## 5. Definition of Done

- [x] Origin `bot_self_reply` — 11-й в CHECK; миграция v8→v9 идемпотентна и не теряет данные (тесты).
- [x] Self-факты: вес 0.2, важность 2, `status='confirmed'`, `target_user NULL`.
- [x] Экстрактор — LLM (`reflection` → фоллбэк на основную); fail-safe; cap 300.
- [x] Self исключён из Сна/«золотых»/компакции/`graph_stats.facts`; в direct-RAG — тег и анти-эхо.
- [x] `persona_state` обновляется; PG-DDL идемпотентен.
- [x] Полный `pytest` **0 failed** (5428 passed; база 5392); `node --check` clean; `git diff --check` чист; Δ каталога сверен (429/401/405).

## 6. Чек-лист задач

- [x] **T-1477 (@Architect, гейт):** spec/ADR редакции 2: origin `bot_self_reply` + v9-миграция, LLM-экстрактор,
  вес/важность, origin-исключения, `persona_state`, флаг ON, Δ каталога, обратимость.
- [x] **T-1478 (@Builder):** расширить `_GRAPH_FACT_ORIGINS_SQL`; `_IMPORTANCE_BASE`; `_SCHEMA_VERSION_AGI_MEMORY=9`
  (+`_SCHEMA_VERSION_AGI_MEMORY_V8=8`); новый `_migrate_self_origin_v9()` (rebuild всех 16 колонок + индексы) +
  вызов в `initialize()`.
- [x] **T-1479 (@Builder):** каталог/настройки: `GRAPH_FACT_WEIGHT_BOT` (+запись в `_LIMITS`, группа `limits_graph`),
  `BOT_SELF_AWARENESS_ENABLED` (+`_FLAGS`, `flags_memory`, default True), `SELF_ESSENCE_MAX_CHARS`; `.env.example`;
  пин-тесты каталога.
- [x] **T-1480 (@Builder):** `services/self_reflection.py` (prompt, `extract_self_essence` с фоллбэком, cap,
  `record_extractor_status`); `DDL_STATEMENTS` + `persona_state` singleton-сид.
- [x] **T-1481 (@Builder):** `summary_memory._origin_weight` — ветка `bot_self_reply`; `_ORIGIN_LABELS`;
  `include_self` plumbing (`search_graph_facts_fts`/`_vec_candidates`/`_search_graph_facts`/`_knn_graph_facts`/`get_rag_facts`).
- [x] **T-1482 (@Builder):** `_memorize_direct_reply`: split query/answer + вызов экстрактора + запись self
  (`memorize_self_reply`), флаг OFF → байт-в-байт прежний; `_build_rag_block`: `include_self=True` + анти-эхо.
- [x] **T-1483 (@Builder):** origin-исключения self: `list_new_confirmed_facts`, `search_golden_facts_fts`,
  `get_live_graph_facts`, `find_exact_dup_groups`, `graph_stats.facts` (+`bot_self_replies`).
- [x] **T-1484 (@Builder):** тесты миграции v9 (идемпотентность/данные/from scratch/FTS/vec), экстрактора, RAG-метки/анти-эхо,
  исключений Сна/золотых, Δ каталога, `persona_state`.
- [x] **T-1485 (@Builder):** `node --check web/app.js`, полный `pytest` (0 failed, дельта), `git diff --check`;
  независимый пересчёт инвариантов каталога.
- [ ] **T-1486 (@PM/@Reviewer, гейт):** сверка DoD/инвариантов, проверка миграции и обратимости, R17-скан;
  передача канона self-метки в F2/F3/F4/F6.

## 7. Открытые вопросы (закрыты владельцем)

- **F1-Q1:** маркер self → **origin** (UPD п.1). **F1-Q3:** экстрактор → **LLM** (UPD п.3).
- **F1-Q2:** вес → ключ `limits.graph_fact_weight_bot` 0.2. **F1-Q4:** Сон — origin-исключение.
- **F1-Q5:** анти-эхо — динамический блок (не канон).

## 8. Feature flag / progressive delivery

- `flags.bot_self_awareness_enabled` **default True** (UPD п.2). OFF → прежнее поведение байт-в-байт.
- Rollback = `git revert` + обратный `UPDATE graph_facts SET origin='bot_direct_reply'` при необходимости отката схемы.
