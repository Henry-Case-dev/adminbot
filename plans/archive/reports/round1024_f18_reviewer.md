# Отчёт @Reviewer — раунд 10.24, F18 `sqlite-row-get-fix-round1024` (шаг 5)

> Коммит: `a406440` (HEAD). Baseline `00eab85`. Ревью проведён по `spec.md`,
> `ADR-1024-19.md`, `tasks.md`, `plans/current_task.md` (UPD4, кластер D),
> `git show a406440 --stat`, `git diff a406440^ a406440`.
> R17/R18: секреты/значения `.env`/токенов не цитируются; только `chat_id`,
> классы ошибок и координаты кода.

## Статус

**Approved**

F18 реализована ровно по спецификации: точечный fix `_participant_names`
(импорт + 3 строки), регресс закреплён тестами на **настоящем** `sqlite3.Row`,
fail-open сохранён и больше не срабатывает, API-контракт/инварианты не тронуты.
Полный pytest — **7516 passed, 0 failed**. Найденный превентивным аудитом
дефект-«одноклассник» (`services/oversight.py`) вынесен как **follow-up вне
scope F18** и не блокирует приёмку (spec §3.3/T-2330: «зафиксировать как
follow-up»).

## Findings по severity

### Critical — нет

### High — нет

### Medium (вне scope F18, follow-up к отдельной задаче)

**[Severity: Medium]** (для F18 — информационный, задача не блокируется)
File: `services/oversight.py`
Location: `_activity_map` — строки `137`, `139`, `144`
Problem: блок агрегата `last_active_ts` для Oversight-дашборда сломан по **трём**
причинам сразу, и это тот же класс, что и инцидент F18:
1. `web_runtime.get_lore_db()` (стр. 137) — в `services/web_runtime.py`
   есть только `get_web_bot()`; атрибута `get_lore_db` **нет** (проверено
   рантаймом: `'get_lore_db' in dir(services.web_runtime) == False`).
   Правильный аксессор — `lore_runtime.get_lore_db()`.
2. `db.db.fetch_all(...)` (стр. 139) — у `aiosqlite.Connection` **нет**
   метода `fetch_all` (проверено рантаймом: `'fetch_all' in
   dir(aiosqlite.Connection) == False`); это asyncpg-API. Нужен
   `await self.db.execute(...)` + `fetchall()`.
3. `ts = r.get("last_ts")` (стр. 144) — прямой `.get()` на строке курсора
   SQLite: ровно запрещённый ADR-1024-19 паттерн (на `dict(r)`/`row_get`
   строке нет `.get`). Рядом, стр. 143, уже используется subscript
   `r["chat_id"]` — смешанный доступ.
Why it matters: сегодня весь блок завёрнут в широкий `except Exception`
(стр. 148–150) → он **всегда** возвращает `{}` и пишет WARNING с traceback на
каждый refresh. Дашборд Oversight молча теряет `last_active_ts` всех чатов
(«плоские» данные активности), а логи зашумлены. Если исправить только пункты
1–2, пункт 3 немедленно даст `AttributeError: 'sqlite3.Row' object has no
attribute 'get'` — то есть баг переедет ровно в ту же тихую форму, что жила в
F18.
Required fix (в рамках отдельной задачи, НЕ в коммите F18):
`lore_runtime.get_lore_db()` + `await db.db.execute(...)` + `fetchall()`,
чтение полей через `database.row_get` (или `dict(row)` на строку), затем
тест на реальном `sqlite3.Row`.

Примечание: в F18-спеке follow-up был предсказан как `services/oversight.py:
139/144` — подтверждаю координаты; фактически дефект шире (стр. 137/139/144).

### Low — нет

## Превентивный аудит `.get()` на строках курсора (T-2330)

Метод: собраны все методы `services/database.py`, возвращающие **сырые**
`cursor.fetchall()` без нормализации (18 методов), и проверены все их
потребители на прямой `.get()`. Также проверены `web/api/**` и сервисы,
читающие SQLite.

