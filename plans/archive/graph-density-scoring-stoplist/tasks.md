# Фича F3 — `graph-density-scoring-stoplist` (Граф: скоринг по Σ importance, STOP_LIST центров, ×2 за Убеждение/Парадигму, плотность 500–800 узлов, DDL `edges.fact_id` v9→v10)

> **Статус: ⏳ PLANNED** (Step 1 @PM → Step 2 @Architect, **итерация 2 после human-gate**, 15.09.2026). Реализация — T-1728…T-1734 + **T-1773…T-1777** (@Builder), гейты T-1727 (@Architect) / T-1735 (@Reviewer/@PM).
> **Spec:** `spec.md` (итерация 2). **ADR:** `adr-1018-3-graph-density-scoring.md` (**SUPERSEDE ADR-1015-2**; DDL санкционирован).
> **Раунд:** 10.18. **Нумерация:** T-1727…T-1735 + T-1773…T-1777.
> **Тип:** backend (`services/database.py`, `services/summary_memory.py`, `web/api/memory_agi.py`) + фронт-ёмкость. **Приоритет:** **P1**.
> **Зависимости:** —. **Конфликт файлов:** `services/database.py` (F5 тоже), `services/summary_memory.py`, `web/api/memory_agi.py` (F2), тесты графа.
> **ТЗ:** `plans/current_task.md` **§3.1–§3.2** + **UPD п.1** (строки 113-114).
> **Baseline:** HEAD `118a03c`; pytest **6007 passed / 0 failed**; каталог **435/406/411/90/88/19**; SQLite **v9 → v10**; APP_VERSION 2.57.0.

## 0. Цель

Убрать «мусорные технические» центры кластеров и поднять плотность картинки: топ считать по **Σ importance** образующих рёбра фактов, ввести **STOP_LIST центров**, давать **×2** узлам-участникам Убеждений/Парадигм, искать Топ-150/200 и отдавать **500–800 узлов** в итоговом JSON.

**Требуется (ТЗ §3.1–§3.2):**
- Формула топа: не число рёбер (Degree Centrality), а **сумма importance** фактов этих рёбер.
- **STOP_LIST центров** (исключить из топ-выборки как центры кластеров): `видеосообщение`, `голосовое`, `сообщение`, `фото`, `кружочек`, `ссылка`. В графе как **периферия** — допустимы.
- **Приоритет сущностей:** узел, участвующий в **Убеждении** или **Парадигме**, получает вес **×2**.
- **Плотность:** базовая выборка **Топ-150** или **Топ-200** центральных узлов (после фильтрации) + все смежные рёбра и узлы; итог — **500–800 узлов**.

## 1. Контекст и доказательства (@Memory Step 0 + аудит итерации 2)

- **Прямой конфликт с действующим ADR-1015-2:** там `degree = число рёбер`, сиды **топ-50**, cap **120/240**, `GRAPH_SEED_NODES` — **код-константа**. Требуется **новый ADR с SUPERSEDE ADR-1015-2**.
- **У ребра нет `importance` напрямую:** Σ importance потребует **join к `graph_facts`** → perf-risk на больших объёмах (T-1729).
- **Ключ связи edge↔fact отсутствует:** `upsert_edge` вызывается **до** `insert_graph_fact` (`services/summary_memory.py:1831-1841`) → нужна колонка `edges.fact_id` (DDL v9→v10) **и** перестановка порядка записи.
- **Решение владельца (UPD п.1):** DDL **разрешён и обязателен**, fallback-вариант исключён.
- **Canvas-предохранитель ADR-1013-2:** рост до 500–800 узлов — решить риск по нагрузке/рендеру (T-1727/T-1731).
- Текущий `graph_snapshot` — `services/database.py` (degree-CTE, seed top-N, join `nodes`, фильтр сирот/висячих рёбер). API — `web/api/memory_agi.py` (cap `120/240`, контракт `nodes/edges/truncated/limits`, R16).
- Техдолг **S10.13-14** (висячие рёбра) закрыт в 10.15 (F1) — не ломать.

