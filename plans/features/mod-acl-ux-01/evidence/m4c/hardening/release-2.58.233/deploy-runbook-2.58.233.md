# Deploy runbook — 2.58.233 (MOD-ACL-UX-01 M4C ACL-hardening S1/S2/S3)

Status: **REVIEW / READY_FOR_DEPLOY_PREPARATION — deploy only by separate authorization**.
В этой сборке не было деплоя, SSH, production DB, LLM-чата, изменения ключей/моделей/настроек,
миграций или DDL. Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit
`admin_bot`. Старый VPS `198.46.175.136` декомиссован и не является rollback-целью.

## 0. Обязательное условие: один процесс

S1/S2 сериализуют ACL-мутации через **per-app** `asyncio.Lock` (`web/api/routes.py`,
`_acl_mutation_lock`). Такой lock не даёт глобальной атомарности между процессами.

**До любого деплоя, read-only:**

```bash
systemctl show admin_bot -p MainPID -p NRestarts
pgrep -af bot.py
```

- Ожидается **ровно один** процесс `bot.py` (MainPID = единственный PID; `pgrep` — одна строка,
  допустим сам `pgrep`/shell-паттерн не в счёт — проверять фактический список).
- **Если процессов больше одного — остановиться, не деплоить и эскалировать Architect.**
  Альтернатива (PostgreSQL advisory lock в той же транзакции, без DDL) — отдельное
  архитектурное решение, а не скрытая правка на деплое.
- Дополнительно зафиксировать число потоков/воркеров: systemd unit штатно
  `ExecStart=…/python bot.py`, без `--workers`; `uvicorn.run()`/потоки запрещены (R2).
- Результат preflight записать в deploy evidence (фактические PID/команда, не «ок»).

## 1. Preconditions

- Release branch `release/mod-acl-hardening-2.58.233`.
- Content tip (product/test bytes) `aada3af8308149b989c543fa575b22c5736c17df`: 3 cherry-picked
  коммита кандидата (`3b9909447` S1/S2/S3, `523b137df` evidence, `c67fd490f` tests/evidence) +
  стандартный bump 2.58.232 → 2.58.233. Version **2.58.233**, schema **48**, DDL **0**.
- Reviewed candidate: `c67fd490ff11f7c72bdd6cf82bef5513a8b29b3f`, product
  `3b9909447982eadffb0c20beb266870b21eb2a3a`. Review:
  `plans/features/mod-acl-ux-01/evidence/m4c/hardening/review-r1.md` @ master `3b7041024` —
  **APPROVED_FOR_RELEASE_PREPARATION**, `M4C-HARD-R1-N01` backlog-only. Product bytes релиза
  идентичны кандидату (`git diff c67fd490f..HEAD -- services web` пуст).
  Contract: `plans/features/mod-acl-ux-01/evidence/m4c/acl-hardening-contract-2026-11-22.md`
  (`1da5dd5b9`). Не деплоить неотревьюенные ретраи или изменённые байты.
- Rollback/base: `462568ed7662cf5786a543bce8ecb6618e073c87` (2.58.232, schema 48, DDL 0).
- Product scope: `web/api/routes.py` (5 `requires_global_admin()` guards, S2 lockout guards,
  per-app lock), `services/roles.py` (аддитивные pure-helpers I1/I2), `services/access_preview.py`
  (только `consumers` metadata `section.access`), `web/index.html` (admins-модалка read-only для
  non-global), hardening tests/tool/evidence и version wave.
  `web/api/access.py`, `web/api/deps.py`, `services/permissions.py`, `services/pg_db.py`,
  `services/config_cache.py`, `services/access.py`, `services/database.py`, `web/app.js` —
  byte-identical базе. Endpoint'ов/флагов/DDL/миграций нет.
- Не менять `.env`, persisted settings, chat overrides, ключи, модели, промпты и флаги во время
  деплоя. Не выполнять reindex, массовый backfill, cache flush и live LLM-чат.
- Backup: pre-deploy backup существующим механизмом, deploy-пул `keep=2`; проверить свободное
  место до полной копии; rollback-копию не удалять до подтверждения деплоя.
