# Inventory — OLD VPS (read-only) + NEW VPS readiness (read-only) — slice INV, release-then-migrate

**Дата:** 2026-10-28 23:19–23:27 UTC. **Исполнитель:** DevOps (subagent INV).
**MIGRATION_SOURCE_SHA (заморожен):** `5346ee765e83ee859596b60437811b21db1e4564` (build 2.58.141, ветка release/p0-2026-10-26).
**Режим:** строго read-only на обоих серверах. Изменений данных/конфигурации не выполнено.
**Приоритет источников (REQ-RM-SOURCE-PRIORITY):** прочитаны AGENTS.md, owner-input §0–§2, карта требований; наблюдаемый production и его фактические файлы имеют приоритет над Git/README/предположениями.

## 0. SSH-журнал сеансов (fail2ban-безопасный паттерн)

| # | Время (UTC) | Хост | Цель | Пауза от пред. | Auth |
|---|---|---|---|---|---|
| 1 | 23:19:07 | nik@198.46.175.136 | recon, таймаут 15 с | — | пароль из локального deploy_commands.txt (в памяти процесса) |
| 2 | 23:20:23 | nik@198.46.175.136 | основной инвентаризационный прогон (1 соединение, `bash -s`) | ~76 с | тот же, single auth, без ретраев |
| 3 | 23:23:47 | nik@198.46.175.136 | докаптура: .env имена ключей, Caddy, PG-имена, bot-api | ~3 м 24 с | тот же |
| 4 | 23:26:37 | root@192.255.209.205 | readiness нового VPS (1 короткий сеанс) | ~2 м 50 с (другой хост) | ключ adminbot_vps, без пароля |

- Параллельных коннектов нет, повторов auth нет, поллеров нет, перебора кредов нет.
- Статус старого прода дополнительно проверен по HTTP (не SSH): внешний `https://admin-bot.duckdns.org/healthz` → **200** `{"status":"ok","version":"2.58.141"}`; админка `/` → 307 (редирект на вход — штатно).
- Пароли/токены в командах/логах/артефакте не печатаются; парсинг кредов — из непубличного локального файла, значения остаются в памяти процесса.

## 1. Старый VPS — система и ресурсы (REQ-RM-INV-SYSTEM)

| Параметр | Значение |
|---|---|
| ОС | Ubuntu 24.04.4 LTS (ID=ubuntu, VERSION_ID=24.04) |
| Ядро / арх | 6.8.0-147-generic, x86_64 |
| Uptime / load | 3 д 9 ч, load 0.07–0.09 |
| Часовой пояс | Etc/UTC (системное время = UTC) |
| CPU | **1** ядро |
| RAM | 961 MiB total, available 422 MiB; **swap 3 GiB, использован 1.5 GiB** |
| Диск | /dev/vda2 **24G**, used 17G, **free 5.8G (75%)** |
| Python (system) | 3.12.3 |
| Python (venv) | /var/www/admin_bot/venv/bin/python 3.12.3, pip 24.0 |
| Ключевые пакеты venv | aiogram 3.31.0, aiosqlite 0.22.1, asyncpg 0.31.0, sqlite-vec 0.1.9, fastapi 0.141.1, uvicorn 0.52.4, httpx 0.28.1, pydantic 2.13.4, aiohttp 3.14.1 |
| Здоровье | локальный healthz 200 `{"status":"ok","version":"2.58.141"}`; journal 24 ч: **0** Traceback/ERROR |

## 2. systemd / cron / процессы (REQ-RM-INV-SYSTEMD)

`systemctl cat admin_bot`:

```ini
# /etc/systemd/system/admin_bot.service
[Service]
Type=simple
User=root
WorkingDirectory=/var/www/admin_bot
ExecStart=/var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py
Restart=always
RestartSec=5
# override.conf: TimeoutStopSec=60
```

