# W7-S1 — «Когнитивная карта»: данные и клиентский адаптер (отчёт Builder)

Слайс: `EVOL-COG-MAP` / `W7-S1` (`GET /api/memory/cognitive-map` + модель/фильтры/
камера/аллокатор подписей + офлайн-тесты). UI остаётся на текущем рендерере.
Основание: `plans/features/evol/arch/cog-map-contract.md` §2/§5/§6 (заморожено),
`plans/current_task.md` §2.3 (строки 1263–1274), строки `EVOL-COG-MAP` в
`plans/features/evol/requirements-map.json`.

Ветка `feat/cog-map-s1`, база `2ed8966e`. Коммиты: `770f53c1` (код + тесты),
`f49dd125` (отчёт), `48b21ace` (ревью — Needs Fixes, B1), далее — правка B1
(см. §9).

## 1. Что добавлено (и чего не тронуто)

| Файл | Статус | Роль |
|---|---|---|
| `web/api/cognitive_map.py` | новый | `GET /api/memory/cognitive-map` + `build_cognitive_map(db, chat_id)` |
| `web/static/cognitive-map.js` | новый | чистый адаптер (нормализация/фильтры/камера/подписи) |
| `web/app.py` | +5 строк | одна регистрация `include_router(cognitive_map_router, prefix="/api")` |
| `tests/test_evol_cog_map_api.py` | новый | 23 pytest-теста эндпоинта и модели |
| `tests/js/evol_cognitive_map_test.js` | новый | 407 node-проверок адаптера |

Не тронуто: `web/index.html`, `web/app.js`, `web/static/app.css`,
`services/database.py`, `web/api/memory_agi.py`, `web/api/routes.py`
(byte-freeze F11 держится), `requirements-map.json`, `progress_scope.json`,
`workflow_state.md`. Новых зависимостей нет (vis-network уже вендорен и в
адаптере не используется).

## 2. Контракт эндпоинта

`GET /api/memory/cognitive-map?chat_id=<int|отсутствует>` — только глобальный
admin (та же зависимость, что у остального Memory-API:
`get_tma_user` + `_require_global_admin`). `chat_id` — область: конкретный чат
(`scope.mode="chat"`) либо глобальный агрегат администратора
(`scope.mode="global"`); узлы при этом ВСЕГДА чат-квалифицированы.

Ответ (JSON, `version = "cog-map/1"`):

```jsonc
{
  "version": "cog-map/1",
  "generated_at": <epoch>,
  "state": "ok" | "partial" | "empty" | "degraded",
  "scope": {"mode": "chat"|"global", "chat_id": <int|null>},
  "degraded": {"active": false, "not_loaded": ["<имя источника>"]},
  "sources": {"facts": "loaded"|"not_loaded", "graph": ..., "edges": ..., ...},
  "caps": {"nodes": 800, "edges": 2400, "per_class": 150,
           "classes": 4, "entity_nodes": <150..800>},
  "shown_of": {"nodes": N, "edges": M,
               "by_kind": {"fact": {"shown": n, "total": t, "truncated": b}, ...},
               "totals": {"nodes": <сколько всего>, "edges": <сколько всего>},
               "unresolved_refs": <ссылки, не связанные из-за cap>},
  "truncated": {"nodes": b, "edges": b,
                "by_class": {"fact": b, "belief": b, "paradigm": b,
                             "evolution": b, "entity": b}},
  "nodes": [ /* см. ниже */ ],
  "edges": [ /* см. ниже */ ]
}
```

Узел (`nodes[]`):

```jsonc
{
  "id": "fact:<chat>:<id>" | "belief:<chat>:<id>" | "paradigm:<chat>:<id>"
      | "obs:<chat>:<id>"
      | "evt:<chat>:revision:<id>"
      | "evt:<chat|global>:dream:<id>"   // chat_id=0 → system → global
      | "ent:<chat>:<nodes.id>",
  "kind": "entity"|"fact"|"belief"|"paradigm"|"observation"|"evolution_event",
  "scope": "chat"|"global", "chat_id": <int|null>,
  "title": "<короткая подпись>", "text": "<полный текст|null>",
  "status": "<из БД|null>",
  "isolated": true|false,           // нет ни одного подтверждённого ребра
  "time": {"occurred_at": <|null>, "observed_at": <|null>, "saved_at": <|null>,
           "confirmed_at": <|null>, "updated_at": <|null>},
  "provenance": {...},              // record/chat_id/message_id/origin/source_ids...
  "metrics": {"importance": <|null>, "weight": <|null>, "degree": <|null>},
  "refs": {...}                     // supersedes/source_ids/new_fact_id/...
}
```

