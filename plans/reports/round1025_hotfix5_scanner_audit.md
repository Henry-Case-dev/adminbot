# Scanner-аудит: hotfix5-summary-cover-window-round1025

- **Дата:** 21.09.2026, Step 6 @Scanner
- **Коммит:** `b3fb6a5` (диапазон `0e43c37..b3fb6a5`, 9 файлов, +630/−43)
- **Область:** `config/settings.py`, `services/image_generation.py`, `services/summary_generator.py`,
  `services/worker_budget.py`, `services/summary_scheduler.py`, `.env.example`, тесты
  (`test_hotfix5_summary_cover_window_round1025.py`, `test_image_generation_round1023.py`, `test_webapp_dm_ui.py`).

## Итог

**Critical 0 / High 0 / Medium 1 / Low 3 / Info 1.** Блокеров нет → **к деплою — да.**

## Medium

- **[M10.25H5-1] Ретрай умножается на внутренний 429/503-ретрай → до 4 сетевых вызовов и до ~4×окна.**
  `services/image_generation.py:810-828` (внешний цикл, 2 попытки) поверх `_request_with_retry`
  (`:423-437`, ≤1 повтор на 429/503). Сценарий: провайдер стабильно отдаёт 503 → за один запрос обложки
  уходит **4 HTTP-вызова** (подтверждено пробой: `HTTP_CALLS_ON_503 = 4`). По времени худший случай —
  `2 попытки × (2 запроса × 180 c) ≈ 720 c` на чат, тогда как комментарии settings/.env обещают
  «суммарный бюджет ≤ 2×окно = 360 c». Это фон (cron, `max_instances=1`), не блокер, но заявленный инвариант
  неточен. **Фикс:** либо считать бюджет как `(attempts) × (1 + _RETRY_MAX) × timeout` в доке, либо не делать
  внешний ретрай на `rate_limited`/`bad_gateway`/`unavailable` (их уже покрывает внутренний).

## Low

- **[L10.25H5-1] `reason_class` не покрывает `empty`/`too_large`/`empty_prompt`/`temp_write_failed` →
  класс `error`.** `services/image_generation.py:300-311`. Таксономия в докстринге заявляет `bad_json`, но
  `empty` (пустой ответ провайдера) и `too_large` попадают в безликое `error`; `no_image` наоборот отнесён к
  `bad_json`. Наблюдаемость страдает, логика не затронута. **Фикс:** добавить `empty`/`too_large` в явные классы.

- **[L10.25H5-2] Слепой ретрай на невосстановимые HTTP-классы.** `services/image_generation.py:810-828`:
  `bad_request`/`unauthorized`/`forbidden`/`payment_required` повторяются второй раз без шанса на успех
  (лишний запрос + backoff 2 c). **Фикс:** ретраить только `timeout`/`rate_limited`/`bad_gateway`/`unavailable`/`bad_json`.

- **[L10.25H5-3] Тест-качество: поведение планировщика проверяется grep'ом исходника.**
  `tests/test_webapp_dm_ui.py:124-131` после правки проверяет наличие подстрок `chat_id = int(raw_chat_id)`/`if chat_id > 0`
  в тексте файла — рефакторинг без смены семантики уронит/обманет тест. Поведенческие тесты в
  `test_hotfix5...py` (класс C) полноценные; этот — дублирующий и хрупкий. **Фикс:** оставить поведенческий,
  grep убрать.

## Info

- **Корневые `*.zip` (404/150/533 МБ) и `backups/pre-round1025-hotfix5-src.zip`.** git-ignored, в индекс/коммит
  не входят (`git ls-files "*.zip"` пуст, `git status` чист). Претензий к деплою нет, но это балласт на диске.

## Верифицировано чисто

- **Бюджет — ровно одно списание.** `generate_image_verbose` вызывает `_consume_budget` **один раз** (`:803`),
  дальше `generate(..., consume_budget=False)` (`:704`, `:812-814`). Двойного списания на попытку нет;
  `generate_and_send`/tool/пре-гейт идут прежним путём с `consume_budget=True` — один spend. Счётчик
  инкрементится `amount=1` независимо от числа попыток.
- **Отдельная ветка `image_calls` не обходится и не ломает другие метрики.** `worker_budget.py:284-291`:
  `image_calls` резолвится из env-only `WORKER_DAILY_IMAGE_CALLS_PER_CHAT/GLOBAL`, `_resolve_limit`/каталог не
  зовутся; sentinel `0`/`<0` проходит через общий `budget_limits` в `consume`. `llm_calls`/`llm_tokens` — прежний
  каталоговый контур (тест `resolve.assert_not_awaited` подтверждает изоляцию). Δ каталога = 0.
- **R17/безопасность.** WARNING-логи несут только `reason` (безопасный код), `reason_class`, `provider` (hostname),
  `chat_id`, `latency_ms`; промпта/URL с ключом нет. `provider_label` → `_provider_from_url` (`hostname`, без
  userinfo). URL в `log_external_api` дополнительно чистится `redact_url` (срезает `user:pass@` и query).
- **Планировщик.** `summary_scheduler.py:49-67`: `int(raw_chat_id)` в `try/except (TypeError, ValueError)` —
  `None`/`"abc"`/`""` пропускаются с WARNING, тик не падает; DM-фильтр `chat_id > 0` сохранён (поведение прежнее).
- **Регрессии.** Полный `pytest` зелёный; `probe`-таймаут не тронут (`IMAGE_REQUEST_TIMEOUT_SECONDS=90` —
  `probe`/`generate` default; 180 c только у verbose-обложки). `CancelledError` (BaseException) не ловится
  `except Exception` в `generate`/`_deliver_rich` — отмена проходит, `tmp_path` чистится `finally`.
- **Новые тесты не тавтологичны и падают без фикса.** Импорт `reason_class`/`provider_label` и kwarg `timeout`
  отсутствовали в старом коде; `test_timeout_maps_to_timeout_reason` (старо → `reason="error"`),
  `test_string_chat_id_cast_to_int` (старо → строка `"-100"`), `test_image_limit_is_separate_from_llm`
  (старо → реюз LLM-лимита) — все ловят регресс. `test_mapping`/`test_env_only_defaults` — контрактные, не тавтологичны.

## Прогоны (факт)

- `python -m pytest -q` → **8124 passed, 1 warning** (Starlette deprecation), 113.19 s.
- Целевые (`hotfix5` + `test_image_generation_round1023` + `test_webapp_dm_ui`) → **87 passed**, 4.06 s.
- `tests/js/*` через `node` → **24/24 файлов OK** (JS-изменений в коммите нет — регресс-контроль).

## Инварианты

- Δ DDL = 0 (`migrate_history/`, `*.sql`, `docker/` не менялись).
- Δ каталога = 0 (`services/param_catalog.py` не в диффе; `test_new_keys_not_in_param_catalog` подтверждает).
- `stash@{0}` (`wip(f1): IA v2…`) цел. Трекаемых zip нет. Секретов в диффе нет.

## Вердикт

**К деплою — да.** Critical/High отсутствуют; Medium — точность заявленного ретрай-бюджета (не блокирует,
можно закрыть follow-up'ом). Low — наблюдаемость/тест-гигиена.
