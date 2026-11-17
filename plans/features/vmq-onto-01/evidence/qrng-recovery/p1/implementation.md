# QRNG P1 — изоляция и честность (implementation)

**Дата:** 2026-11-17
**База:** deployed `34c25d09` (2.58.213) — **не** master; master-дерево отличается (§0.2 arch-decision).
**ARCH_DECISION:** `plans/features/vmq-onto-01/evidence/qrng-recovery/arch-decision-2026-11-17.md` (commit `458fafc3`, не входит в базу — реализации прочитана из master-копии).
**Ветка:** `fix/qrng-p1` (worktree `…/worktrees/c742e4de9e92c489/qrng-recovery-d99bf407dbfe-5c725ffc`).
**Статус:** реализация + тесты; REVIEW/VERIFIED не заявлялись, bump/deploy не выполнялись.

## 0. Границы P1 (что сделано / что сознательно не сделано)

Сделано ровно по scope P1: additive DDL + идемпотентная миграция; fingerprint-
scoped reserve; draft-key isolation; provenance/DTO (канонический provider id,
`entropy_class`, per-provider reserve); cooldown ручных проверок; RBAC-фикс
операций провайдера; явный PRNG-статус без перезаписи настройки.

Не сделано (P2–P5): адаптеры IBM/LfDR, селектор/порядок fallback (P3),
UI-страница и перенос `keys_random` (P4), IBM job lifecycle (P5), `TaskSupervisor`,
`quantum_publication`, `semantic_schedule`, QND-журнал, prompts/models,
`keys_random` в UI (P4). Новых очередей/сторов/планировщиков/API ключей нет.

## 1. Соответствие контракту (arch D1/D2/D3/D6/D8/D14, QAN-REC)

| Требование | Реализация | Где |
|---|---|---|
| D2: ровно 2 аддитивные колонки, идемпотентная миграция, old code ignore | `config_fingerprint TEXT NULL`, `external_ref TEXT NULL`; шаг `random_batch_provenance_v48` (`ALTER TABLE ... ADD COLUMN` под `PRAGMA table_info`; PG no-op; повтор no-op) | `services/database.py` (`_SCHEMA_VERSION_RANDOM_BATCH_PROVENANCE = 48`, `_migrate_random_batch_provenance_v48`) |
| D2: backfill только при совпадении fingerprint текущего ключа, иначе NULL | `RandomSourceService.sync_batch_provenance()`: `key_fingerprint(current) == state.key_fingerprint AND activated_at` → UPDATE только `config_fingerprint IS NULL` и только ANU-провайдеров (`anu` + легаси `"ANU Quantum Numbers"`). Идемпотентно; вызовы: `startup()` (active), `activate()` success, refill success. Миграция backfill НЕ делает: у неё нет доступа к effective-ключу (PG `bot_settings`), а придуманный отпечаток был бы ложным provenance | `services/mca_random_source.py` |
| D3: reserve только `NULL OR = current`; draft не вставляет; saved-key deposit + fingerprint | `RandomStore._fingerprint_clause()` в `reserve_draw`/`reserve_chunk`/`reserve_remaining`; `_run_check` draft-ветка возвращает `healthy` по реальной партии и **не** пишет в `mca_random_batches` (`deposited=false`); `activate()` пишет `config_fingerprint=fingerprint` и возвращает `deposited=true` | `services/mca_random_source.py` |
| D1 (каркас): реестр трёх провайдеров, canonical id, `entropy_class=hardware_quantum` | `PROVIDERS: dict[str, ProviderSpec]` (`ibm_quantum`, `anu`, `lfdr`), `canonical_provider_id()` маппит легаси `"ANU Quantum Numbers"`→`anu`; `source_impl` производный (`anu-quantum`); новые записи — `provider='anu'`; история не переписывается | `services/mca_random_source.py` |
| G4: provenance в DTO | `DrawResult.provider_id/entropy_class`, `ReservedDraw/ReservedChunkValue.provider_id`, `CoreDreamRandomSource` meta (`provider_id`, `entropy_class`, производный `source_impl`) | там же |
| per-provider reserve в статусе | `RandomStore.provider_reserve()` + `status_snapshot`: `provider`, `entropy_class`, `providers[]` (3 записи), `provider_reserve{ibm_quantum,anu,lfdr}`, `last_batch.provider_id` (история рядом, не перезаписана); pass-through в `StatusService.random_source_snapshot` | `services/mca_random_source.py`, `services/status_service.py` |
| D6/FALL-02: PRNG не скрытый fallback, сохранённое значение не перезаписывается | `fallback_setting` (существующее поле) + явная подпись `fallback_setting_label="псевдослучайный откат (не квантовый)"`; код не пишет `memory.random_fallback_to_pseudorandom`; при `false` и пустом запасе — `deferred`, 0 строк журнала; PRNG-draw никогда не имеет `entropy_class` | `services/mca_random_source.py` |
| D8/RBAC-01/02/SEC-01: операции провайдера — только global admin | `POST /api/random/test` → `Depends(requires_global_admin())`, `can_view_key_value` из этого пути удалён; запись/удаление 9 ключей `keys.random_quantum_*` в `POST /api/config` → `user_is_global_admin`, иначе 403 (остальные keys-ключи — прежний ACL) | `web/api/routes.py` |
| G14/D14: cooldown ручных проверок | окно `MCA_RANDOM_MANUAL_CHECK_COOLDOWN_SECONDS` (env-only, default 10, 0 = выключено) в `RandomSourceService.test_connection`: повтор в окне → тот же результат + `cooldown=true`/`retry_after_seconds`, без запроса; singleflight «в полёте» сохранён; планировщика нет | `services/mca_random_source.py`, `services/mca_gates.py`, `config/settings.py` |
| EXC-*: Lizaonair отсутствует | нет id/адаптера/ветки в коде (grep + тест `test_registry_three_hardware_providers_no_lizaonair`); в статусе нет упоминаний | — |

