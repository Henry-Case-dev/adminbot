# DEPLOY-25897 — evidence: выкат 2.58.97 (CFG-04 + ADD-EXP F1)

Релиз: **2.58.97** — состав поезда: **CFG-04** (один save-CTA + честный
dirty-чип-индикатор, safe-area/keyboard-aware sticky-панель, доступное
последнее поле, полный tech-key expand/copy, сохранение состояния при
повороте; ревью `e27216d3` Approved, D.4=PENDING_OWNER_E2E optional) +
**ADD-EXP F1** (`5b86517e`: исполнимые частотные якори мата 1-из-4–5 / одно
слово в большинстве разговорных реплик + честный header без ложного
делегирования L1; ревью `188f7414` Approved) + bump 2.58.97 (`fcd73a38`).
§4-приёмка (живые ответы, F4) — отдельный лейн; здесь только выкат.

- Утверждённый кандидат: `99f5672c5e1d27e957100395a13178fef929b035`
  (= `origin/master` tip на момент выката; review-коммит `99f5672c`; pkg
  `e5217933`; bump `fcd73a38`; fix `8b437c39`; runtime-дельта к базе 2.58.96
  (`95d11472`) = ровно 5 whitelist-файлов).
- Прод ДО: `95d11472b9e533b554554918e3efa6b42125260b` (2.58.96, healthz
  2.58.96) → ПОСЛЕ: **`99f5672c` (2.58.97)**.
- **Server-reported HEAD после выката = `99f5672c…`** — совпадает с
  кандидатом (C-checkout, J-стадия, HTTPS-проба).
- DEPLOY_SOURCE: `origin/master` (иммутабельный коммит; fetch
  `95d11472..99f5672c`, B3-ancestor пройден). Mutable worktree **не требуется**;
  прод-репо: `git checkout -B master origin/master` + `/tmp`-логи; репо-файлы
  DevOps-машины — только scratch + этот evidence-каталог.
- T0 (рестарт, UTC): **2026-10-19 19:13:31**; MainPID 3739015 → **3791730**
  (NRestarts=0, active/running, ExecMainStartTimestamp 19:13:43Z,
  ExecMainStatus=0). PID до выката (3739015) — процесс 2.58.96 от
  14:51:31Z (цепочка 25896 → 25897 непрерывна).
- Инструменты (scratch `release-25897`): `deploy_25897.py` sha256_12
  **`665f818a0764`** (T0-hardened клон `b8179a3cdb3f`; использован **как
  есть**); `rel97_final.sh` sha256_12 **`d7a755d7b3e6`** (read-only;
  использован как есть, загружен в `/tmp/rel97_final.sh`). Offline-чек до
  выката: EXIT 0 (5/5 whitelist, 9/9 хэшей, hash errors none).

## Режимы и rc

| режим | rc | результат |
|---|---|---|
| recon (read-only) | 0 | SSH ok; прод 2.58.96 @ `95d11472` (master); healthz 2.58.96; server UTC 19:11:29Z |
| main | 0 | checkout `99f5672c`; дельта 5/5 == whitelist; артефакты 9/9; restart; healthz 2.58.97; J-стадия OK; WARNINGS=0; без abort/rollback |
| journal-probe (read-only) | 0 | ERR-триаж: 2 матча = старый PID 3739015, shutdown; 465 строк журнала, новых ERR нет |
| journal-tail (read-only) | 0 | traceback до конца: `asyncio.exceptions.CancelledError` (отмена in-flight cover-генерации при остановке) |

## Ключевые проверки (main, 19:13–19:14Z)

- healthz loopback **и** HTTPS (DevOps-машина, 19:19:48Z) = `2.58.97`;
  HTTPS-маршруты `/healthz` 200, `/web/` 200, `/static/app.css` 200.
- Изоляция дельты: `DELTA_RUNTIME` **5/5** == whitelist (set-eq):
  `web/app.js`, `web/index.html`, `web/static/app.css` (CFG-04),
  `services/mca_expression.py` (ADD-EXP F1), `config/settings.py` (bump);
  `TRACKED_MOD_AFTER`=0; `DELTA_TOTAL`=270 (остальное — /plans + tests/evidence,
  не runtime).
