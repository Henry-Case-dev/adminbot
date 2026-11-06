# EPIC-MEMORY-COGNITIVE-02 — замороженные контракты (MEMORY-01…07, backend MEMORY-08)

**Статус:** решение Архитектора, вход для Builder. Один документ, без второго ADR.
**Источник:** `plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md` (sha256 `316893a9…0ed1`), карта `requirements-map.json` — read-only.
**Заменяет:** только раздел «поисковая панель» в `plans/features/evol/arch/cog-map-contract.md` (санкция §0/§9.4 ТЗ). Остальные части cog-map-contract (типы узлов, окно 800/2400, честные состояния, «нет второго хранилища») остаются в силе.

---

## 0. База реализации и границы

### 0.1. Реальная база — release-линия, не master

| Факт | Значение |
|---|---|
| Прод | `2.58.161` @ `a563ee31` (`release/2.58.161`), миграции до `v42` (`_SCHEMA_VERSION_SLOT_CLAIMS`) |
| `master` (локально) | своя линия: `max v37`, **нет** `web/api/cognitive_map.py`, `web/static/cognitive-map.js`, `services/chat_clock.py` |
| Аудит MEMORY-00 | выполнен на `8bb2800f` (линия master); выводы по reuse-поверхности совпадают с release, но UI/карта/часы существуют **только** на release |
| Дивергенция | `8bb2800f` не предок `a563ee31` (1068 коммитов разницы); между `8bb2800f` и локальным `HEAD` изменён только `requirements-map.json` |

**Решение:** весь эпик реализуется на release-линии (`release/2.58.161` → следующая версия). Все ссылки ниже — на символы этой линии (`module::symbol`), а не на номера строк. Реализация на master создала бы дубль карты и второй clock — запрещено.

### 0.2. Reuse-поверхность (адаптируем, не создаём)

| Механизм | Где | Используется контрактом |
|---|---|---|
| `nodes` / `edges`, `UNIQUE(chat_id, entity_name)`, `UNIQUE(source_id,target_id,relation_type)` | `services/database.py` | C-1 (точное имя = legacy-путь), C-2 (identity ребра = `edges.id`) |
| `upsert_node` (INSERT OR IGNORE), `upsert_edge` (weight cap 5, `fact_id` COALESCE) | `services/database.py` | C-2, C-3 (идемпотентность, вес ≠ истина) |
| `graph_snapshot` + `GRAPH_MAX_NODES=800` / `GRAPH_MAX_EDGES=2400` / `GRAPH_SEED_NODES=150` | `services/database.py`, `web/api/memory_agi.py` | **только рендер**; поиск их не использует |
| `mca_source_refs` / `mca_evidence_links` / `mca_provenance_status` + `provenance.py` | v17 | C-2: множественные основания ребра, статусы, независимость |
| `graph_facts`: `subject_ref_id`, `attribution_method`, `assertion_kind`, `speaker_author_id`, `perspective`, `memory_kind`, `scope`, `valid_from`, `valid_to`, `confidence_basis`, `revision`, `status`, `supersedes`, `weight`, `last_confirmed_at` | v12/v17/v31 | C-2, C-3 без новых колонок |
| `graphrag_provenance.validate_person_edge_write` / `classify_fact_provenance` / `independent_roots_count` / `plan_correction` | `services/graphrag_provenance.py` | C-2, C-3 (weight cap 0.55, confident/tentative/legacy) |
| `AliasResolver` / `LiveAliasView` / `build_alias_resolver` (каскад chat→global→nickname→username) | `services/summary_aliases.py` | C-1 (display-имена, mutable pointers), C-4 |
| `mca_retrieval_context`: `RetrievalRequest`/`RetrievalCandidate`/`RetrievalResult`, каналы exact/lexical/vector/reply_graph/episode, `apply_identity_prior`, `EvidenceBundle` | `services/mca_retrieval_context.py` | C-4 (единый retrieval, +1 канал) |
| `mca_episodes` / `mca_stories` (`event_start_ts`/`event_end_ts`) | v21 | C-3 (T_event из эпизода), C-4 |
| `mca_events` (`emit_mca_event`), `mca_trace` (`trace_id`) | v15 | наблюдаемость C-5 |
| `services/chat_clock.py`: `snapshot(chat_id, at_utc=…)`, `TimeSnapshot`, цепочка IANA-пояса | release | C-3 (относительные даты, DST/fold) |
| `chat_params.get_chat_param(chat_id, 'flags.x.y')` (chat override → global hot → default) + `param_catalog` `ParamSpec(pg_id="flags.…")` | `services/chat_params.py`, `services/param_catalog.py` | C-5 (global/chat inheritance без новых механизмов) |
| `task_jobs` (durable очередь, checkpoint) | v14 | C-5 (resume бэкфилла без новой таблицы) |
| `web/api/cognitive_map.py` + `web/static/cognitive-map.js` (`/api/memory/cognitive-map`, `PAYLOAD_VERSION`, `KINDS`, `computeClusters`, `GROUP_NEUTRAL_LABEL`) | release | C-4 (владелец map-API и UI-адаптера) |
| `mca_associations` (`analogy/motif/contrast/continuation`, `status='candidate'`) | v30 | C-2 (cooccurrence-гипотезы живут здесь, не в `edges`) |

### 0.3. Подтверждённые конфликты (что именно исправляем)

1. **`UNIQUE(chat_id, entity_name)` + точное сравнение** (`database::upsert_node`) → `Папаха`/`папаха` раздваиваются; типизированной канонической идентичности нет.
2. **`edges.fact_id` — одно основание**; путь `summary_memory::_write_graph_triplets` (крон-извлечение) пишет `fact_id=NULL` осознанно → у части рёбер обоснования нет вовсе, и это невидимо в UI.
3. **`summary_memory::_dedup_decide`**: cosine ≥ 0.95 → `noop`, `[0.85, 0.95)` → **`supersede`** (инвалидация старого факта по сходству векторов), ниже → `add`. Это прямое нарушение MEM-02.5/MEM-04.4/INV-06: сходство вектора не доказательство, а `noop` не даёт независимому повтору стать подтверждением.
4. **Caps 800/2400/150** — ограничения кадра; поиск по ним невозможен (`_graphSignature` + client-side `searchNodes` ищут только в загруженной сцене).
5. **Видимый toolbar**: в `web/index.html` (release) inline и fullscreen содержат `[input][Найти][Все типы][Все кластеры][Сбросить вид]`; клиентские фильтры `{kinds, scopes, chats, statuses, search, cluster}` живут в `cognitive-map.js`. Поиск — подстрока по `search`-блобу 800 узлов.
6. **«Группа · N»** (`GROUP_NEUTRAL_LABEL`, `computeClusters`) — пространственный кластер, не семантическое сообщество.

### 0.4. Запрещено создавать (проверяется ревью)

