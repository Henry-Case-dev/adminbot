# Release 2.58.264 — deploy evidence (FC-TRUST-01 S1)

Deploy 2026-11-27T23:01:08Z → restart 23:01:09Z. Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 4 single key-auth connections (recon, deploy,
post-window, read-only flags), no parallel sessions, no background processes, no DB copy, no retries.

## Authorisation and composition

- Reviewed product candidate `c55b0ddb4ac4ec17ecb1acb195557bb9919f5142` (branch
  `fix/fct-s1-contract-gaps-2026-11-28`, tip `b614f3fdb`); review
  `.../fct-s1-gaps-2026-11-28/review-r2/review-r2.md` sha256 `80fba406…` —
  **APPROVED_FOR_RELEASE_PREPARATION** (RV-S1-01 closed; R1 `56e3d1240`).
- Assembly: `assembly.md` (sha256 `50722992…`) — branch `release/2.58.264` from `4cdd72e17`,
  product commit `0118dc081`, bump `c531aab1e`, evidence `c67683dd6`.
- Base (deployed): `4cdd72e17` = 2.58.263.

## Identity

| Field | Value |
|---|---|
| pre-deploy HEAD | `4cdd72e17ef418c3901497dcce717d53bda1a62f` (2.58.263, detached), `dirty_tracked=0` |
| deployed_sha (actual HEAD) | `c67683dd68dc4e2e3d48bff06c6568b3448cbc20` |
| previous | `4cdd72e17` / 2.58.263 |
| checkout | `git fetch --prune origin release/2.58.264` → `git checkout --detach c67683dd6`; `post_dirty=0` |
| changed paths | 48 (`git diff --name-only 4cdd72e17 HEAD`, включая evidence-файлы релиза); `chown adminbot:adminbot`, `chmod 644`, `umask 022`; `UNREADABLE` для сервисного пользователя = **0**; `IMPORT_OK 2.58.264` |
| manifest | `effect=deploy`, `deployed_sha=c67683dd6…`, `previous_sha=4cdd72e17…`, `previous_version=2.58.263`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-27T23:01:08.123708Z`, `deployer=devops` |

Продуктовые блобы на проде == кандидату (см. «Product SHA на проде»).

## Version — три источника

`config/settings.py` `APP_VERSION = "2.58.264"`; local `http://127.0.0.1:8000/healthz` →
`{"status":"ok","version":"2.58.264"}`; public `https://admin-bot.duckdns.org/healthz` → same.

## Unit

`active`, MainPID 1137172, `NRestarts=0`, ExecMainStart `2026-11-27 23:01:09 UTC`, один процесс.

## Routes pin / bundle

- `sha256(web/api/routes.py)` = `b8f63355…` (= base; routes не менялись).
- `web/app.js` на диске `3631e82de2a8…` (2739459 B) = отданный `/web/app.js`.

## Schema и сохранённые настройки (PostgreSQL `bot_settings`)

`user_version=49` (sqlite, read-only). DDL Δ=0, миграций нет.

| Metric | Before (pre-restart) | After |
|---|---|---|
| `bot_settings` rows | 558 | **558** |
| md5 всех строк (key=value, sort by key) | `50887d362fe93bf7646beae77cce32c6` | **`50887d362fe93bf7646beae77cce32c6`** |
| `max(updated_at)` | `2026-11-27 21:48:55.89274+00` | **`2026-11-27 21:48:55.89274+00`** |
| `category='prompts'` | 29 | **29** |

Новых сидов нет (`services/param_catalog.py` не менялся) ⇒ ни одна настройка не переписана:
rowcount, md5 и max(updated_at) совпадают до/после.

## Effective-конфигурация фактчека (D6, read-only, настройки не менялись)

`raw/effective-flags.txt` — фактическое значение существующих глобальных строк `bot_settings`:

| Ключ | Значение на проде |
|---|---|
| `flags.factcheck_enabled` | **true** (пайплайн фактчека включён) |
| `flags.factcheck_pipeline_v2` | true |
| `flags.factcheck_suitability_gate` | false |
| `flags.factcheck_wide_context` | true |
| `flags.factcheck_wide_context_default_v1` | true |

