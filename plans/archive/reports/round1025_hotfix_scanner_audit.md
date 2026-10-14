# Scanner-аудит хотфикса `hotfix-media-tma-round1025` (раунд 10.25)

> Режим: точечный diff-аудит по запросу ASAP. Диапазон `7c38f70..ee23e47`
> (коммиты `8b16c4a`, `ee23e47`). @Reviewer уже дал Approved — здесь
> независимый поиск скрытых логических/безопасностных проблем. Код не менялся.
> Секретов в отчёте нет (токены — вымышленные).
>
> Затронуто по диффу: `handlers/youtube.py`, `services/smartmodule_phrases.py`,
> `services/media_download.py`, `services/llm_client.py`, `config/settings.py`,
> `web/index.html`, `docker-compose.yml`, `.gitignore`, `README.md`,
> `plans/features/hotfix-media-tma-round1025/*`, тесты.

---

## 1. Сводка

| Severity | Кол-во |
|---|---|
| **Critical** | **0** |
| **High** | **0** |
| **Medium** | **2** |
| **Low** | **4** |
| Info | 4 |

**Вердикт: Critical = 0, High = 0 → к Шагу 7/9 — ДА.**
Рекомендация (не блокер): закрыть **M-1** однострочно и **M-2** (env-шаблон +
согласование рубильников) **до прод-деплоя**, т.к. иначе «единый рубильник» из
ADR-1025-6 остаётся неполным и в логах остаётся латентный R17-риск.

Фактические прогоны (зафиксировано):

- `python -m pytest -q` → **7976 passed / 0 failed**, 1 warning
  (предсуществующий `StarletteDeprecationWarning` про `httpx` в
  `.venv/.../fastapi/testclient.py`), **109.17 s**.
- `tests/js/*.js` → **19 файлов, 19/19 OK** (`node tests/js/<file>.js`).
- Точечно новые тесты хотфикса →
  `tests/test_hotfix_round1025_media.py` + `..._logging.py` + `..._cachebust.py`
  = **30 passed**.
- `git diff --check 7c38f70..ee23e47` → exit 0 (пусто).

---

## 2. Находки

### [Medium] M-1. `_read_local_source` логирует СЫРОЙ `file_path`; новая ветка абсолютного пути заводит туда `<bot_id>:<token>`

- **Файл:** `services/media_download.py:99-101` (лог `path=%s`) в связке с
  новой веткой `services/media_download.py:68-70` (`local_file_path` теперь
  принимает абсолютный путь внутри `TELEGRAM_API_FILES_DIR`).
- **Суть:** при абсолютном `file_path` внутри корня `src` уже не `None`, и
  если файла на диске ещё нет (`getFile`-гонка ~1-2 с — штатный кейс, ровно
  то, ради чего в коде 3 ретрая) — срабатывает
  `logger.warning("[%s] local api file missing ... | path=%s", ..., file_path)`
  и в лог уходит **полный абсолютный путь**, который в каталоге Bot API
  содержит подкаталог `<bot_id>:<secret>` (см. `local_files_subdir`, `:27-40`).
  Это прямо противоречит docstring'ам самого файла
  (`:14`, `:58-59`, `:82-83`): «абсолютный путь с `<bot_id>:<token>` — НИКОГДА».
  До этой правки абсолютный путь всегда давал `None`, и лог-строка с
  абсолютным путём была недостижима — **это регресс R17, внесённый хотфиксом**.
- **Воспроизведение (Windows, venv-питон):** мок `bot.get_file` возвращает
  абсолютный путь внутри корня, файла нет; вызов
  `media_download._read_local_source(bot, "FILEID", cb, attempts=1)` →
  в логе: `path=C:\...\botapi_xxx\123456789:AAHsupersecrettokenVALUE\videos\file_0.mp4`,
  т.е. токен в открытом виде. (Токен вымышленный.)
- **Почему всё же Medium, а не High:** в проде сообщение проходит через
  глобальную маскировку — `bot.py:145-150` вешает `SecretMaskFilter` на
  `console_handler`, `LogRingHandler`/`BetterStackHandler` вызывают `sanitize`,
  а `API_TOKEN` входит в `_collect_secrets()` (проверено: `settings.API_TOKEN
  in _collect_secrets()` → True, `sanitize()` его вырезает). Веб-процесс
  (uvicorn) живёт в ТОМ ЖЕ процессе (`bot.py:1090-1100`, `log_config=None`),
  поэтому тоже фильтруется. Подтверждённой утечки «в прод» нет, но:
  - код нарушает собственный R17-контракт и логирует секрет в `LogRecord`
    **до** фильтрации (любой будущий/сторонний handler без фильтра, `caplog`,
    самодельный логгер — утекут);
  - если Bot API вернёт абсолютный путь в другой раскладке, где `API_TOKEN`
    не является дословной подстрокой (например, сменится формат каталога
    data-dir), маскировка не сработает по определению.
