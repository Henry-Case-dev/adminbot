# Evidence — S9 `summary-testing-ui-round1026` (Эпик 2, §113)

- **Автор:** Step 4 @Builder (23.09.2026).
- **База (diff base):** HEAD `cc6105c` (closing-docs S5); annotated-тег отката **`pre-round1026-s9`** → объект тега `9f4305a`, deref-commit **`cc6105c`** (= HEAD; проверено `git rev-list -n 1 pre-round1026-s9` = `cc6105c…`). Ранее в evidence ошибочно указывался `ae5a147` (L-R1026S9-1) — исправлено.
- **APP_VERSION:** `2.58.24 → 2.58.25` (D8).
- **Δ DDL=0:** `services/database.py`/`services/pg_db.py`/SQL — вне diff (`git status`: не изменены).
- **Δ каталога=0:** `param_catalog.py` вне diff; tab-id `testing` УЖЕ объявлен (`WORKSPACE_TABS.mod_summary`); F8 не переиздаётся. Импорт-проверка: REGISTRY **469** / FIELDS **426** / CATEGORIZED **444** / GROUPS **100** / TAB **98** / RULES **21**.

## Изменённые/новые файлы

| Файл | Тип | Что |
|---|---|---|
| `services/summary_test_run.py` | **new** | dry-run сервис `run_summary_test`/`TestRunResult`/`present_result`; коды `TEST_*` (+`TEST_RUN_FAILED`); метрики §112; 0 публикаций/памяти/image; **rework:** `_empty_metrics`/`_empty_artifacts`/`_empty_display`, `error_result`, `empty_payload`, нормализация `present_result` (B-R1026S9-2) |
| `web/api/summary_test.py` | **new** | роутер (async 202 + polling, in-memory store TTL 15 мин/≤20, availability-probe, обложка по подтверждению); `routes.py` вне diff; **rework:** `_result_payload`/`_execute` отдают контракт-валидные структуры; purge/эвикция не выбрасывают running (L-R1026S9-3) |
| `services/summary_generator.py` | modified | additive `SummaryGenerator.build_test_rows` (+51, только добавление; тело `_run`/`_run_hybrid_l2` не тронуто); **rework:** сброс `_filter_metrics[chat_id]` перед `_apply_filter` (L-R1026S9-5, аддитивно) |
| `services/web_runtime.py` | modified | `set_summary_generator`/`get_summary_generator` (+reset) |
| `bot.py` | modified | импорт + `set_summary_generator(generator)` после создания (строка `from services.web_runtime import set_web_bot` сохранена) |
| `web/app.py` | modified | include `summary_test_router` (минимальная точка подключения; `routes.py` не тронут) |
| `config/settings.py` | modified | env-only ClassVar `SUMMARY_TEST_UI_ENABLED` (default ON; hot-OFF `false`) + bump `APP_VERSION` 2.58.25 |
| `web/app.js` | modified | `summaryTest` state, computed `summaryTestVisible`/`summaryTestWindows`, watcher `workspaceTab`, методы run/poll/cover/availability; **rework:** computed `summaryTestMetrics`/`summaryTestArtifacts` (guard) + `summaryTestDropPercent` (§112) |
| `web/index.html` | modified | секция `data-summary-test` (форма чат/окно/«Проверить пайплайн», dry-run-пометки, метрики §112, диагностика, артефакты, обложка); **rework:** guard `v-if` метрик/артефактов + строка `data-summary-test-drop` «Процент отсева» |
| `README.md` | modified | `v2.58.25` + описание S9 (флаг default ON; hot-OFF false) |
| `.env.example` | modified | S9-блок env-only `SUMMARY_TEST_UI_ENABLED` (default ON; hot-OFF false) |
| `plans/docs/param-registry-round1025.meta.md` | modified | `APP_VERSION 2.58.25` (пин-тест `test_meta_provenance`) |
| `tests/test_summary_test_run.py` | **new** | 22 теста (dry-run/0-0-0/артефакты/fail-closed/метрики/каталог; **rework:** контракт error-payload, fail-open reset) |
| `tests/test_summary_test_api.py` | **new** | 21 тест (RBAC/флаг default ON + OFF по env false/202+poll/409/429/store/обложка; **rework:** error-payload contract, `_execute` exception, running-retention) |
| `tests/test_settings_helpers.py` | modified | +3 теста: default ON / env `false` hot-OFF / true-формы флага (S9 Step 5) |
| `tests/js/round1026_s9_testing_test.js` | **new** | JS-маркеры UI (реальная логика app.js + маркеры index.html) + default-ON probe |
| `tests/test_webapp_js_unit.py` | modified | регистрация JS-теста S9 |
| пины версии (`tests/*_round1025.py`, `test_webapp_round1026_polygon.py`, `tests/js/round1025_hotfix7/8/9/10_*.js`) | modified | `2.58.24 → 2.58.25` (атомарный bump) |

