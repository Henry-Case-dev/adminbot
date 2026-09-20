# spec.md — F13 `native-reply-media-context-round1024` (UPD4 баг A-1: медиа в контексте реплая)

> Раунд 10.24 (UPD4) · Приоритет **P1** · ADR: **ADR-1024-14** · Задачи: **T-2291…T-2298**
> ТЗ: `plans/current_task.md` UPD4 (стр. 274–279) — файл untracked, в git не коммитить, секреты/URL не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; прод `4314ea4`; SQLite `v12`; каталог **REGISTRY 457 / GROUPS 96 / `_TAB_BY_GROUP` 94**.
> **Граница:** F13 доставляет **факт нативного медиа в контекст LLM**. F14 (`native-media-tools-round1024`) даёт **инструментам** возможность скачать/суммаризовать это медиа. F13 **НЕ трогает** `services/tool_schemas.py`, `services/tool_router.py`, `handlers/**`.

## 1. Цель

Юзер реплаит «Бот что на видео» на **нативное TG-видео** — фразы нет в триггерах YouTube, запрос уходит в `direct_chat`, но контекст реплая **text-only**: сообщение с медиа и пустым текстом отбрасывается на всех трёх рендерах (`thread_chain`, `chat_context`, `Current_Question`). LLM физически «не видит» видео и не может вызвать инструмент.

Сделать так, чтобы **факт наличия нативного медиа** (тип + внутренний реф) доходил до модели в цепочке реплаев, окне контекста и `<Current_Question>`, **байт-в-байт не меняя** вывод при отсутствии медиа (регресс-инвариант ADR-1023-1/ADR-1023-2).

## 2. Что уже есть (координаты)

- **Триггеры YouTube** не содержат «что на видео»: `services/command_registry.py:25` (`транскрипт`, `че за видос`, `о чем видео`, `поясни за видос`) → свободная форма уходит в `direct_chat`.
- **Цепочка реплаев скипает пустой текст:** `services/thread_chain.py:131-146` (`text = row["text"] or ""`; `if text:` — узел без текста не попадает в цепочку/`<reply_chains>`).
- **Окно контекста скипает пустой текст:** `services/chat_context.py:107-110` (`text = (row["text"] or "").strip(); if not text: continue`).
- **Current_Question только текст:** `services/direct_chat_service.py:1220-1233` (`_strip_direct_prefix(message.text or "")`).
- **Нативное медиа на сообщении:** `message.video` / `message.video_note` / `message.document` (реплай — `message.reply_to_message`). Квалификатор видео — `handlers/youtube.py:286-321` (`_document_is_video`, `_resolve_video_media`); `voice`/`video_note`/`audio` для видео **не** квалифицируются.
- **Хранимое `media_type`:** `handlers/summary.py:125-143` (`_detect_media_type`): `video`/`video_note` → `"video"`, `document` → `"document"`, далее `photo`/`voice`/`audio`/`animation`/`sticker`/`other`; текст → `"text"`. Пустые «служебные» (`other`) не сохраняются (`:174-176`).
- **`media_type` доступен во всех чтениях:** `database.get_smart_message_by_tg_id` (`:1867-1876`), `get_recent_messages` (`:1783-1795`), `get_messages_around` (`:1800-1854`) — колонка `media_type` в SELECT. **Δ DDL не нужен.**
- **Существующий рендер маркера:** `services/tool_router.py:1036-1061` (`_history_lines`) уже рисует `[медиа: {media_type}]` для строк с пустым текстом (`get_recent_history`). Marker-диалект задаётся **этой точкой** — F13 расширяет его внутренним рефом, F14 приводит `tool_router` к общему хелперу.
- **Единый рендер строки:** `format_context_item` (`services/canonical_context.py:252-295`), `format_chain_line` (`services/thread_chain.py:161-177`), `render_reply_chains` (`:180-193`). Канон `[Дата Время | Автор | ID | Переслано]: текст` — R16.
- **Байт-эталоны 10.23:** F1 маркировка (`ADR-1023-1`) и F2 окно/граф (`ADR-1023-2`) — обязательный регресс при отсутствии медиа.

