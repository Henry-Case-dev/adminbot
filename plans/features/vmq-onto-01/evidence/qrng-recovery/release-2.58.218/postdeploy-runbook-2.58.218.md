# Post-deploy runbook — 2.58.218 (QRNG-RECOVERY-01 / F-01)

**Статус:** только процедура для DevOps после отдельного разрешённого деплоя.
В этой сборке деплой не выполнялся, production не затрагивался.
**Откат:** `f68e7631d` (2.58.217); схема может остаться 48 — две nullable-колонки
`mca_random_batches.config_fingerprint/external_ref` инертны для старого кода.

## 0. Предусловия (до рестарта)

1. `git -C /var/www/admin_bot status --porcelain --untracked-files=no` пуст;
   `git rev-parse HEAD` = выкладываемый SHA (ветка `release/qrng-f01-2.58.218`).
2. Свободное место проверено: `python manage.py disk audit` (не начинать при
   недостатке места). Штатный deploy-бэкап создаётся существующим workflow
   (пул `deploy_backup keep=2`), отдельная копия БД вручную не нужна.
3. `python tools/release_manifest.py` пишет `.deploy/release.json` на фактическом
   checkout **до** рестарта; в манифесте `version=2.58.218`,
   `previous_sha=f68e7631d`, `dirty_tracked=false`.
4. `sudo systemctl restart admin_bot`.

## 1. Health / identity / schema / disk

| Проверка | Ожидание |
|---|---|
| `curl -fsS https://<host>/healthz` | HTTP 200 |
| версия в UI/`/api/status` | `2.58.218` |
| `git -C /var/www/admin_bot rev-parse HEAD` | равен `release.json.deployed_sha` |
| `release.json` | `version=2.58.218`, `previous_sha=f68e7631d`, `dirty_tracked=false` |
| схема | `PRAGMA user_version` = **48**; обе колонки `config_fingerprint`, `external_ref` есть; pending-шагов нет |
| `python manage.py disk audit` | свободное место в норме |
| `python manage.py disk cleanup --apply` | deploy-пул keep=2, без удаления активных данных |
| журнал запуска | нет новых `random_activation` `failed`/`unknown`, нет ERROR миграций |

Схема не менялась этим релизом: DDL 0, новых миграций нет.

## 2. Безопасная read-only проверка F-01 (без расхода партий)

Синтетическая проверка (уже выполнена при сборке, безопасна и не требует
production-данных):

```
python -m pytest tests/test_qrng_f01_activation_batch_scope.py -q --tb=short
```

Ожидание: **4 passed**. Использует temp SQLite и инжектированный HTTP; реальные
ANU/LfDR-ключи и платные задания не нужны.

Если нужна проверка на копии production-БД (только read-only, копию удалить после):

1. Снять компактную копию БД на время проверки (или открыть production-БД
   строго read-only) — без записи, без вызова `activate()`.
2. Сравнить последнюю активацию с журналом:

```sql
SELECT key_fingerprint, activation_batch_id, activated_at
FROM mca_random_state
ORDER BY activated_at DESC LIMIT 1;

SELECT draw_id, created_at, purpose, source, provider, batch_id, value
FROM mca_random_draws
WHERE purpose = 'activation_selfcheck'
ORDER BY created_at DESC, draw_id DESC LIMIT 1;
```

Ожидание: `mca_random_state.activation_batch_id = mca_random_draws.batch_id`,
`source = quantum`, `provider` соответствует партии. Это и есть инвариант F-01:
state/журнал называют фактически израсходованную партию.

3. Убедиться, что у партии из журнала `consumed_upto >= 1`, а у более старой
   LfDR/NULL-партии нет скачка `consumed_upto` в тот же момент:

```sql
SELECT batch_id, provider, config_fingerprint, length, reserved_upto,
       consumed_upto, created_at
FROM mca_random_batches
WHERE batch_id = '<activation_batch_id>';
```

Любая запись в production-БД запрещена; копию БД удалить сразу после проверки.

## 3. Живая активация — только по факту реального сохранения ключа

- Если в ходе обычной эксплуатации global admin реально сохраняет/проверяет
  ANU-ключ и происходит активация — выполнить SQL из §2 и зафиксировать
  `activation_batch_id == journal batch_id`, `provider = anu`.
- Если реальной активации не было — честно записать `live_activation:
  not_checked`; **не** инициировать активацию/проверку ключа искусственно ради
  проверки (это тратит квоту провайдера).
- IBM paid jobs и платные запросы не запускать. LfDR/ANU live-проверки не
  обязательны для приёмки этого фикса.

## 4. Откат (при проблеме)

```
git -C /var/www/admin_bot checkout f68e7631d
python tools/release_manifest.py --effect rollback
sudo systemctl restart admin_bot
```

Проверить `/healthz`, версию `2.58.217`, identity (`HEAD=f68e7631d`).
Схема остаётся 48; данные не откатываются, DDL/DROP не выполнять.