Neo4j / managed memory / второй граф / второе векторное пространство / вторая embedding-модель / второй identity-resolver / отдельная система доказательств / ещё одна LLM-генерация на сообщение / второй search-движок / новые колонки в `nodes`/`edges`/`graph_facts` / `DROP`/`CREATE` существующих таблиц / mass re-embed / переписывание prompt registry / hardcode имён, chat_id, alias, путей, версий ОС.

Аддитивная схема этого эпика — **ровно один шаг `v43`** (§6). Больше ничего.

---

## 1. C-1. Каноническая идентичность и `resolve_entity`

### 1.1. Структура

```python
EntityRef = {
  "chat_id": int,                  # обязателен: идентичность чат-квалифицирована
  "node_id": int,                  # nodes.id (стабильный, legacy-совместимый)
  "entity_type": "user"|"topic"|"event"|"fact",   # только существующий CHECK
  "display_name": str,             # текущее видимое имя (не переименовывает историю)
  "legacy_ids": [int],             # node_id, сведённые в этот канонический (аддитивно)
  "aliases": [str],                # все орфографии из member-узлов + alias-карты
}

EntityResolution = {
  "status": "resolved"|"ambiguous"|"new"|"rejected",
  "canonical": EntityRef|None,
  "candidates": [{"ref": EntityRef, "reason": str, "discriminator": str}],  # ≥2 при ambiguous
  "reason_code": str,
  "normalized_mention": str,       # диагностика, НЕ ключ
  "scope": {"chat_id": int, "entity_type": str},
}

async def resolve_entity(
    *, scope: {"chat_id": int, "entity_type": str},
       mention: str,
       stable_identity: {"kind": "tg_user", "value": int} | None = None,
       evidence: {"source_ref_ids": tuple[int, ...],
                  "episode_id": str | None} | None = None,
       allow_create: bool = False,
) -> EntityResolution
```

Вызов доступен извлечению, retrieval и UI. `allow_create=False` для всех read-путей (UI/поиск/карточки): «новой» сущности не создаётся, `new` означает «ничего не найдено, было бы новой».

### 1.2. Порядок разрешения (первое решающее правило выигрывает)

1. `stable_identity.kind='tg_user'` → активная строка `mca_entity_canonical` (`resolution='self'`, `stable_kind='tg_user'`, `stable_value=str(value)`) в этом чате → `resolved`. Две активные строки → `ambiguous` (дефект данных, честно).
2. Подтверждённый alias: mention совпадает с alias-картой (`limits.summary_aliases`: chat → global) для `user_id` U, и в чате есть узел `Canon(U)` → `resolved` (это уже действующий каскад `AliasResolver`).
3. Точное имя: `nodes(chat_id, entity_name = mention)` → `resolved` (**legacy-путь байт-в-байт как `upsert_node`**).
4. Кандидаты по casefold: все узлы `(chat_id, entity_type)`, где `casefold(trim(NFC(mention)))` равен нормализованному имени узла. Ровно один → `resolved`, `reason_code='casefold_unique'`, `confidence='tentative'`. Больше одного → `ambiguous`.
5. Redirect: у найденного кандидата есть активная строка `mca_entity_canonical` → `resolved` в канонический (legacy-id продолжает резолвиться).
6. Иначе → `new` (`allow_create` не пишет; создание — только на write-пути извлечения через существующий `upsert_node`).
7. `rejected`: `entity_type` вне четырёх; пустой/пробельный mention; mention > 200 символов; scope без прав (ACL) — **не** `new`.

### 1.3. Инварианты

- **ID-1. Только чтение.** Резолвер ничего не пишет: ни узлов, ни redirect-строк, ни evidence.
- **ID-2. Чат-квалификация.** Никогда не возвращает узел другого чата. Общий (админский) обзор возвращает **сгруппированные по чату** результаты, никогда не одну слитую личность (INV-05).
- **ID-3. Никогда не сливает.** `MERGE` — отдельная явная операция (админ/бэкфилл, §5), не следствие резолва.
- **ID-4. Casefold — только кандидаты.** Unicode-нормализация, trim, casefold, варианты кавычек, падежи, транслитерация **не** доказывают тождество и не выполняют слияние. Оригинальное написание и видимые алиасы сохраняются.
- **ID-5. Никакого возвышения типа.** Термин из текста не становится Telegram-пользователем; `entity_type='user'` — только при реальной identity (ID/алиас-карта/evidence).
- **ID-6. Якорь пользователя — Telegram user ID**, alias/nickname — изменяемые указатели. Смена ника не переписывает evidence (source refs хранят author id, не имя).
- **ID-7. Детерминизм.** Ответ зависит только от `(scope, entity_type, mention, stable_identity, graph_revision, alias_revision)`; кэш обязан включать обе ревизии.
- **ID-8. Неоднозначность — данные, не выбор.** При `ambiguous` — ≥2 реальных варианта с различающим признаком (тип/чат/период/источник/degree). Автовыбор «самого популярного» запрещён.

### 1.4. Как legacy-узлы продолжают резолвиться

`nodes` не переписываются и не удаляются. Слияние = **добавление строки** `mca_entity_canonical` (`member_node_id` → `canonical_node_id`, `status='active'`), после чего:
- чтение и запись отношений резолвят `node_id` → канонический через одну таблицу;
- member-узел остаётся в БД со своим `id` и написанием → старые `edges.source_id/target_id`, `graph_facts.subject_ref_id`, `mca_source_refs.entity_id` остаются валидны;
- откат = `status='revoked'` (или удаление строк) — данные не теряются;
- `graph_snapshot`/`build_cognitive_map` схлопывают member→canonical **на чтении** и суммируют рёбра по `(canonical_source, canonical_target, relation_type)`; дубли в выдаче не появляются, история не теряется.

### 1.5. Адаптер

Новый тонкий модуль `services/entity_resolver.py` (**read-only фасад**, никакого своего хранилища и своей alias-карты): делегирует `summary_aliases.AliasResolver`/`current_alias_resolver` за display-именами, `nodes`/`mca_entity_canonical` за идентичностью. Это расширение существующего разрешения алиасов (INV-03), а не второй резолвер: собственных таблиц, кэшей идентичности и правил приоритета у него нет.

### 1.6. Запрещено

Второй словарь алиасов; `entities`-таблица, дублирующая `nodes`; UUID-идентичность; `UNIQUE`-индекс по casefold(name); автоматическая транслитерация/лемматизация как доказательство; векторная кластеризация как identity; «канонизация» через `lower()` всех имён.

### 1.7. Dual-read / rollback

Гейт `MCA_MEMORY_IDENTITY_ENABLED` + `flags.memory_identity_enabled` (per chat). OFF → вызывающие используют сегодняшний точный путь (эквивалент правила 3). ON → правила 1–7. Обе ветки читают одни таблицы; новые таблицы OFF-ветка не читает. Откат: гейт OFF; затем `status='revoked'` для слияний.

