# Фича F8 — `hybrid-tool-calling-round1015` (Гибридный вызов функций: Fast-Track + Tool Calling)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 14.09.2026). T-1611…T-1617 выполнены; гейты T-1610/T-1618 — `[ ]`.
> **Раунд:** 10.15. **Нумерация:** T-1610…T-1618 (продолжает F7 T-1609).
> **Тип:** backend (LLM/tools). **Приоритет:** **P1**.
> **Зависимости:** **F6** (fast-track реестр) — обязательно; **F9** (`get_recent_history`) — общий tool-сет.
> **Конфликт файлов:** `services/tool_schemas.py`, `services/tool_router.py`, `services/direct_chat_service.py`, `bot.py` (DI-kwargs, порядок роутеров не трогать).
> **ТЗ:** `plans/current_task.md`, UPD §4 (строки 130-135).
> **Эпик:** `Epic: Багфиксы Графа памяти, Воркера Сна и Ностальгии round1015`.
> **Baseline:** HEAD `798e044`; pytest **5589 passed / 0 failed**; каталог **435/90/406/411/88/19**.

## 0. Цель

Дать основной LLM чата доступ к функциям через JSON-Schema tools, сохранив Fast-Track regex (F6) как быстрый путь в обход LLM. Свободная форма должна распознаваться моделью и исполняться бэкендом; скачивание файла — на бэкенде с фиктивным `tool_response`.

**Текущее состояние (Step 0):** tool-loop `services/tool_loop.py` (лимиты 4 раунда / 2 вызова); реестр `services/tool_router.py:127-143`; схемы `services/tool_schemas.py:93-94` (3 инструмента); вызов из `direct_chat_service.py:610-617`; DI `bot.py:422-423`.

## 1. Требования (UPD §4)

- [x] Основная LLM чата получает инструменты (JSON Schema).
- [x] Текстовые команды F6 остаются Fast-Track (regex, обход LLM).
- [x] Свободная форма → LLM распознаёт интент → tool_call → исполнение на бэкенде.
- [x] **Корнер-кейс файлов:** скачивание исполняется на бэкенде, MP4 отправляется сам, в LLM — фиктивный `{"status":"success","message":"Файл успешно загружен в чат"}`.

## 2. Целевые модули (`file:line` на HEAD `798e044`)

- `services/tool_schemas.py:93-94` — новые схемы + `TOOL_CALLING_TOOLS`.
- `services/tool_router.py:88-143` — `ToolDeps`/`ToolContext`/`dispatch` + методы инструментов.
- `services/direct_chat_service.py:610-617` — контекст с `bot`/`reply_to_message_id`.
- `bot.py:422-423` — DI-kwargs (`video`/`downloader`/`health`).
- (опц.) `services/media_send.py` — общий `_send_media`.
- Тесты: новый `tests/test_tool_calling_round1015.py`; регресс tool-loop/direct_chat.

## 3. Инварианты (constraints)

- **Порядок роутеров `bot.py` не менять** (только DI-kwargs). Fast-Track приоритет — порядок 0d–0g + F6-yield.
- **Существующие инструменты/схемы не менять** (снапшот-тест).
- `TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2` — не менять.
- **Успех `download_media` только после реальной отправки файла**; иначе `status:"error"`.
- R16/R17 (в логи — только имя инструмента/класс ошибки, без URL/текстов).
- Каталог-инварианты **435/90/406/411/88/19** — **Δ=0**.
- `media/`/`.env` не трогать.
- **Ревью-гейты:** полный `pytest` 0 регрессий, R17-скан, русские commits.

## 4. Зависимости

- **Вверх:** **F6** (реестр/приоритет), **F9** (`get_recent_history`).
- **Вниз:** нет.
- **Конфликт файлов:** `tool_schemas.py`/`tool_router.py` делит с F9 (аддитивно, F9 вливать после/вместе).

## 5. Definition of Done

- [x] `TOOL_CALLING_TOOLS` = 7 инструментов; существующие схемы не изменены.
- [x] Fast-Track не уходит в LLM; свободная форма вызывает инструменты.
- [x] `download_media`: файл в чате + фиктивный success в LLM; сбой → честный error.
- [x] Таймауты/лимиты/fail-safe соблюдены; R17.
- [x] Полный `pytest` **0 failed**; каталог Δ=0.

## 6. Чек-лист задач

- [ ] **T-1610 (@Architect, гейт):** спека + ADR (tool-сет, приоритеты, корнер-кейс файлов, лимиты, R17). *(выполнено)*
- [x] **T-1611 (@Builder):** `services/tool_schemas.py` — новые схемы `summarize_video`/`download_media`/`get_bot_health` (+ `get_recent_history` из F9); расширить `TOOL_CALLING_TOOLS` (порядок канона R9).
- [x] **T-1612 (@Builder):** `services/tool_router.py` — `ToolDeps`(+`video`/`downloader`/`health`)/`ToolContext`(+`bot`/`reply_to_message_id`/`user_id`); `dispatch`-ветки.
- [x] **T-1613 (@Builder):** `_summarize_video` (делегирование `YoutubeSummarizerService`, mode summary/transcript, truncate, error-строки).
- [x] **T-1614 (@Builder):** `_download_media` — корнер-кейс: реальная отправка MP4 (`_send_media`) + фиктивный `tool_response`; сбой → `status:"error"`; `wait_for` таймаут; удаление tmp.
- [x] **T-1615 (@Builder):** `_get_bot_health` (CheckupLogsFetcher+CheckupService); `direct_chat_service` — контекст с `bot`/`reply_to_message_id`; `bot.py` — DI-kwargs.
- [x] **T-1616 (@Builder):** `tests/test_tool_calling_round1015.py` (кейсы §10 спеки: состав, приоритет, свободная форма, корнер-кейс, лимиты, R17, обратная совместимость).
- [x] **T-1617 (@Builder):** гейты: полный `pytest` **0 failed**, каталог Δ=0, R17-скан, `git diff --check`; русский commit.
- [ ] **T-1618 (@PM/@Reviewer, гейт):** сверка DoD, ревью корнер-кейса скачивания и R17, подтверждение приоритета Fast-Track.

## 7. Открытые вопросы (@Architect → владелец)

- Решений, требующих Human Gate, нет. Сет из 7 инструментов (выше soft-ориентира «≤6») обоснован в ADR-1015-3.

## 8. Feature flag / progressive delivery

- **Feature flag не требуется:** расширение существующего tool-механизма; гейт скачивания — `flags.download_enabled`. Rollback = `git revert`.
- **Progressive delivery неприменим.** Мониторинг — `[tools]`-логи.
