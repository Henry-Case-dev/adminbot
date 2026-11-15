# VMQ-ONTO-01 / 2.58.204 — controlled production deploy

Дата: 2026-11-15 (UTC). Прогон: **02:58:35–03:02:47Z** (деплой + проверки),
read-only e2e и повторная сверка — **03:04–03:09Z**. Сервер:
`192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`, user `adminbot`.

Кандидат: **`2b419aa2627f627eb6ea5e2f46b5e01118da2bf0`**, ветка
`release/vmq-onto-01-2.58.204`, версия **2.58.204** (train tip).
Предыдущая production-версия / rollback target:
**`c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` / 2.58.203**.

## 0. Deploy admission (факт порядка)

- Независимое дельта-ревью **точного tip** `2b419aa2` — **Approved for
  controlled deployment only** (`delta-review-r1.md`, sha256
  `4BAC1DE32D31C3B5D8C358941DA74C08238CA0D0CA1B4EB9D01E5831E3E69C9F`).
  156 тестов поезда, мутации, DDL 0/schema 47, без composer/config/gates/
  migrations, блокирующих находок нет.
- `requirements_gate.py --stage deploy` **не может привязать top-level train
  candidate**: карта требований держит `candidate_commit = c97c06e4`
  (сознательно, до фактического деплоя), поэтому `--candidate 2b419aa2`
  даёт `candidate mismatch`, а ONTO-B/M2 дополнительно красные только на
  intra-train зависимостях O-01/O-02/O-03 (они становятся VERIFIED лишь
  после выката). Формального «train gate pass» нет и здесь не заявляется;
  контролируемый допуск — дельта-ревью точного tip. Статусы карты DevOps
  не менял: M-04/O-04 остаются `READY_FOR_LIVE` с одобренным
  postrelease-wait (addendum M2 review sha `2E980F19…`), memory-строки
  открыты.

## 1. Pre-state

```
UTC                 2026-11-15T02:58:35Z
HEAD                c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
BRANCH              release/smart-corrective-01
APP_VERSION         2.58.203
TRACKED_DIRTY       0 (untracked только .cache/)
MIGRATION_STEPS     47
UNIT                active, MainPID 887397, NRestarts 0,
                    start 2026-11-14 18:56:49 UTC
HEALTH_LOCAL        200 {"status":"ok","version":"2.58.203"}
HEALTH_PUBLIC       200 {"status":"ok","version":"2.58.203"}
DISK                20 334 660 KB free (/), 80%
DB_BYTES            3 289 079 808
BACKUPS_BYTES       39 751 273 374 (pre-existing, не чистился)
MANIFEST            c97c06e4 / 2.58.203 / previous 0beed63d / 2.58.202
```

Preflight кандидата (worktree `release/vmq-onto-01-2.58.204`, unit
`vmq-onto-01-release-2.58.204`): `HEAD=2b419aa2`, `origin` тот же SHA,
tracked dirty 0, `merge-base c97c06e4`, `APP_VERSION=2.58.204`,
`MigrationStep(` = 47, DDL-операторов в диффе 0, manifest dry-run:
`version=2.58.204, deployed_sha=2b419aa2, dirty_tracked=false,
release_branch=release/vmq-onto-01-2.58.204`.

## 2. Backup

```
path        /var/www/admin_bot/backups/pre_deploy_258204_20261115T025835Z.db
size        3 289 239 552 B
sha256      93604b36a6a573758b8603509bb251bda6881cf7572ec65ff1df610b44f8f200
integrity   ok
user_version 47
tables      130
```

SQLite `.backup()` по read-only соединению (`mode=ro`), затем read-back
`PRAGMA integrity_check`/`user_version`/таблицы. `backups/` не чистился;
после деплоя 43 040 512 926 B, свободно 13 917 636 KB.

## 3. Fetch / checkout / manifest

