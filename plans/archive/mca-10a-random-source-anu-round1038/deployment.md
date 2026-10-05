# deployment.md — mca-10a-random-source-anu (prod 2.58.58)

**Пакет:** `mca-10a-random-source-anu` (T-4985) — Risk R3 (threat-failure-analysis, THR-1…THR-14) — **Статус: VERIFIED**
**Выполнен:** 05.10.2026 (рестарт #1 03:36:21 UTC, рестарт #2 03:41:25 UTC) — деплой @DevOps T-4985 (reviewer **Approved** T-4984 + addendum «F-1 resolved — quota recheck»; binding: HEAD `c49ee02` + WTH-манифест 89 файлов `plans/reports/mca10a_wth_manifest_review.txt`).

## 1. Preflight (binding)

- Манифест (89 data lines; 74 tracked-modified + 15 new; recipe: `path␣␣sha256`, sorted, LF, UTF-8, join+trailing LF): **sha256 тела `424b09d57b47c3fc34459a4ecdfb39e7f9e9353a9b3fd7fadca111337fc10435` — MATCH, воспроизводимо**. Per-file 89/89 — хэши совпадают с запиннованным (15 new — по content, дрейфа нет).
- Review + addendum подтверждены: verdict `Approved`, F-1 resolved (period-aware quota + тест `test_quota_period_rollover_honest_remaining`, pre-fix RED); F-2…F-6 non-blocking/pre-existing.
- Prod pre-state: HEAD `9f4989c` (2.58.57), PID 3774675, active, NRestarts 0, `/healthz` 200 `2.58.57`; SQLite **v26** (`schema_migrations` 15, таблиц 100; `mca_random*` — нет), PG 26 таблиц (17/13/24, `llm_usage_events` 2890).

## 2. Version bump CA-11 и коммиты (явные пути, без `git add -A`)

- **Bump 2.58.57→2.58.58** per CA-11 per-feature (прецедент mca-06/08/15/11): `config/settings.py` `APP_VERSION` (аннотация mca-10a + Prior-цепочка сохранена) + **14 py release-pin файлов** (`APP_VERSION ==`/`'APP_VERSION = "'` пины: decision_making/image_context_memory/scope_selector/round1025_f8_registry/summary_{deploy,fact_package,logging_runid,publish_integration,test_run}/telegram_reactions/tool_coordinator/unified_image_request/webapp_f11/webapp_polygon) + **4 JS-харнесса** `round1025_hotfix{7,8,9,10}` regex-пины `2.58.49→2.58.58` (закрытие **reviewer F-5**) + F8 meta-pin `plans/docs/param-registry-round1025.meta.md` (APP_VERSION; HEAD-строка остаётся `c49ee02` — записан на binding-HEADе при переиздании).
- **feat: `cd0a353`** — 88 файлов (+15283/−9660): 74 tracked-diff манифеста + 9 новых (`services/mca_random_source.py`, 5 блок-тестов A–E, JS-тест + harness, `tools/_mca10a_reissue_f8.py`) + 5 release-pin-sweep файлов (`tests/test_scope_selector_round1025.py` + 4 hotfix-харнесса, вне манифеста по прецеденту release-pin bump). Дельты против манифеста — **только версииный свип/APP_VERSION/meta-пин** (санкция review: F-5 «закрываются штатным release-pin bump на T-4985»; F8-артефакты/каталог не менялись — TSV/screen-map hash-идентичны, `--check` OK).
- **docs: `12a741a`** — 8 файлов: `plans/features/mca-10a-random-source-anu/{spec.md, adr-1028-14-random-source-anu.md, threat-failure-analysis.md, tasks.md, requirements-map.md, evidence.md, review.md}` + `plans/reports/mca10a_wth_manifest_review.txt`.
- **deploy-doc:** этот файл (после deploy).
- Исключены per манифест-заголовок: `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, debris (`node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*`, `plans/verification_cache.json`). Остались несёкнутыми и не пушнуты.

## 3. Сейл-контур миграций (mca-14, Δ DDL = v27)

- **Ручной pre-restart backup @DevOps ДО pull/рестарта:** `pre_migration_devops_20261005_033344.db` **1 384 566 784 B** (1.38 GB), read-back sha256 OK (`80a1d990…3eb1`, source==copy). ⚠️ После boot **disk-retention policy mca-14 ротировала этот копию и прошлогодний `pre_migration_20261004_210851.db`** (лог `[disk_retention] migration backup rotated out`) — штатный retention; восстановительный якорь — собственный guard-копия mca-14 (см. ниже).
- **Guard mca-14 при boot ДО применения (fail-closed):** `Oct 05 03:38:58 UTC services.memory_backup INFO: pre-migration copy created + read-back ok | target_version=26` → `/var/www/admin_bot/pre_migration_20261005_033640.db` **1 316 651 008 B (1.317 GB)** — **якорь rollback.**
- **Миграция v26→v27 применена:** `PRAGMA user_version` **27**; `schema_migrations` **16** с book-записью **`(27, random_source)` — ровно 1 раз**; таблиц **104** (100+4: `mca_random_batches`/`mca_random_draws`/`mca_random_quota_state`/`mca_random_state`); **3 idx `idx_mca_random*`**.
- **Идемпотентность:** второй рестарт (03:41:25 UTC, PID 3807957) — **no-op**: `user_version 27`, `sm` 16, таблиц 104, book27=1, healthz 200 @2.58.58 (try 6 = через ~30 c после boot), NRestarts 0, ExecMainStatus 0.

## 4. Health / route smoke / kill-switches

- `/healthz` **200 `{"status":"ok","version":"2.58.58"}`** (первая же проверка после boot#1 и boot#2); `/api/health` **200**.
- `POST /api/random/test` unauth → **401 `{"detail":"missing init data"}`** (RBAC intact; внешний ANU-вызов не выполнялся — live-часть под ключом).
- `.env`/systemd: **0 env-оверрайдов по K1 `MCA_RANDOM_SOURCE_ENABLED`/K2 `MCA_RANDOM_QUANTUM_ENABLED`/K3 `MCA_RANDOM_REFILL_ENABLED`/K4 `MCA_RANDOM_EXPLORATION_ENABLED`** (grep .env = 0 вхождений, systemd overrides нет) → все **default ON**; K5 `MCA_MONEY_LIMITS_ENABLED` OFF не тронут. Состояние Counter/override/config не менялось (0 записей от DevOps).

## 5. Данные / PG no-op

-SQLite spot-checks (pre → post): `task_jobs` 643→644 (+1 live), `mca_events` 10265→10272 (+7 live boot/notable), `mca_bot_outputs` 75=75, `summary_runs` 13=13, `mca_style_requests` 0=0; новые таблицы: batches/draws/quota_state **0**, `mca_random_state` **1** (singleton init-строка state-контура — ожидаемо при пустом ключе, F-6 шум). PG миграций — **no-op byte-равно pre**: таблицы 26=26, assignments 17=17, assets 13=13, provenance 24=24, `llm_usage_events` **2890=2890**.

## 6. Focused-проверки (не полный suite)

| Проверка | Результат |
|---|---|
| Локально (пост-бамп, pre-commit): блоки A–E + JS + F8 mca10a | **108 passed** (7.58s; было 107 @review — F-1 тест добавляет +1) |
| 14 release-pin пин-тестов (пост-бамп) | **14 passed** (+1 дубликат-ID исключён) |
| tests/test_webapp_js_unit hotfix7–10 (node v24.16.0) | **4 passed** — F-5 закрыт |
| Prod-venv pre-restart: тот же набор A–E+JS+F8 | **107 passed, 1 skipped (JS-тест — node не установлен на prod; узел-эквивалент performed локально)** 36.90s |
| `gen_param_registry_round1025 --check` (pre- и post-restart) | **CHECK OK: реестр 502 == REGISTRY, R17-чисто, TSV/map идемпотентны** (×2) |
| Локальный `node tests/js/round1037_random_source_test.js` | **MCA10A-RANDOM-OK** (evidence Builder; харнесс в feat) |

## 7. Логи / R17 (окно 03:36:00→03:46:20 UTC, оба boot)

- **ERROR/CRITICAL/Traceback = 0** (оба окна, до рестарта #2 включительно).
- R17-скан (`sk-`/`Bearer`/`AKIA`/`-----BEGIN`/`*api_key=`; `random_quantum_api_key`): **0 хитов** — ключ ANU нигде не фигурирует (живого ключа нет: K1/K2 ON, но ключ не установлен → `provider_unconfigured`, активация невозможна по конструкту).

## 8. Rollback

- **Soft (первый выбор):** `.env += MCA_RANDOM_SOURCE_ENABLED=false` (K1 master; при необходимости + K2/K3/K4=false) + рестарт → dream = `default_source` **бит-в-бит 2.58.57**, ANU/рефила не активны, v27-таблицы инертны (не читаются K1-OFF).
- **Cold:** `git revert` feat `cd0a353` (либо checkout `9f4989c` = 2.58.57). **v27 аддитивна/инертна** (v26 мультивалидна — scheme self-guard; restore не требуется); аварийный restore-якорь: `pre_migration_20261005_033640.db` (1.317 GB, root) — только R18.
- Замечание: ручной devops-копия утянута retention-политикой автоматически — фактический якорь один (guard-copy); следующий daily MemoryBackup — 05:00 Asia/Yekaterinburg.

## 9. Findings-диспозиции (review T-4984)

- **F-1 Medium — RESOLVED** в кандидате (period-aware quota; тест в 108).
- **F-2 (quantum pick <k при коллизии индексов)** — non-blocking, фичевый quality-ограничение; в release не попадал (код не менялся); учтен как известный caveat для mca-10b.
- **F-3 (errata «secret 32→33»)** — задокументировано в evidence/ADR-1028-14 (реально: тул-семантика 32→41 / истинных secret 31→32); код-импакта нет; merge/реконсиляция @Architect подтвердит errata.
- **F-5 (4 JS-пина)** — **CLOSED** release-pin bump 2.58.58 (тесты зелёные).
- **F-6 (шум provider_unconfigured на старте без ключа, 1 событие/boot)** — видно в prod (ожидаемо); приглушение — вне релиза.
- **F-4 (pre-existing counter-drift `test_telegram_reactions::test_direct_safety_net_calls_legacy`)** — pre-existing red, backlog as-is (вне дельты; файл не менялся логикой, release-pin только в версии).

## 10. Incidental findings (для Orchestrator)

- **[I-1][Info]** `[disk_retention] migration backup rotated out | pre_migration_devops_20261005_033344.db` — ручной pre-restart бэкап удалён retention-политикой сразу после deploy; известное mca-14-поведение, вне mca-10a; фактический R18-якорь остаётся в guard-копии.
- **[I-2][Info]** untracked-мусор на проде: `info_text.md.bak.epic{44,55,56,57,58}` — не в git, deploy не мешает (pre-existing).
- **[I-3][Info]** `README.md` version-строка не обновляется начиная с round 10.34 (v2.58.49 при prod 2.58.58) — док-долг двух релизов (mca-11 не чинил), вне mca-10a.

## 11. Заключение @DevOps

T-4985 выполнен: prod **2.58.58 VERIFIED** (feat `cd0a353` + docs `12a741a` + deploy-doc этот файл), preflight manifest sha256 `424b09d5…` MATCH (per-file 89/89), Δ DDL v26→v27 идемпотентно с fail-closed backup-guard (1.317 GB read-back OK), Δ каталога += 13/2 (F8 `--check` OK **502** дважды), K1–K4 ON / 0 env-overrides, health 200 x2, route 401 unauth (RBAC), данные целы, PG no-op, 0 ERROR/CRITICAL/Traceback, **R17=0** (ANU-ключ нигде нет; live-ключ не установливался за чат/DevOps). Следующий шаг: **live-приёмка T-4986 [PENDING OWNER]** (реальный ключ ANU: запись через keys_random, `POST /api/random/test`, активация квантового запаса, честная витрина) → затем reconcile/includes T-4987. Deploy-машина подтверждает: **live T-4986 может идти**.
