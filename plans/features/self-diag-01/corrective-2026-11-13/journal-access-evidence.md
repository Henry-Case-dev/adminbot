# SELF-DIAG-01 corrective §2 — восстановление чтения systemd journal сервисным пользователем

**Дата:** 2026-11-13, окно 04:12:07Z–04:17:40Z (UTC сервера).
**Среда:** PRODUCTION VPS `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`.
**Скоуп:** только окружение/права. Код не менялся, деплой кода не выполнялся.
**Состояние до и после:** `HEAD=234776589c934024ed0e8dceba189fb9d70d3215`, ветка `release/2.58.198`,
`APP_VERSION = "2.58.198"`, `/healthz` → `{"status":"ok","version":"2.58.198"}`.

**Итог: ВОССТАНОВЛЕНО.** Причина — не sandbox, а отсутствие сервисного пользователя в группе
`systemd-journal` (файлы журнала `0640 root:systemd-journal`). Добавление в группу + рестарт:
`journalctl` под `adminbot` теперь rc=0, включая `journalctl -u admin_bot` (собственный журнал
сервиса) и точную командную форму бота; после рестарта 0 traceback / 0 ERROR / 0 `attempt LOST`.

---

## 1. Effective unit (redacted)

`systemctl cat admin_bot` (значения `Environment*` замаскированы; показаны только имена переменных):

```
# /etc/systemd/system/admin_bot.service
[Unit]
Description=Telegram Admin Bot
After=network.target

[Service]
Type=simple
User=adminbot
WorkingDirectory=/var/www/admin_bot
EnvironmentFile=/var/www/admin_bot/.env
ExecStart=/var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/admin_bot.service.d/override.conf
[Service]
TimeoutStopSec=60
```

`systemctl show` (ключевые свойства):

```
User=adminbot
Group=
SupplementaryGroups=
DynamicUser=no
PrivateTmp=no
PrivateDevices=no
ProtectSystem=no
ProtectHome=no
NoNewPrivileges=no
ReadOnlyPaths=
InaccessiblePaths=
SystemCallFilter=~
RestrictAddressFamilies=~
AmbientCapabilities=
EnvironmentFiles=/var/www/admin_bot/.env (ignore_errors=no)
FragmentPath=/etc/systemd/system/admin_bot.service
```

Файлы unit'а не менялись: sha256 до и после фикса идентичны —
`f4780ebc5122…a60cf5` (`admin_bot.service`), `fb6761975c40…0fba734` (`override.conf`).

## 2. Диагностика (read-only)

`id adminbot` → `uid=999(adminbot) gid=987(adminbot) groups=987(adminbot)` — до фикса.
`getent group systemd-journal` → `systemd-journal:x:999:` (без участников).
`getent group adm` → `adm:x:4:syslog`.

Журнал и права:

```
systemd 255 (255.4-1ubuntu8)
drwxr-sr-x+ 2 root systemd-journal   40 Nov 11 19:46 /run/log/journal
drwxr-sr-x+ 3 root systemd-journal 4096 Apr 26  2024 /var/log/journal
drwxr-sr-x+ 2 root systemd-journal 4096 /var/log/journal/3f8498c7…ce23
-rw-r-----+ 1 root systemd-journal 100663296 … system@e043913b…-00000000000cdd86-….journal
```

ACL каталога (`getfacl`): `group::r-x`, `group:adm:r-x`, `other::r-x` (каталог листается),
файлы `0640 root:systemd-journal` — читаются только root, члены `systemd-journal` и `adm` (ACL).

Корневое чтение работает: `journalctl -n 5 --no-pager` → rc=0 (в выводе — свежие записи хоста).

### Точное воспроизведение отказа (сервисный пользователь, пустое окружение)

```
runuser -u adminbot -- env -i PATH=/usr/bin:/bin journalctl -n 5 --no-pager
```

вывод (stderr):

```
Hint: You are currently not seeing messages from other users and the system.
      Users in groups 'adm', 'systemd-journal' can see all messages.
      Pass -q to turn off this notice.
No journal files were opened due to insufficient permissions.
```

