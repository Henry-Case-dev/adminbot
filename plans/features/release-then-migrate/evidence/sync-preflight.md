# SYNC — pre-sync данных на NEW VPS без остановки старого бота (online-методы) — slice SYNC, release-then-migrate

**Дата:** 2026-10-29 00:11–00:27 UTC (сеансы; артефакт 2026-10-29).
**Исполнитель:** DevOps (subagent SYNC). **MIGRATION_SOURCE_SHA:** `5346ee765e83ee859596b60437811b21db1e4564` (build 2.58.141) — подтверждён на живом старом сервере в начале и в конце среза.
**Режим:** старый бот работал всё время (healthz 200 `2.58.141` на каждом OLD-сеансе); ничего на OLD не остановлено/не изменено в данных и конфигурации; на NEW бот/писатели не запущены (units `inactive+disabled`, caddy/xray `inactive+disabled`, из контейнеров работает только разрешённый пустой postgres с PREP).
**Канал переноса:** прямой old→new через временный ed25519-ключ (создан на OLD, отозван по завершении; fingerprint NEW `SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` сверен с INV/PREP-эталоном после TOFU). `rsync -a --partial --stats` (**без `--delete`**), bot-api — tar-пайп из контейнера с `--numeric-owner`. Локальная машина только оркестрировала (paramiko; пароли только в памяти процесса).

## 0. Журнал SSH-сеансов (fail2ban-безопасная дисциплина)

| # | Время UTC | Хост | Содержание | Пауза |
|---|---|---|---|---|
| 1 | 00:11:30 | OLD nik@198.46.175.136 | recon 5 с (tools/sudo/docker/git HEAD) | — |
| 2 | 00:12:40 | OLD | main: SQLite backup API + integrity + pg_dump + факты/хэши + keygen (~138 с) | ~70 с |
| 3 | 00:15:52 | NEW root@192.255.209.205 | prep: staging-каталог, установка временного pubkey, rsync-бинарь, dirs/ACL | — |
| 4 | 00:17:05 | OLD | transfer: rsync 7 потоков + tar-пайп bot-api + xray (~42 с) | ~60 с+ |
| 5 | 00:18:22 | NEW | verify: SQLite integrity + PG restore + dotenv/systemd-проба + freeze diff + хэши (64 с) | ~60 с+ |
| 6 | 00:21:18 | NEW | fix: chown runtime-наборов под adminbot + фикс systemd-пробы (10 с) | ~60 с+ |
| 7 | 00:22:37 | NEW | pin retry: venv закреплён под старые prod-версии (21 с) | ~60 с+ |
| 8 | 00:24:07 | OLD | cleanup: staging+ключ удалены, health повторно подтверждён (6 с) | ~60 с+ |
| 9 | 00:24:5x | OLD | bot-api tree digest (5 с) | ~60 с+ |
| 10 | 00:25:28 | NEW | final: tree digest NEW, аудит «S»-строки .env, конечное состояние (4 с) | — |
| 11 | 00:26:29 | NEW | revoke: временный ключ отозван, post-transfer git/media (4 с) | — |

- OLD: **5 коннектов** (лимит ~5 соблюдён), NEW: 6, все последовательные с паузами ≥62 c (принудительный pacing в драйвере), без параллели/ретраев/поллеров; single auth за коннект.
- Старый сервер после среза: все 4 контейнера Up (healthy), admin_bot active, healthz 200, `git HEAD` = SHA, untracked 13 (без изменений), диски/бэкапы не тронуты (`backups/` 1.5 GB на месте, владение/режим прежние).

## 1. Снапшоты на OLD (REQ-RM-SYNC-SQLITE / REQ-RM-SYNC-PG)

| Операция | Результат | Время |
|---|---|---|
| SQLite backup API (`venv python`, источник `mode=ro`, активный WAL 4.1 MB) | `/tmp/mig_sync/local_database_presync.db` = **1,669,840,896 B (1.55 GiB)**, exit 0 | **11.6 c** |
| `PRAGMA integrity_check` на копии **на OLD** | **ok**; PAGE_COUNT 407676, FREELIST 91, объектов 298, таблиц 121, user_version 37 | 115.9 c |
| `pg_dump -Fc -U adminbot adminbot` (docker exec, PG 16.15) | `adminbot_presync.dump` = **603,589 B**, stderr 0 B, exit 0 | **1 c** |

