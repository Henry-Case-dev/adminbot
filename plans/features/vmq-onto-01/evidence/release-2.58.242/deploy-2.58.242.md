# Deploy 2.58.242 — QRNG IBM P5A+P5B (первый live-выход)

- **Роль:** DevOps (subagent). Хост `192.255.209.205` (`vps159032-gqg`),
  checkout `/var/www/admin_bot`, unit `admin_bot` (user `adminbot`).
- **Окно:** `2026-11-24T13:58:21Z` (recon) — `2026-11-24T14:13:52Z` (финальные проверки).
- **Авторизация:** независимое delta-ревью `delta-review-r1.md`
  sha256 `58e82e71bed89537b25c69523ab22d486d657f8f153771b0ad9b10e471ca2576` =
  **`APPROVED_FOR_DEPLOY`**, candidate/tip `ff226ca0a`, blocking findings **0**,
  non-blocking `DR-242-N01..N04` (backlog/live-watch), rows `QAN-REC-IBM-01..03` — **REVIEW**.
- **Итог:** **DEPLOY OK**. Выложен ровно `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e`
  (detached, tree `b2205b58696b98e8a03fd6f2545fa35a3d9ce9d7`), product-дерево =
  `dfa5118fd` (`703e0651…`), версия **2.58.242**. Rollback — code-only `3f42cfdd1`.
- **Режим:** code-only. DDL 0 (схема побайтно равна pre-deploy backup), миграций 0,
  флагов 0, данных не мигрировали. `requirements.txt` + `qiskit-ibm-runtime==0.52.1`
  установлен в venv (ленивый импорт).
- **SSH (fail2ban-дисциплина):** 4 одиночных подключения без ретраев:
  `13:58` (recon, read-only), `14:02` (backup+deploy+restart), `14:09`
  (postdeploy + pip + функциональные пробы), `14:13` (hot-cache QRNG, финальный
  restart, финальные проверки). Ни одного auth-фейла.

