# Хотфикс-5 `hotfix5-summary-cover-window-round1025` — локальная спецификация (ретро-оформление, Шаг 8 @PM)

> **Раунд:** 10.25 (внеплановый, после hotfix4, перед F3 в пакете Волны 1). **Задачи:** T-2563…T-2572 (`tasks.md`).
> **Мастер-ТЗ:** `plans/current_task.md` (untracked — **не коммитить**, секреты не цитировать, R17/R18).
> **Тип:** backend (генерация изображений / планировщик саммари / worker-budget / наблюдаемость).
> **Статус:** ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026). Финальный код — **`412f844`** (база `b3fb6a5`, ревью `cbaec05`, `412f844`). Шаг 7 Merge — `plans/ARCHITECTURE.md` §57.2. Папка — `plans/archive/hotfix5-summary-cover-window-round1025/`. **⏳ деплой (Шаг 9 @DevOps) и live-гейт владельца — НЕ выполнены.**
> **ADR:** `adr-1025-11-summary-cover-window.md` (ретро; Шаг 2 @Architect формально не оформлялся — см. waiver-пометку в ADR).
> **Baseline (после F2, перед hotfix5):** пакет `f2328fb..`; Δ DDL = 0, Δ каталога = 0 (правки env-only + существующие ключи).
> **⚠️ Waiver:** папка/`spec.md`/ADR/tasks у hotfix5 **отсутствовали** полностью (единственный след — отчёт `plans/reports/round1025_hotfix5_scanner_audit.md`). Настоящие артефакты — **ретро-документы** Шага 8 @PM, восстановленные из кода (`412f844`), тестов и аудита. Зафиксировано как **процессный техдолг**.

## Инварианты
1. **Δ DDL = 0**; **Δ каталога = 0** — отдельный image-бюджет и все рубильники **env-only** (`ClassVar`, вне `param_catalog`); новых ключей каталога нет.
2. **Ровно одно списание** бюджета на запрос обложки; рабочий rich-путь саммари и прежние image-пути (`generate_and_send`/tool/пре-гейт с `consume_budget=True`) не ломаются.
3. Не трогать F0/F1/P0-fix/hotfix2/hotfix3/hotfix4, Эпик 2, промпт-каноны. R17: в логах — только безопасные коды/числа, без текста промпта/URL с ключом. Бэкапы/теги/`stash@{0}` не удалять.

---

## 1. Окно и ретраи генерации обложки
**Установленный корень:** verbose-путь генерации обложки ретраил при каждом сбое, а внутренний HTTP-слой (`_request_with_retry`, ≤1 повтор на 429/503) **умножался** на внешний цикл → до **4 сетевых вызовов** и до ~4×окна на один запрос; при этом док-инвариант `settings.py`/`.env.example` обещал «суммарный бюджет ≤ 2×окно = 360 c». Плюс слепой ретрай на невосстановимых классах (`bad_request`/`unauthorized`/`forbidden`/`payment_required`).

**Решение (ADR-1025-11 D1):**
- **Внешний цикл** (`services/image_generation.py::generate_image_verbose`) ограничен **≤2 попытками**, владеет повторами **только он**.
- **Внутренние ретраи отключены** на период обложки: `generate(..., retry=False)` → `_generate_post`/`_generate_get`/`_download_bytes` → `_request_with_retry(..., max_retries=0)` (при `max_retries=0` цикл `attempt < 0` не идёт). → на попытку ≤2 сетевых вызова.
- **Селективность:** повтор только на транзиентных (`is_transient_reason`: `timeout`/`network`/`unreachable`/`429`/`502`/`503`/`504`); детерминированные причины (`unauthorized`/`bad_request`/`bad_json`/`too_large`/…) → `break` после 1-й попытки.
- **Реальный дедлайн попытки:** `asyncio.wait_for(generate(...), timeout=окно)` — POST+скачивание ограничены **одним окном** → **worst-case = `attempts × окно + backoff`** (док-инвариант: 2×180+2 = **362 c**).
- `asyncio.CancelledError` (BaseException) **не глотается** `except Exception` → отмена/cleanup корректны; `tmp_path` чистится `finally`.

## 2. Отдельный image-бюджет
**Решение (ADR-1025-11 D2):**
- Метрика **`image_calls`** резолвится из **env-only** `WORKER_DAILY_IMAGE_CALLS_PER_CHAT`/`WORKER_DAILY_IMAGE_CALLS_GLOBAL` (`services/worker_budget.py`), **не** из каталога (`_resolve_limit`/каталог не зовутся); sentinel `0`/`<0` проходит через общий `budget_limits` в `consume`. `llm_calls`/`llm_tokens` — прежний каталоговый контур (изоляция подтверждена тестом `resolve.assert_not_awaited` во втором тесте). **Δ каталога = 0.**
- **Ровно одно списание:** `generate_image_verbose` вызывает `_consume_budget` **один раз**, далее `generate(..., consume_budget=False)`; счётчик инкрементится `amount=1` независимо от числа попыток. Двойного списания на попытку нет.

