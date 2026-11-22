# Postdeploy runbook — 2.58.237 (M5A semantic stage)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (deploy не выполнялся).
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit
`admin_bot`. Артефакт **code-only**: DDL/schema нет, PG backup/DDL не нужны.

## 1. Preconditions

- Release branch `release/mod-acl-m5a-2.58.237`; content tip `2c39abed2`,
  bump `c7db72be0`; фактический deploy HEAD — tip ветки (docs/evidence выше
  bump; product bytes те же, version 2.58.237).
- Base/rollback `e0cc93246` (2.58.236); schema SQLite **48**, PG DDL **0**.
- Review `8238a33eb` APPROVED; 11 VERIFIED / 3 REVIEW / `MAC-M5-01`
  PENDING (M5B/M5C). 3 REVIEW не выдаются за VERIFIED.
- `.env`, persisted settings, chat overrides, gates, keys, prompts не
  менялись. Reindex/backfill/cache flush/LLM smoke не требуются.

## 2. Pre-deploy preflight (read-only)

1. **Single-process:** `systemctl show admin_bot -p MainPID -p NRestarts` и
   `pgrep -af bot.py`; ожидается 1 процесс, MainPID совпадает, без
   `--workers`. Больше 1 — stop/escalate, не деплоить.
2. **ACL sanity (read-only):** admin-API отвечают; есть effective global
   admin/wildcard; `bot_roles`/`bot_admins`/чатовые override читаются без
   503. Код ACL в 2.58.237 не менялся; **positive ACL writes не выполнять**.
3. **Текущее состояние:** `git rev-parse HEAD` = `e0cc93246`,
   `APP_VERSION=2.58.236`; journal без ERROR; `NRestarts=0`; последний
   `experience.review` не застрял в `running`/`queued`.
4. **Disk:** `python manage.py disk audit`; места достаточно для SQLite
   backup; вручную ничего не удалять.
5. **SQLite backup (существующий механизм):** predeploy backup через
   backup API, `quick_check=ok`, `user_version=48`; rollback-копия
   сохраняется; deploy-пул `keep=2`. **PG backup/DDL не выполнять.**
6. Effective configuration `memory.experience_*` не сбрасывать.

## 3. Deploy

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot pull --ff-only` до authorized release SHA.
3. Проверить: `git status --porcelain --untracked-files=no` пуст;
   `git rev-parse HEAD` = authorized SHA; `APP_VERSION="2.58.237"`;
   `git diff --quiet d1315bf86 HEAD -- services/mca_experience_jobs.py
   tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py`.
4. **Manifest по фактическому HEAD ДО restart:**
   `python tools/release_manifest.py` (без `--dry-run`).
   Ожидание: `version=2.58.237`, `effect=deploy`, `dirty_tracked=false`,
   `previous_sha=e0cc93246…`, `previous_version=2.58.236`.
5. `sudo systemctl restart admin_bot`.

## 4. Postdeploy verification

1. **Health/identity:** `/healthz`/`/api/status` → 200; version `2.58.237`;
   served bytes `/`/`web/app.js` 200, ненулевой размер, ожидаемый hash/ETag.
2. **Service:** active; `NRestarts=0`; journal за окно деплоя без ERROR/
   traceback; startup single-process.
3. **Schema/DDL:** `PRAGMA user_version=48`; `schema_migrations` 48/48;
   DDL=0; новых таблиц/колонок/индексов нет.
4. **Semantic stage status (M5A):** последний `experience.review` payload
   содержит `semantic_stage_status` (`completed/partial/unavailable`),
   `semantic_partial` и `semantic_partial_reasons`; то же видно в
   `semantic_progress.stage_status/partial/partial_reasons`.
   - `completed` — только статус выполненного job, **не** «полное обучение»;
   - `unavailable/partial` при `llm_unavailable`/parse/write/read/budget/
     deferred/truncated; cursor при `llm_unavailable` не двигается;
   - `partial` не выдавать за полный успех, `completed` не выдавать за
     полное обучение.
5. **Counters:** durable `semantic_batches_run`, `semantic_throughput_rows`,
   `semantic_selected`, `semantic_truncated`, `semantic_llm_unavailable`
   присутствуют и после failed/worker_lost (`COUNTERS={}` недопустим).
6. **ACL:** только read-only проверки; positive ACL writes не выполнять.
7. **Bounded live check (2–3 прохода, 15–30 мин):** фиксировать
   `semantic_stage_status`, reasons, lag/pending, cursor/fresh cursor,
   throughput; спад lag — evidence, отсутствие за 2–3 прохода — RFL, не
   VERIFIED. Не подменять lag нулём и не заявлять полный дренаж 2M.
8. **Disk hygiene:** `python manage.py disk audit`, затем
   `python manage.py disk cleanup --apply` (keep=2); удалять только свои
   временные артефакты.

## 5. Rollback (code-only)

1. `git checkout e0cc93246` (2.58.236), restart `admin_bot`; health/version
   2.58.236, schema 48, DDL 0, `NRestarts=0`, journal clean.
2. Новые payload-поля `semantic_stage_status/partial/partial_reasons`
   старым кодом игнорируются; cursor/retry/truncation state и история
   сохраняются; `record_feedback` идемпотентен.
3. Настройки/ключи/override не откатываются; PG backup/DDL не нужны;
   ручной DDL не выполняется.

## 6. Status / RFL

- `MAC-M5-01` PENDING: требует M5B (`MAC-EXP-08`) и M5C/native question.
- 3 REVIEW-строки M5A не VERIFIED; их не объявлять закрытыми.
- RFL: production-lag/model 8192, точный `worker_lost` trigger, archive
  re-anchor.