### Поведение при отсутствии ключа
`_current_fingerprint()` пуст → фильтр не применяется (легаси-семантика
2.58.213: уже полученная энтропия остаётся расходуемой, новых запросов без
ключа нет). Ротация A→B (ключ есть) фильтрует строго.

## 2. Изменённые файлы

- `services/mca_random_source.py` — реестр/канонизация, 2 колонки в записи,
  scoped reserve, draft isolation, cooldown, backfill, DTO.
- `services/database.py` — v48-шаг (random-store schema version; шаг v47
  `semantic_schedule` не изменён).
- `services/mca_gates.py`, `config/settings.py` — env-only cooldown (ClassVar,
  счётчик полей Settings не меняется: 472).
- `services/status_service.py` — pass-through provenance-полей.
- `web/api/routes.py` — RBAC провайдерских операций (Δ routes = 0).
- Тесты: новый `tests/test_qrng_p1_isolation.py` (24 теста); осознанные
  обновления существующих контрактных ассертов:
  `test_mca10a_random_source_block_a` (canonical provider в meta),
  `test_mca10a_random_source_block_c` (draft проверка больше не зачисляет
  партию — контракт D3), `test_goodmorning` (canonical provider в новой
  записи журнала), `test_evol014_meme_initiative` (хвост схемы 47→48),
  `test_round1025_f8_registry` + `test_mca23_planned_vs_actual` (осознанный
  re-pin sha256 `web/api/routes.py`, L-F11S-1; Δ routes = 0).

## 3. Миграция (v48)

- Версия: `_SCHEMA_VERSION_RANDOM_BATCH_PROVENANCE = 48`; шаг
  `MigrationStep(48, "random_batch_provenance_v48")`.
- DDL: `ALTER TABLE mca_random_batches ADD COLUMN config_fingerprint TEXT` /
  `external_ref TEXT`; guard `sqlite_master` + `PRAGMA table_info`; PG — no-op
  (random-таблиц в `pg_db.py` нет).
- Данные: ни одного UPDATE/DELETE в миграции; существующие строки получают
  `NULL/NULL`; backfill — отдельный идемпотентный сервисный шаг.
- Откат: старый код колонки не читает; `DROP COLUMN` не требуется.
- Доказательство: `migration.md` (PRAGMA/шаги/повторный прогон на копии).

## 4. Ограничения и честные пробелы

1. **UI-текст (P4).** В `web/index.html` подсказка у поля ключа всё ещё
   обещает зачисление проверочной партии в запас. По scope P1 UI не
   менялся; P4 обязан заменить подпись на «черновая проверка не зачисляется»
   (arch VPM `keys_random` MOVE). До P4 UI-текст расходится с API-контрактом
   (`deposited=false`) — зафиксировано, не скрыто.
2. **Producer пути `keys.random_quantum_*`.** Generic `POST /api/config`
   теперь требует global admin для этих 9 ключей; выделенный provider-route
   сохранения появится в P4. Это сознательное ужесточение (D8), не новый ACL.
3. **`provider` при lint-чтении.** `provider_id` — канонический; сырое поле
   `provider` в исторических строках не перезаписывается (по контракту).
4. **IBM/LfDR** в статусе — `configured=false`, `state=provider_unconfigured`,
   адаптеры не подключены (P2/P5); фейковых зелёных статусов нет.
5. **Live ANU-запрос** не выполнялся: P1 проверен unit/миграционными тестами
   с инъекцией `http_get`; живая проверка действующим ключом — после
   реализации/деплоя (arch §10), к P1 не относится.
6. Production DDL не применялся (только временные тестовые копии SQLite).