## 3. Наблюдаемость (R17-safe)
**Решение (ADR-1025-11 D3):**
- WARNING-логи несут только `reason` (безопасный код), `reason_class`, `provider` (**hostname**), `chat_id`, `latency_ms`; промпт/URL с ключом **не логируются**.
- `provider_label` → `_provider_from_url` (hostname, без userinfo); URL в `log_external_api` дополнительно чистится `redact_url` (срезает `user:pass@` и query).
- **Таксономия `reason_class`** уточнена явными классами (закрытие слепой зоны `empty`/`too_large`).

## 4. Планировщик: устойчивость chat_id
**Решение (ADR-1025-11 D4):** `services/summary_scheduler.py` — `int(raw_chat_id)` в `try/except (TypeError, ValueError)`; `None`/`"abc"`/`""` пропускаются с WARNING, тик **не падает**; DM-фильтр `chat_id > 0` сохранён (поведение прежнее).

## 5. Точки изменения (file:line, по аудиту)
| Область | Файлы |
|---|---|
| Окно/ретраи | `services/image_generation.py` (`generate_image_verbose` ~`:897-901`, `generate`/`_generate_post`/`_generate_get`/`_download_bytes`, `_request_with_retry` ~`:460`, `is_transient_reason`); `config/settings.py`; `.env.example` |
| Image-бюджет | `services/worker_budget.py` (~`:284-291`); `services/image_generation.py` (`_consume_budget` ~`:803`, `consume_budget=False` ~`:704,812-814`) |
| Наблюдаемость | `services/image_generation.py` (`reason_class` ~`:300-311`, `provider_label`/`_provider_from_url`, `log_external_api`) |
| Планировщик | `services/summary_scheduler.py` (~`:49-67`) |
| Тесты | `tests/test_hotfix5_summary_cover_window_round1025.py`, `tests/test_image_generation_round1023.py`, `tests/test_webapp_dm_ui.py` |

## 6. Верификация
- **Бюджет:** ровно одно списание на запрос; `image_calls` изолирован от LLM-лимита; sentinel `0`/`<0` работает.
- **Ретраи:** при первом таймауте и последующем успехе — **ровно 2 попытки**, `retry is False`; детерминированный сбой — **1 попытка**; обе «зависшие» попытки уложились в дедлайн (`wait_for`).
- **Планировщик:** строковый/`None`/пустой `chat_id` не роняет тик (WARNING); DM-фильтр сохранён.
- **R17:** логи — только коды/числа; секретов/URL с ключом нет.
- **Регресс:** полный pytest зелёный (5 предсуществующих env-падений aiogram — вне пакета); целевые (hotfix5 + `image_generation_1023` + `webapp_dm_ui`) — **87 passed** (базовый аудит) / **152 passed** по пакету; JS **24/24** (изменений JS нет — регресс-контроль); Δ DDL = 0, Δ каталога = 0; `stash@{0}` цел.

## 7. Риски и откат
| Риск | Ур. | Снятие |
|---|---|---|
| Ретрай ×2 × внутренний 429/503 → до 4 вызовов | Medium | Отключён внутренний ретрай (`max_retries=0`); селективность; **закрыт** ревью (`cbaec05`) |
| Слепой ретрай на невосстановимых классах | Low | `is_transient_reason` → `break` после 1-й попытки |
| Завышенный worst-case времени | Medium | Реальный дедлайн попытки `wait_for` → `attempts × окно + backoff` (`412f844`) |
| Двойное списание бюджета | High | `consume_budget` один раз; `amount=1` независимо от попыток |
| Тик планировщика падает на битом `chat_id` | Medium | `int()` в `try/except` + WARNING |
| Секреты/URL с ключом в логах | Critical | R17-safe поля + `redact_url` |

**Флаги/откат:** новых kill-switch не требуется; «поставка» = деплой пакетом + cache-bust `APP_VERSION`. Откат — `git revert` коммитов hotfix5 (`b3fb6a5..412f844`). **Δ DDL = 0**, **Δ каталога = 0**. Бэкапы/теги/`stash@{0}` не удалять (R18).

## 8. Ссылки
- `plans/features/hotfix5-summary-cover-window-round1025/{tasks.md, adr-1025-11-summary-cover-window.md}` (после Шага 8 — `plans/archive/hotfix5-summary-cover-window-round1025/`).
- `plans/ARCHITECTURE.md` §57.2/§57.4/§57.5; `plans/round1025-architecture.md`.
- Аудиты: `plans/reports/round1025_hotfix5_scanner_audit.md` (базовый), `plans/reports/round1025_package_scanner_audit.md` (пакетный).
