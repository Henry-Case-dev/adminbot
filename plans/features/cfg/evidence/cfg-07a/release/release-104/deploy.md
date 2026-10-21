# DEPLOY-258104 — evidence: выкат 2.58.104 (CFG-07D.5 bounded metatext retry + FA/MB-детекторы + леджер CFG-07A + бамп) и постдеплой-речек 07A-1/07C.6/07D.5

Релиз: **2.58.104** — bounded metatext-retry в factcheck v2 (≤1 metatext-повтор
из общего бюджета, честный `metatext_fallback`), FA/MB-детекторы корпуса в
`public_speech_guard` (FA-01/02/06/07/08, MB-10/11/12, фикс char-class дефекта
`_bracket_block_re`), retry-канон в `prompt_style_blocks`, леджер CFG-07A,
релизный бамп. Ревью **Approved** — `review-rel.md` (REV-REL-258104; гейт
review-stage EXIT 0 на `d860a529`, поезд подтверждён на `8ea6ed4e`).
Миграций нет (ΔDDL=0), user_version 37 остаётся; промпт-миграция штатно на
старте bot.py.

- **Фактический deployed SHA: `8ea6ed4e016cf8fbb23e1447cb02503c54131650`**
  (= `origin/master` = ревью-кандидат поезда; verified on prod: fetch
  `2a3e4fc9..8ea6ed4e master`, checkout -B master, NEW_HEAD == 8ea6ed4e,
  TRACKED_MOD_AFTER=0).
- **Привязка кандидата (уточнение брифa):** в брифе лейна кандидатом назван
  `6388899d` — это промежуточный F1-фикс **внутри истории мастера**
  (предок `8ea6ed4e`, проверено `git merge-base --is-ancestor`, APP_VERSION на
  нём 2.58.101), а не голова кандидата. Авторитетная привязка — review-rel.md:
  поезд `8ea6ed4e`, гейт на `d860a529`, «docs поверх, код == кандидату».
  Задеплоен `8ea6ed4e` — ровно то, что одобрил Reviewer.
- Прод ДО: `2a3e4fc9` (2.58.103, healthz 2.58.103, MainPID 7265) → ПОСЛЕ:
  **`8ea6ed4e` (2.58.104, MainPID 29475, ExecMainStart 21:00:38Z,
  NRestarts=0, active/running)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит). **MUTABLE_
  WORKTREE_REQUIRED: no** — запись: прод-репо /var/www/admin_bot (checkout),
  /tmp, DevOps-scratch, этот evidence-каталог. **PG — только read-only пробы
  (SELECT; SET_CALLS=0 через RO-shim резолва).**
- **T0: 1792530023 (2026-10-20 21:00:23Z)**, RESTART_RC=0; healthz 2.58.104
  через ~20 с (POLL7, 21:00:58Z). Рестарт предыдущего процесса — штатный
  SIGTERM systemctl, шатдаун-транзиентов в журнале с T0 нет (ERR=0).

## Гейты перед рестартом (все OK)

- FETCH1_RC=0; ORIGIN_MASTER == 8ea6ed4e == кандидат (CAND_TO_OM = 0/0);
  RB_IS_ANCESTOR=1 (2a3e4fc9 — предок); NEW_HEAD==ORIGIN_MASTER;
  TRACKED_MOD_AFTER=0; COLLIDE_COUNT=0; OWN_BAD_BEFORE=0/AFTER=0.
  Fetch также принёс **новую ветку `origin/release/fix-2.58.103` = `79df9f5d`**
  (создана Reviewer при push — граница отката по заявке review-rel).
- DELTA 2a3e4fc9→8ea6ed4e: total 54; **runtime set == ровно 5 файлов**
  (config/settings.py, services/factcheck_service.py,
  services/negative_constraints.py, services/prompt_style_blocks.py,
  services/public_speech_guard.py); **DELTA_DDL=0** (database.py, scripts/ —
  пусто); DELTA_OTHER_NONSTD=0.
- sha256_12 на диске прода == локальному кандидату (raw-byte из git cat-file,
  pf104.py): settings `75d7cec36e84`, factcheck_service `afdbf77a3a2b`,
  negative_constraints `e1ca1844e2ed`, prompt_style_blocks `a7b76755e589`,
  public_speech_guard `bfcfa213eb59`, README `99833a6bd1fc`,
  database.py `b7fdd7615a52` (неизменный контроль),
  web/app.js `db8457cafa9b` (неизменный контроль).