- **EnvironmentFile отсутствует** → окружение загружает приложение из `/var/www/admin_bot/.env` (файл 8121 B, mtime 2026-10-17 21:54, nik:developers).
- Процесс: **root** (важно для PREP: создавать то же владение или осознанно сменить пользователя с проверкой прав).
- Состояние: active/running, MainPID 959071, NRestarts=0, старт 2026-10-28 22:35:17 UTC (рестарт релиза 2.58.141).
- Смежные сервисы: `caddy.service` active, `docker.service` active, `xray.service` active; nginx не установлен/неактивен.
- Cron (nik): `30 6 * * 1` — еженедельный `tools/disk_retention.py` (лог `/home/nik/adminbot-disk-retention.log`). `/etc/cron.d` — только штатный sysstat/e2scrub.
- Таймеры systemd — только штатные системные (apt/logrotate/sysstat/fstrim и т.п.), бот-таймеров нет.
- Отдельных worker/scheduler-сервисов нет: workers/scheduler — внутри единственного процесса admin_bot (подтверждено деплой-артефактом 2.58.141: scheduler тикает, VisionMediaWorker и т.д.).

## 3. Git на старом VPS (REQ-RM-INV-GIT)

| Параметр | Значение |
|---|---|
| HEAD | `5346ee765e83ee859596b60437811b21db1e4564` — **MATCH с MIGRATION_SOURCE_SHA** ✅ |
| Commit | bump 2.58.140 → 2.58.141, дата 2026-10-29 10:32:06 +1200 |
| Ветка / upstream | **detached HEAD** («HEAD does not point to a branch»), upstream нет |
| remote origin | `https://github.com/Henry-Case-dev/adminbot.git` (без встроенных кредов) |
| `git describe` | pre-asap2-2.58.33-1101-g5346ee76 |
| `git status --porcelain` | **13 строк, все untracked (`??`), tracked-изменений НЕТ** |

Untracked (классификация, ничего не удалять):
- `info_text.md.bak.epic44/55/56/57/58/59/71/83`, `info_text.md.pre1015.drift.bak` — 9 бэкап-копий info_text (история правок; решить при SYNC, текущий рабочий файл — `info_text.md`, tracked).
- `pre_migration_20261001_161834.db-journal` — **осиротевший journal от 01.10** без соответствующего .db (не живое состояние).
- `pre_migration_backup/` — 2.9 MB (pre-migration артефакты 01.10).
- `test_subs.ru.json3` — 400 KB тестовые данные.
- `tools/_s41_precheck.py` — локальный сервисный скрипт.

## 4. SQLite — фактические пути (REQ-RM-INV-SQLITE)

| Файл | Размер | Примечание |
|---|---|---|
| `/var/www/admin_bot/local_database.db` | **1,669,767,168 B (1.55 GiB)** | основная БД; `DB_PATH=local_database.db` (относительный) |
| `local_database.db-wal` | 4,177,712 B (4.0 MB) | **WAL-режим активен** (checkpoint-ключи: DB_WAL_CHECKPOINT_ENABLED/HOURS) |
| `local_database.db-shm` | 32,768 B | — |
| `backups/local_database_20261028.db` | 1,591,263,232 B (1.48 GiB) | ежедневный бэкап 00:00 UTC 28.10 (генерит приложение) |
| `pre_migration_20261001_161834.db-journal` | (untracked) | осиротевший journal, не живое состояние |

- Дополнительных .db (L1/L2/graph/aliases/embeddings/summary/initiative) **отдельными файлами НЕТ** (поиск maxdepth 5) — все memory-состояния внутри `local_database.db` (таблицы), GraphRAG/embeddings — тоже (sqlite-vec в venv). Опираться на дефолты .env.example не требовалось — фактический поиск файлов выполнен.
- `chrome-profile/Default/declarative_performance_observer.db` (32 KB) — артефакт Chromium-профиля (см. §7).

## 5. PostgreSQL (REQ-RM-INV-PG)

