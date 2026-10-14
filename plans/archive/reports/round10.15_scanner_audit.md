# Step 6 — SCANNER AUDIT раунда 10.15 (диff-аудит, независимый от @Reviewer)

> **Сканер:** @Scanner (фоновый аудитор логических ошибок). **Дата:** 14.09.2026.
> **Baseline:** HEAD `798e044`. **Объём:** незакоммиченный `git diff` (47 файлов) + untracked (9 фич F1–F9, `services/command_prefix.py`/`command_registry.py`/`media_send.py`, 8 новых test-файлов).
> **Метод:** построчный аудит диффа/untracked с file:line; независимое воспроизведение кейсов через `.venv/Scripts/python.exe`; прогон pytest/JS-гейтов. **Код НЕ правился.**

## 1. Валидатор (независимый прогон)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5761 passed**, 0 failed, 1 warning (`StarletteDeprecationWarning` — не наш код), 89.4s | 0 |
| `node --check web/app.js` | clean | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |

Целевые 8 новых файлов (`command_registry`, `sleep_fallback`, `nostalgia_revamp`, `tool_calling`, `recent_history_tool`, `guide`, `webapp_round1015_graph`, `webapp_round1015_ui`) — **162 passed / 0 failed**.

## 2. Findings

| ID | Severity | File:line | Описание | Рекомендация |
|---|---|---|---|---|
| **R10.15-1** | **Medium** | `services/command_prefix.py:51-58`; `handlers/youtube.py:186-193,1027-1040`; `handlers/web.py:82-90,118-137`; `info_text.md` §3/§4 (строки 25-31) | **F6↔F7: «ссылка-первой» из гайда не матчится fast-track.** `split_prefix` якорит префикс к `^` строки; гайд F7 и спека F7 §3 («Reply или ссылка в строке») дают пример `https://youtu.be/… Олег, поясни за видос` (ссылка перед командой). Воспроизведено: `youtube._triggered_body("https://youtu.be/dQw4w9WgXcQ Олег, поясни за видос") is None`, `web._triggered_body("https://example.com/a Олег, выжимка") is None`. До 10.15 `_has_trigger` был substring, а URL искался по полному тексту → link-first работал детерминированно; теперь уходит в LLM (недетерминированно, зависит от tool-call `summarize_video`). | Либо искать префикс/триггер не только в начале (для сценария «ссылка + фраза»), либо переписать примеры гайда (`Олег, поясни за видос https://…`). Добавить регресс-тест на link-first. |
| **R10.15-2** | **Medium** | `services/tool_router.py:578-596` (`_get_bot_health`, гейта флага нет); ср. `handlers/checkup.py:97`; `bot.py:409-410` | **F8: инструмент `get_bot_health` обходит master-флаг `flags.checkup_enabled`.** `checkup_service`/`_checkup_fetcher` создаются в `bot.py` безусловно; при выключенном модуле роутер 0g возвращает `UNHANDLED`, но LLM-инструмент всё равно вызывает `fetcher.fetch()` + `checkup()` (сетевой запрос логов + LLM-расход) для любого чата direct_chat. `_download_media` при этом флаг уважает (`:549`) — несогласованность. | Проверять `hot.get("flags.checkup_enabled", …)` в `_get_bot_health` (как в `_download_media`) либо не инжектить health в `ToolDeps` при выключенном модуле. |
| **R10.15-3** | **Medium** | `handlers/youtube.py:169-172,1030-1040`; `handlers/web.py:65-68,125-137`; `services/command_registry.py:84-90` | **F6: триггер ищется КАК ОТДЕЛЬНОЕ СЛОВО в любом месте остатка + безусловный консьюм без цели → ложное «съедание» обычной речи.** `has_trigger_word` (anywhere) + новый consume: `Олег, помнишь, мы обсуждали транскрипт того созвона?` → `_triggered_body` не None, `_classify_video_request` → None → бот отвечает «а ссылку-то приложить?» вместо LLM-ответа. До 10.15 такие сообщения уходили в LLM (`UNHANDLED`). `search`/`download`/`checkup` якорятся к началу остатка (`matches_group`/`_TRIGGER_RE`) и этим классом не страдают — только youtube/web. | Для consume-без-цели требовать якорь триггера к началу остатка (отдельный regex), `has_trigger_word` оставить только для разбора при наличии URL. Добавить регресс-тест «обычный текст с словом-триггером → не консьюм». |
| **R10.15-4** | Low | `handlers/direct_chat.py:102-116,461-463`; `bot.py:739-748`; `handlers/video_download.py:222` | **F6 M2-остаток: yield решается по hot-флагу, а доступность воркера — по startup-DI.** Роутер 4e регистрируется в `bot.py` только если `flags.download_enabled` был true при старте; если флаг включат в рантайме (hot) — `_functional_module_active("download")` вернёт true, direct_chat сдаст `UNHANDLED`, а роутера 4e в дереве нет → сообщение покинет direct_chat к нижестоящим catch-all (slavik/vasya) или останется без ответа. Аналогично при `_service/_fetcher is None` (0d–0g) yield не отменяется, хотя воркер неработоспособен. | Yield завязать на фактическую доступность воркера (наличие сервиса/роутера), а не только на флаг; либо регистрировать download-роутер всегда с внутренней проверкой флага. |
| **R10.15-5** | Low | `web/api/memory_agi.py:495-499` | **F5: `deep_sleep.active_until=None` при `dream_enabled=false` + `deep_enabled=true` + в окне** (after_sleep-ветка переиспользует `dream_active_until`, погашенный H1-гейтом `enabled`). Бейдж покажет «🌌 Глубокий сон идёт» без времени окончания. Косметика, но расходится с «до HH:MM». | Считать `deep_active_until` независимо: `_next_hour_epoch(end_h, …) if deep_in else None`. |
| **R10.15-6** | Low | `services/tool_router.py:598-625` | **F9: не реализован fallback `ctx.query`.** Спека F9 §5: «`ctx.query` используется как fallback, если модель не передала `query`». Реализация читает только `args.get("query")`; при `{}` от модели всегда идёт depth-путь. §2 (fallback depth=50) соблюдён, т.е. не exploitable. | Реализовать `query = args.get("query") or ctx.query` при наличии либо поправить спеку. |
| **R10.15-7** | Low | `services/command_prefix.py:85-87`; `services/command_registry.py:62-64` | **Мёртвый API (класс L1-итерации 2):** `is_functional_command` и `command_registry.matches` не вызываются в продовом коде (прод использует `functional_group`/`group_of`/`matches_group`/`has_trigger_word`); остались только в тестах и как spec-API. | Удалить или задокументировать как публичный контракт модуля. |
| **R10.15-8** | Low | `services/database.py:3651-3665` | **F1: `seed`-CTE берёт топ-N по degree из `edges` без проверки «видимости» узла** (`entity_name` non-empty / chat-скоуп). Топовый узел с пустым `entity_name` или вне `nodes` занимает слот сида, но отфильтровывается финальным WHERE → эффективных сидов меньше `seed_nodes` (крайний кейс; тест `test_orphan_removed_when_only_edge_hidden` показывает, что пустые имена достижимы). | Ограничить `seed` join’ом с `nodes` + nwhere (или считать `LIMIT` по валидным узлам). |
| **R10.15-9** | Low | `services/tool_router.py:539-572` | **F8: `download_media` (tool) не применяет download-кулдаун** роутера 4e (`handlers/video_download.py` `_cooldown`); в пределах tool-loop (4 раунда × 2 вызова) возможны серийные скачивания. Таймаут-частичные файлы не текут (`VideoDownloader.download_direct` чистит `out_path` в finally — проверено). | Переиспользовать общий кулдаун или ограничить число download-вызовов в tool-loop. |