### 1.8. Идемпотентность

Резолвер — чистая функция. Слияние: PK `(chat_id, entity_type, member_node_id)`; повторный dry-run даёт тот же список кандидатов; повторное применение — no-op.

### 1.9. Обязательные тесты (негативные/мутационные)

| # | Сценарий | Ожидание |
|---|---|---|
| T1 | `Папаха`/`папаха` — один человек, есть evidence | один канонический узел, обе формы резолвятся, legacy node_id валиден |
| T2 | `папаха` (предмет) и `Папаха` (человек), 2 узла, нет redirect | `ambiguous`, 2 варианта, **никакого** автослияния |
| T3 | Ник «Саша» у двух людей | `ambiguous` |
| T4 | Один алиас в двух чатах | два независимых результата, кросс-чат не резолвится |
| T5 | Смена ника | резолв по новому алиасу; старые source refs/узлы не изменены |
| T6 | Упоминание в цитате | резолвится объект цитаты, не пересылающий (атрибуция в C-2) |
| T7 | Имя темы = имя человека | типы не смешиваются (`entity_type` фильтр) |
| T8 | `bot_self_reply` | имя бота не становится `user`-узлом |
| T9 | Редактированный/удалённый исходник | резолв не падает, evidence помечается как недоступный |
| T10 | 100 повторов одного запроса | идентичный результат; 0 ложных персональных слияний в полном прогоне (нулевая терпимость) |
| M1 | Мутация: убрать проверку уникальности casefold-кандидатов | T2/T3 обязаны упасть |

---

## 2. C-2. Ребро, подтверждённое несколькими независимыми источниками

### 2.1. Логическое представление (всё выводится, ничего не дублируется в БД)

```python
RelationView = {
  "edge_id": int, "chat_id": int,
  "source_entity_id": int, "target_entity_id": int,   # канонические после C-1
  "relation_type": str, "relation_label": str,        # русское человеческое имя
  "direction": "directed",                            # edges всегда направлены
  "origin_class": str,          # самый слабый класс из sources (см. 2.2)
  "sources": [{
      "source_ref_id": int, "fact_id": int|None,
      "kind": "message"|"graph_fact"|"episode"|"bot_output",
      "origin_class": str, "assertion_mode": str,     # asserted/quoted/reported/inferred/denied/hypothetical/joking/unknown
      "speaker": str|None, "subject": str|None,        # раздельны (INV-07)
      "event_ts": int|None, "observed_ts": int|None,
      "verification": str, "independence": str, "method": str,
      "established_at": int,
  }],
  "independent_support": int,   # provenance.evidence_independent_count(links)
  "frequency": int,             # edges.weight — частота, НЕ истина
  "status": "confirmed"|"tentative"|"unverified"|"contradicted"|"superseded"|"rejected",
  "valid_from": int|None, "valid_to": int|None, "last_confirmed": int|None,
  "confidence_basis": str|None,
  "explanation": str,           # «А упомянул Б в сообщении X (дата)», «А утверждал о связи с Б»,
                                # «гипотеза из N совпадений», «Происхождение не установлено»
  "revision": {"graph": str, "edge_updated_at": int},
}
```

### 2.2. Классы происхождения — выводятся из существующих полей

| Класс | Правило вывода (первое совпадение) |
|---|---|
`quote_forward` | `smart_messages.is_forward=1` / `forward_from != ''` **или** `graph_facts.perspective='quoted'`
`reported_third_party` | `perspective='third_party'` **или** `attribution_method='third_party'`
`explicit_direct` | `perspective='self'` **и** `attribution_method IN ('self_report','direct_evidence')`
`derived_with_lineage` | `provenance_channel IN ('dream','dossier_layer_a','dossier_layer_b')` **или** evidence-link `derived_from` (обязателен `basis`/`method` с правилом вывода)
`cooccurrence` | только `mca_associations` (в `edges` не пишется вовсе)
`legacy_unknown` | `edges.fact_id IS NULL` и нет ни одной evidence-связи, либо сигналов нет

Правило конфликта: `edge.origin_class` = **самый слабый** класс среди источников (лестница выше читается сверху вниз как «слабее → сильнее»: `legacy_unknown < cooccurrence < derived_with_lineage < quote_forward < reported_third_party < explicit_direct`). Каждый источник при этом показывает свой класс отдельно.

Модальность `assertion_mode`: из `graph_facts.assertion_kind`/`perspective`; отсутствующий сигнал → `unknown`, **не** `asserted`.

### 2.3. Как одно ребро несёт много источников

Одна строка `edges` + N строк `mca_evidence_links`, где `subject_ref_id` указывает на **SourceRef самого ребра**:

```
mca_source_refs(store='sqlite', entity_type='graph_edge', entity_id=str(edges.id), chat_id, revision=graph_rev)
   ↑ subject_ref_id
mca_evidence_links(source_ref_id = SourceRef сообщения / факта / эпизода,
                   link_type ∈ derived_from|supports|contradicts|mentions|supersedes,
                   verification ∈ verified|tentative|rejected|unknown,
                   independence ∈ independent|self_referential|unknown,
                   claim_key, method, basis, checks_json, established_at)
```

Требуемое изменение кода (без схемы): расширить `services/provenance.py::ENTITY_TYPES` значениями `"graph_edge"` и `"entity"` и добавить конструкторы `graph_edge_source_ref(chat_id, edge_id)` / `node_source_ref(chat_id, node_id)`. Дедуп-индексы `mca_source_refs` (`store,entity_type,entity_id,chat,revision`) и `mca_evidence_links` (`subject,source,link_type,claim_key`) уже обеспечивают идемпотентность.

**`edges.fact_id` сохраняется как совместимое поле** (одиночное основание для скоринга `COALESCE(importance, weight)` в `graph_snapshot`); новые писатели продолжают его заполнять, дополнительные основания идут в `mca_evidence_links`.

**Минимальная аддитивная связка `edge_id` НЕ создаётся:** существующая схема адресует ребро (SourceRef с `entity_type='graph_edge'`), значит условие MEM-03.2 «если технически не поддерживает» не наступило. Второй таблицы доказательств нет.

### 2.4. Инварианты

