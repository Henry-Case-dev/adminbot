# DEPLOY-25895 — evidence: выкат 2.58.95 (CFG-03 + POSTGEN-DIAG + VISION-ADAPT)

Релиз: **2.58.95** — состав поезда: **CFG-03** (полный аудит 579 параметров
мини-аппа, UI_missing=0, честные описания 5 «мёртвых» ручек), **POSTGEN-DIAG**
(bounded retry тяжёлого payload пост-генерации, нормализация bytes→JPEG, sniff
fill-байтов, detail-наблюдаемость), **VISION-ADAPT** (адаптивный универсальный
preprocessing: staged weight->downscale, provider-agnostic лимиты, bounded
retry только image-class; кодек = Pillow если установлен, иначе ffmpeg).
§4-приёмка (positive vision) — отдельный лейн; здесь только выкат.

- Утверждённый кандидат: `113f3a629cab54f7fcc261349a7c9af3b90f56d7`
  (= `origin/master` tip; review-коммит `113f3a62`; bump `35b8b455`;
  runtime-дельта к базе 2.58.94 (`9072347b`) = ровно 5 whitelist-файлов).
- Прод ДО: `9072347b` (2.58.94, healthz 2.58.94) → ПОСЛЕ: **`113f3a62` (2.58.95)**.
- **Server-reported HEAD после выката = `113f3a62…`** — совпадает с кандидатом
  (три независимых среза: C-checkout, J-стадия, HTTPS-проба после выката).
- DEPLOY_SOURCE: `origin/master` (иммутабельный коммит; fetch
  `9072347b..113f3a62`, B3-ancestor пройден). Mutable worktree **не требуется**;
  прод-репо: `git checkout -B master origin/master` + `/tmp`-логи; репо-файлы
  DevOps-машины — только scratch.
- T0 (рестарт, UTC): **2026-10-19 13:07:43**; MainPID 3657672 → **3716545**
  (NRestarts=0, active/running, ExecMainStartTimestamp 13:07:57Z).
- Инструменты: `deploy_25895.py` — предрегистрированный sha256_12
  `03d52c843908`; **фактически использован фиксированный `473686f333fb`**
  (см. «Девиации»: фикс `apre` против ложного abort + `_rb` detach-fallback);
  `rel95_final.sh` sha256_12 `b912792903f4` (read-only, как есть);
  `recon95_combined.py`, `journal95_probe.py/.sh` — read-only пробы.

## Режимы и rc

| режим | rc | результат |
|---|---|---|
| recon (read-only) | 0 | SSH ok; прод 2.58.94 @ `9072347b` (master); PIL в venv нет, ffmpeg 6.1.1 есть; ветки `release/fix-2.58.93/94` в прод-репо отсутствуют (объекты коммитов есть) |
| main #1 | 2 | ЛОЖНЫЙ abort из-за бага скрипта (см. «Девиации»); tree-restore OK; рестарта НЕ было; прод не задет |
| main #2 | 0 | checkout `113f3a62`, restart, healthz 2.58.95, 9/9 артефактов, J-стадия OK |
| journal probe (read-only) | 0 | ERR=2 / 402=1 разобраны построчно — не дефекты релиза |

## Ключевые проверки (main #2, 13:07–13:08Z)

- healthz loopback **и** HTTPS = `2.58.95`; HTTPS-маршруты 200/200/200.
- Изоляция дельты: `DELTA_RUNTIME` **5/5** == whitelist (set-eq):
  `config/settings.py`, `services/image_normalize.py` (новый),
  `services/mca_vision.py`, `services/param_catalog.py`,
  `services/postgen_vision.py`; `TRACKED_MOD_AFTER`=0.
- `EXPECT12`-хэши **9/9** (вкл. `services/image_normalize.py` b4f9f7a95d6d,
  `services/mca_vision.py` a768eac7387b, `services/postgen_vision.py`
  232e65a4af41, `services/param_catalog.py` 4886ff036b0e,
  `config/settings.py` 1e534c6c15c3, README 28cdd3dfbd8d, F8-meta 889a98e3c961,
  sanity fullscreen-policy.js 96db06425079 / telegram_send.py e23bced2fdb8);
  `APP_VER=2.58.95`; F8-meta HEAD `b20fe4f7`.
- Маркеры поезда (deployed bytes): CFG-03 HONEST_DESC=5, TSV=580,
  inventory/test=1/1; POSTGEN-DIAG module=1, validate=1, sniff=5, postgen=2,
  test=1; VISION-ADAPT plan=1, optimize=2, codec=1, adapt_event=1, adapt_log=1,
  retry=2, env_bytes=2, env_pixels=2, test=1.
- Регрессионные маркеры: DL-FIX 8/8, CFG-02C 13/13, 2.58.92 13/13, 2.58.91
  16/16 — все на месте (значения == ожиданиям `rel95_final.sh`).
- Served: `SERVED_EQ_APP_JS=SAME`, `SERVED_EQ_APP_CSS=SAME`, `PAGE_VER`=**15**,
  `SUBST_CSS`=**2**, `SCOPE_LABEL_SERVED`=1.
- Дрифт=0: `TRACKED_MOD`=0 (до и после), `TR_RUNTIME_DRIFT`=0,
  A-pre `PROD_RUNTIME_DRIFT`=0; HEAD == origin/master == кандидат.
- Миграции: `pending=[]`, user_version **36→36 (ΔDDL=0)**, `migrations: complete`.
- Воркеры: SKIPS=**0** («maximum number of running instances»), CLAIM_SLOW=0,
  MAINT_TIMEOUT=0, VISION_TICK=1, RUNTIMEWARN=0, VISION_PROBE_FAIL=0,
  GRACEFUL=2, POLLER=1.

## Журнал since T0 — построчный разбор ERR=2 / 402=1

