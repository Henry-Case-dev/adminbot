# `mca-03-message-identity` — спецификация (Step 2 @Architect, T-3779)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 1** (данные). **Фича-ID:** `mca-03-message-identity`.
- **Тип:** backend/data — логическая идентичность сообщений, поля/время/версии, роли/алиасы, миграция `chat_id`. **P0-предпосылка** для `mca-04a` (provenance) → `mca-07` (retrieval) и далее (`mca-05`/`mca-08`/`mca-15`/`mca-18`/`mca-19`/`mca-20`).
- **Источник (IMMUTABLE, R17/R18):** `plans/current_task.md` v1.8 **§7** (`:180–198`), §3/§3.1 (`:45–75`), §4 (`:77–101`), §17.1–§17.3 (`:818–846`), §18 (`:856–872`), §19 **A07/A08/A11/A88** (`:888`,`:889`,`:892`,`:969`), §22 (`:1062–1077`).
- **Задачи:** `tasks.md` T-3777…T-3797. **Приёмки:** A07, A08, A11, A88.
- **ADR:** `adr-1027-4-message-identity.md` (D1–D12). **Рамка:** `plans/docs/mca-round1027-arch-frames.md`.
- **Статус:** Proposed → Accepted по T-3796 (Merge §96+). **Deploy:** `DEFERRED_TO_RELEASE`.
- **Risk-Level:** **R3** — идентичность/версии — основа памяти и provenance; ошибка ведёт к ложному слиянию людей/источников, потере даты события или «устаревшей актуальной» версии, которые каскадно портят retrieval/досье. Обязателен `threat-failure-analysis.md` (Блок H). Триггеры понижения до R2: подтверждённая изоляция группового write-пути, отсутствие переписывания legacy-ID, A07/A08/A11/A88 на фактическом diff.
- **Baseline (Step 0, используется как данность):** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v15** после волны 0 (v13 `schema_migrations`, v14 `task_jobs`, v15 `mca_events`); каталог `473/430/448/102/100/21`; канон 12; pytest 9588/0 + JS 47/47; reviewed-commit `05bc870`.
- **Зависимости:** `mca-14` ✅ (реестр `MigrationStep` + книга `schema_migrations`, механизм Δ DDL — `ARCHITECTURE.md` §93), `mca-01` ✅ (единый write-механизм `write_transaction`/`serialized()`/`@_serialized_write`, `task_jobs` — §95), `mca-13` ✅ (event-контракт §17.1, `mca_events` — единый durable-стор; вторая телеметрия запрещена — §94).

## 1. Область и исключения

**Входит:** единый контракт логической идентичности Telegram-сообщения `chat_id + tg_message_id`; namespace/dataset ID и стабильный source record ID; canonical source и правило связывания импортной/живой копии; сохранение полей §7 (текст/подпись, автор, имя на момент, `sent_at`/`ingested_at`/`edited_at`, reply target, forward/quote, media reference, `source_kind`, revision/hash); честное различие «дата события ≠ дата импорта»; разделение автор/адресат/цитируемый/субъект и display-only алиасы без автослияния; редакции → версии + пометка зависимых выводов; `unavailable/deleted` только по свидетельству; явный mapping `chat_id` при миграции; Δ DDL **v16** через реестр `mca-14`; producer/consumer на канонической идентичности; события MCA-13/стадии MCA-17a; R17-маскирование; kill-switch.

**Не входит (границы):**
- **Provenance-контракт** (SourceRef/EvidenceLink, статусы происхождения) — `mca-04a`; MCA-03 отдаёт примитивы (`chat_id`+`tg_message_id`, namespace/dataset_id, revision, `sent_at`), но не создаёт второй контракт ссылок.
- **Retrieval/EvidenceBundle, age-by-event-time, `missing_timestamp`** — `mca-07`/`mca-06`; MCA-03 только предоставляет честные поля времени.
- **Subject/speaker entity, SelfModel, тип памяти** — `mca-18` (расширяет MCA-03).
- **MediaAsset/MediaAnalysis, bytes/MIME, vision** — `mca-19` (расширяет MCA-03; `media_ref` в MCA-03 — только ссылка, без байтов).
- **ClaimEnvelope/TemporalVerdict** — `mca-20`.
- **UI-витрина источников** и полная матрица процессов MCA-17 — `mca-17a`/`mca-17c`/`mca-12`; MCA-03 регистрирует свои стадии/виджет-ID, но не строит новую панель.
- **Реальное удаление зависимых выводов** при редакции — `mca-04a`/`mca-06`; MCA-03 только фиксирует версию и эмитирует `source_revision_changed`.
- **FTS/вектор-индексы** не пересоздаются ad hoc; используется существующий `smart_messages_fts`.

