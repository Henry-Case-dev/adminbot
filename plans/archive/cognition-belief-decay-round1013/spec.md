# Spec F2 — `cognition-belief-decay-round1013` (Belief Decay + Resurrection)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; спека Step 2 @Architect, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §4 + §4.1. Tasks: T-1424…T-1433. Тип: backend. P0.
> Зависимости: F1 (метки/рендер RAG). Вниз: F3 (архив/воскрешение), F5 (API).

## 0. Цель

Убеждения перестают быть вечными: без подкрепления новыми фактами теряют вес,
уходят в архив, но «воскрешаются» тремя механизмами (векторный резонанс,
Сон-Реаниматор, активация по графу).

## 1. Объём

### In scope
- Декай-шаг: неподкреплённые beliefs теряют 0.1/мес; `weight < 0.3` → архив.
- Изоляция архива из активного контекста; сохранение в векторном поиске с пенальти.
- Векторный резонанс + восстановление веса (воскрешение).
- Сон-Реаниматор (отмена дублирующего синтеза).
- Активация по графу (связки 2–3 узлов в L1 → горячий инжект).
- Телеметрия (API/health), feature flag `flags.belief_decay_enabled` (OFF).

### Out of scope
- Новые таблицы/DDL; изменение CHECK `kind`/`origin`.
- Параллельная реализация в F8/F3 (там только потребители).

## 2. Схема данных (без DDL — F2-Q1 РЕШЕНО)

**Хранилище архива:** `graph_facts.status = 'archived_belief'` (существующая
колонка `status`, **CHECK отсутствует** — сверено по `database.py:863`). НЕ
`kind` (там `CHECK(kind IN ('fact','belief'))` — новый `kind` = DDL → запрещено).
НЕ новый JSON-marker как единственный признак (SQL-фильтрация JSON дороже).

Доп. метаданные — в существующей колонке `belief_meta` (TEXT, JSON):
```json
{"confidence":1.0,"sources_count":2,"distilled_at":1710000000,"cluster_id":5,
 "base_weight":0.6,"archived_at":1719000000,"last_reinforced_fact_id":12345,
 "decay_months":3}
```
Состояния `status` для beliefs: `confirmed` (активно), `archived_belief`
(архив), `unconfirmed` (legacy soft-delete D-7). Белый список читающих путей:

| Путь | Фильтр статуса | Архив виден? |
|---|---|---|
| `search_graph_facts_fts` (FTS RAG) | `status='confirmed'` | нет (осознанно) |
| `_knn_graph_facts` (вектор RAG) | **меняем на `confirmed`+`archived_belief`** | **да, с пенальти** |
| `get_dream_candidates` (сон) | `status='confirmed' AND kind='fact'` | нет |
| `list_beliefs_for_supersede` | `status='confirmed'` | нет (реаниматор — отдельно) |
| `list_recent_beliefs` (API) | без фильтра | да (для дашборда) |
| `dig_into_lore` | включает архив | да (прямое копание) |

**Подкрепление (F2-Q2 — РЕШЕНО):** belief подкреплён, если появился новый
сырой факт (`kind='fact'`, `status='confirmed'`, `id > belief_meta.last_reinforced_fact_id`)
в том же чате, чей текст содержит **якорный токен** belief (первый значимый
токен через `significant_tokens`, как в `_find_supersede_old`). При подкреплении:
`last_confirmed_at = now`, `last_reinforced_fact_id = max(new_ids)`, `weight = base_weight`.

## 3. API/контракты

Аддитивно к `web/api/memory_agi.py` (секция memory, глобальный admin — как сейчас):
- `GET /api/memory/dream/beliefs?chat_id=&limit=&status=` — `status` опц.
  (`confirmed|archived_belief|all`, дефолт `all`), поля + `archived: bool`,
  `base_weight`, `archived_at` (R17-safe: только метаданные, без секретов).
- `GET /api/memory/health` (или расширение существующего health) —
  счётчики: `beliefs_active`, `beliefs_archived`, `resurrections_total`,
  `decay_runs_total`, `last_decay_at`.
- Никаких сырых ключей/эмбеддингов в ответах (R17).

## 4. Алгоритмы

### 4.1. Декай-шаг (cron/шаг в тик «сна»)
Запуск: не чаще `BELIEF_DECAY_INTERVAL_DAYS = 3` (код-константа settings).
Маркер последнего прогона — строка `memory_dream_log(kind='decay_run')`
(нулевой DDL). Идемпотентность: цель-вес считается от базы, не инкрементально.

```
now = int(time.time())
base = belief_meta.base_weight or DREAM_BELIEF_WEIGHT          # 0.6
inact = hot.get("limits.belief_inactivity_days", 180)
step  = hot.get("limits.belief_decay_per_month", 0.1)
arch  = hot.get("limits.belief_archive_threshold", 0.3)

for belief in beliefs(kind='belief', status='confirmed'):
    if reinforced(belief, now): continue                    # см. §2
    age_days = (now - (belief.last_confirmed_at or belief.created_at)) / 86400
    if age_days <= inact: continue
    months_overdue = int((age_days - inact) // 30)          # 30-дн. интервалы (F2-Q5)
    target = max(0.0, base - step * months_overdue)
    if target >= arch:
        update weight=target, last_confirmed_at unchanged
    else:
        update status='archived_belief', weight=max(target,0.0),
               belief_meta.archived_at=now, belief_meta.decay_months=months_overdue
```