| Параметр | Значение |
|---|---|
| Контейнер | `adminbot-postgres`, образ `postgres:16-alpine`, фактическая версия **PostgreSQL 16.15**, Up 3 days (healthy) |
| Порт | только 127.0.0.1:5432 → контейнер 5432 (docker-proxy) |
| Имена (не секреты) | `POSTGRES_USER=adminbot`, `POSTGRES_DB=adminbot`; `POSTGRES_DSN`/`POSTGRES_PASSWORD` существуют в .env — **значения не печатаются** |
| Базы | `adminbot` — **16 MB**, `postgres` — 7.3 MB |
| Крупнейшие таблицы (public) | llm_usage_events 3.5 MB, chat_lore_history 1.4 MB, uptime_events 680 KB, bot_settings 504 KB, chat_profiles 264 KB, anticliche_cache 152 KB, persona_traits 120 KB, cover_style_provenance 104 KB, worker_budget 104 KB, bot_settings_bak_20260903 88 KB, cover_style_issue_assignments 80 KB, chat_usage 72 KB, persona_state 64 KB, image_reservation 64 KB, personas 64 KB |
| Параметры процесса | max_connections=50, shared_buffers=128MB; 3 idle-соединения приложения с 172.18.0.1 |
| Содержимое | настройки админки, роли, промпты, состояние (bot_settings, chat_profiles, personas и т.д.) — перенос обязательно дампом (pg_dump -Fc), не сырым volume |

## 6. Docker / compose (REQ-RM-INV-DOCKER)

- Файл: `/var/www/admin_bot/docker-compose.yml` (7311 B, mtime 2026-09-20).
- `docker compose config --services`: `bgutil-ytdlp-pot-provider`, `cobalt`, `postgres`, `telegram-bot-api` — все 4 запущены, Up 3 days.

| Контейнер | Образ | Состояние | Порты |
|---|---|---|---|
| adminbot-telegram-bot-api | aiogram/telegram-bot-api:latest | Up 3 days (healthy) | 127.0.0.1:8081→8081 |
| adminbot-postgres | postgres:16-alpine | Up 3 days (healthy) | 127.0.0.1:5432→5432 |
| adminbot-cobalt | ghcr.io/imputnet/cobalt:11 | Up 3 days (healthy) | (без published-портов) |
| adminbot-bgutil-pot | brainicism/bgutil-ytdlp-pot-provider | Up 3 days | (без published-портов) |

- Volume: **`admin_bot_adminbot_pgdata`** (compose-префикс! не «adminbot_pgdata»), Mountpoint в /var/lib/docker/volumes/...; локальные volumes всего 1, суммарно **73.51 MB**; images 1.39 GB; build cache 0.
- Bind mount `docker/telegram-bot-api` (host, 44 KB видимых nik-файлов) → `/var/lib/telegram-bot-api` в контейнере; **внутри контейнера 66.3 MB** (файлы локального Bot API + `tqueue.binlog` 31,748 B активный; `webhooks_db.binlog` пуст). Каталог хост-сайта принадлежит `messagebus:lxd` с правами 2750/600 — **из-под nik не читается** (UID/GID нужно сохранить при переносе).
- Использование диска docker: /var/lib/docker в составе 17G used на 24G диске.

## 7. Переносимая конфигурация/медиа (REQ-RM-INV-FILES)

Размеры `/var/www/admin_bot` (итого **4.6 GB**):

| Каталог/файл | Размер | Класс |
|---|---|---|
| local_database.db (+WAL/SHM) | 1.6 GB | **обязательный** (SQLite backup API) |
| backups/ (11 файлов, вкл. dossier_jobs 6 файлов) | 1.5 GB | rollback-материал;_latest daily 1.5G — решение SYNC |
| plans/ | 413 MB | workflow-документация, не runtime; решение PM/Architect |
| venv/ | 404 MB | не переносить — пересоздать (pip freeze зафиксировать при SYNC) |
| media/ | **96 MB, 59 файлов** | обязательный |
| docker/telegram-bot-api (внутри контейнера 66.3 MB) | 66.3 MB | **обязательный** (file_path ссылки + очередь обновлений) |
| tests/ 25 MB, services/ 24 MB, web/ 5.9 MB, tools/ 5.5 MB, SmartModule, handlers, filters, config, scripts, docs | ~65 MB | код = git @ SHA |
| chrome-profile/ | 5.0 MB | Chromium-профиль (yt/vision пайплайн); классифицировать при SYNC |
| extra_images/ | 2.9 MB | контент — переносить |
| pre_migration_backup/ | 2.9 MB | legacy от 01.10 |
| info_text.md | 20,900 B | обязательный (tracked) |
| .env | 8,121 B | **обязательный**, перенос как есть (значения не публиковать) |

