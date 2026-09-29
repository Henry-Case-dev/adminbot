# `mca-03-message-identity` — evidence (Step 3 @Builder, T-3782…T-3795)

> **Статус:** 🟩 Реализовано + верифицировано (Builder). Ожидает независимого @Reviewer (T-3796).
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; пер-фичевых деплоев/тегов/bump `APP_VERSION` нет).
> **Risk:** R3 (см. `threat-failure-analysis.md`).

## 1. Baseline → текущее состояние

| Параметр | Значение |
|---|---|
| HEAD (baseline отката) | `05bc8704c2de5e7de1d5d04ac34df763d35219aa` |
| Ветка | `master`; рабочее дерево содержит незакоммиченные изменения волны 0 + других фич (не трогали) |
| `APP_VERSION` | **2.58.31 (не менялся)** |
| SQLite DDL | **v15 → v16** (шаг `message_identity` через реестр `mca-14`) |
| Feature-Diff-SHA256 (`git diff -- <feature files>`; LF) | `4c34c77168e71380…` |
| Commits/теги | нет (по инструкции); `current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не изменялись этим шагом |

## 2. Изменённые файлы

| Файл | Режим | Суть |
|---|---|---|
| `services/message_identity.py` | **NEW** | контракт `(chat_id, tg_message_id)`, namespace/source record, роли, hash, время, версии, mapping, gated producers + WARN `duplicate_identity_rows` |
| `services/database.py` | **AMEND** | DDL v16 (18 nullable-колонок + 3 таблицы + индексы + partial UNIQUE), migration/backfill, canonical get-or-create, revisions, state, source records, chat_id mapping, расширенный `get_smart_message_by_tg_id` |
| `services/mca_gates.py` | **AMEND** | kill-switch'и `MCA_MESSAGE_IDENTITY_ENABLED`, `MCA_MESSAGE_REVISION_TRACKING_ENABLED` |
| `services/mca_events.py` | **AMEND** | `reason_code` `duplicate_identity_rows` в реестре §17.2 |
| `config/settings.py` | **AMEND** | env-only `ClassVar` kill-switch'и (Δ каталога = 0) |
| `handlers/summary.py` | **AMEND** | observer → canonical live (дата события/роли/media_ref); новый `edited_message`-хендлер → версия |
| `tools/history_import/parser.py` | **AMEND** | импорт: `sent_at`/`sent_at_source`/`source_kind`/`reply_to_kind`/`source_record_id`/`caption` |
| `tools/history_import/loader.py` | **AMEND** | запись v16-полей + `message_source_records` (ON) / legacy-INSERT (OFF) |
| `tests/test_mca03_message_identity_round1027.py` | **NEW** | 20 тестов: миграция/идемпотентность/дубли/backfill + A07/A08/A11/A88 + OFF-паритет + R17 |
| `tests/test_mca01_tx_task_supervisor_round1027.py` | **AMEND** | allowlist AST-guard `database.py` 102 → 109 (7 санкционированных commit шага v16/backfill) |
| 13 × существующие тесты | **AMEND** | schema-target `user_version` 15 → 16 (test_database + 12 миграционных/UI) |

## 3. Δ DDL v16 (идемпотентность / backfill)

- **18 nullable-колонок** `smart_messages` (`ALTER ... ADD COLUMN` под guard `PRAGMA table_info`): `sent_at`, `ingested_at`, `edited_at`, `sent_at_source`, `source_kind`, `namespace`, `source_record_id`, `caption`, `content_hash`, `media_ref`, `reply_to_kind`, `reply_to_author_id`, `quote_text`, `quote_author_id`, `forward_author_id`, `message_state`, `state_evidence`, `current_revision`.
- **Таблицы:** `message_source_records` (UNIQUE(namespace, local_record_id)), `message_revisions` (UNIQUE(message_id, revision_no)), `chat_id_migrations` (PK(old,new)).
- **Индексы:** `idx_smart_messages_chat_tg`, `idx_smart_messages_chat_sent` (подтверждено `EXPLAIN QUERY PLAN`: `SEARCH ... USING COVERING INDEX` — оба), `idx_message_source_records_message`, `idx_message_source_records_chat_tg`, `idx_message_revisions_message`.
- **Duplicate pre-check:** при legacy-дублях `(chat_id, tg_message_id)` для live partial UNIQUE `idx_smart_messages_chat_tg_live_unique` **не создаётся**, эмитится WARN `duplicate_identity_rows` (logger + MCA-13); строки НЕ удаляются. При чистом прогоне UNIQUE создаётся.
- **Backfill bounded/resumable:** guard `sent_at_source IS NULL`, батчи по 1000; импорт → `sent_at=timestamp`, `sent_at_source='import_date'`, `namespace='legacy_import_v1'`, `source_record_id='k:'||import_key`, `reply_to_kind='export'`; live-legacy → `sent_at=NULL`, `sent_at_source='legacy_unverified'` (`timestamp` НЕ переносится). Повторный прогон — no-op; старые `id`/`timestamp`/FTS сохранены (тесты).
- **Идемпотентность:** повторный `initialize()` — 0 дублей в `schema_migrations`, `user_version=16`.
- **Устойчивость:** шаг не падает на усечённой synthetic-legacy без `import_key` (pre-check/backfill трактуют строки как live).

## 4. Kill-switch

| Переменная | Default | OFF-паритет |
|---|---|---|
| `MCA_MESSAGE_IDENTITY_ENABLED` | ON | `save_smart_message` (baseline): без source records/новых полей |
| `MCA_MESSAGE_REVISION_TRACKING_ENABLED` | ON | правки без версий |

Резолв per-call, никогда не бросает; Δ каталога = 0 (F8 NOT_APPLICABLE).

## 5. Тесты (фактические числа)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`) | `python -m pytest -q -p no:cacheprovider` | **9608 passed / 0 failed** (baseline 9588 + 20 новых) |
| Focused mca-03 | `pytest tests/test_mca03_message_identity_round1027.py -q` | **20 passed** |
| Регрессии миграций/wave-0/loader/observer | `pytest tests/test_mca0{1,3,4}* tests/test_history_parser.py tests/test_history_loader.py tests/test_database.py tests/test_summary_handlers.py -q` | **252 passed** |
| JS vm-харнесс | `node tests\js\*.js` (47 файлов) | **47/47 ok** |
| Whitespace | `git diff --check` | exit 0 |
| EXPLAIN QUERY PLAN | probe на fresh v16 | оба индекса `chat_tg`/`chat_sent` — `SEARCH ... COVERING INDEX` |

