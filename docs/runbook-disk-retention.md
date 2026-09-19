# Runbook: retention диска (F9, ADR-1024-2)

Применяется @DevOps на сервере. Секретов в файле нет (R17).

## Политика (владелец, UPD3 №5)

- Бэкапы БД (`local_database_*.db` + `memory_rebuild_*.db`) — **ровно 1**
  новейший. Хранить 3+ запрещено.
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