### Info
- **Repo-wide R17-долг (вне диффа раунда, подтверждён):** `plans/current_task.md:62-65` содержит SSH-доступ и пароль. Файл в `.gitignore` (10.11), но уже в истории; рекомендовано сменить пароль и вычистить историю. К 10.15 не относится.
- Комментарий-заголовок `services/command_registry.py:11-15` перечисляет снятые алиасы — соответствует spec F6-U1; расхождений с реестром нет.
- `info_text.md` §5 упоминает `Бот, живой?` — триггер `живой?` в реестре строкой с `?`; проверено `matches_group("checkup","живой?") == True`, «живой»/«живой собака» — False.

## 3. Инварианты (независимо подтверждены)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/приватный текст в логах) | ✅ | новые логи `[tools]`: `mode`/`error=<class>`/`chat_id`/`count`/`out_chars`; `[Sleep]` — только числа; `[nostalgia]` lore/memes-ошибки без текста; `[config_cache]` миграция — только ключ. URL/query/тексты не логируются |
| R16 (id/entity_name/entity_type) | ✅ | `database.py:3669-3672`; `tool_router._history_lines` через `_resolve_name` |
| Порядок роутеров `bot.py` | ✅ | diff — только DI-kwargs (`:384-432`); 0d–0g/0h/4e не переставлены |
| Каталог 435/406/411/90/88/19 (Δ=0) | ✅ | полный pytest (в т.ч. пин-тесты каталога) зелёный |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| tool-сет = 7 | ✅ | `tool_schemas.py:177-185`; `field`-валидация схем — тесты `test_tool_calling_round1015` |
| PREV-слепок F4 + `PROMPT_MIGRATIONS` не тронут | ✅ | `git diff -- services/nostalgia_prompts.py` содержит `PREV_NOSTALGIA_PROMPT` байт-в-байт; `git diff -- services/prompt_migrations.py` — пусто |
| F6: нет флага `command_prefix_enabled` | ✅ | grep по репо — 0 |
| F6: реестр 17 + `чекап`/`фактчек` bare | ✅ | `command_registry.py:23-32`; поведенческие тесты |
| F8: успех download только после отправки | ✅ | `tool_router.py:558-572`; тест `test_download_failure_is_honest_error_no_send` |
| XSS / инъекции | ✅ | новый HTML без `v-html`; Vue `{{ }}`; SQL параметризован (`graph_snapshot`); `re.escape` в префиксе; лор/мемы идут только в LLM-промпт (не в HTML) |
| F5 аддитивность API (`next_wake_at`/`next_run_at` сохранены) | ✅ | `memory_agi.py:525-537` — только +`active`/`active_until` |

