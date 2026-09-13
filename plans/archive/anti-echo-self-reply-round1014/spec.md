# Spec F1 — `anti-echo-self-reply-round1014` (Механика Самосознания: Anti-Echo & Self-Reflection)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, **итерация 2**, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1477…T-1486. **ТЗ:** `plans/current_task.md` §1 + **UPD п.1,3**.
> **Зависимости:** нет (базовая). **Вниз:** F2/F3/F4/F6, F8. **Baseline:** HEAD `2edc65b`, pytest 5392/0, **SQLite v8**, каталог 427/90/399/403.
> **ADR:** `adr-1014-2-anti-echo-self.md` (origin `bot_self_reply`, v9-миграция, LLM-экстрактор, `persona_state`).
> **Ревизия:** отменяет редакцию 1 (`status='self_reply'` + rule-based) по UPD владельца.

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **F1-Q1** маркер self | **`graph_facts.origin = 'bot_self_reply'`** (11-й origin; CHECK расширяется), `status='confirmed'`. **`status='self_reply'` НЕ вводится.** Идентификация — по origin (честная схема; UPD п.1). |
| **F1-Q2** вес/важность | `limits.graph_fact_weight_bot` (float, `limits_graph`, дефолт **0.2**; `settings.GRAPH_FACT_WEIGHT_BOT`), важность **2**. |
| **F1-Q3** экстрактор | **только LLM** через `LLMClient.generate_worker('reflection')` (F8); фоллбэк на основную модель; fail-safe (пусто → не пишем). UPD п.3. |
| **F1-Q4** Сон/золотые/decay | self исключается **по origin**: не в `_DREAM_SOURCE_ORIGINS`; фильтры `origin != 'bot_self_reply'` в `list_new_confirmed_facts`, `search_golden_facts_fts`, `get_live_graph_facts`, `find_exact_dup_groups`, `graph_stats.facts`. |
| **F1-Q5** анти-эхо | Динамическая `_SELF_ECHO_INSTRUCTION` в `<RAG_Memory>` только при наличии self. Канон не трогаем. |
| **F1-Q6** SQLite | **v8 → v9** (`_SCHEMA_VERSION_AGI_MEMORY = 9`) + идемпотентный rebuild `graph_facts` (все 16 колонок, индексы, FTS/vec сохранны). Обратимо (см. ADR §D2). |
| **F1-Q7** метрики | Таблица `persona_state` (singleton) — `last_extract_at/status/error` для F4. |
| **Нижние метки** | Новый RAG-кортеж **не нужен** (origin-based label); `_ORIGIN_LABELS['bot_self_reply']='Источник: Я сам (Бот)'`. |
| **Feature flag** | `flags.bot_self_awareness_enabled` (bool, `flags_memory`, дефолт **True** — UPD п.2). |

---

## §1. Цель и scope

Бот не строит «эхо-камеру галлюцинаций»: собственные ответы получают **отдельный origin**, заниженный вес, проходят **LLM-экстрактор сути**; при подаче своих прошлых слов добавляется анти-эхо-инструкция; Сон/«золотые»/компакция self не видят.

**In scope:** origin `bot_self_reply` + SQLite v9-миграция; вес `limits.graph_fact_weight_bot`; LLM-экстрактор (роль `reflection` + фоллбэк); `memorize_self_reply`; разделение query/answer; RAG-метка и opt-in `include_self`; анти-эхо; origin-исключения; `persona_state`; флаг.

**Out of scope:** rule-based экстрактор (отклонён); изменение `_DREAM_SOURCE_ORIGINS` как списка; PG-схема self; F2-Persona; UI (F3/F4); провайдер-блок (F8).

---

## §2. Схема данных

### 2.1. SQLite: новый origin + миграция v9

