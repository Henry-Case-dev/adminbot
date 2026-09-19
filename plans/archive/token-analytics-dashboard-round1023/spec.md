# spec.md — F7 `token-analytics-dashboard-round1023`

> **Раунд 10.23** · Приоритет **P1** · Шаг 2 @Architect (часть 2/3) · Тип: backend (DDL/telemetry) + UI (dashboard)
> **ADR:** `ADR-1023-7.md` (Accepted). **Задачи:** `tasks.md` (T-2157…T-2166).
> **ТЗ:** `plans/current_task.md`, «Рефакторинг UI и Аналитика (Мини-апп) → 1. Сводка (Token Metrics Dashboard)» (untracked; секреты не цитируем — R17/R18).
> **Сквозной архитектурный документ:** `plans/features/round1023-architecture.md` (§1 F7, §3.4 DDL, §5 ступени, §8).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** backend независим; `services/system2_handoff.py` общий с F3 → **F3 раньше, F7 добавляет аддитивно**; UI-ступень после F5 (`web/**`: F5 → **F7** → F8 → F9).

---

## 0. Контекст и факты аудита кода + важное уточнение БД

| Факт | Точка в коде |
|---|---|
| Токены/usage: реальные значения из API-ответа | `services/llm_client.py:704-715` (`usage.prompt_tokens`/`completion_tokens` — только логируются) |
| Запись бюджета (PG, `source='global'`) | `services/llm_client.py:446` `_record_global_usage` → `services/chat_usage.py:266` `report_call` |
| Оценка токенов (fallback) | `services/token_counter.py:63` `count_tokens`, `chat_usage.estimate_tokens` (len/4) |
| Бюджет фона | `services/worker_budget.py:196` `consume` |
| Каркас мини-аппа и API | `web/app.js`, `web/index.html`, `web/api/routes.py`, `web/api/gates.py:152` (`/api/workers/budget` — образец RBAC/чтения) |
| Чтение дашбордов из PG | `web/api/gates.py:161` `worker_budget.get_day_summary(cache.pg)`; `web/api/routes.py:680` `chat_usage.key_status(cache.pg)` |
| Идемпотентный PG-DDL | `services/pg_db.py:33` `DDL_STATEMENTS`, выполняется в `init()` |
| Stage-1/Stage-2/tool-loop | `services/system2_handoff.py`, `services/tool_loop.py:89`, оркестраторы (`factcheck_service`, `direct_chat_service`, `summary_generator`) |

### 0.1. Ключевое уточнение: DDL идёт в **PostgreSQL**, не в SQLite (AMEND к Part 1 §3.4)

Предварительная формулировка `round1023-architecture.md` §3.4 допускала «SQLite v12→v13». По факту кода:
- **запись** usage идёт через `chat_usage`/`worker_budget` — **PG** (asyncpg; `llm_client._record_global_usage` → `hot.get_config_cache().pg`);
- **чтение** дашбордов в `web/api/*` — **только `cache.pg`**; доступа к SQLite у web-API нет.

Поэтому таблицы `llm_usage_events` и `llm_model_prices` создаются в **PG** (`services/pg_db.py`). **Δ SQLite DDL = 0** (user_version остаётся **v12**). Это совпадает с PM-задачей T-2158 (`pg_db.py`/`config_migrations.py`) и фиксируется в **ADR-1023-7 §Amend**. Part 1 сам оговорил: «Точные Δ/DDL F4–F9 фиксируются в Part 2/3».

> F9 — идемпотентная **PG**-миграция Справки v4→v5, с SQLite не конфликтует.

---

## 1. Цель

Прозрачно репортить расходы токенов: писать в PG `module`, `step`, `input_tokens`, `output_tokens`, `cost_usd`, `timestamp` и сквозной `correlation_id`. На дашборде — визуальное дерево (Flow node) последнего вызова (`[Слой 1: 4000 т.] → [Слой 2: 600 т.] → Итого: $0.002`) и графики за день/неделю/месяц. Старый бюджетный учёт (`chat_usage`/`worker_budget`, `source='global'`) сохраняется без изменений.

---

## 2. Требуемое поведение

### 2.1. Обогащённая запись usage

