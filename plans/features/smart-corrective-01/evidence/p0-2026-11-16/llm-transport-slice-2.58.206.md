# P0 SMART transport — LLM transport slice (2.58.206)

- Дата: 2026-11-16
- База: `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1` (2.58.205)
- Ветка: `fix/p0-llm-transport`
- Код-кандидат: `c292a1cf` (этот файл — отдельный evidence-коммит)
- Статус: REVIEW-кандидат; не деплоился, VERIFIED не заявляется.

## Что изменено (observable contract)

| Требование (рабочая привязка AC) | Реализация | Доказательство |
|---|---|---|
| AC-01 дефолты 180/360 | `config/settings.py`: `LLM_TIMEOUT=180.0`, `LLM_TOTAL_BUDGET=360.0`; семантика «один HTTP-ответ» / «одна основная попытка, не дедлайн исследования» в комментариях, `param_catalog`, README, `.env.example` | `test_p0_llm_transport_258206.py::TestDefaults`; RED на базе: `defaults=[30.0, 60.0]` |
| AC-02 идемпотентная PG-миграция | `services/config_migrations.py::LLM_GUARD_MIGRATIONS` + `migrate_llm_guard_defaults` (None → seed, old → update, custom → INFO preserve, PG down → skip); вызов в `bot.main()` рядом с `migrate_context_limit_defaults` ДО `on_startup()` (создание `LLMClient`, `bot.py:465`) | `TestMigration` (7 тестов) + `test_bot_calls_migration_before_startup`; RED: `ImportError` на базе |
| AC-03 hot-apply модели/таймаута/бюджета без рестарта | `_refresh_chat_model` / `_refresh_transport_policy` на входе `generate_with_metadata`/`generate_chat`/`generate_background`/`stream_chat_completion` и `_post`; per-request `httpx.Timeout`; кэшированный httpx-клиент не пересоздаётся; in-flight snapshot; ручные/тестовые override (`backoff_base=0`, `_timeout=0.05`) сохраняются | `TestHotApply` (5 тестов, `id(client._client)` стабилен, mid-flight смена не меняет текущую попытку); RED: `payload_model=m-init`, `call_timeout_arg=None` |
| AC-04 фоллбэк и эмбеддинги — свои окна | `_post_fallback` → `LLM_FALLBACK_TIMEOUT_SECONDS` (explicit supervised timeout сохраняется); `_get_fallback_client` создаётся с fallback-таймаутом; `channel='embed'` → `min(policy, 60s)` | `TestTimeouts` (5 тестов: primary 180, fallback 60, explicit 0.7/0.9, embed 60/5) |
| AC-05 причина/метрики/логи | `LLMTimeoutError(cause_class='budget')`; `_LLM_STATS['budget_exhausted'|'read_timeouts']`; `llm_stats()` расширен; `LLM timeout`/`LLM request OK` несут provider host, model, channel, module, step, attempts n/total, elapsed_ms, effective_timeout, effective_budget, timeout_source, budget_source, reason, cause_class, request_chars, tools_count, streaming, finish_reason; без prompt/ключей | `TestObservability` (5 тестов, caplog); RED: stats keys = requests/timeouts/fallbacks/timeout_share; `cause_class='budget'` отсутствовал |
| AC-06 админка видима | `web/app.js`: группа `prov_policy` «Время ответа и защита» первой, `llm_guard` без `zone:'advanced'`/`modules`, подписи «Таймаут одного запроса, сек», «Повторов при сбое», «Предел одной основной попытки, сек», note «Весь бот… без перезапуска… не ограничивает всё исследование»; backoff/CB остаются advanced | `tools/ui_p0_llm_guard_e2e.py` (Playwright, `llm-guard-ui-e2e.json`): 1280×800 и 390×844, `prov_policy` первая, `llm_guard` видим, `details.open=false`, 3 поля видны, overflow=false; статические тесты JS/Python; RED: `prov_policy` отсутствует, `guard_zone_advanced=true` |
| AC-09 без adaptive per-model/provider | адаптивность НЕ вводилась; политика читает только объявленные ключи транспорта (структурный тест) | `TestAdminContract::test_transport_policy_reads_only_declared_keys`. Adaptation отложена до p95: данных p95 по моделям/провайдерам в этом срезе нет, сам механизм не добавлялся |

Не тронуты: модели/провайдеры/OpenCode/промпты; Summary supervisor per-call
overrides (`budget`/`max_retries`/`timeout`/`budget_reason_label`) — без
изменений; `tool_loop.py`, `checkup_service.py`, `handlers/checkup.py`,
`direct_chat_service.py` не менялись.

## RED на базе `bca18c1e` (read-only прогон)

