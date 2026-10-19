# Релиз **2.58.94** — VISION-DL-FIX: скачивание файлов локального Bot API (vision download→decode)

Дата сборки кандидата: 2026-10-19 (UTC; по логам прогонов ниже).
Кандидат: **master-линия** (код-коммит DL-FIX `7c2998b1`; следом docs-only
`34476660` — deploy-evidence 2.58.93) + bump `70659be3`;
прод до релиза — **`2.58.93 @ b4d30cab`**
(ветка рубежа `release/fix-2.58.93` создана локально на `b4d30cab`).
Статус: **собран и проверен локально**; деплой и приёмка — отдельный шаг (§4).
Задача: RELEASE-PKG-94 (релиз-пакет; без деплоя/SSH-записей).
Верификация — в **изолированном чистом worktree** от bump-коммита
(`OPENCODE_WORKFLOW_SCRATCH\release-25894\wt` @ `70659be3`); главное дерево
для прогонов кандидата не использовалось.

## 1. Состав (что вошло)

| Линия | Коммит | Что это по-человечески |
|---|---|---|
| DL-FIX (код) | `7c2998b1` | Все vision-джобы умирали на `stage=download` (приёмка 2.58.92: `64 skipped + 32 failed`, `mca_media_analyses` пуст): локальный Bot API (`--local`) отдаёт в `getFile` **абсолютный путь внутри своего контейнера** (`/var/lib/telegram-bot-api/<token>/…`), а aiogram при `is_local=True` читает этот путь с ФС **хоста**, где каталога нет (он существует только как bind-mount контейнера) → `FileNotFoundError`. HTTP-скачивание локального сервера в `--local` не обслуживается (404 во всех вариантах пробы). Фикс: новый `services/local_bot_api.py` — фабрика сессии `build_local_api_session` (`is_local=True` + fail-safe обёртка `HostFilesPathWrapper`: контейнерный путь → host-каталог `TELEGRAM_API_FILES_DIR` — **та же нормализация**, что прод-проверенная для голосовых/видео в `services/media_download.py`; относительный/чужой абсолютный/сам корень возвращаются как есть, без `ValueError`); `bot.py` собирает локальную сессию **только** через фабрику (прямые импорты `AiohttpSession`/`TelegramAPIServer` убраны); стартовая диагностика читаемости host-каталога — R17-safe WARNING/INFO с маркером `[local-bot-api] файлы: … (container /var/lib/telegram-bot-api)`. Облачный режим (`DOWNLOAD_ENABLED=false`) не затронут; API-вызовы не менялись (та же локальная база). Δ DDL = 0, Δ каталога = 0. |
| Доки | `34476660` | Deploy-evidence 2.58.93 (plans-only, runtime не менялся). |
| Bump/F8 | `70659be3` | `2.58.93 → 2.58.94`: settings + README + F8-meta (APP_VERSION `2.58.94`, HEAD-штамп `7c2998b1` — последний код-коммит кандидата; прецедент 2.58.91 `88593e9a` при docs-only хвосте; docs-only `34476660` следует за ним) + 24 py-пина + 4 JS-пина = 31 файл (+33/−33, версионно-чистый — `bump-verify.txt`; «2.58.93» вне `plans/` не осталось, включая escaped-пины `2\.58\.93` в JS). |

Ревью фикса: `review-dl-fix.md` (коммит `02e817d9`) — **Approved**: корень
доказан прод-диагностикой/пробой (read-only), `HostFilesPathWrapper` ==
нормализация `media_download`, fail-safe, контракт на реальном aiogram,
RED 1f/6p → GREEN 7/7, свод-195 точным совпадением, профиль media 556,
`t5150` — пре-сущ., R17-скан 0.

## 2. Дельта к проду (изоляция)

База = прод `b4d30cab` (2.58.93). Полная дельта после bump-коммита
(включая `plans/**`) = **49 файлов**; без `plans/**` — **33**
(`delta-non-plans.txt`):

- **3 runtime-файла** — ровно они и есть вайтлист деплой-скрипта (любой
  другой runtime-файл в дельте = abort; сверка равенства множеств офлайн:
  PASS, `deploy-offline-check.txt`): `bot.py`,
  `services/local_bot_api.py` (**новый**), `config/settings.py` (bump-версия)
  (runtime-stat: 3 файла, **+166/−6** — `delta-runtime-stat.txt`);
