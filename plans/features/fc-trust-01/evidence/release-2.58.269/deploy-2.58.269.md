# Release 2.58.269 — deploy evidence (FC-TRUST-01 S6 U1, схема v49 ⇒ v50)

Deploy 2026-11-28T04:07:43Z → restart 04:07:44Z; миграция завершена 04:15:14Z
(backup-guard 445 s на 7.0 GB БД). Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 1 recon + 5 сессий (deploy и проверки),
строго одиночные key-auth подключения, без параллельных сессий и фоновых процессов.

## Authorisation and composition

- Reviewed candidate `fa3cb0391f53728d1b64961b34d49cf8eee9174e` (branch
  `feat/fct-s6-u1-run-link-2026-11-28`, tip `589269b04`); review
  `.../fct-s6-u1-2026-11-28/review-r1/review-r1.md` sha256 `e48b2abd…` —
  **APPROVED_FOR_RELEASE_PREPARATION** (B-1/B-2 BACKLOG_ONLY, миграция признана аддитивной
  и обратимой).
- Assembly `assembly.md` — branch `release/2.58.269` от `e46aa0696`, продукт `f4ca6dc8d`
  (байт-в-байт 7 файлов `fa3cb0391`), bump `07c345e88` (29/34), evidence `6d97c02d8`;
  push в `origin/release/2.58.269` (`git ls-remote` = `6d97c02d8…`).
- Base (deployed): `e46aa0696` = 2.58.268, `user_version=49`.

## Identity

| Field | Value |
|---|---|
| pre-deploy HEAD | `e46aa0696…` (2.58.268, detached; «Previous HEAD position was e46aa0696») |
| deployed_sha (actual HEAD) | `6d97c02d8a4830c5824cc9c39db311373f953b6d` |
| post-checkout dirty (tracked) | 0 |
| manifest | `effect=deploy`, `previous_sha=e46aa0696…`, `previous_version=2.58.268`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-28T04:07:43.509788Z` |

Продуктовые блобы на проде (`git hash-object`), совпадают с кандидатом:

```
526377c8f78db4bc8524ac4f4594d36a9a96719c  services/database.py
c617cff8257090e4fa9807cb12236d93173fa902  services/temporal_factcheck.py
7fbf0eaa67be6477c7a9d108644c8c017c5ade08  services/factcheck_orchestrator.py
7590f714fc035572a85872cd4ab99e817e189d52  services/factcheck_service.py
89677641866451f8d940aa15136ab65c1296e77b  handlers/factcheck.py
1b5c061112dafd39bc021b0b84e2c42525e997bb  tests/test_fc_trust_s6_run_link.py
64bb06c05fc7067b2630951c2b407d5455e631fb  services/factcheck_prompts.py   (= база, канон)
```

Владелец изменённых файлов выровнен под сервис (`adminbot:adminbot`, 644),
`unreadable=0`, `IMPORT_OK 2.58.269`.

## Version — три источника

`config/settings.py` `APP_VERSION = "2.58.269"`; локальный `http://127.0.0.1:8000/healthz`
→ `{"status":"ok","version":"2.58.269"}`; публичный `https://admin-bot.duckdns.org/healthz`
→ то же.

## Unit

`active/running`, MainPID 1223380, **NRestarts=0**, ExecMainStart `2026-11-28 04:07:44 UTC`,
`procs=1`; ExecStart `venv/bin/python bot.py`.

## Миграция схемы (штатный старт сервиса, не вручную)

| Метрика | До | После |
|---|---|---|
| `user_version` | 49 | **50** |
| `mca_factcheck_runs` строк | 57 | **57** |
| `mca_factcheck_evidence` строк | 435 | **435** |
| `schema_migrations` | max 49 | **+ (50, 'factcheck_run_link_v50')** |

- Новые колонки существуют и nullable: `mca_factcheck_runs.correlation_id` (`notnull=0`,
  все 57 старых строк NULL), `mca_factcheck_evidence.evidence_id/opened/strength`.
