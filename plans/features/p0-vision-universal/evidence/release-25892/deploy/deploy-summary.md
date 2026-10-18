# Deploy 2.58.92 — run evidence (REL-25892)

Деплой-прогон: P0V FIX2 (V-FIX2) + ADD-TR FIX2 (TR-FIX2), релиз **2.58.92**.
Минимальный пост-смок; полная приёмка §4 — следующая волна.

## Биндинг и источник

| | |
|---|---|
| Кандидат (DEPLOY_SOURCE) | `1d367e4c561b5d1bc224c4c5ee64261945ed83bd` = origin/master tip (bump `2c28e2a1` внутри; V-FIX2 `f7a14994`, TR-FIX2 `9d310996`) |
| Прод до релиза | `f2a6248ae30d8e0b1878785bb6d1477f65e21c78` — 2.58.91 |
| Прод после | `1d367e4c561b5d1bc224c4c5ee64261945ed83bd` — ветка `master` |
| Скрипт деплоя | `deploy_25892.py` sha256_12 `10322d72a735` (reviewed) |
| J-скрипт | `rel92_final.sh` sha256_12 `bd4d91c2c7c2` (reviewed) |
| Пост-смок | `smoke92_readonly.py` (read-only, в scratch; dry-run с fake-SSH перед запуском) |
| Диагностика | 2 успешных SSH-коннекта (основной A–J; read-only смок); ретраев auth нет; креды не печатались |

## Версия до/после

- healthz до: `{"status":"ok","version":"2.58.91"}` (loopback, 23:25:38Z).
- healthz после: `{"status":"ok","version":"2.58.92"}` — loopback (F3 23:26:10Z,
  J 23:26:29Z, смок 23:38:34Z) и HTTPS (`HTTPS_HZ`, 23:26:33Z).

## A–J (по шагам прогона, сырьё — `deploy-run.txt`)

- **A pre-state** (23:25:38Z): `OLD_HEAD=f2a6248a`, `OLD_BRANCH=master`,
  `TRACKED_MOD=0`, `UNTRACKED=13` (унаследованные, не дельтой),
  `SERVICE=active`, `MAINPID=3508490`, `HZ_BEFORE=2.58.91`, `ENV_AXES=5`,
  `PROD_RUNTIME_DRIFT=0`, `INDEX_LOCK=absent`.
- **B fetch**: `FETCH1_RC=0`, `f2a6248a..1d367e4c origin/master`;
  `BUMP_IS_ANCESTOR=1`; tip = `1d367e4c`.
- **C checkout**: `CO_RC=0`, `NEW_HEAD=1d367e4c`, `TRACKED_MOD_AFTER=0`,
  `DELTA_TOTAL=107`; runtime-дельта **= ровно 7 файлов == RUNTIME_WHITELIST**
  (равенство множеств; чужого runtime нет).
- **D artifacts**: `HASH-CHECK: 12/12 == EXPECT12`; `APP_VER=2.58.92`;
  маркеры TR-FIX2 (`TRFIX_MEDIA_TARGET_ROUTER=4`, `_EXEC=1`, `_DCS=1`,
  `TRFIX_REPLY_SRC_ROUTER=3`, `_DCS=1`, `TRFIX_REFCLAIM_TF=1`, `_ROUTER=1`)
  и V-FIX2 (`VFIX_SCOPE=3`, `VFIX_CLAIM_ONCE=3`, `VFIX_MAINT=3`,
  `VFIX_429WINDOW=2`, `VFIX_GRANULE=3`, `VFIX_REARM=2`) — на месте;
  meta HEAD `f7a14994`.
- **F restart**: `RESTART_RC=0`, **T0=2026-10-18 23:25:48 UTC**
  (сервер: 2026-10-19 04:25:48 +05); healthz `2.58.92` наблюдён;
  журнал since T0 `ERROR|CRITICAL|Traceback` = **0** (F4).
- **G served bytes**: `SERVED_EQ_APP_JS=SAME` (`b14ef48ab16a`),
  `SERVED_EQ_APP_CSS=SAME` (`6d3ae1112d50`); `PAGE_VER=15` (ожидание 15),
  `SUBST_CSS=2` (ожидание 2).
