# Хотфикс-5 — `hotfix5-summary-cover-window-round1025` (внеплановый, после hotfix4, перед F3; пакет Волны 1)

> **Триггер:** при разборе Волны 1 (F2 + F3) выявлен дефект verbose-пути генерации обложки: внешний ретрай ×2 умножался на внутренний HTTP-ретрай (429/503) → до 4 сетевых вызовов и до ~4×окна на чат; слепой ретрай на невосстановимых классах; image-лимит смешивался с LLM-лимитом; тик планировщика мог падать на битом `chat_id`.
> **Тип:** backend (генерация изображений / планировщик саммари / worker-budget / наблюдаемость). **Приоритет:** P1 (фон, cron `max_instances=1`; не блокер).
> **Зависит от:** F2 (ступень `web/**` не задействована) + hotfix4 (`f2328fb`). **Задачи:** **T-2563…T-2573 (11)** — ретро-нумерация Шага 8 @PM (продолжает F2 T-2529…T-2562; далее F3 T-2574…T-2580; дублей нет).
> **Статус:** ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026).** Коммиты: база `b3fb6a5` → ревью `cbaec05` → финал **`412f844`**. Шаг 7 Merge — `plans/ARCHITECTURE.md` §57.2. Папка — `plans/archive/hotfix5-summary-cover-window-round1025/`.
> **⚠️ Waiver:** у hotfix5 **не было** папки/spec/ADR/tasks — единственный след `plans/reports/round1025_hotfix5_scanner_audit.md`. Артефакты ниже — **ретро-документы** Шага 8 (восстановлены из кода/тестов/аудита). Процессный техдолг.
> **Инварианты:** Δ DDL = 0; Δ каталога = 0 (всё env-only `ClassVar`); **ровно одно списание** бюджета на запрос; рабочий rich-путь и прежние image-пути не ломать; R17 (в логах — только коды/числа); бэкапы/теги/`stash@{0}` не удалять.

## Установленные причины (данность, НЕ перепроверять)
- **Ретрай ×2 × внутренний 429/503:** `services/image_generation.py` — внешний цикл (2 попытки) поверх `_request_with_retry` (≤1 повтор на 429/503) → до **4 HTTP-вызовов** за один запрос обложки; worst-case по времени противоречил доку «≤2×окно=360 c».
- **Слепой ретрай:** невосстановимые классы (`bad_request`/`unauthorized`/`forbidden`/`payment_required`) повторялись второй раз без шанса на успех.
- **Смешение бюджетов:** image-запросы считались в LLM-контуре вместо отдельного `image_calls`.
- **Планировщик:** незащищённый `int(raw_chat_id)`.

---

## 0. Точка отката и baseline (ретро)
- [x] **T-2563** [@DevOps] — **Точка отката hotfix5 + фиксация baseline (ретро).** Тег/бэкап области (`services/image_generation.py`, `services/summary_scheduler.py`, `services/worker_budget.py`, `config/settings.py`, `.env.example`); baseline — пакет `f2328fb..`, pytest базы 8041/0, JS 23/23, matrix 0, APP_VERSION 2.58.4 предшествует F2. Секреты не печатать; zip/`.env`/`current_task.md` в git не добавлять (R18).
  **Готово, когда:** точка отката зафиксирована, возврат возможен. — ✅ **выполнено (`b3fb6a5`).**

## 1. [P1] Окно/ретраи генерации обложки
- [x] **T-2564** [@Builder] — **Окно/ретраи `generate_image_verbose`.** ≤2 попытки; владелец повторов — внешний цикл; каждая попытка ограничена `asyncio.wait_for(generate(...), timeout=окно)`; `asyncio.CancelledError` не глотается; `tmp_path` чистится `finally`. `services/image_generation.py`; `.env.example`/`config/settings.py` (док-инвариант `attempts×окно+backoff`).
  **Готово, когда:** worst-case = `attempts×окно+backoff`; отмена/cleanup корректны. — ✅ **выполнено (`b3fb6a5`, финал `412f844`).**
- [x] **T-2565** [@Builder] — **Отключение дубля внутренних ретраев + селективность.** `generate(..., retry=False)` → `_request_with_retry(max_retries=0)` на период обложки; повтор только на `timeout`/`network`/`unreachable`/`429`/`502`/`503`/`504`; детерминированные → `break` после 1-й попытки (`is_transient_reason`).
  **Готово, когда:** на попытку ≤2 сетевых вызова; невосстановимые классы не повторяются. — ✅ **выполнено (`cbaec05`).**

## 2. [P1] Отдельный image-бюджет
- [x] **T-2566** [@Builder] — **Отдельный `image_calls`-бюджет (env-only).** `services/worker_budget.py` — резолв из `WORKER_DAILY_IMAGE_CALLS_PER_CHAT`/`_GLOBAL`, каталог не зовётся (`resolve` не awaited); sentinel `0`/`<0` через общий `budget_limits`; **ровно одно списание** (`_consume_budget` один раз в `generate_image_verbose`, далее `consume_budget=False`; `amount=1` независимо от числа попыток).
  **Готово, когда:** двойного списания нет; LLM-контур изолирован; Δ каталога = 0. — ✅ **выполнено (`cbaec05`).**

