# ADR-1019-6 — Retention импортированной истории `smart_messages`, включение Сна/декая/воскрешений, честные метрики памяти

- **Статус:** Accepted (реализовано в F7, Step 4 @Builder, раунд 10.19; **итерация 2 — UPD3, 15.09.2026**; **итерация 3 — фиксы ревью Батча E: fail-closed chat-слой + hard-deny чатов с `enforce`-retention, env-гейт purge + бэкап-гейт, D-7 строго по архиву; UPD4 — нейтральный сид настроек (без «VIP»)**). **Δ каталога санкционирован владельцем (UPD3 п.5).**
- **Дата:** 2026-09-15
- **Раунд:** 10.19, фича F7 `memory-retention-health` (T-1835) + итерация 2 (T-1853)
- **База:** HEAD `fd6acc7`. **Связано:** §3 (SmartModule/память), §18 (импорт истории, FTS5+GraphRAG), §21 (AGI Memory), §34 (Belief Decay + Resurrection), F-15, ADR-1018-7 (резолв настроек), **ADR-1019-8** (per-chat sentinel, сид настроек чатов, guard, изоляция).
- **AMEND:** уточняет контракт retention: **импортированные** строки (v7 `import_key`) выводятся из «вечного» состояния и получают собственный per-chat срок хранения. **AMEND (итерация 2):** D1/D2/D7 дополнены sentinel `0=вечно`, guard'ом и DDL v11 (изоляция, UPD3 п.2-3). Дополняет (не отменяет) штатный retention live-сырья (`FULL_MEMORY_RETENTION_DAYS`) и graph-retention (`GRAPH_*_RETENTION_DAYS`).

## Context

1. Чекап: `smart_messages` ≈ **2 млн строк**, БД **724 МБ**, свободно **8 из 23 ГБ**; «система копит склероз».
2. **Root cause объёма:** штатный retention обходит импорт. `_compress_purge_extract_only` (`summary_memory.py:2907-2909`) вызывает `get_smart_raw(..., exclude_imported=True)`, а `compress_and_purge` удаляет только live-сырьё после сжатия. Строки истории (`import_key IS NOT NULL`, ~1.27M из архивов, §18) графом пополняются Graph-воркером (`history_processed`), но **никогда не удаляются** (v7-миграция `database.py:800-870`).
3. Чекап: **глубокий сон 0 прогонов, воскрешения 0, охлаждение 0, 667 просрочено, 40 не подтверждено**. Причина «0»: рубильники `DREAM_ENABLED=False` (`settings.py:1090`), `DEEP_SLEEP_ENABLED=False` (`:1137`), `flags.belief_decay_enabled` (default False, `dream_worker.py:1091-1092`). Владелец (UPD п.3) подтвердил: тумблеры в UI были включены, но значения не доходили до воркеров (класс дефекта, исправленный ADR-1018-7) — F7 верифицирует и включает.
4. `web/api/memory_agi.py:357-382` не отдаёт overdue/unconfirmed/размеры — владелец не видит фактическую картину.
5. Инварианты: **данные не терять безвозвратно** (архив перед purge, бэкап), R16 (аддитивность), R17 (без текстов фактов), DDL санкционирован, но retention реализуем **без новых таблиц**.

## Decision

### D1. Retention импортированной истории — отдельный **per-chat** срок, `0 = вечно`
Вводится `limits.import_history_retention_days` (int, группа `limits_memory`, дефолт **180**, `0` = **вечно**, `<0` = невалидно → глобальный дефолт) — **Δ каталога +1** (санкция UPD3). Резолв per-chat (`resolve_setting_cached`, ADR-1018-7). Новый метод `DatabaseService.purge_imported_history(*, chat_cutoffs: dict[int, int], batch=2000, dry_run=False, chat_max_ids: dict[int, int] | None = None)` — **keyword-only allow-list**; удаляет `smart_messages WHERE chat_id IN chat_cutoffs AND import_key IS NOT NULL AND history_processed = 1 AND timestamp < chat_cutoffs[chat_id] [AND id <= chat_max_ids[chat_id]]` + FTS-строки, батчами; `dry_run` — только подсчёт (`candidates` — фактический подсчёт, НЕ `deleted`). Идемпотентно, без нового APScheduler-джоба. **Иной sentinel, чем у бюджетов:** `0` здесь = «вечно», не «запрет» (ADR-1019-8 §D2). **D-7 (ревью Батча E):** `chat_max_ids` ограничивает purge заархивированным множеством; при `candidates != archived` purge прерывается (`reason='archive_mismatch'`).

