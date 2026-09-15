# ADR-1018-3 — Плотность и скоринг графа: Σ importance рёбер, STOP_LIST центров, ×2 за Убеждение/Парадигму, DDL `edges.fact_id` (v9→v10)

- **Статус:** Proposed (**обновлён после human-gate, итерация 2** — 15.09.2026)
- **Дата:** 2026-09-15
- **Раунд:** 10.18, фича F3 `graph-density-scoring-stoplist` (T-1727)
- **База:** HEAD `118a03c`.
- **SUPERSEDE:** **ADR-1015-2** («Degree Centrality + окрестность + очистка сирот») — полностью заменяется политикой скоринга/сидов/cap. Сохраняются из ADR-1015-2 только: раскрытие полной окрестности (оба направления), рёбра строго с обоими концами в наборе (S10.13-14), очистка сирот после edge-cap, честный `truncated`, сохранение `degree` в узле.
- **AMEND (итерация 2):** снимается ранее действовавший в задачах F3 инвариант «новых таблиц/колонок не требуется» — владелец санкционировал **обязательную** DDL-миграцию `edges.fact_id` (UPD п.1, строки 113-114).
- **Связано:** ADR-1013-2 (библиотека/Canvas-предохранитель), ADR-1018-5 (общий STOP_LIST-модуль), project.md §«Политика DDL» (DDL разрешён с раунда 10.4).

## Context

1. `graph_snapshot` ранжирует узлы по **Degree Centrality** = числу рёбер (`services/database.py:3657-3678`); метаузлы-форматы («видеосообщение», «кружочек», «ссылка») имеют высокую степень и забивают топ-50 (ТЗ §3.1).
2. Cap `120/240` (ADR-1013-2/1015-2) даёт визуально «пустой» граф (~100 узлов) — ТЗ §3.2 требует **500–800**.
3. **Критично:** у `edges` **нет** `fact_id` (`:239-253`), у `graph_facts` **нет** subject/object (`:261-271`); `upsert_edge` вызывается **до** `insert_graph_fact` (`services/summary_memory.py:1831-1841`). Формула «Σ importance фактов-рёбер через join» напрямую **невыразима**.
4. `graph_facts.importance` вычисляется `rule_importance()` (`services/database.py:82-113`) и clamp 1..10 в `insert_graph_fact` (`:1735-1736`).
5. **Решение владельца (UPD п.1):** «DDL edges.fact_id (v9 → v10) — **ДА**. … Никаких fallback-искажений с фейковыми весами. Инвариант на запрет DDL для этой задачи снимается.» → проектируем миграцию как обязательную часть фичи.
6. **Механизм миграций проекта:** `services/database.py:423-433` (цепочка `_migrate_*` в `init()`), `:45-60` (константы версий), образцы — `_migrate_history_import_v7` (ADD COLUMN c guard), `_migrate_self_origin_v9` (rebuild, `user_version` вне guard, обратимость в docstring).

## Decision

### D1. Link edge → fact: **обязательная** nullable-колонка `edges.fact_id` + миграция v9→v10
- **DDL:** `ALTER TABLE edges ADD COLUMN fact_id INTEGER` (nullable, без rebuild; FTS5/vec не затрагиваются) + `CREATE INDEX IF NOT EXISTS idx_edges_fact_id ON edges(fact_id)`; `_SCHEMA_SQL` CREATE TABLE обновляется для fresh DB; новая константа `_SCHEMA_VERSION_EDGES_FACT_ID = 10`; метод `_migrate_edges_fact_id_v10` в цепочке `init()` после `_migrate_self_origin_v9()`. **Факт реализации:** `CREATE INDEX` живёт в миграции (вне guard), а НЕ в `_SCHEMA_SQL` — на legacy-БД executescript идёт до v10 и упал бы на несуществующей колонке.
- **Идемпотентность:** guard по `PRAGMA table_info(edges)` («fact_id» нет → ALTER+index); `PRAGMA user_version = 10` — **всегда**, вне guard (прецедент v9).
- **Запись:** в `_memorize_facts_inner` порядок меняется — сначала `insert_graph_fact` (получаем `fact_id`), затем `upsert_edge(..., fact_id=fact_id)`; `upsert_edge` += `fact_id: int|None=None`; `ON CONFLICT … DO UPDATE SET fact_id = COALESCE(excluded.fact_id, edges.fact_id)`. **B3-5 (атомарность):** пара выполняется в ОДНОЙ транзакции (`commit=False` у обоих + единый `commit`, `rollback` при сбое второго шага) — «факт без ребра» невозможен; дефолт `commit=True` сохраняет поведение остальных вызовов. Cron-путь `_extract_and_save_graph` (`summary_memory.py:2919-2933`) не создаёт `graph_facts` → `fact_id` остаётся NULL (осознанно).
- **Legacy-рёбра:** **осознанный NULL** (backfill отклонён — сопоставление ребра и факта по triple-строке недетерминировано). Формула для NULL: `edge_importance = COALESCE(f.importance, e.weight)` — это не «фейковый вес», а честная деградация к повторяемости там, где provenance объективно неизвестен. Новые рёбра получают `fact_id` немедленно → постепенное оздоровление данных без backfill-миграции.
- **Обратный откат (документируется в docstring + spec §4.1b):** `git revert` безопасен (колонка аддитивна/безвредна); полный откат схемы — `DROP INDEX idx_edges_fact_id` + `ALTER TABLE edges DROP COLUMN fact_id` (SQLite ≥3.35) + `PRAGMA user_version = 9`. Данные не теряются.
- **Fallback-вариант (`weight` вместо formula) исключён** из ADR: он искажал смысл ТЗ, а DDL санкционирован.

