# ASAP-хотфикс `hotfix-media-tma-round1025` — локальная спецификация

> **Раунд:** 10.25 (внеплановый, между F0 и F1). **Задачи:** T-2456…T-2481 (`tasks.md`).
> **Мастер-ТЗ:** `plans/current_task.md` (untracked — **не коммитить**, секреты не цитировать, R17/R18).
> **Тип:** инфра (Docker/Bot API) + backend (логи/фразы/гейт размера) + web (cache-bust) + ops (деплой/верификация) + git-hygiene (изоляция F1-WIP).
> **Статус:** Step 2 @Architect — спроектировано. Реализация — @Builder (Step 4).
> **ADR:** `adr-1025-6-bot-api-local-mode.md` (только по медиа/local-режиму; cache-bust/логи — существующие механизмы, ADR не требуется).
> **Baseline:** HEAD **`7c38f70`** (= origin/master); pytest **7946/0**; JS **19/19**; SQLite `user_version=12`; `APP_VERSION` **2.58.0**.

## Инварианты хотфикса (нарушать нельзя)
1. **Δ DDL = 0**, **Δ каталога (ParamSpec/GROUPS) = 0**.
2. **Не менять контракты**: `DatabaseService.write_transaction` (F0), путь скачивания `fetch_media_to_tmp`/`media_download`, LLM-каскад `_fallback_with_retries` (только логирование).
3. **Эпик 2 не трогать** (Саммари/роутинг/обложка/Rich Message); промпты не менять.
4. **R17/R18:** логи без секретов/токенов/содержимого; `.env` не коммитить; `plans/current_task.md` и zip-архивы (`~0.9 ГБ`) не добавлять в git.
5. **Порядок роутеров `bot.py`** не трогать; CSP/zero-build (Vue 3 global, self-host).

---

## 0. Изоляция F1-WIP и точка отката (T-2456…T-2460) — ПЕРВЫМ

**Проблема (факт):** в рабочей копии незакоммиченный F1 (`git status`: `web/app.js`, `web/index.html`, `web/api/routes.py`, `config/settings.py`, `services/param_catalog.py`, `web/static/app.css`, `web/static/telegram-init.js` + ~16 тестов) и untracked F1-файлы. Правки хотфикса поверх WIP недопустимы.

**Порядок:**
1. **T-2456 — точка отката:** `git tag pre-round1025-hotfix`; бэкап `var/backups/hotfix-round1025-<ts>/`; `.env.bak.round1025-hotfix` (значения не печатать). Baseline — HEAD `7c38f70`, pytest 7946/0, JS 19/19, SQLite v12, APP_VERSION 2.58.0.
2. **T-2457 — tracked-WIP в stash:** `git stash push -m "f1-wip: ia-shell-navigation-round1025 (продолжить после hotfix)"` **по явному списку** tracked-файлов (см. `tasks.md` §«Контекст»); флаг `-u` **не** использовать.
3. **T-2458 — untracked F1 в бэкап:** переместить в `var/backups/f1-wip-<ts>/` с сохранением структуры: `tests/fixtures/round1025/`, `tests/js/round1025_ia_routing_test.js`, `tests/js/round1025_shell_breakpoints_test.js`, `tests/test_ia_inventory_round1025.py`, `tests/test_ia_shell_round1025.py`, `tools/ui_round1025_matrix.py`, `tools/_ui_round1025_*` (+ `tools/_ui_round1025_shots/`, `tools/_ui_round1025_raw.json`). **`bot.zip`/`admin_bot.zip`/`adminbot.zip` НЕ трогать.**
4. **T-2459 — верификация чистой базы:** `git status` без tracked-изменений; untracked — только zip (+ `plans/current_task.md`/`var/`).
5. **T-2460 (P2) — `.gitignore`** для zip отдельным коммитом (или явно закрыть «не требуется»).

**Критично:** тег `pre-round1025-f1` уже существует — F1-WIP восстановим (T-2481).

---

## 1. Медиа / транскрибация — P0 (T-2461…T-2465)