```json
{
  "release": "2.58.242",
  "slice": "QRNG-IBM-P5A-P5B",
  "deploy_mode": "code-only",
  "authorization": {"delta_review_sha256": "58e82e71bed89537b25c69523ab22d486d657f8f153771b0ad9b10e471ca2576",
                    "verdict": "APPROVED_FOR_DEPLOY", "blocking_findings": 0},
  "deployed": {
    "sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
    "tree_expected": "b2205b58696b98e8a03fd6f2545fa35a3d9ce9d7",
    "tree_actual": "b2205b58696b98e8a03fd6f2545fa35a3d9ce9d7",
    "product_tree": "703e0651802b80a5d9da0929d8b6be6d0a830a8e (dfa5118fd)",
    "checkout_mode": "detached", "dirty_tracked": 0, "version": "2.58.242",
    "base_rollback_sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
    "base_version": "2.58.241",
    "manifest": {"deployed_at": "2026-11-24T14:07:50.621741Z",
                 "previous_sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
                 "previous_version": "2.58.241", "dirty_tracked": false, "effect": "deploy"},
    "manifest_before": {"deployed_sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
                        "version": "2.58.241",
                        "previous_sha": "f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9",
                        "previous_version": "2.58.240"},
    "restart1_at": "2026-11-24T14:07:52Z", "restart2_at": "2026-11-24T14:13:46Z",
    "main_pid": 3878026
  },
  "delta": {"files": 103, "product_and_deps": 100, "docs": 3, "web": 3,
            "migrations": 0, "services_database_py": 0, "services_pg_db_py": 0,
            "services_mca_gates_py": 0, "new_flags": 0},
  "preflight": {"head": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
                "tree": "853dd3b471034fb297753604d98367ed208dbf6f",
                "dirty_tracked": 0, "dirty_untracked": 0,
                "health": {"local": "2.58.241", "public": "2.58.241"},
                "service": {"active": "active", "nrestarts": 0, "main_pid": 3849390,
                            "exec_start": "2026-11-24T12:03:23Z", "procs": 1},
                "db_bytes": 5915566080, "disk_avail_bytes": 54603825152,
                "target_sha_present": false},
  "backup": {"path": "backups/predeploy-258242-20261124T140248Z.db",
             "bytes": 5642412032,
             "sha256": "5a11a4484cddebb257b113d42cf80d56b9b665e9d3ebd7c1264a66c45132b8f1",
             "quick_check": "ok", "user_version": 48, "tables": 130,
             "schema_migrations": "37/48", "graph_facts": 39839,
             "schema_sha": "be483ef187887deb", "mode": "vacuum_into_readonly",
             "elapsed_s": 188.0, "owner_mode": "adminbot:adminbot 600"},
  "dependencies": {"qiskit-ibm-runtime": "0.52.1", "qiskit": "2.6.2",
                   "numpy": "2.5.5", "scipy": "1.18.1",
                   "ibm-platform-services": "0.77.2",
                   "pip_check": "No broken requirements found",
                   "import_smoke": "OK (numpy/scipy/qiskit/qiskit_ibm_runtime + app modules)"},
  "post": {"health": {"local": "2.58.242", "public": "2.58.242", "http": 200},
           "service": {"active": "active", "nrestarts": 0, "main_pid": 3878026,
                       "exec_start": "2026-11-24T14:13:46Z", "procs": 1,
                       "health_after_restart_s": 5},
           "identity": {"code": "verified_deployed", "reason": "",
                        "deployed_sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
                        "checkout_sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
                        "version_provenance": {"runtime": "2.58.242",
                                               "manifest": "2.58.242", "consistent": true},
                        "dirty": false, "conflict": [],
                        "sources": ["release_manifest", "git_head", "git_cli",
                                    "runtime_app_version", "process_start"]},
           "sqlite": {"user_version": 48, "tables": 130, "schema_migrations": "37/48",
                      "schema_sha": "be483ef187887deb", "ddl": 0,
                      "ddl_schema_identical_to_backup": true,
                      "graph_facts": 39839, "graph_facts_vec": 39952},
           "served": {"app_js_bytes": 2676044,
                      "app_js_sha256": "52be44385c3fcddffa8f8c44c67555a6080dec8fe87a7972d58e536c264ae809",
                      "disk_eq_local_eq_public": true,
                      "index_pins": "app.css?v=2.58.242, app.js?v=2.58.242",
                      "web_root": 200, "root_slash": 307, "api_config_unauth": 401},
           "journal": {"restart1_window": {"lines": 244, "error": 0, "critical": 0,
                                           "traceback": 0, "exception": 0},
                       "final_window": {"lines": 165, "error": 0, "critical": 0,
                                        "traceback": 0, "exception": 0},
                       "baseline_24h": {"lines": 80858, "error": 7, "critical": 0,
                                        "traceback": 23,
                                        "source": "anticliche_worker wikipedia fetch; aiogram TelegramNetworkError (pre-existing)"}}},
  "qrng_p5": {
    "registry": {
      "ibm_quantum": {"configured": false, "state": "provider_unconfigured",
                      "reserve": 0, "key_present": false, "crn_present": false,
                      "dependency": true, "max_inflight": 1,
                      "max_jobs_per_day": 4, "max_qpu_seconds_per_day": 120,
                      "jobs": []},
      "anu": {"configured": true, "state": "active", "reserve_before_draw": 1127,
              "reserve_after_draw": 1126, "quarantined": 0, "config_matches": true},
      "lfdr": {"configured": true, "state": "unverified", "reserve": 1023,
               "quarantined": 0, "config_matches": true}},
    "effective": {"selected_source": "quantum", "effective_source": "quantum",
                  "resolved_primary": "anu", "effective_provider": "anu",
                  "reserve_remaining": 2150, "reserve_after_draw": 2149,
                  "low_watermark": 256, "buffer_max": 2048,
                  "prng_active": false, "last_fallback_reason": null},
    "draws": {"quantum_before_draw": 5351, "quantum_after_draw": 5352,
              "pseudorandom": 44,
              "continuity": "quantum 5348@14:02:48 -> 5349@14:09:30 (real process draw through deploy window)"},
    "live_draw": {"index": 1, "value": 289, "source": "quantum",
                  "selected_source": "quantum", "reason": null,
                  "policy_version": "mca10a-v1", "provider": "anu"},
    "fallback_counters": {"auth_failed": 0, "quota": 0, "transport": 0,
                          "error_storm": false},
    "ibm_jobs_scheduled": {"task_jobs_kind_random.ibm_job_all_time": 0,
                           "mca_random_batches_provider_ibm_all_time": 0,
                           "snapshot": []},
    "n04": "inert: refill trigger requires configured IBM; no IBM job/slot created"},
  "secrets": {"journal_crn_v1": 0, "journal_apikey": 0, "journal_long_hex40": 0,
              "appjs_crn_v1": 0, "appjs_env_name": 0, "index_crn_v1": 0,
              "auth_errors": "401 missing init data, no secret material"},
  "auth_boundary": {"GET /api/config": 401, "GET /api/status": 401,
                    "GET /api/config/keys/status": 401, "POST /api/config": 401,
                    "POST /api/random/test": 401, "POST /api/random/ibm/smoke": 401},
  "settings_preserved": {"pg_tables": 10, "pg_rows": 1695,
                          "digest_before": "ee883756cef955c84ced325890d1302bd8c1fd132a9d0ae8872f8dc1a9ecf6a5",
                          "digest_after": "ee883756cef955c84ced325890d1302bd8c1fd132a9d0ae8872f8dc1a9ecf6a5",
                          "match": true},
  "disk": {"avail_before": 54603825152, "avail_after_backup": 48961576960,
           "cleanup_deleted": "predeploy-258240-20261124T093140Z.db",
           "cleanup_freed_bytes": 5585489920, "deploy_pool_keep": 2,
           "deploy_pool_remaining": ["predeploy-258241-20261124T115812Z.db",
                                     "predeploy-258242-20261124T140248Z.db"],
           "avail_final": 54222434304, "partial_files": 0, "own_temp_files": 0},
  "deviations": [
    "pip install -r requirements.txt first ran before checkout (old requirements, no qiskit, rc=0); installed at deployed checkout afterwards and a second manual restart (14:13:46Z) aligned the running process with the final dependency set",
    "first QRNG sidecar read lacked ConfigCache (under-reported ANU key/quarantine); authoritative values re-read with read-only ConfigCache _load_all",
    "sidecar forced refill fetched one LfDr batch 7433344c (1024 values, 1 consumed by probe) — real extra reserve, harmless, documented",
    "backup verification connection lacked sqlite_vec, so graph_facts_vec count taken from live DB (39952)"
  ],
  "not_verified": ["IBM IAM/CRN/QPU/queue/usage/RU and hardware smoke (no credentials; owner-only)",
                   "authenticated HTTP /api/config и /api/random/* (TMA session not minted)",
                   "new browser/visual run on rebased tree (reused P5B r3 per delta review)"],
  "rows": {"QAN-REC-IBM-01": "REVIEW", "QAN-REC-IBM-02": "REVIEW",
           "QAN-REC-IBM-03": "REVIEW"},
  "hardware_verified_claim": false,
  "rollback": {"executed": false, "code_only_sha": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
               "ddl": 0, "migrations": 0, "flags": 0, "data_migration": false},
  "verdict": "DEPLOY_OK"
}
```