- **Направление фикса (1 строка):** логировать не `file_path`, а хвост/имя —
  `Path(file_path).name` или `PurePosixPath(file_path).name`, как уже сделано
  для `src.name` на копировании (`:105-106`). Либо прогнать через
  `log_ring.sanitize`.

### [Medium] M-2. «Единый рубильник» из ADR-1025-6 D1 фактически не единый: гейт размера читает `TELEGRAM_LOCAL`, а локальное чтение файла — `flags.download_enabled` (`DOWNLOAD_ENABLED`)

- **Файлы:** `handlers/youtube.py:164-197` (`telegram_local_mode_enabled` /
  `effective_video_max_size_mb`) и `services/media_download.py:144`
  (`if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED)`),
  `web/api/avatars.py:143-145`, `services/status_service.py:575-576`.
- **Суть:** режим для **гейта размера** определяется `TELEGRAM_LOCAL`, а
  фактический способ получения файла (диск vs `bot.download`) — совсем другим
  флагом `DOWNLOAD_ENABLED` (`config/settings.py:1287`, default **False**).
  Документация (ADR D1, комментарии в `docker-compose.yml:14-29`, docstring
  `handlers/youtube.py:142-159`) заявляет «ЕДИНЫЙ рубильник» — это неточно.
  Возможные расхождения:
  - `TELEGRAM_LOCAL=1` + `DOWNLOAD_ENABLED=False`: гейт честно пропускает до
    конфигурных 50 МБ, но диск-путь выключен → идём через `bot.download`.
    Работоспособно (локальный сервер отдаёт файл по HTTP), но гейт становится
    «щедрее» гарантированного пути, а `status_service.local_api` (считается от
    `DOWNLOAD_ENABLED`) покажет `false` при включённом `--local`.
  - `DOWNLOAD_ENABLED=True` + `TELEGRAM_LOCAL` не задан: диск-путь включён, а
    контейнер без `--local` (20 МБ) → гейт режет по 20 МБ, мониторинг при
    этом рапортует `local_api=true`.
  - Отдельно опасно: если контейнер поднят в `--local` **не** через
    `TELEGRAM_LOCAL` (override-compose / ручной флаг `--local` / своя команда),
    приложение по-прежнему считает режим «cloud» и **режет легитимные файлы
    20–50 МБ**, которые до хотфикса проходили по гейту 50 МБ. Это и есть
    риск «отказа легитимных файлов» из брифа.
- **Сопутствующее:** `.env.example` (tracked) **не обновлён** — в нём нет
  `TELEGRAM_LOCAL` (есть только `DOWNLOAD_ENABLED=False` и
  `TELEGRAM_API_FILES_DIR`). README тоже не описывает новый рубильник. Тот,
  кто разворачивает по шаблону, не узнает о шаге и останется в cloud-20 МБ,
  т.е. головная фича хотфикса (локальный Bot API) по умолчанию не включится.
- **Что проверено и работает корректно:** паритет с образом подтверждён по
  исходнику `aiogram/telegram-bot-api` `docker-entrypoint.sh` —
  `append_flag_from_env` использует `[ -n "$(printenv ...)" ]`, т.е. **любое
  непустое** значение → `--local`; пусто/не задано → cloud. Семантика
  `telegram_local_mode_enabled()` (`os.getenv`, `bool(raw and raw.strip())`)
  совпадает 1:1, инверсии нет, обе ветви достижимы (env читается при каждом
  вызове — reload-friendly).
- **Направление фикса:** либо вывести диск-гейт из одного сигнала
  (`telegram_local_mode_enabled()`), либо явно и письменно связать
  `DOWNLOAD_ENABLED` и `TELEGRAM_LOCAL` (в ADR/compose/README/.env.example) и
  вернуть `status_service.local_api` тот же источник, что и гейт.

### [Low] L-1. Новые тесты абсолютного пути тавтологичны на win32 (не тестируют новую ветку)

- **Файл:** `tests/test_hotfix_round1025_media.py::TestLocalFilePathRound1025`
  (`test_absolute_inside_root_accepted`, `test_absolute_outside_root_rejected`).