- `.env`: **156 ключей** (фактических; полный список имён — в raw-логе). Сверка с .env.example (184 ключа): 35 серверных ключей отсутствуют в example (TELEGRAM_LOCAL, POSTGRES_USER/DB, LLM_FALLBACK_*, CHECKUP_BETTERSTACK_SQL_*, YOUTUBE_TRANSCRIPT_PROXY_*, YTDLP_POT_PROVIDER, UNIFIED_COMPOSER_ENABLED, EMBED_CACHE_MAX_ROWS и др.) и ~70 example-ключей на сервере не заданы (действуют дефолты кода). **Вывод: .env.example не является надёжным источником — переносить фактический .env целиком.**
- Секреты по именам (значения не раскрыты): API_TOKEN, LLM_API_KEY, LLM_FALLBACK_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, EXA_API_KEY, TAVILY_API_KEY, IMAGE_API_KEY, EMBEDDING_FALLBACK_API_KEY(_2), POSTGRES_PASSWORD, POSTGRES_DSN, SENTRY_DSN, LOGTAIL_SOURCE_TOKEN, CHECKUP_BETTERSTACK_SQL_PASSWORD, TELEGRAM_API_ID/HASH, YOUTUBE_TRANSCRIPT_PROXY_USERNAME/PASSWORD, YOUTUBE_COOKIES_FILE (путь к cookies).
- Hot config — из PG (bot_settings/personas/промпты), отдельных hot-файлов не зафиксировано.
- TELEGRAM_API_FILES_DIR — ключ присутствует (значение — путь; считается при SYNC/PREP).

## 8. Сеть / прокси / TLS (REQ-RM-INV-NETWORK)

- Домен админки/медиа: **admin-bot.duckdns.org** → Caddy → reverse_proxy 127.0.0.1:8000 (приложение uvicorn; `/media/*` тоже на :8000). Публичный паттерн медиа: `https://admin-bot.duckdns.org/media/...`.
- Caddyfile `/etc/caddy/Caddyfile` (127 B) — auto-HTTPS (certbot не используется); бэкапы Caddyfile.bak.round3 / .pre1016.bak.
- xray.service active: `/usr/local/bin/xray run -config /usr/local/etc/xray/config.json`; конфиг root:root 0600 (1515 B, +2 бэкапа) — содержит секреты, переносить под root-only. Прокси-переменные (COBALT_HTTP_PROXY, YOUTUBE_TRANSCRIPT_PROXY_*) — **только имена**, значения не печатались (ожидание из owner-дока: локальный прокси 127.0.0.1:10808).
- Режим приёма: **polling** (aiogram `dp.start_polling`), webhook НЕ используется (`webhooks_db.binlog` пуст); **TELEGRAM_LOCAL=1** — локальный Bot API на 127.0.0.1:8081 (LOCAL_BOT_API_URL), большие файлы до 2000 MB через него.
- Слушающие порты: приложение 127.0.0.1:8000 (uvicorn/healthz), 127.0.0.1:8081 (bot-api), 127.0.0.1:5432 (PG), 443 Caddy (публично), xray-порт (конфиг 0600). Утилита ss/netstat на хосте отсутствовала — порты подтверждены docker-proxy-процессами и Caddyfile.

## 9. Jobs / очереди / offsets (REQ-RM-INV-JOBS)

- Scheduler/workers — внутри процесса admin_bot (единственный ExecStart); отдельные таймеры/кроме еженедельного disk_retention cron — нет.
- Ежедневные артефакты приложения в 00:00 UTC: `backups/local_database_YYYYMMDD.db` (1.5 GB) и `backups/facts_YYYYMMDD.txt` (4.4 MB) — штатный механизм бэкапа/фактов; retention чистит еженедельный cron.
- Telegram offset: aiogram polling — offset в памяти процесса; **необработанная очередь хранится в локальном Bot API** (`tqueue.binlog`, активный, 31.7 KB) → при cutover перенос каталога bot-api сохраняет неконсьюмленные обновления; webhooks нет. Риск двойной обработки минимизируется строгой последовательностью «старый остановлен → перенесён бот-api каталог → новый стартует».
- Pending jobs: `backups/dossier_jobs/dossier_rebuild_jobs.json` + rollback/cancelled jsonl (6 файлов) — state dossier-джобов; таблицы PG (image_reservation, worker_budget) и SQLite содержат активное состояние — переносить консистентным снапшотом.

