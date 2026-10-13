# W-A3 (D02) — group→supergroup migration: link-before-migrate

Lane: W-A3, Wave A, ASAP 8 v6. Baseline HEAD `1e98027` (release 2.58.77). Status: **DONE (код+тесты в дереве, НЕ закоммичено)**.

## Root cause (подтверждён воспроизведением)

`handlers/chat_lifecycle.py::on_chat_migrated` вызывал `add_link(old,new)` (:243) ДО `migrate_profile` (:244). `ChatLoreStore.migrate_profile` первым делом резолвил old по chat_links → `resolved_old == new` → ранний no-op `{"moved": False, "merged": False}` ДО чтения старого профиля. Хендлер видел «профиля new нет» → создавал ПУСТОЙ профиль (`upsert_profile_on_join`), старый осиротевал (данные читались только через link-resolve). merge-ветка Q9 в реальном флоу недостижима. Дополнительно найден **дефект D4 из v5**: `COPY_ADMINS_SQL` (merge-ветка) не копировал `role_name` → вставка получала DB default `'local_admin'` (pg_db.py:151-153) → **эскалация moderator → local_admin** при переезде. И третье: merge-ветка теряла `relations`/`relations_enabled`/`chat_params`/`gates_opt_in`.

## Fix (минимально-рискованный: store не доверяет голому link)

Порядок вызовов хендлера сохранён (add_link сначала — резолв старых id жив даже при сбое миграции; контракт test_chat_lifecycle/test_asap7 не сломан). Изменён `services/chat_lore_store.py`:

1. **Link existence ≠ proof of migration**: если `resolved_old == new`, store проверяет профиль под ИСХОДНЫМ id — есть → досносит миграцию (`resolved_old = old_chat_id`, INFO-лог); нет → честный no-op (переезд завершался ранее, duplicate event не пишет второй remap).
2. **`COPY_ADMINS_SQL`**: `role_name` копируется явно (`SELECT ..., role_name`) — точная роль, default не применяется. `MOVE_ADMINS_SQL` (move-ветка) роль и так сохранял (UPDATE строки целиком) — покрыто тестом.
3. **`MERGE_PROFILE_SQL` + Python-мерж** (`_merge_json_maps`): в merge переносятся `relations`, `relations_enabled` (old OR new), `chat_params` (пер-ключевой union: новое живое значение приоритетно, старое заполняет пробелы; внутри dict-ключей — то же), `gates_opt_in` (old OR new). migrate-выборка расширена `chat_params, gates_opt_in`.
4. **`MOVE_HISTORY_SQL`** (обе ветки): `chat_lore_history` переезжает на новый id — timeline лора живой на новом чате (раньше читался только по старому id), remap-строка ровно одна на переезд.

Идемпотентность/атомарность: link и профиль — РАЗНЫЕ транзакции (add_link коммитится первой), сама миграция — одна транзакция (профиль+link+админы+история+NOTIFY) → partial failure откатывается целиком, ретрай тем же событием доводит.

## Матрица миграции (проверено тестами на реальном store)

| Что | Move (профиля new нет) | Merge (new занят) |
|---|---|---|
| Лор/настройки chat_profiles (manual/auto/auto_enabled/period/window/is_active/last_auto_at) | строка целиком | Q9 (manual — старый, auto — новый, bool OR, max ts) |
| `relations` (participants: стадии/заметки) | строка целиком | **БЫЛО: терялись → FIX** union, новое приоритетно |
| `relations_enabled` | строка целиком | **БЫЛО: терялось → FIX** old OR new |
| `chat_params` (overrides = per-chat параметры, gates = feature opt-ins, perm_overrides, keys-мета, module state) | строка целиком | **БЫЛО: терялось → FIX** пер-ключевой union |
| `gates_opt_in` | строка целиком | **БЫЛО: терялось → FIX** old OR new |
| `chat_admins` + точная роль | UPDATE строки (роль сохраняется) | **БЫЛО: роль терялась → эскалация до local_admin → FIX** (явный role_name) |
| `chat_links` | upsert в той же транзакции | то же |
| `chat_lore_history` | **БЫЛО: оставалась под old → FIX** переезжает | то же |
| remap-строка истории | 1 шт (дубликат события не добавляет) | 1 шт |
| NOTIFY old+new | да | да |