## 3. Требуемое поведение

1. **Строка с пустым текстом и нативным медиа не отбрасывается** — вместо текста рендерится компактный медиа-маркер; строка остаётся канонической (заголовок `[ts | автор | ID]:`, `kind="msg"`).
2. **Медиа-маркер несёт тип + внутренний реф** медиа-узла, без публичного URL и без `file_id` (R17).
3. **`<Current_Question>` не пуст**, если текста нет, но есть нативное медиа на самом сообщении или на `reply_to_message`; при непустом тексте маркер **дописывается** и не теряется при срезе префикса/капе.
4. **Инвариант «нет медиа ⇒ байт-в-байт»:** при отсутствии медиа (все строки `media_type` пусто/`text` либо текст непуст) вывод `thread_chain`, `chat_context`, `<Current_Question>` **побайтово** равен прежнему. Усечение окна/цепочки и бюджеты **не меняются**.
5. **Медиа с непустым текстом (caption) не трогается** — рендер прежний (только пустой текст уходит в маркер). Сознательное сужение поверхности (см. §10).
6. **Fail-open:** любая ошибка резолва медиа/рендера — прежнее поведение, без исключений наружу.

## 4. Контракт медиа-маркера

**Владелец контракта — F13.** Новый тонкий модуль `services/media_marker.py` (единственный источник маркера; F14 импортирует его).

### 4.1. Формат (single dialect)

```
[медиа: {media_type}]              # реф неизвестен (R16 — опускаем)
[медиа: {media_type} tg:{id}]      # внутренний реф: Telegram id медиа-узла
[медиа: {media_type} msg:{id}]     # внутренний реф: внутренний id строки (нет tg)
```

- `{media_type}` — словарь БД: `video|photo|voice|audio|animation|sticker|document|other`.
- `{id}` — **внутренний** идентификатор; публичный URL / `file_id` / токены **не** попадают (R17).
- В канонических строках (цепочка/окно) реф дублирует `ID` заголовка (`tg:<id>`), но маркер **самодостаточен** — F14 парсит одним regex без корреляции с заголовком.
- Неизвестное/битое `media_type` санитизируется до `[a-z_]` (≤20); пусто → `other`. Переносы/`]`/`[` не проходят — инъекция в канон невозможна.

Regex для F14: `^\[медиа: (?P<media>[a-z_]{1,20})(?: (?P<ref>(?:tg|msg):\d+))?\]$`.

### 4.2. API `services/media_marker.py`

```python
def is_media_type(media_type) -> bool        # non-empty и != "text"
def media_marker(media_type, item_id=None) -> str
def row_media_marker(row, item_id=None) -> str   # читает media_type через row_get
def message_media_type(message) -> str | None    # aiogram-like объект → token (или None)
def media_context_enabled() -> bool              # читает settings.flag (единая точка для тестов)
```

`message_media_type`: `video`/`video_note` → `"video"`, `photo` → `"photo"`, `voice` → `"voice"`, `audio` → `"audio"`, `animation` → `"animation"`, `sticker` → `"sticker"`, `document` → `"document"`; иначе `None` (текст/отсутствие). Словарь совпадает с `_detect_media_type` (`handlers/summary.py`) — **единый словарь токенов** БД и live-сообщения.

### 4.3. Точка связи с инструментами (передаётся F14)

- **Внутренний реф = `tg:<tg_message_id>`** медиа-узла (или `msg:<internal_id>`, если tg-id нет). В канонической строке он же стоит в заголовке; в `<Current_Question>` — внутри маркера.
- F13 **только отдаёт реф в контекст**; схемы инструментов (`summarize_video`/`download_media`, обязательный `url`) — **зона F14** (AMEND ADR-1020-4 / ADR-1016-1 / ADR-1017-2).
- F14 обязан валидировать реальное вложение live-сообщения: `video_note` и не-видео `document` под маркером `video`/`document` **не** должны скачиваться (см. риск R5).

