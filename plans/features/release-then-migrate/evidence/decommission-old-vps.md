# Decommission OLD VPS — release-then-migrate (phases 3–6, DevOps)

**Дата/окно:** 2026-10-29, 07:12–07:40 UTC (локально 19:12–19:40 UTC+12).
**Вердикт: COMPLETE** — Adminbot полностью удалён со старого VPS (198.46.175.136); чужие данные/сервисы не затронуты; новый production перепроверен после удаления.
**Условия GO:** фазы 1–2 пройдены ранее (см. `final-acceptance-and-backup.md`): новый прод здоров, независимый проверенный бэкап на машине владельца.
**Освобождено дискового пространства:** 17G → 8.3G used (24G диск; 5.8G → **15G свободно, ≈ 8.7 GB**).

## 0. SSH-журнал (fail2ban-дисциплина)

| # | Время UTC | Хост | Цель | Пауза | Auth |
|---|---|---|---|---|---|
| 1 | 07:12:47 | nik@198.46.175.136 | recon 15с | — | пароль (deploy_commands.txt, в памяти процесса) |
| 2 | 07:14:18 | старый | PASS1 read-only инвентаризация | ~90с | тот же, single auth |
| 3 | 07:21:08 | старый | PASS2 попытка — **не исполнилась** (моя ошибка порядка stdin; parse-error до первого действия) | ~6м45с | тот же |
| 4 | 07:29:00 | старый | PASS2 удаление + инлайн-сверка | ~7м52с | тот же |
| 5 | 07:32:20 | старый | PASS2b: удаление каталога, probe, финальная сверка §19 | ~3м | тот же |
| 6 | 07:35:59 | старый | очистка /tmp-артефактов релиза | ~3м30с | тот же |
| 7 | 07:37:47 | старый | финальная мини-доводка + подтверждение | ~1м45с | тот же |
| 8 | 07:38:38 | root@192.255.209.205 | §20 новый прод (read-only) | другой хост | ключ adminbot_vps |
| 9 | 07:40:0x | новый | добор: ERROR/Traceback/heartbeat | ~1м20с | ключ |

Hostkey старого запинен при recon (`ssh-ed25519 52:b5:15:d4:32:f7:cb:09:e5:4b:c4:07:3c:3c:cf:26`), **MATCH на каждом** из 7 коннектов; паузы ≥60с; параллельных коннектов/ретраев auth нет; авторизационных отказов 0 (два parse-error — после успешного auth, скрипт не исполнялся, состояние не менялось). Серверное время сверено (UTC, совпадает с журналом).

## 1. PASS 1 — инвентаризация (§10–§11), 07:14Z

Атрибуты: путь / тип / владелец / evidence принадлежности боту / использование другими / symlink / mountpoint / чужое содержимое / действие / пост-проверка.

