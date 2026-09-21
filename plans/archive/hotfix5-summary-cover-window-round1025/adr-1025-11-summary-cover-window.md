# ADR-1025-11 — Окно/ретраи генерации обложки, отдельный image-бюджет, наблюдаемость, int chat_id в планировщике

- **Статус:** Accepted (ретро; решения подтверждены реализацией + ревью + аудитом)
- **Дата:** 2026-09-22 (ретро-оформление Шага 8 @PM; решения приняты в ходе реализации 21.09.2026)
- **Раунд:** 10.25, внеплановый хотфикс **`hotfix5-summary-cover-window-round1025`** (T-2563…T-2573)
- **Связано:** `spec.md`; `plans/ARCHITECTURE.md` §57.2 (§56 — hotfix4), §55 (hotfix3), §53 (hotfix-медиа); ADR-1025-7 (обложка на fallback), ADR-1025-8 (per-chat стиль обложки), ADR-1023-5 (image-тул), ADR-1024-18/ADR-1025-5 (worker-budget/DB-lock паттерны)
- **Затрагивает:** `services/image_generation.py`, `services/summary_scheduler.py`, `services/worker_budget.py`, `services/summary_generator.py`, `config/settings.py`, `.env.example`, тесты (`tests/test_hotfix5_summary_cover_window_round1025.py`, `tests/test_image_generation_round1023.py`, `tests/test_webapp_dm_ui.py`)

## Waiver (процессный техдолг)
У hotfix5 **не было папки/`spec.md`/ADR/tasks** (единственный след — `plans/reports/round1025_hotfix5_scanner_audit.md`). Данный ADR — **ретро-документ** Шага 8 @PM, восстановленный из кода (`412f844`), тестов и аудита. Зафиксировано как процессный техдолг: внеплановые хотфиксы пакета должны получать хотя бы минимальные артефакты **до** деплоя.

## Контекст
Verbose-путь генерации обложки саммари (`generate_image_verbose`) ретраил сбойную генерацию **внешним** циклом (2 попытки), но под ним работал **внутренний** HTTP-ретрай `_request_with_retry` (≤1 повтор на 429/503). Итог: до **4 сетевых вызовов** и до ~4×окна времени на один запрос обложки, что противоречило доку-инварианту «суммарный бюджет ≤ 2×окно = 360 c». Дополнительно: повтор применялся и к невосстановимым классам ошибок; image-запросы учитывались в LLM-бюджетном контуре; тик планировщика мог падать на нештатном `chat_id`.

## Решение

### D1. Окно/ретраи — владелец повторов один, попытка ограничена одним окном
- Внешний цикл `generate_image_verbose` — **≤2 попытки**; **владеет повторами только он**.
- Внутренние HTTP-ретраи на период обложки **отключаются**: `generate(..., retry=False)` → `_generate_post`/`_generate_get`/`_download_bytes` → `_request_with_retry(..., max_retries=0)` (при `max_retries=0` цикл не выполняется). На попытку — ≤2 сетевых вызова.
- **Селективность:** повтор только на транзиентных (`is_transient_reason`: `timeout`/`network`/`unreachable`/`429`/`502`/`503`/`504`); детерминированные (`unauthorized`/`bad_request`/`bad_json`/`too_large`/…) → `break` после 1-й попытки.
- **Реальный дедлайн попытки:** `asyncio.wait_for(generate(...), timeout=окно)` → **worst-case = `attempts × окно + backoff`** (док-инвариант `settings.py`/`.env.example`: 2×180+2 = **362 c**).
- `asyncio.CancelledError` (BaseException) **не глотается** `except Exception` → отмена/cleanup корректны; `tmp_path` — в `finally`.

