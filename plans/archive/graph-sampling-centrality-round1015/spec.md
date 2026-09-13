# Спека F1 — `graph-sampling-centrality-round1015` (Умная выборка графа: Degree Centrality + окрестность + сироты)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). Реализовано T-1550…T-1556; гейты T-1549/T-1557 за @Architect/@Reviewer.
> **Раунд:** 10.15. **Тип:** backend (read-only выборка). **Приоритет:** P0. **T-ID:** T-1549…T-1557.
> **ТЗ:** `plans/current_task.md` §1 (backend-часть). **ADR:** [`adr-1015-2-graph-sampling.md`](adr-1015-2-graph-sampling.md).
> **Зависимости:** нет. **Конфликт файлов:** `services/database.py`, `web/api/memory_agi.py` (делит с F5 — только аддитивные поля, F5 их не добавляет в граф).
> **Закрывает техдолг:** S10.13-14 (висячие рёбра).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19.

## 1. Цель

Заменить неструктурированную выборку `graph_snapshot` на связную: **топ-50 сидов по Degree Centrality** → **все смежные узлы и рёбра** → **удаление сирот** (узел без рёбер ВНУТРИ выборки) и **висячих рёбер** (оба конца обязаны быть в `nodes`). Финальные cap `120/240` применяются ПОСЛЕ раскрытия и очистки. Контракт JSON для фронта (`vis-network`) сохраняется (только аддитивно/уточняюще).

**Проблема сейчас:** `services/database.py:3610-3665` применяет `LIMIT max_nodes` к «сырым» узлам ДО раскрытия окрестности и не гарантирует связность/отсутствие висячих рёбер → на фронте «сетка из разрозненных точек».

## 2. Scope

**In scope**
- Переписать тело `graph_snapshot` (`services/database.py:3610-3665`): сиды по centrality, раскрытие окрестности, очистка сирот/висячих рёбер, cap после очистки.
- Добавить параметр `seed_nodes` (default 50) в `graph_snapshot`.
- Константа `GRAPH_SEED_NODES = 50` в `web/api/memory_agi.py` рядом с `GRAPH_MAX_NODES/EDGES`; прокидка в вызов `:512-514`.
- Тесты: расширить `tests/test_webapp_round1013_f5_ui.py`; новый `tests/test_webapp_round1015_graph.py`.

**Out of scope**
- Фронт (physics/search) — F2. Релокация статистики/бейджи — F5.
- Изменение `graph_stats` (`:3667-3731`) — не трогать (контракт `/api/memory/stats` стабилен).
- Новые каталог-ключи, DDL, миграции. Записи в БД запрещены (read-only).

## 3. Схема данных и индексы (SQLite, без изменений)

Таблицы `nodes` (`id` PK, `chat_id`, `entity_name`, `entity_type`, `origin`, `expires_at`), `edges` (`id` PK, `chat_id`, `source_id→nodes.id`, `target_id→nodes.id`, `relation_type`, `weight`, `origin`, `expires_at`).

Существующие индексы (используем, **новых не создаём**):
- `idx_edges_source (source_id)`, `idx_edges_target (target_id)` — точечные выборки по концам/окрестности;
- `idx_edges_chat_weight (chat_id, weight)` — chat-скоуп + сортировка по весу;
- `idx_nodes_chat_type (chat_id, entity_type)` — chat-скоуп узлов.

**⛔ SQLite-схему не менять** (ноль новых таблиц/колонок/индексов), read-only.

### Контракт JSON (стабильный)

```json
{
  "nodes": [{"id": 12, "label": "Толян", "group": "user", "degree": 7}],
  "edges": [{"from": 12, "to": 44, "label": "дружит", "weight": 3}],
  "truncated": true,
  "limits": {"nodes": 120, "edges": 240}
}
```
- `limits` добавляется в API-роутере (`memory_agi.py:519`) — как сейчас.
- `degree` — сохраняется (F1-Q4 RESOLVED: фронт `_graphSignature`, `app.js:5239`, читает его). Семантика: **полный degree в скоупе** (число рёбер `origin != 'bot_direct_reply'` в пределах chat-скоупа).
- Новые поля JSON **не добавляются** (минимизация).

## 4. Алгоритм (точный)

**Параметры:** `chat_id: int|None`, `max_nodes=120`, `max_edges=240`, `seed_nodes=50`.
`ADJ = "r.origin != 'bot_direct_reply'"`, `SCOPE = "r.chat_id = ?"` (только при `chat_id is not None`).

### Шаг 1. Degree Centrality (неевзвешенная, по числу рёбер)

F1-Q1 RESOLVED: степень = количество **рёбер** (каждое ребро считается один раз), НЕ сумма `weight`. Обоснование: топология важнее малых целочисленных весов; детерминизм.

