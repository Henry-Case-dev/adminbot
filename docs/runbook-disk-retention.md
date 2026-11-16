# Runbook: retention диска (F9, ADR-1024-2)

Применяется @DevOps на сервере. Секретов в файле нет (R17).

## Политика (владелец, UPD3 №5)

- Бэкапы БД (`local_database_*.db` + `memory_rebuild_*.db`) — **ровно 1**
  новейший. Хранить 3+ запрещено.
- Деплой-бэкапы (`pre_deploy_<ver>_<ts>.db`, `predeploy-<ver>*.db`,
  `pre_t<ticket>_*.db`) — **2 новейших** (текущий rollback + предыдущий);
  их пишет деплой-тулинг в каталог бэкапов приложения.
- `imported_history_*.jsonl` и любые архивы истории сообщений —
  **неприкосновенны** (бессрочно).
- Прочие не-history JSONL — окно **180 дней**.
- Логи journald — **7 дней**.

## Аудит и очистка (код)

```bash
cd /var/www/admin_bot && source venv/bin/activate
python manage.py disk audit              # read-only снимок
python manage.py disk cleanup            # dry-run (ничего не удаляет)
python manage.py disk cleanup --apply    # удаление; verify свежего бэкапа
```

`--dir <path>` (можно несколько раз) переопределяет каталог; без флага
берётся `reactions.memory_backup_dir` (hot-config) → `MEMORY_BACKUP_DIR`.

Пул деплой-бэкапов виден в аудите отдельной категорией `deploy_backup` и в
плане очистки (`reason=deploy_keep_newest_2`); `apply_cleanup` дополнительно
исполняет `prune_deploy_backups(keep=2)` и удаляет WAL/SHM-компаньоны
снесённых копий. Живая БД `local_database.db` (+ её `-wal`/`-shm`) не
совпадает ни с одним паттерном и не трогается.

## После успешного деплоя/приёмки — обязательный шаг

Деплой пишет полную копию БД (`pre_deploy_*`/`predeploy-*`, 1.8–3.0G за релиз)
в каталог бэкапов, поэтому после каждого релиза:

```bash
cd /var/www/admin_bot && source venv/bin/activate
python manage.py disk audit              # в категориях виден deploy_backup
python manage.py disk cleanup --apply    # сохраняет 2 новейших deploy-копии
ls -1t backups/*.db | head -5            # текущий + предыдущий rollback
```

Сохраняются **2 новейших** деплой-копии (текущий rollback + предыдущий
релиз), daily-бэкап (`local_database_*`, ровно 1), `pre_migration_*` (ровно 1
в своём пуле) и вся история сообщений. Ежедневный джоб
`memory_backup._rotate` исполняет ту же политику автоматически — отдельный
таймер для деплой-копий не нужен. Ручное удаление — только по точным путям,
без `rm -rf`.

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
