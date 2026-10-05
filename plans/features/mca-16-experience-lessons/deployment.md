# deployment.md - mca-16-experience-lessons (prod 2.58.59)

**Фича:** `mca-16-experience-lessons` (T-5014) - Risk R3 - **статус: VERIFIED**
**Выполнено:** 05.10.2026 (boot #1 05:51:17 UTC health 05:54:17; boot #2 05:55:30 UTC health 05:57:01) - шаг @DevOps T-5014 (reviewer **Approved** T-5013; binding: HEAD `92252d1` + WTH-манифест `plans/reports/mca16_wth_manifest_review.txt`, FILES=90, `MANIFEST_SHA256=59ad278b…`).

## 1. Preflight (binding)

- Рецепт манифеста воспроизведён (90 data lines; `sha256hex␣␣path`, sorted, LF + trailing LF): **sha256 = `59ad278b70c1f817395b212c7309c2711f74ca2c8631dde30835c41d8296f1fc` - MATCH**. Per-file 90/90 - все совпали с рабочим деревом.
- Review: verdict **Approved** (`plans/features/mca-16-experience-lessons/review.md`).
- Prod pre-state: HEAD `12a741a` (2.58.58), PID 3807957, active, NRestarts 0, `/healthz` 200 `2.58.58`; SQLite **v27** (`schema_migrations` 16, таблиц 104; `mca_experience*`/`mca_lessons*` - нет), 0 env-оверрайдов K1-K4.

## 2. Version bump CA-11 + коммиты (явные пути, не `git add -A`)

- **Bump 2.58.58→2.58.59**: `config/settings.py` `APP_VERSION` + `README.md` version-pin + **20 py release-pin файлов** (asserts `APP_VERSION ==`/`'APP_VERSION = "'`/regex-pin) + **4 JS-пин-файла** `round1025_hotfix{7,8,9,10}` regex `2.58.58→2.58.59` (wire «pins must be swept at T-5014») + F8 meta-pin `plans/docs/param-registry-round1025.meta.md`. References вида «parity 2.58.58» в docstring/комментариях не тронуты (исторический смысл).
- **feat: `f97e641`** - 90 файлов (+10940/−3681): манифест-runtime/tests/F8 (`services/mca_experience.py`, `mca_experience_jobs.py`, `database.py` v28, gates/settings/events/registry/retrieval/direct/status/memory_maintenance/param_catalog/web) + `tools/_mca16_reissue_f8.py` + 6 mca16-тестов + release-pin-sweep (20 py + 4 JS + meta). Исключения review-манифеста не стейджены.
- **docs: `6b3d421`** - 8 файлов: `plans/features/mca-16-experience-lessons/{spec.md, adr-1028-15-experience-lessons.md, threat-failure-analysis.md, tasks.md, requirements-map.md, evidence.md, review.md}` + `plans/reports/mca16_wth_manifest_review.txt`.
- **deploy-doc:** этот файл (после deploy).
- `git diff --cached --check`: только pre-existing CRLF-шум в ~30 тест-файлах (89 substantive lines - counters/pins; finding Reviewer, non-blocking → backlog).

## 3. Прод-миграция (mca-14, Δ DDL = v28)

- **Ручной pre-restart backup @DevOps ДО pull/рестарта:** `pre_migration_devops_20261005_054839.db` **1 384 734 720 B (1.38 GB)**, read-back sha256 OK (`9276d83bf3cfb601…`, source==copy).
- **Guard mca-14 при boot ДО применения (fail-closed):** `Oct 05 05:53:54 UTC services.memory_backup INFO: memory_backup: pre-migration copy created + read-back ok | target_version=27` → `/var/www/admin_bot/pre_migration_20261005_055136.db` **1 316 823 040 B (1.317 GB)** - якорь rollback.
- **Миграция v27→v28 применена:** journal `migration v28: mca_experience_episodes / mca_experience_feedback / mca_lessons / mca_lesson_applications` + `migration v28 applied | experience_bank`; `PRAGMA user_version` **28**; `schema_migrations` **17** с book-записью **`(28, experience_bank)` - ровно 1 раз**; таблиц **108** (104+4); **9 idx** (`idx_mca_experience_episodes_{chat_created,idem,scope_task}`, `idx_mca_experience_feedback_{chat_created,dedup}`, `idx_mca_lesson_applications_{dedup,lesson}`, `idx_mca_lessons_{status_scope,type_status}`).
- **Идемпотентность:** второй рестарт (05:55:30 UTC, PID 3835578) - **no-op**: `user_version 28`, sm 17, таблиц 108, book28=1 (0 новых миграционных строк в журнале), healthz 200 @2.58.59, NRestarts 0, ExecMainStatus 0.

## 4. Health / smoke / kill-switches

- `/healthz` **200 `{"status":"ok","version":"2.58.59"}`** (boot #1 try за ~3 мин: guard-копия 1.317 GB занимает время; boot #2 try 3); `/api/health` **200** (оба boot).
- `https://admin-bot.duckdns.org/web/` **200**, served `?v=2.58.59` **×12**, stale `v=2.58.58` = 0; `/web/app.js?v=2.58.59` **200**.
- `.env`/systemd: **0 env-оверрайдов на K1 `MCA_EXPERIENCE_LESSONS_ENABLED`/K2 `MCA_EXPERIENCE_FEEDBACK_ENABLED`/K3 `MCA_EXPERIENCE_REVIEW_ENABLED`/K4 `MCA_EXPERIENCE_CONTEXT_ENABLED`** → все **default ON**. Состояние counter/override/config DevOps не менял.

## 5. Данные / PG no-op

SQLite spot-checks (pre → post): `task_jobs` 645→646→647 (+1/+1 live-джобы), `mca_events` 10412→10415→10419 (boot/notable), `mca_bot_outputs` 76=76, `summary_runs` 13=13, `mca_random_state` 1=1, `mca_random_draws` 0=0; новые таблицы: `mca_experience_episodes`/`mca_experience_feedback`/`mca_lessons`/`mca_lesson_applications` - **0** (var/registry созданы при первом boot, не наполняются - ожидаемо). PG - **no-op** (`pg_db.py` DDL не тронут; SANCTIONS: v28 SQLite-only).

## 6. Focused-проверки (без полного suite)

| Проверка | Результат |
|---|---|
| Dev-venv (pre-commit): mca16 A–F | **91 passed** (10.73s) |
| Интеграционный slice: `pytest tests -k test_mca` (соседний пакет 36 файлов) | **1118 passed** (1117 @review + 1 тест с `mca` в имени вне пакета) |
| `gen_param_registry_round1025 --check` | **CHECK OK 504** (REGISTRY 504/GROUPS 108/_TAB_BY_GROUP 106/Settings 441/delta 93; R17-чисто) |
| JS: все `tests/js/*.js` | **59/59 OK** (после sweep 4 hotfix-пинов; `MCA16-EXP-OK`) |
| Prod-venv pre-restart: mca16 A–F + F8 | **91 passed** (47.22s) + `CHECK OK 504` |
| `--check` post-restart (×2) | **CHECK OK 504** |
| Catalog Δ | **+2/+1** (502→504, 107→108, `_TAB_BY_GROUP` 105→106; F8 re-issue подтверждён) |
| `ROUTES_SHA256_F11` | unchanged (routes.py не в diff) |

## 7. Журнал / R17

- **ERROR/CRITICAL/Traceback = 0** (обе проверки, оба boot).
- R17-скан журнала (`sk-`/`Bearer`/`-----BEGIN`/`AKIA`/`*api_key=`): **0 находок**.

## 8. Логины/механика

- Прод-VPS `racknerd-f4e3456` (`198.46.175.136`), каталог `/var/www/admin_bot`; systemd-юнит `admin_bot` (`Restart=always`), API на `127.0.0.1:8000`.
- Push origin/master `92252d1..6b3d421` (без force); ff `12a741a..6b3d421` (--ff-only), POST_DIRTY=13 (чужой WIP: workflow_state/arch-frames + debris - не тронут).

## 9. Rollback

- **Soft (первый выбор):** `.env += MCA_EXPERIENCE_LESSONS_ENABLED=false` (+ при необходимости K2/K3/K4=false) + рестарт → L-контур полностью инертен, **бит-в-бит 2.58.58**; v28-таблицы остаются пустыми и не читаются.
- **Cold:** `git revert` feat `f97e641` (либо checkout `12a741a` = 2.58.58). **v28 аддитивна/инертна** (v27 мультивалидна; restore не требуется); аварийный restore-якорь: `pre_migration_20261005_055136.db` (1.317 GB, root) - только R18 (руками владельца).
- Примечание: ручной devops-бэкап `pre_migration_devops_20261005_054839.db` может быть ротирован disk-retention mca-14 (известное поведение mca-10a I-1); фактический R18-якорь - guard-копия.

## 10. Findings-закрытия (review T-5013)

- **Release-pin sweep** (20 py + 4 JS + meta 2.58.58→2.58.59) - выполнен в этом окне; `git diff --cached --check` подтверждает, что только эти файлы содержат версию.
- **docstring mismatch `relevance_score` «≥4» vs код «≥5»** - non-blocking, уходит в backlog (не блокер деплоя).

## 11. Incidental findings (для Orchestrator)

- **[Info]** CRLF-шум в ~30 тест-файлах - pre-existing (зарегистрирован Reviewer) → backlog.
- **[Info]** `llm_usage_events` - PG-only (SQLite-гость не существует); первая попытка spot-check по `messages` - таблицы нет в SQLite (историческое имя иное) - не дефект.

## 12. Итоги @DevOps

T-5014 выполнен: prod **2.58.59 VERIFIED** (feat `f97e641` + docs `6b3d421` + deploy-doc этот файл), preflight manifest sha256 `59ad278b…` MATCH (per-file 90/90), Δ DDL v27→v28 идемпотентна с fail-closed backup-guard (1.317 GB read-back OK), Δ каталога += 2/+1 (F8 `--check` OK **504** дважды), K1–K4 ON / 0 env-overrides, health 200 ×2, `/api/health` 200, `/web/` 200 served `?v=2.58.59`, данные целы, PG no-op, 0 ERROR/CRITICAL/Traceback, **R17=0**. Следующий шаг: **live-приёмка T-5015 [PENDING OWNER]** (реальный чат: lessons/feedback/review/candidates-каналы) → затем reconcile T-5016. Deploy-машина подтверждает: **live T-5015 может идти**.
