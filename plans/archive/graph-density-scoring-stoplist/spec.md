# Spec F3 — `graph-density-scoring-stoplist` (Σ importance, STOP_LIST центров, ×2 за Убеждение/Парадигму, 500–800 узлов)

> **Раунд:** 10.18 (Step 2 @Architect, **итерация 2 после human-gate**, 15.09.2026). **Тип:** backend (`services/database.py`, `web/api/memory_agi.py`, `services/summary_memory.py`) + фронт-ёмкость. **Приоритет:** P1.
> **ADR:** `adr-1018-3-graph-density-scoring.md` (**SUPERSEDE ADR-1015-2**).
> **Задачи:** T-1727…T-1735 + **T-1773…T-1777** (итерация 2: DDL v10). **Baseline:** HEAD `118a03c`; pytest 6007 passed; каталог 435/406/411/90/88/19; SQLite v9 → **v10**.
> **Источник:** `plans/current_task.md` §3.1–§3.2 (строки 56–70) + **UPD п.1** (строки 113-114).
> **Зависит:** F5 — общая STOP_LIST-константа. **Влияет:** F4 (ёмкость физики).
> **UPD п.1 (решение владельца):** «DDL edges.fact_id (v9→v10) — **ДА**. Добавляйте fact_id, делайте миграцию на v10. Никаких fallback-искажений с фейковыми весами. Инвариант на запрет DDL снимается.» → **fallback-вариант удалён из спеки**, миграция обязательна (см. §4.1/§5).

## 1. Контекст и цель

Граф пуст (~100 узлов) и замусорен центрами-метаузлами («видеосообщение», «кружочек», «ссылка»). Текущее ранжирование — **Degree Centrality** (число рёбер), seed top-50, cap 120/240 (ADR-1015-2). Цель: считать **Σ importance** фактов-рёбер, ввести STOP_LIST **центров**, ×2 за участие в Убеждении/Парадигме, seed top-150, итог **500–800 узлов**.

## 2. Текущее поведение (сверено с кодом)

- `graph_snapshot(chat_id, max_nodes=120, max_edges=240, seed_nodes=50)` (`services/database.py:3624-3722`): CTE `re` (UNION source/target, `origin != 'bot_direct_reply'`) → `deg` (`COUNT(*)`) → `seed` (top-N `degree DESC, id ASC`) → `adj` → `cand` → узлы `ORDER BY is_seed DESC, degree DESC, id ASC LIMIT max_nodes+1` → рёбра строго с обоими концами (`:3693-3712`) → чистка сирот (`:3714-3718`).
- API: `GRAPH_MAX_NODES=120`, `GRAPH_MAX_EDGES=240`, `GRAPH_SEED_NODES=50` (`web/api/memory_agi.py:56-62`); `GET /api/memory/graph` (`:551-572`) отдаёт `{nodes, edges, truncated, limits}`; узел несёт `degree` (зависимость `_graphSignature`).
- `edges` (`services/database.py:239-253`): `id, chat_id, source_id, target_id, relation_type, weight(1..cap5), last_updated, origin, expires_at`; **нет ссылки на факт**.
- `graph_facts` (`:261-271` + v7/v8/v9 колонки): `id, chat_id, fact TEXT, origin, expires_at, created_at, target_user, status, supersedes, weight, last_confirmed_at, message_timestamp, importance, kind, source_ids, belief_meta`; **нет subject/object** — факт хранится как строка `"{subject} {predicate} {object}"` (+ `" (context)"`).
- `upsert_edge` вызывается из `_memorize_facts_inner` (`services/summary_memory.py:1831-1836`) **до** `insert_graph_fact` (`:1837-1841`) — прямой связи edge↔fact в схеме нет. Второй вызов `upsert_edge` — в крон-пути `_extract_and_save_graph` (`:2919-2933`) — **graph_facts там не создаётся вовсе** (для него `fact_id` останется NULL осознанно).
- Механизм миграций SQLite: `services/database.py` — константы версий (`:45-60`, текущая `_SCHEMA_VERSION_AGI_MEMORY = 9`), цепочка в `Db.init()` (`:423-433`), образец идемпотентной ступени `_migrate_self_origin_v9` (`:938-1015`): guard по `sqlite_master`, `PRAGMA user_version` **всегда** вне guard, обратимость документирована в docstring. Для ADD COLUMN образец проще — `v7`-ступень (`:839-840`) с idempotent-guard по `PRAGMA table_info`.
- `edges` (`:239-253`): `id, chat_id, source_id, target_id, relation_type, weight(1..cap5), last_updated, origin, expires_at`; **нет ссылки на факт**. `upsert_edge` (`:1600-1627`) — `INSERT … SELECT chat_id … FROM nodes` + `ON CONFLICT … DO UPDATE SET weight/last_updated`.
- `graph_facts` (`:261-271` + v7/v8/v9 колонки): `id, chat_id, fact TEXT, origin, expires_at, created_at, target_user, status, supersedes, weight, last_confirmed_at, message_timestamp, importance, kind, source_ids, belief_meta`; **нет subject/object** — факт хранится как строка `"{subject} {predicate} {object}"` (+ `" (context)"`).
- `rule_importance(origin, fact)` (`services/database.py:82-113`): база по origin + бонусы, clamp 1..10.

