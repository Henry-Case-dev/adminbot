# Spec: sqlite-row-get-fix-round1024 (UPD4-D)

> Раунд 10.24 (UPD4 «кластер D») · Приоритет **P2** · Severity **Low-Medium**
> Тип: backend-багфикс web-API (`web/api/**`). Владелец: F18 (`web/api/chat_lore.py` — эксклюзив).
> **ADR:** `ADR-1024-19.md`.
> **ТЗ:** `plans/current_task.md`, секция UPD4 (строки 274–316). Файл untracked; секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Задачи: `tasks.md` T-2328…T-2331.
> **Δ DDL = 0 · Δ каталога = 0 · новых флагов нет.**

## 1. Цель

Устранить падение `_participant_names` в `web/api/chat_lore.py` и вернуть корректные
имена участников в ответе relations-эндпоинта.

Сейчас функция обращается к строкам SQLite как к словарям:
`r.get("user_id")` / `r.get("author_name")` (строки 675–676). Источник строк —
`aiosqlite.Row` (это `sqlite3.Row`), у которого **нет** метода `.get` →
`AttributeError: 'sqlite3.Row' object has no attribute 'get'`. Широкий
`except Exception` (строки 677–681) глотает исключение, пишет WARNING и
возвращает `None` → срабатывает uid-fallback: **имена участников теряются**
(в списке остаются сырые ID). Баг «тихий», поэтому жил до UPD4.

Вторичная цель — **закрыть класс багов**, а не единичный случай: превентивно
проверить другие чтения `.get(...)` по строкам курсора в `web/api/**` и сервисах.

## 2. Что уже есть (координаты)

| Что | Где |
|---|---|
| Баг | `web/api/chat_lore.py:666-682::_participant_names`; `.get` — `:675-676` |
| Вызов бага | `web/api/chat_lore.py:584` (`names = await _participant_names(db, chat_id)`) → `relations_service.get_relations_snapshot(..., names=names)` `:585-586`; каскад имён `:638-658` |
| Источник строк | `services/database.py:3714-3726::get_active_participants` → `await cursor.fetchall()`; строки `row_factory = aiosqlite.Row` (`services/database.py:515,590,626`) |
| Канон-аксессор | `services/database.py:145-153::row_get` — `hasattr(row, "get")` → `.get`, иначе `row[key]` с ловлей `KeyError/IndexError/TypeError` |
| Прецедент нормализации | `services/tool_router.py:1030-1031` — `rows = [dict(row) for row in rows]` (маркировано «T-678: aiosqlite.Row не имеет .get») |
| Прецедент использования `row_get` | `services/chat_context.py:112-120`, `services/direct_chat_service.py:2519-2526` |
| Маскирующий `except` | `web/api/chat_lore.py:677-681` (WARNING + `None`) |
| Контракт ответа | `GET /api/chat_lore/{chat_id}/relations` → `{chat_id, relations_enabled, users[:_RELATIONS_LIST_MAX]}` (`:659-663`); `_RELATIONS_LIST_MAX=100` |

Импорта `services.database` в `web/api/**` сейчас нет; циклов нет —
`services/database.py` импортирует только `config.settings`, `services.hot_config`,
`services.graph_stoplist`, `services.user_relations` (никто не тянет `web.api`).

## 3. Требуемое поведение

### 3.1. Исправление `_participant_names` (T-2328)

- Доступ к полям строки — через **канонический `row_get`** из
  `services.database` (решение зафиксировано в ADR-1024-19; альтернатива
  `dict(row)` допустима, но не выбирается — см. §5 и ADR).
- Маппинг **не меняется семантически**: `{user_id: author_name}` только для строк,
  где `user_id` присутствует/истинен и `author_name` непустой после `.strip()`;
  значения — **КАК ЕСТЬ** (без strip/чистки — раунд 10.2); пустые/пробельные имена
  пропускаются как отсутствующие.
- Целевая форма (фильтр вычисляется до ключа/значения, поэтому `int(None)` невозможен):