- `EXPECT12`-хэши **9/9** (вкл. `web/app.js` `885094459700`,
  `web/index.html` `528f358a6589`, `web/static/app.css` `6b5ca0cc1d47`,
  `services/mca_expression.py` `d23e00763b0d`, `config/settings.py`
  `10b6c981b5fc`, README `4b48dd825026`, F8-meta `bd31b8f5914e`, sanity
  fullscreen-policy.js `96db06425079` / telegram_send.py `e23bced2fdb8`);
  `APP_VER=2.58.97`; F8-meta HEAD `2428768`.
- Маркеры CFG-04 10/10 (deployed bytes): CFG04_STICKY_SAVE=12,
  CFG04_SAVE_INDICATOR=1, CFG04_TECH_KEY_LINES=21, CFG04_SYNC_PANEL=4,
  CFG04_DIRTY_GUARD=8, CFG04_ORIENT=2, CFG04_KB_OFFSET_CSS=14,
  CFG04_SAFE_AREA=17, CFG04_TEST=1, CFG04_JS_TEST=1.
- Маркеры ADD-EXP F1 7/7: EXP_MODULE=1, EXP_FREQ_ANCHOR=1, EXP_OCC_ANCHOR=1,
  EXP_SHORT_PARTICLE=1, EXP_HEADER_HONEST=1, EXP_HEADER_NO_L1=0, EXP_LAYER=1.
- Spot-маркеры поездов 2.58.96/95: CFG03_HONEST_DESC=5, CFG03_TSV_ROWS=580,
  PGD_NORMALIZE_MODULE=1, VA_ADAPT_EVENT=1, EXP_GATE_FLAG=2.
- Регрессионные наборы: DL-FIX 8/8, CFG-02C 13/13, 2.58.92 13/13, 2.58.91
  16/16 — все на месте. Сравнение с `final-verification.txt` 2.58.96:
  100 общих маркеров, отличия только ожидаемые (HEAD, версия, PID,
  `SERVED_APP_JS` 1d68fede513e→885094459700, `SERVED_APP_CSS`
  6d3ae1112d50→6b5ca0cc1d47 — оба файла в дельте CFG-04; ERR 0→2 —
  разобран ниже). Наборы ADD-EXP 96, не входящие в 97-скрипт (13 шт.),
  относятся к файлам вне whitelist-дельты → байт-идентичны 2.58.96
  (следствие set-eq дельты).
- Served: `SERVED_EQ_APP_JS=SAME` (`885094459700`), `SERVED_EQ_APP_CSS=SAME`
  (`6b5ca0cc1d47`), `STICKY_SAVE_SERVED=12` (≥1), `SCOPE_LABEL_SERVED`=1,
  `PAGE_VER`=**15**, `SUBST_CSS`=**2**.
- Дрифт=0: `PROD_RUNTIME_DRIFT`=0 (до), `TRACKED_MOD`=0 (до и после),
  HEAD == origin/master == кандидат (на момент выката).
- Миграции: `pending=[]`; sqlite `user_version` **36→36 (ΔDDL=0)**;
  `migrations: complete`.
- Воркеры: SKIPS=**0** («maximum number of running instances»),
  CLAIM_SLOW=0, MAINT_TIMEOUT=0, VISION_TICK=1, RUNTIMEWARN=0,
  VISION_PROBE_FAIL=0, GRACEFUL=2, POLLER=1; `[local-bot-api] файлы:`=1,
  warn=0.

## Журнал since T0 — разбор ERR=2 (формальное ожидание 0)

`ERR=2` (grep `ERROR|CRITICAL|Traceback`) — обе строки суть **один**
инцидент остановки, **старый процесс PID 3739015 (2.58.96)**:

- `19:13:31,655 apscheduler.executors.default - ERROR - Job
  "SummarySchedulerService._tick" raised an exception` + Traceback →
  `asyncio.exceptions.CancelledError` в
  `summary_generator._publish_rich_document_impl → image_generation.generate
  → _request_with_retry` (ожидание ответа image-провайдера).
- Контекст: рестарт в 19:13:31 прервал in-flight генерацию обложки
  rich-сводки; сама сводка завершилась до этого (`SUMMARY_COMPLETE
  status=ok | duration_ms=809525 | source_count=335`), polling остановлен.
- Штатный graceful shutdown после отмены прошёл чисто: `SUMMARY_SHUTDOWN_DRAIN
  phase=draining in_flight=0 cancelled=0` → `[shutdown] bye | elapsed_ms=3580`
  → `runtime sqlite closed` → `pg_db pool closed`.