- **R-1.** `status='confirmed'` ⟹ ≥1 evidence-link с `verification='verified'` и разрешимым источником. Проверяется на чтении API и на записи.
- **R-2.** Вес/частота никогда не меняют `status` и `origin_class`. `weight` = подтверждения с cap 5 (существующий `_EDGE_WEIGHT_CAP`), отображается как «частота».
- **R-3.** Собственный вывод бота не corroborates сам себя: `provenance.is_self_referential_origin`, `origin='bot_direct_reply'`, `mca_bot_outputs` → `independence='self_referential'`; в `independent_support` не входит.
- **R-4.** Повторный репост/пересказ того же корня не добавляет независимости (тот же `source_ref_id`).
- **R-5.** Ложная транзитивность запрещена: `A–B` и `B–C` **никогда** не дают `A–C`. `derived_with_lineage` — только с явной семантикой предиката и цепочкой ссылок.
- **R-6.** Cooccurrence/соседство на экране/сходство эмбеддингов не создают типизированное ребро.
- **R-7.** Legacy bare-edge не удаляется и не скрывается, показывается как «Происхождение не установлено», не попадает в confident-контекст, вес ограничен 0.55 (`validate_person_edge_write`).
- **R-8.** Противоречие/устаревание — только аддитивно (evidence-link + `mca_provenance_status`); физического удаления и `DELETE` нет.
- **R-9.** Направление и авторство сохраняются: содержание пересылки приписывается первоисточнику, не переславшему (`quote_forward`).
- **R-10.** Merge узлов переносит **наборы доказательств** без потери ни одного `fact_id`, веса, периода, авторства, оспоренного статуса (MEM-02.6).

### 2.5. Dual-read / rollback / идемпотентность

- OFF (`MCA_RELATION_EVIDENCE_ENABLED` + `flags.relation_evidence_enabled`) → пишем как сегодня (`fact_id`, без edge-refs), читаем как сегодня. ON → дополнительно пишем/читаем edge-evidence; старые читатели (`graph_snapshot`, legacy API) не меняются.
- Откат: гейт OFF; edge-ref строки остаются инертными (старый код их не читает); удаление не требуется.
- Идемпотентность: перед `upsert_edge` проверяется наличие link `(edge_ref, source_ref)`; если есть — `weight_increment=0` и **без** сброса `last_updated` (новый аддитивный параметр `touch_recency: bool = True` у `upsert_edge`). Повторная экстракция того же сообщения не накачивает вес (SC-08).

### 2.6. Обязательные тесты

Ребро с 3 источниками показывает все 3 и `independent_support=3`; тот же источник дважды → 1; self-output не подтверждает; репост не подтверждает; legacy-ребро (`fact_id NULL`) — «происхождение не установлено» + вес ≤0.55; `A–B`,`B–C` не дают `A–C` (негатив); cooccurrence не появляется в `edges`; противоречивое ребро показывает обе стороны; карточка ребра открывается по `edge_id` и содержит кликабельные исходники; повторный прогон извлечения не меняет вес (мутация: убрать проверку link → тест падает).

---

## 3. C-3. Время, эволюция и политика обслуживания

### 3.1. Три различных мгновения (не смешивать)

| Понятие | Источник | Правило |
|---|---|---|
**T_assertion** — когда утверждение произнесено | `smart_messages.sent_at`/`timestamp`, `mca_source_refs.tg_message_id` → сообщение | используется для разрешения относительных дат |
**T_event** — время утверждаемой действительности | `graph_facts.valid_from/valid_to`; иначе `mca_episodes.event_start_ts/event_end_ts` связанного эпизода | только если источник это поддерживает; иначе `NULL` |
**T_observed** — когда записано в память | `graph_facts.created_at`, `mca_source_refs.created_at`, `mca_evidence_links.established_at`, `edges.last_updated` | никогда не выдаётся за T_event |

Жёстко: **отсутствующая дата ≠ timestamp сообщения ≠ `time.time()`**.

### 3.2. Относительные даты

«вчера», «сегодня», «через неделю» разрешаются **от T_assertion** через `services/chat_clock.py::snapshot(chat_id, at_utc=T_assertion)` (per-chat IANA, DST/fold-корректно, цепочка `limits.chat_timezone` → legacy → global → factory). Глобального фиксированного пояса нет. Историческое сообщение, переработанное позже, интерпретируется по своему мгновению, не по времени запуска воркера. Неизвестный пояс → `timezone_source='utc_fallback'` и это **видно** в карточке («часовой пояс неизвестен, UTC»).

### 3.3. `supersedes` без разрушения

`graph_facts.supersedes` + `database::invalidate_graph_fact` + `database::log_fact_compression` + `mca_provenance_status.freshness_status='superseded'`. Старая строка сохраняется целиком вместе с источниками; закрытие `valid_to` ставится по T_assertion новой поправки, **не** по «сейчас»; если противоречие объяснимо разными периодами/сферами — хранятся обе версии (пример: «раньше работал там, теперь здесь» — не ошибка).

### 3.4. Единая политика решений

Реализуется в `summary_memory::_dedup_decide` (единственная точка решения) с `graphrag_provenance::plan_correction` для отрицаний/поправок.

| Решение | Условие | Запись |
|---|---|---|
**ADD** | нет кандидата с тем же `(chat, canonical subject, predicate, object)` и той же identity | новый факт + ребро + evidence-link |
**ENRICH** | то же утверждение, новые **пустые** метаданные (период/область/база уверенности) | UPDATE только `NULL`-полей + evidence-link; non-NULL не перезаписывается |
**CONFIRM** | то же утверждение, **независимый корень** (`source_ref_id` новый, не self-output) | +1 evidence-link (`verification='verified'`, `independence='independent'`), `last_confirmed_at=now`, вес ребра +1 (cap 5) |
**SUPERSEDE** | тот же субъект+предикат, **другое** значение, с собственным источником | новый факт (`supersedes=old`), старый инвалидируется штатным механизмом, `valid_to` = T_assertion новой поправки |
**CONTRADICT** | явное отрицание/поправка (`claim_envelope.is_deny_phrase`/`is_correction_phrase`, `plan_correction`) | link `contradicts`, `verification='tentative'`, `conflict_status='conflicting'`; без переключения истинности до разрешения |
**NOOP** | тот же корень (`source_ref_id` + revision) повторно | **ноль** записей: ни веса, ни `last_updated`, ни `last_confirmed_at` |

**Изменение поведения (гейтировано):** cosine-полосы `_dedup_decide` перестают быть доказательством.
- `cosine ≥ 0.95` больше **не** даёт `noop` (иначе независимый повтор теряется);
- `cosine ∈ [0.85, 0.95)` больше **не** даёт `supersede` (инвалидация по сходству запрещена);
- при гейте ON сходство даёт только событие `dedupe_candidate` с id ближайшего кандидата; решение остаётся ADD, если не совпали identity+assertion (тогда CONFIRM) или не сменилось значение (тогда SUPERSEDE) или нет отрицания (CONTRADICT).
- Принятое следствие: больше «похожих» фактов в БД вместо уничтожения; митигация — диагностика `dedupe_candidate` + dry-run слияний (MEM-02.6), а не удаление.
- Гейт OFF → точный прежний расчёт (паритет), данные не трогаются.

### 3.5. Консолидация (сон/саммари/опыт/досье)

Обобщение допускается только из повторяющихся независимых сигналов, с обязательным lineage (`source_ids`, evidence-links) и разграничением `observation` (оперативное) / `stable_trait` (долговременное) / `bot_belief` (гипотеза). Одна ссора, мем, шутка или роль в ролевой игре не закрепляется как постоянное свойство. Старое/редкое не стирается ради квот; hot-context управляется вероятностью вызова, архивный поиск сохраняется (кроме штатных delete/forget и политик retention).