## 1. Preflight (`13:58Z`, read-only)

| Проверка | Значение |
|---|---|
| HEAD / tree / branch | `3f42cfdd1…` / `853dd3b4…` / `detached` |
| tracked / untracked dirty | 0 / 0 |
| unit | `active/running`, `NRestarts=0`, MainPID `3849390`, exec start `12:03:23Z`, 1 процесс |
| `/healthz` local + public | 200 `2.58.241` / 200 `2.58.241` |
| SQLite | `user_version=48`, 130 таблиц, миграции 37/max 48 |
| БД / диск | 5 915 566 080 B; avail `54 603 825 152 B` |
| `.deploy/release.json` (до) | `deployed_sha=3f42cfdd1` (2.58.241), `previous_sha=f7e20e15d` (2.58.240) — штатное поле «предыдущий релиз» |
| target SHA | на хосте отсутствовал → `git fetch --prune origin` подтянул `release/qrng-ibm-p5b-2.58.242` |
| backups до | deploy-пул 2 (`predeploy-258240`, `predeploy-258241`), daily `local_database_20261124.db` |

## 2. Pre-deploy backup

| Параметр | Значение |
|---|---|
| Путь | `backups/predeploy-258242-20261124T140248Z.db` |
| Байты | **5 642 412 032** |
| sha256 | `5a11a4484cddebb257b113d42cf80d56b9b665e9d3ebd7c1264a66c45132b8f1` |
| Integrity | `quick_check=ok`, `user_version=48`, 130 таблиц, миграции 37/48, `graph_facts=39839` |
| Схема | `schema_sha=be483ef187887deb` (критерий DDL 0) |
| Владелец/режим | `adminbot:adminbot 600` |
| Метод | `VACUUM INTO` из read-only подключения, `.partial` → rename после успеха; **188.0 с** |

