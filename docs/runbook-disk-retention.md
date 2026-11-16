# Runbook: retention диска (F9, ADR-1024-2)

Применяется @DevOps на сервере. Секретов в файле нет (R17).

## Политика (владелец, UPD3 №5)

- Бэкапы БД (`local_database_*.db` + `memory_rebuild_*.db`) — **ровно 1**
  новейший. Хранить 3+ запрещено.
- Деплой-копии (`pre_deploy_*.db`, legacy `predeploy-*.db`, старые
  `pre_t*.db`) — **2 новейших** (rollback-readiness). Ротируются и CLI
  `disk cleanup`, и ежедневным `memory_backup._rotate`.
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
`db_backup` (keep 1), `deploy_backup` (keep 2), `facts_export` (keep 1),
`jsonl_retention` (>180 дней). Живая `local_database.db` и её `-wal`/`-shm`
не матчатся ни одним паттерном и не удаляются; `pre_migration_*.db`
ротируется только call-site миграции (keep 1).

## После каждого деплоя (обязательный шаг харнесса)

1. Деплой-харнесс после успешного healthz/version вызывает
   `python manage.py disk cleanup --apply` (существующий `deploy_v2.9.2.py`
   и шаблон `tools/_dep*.py`, шаг J).
2. Временные staging-копии `/tmp/predeploy-*.db`, `/tmp/pre_deploy_*.db`,
   `/tmp/pre_t*.db` удаляются в `finally` — они не должны переживать прогон.
3. Ошибка очистки не отменяет успешный деплой, но фиксируется в отчёте.

Если деплой прошёл мимо харнесса — ежедневный бэкап всё равно подрежет
деплой-пул до 2 новейших.

## Хвосты, которые нельзя оставлять на проде

- `/root/deploy-*`, `/root/vmq*` — временные деплой/исследовательские
  каталоги: держать вне прода либо удалять сразу по завершении (они не
  входят в автоматические паттерны retention).
- `/tmp/predeploy-*`, `/tmp/pre_deploy_*`, `/tmp/pre_t*` — staging-копии
  БД: удаляются харнессом; вручную — `rm -f` по этим трём маскам только
  после проверки, что копия уже перенесена в `backups/`.
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