### Покрытие приёмок

- **A07** (два Макса/цитата/forward/смена алиаса): `test_a07_two_chats_same_message_id_no_conflict`, `test_a88_two_same_name_users_not_merged_by_name`, `test_live_identity_fields_and_roles`, `test_chat_id_migration_explicit_only`.
- **A08** (редакция→версия+пометка): `test_a08_edit_creates_revision_updates_fts` (FTS старого текста = 0, событие `source_revision_changed`), `test_a08_unavailable_only_by_evidence`.
- **A11** (2022 найдено сегодня → две даты): `test_a11_import_via_loader_two_dates`, `test_legacy_backfill_import_and_live`.
- **A88** (источники/одноимённые по устойчивому ID): `test_a88_two_same_name_users_not_merged_by_name`, `test_live_identity_fields_and_roles`.
- **SC-12/A87** (идемпотентность/legacy): `test_v16_idempotent_reinitialize`, `test_duplicate_precheck_warns_no_unique`, `test_legacy_backfill_import_and_live`.
- **A28/SC-17** (OFF-паритет): `test_identity_off_legacy_parity`, `test_revision_tracking_off_parity`, `test_loader_identity_off_parity`, `test_observer_identity_off_parity`.
- **A53/SC-16** (R17): `test_r17_event_drops_raw_context` (raw `text`/secret-поля не попадают в событие).
- **A27/SC-15** (события): `test_duplicate_warning_reason_registered`.

## 6. Наблюдения/отклонения (для @Reviewer)

1. **Правки человеком → версия** обрабатываются новым `edited_message`-хендлером summary-observer'а (canonical ingestion-роутер, все чаты), а не bot-only хендлером `handlers/direct_chat.py` (он намеренно игнорирует правки людей и предназначен для `bot_replies`). Это сохраняет семантику direct_chat и покрывает A08 без второго ingestion.
2. **FTS-порядок:** для external-content `smart_messages_fts` удаление старой записи выполняется ДО `UPDATE` контент-таблицы (иначе FTS5 не снимает старые токены). Затронуты новые пути update/edit.
3. **Backfill не создаёт** `message_source_records`/`message_revisions` для legacy-строк (только колонки) — bounded и достаточно для линковки импорт↔live по `(chat_id, tg_message_id)`; версии/вхождения пишутся producer'ами на новых записях.
4. **Импорт `caption`:** экспорт не несёт отдельного caption → для media-записей `caption=text`, для текстовых `NULL` (честный unknown).
5. **Consumers (T-3789):** контракт отдаёт `get_smart_message_by_tg_id` (расширен полями v16) и `get_message_source_records`/`get_message_revisions`; второй контракт не создан. Глубокая перестройка retrieval/досье отнесена к `mca-07`/`mca-04a` (границы spec §1).

## 7. Deploy / rollback (T-3795) — `DEFERRED_TO_RELEASE`

- **Migration smoke v16** (fresh + legacy): выполнен тестами (создание/идемпотентность/backfill/duplicate pre-check).
- **Manifest §20 (`config changes`):** `MCA_MESSAGE_IDENTITY_ENABLED` (default ON), `MCA_MESSAGE_REVISION_TRACKING_ENABLED` (default ON) — env-only, Δ каталога 0.
- **Effective-state:** DDL v16 аддитивна (новые колонки/таблицы безвредны при старом коде); при OFF — legacy-путь.
- **Rollback:** hot — env-OFF обоих рубильников; cold — `git revert` к `05bc870` (анкер `7165ff7`); restore БД — только аварийный сценарий (R18: теги/бэкапы не удаляются).
- **Per-feature deploy/тега/bump нет** — вход в агрегатный релиз `mca-release`.