### 1.1. Установленные факты (проверено по коду)
| Факт | Якорь |
|---|---|
| `telegram-bot-api` **без** `--local`: env задаёт только `TELEGRAM_API_ID/HASH`, команды `--local` нет → облачный `getFile` = **20 МБ** | `docker-compose.yml:5-23` (services.telegram-bot-api, `:11-13` env) |
| aiogram-клиент **уже** локальный: `is_local=True` | `bot.py:230-231` (`TelegramAPIServer.from_base(settings.LOCAL_BOT_API_URL, is_local=True)`) |
| Адрес/каталог уже согласованы (host==container путь, порт 8081) | `config/settings.py:1301` `LOCAL_BOT_API_URL="http://localhost:8081"`; `:1304-1305` `TELEGRAM_API_FILES_DIR="docker/telegram-bot-api"`; compose volume `:16` |
| Путь скачивания: локальное чтение 3 попытки → фолбэк `bot.download` → `TelegramBadRequest` | `services/media_download.py:131-152` (`_read_local_source` `:62`, `fetch_media_to_tmp` `:116`) |
| Гейт размера **50 МБ** > эффективного облачного потолка 20 МБ → крупный файл проходит гейт и падает на `getFile` | `handlers/youtube.py:1012-1022` (`VIDEO_TRANSCRIBE_MAX_SIZE_MB` default 50 — `config/settings.py:1321`) |
| `fetch_media_to_tmp` **общий** (youtube, voice, video_download, native_media) — фикс не дублируется по хендлерам | `handlers/youtube.py:1039`, `handlers/voice_transcription.py:277`, `handlers/video_download.py:789`, `services/native_media.py:177` |
| `_FETCH_TIMEOUT=120с`, лог только класса исключения | `handlers/youtube.py:138`, `:1041-1044` |

### 1.2. Решение (ADR-1025-6)
- **Основной путь:** включить локальный режим сервера — `TELEGRAM_LOCAL=1` в `docker-compose.yml` (сервис `telegram-bot-api`), при необходимости дублировать `--local` в command. Локальный Bot API: `getFile` до **2000 МБ**, файл ложится в `TELEGRAM_API_FILES_DIR` (том уже смонтирован, host==container path). **Перезапускать только этот контейнер.**
- **Эффективный лимит — по режиму.** Гейт размера в `handlers/youtube.py:1012-1022` должен использовать **эффективный** потолок: local ON → прежний `VIDEO_TRANSCRIBE_MAX_SIZE_MB` (50); local OFF (fallback) → **20 МБ** (облачный ceiling).
- **Fallback-план (если `--local` недоступен по ресурсам диска/RAM):** согласовать `VIDEO_TRANSCRIBE_MAX_SIZE_MB` с 20 МБ и давать честную фразу **до** скачивания; НЕ оставлять 50 при облаке.

### 1.3. Точные точки изменения
| Якорь | Изменение |
|---|---|
| `docker-compose.yml:11-13` | + env `TELEGRAM_LOCAL: "1"` (и/или `command: [--local, ...]`); проверить entrypoint образа `aiogram/telegram-bot-api` |
| `config/settings.py:1321` (и `:1301/:1304`) | **не менять** значения; при fallback — обосновать 20 МБ через env/hot-ключ (Δ каталога=0 — существующий `limits.video_transcribe_max_size_mb`) |
| `handlers/youtube.py:1012-1022` | гейт: эффективный лимит по режиму (local/cloud); лог `bytes=<size> limit_mb=<lim> mode=<local|cloud>` (без секретов) |
| `services/smartmodule_phrases.py:218-222` | фразы `VIDEO_MEDIA_TOO_BIG_PHRASES`: убрать хардкод «50 мб» → шаблон с `{limit}` (или отдельный пул для 20 МБ) |
| `handlers/youtube.py:1030-1047` | при сбое fetch — понятная причина (§2/T-2466/T-2468), не общая фраза |

**Контракт скачивания не меняется** — правится только порог/диагностика вокруг `fetch_media_to_tmp`.

---

## 2. Честные ошибки и диагностируемость — P0 (T-2466…T-2469)

**Факты:** `handlers/youtube.py:1042-1044` логирует только `type(exc).__name__`; `services/llm_client.py:820` формирует `f"{type}: {exc}"`, но у `httpx.ReadTimeout`/`asyncio.TimeoutError` `str(exc)` пуст → лог `error=ReadTimeout: ` (без причины). `media_download.py:149-151` уже логирует корректно.

