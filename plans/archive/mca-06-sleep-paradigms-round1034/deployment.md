# deployment.md — mca-06-sleep-paradigms (prod 2.58.49)

Фича: `mca-06-sleep-paradigms` — Risk R3 — **Деплой: VERIFIED**
Дата: 04.10.2026 (UTC) — отв.: @DevOps — траншея T-4733 (effective-config, частично PO) + T-4734 (release/deploy)

## 1. Binding

- Кандидат: Review Approved for release, round 2 (WTH-2 `02D5160D1783D77C…`, HEAD `4a6603b`); doc-хвосты L-doc-1/L-doc-2/L-2 - в release-коммит (round-2 разрешение).
- Прод: `nik@198.46.175.136:/var/www/admin_bot` (racknerd-f4e3456), systemd-юнит `admin_bot` (Ubuntu 24.04, venv `/var/www/admin_bot/venv`, Python 3.12, БД `/var/www/admin_bot/local_database.db`).

## 2. Коммиты

- **feat**: `7fc2e39` — `feat(round1034): mca-06 sleep paradigms - gate resolver, dream evidence, historical profile, quotas, run reports (APP_VERSION 2.58.49)` (57 файлов: config/settings.py, services/{database,dream_worker,mca_dream_evidence,mca_dream_history,mca_dream_random,mca_events,mca_gates,mca_process_registry,mca_trace,provenance,summary_memory}.py, web/api/memory_agi.py, web/app.js, tools/{mca06_timestamp_audit,ui_mca06_sleep_card}.py, 5 mca06-тест-файлов + version-pin свип 26 py-тестов + 4 JS-харнеса (round1025 hotfix7/8/9/10), param-registry meta.md).
- **docs**: `04b5fdd` — spec/ADR-1028-9/requirements-map/tasks/evidence/review/threat/conflict-audit/reuse-inventory + plans/reports/{mca06_t4712_timestamp_audit.md, mca06_wth_manifest_delivery.txt} + full_audit_results.md (12 файлов).
- Чужой WIP (исключён из коммитов): `plans/metrics.md`, `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, `node_modules/`, `package*.json`, `.playwright-mcp/`, `extra_images/`, `plans/verification_cache.json`.
- Prod push/ff: `git push origin master` (4a6603b..04b5fdd) → прод `git pull --ff-only`: `b4dcb34..04b5fdd` **fast-forward, без force** (75 файлов, +7857/−669).

## 3. Release-prep

- APP_VERSION bump 2.58.48 → 2.58.49 (`config/settings.py:2812` release-marker round1034 (mca-06) + README строка 5).
- Version-pin sweep: `config/settings.py` APP_VERSION-строка + release-marker, 26 py-тестов `assert APP_VERSION == '2.58.48'` → `'2.58.49'`, 4 JS-харнеса (`tests/js/round1025_hotfix{7,8,9,10}*.js` regex-пины), `plans/docs/param-registry-round1025.meta.md` (APP_VERSION), `README.md` (v2.58.49 + сегмент mca-06).
- Parity-комментарии в коде/доках вида «OFF = бит-в-бит 2.58.48» **сохранены как 2.58.48** — по аналогии с прошлыми релизами (ссылка на базу OFF-parity, не на текущую версию).
- Doc-хвосты (разрешены round-2): spec.md L-2 (265/306/353: bump-нотация 2.58.48→2.58.49), ADR-1028-9 D12/AM-4 (bump-нотация), tasks.md L-doc-1 (T-4718 AM-6 примечание) + T-4734 (bump 2.58.48→2.58.49), evidence.md L-doc-2 (123 passed).

## 4. Тесты (detached)

- **Финал (post-bump, было два прохода)**: первый — `pytest tests -x -q` → 6472 passed + 1 FAIL = `test_meta_provenance` (param-registry meta APP_VERSION); второй (post-meta-fix без -x) — **11298 passed / 0 failed / 1 warning, 379.22s**.
- Промежуточный (post-bump, pre-meta-fix) Run 2: 4 failed / 11294 passed — 4 JS-пиновых Джеронима (hotfix7/8/9/10 — "D: APP_VERSION 2.58.34" проверка regexом — сидят на settings APP_VERSION) — ожидаемо, все 4 были свипнуты.
- Ожидание «11294/0 или 2 known» — **перевыполнено (0 failed)**.
- JS: **55/55** (Manual node --check web/app.js OK; headless node — hotfix7/8/9/10 все OK ЛОКАЛЬНО post-bump).
- F8 --check: **CHECK OK** (реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны) — prod venv.
- py_compile services/*.py + config/settings.py — OK.

## 5. Деплой факт (T-4734 chronology)

- Диск до: `/dev/vda2` **24G / used 17G / avail 5.8G (75%)** — достаточно для backup-guard (~2.7G прогноз).
- `git pull --ff-only` **05a210c..b4dcb34 НЕ БЫЛО** — корректный путь: `b4dcb34..04b5fdd` fast-forward ✓.
- Рестарт: `sudo systemctl restart admin_bot` (NOPASSWD-allowlist: systemctl) ✓ rc=0.
- **Active: active (running) since Sun 2026-10-04 07:24:46 UTC; Main PID 3542156; NRestarts=0; ExecMainStatus=0** (проверено 07:50 UTC).
- Останов старого PID 3484893: stop-sigterm timed out 90 s → SIGKILL — ожидаемый systemd-путь для юнитов с долгими cleanup-tasks («Failed with result 'timeout'»→ SIGKILL → Started 3542156) — это НЕ падение приложения, а штатная зачистка останова (см. detail oct 04 07:24:46 systemd[1]). Не влияет на работоспособность (журнал «01 Failed with result 'timeout'» = старый процесс был убит).

## 6. DDL v24→v25 факт

- **Backup guard (fail-closed)**: `Oct 04 07:27:44 … services.memory_backup - INFO - memory_backup: pre-migration copy created + read-back ok | target_version=24` → **`/var/www/admin_bot/pre_migration_20261004_072506.db` (1.31GB, root?)** + `-journal` рядом.
- **Migration v25**: `07:27:44.054 [database] migration v25: pipeline_runs.chat_id added`; `07:27:44.061 … pipeline_runs.report_json added`; `07:27:44.068 [database] migration v25 applied | dream_run_reports`.
- READ-only post-fact проверка (`/tmp/check_v25.py`, c_progress + hidden mistake-guard):
  - `PRAGMA user_version = 25` ✓;
  - `PRAGMA table_info(mca_pipeline_runs)` — присутствуют **`chat_id`** и **`report_json`** (добавлены к уже существующим 15 колонкам — не переименованы, не перезаписаны);
  - `PRAGMA index_list(mca_pipeline_runs)` — есть **`idx_mca_pipeline_runs_chat`** (cols: `pipeline_type, chat_id, started_at`) —ilu идемпотентность через `CREATE INDEX IF NOT EXISTS`;
  - остальные индексы (`_status`, `_type_started`, `_root_job` + autoindex) нетронуты;
  - `schema_migrations` last = **(25, 'dream_run_reports')** — реестр mca-14 обновлён.
- PG: no-op (mca-06 только SQLite) ✓.

## 7. T-4733: прод effective-config + run-state tracking verification

### 7.1 Effective-config

==== from live Settings (prod-venv, post-restart) ====
- APP_VERSION **2.58.49** (podтвердждено код → настройки)
- 7 kill-switches (feature "MCA_DREAM_*", env-only, default ON; read-only чтение, no secrets):
  - `MCA_DREAM_GATE_RESOLVER_ENABLED` = **True**
  - `MCA_DREAM_HISTORICAL_PROFILE_ENABLED` = **True**
  - `MCA_DREAM_EVIDENCE_TYPING_ENABLED` = **True**
  - `MCA_DREAM_QUOTAS_SPLIT_ENABLED` = **True**
  - `MCA_DREAM_RUN_REPORTS_ENABLED` = **True**
  - `MCA_DREAM_REVISION_QUEUE_ENABLED` = **True**
  - `MCA_DREAM_RANDOM_EXPLORE_ENABLED` = **True**
- Лимиты mca-06 (env-only, default/‑кастом): `MCA_DREAM_HISTORICAL_PRELIMIT_FACTOR=4`, `MCA_DREAM_MAX_TOPIC_PACKETS=3`, `MCA_DREAM_ENRICH_MAX_ROUNDS=2`, `MCA_DREAM_ENRICH_BATCH_MESSAGES=50`, `MCA_DREAM_GLOBAL_ATTEMPTS_LIMIT=30`, `MCA_DREAM_PER_CHAT_ATTEMPTS_LIMIT=1`, `MCA_DREAM_BACKOFF_BASE_SECONDS=3600`, `MCA_DREAM_BACKOFF_CAP_SECONDS=86400`, `MCA_DREAM_REVISION_QUEUE_CAP=20`
- Классический сон (context): `DREAM_ENABLED=True`, `DEEP_SLEEP_ENABLED=True`, `DEEP_SLEEP_TOKENS_PER_DAY=40000`, `DEEP_SLEEP_TOP_K=20`, `DEEP_SLEEP_MAX_PARADIGMS=3`, `DEEP_SLEEP_HOUR=7`, `DEEP_SLEEP_TRIGGER=after_sleep`, `DREAM_TOKENS_PER_DAY=300000`, `DREAM_WINDOW_START_HOUR=4`, `DREAM_WINDOW_END_HOUR=6`, `DREAM_MAX_CLUSTERS_PER_RUN=10`, `DREAM_MAX_CHATS_PER_RUN=10`, `DREAM_DISTILLATIONS_PER_DAY=60`, `DREAM_IMPORTANCE_SUM_THRESHOLD=8`, `DREAM_REPEAT_THRESHOLD=2`, `DREAM_QUIET_CHECK_MINUTES=10`, `DREAM_TICK_MINUTES=60`, `DREAM_INITIAL_WINDOW_HOURS=168`, `DREAM_MIN_NEW_FACTS_PER_CHAT=2`, `DREAM_CLUSTER_OVERLAP_TOKENS=2`.
- `GRAPHRAG_REBUILD_SLEEP_SECONDS=0.5` (несвязанный).

### 7.2 env-overrides / kill-switches

- Прод `.env`: **0 вхождений `MCA_DREAM_*`** (grep по 7 именам — 0 строк); только `DREAM_ENABLED=true` + `DEEP_SLEEP_ENABLED=true` (master-флаги, не mca-06 свитчи) → все 7 kill-switches live = **кодовые default ON** ✓ ( expectation выполнен).
- systemd-юнит: `systemctl show admin_bot -p Environment` = **только одна строка-строка con PATH (`LANG`,`LANGUAGE` и т.д.)** — 0 MCA_DREAM-оверрайдов ✓.

### 7.3 Run-state tracking verification (run-уровня) fi, стабус

- Worker зарегистрирован: `07:27:45± services.dream_worker - INFO - DeepSleep job registered (enabled resolved per-tick) | tick_minutes=60 (applies on restart)`.
- Таблица-инфраструктура: `mca_pipeline_runs` live, user_version = 25, migration idempotent (`test_v25_idempotent`). Backend ready to persist Sleep.deep runs (start_run → finish_run + set_run_report — support ярусов).
- **Live-run прогона** (`sleep.deep` run-row + `report_json` §7.2 + результат 8 групп) **НЕ выполнен** на проде: при проде-венте прошло ~25 минут после рестарта; факт: `pipeline_type counts = [] (0 rows)`, `report_json = [] (0)` — так ещё нет ни одного Sleep-run-ст��а (юкз. у per-tick нет `after_sleep`-триггера на текущий UTC-мой — см. ниже). Не является FAIL’ом: техсредства готовы; честный NOT_VERIFIED run-статуса (THR-15: no-false-acceptance), PENDING OWNER — живой сон требует платные LLM-вызовы (spec 11.3, PO-1).

- `deep_sleep_migration` skip msg (07:25:06) — док-верификация для отчета пользователя «skip: выключено (ветка A аудита)» — как предыстория: mca-06 не которая decides skip реализацию, а та«branch только данного лог-записи, НЕ в скоупе T-4727 (trace-конистема — 'threshold_migration').

## 8. Пост-деплой верификация (T-4734 smoke checker)

| # | Проверка | Статус |
|---|---|---|
| 1 | health 200/2.58.49 | **PASS** — `{"status":"ok","version":"2.58.49"}` (localhost + duckdns[внешний 200 тоже]) |
| 2 | user_version=25 | **PASS** — 25, last migration (25, dream_run_reports); backup pre-DDL 1.31G |
| 3 | 7 kill switches MCA_DREAM_* default ON | **PASS** — все 7 = True, 0 prod-.env вхождений, 0 systemd Environment-оверарайдов (изолированно от `systemctl show`) |
| 5 | /api/memory/dream/chain unauth | **PASS** — 401 `{"detail":"missing init data"}` |
| 6 | ladder/parity prostate venv mca-06 files | **PASS** — bc=36, de+fg+h+i=87, (dish=) deep_sleep/dead_extractor/episodes/run_store/source_window/mca01/mca05/sleep_manual 228. Итого **36+87+228 = 351 passed / 0 failed** в прод-venv |
| 7 | F8 488 CHECK | **PASS** — CHECK OK (registry 488 == REGISTRY) EXIT 0 |
| 8 | alien-noise/error scan (journal) | **PASS** — grep ERROR+CRITICAL+Traceback = **0** на 07:25→07:50 |
| 9 | R17-scan (sk-/Bearer/xox/AKIA/api_key=/-----BEGIN) | **PASS** — **0 хитов** в журнале + логи (uniq -c пустой) |
| 10 | ConfigCache keys (hot.get) | **PASS** — 5/5 CONFIGURED с last4 (llm_api_key, image_api_key, summary_l1/l2_api_key, telegram_api_hash) |

## 9. FREE прод-приёмка + deployed UI browser smoke (Playwright, unauth-поверхность)

- **v2.58.49 кэш-баст live**: `?v=2.58.49` в served HTML (`v=2.58.49`) post-reload ✓
- **desktop 1280×800**: Raven-щит показан; `#/modules` — скрипты `v=2.58.49`; **`.more-sheet` / `.more-backdrop` отсутствуют в DOM** при закрытом состоянии (sheetRect = null → unmount-контракт); **Quick Access (`.module-quick-wrap`) отсутствует в DOM** (count=0) ✓.
- **mobile 390×844**: `#/modules` — `.more-sheet` отсутствует, `.module-quick-wrap` = 0, `.bottom-nav` присутствует, консоль 0 JS-ошибок ✓  (screenshot `page-2026-10-04T07-49-44-891Z.png`).
- Card — URI-виртуальное восприятие: подтверждено 2 сценария (dealer-vs-kill-switches не запускался — только поверх браузера).