## 8. Известные ограничения / не запускалось

- **Реальный deploy** — не выполнялся (`DEFERRED_TO_RELEASE`).
- **Browser-верификация** — NOT_APPLICABLE (фича backend/data, UI не меняет).
- **Live A28 на реальном рантайме** и полный smoke legacy v1:v11 — за `mca-release`.
- **GEN-R20 (фактическая заполненность ID/пересечения импорт↔live на реальной БД)** — не собиралась: требует доступа к прод/рабочей БД и не входит в безопасный локальный smoke Builder'а; отнесено к @Memory/@DevOps шагу инспекции (данные недоступны на этом шаге).

## 9. Rework round 10.27 (по итогам Reviewer gate, T-3796)

> Reviewer gate: **Needs Fixes** (`B-MCA03-1` High, `B-MCA03-2` High + M/L). Все High
> и non-blocking исправлены/зарегистрированы; требования не ослаблены.

### High
- **B-MCA03-1 — namespace-коллизия (потеря provenance ≈316 тыс. записей).**
  `tools/history_import/loader.py`: `_dataset_namespace(path)` = `import:<export_id>:<sha256(abspath|size)[:16]>`; per-file namespace по умолчанию (`load_file`/`import_history_fts`, `namespace=None`); явный namespace — override. Legacy-backfill namespace `legacy_import_v1` не меняется (совместимость). `manage.py` не требует правок (per-file namespace выводится автоматически).
  Тест `test_import_two_exports_same_record_ids_keep_provenance`: два экспорта с одинаковой шапкой (`-1005001`) и record-id `1/2`, разным текстом → `smart_messages=4`, `message_source_records=4`, 2 различных namespace.
- **B-MCA03-2 — `sent_at` ≠ `ingested_at` на живом пути.**
  `handlers/summary.py::summary_observer`: `sent_at = _sent_at_of(message)` (дата Telegram) и `ingested_at = int(time.time())` (время записи) вычисляются независимо; legacy `timestamp` = время записи; значения не приравниваются. Ослабленный assert `... or sent_at > 0` заменён строгим.
  Тесты: `test_observer_sent_at_is_telegram_date_not_ingest_time` (событие 2022 → `sent_at == date.timestamp()`, `before ≤ ingested_at ≤ after`, `sent_at < ingested_at`, `timestamp == ingested_at ≠ sent_at`); `test_observer_live_writes_identity` (строгий).
- **Импорт (A11):** `sent_at` из экспорта (`date_unixtime`), `ingested_at` = момент записи — `test_a11_import_via_loader_two_dates`.

### Medium / Low
- **M-MCA03-4** (связывание импорт↔live): `services/database.py::save_smart_message_identity` — `_record_occurrence` пишет вхождение и на существующей canonical-строке (`INSERT OR IGNORE`, идемпотентно). Тест `test_import_and_live_share_one_canonical_source` (1 canonical, `source_kind ∈ {import, live}`).
- **M-MCA03-5** (`sent_at` в changed-ветке): в коде уже присутствует `COALESCE(sent_at, ?)`/`COALESCE(ingested_at, ?)`; добавлен регресс-тест `test_existing_row_backfills_sent_at_on_changed_update`.
- **M-MCA03-3** (wiring `chat_id_migrations`): `handlers/chat_lifecycle.py` — DI `db` (`setup_chat_lifecycle`), запись `register_chat_id_migration` в `on_chat_migrated` (`evidence='telegram:migrate_to_chat_id'`, fail-open); `bot.py` пробрасывает `db=db`. Тест `test_chat_migrated_wiring_records_chat_id_mapping`.
- **L-MCA03-6 (граница):** ре-наблюдение сообщения в том же тексте обновляет canonical без новой revision — версии только через `record_edit`/edited-хендлер; согласуется с дизайном, не дефект.
- **L-MCA03-7 (граница):** edited-хендлер summary-observer'а намеренно UNHANDLED (bot-edit остаётся вне revision-логики; порядок роутеров: summary-observer 0a до direct_chat).

### Тесты (rework, факт)
| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`) | `python -m pytest -q -p no:cacheprovider` | **9678 passed / 0 failed** (baseline 9667 + 11 новых) |
| Focused mca-03 | `pytest tests/test_mca03_message_identity_round1027.py -q` | **25 passed** |
| Focused mca-02+mca-03+loader | `pytest tests/test_mca03_* tests/test_mca02_* tests/test_history_loader.py -q` | **94 passed** |
| JS vm-харнесс | `node tests/js/*.js` | **47/47 ok** |