### 3.6. Dual-read / rollback / идемпотентность

Гейт `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` + `flags.memory_maintenance_policy_enabled`. OFF → `_dedup_decide` как сегодня. Откат: гейт OFF. Идемпотентность: NOOP-правило + уникальные индексы evidence-links + проверка «этот корень уже связан».

### 3.7. Обязательные тесты

`valid_from` ставится только при поддержке источником; отсутствующая дата ≠ T_assertion ≠ now; «вчера» через границу DST и после смены пояса чата; историческое сообщение, переработанное позже, сохраняет своё разрешение; поправка сохраняет старую строку и её источники; ENRICH не перезаписывает non-NULL; NOOP не повышает вес; CONFIRM только при независимом корне; cosine-полоса не инвалидирует (мутация: вернуть старый `supersede` → тест падает); противоречие доступно с обеих сторон.

---

## 4. C-4. Единый read-only поиск для одного поля карты

### 4.1. Ручка

Одна, на владельце map-API (`web/api/cognitive_map.py`, тот же `_require_global_admin`/`_db_or_503`):

```
GET /api/memory/search?q=<str>&chat_id=<int?>&cursor=<str?>&generation=<int>&limit=<int<=20>
```

- `q`: 1…200 символов, без спецсинтаксиса. **Нет** параметров `kind`/`type`/`cluster`/`status` — клиент не классифицирует заранее.
- `chat_id`: сервер сам определяет допустимый scope из прав (`_require_global_admin` + известный набор чатов); чужой/неразрешённый → `403 scope_forbidden` (не пустой результат). URL/`startapp` права не расширяют.
- `cursor`: opaque base64url `{bucket, score_q, canonical_id, rev}`; `rev = (graph_revision, alias_revision, index_fingerprint)`; при несовпадении `rev` → `status='cursor_stale'`, items=[], клиент начинает с первой страницы.
- `generation`: монотонный клиентский счётчик; сервер **эхо**-возвращает; клиент отбрасывает ответы с `generation < max_seen` (SC-26).

Существующие детальные ручки добавляются тем же владельцем, сохраняя старые параметрические фильтры для совместимости:
`GET /api/memory/entity/{node_id}`, `/entity/{node_id}/neighbors?kinds=&depth=&cursor=`, `/edge/{edge_id}`, `/community/{build_id}/{community_id}`, `/diagnostics/missing-link?from=&to=`.
`GET /api/memory/graph` и `/api/memory/cognitive-map` остаются, новые поля аддитивны.

### 4.2. `SearchIntent` (только на сервере)

```python
SearchIntent = {
  "q": str, "scope": {"chat_id": int|None, "mode": "chat"|"scope_all"},
  "intents": [{"kind": "person"|"fact"|"event"|"belief"|"relation"|"topic"|"time"|"unknown", "weight": float}],
  "subjects": [EntityRef], "ambiguous_subjects": [EntityResolution],
  "terms": [str], "quoted": [str],
  "time_hint": {"from": int, "to": int, "tz_source": str} | None,
  "mode": "specific"|"episodic"|"thematic",
}
```
Интент — **подсказка ранжированию, не фильтр**. Низкая уверенность/многозначность → смешанная выдача. Тип результата берётся из данных, не из классификатора. Никакого LLM: интент собирается детерминированно из алиасов/сущностей, FTS-термов, `is_history_query`, `chat_clock` (для «вчера»), явных реляционных маркеров.

### 4.3. `SearchResult`

```python
SearchItem = {
  "ref_kind": "entity"|"fact"|"episode"|"community"|"relation",
  "canonical_id": str,            # ent:<chat>:<node>, fact:<id>, episode:<id>,
                                  # edge:<id>, comm:<build>:<id>
  "legacy_ids": [str],
  "title": str,                   # человеческое название из данных
  "category": "Человек"|"Событие"|"Факт"|"Убеждение"|"Тема"|"Связь",
  "snippet": str|None,            # ≤400 симв. (существующий _PREVIEW_MAX_CHARS), ACL-проверено
  "match_cause": "exact_name"|"alias"|"casefold"|"fts"|"semantic"|"temporal"|"relation_path"|"community",
  "evidence_status": "confirmed"|"tentative"|"legacy"|"contradicted"|"unknown",
  "event_ts": int|None, "observed_ts": int|None,
  "focus": {"chat_id": int, "node_id": int} | None,   # None для факта без узла — честно
  "ambiguity": {"reason": str, "variants": [{"canonical_id": str, "title": str, "discriminator": str}]} | None,
}
SearchResponse = {
  "status": "ok"|"ambiguous"|"empty"|"legacy_only"|"partial"|"forbidden"|"error"|"cursor_stale",
  "query_state": "local_matches"|"server_searching"|"candidates"|"no_matches"|
                 "weak_legacy_only"|"partial"|"error"|"no_rights",
  "items": [SearchItem], "next_cursor": str|None, "has_more": bool, "generation": int,
  "scope": {"chat_id": int|None, "mode": str, "partial": bool},
  "revision": {"graph": str, "alias": str, "community_build": str|None, "index_fingerprint": str},
  "debug": {"channels": [...], "why_ranked": [...]} | None,   # admin-only, без сырого текста
}
```

### 4.4. Ранжирование

Пул кандидатов из каналов (каждый — bounded SQL, не полный скан): exact/alias/identity, lexical/FTS (`smart_messages_fts`, `graph_facts_fts`, `smart_archive_facts_fts`), semantic (существующие embeddings через `MemoryManager`, текущая модель/поколение), episodes (`mca_episodes`/`mca_stories`/`lore_stories`), relation (1 hop, 2 hop только по обоснованному запросу), community (membership сборки). Слияние — существующая детерминированная агрегация `_CHANNEL_WEIGHTS` + новый канал `entity` (предлагаемый вес 90, между exact и lexical) + `apply_identity_prior`. Точная идентичность и chat scope приоритетны, но правило «слово совпало → остальное отбрасываем» запрещено.

**Typed reranker (`apply_retrieval_rerank`) в поиске не вызывается** (он может быть LLM-backed): UI-поиск обязан быть без LLM. Диагностика `why_ranked` — вклад каналов, без текста переписки.

### 4.5. Полный охват, независимый от 800/2400

Поиск и обход используют таблицы целиком (`nodes`, `edges`, `graph_facts`, FTS, vec, эпизоды, community-membership) с `LIMIT`/keyset-пагинацией. `graph_snapshot`/`GRAPH_MAX_*` — **только** начальное окно сцены; константы не меняются. Результат за пределами сцены: `focus` → ego-network 1 hop → вставка в сцену без полной перезагрузки → центрирование → `Назад` возвращает viewport/selection (MEM-08.3/08.21).

