# Release 2.58.267 — deploy evidence (FC-TRUST-01 S4 U3)

Deploy 2026-11-28T01:52:29Z → restart 01:52:34Z. Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 4 single key-auth connections (recon, deploy,
post-checks/journal/rollback/disk), no parallel sessions, no background processes, no DB copy,
no retries.

## Authorisation and composition

- Reviewed product candidate `718fe0a824522d68aa58605fc2b8ef1711e62534` (branch
  `feat/fct-s4-u3-publication-2026-11-28`, tip `266c9d381`); review
  `.../fct-s4-u3-2026-11-28/review-r1/review-r1.md` sha256 `50ad6040…` —
  **APPROVED_FOR_RELEASE_PREPARATION** (RV-S4U3-01 BACKLOG_ONLY).
- Assembly: `assembly.md` (sha256 `77c325f3…`) — branch `release/2.58.267` from `cd2245fdb`,
  product commit `390f146f0`, bump `7b835b838`, evidence `9709b14af`.
- Base (deployed): `cd2245fdb` = 2.58.266.

## Identity

| Field | Value |
|---|---|
| pre-deploy HEAD | `cd2245fdbc50b764843aa1f6128cae824f054af7` (2.58.266, detached), `pre_dirty=0` |
| deployed_sha (actual HEAD) | `9709b14af6d87a9de18a53825542f7c60c2ffe1f` |
| previous | `cd2245fdb` / 2.58.266 |
| checkout | `git fetch --prune origin release/2.58.267` → `git checkout --detach 9709b14af`; `post_dirty=0` |
| changed paths | 53 (`git diff --name-only cd2245fdb HEAD`, включая evidence-файлы релиза); `umask 022`, `chown adminbot:adminbot`, `chmod 644`; `unreadable=0`; `IMPORT_OK 2.58.267` |
| manifest | `effect=deploy`, `deployed_sha=9709b14af…`, `previous_sha=cd2245fdb…`, `previous_version=2.58.266`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-28T01:52:32.688855Z` |

Продуктовые блобы на проде (`git hash-object`), совпадают с кандидатом:

```
9866e390cd65… services/factcheck_renderer.py       (= candidate)
15688f173fe3… services/factcheck_orchestrator.py   (= candidate)
502604e57986… services/search_aggregator.py        (= candidate)
0b2c70491789… tests/test_fc_trust_render.py        (= candidate)
```

## Version — три источника

`config/settings.py` `APP_VERSION = "2.58.267"`; local `http://127.0.0.1:8000/healthz` →
`{"status":"ok","version":"2.58.267"}`; public `https://admin-bot.duckdns.org/healthz` → same.

## Unit

`active`, MainPID 1185992, `NRestarts=0`, ExecMainStart `2026-11-28 01:52:34 UTC`, один процесс
(`procs=1`).

## Routes pin / bundle

- `sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a`
  (= base; routes не менялись).
- `web/app.js` на диске `3631e82de2a8…` = отданный `/web/app.js` (тот же sha256);
  `/web/` → HTTP 200.

## Schema и сохранённые настройки (PostgreSQL `bot_settings`)

`user_version=49` (sqlite `local_database.db`, read-only) до и после. DDL Δ=0, миграций нет.

| Metric | до деплоя | после деплоя |
|---|---|---|
| `bot_settings` rows | 558 | **558** |
| digest всех строк (md5 `key=value::text`, sort by key) | `6f6d6624f5f676a1f26dc4be75128aed` | **тот же** |
| `max(updated_at)` | `2026-11-27 21:48:55.892740+00:00` | **тот же** |
| `category='prompts'` | 29 | **29** |

Digest считается одной и той же формулой до и после ⇒ ни одна строка не переписана; новых
сидов нет (`services/param_catalog.py` не менялся). Effective-флаги фактчека (read-only)
включены: `flags.factcheck_enabled=true`, `flags.factcheck_pipeline_v2=true`,
`flags.factcheck_wide_context=true`.

## Journal window (01:52:34 → 02:06:41 UTC, 14.1 min)