- `_GRAPH_FACT_ORIGINS_SQL` (`database.py:67-71`): 10 → **11** значений (+ `'bot_self_reply'`).
- `_IMPORTANCE_BASE['bot_self_reply'] = 2` (`database.py:78-88`).
- **Версии:** `_SCHEMA_VERSION_AGI_MEMORY = 9` (текущая цель); историческая v8 — `_SCHEMA_VERSION_AGI_MEMORY_V8 = 8` (для `_migrate_agi_memory_v8`); новый метод использует `_SCHEMA_VERSION_AGI_MEMORY`.
- Новый метод `DatabaseService._migrate_self_origin_v9()` (образец `_migrate_video_origins_v4`/`_migrate_agi_memory_v8`):
  - guard: `'bot_self_reply' not in sqlite_master.sql('graph_facts')`; **`PRAGMA user_version = 9` ставится ВСЕГДА** (вне guard) — на новой БД CHECK уже может содержать значение (т.к. v5/v8 интерполируют обновлённый `_GRAPH_FACT_ORIGINS_SQL`), тогда rebuild корректно пропускается, но версия фиксируется;
  - `ALTER TABLE graph_facts RENAME TO graph_facts_v9_legacy`;
  - `CREATE TABLE graph_facts` с `CHECK (origin IN <11>)` и всеми 16 колонками v8 (`id, chat_id, fact, origin, expires_at, created_at, target_user, weight, status, last_confirmed_at, supersedes, message_timestamp, importance, source_ids, kind, belief_meta`);
  - `INSERT ... SELECT` всех 16 колонок (id 1:1 → FTS/vec валидны);
  - `DROP TABLE graph_facts_v9_legacy`;
  - пересоздать 5 индексов v8;
  - `PRAGMA user_version = 9`.
- Вызов в `initialize()` после `_migrate_agi_memory_v8()` (`:401`).
- **Обратимость:** откат = `UPDATE graph_facts SET origin='bot_direct_reply' WHERE origin='bot_self_reply'` + `git revert` (старый CHECK иначе отклонит строки).

### 2.2. PG: `persona_state` (singleton; владелец DDL — F1)

```sql
CREATE TABLE IF NOT EXISTS persona_state (
    id                  BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),
    last_extract_at     TIMESTAMPTZ,
    last_extract_status TEXT NOT NULL DEFAULT 'never',  -- ok|empty|error|skipped
    last_error          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO persona_state (id) VALUES (true) ON CONFLICT (id) DO NOTHING;
```
F2 расширяет таблицу трейт-колонками (`last_trait_at`, `last_trait_status`) через `ADD COLUMN IF NOT EXISTS` (аддитивно, идемпотентно) — см. spec F2.

### 2.3. Каталог-Δ F1 (санкционированный)

| pg_key | группа | тип | settings_field | дефолт | per_chat |
|---|---|---|---|---|---|
| `limits.graph_fact_weight_bot` | `limits_graph` | float | `GRAPH_FACT_WEIGHT_BOT` | `0.2` | true |
| `flags.bot_self_awareness_enabled` | `flags_memory` | bool | `BOT_SELF_AWARENESS_ENABLED` | **`True`** | true |

### 2.4. Новый origin — свойства

- `origin='bot_self_reply'`, `status='confirmed'`, `kind='fact'`, `target_user=NULL`, `importance=2`, `weight` из hot-ключа, TTL как у прямого чата.
- В RAG попадает только при `include_self=True` (direct-путь); метка `[Источник: Я сам (Бот)]`.

---

## §3. Алгоритмы

### 3.1. LLM-экстрактор сути (`services/self_reflection.py`, новый)

```python
SELF_REFLECTION_PROMPT = (
    "Ты — модуль саморефлексии бота. Ниже — только что отправленный ответ бота. "
    "Верни РОВНО одну короткую фразу-суть в формате: "
    "[Бот] <решил|посоветовал|заявил>: <суть (≤300 симв.)>. "
    "Без пояснений, без кавычек, без списков. Если сути нет — верни пустую строку.")

async def extract_self_essence(llm, answer: str, *, chat_id=None) -> str:
    """LLM-only. generate_worker('reflection') → фоллбэк generate() (основная).
    Fail-safe: любая ошибка/пусто → ''. Нормализация: strip, схлопывание
    whitespace, cap settings.SELF_ESSENCE_MAX_CHARS (300)."""

def record_extractor_status(status: str, error: str | None = None) -> None:
    """best-effort UPSERT persona_state.last_extract_at/status/error (never raises)."""
```

