# VISION-DL-FIX — скачивание файлов локального Bot API (ACCEPTANCE-92C)

Срез закрывает находку приёмки 2.58.92: **все vision-джобы умирали на
`stage=download`** (`64 skipped + 32 failed`, `mca_media_analyses` пуст) при
`AiohttpSession(TelegramAPIServer.from_base("http://localhost:8081",
is_local=True))` и `DOWNLOAD_ENABLED=true`.

База: HEAD `b33c0c47` (master), правки без коммита — на ревью.
Файлы: `bot.py` (f9d8306e6034), `services/local_bot_api.py` (**новый**,
a97e1d3eeab0), `tests/test_vision_dl_fix.py` (**новый**, ac618a776c53).
`services/mca_vision.py` (f8cb004c6c84) и `web/api/routes.py` (d54cc29695c7)
**не менялись** — фикс на уровне сессии/конфига.

## 1. Где именно ломалось (прод-факты, read-only, 2 коннекта)

Диагностика: `harness/vision_dl_diag.py` → `prod-diag-2026-10-19.json`;
живая проба путей: `harness/vision_dl_probe.py` → `prod-probe-2026-10-19.json`.

| Факт | Значение |
|---|---|
| Бот | systemd `admin_bot`, `User=root`, `WorkingDirectory=/var/www/admin_bot`, `venv/bin/python bot.py` (на хосте, не в контейнере) |
| Bot API | контейнер `adminbot-telegram-bot-api` (`aiogram/telegram-bot-api:latest`, **Bot API 10.3**), `TELEGRAM_LOCAL=1`, `TELEGRAM_WORK_DIR=/var/lib/telegram-bot-api` |
| Том | `docker inspect`: `/var/www/admin_bot/docker/telegram-bot-api => /var/lib/telegram-bot-api` (bind-source на хосте = `TELEGRAM_API_FILES_DIR`) |
| `/var/lib/telegram-bot-api` **на хосте** | отсутствует (каталог существует только в контейнере) — ровно то, что видел harness |
| aiogram (прод и локально) | **3.31.0** |
| `.env` | `LOCAL_BOT_API_URL=http://localhost:8081`, `TELEGRAM_API_FILES_DIR=docker/telegram-bot-api`, `DOWNLOAD_ENABLED=True`, `TELEGRAM_LOCAL=1` |
| `getMe` (локальная база) | HTTP 200 — сервер жив, токен валиден |
| `/file/bot<token>/<абс. контейнерный путь>` | **404** |
| `/file/bot<token>/photos/file_1317.jpg` (относительный) | **404** |
| `/file/bot<token>/<host-эквивалент>` | **404** |
| A) текущая сессия (`is_local=True`, путь контейнера) | `file_path=/var/lib/telegram-bot-api/<token>/photos/file_1317.jpg`, `exists=false`, `FileNotFoundError` |
| C) облачная сессия (контроль) | 54 960 байт — файл доступен |

**Механизм**: локальный Bot API (`--local`) отдаёт в `getFile` АБСОЛЮТНЫЙ путь
ВНУТРИ СВОЕГО КОНТЕЙНЕРА (документировано:
core.telegram.org/bots/api#using-a-local-bot-api-server; в исходнике
tdlib/telegram-bot-api `Client.cpp::json_store_file`: в `local_mode_` пишется
`file->local_->path_`, в облачном режиме — относительный путь). aiogram при
`is_local=True` читает этот путь с ФС **хоста бота**
(`Bot.download_file` → `wrap_local_file.to_local(...)` → `aiofiles`) → на хосте
каталога нет → `FileNotFoundError` → `stage=download` (все vision-джобы).
HTTP-скачивание локального сервера в `--local` **не обслуживается** (три 404
выше; то же подтверждает README aiogram/telegram-bot-api: «local mode doesn't
provide possibility to download files from API»).

## 2. Выбранный путь (код + конфиг, без облака)

1. **`services/local_bot_api.py`** — фабрика сессии `build_local_api_session`:
   `is_local=True` (чтение ФС, трафик не уходит в облако) + обёртка
   `HostFilesPathWrapper` — маппинг `/var/lib/telegram-bot-api/<...>` →
   `<TELEGRAM_API_FILES_DIR>/<...>` (та же нормализация, что уже
   прод-проверена для голосовых/видео в `services/media_download.py`).
   Обёртка **fail-safe**: относительный/чужой абсолютный/сам корень
   возвращаются как есть, без `ValueError` (в отличие от aiogram-овского
   `SimpleFilesPathWrapper`, который падает на `relative_to`).
2. **`bot.py`** — локальный режим собирается этой фабрикой
   (`build_local_api_session(settings.LOCAL_BOT_API_URL)`); прямые импорты
   `AiohttpSession`/`TelegramAPIServer` из bot.py убраны.
