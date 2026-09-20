# Scanner-аудит P0-фикса round1025 (hotfix2, коммит `fea2daa`)

> Точечный независимый diff-аудит по запросу (прод-инцидент). Диапазон `78e612a..fea2daa`.
> Код не менялся. Секретов в отчёте нет (токены вымышленные).
> Затронуто: `web/app.js`, `services/media_download.py`, `web/api/avatars.py`,
> `config/settings.py`, `README.md`, `tools/ui_round1025_matrix.py`, `tests/test_media_local_path_round1025.py`,
> `tests/js/round1025_save_state_test.js`, `plans/features/.../tasks.md`.

## 1. Сводка

| Severity | Кол-во |
|---|---|
| **Critical** | **0** |
| **High** | **0** |
| **Medium** | **2** |
| **Low** | **3** |

**Вердикт: к деплою — ДА** (0 Critical / 0 High, оба P0 закрыты). Рекомендую закрыть
M-1/M-2 (одна строка + санитайз трейсбека) вместе со следующим коммитом.

Фактические прогоны:
- `python -m pytest -q` → **8003 passed / 0 failed** (117.37 s, 1 предсуществующий
  `StarletteDeprecationWarning` про httpx).
- `tests/js/*.js` → **21 файл, 21/21 OK** (`node tests/js/<file>.js`).
- `git diff --check 78e612a..fea2daa` → exit 0; `git ls-files "*.zip"` пусто.

## 2. P0-механизмы — подтверждены

1. **JS render-регрессия (`web/app.js:2142-2150`).** `stickyFieldFailed` перенесён
   computed→methods без изменения тела. Шаблоны `web/index.html:851,970` вызывают
   `stickyFieldFailed(item.key)` — с computed-геттером это был boolean → render
   `TypeError` → пустой generic-раздел. Дублей нет, в `computed` ключа нет (проверено
   грепом: единственное объявление).
2. **Container→host путь (`services/media_download.py:60-82`).** Префикс
   `/var/lib/telegram-bot-api/<bot_id>:<token>/…` режется и переносится под
   `settings.TELEGRAM_API_FILES_DIR`; относительный → `root/<bot_id:token>/<path>`;
   иной абсолютный (в т.ч. Windows) → как есть; ровно контейнерный root → `None`.
   Маппинг однократный (повторный префикс даёт путь внутри корня, но файла там нет →
   fail-closed fallback). Guard `_is_within_root` (resolve + is_relative_to) сохранён.

## 3. Находки

### [Medium] M-1. Лог сырого `file_path` теперь достижим на штатном контейнерном пути (R17)

- **Файл:** `services/media_download.py:153-155` (`path=%s` → `file_path`).
- **Сценарий:** локальный Bot API в `--local` отдаёт абсолютный контейнерный путь
  `/var/lib/telegram-bot-api/42:TOKEN/…`. Файл появляется на диске с задержкой
  ~1-2 с (ровно ради чего 3 ретрая). На первой попытке `src` уже валиден, но
  `src.exists()` = false → в лог уходит полный путь, включающий `<bot_id>:<token>`.
  До фикса контейнерный путь давал `None` и эта строка не срабатывала — теперь
  (после нормализации) это основной прод-путь. Это тот же дефект, что M-1 в
  `round1025_hotfix_scanner_audit.md`, но теперь достижимый «по умолчанию».
- **Оценка:** в проде сообщение маскируется `SecretMaskFilter` (`bot.py:150`,
  `settings.API_TOKEN in _collect_secrets()` → True), поэтому подтверждённой утечки
  в journald нет → **Medium**, не High. Но контракт R17 в коде нарушен, и любой
  сторонний handler/`caplog` без фильтра утечёт токен.
- **Фикс (1 строка):** логировать хвост — `PurePosixPath(file_path).name`
  (как уже сделано для `src.name`), либо `log_ring.sanitize`.

### [Medium] M-2. Трейсбек `avatars` при fallback может нести контейнерный путь с токеном

- **Файл:** `web/api/avatars.py:157` (`bot.download_file(path, …)`), `:171-175` →
  `_log_bot_api_failure(..., expected=False)` → `:199-201` `logger.warning(..., exc_info=True)`.
- **Сценарий:** если `read_host_file_bytes` вернул `None` (файла ещё нет / путь вне
  корня), вызывается `download_file` с контейнерным путём; aiogram бросает
  `FileNotFoundError` с сообщением, содержащим `<bot_id>:<token>`. Ловится общим
  `except Exception` и пишется с трейсбеком. `SecretMaskFilter` мутирует только
  `record.msg`, **трейсбек (exc_info) не маскируется** → токен уходит в stdout/journald.