### 1.1. Фактическое состояние baseline (сверено с рабочей веткой; REUSE §3)

- `smart_messages` (`services/database.py:437–449`) имеет `id`, `user_id` (= логический `author_id`), `chat_id`, `text`, `reply_to_id`, `timestamp`, `media_type`, `author_name`, `is_forward`, `forward_source`, `tg_message_id` (+ миграционные `import_key`, `history_processed`). **`UNIQUE(chat_id, tg_message_id)` отсутствует**; `get_smart_message_by_tg_id` (`:2573`) уже фильтрует по `chat_id` — частичная опора на `chat_id + tg_message_id` **есть, подтвердить тестом**.
- Живой ingestion (`handlers/summary.py:157–212`) пишет `timestamp=int(time.time())` — это **время записи, а не `message.date`**; `sent_at`/`ingested_at` не разделены. **Дефект §7 присутствует.**
- Редакции: `handlers/direct_chat.py:333–345` обрабатывает **только правки бота** (`bot_replies`), правка человеком → `UNHANDLED`, версий нет. **Дефект §7 присутствует.**
- Импорт (`tools/history_import/parser.py`) пишет `import_key = sha256(ts|user_id|text)` и намеренно `tg_message_id=NULL`; namespace/dataset ID и стабильный source record ID **отсутствуют**. `detect_export_id` читает id чата из шапки экспорта. **Дефект §7 присутствует.** `reply_to_id` импорта — экспортный id (может быть отрицательным) — смешение с TG id.
- Алиасы (`services/summary_aliases.py`) — каскад alias → nickname → username → user_id, display-only; слияния идентичностей по имени нет. **Требование §7 «ALIAS > real_name > username — отображение» уже соблюдено — подтвердить тестом, не переписывать.**
- Mapping исторических смен `chat_id` отсутствует. **Дефект §7 присутствует.**
- `unavailable/deleted`-статус не моделируется; отсутствие API-события нигде не считается доказательством. **Требование §7 не нарушено, но и не смоделировано.**

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA03-01 — логическая идентичность `chat_id + tg_message_id` (не одиночный `message_id`) | §7 `:188` | SC-01, SC-02 | T-3783, T-3790 |
| REQ-MCA03-02 — namespace/dataset ID + стабильный source record ID + canonical source; локальный ID ≠ Telegram ID | §7 `:188` | SC-03, SC-04 | T-3783, T-3788 |
| REQ-MCA03-03 — сохраняемые поля §7; `sent_at`/`ingested_at`/`edited_at`; дата события ≠ дата импорта; `timestamp` не переименовывать | §7 `:190` | SC-05, SC-06 | T-3784, T-3791 |
| REQ-MCA03-04 — разделение автор/адресат/цитируемый/субъект; display-only алиасы; запрет автослияния по имени | §7 `:192` | SC-07, SC-08 | T-3785, T-3789, T-3791 |
| REQ-MCA03-05 — редакция → версия + пометка зависимых; `unavailable/deleted` только по свидетельству | §7 `:194` | SC-09, SC-10 | T-3786, T-3791, T-3792 |
| REQ-MCA03-06 — явный mapping смены `chat_id` по подтверждённым метаданным | §7 `:196` | SC-11 | T-3787, T-3790 |
| REQ-MCA03-07 — Δ DDL v16 через реестр `mca-14`; старые ID/таблицы сохраняются; nullable = честный unknown | §18 `:864–866` | SC-12 | T-3782, T-3784 |
| REQ-MCA03-08 — producers/consumers на канонической идентичности; REUSE Epic 1–3; второй контракт не создаётся | §3/§3.1 `:47`,`:60–75` | SC-13, SC-14 | T-3788, T-3789 |
| REQ-MCA03-09 — события MCA-13 + `reason_code`; стадии MCA-17a; R17-маскирование | §17.1–§17.3 `:818–846`; §27.1 | SC-15, SC-16 | T-3792, T-3793 |
| REQ-MCA03-10 — kill-switch env-only default ON, OFF = паритет baseline; deploy `DEFERRED_TO_RELEASE`; регрессии | §18 `:872`; §2.4–2.5 | SC-17 | T-3794, T-3795 |
| REQ-MCA03-11 — границы с `mca-04a`/`mca-07`/`mca-18`/`mca-19`/`mca-20` (один контракт) | §3.1 `:66–75` | SC-18 | T-3783, T-3789 |

