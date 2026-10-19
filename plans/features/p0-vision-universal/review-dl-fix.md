# REV-DL-FIX — вердикт (скачивание Vision через local Bot API; ACCEPTANCE-92C)

Независимое ревью. Read-only; этот коммит — только данный документ.

**Кандидат (uncommitted поверх `b4d30cab` = HEAD):** `bot.py` sha256_12 `f9d8306e6034`; `services/local_bot_api.py` (новый) `a97e1d3eeab0`; `tests/test_vision_dl_fix.py` (новый) `ac618a776c53`. Хеши сверены в дереве и в изолированном worktree (venv-питон, как в evidence). `bot.py` идентичен и на `b33c0c47` (README-база) — переезд базы фикс не затронул.

## 1. Корень — подтверждено прод-эвиденсом
`prod-diag`: контейнер `adminbot-telegram-bot-api` (`TELEGRAM_LOCAL=1`, `TELEGRAM_WORK_DIR=/var/lib/telegram-bot-api`), bind `/var/www/admin_bot/docker/telegram-bot-api => /var/lib/telegram-bot-api`; на хосте `/var/lib/telegram-bot-api` **отсутствует**; `getFile`-путь — контейнерный; aiogram 3.31 `is_local=True` читает его с ФС хоста → `FileNotFoundError`. `prod-probe`: «A) текущая сессия» `exists=false` + `FileNotFoundError`; HTTP `/file/bot…` → **404** во всех трёх вариантах (абс. контейнерный, относительный, host-эквивалент); облачный контроль — 54 960 байт. Механизм совпадает с документацией local Bot API (абсолютный путь контейнера в local-режиме; HTTP-скачивание не обслуживается). Оговорка честно зафиксирована: проба «B» упала `PermissionError` (запуск под `nik`, каталог `messagebus:lxd`) — прямой прод-прогон маппинга под ботом (root) не выполнен; поддержка — прод-путь голосовых/видео уже читает этот же каталог.

## 2. Фикс — подтверждено кодом
`HostFilesPathWrapper`: `/var/lib/telegram-bot-api/<…>` → `<TELEGRAM_API_FILES_DIR>/<…>` — **та же нормализация**, что прод-проверенная `media_download.normalize_api_file_path` (сверил обе); fail-safe: относительный/чужой абсолютный/сам корень возвращаются как есть, без `ValueError`; `host_files_root` резолвит относительный `TELEGRAM_API_FILES_DIR` от каталога приложения; `local_files_dir_readable` + R17-safe WARNING/INFO со стартовым маркером `[local-bot-api]`; `bot.py` собирает локальную сессию **только** через `build_local_api_session` (инвариант-тест), прямые импорты убраны; облачный режим не затронут.

## 3. Тесты — перепрогнаны (мой изолированный worktree `b4d30cab` + патч)
- GREEN нового файла: **7/7** ✓; RED (откат `bot.py`): **1 failed / 6 passed** ✓ (конфиг-инвариант; ветка «без маппинга → FileNotFoundError» внутри aiogram-контрактного теста).
- Свод-195 (vision core + mca19 A–G + rework + addtr_postgen): **195 passed** — точное совпадение ✓. Второй мой профиль (media/download/voice/video/avatars, шире): **556 passed**. Нюанс: составы «264» и «182» в evidence не зафиксированы (только итоговые числа; «182» не найден вовсе) — буквально не сверяемы; ≥2 свода воспроизведены и зелёные, кандидат регрессий не даёт (не блокер).
- `t5150` спот: **5 failed** и на патче, и на базе — **pre-existing** ✓.

## 4. R17 — чисто
Мой скан (паттерн `<bot_id>:<token>`) по всему `evidence/dl-fix/**` + три файла кандидата: **0 токен-подобных строк** ✓. Зафиксированный в README инцидент (первая версия пробы, локальный untracked JSON) замаскирован; в коммит/отчёт токен не попадал.

## 5. Дисциплина
Периметр = ровно `bot.py` + 2 новых файла; `services/mca_vision.py` / `web/api/routes.py` не тронуты (в дереве clean); чужие untracked tools-пины — не этого лейна; мой коммит — только вердикт.

## Леджеру (рекомендация)
- Фикс = **инфра-путь** (сессия/конфиг, не смена Vision-контура): `P0V-PIPE-E2E` / `-CONTEXT` / `-DOD` остаются **READY_FOR_LIVE** до live; `ADTR-TOOLS-VISION` — live после деплоя.
- Деплой-шаг: штатный рестарт; в журнале ждать маркер `[local-bot-api] файлы: … (container /var/lib/telegram-bot-api)`; затем повторная приёмка: vision-джоба проходит `download → decode → vision → store`, `mca_media_analyses` наполняется, `stage=download`-исходы исчезают.
- Остаточные риски (не блокеры): чтение host-каталога процессом (prod root ✓; инфра-инструкция при смене пользователя); HTTP-эндпоинт локального сервера остаётся 404 (при нужде — reverse-proxy, отдельный инфра-контур).

## Вердикт
**Approved.** Корень доказан прод-фактами, фикс точечный и fail-safe, контракт на реальном aiogram и RED/GREEN воспроизведены, R17 чист; live-половина — только postdeploy.