- **Суть (подтверждено исполнением):** на Windows
  `PurePosixPath(r"C:\...\file.mp4").is_absolute()` → **False**, а
  `Path(root)/subdir/абсолютный_windows_путь` в силу `ntpath.join` **сбрасывается
  на этот абсолютный путь**: `src == inside`. Поэтому старый код (проверка
  `is_absolute` → join → `resolve().is_relative_to(root)`) даёт ровно тот же
  результат: inside → `src`, outside → `None`. Значит, оба теста **проходят и
  без новой логики** `:68-70` — строки новой ветки на CI-OS не исполняются.
  Это ровно то, что отметил @Reviewer.
- **Дополнительно:** в `test_absolute_inside_root_accepted` bot.id = `999`, а
  в пути — `7843:token` (для относительной ветки это было бы рассогласование;
  для текущего теста безвредно, но путает).
- **Направление фикса:** сделать тест, реально попадающий в POSIX-ветку —
  `pytest.mark.skipif(sys.platform == "win32")` с путём вида
  `/var/lib/telegram-bot-api/123:tok/videos/f.mp4` и root `/var/lib/...`, либо
  unit-тест `_is_within_root`/`local_file_path` с прямым monkeypatch
  `PurePosixPath.is_absolute`, плюс mutation-проверка (временно вернуть старую
  реализацию и убедиться, что тест краснеет).

### [Low] L-2. Cache-bust покрыт частично: вендорные скрипты TMA остались без `?v=`

- **Файл:** `web/index.html:15` (`/static/vendor/telegram-web-app.js`),
  `:3616` (`vue.global.prod.min.js`), `:3623` (`chart.umd.min.js`) — без
  `?v=`; `:3624` (`app.js`) и `:3627` (`telegram-init.js`) — с `?v=`; у
  `dompurify-3.4.15.min.js` версия зашита в имя файла.
- **Суть:** цель T-2470 — «cache-bust ассетов TMA». `telegram-init.js` починен,
  но при следующей замене `telegram-web-app.js`/`vue`/`chart` (они pinned и
  обновляются редко, но обновляются) WebView отдаст залипшую старую копию —
  это тот же класс дефекта, что чинили. `tailwind.css`/`app.css`/`app.js` +
  `@font-face` — версионированы (тесты подтверждают).
- **Направление фикса:** добавить `?v=__APP_VERSION__` к трём vendor-скриптам
  (static-роут к query нейтрален).

### [Low] L-3. `_process_video_media` не делает пост-скачивающую проверку размера

- **Файл:** `handlers/youtube.py:1097-1121`.
- **Суть:** гейт по `media.media.file_size` пропускается, если поле `None`
  (aiogram `Optional[int]`). В отличие от `_process_url_media`/`
  _process_youtube_transcript`, здесь после `fetch_media_to_tmp` **нет**
  `_downloaded_too_big(path)`. С включением `--local` (getFile до 2000 МБ)
  цена этого пропуска растёт: нативный документ без `file_size` может быть
  скопирован и уйдёт в STT. Дефект **предсуществующий** (не внесён этим
  диффом), но хотфикс повышает его потенциальный масштаб.
- **Направление фикса:** после fetch добавить ту же проверку
  `_downloaded_too_big(path)` + фразу с лимитом.

### [Low] L-4. `.gitignore`: бланкетный `*.zip`

- **Файл:** `.gitignore:101` (`*.zip`).
- **Суть:** сейчас zip в git не отслеживаются (`git ls-files "*.zip"` пусто,
  `git check-ignore` подтверждает владельческие архивы) — цель T-2460
  достигнута. Но правило глобальное: любой в будущем нужный архивный артефакт
  молча не закоммитится. Аккуратнее — точечно `/bot.zip`, `/admin_bot.zip`,
  `/adminbot.zip` (или `backups/`).

---

## 3. Что чисто (проверено)

1. **Traversal-guard `_is_within_root`/`local_file_path` — корректен и
   fail-closed.** `resolve()` (non-strict) + `is_relative_to`:
   - `..` в относительном пути → нормализуется и выходит за корень → `None`;
   - абсолютный путь вне корня / чужой диск / `/` → `None`;
   - Windows-абсолют (`C:\...`, `\Windows\...`, UNC) при `is_absolute()==False`
     уходит в относительную ветку, но `Path`-join сбрасывается на абсолют, и
     `_is_within_root` его отсекает (проверено на win32);
   - symlink внутри корня, ведущий наружу, после `resolve()` оказывается вне
     корня → `None` (безопасное направление отказа);
   - `OSError` → `None`. Произвольное чтение файлов вне
     `TELEGRAM_API_FILES_DIR` невозможно.
