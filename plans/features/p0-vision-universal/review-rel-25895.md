# REV-REL-25895 — вердикт (релиз 2.58.95: CFG-03 + POSTGEN-DIAG + VISION-ADAPT)

Независимый аудит релиз-пакета. Режим read-only: деплой и push НЕ выполнялись;
этот коммит — только данный документ. Прод до релиза — 2.58.94 @ `9072347b`.

Кандидат: docs/evidence HEAD `62a4f561` поверх bump `35b8b455` (runtime заморожен
bump-коммитом; код-линия: CFG-03 `df078406`, POSTGEN-DIAG `61ecd034`,
VISION-ADAPT `b20fe4f7`). Вход: отчёт `release-25895-report.md`,
`evidence/release-25895/**`, `deploy_25895.py` (`03d52c843908`),
`rel95_final.sh` (`b912792903f4`), `check_deploy_25895.py` (`3e6883288482`).
Верификация — изолированный worktree `release-25895/wt` @ `35b8b455` + мои
прогоны; `wt-base` @ `9072347b` для базовых доказательств.

## 1. Bump `35b8b455` — подтверждён

- ровно 31 файл (settings + README + F8-meta + 24 py-пина + 4 JS-пина), +33/−33;
- каждая изменённая строка — только версия `2.58.94→2.58.95` / HEAD-штамп meta
  `61ecd034→b20fe4f7`; моя независимая проверка всех 33 пар — 0 нарушений
  (включая escaped-пины `2\.58\.94` → `2\.58\.95`);
- `APP_VERSION = "2.58.95"`; meta HEAD = `b20fe4f7` (последний код-коммит);
- чужая ADD-EXP-WIP (speech/prompt_composer/app.js/index.html/direct_chat_service
  и др.) не вошла ни в один коммит поезда — сверка списков всех 8 коммитов
  (код + 4 ревью + bump + docs); WIP остался в дереве без изменений.

## 2. Дельта `9072347b..HEAD` — изоляция подтверждена

- non-plans = **39** файлов (set-equality с `delta-non-plans.txt` — мой прогон);
- runtime = ровно **5**: `services/image_normalize.py` (новый),
  `services/mca_vision.py`, `services/postgen_vision.py`,
  `services/param_catalog.py`, `config/settings.py`;
- сверка с reviewed-коммитами: 4 файла побайтово == `b20fe4f7`;
  `param_catalog.py` == `df078406`; `settings.py` отличается от `b20fe4f7`
  только строкой APP_VERSION (bump);
- **ΔDDL = 0** (database.py/migrations/scripts не в дельте; user_version 36);
- каталог **Δ = 0**: `tools/gen_param_registry_round1025.py --check` —
  579 == REGISTRY (мой прогон, EXIT 0); diff `param_catalog.py` — ровно
  5 честных описаний, ключей не добавлено/не удалено;
- вне набора — только 2 исторические ссылки «2.58.94» в комментариях
  (`image_normalize.py`, `test_postgen_diag.py`); прецедент допустим;
- EXPECT12 (9 артефактов) — все sha256_12 пересчитал сам, совпали; sanity-файлы
  (`fullscreen-policy.js`/`telegram_send.py`) байт-в-байт равны прод-базе.

## 3. Прогоны — воспроизведены (мои, в wt @ `35b8b455`)

- полный pytest: **10 failed / 14519 passed / 39 skipped** (694.62s). 9 падений =
  известный пре-сущ. набор (5×t5150, 2×asap7_direct_settings, mca01_tx,
  history_cli-worktree-артефакт); 10-е — документированный env-флейк
  random_source (`reserve read failed`/no active connection): одиночный тест
  зелёный, на базе `9072347b` флейк-класс падает на ДРУГОМ тесте того же файла;
  прямые базовые прогоны 4 файлов: **9f/63p — те же 9 ID**;
- 39 skipped = PIL-отсутствие у новых skipif-тестов (не маскировка;
  канонический `py -3`: adapt **43**, postgen **27**);
- фокусные (мои прогоны): постген-кластер **447p/39s**, cfg03 **16**,
  cfg03-кластер **453**, F8 **29**, реестр **579 --check OK**,
  speech/UI **100**, JS-свип **88/0**, UI e2e (Playwright) **PASS**.

## 4. Скрипты — сверены офлайн (прод не трогался)

- хэши скриптов совпали (`03d52c843908`/`b912792903f4`/`3e6883288482`);
  `check_deploy_25895.py` — **EXIT 0** (мой прогон): вайтлист 5/5 == дельта,
  BUMP == HEAD, upload на месте;
- `deploy_25895.py`: T0-hardened клон 25894, все NF-фиксы на месте
  (checked_out-гейт + tree-restore, set-equality вайтлиста, B3 fail-closed
  ancestor, D1-хэши → abort, WARNINGS-summary, SERVED_EQ, один SSH-коннект на
  main, recon read-only); `PROD_BRANCH=release/fix-2.58.94`,
  авто-откат `release/fix-2.58.93`, `EXPECT_VER=2.58.95`; секреты читаются из
  `deploy_commands.txt`, scrub в логах (прод-побочек в recon нет);
- `rel95_final.sh`: `bash -n` OK (Git Bash); read-only; маркеры поезда +
  **33 ожидания сверил построчно с кандидатом — 0 расхождений**; USER_VERSION,
  SKIPS-окно, ERR_402, PAGE_VER/SUBST_CSS, served/healthz, read-only API.

## 5. Чек-лист §4 — полон и корректен