`GET https://admin-bot.duckdns.org/api/config` → **401** без Telegram `initData` (эндпоинт жив,
тело не читалось: авторизованной TMA-сессии у агента нет, подделка `initData` не выполнялась).
Per-chat override отдельно не перечислялись: подходящей таблицы overrides в схеме не найдено,
отдельный обход не делался — глобальное значение и отсутствие новых сидов зафиксированы.

## Product SHA на проде (байтовая идентичность)

`raw/deploy-final-window.txt`:

```
services/factcheck_planner.py      b143e4a7713c3bc960444a389629df64f0d7347a  (= candidate)
services/factcheck_service.py      12c74ebc578ec6b8e27b0b9015c78189592c9c10  (= candidate)
services/factcheck_orchestrator.py 485bbe38cef2206e2869aa49eeaeb7c56aefb1b2  (= candidate)
tests/test_fc_trust_s1_contract.py 5d5affc9ef6b2a9c60fb2364ab300293eb026e9b  (= candidate)
```

## Journal window (23:01:09 → 23:14:17 UTC, 13.1 min)

687 строк. HTTP 5xx = **0**; `Traceback` = **0**; `CRITICAL` = **0**; `KeyError` = **0**;
`AttributeError` = **0**; `TypeError` = **0**; упоминаний `assertion_kind`/`ClaimUnit` = 0
(живой фактчек-ход в окне не инициировался).

`ERROR` = **2** — оба pre-existing в `services.anticliche_worker`
(`[pipeline] component=anticliche step=fetch/refresh … sources_unavailable`), тот же паттерн,
что в evidence 2.58.263; к дельте отношения нет.

Строк фактчека — 3, все INFO на старте:
`[factcheck_context_migration] legacy == дефолт — мигрировать нечего`,
`[factcheck_wide_context_migration] уже применено — no-op`,
`SmartModule SmartSearch … (FactCheck — после сборки ToolRouter)`. Ошибок в фактчек-тракте — 0.

## Rollback (dry-run only, not executed)

Временный detached worktree `4cdd72e17` + текущий манифест:
`tools/release_manifest.py --effect rollback --dry-run` → **rc=0**

```json
{ "deployed_at": "2026-11-27T23:14:21.185004Z", "deployed_sha": "4cdd72e17ef418c3901497dcce717d53bda1a62f",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "c67683dd68dc4e2e3d48bff06c6568b3448cbc20",
  "previous_version": "2.58.264", "schema": 1, "version": "2.58.263" }
```

DDL Δ=0 ⇒ откат code-only (`git checkout --detach 4cdd72e17` + restart). Worktree удалён
без `--force`, `worktree prune` выполнен, `git worktree list` = только основной checkout.

## Disk

`raw/deploy-final-window.txt`: `df -h /` 99G total / 51G used / **43G avail (55%)** — до и после.
`manage.py disk audit`: forecast `bytes_per_day=1686631609`, `projected_30d=50598948286 (47.1 GiB)`,
top category `deploy_backup` (`predeploy-258258-…db` 6.82 GB, `predeploy-258257-…db` 6.77 GB).
`disk cleanup --apply` (deploy pool keep=2): `deleted=0 bytes_freed=0 skipped=0 errors=0`.
Полная копия БД не создавалась (DDL 0). Временные файлы удалены, `/tmp/ab264*` и `/tmp/rb264*` — 0.

## Live-smoke

Тестовые сообщения в рабочие чаты **не отправлялись**. Проверено: три источника версии,
`/healthz` локально и публично, `/web/` HTTP 200, отданный `app.js` == диску, `IMPORT_OK`,
`user_version`, настройки, журнал, PostgreSQL-строки.

## Ограничения

- Живой пользовательский фактчек-ход в окне не инициировался (в рабочие чаты тестовых сообщений не отправлялось).
- FCT-113 остаётся REVIEW (семантика — S4); B-1 — BACKLOG_ONLY.

## Artefacts

Создано на проде: `.deploy/release.json` (перезаписан), новый процесс сервиса. Временные файлы
(`/tmp/ab264_changed.txt`, локальные скрипты прогонов) удалены; worktree релиза остаётся до закрытия очереди.
