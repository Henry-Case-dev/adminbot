# Postdeploy runbook — 2.58.234 (MOD-ACL-UX-01 M4C C3)

Status: **REVIEW / FIXED (delta-review B01) — READY_FOR_RE_REVIEW — деплой только отдельной авторизацией.**
В этом артефакте нет деплоя, SSH, production DB, LLM-вызовов, live-chat и positive ACL-writes.
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Старый VPS `198.46.175.136` декомиссован и не является rollback-целью.

## 1. Preconditions

- Release branch `release/mod-acl-m4c3-2.58.234`.
- Content tip `3b18ca1dd0a3e6c9c528bcbb1a2a975276dcf49f`: 4 cherry-picked коммита C3
  + завершение version wave. Version **2.58.234**, schema **48**, PG DDL **1**.
- Reviewed candidate `0f808810d92fcb9116e2549c8106b5f360b9229c`; review
  `plans/features/mod-acl-ux-01/evidence/m4c/c3/review-r1.md` @ master `e96314dc7` —
  **APPROVED_FOR_RELEASE_PREPARATION** (R1.1); `C3-R1-N02…N08` backlog-only.
  Product bytes идентичны review (`git diff 5bf340dd0..3b18ca1dd -- services web config` пуст).
- Rollback/base `f232a3a30a79c074fc3d7fa75d8aa947720d76a4` (2.58.233, schema 48, DDL 0) —
  **raw только при `access_rows=0`**. При наличии `field='access'` строк — prepared target
  **`be23f5eff7287b02e2e91d9b5a5af2b474198beb`** (`rollback/mod-acl-m4c3-ddl-compatible`),
  только CHECK 11 значений; proof `rollback-ddl-proof.md/json`.
- **DDL 1:** только CHECK `chat_lore_history.field` += `'access'` (DROP CONSTRAINT IF EXISTS +
  ADD, superset). Новых таблиц/колонок/индексов нет; SQLite остаётся 48 и не мигрирует.
- Не менять `.env`, persisted settings, chat overrides, роли, промпты, ключи, gates и модель.
  Не запускать reindex, backfill, cache flush, live LLM-вызовы и положительные ACL-записи.

## 2. Pre-deploy preflight (read-only, без секретов)

1. **Single-process — обязательное условие.** `systemctl show admin_bot -p MainPID -p NRestarts`
   и `pgrep -af bot.py`: ровно **1** процесс `bot.py`, MainPID = этот PID, `ExecStart` без
   `--workers`. Если >1 процесса — **stop/escalate**, не продолжать: ревизии ролей рассчитаны
   на single-process (precondition hardening §4.6).
2. ACL-снимок (PostgreSQL, read-only; сверить с 2.58.233):
   - `bot_roles` **4** (`admin`, `local_admin`, `moderator`, `user`; все `is_custom=false`),
   - `bot_admins` **3** (`admin` 1, `moderator` 2), `chat_admins` **1**,
   - custom-роли **0**; custom с `section.access`/wildcard **0**,
   - покрытие назначенными global admin/wildcard ≥1 — **не требуется** менять.
3. **Constraint/DISTINCT (N02) — до restart:**
   ```sql
   SELECT pg_get_constraintdef(oid) FROM pg_constraint
    WHERE conname = 'chat_lore_history_field_check';
   -- ожидаемо: ровно 10 старых значений, БЕЗ 'access':
   -- 'manual','auto','auto_enabled','auto_period_hours','auto_window_hours',
   -- 'remap','chat_admin','chat_params','chat_keys','gates'
   SELECT DISTINCT field FROM chat_lore_history ORDER BY field;
   -- ожидаемо: подмножество 10 старых значений
   SELECT count(*) FROM chat_lore_history WHERE field = 'access';
   -- ожидаемо: 0 до forward-деплоя
   ```
   Если constraint отличается или найден неизвестный `field` — **stop/escalate**: forward ADD
   на старте упадёт (fail-closed), сервис будет недоступен до разбора.
4. Текущее состояние: `git rev-parse HEAD` = `f232a3a30…`, `APP_VERSION` = 2.58.233,
   `user_version=48`, `schema_migrations` 48/48.
5. Disk/size: `python manage.py disk audit`; `SELECT pg_size_pretty(pg_total_relation_size(
   'chat_lore_history'))` и свободное место; объём PG-бэкапа не должен превышать доступное место
   (P0-PROD-DISK-01).
6. **Backups до миграции:**
   - SQLite: штатный pre-deploy backup (SQLite backup API, `quick_check=ok`, `user_version=48`),
     rollback-копию не удалять; deploy-пул `keep=2`;
   - PostgreSQL: targeted logical backup **до DDL** —
     `pg_dump --format=custom --data-only --no-owner --no-privileges -t chat_lore_history
     -t bot_roles -t bot_admins -t chat_admins -f <backup>.dump "$DATABASE_URL"`; проверить
     размер, sha256 и восстановимость (`pg_restore -l`/row counts), хранить до завершения
     release/rollback-окна, затем удалить. SQLite backup PG-DDL не покрывает.
