# PREP + GIT — новый VPS подготовлен (без запуска бота), Git-копия от точного SHA — slice PREP/GIT, release-then-migrate

**Дата:** 2026-10-28 23:45–23:52 UTC (сеансы; артефакт 2026-10-29).
**Исполнитель:** DevOps (subagent PREP+GIT).
**MIGRATION_SOURCE_SHA (заморожен, INV):** `5346ee765e83ee859596b60437811b21db1e4564` (build 2.58.141, ветка release/p0-2026-10-26).
**Цель:** root@192.255.209.205 (новый VPS, Ubuntu 24.04, 2CPU/3.8GiB/99G). **Бот на новом VPS НЕ запускался.** DNS не тронут. Данные не переносились (это SYNC).

## 0. Журнал SSH-сеансов (дисциплина)

| # | Время UTC | Цель | Длит. | Пауза от пред. |
|---|---|---|---|---|
| 1 | 23:45:37 | TOFU: fingerprint-эхо (`CONNECT_OK`, hostname, время) | ~2 c | — |
| 2 | 23:47:17–23:48:56 | Основной PREP+GIT прогон (1 соединение, скрипт через `bash -s`, 17 секций OK/FAIL) | 99 c | ~100 c |
| 3 | 23:50:16 | Remediation: pip-кэш, chown runtime-каталогов, preflight-ретрай | 6 c | ~80 c |
| 4 | 23:51:05 | Import-preflight финал (full `import bot`) | 6 c | ~45 c |
| 5 | 23:51:40 | Кросс-сессионная верификация состояний | 4 c | ~35 c |

- Все сеансы к НОВОМУ VPS; **старый сервер не подключался** (read-only, не требовался — INV-факты переиспользованы).
- Auth: только ключ `adminbot_vps` (BatchMode), single login, без ретраев/поллеров/параллели.
- TOFU: host key RSA `SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` — **совпал с INV-записью** (INV §10). Сверка с панелью Virtualizor — owner-side sanity-пункт, агентом не выполнялась (нет доступа к панели); зафиксировано как TOFU-сверка с INV-эталоном.
- Секрет-скан всех raw-логов: bot-token / PG-DSN / ghp / AKIA / password-присвоения — **0 совпадений** (плейсхолдер PG-пароля и фиктивный токен preflight в вывод не попадали).

## 1. Системная база (PREP-1)

| Параметр | Значение |
|---|---|
| ОС (по SSH, /etc/os-release) | Ubuntu 24.04 LTS (noble), 6.8.0-31-generic, x86_64 — переустановка не выполнялась |
| Hostname | vps159032-gqg |
| CPU / RAM / диск | 2 / 3916 MiB / 99G (после работ: used 11G, **free 84G** — запас ≫ переносимых ≈1.75–2.2 GB) |
| Timezone | Etc/UTC (совпадает со старым сервером, INV §1) |
| **Swap** | **4G /swapfile**, sw+fstab (старый: 3G swap при 1GiB RAM активно использовался; новый 3.8GiB без swap — закрыто) |
| Базовые пакеты | ca-certificates, curl, gnupg, **acl**, **ufw**, unzip, **python3-venv** (полный dist-upgrade сознательно не выполнялся — минимальная установка, свёртка не требуется) |
| UFW | active; default deny incoming / allow outgoing / **forward ACCEPT** (требование docker NAT); правила 22/tcp, 80/tcp (Caddy HTTP+redirect), 443/tcp; пост-проверка: контейнерный outbound `NAT_OK` (mirrors старую осанку «наружу только 22/443+80») |

## 2. Сервис-пользователь и дерево каталогов (PREP-2)

