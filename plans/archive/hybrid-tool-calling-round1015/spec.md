# Спека F8 — `hybrid-tool-calling-round1015` (Гибридный вызов функций: Fast-Track regex + Tool Calling)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, 14.09.2026). T-1611…T-1617 выполнены; гейты T-1610/T-1618 — `[ ]`.
> **Раунд:** 10.15. **Тип:** backend (LLM/tools). **Приоритет:** P1. **T-ID:** T-1610…T-1618.
> **ТЗ:** `plans/current_task.md` UPD §4 (строки 130-135). **ADR:** [`adr-1015-3-tool-calling.md`](adr-1015-3-tool-calling.md).
> **Зависимости:** **F6** (fast-track реестр/приоритет) — обязательно; **F9 `recent-history-tool-round1015`** (инструмент `get_recent_history` подключается к общему tool-сету).
> **Конфликт файлов:** `services/tool_schemas.py`, `services/tool_loop.py`, `services/tool_router.py`, `services/direct_chat_service.py`, `bot.py` (только DI-kwargs, порядок роутеров не трогать).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19. **Прецеденты:** эпик 3.3 (tool_loop/tool_router/tool_schemas), `plans/archive/tg-video-tool-calling-fixes`, multimodal pipeline.

## 1. Цель

Основная LLM чата (DeepSeek, `direct_chat`) получает доступ к функциям через **JSON Schema tools**. **Fast-Track regex остаётся и приоритетнее:** канонические текстовые команды F6 (`Бот, найди`, `Бот, скачай`, …) мгновенно перехватываются функциональными воркерами **в обход LLM**. Если же юзер пишет свободной формой («Олег, скачай этот видос пожалуйста», «сделай выжимку из этого ролика»), LLM распознаёт интент и вызывает соответствующий инструмент — гибридный путь.

## 2. Сосуществование путей и приоритеты

```
сообщение
 ├─ 0c factcheck (bare «фактчек»)        ─┐
 ├─ 0d search  (prefix+найди/поищи/загугли)│ Fast-Track: консьюм, LLM НЕ вызывается
 ├─ 0e youtube (prefix+…)                  │ (F6; regex/regex+URL)
 ├─ 0f web     (prefix+…)                  │
 ├─ 0g checkup (bare «чекап» / prefix+…)  ─┘
 ├─ 0h direct_chat
 │    └─ tool_loop → LLM (tools=TOOL_CALLING_TOOLS)
 │         └─ решение модели: обычный текст ИЛИ tool_call
 └─ 4e download (prefix+скачай/загрузи/стяни) — по пропагации (F6-yield)
```

- Порядок роутеров `bot.py` **не меняется**. Fast-Track выигрывает по порядку (0d–0g до 0h) и по F6-yield (download).
- **Инвариант:** если сообщение совпадает с `префикс + канонический триггер`, оно НЕ доходит до LLM (F6). Инструменты вызываются только из свободной формы / не-триггерного текста.
- Tool Calling — уже существующий механизм direct_chat (`tool_router is not None`). Данная фича **расширяет набор инструментов и контекст**, не меняя Fast-Track.

## 3. JSON-Schema инструменты (итоговый tool-сет)

Порядок `TOOL_CALLING_TOOLS` сохраняет канон R9 (память → лор → веб) и добавляет новые в конце. **Существующие имена/схемы не менять** (модель опирается на description).

| Инструмент | Статус | Назначение | Аргументы |
|---|---|---|---|
| `query_chat_memory` | существует | история/факты/счёт упоминаний | `query`, `time_range` |
| `dig_into_lore` | существует | старое/ностальгия/годы | `query`, `year?`, `person?`, `mode?` |
| `execute_web_search` | существует | поиск/гугл, свежие факты | `query` |
| `summarize_video` | **новый** | выжимка/транскрипт ролика по ссылке | `url` (string), `mode` enum `summary`/`transcript` (default `summary`) |
| `download_media` | **новый** | скачать видео по ссылке и прислать в чат | `url` (string) |
| `get_bot_health` | **новый** | статус/здоровье бота (чекап-данные) | без параметров (`{}`) |
| `get_recent_history` | **новый (F9)** | кратковременная память (стенограмма) | `depth` (int 1..150) **или** `query` (string) |