7. Проверить effective configuration: persisted settings/chat overrides не изменены C3;
   новых флагов C3 не вводит (audit/409/recheck действуют безусловно).

## 3. Deploy steps (только после отдельной авторизации)

1. Убедиться, что оба backup из §2.6 созданы: SQLite `quick_check=ok` и PG dump (размер/sha256,
   row counts). Без PG-бэкапа деплой не начинать.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (или checkout authorized release SHA).
4. Проверить: `git status --porcelain --untracked-files=no` пуст; `APP_VERSION` = `2.58.234`;
   `git rev-parse HEAD` = authorized SHA; product diff от `3b18ca1dd` пуст.
5. Записать manifest по **фактическому** checkout SHA **до** restart:
   `python tools/release_manifest.py` (не `--dry-run`). Ожидаемо `version=2.58.234`,
   `effect=deploy`, `dirty_tracked=false`, `previous_sha=f232a3a3…` / `previous_version=2.58.233`.
6. `sudo systemctl restart admin_bot` — startup применит DDL 1 до обслуживания запросов.
7. Немедленно выполнить §4. Не объявлять VERIFIED по runbook: нужен фактический deployed SHA,
   effective state и postdeploy evidence.

## 4. Postdeploy checks (read-only; без положительных записей)

| Проверка | Ожидание |
|---|---|
| Local HTTP (без proxy) | `/healthz` → 200 |
| Public HTTP `https://<host>/healthz` | 200 |
| Version | runtime `2.58.234`; manifest version = 2.58.234 |
| Checkout/identity | `git rev-parse HEAD` = manifest `deployed_sha`; identity probe → `code=verified_deployed`, `conflict=[]`, version provenance consistent |
| Schema | `user_version=48`; `schema_migrations` max/count 48; SQLite не мигрировал |
| **DDL 1** | `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='chat_lore_history_field_check';` — ровно **11** значений, содержит `'access'`; `SELECT DISTINCT field FROM chat_lore_history` — подмножество 11; `count(*) WHERE field='access'` не уменьшился; startup journal без ошибки DDL; повторный startup идемпотентен (DROP IF EXISTS + ADD); ручной DDL **не нужен**, если startup прошёл |
| DDL statements | в коде 62 statement; новых таблиц/колонок/индексов нет; `chat_lore_history` существует в PG и отсутствует в SQLite |
| Process | ровно один `bot.py`; `systemctl show -p NRestarts admin_bot` → **0** после deploy-restart |
| Journal | `journalctl -u admin_bot --since <deploy time>`: 0 ERROR/CRITICAL/Traceback; миграционный блок завершён |
| ACL data | `bot_roles` 4 / `bot_admins` 3 / `chat_admins` 1 / custom 0; digest'ы pre==post (без изменений); `access`-строки не удалять; их появление после ACL-действий — нормально |
| Served bytes | local == public sha256 для `/web/app.js`, `/web/index.html`, `/web/static/app.css`; `index.html` содержит version query `?v=2.58.234`; served байты соответствуют git (с учётом query) |
| Auth `POST /api/admins` | без initData → **401** |
| Audit `GET /api/access/audit` | без initData → **401**; для non-admin initData → **403** (если реальная non-admin сессия недоступна — зафиксировать RFL, не owner QA); для global admin → 200 |
| Reset/409 boundary | UI `#/access/local` показывает свёрнутый блок перекрытий и «Сбросить в наследование», `#/access/roles` — draft/save bar/audit-панель; **никаких** положительных PUT/DELETE/POST в проверке не выполнять; 404/409-карточки проверяются на локальном стенде, не на production |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); свободное место проверено |
| Temp artifacts | на production не оставлять probe DB, snapshot'ы, e2e-скриншоты, копии БД; всё временное удалено (P0-PROD-DISK-01) |

Дополнительно (агентские проверки, не positive-write):
1. `GET /api/roles` / `GET /api/admins` / `GET /api/roles/tree` без initData → 401;
   с admin-сессией — 200, `revision` присутствует в `/api/roles`.
2. `GET /api/access/param_permissions` с admin-сессией — 200, у items есть `updated_at`;
   `GET /api/access/audit?limit=1&scope=global` — 200/[] или строки без значений/промптов.
3. Проверить, что `field='access'` не попадает в `/api/chat_lore/{id}/history` и oversight.
4. Если обнаружен 403/409/503 в обычном чтении — зафиксировать точный код/тело и evidence;
   **не** «исправлять» production положительными записями.
5. Live TMA, натуральный двухоконный 409, натуральный отзыв в середине долгого запроса и
   реальная local_admin-сессия — **RFL** (названный gap), не owner QA.

## 5. Rollback (B01 — corrected)

