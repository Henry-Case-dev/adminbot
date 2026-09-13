# Фича F9 — `recent-history-tool-round1015` (Инструмент `get_recent_history` — кратковременная память)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 14.09.2026). Код + тесты готовы; pytest **5752 passed / 0 failed**; каталог Δ=0; коммит не выполнялся (запрет раунда).
> **Раунд:** 10.15. **Нумерация:** T-1619…T-1624 (продолжает F8 T-1618).
> **Тип:** backend (LLM/tools). **Приоритет:** **P1**.
> **Зависимости:** **F8** (tool-loop/реестр/схемы) — обязательно; **F6** (fast-track приоритет).
> **Конфликт файлов:** `services/tool_schemas.py`, `services/tool_router.py` — делит с F8 (аддитивно).
> **ТЗ:** `plans/current_task.md`, UPD §5 (строки 137-144).
> **Эпик:** `Epic: Багфиксы Графа памяти, Воркера Сна и Ностальгии round1015`.
> **Baseline:** HEAD `798e044`; pytest **5589 passed / 0 failed**; каталог **435/90/406/411/88/19**.

## 0. Цель

LLM получает тул прямого чтения **сырого лога недавних сообщений** (L1-окно): `depth` (≤150) или `query` (по последним часам). Отдаёт точную хронологическую стенограмму `Имя: текст` — для «что обсуждали 10 минут назад», «кто скинул ту ссылку», «кто прав в споре».

**Текущее состояние (Step 0):** `database.get_recent_messages(chat_id, limit)` уже есть (`database.py:1405-1417`, ASC); FTS через `memory.search_long_term`; аналогичные инструменты `query_chat_memory`/`dig_into_lore` (`tool_router.py:167-381`); `_resolve_name`/`_truncate`/`keywords` в `tool_router.py`.

## 1. Требования (UPD §5)

- [ ] Новый инструмент `get_recent_history` в tool-сете основной LLM.
- [ ] Параметры: `depth` (кол-во вглубь, до 150) **ИЛИ** `query` (поиск по сырой SQLite последних часов).
- [ ] Формат ответа — точная хронологическая стенограмма (`Имя: текст`), не векторный RAG.
- [ ] Скоуп — текущий чат; лимиты/обрезка; приватность/R17.

## 2. Целевые модули (`file:line` на HEAD `798e044`)

- `services/tool_schemas.py:93-94` — `TOOL_GET_RECENT_HISTORY` + `TOOL_CALLING_TOOLS`.
- `services/tool_router.py:129-133,167-230` — `dispatch`-ветка + `_get_recent_history`; переиспользование `_require_query`/`_resolve_name`/`_truncate`/`keywords`.
- `services/database.py:1405-1417` — `get_recent_messages` (переиспользовать as-is).
- Тесты: новый `tests/test_recent_history_tool_round1015.py`.

## 3. Инварианты (constraints)

- **Chat-скоуп строго `ctx.chat_id`** (R16); кросс-чатовые выборки запрещены.
- **R17:** в логи — только `chat_id`/count/out_chars; **без** текста сообщений/URL/имён.
- **DDL не требуется** — read-API `get_recent_messages` уже есть.
- Сбой инструмента → структурированная `ОШИБКА`, tool-loop не падает, модель не выдумывает.
- Каталог-инварианты **435/90/406/411/88/19** — **Δ=0** (лимиты — код-константы).
- `media/`/`.env`/порядок роутеров `bot.py` не трогать.
- **Ревью-гейты:** полный `pytest` 0 регрессий, R17-скан, русские commits.

## 4. Зависимости

- **Вверх:** **F8** (общий tool-loop/реестр/`TOOL_CALLING_TOOLS`), **F6** (fast-track).
- **Вниз:** нет.
- **Конфликт файлов:** `tool_schemas.py`/`tool_router.py` делит с F8 — вливать F9 после/вместе с F8.

## 5. Definition of Done

- [ ] `get_recent_history` доступен LLM; `depth` (≤150) либо `query` (последние часы); chat-скоуп.
- [ ] Точная хронологическая стенограмма `Имя: текст`; клампы/обрезка соблюдены.
- [ ] Переиспользован `database.get_recent_messages`; DDL не введён.
- [ ] R16/R17; при сбое — структурированная ошибка.
- [ ] Полный `pytest` **0 failed**; каталог Δ=0.

## 6. Чек-лист задач

- [ ] **T-1619 (@Architect, гейт):** спека инструмента (схема, depth/query-семантика, формат, лимиты, R16/R17). *(выполнено @Architect)*
- [x] **T-1620 (@Builder):** `TOOL_GET_RECENT_HISTORY` в `tool_schemas.py` + регистрация в `TOOL_CALLING_TOOLS` (заведено F8; проверено инвариантным тестом 7 тулов).
- [x] **T-1621 (@Builder):** `_get_recent_history` в `tool_router.py` — путь `depth` (`get_recent_messages`) + путь `query` (FTS + фильтр окна + сортировка ASC); формат `Имя: текст`; клампы/обрезка/пустая-фраза.
- [x] **T-1622 (@Builder):** R17/R16-дисциплина логирования + структурированные ошибки; страховочный `wait_for`.
- [x] **T-1623 (@Builder):** `tests/test_recent_history_tool_round1015.py` (20 кейсов §8) + гейты: полный `pytest` **0 failed**, каталог Δ=0, R17-скан, `git diff --check`. *(коммит не выполнялся — запрет раунда)*
- [ ] **T-1624 (@PM/@Reviewer, гейт):** сверка DoD, ревью скоупа/R17/R16, подтверждение интеграции в F8 tool-сет.

## 7. Открытые вопросы (@Architect → владелец)

- Решений, требующих Human Gate, нет. Δ=0 обоснован (spec §6).

## 8. Feature flag / progressive delivery

- **Feature flag не требуется;** доступность наследует гейт tool-loop. Rollback = `git revert`.
- **Progressive delivery неприменим.**