`graph_facts_vec` в этой сессии проверить не удалось (в проверочном подключении не был
загружен `sqlite_vec`); живой счётчик снят после деплоя: **39 952**.

## 3. Выкладка

| Шаг | Результат |
|---|---|
| `git fetch --prune origin` | rc=0; появилась `release/qrng-ibm-p5b-2.58.242` |
| `git cat-file -t ff226ca` | `commit` |
| `pip install -r requirements.txt` (первый прогон до checkout) | rc=0, но старый requirements (без qiskit) → **no-op**; см. §8 |
| `git checkout --detach ff226ca` | rc=0; HEAD=`ff226ca`, tree=`b2205b58…` == ожидаемое |
| tracked dirty после checkout | 0 |
| `APP_VERSION` | `2.58.242` |
| Дельта `3f42cfdd1..HEAD` | **103** файла; `web/` 3; `migrations/` 0; `services/database.py` 0; `services/pg_db.py` 0; `services/mca_gates.py` 0 |
| `web/app.js` | 2 676 044 B |
| `tools/release_manifest.py --effect deploy` | rc=0, `deployed_at=14:07:50.621741Z` |
| `systemctl restart admin_bot` | rc=0 |
| health | 200 `2.58.242` с 6-й секунды |

## 4. Post-deploy: базовые проверки

| Проверка | Результат |
|---|---|
| `/healthz` local / public | 200 `2.58.242` / 200 `2.58.242` |
| Service | `active`, **`NRestarts=0`**, MainPID `3878026`, exec start `14:13:46Z`, **1** процесс |
| Identity | `code=verified_deployed`, `reason=""`, `deployed_sha == checkout_sha == ff226ca…`, `runtime=manifest=2.58.242`, `consistent=true`, `dirty=false`, `conflict=[]` |
| SQLite | `user_version=48`, 130 таблиц, миграции 37/48, `schema_sha=be483ef187887deb` == backup → **DDL 0** |
| Journal (restart1 → restart2) | 244 строки; **0 ERROR, 0 CRITICAL, 0 Traceback, 0 Exception** |
| Journal (final, после `14:13:46Z`) | 165 строк; **0 ERROR, 0 CRITICAL, 0 Traceback** |
| `/web/app.js` | 2 676 044 B, sha256 `52be4438…ae809` — **disk == local == public** (public снят до 2-го рестарта, статика не менялась) |
| `/web/index.html` | `app.css?v=2.58.242`, `app.js?v=2.58.242` |
| `/web/` / `/` | 200 / 307 |
| `/api/config` без auth | **401** `{"detail":"missing init data"}` |

24-часовой baseline до деплоя — 7 ERROR / 23 Traceback, источник pre-existing:
`services.anticliche_worker` (Wikipedia fetch/refresh) и `aiogram`
`TelegramNetworkError`; в окнах деплоя новых нет.

## 5. Release-specific: QRNG IBM P5A+P5B (blocking)

Источник — production-путь `RandomSourceService.status_snapshot()` в отдельном
процессе на deployed SHA с **read-only `ConfigCache._load_all()`** (без DDL/сидов),
тот же hot-слой, что у бота. Значения ключей не выбирались.

### 5.1 Реестр провайдеров