2. **Утечки токенов/<bot_id>:<token> в логи, кроме M-1, нет.** Лог
   `get_file failed` пишет только `file_id`/класс; copy-ошибка — только
   `src.name`. `llm_client._provider_host` отдаёт **только hostname**
   (`urlsplit(...).hostname`), без userinfo/пути/кредов;
   `_safe_exc_text` (и в `youtube`, и в `llm_client`) делает `str → repr` при
   пустом `str` (httpx.ReadTimeout), маскирует секреты, схлопывает переводы
   строк, обрезает, никогда не бросает. `total_attempts` в
   `_fallback_with_retries` определён (`llm_client.py:828`) — `NameError`
   нет; логика ретраев не изменена.
3. **Фразы 5.10:** хардкод «50 мб» убран; наружу торчит только
   `video_too_big_phrase(limit_mb)` с `.replace("{limit}", str(int(...)))`.
   `VIDEO_MEDIA_TOO_BIG_PHRASES` в коде не используется (repo-wide `git grep`
   — только архивы планов). Литерал `{limit}` в пользовательский текст не
   попадёт ни на одном из 3 call-sites (`youtube.py:899-900`, `939-940`,
   `1060-1061`, `1099`) — все идут через `_too_big_phrase`; для ссылочных
   веток передаётся `_configured_video_max_size_mb()`, для нативной — реальный
   `size_mb` (тесты проверяют «20»/«50»/«2000»).
4. **Логика режима:** облачная ветвь (env пусто → 20 МБ) и локальная (env
   непусто → `min(configured, 2000)`) достижимы, инверсии нет; паритет с
   образом подтверждён исходником `docker-entrypoint.sh`. Гейт срабатывает
   **до** fetch (тесты: `fetch.await_count == 0` в облаке, `== 1` в local на
   25 МБ).
5. **Регрессий пути скачивания нет:** `fetch_media_to_tmp` не менялся по
   поведению (3 попытки/1 s, fallback `bot.download`); голосовые/кружки/
   нативные медиа ходят через тот же хелпер; `_read_local_source` остался
   общим для youtube/voice/avatars; новый отдельный пул
   `VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES` не конфликтует с
   `VIDEO_MEDIA_UNAVAILABLE_PHRASES`; таймаут отделён от generic-ошибки
   (`asyncio.TimeoutError`/`TimeoutError` перед `except Exception`).
6. **Cache-bust механика:** `web/app.py::_render_index` подставляет версию из
   `config.settings.APP_VERSION` при старте; `/static/telegram-init.js` —
   статический mount, query безопасен; `__APP_VERSION__` в рендере не
   остаётся (тесты). «Залипшей» версии `2.58.0` в рендере нет.
7. **Секретов в диффе нет** (грепом по android/`AA…`/`bot<id>:<token>` —
   пусто; в тестах только вымышленные `supersecrettoken12345`/`sk-secretvalue123`).

---

## 4. Инварианты

| Инвариант | Факт | Статус |
|---|---|---|
| Δ PG-DDL = 0 | `services/database.py`, `services/pg_db.py` — не в диффе | ✅ |
| Δ каталога = 0 | `services/param_catalog.py` — не в диффе | ✅ (config/settings.py: только `APP_VERSION`) |
| F0 не тронут | в диапазоне `7c38f70..ee23e47` нет файлов F0 (`write_transaction`, `web/app.js`, `chat_params` и т.д.) | ✅ |
| Эпик 2 не тронут | файлов `services/anticliche_worker.py` и смежных в диффе нет | ✅ |
| F1-WIP цел | `git stash list` → `stash@{0}: wip(f1): IA v2 round1025 …`; `git stash show --stat` = 25 файлов / +971 (совпадает с F1-объёмом) | ✅ |
| zip не в git | `git ls-files "*.zip"` пусто; `git check-ignore` подтверждает | ✅ |
| `git diff --check` | exit 0 | ✅ |

---

## 5. Фактические цифры и вердикт

- База: `7c38f70`; хотфикс: `8b16c4a` → `ee23e47`; рабочее дерево чистое
  (незакоммиченного нет).
- Полный pytest: **7976 passed / 0 failed** (109.17 s, 1
  предсуществующий warning).
- JS: **19/19 OK**.
- Новые тесты хотфикса: **30 passed**.
- Findings: **Critical 0 / High 0 / Medium 2 / Low 4 / Info 4.**

**Можно к Шагу 7/9 — ДА.** Блокеров нет. Перед прод-деплоем желательно:
M-1 (хвост пути в лог вместо полного — 1 строка) и M-2 (согласовать
`TELEGRAM_LOCAL` ↔ `DOWNLOAD_ENABLED`, добавить рубильник в `.env.example`
и README).
