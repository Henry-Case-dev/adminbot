# Deploy 2.58.91 — run evidence (REL-25891)

Деплой-прогон: P0V (core/UI) + ADD-TR (ENTRY/GRID/TOOLS/POSTGEN) +
CFG-02B + P0-FU, релиз **2.58.91**. Минимальный пост-смок; приёмка §4 —
следующая волна.

## Биндинг и источник

| | |
|---|---|
| Кандидат (DEPLOY_SOURCE) | `f2a6248ae30d8e0b1878785bb6d1477f65e21c78` = origin/master tip (bump `8bc8e9b5` внутри) |
| Прод до релиза | `3b02366e63022eb4c760892aa1bcb4f26516e789` — 2.58.90 |
| Прод после | `f2a6248ae30d8e0b1878785bb6d1477f65e21c78` — ветка `master` |
| Скрипт деплоя | `deploy_25891.py` sha256_12 `caeebf41f201` (reviewed) |
| J-скрипт | `rel91_final.sh` sha256_12 `c41f1d5d17c9` (reviewed) |
| Dиагностика | 1 основной SSH-коннект + 1 read-only смок-коннект; ретраев нет; креды не печатались |

## Версия до/после

- healthz до: `{"status":"ok","version":"2.58.90"}` (HTTPS, 20:11 UTC).
- healthz после: `{"status":"ok","version":"2.58.91"}` — loopback и HTTPS
  (`HTTPS_HZ`), 20:12:27 и повторно 20:14:52 UTC.

## A–J (по шагам прогона, сырьё — `deploy-run.txt`)

- **A pre-state** (20:11:35Z): `OLD_HEAD=3b02366e`, `OLD_BRANCH=master`,
  `TRACKED_MOD=0`, `PROD_RUNTIME_DRIFT=0`, `INDEX_LOCK=absent`,
  `SERVICE=active`, `MAINPID=3430462`, `HZ_BEFORE=2.58.90`, `UNTRACKED=13`
  (унаследованные, не дельтой).
- **B fetch**: `FETCH1_RC=0`, `3b02366e..f2a6248a origin/master`;
  `BUMP_IS_ANCESTOR=1`; tip = `f2a6248a`.
- **C checkout**: `NEW_HEAD=f2a6248a`, `TRACKED_MOD_AFTER=0`,
  `DELTA_TOTAL=330`; runtime-дельта **= ровно 24 файла == RUNTIME_WHITELIST**
  (равенство множеств; чужого runtime нет).
- **D artifacts**: `HASH-CHECK: 29/29 == EXPECT12`; `APP_VER=2.58.91`;
  маркеры P0V/ADD-TR/CFG-02B/P0-FU присутствуют (`VISION_URL=4`,
  `VISION_VIS=2`, `VISION_PROBE=5`, `VISION_CLAIM=5`, `ENTRY_CAPTION=4`,
  `TOOLS_HEALTH=6`, `POSTGEN_MODULE=1`, `POSTGEN_FLAG=3`, `CFG02B_FLAG=3`,
  `CFG02B_BUCKET=3`, `GRID_SPEECH=5`, `UI_VISION_LINE=2`,
  `UI_VISION_FACTS=2`, `UI_PROV_CONTAINER=1`, `PINS_REISSUED=2`,
  `INIT_WINDOW=7`); meta HEAD `88593e9a`.
- **F restart**: `RESTART_RC=0`, **T0=2026-10-18 20:11:46 UTC**
  (сервер: 2026-10-19 01:11:46 +05); healthz `2.58.91` наблюдён;
  журнал since T0 `ERROR|CRITICAL|Traceback` = **0**.
- **G served bytes**: `SERVED_EQ_APP_JS=SAME`, `SERVED_EQ_APP_CSS=SAME`;
  `PAGE_VER=15` (ожидание 15), `SUBST_CSS=2` (ожидание 2).
