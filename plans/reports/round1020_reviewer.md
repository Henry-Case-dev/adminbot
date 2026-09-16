# Отчёт @Reviewer — эпик `round1020` (Летописец / RAG-refactor / UX-UI / Agentic AI / Справка UI)

- **Step 5 стrict-workflow:** строгий QA + security-ревью фаз **B, C, D, E, G, H**; закрытие гейтов
  **T-1885, T-1893, T-1904, T-1912, T-1927, T-1931**.
- **Дата:** 16.09.2026. **Baseline при планировании:** HEAD `2f3e1f0`, pytest 6326.
- **Ревьюируемое состояние:** рабочая копия (91 изменённый файл, 8 новых: `services/canonical_context.py`,
  `services/context_middleware.py`, `services/lore_compiler_service.py`, `services/reply_postprocess.py`,
  `tests/*round1020*`). Код не правился (@Reviewer), кроме служебных отметок гейтов в `tasks.md`.

---

## 1. ВЕРДИКТ

**ВЕРДИКТ: Approved**

Critical/High дефектов не обнаружено. Все гейтовые DoD выполнены, полный тестовый прогон зелёный,
JS-гейты чистые, каноны промптов атомарны и синхронны, миграции идемпотентны, меню мини-аппа не изменено,
R17-скан чист. Ниже — Medium/Low наблюдения (не блокируют деплой) и остаточные риски.

---

## 2. Сводная таблица гейтов

| Гейт | Содержание | Статус | Основание |
|---|---|---|---|
| **T-1885** | Ревью B: DoD БЛОК 0/2/5, R16-аддитивность, канон-атомарность, каталог-Δ (+1 tz), R17, prompt-cache | ✅ **PASSED** | 14 точек подачи контекста + генерируемый инвентарный тест; `strip_context_header` в E1/F2; Time Injection первым user-блоком (system статичен); `limits.chat_timezone` (+1); снапшоты точек 2/3/8/13 обоснованы |
| **T-1893** | Ревью C: DoD «Летописца», роутинг, канон, R16/R17, каталог-Δ, отсутствие бампа `user_version` | ✅ **PASSED** | 8 тулов; `compile_lore_story` + `lore_stories` без бампа (PRAGMA 11/12 в зависимости от фазы); `LORE_STORY_SYSTEM_PROMPT` синхронен с canon; UPD-механика; флаг default ON |
| **T-1904** | Ревью D + ⏸ живая приёмка UI (десктоп/Android/Nekogram), кнопка manual DeepDream | ⏸ **CODE PASSED / HUMAN PENDING** | Снимок навигации 25 вкладок + 6 nav + 12 карточек неизменны; 3 критич. бага закрыты; досье/тикер/glass/grid/sticky/labels/аккордеон; **живая верификация владельцем — не выполнена** (⏸, не закрываю) |
| **T-1912** | Ревью E: DoD фактчека/техдолга, канон, R17 (retention-логи без путей) | ✅ **PASSED** | `factcheck_tools()` (3 тула) + DI; S10.19-15 `key_status` ровно 1×; S10.19-23 fsync каталога; retention по снапшоту; вывод без путей |
| **T-1927** | Ревью G: DoD БЛОК 7, канон-атомарность 7.2c, миграционная матрица, R16/R17, каталог-Δ не вырос | ✅ **PASSED** | `ToolLoopResult` fail-safe; `LLMChatResult.reasoning` аддитивно; stripper 5 тегов; middleware header-safe; v11→v12 идемпотентно + PG no-op; EN 8/8; каталог **439/92/20** = +2 |
| **T-1931** | Ревью H + ⏸ приёмка «Справки» владельцем (стиль/актуальность) | ⏸ **CODE PASSED / HUMAN PENDING** | `INFO_CANON_VERSION` 2→3, снипшоты v1/v2, байт-зеркало `info_text.md`, Летописец/Фактчек/Безлимиты; **приёмка владельцем — не выполнена** (⏸) |

> T-1913…T-1917 (Фаза F) не трогались.

---