```sql
WITH re AS (
  SELECT source_id AS nid, target_id AS oid FROM edges
   WHERE origin != 'bot_direct_reply' [AND chat_id = ?]
  UNION ALL
  SELECT target_id AS nid, source_id AS oid FROM edges
   WHERE origin != 'bot_direct_reply' [AND chat_id = ?]
),
deg AS (
  SELECT nid, COUNT(*) AS degree FROM re GROUP BY nid
),
seed AS (
  SELECT nid FROM deg ORDER BY degree DESC, nid ASC LIMIT ?   -- 50
),
adj AS (
  SELECT DISTINCT r.nid FROM re r WHERE r.oid IN (SELECT nid FROM seed)
),
cand AS (
  SELECT nid FROM seed UNION SELECT nid FROM adj
)
SELECT n.id AS id, n.entity_name AS label, n.entity_type AS grp,
       COALESCE(d.degree, 0) AS degree
  FROM cand c
  JOIN nodes n ON n.id = c.nid
  JOIN deg  d ON d.nid = c.nid
 WHERE n.entity_name IS NOT NULL AND n.entity_name != ''
   [AND n.chat_id = ?]
 ORDER BY (c.nid IN (SELECT nid FROM seed)) DESC, degree DESC, n.id ASC
 LIMIT ?;   -- max_nodes + 1
```
- F1-Q3 RESOLVED: сохраняем **все компоненты**, достижимые из сидов (окрестность 1 шаг). Изолированные компоненты, не касающиеся сидов, отсекаются фильтром `cand`.
- При `< 50` сидов — берутся все (LIMIT естественно меньше).
- `seed` приоритизируется над `adj` в ORDER BY (сиды не вытесняются соседями с большим degree).

**Производительность:** degree — `GROUP BY` по `UNION ALL` двух **индексированных** выборок (`idx_edges_source`/`idx_edges_target`), без коррелированного `COUNT(*)` на каждый узел (текущий анти-паттерн `:3627-3630`). `adj` — два index-lookup'а по `IN (seed)` (OR-оптимизация SQLite). Ожидаемый `EXPLAIN QUERY PLAN`: `SEARCH edges USING INDEX idx_edges_*`. Для `chat_id` — `idx_edges_chat_weight` (filter chat).

### Шаг 2. Рёбра (строго оба конца в наборе)

```sql
SELECT source_id, target_id, relation_type, weight
  FROM edges
 WHERE origin != 'bot_direct_reply'
   AND source_id IN (<node_ids>) AND target_id IN (<node_ids>)
   [AND chat_id = ?]
 ORDER BY weight DESC, id DESC
 LIMIT ?;   -- max_edges + 1
```
**S10.13-14 закрыт:** `AND` вместо `OR` — рёбра с концом вне `nodes` не отдаются.

### Шаг 3. Очистка сирот (Python, ≤ ~121 узел)

```python
keep = {n["id"] for n in nodes}
edges = [e for e in edges if e["from"] in keep and e["to"] in keep]
# сироты = узлы без рёбер ПОСЛЕ edge-cap
edge_nodes = {e["from"] for e in edges} | {e["to"] for e in edges}
orphans = [n for n in nodes if n["id"] not in edge_nodes]
if orphans:
    nodes = [n for n in nodes if n["id"] in edge_nodes]
    # узел-сирота не вытесняет cap: дыр не остаётся (nodes ⊆ edge_nodes)
```
Если после удаления сирот `edges` ссылается только на оставшиеся узлы — повторный фильтр не нужен (по построению оба конца в `edge_nodes`).

### Шаг 4. `truncated`

`truncated = (raw_node_count > max_nodes) or (raw_edge_count > max_edges) or bool(orphans)`.
`nodes`/`edges` уже усечены до `max_nodes`/`max_edges`.

## 5. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `services/database.py:3610-3665` | Тело `graph_snapshot`: новые CTE (шаг 1), рёбра оба-конца (шаг 2), очистка сирот (шаг 3), `truncated` (шаг 4). Новый kwarg `seed_nodes: int = 50`. |
| 2 | `web/api/memory_agi.py:58-59` | Добавить `GRAPH_SEED_NODES = 50` (комментарий: F1-Q2 RESOLVED — код-константа, каталог-Δ=0). |
| 3 | `web/api/memory_agi.py:512-514` | Прокидка `seed_nodes=GRAPH_SEED_NODES` в `graph_snapshot(...)`. |
| 4 | `web/api/memory_agi.py:500-520` | Контракт без изменений; `limits` остаётся; fail-open 200 сохранён. |
| 5 | `services/database.py:3614-3616` | Docstring: обновить описание алгоритма/`truncated`. |