- **J final (read-only, 20:12:27Z)**: `HEAD=f2a6248a`, `BRANCH=master`,
  `TRACKED_MOD=0`; healthz `2.58.91`; `MainPID=3508490`, `NRestarts=0`,
  `ExecMainStatus=0`, `active/running`, start `20:11:57 UTC`;
  маркеры + regression-маркеры (CFG resolver/reserve, SP hub/route,
  fullscreen, SOUL-W6) на месте; served SAME; PAGE 15/2;
  **`/api/vision/state` → HTTP 401 `{"detail":"missing init data"}`
  (штатный TMA-гейт, секретов не отдаёт)**; миграции
  `start current user_version=36 pending=[]` → `complete user_version=36
  0.0s`, `USER_VERSION (36,)` — **Δ DDL=0**; journal since T0:
  `ERR=0`, `RUNTIMEWARN=0`, `GRACEFUL=2`, `POLLER=1`,
  `VISION_PROBE_FAIL=0`, `VISION_EVENTS=0`; HTTPS-маршруты
  `/healthz` 200, `/web/` 200, `/static/app.css` 200.
- **S post-smoke (read-only, 20:14:52Z — через ~3 мин после T0)**:
  `DRIFT_TO_ORIGIN=0`, `TRACKED_MOD=0`, `HEAD=f2a6248a`, ветка `master`;
  `MainPID=3508490`, `NRestarts=0` (стабилен), `active/running`;
  healthz `2.58.91`; `CODE_WEB=200`, `CODE_CSS=200`,
  `CODE_VSTATE=401`; журнал since T0: `ERR_CRIT_TRACEBACK=0`,
  `COUNT_402=0`, raw-выборка ERROR/CRITICAL/Traceback/402 пуста;
  `VISION_LINES=70` — это INFO-тики `VisionMediaWorker._tick`
  (interval 5 c, `executed successfully`) — воркер жив; ошибок нет.
  Отдельный read-only прогон: `post-smoke-readonly.txt`.

## Warnings / откат

- **WARNINGS: 0**; abort нет; tree-restore не вызывался; авто-откат не
  вызывался; сервис поднят с первого раза.
- Рубежи отката (не использованы, готовы): `release/fix-2.58.90`
  (`3b02366e`, 2.58.90), `release/fix-2.58.89` (`d59fab94`), штатный
  `release/cfg1-2.58.88` (2.58.88). Прод-ветка после деплоя — `master`.

## Замечания и остатки

- `/api/vision/state` без initData — штатный 401-гейт (прецеденты всех
  предыдущих релизов: «missing init data — штатная авторизация»).
  Секретов в ответе нет. Заполненность `provider/model/api_type` в
  авторизованном ответе здесь не наблюдается (нужен Telegram initData);
  схема `runtime_snapshot` (provider/model/api_type/source/base_url,
  без полей-ключей) входит в hash-анкеренные байты 2.58.91 и проверена
  UI-e2e кандидата (`evidence/ui/p0v-ui-evidence.md` §4). Живая
  авторизованная витрина — чек §4(d) следующей волны.
- `ENV AXES` (.env) = 5, как и до релиза; `IMAGE_FREQ_LIMIT_ENABLED` /
  `IMAGE_POSTGEN_VISION_ENABLED` в .env не заданы → заводской OFF,
  деплой .env не менял. Включение/проверка ON-ветвей — приёмка §4.
- Приёмка §4 (live tool calls/Telegram-доставка, postgen, grid/Vision-UI
  на прод-странице, SCEN-B, экономика) — **следующая волна**, не в этом
  прогоне. Карта P0V: 2 пункта `READY_FOR_LIVE` (postdeploy:
  P0V-ARCH-ENDPOINTS, P0V-ARCH-SWITCH), 5 `PENDING`; map не strict —
  release-гейт запускается после live-волны.

## Файлы и контрольные суммы (sha256_12)

| файл | sha256_12 |
|---|---|
| `deploy-run.txt` (A–J лог, scrubbed) | `e3694fffaf97` |
| `final-verification.txt` (J read-only) | `b39f77745a26` |
| `post-smoke-readonly.txt` (S read-only) | `371d98083243` |
| этот файл — `deploy-summary.md` | см. коммит `docs(p0v): deploy 2.58.91 run evidence` |

Источник сырья: `%OPENCODE_WORKFLOW_SCRATCH%\release-25891\logs\`
(scratch; в репозиторий промотированы только эти три файла + сводка).