- Простое копирование .db с WAL **не использовалось** — только backup API (требование §5; raw-копия активного WAL не создавалась).
- Факты PG на OLD (exact counts): bot_settings 544, chat_profiles 3, personas 2, llm_usage_events 9377, chat_lore_history 250, uptime_events 4345, image_reservation 14, worker_budget 311, anticliche_cache 1.

## 2. Перенос old→new (REQ-RM-SYNC-IMMUTABLE) — объёмы/время

| Поток | Логический объём | Факт переноса | Время |
|---|---|---|---|
| Staging (SQLite-снапшот + PG dump + freeze + facts) | 1,670,447,014 B | rsync, 5 файлов, exit 0 | **29 c** |
| media/ | 100,237,770 B, 59 файлов | rsync: 59 transferred, 1 новый (runtime-файл); итоговые байты NEW == OLD **байт-в-байт** | 1 c |
| extra_images/ | 2,982,616 B, 3 файла | rsync, exit 0 | <1 c |
| chrome-profile/ | 5,462,394 B, 132 файла | rsync, exit 0 | 1 c |
| backups/dossier_jobs/ (активное состояние джобов) | 34,926 B, 6 файлов | rsync, exit 0 | <1 c |
| info_text.md + cookies (`srv_cookies.txt`, путь из `YOUTUBE_COOKIES_FILE` по его исходному абсолютному пути) | 20,900 B + 47,265 B | rsync, exit 0 | 2 c |
| .env → `/var/www/admin_bot/.env` | 8,121 B | rsync `--chmod=600` + chown adminbot:adminbot, exit 0 | <1 c |
| bot-api store (66.3 MB, 424 файла) | 69 MB класс | tar-пайп из контейнера → распаковка `--numeric-owner -p` в bind-каталог с ACL PREP; exit 0/0 | **2 c** |
| xray config → `/usr/local/etc/xray/config.json` | 1,515 B | rsync + chown root:root, chmod 600, exit 0 | 1 c |
| **Итого** | **≈ 1.81 GB логики, ≈ 1.74 GB по проводу** | все exit 0 | **≈ 42 c** (54 MB/s на bulk) |

**Владение/права:** rsync сохранил числовые uid/gid источника верно; затем применён **осознанный дельта новой инфраструктуры** (как User root→adminbot в PREP §6.1): `chown -R adminbot:adminbot` на media/extra_images/chrome-profile/dossier_jobs; `.env` = adminbot:adminbot 600; bot-api остался в системе 101:101 + default ACL `u:adminbot:r-x` (PREP) — доступ adminbot проверен: чтение bot-api OK, запись media/extra/chrome/dossier OK, чтение .env OK.

**Выборочные хэши old==new (все MATCH):** .env `67bb8b1ecb54560ca61a32d268774e903f87a60870334bf37223b23411a3d4bd`; info_text.md `c8866df2d935d2e5acceff853febafa79ed2a14a6e7640b7059189f3d8f4c47d`; cookies `444803f1226652fd391601ec68ef32cc96df04e5a0db665b4ba2e36cae66db8c`; dossier_rebuild_jobs.json `ed722143a4bfde2cb95b04ce01d222c70fd84607b6d9f88f227be33f7e1a3440`; 3 media-сэмпла (вкл. крупнейший 13.4 MB `17aef32d…` — MATCH); bot-api **tree digest 424 файлов: OLD `76928ce9d2347b8bf2699f719b1eb8539e1437892eba62306e4cc6f91f956f0f` == NEW** (полный бит-в-бит). du-суммы всех наборов old==new.

## 3. Восстановление/верификация на NEW (REQ-RM-SYNC-PG / PREFLIGHT)