### D2. Формула скоринга
`score(node) = Σ_{e инцидентных} edge_importance(e)`, где `edge_importance(e) = COALESCE(f.importance, e.weight)`; затем `×2`, если узел участвует в Убеждении/Парадигме. `degree` сохраняется как отдельная метрика (фронт `_graphSignature`), но **не** используется для сортировки. Tie-break: `score DESC, degree DESC, id ASC`.

### D3. STOP_LIST — только центры
`GRAPH_CENTER_STOPLIST = {видеосообщение, голосовое, сообщение, фото, кружочек, ссылка}` фильтруется **в seed-выборке**; периферия остаётся. Единый источник — новый `services/graph_stoplist.py` (список **centers** ≠ список **penalty** из ADR-1018-5; различия явные).

### D4. ×2 за Убеждение/Парадигму
Множество belief-узлов = node-id, чей `entity_name` встречается в тексте alive `graph_facts` `kind='belief'` (chat scope; bounded: beliefs немного). **Факт реализации:** `_belief_participation_blob` (casefold + ё→е склейка текстов живых beliefs) + пост-фильтр в Python (SQLite `lower()` — ASCII-only, кириллицу не понижает) **по границам токенов** (regex `(?<![\wё])…(?![\wё])`, B3-4) — подстрочные ложные срабатывания исключены («тема» внутри «система»). `score *= 2`. Fail-open: недоступно → множитель 1.

### D8. STOP_LIST и ранжирование — в Python поверх bounded-пула
Сиды ранжируются в Python по `score_final DESC, degree DESC, id ASC` над пулом `max(seed_nodes × 10, 2000)` (SQL-упорядочен по сырому score) — из-за кириллической нормализации STOP_LIST/×2. Пул ограничен, полного скана нет.

### D5. Плотность
`GRAPH_SEED_NODES = 150` (range 150–200), `GRAPH_MAX_NODES = 800`, `GRAPH_MAX_EDGES = 2400` — код-константы в `web/api/memory_agi.py` (каталог-Δ=0, прецедент ADR-1015-2). Окрестность/рёбра/сироты/`truncated` — алгоритм ADR-1015-2 сохраняется.

### D6. Perf-бюджет и Canvas
Индексы `idx_edges_fact_id`, при необходимости `idx_graph_facts_kind`. Замер до/после обязателен. Canvas-предохранитель ADR-1013-2 закрывается совместно с F4 (physics отключается по `stabilizationIterationsDone`); ADR-1013-2 **не supersede**, дополняется ссылкой на F4.

**S10.18-30 (итерация 3):** ×2-фаза матчинга belief-блоба была доминирующей стоимостью `graph_snapshot` (`re.search(name, blob)` на каждый узел пула ≤2000 в event loop). Заменена на O(1): токены блоба (`re.findall(r"[\wё]+", blob)`) строятся ОДИН раз, однословное имя проверяется как `name in token_set`, многословное — по padded-строке токенов; границы токенов (B3-4) сохранены. Замер на синтетическом профиле (15 000 рёбер / 20 000 фактов / 4 000 узлов / 200 живых beliefs, blob ≈5 КБ, пул 2000): полный `graph_snapshot` **241 мс → 55 мс** (×2-цикл **185 мс → 1.1 мс**). Бюджет: `graph_snapshot` ≤ ~60 мс на референсном профиле при пуле 2000 (polling 15 с, при manual — 5 с).