Ребро (`edges[]`): `{id, from, to, relation, kind: "recorded"|"derived",
derived: bool, chat_id, justification_recorded: bool, provenance{...}}`.
`justification_recorded=false` + `provenance.fact_id=null` — «обоснование не
записано» (текст для карточки рисует S3, не сервер).

Раздельные времена: `occurred_at` ← `message_timestamp` (когда произошло),
`observed_at` ← `mca_trait_observations.observed_at`, `saved_at` ← `created_at`,
`confirmed_at` ← `last_confirmed_at`, `updated_at` ← только `edges.last_updated`
(там, где запись реально обновляется). Отсутствующее — `null`, «0 вместо даты»
не подставляется. `confidence`/`strength`/`freshness` не рассчитываются и в
payload отсутствуют.

Типы рёбер: записанные `edges.relation_type`; `derived_from` — по
`edges.fact_id` (факт, породивший связь) и по `graph_facts.source_ids`
(убеждение/парадигма ← свои факты); `revised_by` — по
`graph_facts.supersedes`. Новых типов не выдумывается.

## 3. Источники и границы (только существующее, без второго хранилища)

| Что | Источник | Запрос/граница |
|---|---|---|
| Топология сущностей и рёбра | `db.graph_snapshot` (не меняется) | `max_nodes = 800 − когнитивные`, `max_edges = 2400`, `seed_nodes = 150`; сироты/stoplist/score — как есть |
| `fact` / `belief` / `paradigm` | `graph_facts` | по одному запросу на класс, `LIMIT 151`, `COUNT(*) OVER()` = полный размер класса |
| `observation` | `mca_trait_observations` | `LIMIT 151`, `ORDER BY observed_at DESC, id DESC` |
| `evolution_event` | `graph_facts.supersedes`, `memory_dream_log` (`distilled`/`resurrect`/`decay_run`/`deep_run`) | ≤151 строк на источник, класс обрезается до 150 |
| Provenance рёбер | `edges.fact_id/origin/created_at/last_updated/weight` | один запрос `IN` по показанным сущностям (≤800 параметров), `LIMIT 2401` |
| «Показано X из Y» | счётчики `COUNT(*)`/окно | 6 дешёвых запросов, индексные фильтры (`chat_id, kind` и т.п.) |

Бюджет: 4 когнитивных класса × 150 = ≤600 узлов; сущностям — остаток
(`max(150, 800 − когнитивные)`), поэтому суммарно ≤800. Рёбра ≤2400.
Порядок обрезки фиксирован: класс → `importance DESC, created_at DESC, id DESC`
→ cap; для класса «эволюция» — по времени события, затем id. Внутри «эволюции»
`observation`, `evolution_event` и ревизии `supersedes` делят один лимит 150.
Неограниченных выборок, N+1 и запросов на раскрытие узла нет. LLM/эмбеддингов
нет (§2 контракта).

**Правило полноты (одно на все шесть классов и на рёбра):**
`by_kind[kind].truncated == (total > shown)`; `truncated.nodes` — сводка
`any(...)` по классам, `truncated.edges == (edge_total > shown_edges)` (или
упор в cap). Поэтому `state="ok"` невозможен, когда показана часть данных:
снапшот, вернувший окрестность 150 сидов из 850 сущностей, даёт
`shown=152, total=850`, `truncated=true`, `state="partial"`.

## 4. Изоляция, scope, права, деградация

* **Изоляция чатов** — доказано тестами: при `chat_id=A` в payload нет ни
  одного узла чужого чата (проверяется `chat_id` каждого узла и префикс `id`),
  а не «скрытие» на клиенте. Ключ узла всегда содержит chat: `fact:<chat>:<id>`,
  `ent:<chat>:<nodes.id>`, `obs:<chat>:<id>`, `evt:<chat>:...`.
* **Одинаковые имена не сливаются**: в глобальном агрегате два «Хаб» из разных
  чатов дают два узла с разными id — тест `test_same_names_do_not_merge_in_global`.
* **Глобальная область** — только явным отсутствием `chat_id`, помечена
  `scope.mode="global"`; тот же RBAC (глобальный admin).
