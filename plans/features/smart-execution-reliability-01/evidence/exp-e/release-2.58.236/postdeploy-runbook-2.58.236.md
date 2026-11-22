# Postdeploy runbook — 2.58.236 (B03 heartbeat/counters)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (deploy не выполнялся).
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit
`admin_bot`. Артефакт **code-only**: DDL/schema нет, PG backup/DDL не нужны.

## 1. Preconditions

- Release branch `release/exp-e-trunc-lag-2.58.236`; content tip
  `145f9a67a`, bump `ab66b66e7`; фактический deploy HEAD — tip ветки
  (docs/evidence выше bump; product bytes те же, version 2.58.236).
- Base/primary rollback `f4ad6902f` (2.58.235); catastrophic fallback
  `56e2450d2` (2.58.234). Schema SQLite **48**, PG DDL **0**.
- Review `e91c9ccfc` **APPROVED_FOR_RELEASE_PREPARATION**; B03 закрыт;
  N01 (`_fence=0` heartbeat) — nonblocking backlog; exact `worker_lost`
  trigger — RFL.
- `.env`, persisted settings, chat overrides, gates, keys, prompts не
  менялись. Reindex/backfill/cache flush/LLM smoke не требуются.

## 2. Pre-deploy preflight (read-only)

1. **Single-process:** `systemctl show admin_bot -p MainPID -p NRestarts` и
   `pgrep -af bot.py`; ожидается 1 процесс, MainPID совпадает, без
   `--workers`. Больше 1 — stop/escalate, не деплоить.
2. **ACL sanity (read-only):** admin-API отвечают; есть effective global
   admin/wildcard; `bot_roles`/`bot_admins`/чатовые override читаются без
   503. Код ACL в 2.58.236 не менялся.
3. **Текущее состояние:** `git rev-parse HEAD` = `f4ad6902f`,
   `APP_VERSION=2.58.235`; journal без ERROR; `NRestarts=0`;
   последний `experience.review` не в `running`/`queued` застрявшем
   состоянии (иначе дождаться/эскалировать).
4. **Disk:** `python manage.py disk audit`; места достаточно для SQLite
   backup; вручную ничего не удалять.
5. **SQLite backup (существующий механизм):** predeploy backup через
   backup API, `quick_check=ok`, `user_version=48`; rollback-копия
   сохраняется; deploy-пул `keep=2`. **PG backup/DDL не выполнять.**
6. Effective configuration `memory.experience_*` не сбрасывать; заводские
   значения 2.58.236 применяются без миграции настроек.

## 3. Deploy

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot pull --ff-only` до authorized release SHA.
3. Проверить: `git status --porcelain --untracked-files=no` пуст;
   `git rev-parse HEAD` = authorized SHA; `APP_VERSION="2.58.236"`;
   `git diff --quiet 66ed5cd28 HEAD -- services/mca_experience_jobs.py
   tests/test_exp_e_trunc_lag_amendment.py
   tests/test_sxr_i2_fresh_stream_drain.py`.
4. **Manifest по фактическому HEAD ДО restart:**
   `python tools/release_manifest.py` (без `--dry-run`).
   Ожидание: `version=2.58.236`, `effect=deploy`, `dirty_tracked=false`,
   `previous_sha=f4ad6902f…`, `previous_version=2.58.235`.
5. `sudo systemctl restart admin_bot`.

## 4. Postdeploy verification

1. **Health/identity:** `/healthz`/`/api/status` → 200; version `2.58.236`;
   served bytes `/`/`web/app.js` 200, ненулевой размер, ожидаемый hash/ETag.
2. **Service:** `systemctl is-active` active; `NRestarts=0`; journal за окно
   деплоя без ERROR/traceback; startup single-process.
3. **Schema/DDL:** `PRAGMA user_version=48`; `schema_migrations` 48/48;
   DDL=0; новых таблиц/колонок/индексов нет.
4. **Experience counters — completed pass:** последний
   `task_jobs.kind='experience.review'` содержит непустые `counters`:
   `semantic_batches_run>0`, `semantic_throughput_rows>0`,
   `semantic_fresh_lanes>=1` (для отстающего чата) либо чат догнан,
   `semantic_truncated` не штормит, `semantic_llm_unavailable` не растёт;
   cursor двигается только после валидного контента.
5. **Counters persist on failed/worker_lost:** при любом terminal
   `failed`/`worker_lost` payload обязан содержать durable
   `counters.semantic_*` и `semantic_truncation`/`semantic_retry` при
   обрезке — **`COUNTERS={}` недопустим**. Если снова пусто — это
   отдельный инцидент (B03 не сработал), не «нет данных».
6. **Heartbeat/fencing:** в running-job `heartbeat_at` обновляется чаще
   lease (не gap == duration); при takeover/fenced job останавливается без
   записи cursor/finish. `N01` (`_fence=0` первый takeover) — известный
   nonblocking backlog, не выдавать за исправленный.
7. **Bounded live lag check (2–3 прохода, 15–30 мин):** до/после каждого
   прохода фиксировать `semantic_lag.rows`, `pending_rows`, `lag_seconds`,
   main/fresh cursor, `semantic_batches_run`, `semantic_throughput_rows`,
   `semantic_truncated`, `semantic_retry`. Спад lag — evidence; отсутствие
   спада за 2–3 прохода — RFL/REVIEW, **не VERIFIED**. Не подменять lag
   нулём и не заявлять полный дренаж 2M за 5 дней без замера.
8. **Disk hygiene:** `python manage.py disk audit`, затем
   `python manage.py disk cleanup --apply` (deploy-пул `keep=2`); удалять
   только собственные временные артефакты, не чужие backup/данные.

## 5. Rollback (code-only)

1. Primary: `git checkout f4ad6902f` (2.58.235), restart `admin_bot`;
   health/version 2.58.235, schema 48, DDL 0, `NRestarts=0`, journal clean.
2. Catastrophic fallback `56e2450d2` (2.58.234) — только по отдельному
   решению; ручной DDL не выполняется.
3. Новые payload-ключи/counters старым кодом игнорируются; история и
   сообщения не удаляются; `record_feedback` идемпотентен. Настройки/ключи/
   override не откатываются; PG backup/DDL не нужны.

## 6. Backlog / RFL

- **EXP-E-B03-N01** (nonblocking): heartbeat для `_fence=0` безусловный,
  первый takeover не детектится; store-гард защищает terminal write,
  payload может быть перезаписан идемпотентно. Отдельный backlog, не
  блокирует 2.58.236.
- **RFL:** точный триггер `worker_lost` 2.58.235 не воспроизведён; B03
  закрывает heartbeat/counters/bounded retry, но registry/watchdog-потерю
  нужно подтверждать post-deploy.
- Production lag/model 8192 — только после деплоя bounded 2–3 проходами.
- Archive re-anchor не выполнялся.
