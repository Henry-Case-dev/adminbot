# REV-ACCEPT-95 — независимая проверка живой приёмки 2.58.95

Независимое ревью приёмки (evidence + live-спот-чеки). Режим read-only: прод-код и карты не менялись; этот коммит — только данный документ.

## Кандидат / связывание

- Приёмка: `plans/features/p0-vision-universal/evidence/release-25895/acceptance/**` (60 файлов вкл. README) + CFG-03-часть `plans/features/cfg/evidence/cfg-03/acceptance/**` (8 файлов; скриншоты/UI-JSON общие с волной 95).
- Прод при волнах: **2.58.95 @ `113f3a62`** (T0 2026-10-19 13:07:43Z, MainPID 3716545, NRestarts=0); волны 95a–95e 13:47–14:34Z, UI 14:20–14:42Z.
- **На момент ревью прод уже 2.58.96 @ `95d11472`** (следующий reviewed-деплой; healthz = 2.58.96). Живые спот-чеки 2026-10-20 выполнены на 2.58.96; проверяемые инварианты не менялись: sha256_12 `113f3a62:web/app.js` = `44642c5a2b3e` == p6b `served_sha12`/`disk_sha12`, в 2.58.96 app.js изменён только ADD-EXP-слоем (served == HEAD `1d68fede513e`, сверил).

## Вердикт

**Approved** — приёмка и доказательства. Родительский статус НЕ DONE по двум положительным половинам: (b) `ready` постгена и (c) `ready + GT` на тяжёлых фикстурах — остаются UNVERIFIED/RFL (Findings 1/2, леджер §5).

## 1. Проверка по пунктам

### (a) CFG-03 Ф6
- **03.6 (live, повторно):** живой `GET /api/config` (админ-initData, X-Chat-Id рабочего чата): все **5** мёртвых ручек присутствуют, точный маркер «Не влияет: значение сохраняется в конфиге…», ровно **5** точных совпадений на 562 item (6 «Не влияет», 1 «НЕ действует» — `memory_backup_keep`). `served app.js == disk` подтверждён хэшем; `css_same=false` в p6b — подстановка `__APP_VERSION__` (2 места), не дефект; scope-метка в HTML на месте. UI: «Память» — `dig_into_lore` с «Не влияет…», `memory_backup_keep` с «НЕ действует…»; модалки «Ответы в чате»/«Выжимка видео» — обе ручки; console errors 0; desktop+mobile 390 без overflow.
- **03.4 `flags.vision_enabled`:** OFF → `requested=false/vision_disabled`, tool = `disabled`, полный ход — честный ответ, **0** vision-вызовов/анализов/джоб; ON (исходный override=true восстановлен) → анализ запускается (95a: две реальные ready-аналитики пользовательских фото 13:51, 180/185 КБ; 95b/95c: tool-путь ставит джобы). 95a-попытка ON-проверки упёрлась в `DIRECT_UPDATE_DEDUP_HIT` (p3 `ok:false`) — раскрыто; ON достигнут в 95b/95c.
- **03.4 `limits.image_daily_limit`:** ровно 1 генерация (chat-scope `used+1=17`), вторая — отказ **до** платного вызова: 0 провайдер-вызовов, 0 фото, 0 новых строк журнала, шаблон `message.image_failure.quota_exhausted`; глобальный слой не тронут; восстановление точное (override снят, global 5). Отклонение от эскиза (глобально 1; «вернуть 60») обосновано (prod chat-day уже 16; global на проде = 5) и зафиксировано. Оговорка: числовой «фактический остаток» в отказе выражен шаблоном «суточный лимит выбран» (0 остаток); точная reset-строка — в CFG-02A.5. Принимаю как эквивалент с оговоркой.
- **03.11 (выборочно):** 422 (неверный тип), 422 (bogus-select), 409 (stale optimistic) — значения до==после, записей нет. Live-спот 3 классов подтверждён; это не полный per-параметр контур (см. леджер).
- **03.12:** OFF/ON по маршрутам (tool+ход) подтверждён; ON — анализ стартует. UI-часть effective state — существующее P0V-UI/e2e, в этой волне не перепроверялась.
- **CFG-02B.2/.2.3/.8:** ON-предпосылка (budget ON + freq ON, burst=2, cooldown=120, per_user) → «Сколько генераций подряд»=2, «Время ожидания»=120, тумблер ON; select **ровно 2** варианта (`per_user`/`per_chat`, подписи «Для каждого пользователя»/«Общий на весь чат»), чекбоксов нет; факты «Включено и действует / Для каждого пользователя / Локальный (чат) / 2 из 2 / сейчас доступно»; mobile 390 без overflow. OFF-restore → «Выключено (заводской режим) / Глобальный (по умолчанию) / 3 из 3», зависимые поля скрыты, конфиг восстановлен (`restore_matches=true`).
  **Мой живой спот (read-only):** UI-рендер 2.58.96 воспроизводит восстановленное состояние байт-в-байт по подписям/значениям (`0 из 5`, scope-метка, console errors 0, mobile 390 без overflow); живой API freq-блок = `switch_off/per_user/burst 3/cooldown 300/source global`; в served app.js (==disk) ровно 2 подписи режима; memory-карточка — «Не влияет…».

