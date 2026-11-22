# Deploy runbook — 2.58.232 (MOD-ACL-UX-01 M4C C2: read-only «Проверить доступ»)

Status: **REVIEW / READY_FOR_DEPLOY_PREPARATION — deploy only by separate authorization**.
В этой сборке не было деплоя, SSH, production DB, LLM-чата, изменения ключей/моделей/настроек,
миграций или DDL. Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit
`admin_bot`. Старый VPS `198.46.175.136` декомиссован и не является rollback-целью.

## 1. Preconditions

- Release branch `release/mod-acl-m4c2-2.58.232`.
- Content tip (product/test bytes) `0fcba327fab8111c666501ff75d00f4c3dcefae0`: 5 cherry-picked
  C2 commits (`8e50b0fa3` C2a, `bc742adc0` C2b, `ba8b93121` evidence, `ece63acac` R1 blockers,
  `e20f58204` c4 coverage/scope) + стандартный bump 2.58.231 → 2.58.232.
  Version **2.58.232**, schema **48**, DDL **0**.
- Reviewed candidate: `e20f58204a9ebc377a4c061c475f4edb61777f19` (base `d86bf66d4`).
  Review: `plans/features/mod-acl-ux-01/evidence/m4c/c2/review-r1.md` @ master `a4d3ce033`
  (blob sha256 `7c2f51f0…6ac8b7`), addendum_c4 **APPROVED_FOR_RELEASE_PREPARATION**.
  Contract: `plans/features/mod-acl-ux-01/evidence/m4c/c2-contract-2026-11-22.md`
  (sha256 `0b9fdcef…8533cf`). Не деплоить неотревьюенные ретраи или байты без C2.
- Rollback/base: `7a4d5724da04fd34821584717d63657f6fc53a50` (2.58.231, schema 48, DDL 0).
- Product scope: `services/access.py`, `services/access_errors.py`, `services/access_preview.py`,
  `services/roles.py`, `services/chat_params.py`, `web/api/access.py`, `web/app.js`,
  `web/index.html`, `web/static/app.css`, C2 tests/tools/evidence и version wave.
  `web/api/routes.py`, `web/api/deps.py`, `services/permissions.py`, `services/pg_db.py`,
  `services/param_catalog.py`, `services/config_cache.py`, `services/database.py`, `migrations`
  не изменены.
- Не менять `.env`, persisted settings, chat overrides, ключи, модели, промпты и флаги во время
  деплоя. Не выполнять reindex, массовый backfill, cache flush и live LLM-чат.
- Backup: pre-deploy backup существующим механизмом, deploy-пул `keep=2`; проверить свободное
  место до полной копии; rollback-копию не удалять до подтверждения деплоя.
- SSH/fail2ban: один короткий recon, liveness по HTTPS `/healthz`; без параллельных коннектов и
  повторных auth-попыток в цикле.

## 2. Production preflight — read-only (no secret values)

1. Read-only проверка `bot_roles`/`bot_admins` (contract §6.4, как в C1):
   - ожидается **4 built-in роли**, **3 назначения**, **0 custom-ролей с `section.access`**;
   - если появляется **custom-роль с `section.access`** — это S1-hardening сигнал: остановиться
     до деплоя и сообщить, не «исправлять» данные и не расширять C2. C2 показывает такие роли
     как `mixed` и не является S1-фиксом.
   - печатать только количества/имена ролей/факт наличия; не выводить permissions-значения
     целиком, если они содержат чувствительные данные.
2. Identity/состояние до деплоя: HEAD `7a4d5724d`, version **2.58.231**, `user_version=48`,
   `schema_migrations` max/count 48, DDL 0; записать фактические значения.
3. Effective flags/settings: ACL-флаги и persisted settings/chat overrides не должны меняться
   этим релизом; зафиксировать effective значения и digests документов настроек/промптов
   **до** рестарта (C2 не меняет prompt/настройки).
4. Диск: `python manage.py disk audit` (read-only); убедиться в достаточном свободном месте.
5. Deployment evidence должен использовать фактический authorized SHA. Content tip —
   `0fcba327f`; если на хосте checkout docs-коммита выше него, manifest фиксирует этот HEAD,
   а product/test diff от `0fcba327f` обязан быть пустым.

## 3. Deploy steps (только после отдельной deploy-авторизации)

1. Проверить свободное место и сохранить текущую rollback-копию.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (или checkout авторизованного release-коммита).
4. Проверить: `git status --porcelain --untracked-files=no` пуст; `APP_VERSION` = `2.58.232`;
   `git rev-parse HEAD` равен авторизованному release SHA; product/test diff от `0fcba327f`
   пуст; schema/DDL не менялись (миграций нет).
5. Сделать pre-deploy backup существующим deploy-механизмом (keep rollback copy).
6. Записать манифест **до** рестарта: `python tools/release_manifest.py` (без `--dry-run`).
   Подтвердить `version=2.58.232`, `effect=deploy`, `dirty_tracked=false`,
   `previous_sha=7a4d5724d…` / `previous_version=2.58.231`, `deployed_sha` = фактический HEAD
   хоста.
7. `sudo systemctl restart admin_bot`
8. Сразу выполнить §4 и §5. Не объявлять VERIFIED по одному runbook: записать deployed SHA,
   effective configuration и фактические наблюдения.