**Орфан-REQ нет;** T-3777/3778/3796/3797 — процессные (baseline/PM/ревью-merge/архив).

## 3. Наблюдаемое поведение и отказы

- Два разных чата с одинаковым `message_id` не конфликтуют: ключ канонической идентичности — пара `(chat_id, tg_message_id)`.
- Импортированная и живая копия одного сообщения связаны с **одним** canonical source **только** при совпадении `(chat_id, tg_message_id)`; при отсутствии Telegram ID связывание не производится, локальный идентификатор не выдаётся за Telegram.
- Дата события (`sent_at`) и дата импорта/записи (`ingested_at`) различаются; историческое сообщение 2022, найденное сегодня, имеет **две** даты; при отсутствии достоверного времени — честный unknown (не «сегодня»).
- Цитата не становится мнением цитирующего: автор, адресат ответа, процитированный автор и субъект обсуждения — разные поля/роли.
- Совпадение имени/прозвища не объединяет людей; два «Макса» остаются разными идентичностями, различимыми по `user_id`.
- Редакция создаёт новую версию; актуальная версия — только последняя; зависимые выводы помечаются на пересмотр.
- `unavailable/deleted` устанавливается только при свидетельстве; отсутствие API-события не считается доказательством сохранности.
- Смена `chat_id` при миграции группы учитывается **только** по подтверждённым метаданным, не по похожему названию.
- OFF kill-switch = точный legacy-путь (наблюдаемое поведение baseline).

## 4. Интерфейсы и контракты

### 4.1. Логическая идентичность (D1/D2)
- **Канонический ключ:** `(chat_id, tg_message_id)` при известном Telegram ID. `smart_messages.id` — стабильный **внутренний** ID; он **никогда** не предъявляется как Telegram ID.
- **Canonical source:** строка `smart_messages` — единственный канонический носитель сообщения; вхождения (occurrences) — строки `message_source_records`, ссылающиеся на `message_id`.
- **Namespace/dataset ID:** `namespace` (напр. идентификатор импортной партии/экспорта) + `source_record_id` — стабильный ID записи внутри namespace (для импорта это экспортный record id в текстовом виде либо сгенерированный `k:<import_key>` для legacy; **локальный, не TG**).
- **Правило связывания:** импортная и живая копии связываются с одним canonical source **только** при `tg_message_id` на обеих и равенстве `(chat_id, tg_message_id)`. Иначе — раздельные source records; слияние по имени/близкому тексту **запрещено**.
- Локальный `source_record_id`/`smart_messages.id` **не** подставляется туда, где требуется Telegram ID; `source_kind ∈ {live, import, unknown}`.

### 4.2. Поля и время (D3)
- Сохраняются (все новые — nullable, честный unknown): `text`, `caption` (отдельно от производных), `user_id` (логический `author_id`), `author_name` (имя на момент), `sent_at`, `ingested_at`, `edited_at`, `reply_to_id` + `reply_to_kind` (`tg`|`export`|`unknown`), `reply_to_author_id`, `quote_text`, `quote_author_id`, `forward_author_id` (+ существующий `forward_source`), `media_ref`, `source_kind`, `namespace`, `source_record_id`, `content_hash`, `current_revision`, `message_state`, `state_evidence`, `sent_at_source`.
- **Дата события ≠ дата импорта:** `sent_at` — `message.date` (live) / `date_unixtime` (импорт); `ingested_at` — момент записи; `edited_at` — последняя правка.
- **`timestamp` не переименовывается.** Legacy-семантика фиксируется через `sent_at_source`: `telegram_date` | `import_date` | `legacy_unverified` | `unknown`. Backfill (D7) НЕ переносит `timestamp`→`sent_at` для live-legacy (там `timestamp` — время записи) и переносит для импорта (там `timestamp` — дата события), с явным маркером.

