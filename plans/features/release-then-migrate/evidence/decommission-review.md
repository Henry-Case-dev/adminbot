# Decommission review — independent acceptance (Reviewer)

**Вердикт: ACCEPT**
**Дата проверки:** 2026-10-29, около 07:50 UTC (19:50 UTC+12).
**Объект:** заключительная очистка старого VPS по директиве владельца, части V–VI и §22. Это не приёмка нового кода.
**Кандидат production:** `5346ee765e83ee859596b60437811b21db1e4564` / `2.58.141` на `192.255.209.205`.
**Блокеров нет.** Устаревшие формулировки в `AGENTS.md` и `deploy_commands.txt` — обязательная правка документов для оркестратора, не отказ в очистке.

Независимые проверки этой сессии: внешний HTTPS, локальный бэкап (все 6 хешей + SQLite), одна read-only SSH-сессия на старый VPS, одна read-only SSH-сессия на новый VPS. Секреты не печатались. Повторных auth не было.

## Чеклист §22

| Пункт §22 | Статус | Доказательство |
|---|---|---|
| Итоговые результаты нового production | PASS | Внешний `GET https://admin-bot.duckdns.org/healthz` → 200 `{"status":"ok","version":"2.58.141"}`; DNS A → `192.255.209.205`. SSH root: `admin_bot` active+enabled, MainPID **72680**, NRestarts=0, HEAD `5346ee765e83ee859596b60437811b21db1e4564`, локальный healthz тот же. SQLite ro: **2 050 948** сообщений, graph_facts **21 739**. Контейнеры postgres/bot-api/cobalt healthy, bgutil Up. Рост от бэкапа 2 050 649 и от сверки DevOps 07:40Z (2 050 911) монотонный. |
| Независимая резервная копия | PASS | Каталог на машине владельца, не на VPS: `C:\Users\main\.config\opencode\WorkspaceData\backups\adminbot-postmigration-2026-10-29\`. 8 файлов, 1 776 899 555 байт (1 694,6 МиБ). Все 6 хешей `MANIFEST.sha256` пересчитаны локально — **совпали**. SQLite `integrity_check=ok`, user_version 37, smart_messages **2 050 649**, 121 таблица. media.tar: 59 файлов. botapi: есть tqueue.binlog и webhooks binlog. `postgres.dump` начинается с `PGDMP` (custom). Локального `pg_restore` нет — лимитация честная; читаемость TOC закрыта серверным `pg_restore -l` в фазе 2. |
| Правильность области удаления | PASS | Журнал `decommission-old-vps.md` сверен с `inventory-old-vps.md` и сырыми `pass2.sh` / `pass2b.sh` / `raw_pass2*.out.txt`. Удалены только объекты бота: `/var/www/admin_bot` (после проверки «это каталог, не symlink, mount = /»), unit+drop-in, 4 контейнера по label `admin_bot`, volume `admin_bot_adminbot_pgdata`, сеть `admin_bot_default`, 4 образа по точным именам, единственный vhost Caddy, cron `disk_retention`, поимённые файлы `~nik`. Запрещённого не было: нет `docker system prune -a`, нет массового `volume prune`, нет остановки daemon, нет `compose down -v`, нет `journalctl --vacuum`, нет зачистки history, нет reboot, пользователь `nik` на месте. |
| Чужие сервисы не повреждены | PASS | SSH nik: uptime **3 дня 17 ч** (reboot не было), sshd/fail2ban/docker active, `nik` uid=1000, `.bash_history` **220 256** байт (как в журнале DevOps), `/opt/headroom` на месте (владелец headroom, mtime 11 Sep), headroom.service active, `/tmp/data-gym-cache` на месте, `~nik/.ssh` не тронут. xray inactive — так было ещё до очистки (POST 04:54Z), сервис не удаляли. |
| Реальное отсутствие установки Adminbot на старом VPS | PASS | SSH: `/var/www` пуст, `/var/www/admin_bot` отсутствует, `systemctl is-enabled admin_bot` = not-found, unit-files hits = 0, crontab nik пуст и без bot-строк, процессов bot/venv/telegram-bot-api = 0, `docker ps -a` пуст, volumes пусты, daemon жив (29.x). Caddyfile без `admin-bot` (grep 0). |

## Точечные проверки ревьюера

| Проверка | Наблюдение |
|---|---|
| Новый прод, HTTPS | 200, версия 2.58.141, DNS только на новый IP |
| Новый прод, SSH | whoami=root; active+enabled; HEAD совпал; один MainPID 72680 с 04:56Z |
| Счётчик сообщений | 2 050 948 сейчас > 2 050 911 (07:40Z) > 2 050 649 (бэкап 06:48Z) |
| Старый IP в конфигах нового | grep по `.env`, Caddyfile, unit, compose, `config/` = **0**. Сырой `pass3new`: те же 0; запрос PG не вернул строк |
| Старый VPS, отсутствие бота | каталог/unit/cron/процессы/контейнеры/volumes отсутствуют |
| Старый VPS, чужое | headroom, nik, history, sshd, fail2ban, docker daemon целы |
| Бэкап | 6/6 sha256 OK; SQLite ok; 59 медиа; binlog бот-API на месте |

`pgrep -c` в этой сессии показал 3 совпадения шаблона `bot.py`. Это самосовпадение: шаблон был в командной строке удалённого shell и у самого pgrep. Systemd держит один MainPID 72680, NRestarts=0, тот же PID, что в сверке DevOps. Второго poller нет.

## Сверка удаления с инвентарём

Каждый удалённый класс есть в инвентаре 28.10 или в PASS1 29.10 и принадлежит боту:

- приложение, SQLite, media, `.env`, venv, бэкапы внутри `/var/www/admin_bot`;
- `admin_bot.service` + override;
- 4 контейнера, volume с compose-префиксом, сеть, bind-mount bot-api;
- Caddyfile из одного блока `admin-bot.duckdns.org` (127 байт в инвентаре) заменён комментарием, бинарник и cert storage не тронуты, caddy не запускали;
- cron nik — одна строка `disk_retention.py`, после фильтра crontab пуст;
- `~nik` — явный список эпиков/релизов/копий `.env` и pg-дампов бота; после удаления остались `.ssh`, `.bashrc`, `.gitconfig`, `.bash_history`.

Первый safety-check каталога в pass2 честно **ABORT** (кривой `findmnt`). Каталог снят только в pass2b, когда containing mount был `/`, путь не symlink. Сейчас каталога нет.

Намеренно оставлено и это правдоподобно: xray (VPN владельца, не удаляли), `/opt/headroom`, `/tmp/data-gym-cache`, общие журналы, fwupd в failed (сырой sweep 07:32Z: `fwupd.service` и `fwupd-refresh.service` failed; ревьюер застал `is-system-running=degraded`, uptime без reboot).

## Обязательная правка документов (не блокер очистки)

Оркестратор должен поправить тексты, которые всё ещё описывают старый VPS как живой резерв с целыми данными. Откат теперь только из бэкапа на машине владельца. На старый IP деплоить нельзя: установки там нет.

1. `AGENTS.md`, инфра-абзац: «остановлен и сохранён как fallback… данные/бэкапы целы» — **устарело**.
2. Приватный `deploy_commands.txt`, шапка и хвост плана (старый VPS = fallback, «данные целы», «не очищать до подтверждения») — то же устаревание. Секреты в отчёт не копировать.

Ревьюер эти файлы не редактировал.

## Замечания, не блокирующие

- Усечённые sha256 в `final-acceptance-and-backup.md` перепутаны на хвостах (склейка при сокращении). Источник истины — `MANIFEST.sha256`; он совпал с пересчётом. Таблицу в том отчёте лучше не цитировать как полные хеши.
- Образы Docker на старом хосте стали 0, потому что других образов не было и четыре ботных сняты по имени. `docker system prune -a` не вызывался, daemon жив. Чужого Docker не было.
- Предупреждения embed `NameError` на новом проде — прежнее семейство, не регрессия очистки.
- Обновлятора DuckDNS нет ни на старом, ни на новом. Домен сейчас смотрит на новый IP. Долгосрочная ротация — сторона владельца, на текущую работу не влияет.
- Локально нет `pg_restore`. Формат дампа подтверждён magic `PGDMP`; полный TOC остаётся на серверной проверке фазы 2.

## Итог для оркестратора

Очистку старого VPS можно считать принятой. Новый сервер — единственный production, живой, на принятом SHA. Независимый бэкап на машине владельца цел. Чужие сервисы и учётка `nik` не повреждены. Следующий шаг — поправить `AGENTS.md` и шапку `deploy_commands.txt`, чтобы никто не пытался откатиться на уже пустой старый VPS. Повторная очистка и новый эпик не нужны.
