# @Scanner — diff-based аудит эпика `round1020` (T-1915, Step 6)

- **Дата:** 16.09.2026. **Baseline:** HEAD `2f3e1f0` (pytest 6326).
- **Объект:** рабочая копия эпика (91 изменённый + 8 новых файлов), diff-based.
- **Инструменты:** `git status/diff`, чтение ядровых путей, pytest (полный), 4 JS-гейта.
- **R17:** значения секретов не печатаются (только файлы/факты).

## 1. Сводка severity

| Severity | Кол-во | Блокирует? |
|---|---|---|
| Critical | **0** | — |
| High | **1** | **ДА** (возврат к @Builder) |
| Medium | 7 (из них 3 — подтверждение находок @Reviewer) | нет |
| Low | 9 | нет |
| Info | 5 | нет |

**ВЕРДИКТ: есть Critical/High — требуется возврат к @Builder.**
Причина: `web/index.html` — в generic-ветке конфиг-вкладок удалены кнопки «Сохранить»,
а sticky-save добавлен только в 3 других места (модалка «Модулей», вкладка «Доступы»,
модалка досье). На всех конфиг-вкладках правки текстовых/int/json/промпт-полей и ключей
сохранить невозможно. @Reviewer это пропустил (его тест проверяет только **отсутствие**
точечных кнопок, а не наличие панели).

---

## 2. High

### S10.20-1 [High] Конфиг-вкладки потеряли возможность сохранения (регресс T-1900)

- **Файл:** `web/index.html:170-700` (ветка `v-else-if="currentTabIsConfig"`), конкретно
  шаблоны элементов `web/index.html:537-581` (`json`/`prompts`/`content`, `keys`/`secret`,
  прочий `input`) и advanced-блоки `web/index.html:594-659`.
- **Что:** диффом удалены все точечные кнопки «Сохранить»/«Сохранить ключ»
  (`git diff` hunks `-539,12`, `-565,12`, `-589,12`, `-645,12`, `-662,8`, `-677,12`),
  но `<sticky-save>` в этой ветке **не добавлен**. Панель есть только:
  `web/index.html:962` (футер модалки «Модули»), `web/index.html:1544`
  (конец ветки `activeTab === 'access'`), `web/index.html:2689` (футер модалки досье).
  Ветка `currentTabIsConfig` закрывается на `web/index.html:700` — панели внутри нет.
- **Влияние (функциональный блокер UI):** на вкладках «LLM Провайдеры» (базовые поля),
  «Промпты», «Память», «Умный кэш», «Имена», «Реакции-Триггеры», «Лор чатов» и `mod_*`
  config-вкладках **нельзя сохранить** textarea/input/JSON/промпты и ключи (key-drafts
  сохраняются только через `dirtyKeyItems` sticky-панели). Авто-сейв остался лишь у
  `bool` (`index.html:515`) и `widget=select` (`index.html:571`); `kv-editor`/`list-editor`
  имеют собственные кнопки. Правки молча теряются при перезагрузке — при живом деплое
  это выглядит как «настройки не применяются» на большинстве вкладок.
- **Почему пропущено @Reviewer:** `tests/test_webapp_round1020_ui.py:184-189` проверяет
  «`>Сохранить<` больше нет» в срезе от `currentTabIsConfig` до `activeTab === 'relations'`
  (срез включает и ветку «Доступы», где панель есть), а `tests/js/round1020_ui_test.js:393`
  — только `INDEX.indexOf('<sticky-save') >= 0` (любое вхождение).
- **Ремонт (минимальный):** добавить `<sticky-save class="col-span-full"></sticky-save>`
  в конец ветки `currentTabIsConfig` (перед `web/index.html:700`) + в тестах проверять
  наличие панели **для каждой** ветки, где удалены точечные кнопки (config / modules / access).

---

## 3. Medium

### S10.20-2 [Medium] Per-chat гейт «Летописца» не соблюдается в самом инструменте
`services/direct_chat_service.py:681` резолвит флаг per-chat
(`get_chat_param`: override → hot → default) и этим формирует `active_tools(...)`,
а `services/tool_router.py:1005` (и `services/factcheck_service.py:92`) читают флаг
**только глобально** (`hot.get(...)`). Сценарий: глобально `OFF`, для чата `ON` → модель
**видит** инструмент, вызывает, получает «Инструмент compile_lore_story отключен.»
**Ремонт:** резолвить флаг тем же `get_chat_param(chat_id, ...)` внутри `_compile_lore_story`
(и в фактчеке) либо явно задокументировать «глобальный рубильник, per-chat игнорируется».