**Вне diff (проверено `git status`):** `services/image_generation.py`, `services/telegram_send.py`, `services/summary_{filter,context_restore,l1_clusterizer,l1_contract,fact_package,l2_writer,article_formatter,xml,memory}.py`, `web/api/routes.py`, `services/database.py`, `services/pg_db.py`, `services/param_catalog.py`.

## Прогоны (фактические результаты)

- `py -3 -m pytest -q` (`.venv`): **8854 passed / 0 failed** (baseline 8807 → **+47**: 18 сервис + 18 API + 3 settings + 1 JS-регистрация + **+7 rework T-3375**).
- JS: `node --check web/app.js` → OK; все `node tests/js/*.js` → **44/44 OK** (в т.ч. `round1026_s9_testing_test.js` → `SUMMARY-TESTING-UI-OK`; добавлены проверки guard error-пути и «Процент отсева»).
- `git diff --check` → без whitespace-ошибок (только LF/CRLF-предупреждения).
- Каталог импортом: 469/426/444/100/98/21 (не изменился).
- Δ DDL=0: DB/SQL-файлы вне diff.

## Покрытые приёмочные сценарии (spec §9)

- **SC-04/SC-12 (инварианты dry-run):** шпионы `send_text`/`send_rich_message`/`build_cover_media`/`generate_image_verbose` + `summary_memory.*` не вызваны; `_hybrid_l2_enabled`/`_run_hybrid_l2` не вызваны; `llm.generate.await_count == 2` (steps `l1_clusterizer`,`l2_writer`); `SUMMARY_HYBRID_L2_ENABLED` до==после (False).
- **SC-05 (артефакты):** source/filtered/dropped/restored/clusters/package/article/rich_preview/plain_preview — реальные объекты S1–S5.
- **SC-06:** пустое окно → `empty`/`TEST_WINDOW_EMPTY`, 0 LLM-вызовов.
- **SC-07/SC-08:** невалидный L1 → `invalid`/`TEST_L1_INVALID` (L2 не вызывается); `LLMError` → `TEST_LLM_UNAVAILABLE`; пакет не deliverable → `skipped`/`TEST_PACKAGE_NOT_DELIVERABLE`; нет генератора → `TEST_NO_GENERATOR`.
- **SC-09:** обложка по умолчанию `not_generated`; подтверждение без промпта → `COVER_GENERATION_FAILED`, `generate_image` не вызван.
- **SC-10/SC-11:** rich-предпросмотр содержит `<h1>`; plain — `<b>`-заголовок.
- **SC-13:** токены/стоимость без PG → «Нет данных»; `-1`-sentinel → «Без лимита»; статус публикации «не публиковалось (dry-run)».
- **SC-14:** 401 (без initData), 403 (не-админ), 422 (невалидный chat_id), 404 (флаг OFF — явный env `false`, до auth); default ON → 200; R17-safe ответы.
- **SC-15:** маршрут `#/modules/summary/testing` валиден; tab-id уже объявлен; форма/пометки/метрики/обложка — JS-тест зелёный; default ON → probe доступности вызывается.

## Правка Step 5 @Builder (23.09.2026) — default ON по вердикту @Architect

- `SUMMARY_TEST_UI_ENABLED` **default `True`** (было `False`); комментарий: «Default ON; hot-OFF `SUMMARY_TEST_UI_ENABLED=false`»; в bump-комментарии `default OFF` → `default ON`. Флаг — тумблер доступности UI/API (dry-run 0/0/0, только global admin), **не** гейт публикации; OFF = hot-OFF (404 + скрытие вкладки). ADR-1026-8 D1 уточнён @Architect (Step 5).
- Тесты: OFF-ветка — явный env `false` (reload singleton + rebind в роутере, `tests/test_summary_test_api.py::TestFlagAndRbac::test_flag_off_404_before_auth`); добавлен default-ON тест (API 200 без ручного включения) + 3 env-теста в `tests/test_settings_helpers.py` + default-ON probe в JS.
- Docs: `README.md` и `.env.example` — `default OFF` → `default ON` (новый S9-блок env-only флага).
- Вне правок: живой путь/публикация/каталог/DDL; `APP_VERSION` = `2.58.25`; Δ каталога=0.