- Новый процесс 3791730 в окне 19:13:43–19:16:50 — **ни одного**
  ERR/CRITICAL/Traceback; фон: vision_media ticks, `outcome=success`.
- Вывод: shutdown-шум рестарта (отмена сетевого ожидания картинки), **не
  дефект 2.58.97** — дельта релиза не касается summary/image-кода.
- Прочее: `ERR_402=0`, `RUNTIMEWARN=0`; при shutdown-флаше Sentry
  зафиксировал «2 pending events» (в журнале — один ERROR+traceback;
  второй источник не устанавливался — вне скоупа релиза).

## Откат

- Abort до рестарта: `_tree_restore` → `release/fix-2.58.96` (`95d11472`;
  ветки в прод-репо может не быть → fallback detach `95d11472`). Не
  потребовался.
- Abort после рестарта: `_rb` → `release/fix-2.58.95` (2.58.95; fallback
  detach `113f3a62` — объект в прод-репо есть: HEAD до выката 2.58.96).
  Не потребовался.
- Все рубежи на origin (ls-remote 19:10Z): `release/fix-2.58.96` =
  `95d11472`, `release/fix-2.58.95` = `113f3a62`, `release/fix-2.58.94` =
  `9072347b`; `master` = `99f5672c`. Киль-свитч ADD-EXP:
  `EXPRESSION_EXAMPLES_ENABLED=0` (env-only, default ON).

## Девиации (честно)

1. `ERR=2` в окне T0 — разобран: shutdown `CancelledError` старого процесса
   при рестарте (см. раздел выше); не дефект релиза.
2. API-пробы `/api/vision/state`, `/api/workers/budget` без TMA-заголовка
   вернули `{"detail":"missing init data"}` — ожидаемая auth-заглушка.
3. Live-маркеры (`expression_diag`, `[vision] adapt/postgen`) в окне выката
   = 0 — появятся при первой живой генерации / тяжёлом кадре; §4-скоуп.
4. `UNTRACKED=13` на проде — pre-existing (как в 2.58.95/96).
5. `mca_media_analyses`: total 98, failed=67 / ready=30 / running=1 —
   состояние данных, pre-existing (running=1 наблюдался и ранее).
6. `EXPRESSION_EXAMPLES_ENABLED` отсутствует в `.env` — env-only
   kill-switch, default ON (как в 2.58.96); few-shot черновики требуют
   owner-approve (`owner_approved=0` — дизайн BLOCK-1).
7. Release-гейт read-only (`gate-release-readonly.txt`): exit 1 — карта cfg
   ещё привязана к `113f3a62` (stale; strict_evidence=true), 187 PENDING
   непостроенных слайсов + 4 RFL. Ожидаемо (ledger: bind 2.58.95 →
   ре-биндинг в acceptance-линии). Карта этим лейном **не редактировалась**.
8. SSH-коннекты лейна: **4** (recon, main, journal-probe, journal-tail) —
   все с успешным auth, паузы ≥90 с, один логин `nik`, без ретрай-спама;
   fail2ban не задет. Две дополнительные read-only пробы — для
   обязательного ERR-триажа (по прецеденту 2.58.95).

## Остаток

- §4-приёмка (живые ответы F4: CFG-04 live B.1-3/C.1-4/D.1,D.5,A.1,B RFL +
  ADD-EXP behavior criterion) — отдельный лейн; D.4 — optional owner E2E.
- Ре-биндинг карты cfg на `99f5672c` и закрытие RFL production-typed
  evidence — ledger/acceptance-линия.

## Файлы (sha256_12)

- `deploy-run.txt` **`0e92a1677ff8`** (scrub применён скриптом);
- `final-verification.txt` **`f1cd04f42867`** (J-стадия, read-only);
- `recon97.txt` **`89d43338edcc`**;
- `journal97-probe.txt` **`76082a188336`** (ERR-триаж: контекст/PID);
- `journal97-tail.txt` **`887f6b65254b`** (хвост traceback + shutdown-цепочка);
- `gate-release-readonly.txt` **`8b556b66d310`** (exit 1, read-only);
- `deploy-summary.md` (этот файл).
- Времена: recon 19:11:25–19:11:29Z; main 19:13:15Z–~19:14:15Z (J NOW
  19:14:11Z); journal-probe 19:16:46Z; journal-tail 19:19:26Z; внешняя
  HTTPS-проба DevOps-машины 19:19:48Z → `2.58.97`.
