# Spec F6 — `media-files-avatars-sync` (Аватары: локальный fallback как `media_download`; диагностика рассинхрона ФС↔БД; `fetch failed` юзера 525660918)

> **Раунд:** 10.19 (Step 2 @Architect, 15.09.2026). **Тип:** backend (`web/api/avatars.py`, `services/media_download.py`, новый `services/media_integrity.py`, `web/api/*`). **Приоритет:** **P1**.
> **ADR:** `adr-1019-5-media-local-fallback.md`.
> **Задачи:** T-1826…T-1834. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/90/406/411/88/19**.
> **Источник:** `plans/current_task.md` UPD2 п.6 (строка 158): «`photos/file_456.jpg`, потом `file_457.jpg` — файлов просто нет; аватарки отлетают с `fetch failed` для юзера 525660918; файловая помойка не синхронизирована с БД».
> **Конфликт файлов:** `web/api/*` (F3), `services/param_catalog.py` (только если Δ).

## 1. Контекст и цель

`services/media_download.py::fetch_media_to_tmp` (`:43-102`) умеет починить **относительный** `file_path` локального Bot API: читает файл с диска `TELEGRAM_API_FILES_DIR/<bot_id:token>/<path>` с 3 ретраями, иначе `bot.download`. `web/api/avatars.py::fetch_avatar_bytes` (`:120-160`) **не имеет** этого fallback: `bot.get_file` → `bot.download_file(path, buf)` напрямую. В локальном режиме (`is_local=True`) `download_file` читает относительный путь от cwd → `FileNotFoundError`, аватары «отлетают».

**Цель:** дать аватарам тот же локальный fallback, ввести диагностику рассинхрона ФС↔БД и разобрать `fetch failed` юзера `525660918`.

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `web/api/avatars.py:120-160` — `fetch_avatar_bytes`: кэш (положительный + дефинитивные негативы); `_avatar_file_id` → `get_file` → `download_file`; исключения: `TelegramRetryAfter`/`TelegramNetworkError` → без негатива (BUG-4), `TelegramBadRequest` → негатив (debug), прочее → warning+traceback.
- `services/media_download.py:27-40` — `local_files_subdir(bot)` (строка `<bot_id>:<token>`; **R17 — не логируется**).
- `services/media_download.py:43-102` — `fetch_media_to_tmp`: гейт `flags.download_enabled`; относительный `file_path` → `Path(TELEGRAM_API_FILES_DIR)/local_files_subdir(bot)/file_path`, `resolve().is_relative_to(root)` (защита от traversal), `src.exists()` → `shutil.copyfile`; 3 попытки с `sleep(1.0)`; иначе `bot.download`.
- `web/api/avatars.py:163-184` — `safe_exc_text`/`_log_bot_api_failure` (политика WARNING/debug раунда 10.17).
- Наблюдение чекапа: в БД есть `photos/file_456.jpg`/`file_457.jpg`, **на диске файлов нет** → ошибка чтения/скачивания; `fetch failed` для `525660918`.

## 3. Требуемое поведение

1. `fetch_avatar_bytes` использует **локальный fallback** (как `media_download`): при относительном `file_path` и локальном режиме — чтение из `TELEGRAM_API_FILES_DIR/<bot_id:token>/<path>` с ретраями; при отсутствии — прежний `bot.download` как фоллбэк.
2. Поведение «транзиент → не кэшировать» (BUG-4/10.17) **сохранено**.
3. **Диагностика рассинхрона**: счётчики «в БД есть — на диске нет» и «на диске есть — в БД нет» (для медиа-путей), R17-safe.
4. `fetch failed` юзера `525660918` разобран: причина (код ошибки/тип) + фикс или обоснование (ограничение приватности).
5. Логика локального чтения — **общий хелпер**, без дублирования с `media_download`.
6. Дополнительно: **bounded** фоновая сверка/восстановление отсутствующих файлов (fail-open), без роста нагрузки.
7. R17: строка `<bot_id>:<token>` и абсолютные пути с токеном **никогда** не логируются; в логах — только хвост `photos/file_*.jpg`.