- Маркеры: `APP_VERSION = "2.58.104"` =1; `def guard_public_text` =1;
  `egress_guard` wiring =2 (factcheck_orchestrator + tool_router);
  standalone `"flagged"` в гвард-файлах = **0** (голых `flagged` = 3 —
  пре-существующий `lore_stats_recheck_flagged` в tool_router, вне семантики
  B1; урок аборта 103 учтён); `FACTORY_SET_SHA256_12` = `037080375ac8` =2
  (отпечаток не тронут); F8-meta содержит `d860a529` =1; лестницы
  `PREV_*_CFG07A` = 21; `def rollback_prompt_canons` =1 (async) —
  **откат-механизм на месте, НЕ применялся**.
- 07D.5 wiring на прод-байтах: `_metatext_retry_reason` def=1 (factcheck_
  service, вызова 2), `metatext_retry_reason` def=1 (guard),
  `METATEXT_RETRY_SYSTEM_PROMPT` =1 (prompt_style_blocks, R17 на месте),
  `metatext_fallback` =4 (negative_constraints), `pipeline_v2_enabled` в
  factcheck_service =2 (тот же единый V2-гейт; нового чтения рубильника нет).

## Здоровье и смоук

- healthz: loopback `{"status":"ok","version":"2.58.104"}` и внешний (HTTPS
  admin-bot.duckdns.org, вне SSH) `200 …2.58.104`; `/web/` 200; served app.js
  sha `db8457cafa9b` == диск == кандидат.
- `[config_cache] initialized: settings=532 roles=4 admins=3`;
  `[database] migrations: start | current user_version=37 | pending=[]` →
  `complete | user_version=37 | total 0.0s` — **ΔDDL=0 подтверждён на проде**.
  (sqlite-pragma проба одношотовым скриптом не выполнена: ImportError DB_PATH —
  тот же известный дефект fn102; v37 подтверждён журналом сервиса.)
- Промпт-миграция: `[prompt_migration]` 16 строк, **ошибок 0**, **0× «канон
  обновлён»**; **11× «кастом юзера — НЕ трогаем»** — включая все 7 целевых
  ключей CFG-07A с прежними длинами (5294/3558/2312/2622/2252/2248/2071);
  5× «уже новый канон».
- **Сообщений в чаты не отправлялось** (запрет лейна).

## Постдеплой 07A-1 (CFG-07A.1, live_required=postdeploy) — read-only, штатный механизм

Метод — прецедент deploy-258103 §постдеплой: RO asyncpg SELECT (7 ключей +
`character.prompt_history`) → deployed `resolve_speech_value(key, stored,
source="global", cache=RO-shim)`, RO-shim отдаёт реальный провенанс-док из PG,
`cache.set` бросает исключение (доказательство 0 записей через путь резолва).

- **(a) БАЙТЫ: 7/7 UNCHANGED.** sha256_12/len каждого ключа байт-в-байт равны
  пре-деплой-снимку recon104 и базе deploy-258103: direct_chat
  `cf404931f84c`/5294, summary `d697b0745b29`/3558, checkup `1e8a3c69cf7b`/2312,
  search `ba43fb679db6`/2622, youtube `e0a1ffaf18a1`/2252, youtube_video
  `c8bba06ec6a8`/2248, webpage `7801085b6ef5`/2071. Провенанс-док
  `21f71e8d21e4`/374 (не менялся). **PG не мутирован.**