### 4.3. Роли и алиасы (D4)
- **author** = `user_id`; **reply addressee** = автор сообщения, на которое отвечают (`reply_to_author_id`), а не отвечающий; **quoted author** = `quote_author_id` (Telegram `quote`, может отличаться от адресата); **forward original author** = `forward_author_id`; **subject обсуждения** — не в MCA-03 (владелец — `mca-04a`/`mca-18`); запрещено схлопывать субъект в автора.
- `ALIAS > real_name > username` — **только отображение** (REUSE `services/summary_aliases.py`, не переписывать). Имя/прозвище **не является** ключом слияния; ключ идентичности — `user_id`/устойчивый ID.

### 4.4. Версии и свидетельства (D5)
- Редакция (`edited_message` от человека и/или редакция при импорте) → append `message_revisions` (`revision_kind='edit'`), инкремент `current_revision`, обновление `text`/`caption`/`content_hash`/`edited_at`, обновление FTS, событие `source_revision_changed`.
- Пометка зависимых выводов: MCA-03 **фиксирует** версию и эмитирует событие; пересмотр/инвалидация выводов — потребители (`mca-04a`/`mca-06`/`mca-07`). Устаревшая версия не остаётся «актуальной» (актуальная — `current_revision`).
- `message_state ∈ {active, unavailable, deleted, NULL=unknown}` + `state_evidence`. Смена состояния — только при свидетельстве (сервисное сообщение/подтверждённое событие); отсутствие API-события статус не меняет. Для не-`active` свидетельство обязательно.

### 4.5. Mapping `chat_id` (D6)
- `chat_id_migrations(old_chat_id, new_chat_id, evidence, observed_at)`; заполняется **только** из подтверждённых Telegram-метаданных (`migrate_to_chat_id`/`migrate_from_chat_id` сервисного сообщения). Резолвер отдаёт канонический `chat_id`; объединение по похожему названию запрещено.

### 4.6. Producer/consumer (D8)
- **Producers:** `handlers/summary.py::summary_observer` (live; `sent_at=message.date`, `ingested_at=now`, canonical get-or-create, source record), `handlers/direct_chat.py` edited-handler (правка человеком → revision), `tools/history_import/loader.py` (namespace/source record, `source_kind='import'`, `sent_at`=дата события, `reply_to_kind='export'`), backfill/CLI.
- **Consumers:** `services/summary_memory.py`, `services/direct_chat_service.py`, `lore_*`, retrieval (`mca-07`), досье/provenance (`mca-04a`), UI-карточка источника (`mca-12`/`mca-17a`) — только через контракт, без дубля логики идентичности.
- **Границы:** `mca-04a`/`mca-07`/`mca-18`/`mca-19`/`mca-20` **потребляют/расширяют** контракт MCA-03; второй контракт идентичности/версий запрещён.

### 4.7. Наблюдаемость и R17 (D10)
- События по контракту `mca-13` (`start`+terminal `outcome`) через REUSE `emit_mca_event`/`mca_events` (второй store запрещён). `reason_code`: `ambiguous_identity`, `source_revision_changed`, `source_missing` + расширение `duplicate_identity_rows` (WARN, регистрируется в реестре MCA-13).
- Стадии/виджет-ID процесса регистрируются для `mca-17a` (новый процесс без наблюдаемости = незавершённая интеграция).
- R17: в логи/события — только id/коды/`error_type`; `sanitize()` до записи во все каналы; SourceRef вместо сырого контекста; секреты не логируются.

## 5. Δ DDL (санкция) / Δ каталога / kill-switch

**Δ DDL = v16** (аддитивно, идемпотентно, через реестр `mca-14`; PG — no-op; старые таблицы/ID не переименовываются и не удаляются). Точные объекты:

`ALTER TABLE smart_messages ADD COLUMN` (каждый под guard `PRAGMA table_info`, все nullable — честный unknown):
```
sent_at            INTEGER
ingested_at        INTEGER
edited_at          INTEGER
sent_at_source     TEXT
source_kind        TEXT
namespace          TEXT
source_record_id   TEXT
caption            TEXT
content_hash       TEXT
media_ref          TEXT
reply_to_kind      TEXT
reply_to_author_id INTEGER
quote_text         TEXT
quote_author_id    INTEGER
forward_author_id  INTEGER
message_state      TEXT
state_evidence     TEXT
current_revision   INTEGER
```
Новые таблицы:
```
CREATE TABLE IF NOT EXISTS message_source_records (
    source_record_id INTEGER PRIMARY KEY AUTOINCREMENT,   -- внутренний стабильный ID; НЕ Telegram ID
    message_id       INTEGER NOT NULL,                    -- canonical → smart_messages.id
    namespace        TEXT NOT NULL,
    local_record_id  TEXT,
    tg_message_id    INTEGER,
    chat_id          INTEGER NOT NULL,
    source_kind      TEXT NOT NULL,
    observed_at      INTEGER NOT NULL,
    UNIQUE (namespace, local_record_id)
);
CREATE INDEX IF NOT EXISTS idx_message_source_records_message ON message_source_records(message_id);
CREATE INDEX IF NOT EXISTS idx_message_source_records_chat_tg ON message_source_records(chat_id, tg_message_id);

CREATE TABLE IF NOT EXISTS message_revisions (
    revision_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id     INTEGER NOT NULL,
    chat_id        INTEGER NOT NULL,
    tg_message_id  INTEGER,
    revision_no    INTEGER NOT NULL,
    revision_kind  TEXT NOT NULL,          -- initial|edit|unavailable|deleted
    text           TEXT,
    caption        TEXT,
    content_hash   TEXT NOT NULL,
    evidence_kind  TEXT,                   -- обязателен для unavailable/deleted
    editor_user_id INTEGER,
    created_at     INTEGER NOT NULL,
    UNIQUE (message_id, revision_no)
);
CREATE INDEX IF NOT EXISTS idx_message_revisions_message ON message_revisions(message_id, revision_no);

CREATE TABLE IF NOT EXISTS chat_id_migrations (
    old_chat_id INTEGER NOT NULL,
    new_chat_id INTEGER NOT NULL,
    evidence    TEXT NOT NULL,
    observed_at INTEGER NOT NULL,
    PRIMARY KEY (old_chat_id, new_chat_id)
);
```
Индексы `smart_messages` (только под подтверждённый `EXPLAIN QUERY PLAN`):
```
CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_tg ON smart_messages(chat_id, tg_message_id);
CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_sent ON smart_messages(chat_id, sent_at);
```
Опциональный partial UNIQUE (усиление каноничности) создаётся **только при прохождении duplicate pre-check**; иначе — WARN `duplicate_identity_rows` и non-unique индекс:
```
CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_messages_chat_tg_live_unique
    ON smart_messages(chat_id, tg_message_id)
    WHERE tg_message_id IS NOT NULL AND import_key IS NULL;
```
**Backfill legacy (в рамках v16, bounded/resumable):** для `import_key IS NOT NULL` → `source_kind='import'`, `namespace='legacy_import_v1'`, `source_record_id='k:'||import_key`, `sent_at=timestamp`, `sent_at_source='import_date'`, `reply_to_kind='export'`; для `import_key IS NULL` → `source_kind='live'`, `sent_at=NULL`, `ingested_at=NULL`, `sent_at_source='legacy_unverified'` (`timestamp` не переносится). Guard повторного прогона — `sent_at_source IS NULL`; батчи с ограничением; старые `id`/`timestamp`/FTS сохраняются.

**Δ каталога = 0.** Все рубильники — env-only `ClassVar`; `param_catalog.py` вне diff; F8 (ADR-1026-2) **NOT_APPLICABLE**.

**Kill-switch (утверждены, env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline):**
- `MCA_MESSAGE_IDENTITY_ENABLED` — OFF: прежний ingestion/импорт без канонической идентичности и source records (поведение baseline).
- `MCA_MESSAGE_REVISION_TRACKING_ENABLED` — OFF: редакции без версионирования (текущее поведение; правка человеком игнорируется, правка бота по-прежнему обновляет `bot_replies`).

OFF фиксируется в release-manifest/логе с причиной/временем/планом (R17-safe); релиз — со всеми ON.

## 6. Приёмочные сценарии (SC)