## 4. Технический дизайн

### 4.1. Общий хелпер `services/media_download.py`

```python
async def read_local_file_bytes(bot, file_id: str, *, attempts: int = 3,
                                sleep: float = 1.0) -> bytes | None:
    """Локальный Bot API: относительный file_path → байты из
    TELEGRAM_API_FILES_DIR/<bot_id:token>/<path>; 3 попытки (API кеширует
    файл с задержкой ~1-2с); None если файла нет/облако/ошибка.
    R17: <bot_id>:<token> не логируется — только file_path-хвост/имя."""

def local_file_path(bot, file_path: str) -> Path | None:
    """Безопасный резолв относительного пути под корнем TELEGRAM_API_FILES_DIR
    (traversal-guard как в fetch_media_to_tmp); абсолютный/выход за корень →
    None."""
```
- `fetch_media_to_tmp` **рефакторится** на эти хелперы (поведение байт-в-байт: гейт `flags.download_enabled`, 3 попытки, fallback `bot.download`) — устраняет дублирование (R: F6/tasks.md R5).
- Аватары используют `read_local_file_bytes`; при `None` — `bot.download_file` (cloud/локальный fallback).

### 4.2. `web/api/avatars.py::fetch_avatar_bytes`

```python
file_id = await _avatar_file_id(bot, kind, tid)
if file_id:
    if hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
        data = await read_local_file_bytes(bot, file_id)      # локальный fallback
    if data is None:
        try:
            file = await bot.get_file(file_id)
            path = getattr(file, "file_path", None)
            if path:
                buf = io.BytesIO()
                await bot.download_file(path, destination=buf)
                data = buf.getvalue() or None
        except (TelegramRetryAfter, TelegramNetworkError): …   # как сейчас: без негатива
        except TelegramBadRequest: …                            # негатив + debug
        except Exception: …                                     # warning + traceback (R17-safe)
```
- Порядок/классы исключений и кэш-политика **не меняются** (BUG-4 сохраняется).

### 4.3. `services/media_integrity.py` (новый) — диагностика и восстановление

```python
async def audit_media_files(db, bot=None, *, chat_id: int | None = None,
                            sample_limit: int = 200) -> dict:
    """Диагностика БД↔ФС. Возвращает {db_media_rows, text_media_paths,
    files_on_disk, missing_on_disk, orphan_files, sample_missing,
    reliable: false, basis: 'text_scan'}.
    D-4 (ревью Батча E): `db_media_rows` — достоверный COUNT медиа-строк;
    `text_media_paths`/missing/orphan — ЭВРИСТИКА по тексту сообщений
    (реальных file_path в схеме нет) → `reliable=false`, числа не выдаются
    за точный рассинхрон. Тяжёлый обход диска — в `asyncio.to_thread` (D-3).
    R17: только хвосты имён; ошибки → fail-open (нулевые счётчики)."""
```
- **`restore_missing_files` — УБРАН из публичного API (Low, ревью Батча E):** не имел call-site и реального маппинга path→file_id (Bot API `file_path` транзиентен) → не восстанавливал файлы. Перенесён в `backlog.md` (реализация — только при появлении персистентного маппинга).
- Источник строк БД: `db_media_rows` — `smart_messages` с медиа (`media_type != 'text'`); `text_media_paths` — best-effort regex `photos/file_*.jpg` по ТЕКСТУ (в схеме нет реальных путей), с `LIMIT` и fail-open.
- Диагностика отдаётся **аддитивно** (R16): `GET /api/status/media-health` — **только числа + примеры хвостов имён**; не логировать токен. Эндпоинт TTL-кэшируется (120с, D-5).
- **Рекомендация:** фаза 1 — только диагностика (лог при старте/по запросу); фаза 2 — bounded `restore_missing_files` по кнопке/расписанию (не агрессивно).

### 4.4. `fetch failed` для 525660918 (T-1829)