```
git fetch origin +refs/heads/release/vmq-onto-01-2.58.204:refs/remotes/...
FETCH_RC     0
git switch -C release/vmq-onto-01-2.58.204 origin/release/vmq-onto-01-2.58.204
SWITCH_RC    0
HEAD         c97c06e4..2b419aa2
BRANCH       release/vmq-onto-01-2.58.204
UPSTREAM     origin/release/vmq-onto-01-2.58.204
tracked dirty 0
APP_VERSION  2.58.204
```

Manifest записан **до** рестарта (`venv/bin/python tools/release_manifest.py
--deployer devops`, rc=0), `chown adminbot:adminbot`, chmod 644:

```json
{"deployed_at": "2026-11-15T03:00:14.096313Z",
 "deployed_sha": "2b419aa2627f627eb6ea5e2f46b5e01118da2bf0",
 "deployer": "devops", "dirty_tracked": false, "effect": "deploy",
 "previous_sha": "c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5",
 "previous_version": "2.58.203",
 "release_branch": "release/vmq-onto-01-2.58.204",
 "schema": 1, "version": "2.58.204"}
```

## 4. Restart / health

```
systemctl restart admin_bot   rc=0
poll 1,2                     пусто (процесс стартует)
poll 3                       200 {"status":"ok","version":"2.58.204"}
health public                200 {"status":"ok","version":"2.58.204"}
health local (повтор)        200 {"status":"ok","version":"2.58.204"}
/api/health                  200 {"status":"ok"}
unit                         active/running, MainPID 991458, NRestarts 0,
                             ExecMainStatus 0, start 2026-11-15 03:00:16 UTC
```

## 5. Schema / журнал

```
user_version        47
tables              130
schema_migrations   rows 36, max_version 47
[ startup ]         [database] migrations: start | current user_version=47 | pending=[]
journal (с рестарта) 156 строк, TRACEBACK 0, ERROR 0, CRITICAL 0, WARNING 1,
                     database is locked 0
```

Единственный WARNING — известный pre-existing класс `services.summary_memory`:
`embedding generation not serviceable | index=smart_archive | status=superseded |
FTS-only (A06) | build pending — source empty (nothing to vectorize)`. Он же
наблюдался до релиза; к VMQ-дельтам не относится.

Повторная read-only сверка через ~7 минут после e2e: журнал того же
процесса — 0 новых строк (MainPID 991458, NRestarts 0, health 200/2.58.204).

## 6. Identity

`services.deploy_identity.collect_identity(APP, process_started_at=03:00:16Z)`:

```
code                 verified_deployed
deployed_sha        2b419aa2627f627eb6ea5e2f46b5e01118da2bf0
checkout_sha        2b419aa2627f627eb6ea5e2f46b5e01118da2bf0
dirty                false
version_provenance   runtime=2.58.204, manifest=2.58.204, consistent=true
previous             c97c06e4 / 2.58.203
upstream_head        refs/remotes/origin/release/vmq-onto-01-2.58.204 =
                     2b419aa2, observed 03:00:13.947401Z
sources              release_manifest, git_head, git_cli,
                     runtime_app_version, process_start
conflict             []
```

## 7. Effective config / сохранность

Pre == post (см. `state-pre.json` / `state-post.json`):

- `bot_settings`: count **548**, digest **e98edf0ec3ea95d1…** — без изменений;
  все 6 контролируемых ключей (`flags.budgets_enabled`,
  `flags.factcheck_pipeline_v2`, `models.llm_model_name`,
  `models.llm_base_url`, `prompts.checkup_system_prompt`,
  `prompts.factcheck_subject_system_prompt`) идентичны.
- `chat_profiles`: count **3**, digest **323a6528d0c6cee5…**; owner-редакция
  чекапа сохранена: `rev:d31300ef35a0`, 12 469 симв., sha256 `31d17506…`,
  `retired=false`. Промпт-журнал не получил новых ревизий; активации без
  изменения тел (последние: 2945 `deploy_activate/skipped_same/
  factory_superseded_manual` — сохранённая ручная редакция не перетёрта).