- Вызов в `_memorize_direct_reply` (см. §3.3) при флаге ON; результат — до записи факта.
- Роль `reflection` регистрируется в F8; пока F8 не влит — `generate_worker` бросает `ValueError` → фоллбэк на `llm.generate`.

### 3.2. Запись self-факта

`MemoryManager.memorize_self_reply(chat_id, essence)` (или прямой вызов `db.insert_graph_fact`):
```
if not hot.get("flags.bot_self_awareness_enabled", settings.BOT_SELF_AWARENESS_ENABLED): return 0
if not essence: return 0
weight = clamp(hot.get("limits.graph_fact_weight_bot", settings.GRAPH_FACT_WEIGHT_BOT))
expiry = None if ttl in (None,0) else now + ttl_days*86400*(0.5+weight)
fact_id = await db.insert_graph_fact(chat_id, essence, "bot_self_reply",
             expires_at=expiry, target_user=None, status="confirmed",
             weight=weight, importance=2, kind="fact")
# vec — best-effort (fail-open, как существующие memоrize-пути)
```
- FTS-строка пишется внутри `insert_graph_fact`; nodes/edges НЕ создаются.

### 3.3. Разделение прямого ответа (`_memorize_direct_reply`, `:959-990`)

- **Флаг OFF:** прежняя строка байт-в-байт — `memorize_facts(chat_id, f"{query}\n{answer}", "bot_direct_reply", target_user=asker)`.
- **Флаг ON:**
  1. `memorize_facts(chat_id, query, "bot_direct_reply", target_user=asker)` — только запрос (вес 0.7);
  2. `essence = await extract_self_essence(self.llm, answer, chat_id=chat_id)`;
  3. `record_extractor_status('ok'|'empty'|'error')`;
  4. `memorize_self_reply(chat_id, essence)` если essence непуст;
  5. пост-фаза `_reassign_fact_owners` — `before_id` берётся ДО обоих вызовов (self не переприсваивается — он не `bot_direct_reply`).

### 3.4. RAG-рендер и opt-in

- `_ORIGIN_LABELS['bot_self_reply'] = 'Источник: Я сам (Бот)'` (`summary_memory.py:294-305`).
- `database.search_graph_facts_fts(..., include_self=False)`: `if not include_self: AND f.origin != 'bot_self_reply'`.
- `summary_memory._vec_candidates` (`:2474`): `and (include_self or row["origin"] != "bot_self_reply")`.
- `_search_graph_facts`/`_knn_graph_facts`/`get_rag_facts` — параметр `include_self=False` (default) пробрасывается; direct-путь `_build_rag_block` передаёт `include_direct_reply=True, include_self=True`.
- Кортежи остаются 4-элементными `(origin, fact, rag_ts, author)`.

### 3.5. Анти-эхо-инструкция

```python
_SELF_ECHO_INSTRUCTION = ("Ниже — твои ПРОШЛЫЕ слова. Относись к ним критически: "
                          "ты мог шутить, отыгрывать роль или ошибаться.")
```
- `_build_rag_block` (`direct_chat_service.py:1690-1771`): если среди `kept` есть self (`item[0]=='bot_self_reply'`) → строка добавляется первой внутри `<RAG_Memory>`.
- Только при self; канон промпта direct не меняется → PREV/`PROMPT_MIGRATIONS` не нужны.

### 3.6. Исключения self (по origin)

| Место | Изменение |
|---|---|
| `dream_worker._DREAM_SOURCE_ORIGINS` `:132-136` | без изменений; self просто не в списке |
| `database.list_new_confirmed_facts` `:1971-1984` | `AND origin != 'bot_self_reply'` |
| `database.search_golden_facts_fts` `:2359-2385` | `AND f.origin != 'bot_self_reply'` |
| `database.get_live_graph_facts` `:3315`; `find_exact_dup_groups` `:3332` | `AND origin != 'bot_self_reply'` |
| `database.graph_stats.facts` `:3579-3581` | `AND origin != 'bot_self_reply'`; + новый счётчик `bot_self_replies` |
| `database.search_graph_facts_fts` / `_vec_candidates` | `include_self=False` по умолчанию |

