# Отчёт F22 `budget-data-repair-round1024` — ремонт seed-overrides + read-only аудит

> **Раунд:** 10.24 · **Фича:** F22 · **ADR:** ADR-1024-23 · **Baseline:** HEAD после F20 `070f31c`
> **R17/R18:** секреты и сырые значения ключей в этом отчёте и в JSONL не выводятся.
> **Статус live-аудита:** ожидает прогона на прод-сервере (@DevOps, T-2375) — локально PG нет.

## 1. Что сделано в коде (F22)

| Файл | Изменение |
|---|---|
| `manage.py` | **connect-fix** в `_cmd_apply_chat_overrides`: обязательный `await pg.connect()` до `init(...)`; при недоступной PG — сообщение в stderr и **non-zero exit** (тихий no-op устранён). |
| `manage.py` | Новая **read-only** команда `audit-chat-overrides` (только `SELECT`): сверка 8 seed-ключей с эталоном (`ok\|absent\|different`), таймлайн `chat_lore_history field='chat_params'` с детектором вайпа, `chat_keys` только `{configured,last4}`, счётчики, резолв `flags.chat_context_budgets_enabled`. |
| `tests/test_budget_data_repair_round1024.py` | 17 тестов: ремонт/идемпотентность/immutability/break-glass, разрыв петли F20→сид, таймлайн и вайп, read-only, R17-редакция, fail-loud CLI PG, границы флагов. |
| `services/chat_settings_seed.py`, `config/chat_settings_seed.json`, `scripts/backfill_104_chat_flags.py` | **Не менялись** (канон ремонта — plain-сид; один write-path). Δ DDL = 0, Δ каталога = 0. |

## 2. Команды для прод-ремонта (T-2375, без секретов)

Порядок прод-проверки — по spec §6.3. Запускать на прод-сервере (PG `127.0.0.1`).

### 2.1. Read-only аудит ДО ремонта (ничего не пишет)

```
python manage.py audit-chat-overrides --chat-id -1002661910336
```

Ожидаемо: 8 seed-ключей — `absent`; в таймлайне найден `wipe_suspected=yes`.
Строгий режим (non-zero при дрейфе):

```
python manage.py audit-chat-overrides --chat-id -1002661910336 --strict
```

### 2.2. Ремонт (plain-сид, БЕЗ `--force`)

```
python manage.py apply-chat-overrides
```

Ожидаемо: `applied=1`, ключи целевого чата; при уже восстановленном наборе — `skipped=1`.

> `--force` — **только break-glass** по явному гейту владельца и после аудита,
> показавшего ключ класса `different` (перезаписывает ручные правки —
> `manual-overrides-immutable`).

### 2.3. Повторный аудит ПОСЛЕ ремонта (идемпотентность/контроль)

```
python manage.py audit-chat-overrides --chat-id -1002661910336 --strict
```

Ожидаемо: все 8 ключей `ok`, `-1` на месте; `flags.chat_context_budgets_enabled` не изменён.
Повторный `apply-chat-overrides` → `skipped=1` (no-op, без history/NOTIFY).

## 3. Артефакты аудита

- JSONL: `var/audit/chat_overrides_<chat_id>_<utc>.jsonl` (gitignored) — строки `summary`,
  `timeline`, `chat_key`, `chat_usage`, `worker_budget`, `global_limit`, `context_flag`.
- В JSONL/stdout: только имена ключей, числа-значения лимитов (`0/-1`) и `{configured,last4}`.
  Сырые `key_value`, токены и полные JSON-дампы `old_value`/`new_value` не выводятся.

## 3a. Итерация 1 (review fixes, @Reviewer)

- **High-1:** `context_flag` в CLI теперь резолвится из уже вычитанных данных PG
  (`overrides` → `bot_settings` → `settings`), а не через bot-only `ChatParamsCache`.
  Аудит показывает фактический per-chat источник (`source='chat'`).
- **High-2:** fail-loud на нечитаемый/пустой сид: `apply-chat-overrides` и
  `audit-chat-overrides` (в т.ч. `--strict`) → stderr + non-zero.
- **Medium-3:** восстановлен `await pg.init(seed_settings=False)` после `connect()`.
- **Medium-4:** R17 — в вывод/JSONL идёт только эталонное seed-значение, не текущий override.
- **Medium-5:** тест петли вызывает реальный F20-роут `POST /api/config`; добавлены
  тесты `--strict`, реального резолва флага и пины Δ DDL/каталога.
- **Low-6:** отказ секции аудита (`warnings`) при `--strict` → non-zero.

## 4. Границы

- `flags.chat_context_budgets_enabled` (усечение контекста direct) и master-тумблер
  F21 `flags.budgets_enabled` — **разные оси**: master OFF перекрывает всё, master ON
  не отменяет усечение контекста. F22 флаги не пишет; `backfill_104_chat_flags.py` не менялся.