**Ключевой архитектурный факт:** формально «Σ importance рёбер (join к `graph_facts`)» **невыразим** на текущей схеме без дополнительного ключа (у `edges` нет `fact_id`, у `graph_facts` нет subject/object). **Решение принято владельцем (UPD п.1): обязательная DDL-миграция v9→v10 + nullable `edges.fact_id`** (см. §4.1 и ADR-1018-3 D1). Fallback-вариант «на weight» **не рассматривается**.

## 3. Требуемое поведение

1. Ранжирование центров — по **`score(node) = Σ_{e∈incident(node)} edge_importance(e)`**, где `edge_importance(e)` = importance факта, породившего ребро; детерминированный tie-break.
2. **STOP_LIST центров** (`видеосообщение, голосовое, сообщение, фото, кружочек, ссылка`) применяется **только к seed-выборке**; периферия сохраняется.
3. Узел — участник Убеждения или Парадигмы → **×2** к score.
4. Seed = **top-150** (range 150–200), затем вся окрестность; итог **500–800 узлов**.
5. Контракт `nodes/edges/truncated/limits` сохранён (R16); `degree` сохранён в узле.
6. Perf-бюджет запроса и Canvas-предохранитель ADR-1013-2 закрыты (F4 стабилизирует физику).

## 4. Технический дизайн

### 4.1. Связь edge → fact: обязательная DDL-миграция v9→v10 (без fallback)

**Решение владельца (UPD п.1): DDL разрешён и обязателен.** Никаких фейковых весов.

**a) Схема (SQLite v9 → v10):**
```sql
ALTER TABLE edges ADD COLUMN fact_id INTEGER;              -- nullable, без rebuild
CREATE INDEX IF NOT EXISTS idx_edges_fact_id ON edges(fact_id);
PRAGMA user_version = 10;
```
- `_SCHEMA_SQL` CREATE TABLE `edges` (`services/database.py:239-250`) обновляется для fresh DB: добавить `fact_id INTEGER,` (после `expires_at`).
- **Реализация (T-1773):** `CREATE INDEX idx_edges_fact_id` вынесен из `_SCHEMA_SQL` в `_migrate_edges_fact_id_v10` (вне guard). Причина: на legacy-БД `_SCHEMA_SQL` выполняется ДО миграции v10, когда колонки `fact_id` ещё нет — `CREATE INDEX ... ON edges(fact_id)` там падал бы (`no such column`). Fresh DB получает колонку из CREATE TABLE, индекс — из миграции.
- FTS5/vec **не затрагиваются** (ALTER ADD COLUMN без rebuild; `graph_facts` не пересоздаётся).