Итого **7 инструментов** (при soft-ориентире R9 «≤6»): рост оправдан — каждый покрывает отдельный интент owner-TZ (поиск/видео/скачивание/здоровье/память/лор/кратковременная память). В описаниях явно указать приоритеты: «для свежих фактов — `execute_web_search`; для прошлого чата — `query_chat_memory`/`dig_into_lore`; для последних сообщений — `get_recent_history`».

Пример схемы (остальные — по образцу `services/tool_schemas.py:13-91`):
```python
TOOL_SUMMARIZE_VIDEO = {
    "type": "function",
    "function": {
        "name": "summarize_video",
        "description": ("Выжимка или расшифровка видео по ссылке (YouTube/платформы/прямой файл). "
                        "Вызывай, когда пользователь просит пересказать/расшифровать ролик и дал ссылку. "
                        "mode='transcript' — сырой текст; mode='summary' — сжатая выжимка."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Ссылка на видео."},
            "mode": {"type": "string", "enum": ["summary", "transcript"], "default": "summary"},
        }, "required": ["url"], "additionalProperties": False},
    },
}
TOOL_DOWNLOAD_MEDIA = {
    "type": "function", "function": {
        "name": "download_media",
        "description": ("Скачать видео по ссылке и отправить файлом в этот чат. "
                        "Вызывай на просьбу «скачай/загрузи/стяни <ссылка>» в свободной форме."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Ссылка на видео."},
        }, "required": ["url"], "additionalProperties": False}}}
TOOL_GET_BOT_HEALTH = {
    "type": "function", "function": {
        "name": "get_bot_health",
        "description": ("Показать статус/здоровье бота (логи, память, сервисы). "
                        "Вызывай на вопрос «ты в порядке / как дела / чекни здоровье», "
                        "если команда пришла свободной формой."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}
```

## 4. Интеграция с LLM-клиентом и tool-loop

- **LLM-клиент не меняется:** `llm_client.generate_chat(messages, tools=…, tool_choice="auto", chat_id=…)` (`services/llm_client.py:962-1048`) уже парсит `tool_calls`/`LLMToolCall`.
- **Цикл `services/tool_loop.py`** переиспользуется как есть: `chat_with_tools(llm, messages, tools, router, ctx, temperature, chat_id)`.
- **`direct_chat_service`** (`:610-617`) передаёт `tools=TOOL_CALLING_TOOLS`, `router=self.tool_router`, `ctx=ToolContext(chat_id, query)`. Меняем только:
  1. `ToolContext` расширяется: `bot`, `reply_to_message_id`, `user_id` (аддитивно, дефолты `None` — обратная совместимость).
  2. В месте вызова добавляем `bot=bot`, `reply_to_message_id=message.message_id`, `user_id=user_id`.
  3. `TOOL_CALLING_TOOLS` дополняется новыми схемами.
- **`tool_loop` обработка:** `assistant(tool_calls)` → `router.dispatch(name, args, ctx)` → `role:"tool"` c результатом (существующий код, `:72-90`). `router.dispatch` **никогда не бросает** — при сбое возвращает `ОШИБКА <tool>: <class>` (`tool_router.py:138-143`), модель видит честный текст.

## 5. Расширение `ToolDeps` / `ToolRouter` (DI из `bot.py:422-423`)

```python
class ToolDeps:
    def __init__(self, search, memory, aliases=None, *,
                 video=None, downloader=None, health=None) -> None: ...
class ToolContext:
    def __init__(self, chat_id, query, *, bot=None, reply_to_message_id=None, user_id=None): ...
```
- `video` — `YoutubeSummarizerService` (создаётся в `bot.py:384`) или общий транскриптор+вышка для `summarize_video`.
- `downloader` — общий `VideoDownloader` (`bot.py`, 4e/0e-shared инстанс).
- `health` — `CheckupService` + `CheckupLogsFetcher` (`bot.py:392-405`) для `get_bot_health`.
- `bot.py` — **только DI-kwargs** (передать существующие инстансы в `ToolDeps`), порядок роутеров не трогать.

## 6. Корнер-кейс файлов (UPD §4 — подводный камень)

