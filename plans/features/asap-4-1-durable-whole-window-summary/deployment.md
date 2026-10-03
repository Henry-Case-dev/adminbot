# deployment.md — asap-4-1-durable-whole-window-summary (prod 2.58.47)

Feature: `asap-4-1-durable-whole-window-summary` · Risk R3 · **Статус: VERIFIED**
Дата: 03.10.2026 (UTC) · Исполнитель: @DevOps · Задача T-4630

## 1. Binding и авторизация

- Review: **Approved for release** (round 2, дельта-гейт фикса [M-ASAP41-1], doc-only) — release-blocking: 0.
- Reviewed-Commit: `60f1c7c07a63192c749ba432f91ab44265adbc50` (= локальный HEAD до коммитов) ✓
- Spec-Hash: `E6A6E5EC…` (spec.md SHA-256 — сверён по манифесту round-2: `e6a6e5ece…f6` включает полный хеш) ✓
- **WTH re-measure (до release-prep):** пин round-2 `BA44A8CDD2BCC832…7419246` воспроизведён — SHA-256 сырых байтов файла-манифеста `plans/reports/asap41_wth_manifest_review_round2.txt` (76 файлов, UTF-8 BOM + CRLF) = `ba44a8cdd2bcc832b9c7e4541745eaccb0e6e98e19cc503f576df12b37419246` — **байт-в-байт** ✓. Содержательная сверка «файлы на диске ↔ per-file хеши манифеста»: 75/76 байт-в-байт; единственное расхождение — `plans/workflow_state.md` (ожидалось `2E45CFAA…`, актуально `CBD6F9A0…`) — служебный файл оркестратора (state_revision), меняется между раундами по замыслу round-2 ревью (он же был одним из 3 per-file расхождений round-1→round-2), в дифф эпика не входит.
- **Drift при коммите (WTH-манифест, post-prep):** повторная сверка 76 файлов с обратным свипом пинов — **73/76 байт-в-байт**; дрейф:
  1. `config/settings.py` — release-prep hunk (APP_VERSION 2.58.46→2.58.47 + голова версии-цепочки комментария) — конвенция release-prep предыдущих раундов;
  2. `plans/workflow_state.md` — оркестраторский bookkeeping, не в диффе эпика, не коммитился;
  3. `tests/test_tool_coordinator_round1026.py` — **контент байт-в-байт с reviewed** (LF-нормализация revert-пина = `27ff77…` = HEAD + эпик-хунок[701:709]→[701:735] + пин; доказано сравнением), но окончания строк эпик-хунку (34 строки) нормализованы к CRLF конвентно репо (инструмент release-prep срезал \r при текстовом редактировании; посимвольное восстановление исходных окончаний оказалось невозможным — проверены все доступные источники). Семантическая разница = 0 (pytest-прогон: 11080 passed — файл включён и стабилен).
  - Post-prep WTH пересчитан и опубликован: `plans/reports/asap41_wth_manifest_delivery.txt` — SHA-256 `02b2c66749e27af8e7c10026fc292f8c1e076dfb045e3f1224672bf984ffc4c7` (recipe round-1: сырые байты, BOM+CRLF).
- Полный pytest после prep-свипа: **11080 passed / 2 failed** (357s, detached) — оба failed = известные pre-existing round1026 `forbidden_paths_out_of_diff`/`_vs_baseline` (те же 2, что в review-прогоне 11 075+2; расхождение в счётчике (+5) объясняется флапом исторических пин-тестов — review.md line 83 констатия). py_compile settings.py OK.
- Секреты (R18/секрет-гигиена): 0 хитов (diff + untracked scope, паттерны API-ключей/токенов/приватных ключей).

## 2. Release prep

- APP_VERSION `2.58.46 → 2.58.47` (`config/settings.py`, версия-цепочка: новая голова asap-4-1 + «Предыдущая: post-asap4-corrective-pass round1030») + README.md (заголовок «Версия»).
- Свип version-пинов: 24 pin-вхождения в 23 py-тестах (12 `assert APP_VERSION ==` + 3 строковых `'APP_VERSION = "…"'` + 9 `m.group(1) ==`) + 4 js-теста (regex `2\.58\.46` → `2\.58\.47`). Исторические паритет-ссылки «бит-в-бит 2.58.46» в services/тестах эпика не тронуты (так и задумано).
- F8-meta переиздана генератором (`python tools/gen_param_registry_round1025.py`; `--check` EXIT=0, «CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто»; Δ каталога = 0; в meta обновились только APP_VERSION + HEAD short).