**b) Миграция (`services/database.py`):**
- Новая константа `_SCHEMA_VERSION_EDGES_FACT_ID = 10` (рядом с `:45-60`); текущая цель — 10.
- Новый метод `_migrate_edges_fact_id_v10(self)`, вызываемый в `Db.init()` **после** `_migrate_self_origin_v9()` (`:433`). Образец идемпотентности — `v7`-ступени (guard по `PRAGMA table_info`):
  ```python
  cursor = await self.db.execute("PRAGMA table_info(edges)")
  cols = {row["name"] for row in await cursor.fetchall()}
  if "fact_id" not in cols:
      await self.db.execute("ALTER TABLE edges ADD COLUMN fact_id INTEGER")
      await self.db.execute(
          "CREATE INDEX IF NOT EXISTS idx_edges_fact_id ON edges(fact_id)")
      await self.db.commit()
  await self.db.execute("PRAGMA user_version = 10")   # ВСЕГДА, вне guard
  await self.db.commit()
  ```
- Повторный запуск — no-op (guard); `user_version` фиксируется безусловно (прецедент `_migrate_self_origin_v9:1012-1015`).
- **Обратный откат (документируется в docstring + ADR):** колонка аддитивна и nullable; `git revert` безопасен. При необходимости полного отката схемы — `ALTER TABLE edges DROP COLUMN fact_id` (SQLite ≥3.35; иначе оставить колонку — она безвредна) + `DROP INDEX idx_edges_fact_id` + `PRAGMA user_version = 9`. Данные не теряются.

**c) Запись связи (`services/summary_memory.py::_memorize_facts_inner`):**
- Порядок меняется: **сначала** `fact_id = await self.db.insert_graph_fact(...)` (`:1837-1841`), **потом** `await self.db.upsert_edge(..., fact_id=fact_id)` (`:1831-1836`). `dedup`-ветка `continue` (`:1811-1818`) не затронута.
- `upsert_edge` (`services/database.py:1600-1627`) += параметр `fact_id: int | None = None`; SQL:
  ```sql
  INSERT INTO edges (chat_id, source_id, target_id, relation_type, weight,
                     origin, expires_at, fact_id)
  SELECT chat_id, ?, ?, ?, ?, ?, ?, ? FROM nodes WHERE id = ?
  ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
    weight = MIN(weight + excluded.weight, :cap),
    last_updated = CURRENT_TIMESTAMP,
    fact_id = COALESCE(excluded.fact_id, edges.fact_id)
  ```
- Совместимость вызовов: параметр опциональный, дефолт `None` → все существующие вызовы (`:1831`, cron `:2919-2933`) не меняются; в cron `fact_id` останется NULL (осознанно).
- **Атомарность fact+edge (B3-5):** оба шага (T-1774) идут в ОДНОЙ транзакции — `insert_graph_fact(..., commit=False)` + `upsert_edge(..., commit=True по умолчанию, здесь commit=False)` + единый `commit`; при сбое второго шага `rollback` (факт не остаётся без ребра). Новый опциональный `commit: bool = True` у обоих методов (дефолт — поведение прочих вызовов неизменно).

**d) Существующие рёбра без `fact_id` (решение):**
- **Вариант принят: осознанный NULL** (вариант «backfill» отклонён как недетерминированный — сопоставление ребра и факта по triple-строке ненадёжно: `insert_graph_fact` пишет `"{subject} {predicate} {object}"`, а нормализация/склейка может расходиться).
- Семантика для NULL: `edge_importance(e) = COALESCE(f.importance, e.weight)` (**деградация к повторяемости**, не «фейковый вес»). Это не fallback-выбор варианта формулы, а корректная обработка исторических данных, для которых provenance объективно неизвестен.
- Новые/обновлённые рёбра получают `fact_id` немедленно → формула Σ importance работает точно. Постепенное «оздоровление» данных без backfill-миграции.
- R17-safe: в логи выводится только счётчик `edges_fact_id_null` (число) при необходимости диагностики.

