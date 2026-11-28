# Release 2.58.268 — deploy evidence (FC-TRUST-01 S5 U1)

Deploy 2026-11-28T03:00:35Z → restart 03:00:36Z. Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 1 recon + 1 deploy + 2 проверочных подключения
(один промах auth по неверному ключу — дальше строго одиночные key-auth сессии), без параллельных
сессий, без фоновых процессов, без копий БД.

## Authorisation and composition

- Reviewed product candidate `a0a34dcd32a3c55004c0f4c1f88cc9b2283391ae` (branch
  `feat/fct-s5-u1-writer-dates-2026-11-28`, tip `dd75a9e67`); review
  `.../fct-s5-u1-2026-11-28/review-r1/review-r1.md` sha256 `fdfd805c…` —
  **APPROVED_FOR_RELEASE_PREPARATION** (B-1 BACKLOG_ONLY).
- Assembly: `assembly.md` (sha256 `22dfd187d43dc6a4387c5b83fe79e329082805b9a773a21f5b961ea041d496c8`)
  — branch `release/2.58.268` от `9709b14af`, продукт `4414a026c`, bump `9c45a454c`,
  assembly evidence `ff010428b`, identity `e46aa0696`; push в `origin/release/2.58.268`.
- Base (deployed): `9709b14af` = 2.58.267.

## Identity

| Field | Value |
|---|---|
| pre-deploy HEAD | `9709b14af6d87a9de18a53825542f7c60c2ffe1f` (2.58.267, detached), `pre_dirty=0` |
| deployed_sha (actual HEAD) | `e46aa0696769a5e2b3caa2c0074c7de209dbb597` |
| previous | `9709b14af` / 2.58.267 |
| checkout | `git fetch --prune origin release/2.58.268` → `git checkout --detach e46aa0696`; `post_dirty=0` |
| changed paths | 51 (`git diff --name-only 9709b14af HEAD`, включая evidence релиза); `umask 022`, `chown adminbot:adminbot`, `chmod 644/755`; `unreadable=0`; `IMPORT_OK 2.58.268` |
| manifest | `effect=deploy`, `deployed_sha=e46aa0696…`, `previous_sha=9709b14af…`, `previous_version=2.58.267`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-28T03:00:35.445730Z` |

Продуктовые блобы на проде (`git hash-object`), совпадают с кандидатом и с релизом:

```
6f916bb9801e04d6c12b899d23779fbb2dbc70d3  services/factcheck_service.py
4e1390cfec76130b15c659f8864f6352be06e4cd  tests/test_fc_trust_s5_writer.py
64bb06c05fc7067b2630951c2b407d5455e631fb  services/factcheck_prompts.py   (= база, канон 4cd1e893)
```

## Version — три источника

`config/settings.py` `APP_VERSION = "2.58.268"`; local `http://127.0.0.1:8000/healthz` →
`{"status":"ok","version":"2.58.268"}`; public `https://admin-bot.duckdns.org/healthz` → same.

## Unit

`active`, MainPID 1204861, `NRestarts=0`, ExecMainStart `2026-11-28 03:00:36 UTC`, один процесс
(`procs=1`). ExecStart = `venv/bin/python bot.py`.

## Routes pin / bundle

- `sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a` (= base).
- `web/app.js` на диске `3631e82de2a8…` = отданный `/web/app.js` (тот же sha256); `/web/` → HTTP 200.

## Schema и сохранённые настройки (PostgreSQL `bot_settings`)

`user_version=49` (sqlite `local_database.db`, read-only). DDL Δ=0, миграций нет.

| Metric | 2.58.267 (в evidence предыдущего релиза) | после 2.58.268 |
|---|---|---|
| `bot_settings` rows | 558 | **558** |
| digest md5 (`"\n".join("key=value::text")`, sort by key) | `6f6d6624f5f676a1f26dc4be75128aed` | **`6f6d6624f5f676a1f26dc4be75128aed`** |
| `max(updated_at)` | `2026-11-27 21:48:55.892740+00:00` | **тот же** |
| `category='prompts'` | 29 | **29** |
| `max(updated_at)` для prompts | — | `2026-11-27 12:16:16.360531+00:00` (старше деплоя) |
| строк, изменённых после 03:00 UTC | — | **0** |