### 4.2. Векторный резонанс (4.1.a)
В `_knn_graph_facts` (summary_memory):
```
records = await self.db.get_graph_fact_records(ids)   # без status-фильтра
by_id = {r.id: r for r in records if r["status"] in ("confirmed","archived_belief")}
...
for fid, cosine, vec in ranked:
    row = by_id.get(fid)
    if row is None: continue
    w_eff = _effective_weight(row["weight"], row["last_confirmed_at"], now)
    score = cosine * w_eff
    if row["status"] == "archived_belief":
        score -= hot.get("limits.belief_resonance_penalty", 0.3)   # пенальти
    sims.append((fid, score, vec, row, cosine))
# после выбора top:
if cosine >= hot.get("limits.belief_resonance_threshold", 0.78) \
   and status == "archived_belief":
    resurrect(fid): status='confirmed', weight=base, last_confirmed_at=now,
                  belief_meta.resurrected_at=now, belief_meta.resurrections+=1
```
Порог (F2-Q3 — РЕШЕНО): `limits.belief_resonance_threshold = 0.78` (cosine);
пенальти `limits.belief_resonance_penalty = 0.3`; база веса — `DREAM_BELIEF_WEIGHT` (0.6).
При resurrection — событие в телеметрию (счётчик) и (опц.) `memory_dream_log(kind='resurrect')`.

### 4.3. Сон-Реаниматор (4.1.b)
Перед `_write_belief` в `DreamWorker._distill_cluster`:
```
cluster_vec = embed(" ".join(fact texts))
archived = archived beliefs того чата (status='archived_belief')
best = argmax cosine(cluster_vec, archived_vec)
if best.cosine >= resonance_threshold:
    # синтез отменяется (экономия)
    resurrect(best.id): last_confirmed_at=now, weight=base,
                        fact_text — обновить? НЕТ (текст стабилен), обновляем дату
    log(kind='skipped', status='resurrected', belief_id=best.id)
    return "unchanged", tokens, True
```
Требование: не дублировать belief; дата обновляется, текст — нет.

### 4.4. Активация по графу (4.1.c) — F2-Q4 РЕШЕНО
Источник связок: SQLite `nodes`/`edges` (существующий GraphRAG-граф).
Окно L1: последние `L1_GRAPH_WINDOW = 40` сообщений `smart_messages` чата.
```
tokens = significant_tokens(l1_text)                       # casefold
matched_nodes = nodes(chat) where entity_name ∈ tokens
pairs = combinations(matched_nodes, 2) + triples(matched_nodes, 3)
hot_pairs = [p for p in pairs if freq(p in L1) >= 3]       # код-константа
if hot_pairs:
    archived = beliefs(status='archived_belief') чей anchor-токен
               или target_user ∈ names(hot_pairs)
    inject archived[:GRAPH_ACTIVATION_CAP=5] в <RAG_Memory> текущего хода
    (без вызова dig_into_lore); weight не восстанавливаем (только показ)
```
Кэп/пороги — код-константы (`GRAPH_ACTIVATION_CAP=5`, `GRAPH_ACTIVATION_MIN_HITS=3`),
не каталог (минимизация Δ). Fail-open: ошибка графа → без инжекта.

## 5. Файлы и точки изменения

| Файл | Что |
|---|---|
| `services/dream_worker.py` | `_write_belief` :657 (+base_weight в belief_meta); новая `_decay_step`/`_reinforce`; реаниматор в `_distill_cluster` :560 |
| `services/summary_memory.py` | `_knn_graph_facts` :2146 (статусы+пенальти+resurrect); резонанс-хелпер |
| `services/database.py` | `get_graph_fact_records` :2931 — добавить `belief_meta`,`kind` в SELECT; новые `list_archived_beliefs`, `list_reinforced_beliefs`, `set_belief_status`, `archive_belief`, `count_beliefs_by_status`, `last_decay_run` |
| `services/memory_health.py`, `services/memory_maintenance.py` | телеметрия/счётчики |
| `services/tool_router.py` | `dig_into_lore` — включает архив |
| `services/direct_chat_service.py` | graph-activation инжект (L1) — опц. hook |
| `web/api/memory_agi.py` | `status`-фильтр beliefs + health-счётчики |
| `config/settings.py` | дефолты 6 ключей (см. §7) |
| `services/param_catalog.py` | `_FLAGS`/`_LIMITS` += 6 записей |

## 6. Расписание

