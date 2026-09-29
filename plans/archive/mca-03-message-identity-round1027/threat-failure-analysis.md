# `mca-03-message-identity` — threat & failure analysis (R3, ADR-1027-4 D5/D7/D10)

> **Причина R3:** логическая идентичность/версии — основа памяти и provenance.
> Ошибка каскадно портит retrieval/досье: ложное слияние людей/источников,
> потеря даты события, «устаревшая актуальная» версия. Артефакт обязателен
> (spec §Risk; Блок H).

## 1. Границы и активы

- **Активы:** строки `smart_messages` (canonical source), `message_source_records`,
  `message_revisions`, `chat_id_migrations`; поля времени (`sent_at`/`ingested_at`/
  `edited_at`) и   ролей; FTS `smart_messages_fts`; kill-switch'и.
- **Вне scope:** provenance-контракт (`mca-04a`), retrieval/age (`mca-07`),
  subject/speaker (`mca-18`), media bytes (`mca-19`).

## 2. Модель угроз (R17: секреты/полные пути не логируются)

| # | Угроза | Вектор | Мера | Остаточный риск |
|---|---|---|---|---|
| T1 | Ложное слияние двух людей | совпадение имени/прозвища | ключ идентичности = устойчивый `user_id`/`(chat_id,tg)`; имя только display | Low |
| T2 | Межчатовый конфликт | один `message_id` в разных чатах | канонический ключ = пара `(chat_id, tg_message_id)`; partial UNIQUE scoped по чату | Low |
| T3 | Локальный ID выдан за Telegram | подстановка `smart_messages.id` | `tg_message_id` пишется только из фактического TG id; `source_record_id` — локальный | Low |
| T4 | Подмена времени события временем импорта | переименование `timestamp`→`sent_at` | `timestamp` не трогается; `sent_at_source ∈ {telegram_date,import_date,legacy_unverified,unknown}`; backfill live → NULL | Low |
| T5 | Смешение источников | слияние импорта и live по имени/тексту | связывание только при равенстве `(chat_id,tg)`; иначе раздельные source records | Low |
| T6 | Устаревшая версия как актуальная | перезапись текста без истории | append `message_revisions` + инкремент `current_revision`; FTS пересобирается; событие `source_revision_changed` | Low |
| T7 | Ложный `unavailable/deleted` | отсутствие API-события | смена состояния только при непустом `evidence`; иначе отказ | Low |
| T8 | Ложная смена `chat_id` | объединение по похожему названию | `chat_id_migrations` только из подтверждённых метаданных; резолвер с защитой от цикла | Low |
| T9 | Утечка секретов/контекста в логи/события | несанитизированные поля | события через MCA-13 (`sanitize()`, whitelist полей); в коде только id/коды | Low |
| T10 | Небезопасный/частичный DDL | сбой миграции, legacy-дубли | аддитивность, self-guard, backup перед шагами, duplicate pre-check, bounded backfill с guard | Low |

## 3. Модель отказов (failure modes)

| F | Отказ | Наблюдаемый эффект | Обработка | Проверка |
|---|---|---|---|---|
| F1 | Legacy-дубли `(chat_id, tg)` | partial UNIQUE не создаётся | WARN `duplicate_identity_rows`; строки сохранены | `test_duplicate_precheck_warns_no_unique` |
| F2 | Повторный прогон миграции | дубли в книге/переприсвоение | `IF NOT EXISTS` + guard `sent_at_source IS NULL` | `test_v16_idempotent_reinitialize`, `test_legacy_backfill_import_and_live` |
| F3 | Сбой на шаге до v16 (fresh) | пропуск ранних ступеней | runner применяет `version > current`; книга без преждевременного `user_version` (mca-14) | wave-0 `test_fresh_init_failure_on_early_step_recovers` |
| F4 | Редакция с тем же текстом | лишняя версия | идемпотентность `record_edit` (no-op) | `test_a08_edit_creates_revision_updates_fts` |
| F5 | FTS рассинхрон при редактировании | старый текст находится поиском | delete FTS ДО `UPDATE` контент-таблицы | `test_a08_edit_creates_revision_updates_fts` |
| F6 | OFF kill-switch | новые поля/записи | exact legacy-путь (`save_smart_message`) | `test_identity_off_legacy_parity`, `test_revision_tracking_off_parity` |
| F7 | Отсутствие TG id | нельзя связать импорт/live | раздельные source records; локальный ID не выдаётся за TG | `test_a88_*`, `test_a11_*` |
| F8 | Цикл в `chat_id_migrations` | зацикливание резолвера | bound `max_hops` + `seen` | `test_chat_id_migration_explicit_only` |