`rc=1` — ровно owner-симптом.

`journalctl -u admin_bot -n 300 --no-pager` под сервисным пользователем до фикса: `rc=1`, 0 строк,
тот же `insufficient permissions`.

## 3. Причина (установлена, не предположение)

Отказ вызван **групповыми правами доступа к файлам журнала**, а не sandbox:

- в unit'е вообще нет sandbox-директив (`ProtectSystem=no`, `ProtectHome=no`, `PrivateTmp=no`,
  `ReadOnlyPaths=`, `InaccessiblePaths=`, `SystemCallFilter=~`, `NoNewPrivileges=no`) — journald
  не скрыт от процесса;
- каталог журнала доступен на чтение (`other::r-x`), поэтому листинг проходил
  (`service_user CAN list journal dir`), но сами `system.journal` — `0640 root:systemd-journal`,
  и `adminbot` не состоял ни в `systemd-journal`, ни в `adm`
  (`service_user CANNOT read system.journal`);
- отсюда `rc=1` + «No journal files were opened due to insufficient permissions».

## 4. Фикс (штатный механизм, минимум прав)

```
usermod -aG systemd-journal adminbot        # rc=0
systemctl restart admin_bot                 # rc=0
```

- `id adminbot` после: `uid=999(adminbot) gid=987(adminbot) groups=987(adminbot),999(systemd-journal)`
- `getent group systemd-journal` → `systemd-journal:x:999:adminbot`
- `stat /etc/group` → mtime `2026-11-13 04:13:14Z` (изменение сохранено на диске)
- Группа `adm` **не** добавлялась: журнал принадлежит `systemd-journal`, fallback через `/var/log`
  не требуется.
- Бот не запускается под root; sudo не выдавался; sandbox не отключался (он и не был включён);
  внешние сборщики логов не устанавливались.

Фактическая принадлежность группы у **работающего** процесса (не только в `/etc/group`):

```
MainPID=401081
Groups: 987 999
→ adminbot:987, systemd-journal:999
```

## 5. Верификация под сервисным пользователем (после рестарта)

Рестарт: `2026-11-13 04:13:15Z`, `InvocationID=aff04b3e6e044d4f84abc03a357ea00f`, `NRestarts=0`,
`ActiveState=active`, `MainPID=401081`.

| Проверка (как `adminbot`, `env -i PATH=/usr/bin:/bin`) | Результат |
|---|---|
| `journalctl -n 5 --no-pager` | **rc=0**, stderr пуст, в выводе свежие записи текущего запуска (`python[401081]` 04:13:19Z) |
| `journalctl -u admin_bot -n 50 --no-pager` | **rc=0**, 50 строк, stderr пуст |
| `journalctl -u admin_bot -n 50 -o json` | 50/50 записей с `_SYSTEMD_INVOCATION_ID=aff04b3e…ea00f` (текущий invocation) |
| `journalctl -u admin_bot -n 300 --no-pager` (точная форма `CHECKUP_JOURNALCTL_CMD`) | **rc=0**, 300 строк, stderr 0 байт |
| повтор на 04:17:40Z: `journalctl -n 3` / `-u admin_bot -n 3` | rc=0 / rc=0, stderr пуст, записи текущего invocation |

`/healthz`: `{"status":"ok","version":"2.58.198"}` (localhost 04:13:16Z, 04:13:39Z, 04:17:40Z;
публично `https://admin-bot.duckdns.org/healthz` → 200, 2.58.198, ≈04:15Z).

**Рост ошибок после фикса:** окно `04:13:15Z–04:17:40Z` (4 мин 25 с, 314 строк журнала) —
`traceback=0`, `ERROR=0`, `CRITICAL=0`, `attempt LOST=0`, `insufficient permissions=0`.
Две traceback-записи, попавшие в 6-минутное окно основного прогона, датированы **до** рестарта
(`04:10:48Z`, `04:10:57Z`, `LLMBadResponseError`/`TimeoutError`) — к journal-правам не относятся;
после рестарта новых нет. `NRestarts=0`, сервис стабилен.