## 4. Postdeploy checks (read-only, если не указано иное)

| Проверка | Ожидание |
|---|---|
| Local HTTP (на хосте, мимо proxy) | `/healthz` → 200 |
| Public HTTP `https://<host>/healthz` | 200 (TLS/proxy тоже живы) |
| Version | `APP_VERSION` = `2.58.232` (runtime и manifest согласованы) |
| Checkout identity | `git rev-parse HEAD` **строково равен** manifest `deployed_sha` |
| Deployed identity | существующий identity probe → `code=verified_deployed`; иной код записать честно, не выдавать за успех |
| Product diff | `git diff --name-only 0fcba327f..HEAD -- services web config tests tools` пуст (docs-коммиты могут отличаться) |
| Schema | `user_version=48`; `schema_migrations` max/count 48; новых миграций/DDL нет |
| Process | ровно один bot-процесс; `systemctl show -p NRestarts admin_bot` без новых автоматических рестартов после deploy-рестарта |
| Journal | `journalctl -u admin_bot --since <deploy time>` без новых fatal startup/migration/traceback; допустимы обычные info/warning |
| Settings/flags | effective values, persisted settings и chat overrides сохранены; новых флагов нет |
| Prompts/profiles (digests) | digests effective prompt/settings документов **до и после** совпадают; C2 не меняет промпты |
| Served bytes | `web/app.js` и `web/static/app.css` по cache-busted URL (`?v=2.58.232`) побайтово совпадают с checkout (sha256); для отдаваемого `index.html` записать sha256 и фактическую трансформацию, подтвердить версию/отсутствие stale placeholder |
| C2 GET mounted | без initData `GET /api/access/effective`, `/api/access/chats/{id}/param_permissions`, `/api/access/chats/{id}/admins` → 401 (не 404/405) |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); свободное место достаточно |
| Temp artifacts | на production не осталось probe DB, snapshot-копий, временных e2e-выгрузок или тестовых файлов (P0-PROD-DISK-01) |

## 5. C2 read-only live check (bounded, без live-chat/LLM)

Цель — один ограниченный read-only проход по реальной странице ролей/гейтов, без записи,
без сообщений в чаты и без LLM-вызовов.

1. Открыть «Доступ → Роли» и «Фактические гейты» (TMA, существующая сессия; non-global TMA —
   если доступна, иначе честно записать SCN-01 RFL, не назначать owner QA).
2. Проверить: preview «Проверить доступ» присутствует **только** внутри «Фактических гейтов»;
   на desktop форма в две колонки, на mobile — стек; тач-цели ≥44; h-scroll 0.
3. Read-only прогоны preview для доступных акторов:
   - admin + `section.access` → `allowed` (роль + ceiling);
   - moderator + `section.limits` → coverage-слой (`allowed/denied` по фактическим deps), без
     выдуманного endpoint-guard;
   - chat scope: moderator param view `allowed` + перекрытия, edit `denied`; DM — только владелец;
   - `section.*` в chat/DM (кроме `chat_lore`) → `not_applicable` (scope_capability), а не
     ложный allow/deny;
   - local_admin edit param → `allowed`; user/custom — по фактическим слоям (custom
     `section.access` может быть `mixed` — это ожидаемо, S1 остаётся C3);
   - смена actor/scope/resource очищает старый результат (in-flight generation guard);
     роль без назначений — `no-actor` только после успешной загрузки `/api/admins`.
4. Ошибки: 401/403/404/422/503 отображаются разными карточками; 503 — «временно недоступно»,
   не «запрещено»; 403 — «нет доступа», не пустой экран.
5. No-leak: в ответе/на экране нет values, prompt-текстов, секретов, `last4`; hidden-ключи
   отклоняются; `author_recorded:false` показывается как «автор не записан (audit — C3)».
6. Read-only proof: preview не делает POST/PUT/DELETE; 9 write-декораторов `access_router`
   остаются 9; DDL 0. Любая запись/изменение настроек — стоп-сигнал, не «проверка».
7. SCN-01 (live non-global TMA) остаётся **RFL**; отсутствие такого актора/сессии не является
   дефектом релиза и не блокирует остальные проверки. C3 (S8-523/S8-505: recheck/save,
   durable audit/who changed, revisions/409) в этот релиз не входит.

## 6. Rollback

- Code rollback target: `7a4d5724da04fd34821584717d63657f6fc53a50` (2.58.231, schema 48, DDL 0).
- Миграций/DDL нет; данные, settings, chat overrides и ключи не менялись — data-action не нужен.
- C2 preview read-only, поэтому после rollback не требуется чистить созданные им записи;
  удалить только временные артефакты текущей проверки.
- После rollback: local/public health 200, `APP_VERSION=2.58.231`, identity = rollback SHA,
  schema 48/DDL 0, `NRestarts`, journal без fatal, settings/prompt digests не изменились,
  served bytes снова соответствуют rollback checkout. Deploy backup и evidence не удалять до
  подтверждения rollback.

## 7. Stop conditions

Fatal startup/migration/traceback; identity mismatch; schema/DDL change; изменение
ключей/моделей/настроек/промптов; POST/PUT/DELETE из preview; неожиданный массовый трафик;
любая запись в БД, которой не было в C2; регрессия ранее проверенного пути. При несоответствии
deployed bytes — rollback и честная запись фактического состояния.
