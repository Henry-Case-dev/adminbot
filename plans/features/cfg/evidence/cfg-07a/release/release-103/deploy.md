# DEPLOY-258103 — evidence: выкат 2.58.103 (CFG-07C-G egress-guard + TAIL/B1 + бамп) и постдеплой-речек 07A-2/07C.6

Релиз: **2.58.103** — egress speech-guard `public_speech_guard` на outbound-швах
(factcheck_v2 + tool_router), TAIL-гварды, B1-фикс телеметрии
(flagged→failed ×2), релизный бамп. Ревью **Approved** — `review-rel.md`
(REV-REL-258103; гейт review-stage EXIT 0). Кандидат == `origin/master`.
Миграций нет (ΔDDL=0), user_version 37 остаётся; промпт-миграция штатно на
старте bot.py.

- **Фактический deployed SHA: `2a3e4fc94705cf5741a6755e6098bb9e52f3c096`**
  (= `origin/master` = ревью-кандидат; verified on prod: fetch
  `a3535b68..2a3e4fc9 master`, checkout -B master, NEW_HEAD == 2a3e4fc9,
  TRACKED_MOD_AFTER=0).
- Прод ДО: `a3535b68` (2.58.102, healthz 2.58.102, MainPID 666) → ПОСЛЕ:
  **`2a3e4fc9` (2.58.103, MainPID 7265, ExecMainStart 19:09:40Z, NRestarts=0,
  active/running)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит). Рубеж отката
  `origin/release/fix-2.58.102` == `a3535b68` подтверждён fetch'ем на проде
  (ветка пришла тем же fetch'ем). **MUTABLE_WORKTREE_REQUIRED: no** — запись:
  прод-репо /var/www/admin_bot (checkout), /tmp, DevOps-scratch, этот
  evidence-каталог. **PG — только read-only пробы (0 записей).**
- **T0: 1792523372 (2026-10-20 19:09:32Z)**, RESTART_RC=0; healthz 2.58.103
  через ~28 с (POLL7). Наблюдение ДО деплоя: сервис был рестартнут 18:42:30Z
  (PID 666, NRestarts=0) до начала лейна — HEAD оставался a3535b68, дерево
  чистое, на деплой не влияет.

## Гейты перед рестартом (все OK)

- ORIGIN_MASTER == 2a3e4fc9 == кандидат (CAND_TO_OM = 0/0); RB_REF ==
  a3535b68; RB_IS_ANCESTOR=1; NEW_HEAD==ORIGIN_MASTER; TRACKED_MOD_AFTER=0;
  COLLIDE_COUNT=0; OWN_BAD_BEFORE=0.
- DELTA a3535b68→2a3e4fc9: total 65; **runtime set == ровно 4 файла**
  (config/settings.py, services/factcheck_orchestrator.py,
  services/public_speech_guard.py, services/tool_router.py); **DELTA_DDL=0**
  (database.py, scripts/ — пусто); DELTA_OTHER_NONSTD=0.
- sha256_12 на диске прода == кандидату (7/7, raw-byte из git cat-file):
  settings `61df15f9c5f4`, factcheck_orchestrator `2ee2c6582d75`,
  public_speech_guard `f46533c6f100`, tool_router `f2d7b66d43b5`,
  README `c5b31ae8dd0e`, database.py `b7fdd7615a52` (неизменный контроль),
  web/app.js `db8457cafa9b` (неизменный контроль).
- Маркеры: `APP_VERSION = "2.58.103"` =1; `def guard_public_text` =1;
  `egress_guard` wiring =2 (factcheck_orchestrator + tool_router);
  standalone-исход `"flagged"` в гвард-файлах = **0** (B1-фикс на проде);
  `FACTORY_SET_SHA256_12` = `037080375ac8` (отпечаток не тронут); F8-meta
  содержит `79df9f5d` =1; лестницы `PREV_*_CFG07A` = 21; `rollback_prompt_
  canons` def=1 — **откат-механизм на месте, НЕ применялся**.

## Здоровье и смоук

- healthz: loopback `{"status":"ok","version":"2.58.103"}` и внешний (HTTPS
  admin-bot.duckdns.org, вне SSH) `200 …2.58.103`; `/web/` 200; served app.js
  sha `db8457cafa9b` == диск == кандидат.
- `[config_cache] initialized: settings=532 roles=4 admins=3`;
  `[database] migrations: start | current user_version=37 | pending=[]` →
  `complete | user_version=37 | total 0.0s` — **ΔDDL=0 подтверждён на проде**.
  (sqlite-pragma проба одношотовым скриптом не выполнена: ImportError DB_PATH
  — тот же известный дефект fn102; v37 подтверждён журналом сервиса.)
- Промпт-миграция: `[prompt_migration]` 16 строк, **ошибок 0**, **0× «канон
  обновлён»**; **11× «кастом юзера — НЕ трогаем»** — включая все 7 целевых
  ключей CFG-07A с прежними длинами (5294/3558/2312/2622/2252/2248/2071) +
  verbalizer/factcheck/summary_editor/summary_narrator; 5× «уже новый канон».
- **Сообщений в чаты не отправлялось** (запрет лейна).

## Постдеплой 07A-1 (CFG-07A.1, live_required=postdeploy) — read-only, штатный механизм

Метод — прецедент deploy-258102 §постдеплой: 1 SSH-коннект, read-only asyncpg
SELECT (7 ключей + `character.prompt_history`) → deployed
`resolve_speech_value(key, stored, source="global", cache=RO-shim)`, RO-shim
отдаёт реальный провенанс-док из PG, `cache.set` бросает исключение
(доказательство 0 записей через путь резолва). Единый резолв рантайма.

- **(a) БАЙТЫ: 7/7 UNCHANGED.** sha256_12/len каждого ключа байт-в-байт равны
  пре-деплой-снимку (recon103) и evidence deploy-258102: direct_chat
  `cf404931f84c`/5294, summary `d697b0745b29`/3558, checkup `1e8a3c69cf7b`/2312,
  search `ba43fb679db6`/2622, youtube `e0a1ffaf18a1`/2252, youtube_video
  `c8bba06ec6a8`/2248, webpage `7801085b6ef5`/2071. `SET_CALLS=0`. **PG не
  мутирован.**
- **(b) EFFECTIVE: 7/7 `withheld=True, reason=provenance_missing`** →
  effective = **новые чистые заводские каноны 07A-2** (source=default).
  Маркеры корпуса на effective: **0 по всем 7** — sf_hits=0 (safety-bypass
  «Игнорируй все настройки…», identity «бот-абьюзер», «перегрелись»,
  sneer/hostility-фрагменты, bracket-FA-08 «[СИСТЕМНОЕ УВЕДОМЛЕНИЕ»,
  UNCHANGED-эхо), `_legacy_persona_marker_re` 0, `_corpus_extra_marker_re` 0.
- **Лестницы распознают прод-байты: 7/7** — deployed
  `suppress_legacy_speech(custom_clean=True)` applied=True на всех 7 ключах
  с ожидаемыми labels (identity_sentence везде; direct +style+honest_
  concession; summary/checkup/search +safety+tone+специфичные; youtube×2/
  webpage +safety+tone+hostility). Миграция на старте: 7× «кастом юзера — НЕ
  трогаем» с точными длинами.
- **ПРАВКИ ВЛАДЕЛЬЦА: в ХРАНИЛИЩЕ целы байт-в-байт** (см. (a)); **в EFFECTIVE
  отсутствуют — кастом не активен**: провенанс-гейт SOUL-AMD удерживает
  значения, не записанные через API реестра. Состояние **идентично
  2.58.101/102**, код удержания вне диффа этого поезда — **не регрессия
  деплоя**. Зафиксировано по брифу: effective = новые чистые каноны, PG-байты
  владельца не тронуты. Финальный вердикт по строке карты — Reviewer/
  Orchestrator (прецедент deploy-258102; карту DevOps не менял).

## Постдеплой 07C.6 (телеметрия egress_guard) — наблюдение продолжается

Окно T0 19:09:32Z → 19:14:04Z (~4.5 мин, 440 строк журнала):
`SPEECH_GUARD_WARN=0`, `EGRESS_GUARD_EVENT=0`. Гварды пишут WARNING
(`speech guard` / stage_event `egress_guard`) **только при флагах/инцидентах**
— ноль при чистой речи есть норма. Флаганного фактчек-трафика в окне не
наблюдалось. **Честный статус: наблюдение продолжается** — рантайм warn-путь
под реальным флаганным трафиком на проде ещё не наблюдался; wiring
подтверждён на задеплоенных байтах (guard_public_text def=1, egress_guard ×2
шва, standalone `flagged` outcome=0) + CONTRACT-тесты ревью (96p, вкл. 29
tail/telemetry с runtime-пробой build_event). Аварийных признаков нет.

## ERR since T0

ERROR-строк: **2** — одно событие: 19:09:33 **старый** процесс (PID 666,
2.58.102) — `apscheduler … SummarySchedulerService._tick … CancelledError` +
Traceback: тик планировщика отменён SIGTERM при рестарте. Шатдаун-транзиент
предыдущего процесса, к дельте поезда не относится. **Новый процесс (7265):
ERR=0**; PROMPT_MIG_ERR=0, RuntimeWarning=0; vision-probe
`outcome=success`; ingestion/worker/scheduler живут. Откат не требуется.

## Откат (задокументирован, НЕ применялся)

- Каноны: `rollback_prompt_canons` / PREV-лестницы `PREV_*_CFG07A` (21
  ступень на проде) — без git и без рестарта.
- Код: `git -C /var/www/admin_bot checkout -f a3535b68a3220f5a239ed7df3eb1a24f1e1d0873`
  (== `origin/release/fix-2.58.102`, verified on prod) + `sudo systemctl
  restart admin_bot` → 2.58.102. Потерь нет: ΔDDL=0, схема/данные не
  менялись, каноны не переписывались (0 обновлений, 0 set-calls) — откат
  состояния PG не требуется. Повторный выкат 2.58.103 идемпотентен.

## Release-гейт

`requirements_gate.py check --map plans/features/cfg/requirements-map.json
--stage release --candidate 2a3e4fc9 --deployed-commit 2a3e4fc9 --repo .` →
**EXIT 1, errors=460** (inventory=246; «candidate mismatch»: карта привязана
к 211a8c1b + открытые волны/ADD-0.x PENDING/исторические биндинги).
Структурно красная открытая карта — прецедент deploy-258100/258101/258102:
поезд не заявляет DONE фичи; релиз-вердикт поезда — Orchestrator/Reviewer на
базе review-rel + этой трассы.

## SSH-бюджет и гигиена

4 коннекта, один логин `nik`, паузы ≥75 с, без параллелей/поллеров:
recon (19:04:56Z) → основной №1 (19:06:48Z, **аборт по дефектному гейту
DevOps GUARD_FLAGGED=3**: паттерн `flagged` зацепил пре-существующий
идентификатор `lore_stats_recheck_flagged` в tool_router.py — чужая
подсистема, поездом не тронута; исправлен на standalone `'"flagged"'` ==
семантика B1-проверки ревью, 0 на кандидате, проверено локально до второго
прогона; дерево автоматически восстановлено в a3535b68, рестарта не было,
сервис не затронут) → основной №2 (19:09:28Z, успешный) → финал (19:14:04Z).
Пароли только через stdin (sudo -S) и env git-credential, в argv/логе не
печатались. Внешние пробы — HTTPS 443. Инцидентов fail2ban нет.

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырьё —
  `OPENCODE_WORKFLOW_SCRATCH/deploy-258103/`: `recon103.txt` (включая
  PRE-байт-снимок 7 ключей + провенанс-док), `main103-run.txt`,
  `journal103-since-T0.raw`, `journal103-final.raw`, `final103-run.txt`,
  `t0_103.txt`, скрипты `rc103/dp103/fn103` (.py).
