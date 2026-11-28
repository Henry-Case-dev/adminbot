# Release 2.58.265 — deploy evidence (FC-TRUST-01 S4 U2)

Deploy 2026-11-28T00:02:22Z (manifest 00:02:23Z) → restart 00:03:23Z. Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 6 одиночных key-auth подключений за ~15 минут
(recon, deploy, проверка, компактная идентичность, права, окно журнала/rollback/диск, smoke),
без параллельных сессий, без фоновых процессов, без копии БД, без ретраев.

## Авторизация и состав

- Reviewed-кандидат `6ab3b718a665b6f61e2ab7e018f62d4d05040a66` (ветка
  `feat/fct-s4-u2-verdict-2026-11-28`, tip `6d911272e`); ревью
  `.../fct-s4-u2-2026-11-28/review-r1/review-r1.md` sha256 `b8483a26…` —
  **APPROVED_FOR_RELEASE_PREPARATION**.
- Сборка: `assembly.md` (sha256 `95927ca4…`) — ветка `release/2.58.265` от `c67683dd6`,
  product `aa7f3f6d8`, bump `d95ac5ca0`, evidence `55178d5bd` (= tip, запушен в origin).
- База (deployed): `c67683dd6` = 2.58.264.

## Идентичность

| Поле | Значение |
|---|---|
| pre-deploy HEAD | `c67683dd68dc4e2e3d48bff06c6568b3448cbc20` (2.58.264, detached), `dirty=0` |
| deployed_sha (фактический HEAD) | `55178d5bd1c7f21f2c4966195df7cb7a93096503` |
| previous | `c67683dd6` / 2.58.264 |
| checkout | `git fetch --prune origin release/2.58.265` → `git checkout --detach 55178d5bd`; `dirty_after=0` |
| changed paths | 54 (`git diff --name-only c67683dd6 HEAD`, включая evidence релиза); `chown adminbot:adminbot`, `chmod 644/755`, `umask 022`; `UNREADABLE` для сервисного пользователя = **0** (`perms_checked`, ни одной строки `UNREADABLE`) |
| manifest | `effect=deploy`, `deployed_sha=55178d5bd…`, `previous_sha=c67683dd6…`, `previous_version=2.58.264`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-28T00:02:23.554971Z`, `deployer=devops` |

## Версия — три источника

`config/settings.py` `APP_VERSION = "2.58.265"`; local `http://127.0.0.1:8000/healthz` →
`{"status":"ok","version":"2.58.265"}`; public `https://admin-bot.duckdns.org/healthz` → тот же ответ.
`IMPORT_OK 2.58.265` (venv сервисного пользователя).

## Unit

`active/running`, MainPID 1154684, `NRestarts=0`, ExecMainStart `2026-11-28 00:03:23 UTC`,
`procs=1` (`pgrep -fc 'venv/bin/python /var/www/admin_bot/bot.py'`).

## Product SHA на проде (байтовая идентичность)

`git hash-object` на проде == блобы кандидата:

```
8db1e41fece0684978cbd35c90920c67fa459b66  services/factcheck_orchestrator.py
e06c6afb9c83c39ac93b35fafebec70b5987aef2  services/factcheck_service.py
db1e73341020ad3f0f632e285f6dbbf9fb3c7fd3  services/factcheck_planner.py
c9b0f4cae07474ea143644331905082858775937  tests/test_fc_trust_verdict.py
aa443043e1ab8dc9b172f8f220d3fb1acff1f225  tests/test_evol_fc_evidence_style.py
569a4b91e3941a9730053315ad95ea9131fc726a  tests/test_factcheck_fc_r1_fix.py
82298d04a82ddf435bd2462306eec1c8c7a37c49  tests/test_factcheck_orchestrator_cfg06.py
0f43bb08032b8dad7fc81c6d56915033eab96e26  tests/test_factcheck_service.py
```

3/3 продуктовых и 5/5 тестовых файлов совпадают с `6ab3b718a`.

## Routes pin / bundle

- `sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a` (= base).
- `web/app.js` на диске `3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a`
  (2739459 B) == отданный `/web/app.js` (HTTP 200, sha совпал); `/web/` → HTTP 200.

## Schema и сохранённые настройки (PostgreSQL `bot_settings`)

`user_version=49` (sqlite, read-only). DDL Δ=0, миграций нет.

| Metric | Значение |
|---|---|
| `bot_settings` rows | **558** |
| `category='prompts'` | **29** |
| `max(updated_at)` | `2026-11-27 21:48:55.892740+00:00` — не изменился с 2.58.264 |
| md5 (python, key=value по строкам) | `5cf6fe370bb3a3c52a1f9efc0e66328e` |

