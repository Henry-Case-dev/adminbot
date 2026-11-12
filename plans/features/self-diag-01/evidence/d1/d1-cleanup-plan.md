# SELF-DIAG-01 D1 — targeted cleanup 5 осиротевших Better Stack ключей

Дата документа: 2026-11-12. Автор: Builder (D1-closure).
Статус: **EXECUTED** — cleanup выполнен DevOps 2026-11-12 и зафиксирован
коммитом `6691ef7e`; артефакт исполнения —
`plans/features/self-diag-01/evidence/d1/cleanup-2026-11-12/`.
Этот документ — точный план + фактический результат + checklist повторной
проверки. **Повторно DELETE не выполнять**: строк в БД уже нет, повторный
прогон даст `DELETE 0` и ничего не докажет.

Границы: меняются только 5 строк `bot_settings`. Код, релиз, версия,
другие настройки, чаты, глобальный Better Stack logging — без изменений.
Значения секретов не печатаются и не коммитятся.

## 0. Объект

Ровно 5 ключей (и никакие другие):

| # | Ключ | Категория | Длина | Секрет |
|---|---|---|---|---|
| 1 | `keys.checkup_betterstack_sql_password` | keys | 66 | да |
| 2 | `keys.checkup_betterstack_sql_user` | keys | 35 | да |
| 3 | `models.checkup_betterstack_sql_host` | models | 40 | нет |
| 4 | `models.checkup_betterstack_sql_query` | models | 2 | нет |
| 5 | `models.checkup_betterstack_sql_table` | models | 20 | нет |

Запрещено: `TRUNCATE`, `DELETE ... LIKE '%betterstack%'`, удаление других
ключей, очистка таблицы, переписывание релизных записей.

## 1. Предусловия: доказанное отсутствие потребителей

Проверено на `2587616759de31283585ffc105c91e7193c2e89e` (2.58.197):

| Проверка | Результат |
|---|---|
| `git grep -n -i -E 'checkup_betterstack\|CHECKUP_JOURNALCTL_CMD\|models_checkup\|keys_betterstack' -- services handlers config web bot.py main.py` | 3 строки, все — мёртвые id в `web/app.js:92,192,193`; потребителей нет |
| `git grep -n 'create_subprocess_shell' -- services handlers config web bot.py` | rc=1, 0 |
| `param_catalog.get_by_pg_key(<5 ключей>)` | `None` для всех 5 |
| `services/param_catalog.py`: группы `models_checkup`, `keys_betterstack` | отсутствуют |
| `config/settings.py`: `CHECKUP_BETTERSTACK_SQL_*`, `CHECKUP_JOURNALCTL_CMD` | атрибутов нет; есть только `CHECKUP_LOG_WINDOW_LINES`/`CHECKUP_LOG_UNIT` |
| `services/pg_db.py`: упоминания `checkup` | 0 → пере-сида при старте нет |
| `POST /api/config` с любым из 5 ключей | 422 «неизвестный ключ» (`get_by_pg_key=None`); для известных `keys.*` действует отдельный BYOK-путь |
| `POST /api/config/keys/own` (global) | allowlist `GLOBAL_SECRET_KEYS = {keys.image_api_key}` → чужой ключ = 422 |
| глобальный logging (`services/betterstack_handler.py`, `services/external_log.py`, env `BETTERSTACK_HOST`/`LOGTAIL_SOURCE_TOKEN`) | не трогается (D1-11) |

`/api/config` перебирает `ConfigCache.get_all()`; после удаления строк и
рестарта элементов нет. `get_all()` фильтрует `_REMOVED_SETTING_KEYS`
(только 2 `temporal.*`), но для этих 5 ключей фильтр не нужен: строк нет,
синтетика `_synthetic_group_items` строится только по `REGISTRY`, а этих
ключей в нём нет.

## 2. Pre-check (read-only, без печати значений)

```sql
SELECT key, length(value::text) AS value_len, category
FROM bot_settings
WHERE key IN (
  'keys.checkup_betterstack_sql_password',
  'keys.checkup_betterstack_sql_user',
  'models.checkup_betterstack_sql_host',
  'models.checkup_betterstack_sql_query',
  'models.checkup_betterstack_sql_table'
)
ORDER BY key;
```

Ожидание: ровно 5 строк с длинами 66/35/40/2/20. Плюс контроль, что нет
других Better Stack ключей:

```sql
SELECT key FROM bot_settings
WHERE key ILIKE '%betterstack%'
  AND key NOT IN (<те же 5 ключей>);
```

Ожидание: 0 строк. `SELECT *` и вывод значений запрещены.

## 3. Backup (ровно 5 строк, вне репозитория)

Требования:

- выгрузить только 5 строк: `key`, `value` (JSONB как есть), `category`,
  `updated_at`;
- файл создаётся с правами `0600`, каталог `0700`;
- хранится **вне Git-репозитория**:
  `WorkspaceData/backups/self-diag-01/` (локально) и
  `/root/adminbot_backup_self-diag-01/` (сервер) — точные пути и sha256
  фиксируются в evidence;
- значения не попадают в чат, отчёт, git или логи; в evidence — только
  имена, длины, количество строк и sha256 файла.

Фактически выполнено (`cleanup-2026-11-12.md` §2):

| Параметр | Значение |
|---|---|
| серверный backup | `/root/adminbot_backup_self-diag-01/bot_settings_betterstack_2026-11-12.json` (`0600`) |
| локальная копия | `WorkspaceData/backups/self-diag-01/bot_settings_betterstack_2026-11-12.json` |
| размер / строки | 1327 байт / 5 |
| sha256 | `706b61f3282002ee8e801c89035583fd33350457daf1f8b6840d0b8e158dd969` |
| restore-скрипт | `/root/adminbot_backup_self-diag-01/restore_bot_settings_betterstack.py`, sha256 `157225a0a857f54a234cafda4edc67b68ed3d23bb44c5aef82342383a5bef8f2` |

Проверка копии (без печати значений): файл существует, размер 1327,
sha256 совпал, внутри ровно 5 ключей из §0.

## 4. Удаление — одна транзакция

```sql
BEGIN;
DELETE FROM bot_settings
 WHERE key IN (
   'keys.checkup_betterstack_sql_password',
   'keys.checkup_betterstack_sql_user',
   'models.checkup_betterstack_sql_host',
   'models.checkup_betterstack_sql_query',
   'models.checkup_betterstack_sql_table'
 )
RETURNING key;
COMMIT;
```

Ожидание: `DELETE 5`, ровно 5 возвращённых ключей из §0, набор совпадает
побайтово. Если вернулось ≠5 или другой набор — `ROLLBACK`, разбор, не
повторять вслепую. Никаких `LIKE`, `TRUNCATE`, других ключей.

## 5. Post-check

1. **БД:**

   ```sql
   SELECT count(*) FROM bot_settings WHERE key IN (<5 ключей>);          -- 0
   SELECT key FROM bot_settings
    WHERE key ILIKE '%betterstack%' OR key LIKE 'models.checkup%';        -- 0
   ```

2. **Config cache:** сразу после DELETE процесс ещё держит старый
   in-memory снапшот (`ConfigCache._settings` читается на старте; `reload()`
   вызывается только при записях через API). Поэтому один рестарт
   обязателен: `systemctl restart admin_bot`.
3. **`GET /api/config`** (реальный HTTP, global admin — самый широкий
   ответ): нет ни одного item с
   `keys.checkup_betterstack*` / `models.checkup_betterstack*`;
   `items` уменьшился ровно на 5 (факт: 623 → 618); остальные 6 checkup
   настроек на месте. Для non-admin секретные `keys.*` и раньше были
   скрыты, а `models.*` после удаления отсутствуют.
4. **`/healthz`**: `{"status":"ok","version":"2.58.197"}`; unit `active`,
   `NRestarts=0`; новых `Traceback/ERROR/CRITICAL` после рестарта нет.
5. **Повторная проверка БД после рестарта** (пере-сид): `count=0`.
6. **Git:** HEAD/branch не изменились, tracked-правок 0.

## 6. Откат

```bash
ssh root@<prod> "cd /var/www/admin_bot && \
  venv/bin/python /root/adminbot_backup_self-diag-01/restore_bot_settings_betterstack.py && \
  systemctl restart admin_bot"
```

Скрипт делает upsert 5 строк из backup в одной транзакции (JSONB
сохраняется). После отката: `count=5`, `/api/config matched=5`,
`/healthz` 200, затем повторная проверка. Если серверный backup утрачен —
залить локальную копию с тем же sha256 в ту же директорию (`0600`) и
повторить. Откат не исполнялся: проверка после удаления прошла.

