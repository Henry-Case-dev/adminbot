# deployment.md — asap-4-2-summary-surgical-reliability (prod 2.58.48)

Feature: `asap-4-2-summary-surgical-reliability` · Risk R3 · **Статус: VERIFIED**
Дата: 04.10.2026 (UTC) · Исполнитель: @DevOps · Задача T-4834 (Step 8)

## 1. Binding и окружение

- Прерванная сессия (resume по месту остановки; прямой SSH в этот рейс сначала таймаутил, спустя минуты порт 22 восстановился — флот-симптом сетевого окна; повторные пробы 2222/2200/22022/8022/2022 — закрыты, маршрута нет; финальное соединение удачным).
- Прод: `nik@198.46.175.136:/var/www/admin_bot` (racknerd-f4e3456), systemd-юнит `admin_bot` (Ubuntu 24.04, venv `/var/www/admin_bot/venv`, Python 3.12).
- Кандидат: origin/master = **`b4dcb34`** (docs round1032) = локальный HEAD; feat-коммит **`1da44b5`** (APP_VERSION **2.58.48**, весь скоуп ASAP 4.2 — 99 файлов: summary_source_anchors / summary_l2_anchor_repair / L1-map v2 / supervisor / capacity live-precedence + NanoGPT edit + MiniApp UX; APP_VERSION 2.58.47→2.58.48).
- Миграция с 05a210c (2.58.47) на b4dcb34 — fast-forward, без конфликтов; деплой-авторизация — Orchestrator (T-4834, Step 8, resume).

## 2. Деплой (факты)

- `git pull --ff-only` на проде: `05a210c..b4dcb34` (fast-forward) → HEAD **`b4dcb34`** ✓.
- Диск до рестарта: 24G всего / **17G used, 5.8G free (75%)** — без дефицита.
- **Рестарт**: `sudo -n systemctl restart admin_bot` (NOPASSWD-allowlist: systemctl) → **rc=0**; **active (running) с 02:34:38 UTC, MainPID=3484893, NRestarts=0, ExecMainStatus=0** ✓.

## 3. DDL

- **user_version = 24 → 24** (read-only PRAGMA до и после рестарта) — **DDL=0** ✓ (свер»). Ни одной новой таблицы/колонки в asap-4-2 по паспорту (anchors живут в immutable `summary_source_windows` + run-stage артефактах); таблицы v24 (`summary_source_windows`, `summary_runs`, `summary_run_stages`) — на месте ✓; в журнале старта строк миграции/DDL нет.
- PG: no-op (Summary-контур весь в SQLite).

## 4. Kill-switches — паспорт дефолта

- **Прод-.env: 0 вхождений** имён флагов (`SUMMARY_[A-Z0-9_]*_ENABLED`, `SUMMARY_MODE_A/B`, `RUN_MODE`, `EMBED_ASYNC_BATCH_ENABLED`, `COVER_STYLE_PROVIDER_ROUTES_ENABLED`, `IMAGE_PROMPT_*`) → кодовые дефолты; **0 systemd Environment-оверрайдов** (`systemctl show -p Environment` = пусто). Значения env не читались (R17 — счётчик имён).
- **Живой Settings-дамп на проде (env-loaded, прод-venv)**:
  - **4 anchor-флага ON**: `SUMMARY_SOURCE_ANCHORS_ENABLED`, `SUMMARY_L1_ANCHOR_REPAIR_ENABLED`, `SUMMARY_L2_EVIDENCE_REPAIR_ENABLED`, `SUMMARY_L2_TARGETED_REVISION_ENABLED` ✓
  - **5 «42»-свитчей ON**: `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED`, `SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED`, `COVER_STYLE_PROVIDER_ROUTES_ENABLED`, `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED`, `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED` ✓
  - **Mode A/B OFF**: `SUMMARY_LLM_ASYNC_MODE_ENABLED=false`, `SUMMARY_LLM_STREAMING_MODE_ENABLED=false` (+ `SUMMARY_STREAMING_ENABLED=false`) ✓
  - **Async batch OFF**: `EMBED_ASYNC_BATCH_ENABLED=false` ✓
  - Базовые Summary-зоны (A–G: SOURCE_WINDOW_DURABLE / WHOLE_WINDOW_FIRST / OVERFLOW_LEDGER / L1_SEMANTIC_MAP / WRITER_SOURCE_INPUT / LEGACY_SOURCE_WINDOW / SUPERVISOR / RUN_DURABLE / STYLE_GLOBAL_DEFAULT и др.) — все ON ✓. OFF = бит-в-бит 2.58.47-контуры (rollback-полка).

## 5. Пост-деплой приёмка