```
names = {
    int(row_get(r, "user_id")): str(row_get(r, "author_name"))
    for r in rows
    if row_get(r, "user_id")
    and str(row_get(r, "author_name") or "").strip()
}
```

- Импорт: `from services.database import row_get` рядом с прочими `services.*`
  импортами (`web/api/chat_lore.py:41-45`).
- Широкий `except Exception` (`:677-681`) **сохраняется** как честная страховка
  (fail-open не ломаем), но больше **не должен срабатывать** на этом коде.
  Формат WARNING-лога не меняется (R17: только `chat_id`, без имён/текстов).

### 3.2. Поведение при отсутствии данных

- Пустой результат или все имена пустые → возвращается `None` (как раньше) →
  uid-fallback штатный (это корректный сценарий, а не ошибка).
- Строка без колонки (`IndexError`) → `row_get` вернёт `default` (None) → строка
  пропускается, **без** падения.

### 3.3. Превентивный аудит `.get()` на Row (T-2330)

Закрыть класс багов, не только инцидент. Метод (для @Reviewer):
1. Найти все точки `fetchall()` / `fetchone()` / `async for ... in cursor` в
   `web/api/**` и `services/**`.
2. Для каждой строки-приёмника проверить, нет ли `row.get(...)` / `r.get(...)`.
3. Безопасными считать только: (а) строку, нормализованную в `dict`; (б) строку
   asyncpg (`Record` **имеет** `.get`, напр. `services/anticliche_cache.py:197`);
   (в) доступ через `row_get`/subscript.
4. Найденные реальные кандидаты (`aiosqlite.Row` + `.get`) — зафиксировать как
   follow-up с координатами; заведомо приемлемые — с обоснованием.
Результат аудита — раздел в ревью-отчёте; новых задач по умолчанию не плодим,
только честный список.

## 4. Изменения по файлам

| Файл | Что |
|---|---|
| `web/api/chat_lore.py` | + импорт `row_get`; замена `r.get(...)` → `row_get(r, ...)` в `_participant_names` (`:674-676`). Больше ничего в модуле не трогаем. |
| `tests/test_chat_lore_participant_names_round1024.py` (новый) | Регресс-тесты (см. §6). |
| `plans/features/sqlite-row-get-fix-round1024/**` | spec/ADR/tasks (эталон). |

Δ DDL = 0, Δ каталога/settings = 0, миграций/флагов нет.

## 5. Контракты

- **API relations — БЕЗ изменений (R16):** `{chat_id, relations_enabled, users[]}`;
  поля/порядок/`_RELATIONS_LIST_MAX` не меняются. Меняется только **качество
  данных** — вместо uid-fallback приходят имена (это и есть цель).
- **Имена — КАК ЕСТЬ** (инвариант 10.2): никакой обрезки/`strip`/капы; ID как имя
  по-прежнему невозможно (каскад `:638-658`).
- **Внутренний контракт доступа к Row (новый канон, ADR-1024-19):** строка курсора
  → `row_get(row, key)` или предварительный `dict(row)`; прямой `row.get(...)`
  на `aiosqlite.Row` запрещён.
- **Fail-open:** ошибки чтения не поднимают статус выше прежнего поведения
  (WARNING + `None` → uid-fallback), 5xx не появляется.

## 6. Тесты

Новый `tests/test_chat_lore_participant_names_round1024.py` (pytest-asyncio, по
образцу `tests/test_chat_lore_api.py` / `tests/test_database.py`):

1. **Регресс `AttributeError`:** `db.get_active_participants` возвращает **реальные**
   `sqlite3.Row` (in-memory `sqlite3.connect(":memory:")`, `row_factory = sqlite3.Row`,
   `SELECT 1 AS user_id, 'Аня' AS author_name`) → `_participant_names` **не бросает**
   и возвращает `{1: "Аня"}`. (На старом коде — падение.)
2. **Корректный маппинг и фильтрация:** строки с пустым/пробельным `author_name`
   пропускаются; `user_id=0`/NULL пропускается; значения не чистятся (эмодзи/пробелы
   внутри сохраняются дословно).
