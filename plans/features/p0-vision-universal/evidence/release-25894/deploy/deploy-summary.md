# DEPLOY-25894 — evidence: выкат 2.58.94 (VISION-DL-FIX) + пост-смок

Релиз: **2.58.94** — VISION-DL-FIX: скачивание файлов локального Bot API
(контейнерный `/var/lib/telegram-bot-api/<…>` → host-каталог bind-mount
`TELEGRAM_API_FILES_DIR`; фабрика `services/local_bot_api.build_local_api_session`
+ fail-safe `HostFilesPathWrapper`; `bot.py` собирает локальную сессию только
фабрикой). Приёмка §4 (b)–(e) — следующая волна.

- Утверждённый кандидат: `9072347b986b91f05d580a11c1aae6646b250e29`
  (= `origin/master` tip; review-коммит `9072347b`; bump `70659be3`, код DL-FIX
  `7c2998b1`; docs-only хвост после bump — plans/**).
- Прод ДО: `b4d30cab364e920d453d2d6a2afe2f95e1c24834` (2.58.93, healthz 2.58.93,
  HTTPS-проверка перед выкатом) → ПОСЛЕ: `9072347b` (2.58.94).
- **Server-reported HEAD после выката = `9072347b…`** — совпадает с утверждённым
  кандидатом (три независимых среза: C-стадия checkout, J-стадия деплоя,
  пост-смок).
- DEPLOY_SOURCE: `origin/master` (иммутабельный коммит; push выполнен до выката,
  B3-ancestor пройден; `release/fix-2.58.93` @ `b4d30cab` запушена). Mutable
  worktree **не требуется**; деплой репо не изменяет (пишет только scratch-логи
  на DevOps-машине).
- Инструменты: `deploy_25894.py` sha256_12 **`4eb764c8ba0f`** (режим `main`,
  ровно 1 SSH-коннект; abort-ветки tree-restore/rollback не запускались);
  `rel94_final.sh` **`b788f5e79dfd`** (read-only probe; J-стадия + пост-смок);
  `smoke94_readonly.py` **`47292388664c`** (read-only, 1 SSH-коннект).

## Режимы и rc

| режим | rc | результат |
|---|---|---|
| main | 0 | checkout `9072347b`, restart, healthz 2.58.94, J-стадия OK |
| post-smoke (read-only) | 0 | журнал/маркеры/served/миграции/дрифт — все ожидания сошлись |

Recon-коннект не выполнялся (лейн — один основной прогон; доступность прода
проверена HTTP/HTTPS). T0 (рестарт, UTC): **2026-10-19 08:18:20**;
MainPID: 3635488 → **3657672** (NRestarts=0, active/running,
ExecMainStartTimestamp 08:18:33Z; в пост-смоуке PID тот же — без перезапусков).

## Ключевые проверки (main 08:18–08:19Z + post-smoke 08:22:53Z)

- healthz loopback **и** HTTPS = `2.58.94`; маршруты HTTPS 200/200/200.
- Изоляция дельты: `DELTA_RUNTIME` 3/3 == whitelist (set-eq): `bot.py`,
  `config/settings.py`, `services/local_bot_api.py`; `TRACKED_MOD_AFTER`=0;
  `EXPECT12`-хэши **8/8**; `APP_VERSION="2.58.94"`; F8-meta HEAD `7c2998b1`.
- DL-FIX-маркеры deployed bytes **8/8** (WRAPPER=3, FACTORY=1, CONTAINER_ROOT=3,
  HOST_ROOT=3, READABLE=2, BOT_FACTORY=2, BOT_RAW=0, MARKER_SRC=1);
  регрессионные маркеры контура 2.58.93/92/91: CFG-02C 15/15, 2.58.92 13/13,
  2.58.91 16/16 — все на месте.
- Журнал since T0: ERR/CRITICAL/Traceback=**0**, `402`=**0** (raw-выборка
  ERR/402 пуста), RuntimeWarning=0, SKIPS=**0** («maximum number of running
  instances»), GRACEFUL=2, POLLER=1, VISION_PROBE_FAIL=0.
- **F5-маркер DL-FIX (обязательный)**: `LOCAL_BOT_API_MARKER`=**1**,
  `LOCAL_BOT_API_WARN`=0 — `[local-bot-api] файлы: … (container
  /var/lib/telegram-bot-api)` в журнале после рестарта.
- ENV (.env): `DOWNLOAD_ENABLED=True`, `TELEGRAM_LOCAL=1`,
  `LOCAL_BOT_API_URL=http://localhost:8081`,
  `TELEGRAM_API_FILES_DIR=docker/telegram-bot-api`.
- Served: `SERVED_EQ_APP_JS=SAME`, `SERVED_EQ_APP_CSS=SAME`, `PAGE_VER`=**15**,
  `SUBST_CSS`=**2**, `SCOPE_LABEL_SERVED`=1.
- Дрифт=0: `TRACKED_MOD`=0, `DRIFT_TO_ORIGIN`=0, A-pre `PROD_RUNTIME_DRIFT`=0.
- Миграции: `pending=[]`, `user_version=36` (ΔDDL=0; база 36), migrations
  `complete` (0.0s).
- MCA baseline (read-only, для приёмки (b)): `MCA_ANALYSES_TOTAL`=0,
  `BY_STATUS`=[], `MCA_ASSETS_TOTAL` 3330→3331 (одна новая медиа-запись за
  окно); `VISION_DL_STAGE`=0; `VISION_EVENTS`=3 (не ошибки — raw-выборка
  ERR/CRIT/TB/402 пуста). Положительная цепочка download→decode→vision→store
  проверяется приёмкой (следующая волна).

Warnings: нет (WARNINGS-SUMMARY пуст; tree-restore/rollback не запускались).

## Откат

- Abort до рестарта: `_tree_restore` → прод-линия `release/fix-2.58.93` @
  `b4d30cab` (запушена; fallback — detach `b4d30cab`) — **не потребовался**.
- Abort после рестарта: авто-рубеж `release/cfg1-2.58.88` (2.58.88) —
  **не потребовался**.
- Готовность отката сохраняется: `release/fix-2.58.93` (b4d30cab) и
  `release/cfg1-2.58.88`; мягкая альтернатива — `DOWNLOAD_ENABLED=false`
  (легаси-облачный путь).

## Остаток

- §4-приёмка (b)–(e) — следующая волна (объединённая CFG-02C §Ф6 + positive
  vision): положительное распознавание, наполнение `mca_media_analyses`,
  five-facts доставка, postgen по bitmap, уборка, экономика. Пункты карты
  `READY_FOR_LIVE` — за ней; родительский DONE — только после неё.
  Пункт §4(a) (healthz/T0/SKIPS=0/маркер) закрыт этим выкатом.

## Файлы (sha256_12)

- `deploy-run.txt` **`ea6cef8826da`**; `final-verification.txt`
  **`a66980aa09f9`**; `post-smoke94.txt` **`d1a582231386`**.
- Прогон: 2026-10-19 08:18:11Z – 08:22:56Z UTC.

Примечание: read-only API-пробы без TMA-заголовка вернули
`{"detail":"missing init data"}` (ожидаемая auth-заглушка, не дефект).
`UNTRACKED=13` на проде — pre-existing.