`raw/settings-digest.txt`: формула подтверждена сверкой с дайджестом 2.58.267 — варианты
`md5("\n".join(k=v))` и `md5("\n".join(k=json))` дают ровно `6f6d6624…` (`match_258267=True`),
остальные варианты — нет ⇒ дайджест сопоставим и строки не переписаны.
Stored effective-флаги фактчека: `flags.factcheck_enabled=true`, `flags.factcheck_pipeline_v2=true`,
`flags.factcheck_wide_context=true`.

## Journal window (03:00:32 → 03:13:05 UTC, 12.6 min)

`raw/deploy-post.txt`, 695 строк:

| Метрика | Значение |
|---|---|
| `ERROR` | **2** — оба `services.anticliche_worker` (`step=fetch status=error reason=sources…`, `step=refresh fetch_error`), тот же pre-existing паттерн, что в 2.58.266/2.58.267; к фактчеку отношения нет |
| `CRITICAL` / `Traceback` | **0 / 0** |
| HTTP 5xx | **0** |
| `KeyError` / `TypeError` / `AttributeError` | **0 / 0 / 0** — ошибок нового блока `dates` в Writer-тракте нет |
| Строки фактчек-тракта | 3, все INFO на старте (`factcheck_context_migration`, `factcheck_wide_context_migration` no-op, `SmartModule SmartSearch`) |

Отдельно по Writer-тракту: живого фактчек-хода в окне не было (тестовые сообщения в рабочие чаты
не отправлялись), поэтому строк `_writer_dates_payload` в журнале 0 (`writer_dates_mentions=0`) —
это отсутствие вызова, а не признак сбоя; новых исключений в тракте нет.

## Rollback (dry-run only, not executed)

`raw/deploy-post.txt` — временный detached worktree `9709b14af` на проде + текущий манифест как
«предыдущий»:

```json
{ "deployed_at": "2026-11-28T03:13:11.406226Z", "deployed_sha": "9709b14af6d87a9de18a53825542f7c60c2ffe1f",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "e46aa0696769a5e2b3caa2c0074c7de209dbb597",
  "previous_version": "2.58.268", "schema": 1, "version": "2.58.267" }
```

`rollback_dryrun_rc=0`. Worktree удалён без `--force`, `worktree prune` выполнен,
`git worktree list` = только основной checkout. Рабочий манифест `effect=deploy` не изменён.
DDL Δ=0 ⇒ откат **code-only** (`git checkout --detach 9709b14af` + restart).

## Disk

`raw/deploy-post.txt`: `df -h /` 99G / 50G used / **44G avail (54%)** — как до деплоя.
`manage.py disk audit` (read-only): `total_bytes=19179296958 (17.9 GiB)`, forecast
`bytes_per_day=1603022785`, `projected_30d=48090683566 (44.8 GiB)`.
`manage.py disk cleanup --apply` (deploy pool keep=2): `deleted=0 bytes_freed=0 skipped=0 errors=0`.

Пригодные свежие бэкапы после cleanup — **3** (2 deploy + 1 db), требование ≥2 соблюдено:

```
predeploy-258257-20261127T072559Z.db  6.4G  Nov 27 07:26
predeploy-258258-20261127T115028Z.db  6.4G  Nov 27 11:51
local_database_20261128.db            5.3G  Nov 28 00:03
```

Полная копия БД не создавалась (DDL 0). Временные файлы на проде
(`/tmp/ab268_changed.txt`, `/tmp/ab268_journal.txt`, `/tmp/ab268_appjs`, `/tmp/ab268_manifest.json`,
`/tmp/ab268_rb`) удалены — `tmp_left=0`.

## Live-smoke

Тестовые сообщения в рабочие чаты **не отправлялись**. Проверено: три источника версии,
`/healthz` локально и публично, `/web/` HTTP 200, отданный `app.js` == диску, `IMPORT_OK`,
`user_version`, PostgreSQL-строки/digest/prompts, блоб-идентичность продуктовых файлов, журнал.

## Ограничения

- Живой пользовательский фактчек-ход в окне не инициировался, поэтому новые даты в тексте Writer'а
  наблюдались только на уровне payload-тестов (`test_fc_trust_s5_writer`, 8 passed) — в журнале
  ошибок тракта нет, но реальная формулировка дат уйдёт в чат при следующем фактчек-ответе.
- B-1 ревью (BACKLOG_ONLY): `retrieved_at` snippet-only строк — вне контракта S5-U1.

## Artefacts

Создано на проде: `.deploy/release.json` (перезаписан), новый процесс сервиса. Временные файлы
удалены; worktree релиза остаётся до закрытия очереди.