- **SQLite:** integrity_check на принятом файле — **ok** (9.1 c на 2 ядрах; на 1-ядером старом — 115.9 c); PAGE_COUNT/FREELIST/OBJECTS/TABLES/USER_VERSION — **MATCH** со старым по всем пунктам. Файл лежит в staging `/var/lib/adminbot_migration/` (root 700) до CUT — приложение его сейчас не использует (замена финальным снапшотом на CUT по §5/§6).
- **PG:** роль adminbot приведена к реальному паролю из `.env` (POSTGRES_DSN и POSTGRES_PASSWORD согласованы — PW_SOURCES_MATCH 1; значение в печать не попало). `pg_restore -Fc --clean --if-exists` — **exit 0, 0 ошибок, <1 c**, 26 public-таблиц; все 9 exact-каунтов **MATCH** со старым; соединение по реальному DSN — OK, server_version_num 160015 (PG 16.15 — как на старом).
- **systemd unit:** `admin_bot/caddy/xray` — inactive + disabled; dotenv-probe юнит удалён; из контейнеров работает только postgres.

## 4. systemd EnvironmentFile vs python-dotenv (handoff PREP §6.2)

Исправленная проба: юнит с `EnvironmentFile=/var/www/admin_bot/.env` сам дампит своё окружение в root-only файл → сравнение с `dotenv_values`. Результат: **VALUE_MISMATCH = 0 по всем 146 общим ключам**; лишние в systemd — только системные `MEMORY_PRESSURE_WATCH/WRITE`; единственная дельта — ключ **`S`**, присутствующий в dotenv-парсинге, но не в systemd: это **строка 80 .env — одиночный символ «S» без `=`** (старый косметический артефакт ручной правки; \r\n нет). Приложение читает его через dotenv, как и на старом сервере (там EnvironmentFile не было вовсе) — **поведенческой разницы на CUT нет**; значение не правилось (правило «не сбрасывать», байт-в-байт сохранено, sha совпадает). Дубли ключей (10: CHAT_GLOBAL_CONTEXT_LIMIT, CHECKUP_MAX_INPUT_SYMBOLS, FACTCHECK_MAX_SYMBOLS, SEARCH_MAX_SYMBOLS, WEBPAGE_MAX_SYMBOLS, YOUTUBE_MAX_SYMBOLS, YOUTUBE_TRANSCRIPT_PROXY_DOMAIN/LOCATIONS/PASSWORD/PORT) — оба парсера берут последнее вхождение, согласовано с PREP §6.2.

## 5. venv: freeze diff и закрепление версий (handoff PREP §8)

Свежая резолюция NEW дала дрейф 48 пакетов против старого prod-venv (fastapi 0.141.1→0.162.0, starlette 1.6→1.10, asyncpg 0.31→0.32, yt-dlp 2026.8.19→2026.10.26, playwright 1.62→1.64.1 и др.). Для CUT устранён как переменная: **все 48 пакетов запиннены к точным старым prod-версиям** (все внутри диапазонов requirements.txt). Итоговый diff: **0 changed**, 84 пакета идентичны; осталось: ADDED `opentelemetry-api 1.45.1`, `pytest-timeout 2.4.0`, `tzdata 2026.6` (новые безобидные зависимости); REMOVED `logtail-python 0.4.0` (в requirements.txt прямо задокументировано «в прод-коде не используется») и `msgpack 1.2.1` (легаси-транзитив). `pip check` — No broken requirements; **import bot с реальным .env — OK**; sqlite-vec v0.1.9 — OK (повторно после пиннинга).

## 6. TLS/домен, xray, cron (REQ-RM-SYNC-ENV-TLS)

- Caddy: `caddy validate` — **Valid configuration** (Caddyfile из PREP, байт-близкий старому); **не запущен** (inactive+disabled) — ACME-гон с живым доменом исключён; Host-заголовочный тест — CUT (по заданию). DNS не тронут, пользователи не переадресованы.
- xray: конфиг перенесён (root:root 0600, sha old==new `88e11e2e…`); `xray run -test` на NEW (26.10.21) — **Configuration OK** (deprecated-варнинг gRPC-транспорта — нефатальный, информационный); версии: старая 26.3.27 → новая 26.10.21. Сервис не запущен.
- Cron `disk_retention` (nik, еженедельно): строка `30 6 * * 1 cd /var/www/admin_bot && venv/bin/python tools/disk_retention.py >> /home/nik/adminbot-disk-retention.log 2>&1`; скрипт tracked на SHA (sha `400f365d…` совпадает old==new через git). Пере-установка под нового пользователя/расписание — решение PM/Architect на CUT/SWITCH (handoff PREP §10.4).
- `.env`: OLD_IP_VALUE_HITS = 0 (нет значений со старым IP — исправления путей/IP/URL не потребовались, ничего не сброшено); TELEGRAM_API_FILES_DIR = дефолтный относительный `docker/telegram-bot-api` (валиден на NEW с тем же app-root; подтверждено import-логом).