- После каждого LLM-вызова (Stage-1/Stage-2/tool-раунд/одиночный) при `TOKEN_ANALYTICS_ENABLED` пишется строка в `llm_usage_events`.
- **Реальные** `input_tokens`/`output_tokens` берутся из `usage` API-ответа (`prompt_tokens`/`completion_tokens`); при отсутствии usage — оценка `token_counter.count_tokens` (fallback len·0.3) и пометка `tokens_estimated=true`.
- Существующий `chat_usage.report_call` (бюджет) **не меняет** семантику: по-прежнему пишет только `source='global'`, fail-open.
- Всё — fail-open: ошибка аналитики не влияет на ответ пользователю.

### 2.2. Сквозной correlation-id

- Новый помощник: `services/usage_events.py::new_correlation_id() -> str` (UUID4 hex).
- Оркестратор создаёт **один** `correlation_id` на ответ пользователя и передаёт его:
  - Stage-1 (`llm.generate_chat(..., correlation_id=..., module=..., step="stage1")`),
  - каждый tool-раунд внутри Stage-1 (`tool_loop.chat_with_tools(..., correlation_id=...)` → `step="tool"`, + имя тула),
  - Stage-2 (`step="stage2"`),
  - генерация изображения F5 (`step="image"`).
- `llm_client.generate`/`generate_chat` получают **опциональные** kwargs `module`, `step`, `correlation_id` (default `None` → генерируется внутренний id, чтобы одиночные вызовы тоже логировались). Полная обратная совместимость.
- `tool_loop.chat_with_tools` получает опциональный `correlation_id` и прокидывает его в каждый `llm.generate_chat`.
- `services/system2_handoff.py` — **no-op по коду** (ступень **F3 → F6 → F7**): `correlation_id` не является полем Stage-1 JSON и пробрасывается kwargs-ами `llm.generate/generate_chat`/`tool_loop.chat_with_tools`; поля/контракт F3/F6 (`response_mode`, `cover_prompt` и др.) **не трогаются**.

### 2.3. Расчёт `cost_usd`

- Новый модуль `services/llm_pricing.py`:
  - `async def resolve_price(pg, model) -> tuple[float, float] | None` — читает `llm_model_prices` (in-process кэш + TTL/invalidate);
  - `def compute_cost(price, input_tokens, output_tokens) -> tuple[float, bool]` — `cost = input/1e6*in_price + output/1e6*out_price`; `known=False` при отсутствии цены.
- **Fail-safe:** модель без цены → `cost_usd=0`, `price_known=false` (не падаем, не выдумываем цену).
- Таблица цен редактируется без каталога (PG + опциональный admin-API). Δ каталога = 0.

### 2.4. Расширение `source`

- Поле `source` в `llm_usage_events` (не в `chat_usage`!) принимает `'global' | 'chat' | 'byok' | 'worker' | 'image'`. Значение `'global'` остаётся каноном для бюджетного контура.
- Существующее поведение `_record_global_usage` (`source != 'global'` → бюджет не тратится) **сохраняется**; аналитика пишет событие для любого source.

### 2.5. DDL (PG)

**`llm_usage_events`:**

| Колонка | Тип | Смысл |
|---|---|---|
| `id` | `BIGSERIAL PRIMARY KEY` | |
| `ts` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | timestamp |
| `correlation_id` | `TEXT NOT NULL` | сквозной id ответа |
| `module` | `TEXT NOT NULL` | `direct_chat`/`factcheck`/`summary`/`search`/`image`/… |
| `step` | `TEXT NOT NULL` | `stage1`/`stage2`/`tool`/`single`/`image` |
| `tool_name` | `TEXT NOT NULL DEFAULT ''` | для `step='tool'` |
| `source` | `TEXT NOT NULL DEFAULT 'global'` | см. §2.4 |
| `chat_id` | `BIGINT` | scope (nullable) |
| `model` | `TEXT NOT NULL DEFAULT ''` | id модели |
| `input_tokens` | `BIGINT NOT NULL DEFAULT 0` | |
| `output_tokens` | `BIGINT NOT NULL DEFAULT 0` | |
| `tokens_estimated` | `BOOLEAN NOT NULL DEFAULT false` | оценка vs реальные |
| `cost_usd` | `NUMERIC(12,6) NOT NULL DEFAULT 0` | |
| `price_known` | `BOOLEAN NOT NULL DEFAULT true` | false = цены нет |

Индексы: `idx_llm_usage_events_ts (ts DESC)`, `idx_llm_usage_events_corr (correlation_id)`, `idx_llm_usage_events_module_ts (module, ts DESC)`.

