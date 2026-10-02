# Deployment: сервер-sайд retention/cleanup диска (T-4506 → T-4507)

Feature: `post-asap4-corrective-pass` · Задача: **T-4506 [@Builder]** (реализация + тесты) →
**T-4507 [@DevOps]** (установка на прод + первая чистка по disk-audit §9).
Скрипт: `tools/disk_retention.py` (только stdlib, без импорта приложения).
Тесты: `tests/test_disk_retention_server_t4506.py` (45+1).
Секретов в файле нет (R17). Хост: `racknerd-f4e3456` (198.46.175.136), Ubuntu.

## 1. Что это и что НЕ трогает

Скрипт чистит ТОЛЬКО whitelist-классы из disk-audit §9
(`plans/features/post-asap4-corrective-pass/disk-audit.md`), файл-за-файлом.
Внутри скрипта HARDCODE denylist — сильнее whitelist, никогда не трогается
(даже если файл лежит в whitelist-каталоге):

| Защищено всегда | Как |
|---|---|
| Рабочая БД + WAL/shm (`local_database.db*`) | точные имена |
| Суточный авто-бэкап и любые именованные копии (`local_database_2*.db`) | glob |
| `pre_migration_20261002_101544.db` и любые `pre_migration_*.db` | glob |
| Версионные якоря (`*pre_v*` — pre_v21 и будущие pre_vNN) | маркер |
| `.env*` (секреты), `*cookie*` | glob/маркер |
| История сообщений (`*history*` — бессрочно, UPD3 №5) | маркер |
| `media/`, `uploads/`, память/GraphRAG (`graphrag|chroma|lancedb|embeddings|memory`) | сегменты пути |
| `venv/`, `.git/`, браузерный профиль (`chrome-profile*`) | сегменты пути |

`migrate_history/` — **conditional**: по умолчанию исключён; только с явным
`--with-owner-confirm` (после off-site архива; и всё равно только файлы старше
7 дней). Никаких `rm -rf` по широким путям: только `unlink` отдельных файлов
из вычисленного плана, с повторной проверкой каждого пути перед удалением и
логом построчно. Каталоги не удаляются.

Kill-switch: `ADMINBOT_DISK_RETENTION_ENABLED=0` → полный no-op (default ON).
Dry-run — режим по умолчанию; реальное удаление — только `--apply`.

## 2. Классы очистки (правила из аудита)

| Класс | Корни | Правило | Аудит-диспозиция |
|---|---|---|---|
| `db_anchor_backups` | `/home/nik/backups`, `/home/nik/backups_adminbot` (+ `/var/www/admin_bot` read-only для ранжирования) | keep 2 новейших по всем местам якорей + текущий месяц | `pre_mca_v19` (0.79G) удаляется; `pre_v21`, `pre_migration`, daily — защищены всегда |
| `app_adhoc_db_baks` | `/var/www/admin_bot` (корень) | `local_database.db.bak.*` старше 14 дней | `local_database.db.bak.2026-09-15-0744` (0.71G) |
| `playwright_artifacts` | `/var/www/admin_bot/.playwright-mcp` | всё старше 7 дней | screenshot/traces/videos |
| `pytest_tmp` | `/tmp/pytest-of-nik` | всё старше 3 дней | 88M |
| `pytest_tmp_files` | `/tmp` (не рекурсивно) | `adminbot_test_*` старше 3 дней | темп-файлы тестов |
| `rotated_logs` | `/opt/headroom/home/.headroom/logs` | `proxy.log.N[.gz]` старше 14 дней | 50M; активный `proxy.log` не совпадает с паттерном |
| `migrate_history` | `/var/www/admin_bot/migrate_history` | старше 7 дней, только `--with-owner-confirm` | 1.01G (после off-site архива) |

## 3. Установка на прод (@DevOps, T-4507)

Код доставляется git-ом (`tools/disk_retention.py` уже в репо после мерджа).
Юниты systemd создаются на месте (в репо не хранятся — host-specific):