### 3.7. Метрики экстрактора

- `record_extractor_status` пишет `persona_state` best-effort (не роняет ответ).
- F4 читает `bot_persona.get_persona_health()` → `extractor_status`, `extractor_last_at`.

---

## §4. Файлы и точки изменения (`file:line` на HEAD `2edc65b`)

| Файл | Точка | Изменение |
|---|---|---|
| `services/database.py` | `:53` | `_SCHEMA_VERSION_AGI_MEMORY=9`; `_SCHEMA_VERSION_AGI_MEMORY_V8=8` |
| `services/database.py` | `:67-71` | `_GRAPH_FACT_ORIGINS_SQL` + `bot_self_reply` |
| `services/database.py` | `:78-88` | `_IMPORTANCE_BASE['bot_self_reply']=2` |
| `services/database.py` | `:230-246` | базовая CHECK (v7-база) — оставить; актуальный CHECK после rebuild-миграций |
| `services/database.py` | `initialize` `:401` | вызвать `_migrate_self_origin_v9()` |
| `services/database.py` | новый метод `_migrate_self_origin_v9` | rebuild (§2.1) |
| `services/database.py` | `:1971`, `:2359`, `:3315`, `:3332`, `:3579` | origin-фильтры self |
| `services/database.py` | `search_graph_facts_fts` `:2388` | `include_self` |
| `services/summary_memory.py` | `:211-222` | ветка `bot_self_reply` → `limits.graph_fact_weight_bot` |
| `services/summary_memory.py` | `:294-305` | label `Источник: Я сам (Бот)` |
| `services/summary_memory.py` | `:2184`, `:2235`, `:2431`, `:2474` | `include_self` plumbing |
| `services/summary_memory.py` | новый `memorize_self_reply` (или на стороне MemoryManager) | §3.2 |
| `services/self_reflection.py` | новый | prompt, `extract_self_essence`, `record_extractor_status` |
| `services/direct_chat_service.py` | `_memorize_direct_reply` `:959-990` | split query/answer + экстрактор |
| `services/direct_chat_service.py` | `_build_rag_block` `:1690-1771` | `include_self=True` + анти-эхо |
| `services/pg_db.py` | `DDL_STATEMENTS` | `persona_state` + сид singleton |
| `config/settings.py` | `:797-798` | `GRAPH_FACT_WEIGHT_BOT`, `BOT_SELF_AWARENESS_ENABLED`, `SELF_ESSENCE_MAX_CHARS` |
| `services/param_catalog.py` | `_LIMITS`/`_FLAGS` | +2 записи |
| `.env.example` | рядом с `GRAPH_FACT_WEIGHT_*` | +`GRAPH_FACT_WEIGHT_BOT=0.2`, +`BOT_SELF_AWARENESS_ENABLED=true` |
| тесты | новые `tests/test_self_reflection.py`, `tests/test_graph_facts_origin_v9.py`; расширить `test_summary_memory*`, `test_dream*`, `test_direct_chat*`, `test_param_catalog` | §7 |

---

## §5. Конфиг/дефолты

| Ключ | Тип | Дефолт | Назначение |
|---|---|---|---|
| `limits.graph_fact_weight_bot` | float | **0.2** | вес self-факта |
| `flags.bot_self_awareness_enabled` | bool | **True** | гейт механики (UPD п.2) |
| `settings.SELF_ESSENCE_MAX_CHARS` | int | 300 | cap сути (code-константа, без каталога) |
| `limits.chat_direct_reply_ttl_days` | int | 30 | TTL self (существующий) |

---

## §6. Feature flag / progressive delivery

- `flags.bot_self_awareness_enabled` — **default True** (требование владельца). OFF → `_memorize_direct_reply` байт-в-байт прежний, self не пишется, RAG без self/инструкции.
- Rollback: флаг OFF + `git revert`; данные обратимы (`UPDATE ... SET origin='bot_direct_reply'`).