- **Исправленный путь F18 (`_participant_names`) и его источник
  `get_active_participants` — чисто.** Все 5 потребителей источника
  используют subscript/`row_get`/`dict(...)`, прямых `.get()` нет:
  `web/api/chat_lore.py:679` (`row_get`), `services/chat_context.py:108-120`
  (subscript + `row_get`), `services/direct_chat_service.py:2172-2184`
  (subscript), `services/dream_worker.py:852-859` (subscript),
  `services/summary_memory.py:2234-2240` (subscript).
- Прочие сырые read-API безопасны: `tool_router.py:1031,1044` и
  `summary_memory.py:2693` нормализуют `dict(...)` перед `.get`;
  `handlers/search.py:88 → chat_context` использует `row_get`;
  `chat_context`, `nostalgia_prompts._row_get`, `media_integrity.row_get` —
  локальные/канонический аксессор; asyncpg-потребители (`status_service`,
  `bot_persona`, `chat_params`, `chat_lore_store`) работают с `Record`, у
  которого `.get` есть.
- **Единственный реальный кандидат-одноклассник** —
  `services/oversight.py:144` (см. Medium выше). Он расположен в
  `web/api/oversight.py`-потребителе через `db.dossier_feed`, который сам
  нормализует строки в dict (`database.py:4586`) — там `.get` **безопасен**.

## Контракт: чекбоксы критериев приёмки

- [x] `_participant_names` на `aiosqlite.Row` не бросает `AttributeError`;
      возвращает `{user_id: author_name}` (`web/api/chat_lore.py:678-683`).
- [x] `.get` на `aiosqlite.Row` в исправленном пути отсутствует; доступ —
      канонический `services.database.row_get`; импорт добавлен `:44`.
- [x] Маппинг не изменён семантически: фильтр `user_id` истинен +
      непустой `author_name.strip()`; значения — **КАК ЕСТЬ** (без
      strip/чистки), `int(None)` невозможен (фильтр до ключа).
- [x] Fail-open `except Exception` сохранён (`:684-688`), формат WARNING без
      имён/текстов — только `chat_id` (R17). На исправленном коде не
      срабатывает.
- [x] Пусто/все отфильтрованы → `None` (uid-fallback штатный).
- [x] Строка без колонки → `row_get` даёт default, строка пропускается.
- [x] Превентивный grep T-2330 выполнен, результат зафиксирован (раздел выше).
- [x] Δ DDL = 0, Δ каталога/settings = 0, новых флагов/миграций нет
      (`git show a406440 --stat`: только `web/api/chat_lore.py` + новый тест).
- [x] R16: API relations не тронут — `{chat_id, relations_enabled, users[]}`,
      `_RELATIONS_LIST_MAX=100`; меняется только качество данных (имена).
- [x] R17/R18: в diff/отчёте нет секретов; логи не цитируют имена/тексты.
- [x] `parse_mode=None`: путь чисто web/JSON, Telegram-формирование не
      затрагивается.
- [x] Не сломаны F1/F2/F7/F20 — полный pytest зелёный.
- [x] `git diff --check a406440^ a406440` — чисто (exit 0).

## Тесты

- Целевой набор `tests/test_chat_lore_participant_names_round1024.py`:
  **6 passed**. Покрытие по spec §6: реальные `sqlite3.Row` (не dict-моки),
  маппинг+фильтрация (пустые/пробельные, `user_id=0`/NULL), пустой результат
  → `None`, отсутствующая колонка → без падения, dict-совместимость,
  документирующий корень `not hasattr(row, "get")`.
- Полный прогон `.venv/Scripts/python.exe -m pytest -q`:
  **7516 passed, 1 warning, 0 failed** (108.53s) — совпадает с заявленным.
  Единственный warning — сторонний `StarletteDeprecationWarning`
  (fastapi.testclient/httpx), к F18 отношения не имеет.
- Тесты детерминированы и независимы (in-memory SQLite, локальный стаб
  `_FakeDB`, без сети/БД).

## Итог

F18 готова к приёмке. Найденный дефект-одноклассник в `services/oversight.py`
не входит в scope F18 и уже задокументирован как follow-up (T-2330); при
планировании следующей итерации завести отдельную задачу — иначе `last_active_ts`
Oversight продолжит молча деградировать, а «тихий» broad-except снова спрячет
класс бага.
