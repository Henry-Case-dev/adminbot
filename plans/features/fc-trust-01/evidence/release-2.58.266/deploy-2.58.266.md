# Release 2.58.266 — deploy evidence (FC-TRUST-01 S4 U1)

Deploy 2026-11-28T01:05:44Z → restart 01:06:45Z. Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 5 single key-auth connections (recon, deploy,
settings/identity, journal window, rollback dry-run), no parallel sessions, no background
processes, no DB copy, no retries.

## Authorisation and composition

- Reviewed product candidate `282151269852c57c916e8fd26f2bffd00747fad8` (branch
  `feat/fct-s4-u1-evidence-2026-11-28`, tip `d5e1247cb`); review
  `.../fct-s4-u1-2026-11-28/review-r2/review-r2.md` sha256 `15b01429…` —
  **APPROVED_FOR_RELEASE_PREPARATION** (RV-S4U1-01/02 closed; R1 `a0ae1ba05`).
- Assembly: `assembly.md` (sha256 `6e3ab81d…`) — branch `release/2.58.266` from `55178d5bd`,
  product commit `7d4ab2f00`, bump `9ffa54954`, evidence `cd2245fdb`.
- Base (deployed): `55178d5bd` = 2.58.265.

## Identity

| Field | Value |
|---|---|
| pre-deploy HEAD | `55178d5bd1c7f21f2c4966195df7cb7a93096503` (2.58.265, detached), `pre_dirty=0` |
| deployed_sha (actual HEAD) | `cd2245fdbc50b764843aa1f6128cae824f054af7` |
| previous | `55178d5bd` / 2.58.265 |
| checkout | `git fetch --prune origin release/2.58.266` → `git checkout --detach cd2245fdb`; `post_dirty=0` |
| changed paths | 54 (`git diff --name-only 55178d5bd HEAD`, включая evidence-файлы релиза); `umask 022`, `chown adminbot:adminbot`, `chmod 644`; `UNREADABLE` для сервисного пользователя = **0**; `IMPORT_OK 2.58.266` |
| manifest | `effect=deploy`, `deployed_sha=cd2245fdb…`, `previous_sha=55178d5bd…`, `previous_version=2.58.265`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-28T01:05:44.851535Z` |

`raw/deploy-settings-identity.txt` — блобы на проде (`git hash-object`), совпадают с кандидатом:

```
1fdc8333544a… services/factcheck_planner.py       (= candidate)
cba937d970b0… services/search_aggregator.py       (= candidate)
3c5aa47f7cca… services/temporal_factcheck.py      (= candidate)
54c9e3004dfd… services/factcheck_orchestrator.py  (= candidate)
64cedab6a708… services/factcheck_service.py       (= candidate)
28eeb7d99e37… tests/test_fc_trust_s4_evidence.py  (= candidate)
```

## Version — три источника

`config/settings.py` `APP_VERSION = "2.58.266"`; local `http://127.0.0.1:8000/healthz` →
`{"status":"ok","version":"2.58.266"}`; public `https://admin-bot.duckdns.org/healthz` → same.

## Unit

`active`, MainPID 1172938, `NRestarts=0`, ExecMainStart `2026-11-28 01:06:45 UTC`, один процесс
(`procs=1`).

## Routes pin / bundle

- `sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a`
  (= base; routes не менялись).
- `web/app.js` на диске `3631e82de2a8…` (2739459 B) = отданный `/web/app.js` (тот же sha256);
  `/web/` → HTTP 200.

## Schema и сохранённые настройки (PostgreSQL `bot_settings`)

`user_version=49` (sqlite `local_database.db`, read-only). DDL Δ=0, миграций нет.

| Metric | Значение после релиза | Сверка |
|---|---|---|
| `bot_settings` rows | **558** | без изменений |
| md5 всех строк (key=value, sort by key) | `50887d362fe93bf7646beae77cce32c6` | **совпадает** с 2.58.264/2.58.265 |
| `max(updated_at)` | `2026-11-27 21:48:55.892740+00:00` | не двигался ⇒ ни одна строка не переписана |
| `category='prompts'` | **29** | без изменений |