### 4.6. Сообщества vs LOD-тайлы (жёсткое разделение)

`community` — backend-сборка по реальным узлам/рёбрам в chat scope (см. C-6), стабильный `build_id`, `member_count`, `label_basis`; API отдаёт `ref_kind='community'`. Пространственные LOD-тайлы (`computeClusters`, «Группа · N») остаются **клиентской** техникой рендера, никогда не приходят из API как «сообщество» и не дают поисковых результатов. `entity_id` никогда не меняется из-за раскладки.

### 4.7. Инварианты

- **S-1.** Один backend-вход на один client input; второго поискового движка/endpoint-конкурента нет.
- **S-2.** Ноль LLM-вызовов на поиск и на символ; ноль re-embed; ноль мутаций памяти (никаких merge/recompute/backfill/extract из запроса).
- **S-3.** ACL проверяется до ответа, включая server-кэш, client-кэш и «недавние запросы»; кэш ключуется scope+revision и не разделяется между чатами.
- **S-4.** `no_rights` ≠ `no_matches` ≠ `error`; «нет совпадений» означает завершённый поиск в разрешённом scope с понятным описанием.
- **S-5.** Неоднозначность показывается вариантами, «самый популярный» не выбирается; отсутствие источника — «Источник не указан».
- **S-6.** Пустой ввод — обычный обзор, без выдуманных подсказок/историй.
- **S-7.** Никаких утечек внутренних ID/score/«кластер 139»/raw-троек в основную выдачу.
- **S-8.** Один state/компонент для inline и fullscreen; второй `input` запрещён.

### 4.8. Производительность (критерии измерения, не обещания)

Локальная реакция ≤100 мс (desktop, следующий кадр); server p95 ≤500 мс в прогретом прогоне; client p95 ≤800 мс без эмуляции сети; 6–8 первых результатов без скачка layout; debounce 120–180 мс; отдельно cold/Android/real network. Превышение — дефект с профилированием SQLite/индексов/scoring/рендера, а не «спиннер».

### 4.9. Dual-read / rollback / идемпотентность

Гейт `MCA_MEMORY_SEARCH_ENABLED` + `flags.memory_search_enabled`. ON → новое поле; OFF → прежний toolbar (`Найти`/`Все типы`/`Все кластеры`) и клиентский поиск по сцене. Поиск read-only → идемпотентен по определению; пагинация детерминирована при неизменной `rev`.

### 4.10. Обязательные тесты

Gold-set ≥60 запросов (EVAL-07) со всеми интентами и `(query, expected typed refs, допустимые альтернативы, scope, evidence, expected ambiguity/none)`; top-1/Recall@5/MRR/precision for relations; узел за пределами 800 находится и фокусируется; пагинация через 2+ страницы без дублей/пропусков; `cursor_stale` при смене rev; гонка `Пап`→`Папаха` (ответ в обратном порядке не перетирает); ACL-негатив (чужой чат не возвращается, не-админ 403); отсутствие LLM-вызовов (счётчик не растёт); отсутствие полного скана (план запроса/инструментация); отсутствие утечек ID/текста; `no_rights`/`no_matches`/`error` различимы (мутация: подменить статус → тест падает).

---

## 5. C-5. Миграция, гейты, бэкфилл, выпуск

### 5.1. Схема — ровно один аддитивный шаг `v43`

**`mca_entity_canonical`** (идентичность/редирект, обратимо):
```
chat_id INTEGER NOT NULL, entity_type TEXT NOT NULL,
member_node_id INTEGER NOT NULL,        -- nodes.id как есть
canonical_node_id INTEGER NOT NULL,     -- = member для resolution='self'
resolution TEXT NOT NULL,               -- 'self'|'alias'|'merged'
stable_kind TEXT,                       -- 'tg_user' | NULL
stable_value TEXT,                      -- '428494' | NULL
method TEXT NOT NULL,                   -- 'alias_map'|'explicit_evidence'|'manual_admin'
evidence_ref_id INTEGER,                -- mca_source_refs.source_ref_id
confidence TEXT NOT NULL,               -- 'confirmed'|'tentative'
status TEXT NOT NULL DEFAULT 'active',  -- 'active'|'revoked'
created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
PRIMARY KEY (chat_id, entity_type, member_node_id)
```
Индексы: `(chat_id, entity_type, stable_kind, stable_value) WHERE status='active'`; `(chat_id, canonical_node_id)`.

**`mca_community_builds`** (реестр сборок сообществ):
```
build_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL,
algorithm TEXT NOT NULL, algorithm_version TEXT NOT NULL,
params_json TEXT NOT NULL DEFAULT '{}',
graph_revision TEXT NOT NULL,
node_count INTEGER NOT NULL, edge_count INTEGER NOT NULL,
prev_build_id TEXT, change_summary_json TEXT NOT NULL DEFAULT '{}',
status TEXT NOT NULL,                   -- 'building'|'active'|'superseded'|'failed'
started_at INTEGER NOT NULL, finished_at INTEGER
```
Индекс: `(chat_id, status, started_at DESC)`.

**`mca_community_members`**:
```
chat_id INTEGER NOT NULL, build_id TEXT NOT NULL,
community_id TEXT NOT NULL, node_id INTEGER NOT NULL,
member_weight REAL NOT NULL DEFAULT 1.0, created_at INTEGER NOT NULL,
PRIMARY KEY (chat_id, build_id, community_id, node_id)
```
Индексы: `(chat_id, build_id, node_id)`, `(chat_id, build_id, community_id)`.

Ничего больше: **никаких** новых колонок в `nodes`/`edges`/`graph_facts`, никакой таблицы доказательств, никакой таблицы чекпоинтов (см. 5.3), никакого кэша поиска в БД. Все три таблицы — `CREATE … IF NOT EXISTS` под self-guard, `ALTER` не нужен, старый код их не читает, `PG` — no-op (memory-контур SQLite-only, как v28/v30).

### 5.2. Гейты (существующий реестр, global/chat inheritance)

| Гейт (env-аварийный) | Каталог (product) | Что включает |
|---|---|---|
`MCA_MEMORY_IDENTITY_ENABLED` | `flags.memory_identity_enabled` | C-1 read-резолвер, чтение redirect'ов |
`MCA_RELATION_EVIDENCE_ENABLED` | `flags.relation_evidence_enabled` | C-2 запись/чтение edge-evidence |
`MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` | `flags.memory_maintenance_policy_enabled` | C-3 политика решений |
`MCA_MEMORY_SEARCH_ENABLED` | `flags.memory_search_enabled` | C-4 ручка + новое поле карты |
`MCA_MEMORY_COMMUNITIES_ENABLED` | `flags.memory_communities_enabled` | C-6 сборка/чтение сообществ |
`MCA_MEMORY_BACKFILL_ENABLED` | `flags.memory_backfill_enabled` | бэкфилл (default OFF до замеров) |