3. **Стартовая диагностика**: если host-каталог не читается — WARNING с путём
   (R17-safe, без токена) и прежнее поведение; если читается — INFO.
4. API-вызовы не меняются (та же локальная база), облачный режим
   (`DOWNLOAD_ENABLED=false`) — прежний `Bot(token=...)` без локальной сессии.
   `SafeFetcher`/внешние URL не затрагивались; R17: токен нигде не логируется
   (путь с `<bot_id>:<token>` наружу не выводится).

### Инфра-вариант (альтернатива/подстраховка, без кода)

Если по какой-то причине host-каталог окажется недоступен процессу бота
(например, бот будет запущен не под root и вне группы владельца каталога):

* проверить, что bind-mount виден: `ls -ld /var/www/admin_bot/docker/telegram-bot-api`
  (прод: `drwxrwsr-x messagebus:lxd`);
* при отказе прав — `chmod g+rX`/`chown` каталога или добавить пользователя
  бота в группу владельца (`usermod -aG <group> <botuser>`);
* либо «симлинк»-вариант: `ln -s /var/www/admin_bot/docker/telegram-bot-api
  /var/lib/telegram-bot-api` (тогда контейнерный путь резолвится на хосте
  и без маппинга в коде — но это host-level изменение, требующее root).

HTTP-вариант (nginx-reverse-proxy, отдающий каталог на `/file/bot<token>/…`)
возможен как отдельный инфра-контур (пример: aiogram/telegram-bot-api
`example/nginx`), но в этом срезе не нужен: файл доступен по ФС.

## 3. RED → GREEN

* **RED (прод, живая проба)**: `prod-probe-2026-10-19.json` — «A) текущая
  сессия»: `exists=false`, `FileNotFoundError`; «B) фикс-кандидат»
  (`SimpleFilesPathWrapper(container → host)`): в пробе упал на
  `PermissionError`, потому что проба запускалась SSH-пользователем `nik`, а
  каталог принадлежит `messagebus:lxd` (бот работает под **root** и читает
  его — этот же каталог уже используется прод-путём голосовых/видео).
* **RED (код, локально)**: `red-2026-10-19.txt` — при откаченном `bot.py`
  падает конфиг-инвариант (`1 failed`); прод-симптом воспроизводится в самом
  тесте `test_download_reads_host_path_not_container_path` веткой «без
  маппинга» → `FileNotFoundError`.
* **GREEN**: `green-2026-10-19.txt` — 7 passed:
  1. конфиг-инвариант (локальная база, `is_local=True`, маппинг
     `<bot_id>:<token>` → host-каталог, обратный маппинг);
  2. fail-safe обёртки на неожиданных путях;
  3. **контракт на реальном aiogram**: `Bot.download_file` читает host-файл по
     контейнерному `file_path` (байты совпадают), без маппинга —
     `FileNotFoundError`;
  4. резолв относительного `TELEGRAM_API_FILES_DIR` от каталога приложения;
  5. диагностика читаемости каталога;
  6. конфиг-инвариант `bot.py` (сессия только через фабрику);
  7. **интеграционный (bounded, локально)**: aiohttp-стаб локального Bot API —
     `getFile` POST по локальной базе отдаёт абсолютный контейнерный путь,
     сессия читает файл из host-каталога; HTTP `/file/bot…` → 404.
* **Профильный свод**: `sweep-2026-10-19.txt` — 195 passed (vision core +
  mca19 A–G + rework + addtr_postgen); media/download/voice/video/avatars —
  264 passed.

## 4. Что останется на выкат/приёмку

1. Деплой (штатный): правка конфигурации сессии + новый модуль; перезапуск
   бота — после него в журнале ждать `[local-bot-api] файлы: … (container
   /var/lib/telegram-bot-api)`.
2. Повторная приёмка: vision-джоба по новой картинке проходит
   `download → decode → vision → store`, `mca_media_analyses` наполняется;
   `stage=download`-исходы исчезают.
3. Остаточный риск: чтение host-каталога процессом бота (прод: root ✓;
   при смене пользователя — инфра-инструкция §2). Отдельно: HTTP-эндпоинт
   скачивания локального сервера остаётся недоступным (404) — если когда-то
   понадобится HTTP-путь, потребуется reverse-proxy (инфра-контур).
4. Pre-existing (не связано): `tests/test_t5150_startup_migrations_round1046.py`
   — 5 failed из-за устаревшего ожидаемого списка миграций (проверено на
   откаченном `bot.py`: тот же набор падений).
5. R17-инцидент в ходе диагностики: первая версия пробы напечатала имя
   каталога с токеном в **локальный untracked** JSON-evidence; маскирование
   исправлено сразу (`<token:masked>`), файл перепроверен на отсутствие
   токен-подобных строк до включения в отчёт. В коммит/отчёт токен не попадал.
