# ADR-1027-4 — `mca-03-message-identity`: логическая идентичность `chat_id + tg_message_id`, namespace/dataset + stable source record ID, canonical source; поля/время/версии (event ≠ import time); роли автор/адресат/цитируемый/субъект + display-only алиасы; редакции→версии с пометкой зависимых; `unavailable/deleted` только по свидетельству; явный mapping `chat_id` — Δ DDL = v16, Δ каталога = 0, R3

- **Статус:** **Accepted** (факт Merge в `plans/ARCHITECTURE.md` **§96**, T-3796, 26.09.2026; см. §96.1–§96.6). На момент Step 2 — Proposed.
- **Фича:** `mca-03-message-identity` (Wave 1, данные, P0-предпосылка). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` §7 (`:180–198`), §3/§3.1 (`:45–75`), §4 (`:77–101`), §17.1–§17.3 (`:818–846`), §18 (`:856–872`), §19 A07/A08/A11/A88; §22 (`:1062–1077`); R17/R18.
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v15**; каталог `473/430/448/102/100/21`; канон 12.
- **Связано:** AMEND `handlers/summary.py` (ingestion), `services/database.py` (`smart_messages` + миграция v16), `tools/history_import/loader.py`/`parser.py` (namespace/source record); REUSE `services/summary_aliases.py` (display-only), `write_transaction`/`serialized()`/`@_serialized_write` (`mca-01`), `emit_mca_event`/`mca_events` (`mca-13`), реестр `MigrationStep` (`mca-14`); Unblocks `mca-04a`/`mca-07`; рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§7 требует: логическая идентичность Telegram-сообщения — пара `chat_id + tg_message_id`, а не одиночный `message_id`; импорт имеет namespace/dataset ID и стабильный source record ID; при сохранённом Telegram ID импортная и живая копии одного сообщения связаны с одним canonical source; при отсутствии ID локальный идентификатор не выдаётся за Telegram. Сохранять: текст/подпись, `author_id`, имя на момент, `sent_at`, `ingested_at`, `edited_at`, reply target, forward/quote, media reference, `source_kind`, revision/hash; **дата события ≠ дата импорта**; старый `timestamp` не переименовывать в `sent_at` без проверки семантики. Разделять автора/адресата/цитируемого/субъекта; `ALIAS > real_name > username` — отображение, не слияние; совпадение имени не объединяет. Редакция → новая версия, поиск обновляется, зависимые выводы помечаются; `unavailable/deleted` — только по свидетельству. Смена `chat_id` при миграции группы — явный mapping по подтверждённым метаданным.

**Фактическое состояние baseline (сверено с рабочей веткой):** `smart_messages` хранит `id/user_id/chat_id/text/reply_to_id/timestamp/media_type/author_name/is_forward/forward_source/tg_message_id` (+`import_key`,`history_processed`), без `UNIQUE(chat_id, tg_message_id)`; `get_smart_message_by_tg_id` уже фильтрует по `chat_id`. Живой observer пишет `timestamp=time.time()` (время записи, не `message.date`). Правки человеком игнорируются (`direct_chat.py` обрабатывает только правки бота). Импорт пишет `import_key=sha256(ts|uid|text)`, `tg_message_id=NULL`, без namespace/source record; `reply_to_id` импорта — экспортный id. Mapping `chat_id` и модель `unavailable/deleted` отсутствуют. Алиасы display-only уже соблюдены (`summary_aliases.py`) — REUSE, не переписывать.

## Решения

**D1. Каноническая идентичность — `(chat_id, tg_message_id)` + внутренний ID.**
- **Выбрано:** канонический ключ сообщения при известном Telegram ID — пара `(chat_id, tg_message_id)`; `smart_messages.id` — стабильный **внутренний** ID, никогда не предъявляемый как Telegram ID. Lookup/вставка — канонический get-or-create по `(chat_id, tg_message_id)` до INSERT.
- **Обоснование:** §7 verbatim (`:188`); A07 «два разных чата с одинаковым message_id не конфликтуют».
- **Альтернатива:** глобально уникальный `message_id` без `chat_id` — отклонено (ложные конфликты между чатами).

**D2. Namespace/dataset + stable source record ID + canonical source.**
- **Выбрано:** `message_source_records(source_record_id PK, message_id→smart_messages.id, namespace, local_record_id, tg_message_id, chat_id, source_kind, observed_at)` — вхождения; canonical source = строка `smart_messages`. `source_record_id`/`smart_messages.id` — локальные, **не** Telegram. Связывание импортной и живой копии — **только** при совпадении `(chat_id, tg_message_id)`; иначе — раздельные source records.
- **Обоснование:** §7 verbatim (`:188`); честное различие локального и Telegram ID.
- **Альтернатива:** хранить namespace/source_record только колонками в `smart_messages` — отклонено (не моделирует несколько вхождений одной канонической записи и связь импорт↔live).

**D3. Поля и семантика времени.**
- **Выбрано:** аддитивные nullable-колонки `sent_at`, `ingested_at`, `edited_at`, `caption`, `content_hash`, `media_ref`, `reply_to_kind`, `reply_to_author_id`, `quote_text`, `quote_author_id`, `forward_author_id`, `source_kind`, `namespace`, `source_record_id`, `sent_at_source`, `current_revision`, `message_state`, `state_evidence`. Живой ingestion: `sent_at=message.date`, `ingested_at=now`; импорт: `sent_at=date_unixtime`, `reply_to_kind='export'`. `timestamp` **не** переименовывается; происхождение `sent_at` фиксирует `sent_at_source ∈ {telegram_date, import_date, legacy_unverified, unknown}`.
- **Обоснование:** §7 verbatim (`:190`); A11 «две даты; нет подмены времени события».
- **Альтернатива:** переименовать `timestamp`→`sent_at` — прямо запрещено §7.

**D4. Роли и display-only алиасы.**
- **Выбрано:** author=`user_id`; reply addressee=`reply_to_author_id` (автор replied-to, не отвечающий); quoted author=`quote_author_id`; forward author=`forward_author_id`; subject — вне MCA-03 (`mca-04a`/`mca-18`). Каскад `ALIAS > real_name > username` — REUSE `summary_aliases.py`, только отображение; ключ идентичности — устойчивый ID, не имя.
- **Обоснование:** §7 verbatim (`:192`); A07/A88.

**D5. Версии/редакции и свидетельства.**
- **Выбрано:** `message_revisions(message_id, revision_no, revision_kind, text, caption, content_hash, evidence_kind, editor_user_id, created_at)`; редакция → append + инкремент `current_revision` + обновление FTS + `edited_at` + событие `source_revision_changed`. `message_state ∈ {active, unavailable, deleted, NULL=unknown}` + `state_evidence`; смена состояния только по свидетельству. Пересмотр зависимых выводов — потребители (MCA-03 только фиксирует версию и эмитирует событие).
- **Обоснование:** §7 verbatim (`:194`); A08.

**D6. Mapping `chat_id`.**
- **Выбрано:** `chat_id_migrations(old_chat_id, new_chat_id, evidence, observed_at)`; заполняется только по подтверждённым метаданным `migrate_to/from_chat_id`; резолвер отдаёт канонический `chat_id`. Слияние по названию запрещено.
- **Обоснование:** §7 verbatim (`:196`).

**D7. Миграция v16 и сохранение legacy.**
- **Выбрано:** один шаг `v16` через реестр `mca-14` — `ALTER TABLE ... ADD COLUMN` под guard `PRAGMA table_info` + `CREATE TABLE/INDEX IF NOT EXISTS`; старые `id`/`timestamp`/FTS не трогаются; backfill bounded/resumable с guard `sent_at_source IS NULL`. Для импорта `sent_at=timestamp` (`import_date`), для live `sent_at=NULL` (`legacy_unverified`). Partial UNIQUE `(chat_id,tg_message_id) WHERE tg_message_id IS NOT NULL AND import_key IS NULL` — только при прохождении duplicate pre-check; иначе WARN `duplicate_identity_rows` + non-unique индекс.
- **Обоснование:** §18 (`:864–866`); MCA14-R1/R2; безопасность при возможных legacy-дублях.
- **Альтернатива:** удалить legacy-дубли под UNIQUE — запрещено (старые записи/ID сохраняются); rebuild `smart_messages` — отклонено (риск FTS/ID).

**D8. Producers/consumers и единый контракт.**
- **Выбрано:** producers — `handlers/summary.py::summary_observer` (AMEND, не второй ingestion), edited-handler, `tools/history_import/loader.py` (namespace); consumers — `summary_memory.py`, `direct_chat_service.py`, `lore_*`, MCA-04a/07/18/19/20 — только через контракт MCA-03. Второй контракт идентичности/версий запрещён.
- **Обоснование:** §3/§3.1 (REUSE); §4 (один контур).

**D9. Kill-switch.**
- **Выбрано:** `MCA_MESSAGE_IDENTITY_ENABLED` (ON: каноническая идентичность/source records; OFF: legacy ingestion/импорт), `MCA_MESSAGE_REVISION_TRACKING_ENABLED` (ON: версии редакций; OFF: текущее поведение). env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline.
- **Обоснование:** §18 (`:872`); прецедент `DB_LOCK_RESILIENCE_ENABLED`.

**D10. Наблюдаемость и R17.**
- **Выбрано:** события через `emit_mca_event`/`mca_events` (`start`+`outcome`), `reason_code` — REUSE `ambiguous_identity`/`source_revision_changed`/`source_missing` + расширение `duplicate_identity_rows`; регистрация стадий/виджет-ID для `mca-17a`; `sanitize()` до записи, SourceRef вместо сырого контекста.
- **Обоснование:** §17.1–§17.3; §27.1; GEN-R14/R17.

**D11. Δ DDL = v16; Δ каталога = 0.**
- Точные объекты — spec §5. PG — no-op. Каталог не меняется, F8 не переиздаётся. Версия бронируется в рамке §1.2.

**D12. Границы.**
- MCA-03 — источник примитивов идентичности/времени/версий; `mca-04a` — типизированные ссылки/provenance; `mca-07`/`mca-06` — retrieval/age; `mca-18` — subject/self; `mca-19` — media bytes/MIME; `mca-20` — claim/time. Не дублировать.

## Санкции и вердикты

- **Δ DDL = v16** — 18 nullable-колонок `smart_messages` + 3 таблицы (`message_source_records`, `message_revisions`, `chat_id_migrations`) + индексы; через реестр `mca-14` (`ARCHITECTURE.md` §93); старые таблицы/ID/FTS сохраняются; PG — no-op. Версия бронируется в `mca-round1027-arch-frames.md` §1.2.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch:** `MCA_MESSAGE_IDENTITY_ENABLED`, `MCA_MESSAGE_REVISION_TRACKING_ENABLED` (env-only, default ON, OFF-паритет baseline).
- **reason_code:** REUSE `ambiguous_identity`/`source_revision_changed`/`source_missing`; расширение `duplicate_identity_rows` (WARN).
- **Risk:** **R3** (основа памяти/provenance; каскад при ложном слиянии/потере даты/устаревшей версии); `threat-failure-analysis.md` обязателен (Блок H). Понижение — при доказанной изоляции и A07/A08/A11/A88 на фактическом diff.
- **Обратный путь:** hot env-OFF; cold `git revert` → `7165ff7`; v16 аддитивна (новые колонки/таблицы безвредны).
- **Release policy:** `DEFERRED_TO_RELEASE`.

## AMEND / REUSE-карта

| Артефакт | Режим | Суть |
|---|---|---|
| `services/database.py` (`smart_messages`, миграция v16) | **AMEND** | аддитивные колонки/таблицы/индексы; lookup/канонический get-or-create; backfill bounded |
| `handlers/summary.py::summary_observer` | **AMEND** | `sent_at=message.date`/`ingested_at`; canonical identity; source record (не второй ingestion) |
| `handlers/direct_chat.py` (edited handler) | **AMEND** | правка человеком → revision (при ON) |
| `tools/history_import/{parser,loader}.py` | **AMEND** | namespace/source record; `reply_to_kind='export'`; `tg_message_id` остаётся NULL при отсутствии |
| `services/summary_aliases.py` | **REUSE** | display-only каскад (уже соблюдён) — подтвердить тестом |
| `services/database.py::get_smart_message_by_tg_id` | **REUSE/AMEND** | chat-scoped lookup уже есть — расширить до канонического |
| `write_transaction`/`serialized()`/`@_serialized_write` (`mca-01`) | **REUSE** | единый write-механизм |
| `emit_mca_event`/`mca_events` (`mca-13`) | **REUSE** | события; второй store запрещён |
| реестр `MigrationStep`/`schema_migrations` (`mca-14`) | **REUSE** | механизм Δ DDL |
| identity/dossier Epic 3, ToolResult/SourceRef | **REUSE / не ломать** | потребители канонической идентичности |
| `mca-04a`/`mca-07`/`mca-18`/`mca-19`/`mca-20` | **Unblocks** | расширяют/потребляют контракт MCA-03 |

| Решение | Задачи |
|---|---|
| D1 (идентичность) | T-3783, T-3788, T-3790 |
| D2 (namespace/canonical) | T-3783, T-3788 |
| D3 (поля/время) | T-3784, T-3791 |
| D4 (роли/алиасы) | T-3785, T-3789, T-3791 |
| D5 (версии/свидетельства) | T-3786, T-3791, T-3792 |
| D6 (mapping chat_id) | T-3787, T-3790 |
| D7 (Δ DDL/legacy) | T-3782, T-3794 |
| D8 (producers/consumers) | T-3788, T-3789 |
| D9 (kill-switch) | T-3794, T-3795 |
| D10 (наблюдаемость/R17) | T-3792, T-3793 |
| D11 (Δ DDL/каталог) | T-3780, T-3782 |
| D12 (границы) | T-3783, T-3789 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Ключ идентичности | `message_id`; `(chat_id, tg_message_id)` | **пара** | §7; A07 (межчатовые коллизии) |
| Канонический источник | дублировать импорт/live; единый source | **единый `smart_messages`** | §7 canonical source |
| Namespace/source record | только колонки; отдельная таблица вхождений | **таблица вхождений** | несколько вхождений/связь импорт↔live |
| Время | переименовать `timestamp`; аддитивные sent/ingested | **аддитивно** | §7 запрещает переименование |
| Версии | перезапись `text`; таблица редакций | **таблица редакций** | A08; сохранность истории |
| `unavailable/deleted` | по отсутствию события; по свидетельству | **по свидетельству** | §7 verbatim |
| UNIQUE идентичности | жёсткий UNIQUE; partial + pre-check | **partial UNIQUE с pre-check** | legacy-дубли не должны ломать миграцию |
| Kill-switch | каталожный; env-only | **env-only ClassVar** | Δ каталога=0 |
| Risk | R2; R3 | **R3** | основа памяти/provenance |

## Последствия

- §7: каноническая идентичность `chat_id + tg_message_id`; namespace/source record/canonical source; поля/время/версии (event ≠ import time); разделение ролей + display-only алиасы; редакции→версии+пометка; `unavailable/deleted` только по свидетельству; mapping `chat_id`.
- Δ DDL=v16 (реестр `mca-14`); Δ каталога=0; risk R3 + threat-артефакт; hot-откат env-OFF; cold — `git revert` → `7165ff7`; deploy `DEFERRED_TO_RELEASE`.
- Потребители `mca-04a`/`mca-07`/`mca-18`/`mca-19`/`mca-20` строятся **поверх** контракта; второй контракт идентичности запрещён.

## Ссылки

- Feature: `plans/features/mca-03-message-identity/{spec.md, tasks.md, adr-1027-4-message-identity.md}`.
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1.2 v16, §3 kill-switch, §4 нумерация).
- Код: `services/database.py` (`smart_messages:437–449`, `save_smart_message:2379–2420`, `get_smart_message_by_tg_id:2573–2582`, `migration_steps:985–1027`); `handlers/summary.py` (`:157–212`); `handlers/direct_chat.py` (`:333–345`); `tools/history_import/parser.py` (`:122–172`), `loader.py` (`_INSERT_SQL`); `services/summary_aliases.py`; `services/mca_gates.py`; `config/settings.py`.
- ТЗ: `plans/current_task.md` §7 (`:180–198`), §17.1–§17.3 (`:818–846`), §18 (`:864–866`), §19 A07/A08/A11/A88 (`:888–892`,`:969`), §22 (`:1066–1075`).
- Архитектура: merge → §96+; входы — §93 (`mca-14`), §94 (`mca-13`), §95 (`mca-01`).
- Точка отката: коммит `7165ff7`.