### D7. Feature flag — не введён
`flags.graph_scoring_v2_enabled` **не вводится**: каталог-Δ=0 и решение владельца (UPD) — новая политика (Σ importance, STOP_LIST, ×2, 150/800/2400) активна безусловно, без dead-code OFF-ветки. **Порядок соблюдён:** миграция v10 + запись `fact_id` (T-1773/T-1774) в том же батче ДО активации выборки. Rollback — `git revert` + обратный путь §D1.

## Consequences

**Positive**
- Топ формируется по важности, а не по «болтливости» узла; мусорные метаузлы уходят из центров.
- Плотность 500–800 узлов даёт осмысленную картинку; API-контракт сохранён (R16).
- STOP_LIST — единый источник, переиспользуется F5 (нет дрейфа).
- Минимальный DDL (nullable ADD COLUMN без rebuild) безопасен, идемпотентен и обратим; provenance рёбер становится точным.

**Negative**
- Вводится DDL (SQLite v9→v10) — отклонение от первоначальной формулировки tasks.md «колонок не требуется»; санкционировано владельцем (UPD п.1), требует ревью @Scanner (идемпотентность/обратимость).
- Исторические рёбра остаются с `fact_id IS NULL` → их вклад в score считается по `weight` (приближение) до появления новых рёбер.
- `chat_id=None` (вся база) — O(E) join; риск медленного polling 15с; кэш вне скоупа.
- Рост узлов до 800 повышает нагрузку на Android WebView (митигируется F4).
- STOP_LIST может ложно исключить из центров реально важный узел с таким именем (редкий кейс; периферия сохраняется).

## Alternatives

- **A1. Per-render LIKE-join `edges`↔`graph_facts` по triple-строке.** Отклонено: O(candidates×facts), неприемлемо при polling 15с и объёме истории (166k+ фактов).
- **A2. FTS5 MATCH на каждое ребро.** Отклонено: сотни per-edge запросов на рендер.
- **A3. Оставить Degree Centrality, только расширить cap.** Отклонено: не решает замусоренные центры (ТЗ §3.1).
- **A4. Взвешенный degree (Σ edge.weight).** Отклонено: weight — повторяемость, cap 5; ТЗ требует importance. **(Также отклонено владельцем как fallback при DDL — UPD п.1.)**
- **A5. Полный node-level `LIKE` по фактам для importance.** Отклонено: cross-product node×fact; не индексируется.
- **A6. Отдельная materialized-таблица node_score.** Отклонено: лишняя денормализация/DDL; fact_id достаточно.
- **A7. Backfill `fact_id` для исторических рёбер по triple-строке.** Отклонено: недетерминированное сопоставление (`"{subject} {predicate} {object}"` может расходиться с узлами/нормализацией), риск ошибочного provenance → неверный score. Осознанный NULL + `COALESCE` точнее и предсказуемее.
- **A8. Rebuild `edges` (как v8/v9-rebuild `graph_facts`).** Отклонено: не требуется для ADD COLUMN; rebuild дороже и рискует FK-ссылками `source_id/target_id`. ADD COLUMN — минимально инвазивная форма.

## References

- `services/database.py:45-60,82-113,239-253,261-271,415-433,764-1015,1600-1627,1699-1760,3624-3722`
- `web/api/memory_agi.py:56-62,551-572`; `web/app.js:5267-5324` (`_graphSignature`, `renderCognitionGraph`)
- `services/summary_memory.py:1808-1847` (`upsert_edge`/`insert_graph_fact`), `:2905-2934` (cron-путь, `fact_id` NULL)
- ADR-1015-2 (`plans/archive/graph-sampling-centrality-round1015/adr-1015-2-graph-sampling.md`); ADR-1013-2; S10.13-14 (§25); project.md §«Политика DDL»
- Задачи: T-1727 (ADR), T-1728 (скоринг), T-1729 (perf), T-1730 (stoplist), T-1731 (плотность), T-1732 (API/фронт), T-1733 (тесты), T-1734 (гейты), T-1735 (@Reviewer/@PM), **T-1773…T-1777 (итерация 2: миграция v10, `fact_id` на записи, тесты миграции/legacy NULL, обратный путь)**.