## 2. Требования

- [x] **DDL v9→v10:** `edges.fact_id` (nullable) + `idx_edges_fact_id`; идемпотентная миграция; `user_version=10`; fresh DB — в `_SCHEMA_SQL`; обратный путь документирован.
- [x] Ранжирование узлов — по Σ importance рёбер (join к `graph_facts`), с детерминированным tie-break; legacy NULL → `COALESCE(f.importance, e.weight)`.
- [x] Запись `fact_id` в `_memorize_facts_inner` (порядок insert_fact → upsert_edge); cron-путь — NULL (осознанно).
- [x] STOP_LIST применяется **только к центрам** (топ-выборка); периферия сохраняется.
- [x] ×2 для узлов-участников Убеждений/Парадигм.
- [x] Сиды: Топ-150/200 после фильтрации; + все смежные рёбра и узлы; итог **500–800 узлов**; контракт сохранён (R16).
- [x] Perf: join/индексы укладываются в бюджет запроса; canvas выдерживает 500–800 (ADR-1013-2).

## 3. Constraints (инварианты раунда)

- **R16** (id — ключ: `id`/`entity_name`/`entity_type`), **R17** (без секретов/текстов).
- **DDL: санкционирован (UPD п.1)** — SQLite v9→v10; ADD COLUMN без rebuild; идемпотентность + обратный путь + сохранение данных/FTS/vec (project.md §«Политика DDL»).
- **Каталог:** **Δ=0** (лимиты — код-константы `GRAPH_*`).
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `node --check web/app.js`; JS-гейты; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** T-1727 (@Architect, ADR) — обязателен.
- **Вниз:** F4 (физика) — опирается на новую ёмкость узлов (500–800).
- **Порядок:** F3 → F4 (F3 увеличивает граф, F4 стабилизирует физику под новый размер). F3 делит stop-list-константу с F5 — согласовать.

## 5. Definition of Done

- [x] **Миграция v10 выполнена идемпотентно:** `edges.fact_id` + `idx_edges_fact_id`; `user_version=10`; fresh DB содержит колонку; FTS/vec валидны.
- [x] Топ формируется по Σ importance (+×2), а не по degree; технические мета-узлы не являются центрами кластеров.
- [x] Итоговый JSON в диапазоне **500–800 узлов**, рёбра/узлы согласованы (без висячих). *Уточнение (B3-2): диапазон подтверждён тестом на репрезентативном профиле (750 узлов, без усечения); на разреженном реальном графе значение ниже — свойство данных (spec R11).*
- [x] Контракт API сохранён (R16), cap/VALID лимиты обновлены согласованно.
- [x] Perf-бюджет соблюдён (индексы/бounded-пул; замер — §отчёт); canvas-риск ADR-1013-2 закрыт решением. **Уточнение (S10.18-30):** ×2-цикл переведён на O(1)-токены (241 мс → 55 мс на референсном профиле), см. §10.
- [x] Полный `pytest` **0 failed**; каталог Δ=0 зафиксирован; обратный путь отката описан.

## 6. Чек-лист задач

- [x] **T-1727 (@Architect, гейт):** `spec.md` + **ADR-1018-3** (итерация 2) — SUPERSEDE ADR-1015-2: формула скоринга (Σ importance через join к `graph_facts`), STOP_LIST центров, ×2, число сидов, новый cap, perf-бюджет/canvas, tie-break, **обязательная DDL v9→v10 и политика legacy-NULL**.
- [x] **T-1728 (@Builder):** backend — переписать ранжирование `graph_snapshot`: Σ importance по рёбрам (join к `graph_facts`), STOP_LIST центров, ×2 за Убеждение/Парадигму.
- [x] **T-1729 (@Builder):** perf — оптимизация join/индексов, ограничение объёма выборки, замер времени запроса.
- [x] **T-1730 (@Builder):** STOP_LIST как единый константный источник (без дублирования с F5).
- [x] **T-1731 (@Builder):** плотность — сиды Топ-150/200 + все смежные рёбра/узлы; обновить cap в `memory_agi.py`; гарантировать итог 500–800 узлов.
- [x] **T-1732 (@Builder):** API/фронт-ёмкость — контракт `nodes/edges/truncated/limits` сохранён; фронт корректно рендерит 500–800.
- [x] **T-1733 (@Builder):** тесты — порядок по Σ importance, STOP_LIST не в центрах, ×2 (в т.ч. границы токенов B3-4), диапазон 500–800 узлов на репрезентативном графе (B3-2), атомарность fact+edge (B3-5), отсутствие сирот/висячих рёбер.
- [x] **T-1734 (@Builder):** гейты — полный `pytest` 0 failed (**6100 passed**), каталог Δ=0, R17, `git diff --check` clean. Коммит — отдельным шагом @Orchestrator/@DevOps (Builder не коммитит).
- [ ] **T-1735 (@Reviewer + @PM, гейт):** сверка DoD, R16-контракт, perf-бюджет, согласованность ADR-1018-3 ↔ код, **аудит миграции v10**.