### S10.20-3 [Medium] `dig_into_lore`: JSON-контракт ломается капом `dig_max_symbols`
`services/tool_router.py:644-646` возвращает `_truncate(json.dumps(result), dig_max_symbols)`,
где `_truncate` (`tool_router.py:225-229`) режет по символам и дописывает `…`. Тексты
сообщений из `search_long_term` не капнуты (`summary_memory.py:1727-1737`), `DIG_MAX_SYMBOLS`
по умолчанию 3500 (`config/settings.py:1123`) → при длинных сниппетах JSON приходит модели
**невалидным** (нет закрывающих скобок). До раунда усечение было по plain-тексту (безвредно).
**Ремонт:** собирать JSON после усечения секций (обрезать `snippets`/`facts` по бюджету,
а не строку JSON целиком) или явно возвращать `truncated: true`.

### S10.20-4 [Medium] Фактчек получает инструкцию «верни story ДОСЛОВНО» + HTML в plain-режим
`services/tool_router.py:88-92` (`_LORE_RETURN_INSTRUCTION`) добавляется в tool-output
в **любом** вызове, включая фактчекер (`factcheck_tools()` содержит `compile_lore_story`).
В фактчеке `ctx.lore_compiled` не читается (`factcheck_service.py:95-99`), доставка идёт
`cleanup_llm_text` → plain (`summary_cleanup.py:21-27`) → вероятный итог: вместо вердикта
приходит история, а теги `<b>/<i>` видны пользователю как сырой текст.
**Ремонт:** не добавлять инструкцию, когда вызывающий — не DirectChat (или срезать
HTML-теги из lore-текста в `cleanup_llm_text`), либо убрать `_LORE_RETURN_INSTRUCTION`
вообще (детерминизм уже обеспечен `ctx.lore_story`).

### S10.20-5 [Medium] UPD-механика `lore_stories`: `last_ts` может обогнать фактически включённые данные
`services/lore_compiler_service.py:134-137`: `last_ts = max(since, dense.latest, stats.last_seen)`,
при этом в историю попадают только: топ-3 самых плотных окна
(`database.py:lore_dense_dialogs`: `max_scan=300`, `max_dialogs=3`, `max_window_rows=60`)
и кап `_LORE_DIALOG_MAX_SYMBOLS=6000` (+ `_trim`). Сообщения, попавшие в `total/last_seen`,
но не в окна/капы (или пришедшие между COUNT-запросом и upsert), навсегда исключаются
из будущих UPD (`ts > last_ts`). **Ремонт:** `last_ts` считать по **включённому** в промпт
материалу (максимум по `dialog_lines`), а не по глобальным агрегатам.

### S10.20-6 [Medium] Sticky-save «благословляет» неудачное сохранение как baseline
`web/app.js:2646-2670` (`saveModalEdits`): при ошибке `saveConfigItem` (`app.js:3775-3784`)
конфиг **не перезагружается** (reload только на 409), значения остаются в `configItems`,
после чего вызывается `this._snapshotConfig()` → неуспешно сохранённые правки становятся
новым baseline и индикатор «Изменено: N» гаснет. Пользователь видит toast об ошибке, но
панель говорит «Нет изменений»; повторно сохранить через sticky уже нельзя (только уйти
с/на вкладку). **Ремонт:** не вызывать `_snapshotConfig()` при наличии ошибок
(собирать `failed`-список в `saveModalEdits`) и подсвечивать их в панели.

### S10.20-7 [Medium] «Бюджет контекста»: acct-лимит затирает per-chat cap
`services/status_service.py:536-542`: `limit = acct.get("context_limit") or ctx_cap`.
`acct` — последний счётчик процесса (глобальный/последнего чата), поэтому при живом
`acct.context_limit` per-chat cap (новый резолв `status_service.py:511-531`) не показывается
— реактивность виджета по chat_id работает только для `unlimited`. **Ремонт:** при
непустом per-chat override отдавать его в приоритете (или отдавать `source`).

