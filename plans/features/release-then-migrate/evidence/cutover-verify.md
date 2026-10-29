# CUTOVER attempt + ROLLBACK — release-then-migrate (slice CUT/VERIFY, DevOps)

**Дата окна:** 2026-10-29, 00:53:38Z → 01:04:31Z (UTC; оба сервера Etc/UTC). **Исполнитель:** DevOps.
**MIGRATION_SOURCE_SHA:** `5346ee765e83ee859596b60437811b21db1e4564` (2.58.141) — подтверждён на OLD в recon (O1) и на NEW (N1/nc2).
**Итог попытки:** **CUT → ROLLBACK (чистый)**. Окно остановлено по ABORT RULE на шаге 7 (переключение DNS): токен DuckDNS не найден ни в `.env`, ни в cron/systemd/скриптах/историях команд обоих серверов (запись A выставлялась владельцем через панель — креденшел существует только у владельца). Старый production восстановлен и верифицирован; NEW остался в безопасном неактивном состоянии. Статус среза: **WAITING_EXTERNAL (DuckDNS токен/правка A-записи владельцем) → повторное окно CUT ≈10–12 мин после устранения**.
**План отката:** `plans/features/release-then-migrate/evidence/rollback-plan.md` (написан ДО окна; откат выполнен ровно по его §2/§7).

## 0. Журнал SSH-сеансов (дисциплина fail2ban: паузы ≥62 c, single auth, без ретраев/параллели)

| # | Время UTC | Хост | Содержание | Результат |
|---|---|---|---|---|
| O1 | 00:43:22 | OLD nik@ | recon+preflight (healthz 200, HEAD==SHA, unit active, DNS→198.46.175.136, .env sha==SYNC) | OK |
| N1 | 00:46:25 | NEW root@ | preflight (unit inactive+disabled, 0 процессов, staging на месте) | OK |
| N1b | 00:48:32 | NEW | диагностика host key/authorized_keys | OK |
| O2 | 00:53:36 | OLD | **WINDOW_START 00:53:38Z**: stop admin_bot+bot-api, финальные снапшоты, keygen | OK |
| N2a | 00:54:57 | NEW | установка adminbot_vps + временного ключа, staging cut/ | OK |
| O2b | 00:55:07 | OLD | пуш — СБОЙ (root-owned staging: O2 исполнялся под sudo целиком) | откат не требовался |
| O2b | 00:57:20 | OLD | пуш — СБОЙ (stdin-swallow: bash -s + дочерний ssh) | откат не требовался |
| O2b | 00:59:43 | OLD | пуш: SQLite 1,669,840,896 B + dump + bot-api 69.5 MB + media(0 delta) + env; REMOTE sha == OLD (4/4) | OK |
| N2 | 01:01:43 | NEW | sha-verify, integrity=ok ДО размещения, placement, PG restore rc=0/0err, counts 26/26==OLD, DSN OK, ENV match | OK |
| O3 | 01:02:25 | OLD | DuckDNS-охота: 3 кандидата → KO → **ABORT до остановки стека** (ветка плана §5) | abort |
| O3b | 01:03:59 | OLD | расширенная охота (token=, uuid, обе истории): **candidates=0** → **ROLLBACK** по плану | ROLLBACK_DONE 01:04:31Z |
| nc1/nc2 | 13:05+01:06 (+1200) | NEW | authorized_keys восстановлен (1 строка, ключ владельца; временный ключ удалён), финальный state NEW | OK |

- OLD: 6 коннектов (лимит ~5–6 — на лимите, дальнейшие OLD-подключения в этом окне прекращены; восстановление проверено внутри сеанса O3b + внешне по HTTP). NEW: 6 локальных + 2 входящих пуша от OLD.
- Host key NEW: `ssh-rsa SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` — **эталон INV/PREP/SYNC подтверждён** (серверный `ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub` и known_hosts_migrate). Ранний «MISMATCH» — ошибка моего диагностика (sha256 от MD5-дайджеста paramiko), не инцидент.
- Пароль root NEW: ключ adminbot_vps был сломан SYNC-revoke (в authorized_keys осталась 1 нечитаемая строка) — временно использован пароль из deploy_commands.txt (владельческий метод доступа); по итогу authorized_keys **восстановлен** на корректный ключ владельца — доступ по ключу снова работает.

## 1. CUT по шагам (§6 owner-input)