- `adminbot`: **uid=999, gid=987**, system user, shell `/usr/sbin/nologin`, home `/var/www/admin_bot`. **Приложение больше не от root — ключевая дельта нового окружения.**
- `/var/www/admin_bot` и дерево (код, venv, media, extra_images из клона; `backups/`, `chrome-profile/` созданы руками) — `adminbot:adminbot`.
- **`docker/telegram-bot-api`** (bind-mount бот-api): владелец **численно 101:101** (= внутренний пользователь `telegram-bot-api` образа `aiogram/telegram-bot-api:latest`; на обоих хостах эти номера отображаются как `messagebus:lxd` — совпадение имён как на старом VPS), режим **2775 (setgid)**, ACL:
  - access: `u:adminbot:r-x` (host-бот читает файлы bind-mount по `TELEGRAM_API_FILES_DIR`, см. compose-комментарий D263);
  - default: `u::rwx,g::---,o::---,m::rwx,u:adminbot:r-x` → новые файлы контейнера: владелец 101 rw-, adminbot r-- (чтение), группа/остальные — нет; new dirs: adminbot r-x. Компенсация прав root→сервис-юзер без расширения доступа «наружу».
  - ⚠ Для SYNC: перенос содержимого каталога сохранять с ACL (`rsync -A`/`tar --acls`) либо повторить `setfacl` после переноса.

## 3. Docker / compose (PREP-3)

- Docker Engine **29.9.2** + Compose plugin **v5.6.1** (официальный repo download.docker.com, noble), storage overlayfs, service active/enabled.
- Compose-файл — **штатный `docker-compose.yml` из клона на замороженном SHA** (байт-соответствие старому runtime; ничего не выдумывалось). Project name: `admin_bot` (дефолт по каталогу — тот же префикс, что на старом VPS; `name:` в файле не задан, явная фиксация не потребовалась).
- **Volume: `admin_bot_adminbot_pgdata`** — создан, имя **байт-в-байт совпадает со старым** (INV §6: compose-префикс, не «adminbot_pgdata»). Решение зафиксировано: явное имя не назначалось — дефолт проекта воспроизводит точное имя.
- Состояния (кросс-сессионно подтверждены):

| Контейнер | Образ | Состояние | Порты |
|---|---|---|---|
| adminbot-postgres | postgres:16-alpine | **Up (healthy)** — разрешённый не-конфликтующий aux | **только 127.0.0.1:5432** (docker-proxy) |
| adminbot-telegram-bot-api | aiogram/telegram-bot-api:latest | **Created (не запущен)** | (конфиг 127.0.0.1:8081, по факту не слушает) |
| adminbot-cobalt | ghcr.io/imputnet/cobalt:11 | **Created (не запущен)** | (host-net, API_LISTEN_ADDRESS=127.0.0.1:9000) |
| adminbot-bgutil-pot | brainicism/bgutil-ytdlp-pot-provider | **Created (не запущен)** | (host-net :4416, прикрывается ufw) |

- Env контейнеров: **временный `.env.prep`** (root:root 0600, git-ignored через `.env.*`) только с интерполяционными переменными compose; `POSTGRES_PASSWORD` — одноразовый `openssl rand`, **не печатался**; `TELEGRAM_*`, `COBALT_HTTP_PROXY` пустые. **Боевой `.env` (156 ключей, byte-exact с дублями) приходит на SYNC** — контейнеры bot-api/cobalt до SYNC не стартуют, поэтому плейсхолдер ни на что не влияет; на SYNC/cutover compose перезапускается от реального `.env`.
- **PG сейчас пустой, с одноразовым паролем** — это preflight-инстанс. На SYNC: восстановление финального дампа в согласованный volume при реальном `.env` (пересоздание пустого preflight-volume до загрузки боевых данных безопасно и не нарушает запрет `down -v` на боевых данных).
- Host-network зависимости уточнены: cobalt и bgutil — `network_mode: host` (по коммит-комментариям Epic 73/77: xray 127.0.0.1:10808 достижим только из host-стека; ports/extra_hosts при host-net не работают). Прокси-переменные (`COBALT_HTTP_PROXY` → `HTTP(S)_PROXY` cobalt) — значения приходят с `.env` на SYNC.
- Слушающие порты хоста: единственный `127.0.0.1:5432`. Наружу не светится ничего (80/443 — для Caddy на cutover, 22 — SSH).