### (b) Постген — ровно 1 генерация
- gen1: **1** провайдер-вызов `qwen-image-3-pro`, 1 037 752 B, 58.3 c → фото **mid 1166489** доставлено; `image_reservation …:1166487:direct` = committed; бюджет chat **16→17**, shared **21→22** (+1); 1 vision-вызов на 1 генерацию (дублей нет). Подтверждено по p4b + p7b.
- Stage A: `normalize in=1037752 out=104689` → `adapt stage=A, scale=1.00`; один вызов, `ms=20004`, `error=TimeoutError` → `[vision] postgen status=pending reason=deadline_exceeded`; Writer-блок `status="pending" reason="deadline_exceeded"` + запрет утверждать содержимое; ответ честный («…я даже не в курсе, что там получилось»). Событие `image_postgen_vision outcome=skipped reason_code=deadline_exceeded`.
- gen2: 0 вызовов, 0 фото, 0 новых строк журнала, honest quota answer. `gen2_block_quota_exhausted/reset_note=false` — сработал image-capability-gate (не reserve-deny); раскрыто.
- **Finding 2 — классификация: бюджет vs латентность модели.** `IMAGE_POSTGEN_VISION_TIMEOUT_SECONDS=20` (p0b `postgen_budget=20.0`); та же модель: 24 КБ/262144 px → ready 7.5 с, 180 КБ → 8.8–9.9 с, 1 Мп → 20 с не хватает. Не маскировка: ready/контент не заявлялись. `ready` на 1024×1024 не наблюдался — RFL-хвост, не блокер.

### (c) Vision-adapt
- Фикстуры: 1 337 017 B sha256 `3be6d6d6…` (95b) и 1 115 814 B `5b47148f…` (95c); download sha байт-в-байт; intake-ассеты созданы.
- 95b: `normalize 1337017→801992` (A) → `540078` (B, scale 0.90); `adapt strategy=optimize reason=payload_over calls=1 ms=34088`; 95c: `1115814→642544` (A, fits), `calls=1 ms=20653`. Журнал прод-процесса (MainPID 3716545) — подтверждаю.
- `parse_error` (не-JSON от провайдера) на обоих: analysis id 43 rev2 / id 45 rev2 `failed/parse_error`, uncertainty «ответ модели не JSON», GT 0/8 и 0/3. Путь проверен по коду: `parse_analysis_payload` → `VisionAnalysis(failed, parse_error)` без исключения; `analyze_adaptive` ретраит только `VisionError` image-class; `process_asset_job` → CAS-finish failed/parse_error, job completed, авто-повтора нет (rev2 = CAS-бамп одной попытки). Честный терминальный отказ, без бесконечных ретраев и без ложного успеха. Положительная половина (ready+GT) не достигнута — внешнее поведение бесплатной модели, Finding 1, остаётся RFL.
- Калибровка: live 700000/4000000/90/ffmpeg/normalize ON == дефолты (`defaults_match`), ручки не менялись.
- Бонус (реальное фото 14:30:16): `unreadable rescued via normalization in=242886 out=24021 detail=not a supported raster image` → `strategy=original reason=fits status=ready` (`calls=1`, 7.5 с) — декод-фоллбэк POSTGEN-DIAG жив.

### (d) Орфан
`id=8`, asset `a32e0331…`, msg 1166176, создан **09:12:42Z** (epoch 1792401162); job `e75c45b7…` = `interrupted/worker_lost` (created 09:12:41, updated **09:14:44Z**). INCIDENT `vision.media` 09:14:44 подтверждён независимо по `evidence/release-25894/acceptance/journal-since-t0.txt` (тот же job_id). T0 13:07:43 → строка на ~4 ч старше рестарта 2.58.95; 95a-pre (13:47) уже её видел; probe95c (14:14) и final95d (14:31) — ровно одна running-строка (id=8), новых нет. **Классификация подтверждена:** in-flight-орфан эпохи 2.58.94, не от рестарта 95.
Замечание: `d-orphan-95b.json` и `orphan_classification` в p7b = `no_running_rows` — **ложноотрицательный артефакт** (p0b-снимок упал на `no such column: parent_tg_message_id`, `analyses_running` не собрался; при этом в том же p7b `analyses_running_after=[id=8]`). На классификацию не влияет (она на probe95c/final95d/95a-pre); в леджере цитировать probe95c/final95d, d-orphan-95b не использовать.

