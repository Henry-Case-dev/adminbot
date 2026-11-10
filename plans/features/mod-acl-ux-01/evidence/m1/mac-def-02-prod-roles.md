# MAC-DEF-02 — инвентарь реальных ролей прода (вход для приоритета)

Снято **read-only** на выкаченном 2.58.181 (коммит
`92070d0eda83674fd386324d55ba12a28b5e3837`), 10.11.2026.
Источник — PostgreSQL (`POSTGRES_DSN`), таблицы `bot_roles` и `bot_admins`;
запрос шёл в транзакции `READ ONLY`. SQLite `local_database.db` здесь не
источник ролей (`services/config_cache.py::_load_all` читает PG).

## Ответ на вопрос строки

**Нет.** В проде нет ни одного аккаунта с `role_type='global_admin'` без
`wildcard`: `accounts_global_admin_without_wildcard = 0`.

## Роли (`bot_roles`, 4 записи)

| role_name | role_type | wildcard | is_custom |
|---|---|---|---|
| `admin` | `global_admin` | **true** | false |
| `local_admin` | `local_admin` | false | false |
| `moderator` | `moderator` | false | false |
| `user` | `user` | false | false |

Ролей с `wildcard=true`: **1**. Ролей с `role_type='global_admin'`: **1**.

## Назначения (`bot_admins`, 3 записи)

Telegram-id замаскированы (последние 4 цифры), секретов в файле нет.

| id | роль | role_type роли | wildcard роли |
|---|---|---|---|
| `***2796` | `moderator` | `moderator` | false |
| `***7079` | `moderator` | `moderator` | false |
| `***3495` | `admin` | `global_admin` | **true** |

## Следствия

1. **Приоритет MAC-DEF-02 — низкий, не срочный.** Остаточный дефект
   (`can_view_key_value` / `can_edit_param` не смотрят `role_type`) сегодня
   недостижим на проде: единственная `global_admin`-роль несёт `wildcard=true`
   и проходит оба предиката по wildcard-ветке. Ни один реальный аккаунт не
   затронут.
2. **MAC-DEF-01 на проде сейчас латентен.** Ветка `user_has_permission` →
   `user_is_global_admin` не меняет наблюдаемого поведения существующих
   идентичностей, потому что единственный `global_admin` и так проходит по
   wildcard. Фикс убирает будущую ловушку: если появится роль
   `role_type=global_admin` без wildcard, она больше не получит ложный 403.
3. Проверка на проде подтверждает доступ владельца: `GET /api/admins` → **200**
   и `GET /api/roles` → **200** с owner-`initData` (до фикса это работало
   только благодаря wildcard сид-роли `admin`, `services/pg_db.py`).
4. Если владелец когда-нибудь создаст роль `global_admin` без wildcard,
   MAC-DEF-02 становится срочным — до этого строка остаётся PENDING без
   перевода в очередь.

## Не входит в эту проверку

Матрица 12 конфигураций `user_is_global_admin` (semantics unchanged) — это
тестовый артефакт Reviewer'а, не прод-инвентарь. Секретные значения ключей не
читались и не выводились.