**Новые задачи итерации 2 (DDL v9→v10):**

- [x] **T-1773 (@Builder):** `services/database.py` — константа `_SCHEMA_VERSION_EDGES_FACT_ID = 10`; `_SCHEMA_SQL` `edges` += `fact_id INTEGER` (индекс `idx_edges_fact_id` НЕ в `_SCHEMA_SQL`, а в `_migrate_edges_fact_id_v10` — на legacy-БД executescript идёт до v10, `CREATE INDEX ... ON edges(fact_id)` там упал бы); метод `_migrate_edges_fact_id_v10` (guard по `PRAGMA table_info`, `CREATE INDEX IF NOT EXISTS` вне guard, `user_version=10` вне guard, docstring с обратным путём); вызов в `init()` после `_migrate_self_origin_v9` (`:433`).
- [x] **T-1774 (@Builder):** `services/database.py::upsert_edge` += `fact_id: int|None=None` + `ON CONFLICT … fact_id = COALESCE(excluded.fact_id, edges.fact_id)`; `services/summary_memory.py::_memorize_facts_inner` — перестановка: сначала `insert_graph_fact`, затем `upsert_edge(..., fact_id=fact_id)`; cron-путь `:2919-2933` — `fact_id=None` (осознанно, комментарий).
- [x] **T-1775 (@Builder):** тесты миграции v10 — идемпотентность/no-op; fresh DB; `user_version==10`; индекс существует; FTS/vec валидны; тест `fact_id` заполнен для memorise и NULL для cron/legacy.
- [x] **T-1776 (@Builder):** формула/скоринг — legacy NULL → `COALESCE(f.importance, e.weight)`; тест, что NULL-рёбра не выпадают из score и не искажают приоритеты неоправданно.
- [ ] **T-1777 (@Reviewer/@Scanner, гейт):** аудит DDL: идемпотентность, обратимость, сохранность данных/id, отсутствие влияния на FTS/vec; подтверждение «0 фейковых весов».
- [x] **T-1778 (@Builder, S10.18-30):** perf ×2-фазы — убрать per-node `re.search` по belief-блобу; токены блоба один раз (`re.findall(r"[\wё]+", blob)`) → `name in token_set` / padded для многословных (границы токенов B3-4 сохранены); замер на референсном профиле (241→55 мс) + WARNING `upsert_edge` при `rowcount==0` (S10.18-33).

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **Прямой конфликт с ADR-1015-2** (degree, top-50, cap 120/240) | Новый **ADR-1018-3 SUPERSEDE** (T-1727) |
| R2 | Σ importance требует join к `graph_facts` → perf-risk | T-1729 замер + индексы; лимит объёма |
| R3 | **Canvas-предохранитель ADR-1013-2** при 500–800 узлах | T-1727 решение + T-1732 проверка; F4 стабилизирует физику |
| R4 | STOP_LIST уберёт полезные узлы из центра | STOP_LIST **только к центрам**; периферия остаётся; тест T-1733 |
| R5 | Дублирование stop-list между F3 и F5 | Единая константа T-1730, переиспользование в F5 (T-1745) |
| R6 | Каталог-Δ конфликтует с F1/F6 | Δ=0 (код-константы) |
| R7 | Рост объёма сломает тесты графа 10.13/10.15 | T-1734 полный прогон; обновить ожидания диапазонов |
| R8 | **DDL v10 повредит данные/FTS/vec** | ADD COLUMN без rebuild; guard `table_info`; `user_version` вне guard; T-1775/T-1777 |
| R9 | **Порядок edge/fact даст NULL `fact_id` даже для новых рёбер** | T-1774 перестановка + `COALESCE`; тест заполненности |
| R10 | Backfill-соблазн исказит provenance | Осознанный NULL + `COALESCE`; backfill отклонён (ADR A7) |

