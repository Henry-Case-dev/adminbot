# MEM-08-S1 — контракт одного поискового ответа и карта сохранения старых фильтров

Статус: артефакт среза **S1** (аудит + контракт read-модели), не редизайн.
Авторитет: `plans/features/memory-cognitive-02/contracts.md` §4.2–§4.9, §6 C-6,
§9.5, §11 (`MEM-08-S2` = `web/api/cognitive_map.py` + `services/memory_search.py`);
ТЗ владельца `plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md`
§9.4 (MEM-08.14…MEM-08.28) и §9.5 (операции API).
Классификация Architect: **ARCH_REUSE_CONFIRMED** — новая форма ответа не
изобретается: DTO уже существуют в `services/memory_contracts.py` (MEMORY-01),
поиск идёт строго через существующий `services/mca_retrieval_context.py::retrieve`.

Три понятия, которые нельзя смешивать (§4.6, INV-15):

| Понятие | Идентификатор | Источник | Поиск |
|---|---|---|---|
| LOD-тайл раскладки | `agg:` (клиент) | клиентский `buildAggregates` | **никогда не результат** |
| Компонент связности | `cl:` (клиент) | клиентский `computeClusters` (union-find по рёбрам) | фильтр сцены, не поиск |
| Семантическое сообщество | `comm:<build_id>:<community_id>` | `mca_community_members` активной сборки | `ref_kind="community"` |

## 1. Ответ поиска (`SearchResponse`, §4.3)

Ручка: `GET /api/memory/search?q=…&chat_id=…&limit=…&cursor=…` (тело ответа —
`SearchResponse.as_dict()`, RBAC — как у остального Memory-API).
Форма — ровно `memory_contracts.SearchResponse` (без новых полей):

`status ∈ {ok, ambiguous, empty, legacy_only, partial, forbidden, error, cursor_stale}`,
`query_state ∈ {local_matches, server_searching, candidates, no_matches,
weak_legacy_only, partial, error, no_rights}`, `reason_code`, `items`,
`next_cursor`, `has_more`, `generation`, `scope{chat_id,mode,partial}`,
`revision{graph,alias,community_build,index_fingerprint}`, `debug` (admin-only,
без сырого текста переписки).

Допустимые пары `status`/`query_state` — взаимоисключающая матрица
`memory_contracts._OUTCOME_MATRIX` (валидируется в `__post_init__`, поэтому
подмена статуса на «пусто» технически невозможна).

Элемент выдачи (`SearchItem`): `ref_kind ∈ {entity,fact,episode,community,relation}`,
`canonical_id` (`ent:`/`fact:`/`episode:`/`comm:`/`edge:`), `legacy_ids`, `title`,
`category ∈ {Человек,Событие,Факт,Убеждение,Тема,Связь}`, `snippet` (≤
`preview_max_chars()`), `match_cause`, `evidence_status`, `event_ts`,
`observed_ts`, `focus{chat_id,node_id}|null`, `ambiguity{reason,variants}|null`.

### 1.1. Что отдаётся для сообщества (`ref_kind="community"`)

`canonical_id = "comm:<community_id>"` (build-скоуп не в ID: `community_id`
стабилен между rebuild, §6). В выдаче — только `community_id` из **активной**
сборки; `superseded`/`building`/`failed` в поиск не попадают.

Дополнительно к `SearchItem` сообщество описывается тем же блоком карты
(§2 ниже): `build_id`, `member_count`, `label`, `label_kind`, `label_basis`.
В `title` попадает подпись сообщества; при отсутствии семантической подписи —
нейтральное `Сообщество N` и `label_kind="neutral"` (никогда не выдаётся за
категорию).

## 2. Блок сообществ в payload карты (`GET /api/memory/cognitive-map`)

Payload-версия остаётся `cog-map/1`: блок **аддитивен**, все существующие поля
(`version`, `generated_at`, `state`, `scope`, `degraded`, `sources`, `caps`,
`shown_of`, `truncated`, `nodes`, `edges`) сохраняются байт-в-байт
(regression-фикстура `tests/fixtures/mem08/cognitive_map_payload_v1.json`).

```
"communities": {
  "state": "ok" | "no_active_build" | "unavailable",
  "reason_code": str|null,            # scope_global | tables_absent | no_active_build
  "build": {"build_id","algorithm","algorithm_version","graph_revision",
            "status","started_at","finished_at","node_count","edge_count",
            "prev_build_id"} | null,
  "items": [{
     "community_id": str,
     "member_count": int,             # реальный COUNT активной сборки
     "label": str,                    # «Сообщество: <имена>» либо «Сообщество N»
     "label_kind": "named" | "neutral",
     "label_basis": str,              # «как сформировано», без догадок
     "dominant_names": [str],
     "metrics": {"confirmed_links": int|null, "tentative_links": int|null,
                 "legacy_links": int|null, "cooccurrence_links": int|null,
                 "density": float|null, "last_activity": int|null},
     "metrics_basis": "full" | "partial" | "unknown"
  }],
  "total": int, "shown": int, "truncated": bool
}
```

Правила честности:
- блок читается **только** из `mca_community_builds.status='active'` того же
  чата; `LIMIT`-чтение, никакого полного скана;
- `member_count` — реальный `COUNT(*)`; отсутствующая метрика = `null`
  (в UI «Неизвестно»), а не `0`;
- подпись пересчитывается существующими `memory_communities.community_stats` /
  `community_label` только когда состав сообщества целиком помещается в
  bounded-чтение; иначе — нейтральная подпись + `label_basis`, объясняющий
  почему (`label_kind="neutral"`);