### S10.20-8 [Medium — подтверждение @Reviewer M1] `_trim` режет канонический заголовок
`services/lore_compiler_service.py:241-257` (`out.append(text[:room])`) обрезает строку
посередине `[ts | Автор | id]:` — противоречит «метаданные неприкосновенны»; влияет
только на вход синтеза. **Ремонт:** `truncate_keep_header` или `break` без `text[:room]`.
(Также подтверждаю M2 `_LORE_NODE_SCAN_LIMIT=2000` по `id` и M3 `ORDER BY RANDOM()`
в `dossier_feed` при GLOBAL-поллинге 45 с — обе не блокирующие, но перф-риск на росте БД.)

---

## 4. Low

### S10.20-9 [Low] Реестр `CONTEXT_POINTS`: pattern точки `legacy_rag` не соответствует рантайму
`services/canonical_context.py:124-128` требует `^\[\d{2}\.\d{4} \| Автор: [^\]]+\] `,
но `_search_graph_facts` теперь отдаёт 6-кортежи (`summary_memory.py:2584-2590`), и в
legacy `<context>` уходит канонический header `[04.2024 | Толян | fact:1 | Переслано: …]: `
(`summary_memory.py:1011-1024`). `_sample_legacy_rag` строит 4-кортеж вручную
(`tests/test_memory_core_round1020.py:145-147`) → инвентарный тест для этой точки вакуумный.
Аналогичный гэп — reviewer Low #4 (`direct_rag`). **Ремонт:** добавить сэмплы с 6-кортежем
и расширить pattern (либо зафиксировать два допустимых варианта).

### S10.20-10 [Low] HTML-доставка Летописца: обрыв тега на границе чанка → дубль текста
`direct_chat_service.py:803-826` + `smartmodule_utils.py:183-192`: чанки режутся по пробелам
(`_chunk_by_whitespace`), тег может разорваться → `TelegramBadRequest` на чанке 2+ →
фолбэк пересылает **весь** ответ plain (часть 1 уже отправлена) → визуальное дублирование.
Вероятность низкая (story обычно < 4096), но при длинных историях реальна.
**Ремонт:** тег-безопасный чанкинг либо фолбэк только для чанков с ошибкой.

