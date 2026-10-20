# DEPLOY-258100 — evidence: выкат 2.58.100 (samples-ux) + миграция SQLite v37

Релиз: **2.58.100** — samples-ux (библиотека примеров: 3 категории,
редактируемые заводские наборы, UI) в составе релизного поезда. Ревью
**Approved** — `plans/features/samples-ux/evidence/release/review-rel.md`
(REV-REL-258100, кандидат `acc285d7` = HEAD master). Миграция v37 применена
штатно при старте сервиса.

- **Фактический deployed SHA: `acc285d77d03c7adbf5527dc7f0fa9e9904fed8e`**
  (= `origin/master`; verified on prod: fetch `7142ffcf..acc285d7 master`,
  checkout -B master, HEAD_POST == acc285d7, TMOD=0).
- Прод ДО: `7142ffcf` (2.58.99, healthz 2.58.99, MainPID 3966377) → ПОСЛЕ:
  **`acc285d7` (2.58.100, MainPID 3989095)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит); fetch подтвердил
  рубеж отката `origin/release/fix-2.58.99` == `7142ffcf` (new branch on prod).
  **MUTABLE_WORKTREE_REQUIRED: no** — запись: прод-репо /var/www/admin_bot
  (checkout -B master), прод-БД (штатная миграция v37 при старте), /tmp,
  DevOps-scratch, этот evidence-каталог, поле deployed_commit карты samples-ux.

## Таймлайн (server UTC)

- Recon 11:35:08Z: прод 2.58.99, healthz `2.58.99`, TMOD=0, UNTRACKED=13
  (pre-existing), NRestarts=0; **пре-миграционная БД: user_version=36,
  humor_samples rows=31, cols=25**.
- Main 11:36:46–11:38:37Z: fetch RC=0 (OM=acc285d7, RB=7142ffcf — оба сверены
  на проде), checkout RC=0, APP_VERSION_PIN=1; **T0 11:36:48Z (epoch
  1792496208)**, RESTART_RC=0; MainPID **3989095**, ExecMainStart 11:37:06Z,
  ExecMainStatus=0, active/running, **NRestarts=0**.
- Миграция (в журнале приложения): 11:37:25Z `[database] migrations: start |
  current user_version=36 | pending=[37]` → backup-guard **153.0s**
  (`pre-migration copy created + read-back ok | target_version=36`, старый
  бэкап ротирован disk_retention) → 11:39:58Z **v37 applied**:
  - `migration v37: humor_samples +columns ['category', 'expression_mode',
    'tombstone', 'tombstone_at', 'owner_modified', 'owner_modified_at']` (+6);
  - `migration v37: category backfill {'mat': 12, 'humor': 16, 'legacy': 3,
    'mode_from_tag': 12}` — 12+16+3=31 == все строки учтены;
  - `[database] migrations: complete | user_version=37 | total 153.3s`.