## 4. Итог

- **Critical: 0. High: 0. Medium: 3. Low: 6. Info: 3.**
- **Вердикт по контракту: открытых Critical/High — НЕТ.** Medium (R10.15-1/-2/-3) — функциональные/конфиг-расхождения, не production-blocking; рекомендовано закрыть до/вместе с шагом 7 (особенно R10.15-1 — правка гайда или матчера, и R10.15-2 — один гейт-чек).
- Регрессий смежных подсистем (evidence-driven) не выявлено: pytest 5761/0, JS-гейты чистые, PREV/каноны/каталог/роутеры целы.

*Round 10.15 scanner audit generated by @Scanner on 2026-09-14.*

---

## 5. Повторный аудит (итерация 2, 2026-09-14) — верификация фиксов @Builder

> **Метод:** повторный построчный аудит изменившихся участков + независимое воспроизведение кейсов
> (`command_prefix`/`youtube`/`web`/`tool_router`/`memory_agi`) + полный прогон валидатора. **Код НЕ правился.**

### 5.1 Статус R10.15-*

| ID | Было | Статус | Доказательство (file:line) |
|---|---|---|---|
| **R10.15-1** | Medium | **CLOSED** | Новая `split_prefix_anywhere` (`services/command_prefix.py:61-77`); ссылка-первой в `handlers/youtube.py:206-215` и `handlers/web.py:97-106` (URL обязан стоять ДО обращения, затем `matches_group` остатка). Воспроизведено: `https://youtu.be/dQw4w9WgXcQ Олег, поясни за видос` → `_triggered_body` не None, `_parse` даёт `video_id=dQw4w9WgXcQ`; web-аналог — `habr.com/... Олег, выжимка` → URL. Регресс-тесты: `test_command_registry_round1015.py:153-161,225-242`. |
| **R10.15-2** | Medium | **CLOSED** | `services/tool_router.py:623` — `if not hot.get("flags.checkup_enabled", settings.CHECKUP_ENABLED): return "ОШИБКА get_bot_health: модуль выключен"` ДО `health.fetcher.fetch()`/`checkup()`. Тест `test_tool_calling_round1015.py:438-455` (`fetch`/`checkup` не вызваны). |
| **R10.15-3** | Medium | **CLOSED** (с residual Low) | Консьюм без цели убран; обычная речь без URL → `UNHANDLED`: `youtube.py:200-205` / `web.py:91-96` (проверка `matches_group` ИЛИ `_has_trigger + URL`, иначе `None`). Воспроизведено: «Олег, помнишь транскрипт того созвона?» → YT/Web `None`; «Олег, транскриптер» → `None`. Тесты `:249-279`. Residual — см. R10.15-11. |
| **R10.15-4** | Low | **OPEN** (не менялся) | `handlers/direct_chat.py:461-463` yield по hot-флагу (`_functional_module_active`), а роутер 4e регистрируется в `bot.py:747-753` по startup-значению флага → рантайм-включение `download_enabled` = yield без воркера. Follow-up, не блокер. |
| **R10.15-5** | Low | **CLOSED** | `web/api/memory_agi.py:497-501` — `deep_active_until` считается независимо (`deep_enabled and in_window` → `_next_hour_epoch(end_h)`), больше не переиспользует погашенный `dream_active_until`. Тесты `test_webapp_round1015_ui.py:110-171`. |
| **R10.15-6** | Low | **CLOSED** | `services/tool_router.py:657-661` — `if not query and args.get("depth") in (None, ""): query = ctx.query` (явный `depth` не перекрывается). Тест `test_recent_history_tool_round1015.py:134-148`. |
| **R10.15-7** | Low | **CLOSED** | `is_functional_command` и `command_registry.matches` удалены; `grep -rn` по репо — 0 вхождений (ни в проде, ни в тестах). |
| **R10.15-8** | Low | **CLOSED** | `services/database.py:3651-3652` — `seed AS (… JOIN nodes n ON n.id=d.nid WHERE <nwhere> …)`; скрытые узлы (пустой `entity_name`/чужой chat) больше не занимают слот сида. Тест `test_webapp_round1015_graph.py:105-118`. |
| **R10.15-9** | Low | **CLOSED** | `services/tool_router.py:576-591` (`cooldown_refresh`→`cooldown_remaining`→`cooldown_touch` через общий трекер 4e); provider `handlers/video_download.py:116-122` `get_download_cooldown`, DI `bot.py` `download_cooldown=get_download_cooldown`. Тесты `test_tool_calling_round1015.py:289-335` (блок без download / success жжёт / нет провайдера — noop). |