Эффективность: `settings`-атрибут (per-call, аварийный) **AND** `await chat_params.get_chat_param(chat_id, "flags.…")` (chat override → global hot → default). Дефолт у всех — **OFF до приёмки**, включение штатным релизом по PET_PROJECT (никаких канареек по чатам). Скрытых «включено по умолчанию» нет.

### 5.3. Бэкфилл (ограниченный, с чекпоинтами)

Baseline ДО миграции: `VACUUM INTO`-бэкап, `PRAGMA integrity_check`, версия схемы, `COUNT(*)` по ключевым таблицам, fingerprint/поколение embedding-индекса, hash-паритет активных промптов. Тест миграции — на копии.

| Шаг | Объём | Запись | Чекпоинт/resume |
|---|---|---|---|
B1 | dry-run кандидатов дублей по чату/типу/алиасу/источнику; отчёт: кандидатов/подтверждено/сомнительно/влияние на ссылки | **никакой** | `task_jobs.payload` |
B2 | только безопасно подтверждённые слияния (явный evidence), по чату, в транзакции | `mca_entity_canonical` | per-chat checkpoint, idempotent rerun |
B3 | evidence для рёбер с `fact_id`: копия `(source_ref_id, verification, independence)` из связей факта, `method='metadata'`, `claim_key='edge_from_fact'` | `mca_source_refs`+`mca_evidence_links` | per-chat/dataset курсор |
B4 | сборка сообществ по чатам, батчами | `mca_community_*` | per-chat build_id |
B5 | ничего не делает с: текстами фактов, `vec0`/`graph_facts_vec`, embeddings, старыми ID, промптами | — | — |

Правила: только изменённые/конфликтные категории; отсутствующее обоснование **нельзя** доделать выдуманным LLM-источником — остаётся `legacy_unknown`; изоляция сбоев по чатам; пауза/возобновление существующим supervisor; тяжёлая операция никогда не запускается из UI-запроса; повтор не удваивает вес.

### 5.4. Откат

Флаги OFF (поведение baseline, прежний UI) → при необходимости предыдущий релиз по SHA. Схема деструктивно не откатывается: новые таблицы инертны для старого кода. Слияния отменяются `status='revoked'`. Данные не удаляются.

### 5.5. Добавочная нагрузка

Ноль обязательных LLM-вызовов на сообщение (все новые решения детерминированы); ноль новых LLM на поиск; запись — только там, где уже идёт извлечение/обслуживание.

---

## 6. C-6. Семантические сообщества (backend, версионируемые)

- Считаются по реальным узлам/рёбрам в chat scope, вход не ограничен экранными 697/800/150.
- Веса рёбер: `confirmed` = 1.0, `tentative` = 0.5, `legacy_unknown` = 0.25, `cooccurrence` (из `mca_associations`) = 0.1; параметры — централизованные константы с тестами, algorithm/version пишутся в `mca_community_builds`.
- Запуск асинхронный/пакетный (по изменениям + периодическое восстановление drift), никогда на `/status`, `/menu`, ответ, zoom/pan. Планировщик — существующий `memory_maintenance` (не новый воркер).
- Подпись: из реально доминирующих сущностей/тем с источниками; иначе нейтральное `Сообщество N` + «как сформировано». LLM-наименования на горячем пути нет.
- `community_id` стабилен, пока сборка активна (перезагрузка/мелкие изменения не меняют ID); split/merge фиксируются в `change_summary_json`; `entity_id` от раскладки не меняется никогда.
- API отличает community от render-tile; `member_count`, `confirmed/tentative` доли, `last_activity`, `density` — из настоящих метрик, неизвестное = «Неизвестно».

Тесты: сборка по реальным данным (не по совпадению имён/близости), устойчивость ID при повторной сборке без изменений, split/merge описан, отсутствие сборки на горячем пути (счётчик запусков), `cooccurrence` не повышает плотность как подтверждённое ребро.

---

## 7. Наблюдаемость

События — только `emit_mca_event` (`mca_events`), поля `trace_id, chat_id, kind, outcome, reason_code, duration_ms, counts, config_version`; **без** сырого текста, токенов, `initData`, ПДн (R17).

`entity_resolution`, `merge_decision`, `assertion_recorded`, `edge_evidence_attached`, `edge_legacy`, `conflict_detected`, `dedupe_candidate`, `memory_retrieved`, `memory_rejected`, `context_selected`, `community_refresh`, `map_search`, `map_neighbors`, `backfill_checkpoint`.

Метрики с знаменателем: доля рёбер с источником; доля `legacy/unverified`; merge candidates/confirmed/false merges; ambiguities; search `query_to_first_local`, `query_to_first_server`, `p50/p95`, `top1/Recall@5/MRR`, `wrong_entity_rate`, `ambiguity_coverage`, `stale_result_suppression`, `offscene_hit_rate`, `search_unauthorized_leaks` (обязан быть 0), DB query plan, фоновые LLM-вызовы (обязаны быть 0 на поиск/сообщение). Нет данных → «Не измерялось», не 0/OK.

Трасса одного ответа (для админа): запрос → разрешённая личность → кандидаты → почему выбраны/исключены → подтверждающие SourceRef → что ушло в L2 → что доставлено. Внутренние ID в текст бота не попадают.

---

## 8. Visual Preservation Map (только то, что меняется)

Сцена проверяется реальным рендером (Playwright + Browser Use) до и после; ниже — контракт для Builder.

| BLOCK | Сейчас | ACTION | MUST PRESERVE | ALLOWED CHANGE | WHY |
|---|---|---|---|---|---|
Inline-карта в «Статусе» (`status-graph`), строка поиска | `[input «Поиск по имени или алиасу…»][Найти][Все типы][Все кластеры][Сбросить вид][статус]` | **REDESIGN** (санкция §9.4) | рамка карточки, glass, строка счётчиков, кнопка `Полный экран`, сам canvas | один input `Найти в памяти` / плейсхолдер `Человек, событие, факт или вопрос…`, иконка+`×`+индикатор внутри поля, панель до 6–8 результатов; `Сбросить вид` → иконка/контекст сцены; типы/кластеры → контекстные действия инспектора | владелец требует ровно одно поле, без обязательной кнопки |
Fullscreen-панель (`graphFullPanel`) | тот же toolbar целиком | **REFINE** | полноэкранный режим, back-stack, safe-area, один state с inline | тот же компонент/состояние, без второго `input` и без дублирующих контролов | SC-21/SC-28 |
Сцена/физика/LOD (`cognitive-map.js`, `lodFor`, гистерезис, `reducedMotion`, mobile simple) | витрина 800/2400, кластеры «Группа · N» | **KEEP** | пороги, гистерезис, физика после стабилизации, mobile-упрощение, dispose RAF/listeners | только подсветка выбранного/пути; никакой смены семантики | INV-15, MEM-08.7/08.8 |
Инспектор узла/ребра | name/type/group/degree, соседи | **REFINE** | существующие бейджи, кнопки, карточка источника | + алиасы, статус идентификации, эпизоды, «Источник/Происхождение не установлено», для ребра — sources/validity/independent_support | MEM-08.9, C-2 |
Счётчики | «N узлов · M рёбер · показаны не все» | **REFINE** | вторичный тон, компактность, честное `truncated` | `В памяти: N сущностей и M связей` / `Показано: n и m` / `Область` / `Сообщества` / `Данные обновлены`; неизвестное = «Неизвестно» | MEM-08.5 |
Легенда типов | `groups` vis-network | **KEEP** | категории, доступность в карточках | сворачиваемая/контекстная | MEM-08.24 |
Четыре ленты ниже карты (убеждения/цепочка/таймлайн/уроки) | работают | **KEEP** | порядок, данные, карточки, источники | ничего | INV-15 |