**`llm_model_prices`:**

| Колонка | Тип |
|---|---|
| `model` | `TEXT PRIMARY KEY` |
| `input_usd_per_1m` | `NUMERIC(12,6) NOT NULL` |
| `output_usd_per_1m` | `NUMERIC(12,6) NOT NULL` |
| `currency` | `TEXT NOT NULL DEFAULT 'USD'` |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |

Идемпотентный сид базовых цен (`INSERT ... ON CONFLICT (model) DO NOTHING`); значения — стартовые, владелец уточняет (цены меняются). `NUMERIC` — R17: только числа.

### 2.6. Ретенция

- `TOKEN_ANALYTICS_RETENTION_DAYS` (env-only `ClassVar`, default 90; Δ каталога = 0).
- Точечная очистка `DELETE FROM llm_usage_events WHERE ts < now() - interval` — opportunistic (при записи/по таймеру, с дедупом), fail-open.

### 2.7. API дашборда (R16-аддитивно, RBAC глобального админа)

Образец RBAC/чтения — `web/api/gates.py:152` (`/api/workers/budget`).

- `GET /api/analytics/usage/latest` → последний `correlation_id` и все его события по `ts`:
```json
{
  "correlation_id": "…", "ts": "…",
  "steps": [
    {"module":"direct_chat","step":"stage1","tool_name":"","model":"…",
     "input_tokens":4000,"output_tokens":600,"cost_usd":0.0007,
     "price_known":true,"tokens_estimated":false},
    {"module":"direct_chat","step":"tool","tool_name":"query_chat_memory", "…":"…"}
  ],
  "total": {"input_tokens":4600,"output_tokens":600,"cost_usd":0.002}
}
```
- `GET /api/analytics/usage/summary?period=day|week|month` → `{period, since, totals, by_module:[…], series:[{bucket, cost_usd, input_tokens, output_tokens}]}` (day → часовые бакеты, week/month → дневные).
- `GET /api/analytics/prices` + `PUT /api/analytics/prices` (обслуживание цен, admin-only) — опционально.
- `TOKEN_ANALYTICS_ENABLED=OFF` → эндпоинты возвращают пустой/shape-совместимый ответ без ошибок.

### 2.8. UI

- Блок «Сводка (Token Metrics Dashboard)»: Flow-node последнего вызова + графики день/неделя/месяц.
- Размещение — в существующем разделе «Сводка»/спец-экране (persona-прецедент special-screen); **структура меню не меняется** (`tma-menu-freeze`), `node --check web/app.js` зелёный.

---

## 3. Изменения по файлам

| Файл | Тип изменения |
|---|---|
| `services/usage_events.py` | **новый**: `new_correlation_id`, `record(...)`, ретенция |
| `services/llm_pricing.py` | **новый**: резолв цен + `compute_cost` (fail-safe) |
| `services/pg_db.py` | аддитивно: DDL `llm_usage_events` + `llm_model_prices` + индексы + сид цен |
| `services/llm_client.py` | аддитивно: захват реального `usage`, опц. kwargs `module/step/correlation_id`, вызов `usage_events.record` (бюджет — без изменений) |
| `services/tool_loop.py` | аддитивно: опц. `correlation_id` в `chat_with_tools` → проброс в каждый раунд |
| `services/system2_handoff.py` | **no-op по коду** (review iter1): модуль не делает LLM-вызовов, `correlation_id` — не поле Stage-1 JSON; id идёт kwargs-ами `оркестратор → llm.generate/generate_chat`. Поля F3 не трогаются |
| `services/{factcheck_service,direct_chat_service,summary_generator}.py` | аддитивно: создание `correlation_id` на ответ + передача в Stage-1/2 |
| `web/api/routes.py` / новый router | эндпоинты аналитики (R16-аддитивно) |
| `web/index.html` / `web/app.js` | ступень F5→**F7**→F8: блок дашборда (generic-рендер; меню не меняется) |
| `config/settings.py` | `TOKEN_ANALYTICS_ENABLED`, `TOKEN_ANALYTICS_RETENTION_DAYS` (env ClassVar) |
| `services/chat_usage.py` / `services/worker_budget.py` | **НЕ** меняются (регресс-инвариант бюджетного учёта) |

---

## 4. Контракты/схемы БД, Δ DDL