Формальное ожидание «ERR/CRIT/TRACEBACK/402 = 0» не совпало; все три строки
разобраны (полные строки и выборки — `journal95-probe.txt`):

1. **ERR/Traceback #1** — `13:07:43,987 apscheduler.executors.default - ERROR -
   Job "SummarySchedulerService._tick" raised an exception` (+Traceback) —
   **старый процесс PID 3657672** в момент остановки: рестарт прервал
   in-flight сводку/обложку (в 13:07:39 был `COVER_STYLE_RUNNING`,
   `duration_ms=90027`). Shutdown-шум остановки, не код 2.58.95.
2. **ERR #2** — `13:09:19,806 services.mca_events - ERROR - mca_event=INCIDENT |
   stage=takeover | reason_code=incident_opened | pipeline_type=summary` —
   **новый процесс**, но это штатный incident-механизм бота: takeover
   прерванной рестартом работы (уровень ERROR — дизайн mca_events для
   инцидентов). Аналогичный INCIDENT был до выката в 09:14:44 (vision.media) —
   поведение pre-existing.
3. **402 #1** — `13:08:18,402 services.config_migrations - INFO -
   [threshold_migration] уже новый дефолт` — «402» = **миллисекундный фрагмент
   таймстампа**; ложное срабатывание grep. Реальных HTTP 402 нет (за сутки 74
   совпадения — все ms-фрагменты/номера; выборка в probe).

Вывод: дефектов кода 2.58.95 в окне нет; CRITICAL=0, RuntimeWarning=0.

## Откат

- Abort до рестарта: `_tree_restore` → `release/fix-2.58.94` (ветки в прод-репо
  нет) → **fallback detach `9072347b` — фактически отработал в прогоне #1**:
  `TR_RC=0`, runtime-диффы 0, tracked-mod 0, рестарта не было.
- Abort после рестарта: `_rb` → `release/fix-2.58.93` (ветки в прод-репо нет) →
  **fallback detach `b4d30cab`** (объект подтверждён `OBJ_RB93TIP=commit`;
  добавлен фиксом `deploy_25895.fix.diff`). Не потребовался.
- Готовность отката сохраняется: обе ветки на origin (`release/fix-2.58.94` =
  `9072347b`, `release/fix-2.58.93` = `b4d30cab`, ls-remote 13:00Z); объекты
  коммитов в прод-репо есть. Киль-свитч VISION-ADAPT:
  `MCA_VISION_NORMALIZE_ENABLED=0` (env-only, default ON).

## Девиации (честно)

1. Recon v1 (мой scratch-скрипт) упал на клиентской ошибке форматирования
   ПОСЛЕ установления SSH-коннекта (команды не выполнялись); исправлено,
   повторный recon успешен. Вреда нет.
2. Прогон #1: **ложный abort** — баг в клоне скрипта: `out` перезаписывался
   выводом `A2_user_version` до проверок A_pre_state (`PROD_RUNTIME_DRIFT=0` /
   `INDEX_LOCK=absent` фактически были истинны). Скрипт корректно выполнил
   tree-restore (detach `9072347b`), рестарта не было; прод всё время отдавал
   2.58.94 (HTTPS-проверка между прогонами).
3. Правка скрипта (deployment mechanics, не продукт): sha12 `03d52c843908` →
   **`473686f333fb`**; полный diff — `deploy_25895.fix.diff`. После правки оба
   офлайн-чека EXIT 0 (`check-offline-postfix.txt`, `bind-check-postfix.txt`).
4. SSH-коннекты лейна: 5 (recon-crash, recon, main#1, main#2, journal-probe) —
   все с успешным auth, паузы ≥90 с, без ретрай-спама; fail2ban не задет.
5. API-пробы `/api/vision/state`, `/api/workers/budget` без TMA-заголовка
   вернули `{"detail":"missing init data"}` — ожидаемая auth-заглушка.
   `UNTRACKED=13` на проде — pre-existing (как и в 2.58.94).

## Остаток

- §4-приёмка (positive vision: адаптив на тяжёлом кадре, postgen, экономика) —
  отдельный лейн. Журнальные маркеры `[vision] adapt` / `[vision] postgen`
  появятся при первом тяжёлом кадре (ожидание дизайна; в окне выката 0).
- Наблюдение для приёмки: в `mca_media_analyses` есть `running`=1 (in-flight
  или орфан после рестарта; takeover-инцидент бот уже открыл сам).
- Pre-existing (вне релиза): yt-dlp прокси-407 (10:22, video download),
  INCIDENT vision.media (09:14) — не связаны с 2.58.95.

## Файлы (sha256_12)

- `deploy-run.txt` **`11bd5a6ca88c`** (прогон #2, успешный);
  `final-verification.txt` **`894543590546`**; `recon95-combined.txt`
  **`89de1e688b81`**; `journal95-probe.txt` **`6774668c0a7e`**;
  `deploy-run-1-aborted.reconstructed.txt` **`a92aa10d8b52`** (реконструкция
  лога ложного abort, прогон #1); `deploy_25895.fix.diff` **`ccc040f084fc`**;
  `check-offline-postfix.txt` **`eed2e490fe6e`**; `bind-check-postfix.txt`
  **`9ca02d93bb2d`**.
- Прогон #2: 2026-10-19 13:07:29Z – 13:08:35Z UTC; journal-probe
  13:10:33Z–13:10:48Z; HTTPS-пробы 13:05Z / 13:11Z.
- Скрипты (scratch DevOps-машины): `deploy_25895.py` факт. sha12
  **`473686f333fb`** (предрегистр. `03d52c843908`); `rel95_final.sh`
  `b912792903f4`; `recon95_combined.py`, `journal95_probe.py/.sh` — read-only.