## 7. Классификация непереносимого (каждое отсутствие доказано)

- `backups/` daily-история (1.5 GB) — rollback-материал, остаётся на OLD (owner §8 «старый VPS сохранён для rollback»); активное состояние джобов (dossier_jobs) перенесено отдельно.
- `venv/` — пересоздан (не переносится по плану), закреплён до old-версий (§5).
- 43 шт. `.env.bak*`, 9 шт. `info_text.md.bak*`, `pre_migration_backup/`, `pre_migration_20261001_161834.db-journal` (осиротевший, INV §4), `test_subs.ru.json3`, `tools/_s41_precheck.py` — история/тест-мусор/локальные утилиты, в runtime на SHA не участвуют; остаются на OLD.
- `migrate_history/` (пуст), `var/` (пуст), `probes_full/` (2 файла 114 KB от 26.10, в коде ссылок нет) — не runtime-данные.
- `__pycache__/`, `id_ed25519_shared` — см. находки §10.

## 8. Отложено на CUT (финальный консистентный дельта-набор)

1. SQLite tail: записи после 00:12:52Z (снапшот pre-sync) — финальный backup API на остановленном/тихом боте, замена staging-копии.
2. PG tail: дельта после 00:14Z (llm_usage_events, uptime_events, image_reservation, worker_budget и т.п.) — финальный pg_dump + `--clean --if-exists` поверх pre-restore.
3. bot-api: `tqueue.binlog` (рос 31,748→40,688 B за INV→SYNC — очередь живёт) + файлы после 00:17Z; финальная копия при остановленном старом боте (запрет двойной обработки — последовательность «старый остановлен → перенос → старт нового»).
4. media/дельта после 00:15Z + финальный rsync (в т.ч. 59-й runtime-файл уже приехал; возможные новые).
5. Финальные byte-compare .env/xray/cookies и сравнение count'ов против финальных снапшотов (§6 owner-input).

## 9. Замер для честной оценки простоя CUT (REQ-RM-DOWNTIME-MEASURE)

Измеренные константы: SQLite backup API 1.55 GiB — 11.6 c (OLD 1 ядро); integrity_check — 115.9 c на OLD / 9.1 c на NEW; pg_dump 590 KB — 1 c; pg_restore — <1 c; провод VPS↔VPS — **≈54 MB/s** (1.67 GB за 29 c); bot-api 66 MB — 2 c. Оценка data-plane CUT: финальный снапшот 1.6–1.7 GB ≈ 30 c + дамп/рестор PG ≈ 2–3 c + дельта media/bot-api ≈ 3–5 c + integrity на NEW ≈ 10 c ≈ **50–90 c чистой передачи/проверки**; полный окно простоя дополнительно включает остановку старого бота, финальные проверки count'ов и старт нового (здесь не измерялось) — ориентир **≈5–10 минут**, не обещание. Все исходные числа зафиксированы в raw-логах.

## 10. Находки (incidental, вне среза; ничего не менялось)

1. **`id_ed25519_shared`** — приватный SSH-ключ (0640, 464 B) лежит в `/var/www/admin_bot` на OLD; gitignored, кодом не используется. Гигиенический риск на старой машине (решение владельца; на NEW не переносился).
2. **`.env` на OLD — 0664** (world-readable) + 43 копии `.env.bak*` в каталоге приложения. На NEW `.env` — 600 adminbot (осознанное улучшение). OLD не трогали.
3. `.env` строка 80 — одиночная «S» (§4) — косметика, поведение не меняет.
4. `probes_full/` — 2 файла-артефакта от 26.10, в коде не упоминаются; кандидаты на очистку (решение владельца/PM).
5. xray: deprecated gRPC-транспорт в конфиге (работает; «Configuration OK») — будущий переход на XHTTP, вне среза.
6. Подтверждён мотив миграции: OLD — 1 ядро/961 MB RAM (integrity 115.9 c против 9.1 c на NEW), 75% диска.

## 11. Соответствие строкам карты (9 строк slice SYNC)

