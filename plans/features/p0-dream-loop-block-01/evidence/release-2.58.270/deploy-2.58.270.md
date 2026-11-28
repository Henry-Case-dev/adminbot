# Release 2.58.270 — deploy evidence (P0-DREAM-LOOP-BLOCK)

Деплой 2026-11-28T06:09:2xZ (checkout) → restart 06:09:31Z. Роль: DevOps.
Host `192.255.209.205:/var/www/admin_bot`. SSH: 4 одиночных key-auth соединения
(recon, deploy, post-window, final), без параллельных сессий, без фоновых процессов,
без копии БД, без ретраев.

## Авторизация и состав

- Reviewed-кандидат `e30ae12bf0a6fff5f7eac7bfaea400175dd55c52` (ветка
  `fix/p0-dream-loop-block-2026-11-28`, tip `028dcf637`); ревью
  `.../fix-2026-11-28/review-r1/review-r1.md` sha256 `4abee23f…` —
  **APPROVED_FOR_RELEASE_PREPARATION**; B-1/B-2 — BACKLOG_ONLY.
- Сборка: `assembly.md` — ветка `release/2.58.270` от `6d97c02d8`, продукт `344d6126b`
  (побайтово `e30ae12bf`), bump `3eafef83c`, evidence `63f6d4422` + `438ad790e`.
- База (deployed): `6d97c02d8` = 2.58.269, `user_version=50`.

## Identity

| Поле | Значение |
|---|---|
| pre-deploy HEAD | `6d97c02d8a4830c5824cc9c39db311373f953b6d` (2.58.269, detached), `dirty=0` |
| deployed_sha (фактический HEAD) | `438ad790eb998d1af6d6731be4392ea1d6179b4e` |
| previous | `6d97c02d8` / 2.58.269 |
| checkout | `git fetch --prune origin release/2.58.270` → `git checkout --detach 438ad790e`; `dirty=0` |
| changed paths | 51 (`git diff --name-only 6d97c02d8 HEAD`, включая evidence релиза); `chown adminbot:adminbot`, `chmod 644`, `umask 022`; `UNREADABLE` для сервисного пользователя = **0**; `IMPORT_OK 2.58.270 offloop=True budget_s=5.0 mmr_unchanged=True` |
| manifest | `effect=deploy`, `deployed_sha=438ad790e…`, `previous_sha=6d97c02d8…`, `previous_version=2.58.269`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-28T06:17:51.700219Z`, `deployer=devops` |

Манифест записан штатным `tools/release_manifest.py` (rc=0) **после** рестарта
(06:17:51Z); рестарт 06:09:31Z был выполнен вручную, потому `deployed_at` позже
старта процесса, а `deployed_sha` совпадает с фактическим HEAD. Ограничение честное,
identity не выдумана: `dirty_tracked=false` при `dirty=0`.

## Версия — три источника

`config/settings.py` `APP_VERSION = "2.58.270"`; `venv/bin/python -c` → `2.58.270`;
local `http://127.0.0.1:8000/healthz` → `{"status":"ok","version":"2.58.270"}`;
public `https://admin-bot.duckdns.org/healthz` → то же.

## Unit

`active`, MainPID **1258470**, `NRestarts=0`, ExecMainStart `2026-11-28 06:09:31 UTC`,
`procs=1` (один процесс).

## Graceful stop (B-1 из ревью)

Перед рестартом проверено отсутствие активного глубокого прохода:
`journalctl --since -20 min` по `_run_deep|deep_sleep|deep_after|_mmr_select|mmr_budget|select_historical`
→ **0** совпадений; `loop_lag` за 20 мин → 0 строк; состояние `pre_migration…db`
не трогалось. Фактический `systemctl restart`: **2 секунды** (без ожидания потока MMR,
`-9` не понадобился, `TimeoutStopSec` не достигнут).

## Product SHA на проде (байтовая идентичность)

```
git rev-parse HEAD:services/summary_memory.py                     2fdb657c1f35d34076b6f87a4fd5f1f9a3a636fd  (= candidate)
git rev-parse HEAD:tests/p0_dream_loop/test_no_event_loop_block.py 391772ed50efec97d5fe65828dc1bf17b43d76a7 (= candidate)
sha256 services/summary_memory.py      e93a4aac299051c5183050f31b34aea03fb02dc777312e98bea1d4c476985485
sha256 tests/p0_dream_loop/test_no_event_loop_block.py d209eb3e1054b938fa6eab63b19f45906e4c786e5ce517fc2ad612cfeabab4b2
```

Оба sha256 совпадают с локальными значениями сборки (`assembly.md` §0/§7).

## Схема и сохранённые настройки

| Metric | Before (06:03Z) | After (06:09Z) |
|---|---|---|
| `local_database.db` `user_version` | **50** | **50** (не изменилась) |
| `quick_check` | ok | ok |
| `bot_settings` rows | 558 | **558** |
| md5 всех строк (key=value, sort by key) | `50887d362fe93bf7646beae77cce32c6` | **`50887d362fe93bf7646beae77cce32c6`** |
| `max(updated_at)` | `2026-11-27 21:48:55.892740+00` | **то же** |
| `category='prompts'` | 29 | **29** |