- **SC-01:** канонический ключ — `(chat_id, tg_message_id)`; два чата с одинаковым `message_id` не конфликтуют (A07).
- **SC-02:** локальный `smart_messages.id`/`source_record_id` не предъявляется как Telegram ID; `tg_message_id=NULL` там, где нет Telegram ID.
- **SC-03:** импорт несёт namespace/dataset ID и стабильный source record ID; при совпадении `(chat_id, tg_message_id)` импортная и живая копии привязаны к одному canonical source.
- **SC-04:** без Telegram ID связывание не производится; слияние по имени/близкому тексту невозможно.
- **SC-05:** сохраняются все поля §7; `text` и `caption` различимы; reply/forward/quote/media ref присутствуют (nullable = unknown).
- **SC-06:** `sent_at` ≠ `ingested_at`; история 2022, найденная сегодня, имеет две даты; `timestamp` не переименован; `sent_at_source` фиксирует происхождение (A11).
- **SC-07:** автор / адресат ответа / процитированный автор / forward-автор разделены; цитата не становится мнением цитирующего; субъект не подменяет автора (A07/A88).
- **SC-08:** `ALIAS > real_name > username` — только отображение; два одноимённых «Макса» не объединяются; ключ — устойчивый ID (A07/A88).
- **SC-09:** редакция → новая версия; поиск обновлён; актуальна только последняя версия; зависимые выводы помечены (`source_revision_changed`) (A08).
- **SC-10:** `unavailable/deleted` — только при свидетельстве; отсутствие API-события статус не меняет и не считается доказательством сохранности.
- **SC-11:** смена `chat_id` учитывается только по подтверждённым метаданным (`chat_id_migrations`); объединение по названию запрещено (A07).
- **SC-12:** миграция v16 аддитивна/идемпотентна через реестр; старые ID/таблицы/FTS сохранены; nullable = честный unknown; повторный прогон — no-op.
- **SC-13:** producer-пути (live/edited/import) пишут каноническую идентичность через существующий путь (`handlers/summary.py`), без второго ingestion.
- **SC-14:** consumers (retrieval/досье/истории) используют каноническую идентичность и устойчивый source record ID; legacy/unknown корректны; второй контракт не создан.
- **SC-15:** события `start`+`outcome` через `mca_events` с корректным `reason_code`; стадии/виджет-ID зарегистрированы для `mca-17a` (A27).
- **SC-16:** R17 — логи/события без секретов/сырого контекста; `sanitize()` до записи (A53).
- **SC-17:** kill-switch env-only default ON; OFF = точный legacy-путь; регрессии identity/dossier Epic 3 и FTS зелёные; deploy `DEFERRED_TO_RELEASE` (A28/A87).
- **SC-18:** `mca-04a`/`mca-07`/`mca-18`/`mca-19`/`mca-20` используют/расширяют контракт MCA-03, не создавая второй.

## 7. Тесты / деплой / откат

- **Тесты:** контрактные (два чата/одинаковый message_id; same-name не сливаются; цитата ≠ мнение; редакция→версия+пометка; `unavailable` только по свидетельству; mapping `chat_id`); интеграционные end-to-end на **обновлённых** путях с включёнными функциями (A07/A08/A11/A88; перенос старого unit-теста недостаточен); миграционный smoke v16 (идемпотентность, сохранение ID/FTS, backfill no-op при повторе); R17; регресс identity/dossier Epic 3; pytest ≥ baseline, `git diff --check`=0.
- **Деплой:** `DEFERRED_TO_RELEASE` (§20). На `mca-release` — backup+read-back, migration smoke v16, effective-state §20.2, manifest (`config changes`: kill-switch имена).
- **Откат:** hot — `MCA_MESSAGE_IDENTITY_ENABLED=false`/`MCA_MESSAGE_REVISION_TRACKING_ENABLED=false`; cold — `git revert` → `7165ff7`; DDL v16 аддитивен (новые колонки/таблицы безвредны), restore БД — только аварийный сценарий (R18: теги/бэкапы не удаляются).

## 8. Документация / MEMORY

- Merge-раздел `plans/ARCHITECTURE.md` §96+ — по T-3796 (@Architect, только по Accepted).
- Рамка: `plans/docs/mca-round1027-arch-frames.md` §1.2 (бронь v16), §3 (kill-switch).
- KG/индекс — на @Memory (Step 10); MEMORY_DELTA в handoff.