### D2. Отдельный image-бюджет (env-only), ровно одно списание
- Метрика **`image_calls`** резолвится из **env-only** `WORKER_DAILY_IMAGE_CALLS_PER_CHAT`/`_GLOBAL` (`services/worker_budget.py`); `_resolve_limit`/каталог **не зовутся**; sentinel `0`/`<0` проходит через общий `budget_limits`. `llm_calls`/`llm_tokens` — прежний каталоговый контур. **Δ каталога = 0.**
- **Ровно одно списание** на запрос обложки: `_consume_budget` вызывается один раз в `generate_image_verbose`, далее `generate(..., consume_budget=False)`; счётчик — `amount=1` независимо от числа попыток. Прежние image-пути (`generate_and_send`/tool/пре-гейт) идут с `consume_budget=True` — один spend.
- **Почему env-only:** новые каталоговые ключи дали бы Δ каталога > 0 и потребовали бы миграций; operational-лимиты фонового воркера — env-only паттерн (§55/§56).

### D3. Наблюдаемость (R17-safe) и таксономия причин
- WARNING-логи несут только `reason` (безопасный код), `reason_class`, `provider` (**hostname**), `chat_id`, `latency_ms`; промпт/URL с ключом **не логируются**.
- `provider_label` → `_provider_from_url` (hostname, без userinfo); URL в `log_external_api` дополнительно чистится `redact_url` (срезает `user:pass@` и query).
- `reason_class` расширен явными классами (полнота для `empty`/`too_large`) — наблюдаемость без раскрытия содержимого.

### D4. Планировщик — устойчивый `chat_id`
`services/summary_scheduler.py`: `int(raw_chat_id)` в `try/except (TypeError, ValueError)`; `None`/`"abc"`/`""` пропускаются с WARNING, тик **не падает**; DM-фильтр `chat_id > 0` сохранён (поведение прежнее).

### D5. Флаги/инварианты
Новых kill-switch не требуется (фон-багфикс; «поставка» = деплой пакетом + cache-bust `APP_VERSION`). Откат — `git revert` коммитов `b3fb6a5..412f844`. **Δ DDL = 0**, **Δ каталога = 0**.

## SUPERSEDE / AMEND
- **Не отменяет** ни один прежний ADR; дополняет контур генерации обложки (§55/§56) и worker-budget.
- **Не переопределяет** поведение не-verbose путей (`generate_and_send`/image-тул) — они сохраняют прежние ретраи/бюджет.

## Последствия
**Positive:** предсказуемое время запроса обложки (`attempts×окно+backoff`); нет «×4»-всплесков вызовов; изолированный image-бюджет с ровно одним списанием; R17-safe логи; устойчивый тик планировщика.
**Negative/издержки:** `is_transient_reason`-таксономия и `reason_class` требуют поддержки при добавлении новых провайдерных ошибок; grep-тест `test_webapp_dm_ui.py` вместо поведенческого (L10.25H5-3); балласт `*.zip`/бэкапов на диске (git-ignored).

## Альтернативы
| Альтернатива | Почему отклонена |
|---|---|
| Оставить оба уровня ретраев | «×4»-всплеск вызовов и времени (M10.25H5-1) |
| Считать бюджет как `(attempts)×(1+_RETRY_MAX)×timeout` в доке | Маскирует дефект вместо устранения |
| Новый каталоговый ключ image-лимита | Δ каталога > 0; operational-лимит воркера — env-only |
| Общий лимит с LLM | Смешение семантик контуров; image-запросы не должны «есть» LLM-квоту |
| Ретраить любые ошибки | Лишние запросы/backoff без шанса на успех |

## Верификация
- Ровно 2 попытки при timeout→success (`retry is False`); 1 попытка при детерминированном сбое; обе «зависшие» попытки в дедлайне.
- Ровно одно списание бюджета; `image_calls` изолирован от LLM-лимита; sentinel `0`/`<0` работает.
- Планировщик: битый/пустой/строковый `chat_id` не роняет тик; DM-фильтр сохранён.
- R17: логи — только коды/числа.
- Регресс: полный pytest зелёный (5 env-падений aiogram — вне пакета); целевые **87 passed** (базовый) / **152 passed** (пакет); JS **24/24**; `git diff --check` exit 0; `stash@{0}` цел. **Ограничение:** Playwright-матрица в среде Шага 8 не воспроизведена.

## Откат
`git revert` коммитов `b3fb6a5..412f844`. Бэкапы/теги/`stash@{0}` не удалять (R18).