**Не менять:** `graph_stats` (`:3667+`), `web/api/memory_agi.py:525-544`, порядок роутеров `bot.py`, `media/`, `.env`.

## 6. Открытые вопросы → решения

- **F1-Q1** степень: **неевзвешенная** (число рёбер). `weight` — только порядок вывода рёбер.
- **F1-Q2** 50 сидов: **код-константа** `GRAPH_SEED_NODES` (каталог-Δ=0; прецедент `GRAPH_MAX_NODES/EDGES`, ADR-1013-2).
- **F1-Q3** компоненты: **все достижимые из сидов**; изолированные компоненты отбрасываются.
- **F1-Q4** `degree`: **сохранить** (фронт зависит). Семантика — полный degree в скоупе.

## 7. Конфиг/дефолты и feature-флаг

- Константы: `GRAPH_MAX_NODES=120`, `GRAPH_MAX_EDGES=240`, `GRAPH_SEED_NODES=50` — в `web/api/memory_agi.py` (код).
- **Feature flag:** не требуется (read-only). Rollback = `git revert`. **Каталог-Δ = 0.**

## 8. Тест-план

Новый `tests/test_webapp_round1015_graph.py` (fake/in-memory SQLite, как `test_webapp_round1013_f5_ui.py`):
1. **Топ-сиды:** строится граф с известным degree → 50 сидов совпадают с ожидаемыми (проверка приоритета).
2. **Окрестность:** узел, не входящий в топ, но смежный сиду, присутствует.
3. **Сироты:** изолированный узел (`degree ≥ 1` в полной базе, но рёбра ведут к узлам без `entity_name`) исключён.
4. **Нет висячих рёбер:** для всех `edges` `e.from`/`e.to` ∈ `nodes.id` (S10.13-14).
5. **cap/truncated:** >120 кандидатов → `len(nodes) ≤ 120`, `truncated is True`; ≤0/пусто → `{nodes:[],edges:[],truncated:false}`.
6. **edge-cap → нет сирот:** узел, чьи связи отрезаны edge-cap, удаляется, `truncated is True`.
7. **`chat_id`-скоуп:** узлы/рёбра/degree считаются только по чату (нет кросс-чатовых).
8. **origin-исключение:** рёбра/degree с `origin='bot_direct_reply'` не учитываются.
9. **API:** `GET /api/memory/graph` — `limits` на месте, ответ связный; ошибка БД → 200 с пустым графом (fail-open, не 500).
10. **Регресс:** существующие `graph_snapshot`-кейсы `tests/test_webapp_round1013_f5_ui.py:238,361-363,461-462` обновлены под новую семантику (сироты/оба конца), не удалены.

**Гейты:** полный `pytest` 0 failed; `node --check web/app.js`; каталог Δ=0 (435/406/411/90/88/19); R17-скан; `git diff --check`; русский conventional commit.

## 9. Риски

| Риск | Митигация |
|---|---|
| `GROUP BY` по всем рёбрам дорог при `chat_id=None` (глобальный админ) | Только глобальный admin, polling 15с; индексы `idx_edges_*`; при росте — кандидат на кэш (вне скоупа). EXPLAIN-проверка в T-1557. |
| Расхождение с фронтом (`degree`) | Поле сохранено; `_graphSignature` не ломается (тест F2). |
| Латентное изменение состава графа | Новые unit-тесты + live-чеклист; откат `git revert`. |
| Слишком «плотный» соседний узел с degree > сида | ORDER BY приоритизирует сидов; при cap узлы-сироты удаляются стабильно. |

## 10. Критерии приёмки (DoD)

- [ ] Топ-50 сидов по centrality + **все** смежные узлы/рёбра в выборке.
- [ ] Нет узлов-сирот (каждый узел ≥1 ребро внутри выборки) и нет висячих рёбер (S10.13-14).
- [ ] cap `120/240` — финальный, после очистки; `truncated` честный; `limits` не изменён.
- [ ] `chat_id`-скоуп и исключение `origin='bot_direct_reply'` сохранены; fail-open (пустой граф, не 500).
- [ ] `degree` в узлах сохранён; контракт JSON совместим с фронтом.
- [ ] Новые тесты зелёные; полный `pytest` — 0 failed; `node --check` clean; каталог Δ=0.

## 11. Инварианты

R16 (`id` — ключ, `label` — `entity_name`, `group` — `entity_type`), R17 (только числа/имена, без эмбеддингов/секретов), **SQLite-схема без изменений**, read-only, `media/`/`.env` не трогать, порядок роутеров `bot.py` не трогать, каталог 435/406/411/90/88/19.