Метод md5 отличается от SQL-выражения прошлого релиза, поэтому хеши напрямую не сравнивались.
Неизменность подтверждена rowcount 558, prompts 29, неизменным `max(updated_at)` и отсутствием
новых сидов (`services/param_catalog.py` не менялся).

## Журнал (00:03:23 → 00:17:49 UTC, 14.4 мин)

805 строк: `ERROR` = **2** (оба pre-existing `services.anticliche_worker`
`step=fetch/refresh … sources_unavailable` — тот же паттерн, что в 2.58.264), `WARNING` = 4,
`KeyError` = **0**, `AttributeError` = **0**, `TypeError` = **0**.

`Traceback` = **1** — таймаут LLM в `services/initiative_observer.py::_evaluate_window`
(WARNING `[b01] opportunity eval failed`, стек через `llm_client.generate`), к фактчек-тракту
не относится. Класс pre-existing: в предыдущем 62-минутном окне (23:01:09–00:03:22) было
**11** Traceback при том же коде 2.58.264.

Фактчек-тракт: `execution_status`-событий = 0, `factcheck_claims` = 0 — живой пользовательский
фактчек-ход в окне не инициировался (тестовые сообщения в рабочие чаты не отправлялись),
поэтому новых `KeyError`/`AttributeError` в тракте быть не могло по факту отсутствия прогонов.

Сразу после restart публичный `/web/` на +5 с вернул **502** (бэкенд ещё поднимался);
к 00:04:14 local и public `/healthz` → 200, `/web/` и `/web/app.js` → 200. Устойчивого 5xx нет.

## Smoke развёрнутого кода (venv сервисного пользователя, без внешних вызовов)

```
fields_ok True unknown '' evidence
statuses 4 causes 9
partial-> insufficient_evidence
conflicting-> mixed
confirmed-> supported
```

`CheckedVerdict` содержит `execution_status`/`execution_cause`/`proof_basis` с заявленными
default-значениями; `EXECUTION_STATUSES` = 4, `EXECUTION_CAUSES` = 9; P0-маппинг
PARTIAL → `insufficient_evidence` действует на проде, `CONFLICTING` → `mixed` сохранён.

## Rollback (dry-run, не выполнялся)

Временный detached worktree `c67683dd6` + текущий манифест:
`tools/release_manifest.py --repo-root /tmp/rb265 --effect rollback --dry-run` → **rc=0**

```json
{ "deployed_at": "2026-11-28T00:17:53.252517Z", "deployed_sha": "c67683dd68dc4e2e3d48bff06c6568b3448cbc20",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "55178d5bd1c7f21f2c4966195df7cb7a93096503",
  "previous_version": "2.58.265", "schema": 1, "version": "2.58.264" }
```

DDL Δ=0 ⇒ откат code-only (`git checkout --detach c67683dd6` + restart). Worktree удалён без
`--force`, `git worktree prune` выполнен, `git worktree list` = только основной checkout.

## Диск

До деплоя: 55G used / 38–40G free (59%). После: 56G used / 38G free; `disk cleanup --apply`
(deploy pool keep=2) → `deleted=1 bytes_freed=6308028416 (5.9 GiB) skipped=0 errors=0`
(`local_database_20261127.db`, category `db_backup`); итог **50G used / 44G free (54%)**.
`disk audit`: forecast `bytes_per_day=2152152521`, `projected_30d=64564575658 (60.1 GiB)`,
top — `predeploy-258258-…db` 6.82 GB, `predeploy-258257-…db` 6.77 GB (retention keep=2 не тронул).
Полная копия БД не создавалась (DDL 0). Временные `/tmp/ab265*`, `/tmp/rb265`, `/tmp/j_*265.txt` — 0.

## Live-smoke

Тестовые сообщения в рабочие чаты **не отправлялись**. Проверено: три источника версии,
`/healthz` локально и публично, `/web/` и `/web/app.js` HTTP 200, served `app.js` == диску,
`IMPORT_OK`, `user_version`, настройки PG, журнал, manifest, smoke развёрнутого модуля.

## Ограничения

- Живой пользовательский фактчек-ход не инициировался (запрет тестовых сообщений в рабочие чаты);
  поведение `execution_status` на реальном turn не наблюдалось, проверены поля, статусы и маппинг.
- Публикация `execution_status` пользователю — U3 (вне релиза). RV-S4U2-01/02 — BACKLOG_ONLY.
- `Traceback` в окне — pre-existing LLM-таймаут `initiative_observer`, не связан с дельтой.

## Артефакты

Создано на проде: `.deploy/release.json` (перезаписан), новый процесс сервиса.
Временные файлы удалены; worktree релиза остаётся до закрытия очереди.