## 3. Коммиты и деплой

- FEAT: `f22023e` — `feat(round1031): asap-4-1 durable whole-window summary - SummarySourceWindow, semantic map, supervised execution, durable runs, idempotent publication (APP_VERSION 2.58.47)` — 94 файла: 6 новых services (summary_source_window / summary_run_store / summary_coverage_ledger / summary_fact_view / summary_l1_semantic_map / summary_llm_supervisor), правки ядра Summary/cover/pipeline/database/settings/llm_client/mca_events/prompt_migrations, 20 новых asap41-тестов + JS-тест зоны G + tools/ui_asap41_zone_g_e2e.py, свип пинов (23 py + 4 js) + F8 meta/tsv + README + param_catalog.py/f8_baseline (round-2 фикс M-ASAP41-1) + test_summary_param_catalog_annotation_asap41.py.
- DOCS: `05a210c` — spec/ADR-1028-8/tasks/evidence/review/requirements/reuse/conflict-audit + architecture.md canon + full_audit_results + 3 WTH-манифеста (round-1, round-2, delivery) — 15 файлов.
- Push: `60f1c7c..05a210c → origin/master` (github Henry-Case-dev/adminbot).
- Чужой WIP не коммитился: plans/metrics.md, plans/workflow_state.md, plans/docs/mca-round1027-arch-frames.md, node_modules/, package*.json, .playwright-mcp/, extra_images/, временные инструменты DevOps.
- Прод: `git pull --ff-only` на `/var/www/admin_bot` → HEAD `05a210c`; APP_VERSION 2.58.47 подтверждён на проде.
- Диск ДО рестарта: `df` → 17G used / **5.8G free (75%)** — достаточно для fail-closed backup guard.
- Pre-restart DDL-факты (read-only SQLite): `user_version=23`, таблицы v24 отсутствуют.
- Рестарт: `sudo systemctl restart admin_bot` (NOPASSWD-правило) → **active (running) с 10:27:54 UTC, PID 3294197, NRestarts=0** (на момент 10:36:38 стабильно).
- **DDL SQLite v23→v24 — ПРИМЕНИЛАСЬ**: `PRAGMA user_version` = **24** (read-only после старта); **3 новые таблицы созданы и присутствуют**: `summary_source_windows`, `summary_runs`, `summary_run_stages` (additive, реестр mca-14; PG no-op — Summary-контур вся SQLite; фактический F8 CHECK на проде: «CHECK OK: реестр 488 == REGISTRY» EXIT=0).
- **Fail-closed backup guard сработал**: `10:31:00 memory_backup: pre-migration copy created + read-back ok | target_version=23` → бэкап `pre_migration_20261003_102818.db` (1 310 662 656 B ≈ 1.31 GB, root-owned) создан ДО DDL; rotation удалил старый `pre_migration_20261002_101544.db` (retention-политика keep-1 для pre_migration).

## 4. Post-deploy приёмка (факты)