- **29 файлов `tests/`** = новый контрактный `tests/test_vision_dl_fix.py`
  (7 тестов) + 24 py-пина + 4 JS-пина (bump);
- `README.md` — 33-й не-плановый файл;
- плюс `plans/**` (16 файлов: F8-meta из bump-набора + 15 доков/evidence,
  накопленных линией 2.58.93→DL-FIX — deploy-evidence `34476660` и
  `evidence/dl-fix/**`, `review-dl-fix.md`).

Sanity-файлы обязаны остаться байт-в-байт прод-2.58.93: `services/telegram_send.py`
`e23bced2fdb8`, `web/static/fullscreen-policy.js` `96db06425079`,
`services/prompt_composer.py` `fd8a2a70d5d7` — сверено (в дельте их нет;
побайтовое равенство прод-версиям подтверждено).

## 3. Проверки кандидата (run-as-is, в изолированном worktree от bump-коммита)

| Проверка | Результат |
|---|---|
| Полный `pytest -q` (чистый прогон, без конкурентной нагрузки) | **9 failed / 14473 passed** (741.60s); все 9 — пре-сущ. (5×`t5150`, 2×`asap7_direct_settings`, 1×`mca01_tx_task_supervisor`, 1×`history_cli` worktree-env); env-флейк random_source-класса в этом прогоне **не сработал**; баланс с базой 2.58.93 (10f/14465p): +7 passed = новые тесты DL-FIX, +1p/−1f = флейк (атрибуция — `pytest-attribution.txt`) |
| `tests/test_vision_dl_fix.py` (DL-FIX контракт) | **7 passed** (5.00s) |
| Свод-195: vision core + mca19 A–G + rework + addtr_postgen | **195 passed** (22.06s) — точное совпадение с dl-fix sweep |
| Профиль media/download/voice/video/avatars (25 файлов; надмножество 556-класса REV-DL-FIX) | **741 passed** (27.93s) |
| `tests/test_t5150_startup_migrations_round1046.py` | **5 failed / 2 passed** — пре-сущ. (подтверждено на базе без фикса; см. §6) |
| F8-пара (py): `test_round1025_f8_registry.py` | **29 passed** (3.69s) |
| F8-пара (каталог): `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 579 == REGISTRY** (R17-чисто, TSV/map идемпотентны) |
| JS-sweep: `node tests/js/*_test.js` (88 файлов) | **88 файлов / 0 падений** |
| Офлайн-сверка деплой-скрипта (hashes 8/8, вайтлист==дельта 3/3, BUMP==HEAD, upload) | **EXIT 0** |
| Bump-verify (каждая изменённая строка = только версия/HEAD-штамп) | **OK: 31 файл, 31 пара строк** |

Артефакты: `focused-blast.txt` + `focused-s1…s6`, `js-sweep.txt`,
`bump-verify.txt`, `frozen-fingerprint.txt`, `markers-candidate.txt`,
`delta-*.txt`, `deploy-offline-check.txt`, `pytest-full.txt`,
`pytest-attribution.txt`.

## 4. Чек-лист пост-деплойной приёмки

Выполняет деплой/приёмка-лейн ПОСЛЕ выката; дисциплина fail2ban: один recon +
один основной коннект, без ретраев; HTTP — `https://admin-bot.duckdns.org/healthz`.
Все проверки — read-only или контролируемые, **без лишних платных вызовов**.

**(a) healthz + T0 + журнал + SKIPS=0 + стартовый маркер DL-FIX.**
`healthz` = `2.58.94` (loopback и HTTPS), MainPID сменился; журнал since T0:
`ERR/CRIT/Traceback = 0`, RuntimeWarning/«never awaited» = 0, `database is
locked` = 0; миграции `complete`, `user_version` без изменений (Δ DDL=0);
**SKIPS=0** (линия 2.58.92: «maximum number of running instances» = 0);
**обязательный маркер DL-FIX после рестарта**:
`[local-bot-api] файлы: … (container /var/lib/telegram-bot-api)` — ≥1
(`LOCAL_BOT_API_MARKER` в `rel94_final.sh`; WARNING-вариант «каталог файлов не
читается» должен быть 0 — иначе host-каталог недоступен процессу бота,
эскалация по инфра-инструкции README dl-fix §2).
Источник: `deploy_25894.py` (F3/F4/F5/J) + `rel94_final.sh`.

**(b) ПОЛОЖИТЕЛЬНОЕ распознавание (главная приёмка DL-FIX).**
Свежее фото в чат → `recognize_image` → цепочка `download → decode → vision →
store` проходит; **`mca_media_analyses` наполняется** (`MCA_ANALYSES_TOTAL`
растёт, статусы `ready`/`no_text` — валидные; `unavailable`/`failed` не
доминируют); описание доставлено в чат (five-facts: что/кто/где/детали/фон —
без выдумок). Контроль «до/после» — `rel94_final.sh` (read-only счётчики) +
журнальные `VISION_*` события; `stage=download` для НОВЫХ джоб не появляется
(исторические `stage=download` до рестарта — не считаются регрессией).

**(c) postgen: описание по финальному bitmap (не эхо).**
1 генерация изображения → postgen-vision описывает ИТОГОВУЮ картинку (не
промпт-эхо): сравнение описания с промптом — не совпадение дословное;
`POSTGEN_MODULE=1` + маркеры `IMAGE_POSTGEN_VISION_ENABLED`; 1 вызов vision на
1 генерацию (bounded), дедуп не сломан.

**(d) уборка тестовых сообщений.**
Все тестовые сообщения/картинки приёмки удалить в чатах после прогонов
(правило владельца; прецедент — `accept91_cleanfinal.py`); evidence
(message_id/скрин) — до удаления.

**(e) экономика/журнал.**
Списания/квоты по логу не превышены; `IMAGE_*`/`COVER_*`/`TOOL_CALL`/
`VISION_*` в норме; `ERR/CRIT/402 = 0`; дедуп ответов не сломан;
`GET /api/workers/budget` и `/api/vision/state` отдают данные без утечки
секретов (R17).

## 5. Откат

**Рубежи (по убыванию близости):**
- `release/fix-2.58.93` (`b4d30cab`, 2.58.93) — пред-релизная линия прода;
  создана локально под этот релиз (deploy: tree-restore при abort ДО рестарта).
- `release/fix-2.58.92` (`1d367e4c`, 2.58.92) — предыдущий рубеж.
- `release/cfg1-2.58.88` (`c37b8577`, 2.58.88; tip ветки `35789982`) —
  **штатный рубеж авто-отката деплой-скрипта** (путь ПОСЛЕ рестарта при
  неполучении healthz 2.58.94 / пустом T0).
Abort ДО рестарта (whitelist/дельта/хеши) отката не ждёт: `_tree_restore`
возвращает дерево к прод-линии 2.58.93 (`release/fix-2.58.93` / точный
`PROD_REF` detach, без рестарта) — downgrade исключён.
Мягких kill-switch'ей этот релиз не вводит (DL-FIX — код-фикс без флагов):
«мягкая дверь» — возврат кода на ветку-рубеж (cold); прежние
per-chat/env-переключатели (CFG-02B, Vision, Direct) не меняются.
Альтернатива при отказе новой сессии: `DOWNLOAD_ENABLED=false` в `.env` +
рестарт возвращает прежний облачный путь `Bot(token=...)` (без локальной
сессии) — легаси-поведение сохранено в коде.

## 6. Риски/остатки (честно)

1. **`t5150` ×5 (пре-сущ.)**: устаревший ожидаемый список миграций —
   воспроизведено и на базе без фикса (`review-dl-fix.md` §3), файл дельтой
   не тронут. Не регрессия.
2. **Пре-сущ. падения полного pytest — ровно 9** (этот прогон: 9 failed /
   14473 passed): `asap7_direct_settings` ×2, `mca01_tx_task_supervisor` ×1,
   `t5150` ×5, environment-артефакт `test_history_cli::test_scope_is_required`
   в чистом worktree. Известный env-флейк random_source под SQLite-lock
   (в каждом прогоне разный тест, зелёный в изоляции) в этом прогоне
   **не сработал** — см. `pytest-attribution.txt`; при повторных прогонах
   допустимо 10-е падение этого класса (не регрессия).
3. **Чтение host-каталога процессом бота**: прод — `User=root`, каталог
   `messagebus:lxd` читается (тот же каталог уже используется прод-путём
   голосовых/видео); при смене пользователя бота — инфра-инструкция
   (`evidence/dl-fix/README.md` §2).
4. **HTTP-эндпоинт скачивания локального сервера** остаётся 404 — при нужде
   в HTTP-пути потребуется reverse-proxy (отдельный инфра-контур); для
   текущего фикса не требуется (файл читается по ФС).
5. **Проба «B» под SSH-пользователем** упала `PermissionError` (каталог
   `messagebus:lxd`, бот — root): прямой прод-прогон маппинга под ботом не
   выполнялся; это закрывает приёмка §4(b) на живом проде.

## 7. Деплой-артефакты (подготовлены, НЕ запускались)

- `C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\
  release-25894\deploy_25894.py` — sha256_12 **`4eb764c8ba0f`** (T0-hardened clone
  `deploy_25893.py`/`ab71cc472dd7`; NF-фиксы сохранены: checked_out-гейт
  tree-restore, set-equality вайтлиста, tree-restore к прод-линии 2.58.93,
  WARNINGS-summary, SERVED_EQ; отличие: runtime-дифф-фильтр включает `bot.py`
  — файл в корне, вне `config/services/web/handlers`): A pre-state →
  B fetch origin/master (BUMP-ancestor gate) → C checkout + runtime-whitelist
  дельты (3 файла) → D sha256_12 (8 артефактов: 3 runtime + README + meta +
  3 sanity) + маркеры DL-FIX и регрессионные линии 2.58.93/92/91 →
  F restart + T0 + healthz 2.58.94 + журнал + `[local-bot-api]`-маркер →
  G served-bytes → J `rel94_final.sh`.
- `rel94_final.sh` — sha256_12 **`b788f5e79dfd`** (read-only; DL-FIX-маркеры с
  ожиданиями, `LOCAL_BOT_API_MARKER`, read-only `mca_media_analyses` счётчики,
  SKIPS-контроль, регрессионные маркеры CFG-02C/2.58.92/2.58.91, SERVED_EQ,
  PAGE_VER/SUBST_CSS, `/api/workers/budget`, `/api/vision/state`).
- Офлайн-сверка констант скрипта с кандидатом: `check_deploy_25894.py`
  **EXIT 0** (hashes 8/8, вайтлист == дельта 3/3, BUMP == HEAD, uploads на
  месте) — `deploy-offline-check.txt`.
- Авто-откат ПОСЛЕ рестарта: `release/cfg1-2.58.88`; abort до рестарта →
  `_tree_restore` к прод-линии 2.58.93 (`release/fix-2.58.93`/`b4d30cab`).
- **Предусловие запуска:** `master` запушен в origin с bump-коммитом 2.58.94
  (B3 fail-closed, иначе прод не трогается). Ветку `release/fix-2.58.93` при
  выкате желательно запушить (иначе tree-restore идёт fallback-detach'ем на
  `b4d30cab` — объект уже есть на проде).

## 8. Кандидат-фингерпринт

- tip master / bump-коммит: `70659be3` (2.58.94) — дерево кандидата заморожено им.
- **После сборки пакета** master получил один plans-only docs-коммит (этот
  отчёт + `evidence/release-25894/**`; 19 файлов, все под `plans/`) — runtime
  не изменился: дельта `b4d30cab..HEAD` по `config/services/web/handlers/bot.py`
  = те же **3 файла**; 8/8 артефактов `EXPECT12` на текущем HEAD совпадают с
  `frozen-fingerprint.txt`; `70659be3` — ancestor HEAD (B3-гейт пройдёт).
- Последний код-коммит: `7c2998b1` (DL-FIX); доки — `34476660` (deploy-evidence 2.58.93, plans-only).
- Прод-базис: `b4d30cab` (2.58.93); ветка откатного рубежа `release/fix-2.58.93`.
- sha256_12 8 артефактов — в `deploy_25894.py::EXPECT12` и
  `evidence/release-25894/frozen-fingerprint.txt` (+ полные sha256 там же):
  `bot.py f9d8306e6034`, `services/local_bot_api.py a97e1d3eeab0`,
  `config/settings.py 94b22606a68d`, `README.md f3acd3e0645b`,
  `meta 0f622688098f` + sanity `e23bced2fdb8`/`96db06425079`/`fd8a2a70d5d7`.
