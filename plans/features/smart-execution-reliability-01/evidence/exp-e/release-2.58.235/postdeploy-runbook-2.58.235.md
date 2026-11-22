# Postdeploy runbook — 2.58.235 (E-TRUNC / E-LAG)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (deploy не выполнялся).
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit
`admin_bot`. Артефакт **code-only**: DDL/schema нет, PG backup/DDL не нужны.

## 1. Preconditions

- Release branch `release/exp-e-trunc-lag-2.58.235`; content tip
  `b1036c53d26350c36b15e75d172f7008eb49a59f`, bump
  `f2c39e36921a0487c5e645f01184c60895bc68a6`; фактический deploy HEAD —
  tip ветки (docs/evidence выше bump; product bytes те же).
- Version **2.58.235**, base/rollback `56e2450d2` (2.58.234), schema SQLite
  **48**, PG DDL **0**, `APP_VERSION` меняется только в `config/settings.py`.
- Review `55aafa79f` **APPROVED_FOR_RELEASE_PREPARATION**; B01/N01/B02
  закрыты; RFL: production lag, модель на 8192, archive re-anchor.
- `.env`, persisted settings, chat overrides, gates, keys, prompts не
  менялись. Reindex/backfill/cache flush/LLM smoke не требуются.

## 2. Pre-deploy preflight (read-only)

1. **Single-process:** `systemctl show admin_bot -p MainPID -p NRestarts`
   и `pgrep -af bot.py`; ожидается **1** процесс `bot.py`, MainPID совпадает,
   `ExecStart` без `--workers`. Больше 1 — stop/escalate, не деплоить.
2. **ACL sanity (read-only):** существующие admin-API отвечают; есть хотя бы
   один effective global admin/wildcard; `bot_roles`/`bot_admins`/чатовые
   override читаются без 503. Код ACL в 2.58.235 не менялся; ожидаемые
   production-счётчики 2.58.234 сохраняются, lockout-переходов нет.
3. **Текущее состояние:** `git rev-parse HEAD` = `56e2450d2`,
   `APP_VERSION=2.58.234`, `PRAGMA user_version=48`,
   `schema_migrations` 48/48, journal без ERROR, `NRestarts=0`.
4. **Disk:** `python manage.py disk audit`; свободного места достаточно для
   SQLite backup; никакие старые backup/логи вручную не удалять.
5. **SQLite backup (существующий механизм):** pre-deploy backup через
   штатный backup API, `quick_check=ok`, `user_version=48`, rollback-копия
   сохраняется, deploy-пул `keep=2`. **PG backup/DDL не выполнять.**
6. Effective configuration: persisted/tenant/env overrides не сбрасывать;
   `memory.experience_*` hot-ключи остаются как есть (заводские значения
   2.58.235 применяются без миграции настроек).

## 3. Deploy

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot pull --ff-only` до authorized release SHA.
3. Проверить: `git status --porcelain --untracked-files=no` пуст;
   `git rev-parse HEAD` = authorized SHA; `APP_VERSION="2.58.235"`;
   `git diff --quiet 066909923 HEAD -- services/mca_experience_jobs.py
   tests/test_exp_e_trunc_lag_amendment.py` (product bytes равны
   reviewed candidate).
4. **Manifest по фактическому HEAD ДО restart:**
   `python tools/release_manifest.py` (без `--dry-run`).
   Ожидание: `version=2.58.235`, `effect=deploy`, `dirty_tracked=false`,
   `previous_sha=56e2450d2…`, `previous_version=2.58.234`.
5. `sudo systemctl restart admin_bot`.

## 4. Postdeploy verification

1. **Health/identity:** `/healthz`/`/api/status` → 200; version `2.58.235`;
   served bytes `/`/`web/app.js` отдаются без ошибок (200, ненулевой размер,
   ожидаемый hash/ETag).
2. **Service:** `systemctl show admin_bot -p NRestarts` = **0**;
   `systemctl is-active` = active; journal за окно деплоя без ERROR/
   traceback; startup single-process.
3. **Schema/DDL:** `PRAGMA user_version=48`; `schema_migrations` 48/48;
   DDL=0; новых таблиц/колонок/индексов нет.
4. **Experience job counters** (последний `task_jobs.kind='experience.review'`):
   - `semantic_batches_run > 0`;
   - `semantic_throughput_rows > 0`;
   - `semantic_fresh_lanes >= 1` (для отстающего чата `semantic_fresh`
     содержит boundary/cursor) либо чат уже догнан без fresh-полосы;
   - `semantic_truncated` не растёт штормом относительно
     `semantic_batches_run`; `semantic_llm_unavailable` не растёт;
   - курсор двигается только после валидного контента; при обрезке —
     durable `semantic_truncation`/`row_limit`, cursor стоит.
5. **Bounded live lag check (2–3 прохода, 15–30 мин):**
   фиксировать до/после каждого прохода: `semantic_lag.rows`,
   `pending_rows`, `lag_seconds`/oldest, main cursor, fresh cursor,
   `semantic_batches_run`, `semantic_throughput_rows`, `semantic_truncated`.
   Спад lag — evidence; отсутствие спада за 2–3 прохода — RFL/REVIEW, **не**
   VERIFIED. Не подменять lag нулём, не заявлять полный дренаж 2M за 5 дней
   без фактического замера.
6. **Disk hygiene:** `python manage.py disk audit`, затем
   `python manage.py disk cleanup --apply` (deploy-пул `keep=2`); удалить
   только собственные временные артефакты деплоя, не трогать пользовательские
   данные/чужие backup.

## 5. Rollback (code-only)

1. `git -C /var/www/admin_bot checkout 56e2450d2` (или fast-forward/revert
   release-коммитов), restart `admin_bot`.
2. Health/version 2.58.234, schema 48, DDL 0, `NRestarts=0`, journal clean.
3. Новый payload `semantic_fresh` старым кодом игнорируется: таблицы/DDL не
   менялись, исходные сообщения/история не удаляются. Возможен повторный
   проход строк свежей полосы основным курсором; `record_feedback`
   идемпотентен по `dedup_key`, дубли уроков не создаются.
4. PG backup/DDL и откат настроек/ключей/override не выполняются.

## 6. RFL

- Реальный спад lag/throughput и успешность модели на бюджете 8192/уменьшенных
  окнах проверяются только после деплоя (bounded 2–3 прохода).
- Archive re-anchor для чата без `archive_start` не выполнялся; fresh-полоса
  сохраняет старый хвост и честный lag.