---

## §7. Тест-план

1. **Миграция v9:** legacy-фикстура v8 со всеми колонками → прогон дважды (идемпотентно); все строки/`importance`/`kind`/`belief_meta`/`source_ids` сохранены; `origin='bot_self_reply'` вставляется; старый origin `derived_belief` не потерян; FTS-хит по id работает; `user_version==9`.
2. **From scratch:** пустая БД → `initialize()` → v9, `PRAGMA user_version==9`, схема содержит все 16 колонок.
3. **Вес/важность:** `_origin_weight('bot_self_reply')==0.2`; hot-override `limits.graph_fact_weight_bot`; `rule_importance('bot_self_reply', ...)>=2`.
4. **Экстрактор:** формат `[Бот] ...`; пустой/кривой ответ → `''`; dedicated-ошибка → фоллбэк на `generate`; `record_extractor_status` пишет `persona_state`.
5. **Запись self:** flag OFF → нет строки; ON → `origin='bot_self_reply'`, `status='confirmed'`, `kind='fact'`, `target_user IS NULL`; FTS-строка есть; nodes/edges нет.
6. **Разделение:** ON → `query` под `bot_direct_reply`, essence под `bot_self_reply`; OFF → `query\nanswer` под `bot_direct_reply` (байт-в-байт).
7. **RAG:** метка `[Источник: Я сам (Бот)]`; `include_self=False` → self невидим; direct `include_self=True` → виден; анти-эхо только при self.
8. **Исключения:** self не в `get_dream_candidate_chats`/`get_new_chat_facts`-эквивалентах/`list_new_confirmed_facts`/`search_golden_facts_fts`/`get_live_graph_facts`; `graph_stats.facts` без self, `bot_self_replies` считает.
9. **PG DDL:** `PgDatabase.init()` дважды — без ошибок; `persona_state` singleton-строка ровно одна.
10. **Каталог/инварианты:** Δ: REGISTRY 427→435, Settings 399→406, categorized 403→411, GROUPS 90, mapped 88, TAB_RULES/CONFIG_TAB_TITLES 19 (см. сводную таблицу F2 §5 — общий Δ раунда).
11. `node --check web/app.js`, полный pytest 0 failed, `git diff --check`.

---

## §8. Риски и митигации

| Риск | Митигация |
|---|---|
| Rebuild теряет колонки/строки | копирование всех 16 колонок + тесты «до/после», «from scratch», идемпотентность |
| FTS/vec ломается после rebuild | id сохраняются 1:1 (D201); тест FTS-хита и vec-поиска |
| Старый CHECK отклонит откат | обратный `UPDATE origin` перед revert (документировано) |
| Self всё же просачивается в Сон/золотые | явные origin-фильтры + регресс-тесты по каждому месту |
| Роль `reflection` не зарегистрирована (F8 не влит) | `generate_worker` обёрнут; фоллбэк на основную модель |
| LLM-экстрактор дорог/шумит | cap 300, low importance/weight, fail-safe, метрики |
| Pytest-база смещается | фиксировать Δ и обновлять пин-тесты каталога |

---

## §9. Критерии приёмки (DoD)

- [ ] `graph_facts.origin` CHECK расширен `'bot_self_reply'`; SQLite `user_version==9`; миграция идемпотентна и не теряет данные.
- [ ] Все self-высказывания — `origin='bot_self_reply'`, `status='confirmed'`; вес 0.2, важность 2.
- [ ] Экстрактор — LLM (роль `reflection`), фоллбэк на основную модель, fail-safe; длинные ответы целиком не сохраняются.
- [ ] В `<RAG_Memory>` при self есть тег `[Источник: Я сам (Бот)]` и анти-эхо-инструкция.
- [ ] Сон/«золотые»/компакция/`graph_stats.facts` self не видят; `persona_state` обновляется.
- [ ] Флаг OFF → поведение байт-в-байт прежнее.
- [ ] Полный `pytest` 0 failed (база 5392), `node --check` clean, Δ каталога задокументирован и закреплён пин-тестами.