## 3. [P1] Наблюдаемость (R17-safe)
- [x] **T-2567** [@Builder] — **R17-safe логи + таксономия причин.** WARNING несёт только `reason`/`reason_class`/`provider`(hostname)/`chat_id`/`latency_ms`; `provider_label` → `_provider_from_url` (hostname, без userinfo); URL чистится `redact_url`; `reason_class` расширен явными классами (полнота для `empty`/`too_large`).
  **Готово, когда:** промпт/URL с ключом не логируются; причины классифицированы. — ✅ **выполнено (`cbaec05`).**

## 4. [P1] Планировщик
- [x] **T-2568** [@Builder] — **Устойчивость `chat_id` в планировщике.** `services/summary_scheduler.py` — `int(raw_chat_id)` в `try/except (TypeError, ValueError)`, невалидные пропускаются с WARNING, тик не падает; DM-фильтр `chat_id > 0` сохранён.
  **Готово, когда:** битый/пустой `chat_id` не роняет тик. — ✅ **выполнено (`b3fb6a5`).**

## 5. [P1] Ревью-фиксы и регресс-тесты
- [x] **T-2569** [@Builder] — **Поведенческие регресс-тесты.** `tests/test_hotfix5_summary_cover_window_round1025.py` (+правки `test_image_generation_round1023.py`, `test_webapp_dm_ui.py`): ровно 2 попытки при timeout→success (`retry is False`), 1 попытка при детерминированном сбое, обе «зависшие» попытки в дедлайне (`attempt_bounded_by_window_deadline`), строковый `chat_id` → int, image-лимит отделён от LLM-лимита. Тесты **падают на старом коде**.
  **Готово, когда:** тесты зелёные, red→green доказан. — ✅ **выполнено (`cbaec05`/`412f844`).**
- [x] **T-2570** [@Builder] — **Ревью-фиксы iter1/iter2 + полный регресс.** Ревью iter1 (`cbaec05`): селективный ретрай, global image-бюджет, отключение дубля ретраев, таксономия причин, поведенческий тест планировщика. Ревью iter2 (`412f844`): реальный дедлайн попытки (`wait_for`), worst-case = `attempts×окно+backoff`. Регресс: полный pytest зелёный (5 env-падений aiogram — вне пакета), целевые **87 passed**, JS **24/24**, `git diff --check` exit 0, `stash@{0}` цел.
  **Готово, когда:** все показатели подтверждены. — ✅ **выполнено.**

## 6. [P1] Ревью / аудит
- [x] **T-2571** [@Reviewer/@Scanner] — **Ревью/аудит.** @Reviewer **Approved**; @Scanner **Critical 0 / High 0** — базовый `plans/reports/round1025_hotfix5_scanner_audit.md` (**M10.25H5-1** «ретрай × внутренний 429/503 → до 4 вызовов» — **закрыт** ревью `cbaec05`; Low L10.25H5-1…-3, Info — техдолг/не блокеры) + **пакетный** `plans/reports/round1025_package_scanner_audit.md` (C0/H0, «к деплою ДА»: бюджет = ровно одно списание, R17-логи, планировщик, `CancelledError` не глотается).
  **Готово, когда:** вердикты зафиксированы отчётом. — ✅ **выполнено 22.09.2026.**

## 7. [P1] Деплой / live-гейт / архив
- [ ] **T-2572** [@DevOps] — **Деплой пакетом (Шаг 9) + live-гейт владельца.** ⏳ **НЕ выполнено.** Атомарные русские conventional commits (код+тесты) → push `origin/master` → прод `git pull --ff-only` → `systemctl restart admin_bot` → `/api/health` 200; `APP_VERSION` — по итогу пакета **2.58.6**. **Live-гейт владельца (post-deploy):** обложка саммари генерируется в пределах окна без «×4»-всплесков; WARNING-логи несут только `reason`/`reason_class`/`provider`(host)/`chat_id`/`latency_ms` (без промпта/URL с ключом); `image_calls` — отдельный счётчик; тик планировщика не падает на битом `chat_id`; регрессии F0/F1/hotfix = 0; `database is locked` = 0.
  **Готово, когда:** прод обновлён, health 200; live-доказательства по каждому пункту. — ⏳ **ожидает Шаг 9 + владельца.**
- [x] **T-2573** [@PM] — **Архивация (Шаг 8).** ✅ **Выполнено 22.09.2026:** папка создана (ретро-оформление — `spec.md` + **ADR-1025-11** + `tasks.md`) и перенесена → `plans/archive/hotfix5-summary-cover-window-round1025/`; `plans/backlog.md` обновлён; бэкапы/теги/`stash@{0}` не удалялись (R18).

---

## Feature flags / раскатка
- Поэтапная раскатка internal → 10% → 50% → 100% **не требуется** (пет-проект, один прод; прецедент §53/§54.1/§55/§56). «Поставка» = деплой пакетом + cache-bust `APP_VERSION`.
- Все рубильники — **env-only** (`WORKER_DAILY_IMAGE_CALLS_PER_CHAT`/`_GLOBAL`); **Δ каталога = 0**; **Δ DDL = 0**. Откат — `git revert` коммитов `b3fb6a5..412f844`.

## Риски
- Смешение image- и LLM-бюджета (**High**): T-2566 — отдельный резолв + изоляция.
- Завышенный worst-case (**Medium**): T-2564 — реальный дедлайн попытки.
- Секреты/URL с ключом в логах (**Critical**): T-2567 — R17-safe поля + `redact_url`.
- Падение тика планировщика (**Medium**): T-2568 — `try/except`.