## 10. Rollback

- **Soft**: `MCA_DREAM_*_ENABLED=false` (7 переключателей, послойно: resolver → профиль → evidence → квоты → отчёты → пересмотр → исследование) + `systemctl restart admin_bot` → OFF = бит-в-бит 2.58.48.
- **Cold**: `git revert` до `4a6031cb/04b5fdd`; **v25 аддитивна** — старый код 2.58.48 не читает новые колонки (nullable) — restore-якорь живой (backup-guard) — не деградирует пайплайн.
- **restore-якорь**: `/var/www/admin_bot/pre_migration_20261004_072506.db` (1.31GB) — только аварийный (R18).

## 11. PENDING OWNER

- **T-4733 live-прогон глубокого сна** — PENDING OWNER (платные LLM-вызоы + DEEP_SLEEP_TRIGGER after_sleep — сон в ~02:30 UTC; прямой преленч выполняет DevOps manual تشать; требует Poev-санкцию по бюджету/окну) ⇒ run-статус §7.3 — NOT_VERIFIED-with-причиной (THR-15 honest.
- **Dream-episodes pool** (T-4709/4710): эпи�зоды = 0 на проде (mca-05 live-извлечение не запускалось всё ещё — owner-scope).
- **mca-17c**: браузерный рендер chain-UI (карточка delta) — зона следующей фичи (round-only, doc-only для mca-06).
- **Внешний сет popcorn попробовать 'sleep state card' в браузере** — уже в §9 (2 сценария: 0-sheetkeeping/0-quick-access/0-JS-errors на 2.58.49) но live-ывод-мы диджи — PENDING OWNER

## 12. Итог

- APP_VERSION **2.58.49**, feat/doc-коммиты образуют атомарную пару (7fc2e39 + 04b5fdd).
- Migrations v25 applied + guard + read-back; user_version = 25; 0 errors; R17-чисто; kill-switches-default-паспорт exact.
- ConfigCache живы (5/5 last4 configured); browser smoke free — 0 JS errors.
- **верифицировано VERIFIED поверх прод-актуального контура.**

---

Delivered: 04.10.2026 07:52 UTC — VERIFIED (T-4733 live-deep-sleep run = PENDING OWNER)