### D1a. Guard «вечного» хранения (UPD3 п.3 + D-1 ревью Батча E)
`services/retention_policy.py::imported_history_purge_allowed(chat_id) -> (allowed, days, source)`; `allowed = (days != 0)`. Маппинг `chat_cutoffs` строится **только** из разрешённых чатов; целевой чат `-1002661910336` (retention `0`) **никогда** не попадает в purge. **Fail-closed (D-1):** `worker_settings` сигнализирует `source='error'` при недоступном chat-слое (нет `ChatParamsPool`/ошибка PG); `_resolve_days` при `source=='error'` → `(0,'error')` → `allowed=False`; `run_import_retention` при любом `'error'` **отменяет прогон целиком** (`chat_layer_unavailable`), не строя cutoffs из fail-open `'default'`. **Hard-deny (defence-in-depth):** `chat_settings_seed.enforced_eternal_chat_ids()` (retention-ключ в `enforce` из `config/chat_settings_seed.json`) запрещает purge независимо от резолва (`source='seed_enforced'`). Seed `enforce`-политика (ADR-1019-8 §D4) возвращает `0` на каждом старте. Единственный call-site — `memory_maintenance.run_import_retention()` (тест-инвариант).

### D1b. Изоляция `import_key`/чекпоинтов (UPD3 п.2) — латентный cross-chat дефект
`import_key = sha256(ts|user_id|text)` (`parser.py:122-131`) **не включает `chat_id`**, а индекс `idx_smart_messages_import_key` **глобально UNIQUE** (`database.py:866`) → импорт одного контента в два чата **подавит** строку второго (`INSERT OR IGNORE`). `import_checkpoints` ключуется только `path` → второй чат видит чужой «done». **Фикс:** SQLite **v11** — `idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key) WHERE import_key IS NOT NULL` (формула ключа **не меняется** — сохраняем идемпотентность 1.27M строк); `import_checkpoints` — ключ `(path, chat_id)`. Полный аудит — spec F7 §4.6.

### D2. Архив перед purge — обязательный инвариант
Перед удалением — экспорт выборки в `backups/imported_history_<ts>.jsonl(.zst)`. Сбой архивации → **удаление не выполняется** (fail-safe). Purge запускается только после бэкапа БД (@DevOps). Progressive delivery: dry-run → бэкап → DDL v11 → батчевый purge.

**Гейт деструктивного purge (D-2, ревью Батча E, env-only — Δ каталога не растёт):** авто-крон `compress_and_purge` вызывает retention-шаг только при `IMPORT_RETENTION_ENABLED=true` (**default OFF**) и передаёт `dry_run=IMPORT_RETENTION_DRY_RUN` (**default ON**). Реальное удаление из крона требует ЯВНО `ENABLED=true` И `DRY_RUN=false`. Дополнительно — ручные `manage.py retention` (dry-run по умолчанию) / `manage.py retention --apply`. Первый прогон на проде — гарантированно dry-run.

### D3. Включение Сна/декая/воскрешений — данными, с диагностикой
- `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` резолвятся per-chat (ADR-1018-7) → включаются **данными** (per-chat override целевого чата), не хардкодом.
- `flags.belief_decay_enabled` — включается (рекомендация, глобально) с **консервативными** порогами (`limits.belief_inactivity_days`/`_decay_per_month`/`_archive_threshold` не агрессивнее текущих).
- Каждый пропуск гейта логируется с `reason=` и `source=chat|global|default` (R17-safe) — «0 прогонов» перестаёт быть необъяснимым.
- `_try_reanimate`: логируется причина «не сработало» (нет векторов/архива/ниже порога).
- **Без нового фича-флага** (прецедент 10.18); откат — данные/`git revert`.

### D4. Метрики здоровья — аддитивно (R16)
Новые `count_overdue_facts`, `count_unconfirmed_facts`, `count_smart_messages`; `memory_health_summary` += `facts_overdue`, `facts_unconfirmed`, `smart_messages_total`, `deep_sleep_runs_total`, `storage.{db_size_bytes, db_size_mb, disk_free_bytes}`. Только числа (R17); fail-open (ошибка → нули, не 500).

### D5. «667/40» — семантика, а не удаление вручную
`overdue` = `expires_at < now` и статус не терминальный; уходят штатным пересмотром (`purge_expired_graph_facts`, `memory_maintenance.review`) по существующим срокам. `unconfirmed` = `status='unconfirmed'`, сбрасываются `GRAPH_UNCONFIRMED_RETENTION_DAYS=14`. Ручной «обнуляющий» DELETE не вводится.