- SSH/fail2ban: один короткий recon, liveness по HTTPS `/healthz`; без параллельных коннектов и
  повторных auth-попыток в цикле.

## 2. Production preflight — read-only (no secret values)

1. **Single-process preflight — §0 (обязательно первым).** При >1 процессе — stop/escalate.
2. Read-only проверка ACL (contract §5.5, как в 2.58.232):
   - ожидается **`bot_roles` 4** (`admin`, `local_admin`, `moderator`, `user`; `is_custom=false`),
     **`bot_admins` 3** (`admin` 1, `moderator` 2), **`chat_admins` 1**;
   - custom-ролей **0**; custom с `section.access`/wildcard **0**;
   - если появился **неожидаемый global admin/wildcard** (custom-роль с wildcard у не-владельца) —
     **не деплоить** до триажа: это активная аномалия ACL;
   - если появилась custom-роль с `section.access` у non-owner — S1 безопасен (снимает
     write-возможность), но актора/роль зафиксировать; read-GET после деплоя должен остаться 200;
   - печатать только количества/имена ролей/факт наличия; не выводить permissions-значения
     целиком, если они содержат чувствительные данные.
   - md5-якоря 2.58.232 для контроля дрейфа (не security-hash): `bot_roles`
     `5446e7d4e1b3dbbb2620b900e3bd976f`, `bot_admins` `894309cda0acae0c1b48b54769e164ab`,
     `chat_admins` `31d503dd97f6dff2649b6b18d25bd7c3`. Расхождение — записать, не «додумывать».
3. Identity/состояние до деплоя: HEAD `462568ed7`, version **2.58.232**, `user_version=48`,
   `schema_migrations` max/count 48, DDL 0; записать фактические значения.
4. Effective flags/settings: ACL-флагов нет (S1/S2 действуют безусловно); persisted settings/chat
   overrides не должны меняться этим релизом; зафиксировать effective значения и digests
   документов настроек/промптов **до** рестарта.
5. Диск: `python manage.py disk audit` (read-only); убедиться в достаточном свободном месте.
6. Deployment evidence должен использовать фактический authorized SHA. Content tip —
   `aada3af83`; если на хосте checkout docs-коммита выше него, manifest фиксирует этот HEAD,
   а product/test diff от `aada3af83` обязан быть пустым.

## 3. Deploy steps (только после отдельной deploy-авторизации)

1. Проверить свободное место и сохранить текущую rollback-копию.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (или checkout авторизованного release-коммита).
4. Проверить: `git status --porcelain --untracked-files=no` пуст; `APP_VERSION` = `2.58.233`;
   `git rev-parse HEAD` равен авторизованному release SHA; product diff от `aada3af83` пуст;
   schema/DDL не менялись (миграций нет).
5. Сделать pre-deploy backup существующим deploy-механизмом (keep rollback copy).
6. Записать манифест **до** рестарта: `python tools/release_manifest.py` (без `--dry-run`).
   Подтвердить `version=2.58.233`, `effect=deploy`, `dirty_tracked=false`,
   `previous_sha=462568ed7…` / `previous_version=2.58.232`, `deployed_sha` = фактический HEAD.
7. `sudo systemctl restart admin_bot`
8. Сразу выполнить §4 и §5. Не объявлять VERIFIED по одному runbook: записать deployed SHA,
   effective configuration и фактические наблюдения.

## 4. Postdeploy checks (read-only, если не указано иное)