Жёстко запрещено: второй поисковый `input` (в т.ч. в fullscreen); прежняя многопольная форма под иконкой «расширенный поиск»; превращение «Группа · N» в «сообщество»; выдуманные узлы/рёбра; «красивое» переупорядочивание лент; donut/radial для категорий без знаменателя.

Ответственность saga-состояний (MEM-08.23) в UI: `empty_input`(обзор) → `local_matches` → `server_searching` → `candidates` | `ambiguous` | `no_matches` | `weak_legacy_only` | `partial` | `error/offline` | `no_rights`; локальный отклик показывается сразу и никогда не выдаётся за полный серверный поиск.

---

## 9. Параллелизация и write-scopes

После принятия этого документа.

| Срез | Можно начинать | Зависит | Файлы (write scope) | Класс |
|---|---|---|---|---|
MEMORY-01 (типы/контракт в коде: `EntityRef`, `RelationView`, `SearchItem`) | сразу | — | `services/memory_contracts.py` (новый) | `PARALLEL_SAFE` |
MEMORY-02 (identity, resolver, слияния) | сразу | C-1 | `services/entity_resolver.py` (новый), `services/summary_aliases.py` (read-extension) | `BLOCKED_BY:schema_v43_part_A` |
MEMORY-03 (edge-evidence) | сразу | C-2 | `services/provenance.py`, `services/graphrag_provenance.py`, `services/relation_evidence.py` (новый) | `PARALLEL_SAFE` |
MEMORY-04 (temporal/политика) | после 01 | C-3, C-1 | `services/summary_memory.py`, `services/graphrag_provenance.py` | `SERIALIZE` (`summary_memory.py`) |
MEMORY-05 (соц/эпизод/мультимодал) | после 03+04 | C-2/C-3 | `services/summary_memory.py`, `services/mca_episodes.py`, `services/mca_vision.py` | `SERIALIZE` (`summary_memory.py`) |
MEMORY-06 (единый retrieval) | после 02+03+04 | C-4 backend | `services/mca_retrieval_context.py`, `services/direct_context_composer.py` | `SERIALIZE` (`mca_retrieval_context.py`) |
MEMORY-07 (сообщества) | после 02+03 | C-6 | `services/memory_communities.py` (новый), `services/memory_maintenance.py` (регистрация job) | `BLOCKED_BY:schema_v43_part_B` |
MEM-08-S2 (backend поиск) | после 06 | C-4 | `web/api/cognitive_map.py`, `services/memory_search.py` (новый) | `SERIALIZE` (`cognitive_map.py`) |
MEM-08-S3 (omnibox UI) | после согласования формы ответа S2 | C-4 | `web/app.js`, `web/index.html`, `web/static/cognitive-map.js` | `SERIALIZE` (один UI-писатель) |
MEM-08-S4 (focus/expand/offscreen) | после S2+S3 | C-4 | `web/app.js`, `web/static/cognitive-map.js` | `SERIALIZE` |
MEM-08-S5 (EVAL-07) | после S1–S4 | — | `tests/`, evidence | `READ_ONLY_PARALLEL` |
MEMORY-09 (телеметрия/бэкфилл/выпуск) | параллельно с 02 | C-5 | `services/mca_events.py` (только новые имена), backfill-модуль | `PARALLEL_SAFE` |
MENU-01 | уже идёт независимо | — | `handlers/menu.py` | `READ_ONLY_PARALLEL` к памяти; **не** писать `web/index.html` одновременно с UI-лейном |

**Сериализуемые точки (ровно по одному владельцу в момент времени):**
`services/database.py` (вся схема v43 + `upsert_edge(touch_recency)`), `services/summary_memory.py`, `services/summary_aliases.py`, `services/mca_retrieval_context.py`, `web/api/memory_agi.py`, `web/api/cognitive_map.py`, `web/app.js`, `web/index.html`, `web/static/cognitive-map.js`.

**Порядок слияния:** `database.py` (v43 part A/B) → identity/evidence (02/03) → retrieval (06) → API поиск (S2) → UI (S3/S4) → сообщества-UI/EVAL (S5). Максимум 3 одновременных писателя, у каждого — непересекающийся scope.

---

## 10. Приёмочные обязательства (сводно)

Нулевая терпимость (release blocker, EVAL-04): одно подтверждённое ложное автослияние двух Telegram user ID в gold; утечка памяти чужого чата; «подтверждённая» связь без источника; потеря исходного SourceRef/legacy-id; выдуманная связь в UI; полная перестройка embeddings без смены модели; изменение сохранённых промптов; новый обязательный LLM-вызов на ход; вторая поисковая форма/строка.

Обязательные доказательства: gold-set ≥200 размеченных проверок (EVAL-01/02), отдельный search-gold ≥60 (EVAL-07), A/B baseline vs кандидат с зафиксированными SHA/настройками/индексами, реальные p50/p95 и скриншоты/запись desktop+Android, мутационные тесты по каждому контракту, независимая проверка Reviewer на реальных SQL/данных, а не на заглушках.

---

## 11. Остались ли продуктовые решения владельцу

**Нет.** Проверено по правилу Human Gate:

1. Единственное поле поиска уже выбрано владельцем (MEM-08.14/SC-21) — это не развилка.
2. Выпуск без канареек и разрешений на флаг — стоячее решение PET_PROJECT; отдельное согласие не требуется.
3. Смена семантики `_dedup_decide` (сходство вектора перестаёт инвалидировать факты) — не новый выбор, а прямое следствие требований MEM-02.5/MEM-04.4/INV-06 («не уничтожать по сходству»). Цена — больше похожих записей вместо удаления; это совместимо с INV-01/EVAL-05 и не меняет пользовательское поведение бота иначе как честнее.
4. Никаких новых затрат, хранения ПДн, необратимых операций или интероп-решений контракт не вводит; единственная внешняя зависимость эпика (BotFather для MENU-01) к памяти не относится и уже учтена.