Декай — шаг внутри `DreamWorker._tick` (`dream_worker.py:255`) перед
`_process_chat`, под флагом `flags.belief_decay_enabled`. Тик уже 60 мин
(`DREAM_TICK_MINUTES`). Интервал между прогонами — 3 дня (константа). При
выключенном `memory.dream_enabled` декай также не идёт (приемлемо для бэкенд-фазы;
в проде `flags.belief_decay_enabled` OFF).

## 7. Каталог-Δ

| Ключ | Кат. | Группа | Тип/дефолт | Settings-поле | per_chat |
|---|---|---|---|---|---|
| `flags.belief_decay_enabled` | flags | `flags_memory` | bool / **False** | `BELIEF_DECAY_ENABLED` | true |
| `limits.belief_inactivity_days` | limits | `limits_memory` | int / 180 | `BELIEF_INACTIVITY_DAYS` | true |
| `limits.belief_decay_per_month` | limits | `limits_memory` | float / 0.1 | `BELIEF_DECAY_PER_MONTH` | true |
| `limits.belief_archive_threshold` | limits | `limits_memory` | float / 0.3 | `BELIEF_ARCHIVE_THRESHOLD` | true |
| `limits.belief_resonance_penalty` | limits | `limits_memory` | float / 0.3 | `BELIEF_RESONANCE_PENALTY` | true |
| `limits.belief_resonance_threshold` | limits | `limits_memory` | float / 0.78 | `BELIEF_RESONANCE_THRESHOLD` | true |

Итог F2: **REGISTRY +6 (406→412 с учётом F1)**, Settings +6 (378→384),
GROUPS 90, mapped 88, TAB_RULES 19 — без изменений. Тип float в каталоге —
как существующие (`_env_float`); сверить с `ParamSpec` type.

## 8. Feature flag / progressive delivery

- `flags.belief_decay_enabled` (default **OFF**). При OFF — поведение 10.12 без
  изменений (архива/реанимаций нет).
- Rollout: internal (тест-чат) → 10% (staged `--chat-id`) → 50% → 100%.
- Критерии отката: рост доли archived, ошибки воскрешения, деградация RAG.
- Rollback: `git revert` + флаг OFF; данные — восстановление weight через
  скрипт/`hot` (без DDL).

## 9. Тест-план

1. Декай на границе: 180 дней → нет; 181 → −0.1; 211 (месяц+1) → −0.2; вес 0.3
   → архив; вес 0.31 → не архив; идемпотентность (повторный прогон не меняет).
2. Подкрепление: новый факт с якорным токеном → сброс даты/веса; без токена — нет.
3. Изоляция: FTS/сон не видят архив; KNN видит с пенальти.
4. Резонанс: cosine ≥ 0.78 → resurrection (status confirmed, weight 0.6);
   ниже — без resurrection.
5. Реаниматор: сильное совпадение кластера → синтез отменён, старый belief
   восстановлен с новой датой (без нового id).
6. Граф-активация: связка 2–3 узлов ≥ 3 в L1 → архивные факты в контексте без
   `dig_into_lore`; ниже порога — нет.
7. Телеметрия: счётчики архива/воскрешений — R17-safe (нет эмбеддингов/ключей).
8. Регресс `test_dream*`, `test_memory*`, `test_summary_memory*`.

## 10. Риски

| Риск | Митигация |
|---|---|
| Архив теряется из KNN (status-фильтр) | Явно расширить статусы в `_knn_graph_facts` |
| `get_graph_fact_records` не отдаёт belief_meta | Добавить колонки в SELECT (аддитивно) |
| Дрейф веса при повторных прогонах | Цель от base, не инкремент |
| Реаниматор дублирует belief | Не создавать новый; обновлять дату старого |
| Пенальти 0.3 «топит» архив ниже всех | Порог 0.78 подобран ≥; tunable через каталог |

## 11. Критерии приёмки

- [ ] Декай 0.1/мес после 180 дней; `<0.3` → `archived_belief`; идемпотентно; без DDL.
- [ ] Архив не в активном контексте, но в KNN с пенальти −0.3.
- [ ] Резонанс ≥ порога → в контекст + вес восстановлен.
- [ ] Реаниматор отменяет синтез и обновляет дату.
- [ ] Граф-активация (2–3 узла) поднимает архив без `dig_into_lore`.
- [ ] Телеметрия и `flags.belief_decay_enabled` (OFF) на месте; R17/R16.
- [ ] `pytest` 0 failed; `git diff --check`; каталог-Δ (412/384) сверена.

## 12. Разрешение open questions (F2)

- **F2-Q1** — `status='archived_belief'` (колонка без CHECK), не `kind`, не JSONB-маркер.
- **F2-Q2** — подкрепление = новый confirmed-факт с якорным токеном (id > last_reinforced).
- **F2-Q3** — порог резонанса 0.78; пенальти 0.3; база веса 0.6.
- **F2-Q4** — связки из SQLite `nodes`/`edges`, L1=40 сообщений, cap 5, порог 3.
- **F2-Q5** — 30-дневные интервалы (детерминированно/тестируемо).