## 3. Запуски (фактические цифры)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv/Scripts/python.exe -m pytest tests/ -q --timeout=300` | **6523 passed, 1 warning, 0 failed** (88.55s) |
| Синтаксис JS | `node --check web/app.js` | OK |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` |
| Vue mount | `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` |
| Round1020 UI | `node tests/js/round1020_ui_test.js` | `JS-UNIT-OK` (64 assert) |
| Целевые round1020 | 6 новых файлов | **187 passed** |
| Diff whitespace | `git diff --check` | clean (exit 0) |
| Компиляция сервисов | `compileall services` | OK |

> Примечание: первый прогон pytest в этой сессии наткнулся на таймаут в **teardown** немодифицированного
> `tests/test_summary_memory.py` (закрытие aiosqlite-соединения). Повторные прогоны (полный и точечный
> 79 passed) завершаются штатно — флак среды win32, к round1020 не относится.

---

## 4. Проблемы

### Critical / High
**Нет.**

### Medium (не блокируют деплой, рекомендуется трек)

1. **`LoreCompilerService._trim` режет строку посимвольно, включая канонический заголовок.**
   Файл: `services/lore_compiler_service.py:241-257` (`_trim`, ветка `out.append(text[:room])`).
   Последняя влезающая строка может быть обрезана посередине `[ts | Автор | id]:` — LLM получит
   полу-заголовок. На доставку пользователю не влияет (влияет только на вход синтеза), но противоречит
   духу «метаданные неприкосновенны».
   **Требуемый фикс (не блокирующий):** использовать `context_middleware.truncate_keep_header` либо
   просто отбрасывать невлезающую строку целиком (`break` без `text[:room]`).

2. **`DatabaseService.lore_graph_slice` сканирует узлы чата под капом `_LORE_NODE_SCAN_LIMIT=2000` по `id`.**
   Файл: `services/database.py` (`lore_graph_slice`, `SELECT ... FROM nodes WHERE chat_id=? ORDER BY id LIMIT 2000`).
   Для чата с >2000 узлами узел топика может не попасть в скан → пустой граф-срез при непустой хронологии
   (функциональная неполнота, не ошибка). Спека §3.2 предписывала реюз `limits.dig_graph_hop_depth` — здесь
   использован код-константный кап.
   **Требуемый фикс (не блокирующий):** вынести кап в каталог/`hot` или явно задокументировать ограничение
   в каноне инструмента.

3. **`dossier_feed` при GLOBAL использует `ORDER BY RANDOM()` без индексов.**
   Файл: `services/database.py:dossier_feed` + `web/api/oversight.py::dossier_feed`.
   При `chat_id=None` — полный скан `graph_facts` + сортировка, вызывается каждые 45 с (поллинг тикера).
   На больших таблицах — избыточная нагрузка. Доступ — только global admin.
   **Требуемый фикс (не блокирующий):** ограничить выборку (подзапрос по `id`-диапазону/`LIMIT` до `RANDOM()`)
   или кэшировать выдачу.

### Low

4. **Инвентарный паттерн точки `direct_rag` не покрывает обогащённую Tier-A форму T-1924.**
   `services/canonical_context.py:120-123` (`CONTEXT_POINTS.direct_rag.pattern` ожидает `... ] `),
   тогда как при наличии provenance строка становится `[label] [ММ.ГГГГ | Автор | fact:ID]: текст`
   (`summary_memory._format_origin_labeled_line`). Тест-сэмпл использует 4-кортеж → гэп покрытия,
   не рантайм-баг (обогащённая форма несёт метаданных больше). Рекомендуется добавить сэмпл с 6-кортежем.

5. **`escape_lore_html` пропускает `<a href="javascript:...">`.**
   `services/smartmodule_utils.py:_LORE_HTML_TAG_RE`. В Telegram JS не исполняется, в мини-аппе истории
   не рендерятся (досье/тикер используют `{{ }}`-интерполяцию, `v-html` — только sanitized Справка/Гайд).
   Практической уязвимости нет; при переносе историй в TMA обязательно пропускать через DOMPurify/sanitize.

6. **Устаревшие докстринги/метаданные (не влияют на поведение):**
   - `tests/test_database.py:565` — «user_version остаётся 10», фактически assert == 12;
   - `tasks.md` T-1901 «REGISTRY=438», фактически **439** (тест `test_counters_not_grown` — 439, корректно);
   - `spec.md` §19 указывает зеркало `plans/docs/info_text.md`, фактический сид — корневой `info_text.md`
     (код и tasks.md корректны);
   - `plans/MEMORY.md` — «код не тронут, впереди Step 4 @Builder» (фазы B–H фактически реализованы).

7. **RBAC `PUT dossier`:** доступ через `_require_chat` → `can_access_chat` (global/local admin, moderator).
   Право записи у moderator — как у существующих relations-write. **Новой эскалации нет**, вне скоупа 10.20.

8. **R17-долг (пре-существующий, не внесён round1020):** в `plans/MEMORY.md` и `plans/backlog.md` присутствует
   18-символьный SSH-хост-токен (был в HEAD до раунда; `current_task.md` — untracked и в `.gitignore:70`).
   Значение не цитирую. Новые файлы/отчёты круг-1020 чистые.

---

## 5. Проверка Definition of Done (§5 tasks.md)

| Пункт DoD | Статус | Доказательство |
|---|---|---|
| Отчёт Фазы A + Human Gate A | ✅ | `plans/reports/round1020_llm_engine_audit.md` (32.9 KB) |
| Метаданные во всех путях, не режутся капом | ✅ | 14 точек, `representation`+`pattern`, header-safe `truncate_keep_header` |
| Роутинг EN + строгая типизация | ✅ | `test_all_eight_descriptions_are_english`, `additionalProperties:false` ×8 |
| ASC у всех RAG-потребителей; `/summary` архив≠свежее; dig не счётчиком | ✅ | `sort_by_timestamp=True` ×8, `order_rag_facts_asc`, JSON-контракт dig |
| Time Injection первым user-блоком, cache не сломан; `-1` → «Безлимит (∞)» | ✅ | `payload_builder.build_messages(time_line=…)`, `test_system_static_between_calls` |
| `compile_lore_story` (8 тулов), UPD, HTML-доставка, флаг default ON | ✅ | `test_lore_compiler_round1020` (29), `_send_direct_answer(lore=…)` |
| `lore_stories` без бампа `user_version` | ✅ | `CREATE IF NOT EXISTS`, PRAGMA не растёт от неё |
| Agentic AI: fail-safe, reasoning, middleware, `graph_facts` v12 | ✅ | `test_agentic_ai_round1020` (44) |
| UI: баги/досье/тикер/glass/grid/sticky/labels/аккордеон; меню НЕ изменено | ✅ | `test_webapp_round1020_ui` (23) + JS 64 assert + снимок навигации |
| Фактчекер: тулы + промпт + техдолг | ✅ | `test_factcheck_tools_round1020` (25) |
| Справка v3, стиль сохранён, бамп+слепок | ✅ | `test_help_ui_round1020` (15) |
| SPEC_READY владельцу ДО деплоя | ⏸ | T-1913 (Фаза F) |
| pytest 0 failed, JS-гейты, каталог-Δ, R17, `git diff --check` | ✅ | см. §3 |
| Живая верификация человеком (UI/Летописец/Справка/DeepDream) | ⏸ | T-1904/T-1931/T-1913 |

---

## 6. Проверка инвариантов

| Инвариант | Итог |
|---|---|
| **Prompt Caching** (system статичен, время — первый user-блок) | ✅ `build_messages` не трогает system; `test_system_static_between_calls` |
| **D206 / ASC** (состав top-K не меняется, порядок хроно) | ✅ `order_rag_facts_asc`, D206-тесты зелёные |
| **R42/R46** (XML-структура саммари/RAG) | ✅ байт-инвариант структуры, тесты зелёные |
| **R16** (аддитивность: id-ключ, новые поля с дефолтами) | ✅ 3/4-кортежи валидны, kwargs с дефолтами, `prepare`-совместимо |
| **Меню-freeze** | ✅ TABS 25 / navbar 6 / MODULES 12 не изменены (diff + тест) |
| **`TOOL_MAX_ROUNDS` / `llm_client.generate_chat`** | ✅ лимит = 4 не менялся |
| **Порядок роутеров `bot.py`** | ✅ `dp.include_router` не тронут; `setup_factcheck` перенесён (только DI) |
| **`parse_mode` глобально `None`** | ✅ локально HTML только при `ctx.lore_compiled`, фолбэк plain |
| **S10.19-13 sentinel** (`0` не задано / `-1` безлимит до ceiling) | ✅ `_apply_context_budget` семантика не изменена, тесты зелёные |
| **Каноны промптов** (код + canon + `PROMPT_MIGRATIONS` + слепки, один коммит) | ✅ `PREV_CHAT_R2020`/`PREV_FACTCHECK_R2020`/`PREV_R2020_SUMMARY` байт-идентичны HEAD; `LORE_STORY` — новый, в `architecture.md` (без PG-сида — прецедент LORE_MERGE/INIT) |
| **Каталог-Δ** | ✅ санкционированный: REGISTRY 437→**439**, GROUPS 92, TAB_RULES 20, fields 407→409 (flags +1, limits +1) |

---

## 7. Security-выводы

- **SQL-инъекции:** все новые запросы параметризованы (`lore_graph_slice`, `lore_dense_dialogs`,
  `search_messages_fts_count_by_author`, `get/upsert/delete lore_story`, `dossier_*`). Динамические
  плейсхолдеры (`","join("?"*n)`) формируются из длин списков, не из значений. ✅
- **XSS в мини-аппе:** досье/тикер выводятся через Vue-интерполяцию `{{ }}` (экранирование), `v-html`
  новых точек не добавлялось; `v-html` остаётся только для sanitized Справки/Гайда. ✅
- **HTML-доставка Летописца:** `escape_lore_html` экранирует всё вне whitelist; при `TelegramBadRequest`
  — plain-фолбэк с исходным текстом. Риск `<a href="javascript:">` не эксплуатируется в Telegram (Low #5). ✅
- **RBAC:** новый API досье — `_require_chat`; тикер — `requires_global_admin()`. Эскалации от фикса
  `openModuleWindow` нет: запись гейтится per-item `canEditConfig`, модалка открывается read-only. ✅
- **R17:** `plans/current_task.md` untracked + `.gitignore:70`; скан новых/изменённых файлов не выявил
  секретов/токенов/паролей; логи (`tool_loop`, `lore_compiler`, `retention`) содержат только числа/имена
  тулов/длины. Retention-вывод без путей (`archive=yes/no`). ✅
- **Retention при живом боте:** dry-run по временному SQLite-снапшоту (backup API), `--apply` —
  `initialize_existing()` без DDL (WAL/busy_timeout). ✅
- **Миграция `graph_facts` v11→v12:** guard `PRAGMA table_info`, `ADD COLUMN` без пересборки FTS/vec,
  PG — no-op (phantom-таблица не создаётся). ✅

---

## 8. Осознанно принятые обновления снапшотов

1. **Точки 2/3/8/13** БЛОК 0 (канонизация): `test_direct_chat.py`, `test_epic65.py`,
   `test_recent_history_tool_round1015.py`, `test_direct_chat_prompts.py` — канонический префикс
   `[ts | Автор | ID | Переслеано]:`; замер `facts=80→80, chars=3800→6492` зафиксирован.
2. **`user_version` 11→12** в тестах БД/миграций (каскады, `test_database.py`, `test_graphrag_*`,
   `test_history_migration_v7`, `test_hotfix_jsonb_types` и др.) — реальная миграционная ступень, не «подгонка».
3. **dig_into_lore plain→JSON**: 8 снапшотов `test_tool_router.py` — смена контракта по спеке §4.3.
4. **EN-схемы 8 тулов**: `test_tool_schemas.py` — ревизия канона 3.3 (T-1925).
5. **Счётчики каталога** (+2 ключа, N текстов): `test_param_catalog.py`, `test_webapp_round1020_ui.py` — санкция О3/О4.
6. **Справка v2→v3**: `test_info_service`, `test_guide_round1015`, `test_info_handlers`,
   `canon_delivered_version`-маркеры (`test_config_cache`, `test_hotfix_jsonb_types`, `test_webapp_api`) — T-1929.
7. **Модальные ✕ 4→5** (`test_webapp_round1010_ui`, `test_webapp_avatars_ui`) — новая модалка досье.
8. **round-limit degradation**: 3 теста, ассертившие `LLMBadResponseError` на лимите раундов, переведены
   на degraded-контракт (BLOCK 7.1) — осознанно, эталоны пустого финала сохранены.

**Не обновлялись и остались байт-инвариантом:** `<chat_history>` XML-структура, legacy-RAG
`<context>/<user_gossip>/<bot_knowledge>`, D206-порядок, R42/R46-эталоны.

---

## 9. Остаточные риски / что сделать до деплоя

**Блокирующих фиксов нет.** Перед деплоем:

1. ⏸ **Живая приёмка владельцем (T-1904/T-1931/T-1913):** UI-сценарии (десктоп/Android/Nekogram),
   реальный вызов «Летописца» (первый + повторный → UPD/Свежак), кнопка «Форсировать глубокий сон»,
   тексты Справки; зафиксировать «меню не изменено».
2. **SPEC_READY (T-1913):** показать пайплайны фаз B/C/E/G/H, флаг default ON, Δ каталога +2,
   миграцию v11→v12, локальный `parse_mode=HTML`.
3. **@Scanner-аудит (T-1915)** → `round1020_scanner_audit.md` (0 Critical/High).
4. Рекомендательно (не блокирует): Medium #1 (`_trim`), #2 (кап скана узлов), #3 (`RANDOM()`),
   Low #4 (паттерн `direct_rag`), Low #6 (докстринги); синхронизировать `plans/MEMORY.md`.
5. **@DevOps:** git pull --ff-only + restart; проверить миграцию v12 на прод-БД (`PRAGMA user_version`),
   первый прогон `python manage.py retention` (dry-run) при живом боте; пароль SSH в репо НЕ хранить.

---

## 10. Отметки гейтов в `tasks.md`

- **Помечены `[x]`:** **T-1885, T-1893, T-1912, T-1927** (код-ревью фазы B/C/E/G пройдены).
- **НЕ помечены (⏸):** **T-1904, T-1931** — требуют живой приёмки владельцем (UI / Справка), закрывать
  без вердикта владельца нельзя.
- **T-1913…T-1917 (Фаза F) не трогались.**