`raw/deploy-post.txt` (отметка 01:52:40Z, 575 строк) + `raw/deploy-post2.txt` (с момента старта
01:52:30Z, 936 строк):

| Метрика | Значение |
|---|---|
| `ERROR` | **3** — 1 startup-запись `services.mca_events` `event_name=INCIDENT outcome=success` (журнал уже известных инцидентов, не новый сбой) + 2 pre-existing `services.anticliche_worker` `sources_unavailable` / `fetch_error wikipedia` (тот же паттерн, что в 2.58.266) |
| `CRITICAL` / `Traceback` | **0 / 0** |
| HTTP 5xx | **0** |
| `KeyError` / `AttributeError` / `TypeError` | **0 / 0 / 0** — новых полей (`publication_kind`, `unverified_media`, `execution_cause`) в тракте ошибок нет |
| Строки фактчек-тракта | 3, все INFO на старте (`factcheck_context_migration` no-op, `factcheck_wide_context_migration` no-op, `SmartModule SmartSearch`) — ошибок рендерера/оркестратора 0 |

## Rollback (dry-run only, not executed)

`raw/deploy-post2.txt` — временный detached worktree `cd2245fdb` на проде + текущий манифест
как «предыдущий»:

```json
{ "deployed_at": "2026-11-28T02:07:05.412551Z", "deployed_sha": "cd2245fdbc50b764843aa1f6128cae824f054af7",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "9709b14af6d87a9de18a53825542f7c60c2ffe1f",
  "previous_version": "2.58.267", "schema": 1, "version": "2.58.266" }
```

`rc=0`. Worktree удалён без `--force`, `worktree prune` выполнен, `git worktree list` = только
основной checkout, `/tmp/ab267*` = 0. Рабочий манифест `effect=deploy` не изменён.
DDL Δ=0 ⇒ откат **code-only** (`git checkout --detach cd2245fdb` + restart).

## Disk

`raw/deploy-post.txt`: `df -h /` 99G total / 50G used / **44G avail (54%)** — до и после.
`manage.py disk audit`: forecast `bytes_per_day=1609231610`, `projected_30d=48276948314 (45.0 GiB)`.
`manage.py disk cleanup --apply` (deploy pool keep=2): `deleted=0 bytes_freed=0 skipped=0 errors=0`.

Пригодные свежие бэкапы после cleanup — **3** (2 deploy + 1 db backup), требование ≥2 соблюдено:

```
predeploy-258257-20261127T072559Z.db  6.4G  Nov 27 07:26
predeploy-258258-20261127T115028Z.db  6.4G  Nov 27 11:51
local_database_20261128.db            5.2G  Nov 28 00:03
```

Полная копия БД не создавалась (DDL 0). Временные файлы (`/tmp/ab267_changed.txt`,
`/tmp/ab267_journal.txt`, `/tmp/ab267_j2.txt`, `/tmp/ab267_rb*`) удалены, остаток 0.

## Live-smoke

Тестовые сообщения в рабочие чаты **не отправлялись**. Проверено: три источника версии,
`/healthz` локально и публично, `/web/` HTTP 200, отданный `app.js` == диску, `IMPORT_OK`,
`user_version`, PostgreSQL-строки/digest, блоб-идентичность продуктовых файлов, журнал.

## Ограничения

- Живой пользовательский фактчек-ход в окне не инициировался (в рабочие чаты тестовых сообщений
  не отправлялось); новые ветки рендера (`technical/partial`, подписи `publication_kind`,
  per-part `media_note`) в окне наблюдались только по тракту без живого хода — ошибок тракта нет.
- RV-S4U3-01 (BACKLOG_ONLY): `ambiguous_no_text_claim` / `album_incomplete` не попадают в
  `media_note`; вне контракта релиза.

## Artefacts

Создано на проде: `.deploy/release.json` (перезаписан), новый процесс сервиса. Временные файлы
(`/tmp/ab267_*`) удалены; worktree релиза остаётся до закрытия очереди.