## 4. Caddy (PREP-4)

- Установлен **caddy 2.11.7** (официальный repo cloudsmith). Caddyfile `/etc/caddy/Caddyfile` — **байт-близкая копия старого** (INV §8: домен admin-bot.duckdns.org → encode zstd gzip → handle /media/* → reverse_proxy 127.0.0.1:8000; 127 B): `caddy validate` — Valid configuration.
- **Решение: НЕ запущен и disabled** (`inactive`, `disabled`) — исключён ACME-гон с живым старым сервером на том же домене; финальный `enable+start` — на cutover.

## 5. Xray (PREP-2, «фактически используемые зависимости»)

- `/usr/local/bin/xray` — **Xray 26.10.21** (официальный release XTLS; старая версия INV не снималась — при SYNC сверить совместимость конфига, при несовместимости запиновать версию).
- Unit `/etc/systemd/system/xray.service` (ExecStart как на старом: `xray run -config /usr/local/etc/xray/config.json`, User=root — конфиг 0600 root-only на старом), **inactive + disabled**.
- **`/usr/local/etc/xray/config.json` отсутствует** — переносится с SYNC (секретный, root:root 0600; прокси 127.0.0.1:10808 для cobalt/yt-dlp поднимется вместе с ним).

## 6. systemd unit admin_bot (PREP-2)

`/etc/systemd/system/admin_bot.service` + drop-in `override.conf` (TimeoutStopSec=60) — шейп старого unit (INV §2), статусы: **inactive + disabled** (не стартовал ни разу):

```ini
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
```

**Зафиксированные инфра-дельты (осознанные, прикладная логика не менялась):**
1. **User: root → adminbot** (требование owner-input §3 «не запускать приложение от root»).
2. **+ EnvironmentFile=/var/www/admin_bot/.env** (по прямому заданию DevOps-срезa; на старом — нет, приложение грузит dotenv само). Семантика согласована: `config/settings.py` = `load_dotenv()` без override → process-env приоритетнее .env; дубль-ключи в .env: оба парсера берут последнее вхождение. ⚠ SYNC-пункт: после переноса реального .env сверить systemd-парсинг (`systemctl show -p Environment`) против dotenv-семантики на спец-значениях (`#` в значениях, кавычки) — при расхождении дельта устраняется (убрать EnvironmentFile) **до** cutover.
3. Строгий EnvironmentFile → unit не стартует без `.env` (файл появится на SYNC) — это желаемое fail-loud до cutover.
4. ACL на bot-api каталог (см. §2) — компенсация потери root-чтения.

**Производственные писатели/polling/фоновые задания на новом VPS:** отсутствуют (бот не стартовал; telegram-bot-api/cobalt/bgutil не запущены; postgres — разрешённый пустой aux; никаких cron/timers бота не создано).

## 7. Git (GIT-срез)

- `git ls-remote https://github.com/Henry-Case-dev/adminbot` **без кредов** работает и с нового VPS (репозиторий публичен для чтения) → **HTTPS-клон, deploy key НЕ требуется**, токенов/паролей в URL нет. Git 2.43.0.
- Клон `/var/www/admin_bot` (7020 файлов), затем `checkout --detach 5346ee765e83ee859596b60437811b21db1e4564`: `git rev-parse HEAD` == SHA (**SHA_MATCH_OK**), `git status -sb` = `## HEAD (no branch)` + чисто — detached-шейп зеркалит старый сервер (INV §3). Клон ≈ 502 MiB pack; plans/, media/ (58 tracked), extra_images/, info_text.md приходят кодом из SHA — это tracked-контент, НЕ замена переносу данных (SQLite/PG/.env/backups на SYNC не попали).
- **Цикл деплоя** (неинтерактивно, `GIT_TERMINAL_PROMPT=0`): `git fetch --prune origin` ✓; `git status -sb` ✓; `git rev-parse HEAD` ✓; `git pull --ff-only origin release/p0-2026-10-26` — исполнен: fast-forward `5346ee76..1f4fe81a` (удалённая ветка ушла вперёд ровно на один docs-коммит deploy-записи), затем `checkout --detach <SHA>` — **SHA_RESTORED_OK**, рабочая копия снова чистая на замороженном SHA.
  - Заметка: «голый» `git pull --ff-only` без refspec на detached HEAD отказывает (нет upstream) — это штатная семантика git; рабочий цикл DevOps = fetch + pull c явным refspec (как исполнено). На SWITCH checkout сознательно двигается на новый approved SHA по релизному гейту.
  - Host selector в непубличных деплой-командах/мониторинге — **не менялся** (область SWITCH, отложено по заданию); старый VPS не тронут, git-копия сохранена (rollback готов).
- Для root-операций git добавлен `safe.directory /var/www/admin_bot`; префлайт-git выполнялся от adminbot.

## 8. venv + import preflight (GIT-срез)

- venv: **`/var/www/admin_bot/venv`** (старая конвенция, INV §1; НЕ `.venv`), python 3.12.3, **pip 24.0** — точное зеркало старого. `pip install -r requirements.txt` от установленного venv **под пользователем adminbot** (проверка прав сервис-юзера), `pip check` — No broken requirements. Установлено (свежая резолюция в рамках диапазонов requirements): aiogram 3.31.0, aiosqlite 0.22.1, asyncpg 0.32.0, sqlite-vec 0.1.9, fastapi 0.162.0, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.13.5, aiohttp 3.14.5, yt-dlp 2026.10.26, playwright 1.64.1 (браузеры не ставились — не нужны до SYNC-решения), bgutil-ytdlp-pot-provider 2.0.2, sentry-sdk 2.64.0. Дрейф против старого venv минимальный (старый замораживался 2026-10-29) — ⚠ SYNC-пункт: сверить с `pip freeze` старого сервера.
- **Import preflight** (как adminbot, `ADMINBOT_SKIP_DOTENV=1` — .env до SYNC нет; ничего не запускалось: no polling, no network кроме pip):
  - `sqlite-vec`: `enable_load_extension` + `sqlite_vec.load` → **vec_version v0.1.9** (нативный модуль работает) ✓;
  - все обязательные библиотеки импортируются ✓ (aiogram, asyncpg, fastapi, uvicorn, yt_dlp, trafilatura, tiktoken, openai, duckduckgo_search, youtube_transcript_api, ijson, tqdm, psutil, apscheduler, sentry_sdk, aiohttp, httpx, pydantic, aiosqlite; bgutil-метаданные 2.0.2);
  - **`import bot` = IMPORT_BOT_OK** — полный граф приложения (config.settings, services.*, handlers.*, web.app) импортируется под сервис-юзером с фиктивным формат-валидным API_TOKEN (конструкция `Bot(token=...)` offline; реального токена до SYNC нет, сеть не дёргалась); побочные WARNING (betterstack disabled) — штатные без .env.
- Инцидент-история (мелкий, исправлен): первый preflight падал т.к. скрипт из /tmp не добавляет CWD в sys.path (ModuleNotFoundError: bot) — исправлено PYTHONPATH; module-level `Bot(token=settings.API_TOKEN)` требует формат-валидный токен даже на import — задокументировано. `backups/`+`chrome-profile/` первоначально создались root:root (после chown-фазы) — chown исправлен; pip-кэш `.cache/` (создан runuser-pip, HOME=repo) удалён; `git status` чист.

## 9. Соответствие строкам карты

| Req ID | Статус для PM-байнда | Evidence |
|---|---|---|
| REQ-RM-PREP-NO-REKEY (PREP) | готово к VERIFIED | §0–1: без переустановки/перегенерации ключа; тот же ключ принят с первой попытки; ОС проверена по SSH; панель-сверка = owner-sanity (TOFU-заметка) |
| REQ-RM-PREP-FINGERPRINT (PREP) | готово к VERIFIED (агентная часть) | §0: fingerprint == INV-эталон; §1: CPU/RAM/disk/arch; panel-side сверка — owner-sanity, агентом недоступна (честно не VERIFIED-её) |
| REQ-RM-PREP-USER (PREP) | готово к VERIFIED | §2, §5, §6: adminbot uid=999, не-root; git/python3.12+venv/docker+compose/caddy (+xray-скелет); пути/права/ACL/TZ; unit остановлен+disabled; писатели/polling/jobs отсутствуют |
| REQ-RM-PREP-DOCKER (PREP) | готово к VERIFIED | §3: loopback-бинды точные (5432/8081/9000 по compose); host-net зависимости + xray:10808 уточнены; стартован только postgres (пустой, healthy); двух pollers нет |
| REQ-RM-PROHIB-CLONE (GIT) | готово к VERIFIED | §7: клон = только код от точного SHA; перенос данных явно отнесён к §5–6 (SYNC) |
| REQ-RM-GIT-SHA-FREEZE (GIT) | уже VERIFIED | (существующие evidence deploy-old-vps.md, final-report-258141) |
| REQ-RM-GIT-OLD-HEAD (GIT) | готово к VERIFIED (переиспользование) | INV §3 (артефакт inventory-old-vps.md): HEAD старого == MIGRATION_SOURCE_SHA, detached, tracked-dirty нет, 13 untracked классифицированы — новых SSH к старому не требовалось |
| REQ-RM-GIT-NEW-CLONE (GIT) | готово к VERIFIED | §7: /var/www/admin_bot строго от SHA; origin Henry-Case-dev/adminbot HTTPS без кредов; публичный read без авторизации (deploy key не нужен) |
| REQ-RM-GIT-CYCLE (GIT) | готово к VERIFIED | §7: fetch/status/rev-parse/pull --ff-only неинтерактивны; заморозка восстановлена; host selector — SWITCH (отложено по заданию), старый VPS сохранён |

## 10. Отложенные на SYNC/SWITCH (handoff)

1. `.env` 156 ключей byte-exact (с дублями; значения TELEGrams/proxy читаются на месте) + systemd/dotenv parse-сверка (§6.2).
2. SQLite/PG/.env/media/bot-api каталог (66.3 MB, с ACL)/backups-решение/info_text/chrome-profile/extra_images-delta; TELEGRAM_API_FILES_DIR value проверить против фактического пути.
3. xray config.json (root 0600) + старт disabled→cutover; сверка версии xray.
4. cron `disk_retention` (на старом — nik, еженедельно): перенести под нового пользователя/расписание (решение PM/Architect).
5. PG: дамп→restore в согласованный volume от реального `.env` (preflight-volume заменить до боевых данных).
6. Caddy: enable+start на cutover (сейчас disabled); DNS/ACME — cutover.
7. Host selector деплой-команд/мониторинга → SWITCH.

## 11. Raw-evidence

`WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-63f9bb54ea/`:
- `prep_git_new_vps.sh` (основной скрипт, 17 секций), `prep_fix2.sh`, `preflight_final.sh`, `state_check.sh`;
- `raw_new_prep1.txt` (основной прогон; FAIL=1 только import-preflight sys.path — исправлен), `raw_new_fix2.txt`, `raw_preflight_final.txt` (IMPORT_BOT_OK), `raw_state_check.txt` (кросс-сессионные состояния);
- секрет-скан raw-логов: 0 совпадений (bot-token/DSN/ghp/AKIA/password-присвоения; плейсхолдер PG-пароля и фиктивный токен не печатались).

**Итог срезов:** PREP выполнен полностью (система, юзер, docker-compose точного шейпа с пустым healthy-postgres, caddy установлен/выключен, xray-скелет, unit adminbot-ownership остановлен+disabled, без писателей/polling); GIT выполнен полностью (точный SHA, origin без секретов, цикл fetch+pull --ff-only доказан неинтерактивно, заморозка восстановлена). Блокеров нет. Бот на новом VPS не запускался; DNS/данные не тронуты.