### 5.2 Остаточные Low (новые, итерация 2)

| ID | Sev | File:line | Описание | Рекомендация |
|---|---|---|---|---|
| **R10.15-10** | Low | `services/command_prefix.py:71-77`; `handlers/youtube.py:206-215`; `handlers/web.py:97-106` | **Link-first привязан к ПЕРВОМУ вхождению имени.** `split_prefix_anywhere` возвращает токен первого совпадения (токены отсортированы, «олег» матчит раньше склонений), поэтому `эй Олег, смотри https://youtu.be/x Олег, поясни за видос` → `at` у первого «Олег» (URL ещё не было) → `None` → валидная команда уходит в LLM. Воспроизведено. Крайне узкая формулировка. | Перебирать совпадения регулярки, выбирая первое, у которого `text[:start]` содержит URL, либо брать последнее совпадение в URL-содержащей строке. Матч по «первому» документировать, если осознанно. |
| **R10.15-11** | Low | `handlers/youtube.py:203`; `handlers/web.py:94` | **«Валидная цель» = любой http-URL.** Путь «триггер в любом месте + URL» принимает любой URL (`extract_urls`/`extract_web_url`), тогда как `_classify_video_request` требует YouTube/direct-media. Итог: «Олег, глянь https://habr.com/x — там транскрипт обсуждают» → консьюм с фразой «а ссылку-то приложить?» при наличии ссылки (до 10.15 уходило в LLM). Воспроизведено (`_triggered_body` ≠ None). Частичный residual R10.15-3. | Считать целью только реально обрабатываемый тип ссылки (YouTube/direct-media для youtube; web-URL для web) либо в фразе без цели учитывать наличие любой ссылки. |