1. **Health**: `GET :8000/healthz` → HTTP 200 `{"status":"ok","version":"2.58.47"}`.
2. **DDL**: `user_version=24`; все 3 таблицы v24 на месте (см. §3); PG no-op (Summary-контур всё в SQLite, DDL-состояния PG не менялись).
3. **Kill-switches — паспорт дефолта**: в проде `.env` **0 вхождений** для всех имён `SUMMARY_*_ENABLED` (29 имён), `SUMMARY_MODE_A/B`, `RUN_MODE`, `EMBED_ASYNC_BATCH_ENABLED` → кодовые дефолты: зоны A–G ON, Mode A/B — контрактные слоты OFF, async batch OFF (бит-в-бит OFF-паритет доступен лишь переключателями, env-оверрайдов на проде НЕТ; значения env не читались — только счётчик вхождений имён, R17-подход).
4. **Inspector API RBAC**: `/api/analytics/pipeline/inspector` → **401** unauth (журнал: `[tma-auth] src=none valid=False reason='missing init data' path=/api/analytics/pipeline/inspector`); `/api/memory/embeddings` → **401**; `/api/memory/attribution/metrics` → **401**. `/api/analytics/pipeline/runs` → 404 (путь в API не существует — не в контракте; gate-требование закрыто реальными эндпоинтами). Аутентифицированный просмотр Inspector — за владельцем (прецедент T-4447/T-4509; admin-креденшелы у DevOps-сессии отсутствуют и не запрашивались).
5. **Ladder/parity на прод-venv** (venv pytest 9.1.1): `test_summary_wave8_off_parity_asap41 + test_summary_wave8_ladder_matrix_asap41 + test_summary_cover_style_wave_f_asap41 + test_cover_style_wave_b_asap4 + test_summary_source_window_asap41 + test_summary_run_store_asap41` → **87 passed** (32s). факты: asap41 (off-паритет, ladder-матрица M3/M4/M5, дurable-окно/runs) + asap4 (cover wave B) файлы — свежие прод-файлы, прогон на прод-venv.
6. **Каталог F8**: прод-прогон `gen_param_registry_round1025.py --check` → `CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`, EXIT=0 (Δ каталога = 0 — как в ревью).
7. **Посторонние ошибки**: окно 10:27:54→10:36:38 (225 строк журнала) — `ERROR|CRITICAL|Traceback`: 2 хита, оба = **известный контур asap-4** (GraphRAG embed: `EmbeddingGroupCoolingDown: group cooling down until 1791072300`; «fact saved text-only» — честный fail-soft, факт сохраняется текстом; это известный 429-квота/spend-parking контур, вне скоупа эпика; NATURAL RESUME по расписанию ~10:45 UTC). Новых ошибок от кода эпика нет.
8. **R17-скан журнала** (sk-/Bearer/xox/AKIA/private-key паттерны): **0 хитов**; в логах только счётчики/ids/reason-коды.
9. **Browser smoke на проде** (SSH-туннель → Playwright, unauth-поверхность):
   - desktop 1280×800: `/web/#/` и `#/oversight` — UI отрисован (sidebar нав, заголовок), честная заглушка «Миниапп открыт без Telegram-контекста» (RBAC через меню бота); **0 JS-ошибок** (единственный console-entry: 404 `/favicon.ico` — косметика, не JS); скриншот `evidence/asap41_prod_desktop_1280.png`;
   - mobile 390×844: та же страница — вёрстка применяется, **0 JS-ошибок**; скриншот `evidence/asap41_prod_mobile_390.png`;
   - аутентифицированный проход Run Inspector (zone G state-оси) — за владельцем (Browser-Verification admin-часть = PENDING-OWNER, прецедент T-4509).

## 5. Ограничения (честно)

- Аутентифицированный просмотр панели/Run Inspector не выполнялся (нет admin-креденшелов — и не запрашивались; R17). Unauth-401-гйты верифицированы, UI-каркас (desktop+mobile) smoke-проверен.
- Wiki-поток GraphRAG/embedding продолжает известный cooldown-контур asap-4 (NATURAL RESUME к 10:45 UTC) — вне скоупа эпика, поведение не изменилось (см. §4.7).
- Post-prep WTH (`02b2c667…`) отличен от пина `BA44A8CD…` по 3 документированным файлам (§1); контент эпика байт-в-байт, отклонение — окончания строк одного хунку тестового файла + release-prep пин hunks (конвенция предыдущих раундов).

## 6. PENDING OWNER (PO-1..5)

- PO-1: реальные 839-сообщения прогоны саммари (полный durable-контур на живом распределении сообщений) — мониторинг первых реальных run'ов в `summary_runs`.
- PO-2: живой Medved Press (cover-лестница на реальном пайплайне издательства).
- PO-3: Mode A/B live-включение (контрактные слоты запланированы как отдельные фичи; кодовые дефолты OFF).
- PO-4: прод-замеры latency/токенов supervised-контура (L1≤2/L2≤6 бюджеты на живых данных).
- PO-5: аутентифицированный Run Inspector обзор (admin-сессия владельца).

## 7. Rollback

- Soft: env-рубильники по доменам (все 9 kill-switches `SUMMARY_*` default ON → `false` = бит-в-бит 2.58.46-контуры; Mode A/B и async batch уже OFF) + рестарт.
- Cold: `git revert` до `05a210c`/`f22023e`; БД v24 аддитивна (старый код её не читает; таблицы остаются — данные не теряются; restore-якорь: `pre_migration_20261003_102818.db`, 1.31 GB, root-owned, суточный бэкап цел).

---

Delivered: 03.10.2026 10:36 UTC · VERIFIED