| Req ID | Статус для PM-байнда | Evidence |
|---|---|---|
| REQ-RM-SYNC-IMMUTABLE | готово к VERIFIED | §2: rsync --partial без --delete по защищённому каналу; пути/права/владение сохранены (+осознанный chown-дельта adminbot-модели §2); размеры/количества/хэши/du old==new; набор без мусора, каждое отсутствие классифицировано §7 |
| REQ-RM-SYNC-SQLITE | готово к VERIFIED | §1, §3: backup API (не сырая копия WAL), integrity ok на копии на OLD и повторно на NEW, все факты MATCH |
| REQ-RM-SYNC-PG | готово к VERIFIED | §1, §3: pg_dump -Fc/pg_restore exit 0, 26 таблиц, 9/9 count MATCH, DSN-коннект OK; pre-restore зафиксирован и будет заменён финальным дампом на CUT (§8.2), сырого копирования volume не было |
| REQ-RM-SYNC-ENV-TLS | готово к VERIFIED | §4, §6: .env байт-в-байт (sha), значения не публиковались, IP-зависимостей нет (0 хитов) — правки не требовались, ничего не сброшено; caddy validate OK + не запущен, DNS не тронут; дубли ключей и «S» задокументированы |
| REQ-RM-SYNC-PREFLIGHT | готово к VERIFIED | §3, §5: sqlite-vec v0.1.9 OK, import bot с реальным .env OK, unit/systemd/dotenv проба §4, docker/PG health OK, media-права adminbot OK; polling/фоновые джобы не запускались; migrate_env_to_pg/импорт истории/пересборка эмбеддингов НЕ выполнялись |
| REQ-RM-DOWNTIME-MEASURE | готово к VERIFIED | §9: объёмы и скорость измерены (54 MB/s, все шаги), переносимый набор подготовлен, входные данные для расчёта простоя CUT зафиксированы |
| REQ-RM-PROHIB-REIMPORT | готово к VERIFIED | §5, §11-PREFLIGHT: migrate_env_to_pg/history import/embedding rebuild не запускались; существующие БД перенесены как есть (SQLite-факты и PG-каунты байт/число-в-число) |
| REQ-RM-PROHIB-MEMORY | готово к VERIFIED | §1, §3: память перенесена внутри local_database.db без изменений (121 таблица, user_version 37, все счётчики MATCH); политика хранения не менялась |
| REQ-RM-PROHIB-ADMINRESET | готово к VERIFIED | §3: настройки/роли/промпты восстановлены из реального дампа (bot_settings 544, chat_profiles 3, personas 2 — MATCH); ничего не обнулялось (--clean поверх placeholder, затем реальные данные) |

## 12. Raw-evidence и секрет-гигиена

`WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-92062bcd04/`: `mig_driver.py` (paramiko-драйвер: pacing ≥62 c, пароли только в памяти, санитизация), `scripts/*.sh`, `raw/raw_*.txt` (old_recon, old_main, old_sudo_xray, new_prep, old_transfer, new_verify, new_fix, new_pin_retry, old_cleanup, old_digest, new_final, new_revoke).
- Санитизация каждого raw-лога до записи: маскирование bot-token паттерна (в т.ч. имени каталога bot-api), DSN, литералов паролей из deploy_commands.txt; **контрольный скан sanitized-логов: 0 остатков** по всем 12 файлам (секрет-скан чист).
- Временный ed25519-ключ переноса: создан на OLD, отозван после верификации (OLD: приватный удалён + staging снят; NEW: строка из authorized_keys удалена, `AUTHKEY_LINES 1`, подстрока migration-sync-temp — 0 вхождений).
- В конечном состоянии NEW: staging `/var/lib/adminbot_migration/` (root 700) хранит pre-sync снапшот/дамп/фризы до CUT; прод-писатели на NEW отсутствуют.

**Итог slice SYNC:** предварительная синхронизация выполнена полностью и онлайн — SQLite/PG/.env/media/bot-api/xray/cookies/dossier/chrome/profile-наборы на NEW верифицированы (integrity, count, hash, digest, import, dotenv/systemd), venv закреплён под старый prod-набор, старый бот не прерывался ни на секунду. Блокеров нет; финальный консистентный дельта-набор и переключение — slice CUT.
