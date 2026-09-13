# Спека F9 — `recent-history-tool-round1015` (Инструмент `get_recent_history` — кратковременная память)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). Код + тесты готовы; pytest **5761 passed / 0 failed**; каталог Δ=0; коммит не выполнялся (запрет раунда).
> **Раунд:** 10.15. **Тип:** backend (LLM/tools). **Приоритет:** P1. **T-ID:** T-1619…T-1624.
> **ТЗ:** `plans/current_task.md` UPD §5 (строки 137-144). **Зависимости:** **F8 `hybrid-tool-calling-round1015`** (общий tool-loop/реестр) — обязательно; **F6** (fast-track).
> **Конфликт файлов:** `services/tool_schemas.py`, `services/tool_router.py` (делит с F8 — аддитивно, вливать вместе/после).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19. **Прецеденты:** `query_chat_memory`/`dig_into_lore` (`tool_router.py:167-381`), L1-FTS, `database.get_recent_messages` (`database.py:1405-1417`).

## 1. Цель

Дать LLM инструмент прямого чтения **сырого лога недавних сообщений (L1-окно)** — для вопросов «Что мы обсуждали 10 минут назад?», «Кто скинул ту ссылку?», «Кто прав в этом споре?». В отличие от векторного RAG (смыслы) инструмент отдаёт **точную хронологическую стенограмму** (`Имя: текст`) за короткий промежуток.

## 2. Входные параметры и семантика

```python
TOOL_GET_RECENT_HISTORY = {
    "type": "function", "function": {
        "name": "get_recent_history",
        "description": ("Недавняя стенограмма ЭТОГО чата: последние сообщения по порядку (Имя: текст). "
                        "Вызывай на «что обсуждали 10 минут назад», «кто скинул ту ссылку», "
                        "«кто прав в споре», «перечитай последние сообщения». "
                        "depth — сколько сообщений вглубь (до 150); ЛИБО query — поиск по недавним "
                        "сообщениям последних часов. Это точная хронология, НЕ смысловой RAG."),
        "parameters": {"type": "object", "properties": {
            "depth": {"type": "integer", "minimum": 1, "maximum": 150,
                      "description": "Сколько последних сообщений вернуть (по умолчанию 50)."},
            "query": {"type": "string",
                      "description": "Фрагмент/тема для поиска по недавним сообщениям (последние часы)."},
        }, "additionalProperties": False},
    },
}
```

- Ровно один из параметров осмыслен; если переданы оба — **приоритет `query`** (целевой поиск важнее среза).
- Если ни один не передан → fallback `depth = DEFAULT (50)`.
- `depth` клампится в `1.._HISTORY_MAX_DEPTH (150)`; `query` нормализуется токенами (`tool_router.keywords`).

## 3. Поведение (два пути)

**Путь A — `depth` (хронологический срез):**
```python
rows = await db.get_recent_messages(ctx.chat_id, depth)   # ASC, последние N
```
`db` — из `self.deps.memory.db` (как в `_dig_into_lore`, `tool_router.py:324`) или `self.deps.db` (F8). Формат строки: `f"{name}: {text}"` (R16: имя из алиаса/author_name/user_id через `_resolve_name`; медиа-события — текстом/маркером, пустой текст пропускается). Результат — единый хронологический список.

**Путь B — `query` (поиск по недавним часам):**
```python
since = int(time.time()) - _HISTORY_QUERY_WINDOW_SECONDS          # «последние часы»
rows = await self.deps.memory.search_long_term(ctx.chat_id, keywords(query), limit=_HISTORY_SEARCH_LIMIT)
rows = [dict(r) for r in rows]                                    # T-678: aiosqlite.Row
rows = [r for r in rows if int(r.get("timestamp") or 0) >= since]
rows.sort(key=lambda r: int(r.get("timestamp") or 0))             # хронологически
```
Окно/лимиты — **код-константы** (см. §6): `_HISTORY_QUERY_WINDOW_SECONDS`, `_HISTORY_SEARCH_LIMIT`.

**Общее:** заголовок-шапка не нужен (модель должна видеть чистую стенограмму); при пустом результате — честная строка `«За последние сообщения ничего не нашлось»` (модель не выдумывает). Обрезка — `_truncate(text, _HISTORY_MAX_SYMBOLS)`.

## 4. Скоуп и приватность

- **Chat-скоуп строго `ctx.chat_id`** (как все инструменты direct_chat; R16). Кросс-чатовые выборки запрещены.
- **R17:** в логи — только `chat_id`, количество строк, `out_chars`; **никогда** текст сообщений/URL/имена. Ошибка этапа → WARNING с `type(exc).__name__` и пустой результат (не роняем tool-loop).
- Инструмент **не является** обходом RBAC: он работает в контексте чата, где и так есть доступ к сообщениям (как `query_chat_memory`).

## 5. Интеграция в tool-calling (F8)

- Схема добавляется в `TOOL_CALLING_TOOLS` (F8 §3).
- Ветка `dispatch` (`tool_router.py:129-133`): `"get_recent_history": self._get_recent_history`.
- Контекст — существующий `ToolContext(chat_id, query, …)`; `ctx.query` используется как fallback, если модель не передала `query`, но передала свободный текст (совместимо с `_require_query`).
- Вызов исполняется **внутри** существующего tool-loop (лимиты F8: 4 раунда / 2 вызова за раунд). Отдельного таймаута не требуется (SQLite-чтение локальное), но обёртка `asyncio.wait_for(..., timeout=_HISTORY_TOOL_TIMEOUT)` — на всякий случай (код-константа, напр. 10с).