## 10. Новый VPS — readiness (read-only, root@192.255.209.205)

| Параметр | Значение |
|---|---|
| ОС | **Ubuntu 24.04 LTS (Noble)** — соответствует предпочтению owner-input §3 ✅ (без переустановки; Rebuilding/SSH Keys/VPS Start = Completed согласуются с фактом) |
| Ядро / арх | 6.8.0-31-generic, x86_64 |
| Uptime | ~7 ч (свежая установка) |
| CPU / RAM | **2** ядра, 3.8 GiB total (3.4 GiB available), **swap отсутствует (0 B)** |
| Диск | /dev/vda1 **99G**, used 2.4G, **free 91G (3%)** |
| Python | python3 3.12.3 присутствует |
| Git | 2.43.0 присутствует |
| Docker / nginx / caddy | **отсутствуют** (установка в slice PREP) |
| /var/www | отсутствует |
| SSH auth | ключ `adminbot_vps` работает, root, без пароля ✅ (ключ не перегенерировался) |
| Host key fingerprint | ssh-rsa `SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` — сверить с панелью Virtualizor (обязательство REQ-RM-PREP-FINGERPRINT, slice PREP) |
| Часовой пояс | Etc/UTC |

Заметки на PREP: добавить swap (старый сервер активно использует 1.5/3 GiB swap при 961 MiB RAM; новый без swap при 3.8 GiB — запас есть, но swap малой стоимости полезен), установить Docker/Compose, Caddy, создать deploy-пользователя с UID/GID под существующие права (developers/lxd/messagebus-мэппинги для bot-api каталога).

## 11. Замер объёмов для §5 SYNC и оценки простоя

| Набор | Размер |
|---|---|
| Обязательный runtime-набор (SQLite-снапшот ~1.56 GiB + media 96 MB + bot-api store 66.3 MB + .env/info_text/extra_images/docker-конфиги) | **≈ 1.75 GB** |
| PG дамп (база 16 MB; volume 73.5 MB) | ~0.02–0.07 GB |
| Опционально: последний daily-бэкап (rollback-материал) | +1.5 GB |
| Опционально: plans/ (413 MB), chrome-profile (5 MB), pre_migration_backup (2.9 MB) | +0.42 GB |
| venv (пересоздание, не перенос) | 0 (pip-фаза) |
| Docker-образы (re-pull) | ~1.4 GB (не входит в перенос данных) |

Свободно на новом VPS 91 GB — запас многократный. Оценка времени простоя: финальная дельта = SQLite-снапшот (backup API ~1.6 GB копия на месте + передача) + PG дамп (~ десятки MB) + delta media/bot-api; узкое место — передача ~1.6–1.8 GB по SSH (точную скорость замерит SYNC на первой передаче).

## 12. Соответствие строкам карты (13 строк slice INV)