### (e) Уборка
16/16 удалено (список/статусы в `cleanup-register.json`; ответ 95a gen1 1166471 восстановлен через `bot_reply_parents`); residual_smart=0; `bot_replies`/`bot_reply_parents` 7+7 → 0 (final95d); safety-gate — 0 коллизий с реальными пользователями. Остаток: фото 95a — **mid известен: 1166469** (`summary.json`: kind=photo, bytes=1 091 119, sha12 `984f3b5cf908`, reply_to 1166464; записан send_photo-рекордером, т.е. это фото бота), а не «кандидаты 1166467/1166469». Формулировка README «mid не сохранён» неточна. Удаление по догадке не выполнялось — правило соблюдено, остаток раскрыт; рекомендуется удалить 1166469 (id достоверен) владельцем/следующей волной.

## 2. Findings (1)–(4)

1. **parse_error на тяжёлых фикстурах — не блокер 2.58.95:** путь корректен (терминальный честный отказ, 1 вызов, без ретраев/маскировки); блокирует только положительную половину RFL (c).
2. **Постген 20 с < латентности модели на 1 Мп — не блокер:** bounded, честный pending, доставка не блокирована; RFL-хвост «ready» остаётся.
3. **SQLite-контеншн окна волны — известный класс (ACCEPTANCE-94):** все ERR 95a/95b/95c (8/2/1) = `database is locked` (fail-open → bounded spool; NRestarts=0); сообщение реального пользователя 13:54:21 не потеряно (пропущена только строка наблюдаемости). Подтверждено построчно по run-логам. Не блокер.
4. **Бонус-декод-фоллбэк — положительное живое наблюдение**, не дефект.

**Непомаскированность:** все отказы видны (`status/reason`, `analysis failed/parse_error`, `vision_adapt/vision_media` failed/WARN); ложного ready/контента нет; ответы Writer'а честные; отказ второй генерации — до платного вызова.

## 3. Базовые маркеры

- healthz 2.58.95 (loopback и HTTPS) в начале/конце волн — подтверждено run-логами; MainPID 3716545, **NRestarts=0**; `user_version=36` до/после (**ΔDDL=0**; p0-pre/probe95c/final95d); **SKIPS=0**, 402=0 в окнах волн, RuntimeWarning=0; `mca_events` ERROR/CRITICAL от волн = 0 (final95d).
- T0_ERR=11 построчно = 8+2+1 (все — класс `database is locked`); INCIDENT 13:09:19 (summary) и APScheduler-ошибка 13:07:43 — деплой-окно/до волн, не от волн.
- **Живой спот 2026-10-20 (2.58.96):** healthz ok; админ-API 200 (562 item, 5 маркеров); served `/web/app.js` == HEAD (sha12 `1d68fede513e`); HTML scope-метка/версия; UI: memory-карточка «Не влияет…», freq-блок OFF-restore, mobile 390 без overflow, console errors 0.

## 4. Остатки (UNVERIFIED)

- (b) `status=ready` постгена на 1024×1024 — не наблюдался (бюджет vs латентность; observed pending/deadline_exceeded).
- (c) positive half: ready + GT-токены на тяжёлых фикстурах — не достигнуто (провайдер non-JSON, 2 фикстуры/2 волны).
- 03.11 полный per-параметр контур и 03.12 UI-часть — не в этой волне (build/UI evidence).
- Группа `content_media` («Медиа-шара») в живом окне «Выжимка видео» не отрендерилась в этих прогонах (`video_content_media.groups=[]`; диагностика ui-diag95/95b — modal_groups=[], tabs без группы). Раскрыто честно; статический/e2e маркер PASS (`focused-s10-ui-e2e.txt`). Не блокер, но live-03.1 = 4 из 5 групп, content_media — static/e2e.

## 5. Леджер-заметки (LEDGER-ACCEPT-95)