### 5.3 Валидатор (итерация 2)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5774 passed**, 0 failed, 1 warning (`StarletteDeprecationWarning` — не наш код), 82.1s (было 5761 → +13) | 0 |
| `node --check web/app.js` | clean | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| `git diff --check` | чисто (только LF→CRLF warnings, whitespace-errors нет) | 0 |

### 5.4 Инварианты (итерация 2)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 | ✅ | новые логи tool-сета: `chat_id`/`count`/`out_chars`/`error=<class>`/`mode`; URL/тексты логов/инструментов не пишутся |
| R16 | ✅ | `tool_router._history_lines` → `_resolve_name`; `graph_snapshot` id/label/group |
| Порядок роутеров `bot.py` | ✅ | diff — только import + DI-kwargs в `on_startup`; `include_router` (654-762) не тронуты; download-роутер по-прежнему 4e (после direct_chat) |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| Каталог 435/406/411/90/88/19 | ✅ | полный pytest зелёный (в т.ч. пин-тесты `test_param_catalog.py` — 406/GROUPS 90) |
| tool-set = 7 | ✅ | `tool_schemas.py` `TOOL_CALLING_TOOLS` — 7 (query_chat_memory, dig_into_lore, execute_web_search, summarize_video, download_media, get_bot_health, get_recent_history) |
| PREV F4 байт-идентичен | ✅ | AST-сравнение HEAD `NOSTALGIA_PROMPT` == текущий `PREV_NOSTALGIA_PROMPT` (451 симв., `True`) |
| `PROMPT_MIGRATIONS` не тронут | ✅ | `git diff -- services/prompt_migrations.py` — пусто |
| F1–F9 / реестр F6 | ✅ | 8 новых тест-файлов + обновления зелёные; `command_registry` 17+2 bare, word-boundaries |

### 5.5 Вердикт по контракту (итерация 2)

- **Все три Medium (R10.15-1/-2/-3) закрыты фактически** (не декларативно): код + воспроизведение + регресс-тесты.
- **Новое распределение: Critical 0 / High 0 / Medium 0 / Low 3 (R10.15-4 OPEN + R10.15-10/-11 новые) / Info 3.**
- **Контракт: открытых Critical / High / Medium — НЕТ.** Остаточные Low не блокируют шаг 7; R10.15-4 — осознанный follow-up.
- Регрессий смежных подсистем не выявлено: pytest 5774/0, JS-гейты чистые, каноны/каталог/роутеры/PREV целы.

*Round 10.15 scanner audit, iteration 2 — generated by @Scanner on 2026-09-14.*