| Якорь | Изменение |
|---|---|
| `handlers/youtube.py:1041-1044` | добавить **текст** исключения: `exc=%s` через R17-safe обработку (тот же санитайзер/`repr` с маскировкой; без токенов/содержимого). Существующий пул `VIDEO_MEDIA_UNAVAILABLE_PHRASES` — оставить |
| `services/llm_client.py:819-827` | обогатить `last_error`: `type(__name__)`, безопасный текст/`repr`, `provider/model`, `timeout=<self._fallback_timeout>`, `attempt=k/n`; при пустом сообщении — не оставлять «Type: ». **Логику ретраев не менять** |
| `services/smartmodule_phrases.py` (рядом `:224-228`) | добавить/уточнить пул фраз, различающих: «файл слишком большой» (`VIDEO_MEDIA_TOO_BIG_PHRASES`), «сервис недоступен» (`VIDEO_MEDIA_UNAVAILABLE_PHRASES`), «провайдер не ответил» (новая фраза для LLM-таймаута, если путь доходит до пользователя) |
| `handlers/youtube.py:1017-1022` | при превышении — фраза с фактическим лимитом (T-2464/T-2468) |

**R17:** логи — только class/status/reason-коды/размеры/имена моделей; ключи, полные URL, `Authorization`, содержание медиа — запрещены.

---

## 3. Cache-bust / TMA «разделы не открываются» — P0 (T-2470…T-2472)

### 3.1. Механизм (проверено)
- **Единственный источник версии:** `config/settings.py:1617` `APP_VERSION = "2.58.0"` (module-константа, **не** dataclass-поле → Δ каталога=0).
- **Подстановка:** `web/app.py:97-102` `_render_index()` и `:105-121` `_render_app_css()` заменяют `__APP_VERSION__` → `APP_VERSION`; результат кэшируется **один раз at startup** (`:218-219`) → после bump нужен **рестарт `admin_bot`**.
- **Где стоит `?v=__APP_VERSION__` (строки — по чистой базе `HEAD 7c38f70`, т.е. ПОСЛЕ изоляции F1):** `web/index.html:19` (tailwind.css), `:22` (app.css), `:3624` (app.js); `app.css` `@font-face` (`.woff2`). Значения у **всех трёх ассетов — одна версия** (согласованный набор). *(В F1-WIP-копии те же строки смещены: app.js ≈3786.)*
- **Без `?v=`:** vendor-скрипты (`index.html:15,3616,3620,3623`) и `<script src="/static/telegram-init.js">` (`:3627`) — полагаются на `Cache-Control: no-cache, no-store, must-revalidate` (`web/app.py:80-93` `CacheControlStaticFiles`, `:248-253` явный маршрут `/static/app.css`, `:331-339` HTML).
- **Диагностика:** `/healthz` отдаёт `{"status","version": APP_VERSION}` (`web/app.py:266-276`).

### 3.2. Решение T-2470
- **Bump `APP_VERSION`** `2.58.0 → 2.58.1` в `config/settings.py:1617` — единый согласованный cache-bust трёх ассетов (`tailwind.css`/`app.css`/`app.js`) + шрифт. Инвалидация клиента Telegram WebView — через новый URL `?v=`.
- **Обязательно синхронно:** `README.md:5` (`v2.58.0` → `v2.58.1`) — иначе `tests/test_webapp_round108_ui.py:225-229` (`test_app_version_matches_readme`) упадёт.
- **Рекомендуется** добавить `?v=__APP_VERSION__` к `telegram-init.js` (`index.html:3627`) как аддитивное усиление (не обязательно для закрытия дефекта — файл и так no-cache). Если менять — атомарно с тестами (`test_webapp_round108_ui.py:218-223`).
- **Не ломает:** `test_aliases_render_round1022.py:48` (читает `APP_VERSION` из константы), `test_smoke_round1016_miniapp_selfhost.py:72`, `test_webapp_api.py:1292-1302`, `test_webapp_dns_round1017.py:91` — все берут версию динамически. **Egress-guard** (`services/telegram_send.py`, `SEND_POINTS`) не затрагивается (правок отправки нет).

### 3.3. Верификация (T-2471/T-2472)
- **T-2471:** детерминированная проверка — `"/web/app.js?v=<APP_VERSION>"` и `"/static/app.css?v=<APP_VERSION>"` присутствуют в отрендеренном index, `__APP_VERSION__` не остаётся (есть базовые ассерты — расширить на согласованность версии index↔app.js↔app.css).
- **T-2472:** после деплоя (T-2478) открыть TMA, убедиться в network, что загружены ассеты новой версии, и что config-разделы открываются без `ReferenceError` в консоли.

---

## 4. LLM `ReadTimeout` — P1 (T-2473…T-2474)