## 4. Наблюдаемость (D10)

- События `start`/terminal `outcome` через `emit_mca_event`/`mca_events` (единственный
  durable-стор; второй запрещён). `reason_code`: `source_revision_changed`,
  `source_missing`, `ambiguous_identity` (REUSE) + `duplicate_identity_rows` (WARN,
  зарегистрирован в `services/mca_events.py`).
- R17: события проходят `sanitize()`; сырой `text`/секреты не входят в whitelist
  полей и не попадают в лог/стор (`test_r17_event_drops_raw_context`).

## 5. Остаточные риски / передача

- Полная интеграция потребителей (retrieval/досье, age-by-event-time) — `mca-07`
  и `mca-04a` (границы spec §1); MCA-03 отдаёт только примитивы.
- Live-проверка A28 на реальном рантайме и полный migration smoke legacy v1:v11 —
  за `mca-release` (`DEFERRED_TO_RELEASE`).
- Триггеры понижения R3→R2 (spec §Risk): подтверждённая изоляция группового
  write-пути, отсутствие переписывания legacy-ID, A07/A08/A11/A88 на фактическом
  diff — на момент Builder A07/A08/A11/A88 покрыты тестами, legacy-ID сохраняются.

## 6. Rework round 10.27 (по итогам Reviewer gate: B-MCA03-1/B-MCA03-2)

| # | Угроза/отказ | Вектор | Мера (после фикса) | Проверка |
|---|---|---|---|---|
| T11 | Потеря provenance при нескольких импортах | общий `namespace='legacy_import_v1'` + `UNIQUE(namespace, local_record_id)` при пересечении record-id экспортов (~316 547 на реальных `10.2024`×`10.08.2025`) | per-dataset namespace `import:<export_id>:<file-fingerprint>` (`_dataset_namespace`) — стабилен для повторного импорта, различает экспорты даже с одинаковой шапкой | `test_import_two_exports_same_record_ids_keep_provenance` |
| F9 | Схлопывание даты события и записи (live) | `sent_at`/`ingested_at` неразличимы у живого сообщения | независимые `sent_at=message.date` и `ingested_at=now`; legacy `timestamp`=время записи; строгий пин `sent_at < ingested_at` для поздно доставленного | `test_observer_sent_at_is_telegram_date_not_ingest_time`, `test_observer_live_writes_identity` |
| F10 | Формальность связывания импорт↔live | occurrence live не записывалось на существующую canonical-строку | `_record_occurrence` на insert **и** update-ветке (`INSERT OR IGNORE`); обе копии различимы по `source_kind` | `test_import_and_live_share_one_canonical_source` |
| F11 | `sent_at` не заполняется в changed-ветке | pre-v16 строка (NULL) + изменённый live-текст | `COALESCE(sent_at, ?)`/`COALESCE(ingested_at, ?)` в changed-UPDATE | `test_existing_row_backfills_sent_at_on_changed_update` |
| F12 | `chat_id_migrations` без producer'а | `register_chat_id_migration` не вызывался из живого пути | DI `db` в `setup_chat_lifecycle` + запись в `on_chat_migrated` (fail-open) | `test_chat_migrated_wiring_records_chat_id_mapping` |