`download_media` исполняется **на бэкенде** и сам отправляет MP4 в Telegram; LLM работает только с текстом, поэтому возвращаем **фиктивный** `tool_response`, иначе модель начнёт «печатать» видео (галлюцинация):
```python
async def _download_media(self, arguments, ctx) -> str:
    url = self._require_str(arguments, "url")
    if ctx.bot is None or self.deps.downloader is None:
        return '{"status": "error", "message": "Скачивание недоступно"}'
    try:
        path = await asyncio.wait_for(
            self.deps.downloader.download(url, "direct"), timeout=_DOWNLOAD_TOOL_TIMEOUT)
    except Exception as exc:
        logger.warning("[tools] download failed | error=%s", type(exc).__name__)  # R17: без URL
        return json.dumps({"status": "error", "message": "Не удалось скачать видео"}, ensure_ascii=False)
    try:
        await _send_media(ctx.bot, ctx.chat_id, path, reply_to=ctx.reply_to_message_id)
    finally:
        path.unlink(missing_ok=True)
    return json.dumps({"status": "success", "message": "Файл успешно загружен в чат"}, ensure_ascii=False)
```
- **Успех — только после реальной отправки.** При сбое возвращаем `status:"error"` (не врём модели).
- `_send_media` — тонкий враппер над существующим `_send_file` (`handlers/video_download.py:502`) / `FSInputFile`+`supports_streaming=True`; вынести в общий helper (напр. `services/media_send.py`), чтобы не тянуть хендлер в сервис.
- `url` в логи не пишем (R17); `download_media` доступен только при `flags.download_enabled` (иначе `status:"error"`).

## 7. Остальные инструменты (поведение)

- **`summarize_video`:** делегирует `YoutubeSummarizerService` (URL) или общий транскриптор для нативных медиа; результат → `_truncate(..., _MEMORY_MAX_SYMBOLS)`. Ошибки → структурированный `ОШИБКА summarize_video: …`. `mode=transcript` → сырой текст (cap), `mode=summary` → выжимка. Только `http(s)`-URL: не-URL → `ОШИБКА`.
- **`get_bot_health`:** `CheckupLogsFetcher.fetch()` → `CheckupService.checkup(...)` (тот же путь, что 0g) → текст отчёта; пусто/ошибка → структурированный error. Кулдаун **не** применяем (инструмент — по интенту LLM), но лимит вызовов — tool-loop.
- **`get_recent_history`** — специфицирован в F9 (`recent-history-tool-round1015`); здесь только регистрация в `TOOL_CALLING_TOOLS` и `dispatch`-реестре.

## 8. Лимиты, итерации, fail-safe

- **Раунды:** существующие `TOOL_MAX_ROUNDS = 4` (`tool_loop.py:24`); **вызовов за раунд** — `_TOOL_CALLS_PER_ROUND_MAX = 2` (`:25`). Новых ключей каталога — нет.
- **Таймауты инструментов (код-константы):** `download_media` — `_DOWNLOAD_TOOL_TIMEOUT = 180.0` (в пределах NFR-4 эпика скачивания); `summarize_video` — бюджет внутри сервиса + `asyncio.wait_for`; `get_bot_health` — существующий бюджет фетчера логов; `execute_web_search` — существующий 25с.
- **Fail-safe:** провайдер отверг tools на 1-м раунде → один обычный ответ без tools (`tool_loop.py:49-56`, существующее); пустой финал/лимит раундов → `LLMBadResponseError` → молчание + 🗿 (существующие ветки direct_chat).
- **Tool-сбой** → `dispatch` возвращает `ОШИБКА …`; `tool_loop` ловит исключение инструмента и передаёт модели текст (`:83-88`).
- **R17:** в логи — только `tool=<name>`, `out_chars`, `type(exc).__name__`; URL/тексты/секреты не логировать.
- **Persona:** инструменты доступны независимо от Имени; описание/стиль ответа задаётся CHAT_SYSTEM_PROMPT+persona-блоком (F6-имя не влияет на доступность тулов, только на триггеры/wake-word).