- Индекс `idx_mca_factcheck_runs_correlation` создан; старые индексы
  `idx_mca_factcheck_runs_chat_time/_scope_time/_evidence_run` на месте.
- `quick_check=ok`, `integrity_check=ok` (после миграции, фаза B).
- Журнал: `migrations: start | current user_version=49 | pending=[50]` →
  `backup-guard: done in 445.2s` → 4×`migration v50: … added` →
  `migration v50 applied in 0.0s | factcheck_run_link_v50` →
  `migrations: complete | user_version=50 | total 445.3s`. Ошибок `no such column`/
  `sqlite3`/`database is locked` — 0.
- Backup-guard отработал штатно: `VACUUM INTO` + read-back, ротация keep=1 вытеснила
  `pre_migration_20261127_010909.db`, оставив свежую копию
  `pre_migration_20261128_040748.db` (6.6 GB, снята при 49 до миграции).

## Обратимость — проверка откат-SQL на копии v50 (продукт не откатывался)

`raw/rollback-copy-check.txt`: `VACUUM INTO` текущей БД (v50) → `/tmp/ab269_v50.db`,
затем rollback-SQL из evidence:

```
copy_user_version_before=50  →  after=49
runs_rows=57 → 57 ; evidence_rows=435 → 435
runs_cols_after=[… 'created_at','updated_at'] (correlation_id удалён)
evidence_cols_after=[… 'source_kind','created_at'] (evidence_id/opened/strength удалены)
indexes_left=['idx_mca_factcheck_runs_chat_time','idx_mca_factcheck_runs_scope_time','idx_mca_factcheck_evidence_run']
legacy_select_runs=(57, 1791296205, 1795268914) ; legacy_select_evidence=(435,) ; stage_trace len=436
copy_integrity=ok ; copy_quick=ok ; rollback_sql_rc=0
```

Старые `SELECT`/`INSERT` формы v49 работают, данные строк не потеряны. Копия удалена
(`copy_exists=False`, `tmp_left=0`). Тот же SQL локально проверен на пробной БД
(`assembly.md` §4). Продуктовая БД **не откатывалась**.

## Rollback кода (dry-run, не выполнялся)

`raw/deploy-post.txt`: временный detached worktree `e46aa0696` → `release_manifest.py
--dry-run --effect rollback` → `rc=0`, манифест `deployed_sha=e46aa0696…`,
`version=2.58.268`, `effect=rollback`; worktree удалён без `--force`, `prune` выполнен,
`rb_worktrees_left=0`, рабочий манифест остался `effect=deploy`. Фактический откат не
выполнялся: старый код совместим с v50 (все новые колонки nullable и им не читаются),
поэтому откат кода возможен **code-only**.

## Routes pin / bundle

- `sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a` (= база).
- `web/app.js` на диске `3631e82de2a8…` = отданный `/web/app.js` (тот же sha256); `/web/` → 200, `/healthz` → 200.

## Сохранённые настройки (PostgreSQL `bot_settings`)

| Metric | 2.58.268 | после 2.58.269 |
|---|---|---|
| rows | 558 | **558** |
| digest md5 (`"\n".join(key=value::text)`, sort by key) | `6f6d6624f5f676a1f26dc4be75128aed` | **`6f6d6624…` (тот же)** |
| `max(updated_at)` | `2026-11-27 21:48:55.892740+00:00` | **тот же** |
| `category='prompts'` | 29 | **29** |
| prompts `max(updated_at)` | `2026-11-27 12:16:16.360531+00:00` | тот же |

`flags.factcheck_enabled=true`, `flags.factcheck_pipeline_v2=true`,
`flags.factcheck_wide_context=true` — без изменений (`raw/settings-digest.txt`).

## Журнал (окно 04:15:14 → 04:38:15 UTC, 23 мин; миграция уже завершена)

`raw/journal-window.txt`, 1810 строк:

| Метрика | Значение |
|---|---|
| `ERROR` | **2** — оба `services.anticliche_worker` (fetch/refresh wikipedia upstream), тот же pre-existing паттерн, что в 2.58.266–2.58.268; к фактчеку/миграции отношения нет |
| `CRITICAL` / `Traceback` | 0 / 0 |
| HTTP 5xx (500/502/503) | 0 / 0 / 0 |
| `no such column` / `sqlite3.OperationalError` / `database is locked` | 0 / 0 / 0 |
| `KeyError` / `TypeError` / `AttributeError` / `ImportError` | 0 / 0 / 0 / 0 |
| Строки фактчек-тракта | только INFO миграции v50 (5 строк) |

Живого пользовательского фактчек-хода в окне не было (тестовые сообщения в рабочие чаты
не отправлялись), поэтому запись `correlation_id`/`deliver` в новых колонках на реальном
прогоне не наблюдалась — это отсутствие вызова, а не сбой; новых исключений в тракте нет.

## Отдельно: FTS5 `integrity_check` (не связано с v50)

Одна живая проверка в 04:47 дала `malformed inverted index for FTS5 table
main.smart_messages_fts`; два последующих живых прогона — `ok` (446 s / 355 s), статичная
копия v50 — `integrity_check=ok`, `quick_check=ok`, FTS5-специфичный
`VALUES('integrity-check')` — ok, `MATCH` возвращает строки (794), в индексе 2 121 871 строк;
в журнале нет ни одного `malformed`/`fts`-сообщения. Вывод: артефакт чтения живого FTS5-индекса
при конкурентной записи, не дефект данных и не следствие миграции. Данные не менялись
(`raw/integrity-fts-note.txt`).

## Disk

`raw/disk.txt`: `df -h /` 99G, used 51G, **avail 44G (54%)** — как до деплоя.
`manage.py disk audit`: `total_bytes=19179296958 (17.9 GiB)`, forecast
`bytes_per_day=1595147249`, `projected_30d=47854417478 (44.6 GiB)`.
`manage.py disk cleanup --apply`: `deleted=0 bytes_freed=0 skipped=0 errors=0` (deploy-пул keep=2).

Пригодные свежие бэкапы — **4** (≥2 соблюдено), включая свежий pre-migration:

```
6816780288  2026-11-27 11:51  backups/predeploy-258258-20261127T115028Z.db
6766456832  2026-11-27 07:26  backups/predeploy-258257-20261127T072559Z.db
6596562944  2026-11-28 04:11  pre_migration_20261128_040748.db   (свежий pre-migration, v49)
5587439616  2026-11-28 00:03  backups/local_database_20261128.db
```

`pre_migration_20261128_040748.db` (`/var/www/admin_bot/`, рядом с БД — так пишет
`migration_backup`) намеренно сохранён как точка возврата для этого релиза;
его ротацию выполнит следующий migration-guard (keep=1) — вручную не удалялся.

## Временные файлы

Созданы и удалены на проде: `/tmp/ab269_appjs`, `/tmp/ab269_rb` (worktree),
`/tmp/ab269_journal.txt`, `/tmp/ab269_jwin.txt`, `/tmp/ab269_j2.txt`,
`/tmp/ab269_copy.db` (v49-копия, ранний прогон), `/tmp/ab269_v50.db`, `/tmp/ab269_fts.db`.
Итог `tmp_left=0`. Основной checkout не откатывался, чужой работы не затрагивалось.

## Ограничения / что осталось

- Реальный пользовательский фактчек-ход в окне не инициировался (запрет на тестовые
  сообщения в рабочие чаты) — запись `correlation_id` и стадии `deliver` в новых колонках
  подтверждена структурно (тесты + схема), но не живым прогоном.
- Единственный `malformed` FTS5-ответ живой проверки объяснён и перепроверен (§ выше);
  данных не касались.
- B-1/B-2 ревью (BACKLOG_ONLY) — вне контракта S6-U1.

## Artefacts

Создано на проде: `.deploy/release.json` (перезаписан), новый процесс сервиса,
новый migration-backup. Временные файлы удалены; release-worktree остаётся до закрытия
очереди.