- Внешний HTTPS healthz `{"status":"ok","version":"2.58.100"}` к 11:40:40Z
  (~4 мин стартапа: VACUUM-копия на прод-объёме — задокументированное
  поведение backup-guard'а). Final-верификация 11:42:43Z.

## Миграция и сохранность данных (read-only PRAGMA/SELECT через прод-venv)

- **user_version: 36 → 37** ✓; **rows: 31 → 31** (ни одна строка не потеряна);
  **cols: 25 → 31** (+6, список совпадает с SAMPLES_V37_ADD_COLUMNS).
- Дистрибуция категорий после: `humor=16, legacy=3, mat=12` — **байт-в-байт
  равна счётчикам бэкфила**; expression_mode: `off=4, occasional=4,
  frequent=4` (12 == mode_from_tag), 19 пустых (не expression_register).
- Ошибок миграции/бэкфила нет: `backfill row failed`=0, `[humor-samples]`
  warnings=0, Traceback=0, `[database] migration v36` не появлялась
  (v36 уже была). Pre-migration backup создан и прочитан обратно до DDL.
- Ограничение пробы: разрез по `tombstone` не снят (в пробе-скрипте был неверный
  идентификатор колонки `is_tombstoned`; фактическая колонка — `tombstone`,
  в схеме есть, DDL применился). Не влияет на acceptance-пункты полосы;
  SQL-ручками сверх процедуры не лезли.

## Здоровье и смоук

- healthz: loopback и внешний (HTTPS, admin-bot.duckdns.org)
  `200 {"status":"ok","version":"2.58.100"}`; `/web/` 200;
  `/web/app.js` 200, **served sha256 `db8457ca…` == диск на проде ==
  git-блоб `acc285d7:web/app.js`** (полная цепочка байтов).
- `config_cache initialized: settings=532 roles=4 admins=3`; prompt/config
  миграции: 13× «кастом юзера — НЕ трогаем» (прецедентный паттерн), остальное
  «уже новый канон»; фактчек-флаг не трогался (ON с 2.58.99).
- **Сообщений в чаты не отправлялось** (запрет лейна).

## ERR since T0 — честная классификация

`J_ERR=2` (при требовании полосы ERR=0). Обе строки — **один инцидент**
`inc_c16332769f7648179ffeb44f57bf3ab3` (`component=incidents`,
`reason_code=incident_opened`, `pipeline_type=vision.media`, 11:40:01–02Z,
`outcome=success`, stage=takeover): инцидент-менеджер нового процесса
зафиксировал прерванное рестартом in-flight vision-задание — на старом PID в
11:36:54Z было `[vision] drain timeout | inflight=1` (типовой артефакт любого
рестарта, pre-existing паттерн). После старта vision-воркера (11:40:02Z) тики
успешны каждые 5с, отказов нет, CRIT=0, Traceback=0. Классификация:
**рестарт-транзиент, не дефект 2.58.100/samples-ux**; runtime-ошибок после
стабилизации — 0. Попутная находка, не блокер (см. ниже).

## Откат (задокументирован, НЕ применялся)

- Cold: `git checkout -f 7142ffcf47ce4667cf22113c56881d3f1abb29a2`
  (== `origin/release/fix-2.58.99`, verified on prod после fetch) +
  `sudo systemctl restart admin_bot` → 2.58.99. Совместимость: v37-схема
  работает со старым кодом — все +6 колонок NOT NULL с DEFAULT/nullable
  (review-rel §3: INSERT заполняет дефолты, SELECT старые колонки не трогает);
  повторный выкат 2.58.100 безопасен — миграция идемпотентна.
- Soft: не применим к DDL (флага у релиза нет); при проблеме данных —
  pre-migration копия на проде (`pre_migration_*`, создана backup-guard'ом
  перед DDL, read-back ok).

## Release-гейт (структурная красная зона поезда)

`requirements_gate.py check --map plans/features/samples-ux/requirements-map.json
--stage release --repo .`:
- `--candidate acc285d7 --deployed-commit acc285d7` → **EXIT 1, errors=129**:
  evidence строк привязан к слайс-кандидату `27b1165a` (REV-SAMPLES-UX),
  гейт требует биндинг к поданному кандидату;
- `--candidate 27b1165a --deployed-commit acc285d7` → **EXIT 1, errors=1**
  («deployed differs from reviewed candidate»; все остальные проверки зелёные).
- Причина: гейт v2 сравнивает SHA буквально и не моделирует «деплой HEAD
  поезда ⊇ слайс-кандидат с идентичными байтами фичи» (review-rel §1:
  «Samples-ux файлов в бампе НЕТ» — runtime-байты 27b1165a == acc285d7).
  Биндинги evidence честно не переписывались. Итоговый release-вердикт —
  за Orchestrator/Reviewer.

## Попутные находки (не блокеры)

1. (info) `[vision] drain timeout | inflight=1` на останове старого PID →
   INCIDENT incident_opened (vision.media) на новом — рестарт-артефакт,
   pre-existing паттерн; воркер здоров. Наблюдение можно продолжить вне полосы.
2. (info) Стартап с VACUUM INTO backup-guard занимает ~4 мин на прод-объёме —
   healthz недоступен ~3 мин после рестарта; ожидаемо по коду
   («на прод-объёме может занимать минуты»), учесть в будущих окнах.
3. (info) Баг пробы `is_tombstoned` (см. «Ограничение пробы») —
   скриптовый, не прод.

## SSH-бюджет и гигиена

**3 коннекта**, один логин `nik`: recon 11:35:08Z (read-only), main
11:36:46Z, final 11:42:43Z (read-only); паузы >1 мин, без параллелей/поллеров
по SSH; пароли только через stdin (sudo -S) и SFTP-файл 0600 (git askpass),
в argv/выводе не печатались (scrub). Внешние пробы — HTTPS 443 (домен),
не ограничены. Инцидентов fail2ban нет.

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырьё —
  `OPENCODE_WORKFLOW_SCRATCH/deploy-258100/`: `recon100.txt`, `main100-run.txt`,
  `final100-run.txt`, `journal100-since-T0.raw` (полный, 311 строк),
  `postdeploy_http.txt`, скрипты `rc100/dp100/fn100` (.py+.sh).