## 6. Кодовый путь, который читает журнал (не менялся)

Health/API-эндпоинта, который отчитывается о чтении журнала, нет (`/healthz` отдаёт только
`status`/`version`). Чтение выполняет существующий чек-ап:

- `config/settings.py:2151` — `CHECKUP_JOURNALCTL_CMD = "journalctl -u admin_bot -n 300 --no-pager"`;
- `bot.py:571` — передаёт настройку в чек-ап;
- `services/system_logs_fetcher.py:94–111` — каскад: SQL API → journalctl;
- `services/system_logs_fetcher.py:198–238` — `_fetch_journalctl()`: `asyncio.create_subprocess_shell`,
  `rc != 0` → `CheckupLogsUnavailableException` (DEAD + `stderr_tail` в лог), `rc == 0` → фильтр
  `error|warning|traceback`, последние 300 строк.

Что путь реально исполняется в production: до фикса в журнале сервиса за 24 ч была ровно 1 запись
с `insufficient permissions` — это `stderr_tail` из `_fetch_journalctl`, т.е. journal-ступень
достигалась и падала. После фикса та же команда под сервисным пользователем даёт rc=0, поэтому
ступень больше не блокируется правами. Сквозной чек-ап через Telegram/LLM в этом прогоне не
запускался (LLM-сценарий «A» — зона Builder).

## 7. Персистентность при рестарте и деплое

- Членство в группе хранится в `/etc/group` — переживает `systemctl restart admin_bot`,
  перезагрузку и штатный деплой.
- Штатный деплой проекта: `git pull --ff-only` + `systemctl restart admin_bot`; unit в репозитории
  отсутствует (`*.service` в репозитории нет), деплой-скрипты группу не трогают, unit-файл не
  перезаписывают — правки, которые могли бы откатить фикс, не найдены. Hash unit'а после фикса
  совпадает с исходным, поэтому никакого restore не требуется.
- Ограничение: при полной переустановке/пересборке VPS членство нужно выставить заново
  (`usermod -aG systemd-journal adminbot` + рестарт) — это шаг provisioning, не деплоя кода.

## 8. Откат

```
gpasswd -d adminbot systemd-journal
systemctl restart admin_bot
# unit не менялся; при гипотетическом изменении фрагмента:
#   restore /etc/systemd/system/admin_bot.service[.d/override.conf] → systemctl daemon-reload
systemctl is-active admin_bot && curl -fsS http://127.0.0.1:8000/healthz
```

## 9. Остаточные ограничения (честно)

1. Членство в `systemd-journal` даёт чтение **всего** системного журнала (стандартная семантика
   Linux для этой группы), не только `admin_bot`, и не даёт root/sudo. Более узкий вариант —
   ACL на конкретные файлы — отвергнут как хрупкий (ротация/новые файлы журнала); выбран штатный
   минимальный механизм.
2. Сквозной чек-ап (LLM → tool → журнал) не прогонялся; проверена сервисная среда и точная
   команда из настройки. Полный сценарий — на стороне Builder после релиза.
3. Группа `adm` не добавлена; `/var/log` fallback не проверялся, поскольку не требуется.

## 10. SSH-дисциплина (fail2ban)

3 подключения, все key-auth (`root`), без паролей, без параллельных сессий, без ретраев и без
ошибок аутентификации: recon `04:12:07Z`, основной прогон `04:13:14Z` (фикс+рестарт+верификация),
контрольный read-only прогон `04:17:40Z` (окно после рестарта). Между подключениями ≥ 1 мин,
между основным и контрольным ≈ 4 мин. Каждая команда ограничена таймаутом; временные файлы
`/tmp/_j*`, `/tmp/_v*` удалены в тех же прогонах. Секреты не читались и не выводились
(`.env` не открывался, значения `Environment*` замаскированы).