* **Системные записи** — `memory_dream_log.chat_id = 0` (глобальный `decay_run`)
  не выдаётся за «чат 0»: узел `evt:global:dream:<id>` со `scope="global"` и
  `chat_id=null`; в карту конкретного чата он не попадает.
* **Права** — 401 без initData, 403 не-админу (HTTP-проверки через TestClient)
  и 403 при прямом вызове с не-админом.
* **Деградация** — падение источника не роняет ответ: `state="degraded"`,
  `degraded.not_loaded=[имена]`, `sources[имя]="not_loaded"`, остальные данные
  остаются. `empty` (источники прочитаны, данных нет) и `not_loaded` (чтение
  упало) различимы по `state` и `sources`. Новых reason-кодов не введено.
  Отсутствие БД — прежний 503 (`_db_or_503`), как у остального Memory-API.

## 5. Клиентский адаптер (`web/static/cognitive-map.js`)

Zero-build, CSP `self`, без inline/CDN, по образцу `execution_graph.js`;
экспортируется как `window.CognitiveMap` и через `module.exports` в node.
Чистые функции (без DOM, без vis-network, без сети):

* `normalizePayload(payload, {aliases})` → модель: snake_case → camelCase,
  `kind` вне списка → `other`, узлы без `id` отбрасываются, рёбра без обоих
  концов отбрасываются (концы не дорисовываются), `degree`/`isolated`
  пересчитываются по принятым рёбрам, версия payload проверяется
  (`version_missing`/`version_mismatch` в `warnings`), битый ответ не бросает;
* `searchNodes(model, query)` — по названию и алиасу (`aliases` из
  `summaryAliasesMap`), нормализация регистра/`ё→е`/пробелов, многословный
  запрос, детерминированная сортировка;
* `applyFilters(model, {kinds, scopes, chats, statuses, search, hideIsolated})` —
  ребро остаётся только если оба конца прошли фильтр (иначе связь не
  рисуется вообще), возвращает честные счётчики; `scopes: ['global']` отделяет
  системные/глобальные записи от чатовых (`chats: [null]` — совместимый алиас);
* камера: `createCamera/clampCamera/cameraFromNetwork/cameraToNetwork/
  cameraEquals` (сохранение/восстановление позиции и масштаба в пределах сессии);
* `allocateLabels(items, opts)` — экранное разрешение коллизий: приоритет
  (выбранный → парадигма → убеждение → факт → сущность → наблюдение →
  изменение → degree → длина → id), жадная расстановка без пересечений, обрезка
  за вьюпорт, LOD (`overview` < 0.55 → ≤6 подписей, `normal` → ≤16, `detail` →
  ≤26; мобильный потолок 12 — визуальные константы, не квоты данных);
* `kindSummary(model)` — данные для обязательной легенды и «показано X из Y».

Детерминизм проверяется сравнением двух прогонов и отсутствием
`Math.random`/`Date`/сети в коде модуля.

## 6. Тесты