**Запрет:** raw `f232a3a3` **нельзя** использовать, если в `chat_lore_history` есть хотя бы одна
строка `field='access'`. Old code на каждом старте делает `DROP` + `ADD CHECK (10 значений)`;
ADD падает SQLSTATE 23514, DROP уже закоммичен → CHECK отсутствует; `ConfigCache.init()`
перехватывает ошибку → roles/admins пусты, ACL 503, владелец не global_admin. Это воспроизведено
на PostgreSQL 18.7: `rollback-ddl-proof.md/json`.

1. **Pre-rollback gate (read-only, до checkout):**
   ```sql
   SELECT count(*) FROM chat_lore_history WHERE field = 'access';
   SELECT DISTINCT field FROM chat_lore_history ORDER BY field;
   SELECT pg_get_constraintdef(oid) FROM pg_constraint
    WHERE conname = 'chat_lore_history_field_check';
   ```
   - `access_rows=0` и `DISTINCT field` ⊆ 10 старых значений → **raw `f232a3a3` разрешён** (2A).
   - `access_rows>0` → raw **запрещён**; выбрать **2B** (prepared target, default) или **2C**
     (отдельно авторизованный metadata-only cleanup). Не продолжать без выбора.
2. **Backup перед rollback:** свежий targeted `pg_dump` `chat_lore_history` + `bot_roles` +
   `bot_admins` + `chat_admins` (см. §2.6), проверить размер/sha256/восстановимость; SQLite
   rollback-копия сохраняется. Без PG-бэкапа rollback не начинать.
3. **2A. Raw `f232a3a3` (только gate=0):**
   - `git checkout f232a3a30a79c074fc3d7fa75d8aa947720d76a4`; `python tools/release_manifest.py
     --effect rollback`; `sudo systemctl restart admin_bot`;
   - проверить: `/healthz` 200, version 2.58.233, CHECK **10** значений (без `access`),
     `access_rows=0`, `roles`/`admins` не пусты, `GET /api/roles` 200 (не 503), `NRestarts=0`,
     journal без DDL-ошибок.
4. **2B. Prepared rollback target (default при access_rows>0):**
   - target **`be23f5eff7287b02e2e91d9b5a5af2b474198beb`**, branch
     `rollback/mod-acl-m4c3-ddl-compatible` (от `f232a3a3`, только CHECK 11 значений;
     `services/pg_db.py` blob `0174c28b…` идентичен forward; `APP_VERSION=2.58.233`);
   - `git fetch --prune && git checkout be23f5eff…`; `python tools/release_manifest.py
     --effect rollback` (version 2.58.233, `deployed_sha` = target, previous = 2.58.234);
   - `sudo systemctl restart admin_bot`;
   - проверить: `/healthz` 200, version 2.58.233, CHECK **11** значений с `access`,
     `access_rows` не уменьшился, `DISTINCT field` ⊆ 11, `roles`/`admins` не пусты,
     `GET /api/roles` 200 (не 503), `NRestarts=0`, journal без DDL-ошибок; startup DDL применён;
   - идемпотентность: повторный restart в окне rollback должен пройти (62/62; доказано на
     scratch PG); если окно не позволяет — зафиксировать constraint и отложить второй restart.
5. **2C. Authorized metadata cleanup (альтернатива, отдельная авторизация):** экспортировать
   компактные evidence (count/ids/хеши), `DELETE FROM chat_lore_history WHERE field='access'`
   **только** эти строки, повторно проверить `access_rows=0` и `DISTINCT field` ⊆ 10, затем
   выполнить 2A. Это разрушает audit-след; по умолчанию **не** применять. Без авторизации
   cleanup запрещён.
6. Если startup DDL упал: **stop/escalate**, не «чинить» вручную; восстановить
   `chat_lore_history` + ACL-таблицы из PG dump, зафиксировать вывод. Downgrade CHECK и ручной
   DDL не выполняются; данные не удаляются (кроме явно авторизованного 2C).
7. `C3-R1-N07` (исправленная формулировка): на prepared target старые lore/oversight-readers
   могут показать `access`-строки сырым JSON (косметика; секретов/потери данных нет). При 2C
   таких строк нет. Это не причина откладывать откат при реальной регрессии.

## 6. Ограничения

- Runbook — REVIEW / FIXED (B01); деплой не выполнялся, VERIFIED не заявлялся.
- DDL и обе rollback-ветки доказаны на **PostgreSQL 18.7** (PGlite 0.5.17, локальный scratch):
  raw old + `access` → 23514/CHECK absent; prepared target 62/62 дважды → CHECK 11, строка
  валидна; `access_rows=0` → raw old успешен. Production-применение проверяется здесь,
  postdeploy.
- B01 исправлен (prepared target + proof); delta-N01/N02/N03/N04 — backlog/accuracy, продукт не
  расширялся; `C3-R1-N02…N08` остаются backlog; RFL не назначаются owner QA.
- Raw `f232a3a3` допустим только при `access_rows=0`; prepared target — не raw.