Диагностическая последовательность (результат — в отчёт):
1. Тип исключения (из логов `[avatar] fetch failed | kind=user tid=525660918` + traceback, R17-safe);
2. `get_user_profile_photos(525660918, limit=1)` — есть ли фото вообще;
3. Если фото есть, но файл отсутствует локально → покрывается fallback (§4.2);
4. Если `TelegramBadRequest` «user not found»/приватность → обосновать (негатив, 404).
Фикс — общий (fallback) + при необходимости точечная политика кэша негатива.

## 5. Изменения схемы / каталога / env

- **Схема БД:** нет (только чтение для диагностики).
- **Каталог:** **Δ=0** (переиспользуются `flags.download_enabled`, `content.media_*`; новых ключей нет). Диагностический эндпоинт — без каталога.
- **env:** нет (`TELEGRAM_API_FILES_DIR` уже есть, не логируется).

## 6. Влияние на тесты

- Новый `tests/test_media_integrity_round1019.py`:
  - `local_file_path` — относительный под корнем → Path; абсолютный/`../` → None (traversal-guard);
  - `read_local_file_bytes` — файл есть (байты), нет (None, 3 попытки), ошибка копирования (None);
  - `audit_media_files` — honest-счётчики (db_media_rows/text_media_paths/missing/orphan, `reliable=false`), R17 (в результате нет `<bot_id>:<token>`);
  - `restore_missing_files` отсутствует в публичном API (Low, ревью Батча E) — перенесён в backlog.
- `tests/test_avatars*.py` (если есть) / новый: `fetch_avatar_bytes` — локальный fallback (файл на диске → байты); fallback на `bot.download` при отсутствии; негатив/транзиент-политика сохранена; R17-чистота логов (нет `<bot_id>:<token>`, нет абсолютного пути).
- **Регресс `fetch_media_to_tmp`**: после рефакторинга — прежнее поведение (3 попытки, fallback) — существующие тесты `tests/test_media_download.py` зелёные.
- Полный `pytest` 0 failed; `git diff --check`; R17-скан (`git diff` на секреты). 

## 7. Rollout / feature-flag / откат

- Feature flag не вводится; фон-восстановление работает только при `flags.download_enabled` (уже существует) и bounded.
- **Progressive delivery:** диагностика → ручной запуск восстановления на тестовом чате/юзер `525660918` → затем общий.
- **Rollback:** `git revert`. Автовосстановление можно отключить, не откатывая fallback.
- Деплой: @DevOps (SSH + рестарт + live-проверка аватарок, в т.ч. 525660918).

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Локальный fallback не применим в облачном режиме | Сохранить `bot.download`-фоллбэк; fallback только при относительном path + local mode |
| R2 | Утечка `<bot_id>:<token>` | R17-скан; логировать только `photos/file_*.jpg` |
| R3 | Ретраи/восстановление дают нагрузку | Ограничить число/сон/limit; негатив-кэш для дефинитивных ошибок |
| R4 | Рассинхрон — следствие чистки/переезда | Диагностика + процедура (T-1832); автовосстановление — bounded/fail-open |
| R5 | Дублирование логики с `media_download` | Общий хелпер §4.1 (обязателен) |
| R6 | Пересечение `web/api/*` с F3 | Согласованное вливание |

## 9. Открытые вопросы (рекомендации)

1. **Где отдавать диагностику:** рекомендация — **аддитивный** `GET /api/status/media-health` (числа + примеры хвостов), плюс лог при старте; UI-блок — по желанию владельца (F7 уже расширяет health-метрики — можно свести).
2. **Автовосстановление:** рекомендация — **включить bounded** (limit 25/прогон, fail-open), но только при `flags.download_enabled`; при сомнениях — сначала dry-run (только подсчёт).
3. **Политика негатива для юзера без фото/приватного:** рекомендация — дефинитивный негатив кэшировать (404), транзиент — не кэшировать (как сейчас).
4. **Источник строк БД для аудита:** уточняется @Builder (схемы `smart_messages`/`graph_facts`/media-refs); влияет только на полноту выборки, не на контракт.