| Провайдер | configured | state | reserve | quarantined | детали |
|---|---|---|---|---|---|
| `ibm_quantum` | **false** | **provider_unconfigured** | 0 | 0 | `key_present=false`, `crn_present=false`, `dependency=true`, `max_inflight=1`, jobs/day 4, QPU 120 c |
| `anu` | true | **active** | **1127 → 1126** (после live-draw) | 0 | `config_matches=true`, ключ есть (len 40, значение не выводилось) |
| `lfdr` | true | unverified | **1023** | 0 | `config_matches=true`; партия получена реальным refill (§8) |

`effective_source=quantum`, `resolved_primary=anu`, `effective_provider=anu`,
`reserve_remaining=2150 → 2149`, `low_watermark=256`, `prng_active=false`,
`last_fallback_reason=null`.

### 5.2 Живой draw и непрерывность

| Проверка | Результат |
|---|---|
| Draw через production-путь | `draw_index(2)` → **index 1, value 289, source quantum, reason null, policy mca10a-v1** |
| Reserve до/после | 2150 → **2149** (ANU 1127 → 1126) |
| `draws` quantum | 5351 → **5352** (+1, ровно проверочный; pseudorandom 44 без изменений) |
| Непрерывность через окно деплоя | quantum-счётчик `5348` (`14:02:48`) → `5349` (`14:09:30`) — реальный процесс бота сделал квантовый draw через рестарт; простоев нет |
| Startup после рестарта | `[random_source] startup {'status':'ok','remaining':1127,'provider':'anu'}` |

### 5.3 Fallback / IBM inert (N04)

- `auth_failed=0`, quota-ошибок `0`, transport-ошибок `0`, error storm нет
  (journal чистый); IBM `last_error=null`.
- IBM не блокирует draws: при неконфигурированном IBM триггер refill не
  срабатывает (`_maybe_schedule_refill` возвращается до планирования);
  `task_jobs kind='random.ibm_job'` — **0 за всё время**, `mca_random_batches
  provider='ibm_quantum'` — **0**, `ibm_jobs=[]`. Слот `job_max_age` не занят.

### 5.4 Админ-поверхность

| Проверка | Результат |
|---|---|
| `randomIbmCheck` в served `app.js` | **18** вхождений |
| `keys.random_ibm_api_key` / `keys.random_ibm_crn` | **5** / **5** |
| `randomIbmSmoke` / `QRNG_PROVIDERS` | 18 / 18 |
| `GET /api/config`, `GET /api/status`, `GET /api/config/keys/status` | **401** |
| `POST /api/config`, `POST /api/random/test`, `POST /api/random/ibm/smoke` | **401** |
| Raw secret в ответах | нет (`missing init data`) |

### 5.5 Секреты

| Поиск | Результат |
|---|---|
| journal (оба окна) `crn:v1:` / `apikey` / `RANDOM_IBM_API_KEY` / hex≥40 | **0 / 0 / 0 / 0** |
| served `app.js` `crn:v1:` / `RANDOM_IBM_API_KEY` | **0 / 0** |
| served `index.html` `crn:v1:` | **0** |

## 6. Сохранность настроек/профилей/промптов

Read-only digest PostgreSQL по тем же 10 таблицам (1 695 строк):

```
PG_DIGEST_BEFORE=ee883756cef955c84ced325890d1302bd8c1fd132a9d0ae8872f8dc1a9ecf6a5
PG_DIGEST_AFTER =ee883756cef955c84ced325890d1302bd8c1fd132a9d0ae8872f8dc1a9ecf6a5
MATCH=YES   PG_ROWS=1695 (== до)
```

Схема SQLite и данные не мигрировали; `schema_sha` live == backup.

## 7. Диск / retention (P0-PROD-DISK-01)

| Шаг | Результат |
|---|---|
| `manage.py disk audit` | deploy_backup 3 (15.6 GiB), db_backup 1 (5.0 GiB), facts 1, jsonl 5, other 6; total 15.5 GiB |
| `manage.py disk cleanup --apply` (deploy keep=2) | `deleted=1 bytes_freed=5 585 489 920` — `predeploy-258240-…db` |
| Deploy-пул после | `predeploy-258241-…db` + `predeploy-258242-…db` (keep=2) |
| Свободно | `54 603 825 152` → (backup) `48 961 576 960` → (cleanup) **`54 222 434 304 B` (46% used)** |
| Свои temp/partial | `0`, `0`; `/tmp/_*` — 0 |