- **(b) EFFECTIVE: 7/7 `withheld=True, reason=provenance_missing`** →
  effective = **чистые заводские каноны 07A-2** (source=default). Маркеры
  корпуса на effective: **0 по всем 7** (SF-семья, bracket-FA-08
  «[системное уведомление», UNCHANGED-эхо, `_legacy_persona_marker_re` 0,
  `_corpus_extra_marker_re` 0).
- **Лестницы распознают прод-байты: 7/7** — `suppress_legacy_speech(
  custom_clean=True)` applied=True на всех 7 с ожидаемыми labels.
- **КАСТОМЫ ВЛАДЕЛЬЦА: в хранилище целы байт-в-байт (a); в effective
  отсутствуют** (withheld провенанс-гейтом SOUL-AMD). Результат
  `owner_present=0` **байт-в-байт совпадает с финалом deploy-258103**
  (final103-run.txt: те же 8 ctx-фрагментов, len_delta_prev=-35) — состояние
  идентично 2.58.101/102/103, код удержания вне диффа поезда 104 — **не
  регрессия деплоя**. Активация кастомов — добровольное решение владельца
  (owner_live_checks §8 / OQ-15, не блокер).

## Постдеплой 07C.6/07D.5 (телемetry) — наблюдение продолжается

Окно T0 21:00:23Z → 21:02:0xZ (238 строк журнала): `SPEECH_GUARD_WARN=0`,
`EGRESS_GUARD_EVENT=0`, `METATEXT=0`. Гварды пишут WARNING только при
флагах/инцидентах — ноль при чистой речи есть норма; флаганного фактчек-
трафика в окне не наблюдалось. **V2-рубильник не тронут: hot
`flags.factcheck_pipeline_v2` = 'true' (bot_settings), env UNSET** — контур
v2 (включая новый metatext-retry) активен на проде так же, как с 2.58.102.
Wiring подтверждён на задеплоенных байтах (маркеры выше) + CONTRACT-тесты
ревью (41 guard + 346 фактчек-семья). Runtime-путь retry/детекторов под
реальным флаганным трафиком на проде ещё не наблюдался — **честный статус:
наблюдение продолжается** (прецедент 07C.6). Аварийных признаков нет.

## ERR since T0

ERROR-строк: **0** (финальный срез 238 строк: ERR=0, RuntimeWarning=0,
PROMPT_MIG_ERR=0; ingestion/worker/scheduler живут, vision-probe ошибок нет).
Новый процесс 29475 чист. Откат не требуется.

## Откат (задокументирован, НЕ применялся)

- **Основной: `git -C /var/www/admin_bot checkout -f 2a3e4fc94705cf5741a6755
  e6098bb9e52f3c096` + `sudo systemctl restart admin_bot` → 2.58.103** —
  точное предыдущее состояние прода (проверен на проде в deploy-258103);
  потерь нет: ΔDDL=0, схема/данные не менялись, каноны не переписывались
  (0 обновлений, 0 set-calls). Повторный выкат 2.58.104 идемпотентен.
- **Коррекция брифа/review-rel:** названная там граница `79df9f5d`
  (= origin/release/fix-2.58.103, пришла fetch'ем) — док-коммит **до** бампа
  103: код == 2.58.103, но `APP_VERSION = "2.58.102"`, healthz после отката
  показал бы 2.58.102. Поэтому первичная точка отката — `2a3e4fc9`
  (код+версия == бывший прод). `79df9f5d` — валидная запасная точка того же
  кода.
- Каноны: `rollback_prompt_canons` / PREV-лестницы (21 ступень) — без git и
  без рестарта. Софт-выключение 07D.5: hot-флаг `flags.factcheck_pipeline_v2`
  → false или env `FACTCHECK_PIPELINE_V2_ENABLED=false` (не применялось;
  флаг владельца не трогался).

## Release-гейт

`requirements_gate.py check --map plans/features/cfg/requirements-map.json
--stage release --candidate 8ea6ed4e --deployed-commit 8ea6ed4e --repo .` →
**EXIT 1, errors=458** (inventory=246, manual=42, scoped=245; полный вывод —
scratch `release-gate-104.txt`). Расклад:

- **1 × top-level «candidate mismatch»**: map `candidate_commit` = `d860a529`
  (привязка леджера dd6acf83, сделанная Reviewer'ом), гейт требует
  map == `--candidate` == `--deployed-commit`; подмена привязки поезда для
  зелёного гейта не производилась.
- **457 × открытые будущие волны CFG-фичи** (ADD-0.1–0.6 PENDING, ADD-1.C*,
  CFG-01.*, CFG-02A.* — без evidence by design, фича не закрыта).
- **Слайс поезда CFG-07A — в failures отсутствует (0 ошибок)**: леджер-хвост
  (deployed_commit + evidence @ 8ea6ed4e + note) принят гейтом.

Структурно красная открытая карта — прецедент deploy-258100/258101/258102/
258103 (там EXIT 1 errors=460): поезд не заявляет DONE фичи; релиз-вердикт
поезда — Orchestrator/Reviewer на базе review-rel (review-stage EXIT 0) +
этой трассы.

## Леджер-хвост (review-rel постдеплой п.4)

- top-level `deployed_commit` → `8ea6ed4e…`; CFG-07A.1: + production-evidence
  @ candidate `8ea6ed4e` (release-104/deploy.md), note → `VERIFIED @ deployed
  8ea6ed4e (2.58.104), 21.10.` Больше в карте ничего не менялось.

## SSH-бюджет и гигиена

3 коннекта, один логин `nik`, паузы ≥75 с, без параллелей/поллеров:
recon (20:58:52Z, ~15 с таймауты) → основной (21:00:18Z) → финал (21:02:00Z).
Пароли только через stdin (sudo -S) и env git-credential, в argv/логе не
печатались. Внешние пробы — HTTPS 443. Инцидентов fail2ban нет.

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырьё —
  `OPENCODE_WORKFLOW_SCRATCH/deploy-258104/`: `recon104.txt` (PRE-байт-снимок
  7 ключей + провенанс-док + V2-флаг), `main104-run.txt`, `t0_104.txt`,
  `journal104-since-T0.raw`, `journal104-final.raw`, `final104-run.txt`,
  `preflight-104.txt`, скрипты `pf104/rc104/dp104/fn104` (.py).