- **Корень — провайдер** `nano-gpt.com` (primary + резервная модель одновременно в таймауте; хроническая картина). С F0 не связано.
- `services/llm_client.py:796-828` (`_fallback_with_retries`): `LLM_FALLBACK_TIMEOUT_SECONDS` default **120.0** (`config/settings.py:1079-1080`), `LLM_TIMEOUT` **30.0** (`:379`), `LLM_MAX_RETRIES` **2** (`:381`).
- **Действие:** (T-2467) обязательное обогащение лога; (T-2473) подстройка таймаутов/ретраев **только при обосновании** (числа до/после), иначе «не менять»; (T-2474) вывод по второму провайдеру + наблюдаемость доли таймаутов/fallback.
- **Не менять** контракт каскада и число физических вызовов System 2.

---

## 5. Смежная инфра/техдолг — P1/P2 (T-2475…T-2476)

WAL ~159 МБ (`wal_autocheckpoint`/`PRAGMA wal_checkpoint`), swap/RAM 961 МБ, медленный graceful-stop (`TimeoutStopSec=30`) — **вне ядра хотфикса**, отдельными решениями; в этом контуре только зафиксировать как техдолг. `database is locked` остаётся **0** (F0-контракт `write_transaction` не трогаем).

---

## 6. Регресс, деплой, верификация (T-2477…T-2480)

- **T-2477:** новые тесты + полный `pytest` = **7946/0**; JS = **19/19**; `node --check web/app.js` чист.
- **T-2478:** коммит(ы) русскими conventional commits (атомарно код+тесты) → push `origin/master` → `git pull --ff-only` → `systemctl restart admin_bot` (+ перезапуск **только** `telegram-bot-api` при медиа-фиксе); `/api/health` = 200.
- **T-2479/T-2480:** доказательства — файл > 20 МБ скачался/транскрибировался; версия ассетов новая, консоль чистая; логи содержат текст причины; pytest 7946/0; JS 19/19; `database is locked` = 0.

---

## 7. Возврат к F1 (T-2481)

Вернуть untracked из `var/backups/f1-wip-<ts>/` на места + `git stash pop` поверх задеплоенного хотфикса; сверить с тегом `pre-round1025-f1`. Конфликты — разрешить явно (ожидаемые: `web/index.html`/`web/app.js` вокруг `?v=` и APP_VERSION; `config/settings.py` вокруг `IA_V2_ENABLED`).

---

## 8. Как докажем фикс (verification)

| Дефект | Доказательство |
|---|---|
| Медиа/транскрибация | Реальное скачивание файла **> 20 МБ**: файл на диске в `TELEGRAM_API_FILES_DIR`, размер в логе; `getFile` поддерживает до 2000 МБ (local ON) |
| Cache-bust | В network клиента `app.js?v=2.58.1` / `app.css?v=2.58.1`; config-разделы открываются; консоль без `ReferenceError`; `/healthz.version` = новая |
| Диагностируемость | В логах виден **текст** причины (`TelegramBadRequest`/`ReadTimeout` с контекстом), без секретов |
| Регресс F0 | pytest **7946/0**, JS **19/19**, `database is locked` = **0** |

## 9. Риски и откат

| Риск | Ур. | Снятие |
|---|---|---|
| Потеря F1-WIP | Critical | T-2457 (stash) + T-2458 (бэкап untracked) ДО правок; тег `pre-round1025-f1` |
| Случайный коммит zip (~0.9 ГБ) | High | T-2459 фиксирует untracked-список; T-2460 `.gitignore` |
| Ложное «исправлено» по cache-bust | High | T-2470 не закрывать без T-2471/T-2472 (реальная проверка клиента) |
| Тихая деградация media-пути | High | T-2464 — эффективный лимит по режиму + ранняя понятная фраза |
| `--local` недоступен (диск/RAM 961 МБ) | High | Fallback-ветка T-2464: лимит 20 МБ + честная фраза (ADR-1025-6) |
| Утечка секретов в лог/отчёт | Critical | R17-safe логирование; `.env` вне git; `current_task.md` не цитировать (R17/R18) |
| Регрессия F0 | High | T-2480: pytest 7946/0, JS 19/19, `database is locked`=0; `write_transaction` не трогаем |

**Откат:** тег `pre-round1025-hotfix` + `git revert` коммита(ов); медиа — `TELEGRAM_LOCAL` вернуть в прежнее состояние (OFF = облачное поведение); cache-bust — вернуть `APP_VERSION`/README + повторный bump.

---

## 10. Покрытие задач
T-2456…T-2460 → §0; T-2461…T-2465 → §1 (ADR-1025-6); T-2466…T-2469 → §2; T-2470…T-2472 → §3; T-2473…T-2474 → §4; T-2475…T-2476 → §5; T-2477…T-2480 → §6; T-2481 → §7. **Все 26 задач покрыты.**