- **Оценка:** дефект **предсуществующий** (та же ветка была основным путём до фикса),
  фикс лишь снижает частоту. Не регресс диффа, поэтому Medium.
- **Фикс:** в `_log_bot_api_failure(expected=False)` логировать `safe_exc_text(exc)`
  без `exc_info`, либо прогнать форматтер через `sanitize`.

### [Low] L-1. JS-тест содержит тавтологичную проверку «нет дублей»

- **Файл:** `tests/js/round1025_save_state_test.js:319-320`
  (`assert.strictEqual(methods.stickyFieldFailed, methods.stickyFieldFailed, 'единственное объявление (нет дублей)')`
  — всегда true, ничего не проверяет. Остальные 4 ассерта блока осмысленны и
  падали бы до фикса (проверка `typeof` + отсутствие ключа в `computed`).

### [Low] L-2. Матрица `_config_stub()` при сбое импорта `param_catalog` молча даёт пустой stub

- **Файл:** `tools/ui_round1025_matrix.py:112-160` — при исключении возвращает
  `{"items": [], "groups": []}` и только `print`. Матрица при этом не падает:
  render с пустым config даст «зелёный» проход → класс «пустой раздел» не поймается.
  Плюс нет ассерта, что разделы реально непустые (только console/pageerror).

### [Low] L-3. Нет регресс-тестов на symlink-escape и двойной контейнерный префикс

- **Файл:** `tests/test_media_local_path_round1025.py`. Текущие тесты: `%s/%s/../../etc/passwd`,
  `/etc/passwd`, `CONTAINER`, missing-file. Логика guard для symlink и двойного
  префикса корректна по разбору (`resolve()` следует симлинкам; повторный префикс →
  fail-closed), но автотестом не закреплена.

## 4. Что чисто (проверено)

1. **Traversal-guard не обойдён:** `..`, `../../etc/passwd`, абсолютный чужой путь,
   ровно контейнерный root → `None`. Symlink внутри корня наружу после `resolve()`
   отсекается. Windows-пути: `PurePosixPath` не-absolute → `Path.is_absolute()` →
   чужой диск → guard `None`; `\`-разделители в контейнерном виде → не под корнем →
   `None`. Произвольное чтение вне `TELEGRAM_API_FILES_DIR` невозможно.
2. **Отсутствие двойного маппинга:** корень совпадает с контейнерным путём →
   `root / rel` = исходный путь (однократно), корректен.
3. **Fail-closed:** нет файла/корень/`OSError`/`src is None` → `None` → вызывающий
   делает `bot.download`/`download_file` (сохранён).
4. **Регрессий голосовых/видео/аватаров/скачивания нет:** `fetch_media_to_tmp` не
   менялся (3 попытки/1 s, fallback `bot.download`); голосовые/кружки/нативные медиа
   идут через него; `_read_local_source` общий; аватары получили новый helper
   поверх прежнего fallback. F0-слой не тронут (diff `web/app.js` — только перенос).
5. **Секретов в диффе нет** (грепом `AA…`/`sk-`/PRIVATE KEY — пусто; в тестах
   синтетический `42:TESTTOKENPLACEHOLDER`).

## 5. Инварианты

| Инвариант | Факт | Статус |
|---|---|---|
| Δ DDL = 0 | миграции/PG в диффе отсутствуют | ✅ |
| Δ каталога = 0 | `services/param_catalog.py` не в диффе (только `APP_VERSION`) | ✅ |
| Эпик 2 / промпты не тронуты | файлов промптов/anticliche в диффе нет | ✅ |
| F0 не тронут | `web/app.js` — только перенос `stickyFieldFailed` | ✅ |
| `stash@{0}` цел | `wip(f1): IA v2 round1025 …`, 25 файлов / +971 | ✅ |
| zip в git | `git ls-files "*.zip"` пусто | ✅ |
| R17 (дифф) | секретов нет; остаточные риски M-1/M-2 (см. выше) | ⚠️ |

**Итог: Critical 0 / High 0 / Medium 2 / Low 3 → к деплою — ДА.** Оба P0
(render и container→host путь) закрыты и покрыты тестами, которые падали бы
до фикса. Перед прод-деплоем желательно закрыть M-1 (хвост пути вместо полного)
и M-2 (санитайз трейсбека).
