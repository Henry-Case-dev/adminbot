# Postdeploy runbook — 2.58.234 (MOD-ACL-UX-01 M4C C3)

Status: **REVIEW / READY_FOR_DEPLOY_PREPARATION — деплой только отдельной авторизацией.**
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
- Rollback/base `f232a3a30a79c074fc3d7fa75d8aa947720d76a4` (2.58.233, schema 48, DDL 0).
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
3. Текущее состояние: `git rev-parse HEAD` = `f232a3a30…`, `APP_VERSION` = 2.58.233,
   `user_version=48`, `schema_migrations` 48/48; `chat_lore_history_field_check` **ещё без**
   `'access'` (зафиксировать вывод `pg_get_constraintdef` как pre-снимок).
4. Disk: `python manage.py disk audit` (read-only); зафиксировать свободное место и объём
   бэкапа до старта.
5. **Backup до миграции:** штатный pre-deploy backup (SQLite backup API, `quick_check=ok`,
   `user_version=48`), rollback-копию не удалять; deploy-пул `keep=2`. Применение DDL не является
   поводом пропускать backup.
6. Проверить effective configuration: persisted settings/chat overrides не изменены C3;
   новых флагов C3 не вводит (audit/409/recheck действуют безусловно).

## 3. Deploy steps (только после отдельной авторизации)

1. Убедиться, что backup из §2.5 создан и `quick_check=ok`.
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
| **DDL 1** | `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='chat_lore_history_field_check';` содержит `'access'`; startup journal не содержит ошибки DDL; повторный startup идемпотентен (DROP IF EXISTS + ADD); ручной DDL **не нужен**, если startup прошёл |
| DDL statements | в коде 62 statement; новых таблиц/колонок/индексов нет; `chat_lore_history` существует в PG и отсутствует в SQLite |
| Process | ровно один `bot.py`; `systemctl show -p NRestarts admin_bot` → **0** после deploy-restart |
| Journal | `journalctl -u admin_bot --since <deploy time>`: 0 ERROR/CRITICAL/Traceback; миграционный блок завершён |
| ACL data | `bot_roles` 4 / `bot_admins` 3 / `chat_admins` 1 / custom 0; digest'ы pre==post (без изменений); audit-строк `field='access'` может ещё не быть — это нормально |
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

## 5. Rollback

1. `git -C /var/www/admin_bot reset --hard f232a3a30a79c074fc3d7fa75d8aa947720d76a4`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Проверить `/healthz` 200, version 2.58.233, schema 48, unknown startup errors нет.
5. DDL/данные: **CHECK не откатывать** — расширенное множество является superset, старому коду
   (`f232a3a3` пишет только старые значения `field`) оно не мешает. Audit-строки `access`
   остаются; удаление данных не выполняется; ручной DDL не нужен. Если startup DDL упал —
   не «чинить» вручную, зафиксировать вывод, остановиться и эскалировать (нужен отдельный
   разбор); откат кода при этом остаётся безопасным для данных.
6. Известный non-blocking остаток `C3-R1-N07`: на откате lore/oversight могут показать
   `access`-строки сырым JSON (старый SELECT не фильтрует field). Данные совместимы, секретов
   в audit нет; это не причина откладывать откат при реальной регрессии.

## 6. Ограничения

- Runbook — REVIEW; деплой не выполнялся, VERIFIED не заявлялся.
- PostgreSQL в локальной сборке отсутствует: DDL доказан исходником/тестами/superset-свойством;
  фактическое применение и constraint проверяются только здесь, postdeploy.
- C3-R1-N02…N08 — backlog, не блокируют релиз; RFL не назначаются owner QA.
- `C3-R1-N07` — описано в §5; downgrade CHECK не выполняется.