| Шаг | Результат | Evidence |
|---|---|---|
| 0 preflight | OLD healthz 200 2.58.141, HEAD==5346ee76, unit active; NEW unit inactive+disabled, 0 процессов, PG healthy | O1/N1 |
| 1 точка возврата | rollback-plan.md §1 (SHA, unit active, DNS→198.46.175.136, объёмы, shas) | артефакт |
| 2 stop OLD writers | admin_bot inactive, 0 процессов; bot-api exited; ⚠ db_holders=3 (см. §4 аномалии) | O2 |
| 3 финальные снапшоты | SQLite backup API (quiet) 1,669,840,896 B sha `760aa5e8…`; pg_dump -Fc 603,446 B sha `fce935bc…`; bot-api tar 69,529,600 B (426 файлов) sha `1317bffd…`; PG counts 26 таблиц (тихие финальные); media 59 файлов digest `d25b19c1…`; env sha `67bb8b1e…`==SYNC | O2 |
| 4 целостность ДО загрузки | SQLite integrity_check=ok (page_count 407676, freelist 80, user_version 37, **76 таблиц** с count'ами); PG pg_restore -l через dump; REMOTE sha 4/4 == OLD | N2/O2b |
| 5 загрузка финала на NEW | live db размещена `/var/www/admin_bot/local_database.db` (adminbot:adminbot 640); PG `pg_restore --clean --if-exists` **rc=0, 0 ошибок**; counts 26/26 == финальным OLD; DSN-коннект с реальным паролем OK (asyncpg, server_version_num=160015); ENV_BYTES_MATCH=yes; media/ownership chown adminbot | N2 |
| 6 logOut/переключение bot-api | **НЕ ВЫПОЛНЕН** (abort до logOut — новый bot-api не стартовал, двойной привязки токена нет) | O3/O3b |
| 7 DNS/reverse proxy | **БЛОКЕР: токен DuckDNS недоступен агенту** (см. §3); A-запись осталась → 198.46.175.136 | O3/O3b |
| 8 старт нового | **НЕ ВЫПОЛНЕН** (правильно: без DNS-переключения домен показывал бы мёртвый сервер) | — |

## 2. Окно и откат

- **WINDOW_START** 00:53:38Z (epoch 1793235218); **фактический гэп**: admin_bot OLD остановлен 00:53:38Z → перезапущен ~01:04:20Z, healthz 200 в **01:04:31Z** ≈ **10 мин 53 с** (в гэпе был бот и приложение: админка/медиа через домен отдавали 502; сам домен/TLS всё время обслуживался Caddy OLD).
- Откат (план §2/§7): контейнеры стартованы (bgutil «No such container adminbot-bgutil-pot-provider» — фактическое имя `adminbot-bgutil-pot`, он и не останавливался — не влияет), `systemctl start admin_bot`, healthz 200 на try5 (~20 c), body `{"status":"ok","version":"2.58.141"}`.
- Внешняя верификация отката (локальная машина, без SSH): `https://admin-bot.duckdns.org/healthz` → **200 2.58.141**; DNS → **198.46.175.136** (точка возврата §1 плана — точное совпадение).
- Данные: не потеряны и не удалены — OLD live-набор не изменялся в окне (снапшоты — только копии), staging-копии на OLD удалены, оригиналы на месте; NEW содержит загруженный (но замороженный) финальный набор и не запускался ни разу → двойного экземпляра/повторных отправок не было ни в один момент окна.

## 3. Блокер: DuckDNS

- `.env`: ключей с `duck` нет (проверено списком имён всех 156 ключей).
- Поиск по OLD (sudo): `/etc/caddy/Caddyfile*`, geosite.dat, `/home/nik/.bash_history` — совпадения только по домену; **token= паттерн: 0 кандидатов**; crontab root: только `rotate_bak.sh` 03:10; cron.d: e2scrub/sysstat.
- API-пробы: 3 кандидата (hex-32 из истории/файлов) → `KO`; uuid-формат не встретился. Вывод: запись изначально выставлялась владельцем через панель DuckDNS — **токен существует только у владельца** (подлинная внешняя зависимость по креденшелу, rollback-plan §5).
- Возобновление: владелец либо обновляет A-запись admin-bot.duckdns.org → `192.255.209.205` в панели, либо передаёт токен в приватный канал (deploy_commands.txt). После этого повторное окно CUT: сценарии сохранены (`scripts/o3b_retry.sh` сокращённо — шаги 6–8) + полный прогон повторной синхронизации дельты (старый бот снова работал → SQLite/PG/bot-api/media дельта обязательна; скрипты O2/O2b/N2/N3/N4 переиспользуемы как есть).

## 4. Состояние NEW (подготовлено к следующей попытке)

- admin_bot inactive+**disabled**, 0 процессов; caddy/xray inactive+disabled; контейнеры: только postgres Up (healthy, разрешённый aux), bot-api/cobalt/bgutil Created (не стартовали).
- Загружено и заморожено (будет заменено свежим финальным снапшотом при повторе): live db 1,669,840,896 B (adminbot:adminbot) — integrity ok; PG восстановлен из финального дампа (counts 26/26); .env байт-в-байт (sha `67bb8b1e…`); git HEAD == 5346ee76; staging `/var/lib/adminbot_migration/cut` (1,740,014,831 B: snapshot+dump+botapi_final.tar+env_final — sha-совпадавшие копии; копия db уже размещена, дубликат можно очистить при следующем прогоне).
- authorized_keys: восстановлен (1 строка, ED25519 владельца); временный ключ миграции удалён (grep 0), приватный ключ на OLD удалён вместе со staging.

## 5. Соответствие строкам карты (для PM-байнда)

| Req ID | Статус по факту окна | Обоснование |
|---|---|---|
| REQ-RM-ROLLBACK-PRE / POST | **VERIFIED** | план написан до окна (rollback-plan.md §1–§7); откат исполнен по нему, возврат верифицирован |
| REQ-RM-PROHIB-DUAL | **VERIFIED** | в каждый момент ≤1 бот: OLD остановлен 00:53:38–01:04:31, NEW ни разу не запускался (unit disabled) |
| REQ-RM-PROHIB-DATA | **VERIFIED** | удалены только копии staging OLD после верифицированного пуша; live-данные OLD/NEW не удалялись |
| REQ-RM-CUT-PRECHECK | **VERIFIED** | SHA-match, память/джобы сверены (O1/N1), окно зафиксировано 00:53:38Z |
| REQ-RM-CUT-STEP1..5 | **VERIFIED** | §1 таблица (шаги 1–5 с числами/sha) |
| REQ-RM-CUT-STEP6..8 | **PENDING (повтор окна)** | не выполнялись (abort до logOut/DNS/старта); блокер — §3 |
| REQ-RM-CUT-NOT-DONE-200 | **VERIFIED (в силу честного abort)** | DONE не объявлялся; сравнения данных выполнены (§1 шаг 4–5), единственность — §PROHIB-DUAL |
| REQ-RM-VERIFY-SQLITE/PG/FILES/GIT/ROUTES/SINGLE/ACCESS/OLDVPS/SNAPSHOT-BASIS | **PENDING (после успешного повторного CUT)** | сравнения против финального снапшота сняты и записаны (§1), но приёмка нового production невозможна без переключения; OLD-VPS intact подтверждён (fallback жив: healthz 200 извне) |
| REQ-RM-VERIFY-OLDVPS (частично) | evidence готов | OLD не тронут в данных; unit/контейнеры восстановлены; media 59; env sha == SYNC |

## 6. Аномалии / incidental findings

1. **DuckDNS-токен недоступен агенту** — блокер шага 7 (см. §3). Не дефект кода/данных.
2. **authorized_keys NEW был сломан** с 00:26:32Z (SYNC-revoke оставил нечитаемую строку; «is not a public key file») — ключ-доступ не работал; исправлено nc1 (ключ владельца восстановлен). Инфра-дефект DevOps-слоя, устранён.
3. **O2 исполнялся под sudo целиком** → staging/ключ root-owned → первый O2b не смог прочитать ключ (исправлено запуском o2b под sudo); второй O2b упал из-за stdin-swallow (`bash -s` + дочерний ssh) — исправлено SFTP-заливкой скрипта. Обе ошибки оркестрации, не данных; в логах не оставили следов данных.
4. **db_holders=3** в O2 после stop (скан /proc по маске *local_database.db*) — не объяснено в окне; компенсировано пост-фактум: integrity_check=ok, 76/76 таблиц и 26/26 PG-счётчиков сошлись, pg_restore rc=0 — снапшот консистентен. К проверке на повторе (снять имена держателей).
5. **10-минутные root CRON-сеансы на NEW** (00:35:01, 00:45:01) — источник не идентифицирован (root crontab показывает только rotate_bak 03:10 — строка попала в NEW-вывод из-за запуска под sudo на OLD); к боту отношения не имеет, не блокер; классифицировать при следующем проходе.
6. Остаток: 1 файл `/tmp/oc_cut_*.sh` на NEW (без секретов; удалить при следующем сеансе).
7. Секрет-гигиена: все raw-логи санитизированы на записи (bot-token regex, DSN, пароли, duckdns token=); значения ключей .env не печатались (только имена); пароль NEW в лог/артефакт не попал. Контрольный скан — чисто.

## 7. Raw-evidence

`WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-7de199fddd/`:
- `cut_driver.py` (paramiko-драйвер: pacing ≥62 c/хост, SFTP-скрипты, санитизация, пароль root NEW — только из deploy_commands.txt в памяти);
- `scripts/o1_recon.sh, n1_preflight.sh, n1b_diag.sh, o2_stop_snap.sh, n2a_install_key.sh, o2b_push.sh, n2_load.sh, o3_logout_finish.sh, o3b_retry.sh, nc1_cleanup.sh, nc2_state.sh`;
- `raw/old_*.out.txt / new_*.out.txt / *.meta.json` (полные выводы всех сеансов).
Локальная машина: 2026-10-29 12:43–13:07 (+12:00).

**Итог среза CUT/VERIFY:** окно отработано по плану до шага 7, остановлено ABORT RULE на недоступном креденшеле DuckDNS, откат выполнен чисто за 10 мин 53 c, старый production проверен внешне (200/2.58.141, DNS на месте), NEW безопасно заморожен для повтора. Единственный оставшийся шаг к завершению миграции — **владелец: обновить A-запись admin-bot.duckdns.org → 192.255.209.205 (или передать токен DuckDNS в приватный файл)**, после чего повторное окно ≈10–12 мин закрывает шаги 6–8 + VERIFY.