| Объект | Тип/владелец | Принадлежность | Другие используют | Symlink/ mount | Действие | Итог |
|---|---|---|---|---|---|---|
| `/var/www/admin_bot` (4.6G: git tree @5346ee76 detached, .env 158 ключей, SQLite 1.67G+WAL+SHM+orphan journal, backups/ 1.5G, media 96M, venv 404M, plans/ 413M, test_subs, pre_migration_backup/, info_text.bak ×9, probes_full/) | dir, root:developers 2775 | бот (деплой-артефакт; бэкапы SQLite/facts от бота) | нет (единственный проект в /var/www) | нет/нет (readlink=сам, содержащий mount=/) | rm -rf (sudo) | удалён ✅ |
| `admin_bot.service` + `admin_bot.service.d/override.conf` (TimeoutStopSec=60) | unit, root | бот (ExecStart bot.py) | нет | — | disable уже был; rm + daemon-reload | удалён, list-unit-files=0 ✅ |
| Контейнеры adminbot-telegram-bot-api / -postgres / -cobalt / -bgutil-pot | docker, Exited (остановлены на cutover ~04:11Z) | labels `com.docker.compose.project=admin_bot` (все 4 проверены) | нет (единственные контейнеры хоста) | — | docker rm -f по label | удалены ✅ |
| volume `admin_bot_adminbot_pgdata` (73.57MB) | docker | label project=admin_bot | нет | — | docker volume rm | удалён ✅ |
| network `admin_bot_default` | docker | label project=admin_bot | нет | — | docker network rm | удалена ✅ |
| образы aiogram/telegram-bot-api, postgres:16-alpine, cobalt:11, bgutil-pot | docker 1.39GB | вытянуты compose-проектом бота | нет (других образов/контейнеров на хосте нет) | — | docker rmi по точным именам (без prune) | удалены (images=0) ✅ |
| bind-mount `docker/telegram-bot-api/` (внутри имя = токен бота) | dir messagebus:lxd | данные локального Bot API бота | нет | нет | внутри rm -rf приложения (через sudo, имя нигде не печаталось) | удалён ✅ |
| Caddyfile: vhost `admin-bot.duckdns.org` (+2 .bak-варианта) | conf, root; caddy inactive | бот (reverse_proxy 127.0.0.1:8000) | других сайтов нет (файл 127B = один блок) | — | блок удалён, конфиг заменён комментарием, `caddy validate` OK, .bak удалены; **бинарник/cert storage не тронуты, сервис не стартовал** | ✅ grep admin-bot=0 |
| cron nik: еженедельный `disk_retention.py` | crontab | бот | других записей нет | — | отфильтрована, crontab пуст | ✅ |
| `adminbot-disk-retention.log` | файл nik | бот (лог крона) | нет | — | rm | ✅ |
| Процессы: rerun_r3.py (PID 308442/308443), 3×`python -` (613105/619036/622981), `probe_258140.py` (800296) | proc, venv бота | интерпретатор /var/www/admin_bot/venv (исключительно бот) | нет | — | TERM→KILL | все завершены ✅ |
| `/tmp/probe_258140.py`, `/tmp/p0d/`, `/tmp/p0d_journal.log`, `deploy_258140.sh`, `tv258140.sh` (verify-скрипт релиза 258140), `_h.py` (тест-хелпер ADMINBOT_SKIP_DOTENV), `d133/d134_*.log`, `rel136_pre_read.py` | файлы /tmp | релизные артефакты бота | нет | — | rm (часть под sudo) | ✅ |
| `/home/nik` ботные артефакты: asap2*/asap21*/asap3_* скрипты и логи, check_*/seed_*/gen_initdata/initdata_asap3, errwin.sh, livafter/restart/postrestart, .r1028_dryrun2.py, soul86_env_backup (копия .env — секреты!), soul86_pg_backup ×3, 0-байтовый local_database.db, файлы 000/200/302/401/404/]+, deploy-258122/24/25/, incident-20260929/, .mig_cut_push/, пустые backups/ + backups_adminbot/ | файлы/каталоги nik | имена = эпики/версии/инциденты проекта; созданы при релизах бота | нет | — | явный поимённый список rm | ✅ |
| Git-креды в app dir (.git/config, .netrc, deploy keys) | — | remote = публичный HTTPS GitHub без кредов; .netrc/.git-credentials/ключей НЕТ | — | — | удалять нечего | ✅ |

DuckDNS-апдейтер на старом: **не найден** (cron root/nik, /etc/cron.*, systemd, /home/nik, /usr/local/bin — 0 попаданий) → риск DNS-flip отсутствует. Firewall: ufw отсутствует, iptables не правил (shared, ботных правил нет). systemd-таймеров ботных нет; юнитов с упоминанием бота, кроме самого admin_bot.service, нет (grep /etc/systemd/system).

## 2. PASS 2 — удаление (§12–§18)

- §12: новый прод здоров (healthz 200 перед стартом); admin_bot inactive+disabled; polling/писатели/Summary/Dream/Initiative на старом отсутствуют (процессов bot.py нет); 6 остаточных процессов бота завершены; юнит выключен и удалён + daemon-reload; reboot НЕ выполнялся.
- §13: `/var/www/admin_bot` удалён целиком (перед этим: stat=directory, readlink=сам, не mountpoint) — .env, SQLite+WAL/SHM+orphan journal, media, embeddings-in-DB, backups/, логи, очереди/джобы (dossier_jobs), test_subs, pre_migration_backup/, venv — всё внутри. Вне каталога: /tmp-артефакты и /home/nik файлы — поимённо (см. §1).
- §14: unit + drop-in удалены; `systemctl list-unit-files | grep admin_bot` = 0; в /etc/systemd/system записей с «bot» нет.
- §15: 4 контейнера (по label), volume (по label), сеть (по label), 4 образа (по точным именам); **docker system prune НЕ выполнялся**, daemon жив (29.7.2): containers=0, images=0, volumes=0.
- §16: vhost admin-bot.duckdns.org удалён (остальные сайты — отсутствовали), конфиг валиден; caddy не запускался (был inactive); cert storage не тронут (оставлен намеренно).
- §17: git-кредов бота вне app dir нет (публичный HTTPS); `~nik/.ssh` (authorized_keys, known_hosts) не тронут; парольный доступ nik сохранён; global .gitconfig (39B, user-настройка) сохранён.
- §18: удалены только прикладные артефакты бота; **journald/auth.log/docker-логи/command history (.bash_history 220256 B) не тронуты**; vacuum не выполнялся; secure erase не выполнялся.

## 3. PASS 3 — §19 сверка старого (07:32–07:37Z, read-only)

Процессов бота/probe/telegram-bot-api = 0; юнит отсутствует (`systemctl cat` fails); таймеров нет; контейнеров/volumes/сетей/образов = 0, daemon жив; `/var/www/admin_bot` отсутствует (SQLite/media/embeddings — с ним); cron пуст; в Caddyfile 0 упоминаний admin-bot (конфиг Valid); git tree и креды отсутствуют; /tmp ботных остатков 0. Системное: SSH жив, systemd running (см. аномалии), fail2ban active, sshd/cron/docker/containerd/rsyslog/resolved/timesyncd работают; user nik и его доступ не тронуты; `.bash_history` 220256 B на месте.