1. **Модули**: `services.summary_source_anchors`, `services.summary_l2_anchor_repair` — importlib-загрузка на проде OK (оба резолвятся в файлы эпика) ✓.
2. **Health**: `GET :8000/healthz` (локальный curl) → **HTTP 200** `{"status":"ok","version":"2.58.48"}` ✓.
3. **RBAC-гейты (unauth)**: `GET /api/analytics/pipeline/inspector` → **401**; `?mode=structured` → **401**; `GET /api/analytics/pipeline/runs/abc` → **401** (эндпоинт существует); `GET /api/memory/embeddings` → **401**; **`POST /api/cover/test-style` → 401** `{"detail":"missing init data"}` ✓ (test-style не публичный).
4. **Ladder/parity на прод-venv**: 11 файлов (asap41: wave8_off_parity, wave8_ladder_matrix, cover_style_wave_f, cover_wave_b_asap4; asap42: summary_source_anchors, anchors_wiring, capacity_asap41, step2c_image_capacity, step3_style_integration, step2c2_miniapp_seeds + cover_styles_contract_asap32) → **177 passed / 0 failed** (3 warnings, 30.75s) ✓.
5. **Каталог F8**: `gen_param_registry_round1025.py --check` → **CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны**, EXIT=0 (Δ каталога = 0) ✓.
6. **Посторонние ошибки**: окно 30 мин после рестарта — `ERROR|CRITICAL|Traceback` = **0 хитов** ✓. Единственный WARNING — известный контур asap-4: GraphRAG embed 429 (kind=spend, spend-parking, `paused_rate_limit`, cooldown 77364s, checkpoint preserved; resume-backoff по расписанию) — вне скоупа эпика, документировано в раундах 1030/1031.
7. **R17-скан журнала** (окно 60 мин): `sk-*`, `Bearer`, `xox*`, `AKIA`, `-----BEGIN`, `api_key=` — **всё по 0 хитов** ✓ (в логах reason-коды/счётчики).
8. **Ключи через ConfigCache**: контрактный путь `hot.get("keys.llm_api_key", settings.LLM_API_KEY)` (ConfigCache → env-фолбэк). Живое доказательство: сразу после рестарта журнал показывает успешные **embedding-вызовы HTTP 200** (`gemini-embedding-001`, `LLM embed_once OK`) — при резолюции из сырого env с фиктивным `LLM_API_KEY=401`Google вернул бы 401; т.е. **ключи резолвятся из каталога (ConfigCache), не из сырого env** ✓. Standalone-питон: кэш горячего конфига не приаттачен вне bot.py-старта (по дизайну set_config_cache) — це ожидаемое поведение, не дефект. Диагностика сделана булевыми фактами (значения ключей/env не печатались — R17).

## 6. FREE прод-приёмка + deployed UI browser smoke (Playwright, unauth-поверхность)

- **desktop 1280×800** `https://admin-bot.duckdns.org/web/#/modules`: **`.more-sheet`/`.more-backdrop` отсутствуют в DOM** (закрытое состояние → unmount; intersection тривиально 0px), band hit-test (4×3 точки нижней зоны) — **0 overlay-перехватов**; **Modules Quick Access отсутствует** (нет `.module-quick-wrap` и текста «Быстрое управление»); честная unauth-заглушка («Миниапп открыт без Telegram-контекста»); console: **0 JS-ошибок** (единственный entry — favicon 404, косметика, pre-existing); скриншот `deployment-evidence/asap42_prod_desktop_1280_modules.png` ✓.
- **mobile 390×844**: та же проверка — шторка не смонтирована, **bandOverlays=0**, Quick Access отсутствует; мобильный shell отрисован (`bottom-nav` 390×45 flex, 2 ссылки, h≤140); **0 JS-ошибок**; скриншот `deployment-evidence/asap42_prod_mobile_390_modules.png` ✓.
- Честное ограничение: аутентифицированный проход (style cards before/after на реальных seeds, отсутствие file-picker/расхода счётчика на `test-style`, живой non-admin 403, RBAC-seeded обзор) — внутри PO-5 (см. §7); prior round 1031 и round 1032 review прошли лучший (review-харнесс + 16 RBAC-seeded unit-тестов из 177-набора, пройденных на прод-venv).

## 7. PENDING OWNER (PO-2..5 — live-приёмки владельца; архив фичи до них запрещён)

- **PO-2**: реальный 1480-Summary run — **Hybrid выживает / Legacy NOT used** (живое распределение сообщений, durable-контур).
- **PO-3**: живой **Medved Press styled cover** (реальный edit HTTP 2xx + реальный image).
- **PO-4**: **Test Style не публичный / без расхода счётчика** (нет file-picker, previews persist, «Протестировать стиль» живой).
- **PO-5**: **stale sha style_example** проверка + аутентифицированный обзор (provider-смена → re-resolve, `800` не протекает в лимит).

## 8. Rollback

- **Soft**: перечисленные env-флаги §4 `=false` + рестарт → OFF = бит-в-бит 2.58.47-контуры (Mode A/B и async batch уже OFF); при красном canary — `COVER_STYLE_PROVIDER_ROUTES_ENABLED=false` → прежний fail-soft Base Cover путь.
- **Cold**: `git revert` до `05a210c`/`f22023e`; **DDL=0 — миграций нет, restore-якорь не требуется** (существование подтверждено: `pre_migration_20261003_102818.db`, 1 310 662 656 B ≈ 1.31GB, root-owned, на сервере; страховка БД).

---

Delivered: 04.10.2026 02:47 UTC · VERIFIED (PO-2..5 PENDING OWNER)