(a) CFG-03 Ф6: 03.4 hot (`image_daily_limit` 1→60; `flags.vision_enabled`
off/on), 03.6 витрина (e2e + маркеры), 03.11 негативы, 03.12 OFF/ON — сценарии
совпадают с `manual-checks.md` (R4); reuse-строки (P0/CFG-01, CFG-02B) указаны.
(b) живой повтор пост-генерации — 1 генерация, quota raise+restore, harness
`accept94b_cover.py` существует; цепочка `[image] generated` → `[vision] postgen
status=ready`, detail в `error_json` (проверено в коде), дедуп-кэш не сломан.
(c) vision-adapt live — маркер `[vision] adapt | strategy=… | reason=… | calls=…`
и событие `vision_adapt` существуют; retry ≤1 только image-class
(400 — лишь с подтверждённым классом изображения; 401/403/429/5xx/сеть — без
повтора; строго меньшая копия); калибровка env-only; откат
`MCA_VISION_NORMALIZE_ENABLED=false` (OFF-паритет в коде и тестах).
(d) PIL/ffmpeg в прод-venv — информационный пункт, оба пути fail-open.
(e) уборка тестовых сообщений. Базовые маркеры — в скриптах (healthz 2.58.95,
ERR/CRIT/402=0, SKIPS=0, user_version без Δ, PAGE_VER=15, SUBST_CSS=2,
LOCAL_BOT_API_MARKER≥1).

## 6. Визуальная проверка (дельта — тексты 5 честных описаний + витрина)

Playwright e2e — PASS (мой прогон). Browser Use (реальный рендер, стабы):
вкладка «Память» — «dig_into_lore: окно …» с «Не влияет…» и `memory_backup_keep`
с «НЕ действует…»; модалка «Ответы в чате» — `chat_lock_max_entries` и
`chat_budget_response_ratio` с «Не влияет…»; модалка «Выжимка видео» —
`youtube_transcript_proxy_*` с «Не влияет…» + synthetic-группа «Медиа-шара»
(«Каталог временной публикации видео» / «Внешний базовый адрес /media»).
Все 5 ручек и группа видны; консоль без ошибок; mobile 390px без overflow (e2e).

## Леджер (приёмка)

- **READY_FOR_LIVE (postdeploy)**: cfg-карта — CFG-02A.3/.4/.5, CFG-02B.2/2.3/8,
  CFG-02.AC1; CFG-03.4/.6/.11/.12 (§4a); p0v-карта — P0V-PIPE-CONTEXT;
  §4b (postgen live), §4c (vision-adapt live); базовые маркеры релиза.
- **Рубеж отката**: `9072347b` → ветка `release/fix-2.58.94` (push при выкате;
  иначе tree-restore — detach на `9072347b`). Авто-откат ПОСЛЕ рестарта —
  `release/fix-2.58.93` (`b4d30cab`, 2.58.93).
- **Обязательства приёмки/PM до `--stage release`** (сегодня гейт не пройдёт):
  1) cfg-карта: CFG-03-строки PENDING (0 evidence) — привязать evidence
     (`review-cfg-03.md` f8bb638d + `evidence/cfg-03/**`) и статусы
     (не-live → VERIFIED; live → после живых проверок); обновить
     `candidate_commit` (сейчас `1d9a7107` — CFG-02C-эра);
  2) p0v-карта: PENDING-строки (P0V-WF-QUEUE/TEST-MATRIX/TEST-MOCKS/WF-STANDARD
     + 5 context-заголовков) и `candidate_commit` (`76b156e0`) — закрыть/
     обосновать; КОРР №2/POSTGEN-приёмка живёт в отчёте §4 и
     `review-vision-adapt.md` — при необходимости завести строки в карте;
  3) перед рестартом проверить наличие ветки авто-отката в прод-репо
     (`git -C /var/www/admin_bot rev-parse --verify release/fix-2.58.93`;
     при отсутствии — fetch той же сессией), иначе `_rb` R1_checkout упадёт
     и авто-откат не сработает (ручной рубеж: master → `9072347b`).
- Предусловие запуска: push `master` с bump-коммитом 2.58.95 (B3 fail-closed).

## Наблюдения (не блокирующие)

* `bump-verify.txt` печатает «changed-line-pairs=31» (счёт по хункам; фактически
  33 пары — проверены все; та же конвенция, что у 2.58.94).
* `prompt_composer.py` убран из sanity-списка EXPECT12 (был в 2.58.94);
  дыры нет — неизменность покрыта set-equality вайтлиста.
* В worktree `wt` осталась незакоммиченная правка `e2e-log.json` (перезапись
  путей скриншотов при повторном прогоне) — только scratch, в репо не влияет.
* 10-е падение полного pytest (env-флейк) — класс задокументирован в 2.58.94;
  при приёмочных прогонах допустимо, не регрессия.

## Вердикт

**Approved** — релиз-пакет 2.58.95 (bump `35b8b455`, HEAD `62a4f561`) проверен:
bump версионно-чистый, дельта изолирована (5/5 runtime == reviewed-коммиты),
ΔDDL=0, каталог 579, хэши 9/9, фокусные наборы и JS/UI-свипы воспроизведены,
скрипты офлайн-согласованы с NF-фиксами и fail-closed гейтами, чеклист §4 полон,
визуальный слой подтверждён (Playwright + Browser Use). DONE — только после
живой приёмки §4 и обязательств леджера; деплой — за DevOps/Orchestrator.