| Req ID | Находка / evidence |
|---|---|
| REQ-RM-INV-SYSTEM | §1 (оба VPS: ОС/arch/python/CPU/RAM/disk) + §10 |
| REQ-RM-INV-SYSTEMD | §2 (unit cat/show, root, без EnvironmentFile, cron/timers, процесс-состав) |
| REQ-RM-INV-GIT | §3 (HEAD == MIGRATION_SOURCE_SHA, detached, 13 untracked, remote чист) |
| REQ-RM-INV-SQLITE | §4 (DB_PATH=local_database.db, WAL/SHM, 1.55 GiB, отдельные memory-файлов нет, осиротевший journal) |
| REQ-RM-INV-PG | §5 (USER/DB имена, 16.15, базы/таблицы/размеры, volume 73.5 MB, DSN не раскрыт) |
| REQ-RM-INV-DOCKER | §6 (4 сервиса, все healthy, volume `admin_bot_adminbot_pgdata`, bind mount bot-api 66.3 MB) |
| REQ-RM-INV-FILES | §7 (.env 156 ключей имён, медиа/аватары/промпты/info_text/cookies/dossier_jobs, класс regenerable) |
| REQ-RM-INV-NETWORK | §8 (домен, Caddy, TLS auto, polling vs webhook, TELEGRAM_LOCAL, порты, xray, прокси-имена) |
| REQ-RM-INV-JOBS | §9 (scheduler в процессе, daily-бэкапы 00:00, tqueue.binlog, dossier jobs, риск-механика offsets) |
| REQ-RM-INV-READONLY | §0 + весь документ: только read-команды, 4 коннекта ≥60 с между, recon 15 с, без ретраев/параллели; сервис жив (healthz 200 в течение и после) |
| REQ-RM-INV-SECRETS | значения секретов не напечатаны (только имена/размеры/состояния); на сервере ничего не изменено; инцидент: имя каталога bot-api содержит токен — из raw-лога замаскировано на месте (см. §13) |
| REQ-RM-SECRETS-DEPLOY | креды только из локального deploy_commands.txt, в память процесса; в код/AGENTS.md/plans/отчёты/git не записаны; remote без кредов; репо не изменено |
| REQ-RM-SOURCE-PRIORITY | прочитаны AGENTS.md (fail2ban/PET_PROJECT правила), owner-input, карта; выводы по факту сервера (напр., unit без EnvironmentFile, volume с compose-префиксом — против «дефолтов») |

## 13. Аномалии / риски / находки

1. **Хорошее:** HEAD == MIGRATION_SOURCE_SHA (совпадение подтверждено на живом сервере), tracked-дirty нет, journal 24 ч без ошибок, NRestarts=0.
2. **Unit от root, без EnvironmentFile** — при PREP сохранить модель (root) или осознанно сменить с проверкой прав на .env/media/DB/chrome-profile.
3. **Volume называется `admin_bot_adminbot_pgdata`** (compose-префикс) — не «adminbot_pgdata» из owner-дока; в compose нового сервера учесть точное имя/префикс.
4. **Bind-mount bot-api читается только контейнером** (host: messagebus:lxd 2750) — при rsync под другим пользователем права/UID не сохранить автоматически; нужен tar/чтение из контейнера или root-канал.
5. **Осиротевший `pre_migration_20261001_161834.db-journal`** + pre_migration_backup/ от 01.10 — не живое состояние; не удалять в фазе INV (решение SYNC).
6. **bot_settings_bak_20260903** (таблица-бэкап в PG) — перенесётся с дампом автоматически; не «чистить».
7. **Старый сервер: 75% диска, swap наполовину занят** — подтверждает мотив миграции; на новом добавить swap.
8. **tqueue.binlog активен** — перенос каталога bot-api обязателен для сохранения неконсьюмленных Telegram-обновлений и file_path (66.3 MB).
9. **.env содержит дубли ключей** (напр., CHAT_GLOBAL_CONTEXT_LIMIT, CHECKUP_MAX_INPUT_SYMBOLS, SEARCH_MAX_SYMBOLS, YOUTUBE_TRANSCRIPT_PROXY_* дважды) — при переносе «как есть» поведение определено последним вхождением dotenv; сохранять байт-в-байт.
10. TELEGRAM_API_FILES_DIR, COBALT_HTTP_PROXY, YOUTUBE_TRANSCRIPT_PROXY_URL — значения не снимались (по контракту INV имена); читаются при SYNC/PREP из .env напрямую.

## 14. Raw-evidence

Скрипты и очищенные raw-выводы: `WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-af821b7ae8/`
- `recon_old.py`, `inv_old.py` → `raw_old.txt` (10.7 KB, все секции до DONE),
- `inv_old2.py` → `raw_old2.txt` (8.2 KB; токен из имени каталога bot-api замаскирован на месте `***REDACTED_BOT_TOKEN***`, повторная проверка паттернов: 0),
- `nvps_check.py` → `raw_new.txt`,
- секрет-скан: token-pattern 0, plain-DSN 0 в обоих raw-файлах.

**Итог slice INV:** инвентаризация завершена полностью (все разделы §2 owner-input), SHA-match подтверждён, оба сервера зафиксированы read-only, готовые факты для PREP/GIT/SYNC-дизайна собраны. Блокеров нет.