## 5. Изменения по файлам

| Файл | Изменение | Владелец |
|---|---|---|
| `services/media_marker.py` (**новый**) | Marker-контракт §4 | **F13** |
| `services/thread_chain.py` (`:131-146`) | Если `text` пуст и `media_context_enabled()` → `text = row_media_marker(row, item_id=...)`; `if text:` прежний. `item_id` вычисляется через `resolve_item_id` **до** решения о скипе | **F13** |
| `services/chat_context.py` (`:107-110`) | Аналогично: `text = (...).strip()`; если пусто и флаг ON → маркер; `if not text: continue`. Вычисление `item_id` переносится выше скипа | **F13** |
| `services/direct_chat_service.py` (`_render_current_question`, `:1220-1233`) | Текст + маркеры нативного медиа самого сообщения и `reply_to_message`; сохранены `_strip_direct_prefix`, `limits.chat_current_question_max_chars`, `escape_xml_text` | **F13** |
| `config/settings.py` | env-only `ClassVar` флаг §6 | **F13** |

**Не трогаем:** `services/tool_schemas.py`, `services/tool_router.py`, `handlers/**`, `services/database.py` (DDL/чтения не меняются), `services/canonical_context.py` (существующие сигнатуры/`CONTEXT_POINTS` без изменений), `services/target_marking.py`.

### 5.1. Псевдо-алгоритм (сохраняет срез/кап)

`thread_chain` / `chat_context` (после каждой правки — прежняя ветка при отсутствии медиа):
```
item_id = resolve_item_id(tg_message_id=..., message_id=...)
text = <как раньше: raw для thread_chain / strip для chat_context>
if not text and media_context_enabled():
    text = row_media_marker(row, item_id=item_id)
if <прежняя проверка text>:
    <прежний рендер строки/ChainItem с подставленным text>
```

`<Current_Question>`:
```
stripped = _strip_direct_prefix(message.text or "")
markers = []
if media_context_enabled():
    own = message_media_type(message)
    if own: markers.append(media_marker(own, f"tg:{message.message_id}"))
    reply = message.reply_to_message
    rmt = message_media_type(reply)
    if rmt: markers.append(media_marker(rmt, f"tg:{reply.message_id}"))
if not stripped and not markers: return ""            # байт-в-байт legacy
if markers:
    suffix = " ".join(markers)
    room = max(0, cap - len(suffix) - 1)
    body = (stripped[:room] + (" " + suffix if stripped else suffix)) if room else suffix
else:
    body = stripped[:cap]                             # байт-в-байт legacy
return f"<Current_Question>\n{escape_xml_text(body)}\n</Current_Question>"
```
> При `markers` текст сначала усекается до `room`, затем дописывается суффикс — маркер **гарантированно** выживает при капе (R4). При отсутствии медиа — ровно `stripped[:cap]`.

## 6. Feature Flag

- `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED` — env-only `ClassVar` (`config/settings.py`, `_env_bool(..., True)`) — **kill-switch, default ON**.
- `OFF` → медиа-строки снова скипаются (прежнее поведение, побайтово), маркеры не рендерятся.
- **Δ каталога = 0** (флаг вне `param_catalog`), **Δ DDL = 0**. Поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21–10.23).

## 7. Тесты (T-2296)