### D6. Разделение сроков (не смешивать семантики)
`FULL_MEMORY_RETENTION_DAYS` (live-сырьё) ≠ `import_history_retention_days` (импорт) ≠ `ARCHIVE_MEMORY_RETENTION_DAYS` (архив) ≠ `GRAPH_*_RETENTION_DAYS` (граф). Каждый — со своим смыслом и описанием в каталоге.

### D7. DDL: retention — без DDL; изоляция — SQLite v11 (**санкция 10.19**)
Удаление импорта — DELETE+FTS, новых таблиц/колонок не требует (`import_key`/`history_processed`/индексы есть с v7). **Итерация 2 добавляет ровно один DDL-шаг** (изоляция, D1b): миграция **v10 → v11** — замена глобального UNIQUE на `(chat_id, import_key)` + `import_checkpoints.chat_id`. Идемпотентно, обратимо (`DROP`/`CREATE`), применимо к существующим данным (глобальный UNIQUE сильнее пер-чат). Обратный путь — `git revert` + восстановление из архива/бэкапа. **Low (ревью Батча E):** rebuild `import_checkpoints` выполняется в ОДНОЙ транзакции (`BEGIN`/`COMMIT`, с `rollback` при ошибке) и с `DROP TABLE IF EXISTS import_checkpoints_old` до `RENAME` — повторный прогон миграции идемпотентен.

### D8. Ссылка на общий ADR
Мультичатовая модель, таблица sentinel-семантик, сид настроек чатов и guard — **ADR-1019-8**. F7 потребляет: `retention_policy`, `0=вечно`, allow-list purge, seed-`enforce`.

## Consequences

**Positive**
- Размер БД/диска стабилизируется (основной драйвер — импорт — получает срок жизни).
- «0 прогонов» становится объяснимым и включаемым; память перестаёт «склерозить».
- Владелец видит фактические метрики (overdue/unconfirmed/размеры), а не только beliefs/nodes.
- Никакого DDL; данные защищены архивом+бэкапом+dry-run.

**Negative**
- Δ каталога +1 (`import_history_retention_days`) — требует санкции и синхронных пин-тестов.
- Удаление импортированной истории необратимо после архива/бэкапа (осознанно; dry-run и срок 180 дней снижают риск).
- Включение декая/сна повышает фоновый расход LLM (митигируется бюджетами F2/F3 и консервативными порогами).
- Retention-шаг конкурирует с воркерами за БД — батчи/`jitter`, замер обязателен.
- Появляется новый артефакт-бэкап (экспорт) — место на диске в момент прогона (учитывать при 8 ГБ свободных).

## Alternatives

- **A1. Использовать `FULL_MEMORY_RETENTION_DAYS` для импорта.** Отклонено: смешивает live и импорт (разные семантики/риски; импорт уже графирован и его сырьё можно удалять раньше/позже).
- **A2. Удалить импортные строки без архива.** Отклонено: необратимо, нарушает инвариант «данные не терять».
- **A3. Оставить как есть и расширять диск.** Отклонено владельцем (724 МБ / 8 из 23 ГБ — «в двух шагах от драки за место»).
- **A4. Новый APScheduler-джоб для retention.** Отклонено: лишняя движущаяся часть; существующий крон достаточен.
- **A5. Отдельные таблицы-архивы (DDL).** Отклонено: не требуется; файловый архив + бэкап проще и обратимее.
- **A6. Агрессивный дефолт (30 дней) для импорта.** Отклонено: риск потери исторического контекста графа; 180 дней — осознанный баланс, настраивается.
- **A7. Включить `DREAM_ENABLED=True` в коде.** Отклонено владельцем (UPD п.3): лечится не флаг, а доставка настроек; включаем данными (per-chat).

## References

- `services/summary_memory.py:2793-2932`; `services/database.py:800-870,1506-1520,2272-2284,3972-4041`
- `services/dream_worker.py:1086-1163,1192-1246`; `services/memory_maintenance.py:286-313`
- `web/api/memory_agi.py:357-382`; `config/settings.py:472,474,558,1090,1137`
- `services/worker_settings.py` (ADR-1018-7 D2); `plans/current_task.md:119-121,166`
- ADR-1018-7 (`plans/archive/settings-worker-sync/adr-1018-7-settings-single-source-of-truth.md`)
- §18 (импорт истории); `plans/features/memory-retention-health/spec.md` §4.1-§4.4
- Задачи: T-1835…T-1844