## 9. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `services/tool_schemas.py:93-94` | + `TOOL_SUMMARIZE_VIDEO`, `TOOL_DOWNLOAD_MEDIA`, `TOOL_GET_BOT_HEALTH`; `get_recent_history` из F9; расширить `TOOL_CALLING_TOOLS`. |
| 2 | `services/tool_router.py:88-143` | `ToolDeps`+`ToolContext` расширены; `dispatch`-реестр + методы `_summarize_video`, `_download_media`, `_get_bot_health`, `_get_recent_history`. |
| 3 | `services/direct_chat_service.py:610-617` | `ToolContext` с `bot`/`reply_to_message_id`/`user_id`. |
| 4 | `bot.py:422-423` | DI: `ToolDeps(..., video=…, downloader=…, health=…)`; порядок роутеров не трогать. |
| 5 | `services/media_send.py` (новый, если факторинг) | Общий `_send_media` (FSInputFile/supports_streaming) для 4e и tool. |
| 6 | `tests/test_tool_calling_round1015.py` (новый) | См. §10. |

**Не трогать:** `TOOL_MAX_ROUNDS`, `_TOOL_CALLS_PER_ROUND_MAX`, существующие схемы/имена, `media/`/`.env`, порядок роутеров.

## 10. Тест-план

Новый `tests/test_tool_calling_round1015.py` (моки LLM/сервисов; без сети):
1. **Состав тулов:** `TOOL_CALLING_TOOLS` содержит 7 имён; существующие схемы не изменены (снапшот-сравнение).
2. **Fast-Track приоритет:** сообщение `Бот, скачай <url>` (и `Олег, скачай`) обрабатывается download-воркером; `chat_with_tools`/LLM НЕ вызывается (мок-ассерт).
3. **Свободная форма:** «скачай этот видос пожалуйста» → LLM возвращает `tool_call download_media` → `dispatch` шлёт файл через мок-bot → в `role:"tool"` приходит `{"status":"success",...}`.
4. **Корнер-кейс скачивания:** при сбое downloader → `status:"error"`, `bot.send_*` НЕ вызывается, нет фейкового success.
5. **summarize_video:** URL+mode summary/transcript → вызов сервиса, результат усечён; не-URL → error-строка.
6. **get_bot_health:** fetch+checkup вызываются, текст возвращается; сбой → error.
7. **tool-loop лимиты:** >2 tool_calls в раунде обрезаются; 4 раунда → `LLMBadResponseError`; провайдер без tools → plain answer.
8. **R17:** в логах нет URL/текста сообщений (caplog-ассерт).
9. **Обратная совместимость:** `tool_router=None` → path без tools зелёный.

**Гейты:** полный `pytest` 0 failed; каталог Δ=0; R17-скан; `git diff --check`; русский commit.

## 11. Каталог-Δ / feature flag

- **Δ = 0** (новых ключей нет; лимиты — код-константы, download гейтится существующим `flags.download_enabled`).
- **Feature flag не требуется** (расширение существующего mechanisms); rollback = `git revert`.
- **Progressive delivery неприменим.** Мониторинг: `[tools] round=… tool=…` в логах; доля tool_calls по инструментам.

## 12. Риски

| Риск | Митигация |
|---|---|
| Галлюцинация «печати» файла | Фиктивный `tool_response` §6; успех только после реальной отправки. |
| Рост tool-сета → путаница модели | Чёткие description + приоритетные подсказки; cap вызовов/раундов. |
| Долгий `download_media` держит tool-loop | `wait_for` + консьюм существующих таймаутов; лимит раундов. |
| Дублирование с Fast-Track | Fast-Track порядок 0d–0g + F6-yield; тест приоритета. |
| Утечка URL/текста в логи | R17-дисциплина: только имя инструмента/класс ошибки. |
| Layering (сервис → handler `_send_file`) | Вынести `_send_media` в `services/media_send.py`. |

## 13. Критерии приёмки (DoD)

- [ ] `TOOL_CALLING_TOOLS` содержит 7 инструментов; существующие схемы не изменены.
- [ ] Fast-Track regex по-прежнему выигрывает и не уходит в LLM.
- [ ] Свободная форма корректно вызывает инструменты через tool-loop.
- [ ] `download_media`: MP4 реально уходит в чат, в LLM — `{"status":"success", "message":"Файл успешно загружен в чат"}`; при сбое — честный error.
- [ ] Лимиты/таймауты/fail-safe соблюдены; R17; полный `pytest` 0 failed; каталог Δ=0.

## 14. Инварианты

Порядок роутеров `bot.py` не менять (только DI-kwargs), `TOOL_MAX_ROUNDS`/`_TOOL_CALLS_PER_ROUND_MAX` не менять, R16/R17, `media/`/`.env` не трогать, каталог Δ=0.
