# A0 — Agentic Audit (Эпик 3 «Agentic Intelligence», Wave 0, Раунд 10.26)

> **Durable-артефакт** (ADR-1026-13 **D1** / `spec.md` §4(a), §5). Единый источник для A1–A10; **не архивируется** вместе с feature-папкой. Обновление после Verified — только AMEND-записью.
>
> | Поле | Значение |
> |---|---|
> | **Baseline** | HEAD **`e8065e9`** == `origin/master` |
> | **APP_VERSION** | **2.58.29** |
> | **Дата** | 24.09.2026 |
> | **Владелец** | @Builder (блоки B–D) → @Architect (T-3496 ✅ реконсиляция) → @Reviewer (T-3498 ✅ Approved) |
> | **Статус** | **✅ APPROVED — единый Reviewer gate (T-3498, C0/H0, обе линзы)** после реконсиляции @Architect (T-3496) и handoff @PM (T-3497); read-only, **deploy NOT_APPLICABLE**. **T-3499 @PM** — архивация feature-папки (этот durable-артефакт **не архивируется**) — следом. Обновление после Verified — только AMEND-записью. |
> | **Тип** | research/audit, **read-only** (0 изменений product code/рантайма/DDL/каталога) |
> | **Источники** | `plans/features/agentic-audit-round1026/spec.md` (REQ-A0-01…-19, SC-01…-23); `adr-1026-13-…md` (D1–D3, **Accepted**); `tasks.md` (T-3484…T-3499); ТЗ `plans/current_task.md` §11 (`:4324+`), §12 (`:4373–4438`), §54 п.1 (`:5877`) |
> | **Инвариант** | Каждый вывод помечен **EVIDENCE** (подтверждено `file:line` baseline `e8065e9` \| логом с кодом/статусом \| воспроизводимой пробой) либо **HYPOTHESIS** (+ план проверки, волна A3/A4). Живой прогон провайдера в A0 **не выполнялся** (ADR-1026-13 D2). |
>
> **Как ссылаться (A1–A10):** `plans/docs/agentic-audit-round1026.md#<anchor>`. Анкоры — **явные** (`<a id="…">`), не зависят от перестановки разделов; полный реестр — [§10.1](#anchors).

**Оглавление:** [1. Карта инструментов](#tool-map) · [2. §12 пп.1–2 инвентарь/схемы](#s12-1-2) · [3. §12 пп.3–5 tool-loop/результаты/лимиты](#s12-3-5) · [4. §12 пп.6–7 image](#s12-6-7) · [5. §12 пп.8–15 память/фактчек/решения](#s12-8-15) · [6. Первопричина image-tool-calling](#root-cause) · [7. Дубликаты/канон 10](#duplicates) · [8. Вход A1–A10](#epic3-handoff) · [9. Инварианты](#invariants) · [10. Трассировочная матрица](#traceability) · [10.1 Реестр анкоров](#anchors) · [Приложение A: реестр EVIDENCE/HYPOTHESIS](#labels)

---

<a id="tool-map"></a>
## 1. Карта инструментов (8/8 полей × 10 + не-LLM прямые пути)

**Канон `TOOL_CALLING_TOOLS` = 10** (`services/tool_schemas.py:337–348`, ADR-1020-4 → ADR-1023-5 → ADR-1024-20). Порядок неизменен («новое — в хвост»); первые 9 имён — байт-в-байт. Доступность (LLM-объявление) фильтруется `active_tools()` (`services/tool_schemas.py:367–389`) по трём гейтам: `flags.lore_compiler_enabled` (default ON), `flags.image_generation_module_enabled` + env `IMAGE_GENERATION_ENABLED` (default OFF у `active_tools`, реальное значение резолвит вызывающий), env `MEDIA_TRANSCRIBE_TOOL_ENABLED` (default ON).

> **Метка:** EV-01, EV-02, EV-03 (см. [Приложение A](#labels)).

<a id="tool-map-llm"></a>
### 1.1. LLM-инструменты (канон 10)

| # | Название | Назначение | Аргументы (JSON Schema) | Результат | Ошибки | Доступность | Зависимости | Возможность последовательного вызова |
|---|---|---|---|---|---|---|---|---|
| 1 | `query_chat_memory` | Поиск по памяти чата: история, кто/когда, долгосрочные факты, статистика упоминаний | `query: string` (**required**); `time_range: enum[last_day,last_week,last_month,all]`, `default=all`; `additionalProperties=false` (`tool_schemas.py:71–98`) | Текст: счётчик упоминаний + дата-диапазон + FTS-строки + (при пустоте) вектор/RAG; усечение `_MEMORY_MAX_SYMBOLS=3500` (`tool_router.py:506–569`) | Не бросает: пусто → «ничего не найдено»; сбой этапа → WARNING (count fail-open); `dispatch` → «ОШИБКА …» | `active_tools` (всегда, если не отфильтрован) | `MemoryManager.search_long_term`/`count_mentions`/`vector_search`/`get_rag_context`; FTS5/vec0 | Да — независим; логически «память → лор → веб» |
| 2 | `dig_into_lore` | Быстрые точные факты: «кто владеет X», «когда было Y»; FTS-сниппеты L1 + факты графа | `query: string` (**required**); `year: integer` (optional); `person: string` (optional); `mode: enum[messages,facts,both]`, `default=both`; `additionalProperties=false` (`tool_schemas.py:100–132`) | JSON: `total_mentions`, `mentions_by_authors`, `first_seen`, `last_seen`, `snippets[]`, `facts[]`; валидный JSON с `truncated:true` при усечении (`tool_router.py:573–769`) | Не бросает: `flags.dig_enabled=false` → строка отключения; этап fail → WARNING + пустая секция; пусто → `status:not_found` | `active_tools` + `flags.dig_enabled` (default true) | `MemoryManager.search_long_term`/`db.search_graph_facts_fts`/`dig_graph_related_names`; alias-резолвер | Да — парный к `compile_lore_story` (лёгкий/тяжёлый нарратив) |
| 3 | `execute_web_search` | Веб-поиск (каскад Tavily→Exa→DuckDuckGo) для свежих/внешних фактов | `query: string` (**required**); `additionalProperties=false` (`tool_schemas.py:51–69`) | Текст: заголовок + результаты; усечение `_SEARCH_MAX_SYMBOLS=4000` (`tool_router.py:484–502`) | Не бросает: timeout/`AllSearchEnginesFailed`/empty → «ОШИБКА … поиск недоступен» | `active_tools` | `SearchAggregator.search`; таймаут `_SEARCH_TOOL_TIMEOUT=25.0` | Да — независим; источник для фактчека и RAG-комбинации |
| 4 | `summarize_video` | Связная **выжимка** видео (не транскрипт) | `url: string` (optional); `source: enum[link,reply]` (optional); `required=[]`; `additionalProperties=false` (`tool_schemas.py:134–163`) | Текст выжимки; усечение `_MEMORY_MAX_SYMBOLS=3500` (`tool_router.py:773–812`) | Не бросает: нет источника/сервиса/timeout/пусто → «ОШИБКА summarize_video: …» | `active_tools`; нативный резолв — env `NATIVE_MEDIA_TOOLS_ENABLED` | `YoutubeSummarizerService`, `VideoDownloader`, `native_media`, `VoiceTranscriber`; `ToolDeps.video/downloader/transcriber` | Да — независим; может идти после web/памяти |
| 5 | `download_media` | Скачать видео по ссылке и отправить файлом в чат | `url: string` (optional); `source: enum[link,reply]` (optional); `quality: enum(QUALITY_ENUM)` (optional); `required=[]`; `additionalProperties=false` (`tool_schemas.py:201–237`) | Фиктивный JSON `{status,message}` (`success`/`needs_quality`/`error`) — файл шлёт бэкенд (`tool_router.py:1042–1202`) | Не бросает: кривая ссылка/выключен/кулдаун/probe fail/размер → `status:error` | `active_tools` + `flags.download_enabled` + общий download-кулдаун | `VideoDownloader`, `media_send`, pending-меню `tdq:` (in-memory, TTL 600 c) | Да — независим; меню качества доводится callback-ом (не LLM-шагом) |
| 6 | `get_bot_health` | Статус/здоровье бота (логи, память, сервисы) | `{}` — нет параметров; `additionalProperties=false` (`tool_schemas.py:239–249`) | Текст отчёта; усечение `_MEMORY_MAX_SYMBOLS=3500` (`tool_router.py:1230–1254`) | Не бросает: модуль OFF → «ОШИБКА … модуль выключен»; сервис недоступен/пусто → «ОШИБКА …» | `active_tools` + `flags.checkup_enabled` | `ToolHealthDeps` (CheckupLogsFetcher+CheckupService), инжект из `bot.py` | Да — независим |
| 7 | `get_recent_history` | Кратковременная память: сырая хронология недавних сообщений чата (не RAG) | `depth: integer [1..150]` (optional); `query: string` (optional); `additionalProperties=false` (`tool_schemas.py:254–278`) | Текст-стенограмма «Имя: текст»; усечение `_HISTORY_MAX_SYMBOLS=3500` (`tool_router.py:1256–1306`) | Не бросает: timeout/сбой → «ОШИБКА …»; пусто → честная фраза | `active_tools` | `database.get_recent_messages`, `MemoryManager.search_long_term`; fallback `ctx.query` | Да — независим |
| 8 | `compile_lore_story` | Тяжёлый нарратив: объяснить мем, рассказать историю, обзор темы | `topic: string` (**required**); `additionalProperties=false` (`tool_schemas.py:285–304`) | JSON `{status,is_update,previous_story_at,story}` (+ инструкция «верни дословно»); ставит `ctx.lore_compiled=True` (`tool_router.py:1381–1435`) | Не бросает: флаг OFF → строка отключения; timeout/сбой/пусто → «ОШИБКА …» | `active_tools` + `flags.lore_compiler_enabled` (per-chat; default ON) | `LoreCompilerService`, `deps.llm`, `deps.db`; второй LLM-вызов внутри инструмента | Да — парный к `dig_into_lore` |
| 9 | `generate_image` | Генерация изображения по текстовому описанию и отправка в чат | `prompt: string` (**required**); `additionalProperties=false` (`tool_schemas.py:315–334`) | JSON `{status,message}` или `{status,reason,message}`; изображение шлёт бэкенд (`tool_router.py:1437–1468`) | Не бросает: модуль OFF/нет prompt → `status:error`; провал провайдера/бюджета → `status:error` + `reason` | `active_tools` + `flags.image_generation_module_enabled` + env `IMAGE_GENERATION_ENABLED`; **на ходу сработавшего пре-гейта — принудительно OFF** (`direct_chat_service.py:748–749`) | `image_generation.generate_and_send`; `worker_budget` (`image_calls`); `IMAGE_API_KEY` | Да — но в A0 выявлен конфликт с прямым пре-гейтом (см. §4, §6) |
| 10 | `transcribe_video` | Сырая дословная транскрибация медиа (не пересказ) | `url: string` (optional); `source: enum[link,reply]` (optional); `required=[]`; `additionalProperties=false` (`tool_schemas.py:169–199`) | Сырой текст; усечение `_MEMORY_MAX_SYMBOLS=3500` (`tool_router.py:893–934`) | Не бросает: нет источника/timeout/пусто → «ОШИБКА transcribe_video: …» | `active_tools` + env `MEDIA_TRANSCRIBE_TOOL_ENABLED` (default ON) | `YoutubeSummarizerService`, `VideoDownloader`, `VoiceTranscriber`, `native_media` (`MEDIA_KINDS`) | Да — независим |

<a id="tool-map-direct"></a>
### 1.2. Не-LLM прямые пути (вне `TOOL_CALLING_TOOLS`)

| Путь | Назначение | Точка входа (`file:line`) | Обходит tool-loop? | Метка |
|---|---|---|---|---|
| Image пре-гейт по ключевой фразе | «Бот, нарисуй …» → генерация+отправка **до** Stage-1 | `direct_chat_service.py:688–693` → `image_generation.maybe_handle_keyword` (`image_generation.py:968`) | Да — детерминированно, вне LLM | EV-11…EV-15 |
| Dig пре-гейт ностальгии | Маркеры ностальгии → `dig_into_lore` до генерации | `direct_chat_service.py:1288–1327` | Да (вызывает роутер напрямую) | EV-33 |
| RAG-блок `<RAG_Memory>` | Инъект релевантных фактов в user-content | `direct_chat_service.py:2259–2357` | Да — программно | EV-22 |
| Досье/карточка (`/persona`) | Агрегация фактов/мемов/портрета в карточку | `direct_chat_service.py:2068–2146`; `dossier_prompts.format_dossier_block:568` | Да — команда, **не** инструмент | EV-20 |
| Фактчек | SearchAggregator → System 2 вердикт | `factcheck_service.py:77` | Свой tool-set (`factcheck_tools`), не общий канон | EV-24 |
| Реакция 🗿 | Реакция на пустой ответ/триггер | `smartmodule_utils.react_moai:93` | Да — best-effort | EV-28 |

> **Примечание о «прямых путях».** Они не входят в канон 10 и **не являются дубликатами** инструментов: image-пре-гейт и `generate_image` — два разных входа в **один и тот же** сервис (`image_generation.generate_and_send`), а не два инструмента; конфликт между ними разобран в §4 и §6.

**Анкоры:** `#tool-map`, `#tool-map-llm`, `#tool-map-direct`.

---

<a id="s12-1-2"></a>
## 2. §12 пп.1–2 — инвентарь и JSON Schema/аргументы

**REQ-A0-01/-02 · SC-01/-02 · T-3484.**

<a id="s12-1"></a>
### 2.1. Инвентарь (§12 п.1) — EVIDENCE

- **Всего инструментов в каноне: 10.** `TOOL_CALLING_TOOLS` (`services/tool_schemas.py:337–348`) в порядке канона R9: `query_chat_memory`, `dig_into_lore`, `execute_web_search`, `summarize_video`, `download_media`, `get_bot_health`, `get_recent_history`, `compile_lore_story`, `generate_image`, `transcribe_video`. **EV-01.**
- **Расхождения с каноном «10» нет** — список фактически содержит 10 записей; комментарий-счётчик синхронизирован (`tool_schemas.py:336`). Зафиксировано как evidence (не «исправлялось»).
- **Диспетчер** `ToolRouter.dispatch` (`services/tool_router.py:455–480`) — реестр ровно из 10 имён (`:457–468`); неизвестное имя → `ОШИБКА: неизвестный инструмент`. **EV-05.**
- **Отдельный tool-set фактчека** `factcheck_tools()` (`tool_schemas.py:398–415`): ровно 3 инструмента (`dig_into_lore`, `compile_lore_story`, `execute_web_search`); гейт «Летописца» действует и здесь. **EV-04.**
- **Не-LLM прямые пути** — см. §1.2 (image/dig пре-гейты, RAG-инъект, досье, фактчек, реакции).

<a id="s12-2"></a>
### 2.2. JSON Schema и аргументы (§12 п.2) — EVIDENCE

Каждая схема — формат OpenAI function calling: `{type:"function", function:{name, description, parameters}}`; **у всех** `additionalProperties:false` (строгая типизация, ADR-1020-7 §4). Полные определения — в §1.1 (колонка «Аргументы»); здесь сводка типов/`required`/`enum`:

| Инструмент | `required` | optional / enum | `file:line` |
|---|---|---|---|
| `execute_web_search` | `query` (string) | — | `tool_schemas.py:51–69` |
| `query_chat_memory` | `query` (string) | `time_range` enum `[last_day,last_week,last_month,all]` default `all` | `tool_schemas.py:71–98` |
| `dig_into_lore` | `query` (string) | `year` int; `person` str; `mode` enum `[messages,facts,both]` default `both` | `tool_schemas.py:100–132` |
| `summarize_video` | — | `url` str; `source` enum `[link,reply]` | `tool_schemas.py:134–163` |
| `transcribe_video` | — | `url` str; `source` enum `[link,reply]` | `tool_schemas.py:169–199` |
| `download_media` | — | `url` str; `source` enum `[link,reply]`; `quality` enum = `QUALITY_ENUM` | `tool_schemas.py:201–237` |
| `get_bot_health` | — | `properties:{}` (нет аргументов) | `tool_schemas.py:239–249` |
| `get_recent_history` | — | `depth` int `[1..150]`; `query` str | `tool_schemas.py:254–278` |
| `compile_lore_story` | `topic` (string) | — | `tool_schemas.py:285–304` |
| `generate_image` | `prompt` (string) | — | `tool_schemas.py:315–334` |

**Валидация аргументов в рантайме:** `dispatch` ловит кривой JSON/тип и возвращает текст ошибки (не бросает); `json.loads(tc.arguments)` + проверка «object» — в `tool_loop.py:175–178`. **EV-02, EV-31.**

**Анкоры:** `#s12-1-2`.

---

<a id="s12-3-5"></a>
## 3. §12 пп.3–5 — механизм tool calling, обработка результатов, лимиты

**REQ-A0-03/-04/-05 · SC-03/-04/-05 · T-3485, T-3486.**

<a id="s12-3"></a>
### 3.1. Механизм tool calling (§12 п.3) — EVIDENCE

- Точка входа цикла — `services/tool_loop.py::chat_with_tools` (`:89`). Вызывается из `DirectChatService` (`direct_chat_service.py:766–773`) и из фактчека (`factcheck_service.py:223`).
- Цикл (OpenAI-совместимый формат ролей):
  1. `llm.generate_chat(payload_messages, tools=tools, tool_choice="auto", …)` (`tool_loop.py:114–122`); `tool_choice` **не форсируется** — всегда `"auto"` (канон R9/backlog §16 п.2; `llm_client.py:1155–1157` добавляет `tools`/`tool_choice` в payload только при непустом `tools`). **EV-06, EV-31.**
  2. Ответ: `result.content` (может быть `None`) + `result.tool_calls` (`LLMToolCall`). Парсинг `tool_calls` — `llm_client.py:1200+`.
  3. Если `tool_calls` нет — финальный текст возвращается (`tool_loop.py:145–156`); пустой финал → `LLMBadResponseError` (контракт 🗿, FR-14/65.1).
  4. Если есть — в `payload_messages` добавляется `assistant` с `tool_calls` (`:167–171`), затем по каждому вызову добавляется `{"role":"tool","tool_call_id":…,"content":output}` (`:184–185`) и цикл повторяет LLM-вызов.

<a id="s12-4"></a>
### 3.2. Обработка результатов (§12 п.4) — EVIDENCE

- **Исполнение:** `router.dispatch(tc.name, arguments, ctx)` (`tool_loop.py:178`). `dispatch` **всегда возвращает строку** (в т.ч. «ОШИБКА …»), не бросает (`tool_router.py:455–480`). **EV-05.**
- **Ошибка инструмента:** исключение → `output = f"ОШИБКА {tc.name}: {type(exc).__name__}"`, `ok=False`; модель **видит** текст ошибки как `role:"tool"` (`tool_loop.py:179–185`). R17: логируется только класс исключения (`:181–182`, `tool_router.py:475–480`).
- **Второй шаг после tool response — ЕСТЬ:** после добавления `role:"tool"` цикл возвращается к LLM-вызову на следующей итерации `for round_index` (`tool_loop.py:112,172–190`). **EV-08.** (Это опровергает место №7 из §12 как причину — см. §6.)
- **Ограничение спама:** `tool_calls` усекаются до `_TOOL_CALLS_PER_ROUND_MAX` (`:158–162`).
- **Деградация:** исчерпание раундов / поздний `LLMError` → частичный текст или `TOOL_LOOP_FALLBACK_PHRASE`, `degraded=True` (`:191–196`, ADR-1020-7 §1); `NoApiKeyForChat` — проброс (`:123–124`). **EV-10.**
- **Телеметрия:** `ToolLoopResult` несёт `rounds_used`, `degraded`, `reason` (`ok`/`round_limit`/`llm_error`), `tool_trace`, `tool_context` (`tool_loop.py:48–73`); `tool_context` в логи **не пишется** (R17).

<a id="s12-5"></a>
### 3.3. Ограничения числа вызовов (§12 п.5) — EVIDENCE

| Лимит | Значение | Смысл | `file:line` |
|---|---|---|---|
| `TOOL_MAX_ROUNDS` | **4** | 1 стартовый вызов + до 3 tool-раундов (≤4 LLM-вызова суммарно) | `tool_loop.py:38`, цикл `:112` |
| `_TOOL_CALLS_PER_ROUND_MAX` | **2** | максимум вызовов одним ходом; лишние усекаются | `tool_loop.py:39`, `:158–162` |

**Поведение при превышении:** раунды — graceful degradation (частичный текст/заглушка, `reason="round_limit"`, `degraded=True`); вызовы в раунде — тихое усечение с WARNING `[tools] tool_calls truncated`. **EV-06, EV-09, EV-10.** Связанные лимиты цепочек — предмет §17 ТЗ (ориентир A1–A2; в A0 не реализуются).

**Анкоры:** `#s12-3-5`.

---

<a id="s12-6-7"></a>
## 4. §12 пп.6–7 — image: прямой контур vs tool-контур

**REQ-A0-06/-07 · SC-06/-07 · T-3488, T-3489.**

<a id="s12-6"></a>
### 4.1. Прямой контур по ключевой фразе (§12 п.6) — EVIDENCE

- **Детектор:** `IMAGE_KEYWORD_RE` (`image_generation.py:93–101`) — сообщение **начинается** с `бот|bot`, далее `нарисуй` / `сгенерируй` / `создай (изображение|картинку|мем|арт)`. `is_image_keyword()` — `:158–160`. **EV-11.**
- **Извлечение промпта:** `extract_prompt()` (`:163–167`) снимает служебную обёртку «Бот, нарисуй …»; пусто → исходный текст. **EV-12.**
- **Врезка в DirectChat:** `_image_pre_gate_block` (`direct_chat_service.py:1345–1374`) вызывается **до** Stage-1 (`:688–693`); условия: есть ключевик И `resolve_module_enabled(chat_id)`. Роутер для пре-гейта **не нужен** (`:1359–1360`). **EV-14.**
- **Генерация+отправка:** `maybe_handle_keyword` (`image_generation.py:968–994`) → `generate_and_send` (`:936–965`); при успехе в user-content инъектится `<image_result status="ok">` с требованием **не вызывать** `generate_image` повторно. **EV-13.**
- **`tool_choice` не форсируется** (`image_generation.py:91,973`; канон R9).
- **Ключевой побочный эффект:** если пре-гейт сработал, `image_pre_gate_fired=True` и на этом ходу `image_enabled` принудительно `False` (`direct_chat_service.py:748–749`) → `generate_image` **исключается** из `active_tools` (`tool_schemas.py:382–383`). Один путь генерации, без двойного платного вызова. **EV-15.**

<a id="s12-7"></a>
### 4.2. LLM-tool-контур (§12 п.7) — EVIDENCE

- **Схема:** `TOOL_GENERATE_IMAGE` (`tool_schemas.py:315–334`) — 9-й инструмент канона; `prompt: string` required.
- **Маршрут:** `tool_router._generate_image` (`tool_router.py:1437–1468`) → гейт `resolve_module_enabled` → `_require_str(arguments,"prompt")` → `image_generation.generate_and_send` (`:1454–1457`). Возврат — короткий JSON-статус (изображение шлёт бэкенд). **EV-16, EV-17.**
- **Доступность:** `active_tools(bool(lore_enabled), bool(image_enabled))` (`direct_chat_service.py:768–769`); `image_enabled` = `resolve_module_enabled(chat_id)` (`:742–743`).

### 4.3. Сравнение прямого и tool-путей

| Аспект | Прямой (пре-гейт) | LLM-tool | Вывод |
|---|---|---|---|
| Триггер | Регэксп по началу сообщения | Решение модели по description | Разные входы |
| Промпт | `extract_prompt(query)` — снимает обёртку | `arguments["prompt"]` — как передала модель | Прямой путь «чище»; tool зависит от модели |
| Генерация/отправка | `generate_and_send` | `generate_and_send` | **Общий сервис** (не дубликат) |
| Гейт модуля | `resolve_module_enabled` | `resolve_module_enabled` | Общий |
| Бюджет | `worker_budget` `image_calls` (global+per-chat) | То же | Общий |
| Взаимоисключение | Сработал → tool OFF на ход (`:748–749`) | Не объявляется, если пре-гейт сработал | **Конфликт по дизайну** (не баг) |

**Пересечения:** общий сервис `generate_and_send` и общий бюджет. **Различия:** триггер (регэксп vs модель), обработка промпта, и главное — при совпадении с регэкспом tool-путь **детерминированно отключён**. **EV-13…EV-17.**

**Анкоры:** `#s12-6-7`.

---

<a id="s12-8-15"></a>
## 5. §12 пп.8–15 — память/досье/RAG/фактчек/URL/Decision Making/JSON L1↔L2/реакции/тумблеры

**REQ-A0-08…-15 · SC-08…-15 · T-3491…T-3494.**

<a id="s12-8"></a>
### 5.1. Извлечение досье (§12 п.8) — EVIDENCE

- **Рендер досье:** `dossier_prompts.format_dossier_block` (`services/dossier_prompts.py:568–603`) — два блока `[Факты]` и `[Локальные мемы/Ярлыки]`; общий бюджет `cap_chars`, при переполнении первыми урезаются мемы, затем факты. **EV-20.**
- **Сборка карточки:** `DirectChatService.build_persona_card` (`direct_chat_service.py:2068–2146`) агрегирует прямые факты (`db.get_persona_card`), связи (`links`), защищённые факты (`get_protected_facts`), мемы (`list_chat_memes`, при `flags.irony_filter_enabled`) и сгенерированный портрет Слоя Б (`get_generated_dossier`); `format_dossier_block` вызывается на `:2135`. **EV-20.**
- **Точка вызова:** карточка строится по команде `/persona` (`handlers/direct_chat.py:274`), а **не** авто-инъекцией в диалог и **не** отдельным инструментом. Это соответствует проблеме §11 «досье не вызывается по необходимости».
- **Отсутствие `get_user_context`:** сквозной grep по `services/**`, `handlers/**` (исключая `var/**`) даёт **0 совпадений**. Целевой API — §33 (ориентир A6). **EV-21.**

<a id="s12-9"></a>
### 5.2. RAG и векторная память (§12 п.9) — EVIDENCE

- **Direct-путь (в диалоге):** `_build_rag_block` (`direct_chat_service.py:2259–2357`) — `memory.get_rag_facts` (порядок релевантности KNN/MMR) → дедуп против `<Global_Context>` (`dedup_rag_vs_global`) → опц. LLM-реранк (`flags.chat_rag_rerank_enabled`) → граф-активация → рендер `<RAG_Memory>` с origin-метками; cap `limits.graph_rag_context_max_chars`. Вызов — из `_build_user_content` (`:1091`). **EV-22.**
- **Легаси/сервисный RAG:** `MemoryManager.get_rag_context` (`summary_memory.py:2479–2520`) — гибридный KNN → FTS5-фолбэк, канон-XML, никогда не бросает. **EV-23.**
- **Векторный поиск:** `vector_search` (`:1855–1881`) — vec0 KNN (int8-квантизация + float-реранк) → FTS5-фолбэк; `search_long_term` (`:1826–1836`) — FTS5 по `smart_messages`. **EV-23.**
- **Хранилища:** FTS5 (`smart_messages`, `graph_facts_fts`, `smart_archive_fts`) + vec0 (`graph_facts_vec`, `smart_archive.embedding/embedding_i8`). **EV-23.**

<a id="s12-10"></a>
### 5.3. Фактчек (§12 п.10) — EVIDENCE

- **Точка входа:** `FactCheckService.check_claim` (`factcheck_service.py:77–131`): `SearchAggregator.search` → memorize-хук + `get_rag_context` → user-content → при `SYSTEM2_FACTCHECK_ENABLED` двухвызовный путь `_check_claim_two_call` (`:133–206`), иначе одиночный путь. **EV-24.**
- **Входы:** `target_text`, `user_hint`, `forward_source`, `chat_id`, `chat_context`. **Выходы:** вердикт-текст после `cleanup_llm_text` + grounding-strip + HTML-strip; пусто → `LLMBadResponseError`. **EV-24.**
- **Ошибки/деградация:** `AllSearchEnginesFailedException`/`LLMError` пробрасываются в хендлер (фразы выбирает хендлер); невалидный JSON Аналитика / провал Stage-2 / исчерпание validator-loop → fallback на одиночный путь 10.21 (пользователь всегда получает ответ). **EV-24.**
- **Tool-доступ:** `_invoke_llm` (`:208–241`) при `tool_router` + `chat_id` идёт через `chat_with_tools` с `factcheck_tools` (3 инструмента). **EV-04, EV-24.**

<a id="s12-11"></a>
### 5.4. Извлечение Markdown из URL (§12 п.11) — EVIDENCE

- `WebContentExtractor.extract` (`web_content_extractor.py:59–95`): каскад **trafilatura → Tavily `/extract` → Exa `/contents`**; успех уровня — `text.strip() > 150` символов; затем жёсткий срез `text[:max_symbols]`. **EV-25.**
- Пустой ключ уровня → уровень пропускается (WARNING); все уровни упали → `WebContentExtractionFailedException` → пул фраз 5.7 в `handlers/web.py`. Таймауты: 10 c (trafilatura) / 15 c (Tavily, Exa). **EV-25.**

<a id="s12-12"></a>
### 5.5. Decision Making Синтезатора (§12 п.12) — EVIDENCE

- **Контракт режима:** `RESPONSE_MODES = ("casual","serious","deep_research")` (`system2_handoff.py:41`); `normalize_response_mode` (`:68–81`) — валидный режим как есть, иначе `""` (сигнал сбоя; жёсткий режим НЕ подставляется — F6/ADR-1024-10 D3). **EV-26.**
- **Разбор справки Синтезатора:** `parse_direct_synthesis` (`:272–321`) валидирует JSON (`user_question`, `answer_outline`, `facts[]`, `limitations[]`), применяет `contains_system_ids`/`redact_secrets`, нормализует `response_mode`. **EV-26.**
- **Двухвызовный direct:** `_synthesize_direct_answer` (`direct_chat_service.py:899–988`) запускается **только** при `SYSTEM2_DIRECT_ENABLED`, успешном tool-финале, непустом `tool_trace` и НЕ `lore_compiled` (`:814–818`); Stage-1 (Синтезатор) → JSON → Stage-2 (Вербализатор) через `verbalize_validated`. Любой сбой/невалидный JSON → `None` → финал tool-loop. **EV-26, EV-32.**
- **Разведение action/style:** в коде baseline действует контракт **`response_mode`** (STYLE) и канал доставки; отдельного поля `action ∈ {reply,react,silent,tool}` **нет** — целевое разведение §39 (ADR-1023-3) — ориентир A8. **EV-26.**

<a id="s12-13"></a>
### 5.6. Схема JSON между L1 и L2 (§12 п.13) — EVIDENCE

- **L1-контракт:** `summary_l1_contract.py` — top-level ровно 5 ключей `{schema_version, threads[], unassigned_message_ids[], response_mode, cover_prompt}` (`:57–59`); тред ровно 4 (`:60–61`); факт ровно 2 (`:62`); лимиты (≤100 тредов, ≤30 фактов/тред, ≤1000 фактов, topic ≤200, fact ≤500), пространства ID **TG**; fail-closed `ok/empty/invalid/truncated/error` (`:64–93`); валидатор `validate_l1_response` (`:305`). **EV-27.**
- **Пакет фактов (вход L2):** `summary_fact_package.py` — top-level ровно `{schema_version, status, threads[], unassigned_message_ids[], service{response_mode, cover_prompt}, budget{kind,limit,estimated,fits}}` (`:65–66`); тема ровно 7 полей (`:67–68`); `description` — детерминированная агрегация (не LLM); fail-closed `ok/truncated/empty/invalid/error/not_built`. **EV-27.**
- **Служебные поля:** `service{response_mode, cover_prompt}` — метаданные оркестратора; `stage2_payload` (`system2_handoff.py:56–65`) исключает их из user-content Stage-2. **EV-27.**

<a id="s12-14"></a>
### 5.7. Механизм реакций Telegram (§12 п.14) — EVIDENCE

- `smartmodule_utils.react_moai` (`:93–107`): best-effort `bot.set_message_reaction(chat_id, message_id, reaction=[ReactionTypeEmoji("🗿")], is_big=False)`; **не бросает** (ошибка → WARNING, молчание сохраняется). **EV-28.**
- Вызовы: direct-chat при пустом ответе (`direct_chat_service.py:801,838`), хендлеры factcheck/search/web/youtube/checkup. Реакция дополняет молчание (send_message не вызывается). **EV-28.**
- **Ограничение:** baseline умеет только фиксированную 🗿-реакцию по программному триггеру; «когда молчать/отвечать/реагировать/silent» — целевой контур §41–§47 (A8–A9). **EV-28.**

<a id="s12-15"></a>
### 5.8. Генеральные переключатели и действующие лимиты (§12 п.15) — EVIDENCE

- **Каталог параметров:** `REGISTRY` (`services/param_catalog.py:1893`), `GROUPS` (`:147`), `TAB_RULES` (`:2124`), `_TAB_BY_GROUP` (`:2253`); baseline-числа: REGISTRY 469 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21 / categorized 444 / Settings 426. **EV-29.**
- **Тяжёлые фичи-гейты:** `feature_gates.ALL_GATED_FEATURES = {dream, nostalgia, lore_auto, permsoc, permsoc_reactions, permsoc_schedule}` (`:32–34`); `gates_enabled` (`:134–169`) — приоритет: явный chat-гейт → явный глобальный kill-switch → fallback → глобальный флаг → False. **EV-30.**
- **Бюджеты:** `worker_budget.METRIC_IMAGE_CALLS="image_calls"` (`:35`); ветка лимита `image_calls` — env-only `WORKER_DAILY_IMAGE_CALLS_GLOBAL` (default 200) / `_PER_CHAT` (default 60) (`:284–291`); семантика sentinel `0=запрет / <0=безлимит / >0=cap`. **EV-19.**
- **Ключевые env/каталожные рубильники** (сводка): `IMAGE_GENERATION_ENABLED` + `flags.image_generation_module_enabled`; `flags.lore_compiler_enabled`; `MEDIA_TRANSCRIBE_TOOL_ENABLED`; `NATIVE_MEDIA_TOOLS_ENABLED`; `flags.dig_enabled`; `flags.download_enabled`; `flags.checkup_enabled`; `flags.graph_rag_enabled`; `flags.chat_rag_rerank_enabled`; `SYSTEM2_DIRECT_ENABLED`; `SYSTEM2_FACTCHECK_ENABLED`; `flags.budgets_enabled`. **EV-19, EV-30.**

**Анкоры:** `#s12-8-15`, `#s12-8`, `#s12-9`, `#s12-10`, `#s12-11`, `#s12-12`, `#s12-13`, `#s12-14`, `#s12-15`.

---

<a id="root-cause"></a>
## 6. Первопричина отказа image-tool-calling (§12, REQ-A0-18)

**SC-18 · T-3490.** Метод: только read-only разбор кода baseline `e8065e9`. **Живой прогон провайдера не выполнялся** (ADR-1026-13 D2). Критерий достаточности первопричины: **(1)** code-path, детерминированно исключающий tool-вызов/генерацию; **(2)** воспроизводимая проба; **(3)** лог/статус конкретного режима отказа.

> **Дисклеймер (Critical KG `Risk-a0-false-toolcall-cause`).** Ниже **доказанные механизмы** (EVIDENCE) отделены от **неподтверждённых причин** (HYPOTHESIS). Вывод «дело только в промпте» — **запрещён**; по коду он и **опровергнут** (§6.3, место №1/№2/№9). Итог A0: **полная первопричина не установлена** — доказаны конкретные code-path-механизмы отказа и составлен план верификации для неподтверждённых кандидатов.

<a id="root-cause-candidates"></a>
### 6.1. Пять кандидатов Step 0

| Кандидат | Метка | Доказательство / основание | Вклад |
|---|---|---|---|
| **(а)** Пре-гейт ключевика перехватывает до LLM | **EVIDENCE (code-path)** — механизм для сообщений, совпавших с `IMAGE_KEYWORD_RE`; обобщение на общий симптом — **HYPOTHESIS** (см. HY-06) | `direct_chat_service.py:688–693` (пре-гейт **до** Stage-1 `:766`); при срабатывании `image_pre_gate_fired=True` → `image_enabled=False` (`:748–749`) → `active_tools` исключает `generate_image` (`tool_schemas.py:382–383`). Регэксп требует начала сообщения `бот|bot` + явный глагол (`image_generation.py:93–101`) | Узкий: только форма «Бот, нарисуй …». Свободная форма («нарисуй кота») пре-гейт **не** ловит → tool-путь объявляется |
| **(б)** plain-fallback при провайдер-отказе tools на 1-м раунде | **EVIDENCE (code-path)** — механизм; факт срабатывания в проде — **HYPOTHESIS** (см. HY-04) | `tool_loop.py:125–135`: `LLMError` на `round_index==0` → `llm.generate(...)` **без tools** → plain-ответ; `generate_image` не вызывается. Факт провайдер-отказа — без лога не подтверждён | Высокий, если провайдер/модель отвергает `tools` |
| **(в)** рубильники модуля | **EVIDENCE (code-path)** — механизм; фактическое состояние env/per-chat — **HYPOTHESIS** (см. HY-03) | `image_generation.resolve_module_enabled` (`:170–187`) — env `IMAGE_GENERATION_ENABLED` AND каталожный `flags.image_generation_module_enabled` (per-chat); OFF → `active_tools` исключает инструмент (`tool_schemas.py:382–383`), `_generate_image` возвращает `status:error` (`tool_router.py:1445–1448`), пре-гейт возвращает `""` (`direct_chat_service.py:1357–1358`). Дефолт env = True; фактическое per-chat состояние в A0 не читается | Детерминированный блокер, если OFF |
| **(г)** провайдер/модель tool calling | **HYPOTHESIS** (см. HY-01) | Живой прогон запрещён (D2); логов провайдера в A0 нет. Косвенно: `plain-fallback` (б) существует именно на случай провайдер-отказа | Возможен; не подтверждён |
| **(д)** реальная ошибка генератора | **HYPOTHESIS** (см. HY-02) | Код различает классы причин (`image_generation.reason_class`, `:325–338`: timeout/network/unauthorized/bad_request/rate_limited/budget/bad_json/too_large/…), но фактические значения в проде A0 не видит | Возможен; не подтверждён |

<a id="root-cause-9places"></a>
### 6.2. Девять возможных мест §12 (verbatim: описание инструмента; схема аргументов; модель; провайдер; обработчик `tool_calls`; маршрутизация; отсутствие второго шага после tool response; ошибка генератора; неверная передача промпта)

| № | Место | Метка | Вывод |
|---|---|---|---|
| 1 | Описание инструмента | **EVIDENCE (не причина по коду)** | Description присутствует (EN, «Call when the user asks to draw…»), `tool_schemas.py:319–322`; канон R9 не нарушен. Дефекта описания в коде не выявлено; «промпт — единственная причина» не подтверждается. Потенциальное влияние на выбор модели — **HYPOTHESIS** (нужна проба) |
| 2 | Схема аргументов | **EVIDENCE (не причина по коду)** | Схема валидна: `prompt: string` required, `additionalProperties:false` (`tool_schemas.py:323–332`); совпадает с тем, что читает `_generate_image` (`tool_router.py:1449`). Дефекта нет |
| 3 | Модель | **HYPOTHESIS** | Поддержка tools конкретной моделью в проде — без прогона/лога не доказана |
| 4 | Провайдер | **HYPOTHESIS** | То же; связка с кандидатом (б) |
| 5 | Обработчик `tool_calls` | **EVIDENCE (исправен)** | `tool_loop.py:157–190` обрабатывает `tool_calls` (усечение до 2, `assistant`+`role:tool`), `llm_client.py:1200+` парсит вызовы. Дефекта не выявлено |
| 6 | Маршрутизация | **EVIDENCE (исправна)** | `tool_router.py:457–468` содержит `generate_image` → `_generate_image` (`:1437`). Дефекта нет |
| 7 | Отсутствие второго шага после tool response | **EVIDENCE (опровергнуто)** | Второй шаг **есть**: после `role:"tool"` цикл повторяет LLM-вызов (`tool_loop.py:112,172–190`). Это место — **не** причина |
| 8 | Ошибка генератора | **HYPOTHESIS** | См. кандидат (д) |
| 9 | Неверная передача промпта | **EVIDENCE (не причина по коду)** | Промпт передаётся корректно: `_require_str(arguments,"prompt")` → `generate_and_send(prompt, …)` (`tool_router.py:1449–1457`); прямой путь — `extract_prompt` (`image_generation.py:163`). Дефекта нет |

<a id="root-cause-verdict"></a>
### 6.3. Итог по первопричине

- **Доказанные (EVIDENCE) механизмы отказа**, каждый — code-path, детерминированно исключающий tool-вызов/генерацию при выполнении условия:
  - **(а)** совпадение с `IMAGE_KEYWORD_RE` → tool-путь принудительно OFF на ход (узкий триггер);
  - **(б)** провайдер-отказ `tools` на 1-м раунде → plain-ответ без инструментов;
  - **(в)** модуль OFF (env или per-chat) → инструмент не объявляется / возвращает `status:error`.
- **Опровергнутые как причина:** место №7 (второй шаг существует), а также места №1/№2/№9 (описание/схема/передача промпта исправны). **Вывод «дело только в промпте» запрещён и по коду не подтверждается.**
- **Неподтверждённые (HYPOTHESIS):** (г) провайдер/модель и (д) реальная ошибка генератора; фактическое состояние рубильников (в) и фактическая частота срабатывания plain-fallback (б) — детализация в **HY-01…HY-06** (Приложение A). Причина **не** выдаётся за доказанную.
- **План проверки (для A3/A4):**
  1. **(г)** — проба tool-совместимости выбранной модели (мок/пробный `chat/completions` с `tools`), сверка `finish_reason`/наличия `tool_calls`; отдельно — `image_generation.probe` для провайдера изображений.
  2. **(д)** — разбор прод-логов `[image] generation failed | reason=…` и `[image] attempt failed | reason_class=…` (`image_generation.py:810–831,913–917`); классификация причин по `reason_class`.
  3. **(в)** — чтение фактических `IMAGE_GENERATION_ENABLED` / `flags.image_generation_module_enabled` (глобально и per-chat).
  4. **(б)** — лог `[tools] provider rejected tools — plain answer` (`tool_loop.py:127–129`) как детектор срабатывания.
  5. **(а)** — подтверждение, что наблюдаемый «отказ tool calling» относится к свободной форме (не к форме «Бот, нарисуй …»), иначе симптом объясняется пре-гейтом.

**Анкоры:** `#root-cause`, `#root-cause-candidates`, `#root-cause-9places`, `#root-cause-verdict`.

---

<a id="duplicates"></a>
## 7. Дубликаты / пересечения / зависимости инструментов

**REQ-A0-17 · SC-17.**

- **Новых инструментов A0 не создавал** (read-only). Канон **10** сохранён (`tool_schemas.py:337–348`); имена/состав/порядок/`required` не менялись. **EV-01.**
- **Дубликатов нет:** реестр `dispatch` (`tool_router.py:457–468`) содержит ровно 10 уникальных имён, совпадающих с каноном; `factcheck_tools` (`tool_schemas.py:401–415`) **переиспользует те же схемы байт-в-байт**, а не дублирует их. **EV-04, EV-05.**
- **Пересечения (по назначению, не по реализации):**
  - `dig_into_lore` ↔ `compile_lore_story` — «быстрые факты» vs «тяжёлый нарратив»; разведены парными EN-описаниями (канон R9). **EV-01.**
  - `summarize_video` ↔ `transcribe_video` — «выжимка» vs «сырой текст»; общий источник/резолвер `_resolve_tool_source` (`tool_router.py:995–1027`), разные наборы kinds (`VIDEO_KINDS` vs `MEDIA_KINDS`). **EV-16-родственные.**
  - `get_recent_history` ↔ `query_chat_memory` ↔ RAG — хронология/счётчики vs семантический RAG; разведены на уровне назначения и описаний.
- **Зависимости:** все инструменты идут через единый `ToolDeps` (`tool_router.py:359–387`) и `ToolContext` (`:390–430`); бюджет/таймауты — код-константы `tool_router.py:79–93`. Медиа-инструменты зависят от `native_media`/`transcriber`; `generate_image` — от `worker_budget` и `IMAGE_API_KEY`; `compile_lore_story` — от `deps.llm`/`deps.db`.
- **Вывод:** дубликатов не создано; канон 10 сохранён; пересечения выявлены и не требуют «склейки» в A0.

**Анкоры:** `#duplicates`.

---

<a id="epic3-handoff"></a>
## 8. Границы Эпика 3 и вход A1–A10 (handoff)

**REQ-A0-19 · SC-22.** A0 **ничего** из перечисленного ниже **не реализует** — фиксирует как вход (AMEND-точки).

> **Freeze каталога инструментов (ADR-1026-13 D3).** A0 **ничего не меняет** в `TOOL_CALLING_TOOLS` — канон **10** (`services/tool_schemas.py:337–348`; ADR-1020-4 → ADR-1023-5 → ADR-1024-20) сохранён без потерь. Расширение канона (координатор, `get_user_context`, image request) — предмет **A1/A2**, не A0. **EV-01.**

<a id="epic3-reuse"></a>
### 8.1. Обязательные контракты-предпосылки (REUSE, не переизобретать)

- **`physical-two-call-pipeline`** (ADR-1022-4 / ADR-1023-3/-6 / ADR-1026-5): координатор **не вводит 3-й LLM-вызов**; «не создавать дополнительный LLM-вызов там, где достаточно программной логики» (§13). Сохранить 2-вызовность DirectChat (`direct_chat_service.py:899–988`) и Саммари. В baseline `response_mode` едет в том же Stage-1 JSON (роутера третьим вызовом нет). **EV-26, EV-32.**
- **ADR-1023-3 — `action` vs `style`:** целевое разведение `ACTION ∈ {reply, react, silent, tool}` и `STYLE ∈ {casual, serious, deep_research}`; `style=null` для не-текстовых действий; запрет `style=silent` и пустого текста. В baseline есть только `response_mode` (STYLE) и канал доставки; поля `action` нет — вводится в §38–§40 (**A8**). **EV-26.**
- **ExecutionGraph REUSE** (§51 ТЗ; `plans/ARCHITECTURE.md` §65 F6 + §79 S8): переиспользовать `services/execution_graph_source.build_graph`, `web/api/analytics.py`, `web/static/execution_graph.js`; **не создавать вторую систему аналитики**; не писать выдуманные токены для алгоритмических шагов; молчание показывать без фиктивного Вербализатора. **EV-27-родственные (метрики L1/L2).**
- **§104 `generate_image` — НЕ ТРОГАТЬ** (`plans/current_task.md:3180–3203`): модель, провайдер, API-ключи, промпт обложки, параметры, обработка ошибок, порядок публикации, прикрепление — без изменений. Учитывая §6 (первопричина не доказана) — любые правки генерации только после пробы A3/A4.
- **Канон ADR-1013-3 (промпты):** изменения промптов — через `PREV_*`-слепки, `PROMPT_MIGRATIONS`, эталон; «один промпт — один источник данных» (дублирует §85).
- **§85 UI Саммари — отдельная санкция** (`plans/current_task.md:2646–2668`): изменения UI/каталога (Δ каталога ≠ 0) в A0 не выполняются; вне scope.

<a id="epic3-a1-a10"></a>
### 8.2. Что A1–A10 должны учесть и НЕ дублировать

- **Не создавать нового независимого агента** — расширять существующий Синтезатор без нарушения Adaptive System 2 (§11).
- **Не создавать дубликаты** инструментов/сервисов: `generate_image` уже есть (прямой + tool входы в один сервис); досье/RAG/фактчек уже существуют (см. §5).
- **Учесть выявленный конфликт image-путей:** при свободной форме инструмент доступен, при «Бот, нарисуй …» — пре-гейт выключает tool-путь (`direct_chat_service.py:748–749`). Целевой «единый image request» (§18–§21, **A3–A4**) обязан сохранить оба входа и общий бюджет.
- **Досье — не инструмент:** `get_user_context` отсутствует (EV-21); целевой structured memory lookup (§33, **A6**) вводится впервые, без дублирования `build_persona_card`.
- **Реакции/молчание:** baseline умеет только 🗿 по программному триггеру (EV-28); контур «когда молчать/реагировать/silent» (§41–§47, **A8–A9**) — новый.
- **Дневные лимиты изображений** (§26–§31, **A5**): уже есть `image_calls` (global+per-chat, EV-19) — расширять, не дублировать.
- **Decision Making** (§38–§40, **A8**): развести `action`/`style` поверх существующего `response_mode`; контракт решения — расширение, не замена.
- **Аналитика** (§48–§51, **A9–A10**): REUSE ExecutionGraph (§65/§79); карта вызовов — на существующем adapter, без второй визуализации.

<a id="epic3-summary"></a>
### 8.3. Сводка «интеграция / анти-дубликат» (обязательно для A1–A10)

| Точка | Что использовать (REUSE) | Что НЕ делать |
|---|---|---|
| Пайплайн | `physical-two-call-pipeline` (2 LLM-вызова, §13) | Не вводить 3-й LLM-вызов там, где хватает программной логики |
| Решение | расширить существующий `response_mode` (STYLE) | Не заменять контракт; `action`/`style` — ADR-1023-3, §38–§40 (**A8**) |
| Аналитика | `services/execution_graph_source.build_graph` + `web/api/analytics.py` + `web/static/execution_graph.js` (§65 F6 / §79 S8) | Не создавать вторую систему аналитики; без выдуманных токенов |
| Генерация изображений | существующий `image_generation.generate_and_send` (прямой + tool входы) | **§104 `generate_image` — НЕ трогать** (модель/провайдер/ключи/промпт/параметры/ошибки/порядок) |
| Промпты | канон **ADR-1013-3** (`PREV_*`, `PROMPT_MIGRATIONS`, эталон) | Не менять промпты вне канона |
| UI/каталог | — | **§85 UI Саммари — отдельная санкция**; Δ каталога ≠ 0 в A0 не допускается |
| Досье | `build_persona_card` + `format_dossier_block` (уже есть, §5.1) | Не дублировать; **`get_user_context` отсутствует** — вводится в **A6** |
| RAG/память | `get_rag_context`/`vector_search`/`search_long_term` (уже есть, §5.2) | Не создавать второй RAG-контур |
| Фактчек | `FactCheckService.check_claim` + `factcheck_tools` (уже есть, §5.3) | Не дублировать фактчек-инструменты |
| Бюджет изображений | `worker_budget` `image_calls` (global+per-chat, EV-19) | Не вводить второй счётчик; расширять существующий (**A5**) |
| Каталог инструментов | канон **10** (freeze, **D3**) | A0 не меняет каталог; новые инструменты — только **A1/A2** |

**Анкоры:** `#epic3-handoff`, `#epic3-reuse`, `#epic3-a1-a10`, `#epic3-summary`.

---

<a id="invariants"></a>
## 9. Инварианты

**REQ-A0-19 · SC-19…-23.**

| Инвариант | Как подтверждается | Метка |
|---|---|---|
| **Read-only (0 изменений product code/рантайма)** | `git diff` по product-путям пуст; изменяются только `plans/features/agentic-audit-round1026/**` и `plans/docs/agentic-audit-round1026.md` | EV-34 |
| **Δ DDL = 0** | SQLite остаётся v12; миграции/БД не трогались | EV-34 |
| **Δ каталога = 0** | `param_catalog.py` не изменён; REGISTRY 469 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21 / categorized 444 / Settings 426 | EV-29, EV-34 |
| **`APP_VERSION` без bump** | остаётся **2.58.29** | EV-34 |
| **R17** | в артефакте — только `file:line`/коды/числа; без ключей/промптов/сырых текстов/сырых ответов LLM | EV-34 |
| **R18** | тег `pre-round1026-a0` → `e8065e9` и бэкапы целы; не удалялись | EV-34 |
| **Аудит ≠ реализация** | A1–A10 не реализованы; артефакт описывает, не исправляет | EV-34 |
| **Deploy = NOT_APPLICABLE** | read-only; прецедент `ARCHITECTURE.md` §67/§70; откат — `git revert` docs-коммита | EV-34 |

**Анкоры:** `#invariants`.

---

<a id="traceability"></a>
## 10. Трассировочная матрица §12 пп.1–15 + §54 п.1 → разделы → REQ-A0 → SC

**REQ-A0-19 · SC-23.** Orphan-требований нет: каждый пункт §12/§54 п.1 имеет раздел артефакта, REQ и SC; каждый REQ-A0-01…-19 и каждый SC-01…-23 привязан к существующему разделу/анкору.

<a id="anchors"></a>
### 10.1. Реестр стабильных анкоров (для A1–A10)

> Анкоры заданы **явно** (`<a id="…">`) — не зависят от перестановки разделов и авто-слагов. Ссылка: `plans/docs/agentic-audit-round1026.md#<anchor>`.

| Анкор | Раздел |
|---|---|
| `#tool-map` | §1 карта инструментов |
| `#tool-map-llm` | §1.1 LLM-инструменты (канон 10) |
| `#tool-map-direct` | §1.2 не-LLM прямые пути |
| `#s12-1-2` | §2 §12 пп.1–2 |
| `#s12-1` / `#s12-2` | §2.1 / §2.2 |
| `#s12-3-5` | §3 §12 пп.3–5 |
| `#s12-3` / `#s12-4` / `#s12-5` | §3.1 / §3.2 / §3.3 |
| `#s12-6-7` | §4 §12 пп.6–7 |
| `#s12-6` / `#s12-7` | §4.1 / §4.2 |
| `#s12-8-15` | §5 §12 пп.8–15 |
| `#s12-8` … `#s12-15` | §5.1 … §5.8 |
| `#root-cause` | §6 первопричина |
| `#root-cause-candidates` / `#root-cause-9places` / `#root-cause-verdict` | §6.1 / §6.2 / §6.3 |
| `#duplicates` | §7 дубликаты/пересечения |
| `#epic3-handoff` | §8 вход A1–A10 |
| `#epic3-reuse` / `#epic3-a1-a10` / `#epic3-summary` | §8.1 / §8.2 / §8.3 |
| `#invariants` | §9 инварианты |
| `#traceability` | §10 трассировочная матрица |
| `#anchors` | §10.1 реестр анкоров |
| `#amend-a2-canon-11` | AMEND — A2 `tool-chains` (канон 10→11) |
| `#labels` | Приложение A |
| `#labels-evidence` / `#labels-hypothesis` / `#labels-forbidden` | Приложение A: EVIDENCE / HYPOTHESIS / запрещённый вывод |

### 10.2. §12 пп.1–15 + §54 п.1 → раздел → REQ → SC

| §ТЗ / источник | Verbatim (кратко) | Блок | Задача | Раздел артефакта | REQ | SC |
|---|---|---|---|---|---|---|
| §12 п.1 | «Все существующие инструменты.» | B | T-3484 | [§2.1](#s12-1) | REQ-A0-01 | SC-01, SC-16 |
| §12 п.2 | «Их JSON Schema и аргументы.» | B | T-3484 | [§2.2](#s12-2) | REQ-A0-02 | SC-02 |
| §12 п.3 | «Существующий механизм tool calling.» | B | T-3485 | [§3.1](#s12-3) | REQ-A0-03 | SC-03 |
| §12 п.4 | «Обработку результатов инструментов.» | B | T-3485 | [§3.2](#s12-4) | REQ-A0-04 | SC-04 |
| §12 п.5 | «Ограничения числа вызовов.» | B | T-3486 | [§3.3](#s12-5) | REQ-A0-05 | SC-05 |
| §12 п.6 | «Генерацию изображений по ключевой фразе.» | C | T-3488 | [§4.1](#s12-6) | REQ-A0-06 | SC-06 |
| §12 п.7 | «Генерацию изображений через LLM.» | C | T-3489 | [§4.2](#s12-7) | REQ-A0-07 | SC-07 |
| §12 п.8 | «Механизм извлечения досье.» | D | T-3491 | [§5.1](#s12-8) | REQ-A0-08 | SC-08 |
| §12 п.9 | «RAG и векторную память.» | D | T-3491 | [§5.2](#s12-9) | REQ-A0-09 | SC-09 |
| §12 п.10 | «Фактчек.» | D | T-3492 | [§5.3](#s12-10) | REQ-A0-10 | SC-10 |
| §12 п.11 | «Извлечение Markdown из URL.» | D | T-3492 | [§5.4](#s12-11) | REQ-A0-11 | SC-11 |
| §12 п.12 | «Decision Making Синтезатора.» | D | T-3493 | [§5.5](#s12-12) | REQ-A0-12 | SC-12 |
| §12 п.13 | «Текущую схему JSON между L1 и L2.» | D | T-3493 | [§5.6](#s12-13) | REQ-A0-13 | SC-13 |
| §12 п.14 | «Механизм реакций Telegram.» | D | T-3494 | [§5.7](#s12-14) | REQ-A0-14 | SC-14 |
| §12 п.15 | «Генеральные переключатели модулей и действующие лимиты.» | D | T-3494 | [§5.8](#s12-15) | REQ-A0-15 | SC-15 |
| §12 «Составить карту…» (8 полей) | Название/Назначение/Аргументы/Результат/Ошибки/Доступность/Зависимости/Последовательный вызов | B, E | T-3487, T-3495 | [§1](#tool-map) | REQ-A0-16 | SC-16 |
| §54 п.1 | «Карту существующих инструментов.» | E | T-3495 | [§1](#tool-map) + [§8](#epic3-handoff) | REQ-A0-16 | SC-16, SC-19, SC-23 |
| §12 «Не создавать дубликаты…» | «Не создавать дубликаты существующих инструментов.» | B, E | T-3484, T-3487, T-3495 | [§7](#duplicates) | REQ-A0-17 | SC-17 |
| §12 «Сначала установить, почему…» | 9 мест + запрет «только промпт» | C | T-3490 | [§6](#root-cause) | REQ-A0-18 | SC-18 |
| §11/§12/§54 п.1 инварианты | read-only, Δ DDL=0, Δ каталога=0, R17/R18, durable-артефакт | 0, E, F | T-3481, T-3495…-3499 | [§8](#epic3-handoff) + [§9](#invariants) | REQ-A0-19 | SC-19…SC-23 |

### 10.3. REQ-A0-01…-19 → раздел(ы) → SC (проверка orphan'ов)

| REQ | Раздел(ы) артефакта | SC |
|---|---|---|
| REQ-A0-01 | [§2.1](#s12-1), [§1](#tool-map) | SC-01, SC-16 |
| REQ-A0-02 | [§2.2](#s12-2), [§1](#tool-map) | SC-02 |
| REQ-A0-03 | [§3.1](#s12-3) | SC-03 |
| REQ-A0-04 | [§3.2](#s12-4) | SC-04 |
| REQ-A0-05 | [§3.3](#s12-5) | SC-05 |
| REQ-A0-06 | [§4.1](#s12-6) | SC-06 |
| REQ-A0-07 | [§4.2](#s12-7), [§4.3](#s12-6-7) | SC-07 |
| REQ-A0-08 | [§5.1](#s12-8) | SC-08 |
| REQ-A0-09 | [§5.2](#s12-9) | SC-09 |
| REQ-A0-10 | [§5.3](#s12-10) | SC-10 |
| REQ-A0-11 | [§5.4](#s12-11) | SC-11 |
| REQ-A0-12 | [§5.5](#s12-12) | SC-12 |
| REQ-A0-13 | [§5.6](#s12-13) | SC-13 |
| REQ-A0-14 | [§5.7](#s12-14) | SC-14 |
| REQ-A0-15 | [§5.8](#s12-15) | SC-15 |
| REQ-A0-16 | [§1](#tool-map), [§2.2](#s12-2), [§7](#duplicates) | SC-16, SC-19, SC-23 |
| REQ-A0-17 | [§7](#duplicates), [§1](#tool-map) | SC-17 |
| REQ-A0-18 | [§6](#root-cause) | SC-18 |
| REQ-A0-19 | [§8](#epic3-handoff), [§9](#invariants), [§10](#traceability) | SC-19, SC-20, SC-21, SC-22, SC-23 |

### 10.4. SC-01…SC-23 → раздел(ы) → REQ (проверка orphan'ов)

| SC | Раздел(ы) артефакта | REQ |
|---|---|---|
| SC-01 | [§2.1](#s12-1) | REQ-A0-01 |
| SC-02 | [§2.2](#s12-2) | REQ-A0-02 |
| SC-03 | [§3.1](#s12-3) | REQ-A0-03 |
| SC-04 | [§3.2](#s12-4) | REQ-A0-04 |
| SC-05 | [§3.3](#s12-5) | REQ-A0-05 |
| SC-06 | [§4.1](#s12-6) | REQ-A0-06 |
| SC-07 | [§4.2](#s12-7), [§4.3](#s12-6-7) | REQ-A0-07 |
| SC-08 | [§5.1](#s12-8) | REQ-A0-08 |
| SC-09 | [§5.2](#s12-9) | REQ-A0-09 |
| SC-10 | [§5.3](#s12-10) | REQ-A0-10 |
| SC-11 | [§5.4](#s12-11) | REQ-A0-11 |
| SC-12 | [§5.5](#s12-12) | REQ-A0-12 |
| SC-13 | [§5.6](#s12-13) | REQ-A0-13 |
| SC-14 | [§5.7](#s12-14) | REQ-A0-14 |
| SC-15 | [§5.8](#s12-15) | REQ-A0-15 |
| SC-16 | [§1](#tool-map), [§2.1](#s12-1) | REQ-A0-01, REQ-A0-16 |
| SC-17 | [§7](#duplicates) | REQ-A0-17 |
| SC-18 | [§6](#root-cause) | REQ-A0-18 |
| SC-19 | [§8](#epic3-handoff), [§9](#invariants) | REQ-A0-16, REQ-A0-19 |
| SC-20 | [§9](#invariants) | REQ-A0-19 |
| SC-21 | [§9](#invariants) | REQ-A0-19 |
| SC-22 | [§8](#epic3-handoff) | REQ-A0-19 |
| SC-23 | [§10](#traceability) | REQ-A0-16, REQ-A0-19 |

**Покрытие SC без потерь:** SC-01…SC-15 ← §2/§3/§4/§5; SC-16 ← §1/§2; SC-17 ← §7; SC-18 ← §6; SC-19 ← §8/§9; SC-20 ← §9; SC-21 ← §9; SC-22 ← §8; SC-23 ← §10.

**Проверка orphan'ов (T-3496):** §12 — **15/15** пунктов привязаны (§10.2); §54 п.1 — привязан; **REQ — 19/19** (§10.3); **SC — 23/23** (§10.4); все ссылки ведут на существующие анкоры (§10.1). **Orphan'ов нет.**

**Анкоры:** `#traceability`, `#anchors`.

---

<a id="labels"></a>
## Приложение A — реестр EVIDENCE / HYPOTHESIS

> Каждый вывод артефакта имеет ровно одну метку (ADR-1026-13 D2). `file:line` — baseline `e8065e9`.

<a id="labels-evidence"></a>
### EVIDENCE (подтверждено кодом baseline)

| ID | Утверждение | Ссылка |
|---|---|---|
| EV-01 | Канон `TOOL_CALLING_TOOLS` = 10, состав/порядок | `tool_schemas.py:337–348` |
| EV-02 | JSON Schema/аргументы всех 10 инструментов | `tool_schemas.py:51–334` |
| EV-03 | `active_tools()` — гейты lore/image/transcribe | `tool_schemas.py:367–389` |
| EV-04 | `factcheck_tools()` — 3 инструмента, реюз схем | `tool_schemas.py:398–415` |
| EV-05 | Диспетчер: реестр 10 имён, «не бросает» | `tool_router.py:455–480` |
| EV-06 | `TOOL_MAX_ROUNDS=4`, цикл LLM-вызовов | `tool_loop.py:38,112` |
| EV-07 | plain-fallback при провайдер-отказе tools (round 0) | `tool_loop.py:125–135` |
| EV-08 | Второй шаг после tool response (повтор LLM) | `tool_loop.py:167–190` |
| EV-09 | Усечение `tool_calls` до 2 | `tool_loop.py:158–162` |
| EV-10 | Graceful degradation при исчерпании раундов | `tool_loop.py:191–196` |
| EV-11 | `IMAGE_KEYWORD_RE` — пре-гейт ключевиков | `image_generation.py:93–101` |
| EV-12 | `extract_prompt` — снятие обёртки | `image_generation.py:163–167` |
| EV-13 | `maybe_handle_keyword` — генерация до Stage-1 | `image_generation.py:968–994` |
| EV-14 | Врезка пре-гейта до Stage-1 | `direct_chat_service.py:688–693,1345–1374` |
| EV-15 | Пре-гейт выключает tool-путь на ход | `direct_chat_service.py:748–749`; `tool_schemas.py:382–383` |
| EV-16 | Маршрут `generate_image` в роутере | `tool_router.py:1437–1468` |
| EV-17 | `generate_and_send` — общий сервис обоих путей | `image_generation.py:936–965` |
| EV-18 | `resolve_module_enabled` — env AND каталог (per-chat) | `image_generation.py:170–187` |
| EV-19 | Бюджет `image_calls` (global+per-chat, env-only) | `worker_budget.py:35,284–291`; `image_generation.py:491–510` |
| EV-20 | Досье: сборка карточки + `format_dossier_block` | `direct_chat_service.py:2068–2146`; `dossier_prompts.py:568–603` |
| EV-21 | `get_user_context` отсутствует (grep 0 совпадений) | `services/**`, `handlers/**` |
| EV-22 | Direct-RAG `<RAG_Memory>` | `direct_chat_service.py:2259–2357` |
| EV-23 | `get_rag_context`/`vector_search`/`search_long_term`, FTS5/vec0 | `summary_memory.py:2479,1855,1826` |
| EV-24 | Фактчек: `check_claim`/`_check_claim_two_call`/`_invoke_llm` | `factcheck_service.py:77,133,208` |
| EV-25 | Каскад trafilatura→Tavily→Exa | `web_content_extractor.py:59–95` |
| EV-26 | Decision Making: `normalize_response_mode`/`parse_direct_synthesis`/`_synthesize_direct_answer` | `system2_handoff.py:41,68,272`; `direct_chat_service.py:899–988` |
| EV-27 | JSON L1↔L2: контракты L1/пакета, `service{response_mode,cover_prompt}` | `summary_l1_contract.py:57–93,305`; `summary_fact_package.py:65–68`; `system2_handoff.py:53–65` |
| EV-28 | Реакции Telegram: `react_moai`/`set_message_reaction` | `smartmodule_utils.py:93–107` |
| EV-29 | Каталог: REGISTRY/GROUPS/TAB_RULES/`_TAB_BY_GROUP` | `param_catalog.py:147,1893,2124,2253` |
| EV-30 | Гейты фич `ALL_GATED_FEATURES`/`gates_enabled` | `feature_gates.py:32–34,134–169` |
| EV-31 | `generate_chat`: `tools`/`tool_choice` в payload, парсинг `tool_calls` | `llm_client.py:1132–1157,1200+` |
| EV-32 | Двухвызовный direct (условия запуска) | `direct_chat_service.py:814–824` |
| EV-33 | Dig пре-гейт ностальгии | `direct_chat_service.py:1288–1327` |
| EV-34 | Read-only-инварианты (diff/DDL/каталог/версия/R17/R18) | см. `evidence.md` (git-проверки) |

<a id="labels-hypothesis"></a>
### HYPOTHESIS (не подтверждено; с планом проверки)

| ID | Гипотеза | Почему не подтверждено | План проверки (волна) |
|---|---|---|---|
| HY-01 | Провайдер/модель не поддерживает `tools` в проде (кандидат г, места №3/№4) | Живой прогон запрещён (D2), логов провайдера нет | Проба tool-совместимости модели (A3/A4) |
| HY-02 | Реальная ошибка генератора изображений (кандидат д, место №8) | Нет прод-логов в A0 | Разбор `[image] generation failed | reason=…`/`reason_class` (A3/A4) |
| HY-03 | Рубильник модуля фактически OFF (env/per-chat) (кандидат в) | Фактическое состояние в A0 не читается | Чтение `IMAGE_GENERATION_ENABLED`/`flags.image_generation_module_enabled` (A3) |
| HY-04 | plain-fallback (б) реально срабатывает в проде | Нет лога `provider rejected tools` | Поиск лога `tool_loop.py:127–129` (A3) |
| HY-05 | Описание/схема инструмента (места №1/№2) влияют на выбор модели | По коду дефекта нет; влияние модели не измерено | A/B-проба описания (A3) |
| HY-06 | Симптом «отказ tool calling» относится к свободной форме, а не к форме пре-гейта (а) | Неизвестно, какие запросы наблюдались | Сверка наблюдаемых запросов с `IMAGE_KEYWORD_RE` (A3) |

<a id="labels-forbidden"></a>
### Запрещённый вывод

- **«Причина только в промпте»** — **не подтверждён и опровергнут** по коду: описание (№1), схема (№2) и передача промпта (№9) исправны (EV-02, EV-16); см. §6.2/§6.3.

**Анкоры:** `#labels`, `#labels-evidence`, `#labels-hypothesis`, `#labels-forbidden`.

---

<a id="amend-a2-canon-11"></a>
## AMEND — A2 `tool-chains-round1026` (T-3547 @Architect, 24.09.2026)

> Политика артефакта: обновление после Verified — **только AMEND-записью**. Исторический слой A0 (канон **10**, §7 `#duplicates`) **не переписывается** — фиксируется факт санкционированного расширения.

- **Канон инструментов: 10 → 11.** Санкция расширения (ADR-1026-13 **D3**, «расширение — предмет A1/A2») **использована** фичей A2 `tool-chains-round1026` (**ADR-1026-15 D5 → Accepted**; `plans/ARCHITECTURE.md` **§84**): добавлен 11-й инструмент **`fetch_article`** (в хвост `TOOL_CALLING_TOOLS`, ADR-1020-4); `factcheck_tools`=3 без изменений; kill-switch env-only `ARTICLE_TOOL_ENABLED` (OFF → эффективный канон 10).
- **Выводы A0 остаются в силе:** карта «10 × 8/8» (§1), дубликаты/прямые пути (§7), первопричина image-tool-calling (§6), HY-01…HY-06 — **не изменялись**; A0 остаётся read-only.
- **Прочие контракты A2 (без изменения этого артефакта):** envelope §16 (out-of-band спутник; модельно-видимый канал сохранён), §17-лимиты (cap 6 / мягкий 360 c / дедуп ≤2 / платные ≤4 / частичный результат), общий резолв ссылки `ctx.resolved_url`; границы A3/A4/A6/A7/A8/A9; §104/§85-UI не тронуты; REUSE ExecutionGraph; Δ DDL=0/Δ каталога=0.
- **Статус A2:** единый Reviewer gate **Approved C0/H0** (R3); **release policy EPIC_ONLY → deployment DEFERRED_TO_EPIC** (агрегат Эпика 3).
- **Ссылки:** `plans/features/tool-chains-round1026/{spec.md, adr-1026-15-tool-chain-contract-and-limits.md, review.md, evidence.md, threat-failure-analysis.md}` (на момент merge T-3547; **архивирована T-3548 @PM, 24.09.2026 → `plans/archive/tool-chains-round1026/`**); `plans/ARCHITECTURE.md` §84.