### 4.2. SQL (`services/database.py::graph_snapshot`)

Новые константы аргументов: `seed_nodes=150`, `max_nodes=800`, `max_edges=2400`. Формула (эскиз):

```sql
WITH re AS (
  SELECT source_id AS nid, target_id AS oid, id AS eid FROM edges
   WHERE origin != 'bot_direct_reply' <scope>
  UNION ALL
  SELECT target_id AS nid, source_id AS oid, id AS eid FROM edges
   WHERE origin != 'bot_direct_reply' <scope>),
imp AS (                                 -- важность ребра = importance факта
  SELECT e.id AS eid, COALESCE(f.importance, e.weight) AS eimp
    FROM edges e LEFT JOIN graph_facts f ON f.id = e.fact_id
   WHERE e.origin != 'bot_direct_reply' <scope>),
score AS (                               -- Σ по инцидентным рёбрам
  SELECT r.nid AS nid, SUM(i.eimp) AS s
    FROM re r JOIN imp i ON i.eid = r.eid
   GROUP BY r.nid)
```
- `degree` сохраняем как отдельную метрику (`COUNT(*)`), но сортировка — по `s`.
- **Реализация (T-1728):** ранжирование сидов делается в Python поверх bounded-пула (`max(seed_nodes × 10, 2000)` строк, упорядоченных SQL по сырому `s DESC, degree DESC, id ASC`). Причина: SQLite `lower()` не понижает кириллицу, поэтому STOP_LIST и ×2 нельзя надёжно применить в SQL. Пул ограничен — полного скана нет.
- **STOP_LIST центров:** `is_center_stopword(label)` (единый `services.graph_stoplist`, нормализация casefold/ё→е) фильтрует **только сиды**; периферия сохраняется.
- **×2:** `_belief_participation_blob(chat_id)` — bounded-выборка текстов живых beliefs (`kind='belief'`, `status='confirmed'`, `supersedes IS NULL`; нормализация casefold + ё→е); узел получает ×2, если его `entity_name` (len ≥ 2, нормализован так же) входит в текст **по границам токенов** (regex `(?<![\wё])…(?![\wё])`), а не подстрокой — «тема» не матчится внутри «система» (B3-4). При недоступности — множитель 1 (fail-open).
- Tie-break выбора сидов: `score_final DESC, degree DESC, id ASC`. Финальный порядок узлов — как в ADR-1015-2 (`is_seed DESC, degree DESC, id ASC`).
- Окрестность/рёбра/сироты/`truncated` — как сейчас (`:3668-3722`), но лимиты больше.

Новые константы в `web/api/memory_agi.py`:
```python
GRAPH_MAX_NODES = 800
GRAPH_MAX_EDGES = 2400
GRAPH_SEED_NODES = 150
GRAPH_CENTER_STOPLIST  # импорт из services.graph_stoplist
```

### 4.3. STOP_LIST — единый источник (`services/graph_stoplist.py`, новый)

```python
GRAPH_CENTER_STOPLIST: frozenset[str] = frozenset({
    "видеосообщение", "голосовое", "сообщение", "фото", "кружочек", "ссылка"})
METAFACT_PENALTY_STOPLIST: frozenset[str] = frozenset({
    "видеосообщение", "голосовое", "фото", "кружочек", "ссылка", "стикер"})

def normalize_token(value) -> str: ...        # casefold, strip, срез пунктуации, ё→е
def is_center_stopword(value) -> bool: ...
def is_metafact_stopword(value) -> bool: ...
```
Списки **различаются** (centers: `сообщение` есть, `стикер` нет; penalty: `стикер` есть, `сообщение` нет) — зафиксировано в ADR §D-stoplists. F5 переиспользует `METAFACT_PENALTY_STOPLIST`/`is_metafact_stopword` (без дублирования).