```
defaults=[30.0, 60.0]; migration_present=false (ImportError)
stats_keys=[fallbacks, requests, timeout_share, timeouts]
client_has_refresh_model=false; client_has_refresh_policy=false
hot_model_before_call=m-init; hot_timeout_before_call=30.0
payload_model_seen=m-init; post_timeout_kwarg_seen=null
app_has_prov_policy=false; guard_zone_advanced=true; guard_timeout_label=false
```
(+ `post_budget_cause=false` — `cause_class="budget"` отсутствовал.)

## GREEN (фактические прогоны)

- `tests/test_p0_llm_transport_258206.py` — **29 passed**.
- Focused batch (новый файл + `test_llm_client`, `test_hotfix3_llm_timeout_metrics_round1025`,
  `test_hot_migration`, `test_settings_helpers`, `test_summary_param_catalog_annotation_asap41`,
  `test_summary_supervisor_asap41`, `test_summary_wave8_supervisor_runs_asap41`,
  `test_embedding_control_plane_asap4`, `test_llm_completion_metadata_ur18`,
  `test_evol013_reason_quality`, `test_speech_inspector_exact`,
  `test_webapp_f5_round1025`, `test_webapp_round1011_ui`, `test_webapp_js_unit`,
  `test_webapp_status_control`, `test_status_service`) — **532 passed**.
- Medium batch (budgets/context/cover/video/capacity/evol_source_reader/
  factcheck_resources/asap42 image capacity/speech) — **445 passed**.
- JS напрямую: `node tests/js/round1025_f5_models_test.js` → `MODELS-GROUPS-OK`;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node --check web/app.js` OK.
- Playwright: `tools/ui_p0_llm_guard_e2e.py` → `{"ok": true, "failures": []}`,
  `advancedOpen=false`, `guard.labels=[3 ожидаемых]`, `visibleFields=3`,
  `groupOrder=[prov_policy, …]`; скриншоты `llm-guard-1280x800.png`,
  `llm-guard-390x844.png`.

### Pre-existing (не регрессии; воспроизведены на базе)

- `tests/test_direct_fallback_recompose_asap32.py`: 5 failed / 3 passed — те же
  5 на `bca18c1e` (двойники `_fallback_with_retries` без `sent`).
- `tests/test_youtube_multimodal_download_round1024.py`: 18 errors на базе
  (окружение/фикстура), не связаны с транспортом.

## Конфигурация / effective-state

- Значения по умолчанию: `LLM_TIMEOUT=180.0`, `LLM_TOTAL_BUDGET=360.0`,
  `LLM_MAX_RETRIES=2`, backoff 1/8/2, `LLM_FALLBACK_TIMEOUT_SECONDS=60`.
- PG имеет приоритет над env-дефолтом (тест: env 30/60 + PG 180/360 → 180/360).
- Миграция пишет `models.llm_timeout`/`models.llm_total_budget` в категорию
  `models`; кастом не трогает; при PG down — skip (повторится на старте).
- Применение к следующему вызову без рестарта; Summary supervisor передаёт
  собственные per-call значения и не затронут.

## Ограничения / честные пробелы

- Деплой не выполнялся; live-подтверждение (journal/effective на проде,
  реальные NanoGPT-запросы) остаётся за DevOps/Reviewer.
- Playwright-стенд использует заглушки `/api/*` (без PG/бэкенда), но рендерит
  реальные `web/index.html` + `web/app.js`.
- Adaptive per-model/provider намеренно не вводился (отложено до p95-данных).
- `README.md` строка про «бюджет 30 секунд» у фоллбэка — существовавшая
  неточность вне среза (не менялась; кандидат в backlog).

## Полный прогон suite (2026-11-16, локально)

- `pytest -q` (весь `tests/`): **21378 passed, 130 failed, 41 skipped,
  25 errors** (2066 c). Ошибки/падения — не транспорта, кроме перечисленного
  ниже.
- Из 130 падений 95 воспроизводятся на базе `bca18c1e` при прогоне того же
  набора node-id (pre-existing). Остальные 34 в изолированном прогоне на
  ветке: **30 passed** (full-suite ordering/global-state, класс существующих
  order-dependent тестов; транспорт не задействуют) и **4 реальных
  catalog-baseline** — исправлены:
  - `services/param_catalog.py` переутверждён в
    `tests/test_round1025_f8_registry.py` (`PARAM_CATALOG_SHA256_FOLLOWUP`,
    DOC-ONLY: только описания трёх ключей);
  - TSV/meta переэмитированы `tools/gen_param_registry_round1025.py`
    (`plans/docs/param-registry-round1025.{tsv,meta.md}`), `--check` → OK;
  - `tests/test_round106_ia_smoke.py::test_llm_guard_fields_no_model_role`
    обновлён: срез блока до следующего `id:` вместо фиксированных 500 симв.
- Отдельно: изменённые прогоном full-suite PNG/JSON под
  `plans/features/evol/audit/evidence/` восстановлены к HEAD (артефакты
  чужих прогонов не коммитились).