## 7. Фактический результат (2026-11-12, production 2.58.197)

| Шаг | Факт |
|---|---|
| pre-count | `PRE_COUNT=5`, `PRE_EXTRA_BETTERSTACK=0` |
| backup | 5 строк, sha256 `706b61f3…b8e158dd969` (см. §3) |
| DELETE | `DELETE_RETURNED=5`, набор совпал |
| БД после | `POST_COUNT=0`; `key ILIKE '%betterstack%'` = 0 |
| `/api/config` до рестарта | 623 items, matched 5 (ожидаемо — RAM) |
| рестарт | один, `ActiveEnter=2026-11-12 10:28:42Z`, healthz ok |
| `/api/config` после | **618 items, matched 0**; 6 checkup-настроек на месте |
| БД после рестарта | `POST_RESTART_DB_COUNT=0` (пере-сида нет) |
| журнал | 233 строки, `TB=0 ERR=0 CRIT=0 WARN=1`; единственный Traceback — до изменений (таймаут MCA) |
| git | HEAD/branch те же, tracked-правок 0 |

## 8. Checklist повторной проверки (read-only, для Reviewer/DevOps)

Ничего из этого Builder не исполнял (production не трогал). Проверки
идемпотентны и не меняют данные:

1. `SELECT key, length(value::text) FROM bot_settings WHERE key IN (<5>);`
   → 0 строк.
2. `SELECT key FROM bot_settings WHERE key ILIKE '%betterstack%';` → 0.
3. `SELECT count(*) FROM bot_settings;` — 6 checkup-настроек
   (`flags.checkup_enabled`, `flags.checkup_memory_metrics_enabled`,
   `limits.checkup_cooldown_seconds`, `limits.checkup_max_input_symbols`,
   `limits.checkup_max_symbols`, `prompts.checkup_system_prompt`) на месте.
4. `GET /api/config` (global admin): 0 items с этими ключами; item-count
   соответствует текущей БД (после cleanup — 618 на том релизе).
5. `GET /healthz` → 200, version 2.58.197; `systemctl is-active admin_bot`
   → active; в журнале после рестарта нет `Traceback/ERROR/CRITICAL`.
6. Backup: файл на месте, sha256 совпадает, restore-скрипт компилируется;
   значения не печатать.

## 9. Почему не нужна правка кода

- `_REMOVED_SETTING_KEYS` — механизм для **сохранённых** PG-значений
  удалённых настроек (FC-06C: строки в БД намеренно не трогались). Здесь
  строки удалены, поэтому добавлять 5 ключей в фильтр — мёртвый код,
  который навсегда подавит любой будущий ключ с таким именем.
- Каталог/`Settings` уже не содержат ключей; `REGISTRY`-синтетика их не
  воссоздаёт; `pg_db._seed_settings` их не сеет; `POST /api/config` и
  BYOK-allowlist отвергают запись.
- Существующие durable-гарды (`tests/test_checkup_logs_fetcher.py`,
  `tests/test_settings_helpers.py`, `tests/test_frontend_tab_mapping.py`,
  `tests/test_param_catalog.py`) покрывают отсутствие ключей в
  коде/каталоге. D1-10 — про данные, а не про новый код.

Локальный focused-пробник (без БД/сети, на 25876167) подтвердил механизм:
со «старым» RAM-снапшотом `ConfigCache.get_all()` отдаёт все 5 ключей; после
пустой перезагрузки — `0`, синтетика `_synthetic_group_items` их не
воссоздаёт (в выдаче остаётся только легитимный
`prompts.checkup_system_prompt`). Отсюда обязательный рестарт после DELETE
и отсутствие необходимости в фильтре-коде.

Итог: **изменений кода/тестов нет**. Любая правка здесь была бы
расширением продукта без требования.

## 10. Риски и ограничения

- Значения 5 строк лежат в двух backup-файлах вне репозитория; их нельзя
  коммитить, копировать в отчёты или печатать. При утрате обоих файлов
  откат невозможен — это осознанная цена hygiene.
- Другие окружения (если появятся) не проверялись: план привязан к
  production 2.58.197.
- После удаления секрет остаётся в старых резервных копиях БД, если они
  существуют; это не переписывается (D1-10 прямо запрещает переписывать
  исторические релизные записи).