## 11. Открытые вопросы — рекомендации @Architect
1. **`--local` возможен?** → Да (том уже смонтирован, host==container path, клиент `is_local=True`); если RAM/диск не позволят — fallback на 20 МБ (ADR-1025-6).
2. **LLM таймауты?** → Не поднимать вслепую: сначала T-2467 (лог причины) → решение по данным; предпочтителен fail-fast, а не долгое ожидание.
3. **Cache-bust?** → Достаточно bump `APP_VERSION` (+README) — механизм уже даёт согласованный набор из трёх ассетов.
4. **Zip?** → `.gitignore` отдельным коммитом (T-2460); файлы не удалять.
5. **WAL/ресурсы?** → Вне ядра хотфикса, отдельной инфра-задачей.
6. **Продолжать F1?** → Да, после T-2481 (решение владельца/@PM).

## 12. Ссылки
- `plans/features/hotfix-media-tma-round1025/{tasks.md, adr-1025-6-bot-api-local-mode.md}`
- `plans/features/ia-shell-navigation-round1025/{spec.md, adr-1025-1-ia-v2.md}` (возврат F1, T-2481)
- `plans/ARCHITECTURE.md` §9/§52 (F0 save-слой — не трогать), `plans/round1025-architecture.md`
- Код: `docker-compose.yml`, `bot.py:230-231`, `services/media_download.py:116-152`, `handlers/youtube.py:138,1012-1047`, `services/llm_client.py:796-828`, `services/smartmodule_phrases.py:218-228`, `config/settings.py:379-381,1079-1080,1301-1321,1617`, `web/app.py:73-121,218-276`, `web/index.html:19,22,3624-3627` (база HEAD; F1-WIP смещает), `README.md:5`

---

## 13. Синхронизация после реализации (Merge/Шаг 7)

Хотфикс реализован (`8b16c4a` + `ee23e47`), @Scanner **0 Critical / 0 High**, задеплоен; фактические отличия от дореализационной спеки (для точности при архивации):

- **Режим Bot API — единый сигнал:** `docker-compose.yml:30` `TELEGRAM_LOCAL: "${TELEGRAM_LOCAL:-}"`; семантика — **непусто=local, unset/пусто=cloud**; **`0` не является «выключено»**. Паритет подтверждён по entrypoint образа (`append_flag_from_env`, `[ -n ... ]`). *(Low @Reviewer «host==container путь» — учтено: `TELEGRAM_API_FILES_DIR` = bind-source `./docker/telegram-bot-api`, absolute `file_path` валиден только внутри корня.)*
- **Гейт размера:** `handlers/youtube.py:160-197` — константы `LOCAL_GETFILE_LIMIT_MB=2000` / `CLOUD_GETFILE_LIMIT_MB=20` + `effective_video_max_size_mb()=min(configured, ceiling)`; ранний гейт до `fetch`.
- **Имя пула фраз (Low @Reviewer):** вместо `VIDEO_MEDIA_TOO_BIG_PHRASES` (больше не используется) — инкапсулированная функция **`video_too_big_phrase(limit_mb)`** (`services/smartmodule_phrases.py`); добавлен отдельный пул **`VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES`** (таймаут провайдера отделён от generic-ошибки).
- **`local_file_path`:** принимает абсолютный путь только внутри `TELEGRAM_API_FILES_DIR` (`_is_within_root` + `resolve().is_relative_to`), fail-closed; ср. §9.2.
- **Cache-bust:** `APP_VERSION` → **2.58.1** (`config/settings.py:1610`) + `README.md`; `?v=__APP_VERSION__` у `tailwind.css`/`app.css`/`app.js` **и `telegram-init.js`** (`web/index.html:3627`); `web/index.html` синхронизирован.
- **R17-логи:** `_safe_exc_text` (при пустом `str` → `repr`, маскировка, обрезка) в `handlers/youtube.py` и `services/llm_client.py`; `_provider_host` — только hostname.
- **Итоги:** pytest **7976/0** (+30 новых), JS **19/19**; прод: `TELEGRAM_LOCAL=1`, `APP_VERSION 2.58.1`, health 200, `database is locked`=0, WAL 159 МБ→0.
- **Остаточный техдолг:** M-1 (R17 в логе медиа — маскируется глобальным фильтром), M-2 (двойной рубильник `TELEGRAM_LOCAL`↔`DOWNLOAD_ENABLED`), LLM-таймауты (провайдер), RAM/swap/graceful-stop, `?v=` для 3 vendor-скриптов, точечный `.gitignore`. Подробно — `plans/ARCHITECTURE.md` §53.