- Бюджеты: **OFF** глобально и во всех 3 чатах (2 чата — явный chat-override,
  как и до релиза); chain limits `max_total=0 max_metered=0 max_same=0
  fuse=0.0`, `limits_enforced=false`.
- MCA caps/fuse: 0/0/0/0; capacity: **1 048 576 / 32 768**,
  `provider_catalog` / `verified`, модель `z-ai/glm-5.3-flash-uncensored`
  (chat model). Всё pre == post.
- Каталог параметров/флаги поезд не менял (645→645 по сборке); новых
  флагов/настроек/промптов/моделей/агентов/планировщиков нет.

## 8. Postdeploy read-only e2e (M-04 / O-04 wait)

Метод: deployed checkout `2b419aa2` исполняется in-process на **копии**
проверенного pre-deploy бэкапа (`/root/vmq204/measure/e2e.db`, 2 087 057
сообщений, 201 эпизод, schema 47, integrity ok); живые данные не пишутся,
сообщения в Telegram не отправляются, chat completion не вызывается.
Это read-only агентский e2e на выложенном коде, **не** работающий
systemd-процесс (это ограничение записано честно). Sanitised результат —
`postdeploy-e2e.json` (32 проверки, 0 failed); сырой серверный файл
содержит текст и в репозиторий не кладётся.

Ключевые наблюдения:

- **Exact owner query** «напиши юмористический рассказ об основных шизах
  конфы»: один overview-несущий `retrieve(include_overview=True)` (первый
  результат — тот же `RetrievalResult`), затем документированная pre-existing
  period-нога того же маршрута (`include_overview=False`); **один
  EvidenceBundle**, в нём coverage 2023:83 / 2024:92 / 2025:9 / 2026:16,
  independent_periods `[2023,2024,2025,2026]`, 5 counterexamples, 8
  limitations (`repeated_claims_present`, `episode_source_integrity_partial`,
  `episodes_stale` и др.), 20 episode refs, 10 semantic hints,
  `context_version` bundle присутствует. Покрытие совпадает с независимым
  SQL-окном эпизодов; чужих (другой чат) refs нет.
- **Temporal query** «из-за чего мы ссорились и ругались в 2023 году»:
  period_fill 1 строка, причина `in_target_year`, год 2023; overview/bundle
  с coverage/limitations; маршрут тот же (overview + period-нога).
- **Person-overview (tool `get_user_context`)**: `biography` — 1 `retrieve`,
  `include_overview=True`; envelope: 11 фактов, 5 строк coverage,
  independent_periods 4, 9 limitations, 5 counterexamples, subject_material;
  `general` — 1 retrieve, overview, 8 фактов; `identity` — 1 retrieve,
  `include_overview=False`, overview отсутствует (честный negative).
  Ни одного `generate`; максимум один embedding-вызов внутри единственного
  retrieve; второго маршрута/поиска/БД/LLM нет.
- **Current-state negative** «что сейчас происходит с E1?»: overview нет,
  `include_overview` ни разу не true, period_fill 0, intent `none`,
  episode reads 0 — исторический overview не протекает.
