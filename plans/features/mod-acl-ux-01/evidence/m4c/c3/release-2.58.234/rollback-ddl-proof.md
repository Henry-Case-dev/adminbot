# Rollback DDL proof — 2.58.234 / M4C C3 (delta-review B01)

- **Status:** proof / REVIEW; деплой, SSH, production DB, LLM и positive ACL-writes не выполнялись.
- **Дата:** 2026-11-22 19:55 +12:00 / 07:55 UTC.
- **Объекты:**
  - raw base `f232a3a30a79c074fc3d7fa75d8aa947720d76a4` (2.58.233, CHECK **10** значений);
  - prepared rollback target **`be23f5eff7287b02e2e91d9b5a5af2b474198beb`**, ветка
    `rollback/mod-acl-m4c3-ddl-compatible` (от `f232a3a3`, **только** `services/pg_db.py` 1/1;
    `APP_VERSION` остаётся **2.58.233**, C3 feature/UI/тестов поведения нет; CHECK **11** значений);
  - forward content tip `3b18ca1dd0a3e6c9c528bcbb1a2a975276dcf49f` (CHECK **11** значений).
- **Среда:** PGlite `0.5.17` — **PostgreSQL 18.7**, WASM, локальная scratch-БД; production не
  затрагивался. Сырые результаты: `rollback-ddl-proof.json`.
- `services/pg_db.py` в rollback target и forward **байт-идентичен** (blob
  `0174c28b6abe8fd04385e97592f870c0629dd909`): оба содержат ровно одно изменение относительно
  raw base — добавление `'access'` в CHECK; 62 statement, новых объектов нет.

## 1. Что доказано

| Проба | Результат |
|---|---|
| raw old DDL (`f232a3a3`) при существующей строке `field='access'` | `DROP CONSTRAINT IF EXISTS` — ok; `ADD CONSTRAINT` с 10 значениями — **ERROR 23514** (`check constraint ... is violated by some row`); CHECK после — **отсутствует** (count=0); строки данных целы (2). Это воспроизводит B01. |
| prepared target, полный startup DDL (62 statement) на БД с `access`-строкой | **62/62 применено, ошибок 0**. |
| prepared target, **повторный** startup (idempotency) с той же `access`-строкой | **62/62 применено, ошибок 0**; CHECK присутствует с 11 значениями. |
| prepared target: значения CHECK | все 10 старых значений + `access` вставляются; `access`-строка сохраняется (count=1). |
| raw old DDL при `access`-строках = **0** | DROP+ADD с 10 значениями проходит; CHECK присутствует (10 значений). Это основание gate «0 → raw allowed». |
| forward SQL vs prepared target SQL | нормализованные `ADD CONSTRAINT` **идентичны** (`forward_matches_target=true`); target отличается от raw только добавлением `'access'`. |

Фактический constraint после target (PGlite):

```text
CHECK ((field = ANY (ARRAY['manual'::text, 'auto'::text, 'auto_enabled'::text,
  'auto_period_hours'::text, 'auto_window_hours'::text, 'remap'::text,
  'chat_admin'::text, 'chat_params'::text, 'chat_keys'::text, 'gates'::text,
  'access'::text])))
```

Ошибка raw old (PGlite):

```text
SQLSTATE 23514
check constraint "chat_lore_history_field_check" of relation "chat_lore_history"
is violated by some row
```

## 2. Воспроизведение на scratch PostgreSQL

Выполняется только на одноразовой БД, **не на production**. SQL взят из фактических
`DDL_STATEMENTS` коммитов (не переписан вручную):

```sql
-- исходное состояние: схема/CHECK как у 2.58.234 и строка audit
CREATE TABLE chat_lore_history (
  id BIGSERIAL PRIMARY KEY,
  chat_id BIGINT NOT NULL,
  field TEXT NOT NULL,
  changed_by BIGINT,
  old_value TEXT,
  new_value TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 11-значный CHECK (forward/target)
ALTER TABLE chat_lore_history ADD CONSTRAINT chat_lore_history_field_check
  CHECK (field IN ('manual','auto','auto_enabled','auto_period_hours',
                   'auto_window_hours','remap','chat_admin','chat_params',
                   'chat_keys','gates','access'));
INSERT INTO chat_lore_history (chat_id, field) VALUES (0, 'access');

-- A. raw f232a3a3 startup: DROP проходит, ADD падает, CHECK исчезает
ALTER TABLE chat_lore_history DROP CONSTRAINT IF EXISTS chat_lore_history_field_check;
ALTER TABLE chat_lore_history ADD CONSTRAINT chat_lore_history_field_check
  CHECK (field IN ('manual','auto','auto_enabled','auto_period_hours',
                   'auto_window_hours','remap','chat_admin','chat_params',
                   'chat_keys','gates'));  -- ERROR 23514, constraint отсутствует

-- B. prepared target: тот же DROP, но ADD с 11 значениями — успех
ALTER TABLE chat_lore_history ADD CONSTRAINT chat_lore_history_field_check
  CHECK (field IN ('manual','auto','auto_enabled','auto_period_hours',
                   'auto_window_hours','remap','chat_admin','chat_params',
                   'chat_keys','gates','access'));
```

Ожидаемо: A даёт `23514` и `count(pg_constraint)=0`; B даёт `count=1` и constraint с `access`;
повтор B (второй startup) снова успешен.

## 3. Полный startup DDL

Rollback target содержит те же 62 statement, что forward (blob `services/pg_db.py` идентичен).
Прогон 62 statement на PGlite с уже существующей `access`-строкой: **62/62** (первый и второй
startup). Прогон raw base 62 statement на той же БД: применено 24, падение на statement 24
(`ALTER TABLE ... ADD CONSTRAINT ... 10 values`, SQLSTATE 23514), CHECK после — отсутствует.

Это доказывает, что old code на prepared target не роняет CHECK и что raw `f232a3a3` после
audit-записи — невалидная rollback-цель.

## 4. Ограничения

- PGlite — реальный PostgreSQL 18.7 в WASM, но не production-версия/окружение; фактическое
  применение DDL на production всё равно проверяется postdeploy (§runbook).
- Поведение `ConfigCache.init()` при ошибке DDL (пустые roles/admins, 503, owner не global_admin)
  в этой пробе не переисполнялось; оно доказано delta-review R1 детерминированной пробой и
  подтверждается причинно: raw old ADD падает, а `ConfigCache.init()` перехватывает ошибку.
- Production-данные не читались/не мутировались; SSH/LLM/деплой не вызывались; VERIFIED не
  заявлялся.
- Rollback target — не релизный кандидат: F8 byte-pin `PG_DB_SHA256_B07` намеренно не обновлён
  (нельзя менять тесты поведения в rollback-target), поэтому полный release-набор тестов на нём
  не запускается; acceptance — этот DDL-proof и startup-совместимость.

## 5. Ссылки

- Прошивка B01: `plans/features/mod-acl-ux-01/evidence/m4c/c3/release-2.58.234/delta-review-r1.md`.
- Rollback target: `rollback/mod-acl-m4c3-ddl-compatible` @ `be23f5eff7287b02e2e91d9b5a5af2b474198beb`.
- Машинные результаты: `rollback-ddl-proof.json` (PGlite 0.5.17 / PostgreSQL 18.7).