`tests/test_evol_cog_map_api.py` — **23 passed** (реальная in-memory SQLite, без
сети/Telegram/LLM; HTTP-часть — TestClient со стабом БД, чтобы aiosqlite не
переезжал между event-loop'ами):

* изоляция чатов и глобальный агрегат с одинаковыми именами (2);
* форма payload, честность узлов (типы id, раздельные времена, provenance,
  отсутствие псевдо-метрик), рёбра с provenance и без выдуманных связей,
  только реальные записи эволюции (4);
* caps/truncation: 160 фактов → 150 показано, `total=160`, порядок обрезки,
  `state="partial"`; **300 сущностей цепочкой → снапшот отдаёт окрестность
  152 → `partial` с честным `by_kind.entity{shown:152,total:300,truncated}`;
  маленький полностью загруженный чат → `ok`; сирота-сущность → честный
  `partial`** (5);
* `empty` ≠ `degraded`, падение конкретного источника, системный `decay_run`
  с `chat_id=0` не выдан за «чат 0» (4);
* RBAC 401/403/200, проброс `chat_id`, 403 в самом эндпоинте (4);
* пин-тест: `/api/memory/graph` (ключи `nodes/edges/truncated/limits`, форма
  узлов/рёбер) и `/api/memory/stats` (10 ключей, реальные счётчики) не
  изменились (1);
* статические инварианты: ровно одна регистрация роутера, в API нет
  `CREATE TABLE/INSERT/UPDATE/DELETE`, эмбеддингов и LLM, топология — из
  `graph_snapshot`, cap-константы на месте (2).

`tests/js/evol_cognitive_map_test.js` — **407 проверок**, маркер
`EVOL-COG-MAP-S1-OK checks=407`: отсутствие DOM/сети/vis-network в модуле;
нормализация (включая битый payload, незнакомый kind, `not_loaded`);
поиск по названию и алиасу; фильтры с разрывом рёбер и счётчиками; камера;
аллокатор (детерминизм, попарное отсутствие пересечений, LOD-пороги, потолки
26/12, обрезка за вьюпорт, узел без координат); сводка для легенды.

**Проверено, что тесты умеют падать** (мутации, обе откатаны):
`_take(fact_rows, COG_CLASS_LIMIT + 1)` → красный
`test_fact_class_truncated_by_importance`; `picked[from] || picked[to]` в JS →
красный тест про разрыв рёбер фильтром.

**Чего тесты НЕ доказывают:** живую плотность/производительность на реальных
данных (356 узлов / 2400 рёбер), размер payload на проде, поведение
рендерера (его ещё нет в этом слайсе), реальный `EXPLAIN QUERY PLAN` на
прод-копии, эндпоинт на проде в обоих чатах и global (живая проверка — шаг
S2/S4, контракт §6 «живой read-only»).

Попутно найдено и исправлено тестами: `_ts()` (фильтр «> 0») обнулял
отрицательные `chat_id` Telegram → введён отдельный `_int_or_none`;
`by_kind.entity.total` складывал все классы вместо числа сущностей.

## 7. Что нужно S2 (данные уже готовы)

1. Заменить `GET /api/memory/graph` на `cognitive-map` в виджете «Статус»,
   сохранив маршрут `#/status/graph` и позицию в сетке; удалить legacy-рендер.
2. Использовать `CognitiveMap.normalizePayload` + `allocateLabels` (слой
   подписей — `nodes.font.size=0` + `afterDrawing`, DataSet не мутировать).
3. Легенда/«показано X из Y» — из `kindSummary` и `shown_of`; состояния
   `empty/partial/degraded` рисуются по `state` + `degraded.not_loaded`.
4. Проверить размер ответа и `EXPLAIN QUERY PLAN` на прод-копии (контракт §5).
5. Переиспользовать `provenance.message_id`/`chat_id` для «Открыть источник»,
   `refs.supersedes`/`source_ids` — для «Истории изменений» (S3).

## 8. Вопросы Architect до S2 (не блокируют S1)

1. **Названия легенды.** В адаптере сейчас: «Сущности/Факты/Убеждения/
   Парадигмы/Наблюдения/Изменения». Контракт §2.2 говорит «Эволюция характера».
   Нужно зафиксировать RU-подписи, иначе S2 (легенда) и S3 (карточка) разойдутся.
2. **`state` сервера vs состояния рендерера.** Сервер отдаёт
   `ok/partial/empty/degraded`; `not_loaded` (vis-network не загружен), `stale`,
   `renderer_failed` остаются клиентскими. Подтвердить, что это разделение
   финальное (и что `stale` считается по `generated_at` на клиенте).
3. **Приоритет внутри класса «эволюция» (150 узлов).** Сейчас — по времени
   события; при большом числе наблюдений события сна вытесняются. Подтвердить
   порядок (время против «сначала события, потом наблюдения»).
4. **`deep_traits`.** Не включён (контракт перечисляет только
   `distilled/resurrect/decay_run/deep_run`). Подтвердить исключение.
5. **`unresolved_refs`.** Счётчик ссылок, не связанных из-за cap. Нужно
   решение, показывать ли его пользователю отдельной строкой («часть связей
   не загружена»), или это только диагностика.
6. **Полный текст в payload.** Узлы отдают `text` целиком (карточке S3 он
   нужен). Если на проде это тяжёлый ответ, нужно решение: оставить как есть
   или догружать текст карточки отдельно — это уже контракт, а не деталь.

## 9. Правка после ревью W7-S1 (B1) — честность полноты

Ревью: `plans/features/evol/reports/w7-s1-review.md` §5 (B1). Замечание
подтверждено: до правки в чате с 850 сущностями снапшот возвращал окрестность
150 сидов, и ответ объявлял `state="ok"`, `truncated.nodes=false`,
`by_kind.entity={"shown":152,"total":850,"truncated":false}` при
`shown_of.totals.nodes=850`. Пять остальных классов считали полноту по
`total > shown`, то есть одно и то же поле означало разное, а S2 по контракту
§4 включает «показано X из Y» только при `partial/truncated` — карта была бы
подана как полная.

**Новое правило (одно на все шесть классов и на рёбра):**

| Поле | Значение |
|---|---|
| `by_kind[kind].truncated` | `total > shown` (для `entity` — `entity_total > shown_entities`, страховка `snapshot.truncated`) |
| `truncated.nodes` | `any(by_kind[*].truncated)` — сводка, а не отдельное мнение |
| `truncated.edges` | `edge_total > shown_edges` ИЛИ упор в `GRAPH_MAX_EDGES` |
| `truncated.by_class.*` | значения `by_kind` (`evolution` — класс целиком: `evolution_cut` или любой из двух видов) |
| `state` | `degraded` → `empty` → `partial` (если `truncated.nodes/edges`) → `ok` |

Следствие: `state="ok"` теперь означает «показано всё, что есть в области».
Сирота-сущность (снапшот её отбрасывает) тоже даёт `partial` — это правда:
узел есть в БД и не показан. Форма payload и `version="cog-map/1"` не менялись:
изменились только значения (и это ровно то, что требовалось).

**Воспроизведение (300 сущностей в цепочке, чат `-3003`):**

| | до правки | после |
|---|---|---|
| `by_kind.entity` | `{shown:152,total:300,truncated:false}` | `{shown:152,total:300,truncated:true}` |
| `truncated.nodes` / `by_class.entity` | `false` / `false` | `true` / `true` |
| `truncated.edges` (151 из 299) | `false` | `true` |
| `state` | `ok` | `partial` |

**Маленькая фикстура остаётся `ok`** (обратная сторона правила, чтобы
`partial` не превратился в «всегда»): чат из двух связанных сущностей и одного
факта → `state="ok"`, `by_kind.entity={shown:2,total:2,truncated:false}`,
`totals.nodes == len(nodes)`, `totals.edges == len(edges)`.

**Тесты, закрепляющие B1** (все падают при откате правки — проверено мутацией
`by_kind.entity.truncated = bool(snapshot.truncated)`: краснеют
`test_entity_neighbourhood_is_reported_partial` и
`test_orphan_entity_is_reported_honestly`):

* `test_entity_neighbourhood_is_reported_partial` — 300 цепочкой: `shown < total`,
  `truncated` по классу/узлам/рёбрам, `state="partial"`;
* `test_fully_loaded_small_chat_is_ok` — маленький полный чат остаётся `ok`;
* `test_orphan_entity_is_reported_honestly` — сирота-сущность не выдаётся за
  полную карту.

**`evt:0:dream:*` (мелкое замечание ревью, исправлено — дешево):**
`memory_dream_log.chat_id = 0` — системный прогон (`decay_run`), а не «чат 0».
Теперь такой узел: `id = evt:global:dream:<id>`, `scope="global"`,
`chat_id=null`, `provenance.chat_id=null`; в карту конкретного чата он не
попадает. Новых полей и reason-кодов нет. Тест
`test_global_decay_run_is_not_chat_zero`. Заодно `_scope_key(None)` даёт
`global` вместо `?` (наблюдения без чата).

**Фильтр области в адаптере (то же замечание):** добавлен явный
`applyFilters(model, {scopes: ['chat'|'global']})`; `chats: [null]` сохранён
как совместимый алиас. Проверено в node-тесте (3 проверки).

**Прогоны после правки** (кандидат — коммит этой правки на `feat/cog-map-s1`):

| Команда | Результат |
|---|---|
| `pytest tests/test_evol_cog_map_api.py -q` | 23 passed |
| `pytest tests/test_webapp_api.py tests/test_webapp_memory_overview_api.py tests/test_webapp_round1015_graph.py tests/test_smoke_round1016_graph.py -q` | 218 passed (вместе с новыми) |
| `node tests/js/evol_cognitive_map_test.js` | `EVOL-COG-MAP-S1-OK checks=407` |

Не изменилось и остаётся `UNVERIFIED` (как в §6): живой ответ прода, размер
payload, `EXPLAIN QUERY PLAN`, рендер (S2+).