```bash
# 3.1 Юнит-сервис (dry-run по умолчанию внутри скрипта; таймер гоняет dry-run,
#     реальная чистка — ручной --apply по процедуре §4)
sudo tee /etc/systemd/system/adminbot-disk-retention.service >/dev/null <<'EOF'
[Unit]
Description=adminbot disk retention (T-4506, whitelist-only, dry-run)
After=network.target

[Service]
Type=oneshot
User=nik
WorkingDirectory=/var/www/admin_bot
ExecStart=/var/www/admin_bot/venv/bin/python tools/disk_retention.py
# Kill-switch (раскомментировать для полного no-op):
# Environment=ADMINBOT_DISK_RETENTION_ENABLED=0
EOF

# 3.2 Еженедельный таймер (понедельник 06:30, догоняет пропущенный запуск)
sudo tee /etc/systemd/system/adminbot-disk-retention.timer >/dev/null <<'EOF'
[Unit]
Description=weekly adminbot disk retention dry-run

[Timer]
OnCalendar=Mon *-*-* 06:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now adminbot-disk-retention.timer
systemctl list-timers adminbot-disk-retention.timer
```

Альтернатива без systemd (cron, от nik): `crontab -e` →
`30 6 * * 1 cd /var/www/admin_bot && venv/bin/python tools/disk_retention.py >> /var/log/adminbot-disk-retention.log 2>&1`

### logrotate (ротированные логи headroom)

Ротация уже есть (proxy.log.1–5); дать logrotate сжимать и ограничить число
копий (старше 14 дней досчищает сам `tools/disk_retention.py`):

```bash
sudo tee /etc/logrotate.d/headroom >/dev/null <<'EOF'
/opt/headroom/home/.headroom/logs/proxy.log {
    weekly
    rotate 5
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

journald уже ограничен (SystemMaxUse=200M, audit §8) — менять не нужно;
опционально разово: `sudo journalctl --vacuum-size=100M` (+~0.09G).

## 4. Первая чистка (T-4507) — процедура

```bash
cd /var/www/admin_bot && git pull --ff-only   # после мерджа pass'а
source venv/bin/activate

# 4.1 Dry-run: план с размерами, НИЧЕГО не удаляется
python tools/disk_retention.py                 # текстовый отчёт
python tools/disk_retention.py --json > /tmp/disk-retention-plan.json

# 4.2 Сверить план с disk-audit §9 (каждый путь ∈ whitelist-классам)
df -h | grep -E 'Filesystem|/dev/vda2'         # df ДО

# 4.3 Применить (по-файлу, с построчным логом)
python tools/disk_retention.py --apply 2>&1 | tee /tmp/disk-retention-apply.log

# 4.4 df ПОСЛЕ + зафиксировать «освобождено X GB» в evidence
df -h | grep -E 'Filesystem|/dev/vda2'

# 4.5 Checklist защиты (R5-B-003): рабочая БД/WAL, pre_migration_20261002_101544.db,
#     pre_v21, суточный backups/local_database_20261002.db, media/, .env — целы
ls -lh local_database.db* pre_migration_20261002_101544.db backups/ | head
```

Одноразовые позиции аудита вне правил автоматики (по явным путям §9, guarded-команды
DevOps; скрипт их не покрывает сознательно):

- `apt-get clean` (безопасно; либо `python tools/disk_retention.py --apply --with-apt` —
  выполняет ТОЛЬКО `apt-get clean` без shell);
- `rm -rf /var/lib/apt/lists/*` — ТОЛЬКО вручную (широкая маска; списки
  регенерируются при первом `apt update`), ~0.30G;
- часть `proxy.log.[1-5]` моложе 14 дней на момент чистки — по явным путям
  аудита либо дождаться автоматики (~неделя);
- `migrate_history/` (1.01G): сначала off-site архив → затем
  `python tools/disk_retention.py --apply --with-owner-confirm`
  (удалит файлы старше 7 дней).

Ожидание (audit §9): занято 18G → ~16.1G (−1.9G); с migrate_history — до ~15.1G.

## 5. Откат / отключение

- Полный no-op: `sudo systemctl edit adminbot-disk-retention.service` →
  `Environment=ADMINBOT_DISK_RETENTION_ENABLED=0` (или закомментировать строку
  в юните) → `sudo systemctl restart adminbot-disk-retention.service`;
- Снять с автозапуска: `sudo systemctl disable --now adminbot-disk-retention.timer`;
- Скрипт без `--apply` ничего не удаляет — dry-run безопасен всегда.