### 4.4. Perf / индексы

- Новые индексы (санкция ADR): `idx_edges_fact_id ON edges(fact_id)`; при необходимости `idx_graph_facts_kind ON graph_facts(chat_id, kind)`.
- Замер до/после в отчёте; при `chat_id=None` (global admin, polling 15с) — риск полного скана; ограничить seed+кап и/или кэш (вне скоупа).
- **×2-фаза (S10.18-30, обязательный бюджет):** токены belief-блоба строятся один раз, проверка участия имени — O(1) (`name in token_set` / padded для многословных), без per-node `re.search` по блобу в event loop. Референсный замер (15 000 рёбер / 20 000 фактов / 4 000 узлов / 200 beliefs, blob ≈5 КБ): полный `graph_snapshot` **241 мс → 55 мс** (бюджет ≤ ~60 мс; при `chat_id=None` — те же границы, blob агрегирует все чаты). Границы токенов (B3-4) сохранены.
- Canvas: 500–800 узлов = предохранитель ADR-1013-2; F4 обязателен следом.

## 5. Изменения схемы / каталога / env

- **DDL (санкционировано владельцем, UPD п.1):** SQLite **v9 → v10** — `ALTER TABLE edges ADD COLUMN fact_id INTEGER` (nullable, без rebuild → FTS/vec не затрагиваются) + индекс `idx_edges_fact_id`; `_SCHEMA_SQL` обновляется для fresh DB; `PRAGMA user_version = 10`. Идемпотентность — guard по `PRAGMA table_info(edges)`; обратимость — колонка аддитивна + документированный обратный путь (`DROP COLUMN`/`user_version=9`); данные не теряются. Существующие рёбра — **осознанный NULL** (см. §4.1d), не backfill.
- **Каталог:** Δ=0 (все лимиты — код-константы `GRAPH_*`); `GRAPH_SEED_NODES` остаётся код-константой (прецедент ADR-1015-2).
- **env:** не трогать.
- **Политика DDL (project.md §«Политика DDL»):** изменение структуры БД и миграции разрешены; требования к SQLite-миграциям (сохранение колонок/id, no-op при повторе, документированный обратный путь) соблюдены.

## 6. Влияние на тесты

- `tests/test_graphrag_database.py` / `test_database.py` / `test_webapp_api.py`: обновить ожидания диапазона (500–800 узлов), порядок по Σ importance, STOP_LIST не в центрах, ×2, отсутствие сирот/висячих рёбер (S10.13-14 не ломать).
- Новый `tests/test_graph_scoring_round1018.py`: формула (fixtures с `fact_id`), tie-break, **осознанный NULL → `COALESCE(f.importance, e.weight)`**, stop-list равенство/нормализация, ×2 **по границам токенов (B3-4: «тема» ≠ «система»; многословные имена)**, **плотность 500–800 на репрезентативном графе (B3-2: 150 центров × 3–5 соседей → 750 узлов, без усечения)**, **атомарность fact+edge (B3-5: сбой `upsert_edge` откатывает факт)**.
- **Тест миграции v10 (новый/расширить существующий):** guard no-op при повторном прогоне; fresh DB получает `fact_id`; `user_version == 10` выставляется всегда; индекс `idx_edges_fact_id` существует; FTS/vec валидны после миграции (id не менялись).
- `tests/test_summary_memory.py`: порядок `insert_graph_fact` → `upsert_edge(..., fact_id=…)`; `fact_id` заполнен для memorise-пути; cron-путь (`_extract_and_save_graph`) — `fact_id IS NULL`.
- Пин-тесты каталога — Δ=0 (не менять).
- JS: фронт не меняет контракт; `JS-UNIT-OK`/`VUE-MOUNT-OK`.
- Полный `pytest` 0 failed; `git diff --check`.