## Rework T-3375 (@Builder, 23.09.2026) — закрытие блокеров @Reviewer/@Scanner

- **B-R1026S9-2 / S-R1026S9-1 (High, UI-краш на error-путях) — закрыт.**
  - `services/summary_test_run.py`: добавлены `_empty_metrics`/`_empty_artifacts`/`_empty_display`; `_base_result` теперь всегда отдаёт полные структуры; `present_result` нормализует `metrics`/`artifacts` (нет `undefined.l1`); новые `error_result` (диагностика + полные структуры) и `empty_payload` (running/edge); код `TEST_RUN_FAILED` для непредвиденного исключения.
  - `web/api/summary_test.py`: `_result_payload` на `entry.result is None` возвращает `empty_payload` (полные `metrics`/`artifacts`/`display`); `_execute` catch-all формирует `error_result` с диагностикой (раньше `result=None` → неполный payload).
  - `web/index.html`: метрики обёрнуты в `v-if="summaryTestMetrics"`, артефакты — в `v-if="summaryTestArtifacts"` (безопасный доступ).
  - `web/app.js`: computed `summaryTestMetrics`/`summaryTestArtifacts` — guard’ы возвращают `null` на неполном payload.
  - **Тесты:** `test_no_generator_error_payload_contract`, `test_error_result_has_diagnostics_and_full_structures`, `test_empty_payload_running_contract` (run); `test_run_no_generator_still_polls_error` расширен + `test_execute_exception_payload_contract` (API); JS-блок (g) на guard error-пути. Все зелёные.
- **B-R1026S9-1 (Medium, §112 «Процент отсева») — закрыт.** `web/index.html` — строка `data-summary-test-drop` «Процент отсева: …»; `web/app.js` — computed `summaryTestDropPercent` (`null`/неизвестно → «Нет данных», без выдуманного `0`). JS-блок (h) + маркеры. `_metrics` уже вычислял `drop_percent` — теперь он виден.
- **L-R1026S9-1 (Low, docs/R18) — закрыт.** `evidence.md`/`tasks.md`: annotated-тег `pre-round1026-s9` → deref-commit **`cc6105c`** (объект тега `9f4305a`), не `ae5a147` (проверено `git rev-list -n 1`).
- **L-R1026S9-3 / S-R1026S9-2 (Low, robustness) — закрыт.** `_RunStore._purge` исключает `status=="running"`; `put_running`-эвикция не выбирает running-кандидатов. Тесты `test_store_ttl_keeps_running`, `test_store_eviction_keeps_running`; существующие `test_store_limit_20`/`test_store_ttl_purge` приведены к семантике (лимит/TTL — для завершённых).
- **L-R1026S9-4 / S-R1026S9-3 (Low, contract/docs) — закрыт.** spec §5.2: убран `503`, зафиксировано `202`/`200` + `status="error"` (`TEST_NO_GENERATOR`) и контракт-валидность; §7 добавлен `TEST_RUN_FAILED`; README — оговорка «кроме отдельного подтверждения обложки».
- **L-R1026S9-5 / S-R1026S9-4 (Low, metrics) — закрыт.** `SummaryGenerator.build_test_rows` сбрасывает слот `_filter_metrics[chat_id]` перед `_apply_filter` (аддитивно, тело живого пути не тронуто) → fail-open больше не подтягивает устаревшие метрики. Тест `test_build_test_rows_fail_open_resets_stale_filter_metrics`.

## Расхождения / не проверено (честно)