- **(a) Маркер в цепочке/окне.** Реплай-цепочка / окно с узлом (`text=""`, `media_type="video"`, `tg=123`) → строка содержит `[медиа: video tg:123]`; `<reply_chains>`/`<chat_context>`/`<Conversation_Thread>` рендерятся канонически.
- **(b) Байт-эталон (обязателен, R1).** Text-only фикстуры → вывод `thread_chain`/`chat_context`/`Current_Question` **точно** равен снимку до-фичи; при `FLAG=False` медиа-фикстура → тоже прежний вывод (медиа-узел отброшен).
- **(c) `<Current_Question>` при видео-реплае без текста.** Пустой `message.text` + `reply_to_message.video` → блок **не пуст**, содержит `[медиа: video tg:<reply_id>]`; непустой текст + видео-реплай → текст сохранён и маркер присутствует; непустой текст без медиа → байт-в-байт.
- **(d) User-content для tool-loop.** Собранный direct-контекст (цепочка + `<Current_Question>`) содержит медиа-маркер и внутренний реф (`tg:<id>`) — контракт для F14.
- **(e) Границы/безопасность.** `media_type` `""`/`"text"` → маркера нет; caption-медиа (непустой текст) → рендер прежний; битый `media_type` санитизируется; канонические pattern-тесты `CONTEXT_POINTS` зелёные; `pytest` — 0 failed; `git diff --check` чист.

## 8. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Правка рендера цепи/окна ломает байт-эталоны 10.23 F1/F2 | Эталонный тест (b) + флаг OFF = прежний путь; маркер появляется только при медиа |
| R2 | Medium | Маркер раздувает бюджет контекста | Компактный формат, участвует в существующем усечении keep-end; капы/алгоритм не меняются |
| R3 | Medium | Утечка `file_id`/URL/служебных данных в контекст/логи | Только тип + внутренний `tg:`/`msg:` реф; R17-логи без контента |
| R4 | Low | Пустой `<Current_Question>` при медиа без текста | Резерв места под маркер в капе; тест (c) |
| R5 | Low | `media_type="video"` не отличает `video` от `video_note`, а `document` — от видео-документа | Явно в контракте F14: валидация реального вложения live-сообщения; не-видео отклоняется понятным результатом |
| R6 | Low | Недоверенный `media_type` из импорта → инъекция в канон | Санитизация `[a-z_]`≤20, fallback `other` (тест e) |

## 9. Критерии приёмки

- Реплай-нативное видео присутствует в контексте direct_chat как медиа-маркер с внутренним рефом (без публичного URL).
- При отсутствии медиа `thread_chain`/`chat_context`/`Current_Question` дают **идентичный** прежнему вывод; флаг OFF — прежнее поведение на любой фикстуре.
- `<Current_Question>` не пуст при видео-реплае без текста; маркер доступен LLM/tool-loop.
- Полный pytest — 0 failed; `git diff --check` чист; канон `CONTEXT_POINTS` не изменён.

## 10. Откат / Δ / инварианты

- **Откат:** `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED=false` / `git revert`. **Δ DDL = 0**, **Δ каталога = 0**, канон-миграций/изменений `media/`/`.env` нет.
- **Инварианты (не нарушаются):** `imported-history-immutable` (только чтение), `physical-two-call` (LLM-вызовов не добавляется), egress-реестры (`SEND_POINTS`/`SEND_ALLOWLIST`) не тронуты, `parse_mode=None` plain-каналы не тронуты, R16 (опускание отсутствующего), R17/R18 (без секретов/URL/`file_id`).
- **Вне объёма F13:** маркировка caption-медиа (сознательно отложено), изменение схем/диспатча инструментов (F14), правка `tool_router._history_lines` под общий хелпер (F14/техдолг).

## 11. Артефакты-ссылки

- ADR: `ADR-1024-14.md`.
- Задачи: `tasks.md` (T-2291…T-2298).
- Прецеденты байт-инварианта: `plans/archive/target-message-marking-round1023/ADR-1023-1.md`, `plans/archive/factcheck-deep-context-round1023/ADR-1023-2.md`.
- Смежная фича: `plans/features/native-media-tools-round1024/tasks.md` (F14, потребитель контракта).
- Карта раунда: `plans/features/round1024-architecture.md`; карта якорей — `plans/reports/global_map.md`.