- **J final (read-only, 23:26:29Z)**: `HEAD=1d367e4c`, `BRANCH=master`,
  `TRACKED_MOD=0`; `MainPID=3548159`, `NRestarts=0`, `ExecMainStatus=0`,
  `active/running`, start `23:26:01 UTC`; PAYLOAD SHA12 8/8 совпали с
  EXPECT12; FIX2- и регрессионные маркеры (VISION_URL/VIS/PROBE/CLAIM,
  ENTRY_CAPTION, TOOLS_HEALTH, POSTGEN_MODULE, CFG02B_FLAG, GRID_SPEECH,
  UI_VISION_LINE/FACTS, PINS_REISSUED, CFG_RESOLVER, CFG02A_RESERVE_MODE,
  SP_HUB_ENTRY, FULLSCREEN_POLICY) на месте; `/api/vision/state` → HTTP 401
  `{"detail":"missing init data"}` (штатный TMA-гейт, секретов не отдаёт);
  **`SKIPS=0`**, `CLAIM_SLOW=0`, `MAINT_TIMEOUT=0`, `VISION_TICK=1`;
  миграции `start current user_version=36 pending=[]` → `complete
  user_version=36 0.0s`, `USER_VERSION (36,)` — **Δ DDL=0**; journal since T0:
  `ERR=0`, `RUNTIMEWARN=0`, `GRACEFUL=2`, `POLLER=1`, `VISION_PROBE_FAIL=0`,
  `VISION_EVENTS=0`; HTTPS-маршруты `/healthz` 200, `/web/` 200,
  `/static/app.css` 200; `HTTPS_HZ=2.58.92`.
- **S post-smoke (read-only, 23:38:34Z — T0+12:46, окно ≥10 мин)**:
  `HEAD=1d367e4c`, `DRIFT_TO_ORIGIN=0`, `TRACKED_MOD=0`, ветка `master`;
  `MainPID=3548159` (стабилен с деплоя), `NRestarts=0`, `active/running`;
  healthz `2.58.92`; `CODE_WEB=200`, `CODE_CSS=200`, `CODE_VSTATE=401`
  `{"detail":"missing init data"}`; журнал since T0: `ERR_CRIT_TRACEBACK=0`,
  `COUNT_402=0`, raw-выборка ERROR/CRITICAL/Traceback/402 пуста;
  **`SKIPS=0`**, `MAINT_TIMEOUT=0`; `CLAIM_SLOW=3` (см. замечания);
  `VISION_LINES=307` — INFO-тики `VisionMediaWorker._tick` (5 c,
  `executed successfully`) + WATCHDOG_SWEEP success — воркер жив;
  served SAME (`b14ef48ab16a` / `6d3ae1112d50`), `PAGE_VER=15`,
  `SUBST_CSS=2`; миграции start/complete `user_version=36`; `USER_VERSION (36,)`.
  Отдельный read-only прогон: `post-smoke-readonly.txt`.

## Warnings / откат

- **WARNINGS: 0**; abort нет; tree-restore не вызывался; авто-откат не
  вызывался; сервис поднялся с первого раза (NRestarts=0).
- Рубежи отката (не использованы, готовы): `release/fix-2.58.91`
  (`f2a6248a`, 2.58.91; также цель tree-restore при abort ДО рестарта),
  `release/fix-2.58.90` (`3b02366e`, 2.58.90), штатный авто-рубеж
  `release/cfg1-2.58.88` (2.58.88). Прод-ветка после деплоя — `master`.

## Замечания и остатки

- `[vision] claim sweep slow` = 3 за ~13 мин (в J-окне 0) — по контракту
  §4(b) **допустимо**: это WARNING-наблюдаемость медленной claim-фазы
  (≥5 c), тик больше НЕ пропускается (`SKIPS=0`); `claim sweep timeout` и
  `maintenance stage timeout` не наблюдались. Для live-волны: посмотреть
  частоту при живой очереди (это же — критерий очереди, §4(b)).
- `/api/vision/state` без initData — штатный 401-гейт (прецеденты всех
  релизов линии), секретов в ответе нет. Живая авторизованная витрина —
  чек §4(c) следующей волны.
- `ENV AXES` (.env) = 5, как и до релиза; деплой `.env` не менял.
  Включение/проверка ON-ветвей — приёмка §4.
- Прозрачность канала: 2 успешных SSH-коннекта (основной A–J, read-only
  смок). Первый запуск смок-скрипта прервался **локальной** ошибкой
  форматирования сразу после auth, до отправки команд (на сервере ничего не
  выполнялось; исправлено локальным dry-run с fake-SSH, затем один чистый
  коннект). Без ретраев auth, без банов.
- Полная приёмка §4 (живые tool calls/Telegram-доставка, per-chat state
  с пробой, reply-на-фото, «это правда?», проба/429, уборка, экономика,
  WebView) — **следующая волна**, не в этом прогоне. Карта P0V:
  2 пункта `READY_FOR_LIVE` (postdeploy: P0V-ARCH-ENDPOINTS,
  P0V-ARCH-SWITCH), 5 `PENDING` (preprod); map не strict — release-гейт
  запускается после live-волны.

## Файлы и контрольные суммы (sha256_12)

| файл | sha256_12 |
|---|---|
| `deploy-run.txt` (A–J лог, scrubbed) | `593e1508dd5f` |
| `final-verification.txt` (J read-only) | `8df8c02ed7dd` |
| `post-smoke-readonly.txt` (S read-only) | `ced52ec9a6ac` |
| этот файл — `deploy-summary.md` | см. коммит `docs(p0v): deploy 2.58.92 run evidence` |

Источник сырья: `%OPENCODE_WORKFLOW_SCRATCH%\release-25892\logs\`
(scratch; в репозиторий промотированы только эти три файла + сводка).