| Проверка | Ожидание |
|---|---|
| Local HTTP (на хосте, мимо proxy) | `/healthz` → 200 |
| Public HTTP `https://<host>/healthz` | 200 (TLS/proxy тоже живы) |
| Version | `APP_VERSION` = `2.58.233` (runtime и manifest согласованы) |
| Checkout identity | `git rev-parse HEAD` **строково равен** manifest `deployed_sha` |
| Deployed identity | существующий identity probe → `code=verified_deployed`; иной код записать честно |
| Product diff | `git diff --name-only aada3af83..HEAD -- services web config tests tools` пуст (docs-коммиты могут отличаться) |
| Schema | `user_version=48`; `schema_migrations` max/count 48; новых миграций/DDL нет |
| Process | ровно один bot-процесс; `systemctl show -p NRestarts admin_bot` без новых автоматических рестартов после deploy-рестарта |
| Journal | `journalctl -u admin_bot --since <deploy time>` без новых fatal startup/migration/traceback; допустимы обычные info/warning |
| Settings/flags | effective values, persisted settings и chat overrides сохранены; новых флагов нет |
| Prompts/profiles (digests) | digests effective prompt/settings документов **до и после** совпадают |
| Served bytes | `web/index.html` (BOM/CRLF, admins-модалка `v-if="isGlobalAdmin"`), `web/app.js` не менялся; для отдаваемого HTML записать sha256 и подтвердить версию/отсутствие stale placeholder |
| ACL data digests | `bot_roles`/`bot_admins`/`chat_admins` — те же digest'ы; S1/S2 не пишут данные (единственная допустимая дельта — изменения владельца в окне деплоя, объяснить) |
| Auth | `POST /api/admins` без initData → **401** (live, сессия не нужна) |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); свободное место достаточно |
| Temp artifacts | на production не осталось probe DB, snapshot-копий, временных e2e-выгрузок или тестовых файлов (P0-PROD-DISK-01) |

## 5. ACL live check (bounded, read-only, без live-chat/LLM)

Цель — один ограниченный read-only проход по реальной странице админов, без записи,
без сообщений в чаты и без LLM-вызовов. Позитивный write **не выполнять**.

1. Открыть «Доступ → … → админы» (`#/access/admins`) при доступной реальной admin-сессии:
   - global admin: список, «Удалить», add-блок («Назначить») присутствуют; версия 2.58.233;
   - non-global актор (если доступна реальная сессия): список виден, «Удалить»/add отсутствуют,
     подпись «Только просмотр», h-scroll нет. **Если реальной non-global сессии нет — честно
     записать RFL** (не owner QA, не блокер; deterministic tests покрывают).
2. Read-only: `GET /api/roles`, `GET /api/admins`, `GET /api/roles/tree` при доступной сессии →
   200 (read остаётся под `section.access`); без initData те же/`POST` — 401.
3. Проверить, что мутации не вызываются: в сетевом логе нет POST/PUT/DELETE на
   `/api/admins`, `/api/admins/remove`, `/api/roles*` во время проверки. Любая запись — стоп-сигнал.
4. 403 на write-маршрутах от non-global — ожидаемое поведение S1; от global admin 403 — сигнал
   бага guard, зафиксировать. Наблюдение за ростом 403 — опционально, не обязательное evidence.
5. No-leak: значения/промпты/секреты в ответах ACL не появляются (регрессия C2 сохранена).
6. SCN-01 (live non-global TMA) остаётся **RFL**; отсутствие такого актора не является дефектом
   релиза. C3 (revisions/409, durable audit, chat-override DELETE, recheck, DDL 1) не входит.

## 6. Rollback

- Code rollback target: `462568ed7662cf5786a543bce8ecb6618e073c87` (2.58.232, schema 48, DDL 0).
- Миграций/DDL нет; данные, settings, chat overrides и ключи не менялись — data-action не нужен.
- После rollback: local/public health 200, `APP_VERSION=2.58.232`, identity = rollback SHA,
  schema 48/DDL 0, `NRestarts`, journal без fatal, settings/prompt digests не изменились,
  served bytes соответствуют rollback checkout; снова действует прежняя (уязвимая) ACL-граница —
  откат применять только при доказанной регрессии кандидата и затем перевыпустить исправление.
- Deploy backup и evidence не удалять до подтверждения rollback.

## 7. Stop conditions

Fatal startup/migration/traceback; identity mismatch; schema/DDL change; изменение
ключей/моделей/настроек/промптов; **более одного процесса `bot.py`**; неожиданный global/wildcard
ACL или запись в БД, которой не было в S1/S2; POST/PUT/DELETE из live-проверки; регрессия ранее
проверенного пути. При несоответствии deployed bytes — rollback и честная запись состояния.