DDL Δ=0, миграции не запускались. `pre_migration_20261128_040748.db` — остаточный
бэкап миграции 2.58.269 (v49), к живому файлу отношения не имеет; входит в пул
`deploy_backup`/retention, не удалялся.

## Routes pin / bundle

`sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a`.
`web/app.js` на диске `3631e82de2a8…` (2 739 459 B) = **отданный** `/web/app.js`
(тот же sha256 и размер).

## Отзывчивость (инцидентный симптом)

| Момент | local `/healthz` | public `/healthz` |
|---|---|---|
| T+6 s (06:09:37Z) | **200**, 0.230 s | **200**, 0.046 s |
| T+8.3 min (06:17:51Z) | **200**, 0.0013 s | **200**, 0.070 s |
| T+12.4 min (06:21:55Z) | **200**, 0.0055 s | **200**, 0.090 s |
| T+12.7 min (06:22:14Z) | **200**, 0.0013 s | **200**, 0.086 s |

`loop_lag` в журнале за окно — **1 строка**, только старт watchdog
(`watchdog started | warn_s=5.000 tick_s=1.000`); значений `lag_ms` нет вообще.
`mmr_budget_exhausted` — **0**.

## Журнал (окно 06:09:31 → 06:21:55Z, 12.4 min)

`window_lines=905`, `errors=2`, `tracebacks=0`, `http5xx=0`, `loop_lag_lines=1`.

Оба `ERROR` — pre-existing `services.anticliche_worker`
(`step=fetch`/`step=refresh`, `status=error`), тот же паттерн, что в evidence
2.58.263/2.58.264, к дельте отношения нет. Ошибок `to_thread`/`executor`/`mmr` — **0**.
Глубокий проход в окне не запускался: `DeepSleep`/`DreamWorker` только
зарегистрированы (`tick_minutes=60`, enabled per-tick); `[deep_sleep_migration] skip`
— это конфигурационная миграция, не прогон.

## Откат

Dry-run (временный detached worktree `6d97c02d8` + копия текущего манифеста),
`tools/release_manifest.py --effect rollback --dry-run` → **rc=0**:

```json
{ "deployed_at": "2026-11-28T06:17:55.511148Z", "deployed_sha": "6d97c02d8a4830c5824cc9c39db311373f953b6d",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "438ad790eb998d1af6d6731be4392ea1d6179b4e",
  "previous_version": "2.58.270", "schema": 1, "version": "2.58.269" }
```

DDL Δ=0 ⇒ откат **code-only** (`git checkout --detach 6d97c02d8` + restart), схема
остаётся v50. Temp-worktree удалён без `--force`, `worktree prune` выполнен,
`git worktree list` = только основной checkout.

## Диск

`df -h /`: 99G total / 51G used / **44G avail (54%)** — до и после.
`manage.py disk audit`: forecast `bytes_per_day=1586016858`,
`projected_30d=47580505763 (44.3 GiB)`, top — `predeploy-258234-pg-…dump` 107 847 B.
`disk cleanup --apply` (deploy-пул keep=2): `deleted=0 bytes_freed=0 skipped=0 errors=0`.
Пригодных deploy-бэкапов — **2** (`predeploy-258258-…db`, `predeploy-258257-…db`),
полная копия БД в этом релизе не создавалась (DDL 0).

## Live-smoke

Тестовые сообщения в рабочие чаты **не отправлялись**. Проверено: три источника версии,
`/healthz` локально и публично (4 замера), отданный `app.js` == диску, `IMPORT_OK`,
`user_version`, `bot_settings`, журнал, unit-состояние, манифест.

## Честные ограничения

- Реальный ночной глубокий проход (`DeepSleep`) в окне деплоя не выполнялся: очередь
  тикает раз в 60 минут и глубокий проход включается по расписанию/условиям. Значит,
  off-loop путь на проде пока подтверждён косвенно: код загружен (`offloop=True`,
  `budget_s=5.0`), unit-тесты и независимый probe ревью; первый реальный ночной
  проход — естественная проверка следующего окна (без искусственного прогона и без
  записи в пользовательские данные).
- Первый комбинированный тестовый прогон на сборке завис на teardown Windows-фикстуры
  (`tests/test_summary_memory.py:39`, proactor loop), 4 повторных прогона — 132 passed;
  см. `assembly.md` §5. Это артефакт окружения, не прод.

## Artefacts

`raw/deploy-recon.txt`, `raw/deploy-run.txt`, `raw/post-window-run.txt`,
`raw/final-check.txt`, `.deploy/release.json` (перезаписан на проде).
Временные файлы на проде (`/tmp/ab270_changed.txt`, `/tmp/rb270`, `/tmp/oc_*`) удалены,
`ls /tmp` — чисто. Release-worktree остаётся до закрытия очереди.