- подпись **не пересчитывается** и остаётся нейтральной, если в чате есть пары
  `mca_associations` (их вес входит в сборку, но read-модель повторяет только
  `edges`): иначе могла бы появиться категория, которой сборка не давала.
  Причина явно пишется в `label_basis`;
- LOD-тайлы (`agg:`) и компоненты (`cl:`) в этот блок не попадают никогда.

## 3. Три состояния сообществ (различаются явно)

| `communities.state` | Когда | `items` | `reason_code` |
|---|---|---|---|
| `unavailable` | таблиц `mca_community_*` нет (`v44` не применён) | `[]` | `tables_absent` |
| `no_active_build` | таблицы есть, активной сборки нет (или `chat_id=null` — глобальная область) | `[]` | `no_active_build` / `scope_global` |
| `ok` | есть ровно одна `active`-сборка чата | реальные сообщества | `null` |

Ни одно состояние не подменяется «пустым успехом»: UI показывает «Сообщества:
н/д» для `unavailable`, «Сообщества ещё не собраны» для `no_active_build` и
реальный список для `ok`. Ошибка чтения БД — существующий `degraded`
(источник `communities` = `not_loaded`), состояние при этом не «ok».

## 4. ACL и различение исходов (§4.7 S-3/S-4, §9.5)

| Ситуация | HTTP | `status` | `query_state` | `reason_code` |
|---|---|---|---|---|
| не глобальный admin | 403 | — (тело ошибки) | — | `permission denied` |
| прав на запрошенный чат нет | 200 | `forbidden` | `no_rights` | `no_rights` |
| поиск выполнен, совпадений нет | 200 | `empty` | `no_matches` | `retrieval_empty` |
| найдено только legacy без источника | 200 | `legacy_only` | `weak_legacy_only` | `legacy_only` |
| техническая ошибка поиска | 200 | `error` | `error` | `retrieval_error` |
| устаревший курсор (§4.9) | 200 | `cursor_stale` | `local_matches`/`candidates`/`partial` | `cursor_revision_mismatch` |
| невалидный `limit`/`q`/`cursor` | 400 | — | — | `invalid_limit` / `query_empty` / `invalid_cursor` |

`no_rights` ≠ `no_matches` ≠ `error`: разные статусы, разные `query_state`,
разные знаменатели метрик (`search_unauthorized_leaks` обязан быть 0,
`cursor_stale_rate` считается отдельно от `no_matches`).

Набор разрешённых чатов передаёт **владелец прав** (§4.4/§4.7 S-3):
`memory_search.search_memory(..., allowed_chat_ids=...)`. Сегодня Memory-API
доступен только глобальному администратору, поэтому эндпоинт передаёт
`None` («не ограничивает»), а `forbidden`/`no_rights` достижим, как только
владелец прав сузит набор (тест на этот путь — в наборе S2). Отсутствие
данных в разрешённом чате остаётся `no_matches`, а не `no_rights`.

## 5. Курсор и устаревание ревизии (§4.9)

Курсор — непрозрачная base64url-строка:
`{v:1, q:<sha1 нормализованного запроса>, s:<scope>, r:<fingerprint ревизии>, o:<offset>}`.
`r` = `sha1(graph|alias|index_fingerprint|community_build)`, где graph/alias —
дешёвые `COUNT(*)`+`MAX(id)` по `nodes`/`edges`/`mca_entity_canonical`,
`index_fingerprint` — активная генерация `graph_facts_vec`, `community_build` —
`build_id` активной сборки чата.

- страница отдаётся из одного bounded-пула `retrieve` (`limit ≤ 20`, §4.4);
  `has_more` ⇔ в пуле остались элементы, `next_cursor` при этом обязателен;
- несовпадение `r` → HTTP 200, `status="cursor_stale"`,
  `reason_code="cursor_revision_mismatch"`, `items=[]`, `next_cursor=null`;
  клиент молча начинает с первой страницы, пустое состояние не рисуется;
- несовпадение `q`/`s` в курсоре — не «устаревание», а ошибка клиента: 400
  `invalid_cursor` (устаревание относится только к ревизии данных).

## 6. Карта сохранения существующих фильтров (§4.10, MEM-08.28)

| Прежний элемент | Судьба в S2 | Где сохраняется |
|---|---|---|
| `chat_id` (область карты/поиска) | сохраняется как серверный scope | параметр эндпоинтов, `SearchScope` |
| `limit`/`top_k` | `limit` 1…20 только для `purpose='ui_search'` | валидация в `RetrievalRequest` |
| `mode`/`scope`/`time_from/time_to`/`participants` | без изменений | `RetrievalRequest`, retrieve |
| «Все типы» (`entity_type`) | в UI — контекстное действие; backend-параметр не удаляется | `channels`/`purpose` в retrieve |
| «Все кластеры» (клиентский `cl:`) | остаётся клиентским фильтром сцены | `web/static/cognitive-map.js` (не S2) |
| `GRAPH_MAX_NODES`/`GRAPH_MAX_EDGES`/`GRAPH_SEED_NODES` | не меняются | `web/api/memory_agi.py` |
| кнопка `Найти` / второе поле | заменяются на один omnibox только в S3 | S3 |

## 7. Границы этого артефакта

- Гейт `MCA_MEMORY_SEARCH_ENABLED` / `flags.memory_search_enabled` (§5.2,
  §4.10) в S2 **не регистрируется**: эндпоинт аддитивен и до S3 никем не
  вызывается, поэтому OFF-паритет сохраняется по построению. Регистрация гейта
  и его per-chat наследование — задача волны, подключающей клиент (S3).
- UI/omnibox, focus/expand (S3/S4) и независимый gold-set EVAL-07 (S5) в этом
  срезе не реализуются; S2 даёт только read-модель и её контрактные тесты.