3. **Пустой результат → `None`:** нет строк / все отфильтрованы → `None` (uid-fallback).
4. **Отсутствующая колонка:** строка без `author_name` → `row_get` даёт default,
   падения нет.
5. **dict-совместимость:** та же функция работает и на dict-строках (не регрессируем
   по `row_get`).
6. **Интеграционный (опц.):** `GET .../relations` под существующим `api_env` отдаёт
   `users[].name` из participant-map, а не uid.

Гейты: полный `pytest` — 0 failed; `git diff --check` чист; R17/R18-скан отчёта.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | Тихий характер бага (broad except) снова замаскирует регресс | Low-Med | Регресс-тест на реальном `sqlite3.Row` (§6.1) |
| R2 | Аналогичные `.get` в других местах | Low | Превентивный аудит T-2330 / §3.3 |
| R3 | Затрагивается relations-ответ | Low | Контракт не меняется (R16); проверка `_RELATIONS_LIST_MAX`/сортировки в интеграционном тесте |
| R4 | Импорт `services.database` в `web/api` создаёт цикл/вес | Low | Циклов нет (проверено §2); альтернатива `dict(row)` не требует импорта — зафиксирована в ADR |
| R5 | Пересечение с F4 (`dossier-live-feed`) по `get_active_participants` | Low | См. §10; файлы разные, helper в `chat_lore.py` не экспортируется |

## 8. Критерии приёмки

- `_participant_names` на `aiosqlite.Row` не бросает `AttributeError`; возвращает
  корректный `{user_id: author_name}`; `None` — только при реальном отсутствии данных.
- В прод-логах исчез `[relations] имена участников недоступны … no attribute 'get'`;
  имена участников в relations отдаются корректно.
- Превентивный grep T-2330 выполнен, результат зафиксирован (найденное — follow-up).
- Полный pytest — 0 failed; `git diff --check` чист; `node --check` не затронут.
- Δ DDL = 0; API-контракт и `_RELATIONS_LIST_MAX` не деградировали; R16/R17/R18 соблюдены.

## 9. Флаг и откат

- **Feature flag: не требуется.** Это чистый behavior-fix, уже fail-open; OFF-ветки
  в поведении нет (tasks.md §Зависимости). Progressive delivery = наблюдение логов
  после деплоя (проверка отсутствия WARNING) и `git revert` при регрессе.
- Откат: `git revert` одного коммита. DDL/миграций/каталога нет, схема не менялась.

## 10. Инварианты и пересечение с F4

- **R16** — изменения аддитивны/совместимы: API-поля relations не меняются.
- **R17** — логи/спеки/отчёты: только `chat_id` и классы ошибок; имена/тексты/секреты
  не цитируются. Значения `.env`/токенов не приводим.
- **R18** — в diff/спеках/отчётах нет значений секретов (в этой фиче секретов нет).
- **Δ DDL = 0** — только чтение существующей таблицы `smart_messages`.
- **Не ломать F1/F2/F7** — модуль `web/api/chat_lore.py` правится точечно (импорт +
  3 строки); прогон полного pytest защищает регресс.
- **`parse_mode=None`** — Telegram-отправка не затрагивается: путь чисто web/JSON,
  сообщения в Telegram не формируются, инвариант не нарушается.
- **Пересечение с F4 `dossier-live-feed-round1024`:** F4 добавляет обратный резолв
  `name → user_id` в `web/api/oversight.py`, используя тот же
  `db.get_active_participants`. Файлы разные (`chat_lore.py` vs `oversight.py`);
  `_participant_names` — приватный helper F18, **не** экспортируется и не
  импортируется в F4. F4 обязан соблюсти тот же канон доступа к Row (ADR-1024-19);
  общий код не выносим (нет нужды, риск связности web-модулей выше выгоды).
  При решении владельца «merge в F4» задачи T-2328…T-2331 переносятся в
  `dossier-live-feed-round1024/tasks.md` с сохранением ID.