- **Corrections/versions (O-04)**: overview отдаёт `episode_versions` для 20
  эпизодов; пересчёт `episode_source_fingerprint` по фактическим
  `smart_messages.current_revision` копии совпадает с проекцией у всех 20
  (`all_fingerprints_match=true`), integrity ok, stale 0. В копии 1 438
  сообщений с revision>1 (по чату), но ни одно из них не входит в
  source-refs сэмплированных эпизодов — фактический «post-correction»
  переход на живых данных не наблюдался; это ограничение данных, не
  противоречие трассы (версионный механизм проверен тестами/мутацией
  Reviewer'а).

Честные ограничения: e2e не прогоняет production L1-план/рантайм-процесс
(план не эмулируется), один чат/один прогон, векторная нога в этом прогоне
была активна (`vec ok`), тогда как в pre-deploy corpus-замере она была
недоступна — поэтому состав строк pre-plan Writer-блока для current-state
отличается от того замера (7×2026 + 3 старых `history_import` строки).
Это наблюдение по-прежнему **открытого** memory-эпика (MEM/TIME), не
блокер M-04/O-04 wait: исторического overview/period-fill в negative-кейсе
нет.

## 9. Rollback

Target: **`c97c06e4` / 2.58.203** (ветка `release/smart-corrective-01`,
локальная и в origin; manifest previous_sha уже указывает на неё).
Схема 47 и данные не меняются (DDL 0, миграций нет), поэтому откат —
code-only:

```
cd /var/www/admin_bot
git switch release/smart-corrective-01
git merge --ff-only c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
venv/bin/python tools/release_manifest.py --effect rollback --deployer devops
sudo systemctl restart admin_bot
# health 200 / 2.58.203, schema 47, identity verified_deployed
```

Restore-point БД: `backups/pre_deploy_258204_20261115T025835Z.db`
(integrity ok, v47). Деплой rollback не потребовал.

## 10. Границы

- Карта требований и статусы **не менялись**: M-04/O-04 остаются
  `READY_FOR_LIVE` до binding'а PM/Reviewer; M-05 и memory-строки не
  закрывались. Memory-эпик остаётся открытым (MEM-04/TIME-01/02/04/06/07 и
  др.) и этим релизом не объявляется исправленным.
- Живых сообщений в чаты не отправлялось; e2e — read-only по копии БД.
- Код после ревью не менялся; деплой — ровно `2b419aa2`.
- Известный docs-gap поезда (Slice C evidence trio на `8bc2bcf7`, не в
  замороженной композиции `16931216`) остаётся bookkeeping-фактом PM; tip
  поезда из-за docs не пересобирался.

## 11. Evidence

- `delta-review-r1.md` — допуск (sha256 `4BAC1DE3…`).
- `deploy-run.log` — фактическая трасса команд (IDENT-строки с текстом
  оверрайдов вырезаны).
- `verify204.json` — 44 проверки, 0 failed (health/identity/schema/
  сохранность/эффективная конфигурация/e2e).
- `state-pre.json`, `state-post.json`, `identity.json`,
  `journal-summary.txt`, `manifest-after.json`.
- `postdeploy-e2e.json` — sanitised e2e (32 проверки, 0 failed),
  `correction_effect`, coverage/route/version трассы.
- `harness/` — скрипты e2e и их sha256 (`provenance.json`); `probe_slice_c.py`
  байт-идентичен уже закоммиченному harness-файлу.

## 12. Gate-состояние после выката (не «pass»)

`requirements_gate.py` на точном выложенном SHA **не может** дать
формальный release/delivery pass, пока карта привязана к `c97c06e4`, а
M-04/O-04 остаются `READY_FOR_LIVE` без binding'а. Фактические выводы
сохранены как есть:

- `gate-release-attempt.txt`: `stage=release` — `candidate mismatch`,
  V-01..V-04 REVIEW, M-04/O-04 READY_FOR_LIVE, M-05 REVIEW, O-01..O-03
  REVIEW, memory/Q/I строки PENDING; exit 1.
- `gate-delivery-attempt.txt`: `engineering_delivery=FAIL`,
  `acceptance=RUN_RELEASE_GATE`, `deferred_req_ids=[]`; exit 1.

Это **не** провал деплоя и не повод откатывать: health/identity/schema/
сохранность/e2e зелёные. Это недостающий bookkeeping-шаг PM: привязать
top-level candidate/deployed к `2b419aa2`, перенести M-04/O-04 (и O-01/
O-02/O-03 после выката) на evidence из этого каталога и только затем
повторить release/delivery gate. DevOps статусы не менял.

