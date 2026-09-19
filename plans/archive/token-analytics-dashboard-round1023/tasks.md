# Задачи: token-analytics-dashboard-round1023

> **Раунд 10.23** · Приоритет **P1** · Шаг 1 @PM (+ Step 2 @Architect: `spec.md` + **ADR-1023-7**) · Тип: backend (DDL/telemetry) + UI (dashboard)
> **ТЗ:** `plans/current_task.md`, «Рефакторинг UI и Аналитика (Мини-апп) → 1. Сводка (Token Metrics Dashboard)». Untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** — (backend независим); UI-ступень после F5.

## Цель
Прозрачно репортить расходы токенов: в БД писать `module`, `step`, `input_tokens`, `output_tokens`, `cost_usd`, `timestamp`. На дашборде — визуальное дерево (Flow node) последнего вызова `[Слой 1: 4000 т.] -> [Слой 2: 600 т.] -> Итого: $0.002` и графики за день/неделю/месяц.

## Контекст / что уже есть
- Токены/usage: `services/token_counter.py`, `services/chat_usage.py` (PG), `services/worker_budget.py`, запись usage в `services/llm_client.py:446` `_record_global_usage` (`:890`/`:1062`), фактический usage из ответа — `:701-714`.
- **Записывается только `source='global'`**; разбивки по module/step/cost **нет**. **Таблицы цен (cost_usd) нет.**
- Каркас mini-app: `web/app.js`, `web/index.html`; API — `web/api/routes.py` (и др.).
- DDL PG: `services/pg_db.py` (идемпотентно); таблица `chat_usage` — `:181`.
- Stage-1/Stage-2/tool-loop: `services/system2_handoff.py`, `services/tool_loop.py` — нужен сквозной correlation-id.

## Задачи
- [x] **T-2157** [@Architect] ADR-1023-7: схема DDL (`llm_usage_events`: module/step/input_tokens/output_tokens/cost_usd/timestamp/correlation_id + существующий scope), таблица цен моделей, контракт сквозного correlation-id через Stage-1/Stage-2/tool-loop, расширение `source` (сейчас только `'global'`), идемпотентность миграций, ретенция, эндпоинты дашборда, откат. Создать `spec.md` + `ADR-1023-7.md`.
- [x] **T-2158** [@Builder] Идемпотентная DDL-миграция новой таблицы usage-events + таблицы цен (`services/pg_db.py`/`services/config_migrations.py`); сид базовых цен (idempotent, `ON CONFLICT DO NOTHING`).
- [x] **T-2159** [@Builder] Обогащённая запись usage (`module`/`step`/`input_tokens`/`output_tokens`/`cost_usd`/`timestamp`) в `services/llm_client.py` + `services/chat_usage.py`; не сломать существующий бюджетный учёт (`source='global'`).
- [x] **T-2160** [@Builder] Сквозной correlation-id через Stage-1 → Stage-2 → tool-loop (`services/tool_loop.py`, оркестраторы) — kwargs-проброс `оркестратор → llm.generate/generate_chat`; `services/system2_handoff.py` — **no-op** (нет LLM-вызовов, id не поле JSON).
- [x] **T-2161** [@Builder] Резолв цены модели и расчёт `cost_usd` (fail-safe при отсутствии цены → 0/флаг «unknown»); модуль расчёта с тестами.
- [x] **T-2162** [@Builder] API дашборда: flow-node последнего вызова + агрегаты день/неделя/месяц (в `web/api/routes.py` или новый router); RBAC/скоуп.
- [x] **T-2163** [@Builder] UI дашборда: визуальное дерево последнего вызова + графики день/неделя/месяц (`web/app.js`, `web/index.html`; структура меню не меняется — tma-menu-freeze).
- [x] **T-2164** [@Builder] Тесты: идемпотентность DDL, расчёт cost, связка correlation-id (1→2→tool), агрегаты API, отсутствие секретов в payload.
- [x] **T-2165** [@Builder] Регресс: бюджет `chat_usage`/`worker_budget` не сломан; `node --check web/app.js`; полный pytest 0 failed.
- [ ] **T-2166** [@DevOps] Деплой + живая приёмка: дашборд показывает дерево последнего вызова и графики; отчёт (R17/R18).

## Критерии приёмки
- В БД пишутся module/step/input/output/cost/timestamp; старый учёт сохраняется.
- correlation-id связывает Stage-1/Stage-2/tool-loop в дерево; на дашборде — flow-node последнего вызова.
- Графики день/неделя/месяц работают; структура меню не изменена.
- Полный pytest — 0 failed.

## Риски
- **R1 (High):** новый DDL/расширение `source` ломает бюджетный учёт → изолированная аддитивная таблица + регресс (T-2158/T-2159/T-2165).
- **R2 (Medium):** нет цен для части моделей → fail-safe расчёт + метка «unknown» (T-2161).
- **R3 (Medium):** correlation-id теряется в tool-loop → сквозной тест цепочки (T-2160/T-2164).
- **R4 (Medium):** UI-изменение задевает freeze-меню → tma-menu-freeze + generic-рендер (T-2163).
- **R5 (R17/R18):** секреты в payload/логах.

## Зависимости / ступени вливания
- **Backend независим** — может идти параллельно канон-цепочке (F3/F4/F6), но `services/system2_handoff.py` общий с F3: **F3 раньше, F7 читает** (порядок полей согласовать; если F3 не влита — correlation-id в Stage-2 добавлять после неё).
- `web/app.js`/`web/index.html` — **ступень F5 → F7 → F8**.
- Требует `spec.md` + `ADR-1023-7` (Step 2 @Architect).

## Feature flag / раскатка
- `TOKEN_ANALYTICS_ENABLED` — env-only `ClassVar` (**default ON**, Δ каталога = 0): OFF → запись/дашборд выключены, прежний учёт сохраняется. Раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert` + DDL-retention (таблица безопасно удаляется).
