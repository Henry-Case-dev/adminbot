# Postdeploy runbook — 2.58.238 (M5A 3 REVIEW + M5B)

Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** (deploy не выполнялся).
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit
`admin_bot`. Деплой **code-only**: DDL/schema нет, PG backup/DDL не нужны.

## 1. Preconditions

- Release branch `release/mod-acl-m5a3-m5b-2.58.238`; content tip
  `f5567fccd4d7ebd95438a3f33754ce234929fb9e`; bump/manifest HEAD
  `7a36f4fc847f4f51246457c02300d047acd565d6`. Деплоить точный bump-SHA
  (product bytes идентичны tip; docs/evidence-коммит product-neutral).
- Base/rollback: `f4040266013bb19374c24c39ed001ba1ccb815f4` (2.58.237).
- Schema: SQLite **48**, PG DDL **0**.
- Review: M5A `86dc3f32e` APPROVED, 3 REVIEW → VERIFIED; M5B
  `e13249472` APPROVED, `MAC-EXP-08` REVIEW/RFL, `MAC-M5-01` PENDING.
- `.env`, persisted settings, chat overrides, gates, keys, prompts не
  менять. Reindex/backfill/cache flush/LLM smoke не запускать.

## 2. Pre-deploy preflight (read-only)

1. **Single-process:** `systemctl show admin_bot -p MainPID -p NRestarts`
   и `pgrep -af bot.py`; ожидается 1 процесс, MainPID существует, без
   `--workers`. Больше 1 — stop/escalate, не деплоить.
2. **ACL sanity (read-only):** admin-API отвечает; есть effective global
   admin/wildcard; `bot_roles`/`bot_admins`/чатовые overrides читаются без
   503. Код ACL не менялся; **positive ACL writes не выполнять**.
3. **Текущее состояние:** `git rev-parse HEAD` = `f40402660`,
   `APP_VERSION=2.58.237`; journal без ERROR; `NRestarts=0`; задача
   `experience.review` не в `running`/`queued`.
4. **Disk:** `python manage.py disk audit`; свободного места достаточно
   для SQLite backup; журнал/ошибки не игнорировать.
5. **SQLite backup (обязательно):** predeploy backup через backup API,
   `quick_check=ok`, `user_version=48`; rollback-копию сохранить;
   deploy-пул `keep=2`. **PG backup/DDL не выполнять.**
6. Effective configuration `memory.experience_*` прочитать; значения не
   переписывать.

## 3. Deploy

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout --detach 7a36f4fc8` (или
   `pull --ff-only` до авторизованного bump-SHA; tip содержит только
   docs/evidence и product bytes не меняет).
3. Проверить: `git status --porcelain --untracked-files=no` пуст;
   `git rev-parse HEAD` = `7a36f4fc8`; `APP_VERSION="2.58.238"`;
   `git diff --quiet 697a28f9e HEAD -- services/mca_experience_jobs.py
   tests/test_mod_acl_ux_m5b_shared_review.py`;
   `git diff --quiet 0907dbae6 HEAD -- services/experience_diagnostics.py
   tests/test_mod_acl_ux01_exp_fix_semantic_checkpoint.py`.
4. **Manifest до restart:** `python tools/release_manifest.py` (без
   `--dry-run`). Ожидается `version=2.58.238`, `effect=deploy`,
   `dirty_tracked=false`, `previous_sha=f40402660…`,
   `previous_version=2.58.237`.
5. `sudo systemctl restart admin_bot`.

## 4. Postdeploy verification

1. **Health/identity:** `/healthz`/`/api/status` 200; version `2.58.238`;
   served bytes `/`/`web/app.js` 200, размеры не нулевые, hash/ETag
   свежие.
2. **Service:** active; `NRestarts=0`; journal после старта без
   ERROR/traceback; startup single-process.
3. **Schema/DDL:** `PRAGMA user_version=48`; `schema_migrations` 48/48;
   DDL=0; таблицы/индексы не менялись.
4. **M5A semantic stage (read-only):** в payload `experience.review` и
   `semantic_progress` проверить `semantic_stage_status`
   (`completed/partial/unavailable`), `semantic_partial`,
   `semantic_partial_reasons`:
   - `completed` — job завершил обучение, **не** доказательство полного
     обучения;
   - `unavailable/partial` — причины `llm_unavailable`/parse/write/read/
     budget/deferred/truncated; cursor не двигается при `llm_unavailable`;
   - `partial` не выдавать за успех, `completed` не выдавать за полный
     успех.
5. **M5B per-chat shared review (read-only):** задача
   `experience.review` тикает; в payload/counters и
   `mca_experience_feedback`/`mca_lessons` проверить группировку по
   `chat_id`; для чата с явным OFF не должно появляться новых
   feedback/candidate/active lessons. Stored overrides не переписывать.
   Пара GLOBAL OFF + CHAT ON / GLOBAL ON + CHAT OFF остаётся **RFL**:
   отдельная контролируемая live-проверка, не часть деплоя; positive ACL
   writes не выполнять.
6. **Counters:** durable `semantic_batches_run`,
   `semantic_throughput_rows`, `semantic_selected`, `semantic_truncated`,
   `semantic_llm_unavailable` консистентны; terminal failed/worker_lost
   не оставляет `COUNTERS={}`.
7. **Bounded live check (2–3 цикла, 15–30 мин):** записать
   `semantic_stage_status`, reasons, lag/pending, cursor/fresh cursor,
   throughput; bounded lag — evidence, длительное наблюдение — RFL, не
   VERIFIED. При lag > 2M и отсутствии bounded catch-up — остановить
   проверку и вернуть на исправление.
8. **Disk hygiene:** `python manage.py disk audit`; затем
   `python manage.py disk cleanup --apply` (deploy keep=2); удалить только
   свои временные файлы.

## 5. Rollback (code-only)

1. `git checkout f40402660` (2.58.237), restart `admin_bot`;
   health/version 2.58.237, schema 48, DDL 0, `NRestarts=0`, journal clean.
2. Payload-поля `semantic_stage_status/partial/partial_reasons` старым
   кодом не читаются; cursor/retry/truncation state не удалять.
3. Настройки/overrides/gates не переписывать; PG backup/DDL не нужны;
   данные M5A/M5B аддитивны и сохраняются.

## 6. Status / RFL

- M5A: 3 REVIEW-строки VERIFIED по review `86dc3f32e`; остальные строки
  M5A не понижены.
- M5B: `MAC-EXP-08` REVIEW/RFL (live preprod не выполнялся);
  `MAC-M5-01` PENDING (M5C/native question).
- M5C/M6 не начаты; эпик M5 не DONE.
