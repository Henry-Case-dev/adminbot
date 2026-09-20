# Задачи: sqlite-row-get-fix-round1024

> **Раунд 10.24 (UPD4-D)** · Приоритет **P2** · Severity **Low-Medium** · Шаг 1 @PM · Тип: backend-багфикс (web API)
> **ТЗ:** `plans/current_task.md`, секция **UPD4** (строки 297–316). Файл untracked; секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Отчёт @Memory: `upd4-live-bug-clusters-round1024` (кластер D).
> **Прод-логи:** `web.api.chat_lore: AttributeError: 'sqlite3.Row' object has no attribute 'get'` (`chat_lore.py:675`).
> **Опция владельца:** возможен **merge в F4** `dossier-live-feed-round1024` (там же `_participant_names`/`get_active_participants`) — по умолчанию сделано **отдельной фичей** (другой web-API файл: `chat_lore.py` vs `oversight.py`); см. открытый вопрос №6 в backlog.

## Цель
`_participant_names` вызывает `r.get(...)` на `aiosqlite.Row` (это `sqlite3.Row` без `.get`) → `AttributeError`, имена участников недоступны, срабатывает uid-fallback. Заменить на существующий `row_get`.

## Что уже есть (координаты)
- Баг: `web/api/chat_lore.py:666-682::_participant_names` — `r.get("user_id")`/`r.get("author_name")` (`:675-676`).
- Источник данных: `services/database.py:3714-3726::get_active_participants` → `await cursor.fetchall()` (строки с `row_factory = aiosqlite.Row`).
- Прецедент фикса: `services/database.py:145-153::row_get` (`hasattr(row, "get")` → `.get`, иначе `row[key]` с fallback).
- Прецедент нормализации Row→dict: `services/tool_router.py:1030-1031` (`rows = [dict(row) for row in rows]`).
- Обработка уже есть: `except Exception` в `_participant_names` (`:677-681`) — из-за этого баг «тихий» (uid-fallback + WARNING).

## Задачи
- [x] **T-2328** [@Builder] `web/api/chat_lore.py:666-682::_participant_names`: заменить `r.get(...)` на `row_get(r, ...)` (импорт из `services.database`); корректный маппинг `{user_id: author_name}`. Рассмотреть `[dict(row) for row in rows]` как альтернативу из прецедента `tool_router.py:1030-1031` — выбрать минимальный вариант (решает @Reviewer).
- [x] **T-2329** [@Builder] Тест: `_participant_names` на `aiosqlite.Row` **не падает**, возвращает корректный маппинг; uid-fallback (`None`) только при реальном отсутствии строк; регресс-тест на воспроизведение исходного `AttributeError`.
- [ ] **T-2330** [@Reviewer] Ревью + **превентивный grep**: нет ли аналогичных `.get(...)` на `aiosqlite.Row`/`sqlite3.Row` в `web/api/**` и сервисах (закрыть класс багов, а не единичный случай).
- [ ] **T-2331** [@DevOps] Деплой + live: в прод-логах нет `[relations] имена участников недоступны ... no attribute 'get'`; имена участников отдаются корректно; отчёт.

## Критерии приёмки
- `_participant_names` работает на `aiosqlite.Row` без `AttributeError`; имена участников возвращаются.
- В прод-логах исчез `AttributeError: 'sqlite3.Row' object has no attribute 'get'`.
- Превентивный grep по `web/api/**` не находит аналогичных обращений `.get` на Row (или найденное зафиксировано follow-up).
- Полный pytest — 0 failed; `git diff --check` чист.

## Риски
- **R1 (Low-Medium):** «тихий» характер бага (except → uid-fallback) маскирует регресс → регресс-тест T-2329.
- **R2 (Low):** аналогичные `.get` в других местах → превентивный grep T-2330.
- **R3 (Low):** изменение web-API затрагивает relations-ответ → проверка контракта `users/_RELATIONS_LIST_MAX` не деградирует.

## Зависимости / ступени
- Зависит от: — (независимый мелкий фикс).
- Зависимость/пересечение: `web/api/chat_lore.py` — эксклюзив F18; общий контекст с F4 (`_participant_names`/`get_active_participants`) — но разные файлы (`web/api/chat_lore.py` vs `web/api/oversight.py`). При решении владельца «merge в F4» — перенести задачи в `dossier-live-feed-round1024/tasks.md` (ID сохраняются).
- Feature flag: **не требуется** (чистый багфикс, поведение-fix).
- Откат: `git revert`; **Δ DDL = 0**, Δ каталога = 0.