Закрываемые строки (честные формулировки):
- **CFG-03.4** → VERIFIED только live-половина: 2 горячие ручки (`flags.vision_enabled`, `limits.image_daily_limit`) проверены live без рестарта, честные статусы; полная матрица hot/restart — build-evidence (`review-cfg-03.md` f8bb638d + `evidence/cfg-03/**`). Формулировка: «live-половина 03.4 закрыта ACCEPTANCE-95 (2 ручки); полный охват — матрица CFG-03».
- **CFG-03.6** → VERIFIED: 5 мёртвых ручек + `memory_backup_keep` честно помечены (live API/UI), scope-метка; вывод из UI не требуется (решение владельца не блокирует, PET).
- **CFG-03.11** → live-спот VERIFIED (422/422/409 без записи, 3 класса); полный per-параметр negative-контур — build-evidence; не приписывать приёмке.
- **CFG-03.12** → live-половина VERIFIED (OFF/ON tool+ход; ON — анализ); UI effective state — P0V-UI/e2e evidence.
- **CFG-03.R4** → VERIFIED: `manual-checks.md` §1–3 (список + точные сценарии) существует и использован.
- **CFG-02B.2 / .2.3 / .8** → VERIFIED (live UI + мой live-спот OFF-restore; ON-состояние — `ui-live-check95.json` + скриншоты 04/05).
- **P0V-карта:** PENDING-строки — 5 заголовков разделов (L00009/18/28/33/40), не атомарные требования: закрыть как context/heading с reason; живые результаты (b)/(c) в карте не отражены — при необходимости завести строки (P0V-POSTGEN-LIVE / P0V-ADAPT-LIVE) или сослаться на `release-25895-report.md` §4; `candidate_commit` `76b156e0` устарел.
- **ADTR-POSTGEN-PENDING** → VERIFIED (live: 1 генерация → 1 bounded postgen, deadline_exceeded, доставка не блокирована, Writer честный).
- **ADTR-POSTGEN-ON** → остаётся READY_FOR_LIVE: ON-проводка/вызов подтверждены live, ready-исход не наблюдался (Finding 2).
- **ADTR-POSTGEN-OFF** → READY_FOR_LIVE (генерация при vision OFF в этой волне не выполнялась; OFF-контур — unit/байт-паритет).
- **ADTR-POSTGEN-DEDUP** → READY_FOR_LIVE (на gen1 дублей нет: 1 фото/1 пост-ответ/1 vision-вызов; cache-hit replay не воспроизводился).
- **P0V-PIPE-CONTEXT** → остаётся READY_FOR_LIVE по буквальному критерию (`[vision] postgen | … | detail=…` non-empty; retry/ready): в волне postgen detail=`-` (timeout), класс `TimeoutError` виден в `vision_adapt`; эквивалентная наблюдаемость есть, буквальный критерий не воспроизведён. Решение — за леджером.
- **REL-95 RFL-хвосты:** CFG-02A.3/.4/.5 и CFG-02.AC1 — вне этой волны (reuse CFG-02A); §4b/§4c — частично (см. выше); базовые маркеры релиза — VERIFIED; рубеж отката `9072347b`/`release/fix-2.58.94` задокументирован и историчен (прод уже 2.58.96 @ `95d11472` — свой reviewed-деплой; для 2.58.95 действий не требуется).
- **Evidence-пути для привязки (candidate `113f3a62`):** CFG-03.4 — `evidence/release-25895/acceptance/p2-vision-off.json`, `p4b-generation.json`; 03.6 — `p6b-showcase-api.json`, `ui-live-check95.json`, `ui/01–03-*.png`; 03.11 — `p5b-negatives.json`; 03.12 — `p2-vision-off.json` + `p3b/p3c-vision-adapt.json`; R4 — `plans/features/cfg/evidence/cfg-03/manual-checks.md`; CFG-02B.2/.2.3/.8 — `ui-live-check95.json`, `ui/04–06-*.png`; POSTGEN — `p4b-generation.json` (+ `p7b-economics.json`, `final95d.json`); VISION-ADAPT — `p3b/p3c-vision-adapt.json`, `runs/accept95b-run.log`, `runs/accept95d-run.log`; орфан — `probe95c.json`, `final95d.json`; уборка — `cleanup-register.json`, `final95d.json`.
- **Гейт:** `requirements_gate.py check --stage review --slice CFG-03 --candidate 113f3a62` сейчас FAIL (candidate mismatch + 19 scoped PENDING: 03.1–03.12, R1–R4, F, M, ADD-1.T3) — ожидаемо до леджера: привязать evidence и обновить `candidate_commit`; затем `--stage release`.

## 6. Nonblocking замечания (evidence hygiene)

1. `d-orphan-95b.json`/p7b `orphan_classification=no_running_rows` — false negative (p0b snapshot error); не цитировать; классификация — probe95c/final95d/95a-pre.
2. Residual photo: mid=`1166469` известен из `summary.json`; README «mid не сохранён»/«кандидаты 1166467/1166469» — уточнить.
3. README «used=16 (legacy-путь)»: точнее «15 legacy + 1 из волны 95a (резервный путь)» — приёмка сама израсходовала 1 генерацию 95a.
4. `image_postgen_vision` для parse_error: класс виден в `analysis.error_reason`, но не в `error_json` события (`error=""` — не исключение); при желании отразить parse_error в error_json (наблюдаемость, не блокер).
5. 03.11/03.12/03.1 — см. леджер: live-спот не выдавать за полный контур.

## 7. Следующее действие

LEDGER-ACCEPT-95: привязать evidence (пути acceptance) к строкам, обновить `candidate_commit`/статусы по §5, затем `--stage release`. Прод-код не менялся; карты не редактировались. Мой docs-коммит — только этот файл.