1. **Конфликт флага (D8) — РАЗРЕШЁН:** spec §5.1 и ADR-1026-8 D1 требуют **default ON**; ошибочная инструкция Step 4 («default false») отменена @Architect (Step 5). Реализовано **ON** (см. «Правка Step 5»). OFF-путь проверяется явным env `false`.
2. **`pre-round1026-s9` → deref-commit `cc6105c`** (= HEAD; annotated-объект `9f4305a`). Ранее в evidence/tasks ошибочно стоял `ae5a147` — исправлено (L-R1026S9-1).
3. **Живой ON-путь (S6/S10)** — GATED, не активировался; публикация/`generate_image`/обложка/XML/`routes.py` — вне diff.
4. **Live-приёмка владельца** S1–S5/Эпика 1/S9 — PENDING OWNER VERIFICATION (не в скоупе Builder).
5. Cover-эндпоинт переиспользует существующий `generate_image_verbose` (0 новых LLM-вызовов) — тест с моком; реальная генерация изображения в этом прогоне не выполнялась.
6. **`summary_generator.py` в diff — намеренно:** задача Step 4 просит проверить «`summary_generator.py` вне diff», но spec §2/T-3348 и ADR-1026-8 D2 **требуют** аддитивный `SummaryGenerator.build_test_rows`. Diff файла — **только добавление** метода (+51 строк, 0 удалений): тела `_run`/`_run_hybrid_l2`/`_apply_filter` не тронуты; поведение OFF-пути не изменено. Публикация (`telegram_send.py`), `image_generation.py`, `summary_memory.py`, `summary_xml.py` — **вне diff**. Расхождение формулировок — на подтверждение @Architect.

## Деплой (T-3378, Шаг 9 @DevOps, 24.09.2026) — **VERIFIED**

- **Окружение:** прод VPS `racknerd-f4e3456` (`/var/www/admin_bot`, systemd-юнит `admin_bot`, `venv/bin/python bot.py`). Локальная дата — 24.09.2026; часы VPS — UTC `2026-09-23 12:22:30`.
- **Коммиты:** `ac3f8fc` (код+тесты, 2.58.24 → **2.58.25**) → `59e5b12` (планы/архив, Merge §77). Push `origin/master` без force: **`cc6105c..59e5b12`**.
- **Релиз-команды (прод):** `git pull --ff-only` (ff `ae5a147..59e5b12`, без конфликтов) → `sudo -n systemctl restart admin_bot` (NOPASSWD-правило sudoers).
- **Преддеплойный гейт (локально):** pytest `.venv` по затронутым (`test_summary_test_run.py`, `test_summary_test_api.py`, `test_webapp_api.py`, `test_settings_helpers.py`, `test_param_catalog.py`) — **286 passed / 0 failed**; JS — **44/44** (`node tests/js/*_test.js`, в т.ч. `round1026_s9_testing_test.js` → `SUMMARY-TESTING-UI-OK`); Δ DDL=0. Секрет-скан diff/новых файлов — чисто (креды `deploy_commands.txt`/`.env*` не коммитились — gitignored).
- **Прод-факты (после рестарта):** `systemctl` active (running), MainPID `467979`; `/api/health` **200** `{"status":"ok","version":"2.58.25"}`; `/healthz` → `2.58.25`; планировщик Саммари стартовал (`SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)`), polling стартовал; каталог импортом — **469**; `SUMMARY_TEST_UI_ENABLED` в `.env` отсутствует → **default ON**, `GET /api/summary/test/availability` → **401** (маршрут зарегистрирован; OFF-семантика 404 проверена юнит-тестами).
- **Инварианты dry-run/живого пути (лог рестарта):** Traceback/CRITICAL/ImportError = **0**; `database is locked` = **0**; `L2_*` = **0**; `FORMAT_*` = **0**; `TEST_*` = **0**; `generate_image` = **0**; публикации (`PUBLISH_*`/`send_rich_message`) = **0** (гибридный живой путь OFF).
- **Миграции:** Δ DDL=0 — SQL/DB-файлы вне релиза; миграции не запускались.
- **Откат (readiness):** annotated-тег `pre-round1026-s9` (объект `9f4305a`, deref **`cc6105c`**) есть на `origin`; план — `git reset --hard pre-round1026-s9` + рестарт `admin_bot`. Hot-OFF без отката — `SUMMARY_TEST_UI_ENABLED=false` (+ рестарт) → вкладка скрыта, API 404. `deploy_commands.txt` не изменялся (R18).
- **Статус:** **VERIFIED**. Live-приёмка владельца (реальный TMA/WebView) — ⏳ PENDING OWNER VERIFICATION.
