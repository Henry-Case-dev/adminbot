# ADR-1014-1 — Хранилище Persona (личность бота): PG-таблица `personas` (DDL РАЗРЕШЁН)

- **Статус:** ACCEPTED (Step 2 @Architect, **итерация 2**, 13.09.2026). **Отменяет редакцию 1 (DDL-free).**
- **Раунд:** 10.14, фича **F2** `persona-storage-core-round1014` (T-1487).
- **Контекст:** `plans/current_task.md` §2 + **UPD п.1–2,4** (owner: «даю прямое разрешение на изменение структуры БД и написание миграций; Persona — полноценная схема со скоупами, НЕ в `bot_settings`/`chat_params.overrides»); `services/pg_db.py` (DDL_STATEMENTS/`PgDatabase.init`); `services/chat_params.py`; `services/param_catalog.py`.
- **Связано:** ADR-1014-2 (F1: SQLite `origin='bot_self_reply'`, `persona_state`), ADR-1013-1 (провайдер-блоки), ADR-1013-3 (промпт-канон вне PG).
- **Снимает инвариант:** «ноль новых PG-DDL» (действовал с 10.4; **снят владельцем** в UPD п.1).

## 1. Проблема

ТЗ §2 требует сущность `Persona` со скоупами: глобально (`is_global=true`) **или** per-`chat_id`. Редакция 1 реализовывала это DDL-free (4 ключа `content.persona_*` в `bot_settings` + `chat_params.overrides` + производный `is_global`). Владелец отклонил этот путь: «Мы строим чистую архитектуру на будущее, а не лепим заплатки» (UPD п.1). DDL и миграции разрешены.

## 2. Решение

**Создать PG-таблицу `personas`** (источник истины для статической личности) + **PG-таблицу `persona_traits`** (динамические черты). F1 владеет `persona_state` (статус экстрактора, ADR-1014-2 §D9). Ноль хранения персоны в `bot_settings`/`chat_params.overrides`.

### 2.1. DDL (`services/pg_db.py`, `DDL_STATEMENTS`, идемпотентно)

```sql
CREATE TABLE IF NOT EXISTS personas (
    id                     BIGSERIAL PRIMARY KEY,
    chat_id                BIGINT,
    is_global              BOOLEAN NOT NULL DEFAULT false,
    name                   TEXT NOT NULL DEFAULT '',
    biography              TEXT NOT NULL DEFAULT '',
    system_prompt_overrides TEXT NOT NULL DEFAULT '',
    is_aware_ai            BOOLEAN NOT NULL DEFAULT true,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT personas_scope_chk CHECK (
        (is_global AND chat_id IS NULL) OR (NOT is_global AND chat_id IS NOT NULL)),
    CONSTRAINT personas_chat_fk FOREIGN KEY (chat_id)
        REFERENCES chat_profiles (chat_id) ON UPDATE CASCADE ON DELETE CASCADE
);
-- Ровно одна глобальная строка:
CREATE UNIQUE INDEX IF NOT EXISTS uq_personas_global
    ON personas (is_global) WHERE is_global;
-- Ровно одна строка на чат:
CREATE UNIQUE INDEX IF NOT EXISTS uq_personas_chat
    ON personas (chat_id) WHERE chat_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS persona_traits (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    BIGINT,                       -- NULL = общеботовая черта (без провенанса)
    trait      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'deep_sleep',  -- deep_sleep | manual
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_persona_traits_created
    ON persona_traits (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_persona_traits_chat
    ON persona_traits (chat_id, created_at DESC);
```

**Обоснование схемы.**
- `is_global` + `chat_id` + CHECK — явная, а не производная семантика скоупа (владелец требует логически правильную схему). Два **partial unique** индекса дают ровно одну глобальную и ровно одну per-chat строку.
- **FK `chat_id → chat_profiles(chat_id)` ON DELETE CASCADE** — «где уместно»: персональная персона не существует без чата; удаление профиля убирает и переопределение. Пишущий путь chat-scope обязан вызвать `ensure_scope_profile(chat_id)` (`services/chat_params.py:337`) до UPSERT. Отход от прежнего стиля «без FK между новыми таблицами» сознательный (владелец санкционировал DDL; целостность — приоритет).
- `persona_traits.chat_id` **без FK** (nullable) — это провенанс наблюдения; черта живёт даже при удалении/переносе профиля. Индекс `(created_at DESC)` — для ленты/счётчиков, `(chat_id, created_at DESC)` — для анализа по чату.
- `dynamic_traits` **в отдельной таблице, а не JSONB-колонкой** — см. §2.4.

### 2.2. Резолв скоупа

`resolve_bot_persona(chain_id) → BotPersona`:
1. **per-chat** строка `personas WHERE chat_id = $1 AND is_global = false`;
2. если нет → **global** строка `WHERE is_global = true`;
3. если нет обеих → **пустая персона* (все поля дефолтны: `name=''`, `biography=''`, `system_prompt_overrides=''`, `is_aware_ai=true`).
- **per-chat переопределяет глобальную целиком по полю** (построчный fallback: пустое поле per-chat = пустое, НЕ наследует global — так UI-поле «не задано» однозначно; сброс чата = `DELETE` строки → наследование global).
- Fail-open: PG down/ошибка → `BotPersona.empty()` + WARNING (промпт жив, деградация к прежнему поведению).

### 2.3. API (см. spec F2 §5)

`GET /api/persona` (scope по `X-Chat-Id`): `scope`, `chat_id`, `values{name,biography,system_prompt_overrides,is_aware_ai}`, `is_global`, `persona_enabled`, `dynamic_traits`.
`PUT /api/persona` (scope по `X-Chat-Id`; RBAC): partial-поля; chat-scope → UPSERT строки чата (после `ensure_scope_profile`); global-scope → UPSERT глобальной строки; `reset:true` → `DELETE` строки чата (наследование global).
`DELETE /api/persona` (chat-scope) — удаление override.
`GET /api/persona/health` (global admin) — метрики Личности (F4).

UPSERT (partial-index inference):
```sql
-- global
INSERT INTO personas (chat_id, is_global, name, biography,
                      system_prompt_overrides, is_aware_ai)
VALUES (NULL, true, $1, $2, $3, $4)
ON CONFLICT (is_global) WHERE is_global DO UPDATE
   SET name = EXCLUDED.name, biography = EXCLUDED.biography,
       system_prompt_overrides = EXCLUDED.system_prompt_overrides,
       is_aware_ai = EXCLUDED.is_aware_ai, updated_at = now();
-- per-chat
INSERT INTO personas (chat_id, is_global, name, biography,
                      system_prompt_overrides, is_aware_ai)
VALUES ($1, false, $2, $3, $4, $5)
ON CONFLICT (chat_id) WHERE chat_id IS NOT NULL DO UPDATE
   SET name = EXCLUDED.name, biography = EXCLUDED.biography,
       system_prompt_overrides = EXCLUDED.system_prompt_overrides,
       is_aware_ai = EXCLUDED.is_aware_ai, updated_at = now();
```

### 2.4. `dynamic_traits` — отдельная таблица `persona_traits`

**Выбор: `persona_traits` (таблица), НЕ JSONB-колонка.** Обоснование:
1. **Метрики** (UPD п.4) = `COUNT(*)` и `MAX(created_at)` — нативный SQL, без парсинга JSON;
2. **Лента** (F4) = `ORDER BY created_at DESC LIMIT N` с индексом;
3. **Ротация/cap** = `DELETE WHERE id NOT IN (SELECT id ... ORDER BY created_at DESC LIMIT $cap)` — без read-modify-write JSON и без гонки писателя;
4. провенанс `chat_id`/`source` — first-class колонки;
5. владелец прямо просит «делай базу логичной».

Формат: одна строка = одна черта; текст ≤ `settings.PERSONA_TRAIT_MAX_CHARS` (200); при записи — дедуп по `lower(btrim(trait))` среди последних N (или глобальный `NOT EXISTS`) и FIFO-cap `settings.PERSONA_TRAITS_MAX` (50). Пишет `DeepSleepWorker._run_persona_traits_once` (F2).

### 2.5. Миграция/сид (идемпотентно)

- DDL исполняется в `PgDatabase.init()` для `DDL_STATEMENTS` (idempotent by `IF NOT EXISTS`). Новые таблицы аддитивны — существующая БД получает их при старте.
- **Сид singleton-состояния** (владелец F1): 
  ```sql
  INSERT INTO persona_state (id) VALUES (true) ON CONFLICT (id) DO NOTHING;
  ```
- **Сид пустой глобальной персоны** (стабильный `updated_at`/optimistic-токен): 
  ```sql
  INSERT INTO personas (chat_id, is_global)
  SELECT NULL, true WHERE NOT EXISTS (SELECT 1 FROM personas WHERE is_global);
  ```
  Значения остаются пустыми (владелец: «Имя и биография пока остаются пустыми»).
- Сиды НЕ перезаписывают существующие строки (`DO NOTHING`/`WHERE NOT EXISTS`) — ручные правки неприкосновенны.
- **Обратимость:** откат — `DROP TABLE persona_traits, personas` + `UPDATE`-миграция не нужна (данных персоны в других хранилищах нет). При откате фичи флаг `flags.persona_enabled=OFF` возвращает байт-в-байт прежний промпт.

## 3. Рассмотренные альтернативы

| Альтернатива | Отклонена потому что |
|---|---|
| **DDL-free (редакция 1):** `content.persona_*` в `bot_settings` + `chat_params.overrides`, производный `is_global` | **Отклонена владельцем (UPD п.1):** «не пихать в bot_settings/chat_params». Нет строгой схемы, нет partial-unique, `is_global` производный, нет FK. |
| Одна таблица `personas` без `persona_traits` (JSONB-колонка traits) | метрики/лента/ротация через парсинг JSON; read-modify-write вместо DELETE. См. §2.4. |
| `dynamic_traits` в `bot_settings` JSON-ключе | владелец запретил Persona в `bot_settings`; парсинг/гонка. |
| Отдельная SQLite-таблица Persona | смешивание слоёв: SQLite — память бота, PG — админ-конфиг; per-chat scope/API уже в PG. |
| FK на `chat_profiles` не вводить (прежний стиль) | персона без чата — невалидное состояние; cascade-очистка нужна. |

## 4. Последствия

**Плюсы:** строгая схема и целостность; явный `is_global`; `COUNT/MAX/ORDER BY` без парсинга; единая точка записи; API/скопы прозрачны; миграция аддитивна и идемпотентна.

**Минусы/издержки:** расширяется PG-схема (Scanner будет проверять DDL/идемпотентность — тест-план §5); нужен `ensure_scope_profile` на chat-записи; `persona_state`/`persona_traits` — новые таблицы (мониторинг).

## 5. Верификация

См. spec F2 §7/§9. Маркеры: `PgDatabase.init()` дважды подряд — без ошибок; ровно одна глобальная и одна per-chat строка (partial-unique); scope-резолв (per-chat → global → empty); round-trip API; `ON CONFLICT` UPSERT; FK cascade; `persona_traits` cap/dedup; отсутствие ключей `content.persona_*` в `bot_settings` (grep); `bot_settings` не содержит персону.