Новых сидов нет (`services/param_catalog.py` не менялся) ⇒ сохранённые пользовательские настройки
не затронуты. Effective-флаги фактчека (read-only) фактически включены:
`flags.factcheck_enabled=true`, `flags.factcheck_pipeline_v2=true`, `flags.factcheck_wide_context=true`.

## Journal window (01:06:45 → 01:18:44 UTC, 12.0 min)

`raw/deploy-final-window.txt`: **681 строка**.

| Метрика | Значение |
|---|---|
| `ERROR` | **4** — 2 startup-записи `services.mca_events` `event_name=INCIDENT outcome=success` (журнал уже известных инцидентов, не новый сбой) + 2 pre-existing `services.anticliche_worker` `sources_unavailable` (тот же паттерн, что в 2.58.264) |
| `CRITICAL` / `Traceback` | **0 / 0** |
| HTTP 5xx | **0** |
| `KeyError` / `AttributeError` / `TypeError` | **0 / 0 / 0** — новых полей `ClaimEvidence` (`publication_kind`, раздельные time-поля, `unverified_media`) в тракте ошибок нет |
| Строки фактчека | 3, все INFO на старте (`factcheck_context_migration` no-op, `factcheck_wide_context_migration` no-op, `SmartModule SmartSearch`) — ошибок в фактчек-тракте 0 |

## Rollback (dry-run only, not executed)

`raw/rollback-dryrun.txt` — временный detached worktree `55178d5bd` на проде + текущий манифест:

```json
{ "deployed_at": "2026-11-28T01:19:31.606192Z", "deployed_sha": "55178d5bd1c7f21f2c4966195df7cb7a93096503",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "cd2245fdbc50b764843aa1f6128cae824f054af7",
  "previous_version": "2.58.266", "schema": 1, "version": "2.58.265" }
```

`rc=0`. Worktree удалён без `--force`, `worktree prune` выполнен, `git worktree list` = только
основной checkout, `/tmp/ab266*` = 0. Рабочий манифест `effect=deploy` не изменён.
DDL Δ=0 ⇒ откат **code-only** (`git checkout --detach 55178d5bd` + restart).

## Disk

`raw/deploy-run.txt`: `df -h /` 99G total / 50G used / **44G avail (54%)** — до и после.
`manage.py disk audit`: forecast `bytes_per_day=1614849934`, `projected_30d=48445498021 (45.1 GiB)`.
`manage.py disk cleanup --apply` (deploy pool keep=2): `deleted=0 bytes_freed=0 skipped=0 errors=0`.

Пригодные свежие бэкапы после cleanup — **2** (правило проекта соблюдено):

```
predeploy-258257-20261127T072559Z.db  6.4G  Nov 27 07:26
predeploy-258258-20261127T115028Z.db  6.4G  Nov 27 11:51
```

Полная копия БД не создавалась (DDL 0). Временные файлы (`/tmp/ab266_changed.txt`,
`/tmp/ab266_journal.txt`) удалены.

## Live-smoke

Тестовые сообщения в рабочие чаты **не отправлялись**. Проверено: три источника версии,
`/healthz` локально и публично, `/web/` HTTP 200, отданный `app.js` == диску, `IMPORT_OK`,
`user_version`, PostgreSQL-строки, блоб-идентичность продуктовых файлов, журнал.

## Ограничения

- Живой пользовательский фактчек-ход в окне не инициировался (в рабочие чаты тестовых сообщений не отправлялось).
- Новые поля `ClaimEvidence` (`publication_kind`, раздельные time-поля, `unverified_media`) в окне
  наблюдались только по импорту/тракту без живого хода; ошибок импорта и тракта нет.

## Artefacts

Создано на проде: `.deploy/release.json` (перезаписан), новый процесс сервиса. Временные файлы
(`/tmp/ab266_changed.txt`, `/tmp/ab266_journal.txt`) удалены; worktree релиза остаётся до закрытия
очереди.