Оставлено для отката: `predeploy-258242-…db` (sha256 §2) + `predeploy-258241-…db`.

## 8. Отклонения и их устранение (честно)

1. **Порядок pip.** `pip install -r requirements.txt` первый раз выполнился до
   checkout, т.е. по requirements 2.58.241 (без qiskit) — rc=0, no-op. После
   checkout установлены зависимости deployed-дерева: `qiskit-ibm-runtime 0.52.1`,
   `qiskit 2.6.2`, `numpy 2.5.5`, `scipy 1.18.1`, `ibm-platform-services 0.77.2`;
   `pip check` — чисто; import-smoke (numpy/scipy/qiskit + app-модули) — OK.
   Затем выполнен **второй ручной рестарт** (`14:13:46Z`), чтобы рабочий процесс
   соответствовал финальному набору зависимостей. `NRestarts` остаётся 0.
2. **Некорректный первый QRNG-снимок.** В postdeploy-сессии sidecar не имел
   `ConfigCache`, поэтому видел ANU как unconfigured, а партию 1128 — как
   quarantined. Авторитетные значения перечитаны с read-only
   `ConfigCache._load_all()` (final-сессия, §5). На деплой это не влияло.
3. **Побочный LfDr-батч.** В ходе исправленной проверки sidecar выполнил
   реальный `refill_if_needed(force=True)` без hot-ключа → одна LfDr-партия
   `7433344c…` (1024 значения, 1 израсходовано пробой). Это дополнительный
   валидный резерв, не дефект; данные не повреждены.
4. **Backup-верификация** не смогла посчитать `graph_facts_vec` (нет
   `sqlite_vec` в том подключении) — живой счётчик 39 952 снят отдельно.

## 9. Что не проверено / ограничения

1. **Hardware VERIFIED не заявляется.** Реальные IBM IAM/instance/CRN/QPU/queue/
   usage/RU, measurement bits и hardware smoke не проверялись — нет credentials
   (единственный owner-only шаг: ввести API key + CRN в админке).
   `QAN-REC-IBM-01..03` остаются **REVIEW**.
2. Аутентифицированные HTTP-пути (`/api/config` запись, `/api/random/*`) не
   вызывались — нужна валидная TMA-сессия; граница auth проверена 401, а
   функциональность QRNG — тем же production-сервисом in-process с реальным
   hot-конфигом.
3. Визуальный гейт на rebased-дереве повторно не исполнялся: по delta-ревью
   переиспользовано доказательство P5B r3 (добавленные UI-строки идентичны);
   серверные маркеры IBM-карточки и пины версии проверены на served bundle.
4. `requirements_gate release` не запускался: строки остаются REVIEW по
   `live_required=postdeploy`; деплой выполнен по независимому
   `APPROVED_FOR_DEPLOY` и мандату Orchestrator.

## 10. Rollback

Code-only: `git checkout --detach 3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c`
(2.58.241) + `systemctl restart admin_bot`; manifest `--effect rollback`.
DDL 0, миграций 0, флагов 0, данных не мигрировали; схема остаётся 48.
Установленные qiskit-пакеты кодом 2.58.241 не используются (можно оставить).
Rollback-копия — `predeploy-258242-20261124T140248Z.db` (sha256 §2). Не выполнялся.

## 11. Воспроизводимость (без секретов)

- Preflight/backup/deploy: `ssh -i <key> root@192.255.209.205 'bash -s'` —
  `VACUUM INTO` из `mode=ro`, `git fetch --prune origin`,
  `git checkout --detach <sha>`, `pip install -r requirements.txt`,
  `tools/release_manifest.py --effect deploy`, `systemctl restart admin_bot`.
- Функциональные проверки: `runuser -u adminbot -- env HOME=/home/adminbot
  ./venv/bin/python -` (код на stdin), cwd `/var/www/admin_bot`:
  `config.settings`, `services.database`, `services.config_cache`
  (`_load_all`, read-only), `services.hot_config`, `services.mca_random_source`.
- PG digest: `asyncpg` read-only SELECT по 10 таблицам.
- SQLite: `file:…?mode=ro` + `sqlite_vec.loadable_path()`.