### S10.20-11 [Low] `escape_lore_html` пропускает `<a href="javascript:...">`
`services/smartmodule_utils.py:_LORE_HTML_TAG_RE`. В Telegram JS не исполняется, истории
в TMA не рендерятся (`{{ }}`) — практической уязвимости нет; при переносе историй в TMA
обязателен sanitize. (Подтверждение Low #5 @Reviewer.)

### S10.20-12 [Low] Time Injection ломает user-префиксный prompt-cache
`services/payload_builder.py:14-27`: время — первый user-блок, поэтому префикс
«system + первый user-блок» меняется каждую минуту. Утверждение «cache не сломан»
верно только для system-части (system в `messages[0]` действительно статичен).
Решение принято ADR-1020-3 (О2 FINAL) — фиксирую как принятый трейд-офф.

### S10.20-13 [Low] `initialize_existing()` не проверяет существование/схему БД
`services/database.py:570-584`: `aiosqlite.connect` создаёт пустой файл при неверном пути,
`PRAGMA user_version` не сверяется → `manage.py retention --apply` по ошибочному пути
отработает по пустой схеме и напечатает «reason=… deleted=0» вместо ошибки.
**Ремонт:** `Path.exists()` + проверка `user_version`/наличия таблиц.

### S10.20-14 [Low] `_date()` считает UTC, а диалог живёт в TZ чата
`services/lore_compiler_service.py:231-239` (`time.gmtime`) — статистика «первое/последнее
упоминание» в истории Летописца может расходиться на сутки с TZ чата (О4/`limits.chat_timezone`).

### S10.20-15 [Low] `_EMPTY_DENSE` — общий мутабельный список между вызовами
`services/lore_compiler_service.py:46,88`: `dict(_EMPTY_DENSE)` копирует словарь, но
`dialogs: []` — один и тот же объект. Сейчас не мутируется (проверено), но это латентная ловушка.

### S10.20-16 [Low] Докстринг «fail-open» у `dossier_feed` не соответствует коду
`services/database.py:4393-4410`: исключения наружу (API ловит сам, `web/api/oversight.py:186-192`);
`get/set/delete_dossier_override` тоже без try/except (у PUT есть 503-ветка). Формально ок,
но докстринг обещает больше, чем делает код.

### S10.20-17 [Low] `persona_dossier_overrides` — запись доступна moderator'у (паритет с relations)
`web/api/chat_lore.py:put_dossier` → `_require_chat` → `can_access_chat` (global/local admin,
moderator). Новой эскалации нет (как у relations-write), но это **новый** изменяемый
артефакт — стоит зафиксировать в матрице ролей.

---

## 5. Info

- **S10.20-18** `LLMChatResult.reasoning` (`services/llm_client.py:226-229`) не имеет
  потребителей, кроме WARNING в `llm_client.py:1054-1060` — телеметрия по ADR, ок.
- **S10.20-19** `search_messages_fts_count_by_author` группирует по `(author_name, user_id)`;
  один человек с разными `author_name` приходит несколькими строками — мердж по имени делает
  вызывающий (`tool_router.py:617-620`, `lore_compiler_service._mentions_by_authors`). Ок.
- **S10.20-20** Диалоги Летописца включают сообщения **всех** авторов внутри окна ±30 мин
  (`lore_dense_dialogs`) — соответствует спеке, но контекст тяжелее «только совпадений».
- **S10.20-21** `_LORE_TOPIC_MAX_CHARS=200` / `_LORE_GRAPH_*` / `_LORE_DIALOG_*` — код-константы
  (каталог-Δ=0), изменение требует ревизии кода — задокументировано.
- **S10.20-22** Пути подачи контекста вне реестра (`summary_memory._build_batch_text`,
  `direct_chat_service.py:1158` — стадии отношений) остались «голыми» осознанно (R42-канон
  `/compress`, служебная метка). В реестре не заявлены — гэп покрытия, не рантайм-баг.

---

## 6. Проверка блокеров (T-1904 / T-1931 / T-1913)

- Гейты **T-1904** (UI), **T-1931** (Справка) — по-прежнему ⏸ HUMAN PENDING; **T-1913** (SPEC_READY) не открывался.
- Code-гейты предыдущих фаз (T-1885/T-1893/T-1912/T-1927) **уже помечены `[x]` @Reviewer** —
  с учётом S10.20-1 их нужно **переоткрыть** (ревью UI-фазы D было code-passed ошибочно).
- До возврата к @Builder: деплой/приёмка владельцем не имеют смысла (сохранение настроек
  в мини-аппе не работает на конфиг-вкладках — живая приёмка упрётся в это сразу).

## 7. Подтверждено корректным (не требует правок)

1. **`ctx.lore_compiled` не протекает**: поле живёт на per-turn `ToolContext`
   (`tool_router.py:284-307`, создаётся в `direct_chat_service.py:687-690`); читается только
   после `chat_with_tools`; при деградации цикла история всё равно доставляется
   (`direct_chat_service.py:730-736`). Обычный ответ вне Летописца — байт-в-байт plain.
2. **`active_tools()`/`factcheck_tools()`**: возвращают новые списки, общие dict-схемы
   не мутируются (`generate_chat` только присваивает `payload["tools"]`), OFF → ровно 7 тулов.
3. **Деградация tool-loop**: `NoApiKeyForChat` — проброс; reject на 1-м раунде — plain-фолбэк;
   пустой финал — прежний `LLMBadResponseError`; лимит раундов/поздний `LLMError` — partial/заглушка.
   Трассировка `strip_reasoning_tags` (парные, незакрытые, «лишние» закрывающие, вложенные) — верна.
4. **`strip_reasoning_tags`**: без тегов — no-op байт-в-байт; порядок в `cleanup_llm_text`
   (сначала срез, потом типографика) сохранён.
5. **`truncate_keep_header`**: заголовок неприкосновенен, `limit<=0` → только заголовок,
   блок без канонического заголовка → прежнее поведение (XML-обёртки не затронуты).
6. **Миграция v11→v12**: порядок (после v11, после всех rebuild'ов graph_facts), guard по
   `PRAGMA table_info`, `ADD COLUMN` без rebuild (FTS5/vec0 не тронуты), `user_version=12`
   безусловно (прецедент v9–v11), legacy-строки NULL/'' толерантны, PG-путь `graph_facts`
   не создаёт (в `pg_db.py` таблицы нет) — no-op.
7. **`lore_stories` / `persona_dossier_overrides`**: `CREATE IF NOT EXISTS`, `user_version`
   не поднимается (PRAGMA 12 в тестах); upsert по `UNIQUE(chat_id, topic_key)`;
   чтение/запись `lore_stories` — параметризовано, ошибки → WARNING (NFR-4).
8. **`memorize_facts`**: 17 колонок = 17 `?` = 17 параметров; аддитивные
   `tg_message_id=None`/`forward_from=''` — существующие вызовы не меняются (R16).
9. **`oversight._limits_block`**: `key_status` отдаёт тот же контракт, что прежняя
   `_limits_metric(contour='direct')` (`used/limit/unlimited/forbidden/source`) — поведение
   сохранено, чтений стало 1 вместо 2 (S10.19-15 закрыт).
10. **D206 / R42 / R46**: `order_rag_facts_asc` применяется ПОСЛЕ дедупа/реранка (состав top-K
    не меняется); `<chat_history>` XML, структура legacy-`<context>/<user_gossip>/<bot_knowledge>`
    и эталоны R42/R46 не тронуты (байт-тесты зелёные); `_line_markers`/`_fact_tokens`
    срезают канонический header корректно (первое `:` уезжало именно в заголовок).
11. **Безопасность**: все новые SQL параметризованы (динамические `?` — только из длин списков);
    RBAC досье — `_require_chat`, `dossier_feed` — `requires_global_admin`;
    открытие модалки модуля по `canViewTab('modules')` записи не даёт (`dirtyItems`/`saveModalEdits`
    фильтруют `canEditConfig`); XSS: досье/тикер — `{{ }}`, `v-html` не добавлялся.
12. **R17**: в diff'е round1020 секретов нет; `plans/MEMORY.md` упоминает untracked ТЗ-файл
    без значения (пре-существующий SSH-хост-токен в `plans/MEMORY.md` настоящим раундом не внесён
    и не тронут); логи нового кода — только числа/имена тулов/длины.
13. **`manage.py retention`**: dry-run по временному снапшоту (backup API), `--apply` —
    `initialize_existing()` без DDL/WAL-конфликта, вывод без путей; fsync каталога — осознанный
    no-op на win32 с честным INFO.
14. **Меню-freeze**: `TABS`/navbar/`MODULES` в diff'е `web/app.js` не менялись.

## 8. Валидатор (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv/Scripts/python.exe -m pytest tests/ -q --timeout=300` | **6523 passed, 1 warning, 0 failed** (89.52 s) |
| Синтаксис JS | `node --check web/app.js` | OK |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` |
| Vue mount | `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` |
| Round1020 UI | `node tests/js/round1020_ui_test.js` | `JS-UNIT-OK` |
| Diff whitespace | `git diff --check` | clean (exit 0) |

> Тесты **зелёные, но не покрывают** S10.20-1: срезы в `test_webapp_round1020_ui.py`
> проверяют отсутствие кнопок и наличие компонента, а не наличие панели в каждой ветке.

## 9. Остаточные риски

1. **S10.20-1 (High)** — единственный блокер; после фикса обязательна JS/Python-проверка
   «панель есть в каждой ветке, где нет авто-сейва» + живая приёмка владельцем (T-1904).
2. Регрессии данных нет: миграция аддитивна, откат — `git revert` + `DROP COLUMN` (SQLite ≥3.35) /
   удаление `lore_stories` (документировано в docstring'ах).
3. Перф: `dossier_feed` (`ORDER BY RANDOM()`) на GLOBAL + поллинг 45 с и кап
   `_LORE_NODE_SCAN_LIMIT=2000` — на росте БД проявятся первыми (S10.20-8/M2/M3).
4. Медиум-риски UPD Летописца (S10.20-5) и «благословения» ошибок sticky-save (S10.20-6)
   стоит закрыть до живой приёмки — иначе владелец увидит «история не догоняет» и
   «сохранил, а не применилось».

---

## 10. Re-audit (после фиксов @Builder, Step 6→4→6, 16.09.2026)

- **Метод:** адресная проверка по коду (не по отчёту @Builder) + повторный прогон гейтов.
- **Итог: 0 Critical / 0 High. Блокер S10.20-1 закрыт. ВЕРДИКТ: «нет Critical/High».**

### 10.1 Статусы находок (проверено по коду)

| Finding | Sev | Статус | Доказательство |
|---|---|---|---|
| S10.20-1 | High | **Closed** | `web/index.html:704` — `<sticky-save class="col-span-full">` в конце ветки `currentTabIsConfig` (до `</template>` :705); панели также :967 (модалка «Модулей»), :1549 (ветка «Доступы»), модалка досье — собственный `<footer class="sticky-save">` :2694. Тесты: `test_webapp_round1020_ui.py:191-208` и `tests/js/round1020_ui_test.js:393-407` проверяют панель **в каждой** из 3 веток (config/modules/access), `config.rindex` после `BYOK`. Ветки Промпты/Память/Имена/Умный кэш/LLM Провайдеры/Реакции/`mod_*`/chat_lore — все внутри `currentTabIsConfig`. |
| S10.20-2 | Medium | **Closed** | `tool_router.resolve_lore_compiler_flag` (:280-295) — `hot.get` → `get_chat_param`; вызывается в `_compile_lore_story` (:1092) и `factcheck_service` (:100). Тесты `TestLoreFlagPerChat` (global OFF + chat ON → тул работает). |
| S10.20-3 | Medium | **Closed** | `_dig_json_payload` (:232-277): усечение `snippets`/`facts` + `truncated:true` ДО `json.dumps`; иначе секции укорачиваются; финальный фолбэк — валидный JSON. Dispatch :715. Тесты `TestDigJsonContract` (в т.ч. `json.loads` при капе 600/50/700). |
| S10.20-4 | Medium | **Closed** | `ToolContext.lore_verbatim_instruction=False` в фактчеке (`factcheck_service.py:104-105`); `_compile_lore_story` добавляет `_LORE_RETURN_INSTRUCTION` только при `True` (:1134-1136); `strip_lore_html` (`smartmodule_utils.py:72-81`) применяется в plain-доставке фактчека (:125). Тесты `TestLoreInstructionAndHtml`. |
| S10.20-5 | Medium | **Closed** | `lore_compiler_service.py:111-118,156`: `included_last_ts = max(ts of _trim_pairs(...))`, `last_ts = max(since, included_last_ts)` — глобальные `dense.latest`/`stats.last_seen` больше не двигают. Тест `TestLastTsAdvancesByIncludedMaterial` (9_000_000 не принимается, сохраняется 1000). |
| S10.20-6 | Medium | **Closed** | `app.js:2656-2689` `saveModalEdits` собирает `failed`, `_snapshotConfig()` только при `failed.length === 0`; `saveConfigItem`/`saveKeyItem` возвращают `true/false` (:3791/-3801, :3845/-3848); панель рендерит `stickyFailed` (:6388). Тесты: `tests/js/round1020_ui_test.js:409-428`. |
| S10.20-7 | Medium | **Closed** | `status_service.py:528-543`: per-chat cap ≠ глобального → `ctx_cap=value`, `per_chat_limit`; `effective_limit = per_chat_limit or acct... or ctx_cap`; добавлен `context.source` (`chat`/`account`/`global`, :550-551). |
| S10.20-8 / M1 | Medium | **Closed** | `lore_compiler_service.py:283-313` `_trim_pairs` через `split_context_header`: режется только body, заголовок цел; строка без headers отбрасывается. Тест `TestTrimKeepsHeader` (3 кейса). |
| Reviewer M2 | Medium | **Closed (док)** | `database.py:2162-2164` докстринг `lore_graph_slice` фиксирует кап `_LORE_NODE_SCAN_LIMIT=2000` (детерминированный скан по id). |
| Reviewer M3 | Medium | **Closed** | `database.py:4457-4477` `dossier_feed`: случайная выборка из свежего пула `limit*20` (`ORDER BY id DESC` в подзапросе), а не `RANDOM()` по полному скану; докстринг «fail-open» приведён к коду. |
| S10.20-9 | Low | **Closed** | `canonical_context.py:120-132`: паттерны `direct_rag`/`legacy_rag` принимают 6-кортеж (`fact:ID`/`Переслано:`); сэмплы реестра обновлены (`tests/test_memory_core_round1020.py:139-163`). |
| S10.20-10 | Low | **Closed** | `direct_chat_service.py:821-841`: HTML-ветка — только если `len(escaped) <= 4096`; длинная история → plain `strip_lore_html` одной доставкой (без обрыва тега/дубля). |
| S10.20-11 | Low | **Closed (коммент)** | `smartmodule_utils.py:55-58`: задокументирован обязательный sanitize при переносе историй в TMA. |
| S10.20-12 | Low | **Принято (ADR-1020-3)** | Time Injection первым user-блоком — осознанный трейд-офф; system статичен. Не трогаем. |
| S10.20-13 | Low | **Closed** | `database.py:580-607` `initialize_existing`: `Path.exists()` → `FileNotFoundError`, проверка наличия таблиц → `RuntimeError` + `db=None`. Тесты `TestInitializeExistingValidation` (3 кейса). |
| S10.20-14 | Low | **Closed** | `lore_compiler_service.py:262-281` `_date(ts, tz_name)` — `ZoneInfo` по tz чата (передаётся из `tool_router._chat_timezone`); фолбэк UTC. |
| S10.20-15 | Low | **Closed** | `lore_compiler_service.py:54-57` `_empty_dense()` отдаёт свежий `dialogs: []`. Тест `test_empty_dense_is_fresh_per_call`. |
| S10.20-16 | Low | **Closed** | `database.py:4457-4461` докстринг приведён к фактическому поведению (ошибки не глотаются; «fail-open» — только пустой результат). |
| S10.20-17 | Low | **Принято (вне скоупа)** | Паритет RBAC `persona_dossier_overrides` moderator'у — новой эскалации нет, фиксируется в матрице ролей отдельно. |

### 10.2 Новые счётчики severity (после ре-аудита)

| Severity | Было | Закрыто | Открыто |
|---|---|---|---|
| Critical | 0 | 0 | **0** |
| High | 1 | 1 | **0** |
| Medium | 7 | 7 | **0** |
| Low | 9 | 7 (2 принято обоснованно) | **0 открытых** (S10.20-12/-17 — принято) |
| Info | 5 | — | 5 (без изменений, не блокеры) |

**Новых находок нет.** Регрессий от фиксов не выявлено.

### 10.3 Валидатор (ре-прогон, независимо)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv/Scripts/python.exe -m pytest tests/ -q --timeout=300` | **6546 passed, 1 warning, 0 failed** (87.49 s) |
| Синтаксис JS | `node --check web/app.js` | OK |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` |
| Vue mount | `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` |
| Round1020 UI | `node tests/js/round1020_ui_test.js` | `JS-UNIT-OK` |
| Diff whitespace | `git diff --check` | clean (exit 0; LF→CRLF-предупреждения без ошибок) |

### 10.4 Регрессионные инварианты (проверено)

- Меню/навигация: снимок 25 вкладок + navbar 6 + 12 карточек модулей — зелёный (`tests/test_webapp_round1020_ui.py`, `test_help_ui_round1020.py`).
- Prompt-cache/Time Injection: system-байты статичны, время — первым user-блоком (тесты `test_memory_core_round1020.py`).
- D206 / R42 / R46: байт-инварианты зелёные; «голых» строк новых нет (инвентарный тест из `CONTEXT_POINTS`).
- Секреты R17: в diff'е round1020 новых секретов/значений нет.

### 10.5 Вывод по блокеру

Блокер **S10.20-1 (High) закрыт** — сохранение textarea/input/JSON/промптов и key-drafts на всех
конфиг-вкладках восстановлено; тесты проверяют панель в каждой ветке. Открытых Critical/High/Medium/Low нет.
Гейты **T-1904** (живая UI-приёмка) и **T-1931** (Справка) остаются ⏸ HUMAN PENDING.
