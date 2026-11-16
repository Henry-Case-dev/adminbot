# Runbook: retention диска (F9, ADR-1024-2)

Применяется @DevOps на сервере. Секретов в файле нет (R17).

## Политика (владелец, UPD3 №5)

- Бэкапы БД (`local_database_*.db` + `memory_rebuild_*.db`) — **ровно 1**
  новейший. Хранить 3+ запрещено.
- Деплой-копии (`pre_deploy_*.db`, legacy `predeploy-*.db`, старые
  `pre_t*.db`) — **2 новейших** (rollback-readiness). Ротируются и CLI
  `disk cleanup`, и ежедневным `memory_backup._rotate`; WAL/SHM-компаньоны
  уходят вместе со своей копией.
- `imported_history_*.jsonl` и любые архивы истории сообщений —
  **неприкосновенны** (бессрочно).
- Прочие не-history JSONL — окно **180 дней**.
- Логи journald — **7 дней**, `SystemMaxUse=500M`.

## Аудит и очистка (код)

```bash
cd /var/www/admin_bot && source venv/bin/activate
python manage.py disk audit              # read-only снимок
python manage.py disk cleanup            # dry-run (ничего не удаляет)
python manage.py disk cleanup --apply    # удаление; verify свежего бэкапа
```

`--dir <path>` (можно несколько раз) переопределяет каталог; без флага
берётся `reactions.memory_backup_dir` (hot-config) → `MEMORY_BACKUP_DIR`
(по умолчанию `backups/` — там же лежат деплой-копии).

План `cleanup` включает:
`db_backup` (keep 1), `deploy_backup` (keep 2, `reason=deploy_keep_newest_2`),
`facts_export` (keep 1), `jsonl_retention` (>180 дней). Живая
`local_database.db` и её `-wal`/`-shm` не матчатся ни одним паттерном и не
удаляются; `pre_migration_*.db` ротируется только call-site миграции (keep 1).

Первопричина инцидента 16.11.2026: в паттерне был только `pre_t*.db`, поэтому
фактические имена деплой-копий (`pre_deploy_*`, `predeploy-*`) не ротировались
никогда — 17 копий (44G) накопились за 4 дня, диск дошёл до 94%. Копии лежали
вместе с `*.db-wal`/`*.db-shm`, которые тоже не попадали ни в один паттерн:
`apply_cleanup` удаляет компаньоны строго вместе со своей копией (точные имена
`<copy>.db-wal`/`<copy>.db-shm`, без масок). `apply_cleanup` дополнительно
исполняет `prune_deploy_backups(keep=2)` сам — частично поданный план не
отменяет политику; при fail-closed отказе (нет свежего daily/safety-бэкапа)
не удаляется ничего, включая деплой-копии.

## После каждого деплоя (обязательный шаг)

Реальный production-деплой этой линии — **ручной SSH** на `192.255.209.205`
(`root`, каталог `/var/www/admin_bot`): `git pull --ff-only` →
`systemctl restart admin_bot` → проверка healthz/version. Сразу после этого
выполняется retention-шаг:

1. `python manage.py disk audit` — read-only снимок: категория
   `deploy_backup`, размеры и свободное место;
2. `python manage.py disk cleanup --apply` — исполняет план и deploy-пул
   (keep=2); fail-closed verify свежего daily/safety-бэкапа сохраняется —
   без него не удаляется ничего;
3. staging-копии `/tmp/predeploy-*.db`, `/tmp/pre_deploy_*.db`,
   `/tmp/pre_t*.db` удаляются сразу после переноса в `backups/` — они не
   должны переживать прогон.

`deploy_v2.9.2.py` — **исторический** деплой-харнесс (старый хост
`198.46.175.136`/`nik`); это НЕ production-маршрут 2.58.205, и полагаться на
его автоочистку нельзя. Если шаг `disk cleanup --apply` пропущен, ежедневный
`memory_backup._rotate` всё равно подрежет деплой-пул до 2 новейших
автоматически — это страховка, а не замена обязательного шага.

## Хвосты, которые нельзя оставлять на проде

- `/root/deploy-*`, `/root/vmq*` — временные деплой/исследовательские
  каталоги: держать вне прода либо удалять сразу по завершении (они не
  входят в автоматические паттерны retention).
- `/tmp/predeploy-*`, `/tmp/pre_deploy_*`, `/tmp/pre_t*` — staging-копии
  БД: после переноса в `backups/` удаляются сразу; вручную — `rm -f` по этим
  трём маскам только после проверки, что копия уже перенесена.
- Исследовательские корпуса/выгрузки и полные копии БД — не хранить на
  production; тяжёлые прогоны выполнять вне сервера (P0-PROD-DISK-01).

## Логи journald — 7 дней (применяет @DevOps)

Файл `/etc/systemd/journald.conf.d/retention.conf`:

```ini
[Journal]
MaxRetentionSec=7d
SystemMaxUse=500M
```

Применение:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/retention.conf >/dev/null <<'EOF'
[Journal]
MaxRetentionSec=7d
SystemMaxUse=500M
EOF
sudo systemctl restart systemd-journald
journalctl --disk-usage
```

## Откат

- Retention — вернуть прежние значения env / `DISK_RETENTION_ENABLED=false`.
- Удалённые бэкапы/JSONL восстановимы только из внешних бэкапов — поэтому
  `--apply` идёт с fail-closed verify (`services/disk_retention.py`).