## 6. Лимиты (код-константы, каталог-Δ=0)

| Константа | Значение | Назначение |
|---|---|---|
| `_HISTORY_MAX_DEPTH` | 150 | верхняя граница `depth` (UPD §5 «до 150») |
| `_HISTORY_DEFAULT_DEPTH` | 50 | default при отсутствии параметров |
| `_HISTORY_SEARCH_LIMIT` | 80 | строк FTS на этапе `query` (до фильтра по окну) |
| `_HISTORY_QUERY_WINDOW_SECONDS` | 12·3600 | «последние часы» для `query` |
| `_HISTORY_MAX_SYMBOLS` | 3500 | обрезка результата (как `_MEMORY_MAX_SYMBOLS`) |
| `_HISTORY_TOOL_TIMEOUT` | 10.0 | страховочный таймаут `wait_for` |

Обоснование Δ=0: значения — внутренние safety-cap/tuning, не owner-настройки; прецедент — `_DIG_GRAPH_MAX_HOP_DEPTH`, `_MEMORY_FTS_LIMIT`, `_TOOL_CALLS_PER_ROUND_MAX`. Если владелец захочет регулировать depth из админки — отдельная будущая правка (+1 ключ `limits.history_max_depth`), не в этом раунде.

## 7. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `services/tool_schemas.py:93-94` | `TOOL_GET_RECENT_HISTORY` + в `TOOL_CALLING_TOOLS`. |
| 2 | `services/tool_router.py:129-133,167-230` | `dispatch`-ветка + `_get_recent_history`; переиспользовать `_require_query`/`_resolve_name`/`_truncate`/`keywords`. |
| 3 | `services/database.py:1405-1417` | `get_recent_messages` — **переиспользовать как есть** (read-API уже есть; DDL не нужен). |
| 4 | `tests/test_recent_history_tool_round1015.py` (новый) | См. §8. |

**Не трогать:** `get_recent_messages`-контракт, `query_chat_memory`/`dig_into_lore`, схему БД (DDL не нужен), каталог.

## 8. Тест-план

Новый `tests/test_recent_history_tool_round1015.py` (SQLite in-memory, без сети):
1. **depth:** N сообщений → стенограмма `Имя: текст` строго ASC; запрошен `depth=150` → кламп; `depth=0`/отрицательный → кламп в 1/дефолт.
2. **query:** релевантные строки за последние часы возвращаются хронологически; строки старше окна отфильтрованы; пустой результат → честная фраза.
3. **приоритет параметров:** переданы `depth` и `query` → работает `query`; ничего не передано → `_HISTORY_DEFAULT_DEPTH`.
4. **скоуп:** строки другого `chat_id` не попадают в результат.
5. **R16:** имя автора резолвится каскадом (alias → author_name → user_id), не выдумывается.
6. **R17:** в логах нет текста сообщений/URL (caplog-ассерт), только count/out_chars.
7. **сбой БД:** исключение → WARNING + `ОШИБКА get_recent_history: <class>` (tool-loop не падает, модель не выдумывает).
8. **интеграция F8:** `TOOL_CALLING_TOOLS` содержит `get_recent_history`; `dispatch` находит ветку.

**Гейты:** полный `pytest` 0 failed; каталог Δ=0; R17-скан; `git diff --check`; русский commit.

## 9. Каталог-Δ / feature flag

- **Δ = 0** (лимиты — код-константы; схема инструмента — код, не каталог).
- **Feature flag не требуется;** rollback = `git revert`. Доступность инструмента наследует гейт tool-loop (`tool_router is not None`).

## 10. Риски

| Риск | Митигация |
|---|---|
| Большая стенограмма «съест» контекст LLM | Клампы depth≤150 + обрезка `_HISTORY_MAX_SYMBOLS` + лимит FTS-строк. |
| Смешение с векторным RAG («смыслы») | Ясный description: «точная хронология, не RAG»; возврат сырых строк. |
| Утечка приватного текста в логи | R17: логируем только count/out_chars. |
| Пустой/шумный результат → галлюцинация | Честная фраза «ничего не нашлось», модель не выдумывает. |
| Тяжёлый FTS на каждый tool_call | Локальная SQLite + `limit` + страховочный `wait_for`. |

## 11. Критерии приёмки (DoD)

- [ ] `get_recent_history` доступен LLM: `depth` (≤150) либо `query` (последние часы), chat-скоуп.
- [ ] Возврат — точная хронологическая стенограмма `Имя: текст`; обрезка/клампы соблюдены.
- [ ] Переиспользован `database.get_recent_messages` (DDL не вводится).
- [ ] R16/R17 соблюдены; при сбое — структурированная ошибка без падения.
- [ ] Полный `pytest` 0 failed; каталог Δ=0.

## 12. Инварианты

Chat-скоуп (`ctx.chat_id`), R16/R17, порядок роутеров `bot.py` не трогать, `media/`/`.env` не трогать, каталог Δ=0 (лимиты — код-константы), DDL не требуется (read-API уже есть).