Вне store (отдельные seam'ы, не в WRITE_SCOPE, задокументировано):
- **aliases/self-model identity**: SQLite `chat_id_migrations` — хендлер уже регистрирует через `message_identity.register_chat_id_migration` (MCA-03, :222-240); резолв — `message_identity.resolve_chat_id`. Не менялся.
- **summary/memory-таблицы (PG)**: домен `services/summary_memory.py` — НЕ мигрируют (как и до фикса); перенос векторов/сводок — отдельный D-ID (D06-смежное), в мой write-scope не входит (summary_* — DO_NOT_TOUCH).

## Тесты

НОВЫЙ `tests/test_asap8_v6_wa3_migration.py` (TEST-LIFECYCLE: REGRESSION owner=ASAP8-V6/D02) — **реальный хендлер** (`handlers.chat_lifecycle.on_chat_migrated`) + **реальный `ChatLoreStore`** (боевой SQL без изменений) на **реальной SQLite-базе**: движок исполняет те же statements (явные BEGIN/COMMIT/ROLLBACK = настоящая атомарность/откат, RETURNING, upsert ON CONFLICT; `$N`→`?` с пермутацией аргументов по номерам, `::type`-касты, `now()`, перехват pg_notify). Никаких FakeStore-имитаций успеха. 13 тестов:

- RED-негативы (проверены на pre-fix коде через `git stash` — **11/13 падают**, в т.ч. все негативные): link-before-migrate переносит профиль с данными; store-level миграция при предзаписанном link; **injected failure halfway (move: срыв на MOVE_ADMINS; merge: срыв на DELETE) → полный откат → ретрай тем же событием доводит, без сирот/дублей remap**; duplicate event → без второй remap/перезаписи/дублей админов; роль-эскалация (moderator остаётся moderator в merge-COPY); матрица merge/move (params/gates/gates_opt_in/relations/module-state-override); история переезжает; NOTIFY; resolve-цепочка; C9-контракт «old отсутствует → новый профиль + gates».
- Адаптер-детали в шапке тест-файла; схема SQLite = боевая pg_db-схема (включая `role_name DEFAULT 'local_admin'` — без которого эскалация не воспроизводится).

Существующие сюиты — зелёные без правок (осознанных обновлений тестов НЕ потребовалось):

```
py -m pytest tests/test_asap8_v6_wa3_migration.py tests/test_chat_lifecycle.py tests/test_asap7_chat_lifecycle.py tests/test_chat_lore_store.py tests/test_chat_lore.py -q
→ 115 passed
tests/test_chat_lore_participant_names_round1024.py tests/test_chat_lore_api.py → 40 passed
tests/test_mca03_message_identity_round1027.py → 25 passed
```

RED-доказательство (pre-fix, stash src-правок): `11 failed, 2 passed` — падают в точности сценарии регрессии (link-before-migrate, оба failure-halfway+retry, duplicate, роль-эскалация, матрица merge/move, NOTIFY/история).

## Files changed

- `services/chat_lore_store.py` — fix (SQL-константы + `_merge_json_maps` + `migrate_profile`).
- `handlers/chat_lifecycle.py` — только комментарий к seam-контракту (логика не менялась).
- `tests/test_asap8_v6_wa3_migration.py` — новый (13 тестов).

## Incidental findings

- `related-nonblocking`: цепочка old→mid→new с «застрявшим» профилем под mid при resolve= new — store вернёт no-op (сирота mid). Telegram не мигрирует supergroup повторно, кейс гипотетический; поведение не хуже pre-fix. Зафиксировано здесь, не чинено.
- `unrelated/pre-existing`: `web/api/chat_lore.py::get_history` читает историю по raw chat_id без resolve — после ДАННОГО фикса неактуально для миграции (история переезжает), но для remap через API-эндпоинт то же свойство теперь обеспечено migrate_profile. Дефекта не осталось.
- `uncertain`: `_profile_seen`-кэш хендлера (in-memory, сбрасывается рестартом) — после миграции содержит new; на старый id может указывать до рестарта; чтений профиля old кэш не кэширует. Влияния на контракт нет.

R17: секретов в коде/тестах/отчёте нет.