## 4. PASS 3 — §20 новый production после удаления (07:38–07:40Z + внешний HTTP)

| Проверка | Наблюдение | Статус |
|---|---|---|
| Сервис | admin_bot active+enabled, PID 72680, NRestarts=0, аптайм процесса с 04:56:02Z | ✅ |
| Git/версия | HEAD `5346ee765e83ee859596b60437811b21db1e4564` = принятый релиз; healthz 2.58.141; dirty = только untracked `.cache/` (известно, CUT) | ✅ |
| Контейнеры | postgres/cobalt/telegram-bot-api healthy, bgutil Up 3h | ✅ |
| PostgreSQL | bot_settings=544, bot_roles=4; heartbeat uptime_events «up» 07:39:05/07:40:05 (каждые 60с) | ✅ |
| SQLite (ro) | **2 050 911 сообщений** (фаза 1 в 06:48Z: 2 050 649 → **+262, монотонный рост**; polling работает), max_id 2 373 139; journal_mode=wal; **integrity_check ok** | ✅ |
| Журнал с 07:00Z | ERROR-уровень: **0**; активная запись (WATCHDOG_SWEEP, VisionMediaWorker тики до 07:40:15) | ✅ |
| Скрытые зависимости от 198.46.175.136 | .env/Caddyfile/compose/unit/config-каталог = 0 попаданий; PG bot_settings по LIKE = 0 строк | ✅ чисто |
| Домен/TLS извне | DNS A → 192.255.209.205; GET /healthz → 200 `{"status":"ok","version":"2.58.141"}` | ✅ |
| Ресурсы | диск 16G/99G (17%), RAM avail 2.7G | ✅ |

## 5. Намеренно оставлено (и почему)

- **xray.service** — личный VPN владельца (конфиг root:0600, не принадлежит боту); на 28.10 был active, сейчас **inactive** — не наше действие, не трогали вовсе.
- **/opt/headroom + headroom.service** — чужой рабочий LLM-прокси-сервис (deepseek) — активен, не тронут.
- **/tmp/data-gym-cache** (root:root, 3.6MB blob) — происхождение неоднозначно (общий pip-кэш) → оставлен.
- **fwupd.service, fwupd-refresh.service = failed** (причина `systemctl is-system-running` = degraded) — **pre-existing** системные firmware-юниты, к боту не относятся, не тронуты (на VPS fwupd штатно падает; состояние не менялось нашими действиями).
- journald, auth.log, .bash_history, .ssh nik, .gitconfig nik, /var/www (пустой, системный), docker daemon, unattended-upgrades, snap/systemd-private в /tmp — общие/системные, не тронуты.
- **DuckDNS-апдейтера нет ни на старом, ни на новом** (наблюдение владельцу: домен сейчас резолвится на новый IP и обслуживается; долгосрочное обновление DuckDNS — сторона владельца/роутера; на работу не влияет).

## 6. Аномалии / находки

1. probe-процесс `probe_258140.py` пережил первый kill (его cmdline не содержал путь venv) — добит во 2b, в финальной сверке отсутствует.
2. Файлы `backups/`, `docker/telegram-bot-api/`, часть /tmp требовали sudo (root/lxd-владение) — выполнено через sudo nik (пароль stdin, не печатался).
3. Traceback 07:31:37 на новом — известный pre-existing embed-дефект (`NameError: _LAST_EMBED_META`, embedding_control_plane.py:1373; факты сохраняются text-only, FTS-fallback жив) — то же семейство из §4 фазы 1 (Builder-backlog), **не регрессия**, к декомиссии отношения не имеет.
4. uptime_events не имеет колонки created_at (колонки id/ts/status) — ошибка моего первого запроса, исправлена повторным; на приёмку не влияет.
5. `pass_gti_pull` из deploy_commands.txt не понадобился (git pull не выполнялся).

## 7. Секреты

Значения секретов/токенов не печатались ни в команды, ни в этот артефакт; имя каталога bot-api (содержит токен) нигде не выведено; маскирование token-паттерна активно на всех выводах; .env не читался (только счётчик ключей). Raw-логи: `WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-509283dbac/` — `raw_pass1/2/2b/3old/3old2/3new/3new2.out.txt`, `sessions.log`, скрипты `pass*.sh`.

**Итог:** старый VPS — SSH жив, ОС/системные службы целы, чужое не тронуто; работающей установки, данных, процессов и конфигураций Adminbot больше нет. Новый VPS — единственный production, здоров, после удаления перепроверен. Будущие деплои — на 192.255.209.205 (deploy_commands.txt уже так устроен).