- **PG:** +2 таблицы (`llm_usage_events`, `llm_model_prices`) + 3 индекса + сид цен.
- **SQLite:** Δ = **0** (user_version остаётся **v12**) — AMEND к Part 1 §3.4 (см. §0.1, ADR-1023-7).
- **Каталог:** Δ = **0**.
- Идемпотентность: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, сид `ON CONFLICT DO NOTHING`.
- Откат: `DROP TABLE IF EXISTS llm_usage_events, llm_model_prices` безопасен (телеметрия).

---

## 5. Канон / промпты

- F7 **не меняет** промпт-константы. Канон-контур (F1→F2→F3→F4→F6) не затрагивается; правка `system2_handoff.py` — только метаданные (`correlation_id`), не тексты промптов.

---

## 6. План тестирования

1. **Идемпотентность DDL:** повторный `init()` — no-op; таблицы/индексы не дублируются.
2. **Расчёт cost:** известная цена → точный `cost_usd`; неизвестная модель → `0` + `price_known=false`.
3. **Связка correlation-id:** один id у Stage-1 → tool-раундов → Stage-2; дерево восстанавливается по `correlation_id`.
4. **Агрегаты API:** day/week/month бакеты; `by_module`; пустой ответ при OFF.
5. **Бюджет не сломан:** `chat_usage.report_call`/`worker_budget.consume` ведут себя как раньше; `source='global'` — канон.
6. **Usage из ответа:** реальные `prompt_tokens`/`completion_tokens` пишутся; при отсутствии — оценка + `tokens_estimated=true`.
7. **Fail-open:** ошибка аналитики не влияет на ответ; PG down → событие пропущено, бот жив.
8. **R17/R18:** payload/логи без секретов и без сырых промптов; только коды/числа.
9. **UI-гейты:** `node --check web/app.js`; структура меню (tma-menu-freeze) не изменена.
10. **Регресс:** полный pytest **0 failed**.

---

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Новый DDL/расширение `source` ломает бюджетный учёт | Изолированные аддитивные таблицы; бюджет не трогаем; регресс (T-2158/T-2159/T-2165) |
| R2 | Medium | Нет цен для части моделей | Fail-safe расчёт + `price_known=false` |
| R3 | Medium | correlation-id теряется в tool-loop | Сквозной тест цепочки 1→2→tool (T-2160/T-2164) |
| R4 | Medium | UI задевает freeze-меню | tma-menu-freeze + generic-рендер |
| R5 | R17/R18 | Секреты/сырьё в payload/логах | Только коды/числа/токены; без промптов |

---

## 8. Feature flag / раскатка / откат

- `TOKEN_ANALYTICS_ENABLED` — env-only `ClassVar` (**default ON**, Δ каталога = 0). `OFF` → запись/дашборд выключены, прежний учёт сохраняется (байт-в-байт бюджеты).
- Поэтапная раскатка % не требуется; откат — kill-switch OFF / `git revert` + `DROP TABLE` (телеметрия безопасна).

---

## 9. Критерии приёмки

- В PG пишутся `module/step/input/output/cost/timestamp`; старый учёт сохранён.
- `correlation_id` связывает Stage-1/Stage-2/tool-loop в дерево; на дашборде — Flow-node последнего вызова.
- Графики день/неделя/месяц работают; структура меню не изменена.
- Полный pytest — **0 failed**.

---

## 10. Зависимости / ступени / handoff

- Backend независим; `web/**` — ступень **F5 → F7 → F8 → F9**; `system2_handoff.py` — **F3 → F6 → F7** (F7 — no-op по коду).
- F5 присылает `step="image"`-события; F8/F9 читают дашборд/описывают его.
- **F7 — единственный владелец DDL этого раунда** (PG); SQLite не трогается.

## 11. Открытые вопросы → Human Gate

1. **AMEND DDL:** `llm_usage_events`/`llm_model_prices` — в **PG** (SQLite остаётся v12) вместо предварительного «SQLite v12→v13» (Part 1 §3.4). ✅ **ЗАКРЫТО (Merge):** зафиксировано в `plans/ARCHITECTURE.md` §49 (критично для Part 3/F9 и пин-тестов).
2. **Базовые цены сида:** какие модели/ставки зафиксировать стартово (значения меняются) — подтвердить.
3. **Ретенция:** 90 дней — подтвердить.
4. **UI-размещение дашборда:** внутри «Сводки» vs отдельный special-screen — подтвердить (меню не меняется в любом случае).