**ADR:** обновлён — ADR-1018-3 (итерация 2: обязательная DDL v9→v10, legacy-NULL, обратный путь).

## 8. Feature flag / progressive delivery

- **Feature flag НЕ вводится** (решение **D7**): `flags.graph_scoring_v2_enabled` отклонён — каталог-Δ=0 и UPD владельца требуют активировать новую политику (Σ importance, STOP_LIST, ×2, 150/800/2400) сразу, без dead-code OFF-ветки. V2-скоринг/лимиты — безусловное поведение `graph_snapshot`/`memory_agi`.
- **Обязательный порядок:** DDL v10 + запись `fact_id` (T-1773/T-1774) и тесты миграции (T-1775) выполнены ДО включения новой выборки (иначе формула видит только NULL).
- **Rollback:** `git revert` + обратный путь DDL (spec §4.1b: `DROP INDEX idx_edges_fact_id` + `DROP COLUMN fact_id` при SQLite ≥3.35 + `PRAGMA user_version=9`; колонка безвредна). Feature-flag-переключения нет.

## 9. Handoff / деплой

`@Orchestrator` — план F3 готов. Спека/ADR — T-1727 (@Architect). Реализация — T-1728…T-1734 (@Builder). **Деплой (SSH pull + `.env` при необходимости + `systemctl restart admin_bot` + live-проверка графа) — отдельный шаг @DevOps. Пароль сервера в репозитории НЕ хранится.**

## 10. Фиксы аудита Батча 3 — S10.18-30 / S10.18-33 (15.09.2026, @Builder)

Закрыты находки §9 отчёта `plans/reports/round10.18_scanner_audit.md`. Скоуп не
расширялся; S10.18-31/-32/-34/-12/-13/-18/-19/-20 не трогались.

| ID | Уровень | Суть фикса | Файл:строка | Тест |
|---|---|---|---|---|
| **S10.18-30** | Medium | Delayout ×2-фазы: per-node `re.search(name, blob)` заменён на O(1) — токены блоба (`re.findall(r"[\wё]+", blob)`) строятся один раз, однословное имя → `name in token_set`, многословное → `f" {words} " in padded`. Границы токенов/ё→е сохранены (B3-4). Замер (15k рёбер/20k фактов/4k узлов/200 beliefs, blob 5 КБ, пул 2000): полный `graph_snapshot` **241 мс → 55 мс**, ×2-цикл **185 мс → 1.1 мс** | `services/database.py::graph_snapshot`, `_belief_name_participates` | `tests/test_graph_scoring_round1018.py::TestBeliefMultiplier` (substring/multiword) |
| **S10.18-33** | Info | `upsert_edge` при `cursor.rowcount == 0` (нет узла-источника) логирует WARNING — «факт без ребра» больше не молчит; транзакция не ломается (fail-open, B3-5) | `services/database.py::upsert_edge` | `tests/test_graph_scoring_round1018.py::TestFactIdWritePath::test_upsert_edge_missing_source_warns_fail_open` |

**Синхронизировано:** ADR-1018-3 D6 (бюджет ×2-фазы) и spec §4.4.
**Гейты:** `pytest` **6106 passed / 0 failed**; `node --check web/app.js` OK;
`JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` exit 0. Каталог-Δ=0.
Коммит/деплой — НЕ выполнялись.