## 7. Rollout / feature-flag / откат

- **Реализация (T-1734):** флаг `flags.graph_scoring_v2_enabled` **не вводится** — каталог-Δ=0 и UPD владельца требуют активировать новую политику сразу (без dead-code). V2-скоринг/лимиты — безусловное поведение `graph_snapshot`/`memory_agi`.
- **Порядок соблюдён:** DDL-миграция v10 и запись `fact_id` (T-1773/T-1774) выполнены в том же батче ДО включения новой выборки (иначе формула видит только NULL).
- Rollback: `git revert` (DDL-колонка безвредна; при необходимости — обратный путь §4.1b).

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Конфликт с ADR-1015-2 | ADR-1018-3 **SUPERSEDE** ADR-1015-2 |
| R2 | Нет `edges.fact_id` → «Σ importance» невыразим | **Решено (UPD п.1):** обязательная миграция v9→v10, fallback исключён; legacy NULL → `COALESCE(importance, weight)` |
| R3 | Perf при `chat_id=None` (full-scan) | Индексы, кап, замер; кэш — вне скоупа |
| R4 | Canvas при 500–800 узлах | F4 (physics off по stabilizationIterationsDone); ADR-1013-2 |
| R5 | STOP_LIST уберёт полезные центры | Только центры; периферия живёт; тесты |
| R6 | Дублирование stop-list с F5 | Единый `services/graph_stoplist.py` |
| R7 | Рост сломает тесты графа 10.13/10.15 | Полный прогон, обновить диапазоны |
| R8 | Δ каталога конфликтует с F1/F6 | Δ=0 у F3 (код-константы) |
| R9 | **Миграция v10 повредит данные/FTS/vec** | ADD COLUMN без rebuild; guard по `table_info`; `user_version` вне guard; тест миграции + обратный путь; id не меняются |
| R10 | **Порядок записи edge/fact рассинхронизирует `fact_id`** | T-1774: перестановка + `COALESCE(excluded.fact_id, edges.fact_id)`; тест `fact_id` заполнен |
| R11 | **Итог 500–800 зависит от локальной плотности вокруг сидов** | Гарантия механизма: на репрезентативном профиле (150 центров × 3–5 соседей) алгоритм даёт **750 узлов без усечения** (тест B3-2). На реальном датасете с низкой связностью top-150 (~408 узлов) значение ниже — это свойство данных (у сидов мало соседей), а не дефект выборки; при необходимости поднять планку — отдельная задача (раскрытие 2 шага / seeds 200 / backfill), вне текущего скоупа. Диапазон НЕ «дожимается» cap-ом. |

## 9. Открытые вопросы

**Принято владельцем (не переоткрывается):** DDL `edges.fact_id` v9→v10 — **ДА**; никаких fallback с фейковыми весами (UPD п.1). Лимиты графа (seeds 150, cap 800/2400, STOP_LIST, ×2) — «как есть» (UPD п.4).

Осталось уточнить (@Builder при реализации, не блокирует):
1. **Судьба исторических рёбер (NULL vs backfill):** рекомендация — **осознанный NULL** (§4.1d) + точная формула для новых рёбер; backfill не делаем (недетерминированное сопоставление triple-строк). Если владелец захочет backfill — отдельная задача с эвристикой и метрикой точности.
2. **Seed 150 или 200:** рекомендация — 150 (баланс плотности/perf); кап `max_nodes=800`, `max_edges=2400`.
3. **Точный состав STOP_LIST центров:** рекомендация — ровно 6 слов из ТЗ §3.1.
4. **`chat_id=None` (вся база) при 800 узлах:** рекомендация — оставить (global admin, read-only), при perf-проблемах — кэш отдельной задачей.
5. **Способ обратного отката схемы:** рекомендация — `git revert` + оставить колонку (безвредна), полный `DROP COLUMN` — только по явному требованию (SQLite ≥3.35).
